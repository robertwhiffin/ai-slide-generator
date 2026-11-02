"""Autologging is explicitly disabled at startup unless TELLR_MLFLOW_LANGCHAIN_AUTOLOG opts in.

``mlflow.genai.evaluate`` (slide verification) temporarily enables tracing autolog for
every flavour that is not EXPLICITLY disabled, process-wide (mlflow 3.14
``models/evaluation/utils/trace.py`` ``configure_autologging_for_evaluation``).  While a
verification ran, every other chat turn's LangChain calls in the process became root
traces in the global active experiment: the verifying user's.  Several chat jobs now
share a process, so that is likelier.  Disabling every flavour explicitly at startup
makes evaluate leave them alone.

SABOTAGE: drop the call from the lifespan -> the lifespan test goes red; disable even
when opted in -> the opt-in test goes red.
"""

import inspect
from unittest.mock import patch

import pytest

from src.api import main
from src.core import mlflow_tracing


@pytest.mark.parametrize("flag", [None, "", "0", "off"])
def test_autolog_is_disabled_unless_opted_in(monkeypatch, flag):
    if flag is None:
        monkeypatch.delenv("TELLR_MLFLOW_LANGCHAIN_AUTOLOG", raising=False)
    else:
        monkeypatch.setenv("TELLR_MLFLOW_LANGCHAIN_AUTOLOG", flag)
    with patch.object(mlflow_tracing.mlflow, "autolog") as autolog:
        assert mlflow_tracing.disable_autologging_unless_opted_in() is True
    autolog.assert_called_once_with(disable=True)


@pytest.mark.parametrize("flag", ["1", "true", "on"])
def test_an_opted_in_deployment_keeps_autolog(monkeypatch, flag):
    monkeypatch.setenv("TELLR_MLFLOW_LANGCHAIN_AUTOLOG", flag)
    with patch.object(mlflow_tracing.mlflow, "autolog") as autolog:
        assert mlflow_tracing.disable_autologging_unless_opted_in() is False
    autolog.assert_not_called()


def test_a_failure_to_disable_never_stops_startup(monkeypatch):
    monkeypatch.delenv("TELLR_MLFLOW_LANGCHAIN_AUTOLOG", raising=False)
    with patch.object(mlflow_tracing.mlflow, "autolog", side_effect=RuntimeError("no flavour")):
        assert mlflow_tracing.disable_autologging_unless_opted_in() is False


def test_every_worker_disables_autolog_at_startup():
    source = inspect.getsource(main.lifespan)
    assert "disable_autologging_unless_opted_in()" in source
