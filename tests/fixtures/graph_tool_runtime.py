"""A fake ``AgentRuntime`` that plays tool calls through the runtime's own dispatcher.

Moved out of ``tests/unit/test_graph_gateway_mcp.py`` so the graph suites that bind
code-defined tools to an agent (the AI Gateway MCP tools, the architect's
``generate_image``) share one harness:

* :class:`FakeRuntime` stands in for ``AgentRuntime``.  Each role has answers, used in
  order (the last one repeats): an output, or a callable ``(call) -> output``.
* :class:`ToolCall` is one ``run(...)`` call.  When it carries a toolset, a test plays
  the model's tool calls with :meth:`ToolCall.use`, which answers them through
  ``DatabricksModelAdapter._answer_tool_call``: budget, counting and
  ``access_errors`` exactly as production records them.
* :func:`run_architect` runs ``architect_node`` once under an emitter and a request
  id and returns its updates, events and the transcript rows it wrote.
"""

from __future__ import annotations

import copy
import queue
import time
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, get_type_hints

from src.api.services.session_manager import get_session_manager
from src.services.agent_runtime import DatabricksModelAdapter
from src.services.agent_tools.toolset import AgentToolset
from src.services.graph import nodes
from src.services.graph.event_emitter import set_chat_request_id, set_event_emitter
from src.services.graph.state import GraphState

#: The budget text the fake loop answers a spent budget with.
BUDGET_TEXT = "Tool budget exhausted. Call the output schema now with what you have."


def ref(token: str) -> str:
    """``{{image:TOKEN}}``, built by concatenation."""
    return "{{image:" + token + "}}"


class ToolCall:
    """One ``run(...)`` call: its arguments, and the tool calls the "model" made."""

    def __init__(self, name: str, graph_release_id: Any, payload: Any, context: Any) -> None:
        self.name = name
        self.graph_release_id = graph_release_id
        self.payload = copy.deepcopy(payload)
        self.context = context
        self.toolset: Optional[AgentToolset] = context.toolset
        #: (max_calls, budget_seconds, calls_made) as the node handed the toolset over.
        self.at_start = (
            None
            if self.toolset is None
            else (self.toolset.max_calls, self.toolset.budget_seconds, self.toolset.calls_made)
        )
        self.tool_texts: List[str] = []
        self._started = False

    @property
    def tool_names(self) -> List[str]:
        return sorted(tool.name for tool in self.toolset.tools) if self.toolset else []

    def has_tool(self, name: str) -> bool:
        return self.toolset is not None and name in self.tool_names

    def use(self, name: str, args: Optional[Dict[str, Any]] = None) -> str:
        """One tool call, answered as the production loop answers it."""
        toolset = self.toolset
        assert toolset is not None, "this call carries no toolset"
        if not self._started:
            toolset.start()
            self._started = True
        text = DatabricksModelAdapter._answer_tool_call(
            {
                "name": name,
                "args": dict(args or {}),
                "id": f"{self.name}-{len(self.tool_texts) + 1}",
                "type": "tool_call",
            },
            {tool.name: tool for tool in toolset.tools},
            toolset,
            budget_text=BUDGET_TEXT,
        )
        self.tool_texts.append(text)
        return text


class FakeRuntime:
    """Stands in for ``AgentRuntime``.  Each role has answers, used in order (the last
    one repeats): an output, or a callable ``(call) -> output``.  A role with no
    answers fails loudly."""

    def __init__(self, **answers: Any) -> None:
        self.answers = {
            role: list(value) if isinstance(value, list) else [value]
            for role, value in answers.items()
        }
        self.calls: List[ToolCall] = []

    def run(self, name, graph_release_id, payload, assembly_context):
        call = ToolCall(name, graph_release_id, payload, assembly_context)
        self.calls.append(call)
        answers = self.answers.get(name)
        if not answers:
            raise AssertionError(f"unexpected runtime call for {name!r}")
        answer = answers.pop(0) if len(answers) > 1 else answers[0]
        output = answer(call) if callable(answer) else answer
        return SimpleNamespace(output=output)

    def calls_for(self, name: str) -> List[ToolCall]:
        return [call for call in self.calls if call.name == name]


def install_runtime(monkeypatch, runtime: FakeRuntime) -> FakeRuntime:
    """Every node's ``get_agent_runtime()`` returns *runtime*."""
    monkeypatch.setattr(nodes, "get_agent_runtime", lambda: runtime)
    return runtime


def fold(state: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    """*state* after *updates*, through GraphState's own reducers."""
    hints = get_type_hints(GraphState, include_extras=True)
    out = dict(state)
    for key, value in updates.items():
        meta = getattr(hints.get(key), "__metadata__", None)
        out[key] = meta[0](out.get(key), value) if meta else value
    return out


def with_slides(spec, **fields_by_position: Dict[int, str]):
    """*spec* with some slides' fields replaced: ``content_brief={0: "..."}``."""
    slides = []
    for slide in spec.slides:
        update = {
            field: values[slide.position]
            for field, values in fields_by_position.items()
            if slide.position in values
        }
        slides.append(slide.model_copy(update=update) if update else slide)
    return spec.model_copy(update={"slides": slides})


def turn_state(env, **overrides) -> Dict[str, Any]:
    """The owner's turn as ``invoke_graph`` hands it over, 5 s in."""
    state = env.state(
        root_session_id=env.session_id,
        actor_session_id=env.session_id,
        turn_started_at=time.time() - 5,
    )
    state.update(overrides)
    return state


def run_architect(env, state: Dict[str, Any], *, request_id: str) -> SimpleNamespace:
    """Run ``architect_node`` once under an emitter and the request id *request_id*."""
    sm = get_session_manager()
    before = len(sm.get_messages(state["session_id"]))
    emitter: queue.Queue = queue.Queue()
    set_event_emitter(emitter)
    set_chat_request_id(request_id)
    try:
        updates = nodes.architect_node(state)
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


__all__ = [
    "BUDGET_TEXT",
    "FakeRuntime",
    "ToolCall",
    "fold",
    "install_runtime",
    "ref",
    "run_architect",
    "turn_state",
    "with_slides",
]
