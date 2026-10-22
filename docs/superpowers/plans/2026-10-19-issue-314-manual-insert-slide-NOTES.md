# Issue #314 follow-up — insert a blank slide by hand, and a "New" indicator: notes for the reviewer

Branch `feat/314-agent-add-slide` (PR #337). The user reviewed #337 on its devloop instance and asked:
"we need a UI indicator too. I want to be able to manually insert a blank slide in the same way that I
can in Google [Slides]. This needs to play into the Deck spec as well."

This follow-up's own changes are `git diff c84d3921..HEAD` (c84d3921 = #337 after the merge-train
merges). Plan: `docs/superpowers/plans/2026-10-19-issue-314-manual-insert-slide.md`, revised after an
independent review (1 blocker, 2 major, 13 minor, 6 nits) and a corrections pre-pass (21 corrections
plus supervisor rulings). Built task by task: an Opus test author, then an implementer, then a
reviewer that sabotage-verified the tests, then a supervisor sabotage on a different target.

## Headline

- **Google-Slides-style insert.** Editors get a **New slide** button in the stage toolbar (inserts after
  the current slide) and a **+** between ribbon thumbnails (before any slide, or at the end).
- **The blank looks like this deck.** It is a copy of the deck's own slide frame with no content (the
  most common wrapper chain, keeping only `class`, `data-label` and `style`), so it paints the
  design system's ground. The bare `<div class="slide"></div>` is only the fallback.
- **It plays into the Deck spec.** The insert writes a blank `SlideSpec` at that position and shifts
  the later entries and rows in ONE transaction, through #337's shared row writer with an exact
  old-row map. Every existing slide keeps its identity, authorship, verdicts, fragments and findings.
  The Spec view shows "Blank slide"; the Markdown export prints "Blank slide.".
- **The architect respects blanks.** "Fill slide 4 with pricing" edits the blank in place. No turn
  rebuilds, re-reviews, drops or invents a description for an untouched blank.
- **"New" indicator.** Whenever slides appear (a manual insert, the agent adding one over SSE or
  polling, a duplicate), the new slide is selected, scrolled into view and marked **New** for 5 s.
- **No schema, prompt or digest change.** Measured on the shipped architect prompt: 6/6 train, 2/2
  held-out on two new blank-slide cases. Eval spend about USD 2.0 of the USD 10 cap.

## What was implemented

**1. The insert affordance (Task 6).** `stage-insert-slide` in the toolbar and `ribbon-insert-k` gaps
(k = 0..n) in `ThumbnailRibbon`. Both call `api.insertSlide(position, sessionId)` (POST `/api/slides`,
no HTML), refetch the deck and select the inserted slide by its `inserted_slide_id`. Hidden for
read-only viewers, save-point previews and non-lock-holders; disabled while a turn runs or an insert is
in flight. A 409/423 toast shows the server's sentence and refetches. During a drag the gaps stay laid
out but hidden, so dnd-kit's measured rects do not move. `ViewerContext`'s shrink clamp now clamps from
the current index (a real defect the reviewer found: a stale index overwrote the selection when a
refetch shrank and grew the deck at once).

**2. The blank shell (Task 1).** `src/domain/deck_spec_slides.py::blank_slide_shell(slide_htmls,
position)`: for each slide, its root-to-`.slide` element chain with only `class`, `data-label` and
`style`, no children and no text. The most common candidate wins; a tie goes to the nearest slide,
never the cover (slide 1) when another slide ties. The winner must be a blank row and pass
`scan_html_for_unsafe_patterns`, else the bare div. On a section-wrapper design system it keeps the
`<section>` that paints the ground; on an unpinned deck it keeps the inline ground. Blank detection is
structural (`is_blank_slide_html`, mirrored in `frontend/src/services/blankSlide.ts`); both languages
are held to one case table, `tests/fixtures/blank_slide_cases.json`.

**3. One transaction, the shared writer (Tasks 2, 3).** `SessionManager.insert_slide`:
- locks the deck OWNER's row first (`_refuse_during_an_arc_review`), then refuses while a turn runs on
  any other session of the deck (`DeckBusyError`, lock younger than `SESSION_LOCK_TIMEOUT_SECONDS`);
- re-reads the rows and refuses unless they are the rows the caller planned against
  (`SlideRowsChangedError`); a row-less deck (legacy, or a duplicate) is first materialised by the
  startup backfill's non-committing core (`_backfill_deck`) and compared by content hash in order;
- shifts through `_splice_slide_rows`, now shared with the graph's `insert_pending_slides`, into
  `_rewrite_slide_rows` (the one whole-deck row writer) with an exact map;
- splices the blank spec entry, bumps the version once, writes one `insert_slide` mutation event and
  one `slide_inserted` usage event.

`ChatService.insert_slide` builds the new deck on a copy (the cached deck is never mutated), passes the
raw username, invalidates the cache on every exit, then reloads and writes one save point. The route
answers 409 `CONVERSATION_BUSY_DETAIL` for a held lock, a running turn or an arc review, and 409 "The
deck changed while the slide was being added. Refresh and try again." when the rows moved. It marks
the spec dirty only for an insert that carries HTML: a blank's spliced entry is already its exact
description, so no arc review is scheduled (and no 409 window follows).

**4. The architect (Task 4).** In `src/services/graph/nodes.py`:
- **N1:** on an edit turn an untouched blank entry is dropped from the build targets, the
  design-contract rebuild-all and the deck-level rebuild set. If the user named it and the model left
  it empty, one plain notice says "Slide N is still blank, so I left it as it is. Tell me what to put
  on it."
- The deck-level re-review makes no judge call for a blank entry; `judged_nothing` ignores blanks.
- **N2:** an arc-review (describe-only) turn on a deck whose spec describes its rows may not change
  the position set, and keeps the persisted entry for a slide whose row and entry are both still
  blank (the architect sees no HTML, so a description would be invented).

**5. The indicator (Task 8).** `diffNewSlides` compares slide_ids with the last server deck: synthetic
`build-N` ids mean a mid-turn view; a first load or a deck switch flags nothing; only pure growth is
flagged. The inserted slide wins the selection, else the first new one. "New" chip, ring and an
sr-only status line for 5 s. SSE and polling behave the same because both end with a refetch. An
errored turn now refetches the deck too (`onDeckRefetched`, deck only: no survey, no "Saved just now"),
on both the SSE `error` event and polling's `onError`. A per-slide error notice mid-turn does not
refetch.

**6. Spec view, export, auto-verify (Task 7).** "Blank slide" label, "Blank slide." export line
(the #330 parity guard gained a BLANK fixture; golden bytes unchanged), and auto-verification skips a
blank (no judge call on an empty frame) until it is filled.

**7. Tests.** Unit: `test_deck_spec_slides.py`, `test_manual_insert_writer.py` (+ a CI-only Postgres
file), `test_manual_insert_service.py`, `test_manual_insert_route.py`, `test_architect_blank_slides.py`,
`test_graph_blank_slide_turn.py` (compiled graph: fill in place, deck-level turn, arc-review turn, edit
of another slide). Vitest: `SlideInsert`, `insertSlide`, `NewSlideIndicator`, `newSlides`,
`ChatPanel.errorRefetch`, `blankSlide`, `useAutoVerification`, SpecView and Markdown additions. Mocked
Playwright: `manual-insert-slide.spec.ts` (in the CI matrix) and a "New" block in
`agent-insert-slide.spec.ts`. Evals: `fill_blank_slide` and `edit_beside_blank`, train and held-out.

## Decisions made on your behalf

1. **The blank is the deck's own frame, not a template section** (sections carry sample content, and
   there is no "blank" section kind). Ties never copy the cover. Residuals: after a design-system
   switch an untouched blank keeps the old frame until filled; a deck whose every slide has a
   distinct inline style copies its nearest non-cover slide.
2. **No schema marker.** "Blank" = an entry with no purpose and no brief; "blank row" = the structural
   predicate. No `DeckSpec`/`SlideSpec`, TS type, prompt or digest change.
3. **One transaction with an exact map** rather than `save_slide_deck`, whose UI round trip wrote SCIM
   display names into every row's authorship and turned NULL timestamps into "now".
4. **Refused while anything runs on the deck**: this session's lock, any other session's turn (owner
   or contributor; 300 s no-heartbeat limit), or a live arc-review claim. Editors only (CAN_EDIT 403,
   editing lock 423).
5. **Legacy and duplicated decks**: no spec -> the insert still works and the spec is left alone; no
   rows (a legacy deck, or a duplicate, which `duplicate_session` creates without rows) -> rows are
   materialised by the backfill core first, in the insert's transaction, and checked against the
   caller's deck by content hash in order (their ids cannot match a blob slide that has none).
6. **No arc review after a blank insert** (an HTML insert still schedules one).
7. **N2(a) applies to every deck**: on a deck whose spec matches its rows, an arc review may not add
   or drop slides. Three sweeper integration tests used deck growth as a device; they now re-describe
   a slide instead, with the same assertions.
8. **A placeholder at an untouched blank entry is not rebuilt by a deck-level turn** (it would be built
   from an empty brief).
9. **The indicator also runs for read-only viewers**, and for duplicates.
10. **No prompt change**: measured first (below).
11. **Eval amendment, made before any agent run**: the judge cannot tell "fill the blank" from "insert
    a slide beside it" (calibration failed twice per split), so `fill_blank_slide` is scored by its
    deterministic checks (edit, revises exactly the blank, inserts nothing); the judge verdict is
    reported, not counted.

## Measurements (shipped architect prompt `add-slide-b` b5a4cba6, judge `databricks-claude-sonnet-5`)

| Run | Split | Cases | Rows | Pass | Detail | ≈ USD |
|---|---|---|---|---|---|---|
| calibration | train, held-out | both | judge only | — | `edit_beside_blank` trusted; `fill_blank_slide` judge-untrusted (both splits) | 0.35 |
| B-T1 630beeaf | train | both, ×3 | 6 | 6/6 | fill: edit, revised [5], inserted [] ×3; beside: revised [6] only ×3; binding refusals 0/6 | 1.32 |
| B-H1 6b2e4ab4 | held-out | both, ×1 | 2 | 2/2 | aggregate: both edit, no insert; binding refusals 0/2 | 0.32 |

Accept rule fixed before the runs (train ≥ 5/6, held-out 2/2): met, so no prompt change.

## Test evidence (sabotage: product line broken -> named test red -> restored green)

Each reviewer ran its own set on the real code, and the supervisor one more on a different target.
Highlights, including the ones that found gaps:
- **Shell/predicates:** cover exclusion removed -> 4; style dropped -> 31; scanner check removed -> 6;
  `str.strip()` for the ASCII rule -> 18; supervisor: splice without re-stamping positions -> 9. The
  Task 1 reviewer found `is_blank_slide_html` calling a visible `<img>` blank (the wrapper regex
  matched inside a comment) and fixed it; the Task 7 reviewer found the TS predicate missing that
  regex gate.
- **Writer:** attribution=None -> twins red; snapshot after the first upsert -> 41; busy query
  including the requester -> 2; supervisor: no flush after the backfill -> 6. The reviewer added a
  SQL-trace test because moving the deck lock later was invisible on SQLite.
- **Service/route:** back through `save_slide_deck` -> 19; cache invalidation outside the finally ->
  7; supervisor: mark_dirty on every insert -> 1. Two survivors (reindexing the working deck; no
  try around the post-commit reload) now have tests.
- **Architect:** rereview skip removed -> 9; N2 not gated on describe-only -> 33; supervisor: the
  design-contract site keeps blanks -> 4. Two survivors (indices vs positions on a gapped insert; the
  rebuild-site drop alone) now have tests.
- **Frontend:** supervisor: pending selection disabled -> 4; baseline not reset on a deck switch ->
  2; SpecView label suppressed -> 4; the mid-turn error guard removed -> 1. The Task 8 reviewer closed
  four survivors (timer outliving the viewer, chips across a deck switch, ...).
- **Playwright (product sabotaged, never the mock):** ribbon `onInsert` unwired, toolbar off by one,
  indicator disabled, SpecView label removed, `insertDisabled` unwired, gaps shown mid-drag: each
  turned its case red.
- **Graph acceptance:** supervisor: the writer's spec splice skipped -> 6.

## Known gaps and follow-ups

- **The other manual operations** (update, duplicate, delete, reorder) still go through
  `save_slide_deck`: heuristic attribution, display names written back, a second best-effort spec
  transaction, no arc-review check, cache mutated before the write. They do keep the deck spec in sync
  (`_rewrite_deck_spec_slides`). The insert no longer depends on them. Follow-up: move them onto the
  insert's writer.
- **A row-less deck whose blob slides lack a `slide_id` key** used to get a 409 on every insert (the
  cached deck mints `slide_N` ids, the backfill writes NULL). Fixed after the whole-branch review
  (MINOR-2): on the row-less path the freshly materialised rows are compared by content hash, in
  order, only; the rows path keeps the full (slide_id, hash) check. Such decks are not only
  pre-backfill legacy ones: `duplicate_session` copies `deck_json` and no rows, so every duplicate
  is row-less until its first write.
- **Postgres lock order**: the insert locks the deck row first; a writer that flushes slide rows
  first could deadlock with it inside the same milliseconds. Postgres aborts one (a 500); nothing is
  corrupted. Same pattern as clear and delete.
- **A model that fills a blank during an unrelated edit** builds it (by design: the entry is
  revised). Not measured.
- **Notice wording**: if a user hand-typed into a blank but the entry is still blank and the model
  leaves it, the notice says "still blank".
- **The `fill_blank_slide` judge cannot separate its should_fail**; a judge-visible mutation is a
  follow-up.
- **Polling in e2e**: the indicator's polling shape is covered by vitest only (Playwright runs SSE).
- **A save-point preview opened within one round trip of an insert** drops that insert's refetch (the
  viewer remounts); the deck shows the new slide on the next refetch.
- **Workbench race (unrelated, fixed in tests only)**: `AgentDefinitionWorkbench.test.tsx` "edits
  custom blocks locally" raced its own Save; the test now waits for the save to land. The component
  itself would also let an in-flight save response overwrite a delete made meanwhile (not in scope).

## Whole-branch review

A fresh Opus reviewer applied the `tellr-code-review` checklist to `git diff c84d3921..a08fbfb0`.

- **Verdict: merge once CI is green. 0 blockers, 0 major, 4 minor, 5 nits.**
- **One row writer and one shift primitive.** `_rewrite_slide_rows` is the only whole-deck row
  writer; `_splice_slide_rows` is shared by the graph's `insert_pending_slides` and the manual
  `SessionManager.insert_slide`; no hand-copied upsert.
- **Rollback holds server-side on every path** (each 409 source, an evidence failure, a row-less deck,
  a stale cache, a reload failure after commit, a save-point failure).
- It re-ran four of the ledger's sabotages (three with the same red counts, one a variant) and four of
  its own on cross-task seams; one survived and is now pinned (a refetch that reorders AND adds still
  flags only the new slide).
- **Minor findings, all fixed with a test that was red first and sabotage-verified:**
  - a refetch that failed after a committed insert reported "Failed to insert slide" (a retry would
    have added a second blank): now retried once, then an "Slide added. Refresh to see it." notice,
    and the insert is never re-sent;
  - row-less decks do occur at runtime (`duplicate_session` copies the blob, no rows), and a blob
    without `slide_id` keys was refused forever: the row-less path now compares by content hash;
  - a session switch or unmount while an insert was in flight could hand the old deck up: the edit
    counter is bumped on both;
  - `evals/README.md` now records the calibration result and the BEFORE runs.
- **Nits left:** the TS and Python blank predicates disagree only for odd wrappers (`p`, `table`,
  `template`, `select`, `svg`), always on empty frames; the Postgres lock-order note above; PPTX and
  Google Slides export of a childless shell were not checked by a test (worth a look on devloop).
- **Pre-existing, outside this branch (not filed):** `duplicate_session` copies only `deck_json`, and
  the graph's writers never update it, so a duplicate of a graph-built deck can show stale slides or
  none.

## CI history

- M1 bacf7e92 (merge of main): run 39586872183 green. M2 c84d3921 (merge-train merge): run 39609846137
  green.
- R1 df1ec985: run 39745638308, Frontend Unit Tests failed on the unrelated workbench test; rerun of
  the failed jobs green. R2 4e1119e1: the same test failed again on first attempt -> diagnosed and
  fixed (82fee536).
- (final rounds filled in below)

## Process note

A network outage killed four sub-agents mid-task (2026-10-21 ~16:54). Their work was salvaged per
executing-plans-tellr §5: no sabotage markers left, diffs matched the implementers' reports, the
reviews were re-run from that state, and the half-written Playwright spec was finished rather than
rewritten.
