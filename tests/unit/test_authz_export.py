"""Authorization gating tests for export.py (SDR-4437 PR-2)."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.database.models.profile_contributor import PermissionLevel


@pytest.fixture
def client():
    from src.api.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def deck_gate(monkeypatch):
    """Recording denier for the deck-permission gate."""
    calls = []

    def gate(session_id, min_permission=PermissionLevel.CAN_VIEW):
        calls.append((session_id, min_permission))
        raise HTTPException(status_code=403, detail="denied")

    monkeypatch.setattr(
        "src.api.routes.export._check_deck_permission_for_session", gate
    )
    return calls


@pytest.fixture
def job_gate(monkeypatch):
    calls = []

    def gate(job_id, min_permission=PermissionLevel.CAN_VIEW):
        calls.append((job_id, min_permission))
        raise HTTPException(status_code=403, detail="denied")

    monkeypatch.setattr(
        "src.api.routes.export._require_export_job_access", gate
    )
    return calls


def test_export_pptx_gated_can_view(client, deck_gate, monkeypatch):
    svc = MagicMock()
    monkeypatch.setattr(
        "src.api.routes.export.get_chat_service", lambda: svc
    )
    resp = client.post("/api/export/pptx", json={"session_id": "s1"})
    assert resp.status_code == 403
    assert deck_gate == [("s1", PermissionLevel.CAN_VIEW)]
    svc.get_slides.assert_not_called()  # gate fires before deck access


def test_export_pptx_async_gated_can_view(client, deck_gate):
    resp = client.post("/api/export/pptx/async", json={"session_id": "s2"})
    assert resp.status_code == 403
    assert deck_gate == [("s2", PermissionLevel.CAN_VIEW)]


def test_export_pptx_editable_gated_can_view(client, deck_gate):
    resp = client.post("/api/export/pptx/editable", json={"session_id": "s3"})
    assert resp.status_code == 403
    assert deck_gate == [("s3", PermissionLevel.CAN_VIEW)]


def test_export_huashu_from_html_gated_can_view(client, deck_gate):
    resp = client.post(
        "/api/export/pptx/editable/huashu/from-html", json={"session_id": "s4"}
    )
    assert resp.status_code == 403
    assert deck_gate == [("s4", PermissionLevel.CAN_VIEW)]


def test_from_records_gated_when_session_id_present(client, deck_gate):
    resp = client.post(
        "/api/export/pptx/editable/from-records",
        json={"session_id": "s5", "slides": []},
    )
    assert resp.status_code == 403
    assert deck_gate == [("s5", PermissionLevel.CAN_VIEW)]


def test_from_records_open_without_session_id(client, deck_gate):
    # Downstream conversion may 4xx/5xx in this harness; the assertions that
    # matter are: no 403 from the gate, and the gate was never invoked.
    resp = client.post(
        "/api/export/pptx/editable/from-records", json={"slides": []}
    )
    assert resp.status_code != 403
    assert deck_gate == []


def test_from_images_gated_when_session_id_present(client, deck_gate):
    resp = client.post(
        "/api/export/pptx/editable/from-images",
        json={"session_id": "s6", "images": []},
    )
    assert resp.status_code == 403
    assert deck_gate == [("s6", PermissionLevel.CAN_VIEW)]


def test_poll_pptx_export_gated_by_job(client, job_gate):
    resp = client.get("/api/export/pptx/poll/job-1")
    assert resp.status_code == 403
    assert job_gate == [("job-1", PermissionLevel.CAN_VIEW)]


def test_download_pptx_export_gated_by_job(client, job_gate):
    resp = client.get("/api/export/pptx/download/job-1")
    assert resp.status_code == 403
    assert job_gate == [("job-1", PermissionLevel.CAN_VIEW)]


def test_editable_available_stays_open(client, deck_gate):
    resp = client.get("/api/export/pptx/editable/available")
    assert resp.status_code == 200
    assert deck_gate == []


# --- MEDIUM-1: huashu diagnostics ------------------------------------------


@pytest.fixture
def production_non_admin(monkeypatch):
    from src.api.routes import _authz

    monkeypatch.setattr(_authz, "_is_production", lambda: True)
    monkeypatch.setattr(_authz, "get_current_user", lambda: "user@test.com")
    monkeypatch.setattr(_authz, "_admin_acl_probe", lambda user: False)
    _authz.reset_admin_cache()
    yield
    _authz.reset_admin_cache()


def test_huashu_available_requires_admin(client, production_non_admin):
    assert client.get("/api/export/pptx/editable/huashu/available").status_code == 403


def test_huashu_install_chromium_requires_admin(client, production_non_admin):
    assert client.post("/api/export/pptx/editable/huashu/install-chromium").status_code == 403


def test_huashu_probe_launch_requires_admin(client, production_non_admin):
    assert client.post("/api/export/pptx/editable/huashu/probe-launch").status_code == 403


def test_huashu_available_response_is_slim(client):
    """MEDIUM-1: no env/filesystem/log detail in the response body."""
    resp = client.get("/api/export/pptx/editable/huashu/available")
    assert resp.status_code == 200
    body = resp.json()
    leak_keys = {
        "home", "sidecar_dir", "chromium_cache_paths", "cache_root_listing",
        "setup_log_tail", "setup_log_size", "setup_log_path_exists",
        "tmp_listing", "playwright_dir_listing", "playwright_core_dir_listing",
        "playwright_browsers_path_env", "environment", "databricks_app_name",
    }
    assert not leak_keys & set(body.get("checks", {}).keys())
    assert "available" in body
