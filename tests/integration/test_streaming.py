"""Integration tests for SSE streaming endpoints.

Tests Server-Sent Events format, event sequencing, and error handling
for the /api/chat/stream endpoint.

Run: pytest tests/integration/test_streaming.py -v
"""

import json
import pytest
from typing import Any, Dict, Generator, List
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from src.api.main import app
from src.api.schemas.streaming import StreamEvent, StreamEventType
from src.api.services.session_manager import SessionNotFoundError


# ============================================
# Helper Functions
# ============================================


def create_stream_event(
    event_type: StreamEventType,
    content: str | None = None,
    tool_name: str | None = None,
    tool_input: Dict[str, Any] | None = None,
    tool_output: str | None = None,
    slides: Dict[str, Any] | None = None,
    error: str | None = None,
) -> StreamEvent:
    """Create a StreamEvent with the given parameters."""
    return StreamEvent(
        type=event_type,
        content=content,
        tool_name=tool_name,
        tool_input=tool_input,
        tool_output=tool_output,
        slides=slides,
        error=error,
    )


def setup_mock_stream(mock_service: MagicMock, events: List[StreamEvent]) -> None:
    """Configure mock chat service to return specified events."""

    def event_generator():
        for event in events:
            yield event

    mock_service.send_message_streaming.return_value = event_generator()


def generate_slide_events(count: int) -> List[StreamEvent]:
    """Generate a typical slide generation event sequence.

    Returns events in order: assistant -> tool_call -> tool_result (for each slide) -> complete
    """
    events = []

    # Initial assistant message
    events.append(
        create_stream_event(
            StreamEventType.ASSISTANT,
            content=f"I'll create {count} slides for you.",
        )
    )

    # Tool call for slide generation
    events.append(
        create_stream_event(
            StreamEventType.TOOL_CALL,
            tool_name="generate_slides",
            tool_input={"count": count, "topic": "Test presentation"},
        )
    )

    # Tool result with slides
    slides_data = {
        "slides": [
            {
                "index": i,
                "html": f"<div class='slide'>Slide {i + 1} content</div>",
                "title": f"Slide {i + 1}",
            }
            for i in range(count)
        ],
        "slide_count": count,
    }
    events.append(
        create_stream_event(
            StreamEventType.TOOL_RESULT,
            tool_output=json.dumps(slides_data),
        )
    )

    # Complete event with final slides
    events.append(
        create_stream_event(
            StreamEventType.COMPLETE,
            slides=slides_data,
        )
    )

    return events


def parse_sse_events(response) -> Generator[Dict[str, Any], None, None]:
    """Parse SSE events from response.

    SSE format is:
    event: <type>
    data: <json>

    (blank line between events)
    """
    current_event_type = None
    for line in response.iter_lines():
        if line.startswith("event: "):
            current_event_type = line[7:]
        elif line.startswith("data: "):
            json_str = line[6:]
            data = json.loads(json_str)
            yield data


def collect_stream_events(
    client: TestClient, request_body: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Collect all events from a streaming request."""
    with client.stream("POST", "/api/chat/stream", json=request_body) as response:
        return list(parse_sse_events(response))


# ============================================
# Fixtures
# ============================================


@pytest.fixture
def client():
    """Create test client."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def mock_chat_service():
    """Mock the chat service."""
    with patch("src.api.routes.chat.get_chat_service") as mock_get:
        service = MagicMock()
        mock_get.return_value = service
        yield service


@pytest.fixture
def mock_session_manager():
    """Mock the session manager."""
    with patch("src.api.routes.chat.get_session_manager") as mock_get:
        manager = MagicMock()
        # Default: lock is acquired successfully
        manager.acquire_session_lock.return_value = True
        mock_get.return_value = manager
        yield manager


@pytest.fixture
def standard_request_body() -> Dict[str, Any]:
    """Standard request body for streaming tests."""
    return {
        "session_id": "test-session-123",
        "message": "Create 3 slides about testing",
    }


# ============================================
# Test Classes
# ============================================


class TestSSEFormat:
    """Tests for correct SSE formatting."""

    def test_content_type_is_event_stream(
        self, client, mock_chat_service, mock_session_manager, standard_request_body
    ):
        """Response Content-Type is text/event-stream."""
        setup_mock_stream(mock_chat_service, generate_slide_events(1))

        with client.stream(
            "POST", "/api/chat/stream", json=standard_request_body
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")

    def test_events_have_event_and_data_lines(
        self, client, mock_chat_service, mock_session_manager, standard_request_body
    ):
        """Each event has 'event:' and 'data:' lines."""
        events = [
            create_stream_event(StreamEventType.ASSISTANT, content="Hello"),
            create_stream_event(StreamEventType.COMPLETE, slides={"slide_count": 0}),
        ]
        setup_mock_stream(mock_chat_service, events)

        with client.stream(
            "POST", "/api/chat/stream", json=standard_request_body
        ) as response:
            lines = list(response.iter_lines())
            # Filter out empty lines
            non_empty_lines = [line for line in lines if line.strip()]

            # Should have pairs of event/data lines
            has_event_line = any(line.startswith("event:") for line in non_empty_lines)
            has_data_line = any(line.startswith("data:") for line in non_empty_lines)

            assert has_event_line, "Missing event: line in SSE output"
            assert has_data_line, "Missing data: line in SSE output"

    def test_events_are_valid_json(
        self, client, mock_chat_service, mock_session_manager, standard_request_body
    ):
        """Event data is valid JSON."""
        events = [
            create_stream_event(StreamEventType.ASSISTANT, content="Hello"),
            create_stream_event(StreamEventType.COMPLETE, slides={"slide_count": 0}),
        ]
        setup_mock_stream(mock_chat_service, events)

        with client.stream(
            "POST", "/api/chat/stream", json=standard_request_body
        ) as response:
            for line in response.iter_lines():
                if line.startswith("data: "):
                    json_str = line[6:]
                    # Should not raise
                    data = json.loads(json_str)
                    assert "type" in data

    def test_cache_control_headers(
        self, client, mock_chat_service, mock_session_manager, standard_request_body
    ):
        """Response includes proper cache control headers for SSE."""
        setup_mock_stream(mock_chat_service, generate_slide_events(1))

        with client.stream(
            "POST", "/api/chat/stream", json=standard_request_body
        ) as response:
            assert response.headers.get("cache-control") == "no-cache"


class TestEventSequence:
    """Tests for correct event ordering."""

    def test_ends_with_complete_event(
        self, client, mock_chat_service, mock_session_manager, standard_request_body
    ):
        """Last event is always 'complete'."""
        setup_mock_stream(mock_chat_service, generate_slide_events(3))

        events = collect_stream_events(client, standard_request_body)

        assert len(events) > 0
        assert events[-1]["type"] == "complete"

    def test_assistant_event_has_content(
        self, client, mock_chat_service, mock_session_manager, standard_request_body
    ):
        """Assistant events include content field."""
        events_to_send = [
            create_stream_event(StreamEventType.ASSISTANT, content="Here's my response"),
            create_stream_event(StreamEventType.COMPLETE, slides={"slide_count": 0}),
        ]
        setup_mock_stream(mock_chat_service, events_to_send)

        events = collect_stream_events(client, standard_request_body)

        assistant_events = [e for e in events if e["type"] == "assistant"]
        assert len(assistant_events) > 0
        assert assistant_events[0]["content"] == "Here's my response"

    def test_tool_call_has_name_and_input(
        self, client, mock_chat_service, mock_session_manager, standard_request_body
    ):
        """Tool call events include tool name and input."""
        events_to_send = [
            create_stream_event(
                StreamEventType.TOOL_CALL,
                tool_name="query_genie",
                tool_input={"query": "sales data"},
            ),
            create_stream_event(StreamEventType.COMPLETE, slides=None),
        ]
        setup_mock_stream(mock_chat_service, events_to_send)

        events = collect_stream_events(client, standard_request_body)

        tool_calls = [e for e in events if e["type"] == "tool_call"]
        assert len(tool_calls) > 0
        assert tool_calls[0]["tool_name"] == "query_genie"
        assert tool_calls[0]["tool_input"]["query"] == "sales data"

    def test_tool_result_has_output(
        self, client, mock_chat_service, mock_session_manager, standard_request_body
    ):
        """Tool result events include output."""
        events_to_send = [
            create_stream_event(
                StreamEventType.TOOL_RESULT,
                tool_output="Query returned 100 rows",
            ),
            create_stream_event(StreamEventType.COMPLETE, slides=None),
        ]
        setup_mock_stream(mock_chat_service, events_to_send)

        events = collect_stream_events(client, standard_request_body)

        tool_results = [e for e in events if e["type"] == "tool_result"]
        assert len(tool_results) > 0
        assert tool_results[0]["tool_output"] == "Query returned 100 rows"

    def test_multiple_events_in_sequence(
        self, client, mock_chat_service, mock_session_manager, standard_request_body
    ):
        """Multiple events are received in correct sequence."""
        events_to_send = [
            create_stream_event(StreamEventType.ASSISTANT, content="Analyzing..."),
            create_stream_event(
                StreamEventType.TOOL_CALL, tool_name="analyze", tool_input={}
            ),
            create_stream_event(StreamEventType.TOOL_RESULT, tool_output="Done"),
            create_stream_event(StreamEventType.ASSISTANT, content="Here are results"),
            create_stream_event(StreamEventType.COMPLETE, slides={"slide_count": 1}),
        ]
        setup_mock_stream(mock_chat_service, events_to_send)

        events = collect_stream_events(client, standard_request_body)

        assert len(events) == 5
        assert events[0]["type"] == "assistant"
        assert events[1]["type"] == "tool_call"
        assert events[2]["type"] == "tool_result"
        assert events[3]["type"] == "assistant"
        assert events[4]["type"] == "complete"


class TestSlideEvents:
    """Tests for slide content in events."""

    def test_complete_event_includes_slides(
        self, client, mock_chat_service, mock_session_manager, standard_request_body
    ):
        """Complete event includes slide deck data."""
        slides_data = {
            "slides": [
                {"index": 0, "html": "<div>Slide 1</div>", "title": "First"},
                {"index": 1, "html": "<div>Slide 2</div>", "title": "Second"},
            ],
            "slide_count": 2,
        }
        events_to_send = [
            create_stream_event(StreamEventType.ASSISTANT, content="Created slides"),
            create_stream_event(StreamEventType.COMPLETE, slides=slides_data),
        ]
        setup_mock_stream(mock_chat_service, events_to_send)

        events = collect_stream_events(client, standard_request_body)

        complete_event = events[-1]
        assert complete_event["type"] == "complete"
        assert complete_event["slides"] is not None
        assert complete_event["slides"]["slide_count"] == 2

    def test_complete_event_can_have_null_slides(
        self, client, mock_chat_service, mock_session_manager, standard_request_body
    ):
        """Complete event can have null slides for non-generation requests."""
        events_to_send = [
            create_stream_event(
                StreamEventType.ASSISTANT, content="I answered your question"
            ),
            create_stream_event(StreamEventType.COMPLETE, slides=None),
        ]
        setup_mock_stream(mock_chat_service, events_to_send)

        events = collect_stream_events(client, standard_request_body)

        complete_event = events[-1]
        assert complete_event["type"] == "complete"
        assert complete_event["slides"] is None


class TestStreamingErrors:
    """Tests for error handling during streaming."""

    def test_session_busy_returns_409(self, client, mock_session_manager):
        """Returns 409 when session is locked."""
        mock_session_manager.acquire_session_lock.return_value = False

        response = client.post(
            "/api/chat/stream",
            json={"session_id": "test-123", "message": "Hello"},
        )
        assert response.status_code == 409

    def test_error_event_includes_message(
        self, client, mock_chat_service, mock_session_manager, standard_request_body
    ):
        """Error events include helpful error message."""
        events_to_send = [
            create_stream_event(StreamEventType.ASSISTANT, content="Starting..."),
            create_stream_event(
                StreamEventType.ERROR, error="LLM rate limit exceeded"
            ),
        ]
        setup_mock_stream(mock_chat_service, events_to_send)

        events = collect_stream_events(client, standard_request_body)

        error_events = [e for e in events if e["type"] == "error"]
        assert len(error_events) > 0
        assert error_events[0]["error"] == "LLM rate limit exceeded"

    def test_error_mid_stream_yields_error_event(
        self, client, mock_chat_service, mock_session_manager, standard_request_body
    ):
        """Error during generation sends error event."""

        def generate_with_error():
            yield create_stream_event(StreamEventType.ASSISTANT, content="Starting")
            yield create_stream_event(
                StreamEventType.TOOL_CALL, tool_name="generate", tool_input={}
            )
            raise Exception("LLM connection lost")

        mock_chat_service.send_message_streaming.return_value = generate_with_error()

        events = collect_stream_events(client, standard_request_body)

        # Should have events up to the error, plus an error event
        assert any(e["type"] == "assistant" for e in events)
        # The error is caught and converted to an error event
        assert any(e["type"] == "error" for e in events)

    def test_session_not_found_error_yields_error_event(
        self, client, mock_chat_service, mock_session_manager, standard_request_body
    ):
        """Returns error event for missing session."""

        def generate_session_error():
            raise SessionNotFoundError("test-123")

        mock_chat_service.send_message_streaming.return_value = (
            generate_session_error()
        )

        events = collect_stream_events(client, standard_request_body)

        # Should have an error event for session not found
        error_events = [e for e in events if e["type"] == "error"]
        assert len(error_events) > 0
        assert "Session not found" in error_events[0]["error"]


class TestConnectionHandling:
    """Tests for client connection scenarios."""

    def test_stream_completes_normally(
        self, client, mock_chat_service, mock_session_manager, standard_request_body
    ):
        """Stream completes and connection closes cleanly."""
        setup_mock_stream(mock_chat_service, generate_slide_events(2))

        with client.stream(
            "POST", "/api/chat/stream", json=standard_request_body
        ) as response:
            events = list(parse_sse_events(response))
            assert events[-1]["type"] == "complete"
        # Connection should be closed after context exits

    def test_session_lock_released_on_completion(
        self, client, mock_chat_service, mock_session_manager, standard_request_body
    ):
        """Session lock is released after stream completes."""
        setup_mock_stream(mock_chat_service, generate_slide_events(1))

        with client.stream(
            "POST", "/api/chat/stream", json=standard_request_body
        ) as response:
            list(parse_sse_events(response))

        # Verify lock was released
        mock_session_manager.release_session_lock.assert_called_with(
            standard_request_body["session_id"]
        )


class TestRequestValidation:
    """Tests for request validation."""

    def test_empty_message_validation(self, client):
        """Empty message is rejected with 422."""
        response = client.post(
            "/api/chat/stream",
            json={"session_id": "test-123", "message": ""},
        )
        assert response.status_code == 422

    def test_missing_session_id_validation(self, client):
        """Missing session_id is rejected with 422."""
        response = client.post(
            "/api/chat/stream",
            json={"message": "Hello"},
        )
        assert response.status_code == 422

    def test_missing_message_validation(self, client):
        """Missing message is rejected with 422."""
        response = client.post(
            "/api/chat/stream",
            json={"session_id": "test-123"},
        )
        assert response.status_code == 422

    def test_whitespace_only_message_validation(self, client):
        """Whitespace-only message is rejected with 422."""
        response = client.post(
            "/api/chat/stream",
            json={"session_id": "test-123", "message": "   "},
        )
        # Depends on validator - may be 422 or 200
        # min_length=1 after strip should reject whitespace
        assert response.status_code == 422

    def test_valid_request_accepted(
        self, client, mock_chat_service, mock_session_manager
    ):
        """Valid request is accepted and processed."""
        setup_mock_stream(mock_chat_service, generate_slide_events(1))

        with client.stream(
            "POST",
            "/api/chat/stream",
            json={"session_id": "test-123", "message": "Create slides"},
        ) as response:
            assert response.status_code == 200


class TestEventTypes:
    """Tests for all supported event types."""

    def test_assistant_event_type(
        self, client, mock_chat_service, mock_session_manager, standard_request_body
    ):
        """Assistant event type is correctly formatted."""
        events = [
            create_stream_event(StreamEventType.ASSISTANT, content="Hello"),
            create_stream_event(StreamEventType.COMPLETE, slides=None),
        ]
        setup_mock_stream(mock_chat_service, events)

        collected = collect_stream_events(client, standard_request_body)
        assistant = next(e for e in collected if e["type"] == "assistant")
        assert assistant["type"] == "assistant"
        assert "content" in assistant

    def test_tool_call_event_type(
        self, client, mock_chat_service, mock_session_manager, standard_request_body
    ):
        """Tool call event type is correctly formatted."""
        events = [
            create_stream_event(
                StreamEventType.TOOL_CALL,
                tool_name="test_tool",
                tool_input={"arg": "value"},
            ),
            create_stream_event(StreamEventType.COMPLETE, slides=None),
        ]
        setup_mock_stream(mock_chat_service, events)

        collected = collect_stream_events(client, standard_request_body)
        tool_call = next(e for e in collected if e["type"] == "tool_call")
        assert tool_call["type"] == "tool_call"
        assert tool_call["tool_name"] == "test_tool"
        assert tool_call["tool_input"] == {"arg": "value"}

    def test_tool_result_event_type(
        self, client, mock_chat_service, mock_session_manager, standard_request_body
    ):
        """Tool result event type is correctly formatted."""
        events = [
            create_stream_event(
                StreamEventType.TOOL_RESULT, tool_output="Result data"
            ),
            create_stream_event(StreamEventType.COMPLETE, slides=None),
        ]
        setup_mock_stream(mock_chat_service, events)

        collected = collect_stream_events(client, standard_request_body)
        tool_result = next(e for e in collected if e["type"] == "tool_result")
        assert tool_result["type"] == "tool_result"
        assert tool_result["tool_output"] == "Result data"

    def test_error_event_type(
        self, client, mock_chat_service, mock_session_manager, standard_request_body
    ):
        """Error event type is correctly formatted."""
        events = [
            create_stream_event(StreamEventType.ERROR, error="Something went wrong"),
        ]
        setup_mock_stream(mock_chat_service, events)

        collected = collect_stream_events(client, standard_request_body)
        error_event = next(e for e in collected if e["type"] == "error")
        assert error_event["type"] == "error"
        assert error_event["error"] == "Something went wrong"

    def test_complete_event_type(
        self, client, mock_chat_service, mock_session_manager, standard_request_body
    ):
        """Complete event type is correctly formatted."""
        events = [
            create_stream_event(
                StreamEventType.COMPLETE, slides={"slide_count": 1}
            ),
        ]
        setup_mock_stream(mock_chat_service, events)

        collected = collect_stream_events(client, standard_request_body)
        complete = next(e for e in collected if e["type"] == "complete")
        assert complete["type"] == "complete"
        assert complete["slides"]["slide_count"] == 1
