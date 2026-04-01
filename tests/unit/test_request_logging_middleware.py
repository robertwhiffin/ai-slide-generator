"""Unit tests for the request logging middleware."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request
from starlette.responses import Response
from starlette.testclient import TestClient
from fastapi import FastAPI

from src.api.middleware.request_logging import RequestLoggingMiddleware


@pytest.fixture
def test_app():
    """Create a minimal FastAPI app with the logging middleware."""
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: str):
        return {"id": session_id}

    @app.get("/api/health")
    async def health():
        return {"status": "healthy"}

    @app.get("/assets/main.js")
    async def asset():
        return Response(content="js", media_type="application/javascript")

    return app


@pytest.fixture
def client(test_app):
    return TestClient(test_app)


class TestPathFiltering:
    def test_logs_api_requests(self, client):
        """API requests should be logged."""
        with patch(
            "src.api.middleware.request_logging._enqueue_log"
        ) as mock_enqueue:
            client.get("/api/sessions/123")
            mock_enqueue.assert_called_once()

    def test_skips_health_endpoint(self, client):
        """Health checks should not be logged."""
        with patch(
            "src.api.middleware.request_logging._enqueue_log"
        ) as mock_enqueue:
            client.get("/api/health")
            mock_enqueue.assert_not_called()

    def test_skips_static_assets(self, client):
        """Static assets should not be logged."""
        with patch(
            "src.api.middleware.request_logging._enqueue_log"
        ) as mock_enqueue:
            client.get("/assets/main.js")
            mock_enqueue.assert_not_called()

    def test_skips_chat_stream(self, client, test_app):
        """SSE streaming endpoint should not be logged."""

        @test_app.post("/api/chat/stream")
        async def stream():
            return Response(content="stream")

        with patch(
            "src.api.middleware.request_logging._enqueue_log"
        ) as mock_enqueue:
            client.post("/api/chat/stream")
            mock_enqueue.assert_not_called()


class TestRouteTemplateExtraction:
    def test_logs_route_template_not_resolved_path(self, client):
        """Should log /api/sessions/{session_id} not /api/sessions/123."""
        with patch(
            "src.api.middleware.request_logging._enqueue_log"
        ) as mock_enqueue:
            client.get("/api/sessions/abc-123")
            call_kwargs = mock_enqueue.call_args
            log_entry = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1]
            assert "/api/sessions/{session_id}" in str(log_entry)


class TestRequestIdHeader:
    def test_response_includes_request_id_header(self, client):
        """Response should have X-Request-ID header."""
        with patch("src.api.middleware.request_logging._enqueue_log"):
            response = client.get("/api/sessions/123")
            assert "X-Request-ID" in response.headers
            # Should be a valid UUID format (36 chars with hyphens)
            assert len(response.headers["X-Request-ID"]) == 36


class TestPathFilteringNonApi:
    def test_skips_non_api_paths(self, client, test_app):
        """Non-/api/ paths (SPA routes, root) should not be logged."""

        @test_app.get("/")
        async def root():
            return {"page": "home"}

        with patch(
            "src.api.middleware.request_logging._enqueue_log"
        ) as mock_enqueue:
            client.get("/")
            mock_enqueue.assert_not_called()


class TestErrorIsolation:
    def test_middleware_survives_db_write_failure(self, client):
        """If the DB write inside _enqueue_log fails, the request should still succeed."""
        with patch(
            "src.core.database.get_session_local",
            side_effect=Exception("DB down"),
        ):
            response = client.get("/api/sessions/123")
            assert response.status_code == 200
