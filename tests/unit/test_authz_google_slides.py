"""Authorization gating tests for google_slides.py (SDR-4437 PR-2)."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.database.models.profile_contributor import PermissionLevel

BASE = "/api/export/google-slides"


@pytest.fixture
def client():
    from src.api.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def deck_gate(monkeypatch):
    calls = []

    def gate(session_id, min_permission=PermissionLevel.CAN_VIEW):
        calls.append((session_id, min_permission))
        raise HTTPException(status_code=403, detail="denied")

    monkeypatch.setattr(
        "src.api.routes.google_slides._check_deck_permission_for_session", gate
    )
    return calls


def test_export_gated_can_view(client, deck_gate):
    resp = client.post(BASE, json={"session_id": "s1"})
    assert resp.status_code == 403
    assert deck_gate == [("s1", PermissionLevel.CAN_VIEW)]


def test_from_records_gated_can_view(client, deck_gate):
    resp = client.post(
        f"{BASE}/from-records",
        json={"session_id": "s2", "title": "t", "slides": []},
    )
    assert resp.status_code == 403
    assert deck_gate == [("s2", PermissionLevel.CAN_VIEW)]


def test_from_huashu_gated_can_view(client, deck_gate):
    resp = client.post(f"{BASE}/from-huashu", json={"session_id": "s3"})
    assert resp.status_code == 403
    assert deck_gate == [("s3", PermissionLevel.CAN_VIEW)]


def test_poll_gated_by_job(client, monkeypatch):
    calls = []

    def gate(job_id, min_permission=PermissionLevel.CAN_VIEW):
        calls.append((job_id, min_permission))
        raise HTTPException(status_code=403, detail="denied")

    monkeypatch.setattr(
        "src.api.routes.google_slides._require_export_job_access", gate
    )
    resp = client.get(f"{BASE}/poll/job-9")
    assert resp.status_code == 403
    assert calls == [("job-9", PermissionLevel.CAN_VIEW)]
