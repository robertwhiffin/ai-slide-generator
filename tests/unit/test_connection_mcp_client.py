"""Task 2: ``ConnectionMcpClient``, the Gateway MCP client over the Unity Catalog
connection proxy ``/api/2.0/mcp/external/<connection name>``.

Module under test: ``src/services/agent_tools/gateway_mcp.py``, which gains
``connection_path``, ``connection_sign_in_url``, ``map_connection_error`` and
``ConnectionMcpClient`` (a ``GatewayMcpClient`` subclass).

The error shapes are the ones probed live on tellr-dev on 2026-11-12 (plan ruling R3):

- **Not signed in** to a per-user connection: an ``McpError`` with code -32600, inside
  nested exception groups. Its message is a JSON string holding
  ``"error_code":"UNAUTHENTICATED"`` and "Please login first to the connection by
  visiting https://<host>/explore/connections/<name>?o=<workspace id>".
- **No grant**: an httpx 403 whose body is
  ``{"error_code":"PERMISSION_DENIED","message":"User is missing USE CONNECTION on <name>."}``.

Neither is a Gateway -32006, and under the Gateway rules the first maps to
``not_found`` (its text says "not found"). So the connection client has its own first
rule (Rule 0); everything else falls through to ``map_gateway_error`` with
``lacks_gateway_scope=False`` (a connection does not need the ``ai-gateway`` scope).

The fake MCP client behind the ``mcp_client_factory(host, token, path)`` seam is the
one ``tests/unit/test_gateway_mcp_client.py`` uses: only the async session methods
answer; the sync wrappers (databricks_mcp's ``_handle_mcp_errors``) refuse.

The last section pins that the Gateway client does NOT pick up the connection rules:
"Gateway behaviour must not change by one byte".
"""

from __future__ import annotations

import builtins
import json
from typing import Any

import httpx
import pytest
from mcp.shared.exceptions import McpError
from mcp.types import CallToolResult, ErrorData, TextContent, Tool

from src.services.agent_tools import gateway_mcp
from src.services.agent_tools.gateway_mcp import (
    ConnectionMcpClient,
    GatewayMcpClient,
    GatewayMcpError,
    GatewayToolSpec,
    connection_path,
    connection_sign_in_url,
    map_connection_error,
)

HOST = "https://h.example"
TOKEN = "user-token-from-get_user_client"

#: The read-only web search connection the user owns on tellr-dev (plan ruling R5).
WEB = "you-web-search-mcp"
#: A per-user (U2M) connection the user is not signed in to.
GH = "gh"
EXTERNAL_PREFIX = "/api/2.0/mcp/external/"
#: The link the UC proxy puts in its "please login" message for GH on HOST.
GH_LINK = "https://h.example/explore/connections/gh?o=7"
#: Tellr's own link for GH on HOST, used when the message has no usable link.
GH_BUILT_LINK = "https://h.example/explore/connections/gh"
#: anyio's task-group message, as the measured groups carry it.
TASK_GROUP = "unhandled errors in a TaskGroup (1 sub-exception)"
#: The production wording of a missing-scope refusal, for the proxy's scope.
SCOPE_TEXT = "Provided OAuth token does not have required scopes: mcp.external"
#: The probed body of a 403 for a user without USE CONNECTION on GH.
USE_CONNECTION_BODY = (
    '{"error_code":"PERMISSION_DENIED","message":"User is missing USE CONNECTION on gh."}'
)

# Python 3.11 builtins; reached through builtins because ruff targets py39.
_ExceptionGroup = builtins.ExceptionGroup


def _uc_not_signed_in_message(link: str = GH_LINK) -> str:
    """The probed ``McpError.error.message`` for a connection the user is not signed in to.

    A compact JSON string (no spaces after the separators), as the proxy sends it. The
    link is followed by the closing ``"}``.
    """
    return (
        '{"error_code":"UNAUTHENTICATED","message":"Credential for user identity'
        "('user@example.com') is not found for the connection 'gh'. Please login first "
        f'to the connection by visiting {link}"}}'
    )


# ---------------------------------------------------------------------------
# Exceptions shaped like the measured ones
# ---------------------------------------------------------------------------


def _in_groups(exc: BaseException, depth: int) -> BaseException:
    """*exc* wrapped in *depth* task-group exception groups, innermost first."""
    for _ in range(depth):
        exc = _ExceptionGroup(TASK_GROUP, [exc])
    return exc


def _http_error(status: int, body: str = "", *, connection: str = GH) -> httpx.HTTPStatusError:
    """httpx's own error for a proxy reply, raised by ``raise_for_status``, its body read."""
    request = httpx.Request("POST", f"{HOST}{EXTERNAL_PREFIX}{connection}")
    response = httpx.Response(status, content=body.encode(), request=request)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        return exc
    raise AssertionError(f"HTTP {status} is not an error status")


def _uc_mcp_error(link: str = GH_LINK) -> McpError:
    return McpError(ErrorData(code=-32600, message=_uc_not_signed_in_message(link)))


#: Every place Rule 0 must look: the ``McpError``'s message (as probed, one group deep
#: as the brief writes it, and two deep as measured), an error response body (a 401,
#: which the Gateway rules would call a missing scope), and an exception's own text.
_NOT_SIGNED_IN_CARRIERS = {
    "mcp_error_in_one_group": lambda: _ExceptionGroup("g", [_uc_mcp_error()]),
    "mcp_error_in_two_groups": lambda: _in_groups(_uc_mcp_error(), 2),
    "http_401_body": lambda: _in_groups(_http_error(401, _uc_not_signed_in_message()), 1),
    "exception_text": lambda: RuntimeError(_uc_not_signed_in_message()),
}


# ---------------------------------------------------------------------------
# The fake MCP client behind the mcp_client_factory seam
# ---------------------------------------------------------------------------


class FakeMcpClient:
    """Stands in for what ``build_user_mcp_client`` returns.

    The async session methods answer from a script (or raise *raises*). The sync
    wrappers carry ``_handle_mcp_errors``, which the client must skip, so they raise.
    """

    def __init__(
        self,
        *,
        tools: list[Tool] | None = None,
        result: Any = None,
        raises: BaseException | None = None,
    ) -> None:
        self.tools = tools or []
        self.result = result
        self.raises = raises
        self.calls: list[tuple[str, Any]] = []

    async def _get_tools_async(self) -> list[Tool]:
        if self.raises is not None:
            raise self.raises
        return list(self.tools)

    async def _call_tools_async(self, tool_name: str, arguments: dict[str, Any] | None = None):
        self.calls.append((tool_name, arguments))
        if self.raises is not None:
            raise self.raises
        return self.result

    def list_tools(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the sync list_tools wrapper (_handle_mcp_errors) was used")

    def call_tool(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the sync call_tool wrapper (_handle_mcp_errors) was used")


class FakeFactory:
    """An ``mcp_client_factory``: records ``(host, token, path)`` per build."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, host: str, token: str, path: str) -> Any:
        self.calls.append((host, token, path))
        return self.client


def make_connection_client(
    fake: FakeMcpClient,
    *,
    connection_name: str = GH,
    token_scopes: frozenset[str] | None = None,
) -> tuple[ConnectionMcpClient, FakeFactory]:
    factory = FakeFactory(fake)
    client = ConnectionMcpClient(
        host=HOST,
        token=TOKEN,
        service_name=connection_name,
        token_scopes=token_scopes,
        mcp_client_factory=factory,
    )
    return client, factory


def _run(client: GatewayMcpClient, operation: str) -> Any:
    if operation == "list_tools":
        return client.list_tools()
    return client.call_tool("search", {"query": "q"})


OPERATIONS = ["list_tools", "call_tool"]


def _error_result(text: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], isError=True)


# ---------------------------------------------------------------------------
# The surface
# ---------------------------------------------------------------------------


def test_the_connection_names_are_exported_and_the_client_is_a_gateway_client():
    """Task 3 binds connections through ``Callable[..., GatewayMcpClient]``."""
    assert {
        "ConnectionMcpClient",
        "connection_path",
        "connection_sign_in_url",
        "map_connection_error",
    } <= set(gateway_mcp.__all__)
    assert issubclass(ConnectionMcpClient, GatewayMcpClient)


# ---------------------------------------------------------------------------
# The UC proxy path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("operation", OPERATIONS)
def test_connection_client_calls_the_uc_proxy_path(operation: str):
    tool = Tool(name="search", description="Search the web.", inputSchema={"type": "object"})
    result = CallToolResult(content=[TextContent(type="text", text="hits")], isError=False)
    fake = FakeMcpClient(tools=[tool], result=result)
    client, factory = make_connection_client(fake, connection_name=WEB)

    out = _run(client, operation)

    # Built once, by the factory, with the user's host and token and the proxy path.
    assert factory.calls == [(HOST, TOKEN, "/api/2.0/mcp/external/you-web-search-mcp")]
    if operation == "list_tools":
        assert out == [
            GatewayToolSpec(
                name="search", description="Search the web.", input_schema={"type": "object"}
            )
        ]
    else:
        assert out is result
        assert fake.calls == [("search", {"query": "q"})]


@pytest.mark.parametrize(
    ("name", "encoded"),
    [
        ("a/../b", "a%2F..%2Fb"),
        ("a b", "a%20b"),
        ("x?y#z", "x%3Fy%23z"),
        ("50%", "50%25"),
    ],
    ids=["slash_and_dots", "space", "query_and_fragment", "percent"],
)
def test_connection_name_is_percent_encoded_in_the_path(name: str, encoded: str):
    """The whole name is one path segment (``quote(name, safe="")``): no "/" survives,
    so a stored name can never walk the proxy path."""
    client, factory = make_connection_client(FakeMcpClient(), connection_name=name)

    client.list_tools()

    [(_, _, path)] = factory.calls
    assert path.endswith(encoded)
    assert path == EXTERNAL_PREFIX + encoded
    assert connection_path(name) == EXTERNAL_PREFIX + encoded


def test_connection_path_of_a_plain_name_is_the_name():
    assert connection_path(WEB) == "/api/2.0/mcp/external/you-web-search-mcp"


# ---------------------------------------------------------------------------
# Rule 0: the UC proxy's "not signed in"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize(
    "make_exception", list(_NOT_SIGNED_IN_CARRIERS.values()), ids=list(_NOT_SIGNED_IN_CARRIERS)
)
def test_uc_unauthenticated_is_sign_in_required_with_the_servers_link(
    operation: str, make_exception
):
    """The link is the proxy's own (on the client's host), with the JSON's closing
    ``"}`` stripped off it."""
    client, _ = make_connection_client(FakeMcpClient(raises=make_exception()))

    with pytest.raises(GatewayMcpError) as info:
        _run(client, operation)

    assert info.value.kind == "sign_in_required"
    assert info.value.sign_in_url == GH_LINK
    assert info.value.message == "Not signed in to gh"


@pytest.mark.parametrize(
    "make_exception", list(_NOT_SIGNED_IN_CARRIERS.values()), ids=list(_NOT_SIGNED_IN_CARRIERS)
)
def test_map_connection_error_applies_rule_zero_itself(make_exception):
    mapped = map_connection_error(make_exception(), host=HOST, connection_name=GH)

    assert isinstance(mapped, GatewayMcpError)
    assert (mapped.kind, mapped.message, mapped.sign_in_url) == (
        "sign_in_required",
        "Not signed in to gh",
        GH_LINK,
    )


@pytest.mark.parametrize(
    "make_exception",
    [
        lambda: _ExceptionGroup(
            "g", [McpError(ErrorData(code=-32600, message='{"error_code":"UNAUTHENTICATED"}'))]
        ),
        lambda: _in_groups(
            _http_error(401, "Please login first to the connection in Catalog Explorer."), 1
        ),
    ],
    ids=["error_code_alone", "login_phrase_alone"],
)
def test_either_rule_zero_phrase_alone_is_sign_in_required_with_a_built_link(make_exception):
    """Rule 0 is ``"error_code":"UNAUTHENTICATED"`` OR the login phrase. With no link in
    the text, the link is Tellr's own Catalog Explorer page for the connection."""
    client, _ = make_connection_client(FakeMcpClient(raises=make_exception()))

    with pytest.raises(GatewayMcpError) as info:
        client.list_tools()

    assert info.value.kind == "sign_in_required"
    assert info.value.sign_in_url == GH_BUILT_LINK


#: Links that are not on HOST. Only the scheme and authority decide, so look-alikes
#: count too.
_FOREIGN_LINKS = {
    "other_host": "https://evil.example/explore/connections/gh?o=7",
    "host_as_prefix": "https://h.example.evil.example/explore/connections/gh?o=7",
    "host_as_userinfo": "https://h.example@evil.example/explore/connections/gh?o=7",
    "other_port": "https://h.example:8443/explore/connections/gh?o=7",
}


@pytest.mark.parametrize("foreign_link", list(_FOREIGN_LINKS.values()), ids=list(_FOREIGN_LINKS))
def test_a_link_on_another_host_is_replaced_by_tellrs_own(foreign_link: str):
    """The message comes from behind the proxy, and the link is shown as Tellr's own
    sign-in link, so a link anywhere but the client's host is never used (nor its
    workspace id)."""
    client, _ = make_connection_client(
        FakeMcpClient(raises=_ExceptionGroup("g", [_uc_mcp_error(foreign_link)]))
    )

    with pytest.raises(GatewayMcpError) as info:
        client.list_tools()

    assert info.value.kind == "sign_in_required"
    assert info.value.sign_in_url == "https://h.example/explore/connections/gh"


@pytest.mark.parametrize("tail", ['"}', '"', "'", ".", ",", ";", ")", "}", ").", "'}"])
def test_connection_sign_in_url_strips_trailing_punctuation_from_the_link(tail: str):
    message = f"Please login first to the connection by visiting {GH_LINK}{tail}"

    assert connection_sign_in_url(HOST, GH, message=message) == GH_LINK


@pytest.mark.parametrize(
    "message",
    [
        None,
        "Please login first to the connection.",
        f"Please login first to the connection by visiting {_FOREIGN_LINKS['other_host']}",
    ],
    ids=["no_message", "no_link", "foreign_link"],
)
def test_connection_sign_in_url_is_built_on_the_host_without_a_usable_link(message):
    assert connection_sign_in_url(HOST, GH, message=message) == GH_BUILT_LINK
    # The name is one percent-encoded path segment of the built link.
    assert (
        connection_sign_in_url(HOST, "a b/c", message=message)
        == "https://h.example/explore/connections/a%20b%2Fc"
    )


# ---------------------------------------------------------------------------
# Everything else: the Gateway rules, with lacks_gateway_scope=False
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize(
    "token_scopes",
    [None, frozenset({"mcp.external", "offline_access"}), frozenset({"all-apis"})],
    ids=["scopes_unknown", "scopes_lack_ai_gateway", "scopes_all_apis"],
)
def test_missing_use_connection_403_is_access_denied(operation: str, token_scopes):
    """A connection needs no ``ai-gateway`` scope, so a 403 is a denied grant even when
    the token's scopes lack ``ai-gateway`` (``lacks_gateway_scope=False``)."""
    client, _ = make_connection_client(
        FakeMcpClient(raises=_in_groups(_http_error(403, USE_CONNECTION_BODY), 1)),
        token_scopes=token_scopes,
    )

    with pytest.raises(GatewayMcpError) as info:
        _run(client, operation)

    assert info.value.kind == "access_denied"
    assert info.value.sign_in_url is None


@pytest.mark.parametrize(
    "body",
    [
        SCOPE_TEXT,
        # The REST error body the Gateway was recorded sending (ws2a corrections log).
        '{"error_code":403,"message":"' + SCOPE_TEXT + ' [ReqId: 3ff8f85b-502c-45d1]"}',
    ],
    ids=["plain_text", "rest_error_json"],
)
def test_a_scope_message_is_missing_scope(body: str):
    """The 403 alone would be ``access_denied`` (see above); the scope message wins."""
    client, _ = make_connection_client(
        FakeMcpClient(raises=_in_groups(_http_error(403, body), 1)),
    )

    with pytest.raises(GatewayMcpError) as info:
        client.list_tools()

    assert info.value.kind == "missing_scope"
    assert info.value.sign_in_url is None


@pytest.mark.parametrize(
    ("make_exception", "kind"),
    [
        (lambda: _in_groups(_http_error(401, "Unauthorized"), 1), "missing_scope"),
        (lambda: _in_groups(_http_error(404, "Not Found"), 1), "not_found"),
        (
            lambda: _in_groups(McpError(ErrorData(code=32600, message="Session terminated")), 2),
            "not_found",
        ),
        (lambda: _in_groups(_http_error(500, "boom"), 1), "unavailable"),
        # Rule 0 is the phrases, not the code: a bare -32600 is not "not signed in".
        (
            lambda: _in_groups(McpError(ErrorData(code=-32600, message="Invalid request")), 2),
            "unavailable",
        ),
    ],
    ids=["http_401", "http_404", "session_terminated", "http_500", "mcp_32600_without_phrases"],
)
def test_other_failures_follow_the_gateway_rules(make_exception, kind: str):
    client, _ = make_connection_client(
        FakeMcpClient(raises=make_exception()),
        token_scopes=frozenset({"mcp.external"}),
    )

    with pytest.raises(GatewayMcpError) as info:
        client.list_tools()

    assert info.value.kind == kind
    assert info.value.sign_in_url is None


# ---------------------------------------------------------------------------
# isError results
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "url"),
    [
        (
            "Please login first to the connection by visiting "
            "https://h.example/explore/connections/gh",
            "https://h.example/explore/connections/gh",
        ),
        (_uc_not_signed_in_message(), GH_LINK),
        ('{"error_code":"UNAUTHENTICATED","message":"Credential not found"}', GH_BUILT_LINK),
        (
            "Please login first to the connection by visiting "
            "https://evil.example/explore/connections/gh",
            GH_BUILT_LINK,
        ),
    ],
    ids=["login_phrase_with_link", "probed_json_message", "error_code_alone", "foreign_link"],
)
def test_an_iserror_result_asking_to_log_in_raises_sign_in_required(text: str, url: str):
    client, _ = make_connection_client(FakeMcpClient(result=_error_result(text)))

    with pytest.raises(GatewayMcpError) as info:
        client.call_tool("search", {"query": "q"})

    assert info.value.kind == "sign_in_required"
    assert info.value.sign_in_url == url


@pytest.mark.parametrize(
    "text", ["rate limited", "Invalid arguments: 'query' is a required property"]
)
def test_an_ordinary_iserror_result_is_returned_for_the_model(text: str):
    result = _error_result(text)
    fake = FakeMcpClient(result=result)
    client, _ = make_connection_client(fake)

    assert client.call_tool("search", {"query": "q"}) is result
    assert fake.calls == [("search", {"query": "q"})]


# ---------------------------------------------------------------------------
# The Gateway client is not moved
# ---------------------------------------------------------------------------


def _gateway_client(fake: FakeMcpClient) -> tuple[GatewayMcpClient, FakeFactory]:
    factory = FakeFactory(fake)
    client = GatewayMcpClient(
        host=HOST, token=TOKEN, service_name="system.ai.github", mcp_client_factory=factory
    )
    return client, factory


@pytest.mark.parametrize(
    ("carrier", "kind"),
    [
        ("mcp_error_in_one_group", "not_found"),
        ("mcp_error_in_two_groups", "not_found"),
        ("http_401_body", "missing_scope"),
        ("exception_text", "not_found"),
    ],
)
def test_the_gateway_client_does_not_apply_the_connection_rule(carrier: str, kind: str):
    """The UC shapes through the Gateway client map exactly as they did before Task 2."""
    client, factory = _gateway_client(FakeMcpClient(raises=_NOT_SIGNED_IN_CARRIERS[carrier]()))

    with pytest.raises(GatewayMcpError) as info:
        client.list_tools()

    assert info.value.kind == kind
    assert info.value.sign_in_url is None
    assert factory.calls == [(HOST, TOKEN, "/ai-gateway/mcp-services/system.ai.github")]


def test_the_gateway_client_returns_a_connection_login_iserror_for_the_model():
    result = _error_result(
        "Please login first to the connection by visiting https://h.example/explore/connections/gh"
    )
    client, _ = _gateway_client(FakeMcpClient(result=result))

    assert client.call_tool("search", {"query": "q"}) is result


# ---------------------------------------------------------------------------
# Task 3: a known token without mcp.external makes a 403 a missing scope
# ---------------------------------------------------------------------------


def test_the_connection_scope_is_mcp_external():
    assert gateway_mcp.CONNECTION_SCOPE == "mcp.external"


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("body", [USE_CONNECTION_BODY, ""], ids=["use_connection_body", "bare_403"])
@pytest.mark.parametrize(
    ("token_scopes", "kind"),
    [
        (frozenset({"sql"}), "missing_scope"),
        (frozenset({"sql", "mcp.external"}), "access_denied"),
        (None, "access_denied"),
        (frozenset({"all-apis"}), "access_denied"),
    ],
    ids=["known_without_mcp_external", "known_with_mcp_external", "scopes_unknown", "all_apis"],
)
def test_a_403_with_known_scopes_lacking_mcp_external_is_missing_scope(
    operation: str, body: str, token_scopes, kind: str
):
    """The plan adds ``mcp.external`` to the scopes Tellr asks for (R2), so a token whose
    scopes are KNOWN and do not grant it is a stale consent: its 403 is
    ``missing_scope`` (the consent message), not "grant USE CONNECTION".
    ``all-apis`` grants every scope; unknown scopes never refuse."""
    client, _ = make_connection_client(
        FakeMcpClient(raises=_in_groups(_http_error(403, body), 1)),
        token_scopes=token_scopes,
    )

    with pytest.raises(GatewayMcpError) as info:
        _run(client, operation)

    assert info.value.kind == kind
    assert info.value.sign_in_url is None


@pytest.mark.parametrize(
    ("make_exception", "kind", "url"),
    [
        (lambda: _ExceptionGroup("g", [_uc_mcp_error()]), "sign_in_required", GH_LINK),
        (lambda: _in_groups(_http_error(404, "Not Found"), 1), "not_found", None),
        (lambda: _in_groups(_http_error(500, "boom"), 1), "unavailable", None),
    ],
    ids=["not_signed_in", "http_404", "http_500"],
)
def test_a_token_without_mcp_external_changes_only_the_403_rule(make_exception, kind, url):
    """The scope rule is the Gateway rules' ``lacks_gateway_scope``: Rule 0 still comes
    first, and a 404 or a 500 is still what it was."""
    client, _ = make_connection_client(
        FakeMcpClient(raises=make_exception()), token_scopes=frozenset({"sql"})
    )

    with pytest.raises(GatewayMcpError) as info:
        client.list_tools()

    assert info.value.kind == kind
    assert info.value.sign_in_url == url


# ---------------------------------------------------------------------------
# Task 3 addendum: link extraction robustness
# ---------------------------------------------------------------------------


def _jsonrpc_envelope(message: str) -> str:
    """A JSON-RPC error response body carrying *message*, compact as a server sends it."""
    return json.dumps(
        {"jsonrpc": "2.0", "id": 1, "error": {"code": -32600, "message": message}},
        separators=(",", ":"),
    )


@pytest.mark.parametrize("escape_slashes", [False, True], ids=["plain", "json_escaped_slashes"])
def test_a_jsonrpc_envelope_body_gives_a_clean_link(escape_slashes: bool):
    """An HTTP 401 whose body is a JSON-RPC envelope round the UC message. In the raw
    body the UC message is JSON inside JSON (its quotes escaped; with some encoders its
    slashes too, as ``\\/``), so the link must come from the envelope's decoded
    message: the proxy's own link, clean."""
    body = _jsonrpc_envelope(_uc_not_signed_in_message())
    if escape_slashes:
        # JSON allows "\/" for "/"; the body still decodes to the same message.
        body = body.replace("/", "\\/")
        assert "https:\\/\\/h.example\\/explore\\/connections\\/gh?o=7" in body
    assert json.loads(body)["error"]["message"] == _uc_not_signed_in_message()
    exc = _in_groups(_http_error(401, body), 1)
    client, _ = make_connection_client(FakeMcpClient(raises=exc))

    with pytest.raises(GatewayMcpError) as info:
        client.list_tools()

    assert info.value.kind == "sign_in_required"
    assert info.value.sign_in_url == GH_LINK
    mapped = map_connection_error(exc, host=HOST, connection_name=GH)
    assert (mapped.kind, mapped.sign_in_url) == ("sign_in_required", GH_LINK)


#: ``"error_code": "UNAUTHENTICATED"`` with spaces, and no "Please login first" phrase.
_SPACED_UNAUTHENTICATED = {
    "json_default_separators": json.dumps(
        {
            "error_code": "UNAUTHENTICATED",
            "message": "Credential for user identity('user@example.com') is not found "
            "for the connection 'gh'.",
        }
    ),
    "spaces_both_sides": '{"error_code" : "UNAUTHENTICATED", "message" : "Credential missing"}',
}


@pytest.mark.parametrize(
    "message", list(_SPACED_UNAUTHENTICATED.values()), ids=list(_SPACED_UNAUTHENTICATED)
)
def test_a_spaced_unauthenticated_marker_is_sign_in_required(message: str):
    """The marker is JSON, so whitespace round its colon is still the marker: through
    an ``McpError`` and through an ``isError`` result. With no link in the text, the
    link is Tellr's own."""
    assert '"error_code":"UNAUTHENTICATED"' not in message
    assert "Please login first" not in message
    client, _ = make_connection_client(
        FakeMcpClient(raises=_in_groups(McpError(ErrorData(code=-32600, message=message)), 2))
    )

    with pytest.raises(GatewayMcpError) as info:
        client.list_tools()

    assert info.value.kind == "sign_in_required"
    assert info.value.sign_in_url == GH_BUILT_LINK

    client, _ = make_connection_client(FakeMcpClient(result=_error_result(message)))

    with pytest.raises(GatewayMcpError) as info:
        client.call_tool("search", {"query": "q"})

    assert info.value.kind == "sign_in_required"
    assert info.value.sign_in_url == GH_BUILT_LINK


#: The UC message with a JSON field after the link's closing quote.
_UC_MESSAGE_WITH_DETAILS = json.dumps(
    {
        "error_code": "UNAUTHENTICATED",
        "message": "Credential for user identity('user@example.com') is not found for the "
        f"connection 'gh'. Please login first to the connection by visiting {GH_LINK}",
        "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo"}],
    },
    separators=(",", ":"),
)

_TRAILING_FIELD_CARRIERS = {
    "mcp_error_in_two_groups": lambda: _in_groups(
        McpError(ErrorData(code=-32600, message=_UC_MESSAGE_WITH_DETAILS)), 2
    ),
    "http_401_body": lambda: _in_groups(_http_error(401, _UC_MESSAGE_WITH_DETAILS), 1),
    "exception_text": lambda: RuntimeError(_UC_MESSAGE_WITH_DETAILS),
}


@pytest.mark.parametrize(
    "make_exception", list(_TRAILING_FIELD_CARRIERS.values()), ids=list(_TRAILING_FIELD_CARRIERS)
)
def test_a_trailing_json_field_does_not_join_the_link(make_exception):
    """``...gh?o=7","details":[...]`` is on the host, so the on-host check alone does
    not stop the trailing field joining the link: the link must end where the URL
    does."""
    assert GH_LINK + '","details":[{"@type":' in _UC_MESSAGE_WITH_DETAILS
    client, _ = make_connection_client(FakeMcpClient(raises=make_exception()))

    with pytest.raises(GatewayMcpError) as info:
        client.list_tools()

    assert info.value.kind == "sign_in_required"
    assert info.value.sign_in_url == GH_LINK


def test_a_trailing_json_field_does_not_join_the_link_of_an_iserror_result():
    client, _ = make_connection_client(
        FakeMcpClient(result=_error_result(_UC_MESSAGE_WITH_DETAILS))
    )

    with pytest.raises(GatewayMcpError) as info:
        client.call_tool("search", {"query": "q"})

    assert info.value.kind == "sign_in_required"
    assert info.value.sign_in_url == GH_LINK
