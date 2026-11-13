"""Task 3: ``build_gateway_tools`` binds Unity Catalog MCP connections beside Gateway services.

A deck's ``mcp`` entries (``MCPTool``, each stored against an ``agent``) arrive as
``connections=``. Each entry for this build's agent is bound as one more source, beside
the Gateway services:

- its display name is ``entry.server_name``, its key is ``entry.connection_name``, its
  instructions are ``entry.description``, and it has no allowlist;
- the first entry per ``connection_name`` wins;
- a connection named like one of the Gateway *entries*' services is skipped, with a
  warning;
- the ``ai-gateway`` scope pre-flight applies to Gateway rows only: connections are
  always listed;
- both kinds are listed in the one thread pool, and named by ONE ``model_tool_names``
  call;
- a connection's failures carry ``source="connection"``, and its access-denied and
  not-found notices name the connection's owner / Catalog Explorer instead of an admin.

``model_tool_names`` also reserves every name starting ``genie_agent_`` (Task 5's Genie
Agent tools).

The doubles are modelled on ``tests/unit/test_gateway_toolset.py``: a fake client per
source, and a keyword-only factory that records its calls. Gateway rows and connections
get SEPARATE factories (``client_factory=`` / ``connection_client_factory=``), and a
factory asked for a source it was not given fails the test, so a source built by the
wrong factory is caught. Built tools are production's ``GatewayMcpAgentTool``, so
routing is checked by running them, through the loop's own ``_answer_tool_call``
where the loop matters.
"""

from __future__ import annotations

import base64
import dataclasses
import json
import logging
import re
import threading
from typing import Any

import pytest
from mcp.types import CallToolResult, TextContent, Tool

from src.api.schemas.agent_config import GatewayMcpTool, MCPTool
from src.core.scope_errors import consent_message
from src.services.agent_runtime import DatabricksModelAdapter
from src.services.agent_tools import gateway_mcp
from src.services.agent_tools.gateway_mcp import GatewayMcpError, GatewayToolSpec
from src.services.agent_tools.gateway_toolset import (
    GatewayFailure,
    GatewayToolsetBuild,
    build_gateway_tools,
    failure_notice,
    model_tool_names,
)
from src.services.agent_tools.toolset import AgentToolset
from src.services.gateway_mcp_registry import GatewayConnection
from src.utils.spotlight import spotlight

HOST = "https://fevm-db-tellr-dev-workspace.cloud.databricks.com"
#: Not a JWT, so its scopes are unknown (``oauth_scopes_from_token`` -> None).
TOKEN = "dapi-user-token"
USER = "alice@example.com"

#: A Gateway service (the brief's naming example).
GITHUB = "c.s.github"
#: A connection (the brief's naming example).
WEB = "web"
#: The read-only web search connection the user owns on tellr-dev (plan ruling R5).
YOU = "you-web-search-mcp"
#: A second connection.
DOCS_CONN = "docs-mcp"
#: The UC proxy's sign-in link for a connection.
CONN_SIGN_IN_URL = HOST + "/explore/connections/" + DOCS_CONN + "?o=7474645249186749"

#: Every model-facing tool name.
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
#: U+00B7 and U+2014, as the Global Constraints copy has them.
DOT = "·"
DASH = "—"


# ---------------------------------------------------------------------------
# Doubles and builders
# ---------------------------------------------------------------------------


def _conn(
    service_name: str, display_name: str, *, agent: str = "architect", id: int = 1
) -> GatewayConnection:
    """An admin registry row for a Gateway service."""
    return GatewayConnection(
        id=id,
        service_name=service_name,
        display_name=display_name,
        description=None,
        agent=agent,  # type: ignore[arg-type]
        instructions=None,
        tool_allowlist=None,
        enabled=True,
        created_by="admin@example.com",
        created_at=None,
        updated_by="admin@example.com",
        updated_at=None,
    )


def _entry(service_name: str, display_name: str) -> GatewayMcpTool:
    """A deck's ``gateway_mcp`` entry."""
    return GatewayMcpTool(type="gateway_mcp", service_name=service_name, display_name=display_name)


def _mcp(
    connection_name: str,
    server_name: str,
    *,
    agent: str = "data_analyst",
    description: str | None = None,
) -> MCPTool:
    """A deck's ``mcp`` entry (a UC connection) for *agent*."""
    return MCPTool(
        type="mcp",
        connection_name=connection_name,
        server_name=server_name,
        description=description,
        agent=agent,  # type: ignore[arg-type]
    )


def _spec(name: str, description: str = "") -> GatewayToolSpec:
    return GatewayToolSpec(
        name=name, description=description, input_schema={"type": "object", "properties": {}}
    )


def _text_result(text: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], isError=False)


class FakeClient:
    """A client double for one source (a Gateway service or a connection).

    ``list_tools`` runs ``before_list`` (a barrier), then raises ``list_error`` or
    returns ``tools``. ``call_tool`` records ``(name, args)`` and raises ``call_error``
    or returns a text block naming the source, so a test can tell who answered.
    """

    def __init__(
        self,
        name: str,
        tools: list[GatewayToolSpec] | tuple[GatewayToolSpec, ...] = (),
        *,
        list_error: BaseException | None = None,
        before_list: Any = None,
        call_error: BaseException | None = None,
    ) -> None:
        self.name = name
        self.tools = list(tools)
        self.list_error = list_error
        self.before_list = before_list
        self.call_error = call_error
        self.list_calls = 0
        self.calls: list[tuple[str, Any]] = []

    def list_tools(self, **kwargs: Any) -> list[GatewayToolSpec]:
        self.list_calls += 1
        if self.before_list is not None:
            self.before_list()
        if self.list_error is not None:
            raise self.list_error
        return list(self.tools)

    def call_tool(self, name: str, arguments: Any, *, timeout_seconds: float = 90) -> Any:
        self.calls.append((name, arguments))
        if self.call_error is not None:
            raise self.call_error
        return _text_result("answer from " + self.name)


class Factory:
    """A client factory double: records every call's kwargs and returns the fake for its
    ``service_name``. Keyword-only, like ``GatewayMcpClient`` / ``ConnectionMcpClient``.

    Asked for a source it was not given, it fails the test: the source was built by
    the wrong factory (or should not have been built at all).
    """

    def __init__(self, label: str, *clients: FakeClient) -> None:
        self.label = label
        self.by_name = {client.name: client for client in clients}
        self.calls: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def __call__(self, **kwargs: Any) -> FakeClient:
        with self._lock:
            self.calls.append(kwargs)
        name = kwargs.get("service_name")
        if name not in self.by_name:
            pytest.fail(f"the {self.label} factory was asked to build {name!r}")
        return self.by_name[name]

    @property
    def built(self) -> list[str]:
        return sorted(call["service_name"] for call in self.calls)


def _gateway(*clients: FakeClient) -> Factory:
    return Factory("Gateway", *clients)


def _connections(*clients: FakeClient) -> Factory:
    return Factory("connection", *clients)


def _build(
    *,
    entries: list[GatewayMcpTool] | None = None,
    registry: dict[str, GatewayConnection] | None = None,
    connections: list[MCPTool] | None = None,
    gateway: Factory | None = None,
    connection: Factory | None = None,
    agent: str = "data_analyst",
    token: str = TOKEN,
    on_call: Any = None,
) -> GatewayToolsetBuild:
    return build_gateway_tools(
        entries or [],
        agent=agent,  # type: ignore[arg-type]
        registry=registry or {},
        host=HOST,
        token=token,
        user=USER,
        on_call=on_call if on_call is not None else (lambda line: None),
        session_id="session-1",
        client_factory=gateway if gateway is not None else _gateway(),
        connections=tuple(connections or ()),
        connection_client_factory=connection if connection is not None else _connections(),
    )


def _run(tool: Any, args: dict[str, Any] | None = None) -> str:
    """Run a built tool as the loop does: args parsed with its ``args_schema``."""
    return tool.run(tool.args_schema.model_validate(args or {}), remaining_seconds=60.0)


def _answer(tool_by_name: dict[str, Any], toolset: AgentToolset, name: str, args: dict, cid: str):
    """One tool call answered by the runtime loop's own dispatcher."""
    return DatabricksModelAdapter._answer_tool_call(
        {"name": name, "args": dict(args), "id": cid, "type": "tool_call"},
        tool_by_name,
        toolset,
        budget_text="Tool budget exhausted.",
    )


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _jwt(payload: dict[str, Any]) -> str:
    """An unsigned JWT: enough for ``oauth_scopes_from_token`` to read its scopes."""
    return (
        _b64url(json.dumps({"alg": "none", "typ": "JWT"}).encode())
        + "."
        + _b64url(json.dumps(payload).encode())
        + ".sig"
    )


def _names(build: GatewayToolsetBuild) -> list[str]:
    return sorted(tool.name for tool in build.tools)


# ---------------------------------------------------------------------------
# Which connection entries a build binds
# ---------------------------------------------------------------------------


def test_connection_entries_for_this_agent_are_bound_and_others_skipped():
    """Each agent's build binds only the connections stored against it. The other
    agent's connection is skipped silently: no tools, no failure, never contacted."""
    connections = [
        _mcp(YOU, "Web Search", agent="data_analyst"),
        _mcp(DOCS_CONN, "Docs", agent="architect"),
    ]

    analyst_factory = _connections(
        FakeClient(YOU, [_spec("web_search")]), FakeClient(DOCS_CONN, [_spec("lookup")])
    )
    analyst = _build(connections=connections, connection=analyst_factory, agent="data_analyst")

    assert _names(analyst) == ["web_search"]
    assert analyst.failures == ()
    assert analyst_factory.built == [YOU]
    assert analyst_factory.by_name[DOCS_CONN].list_calls == 0

    architect_factory = _connections(
        FakeClient(YOU, [_spec("web_search")]), FakeClient(DOCS_CONN, [_spec("lookup")])
    )
    architect = _build(connections=connections, connection=architect_factory, agent="architect")

    assert _names(architect) == ["lookup"]
    assert architect.failures == ()
    assert architect_factory.built == [DOCS_CONN]
    assert architect_factory.by_name[YOU].list_calls == 0


def test_a_connection_entry_without_agent_goes_to_the_analyst():
    """A stored ``mcp`` entry from before agent mode has no ``agent``: it is the data
    analyst's."""
    entry = MCPTool.model_validate(
        {"type": "mcp", "connection_name": YOU, "server_name": "Web Search"}
    )

    analyst_factory = _connections(FakeClient(YOU, [_spec("web_search")]))
    analyst = _build(connections=[entry], connection=analyst_factory, agent="data_analyst")

    assert _names(analyst) == ["web_search"]
    assert analyst.failures == ()

    architect_factory = _connections(FakeClient(YOU, [_spec("web_search")]))
    architect = _build(connections=[entry], connection=architect_factory, agent="architect")

    assert architect.tools == ()
    assert architect.failures == ()
    assert architect_factory.calls == []


def test_the_first_entry_per_connection_name_wins():
    """A connection stored twice is bound once, as its first entry (its server name and
    description): it is listed once, and its tools are not doubled or renamed."""
    factory = _connections(FakeClient(YOU, [_spec("web_search", "Search the web.")]))

    build = _build(
        connections=[
            _mcp(YOU, "Web Search", description="First."),
            _mcp(YOU, "Another name", description="Second."),
        ],
        connection=factory,
    )

    assert [tool.name for tool in build.tools] == ["web_search"]
    assert build.tools[0].description == "Web Search: First.\n\nSearch the web."
    assert factory.built == [YOU]
    assert factory.by_name[YOU].list_calls == 1
    assert build.failures == ()


def test_a_connection_named_like_a_gateway_service_is_skipped_with_a_warning(caplog):
    """Sources are keyed by name, so a connection whose name is one of the Gateway
    entries' service names is skipped (logged as a warning, never shown to the user).
    The Gateway service keeps its tools and stays a Gateway source; the other
    connections still bind."""
    gateway = _gateway(FakeClient(GITHUB, [_spec("create_issue")]))
    connection = _connections(
        FakeClient(GITHUB, [_spec("connection_tool")]), FakeClient(WEB, [_spec("search")])
    )

    with caplog.at_level(logging.WARNING):
        build = _build(
            entries=[_entry(GITHUB, "GitHub")],
            registry={GITHUB: _conn(GITHUB, "GitHub", agent="architect")},
            connections=[
                _mcp(GITHUB, "GitHub connection", agent="architect"),
                _mcp(WEB, "Web", agent="architect"),
            ],
            gateway=gateway,
            connection=connection,
            agent="architect",
        )

    assert _names(build) == ["create_issue", "search"]
    assert build.failures == ()
    assert gateway.built == [GITHUB]
    assert connection.built == [WEB]
    assert connection.by_name[GITHUB].list_calls == 0
    assert any(
        record.levelno >= logging.WARNING and GITHUB in record.getMessage()
        for record in caplog.records
    ), [record.getMessage() for record in caplog.records]
    # The Gateway service is not mistaken for a connection.
    assert GITHUB not in build.connection_keys
    assert WEB in build.connection_keys

    by_name = {tool.name: tool for tool in build.tools}
    assert _run(by_name["create_issue"]) == spotlight("GitHub", "answer from " + GITHUB)
    assert gateway.by_name[GITHUB].calls == [("create_issue", {})]


# ---------------------------------------------------------------------------
# How a connection is bound
# ---------------------------------------------------------------------------


def test_connection_factory_gets_the_connection_name():
    """The connection's client is built by ``connection_client_factory`` as the
    signed-in user (host, token, the token's scopes), for ``entry.connection_name``.
    The Gateway service's client is still built by ``client_factory``."""
    token = _jwt({"sub": USER, "scope": "ai-gateway mcp.external sql"})
    gateway = _gateway(FakeClient(GITHUB, [_spec("create_issue")]))
    connection = _connections(FakeClient(YOU, [_spec("web_search")]))

    build = _build(
        entries=[_entry(GITHUB, "GitHub")],
        registry={GITHUB: _conn(GITHUB, "GitHub", agent="data_analyst")},
        connections=[_mcp(YOU, "Web Search")],
        gateway=gateway,
        connection=connection,
        token=token,
    )

    assert _names(build) == ["create_issue", "web_search"]
    (call,) = connection.calls
    assert call["service_name"] == YOU
    assert {key: call.get(key) for key in ("host", "token", "service_name", "token_scopes")} == {
        "host": HOST,
        "token": token,
        "service_name": YOU,
        "token_scopes": frozenset({"ai-gateway", "mcp.external", "sql"}),
    }
    assert gateway.built == [GITHUB]


def test_the_default_connection_client_calls_the_uc_proxy(monkeypatch):
    """Without ``connection_client_factory`` the connection's client is
    ``ConnectionMcpClient``: its MCP client is built on the UC proxy path
    ``/api/2.0/mcp/external/<connection>``, never the Gateway's path."""
    built: list[tuple[str, str, str]] = []

    class FakeMcpClient:
        async def _get_tools_async(self) -> list[Tool]:
            return [Tool(name="web_search", description="Search.", inputSchema={"type": "object"})]

        async def _call_tools_async(self, tool_name: str, arguments: Any = None) -> Any:
            return _text_result("hits for " + str((arguments or {}).get("query")))

    def fake_build_user_mcp_client(host: str, token: str, path: str) -> FakeMcpClient:
        built.append((host, token, path))
        return FakeMcpClient()

    monkeypatch.setattr(gateway_mcp, "build_user_mcp_client", fake_build_user_mcp_client)

    build = build_gateway_tools(
        [],
        agent="data_analyst",
        registry={},
        host=HOST,
        token=TOKEN,
        user=USER,
        on_call=lambda line: None,
        session_id="session-1",
        connections=(_mcp(YOU, "Web Search"),),
    )

    assert build.failures == ()
    (tool,) = build.tools
    assert tool.name == "web_search"
    assert _run(tool, {"query": "lakehouse"}) == spotlight("Web Search", "hits for lakehouse")
    assert built == [(HOST, TOKEN, "/api/2.0/mcp/external/you-web-search-mcp")]


def test_a_connection_tool_runs_on_its_connection_under_its_server_name():
    """The connection's display name is ``entry.server_name``: the progress line and the
    spotlight source name it, and the call reaches the connection's client by the
    tool's own name."""
    progress: list[str] = []
    web = FakeClient(YOU, [_spec("web_search")])

    build = _build(
        connections=[_mcp(YOU, "Web Search")], connection=_connections(web), on_call=progress.append
    )

    (tool,) = build.tools
    out = _run(tool, {"query": "lakehouse"})

    assert web.calls == [("web_search", {"query": "lakehouse"})]
    assert out == spotlight("Web Search", "answer from " + YOU)
    assert progress == ["Web Search " + DOT + " web_search"]


def test_a_connections_description_heads_each_tool_description():
    """The entry's ``description`` is the source's instructions: it heads every tool's
    description, after the server name. Without one, only the server name does."""
    factory = _connections(
        FakeClient(YOU, [_spec("web_search", "Search the web."), _spec("fetch", "Fetch a page.")])
    )

    build = _build(
        connections=[_mcp(YOU, "Web Search", description="Use for web facts")], connection=factory
    )

    assert len(build.tools) == 2
    assert all(
        tool.description.startswith("Web Search: Use for web facts") for tool in build.tools
    ), [tool.description for tool in build.tools]
    by_name = {tool.name: tool for tool in build.tools}
    assert by_name["web_search"].description == "Web Search: Use for web facts\n\nSearch the web."
    assert by_name["fetch"].description == "Web Search: Use for web facts\n\nFetch a page."

    plain = _build(
        connections=[_mcp(YOU, "Web Search")],
        connection=_connections(FakeClient(YOU, [_spec("web_search", "Search the web.")])),
    )

    assert plain.tools[0].description == "Web Search: Search the web."


def test_a_connection_has_no_allowlist():
    """A connection binds every tool it lists (each listed name once)."""
    factory = _connections(
        FakeClient(
            YOU,
            [_spec("web_search"), _spec("news_search"), _spec("fetch"), _spec("web_search")],
        )
    )

    build = _build(connections=[_mcp(YOU, "Web Search")], connection=factory)

    assert [tool.name for tool in build.tools] == ["web_search", "news_search", "fetch"]


def test_a_connection_listing_zero_tools_binds_and_reports_nothing():
    """Review Focus 2: a server that lists no tools is listed, binds nothing and is not
    a failure; the build does not raise."""
    factory = _connections(FakeClient(YOU, []))

    build = _build(connections=[_mcp(YOU, "Web Search")], connection=factory)

    assert build.tools == ()
    assert build.failures == ()
    assert factory.by_name[YOU].list_calls == 1


# ---------------------------------------------------------------------------
# The scope pre-flight is the Gateway's alone
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "scope",
    ["sql mcp.external offline_access", "sql offline_access"],
    ids=["with_mcp_external", "without_mcp_external"],
)
def test_connections_bind_when_the_token_lacks_ai_gateway(scope: str):
    """A token whose scopes are known and lack ``ai-gateway``: the Gateway entry is one
    ``missing_scope`` failure (no Gateway client built), and the connection is still
    listed and bound. Connections are always listed: no pre-flight of their own."""
    token = _jwt({"sub": USER, "scope": scope})
    gateway = _gateway(FakeClient(GITHUB, [_spec("create_issue")]))
    connection = _connections(FakeClient(WEB, [_spec("search")]))

    build = _build(
        entries=[_entry(GITHUB, "GitHub")],
        registry={GITHUB: _conn(GITHUB, "GitHub", agent="architect")},
        connections=[_mcp(WEB, "Web", agent="architect")],
        gateway=gateway,
        connection=connection,
        agent="architect",
        token=token,
    )

    assert _names(build) == ["search"]
    assert [
        (f.display_name, f.service_name, f.kind, f.sign_in_url, f.source) for f in build.failures
    ] == [("GitHub", GITHUB, "missing_scope", None, "gateway")]
    assert gateway.calls == []
    assert connection.built == [WEB]
    assert connection.calls[0]["token_scopes"] == frozenset(scope.split())


# ---------------------------------------------------------------------------
# Listing: one pool for both kinds
# ---------------------------------------------------------------------------


def test_gateway_services_and_connections_are_listed_in_parallel():
    """Each listing waits at a 3-party barrier: it is passed only if the Gateway service
    and both connections are listed at the same time (listing the connections after
    the Gateway pool, or in a pool of their own one by one, breaks the barrier)."""
    barrier = threading.Barrier(3, timeout=5)
    github = FakeClient(GITHUB, [_spec("create_issue")], before_list=barrier.wait)
    web = FakeClient(WEB, [_spec("search")], before_list=barrier.wait)
    docs = FakeClient(DOCS_CONN, [_spec("lookup")], before_list=barrier.wait)

    build = _build(
        entries=[_entry(GITHUB, "GitHub")],
        registry={GITHUB: _conn(GITHUB, "GitHub", agent="architect")},
        connections=[
            _mcp(WEB, "Web", agent="architect"),
            _mcp(DOCS_CONN, "Docs", agent="architect"),
        ],
        gateway=_gateway(github),
        connection=_connections(web, docs),
        agent="architect",
    )

    assert build.failures == ()
    assert _names(build) == ["create_issue", "lookup", "search"]
    assert [github.list_calls, web.list_calls, docs.list_calls] == [1, 1, 1]


# ---------------------------------------------------------------------------
# Naming: one model_tool_names call over both kinds
# ---------------------------------------------------------------------------


def test_tool_names_are_unique_across_gateway_and_connections():
    """Gateway ``c.s.github`` and connection ``web`` both list ``search``: both are
    prefixed with their slug, and each name runs its own source's ``search``."""
    github = FakeClient(GITHUB, [_spec("search", "Search issues.")])
    web = FakeClient(WEB, [_spec("search", "Search the web.")])

    build = _build(
        entries=[_entry(GITHUB, "GitHub")],
        registry={GITHUB: _conn(GITHUB, "GitHub", agent="architect")},
        connections=[_mcp(WEB, "Web", agent="architect")],
        gateway=_gateway(github),
        connection=_connections(web),
        agent="architect",
    )

    names = _names(build)
    assert len(names) == 2
    assert len(set(names)) == 2
    assert "search" not in names
    assert all(NAME_RE.fullmatch(name) for name in names), names
    assert names == ["github__search", "web__search"]

    by_name = {tool.name: tool for tool in build.tools}
    toolset = AgentToolset(tools=build.tools, max_calls=12, budget_seconds=360.0)

    assert _answer(by_name, toolset, "web__search", {"query": "q"}, "c1") == spotlight(
        "Web", "answer from " + WEB
    )
    assert web.calls == [("search", {"query": "q"})]
    assert github.calls == []

    assert _answer(by_name, toolset, "github__search", {"q": "bug"}, "c2") == spotlight(
        "GitHub", "answer from " + GITHUB
    )
    assert github.calls == [("search", {"q": "bug"})]
    assert web.calls == [("search", {"query": "q"})]


def test_a_tool_named_like_a_genie_agent_is_prefixed():
    """Task 5 names its Genie Agent tools ``genie_agent_<slug>``, so a connection (or
    Gateway) tool named ``genie_agent_...`` binds under its ``slug__``-prefixed name,
    and still calls its source by its own name."""
    web = FakeClient(WEB, [_spec("genie_agent_sales"), _spec("search")])
    github = FakeClient(GITHUB, [_spec("genie_agent_issues")])

    build = _build(
        entries=[_entry(GITHUB, "GitHub")],
        registry={GITHUB: _conn(GITHUB, "GitHub", agent="data_analyst")},
        connections=[_mcp(WEB, "Web")],
        gateway=_gateway(github),
        connection=_connections(web),
    )

    names = _names(build)
    assert names == ["github__genie_agent_issues", "search", "web__genie_agent_sales"]
    assert not [name for name in names if name.startswith("genie_agent_")]

    by_name = {tool.name: tool for tool in build.tools}
    _run(by_name["web__genie_agent_sales"], {"question": "q"})
    assert web.calls == [("genie_agent_sales", {"question": "q"})]


def test_every_name_starting_genie_agent_is_reserved():
    """Reserved: every name starting ``genie_agent_`` (and only those)."""
    docs = "main.tools.docs"

    names = model_tool_names(
        {docs: ["genie_agent_sales", "genie_agent_", "genie_agentic", "search"]}
    )

    assert names == {
        (docs, "genie_agent_sales"): "docs__genie_agent_sales",
        (docs, "genie_agent_"): "docs__genie_agent_",
        (docs, "genie_agentic"): "genie_agentic",
        (docs, "search"): "search",
    }


# ---------------------------------------------------------------------------
# Failures: source="connection", and the connection's own notices
# ---------------------------------------------------------------------------


def test_a_connection_access_denial_names_use_connection():
    """Review Focus 1: a user without USE CONNECTION is told to ask the connection's
    owner for it, not an admin for the Gateway's EXECUTE. The connection is left out;
    the build does not raise."""
    factory = _connections(FakeClient(YOU, list_error=GatewayMcpError("access_denied", "x")))

    build = _build(connections=[_mcp(YOU, "Web Search")], connection=factory)

    assert build.tools == ()
    (failure,) = build.failures
    assert failure.source == "connection"
    assert (failure.display_name, failure.service_name, failure.kind) == (
        "Web Search",
        YOU,
        "access_denied",
    )
    notice = failure_notice(failure, oauth_client_id=None)
    assert "USE CONNECTION" in notice
    assert "EXECUTE" not in notice
    assert notice == (
        "You don't have access to Web Search (you-web-search-mcp). "
        "Ask the connection's owner to grant you USE CONNECTION on it."
    )


@pytest.mark.parametrize(
    ("error_kind", "failure_kind"),
    [
        ("sign_in_required", "sign_in_required"),
        ("missing_scope", "missing_scope"),
        ("access_denied", "access_denied"),
        ("not_found", "not_found"),
        ("unavailable", "unavailable"),
        ("timeout", "unavailable"),
    ],
)
def test_connection_list_time_errors_keep_their_kind_and_are_connection_failures(
    error_kind: str, failure_kind: str
):
    """A list-time ``GatewayMcpError`` on a connection is a failure of the same kind (a
    timeout is ``unavailable``), with its message and sign-in link, marked
    ``source="connection"``; the other connection still binds."""
    url = CONN_SIGN_IN_URL if error_kind == "sign_in_required" else None
    message = "Docs said " + error_kind
    factory = _connections(
        FakeClient(DOCS_CONN, list_error=GatewayMcpError(error_kind, message, sign_in_url=url)),
        FakeClient(YOU, [_spec("web_search")]),
    )

    build = _build(
        connections=[_mcp(DOCS_CONN, "Docs"), _mcp(YOU, "Web Search")], connection=factory
    )

    assert _names(build) == ["web_search"]
    assert build.failures == (
        GatewayFailure(
            display_name="Docs",
            service_name=DOCS_CONN,
            kind=failure_kind,  # type: ignore[arg-type]
            message=message,
            sign_in_url=url,
            source="connection",
        ),
    )


def test_an_unexpected_connection_listing_error_is_an_unavailable_connection_failure():
    factory = _connections(
        FakeClient(DOCS_CONN, list_error=RuntimeError("socket closed")),
        FakeClient(YOU, [_spec("web_search")]),
    )

    build = _build(
        connections=[_mcp(DOCS_CONN, "Docs"), _mcp(YOU, "Web Search")], connection=factory
    )

    assert _names(build) == ["web_search"]
    assert [(f.display_name, f.service_name, f.kind, f.source) for f in build.failures] == [
        ("Docs", DOCS_CONN, "unavailable", "connection")
    ]


def test_access_failures_tell_a_connection_refusal_from_a_gateway_one():
    """Refusals recorded while the tools run map back to their source: a connection's
    owner key is in ``connection_keys``, so its failure is ``source="connection"`` (and
    its notice names USE CONNECTION); a Gateway service's stays ``"gateway"``."""
    github = FakeClient(
        GITHUB,
        [_spec("create_issue")],
        call_error=GatewayMcpError("access_denied", "403 Forbidden"),
    )
    web = FakeClient(
        WEB, [_spec("search")], call_error=GatewayMcpError("access_denied", "403 Forbidden")
    )
    docs = FakeClient(
        DOCS_CONN,
        [_spec("lookup")],
        call_error=GatewayMcpError(
            "sign_in_required", "Not signed in to " + DOCS_CONN, sign_in_url=CONN_SIGN_IN_URL
        ),
    )
    build = _build(
        entries=[_entry(GITHUB, "GitHub")],
        registry={GITHUB: _conn(GITHUB, "GitHub", agent="architect")},
        connections=[
            _mcp(WEB, "Web", agent="architect"),
            _mcp(DOCS_CONN, "Docs", agent="architect"),
        ],
        gateway=_gateway(github),
        connection=_connections(web, docs),
        agent="architect",
    )
    assert isinstance(build.connection_keys, frozenset)
    assert {WEB, DOCS_CONN} <= build.connection_keys
    assert GITHUB not in build.connection_keys

    by_name = {tool.name: tool for tool in build.tools}
    toolset = AgentToolset(tools=build.tools, max_calls=12, budget_seconds=360.0)
    _answer(by_name, toolset, "search", {"query": "q"}, "c1")
    _answer(by_name, toolset, "create_issue", {}, "c2")
    _answer(by_name, toolset, "lookup", {}, "c3")

    failures = build.access_failures(toolset)

    assert [
        (f.display_name, f.service_name, f.kind, f.sign_in_url, f.source) for f in failures
    ] == [
        ("Web", WEB, "access_denied", None, "connection"),
        ("GitHub", GITHUB, "access_denied", None, "gateway"),
        ("Docs", DOCS_CONN, "sign_in_required", CONN_SIGN_IN_URL, "connection"),
    ]
    assert failure_notice(failures[0], oauth_client_id=None) == (
        "You don't have access to Web (web). "
        "Ask the connection's owner to grant you USE CONNECTION on it."
    )
    assert failure_notice(failures[1], oauth_client_id=None) == (
        "You don't have access to GitHub (c.s.github). Ask an admin to grant EXECUTE on it."
    )
    assert failure_notice(failures[2], oauth_client_id=None) == (
        "To use Docs, sign in here: " + CONN_SIGN_IN_URL + " " + DASH + " then ask again."
    )


def _connection_failure(
    kind: str, *, message: str | None = None, url: str | None = None
) -> GatewayFailure:
    return GatewayFailure(
        display_name="Web Search",
        service_name=YOU,
        kind=kind,  # type: ignore[arg-type]
        message=message,
        sign_in_url=url,
        source="connection",
    )


@pytest.mark.parametrize(
    ("kind", "message", "expected"),
    [
        (
            "access_denied",
            "403 Forbidden",
            "You don't have access to Web Search (you-web-search-mcp). "
            "Ask the connection's owner to grant you USE CONNECTION on it.",
        ),
        (
            "not_found",
            "does not exist",
            "Web Search (you-web-search-mcp) was not found on this workspace. "
            "Check the connection in Catalog Explorer.",
        ),
    ],
    ids=["access_denied", "not_found"],
)
def test_connection_failure_notice_copy_exact(kind: str, message: str, expected: str):
    failure = _connection_failure(kind, message=message)

    assert failure_notice(failure, oauth_client_id="abc-123") == expected


@pytest.mark.parametrize(
    ("kind", "message", "url"),
    [
        ("sign_in_required", "Not signed in", CONN_SIGN_IN_URL),
        ("sign_in_required", "Not signed in", None),
        ("missing_scope", "missing mcp.external", None),
        ("removed", None, None),
        ("unavailable", "did not respond within 30 seconds", None),
        ("unavailable", None, None),
    ],
    ids=[
        "sign_in_with_link",
        "sign_in_without_link",
        "missing_scope",
        "removed",
        "unavailable",
        "unavailable_no_reason",
    ],
)
def test_every_other_connection_notice_is_the_gateways(
    kind: str, message: str | None, url: str | None
):
    """Only access_denied and not_found have connection wording; every other kind
    reads exactly as it does for a Gateway service."""
    failure = _connection_failure(kind, message=message, url=url)
    as_gateway = dataclasses.replace(failure, source="gateway")

    assert failure_notice(failure, oauth_client_id="abc-123") == failure_notice(
        as_gateway, oauth_client_id="abc-123"
    )


def test_a_connection_sign_in_and_missing_scope_notice_copy():
    """Two of the unchanged notices in full: the sign-in link, and the consent message
    (a token without ``mcp.external`` is a stale consent)."""
    sign_in = _connection_failure("sign_in_required", message="x", url=CONN_SIGN_IN_URL)
    scope = _connection_failure("missing_scope", message="x")

    assert failure_notice(sign_in, oauth_client_id=None) == (
        "To use Web Search, sign in here: " + CONN_SIGN_IN_URL + " " + DASH + " then ask again."
    )
    assert failure_notice(scope, oauth_client_id="abc-123") == consent_message(
        oauth_client_id="abc-123"
    )


# ---------------------------------------------------------------------------
# The surface
# ---------------------------------------------------------------------------


def test_failure_source_defaults_to_gateway_and_builds_default_to_no_connection_keys():
    """Existing callers are unchanged: a ``GatewayFailure`` built positionally from its
    five fields is a Gateway one, and a ``GatewayToolsetBuild`` without
    ``connection_keys`` has none. A build with no connections has no connection keys."""
    failure = GatewayFailure("LakeDraw", "c.s.lakedraw", "unavailable", None, None)
    assert failure.source == "gateway"
    assert dataclasses.fields(GatewayFailure)[-1].name == "source"

    assert GatewayToolsetBuild(tools=(), failures=()).connection_keys == frozenset()

    build = _build(
        entries=[_entry(GITHUB, "GitHub")],
        registry={GITHUB: _conn(GITHUB, "GitHub", agent="data_analyst")},
        gateway=_gateway(FakeClient(GITHUB, [_spec("create_issue")])),
    )
    assert _names(build) == ["create_issue"]
    assert build.connection_keys == frozenset()
