"""Agent-config + load-profile gating tests (SDR-4437 PR-2)."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.database.models.profile_contributor import PermissionLevel


@pytest.fixture
def client():
    from src.api.main import app

    return TestClient(app, raise_server_exceptions=False)


def _gate_into(calls):
    def gate(session_id, min_permission=PermissionLevel.CAN_VIEW):
        calls.append((session_id, min_permission))
        raise HTTPException(status_code=403, detail="denied")

    return gate


@pytest.fixture
def agent_config_gate(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "src.api.routes.agent_config._check_deck_permission_for_session",
        _gate_into(calls),
    )
    return calls


def test_get_agent_config_requires_can_view(client, agent_config_gate):
    resp = client.get("/api/sessions/s1/agent-config")
    assert resp.status_code == 403
    assert agent_config_gate == [("s1", PermissionLevel.CAN_VIEW)]


def test_put_agent_config_requires_can_manage(client, agent_config_gate):
    resp = client.put("/api/sessions/s1/agent-config", json={})
    assert resp.status_code == 403
    assert agent_config_gate == [("s1", PermissionLevel.CAN_MANAGE)]


def test_patch_tools_requires_can_manage(client, agent_config_gate):
    resp = client.patch(
        "/api/sessions/s1/agent-config/tools",
        json={
            "action": "add",
            "tool": {"type": "genie", "space_id": "sp", "space_name": "nm"},
        },
    )
    assert resp.status_code == 403
    assert agent_config_gate == [("s1", PermissionLevel.CAN_MANAGE)]


def test_load_profile_requires_can_manage_on_session(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "src.api.routes.profiles._check_deck_permission_for_session",
        _gate_into(calls),
    )
    resp = client.post("/api/sessions/s1/load-profile/7")
    assert resp.status_code == 403
    assert calls == [("s1", PermissionLevel.CAN_MANAGE)]
