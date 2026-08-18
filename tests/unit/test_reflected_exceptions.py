"""F-CR-2 (SDR-4437): unexpected internal exceptions must not be reflected to clients.

Broad ``except Exception`` HTTP handlers return a generic message and log the
detail server-side. Curated narrow-except messages (ValueError/PermissionError/
domain errors) are intentionally preserved and are covered by their own tests.
"""
from unittest.mock import MagicMock

from fastapi.testclient import TestClient


def test_list_sessions_error_returns_generic_detail(monkeypatch):
    """A broad-Exception 500 handler must not echo the raw exception string."""
    from src.api.main import app
    from src.api.routes import sessions as sessions_route

    marker = "DB_SECRET_LEAK_xyz789"
    monkeypatch.setattr(sessions_route, "get_current_user", lambda: "alice@test.com")

    def _mgr():
        m = MagicMock()
        m.list_sessions.side_effect = Exception(marker)
        return m

    monkeypatch.setattr(sessions_route, "get_session_manager", _mgr)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/sessions")

    assert resp.status_code == 500
    body = resp.text
    assert marker not in body
    assert resp.json()["detail"] == "Failed to list sessions"
