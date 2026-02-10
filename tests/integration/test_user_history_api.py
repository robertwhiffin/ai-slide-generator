"""Integration tests for user-filtered session history API.

Verifies that GET /api/sessions returns only the current user's sessions
and that sessions auto-created on generation store created_by correctly.
"""
import pytest
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient

from src.api.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


class TestGetSessionsUserFiltering:
    """GET /api/sessions must return only the current user's sessions."""

    def test_returns_only_current_user_sessions(self, client):
        """Mock current user as alice; verify only alice's sessions come back."""
        alice_sessions = [
            {
                "session_id": "s-alice-1",
                "user_id": "alice@co.com",
                "created_by": "alice@co.com",
                "visibility": "private",
                "title": "Alice Deck",
                "created_at": "2026-02-09T10:00:00",
                "last_activity": "2026-02-09T10:05:00",
                "message_count": 3,
                "has_slide_deck": True,
                "profile_id": 1,
                "profile_name": "Default",
            },
        ]

        with patch("src.api.routes.sessions.get_current_user", return_value="alice@co.com"):
            with patch("src.api.routes.sessions.get_session_manager") as mock_get_mgr:
                mock_mgr = Mock()
                mock_get_mgr.return_value = mock_mgr
                mock_mgr.list_user_generations.return_value = alice_sessions

                response = client.get("/api/sessions")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["sessions"][0]["created_by"] == "alice@co.com"
        # Confirm the manager was called with the correct username
        mock_mgr.list_user_generations.assert_called_once_with(
            username="alice@co.com",
            limit=50,
        )

    def test_no_user_returns_empty(self, client):
        """When no current user can be resolved, return empty list."""
        with patch("src.api.routes.sessions.get_current_user", return_value=None):
            with patch("src.api.routes.sessions.get_current_user_from_client", side_effect=Exception("no token")):
                response = client.get("/api/sessions")

        assert response.status_code == 200
        data = response.json()
        assert data["sessions"] == []
        assert data["count"] == 0

    def test_bob_cannot_see_alice_sessions(self, client):
        """When current user is bob, alice's sessions are not returned."""
        bob_sessions = [
            {
                "session_id": "s-bob-1",
                "user_id": "bob@co.com",
                "created_by": "bob@co.com",
                "visibility": "private",
                "title": "Bob Deck",
                "created_at": "2026-02-09T11:00:00",
                "last_activity": "2026-02-09T11:05:00",
                "message_count": 1,
                "has_slide_deck": False,
                "profile_id": None,
                "profile_name": None,
            },
        ]

        with patch("src.api.routes.sessions.get_current_user", return_value="bob@co.com"):
            with patch("src.api.routes.sessions.get_session_manager") as mock_get_mgr:
                mock_mgr = Mock()
                mock_get_mgr.return_value = mock_mgr
                mock_mgr.list_user_generations.return_value = bob_sessions

                response = client.get("/api/sessions")

        data = response.json()
        assert all(s["created_by"] == "bob@co.com" for s in data["sessions"])
        mock_mgr.list_user_generations.assert_called_once_with(
            username="bob@co.com",
            limit=50,
        )


class TestSessionCreationOwnership:
    """Sessions auto-created on first message must store created_by."""

    def test_create_session_stores_created_by(self, client):
        """POST /api/sessions should set created_by to current user."""
        with patch("src.api.routes.sessions.get_session_manager") as mock_get_mgr:
            mock_mgr = Mock()
            mock_get_mgr.return_value = mock_mgr
            mock_mgr.create_session.return_value = {
                "session_id": "new-abc",
                "user_id": "alice@co.com",
                "created_by": "alice@co.com",
                "visibility": "private",
                "title": "New Session",
                "created_at": "2026-02-09T12:00:00",
                "profile_id": None,
                "profile_name": None,
            }

            response = client.post("/api/sessions", json={"title": "New Session"})

        assert response.status_code == 200
        assert response.json()["created_by"] == "alice@co.com"
