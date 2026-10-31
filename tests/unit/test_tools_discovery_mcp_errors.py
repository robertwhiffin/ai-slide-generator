"""GET /api/tools/discover/mcp reports why the list is empty instead of hiding it.

A missing-scope error becomes the consent message (error_code ``missing_scope``);
any other failure becomes a short ``discovery_failed`` line. The success body is
unchanged.
"""

from __future__ import annotations

import base64
import importlib
import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from databricks.sdk.errors.platform import PermissionDenied
from fastapi.testclient import TestClient

ROUTE = "/api/tools/discover/mcp"

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "genie_one" / "error_missing_scope_sdk.json"

CLIENT_ID = "tellr-app-1234"


def _fixture_error() -> BaseException:
    recorded = json.loads(FIXTURE.read_text())
    module_name, _, class_name = recorded["exception_class"].rpartition(".")
    exc_class = getattr(importlib.import_module(module_name), class_name)
    assert exc_class is PermissionDenied
    return exc_class(recorded["message"])


def consent_message(*, oauth_client_id: str | None) -> str:
    # Imported lazily so the discovery_failed and success tests still run (and
    # fail on the body) before src.core.scope_errors exists.
    from src.core.scope_errors import consent_message as real

    return real(oauth_client_id=oauth_client_id)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _jwt(payload: dict) -> str:
    header = _b64url(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    body = _b64url(json.dumps(payload).encode())
    return f"{header}.{body}.c2lnbmF0dXJl"


def _user_client(*, token: str | None, list_side_effect=None, list_return=None) -> MagicMock:
    client = MagicMock()
    client.config.token = token
    if list_side_effect is not None:
        client.connections.list.side_effect = list_side_effect
    else:
        client.connections.list.return_value = list_return or []
    return client


@pytest.fixture
def http():
    from src.api.main import app

    return TestClient(app)


def _warnings_from_tools(caplog) -> list[logging.LogRecord]:
    return [
        r for r in caplog.records
        if r.name == "src.api.routes.tools" and r.levelno == logging.WARNING
    ]


class TestMissingScope:
    def test_fixture_error_returns_consent_message_with_client_id(self, http, caplog):
        token = _jwt({"client_id": CLIENT_ID, "sub": "user@example.com"})
        client = _user_client(token=token, list_side_effect=_fixture_error())
        caplog.set_level(logging.WARNING, logger="src.api.routes.tools")

        with patch("src.api.routes.tools.get_user_client", return_value=client):
            response = http.get(ROUTE)

        assert response.status_code == 200
        body = response.json()
        assert body == {
            "items": [],
            "error": consent_message(oauth_client_id=CLIENT_ID),
            "error_code": "missing_scope",
        }
        # Independent of consent_message: the revoke command names this app's client id.
        assert f"/api/2.0/oauth-app-integrations/{CLIENT_ID}/user-consent/me" in body["error"]

        assert _warnings_from_tools(caplog), "missing-scope failure must be logged at WARNING"
        assert token not in caplog.text, "the user's token must never be logged"

    def test_non_jwt_token_uses_placeholder(self, http):
        client = _user_client(token="dapi123", list_side_effect=_fixture_error())

        with patch("src.api.routes.tools.get_user_client", return_value=client):
            response = http.get(ROUTE)

        assert response.status_code == 200
        body = response.json()
        assert body == {
            "items": [],
            "error": consent_message(oauth_client_id=None),
            "error_code": "missing_scope",
        }
        assert "<this app's OAuth client ID>" in body["error"]

    def test_scope_error_wrapped_as_cause_is_still_missing_scope(self, http):
        inner = _fixture_error()
        try:
            try:
                raise inner
            except PermissionDenied as e:
                raise RuntimeError("listing failed") from e
        except RuntimeError as outer:
            wrapped = outer
        client = _user_client(token=None, list_side_effect=wrapped)

        with patch("src.api.routes.tools.get_user_client", return_value=client):
            body = http.get(ROUTE).json()

        assert body["error_code"] == "missing_scope"
        assert body["items"] == []


class TestDiscoveryFailed:
    def test_runtime_error_returns_discovery_failed(self, http, caplog):
        client = _user_client(
            token=_jwt({"client_id": CLIENT_ID}),
            list_side_effect=RuntimeError("internal detail that must not leak"),
        )
        caplog.set_level(logging.WARNING, logger="src.api.routes.tools")

        with patch("src.api.routes.tools.get_user_client", return_value=client):
            response = http.get(ROUTE)

        assert response.status_code == 200
        assert response.json() == {
            "items": [],
            "error": "Could not list MCP connections: RuntimeError",
            "error_code": "discovery_failed",
        }
        assert _warnings_from_tools(caplog), "discovery failure must be logged at WARNING"

    def test_plain_permission_denied_is_discovery_failed_not_missing_scope(self, http):
        client = _user_client(
            token=_jwt({"client_id": CLIENT_ID}),
            list_side_effect=PermissionDenied("User does not have USE CONNECTION on connection x"),
        )

        with patch("src.api.routes.tools.get_user_client", return_value=client):
            response = http.get(ROUTE)

        assert response.status_code == 200
        assert response.json() == {
            "items": [],
            "error": "Could not list MCP connections: PermissionDenied",
            "error_code": "discovery_failed",
        }


class TestSuccessUnchanged:
    def test_http_connections_listed_with_no_error_keys(self, http):
        http_conn = MagicMock()
        http_conn.name = "jira-conn"
        http_conn.connection_type.value = "HTTP"
        http_conn.comment = "Jira integration"
        other = MagicMock()
        other.name = "sf-conn"
        other.connection_type.value = "SNOWFLAKE"
        other.comment = "Snowflake"
        client = _user_client(token=_jwt({"client_id": CLIENT_ID}), list_return=[http_conn, other])

        with patch("src.api.routes.tools.get_user_client", return_value=client):
            response = http.get(ROUTE)

        assert response.status_code == 200
        assert response.json() == {
            "items": [
                {"id": "jira-conn", "name": "jira-conn", "description": "Jira integration"},
            ],
        }
