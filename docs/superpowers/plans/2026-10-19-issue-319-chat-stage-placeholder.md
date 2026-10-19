# Chat Placeholder Shows the Graph's Current Stage (#319): Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task by task. Also load `executing-plans-tellr` (repo CLAUDE.md): run its plan-vs-code corrections pre-pass before Task 1, sabotage-verify every test, and record baselines as cause-sets. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Revision 2 (2026-10-19):** incorporates the plan review at `~/tellr-loop/issues/issue-319/PLAN-REVIEW.md` with the supervisor's rulings. Findings #1–9 and #11–16 were applied (#15 was cut as ruled; the `lastProgressSeq` guard was kept). Finding #10's copy change was rejected (see D10).

**Goal:** While a graph turn runs, the chat placeholder says what the graph is doing ("Planning the deck…", "Building 10 slides…", "Reviewing slide 3…", "Fixing 2 slides…", "Reviewing the narrative…") instead of the static "Generating slides...". This must work on the polling transport (production) and on SSE (dev). The label must stay true while several slides run at once, must never step backwards, and must be the same whichever uvicorn worker serves the poll.

**Architecture:** Each turn gets one structured **stage summary**, a `TurnProgress` tracker. `invoke_graph` installs it in a `ContextVar` for exactly the duration of `graph.invoke`, through `turn_progress_scope()`: the var is set with a token and reset in `finally`. Graph nodes report stage transitions where they already emit their build-mechanics events: the foreman's batch, each slide's pipeline stages, and deck review. Each report is merged monotonically under a lock, gets a `seq`, and goes to two sinks:
1. A new `turn_progress` `StreamEvent` on the SSE queue. It is queued inside the lock, so the queue is in `seq` order.
2. Two new nullable columns on the turn's own `chat_requests` row. They are written outside the lock by a conditional `UPDATE … WHERE progress_seq < :seq`, which is bounded on PostgreSQL by `SET LOCAL lock_timeout = '2s'`. Concurrent writers therefore can never move the row backwards, and a stuck write holds up only its own thread, for at most about 2 s.

`GET /api/chat/poll` returns the row's snapshot as `turn_progress`. It reads only the database, so every worker serves the same value. The frontend keeps the highest-`seq` snapshot of the current turn and renders it with one pure function. When there is no snapshot (the legacy engine, or before the first report) it shows the unchanged "Generating slides...".

**Tech Stack:** FastAPI + SQLAlchemy 2.0.44 (pytest + xdist; SQLite file DBs in `tests/unit/conftest_graph.py`; PostgreSQL suites that self-skip locally and run in CI); the LangGraph compiled graph; React 19 + Vite (vitest + Testing Library, jsdom); Playwright with a mocked API.

**Spec:** GitHub issue #319 (quoted verbatim under *Acceptance*). The supervisor's design brief is folded into *Decisions*. There is no separate spec doc.

---

## Background: what exists today (verified against `679d2f21`)

1. **The polling transport cannot see any graph event.** `job_queue.process_chat_request` (`src/api/services/job_queue.py:97`) runs `_run_streaming_generator` (`:218`). That collects every `StreamEvent` into a list and keeps only `COMPLETE` and `SESSION_TITLE` (`:158-167`, `:181-190`). `GET /api/chat/poll/{request_id}` (`src/api/routes/chat.py:827-967`) reads only the database: `get_chat_request`, `get_messages_for_request`, `slides_since_cursor` and `slide_revisions_since`. The supervisor's reading is **confirmed**.
2. **The "events the graph already emits" are emit-only.** Three lines go through `_emit` (`nodes.py:222`) and never through `_say` (`nodes.py:241`):
   - the foreman's `f"Building {len(batch)} slide(s)."` (`src/services/graph/nodes.py:2151-2155`);
   - the build reviewer's `f"Slide {position} reviewed: {verdict}."` (`nodes.py:2459-2464`);
   - the fix reviewer's `f"Slide {position} fix reviewed: {verdict}."` (`nodes.py:2936-2940`).

   Production users never see them. On SSE, `ChatPanel`'s `'assistant'` case renders them as chat bubbles (`frontend/src/components/ChatPanel/ChatPanel.tsx:211-222`), and they disappear on reload.
3. **Nothing signals the start of a review or a fix.** The pipeline (`slide_pipeline_node`, `nodes.py:3094-3216`) runs `builder_node → _write_draft_row → build_reviewer_node → [fixer_node → fix_reviewer_node]` for one slide. Up to `CAP = 15` slides run concurrently (`src/services/foreman_service.py:83`), with up to `FIX_CONCURRENCY = 5` fix rounds at once (`nodes.py:2978`). Only verdicts are emitted, so "Reviewing slide 3…" cannot be derived from what exists.
4. **There are two placeholders.** `MessageList` renders a static `Generating slides...` while `isLoading` (`frontend/src/components/ChatPanel/MessageList.tsx:26-31`). That is the one the issue names. `LoadingIndicator` renders a bar whose emoji jokes rotate on a **3 s `setInterval`** (`ChatPanel.tsx:197-202`, `frontend/src/utils/loadingMessages.ts`).
5. **How the transport is chosen.** `isPollingMode()` (`frontend/src/services/api.ts:35-58`) is true in production builds and on Databricks hostnames. `sendChatMessage` (`api.ts:1219`) picks `startPolling` (`:1074`, which polls every `POLL_INTERVAL_MS = 3000`, `:14`) or `streamChat` (`:902`).
6. **Prod runs several worker processes** (`UVICORN_WORKERS`, default 4; `packages/databricks-tellr-app/databricks_tellr_app/run.py:184-185`). The job runs in the worker whose in-memory `job_queue` received `POST /chat/async`. The poll can land on any worker.
7. **`ContextVar.set()` inside a node does not propagate** (`advance_slide_cursor` docstring, `src/services/graph/event_emitter.py:147-163`). The fix slots get around this by being set once per turn in `invoke_graph`, before the invoke (`src/services/graph/builder.py:344`, `nodes.py:2984-2997`), because a context copy shares the *object*. The fix slots are never unset after the turn. In production that is harmless: `chat_service.py:1965-2047` runs `invoke_graph` inside `ctx.run` on a copied context. A caller that runs `invoke_graph` in its own context, which every test does, keeps whatever was set.
8. **Schema migrations** are hand-rolled, idempotent `ALTER TABLE … ADD COLUMN` helpers inside `_run_migrations` (`src/core/database.py:443-658`), run once pre-fork from `run.py`. `create_all` builds fresh installs from the ORM. There is no alembic. For the pattern and an alter-path test, see `_migrate_spec_dirty_marker` (`database.py:1304`) and `tests/unit/test_spec_dirty_marker.py:243-296`.
9. **The poll is creator-only.** `_require_chat_request_owner` (`chat.py:159-182`) runs at `chat.py:892`, before the `chat_requests` row is read (`chat.py:894-896`). This is pinned by `tests/unit/test_authz_chat_poll.py:28-40`.
10. **`get_db_session`** (`src/core/database.py:391-405`) opens one `Session` per `with` block and commits once on exit. Under SQLAlchemy 2.0 autobegin, everything executed in one block is a single transaction, so a `SET LOCAL` there applies to the statements that follow it in that block and to nothing else. The repo's dialect check is `db.get_bind().dialect.name == "postgresql"` (`src/services/graph_configuration_bootstrap.py:82-83`, `src/services/image_service.py:180-181`).

---

## Acceptance criteria (from #319, verbatim) and how each is met

**A1.** "The placeholder reflects the graph's current stage (e.g. "Planning the deck…", "Building 10 slides…", "Reviewing slide 3…", "Fixing 2 slides…", "Reviewing the narrative…") on the polling transport (production) and on SSE."

- **Met by:** the tracker and its reports (Tasks 2–3); the row and the poll projection (Tasks 1 and 4); the client sinks and the label (Tasks 2 and 6–8).
- **Proven on polling by:**
  - `tests/integration/test_turn_progress_polling.py::test_a_polling_client_sees_each_stage_while_the_turn_runs`, which calls `poll_chat` from inside the running turn;
  - `tests/unit/test_turn_progress_cross_worker.py::test_a_poll_on_another_worker_process_sees_the_running_turns_stage`;
  - `frontend/src/services/turnProgressTransport.test.ts` (`startPolling`).
- **Proven on SSE by:**
  - `tests/integration/test_graph_mode_turn.py::TestTheCompleteEvent::test_stage_progress_streams_before_complete_in_seq_order`, the real `_send_message_streaming_graph` generator;
  - `tests/unit/test_turn_progress_graph.py::test_a_build_turn_walks_planning_building_reviewing_deck_in_order`;
  - `frontend/tests/e2e/turn-progress.spec.ts`.
- **Copy:** `frontend/src/utils/turnProgress.test.ts::the five example labels from #319 are produced verbatim`.
- **Rendering:** `ChatPanel.turnProgress.test.tsx`.

**A2.** "Driven by events/state the graph already emits where possible (foreman's "Building N slide(s)", per-slide review/fix events), not by timers."

- **Met by:** reports sit next to the existing emits (the foreman's batch, the pipeline's stage boundaries, deck review). The label is a pure function of the latest snapshot. No timer, heartbeat or interval is added anywhere.
- **Proven by:**
  - `test_turn_progress_graph.py`: every transition comes from the real nodes of a compiled turn;
  - `tests/unit/test_turn_progress.py::test_a_repeated_report_publishes_nothing`: no heartbeats;
  - `ChatPanel.turnProgress.test.tsx::the label is not timer-driven`: 60 s of fake time with no new event leaves the label unchanged.

---

## Decisions

**D1. Transport: one structured snapshot, two sinks.** On SSE the snapshot travels as a new `StreamEventType.TURN_PROGRESS` event. For polling it is written to the turn's `chat_requests` row and returned by the poll as `turn_progress`. These alternatives were rejected:
- *Parse the existing assistant lines.* They are emit-only (Background 2), so polling never sees them. There is no review-start or fix-start line. The UI would also depend on English copy.
- *Derive the stage from persisted rows* (draft rows vs reviewed rows). Rows cannot tell reviewing from fixing. On an edit turn every untouched position already has a row. Planning, data and deck review leave no row at all.
- *Persist as a `SessionMessage`.* That pollutes the transcript, `_conversation` replay and clear-chat (#323). `msg_to_stream_event` has nowhere to carry the data. The `poll_chat` docstring (`chat.py:848-854`) already rules build mechanics out of the transcript.
- *`job_queue.jobs[request_id]`.* It lives in one worker's memory, which is the multi-worker bug class.
- *Overload `chat_requests.result_json`.* That would mix the terminal result with progress, and `mcp_server.py:756` reads that column.

**D2. Persistence: two nullable columns on `chat_requests`.** `progress_json TEXT NULL` holds the snapshot. `progress_seq INTEGER NULL` holds its `seq`, which the SQL guard needs. A new idempotent `_migrate_chat_request_progress` adds them in `_run_migrations`, and the ORM model declares them for `create_all`. Because the row belongs to one request, progress is turn-scoped by construction: no previous turn can leak into it. The poll already reads this row behind the creator gate. The row is cascade-deleted with the session and swept by `cleanup_stale_requests`. Status and result writers update only their own attributes (ORM dirty tracking), so they cannot clobber progress. Pinned in Task 1.

**D3. Concurrency and monotonicity, precisely.** The tracker holds `phase`, `covered: set[int]` and `stages: dict[position, stage]`.
- *Phase rank:* `planning = gathering_data = checking_slides = 0`, `building = 1`, `reviewing_deck = 2`. A phase report applies iff its rank is ≥ the current rank. Same-rank phases may alternate, because `ask_data → data_analyst → architect` loops. A lower-rank report is dropped.
- *Slide stage rank:* `building 1 < reviewing 2 < fixing 3 < done 4`. A slide report applies iff its rank is **strictly** higher than that slide's current stage. Skipping forward is allowed: a placeheld builder goes `building → done`.
- *Covered* only grows. `total = |covered ∪ positions with a stage|`.
- A slide report that applies raises the phase to `building` if the phase is below rank 1, and never past it.
- `seq` rises by exactly 1 for each report that changed something. A report that changes nothing bumps nothing and publishes nothing.
- The snapshot is built under the lock, so snapshot *n* reflects exactly the first *n* changes.
- **SSE:** the event is queued inside the lock. `queue.Queue.put` on the unbounded queue never blocks, so queue order equals `seq` order.
- **DB:** written outside the lock with `UPDATE chat_requests SET progress_json=:j, progress_seq=:s WHERE request_id=:r AND (progress_seq IS NULL OR progress_seq < :s)`.
  - Commits from pipeline threads may land in any order, and the stored `seq` still never decreases.
  - On PostgreSQL, a concurrent UPDATE of the same row waits for the first commit and then re-evaluates the predicate (READ COMMITTED). An older writer queued behind a newer one therefore loses.
- **Blocking.** A progress write never blocks another slide on the tracker lock. It blocks only its own reporting thread, and on PostgreSQL for at most about 2 s waiting on the request row's lock (`SET LOCAL lock_timeout = '2s'`). On timeout the write raises, `_persist` logs it, and the next report carries a newer snapshot. A pool checkout is not bounded separately: it is shared with every other writer, and the pool is 80 + 20 (`database.py:322-326`).
- **Client:** keeps the snapshot with the highest `seq` seen *this turn* and discards any with `seq ≤ held`. It resets at send.
- **What follows:** in every sequence of snapshots a client observes (the SSE stream, or any subsequence a 3 s poll samples), the phase rank and every slide's stage rank never decrease, and neither do `done` or `total`. Per-stage *counts* go up and down as slides move between stages. That is truthful, not a regression.

**D4. Write frequency: no throttling.** A turn makes at most `3N + 5` single-row UPDATEs, keyed by the unique, indexed `request_id`:
- one foreman report per dispatched batch;
- `reviewing` and `done` for each slide;
- `fixing` for each flagged slide;
- the phase reports;
- one write for the placeheld set.

That is roughly 2N to 3N + 5 in practice; a 20-slide deck is about 45–65 writes over several minutes. Each write waits at most about 2 s on the row lock (D3). A throttle would need a flusher thread to deliver the trailing update, which adds complexity with no observable benefit at a 3 s poll.

**D5. The event is named `turn_progress`, not `progress`.** Existing Playwright mocks already send `{"type": "progress", "message": "Generating slides..."}`: `frontend/tests/e2e/chat-ui.spec.ts:52`, `export-ui.spec.ts:52`, `slide-operations-ui.spec.ts:52`, `save-points-versioning.spec.ts:44` and `frontend/tests/helpers/integration-helpers.ts:63`. Today these fall through `ChatPanel`'s switch; reusing the name would route them into the new handler. The DB columns are `progress_*`. The wire key and the event type are `turn_progress` everywhere.

**D6. The frontend renders the label from the data.** The backend contract is data: `seq`, `phase` and per-stage position lists. Copy lives with the UI, in one pure function, `describeTurnProgress`. A vitest conformance test reads `src/services/graph/progress.py` as text and pins the enum literals on both sides. The precedent is `frontend/src/services/__tests__/deckSpecConformance.test.ts`.

**D7. Copy.** It is user-visible plain language with no internal node names and no emoji.
- Slide numbers are **1-based** (`position + 1`), matching the ribbon's `Slide {index + 1}` (`frontend/src/components/SlideViewer/ThumbnailRibbon.tsx:133`).
- The ellipsis is the single character `…` (U+2026).
- The no-snapshot text stays byte-identical, because `chat-ui.spec.ts:436` pins `/Generating slides/`.

For the `building` phase, each non-empty active stage becomes a clause, in pipeline order (building, reviewing, fixing):
- one slide gives `<verb> slide N`; several give `<verb> K slides`;
- the clauses are joined with `, `, the first letter is capitalised, and the sentence ends with `…`;
- when `done > 0` and `total > 1`, ` (D of T done)` is appended, e.g. `Reviewing 2 slides, fixing slide 5… (7 of 10 done)`;
- with nothing active the label is `Building the slides…` (plus the suffix when it applies), or `Finishing the slides…` once `done == total`.

| Snapshot | Label |
|---|---|
| none yet, or the legacy engine | `Generating slides...` (unchanged; three ASCII dots) |
| `planning` | `Planning the deck…` |
| `gathering_data` | `Gathering the data…` |
| `checking_slides` | `Checking the slides against the new brief…` |
| `reviewing_deck` | `Reviewing the narrative…` |
| `building`, one active stage | `Building 10 slides…` · `Reviewing slide 3…` · `Fixing 2 slides…` |
| `building`, several active stages | `Building 3 slides, reviewing 2 slides, fixing slide 6…` |
| `building`, with `done > 0` and `total > 1` | `Reviewing 2 slides, fixing slide 5… (7 of 10 done)` |
| `building`, nothing active, `done < total` | `Building the slides…` (plus the suffix) |
| `building`, nothing active, `done == total` | `Finishing the slides…` |

Queued slides are not named. A slide is queued when it is covered but not yet dispatched, which happens only on decks of more than 15 slides. The `done` suffix carries the overall progress.

**D8. Legacy (monolith) mode stays unchanged.** This rests on one structural fact: **no tracker means no-op.**
- The monolith never calls `invoke_graph`, so it never opens a `turn_progress_scope()`.
- Every `report_*` with no tracker installed returns `False` and does nothing (pinned by `test_reports_without_a_tracker_are_noops_and_never_raise`).
- A turn's tracker cannot outlive the turn and leak into a later monolith turn (pinned by `test_the_tracker_does_not_outlive_the_turn`).
- So the columns stay NULL, the poll returns `turn_progress: null`, and the frontend shows `Generating slides...`.
- The monolith's `tool_call → setLoadingMessage("Querying …")` (`ChatPanel.tsx:239`) and the rotating bar are untouched.
- MCP jobs never carry `engine_mode` (`job_queue.py:128`), so they are unaffected too.

**D9. Edit turns** use the same labels. `total` is the edit's coverage (`target_positions`), so editing slide 2 reads `Building slide 2…` → `Reviewing slide 2…` → … → `Reviewing the narrative…`. There is no separate "Editing" label: the architect's own persisted reply already says it (e.g. "Editing slide 2."), and "building" is literally what the builder does.

**D10. Chat-only turns show "Planning the deck…".** Chat-only turns (`discuss`, `confirm_design_contract`, a degraded edit) only ever report `planning`. The user sees `Planning the deck…` until the reply lands and the turn ends. The same label is used for **every** architect phase. Rationale:
- it is the issue's own example string;
- the architect's role on every turn is the deck plan;
- a chat-only turn is a single model call, so the label shows only briefly;
- the intent is unknown until the architect's model call returns, so an intent-dependent label would be a guess.

The plan review's intent-neutral alternative, "Working on your request…", was considered and **rejected** by the supervisor for those reasons. So was the variant that reports a different phase when the session has no committed deck. Owner sign-off on this copy remains a review risk (Risk 10).

**D11. Data analysis.** `data_analyst_node` reports `gathering_data` (`Gathering the data…`). The architect's next pass reports `planning` again. That is a same-rank change, not a regression.

**D12. Deck-level brief change.** `rereview_committed_slides` runs serially inside the architect, one review call per committed slide (`nodes.py:528`). The architect reports `checking_slides` immediately before it (`Checking the slides against the new brief…`).

**D13. Error turns.**
- A turn-level failure ends loading exactly as today: an `error` event on SSE, or `status=error` → `onError` on polling.
- The poll returns `turn_progress: null` for `completed` and `error` requests, so a request that **reached** a terminal status never shows a stale stage.
- A failed slide is placeheld, that slide moves to `done`, and the turn continues.
- **Known gap (pre-existing, out of scope):** a crashed or unrecovered request keeps its last stage.
  - The pre-existing stuck-request hang applies: `recover_stuck_requests` runs only at boot and only for rows older than 10 minutes (`job_queue.py:306-344`), and the hard-timeout sweeper marks only the in-memory `jobs` dict (`job_queue.py:350-395`).
  - A turn whose worker died can therefore stay `running` indefinitely, and the poll keeps serving its last snapshot (e.g. "Reviewing slide 3… (7 of 10 done)") where it used to show "Generating slides...".
  - No `progress_updated_at` column is added for this.
- **Also pre-existing and out of scope:** on SSE, `_placehold_failed_position`'s mid-turn `ERROR` event (`nodes.py:1262-1266`) trips `ChatPanel`'s `'error'` case and ends loading early. Polling is unaffected.

**D14. No stale progress across turns.**
- Each `invoke_graph` opens a fresh `turn_progress_scope()`, so `seq` restarts at 1, and the scope removes the tracker when the invoke ends.
- The DB row belongs to one request.
- The client resets its held snapshot at send, which is what lets the next turn's `seq 1` replace the previous turn's `seq 40`.

**D15. Shared decks and permissions are unchanged.**
- Progress is served only by `poll_chat`, after `_require_chat_request_owner`. No new endpoint is added.
- A contributor's turn runs in their own contributor session with their own request rows, so an owner never sees a contributor's in-flight stage, and vice versa. This matches the F-CR-31 privacy rule.
- The existing `tests/unit/test_authz_chat_poll.py:28-40` already proves the gate runs before `get_chat_request` reads anything, which is the only source of `turn_progress`.

**D16. The bottom `LoadingIndicator` (timer-rotating jokes) is unchanged.** The issue names the placeholder, not the bar. The bar is shared with the monolith's tool-call text and pinned by `chat-ui.spec.ts`'s "shows rotating loading messages". Retiring it on graph turns is a follow-up UX decision.

**D17. No prompt, output-schema, `DeckSpec` or Agent Definition change.** Nothing under `src/core/skills/` or `src/domain/skill_io.py` is touched, and no model payload changes. Digests are unaffected: `src/services/agent_schema_registry.py:215-250` hashes output-schema validators only.

**D18. Where reports sit.** Each one is next to an existing emit or at a stage boundary.
- Architect entry → `planning`.
- Before `rereview_committed_slides` → `checking_slides`.
- Data-analyst entry → `gathering_data`.
- Foreman dispatch, beside its `Building N slide(s).` emit → `building`, with `covered = outstanding_positions(state)` and the batch dispatched. This is what puts each slide into `building`. The pipeline makes no start-of-build report: in the graph the foreman's report always precedes every `Send`.
- After the draft write → `reviewing`.
- When a fix opens, *before* waiting for a fix slot → `fixing`. A slide waiting for one of the 5 slots is already in its fix round.
- At every pipeline return → `done`.
- `placeholder_node`'s placeheld positions → `done`, as one snapshot through `report_slides`.
- Deck-reviewer entry → `reviewing_deck`.

**D19. The tracker is scoped to one invoke, separately from the emitter.** `invoke_graph` wraps `get_graph().invoke(...)` in `with turn_progress_scope():`. The scope sets the var with a token before the invoke and resets it in `finally`. It is not installed inside `set_event_emitter`.
- **The fix-slot analogy holds only for setting the var before the invoke.** LangGraph copies the calling context into every task and a copy shares the object, so every node and every concurrent pipeline reports into the one tracker.
- **It does not hold for lifetime.** The fix slots stay set after the turn; the tracker is removed. Any caller that runs `invoke_graph` in its own context is left with no tracker. This matters for the tests that do: the plan review found leak sources at `tests/unit/test_graph_nodes.py:4016-4022` and `tests/integration/test_sweeper_describe_only.py:287, 402, 426, 574, 653, 745`. Pinned by `test_the_tracker_does_not_outlive_the_turn` (Task 3).
- **Existing node-level tests are unaffected.** Dozens of unit tests install an emitter and call nodes directly (`test_graph_nodes.py:940-955`, `test_deck_level_spec_change.py:147-162`, `test_slide_release.py:75-80`). They have no tracker, so they see exactly the events they see today.
- **Tests that need the tracker after the turn read the DB row.** None can hold the tracker past `invoke_graph`. The compiled-graph tests in Task 3 call `graph.invoke` directly inside their own `with turn_progress_scope() as progress:` block and read `progress.snapshot()` before the block exits.

**D20. The DONE reports are inline at each of the pipeline's three returns.** There is no wrapper. `tests/unit/test_graph_nodes.py:3573` (`test_no_node_returns_a_dict_a_helper_built`) forbids a `*_node` from returning a helper's dict, and its spirit forbids `update = helper(); return update` too.

**D21. The polling transport is not wired into the current Playwright harness.** There is one global `webServer` on `localhost:3000`, where `isPollingMode()` is false (`frontend/tests/e2e/incremental-slide-delivery.spec.ts:295-338`). A polling project would need a second `webServer` with `VITE_USE_POLLING=true` (`api.ts:37-39`; the spec itself notes this at `:335-336`). That is deferred. Polling is covered instead by vitest driving `api.startPolling` with a stubbed `fetch` (precedent: `frontend/src/services/slideRevisions.test.ts`) and by the backend integration test. Playwright covers SSE end to end in a real browser.

**D22. Accessibility.**
- The placeholder wrapper gains `aria-live="polite"`, `aria-atomic="true"` and `data-testid="chat-turn-progress"`.
- It does **not** get `role="status"`: `frontend/tests/e2e/mixed-release-collaboration.spec.ts:451` asserts exactly one `status` role on its page.
- **Caveat (accepted):** the region is mounted only while `isLoading` (`MessageList.tsx:26-31`). Many screen readers do not announce content that is already present when a live region is inserted, so the first stage may go unannounced; later changes are announced. On SSE the label can change several times a second.
- Keeping the region permanently mounted would restructure `MessageList` and is not done here.

---

## Global Constraints

- **Python:** a per-worktree uv venv. First run `uv sync --extra dev` in the worktree root, then run everything as `uv run …`. Never `pip install`. Run tests as `uv run pytest <paths> -n 4 -q`, **never** `-n auto`.
- **Frontend:**
  - unit tests: `cd frontend && npx vitest run <paths>`;
  - type check: `cd frontend && npm run typecheck` (= `tsc -b`);
  - full unit suite: `cd frontend && npm run test:unit`;
  - E2E (CI form): `cd frontend && npx playwright test tests/e2e/<spec>.spec.ts --project=chromium --workers=1`. The API is mocked with `page.route`, and Playwright's `webServer` starts the dev server.
- **PostgreSQL-marked suites** self-skip unless `TELLR_TEST_POSTGRES_URL` names a reachable server. They run in CI (the unit job and `layer4-integration`).
- **No deploys** and no `publish-dev.yml` inside tasks. See *Post-merge manual check*.
- **Sibling scope.** Do not touch `_surface_notice`, `_transient_failure_notice` or `_placehold_failed_position`'s wording (#321), finding text (#316), clear chat (#323), Spec export (#318) or `evals/` (#313).
- **AST scans over `nodes.py`.** No node-level helper may be named `*_node`: the scans at `tests/unit/test_graph_nodes.py:3363-3367` collect every `FunctionDef` ending in `_node`. No node may `return helper(...)` (`:3573`).
- **Fire-and-forget.** Every `report_*` call must never raise and must never be a precondition for building a deck. This is the same contract as `emit_event` (`event_emitter.py:166-183`), and it is proven at deck level by `test_a_raising_progress_tracker_never_fails_a_deck` (Task 3).
- **New test files clear shared state at setup *and* teardown.** Every new backend test file has an autouse fixture that sets `turn_progress_var` to `None` and calls `set_event_emitter(None)` and `set_chat_request_id(None)`, both before and after each test.

## Review Focus (the whole-branch reviewer should attack these)

1. **Lock discipline in `TurnProgress.report`.** The emit must be inside the lock and the persist outside it. Pinned deterministically by `test_queue_order_is_seq_order_even_when_an_emit_is_slow` and `test_a_slow_persist_does_not_block_another_slides_report` (Task 2).
2. **The conditional UPDATE and its bound.** Drop the `progress_seq < :seq` predicate and `test_an_older_snapshot_never_overwrites_a_newer_one` (Task 1) and both PostgreSQL queued-writer interleavings (Task 5) must go red. Drop the `SET LOCAL lock_timeout` and `test_a_progress_write_gives_up_on_a_held_row_lock_within_the_timeout` (Task 5) must go red.
3. **Cross-worker coherence.** `get_chat_request` must read `progress_json` from the row. An in-process cache turns `test_a_poll_on_another_worker_process_sees_the_running_turns_stage` red (Task 5; it uses a real second OS process).
4. **The tracker is scoped to the turn.** Without the `finally` reset, `test_the_tracker_does_not_outlive_the_turn` (Task 3) goes red. A leak would turn `test_reports_without_a_tracker_are_noops_and_never_raise` red in full-suite runs.
5. **A broken tracker never fails a deck.** Drop the wrappers' `try` and `test_a_raising_progress_tracker_never_fails_a_deck` (Task 3) goes red.
6. **Reset at send** (frontend). Without it, the next turn's `seq 1` is discarded behind the last turn's high `seq`. Pinned by `ChatPanel.turnProgress.test.tsx::the next turn starts fresh even though its seq restarts at 1`.
7. **The migration's ALTER path** must be tested by dropping the columns first, not via `create_all` (the skill's §1 lesson). Pinned by `test_a_pre_319_chat_requests_table_gains_both_columns` and `test_run_migrations_wires_the_helper`.
8. **Transcript hygiene.** No `turn_progress` in poll `events`, no new message rows, no chat bubble. Pinned in Tasks 4, 5, 8 and 9.

---

## File Structure

| File | Task | Change | Responsibility |
|---|---|---|---|
| `src/database/models/session.py` | 1 | Modify | `ChatRequest.progress_json`, `ChatRequest.progress_seq` |
| `src/core/database.py` | 1 | Modify | `_migrate_chat_request_progress`, wired into `_run_migrations` |
| `src/api/services/session_manager.py` | 1 | Modify | `record_chat_request_progress` (conditional UPDATE; PostgreSQL `SET LOCAL lock_timeout`); `get_chat_request` returns `turn_progress` |
| `src/api/schemas/streaming.py` | 2 | Modify | `StreamEventType.TURN_PROGRESS`, `StreamEvent.turn_progress` |
| `src/services/graph/progress.py` | 2 | Create | `TurnPhase`, `SlideProgressStage`, `TurnProgress`, `turn_progress_scope`, `get_turn_progress`, `report_phase`, `report_slide`, `report_slides` |
| `frontend/src/types/turnProgress.ts` | 2 | Create | Wire types and literal lists (needed by Task 2's `api.ts` edit) |
| `frontend/src/services/api.ts` | 2, 7 | Modify | Task 2: `'turn_progress'` in the `StreamEventType` union and `StreamEvent.turn_progress`. Task 7: `PollResponse.turn_progress` and `startPolling` emission |
| `src/services/graph/nodes.py` | 3 | Modify | Report calls at the D18 sites |
| `src/services/graph/builder.py` | 3 | Modify | `invoke_graph` wraps the invoke in `turn_progress_scope()` |
| `src/api/routes/chat.py` | 4 | Modify | The poll response gains `turn_progress` |
| `tests/unit/test_chat_request_progress.py` | 1 | Create | Migration ALTER path, conditional write, row shape (SQLite plus a PostgreSQL class) |
| `tests/unit/test_turn_progress.py` | 2 | Create | Tracker merge rules, scope lifetime, lock discipline, sinks, `report_slides`, concurrency stress |
| `tests/unit/test_slide_release.py` | 2, 4 | Modify | Task 2: pinned enum set (`:144-158`); Task 2 keeps `test_every_backend_event_type_is_in_the_typescript_union` (`:231-245`) green. Task 4: pinned poll key set (`:965-975`) |
| `tests/unit/test_turn_progress_graph.py` | 3 | Create | Compiled-graph turns: stage order, interleavings including a slide waiting for a fix slot, edit/discuss/data/deck-level/failure paths, a raising tracker, the DB row |
| `tests/unit/test_graph_builder.py` | 3 | Modify | `_FakeCompiled` records the tracker; a fresh tracker per turn; the tracker does not outlive the turn |
| `tests/unit/test_poll_turn_progress.py` | 4 | Create | Poll projection rules |
| `tests/unit/test_turn_progress_cross_worker.py` | 5 | Create | A second OS process reads the running turn's stage |
| `tests/integration/test_turn_progress_polling.py` | 5 | Create | The real async transport, polled from inside the running turn |
| `tests/integration/test_graph_mode_turn.py` | 5 | Modify | The real SSE generator yields `TURN_PROGRESS` before `COMPLETE`, with strictly increasing `seq` |
| `tests/integration/test_layer4_multi_worker.py` | 5 | Modify | PostgreSQL concurrent-writer interleavings and the lock-timeout bound |
| `.github/workflows/test.yml` | 5, 9 | Modify | The new integration file in `integration-graph` (5); the new e2e spec in the matrix (9) |
| `frontend/src/utils/turnProgress.ts` | 6 | Create | `DEFAULT_TURN_LABEL`, `parseTurnProgress`, `newerTurnProgress`, `describeTurnProgress` |
| `frontend/src/utils/turnProgress.test.ts` | 6 | Create | Copy table, ordering, validation |
| `frontend/src/utils/turnProgress.conformance.test.ts` | 6 | Create | TS literals vs Python enums |
| `frontend/src/services/turnProgressTransport.test.ts` | 7 | Create | `startPolling` and `streamChat` deliver `turn_progress` |
| `frontend/src/components/ChatPanel/ChatPanel.tsx` | 8 | Modify | Holds the turn's newest snapshot and passes the label |
| `frontend/src/components/ChatPanel/MessageList.tsx` | 8 | Modify | `progressLabel` prop, test id, `aria-live`, `aria-atomic` |
| `frontend/src/components/ChatPanel/ChatPanel.turnProgress.test.tsx` | 8 | Create | Mounted ChatPanel behaviour |
| `frontend/src/components/ChatPanel/MessageList.turnProgress.test.tsx` | 8 | Create | Placeholder rendering |
| `frontend/tests/e2e/turn-progress.spec.ts` | 9 | Create | The SSE path in a real browser |
| `docs/technical/real-time-streaming.md`, `docs/technical/multi-user-concurrency.md`, `docs/technical/database-configuration.md`, `docs/technical/frontend-overview.md`, `docs/user-guide/01-generating-slides.md` | 10 | Modify | Contract and behaviour docs |

## Task order and parallelism

- **Backend:** 1 → 2 → 3 → 4 → 5. Tasks 2 and 4 both edit `tests/unit/test_slide_release.py`. Task 5 is proofs over Tasks 1–4.
- **Frontend:** Task 2 creates `frontend/src/types/turnProgress.ts` and makes the `api.ts` union and `StreamEvent` edits, then 6 → 7 → 8 → 9.
  - Task 6's conformance test reads `progress.py` (Task 2).
  - Task 7 depends on Task 2 for `api.ts`.
  - Task 9 runs after Task 5, because both edit `.github/workflows/test.yml`.
- **Docs:** Task 10 goes last.
- **Parallel:** after Task 2, backend Tasks 3–5 and frontend Tasks 6–8 can run in parallel.

## Before Task 1

- [ ] `uv sync --extra dev`. The worktree already has `.venv` and `frontend/node_modules`; re-sync anyway.
- [ ] Corrections pre-pass (`executing-plans-tellr` §2). Re-verify every `file:line` this plan cites, especially:
  - `nodes.py:1463, 1807, 2018, 2150-2156, 3129-3216, 3266-3294, 3368`;
  - `builder.py:340-377`;
  - `chat.py:892-896, 950-967`;
  - `database.py:391-405, 653-658`;
  - `session_manager.py:3246-3302`;
  - `test_slide_release.py:144-158, 231-245, 965-975`.
- [ ] Baseline as **cause-sets**. On `679d2f21` the planner measured, and the plan reviewer reproduced:
  - `uv run pytest tests/unit/test_slide_release.py tests/unit/test_graph_builder.py tests/unit/test_slide_pipeline.py tests/unit/test_authz_chat_poll.py tests/unit/test_spec_dirty_marker.py -n 4 -q` → 133 passed, 4 skipped (PostgreSQL);
  - `uv run pytest tests/unit/test_graph_nodes.py tests/integration/test_architect_reply_is_persisted.py tests/unit/test_e2e_matrix_covers_specs.py tests/unit/test_ci_collects_integration_tests.py -n 4 -q` → 260 passed;
  - `cd frontend && npx vitest run src/components/ChatPanel src/services/slideRevisions.test.ts` → 24 passed.

  Then re-run the full `uv run pytest tests/unit -n 4 -q` and `npm run test:unit`, and record any failure *causes*. Re-run the **full** unit suite after Tasks 2 and 3 (not just their files): the context-leak class of defect only shows up in a full run.

---

### Task 1: Store a turn's progress on its chat request

Models: test=opus impl=opus

This is a schema migration on a production table, and the conditional write *is* the concurrency guarantee. Both fail silently if wrong.

**Files:**
- Modify: `src/database/models/session.py`, after `result_json` (`:90`).
- Modify: `src/core/database.py`. Put the new helper next to `_migrate_spec_dirty_marker` (`:1304`), and call it in `_run_migrations` immediately before `_reassign_new_objects_to_shared_owner(conn, is_sqlite)` (`:658`).
- Modify: `src/api/services/session_manager.py`:
  - the import `from sqlalchemy import and_, delete, func, or_` (`:14`) becomes `from sqlalchemy import and_, delete, func, or_, text, update`;
  - a new module constant and a new method go after `set_chat_request_result` (`:3246-3265`);
  - `get_chat_request` (`:3267-3302`) gains one key.
- Create: `tests/unit/test_chat_request_progress.py`.

**Interfaces (produced):**

```python
# src/database/models/session.py — class ChatRequest, after result_json
    # #319: the graph turn's latest stage summary (JSON) and its sequence number.
    # Written ONLY by SessionManager.record_chat_request_progress, whose
    # conditional UPDATE on progress_seq is what stops concurrent per-slide
    # writers regressing it.  Read by GET /chat/poll as `turn_progress`.
    progress_json = Column(Text, nullable=True)
    progress_seq = Column(Integer, nullable=True)
```

```python
# src/core/database.py
def _migrate_chat_request_progress(conn, inspector, schema, _qual, is_sqlite) -> None:
    """Add ``progress_json`` and ``progress_seq`` to ``chat_requests`` (#319, idempotent).

    ``create_all`` adds both on a fresh install from the ORM model but never ALTERs
    an existing table, so for every database provisioned before #319 this helper is
    the only thing that adds them.  Both are nullable with no default: a request
    that predates the columns, a monolith turn and a pending request all read NULL,
    which the poll serves as ``turn_progress: null``.  TEXT/INTEGER on both
    dialects, matching ``result_json``.
    """
    from sqlalchemy import text

    try:
        cols = {c["name"] for c in inspector.get_columns("chat_requests", schema=schema)}
    except Exception:
        return
    if not cols:
        return
    qualified = _qual("chat_requests")
    for col_name, col_def in (
        ("progress_json", "TEXT NULL"),
        ("progress_seq", "INTEGER NULL"),
    ):
        if col_name not in cols:
            logger.info("Migration: adding %s to chat_requests", col_name)
            conn.execute(text(f"ALTER TABLE {qualified} ADD COLUMN {col_name} {col_def}"))
```

In `_run_migrations`, put this before the owner-reassignment call, with a one-line comment:

```python
        # --- chat_requests: the graph turn's stage summary for the chat placeholder (#319) ---
        _migrate_chat_request_progress(conn, inspector, schema, _qual, is_sqlite)
```

```python
# src/api/services/session_manager.py — module level, near the other constants
#: How long a turn-progress write waits for its request row's lock on PostgreSQL
#: before giving up (#319).  A progress write is a side channel running on a
#: slide's own thread; it must never hold that slide up for long.
_PROGRESS_LOCK_TIMEOUT = "2s"

# src/api/services/session_manager.py — class SessionManager
def record_chat_request_progress(
    self, request_id: str, seq: int, progress: Dict[str, Any]
) -> bool:
    """Store *progress* as this request's stage summary iff *seq* is newer.

    The predicate is the whole concurrency story: several slide pipelines report
    from several threads and their commits land in any order, so an older
    snapshot must be a no-op rather than a regression.  On PostgreSQL a
    concurrent UPDATE of the same row waits for the first commit and then
    re-evaluates this WHERE against the new row (READ COMMITTED), so two
    writers cannot both win.  Core ``update`` on ``__table__``, as
    ``spec_sync``'s claim does (``src/services/spec_sync.py:475-487``).

    On PostgreSQL the wait for the row lock is bounded by ``SET LOCAL
    lock_timeout``: ``get_db_session`` runs one transaction per ``with`` block,
    so the setting covers exactly the UPDATE below.  A timeout raises
    ``sqlalchemy.exc.OperationalError``; the only production caller
    (``progress._persist``) logs it and the next report carries a newer snapshot.

    Returns True when this snapshot was stored, False when a newer (or equal)
    one already was or the request does not exist.
    """
    table = ChatRequest.__table__
    statement = (
        update(table)
        .where(table.c.request_id == request_id)
        .where(or_(table.c.progress_seq.is_(None), table.c.progress_seq < seq))
        .values(progress_json=json.dumps(progress), progress_seq=seq)
    )
    with get_db_session() as db:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text(f"SET LOCAL lock_timeout = '{_PROGRESS_LOCK_TIMEOUT}'"))
        return db.execute(statement).rowcount == 1
```

`get_chat_request` adds one key to the dict it returns:

```python
                "turn_progress": (
                    json.loads(chat_request.progress_json)
                    if chat_request.progress_json
                    else None
                ),
```

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_chat_request_progress.py`. Assertions must be behavioural only.
  - **Fixtures.** For the SessionManager tests, use `graph_env` from `tests/unit/conftest_graph.py:445`; it patches `src.api.services.session_manager.get_db_session` and seeds a session. For the migration tests, use a fresh `create_engine("sqlite:///<tmp_path>/m.db")` + `Base.metadata.create_all` + `_run_migrations` (pattern: `tests/unit/test_spec_dirty_marker.py:255-296`).
  - `test_a_pre_319_chat_requests_table_gains_both_columns`:
    - `create_all`, then insert one `chat_requests` row;
    - drop both columns (`ALTER TABLE chat_requests DROP COLUMN progress_json` and `… DROP COLUMN progress_seq`) and assert both are absent, using a fresh `inspect`;
    - inside `engine.begin()`, call `_migrate_chat_request_progress(conn, inspect(conn), None, lambda t: f'"{t}"', True)`;
    - assert both columns are present with `nullable is True`, and that the pre-existing row survives with both NULL.
  - `test_run_migrations_wires_the_helper`: the same drop, then `_run_migrations(engine)`, then both columns are present. This catches a helper that exists but is never called.
  - `test_the_migration_is_idempotent`: the helper twice, then `_run_migrations` twice. No error, and each column appears exactly once.
  - `test_get_chat_request_reports_no_progress_before_any_is_recorded`: `create_chat_request(env.session_id)` → `get_chat_request(rid)["turn_progress"] is None`.
  - `test_a_newer_snapshot_replaces_an_older_one`: record seq 1 → True, and it is served; record seq 3 → True, and it is served (the whole dict equals what was written).
  - `test_an_older_snapshot_never_overwrites_a_newer_one`: record 3; then record 2 → False; then record 3 again (equal) → False. The served dict's `seq` is still 3, and the raw `progress_seq` read through `env.factory()` is 3.
  - `test_an_unknown_request_records_nothing_and_does_not_raise`: returns False.
  - `test_status_and_result_writers_do_not_clobber_progress`: record seq 2, then `update_chat_request_status(rid, "running")`, `set_chat_request_result(rid, {"slides": None})` and `update_chat_request_status(rid, "completed")`. Progress is still seq 2.
  - Every SQLite test above also proves that `SET LOCAL` is **not** issued on SQLite, because SQLite would reject it as a syntax error.
  - `class TestPostgresAlterPath` (`pytestmark = pytest.mark.postgres`; copy the self-skip and throwaway-DB fixture from `tests/unit/test_spec_dirty_marker.py:33-50, 303-338`): drop both columns on a real PostgreSQL schema, run `_run_migrations`, assert both are present and nullable, then run `_run_migrations` again with no error.
  - The behavioural proof of the lock timeout is PostgreSQL-only and lives in Task 5 Step 2 (`test_a_progress_write_gives_up_on_a_held_row_lock_within_the_timeout`).
- [ ] **Step 2: Confirm red.** `uv run pytest tests/unit/test_chat_request_progress.py -n 4 -q`. The tests fail on import (`_migrate_chat_request_progress`) or with `AttributeError: record_chat_request_progress`.
- [ ] **Step 3: Implement** the four edits above.
- [ ] **Step 4: Green and sabotage.** Run the file and confirm green. Then apply each sabotage and confirm red:
  - (a) `return` at the top of the helper → the ALTER-path test;
  - (b) delete the `_run_migrations` call → the wiring test;
  - (c) delete `.where(or_(…progress_seq < seq))` → the older-snapshot test;
  - (d) drop the `dialect.name` guard so `SET LOCAL` runs everywhere → every SQLite test above.
- [ ] **Step 5: Regression.** `uv run pytest tests/unit/test_chat_request_progress.py tests/unit/test_spec_dirty_marker.py tests/unit/test_database_migrations.py tests/unit/test_chat_session_creation.py tests/unit/test_authz_chat_poll.py tests/unit/test_slide_release.py -n 4 -q`.

---

### Task 2: The turn-progress tracker, its event, and the frontend wire types

Models: test=opus impl=sonnet

The code is given in full. The tests carry the concurrency and lifetime proofs, so the strongest tier must write them. This task also lands the frontend half of the event's wire contract. Otherwise `test_every_backend_event_type_is_in_the_typescript_union` (`tests/unit/test_slide_release.py:231-245`) goes red: it compares the backend enum with the `api.ts` union exactly.

**Files:**
- Modify: `src/api/schemas/streaming.py`: `StreamEventType` (`:13-23`); in `StreamEvent`, a new field after `slide_cursor` (`:75-77`) and the docstring (`:26-41`).
- Create: `src/services/graph/progress.py`.
- Create: `frontend/src/types/turnProgress.ts`. This is the wire type the `StreamEvent` field needs; its content is given in Task 6's *Interfaces*.
- Modify: `frontend/src/services/api.ts`:
  - add `import type { TurnProgress } from '../types/turnProgress';` with the other type imports (`:1-5`);
  - add `| 'turn_progress'` to the `StreamEventType` union (`:62`);
  - add to the `StreamEvent` interface (`:64-90`): `/** #319: the graph turn's stage summary, on a 'turn_progress' event. */ turn_progress?: TurnProgress | null;`.
- Create: `tests/unit/test_turn_progress.py`.
- Modify: `tests/unit/test_slide_release.py:144-158`. The pinned enum set gains `"turn_progress"`. Update the method name and the docstring's "seven/eight" wording, without weakening the assertion.

**Interfaces (produced):**

```python
# src/api/schemas/streaming.py
    TURN_PROGRESS = "turn_progress"  # The graph turn's stage summary for the chat placeholder (#319)
...
    # #319 — the graph turn's stage summary ({seq, phase, slides}); see
    # src/services/graph/progress.py for the contract.  Only on turn_progress events.
    turn_progress: Optional[Dict[str, Any]] = Field(
        default=None, description="Graph turn stage summary (for turn_progress events)"
    )
```

**Snapshot contract** (JSON). Every list is ascending, the lists are disjoint, and positions are 0-based:

```json
{"seq": 7, "phase": "building",
 "slides": {"total": 10, "building": [0, 1, 2], "reviewing": [3], "fixing": [4, 5], "done": [6, 7, 8, 9]}}
```

`src/services/graph/progress.py`: write this module as given. The docstring is required content.

```python
"""The graph turn's stage summary, for the chat placeholder (#319).

One ``TurnProgress`` per turn, installed by ``invoke_graph`` through
:func:`turn_progress_scope` for exactly the duration of ``graph.invoke``.  It is
set BEFORE the invoke for the same reason the fix slots are: LangGraph copies
the calling context into every task and a copy shares the OBJECT, so the
architect, the foreman and every concurrent ``slide_pipeline_node`` report into
one tracker.  A ``ContextVar.set()`` inside a node would die with that node's
context copy (see ``event_emitter.advance_slide_cursor``), which is why the
tracker is created once per turn and never replaced inside it.  Unlike the fix
slots it does NOT outlive the turn: the scope resets the var with its token in a
``finally``, so a caller that runs ``invoke_graph`` in its own context — every
test does — is left with no tracker, and nothing after the invoke can report.

Monotonic, precisely
--------------------
* ``phase`` has a rank: planning, gathering_data and checking_slides share rank 0
  (the architect and the analyst may alternate in one turn), building is 1,
  reviewing_deck is 2.  A report whose rank is LOWER than the current one is
  ignored.
* Each slide's stage has a rank: building 1 < reviewing 2 < fixing 3 < done 4.  A
  report applies only when its rank is HIGHER; stages may be skipped forward.
* An applied slide report raises the phase to building if it is below that.
* ``covered`` only grows; ``total`` counts every covered or staged position.
* ``seq`` rises by one per report that changed something; a no-op report
  publishes nothing (no heartbeats — the label is never timer-driven).

Two sinks, and why each is ordered as it is
-------------------------------------------
* SSE: the event is queued INSIDE the lock, so the queue carries snapshots in
  strictly increasing ``seq`` order (``Queue.put`` on the unbounded queue never
  blocks).
* Polling: the snapshot is written to the turn's ``chat_requests`` row OUTSIDE
  the lock, by ``SessionManager.record_chat_request_progress``'s conditional
  UPDATE, so commits may land in any order and the row still never goes
  backwards.  A write never blocks another slide on the tracker lock; it blocks
  only its own thread, and on PostgreSQL for at most ``lock_timeout`` (2 s) on
  the row lock.  The poll reads that row, so every worker process serves the
  same stage.

With no tracker (outside ``invoke_graph``: a layer-1 test calling a node
directly, the monolith) every report is a no-op.  Nothing here raises: progress
is a side channel, never a precondition for building a deck.
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from enum import Enum
from typing import Any, Dict, Iterable, Iterator, Mapping, Optional

from src.api.schemas.streaming import StreamEvent, StreamEventType
from src.api.services.session_manager import get_session_manager
from src.services.graph.event_emitter import emit_event, get_chat_request_id

logger = logging.getLogger(__name__)


# The two enums are read as TEXT by
# frontend/src/utils/turnProgress.conformance.test.ts: keep each class body to
# `NAME = "value"` lines only — no docstring, no blank line inside the class.
class TurnPhase(str, Enum):
    PLANNING = "planning"
    GATHERING_DATA = "gathering_data"
    CHECKING_SLIDES = "checking_slides"
    BUILDING = "building"
    REVIEWING_DECK = "reviewing_deck"


class SlideProgressStage(str, Enum):
    BUILDING = "building"
    REVIEWING = "reviewing"
    FIXING = "fixing"
    DONE = "done"


PHASE_RANK: Dict[TurnPhase, int] = {
    TurnPhase.PLANNING: 0,
    TurnPhase.GATHERING_DATA: 0,
    TurnPhase.CHECKING_SLIDES: 0,
    TurnPhase.BUILDING: 1,
    TurnPhase.REVIEWING_DECK: 2,
}

STAGE_RANK: Dict[SlideProgressStage, int] = {
    SlideProgressStage.BUILDING: 1,
    SlideProgressStage.REVIEWING: 2,
    SlideProgressStage.FIXING: 3,
    SlideProgressStage.DONE: 4,
}


class TurnProgress:
    """One turn's stage summary.  Thread-safe; every merge is monotonic."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seq = 0
        self._phase: Optional[TurnPhase] = None
        self._covered: set = set()
        self._stages: Dict[int, SlideProgressStage] = {}

    def report(
        self,
        *,
        phase: Optional[TurnPhase] = None,
        covered: Iterable[int] = (),
        stages: Optional[Mapping[int, SlideProgressStage]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Merge one report; publish and return the new snapshot, or None if nothing changed."""
        with self._lock:
            changed = False
            if phase is not None:
                phase = TurnPhase(phase)
                if phase != self._phase and (
                    self._phase is None or PHASE_RANK[phase] >= PHASE_RANK[self._phase]
                ):
                    self._phase = phase
                    changed = True
            for position in covered:
                position = int(position)
                if position not in self._covered:
                    self._covered.add(position)
                    changed = True
            stage_applied = False
            for position, stage in (stages or {}).items():
                position, stage = int(position), SlideProgressStage(stage)
                current = self._stages.get(position)
                if current is None or STAGE_RANK[stage] > STAGE_RANK[current]:
                    self._stages[position] = stage
                    stage_applied = True
                if position not in self._covered:
                    self._covered.add(position)
                    changed = True
            if stage_applied:
                changed = True
                if self._phase is None or PHASE_RANK[self._phase] < PHASE_RANK[TurnPhase.BUILDING]:
                    self._phase = TurnPhase.BUILDING
            if not changed:
                return None
            self._seq += 1
            snapshot = self._snapshot_locked()
            # INSIDE the lock: the SSE queue then carries snapshots in seq order.
            emit_event(
                StreamEvent(
                    type=StreamEventType.TURN_PROGRESS,
                    turn_progress=snapshot,
                    metadata={"node": "progress"},
                )
            )
        # OUTSIDE the lock: a slow or failing write must not stall another slide.
        _persist(snapshot)
        return snapshot

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return self._snapshot_locked()

    def _snapshot_locked(self) -> Dict[str, Any]:
        slides: Dict[str, Any] = {"total": len(self._covered)}
        for stage in SlideProgressStage:
            slides[stage.value] = sorted(
                position for position, current in self._stages.items() if current == stage
            )
        return {
            "seq": self._seq,
            "phase": self._phase.value if self._phase is not None else None,
            "slides": slides,
        }


#: This turn's tracker — set only inside ``turn_progress_scope()`` (i.e. inside
#: ``invoke_graph``'s invoke); ``None`` everywhere else.
turn_progress_var: ContextVar[Optional[TurnProgress]] = ContextVar(
    "graph_turn_progress", default=None
)


@contextmanager
def turn_progress_scope() -> Iterator[TurnProgress]:
    """Install a fresh tracker for the ``with`` block, then remove it, success or failure.

    Enter it in the context that then calls ``graph.invoke``: LangGraph copies that
    context into every task, and a copy shares the object.  Never enter it inside a
    node — a set there would fork the tracker per task.
    """
    progress = TurnProgress()
    token = turn_progress_var.set(progress)
    try:
        yield progress
    finally:
        turn_progress_var.reset(token)


def get_turn_progress() -> Optional[TurnProgress]:
    return turn_progress_var.get()


def report_phase(
    phase: TurnPhase,
    *,
    covered: Iterable[int] = (),
    dispatched: Iterable[int] = (),
) -> bool:
    """Report a turn phase (and, for building, the covered and dispatched slides).  Never raises."""
    try:
        progress = turn_progress_var.get()
        if progress is None:
            return False
        stages = {int(p): SlideProgressStage.BUILDING for p in dispatched}
        return progress.report(phase=phase, covered=covered, stages=stages) is not None
    except Exception:
        logger.warning("Turn progress could not be recorded; continuing", exc_info=True)
        return False


def report_slide(position: int, stage: SlideProgressStage) -> bool:
    """Report one slide's stage.  Never raises."""
    try:
        progress = turn_progress_var.get()
        if progress is None:
            return False
        return progress.report(stages={int(position): stage}) is not None
    except Exception:
        logger.warning("Turn progress could not be recorded; continuing", exc_info=True)
        return False


def report_slides(positions: Iterable[int], stage: SlideProgressStage) -> bool:
    """Report several slides reaching one stage as ONE snapshot and one write.  Never raises."""
    try:
        progress = turn_progress_var.get()
        if progress is None:
            return False
        stages = {int(p): stage for p in positions}
        if not stages:
            return False
        return progress.report(stages=stages) is not None
    except Exception:
        logger.warning("Turn progress could not be recorded; continuing", exc_info=True)
        return False


def _persist(snapshot: Dict[str, Any]) -> None:
    """Write *snapshot* to this turn's chat request, when there is one.  Never raises."""
    request_id = get_chat_request_id()
    if not request_id:
        return  # the SSE path and the sweeper have no request row
    try:
        get_session_manager().record_chat_request_progress(
            request_id, int(snapshot["seq"]), snapshot
        )
    except Exception:
        logger.warning(
            "Could not persist turn progress; polling clients keep the previous stage",
            exc_info=True,
        )
```

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_turn_progress.py`.
  - **Setup.** Add an autouse fixture that, **at setup and at teardown**, sets `turn_progress_var` to `None` and calls `set_event_emitter(None)` and `set_chat_request_id(None)`. Install an emitter with `set_event_emitter(queue.Queue())` and drain it with `get_nowait()` (pattern: `tests/unit/test_slide_release.py:75-80`). For a fake session manager, use `monkeypatch.setattr("src.services.graph.progress.get_session_manager", lambda: fake)`. Every test that needs a tracker runs inside `with turn_progress_scope() as progress:`.
  - **No tracker, basic event, wire shape:**
    - `test_reports_without_a_tracker_are_noops_and_never_raise`: outside any scope, all three report functions return False and queue nothing.
    - `test_the_first_report_publishes_seq_one_as_a_turn_progress_event`:
      - the event type is `TURN_PROGRESS`;
      - `metadata == {"node": "progress"}`. This is required because `tests/unit/test_graph_builder.py:614-616` groups a turn's events by `metadata["node"]`;
      - `to_sse()` starts with `"event: turn_progress\n"`;
      - the parsed `data:` JSON has `turn_progress.seq == 1`.
    - `test_the_snapshot_shape_is_the_wire_contract`: the top keys are exactly `{"seq", "phase", "slides"}`; the slide keys are exactly `{"total"} | {s.value for s in SlideProgressStage}`; the lists are ascending and pairwise disjoint; `json.dumps` round-trips.
  - **Merge rules:**
    - `test_the_phase_rank_never_decreases`: `BUILDING`, then a late `PLANNING` → no event, `seq` unchanged, phase still building. `REVIEWING_DECK`, then `BUILDING` → dropped.
    - `test_planning_rank_phases_alternate_freely`: `PLANNING → GATHERING_DATA → PLANNING → CHECKING_SLIDES` publishes four snapshots, `seq` 1 to 4.
    - `test_a_slide_stage_never_regresses`: `DONE`, then `REVIEWING` → no event. `FIXING`, then `BUILDING` → no event.
    - `test_stages_may_skip_forward`: `BUILDING`, then `DONE`, applies.
    - `test_a_repeated_report_publishes_nothing`: the same `REVIEWING` twice gives one event.
    - `test_covered_only_grows_and_total_counts_unreported_slides`:
      - `report_phase(BUILDING, covered=[0..4], dispatched=[0, 1])` → total 5, building `[0, 1]`;
      - then `covered=[3, 4], dispatched=[3, 4]` → total still 5;
      - then `report_slide(7, REVIEWING)` → total 6.
    - `test_a_slide_report_raises_the_phase_to_building_and_no_further`: `PLANNING`, then a slide report → phase building. `REVIEWING_DECK`, then `report_slide(0, DONE)` → the phase stays `reviewing_deck`.
  - **`report_slides`:**
    - `test_report_slides_publishes_one_snapshot_for_many_slides`: `report_slides([0, 1, 2], DONE)` queues exactly **one** event, with `done == [0, 1, 2]`. A fake persist sees exactly one call.
    - `test_report_slides_with_no_positions_publishes_nothing`.
  - **Concurrency and lock discipline:**
    - `test_concurrent_reports_reach_the_queue_in_seq_order_and_never_regress`:
      - 15 threads start together behind a `threading.Barrier(15)`. Each walks its position through `building → reviewing → [fixing if p % 3 == 0] → done`, sleeping `random.Random(p).uniform(0, 0.002)` between steps.
      - A 16th thread re-reports `REVIEWING` for every position after random delays (regression attempts).
      - Drain the queue and assert: `seq` equals `1..n` in queue order; across successive snapshots each position's stage rank never decreases; `len(done)` never decreases; the final snapshot has `done == list(range(15))`.
    - `test_queue_order_is_seq_order_even_when_an_emit_is_slow` (deterministic):
      - wrap `src.services.graph.progress.emit_event` so that, for `seq == 1`, it sets `a_in_emit`, waits up to 0.3 s for `b_done`, then delegates;
      - thread A runs `report_slide(0, BUILDING)`; after `a_in_emit`, thread B runs `report_slide(1, BUILDING)` and sets `b_done`;
      - assert the queue order is `[1, 2]`. With the emit moved outside the lock, B finishes first and the order is `[2, 1]`.
    - `test_a_slow_persist_does_not_block_another_slides_report` (deterministic):
      - `set_chat_request_id("req-1")`; the fake's `record_chat_request_progress` blocks on an `Event` when `seq == 1`;
      - thread A runs `report_slide(0, BUILDING)`; once A is inside the fake, thread B runs `report_slide(1, BUILDING)`;
      - assert `B.join(timeout=2)` completes while A is still blocked, and that the queue already holds `seq` 1 and 2; then release A;
      - sabotage: move `_persist` into the `with` block → B blocks → red.
  - **Persist sink:**
    - `test_persist_receives_each_snapshot_with_its_seq`: the fake records `[(rid, 1, snap1), (rid, 2, snap2)]`, and each snap equals the queued event's `turn_progress`.
    - `test_persist_is_skipped_without_a_request_id`: with request id `None`, the fake is never called and the event is still queued.
    - `test_a_failing_persist_is_logged_and_never_raises`: the fake raises → the report returns True and caplog has the warning.
  - **Scope lifetime:** `test_a_scope_installs_a_fresh_tracker_that_copied_contexts_share_and_removes_it_on_exit`:
    - inside the scope, `contextvars.copy_context().run(report_slide, 0, BUILDING)` is visible through the parent's `get_turn_progress().snapshot()`;
    - after the block exits, `get_turn_progress() is None`;
    - a block exited by an exception also leaves `None`;
    - two sequential scopes yield distinct objects, each starting at `seq == 0`.
    - (Pattern: `tests/unit/test_slide_pipeline.py:391-404`.)
- [ ] **Step 2: Confirm red.** Expect `ModuleNotFoundError: src.services.graph.progress`. Update `test_slide_release.py:144-158` and confirm it is red too.
- [ ] **Step 3: Implement** `streaming.py`, `progress.py`, `frontend/src/types/turnProgress.ts` (content in Task 6) and the three `api.ts` edits.
- [ ] **Step 4: Green and sabotage.** Run `uv run pytest tests/unit/test_turn_progress.py tests/unit/test_slide_release.py -n 4 -q`. This includes `test_every_backend_event_type_is_in_the_typescript_union` (`test_slide_release.py:231-245`), which must be green. Then `cd frontend && npm run typecheck`. Sabotages, each red:
  - emit after the `with` block;
  - `_persist` inside the `with` block;
  - `>=` → `>` in the phase rule (the alternation test);
  - `>` → `>=` in the stage rule (the no-op-publishes test);
  - remove the `finally` reset from `turn_progress_scope` (the scope test);
  - drop the `'turn_progress'` member from the `api.ts` union (the TS-union pin).

  Then run the **full** `uv run pytest tests/unit -n 4 -q` and diff causes against the baseline.

---

### Task 3: Report from the graph

Models: test=opus impl=sonnet

The insertion points are exact. The tests are compiled-graph interleavings.

**Files:**
- Modify: `src/services/graph/nodes.py`.
- Modify: `src/services/graph/builder.py`: the imports (`:99-107`); in `invoke_graph`, the final `return get_graph().invoke(state, config)` (`:377`); plus a sentence in its docstring.
- Create: `tests/unit/test_turn_progress_graph.py`.
- Modify: `tests/unit/test_graph_builder.py`: `_FakeCompiled` (`:145-155`), and two new tests in `TestInvokeGraphConfig` (`:290`).

**Edits (exact):**
1. `nodes.py` imports, after the `src.services.graph.event_emitter` block (`:90-97`): `from src.services.graph.progress import SlideProgressStage, TurnPhase, report_phase, report_slide, report_slides`.
2. `architect_node`, after `initiated_by = state.get("initiated_by")` (`:1465`): `report_phase(TurnPhase.PLANNING)`, with the comment `# #319: the placeholder's first stage, for the whole architect call`.
3. `architect_node`, immediately before `verdicts = rereview_committed_slides(` (`:1807`): `report_phase(TurnPhase.CHECKING_SLIDES)`.
4. `data_analyst_node`, before `request = state.get("architect_message") or ""` (`:2018`): `report_phase(TurnPhase.GATHERING_DATA)`.
5. `foreman_node`, inside `if batch:`, right after the `_emit(… f"Building {len(batch)} slide(s).", …)` call (`:2151-2155`) and before `return`:
   ```python
           # #319: the same moment as data — every covered position (the total
           # never shrinks across wakes) and this batch marked as building.  The
           # foreman's report is the ONLY one that puts a slide into building: it
           # precedes every Send, so the pipeline needs no start-of-build report.
           report_phase(
               TurnPhase.BUILDING,
               covered=outstanding_positions(state),
               dispatched=batch,
           )
   ```
6. `slide_pipeline_node` (`:3128-3216`). There is **no** report at pipeline start.
   - Immediately before **each** of the three `return {k: v for k, v in acc.items() if k not in _PIPELINE_LOCAL_KEYS}` (`:3134`, `:3168`, `:3216`): `report_slide(position, SlideProgressStage.DONE)`.
   - Right after `drafted = _write_draft_row(record, mutation)` (`:3144`): `report_slide(position, SlideProgressStage.REVIEWING)`.
   - As the first statement inside `if entry is not None:` (`:3171`), **before** `with _fix_slots():`: `report_slide(position, SlideProgressStage.FIXING)`.
7. `placeholder_node`, before `if not placeheld:` (`:3286`): `report_slides(placeheld, SlideProgressStage.DONE)`. This is one snapshot and one write; with nothing placeheld it is a no-op.
8. `deck_reviewer_node`, before `session_id = state["session_id"]` (`:3368`): `report_phase(TurnPhase.REVIEWING_DECK)`.
9. `builder.py`:
   - add `from src.services.graph.progress import turn_progress_scope`;
   - replace the final `return get_graph().invoke(state, config)` (`:377`) with:
     ```python
         # #319: this turn's stage summary, installed for exactly the duration of
         # the invoke.  Set BEFORE invoke for the same context-copy reason as the
         # emitter and the fix slots (every fanned task shares the object) and
         # removed after it, success or failure, so nothing outlives the turn.
         with turn_progress_scope():
             return get_graph().invoke(state, config)
     ```
   - add one docstring sentence to `invoke_graph`.

Do **not** change any node's returns. `_EXPECTED_NODE_WRITES` (`test_graph_nodes.py:3465-3496`) and the scans must stay green without edits. The other `fake_graph` fixture, at `tests/unit/test_graph_nodes.py:4016-4022`, needs no change, because the scope leaves nothing behind.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_turn_progress_graph.py`.
  - **Imports:** `from tests.unit.conftest_graph import graph_env, graph_env_threadsafe, architect_build, builder_out, fixer_out, review_out, finding, make_spec  # noqa: F401`, and `from tests.unit.test_slide_pipeline import _wire, _run, _transient, BARRIER_TIMEOUT_S`.
  - **Harness:**
    - each test calls `set_event_emitter(q)` and runs `_run(env)` (which is `graph.invoke` directly) inside `with turn_progress_scope() as progress:`;
    - each test reads `progress.snapshot()` or drains `q` before the block exits;
    - the autouse fixture clears `turn_progress_var`, the emitter and `set_chat_request_id(None)` at setup and teardown.
  - **"History"** means the deduplicated sequence of one position's stage across the drained `TURN_PROGRESS` snapshots.
  - **Full build turn:**
    - `test_a_build_turn_walks_planning_building_reviewing_deck_in_order`: `_wire(env, (0, 1, 2), flagged=(1,))`, then `_run(env)`.
      - `seq` values rise strictly by 1.
      - The deduplicated phases are exactly `["planning", "building", "reviewing_deck"]`.
      - The final snapshot is phase `reviewing_deck`, `total 3`, `done [0, 1, 2]`, with the other lists empty.
      - Every event's `metadata == {"node": "progress"}`.
    - `test_each_slide_walks_its_real_stages`: histories `0` and `2` are `["building", "reviewing", "done"]`; history `1` is `["building", "reviewing", "fixing", "done"]`.
  - **Concurrent interleavings:**
    - `test_three_slides_build_at_once_and_the_summary_says_so`: the builder handler waits on `Barrier(3, timeout=BARRIER_TIMEOUT_S)`, and the barrier action captures `get_turn_progress().snapshot()`. Assert `building == [0, 1, 2]` in that capture. Do the same with the `build_reviewer` handler → `reviewing == [0, 1, 2]`.
    - `test_a_finished_slide_and_a_building_slide_coexist_truthfully`: positions `(0, 1)`. Slide 1's builder polls `get_turn_progress().snapshot()` (timeout 5 s) until `0 in slides["done"]`, then captures the snapshot. Assert `building == [1]`, `done == [0]`, phase `building`. (Interleaving pattern: `tests/unit/test_slide_pipeline.py:115-140`.)
    - `test_a_slide_waiting_for_a_fix_slot_already_reads_fixing` (pattern: `tests/unit/test_slide_pipeline.py:359-389`):
      - `_wire(env, tuple(range(6)), flagged=tuple(range(6)))`, with a fixer handler that blocks on `release.wait(timeout=BARRIER_TIMEOUT_S)`;
      - run `_run(env)` on a background thread via `contextvars.copy_context().run`, so the thread shares the tracker;
      - in the test thread, wait (5 s) until `len(env.skills.calls_for("fixer")) == 5`, i.e. all `FIX_CONCURRENCY` slots are held and one slide is waiting for a slot;
      - then wait (5 s) until `progress.snapshot()["slides"]["fixing"] == [0, 1, 2, 3, 4, 5]`, and assert it;
      - set `release`, join, and assert `done == [0..5]` with 6 fixer calls;
      - sabotage: move the `FIXING` line inside `with _fix_slots():` → the waiting slide reads `reviewing` → red.
  - **Failure paths:**
    - `test_a_failed_builder_goes_straight_to_done`: the builder raises at 1 → history `1 == ["building", "done"]`; the final `done == [0, 1, 2]`.
    - `test_a_transient_review_failure_keeps_the_draft_and_reaches_done`: `_transient("opus")` for position 1's review (pattern: `test_slide_pipeline.py:450-470`) → history `1 == ["building", "reviewing", "done"]`.
    - `test_a_raising_progress_tracker_never_fails_a_deck`:
      - `monkeypatch.setattr("src.services.graph.progress.TurnProgress.report", <a function raising RuntimeError>)`, inside the scope;
      - `_wire(env, (0, 1, 2), flagged=(1,))`, then `_run(env)`;
      - assert `sorted(r.position for r in env.rows()) == [0, 1, 2]`, every row has a non-empty `verification_record` (it was reviewed), row 1 holds the fixed HTML, and `len(env.skills.calls_for("deck_reviewer")) == 1`;
      - sabotage: drop the `try/except` in `report_slide` (or in `report_phase`) → the node raises → red.
  - **Other turn shapes:**
    - `test_a_discuss_turn_reports_planning_only`: the architect returns `ArchitectOutput(intent="discuss", message="Let's talk.")` → exactly one snapshot, phase `planning`, `total 0`.
    - `test_a_data_request_turn_gathers_between_two_planning_passes`: the architect handler returns `ask_data` (with `data_request={"metric": "weekly active users"}`) on its first call and `architect_build(make_spec((0, 1)))` after. `data_analyst` returns `AnalystOutput(outcome="success", synthesis="WAU is 1.2m.", sources=["genie:wau"])`. The deduplicated phases are `["planning", "gathering_data", "planning", "building", "reviewing_deck"]`.
    - `test_an_edit_turn_counts_only_its_targets`: seed three rows and persist `make_spec((0, 1, 2))`. The architect returns `_edit_out(_revised(make_spec((0, 1, 2)), {1: "three stat cards"}), [1])` (helpers at `tests/unit/test_graph_nodes.py:134, 153`). The first `building` snapshot has `total == 1` and `building == [1]`; the final `done == [1]`.
    - `test_a_deck_level_brief_change_reports_checking_the_slides`: copy the setup from `tests/unit/test_deck_level_spec_change.py:928-935` (`_persist`, `_seed_rows`, `brief_aware_reviewer({2})`, `_run_architect(env, _audience_changed(), emitter=q)`) and run it inside the scope. The phases contain `planning` and then `checking_slides`, in that order.
    - `test_placeheld_stalled_positions_are_done_in_one_snapshot`: copy the state from `test_graph_nodes.py:2858-2870` (`foreman_wakes=[[0, 1], []]` plus `dispatched_at`) and `monkeypatch.setattr(nodes, "_placehold_failed_position", lambda position, **kw: True)`. Then `placeholder_node(state)` → exactly **one** `TURN_PROGRESS` event, with `done == [0, 1]`.
  - **DB row:** `test_the_turns_stage_lands_on_its_chat_request_row`: `rid = get_session_manager().create_chat_request(env.session_id)`, `set_chat_request_id(rid)`, then run a three-slide turn. `get_chat_request(rid)["turn_progress"]` equals the last queued snapshot (phase `reviewing_deck`, `done [0, 1, 2]`), and the raw `progress_seq` equals its `seq`. This is the state that survives the turn.
  - **In `tests/unit/test_graph_builder.py`:**
    - `_FakeCompiled.__init__` gains `self.progress_during_invoke = []`, and `invoke` appends `get_turn_progress()`. Add a `raise_on_invoke` flag that makes `invoke` raise `RuntimeError` after recording.
    - `TestInvokeGraphConfig::test_every_turn_gets_a_fresh_progress_tracker`: two `invoke_graph("sess-42", {})` calls → two non-`None`, distinct trackers, each with `snapshot()["seq"] == 0` at invoke time.
    - `TestInvokeGraphConfig::test_the_tracker_does_not_outlive_the_turn`: after `invoke_graph("sess-42", {})` returns, `get_turn_progress() is None`, although `progress_during_invoke[0]` was not `None`. With `raise_on_invoke`, `pytest.raises(RuntimeError)`, and afterwards `get_turn_progress()` is still `None`. Sabotage: replace the `with` with a bare `turn_progress_var.set(TurnProgress())` and no reset → red.
- [ ] **Step 2: Confirm red.** No events are queued; `progress_during_invoke` holds `None`.
- [ ] **Step 3: Implement** edits 1–9.
- [ ] **Step 4: Green and sabotage.** Run `uv run pytest tests/unit/test_turn_progress_graph.py tests/unit/test_graph_builder.py -n 4 -q`. Sabotages, each red:
  - remove the `REVIEWING` line;
  - remove any one `DONE` line (the matching path's test goes red);
  - move the `FIXING` line inside `with _fix_slots():`;
  - remove the `turn_progress_scope()` from `invoke_graph`;
  - replace the scope with a bare `set` and no reset;
  - remove the `CHECKING_SLIDES` line;
  - drop the `try` in `report_slide`;
  - replace `report_slides(...)` with a `report_slide` loop (the one-snapshot test).
- [ ] **Step 5: Regression.**
  - `uv run pytest tests/unit/test_graph_nodes.py tests/unit/test_slide_pipeline.py tests/unit/test_slide_release.py tests/unit/test_deck_level_spec_change.py tests/unit/test_graph_routers.py tests/unit/test_graph_builder.py -n 4 -q`;
  - plus `uv run pytest tests/integration/test_graph_orchestration.py tests/integration/test_graph_mode_turn.py tests/integration/test_architect_reply_is_persisted.py tests/integration/test_sweeper_describe_only.py -n 4 -q`;
  - plus the **full** `uv run pytest tests/unit -n 4 -q`.

  Diff failure causes against the baseline.

---

### Task 4: Serve it on the poll

Models: test=opus impl=haiku

The route change is about three lines, and the code is given.

**Files:**
- Modify: `src/api/routes/chat.py`: the return dict (`:950-967`) and the docstring's `Returns:` line (`:870-872`).
- Create: `tests/unit/test_poll_turn_progress.py`.
- Modify: `tests/unit/test_slide_release.py:965-975`. The pinned key set gains `"turn_progress"`.

**Edit:** append this to the returned dict, after `"revision_mark": revision_mark,`:

```python
        # #319 — the graph turn's latest stage summary, read off this request's
        # row, so any worker serves the same value.  Null once the request is
        # terminal (a finished turn never shows a stale stage) and null for a
        # monolith turn, which never writes one.
        "turn_progress": (
            chat_request.get("turn_progress")
            if chat_request["status"] not in ("completed", "error")
            else None
        ),
```

- [ ] **Step 1: Write the failing tests.** Copy the `poll_client` and `poll_manager` fixtures from `tests/unit/test_slide_release.py:915-937` into the new file. `SNAP` is a valid snapshot dict.
  - `test_a_running_request_serves_its_latest_snapshot`: status `"running"` with `turn_progress SNAP` → `body["turn_progress"] == SNAP`.
  - `test_a_pending_request_serves_whatever_it_holds`: pending with `None`, then pending with `SNAP`.
  - `test_a_finished_request_never_serves_a_stale_snapshot`: parametrised over `completed` and `error`, with the row still holding `SNAP` → `None`.
  - `test_a_monolith_request_serves_no_stage`: the row has `turn_progress None` → `None`.
  - `test_stage_progress_never_enters_the_events_list`: the messages yield one assistant event. With `SNAP` present, `events` holds exactly that message-derived event, and no element has `type == "turn_progress"`.
  - The creator-only gate needs no new test. `tests/unit/test_authz_chat_poll.py:28-40` already proves that the gate runs before `get_chat_request`, which is the only source of `turn_progress` (D15).
- [ ] **Step 2: Confirm red.** Expect `KeyError 'turn_progress'`, plus the updated key-set pin.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Green and sabotage.** Run `uv run pytest tests/unit/test_poll_turn_progress.py tests/unit/test_authz_chat_poll.py tests/unit/test_slide_release.py -n 4 -q`. Sabotage: drop the terminal-status condition → the finished-request test goes red.

---

### Task 5: Prove it across workers, under concurrency, through the real async transport, and through the real SSE generator

Models: test=opus impl=haiku

These tests are proofs over Tasks 1–4, so they are expected to pass on their first run. The test author must show red through the listed sabotages (skill §1) instead of a red-first run. The only "implementation" is the CI line. If a proof fails, a defect has escaped Tasks 1–4: stop and escalate to Opus.

**Files:**
- Create: `tests/unit/test_turn_progress_cross_worker.py`.
- Modify: `tests/integration/test_layer4_multi_worker.py`: a new class, plus importing `_await_lock_waiters` from `tests.integration.postgres_concurrency_helpers` (`:202`).
- Create: `tests/integration/test_turn_progress_polling.py`.
- Modify: `tests/integration/test_graph_mode_turn.py`: one new test in `TestTheCompleteEvent` (`:1059`).
- Modify: `.github/workflows/test.yml`. Add `tests/integration/test_turn_progress_polling.py \` to the `integration-graph` run block, right after `tests/integration/test_architect_reply_is_persisted.py \` (`:456`); otherwise `tests/unit/test_ci_collects_integration_tests.py` fails. `test_graph_mode_turn.py` is already in that block.

- [ ] **Step 1: Cross-process read** (always runs, on SQLite) in `test_turn_progress_cross_worker.py`. Use `graph_env_threadsafe`, which gives a file-backed DB at `env.engine.url.database`.
  - **The child process.** Model the script on `tests/integration/test_layer4_multi_worker.py:588-652`:
    - set `DATABASE_URL=sqlite:///<path>`, `ENVIRONMENT=test`, and empty `DATABRICKS_HOST`/`DATABRICKS_TOKEN`;
    - reset `src.core.database._engine`/`_session_local` and `src.api.services.session_manager._session_manager`;
    - print `{"pid", "turn_progress"}` from `SessionManager().get_chat_request(rid)`;
    - the parent parses the **last** stdout line.
  - `test_a_poll_on_another_worker_process_sees_the_running_turns_stage`. **Two child processes:**
    - In the parent: `create_chat_request`, `set_chat_request_id(rid)`, then `with turn_progress_scope():`.
    - Child 1, before any report, sees `None`.
    - The parent then runs `report_phase(PLANNING)`, `report_phase(BUILDING, covered=[0, 1, 2], dispatched=[0, 1, 2])` and `report_slide(0, REVIEWING)`. It then attempts a regression, `record_chat_request_progress(rid, 2, older)`, and asserts it returned False.
    - Child 2 sees `seq 3`, phase `building`, `reviewing == [0]`.
    - Assert that both child pids differ from the parent's.
    - Sabotage: make `get_chat_request` read from a module-level dict filled by `record_chat_request_progress` → child 2 sees `None` → red.
- [ ] **Step 2: PostgreSQL writers** in `test_layer4_multi_worker.py`. Add `class TestTurnProgressWritersNeverRegress` on `postgres_engine`, using `_assert_postgres`, `_make_factory`, `_seed_owner` and `_patched_db` (`:129-180`). Its helper creates the request through `SessionManager().create_chat_request` under `_patched_db`.
  - `test_concurrent_writers_leave_the_highest_seq`: 12 threads behind a `Barrier`, with `seq` 1–12 shuffled by `random.Random(319)`. Each calls `record_chat_request_progress(rid, seq, {"seq": seq})`. The final served snapshot is `{"seq": 12}`, the raw `progress_seq` is 12, and the seq-12 writer returned True.
  - `test_an_older_writer_queued_behind_a_newer_one_loses`:
    - a raw connection runs `BEGIN` and then `UPDATE chat_requests SET progress_seq = 5, progress_json = '{"seq": 5}' WHERE request_id = :r`, without committing;
    - a thread calls `record_chat_request_progress(rid, 4, …)`;
    - assert `_await_lock_waiters(postgres_engine, 1) >= 1`, with the message "the older writer never queued; the race was not exercised";
    - **commit the holder immediately**, before the 2 s `lock_timeout` can fire (do not sleep); then join the thread;
    - it returned False, and the row is `seq 5`.
  - `test_a_newer_writer_queued_behind_an_older_one_wins`: the mirror case. The holder writes `seq 4` uncommitted and the writer sends `seq 6`; commit immediately; the writer returns True and the row is 6.
  - `test_a_progress_write_gives_up_on_a_held_row_lock_within_the_timeout`:
    - the holder writes `seq 5` uncommitted and is **kept open**;
    - a thread calls `record_chat_request_progress(rid, 6, …)` and records its outcome and elapsed time;
    - assert `thread.join(timeout=5)` returns with the thread finished, and that it raised `sqlalchemy.exc.OperationalError` whose message mentions `lock timeout`, with an elapsed time of roughly 1.5–3.5 s;
    - then commit the holder: the row is `seq 5`;
    - on the production path `_persist` swallows this error and logs it (`test_a_failing_persist_is_logged_and_never_raises`, Task 2);
    - sabotage: remove the `SET LOCAL lock_timeout` line → the writer is still blocked at 5 s → red. Commit the holder in a `finally` so the sabotaged run cleans up.
  - Controller sabotage: drop the predicate → the older-writer interleaving stores 4 → red.
- [ ] **Step 3: The real async transport, polled mid-turn**, in `tests/integration/test_turn_progress_polling.py`.
  - **Fixture reuse:** `from tests.integration.test_architect_reply_is_persisted import async_turn_env  # noqa: F401`. The fixture is at `:190`, `_AsyncTurnEnv.poll` at `:167` and `architect_builds` at `:108`.
  - **Helper `_spy_on_turn(env, monkeypatch)`:**
    - take `inner = src.services.graph.nodes.get_agent_runtime()`, which is the fixture's runtime;
    - monkeypatch `src.services.graph.nodes.get_agent_runtime` to a runtime with `run(name, graph_release_id, payload, assembly_context)`;
    - for `name in {"architect", "build_reviewer", "fixer", "deck_reviewer"}`, that `run` first calls `env.poll(get_chat_request_id())` and records `{name, position, status, turn_progress, events}` under a lock, then delegates to `inner.run`.
  - `test_a_polling_client_sees_each_stage_while_the_turn_runs`: `env.architect_builds("Here is the plan for three slides.")`, `env.recorder.configure(slide_count=3, objective_findings_at={1})`, then `env.run()`.
    - During the architect call: `status == "running"`, phase `planning`.
    - During each `build_reviewer(p)`: phase `building`, `p in reviewing`, `total == 3`.
    - During `fixer(1)`: `1 in fixing`.
    - During `deck_reviewer`: phase `reviewing_deck`, `done == [0, 1, 2]`.
    - Causality: the architect's `seq` is below every reviewer's `seq`, which is below the deck reviewer's `seq`.
  - `test_a_finished_turn_serves_no_stage_but_kept_the_last_one`: after `run`, `env.poll(rid)` is `completed` with `turn_progress None`, while `get_session_manager().get_chat_request(rid)["turn_progress"]["phase"] == "reviewing_deck"`. The null is a projection, not a lost write.
  - `test_stage_progress_never_enters_the_transcript`: across every recorded poll and the final one, no `events` element has `type "turn_progress"`; every persisted message's `message_type` is in `{"user_query", "llm_response", "info"}`; and no message content contains `'"seq"'`.
  - `test_a_discuss_turn_only_ever_shows_planning`: with the default discuss knob, the architect observation is phase `planning`, and the row's final phase is `planning`.
- [ ] **Step 4: The real SSE generator.** Add `TestTheCompleteEvent::test_stage_progress_streams_before_complete_in_seq_order` to `tests/integration/test_graph_mode_turn.py`, next to `test_complete_is_the_last_event_and_carries_the_deck` (`:1067-1090`). `graph_chat_env` runs the **real** `invoke_graph` and the real `_send_message_streaming_graph`; only `get_graph` is redirected (`:12-13, 351-381`).
  - `graph_chat_env.recorder.configure(slide_count=3)`, then `events = graph_chat_env.run(is_first_message=False)`.
  - Assert at least one `StreamEventType.TURN_PROGRESS` event.
  - Assert every `TURN_PROGRESS` index is below the `COMPLETE` index.
  - Assert their `turn_progress["seq"]` values are exactly `1..n`.
  - Assert the last one is phase `reviewing_deck` with `done == [0, 1, 2]`.
  - Sabotage: remove `turn_progress_scope()` from `invoke_graph` → no `TURN_PROGRESS` events → red.
- [ ] **Step 5: CI wiring** (the yaml line above). Then run `uv run pytest tests/unit/test_ci_collects_integration_tests.py tests/unit/test_turn_progress_cross_worker.py tests/integration/test_turn_progress_polling.py tests/integration/test_graph_mode_turn.py -n 4 -q`. Where PostgreSQL is available, also run `TELLR_TEST_POSTGRES_URL=<url> uv run pytest tests/integration/test_layer4_multi_worker.py -k TurnProgress -q`; otherwise it self-skips, and CI's `layer4-integration` job runs it.

---

### Task 6: Frontend contract, label and validation

Models: test=opus impl=sonnet

**Files:**
- `frontend/src/types/turnProgress.ts` was **created in Task 2** with the content below. Verify it; do not re-create it.
- Create: `frontend/src/utils/turnProgress.ts`.
- Create: `frontend/src/utils/turnProgress.test.ts`.
- Create: `frontend/src/utils/turnProgress.conformance.test.ts`.

**Interfaces (produced):**

```ts
// frontend/src/types/turnProgress.ts  (created in Task 2)
/**
 * The graph turn's stage summary (#319), mirrored from src/services/graph/progress.py.
 * Positions are 0-based; the UI shows position + 1.  Pinned against the Python
 * enums by src/utils/turnProgress.conformance.test.ts.
 * (Named SlideProgressStage, not SlideStage: SlideViewer/SlideStage.tsx is a component.)
 */
export const TURN_PHASES = ['planning', 'gathering_data', 'checking_slides', 'building', 'reviewing_deck'] as const;
export type TurnPhase = (typeof TURN_PHASES)[number];

export const SLIDE_PROGRESS_STAGES = ['building', 'reviewing', 'fixing', 'done'] as const;
export type SlideProgressStage = (typeof SLIDE_PROGRESS_STAGES)[number];

export type TurnProgressSlides = { total: number } & Record<SlideProgressStage, number[]>;

export interface TurnProgress {
  seq: number;
  phase: TurnPhase;
  slides: TurnProgressSlides;
}
```

```ts
// frontend/src/utils/turnProgress.ts
import { SLIDE_PROGRESS_STAGES, TURN_PHASES } from '../types/turnProgress';
import type { TurnPhase, TurnProgress } from '../types/turnProgress';

const ELLIPSIS = '…';

/** Unchanged legacy text: shown before the first stage arrives and for the legacy engine. */
export const DEFAULT_TURN_LABEL = 'Generating slides...';

const PHASE_LABELS: Record<Exclude<TurnPhase, 'building'>, string> = {
  planning: `Planning the deck${ELLIPSIS}`,
  gathering_data: `Gathering the data${ELLIPSIS}`,
  checking_slides: `Checking the slides against the new brief${ELLIPSIS}`,
  reviewing_deck: `Reviewing the narrative${ELLIPSIS}`,
};

const isPositions = (v: unknown): v is number[] =>
  Array.isArray(v) && v.every((n) => Number.isInteger(n) && n >= 0);

/** A well-formed snapshot, or null (malformed or absent payloads are ignored, never rendered). */
export function parseTurnProgress(value: unknown): TurnProgress | null {
  if (!value || typeof value !== 'object') return null;
  const v = value as Record<string, unknown>;
  if (!Number.isInteger(v.seq) || (v.seq as number) < 1) return null;
  if (typeof v.phase !== 'string' || !(TURN_PHASES as readonly string[]).includes(v.phase)) return null;
  const s = v.slides as Record<string, unknown> | null | undefined;
  if (!s || typeof s !== 'object' || !Number.isInteger(s.total) || (s.total as number) < 0) return null;
  if (!SLIDE_PROGRESS_STAGES.every((stage) => isPositions(s[stage]))) return null;
  return value as TurnProgress;
}

/** The snapshot to hold: `incoming` only when it is newer than `held` (seq strictly greater). */
export function newerTurnProgress(held: TurnProgress | null, incoming: TurnProgress | null): TurnProgress | null {
  if (!incoming) return held;
  if (!held || incoming.seq > held.seq) return incoming;
  return held;
}

function clause(verb: string, positions: number[]): string {
  return positions.length === 1 ? `${verb} slide ${positions[0] + 1}` : `${verb} ${positions.length} slides`;
}

/** The placeholder text for a snapshot (see the plan's D7 table). */
export function describeTurnProgress(progress: TurnProgress | null): string {
  if (!progress) return DEFAULT_TURN_LABEL;
  if (progress.phase !== 'building') return PHASE_LABELS[progress.phase];
  const { total, building, reviewing, fixing, done } = progress.slides;
  const clauses = [
    building.length ? clause('building', building) : null,
    reviewing.length ? clause('reviewing', reviewing) : null,
    fixing.length ? clause('fixing', fixing) : null,
  ].filter((c): c is string => c !== null);
  if (clauses.length === 0 && total > 0 && done.length === total) return `Finishing the slides${ELLIPSIS}`;
  const head = clauses.length ? clauses.join(', ') : 'building the slides';
  const sentence = `${head.charAt(0).toUpperCase()}${head.slice(1)}${ELLIPSIS}`;
  return total > 1 && done.length > 0 ? `${sentence} (${done.length} of ${total} done)` : sentence;
}
```

- [ ] **Step 1: Write the failing tests.**
  - `turnProgress.test.ts`:
    - `the five example labels from #319 are produced verbatim`:
      - `planning` → `Planning the deck…`;
      - building, total 10, building `[0..9]` → `Building 10 slides…`;
      - building, total 1, reviewing `[2]` → `Reviewing slide 3…`;
      - building, total 2, fixing `[0, 1]` → `Fixing 2 slides…`;
      - `reviewing_deck` → `Reviewing the narrative…`.
    - The rest of the D7 table, one `it` per row:
      - gathering, and checking;
      - a singular for each verb;
      - the mixed three-clause sentence `Building 3 slides, reviewing 2 slides, fixing slide 6… (4 of 10 done)`;
      - the suffix only when `total > 1 && done > 0`;
      - nothing active: `Building the slides… (6 of 10 done)`;
      - all done: `Finishing the slides…`.
    - `null → 'Generating slides...'` (byte-exact, three ASCII dots).
    - No label contains an emoji or an internal node name (`architect`, `foreman`, `reviewer`, `pipeline`).
    - `newerTurnProgress`: a higher seq replaces; equal and lower seqs are kept; a null incoming keeps held; a null held takes incoming.
    - `parseTurnProgress` accepts a valid snapshot and rejects:
      - `undefined`, `null` and a string;
      - a `seq` that is missing, non-integer or zero;
      - an unknown or `null` phase;
      - missing `slides`, or a non-integer `total`;
      - any stage list that is missing or contains `-1` or `1.5`;
      - the legacy mock shape `{message: 'Generating slides...'}`.
  - `turnProgress.conformance.test.ts`:
    - `import progressPy from '../../../src/services/graph/progress.py?raw'` (precedent: `frontend/src/services/__tests__/deckSpecConformance.test.ts:27`);
    - extract each class body with `/class TurnPhase\(str, Enum\):\n((?:    \w+ = "[a-z_]+"\n)+)/`, and likewise for `SlideProgressStage`;
    - collect the values and assert they deep-equal `TURN_PHASES` and `SLIDE_PROGRESS_STAGES`, in order;
    - add an entry assertion that each regex matched.
- [ ] **Step 2: Confirm red.** `cd frontend && npx vitest run src/utils/turnProgress.test.ts src/utils/turnProgress.conformance.test.ts`.
- [ ] **Step 3: Implement** `utils/turnProgress.ts`.
- [ ] **Step 4: Green, typecheck, sabotage.** Run `npm run typecheck`. Sabotages, each red:
  - drop the `+ 1` → the verbatim test;
  - rename a Python enum value → the conformance test;
  - change `>` to `>=` in `newerTurnProgress`.

---

### Task 7: The frontend polling transport carries `turn_progress`

Models: test=opus impl=sonnet

This task depends on Task 2, which already added the `'turn_progress'` union member, the `StreamEvent.turn_progress` field and the `TurnProgress` import to `api.ts`.

**Files:**
- Modify: `frontend/src/services/api.ts`.
- Create: `frontend/src/services/turnProgressTransport.test.ts`.

**Edits:**
1. `PollResponse` (`:206-230`) gains `/** #319: the running turn's latest stage summary; null when finished or legacy. */ turn_progress?: TurnProgress | null;`.
2. `startPolling`:
   - declare `let lastProgressSeq = 0;` after `let revisionMark` (`:1095`);
   - insert the block below after the `revision_mark` block (`:1156-1158`) and before `lastMessageId = response.last_message_id;` (`:1160`). The guard is kept on purpose: without it ChatPanel would be re-sent an identical event every 3 s.
   ```ts
            // #319: the graph's stage summary.  Re-sent on every poll while the turn
            // runs; forward it only when it is newer than the last one forwarded.
            const progress = response.turn_progress;
            if (progress && typeof progress.seq === 'number' && progress.seq > lastProgressSeq) {
              lastProgressSeq = progress.seq;
              onEvent({ type: 'turn_progress', turn_progress: progress });
            }
   ```

`streamChat` needs no change, because it forwards every parsed `data:` line.

- [ ] **Step 1: Write the failing tests.** Follow the pattern of `frontend/src/services/slideRevisions.test.ts`: `vi.useFakeTimers()`, `vi.stubGlobal('fetch', …)`, and `advanceTimersByTimeAsync(3001)` per poll.
  - `startPolling forwards a stage only when its seq increases`: the polls return `seq 2`, `seq 2`, `seq 5`, then `completed` with `turn_progress: null`. The forwarded `turn_progress` seqs are `[2, 5]`, and the `complete` event comes after them.
  - `an older seq in a later poll is not forwarded`: `5` then `4` → `[5]`.
  - `a poll response with no turn_progress key (legacy engine) forwards no stage`.
  - `streamChat forwards a turn_progress data line unchanged`. This pins the SSE client half of the contract Task 2 typed.
    - Stub `fetch` with `{ ok: true, body: { getReader: () => reader } }`.
    - `reader.read` yields `new TextEncoder().encode('event: turn_progress\ndata: ' + JSON.stringify(evt) + '\n\n')`, then `{ done: true }`.
    - Assert `onEvent` receives an event deep-equal to `evt`.
- [ ] **Step 2: Confirm red.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Green and typecheck.** Run `cd frontend && npx vitest run src/services/turnProgressTransport.test.ts src/services/slideRevisions.test.ts src/components/ChatPanel/slideReadyEvent.test.ts && npm run typecheck`. Sabotage: drop `> lastProgressSeq` → the duplicate is forwarded → red.

---

### Task 8: The placeholder renders the stage

Models: test=opus impl=sonnet

**Files:**
- Modify: `frontend/src/components/ChatPanel/MessageList.tsx`.
- Modify: `frontend/src/components/ChatPanel/ChatPanel.tsx`.
- Create: `frontend/src/components/ChatPanel/ChatPanel.turnProgress.test.tsx`.
- Create: `frontend/src/components/ChatPanel/MessageList.turnProgress.test.tsx`.

**Edits:**
- **`MessageList`:**
  - `MessageListProps` gains `/** #319: the stage label; defaults to the generic text. */ progressLabel?: string;`, destructured as `progressLabel = DEFAULT_TURN_LABEL` (imported from `../../utils/turnProgress`);
  - the loading `<div>` (`:26-31`) gains `data-testid="chat-turn-progress"`, `aria-live="polite"` and `aria-atomic="true"`;
  - its `<span>` renders `{progressLabel}`;
  - keep the existing classes and the spinner.
- **`ChatPanel`:**
  - Imports: `describeTurnProgress, newerTurnProgress, parseTurnProgress`, and `type TurnProgress`.
  - State, next to `loadingMessage` (`:51`): `const [turnProgress, setTurnProgress] = useState<TurnProgress | null>(null);`.
  - In `handleSendMessage`, beside `setIsLoading(true)` (`:181`): `setTurnProgress(null);`. This is the **only** reset. The placeholder is hidden whenever `isLoading` is false, and resetting at send is what lets the next turn's `seq 1` win (D14).
  - A new case in `handleStreamEvent`, next to `'slide_ready'` (`:329`):
    ```tsx
          // #319 — the graph's stage summary.  Never a chat message: it only feeds
          // the placeholder.  Older, repeated and malformed snapshots are ignored,
          // so the label never steps backwards.
          case 'turn_progress': {
            const incoming = parseTurnProgress(event.turn_progress);
            if (incoming) setTurnProgress(prev => newerTurnProgress(prev, incoming));
            break;
          }
    ```
  - Render: `<MessageList … progressLabel={describeTurnProgress(turnProgress)} />` (`:400`).
  - `LoadingIndicator` and the rotating interval stay untouched (D16).

- [ ] **Step 1: Write the failing tests.**
  - `MessageList.turnProgress.test.tsx`:
    - with loading on and no prop, the default text is `Generating slides...`;
    - a given `progressLabel` is rendered;
    - nothing renders when `isLoading` is false;
    - the wrapper has `aria-live="polite"` and `aria-atomic="true"`, and no `role="status"`.
  - `ChatPanel.turnProgress.test.tsx`. Mount the real `ChatPanel` and the real `MessageList`. **Harness rules (from the plan review):**
    - **Hoist stable mock functions to module scope** and return the *same* instance on every render: `const setIsGenerating = vi.fn(); const refreshConfig = vi.fn();`, used as `useGeneration: () => ({ setIsGenerating })` and `useAgentConfig: () => ({ agentConfig: null, refreshConfig, configOwnerSessionId: null, isPreSession: false })`.
      - Do **not** copy `ChatPanel.tourRefresh.test.tsx:33-35` verbatim. Its `setIsGenerating: vi.fn()` creates a new function on every render.
      - That re-runs the cleanup of the effects keyed on `[sessionId, setIsGenerating]` (`ChatPanel.tsx:80-94`) and `[setIsGenerating]` (`:373-385`). Those cleanups `setIsLoading(false)` and cancel the stream, so the placeholder vanishes immediately after send, for a harness reason.
      - **Do not "fix" `ChatPanel` for this.**
    - **Use the real `MessageList`.** Do not copy the `MessageList` mock at `ChatPanel.tourRefresh.test.tsx:36-40`. The `useSession` mock can follow `:15-24`, with a stable return.
    - **Mock `api`** with:
      - `getSession` resolving `{messages: []}`;
      - a `sendChatMessage` that captures `onEvent`/`onError` and returns a no-op cancel;
      - `getSlides`, `getCurrentSessionId` and `setCurrentSessionId`.
    - **Mock `ChatInput`** as a button that calls `onSend('build me a deck')`.
    - **Helper:** `tp(seq, phase, slides)`.

    Tests:
    - `shows the generic text until the first stage arrives`.
    - `shows each stage as it arrives`: planning, then `Building 3 slides…`.
    - `ignores an older or repeated snapshot`: seq 5 shows `Reviewing slide 3… (2 of 3 done)`; then seq 4, then seq 5 with a different phase → unchanged.
    - `ignores a malformed turn_progress event`: `{type: 'turn_progress'}`, and one with a string `seq`.
    - `the label is not timer-driven`: `vi.useFakeTimers()`, planning, `advanceTimersByTime(60_000)` → still `Planning the deck…`.
    - `a stage never becomes a chat message`: after several events, `getAllByText(/Planning the deck/)` has length 1, and `chat-turn-progress` contains it.
    - `hides on complete and on error`.
    - `the next turn starts fresh even though its seq restarts at 1`: seq 9 `reviewing_deck` → `complete` → send again → `Generating slides...` → `tp(1, 'planning')` → `Planning the deck…`. Sabotage: remove the send-time reset → red.
- [ ] **Step 2: Confirm red.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Green, regression, typecheck.** Run `cd frontend && npx vitest run src/components/ChatPanel && npm run test:unit && npm run typecheck`.

---

### Task 9: SSE end to end in a browser, and the CI matrix

Models: test=opus impl=haiku

**Files:**
- Create: `frontend/tests/e2e/turn-progress.spec.ts`.
- Modify: `.github/workflows/test.yml`. Add `- turn-progress` to `e2e-tests.strategy.matrix.test`, after `- template-viewer` (`:738`); `tests/unit/test_e2e_matrix_covers_specs.py` fails without it.

- [ ] **Step 1: Write the spec.**
  - **Imports:** `test`/`expect` from `../fixtures/base-test`, `setupMocks` from `../helpers/setup-mocks`, and `goToGenerator` from `../helpers/new-ui`.
  - **Setup:** copy `setupForGeneration` verbatim from `frontend/tests/e2e/incremental-slide-delivery.spec.ts:100-142`.
  - **Mock:** serve `/api/chat/stream` with `route.fulfill({ contentType: 'text/event-stream', body })`, where `body` is a series of `data: <json>\n\n` lines.
  - **Helper:** `tp(seq, phase, slides)` builds `{type: 'turn_progress', metadata: {node: 'progress'}, turn_progress: {seq, phase, slides: {total: 0, building: [], reviewing: [], fixing: [], done: [], ...slides}}}`.

  Tests:
  - `the placeholder shows the newest stage the stream delivered, never a stale one`:
    - the body is `tp(1, planning)`, `tp(2, building {total 3, building [0, 1, 2]})`, `tp(4, building {total 3, reviewing [2], done [0, 1]})`, `tp(3, building {total 3, reviewing [1, 2], done [0]})`, with **no** `complete`, so the turn stays open;
    - after send, `getByTestId('chat-turn-progress')` has the text `Reviewing slide 3… (2 of 3 done)`;
    - `getByText('Reviewing slide 3', { exact: false })` has count 1, so the label is not in the transcript.
  - `the placeholder disappears when the turn completes`: `tp(1, planning)`, `tp(2, reviewing_deck)`, `{type: 'complete'}` → `chat-turn-progress` has count 0.
  - `a stream with no stage events (the legacy engine) keeps the generic text`: the body is `{type: 'assistant', content: 'Working on it'}` with no `complete` → `chat-turn-progress` has the text `Generating slides...`.
- [ ] **Step 2: Run.** `cd frontend && npx playwright test tests/e2e/turn-progress.spec.ts --project=chromium --workers=1`. On a branch without Task 8, the first test goes red. Sabotage: delete `case 'turn_progress':` → red.
- [ ] **Step 3: Matrix line.** Add it, then run `uv run pytest tests/unit/test_e2e_matrix_covers_specs.py -q`.

---

### Task 10: Docs

Models: test=sonnet impl=sonnet

There are no tests. The reviewer checks every sentence against the merged code.

**Files and content:**
- `docs/technical/real-time-streaming.md`:
  - The SSE Event Types table (`:73-85`) gains `turn_progress` (the graph engine's stage summary; payload `turn_progress {seq, phase, slides}`) and the missing `slide_ready` row, which is already in `streaming.py:23`.
  - The `StreamEvent` block gains `turn_progress`.
  - The Poll Response example (`:297-307`) gains `"turn_progress": {…} | null`, noting that it is null once the request is completed or errored, and for the legacy engine.
  - The `chat_requests` table (`:512-523`) gains `progress_json` and `progress_seq`.
  - A new subsection, "Turn progress (graph engine, #319)", covers:
    - the snapshot shape;
    - the D3 rules, in brief, including the 2 s PostgreSQL `lock_timeout`;
    - the two sinks;
    - that the tracker is scoped to one invoke;
    - why the poll is cross-worker coherent;
    - where the label is computed (`frontend/src/utils/turnProgress.ts`);
    - the legacy-engine behaviour;
    - the known gap that a crashed request keeps its last stage (D13).
- `docs/technical/multi-user-concurrency.md`, §5 table (`:138-145`): add the two columns, plus one sentence on the conditional UPDATE and on any worker serving the same stage.
- `docs/technical/database-configuration.md`:
  - add the two fields to the `ChatRequest` block (`:485-494`);
  - add item 11 to the `_run_migrations` step list, after item 10 (`:739`): "Adds `progress_json`, `progress_seq` to `chat_requests` (`_migrate_chat_request_progress()`, #319)".
- `docs/technical/frontend-overview.md`: the `MessageList` row (`:324`) mentions the stage placeholder; add a `src/utils/turnProgress.ts` row next to `loadingMessages.ts` (`:337`).
- `docs/user-guide/01-generating-slides.md:56`: replace the sentence with "While your request runs, the chat shows what Tellr is doing — planning the deck, building and reviewing slides, fixing layout problems and reviewing the narrative — and slides appear in the right panel as they finish."
- [ ] **Verify there are no stale claims:** `grep -rn "turn_progress\|progress_json" docs/` must match the code, and `uv run pytest tests/unit/test_e2e_matrix_covers_specs.py tests/unit/test_ci_collects_integration_tests.py -q` must pass.

---

## CI wiring (summary)

- `tests/integration/test_turn_progress_polling.py` goes in the `integration-graph` run block (Task 5). It is guarded by `tests/unit/test_ci_collects_integration_tests.py`. The new test in `tests/integration/test_graph_mode_turn.py` rides on that file's existing entry in the same block.
- `turn-progress` goes in the `e2e-tests` matrix (Task 9). It is guarded by `tests/unit/test_e2e_matrix_covers_specs.py`.
- New `tests/unit/*.py` files are collected wholesale by `unit-tests`. The PostgreSQL class in `test_chat_request_progress.py` runs there through `TELLR_TEST_POSTGRES_URL`.
- The new layer4 class is in a file that `layer4-integration` already names (`test.yml:1119`).
- New vitest files are picked up by `npm run test:unit` (`include: ['src/**/*.test.{ts,tsx}']`).

## Post-merge manual check (owner; not a task)

Polling is the production transport and runs only on Databricks Apps. After merge:
1. Deploy a dev build to **devloop** with the `deploy-tellr-dev` skill.
2. Run a build of 10+ slides with one flagged slide, and watch the placeholder step through planning → building → reviewing/fixing → narrative.
3. Run an edit, and a chat-only question.
4. Check the startup logs: `Migration: adding progress_json to chat_requests` should appear once, and nothing on the next boot.

## Out of scope

- Sibling issues:
  - #321 failure-notice wording (`_surface_notice`, `_transient_failure_notice`, `_placehold_failed_position` text);
  - #316 plain-language findings;
  - #323 clear chat;
  - #318 Spec Markdown export;
  - #313 architect intent evals.
- **The slide-numbering inconsistency, handed to #321 and not changed here.** The new placeholder numbers slides from 1 (`position + 1`, D7), but three persisted, user-visible chat strings number them from 0. On polling, the same slide can be called "slide 3" by the placeholder and "Slide 2" by a notice in the same turn. The three strings are:
  1. `_transient_failure_notice`: `"Slide {position}: the model was briefly unavailable while it was being …"` (`nodes.py:3000-3006`, pinned at `tests/unit/test_slide_pipeline.py:468`);
  2. `_placehold_failed_position`'s notice: `"Slide {position} could not be generated and has been left as a placeholder …"` (`nodes.py:1292-1295`). Its emit-only `ERROR` twin, `"Slide {position} could not be generated."` (`nodes.py:1265`), is also 0-based;
  3. the deck-level re-review message: `"Rebuilding {len(rebuild)}: {rebuild}."` (`nodes.py:1873`).
- The rotating, timer-driven `LoadingIndicator` jokes (D16).
- The pre-existing SSE behaviour where a placeheld slide's `ERROR` event ends loading mid-turn (D13).
- A crashed or unrecovered request keeping its last stage on screen. This is the pre-existing stuck-request hang (D13); there is no `progress_updated_at` staleness guard.
- Resuming the placeholder after a page reload mid-turn. No resume-polling exists today: `startPolling` holds `request_id` only in closure state (`api.ts:1074-1210`), and `ChatPanel` has no resume path.
- Changing or persisting the emit-only build-mechanics chat lines (`Building N slide(s).`, `Slide N reviewed: …`, `Slide N fix reviewed: …`), including their 0-based numbering.
- The MCP status endpoint's `"progress": None` (`src/api/mcp_server.py:778`); MCP runs the monolith.
- Showing queued (not yet dispatched) slides, and per-slide progress inside `rereview_committed_slides`.
- A Playwright polling project with a second `webServer` (D21).
- `scripts/migrate_polling_support.sql`, the legacy manual script; the startup migration is the mechanism.
- Any prompt, output-schema, `DeckSpec` or Agent Definition change.

## Known gaps (accepted, documented)

1. **A crashed or unrecovered request keeps its last stage** (D13). Before this change, the stuck spinner said "Generating slides...". Now it names specific work that is no longer happening. Fixing it belongs with the stuck-request recovery, not here.
2. **Reload mid-turn shows no placeholder** (Out of scope). This was true before the change too.
3. **The live region is mounted conditionally** (D22). The first stage may go unannounced by some screen readers.
4. **Pool checkout is not separately bounded** (D3). `lock_timeout` bounds only the row-lock wait. A pool checkout is bounded by SQLAlchemy's default 30 s `pool_timeout`, which is shared with every other writer (pool 80 + 20).

## Risks / things the reviewer should check

1. **Lakebase ALTER ownership.** `ALTER TABLE chat_requests` needs ownership of the table, exactly like the existing `export_jobs.status_message` ALTER (`database.py:525-542`). Watch the first devloop boot. Never use `devtest` (CLAUDE.md).
2. **Three exact-set pins must be updated, not loosened:**
   - the `StreamEventType` set (`tests/unit/test_slide_release.py:144-158`);
   - the TS union against the backend enum (`test_every_backend_event_type_is_in_the_typescript_union`, `:231-245`; its two halves both land in Task 2);
   - the poll response key set (`:965-975`).
3. **AST scans over `nodes.py`** (`tests/unit/test_graph_nodes.py:3363-3600`). No `*_node` helper, no `return helper(...)`, and `_EXPECTED_NODE_WRITES` unchanged. The reports are statement-level calls only.
4. **Lock discipline** (Review Focus 1). A reviewer should reproduce both deterministic sabotages, not trust a green stress test.
5. **Context propagation and lifetime.** `turn_progress_scope()` must wrap `get_graph().invoke` in `invoke_graph`, and must never be entered inside a node, where a `set` would silently fork the tracker per task. The `finally` reset is what stops a leak into later tests or callers (Review Focus 4). Re-run the **full** unit suite after Tasks 2 and 3: a leak is invisible in single-file runs.
6. **The `lock_timeout` timing tests on a slow CI runner.** The queued-writer interleavings must commit the holder as soon as `_await_lock_waiters` returns (well under 2 s). The give-up test asserts a 1.5–3.5 s window. If CI flakes, widen the *window*; do not raise the production timeout to fit the test.
7. **No snapshot before the first report.** The tracker is created as `invoke_graph` begins the invoke, and the architect reports first. So `Generating slides...` shows only for the pin and root loads, which take milliseconds.
8. **Write volume** (≤ 3N + 5 per turn) shares the connection pool with slide writes. Each write is one short indexed UPDATE, with a row-lock wait of at most 2 s. Report it if Lakebase latency shows contention on the request row.
9. **Merge conflicts.** With #323 in `ChatPanel.tsx`, expect small ones (additive state, one case, one prop). With #321 in `nodes.py`, only adjacent lines.
10. **The copy is new user-visible text.** Product-owner sign-off is needed on D7 and on D10 ("Planning the deck…" on chat-only turns; the "Working on your request…" alternative was considered and rejected) at review.
11. **The integration test polls from inside graph threads** (`asyncio.run(poll_chat(...))` on a thread with no running loop). If the fixture's SQLite file locks under this read load, raise `timeout` rather than weakening the assertions.
