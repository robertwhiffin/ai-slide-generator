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
from src.services.generation_fence import TurnStopped
from src.services.persisted_graph_release import PersistedRuntimeError

logger = logging.getLogger(__name__)

# How often (seconds) a graph turn's consumer reads the turn's status while it
# waits on the graph.  A stop, timeout or orphan rollback ends the turn in the
# database, from any process; the consumer notices within about this long and
# frees the job runner, though the abandoned graph thread may still be blocked
# in a model call (its next write is refused by the fence).
STOP_POLL_SECONDS = 1.0

#: ``error_message`` of a ``running`` request the startup pass finds stuck.
CRASH_RECOVERY_ERROR = "Request timed out (worker crash recovery)"

# In-memory job tracking (request_id -> metadata)
jobs: Dict[str, Dict[str, Any]] = {}
job_queue: asyncio.Queue = asyncio.Queue()

# Job runners per uvicorn process.  Each process (UVICORN_WORKERS, default 4) takes
# the chat jobs POSTed to it; with one runner a second turn on the same process
# waited "pending" until the first finished.  A session's turns are still
# serialised by its database session lock, so runners only overlap different
# sessions.  The default stays 1: a load test of 8 concurrent decks drew 118
# model 429s and failed 6 turns, so more runners wait on better 429 handling.
CHAT_JOB_CONCURRENCY_ENV = "TELLR_CHAT_JOB_CONCURRENCY"
DEFAULT_CHAT_JOB_CONCURRENCY = 1
MAX_CHAT_JOB_CONCURRENCY = 16

# Chat jobs block a thread for minutes, so they run on their own pool.  The API's
# request handlers (the chat poll among them) asyncio.to_thread onto the loop's
# default executor; long jobs parked there would starve them.
_chat_executor: Optional[ThreadPoolExecutor] = None
_chat_executor_lock = threading.Lock()


def chat_job_concurrency() -> int:
    """Job runners per process, from ``TELLR_CHAT_JOB_CONCURRENCY`` (default 1, max 16)."""
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


def _ensure_chat_executor(size: int, *, resize: bool = False) -> ThreadPoolExecutor:
    """The chat-job pool; with ``resize``, one of exactly ``size`` threads.

    ``start_workers`` resizes, so a pool created lazily at another size (a direct
    ``process_chat_request`` call) cannot leave runners without a thread.  The old
    pool's running jobs finish on their own threads.
    """
    global _chat_executor
    replaced: Optional[ThreadPoolExecutor] = None
    with _chat_executor_lock:
        if _chat_executor is not None and resize and _chat_executor._max_workers != size:
            replaced, _chat_executor = _chat_executor, None
        if _chat_executor is None:
            _chat_executor = ThreadPoolExecutor(max_workers=size, thread_name_prefix="chat-job")
        executor = _chat_executor
    if replaced is not None:
        replaced.shutdown(wait=False)
    return executor


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

    A graph request (an Agent deck's turn, ``engine_mode == "graph"``) is
    all-or-nothing: it starts only if it is still ``pending`` (a stop while it
    was queued already rolled it back), completes only while it is still live,
    and a failure rolls back its generation snapshot.  Every other request (a
    Legacy deck's, every MCP job) takes the path it always has.

    Args:
        request_id: Unique request identifier
        payload: Job payload with session_id, message, slide_context
    """
    # Lazy imports: generation_rollback, for one, imports session_manager at its top.
    from src.api.services.chat_service import get_chat_service
    from src.api.services.session_manager import get_session_manager
    from src.services.generation_rollback import has_generation_snapshot, roll_back_generation
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
    # Only the async route's Agent-deck turns carry engine_mode "graph"; a payload
    # without the key (every MCP job) is never one.
    is_graph = payload.get("engine_mode") == "graph"
    # Graph-only snapshot of the slide on stage; absent on MCP and pre-existing jobs.
    stage_slide = payload.get("stage_slide")

    chat_service = get_chat_service()
    session_manager = get_session_manager()

    # Create a queue - callback handler needs it for event flow
    # Events are persisted to DB which is what polling reads
    event_queue: queue.Queue = queue.Queue()

    # False only for a graph request stopped while it was queued.  It is already
    # rolled back and its lock released, and maybe a newer request holds the lock:
    # run nothing, write nothing, release nothing (the finally only stops
    # counting it as this process's job).
    started = True
    # Set once complete_chat_request committed, which dropped the snapshot with it.
    completed = False
    try:
        # Update status.  A graph request starts only while it is still pending,
        # in its own transaction; a start that raises fails (and rolls back) the
        # turn like any other failure below.
        if is_graph:
            started = session_manager.start_chat_request(request_id)
            if not started:
                logger.info(
                    "Skipped a chat request that was stopped before it started",
                    extra={"request_id": request_id},
                )
                return
        else:
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
                    stage_slide,
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
                    stage_slide,
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

        if is_graph:
            # The result, the status and the snapshot's deletion in one
            # transaction; a request that is no longer live is written nothing.
            completed = session_manager.complete_chat_request(request_id, result)
        else:
            session_manager.set_chat_request_result(request_id, result)
            session_manager.update_chat_request_status(request_id, "completed")

    except TurnStopped:
        # A graph turn ended in the database (a stop, a timeout, an orphan
        # rollback) while its graph was still running.  Whoever ended it wrote
        # its status; the runner is free now, and the finally releases only
        # what this request still owns.
        logger.info(
            "Chat job ended: its turn was stopped", extra={"request_id": request_id}
        )

    except _PinnedGraphConfigurationTerminalError:
        if not is_graph:
            session_manager.update_chat_request_status(
                request_id,
                "error",
                PINNED_GRAPH_CONFIGURATION_ERROR,
            )
        elif has_generation_snapshot(request_id):
            # Enter already saved the user message, locked the deck mode and
            # pinned the deck, though no node ran: undo all of it.
            roll_back_generation(
                request_id,
                terminal_status="error",
                error_message=PINNED_GRAPH_CONFIGURATION_ERROR,
                refuse_on_foreign_change=False,
            )
        else:
            session_manager.fail_chat_request(request_id, PINNED_GRAPH_CONFIGURATION_ERROR)

    except Exception as e:
        logger.error(f"Job failed: {e}", extra={"request_id": request_id})
        if not is_graph:
            session_manager.update_chat_request_status(request_id, "error", str(e))
        elif has_generation_snapshot(request_id):
            roll_back_generation(
                request_id,
                terminal_status="error",
                error_message=str(e),
                refuse_on_foreign_change=False,
            )
        else:
            # No snapshot: a stop (or another rollback) has already ended the
            # turn, and its status must not be overwritten.
            session_manager.fail_chat_request(request_id, str(e))
        raise

    finally:
        # Always release session lock.  Graph requests bind the lock to their
        # request id, so release only while this request still owns it, and not
        # while its snapshot survives: a failed restore keeps the deck locked to
        # its sender until a retry restores it.  Monolith requests (including
        # every MCP job) never bind and release as before.  A graph request that
        # never started releases nothing: its stop already released the lock.
        if not is_graph:
            session_manager.release_session_lock(session_id)
        elif started and (completed or not _snapshot_survives(request_id)):
            session_manager.release_session_lock(session_id, request_id=request_id)
        # Clean up in-memory tracking
        jobs.pop(request_id, None)


def _snapshot_survives(request_id: str) -> bool:
    """Whether a finished graph job's generation snapshot is still there.

    Only a failed restore leaves one (``restore_failed``), and its deck stays
    locked until a retry restores it.  An unreadable answer counts as "yes": a
    lock kept goes stale after ``SESSION_LOCK_TIMEOUT_SECONDS`` once this job
    stops refreshing it, while a lock released could free a deck whose restore
    is still pending.  Never raises, so the job's in-memory entry is dropped.
    """
    from src.services.generation_rollback import has_generation_snapshot

    try:
        return has_generation_snapshot(request_id)
    except Exception:
        logger.warning(
            "Could not read the generation snapshot; keeping the session lock",
            exc_info=True,
            extra={"request_id": request_id},
        )
        return True


def _run_streaming_generator(
    chat_service,
    session_id: str,
    message: str,
    slide_context: Optional[Dict[str, Any]],
    request_id: str,
    is_first_message: bool = False,
    image_ids: Optional[list] = None,
    engine_mode: str = "monolith",
    stage_slide: Optional[Dict[str, Any]] = None,
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
            fallback — so this one is appended after the others and defaults to
            monolith.
        stage_slide: Optional graph-only snapshot of the slide on stage
            (``{"slide_number", "slide_id"}``), appended after ``engine_mode``
            and passed positionally by both call sites.

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
            stage_slide=stage_slide,
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
                # process_chat_request's finally has already dropped the entry.
                entry = jobs.get(request_id)
                if entry is not None:
                    entry["status"] = "error"
                    entry["error"] = str(e)
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
    _ensure_chat_executor(count, resize=True)
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


def _stuck_requests() -> List[tuple]:
    """``(request_id, session pk, has a snapshot)`` of every request still
    ``running`` past the longest hard timeout."""
    from sqlalchemy import exists, select

    from src.core.database import get_db_session
    from src.database.models.generation_snapshot import GenerationSnapshot
    from src.database.models.session import ChatRequest

    cutoff = datetime.utcnow() - timedelta(seconds=GRAPH_JOB_HARD_TIMEOUT_SECONDS)
    has_snapshot = (
        exists()
        .where(GenerationSnapshot.request_id == ChatRequest.request_id)
        .correlate(ChatRequest)
    )
    with get_db_session() as db:
        return [
            tuple(row)
            for row in db.execute(
                select(ChatRequest.request_id, ChatRequest.session_id, has_snapshot)
                .where(ChatRequest.status == "running", ChatRequest.created_at < cutoff)
                .order_by(ChatRequest.id)
            )
        ]


def _fail_stuck_request(request_id: str, session_pk: int) -> bool:
    """A stuck request with nothing to restore (a monolith one): ``error``, and
    its session's lock freed unless a newer request has taken it.

    An unbound lock (MCP jobs never bind theirs) counts as this request's.
    """
    from sqlalchemy import or_, update

    from src.core.database import get_db_session
    from src.database.models.session import ChatRequest, UserSession

    with get_db_session() as db:
        failed = db.execute(
            update(ChatRequest)
            .where(ChatRequest.request_id == request_id, ChatRequest.status == "running")
            .values(
                status="error",
                error_message=CRASH_RECOVERY_ERROR,
                completed_at=datetime.utcnow(),
            )
            .execution_options(synchronize_session=False)
        ).rowcount
        if failed != 1:
            return False
        db.execute(
            update(UserSession)
            .where(
                UserSession.id == session_pk,
                or_(
                    UserSession.processing_request_id.is_(None),
                    UserSession.processing_request_id == request_id,
                ),
            )
            .values(is_processing=False, processing_started_at=None, processing_request_id=None)
            .execution_options(synchronize_session=False)
        )
        return True


async def recover_stuck_requests() -> int:
    """End the requests a dead worker left behind.

    Called on startup to recover from crashes.  First the orphan sweep
    (``recover_orphaned_generations``): every live Agent-deck turn whose lock is
    no longer refreshed is rolled back, and every failed restore retried.  Then
    every request still ``running`` past ``GRAPH_JOB_HARD_TIMEOUT_SECONDS``: one
    with a generation snapshot is rolled back to Enter; any other (a Legacy deck's
    turn, an MCP job) is marked ``error`` as before, its lock freed unless a newer
    request holds it.  One request's error is logged and the others go on.

    Returns:
        Number of requests recovered
    """
    from src.services.generation_rollback import (
        RollbackResult,
        recover_orphaned_generations,
        roll_back_generation,
    )

    count = 0
    try:
        count += await asyncio.to_thread(recover_orphaned_generations)
    except Exception:
        logger.warning("Orphaned generation sweep failed at startup", exc_info=True)

    for request_id, session_pk, has_snapshot in await asyncio.to_thread(_stuck_requests):
        try:
            if has_snapshot:
                result = await asyncio.to_thread(
                    roll_back_generation,
                    request_id,
                    terminal_status="error",
                    error_message=CRASH_RECOVERY_ERROR,
                    refuse_on_foreign_change=False,
                )
                recovered = result is not RollbackResult.NOT_LIVE
            else:
                recovered = await asyncio.to_thread(
                    _fail_stuck_request, request_id, session_pk
                )
        except Exception:
            logger.exception(
                "Could not recover a stuck request", extra={"request_id": request_id}
            )
            continue
        if recovered:
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

    A timed-out graph job (an Agent deck's turn) is also rolled back to Enter
    (``error``, the same text, never refused on a foreign change), in a worker
    thread.  Its consumer then sees the turn is no longer live and frees the
    runner, though the graph thread may still be blocked.  A monolith job is
    only marked: it does NOT cancel the underlying worker coroutine, and a stuck
    worker slot remains occupied until the next app restart.  See the spec's
    Error Handling section for the reasoning behind this choice.  One entry's
    rollback error is logged and the sweep goes on.

    Returns:
        Number of jobs marked failed in this sweep (useful for logging).
    """
    from src.services.generation_rollback import roll_back_generation

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
        if entry.get("engine_mode") != "graph":
            continue
        try:
            await asyncio.to_thread(
                roll_back_generation,
                request_id,
                terminal_status="error",
                error_message=entry["error"],
                refuse_on_foreign_change=False,
            )
        except Exception:
            logger.warning(
                "Could not roll back a timed-out graph turn",
                exc_info=True,
                extra={"request_id": request_id},
            )

    return marked


async def refresh_job_session_locks_once() -> int:
    """Refresh the session lock of every turn this process holds, pending or running.

    A session lock goes stale after ``SESSION_LOCK_TIMEOUT_SECONDS`` (300 s), while a
    graph turn may run for ``GRAPH_JOB_HARD_TIMEOUT_SECONDS`` and a queued turn waits
    first.  Without this a second turn on the same session could take the stale lock
    and run alongside the first.  A failed refresh is logged and the others go on.

    A graph entry refreshes its session's lock only while the lock is bound to its
    own request: an entry whose turn was stopped while it was queued must not keep
    a newer request's lock alive (that request's process may have died).  A
    monolith entry (a Legacy deck's turn, an MCP job) refreshes whatever its
    session holds, as before.

    Returns:
        Number of locks refreshed.
    """
    from src.api.services.session_manager import get_session_manager

    now = datetime.utcnow()

    def _alive(entry: Dict[str, Any]) -> bool:
        if entry.get("status") == "running":
            return True
        if entry.get("status") != "pending":
            return False
        # A turn queued past its hard timeout is not kept alive: if every runner is
        # held by a timed-out zombie it never starts, and its lock must go stale
        # rather than lock the user out of the session until a restart.
        queued_at = entry.get("queued_at")
        limit = job_hard_timeout_seconds(entry.get("engine_mode"))
        return queued_at is None or queued_at > now - timedelta(seconds=limit)

    # (session_id, request id the lock must be bound to, or None for any).
    targets = {
        (entry["session_id"], request_id if entry.get("engine_mode") == "graph" else None)
        for request_id, entry in list(jobs.items())
        if entry.get("session_id") and _alive(entry)
    }
    if not targets:
        return 0
    manager = get_session_manager()
    refreshed = 0
    for session_id, bound_to in targets:
        try:
            if bound_to is None:
                ok = await asyncio.to_thread(manager.refresh_session_lock, session_id)
            else:
                ok = await asyncio.to_thread(
                    manager.refresh_session_lock, session_id, request_id=bound_to
                )
            if ok:
                refreshed += 1
        except Exception:
            logger.warning(
                "Session lock refresh failed",
                exc_info=True,
                extra={"session_id": session_id},
            )
    return refreshed


async def mark_timed_out_jobs_loop() -> None:
    """Background loop: every 60 seconds, keeps held session locks live and marks timed-out jobs.

    Runs ``mark_timed_out_jobs_once()``, then ``refresh_job_session_locks_once()``,
    then ``recover_orphaned_generations()`` in a worker thread (it restores decks):
    every process sweeps every Agent-deck turn whose job is gone, and retries
    every failed restore.

    Started in the FastAPI lifespan alongside the existing chat/export workers
    and request-log cleanup loop. Survives its own exceptions so a single
    transient failure does not take the loop down for the lifetime of the
    process. Responds to ``asyncio.CancelledError`` for clean shutdown.
    """
    from src.services import generation_rollback

    while True:
        try:
            await asyncio.sleep(TIMEOUT_SWEEP_INTERVAL_SECONDS)
            # Mark first, so a turn that just timed out is not refreshed once more.
            marked = await mark_timed_out_jobs_once()
            await refresh_job_session_locks_once()
            # After the refresh, so this process's own live turns are fresh.
            try:
                await asyncio.to_thread(generation_rollback.recover_orphaned_generations)
            except Exception:
                logger.warning("Orphaned generation sweep failed", exc_info=True)
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
