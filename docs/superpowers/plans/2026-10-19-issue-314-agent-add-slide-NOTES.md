# Issue #314 — add a slide on the agent path: notes for the reviewer

Branch `feat/314-agent-add-slide`, stacked on `feat/313-architect-intent-evals` (PR #335) at c971e372.
This branch's own changes are `git diff c971e372..HEAD`. Plan:
`docs/superpowers/plans/2026-10-19-issue-314-agent-add-slide.md`. It was revised after an independent
plan review (0 blockers, 6 major, 11 minor, 9 nits; all accepted except two parked nits) and a
corrections pre-pass (25 corrections, all accepted). Built by sub-agents (test author, then
implementer, then reviewer for each task), supervised and committed task by task.

## Headline

- **A user can now ask the graph path to add a slide** ("add a slide on X after slide 3", "add a
  final slide", "insert a new slide 2", "add two slides …"). The architect returns the revised
  `deck_spec` with the new `SlideSpec` where the user asked; the node shifts the later slides and
  builds only the new slide (plus any slide the user also asked to change).
- **No frozen schema moved.** The architect expresses an insertion through the full revised
  `deck_spec` it already returns on every edit. `ArchitectOutput`, `DeckSpec` and `SlideSpec` are
  unchanged, so no schema digest, TS type or conformance literal changed.
- **Existing slides keep everything across the shift**: `slide_id`, authorship, timestamps,
  verification record, spec fragment and findings. The rows move through one shared whole-deck
  writer with an exact old-row → new-position map, in one transaction with the spec write.
- **Measured.** The shipped prompt answered every add with `discuss` (train 0/8, held-out 0/4). The
  promoted prompt passes every add case (train 12/12, held-out 4/4) with no regression on the nine
  existing cases (train 9/9, held-out 9/9). Spend about USD 12.51 of the USD 15 cap.

## What was implemented, by acceptance criterion

**A1: an "add a slide" request produces an updated `deck_spec` with the new `SlideSpec` at the
requested position (or appended), later positions shifted, and only the new slide built.**

- *How the architect expresses it (D1).* An edit whose revised spec has more slides than the
  persisted one is an insertion. `src/domain/slide_alignment.py` (new, pure) aligns the current
  slides to the returned ones in order, cheapest match first (same purpose and brief beats same
  everything else). Unmatched returned slides are inserted; matched slides that differ are revised.
  - A tie for the cheapest alignment is refused (`edit_insert_ambiguous`), never guessed. So is a
    spec that moves an existing slide (`edit_spec_moves_slides`), a shrinking spec and an
    equal-length renumbering (`edit_spec_positions_changed`).
  - "Add after slide 3 and update the agenda slide" works when the agenda is not next to the new
    slide. "Add after slide 3 and rewrite slide 3" is refused as ambiguous; the message asks for the
    add first, then the change.
- *Where (D4).* `architect_node` re-numbers the spec 0..n, then `SlideWriter.insert_pending_slides`
  shifts the committed rows in ONE transaction before any review or build:
  - it re-reads the rows and refuses (`insert_rows_changed`) if they are not the rows the architect
    planned against, including a failed top-of-node read;
  - it writes every row through `_rewrite_slide_rows`, now the only whole-deck row rewrite
    (`save_slide_deck` and `restore_version` call it too, replacing two hand-copied blocks), with the
    exact old-row attribution;
  - it opens a "New slide — not built yet." placeholder at each new position, writes the spec,
    bumps `deck.version` and records one `insert_slide` mutation event.
- *Only the new slide is built (D3).* On an insert turn the targets are the alignment's
  `inserted ∪ revised` in the new numbering. The model's own `target_positions` are logged
  (`insert_targets_disagree`) and ignored. A shifted, unchanged slide is never a target. A deck-level
  change re-reviews after the shift, so each slide is judged against its own spec entry; a design
  contract change still rebuilds everything (after the shift).
- *The prompt.* The promoted architect prompt (`add-slide-b`, b5a4cba61121, was ffc3074dc920) makes
  adding slides an edit, says where the new slide goes (and, with no stated place, before a closing
  slide), says later slides are copied unchanged except their position, says a slide named as the
  anchor is not a target, and says an unlabelled template section cannot be bound.
- *Tests.* `tests/unit/test_slide_alignment.py` (54), `test_architect_insert_slide.py` (34, the node),
  `test_graph_insert_slide_turn.py` (7, compiled graph), `test_architect_edit_prompt.py` (16 new
  prompt pins), the eval cases below.

**A2: slide identity, attribution and verification records of the existing slides survive the
shift.**

- The shift carries every column of every existing row by an exact map, built from the ORM rows
  before the first write. NULL authorship and timestamps stay NULL; `modified_at` is preserved.
- Two read/write paths that keyed on a stale position are fixed, because a shift would otherwise
  show them on the wrong slide (they also fix the UI's insert, reorder and delete):
  - a finding's `slideIndex` now comes from the row whose content minted it (D7);
  - `write_slide_verification` writes a verdict to the row whose HTML it verified when the slide has
    moved since the judge read it (D8).
- A placeholder is now judged by the slide's CURRENT verdict, strictly (D9). Without this the new
  slide could not get its draft preview, and a real slide carrying an LLM-judge error verdict, or one
  rebuilt from a placeholder, was treated as a placeholder.
- *Tests.* `test_insert_pending_slides.py` (by-marker whole-row equality, NULL authorship, gapped rows,
  every precondition; plus a CI-only Postgres file), `test_findings_follow_their_slide.py`,
  `test_pending_slide_is_fillable.py`, and the compiled-graph test, which snapshots every row after a
  build turn and asserts after the insert turn that each one is unchanged as a whole dict, that each
  finding points at the slide whose hash minted it and that a judge verdict stayed on its slide.

**A3: covered by an architect eval case and a graph test.**

- Four insert cases per split, the same ids in train and held-out (held-out words them differently
  on its own deck): `add_slide_anchor`, `add_slide_end`, `add_slide_as_number`,
  `add_slide_and_revise`. Generated by the pack generators with production payloads; pack tests pin
  that production's alignment reads each reference as exactly the expected insert.
- The deterministic scorer scores an insert the way production builds it (D10, landed before any
  measurement): `align_slides(current, output)` must give exactly the expected inserted and revised
  slides, and the deck-level fields must be unchanged. A model target mismatch is noted, not failed.
- The graph test is `tests/unit/test_graph_insert_slide_turn.py`.

**Transports and the frontend (D5).** No frontend code changed. Both transports refetch the deck at
`complete`, which corrects the client: pinned by a mocked SSE Playwright spec
(`frontend/tests/e2e/agent-insert-slide.spec.ts`, in the CI matrix) and a TestClient polling-route test
over real persistence (`tests/unit/test_poll_route_across_an_insert.py`). The panel numbers by
`index + 1` and SpecView by `position + 1`; after a shift both are contiguous, so they agree.

## Measurements

Agent `system.ai.claude-opus-5`, judge `databricks-claude-sonnet-5`. Cost is estimated from tokens at
USD 5 / 25 per million in / out plus about USD 0.035 per judge call (`prices.yaml` has no opus-5
entry). Run ids refer to the issue-314 worktree's local `mlflow.db`. Held-out is aggregates only.

| Run | Config | Split | Cases | Repeats | Rows | Pass | Intent | Positions | Judge err | ≈ USD |
|---|---|---|---|---|---|---|---|---|---|---|
| B1 8e5f7755 | shipped (ffc3074d) | train | 4 insert | 2 | 8 | 0.00 | 0/8 | – | 0 | 0.89 |
| B2 82ed0000 | shipped | train | 9 existing | 1 | 9 | 1.00 | 9/9 | 4/4 | 0 | 1.57 |
| B3 4a3dd928 | shipped | held-out | 4 insert | 1 | 4 | 0.00 | 0/4 | – | 0 | 0.41 |
| S1 c26f6789 | add-slide (e5caefa8) | train | 4 insert | 1 | 4 | 1.00 | 4/4 | 4/4 | 0 | 0.93 |
| S2 9b7cd603 | add-slide-b (b5a4cba6) | train | 4 insert + build_request, edit_request | 1 | 6 | 1.00 | 6/6 | 5/5 | 0 | 1.34 |
| F1 146133de | add-slide-b | train | 4 insert | 3 | 12 | 1.00 | 12/12 | 12/12 | 0 | 2.67 |
| F2 9a15c202 | add-slide-b | train | 9 existing | 1 | 9 | 1.00 | 9/9 | 4/4 | 0 | 1.53 |
| F3 f54dd66b | add-slide-b | held-out | all 13 | 1 | 13 | 1.00 (9 scored) | 13/13 | – | 4 | 1.95 |
| F3b ffaa27ab | add-slide-b | held-out | F3's 4 judge-error rows | 1 | 4 | 1.00 | 4/4 | – | 0 | 0.59 |

- Calibration: all 8 new cases trusted (one held-out reference re-judged after a judge
  `KeyError: 'result'`). With calibration, total spend is about USD 12.51.
- **Accept rule, fixed before the F runs, met:** F1 ≥ 0.75 with every insert case ≥ 2/3 and above B1
  (1.00, 3/3 each, B1 0.00); F2 ≥ 8/9 and ≥ B2 − 1 with no contract failure (9/9); held-out inserts
  ≥ 3/4 and above B3 (4/4 vs 0/4) and existing ≥ 8/9 (9/9).
- **Binding diagnostic (not the yardstick).** The fixture's template sections all have a null label.
  Candidate `add-slide` passed S1 4/4, but production's own binding validation
  (`complete_index_only_bindings` + `invalid_slide_bindings`, which `architect_node` runs) would have
  refused 3 of the 4 turns: the new slide came back bound to a section index with no slide type. The
  shipped prompt has the same problem on build and edit (B2: 2 of 5 spec rows). `add-slide-b` adds the
  rule that an unlabelled section cannot be bound: 0 refusals on S2, F1, F2 and F3. The yardstick was
  not changed after the BEFORE runs; the diagnostic was a supplementary accept condition fixed before
  the F runs.

## Decisions made on your behalf

1. **No schema change (D1).** Inserts are derived from the revised `deck_spec` by alignment. A new
   output field or intent would have moved the frozen schema digest in six test files, the manifest
   and the retained-bundle ledger. The cost is that an add next to a rewritten slide is refused as
   ambiguous (the message asks for two steps).
2. **Rows shift at architect commit, before any build (D4)**, with pending placeholder rows rather
   than a gap, so rows and spec stay aligned on every path, including a turn that dies.
3. **The model's `target_positions` are ignored on an insert turn (D3).** A model that counts in the
   old numbering would otherwise rebuild, and destroy any hand edit on, a shifted, unchanged slide.
4. **No deterministic insertion anchor (D6).** `slide_numbering.py` is unchanged; the prompt carries
   placement. Measured at 12/12 positions on train and 4/4 on held-out.
5. **Product rule for an add with no stated place:** the new slide goes where it fits the argument,
   before a closing or call-to-action slide unless it is itself a closing slide; the message says
   where. "At the end" / "a final slide" means after the last slide.
6. **Findings, verification and placeholder fixes (D7–D9) are in scope**: each would otherwise
   mis-attribute or mis-judge a shifted or inserted slide. They also fix the UI's insert, reorder and
   delete.
7. **The eval yardstick scores production semantics (D10)**, changed before any measurement.
8. **Held-out discipline:** the plan author read the held-out cases, so the plan's own candidate prompt
   text (which named exactly the held-out phrasings) was withdrawn. The prompt candidates were
   written by an agent barred from held-out cases, results, all plan files and the ledger, from the
   issue text, the train failures and a property list with no phrasings.
9. **The binding fix ships with the add-slide prompt.** It was found on train with production's own
   validator and is generic (it fixes builds on unlabelled templates too).
10. **Equal-length edits that turn one slide into an exact copy of another are now refused**
    (`edit_spec_moves_slides`): the alignment cannot tell that from a move.
11. **The frontend lifecycle contract fixture is not re-recorded** (needs PostgreSQL; #313 precedent;
    its CI check compares key shape).
12. **Measurement overrides of the optimise-agent-prompt skill**, for budget: the finalist was
    confirmed at ×3 on the insert cases and ×1 on the nine existing train cases (not ×5 on all), and
    held-out ran at ×1 (not ×3).
13. **Cross-split total is 43 cases**, not the plan's 47 (an arithmetic slip: 6 × 5 + 13).

## Deviations from the plan

- Task 1: two extra refusal rows from the reviewer (the identity tier ranks before the full diff; a
  tie is refused before the move check). C1 widened the move rule to catch reorder-plus-insert.
- Task 2: three extra argument checks raise `ValueError` before any DB access; a row-less (spec-only)
  deck records one `insert_slide` event; `deck.modified_by` is not stamped by the shift.
- Task 3: `write_slide_verification` with an out-of-range position now writes to the unique row whose
  HTML matches (reviewed: safe; it rescues verdicts after a delete).
- Task 8: `--calibrate --cases` exits non-zero for any unknown id, not only when nothing matches.
- Task 11: two candidates instead of one (see Measurements).
- Task 15: the optional user-guide paragraph was skipped (the guide already has an "Add a slide" row,
  and sibling PRs edit that file).

## Whole-branch review

A fresh Opus reviewer applied the `tellr-code-review` checklist, built a writer-by-writer table of
every `session_slides` and `deck_spec_json` writer and every reader that maps findings, verdicts or
positions to slides, ruled on the rollback guarantee path by path, re-ran four of the ledger's
sabotages (same red counts) and four of its own on cross-task seams.

- **Verdict: merge once CI is green. 0 blockers, 0 major, 6 minor, 6 nits.**
- **One row writer.** `save_slide_deck`, `restore_version` and `insert_pending_slides` all go through
  `_rewrite_slide_rows`; no two writers carry identity, authorship, verdicts, fragments or findings
  differently across a shift.
- **Rollback holds on every path:** each refusal, a failed precondition, a shift exception,
  `PersistedRuntimeError`, a failed pre-fan-out write, a failed build, a turn that dies after the
  shift, a UI mutation during the turn, and two workers.
- **Only the new slide is built**, apart from the by-design cases (a design-contract change, a
  deck-level re-review, a `build` answer), including the `ask_data` re-entry and describe-only turns.
- **Eval integrity:** the yardstick commit precedes every measurement (B runs at ca7f9508, S2 and F
  at 3dd49ed9); the promoted prompt is byte-identical to the measured finalist; only the architect
  `prompt_text` moved in the manifest; schema digests unchanged.
- **Minor findings,** all accepted or follow-ups (see Known gaps): the error path does not refetch;
  the lock-free arc-review sweeper can overwrite a shifted spec with an older one (pre-existing race,
  new shape); held-out process gaps (m3, below); `write_slide` overwrites `created_by` (pre-existing);
  the equal-length copy refusal (intended); a verdict landing within milliseconds of a shift can be
  lost (same class as the UI reorder).
- **Held-out process (m3).** The candidate brief's product rule ("when the user explicitly asks for
  the end of the deck") was worded by agents who had read the held-out cases, and one prompt-pin regex
  alternation contains "at the end". The candidate prompts and the promoted prompt contain no
  held-out phrasing. Effect: held-out `add_slide_end` is the weakest generalisation datum; the accept
  rule still holds on the other three held-out insert cases. Also, the `optimise-agent-prompt` skill
  forbids only `cases_heldout/` and the held-out experiment, while plans (with held-out appendices)
  are committed under `docs/superpowers/plans/`; widening the skill is a follow-up (skills are not
  edited by this branch).
- **Sibling overlap:** textual conflicts are trivial (adjacent imports in `nodes.py`, the `test.yml`
  matrix). #332's 1-based notices and #334's `plainMessage` read the corrected slide index and are
  compatible; #334's verbatim reviewer-message tail may still quote a pre-shift "slide N".
- **Nit:** the promotion commit lands before the node commit in this branch's history; harmless at
  HEAD.

## Test evidence (sabotage: production line broken → named test red → restored green)

- **Alignment.** No tie count → 4 ambiguous rows red. Brief-only cost → 2 rows. No moved check → 5
  rows. C1 clause (b) off → the 3 reorder-plus-insert rows. `revised` as indices → 3 gapped rows.
  Map by list index → 5 rows. Cost tuple swapped → 1. Key includes position → 18. No shrink check → 2.
  Supervisor: the returned slides not sorted → 2.
- **The shift.** About 20 pre-validated by the test author (lazy row dicts, attribution `None`,
  fabricated authorship/timestamps, no spec write, no version bump, each precondition). Reviewer:
  attribution keyed by old position → 6; save with `attribution={}` → 4; restore verdicts off by one →
  1 (new test; only an integration test caught it before); pending verdict on the next row → 7.
  Supervisor: precondition ignores `slide_id` → 1.
- **Findings / verification.** Override removed → 4; content lookup removed → 2; camel key wrong → 7;
  `list_index + 1` → 8; lookup only when the position row exists → 1 (new test, a UI delete).
- **Placeholder predicate.** Plain `is_placeholder_record` → 4; whole-record → 8; `is not None` → (a),
  (b) red; first key instead of the content hash → 5; placeholder branch dropped → 4; `score` accepted
  → 4; always draft → 8.
- **Node.** Targets by position → 13; shift after the deck-level re-review → 1; no re-stamp → 4;
  model targets honoured → 5; describe-only shifts → 2; indices on the equal-length path → 2;
  `PersistedRuntimeError` swallowed → 1; shift skipped on a contract change → 1 (new test); spec put in
  updates before the shift → 3; alignment before the bindings → 1 (new test).
- **Compiled graph.** `NO_ATTRIBUTION` for moved rows → 6; only html/scripts/slide_id carried → 6;
  targets by position → 5; no slideIndex override → 1; no spec write in the shift → the next turn is
  refused `spec_positions_stale`; re-stamp by list index → the gapped test. Supervisor: a landed slide
  gets a fresh `slide_id` → 3.
- **Polling route.** The shift stamps `modified_at` → the pinned mid-turn view red; cursor rewinds →
  red; no spec write → the completed-result test red.
- **Yardstick.** Targets instead of revised → (a), (b) red; no deck-level check → (c); filter ignored →
  call count; reference aligned instead of the output → 7; refusal counted as a pass → 3.
- **Cases.** A brief constant changed without regenerating → 3; a held-out reference revising an extra
  slide → 3; `inserted` swapped → 5; a should_fail equal to its reference → 3; new-slide binding set →
  16.
- **Prompt.** The null-label sentence deleted → its binding rule and both skill/manifest equality
  tests red. The test author's deletion matrix maps each new sentence to its own rule.
- **Playwright (SSE).** ChatPanel's `complete` refetch removed → "Expected: 4 Received: 3".
  Supervisor: SpecView labelling `position` instead of `position + 1` → the "Slide 2" assertion red.
- **Unit suite.** Baseline c971e372: 9687 passed, 0 failed. Final (8acf4c32): 10071 passed, 0 failed.
  Frontend: no source change; the vitest baseline's 20 local failures are Node 26's missing
  `localStorage` (CI runs Node 20).

## Known gaps and follow-ups

- **The yardstick should run production's binding validation**, and the eval template fixture is
  unlabelled. The binding check was a hand-run diagnostic here.
- **An add next to a rewritten slide is refused as ambiguous**; no eval case measures how often users
  hit it. A duplicate-like insert gets the same refusal, whose wording then misleads (parked).
- **No eval case for the no-place product rule**; only the layer-3 RC2 test (not run in CI) does.
- **Mid-turn client view** (D5): on SSE the new slide's `slide_ready` replaces the old slide at that
  index; on polling the moved rows keep `modified_at`, so the old last slide arrives twice and the
  moved ones are not re-sent. `complete` corrects both; a turn that errors does not refetch.
- **A `build` answer to an add** rebuilds every slide in place; `build_looks_like_insert` only logs it.
- **An insert turn bumps `deck.version` twice** (shift, then the pre-fan-out write).
- **Rollout:** the Graph V1 manifest seeds a fresh bootstrap only. An existing install gets the node
  behaviour at once but keeps answering an add with `discuss` until an admin publishes a release with
  the new prompt.
- **Pre-existing, found here:** `SlideWriter.write_slide`'s partial update overwrites `created_by`,
  although its comment says an update leaves it alone.
- **Whitespace-only neighbour diffs** rebuild those neighbours (accepted).
- **The arc-review sweeper is lock-free** and can overwrite a shifted spec with an older, shorter one
  (pre-existing race for every edit turn).
- **A verdict written within milliseconds of a shift** can land on the pre-shift row (no row lock; same
  class as the UI reorder).
- **`_placehold_failed_position`** could use the strict predicate for consistency.
- **Widen `optimise-agent-prompt`'s forbidden reads** to the list this branch used (plans, every
  held-out module and fixture, the ledger).
- **Not verified locally:** the Postgres suites (including the new `test_insert_pending_slides_postgres.py`)
  and the integration suites run only in CI; local Playwright ran against system Chrome because the
  pinned Chromium build is not installed here.

## CI history

- Round 1: pending (this commit is pushed with the PR).
