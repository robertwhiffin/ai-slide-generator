"""Chat-poll IDOR gate (SDR-4437 PR-2)."""

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
def session_manager(monkeypatch):
    mgr = MagicMock()
    monkeypatch.setattr("src.api.routes.chat.get_session_manager", lambda: mgr)
    return mgr


def test_poll_stranger_with_leaked_request_id_403(client, session_manager, monkeypatch):
    session_manager.get_session_id_for_request.return_value = "sess-1"
    calls = []

    def gate(session_id, min_permission=PermissionLevel.CAN_VIEW):
        calls.append((session_id, min_permission))
        raise HTTPException(status_code=403, detail="denied")

    monkeypatch.setattr(
        "src.api.routes.chat._check_deck_permission_for_session", gate
    )
    resp = client.get("/api/chat/poll/req-leaked")
    assert resp.status_code == 403
    assert calls == [("sess-1", PermissionLevel.CAN_VIEW)]
    session_manager.get_chat_request.assert_not_called()  # gate before data access


def test_poll_unknown_request_404(client, session_manager, monkeypatch):
    session_manager.get_session_id_for_request.return_value = None
    monkeypatch.setattr(
        "src.api.routes.chat._check_deck_permission_for_session",
        MagicMock(),
    )
    resp = client.get("/api/chat/poll/req-unknown")
    assert resp.status_code == 404


def test_poll_authorized_proceeds(client, session_manager, monkeypatch):
    session_manager.get_session_id_for_request.return_value = "sess-1"
    session_manager.get_chat_request.return_value = {
        "status": "completed", "result": {"ok": True}, "error_message": None,
    }
    session_manager.get_messages_for_request.return_value = []
    monkeypatch.setattr(
        "src.api.routes.chat._check_deck_permission_for_session",
        MagicMock(),
    )
    resp = client.get("/api/chat/poll/req-1")
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"
