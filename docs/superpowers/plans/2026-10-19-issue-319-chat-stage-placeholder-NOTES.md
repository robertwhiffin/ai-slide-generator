# #319: chat placeholder shows the graph's stage. Notes for the reviewer

Plan: `2026-10-19-issue-319-chat-stage-placeholder.md` (this directory).
Branch: `feat/319-chat-stage-placeholder`, based on `679d2f21`.
The supervisor ledger, plan review and corrections are kept outside the repo, under `~/tellr-loop/issues/issue-319/`.

## What shipped, by acceptance criterion

**A1. The placeholder reflects the graph's current stage on polling (production) and on SSE.**

- **One stage summary per turn.**
  - `src/services/graph/progress.py` holds a `TurnProgress` tracker.
  - `invoke_graph` installs it with `turn_progress_scope()` for exactly the duration of the invoke, and removes it in a `finally`.
  - Every concurrent `slide_pipeline_node` task reports into this one object, because a context copy shares it.
- **What it reports.** The phase (`planning`, `gathering_data`, `checking_slides`, `building`, `reviewing_deck`), the covered slide positions, and one stage per slide (`building`, `reviewing`, `fixing`, `done`).
- **SSE.** Each change is published as a new `turn_progress` `StreamEvent`. It is queued inside the tracker lock, so queue order is `seq` order.
- **Polling.**
  - The same snapshot is written to two new nullable columns on the turn's own `chat_requests` row, `progress_json` and `progress_seq`.
  - The write is a conditional `UPDATE … WHERE progress_seq IS NULL OR progress_seq < :seq`, done outside the lock. Concurrent per-slide writers can therefore never move the row backwards.
  - On PostgreSQL the row-lock wait is capped by `SET LOCAL lock_timeout = '2s'`.
  - `GET /api/chat/poll` serves the row as `turn_progress` behind the existing creator-only gate. It reads only the database, so any uvicorn worker returns the same stage. It returns null once the request is completed or errored.
- **Frontend.**
  - `startPolling` forwards a snapshot only when its `seq` rises.
  - `ChatPanel` keeps the newest snapshot of the current turn: older, repeated and malformed ones are ignored, and it resets at send.
  - `MessageList` renders `describeTurnProgress()` from `frontend/src/utils/turnProgress.ts`.
- **Copy.** These are the issue's examples, verbatim: "Planning the deck…", "Building 10 slides…", "Reviewing slide 3…", "Fixing 2 slides…", "Reviewing the narrative…". Overlapping stages read as one sentence with a done count, e.g. "Building 3 slides, reviewing 2 slides, fixing slide 6… (4 of 10 done)". Slide numbers are 1-based.

**A2. Driven by events the graph already emits, not timers.**

- **Where the reports sit.** Each one is next to an existing emit or at a stage boundary:
  - the architect at entry, and before a deck-level re-review;
  - the data analyst at entry;
  - the foreman beside its "Building N slide(s)." emit;
  - each pipeline after its draft write (reviewing), before it waits for a fix slot (fixing), and at each of its three returns (done);
  - the placeholder node, for its placeheld slides, in one snapshot;
  - the deck reviewer at entry.
- **No timers.** No timer, heartbeat or interval was added. A report that changes nothing publishes nothing.
- **The rotating `LoadingIndicator` jokes are left alone** (D16).

**Legacy (monolith) engine.** The monolith never calls `invoke_graph`, so it never installs a tracker. Its reports are no-ops, its columns stay NULL and the poll returns `turn_progress: null`. The placeholder still reads `Generating slides...` byte for byte. MCP is unaffected.

## Decisions made on the user's behalf

- **Persistence.**
  - Choice: two nullable columns on `chat_requests`.
  - Rejected:
    - a `SessionMessage`, because it pollutes the transcript, `_conversation` and clear-chat;
    - the in-process `job_queue.jobs`, because it is invisible to other workers;
    - overloading `result_json`, which MCP reads;
    - deriving the stage from slide rows, which cannot tell reviewing from fixing.
  - Consequence: a new idempotent startup migration, `_migrate_chat_request_progress`.
- **Concurrency semantics.**
  - Phase rank: planning = gathering_data = checking_slides < building < reviewing_deck. The same-rank phases may alternate, because of the ask_data loop.
  - Each slide's stage only moves forward.
  - The covered set only grows.
  - Per-stage counts can go down as slides move on. That is truthful, not a regression.
- **No throttling.** At most about 3N+5 single-row UPDATEs per turn.
- **Event name.** The event is `turn_progress`, not `progress`, because Playwright mocks already send an ignored `progress` type.
- **Chat-only turns** (discuss, confirm design contract, degraded edit) show "Planning the deck…" for their single architect call.
  - Considered and rejected: "Working on your request…", and a variant keyed on whether a deck exists. Reasons:
    - "Planning the deck…" is the issue's own example;
    - the architect's job each turn is the deck plan;
    - the intent is unknown until the model returns.
  - **This copy needs the owner's sign-off.**
- **Edit turns.** No separate "Editing" label. The total is the edit's targets, e.g. "Building slide 2…".
- **The bottom `LoadingIndicator` is unchanged.** It has timer-rotating jokes and is shared with the monolith's tool-call text. Whether to retire it on graph turns is a follow-up UX call.
- **Accessibility.** `aria-live="polite"` plus `aria-atomic="true"`, but no `role="status"`, because `mixed-release-collaboration.spec.ts` pins exactly one status role.

## Deviations from the plan

- **Plan review** found 0 blockers, 3 major, 7 minor and 6 nits; all but one were folded in.
  - Rejected: the alternative copy for chat-only turns (see Decisions).
  - Notable changes:
    - the tracker is scoped with a token reset instead of a bare set, because it leaked into later tests;
    - the api.ts union edit moved into Task 2, so the cross-language enum pin stays green;
    - added the PostgreSQL `lock_timeout`;
    - added a deck-level "a broken tracker never fails a deck" test.
- **Tests added by per-task reviewers** after their own sabotage stayed green. All are test-only, with no production change:
  - every `report_*` wrapper swallows a raising tracker;
  - a phase is set *during* its node's model call, not after it;
  - a new turn's seq 1 is forwarded after a higher previous seq;
  - a pending poll still forwards;
  - the next turn starts fresh after a failed turn, or after a session switch;
  - a TS text pin on `StreamEvent.turn_progress`.
- **Whole-branch review.**
  - Doc corrections: a covered-but-undispatched slide is in no list; the ask_data → discuss case; the poll interval is 3 s, not 2 s.
  - New `turnProgress.conformance.test.ts` case: it reads the snapshot keys out of `_snapshot_locked` and feeds them to the real `parseTurnProgress`. Before this, a coordinated backend key rename would have broken the UI silently.
- **Playwright spec.** Test 2 gates the stream on a promise. The plan's version passed with no implementation at all, because count 0 is also true when the test id is missing.

## Test evidence, including sabotage

- **Baseline on 679d2f21:**
  - `tests/unit`: 9166 passed, 0 failed.
  - vitest: 21 environment failures in 4 files (Node 26 `localStorage`, plus one load timeout).
  - Lint: 72 pre-existing problems.
- **Final state:**
  - `tests/unit`: 9223 passed, 136 skipped, 0 failed.
  - vitest: only the baseline environment failures.
  - Integration graph/polling set: 75 passed.
  - `npm run typecheck`: clean. `npm run build`: clean.
  - No new eslint problems in touched files.
  - Playwright `turn-progress`: 3 passed locally, run through installed Chrome (see Gaps).
- **Sabotage.** Every test was proven by breaking the production line it guards. The test authors ran theirs in /tmp copies, and the reviewers ran different ones on the real tree. Representative runs (production change → test that went red):

| Sabotage | Red test |
|---|---|
| emit moved outside the tracker lock | `test_queue_order_is_seq_order_even_when_an_emit_is_slow` (`[2,1]`) |
| `_persist` moved inside the lock | `test_a_slow_persist_does_not_block_another_slides_report` |
| `progress_seq < seq` predicate dropped | `test_an_older_snapshot_never_overwrites_a_newer_one`; PG `test_an_older_writer_queued_behind_a_newer_one_loses` (CI) |
| `<` → `<=` in the predicate | `test_an_older_snapshot_never_overwrites_a_newer_one` |
| `get_chat_request` serving from a module-level dict | `test_a_poll_on_another_worker_process_sees_the_running_turns_stage` (a real second OS process) |
| route serving from an in-process cache | `test_poll_turn_progress.py` (3 tests) |
| poll serves progress when completed/error | `test_a_finished_request_never_serves_a_stale_snapshot[*]` |
| FIXING moved inside `with _fix_slots()` | `test_a_slide_waiting_for_a_fix_slot_already_reads_fixing` |
| scope removed / bare set without reset | `test_the_tracker_does_not_outlive_the_turn` |
| `request_id=None` at the chat_service → invoke_graph seam | `test_turn_progress_polling.py` (4 tests) |
| PHASE_RANK reviewing_deck 2 → 1 | `test_the_phase_rank_never_decreases` |
| placeholder slides reported FIXING not DONE | `test_placeheld_stalled_positions_are_done_in_one_snapshot` |
| send-time reset removed / reset on complete instead | `the next turn starts fresh…` (3 ChatPanel tests) |
| `case 'turn_progress'` removed | 8 ChatPanel tests; Playwright test 1 |
| `lastProgressSeq` at module scope | `a new turn's seq 1 is forwarded after the previous turn reached a higher seq` |
| `"total"` → `"count"` in `_snapshot_locked` | `turnProgress.conformance.test.ts` (cross-boundary) |
| `'turn_progress'` dropped from the api.ts union | `test_every_backend_event_type_is_in_the_typescript_union` |
| migration adds only one column / TEXT seq / unqualified ALTER | ALTER-path tests (the unqualified one stayed green, see Gaps) |

## Sessions and process

- An API budget outage killed the run partway through (2026-10-19 evening). On resume:
  - the uncommitted work was salvaged and checked (no sabotage markers, diffs matched the implementer reports, tests green);
  - the Task 8 review and the Task 5 proofs were re-dispatched from that state.
- Rework by tier:
  - 0 implementer stops or rewrites on any tier (opus 1, sonnet 6, haiku 2).
  - Every `localised` reviewer verdict was a test gap, never an implementation defect.

## CI history

The CI section is updated after the PR runs; see the PR for the final state.

## Known gaps and follow-ups

- **Crashed turns keep their last stage.**
  - A turn whose worker dies keeps serving its last stage. This is the pre-existing stuck-request hang, but it now names work that is not happening.
  - `recover_stuck_requests` only runs at boot, and only for rows older than 10 minutes.
  - Recommend a follow-up tied to stuck-request recovery.
- **Pre-existing SSE problem (dev only).** A placeheld slide's mid-turn `ERROR` event (`_placehold_failed_position`) ends loading early. Polling is unaffected. Recommend a follow-up.
- **No resume after reload.** A page reload mid-turn shows no placeholder at all; no resume-polling exists today.
- **Slide numbering conflict (#321).** These persisted notices number slides from 0, while the new placeholder numbers from 1:
  - `_transient_failure_notice`;
  - `_placehold_failed_position`'s persisted notice;
  - the deck-level "Rebuilding …".

  They are left to #321.
- **Untested migration schema path.** No migration test passes a non-None schema, so dropping `_qual` goes undetected. This gap applies to every migration helper, not just this one; production also sets `search_path`.
- **Playwright cannot exercise polling.** The localhost harness has `isPollingMode()` false. Polling is covered by vitest driving `startPolling`, plus backend integration tests.
- **Local Playwright browser.**
  - The shared browser cache lacks `chromium_headless_shell-1200`, which `@playwright/test` 1.57 needs.
  - Local runs used installed Chrome through a temporary config.
  - CI installs its own browsers.

## Could not verify locally

- **PostgreSQL tests.** The four `TestTurnProgressWritersNeverRegress` tests in `layer4-integration` and `TestPostgresAlterPath` in the unit job self-skip without PostgreSQL.
  - They were reviewed line by line.
  - CI must show them passed, not skipped.
- **Lakebase.**
  - The ALTER needs table ownership. This is the same requirement as the existing `export_jobs.status_message` ALTER.
  - Owner check after merge: deploy a dev build to **devloop**, confirm `Migration: adding progress_json to chat_requests` logs once and nothing logs on the next boot, and watch the placeholder step through a 10+ slide build, an edit, and a chat-only question.
