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


# Lazy-loaded references (populated on first call to _enqueue_log).
# Declared at module level so they can be patched in tests.
get_session_local = None
RequestLog = None


def _enqueue_log(log_entry: dict) -> None:
    """Write a log entry to the database.

    Called via run_in_executor so it never blocks the event loop or the response.
    Imports are lazy to avoid circular imports at module load time.
    """
    global get_session_local, RequestLog

    if get_session_local is None:
        from src.core.database import get_session_local as _gsl
        from src.database.models.request_log import RequestLog as _RL

        get_session_local = _gsl
        RequestLog = _RL

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
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, _enqueue_log, log_entry)
        except Exception:
            logger.debug("Failed to enqueue request log", exc_info=True)

        return response
