"""The eval-harness tests start from no active MLflow run (see ``mlflow_isolation``)."""

import mlflow
import pytest

from tests.unit.evals.mlflow_isolation import end_stray_runs


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A throwaway tracking store; the previous tracking URI is restored after."""
    prev = mlflow.get_tracking_uri()
    monkeypatch.chdir(tmp_path)
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path / 'a.db'}")
    yield tmp_path
    end_stray_runs()
    mlflow.set_tracking_uri(prev)


def test_a_stray_run_is_ended(store):
    mlflow.log_param("stray", "1")  # the fluent API starts a run nothing ends
    assert mlflow.active_run() is not None

    end_stray_runs()

    assert mlflow.active_run() is None


def test_a_stray_run_whose_store_moved_is_still_cleared(store):
    """The failure seen under xdist: the stray run lives in a store the next test
    no longer points at, so ending it raises "Run ... not found"."""
    mlflow.log_param("stray", "1")
    mlflow.set_tracking_uri(f"sqlite:///{store / 'b.db'}")

    end_stray_runs()  # must not raise

    assert mlflow.active_run() is None
    with mlflow.start_run():  # the next test's sweep can start its own run
        pass
