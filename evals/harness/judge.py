"""LLM judge wrapper (mlflow make_judge) and calibration helper."""
import dataclasses
import json
import pathlib
import types
from typing import Literal

from mlflow.genai import make_judge

from evals.harness.case import Case, load_cases, PACKS_DIR

JUDGE_ENDPOINT = "databricks-claude-sonnet-5"


def judge_prompt(agent_key: str) -> str:
    return (PACKS_DIR / agent_key / "judge_prompt.md").read_text()


def build_judge(agent_key: str, *, model: str = JUDGE_ENDPOINT):
    return make_judge(
        name=f"{agent_key}_equivalence",
        instructions=judge_prompt(agent_key),
        model=f"databricks:/{model}",
        feedback_value_type=Literal["pass", "fail"],
    )


def _brief_or_finding(case: Case):
    p = case.payload
    role = case.agent_key
    if role == "builder":
        return p.get("slide_spec")
    if role in ("fixer", "build_reviewer", "fix_reviewer"):
        return p.get("finding")
    if role == "architect":
        return {"message": p.get("message"), "current_deck_spec": p.get("current_deck_spec")}
    if role == "data_analyst":
        return p.get("data_request")
    if role == "deck_reviewer":
        return {"narrative_arc": p.get("narrative_arc"), "call_to_action": p.get("call_to_action")}
    return p


def _measures_dict(measures):
    if measures is None:
        return None
    return dataclasses.asdict(measures)


def judge_payload(case: Case, result, measures) -> dict:
    return {
        "candidate": result.structured,
        "reference": case.reference,
        "brief_or_finding": _brief_or_finding(case),
        "measures": _measures_dict(measures),
    }


def load_calibration(agent_key: str, case_id: str) -> dict | None:
    path = PACKS_DIR / agent_key / "cases" / case_id / "calibration.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _verdict(judge, case: Case, candidate, measures=None) -> tuple[str, str]:
    """Return ("pass"|"fail"|"error", detail). Errors are never pass or fail."""
    payload = judge_payload(case, types.SimpleNamespace(structured=candidate), measures)
    payload.pop("candidate")
    expectations = payload
    try:
        fb = judge(outputs=candidate, expectations=expectations)
    except Exception as e:  # noqa: BLE001 - a judge error is neither pass nor fail
        return "error", f"{type(e).__name__}: {e}"
    if getattr(fb, "error", None) is not None:
        return "error", str(fb.error)
    value = getattr(fb, "value", None)
    v = value.strip().lower() if isinstance(value, str) else None
    if v in ("pass", "fail"):
        return v, ""
    return "error", f"unrecognised judge value {value!r}"


def calibrate(agent_key: str, *, model: str = JUDGE_ENDPOINT, render_fn=None) -> list[dict]:
    cases = load_cases(agent_key)
    if not cases:
        return []  # empty pack: no judge_prompt.md needed, nothing to calibrate
    judge = build_judge(agent_key, model=model)
    rows = []
    for case in cases:
        cal = load_calibration(agent_key, case.case_id)
        if not cal or "should_fail" not in cal:
            rows.append({
                "case_id": case.case_id, "reference_passed": False,
                "mutation_failed": False, "trusted": False,
                "reason": "missing calibration.json (no should_fail output)",
            })
            continue
        ref_m = render_fn(case, case.reference) if render_fn else None
        mut_m = render_fn(case, cal["should_fail"]) if render_fn else None
        ref_v, ref_detail = _verdict(judge, case, case.reference, ref_m)
        mut_v, mut_detail = _verdict(judge, case, cal["should_fail"], mut_m)
        ref_ok = ref_v == "pass"
        mut_fail = mut_v == "fail"
        reasons = []
        if ref_v == "error":
            reasons.append(f"judge error on reference ({ref_detail})")
        elif not ref_ok:
            reasons.append("judge failed the reference")
        if mut_v == "error":
            reasons.append(f"judge error on should_fail ({mut_detail})")
        elif not mut_fail:
            reasons.append("judge passed the should_fail output")
        rows.append({
            "case_id": case.case_id, "reference_passed": ref_ok,
            "mutation_failed": mut_fail, "trusted": ref_ok and mut_fail,
            "reason": "; ".join(reasons),
        })
    return rows
