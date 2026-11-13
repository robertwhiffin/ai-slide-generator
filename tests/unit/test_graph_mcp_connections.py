# ruff: noqa: F811 — the graph_env fixture is imported, then requested by name.
"""agent-mode MCP Task 4: Unity Catalog MCP connections in the agent-mode graph.

What is pinned (task-4 brief; spec "MCP servers in the agent loop" and "Progress and
errors in chat"; rulings R4 and R9):

* **An ``mcp`` entry runs.** A deck's ``MCPTool`` entries reach the agent they are
  bound to (``agent``) through the AI Gateway pass: the architect's loop, under the
  architect's one turn budget (``ARCHITECT_GATEWAY_MAX_CALLS`` /
  ``ARCHITECT_GATEWAY_BUDGET_SECONDS``, shared by every architect pass of the turn),
  or the analyst's toolset (``ANALYST_GATEWAY_MAX_CALLS`` /
  ``ANALYST_GATEWAY_BUDGET_SECONDS``, R4), alone or beside Genie One.  The client is
  the UC connection client (``/api/2.0/mcp/external/<connection_name>``), built as
  the signed-in user.  An entry for the other agent is never listed.
* **The ``None`` rules stand.**  No user client, or a describe-only turn: nothing is
  bound and no client is built.  No ``mcp`` and no ``gateway_mcp`` entry: nothing is
  listed at all.
* **The registry is the Gateway's only.**  A deck with connections and no Gateway
  entry never reads it.  When the read fails, the connections are still bound and
  the Gateway entries are skipped, never reported "no longer available".
* **Chat.**  Progress lines are the Gateway's (``"{server_name} · {tool}"``,
  ``tool_name "gateway_mcp"``).  A sign-in refusal says the connection's link and
  marks its row ``{"sign_in_url": <url>}``.  A connection's notice key on
  ``gateway_usage[*].notified`` is ``"mcp:<connection_name>"`` (R9), the Gateway's
  stays the bare service name, and a model call that carried connection tools and
  raised says them unavailable under that prefixed key.

How the tests are built (on ``tests/unit/test_graph_gateway_mcp.py``'s harness and
``tests/fixtures/graph_tool_runtime.py``):

* ``graph_env``: a real SQLite database with the production schema; Gateway
  registry rows are real rows.
* Every MCP client the code builds (Gateway or UC connection) is faked at
  ``GatewayMcpClient`` itself (``__init__``, ``list_tools``, ``call_tool``), which
  ``ConnectionMcpClient`` subclasses, so the REAL toolset builder and the REAL tool
  run.  :class:`_Fleet` records each client's class, identity and the path its
  class would reach (its own ``_path()``).
* The model is ``FakeRuntime``; a call carrying a toolset plays tool calls through
  the runtime's own dispatcher.  Answer callbacks never assert (the node catches
  exceptions from a bound call); they play a tool only if the call carries it, and
  the test asserts afterwards.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence

import pytest

from src.api.schemas.streaming import StreamEventType
from src.api.services.session_manager import get_session_manager
from src.domain.skill_io import AnalystOutput
from src.services import gateway_mcp_registry
from src.services.agent_tools.gateway_mcp import (
    ConnectionMcpClient,
    GatewayMcpClient,
    GatewayMcpError,
    GatewayToolSpec,
)
from src.services.agent_tools.gateway_tool import GatewayMcpAgentTool
from src.services.agent_tools.gateway_toolset import (
    ANALYST_GATEWAY_BUDGET_SECONDS,
    ANALYST_GATEWAY_MAX_CALLS,
    ARCHITECT_GATEWAY_BUDGET_SECONDS,
    ARCHITECT_GATEWAY_MAX_CALLS,
)
from src.services.agent_tools.registry import GENIE_TOOL_NAME
from src.services.agent_tools.toolset import AgentToolset, ToolAccessError
from src.services.graph import nodes
from src.services.graph.state import scoped, scoped_vals
from tests.fixtures.graph_tool_runtime import (
    FakeRuntime,
    fold,
    install_runtime,
    run_architect,
    turn_state,
)
from tests.unit.conftest_graph import (  # noqa: F401 — graph_env is a fixture
    architect_build,
    graph_env,
    make_spec,
)
from tests.unit.test_data_analyst_genie_one import (
    HOST,
    Q1,
    SYNTHESIS,
    TOKEN,
    _analyst_state,
    _HarnessAbort,
    _Replay,
    _run_analyst,
    _serve,
    _set_agent_config,
    q1_replies,
)
from tests.unit.test_graph_gateway_mcp import (
    CONSENT,
    CREATE,
    EXPORT,
    GENIE_ONE_ENTRY,
    LAKEDRAW,
    LAKEDRAW_ROW,
    LAKEDRAW_TOOLS,
    SIGN_IN_URL,
    TOKEN_WITHOUT_GATEWAY,
    WEB,
    WEB_ANALYST_ROW,
    _ask_data,
    _entry,
    _loop_gave_up,
    _pinned_error,
    _register,
    _registry_reads,
    _save_images_in,
    _Service,
    _sign_in,
    _sql,
    _text_result,
    _tools_failed,
    _usage_vals,
    _web_tools,
    progress_line,
    removed_notice,
    sign_in_notice,
)

TURN = "turn-1"
REQUEST_ID = "req-mcp-connections"

#: The UC connection proxy prefix (spec, "MCP servers in the agent loop": Transport).
UC_PATH = "/api/2.0/mcp/external/"

# An analyst-bound web search connection (R5's ``you-web-search-mcp``).
YOU = "you-web-search-mcp"
YOU_SERVER = "You.com Search"
YOU_SEARCH = "you_search"
YOU_TOOLS = [
    GatewayToolSpec(
        name=YOU_SEARCH,
        description="Search the web.",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
    )
]

# An architect-bound GitHub connection (R5's per-user U2M connection), named "gh"
# so its sign-in link is the brief's.
GH = "gh"
GH_SERVER = "GitHub"
GH_SEARCH = "search_repositories"
GH_FILE = "get_file_contents"
GH_TOOLS = [
    GatewayToolSpec(
        name=GH_SEARCH,
        description="Search repositories.",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
    ),
    GatewayToolSpec(
        name=GH_FILE,
        description="Read one file of a repository.",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
    ),
]
GH_SIGN_IN_URL = "https://h/explore/connections/gh"

VECTOR_ENTRY = {
    "type": "vector_index",
    "endpoint_name": "vs-endpoint",
    "index_name": "main.docs.idx",
}


def _mcp(
    connection_name: str, server_name: str, agent: str, description: Optional[str] = None
) -> Dict[str, Any]:
    return {
        "type": "mcp",
        "connection_name": connection_name,
        "server_name": server_name,
        "description": description,
        "agent": agent,
    }


YOU_ENTRY = _mcp(YOU, YOU_SERVER, "data_analyst", "Searches the web for public facts.")
GH_ENTRY = _mcp(GH, GH_SERVER, "architect", "Reads the team's repositories.")


def connection_access_notice(name: str, connection: str) -> str:
    """Task 3's connection wording for ``access_denied`` (``failure_notice``)."""
    return (
        "You don't have access to " + name + " (" + connection + "). "
        "Ask the connection's owner to grant you USE CONNECTION on it."
    )


def _key(connection: str) -> str:
    """R9: a connection's notice key."""
    return "mcp:" + connection


# ---------------------------------------------------------------------------
# The fake MCP servers: every client the code under test builds
# ---------------------------------------------------------------------------


class _Fleet:
    """Every ``GatewayMcpClient`` (and so every ``ConnectionMcpClient``) the code under
    test builds, routed to its scripted :class:`_Service` by ``service_name``.

    ``built`` records each client's class, the identity it was built with, and the
    path its class would reach (its own ``_path()``: the Gateway's service path or
    the UC connection proxy).  A client for a server this test did not script
    aborts the test (a ``BaseException``, so no ``except Exception`` in the code
    under test can turn it into a pass)."""

    def __init__(self, *services: _Service) -> None:
        self.services = {service.service_name: service for service in services}
        self.built: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    def install(self, monkeypatch) -> "_Fleet":
        fleet = self

        def init(client, *args, **kwargs):
            name = kwargs.get("service_name")
            client._service_name = name
            record = {
                "cls": type(client),
                "host": kwargs.get("host"),
                "token": kwargs.get("token"),
                "service_name": name,
                "path": client._path(),
            }
            with fleet._lock:
                fleet.built.append(record)
            service = fleet.services.get(name)
            if service is None:
                raise _HarnessAbort(f"an MCP client was built for {name!r}")
            client._t4_service = service

        def list_tools(client, *args, **kwargs):
            return client._t4_service.list_tools()

        def call_tool(client, name, arguments, *args, **kwargs):
            return client._t4_service.call_tool(name, arguments)

        monkeypatch.setattr(GatewayMcpClient, "__init__", init)
        monkeypatch.setattr(GatewayMcpClient, "list_tools", list_tools)
        monkeypatch.setattr(GatewayMcpClient, "call_tool", call_tool)
        return self

    def built_for(self, service_name: str) -> List[Dict[str, Any]]:
        return [b for b in self.built if b["service_name"] == service_name]

    def names(self) -> List[str]:
        return [b["service_name"] for b in self.built]


def _as_user(connection: str) -> Dict[str, Any]:
    """How a UC connection's client must be built: the connection client, as the
    signed-in user, over the UC proxy."""
    return {
        "cls": ConnectionMcpClient,
        "host": HOST,
        "token": TOKEN,
        "service_name": connection,
        "path": UC_PATH + connection,
    }


def _deck(
    env,
    monkeypatch,
    *,
    entries: Sequence[Dict[str, Any]],
    rows: Sequence[Dict[str, Any]] = (),
    services: Sequence[_Service] = (),
    token: Optional[str] = TOKEN,
) -> _Fleet:
    """The owner's deck with these tool entries, registry rows and servers, and the
    user signed in with *token* (``None``: nobody is)."""
    for row in rows:
        _register(env, **row)
    _set_agent_config(env, env.session_id, {"tools": [dict(e) for e in entries]})
    if token is not None:
        _sign_in(token)
    _save_images_in(env, monkeypatch)
    return _Fleet(*services).install(monkeypatch)


def _architect(env, state: Dict[str, Any]) -> SimpleNamespace:
    return run_architect(env, state, request_id=REQUEST_ID)


def _analyst(env, **overrides) -> SimpleNamespace:
    """Run the analyst once, on the owner's turn, 5 s in."""
    t = _run_analyst(env, _analyst_state(env, turn_started_at=time.time() - 5, **overrides))
    t.info = [r["content"] for r in t.rows if r["message_type"] == "info"]
    #: Every info row but the analyst's own answer: the notices.
    t.notices = [
        r["content"]
        for r in t.rows
        if r["message_type"] == "info" and r.get("metadata") != {"agent": "data_analyst"}
    ]
    return t


def _run(env, agent: str) -> SimpleNamespace:
    if agent == "architect":
        t = _architect(env, turn_state(env))
        t.notices = list(t.info)
        return t
    return _analyst(env)


def _success(sources: Sequence[str]) -> AnalystOutput:
    return AnalystOutput(outcome="success", synthesis=SYNTHESIS, sources=list(sources))


def _answers(spec=None) -> Dict[str, Any]:
    """Each node's plain answer (no tool calls)."""
    return {
        "architect": architect_build(spec or make_spec((0, 1))),
        "data_analyst": _success([YOU_SERVER]),
    }


def _gateway_tools(call) -> List[str]:
    """The names of the Gateway-path tools (Gateway or connection) a call carries."""
    if call.toolset is None:
        return []
    return sorted(t.name for t in call.toolset.tools if isinstance(t, GatewayMcpAgentTool))


def _registry_spy(monkeypatch, *, error: Optional[BaseException] = None) -> List[Any]:
    """Record every Gateway registry read (``enabled_by_service``), wherever the node
    reaches it; with *error*, each read raises it."""
    reads: List[Any] = []

    def enabled_by_service(db, service_names, *args, **kwargs):
        reads.append(list(service_names))
        if error is not None:
            raise error
        return real(db, service_names, *args, **kwargs)

    real = gateway_mcp_registry.enabled_by_service
    monkeypatch.setattr(nodes, "enabled_by_service", enabled_by_service)
    monkeypatch.setattr(gateway_mcp_registry, "enabled_by_service", enabled_by_service)
    return reads


def _build_spy(monkeypatch) -> List[Dict[str, Any]]:
    """Record every ``build_gateway_tools`` call the node makes (then make it)."""
    calls: List[Dict[str, Any]] = []
    real = nodes.build_gateway_tools

    def build_gateway_tools(*args, **kwargs):
        calls.append(dict(kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(nodes, "build_gateway_tools", build_gateway_tools)
    return calls


# ===========================================================================
# Binding: each connection reaches the agent it is bound to
# ===========================================================================


def test_an_analyst_bound_connection_reaches_the_analysts_toolset(graph_env, monkeypatch):
    """No Genie One, one analyst-bound connection: the analyst's call carries a
    toolset of the connection's tools (the Gateway path's tool) with the analyst's
    Gateway budget (R4), the client is the UC connection client built as the user,
    the call reaches the server with the model's arguments and comes back
    spotlighted, the progress line is the Gateway's, no figure is code-built from
    it, and the run records its usage."""
    you = _Service(YOU, YOU_TOOLS, results={YOU_SEARCH: _text_result("Lakehouse adoption grew.")})
    fleet = _deck(graph_env, monkeypatch, entries=[YOU_ENTRY], services=[you])

    def answer(call):
        if call.has_tool(YOU_SEARCH):
            call.use(YOU_SEARCH, {"query": "lakehouse adoption 2026"})
        return _success([YOU_SERVER])

    runtime = install_runtime(monkeypatch, FakeRuntime(data_analyst=answer))

    t = _analyst(graph_env)

    (call,) = runtime.calls_for("data_analyst")
    assert isinstance(call.toolset, AgentToolset), "the analyst's call carries no toolset"
    assert call.tool_names == [YOU_SEARCH]
    assert all(isinstance(tool, GatewayMcpAgentTool) for tool in call.toolset.tools)
    assert call.at_start == (ANALYST_GATEWAY_MAX_CALLS, ANALYST_GATEWAY_BUDGET_SECONDS, 0)
    assert fleet.built == [_as_user(YOU)]
    assert you.calls == [(YOU_SEARCH, {"query": "lakehouse adoption 2026"})]
    assert call.tool_texts[0].startswith('<untrusted-data source="' + YOU_SERVER + '">')
    line = progress_line(YOU_SERVER, YOU_SEARCH)
    assert line == "You.com Search · you_search"
    metadata = {
        "tool_name": "gateway_mcp",
        "tool_input": {"connection": YOU_SERVER, "tool": YOU_SEARCH},
    }
    progress = [(r["content"], r["metadata"]) for r in t.rows if r["message_type"] == "tool_call"]
    assert progress == [(line, metadata)]
    events = [e for e in t.events if e.type == StreamEventType.TOOL_CALL]
    assert [(e.content, e.metadata.get("node"), e.metadata.get("tool_name")) for e in events] == [
        (line, "data_analyst", "gateway_mcp")
    ]
    assert t.updates["architect_message"] == SYNTHESIS + "\nSources: " + YOU_SERVER
    assert t.updates["analyst_figures"] == scoped(TURN, [])
    assert [(e["agent"], e["calls"], e["notified"]) for e in _usage_vals(t.updates)] == [
        ("data_analyst", 1, [])
    ]
    assert t.notices == []


def test_an_analyst_bound_connection_rides_beside_genie_one(graph_env, monkeypatch):
    """Genie One plus an analyst-bound connection: ONE toolset holding both, with
    the analyst's Gateway budget (6 / 300, R4); Genie One answers, the connection is
    called, and the figures are still code-built from Genie One's rows only."""
    you = _Service(YOU, YOU_TOOLS)
    fleet = _deck(graph_env, monkeypatch, entries=[GENIE_ONE_ENTRY, YOU_ENTRY], services=[you])
    server = _Replay(q1_replies())
    _serve(monkeypatch, server)

    def answer(call):
        if call.has_tool(GENIE_TOOL_NAME):
            call.use(GENIE_TOOL_NAME, {"question": Q1})
        if call.has_tool(YOU_SEARCH):
            call.use(YOU_SEARCH, {"query": "pickup zip code growth"})
        return _success(["Genie One", YOU_SERVER])

    runtime = install_runtime(monkeypatch, FakeRuntime(data_analyst=answer))

    t = _analyst(graph_env)

    (call,) = runtime.calls_for("data_analyst")
    assert call.tool_names == sorted([GENIE_TOOL_NAME, YOU_SEARCH])
    assert call.at_start == (ANALYST_GATEWAY_MAX_CALLS, ANALYST_GATEWAY_BUDGET_SECONDS, 0)
    assert server.asks() == [{"question": Q1}]
    assert you.calls == [(YOU_SEARCH, {"query": "pickup zip code growth"})]
    assert fleet.built == [_as_user(YOU)]
    figures = scoped_vals({"turn_id": TURN, **t.updates}, "analyst_figures")
    assert figures and all(figure["source"] == "Genie One" for figure in figures)
    assert [(e["agent"], e["calls"]) for e in _usage_vals(t.updates)] == [("data_analyst", 1)]
    assert t.notices == []


def test_an_architect_bound_connection_reaches_the_architects_loop(graph_env, monkeypatch):
    """An architect-bound connection joins the architect's Gateway pass: the call
    carries its tools under the architect's turn budget, the client is the UC
    connection client built as the user, progress lines are the Gateway's, and the
    budget is the TURN's: after a first pass (ask_data) spends 2 calls, the second
    pass starts with ``ARCHITECT_GATEWAY_MAX_CALLS - 2``."""
    gh = _Service(GH, GH_TOOLS)
    fleet = _deck(graph_env, monkeypatch, entries=[GH_ENTRY], services=[gh])
    spec = make_spec((0, 1))

    def first(call):
        if call.has_tool(GH_SEARCH):
            call.use(GH_SEARCH, {"query": "tellr"})
            call.use(GH_FILE, {"path": "README.md"})
        return _ask_data()

    def second(call):
        if call.has_tool(GH_SEARCH):
            call.use(GH_SEARCH, {"query": "tellr architecture"})
        return architect_build(spec)

    runtime = install_runtime(monkeypatch, FakeRuntime(architect=[first, second]))
    state = turn_state(graph_env)

    t1 = _architect(graph_env, state)

    (pass1,) = runtime.calls_for("architect")
    assert pass1.tool_names == sorted([GH_FILE, GH_SEARCH])
    assert all(isinstance(tool, GatewayMcpAgentTool) for tool in pass1.toolset.tools)
    assert pass1.at_start == (ARCHITECT_GATEWAY_MAX_CALLS, ARCHITECT_GATEWAY_BUDGET_SECONDS, 0)
    assert fleet.built == [_as_user(GH)]
    assert gh.calls == [(GH_SEARCH, {"query": "tellr"}), (GH_FILE, {"path": "README.md"})]
    metadata = {"tool_name": "gateway_mcp"}
    progress = [(r["content"], r["metadata"]) for r in t1.rows if r["message_type"] == "tool_call"]
    assert progress == [
        (
            progress_line(GH_SERVER, GH_SEARCH),
            dict(metadata, tool_input={"connection": GH_SERVER, "tool": GH_SEARCH}),
        ),
        (
            progress_line(GH_SERVER, GH_FILE),
            dict(metadata, tool_input={"connection": GH_SERVER, "tool": GH_FILE}),
        ),
    ]
    events = [e for e in t1.events if e.type == StreamEventType.TOOL_CALL]
    assert [(e.metadata.get("node"), e.metadata.get("tool_name")) for e in events] == [
        ("architect", "gateway_mcp"),
        ("architect", "gateway_mcp"),
    ]
    (entry,) = _usage_vals(t1.updates)
    assert (entry["agent"], entry["calls"], entry["notified"]) == ("architect", 2, [])

    state2 = fold(state, t1.updates)
    state2["architect_message"] = "The analyst found the throughput."
    t2 = _architect(graph_env, state2)

    _, pass2 = runtime.calls_for("architect")
    assert pass2.has_tool(GH_SEARCH)
    assert pass2.at_start[0] == ARCHITECT_GATEWAY_MAX_CALLS - 2
    assert t2.updates["deck_spec"].title == spec.title
    assert t2.updates["error_state"] is None
    turn = fold(state2, t2.updates)
    assert sum(e["calls"] for e in scoped_vals(turn, "gateway_usage")) == 3
    assert t1.info == [] and t2.info == []


def test_an_entry_for_the_other_agent_is_not_bound(graph_env, monkeypatch):
    """A deck with one connection per agent: the architect binds and lists ITS
    connection only, and the analyst ITS connection only; neither ever lists (or
    builds a client for) the other's, and nothing is said about it."""
    you = _Service(YOU, YOU_TOOLS)
    gh = _Service(GH, GH_TOOLS)
    fleet = _deck(graph_env, monkeypatch, entries=[YOU_ENTRY, GH_ENTRY], services=[you, gh])
    runtime = install_runtime(monkeypatch, FakeRuntime(**_answers()))

    t = _architect(graph_env, turn_state(graph_env))

    (architect_call,) = runtime.calls_for("architect")
    assert architect_call.tool_names == sorted([GH_FILE, GH_SEARCH])
    assert (gh.list_calls, you.list_calls) == (1, 0)
    assert fleet.names() == [GH]
    assert t.info == []

    a = _analyst(graph_env)

    (analyst_call,) = runtime.calls_for("data_analyst")
    assert analyst_call.tool_names == [YOU_SEARCH]
    assert (gh.list_calls, you.list_calls) == (1, 1)
    assert fleet.names() == [GH, YOU]
    assert a.notices == []


# ===========================================================================
# Chat: the sign-in link
# ===========================================================================


@pytest.mark.parametrize("when", ["run-time", "list-time"])
def test_a_sign_in_refusal_tells_the_user_with_the_connection_link(graph_env, monkeypatch, when):
    """The user is not signed in to the GitHub connection: at run time each of its
    tools raises ``ToolAccessError("sign_in_required", ..., sign_in_url=<link>)``
    (or the listing is refused).  The deck is still built; chat says ONE sign-in
    notice with the connection's link, and its row (both on load and on the polling
    projection) is marked ``{"sign_in_url": <link>}``."""
    err = GatewayMcpError("sign_in_required", "Not signed in to gh", sign_in_url=GH_SIGN_IN_URL)
    gh = _Service(
        GH,
        GH_TOOLS,
        list_error=err if when == "list-time" else None,
        call_error=err if when == "run-time" else None,
    )
    fleet = _deck(graph_env, monkeypatch, entries=[GH_ENTRY], services=[gh])
    spec = make_spec((0, 1))

    def answer(call):
        if call.has_tool(GH_SEARCH):
            call.use(GH_SEARCH, {"query": "tellr"})
            call.use(GH_FILE, {"path": "README.md"})
        return architect_build(spec)

    runtime = install_runtime(monkeypatch, FakeRuntime(architect=answer))

    t = _architect(graph_env, turn_state(graph_env))

    assert fleet.built == [_as_user(GH)]
    notice = sign_in_notice(GH_SERVER, GH_SIGN_IN_URL)
    assert (
        notice == "To use GitHub, sign in here: https://h/explore/connections/gh — then ask again."
    )
    assert t.info == [notice]
    (row,) = [r for r in t.rows if r["content"] == notice]
    assert (row["role"], row["message_type"], row["metadata"]) == (
        "assistant",
        "info",
        {"sign_in_url": GH_SIGN_IN_URL},
    )
    sm = get_session_manager()
    polled = [
        sm.msg_to_stream_event(m)
        for m in sm.get_messages_for_request(REQUEST_ID)
        if m["content"] == notice
    ]
    assert [(p["type"], p["metadata"]) for p in polled] == [
        ("assistant", {"sign_in_url": GH_SIGN_IN_URL})
    ]
    (loaded,) = [m for m in sm.get_messages(graph_env.session_id) if m["content"] == notice]
    assert loaded["metadata"] == {"sign_in_url": GH_SIGN_IN_URL}
    (call,) = runtime.calls_for("architect")
    if when == "run-time":
        assert [
            (type(e), e.kind, e.tool_name, e.sign_in_url) for e in call.toolset.access_errors
        ] == [
            (ToolAccessError, "sign_in_required", GH_SEARCH, GH_SIGN_IN_URL),
            (ToolAccessError, "sign_in_required", GH_FILE, GH_SIGN_IN_URL),
        ]
    else:
        assert call.toolset is None
    assert t.updates["architect_intent"] == "build"
    assert t.updates["deck_spec"].title == spec.title
    assert t.updates["error_state"] is None


# ===========================================================================
# The None rules: no user client, describe-only, no entries
# ===========================================================================


def test_no_user_client_binds_no_connection_tools(graph_env, monkeypatch):
    """Identity: a connection call runs only as the signed-in user.  Under production
    rules with no user client, neither agent binds its connection and no client is
    built (never the service principal's); the deck is still built and nothing is
    said.  Once the user is signed in, the same deck binds both: so it was the
    missing client that bound nothing."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    you = _Service(YOU, YOU_TOOLS)
    gh = _Service(GH, GH_TOOLS)
    fleet = _deck(
        graph_env, monkeypatch, entries=[YOU_ENTRY, GH_ENTRY], services=[you, gh], token=None
    )
    spec = make_spec((0, 1))
    runtime = install_runtime(monkeypatch, FakeRuntime(**_answers(spec)))

    t = _architect(graph_env, turn_state(graph_env))
    a = _analyst(graph_env)

    (architect_call,) = runtime.calls_for("architect")
    (analyst_call,) = runtime.calls_for("data_analyst")
    assert architect_call.toolset is None
    assert analyst_call.toolset is None
    assert fleet.built == []
    assert (gh.list_calls, you.list_calls) == (0, 0)
    assert t.updates["deck_spec"].title == spec.title
    assert t.updates["error_state"] is None
    assert t.info == [] and a.notices == []

    _sign_in()
    _architect(graph_env, turn_state(graph_env))
    _analyst(graph_env)

    _, signed_in_architect = runtime.calls_for("architect")
    _, signed_in_analyst = runtime.calls_for("data_analyst")
    assert signed_in_architect.tool_names == sorted([GH_FILE, GH_SEARCH])
    assert signed_in_analyst.tool_names == [YOU_SEARCH]
    assert fleet.built == [_as_user(GH), _as_user(YOU)]


@pytest.mark.parametrize("agent", ["architect", "data_analyst"])
def test_a_describe_only_turn_binds_no_connection_tools(graph_env, monkeypatch, agent):
    """The arc-review sweeper's describe-only turn has nobody to tell or to sign in:
    neither agent binds its connection or builds a client (``_gateway_user``'s rule;
    the architect also guards it itself, the analyst does not).  The same deck's
    next ordinary turn does bind it."""
    if agent == "architect":
        service, entry, tools = _Service(GH, GH_TOOLS), GH_ENTRY, sorted([GH_FILE, GH_SEARCH])
    else:
        service, entry, tools = _Service(YOU, YOU_TOOLS), YOU_ENTRY, [YOU_SEARCH]
    fleet = _deck(graph_env, monkeypatch, entries=[entry], services=[service])
    runtime = install_runtime(monkeypatch, FakeRuntime(**_answers()))
    describe_only = {"describe_only": scoped(TURN, True)}

    if agent == "architect":
        _architect(graph_env, turn_state(graph_env, **describe_only))
    else:
        _analyst(graph_env, **describe_only)

    (described,) = runtime.calls_for(agent)
    assert described.toolset is None
    assert fleet.built == [] and service.list_calls == 0

    _run(graph_env, agent)

    _, ordinary = runtime.calls_for(agent)
    assert ordinary.tool_names == tools


@pytest.mark.parametrize("agent", ["architect", "data_analyst"])
@pytest.mark.parametrize(
    "config",
    [None, {"tools": [GENIE_ONE_ENTRY]}, {"tools": [VECTOR_ENTRY]}],
    ids=["no-config", "genie-one-only", "legacy-only"],
)
def test_a_deck_without_mcp_or_gateway_entries_lists_nothing(graph_env, monkeypatch, config, agent):
    """A deck with neither an ``mcp`` nor a ``gateway_mcp`` entry: the toolset builder
    and the client factory are never called, the registry is never read, and the
    node writes no ``gateway_*`` key.  The control: the same deck with one
    connection for this agent does list it (so the spies see a listing)."""
    _sign_in()
    _save_images_in(graph_env, monkeypatch)
    fleet = _Fleet(_Service(YOU, YOU_TOOLS), _Service(GH, GH_TOOLS)).install(monkeypatch)
    builds = _build_spy(monkeypatch)
    _serve(monkeypatch, _Replay({}))
    _set_agent_config(graph_env, graph_env.session_id, config)
    runtime = install_runtime(monkeypatch, FakeRuntime(**_answers()))

    with _sql(graph_env.engine) as statements:
        t = _run(graph_env, agent)

    assert builds == []
    assert fleet.built == []
    assert _registry_reads(statements) == []
    assert [key for key in t.updates if key.startswith("gateway_")] == []
    (call,) = runtime.calls_for(agent)
    assert _gateway_tools(call) == []

    connection = GH_ENTRY if agent == "architect" else YOU_ENTRY
    tools = list((config or {}).get("tools", [])) + [connection]
    _set_agent_config(graph_env, graph_env.session_id, {"tools": tools})

    _run(graph_env, agent)

    assert len(builds) == 1
    assert fleet.names() == [connection["connection_name"]]


# ===========================================================================
# The Gateway registry is the Gateway's only
# ===========================================================================


@pytest.mark.parametrize("agent", ["architect", "data_analyst"])
def test_a_connection_only_deck_never_reads_the_gateway_registry(graph_env, monkeypatch, agent):
    """Connections are not registry rows: with no Gateway entry, the registry is never
    read (``enabled_by_service`` raises if it is, and no SQL touches its table), and
    the connection is bound."""
    reads = _registry_spy(monkeypatch, error=RuntimeError("the registry must not be read"))
    if agent == "architect":
        service, entry, tools = _Service(GH, GH_TOOLS), GH_ENTRY, sorted([GH_FILE, GH_SEARCH])
    else:
        service, entry, tools = _Service(YOU, YOU_TOOLS), YOU_ENTRY, [YOU_SEARCH]
    fleet = _deck(graph_env, monkeypatch, entries=[entry], services=[service])
    runtime = install_runtime(monkeypatch, FakeRuntime(**_answers()))

    with _sql(graph_env.engine) as statements:
        t = _run(graph_env, agent)

    assert reads == []
    assert _registry_reads(statements) == []
    (call,) = runtime.calls_for(agent)
    assert call.tool_names == tools
    assert service.list_calls == 1
    assert fleet.built == [_as_user(entry["connection_name"])]
    assert t.notices == []


@pytest.mark.parametrize("agent", ["architect", "data_analyst"])
def test_a_registry_failure_still_binds_the_connections(graph_env, monkeypatch, agent):
    """A Gateway entry plus a connection, and the registry read fails: the connection
    is still bound; the Gateway entry is skipped (never listed, no client) and NOT
    reported as "no longer available" (nor anything else)."""
    reads = _registry_spy(monkeypatch, error=RuntimeError("registry unavailable"))
    if agent == "architect":
        gateway = _Service(LAKEDRAW, LAKEDRAW_TOOLS)
        connection = _Service(GH, GH_TOOLS)
        entries = [_entry(LAKEDRAW, "LakeDraw"), GH_ENTRY]
        rows = [LAKEDRAW_ROW]
        display, tools = "LakeDraw", sorted([GH_FILE, GH_SEARCH])
    else:
        gateway = _Service(WEB, _web_tools())
        connection = _Service(YOU, YOU_TOOLS)
        entries = [_entry(WEB, "Web Search"), YOU_ENTRY]
        rows = [WEB_ANALYST_ROW]
        display, tools = "Web Search", [YOU_SEARCH]
    fleet = _deck(
        graph_env, monkeypatch, entries=entries, rows=rows, services=[gateway, connection]
    )
    runtime = install_runtime(monkeypatch, FakeRuntime(**_answers()))

    t = _run(graph_env, agent)

    assert reads, "a deck with a Gateway entry reads the registry"
    (call,) = runtime.calls_for(agent)
    assert call.tool_names == tools
    assert gateway.list_calls == 0
    assert fleet.names() == [connection.service_name]
    assert removed_notice(display) not in t.notices
    assert t.notices == []
    if agent == "architect":
        assert t.updates["error_state"] is None
    else:
        assert t.updates["architect_message"] == SYNTHESIS + "\nSources: " + YOU_SERVER


# ===========================================================================
# Notice keys (R9) and the failed bound call
# ===========================================================================


@pytest.mark.parametrize(
    "deck", ["connection-only", "beside-a-gateway-connection", "a-connection-named-consent"]
)
def test_a_connection_notice_key_is_prefixed(graph_env, monkeypatch, deck):
    """R9: a connection's notice is recorded on the pass's ``usage()["notified"]`` as
    ``"mcp:<connection_name>"``; a Gateway connection's stays its bare service name.
    The key is read back by the turn's next architect pass, which says nothing again.
    A connection named ``consent`` cannot collide with the consent marker: its own
    notice and the consent message are both said.  The notice is Task 3's
    connection wording (USE CONNECTION)."""
    name, server = (
        ("consent", "Consent Tracker")
        if deck == "a-connection-named-consent"
        else (
            GH,
            GH_SERVER,
        )
    )
    connection = _Service(
        name,
        GH_TOOLS,
        list_error=GatewayMcpError("access_denied", "User is missing USE CONNECTION on " + name),
    )
    entries: List[Dict[str, Any]] = [_mcp(name, server, "architect")]
    rows: List[Dict[str, Any]] = []
    services = [connection]
    token = TOKEN
    expected_info = [connection_access_notice(server, name)]
    expected_keys = [_key(name)]
    if deck == "beside-a-gateway-connection":
        entries.append(_entry(LAKEDRAW, "LakeDraw"))
        rows.append(LAKEDRAW_ROW)
        services.append(
            _Service(
                LAKEDRAW,
                LAKEDRAW_TOOLS,
                list_error=GatewayMcpError(
                    "sign_in_required", "You're not signed in.", sign_in_url=SIGN_IN_URL
                ),
            )
        )
        expected_info.append(sign_in_notice("LakeDraw", SIGN_IN_URL))
        expected_keys.append(LAKEDRAW)
    elif deck == "a-connection-named-consent":
        # LakeDraw is refused up front (the token lacks ai-gateway): the consent
        # message, recorded under the consent marker.
        entries.append(_entry(LAKEDRAW, "LakeDraw"))
        rows.append(LAKEDRAW_ROW)
        services.append(_Service(LAKEDRAW, LAKEDRAW_TOOLS))
        token = TOKEN_WITHOUT_GATEWAY
        expected_info.append(CONSENT)
        expected_keys.extend([LAKEDRAW, "consent"])
    _deck(graph_env, monkeypatch, entries=entries, rows=rows, services=services, token=token)
    install_runtime(
        monkeypatch, FakeRuntime(architect=[_ask_data(), architect_build(make_spec((0, 1)))])
    )
    state = turn_state(graph_env)

    t1 = _architect(graph_env, state)

    assert connection_access_notice(GH_SERVER, GH) == (
        "You don't have access to GitHub (gh). "
        "Ask the connection's owner to grant you USE CONNECTION on it."
    )
    assert sorted(t1.info) == sorted(expected_info)
    (entry,) = _usage_vals(t1.updates)
    assert sorted(entry["notified"]) == sorted(expected_keys)

    state2 = fold(state, t1.updates)
    state2["architect_message"] = "The analyst found it."
    t2 = _architect(graph_env, state2)

    assert t2.info == []
    (entry2,) = _usage_vals(t2.updates)
    assert entry2["notified"] == []


@pytest.mark.parametrize("make_error", [_pinned_error, _loop_gave_up], ids=["provider", "loop"])
@pytest.mark.parametrize("agent", ["architect", "data_analyst"])
def test_a_failed_model_call_marks_connection_owners_as_connections(
    graph_env, monkeypatch, agent, make_error
):
    """A model call carrying a connection's tools raises: ``without_tools`` claims it
    (the same call is made once more, without tools, and the turn completes), and
    the connection is said unavailable once, under the key ``"mcp:<name>"``; a
    Gateway connection bound to the same call keeps its bare key."""
    if agent == "architect":
        services = [_Service(GH, GH_TOOLS), _Service(LAKEDRAW, LAKEDRAW_TOOLS)]
        entries = [GH_ENTRY, _entry(LAKEDRAW, "LakeDraw")]
        rows = [LAKEDRAW_ROW]
        tool, args = GH_SEARCH, {"query": "tellr"}
        good: Any = architect_build(make_spec((0, 1)))
        expected_info = [_tools_failed(GH_SERVER), _tools_failed("LakeDraw")]
        expected_keys = [_key(GH), LAKEDRAW]
        expected_tools = sorted([GH_FILE, GH_SEARCH, CREATE, EXPORT])
    else:
        services = [_Service(YOU, YOU_TOOLS)]
        entries = [YOU_ENTRY]
        rows = []
        tool, args = YOU_SEARCH, {"query": "x"}
        good = _success([YOU_SERVER])
        expected_info = [_tools_failed(YOU_SERVER)]
        expected_keys = [_key(YOU)]
        expected_tools = [YOU_SEARCH]
    _deck(graph_env, monkeypatch, entries=entries, rows=rows, services=services)

    def bound(call):
        if not call.has_tool(tool):
            return good
        call.use(tool, args)
        raise make_error()

    runtime = install_runtime(monkeypatch, FakeRuntime(**{agent: [bound, good]}))

    t = _run(graph_env, agent)

    calls = runtime.calls_for(agent)
    assert calls[0].tool_names == expected_tools
    first, second = calls
    assert second.context.toolset is None
    assert second.payload == first.payload
    if agent == "architect":
        assert t.updates["architect_intent"] == "build"
        assert t.updates["error_state"] is None
    else:
        assert t.updates["architect_message"] == SYNTHESIS + "\nSources: " + YOU_SERVER
    assert sorted(t.notices) == sorted(expected_info)
    (entry,) = _usage_vals(t.updates)
    assert entry["calls"] == 1
    assert sorted(entry["notified"]) == sorted(expected_keys)
