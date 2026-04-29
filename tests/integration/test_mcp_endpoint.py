"""End-to-end integration tests for the /mcp endpoint.

Uses FastAPI TestClient against the full app. LLM generation, the
Databricks identity client, and the job queue are mocked; the MCP
tool handlers themselves, FastMCP request routing, JSON-RPC envelope
handling, and ``/mcp`` mount wiring are all exercised for real.

Two SDK-specific gotchas to keep in mind when reading these tests:

1. ``FastMCP.streamable_http_app()`` returns a Starlette sub-app whose
   lifespan initializes a task group required by ``handle_request``.
   Starlette does NOT run mounted sub-app lifespans, so the parent
   FastAPI lifespan in ``src/api/main.py`` enters the session manager
   via ``AsyncExitStack`` — but only when ``PYTEST_CURRENT_TEST`` is
   unset (since ``StreamableHTTPSessionManager.run()`` can only be
   entered once per instance, and unit-test suites repeatedly
   instantiate the lifespan). Integration tests therefore pop the
   env var during TestClient setup so the real guarded code runs,
   and patch ``init_db`` + migration helpers to no-ops so no DB is
   touched during lifespan.

2. ``POST /mcp`` returns a 307 redirect to ``/mcp/``. Hitting the
   trailing-slash path directly avoids TestClient's redirect handling
   (which may or may not follow redirects automatically depending on
   the httpx version).
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# Trailing slash: the FastMCP streamable-HTTP transport internally
# mounts its route at "/", and main.py mounts that sub-app at "/mcp".
# External POST to "/mcp" returns a 307 to "/mcp/"; going straight to
# the slashed form bypasses that round trip.
MCP_PATH = "/mcp/"


def _jsonrpc(method: str, params: dict | None = None, rid: int = 1) -> dict:
    """Build a minimal JSON-RPC 2.0 request body for the MCP transport."""
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        body["params"] = params
    return body


def _init_payload() -> dict:
    """Standard MCP ``initialize`` call payload."""
    return _jsonrpc(
        "initialize",
        {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "integration-test", "version": "0.0.0"},
        },
    )


def _mcp_headers(session_id: str | None = None, with_auth: bool = True) -> dict:
    """Build the header set FastMCP's streamable-HTTP transport requires.

    The transport demands ``Accept`` include both ``application/json``
    and ``text/event-stream`` so the server can choose its response
    encoding. tellr runs FastMCP in stateless mode (see
    ``src/api/mcp_server.py``), so the server never issues an
    ``mcp-session-id`` header; callers may send one and the server
    ignores it. We keep the ``session_id`` parameter for compatibility
    with tests that still want to pass a value.

    ``Host`` is set to a value that matches FastMCP's DNS rebinding
    allowed-list wildcards. FastMCP auto-enables protection when its
    ``host`` is ``127.0.0.1``/``localhost``/``::1`` (the default for
    our ``FastMCP("tellr")`` instance) and allows hosts matching
    ``["127.0.0.1:*", "localhost:*", "[::1]:*"]``. The wildcard match
    requires a port component (see ``TransportSecurityMiddleware.
    _validate_host``), so we send a dummy port. TestClient defaults to
    ``testserver`` which FastMCP rejects with HTTP 421.
    """
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Host": "127.0.0.1:8000",
    }
    if with_auth:
        headers["Authorization"] = "Bearer fake-tok"
    if session_id is not None:
        headers["mcp-session-id"] = session_id
    return headers


def _decode_mcp_response(resp) -> dict:
    """Decode a FastMCP streamable-HTTP response to a JSON-RPC envelope.

    The streamable transport picks its response encoding based on the
    ``Accept`` header: when the client accepts both ``application/json``
    and ``text/event-stream`` (as we do), FastMCP defaults to SSE. An
    SSE frame for a single JSON-RPC reply looks like:

        event: message
        data: {"jsonrpc":"2.0","id":1,"result":{...}}

    with a trailing blank line. We extract the first ``data:`` line and
    decode it as JSON. When the server instead chose raw JSON (e.g., for
    a 202 Accepted notification ack) we pass that through unchanged.
    """
    ct = resp.headers.get("content-type", "")
    body = resp.text
    if "text/event-stream" in ct:
        for line in body.splitlines():
            if line.startswith("data:"):
                return json.loads(line[len("data:"):].strip())
        # Malformed SSE (no data line) — surface as empty envelope so
        # downstream assertions produce a clear failure.
        return {}
    # Plain JSON response.
    if not body.strip():
        return {}
    return json.loads(body)


def _parse_tool_result(body: dict) -> dict:
    """Extract the tool's structured return value from a JSON-RPC response.

    FastMCP serializes tools with a ``-> dict`` return annotation into two
    places on the CallToolResult: ``structuredContent`` (the dict verbatim,
    per the output schema) and ``content`` (a list whose first entry is a
    ``TextContent`` block containing the JSON-encoded dict). Prefer
    ``structuredContent`` when present so the test doesn't depend on the
    text serialization choice; fall back to decoding ``content[0].text``.
    """
    result = body.get("result") or {}
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    content = result.get("content") or []
    if content:
        text = content[0].get("text", "{}")
        return json.loads(text) if isinstance(text, str) else text
    return {}


def _is_tool_error(body: dict) -> bool:
    """Return True if the JSON-RPC response represents a tool-level error.

    Accepts both shapes FastMCP may produce: a JSON-RPC protocol error
    (``error`` at top level) and a tool-call result with ``isError: true``.
    """
    if "error" in body:
        return True
    result = body.get("result") or {}
    return bool(result.get("isError"))


def _initialize_session(client: TestClient) -> str | None:
    """Run the MCP initialize handshake and return the session id (or None).

    Also sends the ``notifications/initialized`` callback. FastMCP runs
    in stateless mode here so no ``mcp-session-id`` is issued and the
    notification is effectively a no-op, but we keep the sequence to
    exercise the same shape of handshake real clients send.
    """
    init = client.post(MCP_PATH, headers=_mcp_headers(), json=_init_payload())
    assert init.status_code == 200, (
        f"initialize returned {init.status_code}: {init.text!r}"
    )
    session_id = init.headers.get("mcp-session-id")

    client.post(
        MCP_PATH,
        headers=_mcp_headers(session_id=session_id),
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    return session_id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_identity_client():
    """Patch the MCP auth's ``get_or_create_user_client`` to a fake client.

    ``mcp_auth.extract_mcp_identity`` calls ``get_or_create_user_client(token)``
    then ``client.current_user.me()`` to resolve the caller's identity from
    the Bearer token. For integration tests we short-circuit both so the
    auth layer returns a stable ``MCPIdentity`` without any real Databricks
    API call.
    """
    client = MagicMock()
    me = MagicMock()
    me.id = "user-alice"
    me.user_name = "alice@example.com"
    client.current_user.me.return_value = me

    with patch(
        "src.api.mcp_auth.get_or_create_user_client",
        return_value=client,
    ):
        yield client


@contextmanager
def _pytest_env_var_context():
    """Temporarily unset ``PYTEST_CURRENT_TEST`` and restore on exit.

    ``src/api/main.py`` gates the FastMCP session-manager startup on
    ``PYTEST_CURRENT_TEST`` being unset (pytest sets it for every test).
    We pop it just for the window where TestClient runs the FastAPI
    lifespan, so the session manager actually starts and later tool
    calls have the task group they need. Restore immediately — other
    tests and conftest fixtures may rely on pytest-provided state.
    """
    saved = os.environ.pop("PYTEST_CURRENT_TEST", None)
    try:
        yield
    finally:
        if saved is not None and "PYTEST_CURRENT_TEST" not in os.environ:
            os.environ["PYTEST_CURRENT_TEST"] = saved


@pytest.fixture(scope="module")
def client():
    """TestClient that triggers the full FastAPI lifespan, reused across tests.

    MUST be module-scoped. FastMCP's ``StreamableHTTPSessionManager.run()``
    has a hard ``_has_started`` flag that prevents re-entry; since
    ``src.api.mcp_server.mcp`` is a module-level singleton, once any
    test's lifespan starts its task group there's no way to start it
    again within the same process. A per-test ``TestClient`` would
    therefore raise ``RuntimeError: .run() can only be called once``
    on the second test. Module scope means the lifespan runs once,
    all tests in this file share the running session manager, and
    teardown happens when pytest exits this module.

    Three things have to be true at lifespan-enter for MCP calls to
    work end-to-end in integration tests:

    1. The ``PYTEST_CURRENT_TEST`` guard in ``main.lifespan`` must
       evaluate to None so the session manager context is entered.
    2. ``init_db``/``get_session_local``/migration helpers must be
       no-ops (with the env var popped, main.py's ``is_pytest`` check
       also flips false and it would try to talk to a real Postgres).
    3. ``TestClient`` must be used as a context manager (``with ...``)
       so the lifespan runs at all — bare ``TestClient(app)`` skips
       it and tool calls return HTTP 500 from the un-initialized
       session manager.
    """
    from src.api.main import app

    # Patch namespaces MUST match main.py's imports: ``init_db`` and
    # ``get_session_local`` are imported at module load
    # (``from src.core.database import init_db, get_session_local, ...``),
    # so both are bound into ``src.api.main``'s namespace. Same for
    # the migration helpers ``migrate_profiles`` and ``backfill_sessions``
    # which come from ``src.core.migrate_profiles_to_agent_config``.
    #
    # Note: ``migrate_profiles(get_session_local())`` evaluates its
    # argument first, so patching only ``migrate_profiles`` still lets
    # ``get_session_local()`` call into the real DB engine. We patch
    # both to keep the lifespan DB-free.
    with patch("src.api.main.init_db"), \
         patch("src.api.main.get_session_local", return_value=MagicMock()), \
         patch("src.api.main.migrate_profiles", return_value=0), \
         patch("src.api.main.backfill_sessions", return_value=0), \
         _pytest_env_var_context(), \
         TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_initialize_succeeds(client, mock_identity_client):
    """The MCP initialize handshake returns a 200 JSON-RPC envelope.

    tellr runs FastMCP in stateless mode so no ``mcp-session-id`` is
    emitted; we just verify the endpoint is wired up and capabilities
    negotiation works.
    """
    resp = client.post(MCP_PATH, headers=_mcp_headers(), json=_init_payload())
    assert resp.status_code == 200, resp.text
    body = _decode_mcp_response(resp)
    assert "result" in body, f"unexpected envelope: {body!r}"


def test_tools_list_returns_four_tools(client, mock_identity_client):
    """``tools/list`` enumerates exactly the four tellr MCP tools."""
    session_id = _initialize_session(client)

    resp = client.post(
        MCP_PATH,
        headers=_mcp_headers(session_id=session_id),
        json=_jsonrpc("tools/list"),
    )
    assert resp.status_code == 200, resp.text
    body = _decode_mcp_response(resp)

    # FastMCP returns a JSON-RPC envelope with ``result.tools``; the
    # transport may wrap it in SSE (see ``_decode_mcp_response``).
    assert "result" in body, f"unexpected envelope: {body!r}"
    tool_names = {t["name"] for t in body["result"]["tools"]}
    assert tool_names == {
        "create_deck",
        "get_deck_status",
        "edit_deck",
        "get_deck",
    }, f"unexpected tool set: {tool_names}"


def test_create_deck_returns_pending(client, mock_identity_client):
    """Calling ``create_deck`` end-to-end returns a pending job envelope.

    The MCP tool handler, mcp_auth_scope, and FastMCP's JSON-RPC routing
    all run for real. The session manager's ``create_session`` and the
    job-queue ``enqueue_create_job`` are the only pieces stubbed, so a
    success return of ``{session_id, request_id, status: pending}``
    exercises the whole tool pipeline without touching Databricks or
    the LLM.
    """
    session_id = _initialize_session(client)

    async def _fake_enqueue(**kwargs):
        return "req-int-1"

    # ``get_session_manager`` returns a module-level singleton; patching
    # the name in ``mcp_server`` intercepts the call site inside
    # ``_create_deck_impl``. ``enqueue_create_job`` is an async helper;
    # we patch with ``side_effect`` so the coroutine is awaited correctly.
    with patch("src.api.mcp_server.get_session_manager") as get_sm, \
         patch(
             "src.api.mcp_server.enqueue_create_job",
             side_effect=_fake_enqueue,
         ):
        sm = MagicMock()
        sm.create_session.return_value = {"session_id": "sess-int-1"}
        get_sm.return_value = sm

        resp = client.post(
            MCP_PATH,
            headers=_mcp_headers(session_id=session_id),
            json=_jsonrpc(
                "tools/call",
                {
                    "name": "create_deck",
                    "arguments": {"prompt": "integration test deck"},
                },
            ),
        )

    assert resp.status_code == 200, resp.text
    body = _decode_mcp_response(resp)
    assert not _is_tool_error(body), f"tool reported error: {body!r}"
    parsed = _parse_tool_result(body)
    assert parsed["session_id"] == "sess-int-1"
    assert parsed["request_id"] == "req-int-1"
    assert parsed["status"] == "pending"


def test_rejects_request_without_auth(client):
    """A ``tools/call`` without any credential header is rejected.

    ``initialize`` itself doesn't invoke the identity resolver (no tool
    handler runs), so it may succeed. The meaningful check is on a
    follow-up ``tools/call``: ``mcp_auth_scope`` raises ``MCPAuthError``
    when neither ``x-forwarded-access-token`` nor ``Authorization``
    headers are present, and the tool wraps that as ``MCPToolError``,
    which FastMCP surfaces as a tool-level error (isError: true) or a
    JSON-RPC protocol error depending on the failure path. Accept both
    shapes.
    """
    # Step 1: initialize without auth. Expected to succeed (no tool
    # handler runs) but we handle the case where it doesn't.
    init = client.post(
        MCP_PATH,
        headers=_mcp_headers(with_auth=False),
        json=_init_payload(),
    )
    if init.status_code in (401, 403):
        return  # transport rejected unauthenticated init — acceptable
    if init.status_code == 200 and "error" in _decode_mcp_response(init):
        return  # initialize returned JSON-RPC error — acceptable
    assert init.status_code == 200, (
        f"unexpected initialize status: {init.status_code} {init.text!r}"
    )

    session_id = init.headers.get("mcp-session-id")

    # Send the initialized notification to mimic a real client handshake
    # shape (still no auth header). In stateless mode the server ignores
    # the session_id; we pass it through if one happened to be issued.
    client.post(
        MCP_PATH,
        headers=_mcp_headers(session_id=session_id, with_auth=False),
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )

    # Step 2: the actual test — a tool call without credentials must fail.
    resp = client.post(
        MCP_PATH,
        headers=_mcp_headers(session_id=session_id, with_auth=False),
        json=_jsonrpc(
            "tools/call",
            {"name": "create_deck", "arguments": {"prompt": "x"}},
        ),
    )

    body = _decode_mcp_response(resp)
    assert _is_tool_error(body), (
        f"expected auth failure to surface as tool error; got: {body!r}"
    )

    # If it came through as a tool-level error, the message should
    # reference authentication/credentials — useful signal that the
    # error came from mcp_auth_scope and not from some unrelated bug.
    result = body.get("result") or {}
    if result.get("isError"):
        content = result.get("content") or []
        text = content[0].get("text", "") if content else ""
        assert (
            "auth" in text.lower() or "credentials" in text.lower()
        ), f"tool-error content didn't mention auth: {text!r}"


def test_permission_denied_on_other_users_deck(client, mock_identity_client):
    """``get_deck`` on a deck the caller can't view surfaces a tool error.

    The permission facade ``src.api.mcp_server.permission_service`` is
    the single gate the MCP tool consults before returning deck data.
    Patching ``can_view_deck`` to False bypasses the DB-backed
    ``PermissionService`` and lets us test the MCP-side denial path
    without seeding a real deck. The tool handler raises ``MCPToolError``
    which FastMCP renders as a tool-level error result.
    """
    session_id = _initialize_session(client)

    with patch(
        "src.api.mcp_server.permission_service.can_view_deck",
        return_value=False,
    ):
        resp = client.post(
            MCP_PATH,
            headers=_mcp_headers(session_id=session_id),
            json=_jsonrpc(
                "tools/call",
                {
                    "name": "get_deck",
                    "arguments": {"session_id": "someone-elses-deck"},
                },
            ),
        )

    assert resp.status_code == 200, resp.text
    body = _decode_mcp_response(resp)
    assert _is_tool_error(body), (
        f"expected permission denial to surface as tool error; got: {body!r}"
    )

    # Confirm the error message reflects the permission/not-found wording
    # the handler produces, not some unrelated crash.
    result = body.get("result") or {}
    content = result.get("content") or []
    text = content[0].get("text", "") if content else ""
    lowered = text.lower()
    assert (
        "permission" in lowered or "not found" in lowered
    ), f"denial error didn't mention permission/not-found: {text!r}"


def test_mcp_endpoint_accepts_both_slash_forms(client, mock_identity_client):
    """Regression guard: POST /mcp and POST /mcp/ behave identically.

    The SPA catch-all (``@app.get("/{full_path:path}")`` added by
    ``_mount_frontend`` in production) used to make ``POST /mcp`` return
    405 with ``allow: GET``, since Starlette's ``Mount`` cannot tell the
    outer router which methods FastMCP accepts. In tests
    ``IS_PRODUCTION`` is false so ``_mount_frontend`` doesn't run and
    Mount itself returns a 307 redirect for the bare path. The
    ``normalize_mcp_path`` middleware in ``main.py`` rewrites
    ``/mcp -> /mcp/`` in the ASGI scope so both forms reach the FastMCP
    sub-app's POST handler in a single round-trip.

    ``follow_redirects=False`` is critical: without it, ``TestClient``
    would silently follow a 307 from ``/mcp`` to ``/mcp/`` and the test
    would pass even if the middleware regressed.
    """
    # Run the standard MCP handshake against the canonical slashed path
    # first so any FastMCP-internal state (none today, since stateless)
    # mirrors what the existing tests do.
    _initialize_session(client)

    body = _jsonrpc("tools/list", rid=2)

    no_slash = client.post(
        "/mcp",
        headers=_mcp_headers(),
        json=body,
        follow_redirects=False,
    )
    with_slash = client.post(
        "/mcp/",
        headers=_mcp_headers(),
        json=body,
        follow_redirects=False,
    )

    assert no_slash.status_code == 200, (
        f"POST /mcp should return 200 after the middleware rewrite, "
        f"got {no_slash.status_code}: {no_slash.text!r}"
    )
    assert with_slash.status_code == 200, with_slash.text

    no_slash_body = _decode_mcp_response(no_slash)
    with_slash_body = _decode_mcp_response(with_slash)

    no_slash_tools = {
        t["name"] for t in no_slash_body["result"]["tools"]
    }
    with_slash_tools = {
        t["name"] for t in with_slash_body["result"]["tools"]
    }
    assert no_slash_tools == with_slash_tools, (
        f"tool sets differ between paths: "
        f"no_slash={no_slash_tools} with_slash={with_slash_tools}"
    )
    assert {
        "create_deck", "get_deck_status", "edit_deck", "get_deck",
    } <= no_slash_tools, f"unexpected tool set: {no_slash_tools}"
