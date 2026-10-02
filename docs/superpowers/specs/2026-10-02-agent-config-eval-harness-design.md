# Agent Configuration Eval Harness — Design

**Date:** 2026-10-02
**Status:** Approved in brainstorming; awaiting written-spec review
**Scope:** All seven model-driven LangGraph roles

## 1. Purpose

Give an easy, objective way to compare agent configurations for the LangGraph
version of Tellr, and use the results to choose the definitions frozen as
**Graph Version 1** for its release.

- A **configuration** is one Agent Definition: prompt text, model endpoint,
  sampling (`temperature`, `top_p`, `max_tokens`), `schema_overlay` and
  `assembly_rules` — the `DefinitionContentColumns` shape. Comparisons vary the
  **prompt and the model** (quality against cost and latency).
- Each agent is evaluated **in isolation**. Whole-graph combinations are out of
  scope.
- Agents run through the **same code as production**: `AgentRuntime`, prompt
  assembly, schema composition and model adapter.
- The front end is **local**: the MLflow UI.
- The harness is **offline**. It does not change the in-app test workbench, and
  its results never write a workbench verdict.

### Success criteria

1. One command runs a configuration against an agent's cases and logs one
   comparable MLflow run.
2. Two configurations for the same agent can be compared side by side in the
   local MLflow UI on pass rate, spread across repeats, latency, tokens and
   estimated cost.
3. A full sweep (35 cases, N=3) of one configuration completes in minutes, not
   hours, because all calls run concurrently within a worker cap.
4. The judge is calibrated: on every pack it passes the reference and fails the
   planted fault, or the run is flagged as untrusted.
5. Chosen configurations can be promoted into `agent_definition_manifest_v1.py`
   mechanically, with pinned hashes updated, as a reviewable diff.

## 2. Key facts this design depends on

- `AgentRuntime.run_candidate(agent_key, candidate_content, candidate_hash,
  payload, assembly_context, observation=...)`
  (`src/services/agent_runtime.py:633`) runs a `DefinitionContent` with no
  database and no release, through the same `_run_resolved` path production
  uses. Its docstring restricts callers to the #267 test workbench (spec §7.1);
  this harness is a second sanctioned caller and that docstring and §7.1 are
  amended accordingly.
- The runtime binds **no tools** to any role (`src/services/graph/nodes.py:1869`),
  so every case is pure input → structured output.
- Output schemas are `OUTPUT_SCHEMAS` in `src/domain/skill_io.py`. Review
  criteria are `CRITERIA` in `src/domain/finding.py`.
- Graph Version 1 is the frozen file `src/services/agent_definition_manifest_v1.py`
  (no generator since #271). Its content hashes are pinned in two places:
  `tests/unit/test_packaged_release_loader.py:23` and
  `tests/unit/test_graph_definition_manifest.py:695`.
- The fix reviewer receives the pre-fix slide (`original_html`,
  `original_scripts`) alongside the fixed one, so it can judge a fix as a
  change. This landed separately (`cd7d1c3cd`) before the harness, and the
  fix_reviewer pack is written against it.
- MLflow 3.14 (`mlflow.genai.evaluate`, `make_judge`) and Playwright are already
  dependencies. `src/services/evaluation/llm_judge.py` is prior art for
  `make_judge`. No new dependencies are needed.

## 3. Architecture

```
evals/                                (new top-level dir; not collected by CI)
  configs/
    prices.yaml                       per-endpoint token prices
    <agent>/<name>.yaml               one configuration
  fixtures/meridian/
    bundle/                           Meridian design-system source (synthetic)
    deck_spec.json                    the gold deck spec
    slides/<position>.html            the gold deck, one slide per file
    scripts/<position>.js             Chart.js init for chart slides
  packs/<agent>/
    mutations.py                      generates cases from the gold
    judge_prompt.md                   this role's judge instructions
    scorers.py                        this role's scorer selection
    cases/<case_id>/                  generated: payload.json, reference.json, case.yaml
  harness/
    config.py                         YAML -> DefinitionContent (+ v1-baseline loader)
    runner.py                         run_candidate wrapper, infra-error retry
    render.py                         Playwright render + in-page measurements
    scorers.py                        shared scorers (contract, expected_category, render_measures)
    judge.py                          make_judge wrapper, pinned judge endpoint
    mlflow_run.py                     dataset build, genai.evaluate, tags and metrics
    promote.py                        configs -> v1 manifest + pinned hashes
  run_eval.py                         CLI entry point
tests/unit/evals/                     harness self-tests (CI, no model)
```

### Shared core vs agent packs

- **Core** (`harness/`, `run_eval.py`, `fixtures/`): built first, in sequence.
- **Packs** (`packs/<agent>/`): seven independent units built in parallel. A pack
  depends only on the core's interfaces: the case file format, the scorer
  protocol and the judge wrapper.

### Configuration file

```yaml
agent_key: builder
name: sonnet-tight-briefs
base: v1                    # start from the v1 definition; override fields below
prompt_file: prompts/builder-tight.md   # optional; relative to the config file
endpoint_name: databricks-claude-sonnet-5
temperature: 0.2
max_tokens: 4096
```

Fields not given are taken from `base`. `v1-baseline` is the unmodified v1
definition for each role, loaded through `load_graph_v1_manifest()`.

### Data flow per run

1. Load the configuration → `DefinitionContent` → `definition_content_hash`.
2. Build an MLflow evaluation dataset with **N rows per case**, tagged
   `case_id` and `repeat`.
3. `mlflow.genai.evaluate` runs every row concurrently through its worker pool
   (`MLFLOW_GENAI_EVAL_MAX_WORKERS`, set from `--max-workers`, default 8). Each
   row: `run_candidate` → (render, for HTML roles) → scorers.
4. Log one MLflow run per configuration with tags `agent_key`, `config_name`,
   `content_hash`, `judge_endpoint`, `repeats`, `case_filter`, and aggregate
   metrics (section 5).

### Concurrency

`run_candidate` and `DatabricksModelAdapter` are called from many threads at
once, and `AgentRuntime` is a shared `lru_cache`d instance. **Thread safety is
verified as the first core task**, with a stub adapter under concurrent load,
before any pack depends on it. If it is not safe, the runner constructs one
runtime per worker thread.

### CLI

```bash
python evals/run_eval.py --agent builder --config evals/configs/builder/sonnet-tight.yaml \
    --repeats 3 --max-workers 8 [--cases 2,4] [--judge-endpoint <name>]
python evals/run_eval.py --agent all --config v1-baseline --repeats 3
python evals/run_eval.py --agent builder --calibrate
python evals/packs/<agent>/mutations.py          # regenerate that pack's cases
mlflow ui --backend-store-uri sqlite:///mlflow.db
```

`--repeats` defaults to 3; use 1 while iterating and 5 when comparing v1
finalists.

## 4. Cases

### Rules

- A case is `payload.json` (exactly what the agent receives — the role's
  `MODEL_PAYLOAD_KEYS` set), `reference.json` (the known good), and `case.yaml`
  (`kind: positive|mutation`, the fault planted, the expected result, the slide
  positions and criteria concerned).
- One fault per case. Positive cases plant none.
- Cases are **generated** by the pack's `mutations.py` from the Meridian gold,
  never hand-edited, so they are reproducible and their diffs reviewable.
- All cases use the design-system-on branch (`design_system_active: true`,
  Meridian `resolved_style` and `section_css`). The default-style branch is out
  of scope for this version.
- All fixtures are synthetic and public-safe. Meridian is a fake brand.

### Gold

- The gold deck: "HTML Slides vs. PowerPoint: A Better Way to Present", 10
  slides, built by Tellr with the Meridian Test Design System and the Meridian
  Standard template. Slides 4 and 7 carry charts.
- `resolved_style` is the compiled style content from importing the Meridian
  bundle; `section_css` is its token CSS plus the template's style block,
  exactly as `_resolve_brand` would produce them.
- The knitted export's `slide-wrapper` / `slide-container` chrome and its
  `<style>` block are stripped when the deck is split per slide: each gold slide
  is the bare `<div class="slide">` fragment a builder emits.

### Case catalogue (5 per agent, 35 total)

| Agent | Cases |
|---|---|
| **builder** | 1. gold brief, bullet slide (slide 2). 2. gold brief, chart slide (slide 4). 3. gold brief, stat cards (slide 10). 4. brief with too much content for one slide. 5. chart requested, no data supplied. |
| **build_reviewer** | 1. gold slide → no objective findings. 2. hand-off broken → `brief_not_delivered`. 3. off-palette hex → `rogue_colour`. 4. extra bullets → `overflow`. 5. figure contradicts `resolved_data` → `source_contradiction`. |
| **fixer** | Given the broken slide and its finding: 1. `rogue_colour`. 2. `overflow`. 3. `contrast_failure`. 4. `source_contradiction`. 5. `brief_not_delivered` (broken hand-off). |
| **fix_reviewer** | 1. good fix → accept. 2. fault left in → reject. 3. fault fixed, content broken → reject. 4. fix restyles the whole slide → reject. 5. good `overflow` fix → accept. |
| **deck_reviewer** | 1. gold deck → no findings. 2. slide 9 dropped → `arc_gap`. 3. duplicated point → `cross_slide_repetition`. 4. slide 10 removed → `missing_conclusion`. 5. two slides swapped out of order → `arc_gap`. |
| **architect** | 1. build request → `build` + spec. 2. edit request → `edit` + positions. 3. data-dependent request → `ask_data`. 4. switch design system → `confirm_design_contract`, not a silent change. 5. question → `discuss`. |
| **data_analyst** | 1. figures inline → `success`. 2. two sources → `success` with synthesis. 3. nothing supplied → `missing_data`. 4. request needs a tool → `no_tool`. 5. conflicting figures → `success` with the conflict flagged. |

Every mutation's exact form (which bullet, which hex, which figure) is fixed in
`mutations.py` and documented in the generated `case.yaml`.

## 5. Scoring

Deterministic checks wherever the expected answer is a category; the LLM judge
only where the output is prose or HTML.

| Scorer | Kind | Roles | Passes when |
|---|---|---|---|
| `contract` | deterministic | all | the output passed the runtime's schema validation |
| `expected_category` | deterministic | architect, data_analyst, build_reviewer, fix_reviewer, deck_reviewer | intent / outcome / accept-reject / criteria set matches `case.yaml`; for reviewers, the planted criterion is raised at the right position **and** no unplanted objective finding is raised |
| `render_measures` | deterministic | builder, fixer | rendered at 1280×720 with the Meridian CSS: content does not overflow the frame; minimum text contrast ≥ 4.5:1; every used colour is in the Meridian palette; no `<style>` element; chart scripts run without console errors |
| `judge` | LLM | builder, fixer, architect (spec quality), data_analyst (synthesis faithfulness), reviewers (the finding's message describes the planted fault) | the candidate is functionally equivalent to, or better than, the reference for the case's brief or finding |

- Every scorer returns `pass` / `fail` plus a rationale.
- A **case run passes** only when every scorer that applies passes.
- A **case score** is the fraction of its N runs that passed.

### Render measurements

`render.py` loads the slide in a page that links the case's `section_css` and
the Chart.js CDN, waits for chart init, and evaluates in-page JavaScript that
returns:

- `overflow_px`: how far the slide's content extends past 720px height or 1280px
  width (0 when it fits);
- `min_contrast`: the lowest WCAG contrast ratio between rendered text colour
  and its effective background;
- `off_palette`: computed colours not in the palette parsed from the Meridian
  token CSS;
- `console_errors`: JavaScript errors raised during load.

These numbers are passed to the judge as facts and also drive
`render_measures`.

### Judge

- One pinned judge endpoint for every compared configuration, recorded as a run
  tag. The default is the workspace's Claude Sonnet serving endpoint, set as a
  single constant in `harness/judge.py`; `--judge-endpoint` overrides it. Judging
  is a mid-range task, so Sonnet is the cost/quality default. Scores across different judge endpoints are not comparable and the
  comparison view must not mix them.
- Prefer a judge from a different model family from the candidates. If all
  candidates are the same family, use its strongest model and tag the run.
- Each pack's `judge_prompt.md` receives the case input, the reference, the
  candidate output and the render measurements, and must give its verdict
  before its rationale.
- **Calibration** (`--calibrate`): run the judge on the reference as the
  candidate (must pass) and on the unfixed mutated input as the candidate (must
  fail), for every case. A pack whose judge misclassifies any calibration pair
  is flagged untrusted and its scores are reported as such.

### Aggregates logged per run

Overall pass rate; pass rate per case; standard deviation across repeats; count
of `infra_error` and `judge_error`; mean and p95 latency; mean input and output
tokens; estimated cost per case run (tokens × `prices.yaml`).

## 6. Error handling

| Failure | Treatment |
|---|---|
| Endpoint error or throttling (429 and similar) | `infra_error`; retried with exponential backoff (max 3); excluded from the pass rate. A run with > 10% infra errors is tagged `not_comparable`. |
| Output fails schema validation | a real agent failure: `contract` fails; not retried. |
| Judge call fails or returns an unparseable verdict | `judge_error` for that case run; never counted as pass or fail. |
| Render crashes | `render_measures` fails with console errors attached. |
| Invalid configuration file | the CLI exits before any model call, naming the field. |

## 7. Promotion to Graph Version 1

`promote.py --config architect=<file> --config builder=<file> ...`

1. Builds each `DefinitionContent` with the same loader the runner uses. Roles
   not named keep their current v1 definition.
2. Validates the result as `GraphV1Manifest` and calls
   `assert_complete(GRAPH_V1_AGENT_KEYS)`.
3. Rewrites `GRAPH_VERSION_1_MANIFEST_JSON` in
   `src/services/agent_definition_manifest_v1.py`.
4. Recomputes `definition_content_hash` per role and updates both pinned copies
   of `PACKAGED_V1_CONTENT_HASHES`.
5. Prints the MLflow run IDs that justify each promoted role, for the commit
   message.

It leaves a working-tree diff only: it never commits or pushes.

### Risks to resolve while building promote

- `src/services/prompt_assembler.py` holds `LegacyV1PromptTransition` records for
  `data_analyst` and `build_reviewer`, keyed to v1 composite prompts. Promote
  must establish whether changing those roles' v1 prompts breaks the
  transitions or their tests, and fail closed if it would.
- The bootstrap integrity guard validates seeded v1 rows. Confirm whether any
  database that has already seeded the current v1 would reject a changed v1.
  Devloop forks are re-created from prod on each deploy, but this is to be
  verified, not assumed.

## 8. Testing the harness

Runs in CI with no model (`tests/unit/evals/`):

- **Mutations:** each mutation plants exactly the fault it claims, checked by
  rendering or by diff against the gold.
- **Render:** every gold slide measures clean; the overflow, contrast and
  palette mutations measure dirty.
- **Runner:** wiring and concurrency with a stub `AgentModelAdapter`, including
  the thread-safety check from section 3.
- **Scorers:** `expected_category` against hand-written outputs (exact match,
  missing criterion, extra objective criterion).
- **Promote round trip:** promoting the current v1 to itself yields an
  identical file and identical hashes.

Real-model runs live under `evals/` and are not collected by CI, following the
`tests/agentic` convention.

## 9. Build order

1. **Core** (sequential): thread-safety check; config loader and v1-baseline;
   runner; renderer and measurements; shared scorers; judge wrapper; MLflow
   wiring; CLI; calibrate mode; promote; Meridian fixtures (bundle source, gold
   spec, gold slides split per slide).
2. **Packs** (seven in parallel, one subagent each): `mutations.py` →
   generated cases → judge prompt → calibration passing.
3. **Baseline sweep:** `v1-baseline` across all 35 cases at N=3. This is the
   scoreboard every candidate configuration is compared against.

## 10. Out of scope

- In-app integration (auto-verdicts in the test workbench). A later stage may
  surface the judge as an advisory score next to the human verdict.
- Whole-graph configuration combinations.
- The default-style (design-system-off) branch.
- A bespoke viewer that renders case HTML beside the gold. Add only if reading
  HTML as text in MLflow proves to be a real obstacle.
