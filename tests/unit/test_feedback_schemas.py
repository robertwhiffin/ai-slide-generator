"""Unit tests for feedback Pydantic schemas."""

import pytest
from pydantic import ValidationError


class TestFeedbackChatRequest:
    def test_valid_request(self):
        from src.api.schemas.feedback import FeedbackChatRequest

        req = FeedbackChatRequest(messages=[{"role": "user", "content": "This feature is broken"}])
        assert len(req.messages) == 1

    def test_empty_messages_rejected(self):
        from src.api.schemas.feedback import FeedbackChatRequest

        with pytest.raises(ValidationError):
            FeedbackChatRequest(messages=[])


class TestFeedbackSubmitRequest:
    def test_valid_submit(self):
        from src.api.schemas.feedback import FeedbackSubmitRequest

        req = FeedbackSubmitRequest(
            category="Bug Report",
            summary="Text unreadable",
            severity="High",
            raw_conversation=[{"role": "user", "content": "broken"}],
        )
        assert req.category == "Bug Report"

    def test_invalid_category_rejected(self):
        from src.api.schemas.feedback import FeedbackSubmitRequest

        with pytest.raises(ValidationError):
            FeedbackSubmitRequest(
                category="Invalid", summary="test", severity="High", raw_conversation=[]
            )

    def test_invalid_severity_rejected(self):
        from src.api.schemas.feedback import FeedbackSubmitRequest

        with pytest.raises(ValidationError):
            FeedbackSubmitRequest(
                category="Bug Report", summary="test", severity="Critical", raw_conversation=[]
            )


class TestSurveySubmitRequest:
    def test_valid_full_survey(self):
        from src.api.schemas.feedback import SurveySubmitRequest

        req = SurveySubmitRequest(star_rating=4, time_saved_minutes=120, nps_score=8)
        assert req.star_rating == 4

    def test_partial_survey_only_stars(self):
        from src.api.schemas.feedback import SurveySubmitRequest

        req = SurveySubmitRequest(star_rating=3)
        assert req.time_saved_minutes is None
        assert req.nps_score is None

    def test_star_rating_out_of_range(self):
        from src.api.schemas.feedback import SurveySubmitRequest

        with pytest.raises(ValidationError):
            SurveySubmitRequest(star_rating=6)

    def test_star_rating_zero_rejected(self):
        from src.api.schemas.feedback import SurveySubmitRequest

        with pytest.raises(ValidationError):
            SurveySubmitRequest(star_rating=0)

    def test_nps_out_of_range(self):
        from src.api.schemas.feedback import SurveySubmitRequest

        with pytest.raises(ValidationError):
            SurveySubmitRequest(star_rating=3, nps_score=11)

    def test_invalid_time_saved(self):
        from src.api.schemas.feedback import SurveySubmitRequest

        with pytest.raises(ValidationError):
            SurveySubmitRequest(star_rating=3, time_saved_minutes=45)


class TestFeedbackChatResponse:
    def test_response_with_summary_ready(self):
        from src.api.schemas.feedback import FeedbackChatResponse

        resp = FeedbackChatResponse(content="Here is the summary", summary_ready=True)
        assert resp.summary_ready is True

    def test_response_defaults_summary_ready_false(self):
        from src.api.schemas.feedback import FeedbackChatResponse

        resp = FeedbackChatResponse(content="Tell me more")
        assert resp.summary_ready is False


class TestStatsReportResponse:
    def test_weekly_stats(self):
        from src.api.schemas.feedback import StatsReportResponse, StatsTotals, WeeklyStats

        week = WeeklyStats(
            week_start="2026-02-09",
            week_end="2026-02-15",
            responses=14,
            avg_star_rating=4.2,
            avg_nps_score=8.1,
            total_time_saved_minutes=1920,
            time_saved_display="32 hours",
        )
        totals = StatsTotals(
            total_responses=14,
            avg_star_rating=4.2,
            avg_nps_score=8.1,
            total_time_saved_minutes=1920,
            time_saved_display="32 hours",
        )
        report = StatsReportResponse(weeks=[week], totals=totals)
        assert len(report.weeks) == 1
        assert report.totals.total_responses == 14
