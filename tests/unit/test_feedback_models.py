"""Unit tests for feedback database models."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.core.database import Base


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    import src.database.models.feedback  # noqa: F401 - register models with Base

    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    yield session
    session.close()


class TestFeedbackConversation:
    """Tests for FeedbackConversation model."""

    def test_create_feedback_conversation(self, db_session):
        """Test creating a feedback conversation record."""
        from src.database.models.feedback import FeedbackConversation

        feedback = FeedbackConversation(
            category="Bug Report",
            summary="Text unreadable on dark backgrounds",
            severity="High",
            raw_conversation=[
                {"role": "user", "content": "Text is hard to read"},
                {"role": "assistant", "content": "Can you clarify?"},
            ],
        )
        db_session.add(feedback)
        db_session.commit()

        result = db_session.query(FeedbackConversation).first()
        assert result is not None
        assert result.id is not None
        assert result.category == "Bug Report"
        assert result.summary == "Text unreadable on dark backgrounds"
        assert result.severity == "High"
        assert len(result.raw_conversation) == 2
        assert result.created_at is not None

    def test_feedback_conversation_table_name(self):
        """Test the table name is correct."""
        from src.database.models.feedback import FeedbackConversation

        assert FeedbackConversation.__tablename__ == "feedback_conversations"

    def test_feedback_invalid_category_rejected(self, db_session):
        """Insert with category='Invalid' should raise IntegrityError."""
        from src.database.models.feedback import FeedbackConversation

        feedback = FeedbackConversation(
            category="Invalid",
            summary="Test summary",
            severity="High",
            raw_conversation=[{"role": "user", "content": "test"}],
        )
        db_session.add(feedback)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_feedback_invalid_severity_rejected(self, db_session):
        """Insert with severity='Critical' should raise IntegrityError."""
        from src.database.models.feedback import FeedbackConversation

        feedback = FeedbackConversation(
            category="Bug Report",
            summary="Test summary",
            severity="Critical",
            raw_conversation=[{"role": "user", "content": "test"}],
        )
        db_session.add(feedback)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


class TestSurveyResponse:
    """Tests for SurveyResponse model."""

    def test_create_survey_response_full(self, db_session):
        """Test creating a survey response with all fields."""
        from src.database.models.feedback import SurveyResponse

        survey = SurveyResponse(
            star_rating=4,
            time_saved_minutes=120,
            nps_score=8,
        )
        db_session.add(survey)
        db_session.commit()

        result = db_session.query(SurveyResponse).first()
        assert result is not None
        assert result.id is not None
        assert result.star_rating == 4
        assert result.time_saved_minutes == 120
        assert result.nps_score == 8
        assert result.created_at is not None

    def test_create_survey_response_partial(self, db_session):
        """Test creating a survey response with only star rating (others nullable)."""
        from src.database.models.feedback import SurveyResponse

        survey = SurveyResponse(star_rating=3)
        db_session.add(survey)
        db_session.commit()

        result = db_session.query(SurveyResponse).first()
        assert result.star_rating == 3
        assert result.time_saved_minutes is None
        assert result.nps_score is None

    def test_survey_response_table_name(self):
        """Test the table name is correct."""
        from src.database.models.feedback import SurveyResponse

        assert SurveyResponse.__tablename__ == "survey_responses"

    def test_survey_star_rating_too_high(self, db_session):
        """Insert with star_rating=6 should raise IntegrityError."""
        from src.database.models.feedback import SurveyResponse

        survey = SurveyResponse(star_rating=6)
        db_session.add(survey)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_survey_star_rating_too_low(self, db_session):
        """Insert with star_rating=0 should raise IntegrityError."""
        from src.database.models.feedback import SurveyResponse

        survey = SurveyResponse(star_rating=0)
        db_session.add(survey)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_survey_invalid_nps_score(self, db_session):
        """Insert with nps_score=11 should raise IntegrityError."""
        from src.database.models.feedback import SurveyResponse

        survey = SurveyResponse(star_rating=3, nps_score=11)
        db_session.add(survey)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()
