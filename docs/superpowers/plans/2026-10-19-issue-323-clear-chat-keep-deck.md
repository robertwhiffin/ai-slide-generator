# Clear the chat on an existing deck, keep the deck (#323): Implementation Plan

> **For agentic workers:** load `executing-plans-tellr` (repo `CLAUDE.md`) together with
> `superpowers:subagent-driven-development`. Steps use checkbox (`- [ ]`) syntax. Every task
> carries a `Models:` tag. Tests and implementation are written by different agents, in that
> order, and every test a reviewer approves gets sabotage-verified.

**Date:** 2026-10-19
**Issue:** robertwhiffin/ai-slide-generator#323 "Clear the chat on an existing deck and continue from its deck spec and slides"
**Branch:** `feat/323-clear-chat-keep-deck` (off `origin/main` 679d2f21)
**Spec:** none. The issue text and the Decisions below are the authority. The planner made the
Decisions while the user was unavailable. Each one records its reasoning so a reviewer can
overturn it.

## Revision log

Revision 2 (2026-10-19) applies the plan review (`~/tellr-loop/issues/issue-323/PLAN-REVIEW.md`,
findings F1 to F24) under the supervisor's rulings:

- **F1 applied, option (b).** The real-backend Playwright spec is dropped. Task 7 is now the
  TestClient full-stack route test `tests/integration/test_clear_chat_routes.py`, in
  integration-general. Option (a) is rejected and listed under Out of scope.
- **F2 applied.** Task 5 re-reads the permission when a browser-local session becomes persisted.
  Vitest case 12 added.
- **F3 applied.** A2's evidence is relabelled honestly. Task 7 runs a scripted post-clear tour turn.
  Task 9's hand-off notes say no e2e runs a real architect turn after a clear.
- **F4 applied.** Task 1 fixes the two route stubs that would pass through a `TypeError`.
- **F5 applied.** Task 1's sabotage targets corrected.
- **F6 applied.** Task 2 Step 1 names the graph test's real first failure.
- **F7 applied.** Full `SessionMessage` reader table in Context 3, referenced from D1 and Review focus 2.
- **F8 applied.** The restore claim is corrected everywhere, including Task 8's docs text.
- **F9 applied.** The graph test reads the pin back with `load_conversation_pin`; the
  teardown-as-evidence claim is removed.
- **F10 applied.** Task 7 takes a real save point before the clear and checks its preview.
- **F11 applied.** Task 1 adds one `@pytest.mark.postgres` test, which runs in the CI unit job.
- **F12 applied.** Task 5 resets `isClearing` on a session switch and stale-guards the initial load.
- **F13 applied.** Lint and vitest gates are compared against the recorded baselines.
- **F14 parked, evidence added.** `ask_data` `deck_purpose` stays out of scope as a PR follow-up.
- **F15 applied.** D6 records the SSE-disconnect hole.
- **F16 applied.** Task 8 also updates `real-time-streaming.md` and `mcp-server.md`.
- **F17 applied.** D1 reworded only; no filter in `mcp_server.py`.
- **F18 rejected.** Pre-existing behaviour for uncleared legacy duplicates; listed under Out of scope.
- **F19 applied.** The dialog's confirm click is scoped in Tasks 5 and 6.
- **F20 applied.** `conversation.ts` throws the existing `ApiError`; `ConversationApiError` is dropped.
- **F21 applied.** D3 reworded; Task 6 test 3 is labelled a tripwire.
- **F22 applied.** Task 9 is `test=opus impl=opus`; Task 6 states that a stop escalates to opus.
- **F23 applied.** New failure and 409 copy; no 404 mapping.
- **F24 applied.** Local e2e runs need ports 3000 and 8000 free; the `isClearing` term goes on its
  own line.

## Goal

A user with edit rights on an agent-mode deck can clear their own chat. The chat panel empties
and stays empty after a reload. The deck, its slide rows, its Spec, its save points, its engine
and its Conversation Pin are unchanged. The next turn starts from the persisted `DeckSpec` and the
committed slide rows, not from the old transcript. An edit such as "make slide 3 shorter" rebuilds
only slide 3.

The backend route exists but nothing calls it. Planning found three defects in it that must be
fixed before a button can ship (Context items 4, 8 and 10):

1. **The kept first message still shows up.** The kept row reappears in the chat panel after a
   reload, and it is still replayed to the architect as conversation.
2. **The clear is two transactions.** On SQLite it cannot work at all. On Postgres it can leave
   the graph thread deleted while the transcript is still there.
3. **Any editor can clear the owner's chat.** On a shared deck, an editor can wipe the owner's
   transcript by passing the owner's session id.

---

## Context (verified 2026-10-19)

All paths are relative to the worktree root. "Probe" means the planner ran a throwaway script or
test outside the repo against the real code. Nothing in the repo was changed.

1. **`ChatService.clear_context`** (`src/api/services/chat_service.py:2146-2252`) keeps the earliest
   `role='user'` row of the session (query at `:2215-2223`). It bulk-deletes every other row of that
   session (`:2226-2231`). Then it calls `get_checkpointer().delete_thread(session_id)` inside its
   `with get_db_session()` block (`:2234-2236`). It takes no actor argument and writes no attribution.
   Its docstring describes the two-transaction half-state.
2. **Engine mode** (`resolve_engine_mode`, `chat_service.py:164-251`) reads the earliest
   `role='user'` message of the **owner deck's** session. It filters on `role` only, never on
   `message_type`. A deck with no user message resolves to `"graph"`, and `LEGACY_MODE_PHRASE`
   (`src/domain/conversation_engine.py:11`) selects the monolith. The pin backfill
   (`src/services/conversation_pins.py:186-207`) and the duplicate marker carry
   (`src/api/services/session_manager.py:1233-1318`, which copies `message_type`) also read the first
   user row by `role` only.
3. **Every transcript reader goes through `SessionManager.get_messages`**
   (`session_manager.py:1508-1536`). It returns every row with no type filter. Its callers are:
   - `GET /api/sessions/{id}` (`src/api/routes/sessions.py:540-543`, creator only);
   - `GET /api/sessions/{id}/messages` (`sessions.py:741-799`);
   - `ChatService._hydrate_chat_history`, the monolith's history (`chat_service.py:2415-2467`, admits
     `HUMAN_TYPES = {"user_query","user_input","chat"}`);
   - `nodes._conversation`, the architect's `conversation` payload (`src/services/graph/nodes.py:965-988`,
     admits `_HUMAN_TYPES` from `nodes.py:200`);
   - the tour (`src/api/routes/tour.py:117-124`);
   - the slide-verification corpus (`src/api/routes/verification.py:173-179`).

   `SessionManager.create_version` captures `session.messages` raw into a save point's
   `chat_history_json` (`session_manager.py:2508-2519`). Its only caller is
   `ChatService.create_save_point` (`chat_service.py:3040`), which never passes `chat_history`.

   **Every `SessionMessage` reader, and what it sees after this plan** (review F7; this table is
   Review focus 2's baseline):

   | Reader | Location | Sees the re-typed row? | Verdict |
   |---|---|---|---|
   | `GET /sessions/{id}` | `sessions.py:543` | no | correct |
   | `GET /sessions/{id}/messages` | `sessions.py:773` | no | correct |
   | monolith history | `chat_service.py:2433` | no | correct |
   | architect `conversation` | `nodes.py:973` | no | correct |
   | tour stage machine | `tour.py:117-124` | no | Changed, harmless. After a clear the `prompt` and `plan` stages read as not applied, so `stages/plan` answers 409. `build` is derived from the deck, so `review` and `edit` still run. |
   | verification corpus | `verification.py:173-179` | no | Harmless. It reads only `role=tool` rows. A clear deletes those, but graph decks write none, so only a legacy deck cleared through the route loses its corpus. |
   | save-point capture | `session_manager.py:2509-2519` | no | correct |
   | `message_count` (session detail, MCP) | `session_manager.py:816-821`; `mcp_server.py:234` | yes | correct, intended |
   | `list_sessions` count and `messages.any()` | `session_manager.py:996-1015` | yes | harmless (a cleared deck still has a deck) |
   | duplicate carry | `session_manager.py:1233-1318` | yes (role only) | correct; carries the hidden type |
   | `restore_version` prune | `session_manager.py:2789-2801` | yes (by `created_at`) | see Context 14 |
   | `get_messages_for_request` (poll, MCP `get_deck_status`) | `session_manager.py:3332-3368`; `mcp_server.py:817` | yes | harmless; see D1 |
   | `resolve_engine_mode`, pin backfill, the clear's own marker query | `chat_service.py:225, 2216`; `conversation_pins.py:186` | yes | correct |
4. **The kept marker leaks today (probe).** The planner ran a build turn, then the current clear, then
   an edit turn through the compiled graph (the `graph_turn_env` harness). The architect's
   `conversation` was `[{"user": "Build me a deck about puffins"}, {"user": "Make slide 3 shorter"}]`:
   the deck's original prompt is replayed as conversation. The probe then re-typed the kept row to a
   type outside `_HUMAN_TYPES`, and the same turn received only `[{"user": "Make slide 3 shorter"}]`.
   The chat panel hydrates only from `api.getSession(id).messages`
   (`frontend/src/components/ChatPanel/ChatPanel.tsx:97-124`) and does not filter by type, so the
   kept row also reappears in the panel after a reload.
5. **What the probe confirmed for the next turn after an atomic clear** (kept row re-typed,
   checkpoints deleted on the same connection):
   - the architect payload's `current_deck_spec` equals the persisted spec;
   - `committed_slide_count` is 4;
   - `previous_deck_review.digest` equals `compute_deck_digest` of the committed rows
     (`src/services/deck_review_store.py:104`);
   - the turn is `intent="edit"` with `error_state` None;
   - the builder ran only for position 2;
   - rows 0, 1 and 3 kept byte-identical HTML and row 2 changed;
   - the persisted spec was revised only at position 2.
6. **The architect payload** (`nodes.py:1525-1543`) contains `conversation`, `message`,
   `current_deck_spec`, `committed_slide_count`, `previous_deck_review`, `available_design_contract`,
   `template_sections`, `resolved_style` and `design_system_library`. It never contains slide HTML;
   committed slides reach it as the count, the review keyed by the committed-row digest, and the
   spec/row alignment guard (`_persisted_spec_describes_these_rows`, `nodes.py:1006`). This plan
   changes no prompt, output schema, payload key, Agent Definition or digest.
7. **The graph thread holds only per-turn state.**
   - `invoke_graph` uses `thread_id = session_id`, which is the actor session
     (`src/services/graph/builder.py:253-377`, config at `:363-366`).
   - The architect reads the conversation, spec and rows from the database (Context 3 and 6), and
     turn-scoped keys reset every turn (`src/services/graph/state.py` module docstring).
   - Only one thread value is read across turns: `state["deck_spec"]`. `data_analyst_node` uses it for
     `deck_purpose` (`nodes.py:2025-2027`), and the deck reviewer uses it after the architect has
     rewritten it on build and edit turns.
8. **The current clear cannot complete on SQLite (probe).** `delete_thread`
   (`src/core/checkpointer.py:467-472`) opens and commits its own session (`_session`, `:226-245`).
   On a file-backed SQLite database with the real `SqlAlchemyCheckpointSaver`, the current
   `clear_context` raised `OperationalError: database is locked` after the busy timeout (3.1 s with
   `timeout=3`). The outer transaction's bulk DELETE holds the SQLite write lock while the saver's
   second connection waits for it. On Postgres the two transactions touch different tables, so it
   works, but with the half-state its docstring describes. The existing unit tests replace the saver
   with a stub (`tests/unit/test_clear_context.py:49-60`), so neither failure was ever exercised.
9. **Graph integration tests run locally.** `graph_turn_env` (`tests/integration/conftest.py:765-849`)
   runs the compiled graph over a file-backed SQLite database (`_make_graph_engine`, `:559-595`) with
   the real saver. Only `AgentRuntime.run` is stubbed, by `SkillRecorder`
   (`tests/integration/conftest_stub_skills.py`), which has an `edit_target_positions` setting.
   `test_graph_orchestration.py -k "edit_turn or edit_whose"` passed locally (2 tests in 0.46 s).
10. **The route has no creator gate.** `clear_session_context` (`sessions.py:851-899`) checks only
   `_check_deck_permission_for_session(session_id, CAN_EDIT)` (`src/api/routes/_authz.py:202-232`),
   which resolves permission on the ROOT deck (`_get_session_permission_for_info`, `_authz.py:39-73`).
   - So any CAN_EDIT editor of a shared deck can clear the owner's session by id. That id is what
     `/api/sessions/shared` lists and what the frontend posts to `/contribute`.
   - Everywhere else, conversations are creator-only: `GET /messages` (`sessions.py:765-769`),
     `GET /sessions/{id}` (`:538-543`) and chat (`_check_chat_permission`, `src/api/routes/chat.py:94-156`).
   - The route takes no session lock. Other mutation routes take `acquire_session_lock` and answer 409:
     `src/api/routes/slides.py:187-195` and `chat.py:438-446`, `:548-556`, `:731-738`.
11. **The session lock** (`session_manager.py:3104-3152`, release at `:3154-3177`) is a database flag
   (`UserSession.is_processing`). It works across workers and is treated as stale after 300 s.
   The SSE path releases it in the generator's `finally` (`chat.py:~657-662`); the async path holds it
   until the job finishes. The describe-only arc-review sweeper invokes the graph on the owner thread
   **without** the lock and writes no chat rows (`src/services/spec_sync.py:652-664`).
12. **Contributors.**
   - A contributor session is its own `UserSession` row with `parent_session_id` set
     (`src/database/models/session.py:159-164`).
   - It has its own transcript, its own graph thread (its session id) and its own Conversation Pin
     (`graph_release_id`, `session.py:165-175`).
   - The engine resolves on the owner (Context 2).
   - The existing test `test_clearing_a_contributor_session_leaves_the_owners_marker` already pins
     that clearing a contributor's session leaves the owner's rows alone.
13. **Per-process state.** `ChatService` holds one cache, `_deck_cache`, and checks it against the
   deck version (`chat_service.py:346-356`). Clearing the chat does not change the deck. Agents are
   built per request and their history comes from rows. The checkpointer keeps no state of its own.
   So no worker holds a copy of the transcript that a clear on another worker would leave stale.
14. **Save points.**
   - `SlideDeckVersion` lives on the deck owner (`session.py:519-563`).
   - `restore_version` deletes **this session's** rows created after the save point
     (`session_manager.py:2789-2801`); save points live on the owner deck. The kept row survives
     whenever it predates that save point, which is always true for a root deck's own first turn. A
     contributor's kept row can be removed by a restore, because a contributor's first message
     usually postdates the owner's save points. That is harmless: the deck's engine resolves on the
     owner's rows (Context 2).
   - Save-point preview shows the snapshot's `chat_history` (`frontend/src/components/Layout/AppLayout.tsx:739-748`).
   - `message_count` is a raw COUNT (`session_manager.py:816-821`). `is_first_message = message_count == 0`
     gates title generation (`chat.py:753`, `chat_service.py:1153`).
15. **Attribution options.**
   - `usage_events` (`src/database/models/usage_event.py`) is durable and never pruned. Its columns
     are `username` (NOT NULL), `event_type` (free `String(30)`) and `session_id` (an integer, not a
     foreign key).
   - Admin analytics reads it per type and counts every row as activity
     (`src/api/services/usage_service.py:291-297`, `:517-518`).
   - `SharedDeckMutationEvent` lists its allowed operations in a CHECK constraint
     (`session.py:474-490`) and is append-only by trigger. It records deck mutations, which a clear
     is not.
16. **Frontend.**
   - Nothing calls `DELETE /context` (grep).
   - The ChatPanel header is at `ChatPanel.tsx:389-397`. The panel receives `disabled={isReadOnly}`
     (`AppLayout.tsx:1240`), where `isReadOnly = preview || viewOnly || !isLockHolder` (`:806-807`).
   - AppLayout does not track `my_permission`. `GET /api/sessions/{id}` returns it (`sessions.py:556`)
     and the `Session` type declares it (`frontend/src/services/api.ts:117-118`).
   - A reusable `ConfirmDialog` exists (`frontend/src/components/ConfirmDialog.tsx`, testid
     `confirm-dialog`, also used by `deck-history.tsx:135`).
   - `SlideDeck.deck_spec` is declared at `frontend/src/types/slide.ts:133`.
   - An empty panel renders `ChatWelcome` (testid `chat-welcome`, `MessageList.tsx:21`).
17. **CI.**
   - The e2e matrix is at `.github/workflows/test.yml:687-739`, run as
     `npx playwright test tests/e2e/${{ matrix.test }}.spec.ts` (`:986`), and guarded by
     `tests/unit/test_e2e_matrix_covers_specs.py`.
   - Integration test files must be named in a job's run block, guarded by
     `tests/unit/test_ci_collects_integration_tests.py`. The integration-graph job's list is at
     `test.yml:428-465`.
   - Both guards pass today (29 passed).
18. **Playwright.**
   - Mocked specs use `page.route`, with `setupMocks`, `mockSessionWithSlides` and `apiPath`.
   - `setupMocks`' catch-all answers any DELETE under `/api/sessions` with 200 `{success:true}`
     (`frontend/tests/helpers/setup-mocks.ts:96-100`), so a spec must register its own `/context` route.
   - Real-backend specs such as `history-integration.spec.ts` call `127.0.0.1:8000`. The CI e2e
     backend runs with `DATABRICKS_HOST=https://test.databricks.com` (`test.yml:907-913`), which puts
     the identity provider in WORKSPACE mode. Any read of a deck with slide rows then makes a real
     SCIM display-name call that retries for minutes (review F1, probed). No e2e spec in CI reads a
     real deck with rows today. That is why this plan has no real-backend Playwright spec.
   - The tour helpers `_phase1_create_session(created_by)` and `_run_stage(session_id, stage, created_by)`
     (`tour.py:63-89, 228-277`) seed a pinned deck with a spec, verified slides and a transcript, with
     no model call. `tests/unit/test_tour_staged_demo.py:22-69` drives them directly.
   - `integration-general` (`test.yml:522-571`) runs TestClient and SQLite integration files with
     `DATABRICKS_HOST: ""`, which keeps identity LOCAL, so there is no SCIM call. It already runs
     `tests/integration/test_savepoint_e2e.py`, the model for Task 7.

## Global constraints

- **Environment.** Use the per-worktree venv: `uv sync --extra dev` once, then run everything with
  `uv run …`. Never `pip install` and never `git stash`. Commit in a separate shell command:
  `git commit -m "<subject>" -m "Co-authored-by: Isaac <no-reply@databricks.com>"`.
- **No deploys.** Do not run `publish-dev.yml` or `scripts/deploy_local.sh`.
- **Frozen artefacts stay frozen.** No change to any prompt, output schema, Agent Definition,
  architect payload key, `DeckSpec` or `SlideSpec`. That means no change to
  `frontend/src/types/slide.ts` or `deckSpecConformance.test.ts`, and no digest change.
- **No migration.** No new column or table. `message_type` is `String(50)` and
  `usage_events.event_type` is a free `String(30)`.
- **Baselines are sets of failure causes, not counts** (skill §3).
- **Stay out of sibling issues.**
  - #321: failure-notice wording in `nodes.py`.
  - #319: chat stage placeholder, `ChatWelcome.tsx` and `LoadingIndicator.tsx`. ChatPanel edits stay
    in the header, the state declarations and one new handler, to keep merges small.
  - #316: findings copy.
  - #318: Spec export.
  - #313: architect evals.
- **#317 builds on this branch.** Keep the interfaces named in "Extension points for #317" stable.

## Acceptance criteria (from the issue) → how each is met and proven

| # | Acceptance criterion (verbatim) | Met by | Proven by |
|---|---|---|---|
| A1 | A "Clear chat" action on an existing deck (with confirmation) calls the route and empties the chat panel. The deck, its slides and the Spec view stay unchanged. | **Task 5:** header button and `ConfirmDialog`. It calls `conversationApi.clearChat(sessionId)`, empties only the local messages, and never calls `onSlidesGenerated` or refetches slides. **Task 2:** the kept row is hidden from every read, so a reload stays empty. **Task 3:** the gated route. | `ChatPanel.clearChat.test.tsx` (`confirming clears…`, `cancel clears nothing`). `clear-chat.spec.ts` test 1 (panel empty; slides, Spec and save-point trigger unchanged; no `/slides` refetch; reload still empty). `test_clear_chat_routes.py` (full backend stack through TestClient: `GET /sessions/{sid}` and `GET /sessions/{sid}/messages` return `[]` after the clear; slides HTML and `deck_spec` unchanged). `test_get_messages_returns_nothing_after_a_clear_but_the_marker_row_remains`. |
| A2 | After clearing, the next turn picks up the existing deck. The architect gets the persisted `deck_spec` and the committed slides. An edit such as "make slide 3 shorter" works without the old transcript and does not rebuild unrelated slides. Cover this with a graph test and an e2e test. | **Task 2:** the hidden kept row stops the architect seeing the old prompt. **Task 1:** an atomic clear deletes the thread. Nothing changes in the graph: the payload already carries the persisted spec and the row-derived fields (Decision D10). | **Backend half** (the architect gets the spec and row-derived fields, no old transcript, only slide 3 rebuilt): the graph test `test_after_a_clear_an_edit_turn_runs_from_the_spec_and_the_committed_rows` is the only real-architect evidence, backed by unit tests `test_the_architect_conversation_after_a_clear_is_only_new_turns` and `test_the_monolith_history_after_a_clear_is_only_new_turns`. **Real backend after a clear:** `test_clear_chat_routes.py` runs a *scripted* tour turn (no architect) and checks the chat shows only the new rows and the spec differs only at the edited position. **UI journey:** E2E `after clearing, an edit turn shows only the new conversation and changes only slide 3`, which scripts the stream and the slides, so it cannot detect a backend regression. No e2e runs a real architect turn after a clear: CI has no model. |
| A3 | The cleared deck keeps its engine (agent-mode decks stay on the graph), its Graph Release pin and its save points. | The kept row is still the deck's earliest user row. `clear_context` never touches `graph_release_id` or `slide_deck_versions`. Save points taken later do not capture the kept row. | Engine: existing `test_a_graph_sessions_first_row_is_preserved_too`; new `test_a_later_legacy_phrase_after_a_clear_does_not_move_a_graph_deck` and `test_a_duplicate_of_a_cleared_legacy_deck_stays_legacy_and_shows_no_chat`; the graph test asserts `"graph"`. Pin: the graph test reads the pin back with `load_conversation_pin` (the read `invoke_graph` uses); `test_clear_chat_routes.py` checks `graph_version` on `GET /sessions/{sid}`; the e2e checks the `graph-version-status` text. Save points: `test_a_clear_leaves_every_save_point_untouched`, `test_a_save_point_taken_after_a_clear_captures_no_marker`, `test_clear_chat_routes.py` (a real save point's preview `chat_history` is unchanged by the clear), and the e2e save-point trigger. |
| A4 | Permissions: editors only on a shared deck, and the action is attributable. Decide what a contributor's clear means: their own session's transcript only, or the owner's. | **Task 3:** CAN_EDIT gate, plus a new creator gate, plus the session lock. **Task 1:** `usage_events` row `context_cleared` written in the same transaction. **Task 5:** the button shows only for editors. Contributor semantics: own session only (D3). | Route tests `test_an_editor_who_is_not_the_sessions_creator_is_refused` and `test_a_viewer_is_refused_and_nothing_is_cleared`, plus the `_require_conversation_creator` tests. `test_a_clear_records_who_cleared_it_in_the_same_transaction` and `test_the_route_passes_the_caller_as_cleared_by`. Vitest visibility tests. E2E `a viewer is not offered Clear chat`, plus the regression tripwire `a contributor with edit rights clears their own session, never the owner's`. D3's proof is the backend creator-gate tests, not the tripwire. |

## Decisions

- **D1. The kept row stays, re-typed, and every transcript read hides it.**
  - `clear_context` still keeps the earliest user row, because engine mode reads it. It also sets
    that row's `message_type` to a new constant, `ENGINE_MODE_MARKER_MESSAGE_TYPE = "engine_mode_marker"`,
    defined in `src/domain/conversation_engine.py`.
  - `SessionManager.get_messages` and `create_version`'s save-point capture drop rows of that type.
    That covers the chat panel (on load and reload), `GET /messages`, the architect's
    `conversation`, the monolith's history, the tour and the verification corpus. Context 3's reader
    table lists every reader and its verdict.
  - The readers that decide engine mode and the pin (`resolve_engine_mode`, the duplicate carry, the
    pin backfill) filter on `role` only, so they still see the row and nothing about the engine
    changes.
  - `message_count` deliberately still counts the row, so the next turn is not treated as a "first
    message" and does not regenerate the title of an existing deck.
  - `get_messages_for_request` is not filtered. A poll for the deck's first request after a clear
    (for example MCP `get_deck_status(first_request_id)`) returns the kept row with its hidden type.
    That is harmless. `mcp_server.py` is not changed.
  - Rejected alternatives:
    - *Delete the row on graph decks*, since no user row also resolves to graph. A later message
      containing `USE LEGACY MODE` would then become the earliest row and move a graph deck to the
      monolith. The current design rule is that clearing never changes the mode.
    - *A new `engine_mode` column.* Needs a migration and breaks the documented rule that "nothing
      about mode is stored".
    - *A frontend-only filter.* The architect and the monolith would still replay the old prompt
      (Context 4).
- **D2. The half-state is removed in the backend by making the clear one transaction.**
  - `SqlAlchemyCheckpointSaver.delete_thread` gains a keyword-only `session=None`. When given, it runs
    its two DELETEs on the caller's session and does not commit. `clear_context` passes its own `db`.
  - The transcript prune, the marker re-type, the attribution row and the thread delete then commit
    or roll back together.
  - This also removes the SQLite self-deadlock (Context 8). Without the change, the graph test
    required by A2 cannot run, locally or in CI.
  - Lakebase safety holds. The caller's session comes from the app's own factory through
    `get_db_session`, so it passes through the `do_connect` token listener. Nothing is kept on `self`,
    and the caller commits and closes it.
  - The UI still handles failure honestly. On any error it keeps the conversation and shows
    "Couldn't clear the chat. Reload the page to see its current state, then try again." It does not
    claim the conversation is unchanged: if the server committed and the response was lost (a proxy
    timeout), it did change. A retry is idempotent: deleting an absent thread is a no-op DELETE.
  - Rejected alternative: *commit the transcript first, then delete the thread*. That flips the skew
    to "transcript gone, thread kept", and the route would answer 500 for a clear that actually
    happened.
- **D3. A contributor's clear means their own session only:** their own transcript and their own
  graph thread.
  - The owner's transcript is private. A contributor can never read it (Context 10), so they must not
    be able to destroy it.
  - The contributor's own turns already run on their own thread.
  - The deck's engine lives on the owner's rows and stays untouched.
  - The backend enforces this with a new creator gate, and those tests are D3's proof. A
    contributor's UI targets their contributor session (`SessionHistory.tsx:127`,
    `getOrCreateContributorSession` → `onSessionSelect`). A contributor viewing the owner's session
    sees the action disabled, because that session returns no messages to them
    (`sessions.py:540-543`), and the backend refuses it.
- **D4. Who can clear.**
  - Backend:
    - The caller must hold **CAN_EDIT or CAN_MANAGE on the deck**. This existing gate resolves on the
      root deck.
    - The caller must also be **the session's creator**. This gate is new, `_require_conversation_creator`.
    - A user who is not signed in gets 401.
  - Frontend:
    - The button shows only when the session is persisted, the live deck has a Spec, and
      `canEditConversation(my_permission)` is true.
    - It is disabled while a turn is in flight or a clear is running, while the panel is read-only or
      previewing a save point, and when there are no messages.
  - The clear does **not** require the deck *editing* lock. It changes no deck state, and that lock
    exists to serialise deck edits. The UI is still conservative: the button is disabled whenever
    the chat input is read-only.
  - Legacy (monolith) decks: the button is hidden because they have no Spec to continue from. The
    route still works for them, and the mode is still kept by D1.
- **D5. Attribution uses an existing table.**
  - Each clear writes one `usage_events` row in the clear's own transaction, so the row exists if and
    only if the clear committed. Its values are `event_type = EVENT_CONTEXT_CLEARED = "context_cleared"`,
    `username = cleared_by`, and `session_id` = the cleared session's internal id.
  - The structured log line also gains `cleared_by`.
  - `clear_context` takes a required keyword `cleared_by` and refuses a falsy value before changing
    anything.
  - This is the existing durable log of per-user activity: never pruned, no migration, survives
    session deletion, and already read by admin analytics. A clear counting as activity there is
    correct.
  - Rejected: `SharedDeckMutationEvent` (Context 15: needs a CHECK-constraint migration, and would
    report a private chat clear as a deck mutation in collaboration history); log-only (not durable or
    queryable); a visible "chat cleared by" message (contradicts "empties the chat panel").
- **D6. A clear is refused while a turn is in flight.**
  - Backend: the route takes `acquire_session_lock` and answers **409** with `CONVERSATION_BUSY_DETAIL`
    while a turn holds it. It releases the lock in `finally`, and **only if it acquired it**.
  - Frontend: the button is disabled while the panel's own turn is running (`isLoading`). A 409 from
    another tab, MCP or a slide operation (which also takes the session lock, `slides.py:187-195`)
    shows "Something is still running on this deck. Wait for it to finish, then clear the chat." and
    keeps the messages.
  - Known and accepted:
    - The arc-review sweeper runs without the lock and can write a checkpoint after a clear. That is
      harmless: the thread holds only per-turn state (Context 7), and the sweeper writes no chat rows.
    - A turn longer than 300 s makes the lock count as stale. This is the existing behaviour of every
      mutation route.
    - On the SSE path the lock is released in the async generator's `finally` (`chat.py:657-661`)
      while the turn runs on in a daemon thread (`chat.py:596-617`). A client that disconnects or
      reloads mid-turn releases the lock early, so a clear in that window succeeds and the turn's later
      rows and checkpoints land in the cleared conversation. Production polls and holds the lock in
      the database for the whole job, so this affects SSE (local dev) only, and it already applies to
      every lock user. The guarantee is not absolute.
  - No per-worker cache needs invalidating (Context 13).
- **D7. The button sits in the ChatPanel header, on the right of the "AI Assistant / Ask me to create
  or edit slides" block.**
  - It is a `Button` from `@/ui/button` (`size="sm"`, `variant="ghost"`) with a lucide `Eraser` icon,
    the label "Clear chat", and `data-testid="clear-chat-button"`.
  - The confirmation reuses `src/components/ConfirmDialog.tsx`, which also works inside cross-origin
    iframes.
  - It is not in a menu, because the panel has no menu and adding one is gold-plating.
- **D8. Copy.** All strings are constants in `frontend/src/components/ChatPanel/clearChatCopy.ts`:
  - Title: `Clear chat?`
  - Message: `This deletes your conversation on this deck. Your slides, the Spec and save points stay as
    they are, and the assistant carries on from the Spec and the current slides. This can't be undone.`
  - Confirm button: `Clear chat` (variant `danger`). Cancel button: `Cancel`.
  - Tooltip: `Delete this conversation and keep the deck, its Spec and save points`.
  - 409: `Something is still running on this deck. Wait for it to finish, then clear the chat.`
  - 403: `Only editors can clear the chat, and only their own conversation.`
  - Any other failure, including 404: `Couldn't clear the chat. Reload the page to see its current
    state, then try again.` There is no separate 404 message.

  One message serves both the owner and a contributor, because "your conversation" is true for both.
- **D9. Save points stay exactly as they are.**
  - Each one keeps the chat it captured, so a preview of an older save point still shows the old
    conversation. The docs say so.
  - Save points taken after a clear do not capture the kept row (D1).
  - A restore deletes this session's rows created after the save point. The kept row survives
    whenever it predates that save point, which is always true for a root deck's own first turn. A
    contributor's kept row can be removed by a restore, which is harmless: the deck's engine resolves
    on the owner's rows (Context 14).
- **D10. "The architect gets … the committed slides" is read as the row-derived fields the payload
  already has:** `committed_slide_count`, `previous_deck_review` keyed by the digest of the committed
  rows, and the spec/row alignment guard.
  - Slide HTML is not added. That would change the model-facing payload of a pinned Agent Definition,
    and the probe shows the edit works without it (Context 5).
- **D11. One mocked e2e spec, plus a full-stack backend route test.**
  - `clear-chat.spec.ts` mocks the backend with `page.route`. It covers the UI journey including the
    follow-up edit turn, which needs a model and so cannot run on a real backend in CI. It can run
    locally against vite alone (ports 3000 and 8000 free).
  - `tests/integration/test_clear_chat_routes.py` (Task 7) drives the real routes, services and
    database through TestClient. It proves the backend half of "a reload after a clear stays empty"
    (the defect in Context 4), the save-point preview, the pin, and a scripted post-clear turn. It
    runs locally and in integration-general.
  - A real-backend Playwright spec was dropped (review F1). In the CI e2e backend's environment,
    reading a deck with slide rows hangs on SCIM display-name lookups. The fix for that touches a
    shared job and needs the user's ruling (Out of scope).

## Review focus

1. **One transaction.** Nothing inside `clear_context` may commit before its `with` block exits, and
   `delete_thread(..., session=…)` must neither commit nor close the caller's session.
   Sabotage: add `session.commit()` to that branch. Task 1's failing-commit test must go red.
2. **The hidden row is hidden everywhere it is shown to a person or a model, and nowhere else.** It is
   filtered in `get_messages` and in the `create_version` capture. It is deliberately *not* filtered
   in `resolve_engine_mode`, the duplicate carry, the pin backfill, `message_count` or
   `get_messages_for_request`. Check the diff against Context 3's reader table, row by row.
3. **The route's checks run in this order:** deck gate, then creator gate, then lock, then clear, then
   release. A refused or busy request touches nothing, and a 409 never releases another request's lock.
4. **The frontend never refetches slides or resets the Spec on a clear.** A response that lands after
   the user switched session is dropped.
5. **No payload, prompt, schema or digest change** anywhere in the diff.

## File map

| File | Change | Task |
|---|---|---|
| `src/core/checkpointer.py` | `delete_thread(thread_id, *, session=None)` | 1 |
| `src/database/models/usage_event.py` | `EVENT_CONTEXT_CLEARED` | 1 |
| `src/api/services/chat_service.py` | `clear_context(session_id, *, cleared_by)`: one transaction and attribution (T1); marker re-type (T2) | 1, 2 |
| `src/api/routes/sessions.py` | pass `cleared_by` (T1); creator gate, lock and `CONVERSATION_BUSY_DETAIL` (T3) | 1, 3 |
| `src/domain/conversation_engine.py` | `ENGINE_MODE_MARKER_MESSAGE_TYPE`, `is_transcript_message()` | 2 |
| `src/api/services/session_manager.py` | filter in `get_messages` and the `create_version` capture | 2 |
| `src/api/routes/_authz.py` | `_require_conversation_creator(session_id)` | 3 |
| `tests/unit/test_checkpointer.py` | caller-session tests | 1 |
| `tests/unit/test_clear_context.py` | extended in T1 (including one `postgres` test), T2 and T3 | 1, 2, 3 |
| `tests/integration/test_clear_context_graph_turn.py` | **new** graph test | 2 |
| `.github/workflows/test.yml` | integration-graph list (T2); e2e matrix entry `clear-chat` (T6); integration-general list (T7) | 2, 6, 7 |
| `frontend/src/api/conversation.ts` (+ `.test.ts`) | **new** `conversationApi.clearChat`, throwing the existing `ApiError` | 4 |
| `frontend/src/utils/conversationPermissions.ts` (+ `.test.ts`) | **new** `canEditConversation` | 4 |
| `frontend/src/components/ChatPanel/clearChatCopy.ts` | **new** copy constants and `clearChatErrorMessage` | 5 |
| `frontend/src/components/ChatPanel/ChatPanel.tsx` | button, dialog, state, `hasDeckSpec` prop | 5 |
| `frontend/src/components/ChatPanel/ChatPanel.clearChat.test.tsx` | **new** | 5 |
| `frontend/src/components/Layout/AppLayout.tsx` | pass `hasDeckSpec={!!slideDeck?.deck_spec}` | 5 |
| `frontend/tests/e2e/clear-chat.spec.ts` | **new** mocked e2e | 6 |
| `tests/integration/test_clear_chat_routes.py` | **new** TestClient full-stack route test | 7 |
| docs (see Task 8), `frontend/src/components/Help/HelpPage.tsx` | user and technical docs | 8 |

Tasks touching the same file run in order: **1 → 2 → 3** (backend), **4 → 5** (frontend),
**2 → 6 → 7** (`test.yml`), and **8** after everything. Tasks 4 and 5 share no file with Tasks 1 to 3
and may run in parallel with them.

---

## Before Task 1 (controller pre-pass, not a task)

- [ ] **Set up and check prerequisites.**
  - Run `cd /Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-323 && uv sync --extra dev`.
  - Confirm `frontend/node_modules` exists.
- [ ] **Record baseline failure causes:**
  - `uv run pytest tests/unit -q -n 4 -p no:cacheprovider`
  - `uv run pytest tests/integration/test_graph_orchestration.py tests/integration/test_spec_row_alignment.py tests/integration/test_savepoint_e2e.py -q`
  - `cd frontend && npm run test:unit && npm run build`
  - The recorded baselines are in `~/tellr-loop/issues/issue-323/`:
    - `baseline-unit.txt`: 9166 passed, 135 skipped.
    - `baseline-fe-unit.txt`: 3 files and 20 tests red, all from one cause. Node 26 leaves
      `localStorage` undefined in `SlideViewer/FindingsE2.test.tsx`, `SlideViewer/SlideViewer.test.tsx`
      and `SlideViewer/TourViewerBridge.test.tsx`.
    - `baseline-fe-lint.txt`: `eslint .` is not clean today (63 errors in 36 files, including
      `ChatPanel.tsx` and `AppLayout.tsx`), and CI does not run lint.
- [ ] **Frontend gates used by every task** (review F13):
  - **Lint gate:** `cd frontend && npx eslint <touched files>` shows no finding absent from
    `baseline-fe-lint.txt`. Compare by file, rule and message, not line number, because edits shift
    lines.
  - **Vitest gate:** the failure-cause set of `npm run test:unit` equals the baseline, which is only
    the Node 26 `localStorage` cause in the three SlideViewer files above.
- [ ] **Re-run the plan-vs-code check** for every line reference above. Write
  `PLAN-CORRECTIONS.md` beside this plan if anything moved.
- [ ] **Check the shared ports:** `lsof -nP -iTCP:3000 -sTCP:LISTEN; lsof -nP -iTCP:8000 -sTCP:LISTEN`.
  Run e2e locally only if **both** ports are free. A server on 3000 would be reused by Playwright's
  `reuseExistingServer: true`, testing *that* worktree's code. A backend on 8000 would answer the
  mocked spec's unmocked requests (`VITE_API_URL` is `http://127.0.0.1:8000`). See "Local vs CI".

---

### Task 1: `clear_context` is one transaction and records who cleared

**Models:** `test=opus impl=sonnet`. The plan gives the code. The checkpointer is
correctness-sensitive, and its module docstring explains why: a retained connection breaks on Lakebase.

**Files:**
- `src/core/checkpointer.py`, `src/database/models/usage_event.py`
- `src/api/services/chat_service.py` (`clear_context` only)
- `src/api/routes/sessions.py` (one line: pass `cleared_by`)
- `tests/unit/test_checkpointer.py`, `tests/unit/test_clear_context.py`

**Interfaces introduced:**

```python
# src/core/checkpointer.py: replaces the body at :467-472
def delete_thread(self, thread_id: str, *, session: Any | None = None) -> None:
    """Delete every checkpoint AND every pending write for one thread.

    With ``session`` the two DELETEs run on the CALLER's session and are NOT
    committed here: they commit or roll back with the caller's transaction.
    ``ChatService.clear_context`` relies on this so a clear is one transaction,
    and so it never holds a write open while a second connection writes (on
    SQLite that self-deadlocks: ``database is locked``). The caller owns the
    session's lifetime; nothing is retained on ``self``.

    Without ``session`` it opens, commits and closes its own, as before.
    """
    if session is not None:
        session.execute(_DELETE_THREAD_WRITES, {"thread_id": thread_id})
        session.execute(_DELETE_THREAD_CHECKPOINTS, {"thread_id": thread_id})
        logger.info("Deleted graph checkpoints for thread %s in the caller's transaction", thread_id)
        return
    with self._session() as own:
        own.execute(_DELETE_THREAD_WRITES, {"thread_id": thread_id})
        own.execute(_DELETE_THREAD_CHECKPOINTS, {"thread_id": thread_id})
    logger.info("Cleared graph checkpoints for thread %s", thread_id)
```

Also update the module docstring's "IMPLEMENTED SURFACE" line to mention the optional `session`.

```python
# src/database/models/usage_event.py: beside the other constants
EVENT_CONTEXT_CLEARED = "context_cleared"
```

`ChatService.clear_context(self, session_id: str, *, cleared_by: str) -> Dict[str, Any]` takes these
steps, in this order, all inside one `with get_db_session() as db:`:

1. `if not cleared_by: raise ValueError(...)` comes before the `with` block.
2. Resolve the session, find the marker and run the bulk delete, exactly as today.
3. `db.add(UsageEvent(username=cleared_by, event_type=EVENT_CONTEXT_CLEARED, session_id=session.id))`.
4. `db.flush()`, so a failed insert raises before the thread is touched.
5. `get_checkpointer().delete_thread(session_id, session=db)`.

Keep the lazy imports inside the method. The tests patch `src.core.database.get_db_session` and
`src.core.checkpointer.get_checkpointer` at their source. Add `"cleared_by"` to the log `extra`. The
return value is unchanged.

Rewrite the docstring's two-transaction paragraphs (`:2163-2190`) to say:
- the clear is one transaction;
- any failure leaves the transcript, the thread and the attribution exactly as they were;
- the earlier SQLite self-deadlock is why.

**Route:** `sessions.py:875` becomes
`await asyncio.to_thread(chat_service.clear_context, session_id, cleared_by=get_current_user())`.
`asyncio.to_thread` forwards keyword arguments, so no `partial` is needed. `get_current_user` is
already imported (`sessions.py:35`). Task 3 adds the 401 and the gates.

**Tests:**

- `tests/unit/test_checkpointer.py`, class `TestThreadIsolationAndDeletion` (uses its `two_threads`,
  `saver` and `saver_engine` fixtures; the engine is file-backed with ordinary pooling):
  - `test_delete_thread_on_a_callers_session_commits_with_the_caller`. Open
    `sessionmaker(bind=saver_engine)()` and call `saver.delete_thread("thread-a", session=s)`.
    `_count(saver_engine, "graph_checkpoints", "thread-a") == 1` still holds before `s.commit()`;
    `_count` reads on another connection. After the commit, both tables count 0 for `thread-a`, and
    `thread-b` is untouched.
  - `test_delete_thread_on_a_callers_session_rolls_back_with_the_caller`. After `s.rollback()`,
    `thread-a` still has its checkpoint row and its write row.
- `tests/unit/test_clear_context.py`:
  - Update `_RecordingSaver.delete_thread(self, thread_id, *, session=None)` to also record `session`.
  - Pass `cleared_by="test-user@example.com"` at every existing `ChatService().clear_context(...)` call.
  - In `test_marker_survives_rest_goes_spec_readable_thread_deleted`, also assert the saver received
    a non-None session.
  - Rewrite the docstring of `test_an_unimplemented_saver_rolls_the_prune_back`: the "reverse skew is
    real" paragraph is now false.
  - Weaken no assertion. Name each changed test and say why in the step report.
  - New tests, using a file-backed engine built in the test:
    `create_engine(f"sqlite:///{tmp_path/'clear.db'}", connect_args={"check_same_thread": False, "timeout": 2})`,
    then `Base.metadata.create_all` and `_run_migrations`, both from `src.core.database`. Seed one
    checkpoint and one pending write for the session's thread with a real
    `SqlAlchemyCheckpointSaver(session_factory=factory)`. Copy `test_checkpointer.py`'s `_config`,
    `_checkpoint` and `_metadata` helpers.
    - `test_clear_with_the_real_saver_on_a_file_backed_database_is_one_transaction`. The clear
      succeeds. Only the marker row remains; both checkpoint tables count 0 for the thread; there is
      one `context_cleared` row. *Red today:* `OperationalError: database is locked`.
    - `test_a_failed_commit_rolls_back_the_thread_delete_too`. Patch `src.core.database.get_db_session`
      with a context manager that yields a session, then on exit calls `rollback()` and raises
      `RuntimeError("commit failed")`. `clear_context` raises `RuntimeError`. The transcript is intact,
      the checkpoint and write rows are still present, and there are no `context_cleared` rows. A
      retry under the normal fake succeeds and clears both.
  - New tests on the in-memory fixtures:
    - `test_a_clear_records_who_cleared_it_in_the_same_transaction`. Exactly one `UsageEvent` with
      `event_type == EVENT_CONTEXT_CLEARED`, `username == "owner@example.com"` (the `cleared_by` passed)
      and `session_id ==` the session's integer id.
    - `test_a_clear_without_an_actor_is_refused_before_anything_changes`. Pass `cleared_by=None` and
      then `""`. Each raises `ValueError`, rows are unchanged, `saver.deleted == []`, and there is no
      usage event.
    - `test_a_rolled_back_clear_records_no_attribution`. A saver that raises `NotImplementedError`
      leaves no `context_cleared` row.
  - Route test fixture: update `stub_service.clear_context(self, session_id, *, cleared_by)` to record
    `(session_id, cleared_by)`. Update `test_the_happy_path_returns_the_services_result` to expect
    `[("s1", "editor@example.com")]`. Set `monkeypatch.setenv("DEV_USER_ID", "editor@example.com")`:
    the middleware reads it on every request (`src/api/main.py:404-408`).
  - **The two route tests with their own stubs (review F4).** `test_a_missing_session_is_a_404` and
    `test_an_unimplemented_saver_surfaces_as_a_500` define `_Missing.clear_context(self, session_id)`
    and `_Unimplemented.clear_context(self, session_id)` (`tests/unit/test_clear_context.py:404, 418`).
    Once the route passes `cleared_by=`, those raise `TypeError`, which the route maps to 500. The 404
    test would then go red for the wrong reason, and the 500 test would stay green while testing
    nothing.
    - Change both stubs to `(self, session_id, *, cleared_by)` and have each append
      `(session_id, cleared_by)` to a `calls` list.
    - Under `DEV_USER_ID=editor@example.com`, assert `calls == [("ghost", "editor@example.com")]` and
      `calls == [("s1", "editor@example.com")]` respectively, so the status cannot come from a
      signature mismatch.
  - **One Postgres test (review F11)**, class `TestTheClearAgainstRealPostgres`, marked
    `@pytest.mark.postgres` only (not `live`).
    - Copy `test_checkpointer.py`'s `_ADMIN_URL` (`:505-508`, reads `TELLR_TEST_POSTGRES_URL`) and
      `_postgres_available` (`:511-519`), and its `pg` fixture's shape (`:526-570`): a uuid-named
      throwaway database, a `NullPool` engine and a `do_connect` listener appending to `issued`. The
      fixture self-skips when no Postgres is reachable, so it skips locally.
    - Build the schema with `Base.metadata.create_all(engine)` then `_run_migrations(engine)`. Use a
      real `SqlAlchemyCheckpointSaver(session_factory=factory)`, wrapped so `delete_thread` records
      `len(issued)` before and after delegating.
    - `test_the_clear_is_one_transaction_on_postgres`: the clear leaves only the marker row, zero rows
      in both checkpoint tables for the thread, and one `context_cleared` row. `len(issued)` is
      unchanged across `delete_thread(session=db)`, so no new DBAPI connection is issued between the
      clear's checkout and its commit.
    - `test_a_failed_commit_on_postgres_leaves_everything`: under the failing-commit fake, the
      transcript, the checkpoint rows and the absence of a `context_cleared` row are all as before.
    - **CI runs it.** The unit-tests job provisions `postgres:15`, exports
      `TELLR_TEST_POSTGRES_URL: postgresql+psycopg2://test@localhost:5432/test_db` (`test.yml:133-134`),
      and runs `pytest tests/unit … -n auto` with no `-m` filter (`test.yml:135-138`; `pyproject.toml`
      has no `addopts`). `tests/unit/test_ci_exports_postgres_test_url.py` guards that export.

**Steps:**
- [ ] **Step 1 (test author).** Write the tests and confirm they fail for the stated reasons. The
  file-backed test fails with `database is locked`; the attribution tests fail with
  `TypeError: unexpected keyword 'cleared_by'` or with no row found. Leave them uncommitted.
- [ ] **Step 2 (implementer).** Make them green without editing the tests.
- [ ] **Step 3.** Run `uv run pytest tests/unit/test_clear_context.py tests/unit/test_checkpointer.py -q`,
  then `uv run pytest tests/unit -q -n 4`. Compare failure causes against the baseline. Locally the
  `postgres` test reports as skipped; that is expected, and CI's unit job runs it. If a Postgres is
  reachable, also run it with `TELLR_TEST_POSTGRES_URL=<url>`.
- [ ] **Step 4.** Sabotage, one at a time:
  - put `session.commit()` in `delete_thread`'s `session` branch;
  - call `delete_thread(session_id)` without `session=`;
  - write the `UsageEvent` in its own `get_db_session()` *before* the clear's `with` block. A clear
    that then rolls back still leaves an event, so `test_a_rolled_back_clear_records_no_attribution`
    must go red. (`test_a_failed_commit_rolls_back_the_thread_delete_too` stays green under this
    sabotage, because every `get_db_session` there is the failing fake.)
  - insert `db.commit()` right after the bulk delete in `clear_context`.
    `test_a_failed_commit_rolls_back_the_thread_delete_too` must go red, because the transcript is
    gone after the rollback.
  - revert one of the F4 route stubs to `(self, session_id)`. Its test must go red.

  Each must turn a named test red.
- [ ] **Step 5.** Commit: `fix(sessions): clear a session's context in one transaction and record who cleared it`.

---

### Task 2: A cleared conversation is empty to every reader; the graph test

**Models:** `test=opus impl=sonnet`

**Files:**
- `src/domain/conversation_engine.py`, `src/api/services/session_manager.py`
- `src/api/services/chat_service.py` (`clear_context`: one statement)
- `tests/unit/test_clear_context.py`
- **new** `tests/integration/test_clear_context_graph_turn.py`
- `.github/workflows/test.yml` (integration-graph run block)

**Interfaces introduced** (`src/domain/conversation_engine.py`):

```python
#: ``SessionMessage.message_type`` of the one row ``ChatService.clear_context`` keeps.
#: The deck's engine is read off its earliest role='user' row (role only), so a
#: clear cannot delete that row; this type hides it from every transcript read
#: (``SessionManager.get_messages``, save-point capture), and so from the chat
#: panel, the architect's conversation and the monolith's history.
ENGINE_MODE_MARKER_MESSAGE_TYPE = "engine_mode_marker"


def is_transcript_message(message_type: str | None) -> bool:
    """Whether a persisted chat row belongs to the visible conversation."""
    return message_type != ENGINE_MODE_MARKER_MESSAGE_TYPE
```

- `SessionManager.get_messages`: filter `session.messages` with `is_transcript_message(m.message_type)`
  **before** applying `limit`.
- `SessionManager.create_version`: apply the same filter to the auto-captured `chat_history`
  comprehension (`:2509-2519`).
- Do **not** filter `message_count` (`:816-821`), the duplicate's marker query, or `get_messages_for_request`.
- `clear_context`: after the bulk delete, add `if marker is not None: marker.message_type = ENGINE_MODE_MARKER_MESSAGE_TYPE`.
  Update its docstring: the kept row is re-typed and hidden from transcript reads.

**Unit tests** (`tests/unit/test_clear_context.py`, new class
`TestAClearedConversationIsEmptyToEveryReader`). Use the existing fixtures and `_patched`.

Seed the original transcript rows with a real type: `message_type="user_input"` for user rows and
`"llm_response"` for assistant rows. `session_with_messages` defaults to `None`, and `HUMAN_TYPES`
and `_HUMAN_TYPES` already exclude a `None` row, so the `_conversation` and `_hydrate_chat_history`
tests would then pass before the change, which proves nothing.

- `test_get_messages_returns_nothing_after_a_clear_but_the_marker_row_remains`. After the clear,
  `SessionManager().get_messages(sid) == []`, and the raw query (`_messages_of`) still returns one
  `role="user"` row whose `message_type == ENGINE_MODE_MARKER_MESSAGE_TYPE`.
- `test_messages_written_after_a_clear_are_the_whole_transcript`. Add a user row and an assistant row
  after the clear. `get_messages(sid)` returns exactly those two, in order. `get_messages(sid, limit=1)`
  returns only the assistant row; the hidden row is never counted by `limit`.
- `test_the_architect_conversation_after_a_clear_is_only_new_turns`. Before the clear,
  `src.services.graph.nodes._conversation(sid)` includes the old first prompt. After the clear and one
  new `user_input` row, it is exactly `[{"role": "user", "content": <new>}]`.
- `test_the_monolith_history_after_a_clear_is_only_new_turns`. Run the same scenario through
  `ChatService()._hydrate_chat_history(sid, ChatMessageHistory())`
  (`langchain_community.chat_message_histories`). It returns 1, and the history holds only the new
  `HumanMessage`.
- `test_a_later_legacy_phrase_after_a_clear_does_not_move_a_graph_deck`. Start from a graph deck: its
  first row has no phrase. Clear it, then add a user row containing `LEGACY_MODE_PHRASE`.
  `resolve_engine_mode(sid) == "graph"`. Sabotage: delete the marker → red.
- `test_message_count_still_counts_the_marker`. After the clear, `SessionManager().get_session(sid)["message_count"] == 1`.
- `test_clearing_twice_keeps_the_same_marker`. The second clear returns the same
  `preserved_message_id` and `deleted_messages == 0`, and the row stays hidden.
- `test_a_clear_leaves_every_save_point_untouched`. Before the clear, create two versions with
  `SessionManager().create_version(sid, "v", deck_dict={"title": "t", "slides": []})`. Snapshot each
  version's `(version_number, description, deck_json, chat_history_json, deck_spec_json, created_at)`.
  After the clear, the snapshots are identical.
- `test_a_save_point_taken_after_a_clear_captures_no_marker`. Clear, add one user row, then
  `create_version`. The stored `chat_history_json` decodes to exactly that one row.
- `test_a_duplicate_of_a_cleared_legacy_deck_stays_legacy_and_shows_no_chat`. Start from the fixture
  `session_with_spec_and_messages` with its first row's content set to `LEGACY_MODE_PHRASE …`. Clear,
  then `SessionManager().duplicate_session(sid, "copier@example.com")`. On the new session,
  `resolve_engine_mode(new) == "monolith"` and `get_messages(new) == []`.

**Graph test** (new `tests/integration/test_clear_context_graph_turn.py`, using `graph_turn_env`).
Follow the module-docstring style of `test_graph_orchestration.py`. The probe in Context 4 and 5
established that every assertion below holds once Tasks 1 and 2 are in.

`test_after_a_clear_an_edit_turn_runs_from_the_spec_and_the_committed_rows`:

1. **Turn 1.** Run `env.recorder.configure(slide_count=4)`. Persist the first message through
   `get_session_manager().add_message(sid, "user", "Build me a deck about puffins", message_type="user_input")`,
   then `env.run(initial={"architect_message": <same>})`. Persist a second exchange as well: a user row
   and an `llm_response` row. Record:
   - `rows_before = {p: row.html}`;
   - `spec_before = json.loads(env.deck_row().deck_spec_json)`;
   - that `SqlAlchemyCheckpointSaver(session_factory=env.factory).get_tuple({"configurable": {"thread_id": sid, "checkpoint_ns": ""}})`
     is not None.
2. **Clear.** Patch `src.core.database.get_db_session` with `tests.integration.conftest._make_fake_db(env.factory)`,
   and patch `src.core.checkpointer.get_checkpointer` with `lambda: SqlAlchemyCheckpointSaver(session_factory=env.factory)`.
   Call `ChatService().clear_context(sid, cleared_by="owner@example.com")`. Assert:
   - `get_tuple(...)` is None;
   - `env.messages() == []`;
   - `resolve_engine_mode(sid) == "graph"`. This holds for a graph deck even with no marker, so it is
     not engine-preservation evidence; the legacy-phrase and duplicate unit tests are;
   - `load_conversation_pin(env.factory, sid) == env.graph_release_id`
     (`from src.services.conversation_pins import load_conversation_pin`; it is the read
     `invoke_graph` uses, `builder.py:335`);
   - the deck spec and the rows are unchanged.
3. **Turn 2.**
   - Persist `"Make slide 3 shorter"` as a `user_input` row, the way the chat service does before it
     invokes the graph (`chat_service.py:1155-1165`).
   - Run `env.recorder.reset_observations()` and `configure(slide_count=4, edit_target_positions={2})`.
   - `monkeypatch.setattr(env.recorder, "_skill_builder", …)` with a builder that returns
     `BuilderOutput(position=p, html=f"<div class='slide'><h1>Slide {p}</h1><p>{payload['slide_spec']['content_brief']}</p></div>", scripts="")`.
   - Run `final = env.run(initial={"architect_message": "Make slide 3 shorter"})`.
4. **Architect payload** (`env.recorder.calls_for("architect")[0]["payload"]`):
   - `conversation == [{"role": "user", "content": "Make slide 3 shorter"}]`;
   - `message == "Make slide 3 shorter"`;
   - `current_deck_spec == spec_before`;
   - `committed_slide_count == 4`;
   - `previous_deck_review["digest"] == compute_deck_digest([rows_before[p] for p in sorted(rows_before)])`.
5. **Turn result:**
   - `final["architect_intent"] == "edit"` and `final["error_state"] is None`;
   - `env.recorder.positions("builder") == [2]`, with that builder's brief equal to `edited_brief("brief-2")`;
   - rows 0, 1 and 3 have HTML byte-identical to `rows_before`, and row 2's HTML differs;
   - in the persisted spec, slide 2's brief is `edited_brief("brief-2")` and every other slide equals
     the `spec_before` slide.
6. Do not cite the fixture teardown as pin evidence. `_GraphTurnEnv._turn_state` forces
   `state["graph_release_id"] = self.graph_release_id` (`tests/integration/conftest.py:630-642`), and
   `env.run` never goes through `invoke_graph`'s pin loader, so the teardown check holds even if the
   clear nulled the pin. The `load_conversation_pin` read-back in step 2 is the evidence.

**CI wiring:** add `tests/integration/test_clear_context_graph_turn.py \` to the integration-graph
`pytest` list (`test.yml:428-465`). Without it,
`tests/unit/test_ci_collects_integration_tests.py` fails.

**Steps:**
- [ ] **Step 1 (test author).** Write the tests and confirm they are red for the right reasons:
  - The graph test fails first at `env.messages() == []`, because the marker is returned. With that
    one line commented out, it also fails at `conversation`, because the old prompt is replayed.
    Report both, then restore the line.
  - The `get_messages` tests fail because the marker is returned.

  Leave them uncommitted.
- [ ] **Step 2 (implementer).** Make them green without editing the tests. Add the `test.yml` line.
- [ ] **Step 3.** Run:
  `uv run pytest tests/unit/test_clear_context.py tests/integration/test_clear_context_graph_turn.py tests/integration/test_graph_orchestration.py tests/unit/test_ci_collects_integration_tests.py -q`,
  then the full unit suite with `-n 4`. Compare failure causes.
- [ ] **Step 4.** Sabotage, one at a time:
  - drop the re-type in `clear_context` → the graph test and the `get_messages` tests go red;
  - drop the `get_messages` filter → the panel and `limit` tests go red, while `_conversation` stays
    green because of `_HUMAN_TYPES`;
  - filter `message_count` → `test_message_count_still_counts_the_marker` goes red.
- [ ] **Step 5.** Commit: `fix(sessions): hide the engine-mode marker a clear keeps from every transcript read`.

---

### Task 3: The route: editors only, own conversation only, never mid-turn

**Models:** `test=opus impl=sonnet`

**Files:** `src/api/routes/_authz.py`, `src/api/routes/sessions.py`, `tests/unit/test_clear_context.py`

**Interfaces introduced:**

```python
# src/api/routes/_authz.py
def _require_conversation_creator(session_id: str) -> None:
    """Refuse a change to a session's conversation by anyone but its creator.

    Conversations are private (GET /api/sessions/{id}/messages is creator-only).
    Deck permission resolves on the ROOT session, so a CAN_EDIT gate alone lets
    any editor of a shared deck change the OWNER's (or another contributor's)
    conversation by passing that session's id.  Used by DELETE …/context; #317's
    per-message delete reuses it.

    Raises:
        HTTPException 401: no authenticated user.
        HTTPException 404: unknown session.
        HTTPException 403: the caller did not create this session.
    """
```

It uses the module's existing `get_current_user` and `get_session_manager`.

```python
# src/api/routes/sessions.py, module level
# Any holder of the session lock: a chat turn, or a slide operation (slides.py:187-195).
CONVERSATION_BUSY_DETAIL = (
    "Something is still running on this deck. "
    "Wait for it to finish, then try again."
)
```

`clear_session_context` runs these steps in order:

1. `await asyncio.to_thread(_check_deck_permission_for_session, session_id, PermissionLevel.CAN_EDIT)`.
   This line is unchanged.
2. `await asyncio.to_thread(_require_conversation_creator, session_id)`.
3. `current_user = get_current_user()`, then
   `locked = await asyncio.to_thread(get_session_manager().acquire_session_lock, session_id)`.
   If not locked, raise `HTTPException(409, CONVERSATION_BUSY_DETAIL)` with no release.
4. Inside `try`/`finally`, run the clear with `cleared_by=current_user`. Keep today's 404 and 500
   mapping. Release in `finally`.

Update the route docstring: creator plus CAN_EDIT, 409 while busy, one transaction.

**Tests** (`tests/unit/test_clear_context.py`):

- Fixtures:
  - `allowing_creator` and `refusing_creator` (403) monkeypatch
    `src.api.routes.sessions._require_conversation_creator`.
  - `session_lock` monkeypatches `src.api.routes.sessions.get_session_manager` with a stub whose
    `acquire_session_lock` returns a configurable bool.
  - All three record into one shared ordered `events` list, together with the gate and `stub_service`.
  - Add these fixtures to every existing route test that gets past the deck gate.
- Updated existing tests:
  - `test_a_viewer_is_refused_and_nothing_is_cleared` additionally asserts that the creator gate and
    the lock were never called.
  - `test_the_happy_path_returns_the_services_result` asserts the order is exactly: deck gate,
    creator, acquire, service, release.
  - `test_a_missing_session_is_a_404` and `test_an_unimplemented_saver_surfaces_as_a_500` assert
    that the lock was released once.
- New route tests:
  - `test_an_editor_who_is_not_the_sessions_creator_is_refused`: 403, with no acquire and no service call.
  - `test_a_session_with_a_turn_in_flight_is_a_409_and_nothing_is_cleared`: `acquire` returns False.
    The response is 409 with detail `CONVERSATION_BUSY_DETAIL`. The service is not called and
    **release is not called**.
  - `test_the_route_passes_the_caller_as_cleared_by`: with `DEV_USER_ID=editor@example.com`, the
    service receives `cleared_by="editor@example.com"`.
- New class `TestTheConversationCreatorGate`. Use the `as_user` fixture from `tests/unit/conftest.py`
  and a stub at `src.api.routes._authz.get_session_manager`:
  - `test_the_creator_passes`;
  - `test_another_user_is_a_403`;
  - `test_no_user_is_a_401`: run under `as_user(None)`, or by restoring `set_current_user(None)`;
  - `test_an_unknown_session_is_a_404`: the stub raises `SessionNotFoundError`;
  - `test_a_contributor_session_is_gated_on_the_contributor_not_the_owner`. Take session info
    `{created_by: "contributor@example.com", is_contributor_session: True, parent_session_id: "owner"}`.
    The contributor passes and the owner gets 403.

**Steps:**
- [ ] **Step 1 (test author).** Write the tests and confirm they fail for the right reasons: the gate
  is missing, the lock is missing, and the order is wrong. Leave them uncommitted.
- [ ] **Step 2 (implementer).** Make them green without editing the tests.
- [ ] **Step 3.** Run `uv run pytest tests/unit/test_clear_context.py -q`, then the full unit suite
  with `-n 4`, and compare failure causes.
- [ ] **Step 4.** Sabotage, one at a time:
  - swap the creator gate and the lock;
  - release in the 409 branch;
  - compare `created_by` against `parent_session_id`.

  Each must turn a named test red.
- [ ] **Step 5.** Commit: `fix(sessions): gate clearing a conversation on its creator and refuse it mid-turn`.

---

### Task 4: Frontend conversation API client and permission helper

**Models:** `test=opus impl=haiku`. The plan gives the code.

**Files (all new):** `frontend/src/api/conversation.ts`, `frontend/src/api/conversation.test.ts`,
`frontend/src/utils/conversationPermissions.ts`, `frontend/src/utils/conversationPermissions.test.ts`

`conversation.ts` imports `ApiError` from `../services/api`. Some tests mock `../../services/api` with
a factory that has no `ApiError`, for example `ChatPanel.tourRefresh.test.tsx`. They are expected to
be unaffected, because none of them triggers a failed clear and vitest's transformed imports read a
mocked export only where it is used. If such a test fails with `No "ApiError" export is defined on the
mock`, add `ApiError` to that mock through `importOriginal`. Do not weaken the test.

```ts
// frontend/src/api/conversation.ts
/**
 * Conversation API: calls that change a session's CONVERSATION, never its deck.
 * Clear chat (#323) lives here; #317 (delete a message) adds its call beside it.
 * Errors are the app's existing ApiError (services/api.ts), so #317 reuses one type.
 */
import { ApiError } from '../services/api';

const API_BASE_URL = import.meta.env.VITE_API_URL || (
  import.meta.env.MODE === 'production' ? '' : 'http://127.0.0.1:8000'
);

export interface ClearChatResult {
  status: 'cleared';
  session_id: string;
  deleted_messages: number;
  preserved_message_id: number | null;
}

async function errorFrom(response: Response, fallback: string): Promise<ApiError> {
  let message = fallback;
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (typeof detail === 'string' && detail) message = detail;
    else if (detail && typeof detail.message === 'string') message = detail.message;
  } catch {
    // Non-JSON body: keep the fallback.
  }
  return new ApiError(response.status, message);
}

export const conversationApi = {
  /** DELETE /api/sessions/{id}/context: clears THIS session's conversation only. */
  async clearChat(sessionId: string): Promise<ClearChatResult> {
    const response = await fetch(
      `${API_BASE_URL}/api/sessions/${encodeURIComponent(sessionId)}/context`,
      { method: 'DELETE' },
    );
    if (!response.ok) throw await errorFrom(response, 'Failed to clear the chat');
    return response.json();
  },
};
```

```ts
// frontend/src/utils/conversationPermissions.ts
/** Whether the caller may change their own conversation on this deck (clear it; #317: delete a message). */
export function canEditConversation(permission: string | null | undefined): boolean {
  return permission === 'CAN_EDIT' || permission === 'CAN_MANAGE';
}
```

**Tests:**

- `conversationPermissions.test.ts`:
  - `CAN_EDIT` and `CAN_MANAGE` return true;
  - `CAN_VIEW`, `CAN_USE`, `null`, `undefined`, `''` and `'can_edit'` return false.
- `conversation.test.ts`. Stub `fetch` with `vi.stubGlobal`, as `src/services/__tests__/chat503.test.ts`
  does:
  - `clearChat('sess-1')` calls `fetch` once, with a URL ending `/api/sessions/sess-1/context` and
    `method: 'DELETE'`, and resolves to the parsed body;
  - a 409 with `{detail: 'busy'}` rejects with an `ApiError` (imported from `src/services/api.ts`,
    `export class ApiError` at `:16-24`, `constructor(status: number, message: string)`), `status 409`
    and `message 'busy'`;
  - a 403 with `{detail: {message: 'nope'}}` rejects with message `'nope'`;
  - a 500 with a non-JSON body rejects with message `'Failed to clear the chat'`.

**Steps:**
- [ ] **Step 1 (test author).** Write the tests. They fail on the missing modules.
- [ ] **Step 2 (implementer).** Write the code above.
- [ ] **Step 3.** Run `cd frontend && npx vitest run src/api/conversation.test.ts src/utils/conversationPermissions.test.ts && npm run build`.
  Then apply the lint gate: `npx eslint src/api/conversation.ts src/api/conversation.test.ts src/utils/conversationPermissions.ts src/utils/conversationPermissions.test.ts`
  shows no finding absent from `baseline-fe-lint.txt`. These are new files, so it must be clean.
- [ ] **Step 4.** Sabotage: make `canEditConversation` also accept `CAN_VIEW`, and send `POST`
  instead of `DELETE`. Each must go red.
- [ ] **Step 5.** Commit: `feat(frontend): add the conversation API client and edit-permission helper`.

---

### Task 5: The Clear chat action in the chat panel

**Models:** `test=opus impl=sonnet`

**Files:**
- **new** `frontend/src/components/ChatPanel/clearChatCopy.ts`
- `frontend/src/components/ChatPanel/ChatPanel.tsx`
- `frontend/src/components/Layout/AppLayout.tsx` (one prop)
- **new** `frontend/src/components/ChatPanel/ChatPanel.clearChat.test.tsx`

**`clearChatCopy.ts`** exports the D8 strings as `CLEAR_CHAT_LABEL`, `CLEAR_CHAT_DIALOG_TITLE`,
`CLEAR_CHAT_DIALOG_MESSAGE`, `CLEAR_CHAT_TOOLTIP`, `CLEAR_CHAT_BUSY`, `CLEAR_CHAT_FORBIDDEN` and
`CLEAR_CHAT_FAILED`. It also exports this function:

```ts
export function clearChatErrorMessage(err: unknown): string {
  // Duck-typed on `status`, not `instanceof`, so a test that mocks the API module still maps correctly.
  const status = typeof err === 'object' && err !== null && 'status' in err
    ? (err as { status: unknown }).status : undefined;
  if (status === 409) return CLEAR_CHAT_BUSY;
  if (status === 403) return CLEAR_CHAT_FORBIDDEN;
  return CLEAR_CHAT_FAILED;
}
```

**`ChatPanel.tsx` changes** (keep them local to these places):

- **Prop:** `hasDeckSpec?: boolean`, default `false`, with a comment noting the action is offered only
  where a Spec exists to continue from.
- **New state:**
  - `myPermission: string | null`;
  - `isClearChatDialogOpen: boolean`;
  - `isClearing: boolean`.
- **Reset on session switch.** Inside the existing synchronous reset block (`:66-70`), also call
  `setMyPermission(null)`, `setIsClearChatDialogOpen(false)` and `setIsClearing(false)`. Without the
  last one, switching decks while a clear is pending leaves the new session's input disabled until the
  old request settles (review F12).
- **Permission from the session load.** In `loadSessionMessages`, after the `isStale()` check, call
  `setMyPermission(session.my_permission ?? null)`. In its `catch`, after the `isStale()` check, call
  `setMyPermission(null)`.
- **Stale-guard the initial load (review F12).** The mount effect (`:130-134`) currently calls
  `loadSessionMessages(sessionId)` with no `isStale`. Change it to
  `loadSessionMessages(sessionId, () => currentSessionIdRef.current !== sessionId)`, so a slow
  response for the old session cannot set its messages or `my_permission` on the new one.
- **Permission for a deck built in this panel (review F2).** A new deck's first load targets the
  browser-local id, gets a 404 and leaves `myPermission` null. `ensureGraphCapableRoot` then persists
  the same id and calls `markSessionPersisted()` (`AppLayout.tsx:632-641`, `SessionContext.tsx:99-101`),
  so `sessionId` never changes and nothing reloads the permission. Without this effect the button never
  appears on a deck built in the current tab until a reload. Keep it separate from the transcript load,
  so test 7's "`getSession` called once" still holds:

```tsx
const wasPersistedRef = useRef(isSessionPersisted);
useEffect(() => {
  const becamePersisted = !wasPersistedRef.current && isSessionPersisted;
  wasPersistedRef.current = isSessionPersisted;
  if (!becamePersisted || !sessionId) return;
  const target = sessionId;
  api.getSession(target)
    .then(s => { if (currentSessionIdRef.current === target) setMyPermission(s.my_permission ?? null); })
    .catch(() => { /* keep null: the button stays hidden, and the backend still gates */ });
}, [isSessionPersisted, sessionId]);
```
- **Visibility and enablement:**
  - `showClearChat = isSessionPersisted && hasDeckSpec && canEditConversation(myPermission)`;
  - `clearChatDisabled = isLoading || isClearing || disabled || !!previewMessages || messages.length === 0`.
- **Send guard:** `handleSendMessage` returns early when `isClearing`.
- **The confirm handler:**

```tsx
const handleConfirmClearChat = async () => {
  if (!sessionId || isClearing) return;
  const target = sessionId;
  setIsClearChatDialogOpen(false);
  setIsClearing(true);
  setError(null);
  try {
    await conversationApi.clearChat(target);
    if (currentSessionIdRef.current !== target) return;  // the user moved on; leave the new session alone
    setMessages([]);
    setLastReplacement(null);
  } catch (err) {
    if (currentSessionIdRef.current !== target) return;
    setError(clearChatErrorMessage(err));
  } finally {
    setIsClearing(false);
  }
};
```

  It must not call `onSlidesGenerated`, `api.getSlides`, `api.getSession` or `refreshConfig`. The
  deck and the Spec are deliberately left untouched.
- **Header JSX** (`:389-397`): after the `flex-1` title block, render when `showClearChat`:
  `<Button data-testid="clear-chat-button" size="sm" variant="ghost" disabled={clearChatDisabled} title={CLEAR_CHAT_TOOLTIP} onClick={() => setIsClearChatDialogOpen(true)}><Eraser />{CLEAR_CHAT_LABEL}</Button>`.
  Also render
  `<ConfirmDialog open={isClearChatDialogOpen} title={CLEAR_CHAT_DIALOG_TITLE} message={CLEAR_CHAT_DIALOG_MESSAGE} confirmLabel={CLEAR_CHAT_LABEL} cancelLabel="Cancel" variant="danger" onConfirm={handleConfirmClearChat} onCancel={() => setIsClearChatDialogOpen(false)} />`.
- **Input:** the `ChatInput` disabled condition also includes `isClearing`. Put that term on its own
  line of the `disabled` expression (`:411`) and do not touch `placeholder`. This element is the
  likeliest merge conflict with #319.

**AppLayout:** on the `<ChatPanel>` element (`:1236-1269`), add `hasDeckSpec={!!slideDeck?.deck_spec}`.
Use the live `slideDeck`, not `displayDeck`.

**Tests** (`ChatPanel.clearChat.test.tsx`). Copy the mock scaffold of `ChatPanel.tourRefresh.test.tsx`:
`api.getSession`, `SessionContext`, `AgentConfigContext` and `GenerationContext`. Also:
- add `api.sendChatMessage: vi.fn(() => () => {})` and `api.getSlides: vi.fn()`;
- mock `../../api/conversation` as `{ conversationApi: { clearChat } }`;
- mock `MessageList` to render one `<li>` per message;
- mock `ChatInput` as `({ onSend, disabled }) => <button data-testid="mock-send" disabled={disabled} onClick={() => onSend('Make slide 3 shorter')}>send</button>`.

`getSession` resolves `{ messages: [two msgs], my_permission: 'CAN_MANAGE' }` unless a test says
otherwise. Render with `hasDeckSpec`.

Tests:
1. `it.each(['CAN_EDIT', 'CAN_MANAGE'])` `offers Clear chat to an editor (%s) on a deck with a Spec`.
2. `does not offer Clear chat to a viewer, without a permission, without a Spec, or before the session is persisted`.
   These are four cases.
3. `disables Clear chat when there is nothing to clear` (`messages: []`).
4. `disables Clear chat while a turn is in flight`: click `mock-send`, and the button is disabled.
5. `disables Clear chat in a read-only or preview panel`: `disabled` prop true, and separately a
   non-null `previewMessages`.
6. `cancelling the confirmation clears nothing`: the dialog shows `CLEAR_CHAT_DIALOG_MESSAGE`. Cancel
   closes it, `clearChat` is not called, and both messages remain.
7. `confirming clears the panel through the API for this session only`:
   - `clearChat` is called once with `'sess-1'`;
   - the list is empty;
   - `getSession` is still called only once and `api.getSlides` is never called, so there is no refetch;
   - the `onSlidesGenerated` spy is never called.
8. `a busy session keeps the conversation and says why`: `clearChat` rejects with `{status: 409}`.
   `CLEAR_CHAT_BUSY` is shown, both messages remain, and the button is enabled again.
9. `any other failure keeps the conversation and a retry works`: 500 shows `CLEAR_CHAT_FAILED`, and
   the second confirm empties the panel.
10. `input is disabled and the clear cannot double-submit while it runs`: `clearChat` returns a pending
    promise. `mock-send` is disabled, and `clearChat` was called once.
11. `a clear that lands after the session changed leaves the new session alone`: resolve the pending
    clear after a rerender with a new `sessionId`. Before it resolves, `mock-send` is already enabled
    on the new session. After it resolves, the new session's messages remain.
12. `a deck built in this panel offers Clear chat without a reload`:
    1. Mount with `isSessionPersisted=false` and `getSession` rejecting `{status: 404}`.
    2. Re-render with `isSessionPersisted=true`, `getSession` resolving `my_permission: 'CAN_MANAGE'`,
       and `hasDeckSpec=true`.
    3. The button is visible.

Every confirm click is scoped to the dialog, because the header button and the dialog's confirm
button share the name "Clear chat": `within(screen.getByTestId('confirm-dialog')).getByRole('button', { name: 'Clear chat' })`.

**Steps:**
- [ ] **Step 1 (test author).** Write the tests and confirm they are red (no button). Leave them uncommitted.
- [ ] **Step 2 (implementer).** Make them green without editing the tests.
- [ ] **Step 3.** Run `cd frontend && npm run test:unit && npm run build`.
  - Vitest gate: the failure-cause set equals the baseline (the Node 26 `localStorage` cause only).
    `ChatPanel.tourRefresh.test.tsx`, `slideReadyEvent.test.ts` and `AppLayoutSpecToggle.test.ts` must
    stay green.
  - Lint gate: `npx eslint src/components/ChatPanel/ChatPanel.tsx src/components/ChatPanel/clearChatCopy.ts src/components/ChatPanel/ChatPanel.clearChat.test.tsx src/components/Layout/AppLayout.tsx`
    shows no finding absent from `baseline-fe-lint.txt`, compared by file, rule and message.
- [ ] **Step 4.** Sabotage, one at a time:
  - remove the stale-session guard (test 11 goes red);
  - call `api.getSlides` after the clear (test 7 goes red);
  - drop `canEditConversation` from `showClearChat` (test 2 goes red);
  - delete the became-persisted effect (test 12 goes red);
  - drop `setIsClearing(false)` from the reset block (test 11 goes red).
- [ ] **Step 5.** Commit: `feat(chat): clear the chat on a deck, keeping the deck, its Spec and save points`.

---

### Task 6: E2E with a mocked backend (`clear-chat.spec.ts`)

**Models:** `test=opus impl=sonnet`. A red result usually means a mount or timing bug in Task 5, and
fixing it needs judgement. Never loosen the spec to get a pass. A stop escalates straight to opus.

**Files:** **new** `frontend/tests/e2e/clear-chat.spec.ts`, `.github/workflows/test.yml` (matrix)

**Harness:**
- Use `test`/`expect` from `../fixtures/base-test`, `setupMocks`, `mockSessionWithSlides`,
  `mockSessionDetail`, `mockSlidesResponse` and `TEST_SESSION_ID` from `../helpers/session-helpers`,
  and `apiPath` from `../helpers/api-route`. Follow the setup of `spec-view.spec.ts:209-226`.
- Register every route below **after** `setupMocks` and `mockSessionWithSlides`, so the last
  registration wins.

**Mocked routes**, all through a `mockClearableDeck(page, { myPermission, isContributor? })` helper
that returns a recorder:
- **Session detail.** `GET` on `apiPath('/api/sessions/' + TEST_SESSION_ID)` returns
  `{...mockSessionDetail, my_permission, is_contributor_session, parent_session_id: isContributor ? 'owner-session-id' : null, graph_version: 1, active_graph_version: 1, is_older_than_active: false, messages: state.cleared ? [] : TRANSCRIPT}`.
  `TRANSCRIPT` holds four rows: user `'Build a deck about cloud adoption'`, assistant
  `'Building 3 slide(s).'`, user `'Make the title punchier'`, assistant `'Edited slide 1.'`. Other
  methods call `route.fallback()`.
- **Clear.** `DELETE` on `apiPath('/api/sessions/' + TEST_SESSION_ID + '/context')` records the
  pathname, sets `state.cleared = true`, and answers 200
  `{status: 'cleared', session_id, deleted_messages: 3, preserved_message_id: 1}`.
- **Tripwire.** `apiPathMatching(/^\/api\/sessions\/owner-session-id\/context$/)` records into a
  separate array that must stay empty.
- **Slides.** `GET` on `apiPath('/api/sessions/' + TEST_SESSION_ID + '/slides')` counts calls and
  serves `{...mockSlidesResponse, slide_deck: {...mockSlidesResponse.slide_deck, deck_spec: DECK_SPEC, slides: state.slides}}`.
  `DECK_SPEC` is a valid 3-slide spec; copy the shape of `spec-view.spec.ts:58-100`. `state.slides`
  can be swapped mid-test.
- **Contributors.** `apiPath('/api/sessions/' + TEST_SESSION_ID + '/contributors')` answers
  `{contributors: []}`, so the editing lock is granted.
- **Save points.** `'**/api/slides/versions?**'` answers
  `{versions: [{version_number: 1, description: 'Generated 3 slide(s)', created_at, slide_count: 3}], current_version: 1}`.

**Tests:**
1. `an owner clears the chat; slides, Spec, save points and pin are unchanged; a reload stays empty`.
   Use `CAN_MANAGE`.
   - Before the clear, record: the `graph-version-status` text, the save-point trigger text
     (`page.getByTitle('Save Points')`), the slides-GET count, and the Spec's `spec-audience` text
     (shown via `view-toggle-spec`, then return to Slides).
   - Click `clear-chat-button`. `confirm-dialog` is visible with the D8 message. Click the confirm
     button scoped to the dialog:
     `page.getByTestId('confirm-dialog').getByRole('button', { name: 'Clear chat' })`. An unscoped
     `getByRole('button', { name: 'Clear chat' })` is a strict-mode violation, because the header
     button has the same name.
   - Then:
     - `chat-welcome` is visible;
     - no transcript text remains inside `chat-panel`;
     - exactly one DELETE was made, to this session's `/context`;
     - the slides-GET count, the `graph-version-status` text and the save-point trigger text are
       unchanged;
     - `ribbon-thumb-0`, `-1` and `-2` are still present;
     - `view-toggle-spec` shows the same `spec-audience`.
   - `page.reload()`. `chat-welcome` is visible again and no transcript text has come back.
2. `after clearing, an edit turn shows only the new conversation and changes only slide 3`.
   - Clear as in test 1.
   - Set `state.slides` to the same three slides with slide 3's HTML replaced by
     `<div class="slide-container"><h1>Key Benefits (short)</h1></div>`.
   - Route `apiPath('/api/chat/stream')` to an SSE body:
     `assistant` "Editing slide 3." then `complete` carrying the new deck. Use the format at
     `spec-view.spec.ts:280-286`.
   - Fill `chat-input` with `Make slide 3 shorter` and send.
   - Assert:
     - the stream request body has `message === 'Make slide 3 shorter'` and this session's `session_id`;
     - the chat panel shows exactly the new user message and "Editing slide 3." and none of the old
       transcript;
     - clicking `ribbon-thumb-2`, the `slide-stage-frame` frame contains "Key Benefits (short)";
     - `ribbon-thumb-0` and `-1` still show "Benefits of Cloud Computing" and "Cost Savings Drive
       Cloud Adoption". Use the frame pattern at `incremental-slide-delivery.spec.ts:244-251`.
3. `a contributor with edit rights clears their own session, never the owner's`. Use `CAN_EDIT` with
   `isContributor`. The DELETE goes to `TEST_SESSION_ID`, and the tripwire array stays empty. This is a
   **regression tripwire**, not evidence for D3: the handler sends the `sessionId` from `useSession`,
   so the tripwire fires only after a contrived code change. D3's proof is Task 3's creator-gate tests.
4. `a viewer is not offered Clear chat`. Use `CAN_VIEW`. `clear-chat-button` has count 0.
5. `Clear chat is disabled while a reply is being generated`.
   - Hold the stream route on a promise that the test releases.
   - Send a message, then assert `clear-chat-button` is disabled.
   - Release the stream and wait for the assistant message, then assert the button is enabled.
6. `cancelling the dialog clears nothing`. Cancel the dialog. No DELETE is made and the transcript
   is still visible.

**CI wiring:** add `- clear-chat` to the e2e matrix after `- chat-ui` (`test.yml:697`).
`tests/unit/test_e2e_matrix_covers_specs.py` fails without it.

**Steps:**
- [ ] **Step 1.** Write the spec and add the matrix entry.
- [ ] **Step 2.** If ports 3000 **and** 8000 are both free (pre-pass check), run
  `cd frontend && npx playwright test tests/e2e/clear-chat.spec.ts --project=chromium --workers=1`.
  If either is taken, do not run it locally; CI runs it. Read every failure for its cause, then fix the
  real cause in Task 5's code.
- [ ] **Step 3.** Run `uv run pytest tests/unit/test_e2e_matrix_covers_specs.py -q`.
- [ ] **Step 4.** Sabotage, where the local run is possible: make the handler refetch `getSlides`
  (test 1 goes red), and send the parent session id for contributors (test 3 goes red).
- [ ] **Step 5.** Commit: `test(e2e): clear the chat on a deck, then edit it`.

---

### Task 7: Full-stack route test for clear chat (`tests/integration/test_clear_chat_routes.py`)

**Models:** `test=opus impl=sonnet`. This task mostly adds a test of code that Tasks 1 to 3 already
built. The implementer tier only fixes real defects the test exposes. A stop escalates straight to opus.

**Why this test exists (review F1).** It replaces a real-backend Playwright spec. That spec could not
run in CI: the e2e backend's `DATABRICKS_HOST` puts identity in WORKSPACE mode, and reading a deck
with slide rows then hangs on SCIM display-name lookups. This test drives the real FastAPI routes,
services and database through TestClient. It runs locally and in integration-general.

**Files:** **new** `tests/integration/test_clear_chat_routes.py`; `.github/workflows/test.yml`
(integration-general run block)

**Harness.** Model it on `tests/integration/test_savepoint_e2e.py`.

- **Database.** A file-backed SQLite engine from `tests.integration.conftest._make_graph_engine(str(tmp_path / "routes.db"))`.
  It uses ordinary pooling and builds `create_all` plus `_run_migrations`, so the checkpoint tables
  exist. Add `_make_factory(engine)` and `bootstrap_graph_configuration(factory)`.
- **Singletons.** Reset `src.api.services.chat_service._chat_service_instance` and
  `src.api.services.session_manager._session_manager` per test, as `test_savepoint_e2e.py:155-166` does.
- **Patch `get_db_session`** with `_make_fake_db(factory)` at every target the paths use:
  - `src.core.database.get_db_session` (the lazy imports in `chat_service`, including `clear_context`);
  - `src.api.services.session_manager.get_db_session`;
  - `src.api.services.slide_repository.get_db_session`;
  - `src.api.services.deck_level_writer.get_db_session`;
  - `src.api.routes._authz.get_db_session`;
  - `src.api.routes.sessions.get_db_session`.

  Also override `app.dependency_overrides[get_db]` with a generator over `factory()`, and clear the
  overrides on teardown.
- **Checkpointer:** patch `src.core.checkpointer.get_checkpointer` with
  `lambda: SqlAlchemyCheckpointSaver(session_factory=factory)`.
- **Display names:** neutralise them as `graph_turn_env` does (`tests/integration/conftest.py:821-823`),
  by patching `src.services.identity_provider.resolve_display_names` with `lambda emails: {}`.
- **Identity:** `OWNER = "owner@example.com"`.
  - `monkeypatch.setenv("DEV_USER_ID", OWNER)`. The auth middleware reads it per request, so every
    route's `get_current_user()` is the creator.
  - Patch `src.api.routes._authz.get_permission_context` with
    `return_value=PermissionContext(user_name=OWNER)`, as `test_savepoint_e2e.py:183-188` does.
- **Seed** with the tour helpers, called directly: `sid = _phase1_create_session(OWNER)["session_id"]`,
  then `_run_stage(sid, "plan", OWNER)` and `_run_stage(sid, "build", OWNER)` (`src/api/routes/tour.py`).
  This gives a pinned graph deck with a spec, three verified slides and two chat rows: the
  `chat_prompt` (`message_type="chat"`) and the plan reply.
- Use `with TestClient(app) as client:` for every request.

**The planner ran this harness against today's code** (probe, 2026-10-19), with a stub saver
because today's clear deadlocks on file SQLite. Seeding, save-point create and preview, `DELETE /context`,
and the review and edit stages all returned 200 in 0.8 s, with no SCIM call. Today
`GET /sessions/{sid}` still returns the prompt after the clear, so the test below fails for the right
reason until Task 2 lands.

**Test** `test_a_cleared_chat_reads_back_empty_and_the_next_scripted_turn_shows_only_new_rows`:

1. **Before the clear:**
   - `GET /api/sessions/{sid}`: record `graph_version` and assert the messages include the fixture's
     `chat_prompt`. Read the fixture through `src.api.routes.tour._load_fixture()`.
   - `GET /api/sessions/{sid}/slides`: record each slide's `html` and the `deck_spec`.
   - **A real save point (review F10).** `POST /api/slides/versions/create` with
     `{"session_id": sid, "description": "before clear"}` answers 200 with `version_number`. It calls
     `ChatService.create_save_point`, which captures the chat. Then read
     `GET /api/slides/versions/{n}?session_id={sid}` and record its `chat_history`. It contains the
     `chat_prompt`.
2. **Clear:** `DELETE /api/sessions/{sid}/context` answers 200.
3. **After the clear:**
   - `GET /api/sessions/{sid}` has `messages == []` and the same `graph_version`;
   - `GET /api/sessions/{sid}/messages` has `messages == []` and `count == 0`;
   - `GET /api/sessions/{sid}/slides` has the same slide HTML and a deep-equal `deck_spec`;
   - the save point's preview `chat_history` is deep-equal to the recorded one. Previews keep their
     chat (D9);
   - `load_conversation_pin(factory, sid)` is unchanged;
   - one `UsageEvent` row in `factory()` has `event_type == "context_cleared"` and
     `username == OWNER`.
4. **A scripted post-clear turn (review F3).** This is the tour's own script, not an architect turn.
   - `POST /api/tour/demo-deck/{sid}/stages/review` answers 200, then `POST …/stages/edit` answers 200.
     Both still run after a clear, because `_applied_stages` derives `build` from the deck
     (`tour.py:99-124`).
   - `GET /api/sessions/{sid}` messages' contents are exactly
     `[stages.review.advisory, stages.edit.user_prompt, stages.edit.architect_reply]`, with no
     `chat_prompt` and no plan reply.
   - In the `deck_spec` from `GET /api/sessions/{sid}/slides`, only the slide at
     `stages.edit.position` (1) differs from the recorded spec, and its `content_brief` equals
     `stages.edit.content_brief`.
   - Slide 1's HTML changed. The other slides' HTML is unchanged, which is trivially true because the
     fixture rewrites them byte for byte, so do not count it as evidence.
5. Label the test's docstring honestly. It is a **scripted** turn with no architect and no model: it
   proves the backend reads, writes and serves a cleared conversation correctly, and nothing about
   what a model receives. The graph test (Task 2) is the architect evidence.

**CI wiring:** add `tests/integration/test_clear_chat_routes.py \` to the integration-general
`pytest` list (`test.yml:551-563`), alphabetically before `test_comments_removed.py`. That job is
TestClient plus SQLite with `DATABRICKS_HOST: ""`, which keeps identity LOCAL, and it already runs
`test_savepoint_e2e.py`. This test needs nothing else: no Postgres and no graph harness.
`tests/unit/test_ci_collects_integration_tests.py` fails if the file is not named in a job.

**Steps:**
- [ ] **Step 1 (test author).** Write the test. If it is written after Tasks 1 to 3, it should be
  green. Prove it can fail with the sabotage in Step 4. Leave it uncommitted.
- [ ] **Step 2.** Add the CI line.
- [ ] **Step 3.** Run
  `DATABRICKS_HOST= DATABRICKS_TOKEN= uv run pytest tests/integration/test_clear_chat_routes.py tests/integration/test_savepoint_e2e.py tests/unit/test_ci_collects_integration_tests.py -q`.
- [ ] **Step 4.** Sabotage, one at a time:
  - drop the `get_messages` filter (step 3's `messages == []` goes red);
  - drop the re-type in `clear_context` (red at step 3 and at step 4's exact-rows check);
  - make `clear_context` delete `SlideDeckVersion` rows (the preview check goes red).
- [ ] **Step 5.** Commit: `test(sessions): clear chat end to end through the real routes`.

---

### Task 8: Docs and the in-app Help page

**Models:** `test=sonnet impl=sonnet`. The "test" is a claims check: the reviewer verifies every
sentence against the code from Tasks 1 to 5.

**Files and content:**
- **`docs/user-guide/01-generating-slides.md`.** Add a section `## Clearing the Chat` after "Iterating
  on Your Slides". It covers:
  - where the button is;
  - the confirmation;
  - what is kept: slides, Spec, save points, Graph Version;
  - that the assistant carries on from the Spec and the current slides, so you can say "make slide 3
    shorter";
  - that it is offered only on decks with a Spec, and only when you can edit;
  - that save points keep the chat they were saved with;
  - that it can't be undone.
- **`docs/user-guide/08-profile-sharing-permissions.md`.**
  - CAN EDIT: "Clear your own chat on the deck (never the owner's or anyone else's)".
  - CAN VIEW, "What you CANNOT do": "Clear the chat".
- **`docs/technical/permissions-model.md`.**
  - Add a "Clear chat" row to the Conversation Privacy table: Session Creator ✅ with CAN_EDIT or
    above; Any Contributor ❌ (they clear only their own contributor session).
  - Add `DELETE /api/sessions/{id}/context` to the Sessions route list.
- **`docs/technical/backend-overview.md`.**
  - Add a Session Messages Endpoints row for `DELETE /api/sessions/{id}/context`: creator plus
    CAN_EDIT, 409 while a turn runs, one transaction, keeps deck/spec/save points/pin, writes
    `context_cleared`. Handler: `routes/sessions.clear_session_context`.
  - In the Contributor Sessions section, add that a clear affects only the caller's own session.
- **`docs/technical/usage-analytics.md`.**
  - Add `context_cleared` to the event table. Write site: `ChatService.clear_context`, **in the
    clear's own transaction, not fire-and-forget**. Never deduped. `session_id` = the cleared session.
  - Add it to the constants list and the "Write-path guarantees" section.
- **`docs/technical/save-points-versioning.md` §9.** Clearing does not touch save points, so their
  previews still show the chat they captured. The kept engine-mode row is never captured by a new
  save point. A restore deletes this session's rows created after the save point. The kept row
  survives whenever it predates that save point, which is always true for a root deck's own first
  turn. A contributor's kept row can be removed by a restore, which is harmless: the deck's engine
  resolves on the owner's rows.
- **`docs/technical/multi-user-concurrency.md`.** "Session endpoints … do not require locking" gains
  the exception `DELETE /api/sessions/{id}/context`, which takes the session lock and answers 409 while
  a turn runs.
- **`docs/technical/frontend-overview.md`.**
  - In the ChatPanel row of the component table, add Clear chat and `conversationApi.clearChat`.
  - Add a subsection "Conversation API (`src/api/conversation.ts`)" beside "Configuration API".
- **`docs/technical/real-time-streaming.md`.** In the `session_messages` table's `message_type` row
  (`:507`), add `engine_mode_marker`: the one row a clear keeps, hidden from every transcript read.
- **`docs/technical/mcp-server.md`.** In `get_deck_status` (§5.2), add one sentence: after a clear, a
  poll for the deck's first request can return the kept row with `message_type: "engine_mode_marker"`.
- **`frontend/src/components/Help/HelpPage.tsx`.** Add one `<li>` to "Chat Panel (Left)":
  "**Clear chat** (top of the panel) deletes your conversation and keeps the deck, its Spec and save
  points".

**Steps:**
- [ ] **Step 1.** Write the docs.
- [ ] **Step 2.** The reviewer checks every claim against the code, especially the 409, the creator
  gate and "save point previews show the old chat".
- [ ] **Step 3.** Run `cd frontend && npm run build`. Apply the lint gate:
  `npx eslint src/components/Help/HelpPage.tsx` shows no finding absent from `baseline-fe-lint.txt`.
  Run `npx playwright test tests/e2e/help-ui.spec.ts` only if ports 3000 and 8000 are both free.
- [ ] **Step 4.** Commit: `docs: clear chat on a deck`.

---

### Task 9: Verification and whole-branch review

**Models:** `test=opus impl=opus` (controller). The whole-branch review is always opus (skill §7).

- [ ] **Backend:** run `uv run pytest tests/unit -q -n 4` and
  `DATABRICKS_HOST= DATABRICKS_TOKEN= uv run pytest tests/integration/test_clear_context_graph_turn.py tests/integration/test_clear_chat_routes.py tests/integration/test_savepoint_e2e.py tests/integration/test_graph_orchestration.py tests/integration/test_spec_row_alignment.py tests/integration/test_sweeper_describe_only.py -q`.
  The failure-cause set must equal the baseline. The Task 1 `postgres` test skips locally, which is
  expected; CI's unit job runs it.
- [ ] **Frontend:** run `cd frontend && npm run test:unit && npm run build`.
  - Vitest gate: the failure-cause set equals the baseline (the Node 26 `localStorage` cause only).
  - Lint gate: `npx eslint` over every frontend file the branch touched shows no finding absent from
    `baseline-fe-lint.txt`.
- [ ] **CI guards:** run
  `uv run pytest tests/unit/test_ci_collects_integration_tests.py tests/unit/test_e2e_matrix_covers_specs.py tests/unit/test_ci_exports_postgres_test_url.py -q`.
- [ ] **Sabotage:** re-run every sabotage listed in Tasks 1 to 7, with targets for the controller and
  the reviewer kept apart.
- [ ] **Whole-branch review** on opus, with the `tellr-code-review` checklist (multi-worker in-process
  state). Ask for:
  - one row per transcript reader saying filtered or deliberately not filtered, checked against
    Context 3's table (Review focus 2);
  - a ruling on the transaction boundary;
  - a scan for any payload, prompt or schema diff;
  - a merge / no-merge verdict.
- [ ] **Hand-off notes for the user:**
  - **No e2e runs a real architect turn after a clear.** CI has no model. The graph test is the only
    evidence for A2's backend half. `clear-chat.spec.ts` proves the UI journey with a scripted stream,
    and `test_clear_chat_routes.py` proves the backend with a scripted tour turn.
  - Which checks ran only in CI: the Task 1 `postgres` test, and `clear-chat.spec.ts` if ports
    3000/8000 were taken locally.
  - The follow-ups under "Out of scope", including the rejected real-backend e2e option that needs
    the user's ruling, and the `ask_data` `deck_purpose` follow-up for the PR description.

---

## Extension points for #317 (delete a message / reset the chat)

- **The "reset the chat" half of #317 is this feature.** It uses `DELETE /api/sessions/{id}/context`
  and `conversationApi.clearChat` with no new backend.
- **Backend gate.** `_require_conversation_creator(session_id)` (`_authz.py`), together with
  `_check_deck_permission_for_session(..., CAN_EDIT)`, is the full permission check a per-message
  delete route needs. `CONVERSATION_BUSY_DETAIL` and the "acquire, 409, release only if acquired"
  pattern from `clear_session_context` carry over too.
- **The hidden row.** `ENGINE_MODE_MARKER_MESSAGE_TYPE` and `is_transcript_message()` live in
  `src/domain/conversation_engine.py`. A per-message delete must treat the kept row as not found
  (404): deleting it would change the deck's engine.
- **The real trap: never delete a session's earliest `role='user'` row (whole-branch review W3).**
  On a session that was never cleared, the engine-mode row is the earliest user row with its
  normal type (`user_input`/`user_query`/`chat`), visible in the panel, so it will carry a delete
  affordance. Deleting it moves a legacy deck to the graph, and on a graph deck it lets a later
  `USE LEGACY MODE` message become the earliest row. "Deleting" that row must instead re-type it to
  `ENGINE_MODE_MARKER_MESSAGE_TYPE` (hide it), exactly as `clear_context` does. The "earliest user
  row" query already has four copies (`resolve_engine_mode`, `clear_context`, the duplicate carry
  in `session_manager.py`, the pin backfill in `conversation_pins.py`); #317 should extract one
  shared helper rather than add a fifth.
- **Reading rows by id.** Deleting must query raw rows by id within the session, because
  `get_messages` hides the kept row.
- **Attribution.** Add `EVENT_MESSAGE_DELETED` beside `EVENT_CONTEXT_CLEARED` and write it in the
  delete's own transaction, as `clear_context` does.
- **No thread change.** A per-message delete needs no graph-thread change: the architect's
  conversation is read from rows every turn (Context 7).
- **Frontend.**
  - Add `conversationApi.deleteMessage(sessionId, messageId)` in `src/api/conversation.ts`. It throws
    the same existing `ApiError` (`src/services/api.ts:16-24`) through the module's `errorFrom` helper.
  - Gate the per-message action with `canEditConversation(permission)`.
  - Use `ConfirmDialog` for the confirmation.
  - Extend `clearChatCopy.ts`, or add a sibling copy module that reuses the same error mapping.
  - **#317 will need message ids in the panel.** `loadSessionMessages` currently drops `msg.id`, and
    the UI `Message` type (`frontend/src/types/message.ts`) has no `id`. Add `id?: number` and map it.
    Streamed messages have no id until they are reloaded.

## Out of scope (recorded follow-ups)

- **#317** per-message delete, apart from the extension points above. Siblings #321, #319, #316, #318
  and #313.
- **Welcome text after a clear.** A cleared deck shows `ChatWelcome`'s new-deck guidance. Text written
  for a cleared deck would touch #319's surface.
- **The data analyst after a clear (parked, review F14).** `data_analyst_node` reads `deck_purpose`
  from the thread (`nodes.py:2023-2028`). An `ask_data` turn never rewrites `deck_spec`, because it
  returns before `updates.update` (`nodes.py:1589-1596` against `:1914-1916`). So the first `ask_data`
  turn after a clear sends `deck_purpose: None`. It stays out of scope because:
  - the same already happens on every duplicate and on every contributor's first turn, since each
    starts a fresh thread;
  - the analyst has no `bind_tools` today, so it can fetch nothing and returns `no_tool` or
    `missing_data` every time (`tests/integration/test_graph_live_real_model.py:31-36`);
  - the fix touches `nodes.py`, which #321 owns, and changes a model-facing value.

  Record it as a follow-up in the PR description and notes. Fall back to `read_deck_spec` when the
  thread has no spec.
- **Duplicates of uncleared legacy decks show the carried row (review F18, rejected).** The duplicate
  carry copies the source row's original `message_type` (`session_manager.py:1310-1316`), so a
  duplicate of an *uncleared* legacy deck shows the carried prompt in its chat and the monolith's
  history. This predates the plan and is not changed. A cleared source's duplicate carries the hidden
  type (Task 2's test).
- **A real-backend Playwright spec for clear chat (review F1 option (a), rejected; needs the user's
  ruling).** It would mean starting the shared e2e job's uvicorn with `DATABRICKS_HOST=""` and
  `DATABRICKS_TOKEN=""`, as integration-general does. That changes the identity mode for every
  real-backend spec in the matrix, so it is a change to a shared job and must be ruled on separately.
  Until then, Task 7's TestClient route test is the full-stack backend evidence, and the React reload
  is proven only against the mocked backend.
- **Save-point previews** keep showing the conversation they captured (D9). Restoring still does not
  reload the chat panel's messages. That is existing behaviour, and
  `docs/technical/save-points-versioning.md` §9's "chatKey remount" note is already stale.
- **Clear chat for legacy decks and MCP.** The UI does not offer it on legacy (monolith) decks, and
  MCP has no clear tool.
- **Stale session lock.** The lock counts as stale after 300 s and can then be taken by another
  request (existing behaviour).
- **The sweeper can write a checkpoint after a clear.** This is harmless (D6).
- **`CONTEXT.md` is unchanged.** The glossary covers graph-configuration terms. "Conversation Pin" is
  used here as defined there.

## Local vs CI verification limits

- **Backend.** Every new Python test runs locally on SQLite: the graph test, Task 7's route test and
  the unit tests. The graph test uses file-backed SQLite everywhere, including in CI, so it gives no
  Postgres coverage. File SQLite is *stricter* for D2, because two writers deadlock there.
  - **The Postgres evidence for D2 is Task 1's `postgres` test.** It self-skips locally, because there
    is no local Postgres. CI's unit-tests job runs it: it provisions `postgres:15`, exports
    `TELLR_TEST_POSTGRES_URL` and applies no `-m` filter.
- **Frontend unit, build and lint** run locally.
- **Playwright.** Ports 3000 and 8000 are fixed and shared by other agents, and `reuseExistingServer`
  would quietly test another worktree's server.
  - Run `clear-chat.spec.ts` (mocked, needs only vite) locally only when ports 3000 **and** 8000 are
    free. Its unmocked requests go to `127.0.0.1:8000`, and another agent's backend may be there.
  - There is no real-backend Playwright spec (D11). Task 7's route test covers the full backend stack
    and runs locally.
