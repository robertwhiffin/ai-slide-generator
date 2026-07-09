"""Sessions-route 500s must never echo internal DB error detail.

Live-incident shape (dsv1): with the database unreachable, the sessions
routes returned the RAW psycopg2/SQLAlchemy error in the response body —
leaking the internal Postgres endpoint hostname (``ep-…``) and the app
service-principal client id (a UUID) — while the design-systems routes
returned a sanitized generic message. These tests pin the sanitized
behavior: generic body, full detail server-log only.

All fixture values are SYNTHETIC (fake endpoint host, fake client id).
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app

# Synthetic stand-in for the real incident error: psycopg2's operational
# error text carries the endpoint hostname and the SP client id as the role.
_SYNTHETIC_DB_ERROR = (
    "(psycopg2.OperationalError) connection to server at "
    '"ep-synthetic-fixture-123456.aws.example.internal" (10.0.0.1), port 5432 '
    'failed: FATAL: password authentication failed for user '
    '"12345678-abcd-4ef0-9876-fedcba987654"'
)

_LEAK_FRAGMENTS = (
    "ep-",  # internal Postgres endpoint hostname prefix
    "12345678-abcd-4ef0-9876-fedcba987654",  # UUID-shaped SP client id
    "password authentication",  # raw driver error text
    "psycopg2",
)


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def _failing_manager() -> MagicMock:
    mgr = MagicMock()
    boom = Exception(_SYNTHETIC_DB_ERROR)
    mgr.list_sessions.side_effect = boom
    mgr.get_session.side_effect = boom
    return mgr


def _assert_sanitized(response, expected_message: str) -> None:
    assert response.status_code == 500
    body = response.text
    for fragment in _LEAK_FRAGMENTS:
        assert fragment not in body, f"response body leaked {fragment!r}: {body}"
    assert expected_message in body


class TestSessionsRouteErrorSanitization:
    @patch("src.api.routes.sessions.get_current_user", return_value="u@test.com")
    @patch("src.api.routes.sessions.get_session_manager")
    def test_list_sessions_500_is_generic(self, mock_get_mgr, mock_user, client):
        mock_get_mgr.return_value = _failing_manager()

        response = client.get("/api/sessions?limit=5")

        _assert_sanitized(response, "Failed to list sessions")

    @patch("src.api.routes.sessions.get_current_user", return_value="u@test.com")
    @patch("src.api.routes.sessions.get_session_manager")
    def test_get_session_500_is_generic(self, mock_get_mgr, mock_user, client):
        mock_get_mgr.return_value = _failing_manager()

        # Permission gate runs before the manager; let it pass through.
        with patch(
            "src.api.routes.sessions._check_deck_permission_for_session",
            return_value=None,
        ):
            response = client.get("/api/sessions/sess-1")

        _assert_sanitized(response, "Failed to get session")

    @patch("src.api.routes.sessions.get_current_user", return_value="u@test.com")
    def test_list_shared_500_is_generic(self, mock_user, client):
        from src.core.database import get_db

        ctx = MagicMock()
        ctx.user_id = "uid-1"
        ctx.user_name = "u@test.com"
        ctx.group_ids = []

        app.dependency_overrides[get_db] = lambda: iter([MagicMock()])
        try:
            with patch(
                "src.api.routes.sessions.get_permission_context", return_value=ctx
            ), patch(
                "src.api.routes.sessions.get_permission_service"
            ) as mock_perm_service:
                mock_perm_service.return_value.get_shared_session_ids.side_effect = (
                    Exception(_SYNTHETIC_DB_ERROR)
                )
                response = client.get("/api/sessions/shared?limit=5")
        finally:
            app.dependency_overrides.pop(get_db, None)

        _assert_sanitized(response, "Failed to list shared presentations")

    @patch("src.api.routes.sessions.get_current_user", return_value="u@test.com")
    @patch("src.api.routes.sessions.get_session_manager")
    def test_lock_endpoints_500_are_generic(self, mock_get_mgr, mock_user, client):
        mgr = MagicMock()
        mgr.acquire_editing_lock.side_effect = Exception(_SYNTHETIC_DB_ERROR)
        mgr.get_editing_lock_status.side_effect = Exception(_SYNTHETIC_DB_ERROR)
        mock_get_mgr.return_value = mgr

        with patch(
            "src.api.routes.sessions._check_deck_permission_for_session",
            return_value=None,
        ):
            acquire = client.post("/api/sessions/sess-1/lock")
            status = client.get("/api/sessions/sess-1/lock")

        _assert_sanitized(acquire, "Failed to acquire editing lock")
        _assert_sanitized(status, "Failed to check editing lock")
