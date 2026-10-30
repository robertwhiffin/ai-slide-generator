"""The runtime's tool-calling loop (Genie One in agent mode, Task 5).

An invocation whose ``AgentAssemblyContext`` carries an ``AgentToolset`` runs a
bounded loop: the model is bound ONCE to the output schema plus every toolset
tool, tool calls are answered with ``ToolMessage``s, and the loop returns the
first schema call, validated.  Without a toolset nothing changes: the adapter's
single structured-output ``invoke`` is the path.

The chat model is a double injected through ``DatabricksModelAdapter``'s
``model_factory``; the tool is a double; the clock is a double.  The toolset,
the loop and the runtime routing are production's.  One test drives the REAL
``ChatDatabricks`` over a mock transport so the tool dicts and the message
history are proven acceptable to the provider client, not just to the double.
"""

from __future__ import annotations

import itertools
import json
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import httpx
import openai
import pytest
from databricks.sdk.errors import PermissionDenied
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableLambda
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, Field

from src.domain.skill_io import OUTPUT_SCHEMAS
from src.services.agent_runtime import (
    AgentAssemblyContext,
    AgentModelConfiguration,
    AgentRuntime,
    DatabricksModelAdapter,
    ModelProviderUnavailableError,
)
from src.services.agent_runtime_identity import RecordingAgentInvocationIdentitySink
from src.services.agent_schema_registry import AgentSchemaRegistry
from src.services.agent_tools.toolset import AgentToolset, ToolAccessError
from src.services.graph_definition_manifest import (
    DefinitionContent,
    definition_content_hash,
    load_graph_v1_manifest,
)
from src.services.persisted_graph_release import (
    PinnedInvocationEndpointError,
    ResolvedDefinition,
)
from tests.fixtures.deterministic_model_adapter import (
    DeterministicFakeModelAdapter,
    fake_output,
)
from tests.fixtures.packaged_release_loader import packaged_v1_runtime

# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------

SCHEMA = OUTPUT_SCHEMAS["data_analyst"]
#: The schema's model-facing tool name, which every text below names.
SCHEMA_NAME = "AnalystOutput"
OUTPUT = fake_output("data_analyst")
PROMPT = "assembled analyst prompt"
CONFIGURATION = AgentModelConfiguration(
    endpoint_name="system.ai.claude-opus-5-5",
    temperature=0.7,
    max_tokens=4096,
    top_p=0.95,
)
BUDGET_TEXT = f"Tool budget exhausted. Call {SCHEMA_NAME} now with what you have."
NUDGE_TEXT = f"Respond by calling {SCHEMA_NAME}."


def test_the_schema_is_named_as_the_texts_below_assume():
    assert SCHEMA.__name__ == SCHEMA_NAME
    assert convert_to_openai_tool(SCHEMA)["function"]["name"] == SCHEMA_NAME


class FakeClock:
    """A monotonic clock that moves only when a test (or a tool) moves it."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class LookupArgs(BaseModel):
    question: str = Field(description="The question to ask.")


class CountArgs(BaseModel):
    table: str = Field(description="A table name.")


@dataclass(frozen=True)
class ToolRun:
    args: BaseModel
    remaining_seconds: float


class RecordingTool:
    """An ``AgentTool`` double: records each run, then returns or raises a scripted result.

    ``results`` is consumed one per run; the last entry repeats.  An exception
    entry is raised.  ``on_run`` runs first (a test uses it to move the clock,
    as a slow Genie One question would).
    """

    def __init__(
        self,
        name: str = "lookup",
        *,
        description: str = "Look up a fact in the user's data.",
        args_schema: type[BaseModel] = LookupArgs,
        results: Iterable[str | BaseException] = ("42 rows: north=7, south=35",),
        on_run: Callable[[], None] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.args_schema = args_schema
        self._results = list(results)
        self._on_run = on_run
        self.runs: list[ToolRun] = []

    def run(self, args: BaseModel, *, remaining_seconds: float) -> str:
        self.runs.append(ToolRun(args, remaining_seconds))
        if self._on_run is not None:
            self._on_run()
        result = self._results[min(len(self.runs), len(self._results)) - 1]
        if isinstance(result, BaseException):
            raise result
        return result


class ScriptedChatModel:
    """A chat-model double: ``bind_tools`` records its tools; the bound model replays a script.

    Each entry of ``replies`` is an ``AIMessage`` to return or an exception to
    raise.  ``invocations`` keeps a snapshot of every input the bound model was
    handed (the loop may keep appending to one list).
    """

    def __init__(
        self,
        replies: Iterable[AIMessage | BaseException],
        *,
        bind_error: BaseException | None = None,
    ) -> None:
        self._replies = iter(replies)
        self._bind_error = bind_error
        self.bindings: list[tuple[list[Any], dict[str, Any]]] = []
        self.invocations: list[Any] = []

    def bind_tools(self, tools, **kwargs):
        self.bindings.append((list(tools), dict(kwargs)))
        if self._bind_error is not None:
            raise self._bind_error
        return RunnableLambda(self._reply)

    def with_structured_output(self, schema):  # pragma: no cover - failure path
        raise AssertionError("forced tool choice must not be bound")

    def _reply(self, messages: Any) -> AIMessage:
        self.invocations.append(list(messages) if isinstance(messages, list) else messages)
        try:
            reply = next(self._replies)
        except StopIteration:  # pragma: no cover - a loop that never stops
            raise AssertionError("the model was invoked more times than scripted") from None
        if isinstance(reply, BaseException):
            raise reply
        return reply


@dataclass
class Harness:
    chat: ScriptedChatModel
    adapter: DatabricksModelAdapter
    constructed: list[dict[str, Any]]
    client_calls: list[object]
    system_client: object


def _harness(
    *replies: AIMessage | BaseException,
    script: Iterable[AIMessage | BaseException] | None = None,
    bind_error: BaseException | None = None,
) -> Harness:
    chat = ScriptedChatModel(script if script is not None else replies, bind_error=bind_error)
    constructed: list[dict[str, Any]] = []
    client_calls: list[object] = []
    system_client = object()

    def model_factory(**kwargs):
        constructed.append(kwargs)
        return chat

    def client_factory():
        client_calls.append(system_client)
        return system_client

    adapter = DatabricksModelAdapter(model_factory=model_factory, client_factory=client_factory)
    return Harness(chat, adapter, constructed, client_calls, system_client)


def _loop(harness: Harness, toolset: AgentToolset, *, schema: type[BaseModel] = SCHEMA):
    return harness.adapter.invoke_with_tools(
        agent_key="data_analyst",
        configuration=CONFIGURATION,
        schema=schema,
        prompt=PROMPT,
        toolset=toolset,
    )


def _call(name: str, args: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {"name": name, "args": dict(args), "id": call_id, "type": "tool_call"}


def _reply(*calls: dict[str, Any]) -> AIMessage:
    return AIMessage(content="", tool_calls=list(calls))


def _ask(question: str, call_id: str, tool: str = "lookup") -> AIMessage:
    return _reply(_call(tool, {"question": question}, call_id))


def _final(values: dict[str, Any] | None = None, call_id: str = "call_final") -> AIMessage:
    return _reply(_call(SCHEMA_NAME, values if values is not None else OUTPUT, call_id))


def _empty() -> AIMessage:
    return AIMessage(content="I have looked and will now answer in prose.")


def _tool_messages(messages: list[Any]) -> list[ToolMessage]:
    return [message for message in messages if isinstance(message, ToolMessage)]


def _toolset(*tools: RecordingTool, clock: FakeClock | None = None, **kwargs: Any):
    return AgentToolset(tools=tuple(tools), clock=clock or FakeClock(), **kwargs)


# ---------------------------------------------------------------------------
# The toolset and the context field
# ---------------------------------------------------------------------------


def test_toolset_defaults_are_three_calls_and_three_hundred_seconds_on_the_monotonic_clock():
    """Global constraints: at most 3 Genie One questions and 300 s per analyst run."""
    toolset = AgentToolset(tools=())
    other = AgentToolset(tools=())

    assert toolset.max_calls == 3
    assert toolset.budget_seconds == 300.0
    assert toolset.clock is time.monotonic
    assert toolset.calls_made == 0
    assert toolset.access_errors == []
    assert toolset.access_errors is not other.access_errors


def test_toolset_is_exhausted_by_its_call_count_or_its_clock():
    clock = FakeClock(100.0)
    toolset = AgentToolset(tools=(), max_calls=2, budget_seconds=10.0, clock=clock)

    toolset.start()
    assert toolset.remaining_seconds() == 10.0
    assert not toolset.exhausted()

    clock.advance(4.0)
    assert toolset.remaining_seconds() == 6.0
    assert not toolset.exhausted()

    toolset.calls_made = 2
    assert toolset.exhausted()

    toolset.calls_made = 1
    clock.advance(6.0)  # exactly at the budget: remaining 0 is exhausted
    assert toolset.remaining_seconds() == 0.0
    assert toolset.exhausted()


def test_assembly_context_toolset_defaults_to_none_and_is_outside_equality():
    """``toolset`` is ``compare=False``: two contexts that differ only by toolset are
    equal and hash alike (an ``AgentToolset`` is itself unhashable)."""
    toolset = _toolset(RecordingTool())
    plain = AgentAssemblyContext(False)
    with_tools = AgentAssemblyContext(False, toolset=toolset)

    assert plain.toolset is None
    assert with_tools.toolset is toolset
    assert with_tools == plain
    assert hash(with_tools) == hash(plain)
    # The positional shape every existing caller uses is unchanged.
    assert AgentAssemblyContext(True, "root", "actor").toolset is None


def test_tool_access_error_carries_its_kind_tool_and_message():
    error = ToolAccessError("missing_scope", "genie", "the token lacks a scope")

    assert isinstance(error, Exception)
    assert error.kind == "missing_scope"
    assert error.tool_name == "genie"
    assert error.message == "the token lacks a scope"


# ---------------------------------------------------------------------------
# The loop, driven through DatabricksModelAdapter.invoke_with_tools
# ---------------------------------------------------------------------------


def test_schema_call_first_returns_without_running_tools():
    tool = RecordingTool()
    toolset = _toolset(tool)
    harness = _harness(_final())

    result = _loop(harness, toolset)

    assert type(result) is SCHEMA
    assert result == SCHEMA.model_validate(OUTPUT)
    assert tool.runs == []
    assert toolset.calls_made == 0
    assert toolset.access_errors == []
    # The loop starts from the prompt as ONE human message (C4).
    assert harness.chat.invocations == [[HumanMessage(content=PROMPT)]]


def test_a_schema_call_beside_a_tool_call_returns_without_running_the_tool():
    """ "If ANY tool call names the schema": the final answer wins over a tool call."""
    tool = RecordingTool()
    toolset = _toolset(tool)
    harness = _harness(
        _reply(_call("lookup", {"question": "q"}, "call_a"), _call(SCHEMA_NAME, OUTPUT, "call_b"))
    )

    result = _loop(harness, toolset)

    assert result == SCHEMA.model_validate(OUTPUT)
    assert tool.runs == []
    assert toolset.calls_made == 0
    assert len(harness.chat.invocations) == 1


def test_tool_call_then_schema_runs_the_tool_once_and_returns():
    """The tool's return value is the ``ToolMessage`` content, answering the call's id.

    The provider needs the assistant's tool-call message in the history before
    the tool results, so the second round's input is exactly prompt, reply, result.
    """
    tool = RecordingTool(results=("42 rows: north=7, south=35",))
    toolset = _toolset(tool)
    first = _ask("sales by region", "call_1")
    harness = _harness(first, _final())

    result = _loop(harness, toolset)

    assert type(result) is SCHEMA
    assert result == SCHEMA.model_validate(OUTPUT)
    assert tool.runs == [ToolRun(LookupArgs(question="sales by region"), 300.0)]
    assert type(tool.runs[0].args) is LookupArgs
    assert toolset.calls_made == 1
    assert toolset.access_errors == []
    assert len(harness.chat.invocations) == 2
    second = harness.chat.invocations[1]
    assert len(second) == 3
    assert second[0] == HumanMessage(content=PROMPT)
    assert second[1] == first
    assert isinstance(second[2], ToolMessage)
    assert second[2].content == "42 rows: north=7, south=35"
    assert second[2].tool_call_id == "call_1"


def test_each_tool_call_in_one_reply_gets_its_own_tool_message():
    lookup = RecordingTool(results=("lookup answer",))
    count = RecordingTool("count_rows", args_schema=CountArgs, results=("17",))
    toolset = _toolset(lookup, count)
    harness = _harness(
        _reply(
            _call("lookup", {"question": "top region"}, "call_a"),
            _call("count_rows", {"table": "sales"}, "call_b"),
        ),
        _final(),
    )

    _loop(harness, toolset)

    messages = _tool_messages(harness.chat.invocations[1])
    assert [(m.tool_call_id, m.content) for m in messages] == [
        ("call_a", "lookup answer"),
        ("call_b", "17"),
    ]
    assert lookup.runs[0].args == LookupArgs(question="top region")
    assert count.runs[0].args == CountArgs(table="sales")
    assert type(count.runs[0].args) is CountArgs
    assert toolset.calls_made == 2


def test_fourth_call_is_refused_when_max_calls_is_3():
    """Three calls run; the fourth is answered with the budget text and never runs.

    Each run takes 10 s on the fake clock, so ``remaining_seconds`` is read per call.
    """
    clock = FakeClock()
    tool = RecordingTool(results=("r1", "r2", "r3", "r4"), on_run=lambda: clock.advance(10.0))
    toolset = _toolset(tool, clock=clock, max_calls=3)
    harness = _harness(
        _ask("q1", "call_1"),
        _ask("q2", "call_2"),
        _ask("q3", "call_3"),
        _ask("q4", "call_4"),
        _final(),
    )

    result = _loop(harness, toolset)

    assert result == SCHEMA.model_validate(OUTPUT)
    assert [run.args.question for run in tool.runs] == ["q1", "q2", "q3"]
    assert [run.remaining_seconds for run in tool.runs] == [300.0, 290.0, 280.0]
    assert toolset.calls_made == 3
    messages = _tool_messages(harness.chat.invocations[-1])
    assert [(m.tool_call_id, m.content) for m in messages] == [
        ("call_1", "r1"),
        ("call_2", "r2"),
        ("call_3", "r3"),
        ("call_4", BUDGET_TEXT),
    ]
    assert len(harness.chat.invocations) == 5


def test_time_budget_exhaustion_refuses_further_calls():
    """The clock is read from ``start()`` in the loop, not from construction.

    The toolset is built at t=1000 and invoked at t=5000: the first call still
    sees the whole 300 s.  It takes 301 s, so the next call is refused although
    only one of three calls was made.
    """
    clock = FakeClock(1000.0)
    tool = RecordingTool(results=("slow answer",), on_run=lambda: clock.advance(301.0))
    toolset = _toolset(tool, clock=clock, max_calls=3, budget_seconds=300.0)
    clock.now = 5000.0
    harness = _harness(_ask("q1", "call_1"), _ask("q2", "call_2"), _final())

    result = _loop(harness, toolset)

    assert result == SCHEMA.model_validate(OUTPUT)
    assert tool.runs == [ToolRun(LookupArgs(question="q1"), 300.0)]
    assert toolset.calls_made == 1
    messages = _tool_messages(harness.chat.invocations[-1])
    assert [(m.tool_call_id, m.content) for m in messages] == [
        ("call_1", "slow answer"),
        ("call_2", BUDGET_TEXT),
    ]


@pytest.mark.parametrize("kind", ["missing_scope", "access_denied"])
def test_access_error_is_recorded_and_the_loop_continues(kind):
    """A ``ToolAccessError`` is kept on the toolset for the node and answered in-band;
    the next call still runs."""
    error = ToolAccessError(kind, "lookup", "Genie One refused: no EXECUTE on the service")
    tool = RecordingTool(results=(error, "second answer"))
    toolset = _toolset(tool)
    harness = _harness(_ask("q1", "call_1"), _ask("q2", "call_2"), _final())

    result = _loop(harness, toolset)

    assert result == SCHEMA.model_validate(OUTPUT)
    assert len(toolset.access_errors) == 1
    assert toolset.access_errors[0] is error
    assert toolset.calls_made == 2
    assert len(tool.runs) == 2
    messages = _tool_messages(harness.chat.invocations[-1])
    assert [(m.tool_call_id, m.content) for m in messages] == [
        ("call_1", "Access denied: Genie One refused: no EXECUTE on the service"),
        ("call_2", "second answer"),
    ]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (RuntimeError("x" * 400), "Tool error: RuntimeError: " + "x" * 300),
        (ValueError("no rows"), "Tool error: ValueError: no rows"),
        # Each of these is in the MODEL's provider-error tuple.  Raised by a TOOL
        # it must stay a tool message: tool errors never become provider errors.
        (TimeoutError("genie slow"), "Tool error: TimeoutError: genie slow"),
        (OSError("socket closed"), "Tool error: OSError: socket closed"),
        (PermissionDenied("no EXECUTE"), "Tool error: PermissionDenied: no EXECUTE"),
        (httpx.ConnectError("refused"), "Tool error: ConnectError: refused"),
    ],
    ids=["runtime", "value", "timeout", "oserror", "permission_denied", "httpx"],
)
def test_tool_exception_becomes_a_tool_message(error, expected):
    tool = RecordingTool(results=(error, "recovered"))
    toolset = _toolset(tool)
    harness = _harness(_ask("q1", "call_1"), _ask("q2", "call_2"), _final())

    result = _loop(harness, toolset)

    assert result == SCHEMA.model_validate(OUTPUT)
    assert toolset.access_errors == []
    assert toolset.calls_made == 2
    messages = _tool_messages(harness.chat.invocations[-1])
    assert [(m.tool_call_id, m.content) for m in messages] == [
        ("call_1", expected),
        ("call_2", "recovered"),
    ]


def test_bad_tool_arguments_become_a_tool_error_without_running_the_tool():
    """Parsing the call's args with ``args_schema`` is part of the tool call: a
    failure is "any other Exception", answered in-band so the model can retry."""
    tool = RecordingTool()
    toolset = _toolset(tool)
    harness = _harness(_reply(_call("lookup", {"wrong": 1}, "call_1")), _final())

    result = _loop(harness, toolset)

    assert result == SCHEMA.model_validate(OUTPUT)
    assert tool.runs == []
    (message,) = _tool_messages(harness.chat.invocations[-1])
    assert message.tool_call_id == "call_1"
    assert message.content.startswith("Tool error: ValidationError: ")


def test_unknown_tool_is_answered_and_the_loop_continues():
    tool = RecordingTool()
    toolset = _toolset(tool)
    harness = _harness(_reply(_call("vector_index", {"query": "q"}, "call_1")), _final())

    result = _loop(harness, toolset)

    assert result == SCHEMA.model_validate(OUTPUT)
    assert tool.runs == []
    (message,) = _tool_messages(harness.chat.invocations[-1])
    assert (message.tool_call_id, message.content) == ("call_1", "Unknown tool: vector_index")


def test_one_empty_reply_is_nudged_to_call_the_schema():
    tool = RecordingTool()
    toolset = _toolset(tool)
    harness = _harness(_empty(), _final())

    result = _loop(harness, toolset)

    assert result == SCHEMA.model_validate(OUTPUT)
    assert len(harness.chat.invocations) == 2
    nudge = harness.chat.invocations[1][-1]
    assert type(nudge) is HumanMessage
    assert nudge.content == NUDGE_TEXT
    assert tool.runs == []


def test_two_empty_replies_raise_output_parser_exception():
    tool = RecordingTool()
    toolset = _toolset(tool)
    harness = _harness(_empty(), _empty(), _final())

    with pytest.raises(OutputParserException):
        _loop(harness, toolset)

    # The second empty reply ends the loop: the scripted final answer is never reached.
    assert len(harness.chat.invocations) == 2
    assert harness.chat.invocations[1][-1] == HumanMessage(content=NUDGE_TEXT)
    assert tool.runs == []
    assert toolset.calls_made == 0


@pytest.mark.parametrize("max_calls", [1, 3])
def test_the_loop_stops_after_max_calls_plus_three_rounds(max_calls):
    """A model that never calls the schema gets ``max_calls + 3`` rounds, then a parse error."""
    tool = RecordingTool(results=("answer",))
    toolset = _toolset(tool, max_calls=max_calls)
    harness = _harness(script=(_ask(f"q{i}", f"call_{i}") for i in itertools.count()))

    with pytest.raises(OutputParserException):
        _loop(harness, toolset)

    assert len(harness.chat.invocations) == max_calls + 3
    assert len(tool.runs) == max_calls
    assert toolset.calls_made == max_calls


def _connection_error() -> openai.APIConnectionError:
    return openai.APIConnectionError(
        request=httpx.Request("POST", "https://example.invalid/ai-gateway/mlflow/v1")
    )


@pytest.mark.parametrize(
    ("make_error", "where"),
    [
        (lambda: PermissionDenied("denied"), "first_round"),
        (_connection_error, "first_round"),
        (lambda: httpx.ConnectError("refused"), "first_round"),
        (lambda: TimeoutError("model slow"), "first_round"),
        (lambda: PermissionDenied("denied"), "bind"),
        (_connection_error, "after_a_tool_ran"),
        (lambda: TimeoutError("model slow"), "after_a_tool_ran"),
    ],
    ids=[
        "permission_denied",
        "openai_connection",
        "httpx_connect",
        "timeout",
        "bind_permission_denied",
        "openai_connection_round_2",
        "timeout_round_2",
    ],
)
def test_provider_error_maps_to_model_provider_unavailable(make_error, where):
    """The MODEL call's provider errors collapse exactly as ``invoke``'s do."""
    error = make_error()
    tool = RecordingTool()
    toolset = _toolset(tool)
    if where == "bind":
        harness = _harness(bind_error=error)
    elif where == "first_round":
        harness = _harness(error)
    else:
        harness = _harness(_ask("q1", "call_1"), error)

    with pytest.raises(ModelProviderUnavailableError) as raised:
        _loop(harness, toolset)

    assert str(raised.value) == "pinned model provider unavailable"
    assert raised.value.__cause__ is error
    assert len(tool.runs) == (1 if where == "after_a_tool_ran" else 0)


def test_bound_tools_are_schema_plus_toolset_tools_in_one_bind_call():
    """One model, one binding, per invocation — however many rounds run.

    The schema and each tool are bound together with ``tool_choice="auto"``
    (newer Claude models reject a forced choice; ``auto`` is why an empty reply
    is possible and nudged).  Toolset tools go as LangChain tool dicts built from
    each tool's name, description and args schema.  The model is built with the
    endpoint and ``max_tokens`` only, on the SYSTEM client (C4).
    """
    lookup = RecordingTool(description="Ask the data agent a question.")
    count = RecordingTool("count_rows", description="Count a table's rows.", args_schema=CountArgs)
    toolset = _toolset(lookup, count)
    harness = _harness(
        _ask("q1", "call_1"),
        _reply(_call("count_rows", {"table": "sales"}, "call_2")),
        _final(),
    )

    _loop(harness, toolset)

    assert len(harness.chat.invocations) == 3
    assert len(harness.chat.bindings) == 1
    tools, kwargs = harness.chat.bindings[0]
    assert kwargs == {"tool_choice": "auto"}
    assert len(tools) == 3
    functions = {
        function["name"]: function
        for function in (convert_to_openai_tool(tool)["function"] for tool in tools)
    }
    assert set(functions) == {SCHEMA_NAME, "lookup", "count_rows"}
    assert (
        functions[SCHEMA_NAME]["parameters"]
        == convert_to_openai_tool(SCHEMA)["function"]["parameters"]
    )
    for name, description, field in (
        ("lookup", "Ask the data agent a question.", "question"),
        ("count_rows", "Count a table's rows.", "table"),
    ):
        assert functions[name]["description"] == description
        assert set(functions[name]["parameters"]["properties"]) == {field}
        assert functions[name]["parameters"]["required"] == [field]
    for tool in tools:
        if convert_to_openai_tool(tool)["function"]["name"] != SCHEMA_NAME:
            assert isinstance(tool, dict)
    assert harness.constructed == [
        {
            "model": CONFIGURATION.endpoint_name,
            "max_tokens": CONFIGURATION.max_tokens,
            "workspace_client": harness.system_client,
        }
    ]
    assert harness.client_calls == [harness.system_client]


def _scripted_gateway_workspace(bodies: list[dict[str, Any]]):
    """A mock-transport workspace that answers request N with ``bodies[N]``."""
    from tests.fixtures.mock_chat_completions import MockChatCompletionsWorkspace

    class ScriptedWorkspace(MockChatCompletionsWorkspace):
        def _handle(self, request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(200, json=bodies[len(self.requests) - 1])

    return ScriptedWorkspace({}, usage=None)


def _completion(name: str, arguments: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {
        "id": "mock",
        "object": "chat.completion",
        "created": 0,
        "model": "mock",
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps(arguments)},
                        }
                    ],
                },
            }
        ],
    }


def test_the_real_provider_client_accepts_the_tools_and_the_tool_result_history(monkeypatch):
    """The REAL ``ChatDatabricks`` over a mock transport: the tool dicts serialise,
    and round two sends user prompt, assistant tool call, tool result."""
    from tests.fixtures.mock_chat_completions import install_mock_gateway_transport

    install_mock_gateway_transport(monkeypatch)
    workspace = _scripted_gateway_workspace(
        [
            _completion("lookup", {"question": "sales by region"}, "call_lookup"),
            _completion(SCHEMA_NAME, OUTPUT, "call_final"),
        ]
    )
    adapter = DatabricksModelAdapter(client_factory=lambda: workspace)
    tool = RecordingTool(results=("42 rows",))
    toolset = _toolset(tool)

    result = adapter.invoke_with_tools(
        agent_key="data_analyst",
        configuration=CONFIGURATION,
        schema=SCHEMA,
        prompt=PROMPT,
        toolset=toolset,
    )

    assert result == SCHEMA.model_validate(OUTPUT)
    assert tool.runs == [ToolRun(LookupArgs(question="sales by region"), 300.0)]
    assert len(workspace.requests) == 2
    first, second = (json.loads(request.content) for request in workspace.requests)
    for sent in (first, second):
        assert sent["tool_choice"] == "auto"
        assert sorted(tool["function"]["name"] for tool in sent["tools"]) == sorted(
            [SCHEMA_NAME, "lookup"]
        )
        for sampling in ("temperature", "top_p", "top_k"):
            assert sampling not in sent
    assert first["messages"] == [{"role": "user", "content": PROMPT}]
    roles = [message["role"] for message in second["messages"]]
    assert roles == ["user", "assistant", "tool"]
    assert second["messages"][1]["tool_calls"][0]["id"] == "call_lookup"
    assert second["messages"][2]["tool_call_id"] == "call_lookup"
    assert second["messages"][2]["content"] == "42 rows"


# ---------------------------------------------------------------------------
# The runtime routing: AgentRuntime.run -> _run_resolved -> invoke_with_tools
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdapterCall:
    method: str
    agent_key: str
    configuration: AgentModelConfiguration
    schema: type[BaseModel]
    prompt: str
    toolset: Any


class SpyAdapter:
    """An adapter with both methods; each answers with an instance of its schema."""

    def __init__(self) -> None:
        self.calls: list[AdapterCall] = []

    def invoke(self, *, agent_key, configuration, schema, prompt):
        self.calls.append(AdapterCall("invoke", agent_key, configuration, schema, prompt, None))
        return schema.model_validate(fake_output(agent_key))

    def invoke_with_tools(self, *, agent_key, configuration, schema, prompt, toolset):
        self.calls.append(
            AdapterCall("invoke_with_tools", agent_key, configuration, schema, prompt, toolset)
        )
        return schema.model_validate(fake_output(agent_key))


def test_no_toolset_keeps_the_single_call_path():
    """Every agent without a toolset keeps exactly today's one ``invoke`` call."""
    adapter = SpyAdapter()
    runtime = packaged_v1_runtime(model_adapter=adapter)

    result = runtime.run("data_analyst", 1, {"request": "sales"}, AgentAssemblyContext(False))

    assert [call.method for call in adapter.calls] == ["invoke"]
    assert type(result.output) is SCHEMA
    assert adapter.calls[0].prompt == result.diagnostics.assembled_prompt


def test_no_toolset_binds_only_the_schema_through_the_real_adapter():
    """The structured-output path still binds ``[schema]`` alone and sends the prompt str."""
    harness = _harness(_final())
    runtime = packaged_v1_runtime(model_adapter=harness.adapter)

    result = runtime.run("data_analyst", 1, {"request": "sales"}, AgentAssemblyContext(False))

    assert type(result.output) is SCHEMA
    assert len(harness.chat.bindings) == 1
    tools, kwargs = harness.chat.bindings[0]
    assert kwargs == {"tool_choice": "auto"}
    assert len(tools) == 1
    assert issubclass(tools[0], SCHEMA)
    assert harness.chat.invocations == [result.diagnostics.assembled_prompt]


def test_run_with_a_toolset_routes_to_invoke_with_tools():
    """``_run_resolved`` hands the loop the same agent key, configuration, composed
    schema and prompt ``invoke`` would get, plus the context's toolset itself."""
    plain_adapter = SpyAdapter()
    plain = packaged_v1_runtime(model_adapter=plain_adapter).run(
        "data_analyst", 1, {"request": "sales"}, AgentAssemblyContext(False)
    )
    adapter = SpyAdapter()
    sink = RecordingAgentInvocationIdentitySink()
    runtime = packaged_v1_runtime(model_adapter=adapter, identity_sink=sink)
    toolset = _toolset(RecordingTool())

    result = runtime.run(
        "data_analyst", 1, {"request": "sales"}, AgentAssemblyContext(False, toolset=toolset)
    )

    assert [call.method for call in adapter.calls] == ["invoke_with_tools"]
    (call,) = adapter.calls
    (plain_call,) = plain_adapter.calls
    assert call.toolset is toolset
    assert call.agent_key == "data_analyst"
    assert call.configuration == plain_call.configuration
    # Composition builds a fresh class per run, so compare the contract it carries.
    assert call.schema.model_json_schema() == plain_call.schema.model_json_schema()
    assert call.schema is not SCHEMA and issubclass(call.schema, SCHEMA)
    # The toolset never reaches the prompt: the analyst prompt is unchanged.
    assert call.prompt == plain_call.prompt == result.diagnostics.assembled_prompt
    assert result.diagnostics.assembled_prompt == plain.diagnostics.assembled_prompt
    assert type(result.output) is SCHEMA
    assert len(sink.calls) == 1
    assert len(sink.successes) == 1


def _data_analyst_v2_content() -> DefinitionContent:
    content = next(
        item for item in load_graph_v1_manifest().definitions if item.agent_key == "data_analyst"
    )
    data = content.model_dump(mode="python")
    data["schema_contract"] = {
        "version": 2,
        "digest": AgentSchemaRegistry().identity_for("data_analyst", 2).digest,
    }
    data["schema_overlay"] = {
        "field_overrides": {},
        "additional_optional_fields": ["diagnostic_notes"],
    }
    return DefinitionContent.model_validate(data)


def test_run_with_a_toolset_runs_the_loop_and_validates_through_the_registry():
    """End to end: ``run`` -> ``invoke_with_tools`` on the real adapter -> registry.

    A v2 overlay makes the registry's work visible: the composed schema (with
    ``diagnostic_notes``) is what the model is bound to, the output is the
    CANONICAL ``AnalystOutput``, and the overlay field is projected into
    ``additional_fields`` — which only ``validate_output`` does.
    """
    values = {**OUTPUT, "diagnostic_notes": ["checked the sales table"]}
    tool = RecordingTool(results=("42 rows",))
    toolset = _toolset(tool)
    harness = _harness(_ask("sales by region", "call_1"), _final(values))
    sink = RecordingAgentInvocationIdentitySink()
    runtime = packaged_v1_runtime(
        model_adapter=harness.adapter,
        identity_sink=sink,
        content_overrides={"data_analyst": _data_analyst_v2_content()},
    )

    result = runtime.run(
        "data_analyst", 1, {"request": "sales"}, AgentAssemblyContext(False, toolset=toolset)
    )

    assert type(result.output) is SCHEMA
    assert result.output == SCHEMA.model_validate(OUTPUT)
    assert result.diagnostics.additional_fields == {
        "diagnostic_notes": ("checked the sales table",)
    }
    assert result.diagnostics.schema_contract.version == 2
    assert tool.runs == [ToolRun(LookupArgs(question="sales by region"), 300.0)]
    assert toolset.calls_made == 1
    assert harness.chat.invocations[0] == [
        HumanMessage(content=result.diagnostics.assembled_prompt)
    ]
    assert len(harness.chat.bindings) == 1
    bound, _ = harness.chat.bindings[0]
    functions = {
        function["name"]: function
        for function in (convert_to_openai_tool(entry)["function"] for entry in bound)
    }
    assert set(functions) == {SCHEMA_NAME, "lookup"}
    # The COMPOSED schema is bound: only it carries the overlay field.
    assert "diagnostic_notes" in functions[SCHEMA_NAME]["parameters"]["properties"]
    assert len(sink.calls) == 1
    assert len(sink.successes) == 1


def test_run_with_a_toolset_maps_a_provider_error_to_the_pinned_endpoint_error():
    """The loop's ``ModelProviderUnavailableError`` names the pin, as ``invoke``'s does."""
    error = PermissionDenied("denied")
    harness = _harness(error)
    runtime = packaged_v1_runtime(model_adapter=harness.adapter)
    toolset = _toolset(RecordingTool())

    with pytest.raises(PinnedInvocationEndpointError) as raised:
        runtime.run("data_analyst", 1, {}, AgentAssemblyContext(False, toolset=toolset))

    assert raised.value.endpoint_name == "system.ai.claude-opus-5-5"
    assert isinstance(raised.value.__cause__, ModelProviderUnavailableError)
    assert raised.value.__cause__.__cause__ is error


def test_run_with_a_toolset_and_an_adapter_without_tools_raises_type_error():
    """An adapter that cannot run tools never silently drops the toolset."""
    adapter = DeterministicFakeModelAdapter()
    runtime = packaged_v1_runtime(model_adapter=adapter)
    tool = RecordingTool()
    toolset = _toolset(tool)

    with pytest.raises(TypeError, match="^model adapter cannot run tools$"):
        runtime.run("data_analyst", 1, {}, AgentAssemblyContext(False, toolset=toolset))

    assert adapter.calls == []
    assert tool.runs == []


# ---------------------------------------------------------------------------
# Test runs get no live tools (spec: Isolation)
# ---------------------------------------------------------------------------


class _LoaderMustNotResolve:
    def resolve(self, graph_release_id: int, agent_key: str) -> ResolvedDefinition:
        raise AssertionError("a candidate run must never resolve a release")


def test_run_candidate_refuses_a_toolset():
    adapter = SpyAdapter()
    sink = RecordingAgentInvocationIdentitySink()
    runtime = AgentRuntime(
        persisted_release_loader=_LoaderMustNotResolve(),
        model_adapter=adapter,
        identity_sink=sink,
    )
    content = next(
        item for item in load_graph_v1_manifest().definitions if item.agent_key == "data_analyst"
    )
    tool = RecordingTool()
    toolset = _toolset(tool)

    with pytest.raises(ValueError):
        runtime.run_candidate(
            "data_analyst",
            content,
            definition_content_hash(content),
            {},
            AgentAssemblyContext(False, toolset=toolset),
        )

    assert adapter.calls == []
    assert tool.runs == []
    assert sink.calls == []


def test_run_published_baseline_refuses_a_toolset():
    adapter = SpyAdapter()
    runtime = packaged_v1_runtime(model_adapter=adapter)
    tool = RecordingTool()
    toolset = _toolset(tool)

    with pytest.raises(ValueError):
        runtime.run_published_baseline(
            "data_analyst", 1, {}, AgentAssemblyContext(False, toolset=toolset)
        )

    assert adapter.calls == []
    assert tool.runs == []
