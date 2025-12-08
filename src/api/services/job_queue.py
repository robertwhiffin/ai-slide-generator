"""In-memory job queue for async chat processing.

This module provides a background worker that processes chat requests
asynchronously, enabling polling-based streaming to work around
Databricks Apps' 60-second reverse proxy timeout.
"""

import asyncio
import logging
import queue
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from src.api.schemas.streaming import StreamEventType

logger = logging.getLogger(__name__)

# In-memory job tracking (request_id -> metadata)
jobs: Dict[str, Dict[str, Any]] = {}
job_queue: asyncio.Queue = asyncio.Queue()


async def enqueue_job(request_id: str, payload: dict) -> None:
    """Add a job to the queue.

    Args:
        request_id: Unique request identifier
        payload: Job payload with session_id, message, slide_context
    """
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

    session_id = payload["session_id"]
    message = payload["message"]
    slide_context = payload.get("slide_context")

    chat_service = get_chat_service()
    session_manager = get_session_manager()

    # Create a queue - callback handler needs it for event flow
    # Events are persisted to DB which is what polling reads
    event_queue: queue.Queue = queue.Queue()

    try:
        # Update status
        session_manager.update_chat_request_status(request_id, "running")

        # Run blocking agent in thread pool via the generator-based streaming
        result = None
        for event in await asyncio.to_thread(
            _run_streaming_generator,
            chat_service,
            session_id,
            message,
            slide_context,
            request_id,
        ):
            # Capture the final COMPLETE event
            if event.type == StreamEventType.COMPLETE:
                result = {
                    "slides": event.slides,
                    "raw_html": event.raw_html,
                    "replacement_info": event.replacement_info,
                }

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
) -> list:
    """Run the streaming generator and collect events.

    This is a helper to run the generator in a thread pool.

    Args:
        chat_service: ChatService instance
        session_id: Session identifier
        message: User message
        slide_context: Optional slide context
        request_id: Request ID for message tagging

    Returns:
        List of all events from the generator
    """
    events = []
    for event in chat_service.send_message_streaming(
        session_id=session_id,
        message=message,
        slide_context=slide_context,
        request_id=request_id,
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

