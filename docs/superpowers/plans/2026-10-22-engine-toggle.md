# Deck Mode Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. In this repo also load `executing-plans-tellr` (CLAUDE.md): it adds the plan-vs-code pre-pass, sabotage verification of every approved test, and the `Models:` tiering below. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the typed `USE LEGACY MODE` opt-out with a "Mode" dropdown under the chat box. The deck's mode is stored in a `user_sessions.deck_mode` column that is set once, with the deck's first message, and never changes.

**Architecture:**
- `deck_mode` is NULL until a deck's first user message. That message's transaction sets the column with a conditional `UPDATE … WHERE deck_mode IS NULL` on the owner row, and changes pins to match the mode.
- Engine resolution reads the column, and the UI reads it from the session response.
- The phrase helpers, the startup pin backfill and the SSE turn-1 re-resolve are deleted.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy (SQLite locally, Postgres/Lakebase deployed), pytest via `uv run`; React + TypeScript, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-22-engine-toggle-design.md` (revision 2). Executors read it alongside this plan. Section numbers below (§N) refer to it.

## Global Constraints

- Stored values are exactly `"agent"` and `"legacy"`. NULL means not chosen, i.e. unlocked. The column is `deck_mode VARCHAR(16)`, nullable. The request and response field is `deck_mode` everywhere.
- The engine mapping is `legacy` → `"monolith"`, while `agent` and NULL → `"graph"`. The job payload key stays `engine_mode`, and `job_queue`'s `"monolith"` default is unchanged.
- The UI copy is exact:
  - Label `Mode`.
  - Options `Agent mode` / `Legacy mode`.
  - Hint line `Enter to send · Shift+Enter new line`.
  - Popup lines:
    - `Agent mode: plans the deck, then builds it slide by slide, showing progress as it goes.`
    - `Legacy mode: a less capable agent. Usually faster, but harder to converse with and to adapt to changes.`
    - `You can change this until you send your first message. After that it's fixed for this deck.`
- A locked deck receiving a different mode answers HTTP **409** with `detail = {"code": "deck_mode_locked", "message": <plain sentence>, "deck_mode": <stored>}`, and saves no message.
- Python runs through `uv run` in this worktree's `.venv`. Never `pip install`.
- Every Playwright or dev-server run is wrapped as `~/tellr-loop/bin/e2e-lock acquire superpowers && … ; ~/tellr-loop/bin/e2e-lock release superpowers`.
- No local Postgres, so `*_postgres.py` tests skip. **A skip is not a pass.** Report them as "not run".
- No push, PR, issue, publish-dev or deploy without asking the user.
- Commit messages end with `Co-authored-by: Isaac <no-reply@databricks.com>`.
- Brief and spec line numbers have drifted, so locate code by symbol.
- **One pin rule at session creation:** `deck_mode="legacy"` is never pinned, whatever `graph_capable` says; `deck_mode="agent"` is always pinned; `deck_mode=None` follows `graph_capable`, as today.
- **Known, accepted gap: sync `POST /chat`.**
  - It neither sends nor writes `deck_mode`.
  - A deck whose first message arrived through it stays NULL, so it shows as unlocked despite having messages, and its next routed message locks it.
  - The UI never calls `/chat`, so this is not fixed here.
- The e2e lock is broken automatically after **45 minutes** (`~/tellr-loop/bin/e2e-lock`). A full Playwright run that may approach that must be split, or re-acquired between runs.
- **Merge gate:** the branch is not done or mergeable until one of the Final verification Postgres options (step 2) has run.

## Review Focus

1. **A first send that fails *after* its message commits** (e.g. engine resolution 503s, or `enqueue_job` raises). The deck is locked, which is correct because a first message exists, and the UI must show it locked after re-reading the session. → Task 4 (backend) and Task 7 (UI re-read).
2. **Switching decks after picking Legacy on an unlocked deck.** The next unlocked deck must start on Agent mode, not inherit the selection. → Task 7.
3. **A first message with attached images on `/chat/stream`.** The route now persists the message, so it must be persisted exactly once, with the raw text the user typed (as `/chat/async` does), not twice and not with injected image context. → Task 4.
4. **Read-only and preview views** (CAN_VIEW users, save-point preview) show the control disabled with the deck's mode, never an enabled Agent default. → Task 8.
5. **A stale tab** sends Legacy to a deck another tab already locked as Agent. It gets a 409, and the UI must end up showing Agent, locked, with no optimistic "Legacy" left on screen. → Task 7.

---

### Before Task 1 (orchestrator, not dispatched)

- [ ] **Plan-vs-code pre-pass** (executing-plans-tellr §2).
  - Verify every symbol, file and signature this plan names against the branch.
  - Write `PLAN-CORRECTIONS.md`, which overrides the plan, and point every dispatch at it.
  - Confirm that every task below carries a `Models:` tag.
- [ ] **Baseline cause-set** (§3). On the unmodified branch:
  - Run `uv run pytest tests/unit -q`, `uv run pytest tests/integration -q`, `cd frontend && npm run test:unit`, and the Playwright suite under the e2e lock.
  - Record each failing test's **cause**, not the count, and the SKIPPED list, in the ledger. Every later "no new failure causes" check diffs against this.

---

### Task 1: The `deck_mode` column and its run-once migration

**Models:** `test=opus impl=sonnet`. A migration mistake is silent and lands on every database.

**Files:**
- Modify: `src/domain/conversation_engine.py`. Add the Deck Mode constants and the mapping. Leave the phrase helpers for Task 6.
- Modify: `src/database/models/session.py`. Add `UserSession.deck_mode`.
- Modify: `src/core/database.py`. Add `_migrate_deck_mode_schema` and call it in `_run_migrations` immediately after `_migrate_conversation_pin_schema(...)`.
- Test: `tests/unit/test_database_migrations.py` (follow `test_conversation_pin_schema_migrates_pre_column_sqlite_table_idempotently`).

**Interfaces:**
- Produces:
  - `DECK_MODE_AGENT = "agent"`, `DECK_MODE_LEGACY = "legacy"`, and `DECK_MODES: frozenset[str]`.
  - `engine_mode_for_deck_mode(deck_mode: str | None) -> str`, which returns `"monolith"` for legacy and `"graph"` otherwise.
  - `UserSession.deck_mode: Column(String(16), nullable=True)`, with no ORM default and no server default.
  - `_migrate_deck_mode_schema(conn, inspector, schema, _qual, is_sqlite: bool) -> None`.

- [ ] **Step 1: Write the failing tests**
  - `test_deck_mode_migration_fills_existing_rows_with_legacy_and_leaves_new_rows_null(sqlite_engine)`:
    - Create a pre-column `user_sessions (id INTEGER PRIMARY KEY, session_id VARCHAR(64) NOT NULL)` with two rows, then run the migration.
    - Assert both rows have `deck_mode == 'legacy'`.
    - Insert a third row without `deck_mode` and assert it is NULL.
    - Assert the column is nullable.
  - `test_deck_mode_migration_second_run_is_a_noop(sqlite_engine)`:
    - Run the migration, set row 1 to `'agent'`, then run it again.
    - Assert row 1 is still `'agent'` and row 2 is still `'legacy'`.
  - `test_deck_mode_is_null_on_a_fresh_create_all_schema(sqlite_engine)`: after `Base.metadata.create_all`, insert a `UserSession` and assert `deck_mode is None`.
  - `test_engine_mode_for_deck_mode_maps_legacy_to_monolith_else_graph` (put it in the new file `tests/unit/test_deck_mode_resolution.py`). Assert:
    - `"legacy"` → `"monolith"`
    - `"agent"` → `"graph"`
    - `None` → `"graph"`

- [ ] **Step 2: Run them and confirm they fail**
  - Run: `uv run pytest tests/unit/test_database_migrations.py -k deck_mode tests/unit/test_deck_mode_resolution.py -v`
  - Expected: FAIL. `_migrate_deck_mode_schema` and `engine_mode_for_deck_mode` don't exist.

- [ ] **Step 3: Implement**
  - The migration branch is entered only when `deck_mode` is missing from `inspector.get_columns("user_sessions")`.
  - Postgres:
    - `ALTER TABLE <q> ADD COLUMN deck_mode VARCHAR(16) DEFAULT 'legacy'`
    - then `ALTER TABLE <q> ALTER COLUMN deck_mode DROP DEFAULT`
  - SQLite:
    - `ALTER TABLE <q> ADD COLUMN deck_mode VARCHAR(16)`
    - then `UPDATE <q> SET deck_mode = 'legacy'`
  - Both statements run on the caller's `conn`, which is inside `_run_migrations`' `engine.begin()`, so they commit together. Log one `logger.info` line, as the siblings do.

- [ ] **Step 4: Run the tests and confirm they pass.** Same command → PASS. Then run `uv run pytest tests/unit -x -q`. Expected: no new failure *causes* against the baseline (executing-plans-tellr §3).

- [ ] **Step 5: Commit**
  ```bash
  git add src/domain/conversation_engine.py src/database/models/session.py src/core/database.py tests/unit/test_database_migrations.py tests/unit/test_deck_mode_resolution.py
  git commit -m "feat(sessions): add deck_mode column with run-once legacy migration"
  ```

---

### Task 2: Resolution reads the column; the session API exposes it

**Models:** `test=opus impl=sonnet`

**Files:**
- Modify: `src/api/services/chat_service.py`. `resolve_engine_mode` reads `deck_owner.deck_mode` through the existing `_get_deck_owner_session` hop. Rewrite its docstring, which currently says "derived from the transcript".
- Modify: `src/api/services/session_manager.py`:
  - `create_session(..., deck_mode: Optional[str] = None)` raises `ValueError` if the value isn't in `DECK_MODES` or None, and stores it. It applies the Global Constraints pin rule: legacy is never pinned, agent is always pinned, and None follows `graph_capable`.
  - Both return dicts of `create_session` and `get_session` gain `"deck_mode"`. In `get_session` the value comes from the **owner** (`deck_owner.deck_mode`).
- Test: `tests/unit/test_deck_mode_resolution.py`.
- Modify (keep green): `tests/unit/test_engine_mode_selection.py` and `tests/unit/test_engine_mode_wiring.py`. Every assertion that derives the engine from a seeded phrase must seed `deck_mode` on the owner row instead. Delete the phrase-semantics tests whose subject is removed in Task 6. Keep the fail-closed and `engine_mode`-key tests.

**Interfaces:**
- Consumes: Task 1 constants and `engine_mode_for_deck_mode`.
- Produces:
  - `resolve_engine_mode(session_id) -> "graph" | "monolith"`, column-based. The "missing session → monolith" answer is unchanged.
  - `create_session(..., deck_mode=None)`.
  - The session dicts' `deck_mode: str | None`.

- [ ] **Step 1: Write the failing tests** (in `test_deck_mode_resolution.py`, using the sqlite + `_make_fake_db` patching pattern from `test_engine_mode_wiring.py`):
  - `test_a_legacy_owner_resolves_to_monolith`, `test_an_agent_owner_resolves_to_graph`, `test_an_unchosen_owner_resolves_to_graph`.
  - `test_a_contributor_resolves_through_its_owners_column`. The owner is legacy and the contributor's own row is NULL; assert `"monolith"`.
  - `test_the_phrase_in_the_first_message_no_longer_selects_legacy`. The owner is NULL and its earliest user row is `"USE LEGACY MODE build a deck"`; assert `"graph"`.
  - `test_get_session_reports_the_owners_deck_mode_for_a_contributor`.
  - `test_create_session_stores_deck_mode_and_rejects_unknown_values`. Assert that `"agent"` is stored, `None` is stored as NULL, and `"monolith"` raises `ValueError`.
  - `test_create_session_pin_follows_deck_mode`. Assert:
    - `(deck_mode="legacy", graph_capable=True)` → unpinned
    - `(deck_mode="agent", graph_capable=False)` → pinned
    - `(None, True)` → pinned
    - `(None, False)` → unpinned.

- [ ] **Step 2: Run and confirm they fail.** `uv run pytest tests/unit/test_deck_mode_resolution.py -v` → FAIL.

- [ ] **Step 3: Implement** the two changes above. `resolve_engine_mode` no longer calls `earliest_user_message`.

- [ ] **Step 4: Run and confirm they pass.** Run `uv run pytest tests/unit/test_deck_mode_resolution.py tests/unit/test_engine_mode_selection.py tests/unit/test_engine_mode_wiring.py -v` → PASS. Then run the whole unit suite and diff causes.

- [ ] **Step 5: Commit**: `feat(sessions): resolve the engine from deck_mode and expose it on sessions`.

---

### Task 3: The atomic first-message lock

**Models:** `test=opus impl=opus`. It is a single transaction with a race, pin invariants and rollback. Every mistake here is silent.

**Files:**
- Modify: `src/api/services/session_manager.py`:
  - Add `DeckModeLockedError` next to `SessionNotFoundError`.
  - Extract `_insert_user_message(self, db, session: UserSession, *, role: str, content: str, message_type: Optional[str], metadata: Optional[Dict[str, Any]], request_id: Optional[str]) -> SessionMessage` from the body of `add_message`. It does the insert, the flush and the `last_activity` bump on the **caller's** `db`. `add_message` keeps its signature and calls it.
  - Add `add_user_message(...)`.
  - In `get_or_create_contributor_session`, pin the new contributor only when `parent.deck_mode != "legacy"`.
- Test: `tests/unit/test_deck_mode_lock.py` (new). Seed an active `GraphRelease` the way `tests/unit/test_conversation_pin_creation.py` does.

**Interfaces:**
- Consumes: Task 1 constants and `lock_active_graph_release(db)` (`src/services/conversation_pins.py`).
- Produces:
  - `class DeckModeLockedError(Exception)`, with attribute `deck_mode: str` (the stored mode).
  - `SessionManager.add_user_message(self, session_id: str, content: str, *, message_type: str, request_id: Optional[str] = None, requested_deck_mode: Optional[str] = None) -> Dict[str, Any]`.
    - It returns the same keys as `add_message`, plus `"deck_mode": str` (the deck's mode after the call) and `"locked_now": bool`.

**The algorithm.** Everything runs in one `get_db_session()` block, so any raise rolls all of it back:
1. Load the session and `owner = _get_deck_owner_session(db, session)`.
2. If `owner.deck_mode is None`, set `chosen = requested_deck_mode or "agent"` and execute `update(UserSession).where(UserSession.id == owner.id, UserSession.deck_mode.is_(None)).values(deck_mode=chosen)`.
   - **rowcount 1:**
     - Set `locked_now = True`.
     - If `chosen == "legacy"`, set `graph_release_id = NULL` for `id == owner.id OR parent_session_id == owner.id`.
     - Else, if the owner's pin is NULL, set it to `lock_active_graph_release(db).release_id`.
   - **rowcount 0:** another writer won. Re-read with `db.refresh(owner, attribute_names=["deck_mode"])`. The identity-map copy still says NULL, so a plain attribute read is the bug this step exists to avoid.
3. If `requested_deck_mode is not None` and it `!=` the owner's mode, raise `DeckModeLockedError(owner_mode)` before any insert.
4. Call `self._insert_user_message(db, session, role="user", ...)` on **this** `db`. Never call `add_message`, which opens its own transaction and would split the lock from the insert.

- [ ] **Step 1: Write the failing tests**
  - `test_first_message_with_legacy_locks_legacy_and_clears_every_pin_on_the_deck`. The owner and two contributors are pinned. Afterwards the owner's `deck_mode == "legacy"`, all three `graph_release_id is None`, the message row exists, and `locked_now is True`.
  - `test_first_message_with_no_mode_locks_agent`.
  - `test_first_message_with_agent_pins_an_unpinned_owner`.
  - `test_a_contributors_first_message_locks_the_owners_deck`. The owner's column is set; the contributor's own row stays NULL.
  - `test_a_different_mode_on_a_locked_deck_raises_and_saves_nothing`. Assert that `pytest.raises(DeckModeLockedError)` gives `.deck_mode == "agent"`, the message count is unchanged, and the column is unchanged.
  - `test_the_same_mode_or_no_mode_on_a_locked_deck_saves_the_message`.
  - `test_two_first_messages_interleaved_exactly_one_mode_wins`. This is the spec §12 race row, interleaved deterministically.
    - Use a **file-backed** SQLite DB under `tmp_path`, not `:memory:`/StaticPool, so there are two real connections.
    - Wrap `SessionManager._get_deck_owner_session`. On its first call only, after it returns the (NULL) owner, run a complete competing `add_user_message(contributor_sid, ..., requested_deck_mode="agent")` in its own `get_db_session()` and commit it.
    - The outer call, with `requested_deck_mode="legacy"`, must then hit rowcount 0, refresh, and raise `DeckModeLockedError` with `.deck_mode == "agent"`.
    - Afterwards the owner is `"agent"`, exactly one user row exists (the winner's), and the pins match agent.
    - Sabotage check: removing the `db.refresh` must turn this red.
    - The true concurrent race is Postgres-only and recorded as **not run**.
  - `test_a_lock_already_set_before_the_call_is_honoured`. Set the owner to `"agent"` directly, then call with `"legacy"` → `DeckModeLockedError`.
  - `test_a_failed_message_insert_rolls_back_the_lock_and_the_pins`. Patch `_insert_user_message` to raise. Afterwards the column is NULL and the pins are unchanged. Sabotage check: making `add_user_message` call `add_message` instead must turn this red.
  - `test_legacy_deck_mutation_provenance_records_no_graph_version` (spec §12, §5.5):
    - After a legacy lock, take `deck_mutation_context` for the owner and record a mutation through the existing path, e.g. the helper `tests/unit/test_conversation_pin_creation.py` or the shared-deck attribution tests use.
    - Assert the `SharedDeckMutationEvent` row has `graph_release_id is None` and `graph_version is None`.
  - `test_a_new_contributor_on_a_legacy_deck_is_unpinned` and `test_a_new_contributor_on_an_unlocked_deck_is_pinned`.
  - `test_a_mutation_snapshot_taken_before_a_legacy_lock_is_rejected`:
    - Take `deck_mutation_context(...)` on an unlocked pinned deck, then lock it legacy via `add_user_message`.
    - Then call `record_shared_deck_mutation` with the stale actor. It raises `ValueError("mutation actor pin does not match its persisted pin")`, and the deck is unchanged after rollback.

- [ ] **Step 2: Run and confirm they fail.** `uv run pytest tests/unit/test_deck_mode_lock.py -v` → FAIL (no `add_user_message`).

- [ ] **Step 3: Implement** the algorithm above.

- [ ] **Step 4: Run and confirm they pass.** Run the file → PASS. Then `uv run pytest tests/unit/test_deck_contributor_model.py tests/unit/test_deck_contributor_routes.py tests/unit/test_conversation_pin_creation.py -q` → PASS.

- [ ] **Step 5: Commit**: `feat(sessions): lock deck_mode atomically with the first user message`.

---

### Task 4: Chat routes carry the mode; the stream route persists first

**Models:** `test=opus impl=sonnet`. The plan fixes the order of operations; the risk is a lock leak on a new error path, which the tests below pin.

**Files:**
- Modify: `src/api/schemas/requests.py`. Add `ChatRequest.deck_mode: Optional[Literal["agent", "legacy"]] = None`.
- Modify: `src/api/routes/chat.py`:
  - Add `DECK_MODE_LOCKED_CODE = "deck_mode_locked"` and `_deck_mode_locked(exc: DeckModeLockedError) -> HTTPException`. It returns a 409 whose detail has the code, a message (`"This deck's mode is already set to {Agent mode|Legacy mode}, and it can't be changed."`) and `deck_mode`.
  - **Error mapping for the `add_user_message` call, on both routes.** The lock must be released on **every** exit:

    | Error | Response | Also |
    |---|---|---|
    | `DeckModeLockedError` | 409 (`_deck_mode_locked`) | |
    | `ActiveGraphReleaseUnavailableError` (an agent first message, with no active release to pin) | 503 with the existing detail `"No active Graph Release available"` | Nothing is saved and the deck stays unlocked, because the transaction rolled back |
    | Any other exception | Release the lock and re-raise, giving the existing 500 | |

    On async, the first two also run `update_chat_request_status(request_id, "error", <code>)`.
  - **`POST /chat/async`:** replace its `session_manager.add_message(role="user", …)` with `add_user_message(..., message_type="user_query", request_id=request_id, requested_deck_mode=request.deck_mode)`, then apply the mapping above. Its existing final `except Exception` already releases the lock; the two typed errors need their own clauses ahead of it.
  - **`POST /chat/stream`:** after acquiring the session lock and **before** `resolve_engine_mode_or_unavailable`:
    - compute `is_first_message = get_session(...)["message_count"] == 0`
    - call `add_user_message(..., content=request.message, message_type="user_input", requested_deck_mode=request.deck_mode)` inside a `try` that applies the mapping above.
    - pass `is_first_message_override=is_first_message, user_message_persisted=True` to `send_message_streaming`.
  - `_maybe_create_session`: both `graph_capable=selects_graph_engine(request.message)` become `graph_capable=True`.
- Modify: `src/api/services/chat_service.py`:
  - `send_message_streaming(..., user_message_persisted: bool = False)`. Its user-message `add_message` runs only when `not request_id and not user_message_persisted`.
  - **Delete** the SSE turn-1 re-resolve block (the `if not request_id: … resolve_engine_mode_or_unavailable(session_id)` after the persist).
  - The two `graph_capable=selects_graph_engine(message)` auto-create calls (in `send_message` and `send_message_streaming`) become `graph_capable=True`.
- Test: `tests/unit/test_deck_mode_routes.py` (new). Build the harness like `route_env` in `test_engine_mode_wiring.py`, but with the **real** `SessionManager` on the sqlite factory. Patch only permission, `get_chat_service` and `enqueue_job`, and seed an active `GraphRelease`.
- Modify (keep green): `tests/unit/test_engine_mode_wiring.py`, `tests/unit/test_remaining_creation_locks.py`, `tests/unit/test_session_naming.py`, `tests/unit/test_chat_service_no_singleton.py`, `tests/integration/test_graph_mode_turn.py`. Assertions about the turn-1 re-resolve (e.g. `TestStreamingRouteCannotSeeTurnOne`) are deleted, not rewritten, because their subject is gone.

**Interfaces:**
- Consumes: Task 3 `add_user_message` and `DeckModeLockedError`; Task 2 `resolve_engine_mode`.
- Produces: the request body field `deck_mode`, and the 409 contract in Global Constraints. The frontend (Task 7) relies on both.

- [ ] **Step 1: Write the failing tests**
  - `test_async_first_message_with_legacy_enqueues_monolith_and_locks_legacy`. The enqueue payload has `engine_mode == "monolith"`, and the owner column is `"legacy"`.
  - `test_stream_first_message_with_legacy_runs_monolith_on_turn_one`:
    - The service is called with `engine_mode="monolith"`, `user_message_persisted=True`, `is_first_message_override=True`.
    - Exactly one user row exists when the service is called. Assert inside the mock's side effect.
  - `test_a_first_message_with_no_deck_mode_locks_agent` (both routes; parametrize).
  - `test_the_typed_phrase_is_ordinary_text`. `"USE LEGACY MODE …"` with no `deck_mode` gives `"graph"` / agent.
  - `test_a_different_mode_on_a_locked_deck_is_a_409_and_saves_nothing` (both routes). Assert:
    - status 409 and `detail["code"] == "deck_mode_locked"`, `detail["deck_mode"] == "agent"`
    - the user row count is unchanged
    - the session lock is released: `is_processing` is False, or `acquire_session_lock` succeeds again
    - for async only, the chat request status is `"error"`.
  - `test_a_locked_legacy_deck_with_no_deck_mode_proceeds_on_monolith`.
  - `test_resolution_failure_after_the_first_message_leaves_the_deck_locked` (Review Focus 1). Patch `resolve_engine_mode_or_unavailable` to raise `PersistedConfigurationUnavailableError`. The response is 503, the message row and the column stay set, and the lock is released.
  - `test_stream_persists_the_raw_message_once_when_images_are_attached` (Review Focus 3). With `image_ids=["img-1"]`, there is exactly one user row, its content equals `request.message`, and the service receives `user_message_persisted=True`.
  - `test_an_unknown_deck_mode_is_a_422`.
  - `test_no_active_graph_release_on_an_agent_first_message_is_a_503_and_leaves_the_deck_unlocked` (both routes). Seed no active release. Assert:
    - the response is 503
    - the owner column is NULL
    - no user row exists
    - the lock is released
    - (async) the chat request status is `"error"`.
  - `test_an_unexpected_error_while_saving_the_first_message_releases_the_lock` (both routes). Patch `add_user_message` to raise `RuntimeError`. Assert a 500, then that `acquire_session_lock(sid)` returns True.

- [ ] **Step 2: Run and confirm they fail.** `uv run pytest tests/unit/test_deck_mode_routes.py -v` → FAIL.

- [ ] **Step 3: Implement** the route and service changes above.

- [ ] **Step 4: Run and confirm they pass.** Run the new file plus the five keep-green files → PASS. Then run the full unit suite and diff causes.

- [ ] **Step 5: Commit**: `feat(chat): carry deck_mode on chat requests and lock it with the first message`.

---

### Task 5: Duplicates, MCP and the tour set the mode at creation

**Models:** `test=opus impl=sonnet`

**Files:**
- Modify: `src/api/services/session_manager.py`, `duplicate_session`:
  - `new_session.deck_mode = deck_owner.deck_mode`.
  - Pin iff `deck_owner.deck_mode != "legacy"`. A NULL (unlocked) source is pinned like any new deck (spec §5.3, as corrected in revision 2).
  - **Delete** the marker-row carry, the `_selects_agent_mode` import and `source_is_graph`.
  - The log `extra` key `carried_engine_mode_marker` becomes `deck_mode`.
- Modify: `src/api/mcp_server.py`:
  - `create_session(..., graph_capable=False, deck_mode="legacy")`.
  - Persist the prompt verbatim: drop `with_legacy_marker` and its import, and rewrite the comment block above it.
- Modify: `src/api/routes/tour.py`. `create_session(..., graph_capable=True, deck_mode="agent")`, and rewrite the phrase comment.
- Tests:
  - `tests/unit/test_session_duplicate.py` (add cases).
  - `tests/unit/test_mcp_server.py` (rewrite the phrase-prepend tests).
  - `tests/unit/test_tour_ships_a_spec.py` (add the mode assertion).

**Interfaces:**
- Consumes: Task 2 `create_session(deck_mode=...)`.
- Produces: nothing new.

- [ ] **Step 1: Write the failing tests**
  - `test_duplicate_of_an_agent_deck_is_agent_and_pinned`.
  - `test_duplicate_of_a_legacy_deck_is_legacy_unpinned_and_carries_no_message`. The duplicate's `message_count == 0`.
  - `test_duplicate_of_an_unlocked_deck_is_unlocked_and_pinned`.
  - `test_duplicate_of_a_contributor_view_copies_the_owners_mode`.
  - `test_mcp_create_deck_is_legacy_unpinned_and_persists_the_prompt_verbatim`. The persisted first message `== prompt`, with no `"USE LEGACY MODE"` substring.
  - `test_the_tour_deck_is_agent_and_pinned`.

- [ ] **Step 2: Run and confirm they fail.** Run the three files with `-k "deck_mode or verbatim or agent_and_pinned or legacy_unpinned or unlocked"` → FAIL.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run and confirm they pass.** Run the three files plus `tests/unit/test_duplicate_session_carries_spec.py` → PASS.

- [ ] **Step 5: Commit**: `feat(sessions): duplicates, MCP and tour set deck_mode at creation`.

---

### Task 6: Delete the phrase, the backfill and the dead tests; update the glossary

**Models:** `test=opus impl=sonnet`. This is wide but mechanical. The test author's job here is to decide keep/rewrite/delete for each phrase-referencing test, and to record that decision in the commit body.

**Files:**
- Modify: `src/domain/conversation_engine.py`:
  - Delete `LEGACY_MODE_PHRASE`, `AGENT_MODE_PHRASE`, `selects_legacy_engine`, `selects_graph_engine` and `with_legacy_marker`.
  - Keep `ENGINE_MODE_MARKER_MESSAGE_TYPE` and `is_transcript_message`.
  - Rewrite the module docstring and the marker comment: the row now exists only for title suppression.
- Modify: `src/api/services/chat_service.py`:
  - Delete `_selects_agent_mode` and the phrase imports and re-exports (`AGENT_MODE_PHRASE as AGENT_MODE_PHRASE`, etc.).
  - Rewrite the docstrings of `clear_context` and `delete_message`, which say the engine is read off the kept row. The code is unchanged.
- Modify: `src/api/services/session_manager.py`. Update the `earliest_user_message` docstring: its callers are now only clear and delete.
- Modify: `src/services/conversation_pins.py`. Delete `backfill_conversation_pins`, `_backfill_in_transaction`, `BackfillResult` and the phrase import.
- Modify: `packages/databricks-tellr-app/databricks_tellr_app/run.py`. Delete the "Backfilling Conversation Pins…" block.
- Modify: `tests/unit/test_startup_migrations.py`. Remove `backfill_conversation_pins` from the expected `calls` order, and delete `test_init_database_backfill_failure_aborts_before_later_stages`.
- Modify: `CONTEXT.md`. Add **Deck Mode** and amend **Conversation Pin**, worded exactly as spec §8.
- Delete or rewrite every remaining test reference to the deleted symbols. Find them with `grep -rln "LEGACY_MODE_PHRASE\|AGENT_MODE_PHRASE\|selects_legacy_engine\|selects_graph_engine\|with_legacy_marker\|backfill_conversation_pins\|_selects_agent_mode" tests`. Expect, at least:
  - `test_engine_mode_selection.py`, `test_clear_context.py`, `test_delete_message.py`, `test_earliest_user_message.py`
  - `tests/integration/test_conversation_pin_migration_postgres.py` (its backfill tests are deleted)
  - `test_conversation_creator_exclusions_postgres.py`, `test_architect_reply_is_persisted.py`, `test_graph_lifecycle_runtime_postgres.py`.

**Interfaces:** none produced.

- [ ] **Step 1: Write the failing tests**
  - `test_clear_chat_keeps_the_deck_locked_and_its_title` (in `test_clear_context.py`). On a locked legacy deck, after `clear_context`, `deck_mode == "legacy"`, the title is unchanged, and a following `add_user_message(requested_deck_mode="agent")` raises `DeckModeLockedError`.
  - `test_deleting_the_first_message_keeps_the_deck_locked` (in `test_delete_message.py`). The same three assertions after `delete_message` on the earliest user row.
  - `test_the_phrase_helpers_are_gone`. `hasattr(conversation_engine, name)` is False for each of the five names.
  - `test_init_database_no_longer_backfills_pins`. The expected `calls` list has no backfill entry.

- [ ] **Step 2: Establish red.**
  - The clear and delete tests are **expected to pass already**, because the lock exists since Task 3. For them the red step is sabotage:
    - Make `clear_context` and `delete_message` set the owner's `deck_mode = None`.
    - Confirm both tests go red, then restore and confirm green.
    - Grep for the marker to prove the sabotage sat on the executed path.
  - The last two tests FAIL normally (the symbols still exist).

- [ ] **Step 3: Implement the deletions** and the docstring/glossary edits.

- [ ] **Step 4: Run and confirm everything passes.**
  - `grep -rn "LEGACY_MODE_PHRASE\|AGENT_MODE_PHRASE\|selects_graph_engine\|with_legacy_marker\|backfill_conversation_pins" src packages tests` returns nothing.
  - `uv run pytest tests/unit -q` shows no new failure causes.
  - `uv run pytest tests/integration -q`: Postgres files report SKIPPED, which is recorded as *not run*.

- [ ] **Step 5: Commit**: `refactor(engine): remove the USE LEGACY MODE phrase and the startup pin backfill`. The body lists each test file kept, rewritten or deleted.

---

### Task 7: Frontend state: the selection, the stored mode, and sending it

**Models:** `test=opus impl=sonnet`

**Files:**
- Modify: `frontend/src/services/api.ts`:
  - `export type DeckMode = 'agent' | 'legacy'`.
  - `Session` gains `deck_mode?: DeckMode | null`.
  - A trailing `deckMode?: DeckMode` parameter is threaded through `sendChatMessage` → `startPolling` → `submitChatAsync` and `streamChat`. Both request bodies add `deck_mode: deckMode`.
  - Check for a second mirror of the `Session` fields (spec §10).
- Modify: `frontend/src/contexts/SessionContext.tsx`:
  - `OptionalSessionInfo.deck_mode?: DeckMode | null`.
  - The context adds:
    - `storedDeckMode: DeckMode | null` (the server's value; null means unlocked)
    - `selectedDeckMode: DeckMode` (default `'agent'`)
    - `setSelectedDeckMode(mode: DeckMode): void`
    - `setStoredDeckMode(mode: DeckMode | null): void`
  - `createNewSession` resets both (null / `'agent'`).
  - `switchSession` sets `storedDeckMode` from `sessionInfo.deck_mode ?? null` and resets `selectedDeckMode` to `'agent'`.
  - **`switchSession`'s `existingSessionInfo` branch rebuilds `sessionInfo` from a field whitelist. Add `deck_mode` to it.** Without that, restoring through that branch drops the mode.
- Modify: `frontend/src/components/Layout/AppLayout.tsx`, `loadSessionFromServer`. This is the URL-restore and reload path, and it builds the `existingSessionInfo` literal field by field. Add `deck_mode: sessionInfo.deck_mode`.
- Modify: `frontend/src/components/ChatPanel/ChatPanel.tsx`, `handleSendMessage`:
  - `const deckMode = storedDeckMode ?? selectedDeckMode`, passed to `api.sendChatMessage`.
  - If `storedDeckMode === null`, call `setStoredDeckMode(deckMode)` before the call (optimistic lock).
  - Add `reconcileDeckModeAfterError(sentTo: string | null, seq: number): void`. It calls `api.getSession(sentTo)` and then `setStoredDeckMode(session.deck_mode ?? null)`, guarded like `refreshMessageIds` (`sendSeqRef` / `currentSessionIdRef`).
  - Call it **at both failure paths**, next to each existing `refetchDeckAfterError(sentTo, seq)` call: the SSE `error` event and the transport `onError`.
  - **If the re-read itself fails, change nothing.** The optimistic lock stays, and the turn's existing error message is already showing.
- Tests: `frontend/src/components/ChatPanel/ChatPanel.deckMode.test.tsx` (new; follow `ChatPanel.clearChat.test.tsx` for mocking `api` and providers) and `frontend/src/contexts/SessionContext.test.tsx` (create it if absent).

**Interfaces:**
- Consumes: Task 4's `deck_mode` body field and 409 contract; Task 2's `deck_mode` on `GET /api/sessions/{id}`.
- Produces: `DeckMode`, and the four SessionContext members above. Task 8 renders from them.

- [ ] **Step 1: Write the failing tests**
  - `sends deck_mode "legacy" when Legacy mode is selected on an unlocked deck`. The 8th argument of `api.sendChatMessage` is `'legacy'`.
  - `sends the stored mode, not the selection, on a locked deck`.
  - `locks optimistically on send`. `storedDeckMode` becomes the sent mode before the request resolves.
  - `re-reads the session after a failed send and shows the server's mode` (Review Focus 1 and 5). `onError` fires and `getSession` resolves `{deck_mode: 'agent'}`, so `storedDeckMode === 'agent'`. If it resolves `{deck_mode: null}`, the deck is unlocked again.
  - `re-reads the session after an SSE error event too`. The stream emits an `error` event (not `onError`), and `getSession` is called with the sent-to id.
  - `keeps the optimistic lock when the re-read fails`. `getSession` rejects, and `storedDeckMode` stays the sent mode.
  - `restores the stored mode through the existingSessionInfo branch`. `switchSession(id, {title: 't', deck_mode: 'legacy'})` gives `storedDeckMode === 'legacy'`, with no `getSession` call.
  - `switching decks resets the selection to Agent mode` (Review Focus 2). After `setSelectedDeckMode('legacy')` and then `switchSession` to an unlocked deck, `selectedDeckMode === 'agent'` and `storedDeckMode === null`.
  - `new session starts unlocked on Agent mode`.

- [ ] **Step 2: Run and confirm they fail.** `cd frontend && npx vitest run src/components/ChatPanel/ChatPanel.deckMode.test.tsx src/contexts/SessionContext.test.tsx` → FAIL.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run and confirm they pass.** Same command → PASS. Then `npm run test:unit` has no new failure causes, and `npx tsc --noEmit -p .` (or the repo's typecheck script) is clean.

- [ ] **Step 5: Commit**: `feat(ui): track and send the deck's mode`.

---

### Task 8: Frontend UI: the Mode dropdown, and hiding agent furniture on legacy decks

**Models:** `test=opus impl=sonnet`

**Files:**
- Create: `frontend/src/components/ChatPanel/DeckModeSelect.tsx`:
  - `export function DeckModeSelect(props: { value: DeckMode; locked: boolean; onChange: (mode: DeckMode) => void })`.
  - It renders the `Mode` label, a native `<select aria-label="Mode" data-testid="deck-mode-select" disabled={locked}>` with options `Agent mode` (`agent`) and `Legacy mode` (`legacy`), and an info icon (`data-testid="deck-mode-info"`).
  - The icon's tooltip, from `src/ui/tooltip`, holds the three exact popup lines from Global Constraints. Style it like the `AgentConfigBar` selects, at the hint line's size (`text-xs`).
- Modify: `frontend/src/components/ChatPanel/ChatInput.tsx`:
  - New prop `modeControl?: React.ReactNode`.
  - The hint text becomes exactly `Enter to send · Shift+Enter new line`.
  - The right side of the hint row renders the existing line/char counter (when typing) followed by `modeControl`.
- Modify: `frontend/src/components/ChatPanel/ChatPanel.tsx`. Pass `modeControl={<DeckModeSelect value={storedDeckMode ?? selectedDeckMode} locked={storedDeckMode !== null || disabled || !!viewOnlyReason || previewMessages != null} onChange={setSelectedDeckMode} />}`.
- Modify: `frontend/src/components/Layout/AppLayout.tsx`:
  - Read `storedDeckMode` and `selectedDeckMode` from `useSession()`, and compute `const isLegacyDeck = (storedDeckMode ?? selectedDeckMode) === 'legacy'`.
  - Render `GraphVersionStatus` and the `surface="conversation"` `MixedReleaseWarning` only when `!isLegacyDeck`. The Share-dialog `surface="collaboration"` instance is untouched.
- Tests:
  - `frontend/src/components/ChatPanel/DeckModeSelect.test.tsx` (new)
  - `frontend/src/components/ChatPanel/ChatInput.test.tsx` (**new**; no such file exists)
  - `frontend/tests/e2e/deck-mode-toggle.spec.ts` (new; mock the API with `page.route` like `conversation-graph-version.spec.ts`).

**Interfaces:**
- Consumes: Task 7's SessionContext members and `DeckMode`.

- [ ] **Step 1: Write the failing tests**
  - DeckModeSelect:
    - `shows Mode with Agent mode and Legacy mode options`
    - `is disabled and shows the stored mode when locked`
    - `calls onChange with "legacy"`
    - `the info popup shows the three exact lines` (hover or focus, then `findByText` each line verbatim)
    - `the popup still opens when locked`.
  - ChatInput:
    - `renders the shortened hint`. The exact string is present, and "Press Enter to send" is absent.
    - `renders the mode control slot`.
  - ChatPanel (extend Task 7's file): `the control is disabled in a read-only or preview view` (Review Focus 4). Assert this with `disabled`, then with `viewOnlyReason`, then with `previewMessages=[]`.
  - e2e `deck-mode-toggle.spec.ts`:
    - `choosing Legacy hides the version badge, sends deck_mode legacy, then locks the control`. The `graph-version-status` testid disappears once Legacy is selected. The `/api/chat/stream` request body has `deck_mode: 'legacy'`. Afterwards `deck-mode-select` is disabled.
    - `a locked legacy deck opens greyed on Legacy with no badge, loaded by URL`. Use `page.goto('/sessions/<id>/edit')`, so the `loadSessionFromServer` restore path is exercised. The mocked `GET /api/sessions/{id}` returns `deck_mode: 'legacy'`, and the test also reloads the page and re-asserts.

- [ ] **Step 2: Run and confirm they fail.**
  - Run `npx vitest run src/components/ChatPanel/DeckModeSelect.test.tsx src/components/ChatPanel/ChatInput.test.tsx src/components/ChatPanel/ChatPanel.deckMode.test.tsx` → FAIL.
  - Then run `~/tellr-loop/bin/e2e-lock acquire superpowers && npx playwright test tests/e2e/deck-mode-toggle.spec.ts; ~/tellr-loop/bin/e2e-lock release superpowers` → FAIL.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run and confirm everything passes.**
  - The same vitest command → PASS.
  - The full `npm run test:unit` shows no new causes.
  - The full Playwright suite runs under the e2e lock, which auto-breaks at 45 minutes. If the suite runs long, split it by spec file and re-acquire between parts. Fix any body-shape assertion that now sees `deck_mode` in chat bodies. `tests/fixtures/graphLifecycleContract.json` pins only `POST /sessions`; if a chat-body pin breaks, update the fixture and record why.

- [ ] **Step 5: Commit**: `feat(ui): Mode dropdown under the chat box; hide agent-only status on legacy decks`.

---

## Final verification (after Task 8; superpowers:verification-before-completion)

1. `uv run pytest tests/unit -q`, `uv run pytest tests/integration -q`, `cd frontend && npm run test:unit`, and the full Playwright suite under the e2e lock. Record pass/fail *causes* and SKIPPED counts in the ledger.
2. **Postgres proof. Ask the user before doing anything here.** The migration's Postgres branch and the `*_postgres.py` suites have not run. Propose either:
   - (a) a devloop deploy via the `deploy-tellr-dev` skill (push, then `publish-dev.yml`, then `deploy_local.sh … --env devloop`), then check the boot log for the migration line and run a SQL check that existing rows read `legacy` and new decks read NULL; or
   - (b) a Postgres the user provides, to run the `*_postgres.py` files.

   Until one has run, report them as **not run**. **The branch is not done or mergeable until (a) or (b) has run green** (spec §12; Global Constraints merge gate).
3. Whole-branch review on Opus (executing-plans-tellr §7): pass it the ledger's parked list and ask for a merge/no-merge verdict.
