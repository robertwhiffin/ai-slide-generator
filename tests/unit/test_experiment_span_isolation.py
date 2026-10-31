"""A generate span is attributed to its own session's experiment under concurrent jobs.

``mlflow.set_experiment`` sets a PROCESS-GLOBAL active experiment, and MLflow takes a
trace's experiment when its root span starts (``MlflowV3SpanProcessor._start_trace`` →
``get_experiment_id_for_trace`` → ``_get_experiment_id()``, mlflow 3.14).  Several chat
jobs now run in one process (``TELLR_CHAT_JOB_CONCURRENCY``), so between one job's
``set_experiment`` and its span start another job could switch the experiment and the
first user's trace would land in the second user's experiment.

``start_span_in_experiment`` holds a process lock from ``set_experiment`` until the span
has started.  These tests model MLflow exactly as above: a global active experiment, and
a span that captures whichever experiment is active when it is entered.

SABOTAGE: drop the lock in ``start_span_in_experiment`` -> the interleaving test goes red.
Revert either agent call site to ``mlflow.set_experiment`` + ``mlflow.start_span`` -> the
call-site guard goes red.
"""

import inspect
import threading
import time
from contextlib import contextmanager
from unittest.mock import patch

from src.core import mlflow_tracing
from src.services.agent import SlideGeneratorAgent


class _FakeMlflow:
    """A process-global active experiment, set slowly, captured at span start."""

    def __init__(self) -> None:
        self.active = None
        self.captured: dict[str, str] = {}

    def set_experiment(self, experiment_id=None, **_):
        self.active = experiment_id
        time.sleep(0.05)  # the real call is a REST round trip

    def start_span(self, name):
        fake = self

        @contextmanager
        def cm():
            fake.captured[name] = fake.active
            yield object()

        return cm()


def test_each_span_keeps_its_own_experiment_when_two_jobs_interleave():
    fake = _FakeMlflow()
    errors: list[BaseException] = []

    def job(name: str, experiment: str, delay: float) -> None:
        try:
            time.sleep(delay)
            with mlflow_tracing.start_span_in_experiment(name, experiment):
                time.sleep(0.05)
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    with (
        patch.object(mlflow_tracing.mlflow, "set_experiment", fake.set_experiment),
        patch.object(mlflow_tracing.mlflow, "start_span", fake.start_span),
    ):
        a = threading.Thread(target=job, args=("span-a", "exp-a", 0.0))
        b = threading.Thread(target=job, args=("span-b", "exp-b", 0.01))
        a.start()
        b.start()
        a.join(5)
        b.join(5)

    assert not errors, errors
    assert fake.captured == {"span-a": "exp-a", "span-b": "exp-b"}


def test_the_span_body_runs_outside_the_lock():
    """Only the set-and-start pair is serialised; a long generation does not block others."""
    fake = _FakeMlflow()
    with (
        patch.object(mlflow_tracing.mlflow, "set_experiment", fake.set_experiment),
        patch.object(mlflow_tracing.mlflow, "start_span", fake.start_span),
    ):
        with mlflow_tracing.start_span_in_experiment("outer", "exp-a"):
            assert mlflow_tracing.mlflow_experiment_lock().acquire(timeout=1)
            mlflow_tracing.mlflow_experiment_lock().release()


def test_an_error_in_the_body_still_closes_the_span():
    exited: list[object] = []

    def start_span(name):
        @contextmanager
        def cm():
            try:
                yield object()
            finally:
                exited.append(name)

        return cm()

    with (
        patch.object(mlflow_tracing.mlflow, "set_experiment", lambda **_: None),
        patch.object(mlflow_tracing.mlflow, "start_span", start_span),
    ):
        try:
            with mlflow_tracing.start_span_in_experiment("boom", "exp-a"):
                raise RuntimeError("model down")
        except RuntimeError:
            pass
    assert exited == ["boom"]


def test_both_agent_generate_paths_open_their_span_through_the_helper():
    agent = SlideGeneratorAgent
    for method in (agent.generate_slides, agent.generate_slides_streaming):
        source = inspect.getsource(method)
        assert "start_span_in_experiment(" in source, method.__name__
        assert "mlflow.start_span(" not in source, method.__name__
        assert "mlflow.set_experiment(" not in source, method.__name__


def test_set_experiment_is_called_only_under_the_experiment_lock():
    """One unlocked set_experiment anywhere defeats the lock everywhere: it can move the
    global during another thread's locked span start or judge evaluation.  Only the two
    locked helpers may call it."""
    import ast
    from pathlib import Path

    allowed = {
        ("src/core/mlflow_tracing.py", "start_span_in_experiment"),
        ("src/services/evaluation/llm_judge.py", "_evaluate_in_experiment"),
    }
    found = set()
    for path in Path("src").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(func):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "set_experiment"
                ):
                    found.add((str(path), func.name))
    assert found <= allowed, f"set_experiment outside the lock: {sorted(found - allowed)}"
