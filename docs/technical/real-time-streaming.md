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
| `complete` | Generation finished | `slides`, `raw_html`, `replacement_info`, `metadata`, `experiment_url` |
| `session_title` | Auto-generated session title | `session_title` |
| `session_created` | New session created on first message | `session_id` |
| `slide_ready` | One committed slide released by the reorder buffer (graph engine) | `position`, `html`, `scripts`, `agent`, `slide_cursor` |
| `turn_progress` | The graph turn's current stage (graph engine, #319) | `turn_progress` (`seq`, `phase`, `slides`) |

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
    raw_html: Optional[str] = None
    replacement_info: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    experiment_url: Optional[str] = None        # MLflow experiment URL
    session_title: Optional[str] = None         # Auto-generated session title
    session_id: Optional[str] = None            # Session ID (for session_created events)
    position: Optional[int] = None              # 0-based slide position (for slide_ready events)
    html: Optional[str] = None                  # One slide's body HTML (for slide_ready events)
    scripts: str = ""                           # One slide's per-slide JavaScript (for slide_ready events)
    agent: Optional[str] = None                 # Agent this event is attributed to
    slide_cursor: Optional[int] = None          # Next position not yet released (for slide_ready events)
    turn_progress: Optional[Dict[str, Any]] = None  # Graph turn's stage summary (for turn_progress events, #319)
    
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
def send_message_streaming(
    self,
    session_id,
    message,
    slide_context=None,
    request_id=None,
    image_ids=None,
    is_first_message_override=None,
):
    # Get or create session in database (inline — no separate method)
    try:
        db_session = session_manager.get_session(session_id)
    except SessionNotFoundError:
        db_session = session_manager.create_session(session_id=session_id)
    
    # Detect first message (async path uses is_first_message_override
    # because the user message is already persisted before the job runs)
    if is_first_message_override is not None:
        is_first_message = is_first_message_override
    else:
        is_first_message = db_session.get("message_count", 0) == 0
    
    # Persist user message FIRST (skip if async path already did it)
    if not request_id:
        session_manager.add_message(session_id, role="user", content=message)
    
    # Build agent and hydrate chat history from DB
    agent, session_data, experiment_url = self._build_agent_for_session(
        session_id, db_session
    )
    
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

**Key parameters:**
- `request_id` – Links messages to an async chat request. When set, user message persistence is skipped (already done by the async endpoint).
- `is_first_message_override` – Overrides DB-based first-message detection. The async path pre-persists the user message before the job runs, so the DB count is already incremented; the override preserves the correct value.
- `image_ids` – Optional list of image IDs; when present, image context is injected into the message before agent execution.

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
| `GET` | `/api/chat/poll/{request_id}` | Poll for status and events (session creator only; 404 unknown id, 403 otherwise — same privacy rule as `/api/sessions/{id}/messages`) |

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
  "error": null,   // Populated when status=error
  "turn_progress": { "seq": 14, "phase": "building", "slides": { ... } }  // object | null
}
```

`turn_progress` is the graph turn's latest stage summary (see [Turn progress](#turn-progress-graph-engine-319)). It is `null` once the request is `completed` or `error`, for a request that has not reported yet, and for the legacy (monolith) engine, which never reports.

### Turn progress (graph engine, #319)

While a graph turn runs, the chat placeholder names the stage the graph is in (for example "Reviewing slide 3…") instead of a fixed "Generating slides...". The backend reports a structured snapshot of the stage; the frontend turns it into text. The tracker lives in `src/services/graph/progress.py`.

**Snapshot shape:**

```json
{
  "seq": 14,
  "phase": "building",
  "slides": { "total": 10, "building": [4, 5], "reviewing": [3], "fixing": [], "done": [0, 1, 2] }
}
```

| Field | Meaning |
|-------|---------|
| `seq` | Integer starting at 1 each turn; rises by one for every report that changed something |
| `phase` | One of `planning`, `gathering_data`, `checking_slides`, `building`, `reviewing_deck` |
| `slides.total` | Number of slides the turn covers |
| `slides.building` / `reviewing` / `fixing` / `done` | Sorted 0-based positions currently at that stage; a slide is in exactly one list |

Reports are statement-level calls (`report_phase`, `report_slide`, `report_slides`) placed beside existing events in `src/services/graph/nodes.py`: the architect reports `planning` (and `checking_slides` before it re-reviews committed slides after a deck-level brief change); the data analyst reports `gathering_data`; the foreman reports `building` when it dispatches a batch and marks that batch's slides as building; each slide's pipeline reports `reviewing`, `fixing` (when a flagged slide opens a fix round) and `done`; the placeholder node reports the slides it placeholds as `done`; the deck reviewer reports `reviewing_deck`. A turn that only replies in chat (the architect answers without building) reaches only `planning`.

**Monotonic rules (in brief):**
- A phase has a rank: `planning`, `gathering_data` and `checking_slides` share rank 0 (the architect and data analyst can alternate within a turn), `building` is 1, `reviewing_deck` is 2. A report with a lower rank than the current phase is dropped.
- A slide's stage only moves forward: `building` < `reviewing` < `fixing` < `done`. A stage can be skipped (a slide whose builder failed goes straight to `done`); a report that does not advance the slide is dropped.
- A slide report that applies raises the phase to `building` if it was lower.
- The covered set only grows, so `total` never falls.
- A report that changes nothing does not bump `seq` and publishes nothing. There are no timer heartbeats.
- So any sequence of snapshots a client observes (the SSE stream, or the subsequence a poll samples) never lowers the phase's rank or a slide's stage, and `done` and `total` never fall. The per-stage lists do shrink as slides move on.

**Two sinks.** Each applied report builds the snapshot under the tracker's lock and publishes it to both:
- **SSE:** a `turn_progress` event (`StreamEvent.turn_progress`) is put on the turn's event queue inside the lock, so the queue carries snapshots in `seq` order. On polling, the job worker drains the same generator but reads only `complete` and `session_title` from it, so these events never reach a polling client; the row does.
- **Polling:** after the lock is released, `progress._persist` calls `SessionManager.record_chat_request_progress`, which writes `progress_json` and `progress_seq` on the turn's `chat_requests` row with a conditional UPDATE: `WHERE request_id = :r AND (progress_seq IS NULL OR progress_seq < :seq)`. Slide pipelines run on separate threads and their commits can land in any order; the predicate makes an older snapshot a no-op, so the stored `seq` never goes backwards. Without a `request_id` (the SSE path and the sweeper) there is no row and nothing is written.

**Lock discipline.** The database write is outside the tracker lock, so a slow write blocks only the thread that reported and never another slide's report. On PostgreSQL the write first runs `SET LOCAL lock_timeout = '2s'` (`_PROGRESS_LOCK_TIMEOUT`), which covers exactly that one UPDATE because `get_db_session` is one transaction per `with` block, so it waits at most 2 seconds for the row lock (SQLite skips the setting). On timeout the call raises, `_persist` logs a warning, and the next report carries a newer snapshot. The timeout bounds the row-lock wait only; a connection-pool checkout is shared with every other writer and is not bounded by it. Every `report_*` function swallows and logs its own errors: progress is a side channel and never fails a turn.

**Scope of the tracker.** `invoke_graph` (`src/services/graph/builder.py`) wraps `get_graph().invoke(...)` in `turn_progress_scope()`, which installs a fresh tracker in a `ContextVar` before the invoke and resets it in a `finally`. LangGraph copies the calling context into every task and each copy shares the tracker object, so the architect, the foreman and every concurrent slide pipeline report into one tracker. Nothing outlives the invoke, and the next turn starts again at `seq` 1. With no tracker installed, every `report_*` call is a no-op.

**Why the poll is cross-worker coherent.** The poll reads the snapshot from the request's database row (`get_chat_request` returns it as `turn_progress`), not from `job_queue.jobs` or any other in-process state. Whichever worker ran the graph wrote the row, and whichever worker serves the poll reads it, so every worker returns the same stage. `poll_chat` returns it only while the request is neither `completed` nor `error`, after the same session-creator check as the rest of the response. See [Multi-User Concurrency](multi-user-concurrency.md).

**Where the label is computed.** The backend sends data, not text. `describeTurnProgress` in `frontend/src/utils/turnProgress.ts` turns a snapshot into the placeholder label, and `frontend/src/types/turnProgress.ts` mirrors the Python enums (a conformance test reads `progress.py` as text and pins both sides). On polling, `startPolling` in `src/services/api.ts` forwards `response.turn_progress` as a `turn_progress` stream event when its `seq` is higher than the last one it forwarded. `ChatPanel` validates the payload, keeps the snapshot with the highest `seq` (it resets at send) and passes the label to `MessageList`, which shows it in the placeholder (`data-testid="chat-turn-progress"`, `aria-live="polite"`). The `turn_progress` event is never added to the chat transcript.

| Snapshot | Label |
|----------|-------|
| None yet, or the legacy engine | `Generating slides...` |
| `planning` | `Planning the deck…` |
| `gathering_data` | `Gathering the data…` |
| `checking_slides` | `Checking the slides against the new brief…` |
| `reviewing_deck` | `Reviewing the narrative…` |
| `building` | One clause per active stage, in order building, reviewing, fixing, for example `Building 10 slides…`, `Reviewing slide 3…` or `Building 3 slides, reviewing 2 slides, fixing slide 6…`. Slide numbers are 1-based. ` (D of T done)` is appended when `done` is above 0 and `total` is above 1. With nothing active the label is `Building the slides…`, or `Finishing the slides…` once every slide is done. |

**Legacy engine.** The monolith never calls `invoke_graph`, so no tracker exists, every report is a no-op, `progress_json` stays NULL and the poll returns `"turn_progress": null`. The placeholder keeps `Generating slides...`. The rotating loading-message bar below the transcript is timer-driven and unchanged on both engines.

**Known gaps:**
- A crashed or unrecovered request keeps its last stage. The poll serves `turn_progress` for as long as the request's status is `pending` or `running`, and `recover_stuck_requests` marks a `running` request as `error` only at startup and only once it is older than 10 minutes. A turn whose worker died can therefore keep showing its last label. There is no staleness check on the snapshot.
- There is no resume after a page reload mid-turn. `startPolling` holds the `request_id` only in its closure, so a reload shows no placeholder for the in-flight turn.
- On SSE, the `error` event that `_placehold_failed_position` emits for a slide that could not be built reaches `ChatPanel`'s `error` case, which ends loading before the turn is over. This predates progress reporting; polling is unaffected.

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
| `role` | VARCHAR | `user`, `assistant`, `system` |
| `content` | TEXT | Message content |
| `message_type` | VARCHAR | `user_input`, `user_query`, `reasoning`, `tool_call`, `tool_result`, `llm_response`, `clarification`, `info`, `error` |
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
| `progress_json` | TEXT NULL | The graph turn's latest stage summary (JSON); NULL for the legacy engine and before the first report (#319) |
| `progress_seq` | INTEGER NULL | `seq` of the stored `progress_json`; the conditional UPDATE only writes a higher value (#319) |
| `created_at` | TIMESTAMP | Request creation time |
| `completed_at` | TIMESTAMP | Request completion time |

**Migration SQL:** See `scripts/migrate_polling_support.sql`. The two `progress_*` columns are not in that script; `_migrate_chat_request_progress()` adds them at startup (see [Database Configuration](database-configuration.md)).

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

