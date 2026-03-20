"""Tests for the cancellation registry and CancellableAgentExecutor."""

import json
import threading
from datetime import datetime
from unittest.mock import MagicMock, patch

from src.services.cancellation import CancellationRegistry


class TestCancellationRegistry:
    """Tests for CancellationRegistry thread-safe operations."""

    def setup_method(self):
        """Reset registry state before each test."""
        CancellationRegistry._cancelled.clear()

    def test_cancel_sets_flag(self):
        CancellationRegistry.cancel("session-1")
        assert CancellationRegistry.is_cancelled("session-1") is True

    def test_is_cancelled_default_false(self):
        assert CancellationRegistry.is_cancelled("nonexistent") is False

    def test_reset_clears_flag(self):
        CancellationRegistry.cancel("session-1")
        CancellationRegistry.reset("session-1")
        assert CancellationRegistry.is_cancelled("session-1") is False

    def test_reset_nonexistent_is_noop(self):
        CancellationRegistry.reset("nonexistent")  # should not raise

    def test_cancel_is_idempotent(self):
        CancellationRegistry.cancel("session-1")
        CancellationRegistry.cancel("session-1")
        assert CancellationRegistry.is_cancelled("session-1") is True

    def test_independent_sessions(self):
        CancellationRegistry.cancel("session-1")
        assert CancellationRegistry.is_cancelled("session-1") is True
        assert CancellationRegistry.is_cancelled("session-2") is False

    def test_thread_safety(self):
        """Concurrent cancel/check/reset should not raise."""
        errors = []

        def worker(session_id):
            try:
                for _ in range(100):
                    CancellationRegistry.cancel(session_id)
                    CancellationRegistry.is_cancelled(session_id)
                    CancellationRegistry.reset(session_id)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(f"s-{i}",)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []


# ---------------------------------------------------------------------------
# Helpers shared by TestRevertSlidesOnCancel
# ---------------------------------------------------------------------------

class _MockSession:
    def __init__(self):
        self.id = 1
        self.session_id = "sess-abc"
        self.slide_deck = None
        self.messages = []


class _MockSlideDeck:
    def __init__(self, deck_json: str = '{"title":"Test","slides":[]}'):
        self.deck_json = deck_json
        self.verification_map = None
        self.title = "Test"
        self.slide_count = 1
        self.updated_at = datetime.utcnow()


class _MockVersion:
    def __init__(self, version_number: int, deck_json: str):
        self.session_id = 1
        self.version_number = version_number
        self.deck_json = deck_json
        self.verification_map_json = None


class _MockMessage:
    def __init__(self, msg_id: int, role: str, request_id: str = "req-1"):
        self.id = msg_id
        self.role = role
        self.request_id = request_id
        self.metadata_json = None


def _make_sm():
    from src.api.services.session_manager import SessionManager
    return SessionManager.__new__(SessionManager)


def _mock_db(session_obj):
    """Return a context-manager patch for get_db_session yielding mock_db_session."""
    mock_db_session = MagicMock()
    mock_db_session.query.return_value.filter.return_value.first.return_value = session_obj
    return mock_db_session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRevertSlidesOnCancel:
    """Unit tests for SessionManager.revert_slides_on_cancel."""

    def test_restores_slides_to_pre_gen_version(self):
        """When pre_gen_version is set, deck is restored to that version's JSON."""
        sm = _make_sm()
        session = _MockSession()
        session.slide_deck = _MockSlideDeck('{"title":"New","slides":[{},{}]}')
        pre_version = _MockVersion(2, '{"title":"Old","slides":[{}]}')

        with patch("src.api.services.session_manager.get_db_session") as mock_db_ctx:
            mock_db_session = MagicMock()
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=mock_db_session)
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            # First query: session lookup
            # Second query: version lookup
            # Third query: delete newer versions
            q = MagicMock()
            mock_db_session.query.return_value = q
            q.filter.return_value = q
            q.first.side_effect = [session, pre_version]

            sm.revert_slides_on_cancel("sess-abc", pre_gen_version=2, request_id=None)

        assert session.slide_deck.deck_json == '{"title":"Old","slides":[{}]}'
        assert session.slide_deck.slide_count == 1
        assert session.slide_deck.title == "Old"

    def test_clears_deck_when_no_pre_gen_version(self):
        """When pre_gen_version is None, deck is cleared entirely."""
        sm = _make_sm()
        session = _MockSession()
        session.slide_deck = _MockSlideDeck('{"title":"Generated","slides":[{}]}')

        with patch("src.api.services.session_manager.get_db_session") as mock_db_ctx:
            mock_db_session = MagicMock()
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=mock_db_session)
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            q = MagicMock()
            mock_db_session.query.return_value = q
            q.filter.return_value = q
            q.first.return_value = session

            sm.revert_slides_on_cancel("sess-abc", pre_gen_version=None, request_id=None)

        assert session.slide_deck.deck_json is None
        assert session.slide_deck.slide_count == 0
        assert session.slide_deck.title is None

    def test_flags_ai_messages_with_cancelled_metadata(self):
        """AI and tool messages from the cancelled request are flagged cancelled=True."""
        sm = _make_sm()
        session = _MockSession()
        session.slide_deck = _MockSlideDeck()

        ai_msg = _MockMessage(1, "assistant", request_id="req-cancel")
        tool_msg = _MockMessage(2, "tool", request_id="req-cancel")
        user_msg = _MockMessage(3, "user", request_id="req-cancel")

        with patch("src.api.services.session_manager.get_db_session") as mock_db_ctx:
            mock_db_session = MagicMock()
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=mock_db_session)
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            q = MagicMock()
            mock_db_session.query.return_value = q
            q.filter.return_value = q
            # Session lookup, then message lookup (no version since pre_gen_version=None)
            q.first.return_value = session
            q.all.return_value = [ai_msg, tool_msg]  # user_msg excluded by role != 'user' filter

            sm.revert_slides_on_cancel("sess-abc", pre_gen_version=None, request_id="req-cancel")

        assert json.loads(ai_msg.metadata_json)["cancelled"] is True
        assert json.loads(tool_msg.metadata_json)["cancelled"] is True

    def test_user_message_not_flagged(self):
        """User messages are never flagged — only AI/tool messages are."""
        sm = _make_sm()
        session = _MockSession()
        session.slide_deck = _MockSlideDeck()
        user_msg = _MockMessage(3, "user", request_id="req-cancel")

        with patch("src.api.services.session_manager.get_db_session") as mock_db_ctx:
            mock_db_session = MagicMock()
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=mock_db_session)
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            q = MagicMock()
            mock_db_session.query.return_value = q
            q.filter.return_value = q
            q.first.return_value = session
            q.all.return_value = []  # DB filters out user role — returns empty

            sm.revert_slides_on_cancel("sess-abc", pre_gen_version=None, request_id="req-cancel")

        # User message metadata unchanged
        assert user_msg.metadata_json is None

    def test_noop_when_session_not_found(self):
        """No error raised when session does not exist."""
        sm = _make_sm()

        with patch("src.api.services.session_manager.get_db_session") as mock_db_ctx:
            mock_db_session = MagicMock()
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=mock_db_session)
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            q = MagicMock()
            mock_db_session.query.return_value = q
            q.filter.return_value = q
            q.first.return_value = None  # Session not found

            # Should not raise
            sm.revert_slides_on_cancel("missing-session", pre_gen_version=1, request_id="req-1")
