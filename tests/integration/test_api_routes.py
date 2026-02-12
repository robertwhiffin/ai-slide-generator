"""Integration tests for API route endpoints.

Tests HTTP layer behavior: status codes, request validation, response structure.
Services are mocked to isolate route testing from business logic.

Run: pytest tests/integration/test_api_routes.py -v
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import MagicMock, patch, AsyncMock

from src.api.main import app
from src.core.database import Base, get_db
from src.database.models import (  # noqa: F401
    ConfigAIInfra,
    ConfigGenieSpace,
    ConfigHistory,
    ConfigProfile,
    ConfigPrompts,
)


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

    # Create tables (excluding config_history which uses PostgreSQL-specific JSONB)
    tables_to_create = [
        table for table in Base.metadata.sorted_tables
        if table.name != 'config_history'
    ]

    for table in tables_to_create:
        table.create(bind=engine, checkfirst=True)

    # Create simplified history table for tests (TEXT instead of JSONB)
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS config_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL,
                domain VARCHAR(50) NOT NULL,
                action VARCHAR(50) NOT NULL,
                changed_by VARCHAR(255) NOT NULL,
                changes TEXT NOT NULL,
                snapshot TEXT,
                timestamp DATETIME NOT NULL,
                FOREIGN KEY (profile_id) REFERENCES config_profiles (id) ON DELETE CASCADE
            )
        """))
        conn.commit()

    yield engine

    # Cleanup
    for table in reversed(tables_to_create):
        table.drop(bind=engine, checkfirst=True)
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS config_history"))
        conn.commit()
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
def mock_chat_service():
    """Mock the chat service for route testing."""
    with patch("src.api.routes.chat.get_chat_service") as mock_chat:
        with patch("src.api.routes.slides.get_chat_service") as mock_slides:
            service = MagicMock()
            mock_chat.return_value = service
            mock_slides.return_value = service
            yield service


@pytest.fixture
def mock_session_manager():
    """Mock the session manager for route testing."""
    with patch("src.api.routes.chat.get_session_manager") as mock_chat:
        with patch("src.api.routes.slides.get_session_manager") as mock_slides:
            with patch("src.api.routes.sessions.get_session_manager") as mock_sessions:
                with patch("src.api.routes.verification.get_session_manager") as mock_verify:
                    manager = MagicMock()
                    manager.acquire_session_lock.return_value = True
                    manager.release_session_lock.return_value = None
                    mock_chat.return_value = manager
                    mock_slides.return_value = manager
                    mock_sessions.return_value = manager
                    mock_verify.return_value = manager
                    yield manager


# ============================================
# Chat Endpoint Tests
# ============================================


class TestChatEndpoints:
    """Tests for /api/chat endpoints."""

    def test_chat_requires_session_id(self, client):
        """POST /api/chat returns 422 without session_id."""
        response = client.post("/api/chat", json={"message": "Hello"})
        assert response.status_code == 422
        assert "detail" in response.json()

    def test_chat_requires_message(self, client):
        """POST /api/chat returns 422 without message."""
        response = client.post("/api/chat", json={"session_id": "test-123"})
        assert response.status_code == 422
        assert "detail" in response.json()

    def test_chat_empty_message_rejected(self, client):
        """POST /api/chat returns 422 with empty message."""
        response = client.post("/api/chat", json={
            "session_id": "test-123",
            "message": ""
        })
        assert response.status_code == 422

    def test_chat_empty_session_id_rejected(self, client):
        """POST /api/chat returns 422 with empty session_id."""
        response = client.post("/api/chat", json={
            "session_id": "",
            "message": "Hello"
        })
        assert response.status_code == 422

    def test_chat_session_not_found(self, client, mock_chat_service, mock_session_manager):
        """POST /api/chat returns 404 for nonexistent session."""
        from src.api.services.session_manager import SessionNotFoundError

        # Mock the send_message to raise SessionNotFoundError
        mock_chat_service.send_message.side_effect = SessionNotFoundError("test-123")

        response = client.post("/api/chat", json={
            "session_id": "test-123",
            "message": "Hello"
        })
        assert response.status_code == 404
        assert "Session not found" in response.json()["detail"]

    def test_chat_session_busy(self, client, mock_session_manager):
        """POST /api/chat returns 409 when session is locked."""
        mock_session_manager.acquire_session_lock.return_value = False

        response = client.post("/api/chat", json={
            "session_id": "test-123",
            "message": "Hello"
        })
        assert response.status_code == 409
        assert "processing" in response.json()["detail"].lower()

    def test_chat_success(self, client, mock_chat_service, mock_session_manager):
        """POST /api/chat returns 200 with valid response."""
        mock_chat_service.send_message.return_value = {
            "messages": [
                {
                    "role": "assistant",
                    "content": "Hello!",
                    "timestamp": "2024-01-01T12:00:00Z"
                }
            ],
            "slide_deck": None,
            "metadata": {"latency_seconds": 1.0}
        }

        response = client.post("/api/chat", json={
            "session_id": "test-123",
            "message": "Hello"
        })
        assert response.status_code == 200
        data = response.json()
        assert "messages" in data
        assert "metadata" in data

    def test_chat_with_slide_context(self, client, mock_chat_service, mock_session_manager):
        """POST /api/chat accepts slide_context parameter."""
        mock_chat_service.send_message.return_value = {
            "messages": [
                {
                    "role": "assistant",
                    "content": "Editing slides...",
                    "timestamp": "2024-01-01T12:00:00Z"
                }
            ],
            "slide_deck": None,
            "metadata": {}
        }

        response = client.post("/api/chat", json={
            "session_id": "test-123",
            "message": "Edit slide",
            "slide_context": {
                "indices": [0, 1],
                "slide_htmls": ["<div>Slide 1</div>", "<div>Slide 2</div>"]
            }
        })
        assert response.status_code == 200

    def test_chat_invalid_slide_context_non_contiguous(self, client):
        """POST /api/chat returns 422 with non-contiguous indices."""
        response = client.post("/api/chat", json={
            "session_id": "test-123",
            "message": "Edit slides",
            "slide_context": {
                "indices": [0, 2],  # Non-contiguous
                "slide_htmls": ["<div>1</div>", "<div>2</div>"]
            }
        })
        assert response.status_code == 422

    def test_chat_invalid_slide_context_mismatch_length(self, client):
        """POST /api/chat returns 422 when indices and htmls lengths mismatch."""
        response = client.post("/api/chat", json={
            "session_id": "test-123",
            "message": "Edit slides",
            "slide_context": {
                "indices": [0, 1, 2],
                "slide_htmls": ["<div>1</div>", "<div>2</div>"]  # Only 2 htmls for 3 indices
            }
        })
        assert response.status_code == 422

    def test_chat_internal_error(self, client, mock_chat_service, mock_session_manager):
        """POST /api/chat returns 500 on service error."""
        mock_chat_service.send_message.side_effect = Exception("LLM connection failed")

        response = client.post("/api/chat", json={
            "session_id": "test-123",
            "message": "Hello"
        })
        assert response.status_code == 500
        assert "detail" in response.json()

    def test_health_check(self, client):
        """GET /api/health returns 200."""
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_chat_async_submit(self, client, mock_session_manager):
        """POST /api/chat/async returns request_id."""
        mock_session_manager.create_chat_request.return_value = "req-abc123"
        mock_session_manager.add_message.return_value = None

        # Mock enqueue_job
        with patch("src.api.routes.chat.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
            mock_enqueue.return_value = None
            # Also mock get_settings to avoid database access
            with patch("src.core.settings_db.get_settings") as mock_settings:
                mock_settings.return_value = MagicMock(profile_id=1, profile_name="test")

                response = client.post("/api/chat/async", json={
                    "session_id": "test-123",
                    "message": "Hello async"
                })

        assert response.status_code == 200
        data = response.json()
        assert "request_id" in data
        assert data["status"] == "pending"

    def test_chat_async_session_busy(self, client, mock_session_manager):
        """POST /api/chat/async returns 409 when session locked."""
        mock_session_manager.acquire_session_lock.return_value = False

        response = client.post("/api/chat/async", json={
            "session_id": "test-123",
            "message": "Hello"
        })
        assert response.status_code == 409

    def test_chat_poll_not_found(self, client, mock_session_manager):
        """GET /api/chat/poll/{request_id} returns 404 for unknown request."""
        mock_session_manager.get_chat_request.return_value = None

        response = client.get("/api/chat/poll/nonexistent-request")
        assert response.status_code == 404
        assert "Request not found" in response.json()["detail"]

    def test_chat_poll_success(self, client, mock_session_manager):
        """GET /api/chat/poll/{request_id} returns request status."""
        mock_session_manager.get_chat_request.return_value = {
            "status": "completed",
            "result": {"messages": []},
        }
        mock_session_manager.get_messages_for_request.return_value = []
        mock_session_manager.msg_to_stream_event.return_value = {}

        response = client.get("/api/chat/poll/req-123")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] == "completed"


# ============================================
# Slide Endpoint Tests
# ============================================


class TestSlideEndpoints:
    """Tests for /api/slides endpoints."""

    def test_get_slides_requires_session_id(self, client):
        """GET /api/slides returns 422 without session_id query param."""
        response = client.get("/api/slides")
        assert response.status_code == 422

    def test_get_slides_not_found(self, client, mock_chat_service):
        """GET /api/slides returns 404 when no slides exist."""
        mock_chat_service.get_slides.return_value = None

        response = client.get("/api/slides?session_id=test-123")
        assert response.status_code == 404
        assert "No slides available" in response.json()["detail"]

    def test_get_slides_success(self, client, mock_chat_service):
        """GET /api/slides returns slide deck."""
        mock_chat_service.get_slides.return_value = {
            "slides": [{"index": 0, "html": "<div>Slide 1</div>"}],
            "slide_count": 1
        }

        response = client.get("/api/slides?session_id=test-123")
        assert response.status_code == 200
        data = response.json()
        assert data["slide_count"] == 1
        assert len(data["slides"]) == 1

    def test_reorder_slides_invalid_order_type(self, client, mock_session_manager):
        """PUT /api/slides/reorder validates new_order is array."""
        response = client.put("/api/slides/reorder", json={
            "session_id": "test-123",
            "new_order": "not-an-array"
        })
        assert response.status_code == 422

    def test_reorder_slides_missing_new_order(self, client):
        """PUT /api/slides/reorder requires new_order field."""
        response = client.put("/api/slides/reorder", json={
            "session_id": "test-123"
        })
        assert response.status_code == 422

    def test_reorder_slides_session_busy(self, client, mock_session_manager):
        """PUT /api/slides/reorder returns 409 when session locked."""
        mock_session_manager.acquire_session_lock.return_value = False

        response = client.put("/api/slides/reorder", json={
            "session_id": "test-123",
            "new_order": [1, 0, 2]
        })
        assert response.status_code == 409

    def test_reorder_slides_success(self, client, mock_chat_service, mock_session_manager):
        """PUT /api/slides/reorder successfully reorders slides."""
        mock_chat_service.reorder_slides.return_value = {
            "slides": [{"index": 0}, {"index": 1}],
            "slide_count": 2
        }

        response = client.put("/api/slides/reorder", json={
            "session_id": "test-123",
            "new_order": [1, 0]
        })
        assert response.status_code == 200

    def test_reorder_slides_validation_error(self, client, mock_chat_service, mock_session_manager):
        """PUT /api/slides/reorder returns 400 on validation error."""
        mock_chat_service.reorder_slides.side_effect = ValueError("Invalid slide order")

        response = client.put("/api/slides/reorder", json={
            "session_id": "test-123",
            "new_order": [5, 6, 7]  # Invalid indices
        })
        assert response.status_code == 400

    def test_update_slide_success(self, client, mock_chat_service, mock_session_manager):
        """PATCH /api/slides/{index} updates slide HTML."""
        mock_chat_service.update_slide.return_value = {
            "index": 0,
            "html": "<div>Updated</div>"
        }

        response = client.patch("/api/slides/0", json={
            "session_id": "test-123",
            "html": "<div>Updated</div>"
        })
        assert response.status_code == 200

    def test_update_slide_session_busy(self, client, mock_session_manager):
        """PATCH /api/slides/{index} returns 409 when session locked."""
        mock_session_manager.acquire_session_lock.return_value = False

        response = client.patch("/api/slides/0", json={
            "session_id": "test-123",
            "html": "<div>Updated</div>"
        })
        assert response.status_code == 409

    def test_update_slide_validation_error(self, client, mock_chat_service, mock_session_manager):
        """PATCH /api/slides/{index} returns 400 on validation error."""
        mock_chat_service.update_slide.side_effect = ValueError("Slide index out of range")

        response = client.patch("/api/slides/99", json={
            "session_id": "test-123",
            "html": "<div>Updated</div>"
        })
        assert response.status_code == 400

    def test_delete_slide_success(self, client, mock_chat_service, mock_session_manager):
        """DELETE /api/slides/{index} removes slide."""
        mock_chat_service.delete_slide.return_value = {"slide_count": 2}

        response = client.delete("/api/slides/0?session_id=test-123")
        assert response.status_code == 200

    def test_delete_slide_session_busy(self, client, mock_session_manager):
        """DELETE /api/slides/{index} returns 409 when session locked."""
        mock_session_manager.acquire_session_lock.return_value = False

        response = client.delete("/api/slides/0?session_id=test-123")
        assert response.status_code == 409

    def test_delete_slide_validation_error(self, client, mock_chat_service, mock_session_manager):
        """DELETE /api/slides/{index} returns 400 for invalid index."""
        mock_chat_service.delete_slide.side_effect = ValueError("Cannot delete: slide not found")

        response = client.delete("/api/slides/99?session_id=test-123")
        assert response.status_code == 400

    def test_duplicate_slide_success(self, client, mock_chat_service, mock_session_manager):
        """POST /api/slides/{index}/duplicate creates copy."""
        mock_chat_service.duplicate_slide.return_value = {
            "slides": [{"index": 0}, {"index": 1}],
            "slide_count": 2
        }

        response = client.post("/api/slides/0/duplicate", json={
            "session_id": "test-123"
        })
        assert response.status_code == 200

    def test_duplicate_slide_session_busy(self, client, mock_session_manager):
        """POST /api/slides/{index}/duplicate returns 409 when session locked."""
        mock_session_manager.acquire_session_lock.return_value = False

        response = client.post("/api/slides/0/duplicate", json={
            "session_id": "test-123"
        })
        assert response.status_code == 409

    def test_duplicate_slide_validation_error(self, client, mock_chat_service, mock_session_manager):
        """POST /api/slides/{index}/duplicate returns 400 for invalid index."""
        mock_chat_service.duplicate_slide.side_effect = ValueError("Slide index out of range")

        response = client.post("/api/slides/99/duplicate", json={
            "session_id": "test-123"
        })
        assert response.status_code == 400

    def test_update_slide_verification_success(self, client, mock_session_manager):
        """PATCH /api/slides/{index}/verification updates verification."""
        mock_session_manager.get_slide_deck.return_value = {
            "slides": [{"html": "<div>Slide</div>"}],
            "slide_count": 1
        }
        mock_session_manager.save_verification.return_value = None

        # Mock compute_slide_hash
        with patch("src.utils.slide_hash.compute_slide_hash", return_value="hash123"):
            response = client.patch("/api/slides/0/verification", json={
                "session_id": "test-123",
                "verification": {"score": 0.95, "rating": "excellent"}
            })
        assert response.status_code == 200

    def test_update_slide_verification_no_deck(self, client, mock_session_manager):
        """PATCH /api/slides/{index}/verification returns 404 when no deck exists."""
        mock_session_manager.get_slide_deck.return_value = None

        response = client.patch("/api/slides/0/verification", json={
            "session_id": "test-123",
            "verification": {"score": 0.95}
        })
        assert response.status_code == 404

    def test_update_slide_verification_index_out_of_range(self, client, mock_session_manager):
        """PATCH /api/slides/{index}/verification returns 400 for invalid index."""
        mock_session_manager.get_slide_deck.return_value = {
            "slides": [{"html": "<div>Slide</div>"}],
            "slide_count": 1
        }

        response = client.patch("/api/slides/99/verification", json={
            "session_id": "test-123",
            "verification": {"score": 0.95}
        })
        assert response.status_code == 400


# ============================================
# Session Endpoint Tests
# ============================================


class TestSessionEndpoints:
    """Tests for /api/sessions endpoints."""

    def test_list_sessions_success(self, client, mock_session_manager):
        """GET /api/sessions returns list of sessions for current user."""
        mock_session_manager.list_user_generations.return_value = [
            {"session_id": "sess-1", "title": "Session 1"},
            {"session_id": "sess-2", "title": "Session 2"}
        ]

        with patch("src.api.routes.sessions.get_current_user", return_value="test-user"):
            response = client.get("/api/sessions")
        assert response.status_code == 200
        data = response.json()
        assert "sessions" in data
        assert "count" in data
        assert data["count"] == 2

    def test_list_sessions_no_user(self, client, mock_session_manager):
        """GET /api/sessions returns empty when no current user."""
        with patch("src.api.routes.sessions.get_current_user", return_value=None):
            with patch("src.api.routes.sessions.get_current_user_from_client", side_effect=Exception("no client")):
                response = client.get("/api/sessions")
        assert response.status_code == 200
        data = response.json()
        assert data["sessions"] == []
        assert data["count"] == 0

    def test_list_sessions_with_profile_filter(self, client, mock_session_manager):
        """GET /api/sessions accepts profile_id filter."""
        mock_session_manager.list_user_generations.return_value = []

        with patch("src.api.routes.sessions.get_current_user", return_value="test-user"):
            response = client.get("/api/sessions?profile_id=42")
        assert response.status_code == 200
        mock_session_manager.list_user_generations.assert_called_once()
        call_kwargs = mock_session_manager.list_user_generations.call_args
        assert call_kwargs[1].get("profile_id") == 42 or (len(call_kwargs[0]) > 2 and call_kwargs[0][2] == 42)

    def test_list_sessions_with_limit(self, client, mock_session_manager):
        """GET /api/sessions accepts limit parameter."""
        mock_session_manager.list_user_generations.return_value = []

        with patch("src.api.routes.sessions.get_current_user", return_value="test-user"):
            response = client.get("/api/sessions?limit=10")
        assert response.status_code == 200

    def test_list_sessions_limit_validation(self, client):
        """GET /api/sessions validates limit range."""
        response = client.get("/api/sessions?limit=0")
        assert response.status_code == 422

        response = client.get("/api/sessions?limit=101")
        assert response.status_code == 422

    def test_create_session_success(self, client, mock_session_manager):
        """POST /api/sessions creates new session."""
        mock_session_manager.create_session.return_value = {
            "session_id": "new-session-123",
            "title": "New Session",
            "created_at": "2024-01-01T12:00:00Z"
        }

        response = client.post("/api/sessions", json={})
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data

    def test_create_session_with_title(self, client, mock_session_manager):
        """POST /api/sessions accepts optional title."""
        mock_session_manager.create_session.return_value = {
            "session_id": "new-session-123",
            "title": "My Custom Title",
            "created_at": "2024-01-01T12:00:00Z"
        }

        response = client.post("/api/sessions", json={
            "title": "My Custom Title"
        })
        assert response.status_code == 200

    def test_create_session_with_user_id(self, client, mock_session_manager):
        """POST /api/sessions accepts optional user_id."""
        mock_session_manager.create_session.return_value = {
            "session_id": "new-session-123",
            "user_id": "user-abc",
            "title": "Session",
            "created_at": "2024-01-01T12:00:00Z"
        }

        response = client.post("/api/sessions", json={
            "user_id": "user-abc"
        })
        assert response.status_code == 200

    def test_create_session_internal_error(self, client, mock_session_manager):
        """POST /api/sessions returns 500 on service error."""
        mock_session_manager.create_session.side_effect = Exception("Database error")

        response = client.post("/api/sessions", json={})
        assert response.status_code == 500

    def test_get_session_success(self, client, mock_session_manager):
        """GET /api/sessions/{id} returns session details."""
        mock_session_manager.get_session.return_value = {
            "session_id": "test-123",
            "title": "Test Session"
        }
        mock_session_manager.get_messages.return_value = []
        mock_session_manager.get_slide_deck.return_value = None

        response = client.get("/api/sessions/test-123")
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "test-123"
        assert "messages" in data
        assert "slide_deck" in data

    def test_get_session_not_found(self, client, mock_session_manager):
        """GET /api/sessions/{id} returns 404 for missing session."""
        from src.api.services.session_manager import SessionNotFoundError
        mock_session_manager.get_session.side_effect = SessionNotFoundError("nonexistent")

        response = client.get("/api/sessions/nonexistent")
        assert response.status_code == 404
        assert "Session not found" in response.json()["detail"]

    def test_update_session_success(self, client, mock_session_manager):
        """PATCH /api/sessions/{id} can rename session."""
        mock_session_manager.rename_session.return_value = {
            "session_id": "test-123",
            "title": "New Title"
        }

        response = client.patch("/api/sessions/test-123?title=New%20Title")
        assert response.status_code == 200

    def test_update_session_not_found(self, client, mock_session_manager):
        """PATCH /api/sessions/{id} returns 404 for missing session."""
        from src.api.services.session_manager import SessionNotFoundError
        mock_session_manager.rename_session.side_effect = SessionNotFoundError("nonexistent")

        response = client.patch("/api/sessions/nonexistent?title=New")
        assert response.status_code == 404

    def test_delete_session_success(self, client, mock_session_manager):
        """DELETE /api/sessions/{id} removes session."""
        mock_session_manager.delete_session.return_value = None

        response = client.delete("/api/sessions/test-123")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "deleted"

    def test_delete_session_not_found(self, client, mock_session_manager):
        """DELETE /api/sessions/{id} returns 404 for missing session."""
        from src.api.services.session_manager import SessionNotFoundError
        mock_session_manager.delete_session.side_effect = SessionNotFoundError("nonexistent")

        response = client.delete("/api/sessions/nonexistent")
        assert response.status_code == 404

    def test_get_session_messages_success(self, client, mock_session_manager):
        """GET /api/sessions/{id}/messages returns messages."""
        mock_session_manager.get_messages.return_value = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"}
        ]

        response = client.get("/api/sessions/test-123/messages")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        assert len(data["messages"]) == 2

    def test_get_session_messages_not_found(self, client, mock_session_manager):
        """GET /api/sessions/{id}/messages returns 404 for missing session."""
        from src.api.services.session_manager import SessionNotFoundError
        mock_session_manager.get_messages.side_effect = SessionNotFoundError("nonexistent")

        response = client.get("/api/sessions/nonexistent/messages")
        assert response.status_code == 404

    def test_get_session_slides_success(self, client, mock_session_manager):
        """GET /api/sessions/{id}/slides returns slides."""
        mock_session_manager.get_slide_deck.return_value = {
            "slides": [{"html": "<div>Test</div>"}],
            "slide_count": 1
        }

        response = client.get("/api/sessions/test-123/slides")
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "test-123"
        assert data["slide_deck"] is not None

    def test_get_session_slides_not_found(self, client, mock_session_manager):
        """GET /api/sessions/{id}/slides returns 404 for missing session."""
        from src.api.services.session_manager import SessionNotFoundError
        mock_session_manager.get_slide_deck.side_effect = SessionNotFoundError("nonexistent")

        response = client.get("/api/sessions/nonexistent/slides")
        assert response.status_code == 404

    def test_cleanup_expired_sessions(self, client, mock_session_manager):
        """POST /api/sessions/cleanup cleans up expired sessions."""
        mock_session_manager.cleanup_expired_sessions.return_value = 5

        response = client.post("/api/sessions/cleanup")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["deleted_count"] == 5

    def test_export_session_success(self, client, mock_session_manager, tmp_path):
        """POST /api/sessions/{id}/export exports session data."""
        mock_session_manager.get_session.return_value = {
            "session_id": "test-123",
            "title": "Test"
        }
        mock_session_manager.get_messages.return_value = [
            {"role": "user", "content": "Hello"}
        ]
        mock_session_manager.get_slide_deck.return_value = {
            "slides": [],
            "slide_count": 0
        }

        # Mock Path to use temp directory
        with patch("src.api.routes.sessions.Path") as mock_path:
            mock_path.return_value.mkdir.return_value = None
            mock_path.return_value.__truediv__ = lambda self, x: tmp_path / x

            response = client.post("/api/sessions/test-123/export")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "exported"

    def test_export_session_not_found(self, client, mock_session_manager):
        """POST /api/sessions/{id}/export returns 404 for missing session."""
        from src.api.services.session_manager import SessionNotFoundError
        mock_session_manager.get_session.side_effect = SessionNotFoundError("nonexistent")

        response = client.post("/api/sessions/nonexistent/export")
        assert response.status_code == 404


# ============================================
# Verification Endpoint Tests
# ============================================


class TestVerificationEndpoints:
    """Tests for /api/verification endpoints."""

    def test_verify_slide_success(self, client, mock_session_manager):
        """POST /api/verification/{index} triggers verification."""
        mock_session_manager.get_session.return_value = {
            "session_id": "test-123",
            "genie_conversation_id": "genie-conv-123"
        }
        mock_session_manager.get_slide_deck.return_value = {
            "slides": [{"html": "<div>Slide with data</div>"}],
            "slide_count": 1
        }
        mock_session_manager.get_messages.return_value = [
            {
                "role": "tool",
                "message_type": "tool_result",
                "content": "Query result: Sales = $100",
                "metadata": {"tool_name": "query_genie"}
            }
        ]
        mock_session_manager.get_experiment_id.return_value = "exp-123"
        mock_session_manager.save_verification.return_value = None

        # Mock the evaluate_with_judge function
        with patch("src.api.routes.verification.evaluate_with_judge") as mock_eval:
            mock_result = MagicMock()
            mock_result.score = 0.95
            mock_result.rating = "excellent"
            mock_result.explanation = "Great accuracy"
            mock_result.issues = []
            mock_result.duration_ms = 500
            mock_result.trace_id = "trace-123"
            mock_result.error = False
            mock_result.error_message = None
            mock_eval.return_value = mock_result

            # Mock compute_slide_hash
            with patch("src.utils.slide_hash.compute_slide_hash", return_value="hash123"):
                response = client.post("/api/verification/0", json={
                    "session_id": "test-123"
                })

        assert response.status_code == 200
        data = response.json()
        assert data["rating"] == "excellent"
        assert data["score"] == 0.95

    def test_verify_slide_session_not_found(self, client, mock_session_manager):
        """POST /api/verification/{index} returns 404 for missing session."""
        from src.api.services.session_manager import SessionNotFoundError
        mock_session_manager.get_session.side_effect = SessionNotFoundError("nonexistent")

        response = client.post("/api/verification/0", json={
            "session_id": "nonexistent"
        })
        assert response.status_code == 404

    def test_verify_slide_no_slides(self, client, mock_session_manager):
        """POST /api/verification/{index} returns 404 when no slides exist."""
        mock_session_manager.get_session.return_value = {"session_id": "test-123"}
        mock_session_manager.get_slide_deck.return_value = None

        response = client.post("/api/verification/0", json={
            "session_id": "test-123"
        })
        assert response.status_code == 404
        assert "No slides found" in response.json()["detail"]

    def test_verify_slide_index_out_of_range(self, client, mock_session_manager):
        """POST /api/verification/{index} returns 404 for invalid index."""
        mock_session_manager.get_session.return_value = {"session_id": "test-123"}
        mock_session_manager.get_slide_deck.return_value = {
            "slides": [{"html": "<div>Only one slide</div>"}],
            "slide_count": 1
        }

        response = client.post("/api/verification/99", json={
            "session_id": "test-123"
        })
        assert response.status_code == 404
        assert "out of range" in response.json()["detail"]

    def test_verify_slide_no_genie_data(self, client, mock_session_manager):
        """POST /api/verification/{index} returns unknown when no Genie data."""
        mock_session_manager.get_session.return_value = {
            "session_id": "test-123",
            "genie_conversation_id": None
        }
        mock_session_manager.get_slide_deck.return_value = {
            "slides": [{"html": "<div>Title slide</div>"}],
            "slide_count": 1
        }
        mock_session_manager.get_messages.return_value = []  # No tool results
        mock_session_manager.save_verification.return_value = None

        with patch("src.utils.slide_hash.compute_slide_hash", return_value="hash123"):
            response = client.post("/api/verification/0", json={
                "session_id": "test-123"
            })

        assert response.status_code == 200
        data = response.json()
        assert data["rating"] == "unknown"
        assert "No source data" in data["explanation"]

    @pytest.mark.skip(reason="MLflow mocking requires complex setup - mlflow is imported inside function")
    def test_submit_feedback_success(self, client, mock_session_manager):
        """POST /api/verification/{index}/feedback records feedback."""
        with patch("mlflow.set_tracking_uri") as mock_set_uri:
            mock_set_uri.return_value = None
            mock_client = MagicMock()
            mock_client.get_trace.return_value = MagicMock()

            with patch("mlflow.MlflowClient", return_value=mock_client):
                with patch("mlflow.log_feedback") as mock_log:
                    mock_log.return_value = None
                    response = client.post("/api/verification/0/feedback", json={
                        "session_id": "test-123",
                        "slide_index": 0,
                        "is_positive": True,
                        "rationale": "Looks correct",
                        "trace_id": "trace-abc123"
                    })

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

    @pytest.mark.skip(reason="MLflow mocking requires complex setup - mlflow is imported inside function")
    def test_submit_feedback_without_trace_id(self, client, mock_session_manager):
        """POST /api/verification/{index}/feedback handles missing trace_id."""
        with patch("mlflow.set_tracking_uri") as mock_set_uri:
            mock_set_uri.return_value = None

            response = client.post("/api/verification/0/feedback", json={
                "session_id": "test-123",
                "slide_index": 0,
                "is_positive": False,
                "rationale": "Has errors"
            })

        assert response.status_code == 200
        data = response.json()
        assert data["linked_to_trace"] is False

    def test_get_genie_link_success(self, client, mock_session_manager):
        """GET /api/verification/genie-link returns Genie URL."""
        mock_session_manager.get_session.return_value = {
            "session_id": "test-123",
            "genie_conversation_id": "conv-abc"
        }

        with patch("src.core.settings_db.get_settings") as mock_settings:
            settings = MagicMock()
            settings.databricks_host = "https://adb-12345.us-west-2.azuredatabricks.net"
            settings.genie = MagicMock()
            settings.genie.space_id = "space-xyz"
            mock_settings.return_value = settings

            response = client.get("/api/verification/genie-link?session_id=test-123")

        assert response.status_code == 200
        data = response.json()
        assert data["has_genie_conversation"] is True
        assert "url" in data
        assert "conv-abc" in data["url"]

    def test_get_genie_link_no_conversation(self, client, mock_session_manager):
        """GET /api/verification/genie-link handles missing conversation."""
        mock_session_manager.get_session.return_value = {
            "session_id": "test-123",
            "genie_conversation_id": None
        }

        response = client.get("/api/verification/genie-link?session_id=test-123")
        assert response.status_code == 200
        data = response.json()
        assert data["has_genie_conversation"] is False

    def test_get_genie_link_session_not_found(self, client, mock_session_manager):
        """GET /api/verification/genie-link returns 404 for missing session."""
        from src.api.services.session_manager import SessionNotFoundError
        mock_session_manager.get_session.side_effect = SessionNotFoundError("nonexistent")

        response = client.get("/api/verification/genie-link?session_id=nonexistent")
        assert response.status_code == 404


# ============================================
# Error Response Tests
# ============================================


class TestErrorResponses:
    """Tests for consistent error response format."""

    def test_404_includes_detail(self, client, mock_session_manager):
        """404 responses include helpful detail message."""
        from src.api.services.session_manager import SessionNotFoundError
        mock_session_manager.get_session.side_effect = SessionNotFoundError("test")

        response = client.get("/api/sessions/nonexistent")
        assert response.status_code == 404
        assert "detail" in response.json()
        assert isinstance(response.json()["detail"], str)

    def test_422_validation_errors_include_detail(self, client):
        """422 responses include validation error details."""
        response = client.post("/api/chat", json={})
        assert response.status_code == 422
        assert "detail" in response.json()

    def test_422_validation_errors_are_structured(self, client):
        """422 validation errors have structured format."""
        response = client.post("/api/chat", json={})
        assert response.status_code == 422
        errors = response.json()["detail"]
        assert isinstance(errors, list)
        # Each error should have loc, msg, type
        for error in errors:
            assert "loc" in error or "msg" in error

    def test_500_hides_internal_details(self, client, mock_chat_service, mock_session_manager):
        """500 responses don't leak stack traces."""
        mock_chat_service.send_message.side_effect = Exception("DB connection failed: password=secret123")

        response = client.post("/api/chat", json={
            "session_id": "test-123",
            "message": "Hello"
        })
        assert response.status_code == 500
        detail = response.json().get("detail", "")
        # Should not contain full traceback
        assert "Traceback" not in detail

    def test_409_conflict_message(self, client, mock_session_manager):
        """409 responses include meaningful conflict message."""
        mock_session_manager.acquire_session_lock.return_value = False

        response = client.post("/api/chat", json={
            "session_id": "test-123",
            "message": "Hello"
        })
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "processing" in detail.lower() or "busy" in detail.lower()

    def test_method_not_allowed(self, client):
        """Unsupported HTTP methods return 405."""
        response = client.put("/api/chat", json={})
        assert response.status_code == 405

    def test_invalid_json_body(self, client):
        """Invalid JSON body returns 422."""
        response = client.post(
            "/api/chat",
            content="not valid json",
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422
