"""Chat endpoint for sending messages to the AI agent.

Supports:
- POST /api/chat - Synchronous response
- POST /api/chat/stream - Server-Sent Events for real-time updates
- POST /api/chat/async - Submit for async processing (polling-based)
- GET /api/chat/poll/{request_id} - Poll for async request status

When session_id is omitted, a new session is created automatically.

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
from src.services.permission_service import get_permission_service, PERMISSION_PRIORITY

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


def _get_default_style_id() -> int | None:
    """Return the ID of the default slide style (is_default=True, is_active=True), or None."""
    from src.core.database import get_db_session
    from src.database.models import SlideStyleLibrary

    try:
        with get_db_session() as db:
            # Primary: explicit default
            style = (
                db.query(SlideStyleLibrary.id)
                .filter(
                    SlideStyleLibrary.is_default == True,  # noqa: E712
                    SlideStyleLibrary.is_active == True,  # noqa: E712
                )
                .first()
            )
            if style:
                return style.id

            # Fallback: system style (defensive, for mid-migration)
            style = (
                db.query(SlideStyleLibrary.id)
                .filter(
                    SlideStyleLibrary.is_system == True,  # noqa: E712
                    SlideStyleLibrary.is_active == True,  # noqa: E712
                )
                .first()
            )
            return style.id if style else None
    except Exception:
        # Column may not exist yet (pre-migration)
        return None


def _check_chat_permission(session_id: str, db: DBSession) -> None:
    """Verify user can send chat messages in this session.

    Conversations are always private. A user can chat only if:
    1. They are the session creator (owner session), OR
    2. This is their own contributor session AND they have CAN_EDIT or CAN_MANAGE
       on the parent deck via deck_contributors.

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

    # Contributor session: must be the creator AND have at least CAN_EDIT on the parent deck
    if is_creator and is_contributor:
        parent_internal_id = session_info.get("parent_session_internal_id")
        ctx = get_permission_context()
        if parent_internal_id is not None and ctx:
            perm_service = get_permission_service()
            permission = perm_service.get_deck_permission(
                db,
                session_id=parent_internal_id,
                user_id=ctx.user_id,
                user_name=ctx.user_name,
                group_ids=ctx.group_ids,
            )
            if permission and PERMISSION_PRIORITY.get(permission, 0) >= PERMISSION_PRIORITY.get(PermissionLevel.CAN_EDIT, 0):
                # Permission OK — now check editing lock on the parent deck
                try:
                    session_manager.require_editing_lock(session_id)
                except PermissionError as e:
                    raise HTTPException(status_code=423, detail=str(e))
                return

        raise HTTPException(
            status_code=403,
            detail="You have view-only access to this presentation. Editors and managers can use chat to modify slides.",
        )

    raise HTTPException(
        status_code=403,
        detail="You can only chat in your own session. Use your contributor session for shared presentations.",
    )


def _maybe_create_session(request: ChatRequest, session_manager) -> bool:
    """Create a session if request.session_id is missing, or sync agent_config if provided.

    Mutates request.session_id in place.
    Returns True if a new session was created, False otherwise.
    """
    from src.api.schemas.agent_config import AgentConfig

    # Parse explicit agent_config from request (None if not sent by client)
    explicit_config = None
    if request.agent_config:
        config = AgentConfig.model_validate(request.agent_config)
        explicit_config = config.model_dump()

    # Build full agent_config_data with defaults (used for session creation)
    agent_config_data = explicit_config or AgentConfig().model_dump()
    if agent_config_data.get("slide_style_id") is None:
        default_id = _get_default_style_id()
        if default_id is not None:
            agent_config_data["slide_style_id"] = default_id

    if request.session_id:
        # Session ID provided — only sync if client explicitly sent agent_config
        if explicit_config:
            try:
                session_manager.get_session(request.session_id)
                # Session exists — update agent_config via DB
                from src.core.database import get_db_session
                from src.database.models import UserSession

                with get_db_session() as db:
                    session = db.query(UserSession).filter(
                        UserSession.session_id == request.session_id
                    ).first()
                    if session:
                        session.agent_config = agent_config_data
                        logger.info(
                            "Synced agent_config from chat request",
                            extra={"session_id": request.session_id},
                        )
            except SessionNotFoundError:
                # Session ID was generated client-side but never persisted.
                # Create it now with the agent_config.
                current_user = get_current_user()
                session_manager.create_session(
                    session_id=request.session_id,
                    agent_config=agent_config_data,
                    created_by=current_user,
                )
                logger.info(
                    "Created session from client-generated ID with agent_config",
                    extra={"session_id": request.session_id},
                )
                return True
            except Exception as e:
                logger.warning(f"Failed to sync agent_config: {e}")
        return False

    current_user = get_current_user()
    session = session_manager.create_session(
        agent_config=agent_config_data,
        created_by=current_user,
    )
    request.session_id = session["session_id"]
    return True


@router.post("/chat", response_model=ChatResponse)
async def send_message(
    request: ChatRequest,
    db: DBSession = Depends(get_db),
) -> ChatResponse:
    """Send a message to the AI agent and receive response with slides.

    If session_id is not provided, a new session is created automatically.
    Requires CAN_EDIT or higher permission on the session.
    Uses asyncio.to_thread to avoid blocking the event loop during LLM calls.

    Args:
        request: Chat request with optional session_id and message

    Returns:
        Chat response with messages, slide_deck, metadata, and session_id

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

    # Create session on the fly if none provided
    created = await asyncio.to_thread(_maybe_create_session, request, session_manager)
    new_session_id = request.session_id if created else None

    # Acquire session lock to prevent concurrent modifications
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

        response_data = {**result}
        if new_session_id:
            response_data["session_id"] = new_session_id

        return ChatResponse(**response_data)

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

    If session_id is not provided, a new session is created and a
    SESSION_CREATED event is emitted as the first SSE event.

    This endpoint yields Server-Sent Events as the agent executes:
    - session_created: New session was created (includes session_id)
    - assistant: LLM text responses
    - tool_call: Tool invocation started
    - tool_result: Tool returned result
    - error: Error occurred
    - complete: Generation finished with final slides

    Requires CAN_EDIT or higher permission on the session.

    Args:
        request: Chat request with optional session_id and message

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

    # Create session on the fly if none provided
    created = await asyncio.to_thread(_maybe_create_session, request, session_manager)
    new_session_id = request.session_id if created else None

    # Acquire session lock to prevent concurrent modifications
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

        # Emit SESSION_CREATED event first if we just created a session
        if new_session_id:
            session_created_event = StreamEvent(
                type=StreamEventType.SESSION_CREATED,
                session_id=new_session_id,
            )
            yield session_created_event.to_sse()

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

    If session_id is not provided, a new session is created automatically.

    Use this endpoint when SSE streaming is not available (e.g., Databricks Apps
    behind a reverse proxy with connection timeouts).

    Requires CAN_EDIT or higher permission on the session.

    Flow:
    1. POST /api/chat/async -> returns request_id (and session_id if created)
    2. Poll GET /api/chat/poll/{request_id} until status is completed/error

    Args:
        request: Chat request with optional session_id and message

    Returns:
        Dictionary with request_id, status, and session_id (if created)

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
    current_user = get_current_user()

    # Create session on the fly if none provided
    created = await asyncio.to_thread(_maybe_create_session, request, session_manager)
    new_session_id = request.session_id if created else None

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
        # Create request record
        request_id = await asyncio.to_thread(
            session_manager.create_chat_request,
            request.session_id,
            current_user,
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

        result = {"request_id": request_id, "status": "pending"}
        if new_session_id:
            result["session_id"] = new_session_id
        return result

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
