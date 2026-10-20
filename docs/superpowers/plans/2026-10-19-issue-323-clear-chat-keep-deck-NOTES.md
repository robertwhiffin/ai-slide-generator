# #323 Clear chat, keep the deck: notes for the reviewer

**Branch:** `feat/323-clear-chat-keep-deck` (off `origin/main` 679d2f21)
**Plan:** `2026-10-19-issue-323-clear-chat-keep-deck.md` (revision 2, after an independent plan review)
**Built by:** a supervisor agent overnight, with sub-agents for planning, plan review, tests,
implementation, per-task review and a final whole-branch review. Nobody asked the user any questions.
The decisions below were made on the user's behalf.

## What shipped, by acceptance criterion

**A1: a confirmed "Clear chat" action that empties the panel, leaving the deck, slides and Spec view unchanged.**
- **The button.** It sits in the chat panel header (`ChatPanel.tsx`). It reuses the shared
  `ConfirmDialog`, and its copy lives in `clearChatCopy.ts`.
- **The call.** It goes through `conversationApi.clearChat` (`frontend/src/api/conversation.ts`) to the
  existing `DELETE /api/sessions/{id}/context`.
- **On success.** Only the panel's local messages (and its last-replacement feedback) are emptied. It
  never refetches the slides, the Spec or the session.
- **Planning found that the existing route was not safe to put a button on.** Three things were fixed
  in the backend:
  1. **The kept first message came back.** `clear_context` keeps the deck's earliest user row, because
     engine mode is read from it. That row was still returned after a reload, and it was still replayed
     to the architect as conversation. The clear now re-types it `engine_mode_marker`.
     `SessionManager.get_messages` and save-point capture drop that type. Engine-mode, pin, duplicate
     and `message_count` reads go by role only, so they still see the row.
  2. **The clear was two transactions.** `delete_thread` committed on its own connection while the
     prune was still open. On file-backed SQLite that self-deadlocked (`database is locked`). On
     Postgres it could leave the thread deleted and the transcript intact. Now `delete_thread(...,
     session=db)` runs on the clear's own session, so the prune, the marker re-type, the attribution
     row and the thread delete commit or roll back together.
  3. **Any editor could clear the owner's chat.** The route checked only CAN_EDIT on the root deck. See A4.

**A2: the next turn picks up the persisted `deck_spec` and the committed slides. "make slide 3 shorter"
works without the old transcript and doesn't rebuild unrelated slides. A graph test and an e2e test.**
- **What the architect receives.** Nothing in the graph changed. After a clear the payload carries:
  - `conversation`: only the new turns;
  - `current_deck_spec`: the persisted spec;
  - `committed_slide_count`;
  - `previous_deck_review`, keyed by the digest of the committed rows.
- **"The committed slides" means those row-derived fields, not slide HTML (Decision D10).** Adding the
  HTML would change a pinned Agent Definition's model-facing payload.
- **Graph test** (`tests/integration/test_clear_context_graph_turn.py`). It runs build, clear, then
  "Make slide 3 shorter" through the real compiled graph and architect node, on file-backed SQLite with
  the real checkpoint saver. It asserts:
  - the architect payload holds the four fields above;
  - only position 2 was rebuilt, and rows 0, 1 and 3 are byte-identical;
  - the spec changed only at slide 3;
  - the thread was deleted and the pin read back unchanged.

  **The model runtime is stubbed and the edit target is scripted.** This test proves what the architect
  is given, not that a model would pick slide 3.
- **E2E** (`frontend/tests/e2e/clear-chat.spec.ts`, mocked backend). It covers the user journey: clear,
  reload, then an edit turn. It **cannot detect a backend regression**, because it scripts the stream.
- **Full-stack route test** (`tests/integration/test_clear_chat_routes.py`, TestClient against the real
  routes, services and database). It runs a **scripted** tour review/edit turn after the clear. There
  is no model in it.
- **No test in CI runs a model after a clear,** because CI has no model endpoint.

**A3: engine, Graph Release pin and save points kept.**
- **Engine.** The kept row is still the deck's earliest user row. Tests:
  - `test_a_later_legacy_phrase_after_a_clear_does_not_move_a_graph_deck`;
  - `test_a_duplicate_of_a_cleared_legacy_deck_stays_legacy_and_shows_no_chat`;
  - the graph test asserts the deck resolves to `"graph"`.
- **Pin.** `graph_release_id` is never touched. Both the graph test and the route test read it back with
  `load_conversation_pin`. The e2e test checks that the pin text is unchanged.
- **Save points.** Tests:
  - `test_a_clear_leaves_every_save_point_untouched` compares every column of every version;
  - `test_a_save_point_taken_after_a_clear_captures_no_marker`;
  - the route test takes a real save point before the clear and checks its preview's `chat_history`
    afterwards;
  - the e2e test checks the save-point trigger.

**A4: editors only on shared decks, attributable, and a decision on contributors.**
- **Route order** (`clear_session_context`):
  1. CAN_EDIT deck gate, resolved on the root deck. A viewer gets 403.
  2. The new `_require_conversation_creator` (`_authz.py`). It makes the same comparison
     `GET /messages` makes. No user gets 401, and anyone but the session's own `created_by` gets 403.
  3. The session lock. While a turn or slide operation holds it, the route answers 409 with
     `CONVERSATION_BUSY_DETAIL` and does not release someone else's lock.
  4. The clear.
  5. The release, in `finally`.
- **Attribution.** Each clear writes one `usage_events` row (`context_cleared`, `username = cleared_by`,
  the session's internal id) **in the clear's own transaction**, so the row exists if and only if the
  clear committed. Both log lines carry `cleared_by`. Nothing in the UI shows it, and that is deliberate
  for a private conversation.
- **The frontend.** The button shows only for `CAN_EDIT`/`CAN_MANAGE` (`canEditConversation`), on a
  persisted deck that has a Spec. It is disabled while a turn runs, while a clear runs, in read-only or
  preview mode, and when there are no messages.

## Decisions made on your behalf

1. **What a contributor's clear means: their own session only.** That is their own transcript and their
   own graph thread, never the owner's.
   - A contributor session is its own `UserSession` row (`parent_session_id`), with its own transcript,
     graph thread (`thread_id` = its session id) and Conversation Pin.
   - Conversations are already creator-only everywhere else (`GET /messages`, `GET /sessions/{id}`,
     chat).
   - Engine mode resolves on the owner's rows, so a contributor's clear can't change it.
2. **The half-state is closed in the backend (one transaction).** It is not left to the UI. The UI still
   handles failure: it keeps the conversation and says "Couldn't clear the chat. Reload the page to see
   its current state, then try again."
3. **The kept row stays, re-typed and hidden.** Two alternatives were rejected:
   - *Deleting it.* A later `USE LEGACY MODE` message would then become the earliest row and move a
     graph deck.
   - *A new `engine_mode` column.* That needs a migration, and it breaks the "nothing about mode is
     stored" rule.
4. **Attribution goes through the existing `usage_events` table.** It needs no migration and is already
   durable. `SharedDeckMutationEvent` was rejected: it would need a CHECK-constraint migration, and it
   would report a private chat clear as a deck change. A side effect is that the admin analytics now
   count a clear as user activity.
5. **A clear is refused mid-turn (409), through the existing DB-backed session lock.** That lock works
   across workers. The arc-review sweeper takes no session lock, so a clear is also refused (409) while
   the deck's arc review holds a live claim (see Known gaps, "Corrected").
6. **Copy.**
   - Busy (409): "Something is still running on this deck. Wait for it to finish, then clear the chat."
   - Forbidden (403): "Only editors can clear the chat, and only their own conversation."
   - The dialog wording is in `clearChatCopy.ts`.
7. **Legacy (monolith) decks with no Spec are not offered the button.** The route still works for them.
8. **The real-backend Playwright spec was dropped** in favour of the TestClient route test (plan review
   F1). The CI e2e backend runs with a fake `DATABRICKS_HOST`, which puts identity in WORKSPACE mode.
   Reading a deck with slide rows then hangs on SCIM display-name lookups. Blanking those credentials
   for the shared e2e job would change the identity mode for every real-backend spec, so that is left
   for you to decide (see Follow-ups).

## Deviations from the plan

- **Task 7 changed.** It was a real-backend Playwright spec (rev 1). It is now the TestClient route test
  (rev 2, decision 8 above). The route test gained two cases:
  - another CAN_EDIT editor gets 403, using a real `DeckContributor` row and not a patched gate;
  - a clear while the lock is held gets 409, and the lock stays held.
- **Fixes from the per-task reviews:**
  - **T5.** The permission re-read fired on every session switch that flips "persisted", which happens
    on every `/sessions/X/edit` page load. It now fires only for the same id, with a new test.
  - **T2.** A test now proves that only the marker type is hidden: untyped, `info`, `reasoning` and
    similar rows stay visible.
  - **T1 and T3.** Docstring and E501 fixes.
- **Fixes from the whole-branch review:**
  - **W2.** A lock-release failure after a committed clear no longer turns into a 500.
  - **W6.** A late clear response for the previous session no longer unlocks the new session's
    running clear.
  - **W11.** The route log line now carries `cleared_by`.
  - **W1.** The graph test's docstring was corrected.
  - **W3.** The plan's #317 hand-off now states the earliest-user-row rule.

## Test evidence

- **Baselines are recorded as causes, not counts.**
  - Backend `tests/unit`: 9166 passed, 0 failed at baseline. 9196 passed, 137 skipped, 0 failed at the
    end. The new skips are 4 Postgres-only tests.
  - Frontend vitest locally: 20 tests in 3 SlideViewer files fail at baseline and at the end, all from
    one cause. Node 26 leaves `localStorage` undefined, and CI runs Node 20.
  - `eslint .` is not clean on `main` (63 errors), and CI does not run it. No file we touched gained a
    finding.
- **Local results.**
  - The integration files touched: 68 passed.
  - The whole-branch reviewer ran the full integration-general list (136 passed) and the full
    integration-graph list (206 passed) under CI's environment.
  - The mocked e2e spec passed 6/6 locally, and 12/12 with `--repeat-each=2`. This needed a local
    workaround: Playwright 1.57 wants Chromium build 1200, and only 1194 is cached on this laptop.
- **Sabotage.** Every approved test was broken against production code, and each named test went red.
  The controller and the reviewer used different targets. Selected results:
  - **The one-transaction clear:**
    - calling `delete_thread` without `session=` turned 3 red;
    - a commit inside the session branch turned 3 red;
    - a commit after the bulk delete turned 3 red;
    - writing the usage event outside the transaction turned 1 red;
    - removing the `cleared_by` guard turned 2 red.
  - **The hidden marker:**
    - dropping the re-type turned 8 red;
    - dropping the `get_messages` filter turned 5 red;
    - dropping the save-point filter turned 1 red;
    - filtering `message_count` turned 1 red;
    - deleting the marker instead turned 11 red;
    - making `is_transcript_message(None)` false went red only after the reviewer added a test for it.
  - **The route:**
    - releasing the lock on a 409 turned 1 red;
    - swapping the creator gate and the lock turned 5 red;
    - comparing against the parent's or root's creator turned 1 red;
    - dropping the 401 turned 2 red;
    - releasing only on success turned 2 red;
    - leaking `SessionNotFoundError` turned 1 red;
    - running the creator gate before the deck gate turned 7 red.
  - **The route test:**
    - skipping the thread delete, the `get_messages` filter or the re-type, deleting save points,
      releasing on a 409, and removing the creator gate each turned it red.
  - **The frontend:**
    - a `getSlides` refetch after the clear, dropping the stale guards, dropping `canEditConversation`,
      deleting the became-persisted effect, dropping the `isClearing` input guard, and mapping 409 to
      the generic copy each turned vitest red;
    - in Playwright, a `getSlides` refetch turned 1 red, and not emptying the messages turned 3 red.
- **Not verifiable locally; both passed in CI round 1:**
  - The `@pytest.mark.postgres` class in `tests/unit/test_clear_context.py` checks the single
    transaction on real Postgres, and that no new DBAPI connection opens during `delete_thread`. It
    skips locally because there is no Postgres here. Two reviewers read it line by line against the CI
    unit job (Postgres 15, `-n auto`).
  - The e2e matrix run of `clear-chat`.

## CI history

- **Round 1 (PR #331, Test Suite run 39399590333): green on the first push.** 66 checks passed. The
  only two not run, "Agentic Behaviour (layer 3)" and "deploy", skip on every PR.
  - The unit job ran 9135 passed and 232 skipped against Postgres 15. Both
    `TestTheClearAgainstRealPostgres` tests ran there for the first time and passed. They are
    `test_the_clear_is_one_transaction_on_postgres` and
    `test_a_failed_commit_on_postgres_leaves_everything`.
  - Integration: General ran all three `test_clear_chat_routes.py` tests, and all passed.
  - Integration: Graph Orchestration ran `test_clear_context_graph_turn.py`, and it passed.
  - `E2E - clear-chat` passed.
- **No re-runs and no fixes were needed.**

## Known gaps and follow-ups

- **A real-backend Playwright spec needs your ruling.** It would require blanking `DATABRICKS_HOST` and
  `DATABRICKS_TOKEN` for the shared e2e backend, which changes the identity mode for all real-backend
  specs.
- **`ask_data` after a clear sends `deck_purpose: None` on its first turn.** The analyst reads it from
  the thread. Duplicates and a contributor's first turn already do the same, and the analyst has no
  tools today. The fix (fall back to `read_deck_spec`) touches `nodes.py`, which #321 owns.
- **The stale lock window.** The session lock counts as stale after 300 s, but async jobs can run for up
  to 600 s. After a reload in the middle of a long turn the button is enabled again. A clear made
  300–600 s into that turn succeeds, and the job's later replies land in the cleared chat. Every lock
  user already behaves this way.
- **SSE disconnect.** A client that disconnects mid-turn on SSE (local dev) releases the lock while the
  graph keeps running. Production polls.
- **After a save-point restore in the same tab, the button can stay hidden until a reload.** The
  restored deck object carries no `deck_spec`. This is the safe direction, and SpecView already shows
  its empty state in the same way.
- **A CAN_EDIT user who opens the owner's session URL directly sees a disabled button.** That view has
  no messages, and the backend refuses the clear in any case.
- **A clear between the tour's review and edit stages makes the edit stage answer 409.** The tour
  swallows that error.
- **The welcome text after a clear is the new-deck welcome.** Wording written for a cleared deck belongs
  to #319's surface.
- **Corrected: a clear during an arc review used to leave pre-clear state in the thread.** This list
  said the sweeper's post-clear checkpoint was harmless "because the thread holds only per-turn state".
  That premise (plan Context 7) is false. #317's planning found it, and a test here confirms it.
  - The sweeper (`spec_sync.sweep_once` → `run_arc_review` → `invoke_graph`, `src/services/spec_sync.py`)
    runs a graph turn on the owner's thread without the session lock. `thread_id` is the session id
    (`src/services/graph/builder.py`, `config = {"configurable": {"thread_id": session_id}}`), so the
    next turn after a clear resumes the same thread.
  - The turn loads the thread before its architect runs and writes a checkpoint after every superstep,
    carrying every channel. A clear that committed during the review's model call deleted the thread,
    and the review then wrote it back with the pre-clear `findings` (an all-turns log,
    `src/services/graph/state.py`), the pre-clear turn's scoped state, and a reply from an architect
    that had been given the cleared conversation. The next turn's state inherited those findings. No
    agent payload carried pre-clear text: the architect reads `conversation` from the rows and
    `message` from the turn's input.
  - **Fixed:** `clear_context` now refuses with `ArcReviewInFlightError` while the deck's review holds a
    live claim (`spec_sync.review_in_flight`, the inverse of the sweeper's own lease test). It reads the
    deck row `FOR UPDATE` before changing anything. The route answers 409 with
    `CONVERSATION_BUSY_DETAIL`. Proof: `test_a_clear_during_an_arc_review_leaves_nothing_from_before_it`
    (`tests/integration/test_clear_context_graph_turn.py`, real compiled graph and real saver, stubbed
    model) is red without the refusal. Unit tests in `TestTheClearWaitsForAnArcReview` cover the lease
    edge and the contributor case.
  - **Cost:** if a worker dies mid-review, its claim blocks the owner's clear until the claim is
    `CLAIM_TTL_SECONDS` (900 s) old. The sweeper waits out the same lease before it claims again.
- **Pre-existing, not changed:**
  - a duplicate of an *uncleared* legacy deck shows the carried first prompt;
  - `save-points-versioning.md` §9 still has the stale "chatKey remount" line.

## Extension points for #317 (delete a message), which branches from here

- **Reset the chat is this feature.** It uses `DELETE /api/sessions/{id}/context` and
  `conversationApi.clearChat`, and needs no new backend.
- **Backend permission check.** Use `_check_deck_permission_for_session(..., CAN_EDIT)` together with
  `_require_conversation_creator(session_id)` (`src/api/routes/_authz.py`). For the busy case, reuse
  `CONVERSATION_BUSY_DETAIL` and the "acquire, 409 without release, release in a guarded `finally`"
  pattern from `clear_session_context`.
- **Never delete a session's earliest `role='user'` row.** It is the engine-mode row, whether or not a
  clear has re-typed it. "Deleting" it means re-typing it to `ENGINE_MODE_MARKER_MESSAGE_TYPE`
  (`src/domain/conversation_engine.py`, with `is_transcript_message()`), as `clear_context` does. Treat
  an already-hidden row as 404.
  - The "earliest user row" query has four copies: `resolve_engine_mode`, `clear_context`, the
    duplicate carry and the pin backfill. Extract one helper rather than adding a fifth.
  - `get_messages` hides the marker, so look up rows to delete by id directly.
- **Attribution.** Add `EVENT_MESSAGE_DELETED` beside `EVENT_CONTEXT_CLEARED`
  (`src/database/models/usage_event.py`) and write it in the delete's own transaction.
- **No graph-thread change is needed.** The architect's conversation is read from the rows every turn.
- **Frontend.**
  - Add `conversationApi.deleteMessage(sessionId, messageId)` in `frontend/src/api/conversation.ts`. It
    throws the existing `ApiError` through `errorFrom`.
  - Gate the action with `canEditConversation` (`frontend/src/utils/conversationPermissions.ts`).
  - Confirm it with `ConfirmDialog`.
  - Reuse `clearChatErrorMessage`'s status mapping, or add a sibling copy module.
  - The panel will need message ids. `loadSessionMessages` drops `msg.id`, and the UI `Message` type
    has no `id` field yet.
- **Optional shape changes** (whole-branch review W9):
  - `_require_conversation_creator` could return the session info it already reads;
  - the lock block could become a context manager.
- **Merge note:** expect a trivial conflict with #319 at the `ChatInput` `disabled` expression in
  `ChatPanel.tsx`. The `isClearing` term is on its own line.
