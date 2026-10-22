# Agent path: add a new slide to an existing deck (#314) — Implementation Plan

**Date:** 2026-10-20 (revised the same day after the plan review)
**Branch:** `feat/314-agent-add-slide`, stacked on `feat/313-architect-intent-evals` (PR #335, head
c971e372). Worktree `.claude/worktrees/issue-314`.
**Issue:** #314 "Agent path: add a new slide to an existing deck" (supersedes the pre-graph #10 for
the LangGraph path).
**Spec:** none written. The Decisions section holds the rulings. They are provisional; the user may
overrule any of them.
**Before Task 1:** load `executing-plans-tellr` alongside `superpowers:subagent-driven-development`
and run its plan-vs-code corrections pre-pass (§2). Every task has a `Models:` tag (§9).

> **HELD-OUT WARNING.** Appendix H contains held-out case content. Never give this file, or any
> excerpt from it, to the prompt-candidate author (Task 11). Task 11's brief is self-contained and is
> passed to that agent verbatim. No held-out phrasing appears anywhere in this file outside
> Appendix H. Commit messages carry no held-out content.

---

## Plan review: findings and rulings

Review: `~/tellr-loop/issues/issue-314/PLAN-REVIEW.md`. Rulings are the supervisor's.

| # | Severity | Ruling | Where it landed |
|---|---|---|---|
| 1 | MAJOR | ACCEPT. `SlideAlignment` reports positions in the returned spec (`inserted`, `revised`) and canonical indices (`inserted_indices`, `revised_indices`). The equal-length path uses positions, exactly as today's `changed`. Gapped equal-length and gapped-insert tests added, plus sabotage. | D1; Task 1; Task 5; Task 6 |
| 2 | MAJOR | ACCEPT. NEW strict predicate `is_placeholder_verdict`: `is_placeholder_record` holds AND the verdict's keys ⊆ {`error`, `message`}. The LLM-judge error verdict (`llm_judge.py:470-490`, written by `verification.py:250-267`) carries `score`/`rating`/`explanation`/…, so it is not a placeholder. Used at both Task 4 sites. | Context; D9; Task 4 |
| 3 | MAJOR | ACCEPT. Every insertion turn calls `insert_pending_slides`, which re-reads rows in its transaction. Rows present but `expected_rows` empty → `SlideRowsChangedError` (→ `insert_rows_changed`). Both empty → spec and version only. | D4; Task 2; Task 5 |
| 4 | MAJOR | ACCEPT. Insert cases are scored with production semantics: `current_deck_spec` joins the expectations; `align_slides(current, output)` must give `inserted == expect["inserted"]`, `revised == positions − inserted`, deck-level fields equal to the reference's. A model-target mismatch is noted in the rationale, not failed (production ignores the targets). | D10; Task 8 |
| 5 | MAJOR | ACCEPT, option (b). No prescribed EDITING text and no list of user phrasings in Task 11's brief or Task 13's pins. The candidate author writes the placement wording from the issue text and the train failures. Forbidden reads widened. No held-out phrasing outside Appendix H. | D2; D6; D11; Held-out discipline; Tasks 11, 13 |
| 6 | MAJOR | ACCEPT. NEW TestClient test of `GET /api/chat/poll/{request_id}` across a shift: it pins D5's mid-turn polling limit and the completed `result.slides`. The Playwright spec becomes SSE only. | D5; Task 7; Task 14 |
| 7 | MINOR | ACCEPT. Claim corrected: the architect runs twice in a turn after `ask_data` (static `data_analyst → architect` edge). Two-pass test added. | Context; Task 6 |
| 8 | MINOR | ACCEPT. Rows added to the writer table. Invariant restated with its named exceptions. | Context table; Global constraints; Review focus |
| 9 | MINOR | ACCEPT. The shift passes `author_fallback=None`, `now_dt=None`; the pending row's dict is explicit. NULL-author and NULL-timestamp rows join the by-marker test. | D4; Task 2 |
| 10 | MINOR | ACCEPT. Every pack-test edit is named. | Task 9 |
| 11 | MINOR | ACCEPT. Per split, `add_slide_anchor`'s should_fail is right place and right targets with an off-request new slide (judge-only). The other three keep theirs. | D11; Task 9; Appendix H |
| 12 | MINOR | ACCEPT. B2 and F2 are all 9 existing train architect cases ×1. The skill overrides are recorded with the budget reason. Budget re-done. | Measurement; Task 11 brief |
| 13 | MINOR | ACCEPT. Pending copy "New slide — not built yet." Error-path limit documented. | D4; D5; Task 2 |
| 14 | MINOR | ACCEPT. WARNING `build_looks_like_insert`; residual risk recorded. | D1; Task 5; Risks |
| 15 | MINOR | ACCEPT. Task 6 gains turn-dies-after-shift, gapped insert and the `ask_data` loop. | Task 6 |
| 16 | MINOR | ACCEPT, target adjusted after verification. Sabotage the product, not the mock: remove the `complete` handler's `onSlidesGenerated` calls (`ChatPanel.tsx:296-303`). Swapping the refetch for `event.slides` stays green by design: `event.slides` IS the server's final deck (`chat_service.py:2128`, the same `get_slides` dict). | Task 14 |
| 17 | MINOR | ACCEPT. Task 4 runs after Task 2 (it uses `placeholder_slide` / `PENDING_SLIDE_TEXT`). | Order |
| 18 | NIT | ACCEPT. Citations corrected. | Context |
| 19 | NIT | ACCEPT. | Risks |
| 20 | NIT | ACCEPT. INFO log when the returned list order differs from position order. | Task 5 |
| 21 | NIT | REJECTED (parked). | — |
| 22 | NIT | REJECTED (parked); noted. | Risks |
| 23 | NIT | ACCEPT. RC12 spot-check at promotion. | Task 13 |
| 24 | NIT | ACCEPT. No test pins the slide number in a notice text (#332 owns notices). | Task 6 |
| 25 | NIT | ACCEPT (supervisor product rule). | D6; Task 11 brief |
| 26 | NIT | ACCEPT. Documented. | D4; Task 15 |

---

## Goal

A user on the graph path can ask for a new slide in an existing deck ("add a slide on X after
slide 3"; appended; as a named slide number; several at once) and get it. The architect returns the
revised `deck_spec` with the new `SlideSpec` where the user asked. The deck's rows shift through the
one canonical row writer, so every existing slide keeps its identity, attribution, verification
records and findings. Only the new slide (plus any slide the user also asked to change) is built.

## Acceptance criteria (verbatim from #314)

- **(A1)** An "add a slide" request produces an updated `deck_spec` with the new `SlideSpec` at the
  requested position (or appended), later positions shifted, and only the new slide built.
- **(A2)** Slide identity, attribution and verification records of the existing slides survive the
  shift.
- **(A3)** Covered by an architect eval case and a graph test.

**How each is met and tested**

| AC | Met by | Tested by |
|---|---|---|
| A1 spec | The promoted prompt (Tasks 11–13) tells the architect to insert, shift and target only new/changed slides. `architect_node` derives the insertion from the revised spec by an order-preserving alignment (Task 1, wired in Task 5) and canonicalises positions to 0..n. | Eval cases `add_slide_*` in both splits (Task 9), measured BEFORE and AFTER (Tasks 10, 12). `expected_category` scores them with production's own alignment (Task 8). Prompt-contract tests (Task 13). Node tests (Task 5). |
| A1 "only the new slide built" | Turn targets = the alignment's inserted ∪ revised, never the model's raw targets, never a shifted-but-unchanged slide (D3). | Task 6: builder and build reviewer are called for exactly the new position. Task 5 node tests. Task 8 scorer: `revised` must equal the requested revisions, so any untouched slide that changed fails. |
| A2 | Rows shift in ONE transaction through `_rewrite_slide_rows` (the per-slide writer that `save_slide_deck` and `restore_version` also use), with an exact old-row→new-position attribution. The deck spec is written in the same transaction (D4). Findings' `slideIndex` is projected from the slide's current row (D7); a verification write follows the content it verified (D8). | Task 2: by-content row tests (SQLite) + a CI-only Postgres test. Task 3: findings/verification. Task 7: the polling route across a shift. **Task 6: after an insert (contiguous and gapped decks), every existing slide's full row (slide_id, html, scripts, authorship, verification record, spec fragment) is unchanged, keyed by its own marker, and every finding renders on the slide whose content hash minted it.** |
| A3 | Four insert cases per split (Task 9); compiled-graph test (Task 6). | Pack self-tests; Task 6. |

---

## Context (verified 2026-10-20 against c971e372)

**Architect edit path** (`src/services/graph/nodes.py`)
- `architect_node` starts at `:1446`.
  - Committed rows are read once at `:1491` by `_committed_slide_rows` (`:992-1004`), via
    `SlideWriter.list_slides_in_position_order`. Each row dict carries `slide_id` and `content_hash`
    (`slide_repository.py:391-431`).
  - **`_committed_slide_rows` swallows every exception and returns `[]` (`:1000-1004`).** With no rows,
    `_persisted_spec_describes_these_rows` returns True (`:1064-1065`).
  - `committed_positions` is built at `:1493-1497` and `describe_only` at `:1549`.
  - The model payload is the literal dict at `:1563-1587` (11 keys; unchanged by this plan).
- Edit guards are decided from `prior_spec` and rows before the model's spec is used (`:1667-1739`):
  `edit_without_spec`, `spec_positions_stale` (`_persisted_spec_describes_these_rows`, `:1026`,
  compares position SETS), `edit_without_revised_spec`, and `edit_spec_positions_changed`
  (`:1723-1739`). The last refuses ANY change of the position set, so today every add is refused, and
  its user text says "it would have added or removed slides" (`:1737`).
- Brand re-resolve is at `:1745-1751`. `complete_index_only_bindings` / `invalid_slide_bindings`
  (`:1753-1767`) MUTATE `spec`. The one degrade block is `:1771-1796`: it sets discuss, the message
  and `error_state`, emits, `_say`s, and returns.
- Edit targets (`:1799-1830`):
  - `changed = {s.position for s in spec.slides if s != prior_by_position.get(s.position)}` — a set of
    **positions**, computed after the bindings mutate `spec`;
  - then `edit_targets = sorted(set(out.target_positions) | changed)`;
  - on an insert, every slide after the insert point would read as changed;
  - the #313 D5 log-only guard `edit_ignores_references` is at `:1817`.
- `classify_spec_change` is at `:1837` (deck-level fields `_DECK_LEVEL_FIELDS`, `:423-429`, plus the
  design-contract ids). The deck-level branch calls `rereview_committed_slides` at `:1867`. That pass
  reads rows BY POSITION (`:580-595`) against the new spec and treats a row as placeheld via
  `is_placeholder_record(row.get("verification_record"))` on the WHOLE record (`:647`).
- The pre-fan-out deck-level write is at `:2018-2047` (`write_deck_level_columns`, its own
  transaction; it bumps `deck.version` unless the turn is describe-only).
- `ArchitectOutput` (`src/domain/skill_io.py:66-117`) has no insert field. Its source and schema feed
  the frozen `schema_contract` digest: `_V1_DIGESTS` architect `9704af4e…`, pinned in six test files
  (`test_architect_edit_prompt.py`, `test_agent_schema_registry.py`, `test_retained_bundle_ledger.py`,
  `test_graph_definition_manifest.py`, `test_agent_runtime.py`, `test_persisted_agent_runtime.py`),
  plus the registry and the manifest.
- **The architect can run twice in one turn.** No node has a `RetryPolicy`
  (`src/services/graph/builder.py:135-140`), but the static edge `data_analyst → architect` (`:163`)
  re-enters the architect after `ask_data`, with the same `turn_id`. Only an edit return can shift,
  and an edit never loops back, so there is at most one shift per turn.
- Invalid model output fails structured-output validation in the runtime's provider parser, before
  `architect_node` writes anything (cf. `_require_structured_output`, `agent_runtime.py:323`). An
  example is a duplicate `SlideSpec.position`, rejected by `DeckSpec._slide_positions_must_be_unique`
  (`deck_spec.py:139-144`). The turn then ends with an error, not a refusal.

**Downstream of the architect**
- `foreman_service._covered_positions` (`:91`) covers `target_positions` on an edit.
  `build_branch_payload` (`nodes.py:1354`) briefs from `spec.slide_at(position)` and raises when the
  position is absent (`:1389-1395`).
- `slide_pipeline_node` (`:3154`) runs builder → `_write_draft_row` → build reviewer →
  `_write_reviewed_row` (`:1135`) → `SlideWriter.write_slide`:
  - `_write_draft_row` (`:3079`): "a draft only ever fills an EMPTY position"; `get_slide(...) is not
    None` means no draft (`:3109`);
  - `SlideWriter.write_slide` is a partial upsert **by position** (`slide_repository.py:88`);
  - a transient review failure keeps the draft only if one was written (`:3206-3228`), else
    re-raises.
- Failure paths all go through `_placehold_failed_position` (`:1233`) → `commit_placeholder`
  (`slide_repository.py:326`). Its HTML is fixed ("Slide generation failed."), its record is
  `{hash: {"error": True, "message": …}}`, and its author is NULL (Ruling C-15, `nodes.py:1284-1285`).
  Its notices say `Slide {position}` 0-based (`:1289`, `:1317`, `:3064`); that is #332's territory.
- `_release_slides` (`:308`, SSE) releases only this turn's covered positions, in ascending prefix
  order. `deck_reviewer_node` (`:3356`) reads all rows and writes the post-commit columns
  (`slide_count`, `html_content`, `scripts_content`).

**The canonical row writer** (`src/api/services/session_manager.py`)
- `_upsert_slide_row` (`:474`) writes a row's content.
  - Its full-identity path rewrites `slide_id`, authorship, `verification_record =
    merge(base_record, verification)` and `deck_spec_slide = spec_json or base_spec`.
  - Its fallbacks are `created_by = slide_dict.get("created_by") or author_fallback` and
    `created_at`/`modified_at = … or now_dt` (`:542-546`).
- `_attribute_slide_records` (`:361`) decides which old row's `(verification_record,
  deck_spec_slide)` (`SlideAttribution`, `:326`) follows each new position: by `slide_id`, then by
  content hash, then by unclaimed position.
- The sequence attribute → upsert every position → `_prune_slide_rows_beyond` (`:621`) is hand-copied
  twice:
  - `save_slide_deck` (`:1542`, block `:1665-1699`);
  - `restore_version` (`:2724`, block `:2843-2890`, with a per-slide incoming verdict).
- `SessionSlide`'s PK is `(session_id, position)`, and `modified_at` has no `onupdate`
  (`src/database/models/session.py:579-614`). Writers rewrite row CONTENT in place, never a row's
  position.
- The UI insert (`ChatService.insert_slide`, `chat_service.py:3720`) is `SlideDeck.insert_slide` →
  `save_slide_deck(deck_dict)` → `_insert_deck_spec_slide` (`:3985`, through
  `_rewrite_deck_spec_slides`, `:3846`), the last in a SECOND transaction. Its deck comes from
  `_get_or_load_deck` (`:2806`, a version-checked cache).
- `tests/unit/test_insert_shifts_records_and_specs.py` is the precedent for asserting by a per-slide
  MARKER, never by count or position. `tests/unit/test_multiworker_cache_coherence.py` is the
  cache-coherence guard pattern (tellr-code-review §1).

**Verdicts that look like placeholders**
- `is_placeholder_record` is True for any verdict with `error is True` (`slide_repository.py:57-65`).
- On any exception the LLM judge returns `error=True` with `score`, `explanation`, `issues`, `rating`
  and `duration_ms` (`src/services/evaluation/llm_judge.py:470-490`).
- `verify_slide` writes that verdict, plus `trace_id`, `genie_conversation_id` and `error_message`,
  into the slide's CURRENT-hash slot (`src/api/routes/verification.py:250-267`). The slot is shared
  with `tellr_review` (`_merge_verdict_slots`, `session_manager.py:250-294`).
- So today a judge-errored real slide reads as placeheld in `rereview_committed_slides`. A plain
  current-verdict check would read it as placeheld too.

**Reads**
- `get_slide_deck` (`:1784`), row path:
  - `index` is the list index (`:1848`) and `verification = record.get(content_hash)`;
  - findings come via `_deck_findings` (`:206`), with `slideIndex` "projected verbatim from what the
    reviewer stamped". Its own docstring names the limit: a finding whose slide moved after review
    carries its old index.
- The drawer filters `f.slideIndex === currentIndex`
  (`frontend/src/components/SlideViewer/SlideViewer.tsx:218-226`). Apply/Discuss chat text uses
  `slide ${finding.slideIndex + 1}` (`frontend/src/components/Layout/AppLayout.tsx:1067,1083`).
  Finding ids are `criterion:subject_hash:ordinal` (`src/domain/finding.py:229-245`), so they are
  keyed by content.
- `write_slide_verification` (`:2068`) merges into the row **at `position`** (lookup `:2139-2148`) and
  assigns `row.verification_record` directly (`:2177`), not through `_upsert_slide_row`. Callers read
  the deck by index, run the judge, then write by index: `verification.py:148-169`, then
  `:198,226,264`, and `slides.py:522-577`.
- Polling:
  - `slides_since_cursor` (`:2191`) returns the contiguous prefix from position 0 at or above the
    cursor;
  - `slide_revisions_since` (`:2326`) returns rows below the cursor whose `modified_at` is after the
    mark minus 2 s;
  - the route is `GET /api/chat/poll/{request_id}` (`src/api/routes/chat.py:827`, router prefix
    `/api` `:63`), returning `slides`, `slide_cursor`, `slide_revisions`, `revision_mark` and
    `result` (`:950-967`);
  - `result` is what `job_queue` stores from `COMPLETE`, `{"slides": event.slides, …}`
    (`job_queue.py:158-163,181-186`).
- Save points: `get_verification_map` (`:2381`) is flat by hash; `create_version` (`:2449`) snapshots
  `deck_spec_json`; `restore_version` copies it back (C9).

**Frontend and transports**
- SSE `slide_ready` → `AppLayout.handleSlideReady` (`:165-195`) → `_insertSlideAscending` (`:64-78`),
  which REPLACES the slide whose `index` equals the position and otherwise inserts in ascending
  order.
- Both transports end with a deck refetch:
  - SSE `COMPLETE` carries `slides=self.get_slides(...)` (`chat_service.py:2128`) after
    `_invalidate_deck_cache` (`:2090`);
  - the polling client synthesises `complete` from `response.result`
    (`frontend/src/services/api.ts:1156-1180`);
  - ChatPanel's `complete` handler calls `api.getSlides` and `onSlidesGenerated`, falling back to
    `event.slides`, which is the same deck dict (`ChatPanel.tsx:290-305`).
- **ChatPanel's `error` case does not refetch** (`ChatPanel.tsx:271-276`).
- The polling client restarts each turn with `slidesCursor = 0` (`api.ts:1093`). The incremental
  e2e spec's polling test is a permanent `test.skip`: `isPollingMode()` is false on localhost
  (`frontend/tests/e2e/incremental-slide-delivery.spec.ts:296-342`, `api.ts:35-50`).
- Numbering:
  - the panel shows `Slide {index + 1}` (`SlidePanel/SlideTile.tsx:181`,
    `SlideViewer/ThumbnailRibbon.tsx:133`; test id `ribbon-thumb-${index}`, `:90`);
  - SpecView shows `Slide {slide.position + 1}` (`SpecView/SpecView.tsx:214`);
  - they agree when positions are contiguous.
- `frontend/src/types/slide.ts:69-99` mirrors `SlideSpec`/`DeckSpec`; this plan changes neither.

**Resolver** (`src/domain/slide_numbering.py`, #313)
- "after slide 3" resolves "slide 3" (the anchor) only.
- "Insert a new slide 2" resolves the EXISTING slide 2.
- An indefinite ordinal such as "a final slide" resolves nothing (`_INDEFINITE_BEFORE_RE`,
  `:276-278`).
- Verified by running `resolve_slide_references` on every case message (pins in Task 9 and
  Appendix H).

**Eval harness**
- `expected_category_score(agent_key, structured, expect)` (`evals/harness/scorers.py:38-61`) checks
  the intent and, for an edit, `set(target_positions)`. It sees neither the deck spec nor the
  reference.
- The MLflow wrapper (`evals/harness/mlflow_run.py:187-192`) has `expectations = {expect, reference,
  design_system_active}` (`build_dataset`, `:108-120`). There is no `current_deck_spec`.
  `test_mlflow_run.py:272-277` requires the keys ⊇ those three and disjoint from scorer names.
- `judge.calibrate` (`evals/harness/judge.py:90`) has no case filter, and `--calibrate` returns before
  `--cases` is parsed (`evals/run_eval.py:115-126`). A split costs 2 judge calls per case.
- The judge sees `message` and `current_deck_spec` (`judge.py:36-37`). Its edit rule FAILS a
  different target set and FAILS a target brief that does not deliver the request.
- The architect has 9 cases per split. `test_cross_split.py:24,65-67` pins the ids and the total (39);
  `test_pack_generation_isolation.py` pins `{"architect": 9}`. The train deck has 10 slides, held-out
  6. `test_resolved_references_equal_the_expected_edit_positions` (#313's A2 proof) assumes the
  references ARE the targets, which is false for anchors.
- `v1-baseline` is the frozen manifest, i.e. `slide-refs` (content hash `ffc3074dc920…`; verified
  `INSTRUCTIONS == evals/configs/architect/slide-refs.md`).
- **Held-out leaks a repo-wide grep would find:**
  - `docs/superpowers/plans/2026-10-07-eval-heldout-set.md` holds held-out architect messages;
  - `evals/fixtures/meridian/heldout/` is the held-out gold deck;
  - `evals/packs/architect/__pycache__/heldout.*.pyc` and
    `tests/unit/evals/__pycache__/test_pack_architect_heldout*.pyc` exist.

**Pins a prompt change touches** (from #313 Task 10 and NOTES; re-verified)
- Rewritten by `promote`: `tests/unit/test_packaged_release_loader.py:24`,
  `tests/unit/test_graph_definition_manifest.py:707` and `src/services/agent_definition_manifest_v1.py`.
- By hand, recomputed by running code:
  - `tests/unit/test_architect_edit_prompt.py:38` `HEAD_ARCHITECT_CONTENT_HASH`;
  - `tests/unit/test_graph_definition_manifest.py:1159-1161`, the literal `7fc66007…` in
    `test_hashing_rejects_non_string_object_keys_inside_guidance`;
  - `HEAD_UNCHANGED_BLOCK_HASHES` (`test_architect_edit_prompt.py:81-86`), only if INTENT
    CLASSIFICATION changes.
- Phrase pins in `test_architect_edit_prompt.py`:
  - `EDITING_RULE_PHRASES` includes **"adding or removing slides is not an edit"** (`:126-133`); this
    plan deliberately retires it;
  - `EDITING_GUARD_PHRASES` (`:143-151`) keeps "if the user asks for that, use discuss and explain
    that it cannot be applied as an edit";
  - `SLIDE_NUMBERS_RULES` (`:438-489`).
- `tests/unit/evals/test_promote.py::test_zz_real_artefacts_unchanged_versus_head` is red between
  promote and the commit. The lifecycle contract fixture is not re-recorded (#313 precedent).
- Layer-3 live tests (not run in CI, `test.yml:1003-1048`):
  - `tests/agentic/test_rc2_architect_identifies_add_intent.py:74` and
    `test_rc9_architect_add_with_slide_reference.py` assert **`intent == "build"`** for an add. RC2's
    deck ends with a "close" slide.
  - `test_rc12_architect_asks_add_or_replace.py` expects `discuss` for a generation request on an
    existing deck.

**Existing unit tests that pin the old "adding is refused" behaviour**
- `tests/unit/test_graph_nodes.py:809-845` `test_an_edit_that_changes_the_position_set_is_refused`,
  param `adds-a-slide` `(0, 1, 2, 3)`.
- `tests/unit/test_graph_nodes.py:1755-1772` `test_f_a_degraded_edit_logs_nothing`, which uses a
  GROWN spec, `make_spec((0, 1, 2, 3))`, as its degrade trigger.
- The equal-length edit tests (`:880-900`, `:1023-1037` union, `:1040-1056` build growth) stay valid.
  There is no gapped equal-length edit test today (no `make_spec((0, 2` call).

**Sibling overlap** (open PRs; verified with `gh pr view --json files`)

| File this plan edits | Also edited by |
|---|---|
| `src/services/graph/nodes.py` | #332, #333, #334 |
| `src/api/services/session_manager.py` | #331, #332, #333, #334 (`_finding_to_camel`, adjacent to `_deck_findings`; #334's `plainMessage` does not read `slide_index`) |
| `tests/unit/test_graph_nodes.py` (two existing tests) | #332, #334 |
| `.github/workflows/test.yml` (e2e matrix line) | #331, #333 |
| `docs/technical/backend-overview.md` | #331 |
| `docs/user-guide/01-generating-slides.md` (optional) | #330–#334 |

Not edited: `chat_service.py`, `chat.py`, `ChatPanel.tsx`, `AppLayout.tsx`, `SpecView.tsx`, and any
#330 file. New tests go in new files to keep conflicts small.

**Baseline.** At c971e372, `uv run pytest tests/unit -q -n 4` gives **9687 passed, 135 skipped,
0 failed** (89 s). The focused set (graph nodes, architect prompt, architect packs, cross-split,
scorers, read-path keys, save points, graph builder, slide pipeline, deck-level spec change) gives
886 passed, 7 skipped.

### Corrections to the brief (the code wins)

1. **The UI insert is not one canonical writer.**
   - Rows (`save_slide_deck`) and spec (`_rewrite_deck_spec_slides`) are written in two transactions.
   - The row half round-trips the deck through `get_slide_deck`. Its `_resolve_deck_display_names`
     (`session_manager.py:2043-2066`) replaces authorship emails with SCIM display names, and
     `SlideDeck.from_dict` → `to_dict` → `save_slide_deck` then writes them back into `created_by`.
   - The graph shift therefore must NOT reuse that route. It reuses the per-slide writer under it and
     reads raw ORM rows.
   - The UI-path write-back is pre-existing; out of scope, follow-up recommended.
2. **Findings are not displayed by content.** Their `slideIndex` is the stamped position, so any
   shift (UI or graph) shows them on the wrong slide. Fixed here (D7).
3. **Whole-record placeholder checks give false positives.** `is_placeholder_record` on a whole
   record:
   - stays true for a slide that was once a placeholder and was later rebuilt (hash-keyed history is
     merged, never dropped);
   - is true for a judge-errored real slide.

   So `rereview_committed_slides` auto-fails both kinds. Fixed with a strict current-verdict
   predicate (D9).
4. The layer-3 RC2/RC9 tests expect `build` for an add; this plan makes an add an `edit`.
5. `--calibrate` does not honour `--cases`.

### Slide-row and slide-position writers and readers

**Invariant (restated).** Content upserts of a `session_slides` row go through `_upsert_slide_row`,
and every whole-deck rewrite goes through `_rewrite_slide_rows`. There are three named exceptions:
- the verdict-only merge `write_slide_verification` (`:2177`);
- the deletes `SlideWriter.delete_slide` (`slide_repository.py:280`) and `_prune_slide_rows_beyond`;
- the one-off startup backfill.

| # | Component | Reads / writes | Keys on | Breaks on a shift? | Plan |
|---|---|---|---|---|---|
| 1 | `save_slide_deck` per-slide block (`session_manager.py:1665-1699`) | writes every row | attribution: slide_id → hash → unclaimed position | No (it is how UI insert/reorder/delete shift) | Body moves into NEW `_rewrite_slide_rows`; behaviour identical (Task 2) |
| 2 | `restore_version` rows (`:2843-2890`) | writes every row, plus a per-slide incoming verdict | same | No | Calls `_rewrite_slide_rows(incoming=…)`: one copy instead of two (Task 2) |
| 3 | NEW `SlideWriter.insert_pending_slides` | in one txn: shifts rows, opens pending rows, writes `deck_spec_json`, bumps version | exact old-row → new-index map (no heuristic) | — | The graph's only shift (Task 2), called on every insertion turn (Task 5) |
| 4 | `SlideWriter.write_slide` (`slide_repository.py:88`) | partial upsert by position | position | **Yes** if rows are not shifted before a builder lands (it would overwrite the slide now at p) | Rows shift at architect commit, before any dispatch (D4); shifted even when the top-of-node read failed (finding 3) |
| 5 | `commit_placeholder` (`:326`) | placeholder by position | position | No (after the shift) | HTML/record built by NEW `placeholder_slide()`; output byte-identical (Task 2) |
| 6 | `SlideWriter.delete_slide` (`:280`) | deletes one row by position | position | No graph caller on an insert turn | — |
| 7 | `_write_draft_row` (`nodes.py:3079`) | draft into an empty position | `get_slide is not None` | Pending row ⇒ no draft preview, and a transient review failure re-raises | A row whose current verdict is a placeholder by the STRICT predicate counts as empty (Task 4) |
| 8 | `_write_reviewed_row` / fixer / `_land_original` | partial by position; verdict merged by hash | position + hash | No | — |
| 9 | `rereview_committed_slides` (`nodes.py:529`, `:580-595`, `:647`) | reads rows by position vs the new spec | position; whole-record placeholder test | **Yes** if run before the shift. Rebuilt-from-pending and judge-errored slides read as placeheld | Shift before `classify_spec_change` (D4); strict current-verdict predicate (Task 4) |
| 10 | `architect_node` changed-set (`:1799-1811`) | compares spec by position | position | **Yes**: every later slide reads as "changed" | Alignment (D1, D3; Tasks 1, 5) |
| 11 | `_persisted_spec_describes_these_rows` (`:1026`) | spec vs row position sets | set | No after a shift (both 0..n) | Unchanged; next-turn alignment tested (Task 6) |
| 12 | `build_branch_payload`, `_covered_positions` | spec by position; targets | position | No with the canonical spec | Canonical re-stamped spec in state (Task 5) |
| 13 | `_release_slides` (SSE, `:308`) | covered positions; rows by position | position | No | — |
| 14 | `deck_reviewer_node` (`:3356`) | all rows, digest; post-commit columns | content | No. If the turn dies after the shift, `slide_count`/`html_content` stay stale until the next post-commit write | Documented (D4) |
| 15 | `get_slide_deck` findings (`:1882`, `:1919`, `_deck_findings` `:206`) | projects the stamped `slideIndex` | stamped position | **Yes**: shifted slides' findings show on the wrong slide | Row path projects `slideIndex` = the row's list index (D7, Task 3) |
| 16 | `write_slide_verification` (`:2068`, direct assign `:2177`) + `verification.py`, `slides.py:522` | verdict merge by position after an index read | position | **Yes** if a shift lands between read and write (the verdict is stranded) | Locate by content hash first, then position (D8, Task 3) |
| 17 | `slides_since_cursor` / `slide_revisions_since` (polling) | by position, `modified_at` | position | Mid-turn only: shifted rows keep `modified_at` (attribution), so they are not re-sent | Known limit, pinned by a route test (Task 7); the end-of-turn refetch corrects it (D5) |
| 18 | `get_verification_map` / `create_version` / save points | flat by hash | hash | No | — |
| 19 | `ChatService._deck_cache` (`chat_service.py:2806`) | per-process cache | DB version | Stale unless the version moves | The shift bumps `deck.version` in its txn (Task 2) |
| 20 | `ChatService.insert_slide` (UI) | `save_slide_deck` + spec splice | slide_id | No | Unchanged; now calls `_rewrite_slide_rows` through `save_slide_deck` |
| 21 | `_rewrite_deck_spec_slides` (UI spec) | spec renumber | index | — | Not used by the graph (it writes its own canonical spec) |
| 22 | `deck_spec_slide` fragments | travel with `SlideAttribution` | — | Inner `position` goes stale (as after any UI shift); no reader in `src/` | Unchanged; documented |
| 23 | Startup backfill (`src/core/backfill_session_slides_startup.py:154,216`) | `_upsert_slide_row` + prune, from `deck_json` | position | Not on a graph turn | — |
| 24 | Tour route (`src/api/routes/tour.py:149,225`) | `save_slide_deck`, `write_slide_verification` by position | position | Demo sessions only; no graph shift | — |
| 25 | `duplicate_session` (`session_manager.py:1215-1222`) | copies the legacy `deck_json` blob, no rows | — | No graph turn writes that blob, so a duplicate of a graph deck is already stale (pre-existing) | Out of scope; noted |
| 26 | MCP (`src/api/mcp_server.py`) | monolith only: no `engine_mode`, so `job_queue.py:120-127` defaults to monolith | — | Never runs the graph | — |
| 27 | Frontend `_insertSlideAscending` / `handleSlideReady` | replaces by `index` | index | Mid-turn on SSE, the new slide replaces old slide p in the client until `complete` | Known limit; the `complete` refetch corrects it (D5); e2e pin (Task 14) |
| 28 | SlidePanel / ThumbnailRibbon / SpecView numbering | index+1 / position+1 | — | No (rows and spec are both contiguous after the shift) | e2e pin (Task 14) |
| 29 | Findings drawer / Apply / Discuss text | `slideIndex` | — | Yes, via #15 | Fixed by #15 |
| 30 | SlideViewer verification map, AppLayout cross-version match | `slide_id` | slide_id | No (ids preserved) | — |
| 31 | `useAutoVerification` | fires on a falsy `verification` | — | No (the pending record is truthy) | — |
| 32 | Exports (pptx/pdf/Google) | `slides[index]` | list order | No | — |
| 33 | Arc-review sweeper (describe-only) | spec only | — | — | No alignment and no shift on describe-only (Task 5) |
| 34 | `record_shared_deck_mutation` | evidence row, always written (`shared_deck_attribution.py:64-134`) | — | — | One `insert_slide`/`deck` event per shift (`:24,39`) |

---

## Decisions

**D1 — An insertion is expressed through the revised `deck_spec`; no schema change.**
- An edit whose spec has MORE slides than the persisted spec is an insertion. The node aligns old
  slides to new slides with a NEW pure module, `src/domain/slide_alignment.py` (Task 1):
  - Both lists are sorted by `position`.
  - The alignment is order-preserving. It pairs every old slide with one new slide and treats the
    remaining `k = len(new) − len(old)` new slides as inserted.
  - The pair cost is minimised lexicographically: (1 if `(purpose, content_brief)` differ, 1 if any
    field but `position` differs). An untouched slide aligns at (0,0), a neighbour whose only change
    is `assumes`/`hands_off` at (0,1), and a rewritten slide at (1,1).
  - **If more than one alignment reaches the minimum, refuse (`ambiguous`); never guess.**
  - After the unique alignment, if a revised pair's new slide equals a DIFFERENT old slide (field for
    field, ignoring position), refuse (`moves_slides`). An edit never moves a slide's spec.
  - `len(new) < len(old)` → refuse (deletion is out of scope). `len(new) == len(old)` → the unique
    positional pairing (today's behaviour), plus the `moves_slides` check.
- **What the alignment reports (finding 1).** Results are in BOTH numberings:
  - `inserted` / `revised`: the returned spec's own `SlideSpec.position` values;
  - `inserted_indices` / `revised_indices`: indices in position order, which is the canonical
    numbering after the node re-stamps;
  - `old_to_new_index`.

  The equal-length path uses `revised` (positions), which equals today's `changed` on any deck,
  gapped included. The insertion path re-stamps and uses the indices.
- *Why not a new field or intent (`insert_positions`, `add_slide`):*
  - `ArchitectOutput`'s source and JSON schema feed the frozen v1 schema-contract digest, which is
    pinned in six test files, the manifest and the retained-bundle ledger (historical releases);
  - a closed `ArchitectIntent` change also moves the router;
  - the spec the architect already returns on every edit carries all the information. The only loss
    is the rare ambiguous case, which is refused safely.
- *Why not "keep old positions and give new slides fresh numbers":* that contradicts "slides … in
  presentation order" with 0-indexed positions. The natural model output (re-stamped 0..n) would
  then be misread as many revisions.
- **What happens per request:**
  - **"add a slide after slide 3"** → unique alignment, `inserted_indices=(3,)`, targets `[3]`.
  - **"add a slide after slide 3 and update the agenda slide to mention it"** (agenda not adjacent)
    → unique: the agenda pairs with its revision at (1,1) and the new slide is the insert. Targets
    are `[agenda, 3]`.
  - **"add a slide after slide 3 and rewrite slide 3"** (revision ADJACENT to the insert) → two
    alignments tie at (1,1) → refused with `edit_insert_ambiguous`, nothing changed. The message asks
    for the add first, then the change.
  - **The model also tweaks the neighbours' `hands_off`/`assumes`** → unique at (0,2). The
    neighbours are revised and rebuilt: spec/slide consistency wins over "only the new slide". The
    prompt tells the model not to, and the scorer counts it as a failure.
  - **"add two slides"** → `k=2`, both inserted, both built.
  - **An append** (an explicit request for the end of the deck, e.g. "a final slide") → the new
    slide goes at `n`; no existing row moves.
  - **"insert a new slide 3"** → the new slide goes at position 2, and old 2 onwards shift.
  - **A gapped deck** (positions 0, 2, 5) → rows and spec become 0..n; identity is kept.
  - **Mis-shifts:**
    - duplicate positions → rejected by the runtime's parser before the node writes anything (an
      error turn; see Risks);
    - inserted but the last slide dropped (net 0) → `moves_slides` refusal;
    - inserted at the wrong place → applied where the model put it (the eval measures placement);
    - a new slide with an out-of-order fresh position → sorted by position, with an INFO log that
      list order and position order differ (Task 5).
  - **The model answers with `build`** → `build` rebuilds every position in place. Identity and
    records stay BY POSITION, so a mid-deck add answered as `build` mis-attributes every later slide
    (pre-existing build semantics). Task 5 logs a WARNING, `build_looks_like_insert`, when a build
    spec aligns as a pure insertion of the persisted spec over existing rows. This is a residual
    risk (Risks); the eval scores `build` as a failure.
- `edit_spec_positions_changed` stays for shrinking specs and equal-length renumbering. Its user
  sentence changes to "it would have removed or renumbered slides".

**D2 — The prompt change goes through a candidate config first, then promotion.**
- The candidate author (Task 11) writes `evals/configs/architect/add-slide.{md,yaml}` from
  `slide-refs`:
  - it rewrites the EDITING block, retiring "Adding or removing slides is not an edit";
  - it adds an anchor exception to SLIDE NUMBERS;
  - the placement wording is the author's own, written from the issue text, the product rule (D6)
    and the TRAIN failures. This plan prescribes no text and lists no user phrasings (finding 5);
  - INTENT CLASSIFICATION, DESIGN SYSTEMS, the opening and the closing stay byte-identical unless a
    candidate targets INTENT CLASSIFICATION and says so.
- It is measured on train only; the finalist runs on held-out once (Tasks 10, 12). It is promoted as
  the code default (Task 13). Graph v1 is unreleased, so there is no DB migration of prompts.

**D3 — "Only the new slide is built."**
- On an insertion turn, `target_positions = sorted(inserted_indices ∪ revised_indices)` in the
  canonical numbering.
  - The model's own `target_positions` are mapped through the re-stamp, compared, and logged when
    they differ (`insert_targets_disagree`, WARNING).
  - They are not honoured. A model that counts in the old numbering would otherwise rebuild (and
    destroy any hand edit on) a shifted, unchanged slide.
- Equal-length edits keep today's `model targets ∪ revised`, in positions, so a rebuild request
  without a spec change still works.
- The #313 D5 guard is skipped on insertion turns, because anchor references are never targets.
- A `design_contract` change still rebuilds every position.
- A deck-level change re-reviews AFTER the shift, so each committed slide is reviewed against its own
  spec entry. The pending row is a placeholder, so it fails by definition and is already a target.
- Deck review runs when the turn ends, over all rows, as on every turn.

**D4 — Rows shift at architect commit, atomically with the spec, through the canonical writer.**
- **Where.** In `architect_node`, after every degrade decision (guards, bindings, alignment) and
  before `classify_spec_change`. It runs on EVERY insertion turn that is not describe-only, whatever
  the top-of-node row read returned (finding 3).
- **How.** NEW `SlideWriter.insert_pending_slides` does all of this in ONE transaction:
  1. **Re-read the rows and check they are the rows the architect planned against.**
     - `[(slide_id, content_hash)]` in position order must equal `expected_rows`, the list the node
       read at the top.
     - Rows exist but `expected_rows` is empty (the top read failed) → `SlideRowsChangedError`.
     - Both empty (a spec-only deck) → write the spec and bump the version only; no pending rows.
     - Any other mismatch → `SlideRowsChangedError`. This also catches a UI mutation during
       planning.
  2. **Snapshot each old row** into a plain dict (html, scripts, slide_id, created_by, created_at,
     modified_by, modified_at — raw ORM values, never display names) and take its
     `SlideAttribution`, **before any write**: the upsert mutates those ORM objects in place.
  3. **Splice a pending row at each inserted index.** Its content is `placeholder_slide(
     PENDING_SLIDE_MESSAGE, text=PENDING_SLIDE_TEXT)` ("New slide — not built yet."), with a fresh
     `slide_id` and EXPLICIT `created_by=initiated_by`, `modified_by=initiated_by`,
     `created_at=modified_at=utcnow`.
  4. **Rewrite through the canonical writer:** `_rewrite_slide_rows(..., now_dt=None,
     author_fallback=None, attribution=<exact map>, incoming=<pending verdicts>)`. The `None`s
     mean a moved row with a NULL author or timestamp (failed placeholders, backfilled rows) stays
     NULL, and no moved row gets a fresh `modified_at` (finding 9).
  5. **Deck columns:** `deck.deck_spec_json = <canonical spec>`, `deck.version += 1`, and
     `last_activity` touched.
  6. **Evidence:** one `record_shared_deck_mutation(operation="insert_slide", object_type="deck")`.
- *Why not at land time:* builders run in parallel and land by position, so shifting there
  interleaves shifts. *Why not a new graph node:* topology pins (`test_graph_builder.py:66-77`), and
  nothing gained.
- *Why pending rows rather than a gap:* if the turn dies, a gap breaks
  `_persisted_spec_describes_these_rows` and the polling prefix. A placeholder keeps rows == spec on
  every path.
- **Rollback / failure guarantee:**
  - **A refusal, or a failed or stale shift.** Refusals are ambiguous, moves, shrink, bindings and
    stale spec. In every one of these cases nothing is written but the chat lines: deck rows, spec
    and version are unchanged. The turn degrades to discuss with a code: `edit_insert_ambiguous`,
    `edit_spec_moves_slides`, `edit_spec_positions_changed`, `insert_rows_changed` or
    `insert_rows_failed`.
  - **After the shift.** Rows `0..n+k−1` equal the spec positions, and each new position holds the
    pending placeholder.
  - **The new slide's build fails or is rejected** (builder exception, safety gate, reviewer
    failure, stall). `_placehold_failed_position` replaces the pending row with the failed
    placeholder and posts a chat notice. Every other slide is untouched, and rows and spec stay
    aligned.
  - **The turn dies after the shift** (e.g. a re-raised non-transient `PersistedRuntimeError`). The
    pending placeholder stays; its copy is still true. The next turn's
    `_persisted_spec_describes_these_rows` is true, so an edit that targets the new slide is
    accepted and builds it from its brief. Known side effects:
    - `slide_count` and `html_content` stay stale (session list and raw view) until the next
      post-commit write;
    - the client keeps its mid-turn view until reload (D5).
  - **The later pre-fan-out deck-level write fails.** Rows and spec are already aligned, because the
    spec was written in the shift transaction. The turn records `deck_level_write_failed` as today.
  - **Save points.** The end-of-turn save point snapshots the shifted deck. Restoring an earlier
    save point restores rows and `deck_spec_json` together (C9).
- **Multi-worker** (tellr-code-review §1):
  - no in-process state is added;
  - the shift re-reads rows inside its own transaction;
  - the version bump invalidates every other worker's `_deck_cache` and 409s a stale client save,
    which then refetches.
- **Pre-existing, out of scope:** a UI mutation made AFTER the shift, while builders run, can still
  misplace a landed slide. That is true of every edit turn today.

**D5 — Transports: the client learns of the shift from the end-of-turn deck refetch; no frontend code
change.**
- Both transports already refetch the deck on `complete` (Context). After an insert the refetched
  rows and spec are contiguous, so the panel (`index + 1`) and SpecView (`position + 1`) agree.
- **Known limits, documented and pinned:**
  - *Mid-turn on SSE:* the new slide's `slide_ready` replaces the old slide at that index.
  - *Mid-turn on polling:* when the first poll lands before the shift, the next polls deliver:
    - via `slides_since_cursor`, the old last slide again at `n`;
    - via `slide_revisions_since`, only the pending row. Shifted rows keep their `modified_at`
      because it is attribution.

    The client shows, for example, `[A, B, P, D, D]` until `complete`. Task 7 pins exactly this,
    and that `result.slides` is then the shifted deck.
  - *Error path:* ChatPanel's `error` case does not refetch (`ChatPanel.tsx:271-276`). A turn that
    dies after the shift leaves the mid-turn view until reload. A one-line refetch on `error` is a
    follow-up (frontend freeze; #331–#334 are editing ChatPanel).
- No `DeckSpec`/`SlideSpec` field changes, so `frontend/src/types/slide.ts` and
  `deckSpecConformance.test.ts` are untouched.
- Task 14 pins the SSE end state in a mocked Playwright spec; Task 7 pins polling at the route.

**D6 — Nothing deterministic is added to the resolver; the prompt carries placement.**
- `slide_numbering.py` and its contract are unchanged. The prompt (Task 11) says where a new slide
  goes, in the candidate author's own words. It reads numbers against `slide_numbering` (the deck
  before the insert), and treats a named slide on an add as the anchor, not a target.
- **Product rule (supervisor, review NIT 25):**
  - With no stated place, the architect puts the new slide where it fits the argument: before a
    closing or call-to-action slide, unless the new slide is itself a closing slide. It says in its
    message where it put the slide.
  - When the user explicitly asks for the end of the deck, the new slide goes after the last slide.
  - No eval case measures the no-place rule (Risks). The RC2 layer-3 update exercises it (Task 13).
- *Rationale for no resolver change:*
  - a new payload key would force regenerating all 26 architect payloads and an extra S0 run inside
    a USD 15 cap;
  - #313 measured the model at ceiling on position arithmetic;
  - D1/D4 make the node safe whatever position the model picks. A mis-anchored insert lands one
    place off, but never mis-attributes or rebuilds an existing slide.

  If F1 shows anchor slips, the follow-up is a deterministic `slide_insertions` payload key.

**D7 — Findings follow their slide.**
- On the row path of `get_slide_deck`, every finding read from a row's current-hash verdict gets
  `slideIndex` = that row's list index. A `-1` finding is left alone.
- The override is applied to the `Finding` BEFORE `_finding_to_camel`.
- The stored record is not rewritten, and the blob and no-rows paths are unchanged.
- This also fixes UI insert, reorder, delete and duplicate.

**D8 — A verification write follows the content it verified.** `write_slide_verification` writes
to, in order:
1. the row at `position`, if its HTML hashes to the verdict's key;
2. else the single other row whose HTML does;
3. else, as today, the row at `position`.

The change is purely additive.

**D9 — A placeholder is judged by the row's CURRENT verdict, with a strict predicate.**
- NEW `slide_repository.is_placeholder_verdict(verdict)`: `isinstance(verdict, dict)` and
  `is_placeholder_record(verdict)` and `set(verdict) <= {PLACEHOLDER_ERROR_KEY, "message"}`.
- A judge-error verdict carries `score`/`rating`/`explanation`/…, so it is not a placeholder. Nor is
  a slot that also holds `tellr_review`.
- NEW `nodes._holds_placeholder(row)` applies it to `record.get(row["content_hash"])`.
  - `_write_draft_row` treats such a row as empty, so the new slide gets its draft preview and the
    transient-review tolerance.
  - `rereview_committed_slides` uses it instead of the whole-record check.

**D10 — The eval yardstick scores inserts with production semantics, before any measurement.**
- `build_dataset` adds `expectations["current_deck_spec"]` for architect cases that have a deck. The
  key is omitted when the deck is `None`.
- `expected_category_score(..., *, reference=None, current_deck_spec=None)`. When `expect` has
  `"inserted"`, all of these must hold:
  - the intent equals the expected one (`edit`);
  - the output carries a valid `deck_spec`;
  - `align_slides(current, output)` does not refuse;
  - `list(inserted_indices) == expect["inserted"]`;
  - `sorted(revised_indices) == sorted(set(expect["positions"]) − set(expect["inserted"]))`;
  - `audience`, `purpose`, `argument`, `call_to_action`, `narrative_arc` and the design-contract ids
    equal the reference's. A test pins this field tuple to `nodes._DECK_LEVEL_FIELDS`.
- A difference between the model's `target_positions` and `expect["positions"]` is noted in the
  rationale and does NOT fail the row, because production ignores those targets on an insert (D3).
- The missing `reference` or `current_deck_spec` fails with an explicit rationale. Cases without
  `"inserted"` score exactly as today.
- `judge.calibrate` and `--calibrate` honour `--cases`. The 9 existing cases were trusted in #313 on
  byte-identical files with the same judge, so only the new ones are calibrated.
- `judge_prompt.md` and `intent_report.py` are unchanged. On insert rows, `intent_report`'s position
  accuracy reflects the model's targets, which production ignores; `expected_category` is the
  production measure (README).

**D11 — Cases.** Four per split, with the same ids and different phrasing and deck (Task 9,
Appendix H):
- `add_slide_anchor` — an insert relative to a named slide;
- `add_slide_end` — an append;
- `add_slide_as_number` — the new slide takes a named slide number;
- `add_slide_and_revise` — an insert plus a revision of a later slide.

Calibration `should_fail`s, per split:
- `add_slide_anchor`: right place and right targets, but an off-request new slide. The judge alone
  separates it (finding 11).
- `add_slide_end`: the last slide replaced instead of a slide added.
- `add_slide_as_number`: inserted one place late.
- `add_slide_and_revise`: added, but the requested revision forgotten.

**D12 — Measurement and the accept rule** are fixed in the Measurement section before any run.

**D13 — Promotion replaces the default** (`promote`, precedent 45ce906c/e4387c83).
- There is no migration and no contract re-record.
- Rollout caveat, as in #313: the manifest seeds a fresh bootstrap only. Existing installs get the
  node behaviour at once and the prompt when an admin publishes.

**D14 — If no finalist is accepted: branch (ii).**
- Ship Tasks 1–9 and 14 (code, cases, yardstick) with the unchanged `slide-refs` prompt.
- The model keeps refusing most adds, but any insert-shaped edit it emits is applied safely.
- Record BEFORE/AFTER. #314 stays open: A1 is not met end to end.

---

## Global constraints

- **Environment.**
  - Worktree `/Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-314`; use
    absolute paths and `uv run …`.
  - Never `pip install`, never `git stash`, never `gh auth switch`.
  - Import `src.core.database` before other `src.*` imports in tests and scripts.
  - Unit tests use disposable SQLite. There is no local Postgres: `pytest.mark.postgres` and
    `tests/integration` run in CI only.
- **Live calls.** No implementer or reviewer runs `evals.run_eval` or any model. Tasks 10 and 12 are
  SUPERVISOR-run. No deploys.
- **Commits.** The supervisor commits after review with `Co-authored-by: Isaac
  <no-reply@databricks.com>`. No held-out content in commit messages.
- **Do not edit:**
  - `ArchitectOutput`/`skill_io.py`, `DeckSpec`/`SlideSpec`, `slide_numbering.py`;
  - `MODEL_PAYLOAD_KEYS` / the architect payload dict;
  - `judge_prompt.md`, `prices.yaml`;
  - `chat_service.py`, `chat.py`, any frontend source file (Task 14 adds one e2e spec only);
  - #330's files.
- **One row writer.** The invariant and its named exceptions are as restated above the writer table.
  No new hand-copied row writer.
- **No held-out phrasing outside Appendix H** in plans, prompts, READMEs or test names.
- **Testing discipline.** Baselines are cause-sets. Sabotage-verify every approved test (§1), and
  confirm that each sabotage sits on the executed path.

## Held-out discipline

| Agent | May read `cases_heldout/`, `heldout.py`, `test_pack_architect_heldout.py`, Appendix H | Notes |
|---|---|---|
| Task 9 case author (test + impl) | yes, writes them | Never copies held-out text into prompt, README, docs or test names. |
| Supervisor | yes | Held-out results as aggregates only. |
| Task 11 prompt-candidate author | **NO** | Also barred from all of `docs/superpowers/plans/`, `evals/fixtures/**/heldout/`, every `__pycache__` directory, everything under `~/tellr-loop/`, the `tellr-agent-eval-heldout` experiment, and `git show`/`git log -p` of commits touching those paths. Every repo-wide grep uses `--exclude-dir=cases_heldout --exclude-dir=__pycache__ --exclude-dir=heldout`. |
| Task 13 test author | not needed | Pins the finalist's own sentences; no regex enumerates user phrasings. |
| All other tasks | not needed | Task 15 writes held-out ids and aggregates only. |

## File map

| Area | Files |
|---|---|
| Alignment | `src/domain/slide_alignment.py` (new), `tests/unit/test_slide_alignment.py` (new) |
| Row writer + shift | `src/api/services/session_manager.py`, `src/api/services/slide_repository.py`, `tests/unit/test_insert_pending_slides.py` (new), `tests/unit/test_insert_pending_slides_postgres.py` (new, CI-only) |
| Findings / verification | `src/api/services/session_manager.py`, `tests/unit/test_findings_follow_their_slide.py` (new) |
| Placeholder predicate | `src/api/services/slide_repository.py`, `src/services/graph/nodes.py`, `tests/unit/test_pending_slide_is_fillable.py` (new) |
| Architect insert path | `src/services/graph/nodes.py`, `tests/unit/test_architect_insert_slide.py` (new), `tests/unit/test_graph_nodes.py` (two tests) |
| Graph acceptance | `tests/unit/test_graph_insert_slide_turn.py` (new) |
| Polling route | `tests/unit/test_poll_route_across_an_insert.py` (new) |
| Yardstick | `evals/harness/scorers.py`, `evals/harness/mlflow_run.py`, `evals/harness/judge.py`, `evals/run_eval.py`, `tests/unit/evals/{test_scorers,test_mlflow_run,test_judge,test_run_eval}.py` |
| Cases | `evals/packs/architect/{mutations,heldout}.py`, 4 new dirs per split, `tests/unit/evals/{test_pack_architect,test_pack_architect_heldout,test_cross_split,test_pack_generation_isolation}.py` |
| Candidate | `evals/configs/architect/add-slide.{md,yaml}` |
| Promotion | `src/core/skills/architect.py`, the manifest + two pins via promote, `tests/unit/test_graph_definition_manifest.py:1159-1161`, `tests/unit/test_architect_edit_prompt.py`, `tests/agentic/test_rc2_*.py`, `test_rc9_*.py` |
| E2E | `frontend/tests/e2e/agent-insert-slide.spec.ts` (new), `.github/workflows/test.yml` |
| Docs | `CONTEXT.md`, `docs/technical/backend-overview.md`, `evals/README.md`, optional `docs/user-guide/01-generating-slides.md` |

## Order and parallelism

```
Task 1 (alignment) ─┬─> Task 2 (row writer + shift) ─> Task 3 (findings, verification) ─> Task 7 (polling route)
                    │        └─> Task 4 (strict placeholder predicate) ─> Task 5 (architect_node) ─> Task 6 (graph acceptance)
                    │
                    └─> Task 8 (yardstick) ─> Task 9 (cases) ─> [commit 1,8,9] ─> Task 10 SUPERVISOR: C1 C2 B1 B2 B3
                                                                                          v
                                       Task 11 (candidate, train only) <-> Task 12 SUPERVISOR: S1 [S2] F1 F2 F3 → accept?
                                                                                          v
                                                                  Task 13 (promote; after Task 6) ─> Task 15 (docs)
Task 14 (mocked Playwright, SSE) — any time.
```
- Same-file tasks run in sequence: 2 → 3 (`session_manager.py`); 2 → 4 (`slide_repository.py`; Task 4
  uses `placeholder_slide` / `PENDING_SLIDE_TEXT`); 4 → 5 (`nodes.py`).
- Tasks 1–7 and 14 need no live model, so they can ship even if Databricks auth fails (branch ii).
- Task 10 measures the SHIPPED prompt on unchanged payloads. It needs Tasks 1, 8 and 9 only.
- Task 13 waits for Task 6, so the promoted prompt never ships ahead of the node that accepts
  inserts.

---

## Task 1: Pure slide alignment

**Models:** test=opus impl=sonnet

**Files:** `src/domain/slide_alignment.py` (new), `tests/unit/test_slide_alignment.py` (new)

Interface (NEW). The module imports only `json`, `dataclasses`, `typing` and
`src.domain.deck_spec.SlideSpec`:

```python
AlignmentRefusalCode = Literal["removes_slides", "ambiguous", "moves_slides"]

class AlignmentRefused(ValueError):
    """The revised slides cannot be matched to the current ones without guessing."""
    def __init__(self, code: AlignmentRefusalCode, detail: str): ...
    code: AlignmentRefusalCode

@dataclass(frozen=True)
class SlideAlignment:
    new_positions: tuple[int, ...]       # index (position order) -> the returned SlideSpec.position
    old_to_new_index: Mapping[int, int]  # persisted SlideSpec.position -> index in the returned spec
    inserted_indices: tuple[int, ...]    # returned slides with no persisted slide, ascending
    revised_indices: tuple[int, ...]     # returned slides whose persisted slide differs, ascending

    @property
    def inserted(self) -> tuple[int, ...]:  # the same slides as returned-spec POSITIONS
    @property
    def revised(self) -> tuple[int, ...]:   # returned-spec POSITIONS (== today's `changed` when lengths are equal)

def slide_key(slide: SlideSpec) -> str:
    """Canonical JSON of the slide without `position` (sort_keys)."""

def align_slides(old: Sequence[SlideSpec], new: Sequence[SlideSpec]) -> SlideAlignment:
    """D1. Sort both by position. len(new) < len(old) -> removes_slides. Otherwise return the unique
    order-preserving alignment that pairs every old slide and inserts len(new)-len(old) new ones,
    minimising (sum identity_diff, sum full_diff) lexicographically. More than one optimum ->
    ambiguous. A revised pair whose new slide's key equals a DIFFERENT old slide's key ->
    moves_slides."""
```

Algorithm (structure only; the tests are the contract):
- DP over `(i old consumed, j new consumed)` with `0 ≤ j − i ≤ k`.
- Two transitions: "pair old[i−1] with new[j−1]" (+cost) and "insert new[j−1]" (+(0,0)).
- Keep the lexicographic minimum and the number of optimal paths, capped at 2.
- Backtrack the unique path.
- Identity is `(purpose, content_brief)`; full equality is `slide_key`.

Steps:
- [ ] **Step 1 (test author).** Write table-driven tests over `SlideSpec(...)` slides with distinct
  purposes and briefs. Each row is `(old, new, expected)`, asserting both numberings where relevant:
  - **Equal length.**
    - Nothing changed → nothing inserted or revised; identity map.
    - One brief changed → `revised=(p,)`.
    - **Gapped `[0,2,5]`, revise 5 → `revised == (5,)`, `revised_indices == (2,)`.**
    - Gapped, revise 2 → `revised == (2,)`.
  - **Inserts.**
    - At 0, mid-deck and after the last slide.
    - Two inserts, adjacent and apart; `k=3`.
    - **Into gapped `[0,2,5]`** → `old_to_new_index == {0:0, 2:2, 5:3}` for an insert at index 1.
  - **Insert + revision.** A non-adjacent revision before or after the insert point is unique, and
    the revised index is in the NEW numbering (e.g. old 9 → new 10).
  - **Insert with neighbours changed.** Both neighbours changed only in `hands_off`/`assumes` →
    unique; both revised.
  - **Ambiguous.**
    - Insert adjacent to a rewritten slide (purpose or brief changed) → `ambiguous`.
    - An identical-content duplicate that could be either new slide → `ambiguous`.
  - **Refusals.**
    - Shrink → `removes_slides`.
    - Equal-length swap of two slides → `moves_slides`.
    - Insert at 3 with the last slide dropped (net equal) → `moves_slides`.
    - Reorder plus insert → refused (assert that it is refused, not which code).
  - **Edge cases.**
    - The model's out-of-order fresh position (`position=10` placed mid-list) sorts to the end.
    - `slide_key` ignores `position` and treats an absent `template_section_index` like `None`.
  - **Sabotage:**
    - drop the tie count → the two `ambiguous` rows go red;
    - compare only `content_brief` (no full-diff tier) → the hands-off row goes red;
    - drop the moved check → both `moves_slides` rows go red;
    - **return indices from `revised` → the gapped equal-length rows go red;**
    - **map `old_to_new_index` by list position instead of by sorted position → the gapped insert
      row goes red.**

  Confirm red. Leave uncommitted.
- [ ] **Step 2 (implementer):** implement without editing tests.
- [ ] **Step 3.** Run `uv run pytest tests/unit/test_slide_alignment.py -n 4 -q`.
  `grep -nE '^(import|from) ' src/domain/slide_alignment.py` must list only `__future__`, `json`,
  `dataclasses`, `typing` and `src.domain.deck_spec`.

## Task 2: One per-slide rewrite, and the pending-slide shift

**Models:** test=opus impl=opus (the canonical row writer; a quiet mistake mis-attributes verdicts)

**Files:**
- `src/api/services/session_manager.py`, `src/api/services/slide_repository.py`;
- `tests/unit/test_insert_pending_slides.py` (new);
- `tests/unit/test_insert_pending_slides_postgres.py` (new; `pytestmark = pytest.mark.postgres`;
  CI-only; fixture pattern `tests/unit/test_spec_dirty_marker.py:303-348`).

Interfaces (NEW):

```python
# session_manager.py (module level, beside _upsert_slide_row)
def _rewrite_slide_rows(
    db: Session,
    owner_id: int,
    slides: List[Dict[str, Any]],
    *,
    now_dt: Optional[datetime],
    author_fallback: Optional[str],
    attribution: Optional[Dict[int, SlideAttribution]] = None,
    incoming: Optional[Dict[int, Dict[str, Any]]] = None,
) -> None:
    """THE per-slide rewrite of a whole deck: attribution (computed by _attribute_slide_records
    unless the caller passes the exact map), _upsert_slide_row on the full-identity path for every
    position, then _prune_slide_rows_beyond. The caller owns the transaction. The old rows are read
    and attributed BEFORE any upsert."""

# slide_repository.py
FAILED_SLIDE_TEXT = "Slide generation failed."
PENDING_SLIDE_TEXT = "New slide — not built yet."
PENDING_SLIDE_MESSAGE = "Inserted slide not yet built"

def placeholder_slide(error_message: str = "", *, text: str = FAILED_SLIDE_TEXT) -> Tuple[str, Dict[str, Any]]:
    """(html, {content_hash: {PLACEHOLDER_ERROR_KEY: True, "message": error_message}})."""

class SlideRowsChangedError(RuntimeError):
    """The committed rows are not the rows the caller planned against."""

class SlideWriter:
    def insert_pending_slides(
        self,
        session_id: str,
        insert_at: Sequence[int],
        *,
        deck_spec: str,
        expected_rows: Sequence[Tuple[Optional[str], str]],
        created_by: Optional[str],
        mutation: DeckMutationContext,
    ) -> List[str]:
        """D4 steps 1-6 in ONE get_db_session(); returns the new slides' slide_ids in insert_at order
        ([] for a row-less deck, where only the spec and version are written). Raises:
        - ValueError if insert_at is not ascending, distinct and within [0, len(rows) + len(insert_at));
        - SlideRowsChangedError if the re-read rows differ from expected_rows, including rows that
          exist when expected_rows is empty;
        - SessionNotFoundError from the helpers.
        Nothing is written on any raise."""
```

Behaviour:
- `save_slide_deck` replaces its block `:1665-1699` with one call:
  `_rewrite_slide_rows(db, deck_owner.id, slides, now_dt=now_dt, author_fallback=modified_by)`.
- `restore_version` replaces `:2849-2890` with `_rewrite_slide_rows(..., author_fallback=None,
  incoming={position: {hash: verdict}})`, with `incoming` built exactly as today.
- In both methods the query order is unchanged, because the `test_save_points.py` mocks count calls.
- `commit_placeholder` builds its HTML and record with `placeholder_slide(error_message)`. The output
  is byte-identical to today's.
- `insert_pending_slides` writes rows only through `_rewrite_slide_rows`:
  - with `now_dt=None` and `author_fallback=None`;
  - with the exact attribution `{new_index: _attribution_from(old_row)}`;
  - with `incoming={new_index: pending_record}`;
  - the pending dicts carry explicit authorship and timestamps;
  - it never calls `_attribute_slide_records`: the mapping is known, so a heuristic could only be
    wrong;
  - it does NOT write `slide_count`, whose single writer is the post-commit write.

Steps:
- [ ] **Step 1 (test author).** In `tests/unit/test_insert_pending_slides.py` (fixtures in the style
  of `test_insert_shifts_records_and_specs.py:66-160`), seed rows. Each row has a distinctive marker
  in its HTML, its own `slide_id` and `scripts`, its own authorship and timestamps, a TWO-hash
  verification record (history + current, plus a `tellr_review` finding) and a `deck_spec_slide`
  fragment. The rows are:
  - A–D;
  - one **failed placeholder with a NULL author** (commit_placeholder shape);
  - one **backfilled row with NULL `created_at`/`modified_at`**.

  Tests, all keyed by marker:
  - **`insert_pending_slides(sid, [1, 3], ...)`.**
    - Every old row, looked up by its marker, equals its pre-call snapshot in every column except
      `position` and `id`. That includes the NULL author and the NULL timestamps, which stay NULL.
    - The pending rows sit at 1 and 3. Each satisfies `is_placeholder_verdict` on its current
      verdict, shows `PENDING_SLIDE_TEXT`, and has a fresh, distinct `slide_id` (the ones returned),
      `created_by`/`modified_by` = the argument, explicit timestamps and no fragment.
    - `deck_spec_json` equals the argument, `version` is +1, and there is exactly one
      `insert_slide` mutation event.
  - **Append (`insert_at=[len(rows)]`):** no old row is rewritten (`modified_at` unchanged on all).
  - **Gapped rows `[0, 2, 5]` with `insert_at=[1]`:** rows become `0..3` in marker order, every old
    row equals its snapshot by marker, and no row is left at 5.
  - **Precondition failures:**
    - a mismatch (one `content_hash` differs) raises `SlideRowsChangedError`;
    - **`expected_rows=[]` while rows exist** raises `SlideRowsChangedError`;
    - an invalid `insert_at` raises `ValueError`.

    In each case rows, `deck_spec_json` and `version` stay byte-identical.
  - **Row-less deck with `expected_rows=[]`:** the spec is written and the version bumped, no rows
    are created, and the call returns `[]`.
  - **Exact attribution, not the heuristic:** seed an id-less (`slide_id` NULL) leftover pending
    placeholder row AFTER the insert point. After `insert_pending_slides([1])` it keeps its own
    record, and the new pending row carries none. (With `attribution=None`, pass 2 would match the new
    pending row to the leftover by identical HTML and steal its record.)
  - **Contributor session:** writes the owner's deck.
  - **Coherence** (tellr-code-review §1; pattern `tests/unit/test_multiworker_cache_coherence.py`): a
    `ChatService` that cached the deck before the shift returns the shifted deck from
    `_get_or_load_deck` afterwards.
  - **Placeholder HTML:** `placeholder_slide()` with defaults equals what `commit_placeholder` wrote
    before (literal HTML pinned).
  - **The Postgres file** repeats the `[1, 3]` test and one precondition test on a throwaway
    database.
  - **Sabotage** (assign different ones to the reviewer):
    - build the row dicts lazily inside the upsert loop → the by-marker test goes red;
    - `attribution=None` → the leftover-placeholder test goes red;
    - `now_dt=datetime.utcnow()` or `author_fallback=created_by` → the NULL-author/NULL-timestamp
      rows go red;
    - carry only html/scripts/slide_id → red;
    - drop the spec write → red;
    - drop the version bump → the coherence test goes red;
    - skip the `expected_rows=[]` check → its test goes red.

  The existing suites must stay green unchanged: `test_insert_shifts_records_and_specs.py`,
  `test_save_points.py`, `test_slide_writer.py`, `test_deck_read_path_keys.py`,
  `test_reindex_slide_ids.py`. Confirm red. Leave uncommitted.
- [ ] **Step 2 (implementer):** implement without editing tests.
- [ ] **Step 3.**
  - Run `uv run pytest tests/unit/test_insert_pending_slides.py tests/unit/test_insert_shifts_records_and_specs.py tests/unit/test_save_points.py tests/unit/test_slide_writer.py tests/unit/test_deck_read_path_keys.py tests/unit/test_reindex_slide_ids.py tests/unit/test_multiworker_cache_coherence.py -n 4 -q`.
  - Then run the unit suite and compare the failing-cause set with the baseline.
  - `grep -n "_attribute_slide_records(\|_prune_slide_rows_beyond(" src/api/services/session_manager.py`
    must show each called only inside `_rewrite_slide_rows` (besides their definitions).

## Task 3: Findings and verification follow their slide

**Models:** test=opus impl=sonnet

**Files:** `src/api/services/session_manager.py`, `tests/unit/test_findings_follow_their_slide.py`
(new)

Behaviour:
- **`_deck_findings(pairs, *, slide_indices: Optional[List[int]] = None)`.**
  - `slide_indices` is passed on the row path only: the list index of each pair's row.
  - When it is given, each `Finding` with `slide_index != -1` is projected with `slide_index`
    replaced, BEFORE `_finding_to_camel`.
  - Its docstring loses the "carries the index it was stamped with" limit.
- **`write_slide_verification`.** After the legacy branch, it picks the target row in this order:
  1. the row at `position`, if `compute_slide_hash(row.html)` equals the record's key;
  2. else the unique row whose HTML hashes to the key (log INFO "verification followed its slide");
  3. else the row at `position`, as today.

Steps:
- [ ] **Step 1 (test author).**
  - **Findings.**
    - Seed rows A, B, C with reviewer findings stamped at their positions. Use
      `build_verification_record` and ids shaped like `_stamp_findings`' `criterion:hash:ordinal`.
    - Shift with `SlideWriter.insert_pending_slides([1])` and, separately, with a `save_slide_deck`
      reorder.
    - Then for every finding in `get_slide_deck()["findings"]`:
      `slides[f["slideIndex"]]["content_hash"] == f["id"].split(":")[1]`.
    - A stored `-1` finding stays `-1`. The blob path still projects verbatim.
  - **Verification.**
    - Rows A, B: a verdict keyed by A's hash written at position 1 lands in A's row, and B's record
      is unchanged.
    - A verdict whose hash matches no row is written at `position` (today's behaviour).
    - Two identical rows plus a non-matching position fall back to `position`.
  - **Sabotage:** remove the override → the findings test goes red; remove the content lookup → the
    A/B test goes red.

  Confirm red. Leave uncommitted.
- [ ] **Step 2 (implementer).**
- [ ] **Step 3.** Run `uv run pytest tests/unit/test_findings_follow_their_slide.py tests/unit/test_deck_read_path_keys.py tests/unit/test_finding_conformance.py tests/unit/test_verification_conformance.py -n 4 -q`,
  then the unit suite.

## Task 4: The strict placeholder predicate (runs after Task 2)

**Models:** test=opus impl=sonnet

**Files:** `src/api/services/slide_repository.py`, `src/services/graph/nodes.py`,
`tests/unit/test_pending_slide_is_fillable.py` (new)

Behaviour (D9):
- NEW `slide_repository.is_placeholder_verdict(verdict) -> bool`.
- NEW `nodes._holds_placeholder(row: Optional[dict]) -> bool` =
  `row is not None and is_placeholder_verdict((row.get("verification_record") or {}).get(row.get("content_hash")))`.
- `_write_draft_row` (`:3109`) skips only when the row exists AND does not hold a placeholder.
- `rereview_committed_slides` (`:647`) uses `if _holds_placeholder(row):`.

Steps:
- [ ] **Step 1 (test author).** Use `graph_env_threadsafe` and the `test_slide_pipeline.py`
  `_wire`/`_run` pattern. Pending rows come from `placeholder_slide(PENDING_SLIDE_MESSAGE,
  text=PENDING_SLIDE_TEXT)`.
  - **(a)** A position holding a pending placeholder gets the builder's draft before review: the
    reviewer sees the draft HTML.
  - **(b)** A transient review failure there keeps the draft, and the turn finishes.
  - **(c)** A **reviewed slide whose current slot also carries an LLM-judge error verdict** (the
    `verification.py:250-267` shape with `"error": True`, `score`, `rating`, `explanation`,
    `issues`, …):
    - gets NO draft (the reviewer sees the committed HTML);
    - in `rereview_committed_slides`, it is reviewed by the model, not auto-failed.
  - **(d)** A slide whose record holds an OLD placeholder hash and a current real verdict is reviewed
    by the model.
  - **(e)** A genuine placeholder still fails with no model call.
  - `test_a_draft_never_overwrites_a_committed_slide` and
    `test_without_a_draft_a_transient_review_failure_still_fails_the_turn` stay green unchanged.
  - **Sabotage:**
    - plain `is_placeholder_record` on the current verdict → (c) goes red;
    - the whole-record check → (d) goes red;
    - keep the `is not None` rule → (a) goes red.

  Confirm red. Leave uncommitted.
- [ ] **Step 2 (implementer).**
- [ ] **Step 3.** Run `uv run pytest tests/unit/test_pending_slide_is_fillable.py tests/unit/test_slide_pipeline.py tests/unit/test_deck_level_spec_change.py -n 4 -q`.

## Task 5: `architect_node` applies an insertion

**Models:** test=opus impl=opus (ordering inside the node is the whole correctness argument)

**Files:** `src/services/graph/nodes.py`, `tests/unit/test_architect_insert_slide.py` (new),
`tests/unit/test_graph_nodes.py` (two existing tests, named below)

Behaviour (line numbers at c971e372):
1. **NEW `_degrade_edit(state, updates, degrade) -> Dict[str, Any]`.** It is the body of the degrade
   block `:1771-1796` moved verbatim, plus `updates["target_positions"] = None`. The existing site
   calls it.
2. **The `:1723-1739` guard** fires only when `len(spec.slides) < len(prior_spec.slides)`, or when
   the lengths are equal and the position sets differ. Its user text becomes: "I could not apply that
   edit: it would have removed or renumbered slides, and an edit only adds slides or changes the ones
   that are there. Nothing has been changed."
3. **Alignment.** After the bindings (`:1767`) and before the degrade check, for `intent == "edit"`
   when the turn is not describe-only, `prior_spec` is present and there is no degrade yet:
   - `alignment = align_slides(prior_spec.slides, spec.slides)`;
   - INFO-log when the returned list order differs from position order;
   - `AlignmentRefused` sets `edit_degrade` with one of two codes:
     - `edit_insert_ambiguous`: "I could not tell which of the existing slides I was changing and
       where the new slide goes, so nothing has been changed. Ask me to add the slide on its own
       first, then for the other change.";
     - `edit_spec_moves_slides`: "I could not apply that edit: it would have moved existing slides,
       and an edit only adds slides or changes the ones that are there. Nothing has been changed.";
   - `removes_slides` cannot arise, because step 2 caught it.
4. **Targets.**
   - If `alignment.inserted_indices`: re-stamp `spec` (sorted by position, positions `0..m−1`) and
     keep `model_to_final`. Set `edit_targets = sorted(inserted_indices ∪ revised_indices)`. Map the
     model's targets and log `insert_targets_disagree` when they differ. Skip the D5 guard.
   - Otherwise (equal length), the targets are today's
     `sorted(set(out.target_positions) | set(alignment.revised))`. `revised` holds POSITIONS and
     equals today's `changed`.
5. **The shift.** If `alignment.inserted_indices`, ALWAYS call (whatever `committed_rows` holds):

   ```python
   SlideWriter().insert_pending_slides(
       session_id,
       alignment.inserted_indices,
       deck_spec=spec.to_json(),
       expected_rows=[(r.get("slide_id"), r.get("content_hash")) for r in committed_rows],
       created_by=initiated_by,
       mutation=_deck_mutation_context(
           session_id,
           state.get("graph_release_id"),
           operation="insert_slide",
           object_type="deck",
       ),
   )
   ```

   - `SlideRowsChangedError` → `_degrade_edit` with `insert_rows_changed`: "The deck changed while I
     was planning, so I have not added the slide. Nothing has been changed; please ask again."
   - Any other exception (re-raise `PersistedRuntimeError` via `_raise_if_persisted_runtime_failure`
     first) → `insert_rows_failed`: "I could not add the slide, so nothing has been changed. Please
     try asking again."
   - On success, log INFO with the inserted and revised positions.
   - This sits BEFORE `classify_spec_change` (`:1837`).
6. **`build_looks_like_insert`.** For `intent == "build"` with `prior_spec`, committed rows and not
   describe-only: if `align_slides(prior_spec.slides, spec.slides)` succeeds with
   `inserted_indices` non-empty and `revised_indices` empty, log a WARNING. Nothing else changes.
7. **Unchanged paths.** Describe-only turns get no alignment and no shift (today's behaviour).
   Build turns are otherwise untouched.
8. **The canonical `spec`** is what `updates["deck_spec"]` and the pre-fan-out write carry.

Steps:
- [ ] **Step 1 (test author).** Write new classes in `tests/unit/test_architect_insert_slide.py`,
  using `graph_env`, `seed_slides`, `make_spec` and `_edit_out`/`_revised`. Copy those two helpers
  and `_persist` from `test_graph_nodes.py:134-170,618-626`. Every row assertion is by marker HTML.
  - **Insert at 2 of 3.**
    - `architect_intent == "edit"` and `target_positions == [2]`.
    - `updates["deck_spec"]` has positions `0..3`, with the new brief at 2.
    - Rows are `[a, b, PENDING, c]` and `deck_spec_json` equals the canonical spec.
    - The model's `[3]` target is logged and ignored.
    - `build_branch_payload(merged, 2)` briefs the new slide.
  - **Insert + non-adjacent revision** → targets `[revised_new, inserted]`, and the revised brief
    reaches `build_branch_payload`.
  - **Append; two inserts; a spec-only deck** (no rows: the spec is written, no pending rows).
  - **Gapped equal-length** (rows and spec at `[0, 2, 5]`; the model revises position 5) → targets
    `[5]`, and `build_branch_payload(merged, 5)` briefs the revision. Revising 2 → targets `[2]`,
    with no exception.
  - **Gapped insert** (rows and spec at `[0, 2, 5]`; the model inserts after the first) → rows and
    spec become `0..3`, identity is kept by marker, and the targets are the new index.
  - **Top-of-node read failed:** monkeypatch `nodes._committed_slide_rows` to return `[]` while rows
    exist → `insert_rows_changed`, with rows, spec and version unchanged.
  - **Refusals:** ambiguous, moves, shrink and equal-length renumber → discuss with the code;
    rows/spec/version unchanged; the refusal said on both surfaces (pattern
    `test_graph_nodes.py:940-1005`).
  - **Shift failures:** `insert_pending_slides` monkeypatched to raise `SlideRowsChangedError` /
    `RuntimeError` → `insert_rows_changed` / `insert_rows_failed`, nothing changed, and
    `target_positions is None`.
  - **Deck-level change on an insert turn:**
    - `rereview_committed_slides` reviews each shifted slide with ITS OWN html and ITS OWN spec entry
      (assert by marker on the reviewer payload);
    - the pending row is not sent to the model;
    - the new position is in `target_positions`.
  - **Describe-only growth** persists the spec and shifts nothing.
  - **D5:** an insert "after slide 2" logs no `edit_ignores_references` warning.
  - **`build_looks_like_insert`:** a build spec equal to the persisted spec plus one new slide over
    existing rows logs the WARNING; a build that also revises a slide does not.
  - **Edit two existing tests, naming each in the report:**
    - drop the `adds-a-slide` param from
      `test_graph_nodes.py::TestAnEditCarriesItsRevisedSpec::test_an_edit_that_changes_the_position_set_is_refused`
      (its behaviour is now covered positively above);
    - in `test_f_a_degraded_edit_logs_nothing`, replace the grown spec with `make_spec((0, 1))`,
      which still gives `edit_spec_positions_changed`.

    Do not weaken any other assertion.
  - **Sabotage** (split between controller and reviewer):
    - targets by position → the first test goes red;
    - **`revised_indices` on the equal-length path → the gapped test goes red;**
    - shift only `if committed_rows` → the failed-read test goes red;
    - shift after `classify_spec_change` → the deck-level test goes red;
    - skip the re-stamp → `build_branch_payload` raises or briefs wrong;
    - honour the model's targets → red;
    - run the shift on describe-only → red.

  Confirm red. Leave uncommitted.
- [ ] **Step 2 (implementer).**
- [ ] **Step 3.**
  - Run `uv run pytest tests/unit/test_architect_insert_slide.py tests/unit/test_graph_nodes.py tests/unit/test_deck_level_spec_change.py tests/unit/test_architect_design_system_library.py tests/unit/test_agentic_layer_is_placed_and_gated.py -n 4 -q`,
    then the unit suite.
  - The integration suites (CI) must stay green. The stub architect
    (`tests/integration/conftest_stub_skills.py`) never grows a spec.

## Task 6: Graph-level acceptance — an insert keeps every existing slide intact and builds only the new one

**Models:** test=opus impl=opus (impl = fixing any defect this exposes in Tasks 2–5; no new feature)

**Files:** `tests/unit/test_graph_insert_slide_turn.py` (new)

Steps:
- [ ] **Step 1 (test author).** Use the compiled graph on `graph_env_threadsafe` (helpers as in
  `test_graph_builder.py:470-497`; `build_graph(checkpointer=False)`). No assertion pins a slide
  number inside a notice text (#332 owns notices); assert only that the notice row exists.
  - **Turn 1** builds `make_spec((0,1,2,3))`.
    - The builder emits `<h1>{slide_spec.purpose}</h1>`, so each row carries its marker.
    - The build reviewer returns a subjective `brief_not_delivered` finding on positions 1 and 3.
    - Then merge a judge verdict `{"marker": "JUDGE-purpose-2", "score": 90}` into row 2 with
      `SessionManager().write_slide_verification`, and set distinct `created_by`/`created_at`/
      `modified_by` per row in the DB.
    - Snapshot every row as `{marker: full row minus (position, id)}`, and snapshot the findings by
      id.
  - **Turn 2** (a distinct `turn_id`): the architect returns an edit whose spec inserts
    `purpose-NEW` at position 2 (positions re-stamped 0..4), with `target_positions=[2]`. Assert:
    - the builder and build-reviewer calls made in turn 2 are exactly for position `[2]`; there is
      no fixer call;
    - every old marker's row equals its snapshot as a whole dict (slide_id, html, scripts,
      authorship, verification record, fragment), not chosen keys;
    - the row order by marker is `[purpose-0, purpose-1, purpose-NEW, purpose-2, purpose-3]`;
    - the new row holds the built slide (not a placeholder by `is_placeholder_verdict`) and kept the
      pending row's `slide_id`;
    - in `get_slide_deck`, every finding's `slideIndex` points at the slide whose `content_hash` is
      in its id, and `slides[3]["verification"]["marker"] == "JUDGE-purpose-2"`;
    - `deck_spec_json` has positions `0..4`, and each old row's fragment `purpose` equals the spec
      entry at that row's position.
  - **Turn 3:** an ordinary edit that revises `purpose-3`'s brief at its NEW position 4.
    - It is accepted (not `spec_positions_stale`), and the builder is called only for 4.
    - The `purpose-3` row is rebuilt in place, and the other four rows are unchanged.
  - **Failure variant:** turn 2 with the builder raising (a plain exception) for position 2.
    - Position 2 holds the failed placeholder and a notice row exists.
    - All old rows equal their snapshots, rows equal the spec positions, and turn 3's edit is
      accepted.
  - **Turn dies after the shift (finding 15):** turn 2 with the builder raising a non-transient
    `PinnedInvocationEndpointError(endpoint_name="x", graph_release_id=1,
    agent_definition_revision_id=1)` with no cause, under `pytest.raises`.
    - Rows equal the spec positions, the new row is the pending placeholder (`is_placeholder_verdict`,
      `PENDING_SLIDE_TEXT`), and every old row equals its snapshot.
    - The next turn's edit targeting position 2 is accepted and builds it.
  - **Gapped deck (finding 1):**
    - Seed rows at positions 0, 2, 5 (with markers and records) directly, and persist
      `make_spec((0, 2, 5))`.
    - An insert after the first slide gives rows and spec `0..3` in marker order, every old row
      equal to its snapshot by marker, and a builder call only for index 1.
  - **`ask_data` loop (finding 7):**
    - The architect stub is a callable: `ask_data` on the first call, the insert edit on the second.
      The analyst stub is `AnalystOutput(outcome="success", synthesis="…", sources=["s"])`.
    - Exactly one `SharedDeckMutationEvent` has `operation == "insert_slide"`, and the builder is
      called only for the new position.
  - **Sabotage:**
    - (1) in `insert_pending_slides`, pass `NO_ATTRIBUTION` for moved rows → the by-marker equality
      goes red;
    - (2) snapshot only html/scripts/slide_id → red;
    - (3) targets by position → the call assertion goes red;
    - (4) remove Task 3's override → the findings assertion goes red;
    - (5) remove the spec write from the shift and make the pre-fan-out write raise → turn 3 is
      refused;
    - (6) map `old_to_new_index` by list position → the gapped test goes red.
- [ ] **Step 2 (implementer).** If any assertion is red because of Tasks 2–5, fix that code (not the
  test) and report the defect. A test that is wrong goes back to the test author with evidence.
- [ ] **Step 3.** Run `uv run pytest tests/unit/test_graph_insert_slide_turn.py -n 4 -q` three times
  (flake check), then the unit suite.

## Task 7: The polling route across an insert (pins D5's polling limit)

**Models:** test=opus impl=sonnet (no product change expected; impl fixes any defect in Tasks 2–3 the
test exposes)

**Files:** `tests/unit/test_poll_route_across_an_insert.py` (new)

Steps:
- [ ] **Step 1 (test author).** Write a FastAPI `TestClient(app, raise_server_exceptions=False)`
  test (pattern `tests/unit/test_slide_release.py:915-939`), but over REAL persistence.
  - **Setup.**
    - A SQLite engine with the production schema.
    - `get_db_session` patched in `session_manager`, `slide_repository` and `deck_level_writer` (the
      `_fake_db` pattern).
    - `src.api.routes.chat.get_session_manager` returns a real `SessionManager()`;
      `_require_chat_request_owner` is patched.
    - `src.services.identity_provider.resolve_display_names` returns `{}`, because the SCIM call
      hangs (`tests/unit/conftest_graph.py:425-430`).
    - Seed a session, a deck and rows A–D. Their `modified_at` is a fixed old date, outside the 2 s
      revision overlap.
    - `request_id = SessionManager().create_chat_request(sid)`.
  - **Poll 1:** `GET /api/chat/poll/{request_id}` → `slides` are A–D at positions 0–3,
    `slide_cursor == 4`. Keep its `revision_mark`.
  - **Shift:** `SlideWriter().insert_pending_slides(sid, [2], …)`.
  - **Poll 2:** `?slide_cursor=4&revisions_after=<mark>`. This is the **pinned mid-turn limit**:
    - `slides` == one entry at position 4 carrying D's HTML, and `slide_cursor == 5`;
    - `slide_revisions` == exactly the pending row at 2 (`PENDING_SLIDE_TEXT`);
    - C (now at 3) is NOT re-sent.
  - **Land:** `SlideWriter().write_slide(sid, 2, html=NEW…)`; poll 3's `slide_revisions` contains
    position 2 with NEW.
  - **A fresh client** (`slide_cursor=0`, no mark) after the shift receives all five rows in marker
    order `[A, B, NEW, C, D]`.
  - **Complete:**
    - `update_chat_request_status(rid, "completed")`;
    - `set_chat_request_result(rid, {"slides": ChatService().get_slides(sid)})`, which is exactly
      what `job_queue` stores from `COMPLETE` (`job_queue.py:158-163`; `chat_service.py:2128`);
    - the next poll's `result["slides"]["slides"]` is in marker order `[A, B, NEW, C, D]` with `index`
      0–4, and its `deck_spec` positions are 0–4.
  - **Sabotage:** give the shift `now_dt=datetime.utcnow()` (bumping `modified_at`) → poll 2's
    revisions include C and D, and the pinned-limit assertion goes red. That proves the test watches
    the attribution-preserving behaviour.
- [ ] **Step 2 (implementer).** Green without editing the test. A red caused by product code goes
  back to Tasks 2–3.
- [ ] **Step 3.** Run `uv run pytest tests/unit/test_poll_route_across_an_insert.py tests/unit/test_slide_release.py -n 4 -q`.

## Task 8: Eval yardstick — production-semantics insert scoring, and calibration by case

**Models:** test=opus impl=sonnet (it changes the yardstick, so it must land before Task 10)

**Files:** `evals/harness/scorers.py`, `evals/harness/mlflow_run.py`, `evals/harness/judge.py`,
`evals/run_eval.py`, `tests/unit/evals/{test_scorers,test_mlflow_run,test_judge,test_run_eval}.py`

Behaviour (D10):
- **`build_dataset`** (`mlflow_run.py:108-120`) adds `"current_deck_spec"` for architect cases whose
  payload has one.
- **`expected_category` wrapper** (`:187-192`) passes `reference=expectations.get("reference")` and
  `current_deck_spec=expectations.get("current_deck_spec")`.
- **`expected_category_score(agent_key, structured, expect, *, reference=None,
  current_deck_spec=None)`.**
  - It imports `align_slides` from `src.domain.slide_alignment` and validates both specs with
    `DeckSpec`.
  - Fail rationales start `"Insert: "`: a missing input; no or invalid `deck_spec`; `production would
    refuse (<code>)`; `inserted <got> != <want>`; `revised <got> != <want>`; `deck-level field <f>
    changed (production re-reviews every slide)`.
  - The pass rationale appends `; model target_positions <got> differ from <want> (production
    ignores them on an insert)` when they differ.
- **`judge.calibrate(..., case_filter: list[str] | None = None)`.** `run_eval` parses `--cases`
  before the calibrate branch and passes it on.

Steps:
- [ ] **Step 1 (test author).** Scorer table over a small current spec and a reference:
  - **(a)** a correct insert whose targets are in the OLD numbering → **PASS**, with the note in the
    rationale;
  - **(b)** an insert that leaves the requested revision unchanged, with targets `[8, 10]` → **FAIL**
    (`revised`);
  - **(c)** a correct insert that also changes `narrative_arc` → **FAIL** (deck-level);
  - an untouched slide changed in one field (`hands_off`) → FAIL (`revised`);
  - replaced instead of inserted (equal length) → FAIL (`inserted`);
  - an ambiguous spec → FAIL (`production would refuse`);
  - a gapped-but-ordered candidate → PASS;
  - no `deck_spec` → FAIL; `inserted` without a reference or current spec → FAIL;
  - every existing non-insert case, and `test_intent_report.py`'s call, unchanged.

  Also:
  - **Pin:** the scorer's deck-level tuple equals `nodes._DECK_LEVEL_FIELDS`.
  - **Wrapper test** (pattern `test_mlflow_run.py:412-424`): the reference and the current spec
    reach the scorer; `build_dataset` omits `current_deck_spec` for a deck-less case; and the keys
    stay disjoint from the scorer names (`:272-277`).
  - **Calibrate filter:** only the named cases are judged (a stub judge counts the calls), and
    `--calibrate --cases a,b` reaches `calibrate`.
  - **Sabotage:**
    - compare targets instead of `revised` → (a) and (b) go red;
    - drop the deck-level check → (c) goes red;
    - ignore `case_filter` → the call count goes red.

  Confirm red. Leave uncommitted.
- [ ] **Step 2 (implementer).**
- [ ] **Step 3.** Run `uv run pytest tests/unit/evals -n 4 -q`.

## Task 9: Eval cases — four insert cases per split, generated

**Models:** test=opus impl=sonnet (the content is below and in Appendix H; one agent writes both
splits and may read held-out)

**Files:**
- `evals/packs/architect/{mutations.py,heldout.py}`;
- 4 new dirs under `cases/` and 4 under `cases_heldout/`;
- `tests/unit/evals/{test_pack_architect,test_pack_architect_heldout,test_cross_split,test_pack_generation_isolation}.py`;
- `evals/README.md` (two count sentences).

Behaviour:
- Payloads are built by the existing `_payload` (production `architect_slide_payload`), with the shape
  unchanged. The 9 existing case dirs per split stay byte-identical.
- All 8 new cases are `kind: mutation` with `design_system_active: true` and the same prior exchange
  as the existing deck cases. `HAS_DECK` gains the ids.
- `expect = {"intent": "edit", "positions": [...all targets...], "inserted": [...new...]}`.
- References are full `ArchitectOutput`s:
  - `deck_spec` is the gold spec with the new `SlideSpec`(s) spliced in and positions re-stamped,
    plus only the named revision;
  - deck-level fields are unchanged;
  - new slides have `data_references: []`, `slide_type: null`, `template_section_index: null`.
- NEW helpers in the train module, reused by held-out:
  - `_inserted_spec(deck, inserts: dict[int, dict], briefs: dict[int, str] | None = None) -> dict`
    (keys are FINAL positions; validated with `DeckSpec`);
  - `_retargeted(reference, targets) -> dict`.

  New briefs are module constants.

Train cases (deck `evals/fixtures/meridian/deck_spec.json`, 10 slides):

| id | message (exact) | expect | new slide(s) at final position | should_fail |
|---|---|---|---|---|
| `add_slide_anchor` | `Add a slide after slide 3 that compares Reveal.js, Slidev and Marp side by side` | positions [3], inserted [3] | **3:** purpose `Compare the leading HTML slide frameworks side by side`; brief `Comparison table of Reveal.js, Slidev and Marp across authoring format, interactivity, theming and export options, one column per framework`; assumes `The audience has just met HTML slides and heard the leading frameworks named`; hands_off `Whichever framework a team picks, the case for HTML slides holds`. **Message:** `I'll add a new slide 4 comparing Reveal.js, Slidev and Marp side by side, straight after slide 3.` | **judge-only:** right place (3), targets [3], but an off-request new slide: purpose `Recount the history of PowerPoint`, brief `Timeline of PowerPoint releases from 1987 to today, one milestone per version` |
| `add_slide_end` | `Add a final slide that lists the sources behind the evidence` | [10], inserted [10] | **10:** purpose `Appendix — the sources behind the evidence`; brief `Bulleted list of the sources behind the five evidence beats, one line per beat: responsiveness, typography, interactivity, accessibility and collaboration`; assumes `The audience has heard the verdict and may want to check the evidence`; hands_off `Every claim in the deck can be traced to a source`. **Message:** `I'll add a final slide, slide 11, listing the sources behind the evidence.` | the last slide replaced: targets [9], 10 slides with position 9 = the sources slide |
| `add_slide_as_number` | `Insert a new slide 2 with an agenda for the talk` | [1], inserted [1] | **1:** purpose `Set out the agenda for the talk`; brief `Agenda slide listing the five narrative beats in order: why the tool matters, PowerPoint's limits, the evidence for HTML slides, the objections, and the verdict`; assumes `The audience has seen the title and knows the topic`; hands_off `The talk moves from the problem, through the evidence, to a verdict`. **Message:** `I'll insert a new slide 2 with the agenda for the talk; the current slide 2 becomes slide 3.` | inserted one place late: targets [2], agenda at position 2 |
| `add_slide_and_revise` | `Add a slide after slide 8 on offline use and security, and add it to the summary on the last slide` | [8, 10], inserted [8] | **8:** purpose `Evidence beat 6 — Offline use and security`; brief `Show that HTML slides run offline as one self-contained file and can be served from an access-controlled internal site, with no macros or embedded executables, as three short bullets and a callout`; assumes `The audience has seen the collaboration and distribution advantages`; hands_off `HTML slides are safe to share and work without a network`. **Revision at 10 (gold 9):** the gold brief with `five advantage dimensions — responsiveness, typography, interactivity, accessibility, collaboration —` replaced by `six advantage dimensions — responsiveness, typography, interactivity, accessibility, collaboration, and offline use and security —`. **Message:** `I'll add slide 9 on offline use and security after slide 8, and add it to the summary on the last slide, now slide 11.` | added but the summary not revised: targets [8], spec with only the insert |

`fault` sentences name the trap. For example: "add after slide 3 (position 2): the new slide is
position 3, only it is built, and the later slides shift unchanged". For `add_slide_and_revise`, the
fault also says that the gold `narrative_arc` lists five dimensions and must stay unchanged.

Held-out cases: **Appendix H**.

Steps:
- [ ] **Step 1 (test author).** In both pack test files, make every one of these edits explicitly
  (finding 10). Do not "fix" a red test by weakening it.
  - **Lists:**
    - `CASE_IDS` has 13 entries;
    - add `INSERT_CASES`;
    - `EXPECT` gains `inserted`;
    - add `JUDGE_ONLY_CALIBRATION = {"add_slide_anchor"}`;
    - extend `NEW_CASE_IDS` (the list behind `test_new_cases_continue_the_existing_prior_exchange`)
      with the insert ids;
    - rename the existing count tests.
  - **`test_reference_validates_and_passes`** (`test_pack_architect.py:239-245`; held-out `:270`):
    pass `reference=c.reference, current_deck_spec=c.payload["current_deck_spec"]`.
  - **`test_calibration_should_fail_is_wrong_and_valid`** (`:289-296`; held-out `:455`): pass both
    kwargs so it is not vacuous. For `JUDGE_ONLY_CALIBRATION`, assert instead that the scorer PASSES
    the should_fail, because only the judge separates it.
  - **`test_calibration_has_the_wrong_intent`** (`:299-302`): exclude `INSERT_CASES`, whose
    should_fails are edits.
  - **`test_resolved_references_equal_the_expected_edit_positions`** and
    **`test_edit_references_revise_only_their_targets`:** exclude `INSERT_CASES`.
  - **`test_messages`:** pin the 4 new messages per split.
  - **NEW `test_insert_references_are_unambiguous_to_production`:**
    - `align_slides(gold.slides, reference.deck_spec.slides)` gives
      `inserted_indices == expect["inserted"]` and `revised_indices == positions − inserted`;
    - every slide outside `positions` equals its gold slide ignoring position;
    - deck-level fields equal the gold's.
  - **NEW `test_insert_anchors`** (train): the anchor case's refs == `[inserted − 1]`; as_number refs
    == `inserted`; the end refs == `[]`; and_revise refs == `[inserted − 1, last old position]`.
  - **Pinned `slide_references` (train):** anchor → `slide 3` [3]→[2]; end → `[]`; as_number →
    `slide 2` [2]→[1]; and_revise → `slide 8` [8]→[7], then `last slide` [10]→[9].
  - **Markers (train):**
    - the anchor brief names all three frameworks;
    - the end purpose starts `Appendix`;
    - the agenda brief contains `five narrative beats`;
    - the revised summary contains `six advantage dimensions` and `offline use and security`;
    - the judge-only should_fail's brief does not mention any of the three frameworks.

    Held-out markers are in Appendix H.
  - **Fairness on the train gold:**
    - the position 2 brief names `Reveal.js, Slidev, Marp`;
    - no gold purpose contains `agenda`, `Appendix` or `Offline`;
    - the position 7 purpose starts `Evidence beat 5`;
    - the position 9 brief contains `five advantage dimensions`;
    - `narrative_arc` beat 3 lists the five dimensions.
  - **Split pins:** add the ids to `test_cross_split.py`, with a total of 47.
    `test_pack_generation_isolation.py` becomes `{"architect": 13}`.
  - **Sabotage:**
    - change one brief constant → `test_committed_cases_are_current` goes red;
    - put the new slide one place late in a reference → the production-alignment test goes red.

  Confirm red. Leave uncommitted.
- [ ] **Step 2 (implementer).**
  - Generate with `uv run python -m evals.packs.architect.mutations` and
    `uv run python -m evals.packs.architect.heldout`.
  - README: on line 12, "Five per agent (nine for the architect), 39 in total" becomes "(thirteen for
    the architect), 47 in total"; line 86 changes likewise.
- [ ] **Step 3.**
  - Run `uv run pytest tests/unit/evals -n 4 -q`.
  - `git status --porcelain evals/packs/architect` shows only the 8 new dirs and the two generators.
  - `git diff --exit-code` over the 9 existing dirs per split exits 0.

## Task 10 (SUPERVISOR-run): calibrate, then measure BEFORE on the shipped prompt

**Models:** test=sonnet impl=sonnet (SUPERVISOR-run; a delegated read-out uses sonnet)

Preconditions:
- Tasks 1, 8 and 9 are committed.
- Run from the issue-314 worktree root (`mlflow.db` is per worktree), with the default
  `--profile tellr-dev`.

Let `INSERTS=add_slide_anchor,add_slide_end,add_slide_as_number,add_slide_and_revise` and
`EXISTING=build_request,edit_request,ask_data,confirm_design,discuss,edit_polite_ordinal,edit_last_slide,edit_multi_slide,discuss_slide_question`.

- [ ] **C1** `uv run python -m evals.run_eval --agent architect --calibrate --cases $INSERTS`; **C2**
  the same with `--split heldout`.
  - All four must be trusted per split. Re-run only judge-error rows.
  - A misclassified case STOPS this task and returns to Task 9.
- [ ] **B1** `… --config v1-baseline --repeats 2 --cases $INSERTS`.
- [ ] Project the total from B1's measured tokens (formula below). Apply the drop order if the
  projection exceeds USD 13.
- [ ] **B2** `… --config v1-baseline --repeats 1 --cases $EXISTING`.
- [ ] **B3** `… --config v1-baseline --split heldout --repeats 1 --cases $INSERTS`.
- [ ] Run `uv run python -m evals.intent_report --run-id <id>` for each run (held-out: the aggregate
  line only).
- [ ] **Ledger** (`~/tellr-loop/issues/issue-314/`): for each run record the run id, sha,
  `cases_digest`, rows, pass rate, per-case results (train only), intent and position accuracy, judge
  errors, tokens and USD.
  - Group the train failures by cause from the rationales.
  - Hand the B1 and B2 run ids (train) to Task 11.

## Task 11: Prompt candidate (TRAIN ONLY; a separate agent; the supervisor runs every sweep)

**Models:** test=opus impl=opus (design judgement on a pinned artefact)

Give the candidate author **exactly this brief** and nothing else from this plan:

> You are improving the Tellr **architect** v1 prompt so it can add slides to an existing deck. Load
> `.claude/skills/optimise-agent-prompt/SKILL.md` and follow it, with these overrides. The whole
> issue is capped at USD 15, at about USD 0.2 per row, and that cap is the reason for (3) and (4):
> 1. **You never run `evals.run_eval`.** The supervisor runs each sweep and hands you the run id.
> 2. The spend cap is the supervisor's. Propose at most 3 candidates.
> 3. The finalist is confirmed at ×3 on the four add-slide train cases and ×1 on the nine other
>    train cases, not at ×5 on all train cases.
> 4. Held-out is scored once at ×1, not ×3.
>
> **Forbidden reads:**
> - everything under `docs/superpowers/plans/`;
> - `evals/packs/architect/cases_heldout/`, `evals/packs/architect/heldout.py`,
>   `tests/unit/evals/test_pack_architect_heldout.py`;
> - `evals/fixtures/**/heldout/`;
> - every `__pycache__` directory;
> - everything under `~/tellr-loop/`;
> - the MLflow experiment `tellr-agent-eval-heldout`;
> - `git show`/`git log -p` of commits touching those paths.
>
> Every repo-wide grep uses `--exclude-dir=cases_heldout --exclude-dir=__pycache__
> --exclude-dir=heldout`.
>
> **The issue (#314).** "In the agent (graph) path a user cannot ask for a new slide to be added to an
> existing deck ("add a slide on X after slide 3"). An edit turn rewrites `target_positions`; nothing
> inserts a new position or shifts the ones after it." Acceptance: an add request produces an
> updated `deck_spec` with the new `SlideSpec` at the requested position (or appended), later
> positions shifted, and only the new slide built.
>
> **What the code now does with an edit.**
> - If the returned `deck_spec` has more slides than `current_deck_spec`, the node matches the
>   current slides to the returned ones in order, field for field, ignoring `position`.
>   - Unmatched returned slides are new; matched slides that differ are revised.
>   - It builds ONLY the new and the revised slides, whatever `target_positions` says, and
>     re-numbers positions 0..n.
> - So every slide the user did not ask about must be copied exactly, every field, with only its
>   `position` changed.
> - It refuses the edit if it cannot tell which slide was revised and where the new one goes, or if
>   an existing slide's content moved.
> - A change to the deck-level fields (audience, purpose, argument, call_to_action, narrative_arc)
>   re-reviews every slide.
> - The payload is unchanged (`slide_numbering`, `slide_references` as before). In "add a slide after
>   slide 3", the reference to "slide 3" is where the new slide goes, not a slide to change.
>
> **Product rule.**
> - With no stated place, the new slide goes where it fits the argument: before a closing or
>   call-to-action slide, unless the new slide is itself a closing slide. The message says where it
>   went.
> - When the user explicitly asks for the end of the deck, the new slide goes after the last slide.
>
> **Properties every candidate must have.** Write the wording yourself, from the issue text, the
> product rule and the train failures. Do not write a list of user phrasings.
> 1. Adding slides to an existing deck is an edit.
> 2. The new slide goes where the user asks, by the product rule when no place is stated.
> 3. Slide numbers in the request are read against `slide_numbering`, i.e. the deck before the
>    insert.
> 4. Every slide after the new one is copied unchanged except that its position goes up by one, and
>    no other slide (and no deck-level field) changes unless the user asks.
> 5. `target_positions` are the positions, in the returned `deck_spec`, of every new slide and every
>    slide the user asked to change.
> 6. Removing or reordering slides stays `discuss`.
> 7. A slide the user names when adding is where the new slide goes, not a target. SLIDE NUMBERS
>    tells the model to take `target_positions` from `slide_references`, so it needs this exception.
>
> **Where to change the prompt.** Rewrite the EDITING block. Its sentence "Adding or removing slides
> is not an edit: …" must go; keep "if the user asks for that, use discuss and explain that it cannot
> be applied as an edit" for removing/reordering. Add the anchor exception to SLIDE NUMBERS.
>
> **Candidate A, `add-slide` (required).** Copy `src/core/skills/architect.py` `INSTRUCTIONS` into
> `evals/configs/architect/add-slide.md` (no trailing newline: the file is read verbatim) and make
> those two changes. Write `add-slide.yaml`:
>
> ```yaml
> agent_key: architect
> name: add-slide
> base: v1
> prompt_file: add-slide.md
> ```
>
> **Candidates B and C (optional).** Each is aimed at ONE cause seen in the train failures, for
> example an add classified as `build`, neighbours rewritten, or a deck-level field changed. State a
> rule; never quote or paraphrase a case message. A candidate may change the INTENT CLASSIFICATION
> `edit` line; its block hash is pinned, so say so if you do.
>
> **Keep these (pinned by unit tests):**
> - "14 to 20 slides"; "reusable layouts, not a one-of-each menu"; "its slide_type must equal the
>   label of the template_sections entry";
> - "start from current_deck_spec", "return it in full", "revise only what the user asked for on the
>   target slides", "keep every slide's position and every other slide unchanged" (you may qualify
>   it, e.g. "…, except that adding a slide moves the slides after it"), "change deck-level fields
>   only when the user asks";
> - the design_contract and resolved_data sentences;
> - every PAYLOAD RULES line; the SLIDE NUMBERS rules; the VISUAL / TEMPLATE BINDING rules.
>
> The prompt must never say "non-null", and never "reject" inside PAYLOAD RULES. The opening, DESIGN
> SYSTEMS and closing blocks stay byte-identical. Run `uv run pytest
> tests/unit/test_architect_edit_prompt.py -q` against a scratch copy if useful. Only the
> manifest-equality tests and the retired "adding or removing" pin may fail.
>
> **Train cases:** `add_slide_anchor`, `add_slide_end`, `add_slide_as_number`,
> `add_slide_and_revise`, plus the nine others in `evals/packs/architect/cases/`. The deterministic
> `expected_category` scores an add with the production matching above. It does not fail a row for
> `target_positions`, but notes a mismatch.
>
> **Hand-over:** per the skill. For each candidate give its name, `content_hash`, targeted cause and
> train results (pass rate, intent and position accuracy, per-case `expected_category` rationales),
> then recommend a finalist.

## Task 12 (SUPERVISOR-run): search sweeps, the finalist, the accept decision

**Models:** test=sonnet impl=sonnet (SUPERVISOR-run)

- [ ] **S1** `… --config evals/configs/architect/add-slide.yaml --repeats 1 --cases $INSERTS`. Hand
  the run id to Task 11. **S2** (P3) runs B/C on the cases each targets.
- [ ] **F1** `… --config <finalist> --repeats 3 --cases $INSERTS`.
- [ ] **F2** `… --config <finalist> --repeats 1 --cases $EXISTING`.
- [ ] **F3** `… --config <finalist> --split heldout --repeats 1` (all 13). Report the aggregate line
  and the `intent_report` aggregates only; per-case held-out numbers stay in MLflow.
- [ ] Apply the accept rule (Measurement section).
  - Accepted → Task 13.
  - Not accepted → STOP, branch (ii) (D14), no promotion.
  - Ledger the decision and the skill overrides used.

## Task 13: Promote the finalist as the code default

**Models:** test=opus impl=opus (frozen manifest and pinned hashes; pin literals are recomputed by
running code, never guessed)

**Files:**
- `src/core/skills/architect.py`;
- via promote: `src/services/agent_definition_manifest_v1.py`,
  `tests/unit/test_packaged_release_loader.py:24`, `tests/unit/test_graph_definition_manifest.py:707`;
- by hand: `tests/unit/test_graph_definition_manifest.py:1159-1161`,
  `tests/unit/test_architect_edit_prompt.py`;
- `tests/agentic/test_rc2_architect_identifies_add_intent.py`,
  `tests/agentic/test_rc9_architect_add_with_slide_reference.py`.

Steps:
- [ ] **Step 1 (test author).** The test author has not read Appendix H and writes nothing that
  enumerates user phrasings.
  - In `test_architect_edit_prompt.py`, retire the pin "adding or removing slides is not an edit" in
    `EDITING_RULE_PHRASES`. Add the FINALIST's own sentences for properties 1 and 6 as phrase pins.
  - Add `INSERTION_RULES`: one regex per property 2–5 and 7 of Task 11's brief, over the plain
    EDITING / SLIDE NUMBERS blocks. Write each against the finalist's actual sentences, after
    Task 12, in the style of `SLIDE_NUMBERS_RULES` (one sentence each, so deleting a sentence turns
    only its own rule red).
  - Every existing test still passes on the finalist.
  - Update the layer-3 RC2/RC9 tests to the new contract (live; not run in CI):
    - intent `edit`;
    - `len(deck_spec.slides) == committed + 1`;
    - `target_positions` == [the new slide's position];
    - every other slide equal to the input's, ignoring position;
    - RC9 (an anchored add): the new slide straight after the named slide;
    - RC2 (no stated place, deck ending in a "close" slide): the new slide before that closing slide
      (the product rule).
  - Spot-check `test_rc12_architect_asks_add_or_replace.py` against the finalist text. A generation
    request on an existing deck must still ask; update only its docstring if the finalist changes
    that.
  - Confirm red against the current `INSTRUCTIONS`. Leave uncommitted.
- [ ] **Step 2 (implementer).**
  - Set `INSTRUCTIONS` to the finalist `.md` as a parenthesised literal. Verify with
    `uv run python -c "import src.core.database; from src.core.skills.architect import INSTRUCTIONS as I; import pathlib; assert I == pathlib.Path('evals/configs/architect/<finalist>.md').read_text()"`.
  - Run `uv run python -m evals.harness.promote --config architect=evals/configs/architect/<finalist>.yaml --run-id architect=<F1 run id> --dry-run`,
    then the same without `--dry-run`. There must be no "Skill body drift" line.
  - Hash pins, recomputed by running code:
    - `HEAD_ARCHITECT_CONTENT_HASH` = the finalist hash (comment "then for #314 add a slide");
    - `test_graph_definition_manifest.py:1159-1161`: run
      `uv run pytest "tests/unit/test_graph_definition_manifest.py::test_hashing_rejects_non_string_object_keys_inside_guidance" -q`
      and paste the computed value (comment naming #314);
    - `HEAD_UNCHANGED_BLOCK_HASHES` only if INTENT CLASSIFICATION changed.
  - Do not re-record `frontend/tests/fixtures/graphLifecycleContract.json` (#313 precedent); say so
    in the commit message.
- [ ] **Step 3.**
  - Run `uv run pytest tests/unit/test_architect_edit_prompt.py tests/unit/test_graph_definition_manifest.py tests/unit/test_packaged_release_loader.py tests/unit/test_graph_configuration_bootstrap.py tests/unit/test_skill_prose.py tests/unit/test_prompt_assembler.py tests/unit/test_retained_bundle_ledger.py tests/unit/test_persisted_agent_runtime.py tests/unit/test_graph_lifecycle_playwright_contract.py -n 4 -q`,
    then the unit suite.
  - `test_zz_real_artefacts_unchanged_versus_head` is red until the commit, then green.
  - `test_schema_contract_digests_unchanged` and `test_other_roles_definitions_unchanged` pass.
  - Report the old (`ffc3074dc920…`) and new hashes and both hand-updated literals.

## Task 14: Mocked Playwright spec — the deck after an insert turn (SSE)

**Models:** test=opus impl=haiku (no product code; impl only wires the CI matrix)

**Files:** `frontend/tests/e2e/agent-insert-slide.spec.ts` (new), `.github/workflows/test.yml`
(`e2e-tests.strategy.matrix.test`, after `agent-definition-workbench`)

- [ ] **Step 1 (test author).** Mirror `frontend/tests/e2e/incremental-slide-delivery.spec.ts`
  (`setupMocks`, `goToGenerator`, its SSE body builder). SSE only: the polling transport cannot be
  forced on localhost, and Task 7 covers it at the route.
  - **Start:** a 3-slide deck (markers A, B, C; `deck_spec` positions 0–2; one finding stamped for B).
  - **The turn** "Add a slide after slide 1" delivers `slide_ready` for position 1, then `complete`.
    - `complete` carries `slides` = the shifted deck, as production does (`chat_service.py:2128`).
    - The mocked `GET …/slides` returns the same deck: `[A, NEW, B, C]`, a higher `version`,
      `deck_spec` positions 0–3 with NEW at 1, and B's finding with `slideIndex: 2`.
  - **Assert after `complete`:**
    - 4 slides;
    - `ribbon-thumb-1` shows NEW and `ribbon-thumb-2` shows B (`SlideViewer/ThumbnailRibbon.tsx:90`);
    - the Spec view labels NEW's entry "Slide 2";
    - the feedback drawer shows B's finding on the third slide and none on the second.
  - Do not assert the mid-turn view (D5 known limit).
  - **Sabotage the product, not the mock:** remove the `onSlidesGenerated` calls from ChatPanel's
    `complete` handler (`ChatPanel.tsx:296-303`) → red. Swapping the refetch for `event.slides` stays
    green by design, since both are the server's final deck, so it is not a valid sabotage.
- [ ] **Step 2 (implementer).** Add `agent-insert-slide` to the matrix
  (`tests/unit/test_e2e_matrix_covers_specs.py` enforces it).
- [ ] **Step 3.** Run `cd frontend && npx playwright test tests/e2e/agent-insert-slide.spec.ts` and
  `uv run pytest tests/unit/test_e2e_matrix_covers_specs.py -q`.

## Task 15: Docs

**Models:** test=sonnet impl=sonnet ("test" is the reviewer's checklist: no held-out phrasing, every
symbol named exists, and the numbers match the ledger)

- [ ] **`CONTEXT.md` `## Language`:**
  - **Slide Insertion**: an edit whose revised spec has more slides than the deck. New slides go
    where the user asked, later slides shift their Slide Position and Slide Number, and only new and
    revised slides are built. The node derives it by aligning the revised spec to the current one,
    and refuses when that is ambiguous. _Avoid_: add intent, build.
  - **Pending Slide**: the placeholder row an insertion commits at a new position until its slide
    lands. _Avoid_: blank slide.
- [ ] **`docs/technical/backend-overview.md`:** replace the "For #314" list with "Adding a slide
  (#314)":
  - D1 alignment, both numberings and the refusal codes;
  - D3 targets;
  - D4 shift, transaction and failure guarantee, including the stale `slide_count`/`html_content`
    after a dead turn;
  - D7/D8/D9;
  - D5 transports, the mid-turn and error-path limits;
  - D6 and the product rule;
  - the pending-slide copy;
  - `build_looks_like_insert`;
  - the RC2/RC9 contract change.
- [ ] **`evals/README.md`:**
  - the production-semantics insert check and `current_deck_spec` in "Scorers";
  - `--calibrate --cases`;
  - a note that `intent_report`'s position accuracy on insert rows reflects targets that production
    ignores;
  - a dated section, "Architect: add a slide (#314)", with:
    - the case ids and what each tests (no held-out phrasing);
    - the B/S/F table (split, cases, repeats, pass rate, intent/position accuracy, judge errors,
      tokens, USD);
    - the causes;
    - the skill overrides and their budget reason;
    - the D14 branch;
    - held-out aggregates only.
- [ ] Optional (rebase over #330–#334 first): one paragraph in
  `docs/user-guide/01-generating-slides.md` on asking for a new slide.

---

## Measurement plan and budget (cap USD 15 for the issue)

**Cost basis** (#313 ledger ruling):
- Agent opus-5 at USD 5/25 per M in/out; judge `databricks-claude-sonnet-5` at ≈ USD 0.035 per call.
- `prices.yaml` has no opus-5 entry (do not add one), so
  `USD ≈ rows × (mean_in × 5 + mean_out × 25)/1e6 + judge_calls × 0.035`.

Planning rates per row (#313 table, plus 11-slide insert outputs):

| Row type | ≈ USD |
|---|---|
| Train insert | 0.19 |
| Train edit | 0.185 |
| Train discuss / confirm | 0.105 |
| Train build (no deck) | 0.287 |
| Train ask_data | 0.087 |
| Held-out insert | 0.15 |
| Held-out existing 9 cases, total (#313 B4 plan) | 1.24 |

The 9 existing train cases at ×1 cost ≈ USD 1.43.

| ID | Task | Run | Agent rows | ≈ USD | Priority |
|---|---|---|---|---|---|
| C1 | 10 | calibrate train, 4 insert cases | 0 (8 judge) | 0.28 | P1 |
| C2 | 10 | calibrate held-out, 4 insert cases | 0 (8 judge) | 0.28 | P1 |
| B1 | 10 | v1-baseline, train insert ×2 | 8 | ≤ 1.52 (≈ 0.84 if all discuss) | P1 |
| B2 | 10 | v1-baseline, all 9 existing train ×1 | 9 | 1.43 | P2 |
| B3 | 10 | v1-baseline, held-out insert ×1 | 4 | ≤ 0.60 | P1 |
| S1 | 12 | `add-slide`, train insert ×1 | 4 | 0.76 | P1 |
| S2 | 12 | candidates B/C, targeted ×1 | ≤ 4 | ≤ 0.76 | P3 |
| F1 | 12 | finalist, train insert ×3 | 12 | 2.28 | P1 |
| F2 | 12 | finalist, all 9 existing train ×1 | 9 | 1.43 | P1 |
| F3 | 12 | finalist, held-out all 13 ×1 | 13 | 1.84 | P1 |

- **Totals.** Base without S2: **≈ USD 10.42**. With S2: ≈ 11.18. Margin ≥ USD 3.8 for judge-error
  re-runs and another candidate sweep.
- **Drop order** (if B1's measured cost projects the total above USD 13): S2, then B2. Without B2,
  the BEFORE for the existing cases is #313's F1/F2/F3 runs of the same prompt on byte-identical case
  files with the same judge (issue-313 `mlflow.db`, NOTES table). Never drop C1, C2, B1, B3, F1, F2
  or F3. A run that would cross the cap waits for the user.
- **Overrides of `optimise-agent-prompt`, recorded here and in the ledger** (budget reason: USD 15 at
  ≈ USD 0.2 per row):
  - the finalist is confirmed at ×3 on the insert cases plus ×1 on the 9 existing cases (the skill
    says ×5 on all train);
  - held-out runs at ×1 (the skill says ×3; #313 precedent);
  - the candidate author runs no sweeps.
- B runs measure `v1-baseline` = the promoted `slide-refs` prompt (`ffc3074dc920…`) on the same
  payloads as the F runs. No payload key is added, so there is no regeneration and no S0.
- B1 is ×2 against F1 ×3 on purpose. The shipped EDITING rule answers an add with `discuss`, so B1 is
  expected at the floor; F1 needs the third repeat for its per-case rule.

**Accept rule (fixed before any F run).** The finalist is accepted only if ALL of these hold:
1. **F1:** the pass rate is ≥ 0.75, every insert case passes ≥ 2 of 3, and F1's pass rate is higher
   than B1's.
2. **F2:** passes ≥ 8 of 9 and ≥ B2's passes − 1 (or, if B2 was dropped, ≥ the #313 per-case record
   − 1), with no `contract` failure.
3. **F3:** the 4 held-out insert cases pass ≥ 3 of 4 and more than B3; the 9 existing held-out cases
   pass ≥ 8 of 9 (#313's F4 was 9/9 at ×1).

Otherwise STOP: no promotion; branch (ii) (D14).

## CI wiring

- New tests under `tests/unit/` run in the unit job (`.github/workflows/test.yml:132-138`,
  `-n auto`). This includes the polling route test, which uses SQLite and a TestClient.
- `tests/unit/test_insert_pending_slides_postgres.py` is **CI-only**: `pytest.mark.postgres`, run by
  the unit job's Postgres service via `TELLR_TEST_POSTGRES_URL`. It self-skips locally.
  `test_ci_exports_postgres_test_url.py` requires `>= 6` marked modules, so adding one is safe.
- The integration suites (CI-only, Postgres) are not edited and must stay green; the reviewer
  checks the CI run.
- The new Playwright spec is added to the e2e matrix (Task 14). The e2e job runs because
  `frontend/**` changed.
- Live evals and `tests/agentic/` (layer 3, disabled at `test.yml:1003-1048`) are not CI.

## Docs to update

`CONTEXT.md`, `docs/technical/backend-overview.md` and `evals/README.md` (Task 15; the count
sentences in Task 9). Optionally `docs/user-guide/01-generating-slides.md`. No new doc files.

## Out of scope

- Deleting or reordering slides on the agent path (still refused).
- A deterministic insertion-anchor payload key (follow-up if F1 shows anchor slips).
- A mid-turn client refresh after a shift, and a refetch on `error` (follow-ups; they need
  ChatPanel/AppLayout changes).
- The UI routes' display-name write-back into `created_by`; `duplicate_session` copying a stale blob
  for graph decks (follow-ups).
- A UI mutation during a running graph turn (pre-existing for every edit turn).
- `ArchitectOutput`, `DeckSpec`/`SlideSpec`, `slide_numbering.py`, judge prompts, `prices.yaml`.
- Re-recording the lifecycle contract fixture.
- #318, #316, #319, #321, #323, #317.
- Review NITs 21 (restoring whitespace-only neighbour diffs) and 22 (duplicate-like inserts):
  parked.

## Risks

- **Mis-attribution on the shift (§7).** Mitigated by:
  - one writer (`_rewrite_slide_rows`) and exact attribution;
  - a re-read precondition;
  - by-marker whole-row tests at helper level (Task 2, including gapped and NULL-author rows),
    graph level (Task 6) and route level (Task 7);
  - the whole-branch review's writer-by-writer table.
- **The model answers an add with `build`.** Every slide is rebuilt and identities stay by position,
  so later slides are mis-attributed (pre-existing build semantics). `build_looks_like_insert`
  measures it in production; the eval fails it.
- **The model rewrites neighbours or a deck-level field.** They are rebuilt or re-reviewed:
  consistent, but costly. The prompt forbids it, and the scorer fails it.
- **Ambiguity refusals annoy users.** They happen only when a revision touches a slide adjacent to
  the insert with a changed purpose or brief. The message says what to do. No eval case measures it.
- **Duplicate-like inserts** (review NIT 22, parked): an agent "duplicate slide N", or adjacent
  UI-inserted blank entries (`_BLANK_DECK_SPEC_ENTRY`, `chat_service.py:71-77`), give identical
  entries. The alignment then returns `ambiguous`, and the refusal text ("add the slide on its own
  first") misleads.
- **Duplicate-position mis-shift** (NIT 19): the runtime's parser rejects it, so the turn ends with
  a user-visible error rather than a refusal, and the eval counts a `contract` failure.
- **The no-place product rule is unmeasured** by any eval case. Only layer-3 RC2 exercises it.
- **Budget.** Base ≈ USD 10.4 of 15; the repeats are fixed after B1.
- **Judge noise.** Re-run only judge-error rows. An untrusted calibration stops the measurement.
- **Sibling conflicts** in `nodes.py`, `session_manager.py`, `test_graph_nodes.py` and `test.yml`.
  The hunks are small and localised; rebase before the whole-branch review.
- **Rollout.** Existing installs get the node behaviour immediately, but the prompt only on publish.

## Review focus (for the whole-branch Opus review, §7)

1. A writer-by-writer comparison table against the one in Context, checking the restated invariant
   and its named exceptions.
2. A rollback-guarantee ruling against D4, path by path, including the failed top-of-node read and
   the dead turn.
3. That insertion targets can never include a shifted, unchanged slide, and that the equal-length
   path still uses positions on a gapped deck.
4. Multi-worker coherence (tellr-code-review §1).
5. Held-out discipline: no held-out phrasing outside Appendix H or the held-out case files.
6. A merge / no-merge verdict.

## Self-review (plan author)

1. **Coverage.**
   - A1: Tasks 1, 5, 8–13. A2: Tasks 2–4, 6, 7. A3: Tasks 6, 9.
   - Every slide-row writer and reader is in the Context table with a disposition.
   - Review findings 1–26 are dispositioned at the top of this file.
2. **Existing symbols grepped:**
   - graph nodes: `architect_node`, `_committed_slide_rows`, `_deck_positions`,
     `_persisted_spec_describes_these_rows`, `classify_spec_change`, `_DECK_LEVEL_FIELDS`,
     `rereview_committed_slides`, `build_branch_payload`, `_write_draft_row`, `_write_reviewed_row`,
     `_placehold_failed_position`, `_release_slides`, `slide_pipeline_node`, `deck_reviewer_node`,
     `data_analyst_node`, `edit_ignores_references`, `_deck_mutation_context`,
     `_raise_if_persisted_runtime_failure`;
   - row repository: `SlideWriter.write_slide`, `list_slides_in_position_order`, `delete_slide`,
     `commit_placeholder`, `is_placeholder_record`, `PLACEHOLDER_ERROR_KEY`;
   - session manager: `_upsert_slide_row`, `_attribute_slide_records`, `_attribution_from`,
     `SlideAttribution`, `NO_ATTRIBUTION`, `_prune_slide_rows_beyond`, `save_slide_deck`,
     `restore_version`, `get_slide_deck`, `_deck_findings`, `_finding_to_camel`,
     `write_slide_verification`, `slides_since_cursor`, `slide_revisions_since`,
     `create_chat_request`, `update_chat_request_status`, `set_chat_request_result`;
   - deck writes, chat and frontend: `record_shared_deck_mutation`, `SharedDeckMutationEvent`,
     `DeckMutationContext`, `write_deck_level_columns`, `read_deck_spec`, `ChatService.insert_slide`,
     `ChatService.get_slides`, `_get_or_load_deck`, `poll_chat`, `_require_chat_request_owner`,
     `_insertSlideAscending`, `handleSlideReady`;
   - evals: `expected_category_score`, `build_dataset`, `judge.calibrate`;
   - runtime and resolver: `PinnedInvocationEndpointError`, `is_transient_model_failure`,
     `_require_structured_output`, `architect_slide_payload`, `resolve_slide_references`;
   - test helpers: `make_spec`, `graph_env`, `graph_env_threadsafe`, `SkillStub`, `_edit_out`,
     `_revised`;
   - the `promote` CLI and the four hash pins.
3. **NEW symbols, each created by a named task:**
   - Task 1: `src.domain.slide_alignment.*`;
   - Task 2: `_rewrite_slide_rows`, `placeholder_slide`, `FAILED_SLIDE_TEXT`, `PENDING_SLIDE_TEXT`,
     `PENDING_SLIDE_MESSAGE`, `SlideRowsChangedError`, `SlideWriter.insert_pending_slides`;
   - Task 3: `_deck_findings(..., slide_indices=)`;
   - Task 4: `is_placeholder_verdict`, `nodes._holds_placeholder`;
   - Task 5: `nodes._degrade_edit`;
   - Task 8: `expected_category_score(..., reference=, current_deck_spec=)`,
     `calibrate(..., case_filter=)`;
   - Task 9: `_inserted_spec`, `_retargeted`, `JUDGE_ONLY_CALIBRATION`.
4. **No `DeckSpec`/`SlideSpec`/`ArchitectOutput` or payload-key change,** so there is no frontend
   mirroring, no schema digest move and no payload regeneration.

---

## Appendix H — HELD-OUT CASE CONTENT

Readers: the Task 9 agent and the supervisor only. Never show this to the Task 11 author.

- Deck: `evals/fixtures/meridian/heldout/deck_spec.json`, 6 slides (positions 0–5).
- The prior exchange and the library are as in the existing held-out cases (`heldout.py:21-24`).
- New slides have `data_references: []`, `slide_type: null`, `template_section_index: null`.

| id | message (exact) | expect | new slide(s) at final position | should_fail |
|---|---|---|---|---|
| `add_slide_anchor` | `Could you add a slide before slide 5 with a worked before-and-after prompt example?` | positions [4], inserted [4] | **4:** purpose `Make the techniques concrete with one worked example`; brief `Two-column slide with an ad-hoc prompt on the left and its optimised version on the right, labelling where system-prompt framing, a few-shot example and a structured output format were applied`; assumes `Audience has seen the measured gains and wants to see what a better prompt looks like`; hands_off `Applying the patterns to one real prompt is quick and visibly improves it`. **Message:** `I'll add a new slide 5 with a worked before-and-after prompt example, just before the workflow slide.` | **judge-only:** right place (4), targets [4], but an off-request new slide: purpose `Point the team at upcoming AI conferences`, brief `Bullet slide listing three upcoming AI conferences the team could attend, with dates and locations` |
| `add_slide_end` | `Add one more slide at the end with a glossary of the prompt terms` | [6], inserted [6] | **6:** purpose `Appendix — a glossary of the prompt terms used in the deck`; brief `Two-column glossary defining system prompt, few-shot example, chain-of-thought, structured output, eval criteria and test suite in one line each`; assumes `Audience has heard each term during the talk`; hands_off `Everyone leaves with the same vocabulary for prompt work`. **Message:** `I'll add a glossary of the prompt terms as a new final slide, slide 7.` | the last slide replaced: targets [5], 6 slides with position 5 = the glossary |
| `add_slide_as_number` | `Add a new fourth slide on common prompt anti-patterns` | [3], inserted [3] | **3:** purpose `Warn against the habits that undo prompt optimisation`; brief `Bullet slide listing four common prompt anti-patterns — vague instructions, contradictory constraints, examples that leak the answer, and unbounded output — each with a one-line fix`; assumes `Audience knows the four core patterns from the previous slide`; hands_off `Most bad outputs come from a handful of avoidable prompt habits`. **Message:** `I'll add a new slide 4 on common prompt anti-patterns; the impact slide moves to slide 5.` | inserted one place late: targets [4], slide at position 4 |
| `add_slide_and_revise` | `Add a slide after slide 3 on versioning prompts, and add it to the checklist on the final slide` | [3, 6], inserted [3] | **3:** purpose `Show how to keep prompts under version control`; brief `Bullet slide explaining that every prompt change gets a version, a change note and a link to its eval results, so a regression can be traced and rolled back`; assumes `Audience knows the four core patterns and that prompts change often`; hands_off `A versioned prompt can be compared, reviewed and rolled back like code`. **Revision at 6 (gold 5):** the gold brief with `five-item prompt optimisation checklist (define task scope, choose patterns, write eval criteria,` replaced by `six-item prompt optimisation checklist (define task scope, choose patterns, version every prompt, write eval criteria,`. **Message:** `I'll add slide 4 on versioning prompts after slide 3, and add versioning to the checklist on the final slide, now slide 7.` | added but the checklist not revised: targets [3] |

**Pinned `slide_references` (held-out; verified with `resolve_slide_references`).**
- anchor → `slide 5` [5]→[4];
- end → `[]`;
- as_number → `[]` (indefinite ordinal);
- and_revise → `slide 3` [3]→[2], then `final slide` [6]→[5].

`test_insert_anchors` (held-out):
- the anchor refs == `inserted`;
- as_number and end refs == `[]`;
- and_revise refs == `[inserted − 1, last old position]`.

**Markers and fairness.**
- Markers:
  - the anchor brief contains `before` and `optimised version`;
  - the judge-only should_fail's brief contains `conferences` and no `prompt`;
  - the glossary purpose starts `Appendix`;
  - the anti-patterns brief contains `four common prompt anti-patterns`;
  - the revised checklist contains `six-item` and `version every prompt`.
- Gold fairness:
  - the position 4 purpose starts `Provide the workflow`;
  - the position 5 brief contains `five-item`;
  - no gold purpose contains `glossary`, `anti-pattern`, `version` or `conference`;
  - the position 2 purpose contains `techniques`.
