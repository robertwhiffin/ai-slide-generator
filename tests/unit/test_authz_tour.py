"""Authorization gating tests for tour.py (SDR-4437 PR-2)."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.database.models.profile_contributor import PermissionLevel


@pytest.fixture
def client():
    from src.api.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("stage", ["plan", "build", "review", "edit"])
def test_run_stage_requires_can_edit(client, monkeypatch, stage):
    calls = []

    def gate(session_id, min_permission=PermissionLevel.CAN_VIEW):
        calls.append((session_id, min_permission))
        raise HTTPException(status_code=403, detail="denied")

    monkeypatch.setattr("src.api.routes.tour._check_deck_permission_for_session", gate)
    resp = client.post(f"/api/tour/demo-deck/victim-session/stages/{stage}")
    assert resp.status_code == 403
    assert calls == [("victim-session", PermissionLevel.CAN_EDIT)]


def test_legacy_slides_route_is_gone(client):
    assert client.post("/api/tour/demo-deck/any/slides").status_code in (404, 405)
