"""Chat endpoint for sending messages to the AI agent.

Requires a valid session_id. Create sessions via POST /api/sessions.
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException

from src.api.schemas.requests import ChatRequest
from src.api.schemas.responses import ChatResponse
from src.api.services.chat_service import get_chat_service
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
