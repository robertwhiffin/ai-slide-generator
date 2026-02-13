"""Feedback and survey database models."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    String,
    Text,
)

from src.core.database import Base


class FeedbackConversation(Base):
    """Stores AI-assisted feedback conversations and their structured summaries."""

    __tablename__ = "feedback_conversations"

    id = Column(Integer, primary_key=True)
    category = Column(String(50), nullable=False)
    summary = Column(Text, nullable=False)
    severity = Column(String(10), nullable=False)
    raw_conversation = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "category IN ('Bug Report', 'Feature Request', 'UX Issue', "
            "'Performance', 'Content Quality', 'Other')",
            name="check_feedback_category",
        ),
        CheckConstraint(
            "severity IN ('Low', 'Medium', 'High')",
            name="check_feedback_severity",
        ),
    )

    def __repr__(self):
        return (
            f"<FeedbackConversation(id={self.id}, category='{self.category}', "
            f"severity='{self.severity}')>"
        )


class SurveyResponse(Base):
    """Stores periodic satisfaction survey responses."""

    __tablename__ = "survey_responses"

    id = Column(Integer, primary_key=True)
    star_rating = Column(Integer, nullable=False)
    time_saved_minutes = Column(Integer, nullable=True)
    nps_score = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("star_rating >= 1 AND star_rating <= 5", name="check_star_rating_range"),
        CheckConstraint(
            "time_saved_minutes IN (15, 30, 60, 120, 240, 480) OR time_saved_minutes IS NULL",
            name="check_time_saved_values",
        ),
        CheckConstraint(
            "nps_score >= 0 AND nps_score <= 10 OR nps_score IS NULL",
            name="check_nps_score_range",
        ),
    )

    def __repr__(self):
        return f"<SurveyResponse(id={self.id}, stars={self.star_rating}, nps={self.nps_score})>"
