# Eval Harness Held-Out Set Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This repo also requires the companion skill **executing-plans-tellr** (`.claude/skills/executing-plans-tellr/`), per `CLAUDE.md`. Every task carries a `Models:` tag (test author / implementer tiers); the pipeline is: test author writes failing tests, implementer makes them pass without editing them, a reviewer one tier up sabotage-checks and may apply localised fixes.

**Goal:** Add a second, held-out case set to the agent-configuration eval harness, built from a second deck ("Prompt Optimisation: A Practical Framework"), so a prompt tuned against the train cases can be scored on cases the optimiser never saw.

**Architecture:** Deck 2's gold slides and `DeckSpec` become a second fixture set, selected by an optional `deck=` argument that defaults to the existing deck. Each agent pack gains a `heldout.py` generator that writes `cases_heldout/` next to `cases/`. `load_cases`/`calibrate`/`run_sweep`/`run_eval` gain a `split` option (default `train`); held-out runs go to a separate MLflow experiment and the CLI prints aggregate results only. Judge prompts stay agent-level and are shared by both splits. Default behaviour is unchanged.

**Tech Stack:** Python 3.11, MLflow 3.14, Playwright (chromium), PyYAML, pydantic v2, pytest. All already installed. No new dependencies.

**Spec:** the design approved in chat on 2026-10-07 (restated in "Design" below) plus the shared pack contract `.superpowers/sdd/2026-10-07-eval-heldout-set/heldout-facts.md` (a copy of the harness's `packs-facts.md` with the deck-2 additions). The harness it extends is specified in `docs/superpowers/specs/2026-10-02-agent-config-eval-harness-design.md`.

## Design (approved in chat)

- **Fixtures.** `evals/fixtures/meridian/heldout/` holds deck 2: `gold/<pos>.html` (6 slides), `deck_spec.json` (a valid `DeckSpec`), produced by `evals/fixtures/split_heldout.py` from the Downloads files. Deck 1 stays where it is.
- **Cases.** `evals/packs/<agent>/cases_heldout/<case_id>/` with the same four files as train cases. 35 cases: 5 per agent. Adapted per pack, not copied, because deck 2 has no chart.
- **Runs.** `run_eval --split heldout` writes to MLflow experiment `tellr-agent-eval-heldout`, tags `split=heldout`, and prints aggregate pass rates only (no rationales, payloads or references). Train stays on `tellr-agent-eval`.
- **Honest limit.** Held-out is a discipline, not a lock: the files are in the repo. The guard is separate directories/experiment, aggregate-only CLI output, and instructions to any optimiser to use train only.
- **Deck 2 quirk.** Position 4 (spec "Slide 5", the workflow loop) has an inline off-palette `#6b7280` and 6px of safe-area intrusion under current Meridian. It is never a render or layout reference; the deck_reviewer may use it for narrative only. Its HTML is committed as generated, untouched.

## Global Constraints

- **No new dependencies; never `pip install`** (shared pyenv). If an import fails, stop and report.
- **Default behaviour must not change.** Every new parameter defaults to the existing (train) behaviour. All existing tests in `tests/unit/evals/` keep passing with no assertion weakened. A test may change only where this plan says a ruling requires it, and the report must name it.
- **Positions are 0-indexed.** Deck-2 spec "Slide N" = position N-1 (spec "Slide 5" = position 4).
- **Render-clean references for deck 2: positions 0, 1, 2, 3, 5** (measured under current Meridian: overflow 0, safe_area_px 0, min_contrast >= 4.58, off_palette (), no console errors). Position 4 is excluded.
- **Payloads use production shapes**, exactly as the train packs do: run through `model_payload_for(agent_key, ...)`, `design_system_active: true`, `resolved_data` validating as `ResolvedData`, `slide_spec` as `SlideSpec`, any deck spec as `DeckSpec`. See `heldout-facts.md`.
- **Every case has four files** (`case.yaml`, `payload.json`, `reference.json`, `calibration.json`); `calibration.json`'s `should_fail` is a deliberately wrong output in the role's output shape.
- **Judge prompts are shared.** Held-out cases use the agent-level `evals/packs/<agent>/judge_prompt.md`. Do not create or edit judge prompts in this plan.
- **Generators are idempotent and never write the committed tree from a test.** `generate(out_dir: Path | None = None)`; tests generate into `tmp_path` and byte-compare against the committed tree.
- **Fixtures are synthetic and public-safe.** Deck 2 is a generic prompt-optimisation deck in the Meridian brand.
- **Git:** work on branch `feat/eval-heldout` (off `feat/ws2a-ai-gateway`). Commit messages end with `Co-authored-by: Isaac <no-reply@databricks.com>` as its own `-m`. Never push, never merge to main, never `--no-verify`.
- **Live model calls** happen only in Task 11. Every other task is network-free.

## Review Focus

- **A held-out run silently scoring the TRAIN case because the id matches** — most agents share case ids across the splits (`clean`, `rogue_colour`, `edit_request`, ...), and `mlflow_run.py` loads cases by id at predict time (`make_predict_fn`) and inside the `judge` scorer, with no split argument today. Expect the split to travel in the dataset row `inputs` and reach every by-id load; a held-out row must run and be judged against the held-out payload and reference. Pinned in **Task 2** by a same-id-in-both-splits test that asserts what the stub adapter and stub judge actually received.
- **A held-out run landing in the train experiment, or mixing with train runs in Compare** — expect separate experiments and a `split` tag; a comparison across splits must be impossible by construction. Pinned in **Task 2**.
- **`load_cases(agent)` with no argument changing behaviour, or `--cases clean` matching across splits** — expect train-only by default and the filter applied inside the chosen split. Pinned in **Task 1** and **Task 2**.
- **The held-out CLI printing rationales, payloads or references** — expect aggregate pass rates and counts only. Pinned in **Task 2**.
- **A pack using deck-2 position 4 as a render or layout reference** — expect every reference to render clean and position 4 to be absent as a reference. Pinned in **Task 1** (constant and test) and each pack task.
- **Deck 2's "30–50%" appearing twice with opposite meaning** (position 1 says naive prompts use 30–50% MORE tokens; the position-3 stat card says structured prompts use 30–50% FEWER) — expect the `source_contradiction` mutation to target the stat card and the `resolved_data` wording to match it. Pinned in **Task 4** and **Task 5**.
- **Trusting held-out scores before the judge is calibrated on them** — expect a live calibration gate before any sweep. Pinned in **Task 11**.

---

## File Structure

```
evals/fixtures/split_heldout.py                 one-off splitter + spec parser (Task 1)
evals/fixtures/meridian/heldout/
  gold/<0..5>.html                              deck 2 gold slides, bare fragments (Task 1)
  deck_spec.json                                valid DeckSpec (Task 1)
evals/harness/case.py                           deck= and split= options (Task 1)
evals/harness/judge.py                          split-aware calibrate / load_calibration (Task 2)
evals/harness/mlflow_run.py                     split-aware run_sweep / cases_digest / experiment (Task 2)
evals/run_eval.py                               --split flag, aggregate-only heldout output (Task 2)
evals/packs/<agent>/heldout.py                  generate(out_dir=None) -> cases_heldout/ (Tasks 3-9)
evals/packs/<agent>/cases_heldout/<case_id>/    generated, committed (Tasks 3-9)
evals/README.md                                 held-out section (Tasks 10, 11)
tests/unit/evals/test_heldout_fixtures.py       Task 1
tests/unit/evals/test_split_plumbing.py         Task 2
tests/unit/evals/test_pack_<agent>_heldout.py   Tasks 3-9
tests/unit/evals/test_cross_split.py            Task 10
```

---

## Task 1: Deck-2 fixtures and deck/split-aware case helpers

**Models:** test=sonnet impl=sonnet

**Files:**
- Create: `evals/fixtures/split_heldout.py`, `evals/fixtures/meridian/heldout/gold/{0..5}.html`, `evals/fixtures/meridian/heldout/deck_spec.json`, `tests/unit/evals/test_heldout_fixtures.py`
- Modify: `evals/harness/case.py`

**Interfaces:**
- Produces, in `evals/harness/case.py` (all new parameters are keyword-or-positional with the stated default; existing call sites must not change):
  - `SPLITS = ("train", "heldout")`, `HELDOUT_DIR = MERIDIAN_DIR / "heldout"`
  - `RENDER_REFERENCE_POSITIONS = {"train": (1, 3, 9), "heldout": (0, 1, 2, 3, 5)}`
  - `gold_slide(position: int, deck: str = "train") -> str`, `gold_scripts(position: int, deck: str = "train") -> str`, `gold_deck_spec(deck: str = "train") -> dict`; `deck="heldout"` reads from `HELDOUT_DIR`; any other value raises `ValueError` naming it.
  - `cases_dir(agent_key, root=None, split="train")` returns `PACKS_DIR/agent/"cases"` for train and `PACKS_DIR/agent/"cases_heldout"` for heldout (`root` wins when given); `load_case(agent_key, case_id, *, root=None, split="train")`; `load_cases(agent_key, *, root=None, split="train")`. An unknown split raises `ValueError`.
- `split_heldout.py` reads `~/Downloads/prompt-optimisation--a-practical-framework.html` and `~/Downloads/test deck spec 2`. Slides come from `<div class="slide-container">\s*(<section.*?</section>)` (6 of them), written stripped, with no `slide-wrapper`/`slide-container` chrome and no `<style>`. The spec is parsed deterministically from the text layout: `Audience`, `Purpose`, `Argument`, `Call to action`, `Narrative arc` (one beat per line), `Design contract` ("Design system #3Template #5" -> `{design_system_id: 3, template_id: 5}`), and `Slide N` blocks (line after the header = `purpose`; next paragraph = `content_brief`; `Assumes:`; `Hands off:`). `title` is "Prompt Optimisation: A Practical Framework".
- `deck_spec.json` must validate as `src.domain.deck_spec.DeckSpec`. `resolved_data` carries a short `synthesis` with NO numbers in it, `gaps: []`, and exactly three figures (`{key, value, source}`), each `source: "Held-out deck fixture"`: `token_cost_reduction` ("30–50% fewer tokens per request vs. naive prompts"), `consistency_gain` ("up to 40% output consistency gain with few-shot + chain-of-thought"), `iteration_cycles` ("3–5 revision rounds to reach production-grade quality"). Only the stat slide (position 3) lists `data_references` (all three keys); every other slide has `[]`.

- [ ] **Step 1: Write the failing tests** (`tests/unit/evals/test_heldout_fixtures.py`, behavioural, no network):
  - six held-out gold slides exist, each a bare `<section class="slide` fragment, no `<style`, no `slide-wrapper`/`slide-container`;
  - `DeckSpec.model_validate(case.gold_deck_spec("heldout"))` passes; `design_contract` is 3/5; six slides; each slide's `hands_off` equals the spec text for that slide (read from `~/Downloads/test deck spec 2` only if present, else skip with a reason); `data_references` are a subset of the figure keys and only position 3 has any; the synthesis contains no digits;
  - default behaviour: `case.gold_slide(1)` equals `case.gold_slide(1, deck="train")` and still equals the file under `fixtures/meridian/gold/`; `gold_deck_spec()` still has 10 slides;
  - `deck="bogus"` and `split="bogus"` raise `ValueError` naming the value;
  - `cases_dir("builder")` ends with `/cases`; `cases_dir("builder", split="heldout")` ends with `/cases_heldout`; `load_cases("builder")` is unchanged (5 train cases) and `load_cases("builder", split="heldout")` returns `[]` while no held-out cases exist;
  - **(request the `requires_chromium` fixture)** each position in `RENDER_REFERENCE_POSITIONS["heldout"]` renders with overflow 0, `safe_area_px` 0, min_contrast >= 4.5, `off_palette == ()`, no console errors under `meridian_section_css()`; and position 4 is NOT in the tuple.
- [ ] **Step 2:** Run `python -m pytest tests/unit/evals/test_heldout_fixtures.py -q` and confirm RED for the right reason.
- [ ] **Step 3:** Implement `case.py` changes and `split_heldout.py`; run the splitter to produce the committed fixtures.
- [ ] **Step 4:** `python -m pytest tests/unit/evals -q -n auto` is green; `git status --short evals` shows only the intended new files.
- [ ] **Step 5:** Commit.

---

## Task 2: Split plumbing (judge, MLflow run, CLI)

**Models:** test=opus impl=sonnet

**Files:**
- Modify: `evals/harness/judge.py`, `evals/harness/mlflow_run.py`, `evals/run_eval.py`
- Create: `tests/unit/evals/test_split_plumbing.py`

**Interfaces:**
- `judge.load_calibration(agent_key, case_id, *, split="train")` and `judge.calibrate(agent_key, *, model=JUDGE_ENDPOINT, render_fn=None, split="train")`: read cases and `calibration.json` from the split's directory via `case.cases_dir`. Existing results, row shape and behaviour for `split="train"` are unchanged.
- `mlflow_run.EXPERIMENT_NAMES = {"train": "tellr-agent-eval", "heldout": "tellr-agent-eval-heldout"}`; keep `EXPERIMENT_NAME = "tellr-agent-eval"` as-is for existing references. `cases_digest(agent_key, root=None, *, split="train")` hashes the split's tree (today it hard-codes `PACKS_DIR/agent/"cases"`, `mlflow_run.py:45`). `run_sweep(..., split="train")` loads cases from the split, applies `case_filter` within that split, calls `mlflow.set_experiment(EXPERIMENT_NAMES[split])`, and adds the run tag `split`. `NoCasesError` message names the split and uses the split's directory (today `mlflow_run.py:238` hard-codes `"cases"`).
- **The split must reach every by-id load.** `build_dataset(cases, repeats, split="train")` adds `"split"` to each row's `inputs`. `make_predict_fn`'s `predict_fn(agent_key, case_id, repeat, split="train")` calls `load_case(agent_key, case_id, split=split)` (today `mlflow_run.py:123`). The `judge` scorer calls `load_case(inputs["agent_key"], inputs["case_id"], split=inputs.get("split", "train"))` (today `mlflow_run.py:200`). Any other by-id load in `mlflow_run.py` gets the same treatment; the implementer greps for `load_case(` and `cases_dir`/`"cases"` and reports every site.
- `judge.load_calibration` builds its path with a hard-coded `"cases"` component (`judge.py:63`) and `calibrate` calls `load_cases(agent_key)` (`judge.py:91`); both take the split.
- `run_eval.py`: `--split {train,heldout}` (default `train`), applied to both the sweep path and `--calibrate`. For `--split heldout` the CLI prints, per agent, only: agent key, run id, overall `pass_rate`, and the infra/judge error counts. It prints no case ids with rationales, payloads or references. Train output is unchanged. The trust table for `--calibrate --split heldout` keeps its current columns (it reports calibration verdicts, not agent outputs).

- [ ] **Step 1: Write the failing tests** (`tests/unit/evals/test_split_plumbing.py`; stub adapter and stub judge; tmp sqlite tracking URI; no network). Use tmp case trees passed through monkeypatched `PACKS_DIR`/`cases_dir` to create held-out cases for one agent:
  - `calibrate(agent, split="heldout")` reads the held-out tree and its `calibration.json`, and `split="train"` output is byte-for-byte what it was (reuse an existing train calibrate fixture);
  - `run_sweep(..., split="heldout")` logs into experiment `tellr-agent-eval-heldout`, tags `split=heldout`, and `cases_digest` differs from the train digest for the same agent; a train sweep still logs to `tellr-agent-eval` with tag `split=train`;
  - two runs (one per split) can never share an experiment: assert `mlflow.get_experiment_by_name` resolves them to different ids;
  - `--cases` filters within the chosen split only (a case id present in both splits selects the right one);
  - **the same-id collision test (the critical one):** create two tmp case trees for one agent that BOTH contain a case id `clean` but with different payloads and references (distinguishable markers). Run a held-out sweep through the real `run_sweep` with a stub adapter that records the payload it receives and a stub judge that records the `expectations` it receives. Assert the adapter received the HELD-OUT payload, the judge received the HELD-OUT reference, and that the train marker appears nowhere. Then run the same for `split="train"` and assert the reverse. Sabotage: revert the split threading in `predict_fn` (and separately in the `judge` scorer) and see each assertion go RED;
  - an empty held-out tree raises `NoCasesError` naming "heldout";
  - CLI: `main(["--agent", "x", "--split", "heldout", ...])` output contains the pass rate and error counts and contains NONE of: a case id, a rationale string from the stub judge, a payload key. `main([... "--split", "bogus"])` exits non-zero via argparse.
- [ ] **Step 2:** Confirm RED. **Step 3:** Implement. **Step 4:** `python -m pytest tests/unit/evals -q -n auto` green, including every pre-existing judge/mlflow_run/run_eval test unmodified.
- [ ] **Step 5:** Sabotage-check each new behaviour (experiment name, tag, filter scope, output redaction). **Step 6:** Commit.

---

## Pack tasks (3-9): shared rules

Each pack task adds `evals/packs/<agent>/heldout.py` with `generate(out_dir: Path | None = None)` (default `None` = `PACKS_DIR/<agent>/cases_heldout`), reusing the pack's existing helpers from `mutations.py` where they fit (file writing, `Finding` construction) rather than copying them, and committed `cases_heldout/` for the listed cases. The self-test is `tests/unit/evals/test_pack_<agent>_heldout.py`, mirroring the pack's existing train self-test (`test_pack_<agent>.py`): case set, four files, `load_case(..., split="heldout")` with `design_system_active True`, payload keys equal production's set for the role, data-model validity (`ResolvedData`/`SlideSpec`/`DeckSpec`), each mutation really plants its fault against the deck-2 gold (text diff or render measure), references render clean and come only from `RENDER_REFERENCE_POSITIONS["heldout"]`, `expected_category_score` passes the reference and fails `should_fail` where the case is category-scored, calibration present and wrong in the way the case is about, generator idempotent into `tmp_path`, and a "committed cases are current" test that generates into `tmp_path` and byte-compares the committed `cases_heldout/` tree without writing it. Render-dependent tests request the `requires_chromium` FIXTURE (`@pytest.mark.usefixtures("requires_chromium")`, see `tests/unit/evals/conftest.py`), not a marker. Deck-2 payloads use the heldout `DeckSpec`'s `resolved_data` (the three figures), not deck 1's.

## Task 3: builder held-out pack

**Models:** test=sonnet impl=sonnet

Cases (5): `cover_slide` (positive; brief for position 0; reference = `gold_slide(0, "heldout")`), `bullets_problem` (positive; position 1), `stat_cards` (positive; position 3), `too_much_content` (mutation; position-1 brief demands at least 12 dense points; reference is a condensed slide that renders fully clean; `should_fail` overflows), `stat_no_data` (mutation; position-3 brief with `resolved_data.figures == []` and a number-free synthesis; reference makes the point with no digits and no invented figures; `should_fail` is a stat slide that states invented figures).

## Task 4: build_reviewer held-out pack

**Models:** test=sonnet impl=sonnet

Cases (5), payload = production build-review keys (no `deck_brief`): `clean` (position 1), `broken_handoff` (position 1, callout contradicts the hands-off that ad-hoc prompting has real, compounding costs), `rogue_colour` (position 1 title `#E11D48`), `overflow` (position 1 plus about 40 extra bullets), `source_contradiction` (position 3: the stat card "30–50%" changed to "10–15%" while `resolved_data.token_cost_reduction` says 30–50% fewer tokens; the mutated slide must still render clean). Expects as in the train pack. `rogue_colour` must keep min_contrast >= 4.5 (unplanted `contrast_failure` would make the case ambiguous).

## Task 5: fixer held-out pack

**Models:** test=sonnet impl=sonnet

Cases (5), payload = production fixer keys (`position, finding, html, scripts, slide_spec, resolved_style, section_css, resolved_data`): `rogue_colour`, `overflow`, `source_contradiction`, `brief_not_delivered` reuse the Task 4 broken slides (assert equality with the held-out build_reviewer twin's `html`); `contrast_failure` is new, planted on the position-1 callout using palette colours only (rendered min_contrast < 4.5, `off_palette == ()`). Findings are built through `Finding` with `CRITERIA` category/objective; references are the un-mutated held-out gold slide with `changed: true` and an honest `change_summary`. The `source_contradiction` finding message states both values.

## Task 6: fix_reviewer held-out pack

**Models:** test=sonnet impl=sonnet

Cases (5), payload = production fix-review keys (`position, finding, change_summary, html, scripts, original_html, original_scripts, slide_spec, resolved_style, section_css`): `good_fix_accept` (overflow fixed minimally), `fault_left_reject`, `content_broken_reject` (overflow fixed but a bullet's meaning reversed), `restyle_reject` (overflow fixed but recoloured off-palette with min_contrast staying >= 4.5), `good_contrast_fix_accept`. `original_html` and `finding` equal the Task 5 twin's `html` and `finding`. Expects: accepts `{criteria: [], positions: [], verdict: "fixed"}`; rejects carry the planted criterion at position 1 and verdict `surfaced`.

## Task 7: deck_reviewer held-out pack

**Models:** test=sonnet impl=haiku

Cases (5), payload = `narrative_arc`, `call_to_action`, `slide_count`, and `slides` as the single string from `spotlight_prior_slides(htmls, None)`: `clean` (all six slides), `arc_gap_drop_workflow` (drop position 4; arc_gap), `missing_conclusion` (drop position 5; missing_conclusion), `out_of_order` (swap positions 2 and 4; arc_gap), `repetition` (replace position 2 with a slide embedding position 1's `<ul class="bullets">` block verbatim, so it appears exactly twice; cross_slide_repetition). All deck findings use `slide_index -1`; reference messages describe slides by title/topic, never by number. Position 4 may appear here (narrative only).

## Task 8: architect held-out pack

**Models:** test=sonnet impl=sonnet

Cases (5), payload = the production architect's 9 keys with `current_deck_spec` = the held-out `DeckSpec` and the same Meridian `template_sections` and two-system `design_system_library` (Meridian 3/5 plus the synthetic Acme 4/7) as the train pack: `build_request` (build the held-out deck; reference `deck_spec` equals the held-out spec), `edit_request` ("On slide 3, show the four patterns as four cards instead of a bullet list" -> `intent edit`, `target_positions [2]`, and the reference `deck_spec` equals the held-out spec with ONLY `slides[2].content_brief` revised; `should_fail` is the 1-based slip `[3]`), `ask_data` ("build a deck on our team's measured prompt success rates by model last quarter", no data supplied), `confirm_design` (switch to the Acme design system; reference proposes 4/7, says every slide will be rebuilt, `deck_spec` null), `discuss` (a question about few-shot vs chain-of-thought prompting with the deck present). References and `should_fail` validate as `ArchitectOutput`.

## Task 9: data_analyst held-out pack

**Models:** test=sonnet impl=haiku

Cases (5), payload = exactly `data_request` (the user's message as a STRING) and `deck_purpose: None`: `figures_inline` (the message states "structured prompts use 30–50% fewer tokens than naive prompts" with a named source; expect success, the reference passes the figure through), `two_sources` (two sourced figures to combine; the reference cites both), `unsourced_public_stat` (an external statistic nobody supplied; expect `no_tool`; `should_fail` is a `success` with an invented figure whose digits are not in the request), `needs_tool` (query an internal warehouse; expect `no_tool`), `conflicting_figures` (two surveys disagree on revision rounds, 3 vs 5; the reference flags the conflict, `should_fail` picks or averages one). References and `should_fail` validate as `AnalystOutput`.

## Task 10: cross-split guards and held-out README

**Models:** test=sonnet impl=haiku

**Files:** Create `tests/unit/evals/test_cross_split.py`; modify `evals/README.md`.

- [ ] **Step 1: Tests:** for every agent, the held-out set has exactly the case ids this plan lists (35 in total) and each has all four files; no held-out `payload.json` equals any train `payload.json` byte-for-byte; no held-out `reference.json` equals a train one; the existing judge-prompt-vs-payload cross-pack test (`test_judge_prompt_inputs.py`) also covers held-out cases (extend its parametrisation to both splits, additive only); every held-out case's `design_system_active` is true.
- [ ] **Step 2:** Confirm RED, implement, green.
- [ ] **Step 3:** README: add a "Held-out set" section covering what it is, `--split heldout`, the separate experiment, aggregate-only output, the discipline-not-a-lock caveat with the instruction that an optimiser uses train only and held-out is scored on finalists, and a `--split` row in the flags table. No results yet (Task 11 adds them).
- [ ] **Step 4:** Commit.

## Task 11: live calibration, held-out baseline, README results

**Models:** test=n/a impl=sonnet

- [ ] **Step 1 (gate, report-only):** `python -m evals.run_eval --agent all --calibrate --split heldout`. If any case is untrusted, do NOT sweep: investigate each (judge prompt / reference / should_fail / infra / noise, one re-run for noise), and stop and report.
- [ ] **Step 2:** Only if 35/35 are trusted: `python -m evals.run_eval --agent all --config v1-baseline --repeats 3 --split heldout`. Read the 7 new runs back from experiment `tellr-agent-eval-heldout`; for every case below 1.0 read the stored rationales and attribute it AGENT or HARNESS with a quoted rationale. Controller re-verifies any HARNESS attribution against the code before it is written down.
- [ ] **Step 3:** Add the held-out baseline (date, `git_sha`, judge endpoint, per-agent table, cost, failures) to `evals/README.md`. Commit.
