"""Tests for the 10-minute hard-timeout sweeper on chat jobs."""

from datetime import datetime, timedelta

import pytest

from src.api.services import job_queue


@pytest.fixture(autouse=True)
def _clean_jobs():
    """Ensure an empty in-memory jobs dict between tests."""
    job_queue.jobs.clear()
    yield
    job_queue.jobs.clear()


def test_timeout_constant_is_600_seconds():
    assert job_queue.JOB_HARD_TIMEOUT_SECONDS == 600


@pytest.mark.asyncio
async def test_sweep_marks_old_running_job_as_failed():
    now = datetime.utcnow()
    job_queue.jobs["req-old"] = {
        "status": "running",
        "session_id": "s1",
        "started_at": now - timedelta(seconds=700),
    }

    marked = await job_queue.mark_timed_out_jobs_once()

    entry = job_queue.jobs["req-old"]
    assert entry["status"] == "failed"
    error = entry.get("error", "")
    assert "10 minutes" in error or "600" in error
    assert marked == 1


@pytest.mark.asyncio
async def test_sweep_leaves_young_running_job_alone():
    now = datetime.utcnow()
    job_queue.jobs["req-young"] = {
        "status": "running",
        "session_id": "s2",
        "started_at": now - timedelta(seconds=60),
    }

    marked = await job_queue.mark_timed_out_jobs_once()

    assert job_queue.jobs["req-young"]["status"] == "running"
    assert marked == 0


@pytest.mark.asyncio
async def test_sweep_leaves_pending_job_alone():
    now = datetime.utcnow()
    job_queue.jobs["req-pending"] = {
        "status": "pending",
        "session_id": "s3",
        "queued_at": now - timedelta(seconds=1200),
    }

    marked = await job_queue.mark_timed_out_jobs_once()

    assert job_queue.jobs["req-pending"]["status"] == "pending"
    assert marked == 0


@pytest.mark.asyncio
async def test_sweep_idempotent_on_already_failed():
    now = datetime.utcnow()
    job_queue.jobs["req-already-failed"] = {
        "status": "failed",
        "session_id": "s4",
        "started_at": now - timedelta(hours=1),
        "error": "Existing error",
    }

    marked = await job_queue.mark_timed_out_jobs_once()

    entry = job_queue.jobs["req-already-failed"]
    assert entry["status"] == "failed"
    assert entry["error"] == "Existing error"
    assert marked == 0


@pytest.mark.asyncio
async def test_sweep_handles_missing_started_at():
    """Sweeper must not crash if a running job has no started_at timestamp."""
    job_queue.jobs["req-no-ts"] = {
        "status": "running",
        "session_id": "s5",
    }

    marked = await job_queue.mark_timed_out_jobs_once()

    assert job_queue.jobs["req-no-ts"]["status"] == "running"
    assert marked == 0


@pytest.mark.asyncio
async def test_sweep_marks_multiple_timed_out_jobs():
    now = datetime.utcnow()
    for i in range(3):
        job_queue.jobs[f"req-{i}"] = {
            "status": "running",
            "session_id": f"s{i}",
            "started_at": now - timedelta(seconds=900),
        }
    job_queue.jobs["req-fresh"] = {
        "status": "running",
        "session_id": "s-fresh",
        "started_at": now - timedelta(seconds=10),
    }

    marked = await job_queue.mark_timed_out_jobs_once()

    assert marked == 3
    assert job_queue.jobs["req-fresh"]["status"] == "running"
    for i in range(3):
        assert job_queue.jobs[f"req-{i}"]["status"] == "failed"
