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
| `--calibrate` | off | Calibrate the judge instead of sweeping (see below). |
| `--no-render` | off | Skip rendering for the builder and fixer, which drops `render_measures`. |
| `--profile` | `tellr-dev` | Databricks CLI profile every live call uses. It overrides `.env` and `DATABRICKS_HOST`. `''` keeps the ambient environment. |

The agent's endpoint is probed before each sweep; an unreachable endpoint aborts.

The harness runs each agent through `AgentRuntime.run_candidate` **without data tools bound**. The
data_analyst prompt mentions Genie and a vector index, but neither is available in the harness.

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

`git_sha` 904b4153d10098e5bb1a3b5b137ab57b5d447151. Agent endpoint `databricks-claude-opus-4-6`,
judge `databricks-claude-sonnet-5`, 3 repeats, 5 cases per agent (15 rows each), 35 of 35 cases
trusted at calibration (one `fix_reviewer` case needed a re-run after a malformed judge response).
Total estimated cost **USD 16.98**. 0 infra errors in every agent. Each run carries `cases_digest`
and `git_sha` tags, and the judge rationale is stored on each row.

| Agent | Pass rate | Infra errors | Judge errors | Mean latency (s) | Est. cost (USD) |
|---|---|---|---|---|---|
| fixer | 1.00 | 0 | 0 | 13.7 | 2.27 |
| deck_reviewer | 0.93 | 0 | 0 | 21.6 | 3.08 |
| build_reviewer | 0.79 | 0 | 1 | 21.7 | 2.62 |
| architect | 0.71 | 0 | 1 | 13.9 | 2.36 |
| data_analyst | 0.40 | 0 | 0 | 10.4 | 0.78 |
| builder | 0.27 | 0 | 0 | 24.7 | 3.54 |
| fix_reviewer | 0.07 | 0 | 0 | 14.8 | 2.33 |
| **Total** | | | | | **16.98** |

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
- **builder/gold_bullets (0/3), gold_chart (1/3), too_much_content (1/3), gold_stats (2/3), AGENT.**
  The slide intrudes into the 88px/56px safe area (4 to 131px past it), overflows, or has contrast
  below 4.5 (4.13 on `gold_stats`). `render_measures`: "Safe area intrusion: 4.0px past the 88px/56px
  safe area". Judge: "safe_area_px is 4.0 (above 0), which per the hard-evidence rules is an
  automatic fail".
- **builder/chart_no_data (0/3), AGENT.** The agent invents a chart with specific scores when
  `resolved_data.figures` is empty. Judge: "The candidate invents a specific device-by-device
  fidelity chart (with precise fabricated scores ...) despite resolved_data.figures being empty".
- **build_reviewer/source_contradiction (0/3), HARNESS.** The reviewer finds the planted 64% vs 98%
  contradiction (judge passes it), but the fixture's chart script also sets a y-axis colour of
  `#6B7280`, which is not a brand token. The reviewer reports `rogue_colour` and the scorer fails it:
  "Unplanted objective criteria found: {'rogue_colour'}". The finding is real; the fixture carries an
  unplanted fault.
- **fix_reviewer/restyle_reject, content_broken_reject (0/3 each), fault_left_reject (1/3),
  AGENT.** The reviewer invents criterion names and the output schema rejects the reply, so
  `structured` is null. Reproduced once: "Unknown criterion 'brand-color'. Valid criteria: ['arc_gap',
  ...]". Judge: "no candidate output to judge".
- **fix_reviewer/good_fix_accept, good_contrast_fix_accept (0/3 each), HARNESS.** The reviewer
  accepts the fix (verdict `fixed`) and records the original finding with `status: fixed`. The
  `expected_category` scorer ignores status: "Unplanted objective criteria found: {'overflow'}". The
  judge passes `good_fix_accept` ("its status is 'fixed' (not an open objective issue)") but fails
  `good_contrast_fix_accept` for the same shape ("includes an objective finding (status 'fixed' but
  objective: true)"), so the judge prompt is also inconsistent here.
- **deck_reviewer/out_of_order (2/3), AGENT (variance).** One repeat did not place the `arc_gap`
  finding where the case expects it: "Missing expected findings: {('arc_gap', -1)}".

Earlier runs in the `tellr-agent-eval` experiment are tagged `superseded`: they predate the Meridian
frame-rule fix (88px/72px padding, footer at 56px), the safe-area check in `render_measures`, the
`slide_spec`/`resolved_data` judge inputs, the required architect edit `deck_spec`, the fixer's
`resolved_data` input and its prompt change, and stored judge rationales.
