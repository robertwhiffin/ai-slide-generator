# ruff: noqa: F811 — the conftest_graph fixture is imported, then requested by name.
"""Task 6: the graph wiring for Genie One in agent mode.

``data_analyst_node`` builds a Genie One toolset from the ACTOR's agent config,
says a progress line per question, persists the per-user conversation id, writes
code-built figures on the turn-scoped ``analyst_figures`` key, says the consent or
grant message on an access error, and caps analyst rounds per turn
(``analyst_rounds``).  ``architect_node`` writes the Genie figures verbatim into
``resolved_data.figures`` and re-applies the prior spec's on a later turn.

How these tests are built, and why:

* **A real database** (``graph_env``: SQLite with the production schema), so the
  conversation id, the progress lines and the committed spec are read back off
  their rows rather than asserted as a kwarg reaching a mock.
* **Real Genie One replies.**  Every reply is a recorded fixture from
  ``tests/fixtures/genie_one/`` (q1 and q2), replayed through the REAL
  ``GenieOneClient`` by a scripted ``call_tool``.  ``GenieOneClient.__init__`` is
  wrapped so the client the node builds gets that ``call_tool`` (and a fake clock
  and sleep), and records the ``host`` and ``token`` it was built with.  Three
  replies are DERIVED from a recorded one, changing only the named field: a
  ``failed`` final poll (status), and two ``isError`` texts (text).
* **The signed-in user** is bound with ``set_user_client`` (the request-scoped
  ContextVar ``get_user_client`` reads), so the test does not depend on how
  ``nodes`` imports it.  Its token is a hand-built JWT whose ``client_id`` the
  consent message must name.
* **A fake runtime** stands in for ``AgentRuntime``.  It records the FOURTH
  positional argument (the ``AgentAssemblyContext``) whole, and, when that context
  carries a toolset, plays the Task 5 tool loop's contract: ``start()``, one
  ``calls_made`` per call, ``ToolAccessError`` recorded on ``access_errors``, any
  other exception answered in-band.
"""

from __future__ import annotations

import base64
import copy
import inspect
import json
import queue
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence, get_type_hints

import pytest
from databricks.sdk.errors.platform import PermissionDenied

from src.api.schemas.agent_config import GenieOneTool, GenieTool, resolve_agent_config
from src.api.schemas.streaming import StreamEventType
from src.api.services.session_manager import SessionManager, get_session_manager
from src.api.services.slide_repository import SlideWriter
from src.core.databricks_client import set_user_client
from src.core.scope_errors import consent_message
from src.database.models.session import UserSession
from src.domain.deck_spec import DeckSpec, ResolvedData, ResolvedFigure
from src.domain.skill_io import AnalystOutput, ArchitectOutput
from src.domain.slide_operations import DeckChanges, SlideContent, SlideOperation
from src.services.agent_runtime import AgentAssemblyContext
from src.services.agent_tools.genie_one import (
    GENIE_ONE_SOURCE,
    GenieOneClient,
    figures_from_answer,
    render_answer_for_model,
)
from src.services.agent_tools.registry import (
    GENIE_TOOL_NAME,
    GenieOneAgentTool,
    build_analyst_toolset,
)
from src.services.agent_tools.toolset import AgentToolset, ToolAccessError
from src.services.graph import nodes
from src.services.graph.event_emitter import set_chat_request_id, set_event_emitter
from src.services.graph.nodes import (
    MAX_ANALYST_ROUNDS_PER_TURN,
    _with_genie_figures,
    architect_node,
    build_branch_payload,
    data_analyst_node,
)
from src.services.graph.state import (
    _EMPTY_FOR,
    GraphState,
    scoped,
    scoped_vals,
    turn_scoped_concat,
)
from src.utils.spotlight import spotlight
from tests.unit.conftest_graph import (  # noqa: F401 — graph_env is a fixture
    architect_build,
    graph_env,
    make_spec,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "genie_one"

TURN = "turn-1"
REQUEST_ID = "req-genie-one"

HOST = "https://example-workspace.cloud.databricks.com"
APP_CLIENT_ID = "tellr-app-oauth-client-0042"

Q1 = "What are the top 3 pickup zip codes by trip count in samples.nyctaxi.trips?"
Q2 = "What is the average fare for those 3 zip codes, and for all 3 combined?"

# Exact values from the recorded fixtures.
CONVERSATION_ID = "84cb39d7434e46c29b823d3f152d88c4"
DEEP_LINK = (
    "https://example-workspace.cloud.databricks.com/one/chat/threads/"
    "84cb39d7434e46c29b823d3f152d88c4?o=1234567890123456&utm_source=genie_chat_mcp"
)
Q1_FIGURES = [
    ("trip_count (pickup_zip=10001)", "1227", "Genie One"),
    ("trip_count (pickup_zip=10003)", "1181", "Genie One"),
    ("trip_count (pickup_zip=10011)", "1129", "Genie One"),
]
#: One analyst run asking q1 then q2, merged (controller ruling 1).  q2 repeats
#: q1's three trip_count figures with the SAME values (dropped); its avg_fare_amount
#: figures and its "All 3 combined" row are new keys (kept, in q2's row order).
Q1_Q2_FIGURES = Q1_FIGURES + [
    ("avg_fare_amount (pickup_zip=10011)", "10.91", "Genie One"),
    ("avg_fare_amount (pickup_zip=10003)", "10.98", "Genie One"),
    ("avg_fare_amount (pickup_zip=10001)", "10.62", "Genie One"),
    ("trip_count (pickup_zip=All 3 combined)", "3537", "Genie One"),
    ("avg_fare_amount (pickup_zip=All 3 combined)", "10.83", "Genie One"),
]

REQUEST = (
    'I need the busiest pickup zip codes.\n\nDATA REQUEST: {"question": "busiest pickup zip codes"}'
)
SYNTHESIS = "The busiest pickup zip codes are 10001, 10003 and 10011."

#: The exact text the Genie One tool is bound with (task-6 brief).
GENIE_TOOL_DESCRIPTION = (
    "Ask Genie One, the Databricks data agent, a natural-language question about "
    "the user's data. It writes and runs SQL on the user's behalf and returns an "
    "answer with result tables. Each question takes one to four minutes, and you "
    "may ask at most 3 per request, so ask a few broad questions that cover what "
    "the data request needs rather than many narrow ones. Figures from its results "
    'are recorded automatically with source "Genie One"; list "Genie One" in '
    "sources when you use them."
)

ROUNDS_COMPLETE = (
    "Data gathering for this turn is complete. Plan the deck with the data already gathered."
)
GRANT_MESSAGE = (
    "Genie One refused the request. You may need EXECUTE permission on "
    "system.ai.genie_one_mcp; ask a workspace admin to grant it."
)

#: The analyst's message on a q1 success, written out in full.
Q1_MESSAGE = (
    "The busiest pickup zip codes are 10001, 10003 and 10011.\n"
    "Sources: Genie One\n"
    "Figures from Genie One (use these keys in data_references):\n"
    "- trip_count (pickup_zip=10001): 1227\n"
    "- trip_count (pickup_zip=10003): 1181\n"
    "- trip_count (pickup_zip=10011): 1129\n"
    "Explore in Databricks: "
    "https://example-workspace.cloud.databricks.com/one/chat/threads/"
    "84cb39d7434e46c29b823d3f152d88c4?o=1234567890123456&utm_source=genie_chat_mcp"
)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _jwt(payload: Dict[str, Any]) -> str:
    """Hand-built unsigned JWT: header.payload.signature, base64url without padding."""
    header = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    body = _b64(json.dumps(payload).encode())
    return f"{header}.{body}.c2lnbmF0dXJl"


#: The signed-in user's token. Its payload names the app's OAuth client.
TOKEN = _jwt({"client_id": APP_CLIENT_ID, "sub": "analyst@example.com", "scope": "sql"})


# ---------------------------------------------------------------------------
# Recorded Genie One replies
# ---------------------------------------------------------------------------


def load(name: str) -> Dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def q1_replies() -> Dict[str, List[Any]]:
    return {
        "genie_ask": [load("q1_ask")],
        "genie_poll_response": [load("q1_poll_in_progress"), load("q1_poll_final")],
        "genie_get_query_result": [load("q1_query_result_0")],
    }


def q2_replies() -> Dict[str, List[Any]]:
    return {
        "genie_ask": [load("q2_ask")],
        "genie_poll_response": [load("q2_poll_in_progress"), load("q2_poll_final")],
        "genie_get_query_result": [load("q2_query_result_0")],
    }


def q1_then_q2_replies() -> Dict[str, List[Any]]:
    first, second = q1_replies(), q2_replies()
    return {name: first[name] + second[name] for name in first}


def poll_final_with_status(status: str) -> Dict[str, Any]:
    """q1's recorded final poll with only its status changed (none was recorded)."""
    recorded = load("q1_poll_final")
    recorded["structuredContent"]["status"] = status
    recorded["content"][0]["text"] = recorded["content"][0]["text"].replace(
        "**Status:** completed", f"**Status:** {status}"
    )
    return recorded


def q2_result_with_cell(row: int, column: int, value: str) -> Dict[str, Any]:
    """q2's recorded query result with only one cell changed (in both of its forms)."""
    recorded = load("q2_query_result_0")
    structured = recorded["structuredContent"]
    structured["rows"][row][column] = value
    recorded["content"][0]["text"] = json.dumps(structured, separators=(",", ":"))
    return recorded


def is_error_with_text(text: str) -> Dict[str, Any]:
    """error_bad_response_id's recorded isError shape with only its text changed."""
    recorded = load("error_bad_response_id")
    recorded["content"][0]["text"] = text
    return recorded


def recorded_missing_scope_exception() -> BaseException:
    """The recorded SDK error: its real class (``PermissionDenied``), its real message."""
    recorded = load("error_missing_scope_sdk")
    assert recorded["exception_class"] == "databricks.sdk.errors.platform.PermissionDenied"
    return PermissionDenied(recorded["message"])


class _HarnessAbort(BaseException):
    """An unscripted call or a runaway poll.  A BaseException, so no ``except
    Exception`` in the code under test can turn it into a pass."""


class _FakeCallToolResult:
    """Mirrors ``mcp.types.CallToolResult``: ``isError``, ``content[*].text``,
    ``structuredContent``."""

    def __init__(self, recorded: Dict[str, Any]) -> None:
        self.isError = recorded["isError"]
        self.content = [
            SimpleNamespace(type=item["type"], text=item["text"]) for item in recorded["content"]
        ]
        self.structuredContent = copy.deepcopy(recorded["structuredContent"])


class _Replay:
    """A scripted Genie One MCP server, plus a fake clock and sleep on one timeline.

    ``replies`` maps a tool name to its replies, in order: a recorded fixture dict
    (returned as a CallToolResult-like object) or an exception (raised).
    ``on_call`` runs at the start of every call, before the reply.
    """

    MAX_CALLS = 200

    def __init__(self, replies: Dict[str, List[Any]], *, on_call=None) -> None:
        self._replies = {name: list(seq) for name, seq in replies.items()}
        self.calls: List[tuple] = []
        self.now = 1000.0
        self.on_call = on_call

    def call_tool(self, name: str, args: Dict[str, Any]) -> _FakeCallToolResult:
        self.calls.append((name, dict(args)))
        if len(self.calls) > self.MAX_CALLS:
            raise _HarnessAbort("runaway loop: the client never stopped polling")
        if self.on_call is not None:
            self.on_call(name, dict(args))
        pending = self._replies.get(name)
        if not pending:
            raise _HarnessAbort(f"unscripted Genie One call {name}({args!r})")
        reply = pending.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return _FakeCallToolResult(reply)

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def clock(self) -> float:
        return self.now

    def asks(self) -> List[Dict[str, Any]]:
        return [args for name, args in self.calls if name == "genie_ask"]


def _ask(replies: Dict[str, List[Any]], question: str, conversation_id: Optional[str] = None):
    """What the REAL client makes of these recorded replies (the expected answer)."""
    replay = _Replay(replies)
    client = GenieOneClient(
        host=HOST,
        token=TOKEN,
        call_tool=replay.call_tool,
        sleep=replay.sleep,
        clock=replay.clock,
    )
    return client.ask(question, conversation_id=conversation_id, timeout_seconds=300)


def _dumps(figures: Sequence[ResolvedFigure]) -> List[Dict[str, str]]:
    return [f.model_dump() for f in figures]


def _triples(figures: Sequence[ResolvedFigure]) -> List[tuple]:
    return [(f.key, f.value, f.source) for f in figures]


def _serve(monkeypatch, server: _Replay) -> List[Dict[str, Any]]:
    """Route every ``GenieOneClient`` the code under test builds to *server*.

    Returns the list of ``{"host", "token"}`` each such client was built with.  A
    client built by this file's own ``_ask`` (whose ``call_tool`` is a ``_Replay``)
    is passed through untouched and not recorded.
    """
    built: List[Dict[str, Any]] = []
    real_init = GenieOneClient.__init__

    def init(self, **kwargs):
        if not isinstance(getattr(kwargs.get("call_tool"), "__self__", None), _Replay):
            built.append({"host": kwargs.get("host"), "token": kwargs.get("token")})
            kwargs.update(call_tool=server.call_tool, sleep=server.sleep, clock=server.clock)
        real_init(self, **kwargs)

    monkeypatch.setattr(GenieOneClient, "__init__", init)
    return built


def _sign_in(token: str = TOKEN, host: str = HOST) -> None:
    """Bind the signed-in user's client (conftest resets it after every test)."""
    set_user_client(SimpleNamespace(config=SimpleNamespace(host=host, token=token)))


# ---------------------------------------------------------------------------
# The fake runtime
# ---------------------------------------------------------------------------


class _ToolLoopRuntime:
    """Stands in for ``AgentRuntime``; records each call's context WHOLE.

    When the context carries a toolset, it asks ``questions`` through the tool
    named ``genie`` under the Task 5 loop's contract, then returns ``output``.
    Any role but ``data_analyst`` fails loudly.
    """

    def __init__(self, output: AnalystOutput, questions: Sequence[str] = ()) -> None:
        self.output = output
        self.questions = list(questions)
        self.calls: List[SimpleNamespace] = []
        self.tool_texts: List[str] = []

    def run(self, name, graph_release_id, payload, assembly_context):
        if name != "data_analyst":
            raise AssertionError(f"unexpected runtime call for {name!r}")
        self.calls.append(
            SimpleNamespace(
                name=name,
                graph_release_id=graph_release_id,
                payload=payload,
                context=assembly_context,
            )
        )
        toolset = assembly_context.toolset
        if toolset is not None and self.questions:
            toolset.start()
            tool = {t.name: t for t in toolset.tools}[GENIE_TOOL_NAME]
            for question in self.questions:
                if toolset.exhausted():
                    self.tool_texts.append("Tool budget exhausted.")
                    continue
                toolset.calls_made += 1
                args = tool.args_schema.model_validate({"question": question})
                try:
                    text = tool.run(args, remaining_seconds=toolset.remaining_seconds())
                except ToolAccessError as exc:
                    toolset.access_errors.append(exc)
                    text = f"Access denied: {exc.message}"
                except Exception as exc:  # the loop answers any other error in-band
                    text = f"Tool error: {type(exc).__name__}: {str(exc)[:300]}"
                self.tool_texts.append(text)
        return SimpleNamespace(output=self.output)


def _install(monkeypatch, runtime: _ToolLoopRuntime) -> _ToolLoopRuntime:
    monkeypatch.setattr(nodes, "get_agent_runtime", lambda: runtime)
    return runtime


def _success(sources=("Genie One",)) -> AnalystOutput:
    return AnalystOutput(outcome="success", synthesis=SYNTHESIS, sources=list(sources))


# ---------------------------------------------------------------------------
# Session rows
# ---------------------------------------------------------------------------


GENIE_ONE_ONLY = {"tools": [{"type": "genie_one"}]}


def _set_agent_config(env, session_id: str, config: Optional[Dict[str, Any]]) -> None:
    db = env.factory()
    try:
        row = db.query(UserSession).filter(UserSession.session_id == session_id).one()
        row.agent_config = copy.deepcopy(config)
        db.commit()
    finally:
        db.close()


def _raw_agent_config(env, session_id: str) -> Optional[Dict[str, Any]]:
    db = env.factory()
    try:
        row = db.query(UserSession).filter(UserSession.session_id == session_id).one()
        return copy.deepcopy(row.agent_config)
    finally:
        db.close()


def _add_contributor(env) -> str:
    """A contributor session on the owner's deck; its agent_config starts NULL (C8)."""
    db = env.factory()
    try:
        owner = db.query(UserSession).filter(UserSession.session_id == env.session_id).one()
        contributor = UserSession(
            session_id=f"contrib-{owner.id}-genie-one",
            created_by="contributor@example.com",
            parent_session_id=owner.id,
            graph_release_id=owner.graph_release_id,
        )
        db.add(contributor)
        db.commit()
        return contributor.session_id
    finally:
        db.close()


def _analyst_state(env, *, actor: Optional[str] = None, **overrides) -> Dict[str, Any]:
    """The state invoke_graph hands the analyst: session_id IS the actor session."""
    actor = actor or env.session_id
    state = env.state(
        session_id=actor,
        root_session_id=env.session_id,
        actor_session_id=actor,
        architect_message=REQUEST,
    )
    state.update(overrides)
    return state


def _run_analyst(state: Dict[str, Any], emitter: Optional[queue.Queue] = None):
    """Run the node once, under an emitter and a request id; return what it did."""
    sm = get_session_manager()
    before = len(sm.get_messages(state["session_id"]))
    emitter = emitter if emitter is not None else queue.Queue()
    set_event_emitter(emitter)
    set_chat_request_id(REQUEST_ID)
    try:
        updates = data_analyst_node(state)
    finally:
        set_event_emitter(None)
        set_chat_request_id(None)
    events = []
    while not emitter.empty():
        events.append(emitter.get_nowait())
    rows = sm.get_messages(state["session_id"])[before:]
    return SimpleNamespace(updates=updates, events=events, rows=rows)


def _figures_written(updates: Dict[str, Any]) -> Any:
    """``analyst_figures`` as this run wrote it (absent counts as an empty write)."""
    return updates.get("analyst_figures", scoped(TURN, []))


def _assert_one_round_marker(updates: Dict[str, Any], turn_id: str = TURN) -> None:
    marker = updates["analyst_rounds"]
    assert isinstance(marker, dict) and marker["turn"] == turn_id
    assert len(marker["vals"]) == 1, (
        f"each data_analyst run writes exactly one round marker, got {marker['vals']!r}"
    )


# ===========================================================================
# The state contract for the two new keys
# ===========================================================================


def test_the_two_new_keys_are_turn_scoped_lists():
    """Both are ``Annotated[Any, turn_scoped_concat]`` with an ``[]`` empty value
    (C5): without the ``_EMPTY_FOR`` entry ``scoped_vals`` raises ``KeyError``, and
    without the declaration the runtime silently drops the analyst's write."""
    hints = get_type_hints(GraphState, include_extras=True)
    for key in ("analyst_figures", "analyst_rounds"):
        assert hints[key].__metadata__[0] is turn_scoped_concat, key
        assert _EMPTY_FOR[key] == [] and isinstance(_EMPTY_FOR[key], list), key
        assert scoped_vals({"turn_id": TURN}, key) == []
        assert scoped_vals({"turn_id": "turn-2", key: scoped(TURN, ["x"])}, key) == []
        assert scoped_vals({"turn_id": TURN, key: scoped(TURN, ["x"])}, key) == ["x"]
    assert MAX_ANALYST_ROUNDS_PER_TURN == 2


# ===========================================================================
# The registry
# ===========================================================================


def test_the_genie_one_tool_binds_as_genie_with_the_exact_description():
    """Ruling 2: the analyst prompt already names a ``genie`` tool, so that is the
    bound name, and the tool's guidance travels in its description."""
    asked: List[str] = []
    built = build_analyst_toolset(
        resolve_agent_config(GENIE_ONE_ONLY),
        host=HOST,
        token=TOKEN,
        on_question=asked.append,
        session_id="session-x",
    )
    assert built is not None
    toolset, tool = built
    assert GENIE_TOOL_NAME == "genie"
    assert isinstance(toolset, AgentToolset)
    assert isinstance(tool, GenieOneAgentTool)
    assert tuple(toolset.tools) == (tool,)
    assert tool.name == "genie"
    assert tool.description == GENIE_TOOL_DESCRIPTION
    assert set(tool.args_schema.model_fields) == {"question"}
    assert tool.args_schema.model_validate({"question": Q1}).question == Q1
    # Global budget: at most 3 questions and 300 s per analyst run.
    assert (toolset.max_calls, toolset.budget_seconds) == (3, 300.0)
    assert tool.answers == [] and tool.conversation_id is None
    assert asked == [], "building the toolset must not ask anything"


@pytest.mark.parametrize(
    "config",
    [
        None,
        {"tools": []},
        {
            "tools": [
                {"type": "genie", "space_id": "space-1", "space_name": "Sales"},
                {"type": "agent_bricks", "endpoint_name": "ka-endpoint"},
            ]
        },
    ],
    ids=["no-config", "no-tools", "legacy-tools-only"],
)
def test_no_genie_one_entry_builds_no_toolset(config):
    assert (
        build_analyst_toolset(
            resolve_agent_config(config),
            host=HOST,
            token=TOKEN,
            on_question=lambda q: None,
            session_id="session-x",
        )
        is None
    )


# ===========================================================================
# data_analyst_node without Genie One: exactly today's call
# ===========================================================================


TODAY_MESSAGE = "The busiest pickup zip codes are 10001, 10003 and 10011.\nSources: genie"


@pytest.mark.parametrize("case", ["no-config", "legacy-tools-only", "unreadable-actor-row"])
def test_analyst_without_genie_one_runs_exactly_as_today(graph_env, monkeypatch, case):
    """No Genie One entry on the actor row (or a row that cannot be read): the
    runtime gets today's four arguments and a context with NO toolset, and the
    message is today's prose.  No user client is bound and ENVIRONMENT is
    production, so a node that reached for the user's identity here would fail."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    server = _Replay(q1_replies())
    built = _serve(monkeypatch, server)
    runtime = _install(monkeypatch, _ToolLoopRuntime(_success(["genie"]), [Q1]))
    if case == "legacy-tools-only":
        _set_agent_config(
            graph_env,
            graph_env.session_id,
            {"tools": [{"type": "genie", "space_id": "space-1", "space_name": "Sales"}]},
        )
    state = _analyst_state(graph_env)
    if case == "unreadable-actor-row":
        # Any exception reading the actor's config counts as no config.
        _set_agent_config(graph_env, graph_env.session_id, GENIE_ONE_ONLY)
        state["actor_session_id"] = "no-such-session"

    t = _run_analyst(state)

    assert len(runtime.calls) == 1
    call = runtime.calls[0]
    assert (call.name, call.graph_release_id) == ("data_analyst", 1)
    assert call.payload == {"data_request": REQUEST, "deck_purpose": None}
    assert call.context.toolset is None
    assert call.context == AgentAssemblyContext(
        False, graph_env.session_id, state["actor_session_id"]
    )
    assert built == [] and server.calls == []
    assert t.updates["architect_message"] == TODAY_MESSAGE
    assert _figures_written(t.updates) == scoped(TURN, [])
    _assert_one_round_marker(t.updates)
    assert [(r["content"], r["message_type"]) for r in t.rows] == [(TODAY_MESSAGE, "info")]


def test_contributor_without_genie_one_runs_without_tools(graph_env, monkeypatch):
    """Tools come from the ACTOR's own row (ruling 4, C8).  The owner has Genie One;
    the contributor's row starts NULL, so the contributor's turn has no toolset —
    even with a signed-in user, and even though the deck's owner could ask."""
    _sign_in()
    contributor = _add_contributor(graph_env)
    _set_agent_config(graph_env, graph_env.session_id, GENIE_ONE_ONLY)
    assert _raw_agent_config(graph_env, contributor) is None
    server = _Replay(q1_replies())
    built = _serve(monkeypatch, server)
    runtime = _install(monkeypatch, _ToolLoopRuntime(_success(["genie"]), [Q1]))

    t = _run_analyst(_analyst_state(graph_env, actor=contributor))

    assert len(runtime.calls) == 1
    call = runtime.calls[0]
    assert call.context.toolset is None
    assert call.context == AgentAssemblyContext(False, graph_env.session_id, contributor)
    assert built == [] and server.calls == []
    assert t.updates["architect_message"] == TODAY_MESSAGE
    assert _figures_written(t.updates) == scoped(TURN, [])
    assert _raw_agent_config(graph_env, contributor) is None
    assert _raw_agent_config(graph_env, graph_env.session_id) == GENIE_ONE_ONLY


def test_analyst_without_a_user_client_runs_without_tools(graph_env, monkeypatch):
    """A Genie One entry but no signed-in user (production, nothing bound): today's
    call with no toolset.  Never the service principal (global constraint)."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    _set_agent_config(graph_env, graph_env.session_id, GENIE_ONE_ONLY)
    server = _Replay(q1_replies())
    built = _serve(monkeypatch, server)
    runtime = _install(monkeypatch, _ToolLoopRuntime(_success(["genie"]), [Q1]))

    t = _run_analyst(_analyst_state(graph_env))

    assert len(runtime.calls) == 1
    assert runtime.calls[0].context.toolset is None
    assert built == [] and server.calls == []
    assert t.updates["architect_message"] == TODAY_MESSAGE
    assert _figures_written(t.updates) == scoped(TURN, [])


# ===========================================================================
# data_analyst_node with Genie One
# ===========================================================================


def test_analyst_with_genie_one_passes_a_toolset_and_writes_figures(graph_env, monkeypatch):
    """The owner's turn on a Genie One deck: a toolset rides the FOURTH argument,
    the tool runs as the signed-in user, the model sees the spotlighted answer, and
    the figures the code built from the result rows are written on
    ``analyst_figures`` and listed, with the deep link, in the message."""
    expected_answer = _ask(q1_replies(), Q1)
    expected_figures = figures_from_answer(expected_answer)
    assert _triples(expected_figures) == Q1_FIGURES  # the real fixture, by value
    assert GENIE_ONE_SOURCE == "Genie One"

    _sign_in()
    _set_agent_config(graph_env, graph_env.session_id, GENIE_ONE_ONLY)
    server = _Replay(q1_replies())
    built = _serve(monkeypatch, server)
    runtime = _install(monkeypatch, _ToolLoopRuntime(_success(), [Q1]))

    t = _run_analyst(_analyst_state(graph_env))

    # The runtime: today's four positional arguments, the toolset on the context.
    assert len(runtime.calls) == 1
    call = runtime.calls[0]
    assert (call.name, call.graph_release_id) == ("data_analyst", 1)
    assert call.payload == {"data_request": REQUEST, "deck_purpose": None}
    assert call.context == AgentAssemblyContext(False, graph_env.session_id, graph_env.session_id)
    toolset = call.context.toolset
    assert isinstance(toolset, AgentToolset)
    assert [t_.name for t_ in toolset.tools] == ["genie"]
    assert isinstance(toolset.tools[0], GenieOneAgentTool)
    assert (toolset.max_calls, toolset.budget_seconds) == (3, 300.0)
    assert toolset.access_errors == []

    # The client was built ONCE, from the signed-in user's host and token.
    assert built == [{"host": HOST, "token": TOKEN}]
    assert server.asks() == [{"question": Q1}]
    assert [name for name, _ in server.calls] == [
        "genie_ask",
        "genie_poll_response",
        "genie_poll_response",
        "genie_get_query_result",
    ]

    # What the model was handed: the rendered answer, spotlighted as genie_one.
    assert runtime.tool_texts == [spotlight("genie_one", render_answer_for_model(expected_answer))]
    assert toolset.tools[0].answers == [expected_answer]

    # The state writes: figures verbatim, one round marker, the message.
    assert t.updates["analyst_figures"] == scoped(TURN, _dumps(expected_figures))
    _assert_one_round_marker(t.updates)
    assert t.updates["architect_message"] == Q1_MESSAGE
    assert "trip_count (pickup_zip=10001): 1227" in t.updates["architect_message"]
    assert f"Explore in Databricks: {DEEP_LINK}" in t.updates["architect_message"]
    assert set(t.updates) <= {"architect_message", "analyst_figures", "analyst_rounds"}

    # The user sees the same message, durably (polling transport) and on SSE.
    info = [r for r in t.rows if r["message_type"] == "info"]
    assert [r["content"] for r in info] == [Q1_MESSAGE]
    assistant = [e for e in t.events if e.type == StreamEventType.ASSISTANT]
    assert [e.content for e in assistant] == [Q1_MESSAGE]


def test_progress_line_is_emitted_and_persisted_per_question(graph_env, monkeypatch):
    """Each question shows as ``Asking Genie One: <question>`` BEFORE it is asked,
    on SSE (``_emit``) and as a persisted ``tool_call`` row the polling transport
    turns into a tool_call event (C7).  The follow-up continues the first answer's
    conversation, and the deep link the two answers share is listed once.  (How
    their figures merge is test_figures_across_two_answers_are_deduplicated.)"""
    _sign_in()
    _set_agent_config(graph_env, graph_env.session_id, GENIE_ONE_ONLY)
    emitter: queue.Queue = queue.Queue()
    seen_at_ask: List[List[str]] = []

    def on_call(name, args):
        if name == "genie_ask":
            seen_at_ask.append(
                [e.content for e in list(emitter.queue) if e.type == StreamEventType.TOOL_CALL]
            )

    server = _Replay(q1_then_q2_replies(), on_call=on_call)
    _serve(monkeypatch, server)
    _install(monkeypatch, _ToolLoopRuntime(_success(), [Q1, Q2]))

    t = _run_analyst(_analyst_state(graph_env), emitter)

    line1, line2 = f"Asking Genie One: {Q1}", f"Asking Genie One: {Q2}"
    # SSE: one TOOL_CALL per question, each queued before its question was asked.
    tool_calls = [e for e in t.events if e.type == StreamEventType.TOOL_CALL]
    assert [e.content for e in tool_calls] == [line1, line2]
    assert [e.metadata for e in tool_calls] == [
        {"node": "data_analyst", "tool_name": "genie_one"},
        {"node": "data_analyst", "tool_name": "genie_one"},
    ]
    assert seen_at_ask == [[line1], [line1, line2]]

    # Persisted: one assistant tool_call row per question, before the answer.
    progress = [r for r in t.rows if r["message_type"] == "tool_call"]
    assert [(r["role"], r["content"], r["metadata"]) for r in progress] == [
        ("assistant", line1, {"tool_name": "genie_one", "tool_input": {"question": Q1}}),
        ("assistant", line2, {"tool_name": "genie_one", "tool_input": {"question": Q2}}),
    ]
    kinds = [r["message_type"] for r in t.rows]
    assert kinds.index("info") > max(i for i, k in enumerate(kinds) if k == "tool_call")

    # The polling transport turns those rows into tool_call events.
    sm = get_session_manager()
    polled = [
        sm.msg_to_stream_event(m)
        for m in sm.get_messages_for_request(REQUEST_ID)
        if m["message_type"] == "tool_call"
    ]
    assert [(p["type"], p["content"], p["tool_name"], p["tool_input"]) for p in polled] == [
        ("tool_call", line1, "genie_one", {"question": Q1}),
        ("tool_call", line2, "genie_one", {"question": Q2}),
    ]

    # The follow-up continues the conversation the first answer opened.
    assert server.asks() == [
        {"question": Q1},
        {"question": Q2, "conversation_id": CONVERSATION_ID},
    ]
    # The shared deep link is listed once, last.
    message = t.updates["architect_message"]
    assert "- avg_fare_amount (pickup_zip=All 3 combined): 10.83" in message
    assert message.count("Explore in Databricks:") == 1
    assert message.endswith(f"\nExplore in Databricks: {DEEP_LINK}")


def _figure_dicts(triples: Sequence[tuple]) -> List[Dict[str, str]]:
    return [{"key": k, "value": v, "source": s} for k, v, s in triples]


def _merged_message(triples: Sequence[tuple]) -> str:
    return (
        f"{SYNTHESIS}\nSources: Genie One\n"
        "Figures from Genie One (use these keys in data_references):"
        + "".join(f"\n- {k}: {v}" for k, v, _ in triples)
        + f"\nExplore in Databricks: {DEEP_LINK}"
    )


def test_figures_across_two_answers_are_deduplicated(graph_env, monkeypatch):
    """Controller ruling 1: one run asks q1 then q2.  q2 repeats q1's trip_count
    figures for the same zips with the same values, so they are dropped; its
    avg_fare_amount figures and its "All 3 combined" row are new keys, so they are
    kept, after q1's, in q2's order.  The written figures and the message's figure
    lines are that one list."""
    a1 = _ask(q1_replies(), Q1)
    a2 = _ask(q2_replies(), Q2, CONVERSATION_ID)
    # Guard: the recorded q2 answer really does repeat q1's three figures.
    assert _triples(figures_from_answer(a1)) == Q1_FIGURES
    assert set(Q1_FIGURES) < set(_triples(figures_from_answer(a2)))
    _sign_in()
    _set_agent_config(graph_env, graph_env.session_id, GENIE_ONE_ONLY)
    _serve(monkeypatch, _Replay(q1_then_q2_replies()))
    runtime = _install(monkeypatch, _ToolLoopRuntime(_success(), [Q1, Q2]))

    t = _run_analyst(_analyst_state(graph_env))

    assert runtime.calls[0].context.toolset.tools[0].answers == [a1, a2]
    assert t.updates["analyst_figures"] == scoped(TURN, _figure_dicts(Q1_Q2_FIGURES))
    assert t.updates["architect_message"] == _merged_message(Q1_Q2_FIGURES)


def test_a_reappearing_key_with_a_different_value_gets_the_question_suffix(graph_env, monkeypatch):
    """Controller ruling 1, its other half: a key a later answer repeats with a
    DIFFERENT value is kept under ``<key> (question m)``, m the 1-based answer
    index, in place; the exact repeats are still dropped.  The q2 reply is derived:
    q2's recorded result with only 10001's trip_count changed (1227 -> 1230)."""
    replies = q1_then_q2_replies()
    replies["genie_get_query_result"][1] = q2_result_with_cell(2, 1, "1230")
    _sign_in()
    _set_agent_config(graph_env, graph_env.session_id, GENIE_ONE_ONLY)
    _serve(monkeypatch, _Replay(replies))
    _install(monkeypatch, _ToolLoopRuntime(_success(), [Q1, Q2]))

    t = _run_analyst(_analyst_state(graph_env))

    expected = Q1_FIGURES + [
        ("avg_fare_amount (pickup_zip=10011)", "10.91", "Genie One"),
        ("avg_fare_amount (pickup_zip=10003)", "10.98", "Genie One"),
        ("trip_count (pickup_zip=10001) (question 2)", "1230", "Genie One"),
        ("avg_fare_amount (pickup_zip=10001)", "10.62", "Genie One"),
        ("trip_count (pickup_zip=All 3 combined)", "3537", "Genie One"),
        ("avg_fare_amount (pickup_zip=All 3 combined)", "10.83", "Genie One"),
    ]
    assert t.updates["analyst_figures"] == scoped(TURN, _figure_dicts(expected))
    assert t.updates["architect_message"] == _merged_message(expected)


def test_conversation_id_is_persisted_on_the_actor_row_only(graph_env, monkeypatch):
    """Per user per deck (ruling 4, C8): a contributor's Genie One conversation is
    stored on the contributor's own row, in its ``genie_one`` entry only, and the
    owner's conversation is neither used nor touched.  The next turn continues it,
    and an unchanged id is not written again."""
    _sign_in()
    contributor = _add_contributor(graph_env)
    owner_config = {"tools": [{"type": "genie_one", "conversation_id": "owner-conversation-0001"}]}
    actor_config = {
        "tools": [
            {
                "type": "genie",
                "space_id": "space-1",
                "space_name": "Sales",
                "conversation_id": "space-conversation-7",
            },
            {"type": "genie_one"},
        ]
    }
    _set_agent_config(graph_env, graph_env.session_id, owner_config)
    _set_agent_config(graph_env, contributor, actor_config)

    persisted: List[tuple] = []
    real_set = SessionManager.set_genie_one_conversation_id

    def spy(self, session_id, conversation_id):
        persisted.append((session_id, conversation_id))
        return real_set(self, session_id, conversation_id)

    monkeypatch.setattr(SessionManager, "set_genie_one_conversation_id", spy)

    # Turn 1: a new conversation for the contributor.
    server = _Replay(q1_replies())
    _serve(monkeypatch, server)
    _install(monkeypatch, _ToolLoopRuntime(_success(), [Q1]))

    _run_analyst(_analyst_state(graph_env, actor=contributor))

    assert server.asks() == [{"question": Q1}], (
        "the contributor's first question must not continue the owner's conversation"
    )
    assert persisted == [(contributor, CONVERSATION_ID)]
    stored = resolve_agent_config(_raw_agent_config(graph_env, contributor))
    assert stored.tools == [
        GenieTool(
            type="genie",
            space_id="space-1",
            space_name="Sales",
            conversation_id="space-conversation-7",
        ),
        GenieOneTool(conversation_id=CONVERSATION_ID),
    ]
    assert _raw_agent_config(graph_env, graph_env.session_id) == owner_config

    # Turn 2: the stored id is continued; it did not change, so nothing is written.
    server2 = _Replay(q2_replies())
    _serve(monkeypatch, server2)
    _install(monkeypatch, _ToolLoopRuntime(_success(), [Q2]))

    _run_analyst(_analyst_state(graph_env, actor=contributor, turn_id="turn-2"))

    assert server2.asks() == [{"question": Q2, "conversation_id": CONVERSATION_ID}]
    assert persisted == [(contributor, CONVERSATION_ID)]
    assert _raw_agent_config(graph_env, graph_env.session_id) == owner_config


def test_set_genie_one_conversation_id_rewrites_only_that_rows_genie_one_entry(graph_env):
    """A targeted read-modify-write: the other entries and the other fields of the
    row's config are kept, and no other row changes."""
    contributor = _add_contributor(graph_env)
    owner_config = {"tools": [{"type": "genie_one", "conversation_id": "owner-conv"}]}
    actor_config = {
        "tools": [
            {"type": "genie_one", "conversation_id": "old-conv"},
            {
                "type": "genie",
                "space_id": "space-1",
                "space_name": "Sales",
                "conversation_id": "space-conversation-7",
            },
        ],
        "slide_style_id": 12,
    }
    _set_agent_config(graph_env, graph_env.session_id, owner_config)
    _set_agent_config(graph_env, contributor, actor_config)
    before = resolve_agent_config(actor_config)

    get_session_manager().set_genie_one_conversation_id(contributor, "new-conv")

    after = resolve_agent_config(_raw_agent_config(graph_env, contributor))
    expected = before.model_copy(deep=True)
    expected.tools[0].conversation_id = "new-conv"
    assert after == expected
    assert _raw_agent_config(graph_env, graph_env.session_id) == owner_config


def test_missing_scope_access_error_says_the_consent_message(graph_env, monkeypatch):
    """The recorded missing-scope SDK error: the user is told, ONCE, the consent
    message naming the app's OAuth client id from their own token — not the grant
    message, although the recorded text also says 403 Forbidden."""
    _sign_in()
    _set_agent_config(graph_env, graph_env.session_id, GENIE_ONE_ONLY)
    server = _Replay(
        {"genie_ask": [recorded_missing_scope_exception(), recorded_missing_scope_exception()]}
    )
    built = _serve(monkeypatch, server)
    output = AnalystOutput(outcome="no_tool", reason="Genie One was refused", tried_tools=["genie"])
    runtime = _install(monkeypatch, _ToolLoopRuntime(output, [Q1, Q2]))

    t = _run_analyst(_analyst_state(graph_env))

    toolset = runtime.calls[0].context.toolset
    assert [(e.kind, e.tool_name) for e in toolset.access_errors] == [
        ("missing_scope", "genie"),
        ("missing_scope", "genie"),
    ]
    assert built == [{"host": HOST, "token": TOKEN}]
    expected = consent_message(oauth_client_id=APP_CLIENT_ID)
    assert APP_CLIENT_ID in expected
    info = [r["content"] for r in t.rows if r["message_type"] == "info"]
    assert info.count(expected) == 1
    assert GRANT_MESSAGE not in info
    # The analyst's own answer still reaches the architect.
    assert t.updates["architect_message"].startswith(
        "No tool is available for this kind of data request (Genie One was refused). "
        "Tools tried: genie."
    )
    assert _figures_written(t.updates) == scoped(TURN, [])


def test_access_denied_says_the_grant_message(graph_env, monkeypatch):
    """A Genie One 403 (no EXECUTE on the service): the user is told the grant they
    need — not the consent message."""
    _sign_in()
    _set_agent_config(graph_env, graph_env.session_id, GENIE_ONE_ONLY)
    forbidden = is_error_with_text(
        "Calling genie_ask failed with HTTP 403 Forbidden: PERMISSION_DENIED: User "
        "does not have EXECUTE on system.ai.genie_one_mcp."
    )
    server = _Replay({"genie_ask": [forbidden]})
    _serve(monkeypatch, server)
    output = AnalystOutput(outcome="missing_data", gap="Genie One refused the request.")
    runtime = _install(monkeypatch, _ToolLoopRuntime(output, [Q1]))

    t = _run_analyst(_analyst_state(graph_env))

    toolset = runtime.calls[0].context.toolset
    assert [(e.kind, e.tool_name) for e in toolset.access_errors] == [("access_denied", "genie")]
    info = [r["content"] for r in t.rows if r["message_type"] == "info"]
    assert info.count(GRANT_MESSAGE) == 1
    assert consent_message(oauth_client_id=APP_CLIENT_ID) not in info
    assert t.updates["architect_message"].startswith(
        "The requested data could not be found: Genie One refused the request."
    )
    assert _figures_written(t.updates) == scoped(TURN, [])


@pytest.mark.parametrize("failure", ["failed-answer", "is-error-reply"])
def test_analyst_with_failed_genie_answer_still_returns_message(graph_env, monkeypatch, failure):
    """Genie One answers ``failed`` (or replies isError): no figures, no access
    message, and the analyst's gap still reaches the architect and the user."""
    _sign_in()
    _set_agent_config(graph_env, graph_env.session_id, GENIE_ONE_ONLY)
    if failure == "failed-answer":
        replies = {
            "genie_ask": [load("q1_ask")],
            "genie_poll_response": [poll_final_with_status("failed")],
        }
    else:
        replies = {"genie_ask": [load("error_bad_response_id")]}
    server = _Replay(replies)
    _serve(monkeypatch, server)
    output = AnalystOutput(outcome="missing_data", gap="Genie One could not answer.")
    runtime = _install(monkeypatch, _ToolLoopRuntime(output, [Q1]))

    t = _run_analyst(_analyst_state(graph_env))

    assert runtime.calls[0].context.toolset is not None
    assert len(runtime.tool_texts) == 1
    assert runtime.calls[0].context.toolset.access_errors == []
    message = t.updates["architect_message"]
    assert message.startswith("The requested data could not be found: Genie One could not answer.")
    assert "Figures from Genie One" not in message
    assert t.updates["analyst_figures"] == scoped(TURN, [])
    _assert_one_round_marker(t.updates)
    info = [r["content"] for r in t.rows if r["message_type"] == "info"]
    assert info == [message]
    assert GRANT_MESSAGE not in info
    assert consent_message(oauth_client_id=APP_CLIENT_ID) not in info


# ===========================================================================
# Analyst rounds per turn (ruling 6)
# ===========================================================================


def test_third_round_in_a_turn_is_refused_without_calling_the_runtime(graph_env, monkeypatch):
    """Two rounds already ran this turn: the third gets the code-owned message,
    the runtime is never called, Genie One is never asked, the marker is still
    written, and the figures gathered earlier this turn survive."""
    _sign_in()
    _set_agent_config(graph_env, graph_env.session_id, GENIE_ONE_ONLY)
    server = _Replay(q1_replies())
    built = _serve(monkeypatch, server)
    runtime = _install(monkeypatch, _ToolLoopRuntime(_success(), [Q1]))
    gathered = _dumps(figures_from_answer(_ask(q1_replies(), Q1)))
    prior_rounds = scoped(TURN, ["round", "round"])
    state = _analyst_state(
        graph_env,
        analyst_rounds=prior_rounds,
        analyst_figures=scoped(TURN, gathered),
    )

    t = _run_analyst(state)

    assert runtime.calls == []
    assert built == [] and server.calls == []
    assert t.updates["architect_message"] == ROUNDS_COMPLETE
    _assert_one_round_marker(t.updates)
    assert len(turn_scoped_concat(prior_rounds, t.updates["analyst_rounds"])["vals"]) == 3
    after = turn_scoped_concat(state["analyst_figures"], _figures_written(t.updates))
    assert after == scoped(TURN, gathered)
    assert [r for r in t.rows if r["message_type"] == "tool_call"] == []


@pytest.mark.parametrize(
    "prior_rounds",
    [None, scoped(TURN, ["round"]), scoped("turn-0", ["round", "round"])],
    ids=["first-round", "second-round", "two-rounds-of-a-previous-turn"],
)
def test_first_and_second_rounds_call_the_runtime(graph_env, monkeypatch, prior_rounds):
    """The cap is per TURN and is two: a second round runs, and a previous turn's
    rounds (still in the checkpoint) do not count."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    runtime = _install(monkeypatch, _ToolLoopRuntime(_success(["genie"])))
    overrides = {} if prior_rounds is None else {"analyst_rounds": prior_rounds}

    t = _run_analyst(_analyst_state(graph_env, **overrides))

    assert len(runtime.calls) == 1
    assert t.updates["architect_message"] == TODAY_MESSAGE
    _assert_one_round_marker(t.updates)


# ===========================================================================
# architect_node: Genie figures are code-owned in resolved_data
# ===========================================================================


THREE = [
    "<div class='slide'>a</div>",
    "<div class='slide'>b</div>",
    "<div class='slide'>c</div>",
]

NPS = ResolvedFigure(key="nps", value="42", source="Q3 customer survey")
HEADCOUNT = ResolvedFigure(key="headcount", value="118", source="HR system")


def _with_figures(spec: DeckSpec, figures: Sequence[ResolvedFigure]) -> DeckSpec:
    return spec.model_copy(
        update={"resolved_data": spec.resolved_data.model_copy(update={"figures": list(figures)})}
    )


def _retyped(figure: ResolvedFigure, value: str) -> ResolvedFigure:
    return figure.model_copy(update={"value": value})


def _persist(env, spec: DeckSpec) -> None:
    from src.api.services.deck_level_writer import write_deck_level_columns

    write_deck_level_columns(env.session_id, deck_spec=spec.to_json())


def _committed_figures(env) -> List[Dict[str, Any]]:
    return json.loads(env.deck_row().deck_spec_json)["resolved_data"]["figures"]


def _q1_figures() -> List[ResolvedFigure]:
    return figures_from_answer(_ask(q1_replies(), Q1))


def _q2_figures() -> List[ResolvedFigure]:
    return figures_from_answer(_ask(q2_replies(), Q2, CONVERSATION_ID))


def test_with_genie_figures_keeps_only_the_architects_other_figures():
    """Pure: the architect's figures whose source is not Genie One and whose key is
    not a code figure's are kept in order, then the code figures in order; the
    input spec is not changed and nothing but the figures differs."""
    code = _q1_figures()
    architect_figures = [
        NPS,
        _retyped(code[0], "1,227"),
        ResolvedFigure(key=code[1].key, value="1,200", source="Analyst estimate"),
        HEADCOUNT,
        ResolvedFigure(key="trip_count (stale)", value="9", source="Genie One"),
    ]
    spec = _with_figures(make_spec((0, 1)), architect_figures)
    snapshot = spec.model_dump()

    out = _with_genie_figures(spec, code)

    assert out.resolved_data.figures == [NPS, HEADCOUNT] + code
    assert spec.model_dump() == snapshot, "the input spec was mutated"
    assert out == _with_figures(spec, [NPS, HEADCOUNT] + code)


def test_architect_writes_genie_figures_verbatim_into_resolved_data(graph_env):
    """This turn's ``analyst_figures`` are committed byte for byte: a value the
    architect retyped ("1,227") and a figure it dropped are both put right, in the
    state's spec, in the persisted spec and in what every builder is briefed with."""
    code = _q1_figures()
    graph_env.skills.set(
        "architect",
        architect_build(_with_figures(make_spec((0, 1)), [_retyped(code[0], "1,227"), code[2]])),
    )
    state = graph_env.state(
        analyst_figures=scoped(TURN, _dumps(code)), architect_message=Q1_MESSAGE
    )

    updates = architect_node(state)

    assert updates["architect_intent"] == "build"
    assert updates["error_state"] is None
    committed = updates["deck_spec"]
    assert committed.resolved_data.figures == code
    assert committed == _with_figures(make_spec((0, 1)), code)
    assert _committed_figures(graph_env) == _dumps(code)
    assert json.dumps(_committed_figures(graph_env)) == json.dumps(_dumps(code))
    payload = build_branch_payload({**state, **updates}, 0)
    assert payload["resolved_data"]["figures"] == _dumps(code)


def test_architect_keeps_its_own_non_genie_figures(graph_env):
    """The architect's other figures are kept, in its order, before the Genie ones;
    a non-Genie figure that reuses a Genie key gives way to the code's."""
    code = _q1_figures()
    graph_env.skills.set(
        "architect",
        architect_build(
            _with_figures(
                make_spec((0,)),
                [
                    NPS,
                    ResolvedFigure(key=code[0].key, value="1,200", source="Analyst estimate"),
                    HEADCOUNT,
                    _retyped(code[1], "1.181k"),
                ],
            )
        ),
    )

    updates = architect_node(graph_env.state(analyst_figures=scoped(TURN, _dumps(code))))

    assert updates["deck_spec"].resolved_data.figures == [NPS, HEADCOUNT] + code
    assert _committed_figures(graph_env) == _dumps([NPS, HEADCOUNT] + code)


def test_architect_without_genie_figures_commits_its_own_figures_unchanged(graph_env):
    """No Genie figures this turn and none in a prior spec: nothing to merge."""
    graph_env.skills.set(
        "architect", architect_build(_with_figures(make_spec((0,)), [NPS, HEADCOUNT]))
    )

    updates = architect_node(graph_env.state())

    assert updates["deck_spec"].resolved_data.figures == [NPS, HEADCOUNT]
    assert _committed_figures(graph_env) == _dumps([NPS, HEADCOUNT])


def _spy_on_the_layout(monkeypatch) -> List[Dict[str, Any]]:
    """Record every ``apply_slide_layout`` call's bound arguments, then run it."""
    real = SlideWriter.apply_slide_layout
    signature = inspect.signature(real)
    calls: List[Dict[str, Any]] = []

    def spy(self, *args, **kwargs):
        bound = signature.bind(self, *args, **kwargs)
        calls.append({k: v for k, v in bound.arguments.items() if k != "self"})
        return real(self, *args, **kwargs)

    monkeypatch.setattr(SlideWriter, "apply_slide_layout", spy)
    return calls


@pytest.mark.parametrize("edit_form", ["full-spec", "operations"])
def test_later_turn_reapplies_prior_genie_figures_verbatim(graph_env, monkeypatch, edit_form):
    """Ruling 7: on a turn with no new analyst figures, the PERSISTED spec's Genie
    One figures are re-applied verbatim, so an edit that retypes a value (or drops a
    figure) cannot change them.  A previous turn's ``analyst_figures`` (still in
    the checkpoint) are not this turn's.  On the operations path the composed spec
    the layout writer lands carries them too (``plan.spec``)."""
    code = _q1_figures()
    prior = _with_figures(make_spec((0, 1, 2)), [NPS] + code)
    graph_env.seed_slides(THREE)
    _persist(graph_env, prior)
    retyped = [NPS, _retyped(code[0], "1,227"), code[1], HEADCOUNT]
    if edit_form == "full-spec":
        revised = _with_figures(prior, retyped)
        revised = revised.model_copy(
            update={
                "slides": [
                    s.model_copy(update={"content_brief": "three stat cards"})
                    if s.position == 1
                    else s
                    for s in revised.slides
                ]
            }
        )
        out = ArchitectOutput(
            intent="edit", message="Editing.", target_positions=[1], deck_spec=revised
        )
    else:
        out = ArchitectOutput(
            intent="edit",
            message="Adding a slide.",
            operations=[
                SlideOperation(
                    op="insert",
                    after_position=0,
                    slides=[
                        SlideContent(
                            purpose="zip detail",
                            content_brief="the busiest zip code",
                            assumes="the ranking",
                            hands_off="the fares",
                            data_references=[code[0].key],
                        )
                    ],
                )
            ],
            deck_changes=DeckChanges(
                resolved_data=ResolvedData(synthesis="Stub synthesis", figures=retyped, gaps=[])
            ),
        )
    layout_calls = _spy_on_the_layout(monkeypatch)
    graph_env.skills.set("architect", out)
    state = graph_env.state(
        turn_id="turn-2", analyst_figures=scoped("turn-1", _dumps(_q2_figures()))
    )

    updates = architect_node(state)

    expected = [NPS, HEADCOUNT] + code
    assert updates["architect_intent"] == "edit"
    assert updates["error_state"] is None
    assert updates["deck_spec"].resolved_data.figures == expected
    assert _committed_figures(graph_env) == _dumps(expected)
    if edit_form == "operations":
        assert len(layout_calls) == 1
        landed = DeckSpec.from_json(layout_calls[0]["deck_spec"])
        assert landed.resolved_data.figures == expected
        assert [s.content_brief for s in updates["deck_spec"].slides] == [
            "brief-0",
            "the busiest zip code",
            "brief-1",
            "brief-2",
        ]
    else:
        assert updates["target_positions"] == [1]


# ===========================================================================
# Implementer additions (Task 6 impl): behaviour beyond the brief's pins
# ===========================================================================


def test_a_failed_genie_call_reaches_the_model_spotlighted(graph_env, monkeypatch):
    """Global constraint: everything Genie One returns reaches the model only
    through ``spotlight("genie_one", ...)``, including an isError reply's text,
    which the loop's generic ``Tool error:`` answer would hand over raw."""
    _sign_in()
    _set_agent_config(graph_env, graph_env.session_id, GENIE_ONE_ONLY)
    recorded_text = load("error_bad_response_id")["content"][0]["text"]
    _serve(monkeypatch, _Replay({"genie_ask": [load("error_bad_response_id")]}))
    output = AnalystOutput(outcome="missing_data", gap="Genie One could not answer.")
    runtime = _install(monkeypatch, _ToolLoopRuntime(output, [Q1]))

    _run_analyst(_analyst_state(graph_env))

    assert runtime.tool_texts == [
        spotlight("genie_one", f"Genie One could not answer: {recorded_text}")
    ]


def test_an_exact_repeat_from_a_second_analyst_round_is_committed_once(graph_env):
    """Two analyst rounds in one turn that gathered the same figures concatenate
    on ``analyst_figures``; ``resolved_data`` carries each (key, value) once."""
    code = _q1_figures()
    graph_env.skills.set("architect", architect_build(_with_figures(make_spec((0,)), [NPS])))

    updates = architect_node(
        graph_env.state(analyst_figures=scoped(TURN, _dumps(code) + _dumps(code)))
    )

    assert updates["deck_spec"].resolved_data.figures == [NPS] + code
    assert _committed_figures(graph_env) == _dumps([NPS] + code)
