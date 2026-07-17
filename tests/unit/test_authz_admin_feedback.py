"""Admin gating tests for admin.py, admin_usage.py, feedback.py reads (SDR-4437)."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from src.api.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def production(monkeypatch):
    from src.api.routes import _authz

    monkeypatch.setattr(_authz, "_is_production", lambda: True)
    monkeypatch.setattr(_authz, "get_current_user", lambda: "user@test.com")
    _authz.reset_admin_cache()
    yield _authz
    _authz.reset_admin_cache()


@pytest.fixture
def non_admin(production, monkeypatch):
    monkeypatch.setattr(production, "_admin_acl_probe", lambda user: False)


@pytest.fixture
def admin(production, monkeypatch):
    monkeypatch.setattr(production, "_admin_acl_probe", lambda user: True)


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/admin/judge-backend"),
        ("PUT", "/api/admin/judge-backend"),
        ("POST", "/api/admin/google-credentials"),
        ("GET", "/api/admin/google-credentials/status"),
        ("DELETE", "/api/admin/google-credentials"),
        ("GET", "/api/admin/usage/summary"),
        ("GET", "/api/admin/usage/daily"),
        ("GET", "/api/admin/usage/top-users"),
        ("GET", "/api/admin/usage/funnel"),
        ("GET", "/api/admin/usage/retention"),
        ("GET", "/api/admin/usage/heatmap"),
        ("GET", "/api/feedback/report/stats"),
        ("GET", "/api/feedback/list"),
        ("GET", "/api/feedback/report/summary"),
    ],
)
def test_admin_surface_403_for_non_admin(client, non_admin, method, path):
    resp = client.request(method, path)
    assert resp.status_code == 403


def test_feedback_writes_stay_open_for_non_admin(client, non_admin):
    with patch("src.api.routes.feedback.FeedbackService") as svc:
        svc.return_value.chat.return_value = {"content": "ok", "summary_ready": False}
        resp = client.post(
            "/api/feedback/chat",
            json={"messages": [{"role": "user", "content": "hello"}]},
        )
    assert resp.status_code == 200


def test_feedback_list_passes_gate_for_admin(client, admin):
    resp = client.get("/api/feedback/list")
    assert resp.status_code != 403


def test_admin_routes_bypass_in_dev(client):
    """conftest sets ENVIRONMENT=test -> require_admin bypasses (dev parity)."""
    resp = client.get("/api/feedback/list")
    assert resp.status_code != 403
