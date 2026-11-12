# Interrupt Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. In this repo also load `executing-plans-tellr`. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the sender stop a running Agent-deck generation (stop sign or Esc, with a confirmation once builders have started), and make every Agent generation all-or-nothing. A stop, failure, timeout or restart restores the deck, the Spec, the chat and the session fields to the moment Enter was pressed.

**Architecture:**
- `POST /chat/async` writes a `generation_snapshots` row before the user message is saved.
- **Fence:** every write a turn makes first "claims" its `chat_requests` row with a conditional `UPDATE`, which is a row lock on Postgres and the write lock on SQLite. Once the row is terminal (`completed`, `cancelled` or `error`), every later write raises `TurnFencedError`. The one exception is the title thread, which refuses only `cancelled` and `error` (Task 3b).
- **Rollback:** claims the same row, flips it terminal, and restores the snapshot in one transaction, so no turn write can land after it.
- **After a stop:** the job's event loop notices the request is no longer live and frees its runner at once. The abandoned graph thread finishes in the background, writing nothing.
- **Editing lock:** while a generation is live, it holds the deck's editing lock for its sender.

**Tech Stack:** FastAPI, SQLAlchemy (Lakebase Postgres in prod, SQLite in most unit tests), LangGraph with the custom `SqlAlchemyCheckpointSaver`, React 18 + TypeScript + Vitest.

**Spec:** `docs/superpowers/specs/2026-11-12-interrupt-generation-design.md`. Read it first; this plan argues from it.

## Global Constraints

- **Agent decks only.** No behaviour change on Legacy decks (`deck_mode = "legacy"`, engine `"monolith"`), MCP jobs, the SSE route `/chat/stream`, or the arc-review sweeper's own turns. A monolith turn must take exactly today's code path.
- Live request statuses: `("pending", "running")`. Terminal: `"completed"`, `"error"`, `"cancelled"` (new).
- New `chat_requests.rollback_outcome` values: `"rolled_back"`, `"kept_foreign_change"`, `"restore_failed"`, or NULL.
- **Fence rule:** in any transaction that writes on behalf of a turn, `fence_turn_write` is the **first lock-taking statement**, before any `with_for_update()` or `UPDATE`. The rollback also claims the `chat_requests` row first. This ordering is what prevents deadlocks.
- **Copy, exact:**
  - stop tooltip `Stop generating (Esc)`; stop aria-label `Stop generating`
  - generating hint `Esc to cancel · Enter to send · Shift+Enter new line`
  - dialog title `Stop generating?`, buttons `Keep generating` / `Stop and discard`
  - dialog message, with a total: `Your slides are being built ({done} of {total} done). If you stop now, every slide built so far is thrown away and the deck goes back to how it was before you sent this message.`
  - dialog message, when `total` is 0: the same text with ` ({done} of {total} done)` removed
  - cancelled notice `Generation cancelled. Nothing was changed.`
  - failed notice `Generation failed. Nothing was changed.`
  - refused-stop notice `Someone else has edited this deck since you sent this, so it can't be rolled back.`
  - failed-but-kept notice `Generation failed, and it couldn't be undone because someone else has edited this deck since you sent your message.`
  - restore-pending 409 detail, also used in the UI: `This deck is still being restored after a failed generation. Try again in a minute.`
  - stop-failed error `Couldn't stop the generation. It is still running.`
  - arc-review-busy 409 detail `This deck is being updated in the background. Try again in a few seconds.`
  - not-stoppable 409 detail `This generation can't be stopped.`
  - engine-race 409 detail `This deck changed while you sent your message. Try again.`
- **Kept on rollback:** Image Library assets, usage/cost rows, MLflow traces, `shared_deck_mutation_event` rows (append-only). A restore appends one `restore_version` row when the deck existed before Enter, and none on a first-generation rollback, whose deck row is deleted.
- **Python:**
  - Run in the worktree's own venv: `uv sync --extra dev`, then `uv run pytest …`.
  - Postgres-gated tests read `TELLR_TEST_POSTGRES_URL` (default `postgresql+psycopg2://localhost:5432/postgres`). Start Postgres locally with `pg_ctl` (brew postgresql@15).
- **Frontend:** `cd frontend && npx vitest run <path>`, `npm run typecheck`, `npm run lint`.
- **Schema changes:**
  - Ship as idempotent helpers in `src/core/database.py::_run_migrations`, using the inspector-check + `ALTER TABLE` pattern of `_migrate_chat_request_progress` (`database.py:1459`).
  - New tables also get a `Table.create(checkfirst=True)` fallback, as `_migrate_graph_checkpoints` (`:1257`) does.
  - No backfill.
- The `shared_deck_mutation_event.operation` column has a DB CHECK constraint (`database.py:883`), so do not invent a new operation; reuse `"restore_version"` with `object_type="deck"`.
- **"Identical" after a restore** means every content column and every slide row is equal. Three columns are excluded:
  - `session_slide_decks.version`, which is bumped so open clients and other processes reload
  - `updated_at`
  - `user_sessions.last_activity`

## Rulings from plan review (round 1)

- **`deck_reviews` stay.** They are content-addressed by `(deck_id, deck_digest)` (`src/database/models/deck_review.py` docstring). A row written during a stopped turn describes that turn's content. If its digest equals the restored deck's, it is a valid review of identical content. On a first-generation rollback the deck row is deleted and its `deck_reviews` go with it through the FK's `ondelete="CASCADE"` (`deck_review.py:47`).
- **The session survives a first-generation rollback.** The frontend persists it before sending (`ensureGraphCapableRoot`, `ChatPanel.tsx:356`), so it existed before Enter. An on-the-fly session from `_maybe_create_session` also stays, as an empty session.
- **The commit point is sealing.** Once the graph has finished, the turn seals its snapshot (Task 5) before the save point and the title join. From then on a stop returns `already_finished`, and a later failure keeps the finished deck. So a stopped turn never leaves a save point, and a sealed turn is never rolled back.
- **A rolled-back failure deletes its own `info` notice** (the #321 diagnostic, tagged with the request id), along with the rest of the turn's messages. The user sees the failed notice instead, and the server log keeps the cause.
- **Cost of the snapshot:** about two copies of the deck (deck JSON plus slide rows) per Agent Enter. Decks reach about 3 MB, and the snapshot is deleted at the end of every turn.
- **Contention:** every turn write row-locks the one `chat_requests` row for a few milliseconds, so parallel slide writes serialise on it. That is accepted.
- **The stop affordance is polling-only.** It needs a request id, and the dev-only SSE transport has none. The stop sign shows only when `isPollingMode()` (`api.ts:64`) is true.

## Review Focus

1. **Stop pressed before the request id is known** (Esc within ~100 ms of Enter). Expected: it still stops; the stop is queued until `request_accepted` arrives. Owner: Task 10 (`test_stop_before_request_accepted_is_sent_once_accepted`).
2. **Stop racing completion.** Expected: exactly one of "finished deck" or "rolled back", never a mix. A stop that loses the race returns `already_finished`, and the UI keeps the finished deck. Owner: Task 5 (`test_cancel_after_complete_is_already_finished`), Task 8 (`test_complete_and_cancel_race_has_one_winner`).
3. **Double stop** (click, then Esc; or two tabs). Expected: idempotent. The second call is `already_finished`, with no second restore. Owner: Task 4 (`test_second_rollback_is_not_live`).
4. **Instant stop after the architect committed** (planning label still showing, but `apply_slide_layout` / placeholders / Spec already written). Expected: still a full restore. Owner: Task 8 (`test_stop_after_layout_commit_before_builders_restores`).
5. **Esc while the stop dialog or any other dialog is open.** Expected: the dialog handles it (keep generating), and no stop is sent. Owner: Task 10 (`test_escape_with_dialog_open_does_not_stop`).

---

### Task 0 (controller, before Task 1): baselines

Record the failing-test **causes** (not counts) for:
- `uv run pytest tests/unit -q -n auto`
- the CI integration file list
- `cd frontend && npx vitest run`

Write them to `~/tellr-loop/interrupt-generation/baseline.md`. Re-derive after Task 1 (schema change).

Models: test=n/a impl=controller

---

### Task 1: Schema — snapshot table and two columns

**Files:**
- Create: `src/database/models/generation_snapshot.py`
- Modify: `src/database/models/__init__.py` (export), `src/database/models/session.py` (`UserSession.processing_request_id` next to `:208`; `ChatRequest.rollback_outcome` next to `:97`; `ChatRequest.status` comment gains `cancelled`)
- Modify: `src/core/database.py` (two helpers, called from `_run_migrations` after `_migrate_chat_request_progress` at `:664`)
- Test: `tests/unit/test_generation_snapshot_schema.py`

**Interfaces:**
- Produces `GenerationSnapshot` (table `generation_snapshots`):
  - `id` Integer PK
  - `request_id` String(64), unique, not null
  - `actor_session_pk` Integer, not null (`user_sessions.id` of the requesting session)
  - `owner_session_pk` Integer, not null
  - `deck_present` Boolean, not null
  - `deck_columns_json` Text, nullable
  - `slide_rows_json` Text, not null, default `"[]"`
  - `session_fields_json` Text, not null
  - `checkpoint_id` String(255), nullable
  - `mutation_watermark` Integer, nullable (max `shared_deck_mutation_event.id` for the deck at snapshot time)
  - `state` String(20), not null, default `"active"` (`"active"` | `"sealed"` | `"restore_failed"`)
  - `created_at` DateTime, not null
- Produces `UserSession.processing_request_id` String(64) nullable; `ChatRequest.rollback_outcome` String(32) nullable.
- Produces `_migrate_generation_snapshots(conn, schema)` and `_migrate_generation_rollback_columns(conn, schema)`, with the same shape as their neighbours in `_run_migrations`.

- [ ] **Step 1: Write the failing tests.**
  - `test_migration_creates_snapshot_table_on_old_schema`: build a SQLite DB with `create_all` restricted to every table except `generation_snapshots` (`Base.metadata.create_all(bind=engine, tables=[t for t in Base.metadata.sorted_tables if t.name != "generation_snapshots"])`). Then drop `user_sessions.processing_request_id` and `chat_requests.rollback_outcome` by rebuilding those two tables without them (or create them from a copied `Table` minus the columns). Run `_run_migrations`. Assert via the inspector that the table and all its columns exist and that both new columns exist.
  - `test_migration_is_idempotent`: run `_run_migrations` twice; no error; column sets unchanged.
  - `test_snapshot_request_id_is_unique`: inserting two rows with one `request_id` raises `IntegrityError`.
- [ ] **Step 2:** `uv run pytest tests/unit/test_generation_snapshot_schema.py -q`. Expected: FAIL (import error / missing table).
- [ ] **Step 3:** Implement the model, the columns and both migration helpers.
- [ ] **Step 4:** Run the same command. Expected: PASS. Then `uv run pytest tests/unit -q -n auto -k "migration or schema"`. Expected: no new failure causes against the Task-0 baseline.
- [ ] **Step 5:** Commit: `feat(schema): generation snapshots and request-owned session lock columns`.

Models: test=opus impl=sonnet

---

### Task 2: The fence primitive and request-owned session lock

**Files:**
- Create: `src/services/generation_fence.py`
- Modify: `src/api/services/session_manager.py`:
  - `acquire_session_lock` `:3970`: clear `processing_request_id` when taking the lock
  - new `bind_session_lock`
  - `release_session_lock` `:4050`
- Modify: `src/api/services/job_queue.py:314`. The `finally` release passes `request_id` **for graph requests only** (`payload["engine_mode"] == "graph"`). Monolith requests, which include every MCP job, keep today's unconditional `release_session_lock(session_id)`. `mcp_server.py:213-252` acquires the lock and never binds a request id, so a matched release would never fire there.
- Modify: `src/api/routes/chat.py`:
  - `submit_chat_async`: call `bind_session_lock` right after `create_chat_request` (`:838`)
  - every `release_session_lock` in its error paths passes `request_id` once it exists
- Test: `tests/unit/test_generation_fence.py`, `tests/unit/test_session_lock_ownership.py`, and the Postgres race in `tests/integration/test_generation_fence_postgres.py`

**Interfaces:**
- Produces in `generation_fence.py`:
  - `LIVE_STATUSES: tuple[str, ...] = ("pending", "running")`
  - `class TurnFencedError(RuntimeError)` with attribute `request_id: str`
  - `class TurnStopped(RuntimeError)` with attribute `request_id: str`. Raised by the generator's consumer loop in `_send_message_streaming_graph`, which runs on the chat-job executor thread (Task 6). Never raised by a writer.
  - `def claim_turn_row(db: Session, request_id: str) -> bool`: executes `UPDATE chat_requests SET status = status WHERE request_id = :rid AND status IN ('pending','running')` and returns `rowcount == 1`.
  - `def fence_turn_write(db: Session, request_id: str | None = None, *, allow_completed: bool = False) -> None`:
    - `rid = request_id or get_chat_request_id()` (from `src/services/graph/event_emitter.py:101`)
    - if `rid` is None, return without touching the DB
    - otherwise raise `TurnFencedError(rid)` unless `claim_turn_row`
    - with `allow_completed=True`, the claim also matches `status = 'completed'`, so only `cancelled` / `error` are refused. Only the title thread uses this (Task 3b).
  - `def start_chat_request(db: Session, request_id: str) -> bool`: `UPDATE chat_requests SET status='running' WHERE request_id=:rid AND status='pending'`, returning `rowcount == 1`.
  - `def turn_is_live(request_id: str) -> bool`: read-only, own `get_db_session()`.
- Produces in `SessionManager`:
  - `bind_session_lock(self, session_id: str, request_id: str) -> None`: sets `processing_request_id` where `is_processing`.
  - `release_session_lock(self, session_id: str, request_id: str | None = None) -> bool`. With `request_id`, it releases only when `processing_request_id == request_id`. Without it, it releases as today. Either way it clears `processing_request_id` when it releases, and it returns whether it released.

- [ ] **Step 1: Write the failing tests** (SQLite unit fixture from `tests/unit/conftest.py`):
  - `test_fence_noop_without_request_id`: no ContextVar and no arg means no SQL is issued. Patch `claim_turn_row` to raise if called.
  - `test_fence_passes_while_live`: rows `pending` and `running` pass.
  - `test_fence_raises_after_terminal`, parametrised over `cancelled` / `error` / `completed`: it raises `TurnFencedError` whose `.request_id` equals the id.
  - `test_fence_reads_context_var`: `set_chat_request_id(rid)` with status `cancelled` raises.
  - `test_allow_completed_refuses_only_cancelled_and_error`
  - `test_start_chat_request_only_from_pending`: True once; False for `running`, `cancelled`, `completed` or `error`.
  - `test_old_request_release_does_not_free_new_lock`:
    - acquire, then bind `r1`, then `release(…, "r1")` returns True
    - acquire, then bind `r2`, then `release(…, "r1")` returns False and `is_processing` stays True
    - `release(…, "r2")` returns True
  - `test_release_without_request_id_is_unchanged`: the manual-edit path.
  - `test_monolith_job_releases_unbound_lock`: an MCP-style job (acquire, no bind, `engine_mode` monolith) frees the session lock on completion, exactly as today.
  - Postgres-gated (`@pytest.mark.postgres`, self-skip), `test_rollback_claim_waits_for_in_flight_writer`:
    - connection A: `claim_turn_row`, no commit
    - connection B in a thread: `claim_turn_row`, then `UPDATE status='cancelled'`; it must block
    - A commits; B proceeds and commits
    - a fresh `claim_turn_row` returns False
    - Assert ordering with timestamps or `threading.Event`, not sleeps alone.
- [ ] **Step 2:** `uv run pytest tests/unit/test_generation_fence.py tests/unit/test_session_lock_ownership.py tests/integration/test_generation_fence_postgres.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement. Make `release_session_lock`'s match a single conditional `UPDATE`, not read-then-write.
- [ ] **Step 4:** Re-run. Expected: PASS. Then run `uv run pytest tests/unit/test_session_lock_heartbeat.py tests/unit/test_job_queue_concurrency.py tests/unit/test_job_queue_timeout_sweeper.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(turns): write fence primitive and request-owned session lock`.

Models: test=opus impl=sonnet

---

### Task 3a: Fence the deck and planner-state writers

**Files** (each `fence_turn_write(db)` goes at the top of the writer's existing `with get_db_session() as db:` / `_session()` block):
- Modify: `src/api/services/slide_repository.py`: `write_slide` (block at `:200`, so `commit_placeholder` is covered too), `apply_slide_layout` (block at `:618`, so `insert_pending_slides` is covered too), `delete_slide`
- Modify: `src/api/services/deck_level_writer.py`: `write_deck_level_columns` (block at `:272`)
- Modify: `src/services/graph/nodes.py`: the deck-review save block (`:7578`)
- Modify: `src/core/checkpointer.py`: `put` (`:385`) and `put_writes` (`:439`), fence inside `_session()` before the upsert. Also add `latest_checkpoint_id(self, thread_id: str, *, session: Session) -> str | None` and `delete_checkpoints_after(self, thread_id: str, checkpoint_id: str | None, *, session: Session) -> None`:
  - both methods span **every** `checkpoint_ns` of the thread, not only the default namespace that `_SELECT_LATEST_CHECKPOINT` filters on (`checkpointer.py:142-148`)
  - `checkpoint_id` None deletes the whole thread
  - otherwise delete rows with `checkpoint_id > :cid` from both `graph_checkpoint_writes` and `graph_checkpoints`; ids are UUID6, so lexicographic order is creation order (`:145`)
  - run on the caller's session, no commit, like `delete_thread` `:481-488`
- Test: `tests/unit/test_generation_fence_writers.py`, plus additions to `tests/unit/test_checkpointer.py`

**Interfaces:** Consumes Task 2's `fence_turn_write`, `TurnFencedError`. Produces the two checkpointer methods above; Task 4 uses them.

- [ ] **Step 0: Write inventory gate.** Before any fencing, grep for every DB write reachable from a graph turn (`get_db_session`, `session_factory`, `.commit(`, `db.add(`, `.execute(` with UPDATE/INSERT/DELETE) under `src/services/graph/`, `src/services/agent_tools/`, `src/services/image_*`, `src/api/services/` (the writers) and `src/core/checkpointer.py`. Write the list to `~/tellr-loop/interrupt-generation/write-inventory.md`, with each entry assigned to Task 3a or 3b, or marked read-only with a reason. **Stop and report** if any write is neither in 3a/3b nor read-only. Task 8 copies the final list into the technical doc.

- [ ] **Step 1: Write the failing tests.**
  - **`except TurnFencedError: raise` audit.** Every writer call site in `src/services/graph/nodes.py` that sits inside a broad `except Exception`, for example `commit_placeholder` at `:1976-1992`, gets `except TurnFencedError: raise` ahead of the broad clause. An abandoned branch then ends at its first refused write instead of logging and carrying on with more model calls. Test: `test_abandoned_pipeline_stops_at_first_refused_write`. A counting fake model shows no builder or reviewer call starts in that branch after the refused write.
  - For each writer, a pair:
    - `test_<writer>_refused_after_cancel`: ContextVar set to a `cancelled` request. Calling the writer raises `TurnFencedError`, and a re-read shows the target rows **byte-identical** to before. Compare full row dicts, not chosen keys.
    - `test_<writer>_lands_while_live`: ContextVar set to a `running` request; the write lands.
  - `test_writers_unfenced_outside_a_turn`: ContextVar None; all writers work as today, so manual edits and the sweeper are untouched.
  - Checkpointer: `test_put_refused_after_cancel` (no new `graph_checkpoints` row).
  - `test_delete_checkpoints_after_keeps_earlier`: three checkpoints c1<c2<c3, plus writes on each. `delete_checkpoints_after(t, c1)` leaves only c1 and its writes; `latest_checkpoint_id` returns c1.
  - `test_delete_checkpoints_after_none_clears_thread`.
- [ ] **Step 2:** `uv run pytest tests/unit/test_generation_fence_writers.py tests/unit/test_checkpointer.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Re-run. Expected: PASS. Then `uv run pytest tests/unit/test_slide_pipeline.py tests/unit/test_graph_nodes.py tests/unit/test_insert_pending_slides.py -q -n auto`. Expected: no new failure causes.
- [ ] **Step 5:** Commit: `feat(turns): fence deck, review and checkpoint writes`.

Models: test=opus impl=sonnet

---

### Task 3b: Fence messages, progress, session fields, images, title and save point

**Files:**
- Modify: `src/api/services/session_manager.py`:
  - `add_message` (`:1905`): fence from the **ContextVar only**, `fence_turn_write(db)` with no `request_id` argument, at the top of its `with` at `:1927`. Do **not** fence on the explicit `request_id` arg: the monolith passes one too (`streaming_callback.py:104, 155, 217, 256, 337`; `chat_service.py:1193, 1230, 1263`), and monolith writes must behave exactly as today. Graph callers (`nodes.py:504`, `:1835`) run under the ContextVar.
  - `record_chat_request_progress` (`:4163`): add `AND status IN ('pending','running')` to the existing conditional `UPDATE`; do not add a separate fence
  - `set_genie_one_conversation_id` (`:1779`): fence first, before the `with_for_update()` at `:1794`
  - `update_session` / `rename_session` (`:1557`, `:1561`): new kwarg `request_id: str | None = None`, fenced inside its `with`
  - `create_version` (`:3322`): new kwarg `request_id: str | None = None`, fenced at the top of its `with` (`:3345`)
- Modify: `src/services/agent_tools/gateway_tool.py`, `make_image_saver`'s `save` (`:300-313`): fence first inside its `with get_db_session()`. Check which thread runs it; if it is a pool thread, copy the context at submit, as for the image tool below. Test: `test_gateway_image_save_refused_after_cancel`.
- Modify: `src/services/agent_tools/image_generation_tool.py`:
  - `save_to_library` (`:135`): fence first inside the `with` at `:139`
  - the image jobs run on `_POOL` with **no context copy** (`:287`, `_POOL.submit(job_body, job)`), so the ContextVar is None in that thread and the fence would be a silent no-op. Submit `contextvars.copy_context().run, job_body, job` instead.
- Modify: `src/api/services/chat_service.py`:
  - `create_save_point` (`:3153`) gains `request_id: str | None = None`, passed to `create_version`
  - in `_send_message_streaming_graph`, `run_title_gen` (`:1993`) calls `rename_session(session_id, title, request_id=request_id, allow_completed=True)`. The thread's context was copied before `invoke_graph` set the ContextVar, so pass the id explicitly. It is joined for only 10 s (`:2102`), so a slow title can land after `completed`, and it must still land then. `rename_session` and `update_session` therefore gain `allow_completed: bool = False` as well, passed through to the fence.
  - the save-point call (`:2075`) passes `request_id=request_id`
  - catch `TurnFencedError` around the title and save-point writes, log at INFO and continue. That is not a turn failure.
- Test: `tests/unit/test_generation_fence_session_writers.py`

**Interfaces:** Consumes Task 2. Changes the signatures listed above; all new kwargs default to None, so existing callers are unchanged.

- [ ] **Step 1: Write the failing tests:** one `refused_after_cancel` / `lands_while_live` pair per writer above, as in Task 3a:
  - `add_message`, `record_chat_request_progress` (rowcount 0 and `progress_json` unchanged after cancel), `set_genie_one_conversation_id`, `rename_session`, `create_version` (no new `slide_deck_versions` row), and `save_to_library` (no new `image_assets` row)
  - `test_title_thread_write_after_cancel_is_dropped`: run `run_title_gen`'s path with a cancelled request; the title is unchanged and no exception escapes
  - `test_title_after_completed_still_lands`
  - `test_image_save_through_real_pool_refused_after_cancel`: drive `ImageGenerationAgentTool` with a fake generator through the real `_POOL`, under a cancelled request's ContextVar. No `image_assets` row is added. This test fails without the context copy, which is its proof.
  - `test_monolith_add_message_after_completion_still_lands`: explicit `request_id`, no ContextVar, request `completed`. The row is written, exactly as today.
- [ ] **Step 2:** `uv run pytest tests/unit/test_generation_fence_session_writers.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Re-run. Expected: PASS. Then `uv run pytest tests/unit/test_chat_request_progress.py tests/unit/test_turn_progress_graph.py tests/unit -q -n auto -k "genie or title or image or save_point or version"`. Expected: no new failure causes.
- [ ] **Step 5:** Commit: `feat(turns): fence turn messages, progress, session fields, images, title and save point`.

Models: test=opus impl=sonnet

---

### Task 4: Snapshot capture and rollback

**Files:**
- Create: `src/services/generation_rollback.py`
- Modify: `src/api/services/chat_service.py`, `_get_or_load_deck` (`:2947`). Today a cached deck is served when `db_version is None` (`:2960`). After a first-generation rollback deletes the deck row, every **other** process would keep serving its cached deck. Make a **confirmed** "no deck row" drop the cache entry and return None.
  - `_get_deck_version` returns None on **any** exception today (`:3022-3034`), so it must report three cases separately: a version, "no row" and "error". A sentinel or a re-raise works.
  - On error, keep today's behaviour and serve the cache.
  - A row with a NULL `version` keeps today's behaviour too.
  - This read path is shared with Legacy. The only observable change there is that a deck whose row was deleted is no longer served from a stale cache. Add `test_db_error_keeps_cached_deck`.
- Test: `tests/unit/test_generation_rollback.py`

**Interfaces:**
- Consumes:
  - `claim_turn_row`, `LIVE_STATUSES` (Task 2)
  - `latest_checkpoint_id`, `delete_checkpoints_after` (Task 3a)
  - `GenerationSnapshot` (Task 1)
  - `SessionManager._get_deck_owner_session(db, session)` (`session_manager.py:1380`)
  - `record_shared_deck_mutation` (`src/services/shared_deck_attribution.py:64`)
- Produces:
  - `def take_generation_snapshot(db: Session, *, request_id: str, session_id: str) -> None`. Inside the caller's transaction; no commit.
  - `def has_generation_snapshot(request_id: str) -> bool`
  - `def has_pending_restore(session_id: str) -> bool`: true when any snapshot for the actor session or its deck owner is in state `restore_failed`.
  - `def seal_generation(request_id: str) -> bool`: one transaction. `claim_turn_row`, then `UPDATE generation_snapshots SET state='sealed' WHERE request_id=:rid AND state='active'`. Returns True only if both matched; otherwise the transaction rolls back and it returns False. If the claim matched but **no snapshot row exists** (it should be unreachable after Task 5's fail-closed submit), log a WARNING and return True, so a graph turn is never abandoned in `running`.
  - `def discard_generation_snapshot(db: Session, request_id: str) -> None`
  - `class RollbackResult(str, Enum)`: `ROLLED_BACK = "rolled_back"`, `KEPT_FOREIGN_CHANGE = "kept_foreign_change"`, `REFUSED_FOREIGN_CHANGE = "refused_foreign_change"`, `NOT_LIVE = "not_live"`, `NO_SNAPSHOT = "no_snapshot"`, `RESTORE_FAILED = "restore_failed"`, `SEALED_KEPT = "sealed_kept"`
  - `def roll_back_generation(request_id: str, *, terminal_status: Literal["cancelled", "error"], error_message: str | None, refuse_on_foreign_change: bool) -> RollbackResult`

**What the snapshot holds** (take it exactly; the restore must make each one equal again):
- the owner's `session_slide_decks` content columns, or "no deck row": `title`, `html_content`, `scripts_content`, `slide_count`, `deck_json`, `verification_map`, `deck_spec_json`, `css`, `external_scripts_json`, `head_meta_json`, `modified_by`
- every `session_slides` row of the owner, all columns
- the owner's `deck_mode`, `graph_release_id`, `title`
- the actor's `title`
- the actor's `genie_one` agent-config entry `conversation_id`, or absent
- `latest_checkpoint_id(actor session_id)`
- `mutation_watermark`: `max(shared_deck_mutation_event.id) WHERE root_session_id = owner.id`, or **0** when there is none. Matching on `root_session_id` instead of `root_deck_id` keeps the check working on a first generation, when there is no deck row yet.

**`roll_back_generation`, in one `get_db_session()` transaction:**
1. If `not claim_turn_row(db, rid)`, return `NOT_LIVE`.
2. Load the snapshot.
   - **None** (monolith): set the terminal status, release the session lock for `rid`, return `NO_SNAPSHOT`.
   - **`state == 'sealed'`**: the turn has committed.
     - with `terminal_status == "cancelled"`: roll the transaction back, so nothing changes, and return `NOT_LIVE`
     - with `terminal_status == "error"` (a failure, timeout or orphan after the seal): **keep the deck**. Set `status='error'` and `error_message`, leave `rollback_outcome` NULL, delete the snapshot, release the lock by `rid`, and return `SEALED_KEPT`.
3. **Foreign-change check.** There is a foreign change when any `shared_deck_mutation_event` has `root_session_id == owner_session_pk`, `id > mutation_watermark` and `actor_session_id != actor_session_pk`.
   - With `refuse_on_foreign_change`: return `REFUSED_FOREIGN_CHANGE` and roll the transaction back, so the status stays live.
   - Otherwise: set `status=terminal_status`, `rollback_outcome="kept_foreign_change"`, delete the snapshot, release the lock, log at ERROR, return `KEPT_FOREIGN_CHANGE`.
4. **Restore.**
   - **Deck existed:** set the content columns from the snapshot, bump `version` by one, delete the owner's `session_slides`, insert the snapshot rows. Record one `restore_version`/`deck` mutation as `restore_version` does (`session_manager.py:3754-3768`).
   - **No deck row then:** delete the owner's slides and the deck row if one now exists. `deck_reviews` cascades. Record no mutation.
   - Delete `session_messages WHERE request_id = rid`.
   - Restore the session fields. For `genie_one`, change only the entry's `conversation_id`, and only if the entry still exists.
   - `delete_checkpoints_after(actor session_id, snapshot.checkpoint_id, session=db)`.
5. Set `status`, `error_message`, `completed_at`, `rollback_outcome="rolled_back"`. Delete the snapshot. Release the session lock with a conditional `UPDATE` matching `processing_request_id == rid`. Commit. Then call `get_chat_service()._invalidate_deck_cache(...)` in this process for the actor's session_id **and** the owner's session_id, when they differ.

**If any step after 1 raises:**
- open a second transaction
- if `claim_turn_row`, set `status=terminal_status`, `rollback_outcome="restore_failed"` and `error_message` to the restore-pending copy
- set the snapshot's `state="restore_failed"`
- leave the session lock held. Task 5's `finally` releases by `request_id` only when **no snapshot row remains** for the request, and Task 7's `_live_generation_holder` also counts snapshots in state `restore_failed`, so the deck stays locked to its sender until the restore succeeds.
- log at ERROR and return `RESTORE_FAILED`

Task 6's sweep retries these.

- [ ] **Step 1: Write the failing tests.** Seed with the real writers (`SlideWriter`, `write_deck_level_columns`, `add_message`, checkpointer `put`); do not insert raw rows. Compare full row dicts and full column sets.
  - `test_first_generation_rollback_returns_to_empty`: the session has no deck. Snapshot; a turn creates the deck, 3 slides, a Spec, a title, `deck_mode="agent"`, a pin and 4 messages tagged `rid`, plus checkpoints. Roll back. There is no deck row and there are no slides; the title, `deck_mode` and pin equal the snapshot; there are no `rid` messages; the thread has no checkpoints; messages of another request are untouched.
  - `test_edit_rollback_is_exact`: a 4-slide deck with a Spec and a verification record. Snapshot. Then `apply_slide_layout` deletes one slide and moves another, `write_slide` rewrites a third, and `write_deck_level_columns` changes the css and Spec. Roll back. Every `session_slides` row equals the snapshot on every column. The deck columns are equal, and `version` is old + (number of bumps) + 1.
  - `test_checkpoints_before_snapshot_survive`
  - `test_genie_one_conversation_id_restored_only_on_entry`: the entry is restored; other agent-config keys changed mid-turn survive.
  - `test_cancel_refused_on_foreign_change`: another actor's mutation event after the watermark. Result `REFUSED_FOREIGN_CHANGE`; status still `running`; deck unchanged; snapshot kept.
  - `test_failure_keeps_foreign_change`: same setup with `refuse_on_foreign_change=False`. Result `KEPT_FOREIGN_CHANGE`; status `error`; outcome `kept_foreign_change`; deck not restored.
  - `test_second_rollback_is_not_live` (Review Focus 3)
  - `test_rollback_on_completed_is_not_live`
  - `test_cancel_on_sealed_is_not_live_and_changes_nothing`
  - `test_failure_on_sealed_keeps_deck_and_ends_request` (status `error` straight away, the lock released, the snapshot gone)
  - `test_seal_fails_after_cancel`
  - `test_monolith_request_no_snapshot`: `NO_SNAPSHOT`; status set; lock released.
  - `test_restore_failure_marks_restore_failed_and_keeps_lock`: patch the slide insert to raise. Result `RESTORE_FAILED`; snapshot `state="restore_failed"`; `is_processing` still True; `has_pending_restore` True.
  - `test_late_writer_after_rollback_is_refused`: after `ROLLED_BACK`, `write_slide` under the `rid` ContextVar raises `TurnFencedError`, and the slide rows are unchanged.
  - `test_other_process_cache_drops_deck_after_first_generation_rollback`: warm a **second** `ChatService` instance's cache with the turn's deck, standing in for another worker. Roll back a first generation. That instance's `_get_or_load_deck` returns None.
  - `test_other_process_cache_reloads_after_edit_rollback`: the version bump makes the second instance reload the restored deck.
  - `test_first_generation_foreign_change_detected`: no deck at snapshot, watermark 0. Another actor's event on the owner after the snapshot refuses a stop.
  - Postgres-gated, in `tests/integration/test_generation_rollback_postgres.py` (`@pytest.mark.postgres`): `test_first_generation_rollback_deletes_deck_row_on_postgres`: a mutation event references the deck that the rollback deletes. The delete succeeds, the event's `root_deck_id` becomes NULL, and the append-only trigger (`database.py` ~930-975) does not block it.
- [ ] **Step 2:** `uv run pytest tests/unit/test_generation_rollback.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Re-run. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(turns): generation snapshot and all-or-nothing rollback`.

Models: test=opus impl=opus

---

### Task 5: Wire the turn lifecycle — submit, stop route, completion, failure, poll

**Files:**
- Modify: `src/api/routes/chat.py`:
  - `submit_chat_async` (`:774`)
  - new `POST /chat/cancel/{request_id}`
  - `poll_chat` (`:939`) returns `rollback`
- Modify: `src/api/schemas/responses.py`: `CancelChatResponse`
- Modify: `src/api/services/session_manager.py`:
  - `get_chat_request` (`:4197`) returns `rollback_outcome`
  - new `complete_chat_request(self, request_id: str, result: dict | None) -> bool`. It runs `claim_turn_row`, then sets `result_json`, `status="completed"` and `completed_at`, and deletes the snapshot, in one transaction. It returns False when not live.
- Modify: `src/api/services/job_queue.py`, `process_chat_request` (`:188`):
  - **Start (blocking fix).** Replace the unconditional `update_chat_request_status(request_id, "running")` (`:230`) with `start_chat_request` (Task 2) in its own transaction. If it returns False (the request was stopped while queued), **return at once**: no graph run, no status write, no lock release (the rollback already released it), but still `jobs.pop(request_id, None)` so `refresh_job_session_locks_once` (`:530`) stops counting it. The `finally` at `:314` must not release for this early return; move the early return above the `try`, or guard the `finally`.
    - This applies to **graph** requests only (`payload["engine_mode"] == "graph"`). A monolith request keeps the unconditional `update_chat_request_status(request_id, "running")`.
  - **`finally`** (`:312-316`). For graph requests: `release_session_lock(session_id, request_id=request_id)`, **skipped** while a snapshot row for the request still exists (a `restore_failed` restore keeps the deck locked). Monolith requests: unchanged.
  - **Success, graph requests.** Call `complete_chat_request` instead of `set_chat_request_result` + `update_chat_request_status("completed")`. It accepts a request whose snapshot is `sealed`, and deletes it. If it returns False, write nothing.
  - **Success, monolith requests.** Keep both existing writes exactly. Test: `test_monolith_success_writes_unchanged`.
- Modify: `src/api/services/chat_service.py`, `_send_message_streaming_graph`. **Seal** right after the event loop ends without error (`:2048`), **before** the save point (`:2072`):
  - `if request_id and not seal_generation(request_id): raise TurnStopped(request_id)`
  - the save point and the title join then run on a sealed turn, which a stop can no longer roll back
  - this closes the gap where a stop between the save point (`:2075`) and completion (`job_queue.py:297`) would restore the deck but leave a "Generated N slide(s)" version behind
  - **Generic failure** (`except Exception`, `:307`). Call `roll_back_generation(request_id, terminal_status="error", error_message=str(e), refuse_on_foreign_change=False)` **only when** `has_generation_snapshot(request_id)`. Otherwise run today's code, with its status write made conditional on the request still being live, so a stop is never overwritten by `error`.
  - **Pinned-configuration failure** (`except _PinnedGraphConfigurationTerminalError`, `:300`). It fires from `invoke_graph`'s pin loader before any node runs, yet the user message, the deck-mode lock and the snapshot already exist. With a snapshot, call `roll_back_generation(request_id, terminal_status="error", error_message=PINNED_GRAPH_CONFIGURATION_ERROR, refuse_on_foreign_change=False)`. Without one, keep today's write.
- Test: `tests/integration/test_generation_stop_routes.py`, `tests/unit/test_job_queue_rollback.py`

**Interfaces:**
- Consumes: Tasks 2 and 4, plus `spec_sync.review_in_flight(deck, now)`.
- Produces:
  - **Route.** `POST /api/chat/cancel/{request_id}` returns `CancelChatResponse{outcome: Literal["cancelled","already_finished"], status: str | None}`. The 409 body is `{"detail": <copy>, "outcome": "refused_foreign_change" | "not_stoppable"}`, returned with `JSONResponse(status_code=409, content=…)`, because `HTTPException` cannot carry the extra key.
  - **Poll response.** `rollback: str | None` (from `rollback_outcome`); `status` may be `"cancelled"`.

**Submit order** (`submit_chat_async`):
1. Run `acquire_session_lock`, `create_chat_request`, `bind_session_lock`.
2. **Decide the engine read-only**, before anything is written. Use `engine_mode_for_deck_mode(stored_owner_deck_mode or request.deck_mode)` (`src/domain/conversation_engine.py:16`), where the stored mode is read through the owner hop as `resolve_engine_mode` does (`chat_service.py:149`). **Monolith: skip steps 3-4 entirely**, so the turn runs exactly today's path with no snapshot ever written. The existing post-`add_user_message` resolution stays as it is.
3. Graph only, in **one** transaction that first takes `SELECT … FOR UPDATE` on the owner's `session_slide_decks` row (when one exists), as `_refuse_during_an_arc_review` does (`chat_service.py:288-319`):
   - refuse with 409 if `has_pending_restore(session_id)` (the restore-pending detail), or if `review_in_flight(deck, now)` (the arc-review-busy detail). Before returning, release the lock by `request_id` and mark the request `error`.
   - otherwise `take_generation_snapshot(db, request_id=…, session_id=…)` in the same transaction. Taking the deck-row lock first is what serialises submit against the sweeper's claim (Task 7).
4. Run `add_user_message` and the rest as today. Any exception after step 3 calls `roll_back_generation(…, terminal_status="error", refuse_on_foreign_change=False)` before the existing error mapping runs.
5. **Re-check the engine.** Both cases are only possible under a concurrent first message.
   - `resolve_engine_mode_or_unavailable` (`:872`) returns `monolith` but step 2 decided `graph`: discard the snapshot before enqueueing.
   - The reverse (decided `monolith`, resolved `graph`): **fail closed**. Never run a graph turn without a snapshot. Delete the request's messages (`session_messages WHERE request_id`), set the status to `error`, release the lock, and return 409 with the engine-race detail.
   - Tests: `test_engine_mismatch_discards_snapshot`, `test_engine_mismatch_reverse_fails_closed`.

**Cancel route:**
1. Owner check as in `poll_chat` (`get_session_id_for_request`, `_require_chat_request_owner`); 404 for an unknown request.
2. **Live and** `not has_generation_snapshot`: 409 `not_stoppable`. A request that is not live falls through to step 3, which returns `already_finished`.
3. Otherwise, `roll_back_generation(rid, terminal_status="cancelled", error_message=None, refuse_on_foreign_change=True)` in a thread, mapped as follows:

| Result | Response |
|---|---|
| `ROLLED_BACK` | `cancelled` |
| `NOT_LIVE` | `already_finished`, with the current status |
| `REFUSED_FOREIGN_CHANGE` | 409 with the refused-stop copy |
| `RESTORE_FAILED` | 500 "Internal server error" |

- [ ] **Step 1: Write the failing tests** (TestClient):
  - `test_cancel_rolls_back_and_frees_session` (the next `POST /chat/async` returns 200, not 409)
  - `test_cancel_after_complete_is_already_finished` (Review Focus 2)
  - `test_cancel_other_users_request_is_403`
  - `test_cancel_monolith_turn_is_409_not_stoppable`
  - `test_cancel_refused_on_foreign_change_409` (the generation stays `running`)
  - `test_poll_reports_cancelled_and_rollback`
  - `test_submit_refused_while_restore_pending`
  - `test_submit_refused_during_arc_review`
  - `test_submit_failure_after_snapshot_rolls_back` (patch the engine resolver to raise; no user message remains, and `deck_mode` is restored)
  - `test_monolith_submit_writes_no_snapshot` (patch `take_generation_snapshot` to raise if called on a legacy deck; also on a first message that requests `legacy`)
  - In `test_job_queue_rollback.py`:
    - `test_cancelled_pending_request_never_starts`: roll back while `pending`, then run `process_chat_request`. The graph is never invoked (assert on a stubbed `invoke_graph`), the status stays `cancelled`, and the session lock bound to a newer request is untouched.
    - `test_success_path_completes_and_drops_snapshot`
    - `test_graph_failure_rolls_back`
    - `test_pinned_configuration_failure_rolls_back` (a first generation whose pin is missing; no user message remains and `deck_mode` is restored)
    - `test_failure_after_cancel_does_not_overwrite_cancelled`
    - `test_stop_after_seal_is_already_finished_and_keeps_save_point`
    - `test_stop_before_seal_leaves_no_save_point`: block the turn just before the seal, stop it, release. No new `slide_deck_versions` row, and the deck is restored.
    - `test_monolith_failure_path_unchanged` (same status and error text as before; patch `has_generation_snapshot` → False)
    - `test_complete_after_cancel_returns_false_and_writes_nothing`
- [ ] **Step 2:** `uv run pytest tests/integration/test_generation_stop_routes.py tests/unit/test_job_queue_rollback.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Re-run. Expected: PASS. Then `uv run pytest tests/unit -q -n auto -k "chat or job_queue or poll"` and `uv run pytest tests/integration/test_graph_mode_turn.py tests/integration/test_clear_chat_routes.py -q`. Expected: no new failure causes.
- [ ] **Step 5:** Commit: `feat(chat): stop route, snapshot at submit, all-or-nothing completion`.

Models: test=opus impl=sonnet

---

### Task 6: Free the runner on stop; timeout and restart rollback

**Files:**
- Modify: `src/api/services/chat_service.py`, `_send_message_streaming_graph` (`:1852`):
  - **Consumer loop** (`:2041-2045`): replace `event_queue.get()` with `event_queue.get(timeout=STOP_POLL_SECONDS)`. When `request_id` is set, call `turn_is_live(request_id)` at most once per `STOP_POLL_SECONDS`; when it returns False, raise `TurnStopped(request_id)`. Sealing (Task 5) is the final liveness check before the save point.
  - **`run_graph`'s `except` blocks** (`:1940-1989`): if the exception is `TurnFencedError`, or `request_id` is set and `not turn_is_live(request_id)`, log at INFO `"Abandoned graph turn ended"` and skip the ERROR event and `error_container`. Still `put(None)` in `finally`.
- Modify: `src/api/services/job_queue.py`:
  - `STOP_POLL_SECONDS = 1.0`
  - `process_chat_request`: `except TurnStopped: pass` before the generic `except` (no status write; the `finally` releases by `request_id`)
  - `mark_timed_out_jobs_once` (`:481`): for a timed-out `graph` entry, `await asyncio.to_thread(roll_back_generation, rid, terminal_status="error", error_message=<existing text>, refuse_on_foreign_change=False)`
  - `mark_timed_out_jobs_loop` (`:579`): call `await asyncio.to_thread(recover_orphaned_generations)` each sweep (it restores decks, so never run it on the event loop)
  - `refresh_job_session_locks_once` (`:530`): for graph entries, refresh only while `processing_request_id` equals the entry's request id. Add `request_id: str | None = None` to `SessionManager.refresh_session_lock` (`session_manager.py:4022`). Monolith entries are unchanged. Test: `test_cancelled_queued_job_does_not_refresh_newer_lock`.
  - `recover_stuck_requests` (`:436`), already called at startup from `main.py:211`:
    - call `recover_orphaned_generations()` **first**
    - in its own loop, a stuck request **with** a snapshot goes through `roll_back_generation` instead of the bare flip to `error`
    - its unconditional `is_processing = False` (`:470`) becomes a release matched on `processing_request_id`
    - requests without a snapshot (monolith) keep today's behaviour
- Modify: `src/services/generation_rollback.py`:
  - add `def recover_orphaned_generations(now: datetime | None = None) -> int`. It rolls back (`error`, error_message `"Generation interrupted"`, `refuse_on_foreign_change=False`) every live request that has an **active** snapshot and meets either condition:
    - the actor session's `processing_request_id IS DISTINCT FROM request_id` (NULL-safe; on SQLite use `IS NOT`)
    - the session's `processing_started_at` is older than `ORPHAN_AFTER_SECONDS = 180`. That is three missed 60 s refreshes from `refresh_job_session_locks_once`.
  - A live request with a **sealed** snapshot whose job died goes through `roll_back_generation(…, terminal_status="error", error_message="Generation interrupted")`, which returns `SEALED_KEPT`. The finished deck stays.
  - UX consequence: after a restart, a generation that was mid-flight is rolled back within about 3-4 minutes. Until then, polling shows its last progress and a new send gets today's 409.
  - It then retries every `restore_failed` snapshot through a restore that skips step 1's liveness claim. Each retry claims its snapshot **inside the restore's own transaction**, as the first statement: `UPDATE generation_snapshots SET state='restore_failed' WHERE id=:id AND state='restore_failed'`. That is a row lock, and the retry skips the snapshot when rowcount is 0. A crash mid-restore rolls the whole transaction back, so no in-between state can strand a deck. On success it sets `rollback_outcome="rolled_back"`, deletes the snapshot and releases the session lock.
  - It returns the number handled.
- Test: `tests/unit/test_generation_runner_release.py`, `tests/unit/test_generation_recovery.py`

**Interfaces:**
- Consumes: Tasks 2, 4 and 5.
- Produces: `recover_orphaned_generations`, `STOP_POLL_SECONDS`, `ORPHAN_AFTER_SECONDS`.

- [ ] **Step 1: Write the failing tests.**
  - `test_runner_released_while_graph_thread_still_blocked`:
    - run `process_chat_request` with a stubbed `invoke_graph` that blocks on a `threading.Event` after one fenced write
    - cancel via `roll_back_generation`
    - `process_chat_request` must return within 3 s while the stub thread is still blocked
    - set the Event; the stub's next fenced write raises `TurnFencedError`; no row changes; no ERROR event; the lock is not re-released for a newer request bound in between
  - `test_stop_from_another_process_frees_the_consumer`: start a job on `ChatService` instance A, then replace `job_queue.jobs` with an empty dict and run the cancel path through a **second** `ChatService` / `SessionManager` instance, standing in for another uvicorn worker. A's consumer raises `TurnStopped` within `2 * STOP_POLL_SECONDS`, and the deck is restored.
  - `test_timeout_rolls_back_graph_turn` (the deck is restored; status `error`)
  - `test_timeout_leaves_monolith_unchanged`
  - `test_orphan_with_stale_lock_rolled_back`
  - `test_live_job_with_fresh_lock_not_touched`
  - `test_fresh_generation_orphaned_by_restart_rolled_back_after_180s` (age `processing_started_at` to 181 s with `processing_request_id` still equal; it is rolled back)
  - `test_null_processing_request_id_counts_as_orphan`
  - `test_sealed_orphan_marked_error_and_deck_kept`
  - `test_restore_failed_retried_and_lock_released`
  - Postgres-gated (`tests/integration/test_generation_rollback_postgres.py`), `test_restore_retry_claimed_once`: block the first retry inside its transaction on a `threading.Event`, start a second. The second skips; release; exactly one restore.
  - `test_startup_recovery_restores_old_running_request_with_snapshot`: a 1300-second-old `running` request with a snapshot is restored at startup, not just flipped to `error`.
  - `test_startup_recovery_leaves_monolith_as_today`
- [ ] **Step 2:** `uv run pytest tests/unit/test_generation_runner_release.py tests/unit/test_generation_recovery.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Re-run. Expected: PASS. Then `uv run pytest tests/unit/test_job_queue_timeout_sweeper.py tests/unit/test_session_lock_heartbeat.py tests/unit/test_job_queue_concurrency.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(turns): free the runner on stop; roll back timeouts and orphans`.

Models: test=opus impl=opus

---

### Task 7: Keep other writers out while a generation is live

**Files:**
- Modify: `src/api/services/session_manager.py`:
  - new `_live_generation_holder(self, db: Session, deck_owner: UserSession) -> str | None`. Find the newest `GenerationSnapshot` with `owner_session_pk == deck_owner.id` whose `ChatRequest` (joined on `request_id`) is live, **or** whose own `state == 'restore_failed'` (a failed restore keeps the deck locked to its sender). Return `UserSession.created_by` of its `actor_session_pk`; that is the same string `get_current_user()` returns and `locked_by` stores. `ChatRequest` has no user column, and `create_chat_request` drops its `created_by` argument (`session_manager.py:4076-4110`).
  - consult it in `require_editing_lock` (`:3836`), `acquire_editing_lock` (`:3859`) and `get_editing_lock_status` (`:3933`). A holder who is not the caller means locked by the holder, whatever `locked_by` / `locked_at` say.
- Modify: `src/api/routes/chat.py`, `_check_chat_permission` (`:127`), root-owner branch (`:157`):
  - return 423 **only** when `_live_generation_holder` names someone other than the caller, with the detail `f"Session is locked by {display name}"` as `require_editing_lock` words it
  - do **not** call `require_editing_lock` there. An ordinary heartbeat lock held by an idle contributor must keep not blocking the owner, on Legacy decks too.
- Modify: `src/services/spec_sync.py`, `claim_due_marker` (`:401`):
  - put "no live generation on this deck, and no `restore_failed` snapshot for it" (the same rule as `_live_generation_holder`) into the candidate subquery (`spec_sync.py:401-470` picks the deck inside the `UPDATE`), so a deck busy generating never starves the queue
  - then run it as two steps in one transaction:
    1. select the candidate id, then `SELECT … FOR UPDATE` that deck row
    2. re-check the live-generation predicate as its own statement and only then run the claim `UPDATE`
  - Test: `test_live_generation_deck_does_not_block_other_due_decks`, `test_sweeper_skips_deck_with_restore_failed_snapshot`
  - submit (Task 5, step 3) takes the same row lock before its `review_in_flight` check and snapshot, so the two serialise. Under READ COMMITTED, a subquery inside the `UPDATE` alone could miss a snapshot committed while it waited.
- Test: `tests/unit/test_generation_holds_editing_lock.py`

**Interfaces:** Consumes Task 1's model and Task 5's lifecycle. Produces no new public names.

- [ ] **Step 1: Write the failing tests:**
  - `test_live_generation_keeps_lock_after_heartbeat_lapses`: A's generation is live and `locked_at` is 10 minutes old. B's `acquire_editing_lock` returns `acquired: False` naming A; B's `require_editing_lock` raises; status says locked by A.
  - `test_lock_follows_normal_rules_after_generation_ends`
  - `test_owner_chat_refused_423_while_contributor_generation_live`
  - `test_owner_chat_allowed_on_unshared_deck`
  - `test_owner_chat_allowed_while_contributor_holds_idle_heartbeat_lock` (Legacy shared deck as well)
  - `test_sweeper_skips_deck_with_live_generation` (the marker is kept and claimed after the generation ends)
  - Postgres-gated, in `tests/integration/test_generation_lock_postgres.py` (`@pytest.mark.postgres`): `test_submit_and_sweeper_claim_serialise`: either the sweeper claims and submit is refused 409, or submit snapshots and the sweeper skips. Never both.
  - `test_monolith_turn_does_not_hold_lock` (no snapshot, so no hold)
  - `test_restore_failed_snapshot_keeps_lock_and_refuses_manual_edit`
- [ ] **Step 2:** `uv run pytest tests/unit/test_generation_holds_editing_lock.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Re-run. Expected: PASS. Then `uv run pytest tests/unit -q -n auto -k "lock or spec_sync or arc_review or permission"`. Expected: no new failure causes.
- [ ] **Step 5:** Commit: `feat(locks): a live generation holds the editing lock; owner chat and sweeper respect it`.

Models: test=opus impl=sonnet

---

### Task 8: Backend acceptance through real graph turns, plus the technical doc

**Files:**
- Test: `tests/integration/test_generation_stop_graph_turn.py`. Use `graph_env_threadsafe` (`tests/unit/conftest_graph.py:456`; import it explicitly, `from tests.unit.conftest_graph import graph_env_threadsafe  # noqa: F401`, because the integration conftest does not provide it; see `tests/integration/test_graph_orchestration.py`) and the deterministic fakes (`architect_build`, `builder_out`, `review_out`) for the first-generation and edit fixtures.
- Create: `docs/technical/generation-atomicity.md`. It covers snapshot, fence, rollback triggers, the lock rules, the lock-ordering rule, and "how to add a new turn writer" (call `fence_turn_write` first).
- Modify: `.github/workflows/test.yml`: add the new integration files to the job that lists integration files explicitly (`:205` area), and put the Postgres-gated file from Task 2 in the Postgres job.
- Modify: any source file these tests show to be wrong. Each such fix gets its own commit with the failing test named.

**Interfaces:** Consumes everything above.

- [ ] **Step 1: Write the tests.** Each one drives a real `invoke_graph` turn through `process_chat_request`.
  - `test_stop_during_planning_first_generation_restores_empty`
  - `test_stop_after_layout_commit_before_builders_restores` (Review Focus 4): block the first builder on an Event; cancel; full equality with the snapshot.
  - `test_stop_mid_build_on_edit_restores_exactly`: the edit moves, deletes and rewrites slides. Deck, Spec, styles, slide rows and messages all equal the pre-Enter state, and the next turn's architect conversation (`get_messages`) has no trace of the stopped request.
  - `test_late_builder_write_after_stop_changes_nothing`
  - `test_resend_after_stop_starts_immediately`: concurrency 1; the second turn's status becomes `running` while the first graph thread is still blocked.
  - `test_forced_failure_mid_build_rolls_back` (a fake builder raises a 403-shaped error)
  - `test_placeholder_slide_is_success_not_failure`
  - `test_complete_and_cancel_race_has_one_winner` (Review Focus 2): run 20 iterations, each with the cancel and the completion released together from a `threading.Barrier`. Exactly one outcome per run, and the end state is either the completed deck or the snapshot, never a mix.
- [ ] **Step 2:** `uv run pytest tests/integration/test_generation_stop_graph_turn.py -q`. Expected: either PASS, or failures that name a real defect. Fix each defect in source. Never weaken a test.
- [ ] **Step 3:** Write the technical doc. It must include the **write inventory** the spec's "Left to the builder" asks for. List every DB write a graph turn makes, with its fence (writer file:line and fence call), and every DB access in `nodes.py` that is read-only (the plan-review baseline: `:1027`, `:1094`, `:3909`, `:4128`, `:4647`). Confirm it with a grep for `get_db_session`, `session_factory`, `.commit(` and `db.add(` under `src/services/graph/`, `src/services/agent_tools/` and the writers.
- [ ] **Step 4:** Run the full suites: `uv run pytest tests/unit -q -n auto` and the CI integration file list. Expected: no new failure causes against the Task-0 baseline.
- [ ] **Step 5:** Commit: `test(turns): stop and rollback acceptance through real graph turns` (plus the doc).

Models: test=opus impl=opus

---

### Task 9: Frontend — API, ConfirmDialog focus, ChatInput stop mode

**Files:**
- Modify: `frontend/src/services/api.ts`:
  - `cancelChat`
  - `PollResponse.status` adds `'cancelled'`; add `rollback?: RollbackOutcome | null` (`:246-272`)
  - `ClientEventType` (`:94`) adds `'request_accepted' | 'cancelled'`; `StreamEvent` (`:96`) adds `request_id?: string`
  - `startPolling` (`:1187`): after `submitChatAsync` resolves, call `onEvent({type:'request_accepted', request_id})`. On `status === 'cancelled'`, stop polling and emit `{type:'cancelled'}`. On `'error'`, call `onError(new ChatTurnError(message, response.rollback ?? null))`. Re-check `cancelled` after every awaited `pollChat`, and forward nothing once cancelled.
- Modify: `frontend/src/components/ConfirmDialog.tsx`:
  - prop `initialFocus?: 'confirm' | 'cancel'` (default `'confirm'`, so existing callers are unchanged); the focus effect at `:29-31` uses it
  - its Escape handler (`:34-41`) calls `e.preventDefault()` before `onCancel()`, so any other window Escape listener can see the dialog already handled it
- Modify: `frontend/src/components/ChatPanel/ChatInput.tsx`: props `generating?: boolean`, `onStop?: () => void`, `restoreDraftKey?: number`.
- Create: `frontend/src/components/ChatPanel/stopGenerationCopy.ts`, holding every copy string from Global Constraints plus `stopDialogMessage(done: number, total: number): string`.
- Test: `frontend/src/services/api.cancel.test.ts`, `frontend/src/components/ConfirmDialog.focus.test.tsx`, `frontend/src/components/ChatPanel/ChatInput.stop.test.tsx`

**Interfaces:**
- Produces:
  - `api.cancelChat(requestId: string): Promise<CancelChatResult>`
  - `type CancelChatResult = { outcome: 'cancelled' | 'already_finished' | 'refused_foreign_change' | 'not_stoppable'; status?: string; detail?: string }`. A 409 resolves with its body's `outcome` and `detail`; any other non-2xx rejects.
  - `type RollbackOutcome = 'rolled_back' | 'kept_foreign_change' | 'restore_failed'`
  - `class ChatTurnError extends Error { rollback: RollbackOutcome | null }`
- **ChatInput while `generating && onStop`:**
  - the submit button is replaced by a `type="button"` stop button: lucide `Ban`, `text-red-600`, aria-label `Stop generating`, title `Stop generating (Esc)`, `data-testid="chat-stop"`
  - the stop button is enabled even though the textarea is disabled
  - the hint reads the generating copy
- **ChatInput draft restore:** when `restoreDraftKey` changes to a new non-zero value, restore the last submitted text **and** attachments (kept in a ref at submit, preview URLs included), put the cursor at the end, and focus the textarea once it is enabled.

- [ ] **Step 1: Write the failing tests:**
  - api:
    - `test_request_accepted_emitted_with_id`
    - `test_cancelled_status_stops_polling_and_emits_cancelled`
    - `test_error_carries_rollback`
    - `test_no_events_forwarded_after_local_cancel_even_mid_poll` (resolve a pending `pollChat` after cancel; `onEvent` is not called)
    - `test_cancelChat_409_resolves_with_outcome`
  - ConfirmDialog: `test_initial_focus_cancel_focuses_cancel_button`, `test_default_focus_unchanged`, `test_escape_prevents_default`
  - ChatInput:
    - `test_stop_button_replaces_send_while_generating`
    - `test_stop_button_enabled_while_input_disabled`
    - `test_generating_hint_copy`
    - `test_restore_draft_key_restores_text_and_attachments`
    - `test_no_stop_button_without_onStop` (Legacy)
- [ ] **Step 2:** `cd frontend && npx vitest run src/services/api.cancel.test.ts src/components/ConfirmDialog.focus.test.tsx src/components/ChatPanel/ChatInput.stop.test.tsx`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Re-run. Expected: PASS. Then `npx vitest run src/components/ChatPanel src/services` and `npm run typecheck && npm run lint`. Expected: no new failures.
- [ ] **Step 5:** Commit: `feat(chat-ui): stop button, draft restore, cancel API`.

Models: test=opus impl=sonnet

---

### Task 10: Frontend — ChatPanel stop flow, Escape, outcomes, deck reload, user guide

**Files:**
- Create: `frontend/src/components/ChatPanel/useEscapeToStop.ts`
- Modify: `frontend/src/components/ChatPanel/stopGenerationCopy.ts` (from Task 9): add `stopNeedsConfirmation`
- Modify: `frontend/src/components/ChatPanel/ChatPanel.tsx`:
  - `requestIdRef` and `pendingStopRef`
  - the stop handler, dialog and notice state
  - pass `generating`, `onStop` and `restoreDraftKey` to `ChatInput` (`:734-754`), but only when `effectiveDeckMode !== 'legacy'` **and** `isPollingMode()` (export it from `api.ts:64` if it is not exported; the SSE transport has no request id to stop)
  - handle `request_accepted` and `cancelled` in `handleStreamEvent` (`:399-557`) and `ChatTurnError` in `onError` (`:575-584`)
- Modify: `frontend/src/components/Layout/AppLayout.tsx`: new ChatPanel prop `onDeckRestored(deck: SlideDeck | null)`.
  - with a deck: `setSlideDeckGated(deck, deck.version, true)`
  - with `null`: `deckVersionRef.current = 0` **and** `setSlideDeck(null)`, mirroring `handleNewSession` (`:594`, `:624`). Without the reset, the version guard (`:152-159`) would reject the next first generation's version-1 deck.
- Modify: `GeneratedImagePreview.tsx`, `PromptEditorModal.tsx`, `GenerateImageRequestDialog.tsx`, `TemplateViewerModal.tsx`: add `role="dialog"` to the overlay root where it is missing.
- Modify: the user guide page that covers the chat panel, under `docs/user-guide/` (find it with grep). Add stopping a generation and the "all-or-nothing" behaviour, in plain language.
- Test: `frontend/src/components/ChatPanel/ChatPanel.stop.test.tsx`, `frontend/src/components/ChatPanel/useEscapeToStop.test.tsx`

**Interfaces:**
- Consumes: Task 9's API and props.
- Produces:
  - `useEscapeToStop(active: boolean, onStop: () => void): void`. It adds a window `keydown` listener in the bubble phase, registered **once** per `active` change, with `onStop` read from a ref. A listener re-registered on every render would run after ConfirmDialog's and could reopen the dialog. It calls `onStop` only for `key === 'Escape'`, and only when all three hold:
    - `!e.defaultPrevented`
    - `document.querySelector('[role="dialog"]')` is null
    - the event target is not an `input`, `textarea`, `select` or `[contenteditable]`, and is not inside a `[data-escape-owner]` element. Inline Escape handlers in `page-header.tsx:101`, `SessionHistory.tsx:447` and `ElementTreeView.tsx:127` own Escape there.
  - Add `data-escape-owner` to the slide viewer's feedback drawer root (`frontend/src/components/SlideViewer/FeedbackDrawer.tsx`), an open panel whose Escape returns focus.
  - SlideViewer's global focus-return Escape (`SlideViewer.tsx:280`) is otherwise allowed to run **alongside** the stop. **(Ruling)** The "Esc to cancel" hint is showing, so the stop is what the user asked for.
  - `stopNeedsConfirmation(progress: TurnProgress | null): boolean`, true when `progress?.phase` is `'building'` or `'reviewing_deck'`. It lives in `stopGenerationCopy.ts`.

**Behaviour:**
- **Stop:**
  - `stopNeedsConfirmation` true: open `ConfirmDialog` with `initialFocus="cancel"`, `variant="danger"` and the copy. The dialog closes itself if the turn completes, errors or is cancelled while it is open.
  - Otherwise, or on confirm: if there is no `requestIdRef` yet, set `pendingStopRef` to the **current send's `seq`**, and send the stop on that send's `request_accepted`. Otherwise call `api.cancelChat`.
  - Clear `pendingStopRef` and `requestIdRef` when a send starts and when a send fails. A pending stop whose `seq` is not the current send's is dropped, so it can never stop a later generation.
- **`cancelled` / `ROLLED_BACK`** (`finishAfterRollback(kind)`):
  - call `cancelStreamRef.current?.()` and clear the loading, generating, queued and turn-progress states
  - replace `messages` with `conversationApi.listMessages(sentTo)`, the server's truth after the delete
  - bump `restoreDraftKey`
  - run `reconcileDeckModeAfterError(sentTo, seq)`
  - `api.getSlides(sentTo)`, then `onDeckRestored(result.slide_deck ?? null)`
  - show a neutral, dismissible notice with the cancelled copy (for a stop) or the failed copy (for `ChatTurnError.rollback === 'rolled_back'`)
  - the notice clears on the next send
- **A `cancelled` event from polling** (the stop came from another tab): run `finishAfterRollback('cancelled')`, as for a stop sent from this tab.
- **`ChatTurnError.rollback === null`** (Legacy, or an error before any snapshot): today's error path, unchanged.
- **`already_finished`:** close the dialog and do nothing else; polling delivers the finished turn.
- **`refused_foreign_change`:** show the refused-stop notice; generation carries on.
- **`ChatTurnError.rollback === 'kept_foreign_change'`:** use today's error path (`ErrorDisplay`, deck refetch, mode reconcile) with the failed-but-kept copy.
- **`restore_failed`** (whether it arrives from polling or from the poll after a failed `cancelChat`): show the server's `error_message`, which is the restore-pending copy, in `ErrorDisplay`. Refresh messages and the deck as `finishAfterRollback` does, without its notice. This is the only rule for `restore_failed`.
- **Network error, or 5xx from `cancelChat`:** poll the request once (`api.pollChat(requestId)`).
  - `status` is terminal with `rollback === 'restore_failed'`: apply the `restore_failed` rule below.
  - `status` is terminal with `rollback === 'rolled_back'`: `finishAfterRollback('cancelled')`.
  - still live: `ErrorDisplay` with the stop-failed copy; generation carries on.

- [ ] **Step 1: Write the failing tests.** Use the `vi.hoisted` / `vi.mock('../../services/api')` pattern of `ChatPanel.errorRefetch.test.tsx`, but render the **real** `ChatInput` so the stop button is exercised.
  - `test_stop_during_planning_is_instant` (no dialog; `cancelChat` called with the id)
  - `test_stop_during_building_asks_first_with_keep_focused`
  - `test_keep_generating_closes_dialog_without_cancel`
  - `test_stop_and_discard_cancels`
  - `test_escape_triggers_same_stop`
  - `test_escape_with_dialog_open_does_not_stop` (Review Focus 5): mount the real `ConfirmDialog` and the hook together, re-render ChatPanel while the dialog is open, then press Escape. The dialog closes, `cancelChat` is not called, and the dialog does not reopen.
  - `test_stop_before_request_accepted_is_sent_once_accepted` (Review Focus 1)
  - `test_pending_stop_from_failed_send_does_not_cancel_next_send`
  - `test_cancel_500_then_poll_restore_failed_shows_restore_pending`
  - `test_after_cancel_messages_replaced_draft_restored_deck_restored_notice_shown`
  - `test_dialog_closes_when_turn_completes`
  - `test_already_finished_keeps_result`
  - `test_refused_shows_notice_and_keeps_generating`
  - `test_failure_rolled_back_behaves_like_stop_with_failed_notice`
  - `test_failure_kept_foreign_change_uses_error_display`
  - `test_no_stop_on_legacy_deck`
  - `useEscapeToStop`: `test_ignores_when_inactive`, `test_ignores_default_prevented`, `test_ignores_when_dialog_present`, `test_ignores_escape_in_text_input`, `test_ignores_escape_inside_escape_owner`
  - `test_no_stop_in_sse_mode`
  - `test_first_generation_after_empty_rollback_renders` (AppLayout: roll back to empty, then a fresh version-1 deck shows)
- [ ] **Step 2:** `cd frontend && npx vitest run src/components/ChatPanel/ChatPanel.stop.test.tsx src/components/ChatPanel/useEscapeToStop.test.tsx`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Re-run. Expected: PASS. Then `npx vitest run` (the whole suite) and `npm run typecheck && npm run lint`. Expected: no new failures.
- [ ] **Step 5:** Commit: `feat(chat-ui): stop generation with confirmation, Escape, and rollback outcomes`.

Models: test=opus impl=sonnet

---
