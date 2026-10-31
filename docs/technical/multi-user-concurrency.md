# Multi-User Concurrency

How the backend handles concurrent requests from multiple users without blocking or race conditions.

---

## Overview

The AI Slide Generator supports multiple simultaneous users through:
- **Session-scoped state** – each user operates on their own session with isolated slide decks
- **Async endpoint handlers** – FastAPI endpoints use `asyncio.to_thread()` for blocking LLM calls
- **Database-based locking** – prevents concurrent mutations to the same session
- **Per-request tool binding** – eliminates shared mutable state in the LangChain agent
- **Per-user session isolation** – sessions are scoped to the authenticated user via the `created_by` column

---

## Per-User Session Isolation

Sessions are isolated per user using the `created_by` column. Authentication middleware extracts the username from the Databricks token in production (or from `DEV_USER_ID` in local development) and stores it in a `ContextVar`. The `GET /api/sessions` endpoint automatically filters by `created_by = current_user`, so each user sees only their own sessions. The `POST /api/sessions` endpoint sets `created_by` server-side from the authenticated user identity; clients do not pass or override this value.

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
    with get_db_session() as db:
        # SELECT ... FOR UPDATE — blocks concurrent callers until this
        # transaction commits, providing row-level locking in PostgreSQL.
        session = (
            db.query(UserSession)
            .filter(UserSession.session_id == session_id)
            .with_for_update(nowait=False)
            .first()
        )

        if not session:
            return True  # Auto-creation path

        if session.is_processing:
            if session.processing_started_at:
                age = (datetime.utcnow() - session.processing_started_at).total_seconds()
                if age < timeout_seconds:
                    return False  # Busy
            # Stale lock — proceed to acquire

        session.is_processing = True
        session.processing_started_at = datetime.utcnow()
        db.commit()
        return True
```

> **Note:** The `.with_for_update(nowait=False)` call issues a PostgreSQL `SELECT ... FOR UPDATE`, which takes a row-level lock for the duration of the transaction. This prevents two workers from reading the same row simultaneously and both concluding the session is free. If the database does not support `FOR UPDATE` (e.g., during tests), the code falls back to a plain query.

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

### Optimistic Locking (Version Conflict Detection)

In addition to the pessimistic session lock above, `ChatService` uses **optimistic locking** when saving slide decks. Before invoking the LLM, the service snapshots the current deck version. After the LLM completes, it passes `expected_version` to the session manager's save method. If another request modified the deck in the meantime, `VersionConflictError` is raised and the chat result is discarded rather than silently overwriting the concurrent edit:

```python
# src/api/services/chat_service.py  (simplified)
_deck_version_before_llm = self._get_deck_version(session_id)

try:
    session_manager.save_slide_deck(..., expected_version=_deck_version_before_llm)
except VersionConflictError:
    logger.warning("Chat save rejected: deck was edited during LLM call, reloading")
    self._invalidate_deck_cache(session_id)
```

`VersionConflictError` is defined in `src/api/services/session_manager.py` and carries `current_version` and `expected_version` for diagnostics.

### 5. Async Chat Requests (Polling Mode)

For polling-based streaming, async requests are tracked in the `chat_requests` table:

| Column | Type | Purpose |
|--------|------|---------|
| `request_id` | `VARCHAR(64)` | Unique request identifier |
| `session_id` | `INTEGER FK` | Links to user_sessions |
| `status` | `VARCHAR(20)` | `pending`/`running`/`completed`/`error` |
| `result_json` | `TEXT` | Final result (slides, raw_html) |
| `progress_json` | `TEXT NULL` | Graph turn's latest stage summary (#319) |
| `progress_seq` | `INTEGER NULL` | `seq` of the stored `progress_json` (#319) |
| `created_at` | `TIMESTAMP` | Request creation time |
| `completed_at` | `TIMESTAMP` | Request completion time |

Messages are linked to requests via `session_messages.request_id` for efficient polling.

The graph turn's stage summary is written to the request's row (`progress_json`, `progress_seq`) by a conditional `UPDATE ... WHERE progress_seq IS NULL OR progress_seq < :seq`, so concurrent slide pipelines cannot move it backwards, and on PostgreSQL the write sets `lock_timeout` to 2 seconds so it waits at most 2 seconds for the row lock. The poll reads that row rather than in-process state, so any worker serves the same stage. See [Real-Time Streaming](real-time-streaming.md#turn-progress-graph-engine-319).

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

Session endpoints (`/api/sessions/*`) manage session lifecycle and do not require locking, with two exceptions: **`DELETE /api/sessions/{id}/context` (Clear chat)** and **`DELETE /api/sessions/{id}/messages/{message_id}` (delete a message)** take the session lock. Each runs, in order, the deck permission gate (CAN_EDIT), the conversation-creator gate, `acquire_session_lock`, the clear or the delete, and the release. If a chat turn or a slide operation holds the lock, it answers **409** with `CONVERSATION_BUSY_DETAIL` ("Something is still running on this deck. Wait for it to finish, then try again.") and changes nothing. It releases the lock in `finally`, and only if this request acquired it, so a 409 never releases another request's lock. The chat panel maps any 409 from these routes to its own copy, by status rather than by matching the detail text. A delete does not need the deck *editing* lock (`/api/sessions/{id}/lock`), because it changes no deck state; the panel disables the action whenever it is read-only.

Known limits of that lock, shared with every other lock user:
- A lock older than 300 seconds counts as stale and can be taken by another request.
- On the SSE chat path the lock is released in the stream generator's `finally` while the turn keeps running in a daemon thread. A client that disconnects or reloads mid-turn therefore releases the lock early, and a clear or a delete in that window succeeds; the turn's later rows and checkpoints then land after it (in the cleared conversation, or after the deleted turn). The async/polling path holds the lock for the whole job, so this affects the SSE path only.
- The describe-only arc-review sweeper (`spec_sync.py`) invokes the graph on the owner's thread without the lock. Its turn checkpoints every channel after each superstep, and the thread holds cross-turn state (the `findings` log, for one), so a thread deleted under it would come back with the state from before the clear or delete, and the next turn would resume it. So a clear and a delete also check the deck's arc-review claim. While `spec_sync.review_in_flight` is true (a claim younger than `CLAIM_TTL_SECONDS`), `clear_context` and `delete_message` raise `ArcReviewInFlightError` before they change anything, and the route answers the same 409. The deck row is read `FOR UPDATE`, so on PostgreSQL a claim that arrives during a clear or a delete waits for it to commit, and its review then loads the already-deleted thread. Contributor sessions are never refused, because the sweeper runs on the owner's thread only.
- A delete clicked the instant a turn completes can answer 409. On the polling path the request is marked completed before the lock is released (`job_queue.py`), and on the SSE path a turn that generates the deck's title (the first message) joins the title thread, for up to 10 seconds, after `complete`, before the stream generator releases the lock. The panel's 409 copy tells the user to wait.

**What the graph thread holds.** It is not only per-turn state. The checkpointer keeps every checkpoint of every turn, so after a few turns the thread still holds each turn's user message (in the `__start__` and `architect_message` channels) and the architect's reply (`architect_message`). Nothing replays the thread to an agent: the architect's `conversation` is rebuilt from `session_messages` on every turn, and graph state has no messages key. A clear or a delete therefore deletes the whole thread, inside its own transaction, so that the checkpoint does not keep what the conversation no longer does. The next turn starts a new thread. The cost is the two values a node reads across turns, `deck_spec` and `design_system_active`, which go with the thread (and `findings`, which no node reads): an `ask_data` turn after a clear or a delete sends the data analyst `deck_purpose: None`, because an `ask_data` turn returns before the architect writes `deck_spec`, and so does every later one until a build or edit turn writes `deck_spec` into the new thread. The only effect today is that missing purpose; `design_system_active` does not change the analyst's shipped prompt (neither design-system stage applies to that role), and build and edit turns rewrite `deck_spec`. This is a recorded follow-up.

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

`run.py` starts uvicorn with a configurable worker count (default 4):

```python
# packages/databricks-tellr-app/databricks_tellr_app/run.py
workers = int(os.getenv("UVICORN_WORKERS", "4"))
uvicorn.run("src.api.main:app", host=host, port=port, workers=workers)
```

Set the `UVICORN_WORKERS` environment variable to override the default. Each worker has its own `ChatService` singleton and deck cache. The database-based session locking ensures correctness across workers.

### Chat Job Runners

A chat turn (polling mode) runs on the uvicorn worker that received its `POST /api/chat/async`, in that worker's in-memory queue (`src/api/services/job_queue.py`). Each worker runs `TELLR_CHAT_JOB_CONCURRENCY` job runners over its queue: default 4, at most 16, and an unusable value falls back to 4. With the default 4 workers, the app runs up to 16 turns at once. A turn waits only when all runners on its worker are busy.

- **Sessions stay serial.** The database session lock still allows one turn per session, so runners only overlap different sessions.
- **Own thread pool.** Chat jobs run on a dedicated `chat-job` thread pool sized to the runners, not on the loop's default executor. Request handlers (the chat poll among them) `asyncio.to_thread` onto the default executor, and jobs that hold a thread for minutes would starve them.
- **Waiting is visible.** While a turn waits for a runner, its request is `pending` with no `turn_progress`. The poll loop forwards a `queued` event, and the chat shows "Waiting for another request to finish…" until the turn starts.
- **Restarts.** The queue is in memory, so a turn still waiting when its worker restarts is lost and stays `pending`.

Before this, each worker ran one chat job at a time, so a second turn on the same worker waited for the first to finish. On 2026-10-31 an agent turn waited 3 m 45 s behind a concurrent legacy turn. Prod history over 35 days (6,182 turns) peaked at 9 concurrent turns against 4 slots.

### Scaling Considerations

- **Worker count:** Defaults to 4 (configurable via `UVICORN_WORKERS` env var). Each worker holds a database pool of up to 100 connections (`pool_size=80`, `max_overflow=20`) and runs every periodic loop, so prefer raising `TELLR_CHAT_JOB_CONCURRENCY` for more concurrent turns.
- **Concurrent turns:** `UVICORN_WORKERS × TELLR_CHAT_JOB_CONCURRENCY` (16 by default). The model endpoints' rate limits are the next ceiling: a deck builds its slides in parallel, so each turn makes many model calls at once.
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
- [Permissions Model](permissions-model.md) – exclusive editing lock and contributor sessions

