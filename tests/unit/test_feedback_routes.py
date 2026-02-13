"""Unit tests for feedback API routes."""

from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client with mocked dependencies."""
    from src.api.main import app

    return TestClient(app)


class TestFeedbackChatEndpoint:
    @patch("src.api.routes.feedback.FeedbackService")
    def test_chat_returns_response(self, mock_service_class, client):
        mock_instance = MagicMock()
        mock_instance.chat.return_value = {
            "content": "Tell me more about the issue.",
            "summary_ready": False,
        }
        mock_service_class.return_value = mock_instance

        response = client.post(
            "/api/feedback/chat",
            json={"messages": [{"role": "user", "content": "Something broke"}]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["content"] == "Tell me more about the issue."
        assert data["summary_ready"] is False

    def test_chat_empty_messages_rejected(self, client):
        response = client.post("/api/feedback/chat", json={"messages": []})
        assert response.status_code == 422


class TestFeedbackSubmitEndpoint:
    @patch("src.api.routes.feedback.FeedbackService")
    def test_submit_returns_id(self, mock_service_class, client):
        mock_instance = MagicMock()
        mock_record = Mock()
        mock_record.id = 42
        mock_instance.submit_feedback.return_value = mock_record
        mock_service_class.return_value = mock_instance

        response = client.post(
            "/api/feedback/submit",
            json={
                "category": "Bug Report",
                "summary": "Text unreadable",
                "severity": "High",
                "raw_conversation": [{"role": "user", "content": "broken"}],
            },
        )
        assert response.status_code == 200
        assert response.json()["id"] == 42


class TestSurveyEndpoint:
    @patch("src.api.routes.feedback.FeedbackService")
    def test_survey_submit(self, mock_service_class, client):
        mock_instance = MagicMock()
        mock_record = Mock()
        mock_record.id = 7
        mock_instance.submit_survey.return_value = mock_record
        mock_service_class.return_value = mock_instance

        response = client.post(
            "/api/feedback/survey",
            json={"star_rating": 4, "time_saved_minutes": 120, "nps_score": 8},
        )
        assert response.status_code == 200
        assert response.json()["id"] == 7

    def test_survey_invalid_star_rating(self, client):
        response = client.post("/api/feedback/survey", json={"star_rating": 0})
        assert response.status_code == 422


class TestStatsReportEndpoint:
    @patch("src.api.routes.feedback.FeedbackService")
    def test_stats_report(self, mock_service_class, client):
        mock_instance = MagicMock()
        mock_instance.get_stats_report.return_value = {
            "weeks": [],
            "totals": {
                "total_responses": 0,
                "avg_star_rating": None,
                "avg_nps_score": None,
                "total_time_saved_minutes": 0,
                "time_saved_display": "0 minutes",
            },
        }
        mock_service_class.return_value = mock_instance

        response = client.get("/api/feedback/report/stats")
        assert response.status_code == 200
        assert response.json()["totals"]["total_responses"] == 0
