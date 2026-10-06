"""Tests for evals.harness.judge (make_judge wrapper + calibration helper).

Documented assumptions (the brief is silent on these):

* A judge (what ``build_judge`` returns) is a callable invoked with keyword
  arguments; the candidate output is passed as the ``outputs`` keyword. If the
  implementation passes ``outputs`` as the whole ``judge_payload`` dict, the
  candidate is read from its ``"candidate"`` key (``_candidate_of`` handles both).
* The judge's verdict is an object with a ``.value`` attribute in
  {"pass", "fail"} (Feedback-like). ``calibrate`` must read ``.value``.
* ``calibrate`` obtains cases via ``judge.load_cases``, the judge via
  ``judge.build_judge`` and the wrong output via ``judge.load_calibration``
  (all module-level names); tests monkeypatch them, so no model call or network.
* ``judge.PACKS_DIR`` (absolute ``pathlib.Path`` ending ``evals/packs``) is the
  pack root: ``judge_prompt`` reads ``PACKS_DIR/<agent>/judge_prompt.md`` and
  ``load_calibration(agent, case_id)`` reads
  ``PACKS_DIR/<agent>/cases/<case_id>/calibration.json`` (``{"should_fail": ...}``),
  returning None if absent. Calibration candidates: ``case.reference`` (must pass)
  and ``should_fail`` (must fail). A case without calibration is untrusted with a
  ``reason`` mentioning ``calibration.json`` and must not raise.
  Result rows: {case_id, reference_passed, mutation_failed, trusted, reason};
  ``reason`` is truthy when untrusted.
* ``brief_or_finding`` for builder/fixer is the payload sub-dict itself; for
  multi-field roles (architect) only the presence of each field's content is asserted.
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from evals.harness import judge
from evals.harness.case import Case
from evals.harness.render import RenderMeasures
from evals.harness.runner import RunResult


def _result(structured):
    return RunResult(
        status="completed", structured=structured, raw=None, prompt=None,
        latency_ms=1.0, input_tokens=1, output_tokens=1,
        error_detail=None, infra_error=False,
    )


def _case(case_id="c1", agent_key="fixer", payload=None, reference=None):
    return Case(
        case_id=case_id, agent_key=agent_key, kind="mutation",
        design_system_active=False, fault="f",
        payload=payload if payload is not None else {"finding": {"issue": "x"}},
        reference=reference if reference is not None else {"html": f"ref-{case_id}"},
        expect={},
    )


def _candidate_of(kwargs):
    out = kwargs["outputs"]
    if isinstance(out, dict) and "candidate" in out and "reference" in out:
        return out["candidate"]
    return out


class StubJudge:
    """Records calls; verdict decided by verdict_fn(candidate, reference)."""

    def __init__(self, references, verdict_fn):
        self.references = references  # list of reference dicts
        self.verdict_fn = verdict_fn
        self.candidates = []

    def __call__(self, *args, **kwargs):
        cand = _candidate_of(kwargs)
        self.candidates.append(cand)
        is_ref = cand in self.references
        return SimpleNamespace(value=self.verdict_fn(is_ref, cand))


def _run_calibrate(monkeypatch, cases, verdict_fn):
    stub = StubJudge([c.reference for c in cases], verdict_fn)
    monkeypatch.setattr(judge, "load_cases", lambda agent_key: cases)
    monkeypatch.setattr(judge, "build_judge", lambda *a, **k: stub)
    return judge.calibrate(cases[0].agent_key), stub


# ---- constants / build_judge ------------------------------------------------

def test_default_endpoint_is_sonnet():
    assert judge.JUDGE_ENDPOINT == "databricks-claude-sonnet-5"


def test_build_judge_uses_pinned_model_and_pack_prompt(monkeypatch):
    monkeypatch.setattr(judge, "judge_prompt", lambda k: "Judge {{ outputs }} vs {{ expectations }}")
    with patch("evals.harness.judge.make_judge") as mj:
        judge.build_judge("builder")
        _, kw = mj.call_args
        assert kw["model"] == "databricks:/databricks-claude-sonnet-5"
        assert "builder" in kw["name"]
        assert kw["instructions"] == "Judge {{ outputs }} vs {{ expectations }}"


def test_build_judge_model_override_propagates(monkeypatch):
    monkeypatch.setattr(judge, "judge_prompt", lambda k: "{{ outputs }} {{ expectations }}")
    with patch("evals.harness.judge.make_judge") as mj:
        judge.build_judge("builder", model="other-endpoint")
        _, kw = mj.call_args
        assert kw["model"] == "databricks:/other-endpoint"


# ---- judge_prompt -----------------------------------------------------------

def test_default_packs_dir_is_absolute_evals_packs():
    import pathlib
    assert isinstance(judge.PACKS_DIR, pathlib.Path)
    assert judge.PACKS_DIR.is_absolute()
    assert judge.PACKS_DIR.as_posix().endswith("evals/packs")


def test_judge_prompt_reads_pack_file(tmp_path, monkeypatch):
    pack = tmp_path / "zzagent"
    pack.mkdir(parents=True)
    text = "Unique prompt {{ outputs }} / {{ expectations }} 7f3a9c"
    (pack / "judge_prompt.md").write_text(text)
    monkeypatch.setattr(judge, "PACKS_DIR", tmp_path)
    assert judge.judge_prompt("zzagent").strip() == text


# ---- judge_payload ----------------------------------------------------------

def test_payload_builder_uses_slide_spec():
    spec = {"title": "Q3", "bullets": ["a"]}
    case = _case(agent_key="builder", payload={"slide_spec": spec}, reference={"html": "R"})
    out = judge.judge_payload(case, _result({"html": "C"}), None)
    assert set(out) >= {"candidate", "reference", "brief_or_finding", "measures"}
    assert out["candidate"] == {"html": "C"}
    assert out["reference"] == {"html": "R"}
    assert out["brief_or_finding"] == spec
    assert out["measures"] is None


def test_payload_fixer_uses_finding_and_measures_dict():
    finding = {"issue": "overflow", "slide": 3}
    case = _case(agent_key="fixer", payload={"finding": finding, "noise": "zzz"})
    m = RenderMeasures(overflow_px=12.0, min_contrast=4.6, rendered=True)
    out = judge.judge_payload(case, _result({"html": "C"}), m)
    assert out["brief_or_finding"] == finding
    assert isinstance(out["measures"], dict)
    assert out["measures"]["overflow_px"] == 12.0
    assert out["measures"]["min_contrast"] == 4.6
    assert out["measures"]["rendered"] is True


@pytest.mark.parametrize("role", ["build_reviewer", "fix_reviewer"])
def test_payload_reviewers_use_finding(role):
    finding = {"issue": "contrast"}
    case = _case(agent_key=role, payload={"finding": finding})
    out = judge.judge_payload(case, _result({"verdict": "ok"}), None)
    assert out["brief_or_finding"] == finding


def test_payload_architect_has_message_and_deck_spec():
    case = _case(
        agent_key="architect",
        payload={"message": "MSG-SENTINEL-1", "current_deck_spec": {"s": "DECK-SENTINEL-2"}},
    )
    out = judge.judge_payload(case, _result({"plan": 1}), None)
    blob = json.dumps(out["brief_or_finding"], default=str)
    assert "MSG-SENTINEL-1" in blob
    assert "DECK-SENTINEL-2" in blob


def test_payload_data_analyst_uses_data_request():
    case = _case(agent_key="data_analyst", payload={"data_request": {"q": "DR-SENT"}})
    out = judge.judge_payload(case, _result({"x": 1}), None)
    assert out["brief_or_finding"] == {"q": "DR-SENT"}


def test_payload_deck_reviewer_has_arc_and_cta():
    case = _case(agent_key="deck_reviewer",
                 payload={"narrative_arc": "ARC-SENT", "call_to_action": "CTA-SENT"})
    out = judge.judge_payload(case, _result({"x": 1}), None)
    blob = json.dumps(out["brief_or_finding"], default=str)
    assert "ARC-SENT" in blob and "CTA-SENT" in blob


# ---- load_calibration ------------------------------------------------------

def test_load_calibration_reads_file_and_none_when_absent(tmp_path, monkeypatch):
    d = tmp_path / "fixer" / "cases" / "c1"
    d.mkdir(parents=True)
    (d / "calibration.json").write_text(json.dumps({"should_fail": {"html": "BAD"}}))
    monkeypatch.setattr(judge, "PACKS_DIR", tmp_path)
    assert judge.load_calibration("fixer", "c1") == {"should_fail": {"html": "BAD"}}
    assert judge.load_calibration("fixer", "nope") is None


# ---- calibrate --------------------------------------------------------------

def _wrong(case):
    return {"html": f"WRONG-{case.case_id}"}


def _run_calibrate(monkeypatch, cases, verdict_fn, calibrations=None):
    if calibrations is None:
        calibrations = {c.case_id: {"should_fail": _wrong(c)} for c in cases}
    stub = StubJudge([c.reference for c in cases], verdict_fn)
    monkeypatch.setattr(judge, "load_cases", lambda agent_key: cases)
    monkeypatch.setattr(judge, "build_judge", lambda *a, **k: stub)
    monkeypatch.setattr(judge, "load_calibration", lambda agent, cid: calibrations.get(cid))
    return judge.calibrate(cases[0].agent_key), stub


def _good(is_ref, cand):
    return "pass" if is_ref else "fail"


def test_calibrate_trusted_when_judge_separates_gold_from_fault(monkeypatch):
    cases = [_case("a"), _case("b")]
    res, _ = _run_calibrate(monkeypatch, cases, _good)
    assert [r["case_id"] for r in res] == ["a", "b"]
    for r in res:
        assert r["reference_passed"] is True
        assert r["mutation_failed"] is True
        assert r["trusted"] is True


def test_calibrate_untrusted_when_judge_passes_the_should_fail(monkeypatch):
    res, _ = _run_calibrate(monkeypatch, [_case("a")], lambda is_ref, c: "pass")
    assert res[0]["reference_passed"] is True
    assert res[0]["mutation_failed"] is False
    assert res[0]["trusted"] is False
    assert res[0]["reason"]


def test_calibrate_untrusted_when_judge_fails_the_reference(monkeypatch):
    res, _ = _run_calibrate(monkeypatch, [_case("a")], lambda is_ref, c: "fail")
    assert res[0]["reference_passed"] is False
    assert res[0]["mutation_failed"] is True
    assert res[0]["trusted"] is False
    assert res[0]["reason"]


def test_calibrate_mixed_cases_trust_is_decided_per_case(monkeypatch):
    a, b = _case("a"), _case("b")
    # Right on A; wrong on B (passes B's should_fail).
    verdict = lambda is_ref, cand: "pass" if (is_ref or cand == _wrong(b)) else "fail"
    res, _ = _run_calibrate(monkeypatch, [a, b], verdict)
    by_id = {r["case_id"]: r for r in res}
    assert by_id["a"]["trusted"] is True
    assert by_id["b"]["trusted"] is False
    assert by_id["b"]["mutation_failed"] is False


def test_calibrate_judges_reference_and_should_fail_as_candidates(monkeypatch):
    case = _case("a", reference={"html": "GOLD-REF"})
    res, stub = _run_calibrate(monkeypatch, [case], _good)
    assert case.reference in stub.candidates
    assert _wrong(case) in stub.candidates, "should_fail content must be the second candidate exactly"
    assert stub.candidates.index(case.reference) < stub.candidates.index(_wrong(case))
    assert res[0]["trusted"] is True


def test_calibrate_missing_calibration_is_untrusted_not_raising(monkeypatch):
    a, b = _case("a"), _case("b")
    res, stub = _run_calibrate(
        monkeypatch, [a, b], _good, calibrations={"a": {"should_fail": _wrong(a)}}
    )
    by_id = {r["case_id"]: r for r in res}
    assert by_id["a"]["trusted"] is True
    assert by_id["b"]["trusted"] is False
    assert "calibration.json" in by_id["b"]["reason"]


def test_calibrate_builds_judge_for_agent_with_model(monkeypatch):
    case = _case("a")
    stub = StubJudge([case.reference], _good)
    bj = MagicMock(return_value=stub)
    monkeypatch.setattr(judge, "load_cases", lambda k: [case])
    monkeypatch.setattr(judge, "build_judge", bj)
    monkeypatch.setattr(judge, "load_calibration", lambda a, c: {"should_fail": _wrong(case)})
    judge.calibrate("fixer", model="other-endpoint")
    args, kwargs = bj.call_args
    assert "fixer" in args or kwargs.get("agent_key") == "fixer"
    assert kwargs.get("model", args[1] if len(args) > 1 else None) == "other-endpoint"
