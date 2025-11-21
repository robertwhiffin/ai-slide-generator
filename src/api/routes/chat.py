"""Chat endpoint for sending messages to the AI agent.

Phase 1: Single session endpoint.
Phase 4: Add session management with session_id parameter.
"""

import logging

from fastapi import APIRouter, HTTPException

from src.api.models.requests import ChatRequest
from src.api.models.responses import ChatResponse
from src.api.services.chat_service import get_chat_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def send_message(request: ChatRequest) -> ChatResponse:
    """Send a message to the AI agent and receive response with slides.
    
    Phase 1: Uses single global session.
    Phase 4: Will accept session_id in request body.
    
    Args:
        request: Chat request with message and max_slides
    
    Returns:
        Chat response with messages, slide_deck, and metadata
    
    Raises:
        HTTPException: 500 if agent fails to generate slides
    """
    logger.info(
        "Received chat request",
        extra={
            "message_length": len(request.message),
            "max_slides": request.max_slides,
        },
    )

    try:
        # Get service instance (Phase 1: global singleton)
        chat_service = get_chat_service()

        # Process message
        result = chat_service.send_message(
            message=request.message,
            max_slides=request.max_slides,
            slide_context=request.slide_context.model_dump() if request.slide_context else None,
        )

        # Return response
        return ChatResponse(**result)

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
        "phase": "Phase 1 MVP",
    }

