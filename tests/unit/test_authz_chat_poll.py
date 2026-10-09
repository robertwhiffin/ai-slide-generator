"""Chat-poll gate: session creator only (SDR-4437 PR-2, F-CR-31)."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api.services.session_manager import SessionNotFoundError


@pytest.fixture
def client():
    from src.api.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def session_manager(monkeypatch):
    mgr = MagicMock()
    monkeypatch.setattr("src.api.routes.chat.get_session_manager", lambda: mgr)
    return mgr


def _as_user(monkeypatch, user):
    monkeypatch.setattr("src.api.routes.chat.get_current_user", lambda: user)


def test_poll_viewer_cannot_read_other_users_request_403(
    client, session_manager, monkeypatch
):
    """CAN_VIEW on the deck does not expose another user's chat events."""
    _as_user(monkeypatch, "viewer@x.com")
    session_manager.get_session_id_for_request.return_value = "sess-1"
    session_manager.get_session.return_value = {"created_by": "owner@x.com"}
    resp = client.get("/api/chat/poll/req-leaked")
    assert resp.status_code == 403
    # Gate runs before any data access.
    session_manager.get_chat_request.assert_not_called()
    session_manager.get_messages_for_request.assert_not_called()


def test_poll_no_user_403(client, session_manager, monkeypatch):
    _as_user(monkeypatch, None)
    session_manager.get_session_id_for_request.return_value = "sess-1"
    session_manager.get_session.return_value = {"created_by": None}
    resp = client.get("/api/chat/poll/req-1")
    assert resp.status_code == 403
    session_manager.get_chat_request.assert_not_called()


def test_poll_unknown_request_404(client, session_manager, monkeypatch):
    _as_user(monkeypatch, "viewer@x.com")
    session_manager.get_session_id_for_request.return_value = None
    resp = client.get("/api/chat/poll/req-unknown")
    assert resp.status_code == 404
    session_manager.get_session.assert_not_called()


def test_poll_session_missing_404(client, session_manager, monkeypatch):
    _as_user(monkeypatch, "owner@x.com")
    session_manager.get_session_id_for_request.return_value = "sess-gone"
    session_manager.get_session.side_effect = SessionNotFoundError("gone")
    resp = client.get("/api/chat/poll/req-1")
    assert resp.status_code == 404


@pytest.mark.parametrize("user", ["owner@x.com", "editor@x.com"])
def test_poll_session_creator_proceeds(client, session_manager, monkeypatch, user):
    """Root owner, or an editor polling their own contributor session."""
    _as_user(monkeypatch, user)
    session_manager.get_session_id_for_request.return_value = "sess-1"
    session_manager.get_session.return_value = {"created_by": user}
    session_manager.get_chat_request.return_value = {
        "status": "completed", "result": {"ok": True}, "error_message": None,
    }
    session_manager.get_messages_for_request.return_value = []
    resp = client.get("/api/chat/poll/req-1")
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"
