# Multi-User Concurrency

How the backend handles concurrent requests from multiple users without blocking or race conditions.

---

## Overview

The AI Slide Generator supports multiple simultaneous users through:
- **Session-scoped state** – each user operates on their own session with isolated slide decks
- **Async endpoint handlers** – FastAPI endpoints use `asyncio.to_thread()` for blocking LLM calls
- **Database-based locking** – prevents concurrent mutations to the same session
- **Per-request tool binding** – eliminates shared mutable state in the LangChain agent

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         uvicorn (4 workers)                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│  FastAPI async handlers                                                      │
│       │                                                                      │
│       ▼                                                                      │
│  asyncio.to_thread() ──► ChatService (singleton per worker)                  │
│                              │                                               │
│                              ├── _cache_lock (threading.Lock)                │
│                              └── _deck_cache: Dict[session_id, SlideDeck]    │
│                                      │                                       │
│                                      ▼                                       │
│                           SlideGeneratorAgent                                │
│                              └── _create_tools_for_session(session_id)       │
│                                    └── Closure-bound genie wrapper           │
├─────────────────────────────────────────────────────────────────────────────┤
│  PostgreSQL / Lakebase                                                       │
│       └── user_sessions (is_processing, processing_started_at)               │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Key Mechanisms

### 1. Async Request Handling

All FastAPI endpoints are `async def`. Blocking operations (LLM calls, database queries) are wrapped with `asyncio.to_thread()` so the event loop remains responsive:

```python
# src/api/routes/chat.py
@router.post("/chat")
async def send_message(request: ChatRequest):
    result = await asyncio.to_thread(
        chat_service.send_message,
        request.session_id,
        request.message,
        ...
    )
```

This allows one worker to handle multiple in-flight requests concurrently.

### 2. Database-Based Session Locking

Mutation endpoints (chat, reorder, update, duplicate, delete) acquire a session lock before proceeding:

```python
# src/api/services/session_manager.py
def acquire_session_lock(self, session_id: str, timeout_seconds: int = 300) -> bool:
    # If session doesn't exist yet, allow proceeding (auto-creation)
    if not session:
        return True
    
    if session.is_processing:
        # Check for stale lock (held > timeout)
        if age < timeout_seconds:
            return False  # Busy
    
    session.is_processing = True
    session.processing_started_at = datetime.utcnow()
    return True
```

**Lock lifecycle:**
1. `acquire_session_lock()` called at endpoint start
2. If locked → return HTTP 409 Conflict
3. If available → set `is_processing=True`, proceed
4. `release_session_lock()` called in `finally` block

**Columns added to `user_sessions`:**
| Column | Type | Purpose |
|--------|------|---------|
| `is_processing` | `BOOLEAN NOT NULL DEFAULT FALSE` | Lock flag |
| `processing_started_at` | `TIMESTAMP` | Stale lock detection (>5 min) |

### 5. Async Chat Requests (Polling Mode)

For polling-based streaming, async requests are tracked in the `chat_requests` table:

| Column | Type | Purpose |
|--------|------|---------|
| `request_id` | `VARCHAR(64)` | Unique request identifier |
| `session_id` | `INTEGER FK` | Links to user_sessions |
| `status` | `VARCHAR(20)` | `pending`/`running`/`completed`/`error` |
| `result_json` | `TEXT` | Final result (slides, raw_html) |
| `created_at` | `TIMESTAMP` | Request creation time |
| `completed_at` | `TIMESTAMP` | Request completion time |

Messages are linked to requests via `session_messages.request_id` for efficient polling.

### 3. Per-Request Tool Binding

The LangChain agent previously used a shared `current_session_id` instance variable—a race condition when multiple requests ran in parallel. Now tools are created per-request with the session ID bound via closure:

```python
# src/services/agent.py
def generate_slides(self, question: str, session_id: str, ...):
    # Create tools with session_id bound via closure
    tools = self._create_tools_for_session(session_id)
    agent_executor = self._create_agent_executor(tools)
    
    result = agent_executor.invoke(agent_input)
```

The Genie wrapper inside `_create_tools_for_session()` captures the `session` dict reference at creation time, eliminating any shared mutable state.

### 4. Thread-Safe Deck Cache

`ChatService` maintains an in-memory slide deck cache keyed by session ID. All cache access is protected by `_cache_lock`:

```python
# src/api/services/chat_service.py
class ChatService:
    def __init__(self):
        self._cache_lock = threading.Lock()
        self._deck_cache: Dict[str, SlideDeck] = {}
    
    def _get_or_load_deck(self, session_id: str) -> Optional[SlideDeck]:
        with self._cache_lock:
            if session_id in self._deck_cache:
                return self._deck_cache[session_id]
        # Load from database (outside lock)
        ...
```

---

## Endpoints Requiring Session ID

All slide manipulation and chat endpoints require `session_id`:

| Endpoint | Method | Session ID Location |
|----------|--------|---------------------|
| `/api/chat` | POST | Request body (`session_id`) |
| `/api/slides` | GET | Query param (`?session_id=...`) |
| `/api/slides/reorder` | PUT | Request body (`session_id`) |
| `/api/slides/{index}` | PATCH | Request body (`session_id`) |
| `/api/slides/{index}/duplicate` | POST | Request body (`session_id`) |
| `/api/slides/{index}` | DELETE | Query param (`?session_id=...`) |

Session endpoints (`/api/sessions/*`) manage session lifecycle and do not require locking.

---

## Error Responses

| Status | Meaning | When |
|--------|---------|------|
| 409 Conflict | Session is busy | Another request is processing the same session |
| 404 Not Found | Session doesn't exist | Invalid session ID (for operations that require existing session) |

Frontend should handle 409 by showing a "please wait" message or retrying after delay.

---

## Production Deployment

### Multiple Workers

`app.yaml` configures uvicorn with 4 workers:

```yaml
command:
  - "sh"
  - "-c"
  - |
    uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 4
```

Each worker has its own `ChatService` singleton and deck cache. The database-based session locking ensures correctness across workers.

### Scaling Considerations

- **Worker count:** 4 workers is a reasonable default. Increase for higher concurrency; each worker can handle multiple async requests.
- **Lock timeout:** 5 minutes covers long LLM generations. Stale locks are automatically overridden.
- **Cache coherence:** Each worker maintains its own cache. Decks are loaded from database on cache miss, ensuring consistency after cross-worker updates.

---

## Database Migration

Existing databases need the session locking columns:

```sql
ALTER TABLE user_sessions ADD COLUMN is_processing BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE user_sessions ADD COLUMN processing_started_at TIMESTAMP;
```

For polling support, run `scripts/migrate_polling_support.sql`:

```sql
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

ALTER TABLE session_messages ADD COLUMN IF NOT EXISTS request_id VARCHAR(64);
CREATE INDEX IF NOT EXISTS ix_session_messages_request_id ON session_messages(request_id);
```

Fresh deployments create these tables automatically via SQLAlchemy model definitions.

---

## Cross-References

- [Backend Overview](backend-overview.md) – request lifecycle and agent architecture
- [Real-Time Streaming](real-time-streaming.md) – SSE events and message persistence
- [Database Configuration](database-configuration.md) – session schema details
- [Frontend Overview](frontend-overview.md) – how the UI passes session IDs

