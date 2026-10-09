"""SDR-4437 LOW cleanup: dead session-export endpoint (F-CR-10) + OBO token log (F-CR-9)."""
import logging

from fastapi.testclient import TestClient


def test_session_export_route_removed():
    """F-CR-10: the unused POST /api/sessions/{id}/export (dumped full sessions,
    incl. messages, to logs/sessions/{id}.json) must no longer be registered."""
    from src.api.main import app

    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/api/sessions/{session_id}/export" not in paths


def test_obo_middleware_does_not_log_any_token_bytes(monkeypatch, caplog):
    """F-CR-9: the OBO auth middleware must not log any part (prefix) or the length
    of the bearer token."""
    from src.api import main as main_module

    def _boom(token):
        raise RuntimeError("no client in test")

    monkeypatch.setattr(main_module, "get_or_create_user_client", _boom)
    client = TestClient(main_module.app, raise_server_exceptions=False)

    marker = "SECRET_BEARER_TOKEN_abcdefghijklmnopqrstuvwxyz0123456789"
    with caplog.at_level(logging.DEBUG):
        client.get("/api/__nonexistent__", headers={"x-forwarded-access-token": marker})

    dumped = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert marker not in dumped  # full token absent
    assert marker[:20] not in dumped  # no 20-char prefix either
    assert "token_prefix" not in dumped
    assert "token_length" not in dumped


def test_create_user_client_does_not_log_any_token_bytes(monkeypatch, caplog):
    """F-CR-9: create_user_client must not log any part or length of the bearer token."""
    from src.core import databricks_client as d

    class _Me:
        user_name = "u@example.com"

    class _CurrentUser:
        def me(self):
            return _Me()

    class _FakeWorkspaceClient:
        def __init__(self, **kwargs):
            self.current_user = _CurrentUser()

    monkeypatch.setenv("DATABRICKS_HOST", "https://example.com")
    monkeypatch.setattr(d, "WorkspaceClient", _FakeWorkspaceClient)

    marker = "SECRET_BEARER_TOKEN_abcdefghijklmnopqrstuvwxyz0123456789"
    with caplog.at_level(logging.DEBUG):
        d.create_user_client(marker)

    dumped = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert marker not in dumped
    assert marker[:20] not in dumped
    assert "token_prefix" not in dumped
    assert "token_length" not in dumped
