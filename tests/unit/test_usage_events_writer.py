"""Unit tests for the usage-event writer (dedup + non-blocking)."""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def clean_caches():
    from src.api.services import usage_events

    usage_events.reset_dedup_caches()
    yield
    usage_events.reset_dedup_caches()


class TestLoginDedup:
    @patch("src.api.services.usage_events._submit")
    def test_first_login_writes(self, mock_submit):
        from src.api.services.usage_events import record_login

        record_login("alice@corp.com")
        mock_submit.assert_called_once_with("alice@corp.com", "login", None)

    @patch("src.api.services.usage_events._submit")
    def test_repeat_login_within_window_deduped(self, mock_submit):
        from src.api.services.usage_events import record_login

        record_login("alice@corp.com")
        record_login("alice@corp.com")
        assert mock_submit.call_count == 1

    @patch("src.api.services.usage_events._submit")
    def test_login_after_window_writes_again(self, mock_submit):
        from src.api.services import usage_events

        usage_events.record_login("alice@corp.com")
        # Age the cache entry past the 30-minute window
        usage_events._login_cache["alice@corp.com"] -= usage_events._DEDUP_WINDOW_SECONDS + 1
        usage_events.record_login("alice@corp.com")
        assert mock_submit.call_count == 2

    @patch("src.api.services.usage_events._submit")
    def test_continuous_activity_slides_window_no_reemit(self, mock_submit):
        from src.api.services import usage_events

        usage_events.record_login("alice@corp.com")
        assert mock_submit.call_count == 1
        # Age the entry by just under the window, then more activity arrives
        usage_events._login_cache["alice@corp.com"] -= (
            usage_events._DEDUP_WINDOW_SECONDS - 1
        )
        usage_events.record_login("alice@corp.com")
        assert mock_submit.call_count == 1  # gap < window -> no new visit
        # That call must have refreshed the cache (sliding window): another
        # near-window gap still emits nothing. A fixed window would re-emit here.
        usage_events._login_cache["alice@corp.com"] -= (
            usage_events._DEDUP_WINDOW_SECONDS - 1
        )
        usage_events.record_login("alice@corp.com")
        assert mock_submit.call_count == 1

    @patch("src.api.services.usage_events._submit")
    def test_different_users_not_deduped(self, mock_submit):
        from src.api.services.usage_events import record_login

        record_login("alice@corp.com")
        record_login("bob@corp.com")
        assert mock_submit.call_count == 2

    @patch("src.api.services.usage_events._submit")
    def test_empty_username_ignored(self, mock_submit):
        from src.api.services.usage_events import record_login

        record_login("")
        record_login(None)
        mock_submit.assert_not_called()


class TestDeckEvents:
    @patch("src.api.services.usage_events._submit")
    def test_deck_created_always_writes(self, mock_submit):
        from src.api.services.usage_events import record_deck_created

        record_deck_created("alice@corp.com", 7)
        record_deck_created("alice@corp.com", 8)
        assert mock_submit.call_count == 2
        mock_submit.assert_any_call("alice@corp.com", "deck_created", 7)

    @patch("src.api.services.usage_events._submit")
    def test_deck_retrieved_deduped_per_user_session(self, mock_submit):
        from src.api.services.usage_events import record_deck_retrieved

        record_deck_retrieved("alice@corp.com", 7)
        record_deck_retrieved("alice@corp.com", 7)  # deduped
        record_deck_retrieved("alice@corp.com", 8)  # different deck -> writes
        record_deck_retrieved("bob@corp.com", 7)    # different user -> writes
        assert mock_submit.call_count == 3

    @patch("src.api.services.usage_events._submit")
    def test_deck_events_without_username_ignored(self, mock_submit):
        from src.api.services.usage_events import (
            record_deck_created,
            record_deck_retrieved,
        )

        record_deck_created(None, 7)
        record_deck_retrieved(None, 7)
        mock_submit.assert_not_called()


class TestWriteNeverRaises:
    def test_write_event_swallows_db_errors(self):
        from src.api.services.usage_events import _write_event

        with patch(
            "src.core.database.get_session_local",
            side_effect=RuntimeError("db down"),
        ):
            # Must not raise
            _write_event("alice@corp.com", "login", None)

    def test_write_event_persists_row(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from src.core.database import Base
        from src.database.models.usage_event import UsageEvent

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        factory = sessionmaker(bind=engine)

        with patch("src.core.database.get_session_local", return_value=factory):
            from src.api.services.usage_events import _write_event

            _write_event("alice@corp.com", "login", None)

        db = factory()
        row = db.query(UsageEvent).one()
        assert row.username == "alice@corp.com"
        assert row.event_type == "login"
        db.close()
