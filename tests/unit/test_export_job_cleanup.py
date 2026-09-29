"""Tests for the export job TTL cleanup mechanism."""

import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.services import export_job_queue
from src.core.database import Base
from src.database.models.session import ExportJob


def _test_db_session_factory(engine):
    session_factory = sessionmaker(bind=engine)

    @contextmanager
    def mock_get_db_session():
        db = session_factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return mock_get_db_session


def test_cleanup_stale_jobs_removes_only_terminal_expired_jobs(
    monkeypatch, tmp_path
):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(
        export_job_queue,
        "get_db_session",
        _test_db_session_factory(engine),
    )

    stale_path = tmp_path / "stale.pptx"
    fresh_path = tmp_path / "fresh.pptx"
    pending_path = tmp_path / "pending.pptx"
    for path in (stale_path, fresh_path, pending_path):
        path.write_bytes(b"pptx")

    old = datetime.utcnow() - timedelta(minutes=31)
    now = datetime.utcnow()
    session_factory = _test_db_session_factory(engine)
    with session_factory() as db:
        db.add_all(
            [
                ExportJob(
                    job_id="stale",
                    session_id="session-1",
                    status="completed",
                    output_path=str(stale_path),
                    created_at=old,
                ),
                ExportJob(
                    job_id="fresh",
                    session_id="session-1",
                    status="completed",
                    output_path=str(fresh_path),
                    created_at=now,
                ),
                ExportJob(
                    job_id="pending",
                    session_id="session-1",
                    status="pending",
                    output_path=str(pending_path),
                    created_at=old,
                ),
            ]
        )
        db.commit()

    assert export_job_queue.cleanup_stale_jobs(max_age_minutes=30) == 1
    assert not stale_path.exists()
    assert fresh_path.exists()
    assert pending_path.exists()


@pytest.mark.asyncio
async def test_export_cleanup_loop_runs_ttl_sweep(monkeypatch):
    sweeps = []

    async def fake_sleep(_seconds):
        if sweeps:
            raise asyncio.CancelledError

    def fake_cleanup(max_age_minutes):
        sweeps.append(max_age_minutes)
        return 1

    monkeypatch.setattr(export_job_queue.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(export_job_queue, "cleanup_stale_jobs", fake_cleanup)

    with pytest.raises(asyncio.CancelledError):
        await export_job_queue.export_cleanup_loop()

    assert sweeps == [export_job_queue.EXPORT_JOB_MAX_AGE_MINUTES]
