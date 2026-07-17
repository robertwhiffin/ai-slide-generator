"""Feedback and survey API endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.api.schemas.feedback import (
    FeedbackChatRequest,
    FeedbackChatResponse,
    FeedbackSubmitRequest,
    FeedbackSubmitResponse,
    SurveySubmitRequest,
    SurveySubmitResponse,
)
from src.api.routes._authz import require_admin
from src.api.services.feedback_service import FeedbackService
from src.core.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/feedback", tags=["feedback"])


@router.post("/chat", response_model=FeedbackChatResponse)
def feedback_chat(request: FeedbackChatRequest):
    try:
        service = FeedbackService()
        result = service.chat(request.messages)
        return FeedbackChatResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except Exception as e:
        logger.error(f"Feedback chat error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get feedback response",
        )


@router.post("/submit", response_model=FeedbackSubmitResponse)
def submit_feedback(request: FeedbackSubmitRequest, db: Session = Depends(get_db)):
    try:
        service = FeedbackService()
        record = service.submit_feedback(
            db=db,
            category=request.category,
            summary=request.summary,
            severity=request.severity,
            raw_conversation=request.raw_conversation,
        )
        return FeedbackSubmitResponse(id=record.id)
    except Exception as e:
        logger.error(f"Feedback submit error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to submit feedback",
        )


@router.post("/survey", response_model=SurveySubmitResponse)
def submit_survey(request: SurveySubmitRequest, db: Session = Depends(get_db)):
    try:
        service = FeedbackService()
        record = service.submit_survey(
            db=db,
            star_rating=request.star_rating,
            time_saved_minutes=request.time_saved_minutes,
            nps_score=request.nps_score,
        )
        return SurveySubmitResponse(id=record.id)
    except Exception as e:
        logger.error(f"Survey submit error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to submit survey",
        )


@router.get("/report/stats", dependencies=[Depends(require_admin)])
def get_stats_report(weeks: int = Query(default=12, ge=1, le=52), db: Session = Depends(get_db)):
    try:
        service = FeedbackService()
        return service.get_stats_report(db=db, weeks=weeks)
    except Exception as e:
        logger.error(f"Stats report error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate stats report",
        )


@router.get("/list", dependencies=[Depends(require_admin)])
def list_feedback(
    weeks: int = Query(default=12, ge=1, le=52),
    category: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    try:
        service = FeedbackService()
        return service.list_feedback(
            db=db,
            weeks=weeks,
            category=category,
            severity=severity,
            page=page,
            page_size=page_size,
        )
    except Exception as e:
        logger.error(f"Feedback list error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list feedback",
        )


@router.get("/report/summary", dependencies=[Depends(require_admin)])
def get_feedback_summary(weeks: int = Query(default=4, ge=1, le=52), db: Session = Depends(get_db)):
    try:
        service = FeedbackService()
        return service.get_feedback_summary(db=db, weeks=weeks)
    except Exception as e:
        logger.error(f"Feedback summary error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate feedback summary",
        )
