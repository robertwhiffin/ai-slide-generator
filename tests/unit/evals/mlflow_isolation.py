"""End any MLflow run a previous test left active in this worker.

Production code calls MLflow's fluent API outside any run (for example the safety
gate's ``mlflow.log_param("safety_gate_retry", ...)`` in ``src/services/agent.py``),
and the fluent API then starts a run that nothing ends.  Under pytest-xdist the
next eval-harness test on that worker that calls ``mlflow.start_run`` fails with
"Run ... is already active", depending only on how tests were distributed.

``mlflow.end_run`` pops the run off the thread's active-run stack before it marks
the run terminated, so even when terminating fails (the run's store is gone
because a later test moved the tracking URI), the stray run is no longer active.
"""

import mlflow


def end_stray_runs() -> None:
    """End every active fluent MLflow run in this thread; never raise."""
    while mlflow.active_run() is not None:
        try:
            mlflow.end_run()
        except Exception:  # noqa: BLE001 - the run is already off the stack
            pass
