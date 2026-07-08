"""Unit tests for the raw feedback list (service + route)."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    import src.database.models.feedback  # noqa: F401

    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    yield session
    session.close()


def _add_feedback(db, category="Bug Report", severity="High", created_at=None, summary="s"):
    from src.database.models.feedback import FeedbackConversation

    db.add(
        FeedbackConversation(
            category=category,
            severity=severity,
            summary=summary,
            raw_conversation=[{"role": "user", "content": "hi"}],
            created_at=created_at or datetime.utcnow(),
        )
    )
    db.commit()


class TestListFeedbackService:
    def test_returns_items_newest_first(self, db_session):
        from src.api.services.feedback_service import FeedbackService

        _add_feedback(db_session, summary="old", created_at=datetime.utcnow() - timedelta(days=2))
        _add_feedback(db_session, summary="new")
        result = FeedbackService().list_feedback(db_session)
        assert result["total"] == 2
        assert result["items"][0]["summary"] == "new"
        assert "raw_conversation" in result["items"][0]

    def test_filters_by_category_and_severity(self, db_session):
        from src.api.services.feedback_service import FeedbackService

        _add_feedback(db_session, category="Bug Report", severity="High")
        _add_feedback(db_session, category="Feature Request", severity="Low")
        result = FeedbackService().list_feedback(db_session, category="Bug Report")
        assert result["total"] == 1
        assert result["items"][0]["category"] == "Bug Report"
        result = FeedbackService().list_feedback(db_session, severity="Low")
        assert result["total"] == 1

    def test_weeks_window_filters_old_items(self, db_session):
        from src.api.services.feedback_service import FeedbackService

        _add_feedback(db_session, created_at=datetime.utcnow() - timedelta(weeks=20))
        _add_feedback(db_session)
        result = FeedbackService().list_feedback(db_session, weeks=12)
        assert result["total"] == 1

    def test_pagination(self, db_session):
        from src.api.services.feedback_service import FeedbackService

        for i in range(25):
            _add_feedback(db_session, summary=f"item-{i}")
        page1 = FeedbackService().list_feedback(db_session, page=1, page_size=20)
        page2 = FeedbackService().list_feedback(db_session, page=2, page_size=20)
        assert page1["total"] == 25
        assert len(page1["items"]) == 20
        assert len(page2["items"]) == 5


class TestListFeedbackRoute:
    @pytest.fixture
    def client(self):
        from src.api.main import app

        return TestClient(app)

    @patch("src.api.routes.feedback.FeedbackService")
    def test_list_endpoint(self, mock_cls, client):
        mock_cls.return_value.list_feedback.return_value = {
            "items": [],
            "total": 0,
            "page": 1,
            "page_size": 20,
        }
        resp = client.get("/api/feedback/list?weeks=4&category=Bug%20Report&page=1")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_invalid_page_rejected(self, client):
        assert client.get("/api/feedback/list?page=0").status_code == 422
