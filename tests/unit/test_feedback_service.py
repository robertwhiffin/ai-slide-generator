"""Unit tests for the feedback service."""

from unittest.mock import MagicMock, Mock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base


@pytest.fixture
def db_session():
    """In-memory SQLite for testing."""
    engine = create_engine("sqlite:///:memory:")
    import src.database.models.feedback  # noqa: F401

    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    yield session
    session.close()


class TestFeedbackChat:
    """Tests for the feedback chat LLM call."""

    @patch("src.api.services.feedback_service.ChatDatabricks")
    def test_chat_returns_ai_response(self, mock_chat_class):
        from src.api.services.feedback_service import FeedbackService

        mock_model = MagicMock()
        mock_response = Mock()
        mock_response.content = "Can you tell me more about that issue?"
        mock_model.invoke.return_value = mock_response
        mock_chat_class.return_value = mock_model

        service = FeedbackService(endpoint="test-endpoint")
        result = service.chat([{"role": "user", "content": "Something is broken"}])

        assert result["content"] == "Can you tell me more about that issue?"
        assert result["summary_ready"] is False

    @patch("src.api.services.feedback_service.ChatDatabricks")
    def test_chat_detects_feedback_confirmed(self, mock_chat_class):
        from src.api.services.feedback_service import FeedbackService

        mock_model = MagicMock()
        mock_response = Mock()
        mock_response.content = "FEEDBACK_CONFIRMED"
        mock_model.invoke.return_value = mock_response
        mock_chat_class.return_value = mock_model

        service = FeedbackService(endpoint="test-endpoint")
        result = service.chat([{"role": "user", "content": "Yes, that looks right"}])

        assert result["summary_ready"] is True

    @patch("src.api.services.feedback_service.ChatDatabricks")
    def test_chat_prepends_system_prompt(self, mock_chat_class):
        from src.api.services.feedback_service import FeedbackService

        mock_model = MagicMock()
        mock_response = Mock()
        mock_response.content = "Tell me more"
        mock_model.invoke.return_value = mock_response
        mock_chat_class.return_value = mock_model

        service = FeedbackService(endpoint="test-endpoint")
        service.chat([{"role": "user", "content": "Bug report"}])

        call_args = mock_model.invoke.call_args[0][0]
        from langchain_core.messages import SystemMessage

        assert isinstance(call_args[0], SystemMessage)


class TestFeedbackSubmit:
    def test_submit_feedback_creates_record(self, db_session):
        from src.api.services.feedback_service import FeedbackService

        service = FeedbackService(endpoint="test-endpoint")
        result = service.submit_feedback(
            db=db_session,
            category="Bug Report",
            summary="Text unreadable on dark backgrounds",
            severity="High",
            raw_conversation=[{"role": "user", "content": "text is hard to read"}],
        )

        assert result.id is not None
        assert result.category == "Bug Report"

        from src.database.models.feedback import FeedbackConversation

        count = db_session.query(FeedbackConversation).count()
        assert count == 1


class TestSurveySubmit:
    def test_submit_survey_creates_record(self, db_session):
        from src.api.services.feedback_service import FeedbackService

        service = FeedbackService(endpoint="test-endpoint")
        result = service.submit_survey(
            db=db_session, star_rating=4, time_saved_minutes=120, nps_score=8
        )

        assert result.id is not None
        assert result.star_rating == 4

    def test_submit_survey_partial(self, db_session):
        from src.api.services.feedback_service import FeedbackService

        service = FeedbackService(endpoint="test-endpoint")
        result = service.submit_survey(db=db_session, star_rating=5)

        assert result.star_rating == 5
        assert result.time_saved_minutes is None
        assert result.nps_score is None


class TestStatsReport:
    def test_stats_report_empty(self, db_session):
        from src.api.services.feedback_service import FeedbackService

        service = FeedbackService(endpoint="test-endpoint")
        result = service.get_stats_report(db=db_session, weeks=4)

        assert result["weeks"] == []
        assert result["totals"]["total_responses"] == 0

    def test_stats_report_with_data(self, db_session):
        from src.api.services.feedback_service import FeedbackService
        from src.database.models.feedback import SurveyResponse

        db_session.add(SurveyResponse(star_rating=4, time_saved_minutes=60, nps_score=8))
        db_session.add(SurveyResponse(star_rating=2, time_saved_minutes=120, nps_score=6))
        db_session.commit()

        service = FeedbackService(endpoint="test-endpoint")
        result = service.get_stats_report(db=db_session, weeks=4)

        assert result["totals"]["total_responses"] == 2
        assert result["totals"]["avg_star_rating"] == 3.0
        assert result["totals"]["avg_nps_score"] == 7.0
        assert result["totals"]["total_time_saved_minutes"] == 180


class TestFeedbackSummaryReport:
    @patch("src.api.services.feedback_service.ChatDatabricks")
    def test_summary_report_with_feedback(self, mock_chat_class, db_session):
        from src.api.services.feedback_service import FeedbackService
        from src.database.models.feedback import FeedbackConversation

        db_session.add(
            FeedbackConversation(
                category="Bug Report",
                summary="Text unreadable on dark backgrounds",
                severity="High",
                raw_conversation=[],
            )
        )
        db_session.add(
            FeedbackConversation(
                category="Feature Request",
                summary="Want Google Slides export",
                severity="Low",
                raw_conversation=[],
            )
        )
        db_session.commit()

        mock_model = MagicMock()
        mock_response = Mock()
        mock_response.content = (
            '{"summary": "Two items of feedback received.", '
            '"top_themes": ["Dark mode readability", "Export options"]}'
        )
        mock_model.invoke.return_value = mock_response
        mock_chat_class.return_value = mock_model

        service = FeedbackService(endpoint="test-endpoint")
        result = service.get_feedback_summary(db=db_session, weeks=4)

        assert result["feedback_count"] == 2
        assert result["category_breakdown"]["Bug Report"] == 1
        assert result["category_breakdown"]["Feature Request"] == 1

    def test_summary_report_empty(self, db_session):
        from src.api.services.feedback_service import FeedbackService

        service = FeedbackService(endpoint="test-endpoint")
        result = service.get_feedback_summary(db=db_session, weeks=4)

        assert result["feedback_count"] == 0
        assert result["summary"] == "No feedback received in this period."
