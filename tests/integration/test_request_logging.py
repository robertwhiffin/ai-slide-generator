"""Integration tests for request logging middleware.

Verifies that API requests result in rows written to the request_logs table.

Run: pytest tests/integration/test_request_logging.py -v
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base
from src.database.models.request_log import RequestLog


@pytest.fixture
def db_engine():
    """In-memory SQLite engine with request_logs table.

    Uses a shared-cache URI so the same database is visible across threads
    (the middleware fires _enqueue_log via run_in_executor).
    """
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def db_session_factory(db_engine):
    return sessionmaker(bind=db_engine)


@pytest.fixture
def logged_entries():
    """Collects log entries written by the middleware synchronously."""
    return []


@pytest.fixture
def client(db_session_factory, logged_entries):
    """TestClient with middleware wired to in-memory DB.

    Patches _enqueue_log to write synchronously (bypassing run_in_executor)
    so tests don't need time.sleep() to wait for fire-and-forget tasks.
    """
    from src.api.middleware.request_logging import RequestLoggingMiddleware
    from fastapi import FastAPI

    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: str):
        return {"id": session_id}

    @app.get("/api/slides")
    async def list_slides():
        return {"slides": []}

    def _sync_enqueue(log_entry):
        """Write synchronously using the test DB session factory."""
        session = db_session_factory()
        try:
            record = RequestLog(**log_entry)
            session.add(record)
            session.commit()
            logged_entries.append(log_entry)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    with patch(
        "src.api.middleware.request_logging._enqueue_log",
        side_effect=_sync_enqueue,
    ):
        yield TestClient(app)


class TestRequestLoggingIntegration:
    def test_api_request_creates_log_row(self, client, db_session_factory):
        """An API request should result in a row in request_logs."""
        client.get("/api/slides")

        session = db_session_factory()
        logs = session.query(RequestLog).all()
        assert len(logs) == 1
        assert logs[0].method == "GET"
        assert logs[0].path == "/api/slides"
        assert logs[0].status_code == 200
        assert logs[0].duration_ms >= 0
        assert logs[0].request_id is not None
        session.close()

    def test_multiple_requests_create_multiple_rows(self, client, db_session_factory):
        """Each request should create its own log row."""
        client.get("/api/slides")
        client.get("/api/sessions/abc")
        client.get("/api/sessions/def")

        session = db_session_factory()
        logs = session.query(RequestLog).all()
        assert len(logs) == 3
        session.close()

    def test_route_template_logged_not_resolved_path(self, client, db_session_factory):
        """Parameterized routes should log the template."""
        client.get("/api/sessions/my-session-id")

        session = db_session_factory()
        log = session.query(RequestLog).first()
        assert log.path == "/api/sessions/{session_id}"
        session.close()
