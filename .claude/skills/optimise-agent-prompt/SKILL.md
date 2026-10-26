---
name: optimise-agent-prompt
description: Use when running a prompt (or model-setting) optimisation pass on one Tellr LangGraph agent with the offline eval harness in evals/. Covers the train/held-out discipline, the spend cap, what may and may not be changed, how to read failures from MLflow, and how a finalist is validated and handed over. Triggers on "optimise the <agent> prompt", "prompt optimisation pass", "tune the fix_reviewer", "improve the builder pass rate".
---

# Optimising a Tellr agent prompt

You are improving ONE agent's v1 definition (prompt text, optionally model settings) by measuring
candidates with the eval harness. Read `evals/README.md` first: it describes the configs, cases,
scorers, the held-out set and the current baselines. This skill is the rules of the search.

## The rules (non-negotiable)

1. **One agent per pass.** The user names it. Never sweep `--agent all` during a search.
2. **Tune on train only.** Every search sweep uses the default split (`--split train`). Never pass
   `--split heldout` during the search, never read `evals/packs/<agent>/cases_heldout/`, and never
   query the `tellr-agent-eval-heldout` MLflow experiment. Held-out is scored once, on finalists
   (see "Validating a finalist").
3. **Never change the yardstick.** Do not edit anything under `evals/packs/` (cases, references,
   calibrations, judge prompts), `evals/harness/` scorers or judge, `evals/fixtures/`, or
   `evals/configs/prices.yaml`. If you believe a case, reference or judge prompt is wrong, STOP and
   report it with evidence; the user decides.
4. **Only write candidate configs.** Candidates live in `evals/configs/<agent>/<name>.yaml` (with an
   optional prompt file beside it; see "Adding a config" in the README). Do not edit
   `src/core/skills/`, `src/services/agent_definition_manifest_v1.py`, pinned hashes or any `src/` code.
5. **No promote, no commits, no push.** Hand over finalists; the user runs `promote` (which leaves a
   reviewable diff) and commits.
6. **Spend cap.** Default USD 15 per pass unless the user gives another figure. Read `est_cost_usd`
   from each run and keep a running total in your notes. A full 5-case, 3-repeat sweep of one agent
   costs roughly USD 0.8 (data_analyst) to USD 3.5 (builder); see the baseline tables. Stop at the cap.
7. **Calibration first.** Before the first sweep, run
   `python -m evals.run_eval --agent <agent> --calibrate`. Every case must be trusted. Re-run only
   rows that hit a judge parse error or a network failure; if a case is misclassified, STOP and report.
8. **Never pip install**, never edit `.env`, and always use the default `--profile tellr-dev`.

## The loop

1. **Baseline.** If there is no train run for the current v1 at HEAD, run
   `python -m evals.run_eval --agent <agent> --config v1-baseline --repeats 3`.
2. **Read the failures, not just the rate.** For each failing row, read its scorer rationales in
   MLflow (experiment `tellr-agent-eval`, local store `sqlite:///mlflow.db`). The `contract` rationale
   carries the run status and the error detail when the output was rejected; `judge` carries the
   judge's reasoning; `expected_category` names the wrong or extra criterion. Group failures by
   cause, not by count.
3. **Change one thing per candidate**, aimed at one cause. Prefer instructions that state a rule the
   agent broke over examples copied from a case (copying case content into the prompt is fitting to
   train, not improving the agent).
4. **Iterate cheaply:** `--repeats 1` and `--cases <ids>` on the cases the change targets.
5. **Confirm on all train cases at `--repeats 5`** before calling a candidate a winner. A win is a
   higher pass rate with no case dropping by more than one repeat. Treat a single-repeat gain as noise:
   the judge is not perfectly consistent.
6. Record every candidate: name, hash, the cause it targets, train pass rate, cost.

## Validating a finalist

At most two finalists per pass. For each:

1. `python -m evals.run_eval --agent <agent> --calibrate --split heldout` (once per pass; all trusted).
2. `python -m evals.run_eval --agent <agent> --config evals/configs/<agent>/<name>.yaml --repeats 3 --split heldout`.
3. Report only the aggregate line it prints. Do not open the held-out per-case results. A finalist
   whose held-out pass rate falls below the v1 held-out baseline in `evals/README.md` has overfitted
   train; say so and do not recommend it.

## Hand-over

Write a short report for the user: the causes found on train, each candidate with its targeted cause
and result, total spend, the recommended finalist with its train (5-repeat) and held-out pass rates
against v1, and any case or judge problem you stopped on. Give the exact promote call for the
recommended config:

```python
from evals.harness.config import load_config
from evals.harness.promote import promote
promote({"<agent>": load_config("evals/configs/<agent>/<name>.yaml")}, dry_run=True)
```

## Known traps

- **Prompt and runtime facts.** The harness binds no tools to any agent, so a prompt that tells the
  data_analyst to call Genie or a vector index cannot be satisfied (open issue #301). Ask the user
  before tuning that agent.
- **Schema-rejected output.** The output schema is frozen. A candidate that makes the agent emit
  values outside it (for example an invented criterion name) fails `contract`; fix the prompt, not
  the schema.
- **Shared judge prompts** for the deck_reviewer and data_analyst mention train-deck examples. Do not
  copy those examples into a candidate prompt.
- **Architect edits** must return the full revised `deck_spec`; this is a product rule, not a tuning
  choice.
