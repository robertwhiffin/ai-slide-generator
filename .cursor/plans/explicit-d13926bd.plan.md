<!-- d13926bd-dea8-4855-9623-e1d1435ecfbf 6479c8bf-4659-4a01-a37c-04fc359f0171 -->
# Lazy Session Persistence

## Problem

Sessions are immediately persisted to the database on creation, filling the database with empty/unused sessions.

## Solution

Sessions exist only in-memory until explicitly saved. The agent already maintains in-memory session state (`agent.sessions`) and slide decks are already cached (`ChatService._deck_cache`). We leverage this for lazy persistence - no database writes until user clicks "Save".

## Architecture

**Current flow:**

1. Frontend calls `POST /api/sessions` -> DB row created immediately
2. User sends messages -> stored to DB
3. Slides generated -> stored to DB

**New flow:**

1. Frontend generates local session ID (UUID) - no API call
2. Backend works with in-memory sessions (agent already supports this)
3. User clicks "Save" -> single API call creates DB session with all data

## Changes

### 1. Backend: Chat Service

**File:** [`src/api/services/chat_service.py`](src/api/services/chat_service.py)

Modify `send_message()` to work without requiring a database session:

- Remove the `session_manager.get_session()` validation check
- Let `_ensure_agent_session()` create in-memory session on-demand
- Skip database persistence of slide decks (remove `session_manager.save_slide_deck()` call)
- Skip `session_manager.update_last_activity()` call

### 2. Backend: New Save Endpoint  

**File:** [`src/api/routes/sessions.py`](src/api/routes/sessions.py)

Add endpoint to persist an ephemeral session:

```python
@router.post("/save")
async def save_session(request: SaveSessionRequest):
    """Persist an ephemeral session to the database."""
```

### 3. Backend: Chat Service Save Method

**File:** [`src/api/services/chat_service.py`](src/api/services/chat_service.py)

Add method to persist session data:

```python
def save_session(self, session_id: str, title: str) -> Dict[str, Any]:
    """Persist ephemeral session to database."""
```

### 4. Frontend: Session Context

**File:** [`frontend/src/contexts/SessionContext.tsx`](frontend/src/contexts/SessionContext.tsx)

- Remove `api.createSession()` call on mount
- Generate local UUID for `sessionId` instead  
- Add `saveSession(title)` function that calls new save endpoint
- Remove localStorage persistence (ephemeral sessions don't persist across reloads)

### 5. Frontend: API Service

**File:** [`frontend/src/services/api.ts`](frontend/src/services/api.ts)

Add `saveSession(sessionId: string, title: string)` method.

### 6. Frontend: UI Updates

**File:** [`frontend/src/components/Layout/AppLayout.tsx`](frontend/src/components/Layout/AppLayout.tsx)

Update "Save As" handler to call new `saveSession()` from context.

## Behavior Summary

| Action | Before | After |

|--------|--------|-------|

| App loads | DB session created | Local UUID, no DB write |

| Send message | Stored to DB | In-memory only |

| Generate slides | Stored to DB | In-memory only |

| Click "Save" | Renames existing | Creates DB session with data |

| Browser refresh | Session restored | Fresh session (unsaved lost) |

## Notes

- No database migration needed
- Unsaved sessions lost on refresh (expected UX)
- Agent's Genie conversation ID already managed in-memory

### To-dos

- [ ] Add is_saved column to UserSession model
- [ ] Add save_session() method and update list_sessions() filter
- [ ] Add POST /{session_id}/save API endpoint
- [ ] Add saveSession() to frontend API service
- [ ] Add saveSession() to SessionContext and wire up
- [ ] Update AppLayout to use new save functionality
- [ ] Create and run Alembic migration for is_saved column