# #317 Delete a chat message, reset the chat: notes for the reviewer

**Branch:** `feat/317-delete-message-reset-chat`, stacked on `feat/323-clear-chat-keep-deck` (PR #331).
This PR's own changes are the diff against that branch:
https://github.com/robertwhiffin/ai-slide-generator/compare/feat/323-clear-chat-keep-deck...feat/317-delete-message-reset-chat
**Plan:** `2026-10-19-issue-317-delete-message-reset-chat.md` (revision 2, after an independent plan review).
**Built by:** a supervisor agent, with sub-agents for planning, plan review, a plan-vs-code pre-pass, tests,
implementation, per-task review and a final whole-branch review. Nobody asked the user any questions.
The decisions below were made on the user's behalf.

## What shipped, by acceptance criterion

**A1: a user can delete an individual message and reset the whole chat for a session.**
- **Delete a message.** Each of the user's own persisted messages gets a trash icon in the chat panel
  (on hover or keyboard focus). A confirm dialog says the slides and Spec are not rolled back. Confirming calls
  `DELETE /api/sessions/{session_id}/messages/{message_id}` and removes the exchange from the panel. The deck is
  never refetched.
- **What a "message" is: the turn.** A delete removes the user's message and every row after it up to the next
  user message: replies, clarifications, `info` notices, reasoning, tool calls and tool results
  (`src/domain/conversation_turns.py`). Grouping is by role and order, never by `request_id` (empty on SSE) or
  `message_type`, so #321's failure notices join their turn with no change.
- **Reset the chat.** This is #323's Clear chat, reused (Decision 1). It was offered only on decks with a Spec;
  it is now offered on every persisted deck the user can edit, with wording for a deck without a Spec
  (Decision 2).
- **Message ids in the panel.** The panel had no ids. It now takes them from the load, and after every turn
  (on `complete`, an `error` event or a transport failure, on both transports) it reads
  `GET …/messages?limit=200` and gives its id-less user messages the ids of the stored rows with the same
  content (`withPersistedUserIds`). A read that lands after a newer send is dropped, and content that is
  ambiguous (more unsent copies than stored rows) is never paired: those messages offer delete after the next
  load.

**A2: the architect's conversation context (`_conversation`) and the graph checkpoint reflect the deletion/reset.**
- **The conversation.** The architect's `conversation` is rebuilt from the rows on every turn
  (`nodes._conversation`), so deleting the rows removes the turn from it. Deleting a whole turn means no orphan
  reply or unanswered question is left behind.
- **The checkpoint.** Planning found #323's note "the graph thread holds only per-turn state" false. The
  checkpoint saver keeps every checkpoint of every turn and never prunes; each turn stores the user's text
  (`__start__`, `architect_message`) and the architect's reply, and the text survives later turns. So every
  delete also deletes the session's graph thread, in the same transaction (Decision 5). The next turn starts a
  new thread and builds its payload from the database.
- **Proof** (`tests/integration/test_delete_message_graph_turn.py`, real compiled graph, real checkpoint saver,
  stubbed model):
  - three turns, delete the middle one, run a fourth: the fourth turn's conversation is exactly turns 1, 3 and 4;
    no payload of any agent (architect, builder, build reviewer, deck reviewer) contains the deleted text; no
    checkpoint or pending write contains it (and the test first proves it was there);
  - a reset (#323's clear) leaves nothing from before in any payload or checkpoint;
  - a polling turn and an SSE turn are each one deletable turn.
  The model is stubbed: this proves what the agents are given, not what a model would do.

**A3: only users with edit rights can do it on a shared deck; the action is attributable.**
- **Route order** (`delete_session_message`, `src/api/routes/sessions.py`), exactly as #323's clear:
  1. CAN_EDIT on the deck (a viewer gets 403);
  2. `_require_conversation_creator`: no user is 401, anyone but the session's own creator is 403, so a
     contributor deletes only in their own contributor session;
  3. the session lock: while a turn runs, 409 with `CONVERSATION_BUSY_DETAIL`, without releasing someone else's lock;
  4. the delete; 5. a guarded release in `finally`.
  Every not-found case (absent id, another session's id, an assistant row, the hidden first row) answers one
  404 text, so the 404 says nothing about other sessions. A non-integer id is 422.
- **Attribution.** Each delete writes one `usage_events` row `message_deleted` (username = the caller, the
  session's internal id) in the delete's own transaction, so it exists if and only if the delete committed.
  The log lines carry `deleted_by`. Admin analytics count it as activity, as they count `context_cleared`.
- **The UI.** The trash icon shows only for `CAN_EDIT`/`CAN_MANAGE` on a persisted session, never in a
  save-point preview, and is disabled while a turn, a clear or another delete runs, or when the panel is
  read-only.

## Decisions made on your behalf

1. **"Reset the whole chat" is #323's Clear chat, not a second reset.** It already deletes the transcript,
   hides the engine-mode row, deletes the graph thread and records `context_cleared`, in one transaction. A
   permanent graph test now proves the fresh start.
2. **Clear chat is offered on every deck you can edit, not only decks with a Spec.** The acceptance says
   "reset the whole chat for a session", and #323's gate left legacy decks and decks whose first build failed
   with no reset at all. On a deck without a Spec the tooltip and dialog promise nothing about a Spec ("…the
   assistant won't remember anything you discussed, so say what you want in full."), because on a graph deck
   with no Spec the architect refuses edits. This is a deliberate change to #323's frontend gate; two of #323's
   vitest rows that asserted the button is hidden without a Spec were replaced by tests of the new wording.
3. **The unit of deletion is the turn** (user message plus everything after it up to the next user message),
   addressed by the user message's id. Deleting a prompt but keeping its reply would leave an orphan reply in
   the architect's context. The UI offers delete only on user messages.
4. **The session's earliest user message is never deleted.** It carries the engine mode (#323's rule). Deleting
   the first exchange re-types that row to the hidden `engine_mode_marker` and deletes the rest of its turn.
   The UI offers delete on it like any other message. `message_count` keeps counting it, so the title is not
   regenerated.
5. **Every delete deletes the session's graph thread** in the same transaction. Rewriting checkpoint state was
   rejected: the saver implements no prune, and rewriting history is fragile. The cost is the one a clear
   already pays: the thread's `deck_spec` is lost, so `ask_data` turns send the data analyst `deck_purpose: None`
   until a build or edit turn writes the Spec into the new thread (the analyst has no tools today).
6. **The deck is not rolled back.** Slides, the Spec, save points, the engine and the Conversation Pin are
   untouched. The dialog says "Anything it changed in your slides or the Spec stays as it is; it is not rolled
   back." The user guide says the same.
7. **Save points keep what they captured.** A save point's preview still shows a turn deleted later; a save
   point taken after a delete excludes it; a restore never brings it back.
8. **Delete is offered on every persisted deck, legacy or graph, Spec or not.** The legacy agent replays only
   stored rows per request, so nothing else needs changing. A Genie space keeps its own conversation; a deleted
   turn's data questions stay there, as after a clear.
9. **Attribution through `usage_events`** (no migration; `SharedDeckMutationEvent` would need a CHECK-constraint
   migration and would report a private chat edit as a deck change).
10. **Ids by a turn-end read, not by stream events.** `complete.metadata` would reach the panel on both
    transports by editing only `chat_service.py`, but a turn that ends in an error sends no `complete`, and a
    failed turn is exactly what a user wants to delete. One read covers every way a turn ends. The exact upgrade
    path, if content matching ever proves too weak, is returning the user row's id from `POST /api/chat/async`
    and in `complete.metadata` (touches `chat.py`/`api.ts`, owned by sibling branches today).
11. **One helper for the earliest user row** (`earliest_user_message`, `session_manager.py`), replacing three
    copies (engine-mode resolution, clear, duplicate); the startup pin backfill keeps its set-based twin.
    #323's hand-off asked for this.
12. **No real-backend Playwright** (CI's real e2e backend hangs on SCIM, found by #323). The UI journey is a
    mocked spec; the backend is proved by TestClient route tests and graph tests.
13. **An imperative send during a running turn is left as it is** (whole-branch review W3). A finding's Apply or
    Discuss clicked while a reply runs gets a 409 and clears the panel's loading state early, which enables the
    trash icon and Clear chat mid-turn; the backend still answers 409, and the user guide says so. A guard would
    have silently dropped the click, a UX change to a path #316 also uses.

## Deviations from the plan

- **Task 7b was added in plan revision 2** (Decision 2) after the plan review asked for a ruling.
- **Per-task reviews strengthened tests** without changing the plan's production code, except:
  - **T7 (panel):** the delete button's CSS. `Button`'s base `disabled:opacity-50` beat `opacity-0`, so every
    disabled trash icon showed faded on every message during every turn. Fixed with `disabled:opacity-0` and a
    named `group/row` hover (a plain `group` also lit `Message.tsx`'s own hover chevrons).
  - **T1 (helper):** a test-only SQLite index makes the `(created_at, id)` tie-break observable locally, so the
    "order by `created_at` only" mutation is caught without Postgres.
- **Whole-branch review fixes:**
  - **W1 (blocker):** a refused duplicate send (for example a double-click on a finding's Apply: the second
    send gets 409 before anything is stored) could take the stored turn's id, so its trash icon would have
    deleted a turn the user did not pick. Ambiguous content is now never paired. Reproduced through the real
    ChatPanel, fixed, and pinned by three pure tests and one panel test; removing the check, or loosening it by
    one, turns all four red. The reviewer's own probe now shows no trash icon on either copy.
  - **W7:** the route's 500 log line now carries `message_id` and `deleted_by`.
  - **W2, W3, W4, W5:** documentation (the cross-tab residual, the mid-turn enable, two docs claims made false
    by W1, and the graph thread that restore and deck delete leave behind).
- **No separate per-task reviewer for Tasks 4, 5 and 8** (test-only tasks, no production change). Each test
  author ran its own production sabotages with real output, the supervisor ran a controller sabotage on a
  different path for 4 and 5, and the whole-branch review covered all three.

## Test evidence

- **Baselines are recorded as causes, not counts.**
  - Backend `tests/unit`: 9196 passed / 137 skipped / 0 failed at the base; 9286 passed / 137 skipped / 0 failed
    at the end (the 90 new backend tests are all SQLite-backed; the 137 skips are the pre-existing Postgres-only tests).
  - Frontend vitest locally: 20 tests in 3 SlideViewer files fail at the base and at the end, all from one cause
    (Node 26 leaves `localStorage` undefined; CI runs Node 20).
  - `eslint` is not clean on `main` and CI does not run it; no file this branch touched gained a finding.
- **Local runs.** The touched integration files (7) pass: 78 tests. The mocked e2e spec, `clear-chat` and
  `app-tour` passed 36/36 with `--repeat-each=2` (cached Chromium 1194 through a /tmp Playwright config, as on
  #323); `chat-ui` 56/56.
- **Sabotage.** Every approved test was broken against production code and the named test went red; the
  controller and the reviewers used different targets. Selected:
  - **The turn and the first row:** deleting the head instead of re-typing it (7 red); stopping the turn at the
    first non-reply row (5 red); dropping the session filter from the rows query (the other-session case red);
    reading rows in id order (red only after a reviewer-added test); the earliest row of any role (red only after
    a reviewer-added test).
  - **One transaction:** `delete_thread` without `session=` (`database is locked` on file SQLite); the usage
    event in its own session; a commit after the bulk delete; skipping `delete_thread`; the thread handed a fresh
    session. The whole-branch reviewer forced a failure at every SQL statement of the delete (10/10 left the
    database exactly as before).
  - **The route:** swapping the creator gate and the lock (9 red); releasing in the 409 branch; dropping CAN_EDIT;
    `message_id: str`; an unguarded release; dropping the deck gate (also turns `test_route_authz_coverage` red);
    a silenced release-failure log (red only after a reviewer-added test).
  - **The graph:** `delete_message` or `clear_context` skipping `delete_thread`; deleting only the user row;
    `get_messages` no longer hiding the marker; grouping by `request_id` (red on the SSE test).
  - **The panel:** 9 plan and 25 extra sabotages in vitest, among them dropping `canEditConversation`, a slide
    refetch after a delete, removing the send-sequence check, a stale closure in the delete (red only after a
    reviewer-added test), and removing the ambiguity check (W1).
  - **Playwright:** 10 production sabotages, among them a slide refetch, no local removal, the delete button for
    viewers, the Spec gate put back, and removing `disabled:opacity-0`.
- **Not verifiable locally (first run is CI):** the e2e matrix run of `delete-message`; the unit job on
  Postgres with `-n auto` (the new tests are SQLite-only by construction).

## CI history

See the PR. Rounds are recorded in the supervisor's ledger.

## Known gaps and follow-ups

- **Restore and deck delete leave the graph thread.** `restore_version` deletes later chat rows but not the
  thread, and `delete_session` orphans it. Nothing replays it, but the text stays in the checkpoint tables. The
  fix is `delete_thread(session_id, session=db)` in both transactions. Pairs with: **the checkpoint grows without
  bound** (no pruning). Not filed as issues; the user owns triage.
- **`deck_purpose: None` on `ask_data` turns after a delete or clear** until a build or edit turn. The fix (fall
  back to `read_deck_spec`) touches `nodes.py`, which #321 owns.
- **Cross-tab residual of the id pairing.** A send refused in one tab whose text matches a message stored from
  another tab can take that id when the counts happen to match. Exact fix: decision 10's upgrade path.
- **The mocked app runs SSE on localhost**, so the polling transport's id path is covered by vitest only.
- **The turn-end read downloads up to 200 full rows per turn** (large `tool_result` rows on legacy decks).
- **Inherited from #323:** the stale-lock window (300 s lock vs 600 s jobs), SSE disconnect releasing the lock,
  a delete the instant a turn completes can answer 409, and mid-turn per-slide error events ending the panel's
  loading state early.
- **Cosmetic:** `MessageList` keys rows by index, so a collapsible's open state can move to the next message
  after a middle delete. The API tests match URLs with `endsWith`, so dropping the API base URL would go unseen
  (the same as #323's clear tests).
- **Tour:** deleting a tour exchange removes its `tour_stage` rows, so a later scripted stage whose predecessor
  went with it answers 409.
- **On SQLite (tests or an explicit SQLite `DATABASE_URL`) a deleted row's id can be reused** when it held the
  table's highest id; Postgres never reuses ids.

## Expected merge conflicts

- **#319:** `ChatPanel.tsx` (the `<MessageList>` props and the `ChatInput` `disabled` expression),
  `MessageList.tsx` (imports, props, destructure), `frontend-overview.md`, `test.yml`. All keep-both.
- **#321:** `frontend-overview.md`; `real-time-streaming.md` (that one also conflicts with #323 alone). Its edits
  to `message.ts` and the ChatPanel load map merge cleanly.
- **#316:** `docs/technical/frontend-overview.md` only.
