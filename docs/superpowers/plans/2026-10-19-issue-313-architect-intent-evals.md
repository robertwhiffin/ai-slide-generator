# Architect intent and slide references (#313) — Implementation Plan

**Date:** 2026-10-19 (revised the same day after the plan review)
**Branch:** `feat/313-architect-intent-evals` (off `origin/main` 679d2f21), worktree
`.claude/worktrees/issue-313`
**Issue:** #313 "Architect does not always classify the user's intent correctly"
**Spec:** none written. The Decisions section below holds the rulings. They are provisional and the
user may overrule any of them.
**Before Task 1:** load `executing-plans-tellr` alongside `superpowers:subagent-driven-development`
and run its plan-vs-code corrections pre-pass (§2). Every task below has a `Models:` tag (§9).

> **HELD-OUT WARNING.** Appendix H of this file contains held-out case content. Never give this
> file, or any excerpt from Appendix H, to the prompt-candidate author (Task 8). Task 8's brief is
> self-contained and is passed to that agent verbatim. Commit messages carry no held-out content.

---

## Review findings: dispositions

Review: `~/tellr-loop/issues/issue-313/PLAN-REVIEW.md`. Rulings are the supervisor's.

| # | Severity | Disposition | Where it landed |
|---|---|---|---|
| 1 | MAJOR | ACCEPT. A fourth architect hash pin exists at `test_graph_definition_manifest.py:1158-1159`. The Task 10 agent may update hash-pin literals, recomputed by running code. | Context; Task 10; Risks |
| 2 | MAJOR | ACCEPT. `search_traces` needs `locations=[run.info.experiment_id]`. The store-backed test logs to a non-default experiment. Sabotage: drop `locations`. | Context; Task 2 |
| 3 | MAJOR | ACCEPT. A describe-only turn sends `slide_references: []`. `slide_numbering` is still sent. New test (g). | D4; Tasks 5 and 6 |
| 4 | MAJOR | ACCEPT. Singular `slide` takes `and`/`&` lists but not bare commas. Candidate A says: take a resolved phrase from `slide_references`, otherwise look it up in `slide_numbering`, and never use number − 1. Task 10 tests this. | D3; Tasks 5, 8 and 10 |
| 5 | MAJOR | ACCEPT, exclusion approach. An ordinal after a/an/another/one more/new/extra/additional is not a reference. Lookbehind `(?<![-\w])` on number and ordinal words. #314 owns add/insert anchors. | D3; Task 5 |
| 6 | MAJOR | ACCEPT. Held-out `edit_polite_ordinal` names a stat that is not first in the gold brief. Fairness test added. | Appendix H |
| 7 | MAJOR | ACCEPT. Cost basis is opus-5 at USD 5/25 per M and the judge at about USD 0.035 per call. USD 0.41 is already spent. No reusable run exists. Repeats: B1/F1 ×5, B2/F2 ×5, B3/F3 ×3 (P1), B4/F4 ×2. Drop order is ruled. | Task 4; Task 9; Measurement plan |
| 8 | MAJOR | ACCEPT (a). Add S0: the v1 prompt on regenerated payloads. Adds the stop-case decision rule and the A2 coverage per branch. | D13; Task 7½; Task 9 |
| 9 | MINOR | ACCEPT. The sabotage is the off-by-one row. | Task 2 |
| 10 | MINOR | ACCEPT. `test_zz_real_artefacts_unchanged_versus_head` is expected red until commit. | Task 10 |
| 11 | MINOR | ACCEPT. A target slide's `purpose` may be revised where gold contradicts the request (train `edit_last_slide`). For held-out `edit_last_slide` the request itself is replaced, because its purpose, `hands_off` and the deck `call_to_action` all name the checklist. | Task 3; Appendix H |
| 12 | MINOR | ACCEPT. Second reason the smoke payload stays unchanged: the Postgres shape check. The fixture claim is corrected. | Context |
| 13 | MINOR | ACCEPT. Task 8 also may not read `~/tellr-loop/issues/issue-313/`. Repo greps use `--exclude-dir=cases_heldout`. No held-out content in commit messages. | Held-out discipline; Task 8 |
| 14 | MINOR | ACCEPT. Both transports are cited. | Context |
| 15 | MINOR | ACCEPT. `build_request` 3/5 is deck length, so it is out of scope. B3/F3 are regression guards. | Goal; D6 |
| 16 | NIT | ACCEPT. Cost basis cited. | Measurement plan |
| 17 | NIT | ACCEPT. File ownership in `tests/agentic/payloads.py` is split. | Task 6 |
| 18 | NIT | ACCEPT, all five. Monolith parser wording; stale `nodes.py` docstring; two README sentences; `Nth` suffixes and a "21st" test; the bare-comma plural is a pinned known limit. | Context; D3; Tasks 3, 5 and 6 |

---

## Goal

The architect classifies a turn's intent (`discuss` / `ask_data` / `build` / `edit` /
`confirm_design_contract`) more reliably. The user's slide numbers reach the right
`SlideSpec.position`: "slide 2", "the second slide", "the last slide", "slides 2-4". This is
guaranteed by a deterministic contract rather than by the model's arithmetic.

Representative failing requests become eval cases in train and held-out. They are measured on the
current v1 architect before anything changes, then again after.

The issue's `build_request` 3/5 evidence is out of scope. It is a deck-length failure (5 slides
against a 10-slide reference), not an intent failure, and the 14-20 slide rule shipped in 45ce906c
addresses it. B3/F3 measure `build_request` and `ask_data` only as regression guards.

## Acceptance criteria (verbatim from #313)

- **(A1)** Representative mis-classified requests are added as eval cases (train AND held-out), and the
  architect's intent accuracy on them is MEASURED with the current v1 architect BEFORE any prompt change
  (numbers recorded).
- **(A2)** Position references in user language ("slide 2", "the second slide", "the last slide",
  "slides 2-4") resolve to the right `SlideSpec.position` (known failure: "slide 2" read as 0-indexed →
  position 2 instead of 1).

**How each is met and tested**

| AC | Met by | Tested by |
|---|---|---|
| A1 cases | Task 3 adds 4 cases per split. They are in the CURRENT 9-key v1 payload shape and are generated, not hand-written. | Pack self-tests (`tests/unit/evals/test_pack_architect*.py`), cross-split pins (`test_cross_split.py`), generator idempotence and committed-equals-generated tests. |
| A1 measured BEFORE | Task 4 (SUPERVISOR) runs calibration, then v1-baseline train and held-out sweeps on the Task 3 commit. That is before Task 7 regenerates payloads and before any prompt candidate exists. Task 2's `evals/intent_report.py` reads intent and position accuracy. | Numbers go to the Task 4 ledger, then to the evals README (Task 11). |
| A2 deterministic | Task 5's `src/domain/slide_numbering.py` resolves references to positions with no model. Task 6 puts the result in the architect payload as `slide_numbering` and `slide_references`. | An exhaustive table-driven unit test (`tests/unit/test_slide_numbering.py`). Node payload tests in `tests/unit/test_graph_nodes.py`. In Task 7, for every eval edit case in both splits, the union of the resolved reference positions equals the case's expected positions. |
| A2 end to end | Task 8 points the SLIDE NUMBERS block at the new keys. Task 9 measures it. Task 10 promotes it. If Task 9 stops, D13 decides what ships and records the remaining A2 coverage. | Position accuracy among edit-intent rows: S0, F1 and B1 (ledger). Prompt-contract tests (Task 10). |

---

## Context (verified 2026-10-19 against 679d2f21)

**Architect and payload**
- `architect_node` is at `src/services/graph/nodes.py:1422`.
  - The model payload is ONE literal dict, `payload = {...}` (`nodes.py:1527-1543`), with 9 keys.
  - `committed_positions` is built at `:1469`; `describe_only` is set at `:1626`; the edit-target union
    is at `:1758-1769`; the module logger is at `:117`.
- The prompt `src/core/skills/architect.py` `INSTRUCTIONS` ends with `SLIDE NUMBERS / In `message`
  only, speak about slides 1-indexed, matching the UI. `position` and `target_positions` stay
  0-indexed.` (`architect.py:116-118`). Nothing tells the model how to turn the user's "slide 2" into a
  position. That gap is the known off-by-one.
- `MODEL_PAYLOAD_KEYS["architect"]` is at `src/services/agent_model_payload.py:56-68`. Three pins hold
  it:
  - the literal in `tests/fixtures/model_payload_keys.py:64-80` (`EVERY_MODEL_CALL`);
  - the union check in `tests/unit/test_agent_model_payload.py:47-49`;
  - `tests/unit/test_graph_nodes.py:4848` (`TestNoRolesModelPromptCarriesSessionIdentifiers`), which pins
    production to the exact key set.
- `tests/unit/test_agentic_layer_is_placed_and_gated.py:564-610` parses `architect_node` with `ast`. It
  reads the string keys of the single literal `payload = {...}` and requires them to equal
  `tests/agentic/payloads.py:24-34` `ARCHITECT_PAYLOAD_KEYS`. **New keys must therefore be literal dict
  entries. A `**spread` is invisible to that check.**
- The seeded smoke payload (`src/services/graph_configuration_seed.py:3-17`) stays unchanged. Two
  checks would turn red if it changed:
  - `tests/unit/test_graph_configuration_bootstrap.py:44` pins it;
  - CI's Postgres job runs
    `tests/integration/test_graph_lifecycle_acceptance_postgres.py:45`
    `test_a_fresh_recording_has_the_checked_in_contracts_shape` (`.github/workflows/test.yml:462`).
    That test compares the key structure of every recorded body against the frontend contract fixture,
    including the architect smoke case's `synthetic_payload` and `model_payload`. New smoke keys would
    fail CI until a re-record, and a re-record needs PostgreSQL.

  `model_payload_for` keeps only keys that are present (`agent_model_payload.py:109-128`), so stored
  test cases without the new keys stay valid.
- `_conversation` (`nodes.py:965-988`) returns user turns of `_HUMAN_TYPES`
  (`{"user_query","user_input","chat"}`, `nodes.py:200`) and assistant turns. The user's message is
  persisted before the graph runs, on both transports:
  - SSE: `message_type="user_input"` (`src/api/services/chat_service.py:1157-1161`), before the graph
    branch (`:1221`);
  - polling, which the deployed app uses: `message_type="user_query"` (`src/api/routes/chat.py:755-762`),
    before `enqueue_job`.

  The latest user turn is therefore the current request on a normal turn. Two exceptions matter:
  - On the pass after the analyst returns, `architect_message` holds the analyst's synthesis
    (`nodes.py:2074`).
  - The sweeper's describe-only turn (`run_arc_review`, `src/services/spec_sync.py:654-665`) sends
    `ARC_REVIEW_MESSAGE` and persists **no** user row. Its conversation therefore ends with a stale
    human message from before the hand edit that triggered the sweep.
- Only `{"architect_message": message}` reaches the graph (`chat_service.py:1968-1973`). The UI's slide
  selection (`slide_context`) never does.
- The monolith has its own parser, `ChatService._parse_slide_references` (`chat_service.py:2630`).
  - It is a method on the heavy `ChatService`.
  - It handles digits, digit ordinals ("8th slide", `:2675-2679`), ranges, and "after/before slide N".
  - It has no ordinal words, no last/final and no lists, and it returns `number − 1`, assuming
    contiguous positions.
  - It is not reused.
- The `_persisted_spec_describes_these_rows` docstring (`nodes.py:1018-1023`) says the deck spec is
  "renumbered on insert and on nothing else". That is stale: every route now renumbers through
  `_rewrite_deck_spec_slides`. Task 6 corrects the docstring only.

**Positions and slide numbers**
- `SlideSpec.position` is the slide's canonical identity, "stable after deletes and partial rebuilds"
  (`src/domain/deck_spec.py:71-89`).
  - `DeckSpec.slide_at` looks a slide up by field, never by list index (`:146-157`).
  - The only position invariant is uniqueness (`:139-144`), so gaps are representable.
- The UI numbers slides two ways:
  - the slide panel uses list index + 1 over rows in position order
    (`frontend/src/components/SlidePanel/SlidePanel.tsx:336,350`, then `SlideTile.tsx:181`
    `Slide {index + 1}`, and `SlideViewer/ThumbnailRibbon.tsx:133`);
  - SpecView shows `Slide {slide.position + 1}` (`SpecView/SpecView.tsx:214`).

  The two agree only when positions run contiguously from 0.
- Every deck-mutation route re-stamps positions contiguously from 0, so gaps can come only from an
  architect build spec that itself has gaps.
  - The spec: `_rewrite_deck_spec_slides`, `chat_service.py:3846`, re-stamp at `:3961-3965`.
  - The rows: `save_slide_deck`, `src/api/services/session_manager.py:1679` `enumerate`, prune at
    `:1699`.
  - Delete is at `chat_service.py:4081`.
- Edit guards: an edit is refused when the persisted spec's positions differ from the committed rows'
  positions (`_persisted_spec_describes_these_rows`, `nodes.py:1006`). It is also refused when the
  model's spec changes the position set (`edit_spec_positions_changed`). An accepted edit therefore
  always has spec positions equal to row positions.

**Eval harness**
- The train generator (`evals/packs/architect/mutations.py`) and the held-out generator
  (`evals/packs/architect/heldout.py`) build payloads through `model_payload_for(AGENT, {...})`
  (`mutations.py:67-90`, `heldout.py:46-69`).
  - The train deck has 10 slides (positions 0-9).
  - The held-out deck (`evals/fixtures/meridian/heldout/deck_spec.json`) has 6 (positions 0-5).
- The architect `expected_category` check (`evals/harness/scorers.py:49-61`) requires the intent to
  match AND, for an edit, `target_positions` to equal the expected set. **It is not intent accuracy.**
  MLflow logs no aggregate for it either: it aggregates only numeric, bool and yes/no values
  (`aggregation.py:77-84` `_cast_assessment_value_to_float`), and the harness emits `"pass"`/`"fail"`.
- Traces are read like this (probed; reviewer re-probed on run `11c50057`):
  - Get the run with `run = MlflowClient(uri).get_run(run_id)`.
  - Then call `mlflow.search_traces(run_id=run_id, locations=[run.info.experiment_id],
    return_type="list")`. **Without `locations` it raises** "Run … belongs to experiment 1, which is not
    in the list of locations provided: ['0']". Train runs log to `tellr-agent-eval` and held-out runs to
    `tellr-agent-eval-heldout` (`mlflow_run.py:30-31`), so neither uses the default experiment.
  - `trace.data.request` is the JSON of the inputs `{agent_key, case_id, repeat[, split]}`.
  - `trace.data.response` is the JSON of the predict output `{structured, …, infra_error}`.
  - `trace.info.assessments` holds `Feedback` entries (`expected_category`, `contract`, `judge`) and
    `Expectation` entries (`expect`, `reference`, `design_system_active`).
- The judge sees only `message` and `current_deck_spec` from the payload (`evals/harness/judge.py:36-37`),
  plus the reference and the candidate. `predict_fn` loads the case from disk per row
  (`mlflow_run.py:128-129`).
- The probe blocker (supervisor, verified live): `evals/run_eval.py:23-31` `_endpoint_reachable` calls
  `WorkspaceClient().serving_endpoints.get(name)`. The manifest's `system.ai.claude-opus-5` is not a
  serving-endpoint name, so every v1-baseline architect sweep aborts. `gateway_endpoint_name`
  (`src/services/model_endpoint_catalog.py:90-94`) maps `system.ai.<m>` to `databricks-<m>`.
- `evals/configs/prices.yaml` has no `system.ai.claude-opus-5` entry, so `est_cost_usd` is absent
  (`mlflow_run.py:286`). Do not add one (supervisor ruling).
- `mlflow.db` is per worktree (`mlflow_run.default_tracking_uri`, `:39-40`, resolves to
  `EVALS_DIR.parent`). This worktree's store holds one architect run, `11c50057`: v1, `repeats=1`,
  `edit_request,build_request`, USD 0.41 spent. **No reusable 5-repeat run exists.** Launch every #313
  run from the issue-313 worktree root.

**Pins a case or prompt change touches**
- `tests/unit/evals/test_cross_split.py:24` pins the architect held-out ids. `:62-63`
  (`test_total_is_thirty_five`) pins the total at 35.
- `tests/unit/evals/test_pack_generation_isolation.py:29` pins `len(written) == 5` for every agent.
- **Architect hash pins, four in all:**
  - `tests/unit/test_packaged_release_loader.py:24`, rewritten by promote;
  - `tests/unit/test_graph_definition_manifest.py:707`, rewritten by promote;
  - `tests/unit/test_architect_edit_prompt.py:38` `HEAD_ARCHITECT_CONTENT_HASH`, by hand;
  - `tests/unit/test_graph_definition_manifest.py:1158-1159`, the literal `33a88de7…` in
    `test_hashing_rejects_non_string_object_keys_inside_guidance`. It hashes the architect definition,
    prompt included, with a modified overlay. It is updated by hand: precedent 45ce906c did so, and
    `promote.py:89-107` rewrites only the `PACKAGED_V1_CONTENT_HASHES` block.
- `test_architect_edit_prompt.py:81-86` pins the block hashes of opening, INTENT CLASSIFICATION, DESIGN
  SYSTEMS and closing. Other pins in that file:
  - `:385-396` pins the 1-indexed `message` / 0-indexed positions wording;
  - `:400-416` forbids `non-null` and similar phrasing;
  - `:202-208` forbids "reject" in PAYLOAD RULES.
- `tests/unit/test_skill_prose.py:207-222` pins "14 to 20 slides", "reusable layouts, not a one-of-each
  menu" and the slide_type self-check sentence.
- `tests/unit/evals/test_promote.py:612-620` (`test_zz_real_artefacts_unchanged_versus_head`) requires
  the manifest and both promote pin files to equal `HEAD`. It is red between promote and the commit.
- The architect is **not** a `LegacyV1PromptTransition` source. `agent_key` is
  `Literal["data_analyst","build_reviewer"]` (`src/services/prompt_assembler.py:206-212`, records at
  `:231-253`), so promote's lock (`evals/harness/promote.py:156-175`) does not refuse it.
- The v2 protected-assembly digest material (`prompt_assembler.py:359-389`) contains no architect prompt
  and no payload keys. `_V2_DIGEST` (`:398`), `_HISTORICAL_V2_DIGESTS` (`:408`) and
  `test_retained_bundle_ledger` are unaffected.
- The frontend lifecycle contract fixture is checked in two places:
  - unit: round-trips and commit ancestry (`tests/unit/test_graph_lifecycle_playwright_contract.py:134-228`);
  - Postgres CI: key **shape** only (above).

  Neither checks the current prompt text. Precedent 45ce906c promoted an architect prompt without
  re-recording the fixture, which needs PostgreSQL (`graph_lifecycle_journey.py:1893-1904`).
- `promote.py` has a CLI (`:242-280`). The evals README line 151 ("no `__main__`") is out of date.
- Candidate `.md` prompt files are read with `read_text()` (`evals/harness/config.py:113-115`). A
  trailing newline would change the prompt and its hash.

**Baseline**
At 679d2f21 these all pass:
- `tests/unit/evals/{test_pack_architect,test_pack_architect_heldout,test_cross_split,test_pack_generation_isolation,test_run_eval}.py`
- `tests/unit/{test_architect_edit_prompt,test_agent_model_payload,test_agentic_layer_is_placed_and_gated}.py`

That is 283 passed. `tests/unit/test_graph_nodes.py` and `test_architect_design_system_library.py` give
226 passed.

---

## Decisions

**D1 — What "slide N" means.** Slide N is the N-th slide of the current deck in ascending `position`
order: the number the slide panel shows, not `N − 1`.
- The numbering comes from the committed rows' positions when there are rows, else from the persisted
  spec's positions, else it is empty.
- *Rationale:* users read numbers off the slide panel. Routes keep positions contiguous, so normally
  Position = N − 1. A gapped build spec is the only exception, and there the panel numbering is what the
  user sees. Rows come first because the UI renders them, and an edit whose spec and rows disagree is
  refused anyway.
- *Known limit:* SpecView numbers by `position + 1`, which differs only on a gapped deck. Out of scope;
  follow-up.

**D2 — A contract fix, not a prompt nudge.**
- A new pure module, `src/domain/slide_numbering.py`, imports only `re` and `typing`.
- `architect_node` adds two literal payload keys, so the model copies positions instead of computing
  them:
  - `slide_numbering`: `[{"slide_number": 1, "position": 0}, …]`, one entry per slide, in presentation
    order;
  - `slide_references`: `[{"text": "slide 2", "slide_numbers": [2], "positions": [1],
    "out_of_range": []}, …]`, one entry per reference in the user's latest message, in order of
    appearance. It is always a list; it is empty when there is no deck, and empty on a describe-only
    turn (D4).
- No `DeckSpec`/`SlideSpec` field and no output schema changes, so `frontend/src/types/slide.ts` and
  `deckSpecConformance.test.ts` need no mirroring.

**D3 — Reference grammar.** It is documented and table-tested; everything else stays unresolved.

*Matching rules.*
- Case-insensitive, at word boundaries.
- `text` is the exact matched substring, without a leading "the".
- Matches are taken left to right without overlap. At any one start the longest form wins: a list or
  range beats a single number, and "second-to-last" beats "second".

*Numbers.*
- 1–3 digits, or the cardinal words one … twenty.
- Number and ordinal **words** carry the lookbehind `(?<![-\w])` and the lookahead `(?!-[a-z])`. So
  "twenty-one", "twenty-first" and "thirty-second" are unresolved, never misread as "first" or "second".

*Ordinals.*
- 1–3 digits plus any of `st`/`nd`/`rd`/`th`. The suffix is not checked against the number, so 11th,
  12th, 13th, 21st, 22nd and 23rd are all accepted.
- The words first … twentieth.
- `last` and `final` = the slide count.
- `penultimate`, `second-to-last`, `second to last`, `second-last` and `second last` = count − 1.

*Forms.*
- **F1** `slide` [`#` | `number`] ITEM {(`and`|`&`) ITEM}. ITEM is a NUMBER or a digit dash range. Gives
  "slide 2", "slide #2", "slide number 2", "slide two", "slide 2-4", "slide 2 and 3", "slide 2 & 3".
  - A singular `slide` takes **no bare-comma continuation** ("On slide 2, 3 cards…" gives slide 2 only).
  - It takes **no `to`/`through` range** ("move slide 2 to 5" gives slide 2 only).
- **F3** `slides` ITEM {SEP ITEM}.
  - ITEM is a NUMBER, or NUMBER (`-`|`–`|`—`|`to`|`through`|`thru`) NUMBER. Dash ranges take digits only.
  - SEP is `,` | `, and` | `and` | `&`.
  - Gives "slides 2-4", "slides 2 to 4", "slides 2 and 3", "slides 2, 3 and 5", "slides 2-4 and 6",
    "slides two and three".
- **F4** ORDINAL `slide` (singular): "the second slide", "last slide: drop…", "the 4th slide", "the final
  slide", "the penultimate slide".
  - **Exclusion:** an F4 match whose ordinal is immediately preceded by `a`, `an`, `another`, `one more`,
    `new`, `extra` or `additional` is **not** a reference. "Add a final slide", "add a second slide",
    "I need a third slide" and "a new second slide" all name a slide that does not exist yet.
  - #314 owns the interpretation of add and insert anchors. A definite or bare form ("the last slide",
    "last slide: …", "Add a chart to the second slide") is still a reference.

*Ranges.* Inclusive, in either order. A range spanning more than `MAX_RANGE_SPAN = 100` numbers drops the
whole reference.

*Result.*
- `slide_numbers` is sorted and deduplicated.
- `positions` holds the in-range numbers mapped through D1, in the same order.
- `out_of_range` holds numbers < 1 or > count, sorted. Numbers are **reported, never clamped**.
- With no deck, `slide_references == []`.

*Deliberately unresolved.* Each case is tested, so extending the grammar is a deliberate change.
- Count-relative plurals ("the last two slides") and plural ordinals ("the second and third slides").
- Deictic and semantic phrases: "this slide", "the next slide", "the cover", "the agenda slide",
  "a new slide".
- Slide counts ("a 10-slide deck", "10 slides", "five slides"), "Slidev", "slideshow", and "slides"
  alone.
- "or" is not a separator.
- **Known limit, pinned by a test:** a bare-comma plural "On slides 2, 3 bullets each…" resolves to
  [2,3].
- The model looks anything unresolved up in `slide_numbering` (Candidate A says so).

*References are lexical.* A reference says which existing slide a phrase names, not that the user wants
it changed. "after slide 3" resolves "slide 3" and leaves the anchor to #314.

**D4 — Which text is resolved, and when nothing is.**
- The latest `role == "user"` turn in `conversation` is resolved, falling back to `message` when there is
  none.
  - *Rationale:* on the pass after the analyst returns, `message` is the analyst's synthesis
    (`nodes.py:2074`), and the user's "slide 4" must still resolve. On a first pass and in evals the two
    texts are identical, on both transports (Context).
- **On a describe-only turn, `slide_references` is `[]`.** `slide_numbering` is still sent, because it
  describes the current deck.
  - *Rationale:* the sweeper persists no user row (`spec_sync.py:654-665`), so the latest user turn
    predates the hand edit that triggered the sweep. Its "slide 2" may now name a different slide.

**D5 — Guard: log only, no override, no degrade.**
- Trigger: an edit on a turn that is not describe-only, whose model `target_positions` are disjoint from
  every resolved in-range reference position.
- Effect: `architect_node` logs a WARNING (`edit_ignores_references`). Behaviour is otherwise unchanged.
- *Why not override:* an off-by-one model also revised the wrong `SlideSpec`, and the node rebuilds every
  changed slide (`nodes.py:1758-1769`).
- *Why not degrade:* legitimate edits can be disjoint from the named slides ("slide 2 is perfect;
  tighten the rest").

**D6 — New eval cases.** Four per split, by supervisor ruling on spend. They are all edit or discuss cases
on the existing decks, and every one is unambiguous under the CURRENT rules.

| id (both splits) | Tests | Train message | Expect | Calibration `should_fail` |
|---|---|---|---|---|
| `edit_polite_ordinal` | edit phrased as a polite question, with an ordinal | "Could you make the second slide less wordy?" | edit [1] | discuss (asks instead of acting) |
| `edit_last_slide` | a "last" reference | "Simplify the last slide: drop the stat cards and keep just the verdict and the call to action" | edit [9] | the reference with targets [10] (1-based slip) |
| `edit_multi_slide` | a range reference | "Slides 4-6 are too text-heavy; trim each to three short bullets" | edit [3,4,5] | the reference with targets [4,5,6] |
| `discuss_slide_question` | a question that names a slide | "Why is the accessibility point on slide 7?" | discuss | edit [6] |

Held-out uses different phrasings on its own deck: a digit ordinal, "final", an "and" list and a different
question (Appendix H).

Not added:
- A casual design-switch case: held-out `confirm_design` is already casual.
- A data-needing edit: `ask_data` is "before a deck can be planned" (`architect.py:22`), so it is not
  unambiguous.
- Any add/insert case: #314.
- Anything for `build_request` deck length: see the Goal.

**D7 — Calibration negatives are the realistic wrong answer.**
- A position case's `should_fail` is the reference with only `target_positions` shifted by +1.
- An intent case's `should_fail` takes the risky intent.
- The existing 5 cases per split stay **byte-identical**.

**D8 — `judge_prompt.md` does not change.** Its edit rule already fails an off-by-one slip and covers
multi-slide edits. Its discuss rule covers a question about a slide.

**D9 — How intent accuracy is read.** The read-only `evals/intent_report.py` (Task 2) reads the run's
traces. Harness, scorers and judge stay untouched.
- *Intent accuracy:* got intent == expected intent, over non-infra rows. A row with no output counts as
  wrong and is also reported as `no_output`.
- *Position accuracy:* over rows whose expected AND got intent are both edit, the share whose
  `set(target_positions)` equals the expected set.
- Held-out runs print aggregates only.

**D10 — Sequencing for an honest BEFORE.**
- Tasks 5–6 may land at any time: evals never run `architect_node`.
- **Task 7 (regeneration), S0 and Task 8 (prompt) wait until every Task 4 run has finished.**

**D11 — Re-calibration after regeneration is optional.**
- Task 7 changes only `payload.json`, by adding two keys the judge never sees.
- Its verify step proves the judge inputs are identical, so calibration holds.
- C3 is P3.

**D12 — Promotion replaces the default.** Graph v1 is unreleased, so the finalist replaces
`INSTRUCTIONS` and the manifest through `promote` (precedent 45ce906c). There is no migration and no
contract re-record.

**D13 — If Task 9 stops (no finalist).** S0 is the v1 prompt on the regenerated payloads, run before any
candidate (Task 7½).

"Not worse" means that on both intent accuracy and position accuracy over the 4 new train cases, S0 ≥
B1 − 1/denominator. That is the skill's one-repeat noise rule, applied to S0's ×1 rows.

- **Branch (i) — a finalist is accepted.** Ship everything.
  - A2 is met deterministically: the Task 5 resolver, and Task 7's proof on every eval edit message.
  - It is met end to end: F1 position accuracy against B1 (×5 each), plus the Task 10 prompt contract.
- **Branch (ii) — no finalist, S0 not worse than B1.** Ship Tasks 1–7. The payload keys go out with the
  unchanged v1 prompt, which does not name them.
  - The deterministic part of A2 is met in production: the model receives resolved positions.
  - End to end, A2 is measured only by S0 (×1, a weak signal). Record it as partially met in the README
    and on the issue.
- **Branch (iii) — no finalist, S0 worse than B1.** The supervisor reverts the Task 6 and Task 7 commits
  with `git revert` (no history rewrite). Tasks 1–5 stay, including the module and its tests.
  - The deterministic resolution of A2 exists as a tested library but is not wired in.
  - A2 is not met end to end. Document this; the issue stays open.

---

## Global constraints

- **Environment.**
  - Use the per-worktree uv venv: `uv run …`.
  - Never use `pip install`, never `git stash`, never `gh auth switch`.
  - All paths and commands run in `/Users/robert.whiffin/Repos/ai-slide-generator/.claude/worktrees/issue-313`.
  - Import `src.core.database` before other `src.*` imports in tests and scripts that touch
    `src.services`.
  - Unit tests use disposable sqlite.
- **Live calls.** No live model calls in any dispatched task. Live evals (Task 4, S0, the search sweeps
  in Task 8, Task 9) are run **by the supervisor only**. No deploys.
- **Commits.** The supervisor commits after review, with the trailer `Co-authored-by: Isaac
  <no-reply@databricks.com>`. Commit messages contain no held-out case content.
- **Do not edit** `ArchitectOutput`, `DeckSpec`/`SlideSpec`, `judge_prompt.md`, scorers or
  `evals/configs/prices.yaml`.
- **Testing discipline.**
  - Baselines are cause-sets: diff failing-test CAUSES, not counts.
  - Sabotage-verify every approved test (executing-plans-tellr §1).

## Held-out discipline

| Agent | May read `cases_heldout/`, `heldout.py`, `test_pack_architect_heldout.py`, Appendix H | Notes |
|---|---|---|
| Task 3 case author (test author and implementer) | yes, it writes them | Never copies held-out text into prompt or README prose. |
| Task 7 payload-regeneration agents | yes, they regenerate them | Same. |
| Supervisor | yes | Reports held-out results as aggregates only; writes no held-out content in commit messages. |
| Task 8 prompt-candidate author | **NO** | Also barred from this plan file, `~/tellr-loop/issues/issue-313/` (the ledger holds held-out aggregates), the `tellr-agent-eval-heldout` experiment, B4/F4 results, and `git show`/`git log -p` of commits touching those paths. Every repo-wide grep uses `--exclude-dir=cases_heldout`. |
| Tasks 1, 2, 5, 6, 10, 11 | not needed | Task 11 writes held-out ids and aggregates only. |

## File map

| Area | Files |
|---|---|
| Probe fix | `evals/run_eval.py`, `tests/unit/evals/test_run_eval.py` |
| Intent report | `evals/intent_report.py` (new), `tests/unit/evals/test_intent_report.py` (new) |
| Cases | `evals/packs/architect/{mutations.py,heldout.py}`, `evals/packs/architect/cases/*` and `cases_heldout/*`, `tests/unit/evals/{test_pack_architect.py,test_pack_architect_heldout.py,test_cross_split.py,test_pack_generation_isolation.py}`, `evals/README.md` (two count sentences) |
| Slide numbering | `src/domain/slide_numbering.py` (new), `tests/unit/test_slide_numbering.py` (new) |
| Node and payload contract | `src/services/graph/nodes.py`, `src/services/agent_model_payload.py`, `tests/fixtures/model_payload_keys.py`, `tests/agentic/payloads.py`, `tests/unit/test_graph_nodes.py`, `tests/unit/test_agentic_layer_is_placed_and_gated.py` (docstring only), `tests/unit/test_agentic_payload_builders.py` (new) |
| Regeneration | the case generators and pack tests above, plus the 18 committed architect `payload.json` files |
| Candidates | `evals/configs/architect/<name>.yaml` and `.md` |
| Promotion | `src/core/skills/architect.py`, `src/services/agent_definition_manifest_v1.py` (via promote), `tests/unit/test_packaged_release_loader.py:24` (via promote), `tests/unit/test_graph_definition_manifest.py:707` (via promote) and `:1158-1159` (by hand), `tests/unit/test_architect_edit_prompt.py` |
| Docs | `CONTEXT.md`, `docs/technical/backend-overview.md`, `evals/README.md` |

## Order and parallelism

```
Task 1 (probe) ─┐
Task 2 (report) ├─> [commit] ─> Task 4 SUPERVISOR: C1 C2 B1 →(fix repeats) B2 B3 B4 ─┐
Task 3 (cases) ─┘                                                                    │
Task 5 (slide_numbering) ─> Task 6 (node + payload keys) ────────────────────────────┤
                                                                                     v
                                   Task 7 (regenerate payloads; waits for ALL of Task 4)
                                                                                     v
                                   Task 7½ SUPERVISOR: S0 (v1 prompt, new payloads, ×1)
                                                                                     v
                Task 8 (candidate author, train-only) <-> SUPERVISOR search sweeps S1 [S2 S3]
                                                                                     v
                         Task 9 SUPERVISOR: F1 F2 F3 F4 [C3]  ── stop? → D13 branch (ii) or (iii)
                                                                                     v
                                     Task 10 (promote finalist) -> Task 11 (docs + README numbers)
```

Tasks 1, 2, 3 and 5 can run in parallel, because their file sets do not overlap.

---

## Task 1: The eval probe resolves `system.ai.*` names through the gateway mapping

**Models:** test=sonnet impl=haiku (the plan gives the code)

**Files:** `evals/run_eval.py`, `tests/unit/evals/test_run_eval.py`

Behaviour:
- `_endpoint_reachable(endpoint_name)` probes
  `WorkspaceClient().serving_endpoints.get(gateway_endpoint_name(endpoint_name))`.
  - `system.ai.<m>` is probed as `databricks-<m>`.
  - A legacy name is probed as is.
  - The agent call keeps the configured name.
- `validate_endpoint`'s "not reachable" error names both the configured name and the probed name.

```python
from src.services.model_endpoint_catalog import gateway_endpoint_name

def _endpoint_reachable(endpoint_name: str) -> bool:
    """Probe the serving endpoint behind *endpoint_name*; True if it resolves.

    A ``system.ai.<m>`` gateway model name is not a serving-endpoint name, so the probe
    looks up ``gateway_endpoint_name(name)`` (``databricks-<m>``); the agent call keeps
    the configured name.
    """
    try:
        from databricks.sdk import WorkspaceClient

        WorkspaceClient().serving_endpoints.get(gateway_endpoint_name(endpoint_name))
        return True
    except Exception:  # noqa: BLE001 - any failure means not reachable
        return False
```

Steps:
- [ ] **Step 1 (test author).** In `tests/unit/evals/test_run_eval.py`, monkeypatch
  `databricks.sdk.WorkspaceClient` with a fake that records `serving_endpoints.get(name)`, then test:
  - `_endpoint_reachable("system.ai.claude-opus-5")` is True and probes exactly
    `["databricks-claude-opus-5"]`;
  - `"databricks-claude-sonnet-5"` is probed as is;
  - a raising fake gives False;
  - the unreachable `SystemExit` text contains both names.

  Keep `test_unservable_endpoint_fails_fast_naming_the_field` and
  `test_validate_endpoint_probes_the_configured_endpoint` (`:49-63`) unchanged. Confirm red. Leave
  uncommitted.
- [ ] **Step 2 (implementer):** make them green without editing tests.
- [ ] **Step 3.** `uv run pytest tests/unit/evals/test_run_eval.py tests/unit/test_model_endpoint_catalog.py -n 4 -q`.
  Sabotage: drop the `gateway_endpoint_name(...)` call, and the first new test goes red.

## Task 2: Read-only intent/position report over one eval run

**Models:** test=opus impl=sonnet

**Files:** `evals/intent_report.py` (new), `tests/unit/evals/test_intent_report.py` (new)

Interface:

```python
def row_from_trace(trace, *, split: str) -> dict | None:
    """One counted row, or None for an infra-error row.

    Keys: case_id, expected_intent, expected_positions (sorted list; [] unless edit),
    got_intent (None when structured is not a dict), got_positions (sorted list),
    expected_category ("pass"|"fail"|"skip"|None).
    ``expect`` comes from the trace's Expectation named "expect"; if absent, from
    ``evals.harness.case.load_case("architect", case_id, split=split).expect``.
    """

def summarise(rows: list[dict]) -> dict:
    """{"rows", "intent_correct", "intent_accuracy", "no_output", "edit_rows",
        "positions_correct", "position_accuracy", "expected_category_pass",
        "per_case": {case_id: {same keys, plus "got_intents": {intent_or_"none": count}}}}
    Accuracies are None when their denominator is 0. edit_rows = rows whose expected
    AND got intent are both "edit"."""

def report(run_id: str, *, tracking_uri: str | None = None, cases: list[str] | None = None) -> dict
def main(argv: list[str] | None = None) -> int
```

Behaviour:
- `uri = tracking_uri or mlflow_run.default_tracking_uri()`, then `run = MlflowClient(uri).get_run(run_id)`,
  then `mlflow.set_tracking_uri(uri)`.
- Read the traces with `traces = mlflow.search_traces(run_id=run_id,
  locations=[run.info.experiment_id], return_type="list")`. Spans are included, because previews are
  truncated.
  - Inputs come from `json.loads(trace.data.request)`.
  - Outputs come from `json.loads(trace.data.response)`.
  - An `infra_error` row is skipped and counted as `infra_skipped`.
- The split is `run.data.tags.get("split", "train")`.
- CLI: `uv run python -m evals.intent_report --run-id ID [--cases a,b] [--tracking-uri URI] [--json]`.
  - **Train:** a header (run id, split, `config_name`, `content_hash[:12]`, `cases_digest[:12]`), one line
    per case (rows, intent_ok, got_intents, edit_rows, positions_ok, expected_category_pass), and an ALL
    line.
  - **Held-out:** ONE aggregate line with no case ids. `--cases` only restricts the rows aggregated.
  - It writes nothing.

Steps:
- [ ] **Step 1 (test author).**
  - Write table-driven `summarise` tests covering:
    - a correct edit;
    - an off-by-one edit (intent right, positions wrong, `expected_category` fail);
    - a polite edit answered with discuss;
    - discuss answered with edit;
    - no output;
    - a multi-position set compared ignoring order and duplicates;
    - empty input (accuracies None).
  - Write one store-backed test:
    - Use the `tracking` pattern (`tests/unit/evals/test_mlflow_run.py:535`): a tmp sqlite URI, `chdir`
      to tmp.
    - **Call `mlflow.set_experiment("tellr-agent-eval-heldout")` (or another non-default name) before
      `mlflow.start_run()`**, with tag `split`.
    - Call `mlflow.genai.evaluate` over 2 cases × 2 repeats plus 1 infra row. Use a traced predict_fn
      returning `{"structured": …, "infra_error": bool}`, expectations `{"expect": …}`, and a trivial
      `expected_category` scorer.
    - Assert the exact counts from `report(...)`.
  - Write a held-out CLI test (capsys): no case id in the output, exactly one line.
  - **Sabotage 1:** read `expected_category` instead of the structured intent, and the **off-by-one** row
    turns the intent test red. It is the only row the two readings disagree on.
  - **Sabotage 2:** drop `locations=`, and the store-backed test goes red.
  - Confirm red. Leave uncommitted.
- [ ] **Step 2 (implementer):** implement without editing tests.
- [ ] **Step 3.** `uv run pytest tests/unit/evals/test_intent_report.py tests/unit/evals/test_mlflow_run.py -n 4 -q`.

## Task 3: Eval cases for #313, train and held-out, in the CURRENT v1 payload shape

**Models:** test=opus impl=sonnet (case content is given below and in Appendix H). The case author may
read and write `cases_heldout/`.

**Files:**
- `evals/packs/architect/{mutations.py,heldout.py}`;
- the 4 new dirs under `cases/` and the 4 under `cases_heldout/`;
- `tests/unit/evals/{test_pack_architect.py,test_pack_architect_heldout.py,test_cross_split.py,test_pack_generation_isolation.py}`;
- `evals/README.md` (two sentences).

Behaviour:
- Payloads stay in the **9-key v1 shape**.
- The 5 existing case dirs per split stay **byte-identical**.
- All 8 new cases:
  - are `kind: mutation`, with `design_system_active: true`;
  - use the deck: the prior exchange, `current_deck_spec` = that split's gold, and
    `committed_slide_count` 10 (train) or 6 (held-out);
  - carry a `fault` sentence naming the trap.
- References:
  - are full `ArchitectOutput`s;
  - each edit reference returns the full `deck_spec`: the gold spec with only the **target** slides
    revised.
  - A target slide changes `content_brief`, and also changes `purpose` only where the gold purpose
    contradicts the request. That happens only for train `edit_last_slide`, whose gold purpose says
    "with a visual scorecard".
  - Deck-level fields and every non-target slide are unchanged.
- Calibrations follow D7.
- Generation stays idempotent:
  - a module-level `HAS_DECK` replaces the inline tuple at `mutations.py:68`;
  - helpers `_revised_spec(deck, briefs: dict[int, str], purposes: dict[int, str] | None = None) -> dict`
    (validated with `DeckSpec`) and `_slipped(reference) -> dict` (targets +1);
  - revised briefs are module constants (precedent `EDIT_BRIEF_1`, `mutations.py:103`).

Train cases (deck: `evals/fixtures/meridian/deck_spec.json`):

| id | message (exact) | expect | reference | should_fail |
|---|---|---|---|---|
| `edit_polite_ordinal` | `Could you make the second slide less wordy?` | `{"intent": "edit", "positions": [1]}` | edit [1]; message `I'll cut the second slide down to one short line and three terse bullets.`; brief[1] = `State in one short line that presentations drive persuasion and decisions yet most are stuck in a 30-year-old format, then three terse bullets: font substitution, fixed-resolution layouts and bloated files (8–15 MB)` | discuss, `Happy to tighten it. Which parts of the second slide feel too wordy to you?` |
| `edit_last_slide` | `Simplify the last slide: drop the stat cards and keep just the verdict and the call to action` | `{"intent": "edit", "positions": [9]}` | edit [9]; message `I'll simplify the last slide to the verdict and the call to action.`; brief[9] = `Deliver the final verdict in one line: HTML slides are the stronger format. No stat cards. End with the call to action: try an HTML slide framework for your next presentation`; purpose[9] = `Closing slide — verdict and call to action` | `_slipped` → targets [10] |
| `edit_multi_slide` | `Slides 4-6 are too text-heavy; trim each to three short bullets` | `{"intent": "edit", "positions": [3, 4, 5]}` | edit [3,4,5]; message `I'll trim slides 4, 5 and 6 to three short bullets each.`; brief[3] = `Show that HTML slides adapt fluidly to any screen size while PowerPoint locks content to a fixed canvas, as three short bullets`; brief[4] = `Explain that CSS gives HTML slides precise, reliable typography with no font substitution, as three short bullets`; brief[5] = `Show that HTML slides support live demos, embedded video and interactive charts natively in the browser, as three short bullets` | `_slipped` → targets [4,5,6] |
| `discuss_slide_question` | `Why is the accessibility point on slide 7?` | `{"intent": "discuss"}` | discuss; `Slide 7 is the fourth evidence beat: after responsiveness, typography and interactivity, it shows that HTML is accessible by design, and it sets up the collaboration beat on slide 8. I can move or reword it if you like.` | edit [6], `I'll rework the accessibility point on slide 7.` (no deck_spec) |

Held-out cases: **Appendix H**.

Steps:
- [ ] **Step 1 (test author).** Extend both pack self-test files.
  - **Lists:** `CASE_IDS` has 9 entries; `MUTATIONS` gains the 4 new ids; extend `EXPECT` and
    `HAS_DECK`; rename `test_exactly_the_five_cases` to `test_exactly_the_pinned_cases`.
  - **`test_messages`:** pins the 4 new messages exactly.
  - **New `test_edit_references_revise_only_their_targets`**, parametrised over the edit cases including
    `edit_request`:
    - deck-level fields == gold, and every non-target slide == gold;
    - each target slide differs from gold only in `content_brief`, or in `content_brief` and `purpose`;
    - the brief differs from gold;
    - `purpose` differs **only** for train `edit_last_slide` (in held-out, nowhere);
    - per-case markers:
      - `edit_polite_ordinal`: the brief is shorter than gold's and contains "three terse bullets";
      - `edit_last_slide`: the brief contains "No stat cards" and "call to action", and the purpose no
        longer contains "scorecard";
      - each `edit_multi_slide` brief ends "as three short bullets".

    Held-out markers are in Appendix H.
  - **New `test_slipped_calibrations`:** for `edit_last_slide` and `edit_multi_slide`, `should_fail` ==
    reference except `target_positions == [p + 1 for p in targets]`.
  - **Wrong-intent calibrations:** `test_calibration_has_the_wrong_intent` excludes `edit_request`,
    `edit_last_slide` and `edit_multi_slide`. For `edit_polite_ordinal`, `should_fail.intent ==
    "discuss"`. For `discuss_slide_question`, `should_fail.intent == "edit"` with targets [6] in train.
  - **Fairness on the train gold:**
    - pos 1 brief contains "bullet";
    - pos 9 brief contains "three stat cards" and "call to action";
    - pos 9 purpose contains "scorecard";
    - pos 3/4/5 purposes start "Evidence beat 1"/"2"/"3";
    - pos 6 purpose contains "Accessibility".

    Held-out fairness is in Appendix H.
  - **`test_cross_split.py`:**
    - add the 4 ids to `HELDOUT_CASE_IDS["architect"]`;
    - replace `test_total_is_thirty_five` with `test_total_heldout_case_count` (== 39).
  - **`test_pack_generation_isolation.py:29`:** an expected count per agent (`{"architect": 9}`, default
    5).
  - Confirm red. Leave uncommitted.
- [ ] **Step 2 (implementer).**
  - Implement the generators.
  - Run `uv run python -m evals.packs.architect.mutations` and `uv run python -m evals.packs.architect.heldout`.
  - Update the README, and no other README text:
    - line 12: "Five per agent, 35 in total across the seven" becomes "Five per agent (nine for the
      architect), 39 in total across the seven";
    - line 71: "Each agent has a second, separate set of five cases (35 in total)" becomes "Each agent
      has a second, separate set of cases (five per agent, nine for the architect; 39 in total)".
- [ ] **Step 3, verify.**
  - `uv run pytest tests/unit/evals -n 4 -q`.
  - `git status --porcelain evals/packs/architect` shows only the 8 new dirs and the two generators.
  - `git diff --exit-code -- evals/packs/architect/cases/{build_request,edit_request,ask_data,confirm_design,discuss} evals/packs/architect/cases_heldout/{build_request,edit_request,ask_data,confirm_design,discuss}`
    exits 0.
  - Sabotage: change one new brief constant, and `test_committed_cases_are_current` goes red.

## Task 4 (SUPERVISOR-run): calibrate, then measure BEFORE on v1

**Models:** test=sonnet impl=sonnet. The supervisor runs every live command; a delegated read-out uses
sonnet. Nothing here is dispatched for implementation.

Preconditions:
- Tasks 1–3 are committed.
- Everything runs from the worktree root, with the default `--profile tellr-dev`.

Steps, in this order:
- [ ] **C1** `uv run python -m evals.run_eval --agent architect --calibrate`, then **C2** the same with
  `--split heldout`.
  - All 9 cases per split must be trusted.
  - Re-run only rows with a judge-parse or network error.
  - A misclassified case STOPS this task and goes back to Task 3.
- [ ] **B1** `uv run python -m evals.run_eval --agent architect --config v1-baseline --repeats 5 --cases edit_polite_ordinal,edit_last_slide,edit_multi_slide,discuss_slide_question`
- [ ] **Fix the remaining repeats now** (Measurement plan). Use B1's measured `mean_input_tokens` and
  `mean_output_tokens`, and project the total: 0.41 + spent + every remaining run at measured rates.
  - If the projection is ≤ USD 20, keep B3/F3 ×3 and B4/F4 ×2.
  - Otherwise apply the ruled drop order (B4/F4 ×1, then B3/F3 ×2).
  - The repeats chosen here are used again in Task 9. Before and after are always symmetric.
- [ ] **B2** `… --config v1-baseline --repeats 5 --cases edit_request,confirm_design,discuss`. Never
  dropped.
- [ ] **B3** `… --config v1-baseline --repeats 3 --cases build_request,ask_data` (×2 only under the drop
  order).
  - These two cases have no current deck, so `slide_numbering` and `slide_references` are empty for
    them. Only the prompt text can move them; B3 is a regression guard.
- [ ] **B4** `uv run python -m evals.run_eval --agent architect --config v1-baseline --split heldout --repeats 2`
  (×1 under the drop order).
- [ ] **Report each run:**
  - `uv run python -m evals.intent_report --run-id <id>`;
  - for B4, also `--cases edit_polite_ordinal,edit_last_slide,edit_multi_slide,discuss_slide_question`
    (aggregate only).
- [ ] **Ledger.** For each run record: run id, git sha, `cases_digest`, rows, pass rate, per-case pass
  rate (train only), intent accuracy, position accuracy, `no_output`, judge errors, mean tokens, and
  USD (agent plus judge).
  - **This satisfies A1.**
  - Group the train failures by cause from the stored rationales.

## Task 5: `src/domain/slide_numbering.py` — deterministic slide numbers and references

**Models:** test=opus impl=sonnet

**Files:** `src/domain/slide_numbering.py` (new), `tests/unit/test_slide_numbering.py` (new)

Interface (pure; imports `re` and `typing` only; returns JSON-ready lists and dicts):

```python
MAX_RANGE_SPAN = 100

def slide_numbering(positions: Iterable[int]) -> list[dict[str, int]]:
    """[{"slide_number": 1, "position": p0}, ...] over the DISTINCT positions, ascending."""

def resolve_slide_references(text: str | None, positions: Iterable[int]) -> list[dict]:
    """Each D3 reference in *text*, in order of appearance:
    {"text": str, "slide_numbers": [int], "positions": [int], "out_of_range": [int]}.
    [] when *text* is empty/None or *positions* is empty."""

def latest_user_message(conversation: Sequence[Mapping] | None, fallback: str | None) -> str | None:
    """Content of the last turn whose role is "user"; *fallback* when there is none (D4)."""

def architect_slide_payload(conversation, message, positions, *, describe_only: bool = False) -> dict[str, list]:
    """{"slide_numbering": slide_numbering(positions),
        "slide_references": [] if describe_only else
            resolve_slide_references(latest_user_message(conversation, message), positions)}
    The ONE helper architect_node, the eval generators and tests/agentic/payloads.py all call."""

def edit_ignores_references(target_positions: Iterable[int], references: Sequence[Mapping]) -> bool:
    """True iff the references resolve at least one in-range position and *target_positions*
    is disjoint from all of them (D5)."""
```

The module docstring states D1, D3 (including the unresolved forms, the indefinite exclusion and the
known limit) and D4. Those are the docs #314 builds on.

Implementation skeleton (structure only; the test table is the contract):
- word tables `_CARDINALS` (one–twenty) and `_ORDINALS` (first–twentieth);
- every word token wrapped as `(?<![-\w])WORD(?!-[a-z])`;
- one compiled alternation tried longest-first: F3 plural list, then F1 singular with optional `and`/`&`
  list, then F4 ordinal (relative ordinals before plain ones);
- `finditer` over the text;
- an F4 match is skipped when
  `re.search(r"\b(?:a|an|another|new|extra|additional|one more)\s+$", text[:m.start()], re.I)`;
- each kept match expanded to numbers, then mapped through `sorted(set(positions))`.

Steps:
- [ ] **Step 1 (test author).** Write `tests/unit/test_slide_numbering.py` with
  `@pytest.mark.parametrize` tables. Each row is `(text, positions, expected list of
  (text, slide_numbers, positions, out_of_range))`. The default deck is positions 0–9.

  **Resolved:**
  - **Singles.**
    - `slide 2`; `Slide 2` (the text keeps its case); `slide #2`; `slide number 2`; `slide two`;
      `slide 10`.
    - `slide twenty` (deck 0–24).
    - `slide 11` → `([11], [], [11])`; `slide 0` → `([0], [], [0])`.
  - **Singular lists.**
    - `slide 2 and 3` and `slide 2 & 3` → [2,3]→[1,2].
    - `On slide 2, 3 cards instead of a list` → exactly one ref, `slide 2`.
    - `move slide 2 to 5` → exactly one ref, `slide 2`.
  - **Ordinals.**
    - `the second slide` (text `second slide`); `the 2nd slide`; `the first slide`.
    - `Add a chart to the second slide` → [2]→[1].
    - `last slide: drop the cards`, `the last slide` and `the final slide` → [10]→[9].
    - `the penultimate slide`, `the second-to-last slide`, `the second to last slide` and
      `the second last slide` → [9]→[8].
    - `the twelfth slide` → out of range [12].
    - In deck 0–24: `the 11th slide`, `the 12th slide`, `the 13th slide`, `the 21st slide` (→ [21]→[20]),
      `the 22nd slide`, `the 23rd slide`.
  - **Plural ranges and lists.**
    - `slides 2-4`, `slides 2–4`, `slides 2 - 4`, `slides 2 to 4`, `slides 2 through 4`,
      `slides 2 thru 4`, `slide 2-4` and `slides 4-2` → [2,3,4]→[1,2,3].
    - `slides 2 and 3`, `slides 2 & 3` and `slides two and three` → [2,3].
    - `slides 2, 3 and 5` and `slides 2, 3, and 5` → [2,3,5]→[1,2,4].
    - `slides 2-4 and 6` → [2,3,4,6].
    - `slides 9-12` → numbers [9,10,11,12], positions [8,9], out_of_range [11,12].
  - **Several references.**
    - `make slide 3 match slide 2` → two refs, in order.
    - `slide 2 and slide 4` → two refs.
    - `slides 2 and the cover` → one ref [2].
  - **Known limit (pinned).** `On slides 2, 3 bullets each` → [2,3].

  **No reference:**
  - Indefinite ordinals: `Add a final slide with next steps`, `add a second slide on pricing`,
    `I need a third slide for the roadmap`, `add another final slide`, `an extra second slide`,
    `one more final slide`, `a new third slide`, `an additional 4th slide`.
  - Hyphenated words: `the twenty-first slide`, `the thirty-second slide`, `slide twenty-one`.
  - Span: `slides 1-200`.
  - Counts: `a 10-slide deck`, `10 slides`, `Build five slides about X`.
  - Relative and plural: `the last two slides`, `the first three slides`, `the second and third slides`.
  - Deictic and semantic: `this slide`, `the next slide`, `a new slide`, `the cover`, `the agenda slide`.
  - `slides 2 or 3` → only `slides 2`.
  - `slideshow`, `Slidev`, `slides`, `""`, `None`.

  **Numbering:**
  - `slide_numbering([5, 0, 2, 2])` → `[(1,0), (2,2), (3,5)]`.
  - Gapped deck `[0, 2, 5]`: `slide 2`→[2]; `slide 3`→[5]; `the last slide`→[5]; `slide 4` → out of
    range [4].
  - Empty deck: numbering `[]`, and references `[]` for `slide 2`.

  **Helpers:**
  - `latest_user_message`: the last user turn wins over an assistant turn after it; a missing user turn
    or a `None` conversation falls back to `message`.
  - `architect_slide_payload(..., describe_only=True)` returns references `[]` and an unchanged
    numbering.
  - `edit_ignores_references`:
    - targets [2] vs `slide 2` (pos 1) → True;
    - targets [1] → False;
    - targets [2] vs `make slide 3 match slide 2` → False;
    - only out-of-range references → False;
    - no references → False.

  **The four A2 phrases are named tests:** "slide 2"→1, "the second slide"→1, "the last slide"→count−1,
  "slides 2-4"→[1,2,3].

  **Sabotage:**
  - Return `number` instead of the mapped position, and every A2 test goes red.
  - Remove the indefinite exclusion, and `Add a final slide…` goes red.
  - Remove the lookbehind, and `the twenty-first slide` goes red.

  Confirm red. Leave uncommitted.
- [ ] **Step 2 (implementer):** implement without editing tests.
- [ ] **Step 3.** `uv run pytest tests/unit/test_slide_numbering.py -n 4 -q`.
  `grep -nE '^(import|from) ' src/domain/slide_numbering.py` must list only `__future__`, `re` and
  `typing`.

## Task 6: `architect_node` sends `slide_numbering` and `slide_references`; log-only guard

**Models:** test=opus impl=sonnet

**Files:**
- `src/services/graph/nodes.py`, `src/services/agent_model_payload.py`;
- `tests/fixtures/model_payload_keys.py`, `tests/agentic/payloads.py`;
- `tests/unit/test_graph_nodes.py`, `tests/unit/test_agentic_payload_builders.py` (new);
- `tests/unit/test_agentic_layer_is_placed_and_gated.py` (docstring "nine keys" → "eleven" only).

Behaviour:
1. In `architect_node`, before `payload` is built:
   - Move the existing `describe_only = bool(scoped_vals(state, "describe_only"))` line (`nodes.py:1626`)
     up so there is still one definition, now above the payload.
   - Add a private helper `_deck_positions(committed_positions, prior_spec) -> list[int]` (D1): the
     sorted committed positions if there are any, else the persisted spec's positions, else `[]`.

   ```python
   conversation = _conversation(session_id)
   slide_payload = architect_slide_payload(
       conversation,
       state.get("architect_message"),
       _deck_positions(committed_positions, prior_spec),
       describe_only=describe_only,
   )
   payload = {
       "conversation": conversation,
       "message": state.get("architect_message"),
       "current_deck_spec": persisted_spec_dict,
       "committed_slide_count": len(committed_htmls),
       # #313: the user's 1-based slide numbers mapped to positions, and every slide
       # reference in the user's latest message already resolved (src/domain/slide_numbering.py),
       # so the model copies positions instead of computing them.
       "slide_numbering": slide_payload["slide_numbering"],
       "slide_references": slide_payload["slide_references"],
       "previous_deck_review": prior_review,
       ...  # the remaining keys unchanged
   }
   ```

   The keys must be literal entries.
2. Log-only guard (D5). Inside `if intent == "edit":`, after `updates["target_positions"]` is set
   (`nodes.py:1769`):

   ```python
   if not describe_only and edit_ignores_references(out.target_positions, slide_payload["slide_references"]):
       logger.warning(...)
   ```

   The warning names the targets and each reference's `text` and positions, with
   `extra={"session_id": session_id}`. `updates` is unchanged.
3. Add `"slide_numbering"` and `"slide_references"` to `MODEL_PAYLOAD_KEYS["architect"]`
   (`agent_model_payload.py:56-68`).
4. Correct the stale sentence in the `_persisted_spec_describes_these_rows` docstring
   (`nodes.py:1018-1023`). It is docstring-only: every mutation route now renumbers through
   `_rewrite_deck_spec_slides`.
5. **`tests/agentic/payloads.py` ownership.**
   - The **test author** owns the `ARCHITECT_PAYLOAD_KEYS` tuple: both keys added in node order, and the
     docstrings' "nine" changed to "eleven".
   - The **implementer** owns the `architect_payload()` body. It computes the two keys with
     `architect_slide_payload(payload["conversation"], message, positions)` from the **post-override**
     `conversation` and `current_deck_spec`. The positions are those of `current_deck_spec["slides"]` when
     it is a dict, else `[]`. An explicit override of either key still wins.
6. Do NOT change `REQUIRED_SMOKE_PAYLOADS` (two reasons in Context).

Steps:
- [ ] **Step 1 (test author).** Use the patterns at `tests/unit/test_architect_design_system_library.py:104`
  (`env.skills.calls_for("architect")[0]["payload"]`), `_edit_out`/`_revised`
  (`tests/unit/test_graph_nodes.py:134,153`) and `graph_env.state(describe_only=scoped(TURN, True))`
  (`:733`). Add a new class, `TestArchitectSlideNumbering`, in `test_graph_nodes.py`:
  - **(a)** 3 seeded rows and a matching persisted spec; a discuss output; message `Make slide 2 shorter`.
    Then:
    - `slide_numbering` is three dicts, `1→0`, `2→1`, `3→2`;
    - `slide_references[0] == {"text": "slide 2", "slide_numbers": [2], "positions": [1], "out_of_range": []}`.
  - **(b)** No rows and no spec (a build): both keys are `[]`.
  - **(c)** No rows, and a persisted spec at positions (0,1,2): numbering comes from the spec.
  - **(d)** Gapped rows: monkeypatch `nodes._committed_slide_rows` to return rows at [0, 2, 5]. `slide 3`
    resolves to [5].
  - **(e)** The latest user turn wins. Monkeypatch `nodes._conversation` to return [user "Put our figures
    on slide 4", assistant "…"], with `architect_message="Q3 revenue was 10"` over 5 rows. The reference
    resolves `slide 4`→[3]. Sabotage: resolve `message` instead, and (e) goes red.
  - **(f)** The guard, using caplog on `src.services.graph.nodes` at WARNING, over 3 rows plus the spec,
    with the message `slide 2`:
    - an edit with targets [2] and the spec revised at 2 → one warning, and
      `updates["target_positions"] == [2]`;
    - targets [1] with the spec revised at 1 → no warning;
    - a describe-only turn → no warning.

    Sabotage: remove the log call, and (f) goes red.
  - **(g)** Describe-only references. Monkeypatch `nodes._conversation` to end with user "Make slide 2
    shorter". Use 3 rows plus the spec, `describe_only=scoped(TURN, True)`, and `architect_message` =
    the sweeper text. Then `slide_references == []`, and `slide_numbering` still has 3 entries. Sabotage:
    drop the `describe_only=` argument, and (g) goes red.

  Also in Step 1:
  - Write the new `tests/unit/test_agentic_payload_builders.py`:
    - `architect_payload("Make slide 2 shorter", current_deck_spec=deck_spec_dict([...3 slides...],
      title="t"))` resolves positions [1];
    - an overridden `conversation` ending in a user "slide 3" resolves [2];
    - an explicit `slide_references=[]` override wins;
    - an unknown key still raises `KeyError`.
  - Update the literal fixtures: `EVERY_MODEL_CALL`'s architect set, and `ARCHITECT_PAYLOAD_KEYS`.

  Confirm red. Leave uncommitted.
- [ ] **Step 2 (implementer):** the node, the allowlist, the `architect_payload()` body and the docstring.
  Do not edit tests.
- [ ] **Step 3.**
  - `uv run pytest tests/unit/test_graph_nodes.py tests/unit/test_agent_model_payload.py tests/unit/test_agentic_layer_is_placed_and_gated.py tests/unit/test_agentic_payload_builders.py tests/unit/test_architect_design_system_library.py tests/unit/test_agent_test_workbench.py tests/unit/test_graph_configuration_bootstrap.py tests/unit/evals -n 4 -q`
  - then `uv run pytest tests/unit -n 4 -q`, comparing the failing-cause set against the baseline.
  - The integration tests need PostgreSQL, so CI covers them. The stub architect
    (`tests/integration/conftest_stub_skills.py:316`) ignores the new keys.

## Task 7: Regenerate both splits' architect payloads with the production helper

**Models:** test=opus impl=sonnet. These agents may read and write `cases_heldout/`.
**Wait for:** every Task 4 run complete and recorded (D10), plus Tasks 5–6.

**Files:**
- `evals/packs/architect/{mutations.py,heldout.py}`;
- the 18 committed architect `payload.json` files;
- `tests/unit/evals/test_pack_architect.py`, `tests/unit/evals/test_pack_architect_heldout.py`.

Behaviour:
- Both `_payload` builders call
  `architect_slide_payload(conversation, msg, [s["position"] for s in deck["slides"]] if has_deck else [])`.
- They add its two keys to the dict passed to `model_payload_for`, right after `committed_slide_count`
  (node order).
- Nothing else in any case file changes.

Steps:
- [ ] **Step 1 (test author).** In both pack test files:
  - **`PAYLOAD_KEYS`** gains the two keys.
  - **`test_slide_numbering_is_the_deck`:** in train, deck cases have 10 entries `n → n-1`, and
    `build_request`/`ask_data` have `[]`. In held-out, deck cases have 6 entries.
  - **`test_slide_references_are_pinned`**, a literal per case. Train:
    - `edit_request` → `[{"text": "slide 2", "slide_numbers": [2], "positions": [1], "out_of_range": []}]`;
    - `edit_polite_ordinal` → `second slide` [2]→[1];
    - `edit_last_slide` → `last slide` [10]→[9];
    - `edit_multi_slide` → `Slides 4-6` [4,5,6]→[3,4,5];
    - `discuss_slide_question` → `slide 7` [7]→[6];
    - `build_request`, `ask_data`, `confirm_design`, `discuss` → `[]`.

    Held-out pins are in Appendix H.
  - **`test_resolved_references_equal_the_expected_edit_positions`:** for every case that expects an
    edit, the union of `slide_references[*].positions` == `expect["positions"]`. This is A2's
    deterministic proof on the eval messages.
  - **`test_a_discuss_case_still_names_a_slide`.**

  Confirm red. Leave uncommitted.
- [ ] **Step 2 (implementer):** update the generators, then regenerate with
  `uv run python -m evals.packs.architect.mutations` and `uv run python -m evals.packs.architect.heldout`.
- [ ] **Step 3, verify.**
  - `uv run pytest tests/unit/evals -n 4 -q`.
  - `git diff --name-only -- evals/packs/architect | grep -v -e 'payload.json$' -e 'mutations.py$' -e 'heldout.py$'`
    prints nothing (D11).
  - Each payload minus the two new keys equals its committed v1-shape payload. That proves `message` and
    `current_deck_spec`, the judge's inputs, are unchanged. Run before the commit:

    ```bash
    uv run python - <<'EOF'
    import json, pathlib, subprocess
    NEW = {"slide_numbering", "slide_references"}
    for p in sorted(pathlib.Path("evals/packs/architect").glob("cases*/*/payload.json")):
        new = json.loads(p.read_text())
        old = json.loads(subprocess.check_output(["git", "show", f"HEAD:{p}"]))
        assert set(new) - set(old) == NEW, p
        assert {k: v for k, v in new.items() if k not in NEW} == old, p
    print("ok")
    EOF
    ```

## Task 7½ (SUPERVISOR-run): S0 — the keys-only effect

**Models:** test=sonnet impl=sonnet (SUPERVISOR-run)
**Wait for:** Task 7 committed. S0 runs before Task 8 writes any candidate.

- [ ] **S0** `uv run python -m evals.run_eval --agent architect --config v1-baseline --repeats 1 --cases edit_polite_ordinal,edit_last_slide,edit_multi_slide,discuss_slide_question`.
  This is the v1 prompt on the regenerated payloads.
- [ ] `uv run python -m evals.intent_report --run-id <S0>`. Record it in the ledger.
- [ ] Hand the S0 run id to the Task 8 author. It is train data. D13 uses S0 if Task 9 stops.

## Task 8: Prompt candidates (TRAIN ONLY; a separate agent; the supervisor runs every sweep)

**Models:** test=opus impl=opus (design judgement; no tests are authored here, and the per-task reviewer
is opus)
**Wait for:** S0 recorded.

Give the candidate author **exactly this brief**, verbatim, and nothing else from this plan:

> You are improving the Tellr **architect** v1 prompt. Load `.claude/skills/optimise-agent-prompt/SKILL.md`
> and follow it, with two overrides:
> 1. **You never run `evals.run_eval`.** You write candidate configs; the supervisor runs each train sweep
>    and hands you its run id.
> 2. The spend cap is the supervisor's. You propose at most 3 candidates.
>
> **Forbidden reads:**
> - `evals/packs/architect/cases_heldout/`, `evals/packs/architect/heldout.py` and
>   `tests/unit/evals/test_pack_architect_heldout.py`;
> - any file under `docs/superpowers/plans/` dated 2026-10-19;
> - everything under `~/tellr-loop/issues/issue-313/`;
> - the MLflow experiment `tellr-agent-eval-heldout`;
> - `git show`/`git log -p` of commits touching those paths.
>
> Pass `--exclude-dir=cases_heldout` to every repo-wide grep.
>
> Your train results are in experiment `tellr-agent-eval`. Read them with
> `uv run python -m evals.intent_report --run-id <id>` and the stored `expected_category`/`judge`
> rationales. Run S0 is the unchanged v1 prompt on the new payloads; start from its failures.
>
> **What changed in the payload: two new keys.**
> - `slide_numbering`: `[{"slide_number": 1, "position": 0}, ...]`, one entry per slide of the current
>   deck, in presentation order. `slide_number` is what the user sees and says; `position` is the
>   0-indexed `SlideSpec.position`.
> - `slide_references`: `[{"text", "slide_numbers", "positions", "out_of_range"}]`. These are the slides
>   the user's latest message names by number or ordinal, resolved deterministically. Out-of-range
>   numbers are listed, never clamped. The list is empty when there is no deck and on a describe-only
>   turn. Some phrasings are deliberately left unresolved (for example "the last two slides").
> - A reference is lexical: it does not mean the user wants that slide changed.
>
> **Candidate A, `slide-refs` (required).** Copy `src/core/skills/architect.py` `INSTRUCTIONS` exactly
> into `evals/configs/architect/slide-refs.md`. Add no trailing newline, because the file is read
> verbatim. Replace ONLY the SLIDE NUMBERS block, with this text or an equivalent that keeps every
> numbered property below:
>
> ```
> SLIDE NUMBERS
> The user numbers slides from 1, in the order the deck is presented, as the UI shows them. A slide's `position` is its 0-indexed identity in deck_spec and is never the number the user says. The payload's `slide_numbering` maps each slide of the current deck from its `slide_number` to its `position`, and `slide_references` lists the slides the user's latest message names by number or ordinal, already resolved to `positions`. Take target_positions from `slide_references` when the user's phrase was resolved; for a slide number or ordinal it does not resolve, look the slide up in `slide_numbering`. Never compute a position as the slide number minus one. A reference with numbers in `out_of_range` names a slide this deck does not have: do not edit; use discuss and say how many slides the deck has. Find a slide the user names by its content, not its number, in current_deck_spec. A reference says which slide the user means, not that they want it changed: decide the intent from what the user asks for.
> In `message` only, speak about slides 1-indexed, matching the UI. `position` and `target_positions` stay 0-indexed.
> ```
>
> The properties:
> 1. It names `slide_numbering` and `slide_references`.
> 2. Positions come from `slide_references` when resolved; otherwise the number or ordinal is looked up in
>    `slide_numbering`; a position is never computed as number − 1.
> 3. `out_of_range` means no edit; use discuss.
> 4. A reference alone does not make the request an edit.
> 5. The last two sentences stay byte-identical.
>
> Keep the block free of blank lines. Write `slide-refs.yaml`:
>
> ```yaml
> agent_key: architect
> name: slide-refs
> base: v1
> prompt_file: slide-refs.md
> ```
>
> **Candidates B and C (optional, at most two).** Each one is aimed at ONE cause seen in the train
> failures of S0 or A: for example, an edit phrased as a polite question classified as `discuss`, or a
> question about a slide classified as `edit`.
> - State a rule. Never quote or paraphrase a case message.
> - Prefer a new short block after PAYLOAD RULES over editing INTENT CLASSIFICATION, whose hash is pinned.
>   If you do edit it, say so.
>
> **Phrases every candidate must keep** (pinned by unit tests):
> - "14 to 20 slides";
> - "reusable layouts, not a one-of-each menu";
> - "its slide_type must equal the label of the template_sections entry";
> - the EDITING sentences ("start from current_deck_spec", "return it in full", "keep every slide's
>   position and every other slide unchanged", "adding or removing slides is not an edit", and so on);
> - the PAYLOAD RULES lines;
> - the VISUAL / TEMPLATE BINDING rules.
>
> The prompt never contains "non-null" and never says "reject" inside PAYLOAD RULES. The opening, DESIGN
> SYSTEMS and closing blocks stay byte-identical.
>
> **Hand-over:** per the skill. For each candidate give its name, `content_hash`, targeted cause, and train
> results with intent and position accuracy, then recommend a finalist.

Supervisor search sweeps:
- **S1** `uv run python -m evals.run_eval --agent architect --config evals/configs/architect/slide-refs.yaml --repeats 1 --cases edit_polite_ordinal,edit_last_slide,edit_multi_slide,discuss_slide_question`.
- **S2/S3** (P3, dropped first) the same for B or C, on the cases each targets.
- After each sweep, hand the run id to the author.

## Task 9 (SUPERVISOR-run): the finalist, on train and once on held-out

**Models:** test=sonnet impl=sonnet. The supervisor runs it; a delegated read-out uses sonnet.

Use the repeats fixed in Task 4, symmetric with B:
- [ ] **F1** `uv run python -m evals.run_eval --agent architect --config evals/configs/architect/<finalist>.yaml --repeats 5 --cases edit_polite_ordinal,edit_last_slide,edit_multi_slide,discuss_slide_question`
- [ ] **F2** `… --repeats 5 --cases edit_request,confirm_design,discuss`
- [ ] **F3** `… --repeats 3 --cases build_request,ask_data` (same as B3)
- [ ] **F4** `… --split heldout --repeats 2` (same as B4). Report the aggregate line and the
  `intent_report` aggregates only.
- [ ] **C3** (P3, optional, D11): `--calibrate`, and `--calibrate --split heldout`.
- [ ] **Accept the finalist only if all of these hold:**
  - F1 against B1: intent accuracy and position accuracy are both ≥ B1, and the pass rate is higher (or
    both are at 1.0);
  - no train case drops by more than one repeat against its B run;
  - F4's held-out pass rate is ≥ B4's.
- [ ] **Otherwise STOP. Do not promote.** Apply D13:
  - S0 not worse than B1 → branch (ii);
  - otherwise → branch (iii).

  Record the branch and its A2 coverage in the ledger.
- [ ] Ledger: as in Task 4, plus the finalist's name and `content_hash`.

## Task 10: Promote the finalist as the code default

**Models:** test=opus impl=opus (frozen manifest and pinned hashes). By supervisor ruling, the Task 10
agents may update **hash-pin literals**, which are pins, not behavioural assertions. They are always
recomputed by running code, never guessed.

**Files:**
- `src/core/skills/architect.py`;
- `src/services/agent_definition_manifest_v1.py`, `tests/unit/test_packaged_release_loader.py:24` and
  `tests/unit/test_graph_definition_manifest.py:707`, all via promote;
- `tests/unit/test_graph_definition_manifest.py:1158-1159`, by hand;
- `tests/unit/test_architect_edit_prompt.py`.

Steps:
- [ ] **Step 1 (test author).** In `tests/unit/test_architect_edit_prompt.py`, add prompt-contract tests
  for the SLIDE NUMBERS block. They are regexes over `_plain(block)`, in the style of `:338-382`. The
  block:
  - names `slide_numbering` and `slide_references`;
  - says target_positions come from `slide_references` when the phrase was resolved;
  - says that for a number or ordinal that is **not** resolved, the slide is looked up in
    `slide_numbering`: a sentence naming both "not resolve"/"unresolved" and `slide_numbering`;
  - forbids computing a position as the number minus one: `never` with `minus one|number − 1|number - 1`;
  - says an `out_of_range` reference is not edited (`discuss`);
  - says naming a slide does not by itself make the request an edit.

  The existing `test_message_is_one_indexed_but_positions_stay_zero_indexed` (`:385`) still passes.
  Confirm red against the current `INSTRUCTIONS`. Leave uncommitted.
- [ ] **Step 2 (implementer).**
  - Set `INSTRUCTIONS` equal to the finalist `.md`, as a parenthesised literal in the existing style.
    Verify:
    `uv run python -c "import src.core.database; from src.core.skills.architect import INSTRUCTIONS as I; import pathlib; assert I == pathlib.Path('evals/configs/architect/<finalist>.md').read_text()"`.
  - Run promote dry, and check it prints the finalist hash:
    `uv run python -m evals.harness.promote --config architect=evals/configs/architect/<finalist>.yaml --run-id architect=<F1 run id> --dry-run`.
  - Run the same command without `--dry-run`. Expect no "Skill body drift" line.
  - **Hash-pin literals, recomputed by running code:**
    - `test_architect_edit_prompt.py:38` `HEAD_ARCHITECT_CONTENT_HASH` = the finalist `content_hash`,
      with the comment "then for #313 slide references".
    - `test_graph_definition_manifest.py:1158-1159`: run
      `uv run pytest "tests/unit/test_graph_definition_manifest.py::test_hashing_rejects_non_string_object_keys_inside_guidance" -q`
      and paste the computed left-hand value from the assertion. It is `definition_content_hash(built({"1": "a"}))`
      over the promoted manifest. Add a comment naming #313.
    - **Only if** the finalist changed the INTENT CLASSIFICATION block: replace that one entry of
      `HEAD_UNCHANGED_BLOCK_HASHES` (`:81-86`) with the sha256 of the new block, computed in Python.
  - Do **not** re-record `frontend/tests/fixtures/graphLifecycleContract.json`. Precedent 45ce906c did
    not, it needs PostgreSQL, and the shape check ignores prompt text. Say so in the commit message.
- [ ] **Step 3.**
  - `uv run pytest tests/unit/test_architect_edit_prompt.py tests/unit/test_graph_definition_manifest.py tests/unit/test_packaged_release_loader.py tests/unit/test_graph_configuration_bootstrap.py tests/unit/test_skill_prose.py tests/unit/test_prompt_assembler.py tests/unit/test_retained_bundle_ledger.py tests/unit/test_persisted_agent_runtime.py tests/unit/test_graph_lifecycle_playwright_contract.py -n 4 -q`
  - Then `uv run pytest tests/unit -n 4 -q`, comparing failing causes against the baseline.
    **`tests/unit/evals/test_promote.py::test_zz_real_artefacts_unchanged_versus_head` is expected red
    until the supervisor commits**, because it compares the promoted files with `HEAD`. Re-run it after
    the commit; it must then pass.
  - `test_other_roles_definitions_unchanged` and `test_schema_contract_digests_unchanged` pass.
  - Report the old hash (3ed38cb4…), the new hash, and both hand-updated literals.

## Task 11: Docs — position semantics and the re-baseline

**Models:** test=sonnet impl=sonnet. "test" here is the reviewer's checklist: no held-out messages
anywhere, every symbol named exists, and the numbers match the ledger.

**Files:** `CONTEXT.md`, `docs/technical/backend-overview.md`, `evals/README.md`. Write them for the D13
branch that shipped. In branch (iii), the payload-key text says the keys are not wired in.

- [ ] **`CONTEXT.md` `## Language`:** add three entries in the existing format.
  - **Slide Number**: the 1-based number a user sees and says. It is the slide's place in presentation
    order among the deck's current slides, and it changes when a slide before it is inserted, deleted
    or moved. _Avoid_: position, index.
  - **Slide Position**: the 0-based identity, `SlideSpec.position` and the row's `position`.
    `target_positions` and builder briefs are keyed on it. Routes keep it contiguous from 0, but the
    graph maps through Slide Numbering instead of assuming that. _Avoid_: slide number, list index.
  - **Slide Reference**: a phrase naming slides by number or ordinal. `src/domain/slide_numbering.py`
    resolves it to Slide Positions before the architect runs. It does not decide the intent, and an
    indefinite ordinal ("a final slide") is not one. _Avoid_: slide context (the monolith's UI
    selection).
- [ ] **`docs/technical/backend-overview.md`:** add a section, "## Graph Path: Slide Numbers and
  Positions", after "Slide Editing Pipeline". It covers:
  - D1, with the contiguity invariants and the route citations;
  - the two payload keys and their shapes;
  - the D3 grammar, including the indefinite exclusion, the unresolved forms and the known limit;
  - D4 (the latest user turn; empty on describe-only) and D5;
  - the SpecView `position + 1` limit;
  - **for #314:** inserting a slide shifts the Position, and so the Slide Number, of every later slide.
    The numbering is recomputed from the rows each turn. "after slide 3" resolves "slide 3" only, and
    indefinite ordinals are left unresolved, both for #314 to interpret. The EDITING rule "adding or
    removing slides is not an edit" is the rule #314 changes.
- [ ] **`evals/README.md`:**
  - "What it does": add `evals/intent_report.py` and the D9 definitions.
  - "Promotion": correct line 151. promote has a CLI:
    `python -m evals.harness.promote --config ROLE=PATH [--run-id ROLE=ID] [--dry-run]`.
  - Add a dated section, "## Architect intent and slide references (#313), 2026-10-NN". It holds:
    - the new case ids and what each tests (no held-out messages);
    - the probe fix;
    - a BEFORE/S0/AFTER table, one row per run (B1–B4, S0, F1–F4): split, cases, repeats, pass rate,
      intent accuracy, position accuracy, judge errors, mean tokens, USD;
    - the causes;
    - the D13 branch;
    - held-out results as aggregates only.

    Note that earlier architect baseline rows describe the previous prompt.

---

## Measurement plan and budget (cap USD 20 for the whole issue, including USD 0.41 already spent)

**Cost basis (ledger ruling).**
- Opus-5 at USD 5 / 25 per M input / output tokens.
- The judge (`databricks-claude-sonnet-5`, USD 3 / 15 per M, about 12k in / 0.3k out) at about USD 0.035
  per call.
- The supervisor measured v1 architect rows at about 10.5k input and 5.9k output tokens (edit plus build).

Planning token estimates, fitted to that measurement:

| Row type | Input tokens | Output tokens | USD per row (incl. judge) |
|---|---|---|---|
| Train, with a deck, edit | ≈ 12.3k | ≈ 3.5k | ≈ 0.185 |
| Train, with a deck, discuss or confirm | ≈ 12.3k | ≈ 0.3k | ≈ 0.105 |
| No deck, build | ≈ 8.7k | ≈ 8.3k | ≈ 0.287 |
| No deck, ask_data | ≈ 8.7k | ≈ 0.3k | ≈ 0.087 |
| Held-out, with a deck, edit | ≈ 10.7k | ≈ 2.2k | ≈ 0.144 |
| Held-out, with a deck, discuss or confirm | ≈ 10.7k | ≈ 0.3k | ≈ 0.097 |

Calibration costs 2 judge calls per case, about 0.07.

Per repeat:
- train new 4: 0.660;
- B2's three cases: 0.395;
- B3's two cases: 0.374;
- held-out, all 9: 1.241.

`est_cost_usd` is not logged, so compute

```
USD ≈ rows × (mean_input_tokens × 5 + mean_output_tokens × 25) / 1e6 + judge_calls × 0.035
```

| ID | Task | Run | Agent rows | ≈ USD | Priority |
|---|---|---|---|---|---|
| — | — | already spent (probe `11c50057`, v1, edit_request + build_request × 1) | 2 | 0.41 | spent |
| C1 | 4 | calibrate train (9 cases) | 0 (18 judge) | 0.63 | P1 |
| C2 | 4 | calibrate held-out (9 cases) | 0 (18 judge) | 0.63 | P1 |
| B1 | 4 | v1, train new 4 × 5 | 20 | 3.30 | P1, never dropped |
| B2 | 4 | v1, train edit_request, confirm_design, discuss × 5 | 15 | 1.98 | P1, never dropped |
| B3 | 4 | v1, train build_request, ask_data × 3 | 6 | 1.12 | P1 (→ × 2, last resort) |
| B4 | 4 | v1, held-out all 9 × 2 | 18 | 2.48 | P1 (→ × 1) |
| S0 | 7½ | v1 prompt on regenerated payloads, train new 4 × 1 | 4 | 0.66 | P1 |
| S1 | 8 | candidate A, train new 4 × 1 | 4 | 0.66 | P1 |
| S2–S3 | 8 | candidates B/C × 1, ≤ 4 targeted cases each | ≤ 8 | ≤ 1.48 | P3, dropped first |
| F1 | 9 | finalist, train new 4 × 5 | 20 | 3.30 | P1, never dropped |
| F2 | 9 | finalist, B2's cases × 5 | 15 | 1.98 | P1, never dropped |
| F3 | 9 | finalist, B3's cases × 3 | 6 | 1.12 | P1 (→ × 2, last resort) |
| F4 | 9 | finalist, held-out all 9 × 2 | 18 | 2.48 | P1 (→ × 1) |
| C3 | 9 | re-calibrate both (D11) | 0 (36 judge) | 1.26 | P3, dropped second |

**Totals at planning costs.**
- The ruled base (spent + C1–F4, without S2/S3 and C3): 126 agent rows, about **USD 20.75**. That is
  about USD 0.75 over the cap.
- With B4/F4 × 1: about **USD 18.27**.
- With B4/F4 × 1 and B3/F3 × 2: about **USD 17.52**.

**Drop order** (ruled; applied when B1's measured cost projects the total above USD 20): S2/S3 → C3 →
B4/F4 at × 1 → B3/F3 at × 2.
- Before and after stay symmetric at every step.
- Never drop B1, F1, B2 or F2.
- S2/S3 and C3 are outside the base already, so at planning costs the first step that actually applies
  is B4/F4 × 1. It is avoided only if B1's measured cost comes in about 4% or more below the estimate.

The repeats are fixed once, right after B1 (Task 4), and reused for F. A run that would cross the cap
waits for the user.

## CI wiring

- Every new test is under `tests/unit/` and is collected by the unit job (`.github/workflows/test.yml:136`).
  No workflow change is needed.
- There is no new Playwright spec, so the e2e matrix is unchanged.
- The CI Postgres shape check (`test.yml:462`) is unaffected, because the smoke payload is unchanged.
- Live evals and `tests/agentic/` (layer 3, disabled at `test.yml:1003-1048`) are not CI. The agentic
  payloads now carry the two keys through `architect_payload()`; they are not run here.

## Docs to update

`CONTEXT.md`, `docs/technical/backend-overview.md` and `evals/README.md` (Task 11). The README count
sentences are updated in Task 3. No new doc files.

## Out of scope

- Inserting or adding a slide, and any add or insert eval case: #314, which builds on this branch. #314
  owns the add/insert anchors and the indefinite ordinals.
- #323, #321, #319, #318 and #316.
- The issue's `build_request` deck-length evidence (see the Goal).
- UI slide selection on the graph path.
- SpecView's `position + 1` on a gapped deck (recommended as a follow-up).
- Grammar extensions: count-relative plurals, plural ordinals, deictic and semantic references, and the
  bare-comma plural known limit.
- A price for `system.ai.claude-opus-5` in `prices.yaml`.
- Re-recording the lifecycle contract.
- Any change to `ArchitectOutput`, `DeckSpec`/`SlideSpec`, judge prompts or scorers.

## Risks

- **The model ignores the new keys.** S0 measures the keys alone, and S1/F1 measure Candidate A. D13
  decides what ships if no finalist is accepted. The log-only guard gives production telemetry.
- **Parser errors.** The grammar is conservative:
  - no bare-comma continuation for singular `slide`;
  - indefinite ordinals are excluded;
  - hyphenated number words are unresolved.

  References are advisory: the model decides the intent and looks unresolved forms up in
  `slide_numbering`. The one wrong resolution, the bare-comma plural, is pinned as a known limit.
- **Stale references on describe-only turns.** Prevented by D4 and covered by test (g).
- **AST drift test.** Keys are literal entries, and `tests/agentic/payloads.py` changes in the same task.
- **Held-out leakage.** Appendix H, the ledger and commit messages are kept from the candidate author
  (Held-out discipline).
- **A contaminated BEFORE.** Task 7 and S0 wait for every Task 4 run (D10).
- **Budget.** The ruled base is about USD 0.75 over the cap at planning costs. The repeats are fixed after
  B1, following the ruled drop order. Single-repeat gains are noise.
- **Judge noise.** Re-run only judge-error rows. A case that is not trusted at calibration stops the
  measurement.
- **Promotion pins.** There are **four hash pins**, plus one block hash if INTENT CLASSIFICATION changes.
  Task 10 recomputes them by running code. `test_zz_real_artefacts_unchanged_versus_head` is red until
  the commit.
- **`mlflow.db` is per worktree.** Run everything from the issue-313 worktree.
- **The #314 dependency.** D1 and D3 and the docs are the contract #314 extends.

## Self-review (plan author)

1. **Coverage.**
   - A1: Tasks 3 and 4 (+2).
   - A2: Tasks 5–7, and end to end through S0, Tasks 8–10 and D13.
   - The probe blocker: Task 1.
   - Docs: Task 11.
   - Review findings 1–18 are dispositioned at the top of this file.
2. **Existing symbols were grepped.** `architect_node`, `_conversation`, `_committed_slide_rows`,
   `_persisted_spec_describes_these_rows`, `MODEL_PAYLOAD_KEYS`, `model_payload_for`, `EVERY_MODEL_CALL`,
   `ARCHITECT_PAYLOAD_KEYS`, `architect_payload`, `deck_spec_dict`, `REQUIRED_SMOKE_PAYLOADS`,
   `gateway_endpoint_name`, `_endpoint_reachable`, `validate_endpoint`, `expected_category_score`,
   `_brief_or_finding`, `default_tracking_uri`, `promote`, `_transition_records`, `_V2_DIGEST`,
   `HEAD_ARCHITECT_CONTENT_HASH`, `HEAD_UNCHANGED_BLOCK_HASHES`, `PACKAGED_V1_CONTENT_HASHES`,
   `test_hashing_rejects_non_string_object_keys_inside_guidance`,
   `test_zz_real_artefacts_unchanged_versus_head`, `test_a_fresh_recording_has_the_checked_in_contracts_shape`,
   `_parse_slide_references`, `_rewrite_deck_spec_slides`, `run_arc_review`, `SkillStub.calls_for`,
   `scoped`, `_edit_out` and `_revised` all exist at the cited lines.
3. **New symbols are introduced only in Tasks 2, 5 and 6:** `evals.intent_report.*`,
   `src.domain.slide_numbering.*` and `nodes._deck_positions`.
4. **No `DeckSpec`/`SlideSpec` or output-schema change,** so there is no frontend mirroring.

---

## Appendix H — HELD-OUT CASE CONTENT

Readers: the Task 3 and Task 7 agents and the supervisor only. Never show this to the Task 8 author.

Deck: `evals/fixtures/meridian/heldout/deck_spec.json`, 6 slides, positions 0–5. The prior exchange and the
library are as in the existing held-out cases (`heldout.py:21-24`). `HAS_DECK` gains the 4 ids. No
held-out target slide's `purpose` changes.

| id | message (exact) | expect | reference | should_fail |
|---|---|---|---|---|
| `edit_polite_ordinal` | `Would you mind making the 4th slide lead with the 3-5 iteration rounds?` | `{"intent": "edit", "positions": [3]}` | edit [3]; message `I'll make the iteration rounds the headline stat on the fourth slide.`; brief[3] = `Three-stat card slide that leads with typical iteration cycles to production quality (3-5 rounds) as the headline stat, followed by token cost reduction (30-50%) and output consistency improvement (up to 40%)` | discuss, `Sure. Should the iteration figure replace the slide title or sit above the other stats?` |
| `edit_last_slide` | `The final slide should open with the call to action, before the checklist` | `{"intent": "edit", "positions": [5]}` | edit [5]; message `I'll move the call to action to the top of the final slide, ahead of the checklist.`; brief[5] = `Bullet slide that opens with the call to action — adopt this checklist for every new LLM feature starting this sprint — and then presents the five-item prompt optimisation checklist (define task scope, choose patterns, write eval criteria, run test suite, document winning prompt)` | `_slipped` → targets [6] |
| `edit_multi_slide` | `Slides 2 and 3 are too dense — drop the callouts on both` | `{"intent": "edit", "positions": [1, 2]}` | edit [1,2]; message `I'll drop the callouts on slides 2 and 3.`; brief[1] = `Bullet slide listing the three pain points of unoptimised prompts — inconsistent outputs, wasted tokens/cost, and slow iteration — with no callout`; brief[2] = `Bullet slide covering the four key patterns — system-prompt framing, few-shot examples, chain-of-thought reasoning, and structured output formatting — with no callout` | `_slipped` → targets [2,3] |
| `discuss_slide_question` | `Why does slide 2 come before the techniques?` | `{"intent": "discuss"}` | discuss; `Slide 2 sets out what ad-hoc prompting costs, so the four techniques on slide 3 land as the answer to a problem the audience already feels. I can swap them if you prefer.` | edit [1], `I'll move slide 2 after the techniques.` (no deck_spec) |

The held-out `edit_last_slide` request changed after review finding 11. The first request ("one clear next
step instead of a checklist") contradicted three things that all name the checklist: the slide's
`purpose`, its `hands_off` ("Start using the checklist this sprint"), and the deck's `call_to_action`. The
new request keeps all three true. It still needs a real edit, because the gold slide puts the call to
action last, in a callout.

**Markers and fairness for the Task 3 held-out tests.**
- **Brief markers:**
  - `edit_polite_ordinal` contains "headline stat" and "leads with typical iteration cycles";
  - `edit_last_slide` contains "opens with the call to action" and keeps "five-item";
  - both `edit_multi_slide` briefs end "with no callout".
- **Gold fairness:**
  - The **named stat is not first** in the pos 3 gold brief:
    `brief.index("iteration cycles") > brief.index("token cost reduction")`.
  - The pos 5 gold brief has the checklist before the call to action:
    `brief.index("five-item") < brief.index("call to action")`.
  - The pos 1 and pos 2 briefs contain "callout".
  - The pos 2 purpose contains "techniques".
  - `discuss_slide_question` `should_fail` targets [1].

**Task 7 pinned `slide_references` (held-out).**
- `edit_request` (`On slide 3, …`) → `[{"text": "slide 3", "slide_numbers": [3], "positions": [2], "out_of_range": []}]`
- `edit_polite_ordinal` → `4th slide` [4]→[3]
- `edit_last_slide` → `final slide` [6]→[5]
- `edit_multi_slide` → `Slides 2 and 3` [2,3]→[1,2]
- `discuss_slide_question` → `slide 2` [2]→[1]
- `build_request`, `ask_data`, `confirm_design`, `discuss` → `[]`

`slide_numbering` for deck cases: `n → n-1` for n = 1..6.
