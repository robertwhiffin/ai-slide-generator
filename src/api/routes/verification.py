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
    trace_id: Optional[str] = None  # MLflow trace ID to link feedback to


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
            # No Genie data found - verification cannot be performed
            # Return "unknown" rating instead of misleading "excellent"
            return VerifySlideResponse(
                score=0,
                rating="unknown",
                explanation="No source data available for verification. This may be a title slide or slides generated without data queries.",
                issues=[{"type": "no_data", "detail": "No Genie query results found in session"}],
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

    Feedback is logged to MLflow as a structured Assessment using log_feedback().
    This enables:
    - Proper labeling workflow in MLflow UI
    - Aggregation and querying of human feedback
    - Quality monitoring over time
    - Improving the judge prompt based on patterns

    Args:
        slide_index: Index of the slide
        request: FeedbackRequest with feedback details and trace_id

    Returns:
        Confirmation of feedback submission with trace linkage info
    """
    import mlflow
    from mlflow.entities import AssessmentSource, AssessmentSourceType

    feedback_data = {
        "session_id": request.session_id,
        "slide_index": slide_index,
        "is_positive": request.is_positive,
        "rationale": request.rationale,
        "trace_id": request.trace_id,
    }

    feedback_logged = False

    try:
        # Set MLflow tracking URI to Databricks (same as evaluation)
        mlflow.set_tracking_uri("databricks")
        
        # Log feedback using MLflow's log_feedback API (proper Assessment structure)
        if request.trace_id:
            try:
                from mlflow import MlflowClient
                
                # First, verify the trace exists
                client = MlflowClient(tracking_uri="databricks")
                try:
                    # Try to get the trace to verify it exists
                    trace_info = client.get_trace(request.trace_id)
                    logger.info(f"Found trace: {request.trace_id}")
                except Exception as trace_error:
                    logger.warning(f"Trace not found in MLflow: {trace_error}")
                    raise
                
                # Create assessment source (human feedback)
                source = AssessmentSource(
                    source_type=AssessmentSourceType.HUMAN,
                    source_id=f"session_{request.session_id[:8]}",  # Truncate for readability
                )

                # Log as structured feedback/assessment
                mlflow.log_feedback(
                    trace_id=request.trace_id,
                    name="human_verification_feedback",
                    value=request.is_positive,  # True/False
                    rationale=request.rationale or (
                        "User confirmed verification is accurate"
                        if request.is_positive
                        else "User indicated verification has issues"
                    ),
                    source=source,
                    metadata={
                        "session_id": request.session_id,
                        "slide_index": slide_index,
                        "feedback_type": "positive" if request.is_positive else "negative",
                    },
                )

                feedback_logged = True

                logger.info(
                    "Feedback logged as Assessment to trace",
                    extra={
                        "trace_id": request.trace_id,
                        "is_positive": request.is_positive,
                    },
                )

            except Exception as feedback_error:
                logger.error(
                    f"Failed to log feedback as assessment: {feedback_error}",
                    extra={"trace_id": request.trace_id},
                )
                # Don't fallback to tags - Assessments are the proper structure
                # If this fails, something is wrong with MLflow setup
        else:
            logger.warning(
                "Feedback submitted without trace_id - cannot link to verification",
                extra=feedback_data,
            )

        logger.info(
            "Verification feedback submitted",
            extra=feedback_data,
        )

        return {
            "status": "success",
            "message": "Feedback submitted successfully",
            "linked_to_trace": request.trace_id is not None,
            "feedback_logged": feedback_logged,
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
    """Get the Genie conversation deep-link for a session.

    Returns the URL to view the full Genie conversation with all queries
    and results that contributed to slide generation.

    URL format: {host}/genie/rooms/{space_id}/chats/{conversation_id}?o={workspace_id}

    Args:
        session_id: Session identifier

    Returns:
        Genie conversation URL and metadata
    """
    import re

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

        from src.core.settings_db import get_settings

        settings = get_settings()
        workspace_url = settings.databricks_host.rstrip("/")
        space_id = settings.genie.space_id

        # Extract workspace_id from databricks host URL
        # Format: https://adb-{workspace_id}.{region}.azuredatabricks.net
        # or: https://{workspace}.cloud.databricks.com (workspace_id in different location)
        workspace_id = None
        match = re.search(r"adb-(\d+)", workspace_url)
        if match:
            workspace_id = match.group(1)

        # Build deep-link URL to specific conversation
        # Format: {host}/genie/rooms/{space_id}/chats/{conversation_id}?o={workspace_id}
        if workspace_id:
            genie_url = (
                f"{workspace_url}/genie/rooms/{space_id}/chats/{genie_conversation_id}"
                f"?o={workspace_id}"
            )
        else:
            # Fallback: try without workspace_id parameter
            genie_url = f"{workspace_url}/genie/rooms/{space_id}/chats/{genie_conversation_id}"

        logger.info(
            "Generated Genie deep-link",
            extra={
                "session_id": session_id,
                "conversation_id": genie_conversation_id,
                "workspace_id": workspace_id,
                "url": genie_url,
            },
        )

        return {
            "has_genie_conversation": True,
            "conversation_id": genie_conversation_id,
            "workspace_id": workspace_id,
            "url": genie_url,
            "message": "Opens Genie conversation with all queries used for this session.",
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

