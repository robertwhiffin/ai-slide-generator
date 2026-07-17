"""HIGH-6 regression tests: get_user_client() fails closed in production.

The chat path spawns the agent and title-gen threads via
contextvars.copy_context() (chat_service.py:1041/1102) — that dependency is
what the two thread tests pin down.
"""

import contextvars
import threading
from unittest.mock import MagicMock

import pytest

from src.core.databricks_client import (
    get_user_client,
    reset_user_client,
    set_user_client,
)


@pytest.fixture(autouse=True)
def _cleanup():
    reset_user_client()
    yield
    reset_user_client()


def test_error_class_exists():
    from src.core.databricks_client import UserClientRequiredError

    assert issubclass(UserClientRequiredError, Exception)


def test_raises_in_production_when_unbound(monkeypatch):
    from src.core.databricks_client import UserClientRequiredError

    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(UserClientRequiredError):
        get_user_client()


def test_returns_bound_client_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    client = MagicMock()
    set_user_client(client)
    assert get_user_client() is client


def test_falls_back_to_system_client_outside_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    fake_system = object()
    monkeypatch.setattr(
        "src.core.databricks_client.get_system_client", lambda: fake_system
    )
    assert get_user_client() is fake_system


def test_thread_without_context_propagation_raises(monkeypatch):
    """A thread spawned WITHOUT copy_context must fail closed, not run as SP."""
    from src.core.databricks_client import UserClientRequiredError

    monkeypatch.setenv("ENVIRONMENT", "production")
    set_user_client(MagicMock())  # bound on the spawning thread only
    outcome = {}

    def worker():
        try:
            get_user_client()
            outcome["result"] = "resolved"
        except UserClientRequiredError:
            outcome["result"] = "raised"

    t = threading.Thread(target=worker)  # threading.Thread does NOT copy context
    t.start()
    t.join()
    assert outcome["result"] == "raised"


def test_thread_with_copy_context_resolves(monkeypatch):
    """The chat-path pattern (copy_context) keeps working after the change."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    client = MagicMock()
    set_user_client(client)
    ctx = contextvars.copy_context()
    outcome = {}

    def worker():
        outcome["client"] = ctx.run(get_user_client)

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert outcome["client"] is client


# ---------------------------------------------------------------------------
# 401 mapping in main.py
# ---------------------------------------------------------------------------


def test_exception_handler_registered_on_app():
    from src.api.main import app
    from src.core.databricks_client import UserClientRequiredError

    assert UserClientRequiredError in app.exception_handlers


@pytest.mark.asyncio
async def test_exception_handler_returns_401_reauthenticate():
    from src.api.main import user_client_required_handler
    from src.core.databricks_client import UserClientRequiredError

    resp = await user_client_required_handler(
        MagicMock(), UserClientRequiredError("no client")
    )
    assert resp.status_code == 401
    assert b"re-authenticate" in resp.body
