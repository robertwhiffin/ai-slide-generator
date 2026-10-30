# Agent-configuration eval harness

Scores Tellr agent configurations (prompt and model settings) against a fixed pack of cases, so
candidate configurations can be compared on evidence before one is promoted into Graph Version 1.
Real-model runs; results are logged to MLflow.

## What it does

- **Configs** (`evals/configs/`). A config is a named variant of one agent's v1 definition.
  `v1-baseline` is the frozen manifest unchanged. YAML configs override the prompt and/or model
  settings. Each config carries a `content_hash`, logged with every run.
- **Cases** (`evals/packs/<agent>/cases/<case_id>/`). Five per agent (seven for the builder and the
  build_reviewer, twenty-two for the architect), 56 in total across the seven
  roles (`architect`, `data_analyst`, `builder`, `build_reviewer`, `fixer`, `fix_reviewer`,
  `deck_reviewer`). Each case holds `case.yaml` (`kind` positive or mutation, `fault`, `expect`,
  `design_system_active`), `payload.json` (the agent input), `reference.json` (a known-good output)
  and `calibration.json` (a `should_fail` output). The architect's two newest cases,
  `fill_blank_slide` (the user names a manually inserted blank slide by its number and asks for
  content on it: it is filled in place, with no new slide beside it) and `edit_beside_blank` (the
  user asks to change the slide after the blank: only that slide changes and the blank stays blank),
  run on a deck that holds the blank.
  - *Calibrated 2026-10-22.* The judge is trusted on `edit_beside_blank` on both splits. On
    `fill_blank_slide` it cannot separate the should_fail (a new slide inserted beside the blank)
    from the reference on either split. So `fill_blank_slide` is scored by its deterministic checks:
    the intent is `edit`, production's alignment revises exactly the blank, and it inserts nothing.
    Its judge verdict is reported, not counted. The harness does not apply this rule (a row fails
    on any failing scorer, the judge included), so read that case's result from `contract` and
    `expected_category`. A judge-visible should_fail for it is a follow-up.
  - *Measured before any prompt change*, on `v1-baseline` (the shipped `add-slide-b` architect
    prompt): train ×3 6/6 (run `630beeaf`), held-out ×1 2/2 (run `6b2e4ab4`, aggregate only),
    0 production binding refusals. No prompt change was needed.
- **Scorers** (`evals/harness/scorers.py`, `mlflow_run.py`). Every row is scored by:
  - `contract`: the output validated against the agent's schema. An `incomplete` run, such as a model
    inventing a criterion name outside the schema, fails here.
    Its rationale gives the run status and the reason, including the schema validation message (the
    invalid field and value), truncated to 2000 characters.
  - `expected_category`, for the architect, data_analyst and the three reviewers: deterministic
    match on intent/outcome, or on expected findings (criterion, position). Any objective criterion
    not listed in `expect.criteria` fails the row. A fix_reviewer also checks `verdict`.
    - *Architect insert cases* (#314). A case whose `expect` has `inserted` is scored with
      production's own semantics, not by the model's `target_positions`, because `architect_node`
      ignores those targets on an insert and derives the turn from `align_slides` (see "Editing
      the deck's slides", its "The spec path: alignment" part, in
      `docs/technical/backend-overview.md`). `build_dataset` adds
      `expectations["current_deck_spec"]` (the payload's deck) for architect cases that have one,
      and omits the key when the deck is `None`. The row passes only if all of these hold:
      the intent is `edit`; the output carries a valid `deck_spec`;
      `align_slides(current_deck_spec, output)` does not refuse; `inserted_indices` equals
      `expect.inserted`; `revised_indices` equals `expect.positions` minus `inserted`; and the
      deck-level fields (`audience`, `purpose`, `argument`, `call_to_action`, `narrative_arc`) and
      the design contract equal the reference's. The five fields are `scorers.DECK_LEVEL_FIELDS`, a
      test pins them equal to `nodes._DECK_LEVEL_FIELDS`. A model whose own `target_positions`
      differ is noted in the rationale and not failed. A missing `reference` or `current_deck_spec`
      fails the row with an explicit rationale. Every other case scores exactly as before.
    - *Architect operations answers* (architect edit operations). An `edit` answer carrying
      `operations` or `deck_changes` is scored on every edit case, whatever else it carries, the way
      production composes it: `apply_operations` plus `compose_edit_spec` over
      `current_deck_spec`. The row passes only if production would not refuse it; the rebuilt
      indices equal `expect.positions`; the new slides equal `expect.inserted` (default none);
      the layout equals `expect.layout` when the case gives one (what tells a delete or a move
      apart); every slide not rebuilt equals, field for field, the current deck's slide whose row it
      keeps; and the deck-level fields and design contract equal the (composed) reference's. The
      model's own `target_positions` are noted, not failed. The judge sees an operations answer in its
      composed form (`compose_operations_answer`): the composed `deck_spec`, with `target_positions`
      = the rebuilt indices. A `deck_spec`-only insert answer is still scored by the insert check.
      The one exception is the re-description case below.
    - *Architect re-description* (the arc-review sweeper's describe-only turn). A case whose
      `expect` has `full_deck_spec` is scored by `_redescription_score` alone, ahead of the intent
      check and the operations check. On that turn `architect_node` applies no operations: it
      persists the answer's `deck_spec`, keeps the persisted spec instead when the answer's slide
      positions differ from it, and refuses an answer with no `deck_spec` without a retry. The row
      passes only if all of these hold: the intent is `edit` or `build` (the node persists either
      one's `deck_spec` the same way, and `architect_router` ends both turns before the foreman);
      `deck_spec` is a valid DeckSpec whose slide positions equal `current_deck_spec`'s exactly;
      and `operations` and `deck_changes` are both null. The model's own `target_positions` are
      noted, not failed. The judge sees this case's answers as given, never composed
      (`judge._judged`), because production composes nothing on that turn.
    - *Architect deck style.* A case whose `expect` has `deck_style: true` must also pass
      `_deck_style_score`, checked right after the intent. It reads the answer's `deck_spec` and
      passes only if `deck_style` is present, has 1 to 12 components and at most 10,000 characters
      of CSS, `sanitise_deck_style` returns it unchanged (the same object, no notes), every slide
      has a non-blank `look`, and, with a design system active, its CSS holds no hex colour
      literal. The scorer passes the case's `design_system_active` through.
    - *Architect restyle.* A case whose `expect` has `deck_style_keeps` (a list of classes) is a
      restyle given in `deck_changes.deck_style`, the only way production restyles a deck (a
      full-spec edit keeps the persisted style). An operations answer passes only if it passes
      every operations check above and `deck_changes.deck_style` is present and still defines each
      listed class. The classes are read from the style as `sanitise_deck_style` cleans it under the
      case's `design_system_active` (Ruling R27), because production reads only the cleaned style:
      a class defined only inside `@media` fails, since every at-rule is dropped. The restyle is
      also held to a build's hygiene (Ruling R28): the sanitiser must return it unchanged, and with
      a design system active its CSS may hold no hex colour literal. So a raw hex fails, and so
      does a `:root` palette, which the sanitiser drops under a design system, leaving its `var()`
      references undefined. Any other answer, such as a plain edit or a full `deck_spec` that
      carries a style, fails on `positions: []`, as before. Without the key every verdict and
      rationale is unchanged.
  - `render_measures`, for the builder and fixer: the slide is rendered in a browser with the
    Meridian section CSS, followed by the case's deck style CSS when its payload carries one
    (`mlflow_run.render_section_css`, also used by calibration). It must have zero overflow, contrast
    of at least 4.5, no off-palette colours, no console errors and no `<style>` tag. A case whose
    `expect` has `deck_style_classes` must also pass `deck_style_use_score`: every listed class is
    used, no inline `color`, `background`, `background-color`, `font-size`, `font-family` or
    `border-color` is declared, and every class used is defined by the payload's `section_css` or
    its deck style. The scorer loads the row's own case (split included) for the payload.
  - `judge`: an LLM judge (`mlflow.genai.make_judge`) using the pack's `judge_prompt.md`. It compares
    the candidate with the reference and the brief and returns pass or fail. For the builder and the
    build_reviewer, the brief also carries the payload's `deck_style` when it has one.
- **Row outcome.** A row fails if any scorer fails. It is skipped if the judge is skipped, or if
  every scorer is skipped. Skips cover infra errors (after 3 retries with backoff) and judge errors;
  both are excluded from pass rate.
- **MLflow.** One run per agent in experiment `tellr-agent-eval`, stored in the repo-root `mlflow.db`
  (gitignored).
  - Tags: `agent_key`, `config_name`, `content_hash`, `judge_endpoint`, `repeats`, `case_filter`,
    plus `not_comparable` (infra errors above 10% of rows) and `judge_unavailable` (every judge
    call errored).
  - Metrics: `pass_rate`, `pass_rate/<case_id>`, `repeat_stddev`, `infra_error_count`,
    `judge_error_count`, `mean_latency_ms`, `p95_latency_ms`, `mean_input_tokens`,
    `mean_output_tokens`, `est_cost_usd`. Cost uses `evals/configs/prices.yaml`, in USD per 1k tokens.
    An endpoint missing from that file is left unpriced.
- **Intent report** (`evals/intent_report.py`). Read-only; recomputes two architect numbers from one
  run's MLflow traces, because the `expected_category` scorer fails a row on a wrong intent *or* wrong
  edit positions, and MLflow logs no run-level aggregate for either.
  - *Intent accuracy*: the share of non-infra rows whose got intent equals the expected intent. A row
    with no output counts as wrong (and is also reported as `no_output`).
  - *Position accuracy*: over the rows whose expected and got intent are both `edit`, the share whose
    `set(target_positions)` equals the expected set.
  - On an insert row (`expect.inserted`, #314) position accuracy compares the model's own
    `target_positions` with the expected set. Production ignores those targets on an insert, so
    there it is a signal about the prompt, not a measure of what production builds.
    `expected_category` (above) is the production measure.
  - A held-out run prints one aggregate line, never a case id.
  - It reads the per-worktree `mlflow.db` unless `--tracking-uri` is given, and writes nothing.

  ```bash
  python -m evals.intent_report --run-id ID [--cases a,b] [--json]
  ```

## Running a sweep

Run from the repo root:

```bash
python -m evals.run_eval --agent all --config v1-baseline --repeats 3
```

| Flag | Default | Meaning |
|---|---|---|
| `--agent` | `all` | `all` or one agent key. |
| `--config` | `v1-baseline` | `v1-baseline` or a path to a YAML config. A YAML config targets one agent, so `--agent all` only works with `v1-baseline`. |
| `--repeats` | 3 | Repeats per case. |
| `--max-workers` | 8 | Parallelism of `mlflow.genai.evaluate`. |
| `--cases` | all | Comma-separated case ids, for example `gold_chart,overflow`. Also applies to `--calibrate`. |
| `--judge-endpoint` | `databricks-claude-sonnet-5` | Serving endpoint used as the judge. |
| `--split` | `train` | `train` or `heldout`. Selects the case set; see Held-out set below. Also applies to `--calibrate`. |
| `--calibrate` | off | Calibrate the judge instead of sweeping (see below). |
| `--no-render` | off | Skip rendering for the builder and fixer, which drops `render_measures`. |
| `--profile` | `tellr-dev` | Databricks CLI profile every live call uses. It overrides `.env` and `DATABRICKS_HOST`. `''` keeps the ambient environment. |

The agent's endpoint is probed before each sweep; an unreachable endpoint aborts. The probe maps a
`system.ai.<m>` gateway model name to its serving endpoint `databricks-<m>`; the agent call itself keeps the
configured name.

The harness runs each agent through `AgentRuntime.run_candidate` **without data tools bound**. The
data_analyst prompt mentions Genie and a vector index, but neither is available in the harness.

## Held-out set

Each agent has a second, separate set of cases (five per agent, seven for the builder and the
build_reviewer, twenty-two for the architect; 56 in total) in `evals/packs/<agent>/cases_heldout/`,
built from a different source deck than the train cases. It has the same four files per case and
shares each agent's `judge_prompt.md`. Its purpose is to check that a configuration tuned on the train
cases generalises, rather than having been fitted to them.

- **Selecting it.** Pass `--split heldout` (default `train`) to a sweep or to `--calibrate`. Train
  behaviour is unchanged when the flag is omitted.
- **Separate experiment.** Held-out sweeps log to the MLflow experiment `tellr-agent-eval-heldout`;
  train sweeps stay in `tellr-agent-eval`. Held-out runs also carry `split=heldout` and their own
  `cases_digest`.
- **Aggregate-only CLI output.** A held-out sweep prints one line per agent: run id, pass rate, infra
  error count and judge error count. It prints no case ids, rationales, payloads or references.
  This limits what an operator or an optimiser sees by accident. It is not an access control: the
  case files are in the repository, and the MLflow run still stores per-case metrics and judge
  rationales. `--calibrate --split heldout` also prints its per-case trust table.
- **Discipline, not a lock.** Nothing prevents anyone from reading the held-out cases or running
  them often. The set is only useful if it stays unseen. An optimiser must tune against train only.
  Held-out is scored on finalists, once a candidate has been chosen on train, and is not used to pick
  between candidates iteratively. Every look at it spends some of its independence.
- **Calibration is still required.** The judge must be shown to separate each held-out reference from
  its mutation before the pass rates mean anything. Run `python -m evals.run_eval --agent all
  --calibrate --split heldout` after any change to a judge prompt, the judge endpoint or a held-out
  case.
- **Regenerating.** `python -m evals.packs.<agent>.heldout` regenerates that agent's held-out cases.
  A bare `generate()` writes to `cases_heldout` only.
  The cross-split tests (`tests/unit/evals/test_cross_split.py`) guard that the split ids are pinned, no
  held-out payload or reference duplicates a train one, and the generators cannot write to train.

## Prompt optimisation

To run an optimisation pass on one agent, load the `optimise-agent-prompt` project skill
(`.claude/skills/optimise-agent-prompt/SKILL.md`). It sets the rules: train only during the search,
held-out once on finalists, a spend cap, no edits to cases, judges or scorers, and no promote or
commit.

## Adding a config

Create `evals/configs/<agent>/<name>.yaml`. The example is `evals/configs/builder/v1.yaml`.

| Field | Required | Meaning |
|---|---|---|
| `agent_key` | yes | One of the seven roles. |
| `name` | no | Label, default `agent_key`. |
| `base` | no | Only `v1` is supported. |
| `prompt_text` | no | Inline replacement prompt. Takes precedence over `prompt_file`. |
| `prompt_file` | no | Prompt file, path relative to the YAML. |
| `endpoint_name`, `temperature`, `max_tokens`, `top_p` | no | Model overrides. |

Run it with `python -m evals.run_eval --agent builder --config evals/configs/builder/<name>.yaml`.

## Viewing and comparing runs

```bash
mlflow ui --backend-store-uri sqlite:///mlflow.db   # from the repo root
```

Open `tellr-agent-eval`, select runs of the same `agent_key` and use Compare. Check `content_hash`
to confirm which definition a run used.

**Compared configs must share one judge endpoint.** The judge is itself a model; a different judge
shifts pass rates and makes comparison meaningless. Compare only runs with the same
`judge_endpoint` tag, and never a run tagged `not_comparable` or `judge_unavailable`.

## Calibration

```bash
python -m evals.run_eval --agent all --calibrate
```

For each case, the judge must **pass** `reference.json` and **fail** `calibration.json`'s
`should_fail` output (builder and fixer outputs are rendered first). A case is *trusted* only when
both hold. A case the judge cannot separate from its mutation gives pass rates that mean nothing,
so re-calibrate after changing a judge prompt, the judge endpoint or any case. All 35 cases were
trusted when the v1 baseline below was recorded.

To calibrate only some cases (for example the ones you just added), add `--cases`:
`python -m evals.run_eval --agent architect --calibrate --cases add_slide_anchor,add_slide_end`.
It honours `--split`. An id that matches no case for the chosen agents and split exits non-zero,
naming the unknown id(s), so a typo cannot calibrate nothing and read as a pass. The ids that do
match are still calibrated and printed before the exit.

Calibration proves the judge can discriminate on these cases. It does not prove the deterministic
scorers' expectations are reasonable for the live agent (see the baseline notes).

## Promotion

`evals.harness.promote` has a CLI:

```bash
python -m evals.harness.promote --config ROLE=PATH [--run-id ROLE=ID] [--dry-run]
```

`--config` and `--run-id` repeat, once per role. It can also be called from Python:

```python
import src.core.database  # noqa: F401  (break the import cycle first)
from evals.harness.config import load_config
from evals.harness.promote import promote

promote({"builder": load_config("evals/configs/builder/<name>.yaml")}, dry_run=True)
```

`promote(chosen, dry_run=False, repo_root=None, run_ids=None)` takes the chosen `{role: config}` and rewrites, in place:

- `src/services/agent_definition_manifest_v1.py`, only the model fields and the prompt text that
  changed, so unchanged roles stay byte-identical;
- `PACKAGED_V1_CONTENT_HASHES` in `tests/unit/test_packaged_release_loader.py` and
  `tests/unit/test_graph_definition_manifest.py`.

It refuses, writing nothing, when:

- the role is unknown or the config belongs to another role;
- the config's `content_hash` does not match its content;
- a role whose v1 prompt is the source of a `LegacyV1PromptTransition` has its `prompt_text` changed
  (that needs a deliberate migration);
- the promoted manifest's hash differs from the evaluated config's hash;
- a pinned-hash entry is not found exactly once.

`dry_run=True` computes everything without writing. After writing it prints the contract re-record
command, which must be run because the frontend lifecycle contract embeds every v1 prompt and hash:

```bash
DATABASE_URL=sqlite:////tmp/tellr-contract-rerecord.db python -m tests.integration.graph_lifecycle_journey --write-contract frontend/tests/fixtures/graphLifecycleContract.json
```

It also warns if a promoted prompt no longer matches `src/core/skills/<role>.py` `INSTRUCTIONS`;
`promote` does not edit skill files.

## Regenerating fixtures and cases

- Meridian gold slides: `python evals/fixtures/split_gold.py`. It reads the source deck from
  `~/Downloads/html-slides-vs--powerpoint--a-better-way-to-present.html` and writes
  `evals/fixtures/meridian/gold/<n>.html` and `.js`.
- Pack cases: `python -m evals.packs.<agent>.mutations` (for example `evals.packs.builder.mutations`).
  Generation is idempotent.

## Tests

The harness's own self-tests are in `tests/unit/evals/` and run in the normal unit suite. They use
fakes. Real-model runs (`evals.run_eval`) are not collected by CI.

## Baseline: v1-baseline, 2026-10-06

`git_sha` 904b4153d10098e5bb1a3b5b137ab57b5d447151 for architect, data_analyst, deck_reviewer and
fix_reviewer. builder, build_reviewer and fixer were re-swept at `git_sha`
3d5848dd1dd60e455762d44b5087b0a4a0e43b3a after the gold chart fix (`gold/3.js` and `gold/6.js` still
hard-coded the old muted colour `#6B7280`; it is now `#4B5563`). Agent endpoint `databricks-claude-opus-4-6`,
judge `databricks-claude-sonnet-5`, 3 repeats, 5 cases per agent (15 rows each), 35 of 35 cases
trusted at calibration (one `fix_reviewer` case needed a re-run after a malformed judge response).
Total estimated cost **USD 16.81**. 0 infra errors in every agent. Each run carries `cases_digest`
and `git_sha` tags, and the judge rationale is stored on each row.

| Agent | Pass rate | Infra errors | Judge errors | Mean latency (s) | Est. cost (USD) |
|---|---|---|---|---|---|
| fixer | 1.00 | 0 | 0 | 14.0 | 2.27 |
| build_reviewer | 1.00 | 0 | 1 | 21.2 | 2.56 |
| deck_reviewer | 0.93 | 0 | 0 | 21.6 | 3.08 |
| architect | 0.71 | 0 | 1 | 13.9 | 2.36 |
| builder | 0.47 | 0 | 0 | 23.6 | 3.43 |
| data_analyst | 0.40 | 0 | 0 | 10.4 | 0.78 |
| fix_reviewer | 0.07 | 0 | 0 | 14.8 | 2.33 |
| **Total** | | | | | **16.81** |

A judge error is a row whose judge reply could not be parsed (`MlflowException: Failed to parse
response from judge model`); the row is skipped, so the pass rate is over 14 rows, not 15.

Failing cases (pass rate below 1.0), with the attribution and the stored rationale:

- **architect/edit_request (0/3), AGENT.** The edit is right but `deck_spec` is null. Judge: "a
  content-changing edit must be translated into an updated deck_spec ... the candidate returned
  deck_spec: null".
- **architect/build_request (2/3), AGENT (weak).** One repeat built 5 slides against the reference's
  10. Judge: "the slide count (5) is far shorter than the reference's (10) ... not in the same
  ballpark". The judgement is subjective.
- **data_analyst/figures_inline (0/3), AGENT.** The request already states "98% on StatCounter"; the
  agent answers `no_tool` or `missing_data`. Judge: "the analyst should simply pass it through
  faithfully rather than treat it as requiring external retrieval".
- **data_analyst/two_sources (0/3), AGENT.** Both conflicting figures are in the request; the agent
  answers `missing_data`. Judge: "No external tool or additional data ... was actually needed".
- **data_analyst/unsourced_public_stat (1/3), AGENT.** Expected `no_tool`, got `missing_data`.
  Judge: "The candidate instead returned 'missing_data' ... claims to have tried tools". No tools are
  bound in the harness.
- **data_analyst/conflicting_figures (2/3), AGENT.** The agent averages the two surveys. Judge: it
  "computes/invents a 'reasonable central estimate' of approximately 11-12 MB ... effectively
  resolving the conflict".
- **builder/chart_no_data (0/3), AGENT.** The agent invents a chart with specific scores when
  `resolved_data.figures` is empty. Judge: "the candidate invents a specific device-by-device
  fidelity chart ... despite figures being empty" (Laptop 98/85, Tablet 95/52, and so on).
- **builder/gold_chart (1/3), too_much_content (1/3), gold_bullets (2/3), AGENT.** The slide
  overflows or intrudes into the 88px/56px safe area (10 to 85px past it). `render_measures`:
  "Overflow: 43.0px; Safe area intrusion: 84.0px past the 88px/56px safe area". Judge: "safe_area_px of
  10.0 ... explicit hard-evidence grounds for failure". `gold_stats` passes 3/3. One `gold_bullets`
  judge rationale also faults on-palette hard-coded hexes (`#4B5563`, `#374151`) in the chart script;
  that is secondary to the safe-area failure.
- **build_reviewer:** 1.00 (14 of 15 rows counted). The `source_contradiction` case now passes 3/3:
  the earlier unplanted `rogue_colour` finding is gone with the fixture fix. The one judge error is a
  `rogue_colour` row whose judge reply was unparseable.
- **fix_reviewer/restyle_reject, content_broken_reject (0/3 each), fault_left_reject (1/3),
  AGENT.** The reviewer invents criterion names and the output schema rejects the reply, so
  `structured` is null. Reproduced once: "Unknown criterion 'brand-color'. Valid criteria: ['arc_gap',
  ...]". Judge: "no candidate output to judge".
- **fix_reviewer/good_fix_accept, good_contrast_fix_accept (0/3 each), AGENT.** The reviewer
  accepts the fix (verdict `fixed`) but echoes the original finding with `status: fixed`.
  Production `fix_reviewer_node` computes `still_open = [f for f in re_findings if f.criterion ==
  criterion]` (`src/services/graph/nodes.py:2675`), which ignores `status`, so this reply would block
  a good fix in production. The scorer matches production semantics: "Unplanted objective criteria
  found: {'overflow'}". This is a fix_reviewer prompt ambiguity. Separately, the judge was
  inconsistent between the two identical-shape cases (it passed `good_fix_accept`, failed
  `good_contrast_fix_accept`).
- **deck_reviewer/out_of_order (2/3), AGENT (variance).** One repeat did not place the `arc_gap`
  finding where the case expects it: "Missing expected findings: {('arc_gap', -1)}".

Earlier runs in the `tellr-agent-eval` experiment are tagged `superseded`, including the builder, build_reviewer and fixer runs from the first `904b4153d` sweep (gold chart colour): they predate the Meridian
frame-rule fix (88px/72px padding, footer at 56px), the safe-area check in `render_measures`, the
`slide_spec`/`resolved_data` judge inputs, the required architect edit `deck_spec`, the fixer's
`resolved_data` input and its prompt change, and stored judge rationales.

## Held-out baseline: v1-baseline, 2026-10-08

`git_sha` fd29eb37f8ff65ce5358409134fbf683292e119a, experiment `tellr-agent-eval-heldout`
(`--split heldout`). Agent endpoint `databricks-claude-opus-4-6`, judge `databricks-claude-sonnet-5`,
3 repeats, 5 cases per agent (15 rows each). All 35 held-out cases were trusted at calibration; five
cases needed a re-run after a malformed judge reply, a network drop or a `KeyError: 'result'`, and none
was ever misclassified. Total estimated cost **USD 15.66**. 0 infra errors in every agent.

| Agent | Held-out | Train (2026-10-06) | Judge errors (held-out) |
|---|---|---|---|
| fixer | 1.00 | 1.00 | 0 |
| deck_reviewer | 0.93 | 0.93 | 0 |
| build_reviewer | 0.87 | 1.00 | 0 |
| architect | 0.77 | 0.71 | 2 |
| builder | 0.40 | 0.47 | 0 |
| data_analyst | 0.33 | 0.40 | 0 |
| fix_reviewer | 0.00 | 0.07 | 0 |

Held-out and train agree on the pass rates and on the causes of failure listed below, so the v1
prompts are not overfitted to the train cases; the weak agents are weak on both sets. Differences are
within repeat variance except `build_reviewer`, which scored lower on held-out.

Distinct causes of failure, all attributed to the agent rather than the harness:

- **fix_reviewer** rejects: the reply is rejected by the output schema (`structured=None`). The v1 prompt
  says to use criterion names from the registry but does not list them. Accepts: the reviewer echoes the
  original finding as `objective: true, status: fixed`, which production's `still_open` ignores `status`
  for, so a good fix would be blocked in production too.
- **data_analyst** answers `missing_data` for figures already in the request, and for requests with no
  applicable tool, because the prompt advertises Genie and a vector index that the harness does not bind.
- **builder** invents figures when `resolved_data.figures` is empty, and intrudes into the safe area on
  an overloaded brief.
- **architect** edits return `deck_spec: null`: the v1 prompt says DeckSpec construction is build-only,
  while the judge rubric requires it on edits.
- **Judge noise**: two architect `discuss` rows hit `KeyError: 'result'` and were skipped; one
  deck_reviewer `clean` row's verdict contradicts its own rationale.

Known limits: `evals/packs/deck_reviewer/judge_prompt.md` and the data_analyst judge prompt contain
train-deck example figures, and eight held-out `calibration.json` negatives are byte-identical to train's.
Neither changes a held-out payload or reference. `error_detail` is not stored for `incomplete` rows, so
the exact invalid criterion name in fix_reviewer rejects is inferred from the train reproduction.

## Architect re-baseline: edit returns the revised deck spec, 2026-10-08

`git_sha` b893f5a363ddfabecfadd6e0b1488b764da4acad. The architect v1 prompt now requires an edit to return
the full `deck_spec` with only the requested slides revised (the deck spec is the source of truth), and the
graph refuses an edit without one instead of rebuilding from the old brief. Same endpoints, 3 repeats;
all 10 architect cases trusted at calibration on both splits.

| Split | Pass rate | Before | `edit_request` | `build_request` | Judge errors | Est. cost (USD) |
|---|---|---|---|---|---|---|
| train | 0.86 | 0.71 | 3/3 (was 0/3) | 1/3 (was 2/3) | 1 | 2.94 |
| heldout | 1.00 | 0.77 | n/a | n/a | 1 | 2.58 |

The `build_request` failures are the existing cause: the candidate builds a 5-slide deck where the
reference has 10, and the judge fails the argument as too thin. It is unrelated to the edit change and
within one repeat of the previous run. Held-out per-case results are left out, as for the held-out baseline. This re-baseline changes the architect's prompt, so the architect
rows in the earlier baseline tables describe the previous v1 prompt.

## Architect intent and slide references (#313), 2026-10-20

Issue #313 reported two things: the architect picking the wrong intent for casual phrasings, and an
off-by-one on edits that name a slide ("slide 2" read as position 2). This pass adds cases for both,
fixes the endpoint probe so an architect sweep can run at all, and measures the architect before and
after the graph began sending it resolved slide numbers.

- **New cases, four per split** (same ids in both; held-out words them differently on its own deck, and
  its messages are not reproduced here). Every one is unambiguous under the current rules.

  | Case id | Tests |
  |---|---|
  | `edit_polite_ordinal` | an edit phrased as a polite question, with an ordinal reference |
  | `edit_last_slide` | a last/final reference |
  | `edit_multi_slide` | a multi-slide range or list |
  | `discuss_slide_question` | a question naming a slide, which must not rebuild it |

  The architect now has nine cases per split. The existing five differ from before only by the two
  payload keys below.
- **Payloads carry two new keys.** Every architect case payload now has `slide_numbering` and
  `slide_references`, generated by the production helper (`architect_slide_payload` in
  `src/domain/slide_numbering.py`). The judge sees only `message` and `current_deck_spec`, so
  calibration is unaffected. See `docs/technical/backend-overview.md`, "Graph Path: Slide Numbers and
  Positions".
- **Probe fix.** The manifest's architect endpoint is `system.ai.claude-opus-5`, which is a gateway
  model name and not a serving-endpoint name, so `_endpoint_reachable` failed and every architect
  v1-baseline sweep aborted. The probe now looks up `databricks-<m>` (see Running a sweep).
- **Setup.** Agent `system.ai.claude-opus-5`, judge `databricks-claude-sonnet-5`. `prices.yaml` has no
  opus-5 entry, so cost is estimated from tokens at USD 5 / 25 per million input / output for the agent
  and about USD 0.035 per judge call. All 9 train and all 9 held-out architect cases were trusted at
  calibration; two held-out references needed a re-judge after `KeyError: 'result'` judge errors.

"v1" is the architect prompt at HEAD before this issue (content hash 3ed38cb4); `slide-refs` is the
candidate (`evals/configs/architect/slide-refs.md`, ffc3074d) that was promoted. S0 is the v1 prompt on
the new payloads, run to isolate the effect of the keys alone. Pass rate is the harness's, over scored
rows (judge errors are skipped); intent and position accuracy are `evals/intent_report.py`'s. Run ids
are from the issue-313 worktree's local `mlflow.db`.

| Run | Config | Split | Cases | Repeats | Rows | Pass rate | Intent acc. | Position acc. | Judge errors | Mean in/out tokens | ≈ USD |
|---|---|---|---|---|---|---|---|---|---|---|---|
| B1 b1cac4ff | v1 (3ed38cb4) | train | 4 new | 5 | 20 | 1.00 | 20/20 | 15/15 | 0 | 12.5k / 3.5k | 3.68 |
| B2 a76ee18b | v1 | train | edit_request, confirm_design, discuss | 5 | 15 | 1.00 | 15/15 | 5/5 | 2 | 12.5k / 2.0k | 2.20 |
| B3 5fb6440d | v1 | train | build_request, ask_data | 3 | 6 | 1.00 | 6/6 | – | 0 | 8.6k / 4.1k | 1.08 |
| B4 5bf79a39 | v1 | held-out | all 9 | 1 | 9 | 1.00 | 9/9 | 4/4 | 0 | 10.2k / 2.3k | 1.29 |
| S0 7d4f85ee | v1 prompt, new payloads | train | 4 new | 1 | 4 | 1.00 | 4/4 | 3/3 | 0 | 12.8k / 3.4k | 0.73 |
| F1 5622ab66 | slide-refs (ffc3074d) | train | 4 new | 5 | 20 | 1.00 | 20/20 | 15/15 | 2 | 13.1k / 3.3k | 3.68 |
| F2 84ab2df0 | slide-refs | train | edit_request, confirm_design, discuss | 5 | 15 | 0.92 | 15/15 | 5/5 | 2 | 13.1k / 1.9k | 2.23 |
| F3 69ece733 | slide-refs | train | build_request, ask_data | 3 | 6 | 1.00 | 6/6 | – | 0 | 8.9k / 4.3k | 1.13 |
| F4 417a9ec7 | slide-refs | held-out | all 9 | 1 | 9 | 1.00 | 9/9 | 4/4 | 1 | 10.7k / 2.4k | 1.33 |

The nine runs sum to about USD 17.35. With a 2-row probe run (11c50057), calibration and the
post-review diagnostic described below, the total is about USD 19.74. Held-out results are aggregates
only (B4, F4), as for the earlier held-out baselines.

What it showed:

- **The reported off-by-one did not reproduce.** The v1 architect at HEAD was already at ceiling on every
  case before any change: intent correct on 50/50 rows (B1-B4) and positions correct on 24/24 edit rows.
  The issue's `edit_request` 3/5 off-by-one is not there. The issue (filed 2026-10-12) predates the
  prompt's SLIDE NUMBERS rule, added 2026-10-13 in 5653f3ec, which is the most likely reason.
- **The keys did not change the measured outcome.** S0 (v1 prompt, new payloads) and F1-F4 (`slide-refs`)
  are equally exact: intent correct on every row (45/45 train, 9/9 held-out) and positions exact on every
  edit row (23/23 train, 4/4 held-out).
- **The one failed row** is F2's: a `discuss` row whose intent is right. The judge objected to an empty
  `target_positions` list (the reference has one too) and to a follow-up offer. That is judge-subjective
  and within one repeat.
- **Why `slide-refs` was promoted.** It is the v1 default for its contract, not for a measured gain:
  positions are copied from deterministic keys, it is robust on a gapped deck (where a slide number is
  not position + 1), and an out-of-range reference becomes `discuss` instead of an edit. No train-driven
  tuning happened.
- **Multi-reference edits.** A post-review diagnostic ran `slide-refs` directly on three ad-hoc
  multi-reference edits (a layout copied from one slide to another, a chart replaced with another slide's
  chart): it targeted only the slide being changed in 3/3 (about USD 0.58, no judge). The two-reference
  case is not yet an eval case; a follow-up.
- **Branch shipped.** The payload keys are wired into `architect_node` and the `slide-refs` prompt is the
  v1 default. The architect rows in the earlier baseline tables above describe previous prompts.
- **Rollout caveat.** The Graph V1 manifest only seeds a fresh bootstrap (it is not read once any Graph
  Release exists), so an existing install keeps its persisted architect prompt: it gets the two payload
  keys immediately, but the new SLIDE NUMBERS text only when an admin publishes a release carrying it
  (see "Rollout" in `docs/technical/backend-overview.md`).

## Architect: add a slide (#314), 2026-10-20

Issue #314 reported that a user on the graph path cannot ask for a new slide in an existing deck. The
shipped architect prompt told the model that adding or removing slides is not an edit, and the node
refused any change of the slide-position set. This pass makes the yardstick score an insert the way
production builds it, adds four insert cases per split, measures the shipped prompt, searches for a
better one on train only, and promotes the finalist. The node behaviour is in
`docs/technical/backend-overview.md`, "Editing the deck's slides" (the #314 alignment is its "The
spec path: alignment" part).

- **New cases, four per split** (same ids in both; held-out words them differently on its own deck, and
  its messages are not reproduced here).

  | Case id | Tests |
  |---|---|
  | `add_slide_anchor` | a new slide placed after a named slide: only it is built, and the later slides shift unchanged |
  | `add_slide_end` | a new slide appended at the end of the deck, not written over the last slide |
  | `add_slide_as_number` | a new slide given a named slide's number: it takes that place and the named slide moves one place on |
  | `add_slide_and_revise` | a new slide plus a requested change to a later slide: both are built, nothing else changes, and the deck-level fields stay as they were |

  The architect now has thirteen cases per split, 43 across the harness. They are scored by the
  production-semantics insert check (see Scorers). Each case's `should_fail` output, used at
  calibration, is one wrong way to do it: for `add_slide_anchor`, the right place and targets but a
  new slide that is off-request (only the judge can fail it); for `add_slide_end`, the last slide
  replaced instead of a slide added; for `add_slide_as_number`, the slide inserted one place late;
  for `add_slide_and_revise`, the slide added and the requested change forgotten. All eight cases were
  trusted at calibration; one held-out reference needed a re-judge after a judge `KeyError: 'result'`.
- **Setup.** Agent `system.ai.claude-opus-5`, judge `databricks-claude-sonnet-5`. As in #313, cost is
  estimated from tokens at USD 5 / 25 per million input / output for the agent plus about USD 0.035 per
  judge call, because `prices.yaml` has no opus-5 entry.

"v1-baseline" is the architect prompt as shipped before this issue, `slide-refs` (`ffc3074d`, promoted
in #313). `add-slide` (`e5caefa8`) and `add-slide-b` (`b5a4cba6`) are the two candidates
(`evals/configs/architect/add-slide.md`, `add-slide-b.md`); `add-slide-b` is the finalist and was
promoted. B is before, S is the search on train, F is the finalist. Pass rate is the harness's, over
scored rows (judge errors are skipped); intent and position accuracy are `evals/intent_report.py`'s,
and a dash means no edit rows or, on held-out, not reported. Run ids are from the issue-314 worktree's
local `mlflow.db`.

| Run | Config | Split | Cases | Repeats | Rows | Pass rate | Intent acc. | Position acc. | Judge errors | Mean in/out tokens | ≈ USD |
|---|---|---|---|---|---|---|---|---|---|---|---|
| B1 8e5f7755 | v1-baseline (ffc3074d) | train | 4 insert | 2 | 8 | 0.00 | 0/8 | – | 0 | 13.1k / 0.4k | 0.89 |
| B2 82ed0000 | v1-baseline | train | 9 existing | 1 | 9 | 1.00 | 9/9 | 4/4 | 0 | 12.2k / 3.1k | 1.57 |
| B3 4a3dd928 | v1-baseline | held-out | 4 insert | 1 | 4 | 0.00 | 0/4 | – | 0 | 11.2k / 0.4k | 0.41 |
| S1 c26f6789 | add-slide (e5caefa8) | train | 4 insert | 1 | 4 | 1.00 | 4/4 | 4/4 | 0 | 13.7k / 5.1k | 0.93 |
| S2 9b7cd603 | add-slide-b (b5a4cba6) | train | 4 insert, `build_request`, `edit_request` | 1 | 6 | 1.00 | 6/6 | 5/5 | 0 | 13.1k / 4.9k | 1.34 |
| F1 146133de | add-slide-b | train | 4 insert | 3 | 12 | 1.00 | 12/12 | 12/12 | 0 | 13.8k / 4.7k | 2.67 |
| F2 9a15c202 | add-slide-b | train | 9 existing | 1 | 9 | 1.00 | 9/9 | 4/4 | 0 | 12.8k / 2.8k | 1.53 |
| F3 f54dd66b | add-slide-b | held-out | all 13 | 1 | 13 | 1.00 (9 scored) | 13/13 | – | 4 | 11.5k / 2.3k | 1.95 |
| F3b ffaa27ab | add-slide-b | held-out | the 4 judge-error rows of F3 | 1 | 4 | 1.00 | 4/4 | – | 0 | 11.8k / 2.1k | 0.59 |

The runs and two calibration passes (about USD 0.63) sum to **about USD 12.51**, inside the USD 15 cap.
Held-out results are aggregates only (B3, F3, F3b). F3 scored nine rows and four judge-errored; F3b
re-ran only those four. Combined, the held-out insert cases pass 4/4 (B3: 0/4) and the nine existing
held-out cases pass 9/9.

What it showed:

- **The shipped prompt answers every add with `discuss`.** B1 is at the floor: intent wrong on 8/8 rows,
  every one `discuss`. Held-out gives 0/4 (B3). The cause is a single sentence, the EDITING rule
  that adding or removing slides is not an edit. The nine existing train cases are untouched by it
  (B2, 9/9), so this is not a regression elsewhere.
- **Candidate `add-slide` placed the slides but bound them in a way production refuses.** It rewrote the
  EDITING block (adding is an edit, with the new slide, the unchanged later slides and the targets
  stated) and added an anchor exception to SLIDE NUMBERS (a named slide on an add is the anchor, not a
  target). S1 passed 4/4. But the yardstick does not check template bindings. The fixture's
  `template_sections` all have a null `label`, and the prompt says to copy `label` into `slide_type` and
  `index` into `template_section_index`, so the model emits an index-only pair (`slide_type` null,
  index set). Production's validators (`complete_index_only_bindings`, `invalid_slide_bindings`, run in
  `architect_node`) refuse the whole turn on an index-only pair whose section has no label, because it cannot be
  completed from the inventory (`invalid_slide_type_binding`). A diagnostic ran those two functions over each run's outputs and the
  payload's `template_sections`: **3 of the 4 S1 insert rows would be refused.**
- **That gap is pre-existing.** The same diagnostic on the shipped prompt (B2) refuses 2 of its 5
  spec-bearing rows (`build_request` and `edit_request`) on this fixture. It is not introduced by #314,
  and the yardstick is deliberately not changed after the BEFORE runs.
- **Candidate `add-slide-b` fixes it.** It is `add-slide` plus a BINDING sentence (an entry whose
  `label` is null cannot be bound, and `slide_type` and `template_section_index` are set together or not
  at all), and the EDITING new-slide sentence defers binding to those rules. S2 passed 6/6 with 0/6
  production binding refusals. The finalist rule added a supplementary condition before the F runs: the
  finalist's production binding refusals must not exceed v1's on the same cases. F1 0/12, F2 0/5 (v1:
  2/5), F3 0/9 scored rows.
- **Insert cost.** An insert returns the full deck spec, so output tokens rise from about 0.4k (a
  `discuss`) to about 4.7k per row. A row costs about USD 0.22.
- **Accept rule** (fixed before any F run). All three held, and the finalist was accepted:
  1. F1: pass rate at least 0.75, every insert case at least 2 of 3, and above B1's. Got 1.00, every
     insert case 3/3, B1 0.00.
  2. F2: at least 8 of 9 and at least B2's passes minus one, with no `contract` failure. Got 9/9 (B2 9/9).
  3. F3: the 4 held-out inserts at least 3 of 4 and above B3, and the 9 existing at least 8 of 9. Got 4/4
     (B3 0/4) and 9/9.

  Had no finalist been accepted, the fallback was to ship the code and cases with the unchanged prompt
  and leave the issue open; that branch was not taken.
- **Overrides of `optimise-agent-prompt`**, taken for budget (USD 15 at about USD 0.2 per row): the
  finalist was confirmed at 3 repeats on the insert cases plus 1 repeat on the nine existing train cases
  (the skill says 5 repeats on all train); held-out ran at 1 repeat (the skill says 3; the #313
  precedent); and the candidate author, who saw train only, ran no sweeps.
- **Branch shipped.** `add-slide-b` is the v1 default in `src/core/skills/architect.py`
  (`b5a4cba61121`, previously `ffc3074dc920`), promoted with `evals.harness.promote`. The architect
  prompt rows in the earlier baseline tables describe previous prompts.
- **Still open.**
  - The yardstick should run production's binding validation. The diagnostic was run by hand, and the
    fixture's template sections are unlabelled.
  - No eval case measures the no-place product rule (a new slide with no stated place goes where it fits
    the argument, before a closing slide). The layer-3 RC2 test exercises it, but it is not run in CI.
  - Insert rows' position accuracy (above) measures targets production ignores.
- **Rollout caveat.** The Graph V1 manifest only seeds a fresh bootstrap (it is not read once any Graph
  Release exists), so an existing install keeps its persisted architect prompt. It gets the node
  behaviour at once (alignment, the shift and the refusals) but keeps answering an add with `discuss`
  until an admin publishes a release carrying the new prompt (see "Rollout" in
  `docs/technical/backend-overview.md`).

## Architect: edit operations, 2026-10-28

A production user asked to replace one slide of a 16-slide deck with seven; the architect planned it
right twice and the code refused it both times, because a whole revised `deck_spec` cannot say which
slide was rewritten and which are new (`align_slides` ties and refuses `ambiguous`), and delete and
reorder were not supported at all. An edit now returns an ordered `operations` list (insert, update,
delete, replace, move) plus an optional `deck_changes`, which `architect_node` composes over the
persisted spec (design: `docs/superpowers/specs/2026-10-28-architect-edit-operations-design.md`). This
pass adds four cases per split, measures a new prompt on train and held-out, and promotes it.

- **New cases, four per split** (same ids in both; held-out words them differently on its own deck, and
  its messages are not reproduced here). They are scored by the operations check (see Scorers).

  | Case id | Tests |
  |---|---|
  | `delete_slide` | one slide deleted: nothing is rebuilt and the later slides move up unchanged |
  | `move_slide` | one slide moved after a named slide: a reorder that rebuilds nothing |
  | `replace_slide_expand` | one slide replaced by four (the production transcript's shape): the first rewrites it in place, three new slides follow |
  | `mixed_operations` | a delete, an update and an expand into three in one message: only those slides are built |

  The architect now has nineteen cases per split, 49 across the harness. Each train `should_fail` is
  one wrong way to do it (for the delete and the move, the 1-based slip; for the replace, the same plan as
  a whole grown `deck_spec`, which production's alignment refuses; for the mixed edit, also rewriting
  the untouched closing slide).
- **Calibration** (judge `databricks-claude-sonnet-5`, `--calibrate --cases` the four new ids):

  | Case | Train | Held-out |
  |---|---|---|
  | `delete_slide` | trusted | trusted |
  | `move_slide` | not trusted (judge passed the should_fail) | trusted |
  | `replace_slide_expand` | not trusted (judge passed the should_fail) | not trusted (judge passed the should_fail) |
  | `mixed_operations` | not trusted (judge passed the should_fail) | trusted (one re-run after a judge `KeyError: 'result'`) |

  An untrusted case is scored by its deterministic checks (`contract` and `expected_category`, the
  operations check), as `fill_blank_slide` is: its judge verdict is reported, not counted.
  `replace_slide_expand` was expected to be deterministic-only, because its should_fail composes to
  the same deck as the reference. On train the judge also cannot separate the move's and the mixed
  edit's should_fail from the reference. In every run below the judge passed those rows as well, so
  the rule changed no outcome.
- **Setup.** Agent `system.ai.claude-opus-5-5` (manifest v1), judge `databricks-claude-sonnet-5`,
  profile `tellr-dev`. `prices.yaml` has no entry for the agent's endpoint, so the harness logged no
  `est_cost_usd`. Cost is estimated from the logged mean tokens at USD 5 / 25 per million input / output
  (the #313 and #314 rate; Opus 5.5's list price is USD 4 / 20, so this is an upper bound) plus
  USD 0.05 per judge call (also an upper bound: the architect judge payloads measure about 6.5k to 11k
  tokens, about USD 0.02 to 0.04).

"v1" before this change is the shipped prompt (content hash `d4018d7b`, the #314 `add-slide-b` text on
the opus-5-5 seed). `edit-ops` (`8f1493ef`) is the candidate (`evals/configs/architect/edit-ops.md`).
It is the shipped prompt with three parts rewritten: the PAYLOAD RULES edit line, the EDITING block,
and the SLIDE NUMBERS block. Every other block is byte-identical. S is the screen, F the finalist runs.
Pass rate is the harness's, over scored rows (judge errors are skipped). Run ids are from the
`architect-edit-ops` worktree's local `mlflow.db`.

| Run | Config | Split | Cases | Repeats | Rows | Pass rate | Judge errors | Mean in/out tokens | ≈ USD |
|---|---|---|---|---|---|---|---|---|---|
| S1 ec4a9f2c | edit-ops (8f1493ef) | train | 4 new | 3 | 12 | 1.00 | 0 | 16.5k / 0.9k | 1.85 |
| F1 c1bec24d | edit-ops | train | all 19 | 3 | 57 | 1.00 (56 scored) | 1 | 16.0k / 0.9k | 8.69 |
| F2 bcf7d542 | edit-ops | held-out | all 19 | 1 | 19 | 1.00 | 0 | 14.3k / 0.8k | 2.68 |

Calibration (18 judge calls, about USD 0.90) and two ad-hoc live checks (about USD 0.28, no judge,
described below) bring the total to **about USD 14.40**, inside the USD 20 cap. Held-out is an
aggregate only (F2).

What it showed:

- **The screen found nothing to fix.** S1 passed 12 of 12: each new case 3/3, every answer given as
  operations (`delete` 5; `move` 6 after 3; `replace` 4 with four slides; `delete` 2, `update` 1 and
  `replace` 7 with three). No row failed, so there was no failure cause to aim a second candidate at,
  and `edit-ops-b` and `edit-ops-c` were not written (the skill's rule: one change per candidate,
  aimed at a cause). The follow-up pass below later used the name `edit-ops-b` for its own tweaks.
- **Finalist, train (F1).** All 19 train cases passed every scored row: 3/3 each, except
  `discuss_slide_question` at 2/2 scored. Its third row hit a judge parse error, and its `contract`
  and `expected_category` passed. Every existing edit case (`edit_*`, `add_slide_*`,
  `fill_blank_slide`, `edit_beside_blank`) was answered with operations, and the operations check
  passed it. `build_request`, `ask_data`, `confirm_design` and both `discuss` cases kept their intent.
- **Finalist, held-out (F2).** 19 of 19, 0 judge errors, 0 infra errors. Every scorer passed on every
  row, so each new case passed 1/1 by its deterministic scorer.
- **Production binding refusals.** The #314 diagnostic (production's `complete_index_only_bindings` +
  `invalid_slide_bindings` over each row's composed spec and the payload's `template_sections`), run by
  hand over F1: 0 of 45 spec-bearing rows would be refused.
- **Ad-hoc checks** (not eval cases, train payloads only):
  - The arc-review sweeper's message (`spec_sync.ARC_REVIEW_MESSAGE`) on the `edit_request` deck came
    back as `edit` with the full 10-slide `deck_spec`, no `operations`, and every position in
    `target_positions`. That is the describe-only path, unchanged.
  - The `move_slide` payload plus a `rejected_edit` (a previous answer moving the slide after itself,
    with the `move_after_itself` problem) came back corrected (`move` 6 after 3).
- **Acceptance bar** (spec §9 with PLAN-CORRECTIONS C5). **Met.**
  1. Every existing case passed at least its recorded v1 rate. The recorded rates are all 1.00: the
     four inserts 3/3 (#314 F1), the nine older cases 1/1 (#314 F2), and `fill_blank_slide` and
     `edit_beside_blank` 3/3 (`630beeaf`). F1 got 3/3 on each, and 2/2 scored on
     `discuss_slide_question`.
  2. Each new case passed at least 2/3 on train and 1/1 on held-out by the deterministic scorer. Got
     3/3 on train and 1/1 on held-out.
  3. The judge's calibration is recorded (above).
- **Overrides of `optimise-agent-prompt`**, delegated by the owner for this change (PLAN-CORRECTIONS
  C18):
  - The candidate was screened on the four new cases ×3, and the finalist confirmed on all train ×3
    and held-out ×1. The skill says ×5 and ×3.
  - No fresh `v1-baseline` run was made: the old prompt cannot express a delete or a move, so the
    existing cases' bar is the recorded numbers.
  - This pass promoted the finalist, edited `INSTRUCTIONS` and committed. The skill leaves those to
    the user.
  - The skill's "architect edits must return the full revised `deck_spec`" trap no longer applies.
- **Branch shipped.** `edit-ops` became the v1 default in `src/core/skills/architect.py`
  (`8f1493ef35f9`, previously `d4018d7bdc30`; since replaced by `edit-ops-b`, see the follow-up pass
  below). It was promoted with
  `python -m evals.harness.promote --config architect=evals/configs/architect/edit-ops.yaml --run-id architect=c1bec24d8d694cf3a82440d3cc68d368`,
  and the frontend lifecycle contract was re-recorded. The architect prompt rows in the earlier tables
  describe previous prompts.
- **Still open.**
  - The architect judge prompt does not describe operations. It judges the composed form, and on
    train it cannot separate three of the four new should_fails.
  - No eval case covers the describe-only sweeper or the `rejected_edit` retry. Both were checked
    once, by hand, above. (The sweeper now has one: `redescribe_deck`, below.)
  - The yardstick still does not run production's binding validation (diagnostic by hand, as in #314),
    and the message wording (new slides by their revised number, deleted ones by their old number) is
    not scored.
- **Rollout caveat.** As for #313 and #314, the Graph V1 manifest only seeds a fresh bootstrap, so an
  existing install keeps its persisted architect prompt until an admin publishes a release carrying
  the new one. The node behaviour applies at once on every release: the operations path whenever a
  model emits operations, the retry, the deferred message and the refusal note.

## Architect: the sweeper's re-description case, 2026-10-29

The arc-review sweeper (`spec_sync.run_arc_review`) asks the architect to re-describe a deck a
person edited by hand: `ARC_REVIEW_MESSAGE`, with `describe_only=True`. It is the one edit that must
still return a full `deck_spec`. An answer given as `operations` or `deck_changes` is silently
dropped, and the sweeper clears its marker anyway. No case measured this, so one was added to each
split before the next prompt pass. No prompt changed and no real-model run was made.

- **`redescribe_deck`** (both splits, each on its own deck). The payload is what `architect_node`
  sends on the sweeper's turn:
  - `message` is `ARC_REVIEW_MESSAGE` on both splits, the one message the splits share.
  - `conversation` is the prior exchange alone, because the sweeper saves no user message.
  - `slide_references` is `[]` (`architect_slide_payload(..., describe_only=True)`), and
    `slide_numbering` still numbers the deck.

  `expect` is `{intent: edit, full_deck_spec: true}`, scored by the re-description check (see
  Scorers). The reference is the current spec as `deck_spec`, with every position in
  `target_positions` and no operations. The `should_fail` is the answer production drops: an
  `edit` that re-describes the narrative arc as `deck_changes`, with no `deck_spec`.
- The architect now has twenty cases per split, 50 across the harness.
- **Not calibrated or measured yet.** Calibrate it on both splits
  (`--calibrate --cases redescribe_deck`) before relying on its judge verdict. (Done in the
  follow-up pass below: trusted on both splits.)

### Follow-up pass: three prompt tweaks, 2026-10-29

Three rule tweaks to the promoted `edit-ops` prompt, measured on the cases they can move and
promoted. Setup as in the edit-operations pass above (agent `system.ai.claude-opus-5-5`, judge
`databricks-claude-sonnet-5`, profile `tellr-dev`), except that cost is estimated at Opus 5.5's list
price, USD 4 / 20 per million input / output tokens, plus USD 0.05 per judge call.

- **The tweaks.** `edit-ops-b` (`3da09952`, `evals/configs/architect/edit-ops-b.md`) is `edit-ops`
  with two sentences changed:
  - EDITING's placement rules add that moves cannot form a loop (a circle of moves is refused by
    `apply_operations` with a `move_loop` problem).
  - DESIGN SYSTEMS' sentence on committing a confirmed contract now names both homes: inside
    deck_spec on a build, or in deck_changes.design_contract on an edit, as EDITING already said.

  Every other block is byte-identical to `edit-ops`, so the cases these sentences cannot move are
  covered by the edit-operations measurement above. The third tweak (the re-description rule) was
  conditional on `redescribe_deck` failing. It passed 3/3 with the sentence unchanged, so no
  `edit-ops-c` was written.
- **Calibration** (`--calibrate --cases redescribe_deck`): trusted on train, and trusted on held-out
  after one re-run (the first held-out run hit a judge parse error on the should_fail).

| Run | Config | Split | Cases | Repeats | Rows | Pass rate | Judge errors | Mean in/out tokens | ≈ USD |
|---|---|---|---|---|---|---|---|---|---|
| S1 366f7035 | edit-ops-b (3da09952) | train | 4 | 3 | 12 | 1.00 | 0 | 16.5k / 1.6k | 1.78 |
| H1 e3eaa5e9 | edit-ops-b | held-out | 4 | 1 | 4 | 1.00 (3 scored) | 1 | 14.6k / 1.2k | 0.53 |

The four cases are `confirm_design`, `move_slide`, `mixed_operations` and `redescribe_deck`.
Calibration (6 judge calls, about USD 0.30) brings the total to **about USD 2.61**, inside the
USD 5 cap.

- **Train (S1).** 12 of 12, every scorer on every row. `confirm_design` kept its intent and proposal.
  `move_slide` was `move` 6 after 3 each time, and `mixed_operations` was `delete` 2, `update` 1 and
  `replace` 7 with three slides. `redescribe_deck` was an `edit` with the full 10-slide `deck_spec`
  over positions 0..9, no `operations` and no `deck_changes`.
- **Held-out (H1).** The harness's 1.00 is over 3 judge-scored rows. The fourth row, `move_slide`'s,
  was skipped by a judge parse error (`MlflowException: Failed to parse response`), so the harness
  logged no judge verdict for it and no `pass_rate/move_slide`. Its deterministic scorers
  (`contract` and `expected_category`) passed, as on the other three rows. The pass ran only an
  aggregate-only count (4 of 4 deterministic passes) and opened no per-case held-out result; the
  follow-up review then read the row-level scorer verdicts in `mlflow.db` to name the skipped row.
  So `confirm_design`, `mixed_operations` and `redescribe_deck` are 1/1 on every scorer, and
  `move_slide` is 1/1 on the deterministic scorers only, with no judge verdict.
- **Bar met.** Each of the four cases passed at least 2/3 on train (3/3) and 1/1 on held-out by the
  deterministic scorers (for `move_slide`, by those alone), and the unchanged blocks are pinned
  byte-identical (`tests/unit/test_architect_edit_prompt.py`).
- **Shipped.** `edit-ops-b` replaces `edit-ops` as the v1 default in `src/core/skills/architect.py`
  (`3da09952e775`, previously `8f1493ef35f9`). It was promoted with
  `python -m evals.harness.promote --config architect=evals/configs/architect/edit-ops-b.yaml --run-id architect=366f7035e8b043a88bf1be1263816369`,
  and the frontend lifecycle contract was re-recorded.

## Deck style: scoring, and builder and build_reviewer cases, 2026-10-30

The architect can author a deck style (`DeckSpec.deck_style`: CSS on `dk-` classes plus a component
catalogue) that adds to the brand. The harness now scores it (see Scorers), renders slides with it,
and has cases that hand it to the builder and the build reviewer. No prompt changed and no
real-model run was made.

- **The fixture.** `evals/fixtures/deck_style_technical.json` is a `DeckStyle` dump for a technical
  deck: `dk-code` (with the `kw`, `fn`, `str` and `cm` token spans), `dk-table`, `dk-badge` with
  `dk-badge--measured` and `dk-badge--untested`, `dk-steps`, `dk-callout` and `dk-note`. Every colour,
  font and size is a Meridian token (the code font is a literal monospace stack: Meridian has no
  mono token). `sanitise_deck_style(..., design_system_active=True)` returns it as the same object
  with no notes, and a test pins that.
- **Builder** (both splits). `deck_style_code` and `deck_style_table` are positives whose payload
  carries the fixture and whose slide spec carries a `look`. The slide keeps its gold `purpose`,
  `assumes` and `hands_off`, and its brief asks for the piece. `expect.deck_style_classes` lists the
  pieces the slide must use. The reference is built from them. The `should_fail` is the same slide
  painted inline in off-palette colours, so `deck_style_use_score` and the render both fail it.
- **Build reviewer** (both splits; train slide 7, held-out slide 2). `deck_style_clean` builds a
  code listing with `dk-code`. `deck_style_inline_paint` is the same slide with that block painted
  inline instead (a `#1E293B` ground and off-palette token colours), so today's `rogue_colour`
  description catches it. Its expect is `rogue_colour` at that slide. The clean case's
  `should_fail` wrongly flags the deck style's own token colours as `rogue_colour`. The build
  reviewer prompt does not mention deck styles (ruling R10), so these cases measure that gap.
- The builder and the build_reviewer now have seven cases per split, 54 across the harness.
- **Not calibrated or measured yet.** Calibrate the four new cases on both splits before relying
  on their judge verdicts:
  `python -m evals.run_eval --agent builder --calibrate --cases deck_style_code,deck_style_table [--split heldout]`
  and the same for `--agent build_reviewer --cases deck_style_inline_paint,deck_style_clean`. Neither
  judge prompt describes `deck_style`; the judge sees it in the brief. (The builder's two cases are
  calibrated in the pass below, and the build reviewer's in "Fix reviewer: judge fixes against the
  deck style".)

## Builder and fixer: build to the deck style, 2026-10-30

The builder and fixer prompts gain a `DECK STYLE (when deck_style is present)` block (spec
`docs/superpowers/specs/2026-10-29-architect-deck-style-design.md` §3). With a deck style, the
builder builds the slide to its `look`, uses the catalogue's pieces exactly as their
`example_html` shows, keeps a bound section's frame and lays out its body as the look says, uses
token-span classes only inside their piece, and uses no class (and no `dk-` class) that the deck
style, the bound section or the design system does not define. Inline styles are for layout only,
in any deck. The fixer gets the same block, aimed at fixing toward the deck style and keeping the
look. Without a deck style the block is skipped, and every other block is byte-identical, except
that INPUT names the two optional inputs. This pass measured three builder candidates and one fixer
candidate on train, ran the builder finalist on held-out once, and promoted both.

- **Setup.** Builder agent `system.ai.claude-haiku-4-5`, fixer agent `system.ai.claude-opus-5-5`
  (manifest v1), judge `databricks-claude-sonnet-5`, profile `tellr-dev`. `prices.yaml` prices
  neither agent endpoint, so the harness logged no `est_cost_usd`. Cost is estimated from the
  logged mean tokens at list price (Haiku 4.5 USD 1 / 5, Opus 5.5 USD 4 / 20 per million input /
  output) plus USD 0.05 per judge call (an upper bound).
- **Calibration** (`--calibrate --cases deck_style_code,deck_style_table`):

  | Case | Train | Held-out |
  |---|---|---|
  | `deck_style_code` | trusted | not trusted (judge failed the reference) |
  | `deck_style_table` | trusted | not trusted (judge failed the reference) |

  Both held-out references pass the deterministic scorers (`render_measures`, with
  `deck_style_use_score`; pinned by `test_pack_builder_heldout.py` and
  `test_eval_deck_style_scorer.py`). So on held-out these two cases are decided by `contract` and
  `render_measures`, as `fill_blank_slide` is; the judge verdict is reported, not counted. The
  judge prompt still does not describe `deck_style`.
- **Baseline.** Task 7a added two cases, so the builder's `cases_digest` (`1b9e3b28`) differs from
  every recorded builder table. B0 is the then-promoted v1 prompt (`181a982b`) on the current train
  cases, the comparable baseline.
- **Candidates** (`evals/configs/builder/`), one change each:
  - `deck-style` (`d7b7e1ee`): the block above.
  - `deck-style-b` (`615ba622`): `deck-style`, plus "token values count too" and "an extra heading
    or label takes a design-system class that fits, or none". Aimed at S1's one cause.
  - `deck-style-c` (`42c6fccb`): `deck-style`, plus a last check: before returning, keep only
    layout properties in every style attribute, even a `var(--…)` value. Aimed at the same cause.
  - Fixer `deck-style` (`69eb6ea5`, `evals/configs/fixer/deck-style.yaml`): the fixer block.

S are screens, T tie-breaks, F finalist runs, D cause checks. Pass rate is the harness's, over
scored rows. Run ids are from the `architect-styling` worktree's local `mlflow.db`.

| Run | Config | Split | Cases | Repeats | Rows | Pass rate | Judge errors | Mean in/out tokens | ≈ USD |
|---|---|---|---|---|---|---|---|---|---|
| B0 fac70627 | builder v1-baseline (181a982b) | train | all 7 | 1 | 7 | 0.71 | 0 | 6.9k / 1.2k | 0.44 |
| S1 c0c9a056 | deck-style (d7b7e1ee) | train | 2 new | 3 | 6 | 0.67 | 0 | 8.7k / 0.8k | 0.38 |
| S2 79edfe83 | deck-style-b (615ba622) | train | 2 new | 3 | 6 | 0.50 | 0 | 8.7k / 0.9k | 0.38 |
| S3 633c66e8 | deck-style-c (42c6fccb) | train | 2 new | 3 | 6 | 0.67 | 0 | 8.7k / 0.9k | 0.38 |
| T1 05b01b4f | deck-style | train | `deck_style_code` | 5 | 5 | 0.20 | 0 | 8.7k / 0.8k | 0.31 |
| T2 13d59e38 | deck-style-c | train | `deck_style_code` | 5 | 5 | 0.00 | 0 | 8.7k / 0.9k | 0.32 |
| F1 74fe64e6 | deck-style | train | all 7 | 1 | 7 | 0.57 | 0 | 7.4k / 1.2k | 0.44 |
| F2 fc286840 | deck-style | held-out | all 7 | 1 | 7 | 0.71 | 0 | 7.1k / 0.7k | 0.42 |
| D3 f06f0d37 | builder v1-baseline | train | `gold_chart`, `too_much_content` | 3 | 6 | 0.50 | 0 | 6.6k / 1.6k | 0.39 |
| D4 3de9f411 | deck-style | train | `gold_chart`, `too_much_content` | 3 | 6 | 0.83 | 0 | 7.1k / 1.2k | 0.38 |
| X1 485948a7 | fixer deck-style (69eb6ea5) | train | all 5 | 1 | 5 | 0.80 | 0 | 8.8k / 0.7k | 0.49 |
| D1 cc147802 | fixer v1-baseline (83424386) | train | `source_contradiction` | 3 | 3 | 0.00 | 0 | 8.9k / 0.7k | 0.30 |
| D2 4d063603 | fixer deck-style | train | `source_contradiction` | 3 | 3 | 0.00 | 0 | 9.4k / 0.7k | 0.31 |

Calibration (8 judge calls, about USD 0.40) brings the total to **about USD 5.34**, inside the
USD 10 cap. Held-out is an aggregate only (F2), plus the deterministic verdicts of the two
deck-style cases, which the bar needs.

What it showed:

- **One cause, on `deck_style_code`.** Every failing row of the three candidates (and B0's row)
  fails `deck_style_use_score` alone: the builder adds a heading or label over each column and
  paints it inline with token values (`font-size: var(--fs-subtitle); color:
  var(--brand-core-ink)`). The judge passed every one of those rows. Neither targeted change moved
  it: `deck-style` 1/3 (S1), 2/9 pooled with T1 and F1; `deck-style-b` 0/3; `deck-style-c` 1/3, 1/8
  pooled with T2. `deck_style_table` passed every row of every candidate (3/3 in each screen, 1/1
  in F1).
- **Finalist: `deck-style`**, the best of three on the screen and the tie-break. Held-out (F2):
  0.71 (5 of 7), 0 judge errors; both deck-style cases 1/1 by the deterministic scorers. The
  recorded v1 held-out builder rate is 0.40 (2026-10-08, another digest, model and prompt), so F2
  is not below it. No same-digest v1 held-out run was made.
- **Existing cases** (F1 against B0, each ×1; D3 and D4 ×3): `chart_no_data` 0/1 → 1/1,
  `gold_bullets`, `gold_stats` and `deck_style_table` 1/1 → 1/1, `gold_chart` 1/1 → 0/1 (D: v1 1/3,
  `deck-style` 3/3), `too_much_content` 1/1 → 0/1 (D: 2/3 each). The F1 drops are known v1 causes:
  inline paint on an added heading with a hard-coded chart hex (judge), and overflow on the
  overloaded brief. Neither case carries a deck style, so the block does not apply to them.
- **Fixer** (X1): `brief_not_delivered`, `contrast_failure`, `overflow` and `rogue_colour` 1/1.
  `source_contradiction` 0/1, and 0/3 for both v1 (D1) and the candidate (D2): the fixer corrects
  the figure and returns `scripts: ""`, which drops the chart's init (`chart-init-timeout`). The
  fixer's OUTPUT line says "updated Chart.js init code if charts changed; otherwise empty string",
  and production applies the empty scripts (`fixed_scripts`, `src/services/graph/nodes.py`). This is
  a v1 defect, unchanged by this pass. The recorded 1.00 is from 2026-10-06 (another model and
  prompt).
- **Acceptance bar** (plan Task 9). **Missed on one point.**
  1. `deck_style_code` at least 2/3 on train: **missed** (1/3 in S1; 2/9 pooled). 1/1 on held-out:
     met.
  2. `deck_style_table` at least 2/3 on train and 1/1 on held-out: met (3/3, 1/1).
  3. Every existing builder and fixer case at least its recorded rate minus one row: met (above).
  After three builder candidates the best one was promoted, as the brief directs, and the gap is
  recorded here: the Haiku builder still paints an added heading inline with token values.
- **Overrides of `optimise-agent-prompt`**, delegated by the controller for this change:
  screened ×3 on the two new cases, with the finalist on all train ×1 and held-out ×1 (the skill
  says ×5 and ×3); the tie-break and cause-check runs (T, D) are train only; the deterministic
  verdicts of the two held-out deck-style cases were read to apply the bar; and the pass promoted,
  edited `INSTRUCTIONS` and committed.
- **Shipped.** `deck-style` is the builder's v1 prompt in `src/core/skills/builder.py`
  (`d7b7e1ee35c9`, previously `181a982b59e1`), and the fixer's `deck-style` is the fixer's
  (`69eb6ea52400`, previously `8342438644d4`). Promoted with
  `python -m evals.harness.promote --config builder=evals/configs/builder/deck-style.yaml --run-id builder=74fe64e68bb247259c235d43b9c029c8 --config fixer=evals/configs/fixer/deck-style.yaml --run-id fixer=485948a7ff6940ada5fcbc8d650eb3f6`,
  and the frontend lifecycle contract was re-recorded. The builder and fixer rows in the earlier
  tables describe previous prompts.
- **Still open.**
  - `deck_style_code`'s inline-painted headings (above).
  - The fixer drops a chart's script on a text-only fix (`source_contradiction`).
  - The builder judge prompt does not describe `deck_style`, and it fails both held-out references.

## Fix reviewer: judge fixes against the deck style; build reviewer gap, 2026-10-30

The fix reviewer's prompt gains a `DECK STYLE (when the payload carries deck_style)` block, placed
after YOUR JOB. With a deck style, the colours that `deck_style.css` gives its pieces are part of the
contract, not `rogue_colour`. A fix that paints colour, background or font-size inline, or that
restyles a piece the deck style provides, counts against the fix and is reported as `rogue_colour`.
The cascade is judged with `deck_style.css` applied after `section_css`. Without a deck style the
block is skipped, and the rest of the prompt is byte-identical. No criterion was added
(`src/domain/finding.py` is unchanged). This pass measured that one candidate on the fix_reviewer
train pack and promoted it. It also measured the **unchanged** build reviewer on its two deck-style
cases.

- **Setup.** Fix reviewer agent `system.ai.claude-haiku-4-5`, build reviewer agent
  `system.ai.claude-opus-5-5` (manifest v1), judge `databricks-claude-sonnet-5`, profile
  `tellr-dev`. `prices.yaml` prices neither agent endpoint, so cost is estimated as in the builder
  pass above: list price (Haiku 4.5 USD 1 / 5, Opus 5.5 USD 4 / 20 per million input / output
  tokens), plus USD 0.05 per judge call (an upper bound).
- **Calibration.** fix_reviewer train, all 5 cases: trusted. build_reviewer
  `deck_style_inline_paint` and `deck_style_clean`: trusted on train and on held-out. The held-out
  `deck_style_inline_paint` needed one re-run after a judge error on the reference
  (`KeyError: 'result'`); it was not a misclassification.
- **Baseline.** No earlier fix_reviewer run is comparable. The last recorded rate, train 1.00
  (8f85585e, run 2404f31f), was on `databricks-claude-haiku-5-5`, and the fix_reviewer payloads have
  changed since then (5653f3ec). R0 is the promoted v1 prompt (`ff14c8e8`) on the current train cases
  (`cases_digest` `e320f95d`).
- **Candidate:** `evals/configs/fix_reviewer/deck-style.{md,yaml}` (`1050287f`), the block above.

R are fix_reviewer runs and G are the build-reviewer gap runs. Run ids are from the
`architect-styling` worktree's local `mlflow.db`.

| Run | Config | Split | Cases | Repeats | Rows | Pass rate | Judge errors | Mean in/out tokens | ≈ USD |
|---|---|---|---|---|---|---|---|---|---|
| R0 d7941c58 | fix_reviewer v1-baseline (ff14c8e8) | train | all 5 | 1 | 5 | 0.40 | 0 | 6.8k / 0.4k | 0.29 |
| R1 53fb2e4c | fix_reviewer deck-style (1050287f) | train | all 5 | 1 | 5 | 0.60 | 0 | 7.0k / 0.4k | 0.30 |
| G1 a88f0049 | build_reviewer v1-baseline (0a8f6a7c) | train | 2 deck-style | 3 | 6 | 1.00 | 0 | 10.0k / 1.6k | 0.73 |
| G2 c4be1d01 | build_reviewer v1-baseline | held-out | 2 deck-style | 1 | 2 | 1.00 (1 row scored) | 1 | 9.4k / 1.2k | 0.22 |
| G3 108deeb2 | build_reviewer v1-baseline | held-out | 2 deck-style | 1 | 2 | 1.00 | 0 | 9.4k / 1.2k | 0.22 |

G3 is G2 re-run because of G2's judge error. Calibration took 20 judge calls (about USD 1.00), which
brings the total to **about USD 2.76**, inside the USD 6 cap. Held-out is reported as aggregates
only.

What it showed:

- **Fix reviewer, per case (R0 → R1).** `good_fix_accept` 1 → 1, `good_contrast_fix_accept` 1 → 1,
  `restyle_reject` 0 → 1, `fault_left_reject` 0 → 0, `content_broken_reject` 0 → 0. No case dropped,
  so the bar (no existing case drops by more than one row) is met. No fix_reviewer case carries a
  deck style, so the block does not apply to any of them. The `restyle_reject` gain is a single row
  and is treated as noise.
- **One cause, in v1, on both runs.** Each failing row returns verdict `fixed` with no findings for
  a bad fix: the overflow is still there (`fault_left_reject`) or the claim was reversed
  (`content_broken_reject`). The judge and `expected_category` both fail those rows. The Haiku 4.5
  fix reviewer accepts bad fixes. This pass did not change that, and it is still open.
- **Shipped.** `deck-style` is the fix reviewer's v1 prompt in `src/core/skills/fix_reviewer.py`
  (`1050287f9dfc`, previously `ff14c8e8b162`). It was promoted with
  `python -m evals.harness.promote --config fix_reviewer=evals/configs/fix_reviewer/deck-style.yaml --run-id fix_reviewer=53fb2e4c149c45e3b4b276f68466f7ef`,
  and the frontend lifecycle contract was re-recorded.
- **Build reviewer, unchanged (G1 to G3).** `deck_style_inline_paint` passed 3/3 on train and
  `deck_style_clean` passed 3/3. Held-out was 2 of 2 rows (aggregate). Today's prompt reports the
  inline-painted code block as `rogue_colour`, because the case paints it in off-palette hexes
  (`#1E293B`, `#F8FAFC`, ...) and today's `rogue_colour` description catches those. It also does not
  flag the deck style's token colours on the clean slide. **So these two cases show no gap.** They do
  not exercise what the rule would add: inline paint in on-palette token values, an on-palette
  restyle of a provided piece, and the order of `deck_style.css` after `section_css`. A case built
  for any of those is needed to measure the gap. The cases were not changed.
- **The build-reviewer deck-style rule is not shipped** (Ruling R10, correction C27 option c). The
  build reviewer is a `LegacyV1PromptTransition` source, so `promote` refuses to change its prompt.
  Editing its v1 composite (`INSTRUCTIONS`) would make `upgrade_definition_to_v2` refuse the
  persisted v1 build-reviewer definitions on released 0.5.x installs ("Legacy protected prompt
  content was edited"). Editing its authored v2 target moves `_V2_DIGEST`
  (`src/services/prompt_assembler.py` raises at import). The two measured cases do not exercise the
  gap the rule would close (on-palette token paint, an on-palette restyle of a provided piece, the
  cascade order), so their rates neither support nor argue against the change. Shipping it needs an
  **owner decision on a migration**: either a
  transition that accepts both the 0.5.x composite and the new one, or a protected conditional stage
  like `DECK_BRIEF_REVIEW`.
- **Override of `optimise-agent-prompt`, delegated by the controller:** one candidate at ×1 on train
  (the skill says ×5), no held-out fix_reviewer run, and the pass promoted, edited `INSTRUCTIONS` and
  committed.

## Architect: deck-style cases, 2026-10-30

Two architect cases were added on each split. One is a technical build that must author a deck
style. The other is a restyle of the deck's code blocks. No prompt changed and no real-model run
was made. Both are generated by `mutations.py` and `heldout.py`, and every existing case regenerates
byte-identical. `build_request` is unchanged (Ruling R9): its reference is the gold deck, with no
deck style.

- **`build_technical_deck`** (positive, `expect: {intent: build, deck_style: true}`). It is a fresh
  one-turn build, and its payload is `build_request`'s apart from the message. Each message is a
  generic public topic and gives its own figures, so a build is right, not `ask_data`. The two
  splits ask for different pieces (Ruling R29), so a prompt that hard-codes one split's pieces
  does not pass the other for free.
  - Train covers streaming Postgres changes into a lakehouse with logical replication. It asks for
    code, a comparison table and measured/untested badges. Its reference style is the technical
    fixture without `dk-callout`: the template has its own `.callout`, and a deck style reuses a
    template piece rather than restating it (spec §2). The looks use `dk-code`, `dk-table` and
    `dk-badge`, and put each takeaway in "the template's callout".
  - Held-out covers rolling out HTTP/3 across a public website. It asks for a dated timeline and
    a KPI band, and no code. Its reference style is its own: `dk-timeline`, a `dk-kpi-band` for
    four figures (one more than the template's three stat cards hold) and `dk-note`, in Meridian
    tokens. It passes the sanitiser unchanged.
  - Every slide has a `look` that names only the style's pieces, and no style defines a `dk-` twin
    of a template class.
  - The `should_fail` is the same deck with no deck style and no looks. So the deck style is the
    only trap, and `_deck_style_score` fails it ("Deck style: deck_spec.deck_style is missing").
- **`restyle_deck`** (mutation, `expect: {intent: edit, positions: [], deck_style_keeps:
  [dk-code, kw, fn, str, cm]}`). The keeps list is the code block and the token-span classes the
  fixture defines in it, since production's stranding check counts both. The deck is the split's
  gold deck as a deck-style build leaves it: the fixture style and a look on every slide, some of
  them naming `dk-code`. The train message is "Make all the code blocks dark navy with light
  text"; held-out's asks for a dark background.
  - The reference is `deck_changes.deck_style` alone, which rebuilds nothing. It is the fixture
    with `.dk-code` on `--brand-core-ink` and light token spans, all at AA contrast or better.
    Every other rule is unchanged. Meridian has no navy, so the train answer says it uses the
    darkest ink token instead; the held-out answer says only "dark background", as asked.
  - The `should_fail` is the same restyle with `dk-code` renamed to `dk-code-dark`. Every code
    slide would lose its style, so the keeps check fails it and names `dk-code`.
- The architect now has twenty-two cases per split, 56 across the harness.
- **Not calibrated or measured yet.** The architect judge prompt does not describe `deck_style`
  or `look`. Calibrate both cases on both splits before relying on their judge verdicts:
  `python -m evals.run_eval --agent architect --calibrate --cases build_technical_deck,restyle_deck [--split heldout]`.
  (Done in the pass below: the judge passes both references and cannot separate either
  should_fail, so both cases are decided by their deterministic scorers.)

## Architect: deck style and per-slide look, 2026-10-30

The architect prompt now writes the deck style and a look for every slide (spec
`docs/superpowers/specs/2026-10-29-architect-deck-style-design.md` §2). On a build it writes
`deck_spec.deck_style` once, from what the planned slides need and the payload's
`deck_style_context`, and a one-or-two-sentence `look` for each slide. It binds a template section
where its shape fits, binds one for its frame only when the body differs, and otherwise leaves the
slide unbound. A restyle goes through `deck_changes.deck_style`. The prompt also states the
sanitiser's rules, so the style it writes is not stripped. This pass calibrated the judge on the
three cases the change can move, re-ran the promoted prompt as the baseline, screened two
candidates, ran the finalist on all train cases and on held-out, and promoted it. The builder's
no-design-system ground line changed with it (Ruling R26) and was measured and promoted too.

- **Setup.** Architect agent `system.ai.claude-opus-5-5` (manifest v1), judge
  `databricks-claude-sonnet-5`, profile `tellr-dev`. `prices.yaml` has no entry for the agent's
  endpoint, so the harness logged no `est_cost_usd`. Cost is estimated as in the follow-up pass
  above: Opus 5.5 list price, USD 4 / 20 per million input / output tokens, plus USD 0.05 per
  judge call. The judge figure is an upper bound: this pass's judge payloads, sized from the
  logged answers and the case files, come to about USD 0.025 to 0.03 a call.
- **Calibration** (`--calibrate --cases build_technical_deck,restyle_deck,build_request`):

  | Case | Train | Held-out |
  |---|---|---|
  | `build_request` | trusted | trusted |
  | `build_technical_deck` | not trusted (judge passed the should_fail) | not trusted (judge passed the should_fail) |
  | `restyle_deck` | not trusted (judge passed the should_fail) | not trusted (judge passed the should_fail) |

  The judge passes both new references, so `judge_prompt.md` was not changed (Ruling R30). It
  cannot see what the two should_fails get wrong: a deck with no deck style or looks, and a
  restyle that renames `dk-code`. So, as for `fill_blank_slide`, these two cases are decided by
  `contract` and `expected_category` (`_deck_style_score` for the build, the operations check
  with `deck_style_keeps` for the restyle). Their judge verdicts are reported, not counted. In
  this pass the judge failed only the one row that had no output, so the rule changed no outcome.
- **Baseline** (Ruling R11, correction C31). Task 7b's cases changed the architect's
  `cases_digest` (`ad824844`), so no recorded architect table is comparable. B0 is the
  then-promoted prompt (`edit-ops-b`, content hash `42db22a8`) on the current train cases. Its
  build rows are also the token baseline.
- **Candidates** (`evals/configs/architect/`), one change each:
  - `deck-style` (`d0a2d0ec`): `edit-ops-b` plus the rules above. DECKSPEC CONSTRUCTION gains a
    `deck_style:` line after `slides:`, and SLIDESPEC FIELDS a `look:` line. EDITING's
    deck_changes field list names `deck_style`. VISUAL / TEMPLATE BINDING gains the
    bind-where-it-fits sentences. A new `DECK STYLE (deck_style and look):` block before SLIDE
    NUMBERS holds the build, sanitiser, look and edit rules. Every other block is byte-identical.
  - `deck-style-b` (`3527e7bc`): `deck-style` with its size sentence extended, aimed at S1's one
    cause, the output tokens. It adds that most decks need 2,000 to 3,000 characters and four to
    eight pieces. It also says the CSS goes straight into `deck_style`, with the pieces decided in
    a few words of reasoning and no drafting or checking of the CSS or the looks first.
  - No third candidate was written. The finalist runs needed the rest of the USD 22 cap.

B is the baseline, S are screens, F the finalist's train run, H its held-out run, and X the
builder's. Pass rate is the harness's, over scored rows. Run ids are from the
`architect-styling` worktree's local `mlflow.db`.

| Run | Config | Split | Cases | Repeats | Rows | Pass rate | Judge errors | Mean in/out tokens | ≈ USD |
|---|---|---|---|---|---|---|---|---|---|
| B0 311f42c1 | architect v1-baseline (42db22a8) | train | all 22 | 2 | 44 | 0.91 | 0 | 17.7k / 1.5k | 6.63 |
| S1 9d797563 | deck-style (d0a2d0ec) | train | 3 | 3 | 9 | 0.89 | 0 | 17.8k / 7.7k | 2.43 |
| S2 9ebeed72 | deck-style-b (3527e7bc) | train | 2 builds | 3 | 6 | 1.00 | 0 | 15.8k / 8.8k | 1.74 |
| F1 f6766e50 | deck-style-b | train | all 22 | 2 | 44 | 1.00 | 0 | 19.4k / 1.9k | 7.29 |
| H1 084c591b | deck-style-b | held-out | all 22 | 1 | 22 | 1.00 | 0 | 17.7k / 1.5k | 3.33 |
| X1 a3e5c876 | builder deck-style-ground (d6db84b8) | train | all 7 | 1 | 7 | 0.86 | 0 | 7.5k / 1.2k | 0.44 |

S1's three cases are `build_technical_deck`, `restyle_deck` and `build_request`; S2's are the two
builds. Calibration took 12 judge calls (about USD 0.60). That brings the architect's total to
**about USD 22.0** with the judge at its USD 0.05 upper bound, at the USD 22 cap. With the judge
at the USD 0.03 a call its payloads measure, the total is about USD 19.3. The builder's run
(X1) took USD 0.44 of its remaining USD 4.66. Held-out is reported as an aggregate only (H1).

What it showed:

- **Baseline (B0).** All 20 existing cases passed 2/2. Both new cases failed 0/2, each on its
  deterministic scorer. Without the new rules, the build already filled `deck_style` (the field
  is in the schema), but with unprefixed classes (`.code-block`, `.badge`, `.cmp-table`), so
  the sanitiser drops the whole style. The restyle used `deck_changes.deck_style`, but it also
  rebuilt the two code slides with `update` operations, and it named raw hexes in its message.
- **Screen of `deck-style` (S1).** `build_request` passed 3/3 and `restyle_deck` 3/3, the
  restyle as `deck_changes.deck_style` alone: every token from the brand, no operations, no slide
  rebuilt. `build_technical_deck` passed 2/3. Its third row was `incomplete`: the model returned a
  `deck_spec` with no `slides` and `resolved_data.gaps` misplaced (a schema failure, not the
  sanitiser's). The real cost was output tokens: the build rows averaged 10.2k against B0's 5.7k.
  That is mostly reasoning: `build_request`'s answer grew from about 11k to 19k characters of
  JSON (about 2k tokens), while its output grew by about 7k tokens.
- **Screen of `deck-style-b` (S2).** Both builds passed 3/3, and the mean build output fell to
  8.8k. The model still wrote about 3,300 characters of CSS, not the 2,000 to 3,000 the
  sentence suggests.
- **Finalist, train (F1).** All 22 cases passed 2/2, 44 of 44 on every scorer. Every existing
  edit case was still answered with operations and passed the operations check.
  `redescribe_deck` returned the full `deck_spec` with no operations. `restyle_deck` was
  `deck_changes.deck_style` alone, about 2,300 characters, keeping `dk-code` and its token spans,
  with no operations. Each build wrote about 3,000 to 4,000 characters of CSS, six or seven
  components, and a look on all 16 or 17 slides.
- **Finalist, held-out (H1).** 1.00 (22 of 22), with 0 judge errors and 0 infra errors. So every
  held-out case passed 1/1 on every scorer, the three new ones included.
- **Acceptance bar** (plan Task 8, controller overrides). **Missed on one point.**
  1. Every existing case passed at least its B0 rate minus one row. Met: all 20 passed 2/2
     (F1), and all 20 passed 2/2 in B0.
  2. `build_technical_deck`, `restyle_deck` and `build_request` each passed at least 2/3 on
     train and 1/1 on held-out. Met. On train, `deck-style-b` scored 3/3 on both builds (S2).
     `restyle_deck` scored 3/3 in S1, whose edit rules are byte-identical to `deck-style-b`'s,
     and 2/2 in F1. On held-out, all three passed 1/1 (H1 1.00).
  3. Mean output tokens on the build cases rise by at most 2,500 over B0's 5,702. **Missed:**
     8,849 in S2 (+3,147), 9,276 in F1 (+3,574), and 9,020 over all ten `deck-style-b` build rows
     (+3,318). `deck-style` was +4,490 (S1).

  The bar is a proxy for the +30 s time-to-first-slide limit. The architect's mean call time on
  the build rows rose from 51.2 s (B0) to 76.4 s (S2) and 77.6 s (F1), about +26 s, though that
  is the call alone, not a measured time to first slide. After two candidates the better one was
  promoted, as the brief directs, and the gap is recorded here.
- **Builder ground line (Ruling R26).** Without a design system, the builder's DECK STYLE block
  sent an unbound slide to "the ground NO BOUND SECTION gives it". That ground is an inline
  colour and background, which the same block bans when a deck style is present. So the line now
  ends "; when design_system_active is false, that ground is the deck style's ground piece that
  the look names (such as dk-slide): put its class on the slide's root element". The architect
  prompt makes a no-design-system deck style define that piece and each look name it.
  `deck-style-ground` (`d6db84b8`, `evals/configs/builder/`) is the promoted builder with that
  one line changed, and the model is unchanged (Task 9b will switch it). X1 passed 6 of 7 against
  F1 74fe64e6's 4 of 7, the Task 9 measurement of the then-promoted builder: `gold_chart` and
  `too_much_content` went 0/1 → 1/1, and the rest stayed level. `deck_style_code` 0/1 is the
  known cause, the Haiku builder painting an added heading inline with token values. No builder
  case has no design system and a deck style, so X1 shows that the line breaks nothing. It does
  not show that the line works.
- **Overrides of `optimise-agent-prompt`**, delegated by the controller for this change:
  - The screens ran ×3 on the cases the change targets, and the finalist ran on all train ×2 and
    held-out ×1. The skill says ×5 and ×3.
  - `deck-style-b`'s screen covered only the two builds, since its one change is to the build
    rules.
  - The builder ran once on train, with no held-out.
  - This pass promoted, edited `INSTRUCTIONS` and committed.
- **Shipped.** `deck-style-b` is the architect's v1 prompt in `src/core/skills/architect.py`
  (`3527e7bcafc4`, previously `42db22a8e622`). `deck-style-ground` is the builder's v1 prompt in
  `src/core/skills/builder.py` (`d6db84b8a570`, previously `d7b7e1ee35c9`). Promoted with
  `python -m evals.harness.promote --config architect=evals/configs/architect/deck-style-b.yaml --run-id architect=f6766e5053fe4ea9a2100c489870c928 --config builder=evals/configs/builder/deck-style-ground.yaml --run-id builder=a3e5c876e519419190242bd936672e3c`.
  The pins `promote` does not touch were updated by hand (C25), and the frontend lifecycle
  contract was re-recorded. The architect and builder rows in the earlier tables describe
  previous prompts.
- **Still open.**
  - The output-token bar, above. A build now reasons about twice as long as before. The CSS
    itself is about 1k tokens.
  - The architect judge prompt does not describe `deck_style` or `look`, so the judge cannot
    separate either new case.
  - No architect case builds without a design system, so neither the `--dk-` palette nor the
    ground piece is measured. No builder case renders a no-design-system deck style either.
  - S1's one `incomplete` build answer (a `deck_spec` with no `slides`) did not recur in the
    finalist's ten build rows.
