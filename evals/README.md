# Agent-configuration eval harness

Scores Tellr agent configurations (prompt and model settings) against a fixed pack of cases, so
candidate configurations can be compared on evidence before one is promoted into Graph Version 1.
Real-model runs; results are logged to MLflow.

## What it does

- **Configs** (`evals/configs/`). A config is a named variant of one agent's v1 definition.
  `v1-baseline` is the frozen manifest unchanged. YAML configs override the prompt and/or model
  settings. Each config carries a `content_hash`, logged with every run.
- **Cases** (`evals/packs/<agent>/cases/<case_id>/`). Five per agent, 35 in total across the seven
  roles (`architect`, `data_analyst`, `builder`, `build_reviewer`, `fixer`, `fix_reviewer`,
  `deck_reviewer`). Each case holds `case.yaml` (`kind` positive or mutation, `fault`, `expect`,
  `design_system_active`), `payload.json` (the agent input), `reference.json` (a known-good output)
  and `calibration.json` (a `should_fail` output).
- **Scorers** (`evals/harness/scorers.py`, `mlflow_run.py`). Every row is scored by:
  - `contract`: the output validated against the agent's schema. An `incomplete` run, such as a model
    inventing a criterion name outside the schema, fails here.
    Its rationale gives the run status and the reason, including the schema validation message (the
    invalid field and value), truncated to 2000 characters.
  - `expected_category`, for the architect, data_analyst and the three reviewers: deterministic
    match on intent/outcome, or on expected findings (criterion, position). Any objective criterion
    not listed in `expect.criteria` fails the row. A fix_reviewer also checks `verdict`.
  - `render_measures`, for the builder and fixer: the slide is rendered in a browser (Meridian section
    CSS). It must have zero overflow, contrast of at least 4.5, no off-palette colours, no console
    errors and no `<style>` tag.
  - `judge`: an LLM judge (`mlflow.genai.make_judge`) using the pack's `judge_prompt.md`. It compares
    the candidate with the reference and the brief and returns pass or fail.
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
| `--cases` | all | Comma-separated case ids, for example `gold_chart,overflow`. |
| `--judge-endpoint` | `databricks-claude-sonnet-5` | Serving endpoint used as the judge. |
| `--split` | `train` | `train` or `heldout`. Selects the case set; see Held-out set below. Also applies to `--calibrate`. |
| `--calibrate` | off | Calibrate the judge instead of sweeping (see below). |
| `--no-render` | off | Skip rendering for the builder and fixer, which drops `render_measures`. |
| `--profile` | `tellr-dev` | Databricks CLI profile every live call uses. It overrides `.env` and `DATABRICKS_HOST`. `''` keeps the ambient environment. |

The agent's endpoint is probed before each sweep; an unreachable endpoint aborts.

The harness runs each agent through `AgentRuntime.run_candidate` **without data tools bound**. The
data_analyst prompt mentions Genie and a vector index, but neither is available in the harness.

## Held-out set

Each agent has a second, separate set of five cases (35 in total) in `evals/packs/<agent>/cases_heldout/`,
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

Calibration proves the judge can discriminate on these cases. It does not prove the deterministic
scorers' expectations are reasonable for the live agent (see the baseline notes).

## Promotion

`evals.harness.promote` is a library module with no `__main__` entry, so running it with `python -m`
only imports it. Call it from Python:

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
