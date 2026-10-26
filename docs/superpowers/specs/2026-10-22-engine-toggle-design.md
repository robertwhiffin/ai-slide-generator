# Deck Mode toggle (agent ⇄ legacy) — design

**Date:** 2026-10-22 · **Branch:** `feat/engine-toggle-superpowers` · **Base:** `main` @ `2dc94a2d`
**Input brief:** `~/tellr-loop/engine-toggle/BRIEF.md`. It was written against `c48fcc8d`, and its
line numbers have drifted, several by 200+ lines in `session_manager.py`. Find code by symbol, not
by line.
**Revision 2 (2026-10-26):** an independent review was folded in, including a stored lock (§5.3),
which the user chose.

## 1. Intent

Today a user opts a deck out of the LangGraph agent by typing `USE LEGACY MODE` into the deck's
first message, and the engine is re-derived from the transcript on every turn. This change replaces
the magic phrase with a visible **Mode** control next to the chat box. The deck's mode becomes
**stored state on the deck**, not something inferred from what someone typed.

**Who it's for:** someone for whom agent mode has been too slow or hasn't worked, and who wants a
new deck on the legacy engine without knowing a secret phrase.

**Why the mode locks:** a deck built by one engine can't be carried on by the other.
- Agent decks depend on a deck spec, and there is no way to create a deck spec for a deck the legacy
  engine built.
- When both engines write the same deck, its stored slides diverge. That divergence is why
  stickiness exists today.

So the mode is chosen once per deck and never changes.

## 2. Goals, non-goals, anti-goals

**Goals**
- A user can pick Agent or Legacy for a new deck before its first message, without knowing any
  phrase.
- The deck's mode is a database column on the session, and it is the **only** source of truth for
  which engine a turn runs on.
- After the first message the mode can't change in either direction. The UI shows it greyed out,
  and the server refuses a change even if the UI is bypassed.
- Legacy decks don't show agent-only furniture: the pinned-version badge and the
  change-provenance notice.

**Non-goals**
- Switching an existing deck's mode, or converting a deck between engines.
- Special handling of agent decks created on beta/devloop since 2026-10-12. Beta is redeployed
  fresh from this branch.
- The sync `POST /chat` route. It is always monolith and unused by the UI, and it stays as it is.
  Known gap: a deck whose first message arrives through it stays unchosen (§5.3).
- MCP `edit_deck` on a deck created in the UI. It stays on the job queue's monolith default, as
  today.

**Anti-goals** (failures even if the feature "works")
- Clearing chat or deleting the first message unlocks the toggle or renames the deck.
- The startup migration re-runs and flips agent decks back to legacy on a later boot.
- A crash mid-migration leaves new decks defaulting to legacy.
- A failed first send leaves a deck locked to a mode the user didn't get, or with its pin
  half-changed.
- A legacy deck's change history credits legacy edits to a Graph Version.
- Hover text that assumes knowledge of the product's history (e.g. "the original generator").
- Reopening the boot-time cost fixed in PRs 338/339. That means no per-row backfill and no
  full-table scan at startup.

## 3. Fixed decisions (from the brief, restated)

1. Stored state, not transcript-derived. Engine resolution reads the column via the same owner
   hop (`_get_deck_owner_session`) it uses today.
2. Migration with no backfill logic. Create the column and set **every existing row to legacy**.
   New sessions default to agent. Under §5.3, a new session holds "not chosen yet", which runs as
   agent and locks as agent unless legacy is picked.
3. Locked after the deck's first user message, irreversibly, in both directions.
4. The typed phrase is removed. `USE LEGACY MODE` in a message is ordinary text.
5. Agent is the toggle's initial position.
6. `GraphVersionStatus` and the conversation-surface `MixedReleaseWarning` are hidden on legacy
   decks.
7. Existing beta/devloop decks don't matter.
8. Clearing chat or deleting the first message must not unlock the toggle or rename the deck.

**Production impact of decision 2.** Agent mode has never shipped to production, so no production
deck is an agent deck, and marking every existing row legacy changes nothing users see there. On
beta and devloop it knowingly turns agent decks created since 2026-10-12 into locked legacy decks
(decision 7). Rows that already carry a Conversation Pin keep it, because there is no backfill.
The §5.5 invariant applies to decks locked after this change.

## 4. What the user sees

**Placement** (the user's choice, mockup B). The control goes on the right-hand side of the hint
line under the chat textarea in `ChatInput`, where "Press Enter to send, Shift+Enter for new line"
sits today:

```
[ Ask me to create slides...                      🖼 ⤢ ➤ ]
Enter to send · Shift+Enter new line      Mode [Agent mode ▾] (i)
```

- Label **"Mode"**, a small dropdown with **"Agent mode"** and **"Legacy mode"**, and an info
  icon.
- Hovering the info icon shows a popup using the existing `src/ui/tooltip`. The user approved this
  copy:
  - **Agent mode**: plans the deck, then builds it slide by slide, showing progress as it goes.
  - **Legacy mode**: a less capable agent. Usually faster, but harder to converse with and to
    adapt to changes.
  - You can change this until you send your first message. After that it's fixed for this deck.
- Presentation details *(my calls)*:
  - The hint is shortened to "Enter to send · Shift+Enter new line".
  - The dropdown is a native `<select>`, styled like the `AgentConfigBar` pickers. `src/ui/` has no
    Switch.

**Unlocked deck** (its mode is not chosen yet): the dropdown is enabled and starts on Agent mode.
Nothing is saved when it changes (§5.2).

**Locked deck:**
- The dropdown stays in place and shows the deck's stored mode. It is greyed out and disabled,
  "a visual reference that it's set and unchangeable".
- The info popup still works. *(my call)*
- Every deck that already existed before the migration shows as locked Legacy.

**Sending the first message:**
- The UI greys the control as soon as the message is sent.
- If the send fails, the UI re-reads the session and shows whatever the server holds. Because the
  lock and the first message commit together (§5.2), a failed send leaves the deck unlocked.
- If the server refuses because the deck was locked meanwhile (another tab or a collaborator), the
  UI re-reads the session and shows the locked mode. Other open views pick up the lock on their
  next session fetch, or on their own refusal.

**Who sees what** *(my call)*: viewers without edit rights see the control greyed out, showing
the deck's mode. Collaborators see the owner deck's mode.

**Legacy decks:**
- `GraphVersionStatus` (with its "Start latest" button) and the conversation-surface
  `MixedReleaseWarning` are not rendered.
- On an unlocked deck they hide as soon as the dropdown is set to Legacy mode, before sending.
  **This changes behaviour.** *(my call)*
- The Share Deck dialog's `MixedReleaseWarning` (`surface="collaboration"`, "Who changed this deck")
  **stays**. Legacy decks carry no pins (§5.5), so it truthfully reads "Legacy (no graph
  release)". **This changes behaviour.** *(my call)*

## 5. How a deck's mode behaves

### 5.1 The column
Add a new nullable column on `user_sessions`. Suggested name `deck_mode`, with values `agent` and
`legacy`.
- **Empty (NULL)** means not chosen yet: the deck is unlocked.
- **`agent` or `legacy`** means chosen and **locked forever**. The lock is not a separate fact;
  it is "the column is set".

The column is meaningful on the **deck owner's** row. Collaborator sessions read it through the
owner hop, as they do for the engine today.

The job payload's internal `engine_mode` (`graph`/`monolith`) and `job_queue`'s `"monolith"`
default are unchanged: resolution maps the column onto those values.

### 5.2 How the choice reaches the server (F1: decided by the user)
**The choice travels with the first message.** Nothing is persisted when the toggle is changed:
"there's no benefit to saving state in a database for a conversation which hasn't happened yet."

- The UI sends the selected mode on every chat request: `/chat/async` in production and
  `/chat/stream` locally. Both bodies are built inline in `api.sendChatMessage`.
- **Deck unlocked:** the request's mode, or `agent` if it carries none, is written to the owner's
  column.
  - The write is a conditional update (`… WHERE deck_mode IS NULL`) on the owner row. It runs in
    the **same transaction as the deck's first user-message insert**, together with the pin change
    of §5.5. All of it commits, or none of it does.
  - The conditional update, not the per-session lock, is what settles a race. Collaborators on one
    deck hold different session locks, so two first messages can arrive at once. If the update
    finds the column already set, the request is treated as arriving at a locked deck.
- **Deck locked, and the request carries the same mode or none:** proceed normally. Older clients
  and non-UI callers send nothing.
- **Deck locked, and the request carries a different mode:** refuse with a 409 and a plain
  message. The user message is **not** saved. *(my call on the status and shape)*
- **Both routes must have the lock and the first message committed before resolving the engine.**
  - `/chat/async` already saves the user message before it resolves.
  - `/chat/stream` currently resolves first and lets `ChatService.send_message_streaming` save the
    message afterwards. It must be brought in line.
  - Once it is, the SSE turn-1 re-resolve has nothing left to do (§7).

### 5.3 The lock (decided by the user: a stored lock)
A deck is locked exactly when its owner row's `deck_mode` is set. Consequences:
- **First message:** sets it (§5.2). It doesn't matter whether that message comes from the owner
  or from a collaborator's session: the lock is deck-wide by construction.
- **Clear chat / delete first message (F3, untouched).** The column is not touched, so neither
  action can unlock the deck.
  - The existing hidden kept row (`engine_mode_marker`) stays exactly as it is, now only for its
    other job: it keeps `message_count > 0`, so the deck's title isn't regenerated.
  - Its docstrings change to say the engine no longer reads it.
  - It never reaches any agent. `SessionManager.get_messages` drops it, and both history builders
    (`ChatService._hydrate_chat_history`, graph `nodes._conversation`) also allowlist human message
    types it doesn't match. The graph thread is deleted on clear and delete, so nothing replays
    from checkpoints either.
- **Duplicates (decided by the user).** A duplicate copies the owner's `deck_mode` value, so it
  inherits the mode and is locked from creation.
  - The duplicate is pinned unless that value is `legacy`, with a fresh pin as today. An unlocked
    (NULL) duplicate is pinned like any new deck, because it may still lock as agent (§5.5
    invariant).
  - The legacy duplicate's carried hidden row is dropped (the brief's table says the same). A
    duplicate again carries no chat history, and duplicates of either mode get an auto-title on
    their first message, as agent duplicates do today. **This changes behaviour for legacy
    duplicates.** *(my call)*
  - A source that was never messaged (NULL) gives an unlocked duplicate, because no conversation
    has happened. *(my call)*
- **MCP `create_deck`:** creates the session with `deck_mode = legacy` and no pin. The
  `with_legacy_marker` prepend is dropped, and MCP stays legacy.
- **Tour:** creates its session with `deck_mode = agent` and a pin. It writes its own first user
  message, not through a chat route.
- **Pre-existing decks:** every row the migration finds is `legacy` and locked, including decks
  that never had a message. This replaces revision 1's "old empty decks choose freely" and removes
  a state where such a deck would display Agent while storing legacy.
- **Sync `POST /chat`** (out of scope): it neither sends nor writes a mode. A deck whose first
  message arrives through it stays unchosen, which is acceptable because the UI never uses it.

The session response exposes `deck_mode` (`null` | `agent` | `legacy`), resolved via the owner.
`null` tells the UI the deck is unlocked. The transcript can't tell the UI any of this after a
clear or on a duplicate.

### 5.4 Engine resolution
`resolve_engine_mode` reads the owner's column instead of the earliest user row: `legacy` →
`monolith`, `agent` → `graph`. NULL → `graph`, the default. NULL can only be read on paths that
didn't lock first, i.e. sync `/chat`, which ignores the answer.

The fail-closed wrapper (`resolve_engine_mode_or_unavailable`, 503 / error event) and the "missing
session → monolith" answer are unchanged.

### 5.5 Conversation Pins (F2: decided by the user)
**Invariant (for decks locked after this change): every session on an agent deck, owner and
collaborators, has a pin. No session on a legacy deck has one.**
- The UI keeps creating new decks pinned: `POST /sessions` with `graphCapable: true`, and
  `ensureGraphCapableRoot`. The contract fixture `graphLifecycleContract.json` is unaffected.
- **Locking as legacy:** the owner's pin and every collaborator session's pin are cleared in the
  same transaction as the lock (§5.2). No turn has run yet, so no conversation has used the pin.
- **Locking as agent:** if the owner has no pin, it is pinned in that transaction. That happens if
  the deck was created unpinned, e.g. by an old client.
- **New collaborator sessions** are unpinned on a legacy deck. On agent and unlocked decks they are
  pinned, as today; if an unlocked deck later locks as legacy, their pin is cleared then.
- **Why:** every deck mutation stamps the actor's pin into `SharedDeckMutationEvent`, and the Share
  dialog's "Who changed this deck" groups by it. A pinned legacy deck would credit legacy edits to
  "Graph Version N".
- **The pin is immutable by convention, not by a DB guard.** Clearing it is allowed only in this
  locking transaction.
  - `deck_mutation_context` snapshots a session's pin before a deck write, and
    `record_shared_deck_mutation` rejects a snapshot that no longer matches.
  - So a mutation on an unlocked deck, such as a manual blank-slide insert, must not straddle the
    lock. That race is narrow, and the builder must make sure the failure mode is a clean refusal,
    not a corrupted event.

### 5.6 The phrase goes (decision 4)
The following are removed:
- `LEGACY_MODE_PHRASE`, `selects_legacy_engine`, `selects_graph_engine` and `with_legacy_marker`.
- Every `graph_capable=selects_graph_engine(message)` call site: the chat routes'
  `_maybe_create_session` and the `ChatService` auto-create paths. These keep creating pinned
  sessions, matching the UI.

`ENGINE_MODE_MARKER_MESSAGE_TYPE` and `is_transcript_message` **stay** (F3).

## 6. Migration
- One step in the startup migration chain (`src/core/database.py`), using the existing pattern:
  if the column isn't there, `ALTER TABLE … ADD COLUMN`.
  - The branch is entered once per database, so it can never re-run.
  - No `data_migrations` entry is needed.
  - It runs inside `_run_migrations`' `engine.begin()` block. On Postgres, DDL is transactional, so
    the step's statements commit together or not at all, and a crash between them can't leave new
    decks defaulting to legacy.
- **Postgres** (the user's preferred form), two statements:
  - `ADD COLUMN deck_mode VARCHAR(16) DEFAULT 'legacy'` fills every existing row as part of the
    add. A constant default is metadata-only, so there's no table rewrite.
  - `ALTER COLUMN deck_mode DROP DEFAULT` then makes new rows NULL (not chosen yet). Existing rows
    keep `legacy`.
- **SQLite** (local dev databases only): SQLite can't drop a column default. So add the column
  without a default, then `UPDATE … SET deck_mode = 'legacy'` in the same branch. Local databases
  are small.
- **Fresh databases** are built by `create_all` from the ORM model, where the column is nullable
  with no default. They have no old rows, so they never enter the branch.
- **Rolling-deploy window (accepted):** an old instance still serving during a deploy creates
  sessions without knowing the column. Those land NULL, which locks as agent on their first message
  under the new code, even if that message carried the old phrase. Decision 7 covers it: beta is
  redeployed fresh and prod has no agent mode.

## 7. Removed code (F4: decided by the user)
- **The startup pin backfill:** `backfill_conversation_pins` / `_backfill_in_transaction` in
  `src/services/conversation_pins.py`, and its call in
  `packages/databricks-tellr-app/databricks_tellr_app/run.py`. It runs on every boot, unguarded,
  with a window function over every user message. Once every existing deck is legacy it can never
  find anything.
- **`AGENT_MODE_PHRASE`:** its only remaining user is that backfill.
- **The SSE turn-1 re-resolve** in `ChatService.send_message_streaming` (the `if not request_id:`
  block). After §5.2, the stream route locks and saves the first message before resolving.
  *(my call: follows from F1)*
- `_selects_agent_mode`, and the duplicate's phrase-based `source_is_graph` and marker carry.
  They are replaced by reading the column.

## 8. Glossary (F5: decided by the user)
Add to `CONTEXT.md`:

**Deck Mode**: which engine a deck's conversation runs on, **Agent mode** (the LangGraph agent) or
**Legacy mode**. It is chosen with the deck's first message and fixed for the deck's lifetime after
that. Duplicates inherit it, and collaborators share the owner's. *Avoid, in UI copy and docs:*
engine mode, graph/monolith, "USE LEGACY MODE". (`engine_mode` stays as an internal job-payload
field.)

Amend **Conversation Pin**: it is selected for Agent-mode decks only. Legacy-mode decks have none.

On screen the control is labelled just "Mode". The qualified term exists because bare "mode"
already means three other things: MCP's generate/edit `mode`, Presentation Mode, and the app's
`viewMode`.

## 9. Performance
- **Per turn:** engine resolution becomes a column read on the owner row it already loads, instead
  of an ordered query over `session_messages`.
- **Boot:** removing the backfill drops a full scan of user messages from every startup. The
  migration is one metadata-only `ALTER` pair on Postgres.
- **No extra requests:** the toggle makes no network call. The mode rides on the existing chat
  request, and the lock is one conditional `UPDATE` inside the first message's existing
  transaction.

## 10. Constraints
- Run Python through the per-worktree uv `.venv` (`uv run …`). No `pip install`; dependency changes
  go through `pyproject.toml` and `uv lock`.
- There is no local Postgres, so Postgres-backed tests skip, **including the migration proof**. A
  skip is not a pass (§12).
- Every Playwright or dev-server run is wrapped in `~/tellr-loop/bin/e2e-lock acquire superpowers`
  / `release superpowers`, because ports 3000/8000 are shared.
- No push, PR, issue, publish-dev or deploy without asking the user.
- Fields mirrored in two TS places is a known repo pattern (it happened with `DeckSpec`). If the
  `Session` TS type (`frontend/src/services/api.ts`) gains `deck_mode`, check for a second
  mirror.

## 11. Left to the builder
- The column name and the request/response field names (suggested: `deck_mode` everywhere).
- How the first-message transaction is shaped on each route (§5.2). For example, `add_message`
  could take the requested mode, or a dedicated first-message method could do it.
- The exact 409 error shape (§5.2).
- Where in `SessionContext` the mode lives, and how the optimistic lock is reconciled.
- How a mutation on an unlocked deck is kept from straddling the pin clear (§5.5).

## 12. Verification
**Each rule gets its own test, written to fail first.**

| Rule | Test |
|---|---|
| §5.2 | The first message with `legacy` locks legacy, and that same turn runs on the monolith, on both `/chat/async` and `/chat/stream` |
| §5.2 | The first message with no mode locks agent |
| §5.2 | A locked deck plus a different mode → 409, the user message is not saved, and the column is unchanged |
| §5.2 | Two first messages from two sessions on one empty deck → exactly one mode wins, and the loser either proceeds (same mode) or gets a 409 (different mode) |
| §5.2 | A failed first-message save leaves the deck unlocked, with its pins unchanged |
| §5.3 | Clear chat on a locked deck → still locked, title unchanged; the same for deleting the first message |
| §5.3 | A duplicate copies the mode (agent → pinned and locked, legacy → unpinned and locked); no message row is carried |
| §5.3 | MCP `create_deck` → legacy, unpinned, and the first message is persisted verbatim (no phrase) |
| §5.3 | The tour → agent and pinned |
| §5.3 | The typed phrase in a first message is ordinary text: the deck locks agent |
| §5.4 | Resolution reads the column via the owner hop for a collaborator session |
| §5.5 | Locking as legacy clears the owner's and every collaborator's pin; new collaborators on a legacy deck are unpinned; locking as agent pins an unpinned owner |
| §5.5 | Mutation provenance on a legacy deck records no Graph Version |
| §6 | The migration fills existing rows with legacy, new rows are NULL, and a second run is a no-op that leaves agent decks agent (SQLite locally; Postgres below) |
| §4 | UI: the control starts on Agent when unlocked; greyed with the stored mode when locked (including after a clear and on a duplicate); badge and notice hidden on legacy and when Legacy is selected; the popup copy |
| §4 | UI: the chat request body carries the selected mode; a 409 or failure re-reads the session |

**The regression net** is the existing files to keep green. Each of the ~23 files that reference
the phrase or the marker gets a deliberate keep, rewrite or delete.
- Backend (`uv run pytest`): `tests/unit/test_engine_mode_selection.py`,
  `test_engine_mode_wiring.py`, `test_conversation_pin_creation.py`,
  `test_remaining_creation_locks.py`, `test_clear_context.py`, `test_delete_message.py`,
  `test_earliest_user_message.py`, `test_mcp_server.py`, `test_tour_ships_a_spec.py`,
  `test_startup_migrations.py`.
- Backend integration: `test_graph_mode_turn.py`, `test_architect_reply_is_persisted.py`, and the
  Postgres files `test_conversation_pin_migration_postgres.py`,
  `test_conversation_creator_exclusions_postgres.py` and `test_graph_lifecycle_runtime_postgres.py`.
- Frontend: `npm run test:unit` (vitest: `GraphVersionStatus.test.tsx`,
  `MixedReleaseWarning.test.tsx`, the ChatPanel tests, `ChatInput`) and `npm run test`
  (Playwright: `conversation-graph-version.spec.ts`,
  `graph-release-conversation-journey.spec.ts`, `mixed-release-collaboration.spec.ts`).

**Postgres proof.** The Postgres migration and the Postgres-only tests can't run locally. The plan
must name where they run (likely a devloop deploy, via the `deploy-tellr-dev` skill). That run
needs the user's sign-off, since it involves a push and a publish-dev, and it must happen before
the branch is called done. Until then, those results are reported as **not run**.

## 13. Calls I made (for the user to check)

**These change what users see:**
1. On an unlocked deck, the badge and notice hide as soon as Legacy is selected, before sending.
2. The Share-dialog "Who changed this deck" list stays on legacy decks.
3. Legacy duplicates no longer carry the hidden row, so like agent duplicates they get an
   auto-title on their first message.
4. A never-messaged source gives an unlocked duplicate.

**Presentation and plumbing:**
5. The shortened hint text and the native `<select>`; the info popup still works when the control
   is locked.
6. Read-only viewers see the control greyed out.
7. A different mode on a locked deck gets a 409 and the message isn't saved.
8. The SSE turn-1 re-resolve is removed.
