"""Pydantic schemas for feedback endpoints."""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

FEEDBACK_CATEGORIES = [
    "Bug Report",
    "Feature Request",
    "UX Issue",
    "Performance",
    "Content Quality",
    "Other",
]
FEEDBACK_SEVERITIES = ["Low", "Medium", "High"]
ALLOWED_TIME_SAVED = [15, 30, 60, 120, 240, 480]


class FeedbackChatRequest(BaseModel):
    messages: List[Dict[str, str]] = Field(..., min_length=1)


class FeedbackSubmitRequest(BaseModel):
    category: str
    summary: str
    severity: str
    raw_conversation: List[Dict[str, str]]

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        if value not in FEEDBACK_CATEGORIES:
            raise ValueError(f"Category must be one of: {FEEDBACK_CATEGORIES}")
        return value

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, value: str) -> str:
        if value not in FEEDBACK_SEVERITIES:
            raise ValueError(f"Severity must be one of: {FEEDBACK_SEVERITIES}")
        return value


class SurveySubmitRequest(BaseModel):
    star_rating: int = Field(..., ge=1, le=5)
    time_saved_minutes: Optional[int] = None
    nps_score: Optional[int] = Field(default=None, ge=0, le=10)

    @field_validator("time_saved_minutes")
    @classmethod
    def validate_time_saved(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value not in ALLOWED_TIME_SAVED:
            raise ValueError(f"time_saved_minutes must be one of: {ALLOWED_TIME_SAVED}")
        return value


class FeedbackChatResponse(BaseModel):
    content: str
    summary_ready: bool = False


class FeedbackSubmitResponse(BaseModel):
    id: int
    message: str = "Feedback submitted successfully"


class SurveySubmitResponse(BaseModel):
    id: int
    message: str = "Survey response submitted successfully"


class WeeklyStats(BaseModel):
    week_start: str
    week_end: str
    responses: int
    avg_star_rating: Optional[float]
    avg_nps_score: Optional[float]
    total_time_saved_minutes: int
    time_saved_display: str


class StatsTotals(BaseModel):
    total_responses: int
    avg_star_rating: Optional[float]
    avg_nps_score: Optional[float]
    total_time_saved_minutes: int
    time_saved_display: str


class StatsReportResponse(BaseModel):
    weeks: List[WeeklyStats]
    totals: StatsTotals


class FeedbackSummaryResponse(BaseModel):
    period: str
    feedback_count: int
    summary: str
    category_breakdown: Dict[str, int]
    top_themes: List[str]
