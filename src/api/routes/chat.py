"""Chat endpoint for sending messages to the AI agent.

Requires a valid session_id. Create sessions via POST /api/sessions.

Supports:
- POST /api/chat - Synchronous response
- POST /api/chat/stream - Server-Sent Events for real-time updates
- POST /api/chat/async - Submit for async processing (polling-based)
- GET /api/chat/poll/{request_id} - Poll for async request status

Chat access is controlled by session permissions:
- CAN_EDIT or CAN_MANAGE required to send messages (creates/modifies slides)
"""

import asyncio
import contextvars
import logging
from typing import AsyncGenerator, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session as DBSession

from src.api.schemas.requests import ChatRequest
from src.api.schemas.responses import ChatResponse
from src.api.schemas.streaming import StreamEvent, StreamEventType
from src.api.services.chat_service import get_chat_service
from src.api.services.job_queue import enqueue_job
from src.api.services.session_manager import SessionNotFoundError, get_session_manager
from src.core.context_utils import run_in_thread_with_context
from src.core.database import get_db
from src.core.permission_context import get_permission_context
from src.core.user_context import get_current_user
from src.database.models.profile_contributor import PermissionLevel
from src.services.permission_service import PermissionService, PERMISSION_PRIORITY

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


def _check_chat_permission(session_id: str, db: DBSession) -> None:
    """Verify user can send chat messages in this session.

    Conversations are always private. A user can chat only if:
    1. They are the session creator (owner session), OR
    2. This is their own contributor session AND they have CAN_EDIT or CAN_MANAGE

    Viewers get a contributor session so they can see the shared slide deck,
    but they cannot chat (which would modify slides).

    Args:
        session_id: Session identifier
        db: Database session

    Raises:
        HTTPException 403: If user doesn't have permission
    """
    session_manager = get_session_manager()
    current_user = get_current_user()

    try:
        session_info = session_manager.get_session(session_id)
    except SessionNotFoundError:
        return

    is_creator = session_info.get("created_by") == current_user
    is_contributor = session_info.get("is_contributor_session", False)

    # Owner of a root session can always chat
    if is_creator and not is_contributor:
        return

    # Contributor session: must be the creator AND have at least CAN_EDIT on the profile
    if is_creator and is_contributor:
        profile_id = session_info.get("profile_id")
        ctx = get_permission_context()
        if profile_id and ctx:
            perm_service = PermissionService(db)
            permission = perm_service.get_user_permission(
                profile_id=profile_id,
                user_id=ctx.user_id,
                user_name=ctx.user_name,
                group_ids=ctx.group_ids,
            )
            if permission and PERMISSION_PRIORITY.get(permission, 0) >= PERMISSION_PRIORITY.get(PermissionLevel.CAN_EDIT, 0):
                return

        raise HTTPException(
            status_code=403,
            detail="You have view-only access to this presentation. Editors and managers can use chat to modify slides.",
        )

    raise HTTPException(
        status_code=403,
        detail="You can only chat in your own session. Use your contributor session for shared presentations.",
    )


@router.post("/chat", response_model=ChatResponse)
async def send_message(
    request: ChatRequest,
    db: DBSession = Depends(get_db),
) -> ChatResponse:
    """Send a message to the AI agent and receive response with slides.

    Requires a valid session_id. Create sessions via POST /api/sessions first.
    Requires CAN_EDIT or higher permission on the session.
    Uses asyncio.to_thread to avoid blocking the event loop during LLM calls.

    Args:
        request: Chat request with session_id and message

    Returns:
        Chat response with messages, slide_deck, and metadata

    Raises:
        HTTPException: 403 if no permission, 404 if session not found, 409 if session busy, 500 if agent fails
    """
    logger.info(
        "Received chat request",
        extra={
            "message_length": len(request.message),
            "session_id": request.session_id,
        },
    )

    # Check permission before processing
    _check_chat_permission(request.session_id, db)

    session_manager = get_session_manager()

    # Per-session lock prevents concurrent request processing
    locked = await asyncio.to_thread(
        session_manager.acquire_session_lock,
        request.session_id,
    )
    if not locked:
        raise HTTPException(
            status_code=409,
            detail="Session is currently processing another request. Please wait.",
        )

    try:
        chat_service = get_chat_service()

        result = await run_in_thread_with_context(
            chat_service.send_message,
            request.session_id,
            request.message,
            request.slide_context.model_dump() if request.slide_context else None,
            request.image_ids,
        )

        return ChatResponse(**result)

    except SessionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Session not found: {request.session_id}. Create a session first via POST /api/sessions",
        )
    except PermissionError as e:
        raise HTTPException(status_code=423, detail=str(e))
    except Exception as e:
        logger.error(f"Chat request failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process message: {str(e)}",
        ) from e
    finally:
        await asyncio.to_thread(
            session_manager.release_session_lock,
            request.session_id,
        )


@router.post("/chat/stream")
async def send_message_streaming(
    request: ChatRequest,
    db: DBSession = Depends(get_db),
) -> StreamingResponse:
    """Send a message and receive real-time streaming updates via SSE.

    This endpoint yields Server-Sent Events as the agent executes:
    - assistant: LLM text responses
    - tool_call: Tool invocation started
    - tool_result: Tool returned result
    - error: Error occurred
    - complete: Generation finished with final slides

    Requires CAN_EDIT or higher permission on the session.

    Args:
        request: Chat request with session_id and message

    Returns:
        StreamingResponse with SSE events

    Raises:
        HTTPException: 403 if no permission, 409 if session busy
    """
    logger.info(
        "Received streaming chat request",
        extra={
            "message_length": len(request.message),
            "session_id": request.session_id,
        },
    )

    # Check permission before processing
    _check_chat_permission(request.session_id, db)

    session_manager = get_session_manager()
    current_user = get_current_user()

    # Per-session lock prevents concurrent request processing
    locked = await asyncio.to_thread(
        session_manager.acquire_session_lock,
        request.session_id,
    )
    if not locked:
        raise HTTPException(
            status_code=409,
            detail="Session is currently processing another request. Please wait.",
        )

    async def generate_events() -> AsyncGenerator[str, None]:
        """Generate SSE events from the chat service."""
        import queue
        import threading

        event_queue: queue.Queue = queue.Queue()
        error_holder: list = []

        # Capture context BEFORE starting thread to preserve user auth
        ctx = contextvars.copy_context()

        def run_streaming():
            """Run streaming in a separate thread, pushing events to queue."""
            try:
                chat_service = get_chat_service()
                for event in chat_service.send_message_streaming(
                    session_id=request.session_id,
                    message=request.message,
                    slide_context=request.slide_context.model_dump()
                    if request.slide_context
                    else None,
                    image_ids=request.image_ids,
                ):
                    event_queue.put(event)
            except Exception as e:
                error_holder.append(e)
            finally:
                event_queue.put(None)  # Signal completion

        # Start streaming thread with context preserved
        thread = threading.Thread(target=lambda: ctx.run(run_streaming), daemon=True)
        thread.start()

        try:
            # Yield events as they arrive
            while True:
                # Use asyncio to check queue without blocking event loop
                event = await asyncio.to_thread(event_queue.get)
                if event is None:
                    break
                yield event.to_sse()

            # Check for errors after completion
            if error_holder:
                error = error_holder[0]
                if isinstance(error, SessionNotFoundError):
                    error_event = StreamEvent(
                        type=StreamEventType.ERROR,
                        error=f"Session not found: {request.session_id}",
                    )
                else:
                    logger.error(f"Streaming chat request failed: {error}", exc_info=True)
                    error_event = StreamEvent(
                        type=StreamEventType.ERROR,
                        error=f"Failed to process message: {str(error)}",
                    )
                yield error_event.to_sse()

        finally:
            await asyncio.to_thread(
                session_manager.release_session_lock,
                request.session_id,
            )

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.get("/health")
async def health_check():
    """Health check endpoint.

    Returns:
        Status information
    """
    return {
        "status": "healthy",
        "service": "AI Slide Generator",
    }


@router.post("/chat/async")
async def submit_chat_async(
    request: ChatRequest,
    db: DBSession = Depends(get_db),
):
    """Submit a chat request for async processing (polling-based).

    Use this endpoint when SSE streaming is not available (e.g., Databricks Apps
    behind a reverse proxy with connection timeouts).

    Requires CAN_EDIT or higher permission on the session.

    Flow:
    1. POST /api/chat/async -> returns request_id
    2. Poll GET /api/chat/poll/{request_id} until status is completed/error

    Args:
        request: Chat request with session_id and message

    Returns:
        Dictionary with request_id and initial status

    Raises:
        HTTPException: 403 if no permission, 409 if session busy
    """
    logger.info(
        "Received async chat request",
        extra={
            "message_length": len(request.message),
            "session_id": request.session_id,
        },
    )

    # Check permission before processing
    _check_chat_permission(request.session_id, db)

    session_manager = get_session_manager()

    # Check session lock first
    locked = await asyncio.to_thread(
        session_manager.acquire_session_lock, request.session_id
    )
    if not locked:
        raise HTTPException(
            status_code=409,
            detail="Session is already processing a request",
        )

    try:
        # Get current profile info for session association
        from src.core.settings_db import get_settings
        settings = get_settings()
        profile_id = getattr(settings, 'profile_id', None)
        profile_name = getattr(settings, 'profile_name', None)

        # Create request record with profile info
        request_id = await asyncio.to_thread(
            session_manager.create_chat_request,
            request.session_id,
            profile_id,
            profile_name,
        )

        # Capture first-message flag BEFORE persisting the user message,
        # because add_message increments message_count.
        session_data = await asyncio.to_thread(
            session_manager.get_session, request.session_id
        )
        is_first_message = session_data.get("message_count", 0) == 0

        # Persist user message
        await asyncio.to_thread(
            session_manager.add_message,
            session_id=request.session_id,
            role="user",
            content=request.message,
            message_type="user_query",
            request_id=request_id,
        )

        # Queue for processing
        await enqueue_job(
            request_id,
            {
                "session_id": request.session_id,
                "message": request.message,
                "slide_context": (
                    request.slide_context.model_dump() if request.slide_context else None
                ),
                "is_first_message": is_first_message,
                "image_ids": request.image_ids,
            },
        )

        return {"request_id": request_id, "status": "pending"}

    except Exception as e:
        # Release lock on failure
        await asyncio.to_thread(
            session_manager.release_session_lock, request.session_id
        )
        logger.error(f"Failed to submit async chat: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chat/poll/{request_id}")
async def poll_chat(
    request_id: str,
    after_message_id: int = Query(default=0, description="Return messages after this ID"),
):
    """Poll for chat request status and new messages.

    Returns the current request status and any new messages since
    the last poll (based on after_message_id).

    Args:
        request_id: Request ID from submit_chat_async
        after_message_id: Return messages with ID greater than this

    Returns:
        Dictionary with status, events, last_message_id, and result

    Raises:
        HTTPException: 404 if request not found
    """
    session_manager = get_session_manager()

    chat_request = await asyncio.to_thread(
        session_manager.get_chat_request, request_id
    )

    if not chat_request:
        raise HTTPException(status_code=404, detail="Request not found")

    messages = await asyncio.to_thread(
        session_manager.get_messages_for_request, request_id, after_message_id
    )

    events = [session_manager.msg_to_stream_event(m) for m in messages]

    return {
        "status": chat_request["status"],
        "events": events,
        "last_message_id": messages[-1]["id"] if messages else after_message_id,
        "result": chat_request.get("result") if chat_request["status"] == "completed" else None,
        "error": chat_request.get("error_message") if chat_request["status"] == "error" else None,
    }
