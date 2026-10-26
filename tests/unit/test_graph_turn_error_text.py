"""A failed graph turn never shows the client exception text (ws2a follow-up A, fix 1).

Under ``tool_choice="auto"`` a model can name a tool of its own choosing; the
structured-output parser then raises ``OutputParserException("Unknown tool
type: '<provider-chosen name>' ...")`` — model output inside the exception
text.  The graph path's generic failure branch must emit and re-raise a
code-owned message only.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from src.api.schemas.streaming import StreamEventType
from src.api.services.chat_service import (
    GRAPH_TURN_FAILED_MESSAGE,
    ChatService,
    GraphTurnFailedError,
)
from src.domain.skill_io import OUTPUT_SCHEMAS
from src.services.agent_runtime import AgentModelConfiguration, DatabricksModelAdapter
from tests.fixtures.tool_call_doubles import replying

PROVIDER_SECRET = "PROVIDER_SECRET_tool_name_https_leak_example"


def _service() -> ChatService:
    service = ChatService.__new__(ChatService)
    service._deck_cache = {}
    service._cache_lock = threading.Lock()
    service._get_or_load_deck = MagicMock(return_value=None)
    service.get_slides = MagicMock(return_value=None)
    return service


def _provider_named_tool_error() -> Exception:
    """The real binding's parser error for a reply naming a provider-chosen tool."""

    class WrongToolChatModel:
        def bind_tools(self, tools, **kwargs):
            return replying(
                lambda prompt: AIMessage(
                    content="",
                    tool_calls=[
                        {"name": PROVIDER_SECRET, "args": {}, "id": "c", "type": "tool_call"}
                    ],
                )
            )

    adapter = DatabricksModelAdapter(
        model_factory=lambda **_kwargs: WrongToolChatModel(),
        client_factory=lambda: object(),
    )
    try:
        adapter.invoke(
            agent_key="architect",
            configuration=AgentModelConfiguration(
                endpoint_name="e", temperature=0.5, max_tokens=10, top_p=0.5
            ),
            schema=OUTPUT_SCHEMAS["architect"],
            prompt="p",
        )
    except Exception as error:  # noqa: BLE001 - the error under test
        return error
    raise AssertionError("the wrong-tool reply must raise")


@patch("src.api.services.chat_service.get_session_manager")
def test_a_parser_error_carrying_provider_text_never_reaches_the_turn_error(_mock_sm):
    from langchain_core.exceptions import OutputParserException

    parser_error = _provider_named_tool_error()
    # Precondition: the real parser error does carry the provider-chosen text.
    assert isinstance(parser_error, OutputParserException)
    assert PROVIDER_SECRET in str(parser_error)

    def failing_invoke_graph(session_id, state, *, emitter, request_id=None):
        raise parser_error

    events = []
    with patch("src.services.graph.builder.invoke_graph", failing_invoke_graph):
        stream = _service()._send_message_streaming_graph(
            session_id="s-1", message="m", is_first_message=False
        )
        with pytest.raises(GraphTurnFailedError) as raised:
            for event in stream:
                events.append(event)

    error_events = [event for event in events if event.type == StreamEventType.ERROR]
    assert len(error_events) == 1
    assert error_events[0].error == GRAPH_TURN_FAILED_MESSAGE
    for event in events:
        assert PROVIDER_SECRET not in event.to_sse()
    # The re-raised error is what the SSE route and the polling job format with
    # ``str(error)``: code-owned too; the cause is kept for server logs only.
    assert str(raised.value) == GRAPH_TURN_FAILED_MESSAGE
    assert PROVIDER_SECRET not in str(raised.value)
    assert raised.value.__cause__ is parser_error
