"""Admin usage-analytics endpoints (admin-gated, like the rest of /admin)."""

import logging
from datetime import date as dt_date
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.api.routes._authz import require_admin
from src.api.services.usage_service import MAX_WINDOW_DAYS, UsageService
from src.core.database import get_db

logger = logging.getLogger(__name__)

# SDR-4437 MEDIUM-6: workspace-wide usage analytics are admin-only.
router = APIRouter(
    prefix="/api/admin/usage",
    tags=["admin-usage"],
    dependencies=[Depends(require_admin)],
)


def _parse_date(value: str, name: str) -> dt_date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{name} must be a YYYY-MM-DD date",
        )


def _window_kwargs(
    days: int | None,
    start: str | None,
    end: str | None,
    all_data: bool,
) -> dict:
    """Validate window query params into UsageService kwargs.

    Precedence: all > start/end range > days > default (7, applied by the
    service). ``start`` and ``end`` must be provided together.
    """
    if all_data:
        return {"all_data": True}
    if start is not None or end is not None:
        if start is None or end is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="start and end must be provided together",
            )
        start_date = _parse_date(start, "start")
        end_date = _parse_date(end, "end")
        if start_date > end_date:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="start must be on or before end",
            )
        return {"start": start_date, "end": end_date}
    if days is not None:
        if not 1 <= days <= MAX_WINDOW_DAYS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"days must be between 1 and {MAX_WINDOW_DAYS}",
            )
        return {"days": days}
    return {}


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


_DAYS = Query(default=None, description=f"Rolling window, 1..{MAX_WINDOW_DAYS}")
_START = Query(default=None, description="Range start (YYYY-MM-DD, inclusive)")
_END = Query(default=None, description="Range end (YYYY-MM-DD, inclusive)")
_ALL = Query(default=False, alias="all", description="Report over all data")


@router.get("/summary")
def get_summary(
    days: int | None = _DAYS,
    start: str | None = _START,
    end: str | None = _END,
    all_data: bool = _ALL,
    db: Session = Depends(get_db),
):
    kwargs = _window_kwargs(days, start, end, all_data)
    return _handle(UsageService().get_summary, db, **kwargs)


@router.get("/daily")
def get_daily(
    days: int | None = _DAYS,
    start: str | None = _START,
    end: str | None = _END,
    all_data: bool = _ALL,
    db: Session = Depends(get_db),
):
    kwargs = _window_kwargs(days, start, end, all_data)
    return _handle(UsageService().get_daily, db, **kwargs)


@router.get("/top-users")
def get_top_users(
    days: int | None = _DAYS,
    start: str | None = _START,
    end: str | None = _END,
    all_data: bool = _ALL,
    db: Session = Depends(get_db),
):
    kwargs = _window_kwargs(days, start, end, all_data)
    return _handle(UsageService().get_top_users, db, **kwargs)


@router.get("/funnel")
def get_funnel(
    days: int | None = _DAYS,
    start: str | None = _START,
    end: str | None = _END,
    all_data: bool = _ALL,
    db: Session = Depends(get_db),
):
    kwargs = _window_kwargs(days, start, end, all_data)
    return _handle(UsageService().get_funnel, db, **kwargs)


@router.get("/retention")
def get_retention(db: Session = Depends(get_db)):
    return _handle(UsageService().get_retention, db)


@router.get("/heatmap")
def get_heatmap(
    days: int | None = _DAYS,
    start: str | None = _START,
    end: str | None = _END,
    all_data: bool = _ALL,
    db: Session = Depends(get_db),
):
    kwargs = _window_kwargs(days, start, end, all_data)
    return _handle(UsageService().get_heatmap, db, **kwargs)
