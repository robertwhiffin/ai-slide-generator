# Generation Atomicity – stop, rollback and the write fence for Agent-deck turns

An Agent-deck turn is all-or-nothing. The sender can stop it, and a stop, a failure, a timeout or a lost process puts the deck, the Spec, the chat and the session fields back as they were when Enter was pressed. This page explains the snapshot that makes that possible, the fence that stops an abandoned turn's writes, the rollback, and the locks that keep other people out while a turn runs.

Line numbers below were checked at the commit that last changed this page. If they drift, find the code by function name.

---

## 1. Scope

| Path | Atomic? | Why |
|---|---|---|
| `POST /api/chat/async` on an Agent deck (`engine_mode == "graph"`) | Yes | The only path this page covers. |
| Legacy decks (`deck_mode = "legacy"`, engine `"monolith"`) | No | Unchanged. The monolith takes its old code path, apart from the accepted deltas in §11.6. |
| MCP jobs | No | Their payload has no `engine_mode` key, so they run on the monolith (`job_queue.process_chat_request`). |
| `POST /api/chat/stream` (SSE, dev only) | No | No request row, no snapshot, no fence. The synchronous `POST /api/chat` was retired (#382); `test_app_wiring` pins that it stays gone. |
| The arc-review sweeper's own graph turns (`spec_sync.run_arc_review`) | No | No request id is bound, so the fence issues no SQL. |

Every rule below keys on `payload["engine_mode"] == "graph"` or on the presence of a snapshot, never on "a request id exists".

Request statuses: live is `pending` or `running` (`generation_fence.LIVE_STATUSES`). Terminal is `completed`, `error` or `cancelled`. `chat_requests.rollback_outcome` is `rolled_back`, `kept_foreign_change`, `restore_failed` or NULL. `GET /api/chat/poll` returns it as `rollback`.

---

## 2. The lifecycle of one turn

1. **Enter** (`routes/chat.py::submit_chat_async`):
   - The permission check runs, including the owner's async gate (§7.3).
   - The route takes the session lock (`acquire_session_lock`), creates the `chat_requests` row (`pending`) and binds the lock to it (`bind_session_lock`).
   - The engine is decided read-only from the stored Deck Mode (`get_deck_mode`). On an Agent deck, `begin_generation` takes the snapshot (§3) in one transaction, under the deck row's `FOR UPDATE` (the owner's `user_sessions` row on a deck with no row yet), once it has checked that no other generation is live on the deck (§7.4).
   - Then the user message is written (`add_user_message`, tagged with the request id). On a first message this locks the Deck Mode.
   - The engine is resolved again and the job is enqueued.
2. **Queue.** If the turn is stopped while queued, the rollback has already ended it. `start_chat_request` (`pending` → `running`, conditional) then returns False, and the job runs nothing and writes nothing.
3. **Graph.** `chat_service._send_message_streaming_graph` runs `invoke_graph` in its own thread. `invoke_graph` binds the request id in a ContextVar and in `config["configurable"]["chat_request_id"]` (`graph/builder.py`). Every turn write is fenced (§4).
4. **Consumer.** The job's generator checks `turn_is_live` at least once every `STOP_POLL_SECONDS` (1 s), whether or not events arrive. If the turn has ended in the database, it raises `TurnStopped`. The job then frees its runner straight away, while the graph thread may still be blocked in a model call.
5. **Seal (the commit point).** After the graph thread finishes, `seal_generation` claims the request row and moves the snapshot from `active` to `sealed` (§6). This happens before the save point and the title join.
6. **Save point.** `create_save_point(..., request_id=...)` writes "Generated N slide(s)" (fenced).
7. **Complete.** `session_manager.complete_chat_request` claims the row, stores the result, marks it `completed` and deletes the snapshot, all in one transaction. The job's `finally` then releases the session lock, matched on the request id.

---

## 3. The snapshot

Table `generation_snapshots` (`src/database/models/generation_snapshot.py`) holds one row per request (`request_id` is unique). It is created by `_migrate_generation_snapshots` and written by `generation_rollback.take_generation_snapshot` inside `begin_generation`'s transaction.

| Field | What it holds |
|---|---|
| `actor_session_pk`, `owner_session_pk` | The sender's session, and the deck owner's (the same row unless a contributor sends) |
| `deck_present`, `deck_columns_json` | Whether the owner had a deck row, and its `DECK_CONTENT_COLUMNS`: `title`, `html_content`, `scripts_content`, `slide_count`, `deck_json`, `verification_map`, `deck_spec_json`, `css`, `external_scripts_json`, `head_meta_json`, `modified_by` |
| `slide_rows_json` | Every `session_slides` row of the owner, every column |
| `session_fields_json` | Owner: `deck_mode`, `graph_release_id`, `title`. Actor: `title`, plus the Genie One entry's `conversation_id` and each Genie Agent (`genie`) entry's `conversation_id`, by `space_id`. The restore writes back only those ids, and only on entries that still exist |
| `checkpoint_id` | The actor thread's newest LangGraph checkpoint |
| `mutation_watermark` | `max(shared_deck_mutation_event.id)` for the deck: the line that detects someone else's change |
| `state` | `active`, `sealed` or `restore_failed` |

**Not snapshotted, and why:**
- **Chat messages.** Every row the turn writes carries its `request_id` (the user message too), so the rollback deletes them by request id.
- **Checkpoints.** The rollback deletes everything after `checkpoint_id` (`delete_checkpoints_after`, all namespaces).
- **`deck_reviews`.** These are content-addressed by `(deck_id, deck_digest)`, so a review written during a stopped turn stays valid for identical content. On a first-generation rollback they go with the deck row through `ondelete="CASCADE"`.
- **Image Library assets, usage and cost rows, MLflow traces, `shared_deck_mutation_event` rows.** These are kept on purpose. Mutation events are append-only.

**"Identical" after a restore** means every content column and every slide row is equal. Three columns are excluded: `session_slide_decks.version`, which is bumped so open clients and other processes reload; `updated_at`; and `user_sessions.last_activity`.

The snapshot costs about two copies of the deck per Agent Enter. It is deleted when the turn ends.

---

## 4. The fence

`src/services/generation_fence.py`.

```python
fence_turn_write(db, request_id=None, *, allow_completed=False)   # raises TurnFencedError
raise_if_turn_ended(request_id=None)                              # raises TurnFencedError (read-only)
claim_turn_row(db, request_id) -> bool                            # the claim itself
turn_is_live(request_id) -> bool                                  # read-only, own session
```

- **The claim** is `UPDATE chat_requests SET status = status WHERE request_id = :rid AND status IN ('pending','running')`. It matches only while the turn is live, and it takes the row lock (on SQLite, the database write lock).
  - A rollback that cancels the row waits for any writer that has already claimed it.
  - A writer that arrives after the cancel matches nothing and raises `TurnFencedError`.
- **No request id means no SQL.** This covers the explicit argument, the ContextVar and the checkpointer's config. That is why the monolith, MCP, SSE and the sweeper are untouched.
- **`allow_completed=True`** also admits a `completed` turn. Only the title thread uses it, because a slow title can land just after completion. It still refuses `cancelled` and `error`.
- **Where the request id comes from:**
  - Graph nodes, including the `Send`-fanned slide pipelines, read the ContextVar.
  - The checkpointer reads `config["configurable"]["chat_request_id"]`. LangGraph calls `put_writes` for fanned tasks outside the task's context, where the ContextVar is None.
  - The title thread and the save point pass `request_id` explicitly. Their contexts were copied before `invoke_graph` bound it.
  - The image-generation pool copies the node's context into each job (`contextvars.copy_context().run`).
- **`raise_if_turn_ended`** is the fence's read-only twin. It goes before a **model call that no fenced write precedes**, so an abandoned turn stops before paying for that call.
  - It takes no lock. A stop that lands just after it is still refused by the next fenced write.
  - An unreadable status counts as live, for the same reason.
  - Its call sites are listed in §9. One of them is the runtime's tool loop, which checks before every round after the first: a read-only tool (a Gateway answer with no image, the brand search) writes nothing, so without the check a stop during its call would still pay for the next round.
- **Two exceptions, two sides:**
  - `TurnFencedError` is raised on the graph side, by a writer or a check.
  - `TurnStopped` is raised on the job side, by the consumer loop or a seal that lost.
  - The abandoned graph thread never sees `TurnStopped`. When it ends on `TurnFencedError`, or on any error once its turn is no longer live, it is logged at INFO as "Abandoned graph turn ended" (`chat_service.py`, `abandoned()`), with no error recorded and no ERROR event.

**What the fence does not stop:** a model call, or a tool call, that is already in flight when the stop lands. It finishes, and the model call is paid for. The turn then ends at whichever comes first: the tool loop's next round, the next fenced write, or the next `raise_if_turn_ended`.

---

## 5. Rollback

`generation_rollback.roll_back_generation(request_id, *, terminal_status, error_message, refuse_on_foreign_change) -> RollbackResult`

Everything happens in **one transaction**, in this order:

1. **Claim.** `claim_turn_row` runs first. If the turn is not live (finished, already rolled back, unknown), the result is `NOT_LIVE` and nothing is written.
2. **No snapshot** (a monolith request): end the request, release its lock (matched), `NO_SNAPSHOT`.
3. **Sealed snapshot:**
   - A stop is too late. The result is `NOT_LIVE` and nothing changes.
   - A failure, timeout or orphan keeps the finished deck: `error`, snapshot dropped, lock released, `SEALED_KEPT`.
4. **Lock.** `_lock_deck` locks the actor and owner `user_sessions` rows (`FOR UPDATE`, in id order), then the owner's `session_slide_decks` row.
5. **Orphan sweep only** (`spare_newer_turn`): if the sender's lock is bound to a *different* live request, the orphan is ended without a restore and the deck is kept (`KEPT_NEWER_TURN`). Restoring there would wipe the newer turn's starting point.
6. **Foreign change.** This is a mutation event on the owner's deck after the watermark whose actor is not this turn's sender (a NULL actor counts as foreign).
   - With `refuse_on_foreign_change` (a stop), nothing is written and the turn carries on (`REFUSED_FOREIGN_CHANGE`).
   - Otherwise (a failure) the deck is kept as it stands, the request is ended with `kept_foreign_change` and the snapshot is dropped (`KEPT_FOREIGN_CHANGE`).
7. **Restore, in a SAVEPOINT** (`db.begin_nested()`):
   - The session fields come back first, then the deck row and every slide row (delete and re-insert). A deck row the turn created is deleted.
   - The turn's messages are deleted, and the checkpoints after the recorded id.
   - The request is ended with `rolled_back`, the snapshot deleted and the lock released (matched).
   - One `restore_version`/`deck` mutation event is appended when a deck existed before Enter.
   - Result: `ROLLED_BACK`.
8. **The restore raised.** The savepoint rolls back, and the **same** transaction marks the snapshot `restore_failed` (only if it was still `active`) and the request `restore_failed`. Its `error_message` becomes the restore-pending copy. The deck-row lock is held throughout, so an Enter queued on the deck sees the pending restore, never a half-built deck. The session lock stays held. Result: `RESTORE_FAILED`.

Anything else that raises rolls the whole transaction back and propagates. The turn is then still live, so a later stop, timeout or orphan sweep ends it.

After commit, the process drops its own cached decks for the touched sessions. Other processes reload on the version bump, or drop a deck whose row is gone (§11.3).

### 5.1 Triggers

| Trigger | Where | Call | Notes |
|---|---|---|---|
| **Stop** | `POST /api/chat/cancel/{request_id}` (`routes/chat.py::cancel_chat`) | `cancelled`, no message, `refuse_on_foreign_change=True` | Only the sender may stop (404 unknown, 403 anyone else). A live turn with no snapshot answers 409 `not_stoppable`. `ROLLED_BACK` gives `{"outcome":"cancelled","status":"cancelled"}`. `NOT_LIVE` gives `{"outcome":"already_finished","status":<status>}`, and after a seal that status can still be `running`, so the client keeps polling. A foreign change is a 409 `refused_foreign_change`. A failed restore is a 500. |
| **Failure** | `job_queue.process_chat_request`, `except Exception` and the pinned-config clause | `error`, `str(e)` or `PINNED_GRAPH_CONFIGURATION_ERROR`, refuse False | With no snapshot left (a stop got there first), `fail_chat_request` writes `error` only while the turn is live. |
| **Enter failure** | `submit_chat_async` | `_roll_back_failed_enter`: `error`, refuse False | `DeckModeLockedError` and the engine mismatch **discard** the snapshot instead (C9), because the write that locked the mode is someone else's. If the discard raises, the request is ended (`fail_chat_request`). If the rollback raises or its restore fails, the lock is kept for the orphan sweep. |
| **Timeout** | `job_queue.mark_timed_out_jobs_once` (every 60 s) | `error`, "Generation exceeded maximum duration (20 minutes)", refuse False | Graph limit `GRAPH_JOB_HARD_TIMEOUT_SECONDS = 1200`, keyed on the in-memory `started_at`. |
| **Orphan / restart** | `generation_rollback.recover_orphaned_generations`, run by the 60 s loop and at startup (`recover_stuck_requests`) | `error`, "Generation interrupted", refuse False, `spare_newer_turn=True` | An orphan is a live request with an `active` or `sealed` snapshot whose sender's session lock is no longer bound to it (NULL-safe) or has not been refreshed for `ORPHAN_AFTER_SECONDS = 180` (three missed 60 s heartbeats). |
| **Stuck at startup** | `job_queue.recover_stuck_requests` | `error`, `CRASH_RECOVERY_ERROR`, refuse False | Runs after the orphan sweep, for requests still `running` that were created more than 1200 s ago. Those without a snapshot are failed as before (`_fail_stuck_request`). |
| **Retry** | `recover_orphaned_generations` → `_retry_restore` | — | Each `restore_failed` snapshot is claimed by a no-op UPDATE on its own row, then the foreign-change check runs again (C11). The result is `ROLLED_BACK`, `KEPT_FOREIGN_CHANGE`, or `DECK_GONE` (the owner's session was deleted). If only the actor's session is gone, the owner's side is restored. Unless the deck is gone, the request keeps its status, its `error_message` is cleared and its `rollback_outcome` becomes final; the snapshot is deleted and the lock released. A retry that raises changes nothing and is tried again next sweep. |

A stop and a completion race on the same claim: `seal_generation`, `complete_chat_request` and the rollback all claim the request row first, so exactly one of them wins (`test_complete_and_cancel_race_has_one_winner`).

---

## 6. The commit point: sealing

`seal_generation(request_id)` runs as one transaction: it claims the request row, then runs `UPDATE generation_snapshots SET state='sealed' WHERE request_id=… AND state='active'`.

- It is called once the graph thread has finished, **before** the save point and the title join.
- If the seal loses (the turn is no longer live, or the snapshot is not `active`), the consumer raises `TurnStopped`. There is no save point and no `COMPLETE`.
- A live graph turn with no snapshot is sealed vacuously, with a WARNING, so it is never left in `running`.
- After the seal, a stop is `already_finished`. A failure, timeout or orphan keeps the finished deck (`SEALED_KEPT`). A stopped turn can therefore never leave a "Generated N slide(s)" save point behind, and a sealed turn is never rolled back.

---

## 7. Lock rules

### 7.1 The session (processing) lock is request-owned

- **Columns:** `user_sessions.is_processing`, `processing_started_at` and `processing_request_id`.
- **Acquire:** `acquire_session_lock` (`SELECT … FOR UPDATE`). The lock is stale after `SESSION_LOCK_TIMEOUT_SECONDS = 300`. `bind_session_lock` then records the owning request straight after `create_chat_request`.
- **Release:**
  - A graph turn releases only a lock it still owns: `release_session_lock(session_id, request_id)`, one conditional UPDATE. The job's `finally` releases only if the turn started, and either it completed or its snapshot is gone. A `restore_failed` snapshot keeps the deck locked to its sender until the retry.
  - The monolith and MCP release unconditionally, as before.
- **Refresh:** `refresh_job_session_locks_once` (every 60 s) refreshes each lock this process holds. A graph entry refreshes only while the lock is bound to its own request. The orphan sweep reads exactly this heartbeat.
- **Rollback:** the rollback releases the lock, matched, in its own transaction. The exceptions are `RESTORE_FAILED` (kept) and `KEPT_NEWER_TURN` (the newer turn owns it).

### 7.2 A live generation holds the editing lock

`SessionManager._live_generation_holder(db, deck_owner, *, live_only=False)` returns the `created_by` of the newest snapshot on the deck whose request is live or, unless `live_only` is set, whose state is `restore_failed`.

- `require_editing_lock`, `acquire_editing_lock` and `get_editing_lock_status` consult it **before** the heartbeat lock (`locked_by`/`locked_at`, 45 s). While a generation is live, only its sender can edit.
- A monolith turn writes no snapshot, so it holds nothing.

### 7.3 The owner's async gate

`_check_chat_permission(..., gate_owner_on_generation=True)` is passed **only** by `POST /api/chat/async`.

- The deck owner gets a 423 when **another** user's **live** generation holds the deck (`live_generation_holder(..., live_only=True)`).
- An idle contributor's heartbeat lock never blocks the owner.
- A pending failed restore falls through to submit's restore-pending 409.
- `/api/chat/stream` is unchanged (`test_owner_gate_applies_only_to_the_async_route`). The synchronous `/api/chat` no longer exists (#382).

### 7.4 Enter refusals and the arc-review sweeper

- `begin_generation` takes the owner's deck row `FOR UPDATE` first. A deck with no row yet (a first generation) has nothing else to queue on, so it locks the owner's `user_sessions` row instead. Then it refuses in three cases:
  - **another request's generation is live on the deck** (`GenerationRefusedError.GENERATION_IN_FLIGHT`). The route answers 423 `Session is locked by <display name>`, the same as the holder checks, ends the request `error` and releases its session lock (matched). Those checks (§7.3, and the contributor's `require_editing_lock`) run before this lock, so the owner and a contributor, each in their own session, could both pass them in the few round trips before either snapshot committed. The re-check is a fresh statement after the lock, so it sees a snapshot that committed while this Enter queued. Only one generation per deck.
  - a failed restore is pending on the deck (409, `RESTORE_PENDING`, detail `RESTORE_PENDING_MESSAGE`)
  - the arc-review sweeper holds a live claim on it (409, `ARC_REVIEW_IN_FLIGHT`)
- `spec_sync.claim_due_marker` excludes busy decks with the **same** rule (`generation_fence.generation_hold_clause`: a live snapshot, or `restore_failed`).
  - The rule is applied in the candidate `SELECT … FOR UPDATE` and re-checked as its own statement once the lock is held.
  - Enter and the sweeper serialise on that deck-row lock.

---

## 8. Lock ordering

In any transaction that writes on behalf of a turn, **`fence_turn_write` is the first lock-taking statement**, before any `with_for_update()` or `UPDATE`, and it runs in the **same** `with get_db_session() as db:` block as the write. A fence in a separate session protects nothing.

The order is:

1. `chat_requests` (the claim)
2. `user_sessions` (in id order)
3. `session_slide_decks`
4. `session_slides` and other rows

The rollback, the seal, `complete_chat_request`, `fail_chat_request` and `abandon_chat_request` all claim first as well. The rollback then takes `user_sessions` before `session_slide_decks`, which is the order every deck writer's flush takes them.

The retry claims its `generation_snapshots` row instead, because the request is already terminal, and then follows the same order.

Enter (`begin_generation`) and the sweeper's claim take no `chat_requests` lock in their transaction: they start at the deck row. Enter holds exactly one row lock: the deck row or, on a deck with no row yet, the owner's `user_sessions` row (never the deck row while it waits for a `user_sessions` row). Everything else before its snapshot INSERT is a read, and it refuses before that INSERT whenever a generation is live or a restore is pending on the deck, which are the only times a rollback or a retry holds that deck's rows. So it never waits on a rollback while holding something the rollback needs.

Only Postgres shows any of this. SQLite ignores `FOR UPDATE`, and the app's SQLite engine (`src/core/database.py`, used for the in-memory unit-test database) is a `StaticPool` with **one shared connection**. Every session's statements run on that connection, in one transaction, so a SQLite test can only drive statement-sequential interleavings, and a `rollback()` in one thread can undo another thread's uncommitted claim. A race test on SQLite (the complete/cancel race, for example) is only partly sensitive for that reason. The real serialisation is proved on Postgres, by observing the blocked backend (`pg_blocking_pids`): `tests/integration/test_generation_fence_postgres.py` the writer/rollback serialisation on the request row, and `test_generation_lock_postgres.py` the Enter/sweeper and Enter/Enter serialisation on the deck lock.

---

## 9. How to add a new turn writer

1. **Fence it.** Open the write's transaction with `with get_db_session() as db:` and call `fence_turn_write(db)` as its first lock-taking statement. Pass `request_id=` explicitly when the code runs outside the graph thread's context: a thread started before `invoke_graph`, a plain `ThreadPoolExecutor`, or a LangGraph callback. A new pool must copy the context (`contextvars.copy_context().run`) or pass the id.
2. **Let the refusal out.** Wherever the call sits inside a broad `except Exception`, add `except TurnFencedError: raise` ahead of it, in nodes and in tools alike. Otherwise an abandoned branch logs a false ERROR, tries another write, or starts another model call. A broad catch around a model call that runs tools needs it too, because the tool loop raises `TurnFencedError` between rounds. The existing sites:
   - `nodes.py`:
     - `:527` `_say`
     - `:2005` placeholder
     - `:2827` edit layout
     - `:4969` architect tool loop
     - `:5358` insert shift
     - `:5704` architect deck-level write
     - `:6129` `_persist_genie_agent_conversations` (one write per Genie Agent, so the first refusal ends it)
     - `:6341` data analyst
     - `:6763` builder
     - `:6942` build reviewer
     - `:7044` stale-fix reconcile
     - `:7195` fixer
     - `:7380` fix reviewer
     - `:7600` draft
     - `:8004` and `:8075` deck reviewer
   - `agent_runtime.py:732` `_answer_tool_call`
   - `agent_tools/registry.py:160` (Genie One's progress row)
   - `agent_tools/genie_agent.py:436` (a Genie Agent's progress row)
   - `agent_tools/gateway_tool.py:166` and `:382` (Gateway services and UC MCP connections: both run as `GatewayMcpAgentTool`)
   - `agent_tools/image_generation_tool.py:271` and `:325`
   - `chat_service.py:2088` (title) and `:2199` (save point)
3. **Check before an unfenced model call.** If the new code can start a model call with no fenced write before it, call `raise_if_turn_ended()` first. The existing sites, all in `nodes.py`:
   - `_write_draft_row` when the position keeps a real slide (`:7589`)
   - the fix round, after its slot is taken (`:7738`)
   - before the fix review (`:7749`)
   - before each serial deck-level re-review call (`:962`)

   And in `agent_runtime.py`, `invoke_with_tools` checks before every round after the first (`:641`). That covers every tool loop: the architect's (Gateway services, its UC MCP connections, the image tool), the data analyst's (Genie One, Genie Agents, its Gateway services and UC MCP connections), and the builder's and fixer's brand search.
4. **Undo it, or say why it stays.** If the rollback must undo the write, either tag the row with `request_id` (as messages are) and delete it in `_restore_turn`, or add the state to `take_generation_snapshot` and restore it in `_restore_turn`. Otherwise add it to §11 with the reason.
5. **Test it** the way `tests/unit/test_generation_fence_writers.py` does:
   - one test where the write is refused after a cancel, and every row of every table is unchanged
   - one where it lands while live, and the claim is the first write statement of the writer's own transaction
   - for a node, one that pins the next model call never starts

---

## 10. Write inventory

This is every DB write a graph turn makes, with its fence. Confirmed with `grep -n "get_db_session\|session_factory\|\.commit(\|db\.add(\|fence_turn_write\|claim_turn_row"` over `src/services/graph/`, `src/services/agent_tools/`, `src/core/checkpointer.py` and the writers below.

### 10.1 Deck rows, deck-level columns, deck review, checkpoints

| Writer (fence) | What it writes | Graph call sites |
|---|---|---|
| `slide_repository.py:147` `SlideWriter.write_slide` (fence `:202`) | `session_slides` upsert; creates the deck row when given a `mutation` and none exists; mutation event | `nodes.py:1797` `_write_reviewed_row` (from `build_reviewer_node:6904`, `_land_original:6982`, `fix_reviewer_node:7369`); `nodes.py:7591` `_write_draft_row` |
| `slide_repository.py:387` `commit_placeholder` → `write_slide` | a placeholder `session_slides` row, plus a mutation event | `nodes.py:1998` `_placehold_failed_position` (from `builder_node:6770`, `build_reviewer_node:6949`, `fix_reviewer_node:7415`, `placeholder_node:7840`) |
| `slide_repository.py:557` `apply_slide_layout` (fence `:622`) | `session_slides` move/delete/insert; `deck_spec_json`, `version`; `user_sessions.last_activity`; mutation event | `nodes.py:2811` `_apply_edit_plan` (architect) |
| `slide_repository.py:441` `insert_pending_slides` → `apply_slide_layout` | as above | `nodes.py:5342` (architect) |
| `slide_repository.py:340` `delete_slide` (fence `:352`) | one `session_slides` row, plus a mutation event | no graph caller; fenced for any future one |
| `deck_level_writer.py:154` `write_deck_level_columns` (fence `:274`) | `session_slide_decks` columns, `version`, `modified_by`; creates the deck row; `user_sessions.title`, `last_activity`; mutation event | `nodes.py:5694` (architect, pre-fan-out); `nodes.py:7981` (deck reviewer) |
| `nodes.py:8065` deck-review save (fence `:8066`) → `deck_review_store.save_deck_review` (`db.add` `:200`) | a `deck_reviews` row (kept on rollback, §3) | `deck_reviewer_node` |
| `checkpointer.py:413` `put` (fence `_fence_from_config` `:201`, first in its session) | `graph_checkpoints` upsert | the LangGraph loop |
| `checkpointer.py:468` `put_writes` (same) | `graph_checkpoint_writes` inserts | `PregelRunner.commit` (fanned tasks too, through `configurable`) |

### 10.2 Messages, progress, session fields, title, save point, images

| Writer (fence) | What it writes | Call sites |
|---|---|---|
| `session_manager.py:2018` `add_message` (fence `:2047`) | a `session_messages` row tagged with the request id | `nodes.py:519` `_say`; `nodes.py:1857` `_surface_notice` |
| `session_manager.py:4594` `record_chat_request_progress` | `chat_requests.progress_json`. Not claimed: the UPDATE is itself conditional on `status IN LIVE_STATUSES` (`:4622`), so a stopped turn's progress is a no-op | `graph/progress.py:247` `_persist` |
| `session_manager.py:1833` `set_genie_one_conversation_id` (fence `:1848`) | `user_sessions.agent_config` (restored: the Genie One `conversation_id`) | `nodes.py:6105` |
| `session_manager.py:1875` `set_genie_agent_conversation_id` (fence `:1892`) | `user_sessions.agent_config`, one `genie` entry, matched on `space_id` (restored: that entry's `conversation_id`) | `nodes.py:6126` `_persist_genie_agent_conversations`, once per Genie Agent whose conversation id changed |
| `session_manager.py:1588/1604` `rename_session` / `update_session` (fence `:1637`, explicit `request_id`, `allow_completed=True`) | `user_sessions.title` (and the deck row's `title`) | `chat_service.py:2074` title thread |
| `session_manager.py:3465` `create_version` (fence `:3496`, explicit `request_id`) | a `slide_deck_versions` row | `chat_service.py:2191` save point, after the seal |
| `image_generation_tool.py:137` `save_to_library` (fence `:145`) → `image_generation.save_generated_image` → `image_service.upload_image` (`db.add` `:97`, `commit` `:98`) | an `image_assets` row (kept on rollback) | `_POOL` job (`:301`, context copied) |
| `gateway_tool.py:306` `make_image_saver.save` (fence `:311`) → `image_service.upload_image` | an `image_assets` row (kept on rollback) | `GatewayMcpAgentTool.run`, in the node's thread (a Gateway service or a UC MCP connection) |

### 10.3 Turn lifecycle (each one conditional on the turn being live)

`start_chat_request` (a conditional `pending` → `running`) and, claiming first, `complete_chat_request` (`session_manager.py:4541`), `fail_chat_request` (`:4570`), `abandon_chat_request`, `seal_generation` and `roll_back_generation`. The Enter-time writes (`create_chat_request`, `bind_session_lock`, the snapshot, `add_user_message`) run in the route before the turn starts. The user message carries the request id, so the rollback deletes it.

### 10.4 Read-only DB access in a turn

- `nodes.py`:
  - `:1049` `_design_system_library`
  - `:1116` `_design_system_logos`
  - `:3773` `_analyst_data_sources`: the Gateway registry read behind the architect's `data_sources` payload key
  - `:4026` the Gateway registry read (`enabled_by_service`), skipped on a deck with UC MCP connections only
  - `:4257` `_image_generation_available`
  - `:4772` the prior deck-review read (`get_deck_review`)
- `_session_contract`, `_conversation`, `list_slides_in_position_order`, `get_slide`, `read_deck_spec` (`deck_level_writer.py:387`), `resolve_streamed_ds_assets`
- `builder.load_collaboration_root`, `load_conversation_pin`, the persisted-release loader
- `agent_resolution`'s slide-style and deck-prompt reads, `ds_asset_tool`, `image_tools.search_images`
- `turn_is_live` / `raise_if_turn_ended` (a SELECT on `chat_requests`)
- The `mcp_transport`, Genie One, Genie Agent (`genie_agent.GenieAgentClient`), Gateway MCP and UC MCP connection (`gateway_mcp.ConnectionMcpClient`) calls are network only. So is the connection listing, which runs on a plain `ThreadPoolExecutor` (`gateway_toolset.build_gateway_tools`) and needs no request id for that reason.

---

## 11. Documented exceptions

### 11.1 Unfenced writes, by ruling (C7)

These writes are global, idempotent caches with no deck, session or turn state. They are neither fenced nor restored. If one lands after a stop, it changes nothing a rollback would restore.

- **`agent_resolution.py:144`:** `ensure_compiled_style_content_current` recompiles a stale `design_systems.compiled_style_content` in place. `get_db_session` commits it on exit.
- **`materialize_templates`** (`design_system_templates.py:682`), reached through `template_sections.resolve_template_bytes` (`:566`, its session at `:618`) and `get_template_for_generation`, self-heals `design_system_templates` rows.
- **`session_manager.get_slide_deck`'s blob backfill** (`deck.deck_json = …`, `:2968`) runs only for a deck with no `session_slides` rows. That never happens mid-turn on an Agent deck, so it is treated as read-only.

### 11.2 The SVG thumbnail commit (Task 3b)

`image_generation.save_generated_image` commits a second time for an SVG (`image_generation.py:763`), to set `thumbnail_base64` on the row it has just inserted. That transaction is not fenced; the fence covers the INSERT's transaction. The UPDATE only touches a row this turn wrote while it was live, and images stay in the library on rollback, so it is harmless.

### 11.3 The deck cache (C12)

`ChatService._get_or_load_deck` validates a cached deck against `get_slide_deck_version`. When that returns None, it asks `slide_deck_exists`, and a confirmed `False` (for example after a first-generation rollback deleted the row) drops the cached deck. Known gaps:

- **Same version, new deck.** The cache can serve a stale deck when the deck is deleted and recreated and reaches the same `version` before this process looks again. The fix is to key the cache on the deck id.
- **Legacy deltas:**
  - A deck held only in the cache because its save failed (no deck row) is now dropped on the next hit, where it used to be served.
  - During a database outage, each cache hit costs one more failing round trip (the existence check), and the cached deck is still served.

### 11.4 Swallowed refusals, accepted

These sites swallow a refusal without ending the node. Each refused write lands nothing, and none of them starts another model call.

- `_surface_notice` (`nodes.py:1814`) logs a WARNING.
- `_persist_genie_one_conversation` (`nodes.py:6099`) logs a WARNING.
- The progress writer (§10.2) is a no-op.

Its Genie Agent twin, `_persist_genie_agent_conversations` (`nodes.py:6116`), lets the refusal out instead (§9). It writes once per Genie Agent, so a swallowed refusal would try every other space's write and log each as a failure.

One broad catch has no re-raise because no refusal can reach it today: `fix_reviewer_node`'s inner model-call catch. The fix reviewer binds no tools, so its call never enters the tool loop, and the tool loop is where a turn is checked between rounds. Binding a tool to the fix reviewer means adding the re-raise there (§9).

### 11.5 Model calls in flight

Neither the fence nor `raise_if_turn_ended` can cancel a call that is already running. A model call in flight when the stop lands finishes and is paid for, and so does a tool call. The turn then ends at whichever comes first:

- the tool loop's next round, which checks the turn before it starts
- the next fenced write
- the next `raise_if_turn_ended`

So after a stop, a turn normally pays only for the calls already in flight. On a mid-build stop that is one per running slide pipeline. In a tool loop it is the round under way, plus the tool call it asks for. Gateway services, UC MCP connections, Genie One, Genie Agents and image tools write a progress row first, so a stopped turn's call to one is refused before it reaches the service. A Genie call that is already polling when the stop lands runs to its answer or its deadline (an answer can take minutes). The brand search is a database read.

One exception: a retry that follows an in-flight call starts without a check, so it can cost one more model call. That covers:
- a parse retry (builder, build reviewer, fixer)
- a safety-gate regeneration
- the architect's retry without tools, or with a rejected edit
- the analyst's retry without its Gateway tools (Genie One and the Genie Agents are rebuilt for it)

### 11.6 Legacy-path deltas, accepted

The monolith (Legacy decks, MCP) takes its old code path, with these deltas. Each was checked and ruled harmless; none changes what a Legacy turn writes.

- **The session lock is bound on Legacy `/chat/async` too.** `bind_session_lock` records the owning request straight after `create_chat_request`, before the engine is known. Once bound, the submit's error exits release the lock matched on that request id instead of unconditionally, which is equivalent because this request holds it. The monolith job's own `finally` still releases unconditionally.
- **`release_session_lock`** is one Core UPDATE that acts, and logs, only when `is_processing` is true.
- **The startup stuck-request release** (`job_queue._fail_stuck_request`) frees the session lock only while it is unbound or bound to that request. It used to free it unconditionally, which could free a newer request's lock; that is visible only after a double crash.
- **503, not 500, when the database is down at Enter.** The read-only `get_deck_mode` that decides the engine fails closed into the engine-unavailable 503.
- **The deck cache** drops a deck whose row is confirmed absent (§11.3, with its two Legacy deltas).
- **Contributors on `/api/chat/stream`** get 423 while someone else's Agent generation is live on the deck, because `require_editing_lock` consults the live holder (§7.2). By ruling.
- **One extra read each:** `_check_chat_permission` now runs in a thread (`asyncio.to_thread`) and the owner's async gate adds a holder query; `require_editing_lock`, `acquire_editing_lock` and `get_editing_lock_status` add a `generation_snapshots` query, which never matches on a Legacy deck.
- **`spec_sync.claim_due_marker`** now selects its candidate `FOR UPDATE`, re-checks it, then claims. Exclusivity is preserved on both backends.

---

## 12. Tests

| File | What it pins |
|---|---|
| `tests/unit/test_generation_fence.py` | the claim, `fence_turn_write`, `allow_completed`, `turn_is_live`, `raise_if_turn_ended` |
| `tests/unit/test_generation_fence_writers.py` | every deck writer's refusal and claim-first placement; `TestAnAbandonedBranchStops` (every re-raise and check in §9) |
| `tests/unit/test_generation_fence_session_writers.py` | messages, progress, the Genie One and Genie Agent ids, title, save point, image saves; a refused tool write (including a Genie Agent's progress row), or a stop during a read-only tool call, ends the tool loop; a refused Genie Agent id write ends the analyst |
| `tests/unit/test_agent_runtime_tool_loop.py` | the loop's check before every round after the first, and no check without a request id |
| `tests/unit/test_checkpointer.py` | the checkpointer fence via `configurable` |
| `tests/unit/test_generation_snapshot_schema.py` | the table and its migration |
| `tests/unit/test_generation_rollback.py` | the snapshot and every rollback outcome, including the Genie One and Genie Agent conversation ids |
| `tests/unit/test_job_queue_rollback.py`, `test_generation_runner_release.py`, `test_generation_recovery.py` | failure, stop, timeout and orphan triggers; the runner freed on stop; retries |
| `tests/unit/test_generation_holds_editing_lock.py`, `test_session_lock_ownership.py`, `test_job_queue_lock_release.py` | the lock rules in §7, including Enter's refusal of a second generation on the deck (service-level, and the race staged through the real route) |
| `tests/integration/test_generation_stop_routes.py` | the cancel and poll routes |
| `tests/integration/test_generation_stop_graph_turn.py` | acceptance through real graph turns: stop in planning, after layout, mid-build; late writes; resend; forced failure; placeholder; the complete/cancel race (one forced seal-first run, then 20 barrier runs); timeout and restart |
| `tests/integration/test_generation_{fence,rollback,lock}_postgres.py` | row locks and ordering on real Postgres, including two concurrent Enters on one deck (owner and contributor, with and without a deck row): only one snapshots |

---

## 13. Cross-references

- `docs/technical/multi-user-concurrency.md`: session locks and the deck cache across workers
- `docs/technical/save-points-versioning.md`: save points and `restore_version`
- `docs/technical/real-time-streaming.md`: the polling transport the stop works through
- `docs/user-guide/01-generating-slides.md`: stopping a generation, from the user's side
- Spec: `docs/superpowers/specs/2026-11-12-interrupt-generation-design.md`
