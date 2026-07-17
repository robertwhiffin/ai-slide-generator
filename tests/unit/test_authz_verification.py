"""Authorization gating tests for verification.py (SDR-4437 PR-2, HIGH-1)."""

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
    calls = []

    def gate(session_id, min_permission=PermissionLevel.CAN_VIEW):
        calls.append((session_id, min_permission))
        raise HTTPException(status_code=403, detail="denied")

    monkeypatch.setattr(
        "src.api.routes.verification._check_deck_permission_for_session", gate
    )
    return calls


def test_verify_slide_requires_can_edit(client, deck_gate):
    resp = client.post("/api/verification/0", json={"session_id": "s1"})
    assert resp.status_code == 403
    assert deck_gate == [("s1", PermissionLevel.CAN_EDIT)]


def test_slide_feedback_requires_can_edit(client, deck_gate):
    resp = client.post(
        "/api/verification/0/feedback",
        json={"session_id": "s1", "slide_index": 0, "is_positive": True},
    )
    assert resp.status_code == 403
    assert deck_gate == [("s1", PermissionLevel.CAN_EDIT)]


def test_genie_link_requires_can_view(client, deck_gate):
    resp = client.get("/api/verification/genie-link", params={"session_id": "s1"})
    assert resp.status_code == 403
    assert deck_gate == [("s1", PermissionLevel.CAN_VIEW)]
