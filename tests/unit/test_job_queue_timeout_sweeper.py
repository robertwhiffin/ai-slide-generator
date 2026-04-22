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


# ---- Integration: worker populates started_at correctly --------------------


@pytest.mark.asyncio
async def test_job_entry_gets_started_at_when_worker_marks_running():
    """
    Integration-style test: when the worker flips a job to running, started_at
    must be populated so the timeout sweeper can judge its age.

    The actual status flip to "running" happens inside worker() (not
    process_chat_request), because process_chat_request only updates the DB
    row via session_manager. The in-memory jobs dict — which the sweeper
    reads — is flipped inline in the worker loop. This test captures the
    entry state at the moment process_chat_request is invoked (via an
    AsyncMock side_effect), which is immediately after the worker has
    flipped status to "running" — the exact point the sweeper cares about.
    """
    import asyncio
    from unittest.mock import AsyncMock, patch

    request_id = "req-integ-1"
    captured: dict = {}

    async def _capture_entry(_rid, _payload):
        # Snapshot the jobs entry exactly when the worker hands off to
        # process_chat_request — i.e., right after the status flip.
        captured["entry"] = dict(job_queue.jobs[_rid])

    with patch(
        "src.api.services.job_queue.process_chat_request",
        new=AsyncMock(side_effect=_capture_entry),
    ):
        await job_queue.enqueue_job(
            request_id,
            {
                "session_id": "sess-integ",
                "message": "hello",
            },
        )

        worker_task = asyncio.create_task(job_queue.worker())
        try:
            # Wait for the worker to drain our single queued item. join()
            # resolves once task_done() has been called for every queued
            # item, which in worker() happens after process_chat_request
            # returns (i.e., after our capture ran).
            await asyncio.wait_for(job_queue.job_queue.join(), timeout=2.0)
        finally:
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass

    entry = captured.get("entry")
    assert entry is not None, (
        "worker should have invoked process_chat_request for the enqueued job"
    )
    assert entry.get("status") == "running", (
        "worker must flip status to running before calling process_chat_request"
    )
    assert "started_at" in entry, (
        "worker must populate started_at when the job enters the running "
        "state, so the timeout sweeper can age it"
    )
    assert isinstance(entry["started_at"], datetime)
