"""Task 1: the shared MCP transport and the generic AI Gateway MCP client.

Modules under test:

- ``src/services/agent_tools/mcp_transport.py``: ``UserBearerAuth``,
  ``build_user_mcp_client`` and ``run_with_timeout``;
- ``src/services/agent_tools/gateway_mcp.py``: typed errors, error mapping, the
  client and ``probe_service``;
- ``src/domain/gateway_service_name.py``: ``validate_service_name`` (PLAN-CORRECTIONS
  C1), re-exported by ``gateway_mcp``;
- ``src/services/agent_tools/genie_one.py``: its surface is unchanged, and it now
  builds its client on the shared transport.

The Gateway responses are real ones recorded on tellr-dev, loaded from
``tests/fixtures/gateway_mcp/`` (``body_json`` is the response body, ``status`` the
HTTP status and ``headers`` the headers kept). A few error bodies are *derived*
from a recorded one, and each says how.

The exception shapes are those mcp 1.27 raises against a local server, measured
before these tests were written:

- an HTTP 401 (with ``UserBearerAuth``, so the body is read) is an
  ``ExceptionGroup`` holding an ``httpx.HTTPStatusError``;
- an HTTP 200 carrying a JSON-RPC error is ``McpError(code)`` two
  ``ExceptionGroup``s deep;
- an HTTP 404 is ``McpError(32600, "Session terminated")`` two groups deep, with no
  HTTP status anywhere.

Two kinds of test:

- **Unit tests** use the ``mcp_client_factory`` seam (T1.4) with a fake MCP client.
  The fake has only the async session methods. Its sync ``list_tools`` /
  ``call_tool`` wrappers carry databricks_mcp's ``_handle_mcp_errors``, which
  re-sends an ``initialize``, so the fake records and refuses them.
- **Real-stack tests** run the real ``databricks_mcp`` / ``mcp`` / ``httpx`` stack
  against ``_LocalGateway``, a server on 127.0.0.1. Nothing leaves the machine.
"""

from __future__ import annotations

import asyncio
import builtins
import dataclasses
import http.server
import inspect
import json
import subprocess
import sys
import threading
import time
import typing
from collections.abc import Callable
from pathlib import Path
from typing import Any

import databricks.sdk
import databricks_mcp
import httpx
import pytest
from databricks.sdk.errors import NotFound, PermissionDenied
from mcp.shared.exceptions import McpError
from mcp.types import CallToolResult, ErrorData, TextContent, Tool

from src.domain.gateway_service_name import (
    validate_service_name as domain_validate_service_name,
)
from src.services.agent_tools import genie_one
from src.services.agent_tools.gateway_mcp import (
    CALL_TIMEOUT_SECONDS,
    LIST_TIMEOUT_SECONDS,
    GatewayErrorKind,
    GatewayMcpClient,
    GatewayMcpError,
    GatewayProbe,
    GatewayToolSpec,
    gateway_service_url,
    map_gateway_error,
    probe_service,
    sign_in_url,
    validate_service_name,
)
from src.services.agent_tools.mcp_transport import (
    UserBearerAuth,
    build_user_mcp_client,
    run_with_timeout,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "gateway_mcp"

HOST = "https://h.example"
TOKEN = "user-token-from-get_user_client"

WEB_SEARCH = "system.ai.web_search"
GITHUB = "system.ai.github"
LAKEDRAW = "db_tellr_dev_workspace_catalog.tellr_mcp.lakedraw"
SERVICES_PREFIX = "/ai-gateway/mcp-services/"

#: The workspace the LakeDraw fixtures were recorded on. A link in a message is
#: trusted only on the client's own host, so tests that expect the recorded link
#: build their client on this host.
LAKEDRAW_HOST = "https://fevm-db-tellr-dev-workspace.cloud.databricks.com"
#: The recorded workspace id (the fixtures' ``x-databricks-org-id``).
LAKEDRAW_ORG_ID = "7474645249186749"
#: The sign-in link in the recorded LakeDraw message, without the "," after it.
LAKEDRAW_SIGN_IN_URL = (
    "https://fevm-db-tellr-dev-workspace.cloud.databricks.com/mcp-service-login"
    "?name=db_tellr_dev_workspace_catalog.tellr_mcp.lakedraw&o=7474645249186749"
)
#: The staging wording of a missing-scope refusal.
SCOPE_TEXT = "Provided OAuth token does not have required scopes: ai-gateway"
#: anyio's task-group message, as the measured groups carry it.
TASK_GROUP = "unhandled errors in a TaskGroup (1 sub-exception)"

# A Python 3.11 builtin; reached through builtins because ruff targets py39.
_Group = builtins.BaseExceptionGroup


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def _service_path(service: str) -> str:
    return f"{SERVICES_PREFIX}{service}"


def _lakedraw_message() -> str:
    return load("lakedraw_initialize_not_signed_in")["body_json"]["error"]["message"]


def _web_search_spec() -> GatewayToolSpec:
    """The recorded web_search tool, as a ``GatewayToolSpec`` (every field from the fixture)."""
    tool = load("web_search_tools_list")["body_json"]["result"]["tools"][0]
    return GatewayToolSpec(
        name=tool["name"], description=tool["description"], input_schema=tool["inputSchema"]
    )


# ---------------------------------------------------------------------------
# Exceptions shaped like the measured ones
# ---------------------------------------------------------------------------


def _in_groups(exc: BaseException, depth: int) -> BaseException:
    """*exc* wrapped in *depth* task-group exception groups, innermost first."""
    for _ in range(depth):
        exc = _Group(TASK_GROUP, [exc])
    return exc


def _http_error(
    status: int,
    body: str = "",
    *,
    headers: dict[str, str] | None = None,
    service: str = WEB_SEARCH,
) -> httpx.HTTPStatusError:
    """httpx's own error for a Gateway reply, raised by ``raise_for_status``, its body read."""
    request = httpx.Request("POST", f"{HOST}{_service_path(service)}")
    response = httpx.Response(status, content=body.encode(), headers=headers or {}, request=request)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        return exc
    raise AssertionError(f"HTTP {status} is not an error status")


def _lakedraw_not_signed_in_error() -> httpx.HTTPStatusError:
    """The recorded LakeDraw ``initialize``: HTTP 401, a JSON-RPC -32006 body, its headers."""
    recorded = load("lakedraw_initialize_not_signed_in")
    return _http_error(
        recorded["status"],
        json.dumps(recorded["body_json"]),
        headers=recorded["headers"],
        service=LAKEDRAW,
    )


def _github_rejection() -> BaseException:
    """The recorded github ``tools/list``: HTTP 200 + JSON-RPC -32006, as mcp raises it."""
    error = load("github_tools_list_rejected")["body_json"]["error"]
    return _in_groups(McpError(ErrorData(code=error["code"], message=error["message"])), 2)


def _session_terminated() -> BaseException:
    """What mcp 1.27 raises for an HTTP 404, two groups deep."""
    return _in_groups(McpError(ErrorData(code=32600, message="Session terminated")), 2)


def _chain(exc: BaseException) -> list[BaseException]:
    """*exc*, its causes and contexts, and every exception-group member."""
    out: list[BaseException] = []
    stack = [exc]
    seen: set[int] = set()
    while stack:
        cur = stack.pop()
        if id(cur) in seen:
            continue
        seen.add(id(cur))
        out.append(cur)
        stack.extend(e for e in (cur.__cause__, cur.__context__) if e is not None)
        if isinstance(cur, _Group):
            stack.extend(cur.exceptions)
    return out


# ---------------------------------------------------------------------------
# The fake MCP client behind the mcp_client_factory seam (T1.4)
# ---------------------------------------------------------------------------


class FakeMcpClient:
    """Stands in for what ``build_user_mcp_client`` returns.

    The async session methods answer from a script. Both can raise *raises*, and
    both can block on *block* (a ``threading.Event``, set by the test) to stand in
    for a hung call. The sync wrappers carry ``_handle_mcp_errors``, which the
    Gateway path must skip, so they record the call and raise.
    """

    def __init__(
        self,
        *,
        tools: list[Tool] | None = None,
        result: Any = None,
        raises: BaseException | None = None,
        block: threading.Event | None = None,
    ) -> None:
        self.tools = tools or []
        self.result = result
        self.raises = raises
        self.block = block
        self.calls: list[tuple[str, Any]] = []
        self.sync_wrapper_calls: list[str] = []

    def _script(self) -> None:
        if self.block is not None:
            self.block.wait(timeout=5)
        if self.raises is not None:
            raise self.raises

    async def _get_tools_async(self) -> list[Tool]:
        self._script()
        return list(self.tools)

    async def _call_tools_async(self, tool_name: str, arguments: dict[str, Any] | None = None):
        self.calls.append((tool_name, arguments))
        self._script()
        return self.result

    def list_tools(self, *args: Any, **kwargs: Any) -> Any:
        self.sync_wrapper_calls.append("list_tools")
        raise AssertionError("the sync list_tools wrapper (_handle_mcp_errors) was used")

    def call_tool(self, *args: Any, **kwargs: Any) -> Any:
        self.sync_wrapper_calls.append("call_tool")
        raise AssertionError("the sync call_tool wrapper (_handle_mcp_errors) was used")


class FakeFactory:
    """An ``mcp_client_factory``: records ``(host, token, service_path, thread)`` per build."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.calls: list[tuple[str, str, str, threading.Thread]] = []

    def __call__(self, host: str, token: str, service_path: str) -> Any:
        self.calls.append((host, token, service_path, threading.current_thread()))
        return self.client


def make_client(
    fake: FakeMcpClient,
    *,
    host: str = HOST,
    service_name: str = WEB_SEARCH,
    token_scopes: frozenset[str] | None = None,
) -> tuple[GatewayMcpClient, FakeFactory]:
    factory = FakeFactory(fake)
    client = GatewayMcpClient(
        host=host,
        token=TOKEN,
        service_name=service_name,
        token_scopes=token_scopes,
        mcp_client_factory=factory,
    )
    return client, factory


def _run(client: GatewayMcpClient, operation: str, **kwargs: Any) -> Any:
    if operation == "list_tools":
        return client.list_tools(**kwargs)
    return client.call_tool("web_search", {"query": "q"}, **kwargs)


OPERATIONS = ["list_tools", "call_tool"]


def _error_result(text: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], isError=True)


# ---------------------------------------------------------------------------
# A local Gateway for the real-stack tests
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class _SeenRequest:
    method: str
    path: str
    authorization: str | None
    rpc_method: str | None
    rpc_id: Any
    rpc_params: Any


_Reply = Callable[[_SeenRequest, "_LocalGateway"], tuple[int, dict[str, str], bytes]]


class _LocalGateway:
    """A local HTTP server standing in for the AI Gateway.

    The pattern is ``tests/unit/test_genie_one_client.py``'s ``_LocalGateway``. Here
    *reply* picks each answer (status, headers and body), so one server can play a
    whole MCP session. Each request's method, path, ``Authorization`` header and
    JSON-RPC method, id and params are recorded.
    """

    def __init__(self, reply: _Reply) -> None:
        self._reply = reply
        self.requests: list[_SeenRequest] = []

    def __enter__(self) -> _LocalGateway:
        gateway = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def _answer(self) -> None:
                raw = self.rfile.read(int(self.headers.get("content-length") or 0))
                try:
                    message = json.loads(raw) if raw else {}
                except ValueError:
                    message = {}
                if not isinstance(message, dict):
                    message = {}
                seen = _SeenRequest(
                    method=self.command,
                    path=self.path,
                    authorization=self.headers.get("Authorization"),
                    rpc_method=message.get("method"),
                    rpc_id=message.get("id"),
                    rpc_params=message.get("params"),
                )
                gateway.requests.append(seen)
                status, headers, body = gateway._reply(seen, gateway)
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST = do_DELETE = _answer  # noqa: N815

            def log_message(self, *args: Any) -> None:
                pass

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        ).start()
        self.host = f"http://127.0.0.1:{self._server.server_address[1]}"
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self._server.shutdown()
        self._server.server_close()

    def requests_to(self, path: str) -> list[_SeenRequest]:
        return [r for r in self.requests if r.path == path]

    def oauth_discovery_requests(self) -> list[_SeenRequest]:
        """Requests the stock OAuth provider makes after a 401 (RFC 9728 discovery)."""
        return [r for r in self.requests if r.path.startswith("/.well-known/oauth-")]


def _fixed(status: int, body: bytes, headers: dict[str, str]) -> _Reply:
    """Answer every request with one status, headers and body."""
    return lambda seen, gateway: (status, headers, body)


def _lakedraw_not_signed_in(seen: _SeenRequest, gateway: _LocalGateway) -> tuple:
    """The recorded LakeDraw 401 for every request.

    The ``WWW-Authenticate`` header is the recorded one, but its
    ``resource_metadata`` URL points at this server, so a stray OAuth discovery
    stays local.
    """
    recorded = load("lakedraw_initialize_not_signed_in")
    headers = {
        "content-type": "application/json",
        "www-authenticate": (
            f'Bearer resource_metadata="{gateway.host}/.well-known/oauth-protected-resource'
            f'{seen.path}"'
        ),
        "x-databricks-org-id": recorded["headers"]["x-databricks-org-id"],
    }
    return recorded["status"], headers, json.dumps(recorded["body_json"]).encode()


_INITIALIZE_RESULT = {
    "protocolVersion": "2025-06-18",
    "capabilities": {"tools": {}},
    "serverInfo": {"name": "local-gateway", "version": "0"},
}


def _jsonrpc(bodies: dict[str, dict[str, Any]]) -> _Reply:
    """Answer like a Gateway service: ``initialize``, then each method from a recorded body.

    The recorded body gets the request's id. Notifications get a 202. Paths outside
    the service prefix (the SDK's host-metadata fetch) get a 404. No
    ``Mcp-Session-Id`` is sent, as web_search sends none.
    """

    def reply(seen: _SeenRequest, gateway: _LocalGateway) -> tuple:
        if not seen.path.startswith(SERVICES_PREFIX):
            return 404, {"content-type": "text/plain"}, b"Not Found"
        if seen.rpc_id is None:
            return 202, {}, b""
        if seen.rpc_method == "initialize":
            message: dict[str, Any] = {
                "jsonrpc": "2.0",
                "id": seen.rpc_id,
                "result": _INITIALIZE_RESULT,
            }
        elif seen.rpc_method in bodies:
            message = {**bodies[seen.rpc_method], "id": seen.rpc_id}
        else:
            message = {
                "jsonrpc": "2.0",
                "id": seen.rpc_id,
                "error": {"code": -32601, "message": f"Method not found: {seen.rpc_method}"},
            }
        return 200, {"content-type": "application/json"}, json.dumps(message).encode()

    return reply


# ---------------------------------------------------------------------------
# validate_service_name (C1: it lives in src/domain/gateway_service_name.py)
# ---------------------------------------------------------------------------


def test_validate_service_name_normalises_and_rejects():
    assert validate_service_name(" Main.GTM_ai_tooling.LakeDraw ") == "main.gtm_ai_tooling.lakedraw"
    for bad in ("a.b", "a.b.c.d", "a.b/c.d", "a b.c.d"):
        with pytest.raises(ValueError):
            validate_service_name(bad)


@pytest.mark.parametrize(
    "name",
    [WEB_SEARCH, LAKEDRAW, "main.gtm-ai.lake-draw", "c1.s_2.svc-3"],
)
def test_validate_service_name_accepts_three_part_names_unchanged(name: str):
    assert validate_service_name(name) == name


@pytest.mark.parametrize(
    "name",
    ["", "   ", "a..c", ".b.c", "a.b.", "a.b.c;d", "a.b.c%2e", "a.b.c d", "a.b.cé"],
)
def test_validate_service_name_rejects_malformed_names(name: str):
    with pytest.raises(ValueError):
        validate_service_name(name)


def test_validate_service_name_lives_in_domain_and_is_re_exported():
    assert validate_service_name is domain_validate_service_name


def test_service_name_module_imports_nothing_from_services_or_api():
    """C1: the schema modules import it, so importing it must not pull in src.services."""
    code = (
        "import sys\n"
        "import src.domain.gateway_service_name\n"
        "bad = sorted(n for n in sys.modules\n"
        "             if n.split('.')[:2] in (['src', 'services'], ['src', 'api']))\n"
        "print(bad)\n"
        "raise SystemExit(1 if bad else 0)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


# ---------------------------------------------------------------------------
# URLs, constants and the typed error
# ---------------------------------------------------------------------------


def test_gateway_service_url_is_the_ai_gateway_mcp_services_path():
    assert (
        gateway_service_url("https://h.example", WEB_SEARCH)
        == "https://h.example/ai-gateway/mcp-services/system.ai.web_search"
    )


def test_sign_in_url_adds_workspace_id_when_known():
    assert (
        sign_in_url("https://h", "a.b.c", workspace_id="42")
        == "https://h/mcp-service-login?name=a.b.c&o=42"
    )
    assert sign_in_url("https://h", "a.b.c") == "https://h/mcp-service-login?name=a.b.c"


def test_sign_in_url_prefers_the_url_in_the_message():
    # The URL in the message (on the client's host) wins over a built one, even when
    # the workspace id is known.
    assert (
        sign_in_url(LAKEDRAW_HOST, LAKEDRAW, message=_lakedraw_message(), workspace_id="42")
        == LAKEDRAW_SIGN_IN_URL
    )
    # A message with no URL leaves the built one.
    assert (
        sign_in_url("https://h", "a.b.c", message="You're not signed in.", workspace_id="42")
        == "https://h/mcp-service-login?name=a.b.c&o=42"
    )


@pytest.mark.parametrize("tail", [",", ".", ";", ")", ").", "),"])
def test_sign_in_url_strips_trailing_punctuation_from_the_message_url(tail: str):
    url = "https://w.example/mcp-service-login?name=a.b.c&o=7"
    message = f"Sign in at {url}{tail} then retry your request."

    assert sign_in_url("https://w.example", "a.b.c", message=message) == url


#: Links that are not on LAKEDRAW_HOST, each standing in for one a service could put
#: in its own text. Only the scheme and authority decide, so look-alikes count too.
_FOREIGN_SIGN_IN_URLS = {
    "other_host": f"https://evil.example/mcp-service-login?name={LAKEDRAW}&o=1",
    "workspace_host_as_prefix": (
        f"https://fevm-db-tellr-dev-workspace.cloud.databricks.com.evil.example"
        f"/mcp-service-login?name={LAKEDRAW}&o=1"
    ),
    "workspace_host_as_userinfo": (
        f"https://fevm-db-tellr-dev-workspace.cloud.databricks.com@evil.example"
        f"/mcp-service-login?name={LAKEDRAW}&o=1"
    ),
    "other_port": (
        f"https://fevm-db-tellr-dev-workspace.cloud.databricks.com:8443"
        f"/mcp-service-login?name={LAKEDRAW}&o=1"
    ),
}


def _lakedraw_message_linking(url: str) -> str:
    """The recorded LakeDraw message, with its sign-in link swapped for *url*."""
    message = _lakedraw_message().replace(LAKEDRAW_SIGN_IN_URL, url)
    # *url* is the message's one and only link.
    assert url in message and message.count("mcp-service-login") == 1
    return message


def _sign_in_url_via(
    path: str,
    message: str,
    *,
    host: str = LAKEDRAW_HOST,
    headers: dict[str, str] | None = None,
) -> str | None:
    """The sign-in link produced for *message* on a client of *host*, along one *path*.

    *headers* are the 401's (default: content-type only, so no workspace id is known).
    """
    if path == "sign_in_url":
        return sign_in_url(host, LAKEDRAW, message=message)
    if path == "jsonrpc_32006_in_401":
        body = load("lakedraw_initialize_not_signed_in")["body_json"]
        body = {**body, "error": {**body["error"], "message": message}}
        reply_headers = headers or {"content-type": "application/json"}
        exc = _in_groups(
            _http_error(401, json.dumps(body), headers=reply_headers, service=LAKEDRAW), 1
        )
        return map_gateway_error(
            exc, host=host, service_name=LAKEDRAW, lacks_gateway_scope=False
        ).sign_in_url
    if path == "jsonrpc_32006_in_200":
        exc = _in_groups(McpError(ErrorData(code=-32006, message=message)), 2)
        return map_gateway_error(
            exc, host=host, service_name=LAKEDRAW, lacks_gateway_scope=False
        ).sign_in_url
    assert path == "is_error_result"
    client, _ = make_client(
        FakeMcpClient(result=_error_result(message)), host=host, service_name=LAKEDRAW
    )
    with pytest.raises(GatewayMcpError) as info:
        client.call_tool("create_diagram", {})
    assert info.value.kind == "sign_in_required"
    return info.value.sign_in_url


_SIGN_IN_PATHS = ["sign_in_url", "jsonrpc_32006_in_401", "jsonrpc_32006_in_200", "is_error_result"]


@pytest.mark.parametrize("path", _SIGN_IN_PATHS)
@pytest.mark.parametrize(
    "foreign_url", list(_FOREIGN_SIGN_IN_URLS.values()), ids=list(_FOREIGN_SIGN_IN_URLS)
)
def test_sign_in_url_from_foreign_host_is_replaced_by_built_link(path: str, foreign_url: str):
    """Ruling on I1: a message can come from the service behind the Gateway, and the
    link is shown to the user as Tellr's own sign-in link. So a link that is not on
    the client's host is ignored, and the link is built on the client's host."""
    assert _sign_in_url_via(path, _lakedraw_message_linking(foreign_url)) == (
        f"{LAKEDRAW_HOST}/mcp-service-login?name={LAKEDRAW}"
    )


def test_a_foreign_link_never_lends_its_workspace_id_to_the_built_one():
    """The built link's ``&o=`` is the known workspace id, never the foreign link's."""
    message = _lakedraw_message_linking(_FOREIGN_SIGN_IN_URLS["other_host"])

    assert sign_in_url(LAKEDRAW_HOST, LAKEDRAW, message=message, workspace_id="42") == (
        f"{LAKEDRAW_HOST}/mcp-service-login?name={LAKEDRAW}&o=42"
    )
    # Through a 401 carrying the recorded headers: the id is the header's.
    recorded_headers = load("lakedraw_initialize_not_signed_in")["headers"]
    assert _sign_in_url_via("jsonrpc_32006_in_401", message, headers=recorded_headers) == (
        f"{LAKEDRAW_HOST}/mcp-service-login?name={LAKEDRAW}&o={LAKEDRAW_ORG_ID}"
    )


@pytest.mark.parametrize("path", _SIGN_IN_PATHS)
@pytest.mark.parametrize(
    ("host", "message_url"),
    [
        ("https://FEVM-DB-Tellr-Dev-Workspace.cloud.databricks.com", LAKEDRAW_SIGN_IN_URL),
        (f"{LAKEDRAW_HOST}/", LAKEDRAW_SIGN_IN_URL),
        (
            LAKEDRAW_HOST,
            LAKEDRAW_SIGN_IN_URL.replace(
                "fevm-db-tellr-dev-workspace.cloud", "FEVM-DB-TELLR-DEV-WORKSPACE.Cloud"
            ),
        ),
    ],
    ids=["host_in_other_case", "host_with_trailing_slash", "link_in_other_case"],
)
def test_sign_in_url_on_the_same_host_in_another_case_is_kept(
    path: str, host: str, message_url: str
):
    """Hosts compare case-insensitively, ignoring a trailing "/" on the client's host.
    The kept link is the message's own, character for character."""
    assert message_url.startswith("https://")

    assert _sign_in_url_via(path, _lakedraw_message_linking(message_url), host=host) == (
        message_url
    )


def test_timeouts_are_thirty_seconds_to_list_and_ninety_to_call():
    assert LIST_TIMEOUT_SECONDS == 30
    assert CALL_TIMEOUT_SECONDS == 90
    list_default = inspect.signature(GatewayMcpClient.list_tools).parameters["timeout_seconds"]
    call_default = inspect.signature(GatewayMcpClient.call_tool).parameters["timeout_seconds"]
    assert list_default.default == 30
    assert call_default.default == 90


def test_error_kinds_are_the_six_declared():
    assert set(typing.get_args(GatewayErrorKind)) == {
        "sign_in_required",
        "missing_scope",
        "access_denied",
        "not_found",
        "timeout",
        "unavailable",
    }


def test_gateway_mcp_error_carries_kind_message_and_sign_in_url():
    err = GatewayMcpError("sign_in_required", "sign in first", sign_in_url="https://h/x")

    assert isinstance(err, Exception)
    assert (err.kind, err.message, err.sign_in_url) == (
        "sign_in_required",
        "sign in first",
        "https://h/x",
    )
    assert GatewayMcpError("not_found", "gone").sign_in_url is None


# ---------------------------------------------------------------------------
# map_gateway_error: sign-in required (rule 1, JSON-RPC -32006)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("depth", [0, 1], ids=["bare", "in_group"])
@pytest.mark.parametrize("lacks_gateway_scope", [False, True])
def test_not_signed_in_401_maps_to_sign_in_with_url_from_message(depth, lacks_gateway_scope):
    # The expected URL is the one in the recorded message, followed there by a ",".
    assert f"{LAKEDRAW_SIGN_IN_URL}, then retry" in _lakedraw_message()
    exc = _in_groups(_lakedraw_not_signed_in_error(), depth)

    mapped = map_gateway_error(
        exc, host=LAKEDRAW_HOST, service_name=LAKEDRAW, lacks_gateway_scope=lacks_gateway_scope
    )

    assert isinstance(mapped, GatewayMcpError)
    assert mapped.kind == "sign_in_required"
    assert mapped.sign_in_url == LAKEDRAW_SIGN_IN_URL


def test_a_sign_in_body_longer_than_500_chars_is_read_whole():
    """T1.2: derived from the recorded LakeDraw body. Padding goes before "Sign in at",
    and "code" comes last, so both the code and the URL sit past character 500."""
    recorded = load("lakedraw_initialize_not_signed_in")
    padding = "This workspace routes MCP traffic through Unity AI Gateway. " * 12
    message = recorded["body_json"]["error"]["message"].replace(
        "Sign in at", padding + "Sign in at"
    )
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "error": {"message": message, "data": None, "code": -32006}}
    )
    assert body.index('"code"') > 500 and body.index("mcp-service-login") > 500
    exc = _in_groups(_http_error(401, body, headers=recorded["headers"], service=LAKEDRAW), 1)

    mapped = map_gateway_error(
        exc, host=LAKEDRAW_HOST, service_name=LAKEDRAW, lacks_gateway_scope=False
    )

    assert mapped.kind == "sign_in_required"
    assert mapped.sign_in_url == LAKEDRAW_SIGN_IN_URL


def test_the_sign_in_url_is_taken_from_the_parsed_message_not_the_raw_body():
    """T1.2: derived from the recorded LakeDraw body, with the message ending at the URL
    and the body compact. On the raw text, ``\\S+`` would run on into ``","data":null}}``."""
    recorded = load("lakedraw_initialize_not_signed_in")
    message = (
        f"You're not signed in to the MCP service '{LAKEDRAW}'. Sign in at {LAKEDRAW_SIGN_IN_URL}"
    )
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "error": {"code": -32006, "message": message, "data": None}},
        separators=(",", ":"),
    )
    assert f'{LAKEDRAW_SIGN_IN_URL}","data":null}}}}' in body
    exc = _in_groups(_http_error(401, body, headers=recorded["headers"], service=LAKEDRAW), 1)

    mapped = map_gateway_error(
        exc, host=LAKEDRAW_HOST, service_name=LAKEDRAW, lacks_gateway_scope=False
    )

    assert mapped.kind == "sign_in_required"
    assert mapped.sign_in_url == LAKEDRAW_SIGN_IN_URL


def test_an_unparseable_body_with_code_32006_is_still_sign_in_required():
    """T1.2 fallback: a cut-short JSON body is matched on its raw text."""
    body = '{"jsonrpc":"2.0","id":1,"error":{"code" : -32006,"message":"The MCP serv'
    exc = _in_groups(
        _http_error(401, body, headers={"content-type": "application/json"}, service=LAKEDRAW),
        1,
    )

    mapped = map_gateway_error(exc, host=HOST, service_name=LAKEDRAW, lacks_gateway_scope=False)

    assert mapped.kind == "sign_in_required"
    assert mapped.sign_in_url == f"{HOST}/mcp-service-login?name={LAKEDRAW}"


def test_sign_in_url_takes_the_workspace_id_from_the_401_header_when_the_message_has_none():
    """Spec, "The Gateway client": with no URL in the message, the link is built and
    gets ``&o=`` from the response's ``x-databricks-org-id`` header."""
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {
                "code": -32006,
                "message": "You're not signed in to the MCP service 'a.b.c'.",
                "data": None,
            },
        }
    )
    headers = {"content-type": "application/json", "x-databricks-org-id": "42"}
    exc = _in_groups(_http_error(401, body, headers=headers, service="a.b.c"), 1)

    mapped = map_gateway_error(exc, host=HOST, service_name="a.b.c", lacks_gateway_scope=False)

    assert mapped.kind == "sign_in_required"
    assert mapped.sign_in_url == f"{HOST}/mcp-service-login?name=a.b.c&o=42"


@pytest.mark.parametrize("lacks_gateway_scope", [False, True])
def test_jsonrpc_32006_in_200_maps_to_sign_in_with_built_url(lacks_gateway_scope):
    mapped = map_gateway_error(
        _github_rejection(),
        host="https://h.example",
        service_name=GITHUB,
        lacks_gateway_scope=lacks_gateway_scope,
    )

    assert mapped.kind == "sign_in_required"
    assert mapped.sign_in_url == "https://h.example/mcp-service-login?name=system.ai.github"


# ---------------------------------------------------------------------------
# map_gateway_error: missing scope, access denied, not found, unavailable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "make_exception",
    [
        lambda: RuntimeError(SCOPE_TEXT),
        lambda: _in_groups(RuntimeError(SCOPE_TEXT), 2),
        lambda: _in_groups(_http_error(403, SCOPE_TEXT), 1),
        lambda: _in_groups(_http_error(403, "Invalid scope, required scopes: ai-gateway"), 1),
        lambda: _in_groups(McpError(ErrorData(code=-32603, message=SCOPE_TEXT)), 2),
    ],
    ids=["text", "text_in_groups", "403_body", "403_invalid_scope_body", "mcp_error_text"],
)
def test_scope_message_maps_to_missing_scope(make_exception):
    mapped = map_gateway_error(
        make_exception(), host=HOST, service_name=WEB_SEARCH, lacks_gateway_scope=False
    )

    assert mapped.kind == "missing_scope"
    assert mapped.sign_in_url is None


@pytest.mark.parametrize(
    "make_exception",
    [
        lambda: _http_error(401, "Unauthorized"),
        lambda: _in_groups(_http_error(401, "Unauthorized"), 1),
        lambda: _in_groups(_http_error(401, '{"error_code": "UNAUTHENTICATED"}'), 1),
    ],
    ids=["bare", "in_group", "json_without_32006"],
)
def test_any_other_401_maps_to_missing_scope(make_exception):
    mapped = map_gateway_error(
        make_exception(), host=HOST, service_name=WEB_SEARCH, lacks_gateway_scope=False
    )

    assert mapped.kind == "missing_scope"


def _permission_denied() -> BaseException:
    return PermissionDenied("User does not have EXECUTE on 'system.ai.web_search'.")


@pytest.mark.parametrize(
    ("make_exception", "lacks_gateway_scope", "kind"),
    [
        (lambda: _in_groups(_http_error(403, "Forbidden"), 1), False, "access_denied"),
        (lambda: _in_groups(_http_error(403, "Forbidden"), 1), True, "missing_scope"),
        (_permission_denied, False, "access_denied"),
        (_permission_denied, True, "missing_scope"),
        (
            lambda: RuntimeError("PERMISSION_DENIED: no EXECUTE on system.ai.web_search"),
            False,
            "access_denied",
        ),
        (
            lambda: _in_groups(
                _http_error(403, "Service system.ai.web_search does not exist or is not shared"), 1
            ),
            False,
            "access_denied",
        ),
    ],
    ids=[
        "403_scopes_have_gateway",
        "403_scopes_lack_gateway",
        "permission_denied",
        "permission_denied_scopes_lack_gateway",
        "denied_marker_text",
        "403_beats_does_not_exist",
    ],
)
def test_403_maps_to_access_denied_unless_scopes_lack_gateway(
    make_exception, lacks_gateway_scope, kind
):
    mapped = map_gateway_error(
        make_exception(),
        host=HOST,
        service_name=WEB_SEARCH,
        lacks_gateway_scope=lacks_gateway_scope,
    )

    assert mapped.kind == kind
    assert mapped.sign_in_url is None


@pytest.mark.parametrize(
    "make_exception",
    [
        lambda: _in_groups(_http_error(404, "Not Found"), 1),
        lambda: NotFound("Unknown MCP service"),
        lambda: RuntimeError("MCP service 'main.tools.missing' does not exist."),
        lambda: RuntimeError("MCP service not found"),
        _session_terminated,
    ],
    ids=["http_404", "sdk_not_found", "does_not_exist", "not_found_text", "session_terminated"],
)
@pytest.mark.parametrize("lacks_gateway_scope", [False, True])
def test_404_and_server_not_found_map_to_not_found(make_exception, lacks_gateway_scope):
    mapped = map_gateway_error(
        make_exception(),
        host=HOST,
        service_name="main.tools.missing",
        lacks_gateway_scope=lacks_gateway_scope,
    )

    assert mapped.kind == "not_found"


@pytest.mark.parametrize(
    "make_exception",
    [
        lambda: RuntimeError("Connection reset by peer"),
        lambda: _in_groups(_http_error(500, "boom"), 1),
        lambda: _in_groups(httpx.ConnectError("[Errno 61] Connection refused"), 1),
        lambda: _in_groups(McpError(ErrorData(code=-32603, message="Internal error")), 2),
        # Rule 5a needs BOTH code 32600 and "Session terminated".
        lambda: _in_groups(McpError(ErrorData(code=32600, message="Invalid request")), 2),
    ],
    ids=["plain", "http_500", "connect_error", "mcp_internal_error", "mcp_32600_other_text"],
)
@pytest.mark.parametrize("lacks_gateway_scope", [False, True])
def test_other_failures_map_to_unavailable(make_exception, lacks_gateway_scope):
    mapped = map_gateway_error(
        make_exception(),
        host=HOST,
        service_name=WEB_SEARCH,
        lacks_gateway_scope=lacks_gateway_scope,
    )

    assert mapped.kind == "unavailable"


# ---------------------------------------------------------------------------
# GatewayMcpClient through the mcp_client_factory seam
# ---------------------------------------------------------------------------


def test_list_tools_parses_recorded_web_search():
    recorded = load("web_search_tools_list")["body_json"]["result"]["tools"]
    fake = FakeMcpClient(tools=[Tool.model_validate(t) for t in recorded])
    client, factory = make_client(fake)

    specs = client.list_tools()

    assert specs == [_web_search_spec()]
    assert specs[0].name == "web_search"
    assert specs[0].input_schema == {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Search query string"}},
        "required": ["query"],
    }
    # Built by the factory with the user's host, token and the service's path.
    assert [call[:3] for call in factory.calls] == [(HOST, TOKEN, _service_path(WEB_SEARCH))]
    assert fake.sync_wrapper_calls == []


def test_list_tools_keeps_order_and_gives_an_empty_description_when_a_tool_has_none():
    schema = {"type": "object", "properties": {"diagram_data": {"type": "object"}}}
    fake = FakeMcpClient(
        tools=[
            Tool(name="create_diagram", description=None, inputSchema=schema),
            Tool(
                name="get_diagram", description="Fetch a diagram.", inputSchema={"type": "object"}
            ),
        ]
    )
    client, _ = make_client(fake)

    assert client.list_tools() == [
        GatewayToolSpec(name="create_diagram", description="", input_schema=schema),
        GatewayToolSpec(
            name="get_diagram", description="Fetch a diagram.", input_schema={"type": "object"}
        ),
    ]


def test_call_tool_returns_the_result_and_passes_name_and_arguments():
    recorded = load("web_search_call")
    result = CallToolResult.model_validate(recorded["body_json"]["result"])
    arguments = recorded["request"]["params"]["arguments"]
    fake = FakeMcpClient(result=result)
    client, factory = make_client(fake)

    assert client.call_tool("web_search", arguments) is result
    assert fake.calls == [("web_search", arguments)]
    assert [call[:3] for call in factory.calls] == [(HOST, TOKEN, _service_path(WEB_SEARCH))]
    assert fake.sync_wrapper_calls == []


@pytest.mark.parametrize(
    ("host", "text", "url"),
    [
        (LAKEDRAW_HOST, _lakedraw_message(), LAKEDRAW_SIGN_IN_URL),
        (
            HOST,
            "You're not signed in to the MCP service 'system.ai.web_search'.",
            f"{HOST}/mcp-service-login?name={WEB_SEARCH}",
        ),
        (
            "https://w.example",
            "Authorize first: https://w.example/mcp-service-login?name=system.ai.web_search&o=9.",
            "https://w.example/mcp-service-login?name=system.ai.web_search&o=9",
        ),
    ],
    ids=["recorded_lakedraw_text", "not_signed_in_without_url", "login_url_only"],
)
def test_call_tool_is_error_sign_in_result_maps_to_sign_in_required(host: str, text: str, url: str):
    """T1.2: an isError result that says "not signed in" or links mcp-service-login.
    Each client is on the host of the link it should keep."""
    client, _ = make_client(FakeMcpClient(result=_error_result(text)), host=host)

    with pytest.raises(GatewayMcpError) as info:
        client.call_tool("web_search", {"query": "q"})

    assert info.value.kind == "sign_in_required"
    assert info.value.sign_in_url == url


def test_call_tool_returns_other_is_error_results_to_the_caller():
    """The service's own validation error goes back to the model, so it is not raised."""
    result = _error_result("Invalid arguments: 'query' is a required property")
    client, _ = make_client(FakeMcpClient(result=result))

    assert client.call_tool("web_search", {}) is result


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize(
    ("make_exception", "token_scopes", "kind", "url"),
    [
        (
            _github_rejection,
            None,
            "sign_in_required",
            f"{HOST}/mcp-service-login?name={WEB_SEARCH}",
        ),
        (
            lambda: _in_groups(_http_error(403, "Forbidden"), 1),
            frozenset({"sql", "offline_access"}),
            "missing_scope",
            None,
        ),
        (
            lambda: _in_groups(_http_error(403, "Forbidden"), 1),
            frozenset({"ai-gateway", "offline_access"}),
            "access_denied",
            None,
        ),
        (
            lambda: _in_groups(_http_error(403, "Forbidden"), 1),
            frozenset({"all-apis"}),
            "access_denied",
            None,
        ),
        (lambda: _in_groups(_http_error(403, "Forbidden"), 1), None, "access_denied", None),
        (_session_terminated, None, "not_found", None),
        (lambda: KeyError("unexpected"), None, "unavailable", None),
    ],
    ids=[
        "32006",
        "403_scopes_lack_gateway",
        "403_scopes_have_gateway",
        "403_scopes_all_apis",
        "403_scopes_unknown",
        "session_terminated",
        "anything_else",
    ],
)
def test_client_maps_failures_with_its_host_service_and_token_scopes(
    operation, make_exception, token_scopes, kind, url
):
    """Both calls raise only GatewayMcpError. ``lacks_gateway_scope`` comes from
    ``token_scopes`` via ``scopes_grant(scopes, "ai-gateway")``, and unknown scopes
    (None) never lack it."""
    client, _ = make_client(FakeMcpClient(raises=make_exception()), token_scopes=token_scopes)

    with pytest.raises(GatewayMcpError) as info:
        _run(client, operation)

    assert info.value.kind == kind
    assert info.value.sign_in_url == url


@pytest.mark.parametrize("operation", OPERATIONS)
def test_timeout_maps_to_timeout(operation):
    release = threading.Event()
    client, _ = make_client(FakeMcpClient(block=release))
    start = time.monotonic()
    try:
        with pytest.raises(GatewayMcpError) as info:
            _run(client, operation, timeout_seconds=0.05)
        elapsed = time.monotonic() - start
    finally:
        release.set()

    assert info.value.kind == "timeout"
    assert elapsed < 1.0


@pytest.mark.parametrize("operation", OPERATIONS)
def test_the_mcp_client_is_built_lazily_inside_the_worker_thread(operation):
    recorded = load("web_search_call")
    fake = FakeMcpClient(
        tools=[
            Tool.model_validate(t)
            for t in load("web_search_tools_list")["body_json"]["result"]["tools"]
        ],
        result=CallToolResult.model_validate(recorded["body_json"]["result"]),
    )
    client, factory = make_client(fake)
    assert factory.calls == []

    _run(client, operation)

    assert len(factory.calls) == 1
    assert factory.calls[0][3] is not threading.main_thread()


def test_default_factory_builds_a_pat_workspace_client_in_the_timed_worker(
    monkeypatch: pytest.MonkeyPatch,
):
    """T1.4: the default factory is build_user_mcp_client, run inside the worker.
    The fake WorkspaceClient stops the build, so nothing reaches the network."""
    built: list[tuple[dict[str, Any], threading.Thread]] = []

    class FakeWS:
        def __init__(self, **kwargs: Any) -> None:
            built.append((kwargs, threading.current_thread()))
            raise RuntimeError("stopped before any network")

    class FakeMCP:
        def __init__(self, **kwargs: Any) -> None:
            raise AssertionError("not reached: the WorkspaceClient failed first")

    monkeypatch.setattr(databricks.sdk, "WorkspaceClient", FakeWS)
    monkeypatch.setattr(databricks_mcp, "DatabricksMCPClient", FakeMCP)

    client = GatewayMcpClient(host=HOST, token=TOKEN, service_name=WEB_SEARCH)
    assert built == []
    with pytest.raises(GatewayMcpError) as info:
        client.list_tools()

    assert info.value.kind == "unavailable"
    assert [kwargs for kwargs, _ in built] == [{"host": HOST, "token": TOKEN, "auth_type": "pat"}]
    assert built[0][1] is not threading.main_thread()


def test_a_hung_workspace_client_build_is_covered_by_the_timeout(
    monkeypatch: pytest.MonkeyPatch,
):
    release = threading.Event()

    class FakeWS:
        def __init__(self, **kwargs: Any) -> None:
            release.wait(timeout=5)
            raise RuntimeError("released")

    monkeypatch.setattr(databricks.sdk, "WorkspaceClient", FakeWS)

    client = GatewayMcpClient(host=HOST, token=TOKEN, service_name=WEB_SEARCH)
    start = time.monotonic()
    try:
        with pytest.raises(GatewayMcpError) as info:
            client.list_tools(timeout_seconds=0.1)
        elapsed = time.monotonic() - start
    finally:
        release.set()

    assert info.value.kind == "timeout"
    assert elapsed < 1.0


# ---------------------------------------------------------------------------
# Real stack: the default client against a local Gateway (T1.1, T1.5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("operation", OPERATIONS)
def test_client_uses_user_bearer_not_oauth_provider(operation):
    """T1.5: the recorded LakeDraw 401 (with ``WWW-Authenticate``), through the real stack.

    The user's bearer token reaches the service path. The stock OAuth provider
    never runs (it would start RFC 9728 discovery). The 401's -32006 body becomes
    sign-in required. Its recorded link is on the recorded workspace, not on this
    client's (local) host, so it is not trusted: the link is built on the client's
    host, with the workspace id from the 401's ``x-databricks-org-id``. One
    ``initialize`` is sent and no more: ``_handle_mcp_errors`` would re-send one.
    """
    with _LocalGateway(_lakedraw_not_signed_in) as gateway:
        client = GatewayMcpClient(host=gateway.host, token=TOKEN, service_name=LAKEDRAW)
        with pytest.raises(GatewayMcpError) as info:
            _run(client, operation, timeout_seconds=30)

    assert info.value.kind == "sign_in_required"
    assert info.value.sign_in_url == (
        f"{gateway.host}/mcp-service-login?name={LAKEDRAW}&o={LAKEDRAW_ORG_ID}"
    )
    assert gateway_service_url(gateway.host, LAKEDRAW) == gateway.host + _service_path(LAKEDRAW)
    to_service = gateway.requests_to(_service_path(LAKEDRAW))
    assert [(r.method, r.rpc_method, r.authorization) for r in to_service] == [
        ("POST", "initialize", f"Bearer {TOKEN}")
    ]
    assert gateway.oauth_discovery_requests() == []


@pytest.mark.parametrize("operation", OPERATIONS)
def test_http_404_maps_to_not_found_through_the_real_stack(operation):
    """T1.1: mcp 1.27 turns a 404 into McpError(32600, "Session terminated")."""
    missing = "main.tools.missing"
    with _LocalGateway(_fixed(404, b"Not Found", {"content-type": "text/plain"})) as gateway:
        client = GatewayMcpClient(host=gateway.host, token=TOKEN, service_name=missing)
        with pytest.raises(GatewayMcpError) as info:
            _run(client, operation, timeout_seconds=30)

    assert info.value.kind == "not_found"
    assert [(r.method, r.rpc_method) for r in gateway.requests_to(_service_path(missing))] == [
        ("POST", "initialize")
    ]


def test_real_stack_jsonrpc_32006_in_200_is_sign_in_required():
    """The recorded github ``tools/list`` rejection, after a good ``initialize``.

    The local reply carries only content-type, so the workspace id is unknown and the
    built link has no ``&o=``.
    """
    rejected = load("github_tools_list_rejected")["body_json"]
    with _LocalGateway(_jsonrpc({"tools/list": rejected})) as gateway:
        client = GatewayMcpClient(host=gateway.host, token=TOKEN, service_name=GITHUB)
        with pytest.raises(GatewayMcpError) as info:
            client.list_tools(timeout_seconds=30)

    assert info.value.kind == "sign_in_required"
    assert info.value.sign_in_url == f"{gateway.host}/mcp-service-login?name=system.ai.github"


def test_real_stack_list_tools_returns_the_recorded_web_search_tool():
    tools_list = load("web_search_tools_list")["body_json"]
    with _LocalGateway(_jsonrpc({"tools/list": tools_list})) as gateway:
        client = GatewayMcpClient(host=gateway.host, token=TOKEN, service_name=WEB_SEARCH)
        specs = client.list_tools(timeout_seconds=30)

    assert specs == [_web_search_spec()]
    to_service = gateway.requests_to(_service_path(WEB_SEARCH))
    assert [r.rpc_method for r in to_service] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
    ]
    assert {r.authorization for r in to_service} == {f"Bearer {TOKEN}"}


def test_real_stack_call_tool_returns_the_recorded_result():
    recorded = load("web_search_call")
    replies = {
        "tools/call": recorded["body_json"],
        # mcp's ClientSession lists tools after a call to check its output schema.
        "tools/list": load("web_search_tools_list")["body_json"],
    }
    with _LocalGateway(_jsonrpc(replies)) as gateway:
        client = GatewayMcpClient(host=gateway.host, token=TOKEN, service_name=WEB_SEARCH)
        result = client.call_tool(
            "web_search", recorded["request"]["params"]["arguments"], timeout_seconds=30
        )

    assert isinstance(result, CallToolResult)
    assert result.isError is False
    assert [block.text for block in result.content] == [
        recorded["body_json"]["result"]["content"][0]["text"]
    ]
    to_service = gateway.requests_to(_service_path(WEB_SEARCH))
    assert [r.rpc_params for r in to_service if r.rpc_method == "tools/call"] == [
        recorded["request"]["params"]
    ]
    assert {r.authorization for r in to_service} == {f"Bearer {TOKEN}"}


# ---------------------------------------------------------------------------
# probe_service
# ---------------------------------------------------------------------------


class _ScriptedListTools(GatewayMcpClient):
    """A client whose ``list_tools`` returns the given specs or raises the given error."""

    def __init__(self, outcome: list[GatewayToolSpec] | GatewayMcpError) -> None:
        super().__init__(
            host=HOST,
            token=TOKEN,
            service_name=WEB_SEARCH,
            mcp_client_factory=FakeFactory(FakeMcpClient()),
        )
        self._outcome = outcome

    def list_tools(self, **kwargs: Any) -> list[GatewayToolSpec]:
        if isinstance(self._outcome, GatewayMcpError):
            raise self._outcome
        return list(self._outcome)


_PROBE_STATES = {
    "sign_in_required": "sign_in_required",
    "missing_scope": "missing_scope",
    "access_denied": "access_denied",
    "not_found": "not_found",
    "timeout": "unavailable",
    "unavailable": "unavailable",
}


def test_probe_states_cover_every_error_kind():
    assert set(_PROBE_STATES) == set(typing.get_args(GatewayErrorKind))


@pytest.mark.parametrize(("kind", "state"), sorted(_PROBE_STATES.items()))
def test_probe_service_states(kind: str, state: str):
    url = f"{HOST}/mcp-service-login?name={WEB_SEARCH}" if kind == "sign_in_required" else None
    error = GatewayMcpError(kind, f"{kind}: what the service said", sign_in_url=url)

    probe = probe_service(_ScriptedListTools(error))

    assert probe == GatewayProbe(
        state=state, tools=(), sign_in_url=url, detail=f"{kind}: what the service said"
    )


def test_probe_service_states_ready_with_the_tools():
    specs = [
        _web_search_spec(),
        GatewayToolSpec(name="other", description="", input_schema={"type": "object"}),
    ]

    assert probe_service(_ScriptedListTools(specs)) == GatewayProbe(
        state="ready", tools=tuple(specs), sign_in_url=None, detail=None
    )


# ---------------------------------------------------------------------------
# mcp_transport: run_with_timeout and build_user_mcp_client
# ---------------------------------------------------------------------------


def test_run_with_timeout_returns_the_value_from_a_worker_thread():
    threads: list[threading.Thread] = []

    def fn() -> int:
        threads.append(threading.current_thread())
        return 42

    assert run_with_timeout(fn, timeout_seconds=5, on_timeout=lambda: AssertionError("late")) == 42
    assert threads[0] is not threading.main_thread()


def test_run_with_timeout_raises_on_timeout_without_waiting_for_the_worker():
    release = threading.Event()
    late = RuntimeError("took too long")
    start = time.monotonic()
    try:
        with pytest.raises(RuntimeError) as info:
            run_with_timeout(
                lambda: release.wait(timeout=5), timeout_seconds=0.05, on_timeout=lambda: late
            )
        elapsed = time.monotonic() - start
    finally:
        release.set()

    assert info.value is late
    assert elapsed < 1.0


def test_run_with_timeout_lets_the_functions_own_error_through():
    boom = KeyError("boom")

    def fn() -> None:
        raise boom

    with pytest.raises(KeyError) as info:
        run_with_timeout(fn, timeout_seconds=5, on_timeout=lambda: AssertionError("late"))

    assert info.value is boom


def _record_construction(monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], type, type]:
    """Patch WorkspaceClient and DatabricksMCPClient with fakes that record their kwargs."""
    record: dict[str, Any] = {}

    class FakeWS:
        def __init__(self, **kwargs: Any) -> None:
            record["ws"] = kwargs

    class FakeMCP:
        def __init__(self, **kwargs: Any) -> None:
            record["mcp"] = kwargs

        def call_tool(self, name: str, args: dict[str, Any]) -> Any:
            raise AssertionError("not called")

    monkeypatch.setattr(databricks.sdk, "WorkspaceClient", FakeWS)
    monkeypatch.setattr(databricks_mcp, "DatabricksMCPClient", FakeMCP)
    return record, FakeWS, FakeMCP


def test_build_user_mcp_client_builds_with_keywords_against_the_service_path(
    monkeypatch: pytest.MonkeyPatch,
):
    """T1.3: ``WorkspaceClient(host=, token=, auth_type="pat")`` and
    ``Sub(server_url=, workspace_client=)``, keywords only."""
    record, fake_ws, fake_mcp = _record_construction(monkeypatch)

    client = build_user_mcp_client(HOST, TOKEN, _service_path("a.b.c"))

    assert isinstance(client, fake_mcp)
    assert record["ws"] == {"host": HOST, "token": TOKEN, "auth_type": "pat"}
    assert set(record["mcp"]) == {"server_url", "workspace_client"}
    assert record["mcp"]["server_url"] == f"{HOST}/ai-gateway/mcp-services/a.b.c"
    assert isinstance(record["mcp"]["workspace_client"], fake_ws)


# ---------------------------------------------------------------------------
# Genie One: unchanged surface, now on the shared transport
# ---------------------------------------------------------------------------


def test_genie_one_surface_is_unchanged(monkeypatch: pytest.MonkeyPatch):
    """Guard: the names Genie One's own tests use stay, with the same behaviour."""
    assert genie_one.GENIE_ONE_SERVICE_PATH == "/ai-gateway/mcp-services/system.ai.genie_one_mcp"
    assert genie_one._CALL_TIMEOUT_SECONDS == 60
    assert issubclass(genie_one._UserBearerAuth, httpx.Auth)
    record, fake_ws, fake_mcp = _record_construction(monkeypatch)

    client = genie_one._build_mcp_client(HOST, TOKEN)

    assert isinstance(client, fake_mcp)
    assert record["ws"] == {"host": HOST, "token": TOKEN, "auth_type": "pat"}
    assert record["mcp"]["server_url"] == f"{HOST}{genie_one.GENIE_ONE_SERVICE_PATH}"
    assert isinstance(record["mcp"]["workspace_client"], fake_ws)
    # T1.3: Genie One stays on the base's sync call_tool.
    assert type(client).call_tool is fake_mcp.call_tool


def test_genie_one_builds_its_client_on_the_shared_transport():
    """Genie One's ``_UserBearerAuth`` IS the shared one. Its builder delegates to
    ``build_user_mcp_client``, so ``_get_tools_async`` also uses the user's bearer.
    The stock one ran the OAuth provider, which died in discovery on a 401."""
    assert genie_one._UserBearerAuth is UserBearerAuth
    with _LocalGateway(_lakedraw_not_signed_in) as gateway:
        client = genie_one._build_mcp_client(gateway.host, TOKEN)
        with pytest.raises(Exception) as info:
            asyncio.run(client._get_tools_async())

    statuses = [
        e.response.status_code for e in _chain(info.value) if isinstance(e, httpx.HTTPStatusError)
    ]
    assert statuses == [401]
    assert gateway.oauth_discovery_requests() == []
    to_service = gateway.requests_to(genie_one.GENIE_ONE_SERVICE_PATH)
    assert to_service and {r.authorization for r in to_service} == {f"Bearer {TOKEN}"}
