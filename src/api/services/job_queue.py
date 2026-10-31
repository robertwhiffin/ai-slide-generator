"""In-memory job queue for async chat processing.

This module provides a background worker that processes chat requests
asynchronously, enabling polling-based streaming to work around
Databricks Apps' 60-second reverse proxy timeout.
"""

import asyncio
import contextvars
import functools
import logging
import os
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.api.schemas.streaming import StreamEvent, StreamEventType
from src.services.persisted_graph_release import PersistedRuntimeError

logger = logging.getLogger(__name__)

# In-memory job tracking (request_id -> metadata)
jobs: Dict[str, Dict[str, Any]] = {}
job_queue: asyncio.Queue = asyncio.Queue()

# Job runners per uvicorn process.  Each process (UVICORN_WORKERS, default 4) takes
# the chat jobs POSTed to it; with one runner a second turn on the same process
# waited "pending" until the first finished.  A session's turns are still
# serialised by its database session lock, so runners only overlap different
# sessions.
CHAT_JOB_CONCURRENCY_ENV = "TELLR_CHAT_JOB_CONCURRENCY"
DEFAULT_CHAT_JOB_CONCURRENCY = 4
MAX_CHAT_JOB_CONCURRENCY = 16

# Chat jobs block a thread for minutes, so they run on their own pool.  The API's
# request handlers (the chat poll among them) asyncio.to_thread onto the loop's
# default executor; long jobs parked there would starve them.
_chat_executor: Optional[ThreadPoolExecutor] = None
_chat_executor_lock = threading.Lock()


def chat_job_concurrency() -> int:
    """Job runners per process, from ``TELLR_CHAT_JOB_CONCURRENCY`` (default 4, max 16)."""
    raw = os.getenv(CHAT_JOB_CONCURRENCY_ENV)
    if raw is None:
        return DEFAULT_CHAT_JOB_CONCURRENCY
    try:
        value = int(raw.strip())
    except ValueError:
        value = 0
    if value < 1:
        logger.warning(
            "Ignoring %s=%r; using %d chat job runners",
            CHAT_JOB_CONCURRENCY_ENV,
            raw,
            DEFAULT_CHAT_JOB_CONCURRENCY,
        )
        return DEFAULT_CHAT_JOB_CONCURRENCY
    return min(value, MAX_CHAT_JOB_CONCURRENCY)


def get_chat_executor() -> ThreadPoolExecutor:
    """The process's chat-job thread pool, created on first use.

    ``start_workers`` sizes it to its runner count; a direct
    ``process_chat_request`` call (recovery, tests) gets one sized by
    ``chat_job_concurrency()``.
    """
    return _ensure_chat_executor(chat_job_concurrency())


def _ensure_chat_executor(size: int) -> ThreadPoolExecutor:
    global _chat_executor
    with _chat_executor_lock:
        if _chat_executor is None:
            _chat_executor = ThreadPoolExecutor(max_workers=size, thread_name_prefix="chat-job")
        return _chat_executor


def shutdown_chat_executor() -> None:
    """Shut the chat-job pool down without waiting; a later call creates a new one."""
    global _chat_executor
    with _chat_executor_lock:
        executor, _chat_executor = _chat_executor, None
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)

# Maximum duration (seconds) a chat request can stay in "running" before the
# hard-timeout sweeper marks it failed. Belt-and-suspenders on top of the
# startup recover_stuck_requests() pass: the sweeper runs continuously while
# the app is up, whereas recovery only runs at process boot. Gives MCP callers
# a predictable upper bound on poll duration independent of deploy cadence.
JOB_HARD_TIMEOUT_SECONDS = 600

# Agent-mode ("graph") turns get a longer hard limit: a multi-step graph run
# can legitimately exceed the monolith's 10 minutes.
GRAPH_JOB_HARD_TIMEOUT_SECONDS = 1200


def job_hard_timeout_seconds(engine_mode: str | None) -> int:
    """Return the hard-timeout limit (seconds) for a job of the given engine mode."""
    if engine_mode == "graph":
        return GRAPH_JOB_HARD_TIMEOUT_SECONDS
    return JOB_HARD_TIMEOUT_SECONDS

# How often the timeout sweeper loop wakes up to scan for stuck jobs.
# Shorter values catch stuck jobs faster but scan more often; 60 is
# the sweet spot given the 10-minute stuck-job cutoff.
TIMEOUT_SWEEP_INTERVAL_SECONDS = 60

PINNED_GRAPH_CONFIGURATION_ERROR = "Pinned graph configuration is unavailable"
PINNED_GRAPH_CONFIGURATION_METADATA = {
    "code": "pinned_graph_configuration_unavailable"
}


class _PinnedGraphConfigurationTerminalError(Exception):
    """The safe pinned-configuration event was already emitted."""


def is_pinned_graph_configuration_error_event(event: StreamEvent) -> bool:
    return (
        event.type == StreamEventType.ERROR
        and event.error == PINNED_GRAPH_CONFIGURATION_ERROR
        and event.metadata == PINNED_GRAPH_CONFIGURATION_METADATA
    )


def pinned_graph_configuration_error_event_payload() -> dict:
    return {
        "type": StreamEventType.ERROR.value,
        "error": PINNED_GRAPH_CONFIGURATION_ERROR,
        "metadata": dict(PINNED_GRAPH_CONFIGURATION_METADATA),
    }


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
        "engine_mode": payload.get("engine_mode"),
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
    # ws4d D2.  The key is `engine_mode`, NOT `mode`: `mode` is already MCP's
    # generate/edit flag in this same payload (mcp_server.py's enqueue_create_job
    # sets it), so reading `mode` here would hand this the string "generate".
    # The default is what excludes MCP structurally — mcp_server.py builds no
    # `engine_mode` key, so every MCP job runs on the monolith without
    # mcp_server.py knowing this switch exists.
    engine_mode = payload.get("engine_mode", "monolith")

    chat_service = get_chat_service()
    session_manager = get_session_manager()

    # Create a queue - callback handler needs it for event flow
    # Events are persisted to DB which is what polling reads
    event_queue: queue.Queue = queue.Queue()

    try:
        # Update status
        session_manager.update_chat_request_status(request_id, "running")

        # Run blocking agent in the chat-job pool via the generator-based streaming
        # (never the default executor: see _chat_executor).  Use captured context if
        # available to preserve user auth.
        result = None
        session_title = None
        loop = asyncio.get_running_loop()
        if ctx:
            for event in await loop.run_in_executor(
                get_chat_executor(),
                functools.partial(
                    ctx.run,
                    _run_streaming_generator,
                    chat_service,
                    session_id,
                    message,
                    slide_context,
                    request_id,
                    is_first_message,
                    image_ids,
                    engine_mode,
                ),
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
            # Fallback for jobs without context (e.g., recovery): the current
            # context, copied, as asyncio.to_thread would have passed it.
            for event in await loop.run_in_executor(
                get_chat_executor(),
                functools.partial(
                    contextvars.copy_context().run,
                    _run_streaming_generator,
                    chat_service,
                    session_id,
                    message,
                    slide_context,
                    request_id,
                    is_first_message,
                    image_ids,
                    engine_mode,
                ),
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

    except _PinnedGraphConfigurationTerminalError:
        session_manager.update_chat_request_status(
            request_id,
            "error",
            PINNED_GRAPH_CONFIGURATION_ERROR,
        )

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
    engine_mode: str = "monolith",
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
        engine_mode: ``"graph"`` or ``"monolith"`` (ws4d D2).  Every argument
            above is passed POSITIONALLY by both of ``process_chat_request``'s
            call sites — the ``if ctx:`` branch and the no-context recovery
            fallback — so this one is appended last and defaults to monolith.

    Returns:
        List of all events from the generator
    """
    events = []
    try:
        for event in chat_service.send_message_streaming(
            session_id=session_id,
            message=message,
            slide_context=slide_context,
            request_id=request_id,
            is_first_message_override=is_first_message,
            image_ids=image_ids,
            engine_mode=engine_mode,
        ):
            events.append(event)
    except PersistedRuntimeError as exc:
        if any(
            is_pinned_graph_configuration_error_event(event)
            for event in events
        ):
            raise _PinnedGraphConfigurationTerminalError() from exc
        raise
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
    """Start one background worker task.

    Returns:
        The worker task handle
    """
    return asyncio.create_task(worker())


async def start_workers(count: Optional[int] = None) -> List[asyncio.Task]:
    """Start ``count`` job runners (default ``chat_job_concurrency()``) over the one queue.

    The chat-job pool is sized to match, so every runner has a thread.
    """
    count = chat_job_concurrency() if count is None else max(1, count)
    _ensure_chat_executor(count)
    return [asyncio.create_task(worker()) for _ in range(count)]


async def stop_workers(tasks: List[asyncio.Task]) -> None:
    """Cancel every runner, wait for them to stop, then release the chat-job pool.

    A job's thread runs to completion on its own; the startup recovery pass marks
    a job interrupted by a restart.
    """
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass
    shutdown_chat_executor()


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
                ChatRequest.created_at
                < datetime.utcnow() - timedelta(seconds=GRAPH_JOB_HARD_TIMEOUT_SECONDS),
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
    """Single sweep: mark running jobs past their hard-timeout limit as failed.

    Examines the in-memory ``jobs`` dict. The limit is per job, chosen by
    ``job_hard_timeout_seconds(engine_mode)``. For any entry whose ``status`` is
    ``"running"`` and whose ``started_at`` is older than its limit, flips
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
    marked = 0

    for request_id, entry in list(jobs.items()):
        if entry.get("status") != "running":
            continue
        started_at = entry.get("started_at")
        if started_at is None:
            continue
        limit_seconds = job_hard_timeout_seconds(entry.get("engine_mode"))
        if started_at > now - timedelta(seconds=limit_seconds):
            continue

        entry["status"] = "failed"
        entry["error"] = (
            f"Generation exceeded maximum duration "
            f"({limit_seconds // 60} minutes)"
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
            await asyncio.sleep(TIMEOUT_SWEEP_INTERVAL_SECONDS)
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
