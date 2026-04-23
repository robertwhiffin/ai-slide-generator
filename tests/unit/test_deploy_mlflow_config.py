"""Tests for MLflow UC tracing resolution in deploy.py."""

from __future__ import annotations

import pytest

from databricks_tellr.deploy import (
    _mlflow_flat_from_env_section,
    _mlflow_substitutions_for_app_yaml,
)


def test_mlflow_flat_from_nested_block() -> None:
    env = {
        "mlflow_tracing": {
            "sql_warehouse_id": "wh-1",
            "uc_catalog": "main",
            "uc_schema": "s",
            "uc_table_prefix": "p",
        }
    }
    flat = _mlflow_flat_from_env_section(env)
    assert flat["mlflow_tracing_sql_warehouse_id"] == "wh-1"
    assert flat["tellr_mlflow_uc_catalog"] == "main"
    assert flat["tellr_mlflow_uc_schema"] == "s"
    assert flat["tellr_mlflow_uc_table_prefix"] == "p"


def test_mlflow_flat_from_top_level_keys() -> None:
    env = {
        "mlflow_tracing_sql_warehouse_id": "wh-2",
        "tellr_mlflow_uc_catalog": "cat",
    }
    flat = _mlflow_flat_from_env_section(env)
    assert flat["mlflow_tracing_sql_warehouse_id"] == "wh-2"
    assert flat["tellr_mlflow_uc_catalog"] == "cat"
    assert flat["tellr_mlflow_uc_schema"] == ""
    assert flat["tellr_mlflow_uc_table_prefix"] == ""


def test_mlflow_nested_overrides_top_level_for_warehouse() -> None:
    env = {
        "mlflow_tracing_sql_warehouse_id": "ignored",
        "mlflow_tracing": {"sql_warehouse_id": "from-nested"},
    }
    flat = _mlflow_flat_from_env_section(env)
    assert flat["mlflow_tracing_sql_warehouse_id"] == "from-nested"


def test_substitutions_precedence_override_over_yaml_over_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELLR_DEPLOY_MLFLOW_UC_CATALOG", "from-env")
    deployment = {"tellr_mlflow_uc_catalog": "from-yaml"}
    overrides = {"TELLR_MLFLOW_UC_CATALOG": "from-override"}
    out = _mlflow_substitutions_for_app_yaml(
        deployment_flat=deployment,
        overrides=overrides,
    )
    assert out["TELLR_MLFLOW_UC_CATALOG"] == "from-override"
    assert out["TELLR_MLFLOW_UC_SCHEMA"] == ""


def test_substitutions_yaml_before_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELLR_DEPLOY_MLFLOW_UC_SCHEMA", "env-schema")
    out = _mlflow_substitutions_for_app_yaml(
        deployment_flat={"tellr_mlflow_uc_schema": "yaml-schema"},
        overrides={},
    )
    assert out["TELLR_MLFLOW_UC_SCHEMA"] == "yaml-schema"


def test_substitutions_env_when_no_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELLR_DEPLOY_MLFLOW_TRACING_SQL_WAREHOUSE_ID", "w-env")
    out = _mlflow_substitutions_for_app_yaml(deployment_flat={}, overrides={})
    assert out["MLFLOW_TRACING_SQL_WAREHOUSE_ID"] == "w-env"
