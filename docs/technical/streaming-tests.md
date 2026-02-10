# Streaming Test Suite

**One-Line Summary:** Integration tests for Server-Sent Events (SSE) streaming endpoints covering event format, sequencing, error handling, and connection lifecycle.

---

## 1. Overview

The streaming test suite validates the SSE streaming endpoint `/api/chat/stream`. These tests ensure correct event formatting, proper event sequencing, error propagation, and connection handling.

### Test File

| File | Test Count | Purpose |
|------|------------|---------|
| `tests/integration/test_streaming.py` | ~27 | SSE format, event sequence, error handling |

---

## 2. SSE Protocol Background

Server-Sent Events use a specific text format:

```
event: assistant
data: {"type": "assistant", "content": "Hello"}

event: complete
data: {"type": "complete", "slides": {...}}
```

Key characteristics:
- Content-Type: `text/event-stream`
- Cache-Control: `no-cache`
- Each event has `event:` and `data:` lines
- Events separated by blank lines

---

## 3. Event Types

The streaming endpoint emits these event types:

| Event Type | Description | Key Fields |
|------------|-------------|------------|
| `assistant` | LLM text response | `content` |
| `tool_call` | Tool invocation | `tool_name`, `tool_input` |
| `tool_result` | Tool output | `tool_output` |
| `error` | Error occurred | `error` |
| `complete` | Stream finished | `slides` (nullable) |

**Schema:** `src/api/schemas/streaming.py::StreamEvent`

---

## 4. Test Categories

### 4.1 SSE Format Tests

**Goal:** Validate correct SSE wire format.

```
tests/integration/test_streaming.py::TestSSEFormat
```

| Test | Scenario | Validation |
|------|----------|------------|
| `test_content_type_is_event_stream` | Any stream | Content-Type starts with `text/event-stream` |
| `test_events_have_event_and_data_lines` | Multiple events | Each has `event:` and `data:` lines |
| `test_events_are_valid_json` | All events | Data lines parse as valid JSON |
| `test_cache_control_headers` | Any stream | Cache-Control is `no-cache` |

**Key Invariant:** Every `data:` line must contain valid JSON with a `type` field.

---

### 4.2 Event Sequence Tests

**Goal:** Validate correct event ordering and content.

```
tests/integration/test_streaming.py::TestEventSequence
```

| Test | Scenario | Validation |
|------|----------|------------|
| `test_ends_with_complete_event` | Normal completion | Last event is `complete` |
| `test_assistant_event_has_content` | Assistant response | `content` field present |
| `test_tool_call_has_name_and_input` | Tool invocation | `tool_name` and `tool_input` present |
| `test_tool_result_has_output` | Tool completion | `tool_output` present |
| `test_multiple_events_in_sequence` | Full conversation | Events in expected order |

**Expected Sequence:** `assistant` → `tool_call` → `tool_result` → `assistant` → `complete`

---

### 4.3 Slide Events Tests

**Goal:** Validate slide data in stream events.

```
tests/integration/test_streaming.py::TestSlideEvents
```

| Test | Scenario | Validation |
|------|----------|------------|
| `test_complete_event_includes_slides` | Slide generation | `slides` field with deck data |
| `test_complete_event_can_have_null_slides` | Non-generation request | `slides` is null |

**Complete Event Structure:**
```json
{
  "type": "complete",
  "slides": {
    "slides": [...],
    "slide_count": 3
  }
}
```

---

### 4.4 Streaming Error Tests

**Goal:** Validate error handling during streaming.

```
tests/integration/test_streaming.py::TestStreamingErrors
```

| Test | Scenario | Validation |
|------|----------|------------|
| `test_session_busy_returns_409` | Session locked | HTTP 409 (not stream) |
| `test_error_event_includes_message` | Error during generation | `error` field with message |
| `test_error_mid_stream_yields_error_event` | Exception mid-stream | Error event emitted |
| `test_session_not_found_error_yields_error_event` | Invalid session | Error event with "Session not found" |

**Error Event Structure:**
```json
{
  "type": "error",
  "error": "LLM rate limit exceeded"
}
```

---

### 4.5 Connection Handling Tests

**Goal:** Validate connection lifecycle and cleanup.

```
tests/integration/test_streaming.py::TestConnectionHandling
```

| Test | Scenario | Validation |
|------|----------|------------|
| `test_stream_completes_normally` | Normal completion | Final event is `complete` |
| `test_session_lock_released_on_completion` | Stream ends | `release_session_lock` called |

**Critical:** Session lock must be released even if client disconnects.

---

### 4.6 Request Validation Tests

**Goal:** Validate request validation before streaming starts.

```
tests/integration/test_streaming.py::TestRequestValidation
```

| Test | Scenario | Expected |
|------|----------|----------|
| `test_empty_message_validation` | Empty message | 422 |
| `test_missing_session_id_validation` | No session_id | 422 |
| `test_missing_message_validation` | No message | 422 |
| `test_whitespace_only_message_validation` | Whitespace message | 422 |
| `test_valid_request_accepted` | Valid request | 200 |

**Validation:** Happens before stream starts; errors return HTTP status, not SSE.

---

### 4.7 Event Type Tests

**Goal:** Validate all event types are correctly formatted.

```
tests/integration/test_streaming.py::TestEventTypes
```

| Test | Event Type | Key Validations |
|------|------------|-----------------|
| `test_assistant_event_type` | `assistant` | Has `content` |
| `test_tool_call_event_type` | `tool_call` | Has `tool_name`, `tool_input` |
| `test_tool_result_event_type` | `tool_result` | Has `tool_output` |
| `test_error_event_type` | `error` | Has `error` |
| `test_complete_event_type` | `complete` | Has `slides` |

---

## 5. Helper Functions

```python
def parse_sse_events(response) -> Generator[Dict[str, Any], None, None]:
    """Parse SSE events from response."""
    for line in response.iter_lines():
        if line.startswith("data: "):
            yield json.loads(line[6:])

def collect_stream_events(client, request_body) -> List[Dict[str, Any]]:
    """Collect all events from streaming request."""
    with client.stream("POST", "/api/chat/stream", json=request_body) as response:
        return list(parse_sse_events(response))

def generate_slide_events(count: int) -> List[StreamEvent]:
    """Generate typical slide generation event sequence."""
    events = [
        create_stream_event(StreamEventType.ASSISTANT, content=f"Creating {count} slides"),
        create_stream_event(StreamEventType.TOOL_CALL, tool_name="generate_slides", ...),
        create_stream_event(StreamEventType.TOOL_RESULT, tool_output=json.dumps(slides)),
        create_stream_event(StreamEventType.COMPLETE, slides=slides_data),
    ]
    return events
```

---

## 6. Running the Tests

```bash
# Run all streaming tests
pytest tests/integration/test_streaming.py -v

# Run specific category
pytest tests/integration/test_streaming.py::TestSSEFormat -v

# Run with output visible
pytest tests/integration/test_streaming.py -v -s

# Run single test
pytest tests/integration/test_streaming.py -k "test_ends_with_complete_event" -v
```

---

## 7. Key Invariants

These invariants must NEVER be violated:

1. **Complete event:** Every successful stream must end with a `complete` event
2. **Lock release:** Session lock must be released on completion, error, or disconnect
3. **JSON validity:** All `data:` lines must contain valid JSON
4. **Type field:** Every event must have a `type` field
5. **Pre-stream validation:** Request validation errors return HTTP status, not SSE events

---

## 8. Cross-References

- [Real-Time Streaming](./real-time-streaming.md) - Implementation details
- [API Routes Tests](./api-routes-tests.md) - Non-streaming endpoint tests
- [Backend Overview](./backend-overview.md) - FastAPI architecture
- [Multi-User Concurrency](./multi-user-concurrency.md) - Session locking
