# Request Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture request-level metrics (endpoint, duration, status) in Lakebase so developers can identify slow endpoints and diagnose performance under load.

**Architecture:** ASGI middleware wraps each API request, captures timing/metadata, and writes to a `request_logs` table via fire-and-forget async task. A daily background cleanup task deletes rows older than 30 days.

**Tech Stack:** FastAPI, Starlette BaseHTTPMiddleware, SQLAlchemy 2.0+ (sync), PostgreSQL/Lakebase, asyncio, pytest

**Spec:** `docs/superpowers/specs/2026-04-01-request-logging-design.md`

---

### Task 1: RequestLog Model

**Files:**
- Create: `src/database/models/request_log.py`
- Modify: `src/database/models/__init__.py`
- Create: `tests/unit/test_request_log_model.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_request_log_model.py
"""Unit tests for the RequestLog model."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base


@pytest.fixture
def db_session():
    """In-memory SQLite for testing."""
    engine = create_engine("sqlite:///:memory:")
    import src.database.models.request_log  # noqa: F401

    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    yield session
    session.close()


class TestRequestLogModel:
    def test_create_request_log(self, db_session):
        from src.database.models.request_log import RequestLog

        log = RequestLog(
            timestamp=datetime.now(timezone.utc),
            method="GET",
            path="/api/sessions/{session_id}",
            status_code=200,
            duration_ms=123.45,
            request_id="550e8400-e29b-41d4-a716-446655440000",
        )
        db_session.add(log)
        db_session.commit()

        result = db_session.query(RequestLog).first()
        assert result.id is not None
        assert result.method == "GET"
        assert result.path == "/api/sessions/{session_id}"
        assert result.status_code == 200
        assert result.duration_ms == 123.45
        assert result.request_id == "550e8400-e29b-41d4-a716-446655440000"

    def test_timestamp_index_exists(self, db_session):
        """Verify the timestamp column has an index."""
        from src.database.models.request_log import RequestLog

        indexes = RequestLog.__table__.indexes
        timestamp_indexes = [
            idx for idx in indexes if "timestamp" in [c.name for c in idx.columns]
        ]
        assert len(timestamp_indexes) == 1

    def test_repr(self, db_session):
        from src.database.models.request_log import RequestLog

        log = RequestLog(
            method="POST",
            path="/api/slides",
            status_code=201,
            duration_ms=50.0,
        )
        assert "POST" in repr(log)
        assert "/api/slides" in repr(log)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_request_log_model.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.database.models.request_log'`

- [ ] **Step 3: Write the model**

```python
# src/database/models/request_log.py
"""Request logging database model for performance monitoring."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Index, Integer, String

from src.core.database import Base


class RequestLog(Base):
    """Stores per-request metrics for performance monitoring."""

    __tablename__ = "request_logs"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    method = Column(String(10), nullable=False)
    path = Column(String(500), nullable=False)
    status_code = Column(Integer, nullable=False)
    duration_ms = Column(Float, nullable=False)
    request_id = Column(String(36), nullable=True)

    __table_args__ = (
        Index("ix_request_logs_timestamp", "timestamp"),
    )

    def __repr__(self):
        return (
            f"<RequestLog(id={self.id}, method='{self.method}', "
            f"path='{self.path}', status_code={self.status_code}, "
            f"duration_ms={self.duration_ms})>"
        )
```

- [ ] **Step 4: Export from models __init__.py**

Add to `src/database/models/__init__.py`:

```python
from src.database.models.request_log import RequestLog
```

And add `"RequestLog"` to the `__all__` list.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_request_log_model.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add src/database/models/request_log.py src/database/models/__init__.py tests/unit/test_request_log_model.py
git commit -m "feat: add RequestLog model for performance monitoring"
```

---

### Task 2: Request Logging Middleware

**Files:**
- Create: `src/api/middleware/__init__.py`
- Create: `src/api/middleware/request_logging.py`
- Create: `tests/unit/test_request_logging_middleware.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_request_logging_middleware.py
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
            "src.api.middleware.request_logging.get_session_local",
            side_effect=Exception("DB down"),
        ):
            response = client.get("/api/sessions/123")
            assert response.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_request_logging_middleware.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.api.middleware'`

- [ ] **Step 3: Create the middleware module**

```python
# src/api/middleware/__init__.py
"""Request middleware."""
```

```python
# src/api/middleware/request_logging.py
"""Request logging middleware for performance monitoring.

Captures per-request metrics (method, path, status, duration) and writes
them to the request_logs table in Lakebase. Uses fire-and-forget async
writes so logging never blocks or breaks the actual request.
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Paths to exclude from logging
_EXCLUDED_PATHS = frozenset({"/api/health", "/api/chat/stream"})
_EXCLUDED_PREFIXES = ("/assets/",)


def _should_log(path: str) -> bool:
    """Check if this request path should be logged."""
    if path in _EXCLUDED_PATHS:
        return False
    for prefix in _EXCLUDED_PREFIXES:
        if path.startswith(prefix):
            return False
    if not path.startswith("/api/"):
        return False
    return True


def _get_route_template(request: Request) -> str:
    """Extract the route template (e.g., /api/sessions/{session_id}) if available."""
    route = request.scope.get("route")
    if route and hasattr(route, "path"):
        return route.path
    return request.url.path


def _enqueue_log(log_entry: dict) -> None:
    """Write a log entry to the database.

    Called via run_in_executor so it never blocks the event loop or the response.
    Imports are lazy to avoid circular imports at module load time.
    """
    from src.core.database import get_session_local
    from src.database.models.request_log import RequestLog

    session_factory = get_session_local()
    session = session_factory()
    try:
        record = RequestLog(**log_entry)
        session.add(record)
        session.commit()
    except Exception:
        logger.debug("Failed to write request log", exc_info=True)
        session.rollback()
    finally:
        session.close()


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware that logs request metrics to Lakebase."""

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        if not _should_log(path):
            return await call_next(request)

        request_id = str(uuid.uuid4())
        start = time.time()

        try:
            response = await call_next(request)
        except Exception:
            # Re-raise but still try to log the failure
            duration_ms = (time.time() - start) * 1000
            try:
                log_entry = {
                    "timestamp": datetime.now(timezone.utc),
                    "method": request.method,
                    "path": _get_route_template(request),
                    "status_code": 500,
                    "duration_ms": duration_ms,
                    "request_id": request_id,
                }
                loop = asyncio.get_running_loop()
                loop.run_in_executor(None, _enqueue_log, log_entry)
            except Exception:
                pass
            raise

        duration_ms = (time.time() - start) * 1000

        response.headers["X-Request-ID"] = request_id

        try:
            log_entry = {
                "timestamp": datetime.now(timezone.utc),
                "method": request.method,
                "path": _get_route_template(request),
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "request_id": request_id,
            }
            loop = asyncio.get_event_loop()
            asyncio.ensure_future(
                loop.run_in_executor(None, _enqueue_log, log_entry)
            )
        except Exception:
            logger.debug("Failed to enqueue request log", exc_info=True)

        return response
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_request_logging_middleware.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/api/middleware/__init__.py src/api/middleware/request_logging.py tests/unit/test_request_logging_middleware.py
git commit -m "feat: add request logging middleware with path filtering and route templates"
```

---

### Task 3: Register Middleware and Cleanup Task in main.py

**Files:**
- Modify: `src/api/main.py`

- [ ] **Step 1: Register the middleware**

Add after the existing `user_auth_middleware` function (after the `@app.middleware("http")` block, approximately line 316):

```python
# Request logging middleware - registered after auth middleware so it wraps outermost
from src.api.middleware.request_logging import RequestLoggingMiddleware

app.add_middleware(RequestLoggingMiddleware)
```

Note: `app.add_middleware()` class-based middleware wraps outside `@app.middleware("http")` decorators, so this will capture the full request time including auth overhead.

- [ ] **Step 2: Add cleanup task to lifespan — startup**

In the lifespan function, add after the export worker start block (around line 126), inside the `if not IS_TESTING:` block:

```python
        # Start the request log cleanup task
        from src.api.middleware.request_logging import request_log_cleanup_loop
        global _cleanup_task
        _cleanup_task = asyncio.create_task(request_log_cleanup_loop())
        logger.info("Request log cleanup task started")
```

Add `_cleanup_task` to the global declarations at the top of the lifespan function and initialize it at module level:

```python
_cleanup_task = None
```

- [ ] **Step 3: Add cleanup task to lifespan — shutdown**

In the shutdown section of lifespan (after the export worker cancellation block, around line 149):

```python
    if _cleanup_task:
        _cleanup_task.cancel()
        try:
            await _cleanup_task
        except asyncio.CancelledError:
            pass
        logger.info("Request log cleanup task stopped")
```

- [ ] **Step 4: Add the cleanup task function to the middleware module**

Add to `src/api/middleware/request_logging.py`:

```python
async def request_log_cleanup_loop():
    """Background task that deletes request logs older than 30 days.

    Checks every hour, executes cleanup if 24+ hours since last run.
    """
    last_cleanup = time.time()

    while True:
        try:
            await asyncio.sleep(3600)  # Check every hour

            if time.time() - last_cleanup < 86400:  # 24 hours
                continue

            def _do_cleanup():
                from src.core.database import get_session_local
                from sqlalchemy import text

                session_factory = get_session_local()
                session = session_factory()
                try:
                    result = session.execute(
                        text("DELETE FROM request_logs WHERE timestamp < NOW() - INTERVAL '30 days'")
                    )
                    session.commit()
                    return result.rowcount
                except Exception:
                    session.rollback()
                    raise
                finally:
                    session.close()

            loop = asyncio.get_running_loop()
            deleted = await loop.run_in_executor(None, _do_cleanup)
            last_cleanup = time.time()
            logger.info(f"Request log cleanup: deleted {deleted} rows older than 30 days")

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("Request log cleanup failed, will retry next cycle", exc_info=True)
```

- [ ] **Step 5: Verify the app starts**

Run: `python -c "from src.api.main import app; print('App imports OK')"`
Expected: `App imports OK`

- [ ] **Step 6: Commit**

```bash
git add src/api/main.py src/api/middleware/request_logging.py
git commit -m "feat: register request logging middleware and cleanup task in lifespan"
```

---

### Task 4: Integration Test

**Files:**
- Create: `tests/integration/test_request_logging.py`

- [ ] **Step 1: Write the integration test**

```python
# tests/integration/test_request_logging.py
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
    """In-memory SQLite engine with request_logs table."""
    engine = create_engine("sqlite:///:memory:")
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
    from src.api.middleware.request_logging import RequestLoggingMiddleware, _enqueue_log
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
```

- [ ] **Step 2: Run the integration test**

Run: `python -m pytest tests/integration/test_request_logging.py -v`
Expected: 3 passed

- [ ] **Step 3: Run the full test suite to verify nothing is broken**

Run: `python -m pytest tests/ -v --timeout=60`
Expected: All existing tests still pass

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_request_logging.py
git commit -m "test: add integration tests for request logging"
```

---

### Task 5: Final Verification

- [ ] **Step 1: Verify all new tests pass in isolation**

Run: `python -m pytest tests/unit/test_request_log_model.py tests/unit/test_request_logging_middleware.py tests/integration/test_request_logging.py -v`
Expected: All 14 tests pass

- [ ] **Step 2: Run the full test suite**

Run: `python -m pytest tests/ -v --timeout=60`
Expected: All tests pass (existing + new)

- [ ] **Step 3: Manual smoke test — start the app and verify middleware is active**

Run: `uvicorn src.api.main:app --port 8000`

In another terminal:
```bash
curl -s -D - http://localhost:8000/api/health | grep -i x-request-id
# Should NOT have X-Request-ID (health is excluded)

curl -s -D - http://localhost:8000/api/version | grep -i x-request-id
# Should have X-Request-ID header
```

- [ ] **Step 4: Commit any fixes, then create final commit if needed**

```bash
git log --oneline -5  # Verify commit history looks clean
```
