"""A graph turn's COMPLETE event carries the architect's final intent.

``_send_message_streaming_graph`` ends a turn with one COMPLETE event whose
``metadata`` the polling job copies verbatim into the chat request's
``result["metadata"]`` (job_queue.py, ``process_chat_request``).  An MCP
``get_deck_status`` poll reads ``architect_intent`` from there to tell a
question from an applied change, so the value must be the one the turn's graph
actually ended on: ``invoke_graph``'s returned final state's
``"architect_intent"``, or ``None`` when the state has none.

The harness drives the real method with ``request_id=None`` (no seal, no
liveness poll) and ``is_first_message=False`` (no title thread).  The only
place a test intent appears is ``invoke_graph``'s RETURN value: the fake emits
no events, and the initial state the method seeds is checked to hold no intent.
So a hard-coded intent, a value read from anywhere else, or one left over from
an earlier turn cannot pass.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from src.api.schemas.streaming import StreamEvent, StreamEventType
from src.api.services.chat_service import ChatService

SESSION_ID = "s-intent-1"
MESSAGE = "Make me a five-slide deck on Q3 revenue"
SLIDES = {"slides": [], "slide_count": 0}


class FakeInvokeGraph:
    """Stands in for ``invoke_graph``: records each call and returns a scripted state.

    It never touches the emitter, so the returned state is the only channel
    through which an intent could reach the COMPLETE event.
    """

    def __init__(self, *returns: Optional[Dict[str, Any]]) -> None:
        self._returns = list(returns)
        self.calls: List[Dict[str, Any]] = []

    def __call__(
        self,
        session_id: str,
        initial: Optional[Dict[str, Any]] = None,
        *,
        emitter: Any = None,
        request_id: Optional[str] = None,
        **kw: Any,
    ) -> Optional[Dict[str, Any]]:
        self.calls.append(
            {
                "session_id": session_id,
                "initial": dict(initial) if initial is not None else None,
                "request_id": request_id,
            }
        )
        return self._returns.pop(0)


def _final_state(**overrides: Any) -> Dict[str, Any]:
    """A plausible final graph state: keys besides the intent ride along, as in a real turn."""
    state: Dict[str, Any] = {
        "architect_message": "Here is the plan for your deck.",
        "title": "Q3 Revenue",
        "target_positions": [0, 1, 2],
    }
    state.update(overrides)
    return state


def _service() -> ChatService:
    service = ChatService()
    service._invalidate_deck_cache = MagicMock()
    service._get_or_load_deck = MagicMock(return_value=None)
    service.get_slides = MagicMock(return_value=SLIDES)
    return service


def _run_turn(service: ChatService) -> List[StreamEvent]:
    return list(
        service._send_message_streaming_graph(
            SESSION_ID, MESSAGE, is_first_message=False, request_id=None
        )
    )


def _the_complete_event(events: List[StreamEvent]) -> StreamEvent:
    completes = [e for e in events if e.type == StreamEventType.COMPLETE]
    assert len(completes) == 1, (
        f"a graph turn must yield exactly one COMPLETE, got {len(completes)}: "
        f"{[e.type for e in events]}"
    )
    assert events[-1] is completes[0], "COMPLETE must be the turn's last event here"
    return completes[-1]


def _assert_the_graph_ran(fake: FakeInvokeGraph, call_index: int = 0) -> None:
    """The turn really ran the (fake) graph, seeded with this message and no intent."""
    call = fake.calls[call_index]
    assert call["session_id"] == SESSION_ID
    assert call["initial"]["architect_message"] == MESSAGE
    assert "architect_intent" not in call["initial"], (
        "the intent must come from invoke_graph's return, not be seeded into it"
    )


@pytest.fixture(autouse=True)
def _session_manager(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    manager = MagicMock()
    monkeypatch.setattr(
        "src.api.services.chat_service.get_session_manager", lambda: manager
    )
    return manager


@pytest.mark.parametrize(
    ("returned_state", "intent"),
    [
        pytest.param(_final_state(architect_intent="build"), "build", id="build"),
        pytest.param(_final_state(architect_intent="discuss"), "discuss", id="discuss"),
        pytest.param(
            _final_state(architect_intent="confirm_design_contract"),
            "confirm_design_contract",
            id="confirm_design_contract",
        ),
        pytest.param({}, None, id="absent"),
    ],
)
def test_complete_metadata_carries_the_final_architect_intent(
    returned_state: Dict[str, Any], intent: Optional[str]
) -> None:
    fake = FakeInvokeGraph(returned_state)
    service = _service()

    with patch("src.services.graph.builder.invoke_graph", fake):
        events = _run_turn(service)

    assert len(fake.calls) == 1
    _assert_the_graph_ran(fake)
    complete = _the_complete_event(events)
    assert complete.metadata == {"engine_mode": "graph", "architect_intent": intent}
    assert complete.slides == SLIDES


@pytest.mark.parametrize(
    "returned_state",
    [
        pytest.param(_final_state(), id="state-without-the-key"),
        pytest.param(_final_state(architect_intent=None), id="intent-is-None"),
        # Fakes across the suite return nothing at all; the turn must still complete.
        pytest.param(None, id="invoke-graph-returns-None"),
    ],
)
def test_complete_metadata_has_a_null_intent_when_the_final_state_has_none(
    returned_state: Optional[Dict[str, Any]],
) -> None:
    fake = FakeInvokeGraph(returned_state)
    service = _service()

    with patch("src.services.graph.builder.invoke_graph", fake):
        events = _run_turn(service)

    assert len(fake.calls) == 1
    _assert_the_graph_ran(fake)
    complete = _the_complete_event(events)
    assert complete.metadata == {"engine_mode": "graph", "architect_intent": None}


def test_a_turn_never_reports_an_earlier_turns_intent() -> None:
    """Two turns on one ChatService: the second's final state has no intent.

    A value kept on the instance or in a module global would leak ``"build"``
    into the second turn's COMPLETE.
    """
    fake = FakeInvokeGraph(_final_state(architect_intent="build"), {})
    service = _service()

    with patch("src.services.graph.builder.invoke_graph", fake):
        first = _run_turn(service)
        second = _run_turn(service)

    assert len(fake.calls) == 2
    _assert_the_graph_ran(fake, 0)
    _assert_the_graph_ran(fake, 1)
    assert _the_complete_event(first).metadata == {
        "engine_mode": "graph",
        "architect_intent": "build",
    }
    assert _the_complete_event(second).metadata == {
        "engine_mode": "graph",
        "architect_intent": None,
    }
