# Delete a chat message, reset the chat (#317): Implementation Plan

> **For agentic workers:** load `executing-plans-tellr` (repo `CLAUDE.md`) together with
> `superpowers:subagent-driven-development`. Steps use checkbox (`- [ ]`) syntax. Every task
> carries a `Models:` tag. Tests and implementation are written by different agents, in that
> order, and every test a reviewer approves gets sabotage-verified. If
> `~/tellr-loop/issues/issue-317/PLAN-CORRECTIONS.md` exists, it overrides this plan.

**Date:** 2026-10-20
**Issue:** robertwhiffin/ai-slide-generator#317 "Delete a chat message / reset the chat"
**Branch:** `feat/317-delete-message-reset-chat`, stacked on `feat/323-clear-chat-keep-deck` at
0aa0a352 (PR #331). Before every push run `git fetch origin && git merge origin/feat/323-clear-chat-keep-deck`
(merge, never rebase). The PR targets `main`.
**Spec:** none. The issue text and the Decisions below are the authority. The planner made the
Decisions while the user was unavailable, and each one records its reasoning so a reviewer can
overturn it.

## Revision log

Revision 2 (2026-10-20) applies the independent plan review
(`~/tellr-loop/issues/issue-317/PLAN-REVIEW.md`, findings F1 to F14) under the supervisor's rulings:

- **F1 applied.** `refreshMessageIds` carries a send sequence number (`sendSeqRef`). A read that
  resolves after a newer send started is dropped, so an identical next prompt can never take the
  previous turn's id. Vitest test 17 and a sabotage are added (Task 7), with a line in D12 and in
  the Task 9 docs.
- **F2 applied.** D14's dialog text now contains "not rolled back" and avoids "that turn" (F10).
  Task 6 pastes the complete `deleteMessageCopy.ts`, so `impl=haiku` stands.
- **F3 applied.** D12's reason for rejecting server-sent ids is corrected: `complete.metadata`
  does reach the panel on both transports. The real limit is that error-ended turns send no
  `complete`. The single read mechanism stays. `complete.metadata.user_message_id` is recorded as
  the upgrade path.
- **F4 applied.** D5 lists both cross-turn values lost with the thread (`deck_spec` and
  `design_system_active`) and says that any delete starts the next turn on a new thread. The
  `deck_purpose` follow-up is carried into Task 9's docs and Task 10's hand-off.
- **F5 ruled: lift the gate (option a).** Clear chat is now offered on every persisted deck the
  user can edit, with a Spec-less wording chosen by `hasDeckSpec`. This is a deliberate change to
  #323's frontend gate. It is the new **Task 7b**; D1 is rewritten; #323's vitest table and the
  clear-chat docs are updated; an e2e assertion is added in Task 8.
  - The Spec-less wording deliberately does **not** use the ruling's example ("carries on from
    the current slides"). On a graph deck with no Spec the architect refuses edits
    (`edit_without_spec`), so that example would overpromise. Task 7b has the reasoning.
- **F6 applied.** Late rows join the turn they follow: one sentence in D2, in Known and accepted,
  and in the technical docs.
- **F7 applied.** Every commit step lists its exact paths for `git add`. `git add -A` and
  `git add .` are forbidden.
- **F8 applied.** Graph test 1 now runs three turns, deletes the middle one, and checks turn 4.
- **F9–F14 applied.**
  - F9: a `withoutTurn` test with a `tool` message inside the turn.
  - F10: copy and terminology ("exchange" in the user guide, "nothing is undone" in the technical
    docs, the title is kept).
  - F11: the turn-end read asks for `?limit=200`.
  - F12: SQLite reuses ids (a docs line).
  - F13: the tour row is reworded.
  - F14: D5's checkpoint wording is corrected.

## Goal

A user with edit rights can delete one message from their own conversation on a deck. The
message goes, together with every reply the app wrote to it. The architect never sees that turn
again, and the graph checkpoint holds nothing of it. The deck is **not** rolled back: slides, the
Spec, save points, the engine and the Conversation Pin stay as they are, and the UI and the docs
say so.

"Reset the whole chat" is #323's **Clear chat**. Its backend is reused unchanged. Its Spec gate in
the panel is lifted, so every session can be reset (F5 ruling, Task 7b). This plan adds the test
that proves a reset really starts fresh for every agent and for the checkpoint.

The real new work:

1. A `ChatService.delete_message` that removes one **turn** in one transaction. The session's
   earliest user row is hidden, never deleted. The graph thread is deleted, and the delete is
   recorded in `usage_events`.
2. A route `DELETE /api/sessions/{session_id}/messages/{message_id}` with #323's gates, lock and
   409.
3. One helper for the "earliest user row" rule, replacing three copies of the query (#323's
   hand-off asked for this).
4. A per-message delete action in the chat panel. It needs the message ids, and the panel has
   none today: the panel learns them from the load, and after every turn on both transports.
5. Clear chat offered on decks without a Spec too, with wording that does not promise a Spec
   (Task 7b).

---

## Context (verified 2026-10-20)

All paths are relative to the worktree root. "Probe" means the planner ran a throwaway test under
`/tmp/probe317/` with `uv run python -m pytest -p tests.conftest /tmp/probe317/<file> --rootdir=/tmp/probe317`.
It used the real compiled graph (`graph_turn_env`), the real `SqlAlchemyCheckpointSaver` and the
stubbed `SkillRecorder`. Nothing in the repo was changed.

### Rows, turns and the transcript

1. **A chat row** is `SessionMessage` (`src/database/models/session.py:261-293`), with the
   columns `id`, `session_id` (int FK), `role`, `content`, `created_at`, `message_type`,
   `metadata_json` and `request_id`. `UserSession.messages` is ordered by `created_at` only
   (`session.py:200-206`).
2. **Nothing groups rows into turns today.** No column or reader does it.
   - `request_id` is set only on the async (polling) path:
     - the user row is written as `user_query` with the request id (`src/api/routes/chat.py:756-763`);
     - graph rows take it from a ContextVar (`src/services/graph/nodes.py:241-304` `_say`,
       `:1162-1206` `_surface_notice`), and that ContextVar is `None` on SSE and on the sweeper
       (`src/services/graph/builder.py:285-291`).
   - On the SSE path the user row is `user_input` with no request id
     (`src/api/services/chat_service.py:1157-1167`).
   - The tour writes `chat` (`src/api/routes/tour.py:81-87`).
   - The only reliable turn boundary is **order plus role**: a user row, then everything after
     it up to the next `role='user'` row.
3. **The roles and types that are written:**
   - `user`: `user_input`, `user_query` or `chat`. `POST /api/sessions/{id}/messages` writes
     `None` (`src/api/routes/sessions.py:810-856`).
   - `assistant`: `llm_response`, `clarification`, `info` (notices and the deck-review advisory),
     `reasoning` and `tool_call` (`src/services/streaming_callback.py:99-336`;
     `chat_service.py:667-702, 1005-1044, 1263-1300`).
   - `tool`: `tool_result` (`streaming_callback.py:250-255`).
   - **Probe P1** (two graph turns) left the rows `[user, llm_response, info, user, llm_response, info]`.
     The deck-review advisory (`info`) lands after the reply and before the next user row, so it
     belongs to that turn.
4. **Every transcript reader goes through `SessionManager.get_messages`**
   (`src/api/services/session_manager.py:1509-1543`). It drops the #323 marker type before
   `limit`. The architect's `conversation` is `nodes._conversation` (`nodes.py:965-988`). It admits
   user rows whose type is in `_HUMAN_TYPES` and assistant rows whose type is in `_AI_TYPES`
   (`nodes.py:200-201`), and it is the payload key `conversation` (`nodes.py:1527-1529`). If a user
   prompt is deleted and its reply kept, the reply stays in `conversation` with no question before
   it, and the reverse leaves a question with no answer.

### What the architect and the checkpoint see

5. **The architect payload is built from the database every turn**: rows, the persisted spec,
   the committed slide rows and the stored deck review (`nodes.py:1462-1543`). The only key that
   comes from graph state is `message`, which is `state.get("architect_message")`. Both callers
   of `invoke_graph` seed it fresh every turn: chat at `chat_service.py:1971-1976`, the sweeper at
   `src/services/spec_sync.py:654-664`.
6. **The checkpoint keeps every turn, not only the latest (probe P1).**
   - `SqlAlchemyCheckpointSaver.put` inserts one row per checkpoint id
     (`_UPSERT_CHECKPOINT` at `src/core/checkpointer.py:122-130`, `put` at `:385`), and nothing prunes them.
   - After two turns the thread had 14 checkpoints and 86 pending writes.
   - Of a turn's roughly 7 checkpoints, 2 carry the user's message, in the `__start__` input
     channel and in `architect_message`, and so does 1 pending write. The architect's reply is in
     `architect_message` too, because `architect_node` writes `architect_message = <reply>`
     (`nodes.py:1573-1579`).
   - The deleted turn's text was **still in historical checkpoints after a third turn**. Only the
     *latest* checkpoint no longer had it.
   - So a delete that leaves the thread fails "the checkpoint reflects the deletion".
7. **Nothing in the checkpoint is replayed as conversation (probe P1).** The probe deleted turn 2's
   two rows and left the thread, then ran turn 3. Every payload of that turn was free of turn 2's
   text: architect, builder, build_reviewer and deck_reviewer.
   - The architect's `conversation` was the remaining rows plus the new message.
   - No application code reads checkpoint state outside the graph (grep: no `get_state`, and no
     `get_tuple` outside `checkpointer.py`).
   - Graph state (`src/services/graph/state.py:157-323`) has no messages key.
   - The cross-turn values a node reads are:
     - `state["deck_spec"]`: by `data_analyst_node` for `deck_purpose` (`nodes.py:2023-2027`), and
       by the deck reviewer for `narrative_arc` and `call_to_action` (`nodes.py:3466-3474`), after
       the architect rewrote it on that turn (`nodes.py:1914-1916`);
     - `state.get("design_system_active")`: by `data_analyst_node` for its assembly context
       (`nodes.py:2033-2037`). Only the architect's build and edit turns write it
       (`nodes.py:1914-1922`). It is inert for the analyst today, because design-system prompt
       stages apply only to `architect`, `builder` and `fixer` (`src/services/prompt_assembler.py:138-146`);
     - `findings`, an append-only log (`state.py:297`) that no node reads.
   - So #323's note "the architect's conversation is read from the rows every turn" is **true**,
     and its note "the thread holds only per-turn state" is **false**. See Findings.
8. **Deleting the thread is safe for the next turn (probe P2, the planned delete).** The probe
   used the planned turn unit, the earliest-row re-type and `delete_thread(session=db)` in one
   transaction, on file-backed SQLite. Then it ran an edit turn:
   - `intent="edit"` and `error_state` was None;
   - `conversation == [ALPHA user, "Building 4 slide(s)." assistant, GAMMA user]`;
   - no payload and no checkpoint or pending write contained the deleted turn's text;
   - the deck reviewer's `narrative_arc` and `call_to_action` were the same as before the delete
     (`['open','middle','close']`).

   A first-turn delete re-typed the user row, deleted its 2 replies, and left
   `message_count` at 4 and the engine on `graph`.
9. **A reset already starts fresh (probe P3).** The probe used #323's `clear_context` unchanged:
   a build with sentinel strings, then an extra exchange, a clear and an edit turn. No sentinel
   appeared in any agent payload or in any checkpoint or pending write, and `conversation` held
   only the new message. Before the clear, the sentinel was present in the checkpoint, so the scan
   can see text.
10. **The legacy monolith** builds its agent per request (`chat_service.py:431-498`,
    `src/services/agent_factory.py:89`). It hydrates history from `get_messages` each request
    (`chat_service.py:2456-2509`, called at `:485`). Its only per-process cache is `_deck_cache`
    (`chat_service.py:339-358`), keyed by deck version. It has one external memory: the
    Databricks Genie conversation (`genie_conversation_id`, `chat_service.py:476`), which Tellr
    does not replay and #323 does not reset.

### #323's base this plan builds on

11. **Clear chat.** The route is `clear_session_context` (`sessions.py:858-944`). It runs, in
    order:
    1. the deck gate, CAN_EDIT (`_check_deck_permission_for_session`, `src/api/routes/_authz.py:188-218`);
    2. the creator gate (`_require_conversation_creator`, `_authz.py:221-257`);
    3. `acquire_session_lock` (`session_manager.py:3110`), answering 409 with
       `CONVERSATION_BUSY_DETAIL` (`sessions.py:57-60`) and not releasing;
    4. the service;
    5. a guarded release in `finally`.

    The service is `ChatService.clear_context` (`chat_service.py:2147-2293`):
    - it keeps the earliest user row and re-types it to `ENGINE_MODE_MARKER_MESSAGE_TYPE`
      (`src/domain/conversation_engine.py:19-25`), and `is_transcript_message` (`:55-57`) hides it;
    - it bulk-deletes the rest and writes `UsageEvent(event_type=EVENT_CONTEXT_CLEARED)`
      (`src/database/models/usage_event.py:16`);
    - it calls `flush()`, then `get_checkpointer().delete_thread(session_id, session=db)`
      (`checkpointer.py:469-491`).

    All of this is one transaction.
12. **The "earliest user row" query has four copies:**
    - `resolve_engine_mode`, on the owner's session (`chat_service.py:225-233`);
    - `clear_context` (`chat_service.py:2242-2250`);
    - the duplicate carry (`session_manager.py:1234-1242`);
    - the pin backfill, a set-based `row_number()` CTE over every root
      (`src/services/conversation_pins.py:181-219`, rank at `:186-207`).

    All four filter `role == "user"` and order by `(created_at, id)`.
13. **Save points.** `create_version` captures `session.messages` into `chat_history_json` and
    filters the marker (`session_manager.py:2514-2526`). The capture includes each row's `id`.
    `restore_version` deletes this session's rows created after the save point
    (`session_manager.py:2796-2806`), re-inserts no rows and never touches the graph thread.
14. **Analytics.** `usage_events.event_type` is a free `String(30)` (`usage_event.py:26`).
    `usage_service` reads it by explicit type, and also counts every row as activity: users per
    day (`src/api/services/usage_service.py:293`), weekly retention (`:479`), the heatmap's raw
    row count (`:518`) and first-seen (`:194`). A new type cannot break a reader. It counts as
    activity, as `context_cleared` already does.

### The panel, the transports and the ids

15. **The panel has no ids.**
    - The `Message` type (`frontend/src/types/message.ts:10-16`) has no `id`.
    - `loadSessionMessages` maps `session.messages` without `msg.id` (`ChatPanel.tsx:118-148`,
      map at `:125-133`), although `SessionMessage.id` is declared (`frontend/src/services/api.ts:92-99`).
    - The user's message is shown optimistically with no id (`ChatPanel.tsx:232-240`).
    - Streamed assistant messages get none either (`:256-266`).
16. **Neither transport delivers the user row's id.**
    - Polling events carry `message_id` (`session_manager.py:3376-3403`), but `poll_chat` drops
      the user's own row (`chat.py:905-915`).
    - Graph SSE `assistant` events carry no `message_id`: `_emit` and `_say` are separate calls
      (`nodes.py:1585-1587`).
    - SSE also shows emit-only progress lines that are never persisted, for example "Building N
      slide(s)." (`nodes.py:2151-2155`) and "Slide N reviewed: …" (`nodes.py:2460-2465`).
    - Both transports end a turn in `handleStreamEvent` in one of three ways:
      - a `complete` event: SSE passes it through (`api.ts:902-990`), and polling synthesises it
        on `status=completed` (`api.ts:1162-1186`);
      - an `error` event: the SSE route sends one when a turn fails (`chat.py:633-656`);
      - the transport `onError` callback (`api.ts:1167`; `ChatPanel.tsx:398-404`).
    - The image path differs between transports. SSE persists the message with image context
      injected (`chat_service.py:1117`, before the persist at `:1158`). Polling persists the raw
      text (`chat.py:756-763`).
17. **`GET /api/sessions/{id}/messages`** (`sessions.py:749-806`) is creator-only and returns
    `{session_id, messages: [{id, role, content, message_type, created_at, metadata}], count}`.
    Nothing in the frontend calls it today (grep).
18. **The mocked e2e catch-all.** `setupMocks` answers every
    `GET http://127.0.0.1:8000/api/sessions/**/messages` with two canned rows **without ids**
    (`frontend/tests/helpers/setup-mocks.ts:144-155`). `mockSessionDetail` has no `my_permission`
    (`frontend/tests/helpers/session-helpers.ts:13-24`), so no existing spec gets an editor's
    actions.
19. **ChatPanel today** (`ChatPanel.tsx`):
    - the reset block runs on a session switch (`:84-91`);
    - Clear chat: `showClearChat` and `clearChatDisabled` (`:410-413`) and the handler
      (`:415-434`);
    - `<MessageList …/>` at `:494`;
    - the `ChatInput` `disabled` expression at `:505-508`, with `isClearing` on its own line;
    - the `error` case at `:316-321` clears `isLoading` on any ERROR event, including the
      mid-turn per-slide ERROR events (`nodes.py:1263-1267`).

    `MessageList` (`MessageList.tsx:11-37`) renders `<Message key={index} …/>` (`:23-25`).
    `Element.prototype.scrollIntoView` is stubbed for vitest (`frontend/src/test/setup.ts:7`).
20. **CI.**
    - The e2e matrix is at `.github/workflows/test.yml:691-739`, and `- clear-chat` is at `:700`.
    - integration-graph lists files at `:429-466`; `test_clear_context_graph_turn.py` is at `:465`.
    - integration-general lists files at `:553-566` (`DATABRICKS_HOST: ""`), with
      `test_clear_chat_routes.py` at `:554`.
    - Two guards check these lists: `tests/unit/test_ci_collects_integration_tests.py` and
      `tests/unit/test_e2e_matrix_covers_specs.py`.
    - `tests/unit/test_route_authz_coverage.py` passes a route with a `session_id` parameter only
      if its handler calls a listed gate. `_check_deck_permission_for_session` in the
      `to_thread` form qualifies.
    - The frontend-build job runs `npx tsc -b`, so test files must type-check.
21. **Reusable test harnesses** (all verified to exist):
    - `graph_turn_env` (`tests/integration/conftest.py:765-849`);
    - `async_turn_env`, the polling transport through `process_chat_request` and `poll_chat`
      (`tests/integration/test_architect_reply_is_persisted.py:189-291`);
    - `graph_chat_env`, SSE through `send_message_streaming` (`tests/integration/test_graph_mode_turn.py:345-420`);
    - the TestClient `deck` fixture (`tests/integration/test_clear_chat_routes.py:92-143`);
    - in `tests/unit/test_clear_context.py`: the unit helpers `_patched`, `_add_message`,
      `_messages_of`, `_RecordingSaver`, `_session_pk`, `_version_rows`, `file_backed_db`,
      `_seed_clearable_session`, `_patched_with_failing_commit` and `_count`, and the route
      fixtures `client`, `events`, `deck_gate`, `allowing_gate`, `allowing_creator`,
      `refusing_creator`, `session_lock` and `as_editor`.
22. **Siblings in flight** (read-only `git diff main...<branch>`):
    - **#321** touches `frontend/src/types/message.ts`: it adds `details?` after
      `tool_call_id`.
    - #321 also touches `ChatPanel.tsx`: it adds a `details:` line in the load map after the
      `tool_call` block, and the same in the assistant event.
    - #321 also touches `Message.tsx`, `nodes.py` (notice rows, still `info`) and
      `msg_to_stream_event`.
    - **#319** touches `ChatPanel.tsx`: the `turn_progress` case, and `<MessageList>` becomes a
      multi-line element with `progressLabel`.
    - #319 also touches `MessageList.tsx`: the props interface and the destructure.
    - #319 also touches `api.ts` (`startPolling`), `chat.py`, `session_manager.py` (new methods
      near `:3264`) and `test.yml`.
23. **`complete.metadata` reaches the panel on both transports (review F3).**
    - All five `COMPLETE` events are built in `chat_service.py` (`:1278, :1311, :1386, :1864, :2128`).
    - SSE forwards the whole event (`src/api/schemas/streaming.py:79-85`).
    - Polling copies `event.metadata` into the request result (`src/api/services/job_queue.py:164, :187`),
      and `api.ts:1183` puts `metadata: response.result.metadata` on the synthesised `complete`.
    - A turn that ends in an `error` event or `onError` sends **no** `complete`.
24. **The clear backend has no Spec dependency.** `clear_context`'s body
    (`chat_service.py:2231-2293`) touches only `session_messages`, `usage_events` and the graph
    thread. It reads no deck and no `deck_spec_json`. The route (`sessions.py:858-944`) applies
    only the deck gate, the creator gate and the lock. #323's own tests clear sessions that have no
    deck at all: `_seed_clearable_session` (`tests/unit/test_clear_context.py:267-306`) is cleared
    by `test_clear_with_the_real_saver_on_a_file_backed_database_is_one_transaction` (`:596`), and
    `test_a_session_with_no_messages_clears_cleanly` (`:424`). Only the panel's `showClearChat`
    (`ChatPanel.tsx:411`) requires `hasDeckSpec`. The #323 vitest that pins that gate is the
    `does not offer Clear chat $label` table, its two "without a Spec" rows
    (`ChatPanel.clearChat.test.tsx:189-202`). No e2e spec asserts it.
25. **`GET …/messages?limit=N` returns the newest N rows.** `limit` is `Query(None, ge=1, le=1000)`
    (`sessions.py:749-752`), and `get_messages` keeps `messages[-limit:]`
    (`session_manager.py:1532`).

## Global constraints

- **Environment.**
  - Use the per-worktree venv: run everything with `uv run …`, never `pip install`, never
    `git stash`.
  - Use `-n 4` for the full unit suite.
  - Commit in a separate shell command, but only when the supervisor says to:
    `git commit -m "<subject>" -m "Co-authored-by: Isaac <no-reply@databricks.com>"`.
  - **Stage exact paths only (review F7).** The backend and frontend tracks share one worktree,
    and each test author leaves tests uncommitted. Every commit stages exactly the paths its Step 5
    lists, with `git add <path> …`. `git add -A` and `git add .` are forbidden. Before each commit,
    the controller checks that `git status` shows no sabotage residue and nothing from the other
    track staged.
- **No deploys and no local Postgres or Docker.** Postgres-marked tests self-skip locally.
- **Playwright and dev servers.**
  - First run `~/tellr-loop/bin/e2e-lock acquire issue-317`. If it is busy, do not run; do other
    work.
  - Check that ports 3000 and 8000 are both free.
  - Afterwards, run `~/tellr-loop/bin/e2e-lock release issue-317` and stop any server you
    started.
- **Frozen artefacts stay frozen.** Change no prompt, output schema, Agent Definition, architect
  payload key, `DeckSpec`/`SlideSpec`, `frontend/src/types/slide.ts` or digest.
- **No migration.** The new usage event type `message_deleted` is 15 characters and fits
  `String(30)`. No column changes.
- **Baselines are sets of failure causes, not counts** (skill §3). The recorded baselines are in
  `~/tellr-loop/issues/issue-317/`:
  - `baseline-unit.txt`: 9196 passed, 137 skipped, 0 failed.
  - `baseline-fe-unit.txt`: 3 files and 20 tests red, all from one cause, the Node 26
    `localStorage` gap in `SlideViewer/FindingsE2.test.tsx`, `SlideViewer.test.tsx` and
    `TourViewerBridge.test.tsx`.
- **Stay out of the siblings' scope.**
  - Do not touch `nodes.py` (#321/#319), `Message.tsx` (#321), `api.ts` (#319), `chat.py`, or
    `ChatWelcome.tsx` and `LoadingIndicator.tsx` (#319).
  - In `ChatPanel.tsx`, keep edits to:
    - the state and ref declarations;
    - the reset block;
    - the load map's first line;
    - the send sequence line;
    - one new handler pair;
    - the `complete`/`error`/`onError` call sites (one line each);
    - the `<MessageList>` element and one `ConfirmDialog`;
    - one new line in the `ChatInput` `disabled` expression;
    - Task 7b's `showClearChat` line and the Clear chat button's `title` and dialog `message`.
- **#323's interfaces stay as they are.** Do not rename or move them:
  - `clear_context`, `clear_session_context` and `CONVERSATION_BUSY_DETAIL`;
  - `_require_conversation_creator`;
  - `conversationApi.clearChat` and `canEditConversation`;
  - every existing export of `clearChatCopy.ts`, value unchanged. Task 7b only **adds** two
    Spec-less constants.

  The one deliberate change is the panel's Spec gate on Clear chat (F5 ruling, Task 7b).

## Acceptance criteria (verbatim from the issue) → how each is met and proven

| # | Acceptance criterion (verbatim) | Met by | Proven by |
|---|---|---|---|
| A1 | A user can delete an individual message and reset the whole chat for a session. | **Delete:** `DELETE /api/sessions/{id}/messages/{message_id}` (Task 3) → `ChatService.delete_message` deletes that message's turn (Task 2). In the panel there is a trash action on each of the user's messages with a `ConfirmDialog` (Task 7), and ids come from the load and from a `GET …/messages` read at turn end on both transports (Tasks 6 and 7). **Reset:** #323's Clear chat, its backend unchanged, now offered on every persisted deck the user can edit, with a Spec-less wording (D1, Task 7b). | Service: `test_deleting_a_message_deletes_its_whole_turn_and_nothing_else` and the rest of `tests/unit/test_delete_message.py`. Routes, full stack: `test_deleting_a_turn_through_the_routes_keeps_the_deck_spec_and_save_points` (`tests/integration/test_delete_message_routes.py`). Transports: `test_a_polling_turn_is_one_deletable_turn_and_its_poll_rows_go_with_it` and `test_an_sse_turn_is_one_deletable_turn` (graph file), plus vitest `ChatPanel.deleteMessage.test.tsx` tests 11–13 and `turnEndSignal.test.ts`. UI: e2e `delete-message.spec.ts` tests 1–2. Reset: #323's `clear-chat.spec.ts` and `test_clear_chat_routes.py`, plus the Spec-less cases `offers Clear chat on a deck without a Spec ($label), with the wording for one` (vitest, Task 7b) and e2e `clear-chat.spec.ts` test 7 (Task 8). |
| A2 | The architect's conversation context (`_conversation`) and the graph checkpoint reflect the deletion/reset, so a reset chat really starts fresh for the agent. | Deletion: the turn's rows are deleted (D2), the first user row is hidden (D4), and the graph thread is deleted in the same transaction (D5). Reset: #323's clear already re-types and deletes the thread (Context 11); this plan adds the proof (D1). | Graph tests (real compiled graph, real saver, stubbed model): `test_after_deleting_a_turn_neither_the_architect_nor_the_checkpoint_carries_it` and `test_after_a_reset_no_message_from_before_reaches_any_agent_or_the_checkpoint`. Each scans **every** recorder payload and **every** checkpoint and pending write for the deleted text, and first proves the text was there. Units: `test_the_architect_conversation_omits_the_deleted_turn` and `test_the_monolith_history_omits_the_deleted_turn`. |
| A3 | Collaboration/permission rules: only users with edit rights can do it on a shared deck; the action is attributable. | The route applies the CAN_EDIT deck gate, then `_require_conversation_creator`, then the session lock (D7). The panel shows the action only for `canEditConversation(my_permission)` (D13). Each delete writes one `usage_events` `message_deleted` row in its own transaction, and the log lines carry `deleted_by` (D8). | Route units: `test_a_viewer_is_refused_and_nothing_is_deleted`, `test_an_editor_who_is_not_the_sessions_creator_is_refused` and `test_a_turn_in_flight_is_a_409_and_the_lock_is_not_released`. Full stack: `test_another_editor_cannot_delete_from_the_owners_conversation` (a real `DeckContributor` row) and `test_a_delete_while_a_turn_holds_the_session_lock_is_a_409`. Attribution: `test_a_delete_records_who_deleted_in_the_same_transaction` and `test_an_unimplemented_saver_rolls_the_whole_delete_back`. UI: vitest tests 1–2 and e2e test 3. |

## Decisions

- **D1. "Reset the whole chat" is #323's Clear chat. The backend is reused, and the Spec gate is lifted.**
  - `DELETE /api/sessions/{id}/context` already deletes the transcript, hides the earliest user
    row, deletes the graph thread and records `context_cleared`, all in one transaction
    (Context 11).
  - Probe P3 shows the fresh-start property already holds. This plan adds it as a permanent graph
    test: `test_after_a_reset_no_message_from_before_reaches_any_agent_or_the_checkpoint`.
  - **Supervisor ruling (review F5, option a).** The acceptance says "reset the whole chat for a
    session", which means every session. #323 offered Clear chat only where the live deck has a
    Spec (`ChatPanel.tsx:411`). That hid it on every legacy monolith deck and on every deck whose
    first build failed. On those decks, assistant rows that come before the first user row could
    never be removed.
  - Task 7b lifts the gate: Clear chat shows on every persisted session the user can edit. The
    backend needs no change (Context 24).
  - The wording is chosen by `hasDeckSpec`:
    - #323's Spec wording stays exactly as it is where a Spec exists;
    - a new Spec-less wording, which does not promise a Spec, is used otherwise:
      `CLEAR_CHAT_DIALOG_MESSAGE_NO_SPEC` and `CLEAR_CHAT_TOOLTIP_NO_SPEC` in `clearChatCopy.ts`.
  - This deliberately changes #323's frontend gate. #323's vitest rows that asserted the button
    hidden without a Spec become assertions of the Spec-less variant.
- **D2. The unit of deletion is a turn.** A turn is the user's message plus every later row of
  the session up to, not including, the next `role='user'` row. That covers assistant replies,
  clarifications, `info` notices (the deck-review advisory, failure notices, safety notices),
  `reasoning`, `tool_call` and `tool_result` rows.
  - Why the turn:
    - `_conversation` and the monolith history replay user/assistant pairs (Context 4). Deleting a
      prompt but keeping its reply leaves an orphan reply in the architect's context. Deleting a
      reply leaves an unanswered question.
    - Notices and tool rows describe the turn they follow, so they go with it.
  - Grouping is by **role and order** (`created_at`, then `id`), never by `request_id` or
    `message_type`:
    - `request_id` is None on the SSE path and on sweeper and ungated notices (Context 2);
    - grouping by role means any notice type added later, including #321's, joins its turn
      without a change.
  - A turn is addressed by its **user message's id**.
  - Rejected alternatives:
    - *Single-row delete*: it leaves orphans.
    - *Grouping by `request_id`*: it misses every SSE row.
    - *Soft-hiding every row*: every reader would need a filter, and an exact hard delete is what
      makes every reader agree. The one exception is D4.
  - **Late rows join the turn they land after (review F6).** A row of turn N written after turn
    N+1's user row has been stored belongs to turn N+1, or to whichever turn precedes it.
    Deleting turn N then leaves that row, and deleting turn N+1 takes it. Three things can cause
    a late row:
    - a stale-lock takeover after 300 s;
    - an SSE disconnect, which releases the lock while the turn keeps writing (`chat.py:657-662`);
    - the sweeper's ungated `_surface_notice` `info` rows (`nodes.py:1162-1206`).

    This is accepted: the alternative is a turn id on every row, which needs a migration.
- **D3. The route is `DELETE /api/sessions/{session_id}/messages/{message_id}`, with
  `message_id: int`.**
  - It answers **404** with one detail, `MESSAGE_NOT_FOUND_DETAIL` ("That message is not in this
    conversation."), in every not-found case:
    - the id is absent;
    - the id belongs to another session (rows are read with `session_id == session.id`, so there
      is no cross-session delete by id);
    - the id is an assistant or tool row;
    - the row is already the hidden marker.

    Using one text for all of them means the 404 tells a caller nothing about ids in other
    sessions.
  - It answers **422** for a non-integer id. FastAPI does this before any gate.
  - An unknown session is 404, and an unexpected failure is 500.
  - The UI offers the action only on user messages. A turn is never addressed through a reply.
  - It sits next to the existing `GET` and `POST /{session_id}/messages`.
- **D4. The session's earliest user row is never deleted.**
  - When the turn being deleted starts with that row, the row is re-typed to
    `ENGINE_MODE_MARKER_MESSAGE_TYPE` (hidden from every transcript read, exactly as a clear does)
    and the **rest of its turn is deleted**.
  - The UI offers the action on that message like any other, because the user cannot tell it is
    special. The response says `hidden_message_id = <id>`, and a second delete of that id is 404.
  - Consequences:
    - engine mode, the duplicate carry and the pin backfill still see the row;
    - `message_count` stays at 1 or more, so the next turn is not a "first message" and does not
      regenerate the title (`chat_service.py:1154`, `chat.py:753`).
  - It is the session's **own** earliest user row, as in `clear_context`. For a contributor
    session that is the contributor's own row. The engine resolves on the owner's rows, which a
    contributor's delete never touches.
- **D5. Every delete also deletes the session's graph thread, in the same transaction**
  (`get_checkpointer().delete_thread(session_id, session=db)`).
  - Probe P1 shows what the thread holds of a turn:
    - 2 of the turn's roughly 7 checkpoints carry the user's text, in the `__start__` and
      `architect_message` channels, and so does 1 pending write;
    - the reply is in `architect_message`.
  - Those historical checkpoints keep the text through later turns (Context 6). Leaving the
    thread fails A2 ("the graph checkpoint reflects the deletion").
  - **Any delete, of any turn, deletes the whole thread.** The next turn starts on a new thread
    either way. A delete of an older turn also drops the newer turns' checkpoint state; the
    review's middle-delete probe and graph test 1 (Task 4) record this.
  - Rejected: *rewriting state*.
    - The saver implements no `prune`, `copy_thread` or `delete_for_runs`; they raise on the base
      class (`checkpointer.py:79-83`).
    - Rewriting `channel_values` across the history is fragile.
    - Nothing reads the history anyway.
  - The cost is the one a clear already pays. With the thread go the only two values a node reads
    across turns (Context 7):
    - **`deck_spec`.** `data_analyst_node` reads it for `deck_purpose`. An `ask_data` turn returns
      before the architect writes `deck_spec` (`nodes.py:1589-1595`), so **the first `ask_data`
      turn after any delete sends `deck_purpose: None`**. That is #323's parked F14. A delete is a
      much more frequent action than a clear, so this follow-up goes into Task 9's docs and
      Task 10's hand-off. The deck reviewer is unaffected (probe P2), because the architect
      rewrites `deck_spec` on build and edit turns.
    - **`design_system_active`.** `data_analyst_node` passes it to its assembly context
      (`nodes.py:2033-2037`). It is inert for the analyst today (Context 7).
    - **`findings`.** It is lost too, and no node reads it.
  - The next turn builds its payload from the database, as probe P2 shows.
- **D6. The delete is one transaction.** The row delete, the marker re-type, the attribution row
  and the thread delete commit or roll back together. The mechanism is #323's D2:
  - `delete_thread(…, session=db)` runs on the caller's session and does not commit;
  - `flush()` runs before the thread delete;
  - a raise from anywhere leaves everything as it was, and the route answers 500;
  - a retry is safe.

  File-backed SQLite with the real saver is the strict local test, because two writers deadlock
  there. No Postgres test is added: the delete uses the identical `delete_thread(session=db)`
  call that #323's `TestTheClearAgainstRealPostgres` proves issues no second connection.
- **D7. Who may delete, and when.** The route runs these steps in order, exactly as
  `clear_session_context` does:
  1. `_check_deck_permission_for_session(session_id, CAN_EDIT)`: a viewer gets 403;
  2. `_require_conversation_creator(session_id)`: no user is 401 and anyone but the session's
     own `created_by` is 403, so a contributor deletes only in their own contributor session and
     never in the owner's;
  3. `acquire_session_lock`: if a turn or slide operation holds it, the route answers **409**
     with `CONVERSATION_BUSY_DETAIL` and **does not release**;
  4. the delete;
  5. a release in `finally`, with a release failure only logged.

  The deck *editing* lock is not required, because the delete changes no deck state. The UI
  disables the action whenever the panel is read-only.
- **D8. Attribution.**
  - `EVENT_MESSAGE_DELETED = "message_deleted"` sits beside `EVENT_CONTEXT_CLEARED`.
  - Each delete writes one row: `username = deleted_by`, `session_id` = the session's integer id,
    in the delete's own transaction. The row exists if and only if the delete committed.
  - `deleted_by` is required; a falsy value is refused with `ValueError` before anything changes.
  - The service and the route log lines carry `deleted_by` and `message_id`.
  - Admin analytics has no metric for it and needs no change. Like every type it counts as
    activity (Context 14). The heatmap counts each delete as one event, as it counts each clear;
    the docs say so.
  - Rejected: `SharedDeckMutationEvent`, for the same reasons as #323's D5 (a CHECK-constraint
    migration, and a private chat edit reported as a deck mutation).
- **D9. The deck is not rolled back.**
  - The delete touches only `session_messages`, plus the thread and the attribution row. It
    leaves alone: slide rows, `deck_json`, `deck_spec_json`, save points, `graph_release_id` and
    `agent_config`.
  - The architect's next turn starts from the current Spec and slides, which still contain what
    the deleted exchange built. The dialog copy ("it is not rolled back") and the user guide say
    so (D14). The technical docs say "nothing is undone", because **Rollback** is a CONTEXT.md term
    for Graph Releases (review F10).
  - The deck's title is kept, even when the first message is deleted (D4).
- **D10. Save points stay exactly as they are.**
  - A save point keeps the chat it captured, so its preview still shows a later-deleted turn.
  - A save point taken after a delete excludes the turn, and excludes a hidden first row.
  - A restore never brings the turn back, because restore re-inserts no rows (Context 13).
- **D11. Legacy (monolith) decks.**
  - The monolith replays only rows, through `get_messages`, per request, with no in-process
    memory (Context 10). So the delete needs nothing more there.
  - The action is offered on **every** persisted deck the user can edit, Spec or not. Clear chat
    now is too (D1). A failed first turn on a new deck (no slides, no Spec) is exactly what a user
    wants to delete.
  - Known and documented: a Genie space keeps its own conversation (`genie_conversation_id`). A
    deleted turn's data questions stay there, as they do after a clear.
- **D12. How the panel learns message ids on both transports.**
  - **On load:** `loadSessionMessages` maps `id: msg.id`.
  - **After every turn:** when the turn ends (`complete`, an `error` event or the transport's
    `onError`), the panel calls `conversationApi.listMessages(sessionId, 200)`, that is,
    `GET …/messages?limit=200`, which returns the newest 200 rows (Context 25, review F11). It then
    gives each of its **id-less user messages** the id of the persisted user row with **identical
    content**, pairing from the newest (`withPersistedUserIds`).
  - **A read that resolves after a newer send started is dropped (review F1).**
    - Each send takes a sequence number (`sendSeqRef`), and the read carries the number of the
      send whose turn just ended.
    - Without this, a read for turn N that lands after turn N+1's identical prompt ("yes", "try
      again") would give turn N's id to turn N+1's message. A delete would then remove the wrong
      turn, and that cannot be undone.
    - Pairing is idempotent, so the next turn's read pairs everything.
  - The pairing never changes content, order or any assistant message. A message with no
    identical row keeps no id and gets one on the next load:
    - a send refused before persisting;
    - an SSE message with images, whose stored text includes the injected image context;
    - a message older than the newest 200 rows.
  - A failure or a malformed body changes nothing.
  - Polling `message_id`s on assistant events are not needed, because only user messages carry
    the action.
  - Reads are not de-duplicated while one is in flight. A graph turn can issue one extra read per
    mid-turn per-slide `error` event, and each read is bounded by `limit=200` and idempotent.
    Skipping reads would risk dropping the one read that carries the final rows.
  - Rejected alternatives:
    - *Server-sent ids (corrected per review F3).* `complete.metadata` does reach the panel on
      both transports (Context 23). A `metadata.user_message_id` could be added by editing only
      `chat_service.py` and `ChatPanel.tsx`: SSE has the id at `chat_service.py:1158`, and polling
      would look it up by `request_id`. **But a turn that ends in an `error` event or `onError`
      sends no `complete`**, and a failed turn is exactly what a user wants to delete. A read
      would still be needed for those. One mechanism that covers every ending is simpler than
      two. `complete.metadata.user_message_id` is recorded as **the upgrade path** if content
      pairing ever proves too weak.
    - *Replace the panel with the persisted list at turn end.* SSE's emit-only progress lines
      would vanish (Context 16). Every existing mocked e2e that completes a turn would also show
      `setupMocks`' two canned `/messages` rows (Context 18).
- **D13. The panel action.**
  - Each user message with an `id` gets a small ghost icon button (lucide `Trash2`,
    `data-testid="delete-message-button"`, accessible name = `DELETE_MESSAGE_TOOLTIP`). It shows
    on hover and focus, inside a `data-testid="chat-message-row"` wrapper rendered by
    `MessageList`. `Message.tsx` is not touched (#321).
  - The button is **shown** only when the session is persisted and
    `canEditConversation(myPermission)`, and never in a save-point preview.
  - It is **disabled** while a turn is loading, a clear is running, a delete is running, or the
    panel is `disabled` (read-only).
  - Confirming goes through a second `ConfirmDialog`.
  - On success the turn is removed **locally** (`withoutTurn`): the user message and every panel
    message up to the next user message. Nothing is refetched: no slides, no session, no
    `onSlidesGenerated`.
  - A response that lands after a session switch is dropped.
  - A send is ignored while a delete runs, and Clear chat is disabled while a delete runs.
  - **Local ids only.** On SQLite a deleted row's id can be reused by the next row (review F12:
    clearing ids 2–3 gave the next row id 2). Locally, a stale tab could therefore address a newer
    turn. Postgres sequences never reuse ids, so production is unaffected. The technical docs say
    so.
- **D14. Copy.** All strings are in a new `frontend/src/components/ChatPanel/deleteMessageCopy.ts`
  (pasted in full in Task 6). It is a sibling of `clearChatCopy.ts`, whose existing exports stay
  unchanged.
  - Tooltip and accessible name: `Delete this message and the replies to it`.
  - Title: `Delete this message?`
  - Message (review F2 and F10: it contains "not rolled back" and does not say "that turn"):
    `This deletes your message and the assistant's replies to it, so the assistant won't see them
    again. Anything it changed in your slides or the Spec stays as it is; it is not rolled back.
    This can't be undone.`
  - Confirm: `Delete` (danger). Cancel: `Cancel`.
  - 409: `Something is still running on this deck. Wait for it to finish, then delete the
    message.`
  - 403: `Only editors can delete messages, and only in their own conversation.`
  - 404: `That message is no longer in this conversation. Reload the page to see the current
    conversation.` Unlike #323's F23, a 404 gets its own text here, because a delete from a stale
    second tab is a realistic case.
  - Any other failure: `Couldn't delete the message. Reload the page to see the current
    conversation, then try again.`
- **D15. Multi-worker.** The change adds no in-process state.
  - The lock is the database flag.
  - `_deck_cache` is keyed by deck version, and the deck does not change.
  - Agents are built per request from rows.
  - The checkpointer keeps nothing on `self`.

  So no worker holds a copy of the transcript that a delete on another worker would leave stale.
- **D16. One helper for the earliest user row.**
  - **New** `earliest_user_message(db, session_pk) -> Optional[SessionMessage]` is a module
    function in `session_manager.py`, defined just above `class SessionNotFoundError` (`:657`).
  - It replaces the query in `resolve_engine_mode` (owner pk), `clear_context` (session pk) and
    `duplicate_session` (owner pk), and `delete_message` uses it. That is three copies removed
    and no fifth one added.
  - The **pin backfill keeps its set-based CTE.** It is one statement over every root at
    startup, a per-session helper would make it N queries, and its semantics are frozen to
    historical decks. It is Postgres-tested (`test_conversation_pin_migration_postgres.py`). The
    helper's docstring names it as the set-based twin, with the same `role` filter and the same
    `(created_at, id)` order.
  - Proof that each caller still behaves the same:
    - a spy test shows every converted caller goes through the helper;
    - tie-break tests pin `(created_at, id)` through each caller's observable result;
    - the existing suites stay green.
- **D17. No real-backend Playwright spec, for the same reason as #323's F1.** In CI the e2e
  backend hangs on SCIM. The UI journey is a **mocked** spec. The backend is proved by a
  TestClient full-stack route test in integration-general and by graph tests in
  integration-graph.
- **D18. A delete cannot be undone,** and there is no "deleted message" placeholder in the chat.
  The record of the action is the usage event and the log line.

### Known and accepted

These are inherited from #323's D6 and apply to every lock user.

- **Stale lock.** A lock older than 300 s counts as stale and can be taken.
- **SSE disconnect.** On SSE (local dev only) the lock is released when the client disconnects,
  so a delete in that window succeeds while the turn keeps writing.
- **The sweeper.** The arc-review sweeper runs on the owner's thread without the lock. If it
  reads `conversation` before a delete and checkpoints after it, its describe-only reply can
  land in the new thread. `_say` writes no row on a describe-only turn, but the ungated
  `_surface_notice` can write an `info` row. Nothing replays the thread.
- **Late rows join a later turn (D2, review F6).** A row written after the next user row (stale
  lock, SSE disconnect, a sweeper notice) is grouped with the turn it lands after.
- **A 409 right after a turn.** A delete clicked the instant a turn completes can answer 409
  "still running":
  - polling marks the request completed (`job_queue.py:197`) before it releases the lock (`:213`);
  - on SSE the title thread is joined, for up to 10 s, after `complete` (`chat_service.py:2140`).

  The copy tells the user to wait.
- **Mid-turn ERROR events.** The panel's `error` case clears `isLoading` on the mid-turn
  per-slide ERROR events (Context 19). The action can therefore enable mid-turn, and a click then
  gets the 409 copy.

## Review focus

1. **The turn boundary.** The rows deleted are exactly the head plus the rows up to the next
   `role='user'` row, read in `(created_at, id)` order, **within this session only**. Check the
   `session_id == session.id` filter in both queries.
2. **The earliest row is re-typed, never deleted.** It is the session's own earliest row, found
   through the helper, and its re-type is in the same transaction.
3. **One transaction.** Nothing inside `delete_message` commits before the `with` block exits.
   `delete_thread` gets `session=db`.
4. **Route order:** deck gate, creator gate, lock, service, release. A 409 never releases. A
   refused request touches nothing.
5. **The panel never rewrites content when it learns ids.** `withPersistedUserIds` only *adds*
   `id` to id-less user messages, and never refetches slides after a delete. A read that resolves
   after a newer send started is dropped (`sendSeqRef`, D12).
6. **No payload, prompt, schema or digest diff.** No edit to `nodes.py`, `Message.tsx`, `api.ts`
   or `chat.py`.

## Every reader after a delete (the baseline for Review focus 1–2)

| Reader | Location | After a delete |
|---|---|---|
| `GET /sessions/{id}`, `GET /sessions/{id}/messages` | `sessions.py:550, 780` | The turn is gone; a hidden first row stays hidden (#323's filter). |
| Architect `conversation` | `nodes.py:965-988` | The turn is gone. |
| Monolith history | `chat_service.py:2456-2509` | The turn is gone. |
| Graph checkpoint | `checkpointer.py:469-491` | The thread is deleted (D5). |
| Save-point capture | `session_manager.py:2514-2526` | Later save points exclude the turn. Existing ones are unchanged (D10). |
| `message_count` | `session_manager.py:819-824` | Drops by the rows deleted. It is never 0 once a user row existed (D4). |
| `get_messages_for_request` (poll, MCP `get_deck_status`) | `session_manager.py:3338-3373` | A deleted turn's request polls empty. A hidden first row still returns with the marker type (as after a clear). |
| Tour stage machine | `tour.py:117-124` | Changed. Deleting a tour turn removes its `tour_stage` rows, so the next scripted stage answers 409 and the tour cannot continue on that deck. The demo deck itself is unaffected. |
| Slide-verification corpus | `verification.py:173-179` | Deleting a legacy turn removes its `tool_result` rows, so slides built from that data have less to verify against. Documented. |
| Engine mode, duplicate carry, pin backfill | helper (D16); `conversation_pins.py:186-207` | Unchanged: the earliest row is kept. |

## File map

| File | Change | Task |
|---|---|---|
| `src/api/services/session_manager.py` | **new** `earliest_user_message`; duplicate carry uses it (T1); **new** `MessageNotFoundError` (T2) | 1, 2 |
| `src/api/services/chat_service.py` | `resolve_engine_mode` and `clear_context` use the helper, plus a docstring fix (T1); **new** `delete_message` (T2) | 1, 2 |
| `tests/unit/test_earliest_user_message.py` | **new** | 1 |
| `src/domain/conversation_turns.py` | **new** `turn_message_ids` | 2 |
| `src/database/models/usage_event.py` | **new** `EVENT_MESSAGE_DELETED` | 2 |
| `tests/unit/test_conversation_turns.py` | **new** | 2 |
| `tests/unit/test_delete_message.py` | **new**: service tests (T2), route tests (T3) | 2, 3 |
| `src/api/routes/sessions.py` | **new** `MESSAGE_NOT_FOUND_DETAIL` and `delete_session_message` route | 3 |
| `tests/integration/test_delete_message_graph_turn.py` | **new** graph and transport tests | 4 |
| `tests/integration/test_delete_message_routes.py` | **new** TestClient full-stack test | 5 |
| `.github/workflows/test.yml` | integration-graph (T4), integration-general (T5), e2e matrix (T8) | 4, 5, 8 |
| `frontend/src/types/message.ts` | `id?: number` | 6 |
| `frontend/src/api/conversation.ts` (+ `.test.ts`) | `deleteMessage`, `listMessages` | 6 |
| `frontend/src/utils/conversationTurns.ts` (+ `.test.ts`) | **new** `withoutTurn`, `withPersistedUserIds` | 6 |
| `frontend/src/components/ChatPanel/deleteMessageCopy.ts` (+ `.test.ts`) | **new** copy and `deleteMessageErrorMessage` | 6 |
| `frontend/src/services/__tests__/turnEndSignal.test.ts` | **new** transport test (no production change) | 6 |
| `frontend/src/components/ChatPanel/MessageList.tsx` | `deleteAction` prop, row wrapper, button | 7 |
| `frontend/src/components/ChatPanel/ChatPanel.tsx` | ids on load, id refresh at turn end, delete state, handler, dialog | 7 |
| `frontend/src/components/ChatPanel/ChatPanel.deleteMessage.test.tsx` | **new** | 7 |
| `frontend/src/components/ChatPanel/clearChatCopy.ts` | **add** `CLEAR_CHAT_DIALOG_MESSAGE_NO_SPEC`, `CLEAR_CHAT_TOOLTIP_NO_SPEC` | 7b |
| `frontend/src/components/ChatPanel/ChatPanel.tsx` (again) | Clear chat on every deck, with the wording chosen by `hasDeckSpec` | 7b |
| `frontend/src/components/ChatPanel/ChatPanel.clearChat.test.tsx` | #323's "without a Spec" rows become the Spec-less variant test | 7b |
| `frontend/tests/e2e/delete-message.spec.ts` | **new** mocked e2e | 8 |
| `frontend/tests/e2e/clear-chat.spec.ts` | `deckSpec` option on `mockClearableDeck`, plus a test for the Spec-less variant | 8 |
| docs (Task 9), `frontend/src/components/Help/HelpPage.tsx` | user and technical docs | 9 |

**Order and parallelism.**

| Track | Order | Runs in parallel with |
|---|---|---|
| Backend | **1 → 2 → 3 → 4 → 5** (`session_manager.py`, `chat_service.py`, `test_delete_message.py` and `test.yml` are shared) | the frontend track |
| Frontend | **6 → 7 → 7b** (7 and 7b both edit `ChatPanel.tsx`) | the backend track; they share no file with Tasks 1–5 |

- **8** runs after 7b, and after 5 because it also edits `test.yml`.
- **9** runs after 1–8.
- **10** runs last.

---

## Before Task 1 (controller pre-pass, not a task)

- [ ] `cd /Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-317 && uv sync --extra dev`.
  Confirm `frontend/node_modules` exists.
- [ ] **Baselines are recorded already** (Global constraints). Also record the frontend lint
  baseline: `cd frontend && npx eslint . > ~/tellr-loop/issues/issue-317/baseline-fe-lint.txt 2>&1`.
  - **Lint gate for every frontend task:** `npx eslint <touched files>` must show no finding
    absent from that baseline. Compare by file, rule and message, not by line.
  - **Vitest gate:** the failure-cause set of `npm run test:unit` equals the baseline.
- [ ] **Re-run the plan-vs-code check** on every `file:line` above. Write `PLAN-CORRECTIONS.md`
  in `~/tellr-loop/issues/issue-317/` if anything moved.
- [ ] **Confirm every task has a `Models:` tag** (skill §9).

---

### Task 1: One helper for the session's earliest user row

**Models:** `test=opus impl=sonnet`. The code is given. The judgement is in the test author's
tie-break and spy design.

**Files:** `src/api/services/session_manager.py`, `src/api/services/chat_service.py`, **new**
`tests/unit/test_earliest_user_message.py`

**Interface introduced** (`session_manager.py`, module level, directly above
`class SessionNotFoundError` at `:657`):

```python
def earliest_user_message(db: Session, session_pk: int) -> Optional[SessionMessage]:
    """The session's earliest ``role='user'`` row: the row engine mode is read off.

    THE one copy of this rule (#317).  Earliest means ``created_at``, then
    ``id``.  ``role`` only, never ``message_type``: the live paths write
    different types for one user turn (``user_input`` on SSE, ``user_query`` on
    the async route and MCP, ``chat`` on the tour), and the row a clear or a
    message delete keeps is re-typed ``engine_mode_marker`` but is still this
    row.

    Callers: ``resolve_engine_mode`` (on the deck OWNER's session),
    ``ChatService.clear_context`` and ``ChatService.delete_message`` (the row
    they keep), ``SessionManager.duplicate_session`` (the marker it carries).
    The startup pin backfill (``conversation_pins._backfill_in_transaction``)
    applies the same rule set-based, over every root at once, with
    ``row_number()`` over the same two columns; keep the two in step.

    ``session_pk`` is ``UserSession.id`` (the integer key), not the string id.
    """
    return (
        db.query(SessionMessage)
        .filter(
            SessionMessage.session_id == session_pk,
            SessionMessage.role == "user",
        )
        .order_by(SessionMessage.created_at.asc(), SessionMessage.id.asc())
        .first()
    )
```

**Call sites:**

- `chat_service.py:23` imports it:
  `from src.api.services.session_manager import SessionNotFoundError, VersionConflictError, earliest_user_message, get_session_manager`.
- `resolve_engine_mode` (`chat_service.py:225-234`):
  - **Do not reuse the local name `earliest_user_message`.** Assigning to it inside the function
    would shadow the import and raise `UnboundLocalError`. Write
    `earliest = earliest_user_message(db, deck_owner.id)` and
    `content = earliest.content if earliest else None`.
  - Remove the now-unused lazy `from src.database.models.session import SessionMessage` at
    `:215`.
  - In the docstring (`:168-172`), replace "and the architect's own conversation lives in the
    checkpointer under a ``thread_id``" with "and the graph's checkpoint thread, keyed by the
    session id, would be resumed by one engine and ignored by the other". The old clause is
    false (Context 7).
- `clear_context` (`chat_service.py:2242-2250`): `marker = earliest_user_message(db, session.id)`.
  Keep the lazy `SessionMessage` import there, because the bulk delete uses it.
- `duplicate_session` (`session_manager.py:1234-1242`): `marker = earliest_user_message(db, deck_owner.id)`.
- `conversation_pins.py` is **unchanged** (D16).

**Tests** (`tests/unit/test_earliest_user_message.py`). Use `_session_unit_engine`,
`_make_factory` and `_make_fake_db` from `tests/unit/conftest.py`, and seed rows with explicit
`created_at`:

1. `test_the_earliest_user_row_is_ordered_by_created_at_then_id`. Two user rows share one
   `created_at`: the lower id is returned. A user row one second earlier beats both.
2. `test_assistant_and_tool_rows_are_never_the_earliest_user_row`. An `assistant` row and a
   `tool` row both predate every user row.
3. `test_a_hidden_marker_is_still_the_earliest_user_row`. The row's type is
   `ENGINE_MODE_MARKER_MESSAGE_TYPE`.
4. `test_no_user_row_is_none`. Another session's rows are never returned.
5. `test_every_caller_reads_the_row_through_the_helper`.
   - Wrap the real function in a recording spy, patched at
     `src.api.services.chat_service.earliest_user_message` and at
     `src.api.services.session_manager.earliest_user_message`.
   - Call `resolve_engine_mode(contributor_sid)` (the `contributor_session` fixture): the spy
     records the **owner's** pk.
   - Call `ChatService().clear_context(sid, cleared_by=…)` (use the `_RecordingSaver` and
     `_patched` imported from `tests.unit.test_clear_context`): the spy records the session's pk.
   - Call `SessionManager().duplicate_session(sid, "copier@example.com")` (on
     `session_with_spec_and_messages`): the spy records the source owner's pk.
   - Red today with `AttributeError`, because the module has no such attribute (patched with
     the default `raising=True`).
6. `test_a_created_at_tie_is_broken_by_id_for_every_caller`. These are characterization tests:
   green before and after, and sabotage proves they bite. Two user rows share one `created_at`,
   and the lower id carries `LEGACY_MODE_PHRASE`. Then:
   - `resolve_engine_mode == "monolith"`, and with the phrase on the higher id instead,
     `"graph"`;
   - `clear_context(...)["preserved_message_id"]` is the lower id;
   - a duplicate of that legacy source carries the lower id's content and resolves `"monolith"`.

**Steps:**
- [ ] **Step 1 (test author).** Write the tests. Tests 1–5 are red on the missing symbol. Test 6
  is green today; record that it is a characterization test. Leave them uncommitted.
- [ ] **Step 2 (implementer).** Add the helper and convert the three call sites. Do not edit the
  tests.
- [ ] **Step 3.** Run:
  `uv run pytest tests/unit/test_earliest_user_message.py tests/unit/test_engine_mode_selection.py tests/unit/test_engine_mode_wiring.py tests/unit/test_clear_context.py tests/unit/test_session_duplicate.py tests/unit/test_duplicate_session_carries_spec.py -q`.
  Then run `uv run pytest tests/unit -q -n 4` and compare failure causes with the baseline.
- [ ] **Step 4.** Sabotage, one at a time. Each must turn a named test red:
  - order by `SessionMessage.id.desc()` in the helper (test 6 and test 1);
  - put the inline query back in `duplicate_session` (test 5);
  - add `is_transcript_message(...)` to the helper's filter (test 3, and #323's
    `test_clearing_twice_keeps_the_same_marker`);
  - pass `session.id` instead of `deck_owner.id` in `resolve_engine_mode` (test 5, and
    `test_contributor_inherits_the_owner_decks_monolith_mode`).
- [ ] **Step 5.** Commit. Stage exactly
  `git add src/api/services/session_manager.py src/api/services/chat_service.py tests/unit/test_earliest_user_message.py`,
  then commit `refactor(sessions): one helper for a session's earliest user message (#317)`.

---

### Task 2: `ChatService.delete_message`: one turn, one transaction, attributed

**Models:** `test=opus impl=sonnet`. The code is given. The test author carries the
behavioural completeness: every reader, every not-found case, atomicity.

**Files:**
- **new** `src/domain/conversation_turns.py`
- `src/database/models/usage_event.py`
- `src/api/services/session_manager.py` (`MessageNotFoundError` only)
- `src/api/services/chat_service.py` (`delete_message` and imports)
- **new** `tests/unit/test_conversation_turns.py`
- **new** `tests/unit/test_delete_message.py` (the service half)

**Interfaces introduced:**

```python
# src/domain/conversation_turns.py (new)
"""Conversation turns over persisted chat rows (#317).

A TURN is one user message and everything the app wrote in answer to it: every
later row of the same session up to, not including, the next ``role='user'``
row.  Assistant replies, clarifications, ``info`` notices (the deck reviewer's
advisory, failure notices), ``reasoning``, ``tool_call`` and ``tool_result``
rows belong to the turn they follow, whatever their ``message_type`` and
whether or not they carry a ``request_id`` (the SSE path and the sweeper write
none).  Grouping is by role and order only, so a row type added later joins
its turn with no change here.
"""

from __future__ import annotations

from typing import Any, List, Sequence

from src.domain.conversation_engine import is_transcript_message


def turn_message_ids(rows: Sequence[Any], head_id: int) -> List[int]:
    """Ids of the turn whose user message is ``head_id``, the user message first.

    Args:
        rows: ONE session's rows, each with ``id``, ``role`` and
            ``message_type``, in transcript order (``created_at``, then ``id``).
        head_id: The user message that starts the turn.

    Returns:
        ``[]`` when ``head_id`` is not a visible user message in ``rows``:
        absent, another role, or the hidden engine-mode marker.  A turn is
        addressed only by its user message.
    """
    for index, row in enumerate(rows):
        if row.id == head_id:
            break
    else:
        return []
    if row.role != "user" or not is_transcript_message(row.message_type):
        return []
    ids = [row.id]
    for later in rows[index + 1:]:
        if later.role == "user":
            break
        ids.append(later.id)
    return ids
```

```python
# src/database/models/usage_event.py: beside EVENT_CONTEXT_CLEARED (:16)
EVENT_MESSAGE_DELETED = "message_deleted"
# Also add "message deleted" to the UsageEvent class docstring's list.
```

```python
# src/api/services/session_manager.py: directly after class SessionNotFoundError (:657-660)
class MessageNotFoundError(Exception):
    """A message id is not a deletable message of the session.

    One error for every case (absent, another session's, not a user message,
    the hidden engine-mode marker), so the route's 404 is no oracle for ids in
    other sessions.
    """
```

`chat_service.py` imports:
- extend `:23` with `MessageNotFoundError`;
- add `from src.domain.conversation_turns import turn_message_ids`;
- `ENGINE_MODE_MARKER_MESSAGE_TYPE` is already imported at `:30-35`.

Add the method directly after `clear_context` (`:2293`):

```python
    def delete_message(
        self, session_id: str, message_id: int, *, deleted_by: str
    ) -> Dict[str, Any]:
        """Delete one turn of this session's conversation: a user message and its replies.

        The turn is ``message_id`` (a user row of THIS session) and every later
        row up to the next ``role='user'`` row (``turn_message_ids``): replies,
        notices, reasoning and tool rows, whatever their type or request id.
        Deleting a prompt but keeping its reply would leave the architect an
        orphan reply in ``conversation``; the turn goes whole.

        **The session's earliest user row is never deleted** (#323): engine mode
        is read off it.  When the turn starts there, that row is re-typed
        ``ENGINE_MODE_MARKER_MESSAGE_TYPE`` (hidden from every transcript read)
        and the rest of its turn is deleted; ``hidden_message_id`` says so.

        **The graph thread is deleted.**  The checkpointer keeps every
        checkpoint of every turn, and each stores that turn's user message
        (``__start__``, ``architect_message``) and the architect's reply
        (``architect_message``).  Nothing replays them, but a deletion the
        checkpoint still holds is not a deletion.  The next turn starts a new
        thread and builds its payload from the database.

        **The deck is not rolled back**: slides, the Spec, save points and the
        Conversation Pin are untouched.

        **One transaction**, as in :meth:`clear_context`: the row delete, the
        re-type, the ``usage_events`` row and ``delete_thread(session=db)``
        commit or roll back together.

        Args:
            session_id: The session whose conversation to edit.  A contributor
                session edits only its own rows.
            message_id: The user message that starts the turn.
            deleted_by: Username of the caller; recorded in ``usage_events`` and
                the log line.  Required and non-empty.

        Returns:
            ``{"status": "deleted", "session_id", "message_id",
            "deleted_messages": N, "hidden_message_id": id-or-None}``

        Raises:
            ValueError: ``deleted_by`` is empty or None (nothing is changed).
            SessionNotFoundError: session_id does not exist.
            MessageNotFoundError: ``message_id`` is not a visible user message
                of this session (nothing is changed).
        """
        if not deleted_by:
            raise ValueError(
                "delete_message requires deleted_by: who deleted must be recorded"
            )

        from src.core.database import get_db_session
        from src.database.models.session import SessionMessage
        from src.database.models.usage_event import EVENT_MESSAGE_DELETED, UsageEvent

        session_manager = get_session_manager()
        with get_db_session() as db:
            session = session_manager._get_session_or_raise(db, session_id)

            # Columns only, in transcript order: grouping needs no content, and a
            # tool_result row's content can be large.
            rows = (
                db.query(
                    SessionMessage.id, SessionMessage.role, SessionMessage.message_type
                )
                .filter(SessionMessage.session_id == session.id)
                .order_by(SessionMessage.created_at.asc(), SessionMessage.id.asc())
                .all()
            )
            turn = turn_message_ids(rows, message_id)
            if not turn:
                raise MessageNotFoundError(message_id)

            doomed = list(turn)
            hidden_message_id = None
            earliest = earliest_user_message(db, session.id)
            if earliest is not None and earliest.id == message_id:
                # Never delete the engine-mode row: hide it, as a clear does.
                earliest.message_type = ENGINE_MODE_MARKER_MESSAGE_TYPE
                hidden_message_id = earliest.id
                doomed = turn[1:]

            deleted_messages = 0
            if doomed:
                deleted_messages = (
                    db.query(SessionMessage)
                    .filter(
                        SessionMessage.session_id == session.id,
                        SessionMessage.id.in_(doomed),
                    )
                    .delete(synchronize_session=False)
                )

            db.add(
                UsageEvent(
                    username=deleted_by,
                    event_type=EVENT_MESSAGE_DELETED,
                    session_id=session.id,
                )
            )
            # A failed insert or re-type raises here, before the thread is touched.
            db.flush()

            from src.core.checkpointer import get_checkpointer

            get_checkpointer().delete_thread(session_id, session=db)

        logger.info(
            "Deleted a conversation turn",
            extra={
                "session_id": session_id,
                "message_id": message_id,
                "deleted_by": deleted_by,
                "deleted_messages": deleted_messages,
                "hidden_message_id": hidden_message_id,
            },
        )
        return {
            "status": "deleted",
            "session_id": session_id,
            "message_id": message_id,
            "deleted_messages": deleted_messages,
            "hidden_message_id": hidden_message_id,
        }
```

**Pure tests** (`tests/unit/test_conversation_turns.py`, using `SimpleNamespace(id, role, message_type)` rows):
- a turn is the head plus the rows up to the next user row;
- the last turn runs to the end;
- `[]` for an absent id, an assistant id, a tool id, and a user row typed
  `engine_mode_marker`;
- assistant rows before the first user row belong to no turn;
- a user row with `message_type=None` is a head;
- the next user row ends the turn even when it is `user_query` or `chat`.

**Service tests** (`tests/unit/test_delete_message.py`).

Import from `tests.unit.test_clear_context`, by name only and never a class:
`_patched`, `_add_message`, `_messages_of`, `_RecordingSaver`, `_session_pk`,
`_version_rows`, `file_backed_db`, `_seed_clearable_session`, `_patched_with_failing_commit`,
`_assert_thread_rows`, `_PHRASE_MESSAGE` and `_PLAIN_MESSAGE`.

Add a local `_add_row(factory, sid, *, role, content, message_type, offset_seconds, request_id=None)`,
because `_add_message` cannot set `request_id`.

Read `message_deleted` events back by the stored string, the way analytics reads them. The seed
`_TURNS` on a fresh session (`created_by="owner@example.com"`), as (offset, role, content, type,
request_id):

```
 0 user      "Build me a deck about puffins"            user_input    None    # U1 (earliest)
 5 assistant "Building 4 slide(s)."                     llm_response  None    # A1
 6 assistant "Deck review complete."                    info          None    # N1
10 user      "Add a slide on their diet"                user_query    "req-2" # U2
11 assistant "Querying diet data"                       tool_call     "req-2" # T2
12 tool      "diet table"                               tool_result   "req-2" # R2
13 assistant "Slide 4 covers diet."                     llm_response  "req-2" # A2
14 assistant "Slide 4: the model was briefly unavailable." info       None    # N2 (untagged notice)
20 user      "Make slide 3 shorter"                     chat          None    # U3
21 assistant "Which slide is slide 3?"                  clarification None    # A3
```

Class `TestTheTurnIsTheUnit`:
1. `test_deleting_a_message_deletes_its_whole_turn_and_nothing_else`. Delete U2.
   - The remaining contents are exactly `[U1, A1, N1, U3, A3]`.
   - `deleted_messages == 5` and `hidden_message_id is None`.
   - The untagged N2 and the `tool` row R2 are gone: grouping goes by role and order, not by
     `request_id` or type.
2. `test_the_last_turn_runs_to_the_end_of_the_transcript`. Delete U3 and only U3 and A3 go.
3. `test_every_user_message_type_starts_a_turn`. Parametrize the head's type over `user_input`,
   `user_query`, `chat` and `None` on a two-turn session. Deleting the second turn removes it
   whole.
4. `test_an_id_that_is_not_a_visible_user_message_of_this_session_is_not_found`. Parametrize:
   - A1's id;
   - R2's id;
   - `max_id + 1000`;
   - the marker's id after `clear_context` (run the clear with its own `_RecordingSaver`, so the
     delete's saver starts empty);
   - the id of a user row in a **second** session.

   Each raises `MessageNotFoundError`. Both sessions' rows are unchanged, `saver.deleted == []`,
   and there is no `message_deleted` row.
5. `test_an_unknown_session_raises_session_not_found`.

Class `TestTheFirstUserMessageIsHiddenNotDeleted`:
6. `test_deleting_the_first_turn_hides_its_user_row_and_deletes_its_replies`.
   - The raw rows (`_messages_of`) still hold U1, now with type
     `ENGINE_MODE_MARKER_MESSAGE_TYPE`. A1 and N1 are gone.
   - `SessionManager().get_messages(sid)` starts at U2.
   - `hidden_message_id == U1.id` and `deleted_messages == 2`.
7. `test_a_legacy_deck_stays_legacy_after_its_first_turn_is_deleted`. U1's content is
   `_PHRASE_MESSAGE`. After the delete, and after a new user row, `resolve_engine_mode(sid) == "monolith"`.
8. `test_a_graph_deck_stays_graph_when_a_legacy_phrase_follows_a_deleted_first_turn`.
9. `test_message_count_keeps_the_hidden_row_so_the_title_is_not_regenerated`. On a one-turn
   session, delete it: `get_session(sid)["message_count"] == 1`.
10. `test_the_hidden_first_message_cannot_be_deleted_again`. The second call raises
    `MessageNotFoundError` and writes no second event.
11. `test_a_duplicate_of_a_legacy_deck_whose_first_turn_was_deleted_stays_legacy_and_shows_no_chat`.
    Use the `session_with_spec_and_messages` fixture, as #323's duplicate test does.
12. `test_a_contributor_deletes_in_their_own_session_only` (`contributor_session` fixture).
    - The owner has `_PHRASE_MESSAGE`; the contributor has two turns.
    - Delete the contributor's first turn (it is hidden), then the second (it is removed).
    - The owner's rows are byte-identical, `resolve_engine_mode(contrib_sid) == "monolith"`, and
      `saver.deleted == [contrib_sid, contrib_sid]`.

Class `TestEveryReaderSeesTheDeletion`:
13. `test_the_architect_conversation_omits_the_deleted_turn`. Before the delete,
    `src.services.graph.nodes._conversation(sid)` includes U2 and A2. After deleting U2 it is
    exactly `[user U1, assistant A1, user U3, assistant A3]`.
14. `test_the_monolith_history_omits_the_deleted_turn`. Same scenario through
    `ChatService()._hydrate_chat_history(sid, ChatMessageHistory())`.

Class `TestSavePoints`:
15. `test_a_delete_leaves_every_save_point_untouched`. Take two
    `create_version(sid, "v", deck_dict={"title": "t", "slides": []})` save points before the
    delete. `_version_rows` is equal after it, and the captured `chat_history` still holds U2.
16. `test_a_save_point_taken_after_a_delete_captures_only_what_is_left`. Its `chat_history_json`
    decodes to exactly the visible rows. After a first-turn delete it holds no hidden row.

Class `TestTheDeleteIsOneAttributedTransaction`:
17. `test_a_delete_records_who_deleted_in_the_same_transaction`. There is exactly one
    `message_deleted` row, as `(username, session_id) == ("owner@example.com", pk)`, and no
    `context_cleared` row.
18. `test_a_delete_without_an_actor_is_refused_before_anything_changes`. Call with `None` and
    with `""`: `ValueError`, rows unchanged, `saver.deleted == []` and no event.
19. `test_the_graph_thread_is_deleted_on_the_deletes_own_session`. `saver.deleted == [sid]`, and
    `saver.sessions[0]` is a `Session` bound to `_session_unit_engine`.
20. `test_an_unimplemented_saver_rolls_the_whole_delete_back`. The saver raises
    `NotImplementedError`, and the first-turn delete is rolled back: U1's type is unchanged,
    A1 and N1 are present, and there is no event.
21. `test_with_the_real_saver_on_a_file_backed_database_the_delete_is_one_transaction`.
    - Use `file_backed_db` and `_seed_clearable_session`, with a real
      `SqlAlchemyCheckpointSaver(session_factory=factory)`.
    - Delete the second user row ("make slide 3 shorter"). The rows are the first two, the
      thread has 0 rows, the other thread still has 1, and there is one event.
    - This deadlocks (`database is locked`) if `delete_thread` runs without `session=`.
22. `test_a_failed_commit_rolls_back_rows_marker_event_and_thread`. Use `file_backed_db`,
    `_seed_clearable_session` and a real saver, as test 21 does, and `_patched_with_failing_commit`
    on a first-turn delete.
    - It raises `RuntimeError`. The rows are intact, U1's type is unchanged, the checkpoint and
      write rows are present, and there is no event.
    - A retry under `_patched` succeeds.

**Steps:**
- [ ] **Step 1 (test author).** Write both files and confirm they are red for the stated reasons:
  - `ModuleNotFoundError` for `src.domain.conversation_turns`;
  - `AttributeError` for `ChatService.delete_message`;
  - `ImportError` for `MessageNotFoundError` and `EVENT_MESSAGE_DELETED`.

  Leave them uncommitted.
- [ ] **Step 2 (implementer).** Make them green. Do not edit the tests.
- [ ] **Step 3.** Run `uv run pytest tests/unit/test_conversation_turns.py tests/unit/test_delete_message.py tests/unit/test_clear_context.py tests/unit/test_earliest_user_message.py -q`,
  then the full unit suite with `-n 4`. Compare failure causes.
- [ ] **Step 4.** Sabotage, one at a time. Each must turn a named test red:
  - delete the head instead of re-typing it (tests 6, 7, 9 and 11);
  - stop the turn at the first non-assistant row instead of the next user row (test 1);
  - drop the `session_id == session.id` filter from the **rows** query, so another session's user
    row is found and its turn deleted (test 4's other-session case);
  - call `delete_thread(session_id)` without `session=` (test 21 deadlocks or fails);
  - write the `UsageEvent` in its own `get_db_session()` before the `with` block (test 20);
  - `db.commit()` right after the bulk delete (test 22);
  - skip `delete_thread` (test 19).
- [ ] **Step 5.** Commit. Stage exactly
  `git add src/domain/conversation_turns.py src/database/models/usage_event.py src/api/services/session_manager.py src/api/services/chat_service.py tests/unit/test_conversation_turns.py tests/unit/test_delete_message.py`,
  then commit `feat(sessions): delete one turn of a conversation in one transaction (#317)`.

---

### Task 3: The route: editors only, own conversation only, never mid-turn

**Models:** `test=opus impl=sonnet`

**Files:** `src/api/routes/sessions.py`, `tests/unit/test_delete_message.py` (the route half)

**Interfaces introduced** (`sessions.py`):
- Import `MessageNotFoundError` in the session_manager import (`:28-32`).
- Beside `CONVERSATION_BUSY_DETAIL` (`:57-60`):

```python
# One text for every "no such message here" case (absent, another session's,
# not a user message, already hidden), so a 404 is no oracle for other ids.
MESSAGE_NOT_FOUND_DETAIL = "That message is not in this conversation."
```

Add the route directly after `clear_session_context` (it ends at `:944`).

```python
@router.delete("/{session_id}/messages/{message_id}")
async def delete_session_message(session_id: str, message_id: int):
    """Delete one message of this session's conversation, with the replies to it.

    The unit is the turn (``ChatService.delete_message``).  The session's
    earliest user message is hidden rather than deleted, the graph thread is
    deleted, and the deck, its Spec and its save points are NOT rolled back.

    Gates, in order, exactly as ``clear_session_context``: CAN_EDIT on the deck,
    then the session's creator (a contributor edits only their own session),
    then the session lock (409 while a turn or slide operation runs; released
    only if this request took it).

    Raises:
        HTTPException 401/403/404: not signed in, not an editor / not the
            session's creator, unknown session or a message not in it.
        HTTPException 409: a turn or slide operation holds the session lock.
        HTTPException 422: ``message_id`` is not an integer.
    """
    await asyncio.to_thread(
        _check_deck_permission_for_session, session_id, PermissionLevel.CAN_EDIT
    )
    await asyncio.to_thread(_require_conversation_creator, session_id)

    current_user = get_current_user()
    session_manager = get_session_manager()
    locked = await asyncio.to_thread(session_manager.acquire_session_lock, session_id)
    if not locked:
        # The lock belongs to whoever holds it: do not release it.
        raise HTTPException(status_code=409, detail=CONVERSATION_BUSY_DETAIL)

    try:
        chat_service = get_chat_service()
        result = await asyncio.to_thread(
            chat_service.delete_message, session_id, message_id, deleted_by=current_user
        )
        logger.info(
            "Conversation message deleted via API",
            extra={
                "session_id": session_id,
                "message_id": message_id,
                "deleted_by": current_user,
                "deleted_messages": result.get("deleted_messages"),
            },
        )
        return result
    except MessageNotFoundError:
        raise HTTPException(status_code=404, detail=MESSAGE_NOT_FOUND_DETAIL)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete the message") from e
    finally:
        # As in clear_session_context: a release failure must neither turn a
        # committed delete into a 500 nor mask the delete's own exception.
        try:
            await asyncio.to_thread(session_manager.release_session_lock, session_id)
        except Exception:
            logger.exception(
                "Failed to release session lock after a message delete",
                extra={"session_id": session_id},
            )
```

**Route tests.** Use the fixtures imported from `tests.unit.test_clear_context`: `client`,
`events`, `deck_gate`, `allowing_gate`, `allowing_creator`, `refusing_creator`, `session_lock`
and `as_editor`. Add one local `delete_stub_service` fixture: it patches
`src.api.routes.sessions.get_chat_service` with a stub whose
`delete_message(self, session_id, message_id, *, deleted_by)` records
`(session_id, message_id, deleted_by)`, appends `("service", session_id)` to `events`, and
returns a fixed result. A `raises=` knob makes it raise.

1. `test_the_route_is_delete_on_the_message_path`. `app.routes` holds exactly
   `("/api/sessions/{session_id}/messages/{message_id}", {"DELETE"})`.
2. `test_a_viewer_is_refused_and_nothing_is_deleted`. Under `deck_gate`: 403. The gate was called
   with `PermissionLevel.CAN_EDIT`. The creator gate, the lock and the service were never called.
3. `test_the_happy_path_runs_gate_creator_lock_service_release_in_order`. Use
   `DELETE /api/sessions/s1/messages/42` under `as_editor`.
   - `events` is exactly gate, creator, acquire, service, release.
   - The service got `("s1", 42, "editor@example.com")`, and the recorded `message_id` is the
     int `42`, not the string.
   - The body is the service's result.
4. `test_an_editor_who_is_not_the_sessions_creator_is_refused`. 403, with no acquire and no
   service call.
5. `test_a_turn_in_flight_is_a_409_and_the_lock_is_not_released`. `grant=False`. The response is
   409 with detail `CONVERSATION_BUSY_DETAIL`. There is no service call and `released == []`.
6. `test_a_message_not_in_this_conversation_is_a_404_and_the_lock_is_released`. The stub raises
   `MessageNotFoundError`. The detail is `MESSAGE_NOT_FOUND_DETAIL`, and `released == ["s1"]`.
7. `test_a_missing_session_is_a_404_and_the_lock_is_released`. The stub raises
   `SessionNotFoundError`.
8. `test_an_unexpected_failure_is_a_500_and_the_lock_is_released`. The stub raises
   `RuntimeError`.
9. `test_a_lock_release_failure_after_a_committed_delete_is_still_a_200`. Mirror #323's
   `test_a_lock_release_failure_after_a_committed_clear_is_still_a_200`.
10. `test_a_non_integer_message_id_is_a_422_before_any_gate`. `DELETE …/messages/abc` gives 422,
    and `events == []`.

**Steps:**
- [ ] **Step 1 (test author).** Write the tests. They are red with 405 or 404 because the route
  is absent, and `ImportError` on `MESSAGE_NOT_FOUND_DETAIL`. Leave them uncommitted.
- [ ] **Step 2 (implementer).** Make them green. Do not edit the tests.
- [ ] **Step 3.** Run `uv run pytest tests/unit/test_delete_message.py tests/unit/test_route_authz_coverage.py tests/unit/test_clear_context.py -q`,
  then the full unit suite with `-n 4`.
- [ ] **Step 4.** Sabotage, one at a time. Each must turn a named test red:
  - swap the creator gate and the lock (test 3, and test 4's "no acquire");
  - release in the 409 branch (test 5);
  - drop `PermissionLevel.CAN_EDIT` so the default `CAN_VIEW` applies (test 2);
  - map `MessageNotFoundError` to 500 (test 6);
  - type `message_id: str` (test 3's `isinstance` and test 10).
- [ ] **Step 5.** Commit. Stage exactly `git add src/api/routes/sessions.py tests/unit/test_delete_message.py`,
  then commit `feat(sessions): delete a message from your own conversation, editors only, never mid-turn (#317)`.

---

### Task 4: Graph tests: the architect and the checkpoint forget a deleted turn; a reset starts fresh; both transports

**Models:** `test=opus impl=sonnet`. The task adds tests of code Tasks 1–3 built. The implementer
tier only fixes real defects the tests expose, and a stop escalates straight to opus.

**Files:** **new** `tests/integration/test_delete_message_graph_turn.py`, and
`.github/workflows/test.yml` (the integration-graph run block)

**Harness.**
- Use `graph_turn_env` (`tests/integration/conftest.py:765-849`). Import `graph_chat_env` from
  `tests.integration.test_graph_mode_turn` and `async_turn_env` (plus its `REPLY` and `AUTHOR`)
  from `tests.integration.test_architect_reply_is_persisted`. Import by name only, never a test
  function or class.
- Reach the delete as #323's `_clear_reaches` does
  (`tests/integration/test_clear_context_graph_turn.py:87-95`): patch
  `src.core.database.get_db_session` with `_make_fake_db(env.factory)`, and
  `src.core.checkpointer.get_checkpointer` with
  `lambda: SqlAlchemyCheckpointSaver(session_factory=env.factory)`.
- Use a scan helper that reads **every** checkpoint, not just the latest:
  ```python
  def _thread_holds(saver, sid: str, needle: str) -> bool:
      config = {"configurable": {"thread_id": sid, "checkpoint_ns": ""}}
      return any(
          needle in repr(t.checkpoint) or needle in repr(t.pending_writes)
          for t in saver.list(config)
      )
  ```
- Use distinctive sentinels that no stub produces:
  - `ALPHA = "ALPHA-KEEP build me a deck about puffins"`;
  - `BETA = "BETA-DELETE make slide 3 shorter"`;
  - `GAMMA = "GAMMA-KEEP make slide 2 punchier"`;
  - `DELTA = "DELTA-ASK make slide 1 punchier"`.

  The recorder's own replies are `"Building 4 slide(s)."` and `"Editing slide(s) [<positions>]."`
  (`tests/integration/conftest_stub_skills.py:316-344`).
- Write the module docstring honestly: the model is stubbed, so these tests prove what each
  agent is **given** and what the checkpoint **holds**.

**Tests:**

1. `test_after_deleting_a_turn_neither_the_architect_nor_the_checkpoint_carries_it`. It runs
   three turns, deletes the **middle** one, then runs a fourth (review F8; the reviewer's probe
   `test_delete_middle_of_three` showed this exact shape).
   1. **Turn 1.** `configure(slide_count=4)`. Persist `ALPHA` (`user_input`) with
      `get_session_manager().add_message`, then `env.run(initial={"architect_message": ALPHA})`.
   2. **Turn 2.** `configure(slide_count=4, edit_target_positions={2})`. Persist `BETA`, keep its
      returned `id`, and run. The reply is `"Editing slide(s) [2]."`.
   3. **Turn 3.** `configure(slide_count=4, edit_target_positions={1})`. Persist `GAMMA` and run.
      The reply is `"Editing slide(s) [1]."`.
   4. **Non-vacuity.**
      - `_thread_holds(saver, sid, "BETA-DELETE")`, `_thread_holds(saver, sid, "Editing slide(s) [2].")`
        and `_thread_holds(saver, sid, "GAMMA-KEEP")` are all True.
      - Record the slide rows' HTML, the deck row's columns and `deck_spec_json`. Slides 2 and 1
        already carry `edited_brief(...)` from turns 2 and 3.
      - Record `load_conversation_pin(env.factory, sid)`.
   5. **Delete turn 2.** Call `ChatService().delete_message(sid, beta_id, deleted_by="owner@example.com")`.
      - `deleted_messages == 3`: BETA, its reply, and its deck-review advisory.
      - `hidden_message_id is None`.
      - `list(saver.list(config)) == []`.
      - `env.messages()` contents are
        `[ALPHA, "Building 4 slide(s).", _advisory_text([]), GAMMA, "Editing slide(s) [1].", _advisory_text([])]`
        (`from src.services.graph.nodes import _advisory_text`).
      - **Not rolled back:** the deck row's columns, every slide row's HTML and `deck_spec_json`
        are unchanged, so slide 2 keeps turn 2's edit.
      - The pin is unchanged, and `resolve_engine_mode(sid) == "graph"`.
   6. **Turn 4.** `reset_observations()`, `configure(slide_count=4, edit_target_positions={0})`.
      Persist `DELTA` and run.
   7. **What every agent was given.**
      - The architect payload's `conversation` is exactly
        `[{"role":"user","content":ALPHA}, {"role":"assistant","content":"Building 4 slide(s)."}, {"role":"user","content":GAMMA}, {"role":"assistant","content":"Editing slide(s) [1]."}, {"role":"user","content":DELTA}]`.
      - `current_deck_spec` equals the recorded spec.
      - For **every** call in `env.recorder.calls`, `repr(call["payload"])` contains neither
        `"BETA-DELETE"` nor `"Editing slide(s) [2]."`.
      - The turn is `intent == "edit"` with `error_state is None`.
   8. **What the checkpoint holds.**
      - `_thread_holds` is False for `"BETA-DELETE"` and `"Editing slide(s) [2]."`.
      - It is **also False for `"GAMMA-KEEP"`**. Turn 3's checkpoints went with the thread
        (D5's whole-thread cost); the kept turn reaches the architect from its rows only.
      - As a positive control, it is True for `"DELTA-ASK"`.
2. `test_after_a_reset_no_message_from_before_reaches_any_agent_or_the_checkpoint`. This is the
   fresh-start property (D1).
   - **Turn 1.** Persist `"SENTINEL-FIRST build puffins"` and run a build of 3 slides. Then
     persist a user row `"SENTINEL-SECOND add a diet slide"` and an `llm_response`
     `"SENTINEL-REPLY diet added"`.
   - **Non-vacuity.** `_thread_holds(saver, sid, "SENTINEL-FIRST")` is True.
   - **Reset.** `ChatService().clear_context(sid, cleared_by="owner@example.com")`.
   - **Next turn.** Persist `"NEW-ASK shorten slide 2"` and run an edit of `{1}`.
   - **Assert:**
     - no recorder payload contains `"SENTINEL"`;
     - `_thread_holds(saver, sid, "SENTINEL")` is False;
     - `conversation == [{"role": "user", "content": "NEW-ASK shorten slide 2"}]`;
     - `_thread_holds(saver, sid, "NEW-ASK")` is True, as the positive control.
3. `test_a_polling_turn_is_one_deletable_turn_and_its_poll_rows_go_with_it` (`async_turn_env`).
   This is the async transport, through `process_chat_request` and `poll_chat`.
   1. `rid1 = env.run("POLL-ONE draft puffins")`, then `rid2 = env.run("POLL-TWO tighten the intro")`.
   2. The user rows are not in the poll events (`chat.py:913`). Their ids come from the
      transcript read `GET /messages` uses: `SessionManager().get_messages(sid)` has a
      `user_query` row with content `"POLL-TWO …"` and an integer `id`.
   3. Delete it with `deleted_by=AUTHOR`.
   4. Assert:
      - `get_messages_for_request(rid2) == []`;
      - `env.poll(rid2)["events"] == []`;
      - `env.poll(rid1)["events"]` still holds `REPLY`;
      - the thread has no checkpoints.
   5. Then `env.run("POLL-THREE make it shorter")`. The last architect payload's
      `conversation` contains no `"POLL-TWO"`.
4. `test_an_sse_turn_is_one_deletable_turn` (`graph_chat_env`).
   1. `env.run(message="SSE-ONE build me a deck about puffins", is_first_message=True)`, then
      `env.run(message="SSE-TWO add a summary slide", is_first_message=False)`.
   2. The SSE user rows are `user_input` with `request_id` None. Take SSE-TWO's id from
      `get_messages`.
   3. Delete it. `get_messages` is now exactly turn 1's rows, compared by content and type, and
      the thread has no checkpoints.

**CI wiring:** add `tests/integration/test_delete_message_graph_turn.py \` to the integration-graph
list directly after `tests/integration/test_clear_context_graph_turn.py \` (`test.yml:465`).
Without it, `tests/unit/test_ci_collects_integration_tests.py` fails.

**Steps:**
- [ ] **Step 1 (test author).** Write the tests. After Tasks 1–3 they should be green. Prove they
  can fail with Step 4.
- [ ] **Step 2.** Add the `test.yml` line.
- [ ] **Step 3.** Run `uv run pytest tests/integration/test_delete_message_graph_turn.py tests/integration/test_clear_context_graph_turn.py tests/integration/test_graph_orchestration.py tests/integration/test_architect_reply_is_persisted.py tests/integration/test_graph_mode_turn.py tests/unit/test_ci_collects_integration_tests.py -q`.
- [ ] **Step 4.** Sabotage, one at a time. Each must turn a named test red:
  - remove `delete_thread` from `delete_message` (test 1 step 8, and tests 3 and 4);
  - remove it from `clear_context` (test 2's checkpoint scan);
  - drop the marker re-type in `clear_context` (test 2's `conversation` and payload scan);
  - make `turn_message_ids` return only the head (test 1's row list and payload scan, test 3's
    `get_messages_for_request`).
- [ ] **Step 5.** Commit. Stage exactly
  `git add tests/integration/test_delete_message_graph_turn.py .github/workflows/test.yml`, then
  commit `test(sessions): a deleted turn and a reset reach no agent and no checkpoint (#317)`.

---

### Task 5: Full-stack route test (`tests/integration/test_delete_message_routes.py`)

**Models:** `test=opus impl=sonnet`. As in Task 4, the implementer only fixes real defects, and a
stop escalates to opus.

**Files:** **new** `tests/integration/test_delete_message_routes.py`, and
`.github/workflows/test.yml` (the integration-general run block)

**Harness.**
- Import the `deck` fixture and `_sign_in`, `_ok`, `_session`, `_messages`, `_slide_deck`,
  `_session_pk`, `_is_processing`, `_has_thread`, `OWNER`, `EDITOR` and `_GET_DB_SESSION_TARGETS`
  from `tests.integration.test_clear_chat_routes`.
- Seeding: that fixture already ran `plan` and `build`. Each test first runs the tour's
  `review` and `edit` stages through `POST /api/tour/demo-deck/{sid}/stages/{stage}`, so the
  transcript is two turns:
  `[chat_prompt (user), plan reply, review advisory (info)]` and
  `[edit user_prompt (user), edit architect_reply]`.
- `_load_fixture()` gives the expected strings.
- Add `_delete(sid, message_id)`, which runs
  `with TestClient(app) as c: return c.delete(f"/api/sessions/{sid}/messages/{message_id}")`.
- Add `_deleted_events(factory)`, which reads `message_deleted` rows as `(username, session_id)`.

**Tests:**
1. `test_deleting_a_turn_through_the_routes_keeps_the_deck_spec_and_save_points`.
   1. Before the delete:
      - take a real save point with `POST /api/slides/versions/create`, and record its preview
        `chat_history` from `GET /api/slides/versions/{n}?session_id=…`;
      - record the slides' HTML and `deck_spec`;
      - put a checkpoint on the thread, as the fixture does.
   2. `_delete(sid, <edit user_prompt id from GET /messages>)` answers 200 with
      `deleted_messages == 2` and `hidden_message_id is None`.
   3. Assert:
      - `GET /sessions/{sid}` messages' contents are
        `[chat_prompt, plan reply, review advisory]`, and `GET /messages` matches with ids;
      - the slides' HTML and `deck_spec` are unchanged, so the edit's spec change at
        `stages.edit.position` is **kept**;
      - the preview `chat_history` is deep-equal to the recorded one and still contains the
        deleted prompt;
      - the thread is gone and `_deleted_events == [(OWNER, pk)]`.
   4. A second delete of the same id is 404 with `MESSAGE_NOT_FOUND_DETAIL`. A delete of the plan
      reply's (assistant) id is 404.
2. `test_deleting_the_first_turn_hides_it_and_keeps_the_engine_and_pin`.
   - Delete the `chat_prompt` id: 200, `hidden_message_id ==` that id, and `deleted_messages == 2`
     (the plan reply and the advisory).
   - `GET /messages` returns only the edit turn.
   - `resolve_engine_mode(sid) == "graph"`, `load_conversation_pin(factory, sid)` is unchanged,
     and `GET /sessions/{sid}`'s `message_count` equals the remaining rows plus 1 (the hidden
     row).
   - A delete of the same id again is 404.
3. `test_another_editor_cannot_delete_from_the_owners_conversation`.
   - Add a real `DeckContributor` row for `EDITOR` with CAN_EDIT and sign in as `EDITOR`.
   - Positive control: `my_permission == "CAN_EDIT"`.
   - The delete is 403 with `"session creator"` in the detail, and `_is_processing` is False.
   - Signed in as `OWNER` again, the transcript, the thread and the empty event list are
     unchanged.
4. `test_a_delete_while_a_turn_holds_the_session_lock_is_a_409`.
   - With `get_session_manager().acquire_session_lock(sid)` held, the delete is 409 with
     `CONVERSATION_BUSY_DETAIL`. Nothing changed, and `_is_processing` is still True.
   - After a release, the delete succeeds and `_is_processing` is False.
5. `test_a_message_id_from_another_session_is_a_404_and_neither_conversation_changes`.
   - Create a second session with `_phase1_create_session(OWNER)` and take its prompt row's id
     from `GET /sessions/{other}/messages`.
   - `_delete(sid, other_id)` is 404, and both transcripts and both event lists are unchanged.

**CI wiring:** add `tests/integration/test_delete_message_routes.py \` to the integration-general
list after `tests/integration/test_comments_removed.py \` and before
`tests/integration/test_export_parity.py \` (`test.yml:555-556`, alphabetical).

**Steps:**
- [ ] **Step 1 (test author).** Write the test. It should be green after Tasks 1–3. Prove it with
  Step 4.
- [ ] **Step 2.** Add the CI line.
- [ ] **Step 3.** Run `DATABRICKS_HOST= DATABRICKS_TOKEN= uv run pytest tests/integration/test_delete_message_routes.py tests/integration/test_clear_chat_routes.py tests/integration/test_savepoint_e2e.py tests/unit/test_ci_collects_integration_tests.py -q`.
- [ ] **Step 4.** Sabotage, one at a time. Each must turn a named test red:
  - remove the creator gate from the route (test 3);
  - release the lock on a 409 (test 4);
  - drop the session filter from the rows query in `delete_message` (test 5);
  - delete the head on a first-turn delete (test 2);
  - make `delete_message` delete `SlideDeckVersion` rows (test 1's preview check).
- [ ] **Step 5.** Commit. Stage exactly
  `git add tests/integration/test_delete_message_routes.py .github/workflows/test.yml`, then
  commit `test(sessions): delete a message end to end through the real routes (#317)`.

---

### Task 6: Frontend foundations: ids on `Message`, the API calls, the turn helpers, the copy, the transport signal

**Models:** `test=opus impl=haiku`. The plan gives every line of production code. The tests
carry the judgement.

**Files:**
- `frontend/src/types/message.ts`
- `frontend/src/api/conversation.ts` and `conversation.test.ts` (extended)
- **new** `frontend/src/utils/conversationTurns.ts` and `.test.ts`
- **new** `frontend/src/components/ChatPanel/deleteMessageCopy.ts` and `.test.ts`
- **new** `frontend/src/services/__tests__/turnEndSignal.test.ts`

**`message.ts`.** Add `id?: number` as the **first** field of `Message`, above `role`. That
keeps it away from #321's `details?` insert after `tool_call_id`.

```ts
  /** Persisted SessionMessage.id. Absent on a message this panel has shown but not yet matched
   *  to its row (a just-sent or streamed one); only messages with an id can be deleted (#317). */
  id?: number;
```

**`conversation.ts`.** Add the following beside `clearChat`. The import becomes
`import { ApiError, type SessionMessage } from '../services/api';`.

```ts
export interface DeleteMessageResult {
  status: 'deleted';
  session_id: string;
  message_id: number;
  deleted_messages: number;
  hidden_message_id: number | null;
}

export interface SessionMessagesResult {
  session_id: string;
  messages: SessionMessage[];
  count: number;
}

  /** DELETE /api/sessions/{id}/messages/{messageId}: deletes that message and its replies, in THIS session only. */
  async deleteMessage(sessionId: string, messageId: number): Promise<DeleteMessageResult> {
    const response = await fetch(
      `${API_BASE_URL}/api/sessions/${encodeURIComponent(sessionId)}/messages/${encodeURIComponent(String(messageId))}`,
      { method: 'DELETE' },
    );
    if (!response.ok) throw await errorFrom(response, 'Failed to delete the message');
    return response.json();
  },

  /**
   * GET /api/sessions/{id}/messages: the persisted conversation, with ids (session creator only).
   * With `limit`, only the newest `limit` rows (the backend keeps `messages[-limit:]`).
   */
  async listMessages(sessionId: string, limit?: number): Promise<SessionMessagesResult> {
    const query = limit != null ? `?limit=${encodeURIComponent(String(limit))}` : '';
    const response = await fetch(
      `${API_BASE_URL}/api/sessions/${encodeURIComponent(sessionId)}/messages${query}`,
    );
    if (!response.ok) throw await errorFrom(response, 'Failed to load the conversation');
    return response.json();
  },
```

**`conversationTurns.ts`** (new):

```ts
/**
 * Conversation turns in the chat panel (#317). A turn is a user message and every message after
 * it up to (not including) the next user message: the same span the backend deletes for
 * DELETE /api/sessions/{id}/messages/{messageId} (src/domain/conversation_turns.py).
 */
import type { Message } from '../types/message';
import type { SessionMessage } from '../services/api';

/** `messages` without the turn whose user message has id `userMessageId`; unchanged if there is none. */
export function withoutTurn(messages: Message[], userMessageId: number): Message[] {
  const start = messages.findIndex(m => m.role === 'user' && m.id === userMessageId);
  if (start === -1) return messages;
  let end = start + 1;
  while (end < messages.length && messages[end].role !== 'user') end += 1;
  return [...messages.slice(0, start), ...messages.slice(end)];
}

/**
 * Give the panel's id-less user messages the ids of the persisted rows they are.
 *
 * A message sent in this panel is shown before the server stores it, so it has no id, and the
 * delete action needs one. After a turn the panel lists the persisted rows and pairs them from
 * the newest: each id-less user message takes the newest unpaired persisted user row with exactly
 * the same content that is older than every row paired or carried AFTER it and newer than every
 * row carried BEFORE it. Pairing from the newest keeps a send that failed before it was stored
 * (often retried with the same text) from taking the retry's id.
 *
 * Only adds ids: never changes content, order or any other message. A message with no identical
 * row keeps no id and gets one on the next full load. Returns `panel` itself when nothing changed.
 */
export function withPersistedUserIds(panel: Message[], persisted: SessionMessage[]): Message[] {
  const rows = persisted.filter(r => r.role === 'user' && typeof r.id === 'number');
  const rowIndex = (id: number) => rows.findIndex(r => r.id === id);
  const taken = new Set(panel.flatMap(m => (typeof m.id === 'number' ? [m.id] : [])));
  // floor[p]: index (in rows) of the newest row already carried by a message at or before p.
  // A message may only pair with a row NEWER than that, so it never jumps behind an identified one.
  const floor: number[] = [];
  let seen = -1;
  panel.forEach((m, i) => {
    if (m.role === 'user' && typeof m.id === 'number') seen = Math.max(seen, rowIndex(m.id));
    floor[i] = seen;
  });
  const next = [...panel];
  let limit = rows.length;  // only rows[floor[p]+1 .. limit) may still be paired
  let changed = false;
  for (let p = next.length - 1; p >= 0; p -= 1) {
    const message = next[p];
    if (message.role !== 'user') continue;
    if (typeof message.id === 'number') {
      const at = rowIndex(message.id);
      if (at !== -1 && at < limit) limit = at;
      continue;
    }
    for (let r = limit - 1; r > floor[p]; r -= 1) {
      const row = rows[r];
      if (!taken.has(row.id) && row.content === message.content) {
        next[p] = { ...message, id: row.id };
        taken.add(row.id);
        limit = r;
        changed = true;
        break;
      }
    }
  }
  return changed ? next : panel;
}
```

**`deleteMessageCopy.ts`** (new, complete, in the shape of `clearChatCopy.ts`):

```ts
/**
 * Copy for the chat panel's per-message delete (#317, plan decision D14).
 * The dialog says the deck is not rolled back: deleting a message never undoes what it changed.
 */
export const DELETE_MESSAGE_TOOLTIP = 'Delete this message and the replies to it';
export const DELETE_MESSAGE_DIALOG_TITLE = 'Delete this message?';
export const DELETE_MESSAGE_DIALOG_MESSAGE =
  "This deletes your message and the assistant's replies to it, so the assistant won't see them "
  + 'again. Anything it changed in your slides or the Spec stays as it is; it is not rolled back. '
  + "This can't be undone.";
export const DELETE_MESSAGE_CONFIRM_LABEL = 'Delete';
export const DELETE_MESSAGE_BUSY =
  'Something is still running on this deck. Wait for it to finish, then delete the message.';
export const DELETE_MESSAGE_FORBIDDEN =
  'Only editors can delete messages, and only in their own conversation.';
export const DELETE_MESSAGE_GONE =
  'That message is no longer in this conversation. Reload the page to see the current conversation.';
export const DELETE_MESSAGE_FAILED =
  "Couldn't delete the message. Reload the page to see the current conversation, then try again.";

/** Maps a failed delete to its message, by HTTP status and never by the server's detail text. */
export function deleteMessageErrorMessage(err: unknown): string {
  // Duck-typed on `status`, not `instanceof`, so a test that mocks the API module still maps correctly.
  const status = typeof err === 'object' && err !== null && 'status' in err
    ? (err as { status: unknown }).status : undefined;
  if (status === 409) return DELETE_MESSAGE_BUSY;
  if (status === 403) return DELETE_MESSAGE_FORBIDDEN;
  if (status === 404) return DELETE_MESSAGE_GONE;
  return DELETE_MESSAGE_FAILED;
}
```

**Tests:**
- `conversation.test.ts`. Extend it, reusing its `jsonResponse`, `stubFetch` and `onlyRequest`
  helpers.
  - `deleteMessage('sess 1', 42)`:
    - sends one `DELETE` to a URL ending `/api/sessions/sess%201/messages/42`;
    - resolves to the parsed body;
    - a 404 `{detail:'gone'}` rejects with `ApiError` status 404 and message `'gone'`;
    - a 409 rejects with status 409;
    - a 500 with a non-JSON body rejects with `'Failed to delete the message'`.
  - `listMessages('sess 1')`:
    - sends one `GET` (no `method`, or `'GET'`) to a URL ending `/api/sessions/sess%201/messages`;
    - resolves to the body;
    - a 403 rejects with `ApiError` status 403.
  - `listMessages('sess 1', 200)` sends one `GET` to a URL ending
    `/api/sessions/sess%201/messages?limit=200`.
- `conversationTurns.test.ts`.
  - `withoutTurn`:
    - it removes the user message and every message up to the next user message;
    - a `role: 'tool'` message (and a tool-call assistant message) inside the turn is removed with
      it (review F9);
    - the last turn runs to the end;
    - assistant messages before the first user message are never removed;
    - an unknown id returns the same array (`toBe`);
    - a message without an id is never matched.
  - `withPersistedUserIds`:
    1. It assigns ids to id-less user messages by identical content, in order.
    2. **Failed then retried:** for `[U1(id 1), U('retry'), U('retry')]` against rows
       `[1, 9 'retry']`, only the **last** message gets 9.
    3. A failed send in the middle does not shift later ids.
    4. A row id already carried by a panel message is never assigned twice.
    5. Rows without a numeric `id` are ignored (`setupMocks`' canned rows).
    6. A row with different content is not paired (image-injected text).
    7. Assistant messages, content and order are untouched (deep-equal, except added `id`s).
    8. When nothing is paired it returns `panel` itself (`toBe`).
    9. A row older than an already-identified later message is never paired with an id-less
       message that comes after it.
- `deleteMessageCopy.test.ts`.
  - 409, 403, 404, 500 and `{}` map to BUSY, FORBIDDEN, GONE, FAILED and FAILED.
  - `DELETE_MESSAGE_DIALOG_MESSAGE` contains `"slides"`, `"Spec"`, `"not rolled back"` and
    `"can't be undone"`, and does not contain `"turn"`. That pins D9's promise in the copy.
  - Every exported string equals the text pasted above, exactly as #323's "uses the agreed copy"
    test does.
- `turnEndSignal.test.ts`. This is the transport evidence that both transports end a turn with a
  signal the panel can hang the id read on. Stub `fetch` with `vi.stubGlobal` and use fake timers
  for polling, as `slideReadyEvent.test.ts:239-338` does.
  1. **Polling, completed.** `api.startPolling(...)`. The submit answers `{request_id}`. The first
     poll is `running` with an assistant event carrying `message_id: 7`. The second is
     `completed`. `onEvent` received the assistant event (with `message_id` 7) and then exactly
     one `complete`.
  2. **Polling, error.** A poll answers `status: 'error'`. `onError` is called once and no
     `complete` is sent.
  3. **SSE, complete.** `api.streamChat(...)`, with `fetch` resolving a `Response` whose body is
     `data: {"type":"assistant","content":"hi"}\n\ndata: {"type":"complete"}\n\n`. `onEvent`
     receives `assistant`, then `complete`.
  4. **SSE, error event.** A `data: {"type":"error","error":"x"}` body reaches `onEvent` as
     `error`.

**Steps:**
- [ ] **Step 1 (test author).** Write the tests. They are red on missing modules and exports;
  `turnEndSignal.test.ts` is green today. Leave them uncommitted.
- [ ] **Step 2 (implementer).** Write the code above. Do not edit the tests.
- [ ] **Step 3.** Run `cd frontend && npx vitest run src/api/conversation.test.ts src/utils/conversationTurns.test.ts src/components/ChatPanel/deleteMessageCopy.test.ts src/services/__tests__/turnEndSignal.test.ts && npx tsc -b`.
  Then apply the lint gate to the touched files. New files must be clean.
- [ ] **Step 4.** Sabotage, one at a time. Each must turn a named test red:
  - pair from the oldest instead of the newest (`withPersistedUserIds` test 2);
  - drop the `taken` check (test 4);
  - stop `withoutTurn` at the first non-assistant message (its `tool`-message case, F9);
  - drop the `?limit=` query from `listMessages` (its `limit` case);
  - map 404 to FAILED;
  - send `POST` from `deleteMessage`;
  - in `turnEndSignal`, remove the synthesised `complete` in `startPolling` (`api.ts:1177-1185`),
    then revert it. This one only proves that test bites.
- [ ] **Step 5.** Commit. Stage exactly
  `git add frontend/src/types/message.ts frontend/src/api/conversation.ts frontend/src/api/conversation.test.ts frontend/src/utils/conversationTurns.ts frontend/src/utils/conversationTurns.test.ts frontend/src/components/ChatPanel/deleteMessageCopy.ts frontend/src/components/ChatPanel/deleteMessageCopy.test.ts frontend/src/services/__tests__/turnEndSignal.test.ts`,
  then commit `feat(frontend): message ids, the delete and list calls, and conversation-turn helpers (#317)`.

---

### Task 7: The delete action in the chat panel

**Models:** `test=opus impl=sonnet`

**Files:**
- `frontend/src/components/ChatPanel/MessageList.tsx`
- `frontend/src/components/ChatPanel/ChatPanel.tsx`
- **new** `frontend/src/components/ChatPanel/ChatPanel.deleteMessage.test.tsx`

**`MessageList.tsx`.**
- Import `Trash2` from `lucide-react`, `Button` from `@/ui/button` and `DELETE_MESSAGE_TOOLTIP`
  from `./deleteMessageCopy`.
- Add an exported interface, and an optional prop on `MessageListProps`:

```tsx
/** #317: the per-message delete action. Offered on the user's own persisted messages only. */
export interface MessageDeleteAction {
  disabled: boolean;
  onDelete: (messageId: number) => void;
}
// in MessageListProps:
  /** Absent: no message offers delete (a viewer, an unsaved session, a save-point preview). */
  deleteAction?: MessageDeleteAction;
```

- Destructure `deleteAction`. Replace the map at `:23-25` with:

```tsx
      {messages.map((message, index) => (
        <div key={index} className="group relative" data-testid="chat-message-row">
          <Message message={message} />
          {deleteAction && message.role === 'user' && typeof message.id === 'number' && (
            <Button
              type="button"
              data-testid="delete-message-button"
              size="icon"
              variant="ghost"
              className="absolute left-0 top-1/2 size-7 -translate-y-1/2 opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
              title={DELETE_MESSAGE_TOOLTIP}
              aria-label={DELETE_MESSAGE_TOOLTIP}
              disabled={deleteAction.disabled}
              onClick={() => deleteAction.onDelete(message.id as number)}
            >
              <Trash2 />
            </Button>
          )}
        </div>
      ))}
```

**`ChatPanel.tsx`** (only the places listed under Global constraints):
- **Imports:** `withoutTurn` and `withPersistedUserIds` from `../../utils/conversationTurns`, and
  the `deleteMessageCopy` exports.
- **State:** declare these beside the Clear chat state at `:70-73`:
  - `const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null);`
  - `const [isDeletingMessage, setIsDeletingMessage] = useState(false);`
- **Reset block** (`:85-91`): add `setPendingDeleteId(null);` and `setIsDeletingMessage(false);`.
- **Load map** (`:125`): add `id: msg.id,` as the **first** property of the mapped object, above
  `role:`, to stay clear of #321's `details:` line.
- **Send sequence (review F1).** Beside the other refs (`:74-76`), add
  `const sendSeqRef = useRef(0);  // #317: the send a turn-end id read belongs to`. At module
  level, above the component, add:
  ```tsx
  // #317: the turn-end id read asks for the newest rows only (GET …/messages keeps messages[-limit:]).
  const MESSAGE_ID_READ_LIMIT = 200;
  ```
- **Send guard:** after the `isClearing` guard (`:215-218`), add
  `if (isDeletingMessage) { return; }`. After the persistence check (`:222-224`), add
  `const sentTo = sessionId;`. Directly after the optimistic `setMessages` (`:233-240`), add
  `const seq = ++sendSeqRef.current;`.
- **The id read at turn end.** Add this function above `handleSendMessage`:

```tsx
  // #317: a message sent here has no id until the panel matches it to its stored row, and only a
  // message with an id offers delete. Read the stored conversation and add ids; never replace.
  const refreshMessageIds = (target: string | null, seq: number) => {
    if (!target) return;
    Promise.resolve()
      .then(() => conversationApi.listMessages(target, MESSAGE_ID_READ_LIMIT))
      .then(result => {
        // Dropped after a session switch, and after a newer send: that send's message (often the
        // same text) would otherwise take this turn's row, and a delete would remove the wrong
        // turn. The next turn's read pairs everything.
        if (sendSeqRef.current !== seq || currentSessionIdRef.current !== target) return;
        if (!Array.isArray(result?.messages)) return;
        setMessages(prev => withPersistedUserIds(prev, result.messages));
      })
      .catch(() => { /* the ids arrive with the next load; the delete action waits for them */ });
  };
```

  Call `refreshMessageIds(sentTo, seq);` in three places:
  - as the last statement of the `'complete'` case, after `refreshConfig();` at `:368`;
  - as the last statement of the `'error'` case (`:316-321`);
  - as the last statement of the `onError` callback (`:398-404`).

  `Promise.resolve().then(...)` makes a missing `listMessages` (a test's module mock) a caught
  rejection, not a thrown error.
- **Visibility and handler.** Put these beside `showClearChat` (`:410-413`):

```tsx
  // Delete a message (#317): shown to editors on a persisted session, never in a save-point preview.
  const canDeleteMessages = isSessionPersisted && canEditConversation(myPermission) && !previewMessages;
  const deleteMessageDisabled = isLoading || isClearing || isDeletingMessage || disabled;

  const handleConfirmDeleteMessage = async () => {
    const messageId = pendingDeleteId;
    if (!sessionId || messageId == null || isDeletingMessage) return;
    const target = sessionId;
    setPendingDeleteId(null);
    setIsDeletingMessage(true);
    setError(null);
    try {
      await conversationApi.deleteMessage(target, messageId);
      if (currentSessionIdRef.current !== target) return;  // the user moved on; leave the new session alone
      setMessages(prev => withoutTurn(prev, messageId));
      setLastReplacement(null);
    } catch (err) {
      if (currentSessionIdRef.current !== target) return;
      setError(deleteMessageErrorMessage(err));
    } finally {
      if (currentSessionIdRef.current === target) setIsDeletingMessage(false);
    }
  };
```

  It must not call `onSlidesGenerated`, `api.getSlides`, `api.getSession` or `refreshConfig`.
- **Clear chat while deleting:** append `|| isDeletingMessage` to `clearChatDisabled` (`:412-413`).
- **Dialog:** after the Clear chat `ConfirmDialog` (`:482-491`), render
  `<ConfirmDialog open={pendingDeleteId !== null} title={DELETE_MESSAGE_DIALOG_TITLE} message={DELETE_MESSAGE_DIALOG_MESSAGE} confirmLabel={DELETE_MESSAGE_CONFIRM_LABEL} cancelLabel="Cancel" variant="danger" onConfirm={handleConfirmDeleteMessage} onCancel={() => setPendingDeleteId(null)} />`.
- **MessageList** (`:494`): add
  `deleteAction={canDeleteMessages ? { disabled: deleteMessageDisabled, onDelete: setPendingDeleteId } : undefined}`.
- **Input:** put `|| isDeletingMessage` on **its own new line** in the `ChatInput` `disabled`
  expression (`:505-508`), below `|| isClearing`. Do not touch `placeholder`.

**Tests** (`ChatPanel.deleteMessage.test.tsx`).

Copy the mock scaffold of `ChatPanel.clearChat.test.tsx:14-66`, with these differences:
- **do not** mock `./MessageList`, so the real list and the real `Message` render;
- mock `../../api/conversation` as `{ conversationApi: { clearChat, deleteMessage, listMessages } }`;
- `sendChatMessage.mockImplementation((_s, _m, _c, onEvent, onError) => { captured = { onEvent, onError }; return () => {}; })`.

By default, `getSession` resolves `messages` `[U(1,'Build a deck'), A(2,'Built 3 slides.'), U(3,'Make the title punchier'), A(4,'Edited slide 1.')]`
with `my_permission: 'CAN_MANAGE'`.

Use these helpers:
- `deleteButtons()` returns `screen.queryAllByTestId('delete-message-button')`;
- `rowWith(text)` returns the `chat-message-row` containing the text;
- the confirm is always scoped:
  `within(screen.getByTestId('confirm-dialog')).getByRole('button', { name: 'Delete' })`.

1. `it.each(['CAN_EDIT','CAN_MANAGE'])` `offers delete on each of the user's persisted messages to an editor (%s)`.
   There are exactly 2 buttons, inside the rows of U1 and U3, and none on assistant rows.
2. `does not offer delete to a viewer, without a permission, before the session is persisted, or in a save-point preview`.
   Four cases, each with 0 buttons.
3. `disables delete while a turn runs, while the panel is read-only, and while a clear runs`.
   - After `mock-send`, every button is disabled.
   - With `disabled` true, every button is disabled.
   - While `clearChat` is pending (render with `hasDeckSpec` so Clear chat shows), every button
     is disabled.
4. `cancelling the confirmation deletes nothing`.
5. `the confirmation says the deck is not rolled back`. The dialog shows
   `DELETE_MESSAGE_DIALOG_TITLE` and `DELETE_MESSAGE_DIALOG_MESSAGE`.
6. `confirming deletes that message and its replies for this session only, without refetching the deck`.
   - `deleteMessage` was called once with `('sess-1', 3)`.
   - The panel shows U1 and A2 only.
   - `getSlides` was never called, `onSlidesGenerated` was never called, and `getSession` was
     called once.
7. `deleting the first message removes its turn and keeps the rest`. Deleting id 1 leaves U3 and A4.
8. `it.each([[409, DELETE_MESSAGE_BUSY], [403, DELETE_MESSAGE_FORBIDDEN], [404, DELETE_MESSAGE_GONE], [500, DELETE_MESSAGE_FAILED]])` `a failed delete (%i) keeps the conversation and says why`.
   The buttons are enabled again afterwards.
9. `the input is disabled and nothing can double-submit while a delete runs`. With a pending
   promise, `mock-send` is disabled, the other row's button is disabled, and `deleteMessage` was
   called once.
10. `a delete that lands after the session changed leaves the new session alone`.
11. `after an SSE-shaped turn, the new message gets its id and can be deleted without a reload`.
    1. Click `mock-send`. That sends `'Make slide 3 shorter'`. `listMessages` is called with
       `('sess-1', 200)`.
    2. Fire `captured.onEvent({type:'assistant', content:'Editing slide 3.'})`, then
       `captured.onEvent({type:'complete'})`.
    3. `listMessages` resolves to the four rows plus `{id:5, role:'user', content:'Make slide 3 shorter'}`
       and `{id:6, role:'assistant', content:'Editing slide 3.'}`.
    4. There are 3 buttons. Deleting the new one calls `deleteMessage('sess-1', 5)` and removes
       both new messages.
12. `after a polling-shaped turn (assistant events carry message_id, the user row is not echoed), the new message gets its id`.
    Same as test 11, with `{type:'assistant', content:'Editing slide 3.', message_id: 6}`.
13. `a turn that ends in an error still gets its id`.
    - Fire `{type:'error', error:'x'}` with no `complete`; `listMessages` was called and the new
      message has a button.
    - Separately, `captured.onError(new Error('x'))` gives the same.
14. `a failed or malformed id read changes nothing`.
    - `listMessages` rejecting, resolving `{}`, and resolving rows without ids each leave 2
      buttons.
    - The streamed messages are unchanged and no error is shown.
15. `the id read never rewrites the conversation`. With `listMessages` returning the new row with
    different content (an image-injected prompt), the panel's text is unchanged and there is no
    new button.
16. `an id read that lands after a session switch is dropped`.
17. `an id read that lands after the next send started is dropped` (review F1). The scaffold's
    `mock-send` always sends `'Make slide 3 shorter'`, so this is the identical-prompt case.
    1. Send, fire `complete`, and hold `listMessages` pending.
    2. Send again (the same text).
    3. Resolve the first read with the four rows plus `{id:5, role:'user', content:'Make slide 3 shorter'}`.
       No button exists on either new message.
    4. Fire the second turn's `complete`. Its read resolves with rows 5 and
       `{id:8, role:'user', content:'Make slide 3 shorter'}`.
    5. Deleting the newest message calls `deleteMessage('sess-1', 8)`. The older new message's
       button deletes 5.

**Steps:**
- [ ] **Step 1 (test author).** Write the tests and confirm they are red because there is no
  button. Leave them uncommitted.
- [ ] **Step 2 (implementer).** Make them green. Do not edit the tests.
- [ ] **Step 3.** Run `cd frontend && npm run test:unit && npx tsc -b && npm run build`.
  - **Vitest gate:** `ChatPanel.clearChat.test.tsx`, `ChatPanel.tourRefresh.test.tsx`,
    `slideReadyEvent.test.ts` and `AppLayoutSpecToggle.test.ts` stay green, and the cause set
    equals the baseline.
  - **Lint gate:** run it on `ChatPanel.tsx`, `MessageList.tsx` and the new test file.
- [ ] **Step 4.** Sabotage, one at a time. Each must turn a named test red:
  - drop `canEditConversation` from `canDeleteMessages` (test 2);
  - drop `isLoading` from `deleteMessageDisabled` (test 3);
  - call `api.getSlides` after a delete (test 6);
  - remove the stale-session guard (test 10);
  - remove `refreshMessageIds` from the `'complete'` case (tests 11 and 12) or from `onError`
    (test 13);
  - replace `withPersistedUserIds(prev, …)` with a mapping of `result.messages` (tests 14 and 15);
  - remove the `sendSeqRef.current !== seq` check (test 17);
  - drop `MESSAGE_ID_READ_LIMIT` from the call (test 11's `('sess-1', 200)`).
- [ ] **Step 5.** Commit. Stage exactly
  `git add frontend/src/components/ChatPanel/MessageList.tsx frontend/src/components/ChatPanel/ChatPanel.tsx frontend/src/components/ChatPanel/ChatPanel.deleteMessage.test.tsx`,
  then commit `feat(chat): delete a message and its replies from the chat panel (#317)`.

---

### Task 7b: Clear chat on every deck you can edit (supervisor ruling on review F5)

**Models:** `test=opus impl=haiku`. The plan gives every line of production code. The test author
carries the judgement of turning #323's gate rows into variant assertions without weakening the
others.

**Runs after Task 7**, because both edit `ChatPanel.tsx`.

**Files:**
- `frontend/src/components/ChatPanel/clearChatCopy.ts` (additive)
- `frontend/src/components/ChatPanel/ChatPanel.tsx`
- `frontend/src/components/ChatPanel/ChatPanel.clearChat.test.tsx`

**Why no backend work.** The clear route and service have no Spec dependency (Context 24).

**Why this wording, not "carries on from the current slides".** On a graph deck with no persisted
Spec, the architect never sees slide HTML, and it degrades any edit to a discussion
(`edit_without_spec`, `src/services/graph/nodes.py:1628-1638`). "Carries on from the current
slides" would promise an edit that cannot happen. The wording below is true for graph and legacy
decks alike.

**`clearChatCopy.ts`.** Add these after `CLEAR_CHAT_TOOLTIP`. Every existing export keeps its
value.

```ts
/**
 * On a deck without a Spec (#317 lifted #323's Spec gate). It promises no Spec and no "carries on":
 * the graph architect never sees slide HTML and refuses an edit with no persisted Spec
 * (edit_without_spec), and the legacy assistant has only the slides once its history is gone.
 */
export const CLEAR_CHAT_DIALOG_MESSAGE_NO_SPEC =
  'This deletes your conversation on this deck. Your slides and save points stay as they are, but '
  + "the assistant won't remember anything you discussed, so say what you want in full. This can't "
  + 'be undone.';
export const CLEAR_CHAT_TOOLTIP_NO_SPEC = 'Delete this conversation and keep the deck and its save points';
```

Update the file's header comment to say that the dialog message and tooltip have a Spec-less
variant, chosen by `hasDeckSpec`.

**`ChatPanel.tsx`:**
- Import the two new constants.
- The `hasDeckSpec` prop comment (`:48`) becomes:
  `/** Whether the live deck has a Spec. Chooses Clear chat's wording: with a Spec the assistant carries on from it; without one the wording promises nothing about a Spec (#317 lifted #323's Spec gate). */`
- `showClearChat` (`:411`) becomes `isSessionPersisted && canEditConversation(myPermission)`.
  Update its comment: "for editors, on a persisted session, with or without a Spec".
- The Clear chat `Button`'s `title` becomes
  `title={hasDeckSpec ? CLEAR_CHAT_TOOLTIP : CLEAR_CHAT_TOOLTIP_NO_SPEC}`.
- The Clear chat `ConfirmDialog`'s `message` becomes
  `message={hasDeckSpec ? CLEAR_CHAT_DIALOG_MESSAGE : CLEAR_CHAT_DIALOG_MESSAGE_NO_SPEC}`.
- Nothing else changes. `clearChatDisabled`, the handler and `AppLayout`'s
  `hasDeckSpec={!!slideDeck?.deck_spec}` stay as they are.

**Tests** (`ChatPanel.clearChat.test.tsx`, #323's file):
- **The gate table.** In `does not offer Clear chat $label` (`:189-202`), remove the two rows
  `without a Spec (hasDeckSpec false)` and `without a Spec (hasDeckSpec omitted)`. The viewer,
  no-permission and not-persisted rows stay exactly as they are.
- **New** `it.each([{label: 'hasDeckSpec false', hasDeckSpec: false}, {label: 'hasDeckSpec omitted', hasDeckSpec: undefined}])`
  `offers Clear chat on a deck without a Spec ($label), with the wording for one`:
  - the button is enabled, with `title` `CLEAR_CHAT_TOOLTIP_NO_SPEC`;
  - clicking it opens `confirm-dialog`, which shows `CLEAR_CHAT_DIALOG_MESSAGE_NO_SPEC` and does
    **not** show `CLEAR_CHAT_DIALOG_MESSAGE`;
  - confirming calls `clearChat('sess-1')` once and empties the list.
- **New** `uses the agreed wording for a deck without a Spec`. It checks the two new constants'
  exact text, and that `CLEAR_CHAT_DIALOG_MESSAGE_NO_SPEC` does not contain `"Spec"`.
- **New** `a deck with a Spec still gets the Spec wording`. It opens the dialog with
  `hasDeckSpec: true`: the dialog shows `CLEAR_CHAT_DIALOG_MESSAGE` and the title is
  `CLEAR_CHAT_TOOLTIP`. This pins that the variant did not replace the original.
- Every other #323 case stays unchanged and green, including `uses the agreed copy`, the three
  became-persisted cases and the switch cases. Their "before persisted: no button" assertions
  still hold, because the button still needs a persisted session.

**Steps:**
- [ ] **Step 1 (test author).** Edit the table and write the new cases, then confirm they are red:
  the button is hidden without a Spec, and the constants are missing. Leave them uncommitted.
- [ ] **Step 2 (implementer).** Make them green. Do not edit the tests.
- [ ] **Step 3.** Run `cd frontend && npx vitest run src/components/ChatPanel && npx tsc -b`. Then
  run `npm run test:unit` and apply the vitest gate. Apply the lint gate to the three files.
- [ ] **Step 4.** Sabotage, one at a time. Each must turn a named test red:
  - put `hasDeckSpec &&` back in `showClearChat` (the Spec-less `it.each`);
  - swap the ternary branches (the Spec-less test and `a deck with a Spec still gets the Spec wording`);
  - change `CLEAR_CHAT_DIALOG_MESSAGE`'s value (`uses the agreed copy`).
- [ ] **Step 5.** Commit. Stage exactly
  `git add frontend/src/components/ChatPanel/clearChatCopy.ts frontend/src/components/ChatPanel/ChatPanel.tsx frontend/src/components/ChatPanel/ChatPanel.clearChat.test.tsx`,
  then commit `feat(chat): offer Clear chat on every deck, with wording for a deck without a Spec (#317)`.

---

### Task 8: E2E with a mocked backend (`delete-message.spec.ts`)

**Models:** `test=opus impl=sonnet`. A red result usually means a mount or timing bug in Task 7,
and fixing it needs judgement. Never loosen the spec to get a pass. A stop escalates straight to
opus.

**Files:** **new** `frontend/tests/e2e/delete-message.spec.ts`, `frontend/tests/e2e/clear-chat.spec.ts`
(one option and one test, for Task 7b), and `.github/workflows/test.yml` (the matrix)

**Harness.** Follow the structure of `clear-chat.spec.ts`:
- use `test` and `expect` from `../fixtures/base-test`;
- use `setupMocks`, `mockSessionWithSlides`, `mockSessionDetail`, `mockSlidesResponse` and
  `TEST_SESSION_ID`, plus `apiPath` and `apiPathMatching`;
- import the copy constants from `../../src/components/ChatPanel/deleteMessageCopy`;
- register every route **after** `setupMocks` and `mockSessionWithSlides`.

Use a `mockDeletableDeck(page, { myPermission })` helper that returns a recorder with:
- `state.transcript`, a mutable array, initially
  `[{id:1,user,'Build a deck about cloud adoption'}, {id:2,assistant,'Building 3 slide(s).'}, {id:3,user,'Make the title punchier'}, {id:4,assistant,'Edited slide 1.'}]`;
- `state.deleteStatus`, default 200;
- `deletes: string[]`;
- `counts { slidesGets, sessionGets, messagesGets }`.

The helper mocks these routes:
- **Session detail (GET).** It returns
  `{...mockSessionDetail, my_permission, graph_version: 1, active_graph_version: 1, is_older_than_active: false, messages: state.transcript}`.
- **Delete.** It matches `apiPathMatching(new RegExp('^/api/sessions/' + TEST_SESSION_ID + '/messages/(\\d+)$'))`
  for DELETE, and records the pathname.
  - With `deleteStatus` 200, it removes that turn from `state.transcript` by the same rule (the
    user row up to the next user row) and answers
    `{status:'deleted', session_id, message_id, deleted_messages, hidden_message_id: null}`.
  - Otherwise it answers that status with `{detail: 'busy'}`.
- **Messages (GET).** It matches `apiPath('/api/sessions/' + TEST_SESSION_ID + '/messages')` and
  answers `{session_id, messages: state.transcript, count}`.
- **Slides (GET)**, counted. It serves `DECK_SPEC` (copy the 3-slide spec shape from
  `clear-chat.spec.ts:55-101`).
- **Contributors** answers `{contributors: []}`.
- **Save points** answers one version, as clear-chat does.

The SSE body format is `clear-chat.spec.ts`'s `sse(...)`.

**Tests:**
1. `an owner deletes a message and its reply; the slides, the Spec and the other messages stay; a reload agrees`.
   Use `CAN_MANAGE`.
   - Record the slides-GET count and `spec-audience` (via `view-toggle-spec`).
   - Hover the `chat-message-row` that has the text "Make the title punchier", then click its
     `delete-message-button`.
   - The `confirm-dialog` shows `DELETE_MESSAGE_DIALOG_MESSAGE`. Confirm, scoped to the dialog.
   - Then:
     - "Make the title punchier" and "Edited slide 1." are gone, and the other two are visible;
     - `deletes` is `['/api/sessions/<id>/messages/3']`;
     - the slides-GET count is unchanged, `ribbon-thumb-0..2` are present, and `spec-audience` is
       unchanged.
   - `page.reload()`: the same two messages, and nothing of the deleted turn.
2. `a message sent in this tab can be deleted once its turn completes, without a reload`.
   1. Route `apiPath('/api/chat/stream')` to `sse({type:'assistant', content:'Editing slide 3.'}, {type:'complete', slides: {...}})`.
      Before the response, push `{id:5,user,'Make slide 3 shorter'}` and
      `{id:6,assistant,'Editing slide 3.'}` into `state.transcript`.
   2. Send `Make slide 3 shorter`.
   3. After `Editing slide 3.` is visible, the new row's `delete-message-button` appears, and
      `counts.messagesGets` is at least 1.
   4. Delete it. `deletes` ends with `/messages/5`, and neither new message is in the panel.
3. `a viewer is not offered delete`. Use `CAN_VIEW`: `delete-message-button` has count 0.
4. `delete is disabled while a reply is being generated`. Hold the stream on a promise. The
   buttons are disabled. Release it, and once the assistant message shows they are enabled.
5. `cancelling the dialog deletes nothing`.
6. `a busy deck keeps the message and says why`. With `deleteStatus = 409`, confirm:
   `DELETE_MESSAGE_BUSY` is visible and the turn is still shown.

**`clear-chat.spec.ts` (Task 7b's e2e assertion).**
- Give `mockClearableDeck` an option `deckSpec` that defaults to `DECK_SPEC`, and serve it as the
  slides route's `deck_spec` instead of the literal (`clear-chat.spec.ts:208-223`). The six
  existing tests pass nothing, so they are unchanged.
- Add test 7, `on a deck without a Spec, Clear chat is offered with the wording for one`:
  1. `mockClearableDeck(page, { myPermission: 'CAN_MANAGE', deckSpec: null })` and `openDeck`.
  2. `clear-chat-button` is visible and enabled.
  3. The dialog contains `CLEAR_CHAT_DIALOG_MESSAGE_NO_SPEC`, imported from `clearChatCopy`, and
     not `CLEAR_CHAT_DIALOG_MESSAGE`.
  4. Confirm, scoped to the dialog. `chat-welcome` is visible, and `clears` holds exactly this
     session's `/context`.

**CI wiring:** add `- delete-message` to the e2e matrix after `- deck-prompts-ui` (`test.yml:706`,
alphabetical). Without it, `tests/unit/test_e2e_matrix_covers_specs.py` fails.

**Steps:**
- [ ] **Step 1.** Write the spec and the matrix entry.
- [ ] **Step 2.** Run it locally only if `~/tellr-loop/bin/e2e-lock acquire issue-317` succeeds
  **and** ports 3000 and 8000 are free:
  `cd frontend && npx playwright test tests/e2e/delete-message.spec.ts --project=chromium --workers=1`.
  Also re-run `tests/e2e/clear-chat.spec.ts` and `tests/e2e/chat-ui.spec.ts`, because the id read
  now runs after every turn. Release the lock afterwards. Otherwise CI runs it. Fix real causes
  in Task 7's code.
- [ ] **Step 3.** Run `uv run pytest tests/unit/test_e2e_matrix_covers_specs.py -q`.
- [ ] **Step 4.** Sabotage, where the local run is possible:
  - refetch `getSlides` after a delete (test 1);
  - remove `refreshMessageIds` from `'complete'` (test 2);
  - drop `isLoading` from `deleteMessageDisabled` (test 4);
  - put `hasDeckSpec &&` back in `showClearChat` (clear-chat test 7).
- [ ] **Step 5.** Commit. Stage exactly
  `git add frontend/tests/e2e/delete-message.spec.ts frontend/tests/e2e/clear-chat.spec.ts .github/workflows/test.yml`,
  then commit `test(e2e): delete a message, including one sent in this tab; clear a deck without a Spec (#317)`.

---

### Task 9: Docs and the in-app Help page

**Models:** `test=sonnet impl=sonnet`. The "test" is a claims check: the reviewer verifies every
sentence against the code from Tasks 1–7b.

**Files and content:**
- **`docs/user-guide/01-generating-slides.md`.**
  - Add `## Deleting a Message` after "Clearing the Chat" (`:66-91`), before "Navigating
    Slides". It covers:
    - hovering your message and clicking the trash icon, then confirming;
    - that your message **and the assistant's replies to it** are deleted;
    - that the assistant no longer sees them;
    - that **the slides and the Spec are not rolled back**: what the deleted exchange changed
      stays, so ask for the change back if you want it ("make slide 3 longer again");
    - that the deck's title is kept, even when you delete your first message;
    - that it cannot be undone;
    - that it is offered only on your own messages, when you can edit; it is greyed out while a
      reply is generated, while the chat is read-only, and during a save-point preview;
    - the "still running" message;
    - that save-point previews keep the message;
    - that a message you just sent can be deleted as soon as its reply finishes.
  - In "Clearing the Chat", add one line: "Clear chat resets the whole conversation; to remove
    one exchange, see [Deleting a Message](#deleting-a-message)."
  - **Clear chat on any deck (F5).** In "Clearing the Chat" (`:66-91`):
    - "What is kept" says the Spec is kept *if the deck has one*;
    - "The assistant carries on from the Spec and the current slides" gains: "On a deck without
      a Spec, your slides stay, but the assistant has no Spec and no conversation to go on, so
      say what you want in full.";
    - "When the button is available" becomes "on any saved deck you can edit", with the rest of
      that list unchanged;
    - remove the bullet "If the **Clear chat** button is missing right after you restore a save
      point, reload…", because the button no longer hides.
- **`docs/user-guide/08-profile-sharing-permissions.md`.**
  - CAN EDIT (`:74`): "Delete messages in your own chat (never in the owner's or anyone else's)".
  - CAN VIEW cannot (`:63`): "Delete chat messages".
- **`docs/technical/permissions-model.md`.**
  - Add a "Delete a message" row to the Conversation Privacy table (`:74`).
  - Add one paragraph after the Clear chat gates (`:78-83`): `DELETE …/messages/{message_id}`
    applies the same two gates in the same order, then the lock, writes `message_deleted`, and
    answers 404 for any id that is not a visible user message of that session.
  - Add the route to the route list (`:462`).
- **`docs/technical/backend-overview.md`.**
  - Add a Session Messages Endpoints row beside `:71` for
    `DELETE /api/sessions/{id}/messages/{message_id}`. It is the turn unit; the first user
    message is hidden, not deleted; the thread is deleted; it is one transaction; it writes
    `message_deleted`; nothing is undone in the deck. Do not write "rollback", which is a
    CONTEXT.md term for Graph Releases (F10). Handler: `routes/sessions.delete_session_message`.
  - Add one sentence on late rows (F6): a row written after the next user message (stale lock,
    SSE disconnect, a sweeper notice) is grouped with the turn it lands after.
  - Add one sentence on ids (F12): locally on SQLite a deleted row's id can be reused by the next
    row, so a stale tab could address a newer turn; Postgres never reuses ids.
  - Add one sentence to the Contributor Sessions section (`:506`).
- **`docs/technical/usage-analytics.md`.**
  - Add `message_deleted` to the model comment (`:59`), the constants list (`:68-69`), the event
    table (after `:85`) and the "Write-path guarantees" section (`:325`).
  - It is written in the delete's own transaction, one per delete, with no dedup. It counts as
    activity, and the heatmap counts each delete as one event.
- **`docs/technical/save-points-versioning.md`.** Add `### Deleting a message` after "Clearing the
  chat" (`:274-285`): D10's three bullets.
- **`docs/technical/multi-user-concurrency.md`.**
  - Extend the session-lock exception (`:199`) to `DELETE /api/sessions/{id}/messages/{message_id}`.
  - **Correct `:204`.** Replace "the graph thread holds only per-turn state" with the accurate
    statement:
    - the thread keeps every checkpoint of every turn, including each turn's message and reply;
    - nothing replays it to an agent;
    - a clear or a delete deletes the whole thread;
    - the cost is that the first `ask_data` turn after either sends the analyst
      `deck_purpose: None` (D5, a recorded follow-up).
  - Fix the sweeper sentence on that line. It says the sweeper "writes no chat rows", but its
    ungated `_surface_notice` can write an `info` row (F6).
- **`docs/technical/frontend-overview.md`.**
  - In the ChatPanel row (`:322`), add per-message delete, `conversationApi.deleteMessage` and
    `listMessages`.
  - Add the two rows to the Conversation API table (`:532-534`).
  - Add a "**Delete a message** is wired in `ChatPanel` and `MessageList`" bullet list after
    `:536-540`: visibility, disabled states, local turn removal, error mapping, and the id read
    at turn end (D12). Cover the pairing rule, `limit=200`, and the dropped read after a newer
    send (`sendSeqRef`).
  - **Clear chat visibility (F5).** In the Clear chat bullets (`:536-540`), the button now shows
    on every persisted session the user can edit, and `hasDeckSpec` chooses the wording
    (`CLEAR_CHAT_DIALOG_MESSAGE` or `CLEAR_CHAT_DIALOG_MESSAGE_NO_SPEC`, and the matching
    tooltip). Remove the sentence saying the button can stay hidden after a same-tab restore.
- **`docs/technical/real-time-streaming.md`.** Near the `session_messages` table (`:507`), add a
  short "Message ids in the chat panel" note:
  - SSE graph events carry no `message_id`;
  - poll events do, but the user's own row is not echoed;
  - the panel reads `GET /api/sessions/{id}/messages?limit=200` when a turn ends (`complete`,
    `error` or `onError`) and adds ids to its user messages by content;
  - a read that resolves after the user sent again is dropped, and the next turn's read pairs
    both (F1);
  - `complete.metadata` reaches the panel on both transports, but an error-ended turn sends no
    `complete`. That is why the read is the mechanism, and `metadata.user_message_id` is the
    upgrade path (F3);
  - a delete removes a turn's rows by role and order, so a late row joins the turn it lands after
    (F6).
- **`docs/technical/mcp-server.md`.** In §5.2, beside `:266`:
  - add one sentence: after a message delete, a poll for that turn's request returns no messages;
  - replace the parenthetical "(The web UI offers Clear chat only on decks that have a Spec, so
    decks created through `create_deck` do not normally reach this state.)" with "The web UI
    offers Clear chat on every deck the user can edit, including decks created through
    `create_deck`." (F5).
- **`docs/technical/save-points-versioning.md` "Known gap" (`:282`, F5).** Replace it. The Clear
  chat button now shows after a same-tab restore, but until a reload its dialog uses the Spec-less
  wording, because the restored deck object carries no `deck_spec`. That wording is still true.
- **`frontend/src/components/Help/HelpPage.tsx`.**
  - Add one `<li>` after the Clear chat line (`:163`): "**Delete a message** (hover one of your
    messages, click the trash icon) removes it and the assistant's replies; the slides and the
    Spec stay as they are".
  - In the Clear chat line, change "keeps the deck, its Spec and save points" to "keeps the deck,
    its save points and its Spec, if it has one" (F5).

**Steps:**
- [ ] **Step 1.** Write the docs.
- [ ] **Step 2.** The reviewer checks every claim against the code, especially:
  - the turn unit;
  - "not rolled back";
  - the hidden first message;
  - the 404 cases;
  - the corrected checkpoint sentence and the `deck_purpose` cost;
  - that Clear chat is offered on every deck, and its Spec-less wording.
- [ ] **Step 3.** Run `cd frontend && npm run build`, and apply the lint gate to `HelpPage.tsx`.
  Run `npx playwright test tests/e2e/help-ui.spec.ts` only under the e2e-lock with ports 3000
  and 8000 free.
- [ ] **Step 4.** Commit. Stage exactly the files listed above:
  `git add docs/user-guide/01-generating-slides.md docs/user-guide/08-profile-sharing-permissions.md docs/technical/permissions-model.md docs/technical/backend-overview.md docs/technical/usage-analytics.md docs/technical/save-points-versioning.md docs/technical/multi-user-concurrency.md docs/technical/frontend-overview.md docs/technical/real-time-streaming.md docs/technical/mcp-server.md frontend/src/components/Help/HelpPage.tsx`,
  then commit `docs: delete a message, clear any deck, and what the graph thread really holds (#317)`.

---

### Task 10: Verification and whole-branch review

**Models:** `test=opus impl=opus` (controller). The whole-branch review is always opus (skill §7).

- [ ] **Backend.** Run `uv run pytest tests/unit -q -n 4`, and:
  ```
  DATABRICKS_HOST= DATABRICKS_TOKEN= uv run pytest tests/integration/test_delete_message_graph_turn.py tests/integration/test_delete_message_routes.py tests/integration/test_clear_context_graph_turn.py tests/integration/test_clear_chat_routes.py tests/integration/test_savepoint_e2e.py tests/integration/test_graph_orchestration.py tests/integration/test_graph_mode_turn.py tests/integration/test_architect_reply_is_persisted.py tests/integration/test_spec_row_alignment.py tests/integration/test_sweeper_describe_only.py -q
  ```
  The failure-cause set must equal the baseline.
- [ ] **Frontend.** Run `cd frontend && npm run test:unit && npx tsc -b && npm run build`, with the
  vitest and lint gates.
- [ ] **CI guards.** Run
  `uv run pytest tests/unit/test_ci_collects_integration_tests.py tests/unit/test_e2e_matrix_covers_specs.py tests/unit/test_ci_exports_postgres_test_url.py tests/unit/test_route_authz_coverage.py -q`.
- [ ] **Sabotage.** Re-run every sabotage in Tasks 1–8, including 7b, with the controller's and
  the reviewer's targets kept apart.
- [ ] **Whole-branch review** on opus, with the `tellr-code-review` checklist (multi-worker
  in-process state). Ask for:
  - one row per reader in "Every reader after a delete", saying deleted, hidden or deliberately
    unchanged;
  - a ruling on the transaction boundary and the session filter;
  - a scan for any payload, prompt, schema or digest diff, and for any edit to `nodes.py`,
    `Message.tsx`, `api.ts` or `chat.py`;
  - a merge or no-merge verdict.
- [ ] **Hand-off notes for the user:**
  - **The checkpoint finding** (Findings 1), and the `restore_version` follow-up (Findings 2).
  - **No test runs a real model after a delete.** The graph tests prove what agents are given.
  - **Ran only in CI:** `delete-message.spec.ts`, if the lock or ports were taken.
  - **`deck_purpose: None` after every delete** (D5, #323's F14). The first `ask_data` turn after
    any delete or clear sends the analyst no `deck_purpose`, because the thread that held
    `deck_spec` is gone. Deletes make this far more frequent than clears did. The follow-up is to
    fall back to `read_deck_spec` in `data_analyst_node`, which touches `nodes.py` (owned by #321).
  - **#323's Spec gate on Clear chat is lifted** (D1, Task 7b, the supervisor's F5 ruling). Spec-less
    decks get their own wording.
  - **The upgrade path for message ids** if content pairing proves too weak:
    `complete.metadata.user_message_id` (D12, F3).
  - The expected merge conflicts with #319 and #321 (below).

---

## Findings about the base (not fixed here unless a task says so)

1. **#323's "the graph thread holds only per-turn state" is wrong.** It appears in the NOTES'
   extension points, plan Context 7 and D6, and `docs/technical/multi-user-concurrency.md:204`.
   - `SqlAlchemyCheckpointSaver` keeps every checkpoint of every turn, with no pruning (probe P1:
     14 checkpoints and 86 writes after two turns).
   - Each turn's checkpoints store the user's message (`__start__` and `architect_message`) and
     the architect's reply (`architect_message`).
   - #323's **conclusions still hold**: nothing replays the thread to any agent (probe P1), and
     clear deletes the thread anyway.
   - The *claim* is false, and it is what made "no graph-thread change is needed" for #317
     sound wrong. Task 9 corrects the doc. Task 1 corrects the same false idea in
     `resolve_engine_mode`'s docstring (`chat_service.py:168-172`: "the architect's own
     conversation lives in the checkpointer").
2. **`restore_version` prunes chat rows but not the graph thread.** It deletes this session's
   rows created after the save point (`session_manager.py:2796-2806`) and never calls
   `delete_thread`, so the thread keeps the pruned turns' text. Nothing replays it. **Follow-up:**
   the same `delete_thread(session_id, session=db)` in restore's transaction. That is out of
   scope here, because restore has its own tests and semantics.
3. **The checkpoint grows without bound.** It adds about 7 checkpoints and 40 writes per turn,
   and only a clear or a delete removes them. This is out of scope and worth a ticket.
4. **Two orderings.** `UserSession.messages` (and so `get_messages` and the panel) orders by
   `created_at` only (`session.py:206`). Engine mode, clear and delete order by `(created_at, id)`.
   On an exact `created_at` tie the panel order and the turn grouping can differ. It is rare
   (microsecond timestamps). This is out of scope.
5. **The lock is released after the client sees `complete`.** Polling marks `completed`
   (`job_queue.py:197`) before it releases (`:213`). On SSE the title thread joins for up to 10 s
   after `complete` (`chat_service.py:2140`). A clear or a delete clicked at once can answer 409.
   This is pre-existing, and the copy covers it.
6. **The panel treats a mid-turn per-slide ERROR as the end of the turn.** That is the `error`
   case at `ChatPanel.tsx:316-321` against `nodes.py:1263-1267`, and the Clear and Delete actions
   then enable mid-turn. This is pre-existing, and the backend's 409 protects it.
7. **`POST /api/sessions/{id}/messages`** lets the creator add a row with any `role` and a `None`
   type (`sessions.py:810-856`). A `role='user'` row written there is a turn head, and it can
   become the engine-mode row. This is pre-existing. The delete treats it like any user row.

## Expected merge conflicts

- **#319 (`feat/319-chat-stage-placeholder`):**
  - `ChatPanel.tsx`: the `<MessageList>` element (#319 adds `progressLabel` and goes multi-line,
    this plan adds `deleteAction`; keep both props) and the `ChatInput` `disabled` expression
    (one line each). Task 7b's lines (`showClearChat`, the button `title`, the dialog `message`)
    are in the header and dialog, which #319 does not touch;
  - `MessageList.tsx`: the props interface and the destructure (keep both props);
  - `test.yml`: adjacent list lines;
  - docs: `real-time-streaming.md`, `frontend-overview.md`, `multi-user-concurrency.md` and the
    user guide 01.
- **#321 (`feat/321-plain-language-failure-notice`):**
  - `types/message.ts` and the `ChatPanel.tsx` load map: placed apart on purpose (`id` first,
    `details` after `tool_call`), so they are expected to merge cleanly;
  - docs: `frontend-overview.md`, `real-time-streaming.md` and the user guide 01.
  - #321's notice rows stay `role='assistant'`, `info`, so the turn unit (D2) covers them with
    no change. Its `metadata.details` goes with the row.
- **#318, #316, #313:** no overlap is expected.

## Out of scope

- **Undo or restore of a deleted message** (D18), and a "message deleted" marker in the chat.
- **Deleting a single assistant reply, or a reply before any user message,** on its own. The
  only turn-free way to remove such rows is Clear chat, which is now offered on every deck (D1).
- **Rolling the deck back to before the deleted turn.** Use a save point.
- **An MCP tool for deleting a message.**
- **Resetting the Genie conversation** (`genie_conversation_id`) on a delete or a clear (D11).
- **The fix for `deck_purpose: None` after a thread delete** (#323's F14; D5). It is documented
  (Task 9) and handed off (Task 10). The fix touches `nodes.py` (#321).
- **Server-sent message ids** (`complete.metadata.user_message_id`). This is the recorded upgrade
  path (D12, F3).
- **The `restore_version` thread prune** (Findings 2) **and checkpoint pruning** (Findings 3).
- **A real-backend Playwright spec** (D17), and a Postgres-only delete test (D6).
- **Stable React keys in `MessageList`.** It keeps `key={index}`. After a delete, a collapsed or
  expanded tool message state can shift to the next message until a reload. That is cosmetic.

## Local vs CI verification limits

- **Backend.** Every new Python test runs locally on SQLite: the unit tests, the graph tests
  (file-backed SQLite with the real saver, which is the strict case for one transaction) and the
  TestClient route test. There is no new Postgres-only test. #323's
  `TestTheClearAgainstRealPostgres` covers the shared `delete_thread(session=db)` mechanism in
  CI's unit job.
- **Frontend unit, `tsc -b`, build and lint** run locally.
- **Playwright.** Ports 3000 and 8000 are fixed and shared by other agents, and
  `reuseExistingServer: true` would quietly test another worktree's server. Run
  `delete-message.spec.ts`, plus `clear-chat` and `chat-ui` as regression checks for the id read,
  only under `~/tellr-loop/bin/e2e-lock` with both ports free. Otherwise the first run is CI.
