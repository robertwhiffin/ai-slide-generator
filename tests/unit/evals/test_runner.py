"""Failing tests for Task 3: thread-safe Runner over run_candidate.

These tests are RED until evals/harness/runner.py is implemented.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import src.core.database  # break import cycle before any src.services import  # noqa: F401

from evals.harness import config, runner


class _StubAdapter:
    """Returns a valid structured output per role without a network call."""

    def __init__(self):
        self.calls = 0
        self._lock = threading.Lock()

    def invoke(self, *, agent_key, configuration, schema, prompt):
        with self._lock:
            self.calls += 1
        return _valid_output_for(schema)  # build a minimal valid instance of the schema


def _valid_output_for(schema):
    from src.domain.skill_io import BuilderOutput

    if schema.__name__.startswith("Builder") or issubclass(schema, BuilderOutput):
        return schema(position=1, html="<section class='slide'><h1>x</h1></section>", scripts="")
    raise AssertionError(f"add a builder for {schema.__name__}")


class Boom:
    def invoke(self, **k):
        from src.services.agent_runtime import ModelProviderUnavailableError

        raise ModelProviderUnavailableError("429 throttled")


# ---------------------------------------------------------------------------
# The concrete builder payload used across all three tests
# ---------------------------------------------------------------------------

_BUILDER_PAYLOAD = {
    "position": 1,
    "slide_spec": {"position": 1, "title": "t", "purpose": "p"},
    "assumes": [],
    "hands_off": [],
    "resolved_data": {"synthesis": "", "figures": [], "gaps": []},
    "section_html": "",
    "section_css": ".slide{}",
    "resolved_style": "x",
    "design_system_active": True,
}


def test_runner_returns_structured_output_for_a_builder_config():
    r = runner.Runner(model_adapter=_StubAdapter())
    cfg = config.v1_baseline("builder")
    payload = {
        "position": 1,
        "slide_spec": {"position": 1, "title": "t", "purpose": "p"},
        "assumes": [],
        "hands_off": [],
        "resolved_data": {"synthesis": "", "figures": [], "gaps": []},
        "section_html": "",
        "section_css": ".slide{}",
        "resolved_style": "x",
        "design_system_active": True,
    }
    res = r.run(cfg, payload, design_system_active=True)
    assert res.status == "completed"
    assert "slide" in res.structured["html"]
    assert res.infra_error is False


def test_concurrent_runs_do_not_interfere():
    r = runner.Runner(model_adapter=_StubAdapter())
    cfg = config.v1_baseline("builder")
    payload = {
        "position": 1,
        "slide_spec": {"position": 1, "title": "t", "purpose": "p"},
        "assumes": [],
        "hands_off": [],
        "resolved_data": {"synthesis": "", "figures": [], "gaps": []},
        "section_html": "",
        "section_css": ".slide{}",
        "resolved_style": "x",
        "design_system_active": True,
    }
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda _: r.run(cfg, payload, design_system_active=True), range(32)))
    assert all(x.status == "completed" for x in results)


def test_persistent_provider_failure_is_marked_infra_error_not_counted():
    r = runner.Runner(model_adapter=Boom(), max_infra_retries=1)
    payload = {
        "position": 1,
        "slide_spec": {"position": 1, "title": "t", "purpose": "p"},
        "assumes": [],
        "hands_off": [],
        "resolved_data": {"synthesis": "", "figures": [], "gaps": []},
        "section_html": "",
        "section_css": ".slide{}",
        "resolved_style": "x",
        "design_system_active": True,
    }
    res = r.run(config.v1_baseline("builder"), payload, design_system_active=True)
    assert res.infra_error is True
    assert res.status != "completed"
