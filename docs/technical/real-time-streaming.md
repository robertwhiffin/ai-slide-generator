# Real-Time Streaming & Conversation Persistence

Dual-mode streaming with SSE (for local development) and polling (for Databricks Apps), plus database-backed message persistence for conversation restoration.

---

## Overview

The streaming system provides:
- **Dual-mode delivery** – SSE for local dev, polling for Databricks Apps (60s proxy timeout)
- **Real-time updates** – Tool calls, responses, and results appear as they happen
- **Message persistence** – All conversation messages stored in database for history
- **Session restoration** – Chat history rehydrated from database when resuming sessions
- **Navigation lock** – UI prevents navigation during active generation

---

## Architecture

### SSE Mode (Local Development)

```
Frontend                         Backend SSE Endpoint              Agent Thread
    │                                   │                               │
    │  POST /api/chat/stream            │                               │
    │──────────────────────────────────►│                               │
    │  [Navigation disabled]            │   Start agent in thread       │
    │                                   │──────────────────────────────►│
    │                                   │                               │
    │   event: assistant                │◄── StreamingCallbackHandler ──│
    │◄──────────────────────────────────│         │                     │
    │                                   │    [Persist to DB]            │
    │   event: tool_call                │◄──────────────────────────────│
    │◄──────────────────────────────────│                               │
    │   event: tool_result              │◄──────────────────────────────│
    │◄──────────────────────────────────│                               │
    │   event: complete                 │◄── agent finished ────────────│
    │◄──────────────────────────────────│                               │
    │  [Navigation re-enabled]          │                               │
```

### Polling Mode (Databricks Apps)

Databricks Apps runs behind a reverse proxy with a 60-second connection timeout, which breaks SSE for long-running agent requests. Polling mode works around this:

```
Frontend                    Backend
   │                           │
   │  POST /chat/async         │
   │──────────────────────────>│  -> Check session lock
   │  { request_id }           │  -> Create ChatRequest in DB
   │<──────────────────────────│  -> Queue job (in-memory)
   │                           │  -> Return immediately
   │                           │
   │  GET /poll/{request_id}   │     Worker processes job:
   │──────────────────────────>│     - StreamingCallbackHandler
   │  { events, status }       │       persists messages with request_id
   │<──────────────────────────│
   │  (repeat every 2s)        │
   │                           │
   │  status: complete         │
   │<──────────────────────────│
```

**Key Components:**
- **ChatRequest** – Database model tracking request status (`pending`/`running`/`completed`/`error`)
- **Job Queue** – In-memory asyncio queue with background worker (`src/api/services/job_queue.py`)
- **request_id** – Links messages to specific chat requests for efficient polling
- **Auto-creation** – Sessions are auto-created on first async request if they don't exist

---

## SSE Event Types

Defined in `src/api/schemas/streaming.py`:

| Event Type | Purpose | Payload Fields |
|------------|---------|----------------|
| `assistant` | LLM reasoning/response | `content`, `message_id` |
| `tool_call` | Tool invocation started | `tool_name`, `tool_input`, `message_id` |
| `tool_result` | Tool returned result | `tool_name`, `tool_output`, `message_id` |
| `error` | Error occurred | `error`, `tool_name?` |
| `complete` | Generation finished | `slides`, `raw_html`, `replacement_info`, `metadata` |

```python
class StreamEvent(BaseModel):
    type: StreamEventType
    content: Optional[str] = None
    tool_name: Optional[str] = None
    tool_input: Optional[Dict[str, Any]] = None
    tool_output: Optional[str] = None
    slides: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    message_id: Optional[int] = None
    
    def to_sse(self) -> str:
        return f"event: {self.type.value}\ndata: {self.model_dump_json()}\n\n"
```

---

## Backend Components

### StreamingCallbackHandler (`src/services/streaming_callback.py`)

LangChain callback that intercepts agent events and:
1. Emits SSE events to a queue for real-time streaming
2. Persists messages to database for history

| Callback Method | Event Emitted | Persisted As |
|-----------------|---------------|--------------|
| `on_agent_action` | `assistant` (reasoning) | `message_type="reasoning"` |
| `on_tool_start` | `tool_call` | `message_type="tool_call"` |
| `on_tool_end` | `tool_result` | `message_type="tool_result"` |
| `on_chain_error` | `error` | Not persisted |
| `emit_complete` | `complete` | Not persisted (slides saved separately) |

```python
class StreamingCallbackHandler(BaseCallbackHandler):
    def __init__(self, event_queue: queue.Queue, session_id: str, request_id: str = None):
        self.event_queue = event_queue
        self.session_id = session_id
        self.request_id = request_id  # Links messages to async requests
    
    def on_agent_action(self, action: AgentAction, **kwargs):
        # Extract LLM reasoning before tool call
        reasoning = action.log.split("Invoking:")[0].strip()
        if reasoning:
            self.session_manager.add_message(..., request_id=self.request_id)
            self.event_queue.put(StreamEvent(type=ASSISTANT, content=reasoning))
    
    def on_tool_start(self, serialized, input_str, **kwargs):
        # Parse tool input (handles JSON and Python dict strings)
        tool_input = self._parse_tool_input(input_str)
        self.session_manager.add_message(..., request_id=self.request_id)
        self.event_queue.put(StreamEvent(type=TOOL_CALL, ...))
```

### Streaming Agent Method (`src/services/agent.py`)

`generate_slides_streaming()` accepts a callback handler and passes it via the `invoke()` config:

```python
def generate_slides_streaming(self, question, session_id, callback_handler, slide_context=None):
    tools = self._create_tools_for_session(session_id)
    agent_executor = self._create_agent_executor_with_callbacks(tools, [callback_handler])
    
    result = agent_executor.invoke(
        agent_input,
        config={"callbacks": [callback_handler]},  # Required for real-time events
    )
```

### Streaming Chat Service (`src/api/services/chat_service.py`)

`send_message_streaming()` is a generator that:
1. Persists user message to database first
2. Hydrates agent chat history from database
3. Yields SSE events as they arrive from the callback queue
4. Processes final result and yields `complete` event

```python
def send_message_streaming(self, session_id, message, slide_context=None):
    # Persist user message FIRST
    session_manager.add_message(session_id, role="user", content=message)
    
    # Ensure agent has hydrated chat history
    self._ensure_agent_session(session_id, ...)
    
    # Create callback handler with queue
    event_queue = queue.Queue()
    callback_handler = StreamingCallbackHandler(event_queue, session_id)
    
    # Run agent in thread, yield events as they arrive
    def run_agent():
        result = self.agent.generate_slides_streaming(...)
        event_queue.put(None)  # Signal completion
    
    thread = threading.Thread(target=run_agent)
    thread.start()
    
    while True:
        event = event_queue.get()
        if event is None:
            break
        yield event
    
    # Yield final complete event with slides
    yield StreamEvent(type=COMPLETE, slides=slide_deck_dict, ...)
```

### Chat History Hydration

When restoring a session, `_hydrate_chat_history()` loads messages from database into the agent's `ChatMessageHistory`:

```python
def _hydrate_chat_history(self, session_id, chat_history):
    db_messages = session_manager.get_messages(session_id)
    
    for msg in db_messages:
        if msg["role"] == "user":
            chat_history.add_message(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            chat_history.add_message(AIMessage(content=msg["content"]))
    
    return len(db_messages)
```

---

## API Endpoints

### Streaming Endpoint (SSE)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/chat/stream` | SSE streaming chat |

**Request:** Same as `/api/chat`
```json
{
  "session_id": "abc123",
  "message": "Create slides about...",
  "slide_context": { ... }
}
```

**Response:** `text/event-stream` with headers:
```
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
```

### Polling Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/chat/async` | Submit for async processing |
| `GET` | `/api/chat/poll/{request_id}` | Poll for status and events |

**Submit Request:**
```json
// POST /api/chat/async
{
  "session_id": "abc123",
  "message": "Create slides about...",
  "slide_context": { ... }
}

// Response
{
  "request_id": "xYz123...",
  "status": "pending"
}
```

**Poll Response:**
```json
// GET /api/chat/poll/{request_id}?after_message_id=0
{
  "status": "running",  // pending | running | completed | error
  "events": [
    { "type": "assistant", "content": "I'll analyze...", "message_id": 42 },
    { "type": "tool_call", "tool_name": "query_genie", "tool_input": {...} }
  ],
  "last_message_id": 45,
  "result": null,  // Populated when status=completed
  "error": null    // Populated when status=error
}
```

### Updated Session Endpoint

`GET /api/sessions/{id}` now returns messages and slide deck for restoration:

```json
{
  "session_id": "abc123",
  "title": "...",
  "messages": [
    { "id": 1, "role": "user", "content": "...", "created_at": "..." },
    { "id": 2, "role": "assistant", "content": "...", "message_type": "reasoning" }
  ],
  "slide_deck": { ... }
}
```

---

## Frontend Components

### GenerationContext (`src/contexts/GenerationContext.tsx`)

App-level state for tracking generation status:

```typescript
interface GenerationContextType {
  isGenerating: boolean;
  setIsGenerating: (value: boolean) => void;
}
```

Used by `ChatPanel` to set state, consumed by `AppLayout` for navigation locking.

### Unified Chat API (`src/services/api.ts`)

The frontend automatically detects the environment and uses the appropriate method:

```typescript
// Auto-detect: uses SSE locally, polling on Databricks Apps
sendChatMessage(
  sessionId: string,
  message: string,
  slideContext: SlideContext | undefined,
  onEvent: (event: StreamEvent) => void,
  onError: (error: Error) => void,
): () => void  // Returns cancel function
```

**Environment Detection:**
```typescript
const isPollingMode = (): boolean => {
  // Explicit override via env var
  if (import.meta.env.VITE_USE_POLLING === 'true') return true;
  
  // Production mode always uses polling (Databricks Apps has proxy timeouts)
  if (import.meta.env.MODE === 'production') return true;
  
  // Auto-detect Databricks Apps (for dev builds deployed to Databricks)
  const hostname = window.location.hostname;
  return hostname.includes('.databricks.com') ||
         hostname.includes('.azuredatabricks.net');
};
```

**Key behavior:** Production builds always use polling to avoid SSE timeout issues.

**SSE Mode** – Uses `streamChat()` with `ReadableStream`:
```typescript
const reader = response.body.getReader();
while (true) {
  const { done, value } = await reader.read();
  // Parse SSE lines, extract event type and JSON data
  const event = JSON.parse(data) as StreamEvent;
  onEvent(event);
}
```

**Polling Mode** – Uses `startPolling()` with setInterval:
```typescript
const { request_id } = await api.submitChatAsync(sessionId, message, slideContext);
let lastMessageId = 0;

const pollInterval = setInterval(async () => {
  const response = await api.pollChat(request_id, lastMessageId);
  for (const event of response.events) onEvent(event);
  lastMessageId = response.last_message_id;
  
  if (response.status === 'completed' || response.status === 'error') {
    clearInterval(pollInterval);
    // Emit final complete/error event
  }
}, 2000);
```

### ChatPanel Event Handling

```typescript
const handleStreamEvent = (event: StreamEvent) => {
  switch (event.type) {
    case 'assistant':
      setMessages(prev => [...prev, { role: 'assistant', content: event.content }]);
      break;
    case 'tool_call':
      setMessages(prev => [...prev, { 
        role: 'assistant', 
        tool_call: { name: event.tool_name, arguments: event.tool_input }
      }]);
      break;
    case 'tool_result':
      setMessages(prev => [...prev, { role: 'tool', content: event.tool_output }]);
      break;
    case 'complete':
      setIsGenerating(false);
      if (event.slides) onSlidesGenerated(event.slides, event.raw_html);
      break;
  }
};
```

### Session Message Loading

On session change, `ChatPanel` loads persisted messages:

```typescript
useEffect(() => {
  if (!sessionId) return;
  api.getSession(sessionId).then(session => {
    if (session.messages?.length > 0) {
      setMessages(session.messages.map(msg => ({
        role: msg.role,
        content: msg.content,
        tool_call: msg.metadata?.tool_name ? { ... } : undefined,
      })));
    }
  }).catch(err => {
    // 404 expected for new sessions - silently ignore
  });
}, [sessionId]);
```

### Navigation Lock

`AppLayout` disables navigation during generation:

```tsx
const { isGenerating } = useGeneration();

<button
  disabled={isGenerating}
  className={isGenerating ? 'opacity-50 cursor-not-allowed' : ''}
>
  History
</button>

{isGenerating && <span className="animate-pulse">Generating...</span>}
```

Disabled elements: History, Settings, Help, Save As, New, Profile Selector.

---

## Message Display

### Message Component (`src/components/ChatPanel/Message.tsx`)

| Message Type | Display Style |
|--------------|---------------|
| User message | Blue background, right-aligned |
| Assistant reasoning | White background, normal text |
| Tool call | Collapsed accordion with query preview |
| Tool result | Collapsed accordion with output preview |
| HTML output | Collapsed accordion labeled "(HTML)" |

Tool calls show the query directly when expanded:

```tsx
if (message.tool_call) {
  return renderCollapsibleContent(
    `Tool call: ${message.tool_call.name}`,
    queryPreview,
    <div>Query: {toolArgs.query}</div>
  );
}
```

---

## Database Schema

### session_messages Table

| Column | Type | Purpose |
|--------|------|---------|
| `id` | INTEGER | Primary key |
| `session_id` | INTEGER | FK to user_sessions |
| `role` | VARCHAR | `user`, `assistant`, `tool` |
| `content` | TEXT | Message content |
| `message_type` | VARCHAR | `user_input`, `reasoning`, `tool_call`, `tool_result`, `llm_response` |
| `metadata_json` | TEXT | JSON with `tool_name`, `tool_input` |
| `request_id` | VARCHAR(64) | Links to async chat request (for polling) |
| `created_at` | TIMESTAMP | Message timestamp |

### chat_requests Table (Polling Support)

| Column | Type | Purpose |
|--------|------|---------|
| `id` | INTEGER | Primary key |
| `request_id` | VARCHAR(64) | Unique request identifier |
| `session_id` | INTEGER | FK to user_sessions |
| `status` | VARCHAR(20) | `pending`, `running`, `completed`, `error` |
| `error_message` | TEXT | Error details if status=error |
| `result_json` | TEXT | JSON with slides, raw_html, replacement_info |
| `created_at` | TIMESTAMP | Request creation time |
| `completed_at` | TIMESTAMP | Request completion time |

**Migration SQL:** See `scripts/migrate_polling_support.sql`

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Stream error | `error` event emitted, `isGenerating` reset |
| Session lock conflict | 409 returned, stream not started |
| Network disconnect | `AbortController` cancels stream |
| Tool error | `error` event with tool name |

---

## Testing Checklist

### Both Modes
1. **Navigation lock** – Start generation, verify nav buttons disabled
2. **Real-time events** – Tool calls appear before results
3. **Message persistence** – Messages survive page reload
4. **Session restore** – Load session from History, verify messages + slides
5. **Continue conversation** – After restore, agent has context from history
6. **Error recovery** – Errors re-enable navigation

### Polling Mode (Databricks Apps)
7. **Async submission** – POST /api/chat/async returns request_id
8. **Poll updates** – Events arrive via polling every 2 seconds
9. **Completion detection** – Polling stops when status=completed
10. **Error handling** – Errors propagate correctly
11. **Environment detection** – Polling used automatically on *.databricks.com

To force polling mode locally for testing: set `VITE_USE_POLLING=true` in frontend env.

---

## Cross-References

- [Backend Overview](backend-overview.md) – request lifecycle, agent architecture, and polling endpoints
- [Frontend Overview](frontend-overview.md) – component structure, state management, and `sendChatMessage`
- [Multi-User Concurrency](multi-user-concurrency.md) – session locking and ChatRequest tracking
- [Database Configuration](database-configuration.md) – session and chat_requests schema

