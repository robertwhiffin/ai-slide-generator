"""Read-only report of the architect's intent accuracy and position accuracy for one eval run.

    uv run python -m evals.intent_report --run-id ID [--cases a,b] [--tracking-uri URI] [--json]

Two numbers, defined once (plan D9), both over the run's non-infra rows:

* **intent accuracy** -- the share of rows whose got intent (``structured["intent"]``) equals the
  expected intent. A row with no output counts as wrong and is also counted as ``no_output``.
* **position accuracy** -- over the rows whose expected AND got intent are both ``edit``, the share
  whose ``set(target_positions)`` equals the expected set (order and duplicates ignored).

Why a separate report: the harness's ``expected_category`` scorer fails an architect row when the
intent is wrong OR when an edit's positions are wrong, so its pass rate conflates the two; and MLflow
aggregates only numeric/bool/yes-no assessment values, while the harness logs "pass"/"fail" strings,
so no run-level number exists for either. This module recomputes both from the run's traces.

Held-out runs print aggregates only (one line, or the aggregate keys under ``--json``), never a case id.
The report reads the store named by the tracking URI and writes nothing to it; a sqlite URI whose
file does not exist is refused rather than created.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import src.core.database  # noqa: F401 - break import cycle before src.* imports

import mlflow
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient
from sqlalchemy.engine import make_url

from evals.harness import mlflow_run
from evals.harness.case import load_case, split_kwargs


def _assessment(trace, name: str):
    """The value of the trace's assessment called *name* (Feedback or Expectation), else None."""
    for a in trace.info.assessments:
        if a.name == name:
            return a.value
    return None


def row_from_trace(trace, *, split: str) -> dict | None:
    """One counted row, or None for an infra-error row.

    Keys: case_id, expected_intent, expected_positions (sorted; [] unless edit), got_intent (None
    when ``structured`` is not a dict), got_positions (sorted), expected_category ("pass"|"fail"|
    "skip"|None). Inputs and outputs are parsed from the full request/response JSON, not the
    truncated trace previews. ``expect`` is the trace's Expectation named "expect"; when the run
    did not log one it is loaded from the case on disk for *split*.
    """
    case_id = json.loads(trace.data.request)["case_id"]
    outputs = json.loads(trace.data.response or "null") or {}
    if outputs.get("infra_error"):
        return None

    expect = _assessment(trace, "expect")
    if expect is None:
        expect = load_case("architect", case_id, **split_kwargs(split)).expect
    expected_intent = expect.get("intent")

    structured = outputs.get("structured")
    got = structured if isinstance(structured, dict) else {}
    return {
        "case_id": case_id,
        "expected_intent": expected_intent,
        "expected_positions": sorted(expect.get("positions") or []) if expected_intent == "edit" else [],
        "got_intent": got.get("intent"),
        "got_positions": sorted(got.get("target_positions") or []),
        "expected_category": _assessment(trace, "expected_category"),
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _counts(rows: list[dict]) -> dict:
    edit = [r for r in rows if r["expected_intent"] == "edit" and r["got_intent"] == "edit"]
    intent_correct = sum(r["got_intent"] is not None and r["got_intent"] == r["expected_intent"] for r in rows)
    positions_correct = sum(set(r["got_positions"]) == set(r["expected_positions"]) for r in edit)
    return {
        "rows": len(rows),
        "intent_correct": intent_correct,
        "intent_accuracy": _ratio(intent_correct, len(rows)),
        "no_output": sum(r["got_intent"] is None for r in rows),
        "edit_rows": len(edit),
        "positions_correct": positions_correct,
        "position_accuracy": _ratio(positions_correct, len(edit)),
        "expected_category_pass": sum(r["expected_category"] == "pass" for r in rows),
    }


def summarise(rows: list[dict]) -> dict:
    """Intent and position accuracy over *rows*, overall and ``per_case``.

    Accuracies are None when their denominator is 0. ``edit_rows`` counts the rows whose expected
    AND got intent are both "edit". Each ``per_case`` entry adds ``got_intents``
    ({intent or "none": count}).
    """
    by_case: dict[str, list[dict]] = {}
    for row in rows:
        by_case.setdefault(row["case_id"], []).append(row)
    per_case = {
        case_id: {
            **_counts(case_rows),
            "got_intents": dict(Counter("none" if r["got_intent"] is None else r["got_intent"]
                                        for r in case_rows)),
        }
        for case_id, case_rows in by_case.items()
    }
    return {**_counts(rows), "per_case": per_case}


def _require_existing_store(uri: str) -> None:
    """Opening a sqlite URI whose file does not exist makes MLflow create an empty store; refuse instead."""
    if uri.startswith("sqlite:"):
        path = make_url(uri).database
        if path and path != ":memory:" and not Path(path).exists():
            raise MlflowException(f"no MLflow store at {uri}")


def _report(run_id: str, tracking_uri: str | None, cases: list[str] | None) -> tuple[dict, dict]:
    """(the run's tags, the report): what ``report`` returns plus the tags the CLI header prints."""
    uri = tracking_uri or mlflow_run.default_tracking_uri()
    _require_existing_store(uri)
    run = MlflowClient(uri).get_run(run_id)
    mlflow.set_tracking_uri(uri)
    # ``locations`` is required: the runs live in the tellr-agent-eval[-heldout] experiments, and
    # without it search_traces looks in the process's active experiment and raises.
    traces = mlflow.search_traces(
        run_id=run_id, locations=[run.info.experiment_id], return_type="list")

    split = run.data.tags.get("split", "train")
    wanted = set(cases) if cases else None
    rows, infra_skipped = [], 0
    for trace in traces:
        if wanted is not None and json.loads(trace.data.request)["case_id"] not in wanted:
            continue
        row = row_from_trace(trace, split=split)
        if row is None:
            infra_skipped += 1
        else:
            rows.append(row)
    return run.data.tags, {**summarise(rows), "infra_skipped": infra_skipped}


def report(run_id: str, *, tracking_uri: str | None = None, cases: list[str] | None = None) -> dict:
    """``summarise`` of the run's non-infra rows (restricted to *cases* if given), plus ``infra_skipped``.

    The split comes from the run's ``split`` tag (default "train"). ``tracking_uri`` defaults to the
    harness's per-worktree store.
    """
    return _report(run_id, tracking_uri, cases)[1]


def _fraction(numerator: int, denominator: int, accuracy: float | None) -> str:
    return f"{numerator}/{denominator}" + ("" if accuracy is None else f" ({accuracy:.0%})")


def _line(label: str, s: dict) -> str:
    parts = [f"rows={s['rows']}", "intent_ok=" + _fraction(s["intent_correct"], s["rows"], s["intent_accuracy"])]
    if "got_intents" in s:
        parts.append("got_intents=" + ",".join(f"{k}:{v}" for k, v in sorted(s["got_intents"].items())))
    parts += [
        f"edit_rows={s['edit_rows']}",
        "positions_ok=" + _fraction(s["positions_correct"], s["edit_rows"], s["position_accuracy"]),
        f"expected_category_pass={s['expected_category_pass']}/{s['rows']}",
    ]
    return f"{label}  " + " ".join(parts)


def _print_train(run_id: str, tags: dict, result: dict) -> None:
    print(f"run {run_id}  split=train  config_name={tags.get('config_name')}  "
          f"content_hash={(tags.get('content_hash') or '')[:12]}  "
          f"cases_digest={(tags.get('cases_digest') or '')[:12]}")
    width = max([len("ALL"), *map(len, result["per_case"])])
    for case_id, s in sorted(result["per_case"].items()):
        print(_line(case_id.ljust(width), s))
    print(_line("ALL".ljust(width), result) + f" no_output={result['no_output']} "
          f"infra_skipped={result['infra_skipped']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evals.intent_report",
        description="Architect intent accuracy and position accuracy for one eval run (read-only).")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--cases", default=None, help="comma-separated case ids; restricts the rows counted")
    parser.add_argument("--tracking-uri", default=None, help="default: the harness's per-worktree mlflow.db")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    cases = [c.strip() for c in args.cases.split(",") if c.strip()] if args.cases else None

    try:
        tags, result = _report(args.run_id, args.tracking_uri, cases)
    except MlflowException as e:
        print(f"intent_report: {e}", file=sys.stderr)
        return 1

    split = tags.get("split", "train")
    if split != "train":  # held-out discipline: aggregates only, never a case id
        result = {k: v for k, v in result.items() if k != "per_case"}
    if args.json:
        print(json.dumps(result, indent=2))
    elif split == "train":
        _print_train(args.run_id, tags, result)
    else:
        print(f"run {args.run_id}  split={split}  " + _line("ALL", result)
              + f" no_output={result['no_output']} infra_skipped={result['infra_skipped']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
