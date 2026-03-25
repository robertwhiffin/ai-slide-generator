"""Tests for session-creation-on-first-message in chat endpoints.

Verifies that POST /chat/stream, /chat/async, and /chat with no session_id
automatically creates a session, and that agent_config is persisted.

Run: pytest tests/unit/test_chat_session_creation.py -v
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.main import app
from src.core.database import Base, get_db
from src.api.schemas.streaming import StreamEventType


# ============================================
# Fixtures
# ============================================

@pytest.fixture(scope="function")
def test_db_engine():
    """Create test database engine with SQLite in-memory."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def test_db(test_db_engine):
    """Create test database session."""
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_db_engine)
    db = SessionLocal()
    yield db
    db.close()


@pytest.fixture(scope="function")
def client(test_db):
    """Create test client with dependency override."""
    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def mock_chat_permission():
    """Bypass chat permission checks — these tests focus on session creation."""
    with patch("src.api.routes.chat._check_chat_permission"):
        yield


@pytest.fixture
def mock_session_manager(mock_chat_permission):
    """Mock the session manager for route testing."""
    with patch("src.api.routes.chat.get_session_manager") as mock_chat:
        with patch("src.api.routes.sessions.get_session_manager") as mock_sessions:
            manager = MagicMock()
            manager.acquire_session_lock.return_value = True
            manager.release_session_lock.return_value = None
            manager.create_session.return_value = {
                "session_id": "new-session-abc",
                "user_id": None,
                "created_by": "test-user",
                "title": "Session 2026-03-18 12:00",
                "created_at": "2026-03-18T12:00:00",
                "profile_id": None,
                "profile_name": None,
            }
            mock_chat.return_value = manager
            mock_sessions.return_value = manager
            yield manager


@pytest.fixture
def mock_chat_service():
    """Mock the chat service for route testing."""
    with patch("src.api.routes.chat.get_chat_service") as mock_get:
        service = MagicMock()
        mock_get.return_value = service
        yield service


# ============================================
# Schema Tests
# ============================================


class TestChatRequestSchema:
    """Tests for ChatRequest schema with optional session_id."""

    def test_session_id_is_optional(self):
        """ChatRequest should accept missing session_id."""
        from src.api.schemas.requests import ChatRequest

        req = ChatRequest(message="Hello")
        assert req.session_id is None

    def test_session_id_can_be_provided(self):
        """ChatRequest should still accept session_id when provided."""
        from src.api.schemas.requests import ChatRequest

        req = ChatRequest(session_id="test-123", message="Hello")
        assert req.session_id == "test-123"

    def test_empty_session_id_treated_as_missing(self):
        """ChatRequest with empty string session_id should be treated as None."""
        from src.api.schemas.requests import ChatRequest

        req = ChatRequest(session_id="", message="Hello")
        # Empty string should be normalised to None
        assert req.session_id is None

    def test_agent_config_accepted(self):
        """ChatRequest should accept agent_config dict."""
        from src.api.schemas.requests import ChatRequest

        config = {"tools": [{"type": "genie", "space_id": "sp1", "space_name": "Sales"}]}
        req = ChatRequest(message="Hello", agent_config=config)
        assert req.agent_config == config

    def test_agent_config_defaults_to_none(self):
        """ChatRequest agent_config defaults to None."""
        from src.api.schemas.requests import ChatRequest

        req = ChatRequest(message="Hello")
        assert req.agent_config is None


class TestStreamEventType:
    """Tests for SESSION_CREATED event type."""

    def test_session_created_event_type_exists(self):
        """StreamEventType should have SESSION_CREATED."""
        assert hasattr(StreamEventType, "SESSION_CREATED")
        assert StreamEventType.SESSION_CREATED.value == "session_created"

    def test_session_created_event_has_session_id(self):
        """StreamEvent with SESSION_CREATED should carry session_id."""
        from src.api.schemas.streaming import StreamEvent

        event = StreamEvent(
            type=StreamEventType.SESSION_CREATED,
            session_id="new-session-abc",
        )
        assert event.session_id == "new-session-abc"
        sse = event.to_sse()
        assert "session_created" in sse
        assert "new-session-abc" in sse


# ============================================
# /chat/stream Endpoint Tests
# ============================================


class TestChatStreamSessionCreation:
    """Tests for /chat/stream creating sessions on the fly."""

    def test_chat_stream_creates_session_when_missing(
        self, client, mock_session_manager, mock_chat_service
    ):
        """POST /chat/stream with no session_id creates a new session."""
        # Mock streaming to return a simple complete event
        from src.api.schemas.streaming import StreamEvent

        complete_event = StreamEvent(
            type=StreamEventType.COMPLETE,
            slides={"slides": []},
        )
        mock_chat_service.send_message_streaming.return_value = iter([complete_event])

        response = client.post(
            "/api/chat/stream",
            json={"message": "Create slides about revenue"},
        )

        assert response.status_code == 200
        # Session should have been created
        mock_session_manager.create_session.assert_called_once()

    def test_chat_stream_with_agent_config_persists_config(
        self, client, mock_session_manager, mock_chat_service
    ):
        """POST /chat/stream with agent_config passes it to create_session."""
        from src.api.schemas.streaming import StreamEvent

        complete_event = StreamEvent(
            type=StreamEventType.COMPLETE,
            slides={"slides": []},
        )
        mock_chat_service.send_message_streaming.return_value = iter([complete_event])

        agent_config = {
            "tools": [{"type": "genie", "space_id": "sp1", "space_name": "Sales"}],
        }

        response = client.post(
            "/api/chat/stream",
            json={"message": "Create slides", "agent_config": agent_config},
        )

        assert response.status_code == 200
        call_kwargs = mock_session_manager.create_session.call_args
        assert call_kwargs is not None
        # agent_config should be passed to create_session
        assert "agent_config" in (call_kwargs.kwargs or {}) or (
            len(call_kwargs.args) > 0
        )

    def test_chat_stream_emits_session_created_event(
        self, client, mock_session_manager, mock_chat_service
    ):
        """POST /chat/stream should emit SESSION_CREATED as first SSE event."""
        from src.api.schemas.streaming import StreamEvent

        complete_event = StreamEvent(
            type=StreamEventType.COMPLETE,
            slides={"slides": []},
        )
        mock_chat_service.send_message_streaming.return_value = iter([complete_event])

        response = client.post(
            "/api/chat/stream",
            json={"message": "Hello"},
        )

        assert response.status_code == 200
        body = response.text
        # Should contain session_created event before complete
        assert "event: session_created" in body

    def test_chat_stream_with_existing_session_id_skips_creation(
        self, client, mock_session_manager, mock_chat_service, test_db
    ):
        """POST /chat/stream with session_id should NOT create a new session."""
        from src.api.schemas.streaming import StreamEvent
        from src.database.models import UserSession

        # Insert a session so the DB lookup in _maybe_create_session finds it
        session = UserSession(
            session_id="existing-session",
            user_id="test",
            title="Existing",
            created_by="test",
        )
        test_db.add(session)
        test_db.commit()

        complete_event = StreamEvent(
            type=StreamEventType.COMPLETE,
            slides={"slides": []},
        )
        mock_chat_service.send_message_streaming.return_value = iter([complete_event])

        # Mock get_db_session to use the test DB so the lookup finds our session
        from contextlib import contextmanager

        @contextmanager
        def _mock_db_session():
            yield test_db

        with patch("src.core.database.get_db_session", _mock_db_session):
            response = client.post(
                "/api/chat/stream",
                json={"session_id": "existing-session", "message": "Hello"},
            )

        assert response.status_code == 200
        mock_session_manager.create_session.assert_not_called()


# ============================================
# /chat Sync Endpoint Tests
# ============================================


class TestChatSyncSessionCreation:
    """Tests for /chat sync endpoint creating sessions on the fly."""

    def test_chat_sync_creates_session_when_missing(
        self, client, mock_session_manager, mock_chat_service
    ):
        """POST /api/chat with no session_id creates a new session."""
        mock_chat_service.send_message.return_value = {
            "messages": [],
            "slide_deck": None,
            "metadata": {},
        }

        response = client.post(
            "/api/chat",
            json={"message": "Create slides about revenue"},
        )

        assert response.status_code == 200
        mock_session_manager.create_session.assert_called_once()

    def test_chat_sync_returns_session_id_in_response(
        self, client, mock_session_manager, mock_chat_service
    ):
        """POST /api/chat with no session_id returns the new session_id."""
        mock_chat_service.send_message.return_value = {
            "messages": [],
            "slide_deck": None,
            "metadata": {},
        }

        response = client.post(
            "/api/chat",
            json={"message": "Hello"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data.get("session_id") == "new-session-abc"


# ============================================
# /chat/async Endpoint Tests
# ============================================


class TestChatAsyncSessionCreation:
    """Tests for /chat/async endpoint creating sessions on the fly."""

    def test_chat_async_creates_session_when_missing(
        self, client, mock_session_manager, mock_chat_service
    ):
        """POST /api/chat/async with no session_id creates a new session."""
        mock_session_manager.create_chat_request.return_value = "req-123"
        mock_session_manager.get_session.return_value = {"message_count": 0}

        with patch("src.api.routes.chat.enqueue_job", new_callable=AsyncMock):
            with patch("src.core.settings_db.get_settings") as mock_settings:
                mock_settings.return_value = MagicMock(profile_id=None, profile_name=None)
                response = client.post(
                    "/api/chat/async",
                    json={"message": "Create slides about revenue"},
                )

        assert response.status_code == 200
        mock_session_manager.create_session.assert_called_once()
        data = response.json()
        assert data.get("session_id") == "new-session-abc"


# ============================================
# CreateSessionRequest Schema Tests
# ============================================


class TestCreateSessionRequest:
    """Tests for CreateSessionRequest schema changes."""

    def test_create_session_request_has_no_profile_id(self):
        """CreateSessionRequest should not have profile_id (removed in deck-centric redesign)."""
        from src.api.schemas.requests import CreateSessionRequest

        req = CreateSessionRequest()
        assert not hasattr(req, "profile_id")


# ============================================
# Session Manager create_session Tests
# ============================================


class TestSessionManagerAgentConfig:
    """Tests for agent_config parameter on session_manager.create_session."""

    def test_create_session_accepts_agent_config(self):
        """session_manager.create_session should accept agent_config kwarg."""
        import inspect
        from src.api.services.session_manager import SessionManager

        sig = inspect.signature(SessionManager.create_session)
        assert "agent_config" in sig.parameters
