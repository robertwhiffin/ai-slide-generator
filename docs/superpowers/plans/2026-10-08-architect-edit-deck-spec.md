# Architect edits return an updated DeckSpec — Implementation Plan

**Date:** 2026-10-08
**Branch:** `fix/architect-edit-deck-spec` (off local `feat/ws2a-ai-gateway`, b9dc2499f)
**Spec:** none written; the binding authority is the product rule below (user ruling, 2026-10-08) plus
the evidence in this plan's Context. Rulings made without a spec are provisional.

## Product rule (binding)

The DeckSpec is the source of truth for a deck. Every slide edit must be reflected in an updated spec.
An architect `intent='edit'` that returns `deck_spec: null` is an incorrect implementation.

## Context (verified 2026-10-08)

- `ArchitectOutput._intent_payload_consistency` (`src/domain/skill_io.py:89`) requires `deck_spec` for
  `build` only; `edit` requires a non-empty `target_positions`.
- The v1 architect prompt (`src/core/skills/architect.py` `INSTRUCTIONS`, duplicated as the architect
  `prompt_text` in `src/services/agent_definition_manifest_v1.py`) says "DECKSPEC CONSTRUCTION (build intent
  only)". The model payload already carries `current_deck_spec`, but the prompt never says to return it
  revised.
- `architect_node` (`src/services/graph/nodes.py` ~1553-1609): when `out.deck_spec` is None it falls back to
  the persisted `prior_spec` (if `_persisted_spec_describes_these_rows`), else degrades to discuss with
  `spec_positions_stale`; with no prior spec it degrades with `edit_without_spec`.
- `build_branch_payload` (nodes.py ~1270) briefs the builder from `spec.slide_at(position)` only; the
  builder never sees the user's message. So a null-spec edit rebuilds the target slide from its OLD brief
  and the requested change is lost.
- `classify_spec_change` (nodes.py:432) compares only the design contract and deck-level fields, never the
  slides. `target_positions` is copied from the model output; nothing checks that the slides the spec changes
  are the slides that get rebuilt.
- The spec is persisted every build/edit turn (nodes.py ~1810-1832), including describe-only (sweeper)
  turns, whose router ends before the foreman.
- `ArchitectOutput`'s class docstring is part of `model_json_schema()` (checked: "Invariants" is in the
  schema), and so feeds the frozen `schema_contract` digest pinned fail-closed across many tests.
- Edits cannot add or remove slides today: the fallback spec is the prior spec, and `build_branch_payload`
  raises on an absent position. There is no delete or insert intent.
- The eval harness's architect judge already FAILS a content edit with `deck_spec: null` (that rubric is
  correct; do not change it). Train and held-out `edit_request` score 0/3 on v1.
- Local Postgres is up, and `tests/integration` runs locally (`test_spec_row_alignment.py`: 10 passed).

## Global constraints

- Shared pyenv: NEVER `pip install`. Never push, merge, or touch main. Never skip git hooks; keep
  `git commit` in its own shell command (a hook false-positives on compound commands containing a short
  `-n` flag). Commit with `git commit -m "<subject>" -m "Co-authored-by: Isaac <no-reply@databricks.com>"`.
- Import `src.core.database` before other `src.*` imports. Unit tests use disposable sqlite
  (`DATABASE_URL=sqlite:////tmp/<name>.db`).
- Do NOT edit `ArchitectOutput`'s class docstring or any field description (it would change the frozen
  schema digest). Document the new invariant in a code comment and in the validator's error text.
- Do not change the eval judge prompts, cases, or scorers.
- Baselines are cause-sets: diff failing-test CAUSES against the pre-change baseline, not counts.
- Live model calls only in Task 3.

---

## Task 1: Contract and graph — an edit carries its revised spec

**Models:** test=opus impl=sonnet

**Files:** `src/domain/skill_io.py`, `src/services/graph/nodes.py`, `tests/unit/test_skill_io.py`,
`tests/unit/test_graph_nodes.py`, `tests/integration/conftest_stub_skills.py`, and the integration tests
that use its null-spec edit (`test_graph_orchestration.py` ~688, `test_spec_row_alignment.py`,
`test_sweeper_describe_only.py` ~276).

Behaviour:

1. **Validator.** `intent='edit'` requires `deck_spec`. Error text starts `"intent='edit' requires"` (the
   existing edit tests match that prefix) and says the deck spec is the source of truth, so an edit must
   return it revised. `target_positions` stays required and non-empty.
2. **Guards keyed on the persisted spec stay.** An edit with no persisted spec still degrades to discuss
   with `edit_without_spec`; an edit whose persisted spec no longer describes the committed rows still
   degrades with `spec_positions_stale`. Both are decided from `prior_spec` and the committed rows, BEFORE
   the model's spec is used, exactly as today. (Ruling: these protect against editing a deck the spec does
   not describe; the model edits the persisted spec, so the persisted spec must be sound.)
3. **The model's spec briefs the build.** On an edit that passes the guards, `spec = out.deck_spec`. The
   null-spec fallback to `prior_spec` is removed (it is unreachable once the validator requires a spec).
4. **Edits keep the position set.** If the edit spec's set of slide positions differs from `prior_spec`'s,
   degrade to discuss with a new code `edit_spec_positions_changed` and a user-facing message saying the
   edit could not be applied (adding or removing slides is not an edit). (Ruling: edits could never add or
   remove slides; this keeps that, and stops a silent drop leaving a committed row with no spec.)
5. **Every changed slide is rebuilt.** `target_positions` becomes the sorted union of the model's
   `target_positions` and every position whose `SlideSpec` differs from `prior_spec`'s at that position.
   (Ruling: a slide whose brief changed but is not rebuilt is exactly the spec/slide drift the product rule
   forbids.) The design-contract and deck-level branches of `classify_spec_change` keep overriding it as
   today.
6. **Describe-only turns are unchanged.** A sweeper turn whose architect returns edit persists the
   returned spec and builds nothing, as today.

Steps:
- [ ] **Step 1 (test author):** write failing behavioural tests for 1-6: the validator; that the builder
  payload for a target position carries the MODEL's revised brief, not the prior one (sabotage: restore the
  fallback and the test must go red); the two kept guards; positions-changed degrade; the union (a spec that
  changes slide 4 while `target_positions=[2]` rebuilds 2 and 4); describe-only persists the edit spec and
  dispatches no builder. Update `conftest_stub_skills._skill_architect` so an edit returns the persisted
  spec with each target slide's `content_brief` revised, and update every existing test that built a
  null-spec edit. Name every existing test you change and say why; do not weaken an assertion. Confirm red
  for the right reasons; leave uncommitted.
- [ ] **Step 2 (implementer):** make them green without editing tests.
- [ ] **Step 3:** `tests/unit` and `tests/integration` failing-cause set equals the pre-change baseline.
- [ ] **Step 4:** commit.

## Task 2: Prompt — the architect returns the revised spec on an edit

**Models:** test=opus impl=sonnet

**Files:** `src/core/skills/architect.py`, `src/services/agent_definition_manifest_v1.py` (via promote
only), the two pinned `PACKAGED_V1_CONTENT_HASHES` copies (via promote only),
`frontend/tests/fixtures/graphLifecycleContract.json` (re-recorded), a new
`evals/configs/architect/edit-spec.yaml`, and a test file for the prompt contract.

Prompt changes to `INSTRUCTIONS` (keep everything else byte-identical):
- PAYLOAD RULES: `edit → target_positions must be a non-empty list AND deck_spec must be set`.
- Heading `DECKSPEC CONSTRUCTION (build and edit intents):`.
- A short EDITING rule: on an edit, start from `current_deck_spec` and return it in full; revise only what
  the user asked for on the target slides; keep every slide's position and every other slide unchanged;
  change deck-level fields only when the user asks; adding or removing slides is not an edit.
- The design-system rule is unchanged (a contract switch is still proposed, never written into deck_spec).

Steps:
- [ ] **Step 1 (test author):** failing tests: the manifest's architect `prompt_text` equals
  `src/core/skills/architect.py` `INSTRUCTIONS`; it states that edit requires deck_spec and the editing rule;
  the heading no longer says "build intent only"; the architect `schema_contract` digest is UNCHANGED; every
  other role's definition hash is unchanged. Leave uncommitted.
- [ ] **Step 2 (implementer):** edit `INSTRUCTIONS`; write `evals/configs/architect/edit-spec.yaml` whose
  prompt equals the new `INSTRUCTIONS`; run `promote({"architect": load_config(...)})` (dry run first);
  re-record the frontend contract with the command promote prints; run the pinned-hash, manifest, bootstrap
  and packaged-release suites plus Task 1's suites. Report the old and new architect hash.
- [ ] **Step 3:** commit (manifest, pins, skill, config, fixture, test together).

## Task 3: Live verification

**Models:** impl=sonnet (controller runs it)

- [ ] `python -m evals.run_eval --agent architect --calibrate` and `--calibrate --split heldout`: all
  trusted (re-run only errored rows; a misclassification stops the task).
- [ ] `python -m evals.run_eval --agent architect --config v1-baseline --repeats 3` on train and on
  `--split heldout` (about USD 4.60 total).
- [ ] Pass when `edit_request` passes on both splits (at least 2 of 3 repeats each) and no other architect
  case drops by more than one repeat versus the 2026-10-06 / 2026-10-08 baselines. Attribute any failure
  from the stored rationales.
- [ ] README: add an architect re-baseline note (git sha, both pass rates, the cause fixed) under the
  existing baseline sections. Commit.
- [ ] Note for the user: `tests/agentic/test_rc8_*` and `test_rc13_*` (live, not CI) now expect a
  deck_spec on edits; they were not run.
