# Task 8 report: explicit failures that preserve conversation state; every creator needs a pin (AC3, AC2)

**Status:** DONE_WITH_CONCERNS. This task makes production changes under C24/C47 and C52. It found one production inconsistency and did not fix it (concern 1).

## Commits
TASK_BASE is `38a575511`. The controller's ledger-only `0ae480a37` sits directly on top of it, and it is expected.

1. `332f91a4a` `fix: typed pinned-runtime errors survive context managers and LangGraph nodes (#271 C52)`. It touches:
   - `src/services/persisted_graph_release.py`;
   - `tests/unit/test_persisted_graph_release.py`, which gets 7 new tests.
2. `68d81f810` `fix: engine-mode resolution fails closed at all three chat sites (#271 C24/C47)`. It touches:
   - `src/api/routes/chat.py` and `src/api/services/chat_service.py`;
   - `tests/unit/test_engine_mode_wiring.py`: the four ws4d tests inverted, plus the new service-site class;
   - `tests/conftest.py`: the new fixture `engine_mode_resolves_to_monolith`;
   - the five C47(c) files, which opt in to that fixture.
3. `1e7cf9499` `test: explicit Lakebase-contract failures preserve conversation state (#271)`. It touches:
   - `tests/integration/test_lakebase_contract_failures_postgres.py` (new, 22 tests);
   - `.github/workflows/test.yml` (enrolled in `integration-graph` after the Task 7 file);
   - `tests/unit/test_ci_collects_integration_tests.py` (a new pin).
4. This report, force-added, together with the mutation runner at `reports/t271-8-run_mut.py`.

## Production changes
### C52: context-manager-safe typed errors (`persisted_graph_release.py`)
- **The mechanism.** `PersistedConfigurationUnavailableError` and `PinnedInvocationEndpointError` are now `@_context_manager_safe @dataclass(frozen=True)`, with slots dropped.
  - `_context_manager_safe` wraps the frozen `__setattr__` and `__delattr__`. It lets through exactly `__traceback__`, `__cause__`, `__context__`, `__suppress_context__` and `__notes__`.
  - Fields still raise `FrozenInstanceError`.
  - `__str__`, `__post_init__` (the `args`), eq/hash and repr are unchanged.
- **Why dropping slots alone is not enough.** A plain frozen dataclass also refuses `exc.__traceback__ = tb`, and it raises `FrozenInstanceError`, which is mutation M6c.
- **A second trigger.** RED showed that LangGraph also calls `add_note` ("During task with name …") on every node error. So `__notes__` has to be writable too.

### C24/C47: engine-mode resolution fails closed
- **The wrapper.** `resolve_engine_mode_or(session_id, fallback)` is **removed**. It is replaced by `resolve_engine_mode_or_unavailable(session_id)`, which takes no fallback.
  - On any exception it logs the error class only, then raises `PersistedConfigurationUnavailableError(code="lakebase_unavailable")`, chained from the original.
  - `resolve_engine_mode`'s three "no answer → monolith" cases are unchanged, and its docstring is updated.
- **`/chat/stream` (`chat.py`, the resolution after the lock).** It catches the typed error, **releases the session lock explicitly**, then raises `HTTPException(503, detail=ENGINE_MODE_UNAVAILABLE_DETAIL)`.
  - The response has not started at this point, so the generator's `finally` would never run.
  - The detail is `{"code": "lakebase_unavailable", "message": "Conversation configuration is temporarily unavailable. Please retry."}`: a stable code with no internal text.
- **`/chat/async`.** It gets a new `except PersistedConfigurationUnavailableError` clause **ahead of** `except Exception` (C47(a)). The clause releases the lock and answers the same typed 503, where the generic handler would have answered a 500.
- **`chat_service.py` (the SSE re-resolve, formerly `:1141`).** On the typed error it yields the safe `pinned_graph_configuration_unavailable` event (C47(b)), then re-raises.
  - The route's SSE generator sees the pinned event, so it adds nothing else, and its `finally` releases the lock.
  - The event is built by a new `_pinned_graph_configuration_error_event()`, which the graph envelope now reuses as well.
- **C47(e): what stays after a failure. Documented in code comments and asserted in tests.**
  - On `/chat/async`, the user message and the `chat_requests` row (left `pending`, because no job was queued) stay.
  - On the SSE re-resolve, the user message that `send_message_streaming` persisted stays.
  - `/chat/stream`'s route-level 503 persists nothing.
- **Locks.** No lock is held across a remote call. The only lock involved is the existing DB-row session flag, and it is released before raising.

## Tests: inverted or updated, and why
**Inverted, deliberately, by ruling C24.** These are in `tests/unit/test_engine_mode_wiring.py`, in the class `TestResolutionFailureNeverFailsATurn`, which is now `TestResolutionFailureFailsTheTurnClosed`.

| Old ws4d test (fail-open) | Now (fail-closed) |
|---|---|
| `test_a_raising_resolver_returns_the_callers_value` | `test_a_raising_resolver_raises_the_typed_lakebase_error`: the code, the cause, and no internal text in the error |
| `test_the_fallback_defaults_to_monolith` | `test_there_is_no_fallback_to_default_to`: the signature is exactly `(session_id)`, and `resolve_engine_mode_or` no longer exists |
| `test_the_streaming_route_still_serves_the_turn` | `test_the_streaming_route_fails_with_a_typed_503_and_releases_the_lock`: the exact body, the service is never called, and acquire and release are each called once |
| `test_the_async_route_still_enqueues_the_job` | `test_the_async_route_fails_with_a_typed_503_and_releases_the_lock`: nothing is enqueued, release is called once, and the request row and user message were written |

- **Kept.** `test_a_successful_resolution_is_passed_straight_through`, now checked for both answers.
- **New class `TestTheSseReResolveFailsClosed`.** It covers the service site with the route's mode set to `monolith` and to `graph`: exactly the safe event, then the typed raise, with the monolith and the graph both booby-trapped.
- **C47(d) test.** It uses the real `/chat/stream` route with a real `ChatService` and a two-call resolver (monolith, then a raise). It asserts an SSE body of exactly one safe event and the lock released.

**Updated: the incidental fail-open dependents (C47(c)).** They now opt in to `engine_mode_resolves_to_monolith`, which patches `src.api.services.chat_service.resolve_engine_mode` to return `"monolith"`. These tests reached their subject only because their mocked database made the resolver raise and the fail-open kept `monolith`. The fixture states that answer explicitly, and the route and service call sites and the wrapper stay real.

| File | Scope of the opt-in | Tests that were RED without it |
|---|---|---|
| `tests/unit/test_chat_session_creation.py` | file-wide `pytestmark` | 23 |
| `tests/integration/test_streaming.py` | file-wide | 21 |
| `tests/unit/test_chat_service_no_singleton.py` | `TestSendMessageStreamingBuildsAgentPerRequest` | 1 |
| `tests/unit/test_session_naming.py` | `TestSessionNamingInStreaming` | 2 |
| `tests/integration/test_api_routes.py` | `test_chat_async_submit` | 1 |

That is 48 tests in total; C47 predicted about 50. No test about resolution uses the fixture.

**Added: C52.** These four tests are in `tests/unit/test_persisted_graph_release.py`, and each exception is its own parametrisation:
- a plain `@contextmanager`;
- LangGraph's `set_config_context`;
- a real compiled `StateGraph` node, asserting `raised.value is error`;
- a test that keeps frozen fields, `str` and `args` and allows chaining, `__traceback__` and `add_note`.

## The new PostgreSQL file (22 tests, zero skips)
- **`_conversation_state(factory, session_id)`.** It captures:
  - the messages as (id, role, sha256);
  - the latest checkpoint id, plus the whole root-namespace chain (id, parent, blob hash);
  - the deck row (id, title, html, deck_json hashes, slide_count);
  - the slides (position, id, slide_id, html and scripts hashes);
  - the pin;
  - `graph_draft.lock_version`.
- **Harness.**
  - It runs `run_to("S12")`, then Task 7's `open_turn_driver`.
  - One **successful** `new-root` (v2, id 3) turn gives the conversation messages, a deck, a slide and checkpoints. The state is snapshotted after that turn.
  - Each failure is then installed and a second turn is driven through `send_message_streaming`, by `_drive_failing_turn`. This is the driver's seam with a bounded join, and it returns the events and the error instead of asserting success.
- **Every invocation case asserts:**
  - the exact typed error and code;
  - exactly one ERROR event, which is the safe event, is last, and has no COMPLETE;
  - no leaked text;
  - the exact adapter-call prefix, so nothing ran on a substitute;
  - the `pinned_graph_configuration_unavailable` log `(error_class, graph_release_id)`;
  - an **active-release statement spy** equal to `[]`;
  - `after == _expected_after_failed_turn(...)`.
- **The spy's window.** It is armed around the pin load and every `AgentRuntime.run`. The architect's `SessionManager.get_session` projection legitimately reads the active release to compute `is_older_than_active`, and it selects nothing. That read was measured, and it is why the window is not the whole `invoke_graph`.

**The cases:**
1. **A lost pinned release.** The loader raises `GraphReleaseNotFoundError(3)`. The loader is asked only for `(3, "architect")`, and there are no model calls.
2. **Lakebase unavailable**, with a FRESH loader (C18.4), parametrised two ways:
   - `session_factory` raises `OperationalError`;
   - `statement`: the session's `execute` raises, which reaches `AgentRuntime.run`'s own `SQLAlchemyError` branch. This variant is the reviewer-sabotage target.

   In both, the code is `lakebase_unavailable` and the cause is `OperationalError`.
3. **Removed endpoint.** Fixer's `ModelProviderUnavailableError` becomes `PinnedInvocationEndpointError` with:
   - `endpoint_name == "databricks-claude-sonnet-4-5"`;
   - `graph_release_id == 3`;
   - fixer's exact v2 revision id.

   It is attempted exactly once, and the calls are exactly `A1_ROLES` up to fixer.
4. **Protected bundle.** `(2, fb651a0d…)` is popped from the constructed runtime's instance `_bundles` (C32). The code is `protected_bundle_unavailable`, and there are zero model calls.
5. **Schema bundle.** `("builder", 2)` is dropped from `SCHEMA_CONTRACT_BUNDLES`. The code is `schema_contract_unavailable`, the calls are exactly A1 up to builder, and the builder is never called.
6. **Legacy null-pin (`control-legacy`, C37).**
   - The error is `conversation_pin_unavailable`, the log is `("ConversationPinMissingError", None)`, and there are no model calls.
   - No checkpoint is written at all.
   - The pin stays null.
7. **The three C24 sites over the shipped chat router,** on the journey app with a real `resolve_engine_mode` whose `get_db_session` raises `OperationalError` on the chosen call:
   - `/chat/stream`: the typed 503, `is_processing` false, no engine ran, and the state is **exactly** `before`;
   - `/chat/async`: the typed 503, nothing enqueued, `is_processing` false, `chat_requests == [("pending", None)]`, and the state is `before` plus the user message;
   - the SSE re-resolve: the route resolves `graph`, the service's resolve raises, the SSE body is exactly the safe event, `is_processing` is false, and there are no model calls.
8. **Seven creators through `_create` (C38/C51).** The database was never bootstrapped, and the only rows are legacy null-pin sources (the duplicate source has the marker and a deck, and both sources carry a `CAN_VIEW` grant for the actor). Each creator raises `ActiveGraphReleaseUnavailableError`, the `user_sessions` rows are unchanged, `graph_release` stays empty, and the tripwire reads are `[]`.
9. **Five route creators over HTTP** (sessions and chat routers):
   - explicit-root, chat-generated-id (`/chat/stream`), chat-supplied-id (`/chat/async`) and duplicate each answer 503 "No active Graph Release available";
   - **contributor answers 500** (concern 1).

   In every case there is no new row and the tripwire is unread.

## Gates
Env: `PYTHONPATH=tree:tree/packages/databricks-tellr`, `DATABASE_URL=sqlite:////tmp/t271-8.sqlite`, `TELLR_TEST_POSTGRES_URL=…/postgres`. PostgreSQL ran one file per invocation with `-rs -m "not live"`, and there were zero skips in each.

| Gate | Result |
|---|---|
| `tests/integration/test_lakebase_contract_failures_postgres.py` (new) | 22 passed (≈24 s) |
| `tests/unit/test_engine_mode_wiring.py` | 39 passed |
| `tests/unit/test_chat_session_creation.py` | 49 passed |
| `tests/unit/test_chat_service_no_singleton.py` | 9 passed |
| `tests/unit/test_session_naming.py` | 17 passed |
| `tests/integration/test_streaming.py` | 28 passed |
| `tests/integration/test_api_routes.py` | 87 passed, 2 skipped. The skips are the pre-existing hard-coded `pytest.skip` at `:1195`/`:1218` (MLflow mocking), not a PostgreSQL skip. |
| `tests/unit/test_persisted_graph_release.py` | 31 passed |
| Task 6 `test_graph_lifecycle_acceptance_postgres.py` | 1 passed |
| Task 7 `test_graph_lifecycle_runtime_postgres.py`, re-run after the `chat_service.py` edits (C46) | 2 passed |
| `test_conversation_pin_creation_postgres.py` | 2 passed |
| `test_conversation_pin_acceptance_postgres.py` | 1 passed |
| `test_persisted_graph_runtime_failures_postgres.py` | 7 passed |
| `test_graph_mode_turn.py` | 39 passed |
| `test_mixed_release_creation_postgres.py` (whose helpers are imported) | 14 passed |
| `tests/unit/test_ci_collects_integration_tests.py` | 25 passed |
| Full unit (`-n 4`, `DATABASE_URL` unset per the Tasks 6/7 practice so that each xdist worker gets its own SQLite; run inside the worktree; UTC 19:23:52–19:26:39, far from midnight) | 2 failed / 7267 passed / 110 skipped. The 2 failures are exactly the `test_deploy_autoscaling` pair (the baseline cause). An earlier mid-task run gave 2 / 7232 / 110 with the same cause. |
| ruff check on every touched `.py` | No file's count went up. The new file and every new test file are clean. `chat.py` (8), `chat_service.py` (125), `test_api_routes.py` (10) and others keep their pre-existing counts. `ruff format --check` on the new file is clean. |

- `.venv` is absent.
- `ai_slide_generator` was never touched.
- `tellr_int_*`: 5 before and 5 after, and the names are unchanged. I dropped nothing.

## Mutation table
- All mutations ran in my own temp worktree, `/Users/robert.whiffin/Documents/slide-gen-branch-eval/t271-8-mut`, detached at `1e7cf9499`. It has since been removed. The shared tree was never mutated.
- Each anchor was asserted to occur the exact expected number of times and carried a `T271M*` marker.
- After each run the file was restored with `git checkout 1e7cf9499 -- <file>`, then `git diff --quiet` and an empty `git status --porcelain` were asserted.
- GREEN in the mutation tree before starting: wiring 39, C52 31, the PostgreSQL file 22, CI 25.
- The runner is `reports/t271-8-run_mut.py`.

| # | Mutation | Result |
|---|---|---|
| M1 | Fail-open restored at `/chat/stream` (C7's reviewer sabotage: a raising resolver returns `"monolith"`) | RED. Unit `test_the_streaming_route_fails_with_a_typed_503…`. PostgreSQL `test_the_stream_route_answers_503…`: the service's re-resolve then ran the graph, "unexpected adapter invocation for 'architect'". |
| M2 | Fail-open at `/chat/async` | RED. Unit async 503 and PostgreSQL `test_the_async_route_answers_503…` |
| M3 | Fail-open at the SSE re-resolve (C24.4's controller site, C47(d)): swallow the error and keep the route's mode | RED. Unit 3/3 `TestTheSseReResolveFailsClosed`: in the route variant the monolith was built. PostgreSQL `test_the_sse_re_resolve…`: the graph ran. |
| M4 | Lock not released before the `/chat/stream` 503 | RED. Unit, where the release assert fails. PostgreSQL, where `is_processing` is True. |
| M5 | Lock not released before the `/chat/async` 503 | RED. Unit and PostgreSQL. |
| M6 | `slots=True` restored on both C52 exceptions, with the wrapper kept | **GREEN, and expected: an equivalent mutant.** `BaseException` instances always have a `__dict__`, and the wrapper routes the exception attributes to `object.__setattr__`, bypassing the slots-class `super(cls, self)` bug. So slots is not the load-bearing part of the fix. M6b and M6c are the decisive mutants. |
| M6b | The C52 fix removed entirely: back to frozen+slots with no wrapper, the shipped defect | RED. Unit 7/7 C52 tests (`TypeError: super(type, obj)`). PostgreSQL 5: both lakebase variants, removed endpoint, protected bundle, schema bundle ("Graph turn failed: super(type, obj)…"). |
| M6c | Wrapper removed, slots dropped (a plain frozen dataclass) | RED. The same 7 unit and 5 PostgreSQL tests (`FrozenInstanceError` on `__traceback__`/`__notes__`). This proves "just drop slots" is not a fix. |
| M7 | **The plan's REVIEWER sabotage.** `AgentRuntime.run`'s `SQLAlchemyError` branch queries `graph_release WHERE effective_to IS NULL` (via `builder.get_session_local`) before raising. `run` only; `run_published_baseline`'s identical branch is untouched. | RED 1/2, exactly as predicted. `test_lakebase_unavailable…[statement]` failed on the spy: `assert ['select graph_release… where graph_release.effective_to is null'] == []`. The `[session_factory]` variant stays GREEN, correctly: that failure is converted inside the loader's `_open_session` and never reaches the branch. |
| M8 | The SSE re-resolve raises without yielding the safe event | RED. Unit 3/3 and PostgreSQL SSE. |
| M9 | The `/chat/async` 503 body carries `repr(e.__cause__)` | RED. Unit async and PostgreSQL async (the body's exact-equality check and the leak check). |
| M10 | The CI line for the new file removed | RED 2/25: the new pin and `test_every_integration_file_is_collected_or_excluded_with_reason`. |

**Not run:** the plan's CONTROLLER sabotage, which makes `load_conversation_pin` return the active release when the pin is null. It is the controller's. Its target is `test_a_legacy_null_pin_conversation_runs_no_graph_turn_and_is_never_pinned`, and the spy is armed around the pin load exactly so that it can see that query.

## Deviations
1. **"State unchanged" is defined precisely, not as literal equality** (measured). `_expected_after_failed_turn` permits exactly three things; everything else must be byte-identical: earlier messages, deck, every slide, the pin, `lock_version`, and every earlier checkpoint. The three:
   - **(a) This turn's user message** (C47(e)). `send_message_streaming` persists it before the graph runs.
   - **(b) The failed turn's appended checkpoints.** LangGraph writes the turn's input checkpoint before the first node runs, so `latest_checkpoint_id` changes even when the very first node fails. The test asserts that every earlier checkpoint is byte-identical, that each new one descends from the previous latest, and that the new tip carries exactly the pin.
   - **(c) The narration of nodes that completed before a later-node failure.** Nodes commit as they finish. The removed-fixer-endpoint and schema-v2-builder cases fail after architect, data_analyst and architect, so they leave exactly those three assistant rows. The rows are asserted by hash to equal the successful turn's first three. Deck and slide rows are unchanged in both cases. A first-node failure leaves no narration.

   The plan's "latest checkpoint id equal" is unimplementable without making a turn transactional.
2. **`resolve_engine_mode_or` is removed, not kept as a fail-open helper.** A dormant fail-open function is the hazard C24 describes. `test_there_is_no_fallback_to_default_to` pins its absence.
3. **The 503 is explicit route handling, not a `main.py` handler.** The brief allowed either. It is also a dict detail, `{"code", "message"}`, rather than a string, because a stable code must be machine-readable. The creator 503s keep their existing string detail.
4. **The C47(c) fixture is opt-in** (`pytestmark` or a class/test decorator), not autouse, so a resolution test can never inherit it by accident.
5. **Full unit ran with `DATABASE_URL` unset** (as in Tasks 6/7), so the conftest gives each xdist worker its own SQLite file. Every targeted run set `DATABASE_URL=sqlite:////tmp/t271-8.sqlite` explicitly.
6. **The removed-endpoint case uses `new-root`'s second turn**, not A1's first turn in the pin-acceptance file. Fixer is reached by reloading `_first_turn_outputs()`.

## Concerns
1. **Production inconsistency (FOUND, not fixed; routed for C22 triage).** On a database with no active release, `POST /api/sessions/{id}/contribute` answers **500 "Failed to create contributor session"**, not 503.
   - The route first reads the parent through `SessionManager.get_session`, whose public projection (`get_conversation_graph_version` → `_require_active_graph_release`) raises `ConversationGraphReleaseIntegrityError`.
   - That happens before `get_or_create_contributor_session` can raise the typed error the route's 503 clause maps.
   - It is still an explicit refusal with no row and no internal text, and `_create`'s typed error holds.
   - The HTTP test pins the 500 exactly, with a FINDING comment, so a fix turns it red on purpose.
   - A fix belongs in `sessions.py`, which is outside this task's file list. The same projection makes every session GET 500 with no active release.
2. **Mid-turn failures leave partial narration** (deviation 1c). Whether AC3 wants a failed turn's completed-node messages rolled back is a product question. The test pins the current, exact behaviour.
3. **The async `chat_requests` row is left `pending`** after the 503 (C47(e), accepted). It relies on the existing stuck-request recovery and sweeper to be closed out.
4. **Planned mutation M6 (`slots=True` restored) stays GREEN.** It is an equivalent mutant under this fix (see the table). M6b and M6c are the decisive mutants.
5. **The reviewer is reviewing Task 7 concurrently.** This task imports `open_turn_driver`, `GraphTurnDriver`, `MESSAGE`, `RUNTIME_LOGGER` and `TURN_TIMEOUT_SECONDS` from Task 7's file, and it did not modify that file.
