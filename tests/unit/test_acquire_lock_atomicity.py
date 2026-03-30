"""Tests documenting the TOCTOU race in acquire_session_lock.

SQLite does not support SELECT ... FOR UPDATE, so on SQLite the race
condition cannot be prevented at the database level. On PostgreSQL /
Lakebase the `with_for_update(nowait=False)` clause serialises
concurrent lock attempts, closing the race window.

This test uses threading + a barrier to synchronise two threads that
both try to acquire the same session lock simultaneously, proving
that without row-level locking both threads can succeed (the bug
this fix documents).
"""

import threading
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_session(session_id: str = "sess-1", is_processing: bool = False):
    """Return a mock UserSession row."""
    s = MagicMock()
    s.session_id = session_id
    s.is_processing = is_processing
    s.processing_started_at = None
    return s


class _FakeQuery:
    """Minimal stand-in for a SQLAlchemy query chain."""

    def __init__(self, session_obj):
        self._session_obj = session_obj

    def filter(self, *_a, **_kw):
        return self

    def with_for_update(self, **_kw):
        # SQLite will raise NotImplementedError or OperationalError;
        # we simulate that here so the fallback path is exercised.
        raise NotImplementedError("SQLite does not support FOR UPDATE")

    def first(self):
        return self._session_obj


class _FakeQueryNoForUpdate:
    """Query chain where with_for_update is never called (fallback)."""

    def __init__(self, session_obj):
        self._session_obj = session_obj

    def filter(self, *_a, **_kw):
        return self

    def first(self):
        return self._session_obj


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAcquireLockAtomicity:
    """Document the TOCTOU race and verify the FOR UPDATE fallback."""

    @patch("src.api.services.session_manager.get_db_session")
    def test_sqlite_fallback_both_threads_acquire(self, mock_get_db):
        """On SQLite (no FOR UPDATE) two concurrent callers both acquire.

        This is the TOCTOU race: thread-A reads is_processing=False,
        thread-B reads is_processing=False, both set it to True.
        With SELECT FOR UPDATE on Postgres the second thread would block
        until the first commits, seeing is_processing=True.
        """
        from src.api.services.session_manager import SessionManager

        # Each call gets its own independent session object that starts
        # with is_processing=False — simulating two separate DB reads
        # that both see the unlocked state (the TOCTOU window).
        def _db_ctx():
            fresh_session = _make_fake_session(is_processing=False)
            ctx = MagicMock()
            db = MagicMock()
            db.query.return_value = _FakeQuery(fresh_session)
            ctx.__enter__ = MagicMock(return_value=db)
            ctx.__exit__ = MagicMock(return_value=False)
            return ctx

        mock_get_db.side_effect = lambda: _db_ctx()

        barrier = threading.Barrier(2, timeout=5)
        results = [None, None]

        def _acquire(idx):
            barrier.wait()  # both threads start at the same instant
            mgr = SessionManager()
            results[idx] = mgr.acquire_session_lock("sess-1")

        t0 = threading.Thread(target=_acquire, args=(0,))
        t1 = threading.Thread(target=_acquire, args=(1,))
        t0.start()
        t1.start()
        t0.join(timeout=10)
        t1.join(timeout=10)

        # Without row-level locking both threads succeed — this IS the bug
        # on SQLite. On Postgres with FOR UPDATE the second thread would
        # block and then see is_processing=True, returning False.
        assert results[0] is True
        assert results[1] is True

    @patch("src.api.services.session_manager.get_db_session")
    def test_for_update_fallback_still_acquires(self, mock_get_db):
        """When FOR UPDATE raises, the method falls back to plain .first()
        and still acquires the lock (single caller, no contention)."""
        from src.api.services.session_manager import SessionManager

        fake_session = _make_fake_session(is_processing=False)

        def _db_ctx():
            ctx = MagicMock()
            db = MagicMock()
            db.query.return_value = _FakeQuery(fake_session)
            ctx.__enter__ = MagicMock(return_value=db)
            ctx.__exit__ = MagicMock(return_value=False)
            return ctx

        mock_get_db.side_effect = lambda: _db_ctx()

        mgr = SessionManager()
        assert mgr.acquire_session_lock("sess-1") is True
        assert fake_session.is_processing is True
        assert fake_session.processing_started_at is not None

    @patch("src.api.services.session_manager.get_db_session")
    def test_already_locked_returns_false(self, mock_get_db):
        """If the session is already locked (not stale), return False."""
        from src.api.services.session_manager import SessionManager

        fake_session = _make_fake_session(is_processing=True)
        fake_session.processing_started_at = datetime.utcnow()

        def _db_ctx():
            ctx = MagicMock()
            db = MagicMock()
            db.query.return_value = _FakeQuery(fake_session)
            ctx.__enter__ = MagicMock(return_value=db)
            ctx.__exit__ = MagicMock(return_value=False)
            return ctx

        mock_get_db.side_effect = lambda: _db_ctx()

        mgr = SessionManager()
        assert mgr.acquire_session_lock("sess-1") is False

    @patch("src.api.services.session_manager.get_db_session")
    def test_missing_session_returns_true(self, mock_get_db):
        """If the session does not exist yet, allow auto-creation."""
        from src.api.services.session_manager import SessionManager

        def _db_ctx():
            ctx = MagicMock()
            db = MagicMock()
            # with_for_update raises -> fallback -> .first() returns None
            db.query.return_value = _FakeQuery(None)
            ctx.__enter__ = MagicMock(return_value=db)
            ctx.__exit__ = MagicMock(return_value=False)
            return ctx

        mock_get_db.side_effect = lambda: _db_ctx()

        mgr = SessionManager()
        assert mgr.acquire_session_lock("sess-new") is True
