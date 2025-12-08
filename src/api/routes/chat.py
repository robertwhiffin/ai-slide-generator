"""Chat endpoint for sending messages to the AI agent.

Requires a valid session_id. Create sessions via POST /api/sessions.

Supports:
- POST /api/chat - Synchronous response
- POST /api/chat/stream - Server-Sent Events for real-time updates
- POST /api/chat/async - Submit for async processing (polling-based)
- GET /api/chat/poll/{request_id} - Poll for async request status
"""

import asyncio
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from src.api.schemas.requests import ChatRequest
from src.api.schemas.responses import ChatResponse
from src.api.schemas.streaming import StreamEvent, StreamEventType
from src.api.services.chat_service import get_chat_service
from src.api.services.job_queue import enqueue_job
from src.api.services.session_manager import SessionNotFoundError, get_session_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def send_message(request: ChatRequest) -> ChatResponse:
    """Send a message to the AI agent and receive response with slides.

    Requires a valid session_id. Create sessions via POST /api/sessions first.
    Uses asyncio.to_thread to avoid blocking the event loop during LLM calls.

    Args:
        request: Chat request with session_id and message

    Returns:
        Chat response with messages, slide_deck, and metadata

    Raises:
        HTTPException: 404 if session not found, 409 if session busy, 500 if agent fails
    """
    logger.info(
        "Received chat request",
        extra={
            "message_length": len(request.message),
            "session_id": request.session_id,
        },
    )

    session_manager = get_session_manager()

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

        # Run blocking LLM call in thread pool
        result = await asyncio.to_thread(
            chat_service.send_message,
            request.session_id,
            request.message,
            request.slide_context.model_dump() if request.slide_context else None,
        )

        return ChatResponse(**result)

    except SessionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Session not found: {request.session_id}. Create a session first via POST /api/sessions",
        )
    except Exception as e:
        logger.error(f"Chat request failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process message: {str(e)}",
        ) from e
    finally:
        # Always release the lock
        await asyncio.to_thread(
            session_manager.release_session_lock,
            request.session_id,
        )


@router.post("/chat/stream")
async def send_message_streaming(request: ChatRequest) -> StreamingResponse:
    """Send a message and receive real-time streaming updates via SSE.

    This endpoint yields Server-Sent Events as the agent executes:
    - assistant: LLM text responses
    - tool_call: Tool invocation started
    - tool_result: Tool returned result
    - error: Error occurred
    - complete: Generation finished with final slides

    Args:
        request: Chat request with session_id and message

    Returns:
        StreamingResponse with SSE events

    Raises:
        HTTPException: 409 if session busy
    """
    logger.info(
        "Received streaming chat request",
        extra={
            "message_length": len(request.message),
            "session_id": request.session_id,
        },
    )

    session_manager = get_session_manager()

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

        event_queue: queue.Queue = queue.Queue()
        error_holder: list = []
        
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
                ):
                    event_queue.put(event)
            except Exception as e:
                error_holder.append(e)
            finally:
                event_queue.put(None)  # Signal completion

        # Start streaming thread
        thread = threading.Thread(target=run_streaming, daemon=True)
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
            # Always release the lock
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
async def submit_chat_async(request: ChatRequest):
    """Submit a chat request for async processing (polling-based).

    Use this endpoint when SSE streaming is not available (e.g., Databricks Apps
    behind a reverse proxy with connection timeouts).

    Flow:
    1. POST /api/chat/async -> returns request_id
    2. Poll GET /api/chat/poll/{request_id} until status is completed/error

    Args:
        request: Chat request with session_id and message

    Returns:
        Dictionary with request_id and initial status

    Raises:
        HTTPException: 409 if session busy
    """
    logger.info(
        "Received async chat request",
        extra={
            "message_length": len(request.message),
            "session_id": request.session_id,
        },
    )

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
        # Create request record
        request_id = await asyncio.to_thread(
            session_manager.create_chat_request, request.session_id
        )

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
