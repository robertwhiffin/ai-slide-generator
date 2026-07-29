"""HIGH-3: workspace-global prompt/style libraries admin-gated (SDR-4437)."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from src.api.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def non_admin(monkeypatch):
    from src.api.routes import _authz

    monkeypatch.setattr(_authz, "_is_production", lambda: True)
    monkeypatch.setattr(_authz, "get_current_user", lambda: "user@test.com")
    monkeypatch.setattr(_authz, "_admin_acl_probe", lambda user: False)
    _authz.reset_admin_cache()
    yield
    _authz.reset_admin_cache()


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("POST", "/api/settings/deck-prompts", {"name": "x", "prompt_content": "y"}),
        ("PUT", "/api/settings/deck-prompts/1", {"name": "x"}),
        ("DELETE", "/api/settings/deck-prompts/1", None),
        ("POST", "/api/settings/slide-styles", None),  # body irrelevant: gate fires first
        ("PUT", "/api/settings/slide-styles/1", None),
        ("DELETE", "/api/settings/slide-styles/1", None),
        ("POST", "/api/settings/slide-styles/1/set-default", None),
    ],
)
def test_library_writes_403_for_non_admin(client, non_admin, method, path, body):
    resp = client.request(method, path, json=body)
    assert resp.status_code == 403


@pytest.mark.parametrize(
    "path", ["/api/settings/deck-prompts", "/api/settings/slide-styles"]
)
def test_library_reads_stay_open(client, non_admin, path):
    resp = client.get(path)
    assert resp.status_code != 403
