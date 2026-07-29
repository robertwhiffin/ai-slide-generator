"""Authorization gating tests for slides.py version endpoints (SDR-4437 PR-2)."""

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
        "src.api.routes.slides._check_deck_permission_for_session", gate
    )
    return calls


@pytest.mark.parametrize(
    "method,path,body,expected_level",
    [
        ("PATCH", "/api/slides/0/verification",
         {"session_id": "s1", "verification": None}, PermissionLevel.CAN_EDIT),
        ("POST", "/api/slides/versions/create",
         {"session_id": "s1", "description": "cp"}, PermissionLevel.CAN_EDIT),
        ("PATCH", "/api/slides/versions/3/verification",
         {"session_id": "s1", "verification_map": {}}, PermissionLevel.CAN_EDIT),
        ("POST", "/api/slides/versions/sync-verification",
         {"session_id": "s1"}, PermissionLevel.CAN_EDIT),
        ("POST", "/api/slides/versions/3/restore",
         {"session_id": "s1"}, PermissionLevel.CAN_MANAGE),
    ],
)
def test_version_writes_gated(client, deck_gate, method, path, body, expected_level):
    resp = client.request(method, path, json=body)
    assert resp.status_code == 403
    assert deck_gate == [("s1", expected_level)]


@pytest.mark.parametrize(
    "path",
    [
        "/api/slides/versions",
        "/api/slides/versions/3",
        "/api/slides/versions/current",
    ],
)
def test_version_reads_gated_can_view(client, deck_gate, path):
    resp = client.get(path, params={"session_id": "s1"})
    assert resp.status_code == 403
    assert deck_gate == [("s1", PermissionLevel.CAN_VIEW)]
