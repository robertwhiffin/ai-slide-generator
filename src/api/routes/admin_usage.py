"""Admin usage-analytics endpoints (ungated, like the rest of /admin)."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.api.services.usage_service import ALLOWED_WINDOWS, UsageService
from src.core.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/usage", tags=["admin-usage"])


def _validated_days(days: int) -> int:
    if days not in ALLOWED_WINDOWS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"days must be one of {sorted(ALLOWED_WINDOWS)}",
        )
    return days


def _handle(callable_, *args, **kwargs):
    try:
        return callable_(*args, **kwargs)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Usage analytics error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to compute usage analytics",
        )


@router.get("/summary")
def get_summary(days: int = Query(default=7), db: Session = Depends(get_db)):
    days = _validated_days(days)
    return _handle(UsageService().get_summary, db, days=days)


@router.get("/daily")
def get_daily(days: int = Query(default=7), db: Session = Depends(get_db)):
    days = _validated_days(days)
    return _handle(UsageService().get_daily, db, days=days)


@router.get("/top-users")
def get_top_users(days: int = Query(default=7), db: Session = Depends(get_db)):
    days = _validated_days(days)
    return _handle(UsageService().get_top_users, db, days=days)


@router.get("/funnel")
def get_funnel(days: int = Query(default=7), db: Session = Depends(get_db)):
    days = _validated_days(days)
    return _handle(UsageService().get_funnel, db, days=days)


@router.get("/retention")
def get_retention(db: Session = Depends(get_db)):
    return _handle(UsageService().get_retention, db)


@router.get("/heatmap")
def get_heatmap(days: int = Query(default=7), db: Session = Depends(get_db)):
    days = _validated_days(days)
    return _handle(UsageService().get_heatmap, db, days=days)
