# tests/unit/test_usage_event_capture.py
"""Tests that usage events are recorded from the request/deck code paths."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def clean_caches():
    from src.api.services import usage_events

    usage_events.reset_dedup_caches()
    yield
    usage_events.reset_dedup_caches()


@pytest.fixture
def client():
    from src.api.main import app

    return TestClient(app)


class TestLoginCapture:
    def test_authenticated_request_records_login(self, client):
        with patch("src.api.services.usage_events.record_login") as mock_login:
            client.get("/api/version")
        assert mock_login.called
        # Dev fallback identity is used when no OBO token header is present
        username = mock_login.call_args[0][0]
        assert username  # non-empty


class TestDeckRetrievedCapture:
    def test_get_session_records_retrieval(self, client):
        with patch(
            "src.api.routes.sessions.record_deck_retrieved"
        ) as mock_retrieved, patch(
            "src.api.routes.sessions.get_session_manager"
        ) as mock_mgr_factory, patch(
            "src.api.routes.sessions._require_session_access"
        ) as mock_access, patch(
            "src.api.routes.sessions.get_current_user",
            return_value="alice@corp.com",
        ):
            mock_mgr = mock_mgr_factory.return_value
            mock_mgr.get_session.return_value = {
                "id": 7,
                "session_id": "abc123",
                "created_by": "alice@corp.com",
            }
            mock_mgr.get_messages.return_value = []
            mock_mgr.get_slide_deck.return_value = None
            mock_access.return_value.value = "CAN_EDIT"

            resp = client.get("/api/sessions/abc123")

        assert resp.status_code == 200
        mock_retrieved.assert_called_once_with("alice@corp.com", 7)


class TestDeckCreatedCapture:
    def test_save_new_deck_records_creation(self):
        """save_slide_deck's create branch emits deck_created."""
        # Behavioral check via direct call with an in-memory DB:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        import src.database.models  # noqa: F401 - register all models
        from src.api.services import session_manager as sm_module
        from src.core.database import Base

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        factory = sessionmaker(bind=engine)

        from src.database.models.session import UserSession

        db = factory()
        db.add(UserSession(session_id="s1", created_by="alice@corp.com"))
        db.commit()
        db.close()

        import contextlib

        @contextlib.contextmanager
        def fake_get_db_session():
            db = factory()
            try:
                yield db
                db.commit()
            finally:
                db.close()

        with patch(
            "src.api.services.session_manager.get_db_session", fake_get_db_session
        ), patch(
            "src.api.services.usage_events.record_deck_created"
        ) as mock_created:
            mgr = sm_module.SessionManager()
            mgr.save_slide_deck(
                session_id="s1",
                title="Deck",
                html_content="<html></html>",
                slide_count=1,
                modified_by="alice@corp.com",
            )

        assert mock_created.called
        assert mock_created.call_args[0][0] == "alice@corp.com"
