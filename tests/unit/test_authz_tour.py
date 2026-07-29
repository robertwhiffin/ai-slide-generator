"""Authorization gating tests for tour.py (SDR-4437 PR-2)."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.database.models.profile_contributor import PermissionLevel


@pytest.fixture
def client():
    from src.api.main import app

    return TestClient(app, raise_server_exceptions=False)


def test_add_demo_slides_requires_can_edit(client, monkeypatch):
    calls = []

    def gate(session_id, min_permission=PermissionLevel.CAN_VIEW):
        calls.append((session_id, min_permission))
        raise HTTPException(status_code=403, detail="denied")

    monkeypatch.setattr(
        "src.api.routes.tour._check_deck_permission_for_session", gate
    )
    resp = client.post("/api/tour/demo-deck/victim-session/slides")
    assert resp.status_code == 403
    assert calls == [("victim-session", PermissionLevel.CAN_EDIT)]
