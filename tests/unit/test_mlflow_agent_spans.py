"""Tests for MLflow span policy around slide generation (Genie / agent)."""

from unittest.mock import MagicMock

import pytest

from src.core.mlflow_agent_spans import mlflow_agent_generate_spans_enabled


@pytest.fixture(autouse=True)
def clear_span_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELLR_MLFLOW_DISABLE_AGENT_SPANS", raising=False)


def test_auto_off_when_judge_direct(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_settings = MagicMock()
    mock_settings.llm_judge_backend = "direct"
    monkeypatch.setattr(
        "src.core.settings_db.get_settings", lambda: mock_settings
    )
    assert mlflow_agent_generate_spans_enabled() is False


def test_auto_on_when_judge_mlflow(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_settings = MagicMock()
    mock_settings.llm_judge_backend = "mlflow"
    monkeypatch.setattr(
        "src.core.settings_db.get_settings", lambda: mock_settings
    )
    assert mlflow_agent_generate_spans_enabled() is True


def test_env_force_off(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_settings = MagicMock()
    mock_settings.llm_judge_backend = "mlflow"
    monkeypatch.setattr(
        "src.core.settings_db.get_settings", lambda: mock_settings
    )
    monkeypatch.setenv("TELLR_MLFLOW_DISABLE_AGENT_SPANS", "1")
    assert mlflow_agent_generate_spans_enabled() is False


def test_env_force_on_despite_direct(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_settings = MagicMock()
    mock_settings.llm_judge_backend = "direct"
    monkeypatch.setattr(
        "src.core.settings_db.get_settings", lambda: mock_settings
    )
    monkeypatch.setenv("TELLR_MLFLOW_DISABLE_AGENT_SPANS", "0")
    assert mlflow_agent_generate_spans_enabled() is True


def test_auto_on_if_get_settings_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> None:
        raise RuntimeError("no db")

    monkeypatch.setattr("src.core.settings_db.get_settings", _boom)
    assert mlflow_agent_generate_spans_enabled() is True
