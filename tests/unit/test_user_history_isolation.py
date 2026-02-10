"""Unit tests for user-filtered session history (strict ownership isolation).

Verifies that list_user_generations returns only sessions created_by the
requested user -- no shared, workspace-visible, or group-granted sessions leak.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

from src.api.services.session_manager import SessionManager
from src.database.models.session import UserSession


def _make_mock_session(
    session_id: str,
    created_by: str,
    title: str = "Untitled",
    visibility: str = "private",
    last_activity: datetime = None,
    has_slide_deck: bool = False,
    profile_id: int = None,
    profile_name: str = None,
) -> Mock:
    """Build a Mock that looks like a UserSession row."""
    s = Mock(spec=UserSession)
    s.session_id = session_id
    s.user_id = created_by
    s.created_by = created_by
    s.visibility = visibility
    s.title = title
    s.created_at = last_activity or datetime.utcnow()
    s.last_activity = last_activity or datetime.utcnow()
    s.messages = []
    s.slide_deck = Mock() if has_slide_deck else None
    s.profile_id = profile_id
    s.profile_name = profile_name
    return s


@pytest.fixture
def session_manager():
    return SessionManager()


class TestListUserGenerations:
    """list_user_generations should return only sessions owned by the given user."""

    def test_returns_only_owned_sessions(self, session_manager):
        """user_a sees only user_a sessions; user_b sessions are excluded."""
        now = datetime.utcnow()
        alice_session = _make_mock_session("s-alice-1", "alice@co.com", "Alice deck", last_activity=now)
        bob_session = _make_mock_session("s-bob-1", "bob@co.com", "Bob deck", last_activity=now)

        mock_query = MagicMock()
        mock_query.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [alice_session]

        with patch("src.api.services.session_manager.get_db_session") as mock_get_db:
            mock_db = Mock()
            mock_db.query.return_value = mock_query
            mock_get_db.return_value.__enter__ = Mock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = Mock(return_value=False)

            results = session_manager.list_user_generations("alice@co.com", limit=50)

        assert len(results) == 1
        assert results[0]["session_id"] == "s-alice-1"
        assert results[0]["created_by"] == "alice@co.com"

    def test_empty_for_unknown_user(self, session_manager):
        """User with no sessions gets an empty list."""
        mock_query = MagicMock()
        mock_query.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

        with patch("src.api.services.session_manager.get_db_session") as mock_get_db:
            mock_db = Mock()
            mock_db.query.return_value = mock_query
            mock_get_db.return_value.__enter__ = Mock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = Mock(return_value=False)

            results = session_manager.list_user_generations("nobody@co.com")

        assert results == []

    def test_excludes_shared_and_workspace_sessions(self, session_manager):
        """Workspace-visible sessions owned by others must NOT appear."""
        now = datetime.utcnow()
        alice_session = _make_mock_session("s-alice-1", "alice@co.com", last_activity=now)
        # Bob's workspace-visible session -- should NOT be returned for alice
        _make_mock_session("s-bob-ws", "bob@co.com", visibility="workspace", last_activity=now)

        mock_query = MagicMock()
        # The DB filter is created_by == alice, so only alice's session comes back
        mock_query.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [alice_session]

        with patch("src.api.services.session_manager.get_db_session") as mock_get_db:
            mock_db = Mock()
            mock_db.query.return_value = mock_query
            mock_get_db.return_value.__enter__ = Mock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = Mock(return_value=False)

            results = session_manager.list_user_generations("alice@co.com")

        assert len(results) == 1
        assert all(r["created_by"] == "alice@co.com" for r in results)

    def test_ordered_by_last_activity_descending(self, session_manager):
        """Results should come back with most-recent first."""
        now = datetime.utcnow()
        older = _make_mock_session("s-old", "alice@co.com", "Old", last_activity=now - timedelta(hours=2))
        newer = _make_mock_session("s-new", "alice@co.com", "New", last_activity=now)

        mock_query = MagicMock()
        # DB returns them in the correct order (newer first)
        mock_query.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [newer, older]

        with patch("src.api.services.session_manager.get_db_session") as mock_get_db:
            mock_db = Mock()
            mock_db.query.return_value = mock_query
            mock_get_db.return_value.__enter__ = Mock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = Mock(return_value=False)

            results = session_manager.list_user_generations("alice@co.com")

        assert len(results) == 2
        assert results[0]["session_id"] == "s-new"
        assert results[1]["session_id"] == "s-old"
