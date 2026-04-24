"""Tests for Unity Catalog MLflow trace configuration helpers."""
import os
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def clear_uc_env(monkeypatch):
    """Avoid cross-test env leakage."""
    for key in (
        "TELLR_MLFLOW_UC_CATALOG",
        "TELLR_MLFLOW_UC_SCHEMA",
        "TELLR_MLFLOW_UC_TABLE_PREFIX",
        "MLFLOW_TRACING_SQL_WAREHOUSE_ID",
        "TELLR_MLFLOW_SQL_WAREHOUSE_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    yield


def _reset_uc_cache():
    import src.core.mlflow_tracing as mt

    mt._unity_catalog_cls = None  # type: ignore[attr-defined]


def test_get_unity_catalog_trace_location_returns_none_without_env():
    _reset_uc_cache()
    from src.core.mlflow_tracing import get_unity_catalog_trace_location

    assert get_unity_catalog_trace_location() is None


def test_configure_tracing_environment_aliases_warehouse_id(monkeypatch):
    monkeypatch.setenv("TELLR_MLFLOW_SQL_WAREHOUSE_ID", "wh-123")
    from src.core.mlflow_tracing import configure_tracing_environment

    configure_tracing_environment()
    assert os.environ.get("MLFLOW_TRACING_SQL_WAREHOUSE_ID") == "wh-123"


@patch("mlflow.create_experiment", return_value="exp-uc")
def test_create_databricks_experiment_uses_uc_when_env_complete(mock_ce, monkeypatch):
    _reset_uc_cache()
    monkeypatch.setenv("TELLR_MLFLOW_UC_CATALOG", "main")
    monkeypatch.setenv("TELLR_MLFLOW_UC_SCHEMA", "mlflow_traces")
    monkeypatch.setenv("TELLR_MLFLOW_UC_TABLE_PREFIX", "tellr_otel")
    monkeypatch.setenv("MLFLOW_TRACING_SQL_WAREHOUSE_ID", "wh-999")

    trace_loc = MagicMock()
    with patch(
        "mlflow.entities.trace_location.UnityCatalog",
        return_value=trace_loc,
    ):
        from src.core.mlflow_tracing import create_databricks_experiment

        eid = create_databricks_experiment("/Workspace/Users/u/exp")
        assert eid == "exp-uc"
        mock_ce.assert_called_once_with(
            name="/Workspace/Users/u/exp",
            trace_location=trace_loc,
        )


@patch("mlflow.create_experiment", return_value="exp-plain")
def test_create_databricks_experiment_plain_without_uc(mock_ce, monkeypatch):
    _reset_uc_cache()
    from src.core.mlflow_tracing import create_databricks_experiment

    eid = create_databricks_experiment("/Workspace/Users/u/exp")
    assert eid == "exp-plain"
    mock_ce.assert_called_once_with("/Workspace/Users/u/exp")


def test_create_databricks_experiment_falls_back_when_otel_collector_unavailable(
    monkeypatch,
):
    """UC linking can fail when OpenTelemetry Collector is not enabled for the workspace."""
    _reset_uc_cache()
    monkeypatch.setenv("TELLR_MLFLOW_UC_CATALOG", "main")
    monkeypatch.setenv("TELLR_MLFLOW_UC_SCHEMA", "s")
    monkeypatch.setenv("TELLR_MLFLOW_UC_TABLE_PREFIX", "p")
    monkeypatch.setenv("MLFLOW_TRACING_SQL_WAREHOUSE_ID", "wh-1")

    trace_loc = MagicMock()
    otel_err = RuntimeError(
        'Experiment "/x" (ID: 99) was created but linking to trace location '
        "'main.s.p' failed: ENDPOINT_NOT_FOUND: The \"OpenTelemetry Collector for Delta Tables\" "
        "is unavailable in your workspace."
    )

    def create_side_effect(name, trace_location=None):
        if trace_location is not None:
            raise otel_err
        return "fallback-id"

    with patch(
        "mlflow.entities.trace_location.UnityCatalog",
        return_value=trace_loc,
    ):
        with patch("mlflow.create_experiment", side_effect=create_side_effect):
            with patch("mlflow.get_experiment_by_name", return_value=None):
                from src.core.mlflow_tracing import create_databricks_experiment

                eid = create_databricks_experiment("/Workspace/Users/u/exp")
                assert eid == "fallback-id"


def test_create_databricks_experiment_falls_back_reuses_partial_experiment(monkeypatch):
    _reset_uc_cache()
    monkeypatch.setenv("TELLR_MLFLOW_UC_CATALOG", "main")
    monkeypatch.setenv("TELLR_MLFLOW_UC_SCHEMA", "s")
    monkeypatch.setenv("TELLR_MLFLOW_UC_TABLE_PREFIX", "p")
    monkeypatch.setenv("MLFLOW_TRACING_SQL_WAREHOUSE_ID", "wh-1")

    trace_loc = MagicMock()
    otel_err = RuntimeError(
        "ENDPOINT_NOT_FOUND: The \"OpenTelemetry Collector for Delta Tables\" is unavailable."
    )
    partial = MagicMock()
    partial.experiment_id = "111"

    def create_side_effect(name, trace_location=None):
        if trace_location is not None:
            raise otel_err
        raise AssertionError("should reuse existing")

    with patch("mlflow.entities.trace_location.UnityCatalog", return_value=trace_loc):
        with patch("mlflow.create_experiment", side_effect=create_side_effect):
            with patch(
                "mlflow.get_experiment_by_name",
                return_value=partial,
            ):
                from src.core.mlflow_tracing import create_databricks_experiment

                eid = create_databricks_experiment("/Workspace/Users/u/exp")
                assert eid == "111"
