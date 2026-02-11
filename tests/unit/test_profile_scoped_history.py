"""Unit tests for profile-scoped session history.

Verifies that list_user_generations filters sessions by profile_id when
provided, so switching profiles shows only that profile's sessions.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch, call

from src.api.services.session_manager import SessionManager
from src.database.models.session import UserSession


def _make_mock_session(
    session_id: str,
    created_by: str,
    profile_id: int = None,
    profile_name: str = None,
    title: str = "Untitled",
    last_activity: datetime = None,
) -> Mock:
    """Build a Mock that looks like a UserSession row."""
    s = Mock(spec=UserSession)
    s.session_id = session_id
    s.user_id = created_by
    s.created_by = created_by
    s.visibility = "private"
    s.title = title
    s.created_at = last_activity or datetime.utcnow()
    s.last_activity = last_activity or datetime.utcnow()
    s.messages = []
    s.slide_deck = None
    s.profile_id = profile_id
    s.profile_name = profile_name
    return s


@pytest.fixture
def session_manager():
    return SessionManager()


class TestProfileScopedHistory:
    """list_user_generations should optionally filter by profile_id."""

    def test_no_profile_filter_returns_all_user_sessions(self, session_manager):
        """Without profile_id, all user's sessions are returned."""
        now = datetime.utcnow()
        s1 = _make_mock_session("s-1", "alice@co.com", profile_id=1, profile_name="Profile A", last_activity=now)
        s2 = _make_mock_session("s-2", "alice@co.com", profile_id=2, profile_name="Profile B", last_activity=now)

        mock_query = MagicMock()
        mock_query.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [s1, s2]

        with patch("src.api.services.session_manager.get_db_session") as mock_get_db:
            mock_db = Mock()
            mock_db.query.return_value = mock_query
            mock_get_db.return_value.__enter__ = Mock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = Mock(return_value=False)

            results = session_manager.list_user_generations("alice@co.com", limit=50)

        assert len(results) == 2

    def test_profile_filter_returns_only_matching_sessions(self, session_manager):
        """With profile_id, only sessions for that profile are returned."""
        now = datetime.utcnow()
        s1 = _make_mock_session("s-profile-1", "alice@co.com", profile_id=1, profile_name="Profile A", last_activity=now)

        mock_query = MagicMock()
        # When profile_id is provided, the filter chain includes an extra .filter()
        mock_query.filter.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [s1]

        with patch("src.api.services.session_manager.get_db_session") as mock_get_db:
            mock_db = Mock()
            mock_db.query.return_value = mock_query
            mock_get_db.return_value.__enter__ = Mock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = Mock(return_value=False)

            results = session_manager.list_user_generations("alice@co.com", limit=50, profile_id=1)

        assert len(results) == 1
        assert results[0]["session_id"] == "s-profile-1"
        assert results[0]["profile_id"] == 1

    def test_profile_filter_returns_empty_for_no_match(self, session_manager):
        """Profile with no sessions returns empty list."""
        mock_query = MagicMock()
        mock_query.filter.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

        with patch("src.api.services.session_manager.get_db_session") as mock_get_db:
            mock_db = Mock()
            mock_db.query.return_value = mock_query
            mock_get_db.return_value.__enter__ = Mock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = Mock(return_value=False)

            results = session_manager.list_user_generations("alice@co.com", limit=50, profile_id=999)

        assert results == []

    def test_profile_filter_applies_second_filter_call(self, session_manager):
        """When profile_id is provided, an additional .filter() is called on the query."""
        mock_query = MagicMock()

        with patch("src.api.services.session_manager.get_db_session") as mock_get_db:
            mock_db = Mock()
            mock_db.query.return_value = mock_query
            mock_get_db.return_value.__enter__ = Mock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = Mock(return_value=False)

            session_manager.list_user_generations("alice@co.com", limit=50, profile_id=5)

        # First .filter() for created_by, second .filter() for profile_id
        assert mock_query.filter.call_count >= 1
        chained = mock_query.filter.return_value
        assert chained.filter.called, "Expected a second .filter() call for profile_id"

    def test_no_profile_filter_skips_second_filter(self, session_manager):
        """Without profile_id, only one .filter() is applied (created_by)."""
        mock_query = MagicMock()

        with patch("src.api.services.session_manager.get_db_session") as mock_get_db:
            mock_db = Mock()
            mock_db.query.return_value = mock_query
            mock_get_db.return_value.__enter__ = Mock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = Mock(return_value=False)

            session_manager.list_user_generations("alice@co.com", limit=50, profile_id=None)

        # Only one .filter() for created_by, no second filter
        chained = mock_query.filter.return_value
        assert not chained.filter.called, "Should not apply profile_id filter when None"


class TestSessionCreationOwnership:
    """create_chat_request auto-creates sessions with proper created_by."""

    def test_auto_created_session_has_created_by(self, session_manager):
        """Auto-created session from create_chat_request should set created_by."""
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None  # No existing session

        with patch("src.api.services.session_manager.get_db_session") as mock_get_db:
            mock_db = Mock()
            mock_db.query.return_value = mock_query
            mock_get_db.return_value.__enter__ = Mock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = Mock(return_value=False)

            with patch("src.core.user_context.get_current_user", return_value="alice@co.com"):
                session_manager.create_chat_request("new-session-id", profile_id=1, profile_name="Test")

        # add() is called twice: first UserSession, then ChatRequest
        assert mock_db.add.call_count >= 2
        added_session = mock_db.add.call_args_list[0][0][0]  # First add() call
        assert added_session.created_by == "alice@co.com"
        assert added_session.visibility == "private"

    def test_auto_created_session_null_user(self, session_manager):
        """Auto-created session with no current_user sets created_by=None."""
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None

        with patch("src.api.services.session_manager.get_db_session") as mock_get_db:
            mock_db = Mock()
            mock_db.query.return_value = mock_query
            mock_get_db.return_value.__enter__ = Mock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = Mock(return_value=False)

            with patch("src.core.user_context.get_current_user", return_value=None):
                session_manager.create_chat_request("new-session-id")

        added_session = mock_db.add.call_args_list[0][0][0]  # First add() call
        assert added_session.created_by is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
