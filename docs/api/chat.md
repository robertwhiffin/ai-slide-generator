# Chat API

Endpoints for generating and editing slides through natural language conversation.

## Send Message (Synchronous)

Send a message to generate or edit slides. Returns the complete response when finished.

**POST** `/api/chat`

### Request Body

```json
{
  "session_id": "abc123",
  "message": "Create a 10-slide presentation about Q3 revenue trends",
  "slide_context": {
    "indices": [0, 1, 2]
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | string | Yes | Session identifier |
| `message` | string | Yes | User message/prompt |
| `slide_context` | object | No | Context for editing specific slides |
| `slide_context.indices` | array | No | Contiguous slide indices to edit |

### Response

```json
{
  "messages": [
    {
      "role": "user",
      "content": "Create a 10-slide presentation..."
    },
    {
      "role": "assistant",
      "content": "I'll create a presentation..."
    }
  ],
  "slide_deck": {
    "slides": [...],
    "css": "...",
    "scripts": "..."
  },
  "raw_html": "<!DOCTYPE html>...",
  "metadata": {
    "latency_ms": 5000,
    "tool_calls": 3,
    "mode": "genie"
  }
}
```

## Send Message (Streaming)

Send a message with Server-Sent Events (SSE) for real-time updates.

**POST** `/api/chat/stream`

### Request Body

Same as synchronous endpoint.

### Response

Stream of SSE events:

```
event: message
data: {"role": "assistant", "content": "I'll create..."}

event: slide
data: {"slide_id": "slide_0", "html": "..."}

event: complete
data: {"metadata": {...}}
```

### Event Types

- `message` - Chat message update
- `slide` - New or updated slide
- `complete` - Generation complete with metadata

## Submit Async Request

Submit a chat request for async processing. Returns immediately with a request ID.

**POST** `/api/chat/async`

### Request Body

Same as synchronous endpoint.

### Response

```json
{
  "request_id": "req_abc123",
  "status": "pending"
}
```

## Poll Async Request

Poll for the status of an async request.

**GET** `/api/chat/poll/{request_id}`

### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `request_id` | string | Yes | Request identifier from async submission |

### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `after_message_id` | string | No | Only return messages after this ID |

### Response

```json
{
  "request_id": "req_abc123",
  "status": "completed",
  "messages": [...],
  "slide_deck": {...},
  "metadata": {...}
}
```

### Status Values

- `pending` - Request is queued
- `processing` - Request is being processed
- `completed` - Request completed successfully
- `failed` - Request failed with error

## Health Check

Lightweight health check endpoint.

**GET** `/api/chat/health`

### Response

```json
{
  "status": "healthy"
}
```

## Error Responses

### Session Not Found (404)

```json
{
  "detail": "Session not found: abc123. Create a session first via POST /api/sessions"
}
```

### Session Busy (409)

```json
{
  "detail": "Session is currently processing another request. Please wait."
}
```

### Processing Error (500)

```json
{
  "detail": "Failed to process message: <error details>"
}
```

