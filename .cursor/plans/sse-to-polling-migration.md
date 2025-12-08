---
name: SSE to Polling Migration
overview: Replace Server-Sent Events streaming with a polling-based approach to work around the Databricks Apps 60-second reverse proxy connection limit. Uses hybrid in-memory job queue with database-backed events.
todos:
  - id: db-model
    content: Add ChatRequest model and request_id column to SessionMessage
    status: completed

  - id: db-migration
    content: Create ALTER TABLE migration SQL for Lakebase
    status: completed
    dependencies:
      - db-model

  - id: session-manager
    content: Add chat request tracking + msg_to_stream_event methods
    status: completed
    dependencies:
      - db-model

  - id: job-queue
    content: Add job queue, worker, and recovery logic
    status: completed

  - id: callback-handler
    content: Update StreamingCallbackHandler to accept request_id parameter
    status: completed
    dependencies:
      - session-manager

  - id: chat-service
    content: Update send_message_streaming to pass request_id to callback
    status: completed
    dependencies:
      - callback-handler

  - id: backend-endpoints
    content: Add POST /api/chat/async and GET /api/chat/poll/{request_id}
    status: completed
    dependencies:
      - job-queue
      - chat-service

  - id: frontend-polling
    content: Add polling API, environment detection, update ChatPanel
    status: completed
    dependencies:
      - backend-endpoints

  - id: cleanup
    content: Add stale request cleanup and worker crash recovery
    status: completed
    dependencies:
      - backend-endpoints
---

# Polling-Based Chat Streaming

Replace SSE with polling to work around Databricks Apps' 60-second reverse proxy timeout. Combines in-memory job queue with existing database message persistence.

## Current Implementation (Context)

The following components exist and should be reused/extended:

### Backend

- **`src/services/streaming_callback.py`**: `StreamingCallbackHandler` already:
  - Emits events to a `queue.Queue`
  - Persists messages via `session_manager.add_message()`
  - Handles `on_llm_end`, `on_tool_start`, `on_tool_end`, `on_agent_action`

- **`src/api/services/session_manager.py`**: Existing session locking via:
  - `is_processing` and `processing_started_at` columns on `UserSession`
  - `acquire_session_lock()` / `release_session_lock()` methods

- **`src/api/schemas/streaming.py`**: Existing `StreamEvent` and `StreamEventType` enum

### Frontend

- **`frontend/src/contexts/GenerationContext.tsx`**: `isGenerating` state for navigation locking
- **`frontend/src/services/api.ts`**: `streamChat()` using SSE
- **`frontend/src/components/ChatPanel/ChatPanel.tsx`**: Event handling via `handleStreamEvent`

### Database

- `UserSession.is_processing` / `processing_started_at` already handle concurrent request blocking
- `SessionMessage` stores all messages with `message_type` and `metadata_json`

### Documentation

- `docs/technical/real-time-streaming.md` - Current SSE implementation

## Architecture

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

## Backend Changes

### 1. Database Model Updates

**Add to `src/database/models/session.py`:**

```python
class ChatRequest(Base):
    """Tracks async chat requests for polling."""
    __tablename__ = "chat_requests"

    id = Column(Integer, primary_key=True)
    request_id = Column(String(64), unique=True, nullable=False, index=True)
    session_id = Column(Integer, ForeignKey("user_sessions.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(20), default="pending")  # pending/running/completed/error
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    # Final result data (JSON) - slides, raw_html, replacement_info
    result_json = Column(Text, nullable=True)

    # Relationship
    session = relationship("UserSession")

    __table_args__ = (
        Index("ix_chat_requests_session_id", "session_id"),
    )
```

**Add to `SessionMessage`:**

```python
request_id = Column(String(64), nullable=True, index=True)  # Links messages to chat request
```

### 2. Database Migration

Run these ALTER statements on existing Lakebase instances:

```sql
-- Add chat_requests table
CREATE TABLE IF NOT EXISTS chat_requests (
    id SERIAL PRIMARY KEY,
    request_id VARCHAR(64) UNIQUE NOT NULL,
    session_id INTEGER NOT NULL REFERENCES user_sessions(id) ON DELETE CASCADE,
    status VARCHAR(20) DEFAULT 'pending',
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    result_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_chat_requests_request_id ON chat_requests(request_id);
CREATE INDEX IF NOT EXISTS ix_chat_requests_session_id ON chat_requests(session_id);

-- Add request_id to session_messages
ALTER TABLE session_messages ADD COLUMN IF NOT EXISTS request_id VARCHAR(64);
CREATE INDEX IF NOT EXISTS ix_session_messages_request_id ON session_messages(request_id);
```

**Note**: `deploy.sh update` does NOT run migrations. Options:
1. Run SQL manually via Databricks SQL
2. Delete and recreate app (loses data)
3. Add migration logic to app startup

### 3. In-Memory Job Queue

**Create `src/api/services/job_queue.py`:**

```python
"""In-memory job queue for async chat processing."""

import asyncio
import logging
import queue
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from src.api.schemas.streaming import StreamEventType

logger = logging.getLogger(__name__)

# In-memory job tracking (request_id -> metadata)
jobs: Dict[str, Dict[str, Any]] = {}
job_queue: asyncio.Queue = asyncio.Queue()


async def enqueue_job(request_id: str, payload: dict) -> None:
    """Add a job to the queue."""
    jobs[request_id] = {
        "status": "pending",
        "session_id": payload["session_id"],
        "queued_at": datetime.utcnow(),
    }
    await job_queue.put((request_id, payload))
    logger.info("Enqueued job", extra={"request_id": request_id})


def get_job_status(request_id: str) -> Optional[Dict[str, Any]]:
    """Get in-memory job status."""
    return jobs.get(request_id)


async def process_chat_request(request_id: str, payload: dict) -> None:
    """Process a chat request - runs agent and persists results."""
    from src.api.services.chat_service import get_chat_service
    from src.api.services.session_manager import get_session_manager
    from src.services.streaming_callback import StreamingCallbackHandler

    session_id = payload["session_id"]
    message = payload["message"]
    slide_context = payload.get("slide_context")

    chat_service = get_chat_service()
    session_manager = get_session_manager()

    # Create a queue - callback handler needs it for event flow
    # Events are persisted to DB which is what polling reads
    event_queue: queue.Queue = queue.Queue()

    try:
        # Update status
        session_manager.update_chat_request_status(request_id, "running")

        # Run blocking agent in thread pool
        await asyncio.to_thread(
            chat_service.send_message_streaming,
            session_id,
            message,
            event_queue,
            slide_context,
            request_id,  # Pass request_id to tag messages
        )

        # Extract final result from queue (COMPLETE event)
        result = None
        while not event_queue.empty():
            event = event_queue.get_nowait()
            if event.type == StreamEventType.COMPLETE:
                result = {
                    "slides": event.slides,
                    "raw_html": event.raw_html,
                    "replacement_info": event.replacement_info,
                }

        session_manager.set_chat_request_result(request_id, result)
        session_manager.update_chat_request_status(request_id, "completed")

    except Exception as e:
        logger.error(f"Job failed: {e}", extra={"request_id": request_id})
        session_manager.update_chat_request_status(request_id, "error", str(e))
        raise

    finally:
        # Always release session lock
        session_manager.release_session_lock(session_id)
        # Clean up in-memory tracking
        jobs.pop(request_id, None)


async def worker() -> None:
    """Background worker that processes jobs from the queue."""
    logger.info("Job queue worker started")
    while True:
        try:
            request_id, payload = await job_queue.get()
            jobs[request_id]["status"] = "running"

            try:
                await process_chat_request(request_id, payload)
            except Exception as e:
                jobs[request_id]["status"] = "error"
                jobs[request_id]["error"] = str(e)
                logger.error(f"Worker job failed: {e}", extra={"request_id": request_id})

            job_queue.task_done()

        except asyncio.CancelledError:
            logger.info("Job queue worker shutting down")
            break
        except Exception as e:
            logger.error(f"Worker loop error: {e}")


async def start_worker() -> asyncio.Task:
    """Start the background worker task."""
    return asyncio.create_task(worker())
```

### 4. Session Manager Additions

**Add to `src/api/services/session_manager.py`:**

```python
import secrets
from src.database.models.session import ChatRequest

# Chat request operations
def create_chat_request(self, session_id: str) -> str:
    """Create a new chat request, return request_id."""
    request_id = secrets.token_urlsafe(24)

    with get_db_session() as db:
        session = self._get_session_or_raise(db, session_id)

        chat_request = ChatRequest(
            request_id=request_id,
            session_id=session.id,
            status="pending",
        )
        db.add(chat_request)
        db.flush()

        logger.info(
            "Created chat request",
            extra={"request_id": request_id, "session_id": session_id},
        )

        return request_id


def update_chat_request_status(
    self,
    request_id: str,
    status: str,
    error: Optional[str] = None,
) -> None:
    """Update request status (pending/running/completed/error)."""
    with get_db_session() as db:
        chat_request = (
            db.query(ChatRequest)
            .filter(ChatRequest.request_id == request_id)
            .first()
        )

        if not chat_request:
            logger.warning(f"ChatRequest not found: {request_id}")
            return

        chat_request.status = status
        if error:
            chat_request.error_message = error
        if status in ("completed", "error"):
            chat_request.completed_at = datetime.utcnow()


def set_chat_request_result(self, request_id: str, result: Optional[dict]) -> None:
    """Store final result (slides, raw_html, etc)."""
    with get_db_session() as db:
        chat_request = (
            db.query(ChatRequest)
            .filter(ChatRequest.request_id == request_id)
            .first()
        )

        if not chat_request:
            return

        chat_request.result_json = json.dumps(result) if result else None


def get_chat_request(self, request_id: str) -> Optional[Dict[str, Any]]:
    """Get request status and result."""
    with get_db_session() as db:
        chat_request = (
            db.query(ChatRequest)
            .filter(ChatRequest.request_id == request_id)
            .first()
        )

        if not chat_request:
            return None

        return {
            "request_id": chat_request.request_id,
            "session_id": chat_request.session_id,
            "status": chat_request.status,
            "error_message": chat_request.error_message,
            "created_at": chat_request.created_at.isoformat(),
            "completed_at": chat_request.completed_at.isoformat() if chat_request.completed_at else None,
            "result": json.loads(chat_request.result_json) if chat_request.result_json else None,
        }


def get_messages_for_request(
    self,
    request_id: str,
    after_id: int = 0,
) -> List[Dict[str, Any]]:
    """Get messages with request_id, optionally after a given message ID."""
    with get_db_session() as db:
        query = (
            db.query(SessionMessage)
            .filter(SessionMessage.request_id == request_id)
        )

        if after_id > 0:
            query = query.filter(SessionMessage.id > after_id)

        messages = query.order_by(SessionMessage.created_at).all()

        return [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "message_type": m.message_type,
                "created_at": m.created_at.isoformat(),
                "metadata": json.loads(m.metadata_json) if m.metadata_json else None,
            }
            for m in messages
        ]


def msg_to_stream_event(self, msg: dict) -> dict:
    """Convert database message to StreamEvent-like dict for polling response."""
    event_type = "assistant"  # default

    if msg["message_type"] == "tool_call":
        event_type = "tool_call"
    elif msg["message_type"] == "tool_result":
        event_type = "tool_result"
    elif msg["role"] == "user":
        event_type = "assistant"  # User messages also use assistant type

    metadata = msg.get("metadata") or {}

    return {
        "type": event_type,
        "content": msg["content"],
        "tool_name": metadata.get("tool_name"),
        "tool_input": metadata.get("tool_input"),
        "tool_output": msg["content"] if event_type == "tool_result" else None,
        "message_id": msg["id"],
    }


def cleanup_stale_requests(self, max_age_hours: int = 24) -> int:
    """Clean up old/stuck chat requests."""
    cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)

    with get_db_session() as db:
        stale = (
            db.query(ChatRequest)
            .filter(ChatRequest.created_at < cutoff)
            .all()
        )

        count = len(stale)
        for req in stale:
            db.delete(req)

        if count > 0:
            logger.info(
                "Cleaned up stale chat requests",
                extra={"count": count},
            )

        return count
```

### 5. Callback Handler Update

**Update `src/services/streaming_callback.py`:**

```python
class StreamingCallbackHandler(BaseCallbackHandler):
    def __init__(
        self,
        event_queue: queue.Queue,
        session_id: str,
        request_id: Optional[str] = None,  # NEW
    ):
        super().__init__()
        self.event_queue = event_queue
        self.session_id = session_id
        self.request_id = request_id  # NEW
        self._session_manager = None
        self._current_tool_name: Optional[str] = None
```

**Update all `add_message()` calls to include `request_id`:**

```python
# In on_llm_end, on_tool_start, on_tool_end, on_agent_action:
msg = self.session_manager.add_message(
    session_id=self.session_id,
    request_id=self.request_id,  # NEW
    role="assistant",
    content=text,
    message_type="llm_response",
)
```

### 6. Chat Service Update

**Update `src/api/services/chat_service.py`:**

```python
def send_message_streaming(
    self,
    session_id: str,
    message: str,
    event_queue: queue.Queue,
    slide_context: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,  # NEW
) -> None:
    # ...
    callback = StreamingCallbackHandler(
        event_queue=event_queue,
        session_id=session_id,
        request_id=request_id,  # NEW
    )
    # ...
```

### 7. API Endpoints

**Add to `src/api/routes/chat.py`:**

```python
from src.api.services.job_queue import enqueue_job

@router.post("/chat/async")
async def submit_chat_async(request: ChatRequest):
    """Submit a chat request for async processing."""
    session_manager = get_session_manager()

    # Check session lock first
    if not await asyncio.to_thread(
        session_manager.acquire_session_lock, request.session_id
    ):
        raise HTTPException(
            status_code=409,
            detail="Session is already processing a request",
        )

    try:
        # Create request record
        request_id = await asyncio.to_thread(
            session_manager.create_chat_request, request.session_id
        )

        # Persist user message
        await asyncio.to_thread(
            session_manager.add_message,
            session_id=request.session_id,
            request_id=request_id,
            role="user",
            content=request.message,
            message_type="user_query",
        )

        # Queue for processing
        await enqueue_job(request_id, {
            "session_id": request.session_id,
            "message": request.message,
            "slide_context": request.slide_context.model_dump() if request.slide_context else None,
        })

        return {"request_id": request_id, "status": "pending"}

    except Exception as e:
        # Release lock on failure
        await asyncio.to_thread(
            session_manager.release_session_lock, request.session_id
        )
        logger.error(f"Failed to submit async chat: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chat/poll/{request_id}")
async def poll_chat(request_id: str, after_message_id: int = 0):
    """Poll for chat request status and new messages."""
    session_manager = get_session_manager()

    chat_request = await asyncio.to_thread(
        session_manager.get_chat_request, request_id
    )

    if not chat_request:
        raise HTTPException(status_code=404, detail="Request not found")

    messages = await asyncio.to_thread(
        session_manager.get_messages_for_request, request_id, after_message_id
    )

    events = [session_manager.msg_to_stream_event(m) for m in messages]

    return {
        "status": chat_request["status"],
        "events": events,
        "last_message_id": messages[-1]["id"] if messages else after_message_id,
        "result": chat_request.get("result") if chat_request["status"] == "completed" else None,
        "error": chat_request.get("error_message") if chat_request["status"] == "error" else None,
    }
```

### 8. App Startup

**Update `src/main.py` or app initialization:**

```python
from contextlib import asynccontextmanager
from src.api.services.job_queue import start_worker

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    worker_task = await start_worker()
    await recover_stuck_requests()

    yield

    # Shutdown
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass


async def recover_stuck_requests():
    """Mark running requests as error if worker died."""
    from src.api.services.session_manager import get_session_manager
    from src.database.models.session import ChatRequest

    session_manager = get_session_manager()

    with get_db_session() as db:
        stuck = (
            db.query(ChatRequest)
            .filter(
                ChatRequest.status == "running",
                ChatRequest.created_at < datetime.utcnow() - timedelta(minutes=10),
            )
            .all()
        )

        for req in stuck:
            req.status = "error"
            req.error_message = "Request timed out (worker crash recovery)"

            # Release any session locks
            session = db.query(UserSession).get(req.session_id)
            if session:
                session.is_processing = False
                session.processing_started_at = None

        if stuck:
            logger.info(f"Recovered {len(stuck)} stuck requests")
```

## Frontend Changes

### 1. Environment Detection

**Update `frontend/src/services/api.ts`:**

```typescript
const isPollingMode = (): boolean => {
  // Databricks Apps runs behind reverse proxy with 60s timeout
  // Detect via environment variable or hostname
  return (
    import.meta.env.VITE_USE_POLLING === 'true' ||
    window.location.hostname.includes('.cloud.databricks.com')
  );
};
```

### 2. New API Methods

```typescript
interface PollResponse {
  status: 'pending' | 'running' | 'completed' | 'error';
  events: StreamEvent[];
  last_message_id: number;
  result?: {
    slides?: SlideDeck;
    raw_html?: string;
    replacement_info?: Record<string, unknown>;
  };
  error?: string;
}

async submitChatAsync(
  sessionId: string,
  message: string,
  slideContext?: SlideContext,
): Promise<{ request_id: string }> {
  const response = await fetch(`${API_BASE_URL}/api/chat/async`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      message,
      slide_context: slideContext,
    }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new ApiError(response.status, error.detail || 'Failed to submit chat');
  }

  return response.json();
}

async pollChat(requestId: string, afterMessageId: number = 0): Promise<PollResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/chat/poll/${requestId}?after_message_id=${afterMessageId}`,
  );

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new ApiError(response.status, error.detail || 'Failed to poll chat');
  }

  return response.json();
}
```

### 3. Polling Loop

```typescript
function startPolling(
  sessionId: string,
  message: string,
  onEvent: (event: StreamEvent) => void,
  onError: (error: Error) => void,
  slideContext?: SlideContext,
): () => void {
  let cancelled = false;
  let pollInterval: ReturnType<typeof setInterval> | null = null;

  (async () => {
    try {
      const { request_id } = await api.submitChatAsync(sessionId, message, slideContext);

      let lastMessageId = 0;

      pollInterval = setInterval(async () => {
        if (cancelled) {
          if (pollInterval) clearInterval(pollInterval);
          return;
        }

        try {
          const response = await api.pollChat(request_id, lastMessageId);

          // Process new events
          for (const event of response.events) {
            onEvent(event);
          }
          lastMessageId = response.last_message_id;

          // Stop polling on completion
          if (response.status === 'completed' || response.status === 'error') {
            if (pollInterval) clearInterval(pollInterval);

            if (response.status === 'error') {
              onError(new Error(response.error || 'Request failed'));
            } else if (response.result) {
              // Emit complete event
              onEvent({
                type: StreamEventType.COMPLETE,
                slides: response.result.slides,
                raw_html: response.result.raw_html,
                replacement_info: response.result.replacement_info,
              });
            }
          }
        } catch (err) {
          console.error('Poll error:', err);
          // Don't stop polling on transient errors
        }
      }, 2000); // Poll every 2 seconds

    } catch (err) {
      onError(err instanceof Error ? err : new Error('Failed to start chat'));
    }
  })();

  // Return cancel function
  return () => {
    cancelled = true;
    if (pollInterval) clearInterval(pollInterval);
  };
}
```

### 4. Unified Send Function

```typescript
export function sendChatMessage(
  sessionId: string,
  message: string,
  onEvent: (event: StreamEvent) => void,
  onError: (error: Error) => void,
  slideContext?: SlideContext,
): () => void {
  if (isPollingMode()) {
    return startPolling(sessionId, message, onEvent, onError, slideContext);
  } else {
    return streamChat(sessionId, message, onEvent, onError, slideContext);
  }
}
```

### 5. Update ChatPanel

**In `frontend/src/components/ChatPanel/ChatPanel.tsx`:**

Replace:
```typescript
const cancel = api.streamChat(sessionId, trimmedContent, handleEvent, handleError);
```

With:
```typescript
const cancel = api.sendChatMessage(sessionId, trimmedContent, handleEvent, handleError, slideContext);
```

## Migration Strategy

1. **Keep existing `/api/chat/stream` endpoint** for local development (faster feedback)
2. **Frontend auto-detects environment** and chooses:
   - Local dev: SSE streaming
   - Databricks Apps: Polling
3. **Both paths use same event handling logic** (`handleStreamEvent`)
4. **Database migration required** for existing deployments

## Session Lock vs ChatRequest Status

- **Session Lock** (`is_processing`): Prevents concurrent requests to the SAME session
- **ChatRequest Status**: Tracks individual request progress for polling

The async endpoint checks session lock BEFORE creating ChatRequest, ensuring only one request processes per session at a time.

## Key Files Reference

| File | Purpose |
|------|---------|
| `src/services/streaming_callback.py` | Extend with `request_id` parameter |
| `src/api/services/session_manager.py` | Add ChatRequest CRUD methods |
| `src/api/services/job_queue.py` | NEW: In-memory queue + worker |
| `src/database/models/session.py` | Add `ChatRequest` model |
| `src/api/services/chat_service.py` | Pass `request_id` to callback |
| `src/api/routes/chat.py` | Add async/poll endpoints |
| `frontend/src/services/api.ts` | Add polling methods |
| `frontend/src/components/ChatPanel/ChatPanel.tsx` | Use unified send function |
| `docs/technical/real-time-streaming.md` | Current SSE implementation docs |

