"""A turn's session lock stays live while its process holds the turn.

The session lock (``user_sessions.is_processing`` + ``processing_started_at``) goes
stale after ``SESSION_LOCK_TIMEOUT_SECONDS`` (300 s), but a graph turn may run for
1200 s and a queued turn waits before it starts.  Nothing refreshed the lock, so a
second turn on the SAME session could take a stale lock and run alongside the first;
with several job runners per process it can share that process's caches too.

Each process's timeout sweep (every 60 s) now refreshes the lock of every turn it
holds, pending or running.  If the process dies the refresh stops and the lock goes
stale as before.

SABOTAGE: drop the ``is_processing`` condition from ``refresh_session_lock`` -> the
released-lock test goes red; drop the sweep's refresh call -> the loop test goes red;
refresh failed jobs too -> the status-filter test goes red.
"""

import asyncio
import contextlib
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.services import job_queue
from src.api.services.session_manager import SESSION_LOCK_TIMEOUT_SECONDS, SessionManager
from src.core.database import Base
from src.database.models.session import UserSession


@pytest.fixture
def manager():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    @contextlib.contextmanager
    def managed_session():
        db = factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    with patch("src.api.services.session_manager.get_db_session", managed_session):
        yield SessionManager(), factory
    engine.dispose()


def _add(factory, session_id: str, *, processing: bool, age_seconds: float | None):
    started = None if age_seconds is None else datetime.utcnow() - timedelta(seconds=age_seconds)
    with factory.begin() as db:
        db.add(UserSession(session_id=session_id, is_processing=processing, processing_started_at=started))


def _row(factory, session_id: str) -> UserSession:
    with factory() as db:
        return db.query(UserSession).filter(UserSession.session_id == session_id).one()


# --- SessionManager.refresh_session_lock ---------------------------------------------


def test_a_refreshed_lock_is_not_taken_by_a_second_turn(manager):
    sm, factory = manager
    stale_age = SESSION_LOCK_TIMEOUT_SECONDS + 5
    _add(factory, "s-live", processing=True, age_seconds=stale_age)

    assert sm.refresh_session_lock("s-live") is True
    assert sm.acquire_session_lock("s-live") is False, "a refreshed lock was taken as stale"


def test_without_a_refresh_the_same_lock_is_stale(manager):
    """The control for the test above: today's behaviour after 300 s."""
    sm, factory = manager
    _add(factory, "s-old", processing=True, age_seconds=SESSION_LOCK_TIMEOUT_SECONDS + 5)
    assert sm.acquire_session_lock("s-old") is True


def test_a_released_lock_is_not_revived(manager):
    sm, factory = manager
    _add(factory, "s-free", processing=False, age_seconds=None)

    assert sm.refresh_session_lock("s-free") is False
    row = _row(factory, "s-free")
    assert row.is_processing is False
    assert row.processing_started_at is None


def test_refreshing_a_missing_session_is_harmless(manager):
    sm, _factory = manager
    assert sm.refresh_session_lock("no-such-session") is False


# --- the per-process sweep -------------------------------------------------------------


@pytest.fixture
def clean_jobs():
    job_queue.jobs.clear()
    yield job_queue.jobs
    job_queue.jobs.clear()


@pytest.mark.asyncio
async def test_the_sweep_refreshes_pending_and_running_turns_only(clean_jobs):
    clean_jobs.update(
        {
            "r-pending": {"status": "pending", "session_id": "s-pending"},
            "r-running": {"status": "running", "session_id": "s-running"},
            "r-failed": {"status": "failed", "session_id": "s-failed"},
            "r-error": {"status": "error", "session_id": "s-error"},
        }
    )
    sm = MagicMock()
    with patch("src.api.services.session_manager.get_session_manager", return_value=sm):
        refreshed = await job_queue.refresh_job_session_locks_once()

    called = sorted(c.args[0] for c in sm.refresh_session_lock.call_args_list)
    assert called == ["s-pending", "s-running"]
    assert refreshed == 2


@pytest.mark.asyncio
async def test_one_failing_refresh_does_not_stop_the_others(clean_jobs):
    clean_jobs.update(
        {
            "r-1": {"status": "running", "session_id": "s-1"},
            "r-2": {"status": "running", "session_id": "s-2"},
        }
    )
    sm = MagicMock()
    sm.refresh_session_lock.side_effect = [RuntimeError("db blip"), True]
    with patch("src.api.services.session_manager.get_session_manager", return_value=sm):
        refreshed = await job_queue.refresh_job_session_locks_once()

    assert sm.refresh_session_lock.call_count == 2
    assert refreshed == 1


@pytest.mark.asyncio
async def test_the_timeout_loop_refreshes_locks_every_sweep():
    calls: list[str] = []

    async def sleep(_seconds):
        if len(calls) >= 2:
            raise asyncio.CancelledError
        calls.append("tick")

    async def refresh():
        calls.append("refresh")
        return 0

    async def mark():
        return 0

    with patch.object(job_queue.asyncio, "sleep", sleep), patch.object(
        job_queue, "refresh_job_session_locks_once", refresh
    ), patch.object(job_queue, "mark_timed_out_jobs_once", mark):
        with pytest.raises(asyncio.CancelledError):
            await job_queue.mark_timed_out_jobs_loop()

    assert calls == ["tick", "refresh"]


def test_the_sweep_interval_is_well_inside_the_lock_timeout():
    assert job_queue.TIMEOUT_SWEEP_INTERVAL_SECONDS * 3 <= SESSION_LOCK_TIMEOUT_SECONDS
