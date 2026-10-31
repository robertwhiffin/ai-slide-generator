"""The MLflow judge's evaluation run stays in its own session's experiment.

``evaluate_with_judge`` (slide verification) calls ``mlflow.set_experiment`` and then
``mlflow.genai.evaluate``, which reads the PROCESS-GLOBAL active experiment while it
runs (mlflow 3.14 ``genai/evaluation/harness.py``, ``base.py``), on worker threads too.
With several chat jobs per process, another user's turn could set the experiment
mid-evaluation and this user's evaluation run (slide HTML, Genie rows) would land in
that user's experiment.  The judge holds ``mlflow_experiment_lock()`` from
``set_experiment`` until ``evaluate`` returns, and never awaits under it.

SABOTAGE: move ``evaluate`` outside the lock (or drop the lock) -> the interleaving test
goes red.  Await the direct fallback while holding the lock -> the fallback test hangs
and fails on its timeout.
"""

import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from src.core import mlflow_tracing
from src.services.evaluation import llm_judge

FALLBACK_CHECK = "_mlflow_evaluate_should_use_direct_fallback"


class _FakeMlflow:
    def __init__(self) -> None:
        self.active = None
        self.captured: dict[str, str] = {}

    def set_experiment(self, experiment_id=None, **_):
        self.active = experiment_id
        time.sleep(0.02)

    def start_span(self, name):
        from contextlib import contextmanager

        fake = self

        @contextmanager
        def cm():
            fake.captured[name] = fake.active
            yield object()

        return cm()

    def evaluate(self, data=None, scorers=None):
        time.sleep(0.15)  # the judge call; MLflow reads the active experiment late
        self.captured["judge"] = self.active
        df = pd.DataFrame([{"numerical_accuracy/value": "correct", "trace_id": "tr-1"}])
        return SimpleNamespace(run_id="run-1", result_df=df)


def _patched(fake):
    import mlflow
    import mlflow.genai

    return [
        patch.object(mlflow, "set_experiment", fake.set_experiment),
        patch.object(mlflow, "set_tracking_uri", lambda *_a, **_k: None),
        patch.object(mlflow.genai, "evaluate", fake.evaluate),
        patch.object(mlflow.genai, "make_judge", lambda **_k: object()),
        patch.object(mlflow_tracing.mlflow, "start_span", fake.start_span),
        patch.object(llm_judge, "configure_tracing_environment", lambda: None),
    ]


def _judge(experiment_id: str):
    return asyncio.run(
        llm_judge.evaluate_with_judge(
            genie_data="a,b\n1,2",
            slide_content="<div>1</div>",
            experiment_id=experiment_id,
            judge_backend="mlflow",
        )
    )


def test_a_concurrent_turn_cannot_move_the_judges_evaluation_run():
    fake = _FakeMlflow()
    results: dict[str, object] = {}

    def judge():
        results["judge"] = _judge("exp-judge")

    def turn():
        time.sleep(0.05)  # starts while the judge is evaluating
        with mlflow_tracing.start_span_in_experiment("turn-span", "exp-turn"):
            pass

    patches = _patched(fake)
    for p in patches:
        p.start()
    try:
        a = threading.Thread(target=judge)
        b = threading.Thread(target=turn)
        a.start()
        b.start()
        a.join(5)
        b.join(5)
    finally:
        for p in patches:
            p.stop()

    assert fake.captured == {"judge": "exp-judge", "turn-span": "exp-turn"}
    assert results["judge"].run_id == "run-1"


def test_the_direct_fallback_runs_after_the_lock_is_released():
    """The fallback awaits; awaiting under a threading.Lock could deadlock the loop."""
    fake = _FakeMlflow()

    def failing_evaluate(**_):
        raise RuntimeError("egress blocked")

    seen_lock_free: list[bool] = []

    def direct(*args):
        lock = mlflow_tracing.mlflow_experiment_lock()
        got = lock.acquire(timeout=1)
        if got:
            lock.release()
        seen_lock_free.append(got)
        return SimpleNamespace(run_id=None, score=0)

    patches = _patched(fake)
    import mlflow.genai

    patches.append(patch.object(mlflow.genai, "evaluate", failing_evaluate))
    use_fallback = patch.object(llm_judge, FALLBACK_CHECK, lambda e: True)
    patches.append(use_fallback)
    patches.append(patch.object(llm_judge, "_evaluate_with_judge_direct_llm", direct))
    for p in patches:
        p.start()
    try:
        result = _judge("exp-judge")
    finally:
        for p in patches:
            p.stop()

    assert seen_lock_free == [True]
    assert result.run_id is None


def test_a_non_fallback_error_still_propagates():
    fake = _FakeMlflow()

    def failing_evaluate(**_):
        raise ValueError("bad data")

    patches = _patched(fake)
    import mlflow.genai

    patches.append(patch.object(mlflow.genai, "evaluate", failing_evaluate))
    no_fallback = patch.object(llm_judge, FALLBACK_CHECK, lambda e: False)
    patches.append(no_fallback)
    for p in patches:
        p.start()
    try:
        result = _judge("exp-judge")
    finally:
        for p in patches:
            p.stop()

    # evaluate_with_judge reports judge failures as an error result, never raises.
    assert result.error is True
    assert mlflow_tracing.mlflow_experiment_lock().acquire(timeout=1)
    mlflow_tracing.mlflow_experiment_lock().release()
