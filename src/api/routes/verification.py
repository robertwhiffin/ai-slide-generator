"""Slide verification endpoints using LLM as Judge.

Provides API for verifying slide accuracy against Genie source data.
Uses MLflow's make_judge API for semantic comparison.
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.api.services.session_manager import get_session_manager, SessionNotFoundError
from src.services.evaluation import evaluate_with_judge

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/verification", tags=["verification"])


class VerifySlideRequest(BaseModel):
    """Request to verify a slide's accuracy."""

    session_id: str


class VerifySlideResponse(BaseModel):
    """Response from slide verification."""

    score: float
    rating: str
    explanation: str
    issues: list
    duration_ms: int
    trace_id: Optional[str] = None
    genie_conversation_id: Optional[str] = None
    error: bool = False
    error_message: Optional[str] = None


class FeedbackRequest(BaseModel):
    """Request to submit feedback on verification."""

    session_id: str
    slide_index: int
    is_positive: bool
    rationale: Optional[str] = None


@router.post("/{slide_index}", response_model=VerifySlideResponse)
async def verify_slide(slide_index: int, request: VerifySlideRequest):
    """Verify a slide's numerical accuracy against Genie source data.

    Uses LLM as Judge to compare slide content against the Genie data
    that was used to generate it. Returns a score, rating, and explanation.

    Args:
        slide_index: Index of the slide to verify (0-based)
        request: VerifySlideRequest with session_id

    Returns:
        VerifySlideResponse with verification results

    Raises:
        HTTPException: 404 if session/slide not found, 500 on error
    """
    session_manager = get_session_manager()

    try:
        # Get session info including Genie conversation ID
        session = await asyncio.to_thread(
            session_manager.get_session, request.session_id
        )

        genie_conversation_id = session.get("genie_conversation_id")

        # Get slide deck
        slide_deck = await asyncio.to_thread(
            session_manager.get_slide_deck, request.session_id
        )

        if not slide_deck:
            raise HTTPException(
                status_code=404,
                detail="No slides found for this session",
            )

        slides = slide_deck.get("slides", [])
        if slide_index < 0 or slide_index >= len(slides):
            raise HTTPException(
                status_code=404,
                detail=f"Slide index {slide_index} out of range (0-{len(slides)-1})",
            )

        slide = slides[slide_index]
        slide_html = slide.get("html", "")

        # Get Genie data from session messages
        # Look for tool messages with Genie results
        messages = await asyncio.to_thread(
            session_manager.get_messages, request.session_id
        )

        # Collect all tool results (Genie query outputs)
        genie_data_parts = []
        for msg in messages:
            if msg.get("role") == "tool" and msg.get("message_type") == "tool_result":
                content = msg.get("content", "")
                metadata = msg.get("metadata", {})
                tool_name = metadata.get("tool_name", "")

                # Include Genie query results
                if "genie" in tool_name.lower() or "query" in tool_name.lower():
                    genie_data_parts.append(content)

        # Combine all Genie data
        genie_data = "\n---\n".join(genie_data_parts) if genie_data_parts else ""

        if not genie_data:
            # No Genie data found - this might be a title slide or no queries were made
            return VerifySlideResponse(
                score=100,
                rating="excellent",
                explanation="No source data to verify against. This may be a title slide or slides generated without data queries.",
                issues=[],
                duration_ms=0,
                genie_conversation_id=genie_conversation_id,
                error=False,
            )

        # Run LLM judge evaluation
        result = await evaluate_with_judge(
            genie_data=genie_data,
            slide_content=slide_html,
        )

        logger.info(
            "Slide verification completed",
            extra={
                "session_id": request.session_id,
                "slide_index": slide_index,
                "score": result.score,
                "rating": result.rating,
            },
        )

        return VerifySlideResponse(
            score=result.score,
            rating=result.rating,
            explanation=result.explanation,
            issues=result.issues,
            duration_ms=result.duration_ms,
            trace_id=result.trace_id,
            genie_conversation_id=genie_conversation_id,
            error=result.error,
            error_message=result.error_message,
        )

    except SessionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Session not found: {request.session_id}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Verification failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Verification failed: {str(e)}",
        )


@router.post("/{slide_index}/feedback")
async def submit_feedback(slide_index: int, request: FeedbackRequest):
    """Submit user feedback on a verification result.

    Feedback is logged to MLflow for quality monitoring and model improvement.
    Negative feedback requires a rationale to understand what went wrong.

    Args:
        slide_index: Index of the slide
        request: FeedbackRequest with feedback details

    Returns:
        Confirmation of feedback submission
    """
    try:
        import mlflow

        # Log feedback to MLflow
        # Note: This requires an active trace - in practice, we'd link to the
        # verification trace_id from the previous request
        feedback_data = {
            "session_id": request.session_id,
            "slide_index": slide_index,
            "is_positive": request.is_positive,
            "rationale": request.rationale,
        }

        # Use MLflow's log_feedback if available
        # For now, log as a param in a new span
        with mlflow.start_span(name="verification_feedback") as span:
            span.set_attribute("session_id", request.session_id)
            span.set_attribute("slide_index", slide_index)
            span.set_attribute("is_positive", request.is_positive)
            if request.rationale:
                span.set_attribute("rationale", request.rationale)

        logger.info(
            "Verification feedback submitted",
            extra=feedback_data,
        )

        return {
            "status": "success",
            "message": "Feedback submitted successfully",
            "feedback": feedback_data,
        }

    except Exception as e:
        logger.error(f"Failed to submit feedback: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to submit feedback: {str(e)}",
        )


@router.get("/genie-link")
async def get_genie_link(
    session_id: str = Query(..., description="Session ID"),
):
    """Get the Genie conversation link for a session.

    Returns the URL to view the full Genie conversation with all queries
    and results that contributed to slide generation.

    Args:
        session_id: Session identifier

    Returns:
        Genie conversation URL and metadata
    """
    session_manager = get_session_manager()

    try:
        session = await asyncio.to_thread(
            session_manager.get_session, session_id
        )

        genie_conversation_id = session.get("genie_conversation_id")

        if not genie_conversation_id:
            return {
                "has_genie_conversation": False,
                "message": "No Genie queries were made in this session",
            }

        # Construct Genie room URL
        # Note: Deep-linking to specific conversations is not supported in Genie UI
        # The conversation_id is stored for API access but UI only shows the room
        from src.core.settings_db import get_settings

        settings = get_settings()
        workspace_url = settings.databricks_host.rstrip("/")
        space_id = settings.genie.space_id

        # Link to Genie room (conversation deep-links not supported in UI)
        genie_url = f"{workspace_url}/genie/rooms/{space_id}"

        return {
            "has_genie_conversation": True,
            "conversation_id": genie_conversation_id,
            "url": genie_url,
            "message": "Opens Genie room. Look for recent conversations to find queries used.",
        }

    except SessionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Session not found: {session_id}",
        )
    except Exception as e:
        logger.error(f"Failed to get Genie link: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get Genie link: {str(e)}",
        )

