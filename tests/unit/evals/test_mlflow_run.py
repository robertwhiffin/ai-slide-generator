"""Failing tests for Task 7: MLflow run assembly (evals/harness/mlflow_run.py).

RED until evals/harness/mlflow_run.py exists (and judge.calibrate gains render_fn).

Names this file FIXES for the implementer (see task-7-report.md, "names I fixed"):

* ``mlflow_run.load_cases`` / ``mlflow_run.load_case`` — module-level names the
  sweep / predict_fn look up AT CALL TIME (tests monkeypatch them).
* ``mlflow_run.render_slide`` — module-level name the predict_fn calls to render
  builder/fixer HTML (tests monkeypatch it; no Playwright in unit tests).
* Judge access goes through the ``evals.harness.judge`` MODULE at call time
  (``judge.build_judge(...)``, ``judge.judge_payload(...)``), so monkeypatching
  those module attributes takes effect.
* ``mlflow_run.pass_rate(values) -> float | None``.
* ``mlflow_run.row_outcome(values: dict[str, str]) -> "pass"|"fail"|"skip"``.
* ``mlflow_run.build_scorers(agent_key, *, judge_endpoint) -> list[Scorer]``;
  scorer ``.name`` values are drawn from {contract, expected_category,
  render_measures, judge}.
* ``run_sweep(..., runner=None, tracking_uri="sqlite:///mlflow.db")`` — two extra
  keywords: an injectable Runner and the tracking URI.
* Per-case pass rate metric key: ``pass_rate/<case_id>``.
* The judge is called as ``judge(outputs=<candidate structured>,
  expectations=<judge_payload(...) minus the "candidate" key>)``.
* ``judge.calibrate(agent_key, *, model=..., render_fn=None)`` where
  ``render_fn(case, candidate) -> RenderMeasures``.
"""
from __future__ import annotations

import dataclasses
import math
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

import src.core.database  # break import cycle before src.* imports  # noqa: F401

import mlflow
from mlflow.entities import Feedback

from evals.harness import case as case_mod
from evals.harness import config
from evals.harness import judge as judge_mod
from evals.harness import mlflow_run
from evals.harness.case import Case
from evals.harness.render import RenderMeasures
from evals.harness.runner import Runner
from src.services.graph_definition_manifest import definition_content_hash
from tests.fixtures.deterministic_model_adapter import FAKE_OUTPUTS

SCORER_NAMES = {"contract", "expected_category", "render_measures", "judge"}
OUTPUT_KEYS = {
    "structured", "raw", "render", "latency_ms",
    "input_tokens", "output_tokens", "status", "infra_error",
}
JUDGE_EP = "stub-judge-endpoint"


# ---------------------------------------------------------------------------
# helpers / stubs
# ---------------------------------------------------------------------------

def _case(cid, expect, kind="mutation"):
    return Case(cid, "build_reviewer", kind, True, "fault", payload={}, reference={}, expect=expect)


def _builder_case(cid, agent_key="builder"):
    return Case(
        case_id=cid, agent_key=agent_key, kind="positive", design_system_active=True,
        fault="none",
        payload={
            "position": 1,
            "slide_spec": {"position": 1, "title": f"CASE-MARK-{cid}", "purpose": "p"},
            "section_css": ".slide{}",
        },
        reference={"html": f"REF-{cid}"},
        expect={},
    )


def _cfg(agent_key="builder", prompt=None):
    base = config.v1_baseline(agent_key)
    if prompt is None:
        return base
    content = base.content.model_copy(update={"prompt_text": prompt})
    return config.AgentEvalConfig(agent_key, f"cfg-{prompt}", content, definition_content_hash(content))


class EchoAdapter:
    """Valid structured output per role; builder/fixer html echoes markers from the prompt."""

    def __init__(self, jitter=False):
        self.calls = 0
        self._lock = threading.Lock()
        self._jitter = jitter

    def invoke(self, *, agent_key, configuration, schema, prompt):
        with self._lock:
            self.calls += 1
        if self._jitter:
            time.sleep(random.random() * 0.004)
        out = dict(FAKE_OUTPUTS[agent_key])
        if agent_key in ("builder", "fixer"):
            cfg = re.search(r"CFG-MARK-[A-Z]", prompt)
            cm = re.search(r"CASE-MARK-[A-Za-z0-9_]+", prompt)
            out["html"] = (
                f"<section class='slide'><h1>{cfg.group(0) if cfg else 'nocfg'}"
                f"::{cm.group(0) if cm else 'nocase'}</h1></section>"
            )
        return schema.model_validate(out)


class BoomAdapter:
    def __init__(self):
        self.calls = 0
        self._lock = threading.Lock()

    def invoke(self, **k):
        from src.services.agent_runtime import ModelProviderUnavailableError

        with self._lock:
            self.calls += 1
        raise ModelProviderUnavailableError("503 endpoint down")


class StubJudge:
    """Callable judge double: verdict_fn(outputs, expectations) -> 'pass'|'fail' (or raises)."""

    def __init__(self, verdict_fn):
        self.verdict_fn = verdict_fn
        self.calls = []
        self._lock = threading.Lock()

    def __call__(self, *args, **kwargs):
        with self._lock:
            self.calls.append(kwargs)
        v = self.verdict_fn(kwargs.get("outputs"), kwargs.get("expectations"))
        if isinstance(v, str):
            return Feedback(value=v, rationale="stub")
        return v


CLEAN = RenderMeasures(overflow_px=0.0, min_contrast=21.0, rendered=True)


class RenderSpy:
    def __init__(self, measures=CLEAN):
        self.measures = measures
        self.calls = []
        self._lock = threading.Lock()

    def __call__(self, html, scripts="", **kwargs):
        with self._lock:
            self.calls.append({"html": html, "scripts": scripts, **kwargs})
        return self.measures


def _patch_cases(monkeypatch, cases):
    by_key = {(c.agent_key, c.case_id): c for c in cases}
    monkeypatch.setattr(mlflow_run, "load_cases",
                        lambda agent_key: [c for c in cases if c.agent_key == agent_key])
    monkeypatch.setattr(mlflow_run, "load_case", lambda agent_key, case_id: by_key[(agent_key, case_id)])


def _patch_judge(monkeypatch, stub):
    built = []

    def fake_build(*args, **kwargs):
        built.append((args, kwargs))
        return stub

    monkeypatch.setattr(judge_mod, "build_judge", fake_build)
    return built


def _outputs(structured, *, render=None, infra=False, status="completed"):
    return {
        "structured": structured, "raw": None, "render": render, "latency_ms": 1.0,
        "input_tokens": None, "output_tokens": None,
        "status": "model_error" if infra else status, "infra_error": infra,
    }


def _scorer(scorers, name):
    by_name = {s.name: s for s in scorers}
    assert name in by_name, f"no scorer named {name!r}; got {sorted(by_name)}"
    return by_name[name]


def _row(case, repeat=0):
    rows = mlflow_run.build_dataset([case], repeats=repeat + 1)
    return next(r for r in rows if r["inputs"]["repeat"] == repeat)


# ---------------------------------------------------------------------------
# Step 1 tests from the brief
# ---------------------------------------------------------------------------

def test_build_dataset_expands_repeats():
    rows = mlflow_run.build_dataset([_case("a", {"criteria": ["overflow"], "positions": [3]})], repeats=3)
    assert len(rows) == 3
    assert {r["inputs"]["repeat"] for r in rows} == {0, 1, 2}
    assert rows[0]["inputs"]["case_id"] == "a"


def test_pass_rate_excludes_infra_rows():
    agg = mlflow_run.pass_rate(["pass", "pass", "fail", "skip"])
    assert agg == 2 / 3


# ---------------------------------------------------------------------------
# pass_rate / row_outcome
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("values,expected", [
    (["pass"], 1.0),
    (["fail", "skip"], 0.0),
    (["pass", "fail", "fail", "skip", "skip", "skip"], 1 / 3),
    (["skip", "pass", "skip"], 1.0),
])
def test_pass_rate_is_pass_over_pass_plus_fail(values, expected):
    assert mlflow_run.pass_rate(values) == pytest.approx(expected)


@pytest.mark.parametrize("values", [["skip"], ["skip", "skip", "skip"], []])
def test_pass_rate_all_skip_is_none_not_zero(values):
    assert mlflow_run.pass_rate(values) is None


@pytest.mark.parametrize("values,expected", [
    ({"contract": "pass", "judge": "pass"}, "pass"),
    ({"contract": "pass", "judge": "fail"}, "fail"),
    ({"contract": "fail", "judge": "pass"}, "fail"),
    ({"contract": "pass", "expected_category": "fail", "judge": "pass"}, "fail"),
    # a not-applicable render skip (None render) does not void the row
    ({"contract": "pass", "render_measures": "skip", "judge": "pass"}, "pass"),
    # a judge error (judge skip) excludes the row from pass_rate
    ({"contract": "pass", "render_measures": "pass", "judge": "skip"}, "skip"),
    # infra error: every scorer skipped
    ({"contract": "skip", "render_measures": "skip", "judge": "skip"}, "skip"),
])
def test_row_outcome(values, expected):
    assert mlflow_run.row_outcome(values) == expected


# ---------------------------------------------------------------------------
# build_dataset
# ---------------------------------------------------------------------------

def test_build_dataset_rows_carry_inputs_and_expectations_per_case():
    a = Case("a", "build_reviewer", "mutation", True, "f", payload={"p": 1},
             reference={"r": "A"}, expect={"criteria": ["overflow"], "positions": [3]})
    b = Case("b", "build_reviewer", "positive", False, "f", payload={"p": 2},
             reference={"r": "B"}, expect={"criteria": [], "positions": []})
    rows = mlflow_run.build_dataset([a, b], repeats=2)
    assert len(rows) == 4
    assert {(r["inputs"]["case_id"], r["inputs"]["repeat"]) for r in rows} == {
        ("a", 0), ("a", 1), ("b", 0), ("b", 1)}
    for r in rows:
        assert set(r["inputs"]) == {"agent_key", "case_id", "repeat"}
        assert r["inputs"]["agent_key"] == "build_reviewer"
        src_case = a if r["inputs"]["case_id"] == "a" else b
        assert r["expectations"]["expect"] == src_case.expect
        assert r["expectations"]["reference"] == src_case.reference
        assert r["expectations"]["design_system_active"] is src_case.design_system_active


def test_build_dataset_expectation_keys_never_collide_with_scorer_names():
    rows = mlflow_run.build_dataset([_builder_case("a"), _case("b", {"criteria": []})], repeats=2)
    for r in rows:
        keys = set(r["expectations"])
        assert keys >= {"expect", "reference", "design_system_active"}
        assert keys.isdisjoint(SCORER_NAMES), keys & SCORER_NAMES


def test_scorer_names_are_the_fixed_set_and_disjoint_from_expectation_keys(monkeypatch):
    _patch_judge(monkeypatch, StubJudge(lambda o, e: "pass"))
    exp_keys = set(_row(_builder_case("a"))["expectations"])
    for role, must in [("builder", {"contract", "render_measures", "judge"}),
                       ("fixer", {"contract", "render_measures", "judge"}),
                       ("build_reviewer", {"contract", "expected_category", "judge"}),
                       ("architect", {"contract", "expected_category", "judge"})]:
        names = {s.name for s in mlflow_run.build_scorers(role, judge_endpoint=JUDGE_EP)}
        assert names <= SCORER_NAMES, names
        assert names >= must, (role, names)
        assert names.isdisjoint(exp_keys)


# ---------------------------------------------------------------------------
# predict_fn: render field, infra, isolation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("role", ["builder", "fixer"])
def test_predict_render_is_dict_for_html_roles(monkeypatch, role):
    c = _builder_case("a", agent_key=role)
    _patch_cases(monkeypatch, [c])
    measures = RenderMeasures(overflow_px=7.0, min_contrast=5.0, rendered=True)
    spy = RenderSpy(measures)
    monkeypatch.setattr(mlflow_run, "render_slide", spy)
    pf = mlflow_run.make_predict_fn(_cfg(role), Runner(model_adapter=EchoAdapter()), render_enabled=True)
    out = pf(agent_key=role, case_id="a", repeat=0)
    assert set(out) >= OUTPUT_KEYS
    assert out["status"] == "completed"
    assert out["infra_error"] is False
    assert isinstance(out["render"], dict)
    assert out["render"]["overflow_px"] == 7.0
    assert out["render"]["min_contrast"] == 5.0
    assert out["render"]["rendered"] is True
    assert len(spy.calls) == 1
    assert spy.calls[0]["html"] == out["structured"]["html"]
    assert spy.calls[0]["section_css"] == case_mod.meridian_section_css()


@pytest.mark.parametrize("role", ["architect", "data_analyst", "build_reviewer", "fix_reviewer", "deck_reviewer"])
def test_predict_render_is_none_for_non_html_roles(monkeypatch, role):
    c = _builder_case("a", agent_key=role)
    _patch_cases(monkeypatch, [c])
    spy = RenderSpy()
    monkeypatch.setattr(mlflow_run, "render_slide", spy)
    pf = mlflow_run.make_predict_fn(_cfg(role), Runner(model_adapter=EchoAdapter()), render_enabled=True)
    out = pf(agent_key=role, case_id="a", repeat=0)
    assert out["status"] == "completed"
    assert out["structured"] is not None
    assert out["render"] is None
    assert spy.calls == []


def test_predict_render_disabled_gives_none_without_rendering(monkeypatch):
    _patch_cases(monkeypatch, [_builder_case("a")])
    spy = RenderSpy()
    monkeypatch.setattr(mlflow_run, "render_slide", spy)
    pf = mlflow_run.make_predict_fn(_cfg(), Runner(model_adapter=EchoAdapter()), render_enabled=False)
    out = pf(agent_key="builder", case_id="a", repeat=0)
    assert out["structured"] is not None
    assert out["render"] is None
    assert spy.calls == []


def test_predict_infra_error_is_flagged(monkeypatch):
    _patch_cases(monkeypatch, [_builder_case("a")])
    monkeypatch.setattr(mlflow_run, "render_slide", RenderSpy())
    pf = mlflow_run.make_predict_fn(
        _cfg(), Runner(model_adapter=BoomAdapter(), max_infra_retries=0), render_enabled=True)
    out = pf(agent_key="builder", case_id="a", repeat=0)
    assert out["infra_error"] is True
    assert out["structured"] is None
    assert out["render"] is None


def test_concurrent_predict_with_different_configs_and_payloads_does_not_bleed(monkeypatch):
    cases_a = [_builder_case(f"a{i}") for i in range(8)]
    cases_b = [_builder_case(f"b{i}") for i in range(8)]
    _patch_cases(monkeypatch, cases_a + cases_b)
    shared = Runner(model_adapter=EchoAdapter(jitter=True))
    pf_a = mlflow_run.make_predict_fn(_cfg(prompt="Build it. CFG-MARK-A"), shared, render_enabled=False)
    pf_b = mlflow_run.make_predict_fn(_cfg(prompt="Build it. CFG-MARK-B"), shared, render_enabled=False)

    jobs = []
    for rep in range(3):
        for ca, cb in zip(cases_a, cases_b):
            jobs.append(("A", pf_a, ca.case_id, rep))
            jobs.append(("B", pf_b, cb.case_id, rep))

    def run(job):
        tag, pf, cid, rep = job
        return tag, cid, pf(agent_key="builder", case_id=cid, repeat=rep)

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(run, jobs))

    assert len(results) == 48
    for tag, cid, out in results:
        assert out["status"] == "completed", out
        assert f"CFG-MARK-{tag}::CASE-MARK-{cid}" in out["structured"]["html"], (tag, cid, out["structured"])


# ---------------------------------------------------------------------------
# scorers called directly
# ---------------------------------------------------------------------------

def test_infra_error_row_skips_every_scorer_without_calling_the_judge(monkeypatch):
    stub = StubJudge(lambda o, e: "pass")
    _patch_judge(monkeypatch, stub)
    c = _builder_case("a")
    _patch_cases(monkeypatch, [c])
    row = _row(c)
    scorers = mlflow_run.build_scorers("builder", judge_endpoint=JUDGE_EP)
    for s in scorers:
        fb = s.run(inputs=row["inputs"], outputs=_outputs(None, infra=True), expectations=row["expectations"])
        assert fb.value == "skip", (s.name, fb.value)
    assert stub.calls == []


def test_contract_scorer_pass_and_fail(monkeypatch):
    _patch_judge(monkeypatch, StubJudge(lambda o, e: "pass"))
    c = _builder_case("a")
    _patch_cases(monkeypatch, [c])
    row = _row(c)
    s = _scorer(mlflow_run.build_scorers("builder", judge_endpoint=JUDGE_EP), "contract")
    ok = s.run(inputs=row["inputs"], outputs=_outputs({"position": 1, "html": "<section/>"}),
               expectations=row["expectations"])
    bad = s.run(inputs=row["inputs"], outputs=_outputs(None, status="incomplete"),
                expectations=row["expectations"])
    assert ok.value == "pass"
    assert bad.value == "fail"


def test_expected_category_scorer_uses_case_expect(monkeypatch):
    _patch_judge(monkeypatch, StubJudge(lambda o, e: "pass"))
    c = Case("r1", "build_reviewer", "mutation", True, "f", payload={}, reference={},
             expect={"criteria": ["overflow"], "positions": [3]})
    _patch_cases(monkeypatch, [c])
    row = _row(c)
    s = _scorer(mlflow_run.build_scorers("build_reviewer", judge_endpoint=JUDGE_EP), "expected_category")
    hit = {"findings": [{"criterion": "overflow", "slide_index": 3}]}
    miss = {"findings": [{"criterion": "overflow", "slide_index": 1}]}
    assert s.run(inputs=row["inputs"], outputs=_outputs(hit), expectations=row["expectations"]).value == "pass"
    assert s.run(inputs=row["inputs"], outputs=_outputs(miss), expectations=row["expectations"]).value == "fail"


def test_render_measures_scorer_pass_fail_and_skip_on_none(monkeypatch):
    _patch_judge(monkeypatch, StubJudge(lambda o, e: "pass"))
    c = _builder_case("a")
    _patch_cases(monkeypatch, [c])
    row = _row(c)
    s = _scorer(mlflow_run.build_scorers("builder", judge_endpoint=JUDGE_EP), "render_measures")
    st = {"position": 1, "html": "<section class='slide'>x</section>", "scripts": ""}
    clean = dataclasses.asdict(CLEAN)
    overflow = dataclasses.asdict(RenderMeasures(overflow_px=40.0, min_contrast=21.0, rendered=True))
    kw = dict(inputs=row["inputs"], expectations=row["expectations"])
    assert s.run(outputs=_outputs(st, render=clean), **kw).value == "pass"
    assert s.run(outputs=_outputs(st, render=overflow), **kw).value == "fail"
    assert s.run(outputs=_outputs(st, render=None), **kw).value == "skip"


@pytest.mark.parametrize("verdict,expected", [("pass", "pass"), ("fail", "fail")])
def test_judge_scorer_maps_verdict(monkeypatch, verdict, expected):
    stub = StubJudge(lambda o, e: verdict)
    built = _patch_judge(monkeypatch, stub)
    c = _builder_case("a")
    _patch_cases(monkeypatch, [c])
    row = _row(c)
    s = _scorer(mlflow_run.build_scorers("builder", judge_endpoint=JUDGE_EP), "judge")
    st = {"position": 1, "html": "<section>C</section>", "scripts": ""}
    fb = s.run(inputs=row["inputs"], outputs=_outputs(st, render=dataclasses.asdict(CLEAN)),
               expectations=row["expectations"])
    assert fb.value == expected
    assert len(stub.calls) == 1
    assert stub.calls[0]["outputs"] == st
    assert stub.calls[0]["expectations"]["reference"] == c.reference
    assert stub.calls[0]["expectations"]["brief_or_finding"] == c.payload["slide_spec"]
    assert any(JUDGE_EP in a or k.get("model") == JUDGE_EP for a, k in built)


@pytest.mark.parametrize("bad", [
    "raise",
    SimpleNamespace(value=None, error="judge endpoint 503"),
    SimpleNamespace(value="maybe", error=None),
])
def test_judge_error_scores_skip_and_is_not_retried(monkeypatch, bad):
    def verdict(o, e):
        if bad == "raise":
            raise RuntimeError("judge endpoint 503")
        return bad

    stub = StubJudge(verdict)
    _patch_judge(monkeypatch, stub)
    c = _builder_case("a")
    _patch_cases(monkeypatch, [c])
    row = _row(c)
    s = _scorer(mlflow_run.build_scorers("builder", judge_endpoint=JUDGE_EP), "judge")
    fb = s.run(inputs=row["inputs"], outputs=_outputs({"position": 1, "html": "<section/>"}),
               expectations=row["expectations"])
    assert fb.value == "skip"
    assert len(stub.calls) == 1, "a judge error must not be retried"


def test_judge_scorer_builds_expectations_through_judge_payload(monkeypatch):
    stub = StubJudge(lambda o, e: "pass")
    _patch_judge(monkeypatch, stub)
    real = judge_mod.judge_payload
    spy_calls = []

    def spy(case, result, measures):
        spy_calls.append((case, result, measures))
        return {**real(case, result, measures), "spy_token": "JP-SPY-1"}

    monkeypatch.setattr(judge_mod, "judge_payload", spy)
    c = _builder_case("a")
    _patch_cases(monkeypatch, [c])
    row = _row(c)
    s = _scorer(mlflow_run.build_scorers("builder", judge_endpoint=JUDGE_EP), "judge")
    st = {"position": 1, "html": "<section>C</section>", "scripts": ""}
    render = dataclasses.asdict(RenderMeasures(overflow_px=7.0, min_contrast=5.0, rendered=True))
    fb = s.run(inputs=row["inputs"], outputs=_outputs(st, render=render), expectations=row["expectations"])
    assert fb.value == "pass"
    assert len(spy_calls) == 1
    case_arg, result_arg, measures_arg = spy_calls[0]
    assert case_arg.case_id == "a"
    assert result_arg.structured == st
    assert isinstance(measures_arg, RenderMeasures)
    assert measures_arg.overflow_px == 7.0
    # the judge saw judge_payload's output (minus the candidate), not a hand-built dict
    exp = stub.calls[0]["expectations"]
    assert exp["spy_token"] == "JP-SPY-1"
    assert "candidate" not in exp
    assert exp["measures"]["overflow_px"] == 7.0


def test_judge_scorer_measures_none_for_non_html_role(monkeypatch):
    stub = StubJudge(lambda o, e: "pass")
    _patch_judge(monkeypatch, stub)
    c = Case("r1", "architect", "positive", False, "f",
             payload={"message": "m", "current_deck_spec": None}, reference={"intent": "discuss"}, expect={})
    _patch_cases(monkeypatch, [c])
    row = _row(c)
    s = _scorer(mlflow_run.build_scorers("architect", judge_endpoint=JUDGE_EP), "judge")
    fb = s.run(inputs=row["inputs"], outputs=_outputs({"intent": "discuss", "message": "m"}),
               expectations=row["expectations"])
    assert fb.value == "pass"
    assert stub.calls[0]["expectations"]["measures"] is None


# ---------------------------------------------------------------------------
# run_sweep end to end (tmp sqlite, stub adapter, stub judge, no network)
# ---------------------------------------------------------------------------

@pytest.fixture
def tracking(tmp_path, monkeypatch):
    prev = mlflow.get_tracking_uri()
    monkeypatch.chdir(tmp_path)  # a relative sqlite:///mlflow.db would land here, never at repo root
    uri = f"sqlite:///{tmp_path / 'mlflow.db'}"
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    monkeypatch.delenv("MLFLOW_GENAI_EVAL_SKIP_TRACE_VALIDATION", raising=False)
    monkeypatch.delenv("MLFLOW_GENAI_EVAL_MAX_WORKERS", raising=False)
    yield uri
    mlflow.end_run()
    mlflow.set_tracking_uri(prev)


def _sweep(monkeypatch, uri, *, adapter, verdict, cases=None, repeats=2, case_filter=None):
    cases = cases if cases is not None else [_builder_case("a"), _builder_case("b")]
    _patch_cases(monkeypatch, cases)
    stub = StubJudge(verdict)
    built = _patch_judge(monkeypatch, stub)
    monkeypatch.setattr(mlflow_run, "render_slide", RenderSpy(CLEAN))
    cfg = _cfg()
    run_id = mlflow_run.run_sweep(
        cfg, agent_key="builder", repeats=repeats, max_workers=2, judge_endpoint=JUDGE_EP,
        case_filter=case_filter, render_enabled=True,
        runner=Runner(model_adapter=adapter, max_infra_retries=0), tracking_uri=uri,
    )
    mlflow.set_tracking_uri(uri)
    return run_id, mlflow.get_run(run_id), stub, built, cfg


def _fail_case_b(outputs, expectations):
    return "fail" if expectations["reference"] == {"html": "REF-b"} else "pass"


def test_run_sweep_end_to_end_tags_metrics_and_exact_call_count(monkeypatch, tracking, tmp_path):
    import os

    adapter = EchoAdapter()
    run_id, run, stub, built, cfg = _sweep(monkeypatch, tracking, adapter=adapter, verdict=_fail_case_b)

    assert isinstance(run_id, str) and run.info.run_id == run_id
    tags = run.data.tags
    assert tags["agent_key"] == "builder"
    assert tags["config_name"] == cfg.name
    assert tags["content_hash"] == cfg.content_hash
    assert tags["judge_endpoint"] == JUDGE_EP
    assert tags["repeats"] == "2"
    assert "not_comparable" not in tags
    assert "judge_unavailable" not in tags

    m = run.data.metrics
    # case a: 2 passing rows, case b: 2 judge-failed rows
    assert m["pass_rate"] == pytest.approx(0.5)
    assert m["pass_rate/a"] == pytest.approx(1.0)
    assert m["pass_rate/b"] == pytest.approx(0.0)
    assert m["infra_error_count"] == 0
    assert m["judge_error_count"] == 0
    for key in ("repeat_stddev", "mean_latency_ms", "p95_latency_ms"):
        assert key in m, key

    # the hidden trace-validation call is disabled, and nothing else calls the agent
    assert os.environ["MLFLOW_GENAI_EVAL_SKIP_TRACE_VALIDATION"].lower() in ("true", "1")
    assert os.environ["MLFLOW_GENAI_EVAL_MAX_WORKERS"] == "2"
    assert adapter.calls == 2 * 2, f"predict_fn ran {adapter.calls} times, expected n_cases*repeats=4"
    assert len(stub.calls) == 4
    assert any(JUDGE_EP in a or k.get("model") == JUDGE_EP for a, k in built)

    # genai.evaluate logged into THIS run, against the tmp store
    assert len(mlflow.search_traces(run_id=run_id)) == 4
    assert (tmp_path / "mlflow.db").exists()


def test_run_sweep_case_filter_limits_rows(monkeypatch, tracking):
    adapter = EchoAdapter()
    run_id, run, stub, _, _ = _sweep(
        monkeypatch, tracking, adapter=adapter, verdict=_fail_case_b, repeats=3, case_filter=["b"])
    assert adapter.calls == 3
    m = run.data.metrics
    assert m["pass_rate"] == pytest.approx(0.0)
    assert "pass_rate/b" in m
    assert "pass_rate/a" not in m


def test_run_sweep_all_infra_errors_skip_and_tag_not_comparable(monkeypatch, tracking):
    adapter = BoomAdapter()
    run_id, run, stub, _, _ = _sweep(monkeypatch, tracking, adapter=adapter, verdict=lambda o, e: "pass")
    assert adapter.calls == 4  # max_infra_retries=0, no hidden extra call
    m = run.data.metrics
    assert m["infra_error_count"] == 4
    assert m.get("judge_error_count", 0) == 0, "infra skips are not judge errors"
    assert "pass_rate" not in m or math.isnan(m["pass_rate"]), "all-skip run must not report a pass rate"
    assert "not_comparable" in run.data.tags
    assert "judge_unavailable" not in run.data.tags
    assert stub.calls == [], "the judge must not score infra-error rows"


def test_run_sweep_partial_judge_errors_excluded_from_pass_rate(monkeypatch, tracking):
    def verdict(outputs, expectations):
        if expectations["reference"] == {"html": "REF-b"}:
            raise RuntimeError("judge 503")
        return "pass"

    run_id, run, stub, _, _ = _sweep(monkeypatch, tracking, adapter=EchoAdapter(), verdict=verdict)
    m = run.data.metrics
    assert m["judge_error_count"] == 2
    assert m["infra_error_count"] == 0
    # b's rows are skip (excluded), not fail: pass_rate is 1.0, not 0.5
    assert m["pass_rate"] == pytest.approx(1.0)
    assert len(stub.calls) == 4, "judge errors are not retried"
    assert "judge_unavailable" not in run.data.tags
    assert "not_comparable" not in run.data.tags


def test_run_sweep_every_judge_row_errors_tags_judge_unavailable(monkeypatch, tracking):
    def verdict(outputs, expectations):
        raise RuntimeError("judge endpoint unavailable")

    run_id, run, stub, _, _ = _sweep(monkeypatch, tracking, adapter=EchoAdapter(), verdict=verdict)
    m = run.data.metrics
    assert m["judge_error_count"] == 4
    assert "pass_rate" not in m or math.isnan(m["pass_rate"])
    assert "judge_unavailable" in run.data.tags


class SomeBoomAdapter(EchoAdapter):
    """Infra-fails only the cases whose slide_spec title marker is in ``boom_ids``."""

    def __init__(self, boom_ids):
        super().__init__()
        self.boom_ids = set(boom_ids)

    def invoke(self, *, agent_key, configuration, schema, prompt):
        from src.services.agent_runtime import ModelProviderUnavailableError

        cm = re.search(r"CASE-MARK-([A-Za-z0-9_]+)", prompt)
        if cm and cm.group(1) in self.boom_ids:
            with self._lock:
                self.calls += 1
            raise ModelProviderUnavailableError("503 endpoint down")
        return super().invoke(agent_key=agent_key, configuration=configuration, schema=schema, prompt=prompt)


@pytest.mark.parametrize("n_cases, tagged", [(10, False), (8, True)])
def test_run_sweep_not_comparable_threshold_is_more_than_ten_percent(monkeypatch, tracking, n_cases, tagged):
    # exactly one infra-error row: 1/10 = 10% (not > 10%) vs 1/8 = 12.5% (> 10%)
    cases = [_builder_case(f"c{i}") for i in range(n_cases)]
    adapter = SomeBoomAdapter({"c0"})
    _, run, _, _, _ = _sweep(monkeypatch, tracking, adapter=adapter, verdict=lambda o, e: "pass",
                             cases=cases, repeats=1)
    assert run.data.metrics["infra_error_count"] == 1
    assert ("not_comparable" in run.data.tags) is tagged


def test_run_sweep_no_cases_raises_before_any_run_or_model_call(monkeypatch, tracking):
    adapter = EchoAdapter()
    with pytest.raises(mlflow_run.NoCasesError, match="builder"):
        _sweep(monkeypatch, tracking, adapter=adapter, verdict=lambda o, e: "pass", cases=[])
    assert adapter.calls == 0
    mlflow.set_tracking_uri(tracking)
    exp = mlflow.get_experiment_by_name(mlflow_run.EXPERIMENT_NAME)
    assert exp is None or mlflow.search_runs([exp.experiment_id]).empty


def test_run_sweep_case_filter_matching_nothing_raises_no_cases(monkeypatch, tracking):
    adapter = EchoAdapter()
    with pytest.raises(mlflow_run.NoCasesError, match="zz"):
        _sweep(monkeypatch, tracking, adapter=adapter, verdict=lambda o, e: "pass", case_filter=["zz"])
    assert adapter.calls == 0


# ---------------------------------------------------------------------------
# judge.calibrate render hook (the one permitted judge.py edit)
# ---------------------------------------------------------------------------

def _calib_setup(monkeypatch, agent_key="builder"):
    a = Case("a", agent_key, "mutation", True, "f",
             payload={"slide_spec": {"title": "T"}}, reference={"html": "<section>GOLD</section>", "scripts": ""},
             expect={})
    should_fail = {"html": "<section>WRONG-OUTPUT-LONGER</section>", "scripts": ""}
    stub = StubJudge(lambda o, e: "pass" if o == a.reference else "fail")
    monkeypatch.setattr(judge_mod, "load_cases", lambda k: [a])
    monkeypatch.setattr(judge_mod, "build_judge", lambda *x, **k: stub)
    monkeypatch.setattr(judge_mod, "load_calibration", lambda k, cid: {"should_fail": should_fail})
    return a, should_fail, stub


def test_calibrate_render_fn_measures_reach_the_judge(monkeypatch):
    a, should_fail, stub = _calib_setup(monkeypatch)
    rendered = []

    def render_fn(case, candidate):
        rendered.append((case.case_id, candidate))
        return RenderMeasures(overflow_px=float(len(candidate["html"])), min_contrast=9.0, rendered=True)

    rows = judge_mod.calibrate("builder", render_fn=render_fn)
    assert rows[0]["trusted"] is True
    assert ("a", a.reference) in rendered
    assert ("a", should_fail) in rendered
    assert len(stub.calls) == 2
    for call in stub.calls:
        meas = call["expectations"]["measures"]
        assert isinstance(meas, dict)
        assert meas["overflow_px"] == float(len(call["outputs"]["html"]))
        assert meas["min_contrast"] == 9.0


def test_calibrate_without_render_fn_measures_are_none(monkeypatch):
    _, _, stub = _calib_setup(monkeypatch)
    rows = judge_mod.calibrate("builder")
    assert rows[0]["trusted"] is True
    assert len(stub.calls) == 2
    assert all(c["expectations"]["measures"] is None for c in stub.calls)


def test_calibrate_builds_expectations_through_judge_payload(monkeypatch):
    _, _, stub = _calib_setup(monkeypatch)
    real = judge_mod.judge_payload
    seen = []

    def spy(case, result, measures):
        seen.append(case.case_id)
        return {**real(case, result, measures), "spy_token": "JP-SPY-CAL"}

    monkeypatch.setattr(judge_mod, "judge_payload", spy)
    judge_mod.calibrate("builder")
    assert seen == ["a", "a"]
    assert all(c["expectations"]["spy_token"] == "JP-SPY-CAL" for c in stub.calls)
    assert all("candidate" not in c["expectations"] for c in stub.calls)


def test_calibrate_empty_pack_returns_no_rows_without_building_a_judge(monkeypatch):
    monkeypatch.setattr(judge_mod, "load_cases", lambda k: [])

    def no_build(*a, **k):
        raise AssertionError("must not build a judge (or read judge_prompt.md) for an empty pack")

    monkeypatch.setattr(judge_mod, "build_judge", no_build)
    assert judge_mod.calibrate("deck_reviewer") == []
