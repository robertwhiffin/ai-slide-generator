# ruff: noqa: F811 — the conftest_graph fixture is imported, then requested by name.
"""gateway-mcp Task 6: AI Gateway MCP tools wired into the agent-mode graph.

What is pinned (task-6 brief, PLAN-CORRECTIONS C2-C4 and T6.1-T6.9):

* **The architect** binds the actor's architect Gateway tools on every attempt
  (``_assembly_context(..., toolset=...)``), out of ONE per-turn budget (12 calls /
  360 s) shared by every attempt and every architect pass of the turn, read back
  off this turn's ``gateway_usage`` entries whose ``agent`` is ``"architect"``.  No
  ``tools/list`` call starts with no budget left or 700 s into the turn
  (``turn_started_at``).  Its output's image references are reconciled (a tail typo
  fixed, an invented one removed, the user told once per slide), and every failure
  is said once per service per turn.  It writes ``gateway_usage`` and
  ``gateway_images`` on every return path, the ask_data one included.
* **The data analyst** gets its Gateway tools beside Genie One (6 calls / 300 s;
  Genie One alone stays 3 / 300 and keeps its own 3-question cap) or alone (a loop
  over the Gateway tools only, clipped by the deadline).  A Gateway refusal is never
  said as Genie One's, and the consent message is said at most once per turn.
* **The builder** reconciles each slide's HTML against the branch-only
  ``gateway_known_images`` key, which only a Gateway turn's payload carries.
* **Progress** rows and events use ``tool_name = "gateway_mcp"`` and
  ``tool_input = {"connection", "tool"}``, never the model's arguments.
* **No Gateway entry, no change** (C2): no user client, no registry read, no
  identity, no payload key and no ``gateway_*`` state key.

How the tests are built:

* ``graph_env``: a real SQLite database with the production schema.  The registry
  rows are real ``gateway_mcp_connections`` rows (``create_connection``), read back
  through ``nodes.get_db_session``; images are really saved (``image_service`` on
  the same database, ``gateway_tool.get_db_session`` pointed at it).
* The Gateway service is faked at ``GatewayMcpClient`` itself (its ``__init__``,
  ``list_tools`` and ``call_tool``), so the REAL Task 5 builder and the REAL Task 4
  tool run and the node may build its clients however Task 5 does.
* The model is a fake runtime.  When a call carries a toolset it plays tool calls
  through the runtime's own dispatcher, ``DatabricksModelAdapter._answer_tool_call``
  (budget, counting and ``access_errors`` exactly as production records them).
* Expected copy is the Global Constraints text, built by concatenation; image
  references are built as ``"{{image:" + token + "}}"``.
"""

from __future__ import annotations

import contextlib
import copy
import inspect
import json
import logging
import queue
import secrets
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence, get_type_hints

import pytest
from langchain_core.exceptions import OutputParserException
from mcp.types import CallToolResult, TextContent
from sqlalchemy import event

from src.api.schemas.streaming import StreamEventType
from src.api.services.deck_level_writer import read_deck_spec, write_deck_level_columns
from src.api.services.session_manager import get_session_manager
from src.core.scope_errors import consent_message
from src.database.models.image import ImageAsset
from src.domain.deck_spec import DeckStyle, DeckStyleComponent
from src.domain.skill_io import AnalystOutput, ArchitectOutput, DataRequest
from src.services import image_service
from src.services.agent_runtime import AgentAssemblyContext
from src.services.agent_tools import gateway_tool
from src.services.agent_tools.gateway_mcp import (
    GatewayMcpClient,
    GatewayMcpError,
    GatewayToolSpec,
)
from src.services.agent_tools.gateway_tool import GatewayMcpAgentTool
from src.services.agent_tools.registry import (
    GENIE_TOOL_NAME,
    GenieOneAgentTool,
    build_analyst_toolset,
)
from src.services.agent_tools.toolset import AgentToolset
from src.services.gateway_mcp_registry import create_connection
from src.services.graph import builder as graph_builder
from src.services.graph import nodes
from src.services.graph.event_emitter import set_chat_request_id, set_event_emitter
from src.services.graph.nodes import (
    architect_node,
    build_branch_payload,
    builder_node,
    slide_pipeline_node,
)
from src.services.graph.state import (
    _EMPTY_FOR,
    GraphState,
    scoped,
    scoped_vals,
    turn_scoped_concat,
)
from src.services.persisted_graph_release import PinnedInvocationEndpointError
from src.utils.image_utils import IMAGE_PLACEHOLDER_PATTERN
from tests.fixtures.graph_tool_runtime import (
    BUDGET_TEXT,
    ref,
)
from tests.fixtures.graph_tool_runtime import FakeRuntime as _Runtime
from tests.fixtures.graph_tool_runtime import fold as _fold
from tests.fixtures.graph_tool_runtime import install_runtime as _install
from tests.fixtures.graph_tool_runtime import with_slides as _with_slides
from tests.fixtures.model_payload_keys import ARCHITECT_MODEL_KEYS, BUILDER_MODEL_KEYS
from tests.unit.conftest_graph import (  # noqa: F401 — graph_env is a fixture
    DEFAULT_STYLE,
    _fake_db,
    architect_build,
    builder_out,
    finding,
    fixer_out,
    graph_env,
    make_spec,
    review_out,
)
from tests.unit.test_data_analyst_genie_one import (
    APP_CLIENT_ID,
    GRANT_MESSAGE,
    HOST,
    Q1,
    Q2,
    REQUEST,
    SYNTHESIS,
    TOKEN,
    _analyst_state,
    _ask,
    _HarnessAbort,
    _jwt,
    _Replay,
    _run_analyst,
    _serve,
    _set_agent_config,
    q1_replies,
    q2_replies,
    recorded_missing_scope_exception,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "gateway_mcp"

TURN = "turn-1"
REQUEST_ID = "req-gateway-mcp"
#: ``graph_env.state()``'s ``initiated_by``: the turn's user, who owns its images (C4).
USER = "graph-user@example.com"

LAKEDRAW = "db_tellr_dev_workspace_catalog.tellr_mcp.lakedraw"
WEB = "system.ai.web_search"
CREATE = "lakedraw_create_from_spec"
EXPORT = "lakedraw_export_diagram"
SIGN_IN_URL = HOST + "/mcp-service-login?name=" + LAKEDRAW + "&o=1234567890123456"

#: U+00B7 and U+2014, as the Global Constraints copy has them.
DOT = "·"
DASH = "—"


# ---------------------------------------------------------------------------
# Exact copy (Global Constraints), built by concatenation
# ---------------------------------------------------------------------------


def progress_line(name: str, tool: str) -> str:
    return name + " " + DOT + " " + tool


def sign_in_notice(name: str, url: str) -> str:
    return "To use " + name + ", sign in here: " + url + " " + DASH + " then ask again."


def access_notice(name: str, service: str) -> str:
    return (
        "You don't have access to " + name + " (" + service + "). "
        "Ask an admin to grant EXECUTE on it."
    )


def removed_notice(name: str) -> str:
    return name + " is no longer available."


def not_found_notice(name: str, service: str) -> str:
    return (
        name + " (" + service + ") was not found on this workspace. "
        "Ask an admin to check the connection."
    )


def unavailable_notice(name: str, reason: str) -> str:
    return name + " is unavailable right now (" + reason + "). The deck was built without it."


def image_notice(slide: int) -> str:
    return "An image from a connected tool couldn't be placed on slide " + str(slide) + "."


IMAGE_NOTICE_UNNUMBERED = "An image from a connected tool couldn't be placed."
IMAGE_NOTICE_PREFIX = "An image from a connected tool couldn't be placed"

CONSENT = consent_message(oauth_client_id=APP_CLIENT_ID)
#: A JWT naming the app's client whose scopes are known and lack ai-gateway.
TOKEN_WITHOUT_GATEWAY = _jwt({"client_id": APP_CLIENT_ID, "scope": "sql offline_access"})


def new_token() -> str:
    """A token shaped like a real image token (``secrets.token_urlsafe(32)``: 43 chars)."""
    return secrets.token_urlsafe(32)


#: Invented references: 43 characters, sharing no 12-character prefix with anything.
INVENTED = "Z" * 43
INVENTED_2 = "Y" * 43


# ---------------------------------------------------------------------------
# Recorded and doc-sourced Gateway shapes
# ---------------------------------------------------------------------------


def _fixture(name: str) -> Dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def _web_tools() -> List[GatewayToolSpec]:
    """The recorded ``system.ai.web_search`` tools/list (one tool: ``web_search``)."""
    tools = _fixture("web_search_tools_list")["body_json"]["result"]["tools"]
    return [
        GatewayToolSpec(name=t["name"], description=t["description"], input_schema=t["inputSchema"])
        for t in tools
    ]


def _web_result() -> CallToolResult:
    return CallToolResult.model_validate(_fixture("web_search_call")["body_json"]["result"])


def _export_result() -> CallToolResult:
    """LakeDraw's doc-sourced export: one PNG as ImageContent AND as data_base64."""
    return CallToolResult.model_validate(_fixture("lakedraw_export_doc")["result"])


LAKEDRAW_TOOLS = [
    GatewayToolSpec(
        name=CREATE,
        description="Create an architecture diagram from a node/edge spec.",
        input_schema={"type": "object", "properties": {"diagram_data": {"type": "object"}}},
    ),
    GatewayToolSpec(
        name=EXPORT,
        description="Export a saved diagram as an image.",
        input_schema={"type": "object", "properties": {"diagram_id": {"type": "string"}}},
    ),
]


def _text_result(text: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], isError=False)


# ---------------------------------------------------------------------------
# The fake Gateway: GatewayMcpClient itself, per service
# ---------------------------------------------------------------------------


class _Service:
    """One Gateway MCP service.  ``list_tools`` raises ``list_error`` or returns
    ``tools``; ``call_tool`` records ``(name, args)`` and raises ``call_error`` or
    returns ``results[name]`` (default: a text block naming the tool)."""

    def __init__(
        self,
        service_name: str,
        tools: Sequence[GatewayToolSpec] = (),
        *,
        list_error: Optional[BaseException] = None,
        call_error: Optional[BaseException] = None,
        results: Optional[Dict[str, CallToolResult]] = None,
        on_call: Any = None,
    ) -> None:
        self.service_name = service_name
        self.tools = list(tools)
        self.list_error = list_error
        self.call_error = call_error
        self.results = dict(results or {})
        self.on_call = on_call
        self.list_calls = 0
        self.calls: List[tuple] = []
        self._lock = threading.Lock()

    def list_tools(self) -> List[GatewayToolSpec]:
        with self._lock:
            self.list_calls += 1
        if self.list_error is not None:
            raise self.list_error
        return list(self.tools)

    def call_tool(self, name: str, arguments: Any) -> Any:
        self.calls.append((name, copy.deepcopy(dict(arguments))))
        if self.on_call is not None:
            self.on_call(name, arguments)
        if self.call_error is not None:
            raise self.call_error
        result = self.results.get(name)
        return result if result is not None else _text_result(f"{name} done")


class _Gateway:
    """Every ``GatewayMcpClient`` the code under test builds, routed to its service.

    ``built`` records the identity each client was built with.  A client for a
    service this test did not script aborts the test (a ``BaseException``, so no
    ``except Exception`` in the code under test can turn it into a pass)."""

    def __init__(self, *services: _Service) -> None:
        self.services = {service.service_name: service for service in services}
        self.built: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    def install(self, monkeypatch) -> "_Gateway":
        gateway = self

        def init(client, *args, **kwargs):
            service_name = kwargs.get("service_name")
            with gateway._lock:
                gateway.built.append(
                    {
                        "host": kwargs.get("host"),
                        "token": kwargs.get("token"),
                        "service_name": service_name,
                    }
                )
            service = gateway.services.get(service_name)
            if service is None:
                raise _HarnessAbort(f"a Gateway client was built for {service_name!r}")
            client._t6_service = service

        def list_tools(client, *args, **kwargs):
            return client._t6_service.list_tools()

        def call_tool(client, name, arguments, *args, **kwargs):
            return client._t6_service.call_tool(name, arguments)

        monkeypatch.setattr(GatewayMcpClient, "__init__", init)
        monkeypatch.setattr(GatewayMcpClient, "list_tools", list_tools)
        monkeypatch.setattr(GatewayMcpClient, "call_tool", call_tool)
        return self

    def built_for(self, service_name: str) -> List[Dict[str, Any]]:
        return [b for b in self.built if b["service_name"] == service_name]

    @property
    def list_calls(self) -> int:
        return sum(service.list_calls for service in self.services.values())


# ---------------------------------------------------------------------------
# Decks, registry rows, identity
# ---------------------------------------------------------------------------


def _entry(service_name: str, display_name: str) -> Dict[str, Any]:
    return {"type": "gateway_mcp", "service_name": service_name, "display_name": display_name}


GENIE_ONE_ENTRY = {"type": "genie_one"}
LEGACY_GENIE_ENTRY = {"type": "genie", "space_id": "space-1", "space_name": "Sales"}

LAKEDRAW_ROW = dict(
    service_name=LAKEDRAW,
    display_name="LakeDraw",
    agent="architect",
    instructions="Validate the spec, then persist it.",
)
WEB_ARCHITECT_ROW = dict(service_name=WEB, display_name="Web Search", agent="architect")
WEB_ANALYST_ROW = dict(service_name=WEB, display_name="Web Search", agent="data_analyst")


def _register(
    env,
    *,
    service_name: str,
    display_name: str,
    agent: str,
    instructions: Optional[str] = None,
    allowlist: Optional[Sequence[str]] = None,
    enabled: bool = True,
) -> None:
    db = env.factory()
    try:
        create_connection(
            db,
            service_name=service_name,
            display_name=display_name,
            description=None,
            agent=agent,
            instructions=instructions,
            tool_allowlist=allowlist,
            enabled=enabled,
            user="admin@example.com",
        )
    finally:
        db.close()


def _sign_in(token: str = TOKEN, host: str = HOST) -> None:
    from src.core.databricks_client import set_user_client

    set_user_client(SimpleNamespace(config=SimpleNamespace(host=host, token=token)))


def _save_images_in(env, monkeypatch) -> None:
    """Gateway images are saved for real, in the graph's own database."""
    monkeypatch.setattr(gateway_tool, "get_db_session", _fake_db(env.factory))


def _gateway_deck(
    env,
    monkeypatch,
    *,
    entries: Sequence[Dict[str, Any]],
    rows: Sequence[Dict[str, Any]] = (),
    services: Sequence[_Service] = (),
    token: Optional[str] = TOKEN,
) -> _Gateway:
    """The owner's deck with these tool entries, registry rows and services, and the
    user signed in with *token* (``None``: nobody is)."""
    for row in rows:
        _register(env, **row)
    _set_agent_config(env, env.session_id, {"tools": [dict(e) for e in entries]})
    if token is not None:
        _sign_in(token)
    _save_images_in(env, monkeypatch)
    return _Gateway(*services).install(monkeypatch)


def _state(env, **overrides) -> Dict[str, Any]:
    """The owner's turn as ``invoke_graph`` hands it over, 5 s in."""
    state = env.state(
        root_session_id=env.session_id,
        actor_session_id=env.session_id,
        turn_started_at=time.time() - 5,
    )
    state.update(overrides)
    return state


def _architect(env, state: Dict[str, Any]) -> SimpleNamespace:
    """Run ``architect_node`` once under an emitter and a request id."""
    sm = get_session_manager()
    before = len(sm.get_messages(state["session_id"]))
    emitter: queue.Queue = queue.Queue()
    set_event_emitter(emitter)
    set_chat_request_id(REQUEST_ID)
    try:
        updates = architect_node(state)
    finally:
        set_event_emitter(None)
        set_chat_request_id(None)
    events = []
    while not emitter.empty():
        events.append(emitter.get_nowait())
    rows = sm.get_messages(state["session_id"])[before:]
    return SimpleNamespace(
        updates=updates,
        events=events,
        rows=rows,
        info=[row["content"] for row in rows if row["message_type"] == "info"],
    )


def _info(rows: Sequence[Dict[str, Any]]) -> List[str]:
    return [row["content"] for row in rows if row["message_type"] == "info"]


def _image_notices(texts: Sequence[str]) -> List[str]:
    return [text for text in texts if text.startswith(IMAGE_NOTICE_PREFIX)]


def _usage_vals(updates: Dict[str, Any]) -> List[Dict[str, Any]]:
    usage = updates["gateway_usage"]
    assert isinstance(usage, dict) and usage.get("turn") == TURN, usage
    return list(usage["vals"])


def _architect_calls(vals: Sequence[Dict[str, Any]]) -> int:
    return sum(entry["calls"] for entry in vals if entry["agent"] == "architect")


@contextlib.contextmanager
def _sql(engine):
    """Every SQL statement run on *engine* inside the block."""
    statements: List[str] = []

    def before(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", before)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", before)


def _registry_reads(statements: Sequence[str]) -> List[str]:
    return [s for s in statements if "gateway_mcp_connections" in s]


class _IdentitySpy:
    """Records every reach for the user's identity: the user client and the image
    owner fallback.  Production rules: no client is bound, so ``get_user_client``
    raises exactly as it does in production."""

    def __init__(self, monkeypatch) -> None:
        from src.core import databricks_client

        self.calls: List[str] = []

        def get_user_client():
            self.calls.append("get_user_client")
            raise databricks_client.UserClientRequiredError("no user client (spy)")

        def resolve_requesting_user():
            self.calls.append("resolve_requesting_user")
            return None

        monkeypatch.setattr(databricks_client, "get_user_client", get_user_client)
        monkeypatch.setattr(nodes, "get_user_client", get_user_client)
        monkeypatch.setattr(image_service, "resolve_requesting_user", resolve_requesting_user)
        monkeypatch.setattr(
            nodes, "resolve_requesting_user", resolve_requesting_user, raising=False
        )


def _image_row(env, token: str) -> ImageAsset:
    db = env.factory()
    try:
        return db.query(ImageAsset).filter(ImageAsset.token == token).one()
    finally:
        db.close()


# ===========================================================================
# State: the three new keys, and invoke_graph's turn_started_at
# ===========================================================================


def test_gateway_state_keys_are_turn_scoped_lists():
    """``gateway_usage`` and ``gateway_images`` accumulate across the turn's passes
    (``turn_scoped_concat``, empty ``[]``) and a new turn starts them empty."""
    hints = get_type_hints(GraphState, include_extras=True)
    for key in ("gateway_usage", "gateway_images"):
        assert hints[key].__metadata__[0] is turn_scoped_concat, key
        assert _EMPTY_FOR[key] == [] and isinstance(_EMPTY_FOR[key], list), key
        assert scoped_vals({"turn_id": TURN}, key) == []
        assert scoped_vals({"turn_id": "turn-2", key: scoped(TURN, ["x"])}, key) == []
        assert scoped_vals({"turn_id": TURN, key: scoped(TURN, ["x"])}, key) == ["x"]


def test_turn_started_at_is_a_plain_single_writer_key():
    hints = get_type_hints(GraphState, include_extras=True)
    assert "turn_started_at" in hints
    assert not hasattr(hints["turn_started_at"], "__metadata__")
    assert "turn_started_at" not in _EMPTY_FOR


class _FakeCompiled:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def invoke(self, state, config):
        self.calls.append({"state": dict(state), "config": dict(config)})
        return {"ok": True}


def test_turn_started_at_written_by_invoke_graph(monkeypatch):
    """T6.1: one ``time.time()`` (epoch seconds, not monotonic) per turn, written in
    the one state dict ``invoke_graph`` builds, AFTER the caller's ``initial`` — so a
    seeded value is overwritten — and fresh on every turn."""
    fake = _FakeCompiled()
    monkeypatch.setattr(graph_builder, "_compiled_graph", fake)
    monkeypatch.setattr(graph_builder, "get_session_local", lambda: None)
    try:
        before = time.time()
        graph_builder.invoke_graph(
            "sess-gw",
            {"architect_message": "build me a deck", "turn_started_at": 1.0},
            principal="alice@example.com",
            pin_loader=lambda factory, session_id: 1,
            root_loader=lambda factory, session_id: session_id,
        )
        middle = time.time()
        graph_builder.invoke_graph(
            "sess-gw",
            {},
            principal="alice@example.com",
            pin_loader=lambda factory, session_id: 1,
            root_loader=lambda factory, session_id: session_id,
        )
        after = time.time()
    finally:
        set_event_emitter(None)
        set_chat_request_id(None)

    first, second = (call["state"] for call in fake.calls)
    assert isinstance(first["turn_started_at"], float)
    assert before <= first["turn_started_at"] <= middle
    assert middle <= second["turn_started_at"] <= after
    assert first["architect_message"] == "build me a deck"


# ===========================================================================
# No Gateway entry: exactly today's turn (C2, T6.9)
# ===========================================================================


@pytest.mark.parametrize(
    "config",
    [None, {"tools": [GENIE_ONE_ENTRY]}, {"tools": [LEGACY_GENIE_ENTRY]}],
    ids=["no-config", "genie-one-only", "legacy-tools-only"],
)
def test_architect_without_gateway_entries_runs_without_toolset(graph_env, monkeypatch, config):
    """T6.9, under production rules with no user client.  The registry holds an
    enabled architect connection the actor did NOT add.  The architect's call is
    today's: a context with no toolset and the same ids, the same payload keys; no
    user client, no registry read, no image-owner lookup, no Gateway client; no
    ``gateway_*`` key; and its output is committed untouched (no reconciliation,
    even of a reference nobody saved).  A guard: it passes before Task 6 too."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    _register(graph_env, **LAKEDRAW_ROW)
    _set_agent_config(graph_env, graph_env.session_id, config)
    gateway = _Gateway(_Service(LAKEDRAW, LAKEDRAW_TOOLS)).install(monkeypatch)
    identity = _IdentitySpy(monkeypatch)
    brief = "Logo: " + ref(INVENTED) + "."
    spec = _with_slides(make_spec((0, 1)), content_brief={0: brief})
    runtime = _install(monkeypatch, _Runtime(architect=architect_build(spec)))

    with _sql(graph_env.engine) as statements:
        t = _architect(graph_env, _state(graph_env))

    (call,) = runtime.calls_for("architect")
    assert call.context.toolset is None
    assert call.context == AgentAssemblyContext(False, graph_env.session_id, graph_env.session_id)
    assert set(call.payload) == ARCHITECT_MODEL_KEYS
    assert [key for key in t.updates if key.startswith("gateway_")] == []
    assert t.updates["deck_spec"].slide_at(0).content_brief == brief
    assert gateway.built == []
    assert identity.calls == []
    assert _registry_reads(statements) == []
    assert _image_notices(t.info) == []


def test_gateway_entries_without_a_user_client_bind_nothing(graph_env, monkeypatch):
    """Identity: a Gateway call runs only as the signed-in user.  With an entry and no
    user client (production fails closed) no client is built and the call carries
    no toolset; the deck is still built."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    lakedraw = _Service(LAKEDRAW, LAKEDRAW_TOOLS)
    gateway = _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[_entry(LAKEDRAW, "LakeDraw")],
        rows=[LAKEDRAW_ROW],
        services=[lakedraw],
        token=None,
    )
    spec = make_spec((0, 1))
    runtime = _install(monkeypatch, _Runtime(architect=architect_build(spec)))

    t = _architect(graph_env, _state(graph_env))

    (call,) = runtime.calls_for("architect")
    assert call.context.toolset is None
    assert gateway.built == [] and lakedraw.list_calls == 0
    assert t.updates["deck_spec"].title == spec.title
    assert t.updates["error_state"] is None


# ===========================================================================
# The architect: binding, the per-turn budget, the deadline
# ===========================================================================


def test_architect_binds_gateway_tools_and_records_usage(graph_env, monkeypatch):
    """A deck with LakeDraw: the ONE architect call carries a toolset of LakeDraw's
    tools (the real Gateway tool) with the full turn budget, the payload is today's,
    the client is built as the user, the calls reach the service with the model's
    arguments, and the turn records its usage and its (no) saved images."""
    lakedraw = _Service(LAKEDRAW, LAKEDRAW_TOOLS)
    gateway = _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[_entry(LAKEDRAW, "LakeDraw")],
        rows=[LAKEDRAW_ROW],
        services=[lakedraw],
    )
    spec = make_spec((0, 1))

    def answer(call):
        call.use(CREATE, {"diagram_data": {"nodes": ["ingest", "serve"]}})
        call.use(EXPORT, {"diagram_id": "dgm-1"})
        return architect_build(spec)

    runtime = _install(monkeypatch, _Runtime(architect=answer))

    t = _architect(graph_env, _state(graph_env))

    (call,) = runtime.calls_for("architect")
    assert call.context == AgentAssemblyContext(False, graph_env.session_id, graph_env.session_id)
    toolset = call.context.toolset
    assert isinstance(toolset, AgentToolset)
    assert call.tool_names == sorted([CREATE, EXPORT])
    assert all(isinstance(tool, GatewayMcpAgentTool) for tool in toolset.tools)
    assert call.at_start == (12, 360.0, 0)
    assert set(call.payload) == ARCHITECT_MODEL_KEYS
    assert gateway.built_for(LAKEDRAW) == [
        {"host": HOST, "token": TOKEN, "service_name": LAKEDRAW}
    ]
    assert lakedraw.calls == [
        (CREATE, {"diagram_data": {"nodes": ["ingest", "serve"]}}),
        (EXPORT, {"diagram_id": "dgm-1"}),
    ]
    (entry,) = _usage_vals(t.updates)
    assert entry["agent"] == "architect"
    assert entry["calls"] == 2
    assert isinstance(entry["seconds"], (int, float)) and 0 <= entry["seconds"] < 30
    assert entry["notified"] == []
    assert t.updates["gateway_images"] == scoped(TURN, [])
    assert t.updates["deck_spec"].title == spec.title
    assert t.updates["error_state"] is None
    assert t.info == []


def test_architect_retry_shares_turn_budget(graph_env, monkeypatch):
    """Attempt 1 spends 10 calls and is refused with a retryable code
    (``invalid_slide_type_binding``); the retry gets a NEW toolset holding what is
    left of the turn: 2 calls.  Its third call is refused by the budget, so the
    service saw 12 calls, and the pass records 12."""
    lakedraw = _Service(LAKEDRAW, LAKEDRAW_TOOLS)
    _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[_entry(LAKEDRAW, "LakeDraw")],
        rows=[LAKEDRAW_ROW],
        services=[lakedraw],
    )
    refused = architect_build(make_spec((0, 1), slide_type="title"))
    good = architect_build(make_spec((0, 1)))

    def first(call):
        for n in range(10):
            call.use(CREATE, {"diagram_data": {"n": n}})
        return refused

    def second(call):
        assert "rejected_edit" in call.payload
        for n in range(3):
            call.use(CREATE, {"diagram_data": {"n": 10 + n}})
        return good

    runtime = _install(monkeypatch, _Runtime(architect=[first, second]))

    t = _architect(graph_env, _state(graph_env))

    attempt1, attempt2 = runtime.calls_for("architect")
    assert attempt1.at_start == (12, 360.0, 0)
    assert attempt2.toolset is not None and attempt2.toolset is not attempt1.toolset
    max_calls, seconds, made = attempt2.at_start
    assert (max_calls, made) == (2, 0)
    assert 350.0 < seconds <= 360.0
    assert len(lakedraw.calls) == 12
    assert attempt2.tool_texts[2] == BUDGET_TEXT
    assert _architect_calls(_usage_vals(t.updates)) == 12
    assert t.updates["architect_intent"] == "build"
    assert t.updates["error_state"] is None


def test_a_retry_after_the_budget_is_spent_has_no_toolset(graph_env, monkeypatch):
    """Attempt 1 spends all 12 calls: the retry is today's call (no toolset), not a
    toolset with nothing left in it."""
    lakedraw = _Service(LAKEDRAW, LAKEDRAW_TOOLS)
    _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[_entry(LAKEDRAW, "LakeDraw")],
        rows=[LAKEDRAW_ROW],
        services=[lakedraw],
    )

    def first(call):
        for n in range(12):
            call.use(CREATE, {"diagram_data": {"n": n}})
        return architect_build(make_spec((0, 1), slide_type="title"))

    runtime = _install(
        monkeypatch, _Runtime(architect=[first, architect_build(make_spec((0, 1)))])
    )

    t = _architect(graph_env, _state(graph_env))

    attempt1, attempt2 = runtime.calls_for("architect")
    assert attempt1.at_start == (12, 360.0, 0)
    assert attempt2.context.toolset is None
    assert len(lakedraw.calls) == 12
    assert _architect_calls(_usage_vals(t.updates)) == 12


def test_a_refused_pass_still_returns_gateway_usage(graph_env, monkeypatch):
    """T6.3, the refusal return: both attempts are refused, so the turn degrades
    (``_degrade_edit``), and that return still carries what the pass spent and saved."""
    lakedraw = _Service(LAKEDRAW, LAKEDRAW_TOOLS, results={EXPORT: _export_result()})
    _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[_entry(LAKEDRAW, "LakeDraw")],
        rows=[LAKEDRAW_ROW],
        services=[lakedraw],
    )
    refused = architect_build(make_spec((0, 1), slide_type="title"))
    saved: List[str] = []

    def first(call):
        saved.extend(IMAGE_PLACEHOLDER_PATTERN.findall(call.use(EXPORT, {"diagram_id": "d"})))
        call.use(CREATE, {"diagram_data": {"n": 1}})
        return refused

    def second(call):
        call.use(CREATE, {"diagram_data": {"n": 2}})
        return refused

    runtime = _install(monkeypatch, _Runtime(architect=[first, second]))

    t = _architect(graph_env, _state(graph_env))

    assert len(runtime.calls_for("architect")) == 2
    assert t.updates["error_state"] is not None  # degraded, not built
    assert _architect_calls(_usage_vals(t.updates)) == 3
    assert len(saved) == 1
    assert t.updates["gateway_images"] == scoped(TURN, saved)


def test_the_retry_answer_is_reconciled_too(graph_env, monkeypatch):
    """T6.2: the reconcile runs on EVERY attempt's answer, before it is planned.
    Attempt 1 is refused (retryable) and invents a reference on slide 1; the retry,
    which is the answer committed, invents one on slide 2.  The committed spec has
    it removed and the user is told about slide 2 only: the refused answer's slides
    are never said."""
    lakedraw = _Service(LAKEDRAW, LAKEDRAW_TOOLS)
    _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[_entry(LAKEDRAW, "LakeDraw")],
        rows=[LAKEDRAW_ROW],
        services=[lakedraw],
    )
    refused = architect_build(
        _with_slides(
            make_spec((0, 1), slide_type="title"),
            content_brief={0: "Logo " + ref(INVENTED_2)},
        )
    )
    good = architect_build(
        _with_slides(make_spec((0, 1)), content_brief={1: "Diagram " + ref(INVENTED) + "."})
    )
    runtime = _install(monkeypatch, _Runtime(architect=[refused, good]))

    t = _architect(graph_env, _state(graph_env))

    assert len(runtime.calls_for("architect")) == 2
    assert t.updates["architect_intent"] == "build"
    committed = t.updates["deck_spec"]
    assert committed.slide_at(1).content_brief == "Diagram ."
    persisted = read_deck_spec(graph_env.session_id)
    assert all(INVENTED not in json.dumps(slide) for slide in persisted["slides"])
    assert _image_notices(t.info) == [image_notice(2)]


@pytest.mark.parametrize(
    ("prior", "expected"),
    [
        ([{"agent": "architect", "calls": 12, "seconds": 30.0, "notified": []}], None),
        (
            [
                {"agent": "architect", "calls": 6, "seconds": 10.0, "notified": []},
                {"agent": "architect", "calls": 6, "seconds": 10.0, "notified": []},
            ],
            None,
        ),
        ([{"agent": "architect", "calls": 2, "seconds": 360.0, "notified": []}], None),
        ([{"agent": "architect", "calls": 10, "seconds": 100.0, "notified": []}], (2, 260.0)),
        ([{"agent": "architect", "calls": 1, "seconds": 350.0, "notified": []}], (11, 10.0)),
        # The analyst's runs do not spend the architect's budget.
        ([{"agent": "data_analyst", "calls": 6, "seconds": 290.0, "notified": []}], (12, 360.0)),
    ],
    ids=[
        "12-calls-used",
        "two-passes-of-6",
        "360s-used",
        "10-calls-100s-used",
        "350s-used",
        "analyst-usage-only",
    ],
)
def test_second_architect_pass_in_turn_sees_prior_usage(graph_env, monkeypatch, prior, expected):
    """This turn's ``gateway_usage`` (architect entries only, summed) is what the
    pass may still spend.  With nothing left, the call carries no toolset and
    ``tools/list`` is never called (T6.4)."""
    lakedraw = _Service(LAKEDRAW, LAKEDRAW_TOOLS)
    _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[_entry(LAKEDRAW, "LakeDraw")],
        rows=[LAKEDRAW_ROW],
        services=[lakedraw],
    )
    spec = make_spec((0, 1))
    runtime = _install(monkeypatch, _Runtime(architect=architect_build(spec)))

    t = _architect(graph_env, _state(graph_env, gateway_usage=scoped(TURN, prior)))

    (call,) = runtime.calls_for("architect")
    if expected is None:
        assert call.context.toolset is None
        assert lakedraw.list_calls == 0
    else:
        calls_left, seconds_left = expected
        assert call.at_start[0] == calls_left
        assert call.at_start[1] == pytest.approx(seconds_left, abs=0.5)
        assert call.at_start[1] <= seconds_left
    assert t.updates["deck_spec"].title == spec.title


def test_a_previous_turns_usage_does_not_count(graph_env, monkeypatch):
    lakedraw = _Service(LAKEDRAW, LAKEDRAW_TOOLS)
    _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[_entry(LAKEDRAW, "LakeDraw")],
        rows=[LAKEDRAW_ROW],
        services=[lakedraw],
    )
    runtime = _install(monkeypatch, _Runtime(architect=architect_build(make_spec((0, 1)))))
    stale = scoped(
        "turn-0", [{"agent": "architect", "calls": 12, "seconds": 360.0, "notified": []}]
    )

    _architect(graph_env, _state(graph_env, gateway_usage=stale))

    (call,) = runtime.calls_for("architect")
    assert call.at_start == (12, 360.0, 0)


def test_deadline_guard_no_toolset_after_700s(graph_env, monkeypatch):
    """No Gateway call starts 700 s into the turn: past it the architect's call is
    today's (no toolset), ``tools/list`` is not called, and the deck is built."""
    lakedraw = _Service(LAKEDRAW, LAKEDRAW_TOOLS)
    _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[_entry(LAKEDRAW, "LakeDraw")],
        rows=[LAKEDRAW_ROW],
        services=[lakedraw],
    )
    spec = make_spec((0, 1))
    runtime = _install(monkeypatch, _Runtime(architect=architect_build(spec)))

    t = _architect(graph_env, _state(graph_env, turn_started_at=time.time() - 701))

    (call,) = runtime.calls_for("architect")
    assert call.context.toolset is None
    assert lakedraw.list_calls == 0
    assert lakedraw.calls == []
    assert t.updates["deck_spec"].title == spec.title
    assert t.updates["error_state"] is None


def test_deadline_clips_the_architect_budget(graph_env, monkeypatch):
    """650 s in, 50 s of the turn are left: the toolset gets that, not 360 s
    (``turn_started_at`` is epoch seconds, compared with ``time.time()``)."""
    lakedraw = _Service(LAKEDRAW, LAKEDRAW_TOOLS)
    _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[_entry(LAKEDRAW, "LakeDraw")],
        rows=[LAKEDRAW_ROW],
        services=[lakedraw],
    )
    runtime = _install(monkeypatch, _Runtime(architect=architect_build(make_spec((0, 1)))))

    _architect(graph_env, _state(graph_env, turn_started_at=time.time() - 650))

    (call,) = runtime.calls_for("architect")
    max_calls, seconds, _ = call.at_start
    assert max_calls == 12
    assert 40.0 < seconds <= 50.0


def test_an_analyst_connection_is_not_bound_to_the_architect(graph_env, monkeypatch):
    """The actor's only Gateway connection is the analyst's: the architect binds
    nothing, lists nothing and says nothing."""
    web = _Service(WEB, _web_tools())
    _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[_entry(WEB, "Web Search")],
        rows=[WEB_ANALYST_ROW],
        services=[web],
    )
    runtime = _install(monkeypatch, _Runtime(architect=architect_build(make_spec((0, 1)))))

    t = _architect(graph_env, _state(graph_env))

    (call,) = runtime.calls_for("architect")
    assert call.context.toolset is None
    assert web.list_calls == 0
    assert t.info == []


# ===========================================================================
# The ask_data return path, and once-per-turn notices across passes (T6.3, T6.4)
# ===========================================================================


def _ask_data(message: str = "I need the pipeline's throughput first.") -> ArchitectOutput:
    return ArchitectOutput(
        intent="ask_data", message=message, data_request=DataRequest(metric="throughput")
    )


def test_ask_data_pass_returns_gateway_usage(graph_env, monkeypatch):
    """T6.3: the ask_data pass returns early, and still writes the turn's Gateway
    usage, so the second architect pass (after the analyst) starts from what is
    left: 12 - 3 = 9 calls."""
    lakedraw = _Service(LAKEDRAW, LAKEDRAW_TOOLS, results={EXPORT: _export_result()})
    _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[_entry(LAKEDRAW, "LakeDraw")],
        rows=[LAKEDRAW_ROW],
        services=[lakedraw],
    )
    saved: List[str] = []

    def first(call):
        call.use(CREATE, {"diagram_data": {"nodes": ["a"]}})
        call.use(CREATE, {"diagram_data": {"nodes": ["a", "b"]}})
        saved.extend(IMAGE_PLACEHOLDER_PATTERN.findall(call.use(EXPORT, {"diagram_id": "d"})))
        return _ask_data()

    def second(call):
        call.use(CREATE, {"diagram_data": {"nodes": ["c"]}})
        return architect_build(make_spec((0, 1)))

    runtime = _install(monkeypatch, _Runtime(architect=[first, second]))
    state = _state(graph_env)

    t1 = _architect(graph_env, state)

    assert t1.updates["architect_intent"] == "ask_data"
    assert "DATA REQUEST: " in t1.updates["architect_message"]
    (entry,) = _usage_vals(t1.updates)
    assert (entry["agent"], entry["calls"]) == ("architect", 3)
    assert len(saved) == 1
    assert t1.updates["gateway_images"] == scoped(TURN, saved)

    state2 = _fold(state, t1.updates)
    state2["architect_message"] = "The analyst found a throughput of 4,200 rows/s."
    t2 = _architect(graph_env, state2)

    _, pass2 = runtime.calls_for("architect")
    assert pass2.at_start[0] == 9
    assert _architect_calls(_usage_vals(t2.updates)) == 1
    turn = _fold(state2, t2.updates)
    assert _architect_calls(scoped_vals(turn, "gateway_usage")) == 4


@pytest.mark.parametrize(
    "case", ["list-time", "list-time-beside-a-bound-connection", "run-time"]
)
def test_notices_are_said_once_per_service_per_turn(graph_env, monkeypatch, case):
    """Two architect passes in one turn (ask_data, then build), LakeDraw refusing the
    user both times: ONE sign-in notice for the turn.  Each pass records what it
    said (``notified``) and the later pass skips it (T6.4)."""
    err = GatewayMcpError(
        "sign_in_required", "You're not signed in to LakeDraw.", sign_in_url=SIGN_IN_URL
    )
    lakedraw = _Service(
        LAKEDRAW,
        LAKEDRAW_TOOLS,
        list_error=err if case.startswith("list-time") else None,
        call_error=err if case == "run-time" else None,
    )
    entries = [_entry(LAKEDRAW, "LakeDraw")]
    rows = [LAKEDRAW_ROW]
    services = [lakedraw]
    if case == "list-time-beside-a-bound-connection":
        entries.append(_entry(WEB, "Web Search"))
        rows.append(WEB_ARCHITECT_ROW)
        services.append(_Service(WEB, _web_tools()))
    _gateway_deck(graph_env, monkeypatch, entries=entries, rows=rows, services=services)

    def play(call):
        if call.has_tool(CREATE):
            call.use(CREATE, {"diagram_data": {}})

    def first(call):
        play(call)
        return _ask_data()

    def second(call):
        play(call)
        return architect_build(make_spec((0, 1)))

    _install(monkeypatch, _Runtime(architect=[first, second]))
    state = _state(graph_env)

    t1 = _architect(graph_env, state)
    state2 = _fold(state, t1.updates)
    state2["architect_message"] = "The analyst found it."
    t2 = _architect(graph_env, state2)

    notice = sign_in_notice("LakeDraw", SIGN_IN_URL)
    assert t1.info.count(notice) == 1
    assert t2.info.count(notice) == 0
    assert any(LAKEDRAW in entry["notified"] for entry in _usage_vals(t1.updates))


# ===========================================================================
# Chat notices: sign-in, removed, every list-time failure, the scope pre-flight
# ===========================================================================


@pytest.mark.parametrize("when", ["list-time", "run-time"])
def test_sign_in_failure_says_notice_and_turn_continues(graph_env, monkeypatch, when):
    """Review Focus 2: a user not signed in to LakeDraw asks for a deck.  The deck is
    still built and chat carries ONE sign-in notice with the link, visible to the
    polling transport, whether the refusal came at list time (the connection is
    left out of the run) or on each of two calls during it."""
    err = GatewayMcpError(
        "sign_in_required", "You're not signed in to LakeDraw.", sign_in_url=SIGN_IN_URL
    )
    lakedraw = _Service(
        LAKEDRAW,
        LAKEDRAW_TOOLS,
        list_error=err if when == "list-time" else None,
        call_error=err if when == "run-time" else None,
    )
    _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[_entry(LAKEDRAW, "LakeDraw")],
        rows=[LAKEDRAW_ROW],
        services=[lakedraw],
    )
    spec = make_spec((0, 1))
    message = "Building your three-slide architecture deck."

    def answer(call):
        if call.toolset is not None:
            call.use(CREATE, {"diagram_data": {}})
            call.use(EXPORT, {"diagram_id": "d"})
        return architect_build(spec, message)

    runtime = _install(monkeypatch, _Runtime(architect=answer))

    t = _architect(graph_env, _state(graph_env))

    notice = sign_in_notice("LakeDraw", SIGN_IN_URL)
    assert notice == (
        "To use LakeDraw, sign in here: " + SIGN_IN_URL + " — then ask again."
    )
    assert t.info.count(notice) == 1
    (row,) = [r for r in t.rows if r["content"] == notice]
    assert (row["role"], row["message_type"]) == ("assistant", "info")
    polled = [m["content"] for m in get_session_manager().get_messages_for_request(REQUEST_ID)]
    assert polled.count(notice) == 1
    assert GRANT_MESSAGE not in t.info
    # The turn went on: the architect's own answer was committed and said.
    assert t.updates["architect_intent"] == "build"
    assert t.updates["deck_spec"].title == spec.title
    assert t.updates["error_state"] is None
    assert (message, "llm_response") in [(r["content"], r["message_type"]) for r in t.rows]
    (call,) = runtime.calls_for("architect")
    if when == "list-time":
        assert call.context.toolset is None
    else:
        assert [e.kind for e in call.toolset.access_errors] == ["sign_in_required"] * 2


@pytest.mark.parametrize("registry", ["deleted", "disabled"])
def test_removed_connection_says_no_longer_available(graph_env, monkeypatch, registry):
    """Review Focus 1: an admin removed (or disabled) a connection the deck still
    has.  The turn runs without it, says "LakeDraw is no longer available." once,
    and contacts nothing."""
    rows = [] if registry == "deleted" else [dict(LAKEDRAW_ROW, enabled=False)]
    lakedraw = _Service(LAKEDRAW, LAKEDRAW_TOOLS)
    gateway = _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[_entry(LAKEDRAW, "LakeDraw")],
        rows=rows,
        services=[lakedraw],
    )
    spec = make_spec((0, 1))
    runtime = _install(monkeypatch, _Runtime(architect=architect_build(spec)))

    t = _architect(graph_env, _state(graph_env))

    assert t.info.count(removed_notice("LakeDraw")) == 1
    assert removed_notice("LakeDraw") == "LakeDraw is no longer available."
    (call,) = runtime.calls_for("architect")
    assert call.context.toolset is None
    assert gateway.built == [] and lakedraw.list_calls == 0
    assert t.updates["deck_spec"].title == spec.title
    assert t.updates["error_state"] is None


@pytest.mark.parametrize(
    ("kind", "message", "expected"),
    [
        ("access_denied", "403 Forbidden", access_notice("LakeDraw", LAKEDRAW)),
        ("not_found", "does not exist", not_found_notice("LakeDraw", LAKEDRAW)),
        (
            "unavailable",
            "the service answered 502",
            unavailable_notice("LakeDraw", "the service answered 502"),
        ),
        (
            "timeout",
            LAKEDRAW + " did not respond within 30 seconds",
            unavailable_notice("LakeDraw", LAKEDRAW + " did not respond within 30 seconds"),
        ),
        # The consent message names the app's OAuth client from the user's token.
        ("missing_scope", "missing ai-gateway", CONSENT),
    ],
    ids=["access_denied", "not_found", "unavailable", "timeout", "missing_scope"],
)
def test_list_time_failures_say_their_exact_notice(graph_env, monkeypatch, kind, message, expected):
    lakedraw = _Service(LAKEDRAW, LAKEDRAW_TOOLS, list_error=GatewayMcpError(kind, message))
    _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[_entry(LAKEDRAW, "LakeDraw")],
        rows=[LAKEDRAW_ROW],
        services=[lakedraw],
    )
    spec = make_spec((0, 1))
    _install(monkeypatch, _Runtime(architect=architect_build(spec)))

    t = _architect(graph_env, _state(graph_env))

    assert t.info.count(expected) == 1
    assert t.updates["deck_spec"].title == spec.title


def test_a_token_without_ai_gateway_says_the_consent_message_once(graph_env, monkeypatch):
    """The user's token says its scopes and ai-gateway is not among them: no client
    is built, the call carries no toolset, and the consent message (naming the app's
    OAuth client) is said once for the deck's two connections."""
    lakedraw = _Service(LAKEDRAW, LAKEDRAW_TOOLS)
    web = _Service(WEB, _web_tools())
    gateway = _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[_entry(LAKEDRAW, "LakeDraw"), _entry(WEB, "Web Search")],
        rows=[LAKEDRAW_ROW, WEB_ARCHITECT_ROW],
        services=[lakedraw, web],
        token=TOKEN_WITHOUT_GATEWAY,
    )
    spec = make_spec((0, 1))
    runtime = _install(monkeypatch, _Runtime(architect=architect_build(spec)))

    t = _architect(graph_env, _state(graph_env))

    assert t.info.count(CONSENT) == 1
    assert APP_CLIENT_ID in CONSENT
    (call,) = runtime.calls_for("architect")
    assert call.context.toolset is None
    assert gateway.built == []
    assert t.updates["deck_spec"].title == spec.title


# ===========================================================================
# Image references in the architect's output (Review Focus 4)
# ===========================================================================


def test_architect_output_image_refs_reconciled_and_user_told(graph_env, monkeypatch):
    """The model copies the saved token correctly on slide 1, with a tail typo on
    slide 2, and invents two on slide 3.  The committed (and persisted) spec has the
    typo corrected and the invented ones removed, the user is told ONCE, naming
    slide 3, and the turn's saved token reaches the builder's payload."""
    lakedraw = _Service(LAKEDRAW, LAKEDRAW_TOOLS, results={EXPORT: _export_result()})
    _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[_entry(LAKEDRAW, "LakeDraw")],
        rows=[LAKEDRAW_ROW],
        services=[lakedraw],
    )
    saved: List[str] = []

    def answer(call):
        text = call.use(EXPORT, {"diagram_id": "dgm-1"})
        saved.extend(IMAGE_PLACEHOLDER_PATTERN.findall(text))
        (token,) = saved
        spec = _with_slides(
            make_spec((0, 1, 2)),
            content_brief={
                0: "Diagram: " + ref(token),
                1: "Same diagram, smaller: " + ref(token[:40] + "xyz"),
                2: "Logo: " + ref(INVENTED) + ".",
            },
            purpose={2: "Close with " + ref(INVENTED_2)},
        )
        return architect_build(spec)

    _install(monkeypatch, _Runtime(architect=answer))
    state = _state(graph_env)

    t = _architect(graph_env, state)

    (token,) = saved
    assert len(token) == 43
    committed = t.updates["deck_spec"]
    assert committed.slide_at(0).content_brief == "Diagram: " + ref(token)
    assert committed.slide_at(1).content_brief == "Same diagram, smaller: " + ref(token)
    assert committed.slide_at(2).content_brief == "Logo: ."
    assert committed.slide_at(2).purpose == "Close with "
    persisted = read_deck_spec(graph_env.session_id)
    by_position = sorted(persisted["slides"], key=lambda s: s["position"])
    assert [s["content_brief"] for s in by_position] == [
        "Diagram: " + ref(token),
        "Same diagram, smaller: " + ref(token),
        "Logo: .",
    ]
    assert _image_notices(t.info) == [image_notice(3)]
    assert t.updates["gateway_images"] == scoped(TURN, [token])
    # The image is a content image owned by the turn's user (C4), tagged with its service.
    row = _image_row(graph_env, token)
    assert (row.uploaded_by, row.category) == (USER, "content")
    assert row.tags == ["gateway_mcp", LAKEDRAW]
    # The builder of slide 1 may place it.
    payload = build_branch_payload(_fold(state, t.updates), 0)
    assert token in set(payload["gateway_known_images"])
    json.dumps(payload["gateway_known_images"])


def test_an_invented_ref_outside_a_slide_gets_an_unnumbered_notice(graph_env, monkeypatch):
    """A reference in the architect's message (not a slide) is removed too, and the
    notice has no slide number."""
    lakedraw = _Service(LAKEDRAW, LAKEDRAW_TOOLS)
    _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[_entry(LAKEDRAW, "LakeDraw")],
        rows=[LAKEDRAW_ROW],
        services=[lakedraw],
    )
    message = "Here is the diagram " + ref(INVENTED) + " for your deck."
    _install(monkeypatch, _Runtime(architect=architect_build(make_spec((0, 1)), message)))

    t = _architect(graph_env, _state(graph_env))

    assert INVENTED not in t.updates["architect_message"]
    assert all(INVENTED not in row["content"] for row in t.rows)
    assert _image_notices(t.info) == [IMAGE_NOTICE_UNNUMBERED]


def test_refs_already_in_the_deck_or_saved_earlier_this_turn_are_kept(graph_env, monkeypatch):
    """T6.2's known set: the persisted spec's references, the user's message, the
    committed slides' HTML and the images an earlier pass of this turn saved are all
    known; only the invented one goes (and is said, once, for slide 3)."""
    in_spec, in_message, in_html, earlier = new_token(), new_token(), new_token(), new_token()
    persisted = _with_slides(
        make_spec((0, 1, 2)), content_brief={0: "Existing logo " + ref(in_spec)}
    )
    graph_env.seed_slides(
        [
            "<div class='slide'><img src='" + ref(in_html) + "'/></div>",
            "<div class='slide'>b</div>",
            "<div class='slide'>c</div>",
        ]
    )
    write_deck_level_columns(graph_env.session_id, deck_spec=persisted.to_json())
    lakedraw = _Service(LAKEDRAW, LAKEDRAW_TOOLS)
    _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[_entry(LAKEDRAW, "LakeDraw")],
        rows=[LAKEDRAW_ROW],
        services=[lakedraw],
    )
    briefs = {
        0: "Logo " + ref(in_spec) + " and the earlier diagram " + ref(earlier),
        1: "The image the user attached: " + ref(in_message),
        2: "Reuse " + ref(in_html) + ", plus " + ref(INVENTED),
    }
    spec = _with_slides(make_spec((0, 1, 2)), content_brief=briefs)
    _install(monkeypatch, _Runtime(architect=architect_build(spec)))
    state = _state(
        graph_env,
        architect_message="Use my picture " + ref(in_message) + " on slide 2.",
        gateway_images=scoped(TURN, [earlier]),
        gateway_usage=scoped(
            TURN, [{"agent": "architect", "calls": 1, "seconds": 5.0, "notified": []}]
        ),
    )

    t = _architect(graph_env, state)

    committed = t.updates["deck_spec"]
    assert committed.slide_at(0).content_brief == briefs[0]
    assert committed.slide_at(1).content_brief == briefs[1]
    assert committed.slide_at(2).content_brief == "Reuse " + ref(in_html) + ", plus "
    assert _image_notices(t.info) == [image_notice(3)]


@pytest.mark.parametrize("initiated_by", [USER, None], ids=["initiated_by", "fallback"])
def test_images_are_owned_by_the_turns_initiator(graph_env, monkeypatch, initiated_by):
    """C4: the owner is ``state["initiated_by"]``; only without one is it
    ``image_service.resolve_requesting_user()``."""
    monkeypatch.setattr(
        image_service, "resolve_requesting_user", lambda: "fallback-user@example.com"
    )
    lakedraw = _Service(LAKEDRAW, LAKEDRAW_TOOLS, results={EXPORT: _export_result()})
    _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[_entry(LAKEDRAW, "LakeDraw")],
        rows=[LAKEDRAW_ROW],
        services=[lakedraw],
    )
    saved: List[str] = []

    def answer(call):
        saved.extend(IMAGE_PLACEHOLDER_PATTERN.findall(call.use(EXPORT, {"diagram_id": "d"})))
        return architect_build(make_spec((0, 1)))

    _install(monkeypatch, _Runtime(architect=answer))

    _architect(graph_env, _state(graph_env, initiated_by=initiated_by))

    (token,) = saved
    expected = USER if initiated_by else "fallback-user@example.com"
    assert _image_row(graph_env, token).uploaded_by == expected


# ===========================================================================
# Progress rows (T6.8)
# ===========================================================================


def test_progress_row_written_per_call(graph_env, monkeypatch):
    """Each Gateway call shows as "LakeDraw · lakedraw_create_from_spec": a
    ``tool_call`` row written BEFORE the call (``tool_name = "gateway_mcp"``,
    ``tool_input`` naming the connection and the tool, never the model's arguments),
    the matching SSE ``TOOL_CALL`` event, and the polling transport's event."""
    rows_at_call: List[int] = []
    sm = get_session_manager()

    def on_call(name, arguments):
        rows_at_call.append(
            len(
                [
                    m
                    for m in sm.get_messages(graph_env.session_id)
                    if m["message_type"] == "tool_call"
                ]
            )
        )

    lakedraw = _Service(LAKEDRAW, LAKEDRAW_TOOLS, on_call=on_call)
    _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[_entry(LAKEDRAW, "LakeDraw")],
        rows=[LAKEDRAW_ROW],
        services=[lakedraw],
    )
    secret_arg = "MODEL-ARGUMENT-SENTINEL-7f3a"

    def answer(call):
        call.use(CREATE, {"diagram_data": {"title": secret_arg}})
        call.use(CREATE, {"diagram_data": {"title": secret_arg + "-2"}})
        return architect_build(make_spec((0, 1)))

    _install(monkeypatch, _Runtime(architect=answer))

    t = _architect(graph_env, _state(graph_env))

    line = progress_line("LakeDraw", CREATE)
    assert line == "LakeDraw · lakedraw_create_from_spec"
    metadata = {
        "tool_name": "gateway_mcp",
        "tool_input": {"connection": "LakeDraw", "tool": "lakedraw_create_from_spec"},
    }
    progress = [r for r in t.rows if r["message_type"] == "tool_call"]
    assert [(r["role"], r["content"], r["metadata"]) for r in progress] == [
        ("assistant", line, metadata),
        ("assistant", line, metadata),
    ]
    assert rows_at_call == [1, 2]
    events = [e for e in t.events if e.type == StreamEventType.TOOL_CALL]
    assert [e.content for e in events] == [line, line]
    assert all(
        e.metadata.get("tool_name") == "gateway_mcp" and e.metadata.get("node") == "architect"
        for e in events
    )
    for row in t.rows:
        assert secret_arg not in row["content"]
        assert secret_arg not in json.dumps(row.get("metadata"))
    polled = [
        sm.msg_to_stream_event(m)
        for m in sm.get_messages_for_request(REQUEST_ID)
        if m["message_type"] == "tool_call"
    ]
    assert [(p["type"], p["content"], p["tool_name"], p["tool_input"]) for p in polled] == [
        ("tool_call", line, "gateway_mcp", metadata["tool_input"]),
        ("tool_call", line, "gateway_mcp", metadata["tool_input"]),
    ]


# ===========================================================================
# The data analyst
# ===========================================================================


def _success(sources: Sequence[str]) -> AnalystOutput:
    return AnalystOutput(outcome="success", synthesis=SYNTHESIS, sources=list(sources))


def _genie_replies(count: int) -> Dict[str, List[Any]]:
    """Recorded Genie One replies for *count* questions (q1, q2, q1, ...)."""
    sets = [q1_replies() if n % 2 == 0 else q2_replies() for n in range(count)]
    return {name: [reply for s in sets for reply in s[name]] for name in sets[0]}


def test_analyst_with_genie_only_unchanged_budget(graph_env, monkeypatch):
    """Genie One alone (an analyst Gateway connection is registered, but the actor did
    not add it): Genie One's own toolset, 3 questions / 300 s, today's three keys,
    no Gateway client and no registry read."""
    _register(graph_env, **WEB_ANALYST_ROW)
    _set_agent_config(graph_env, graph_env.session_id, {"tools": [GENIE_ONE_ENTRY]})
    _sign_in()
    gateway = _Gateway(_Service(WEB, _web_tools())).install(monkeypatch)
    _serve(monkeypatch, _Replay(q1_replies()))

    def answer(call):
        call.use(GENIE_TOOL_NAME, {"question": Q1})
        return _success(["Genie One"])

    runtime = _install(monkeypatch, _Runtime(data_analyst=answer))

    with _sql(graph_env.engine) as statements:
        t = _run_analyst(_analyst_state(graph_env, turn_started_at=time.time() - 5))

    (call,) = runtime.calls_for("data_analyst")
    assert call.at_start == (3, 300.0, 0)
    assert call.tool_names == [GENIE_TOOL_NAME]
    assert set(t.updates) <= {"architect_message", "analyst_figures", "analyst_rounds"}
    assert gateway.built == []
    assert _registry_reads(statements) == []


def test_build_analyst_toolset_extra_tools():
    """``extra_tools`` defaults to none (Genie One's 3 / 300 exactly as today); with
    extra tools the toolset holds both and the Gateway budget, 6 / 300."""
    from src.api.schemas.agent_config import resolve_agent_config
    from src.services.agent_tools.registry import GENIE_ONE_BUDGET_SECONDS, GENIE_ONE_MAX_QUESTIONS

    assert inspect.signature(build_analyst_toolset).parameters["extra_tools"].default == ()
    config = resolve_agent_config({"tools": [GENIE_ONE_ENTRY]})

    def build(extra):
        return build_analyst_toolset(
            config,
            host=HOST,
            token=TOKEN,
            on_question=lambda question: None,
            session_id="session-x",
            extra_tools=extra,
        )

    toolset, genie = build(())
    assert (toolset.max_calls, toolset.budget_seconds) == (
        GENIE_ONE_MAX_QUESTIONS,
        GENIE_ONE_BUDGET_SECONDS,
    ) == (3, 300.0)
    assert [tool.name for tool in toolset.tools] == [GENIE_TOOL_NAME]

    extra = SimpleNamespace(name="web_search", description="Search.", args_schema=None)
    toolset, genie = build((extra,))
    assert isinstance(genie, GenieOneAgentTool)
    assert (toolset.max_calls, toolset.budget_seconds) == (6, 300.0)
    assert {tool.name for tool in toolset.tools} == {GENIE_TOOL_NAME, "web_search"}
    assert genie in toolset.tools and extra in toolset.tools


def test_genie_one_tool_max_questions_defaults_to_unlimited():
    """T6.6: ``GenieOneAgentTool(max_questions=...)``.  Unset, every question is asked
    (today); set, a question past the cap is answered without asking Genie One and
    without a progress line."""
    answer = _ask(q1_replies(), Q1)
    asked: List[str] = []
    announced: List[str] = []

    class _Client:
        def ask(self, question, *, conversation_id=None, timeout_seconds=300):
            asked.append(question)
            return answer

    def run(tool, question):
        args = tool.args_schema.model_validate({"question": question})
        return tool.run(args, remaining_seconds=60)

    unlimited = GenieOneAgentTool(
        _Client(), conversation_id=None, on_question=announced.append, session_id=None
    )
    for n in range(5):
        run(unlimited, f"question {n}")
    assert len(asked) == 5 and len(unlimited.answers) == 5
    assert len(announced) == 5

    asked.clear()
    announced.clear()
    capped = GenieOneAgentTool(
        _Client(),
        conversation_id=None,
        on_question=announced.append,
        session_id=None,
        max_questions=2,
    )
    texts = [run(capped, f"question {n}") for n in range(3)]
    assert asked == ["question 0", "question 1"]
    assert announced == ["question 0", "question 1"]
    assert len(capped.answers) == 2
    assert isinstance(texts[2], str) and texts[2]


def test_analyst_with_gateway_tools_uses_6_calls(graph_env, monkeypatch):
    """Genie One plus an analyst Gateway connection: one toolset holding both, 6 calls
    / 300 s; the Gateway call shows its progress row; the run writes the five keys."""
    web = _Service(WEB, _web_tools(), results={"web_search": _web_result()})
    gateway = _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[GENIE_ONE_ENTRY, _entry(WEB, "Web Search")],
        rows=[WEB_ANALYST_ROW],
        services=[web],
    )
    _serve(monkeypatch, _Replay(q1_replies()))

    def answer(call):
        call.use(GENIE_TOOL_NAME, {"question": Q1})
        call.use("web_search", {"query": "Databricks AI Gateway MCP services"})
        return _success(["Genie One", "Web Search"])

    runtime = _install(monkeypatch, _Runtime(data_analyst=answer))

    t = _run_analyst(_analyst_state(graph_env, turn_started_at=time.time() - 5))

    (call,) = runtime.calls_for("data_analyst")
    assert call.at_start == (6, 300.0, 0)
    assert call.tool_names == sorted([GENIE_TOOL_NAME, "web_search"])
    assert call.payload == {"data_request": REQUEST, "deck_purpose": None}
    assert gateway.built_for(WEB) == [{"host": HOST, "token": TOKEN, "service_name": WEB}]
    assert web.calls == [("web_search", {"query": "Databricks AI Gateway MCP services"})]
    progress = [r for r in t.rows if r["message_type"] == "tool_call"]
    assert ("assistant", progress_line("Web Search", "web_search"), {
        "tool_name": "gateway_mcp",
        "tool_input": {"connection": "Web Search", "tool": "web_search"},
    }) in [(r["role"], r["content"], r["metadata"]) for r in progress]
    assert set(t.updates) == {
        "architect_message",
        "analyst_figures",
        "analyst_rounds",
        "gateway_usage",
        "gateway_images",
    }
    vals = _usage_vals(t.updates)
    assert vals and all(entry["agent"] == "data_analyst" for entry in vals)
    # Genie One's figures are still code-built from its result rows.
    assert scoped_vals({"turn_id": TURN, **t.updates}, "analyst_figures")


def test_analyst_gateway_only_runs_loop(graph_env, monkeypatch):
    """No Genie One entry, one analyst Gateway connection: the analyst still runs its
    loop, over the Gateway tools alone (6 / 300), through the one call site.  No
    figures (they are built from Genie One only), and today's prose."""
    web = _Service(WEB, _web_tools(), results={"web_search": _web_result()})
    _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[_entry(WEB, "Web Search")],
        rows=[WEB_ANALYST_ROW],
        services=[web],
    )

    def answer(call):
        call.use("web_search", {"query": "Databricks AI Gateway MCP services"})
        return _success(["Web Search"])

    runtime = _install(monkeypatch, _Runtime(data_analyst=answer))

    t = _run_analyst(_analyst_state(graph_env, turn_started_at=time.time() - 5))

    (call,) = runtime.calls_for("data_analyst")
    assert isinstance(call.toolset, AgentToolset)
    assert call.at_start == (6, 300.0, 0)
    assert call.tool_names == ["web_search"]
    assert call.context == AgentAssemblyContext(False, graph_env.session_id, graph_env.session_id)
    assert call.payload == {"data_request": REQUEST, "deck_purpose": None}
    assert len(web.calls) == 1
    assert call.tool_texts[0].startswith('<untrusted-data source="Web Search">')
    message = SYNTHESIS + "\nSources: Web Search"
    assert t.updates["architect_message"] == message
    assert t.updates["analyst_figures"] == scoped(TURN, [])
    assert t.updates["analyst_rounds"] == scoped(TURN, [{"answers": 0}])
    assert t.updates["gateway_images"] == scoped(TURN, [])
    vals = _usage_vals(t.updates)
    assert [(entry["agent"], entry["calls"]) for entry in vals] == [("data_analyst", 1)]
    progress = [r for r in t.rows if r["message_type"] == "tool_call"]
    assert [(r["content"], r["metadata"]) for r in progress] == [
        (
            progress_line("Web Search", "web_search"),
            {
                "tool_name": "gateway_mcp",
                "tool_input": {"connection": "Web Search", "tool": "web_search"},
            },
        )
    ]
    events = [e for e in t.events if e.type == StreamEventType.TOOL_CALL]
    assert [e.content for e in events] == [progress_line("Web Search", "web_search")]
    assert events[0].metadata.get("tool_name") == "gateway_mcp"
    assert events[0].metadata.get("node") == "data_analyst"
    assert _info(t.rows) == [message]


@pytest.mark.parametrize("seconds_in", [650, 701], ids=["650s", "701s"])
def test_analyst_gateway_only_budget_is_clipped_by_the_deadline(
    graph_env, monkeypatch, seconds_in
):
    """Gateway-only analyst: 650 s in, the toolset gets the turn's last 50 s; past
    700 s there is no toolset and no ``tools/list``."""
    web = _Service(WEB, _web_tools())
    _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[_entry(WEB, "Web Search")],
        rows=[WEB_ANALYST_ROW],
        services=[web],
    )
    runtime = _install(monkeypatch, _Runtime(data_analyst=_success(["Web Search"])))

    _run_analyst(_analyst_state(graph_env, turn_started_at=time.time() - seconds_in))

    (call,) = runtime.calls_for("data_analyst")
    if seconds_in == 701:
        assert call.toolset is None
        assert web.list_calls == 0
    else:
        max_calls, seconds, _ = call.at_start
        assert max_calls == 6
        assert 40.0 < seconds <= 50.0


def test_mixed_analyst_past_700s_keeps_genie_and_refuses_gateway_calls(graph_env, monkeypatch):
    """T4.7's purpose: in a mixed toolset the 700 s guard stops Gateway calls only.
    650 s in, the toolset is the full 6 / 300 (Genie One is not cut short); once the
    clock passes 700 s, a Gateway call is answered without reaching the service and
    Genie One still answers."""
    web = _Service(WEB, _web_tools())
    _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[GENIE_ONE_ENTRY, _entry(WEB, "Web Search")],
        rows=[WEB_ANALYST_ROW],
        services=[web],
    )
    server = _Replay(q1_replies())
    _serve(monkeypatch, server)
    real_time = time.time

    def answer(call):
        monkeypatch.setattr(
            gateway_tool,
            "time",
            SimpleNamespace(time=lambda: real_time() + 60, monotonic=time.monotonic),
        )
        call.use("web_search", {"query": "late"})
        call.use(GENIE_TOOL_NAME, {"question": Q1})
        return _success(["Genie One"])

    runtime = _install(monkeypatch, _Runtime(data_analyst=answer))

    _run_analyst(_analyst_state(graph_env, turn_started_at=time.time() - 650))

    (call,) = runtime.calls_for("data_analyst")
    assert call.at_start == (6, 300.0, 0)
    assert web.calls == []
    assert server.asks() == [{"question": Q1}]


def test_mixed_analyst_genie_keeps_its_3_question_cap(graph_env, monkeypatch):
    """T6.6: the mixed toolset allows 6 calls, but Genie One still asks at most 3
    questions per run; a fourth is answered without asking it."""
    web = _Service(WEB, _web_tools())
    _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[GENIE_ONE_ENTRY, _entry(WEB, "Web Search")],
        rows=[WEB_ANALYST_ROW],
        services=[web],
    )
    server = _Replay(_genie_replies(4))
    _serve(monkeypatch, server)
    questions = [Q1, Q2, "Which zip codes grew fastest?", "And the slowest?"]

    def answer(call):
        for question in questions:
            call.use(GENIE_TOOL_NAME, {"question": question})
        return _success(["Genie One"])

    runtime = _install(monkeypatch, _Runtime(data_analyst=answer))

    t = _run_analyst(_analyst_state(graph_env, turn_started_at=time.time() - 5))

    (call,) = runtime.calls_for("data_analyst")
    assert call.at_start[0] == 6
    assert [ask["question"] for ask in server.asks()] == questions[:3]
    genie_rows = [
        r["content"]
        for r in t.rows
        if r["message_type"] == "tool_call" and r["content"].startswith("Asking Genie One: ")
    ]
    assert genie_rows == ["Asking Genie One: " + q for q in questions[:3]]
    assert call.tool_texts[3] and call.tool_texts[3] != BUDGET_TEXT


def test_a_gateway_refusal_is_not_said_as_genie_ones(graph_env, monkeypatch):
    """T6.5: a Gateway tool's access refusal lands on the shared toolset's
    ``access_errors``; it is said as the Gateway notice, never as Genie One's grant
    message."""
    web = _Service(
        WEB, _web_tools(), call_error=GatewayMcpError("access_denied", "403 Forbidden")
    )
    _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[GENIE_ONE_ENTRY, _entry(WEB, "Web Search")],
        rows=[WEB_ANALYST_ROW],
        services=[web],
    )
    _serve(monkeypatch, _Replay(q1_replies()))

    def answer(call):
        call.use(GENIE_TOOL_NAME, {"question": Q1})
        call.use("web_search", {"query": "x"})
        return _success(["Genie One"])

    runtime = _install(monkeypatch, _Runtime(data_analyst=answer))

    t = _run_analyst(_analyst_state(graph_env, turn_started_at=time.time() - 5))

    (call,) = runtime.calls_for("data_analyst")
    assert [(e.kind, e.tool_name) for e in call.toolset.access_errors] == [
        ("access_denied", "web_search")
    ]
    info = _info(t.rows)
    assert GRANT_MESSAGE not in info
    assert info.count(access_notice("Web Search", WEB)) == 1


@pytest.mark.parametrize("when", ["pre-flight", "run-time"])
def test_consent_said_once_across_genie_and_gateway(graph_env, monkeypatch, when):
    """T6.5: Genie One and a Gateway connection both lack the scope — refused up front
    (the token's scopes lack ai-gateway) or each refused during the run.  The consent
    message is said once."""
    web = _Service(
        WEB,
        _web_tools(),
        call_error=GatewayMcpError("missing_scope", "missing ai-gateway")
        if when == "run-time"
        else None,
    )
    _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[GENIE_ONE_ENTRY, _entry(WEB, "Web Search")],
        rows=[WEB_ANALYST_ROW],
        services=[web],
        token=TOKEN_WITHOUT_GATEWAY if when == "pre-flight" else TOKEN,
    )
    _serve(monkeypatch, _Replay({"genie_ask": [recorded_missing_scope_exception()]}))

    def answer(call):
        if call.toolset is not None:
            call.use(GENIE_TOOL_NAME, {"question": Q1})
            call.use("web_search", {"query": "x"})
        return AnalystOutput(outcome="no_tool", reason="refused", tried_tools=["genie"])

    runtime = _install(monkeypatch, _Runtime(data_analyst=answer))

    t = _run_analyst(_analyst_state(graph_env, turn_started_at=time.time() - 5))

    (call,) = runtime.calls_for("data_analyst")
    if when == "pre-flight":
        assert call.toolset is None
    else:
        assert sorted(e.kind for e in call.toolset.access_errors) == ["missing_scope"] * 2
    # The Gateway path ran (an actor with a Gateway entry records the turn's usage).
    assert "gateway_usage" in t.updates
    assert _info(t.rows).count(CONSENT) == 1
    assert GRANT_MESSAGE not in _info(t.rows)


def test_consent_said_once_per_turn_across_architect_and_analyst(graph_env, monkeypatch):
    """T6.5, across nodes: the architect's LakeDraw and the analyst's Genie One are
    both refused for want of ai-gateway in one turn (architect, analyst, architect):
    the consent message is said once for the whole turn."""
    lakedraw = _Service(LAKEDRAW, LAKEDRAW_TOOLS)
    _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[GENIE_ONE_ENTRY, _entry(LAKEDRAW, "LakeDraw")],
        rows=[LAKEDRAW_ROW],
        services=[lakedraw],
        token=TOKEN_WITHOUT_GATEWAY,
    )
    _serve(monkeypatch, _Replay(q1_replies()))
    _install(
        monkeypatch,
        _Runtime(
            architect=[_ask_data(), architect_build(make_spec((0, 1)))],
            data_analyst=_success(["genie"]),
        ),
    )
    state = _state(graph_env)

    t1 = _architect(graph_env, state)
    state = _fold(state, t1.updates)
    analyst = _run_analyst(state)
    state = _fold(state, analyst.updates)
    t2 = _architect(graph_env, state)

    # Said by the first refusal of the turn (the architect's LakeDraw), never again.
    assert t1.info.count(CONSENT) == 1
    assert _info(analyst.rows).count(CONSENT) == 0
    assert t2.info.count(CONSENT) == 0


# ===========================================================================
# The builder: reconcile each slide's HTML (T6.7)
# ===========================================================================

#: Every key ``build_branch_payload`` writes for an unstyled deck today.
HEAD_BRANCH_KEYS = frozenset(
    {
        "session_id",
        "graph_release_id",
        "turn_id",
        "root_session_id",
        "actor_session_id",
        "initiated_by",
        "position",
        "slide_spec",
        "assumes",
        "hands_off",
        "design_contract",
        "resolved_data",
        "section_html",
        "section_css",
        "resolved_style",
        "design_system_active",
    }
)

TEMPLATE_WITH_IMAGE = (
    "<main class='deck'><section class='slide'><img src='{section}'/></section></main>"
)


def _branch_state(env, spec, *, gateway: Optional[str] = TURN, images: Sequence[str] = (), **extra):
    """The state the foreman builds payloads from.  ``gateway`` is the turn whose
    Gateway keys the state carries (``None``: none at all)."""
    state = env.state(
        deck_spec=spec,
        root_session_id=env.session_id,
        actor_session_id=env.session_id,
        resolved_style=DEFAULT_STYLE,
        design_system_active=False,
        architect_intent="build",
        deterministic_css="",
        template_layout_html="",
        turn_started_at=time.time() - 5,
    )
    if gateway is not None:
        state["gateway_images"] = scoped(gateway, list(images))
        state["gateway_usage"] = scoped(
            gateway, [{"agent": "architect", "calls": 1, "seconds": 2.0, "notified": []}]
        )
    state.update(extra)
    return state


def _run_builder(env, payload: Dict[str, Any], html: str) -> SimpleNamespace:
    env.skills.set("builder", lambda p: builder_out(p, html=html))
    before = len(env.messages())
    set_chat_request_id(REQUEST_ID)
    try:
        updates = builder_node(payload)
    finally:
        set_chat_request_id(None)
    rows = env.messages()[before:]
    return SimpleNamespace(
        html=updates["slides"]["vals"][payload["position"]]["html"],
        rows=rows,
        info=_info(rows),
    )


def test_branch_payload_carries_the_known_set_on_a_gateway_turn(graph_env):
    """The branch-only ``gateway_known_images``: this slide's spec refs, its template
    section's refs and the images the turn saved, JSON-native."""
    in_brief, in_section, saved = new_token(), new_token(), new_token()
    spec = _with_slides(
        make_spec((0, 1, 2), slide_type="title", template_section_index=0),
        content_brief={1: "Show " + ref(in_brief)},
    )
    state = _branch_state(
        graph_env,
        spec,
        images=[saved],
        template_layout_html=TEMPLATE_WITH_IMAGE.format(section=ref(in_section)),
    )

    payload = build_branch_payload(state, 1)

    assert set(payload) == HEAD_BRANCH_KEYS | {"gateway_known_images"}
    known = payload["gateway_known_images"]
    json.dumps(known)  # JSON-native (Ruling C-21): a list, never a set
    assert set(known) == {in_brief, in_section, saved}


def test_builder_html_unknown_image_removed_and_known_kept(graph_env):
    """Review Focus 4 in HTML: the spec's image and the turn's saved image are kept (a
    tail typo of the saved one corrected in place); an invented ``<img>`` goes whole,
    an invented background declaration goes, and the user is told once for the
    slide (``_surface_notice``: an info row the polling client sees)."""
    known, saved = new_token(), new_token()
    spec = _with_slides(make_spec((0, 1, 2)), content_brief={1: "Chart: " + ref(known)})
    payload = build_branch_payload(_branch_state(graph_env, spec, images=[saved]), 1)
    kept = '<img src="' + ref(known) + '" alt="kept" />'
    typo = '<img src="' + ref(saved[:40] + "xyz") + '" alt="typo" />'
    bad = '<img src="' + ref(INVENTED) + '" alt="bad" />'
    html = (
        '<div class="slide"><h2>Plan</h2>'
        + kept
        + typo
        + bad
        + "<div style=\"background-image: url('"
        + ref(INVENTED_2)
        + "'); color: red\">x</div>"
        + "<p>body</p></div>"
    )

    t = _run_builder(graph_env, payload, html)

    assert kept in t.html
    assert '<img src="' + ref(saved) + '" alt="typo" />' in t.html
    assert INVENTED not in t.html and 'alt="bad"' not in t.html
    assert INVENTED_2 not in t.html and "background-image" not in t.html
    assert IMAGE_PLACEHOLDER_PATTERN.findall(t.html) == [known, saved]
    assert "<h2>Plan</h2>" in t.html and "x</div>" in t.html and "<p>body</p>" in t.html
    notices = [r for r in t.rows if r["content"].startswith(IMAGE_NOTICE_PREFIX)]
    assert [(r["role"], r["content"], r["message_type"]) for r in notices] == [
        ("assistant", image_notice(2), "info")
    ]
    polled = [m["content"] for m in get_session_manager().get_messages_for_request(REQUEST_ID)]
    assert polled.count(image_notice(2)) == 1
    (call,) = graph_env.skills.calls_for("builder")
    assert "gateway_known_images" not in call["payload"]


def test_a_gateway_turn_with_no_saved_image_still_reconciles(graph_env):
    """The key rides on every Gateway turn's payload, saved image or not."""
    spec = make_spec((0, 1))
    payload = build_branch_payload(_branch_state(graph_env, spec, images=[]), 0)
    assert list(payload["gateway_known_images"]) == []

    t = _run_builder(
        graph_env, payload, '<div class="slide"><img src="' + ref(INVENTED) + '"/><p>a</p></div>'
    )

    assert INVENTED not in t.html and "<p>a</p>" in t.html
    assert _image_notices(t.info) == [image_notice(1)]


@pytest.mark.parametrize("case", ["no-gateway-keys", "a-previous-turns-gateway-keys"])
def test_non_gateway_branch_payload_and_builder_html_are_unchanged(graph_env, case):
    """C2/T6.7: a turn whose architect bound no Gateway (no keys, or only a previous
    turn's) builds today's payload, byte for byte, and the builder's HTML is left
    exactly as the model wrote it, invented reference and all."""
    spec = make_spec((0, 1))
    state = _branch_state(
        graph_env,
        spec,
        gateway=None if case == "no-gateway-keys" else "turn-0",
        images=[new_token()],
    )

    payload = build_branch_payload(state, 1)

    assert "gateway_known_images" not in payload
    assert set(payload) == HEAD_BRANCH_KEYS
    html = '<div class="slide"><img src="' + ref(INVENTED) + '"/><p>b</p></div>'
    t = _run_builder(graph_env, payload, html)
    assert t.html == html
    assert t.info == []


def _model_payloads(env, payload: Dict[str, Any]) -> Dict[str, str]:
    env.skills.calls.clear()
    slide_pipeline_node(payload)
    return {
        role: json.dumps(env.skills.calls_for(role)[0]["payload"], default=str)
        for role in ("builder", "build_reviewer", "fixer", "fix_reviewer")
    }


def test_the_known_set_never_reaches_a_models_payload(graph_env):
    """Branch-only, like ``one_ground``: every slide role's model payload is
    byte-identical with and without the key (the HTML carries no reference, so the
    reconcile is a no-op and only the key differs)."""
    env = graph_env
    clean = "<div class='slide'>content</div>"
    env.skills.set("builder", lambda p: builder_out(p, html=clean))
    env.skills.set(
        "build_reviewer",
        lambda p: review_out(p["position"], [finding("overflow", slide_index=p["position"])]),
    )
    env.skills.set("fixer", lambda p: fixer_out(p, html=clean))
    env.skills.set("fix_reviewer", lambda p: review_out(p["position"]))
    state = _branch_state(env, make_spec((0, 1, 2)), images=[new_token()])
    with_key = build_branch_payload(state, 1)
    assert "gateway_known_images" in with_key
    without_key = {k: v for k, v in with_key.items() if k != "gateway_known_images"}

    keyed = _model_payloads(env, with_key)
    unkeyed = _model_payloads(env, without_key)

    assert keyed == unkeyed
    for role, text in keyed.items():
        assert "gateway_known_images" not in text, role
    builder_payload = json.loads(keyed["builder"])
    assert set(builder_payload) <= BUILDER_MODEL_KEYS | {"deck_style"}


# ===========================================================================
# Final whole-branch review fixes (I1, I2, T6-1, m2, m6)
# ===========================================================================

#: The reason the "unavailable" notice gives when a model call that carried a
#: connection's tools raised (I2).  Global Constraints copy around it.
TOOLS_FAILED_REASON = "the model could not use its tools"


def _tools_failed(name: str) -> str:
    return unavailable_notice(name, TOOLS_FAILED_REASON)


def _pinned_error() -> PinnedInvocationEndpointError:
    """What the runtime raises when the provider refuses the call (e.g. a tool's raw
    ``inputSchema``): the endpoint error, naming the model endpoint."""
    return PinnedInvocationEndpointError(
        endpoint_name="databricks-claude-endpoint",
        graph_release_id=1,
        agent_definition_revision_id=1,
    )


def _loop_gave_up() -> OutputParserException:
    """What the tool loop raises when the model never calls the output schema."""
    return OutputParserException("the model did not call the output schema after 15 rounds")


def _lakedraw_deck(env, monkeypatch, **service_kwargs) -> _Service:
    lakedraw = _Service(LAKEDRAW, LAKEDRAW_TOOLS, **service_kwargs)
    _gateway_deck(
        env,
        monkeypatch,
        entries=[_entry(LAKEDRAW, "LakeDraw")],
        rows=[LAKEDRAW_ROW],
        services=[lakedraw],
    )
    return lakedraw


# ---- I1: the sign-in notice row is marked with its URL ----------------------


def test_sign_in_notice_row_carries_its_url_on_every_path(graph_env, monkeypatch):
    """I1: the chat links ONLY the server-marked sign-in notice.  The row is written
    with ``metadata = {"sign_in_url": <url>}``, and that reaches the client on both
    paths: the polling projection (``msg_to_stream_event``) and the session load
    (``get_messages``, which ``GET /api/sessions/{id}`` returns as it is)."""
    _lakedraw_deck(
        graph_env,
        monkeypatch,
        list_error=GatewayMcpError(
            "sign_in_required", "You're not signed in to LakeDraw.", sign_in_url=SIGN_IN_URL
        ),
    )
    _install(monkeypatch, _Runtime(architect=architect_build(make_spec((0, 1)))))

    t = _architect(graph_env, _state(graph_env))

    notice = sign_in_notice("LakeDraw", SIGN_IN_URL)
    (row,) = [r for r in t.rows if r["content"] == notice]
    assert (row["message_type"], row["metadata"]) == ("info", {"sign_in_url": SIGN_IN_URL})
    sm = get_session_manager()
    (polled,) = [
        sm.msg_to_stream_event(m)
        for m in sm.get_messages_for_request(REQUEST_ID)
        if m["content"] == notice
    ]
    assert (polled["type"], polled["metadata"]) == ("assistant", {"sign_in_url": SIGN_IN_URL})
    (loaded,) = [m for m in sm.get_messages(graph_env.session_id) if m["content"] == notice]
    assert loaded["metadata"] == {"sign_in_url": SIGN_IN_URL}


@pytest.mark.parametrize(
    "error",
    [
        GatewayMcpError("sign_in_required", "You're not signed in.", sign_in_url=None),
        GatewayMcpError("access_denied", "403 Forbidden"),
        GatewayMcpError("not_found", "does not exist"),
        GatewayMcpError("unavailable", "see https://h.example/status for details"),
    ],
    ids=["sign-in-without-a-url", "access_denied", "not_found", "unavailable-with-a-url"],
)
def test_no_other_notice_is_marked_with_a_sign_in_url(graph_env, monkeypatch, error):
    """Only a sign-in notice that SAYS a link is marked: every other notice row (one
    whose text carries a service-authored URL included) is written with no metadata,
    so the chat renders it as plain text."""
    _lakedraw_deck(graph_env, monkeypatch, list_error=error)
    _install(monkeypatch, _Runtime(architect=architect_build(make_spec((0, 1)))))

    t = _architect(graph_env, _state(graph_env))

    notices = [r for r in t.rows if r["message_type"] == "info"]
    assert len(notices) == 1
    assert notices[0]["metadata"] is None
    sm = get_session_manager()
    polled = [
        sm.msg_to_stream_event(m)
        for m in sm.get_messages_for_request(REQUEST_ID)
        if m["message_type"] == "info"
    ]
    assert [p["metadata"] for p in polled] == [None]


# ---- I2: a failed Gateway-bound call is made once more without the tools ---


@pytest.mark.parametrize(
    "make_error", [_pinned_error, _loop_gave_up], ids=["provider-refuses", "loop-gives-up"]
)
def test_a_failed_gateway_bound_architect_call_is_made_again_without_tools(
    graph_env, monkeypatch, caplog, make_error
):
    """I2: the call that carried LakeDraw's tools raises (the provider refused it, or
    the tool loop gave up).  It is made ONCE more, through the same call site, with
    no toolset (today's call) and the same payload; the turn completes with that
    answer; the user is told once that LakeDraw is unavailable; one WARNING names
    the exception type and never the token; and the pass records its usage."""
    _lakedraw_deck(graph_env, monkeypatch)
    spec = make_spec((0, 1))

    def bound(call):
        assert call.toolset is not None
        call.use(CREATE, {"diagram_data": {"n": 1}})
        raise make_error()

    runtime = _install(monkeypatch, _Runtime(architect=[bound, architect_build(spec)]))

    with caplog.at_level(logging.WARNING, logger=nodes.__name__):
        t = _architect(graph_env, _state(graph_env))

    first, second = runtime.calls_for("architect")
    assert first.tool_names == sorted([CREATE, EXPORT])
    assert second.context.toolset is None
    assert second.context == AgentAssemblyContext(
        False, graph_env.session_id, graph_env.session_id
    )
    assert second.payload == first.payload
    assert t.updates["architect_intent"] == "build"
    assert t.updates["deck_spec"].title == spec.title
    assert t.updates["error_state"] is None
    assert t.info == [_tools_failed("LakeDraw")]
    assert _tools_failed("LakeDraw") == (
        "LakeDraw is unavailable right now (the model could not use its tools). "
        "The deck was built without it."
    )
    (entry,) = _usage_vals(t.updates)
    assert (entry["agent"], entry["calls"], entry["notified"]) == ("architect", 1, [LAKEDRAW])
    name = type(make_error()).__name__
    warned = [
        r
        for r in caplog.records
        if r.name == nodes.__name__ and r.levelno == logging.WARNING and name in r.getMessage()
    ]
    assert len(warned) == 1
    assert TOKEN not in caplog.text


def test_each_bound_connection_is_said_unavailable_once(graph_env, monkeypatch):
    """Two architect connections bound to the failed call: one notice for each."""
    lakedraw = _Service(LAKEDRAW, LAKEDRAW_TOOLS)
    web = _Service(WEB, _web_tools())
    _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[_entry(LAKEDRAW, "LakeDraw"), _entry(WEB, "Web Search")],
        rows=[LAKEDRAW_ROW, WEB_ARCHITECT_ROW],
        services=[lakedraw, web],
    )

    def bound(call):
        assert call.has_tool(CREATE) and call.has_tool("web_search")
        raise _loop_gave_up()

    runtime = _install(
        monkeypatch, _Runtime(architect=[bound, architect_build(make_spec((0, 1)))])
    )

    t = _architect(graph_env, _state(graph_env))

    assert [call.context.toolset is None for call in runtime.calls_for("architect")] == [
        False,
        True,
    ]
    assert sorted(t.info) == sorted([_tools_failed("LakeDraw"), _tools_failed("Web Search")])
    assert t.updates["error_state"] is None


def test_a_failed_gateway_bound_retry_is_made_again_without_tools(graph_env, monkeypatch):
    """The edit retry's own bound call raises: it too is made once more without the
    tools (the same retry payload), and that answer is the turn's.  Before the fix
    the endpoint error failed the turn."""
    _lakedraw_deck(graph_env, monkeypatch)
    refused = architect_build(make_spec((0, 1), slide_type="title"))
    good = architect_build(make_spec((0, 1)))

    def first(call):
        assert call.toolset is not None
        return refused

    def retry_bound(call):
        assert call.toolset is not None and "rejected_edit" in call.payload
        raise _pinned_error()

    runtime = _install(monkeypatch, _Runtime(architect=[first, retry_bound, good]))

    t = _architect(graph_env, _state(graph_env))

    calls = runtime.calls_for("architect")
    assert [call.context.toolset is None for call in calls] == [False, False, True]
    assert calls[2].payload == calls[1].payload
    assert t.updates["architect_intent"] == "build"
    assert t.updates["error_state"] is None
    assert t.info == [_tools_failed("LakeDraw")]


def test_after_a_failed_bound_call_the_pass_binds_no_more_tools(graph_env, monkeypatch):
    """Once a call with the tools has failed, the pass's later attempts are today's
    calls: the fallback's answer is refused (retryable) and the retry carries no
    toolset; the notice is said once."""
    lakedraw = _lakedraw_deck(graph_env, monkeypatch)

    def bound(call):
        assert call.toolset is not None
        raise _pinned_error()

    refused = architect_build(make_spec((0, 1), slide_type="title"))
    good = architect_build(make_spec((0, 1)))
    runtime = _install(monkeypatch, _Runtime(architect=[bound, refused, good]))

    t = _architect(graph_env, _state(graph_env))

    calls = runtime.calls_for("architect")
    assert [call.context.toolset is None for call in calls] == [False, True, True]
    assert "rejected_edit" in calls[2].payload
    assert lakedraw.list_calls == 1
    assert t.updates["architect_intent"] == "build"
    assert t.info == [_tools_failed("LakeDraw")]


def test_the_architect_fallbacks_failure_propagates_as_today(graph_env, monkeypatch):
    """The fallback (no tools) raises too: that failure fails the turn exactly as a
    first call's always has, and nothing claims the deck was built."""
    _lakedraw_deck(graph_env, monkeypatch)

    def bound(call):
        raise _loop_gave_up()

    def fallback(call):
        assert call.toolset is None
        raise RuntimeError("the model endpoint is down")

    runtime = _install(monkeypatch, _Runtime(architect=[bound, fallback]))
    state = _state(graph_env)
    before = len(get_session_manager().get_messages(graph_env.session_id))

    with pytest.raises(RuntimeError, match="the model endpoint is down"):
        _architect(graph_env, state)

    assert len(runtime.calls_for("architect")) == 2
    rows = get_session_manager().get_messages(graph_env.session_id)[before:]
    assert _tools_failed("LakeDraw") not in _info(rows)


@pytest.mark.parametrize(
    "config",
    [None, {"tools": [GENIE_ONE_ENTRY]}],
    ids=["no-config", "genie-one-only"],
)
def test_without_gateway_entries_a_failed_architect_call_fails_the_turn(
    graph_env, monkeypatch, config
):
    """C2: a deck without a Gateway entry is unchanged; its failing call is made once
    and its error propagates."""
    _set_agent_config(graph_env, graph_env.session_id, config)

    def fails(call):
        raise _pinned_error()

    runtime = _install(monkeypatch, _Runtime(architect=fails))

    with pytest.raises(PinnedInvocationEndpointError):
        _architect(graph_env, _state(graph_env))

    assert len(runtime.calls_for("architect")) == 1


def test_a_gateway_decks_call_without_tools_still_fails_the_turn(graph_env, monkeypatch):
    """A Gateway deck whose call carried no tools (the connection failed at list
    time) is today's call: the Gateway adds no retry of its own, so a failure that
    is not a parse error is made once and fails the turn.  (An answer that does not
    parse gets the architect's own one retry: the test below and
    test_architect_parse_retry.py.)"""
    _lakedraw_deck(graph_env, monkeypatch, list_error=GatewayMcpError("unavailable", "502"))

    def fails(call):
        assert call.toolset is None
        raise _pinned_error()

    runtime = _install(monkeypatch, _Runtime(architect=fails))

    with pytest.raises(PinnedInvocationEndpointError):
        _architect(graph_env, _state(graph_env))

    assert len(runtime.calls_for("architect")) == 1


def test_a_gateway_decks_unparseable_answer_without_tools_is_asked_once_more(
    graph_env, monkeypatch
):
    """The same Gateway deck, its no-tools call answering text the parser refuses:
    the architect's parse retry makes the same call once more (still no toolset, the
    same payload) and that answer is the turn's.  The Gateway says nothing: no call
    carried its tools."""
    _lakedraw_deck(graph_env, monkeypatch, list_error=GatewayMcpError("unavailable", "502"))
    spec = make_spec((0, 1))

    def unparseable(call):
        assert call.toolset is None
        raise _loop_gave_up()

    runtime = _install(monkeypatch, _Runtime(architect=[unparseable, architect_build(spec)]))

    t = _architect(graph_env, _state(graph_env))

    first, second = runtime.calls_for("architect")
    assert second.context.toolset is None
    assert second.payload == first.payload
    assert t.updates["architect_intent"] == "build"
    assert t.updates["deck_spec"].title == spec.title
    assert t.updates["error_state"] is None
    assert _tools_failed("LakeDraw") not in t.info


def test_an_unparseable_fallback_answer_fails_the_turn(graph_env, monkeypatch):
    """The call with the tools raises and its no-tools fallback answers text the parser
    refuses: that is already the second call, so the turn fails with the parse error.
    Two calls, never three: the parse retry is for a first call, not the fallback."""
    _lakedraw_deck(graph_env, monkeypatch)

    def bound(call):
        assert call.toolset is not None
        raise _pinned_error()

    def fallback(call):
        assert call.toolset is None
        raise _loop_gave_up()

    runtime = _install(
        monkeypatch, _Runtime(architect=[bound, fallback, architect_build(make_spec((0,)))])
    )

    with pytest.raises(OutputParserException):
        _architect(graph_env, _state(graph_env))

    assert len(runtime.calls_for("architect")) == 2


def test_mixed_analyst_falls_back_to_genie_one_alone(graph_env, monkeypatch):
    """I2, the analyst with Genie One and Web Search: the call with both raises, and
    it is made once more with Genie One's own toolset exactly as before this branch
    (3 questions / 300 s, no Gateway tool).  Figures are built from that run's
    answers, and Web Search is said unavailable once."""
    web = _Service(WEB, _web_tools(), results={"web_search": _web_result()})
    _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[GENIE_ONE_ENTRY, _entry(WEB, "Web Search")],
        rows=[WEB_ANALYST_ROW],
        services=[web],
    )
    _serve(monkeypatch, _Replay(q1_replies()))

    def bound(call):
        assert call.has_tool(GENIE_TOOL_NAME) and call.has_tool("web_search")
        call.use("web_search", {"query": "Databricks AI Gateway MCP services"})
        raise _loop_gave_up()

    def genie_only(call):
        call.use(GENIE_TOOL_NAME, {"question": Q1})
        return _success(["Genie One"])

    runtime = _install(monkeypatch, _Runtime(data_analyst=[bound, genie_only]))

    t = _run_analyst(_analyst_state(graph_env, turn_started_at=time.time() - 5))

    first, second = runtime.calls_for("data_analyst")
    assert first.at_start == (6, 300.0, 0)
    assert second.tool_names == [GENIE_TOOL_NAME]
    assert second.at_start == (3, 300.0, 0)
    assert second.toolset is not first.toolset
    assert second.payload == first.payload
    assert _info(t.rows).count(_tools_failed("Web Search")) == 1
    assert t.updates["architect_message"].startswith(SYNTHESIS + "\nSources: Genie One")
    assert scoped_vals({"turn_id": TURN, **t.updates}, "analyst_figures")
    assert t.updates["analyst_rounds"] == scoped(TURN, [{"answers": 1}])
    vals = _usage_vals(t.updates)
    assert [(entry["agent"], entry["notified"]) for entry in vals] == [("data_analyst", [WEB])]


def test_gateway_only_analyst_falls_back_to_no_tools(graph_env, monkeypatch):
    """I2, the analyst with only a Gateway connection: the call with its tools raises,
    and it is made once more with no toolset, today's no-tool call."""
    web = _Service(WEB, _web_tools())
    _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[_entry(WEB, "Web Search")],
        rows=[WEB_ANALYST_ROW],
        services=[web],
    )

    def bound(call):
        assert call.tool_names == ["web_search"]
        raise _pinned_error()

    runtime = _install(monkeypatch, _Runtime(data_analyst=[bound, _success(["The request"])]))

    t = _run_analyst(_analyst_state(graph_env, turn_started_at=time.time() - 5))

    first, second = runtime.calls_for("data_analyst")
    assert first.toolset is not None
    assert second.context.toolset is None
    assert second.payload == first.payload
    message = SYNTHESIS + "\nSources: The request"
    assert t.updates["architect_message"] == message
    assert _info(t.rows) == [message, _tools_failed("Web Search")]


def test_the_analyst_fallbacks_failure_propagates_as_today(graph_env, monkeypatch):
    """The analyst's fallback (no tools) raises too: that failure propagates."""
    web = _Service(WEB, _web_tools())
    _gateway_deck(
        graph_env,
        monkeypatch,
        entries=[_entry(WEB, "Web Search")],
        rows=[WEB_ANALYST_ROW],
        services=[web],
    )

    def bound(call):
        raise _loop_gave_up()

    def fallback(call):
        assert call.toolset is None
        raise RuntimeError("the model endpoint is down")

    runtime = _install(monkeypatch, _Runtime(data_analyst=[bound, fallback]))

    with pytest.raises(RuntimeError, match="the model endpoint is down"):
        _run_analyst(_analyst_state(graph_env, turn_started_at=time.time() - 5))

    assert len(runtime.calls_for("data_analyst")) == 2


def test_genie_only_analyst_failure_is_unchanged(graph_env, monkeypatch):
    """C2: Genie One alone (no Gateway entry): a failing call is made once and its
    error propagates, as before this branch."""
    _set_agent_config(graph_env, graph_env.session_id, {"tools": [GENIE_ONE_ENTRY]})
    _sign_in()
    _serve(monkeypatch, _Replay(q1_replies()))

    def fails(call):
        assert call.tool_names == [GENIE_TOOL_NAME]
        raise _loop_gave_up()

    runtime = _install(monkeypatch, _Runtime(data_analyst=fails))

    with pytest.raises(OutputParserException):
        _run_analyst(_analyst_state(graph_env, turn_started_at=time.time() - 5))

    assert len(runtime.calls_for("data_analyst")) == 1


# ---- T6-1: no image notice for a refused answer ----------------------------


def test_no_image_notice_when_the_committed_answer_is_a_refusal(graph_env, monkeypatch):
    """T6-1: both attempts are refused and invent an image reference on slide 2.
    The turn degrades and only the refusal is said: no image notice for a spec that
    was never committed."""
    _lakedraw_deck(graph_env, monkeypatch)
    refused = architect_build(
        _with_slides(
            make_spec((0, 1), slide_type="title"),
            content_brief={1: "Diagram " + ref(INVENTED) + "."},
        )
    )
    runtime = _install(monkeypatch, _Runtime(architect=[refused, refused]))

    t = _architect(graph_env, _state(graph_env))

    assert len(runtime.calls_for("architect")) == 2
    assert t.updates["error_state"] is not None
    assert _image_notices(t.info) == []


# ---- m2: the builder's known set includes the deck style's references ------


def test_the_known_set_includes_deck_style_and_resolved_style_refs(graph_env):
    """m2: a reference in the deck style (its css or a component's example) or in the
    resolved style is one the slide may place, so a Gateway turn's builder keeps it."""
    in_css, in_component, in_style = new_token(), new_token(), new_token()
    deck_style = DeckStyle(
        css=".logo { background-image: url('" + ref(in_css) + "'); }",
        components=[
            DeckStyleComponent(
                name="logo",
                class_names=["logo"],
                use="on every slide",
                example_html='<img class="logo" src="' + ref(in_component) + '"/>',
            )
        ],
    )
    spec = make_spec((0, 1)).model_copy(update={"deck_style": deck_style})
    state = _branch_state(
        graph_env, spec, resolved_style=DEFAULT_STYLE + "\nLogo: " + ref(in_style)
    )

    payload = build_branch_payload(state, 0)

    assert {in_css, in_component, in_style} <= set(payload["gateway_known_images"])
    html = (
        '<div class="slide"><img class="logo" src="' + ref(in_component) + '"/>'
        + "<div style=\"background-image: url('" + ref(in_css) + "')\">x</div>"
        + '<img src="' + ref(in_style) + '"/><p>a</p></div>'
    )
    t = _run_builder(graph_env, payload, html)
    assert t.html == html
    assert _image_notices(t.info) == []


# ---- m6: the SSE progress event carries the row's tool_input ---------------


def test_the_progress_event_carries_the_rows_tool_input(graph_env, monkeypatch):
    """m6: the SSE ``TOOL_CALL`` event names the connection and the tool exactly as
    the persisted row does (``tool_input``), never the model's arguments."""
    _lakedraw_deck(graph_env, monkeypatch)

    def answer(call):
        call.use(CREATE, {"diagram_data": {"title": "SECRET-ARG"}})
        return architect_build(make_spec((0, 1)))

    _install(monkeypatch, _Runtime(architect=answer))

    t = _architect(graph_env, _state(graph_env))

    tool_input = {"connection": "LakeDraw", "tool": CREATE}
    (row,) = [r for r in t.rows if r["message_type"] == "tool_call"]
    assert row["metadata"] == {"tool_name": "gateway_mcp", "tool_input": tool_input}
    (event,) = [e for e in t.events if e.type == StreamEventType.TOOL_CALL]
    assert event.metadata == {
        "node": "architect",
        "tool_name": "gateway_mcp",
        "tool_input": tool_input,
    }
    assert "SECRET-ARG" not in json.dumps(event.metadata)
