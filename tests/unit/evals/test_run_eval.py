"""Failing tests for Task 7: the run_eval CLI (evals/run_eval.py).

Names fixed here (see task-7-report.md):
* ``run_eval.main(argv: list[str])`` is the entry point.
* ``run_eval`` calls ``mlflow_run.run_sweep`` and ``judge.calibrate`` through the
  ``evals.harness.mlflow_run`` / ``evals.harness.judge`` MODULES at call time.
* ``validate_endpoint`` warns via ``warnings.warn(..., UserWarning)`` naming the
  endpoint when it is absent from ``prices()``.
* ``--cases 2,4`` becomes ``case_filter=["2", "4"]``; absent -> ``None``.
* ``--calibrate`` passes ``render_fn`` to ``judge.calibrate`` for builder/fixer
  (``render_fn(case, candidate) -> RenderMeasures``) and ``render_fn=None`` (or
  omits it) for every other role.
"""
from __future__ import annotations

import warnings

import pytest

import src.core.database  # noqa: F401

import evals.run_eval as cli
from evals.harness import case as case_mod
from evals.harness import config
from evals.harness import judge as judge_mod
from evals.harness import mlflow_run
from evals.harness import render as render_mod
from evals.harness.case import Case
from evals.harness.render import RenderMeasures


@pytest.fixture(autouse=True)
def profile_calls(monkeypatch):
    """main() pins a Databricks profile into os.environ; stub it so tests never touch real auth."""
    calls = []
    monkeypatch.setattr(cli, "apply_profile", lambda profile: calls.append(profile) or "https://h")
    return calls


def _cfg_with_endpoint(name):
    base = config.v1_baseline("builder")
    content = base.content.model_copy(
        update={"model": base.content.model.model_copy(update={"endpoint_name": name})})
    return config.AgentEvalConfig("builder", "x", content, "h")


# ---- validate_endpoint ------------------------------------------------------

def test_unservable_endpoint_fails_fast_naming_the_field(monkeypatch):
    cfg = config.v1_baseline("builder").content.model_copy(
        update={"model": config.v1_baseline("builder").content.model.model_copy(
            update={"endpoint_name": "no-such-endpoint"})})
    monkeypatch.setattr(cli, "_endpoint_reachable", lambda name: False)
    with pytest.raises(SystemExit) as e:
        cli.validate_endpoint(config.AgentEvalConfig("builder", "x", cfg, "h"))
    assert "endpoint_name" in str(e.value)


def test_validate_endpoint_probes_the_configured_endpoint(monkeypatch):
    probed = []
    monkeypatch.setattr(cli, "_endpoint_reachable", lambda name: probed.append(name) or True)
    cli.validate_endpoint(_cfg_with_endpoint("databricks-claude-sonnet-5"))
    assert probed == ["databricks-claude-sonnet-5"]


def test_unpriced_endpoint_warns_but_is_not_fatal(monkeypatch):
    monkeypatch.setattr(cli, "_endpoint_reachable", lambda name: True)
    with pytest.warns(UserWarning, match="unpriced-endpoint-xyz"):
        cli.validate_endpoint(_cfg_with_endpoint("unpriced-endpoint-xyz"))


def test_priced_reachable_endpoint_is_silent(monkeypatch):
    monkeypatch.setattr(cli, "_endpoint_reachable", lambda name: True)
    assert "databricks-claude-opus-4-6" in config.prices()
    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("always")
        cli.validate_endpoint(config.v1_baseline("builder"))
    assert not [w for w in rec if "databricks-claude-opus-4-6" in str(w.message)]


# ---- main: sweep wiring -----------------------------------------------------

class SweepSpy:
    def __init__(self, events):
        self.events = events
        self.calls = []

    def __call__(self, cfg, **kwargs):
        self.events.append("sweep")
        self.calls.append((cfg, kwargs))
        return "run-123"


def _wire(monkeypatch, reachable=True):
    events = []

    def probe(name):
        events.append("probe")
        return reachable

    monkeypatch.setattr(cli, "_endpoint_reachable", probe)
    spy = SweepSpy(events)
    monkeypatch.setattr(mlflow_run, "run_sweep", spy)
    cal = []
    monkeypatch.setattr(judge_mod, "calibrate", lambda *a, **k: cal.append((a, k)) or [])
    return events, spy, cal


def test_main_unreachable_endpoint_exits_before_any_sweep(monkeypatch):
    events, spy, _ = _wire(monkeypatch, reachable=False)
    with pytest.raises(SystemExit) as e:
        cli.main(["--agent", "builder", "--config", "v1-baseline"])
    assert "endpoint_name" in str(e.value)
    assert spy.calls == []
    assert events == ["probe"]


def test_main_validates_then_sweeps_with_defaults(monkeypatch):
    events, spy, cal = _wire(monkeypatch)
    cli.main(["--agent", "builder", "--config", "v1-baseline"])
    assert events == ["probe", "sweep"]
    assert cal == []
    (cfg, kw), = spy.calls
    assert cfg.agent_key == "builder"
    assert cfg.name == "v1-baseline"
    assert cfg.content_hash == config.v1_baseline("builder").content_hash
    assert kw["agent_key"] == "builder"
    assert kw["repeats"] == 3
    assert kw["max_workers"] == 8
    assert kw["judge_endpoint"] == judge_mod.JUDGE_ENDPOINT
    assert kw.get("case_filter") is None
    assert kw.get("render_enabled", True) is True


def test_main_passes_flags_through(monkeypatch):
    _, spy, _ = _wire(monkeypatch)
    cli.main(["--agent", "builder", "--config", "v1-baseline", "--repeats", "2",
              "--max-workers", "3", "--judge-endpoint", "judge-x", "--cases", "2,4", "--no-render"])
    (cfg, kw), = spy.calls
    assert kw["repeats"] == 2
    assert kw["max_workers"] == 3
    assert kw["judge_endpoint"] == "judge-x"
    assert list(kw["case_filter"]) == ["2", "4"]
    assert kw["render_enabled"] is False


def test_main_loads_a_yaml_config_path(monkeypatch):
    _, spy, _ = _wire(monkeypatch)
    path = case_mod.EVALS_DIR / "configs" / "builder" / "v1.yaml"
    cli.main(["--agent", "builder", "--config", str(path)])
    (cfg, kw), = spy.calls
    expected = config.load_config(path)
    assert cfg.name == expected.name == "builder-sonnet5-single-slide"
    assert cfg.content_hash == expected.content_hash
    assert kw["agent_key"] == "builder"


# ---- main: --calibrate ------------------------------------------------------

def test_calibrate_builder_passes_render_fn_and_does_not_sweep(monkeypatch, capsys):
    _, spy, cal = _wire(monkeypatch)
    monkeypatch.setattr(judge_mod, "calibrate", lambda *a, **k: cal.append((a, k)) or [
        {"case_id": "case-zz9", "reference_passed": True, "mutation_failed": True,
         "trusted": True, "reason": ""}])
    cli.main(["--agent", "builder", "--calibrate", "--judge-endpoint", "judge-x"])
    assert spy.calls == []
    (args, kw), = cal
    assert "builder" in args or kw.get("agent_key") == "builder"
    assert kw.get("model") == "judge-x"
    assert callable(kw.get("render_fn"))
    assert "case-zz9" in capsys.readouterr().out


@pytest.mark.parametrize("role", ["architect", "build_reviewer"])
def test_calibrate_non_html_role_passes_no_render_fn(monkeypatch, role):
    _, spy, cal = _wire(monkeypatch)
    cli.main(["--agent", role, "--calibrate"])
    assert spy.calls == []
    (args, kw), = cal
    assert role in args or kw.get("agent_key") == role
    assert kw.get("render_fn") is None


def test_calibrate_render_fn_renders_candidate_with_meridian_css(monkeypatch):
    _, _, cal = _wire(monkeypatch)
    cli.main(["--agent", "fixer", "--calibrate"])
    (_, kw), = cal
    render_fn = kw["render_fn"]

    seen = []
    measures = RenderMeasures(overflow_px=3.0, min_contrast=8.0, rendered=True)

    def fake_render(html, scripts="", **k):
        seen.append({"html": html, "scripts": scripts, **k})
        return measures

    monkeypatch.setattr(render_mod, "render_slide", fake_render)
    monkeypatch.setattr(cli, "render_slide", fake_render, raising=False)
    monkeypatch.setattr(mlflow_run, "render_slide", fake_render, raising=False)

    c = Case("a", "fixer", "mutation", True, "f", payload={}, reference={}, expect={})
    out = render_fn(c, {"html": "<section class='slide'>H-77</section>", "scripts": "draw77()"})
    assert out == measures
    assert len(seen) == 1
    assert seen[0]["html"] == "<section class='slide'>H-77</section>"
    assert seen[0]["scripts"] == "draw77()"
    assert seen[0]["section_css"] == case_mod.meridian_section_css()


# ---- main: --profile pins auth before any model call ------------------------

def test_main_applies_default_profile_before_probe_and_sweep(monkeypatch, profile_calls):
    events, spy, _ = _wire(monkeypatch)
    monkeypatch.setattr(cli, "apply_profile", lambda p: events.append(("profile", p)) or "https://h")
    cli.main(["--agent", "builder", "--config", "v1-baseline"])
    assert events == [("profile", "tellr-dev"), "probe", "sweep"]


def test_main_profile_flag_passes_through_and_precedes_calibrate(monkeypatch, profile_calls):
    _, _, cal = _wire(monkeypatch)
    cli.main(["--agent", "architect", "--calibrate", "--profile", "other-prof"])
    assert profile_calls == ["other-prof"]
    assert len(cal) == 1


def test_main_empty_profile_keeps_ambient_env(monkeypatch, profile_calls):
    _wire(monkeypatch)
    cli.main(["--agent", "builder", "--config", "v1-baseline", "--profile", ""])
    assert profile_calls == []


# ---- main: packs with no cases ---------------------------------------------

def test_main_agent_all_skips_empty_packs_and_sweeps_the_rest(monkeypatch, capsys):
    events, _, _ = _wire(monkeypatch)
    swept = []

    def sweep(cfg, **kw):
        if kw["agent_key"] != "builder":
            raise mlflow_run.NoCasesError(f"no cases for agent {kw['agent_key']!r}")
        swept.append(kw["agent_key"])
        return "run-b"

    monkeypatch.setattr(mlflow_run, "run_sweep", sweep)
    cli.main(["--agent", "all"])
    out = capsys.readouterr().out
    assert swept == ["builder"]
    assert "builder: run_id=run-b" in out
    assert "architect: skipped - no cases" in out


def test_main_agent_all_with_no_cases_anywhere_exits_clearly(monkeypatch):
    _wire(monkeypatch)

    def sweep(cfg, **kw):
        raise mlflow_run.NoCasesError("no cases")

    monkeypatch.setattr(mlflow_run, "run_sweep", sweep)
    with pytest.raises(SystemExit) as e:
        cli.main(["--agent", "all"])
    assert "no cases" in str(e.value)


def test_calibrate_empty_pack_prints_and_does_not_crash(monkeypatch, capsys):
    _wire(monkeypatch)  # judge.calibrate stub returns []
    cli.main(["--agent", "deck_reviewer", "--calibrate"])
    assert "no cases" in capsys.readouterr().out
