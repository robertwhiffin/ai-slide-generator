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

Agent endpoint `databricks-claude-opus-4-6`, judge `databricks-claude-sonnet-5`, 5 cases x 3
repeats per agent, 0 infra errors. Cost is the estimate for the whole 15-row sweep.

| Agent | Pass rate | Est. cost (USD) | Mean latency (s) | p95 latency (s) | Judge errors |
|---|---|---|---|---|---|
| architect | 1.00 | 2.59 | 16.2 | 41.8 | 0 |
| fixer | 1.00 | 2.12 | 11.6 | 19.0 | 0 |
| deck_reviewer | 0.69 | 3.13 | 22.2 | 26.2 | 2 |
| builder | 0.67 | 3.51 | 24.4 | 34.3 | 0 |
| build_reviewer | 0.40 | 2.61 | 20.4 | 25.1 | 0 |
| data_analyst | 0.27 | 0.82 | 11.3 | 14.2 | 0 |
| fix_reviewer | 0.00 | 2.37 | 15.6 | 18.6 | 0 |
| **Total** | | **17.15** | | | |

Causes, from the stored failing rows:

- **fix_reviewer (0.00).** Two causes. First, 9 of 15 runs are `incomplete`: the model invents
  criterion names such as `brand-color` and `text-contrast`, which the output schema rejects. This
  is a real agent failure. Second, on the accept cases the agent reports the finding it was asked to
  verify with `status: fixed`, and the `expected_category` scorer and the judge both count that as an
  "unplanted objective" finding. This is probably a case-expectation problem rather than an agent
  failure.
- **build_reviewer (0.40).** The agent applies the injected "SLIDE FRAME CONSTRAINTS" (at least 88px
  side clearance), but the Meridian gold slides use 64px padding. It therefore reports `overflow` on
  every slide, including clean ones. This is a fixture/prompt inconsistency rather than agent
  error. The planted faults were otherwise found.
- **data_analyst (0.27).** The agent claims `missing_data` with `tried_tools` listing Genie and the
  vector index when no tools are bound, and on `figures_inline` and `two_sources` it does not pass
  through figures the request already gives. The judge agrees these are wrong. The missing tools are
  a harness scope limit, not something to score the agent on.
- **builder (0.67).** The agent fabricates a chart with invented figures when the brief has no data
  (`chart_no_data`, `gold_bullets`). This is a real failure.
- **deck_reviewer (0.69).** The agent flags cross-slide repetition on the clean deck, which does
  repeat the 98% and file-size figures. One `out_of_order` repeat missed the `arc_gap`. Two
  `missing_conclusion` rows were skipped with `judge_error: KeyError: 'result'`, a judge-side
  failure.
- **architect and fixer** pass every case.

Treat the fix_reviewer, build_reviewer and data_analyst numbers as unreliable until the case and
fixture issues above are resolved.
