# Interrupt generation, and all-or-nothing generations — design

Date: 2026-11-12. Status: draft for review.

Decisions are marked **(decided)** when the user made them, and **(my call)** when the
designer made them and the user has not yet confirmed them. Unmarked text describes the
code as it stands.

## Intent

A generation on an Agent deck takes minutes. Users complain that they hit Enter by
accident, or change their mind after sending. They want to stop a generation and be back
exactly where they were, as if they had never pressed Enter.

The same guarantee applies when a generation fails. The user's framing: **ACID on
generations — a generation either succeeds or fails cleanly.** A stop and a failure
both roll the deck and the chat back to the moment Enter was pressed.

## Goals

1. A **stop sign** in the chat input that stops the running generation, and the **Escape**
   key does the same. **(decided)**
2. **Instant stop** while nothing has been built: the person clicks and it stops, with no
   question. **(decided)**
3. **Stop with confirmation** once the builders have started, warning that the slides
   built so far will be thrown away. **(decided)**
4. **Rollback after a stop:** the deck, the Spec and the chat return to the state they
   were in when Enter was pressed. On a first generation that means an empty deck; on a
   later one, the previous deck. **(decided)**
5. **Rollback after a failure**, by the same mechanism. **(decided)**
6. **Nobody else's work is rolled back.** The stop respects the deck's editing lock.
   **(decided)**

## Non-goals

- **Legacy decks** (`deck_mode = "legacy"`, the monolith engine). **(decided)** Legacy
  gets no updates from now on; this feature is for Agent decks only. **Tellr MCP jobs**
  (`create_deck` / `edit_deck`) run on the monolith, so they are out of scope too.
- **Hiding in-progress slides.** **(decided)** Slides keep appearing one by one as each
  builder finishes, for the sender and for anyone else with the deck open. A stop or a
  failure removes them again, back to the deck as it was before the first one appeared.
  Strict isolation would hide them until the end, and we rejected the cost of that (see
  "Approaches considered").
- **Cancelling the model calls themselves.** An in-flight model call may run to
  completion in the background. Its output must be discarded, but it need not be aborted.
  Aborting it to save tokens is welcome if it is cheap, but it is not required.
- **The arc-review sweeper's describe-only turns** (`spec_sync.run_arc_review`). **(my
  call)** These are background turns that no user sent, so there is nothing to stop. Their
  failure semantics stay as they are.
- **The SSE transport** (`POST /chat/stream`, dev only). **(my call)** The deployed app
  polls (`POST /chat/async` + `GET /chat/poll`), and the stop sign targets that transport.
- **Re-attaching to a running generation after a page reload**, if the UI does not do so
  today. **(my call)** If the chat panel already shows a running generation after a reload,
  the stop sign appears there as well.

## Anti-goals (a failure even if it technically works)

- A stop or a failure that leaves the deck half-built, or with a Spec that no longer
  matches its slides.
- A write from a stopped or failed generation that lands after the rollback.
- Rolling back another person's edits.
- The sender has to wait for the abandoned generation's model calls to finish before they
  can send again.
- The planner "remembers" a stopped request on the next turn.

## What the user sees **(decided unless marked)**

Mockups are in `.superpowers/brainstorm/` (gitignored; `stop-sequence.html` and
`stop-confirm.html`).

**While a generation runs:**

- The send arrow in the chat input box (`ChatInput.tsx`, the `type="submit"` button) is
  replaced by a **stop sign**: a red circle with a diagonal slash (lucide `Ban`, red).
  Tooltip: "Stop generating (Esc)".
- The hint line under the box reads **"Esc to cancel · Enter to send · Shift+Enter new
  line"**. Outside a generation it reads as it does today.
- **Escape** triggers the same action as clicking the stop sign. **(my call on scope)**
  It works anywhere on the deck page, unless something else is open that already uses
  Escape: a dialog, the expanded prompt editor, presentation mode, or a menu. That thing
  handles Escape first, and the generation carries on.

**Which kind of stop applies** is decided by the turn's latest `turn_progress.phase`
(`frontend/src/types/turnProgress.ts`):

| Turn state | Stop behaviour |
|---|---|
| queued (`pending`, no progress yet), no phase yet, `planning`, `gathering_data`, `checking_slides` | **instant** |
| `building`, `reviewing_deck` | **confirm first** |

**The confirmation dialog** reuses `ConfirmDialog`:

- Title: "Stop generating?"
- Message: "Your slides are being built (N of M done). If you stop now, every slide built
  so far is thrown away and the deck goes back to how it was before you sent this
  message." N and M come from `turn_progress.slides` (`done.length`, `total`).
- Buttons: **Keep generating** (cancel) and **Stop and discard** (confirm, danger).
- **Keep generating has the focus**, so a stray Enter does not throw work away. Note
  that this is the opposite of `ConfirmDialog`'s current default, which focuses the
  confirm button. Escape inside the dialog means "keep generating".
- Generation continues while the dialog is open. If the generation finishes while the
  dialog is open, the dialog closes and the finished deck stays. **(my call)**

**After a stop** (instant, or confirmed):

- The user's message disappears from the chat.
- The deck shows its pre-Enter state.
- The text they sent goes back into the input box, cursor at the end, ready to edit or
  resend. Any images they attached go back with it. **(my call on images)**
- A small notice in the chat: "Generation cancelled. Nothing was changed."
- The input is usable at once: the person can send a new message straight away.

**After a failure:** the same as after a stop, with the notice "Generation failed.
Nothing was changed." **(my call)** The person's text goes back into the box so that
retrying is one keypress.

**If a stop is refused** (see "Locks and other people"): the generation carries on, and a
notice explains why. Wording, roughly: "Someone else has edited this deck since you sent
this, so it can't be rolled back."

**Who sees the stop sign:** only the person who sent the message, in their own chat
pane. Others with the deck open see the slides appear and, after a stop, disappear, just
as they would after any other change to the deck.

## What counts as a failure **(decided)**

A **failure** is the generation itself breaking: the turn raises, for example a 403 or a
404 from a model or a tool, or `GraphTurnFailedError`. The following also roll back the
same way:

- It **exceeds the hard time limit** (`GRAPH_JOB_HARD_TIMEOUT_SECONDS`, 1200 s).
- The **server restarts mid-generation**.

**Not a failure:** a slide that fails to build and becomes a placeholder inside a
generation that reaches the end. That generation is a success and commits as it does
today. Endings the router already treats as normal are also successes: a `discuss`
reply, or a `confirm_design_contract` question.

## Approaches considered

1. **"Latest complete generation" reads (SCD2-style tombstones).** Every write would be
   tagged with its generation, and every read would select the latest complete one.
   - It would give failure rollback for free.
   - It is rejected as the most work. It needs a schema change and a Lakebase backfill on
     the slide tables. It changes every reader of the deck: the slide repository, the
     PPTX and Google Slides export, MCP `get_deck`, presentation mode, save points,
     sharing and spec sync (`_get_deck_owner_session` alone has about 32 call sites).
   - It also breaks one-by-one slide delivery, which would then need a second read
     path for the in-progress turn.
   - Its extra benefit, history, already exists as save points.
2. **Delete the rows a cancelled generation committed.** Rejected as insufficient. An edit
   turn overwrites slides in place, deletes and moves slides
   (`SlideWriter.apply_slide_layout`), and rewrites the Spec (`write_deck_level_columns`).
   Deleting what the turn wrote cannot bring back what it overwrote. You need a
   before-image, and that is option 3.
3. **Snapshot at Enter, restore on stop or failure.** **(decided)** This needs no reader
   changes and no schema change on the slide tables, and most of it already exists (see
   below).

## The rollback model **(decided: snapshot and restore)**

### When Enter is pressed

`POST /chat/async` takes the snapshot after it acquires the session lock, and **before**
`add_user_message` (which locks the deck mode on a first message). The snapshot is
**stored in the database**, never in process memory. A stop can arrive at any of the
uvicorn processes, and recovery after a restart must be able to find it.

The snapshot holds everything a turn can change, so that it can be put back. The known
inventory:

- **Deck content.** This is the payload a save point already stores (`create_version`,
  `session_manager.py:3322`): the deck JSON, `deck_spec_json`, the verification map, and
  the presentation columns (`css`, `external_scripts_json`, `scripts_content`,
  `head_meta_json`, `title`, `slide_count`). On a first generation the snapshot records
  "no deck / no slides".
- **Session fields a first message or a turn can change:** the session title
  (`rename_session`, set by the parallel title thread), the deck mode (`deck_mode`, locked
  by `add_user_message`), and the Genie conversation ids (`set_genie_one_conversation_id`,
  `_persist_genie_conversation_ids`).
- **The planner's internal state between turns.** That is the LangGraph checkpoint for
  `thread_id = session_id`, in the custom SQLAlchemy saver (`src/core/checkpointer.py`).
  Record the latest checkpoint id before the turn, so the restore can discard every
  checkpoint written after it.
- **Chat messages** need no snapshot. Every row the turn writes, including the user's own
  message, is tagged with the turn's `request_id` (`add_user_message(..., request_id=)`
  and the graph's `set_chat_request_id`).

The snapshot must **not** appear in the user-visible save-point list. It must not count
against `VERSION_LIMIT` (40), and it must never evict a real save point. When the
generation completes, the snapshot is deleted. The normal end-of-turn save point (created
in `_send_message_streaming_graph` after the turn finishes) carries on as today, and a
stopped or failed turn never reaches it.

### When a stop is accepted, or a generation fails

1. **Fence.** The request is marked cancelled or failed **in the database**. From that
   moment, every write the turn attempts is refused: slide rows, placeholders, layout,
   Spec and deck-level columns, chat messages, progress, images and checkpoints.
   - The fence and the restore must be serialised, so that a write that has already
     passed its check cannot commit after the restore. One way is a row lock both sides
     take.
   - Every write path the graph uses must honour the fence, including the ones running
     in `Send`-fanned `slide_pipeline` branches.
   - The parallel **title thread** (`run_title_gen` in `_send_message_streaming_graph`)
     honours it too. **(my call)** Its `rename_session` can land after the restore,
     so it must check the fence, or the title must be applied only if the turn completes.
2. **Restore** the snapshot. Reuse the core of `restore_version` (`session_manager.py:3601`)
   by extracting it into a shared function. It already does most of the work:
   - re-materialises the `session_slides` rows (`_rewrite_slide_rows`)
   - copies the Spec back
   - restores the presentation columns
   - bumps `deck.version`, so open clients accept the restored deck
   - records a shared-deck mutation

   Then:
   - **Delete the turn's chat messages** by `request_id`. Do not copy `restore_version`'s
     delete-by-timestamp; it would also catch messages that are not this turn's.
   - **Put back** the session title, deck mode and Genie conversation ids.
   - **Discard checkpoints** written after the recorded checkpoint.
   - **Make no save point.**
3. **Release** the session lock and the generation's hold on the editing lock (below).
   Then report the outcome to the client.
4. **Keep these:**
   - **Images** the turn's tools saved to the person's Image Library
     (`save_generated_image`). **(decided)** They stay in the library; the restored deck
     simply no longer uses them.
   - **Usage and cost records, MLflow traces, and shared-deck mutation evidence.** **(my
     call)** Those model calls really happened, and the evidence log is append-only; the
     restore appends its own mutation row, as `restore_version` already does.

The person must be able to send again **as soon as step 3 is done**, without waiting
for the abandoned turn's in-flight model calls. That rules out holding the job runner
until the graph thread finishes: `DEFAULT_CHAT_JOB_CONCURRENCY` is 1 per process, so a
held runner would queue the next turn behind the abandoned one. The abandoned graph thread
may finish its call in the background. The fence makes everything it then tries to write
a no-op, and it must exit without side effects.

**A rollback that fails must not fail silently** and leave a half-written deck. Keep
the snapshot and mark the request so that recovery retries the restore. Until the restore
succeeds, the deck must not accept a new turn. **(my call)**

### Where each trigger runs

- **Stop:** a new endpoint, owned by the sender, for one `request_id`. It is accepted only
  while that request is `pending` or `running`. A stop that arrives after the request has
  completed returns a definite "already finished" answer, and the UI keeps the finished
  deck.
  - A `pending` request (queued behind another on its process) is removed, rolled back
    (which in practice only deletes the user message and undoes the deck-mode lock), and
    never starts.
  - Requests are tracked in memory per process (`job_queue.jobs`), so the stop must work
    through the database whichever process receives it.
- **Failure:** in `process_chat_request`'s error path, and in the graph thread's
  `except` paths in `_send_message_streaming_graph`.
- **Hard timeout:** `mark_timed_out_jobs_once`. Today it only marks the in-memory record,
  and the turn keeps running and writing ("Does NOT cancel the underlying worker
  coroutine"). Under this design it must fence and restore.
- **Server restart:** `recover_stuck_requests` at startup. Today it only handles requests
  older than 1200 s and does not restore anything. It must roll back an interrupted
  generation from its stored snapshot. Generations younger than the hard limit must not be
  left in place indefinitely; the builder decides when they are rolled back, at the latest
  when the hard limit passes.

## Locks and other people **(decided)**

Today there are two locks:

- **Session processing lock** (`user_sessions.is_processing`, `acquire_session_lock`). It
  is per session, with a 300 s staleness timeout, kept fresh by
  `refresh_job_session_locks_once` every 60 s. Manual slide edits take it too, so while a
  generation runs the sender cannot edit their own deck, even from another tab.
- **Deck editing lock** (`slide_deck.locked_by` / `locked_at`, `acquire_editing_lock`). It
  is per deck, with a 45 s timeout, kept alive by the browser's 10 s heartbeat
  (`AppLayout.tsx`). It only contends on shared decks. Contributors have their own sessions
  (`parent_session_id`), so this lock, not the session lock, keeps two people apart.

The rules:

1. **Only the sender can stop.** The stop endpoint must check that the caller owns the
   request, as `_require_chat_request_owner` does for poll.
2. **A running generation holds the deck's editing lock for its sender** until it
   completes, fails or is stopped.
   - Today the browser releases the lock after 5 minutes without mouse or keyboard
     activity (`IDLE_TIMEOUT_MS`, `AppLayout.tsx:237`), and the server lets it lapse 45 s
     after the last heartbeat. Someone watching a long generation therefore loses the lock
     mid-generation, and another editor can start changing the deck.
   - The fix must hold whether or not the sender's browser is still open. A server-side
     refresh would have to beat the 45 s timeout; today's job refresh runs only every
     60 s.
3. **Prevent other writes rather than detect them afterwards.** **(my call)** While a
   generation holds the editing lock, the server refuses every other write to that deck.
   That includes three writers that today slip past the lock:
   - **The deck owner's own chat route.** `_require_chat_permission` returns early for
     the root-session owner without calling `require_editing_lock` (`chat.py:157`), so an
     owner can start a turn while a contributor's generation runs.
   - **The arc-review sweeper.** It takes no session lock (`chat_service.py:288`), and
     `claim_due_marker` does not look at whether a generation is running. The sweeper
     must not claim a deck with a running generation. A new generation must not start
     its snapshot while an arc review holds a live claim; reuse
     `spec_sync.review_in_flight`, as `_refuse_during_an_arc_review` does for clear-chat
     and message delete.
   - **Any other path the builder's write audit finds** (for example MCP edits on the
     owner's session while a contributor generates).

   With this in place, "someone else changed the deck mid-generation" should be
   unreachable.
4. **A defensive check still runs before any rollback.** The server checks that nobody
   else has changed the deck since Enter was pressed, rather than assuming it. On shared
   decks, the shared-deck mutation log (`record_shared_deck_mutation`, with its actor
   session) is a candidate signal. If the check fires on a **stop**, the stop is refused,
   the generation carries on, and the UI says why. **(decided)** If it fires on a
   **failure**, the deck is **not** rolled back. **(decided)** We never roll back
   intentional work, even for all-or-nothing. In that case:
   - leave the deck as it stands
   - log the failure loudly
   - tell the sender honestly, roughly: "Generation failed, and it couldn't be undone
     because someone else has edited this deck since you sent your message."

   The sender can recover with a save point.

## Hazards in the current code the builder must close

- **Unconditional lock release.** `release_session_lock` sets `is_processing = False`
  whoever holds the lock, and `process_chat_request` calls it in a `finally`. After a
  stop, the abandoned job's `finally` runs late, and it would release the lock of the
  **next** turn the user has already started. Lock release must belong to the request that
  took the lock.
- **Multi-worker in-process state.** `job_queue.jobs` and the per-process deck cache
  (`_invalidate_deck_cache`) are process-local. A stop handled on process B must not rely
  on process A's memory. After a restore, every process must serve the restored deck, not
  a cached copy (see the `tellr-code-review` skill's multi-worker checklist).
- **Optimistic client state.** `ChatPanel` adds the user message and locks the deck mode
  client-side before the server answers (`ChatPanel.tsx:362-384`). Both must be undone
  client-side after a stop or a failure.
- **Two timeouts out of step.** The editing lock times out after 45 s; the job loop
  refreshes locks every 60 s.

## Constraints

- Agent decks only. No changes to monolith code paths, including MCP's.
- Python env: per-worktree `uv sync --extra dev`, run via `uv run`. Any dependency changes
  go in `pyproject.toml` and `packages/databricks-tellr-app/pyproject.toml`.
- Any new table or column ships as a startup migration on Lakebase. Keep it cheap: no
  backfill of existing rows.
- The checkpointer must keep its session-per-operation rule (`src/core/checkpointer.py`
  module docstring) when checkpoints are discarded.

## Left to the builder

- Where the snapshot lives (a new table, or a hidden kind of `SlideDeckVersion` row), and
  its schema.
- The fence mechanism, and how each write path checks it.
- The stop endpoint's name and shape, and the new terminal status names for
  `chat_requests.status` (today `pending` / `running` / `completed` / `error`). Poll must
  report a stopped request distinctly from a failed one.
- How the job runner is released promptly after a stop, while the graph thread finishes
  in the background.
- How the editing lock is held server-side during a generation.
- The signal used to detect someone else's change since Enter.
- How restart recovery chooses when to roll back an interrupted generation.
- The full inventory of turn writes. The list above is what the design found; the builder
  must confirm it against the graph nodes (`src/services/graph/nodes.py`,
  `slide_repository.py`, `deck_level_writer.py`, `deck_review_store.py`, `spec_sync.py`)
  and either restore each write or say why it stays.

## How we'll know it works

- Stop during planning, on a first generation: empty deck, empty chat, text back in the
  box, title and deck mode as before. Sending again starts a fresh first generation.
- Stop mid-build on an edit that moved, deleted and rewrote slides: the deck, Spec,
  styles and chat are identical to before Enter. The next turn's architect shows no trace
  of the stopped request.
- A builder write that arrives after the stop changes nothing.
- Sending straight after a stop starts at once, not queued behind the abandoned turn.
- A forced failure mid-build rolls back exactly like a stop.
- A forced restart mid-build is rolled back by recovery.
- A hard timeout rolls back.
- Another editor's change mid-generation makes the stop refuse, and their change survives.
- The stop works when it reaches a different uvicorn process from the job's.
