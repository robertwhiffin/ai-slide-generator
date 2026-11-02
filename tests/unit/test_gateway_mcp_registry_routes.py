"""Task 2: the Gateway MCP connection registry and its admin API.

Routes under ``/api/admin/gateway-mcp-connections`` (admin-only, ``require_admin``):
list, create, update, delete, and ``POST /test``, which runs ``tools/list`` AS THE
CALLING ADMIN (the bound user client's host and token).

Harness (the recipe of ``test_agent_definition_workbench_routes.py``):
  - an in-memory SQLite engine (``StaticPool``) with ``Base.metadata.create_all``;
  - a bare ``FastAPI()`` that includes only ``admin_gateway_mcp.router``, with
    ``app.dependency_overrides[get_db]`` yielding a session from that engine (T2.1);
  - ``require_admin`` overridden to allow (admin tests) or to raise 403 (non-admin);
  - the request's user set with ``set_current_user`` and the user client bound with
    ``set_user_client(SimpleNamespace(config=SimpleNamespace(host=..., token=...)))``
    (T2.2). ContextVars set in the test thread reach the route at request time.
  - ``GatewayMcpClient.__init__`` is spied and ``GatewayMcpClient.list_tools`` is
    replaced on the CLASS, so no test reaches the network however the route imports
    the client; ``get_system_client`` raises, so no route may fall back to the SP.
"""

from __future__ import annotations

import base64
import dataclasses
import json
from collections.abc import Iterator
from datetime import datetime
from types import SimpleNamespace
from typing import Any, get_args

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register the complete ORM metadata
from src.api.routes import admin_gateway_mcp
from src.api.routes._authz import require_admin
from src.api.schemas.gateway_mcp import GatewayStatusOut
from src.core.database import Base, get_db
from src.core.databricks_client import reset_user_client, set_user_client
from src.core.user_context import set_current_user
from src.database.models import GatewayMcpConnection
from src.services import gateway_mcp_registry as registry
from src.services.agent_tools.gateway_mcp import (
    GatewayMcpClient,
    GatewayMcpError,
    GatewayToolSpec,
)

BASE = "/api/admin/gateway-mcp-connections"

ADMIN = "admin@example.com"
SECOND_ADMIN = "second-admin@example.com"
HOST = "https://adb-1234.5.azuredatabricks.net"
SECOND_HOST = "https://adb-9876.5.azuredatabricks.net"

#: Every column of the table, which is exactly the field set of GatewayConnectionOut.
OUT_FIELDS = {
    "id",
    "service_name",
    "display_name",
    "description",
    "agent",
    "instructions",
    "tool_allowlist",
    "enabled",
    "created_by",
    "updated_by",
    "created_at",
    "updated_at",
}
STATUS_FIELDS = {"state", "message", "sign_in_url", "tools"}

LAKEDRAW = "main.tellr_mcp.lakedraw"
SIGN_IN_URL = f"{HOST}/mcp-service-login?name={LAKEDRAW}&o=1234"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _jwt(payload: dict[str, Any]) -> str:
    """An unsigned JWT: ``oauth_scopes_from_token`` reads its payload unverified."""
    header = _b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    return f"{header}.{_b64(json.dumps(payload).encode())}.sig"


ADMIN_TOKEN = _jwt({"sub": ADMIN, "scope": "ai-gateway iam.current-user:read"})
ADMIN_SCOPES = frozenset({"ai-gateway", "iam.current-user:read"})


def _user_client(host: str, token: str) -> SimpleNamespace:
    return SimpleNamespace(config=SimpleNamespace(host=host, token=token))


def _create_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "service_name": LAKEDRAW,
        "display_name": "LakeDraw",
        "description": "Draws architecture diagrams.",
        "agent": "architect",
        "instructions": "Use LakeDraw for every architecture diagram.",
        "tool_allowlist": ["draw"],
        "enabled": True,
    }
    body.update(overrides)
    return body


def _update_body(**overrides: Any) -> dict[str, Any]:
    """The six editable fields (T8.3): everything but ``service_name``."""
    body = _create_body(**overrides)
    body.pop("service_name")
    return body


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


@pytest.fixture
def session_factory() -> Iterator[sessionmaker]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False)
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def _bound_admin(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The request's user is ADMIN, whose user client carries ADMIN_TOKEN (T2.2)."""

    def _no_system_client(*_a: Any, **_kw: Any) -> None:
        raise AssertionError("a Gateway admin route reached the service-principal client")

    monkeypatch.setattr("src.core.databricks_client.get_system_client", _no_system_client)
    set_current_user(ADMIN)
    set_user_client(_user_client(HOST, ADMIN_TOKEN))
    try:
        yield
    finally:
        set_current_user(None)
        reset_user_client()


class _GatewayRecorder:
    """What the routes asked of GatewayMcpClient. ``result`` is what list_tools gives:
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


def _deny_admin() -> None:
    raise HTTPException(status_code=403, detail="Admin access required")


def _build_app(session_factory: sessionmaker, *, admin: bool) -> TestClient:
    app = FastAPI()
    app.include_router(admin_gateway_mcp.router)

    def _override_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[require_admin] = (lambda: None) if admin else _deny_admin
    return TestClient(app)


@pytest.fixture
def client(session_factory: sessionmaker) -> TestClient:
    return _build_app(session_factory, admin=True)


def _rows(session_factory: sessionmaker) -> list[GatewayMcpConnection]:
    with session_factory() as s:
        return list(s.scalars(select(GatewayMcpConnection).order_by(GatewayMcpConnection.id)))


def _row(session_factory: sessionmaker, connection_id: int) -> GatewayMcpConnection | None:
    with session_factory() as s:
        return s.get(GatewayMcpConnection, connection_id)


def _row_count(session_factory: sessionmaker) -> int:
    with session_factory() as s:
        return s.scalar(select(func.count()).select_from(GatewayMcpConnection))


def _snapshot(row: GatewayMcpConnection) -> dict[str, Any]:
    return {field: getattr(row, field) for field in OUT_FIELDS}


def _seed(session_factory: sessionmaker, **overrides: Any) -> int:
    values: dict[str, Any] = {
        "service_name": LAKEDRAW,
        "display_name": "LakeDraw",
        "description": None,
        "agent": "architect",
        "instructions": None,
        "tool_allowlist": ["draw"],
        "enabled": True,
        "created_by": "seed@example.com",
        "updated_by": "seed@example.com",
    }
    values.update(overrides)
    with session_factory() as s:
        row = GatewayMcpConnection(**values)
        s.add(row)
        s.commit()
        return row.id


# ---------------------------------------------------------------------------
# The router
# ---------------------------------------------------------------------------


def test_router_exposes_exactly_the_five_admin_routes() -> None:
    """The non-admin parametrisation below covers the router's whole surface."""
    pairs = {
        (method, route.path)
        for route in admin_gateway_mcp.router.routes
        for method in getattr(route, "methods", None) or ()
    }
    assert pairs == {
        ("GET", BASE),
        ("POST", BASE),
        ("PUT", f"{BASE}/{{connection_id}}"),
        ("DELETE", f"{BASE}/{{connection_id}}"),
        ("POST", f"{BASE}/test"),
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def test_create_list_update_delete_round_trip(
    client: TestClient, session_factory: sessionmaker
) -> None:
    created = client.post(BASE, json=_create_body(service_name="Main.X.Y"))

    assert created.status_code == 201, created.text
    body = created.json()
    assert set(body) == OUT_FIELDS
    assert isinstance(body["id"], int)
    assert {k: v for k, v in body.items() if k not in ("id", "created_at", "updated_at")} == {
        "service_name": "main.x.y",
        "display_name": "LakeDraw",
        "description": "Draws architecture diagrams.",
        "agent": "architect",
        "instructions": "Use LakeDraw for every architecture diagram.",
        "tool_allowlist": ["draw"],
        "enabled": True,
        "created_by": ADMIN,
        "updated_by": ADMIN,
    }
    connection_id = body["id"]
    stored = _row(session_factory, connection_id)
    assert stored is not None
    assert stored.service_name == "main.x.y"
    assert stored.created_by == ADMIN
    assert stored.updated_by == ADMIN
    assert stored.created_at is not None

    listed = client.get(BASE)
    assert listed.status_code == 200
    assert listed.json() == [body]

    # Backdate updated_at so "advances" cannot pass on a same-microsecond clock.
    backdated = datetime(2020, 1, 1)
    with session_factory() as s:
        s.execute(
            update(GatewayMcpConnection)
            .where(GatewayMcpConnection.id == connection_id)
            .values(updated_at=backdated)
        )
        s.commit()
    created_at_before = _row(session_factory, connection_id).created_at

    set_current_user(SECOND_ADMIN)
    updated = client.put(
        f"{BASE}/{connection_id}",
        json=_update_body(
            display_name="LakeDraw v2",
            description=None,
            agent="data_analyst",
            instructions=None,
            tool_allowlist=["draw", "render"],
            enabled=False,
        ),
    )

    assert updated.status_code == 200, updated.text
    out = updated.json()
    assert set(out) == OUT_FIELDS
    assert {k: v for k, v in out.items() if k not in ("created_at", "updated_at")} == {
        "id": connection_id,
        "service_name": "main.x.y",
        "display_name": "LakeDraw v2",
        "description": None,
        "agent": "data_analyst",
        "instructions": None,
        "tool_allowlist": ["draw", "render"],
        "enabled": False,
        "created_by": ADMIN,
        "updated_by": SECOND_ADMIN,
    }
    stored = _row(session_factory, connection_id)
    assert stored.agent == "data_analyst"
    assert stored.tool_allowlist == ["draw", "render"]
    assert stored.enabled is False
    assert stored.updated_by == SECOND_ADMIN
    assert stored.created_by == ADMIN
    assert stored.updated_at > backdated
    assert stored.created_at == created_at_before

    # A disabled connection is still listed: the admin must be able to re-enable it.
    relisted = client.get(BASE)
    assert relisted.status_code == 200
    assert relisted.json() == [out]

    deleted = client.delete(f"{BASE}/{connection_id}")
    assert deleted.status_code == 204
    assert deleted.content == b""
    after = client.get(BASE)
    assert after.status_code == 200
    assert after.json() == []
    assert _row(session_factory, connection_id) is None


def test_create_defaults_enabled_true_and_optional_fields_null(
    client: TestClient, session_factory: sessionmaker
) -> None:
    created = client.post(
        BASE,
        json={
            "service_name": "system.ai.web_search",
            "display_name": "Web search",
            "agent": "architect",
        },
    )

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["enabled"] is True
    assert body["description"] is None
    assert body["instructions"] is None
    assert body["tool_allowlist"] is None
    stored = _row(session_factory, body["id"])
    assert stored.enabled is True
    assert stored.tool_allowlist is None


def test_list_returns_every_connection_enabled_or_not(
    client: TestClient, session_factory: sessionmaker
) -> None:
    _seed(session_factory, service_name="main.a.one", display_name="One", enabled=True)
    _seed(session_factory, service_name="main.b.two", display_name="Two", enabled=False)

    listed = client.get(BASE)

    assert listed.status_code == 200
    by_service = {item["service_name"]: item for item in listed.json()}
    assert set(by_service) == {"main.a.one", "main.b.two"}
    assert by_service["main.a.one"]["enabled"] is True
    assert by_service["main.b.two"]["enabled"] is False
    assert all(set(item) == OUT_FIELDS for item in listed.json())


def test_duplicate_service_is_409(client: TestClient, session_factory: sessionmaker) -> None:
    first = client.post(BASE, json=_create_body(service_name="main.x.y", display_name="First"))
    assert first.status_code == 201, first.text

    # The same name after normalisation is a duplicate too.
    second = client.post(BASE, json=_create_body(service_name=" Main.X.Y ", display_name="Second"))

    assert second.status_code == 409, second.text
    rows = _rows(session_factory)
    assert [(r.service_name, r.display_name) for r in rows] == [("main.x.y", "First")]


@pytest.mark.parametrize(
    "bad_name",
    ["a.b", "a.b.c.d", "a.b/c.d", "a b.c.d", "", "   ", "a..c", "main.x.y;drop"],
)
def test_bad_service_name_is_422(
    client: TestClient, session_factory: sessionmaker, bad_name: str
) -> None:
    response = client.post(BASE, json=_create_body(service_name=bad_name))

    assert response.status_code == 422, response.text
    assert _row_count(session_factory) == 0


def test_update_rejects_service_name_field_422(
    client: TestClient, session_factory: sessionmaker
) -> None:
    connection_id = _seed(session_factory, service_name="main.x.y", display_name="LakeDraw")
    before = _snapshot(_row(session_factory, connection_id))

    response = client.put(
        f"{BASE}/{connection_id}",
        json={**_update_body(display_name="Renamed"), "service_name": "main.x.z"},
    )

    assert response.status_code == 422, response.text
    assert _snapshot(_row(session_factory, connection_id)) == before


def test_update_and_delete_of_an_unknown_id_are_404(
    client: TestClient, session_factory: sessionmaker
) -> None:
    connection_id = _seed(session_factory)
    before = _snapshot(_row(session_factory, connection_id))
    missing = connection_id + 1000

    put = client.put(f"{BASE}/{missing}", json=_update_body())
    delete = client.delete(f"{BASE}/{missing}")

    assert put.status_code == 404, put.text
    assert delete.status_code == 404, delete.text
    assert _row_count(session_factory) == 1
    assert _snapshot(_row(session_factory, connection_id)) == before


def test_delete_twice_is_204_then_404(client: TestClient, session_factory: sessionmaker) -> None:
    connection_id = _seed(session_factory)

    assert client.delete(f"{BASE}/{connection_id}").status_code == 204
    assert client.delete(f"{BASE}/{connection_id}").status_code == 404
    assert _row_count(session_factory) == 0


def test_instructions_over_4000_chars_is_422(
    client: TestClient, session_factory: sessionmaker
) -> None:
    assert registry.INSTRUCTIONS_MAX_CHARS == 4000

    too_long = client.post(BASE, json=_create_body(instructions="x" * 4001))
    assert too_long.status_code == 422, too_long.text
    assert _row_count(session_factory) == 0

    at_limit = client.post(BASE, json=_create_body(instructions="x" * 4000))
    assert at_limit.status_code == 201, at_limit.text
    connection_id = at_limit.json()["id"]
    assert _row(session_factory, connection_id).instructions == "x" * 4000

    before = _snapshot(_row(session_factory, connection_id))
    update_too_long = client.put(
        f"{BASE}/{connection_id}", json=_update_body(instructions="y" * 4001)
    )
    assert update_too_long.status_code == 422, update_too_long.text
    assert _snapshot(_row(session_factory, connection_id)) == before


@pytest.mark.parametrize("bad_display_name", ['Lake"Draw', "Lake<Draw", "Lake>Draw", "<b>x</b>"])
def test_display_name_with_quote_or_angle_bracket_is_422(
    client: TestClient, session_factory: sessionmaker, bad_display_name: str
) -> None:
    """T2.4: display_name becomes the spotlight ``source`` attribute."""
    created = client.post(BASE, json=_create_body(display_name=bad_display_name))
    assert created.status_code == 422, created.text
    assert _row_count(session_factory) == 0

    connection_id = _seed(session_factory)
    before = _snapshot(_row(session_factory, connection_id))
    updated = client.put(
        f"{BASE}/{connection_id}", json=_update_body(display_name=bad_display_name)
    )
    assert updated.status_code == 422, updated.text
    assert _snapshot(_row(session_factory, connection_id)) == before


def test_display_name_is_stripped_and_1_to_120_chars(
    client: TestClient, session_factory: sessionmaker
) -> None:
    padded = client.post(
        BASE, json=_create_body(service_name="main.s.one", display_name="  LakeDraw  ")
    )
    assert padded.status_code == 201, padded.text
    assert padded.json()["display_name"] == "LakeDraw"
    assert _row(session_factory, padded.json()["id"]).display_name == "LakeDraw"

    longest = client.post(
        BASE, json=_create_body(service_name="main.s.two", display_name=" " + "y" * 120 + " ")
    )
    assert longest.status_code == 201, longest.text
    assert longest.json()["display_name"] == "y" * 120

    for bad in ("", "   ", "z" * 121):
        response = client.post(BASE, json=_create_body(service_name="main.s.bad", display_name=bad))
        assert response.status_code == 422, (bad, response.text)
    assert {r.service_name for r in _rows(session_factory)} == {"main.s.one", "main.s.two"}


def test_tool_allowlist_is_deduplicated_keeping_order(
    client: TestClient, session_factory: sessionmaker
) -> None:
    created = client.post(BASE, json=_create_body(tool_allowlist=["b", "a", "b", "c", "a"]))

    assert created.status_code == 201, created.text
    assert created.json()["tool_allowlist"] == ["b", "a", "c"]
    connection_id = created.json()["id"]
    assert _row(session_factory, connection_id).tool_allowlist == ["b", "a", "c"]

    updated = client.put(
        f"{BASE}/{connection_id}", json=_update_body(tool_allowlist=["z", "y", "z"])
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["tool_allowlist"] == ["z", "y"]
    assert _row(session_factory, connection_id).tool_allowlist == ["z", "y"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"tool_allowlist": [""]},
        {"tool_allowlist": ["draw", ""]},
        {"agent": "builder"},
        {"agent": "Architect"},
    ],
    ids=["blank-tool", "blank-tool-among-others", "unknown-agent", "agent-case"],
)
def test_invalid_allowlist_entry_or_agent_is_422(
    client: TestClient, session_factory: sessionmaker, overrides: dict[str, Any]
) -> None:
    response = client.post(BASE, json=_create_body(**overrides))

    assert response.status_code == 422, response.text
    assert _row_count(session_factory) == 0


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------

_NEW_SERVICE = "main.other.svc"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", BASE, None),
        ("POST", BASE, "create"),
        ("PUT", f"{BASE}/{{id}}", "update"),
        ("DELETE", f"{BASE}/{{id}}", None),
        ("POST", f"{BASE}/test", "test"),
    ],
    ids=["list", "create", "update", "delete", "test"],
)
def test_non_admin_gets_403(
    session_factory: sessionmaker,
    gateway: _GatewayRecorder,
    method: str,
    path: str,
    body: str | None,
) -> None:
    connection_id = _seed(session_factory)
    before = _snapshot(_row(session_factory, connection_id))
    gateway.result = []
    payload = {
        None: None,
        "create": _create_body(service_name=_NEW_SERVICE),
        "update": _update_body(display_name="Hijacked", enabled=False),
        "test": {"service_name": LAKEDRAW},
    }[body]
    client = _build_app(session_factory, admin=False)

    response = client.request(method, path.format(id=connection_id), json=payload)

    assert response.status_code == 403, response.text
    assert _row_count(session_factory) == 1
    assert _snapshot(_row(session_factory, connection_id)) == before
    assert gateway.init_calls == []
    assert gateway.list_calls == []


# ---------------------------------------------------------------------------
# POST /test — tools/list as the calling admin
# ---------------------------------------------------------------------------


def test_connection_test_reports_sign_in_with_link(
    client: TestClient, gateway: _GatewayRecorder
) -> None:
    gateway.result = GatewayMcpError(
        "sign_in_required",
        f"Not signed in to {LAKEDRAW}. Sign in at {SIGN_IN_URL}",
        sign_in_url=SIGN_IN_URL,
    )

    response = client.post(f"{BASE}/test", json={"service_name": LAKEDRAW})

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == STATUS_FIELDS
    assert body["state"] == "sign_in_required"
    assert body["sign_in_url"] == SIGN_IN_URL
    assert body["tools"] == []
    assert len(gateway.list_calls) == 1


def test_connection_test_ready_lists_tools(client: TestClient, gateway: _GatewayRecorder) -> None:
    """An unregistered service can be tested: the Add form tests before saving."""
    gateway.result = [
        GatewayToolSpec(
            name="web_search",
            description="Search the web.",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        ),
        GatewayToolSpec(name="fetch_page", description="", input_schema={"type": "object"}),
    ]

    response = client.post(f"{BASE}/test", json={"service_name": " System.AI.Web_Search "})

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == STATUS_FIELDS
    assert body["state"] == "ready"
    assert body["sign_in_url"] is None
    assert body["tools"] == [
        {"name": "web_search", "description": "Search the web."},
        {"name": "fetch_page", "description": ""},
    ]
    assert [call["service_name"] for call in gateway.init_calls] == ["system.ai.web_search"]
    assert len(gateway.list_calls) == 1


def test_connection_test_lists_every_tool_whatever_the_stored_allowlist(
    client: TestClient, session_factory: sessionmaker, gateway: _GatewayRecorder
) -> None:
    """The admin picks the allowlist from this list, so it is never filtered by it,
    and a disabled connection is still probed (never ``not_registered``)."""
    _seed(session_factory, tool_allowlist=["draw"], enabled=False)
    gateway.result = [
        GatewayToolSpec(name="draw", description="Draw.", input_schema={"type": "object"}),
        GatewayToolSpec(name="render", description="Render.", input_schema={"type": "object"}),
    ]

    response = client.post(f"{BASE}/test", json={"service_name": LAKEDRAW})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "ready"
    assert body["tools"] == [
        {"name": "draw", "description": "Draw."},
        {"name": "render", "description": "Render."},
    ]


def test_connection_test_probes_as_the_calling_admin(
    client: TestClient, gateway: _GatewayRecorder
) -> None:
    gateway.result = []

    first = client.post(f"{BASE}/test", json={"service_name": "Main.Tellr_MCP.LakeDraw"})

    # A different admin, with an opaque (non-JWT) token: scopes are unknown.
    set_current_user(SECOND_ADMIN)
    set_user_client(_user_client(SECOND_HOST, "dapi-opaque-token"))
    second = client.post(f"{BASE}/test", json={"service_name": LAKEDRAW})

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["state"] == "ready"
    assert [
        {key: call.get(key) for key in ("host", "token", "service_name", "token_scopes")}
        for call in gateway.init_calls
    ] == [
        {
            "host": HOST,
            "token": ADMIN_TOKEN,
            "service_name": LAKEDRAW,
            "token_scopes": ADMIN_SCOPES,
        },
        {
            "host": SECOND_HOST,
            "token": "dapi-opaque-token",
            "service_name": LAKEDRAW,
            "token_scopes": None,
        },
    ]
    assert len(gateway.list_calls) == 2


@pytest.mark.parametrize(
    ("kind", "state"),
    [
        ("access_denied", "access_denied"),
        ("missing_scope", "missing_scope"),
        ("not_found", "not_found"),
        ("unavailable", "unavailable"),
        ("timeout", "unavailable"),
    ],
)
def test_connection_test_maps_each_failure_to_its_state(
    client: TestClient, gateway: _GatewayRecorder, kind: str, state: str
) -> None:
    gateway.result = GatewayMcpError(kind, f"{kind}: what the service said")

    response = client.post(f"{BASE}/test", json={"service_name": LAKEDRAW})

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == STATUS_FIELDS
    assert body["state"] == state
    assert body["sign_in_url"] is None
    assert body["tools"] == []


@pytest.mark.parametrize("bad_name", ["a.b", "a.b/c.d", "../x.y.z", ""])
def test_connection_test_rejects_a_bad_service_name_422_without_probing(
    client: TestClient, gateway: _GatewayRecorder, bad_name: str
) -> None:
    """The name becomes a URL path segment called with the admin's token."""
    gateway.result = []

    response = client.post(f"{BASE}/test", json={"service_name": bad_name})

    assert response.status_code == 422, response.text
    assert gateway.init_calls == []
    assert gateway.list_calls == []


def test_status_schema_states_are_the_seven_declared() -> None:
    """Task 3's user status route returns ``not_registered`` through this schema."""
    assert set(get_args(GatewayStatusOut.model_fields["state"].annotation)) == {
        "ready",
        "sign_in_required",
        "missing_scope",
        "access_denied",
        "not_found",
        "unavailable",
        "not_registered",
    }


# ---------------------------------------------------------------------------
# status_message (shared with Task 3) — the exact copy from the spec
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "detail", "sign_in_url", "expected"),
    [
        (
            "sign_in_required",
            "not signed in",
            SIGN_IN_URL,
            f"To use LakeDraw, sign in here: {SIGN_IN_URL} — then ask again.",
        ),
        (
            "access_denied",
            "403 Forbidden",
            None,
            f"You don't have access to LakeDraw ({LAKEDRAW}). Ask an admin to grant EXECUTE on it.",
        ),
        (
            "not_found",
            "Session terminated",
            None,
            f"LakeDraw ({LAKEDRAW}) was not found on this workspace. "
            "Ask an admin to check the connection.",
        ),
        ("ready", None, None, None),
    ],
    ids=["sign_in_required", "access_denied", "not_found", "ready"],
)
def test_status_message_uses_the_exact_copy(
    state: str, detail: str | None, sign_in_url: str | None, expected: str | None
) -> None:
    assert (
        registry.status_message(
            state,
            display_name="LakeDraw",
            service_name=LAKEDRAW,
            detail=detail,
            sign_in_url=sign_in_url,
        )
        == expected
    )


# ---------------------------------------------------------------------------
# The registry service (consumed by Tasks 3 and 6)
# ---------------------------------------------------------------------------


def _create(db: Session, service_name: str, **overrides: Any) -> registry.GatewayConnection:
    kwargs: dict[str, Any] = {
        "service_name": service_name,
        "display_name": "LakeDraw",
        "description": None,
        "agent": "architect",
        "instructions": None,
        "tool_allowlist": None,
        "enabled": True,
        "user": ADMIN,
    }
    kwargs.update(overrides)
    return registry.create_connection(db, **kwargs)


def test_registry_returns_frozen_connections_with_tuple_allowlists(
    session_factory: sessionmaker,
) -> None:
    with session_factory() as db:
        created = _create(
            db,
            "main.a.svc",
            display_name="A",
            description="The A service.",
            agent="data_analyst",
            instructions="Prefer A.",
            tool_allowlist=["t1", "t2"],
        )
        db.commit()

        assert isinstance(created, registry.GatewayConnection)
        assert isinstance(created.id, int)
        assert (
            created.service_name,
            created.display_name,
            created.description,
            created.agent,
            created.instructions,
            created.tool_allowlist,
            created.enabled,
            created.created_by,
            created.updated_by,
        ) == (
            "main.a.svc",
            "A",
            "The A service.",
            "data_analyst",
            "Prefer A.",
            ("t1", "t2"),
            True,
            ADMIN,
            ADMIN,
        )
        assert created.created_at is not None
        assert created.updated_at is not None
        with pytest.raises(dataclasses.FrozenInstanceError):
            created.enabled = False  # type: ignore[misc]

        fetched = registry.get_by_service(db, "main.a.svc")
        untimed = lambda c: {  # noqa: E731
            k: v for k, v in dataclasses.asdict(c).items() if k not in ("created_at", "updated_at")
        }
        assert fetched is not None
        assert untimed(fetched) == untimed(created)
        assert [c.service_name for c in registry.list_connections(db)] == ["main.a.svc"]


def test_registry_enabled_by_service_returns_only_enabled_requested_rows(
    session_factory: sessionmaker,
) -> None:
    with session_factory() as db:
        _create(db, "main.a.on", display_name="On", tool_allowlist=["x"])
        db.commit()
        _create(db, "main.b.off", display_name="Off", enabled=False)
        db.commit()
        _create(db, "main.c.unasked", display_name="Unasked")
        db.commit()

        found = registry.enabled_by_service(db, ["main.a.on", "main.b.off", "main.z.absent"])

        assert set(found) == {"main.a.on"}
        assert found["main.a.on"].display_name == "On"
        assert found["main.a.on"].tool_allowlist == ("x",)
        assert registry.enabled_by_service(db, []) == {}

        disabled = registry.get_by_service(db, "main.b.off")
        assert disabled is not None
        assert disabled.enabled is False
        assert disabled.tool_allowlist is None
        assert registry.get_by_service(db, "main.z.absent") is None
        assert {c.service_name for c in registry.list_connections(db)} == {
            "main.a.on",
            "main.b.off",
            "main.c.unasked",
        }


def test_registry_raises_its_typed_errors(session_factory: sessionmaker) -> None:
    with session_factory() as db:
        original = _create(db, "main.a.svc", display_name="Original")
        db.commit()

        with pytest.raises(registry.DuplicateServiceError):
            _create(db, "main.a.svc", display_name="Copy")
        db.rollback()

        missing = original.id + 1000
        with pytest.raises(registry.ConnectionNotFoundError):
            registry.update_connection(
                db,
                missing,
                display_name="X",
                description=None,
                agent="architect",
                instructions=None,
                tool_allowlist=None,
                enabled=True,
                user=ADMIN,
            )
        with pytest.raises(registry.ConnectionNotFoundError):
            registry.delete_connection(db, missing)

        remaining = registry.list_connections(db)
        assert [(c.service_name, c.display_name) for c in remaining] == [("main.a.svc", "Original")]
