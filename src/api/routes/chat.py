"""Chat endpoint for sending messages to the AI agent.

Requires a valid session_id. Create sessions via POST /api/sessions.
"""

import logging

from fastapi import APIRouter, HTTPException

from src.api.schemas.requests import ChatRequest
from src.api.schemas.responses import ChatResponse
from src.api.services.chat_service import get_chat_service
from src.api.services.session_manager import SessionNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def send_message(request: ChatRequest) -> ChatResponse:
    """Send a message to the AI agent and receive response with slides.

    Requires a valid session_id. Create sessions via POST /api/sessions first.

    Args:
        request: Chat request with session_id and message

    Returns:
        Chat response with messages, slide_deck, and metadata

    Raises:
        HTTPException: 404 if session not found, 500 if agent fails
    """
    logger.info(
        "Received chat request",
        extra={
            "message_length": len(request.message),
            "session_id": request.session_id,
        },
    )

    try:
        chat_service = get_chat_service()

        result = chat_service.send_message(
            session_id=request.session_id,
            message=request.message,
            slide_context=request.slide_context.model_dump() if request.slide_context else None,
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
