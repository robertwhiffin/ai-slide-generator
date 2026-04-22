"""In-memory job queue for async chat processing.

This module provides a background worker that processes chat requests
asynchronously, enabling polling-based streaming to work around
Databricks Apps' 60-second reverse proxy timeout.
"""

import asyncio
import contextvars
import logging
import queue
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from src.api.schemas.streaming import StreamEventType

logger = logging.getLogger(__name__)

# In-memory job tracking (request_id -> metadata)
jobs: Dict[str, Dict[str, Any]] = {}
job_queue: asyncio.Queue = asyncio.Queue()

# Maximum duration (seconds) a chat request can stay in "running" before the
# hard-timeout sweeper marks it failed. Belt-and-suspenders on top of the
# startup recover_stuck_requests() pass: the sweeper runs continuously while
# the app is up, whereas recovery only runs at process boot. Gives MCP callers
# a predictable upper bound on poll duration independent of deploy cadence.
JOB_HARD_TIMEOUT_SECONDS = 600


async def enqueue_job(request_id: str, payload: dict) -> None:
    """Add a job to the queue.

    Captures the current context (including user auth token) so it can
    be applied when the job is processed in the worker.

    Args:
        request_id: Unique request identifier
        payload: Job payload with session_id, message, slide_context
    """
    # Capture context at enqueue time to preserve user auth
    ctx = contextvars.copy_context()
    payload["_context"] = ctx

    jobs[request_id] = {
        "status": "pending",
        "session_id": payload["session_id"],
        "queued_at": datetime.utcnow(),
    }
    await job_queue.put((request_id, payload))
    logger.info("Enqueued job", extra={"request_id": request_id})


def get_job_status(request_id: str) -> Optional[Dict[str, Any]]:
    """Get in-memory job status.

    Args:
        request_id: Request identifier

    Returns:
        Job metadata or None if not found
    """
    return jobs.get(request_id)


async def process_chat_request(request_id: str, payload: dict) -> None:
    """Process a chat request - runs agent and persists results.

    This function:
    1. Updates request status to running
    2. Runs the agent with streaming callback
    3. Stores the final result in the database
    4. Releases the session lock

    Args:
        request_id: Unique request identifier
        payload: Job payload with session_id, message, slide_context
    """
    from src.api.services.chat_service import get_chat_service
    from src.api.services.session_manager import get_session_manager
    from src.services.streaming_callback import StreamingCallbackHandler

    # Extract captured context (if available) for user auth propagation
    ctx = payload.pop("_context", None)

    session_id = payload["session_id"]
    message = payload["message"]
    slide_context = payload.get("slide_context")
    is_first_message = payload.get("is_first_message", False)
    image_ids = payload.get("image_ids")

    chat_service = get_chat_service()
    session_manager = get_session_manager()

    # Create a queue - callback handler needs it for event flow
    # Events are persisted to DB which is what polling reads
    event_queue: queue.Queue = queue.Queue()

    try:
        # Update status
        session_manager.update_chat_request_status(request_id, "running")

        # Run blocking agent in thread pool via the generator-based streaming
        # Use captured context if available to preserve user auth
        result = None
        session_title = None
        if ctx:
            for event in await asyncio.to_thread(
                ctx.run,
                _run_streaming_generator,
                chat_service,
                session_id,
                message,
                slide_context,
                request_id,
                is_first_message,
                image_ids,
            ):
                if event.type == StreamEventType.COMPLETE:
                    result = {
                        "slides": event.slides,
                        "raw_html": event.raw_html,
                        "replacement_info": event.replacement_info,
                        "experiment_url": event.experiment_url,
                        "metadata": event.metadata,
                    }
                elif event.type == StreamEventType.SESSION_TITLE:
                    session_title = event.session_title
        else:
            # Fallback for jobs without context (e.g., recovery)
            for event in await asyncio.to_thread(
                _run_streaming_generator,
                chat_service,
                session_id,
                message,
                slide_context,
                request_id,
                is_first_message,
                image_ids,
            ):
                if event.type == StreamEventType.COMPLETE:
                    result = {
                        "slides": event.slides,
                        "raw_html": event.raw_html,
                        "replacement_info": event.replacement_info,
                        "experiment_url": event.experiment_url,
                        "metadata": event.metadata,
                    }
                elif event.type == StreamEventType.SESSION_TITLE:
                    session_title = event.session_title

        # Include session title in result so poll endpoint can deliver it
        if result and session_title:
            result["session_title"] = session_title

        session_manager.set_chat_request_result(request_id, result)
        session_manager.update_chat_request_status(request_id, "completed")

    except Exception as e:
        logger.error(f"Job failed: {e}", extra={"request_id": request_id})
        session_manager.update_chat_request_status(request_id, "error", str(e))
        raise

    finally:
        # Always release session lock
        session_manager.release_session_lock(session_id)
        # Clean up in-memory tracking
        jobs.pop(request_id, None)


def _run_streaming_generator(
    chat_service,
    session_id: str,
    message: str,
    slide_context: Optional[Dict[str, Any]],
    request_id: str,
    is_first_message: bool = False,
    image_ids: Optional[list] = None,
) -> list:
    """Run the streaming generator and collect events.

    This is a helper to run the generator in a thread pool.

    Args:
        chat_service: ChatService instance
        session_id: Session identifier
        message: User message
        slide_context: Optional slide context
        request_id: Request ID for message tagging
        is_first_message: Whether this is the first message in the session
        image_ids: Optional list of attached image IDs

    Returns:
        List of all events from the generator
    """
    events = []
    for event in chat_service.send_message_streaming(
        session_id=session_id,
        message=message,
        slide_context=slide_context,
        request_id=request_id,
        is_first_message_override=is_first_message,
        image_ids=image_ids,
    ):
        events.append(event)
    return events


async def worker() -> None:
    """Background worker that processes jobs from the queue."""
    logger.info("Job queue worker started")
    while True:
        try:
            request_id, payload = await job_queue.get()
            jobs[request_id]["status"] = "running"
            jobs[request_id]["started_at"] = datetime.utcnow()

            try:
                await process_chat_request(request_id, payload)
            except Exception as e:
                jobs[request_id]["status"] = "error"
                jobs[request_id]["error"] = str(e)
                logger.error(
                    f"Worker job failed: {e}", extra={"request_id": request_id}
                )

            job_queue.task_done()

        except asyncio.CancelledError:
            logger.info("Job queue worker shutting down")
            break
        except Exception as e:
            logger.error(f"Worker loop error: {e}")


async def start_worker() -> asyncio.Task:
    """Start the background worker task.

    Returns:
        The worker task handle
    """
    return asyncio.create_task(worker())


async def recover_stuck_requests() -> int:
    """Mark running requests as error if worker died.

    Called on startup to recover from crashes.

    Returns:
        Number of requests recovered
    """
    from src.api.services.session_manager import get_session_manager
    from src.core.database import get_db_session
    from src.database.models.session import ChatRequest, UserSession

    session_manager = get_session_manager()
    count = 0

    with get_db_session() as db:
        stuck = (
            db.query(ChatRequest)
            .filter(
                ChatRequest.status == "running",
                ChatRequest.created_at < datetime.utcnow() - timedelta(minutes=10),
            )
            .all()
        )

        for req in stuck:
            req.status = "error"
            req.error_message = "Request timed out (worker crash recovery)"
            req.completed_at = datetime.utcnow()

            # Release any session locks
            session = db.query(UserSession).get(req.session_id)
            if session:
                session.is_processing = False
                session.processing_started_at = None

            count += 1

        if count > 0:
            logger.info(f"Recovered {count} stuck requests")

    return count


async def mark_timed_out_jobs_once() -> int:
    """Single sweep: mark running jobs older than JOB_HARD_TIMEOUT_SECONDS as failed.

    Examines the in-memory ``jobs`` dict. For any entry whose ``status`` is
    ``"running"`` and whose ``started_at`` is older than the timeout, flips
    the status to ``"failed"`` and records an explanatory error. Jobs with
    no ``started_at`` are left untouched (we cannot determine age).

    Does NOT cancel the underlying worker coroutine — it only marks the
    in-memory record. A stuck worker slot remains occupied until the next
    app restart. See the spec's Error Handling section for the reasoning
    behind this choice.

    Returns:
        Number of jobs marked failed in this sweep (useful for logging).
    """
    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=JOB_HARD_TIMEOUT_SECONDS)
    marked = 0

    for request_id, entry in list(jobs.items()):
        if entry.get("status") != "running":
            continue
        started_at = entry.get("started_at")
        if started_at is None:
            continue
        if started_at > cutoff:
            continue

        entry["status"] = "failed"
        entry["error"] = (
            f"Generation exceeded maximum duration "
            f"({JOB_HARD_TIMEOUT_SECONDS // 60} minutes)"
        )
        entry["ended_at"] = now
        marked += 1
        logger.warning(
            "Marked job as timed-out",
            extra={
                "request_id": request_id,
                "session_id": entry.get("session_id"),
                "age_seconds": (now - started_at).total_seconds(),
            },
        )

    return marked


async def mark_timed_out_jobs_loop() -> None:
    """Background loop: runs ``mark_timed_out_jobs_once()`` every 60 seconds.

    Started in the FastAPI lifespan alongside the existing chat/export workers
    and request-log cleanup loop. Survives its own exceptions so a single
    transient failure does not take the loop down for the lifetime of the
    process. Responds to ``asyncio.CancelledError`` for clean shutdown.
    """
    while True:
        try:
            await asyncio.sleep(60)
            marked = await mark_timed_out_jobs_once()
            if marked:
                logger.info(
                    "Timeout sweep marked %d job(s) as failed", marked
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(
                "Timeout sweep iteration failed",
                exc_info=True,
                extra={"error": str(e)},
            )

