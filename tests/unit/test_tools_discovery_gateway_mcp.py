"""Task 3: the discovery union and the per-user Gateway status endpoint.

``GET /api/tools/discover/mcp`` keeps its UC ``items`` (and, on a UC failure, its
``error`` / ``error_code``) exactly as before, and adds ``gateway_items``: the
ENABLED registry rows, each exactly ``{service_name, display_name, description,
agent}``. The registry is read in its OWN try/except (T3.1): a registry failure
gives ``gateway_items: []`` with a WARNING and never touches the UC result.

``GET /api/tools/gateway-mcp/status?service_name=...`` returns ``GatewayStatusOut``
(``{state, message, sign_in_url, tools: [{name, description}]}``):
  - ``not_registered`` for a missing or disabled service, WITHOUT probing;
  - otherwise ``probe_service`` as the CALLING USER (the bound user client's host
    and token, ``token_scopes=oauth_scopes_from_token(token)``), with the row's
    allowlist applied to ``tools`` and ``message`` from ``status_message``.

Harness:
  - an in-memory SQLite engine (``StaticPool``), bound as the process-wide engine
    and session factory (``src.core.database._engine`` / ``_session_local``), with
    the full ORM metadata (or, for T3.1, no tables at all / a factory that raises);
  - a bare ``FastAPI()`` with only ``tools.router``;
  - the user client bound with ``set_user_client(...)``: a ``MagicMock`` with
    ``connections.list`` for discovery, a ``SimpleNamespace(config=...)`` for status;
  - ``get_system_client`` raises in every test, so no path may fall back to the SP;
  - ``GatewayMcpClient.__init__`` is spied and ``GatewayMcpClient.list_tools`` is
    replaced on the CLASS, so no test reaches the network however the route
    imports the client.
"""

from __future__ import annotations

import base64
import importlib
import json
import logging
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from databricks.sdk.errors.platform import PermissionDenied
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register the complete ORM metadata
from src.api.routes import tools as tools_routes
from src.core.database import Base
from src.core.databricks_client import set_user_client
from src.core.scope_errors import consent_message
from src.services.agent_tools.gateway_mcp import (
    GatewayMcpClient,
    GatewayMcpError,
    GatewayToolSpec,
)

DISCOVER = "/api/tools/discover/mcp"
STATUS = "/api/tools/gateway-mcp/status"

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "genie_one" / "error_missing_scope_sdk.json"
)

HOST = "https://adb-1234.5.azuredatabricks.net"
SECOND_HOST = "https://adb-9876.5.azuredatabricks.net"
USER = "user@example.com"
ADMIN = "admin@example.com"
CLIENT_ID = "tellr-app-1234"

LAKEDRAW = "main.tellr_mcp.lakedraw"
WEB_SEARCH = "system.ai.web_search"
GITHUB = "system.ai.github"

SIGN_IN_URL = f"{HOST}/mcp-service-login?name={LAKEDRAW}&o=1234"

STATUS_FIELDS = {"state", "message", "sign_in_url", "tools"}

LAKEDRAW_ITEM = {
    "service_name": LAKEDRAW,
    "display_name": "LakeDraw",
    "description": "Draws architecture diagrams.",
    "agent": "architect",
}
WEB_SEARCH_ITEM = {
    "service_name": WEB_SEARCH,
    "display_name": "Web search",
    "description": None,
    "agent": "data_analyst",
}

JIRA_ITEM = {"id": "jira-conn", "name": "jira-conn", "description": "Jira integration"}

_SCHEMA = {"type": "object"}
DRAW = GatewayToolSpec(name="draw", description="Draw a diagram.", input_schema=_SCHEMA)
RENDER = GatewayToolSpec(name="render", description="Render to PNG.", input_schema=_SCHEMA)
EXPORT = GatewayToolSpec(name="export", description="", input_schema=_SCHEMA)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _jwt(payload: dict[str, Any]) -> str:
    """An unsigned JWT: the scope helpers read its payload unverified."""
    header = _b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    return f"{header}.{_b64(json.dumps(payload).encode())}.sig"


USER_TOKEN = _jwt(
    {"sub": USER, "client_id": CLIENT_ID, "scope": "ai-gateway iam.current-user:read"}
)
USER_SCOPES = frozenset({"ai-gateway", "iam.current-user:read"})


def _by_service(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Gateway items in a fixed order: the response order is not part of the contract."""
    return sorted(items, key=lambda item: item["service_name"])


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_system_client(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_a: Any, **_kw: Any) -> None:
        raise AssertionError("a Gateway discovery/status path reached the service-principal client")

    monkeypatch.setattr("src.core.databricks_client.get_system_client", _raise)


def _bind_db(monkeypatch: pytest.MonkeyPatch, engine: Engine) -> sessionmaker:
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr("src.core.database._engine", engine)
    monkeypatch.setattr("src.core.database._session_local", factory)
    return factory


@pytest.fixture
def db_factory(monkeypatch: pytest.MonkeyPatch) -> Iterator[sessionmaker]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    try:
        yield _bind_db(monkeypatch, engine)
    finally:
        engine.dispose()


@pytest.fixture(params=["table_missing", "database_unreachable"])
def broken_registry(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[str]:
    """The registry cannot be read (T3.1): the table is missing (the default unit DB
    has no tables), or opening a session raises."""
    if request.param == "table_missing":
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        try:
            _bind_db(monkeypatch, engine)
            yield request.param
        finally:
            engine.dispose()
    else:

        def _unreachable(*_a: Any, **_kw: Any) -> None:
            raise OperationalError("SELECT 1", {}, ConnectionRefusedError("connection refused"))

        monkeypatch.setattr("src.core.database._session_local", _unreachable)
        yield request.param


@pytest.fixture
def http() -> TestClient:
    app = FastAPI()
    app.include_router(tools_routes.router)
    return TestClient(app)


def _register(
    factory: sessionmaker,
    service_name: str,
    *,
    display_name: str = "LakeDraw",
    description: str | None = None,
    agent: str = "architect",
    tool_allowlist: list[str] | None = None,
    enabled: bool = True,
) -> None:
    from src.database.models import GatewayMcpConnection

    with factory() as db:
        db.add(
            GatewayMcpConnection(
                service_name=service_name,
                display_name=display_name,
                description=description,
                agent=agent,
                instructions="Model-facing guidance that discovery must not expose.",
                tool_allowlist=tool_allowlist,
                enabled=enabled,
                created_by=ADMIN,
                updated_by=ADMIN,
            )
        )
        db.commit()


def _register_three(factory: sessionmaker) -> None:
    """Two enabled rows (one per agent) and one disabled row."""
    _register(
        factory,
        LAKEDRAW,
        display_name="LakeDraw",
        description="Draws architecture diagrams.",
        agent="architect",
        tool_allowlist=["draw"],
    )
    _register(factory, WEB_SEARCH, display_name="Web search", agent="data_analyst")
    _register(factory, GITHUB, display_name="GitHub", description="Repos.", enabled=False)


# --- UC side ---------------------------------------------------------------


def _missing_scope_error() -> BaseException:
    recorded = json.loads(FIXTURE.read_text())
    module_name, _, class_name = recorded["exception_class"].rpartition(".")
    exc_class = getattr(importlib.import_module(module_name), class_name)
    assert exc_class is PermissionDenied
    return exc_class(recorded["message"])


def _uc_client(*, list_return: list[Any] | None = None, list_side_effect: Any = None) -> MagicMock:
    client = MagicMock()
    client.config.host = HOST
    client.config.token = USER_TOKEN
    if list_side_effect is not None:
        client.connections.list.side_effect = list_side_effect
    else:
        client.connections.list.return_value = list_return or []
    return client


def _uc_connections() -> list[MagicMock]:
    http_conn = MagicMock()
    http_conn.name = "jira-conn"
    http_conn.connection_type.value = "HTTP"
    http_conn.comment = "Jira integration"
    other = MagicMock()
    other.name = "sf-conn"
    other.connection_type.value = "SNOWFLAKE"
    other.comment = "Snowflake"
    return [http_conn, other]


def _tools_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        r
        for r in caplog.records
        if r.name == "src.api.routes.tools" and r.levelno == logging.WARNING
    ]


# --- Gateway side ------------------------------------------------------------


class _GatewayRecorder:
    """What the route asked of GatewayMcpClient. ``result`` is what list_tools gives:
    a list of GatewayToolSpec, or an exception to raise."""

    def __init__(self) -> None:
        self.result: Any = AssertionError(
            "GatewayMcpClient.list_tools was called but this test set no result"
        )
        self.init_calls: list[dict[str, Any]] = []
        self.list_calls: list[dict[str, Any]] = []


@pytest.fixture(autouse=True)
def gateway(monkeypatch: pytest.MonkeyPatch) -> _GatewayRecorder:
    recorder = _GatewayRecorder()
    original_init = GatewayMcpClient.__init__

    def _spy_init(self: GatewayMcpClient, *args: Any, **kwargs: Any) -> None:
        recorder.init_calls.append(dict(kwargs))
        original_init(self, *args, **kwargs)

    def _fake_list_tools(self: GatewayMcpClient, *args: Any, **kwargs: Any) -> list:
        recorder.list_calls.append(dict(kwargs))
        if isinstance(recorder.result, BaseException):
            raise recorder.result
        return list(recorder.result)

    monkeypatch.setattr(GatewayMcpClient, "__init__", _spy_init)
    monkeypatch.setattr(GatewayMcpClient, "list_tools", _fake_list_tools)
    return recorder


def _bind_user(host: str = HOST, token: str = USER_TOKEN) -> None:
    """T2.2: only ``config.host`` / ``config.token`` exist on the bound client."""
    set_user_client(SimpleNamespace(config=SimpleNamespace(host=host, token=token)))


def _status(http: TestClient, service_name: str):
    return http.get(STATUS, params={"service_name": service_name})


def _client_kwargs(call: dict[str, Any]) -> dict[str, Any]:
    return {k: call.get(k) for k in ("host", "token", "service_name", "token_scopes")}


# ---------------------------------------------------------------------------
# GET /api/tools/discover/mcp
# ---------------------------------------------------------------------------


def test_discover_mcp_includes_enabled_gateway_items_only(
    http: TestClient, db_factory: sessionmaker
) -> None:
    _register_three(db_factory)
    set_user_client(_uc_client(list_return=_uc_connections()))

    response = http.get(DISCOVER)

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"items", "gateway_items"}
    assert body["items"] == [JIRA_ITEM]  # the UC shape is unchanged
    assert _by_service(body["gateway_items"]) == [LAKEDRAW_ITEM, WEB_SEARCH_ITEM]


def test_discover_mcp_with_no_registered_connections_has_empty_gateway_items(
    http: TestClient, db_factory: sessionmaker
) -> None:
    set_user_client(_uc_client(list_return=_uc_connections()))

    response = http.get(DISCOVER)

    assert response.status_code == 200, response.text
    assert response.json() == {"items": [JIRA_ITEM], "gateway_items": []}


def test_discover_mcp_gateway_items_survive_uc_scope_error(
    http: TestClient, db_factory: sessionmaker
) -> None:
    _register_three(db_factory)
    set_user_client(_uc_client(list_side_effect=_missing_scope_error()))

    response = http.get(DISCOVER)

    assert response.status_code == 200, response.text
    body = response.json()
    gateway_items = body.pop("gateway_items")
    assert body == {
        "items": [],
        "error": consent_message(oauth_client_id=CLIENT_ID),
        "error_code": "missing_scope",
    }
    assert _by_service(gateway_items) == [LAKEDRAW_ITEM, WEB_SEARCH_ITEM]


def test_discover_mcp_gateway_items_survive_uc_discovery_failure(
    http: TestClient, db_factory: sessionmaker
) -> None:
    _register_three(db_factory)
    set_user_client(_uc_client(list_side_effect=RuntimeError("internal detail")))

    response = http.get(DISCOVER)

    assert response.status_code == 200, response.text
    body = response.json()
    gateway_items = body.pop("gateway_items")
    assert body == {
        "items": [],
        "error": "Could not list MCP connections: RuntimeError",
        "error_code": "discovery_failed",
    }
    assert _by_service(gateway_items) == [LAKEDRAW_ITEM, WEB_SEARCH_ITEM]


def test_discover_mcp_gateway_items_do_not_need_the_user_client(
    http: TestClient, db_factory: sessionmaker
) -> None:
    """The registry is read from the database, so it never needs the user's client
    (or a scope): when building the client fails, the UC half fails as before and
    the Gateway half still answers."""
    _register_three(db_factory)

    def _no_client() -> None:
        raise RuntimeError("no user client")

    with patch.object(tools_routes, "get_user_client", side_effect=_no_client):
        response = http.get(DISCOVER)

    assert response.status_code == 200, response.text
    body = response.json()
    gateway_items = body.pop("gateway_items")
    assert body == {
        "items": [],
        "error": "Could not list MCP connections: RuntimeError",
        "error_code": "discovery_failed",
    }
    assert _by_service(gateway_items) == [LAKEDRAW_ITEM, WEB_SEARCH_ITEM]


def test_discover_mcp_registry_failure_leaves_uc_items_untouched(
    http: TestClient, broken_registry: str, caplog: pytest.LogCaptureFixture
) -> None:
    """T3.1: the registry read has its own try/except; its failure is not a
    ``discovery_failed`` and adds no error keys."""
    set_user_client(_uc_client(list_return=_uc_connections()))
    caplog.set_level(logging.WARNING, logger="src.api.routes.tools")

    response = http.get(DISCOVER)

    assert response.status_code == 200, response.text
    assert response.json() == {"items": [JIRA_ITEM], "gateway_items": []}
    assert _tools_warnings(caplog), "a registry read failure must be logged at WARNING"


def test_discover_mcp_registry_failure_keeps_the_uc_error(
    http: TestClient, broken_registry: str
) -> None:
    set_user_client(_uc_client(list_side_effect=_missing_scope_error()))

    response = http.get(DISCOVER)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "items": [],
        "error": consent_message(oauth_client_id=CLIENT_ID),
        "error_code": "missing_scope",
        "gateway_items": [],
    }


# ---------------------------------------------------------------------------
# GET /api/tools/gateway-mcp/status
# ---------------------------------------------------------------------------


def test_status_not_registered_for_missing(
    http: TestClient, db_factory: sessionmaker, gateway: _GatewayRecorder
) -> None:
    _register(db_factory, WEB_SEARCH, display_name="Web search")
    _bind_user()

    response = _status(http, LAKEDRAW)

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == STATUS_FIELDS
    assert body["state"] == "not_registered"
    assert body["sign_in_url"] is None
    assert body["tools"] == []
    assert body["message"] is None or isinstance(body["message"], str)
    assert gateway.init_calls == [], "a missing service must not be probed"
    assert gateway.list_calls == []


def test_status_not_registered_for_disabled(
    http: TestClient, db_factory: sessionmaker, gateway: _GatewayRecorder
) -> None:
    _register(db_factory, LAKEDRAW, tool_allowlist=["draw"], enabled=False)
    _bind_user()
    gateway.result = [DRAW, RENDER]

    response = _status(http, LAKEDRAW)

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == STATUS_FIELDS
    assert body["state"] == "not_registered"
    assert body["sign_in_url"] is None
    assert body["tools"] == []
    assert gateway.init_calls == [], "a disabled service must not be probed"
    assert gateway.list_calls == []


def test_status_sign_in_required_has_link_and_message(
    http: TestClient, db_factory: sessionmaker, gateway: _GatewayRecorder
) -> None:
    _register(db_factory, LAKEDRAW, display_name="LakeDraw", tool_allowlist=["draw"])
    _bind_user()
    gateway.result = GatewayMcpError(
        "sign_in_required", f"Not signed in to {LAKEDRAW}", sign_in_url=SIGN_IN_URL
    )

    response = _status(http, LAKEDRAW)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "state": "sign_in_required",
        "message": f"To use LakeDraw, sign in here: {SIGN_IN_URL} — then ask again.",
        "sign_in_url": SIGN_IN_URL,
        "tools": [],
    }


def test_status_ready_applies_allowlist(
    http: TestClient, db_factory: sessionmaker, gateway: _GatewayRecorder
) -> None:
    _register(db_factory, LAKEDRAW, tool_allowlist=["draw", "export"])
    _bind_user()
    gateway.result = [DRAW, RENDER, EXPORT]

    response = _status(http, LAKEDRAW)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "state": "ready",
        "message": None,
        "sign_in_url": None,
        "tools": [
            {"name": "draw", "description": "Draw a diagram."},
            {"name": "export", "description": ""},
        ],
    }
    assert len(gateway.list_calls) == 1


def test_status_ready_without_allowlist_lists_every_tool(
    http: TestClient, db_factory: sessionmaker, gateway: _GatewayRecorder
) -> None:
    _register(db_factory, LAKEDRAW, tool_allowlist=None)
    _bind_user()
    gateway.result = [DRAW, RENDER, EXPORT]

    response = _status(http, LAKEDRAW)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "state": "ready",
        "message": None,
        "sign_in_url": None,
        "tools": [
            {"name": "draw", "description": "Draw a diagram."},
            {"name": "render", "description": "Render to PNG."},
            {"name": "export", "description": ""},
        ],
    }


def test_status_probes_as_the_calling_user(
    http: TestClient, db_factory: sessionmaker, gateway: _GatewayRecorder
) -> None:
    _register(db_factory, LAKEDRAW)
    gateway.result = [DRAW]

    _bind_user(HOST, USER_TOKEN)
    first = _status(http, LAKEDRAW)
    _bind_user(SECOND_HOST, "dapi-opaque-token")
    second = _status(http, LAKEDRAW)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert [_client_kwargs(c) for c in gateway.init_calls] == [
        {"host": HOST, "token": USER_TOKEN, "service_name": LAKEDRAW, "token_scopes": USER_SCOPES},
        {
            "host": SECOND_HOST,
            "token": "dapi-opaque-token",
            "service_name": LAKEDRAW,
            "token_scopes": None,
        },
    ]


#: Sentinel: the spec gives no exact status copy for this state, so the message is
#: whatever ``status_message`` returns for it (consent copy also allowed for scope).
FROM_STATUS_MESSAGE = object()

GATEWAY_DETAIL = "detail from the gateway"


@pytest.mark.parametrize(
    ("kind", "state", "message"),
    [
        (
            "access_denied",
            "access_denied",
            f"You don't have access to LakeDraw ({LAKEDRAW}). Ask an admin to grant EXECUTE on it.",
        ),
        (
            "not_found",
            "not_found",
            f"LakeDraw ({LAKEDRAW}) was not found on this workspace. "
            "Ask an admin to check the connection.",
        ),
        ("missing_scope", "missing_scope", FROM_STATUS_MESSAGE),
        ("unavailable", "unavailable", FROM_STATUS_MESSAGE),
        ("timeout", "unavailable", FROM_STATUS_MESSAGE),
    ],
)
def test_status_maps_each_failure_to_its_state(
    http: TestClient,
    db_factory: sessionmaker,
    gateway: _GatewayRecorder,
    kind: str,
    state: str,
    message: Any,
) -> None:
    """The exact copy where the spec gives it; elsewhere ``message`` is what
    ``status_message`` says for the probe's state, display name, service and detail
    (for ``missing_scope`` the existing consent message is accepted too)."""
    _register(db_factory, LAKEDRAW, display_name="LakeDraw", tool_allowlist=["draw"])
    _bind_user()
    gateway.result = GatewayMcpError(kind, GATEWAY_DETAIL)  # type: ignore[arg-type]

    response = _status(http, LAKEDRAW)

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == STATUS_FIELDS
    assert body["state"] == state
    assert body["sign_in_url"] is None
    assert body["tools"] == []
    if message is FROM_STATUS_MESSAGE:
        from src.services.gateway_mcp_registry import status_message

        expected = {
            status_message(
                state,
                display_name="LakeDraw",
                service_name=LAKEDRAW,
                detail=GATEWAY_DETAIL,
                sign_in_url=None,
            )
        }
        if state == "missing_scope":
            expected.add(consent_message(oauth_client_id=CLIENT_ID))
        assert body["message"] in expected
    else:
        assert body["message"] == message


@pytest.mark.parametrize("bad_name", ["a.b", "../x.y.z", "a.b/c.d", ""])
def test_status_never_probes_a_malformed_service_name(
    http: TestClient, db_factory: sessionmaker, gateway: _GatewayRecorder, bad_name: str
) -> None:
    """The name becomes a URL path called with the user's token: a malformed one is
    never probed. Either a 422 or ``not_registered`` (it cannot be registered)."""
    _register(db_factory, LAKEDRAW)
    _bind_user()
    gateway.result = [DRAW]

    response = _status(http, bad_name)

    assert response.status_code in (200, 422), response.text
    if response.status_code == 200:
        assert response.json()["state"] == "not_registered"
    assert gateway.init_calls == []
    assert gateway.list_calls == []
