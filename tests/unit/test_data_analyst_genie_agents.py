# ruff: noqa: F811 — the graph_env fixture is imported, then requested by name.
"""agent-mode MCP Task 6: Genie Agents in the data analyst; code-owned figures for
every Genie source.

What is pinned (task-6 brief; rulings R1, R4 and R8):

* **Binding.**  The ACTOR's ``genie`` entries (Genie Agents, curated Genie spaces)
  join the analyst's toolset when a user client is bound and the token's scopes
  do not rule out ``dashboards.genie``: beside Genie One (Genie One's toolset,
  6 calls / 300 s), alone (``ANALYST_GATEWAY_MAX_CALLS`` /
  ``ANALYST_GATEWAY_BUDGET_SECONDS`` clipped to the turn deadline, or the Gateway
  pass's budget left), and when Genie One cannot run (the node branches on
  ``_genie_one_run``'s RESULT, not on the config).  A token whose known scopes
  lack ``dashboards.genie`` binds none and says the consent message once.
* **The retry** without Gateway tools keeps the Genie Agents, built FRESH: a
  failed first attempt's answers and question counts are discarded.
* **Figures** are code-built from every Genie answer (Genie One's first, then each
  Genie Agent tool's in tool order), carry the source ``"Genie Agent · <space
  name>"`` (R1), and the block header names every distinct figure source; with
  Genie One alone it is byte-identical to today's.
* **Chat.**  A Genie Agent's progress row is ``"Asking <space_name>: <question>"``
  with ``tool_name "genie"`` and ``tool_input {"agent", "question"}``: on the row,
  and TOP-LEVEL on the SSE event.  A refusal says its notice once per space
  (``_GatewayNotices.say_once`` under the key ``genie_agent:<space_id>``); a
  missing scope says the consent message once.  "Once" is per turn with a Gateway
  pass and per analyst run without one (R8).
* **Conversations** are persisted on the actor's row, that space's entry only
  (``SessionManager.set_genie_agent_conversation_id``); a failed write never fails
  the run.
* **The architect** owns no figure whose source ``is_genie_source``: its own typed
  Genie Agent figures give way to the code's, a prior spec's Genie Agent figures
  are re-applied verbatim on a later turn, and a figure whose source merely
  equals a space name ("Sales") stays the architect's (R1, Review Focus 5).

How the tests are built:

* ``graph_env`` (SQLite, the production schema) and the analyst-state helpers of
  ``test_data_analyst_genie_one.py``; Genie One is that file's recorded replay.
* **Genie Agents are faked at the SDK's GenieAPI.**  Every ``GenieAgentClient``
  the code builds (whatever path builds it) is handed :class:`_Genie` as its
  ``genie_factory``, so the REAL client and the REAL ``GenieAgentTool`` run.
  :class:`_Genie` answers in GenieAPI's own shapes (``Wait``, SDK ``from_dict``
  objects), binds every call against GenieAPI's signature, and records the
  identity each client was built with.
* The model is ``tests/fixtures/graph_tool_runtime.FakeRuntime``: tool calls are
  answered through the production dispatcher.  Answer callbacks never assert (the
  node catches what a bound call raises); they play a tool only if the call
  carries it, and the test asserts afterwards.
* Tokens: that file's ``TOKEN`` is ``"sql ai-gateway"``, so tokens that must bind
  a Genie Agent carry ``dashboards.genie`` (built with its ``_jwt``).

Three cases pass before Task 6 too, by design (they are guards, and say so): the
harness check, the no-user-client test and the "nothing-can-run" consent case.
"""

from __future__ import annotations

import copy
import inspect
import queue
import threading
import time
from typing import Any, Dict, List, Optional, Sequence

import pytest
from databricks.sdk.errors import NotFound, PermissionDenied, Unauthenticated
from databricks.sdk.service._internal import Wait
from databricks.sdk.service.dashboards import (
    GenieAPI,
    GenieGetMessageQueryResultResponse,
    GenieMessage,
    GenieStartConversationResponse,
)

from src.api.schemas.agent_config import GenieOneTool, GenieTool, resolve_agent_config
from src.api.schemas.streaming import StreamEventType
from src.api.services.session_manager import SessionManager, get_session_manager
from src.core.scope_errors import consent_message
from src.domain.deck_spec import DeckSpec, ResolvedData, ResolvedFigure
from src.domain.skill_io import AnalystOutput, ArchitectOutput
from src.domain.slide_operations import DeckChanges, SlideContent, SlideOperation
from src.services.agent_runtime import AgentAssemblyContext
from src.services.agent_tools import genie_agent
from src.services.agent_tools.genie_agent import GenieAgentClient, GenieAgentTool
from src.services.agent_tools.genie_one import (
    GenieOneAnswer,
    GenieOneQueryResult,
    figures_from_answer,
)
from src.services.agent_tools.registry import (
    GENIE_TOOL_NAME,
    GenieOneAgentTool,
    build_genie_agent_tools,
)
from src.services.agent_tools.toolset import AgentToolset, ToolAccessError
from src.services.graph import nodes
from src.services.graph.nodes import _with_genie_figures, architect_node
from src.services.graph.state import scoped
from tests.fixtures.graph_tool_runtime import FakeRuntime, fold, install_runtime
from tests.unit.conftest_graph import (  # noqa: F401 — graph_env is a fixture
    architect_build,
    graph_env,
    make_spec,
)
from tests.unit.test_data_analyst_genie_one import (
    APP_CLIENT_ID,
    DEEP_LINK,
    GRANT_MESSAGE,
    HEADCOUNT,
    HOST,
    NPS,
    Q1,
    Q1_FIGURES,
    Q1_MESSAGE,
    REQUEST,
    REQUEST_ID,
    SYNTHESIS,
    THREE,
    TOKEN,
    _add_contributor,
    _committed_figures,
    _dumps,
    _HarnessAbort,
    _jwt,
    _persist,
    _q1_figures,
    _raw_agent_config,
    _Replay,
    _retyped,
    _run_analyst,
    _serve,
    _set_agent_config,
    _sign_in,
    _spy_on_the_layout,
    _with_figures,
    q1_replies,
    recorded_missing_scope_exception,
)
from tests.unit.test_data_analyst_genie_one import (
    _analyst_state as _genie_one_analyst_state,
)
from tests.unit.test_graph_gateway_mcp import (
    WEB,
    WEB_ANALYST_ROW,
    _entry,
    _gateway_deck,
    _loop_gave_up,
    _Service,
    _tools_failed,
    _usage_vals,
    _web_result,
    _web_tools,
)

TURN = "turn-1"

#: U+00B7 MIDDLE DOT, spelled out so no editor can swap it for another dot.
DOT = "·"
SALES_SOURCE = f"Genie Agent {DOT} Sales"
MARKETING_SOURCE = f"Genie Agent {DOT} Marketing"

SALES_ID = "sp-sales"
MARKETING_ID = "sp-marketing"
SALES = {"type": "genie", "space_id": SALES_ID, "space_name": "Sales"}
MARKETING = {"type": "genie", "space_id": MARKETING_ID, "space_name": "Marketing"}
GENIE_ONE = {"type": "genie_one"}
WEB_ENTRY = _entry(WEB, "Web Search")

#: The model-facing names ``genie_agent_tool_names`` gives these spaces (Task 5).
SALES_TOOL = "genie_agent_sales"
MARKETING_TOOL = "genie_agent_marketing"

Q_SALES = "Which regions brought in the most revenue last quarter?"
Q_SALES_2 = "And how did that compare with the quarter before?"
Q_MARKETING = "Which channels brought in the most leads?"

#: The signed-in user's tokens.  ``TOKEN`` (imported) is ``"sql ai-gateway"``: no
#: ``dashboards.genie``.
TOKEN_ALL = _jwt(
    {
        "client_id": APP_CLIENT_ID,
        "sub": "analyst@example.com",
        "scope": "sql ai-gateway dashboards.genie",
    }
)
TOKEN_GENIE_SPACES_ONLY = _jwt(
    {"client_id": APP_CLIENT_ID, "sub": "analyst@example.com", "scope": "sql dashboards.genie"}
)
TOKEN_NEITHER = _jwt(
    {"client_id": APP_CLIENT_ID, "sub": "analyst@example.com", "scope": "sql offline_access"}
)

CONSENT = consent_message(oauth_client_id=APP_CLIENT_ID)

#: Sales' result: two regions' revenue (figures keyed by region).
REVENUE = (("region", "STRING"), ("revenue", "LONG"))
SALES_ROWS = (("East", "1250000"), ("West", "980000"))
SALES_FIGURES = [
    ("revenue (region=East)", "1250000", SALES_SOURCE),
    ("revenue (region=West)", "980000", SALES_SOURCE),
]
#: Marketing's result: two channels' leads.
LEADS = (("channel", "STRING"), ("leads", "LONG"))
MARKETING_ROWS = (("Email", "420"), ("Paid search", "310"))
MARKETING_FIGURES = [
    ("leads (channel=Email)", "420", MARKETING_SOURCE),
    ("leads (channel=Paid search)", "310", MARKETING_SOURCE),
]


def refused(space_name: str) -> str:
    """The exact notice a Genie Agent refusal says (task-6 brief)."""
    return (
        f"{space_name} refused the request. You may need access to that Genie Agent; "
        "ask its owner to share it with you."
    )


def not_found(space_name: str) -> str:
    """The exact notice a deleted or unshared Genie Agent says (final review, fix A4)."""
    return (
        f"{space_name} could not be found. It may have been deleted, or not shared with "
        "you; ask its owner, or remove it from this deck."
    )


def space_link(space_id: str, conversation_id: Optional[str] = None) -> str:
    """The deep link the real client gives a Genie Agent answer."""
    return f"{HOST}/genie/rooms/{space_id}/chats/{conversation_id or 'conv-' + space_id}"


def _figure_dicts(triples: Sequence[tuple]) -> List[Dict[str, str]]:
    return [{"key": k, "value": v, "source": s} for k, v, s in triples]


def _triples(figures: Sequence[ResolvedFigure]) -> List[tuple]:
    return [(f.key, f.value, f.source) for f in figures]


def _info(rows: Sequence[Dict[str, Any]]) -> List[str]:
    return [row["content"] for row in rows if row["message_type"] == "info"]


def _analyst_state(env, **overrides) -> Dict[str, Any]:
    """The analyst's state, 5 s into the turn unless overridden."""
    overrides.setdefault("turn_started_at", time.time() - 5)
    return _genie_one_analyst_state(env, **overrides)


def _split_wrapper(message: str) -> tuple:
    """``(prose before the spotlight wrapper, what the wrapper holds)``; the
    wrapper's ``source`` attribute is not pinned here."""
    prose, opener, rest = message.partition('<untrusted-data source="')
    assert opener, f"no spotlight wrapper in {message!r}"
    inside = rest.split('">\n', 1)[1]
    closer = "\n</untrusted-data>"
    assert inside.endswith(closer), inside
    return prose, inside[: -len(closer)]


# ---------------------------------------------------------------------------
# The fake Genie Agents: GenieAPI itself, per space
# ---------------------------------------------------------------------------


def _refuse_to_wait(**_: Any) -> Any:
    raise _HarnessAbort("Wait.result() was called: the client must poll get_message itself")


def _bind(method: str, args: tuple, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """The call's arguments, bound against GenieAPI's own signature."""
    bound = inspect.signature(getattr(GenieAPI, method)).bind(None, *args, **kwargs)
    bound.apply_defaults()
    arguments = dict(bound.arguments)
    arguments.pop("self")
    return arguments


def _query_result_body(columns: Sequence[tuple], rows: Sequence[Sequence[Any]]) -> Dict[str, Any]:
    """A GET .../attachments/{id}/query-result body, all rows inline."""
    return {
        "statement_response": {
            "statement_id": "01f0bf6d-0000-1111-2222-333344445555",
            "status": {"state": "SUCCEEDED"},
            "manifest": {
                "format": "JSON_ARRAY",
                "schema": {
                    "column_count": len(columns),
                    "columns": [
                        {
                            "name": name,
                            "type_text": type_name,
                            "type_name": type_name,
                            "position": i,
                        }
                        for i, (name, type_name) in enumerate(columns)
                    ],
                },
                "total_chunk_count": 1,
                "chunks": [{"chunk_index": 0, "row_offset": 0, "row_count": len(rows)}],
                "total_row_count": len(rows),
            },
            "result": {
                "chunk_index": 0,
                "row_offset": 0,
                "row_count": len(rows),
                "data_array": [list(row) for row in rows],
            },
        }
    }


class _Space:
    """One Genie Agent (a Genie space), scripted.

    Each question takes the next reply: ``(columns, rows)`` (a COMPLETED answer with
    one query attachment and one text attachment) or an exception (raised by the
    call that sends the question).  ``asks`` records each question, with the
    conversation it continued (``create_message``) or without (a new one).
    ``on_ask(space_id, question)`` runs as each question is sent.
    """

    def __init__(self, space_id: str, replies: Sequence[Any] = (), *, on_ask: Any = None) -> None:
        self.space_id = space_id
        self.replies = list(replies)
        self.on_ask = on_ask
        self.asks: List[Dict[str, Any]] = []
        self.messages: Dict[str, Any] = {}
        self._conversations = 0
        self._lock = threading.Lock()

    def ask(self, question: str, conversation_id: Optional[str]) -> str:
        """Record *question*; raise its scripted exception, or return its message id."""
        with self._lock:
            entry: Dict[str, Any] = {"question": question}
            if conversation_id is not None:
                entry["conversation_id"] = conversation_id
            self.asks.append(entry)
            if not self.replies:
                raise _HarnessAbort(f"unscripted question to {self.space_id}: {question!r}")
            reply = self.replies.pop(0)
            message_id = f"msg-{self.space_id}-{len(self.asks)}"
        if self.on_ask is not None:
            self.on_ask(self.space_id, question)
        if isinstance(reply, BaseException):
            raise reply
        self.messages[message_id] = reply
        return message_id

    def new_conversation(self) -> str:
        with self._lock:
            self._conversations += 1
            n = self._conversations
        return f"conv-{self.space_id}" if n == 1 else f"conv-{self.space_id}-{n}"


class _Genie:
    """GenieAPI's shape, routed by ``space_id`` to one :class:`_Space` each.

    :meth:`install` hands every ``GenieAgentClient`` the code under test builds this
    fake as its ``genie_factory`` (and a sleep that never sleeps), and records the
    identity it was built with in :attr:`built`.  A call for a space this test did
    not script aborts the test (a ``BaseException``, so no ``except Exception`` in
    the code under test can turn it into a pass).
    """

    MAX_CALLS = 200

    def __init__(self, *spaces: _Space) -> None:
        self.spaces = {space.space_id: space for space in spaces}
        self.built: List[Dict[str, Any]] = []
        self.calls: List[tuple] = []
        self._lock = threading.Lock()

    def install(self, monkeypatch) -> "_Genie":
        fake = self

        def init(client, *args, **kwargs):
            with fake._lock:
                fake.built.append(
                    {
                        "host": kwargs.get("host"),
                        "token": kwargs.get("token"),
                        "space_id": kwargs.get("space_id"),
                    }
                )
            kwargs.update(genie_factory=fake.factory, sleep=fake.sleep)
            _REAL_GENIE_AGENT_CLIENT_INIT(client, *args, **kwargs)

        monkeypatch.setattr(GenieAgentClient, "__init__", init)
        return self

    def factory(self, host: str, token: str) -> "_Genie":
        return self

    def sleep(self, seconds: float) -> None:
        with self._lock:
            self.calls.append(("sleep", {"seconds": seconds}))

    def _enter(self, method: str, args: tuple, kwargs: Dict[str, Any]) -> tuple:
        arguments = _bind(method, args, kwargs)
        with self._lock:
            self.calls.append((method, arguments))
            if len(self.calls) > self.MAX_CALLS:
                raise _HarnessAbort("runaway loop: the client never stopped polling")
        space = self.spaces.get(arguments["space_id"])
        if space is None:
            raise _HarnessAbort(f"a Genie Agent call for unscripted space {arguments!r}")
        return space, arguments

    def start_conversation(self, *args: Any, **kwargs: Any) -> Wait:
        space, arguments = self._enter("start_conversation", args, kwargs)
        message_id = space.ask(arguments["content"], None)
        conversation_id = space.new_conversation()
        body = {"conversation_id": conversation_id, "message_id": message_id}
        return Wait(
            _refuse_to_wait,
            response=GenieStartConversationResponse.from_dict(body),
            conversation_id=conversation_id,
            message_id=message_id,
            space_id=space.space_id,
        )

    def create_message(self, *args: Any, **kwargs: Any) -> Wait:
        space, arguments = self._enter("create_message", args, kwargs)
        conversation_id = arguments["conversation_id"]
        message_id = space.ask(arguments["content"], conversation_id)
        body = {
            "id": message_id,
            "message_id": message_id,
            "conversation_id": conversation_id,
            "space_id": space.space_id,
            "content": arguments["content"],
            "status": "SUBMITTED",
        }
        return Wait(
            _refuse_to_wait,
            response=GenieMessage.from_dict(body),
            conversation_id=conversation_id,
            message_id=message_id,
            space_id=space.space_id,
        )

    def get_message(self, *args: Any, **kwargs: Any) -> GenieMessage:
        space, arguments = self._enter("get_message", args, kwargs)
        message_id = arguments["message_id"]
        if message_id not in space.messages:
            raise _HarnessAbort(f"get_message for an unsent message {arguments!r}")
        return GenieMessage.from_dict(
            {
                "id": message_id,
                "message_id": message_id,
                "conversation_id": arguments["conversation_id"],
                "space_id": space.space_id,
                "content": "question",
                "status": "COMPLETED",
                "attachments": [
                    {
                        "attachment_id": f"att-{message_id}",
                        "query": {
                            "title": "Result",
                            "query": f"SELECT * FROM main.{space.space_id.replace('-', '_')}.t",
                            "statement_id": f"stmt-{message_id}",
                        },
                    },
                    {
                        "attachment_id": f"txt-{message_id}",
                        "text": {"content": f"Answer from {space.space_id}."},
                    },
                ],
            }
        )

    def get_message_attachment_query_result(
        self, *args: Any, **kwargs: Any
    ) -> GenieGetMessageQueryResultResponse:
        space, arguments = self._enter("get_message_attachment_query_result", args, kwargs)
        columns, rows = space.messages[arguments["message_id"]]
        return GenieGetMessageQueryResultResponse.from_dict(
            copy.deepcopy(_query_result_body(columns, rows))
        )

    def start_conversation_and_wait(self, *args: Any, **kwargs: Any) -> Any:
        raise _HarnessAbort("start_conversation_and_wait called: the client must poll")

    def create_message_and_wait(self, *args: Any, **kwargs: Any) -> Any:
        raise _HarnessAbort("create_message_and_wait called: the client must poll")


#: Captured at import, before any test patches it, so installing a second fake in
#: one test never chains through the first.
_REAL_GENIE_AGENT_CLIENT_INIT = GenieAgentClient.__init__


@pytest.fixture(autouse=True)
def _no_real_workspace_client(monkeypatch):
    """A real ``WorkspaceClient`` for a Genie Agent means the fake was bypassed."""

    class _Refuse:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise _HarnessAbort("a real WorkspaceClient was built for a Genie Agent")

    monkeypatch.setattr(genie_agent, "WorkspaceClient", _Refuse)
    monkeypatch.setattr(genie_agent, "Config", _Refuse, raising=False)


# ---------------------------------------------------------------------------
# Decks and the model
# ---------------------------------------------------------------------------


def _deck(
    env,
    monkeypatch,
    entries: Sequence[Dict[str, Any]],
    *,
    spaces: Sequence[_Space] = (),
    token: Optional[str] = TOKEN_ALL,
) -> _Genie:
    """The owner's deck with these entries (no Gateway pass), the user signed in
    with *token* (``None``: nobody is), and these spaces scripted."""
    _set_agent_config(env, env.session_id, {"tools": [dict(e) for e in entries]})
    if token is not None:
        _sign_in(token)
    return _Genie(*spaces).install(monkeypatch)


def _gateway_genie_deck(
    env,
    monkeypatch,
    entries: Sequence[Dict[str, Any]],
    *,
    spaces: Sequence[_Space] = (),
    web: Optional[_Service] = None,
    token: str = TOKEN_ALL,
) -> _Genie:
    """The same, with the analyst's Web Search Gateway connection registered (the
    entries add it), so the run has a Gateway pass."""
    _gateway_deck(
        env,
        monkeypatch,
        entries=entries,
        rows=[WEB_ANALYST_ROW],
        services=[web if web is not None else _Service(WEB, _web_tools())],
        token=token,
    )
    return _Genie(*spaces).install(monkeypatch)


def _success(sources: Sequence[str]) -> AnalystOutput:
    return AnalystOutput(outcome="success", synthesis=SYNTHESIS, sources=list(sources))


def _answer(*asks: tuple, sources: Sequence[str] = (), output: Optional[AnalystOutput] = None):
    """The model: ask each ``(tool, question)`` the call carries, in order, then answer."""

    def answer(call):
        for name, question in asks:
            if call.has_tool(name):
                call.use(name, {"question": question})
        return output if output is not None else _success(sources)

    return answer


def _install(monkeypatch, *answers: Any) -> FakeRuntime:
    return install_runtime(monkeypatch, FakeRuntime(data_analyst=list(answers)))


def _tool(call, name: str) -> Any:
    return {tool.name: tool for tool in call.toolset.tools}[name]


# ===========================================================================
# The harness
# ===========================================================================


def test_the_fake_genie_is_read_by_the_real_genie_agent_tool(monkeypatch):
    """The fake is read by Task 5's REAL builder, client and tool the way the tests
    below assume: a figure per region with the Genie Agent source, the deep link, a
    follow-up continuing the conversation, and a 403 / a missing-scope error mapped
    to ``access_denied`` / ``missing_scope``.  A guard on the harness: it passes
    before Task 6 too."""
    said: List[tuple] = []
    sales = _Space(SALES_ID, [(REVENUE, SALES_ROWS), (REVENUE, SALES_ROWS)])
    marketing = _Space(
        MARKETING_ID, [PermissionDenied("Forbidden"), recorded_missing_scope_exception()]
    )
    genie = _Genie(sales, marketing).install(monkeypatch)
    tools = build_genie_agent_tools(
        resolve_agent_config({"tools": [SALES, MARKETING]}),
        host=HOST,
        token=TOKEN_ALL,
        on_question=lambda space, question: said.append((space, question)),
        session_id="session-x",
    )
    assert [tool.name for tool in tools] == [SALES_TOOL, MARKETING_TOOL]
    sales_tool, marketing_tool = tools

    def ask(tool, question):
        args = tool.args_schema.model_validate({"question": question})
        return tool.run(args, remaining_seconds=60)

    ask(sales_tool, Q_SALES)
    ask(sales_tool, Q_SALES_2)
    kinds = []
    for question in (Q_MARKETING, Q_MARKETING):
        with pytest.raises(ToolAccessError) as info:
            ask(marketing_tool, question)
        kinds.append((info.value.kind, info.value.tool_name))

    assert said == [("Sales", Q_SALES), ("Sales", Q_SALES_2)] + [("Marketing", Q_MARKETING)] * 2
    assert sales.asks == [
        {"question": Q_SALES},
        {"question": Q_SALES_2, "conversation_id": f"conv-{SALES_ID}"},
    ]
    assert sales_tool.conversation_id == f"conv-{SALES_ID}"
    first = sales_tool.answers[0]
    assert (first.status, first.source) == ("completed", SALES_SOURCE)
    assert first.deep_link == space_link(SALES_ID)
    assert _triples(figures_from_answer(first)) == SALES_FIGURES
    assert kinds == [("access_denied", MARKETING_TOOL), ("missing_scope", MARKETING_TOOL)]
    assert genie.built == [
        {"host": HOST, "token": TOKEN_ALL, "space_id": SALES_ID},
        {"host": HOST, "token": TOKEN_ALL, "space_id": MARKETING_ID},
    ]
    assert [name for name, _ in genie.calls if name == "sleep"] == []


# ===========================================================================
# Binding
# ===========================================================================


def test_a_genie_agent_alone_gives_the_analyst_a_toolset(graph_env, monkeypatch):
    """A deck with one Genie Agent and no Genie One: the analyst's one call carries a
    toolset of the REAL Genie Agent tool, with the analyst's budget (6 calls /
    300 s, R4), built as the signed-in user; the tool asks its own space."""
    sales = _Space(SALES_ID, [(REVENUE, SALES_ROWS)])
    genie = _deck(graph_env, monkeypatch, [SALES], spaces=[sales])
    genie_one_built = _serve(monkeypatch, _Replay({}))
    runtime = _install(monkeypatch, _answer((SALES_TOOL, Q_SALES), sources=[SALES_SOURCE]))

    t = _run_analyst(graph_env, _analyst_state(graph_env))

    (call,) = runtime.calls_for("data_analyst")
    assert isinstance(call.toolset, AgentToolset)
    assert call.tool_names == [SALES_TOOL]
    tool = _tool(call, SALES_TOOL)
    assert isinstance(tool, GenieAgentTool)
    assert (tool.space_id, tool.space_name, tool.source) == (SALES_ID, "Sales", SALES_SOURCE)
    assert call.at_start == (6, 300.0, 0)
    assert call.context == AgentAssemblyContext(False, graph_env.session_id, graph_env.session_id)
    assert call.payload == {"data_request": REQUEST, "deck_purpose": None}
    # Built as the signed-in user (captured in the node thread); asked its own space.
    assert genie.built == [{"host": HOST, "token": TOKEN_ALL, "space_id": SALES_ID}]
    assert sales.asks == [{"question": Q_SALES}]
    assert call.tool_texts[0].startswith('<untrusted-data source="genie_agent">')
    # No Genie One entry: no Genie One client.  No Gateway pass: no gateway_* key.
    assert genie_one_built == []
    assert set(t.updates) == {"architect_message", "analyst_figures", "analyst_rounds"}
    assert t.updates["analyst_rounds"] == scoped(TURN, [{"answers": 1}])


def test_a_genie_agent_beside_genie_one_shares_one_toolset(graph_env, monkeypatch):
    """Genie One plus a Genie Agent: ONE toolset holding both (Genie One's toolset
    with the Genie Agent as an extra tool: 6 calls / 300 s), each built as the
    signed-in user, each asked once."""
    sales = _Space(SALES_ID, [(REVENUE, SALES_ROWS)])
    genie = _deck(graph_env, monkeypatch, [GENIE_ONE, SALES], spaces=[sales])
    server = _Replay(q1_replies())
    genie_one_built = _serve(monkeypatch, server)
    runtime = _install(
        monkeypatch,
        _answer((GENIE_TOOL_NAME, Q1), (SALES_TOOL, Q_SALES), sources=["Genie One", SALES_SOURCE]),
    )

    t = _run_analyst(graph_env, _analyst_state(graph_env))

    (call,) = runtime.calls_for("data_analyst")
    assert call.tool_names == sorted([GENIE_TOOL_NAME, SALES_TOOL])
    assert isinstance(_tool(call, GENIE_TOOL_NAME), GenieOneAgentTool)
    assert isinstance(_tool(call, SALES_TOOL), GenieAgentTool)
    assert call.at_start == (6, 300.0, 0)
    assert genie_one_built == [{"host": HOST, "token": TOKEN_ALL}]
    assert genie.built == [{"host": HOST, "token": TOKEN_ALL, "space_id": SALES_ID}]
    assert server.asks() == [{"question": Q1}]
    assert sales.asks == [{"question": Q_SALES}]
    assert t.updates["analyst_rounds"] == scoped(TURN, [{"answers": 2}])


def test_genie_agents_still_bind_when_genie_one_cannot_run(graph_env, monkeypatch):
    """Branch on the RESULT, not the config: Genie One is configured but the token
    lacks ``ai-gateway`` (it has ``dashboards.genie``), so Genie One cannot run.  The
    Genie Agent still binds, alone (6 / 300), Genie One's client is never built, and
    the consent message is said exactly once."""
    sales = _Space(SALES_ID, [(REVENUE, SALES_ROWS)])
    genie = _deck(
        graph_env, monkeypatch, [GENIE_ONE, SALES], spaces=[sales], token=TOKEN_GENIE_SPACES_ONLY
    )
    server = _Replay(q1_replies())
    genie_one_built = _serve(monkeypatch, server)
    runtime = _install(
        monkeypatch,
        _answer((GENIE_TOOL_NAME, Q1), (SALES_TOOL, Q_SALES), sources=[SALES_SOURCE]),
    )

    t = _run_analyst(graph_env, _analyst_state(graph_env))

    (call,) = runtime.calls_for("data_analyst")
    assert call.tool_names == [SALES_TOOL]
    assert call.at_start == (6, 300.0, 0)
    assert genie_one_built == [] and server.calls == []
    assert genie.built == [{"host": HOST, "token": TOKEN_GENIE_SPACES_ONLY, "space_id": SALES_ID}]
    assert sales.asks == [{"question": Q_SALES}]
    assert _info(t.rows).count(CONSENT) == 1
    assert t.updates["analyst_figures"] == scoped(TURN, _figure_dicts(SALES_FIGURES))


@pytest.mark.parametrize("with_pass", [False, True], ids=["no-gateway-pass", "gateway-pass"])
def test_a_genie_agent_only_toolset_is_clipped_to_the_turn_deadline(
    graph_env, monkeypatch, with_pass
):
    """R4: without Genie One, the Genie Agents' toolset holds what is left of the
    turn.  650 s in, it gets the turn's last 50 s (6 calls); 701 s in, nothing is
    bound and no space is asked.  Without a Gateway pass the numbers come from
    ``turn_budget`` on the turn's start; with one, from the pass's budget left (its
    Gateway tools ride in the same toolset)."""
    sales = _Space(SALES_ID, [])
    web = _Service(WEB, _web_tools())
    if with_pass:
        _gateway_genie_deck(graph_env, monkeypatch, [SALES, WEB_ENTRY], spaces=[sales], web=web)
    else:
        _deck(graph_env, monkeypatch, [SALES], spaces=[sales])
    runtime = _install(monkeypatch, _success([SALES_SOURCE]))

    _run_analyst(graph_env, _analyst_state(graph_env, turn_started_at=time.time() - 650))
    _run_analyst(graph_env, _analyst_state(graph_env, turn_started_at=time.time() - 701))

    late, past = runtime.calls_for("data_analyst")
    assert late.tool_names == sorted([SALES_TOOL] + (["web_search"] if with_pass else []))
    max_calls, seconds, _ = late.at_start
    assert max_calls == 6
    assert 40.0 < seconds <= 50.0
    assert past.toolset is None
    assert sales.asks == []
    if with_pass:
        assert web.list_calls == 1, "past the deadline nothing is listed"


def test_the_retry_builds_fresh_genie_agent_tools(graph_env, monkeypatch):
    """The call carrying a Gateway tool and the Genie Agent raises; it is made once
    more without the Gateway tool but WITH the Genie Agent, built FRESH: a new
    ``GenieAgentTool`` with no answers and a fresh question count (all three of the
    retry's questions are asked), the Gateway pass's budget left (one Gateway call
    was spent), and only the retry's answers become figures."""
    first_rows = (("East", "111"), ("West", "222"))
    sales = _Space(SALES_ID, [(REVENUE, first_rows)] + [(REVENUE, SALES_ROWS)] * 3)
    web = _Service(WEB, _web_tools(), results={"web_search": _web_result()})
    _gateway_genie_deck(graph_env, monkeypatch, [SALES, WEB_ENTRY], spaces=[sales], web=web)
    seen: Dict[str, Any] = {}
    retry_questions = [f"{Q_SALES} ({n})" for n in (1, 2, 3)]

    def bound(call):
        seen["first_tools"] = call.tool_names
        if call.has_tool(SALES_TOOL):
            call.use(SALES_TOOL, {"question": Q_SALES})
        if call.has_tool("web_search"):
            call.use("web_search", {"query": "regional revenue last quarter"})
        raise _loop_gave_up()

    def retry(call):
        seen["retry_tools"] = call.tool_names
        seen["answers_at_start"] = [
            len(tool.answers)
            for tool in (call.toolset.tools if call.toolset is not None else ())
            if isinstance(tool, GenieAgentTool)
        ]
        for question in retry_questions:
            if call.has_tool(SALES_TOOL):
                call.use(SALES_TOOL, {"question": question})
        return _success([SALES_SOURCE])

    runtime = _install(monkeypatch, bound, retry)

    t = _run_analyst(graph_env, _analyst_state(graph_env))

    first, second = runtime.calls_for("data_analyst")
    assert seen["first_tools"] == sorted([SALES_TOOL, "web_search"])
    assert seen["retry_tools"] == [SALES_TOOL]
    first_tool, retry_tool = _tool(first, SALES_TOOL), _tool(second, SALES_TOOL)
    assert isinstance(retry_tool, GenieAgentTool)
    assert retry_tool is not first_tool, "the retry reused the failed attempt's tool"
    assert seen["answers_at_start"] == [0]
    assert len(first_tool.answers) == 1
    assert second.payload == first.payload
    # The pass's budget left: one Gateway call was spent by the failed attempt.
    assert second.at_start[0] == 5
    assert 0.0 < second.at_start[1] <= 300.0
    # A fresh question count: every retry question reached the space.
    assert [ask["question"] for ask in sales.asks] == [Q_SALES] + retry_questions
    assert len(retry_tool.answers) == 3
    # The failed attempt's answer (111 / 222) is not a figure; the retry's are.
    assert t.updates["analyst_figures"] == scoped(TURN, _figure_dicts(SALES_FIGURES))
    assert t.updates["analyst_rounds"] == scoped(TURN, [{"answers": 3}])
    assert _info(t.rows).count(_tools_failed("Web Search")) == 1


def test_genie_one_a_genie_agent_and_a_gateway_pass_share_one_toolset_and_retry(
    graph_env, monkeypatch
):
    """Genie One, a Genie Agent and a Gateway pass: the first call carries all three
    in Genie One's toolset (``extra_tools=(*agents, *gateway)``, 6 calls / 300 s).  It
    raises; the retry drops the Gateway tool but keeps Genie One AND the Genie Agent,
    the agent built FRESH (a new tool with no answers), and only the retry's answers
    become figures."""
    first_rows = (("East", "111"), ("West", "222"))
    sales = _Space(SALES_ID, [(REVENUE, first_rows), (REVENUE, SALES_ROWS)])
    web = _Service(WEB, _web_tools(), results={"web_search": _web_result()})
    _gateway_genie_deck(
        graph_env, monkeypatch, [GENIE_ONE, SALES, WEB_ENTRY], spaces=[sales], web=web
    )
    _serve(monkeypatch, _Replay(q1_replies()))
    seen: Dict[str, Any] = {}

    def bound(call):
        seen["first_tools"] = call.tool_names
        if call.has_tool(SALES_TOOL):
            call.use(SALES_TOOL, {"question": Q_SALES})
        if call.has_tool("web_search"):
            call.use("web_search", {"query": "regional revenue last quarter"})
        raise _loop_gave_up()

    def retry(call):
        seen["retry_tools"] = call.tool_names
        seen["answers_at_start"] = [
            len(tool.answers)
            for tool in (call.toolset.tools if call.toolset is not None else ())
            if isinstance(tool, GenieAgentTool)
        ]
        if call.has_tool(SALES_TOOL):
            call.use(SALES_TOOL, {"question": Q_SALES_2})
        return _success([SALES_SOURCE])

    runtime = _install(monkeypatch, bound, retry)

    t = _run_analyst(graph_env, _analyst_state(graph_env))

    first, second = runtime.calls_for("data_analyst")
    assert seen["first_tools"] == sorted([GENIE_TOOL_NAME, SALES_TOOL, "web_search"])
    assert first.at_start == (6, 300.0, 0)
    assert seen["retry_tools"] == sorted([GENIE_TOOL_NAME, SALES_TOOL])
    assert isinstance(_tool(second, GENIE_TOOL_NAME), GenieOneAgentTool)
    first_tool, retry_tool = _tool(first, SALES_TOOL), _tool(second, SALES_TOOL)
    assert isinstance(retry_tool, GenieAgentTool)
    assert retry_tool is not first_tool, "the retry reused the failed attempt's tool"
    assert seen["answers_at_start"] == [0]
    assert len(first_tool.answers) == 1 and len(retry_tool.answers) == 1
    assert [ask["question"] for ask in sales.asks] == [Q_SALES, Q_SALES_2]
    # The failed attempt's answer (111 / 222) is not a figure; the retry's are.
    assert t.updates["analyst_figures"] == scoped(TURN, _figure_dicts(SALES_FIGURES))
    assert t.updates["analyst_rounds"] == scoped(TURN, [{"answers": 1}])
    assert _info(t.rows).count(_tools_failed("Web Search")) == 1


def test_genie_agents_without_a_user_client_bind_nothing(graph_env, monkeypatch):
    """Identity: a Genie Agent runs only as the signed-in user.  With an entry and no
    user client (production fails closed) no client is built, the call carries no
    toolset, and nothing is said.  A guard: it passes before Task 6 too."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    sales = _Space(SALES_ID, [(REVENUE, SALES_ROWS)])
    genie = _deck(graph_env, monkeypatch, [SALES], spaces=[sales], token=None)
    runtime = _install(monkeypatch, _answer((SALES_TOOL, Q_SALES), sources=["genie"]))

    t = _run_analyst(graph_env, _analyst_state(graph_env))

    (call,) = runtime.calls_for("data_analyst")
    assert call.toolset is None
    assert genie.built == [] and sales.asks == []
    assert _info(t.rows) == [f"{SYNTHESIS}\nSources: genie"]


@pytest.mark.parametrize(
    ("entries", "token", "tools", "at_start"),
    [
        ([SALES], TOKEN, [], None),
        ([GENIE_ONE, SALES], TOKEN, [GENIE_TOOL_NAME], (3, 300.0, 0)),
        ([SALES, WEB_ENTRY], TOKEN, ["web_search"], (6, 300.0, 0)),
        ([GENIE_ONE, SALES], TOKEN_NEITHER, [], None),
    ],
    ids=["genie-agent-only", "beside-genie-one", "beside-a-gateway-pass", "nothing-can-run"],
)
def test_a_token_without_dashboards_genie_says_consent_and_binds_no_genie_agents(
    graph_env, monkeypatch, entries, token, tools, at_start
):
    """The token's scopes are known and lack ``dashboards.genie``: no Genie Agent is
    bound or asked, and the consent message is said ONCE.  What else can run runs
    exactly as it would without the Genie Agent: Genie One's own toolset (3 / 300),
    or the Gateway tools alone, whose pass records the consent on
    ``gateway_usage``.  "nothing-can-run" (the token lacks ai-gateway too) is a
    guard that Genie One's consent and the Genie Agents' are one message; it passes
    before Task 6 too."""
    sales = _Space(SALES_ID, [(REVENUE, SALES_ROWS)])
    if WEB_ENTRY in entries:
        _gateway_genie_deck(graph_env, monkeypatch, entries, spaces=[sales], token=token)
    else:
        _deck(graph_env, monkeypatch, entries, spaces=[sales], token=token)
    _serve(monkeypatch, _Replay(q1_replies()))
    runtime = _install(
        monkeypatch,
        _answer((GENIE_TOOL_NAME, Q1), (SALES_TOOL, Q_SALES), sources=["Genie One"]),
    )

    t = _run_analyst(graph_env, _analyst_state(graph_env))

    (call,) = runtime.calls_for("data_analyst")
    assert call.tool_names == sorted(tools)
    if at_start is None:
        assert call.toolset is None
    else:
        assert call.at_start == at_start
    assert sales.asks == []
    info = _info(t.rows)
    assert info.count(CONSENT) == 1
    assert refused("Sales") not in info
    if WEB_ENTRY in entries:
        assert [entry["notified"] for entry in _usage_vals(t.updates)] == [["consent"]]


# ===========================================================================
# Figures
# ===========================================================================


def test_genie_agent_figures_are_code_built_with_its_source(graph_env, monkeypatch):
    """The figures are built by CODE from the Genie Agent's result rows, with the
    source ``"Genie Agent · Sales"`` (R1), never from the model's prose (which
    rounds them).  They are written on ``analyst_figures``, listed for the user as
    text and for the architect inside the spotlight wrapper only."""
    sales = _Space(SALES_ID, [(REVENUE, SALES_ROWS)])
    _deck(graph_env, monkeypatch, [SALES], spaces=[sales])
    prose = "East led with about 1.3M; West had roughly 1M."
    output = AnalystOutput(outcome="success", synthesis=prose, sources=[SALES_SOURCE])
    runtime = _install(monkeypatch, _answer((SALES_TOOL, Q_SALES), output=output))

    t = _run_analyst(graph_env, _analyst_state(graph_env))

    (call,) = runtime.calls_for("data_analyst")
    assert call.tool_names == [SALES_TOOL]
    tool = _tool(call, SALES_TOOL)
    assert [answer.source for answer in tool.answers] == [SALES_SOURCE]
    # Guard: the real client turns these rows into exactly these figures.
    assert _triples(figures_from_answer(tool.answers[0])) == SALES_FIGURES
    assert t.updates["analyst_figures"] == scoped(TURN, _figure_dicts(SALES_FIGURES))
    lines = [f"- {key}: {value}" for key, value, _ in SALES_FIGURES]
    (message,) = [text for text in _info(t.rows) if text.startswith(prose)]
    assert all(line in message.split("\n") for line in lines)
    before, inside = _split_wrapper(t.updates["architect_message"])
    assert before == f"{prose}\nSources: {SALES_SOURCE}\n"
    assert all(line in inside.split("\n") for line in lines)


def test_the_block_header_names_every_genie_source(graph_env, monkeypatch):
    """Genie One and two Genie Agents, asked in the OPPOSITE order to the tools'.
    The answers are Genie One's, then each Genie Agent tool's in tool order (config
    order), so the header names every distinct figure source in that order, the
    figure lines follow it, and each answer's deep link is listed once."""
    sales = _Space(SALES_ID, [(REVENUE, SALES_ROWS)])
    marketing = _Space(MARKETING_ID, [(LEADS, MARKETING_ROWS)])
    _deck(graph_env, monkeypatch, [SALES, GENIE_ONE, MARKETING], spaces=[sales, marketing])
    _serve(monkeypatch, _Replay(q1_replies()))
    sources = ["Genie One", SALES_SOURCE, MARKETING_SOURCE]
    runtime = _install(
        monkeypatch,
        _answer(
            (MARKETING_TOOL, Q_MARKETING),
            (SALES_TOOL, Q_SALES),
            (GENIE_TOOL_NAME, Q1),
            sources=sources,
        ),
    )

    t = _run_analyst(graph_env, _analyst_state(graph_env))

    (call,) = runtime.calls_for("data_analyst")
    assert call.tool_names == sorted([GENIE_TOOL_NAME, SALES_TOOL, MARKETING_TOOL])
    triples = Q1_FIGURES + SALES_FIGURES + MARKETING_FIGURES
    block = (
        f"Figures from Genie One, {SALES_SOURCE}, {MARKETING_SOURCE} "
        "(use these keys in data_references):"
        + "".join(f"\n- {k}: {v}" for k, v, _ in triples)
        + f"\nExplore in Databricks: {DEEP_LINK}"
        + f"\nExplore in Databricks: {space_link(SALES_ID)}"
        + f"\nExplore in Databricks: {space_link(MARKETING_ID)}"
    )
    prose = f"{SYNTHESIS}\nSources: {', '.join(sources)}"
    assert _info(t.rows) == [f"{prose}\n{block}"]
    before, inside = _split_wrapper(t.updates["architect_message"])
    assert before == f"{prose}\n"
    assert inside == block
    assert t.updates["analyst_figures"] == scoped(TURN, _figure_dicts(triples))
    assert t.updates["analyst_rounds"] == scoped(TURN, [{"answers": 3}])


def test_the_block_header_is_unchanged_for_genie_one_alone(graph_env, monkeypatch):
    """A Genie Agent is bound but not asked, so Genie One is the only figure source:
    the header is exactly ``"Figures from Genie One (use these keys in
    data_references):"`` and the user's message is byte-identical to today's."""
    sales = _Space(SALES_ID, [])
    _deck(graph_env, monkeypatch, [GENIE_ONE, SALES], spaces=[sales])
    _serve(monkeypatch, _Replay(q1_replies()))
    runtime = _install(monkeypatch, _answer((GENIE_TOOL_NAME, Q1), sources=["Genie One"]))

    t = _run_analyst(graph_env, _analyst_state(graph_env))

    (call,) = runtime.calls_for("data_analyst")
    assert call.tool_names == sorted([GENIE_TOOL_NAME, SALES_TOOL]), "the Genie Agent is bound"
    assert sales.asks == []
    header = "Figures from Genie One (use these keys in data_references):"
    assert _info(t.rows) == [Q1_MESSAGE]
    assert header in Q1_MESSAGE.split("\n")
    before, inside = _split_wrapper(t.updates["architect_message"])
    assert before == f"{SYNTHESIS}\nSources: Genie One\n"
    assert inside == Q1_MESSAGE.split("Sources: Genie One\n", 1)[1]


# ===========================================================================
# Chat: the progress row
# ===========================================================================


def test_a_genie_agent_progress_row_names_the_agent(graph_env, monkeypatch):
    """``"Asking Sales: <question>"``, said BEFORE the question is sent, on both
    surfaces: a persisted ``tool_call`` row whose metadata is ``tool_name "genie"``
    and ``tool_input {"agent": "Sales", "question": ...}``, and a ``TOOL_CALL``
    event carrying the same ``tool_name`` / ``tool_input`` as TOP-LEVEL fields (the
    ones the frontend's live row reads).  The polling transport turns the row into
    the same event."""
    emitter: queue.Queue = queue.Queue()
    seen_at_ask: List[List[tuple]] = []

    def on_ask(space_id, question):
        seen_at_ask.append(
            [
                (e.content, e.tool_name, e.tool_input)
                for e in list(emitter.queue)
                if e.type == StreamEventType.TOOL_CALL
            ]
        )

    sales = _Space(SALES_ID, [(REVENUE, SALES_ROWS)], on_ask=on_ask)
    _deck(graph_env, monkeypatch, [SALES], spaces=[sales])
    _install(monkeypatch, _answer((SALES_TOOL, Q_SALES), sources=[SALES_SOURCE]))

    t = _run_analyst(graph_env, _analyst_state(graph_env), emitter)

    line = f"Asking Sales: {Q_SALES}"
    tool_input = {"agent": "Sales", "question": Q_SALES}
    progress = [r for r in t.rows if r["message_type"] == "tool_call"]
    assert [(r["role"], r["content"], r["metadata"]) for r in progress] == [
        ("assistant", line, {"tool_name": "genie", "tool_input": tool_input})
    ]
    events = [e for e in t.events if e.type == StreamEventType.TOOL_CALL]
    assert [(e.content, e.tool_name, e.tool_input) for e in events] == [(line, "genie", tool_input)]
    assert seen_at_ask == [[(line, "genie", tool_input)]]
    sm = get_session_manager()
    polled = [
        sm.msg_to_stream_event(m)
        for m in sm.get_messages_for_request(REQUEST_ID)
        if m["message_type"] == "tool_call"
    ]
    assert [(p["type"], p["content"], p["tool_name"], p["tool_input"]) for p in polled] == [
        ("tool_call", line, "genie", tool_input)
    ]


# ===========================================================================
# Conversations
# ===========================================================================


def test_a_genie_agent_conversation_id_is_persisted_on_the_actor_row(graph_env, monkeypatch):
    """Per user per deck: a contributor's Genie Agent conversation is stored on the
    contributor's own row, in that space's entry only; the owner's conversation for
    the same space is neither used nor touched.  The next turn continues it, and an
    unchanged id is not written again."""
    setter = getattr(SessionManager, "set_genie_agent_conversation_id", None)
    assert setter is not None, "SessionManager.set_genie_agent_conversation_id is missing"
    contributor = _add_contributor(graph_env)
    owner_config = {"tools": [dict(SALES, conversation_id="owner-sales-conv")]}
    actor_config = {
        "tools": [
            dict(SALES),
            dict(MARKETING, conversation_id="marketing-conv-7"),
            {"type": "genie_one", "conversation_id": "genie-one-conv"},
        ]
    }
    _set_agent_config(graph_env, graph_env.session_id, owner_config)
    _set_agent_config(graph_env, contributor, actor_config)
    _sign_in(TOKEN_ALL)
    sales = _Space(SALES_ID, [(REVENUE, SALES_ROWS), (REVENUE, SALES_ROWS)])
    marketing = _Space(MARKETING_ID, [])
    _Genie(sales, marketing).install(monkeypatch)
    _serve(monkeypatch, _Replay({}))
    persisted: List[tuple] = []

    def spy(self, session_id, space_id, conversation_id):
        persisted.append((session_id, space_id, conversation_id))
        return setter(self, session_id, space_id, conversation_id)

    monkeypatch.setattr(SessionManager, "set_genie_agent_conversation_id", spy)

    # Turn 1: a new conversation for the contributor.
    _install(monkeypatch, _answer((SALES_TOOL, Q_SALES), sources=[SALES_SOURCE]))
    _run_analyst(graph_env, _analyst_state(graph_env, actor=contributor))

    assert sales.asks == [{"question": Q_SALES}], (
        "the contributor's first question must not continue the owner's conversation"
    )
    assert persisted == [(contributor, SALES_ID, f"conv-{SALES_ID}")]
    stored = resolve_agent_config(_raw_agent_config(graph_env, contributor))
    assert stored.tools == [
        GenieTool(
            type="genie", space_id=SALES_ID, space_name="Sales", conversation_id=f"conv-{SALES_ID}"
        ),
        GenieTool(
            type="genie",
            space_id=MARKETING_ID,
            space_name="Marketing",
            conversation_id="marketing-conv-7",
        ),
        GenieOneTool(conversation_id="genie-one-conv"),
    ]
    assert _raw_agent_config(graph_env, graph_env.session_id) == owner_config

    # Turn 2: the stored id is continued; it did not change, so nothing is written.
    _install(monkeypatch, _answer((SALES_TOOL, Q_SALES_2), sources=[SALES_SOURCE]))
    _run_analyst(graph_env, _analyst_state(graph_env, actor=contributor, turn_id="turn-2"))

    assert sales.asks[1] == {"question": Q_SALES_2, "conversation_id": f"conv-{SALES_ID}"}
    assert persisted == [(contributor, SALES_ID, f"conv-{SALES_ID}")]
    assert _raw_agent_config(graph_env, graph_env.session_id) == owner_config


def test_a_failed_genie_agent_conversation_write_does_not_fail_the_analyst(graph_env, monkeypatch):
    """Persisting a new conversation id never raises: a failed write is logged and
    the analyst's answer and figures still reach the architect and the user."""
    assert hasattr(SessionManager, "set_genie_agent_conversation_id"), (
        "SessionManager.set_genie_agent_conversation_id is missing"
    )
    sales = _Space(SALES_ID, [(REVENUE, SALES_ROWS)])
    _deck(graph_env, monkeypatch, [SALES], spaces=[sales])
    attempts: List[str] = []

    def fails(self, session_id, space_id, conversation_id):
        attempts.append(space_id)
        raise RuntimeError("database is locked")

    monkeypatch.setattr(SessionManager, "set_genie_agent_conversation_id", fails)
    _install(monkeypatch, _answer((SALES_TOOL, Q_SALES), sources=[SALES_SOURCE]))

    t = _run_analyst(graph_env, _analyst_state(graph_env))

    assert attempts == [SALES_ID]
    assert t.updates["analyst_figures"] == scoped(TURN, _figure_dicts(SALES_FIGURES))
    assert t.updates["architect_message"].startswith(f"{SYNTHESIS}\nSources: {SALES_SOURCE}")
    assert _info(t.rows)[0].startswith(f"{SYNTHESIS}\nSources: {SALES_SOURCE}")


def test_set_genie_agent_conversation_id_rewrites_only_that_spaces_entry(graph_env):
    """A targeted read-modify-write: only the matching space's ``genie`` entry
    changes; the other entries, the other fields of the row's config and every
    other row are kept.  A row without that space's entry is left alone."""
    contributor = _add_contributor(graph_env)
    owner_config = {"tools": [dict(SALES, conversation_id="owner-conv")]}
    actor_config = {
        "tools": [
            {"type": "genie_one", "conversation_id": "genie-one-conv"},
            dict(SALES, description="Quarterly revenue by region.", conversation_id="old-conv"),
            dict(MARKETING, conversation_id="marketing-conv-7"),
            {"type": "mcp", "connection_name": "you-web-search-mcp", "server_name": "You.com"},
        ],
        "slide_style_id": 12,
    }
    _set_agent_config(graph_env, graph_env.session_id, owner_config)
    _set_agent_config(graph_env, contributor, actor_config)
    before = resolve_agent_config(actor_config)
    setter = getattr(get_session_manager(), "set_genie_agent_conversation_id", None)
    assert setter is not None, "SessionManager.set_genie_agent_conversation_id is missing"

    setter(contributor, SALES_ID, "new-conv")

    after = resolve_agent_config(_raw_agent_config(graph_env, contributor))
    expected = before.model_copy(deep=True)
    expected.tools[1].conversation_id = "new-conv"
    assert after == expected
    assert _raw_agent_config(graph_env, graph_env.session_id) == owner_config

    setter(contributor, "sp-removed-mid-turn", "other-conv")

    assert resolve_agent_config(_raw_agent_config(graph_env, contributor)) == expected


# ===========================================================================
# Chat: refusals (R8; the say_once key)
# ===========================================================================


def test_say_once_says_each_key_once_per_turn(graph_env):
    """``_GatewayNotices.say_once(key, text)`` says *text* as an ``info`` row unless
    *key* was said this turn (by this run, or by an earlier pass on this turn's
    ``gateway_usage``), and records the key for the run's own entry."""
    earlier = scoped(
        TURN,
        [
            {
                "agent": "architect",
                "calls": 0,
                "seconds": 0.0,
                "notified": [f"genie_agent:{MARKETING_ID}"],
            }
        ],
    )
    state = _analyst_state(graph_env, gateway_usage=earlier)
    notices = nodes._GatewayNotices(state, TOKEN_ALL)
    assert hasattr(notices, "say_once"), "_GatewayNotices.say_once is missing"
    sm = get_session_manager()
    before = len(sm.get_messages(state["session_id"]))

    notices.say_once(f"genie_agent:{SALES_ID}", refused("Sales"))
    notices.say_once(f"genie_agent:{SALES_ID}", refused("Sales"))
    notices.say_once(f"genie_agent:{MARKETING_ID}", refused("Marketing"))
    notices.consent()

    rows = sm.get_messages(state["session_id"])[before:]
    assert [(r["content"], r["message_type"]) for r in rows] == [
        (refused("Sales"), "info"),
        (CONSENT, "info"),
    ]
    assert notices.said == [f"genie_agent:{SALES_ID}", "consent"]


@pytest.mark.parametrize("with_pass", [False, True], ids=["no-gateway-pass", "gateway-pass"])
def test_a_genie_agent_access_denial_says_its_notice_once(graph_env, monkeypatch, with_pass):
    """Sales refuses both questions (a 403 for a token that has ``dashboards.genie``:
    the user lacks access to the space); Marketing answers.  The user is told
    Sales' notice ONCE — never Genie One's grant message, the consent message, or
    anything for Marketing — and the answer still reaches the architect.

    With a Gateway pass the notice is said once per TURN under the key
    ``genie_agent:<space_id>`` (recorded on ``gateway_usage``): an earlier pass's
    notice for a Gateway service or a connection that shares the space id's name
    does not silence it, and a second analyst round in the turn does not repeat it."""
    sales = _Space(SALES_ID, [PermissionDenied("Forbidden") for _ in range(4)])
    marketing = _Space(MARKETING_ID, [(LEADS, MARKETING_ROWS), (LEADS, MARKETING_ROWS)])
    if with_pass:
        _gateway_genie_deck(
            graph_env, monkeypatch, [SALES, MARKETING, WEB_ENTRY], spaces=[sales, marketing]
        )
    else:
        _deck(graph_env, monkeypatch, [SALES, MARKETING], spaces=[sales, marketing])
    answer = _answer(
        (SALES_TOOL, Q_SALES),
        (SALES_TOOL, Q_SALES_2),
        (MARKETING_TOOL, Q_MARKETING),
        sources=[MARKETING_SOURCE],
    )
    runtime = _install(monkeypatch, answer)
    state = _analyst_state(graph_env)
    if with_pass:
        state["gateway_usage"] = scoped(
            TURN,
            [
                {
                    "agent": "architect",
                    "calls": 0,
                    "seconds": 0.0,
                    "notified": [SALES_ID, f"mcp:{SALES_ID}"],
                }
            ],
        )

    t = _run_analyst(graph_env, state)

    (call,) = runtime.calls_for("data_analyst")
    assert {SALES_TOOL, MARKETING_TOOL} <= set(call.tool_names)
    assert [(e.kind, e.tool_name) for e in call.toolset.access_errors] == [
        ("access_denied", SALES_TOOL),
        ("access_denied", SALES_TOOL),
    ]
    info = _info(t.rows)
    others = [text for text in info if not text.startswith(SYNTHESIS)]
    assert others == [refused("Sales")]
    assert GRANT_MESSAGE not in info and CONSENT not in info
    assert t.updates["architect_message"].startswith(f"{SYNTHESIS}\nSources: {MARKETING_SOURCE}")
    assert t.updates["analyst_figures"] == scoped(TURN, _figure_dicts(MARKETING_FIGURES))
    if not with_pass:
        return

    (usage,) = _usage_vals(t.updates)
    assert usage["notified"] == [f"genie_agent:{SALES_ID}"]

    t2 = _run_analyst(graph_env, fold(state, t.updates))

    _, again = runtime.calls_for("data_analyst")
    assert [(e.kind, e.tool_name) for e in again.toolset.access_errors] == [
        ("access_denied", SALES_TOOL),
        ("access_denied", SALES_TOOL),
    ]
    assert refused("Sales") not in _info(t2.rows)


def test_a_genie_agent_missing_scope_at_run_time_says_consent_once(graph_env, monkeypatch):
    """Both Genie Agents are refused for a missing scope (the recorded SDK error):
    the consent message is said once, and neither space's access notice is said."""
    sales = _Space(SALES_ID, [recorded_missing_scope_exception()])
    marketing = _Space(MARKETING_ID, [recorded_missing_scope_exception()])
    _deck(graph_env, monkeypatch, [SALES, MARKETING], spaces=[sales, marketing])
    output = AnalystOutput(outcome="no_tool", reason="refused", tried_tools=[SALES_TOOL])
    runtime = _install(
        monkeypatch,
        _answer((SALES_TOOL, Q_SALES), (MARKETING_TOOL, Q_MARKETING), output=output),
    )

    t = _run_analyst(graph_env, _analyst_state(graph_env))

    (call,) = runtime.calls_for("data_analyst")
    assert call.tool_names == [MARKETING_TOOL, SALES_TOOL]
    assert [(e.kind, e.tool_name) for e in call.toolset.access_errors] == [
        ("missing_scope", SALES_TOOL),
        ("missing_scope", MARKETING_TOOL),
    ]
    info = _info(t.rows)
    assert info.count(CONSENT) == 1
    assert refused("Sales") not in info and refused("Marketing") not in info


# ===========================================================================
# Final review fixes: a deleted space, a stale conversation, a 401, no empty link
# ===========================================================================


@pytest.mark.parametrize("with_pass", [False, True], ids=["no-gateway-pass", "gateway-pass"])
def test_a_deleted_genie_agent_says_its_not_found_notice_once(graph_env, monkeypatch, with_pass):
    """Fix A4: Sales answers both questions with a 404 (a deleted space, or one no
    longer shared with the user); Marketing answers.  The loop records two
    ``access_denied`` refusals, and the user is told Sales' NOT-FOUND notice once,
    under the same ``genie_agent:<space_id>`` key as a refusal: never the refusal
    text, the consent message or Genie One's grant message."""
    sales = _Space(SALES_ID, [NotFound("No Genie space found with id sp-sales.")] * 2)
    marketing = _Space(MARKETING_ID, [(LEADS, MARKETING_ROWS)])
    if with_pass:
        _gateway_genie_deck(
            graph_env, monkeypatch, [SALES, MARKETING, WEB_ENTRY], spaces=[sales, marketing]
        )
    else:
        _deck(graph_env, monkeypatch, [SALES, MARKETING], spaces=[sales, marketing])
    runtime = _install(
        monkeypatch,
        _answer(
            (SALES_TOOL, Q_SALES),
            (SALES_TOOL, Q_SALES_2),
            (MARKETING_TOOL, Q_MARKETING),
            sources=[MARKETING_SOURCE],
        ),
    )

    t = _run_analyst(graph_env, _analyst_state(graph_env))

    (call,) = runtime.calls_for("data_analyst")
    assert [(e.kind, e.tool_name) for e in call.toolset.access_errors] == [
        ("access_denied", SALES_TOOL),
        ("access_denied", SALES_TOOL),
    ]
    # Each question started a conversation (none was ever opened), and none was retried.
    assert sales.asks == [{"question": Q_SALES}, {"question": Q_SALES_2}]
    info = _info(t.rows)
    others = [text for text in info if not text.startswith(SYNTHESIS)]
    assert others == [not_found("Sales")]
    assert refused("Sales") not in info
    assert GRANT_MESSAGE not in info and CONSENT not in info
    assert t.updates["analyst_figures"] == scoped(TURN, _figure_dicts(MARKETING_FIGURES))
    if with_pass:
        (usage,) = _usage_vals(t.updates)
        assert usage["notified"] == [f"genie_agent:{SALES_ID}"]


def test_a_stale_genie_agent_conversation_is_restarted_and_the_new_one_persisted(
    graph_env, monkeypatch
):
    """Fix A4: the actor's stored Sales conversation is gone (a 404 on
    ``create_message``).  The question is asked once more in a new conversation, its
    figures reach the architect, the NEW conversation id is written on the actor's
    row, and the user is told nothing about it."""
    stored = "conv-stale"
    _set_agent_config(
        graph_env, graph_env.session_id, {"tools": [dict(SALES, conversation_id=stored)]}
    )
    _sign_in(TOKEN_ALL)
    sales = _Space(SALES_ID, [NotFound(f"Conversation {stored} not found."), (REVENUE, SALES_ROWS)])
    genie = _Genie(sales).install(monkeypatch)
    persisted: List[tuple] = []
    setter = SessionManager.set_genie_agent_conversation_id

    def spy(self, session_id, space_id, conversation_id):
        persisted.append((session_id, space_id, conversation_id))
        return setter(self, session_id, space_id, conversation_id)

    monkeypatch.setattr(SessionManager, "set_genie_agent_conversation_id", spy)
    runtime = _install(monkeypatch, _answer((SALES_TOOL, Q_SALES), sources=[SALES_SOURCE]))

    t = _run_analyst(graph_env, _analyst_state(graph_env))

    (call,) = runtime.calls_for("data_analyst")
    assert call.toolset.access_errors == []
    assert sales.asks == [
        {"question": Q_SALES, "conversation_id": stored},
        {"question": Q_SALES},
    ]
    assert [name for name, _ in genie.calls].count("start_conversation") == 1
    assert t.updates["analyst_figures"] == scoped(TURN, _figure_dicts(SALES_FIGURES))
    assert persisted == [(graph_env.session_id, SALES_ID, f"conv-{SALES_ID}")]
    stored_tools = resolve_agent_config(_raw_agent_config(graph_env, graph_env.session_id)).tools
    assert [tool.conversation_id for tool in stored_tools] == [f"conv-{SALES_ID}"]
    assert [text for text in _info(t.rows) if not text.startswith(SYNTHESIS)] == []


def test_a_genie_agent_401_says_consent_once(graph_env, monkeypatch):
    """Fix A4: an HTTP 401 from a Genie Agent (the SDK's ``Unauthenticated``) is a
    missing scope, as Genie One maps it: the consent message once, no space notice."""
    sales = _Space(SALES_ID, [Unauthenticated("Credential was not sent")] * 2)
    _deck(graph_env, monkeypatch, [SALES], spaces=[sales])
    output = AnalystOutput(outcome="no_tool", reason="refused", tried_tools=[SALES_TOOL])
    runtime = _install(
        monkeypatch, _answer((SALES_TOOL, Q_SALES), (SALES_TOOL, Q_SALES_2), output=output)
    )

    t = _run_analyst(graph_env, _analyst_state(graph_env))

    (call,) = runtime.calls_for("data_analyst")
    assert [(e.kind, e.tool_name) for e in call.toolset.access_errors] == [
        ("missing_scope", SALES_TOOL),
        ("missing_scope", SALES_TOOL),
    ]
    info = _info(t.rows)
    assert info.count(CONSENT) == 1
    assert refused("Sales") not in info and not_found("Sales") not in info


def test_a_genie_agent_whose_start_call_timed_out_lists_no_deep_link(graph_env, monkeypatch):
    """Fix A2: Sales' start call is cut off (so its conversation was never opened);
    Marketing answers.  The figure block lists Marketing's deep link only: no
    "Explore in Databricks" line for Sales, and never an empty ``.../chats/`` link."""
    monkeypatch.setattr(genie_agent, "_CALL_TIMEOUT_SECONDS", 1)
    release = threading.Event()

    def block(space_id: str, question: str) -> None:
        if not release.wait(timeout=10):
            raise _HarnessAbort("the blocking Sales start call was never cut off")

    sales = _Space(SALES_ID, [(REVENUE, SALES_ROWS)], on_ask=block)
    marketing = _Space(MARKETING_ID, [(LEADS, MARKETING_ROWS)])
    _deck(graph_env, monkeypatch, [SALES, MARKETING], spaces=[sales, marketing])
    runtime = _install(
        monkeypatch,
        _answer((SALES_TOOL, Q_SALES), (MARKETING_TOOL, Q_MARKETING), sources=[MARKETING_SOURCE]),
    )

    try:
        t = _run_analyst(graph_env, _analyst_state(graph_env))
    finally:
        release.set()

    (call,) = runtime.calls_for("data_analyst")
    sales_tool = _tool(call, SALES_TOOL)
    assert [(a.status, a.conversation_id, a.deep_link) for a in sales_tool.answers] == [
        ("timed_out", "", None)
    ]
    (message,) = [text for text in _info(t.rows) if text.startswith(SYNTHESIS)]
    links = [line for line in message.split("\n") if line.startswith("Explore in Databricks")]
    assert links == [f"Explore in Databricks: {space_link(MARKETING_ID)}"]
    _, inside = _split_wrapper(t.updates["architect_message"])
    assert [line for line in inside.split("\n") if line.startswith("Explore in")] == links


# ===========================================================================
# The architect: every Genie source is code-owned (R1)
# ===========================================================================


def _sales_answer(rows: Sequence[Sequence[Any]] = SALES_ROWS) -> GenieOneAnswer:
    return GenieOneAnswer(
        conversation_id=f"conv-{SALES_ID}",
        response_id="m1",
        status="completed",
        final_answer=None,
        deep_link=space_link(SALES_ID),
        query_results=(
            GenieOneQueryResult(
                item_id="att-1",
                sql="SELECT region, SUM(revenue) AS revenue FROM main.sales.orders GROUP BY 1",
                columns=("region", "revenue"),
                rows=tuple(tuple(row) for row in rows),
                total_row_count=len(rows),
                truncated=False,
            ),
        ),
        source=SALES_SOURCE,
    )


def _sales_figures() -> List[ResolvedFigure]:
    figures = figures_from_answer(_sales_answer())
    assert _triples(figures) == SALES_FIGURES
    return figures


def test_architect_drops_its_own_typed_genie_agent_figures_and_keeps_code_built_ones(
    graph_env,
):
    """This turn's code-built figures (Genie One's and Sales') are committed byte for
    byte.  Every architect figure whose source is a Genie source is dropped: a Sales
    value it retyped, a Sales figure it invented, a Marketing figure no code built,
    a Genie One value it retyped.  Its other figures are kept, in its order."""
    genie_one_code = _q1_figures()
    sales_code = _sales_figures()
    code = genie_one_code + sales_code
    invented_sales = ResolvedFigure(
        key="revenue (region=North)", value="700000", source=SALES_SOURCE
    )
    invented_marketing = ResolvedFigure(
        key="leads (channel=Email)", value="400", source=MARKETING_SOURCE
    )
    architect_figures = [
        NPS,
        _retyped(sales_code[0], "1.25M"),
        invented_sales,
        HEADCOUNT,
        invented_marketing,
        _retyped(genie_one_code[0], "1,227"),
    ]
    graph_env.skills.set(
        "architect", architect_build(_with_figures(make_spec((0, 1)), architect_figures))
    )

    updates = architect_node(graph_env.state(analyst_figures=scoped(TURN, _dumps(code))))

    expected = [NPS, HEADCOUNT] + code
    assert updates["error_state"] is None
    assert updates["deck_spec"].resolved_data.figures == expected
    assert _committed_figures(graph_env) == _dumps(expected)
    # The pure helper, with only the Sales figures code-built.
    spec = _with_figures(make_spec((0,)), architect_figures)
    assert _with_genie_figures(spec, sales_code).resolved_data.figures == (
        [NPS, HEADCOUNT] + sales_code
    )


def test_architect_keeps_a_figure_whose_source_merely_equals_a_space_name(graph_env):
    """Review Focus 5 (R1): code ownership hinges on the code's prefix, never on a
    user-chosen name.  Figures the architect sourced "Sales" (the space's name),
    "Genie Agent", "Genie Agent: Sales" or "genie agent · Sales" stay the
    architect's: kept beside the code's Sales figures, and on a later turn its edit
    of them stands and a dropped one stays dropped, while the Sales figures are
    re-applied.  Only an exact ``"Genie Agent · "`` source is code-owned."""
    sales_code = _sales_figures()
    near_misses = [
        ResolvedFigure(key="pipeline (region=EMEA)", value="3.1M", source="Sales"),
        ResolvedFigure(key="win rate", value="27%", source="Genie Agent"),
        ResolvedFigure(key="quota attainment", value="94%", source="Genie Agent: Sales"),
        ResolvedFigure(key="churn", value="4%", source=f"genie agent {DOT} Sales"),
    ]
    typed = ResolvedFigure(key="revenue (region=North)", value="700000", source=SALES_SOURCE)
    graph_env.skills.set(
        "architect", architect_build(_with_figures(make_spec((0,)), near_misses + [typed]))
    )

    updates = architect_node(graph_env.state(analyst_figures=scoped(TURN, _dumps(sales_code))))

    assert updates["deck_spec"].resolved_data.figures == near_misses + sales_code
    assert _committed_figures(graph_env) == _dumps(near_misses + sales_code)

    # A later turn: no new analyst figures; the architect retypes the "Sales" figure,
    # drops "win rate" and every Sales figure.
    edited = [_retyped(near_misses[0], "3.4M"), near_misses[2], near_misses[3]]
    graph_env.skills.set("architect", architect_build(_with_figures(make_spec((0,)), edited)))

    updates = architect_node(
        graph_env.state(turn_id="turn-2", analyst_figures=scoped(TURN, _dumps(sales_code)))
    )

    assert updates["deck_spec"].resolved_data.figures == edited + sales_code
    assert _committed_figures(graph_env) == _dumps(edited + sales_code)


@pytest.mark.parametrize("edit_form", ["full-spec", "operations"])
def test_a_later_turn_reapplies_prior_genie_agent_figures_verbatim(
    graph_env, monkeypatch, edit_form
):
    """On a turn with no new analyst figures, the PERSISTED spec's Genie Agent figures
    are re-applied verbatim beside Genie One's, so an edit that retypes a Sales value
    or drops a Sales figure cannot change them.  A previous turn's
    ``analyst_figures`` (still in the checkpoint) are not this turn's.  On the
    operations path the composed spec the layout writer lands carries them too."""
    genie_one_code = _q1_figures()
    sales_code = _sales_figures()
    prior = _with_figures(make_spec((0, 1, 2)), [NPS] + genie_one_code + sales_code)
    graph_env.seed_slides(THREE)
    _persist(graph_env, prior)
    retyped = [NPS, _retyped(sales_code[0], "1.25M"), genie_one_code[1], HEADCOUNT]
    if edit_form == "full-spec":
        revised = _with_figures(prior, retyped)
        revised = revised.model_copy(
            update={
                "slides": [
                    s.model_copy(update={"content_brief": "regional revenue"})
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
                            purpose="regional detail",
                            content_brief="the leading region",
                            assumes="the ranking",
                            hands_off="the trend",
                            data_references=[sales_code[0].key],
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
    stale = [_retyped(sales_code[0], "999")]
    state = graph_env.state(turn_id="turn-2", analyst_figures=scoped("turn-1", _dumps(stale)))

    updates = architect_node(state)

    expected = [NPS, HEADCOUNT] + genie_one_code + sales_code
    assert updates["architect_intent"] == "edit"
    assert updates["error_state"] is None
    assert updates["deck_spec"].resolved_data.figures == expected
    assert _committed_figures(graph_env) == _dumps(expected)
    if edit_form == "operations":
        assert len(layout_calls) == 1
        landed = DeckSpec.from_json(layout_calls[0]["deck_spec"])
        assert landed.resolved_data.figures == expected
    else:
        assert updates["target_positions"] == [1]
