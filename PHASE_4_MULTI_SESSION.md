# Phase 4: Multi-Session Support

## Goal
Implement full multi-session support with per-user session isolation, session management, and cleanup. Enable multiple concurrent users with independent conversation sessions.

## Prerequisites
- ✅ Phase 1, 2, and 3 complete
- ✅ App deployed to Databricks Apps
- ✅ User authentication working
- ✅ Logging and monitoring operational

## Success Criteria
- ✅ Multiple users can have independent sessions
- ✅ Users can create multiple sessions
- ✅ Session state persists across page refreshes
- ✅ Sessions automatically cleaned up after timeout
- ✅ Session isolation (users can't access each other's sessions)
- ✅ Session list/management in UI
- ✅ Graceful handling of expired sessions

## Architecture Changes for Phase 4
- **Backend**: Session manager with user-based isolation, cleanup background task
- **Frontend**: Session context, session selection UI, localStorage persistence
- **State Management**: Per-user session storage with limits
- **Security**: Session validation, user ownership verification

---

## Implementation Steps

### Step 1: Backend - Session Manager Service (Estimated: 4-5 hours)

#### 1.1 Create Session Manager

**`src/api/services/session_manager.py`**

```python
"""
Multi-session manager with per-user isolation.

Manages in-memory sessions with:
- User-based session isolation
- Session creation and cleanup
- Automatic timeout cleanup
- Session limits per user
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging
import threading

from src.models.slide_deck import SlideDeck
from src.services.agent import SlideGeneratorAgent, create_agent

logger = logging.getLogger(__name__)


@dataclass
class WebSession:
    """
    Web session state.
    
    Combines agent session with slide deck and metadata.
    """
    session_id: str
    user_id: str
    agent_session_id: str
    slide_deck: Optional[SlideDeck] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_activity: datetime = field(default_factory=datetime.utcnow)
    message_count: int = 0

    def update_activity(self):
        """Update last activity timestamp."""
        self.last_activity = datetime.utcnow()

    def is_expired(self, timeout_minutes: int) -> bool:
        """Check if session has expired."""
        age = datetime.utcnow() - self.last_activity
        return age > timedelta(minutes=timeout_minutes)

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "agent_session_id": self.agent_session_id,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "message_count": self.message_count,
            "has_slides": self.slide_deck is not None,
            "slide_count": len(self.slide_deck.slides) if self.slide_deck else 0,
        }


class SessionManager:
    """
    Manage web sessions with user isolation.
    
    Thread-safe session management with:
    - Per-user session limits
    - Automatic cleanup
    - Session validation
    """

    def __init__(
            self,
            agent: SlideGeneratorAgent,
            timeout_minutes: int = 60,
            max_sessions_per_user: int = 5,
    ):
        self.agent = agent
        self.timeout_minutes = timeout_minutes
        self.max_sessions_per_user = max_sessions_per_user

        # Storage: {session_id: WebSession}
        self.sessions: Dict[str, WebSession] = {}

        # Thread safety
        self.lock = threading.Lock()

        # Start cleanup task
        self._start_cleanup_task()

        logger.info(
            "SessionManager initialized",
            extra={
                "timeout_minutes": timeout_minutes,
                "max_sessions_per_user": max_sessions_per_user,
            }
        )

    def create_session(self, user_id: str) -> WebSession:
        """
        Create new session for user.
        
        Args:
            user_id: User identifier
        
        Returns:
            Created session
        
        Raises:
            ValueError: If user has too many sessions
        """
        with self.lock:
            # Check user's session count
            user_sessions = [s for s in self.sessions.values() if s.user_id == user_id]

            if len(user_sessions) >= self.max_sessions_per_user:
                # Clean up expired sessions first
                for session in user_sessions:
                    if session.is_expired(self.timeout_minutes):
                        self._delete_session_unsafe(session.session_id)

                # Check again
                user_sessions = [s for s in self.sessions.values() if s.user_id == user_id]
                if len(user_sessions) >= self.max_sessions_per_user:
                    raise ValueError(
                        f"User has reached maximum sessions ({self.max_sessions_per_user})"
                    )

            # Create agent session
            agent_session_id = self.agent.create_session()

            # Create web session
            session_id = str(uuid.uuid4())
            session = WebSession(
                session_id=session_id,
                user_id=user_id,
                agent_session_id=agent_session_id,
            )

            self.sessions[session_id] = session

            logger.info(
                "Session created",
                extra={
                    "session_id": session_id,
                    "user_id": user_id,
                    "agent_session_id": agent_session_id,
                }
            )

            return session

    def get_session(self, session_id: str, user_id: str) -> WebSession:
        """
        Get session by ID with user validation.
        
        Args:
            session_id: Session identifier
            user_id: User identifier (for validation)
        
        Returns:
            Session
        
        Raises:
            ValueError: If session not found or user mismatch
        """
        with self.lock:
            session = self.sessions.get(session_id)

            if not session:
                raise ValueError(f"Session not found: {session_id}")

            if session.user_id != user_id:
                logger.warning(
                    "Session access denied",
                    extra={
                        "session_id": session_id,
                        "requested_by": user_id,
                        "owner": session.user_id,
                    }
                )
                raise ValueError("Session access denied")

            if session.is_expired(self.timeout_minutes):
                self._delete_session_unsafe(session_id)
                raise ValueError(f"Session expired: {session_id}")

            session.update_activity()
            return session

    def update_session(
            self,
            session_id: str,
            user_id: str,
            slide_deck: Optional[SlideDeck] = None,
    ) -> WebSession:
        """
        Update session data.
        
        Args:
            session_id: Session identifier
            user_id: User identifier (for validation)
            slide_deck: Updated slide deck (optional)
        
        Returns:
            Updated session
        """
        with self.lock:
            session = self.get_session(session_id, user_id)

            if slide_deck is not None:
                session.slide_deck = slide_deck

            session.update_activity()
            return session

    def delete_session(self, session_id: str, user_id: str) -> None:
        """
        Delete session with user validation.
        
        Args:
            session_id: Session identifier
            user_id: User identifier (for validation)
        """
        with self.lock:
            session = self.get_session(session_id, user_id)
            self._delete_session_unsafe(session_id)

    def _delete_session_unsafe(self, session_id: str) -> None:
        """
        Delete session (must be called with lock held).
        
        Args:
            session_id: Session identifier
        """
        session = self.sessions.get(session_id)
        if not session:
            return

        # Clean up agent session
        try:
            self.agent.clear_session(session.agent_session_id)
        except Exception as e:
            logger.warning(f"Failed to clear agent session: {e}")

        # Delete web session
        del self.sessions[session_id]

        logger.info(
            "Session deleted",
            extra={
                "session_id": session_id,
                "user_id": session.user_id,
            }
        )

    def list_user_sessions(self, user_id: str) -> List[WebSession]:
        """
        List all sessions for user.
        
        Args:
            user_id: User identifier
        
        Returns:
            List of user's sessions
        """
        with self.lock:
            sessions = [
                s for s in self.sessions.values()
                if s.user_id == user_id and not s.is_expired(self.timeout_minutes)
            ]

            # Sort by last activity (most recent first)
            sessions.sort(key=lambda s: s.last_activity, reverse=True)

            return sessions

    def cleanup_expired_sessions(self) -> int:
        """
        Remove expired sessions.
        
        Returns:
            Number of sessions cleaned up
        """
        with self.lock:
            expired = [
                sid for sid, session in self.sessions.items()
                if session.is_expired(self.timeout_minutes)
            ]

            for session_id in expired:
                self._delete_session_unsafe(session_id)

            if expired:
                logger.info(
                    "Cleaned up expired sessions",
                    extra={"count": len(expired)}
                )

            return len(expired)

    def _start_cleanup_task(self):
        """Start background cleanup task."""

        def cleanup_loop():
            while True:
                try:
                    self.cleanup_expired_sessions()
                except Exception as e:
                    logger.error(f"Cleanup task error: {e}", exc_info=True)

                # Run every 10 minutes
                import time
                time.sleep(600)

        thread = threading.Thread(target=cleanup_loop, daemon=True)
        thread.start()
        logger.info("Cleanup task started")

    def get_stats(self) -> dict:
        """Get session statistics."""
        with self.lock:
            return {
                "total_sessions": len(self.sessions),
                "unique_users": len(set(s.user_id for s in self.sessions.values())),
                "sessions_by_user": {
                    user_id: len([s for s in self.sessions.values() if s.user_id == user_id])
                    for user_id in set(s.user_id for s in self.sessions.values())
                },
            }


# Global session manager instance
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """Get or create global session manager."""
    global _session_manager

    if _session_manager is None:
        from src.core.settings import get_settings
        settings = get_settings()

        agent = create_agent()

        _session_manager = SessionManager(
            agent=agent,
            timeout_minutes=getattr(settings, 'session_timeout_minutes', 60),
            max_sessions_per_user=getattr(settings, 'max_sessions_per_user', 5),
        )

    return _session_manager
```

#### 1.2 Update Settings

**`src/config/settings.py`**

Add session configuration:

```python
class Settings:
    def __init__(self):
        self.environment = os.getenv("ENVIRONMENT", "development")
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        
        # Session configuration
        self.session_timeout_minutes = int(os.getenv("SESSION_TIMEOUT_MINUTES", "60"))
        self.max_sessions_per_user = int(os.getenv("MAX_SESSIONS_PER_USER", "5"))
```

---

### Step 2: Backend - Update API Endpoints (Estimated: 3-4 hours)

#### 2.1 Create Session Routes

**`src/api/routes/sessions.py`** (new file)

```python
"""
Session management endpoints.

Handles session CRUD operations with user isolation.
"""

from fastapi import APIRouter, HTTPException, Request, Depends
from typing import List
from pydantic import BaseModel

from ..services.session_manager import get_session_manager, SessionManager

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

def get_user_id(request: Request) -> str:
    """Extract user ID from request."""
    return request.state.user["user_id"]

@router.post("")
async def create_session(
    request: Request,
    session_manager: SessionManager = Depends(get_session_manager)
):
    """Create a new conversation session."""
    user_id = get_user_id(request)
    
    try:
        session = session_manager.create_session(user_id)
        return session.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("")
async def list_sessions(
    request: Request,
    session_manager: SessionManager = Depends(get_session_manager)
):
    """List all sessions for current user."""
    user_id = get_user_id(request)
    
    try:
        sessions = session_manager.list_user_sessions(user_id)
        return {"sessions": [s.to_dict() for s in sessions]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{session_id}")
async def get_session(
    session_id: str,
    request: Request,
    session_manager: SessionManager = Depends(get_session_manager)
):
    """Get session details."""
    user_id = get_user_id(request)
    
    try:
        session = session_manager.get_session(session_id, user_id)
        return session.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    request: Request,
    session_manager: SessionManager = Depends(get_session_manager)
):
    """Delete a session."""
    user_id = get_user_id(request)
    
    try:
        session_manager.delete_session(session_id, user_id)
        return {"status": "deleted"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/stats")
async def get_stats(
    session_manager: SessionManager = Depends(get_session_manager)
):
    """Get session statistics (admin only in production)."""
    return session_manager.get_stats()
```

#### 2.2 Update Chat Routes

**`src/api/routes/chat.py`**

Update to use session manager:

```python
from fastapi import APIRouter, HTTPException, Request, Depends
from ..models.requests import ChatRequest
from ..models.responses import ChatResponse
from ..services.session_manager import get_session_manager, SessionManager
from src.models.slide_deck import SlideDeck

router = APIRouter(prefix="/api/chat", tags=["chat"])

def get_user_id(request: Request) -> str:
    return request.state.user["user_id"]

@router.post("", response_model=ChatResponse)
async def send_message(
    chat_request: ChatRequest,
    request: Request,
    session_manager: SessionManager = Depends(get_session_manager)
):
    """
    Send a message to the AI agent.
    
    Now requires session_id in request.
    """
    user_id = get_user_id(request)
    
    if not chat_request.session_id:
        raise HTTPException(status_code=400, detail="session_id required")
    
    try:
        # Get session (validates user ownership)
        session = session_manager.get_session(chat_request.session_id, user_id)
        
        # Call agent
        result = session_manager.agent.generate_slides(
            question=chat_request.message,
            session_id=session.agent_session_id,
            max_slides=chat_request.max_slides
        )
        
        # Parse HTML into SlideDeck
        if result["html"]:
            slide_deck = SlideDeck.from_html_string(result["html"])
            session_manager.update_session(
                session.session_id,
                user_id,
                slide_deck=slide_deck
            )
        
        # Update message count
        session.message_count += 1
        
        return {
            "messages": result["messages"],
            "slide_deck": slide_deck.to_dict() if slide_deck else None,
            "metadata": result["metadata"]
        }
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

#### 2.3 Update Slide Routes

**`src/api/routes/slides.py`**

Update all endpoints to require `session_id`:

```python
from fastapi import APIRouter, HTTPException, Request, Depends, Query
from ..services.session_manager import get_session_manager, SessionManager

router = APIRouter(prefix="/api/slides", tags=["slides"])

def get_user_id(request: Request) -> str:
    return request.state.user["user_id"]

@router.get("")
async def get_slides(
    session_id: str = Query(..., description="Session ID"),
    request: Request = None,
    session_manager: SessionManager = Depends(get_session_manager)
):
    """Get slides for session."""
    user_id = get_user_id(request)
    
    try:
        session = session_manager.get_session(session_id, user_id)
        if not session.slide_deck:
            raise HTTPException(status_code=404, detail="No slides available")
        return session.slide_deck.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

# Similar updates for reorder, update, duplicate, delete endpoints
# All require session_id query parameter
# All validate user ownership via session_manager.get_session()
```

#### 2.4 Update Main App

**`src/api/main.py`**

Include sessions router:

```python
from .routes import chat, slides, sessions

# Include routers
app.include_router(sessions.router)  # NEW
app.include_router(chat.router)
app.include_router(slides.router)
```

---

### Step 3: Frontend - Session Management (Estimated: 5-6 hours)

#### 3.1 Update Types

**`src/types/session.ts`**

```typescript
export interface Session {
  session_id: string;
  user_id: string;
  agent_session_id: string;
  created_at: string;
  last_activity: string;
  message_count: number;
  has_slides: boolean;
  slide_count: number;
}

export interface User {
  user_id: string;
  email: string;
  username: string;
  ip_address?: string;
}
```

#### 3.2 Update API Client

**`src/services/api.ts`**

Add session methods and update existing to use session_id:

```typescript
export const api = {
  // Session Management
  async createSession(): Promise<Session> {
    const response = await fetch(`${API_BASE_URL}/api/sessions`, {
      method: 'POST',
    });
    if (!response.ok) throw new ApiError(response.status, 'Failed to create session');
    return response.json();
  },

  async listSessions(): Promise<Session[]> {
    const response = await fetch(`${API_BASE_URL}/api/sessions`);
    if (!response.ok) throw new ApiError(response.status, 'Failed to list sessions');
    const data = await response.json();
    return data.sessions;
  },

  async getSession(sessionId: string): Promise<Session> {
    const response = await fetch(`${API_BASE_URL}/api/sessions/${sessionId}`);
    if (!response.ok) throw new ApiError(response.status, 'Failed to get session');
    return response.json();
  },

  async deleteSession(sessionId: string): Promise<void> {
    const response = await fetch(`${API_BASE_URL}/api/sessions/${sessionId}`, {
      method: 'DELETE',
    });
    if (!response.ok) throw new ApiError(response.status, 'Failed to delete session');
  },

  // Updated existing methods to require sessionId
  async sendMessage(
    sessionId: string,
    message: string,
    maxSlides: number = 10
  ): Promise<ChatResponse> {
    const response = await fetch(`${API_BASE_URL}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId,  // NOW REQUIRED
        message,
        max_slides: maxSlides,
      }),
    });
    if (!response.ok) throw new ApiError(response.status, 'Failed to send message');
    return response.json();
  },

  async getSlides(sessionId: string): Promise<SlideDeck> {
    const response = await fetch(`${API_BASE_URL}/api/slides?session_id=${sessionId}`);
    if (!response.ok) throw new ApiError(response.status, 'Failed to fetch slides');
    return response.json();
  },

  // Similar updates for reorderSlides, updateSlide, duplicateSlide, deleteSlide
  // All now require sessionId as first parameter
};
```

#### 3.3 Create Session Context

**`src/contexts/SessionContext.tsx`**

```typescript
import React, { createContext, useContext, useState, useEffect } from 'react';
import { Session } from '../types/session';
import { api } from '../services/api';

interface SessionContextType {
  currentSession: Session | null;
  sessions: Session[];
  isLoading: boolean;
  error: string | null;
  createSession: () => Promise<void>;
  selectSession: (sessionId: string) => Promise<void>;
  deleteSession: (sessionId: string) => Promise<void>;
  refreshSessions: () => Promise<void>;
}

const SessionContext = createContext<SessionContextType | undefined>(undefined);

export const SessionProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [currentSession, setCurrentSession] = useState<Session | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load sessions on mount
  useEffect(() => {
    refreshSessions();
    
    // Try to restore session from localStorage
    const savedSessionId = localStorage.getItem('currentSessionId');
    if (savedSessionId) {
      selectSession(savedSessionId).catch(() => {
        // Session expired or invalid, create new one
        createSession();
      });
    } else {
      // No saved session, create new one
      createSession();
    }
  }, []);

  // Save current session to localStorage
  useEffect(() => {
    if (currentSession) {
      localStorage.setItem('currentSessionId', currentSession.session_id);
    } else {
      localStorage.removeItem('currentSessionId');
    }
  }, [currentSession]);

  const refreshSessions = async () => {
    try {
      const sessions = await api.listSessions();
      setSessions(sessions);
    } catch (err) {
      console.error('Failed to load sessions:', err);
    }
  };

  const createSession = async () => {
    setIsLoading(true);
    setError(null);
    
    try {
      const session = await api.createSession();
      setCurrentSession(session);
      await refreshSessions();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to create session';
      setError(message);
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  const selectSession = async (sessionId: string) => {
    setIsLoading(true);
    setError(null);
    
    try {
      const session = await api.getSession(sessionId);
      setCurrentSession(session);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load session';
      setError(message);
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  const deleteSession = async (sessionId: string) => {
    try {
      await api.deleteSession(sessionId);
      
      // If deleting current session, create new one
      if (currentSession?.session_id === sessionId) {
        await createSession();
      }
      
      await refreshSessions();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to delete session';
      setError(message);
      throw err;
    }
  };

  return (
    <SessionContext.Provider
      value={{
        currentSession,
        sessions,
        isLoading,
        error,
        createSession,
        selectSession,
        deleteSession,
        refreshSessions,
      }}
    >
      {children}
    </SessionContext.Provider>
  );
};

export const useSession = () => {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error('useSession must be used within SessionProvider');
  }
  return context;
};
```

#### 3.4 Update Chat Panel

**`src/components/ChatPanel/ChatPanel.tsx`**

Update to use session context:

```typescript
import { useSession } from '../../contexts/SessionContext';

export const ChatPanel: React.FC<ChatPanelProps> = ({ onSlidesGenerated }) => {
  const { currentSession } = useSession();
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSendMessage = async (content: string, maxSlides: number) => {
    if (!currentSession) {
      setError('No active session');
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const response = await api.sendMessage(
        currentSession.session_id,  // Now required
        content,
        maxSlides
      );
      
      setMessages(prev => [...prev, ...response.messages]);
      
      if (response.slide_deck) {
        onSlidesGenerated(response.slide_deck);
      }
    } catch (err) {
      console.error('Failed to send message:', err);
      setError(err instanceof Error ? err.message : 'Failed to send message');
    } finally {
      setIsLoading(false);
    }
  };

  // ... rest of component
};
```

#### 3.5 Create Session Sidebar

**`src/components/Layout/SessionSidebar.tsx`**

```typescript
import React from 'react';
import { FiPlus, FiTrash2, FiMessageSquare } from 'react-icons/fi';
import { useSession } from '../../contexts/SessionContext';

export const SessionSidebar: React.FC = () => {
  const { currentSession, sessions, createSession, selectSession, deleteSession } = useSession();

  return (
    <div className="w-64 bg-gray-100 border-r flex flex-col">
      {/* Header */}
      <div className="p-4 border-b bg-white">
        <button
          onClick={createSession}
          className="w-full px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex items-center justify-center space-x-2"
        >
          <FiPlus />
          <span>New Session</span>
        </button>
      </div>

      {/* Session List */}
      <div className="flex-1 overflow-y-auto p-2 space-y-2">
        {sessions.map((session) => (
          <div
            key={session.session_id}
            onClick={() => selectSession(session.session_id)}
            className={`
              p-3 rounded-lg cursor-pointer transition-colors
              ${currentSession?.session_id === session.session_id
                ? 'bg-blue-100 border-2 border-blue-500'
                : 'bg-white hover:bg-gray-50 border-2 border-transparent'
              }
            `}
          >
            <div className="flex items-start justify-between">
              <div className="flex-1 min-w-0">
                <div className="flex items-center space-x-2">
                  <FiMessageSquare className="text-gray-500" size={16} />
                  <span className="text-sm font-medium truncate">
                    Session {session.session_id.slice(0, 8)}
                  </span>
                </div>
                
                <div className="mt-1 text-xs text-gray-500">
                  {session.message_count} messages
                  {session.has_slides && ` • ${session.slide_count} slides`}
                </div>
                
                <div className="mt-1 text-xs text-gray-400">
                  {new Date(session.last_activity).toLocaleString()}
                </div>
              </div>

              <button
                onClick={(e) => {
                  e.stopPropagation();
                  if (confirm('Delete this session?')) {
                    deleteSession(session.session_id);
                  }
                }}
                className="p-1 text-red-600 hover:bg-red-50 rounded"
              >
                <FiTrash2 size={14} />
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* Footer */}
      <div className="p-4 border-t bg-white text-xs text-gray-500">
        {sessions.length} active session{sessions.length !== 1 ? 's' : ''}
      </div>
    </div>
  );
};
```

#### 3.6 Update App Layout

**`src/components/Layout/AppLayout.tsx`**

```typescript
import { SessionProvider } from '../../contexts/SessionContext';
import { SessionSidebar } from './SessionSidebar';

export const AppLayout: React.FC = () => {
  return (
    <SessionProvider>
      <div className="h-screen flex flex-col">
        {/* Header */}
        <header className="bg-blue-600 text-white px-6 py-4 shadow-md">
          <h1 className="text-xl font-bold">AI Slide Generator</h1>
          <p className="text-sm text-blue-100">
            Phase 4 - Multi-Session Support
          </p>
        </header>

        {/* Main Content: Three panels */}
        <div className="flex-1 flex overflow-hidden">
          {/* Session Sidebar - Left */}
          <SessionSidebar />

          {/* Chat Panel - Center-Left */}
          <div className="w-[30%] border-r">
            <ChatPanel onSlidesGenerated={setSlideDeck} />
          </div>

          {/* Slide Panel - Right */}
          <div className="flex-1">
            <SlidePanel slideDeck={slideDeck} onSlideChange={setSlideDeck} />
          </div>
        </div>
      </div>
    </SessionProvider>
  );
};
```

---

### Step 4: Testing (Estimated: 3-4 hours)

#### 4.1 Backend Testing

```bash
# Test session creation
curl -X POST http://localhost:8000/api/sessions \
  -H "X-Forwarded-User: user1@example.com"

# Test listing sessions
curl http://localhost:8000/api/sessions \
  -H "X-Forwarded-User: user1@example.com"

# Test session isolation (different user)
curl http://localhost:8000/api/sessions/{session_id} \
  -H "X-Forwarded-User: user2@example.com"
# Should return 404 or access denied
```

#### 4.2 Frontend Testing

Test flows:
1. **Session Creation**: Click "New Session" → creates new session
2. **Session Switching**: Click different sessions → chat history clears, slides update
3. **Session Persistence**: Refresh page → same session loads
4. **Session Deletion**: Delete session → creates new one automatically
5. **Multiple Sessions**: Create 3+ sessions → all independent
6. **Session Limit**: Create 6+ sessions → shows error

#### 4.3 Multi-User Testing

Test with multiple browser profiles or users:
1. User A creates session → generates slides
2. User B creates session → different slides
3. Verify User A can't access User B's session
4. Verify sessions don't interfere

---

### Step 5: Documentation (Estimated: 1 hour)

**`README_PHASE4.md`**

```markdown
# AI Slide Generator - Phase 4 Multi-Session

## Complete Feature Set
- ✅ Multi-session support with per-user isolation
- ✅ Session management UI
- ✅ Session persistence across page refreshes
- ✅ Automatic session cleanup
- ✅ Session limits per user
- ✅ Full slide editing and chat features

## Usage

### Session Management
1. **New Session**: Click "New Session" in sidebar
2. **Switch Sessions**: Click any session to switch
3. **Delete Session**: Click trash icon on session

### Session Persistence
- Current session saved to localStorage
- Automatically restored on page refresh
- Expired sessions cleaned up automatically

### Limits
- Maximum 5 sessions per user (configurable)
- Sessions expire after 60 minutes of inactivity
- Cleanup runs every 10 minutes

## Configuration

### Environment Variables
```bash
SESSION_TIMEOUT_MINUTES=60      # Session timeout
MAX_SESSIONS_PER_USER=5         # Max sessions per user
```

### Deployment
No changes to deployment process from Phase 3.
Just redeploy with updated code.

## Technical Details

### Backend
- `SessionManager`: Thread-safe session management
- Per-user session isolation with validation
- Background cleanup task
- Session statistics endpoint

### Frontend
- `SessionContext`: React context for session state
- `SessionSidebar`: Session list UI component
- localStorage persistence
- Automatic session restoration

### Security
- User validation on all session operations
- Sessions tied to user_id from headers
- No cross-user session access
- Session expiration enforced

## Monitoring

### New Metrics
- Sessions per user
- Session creation rate
- Session expiration rate
- Average session duration

### Logs
All session operations logged with:
- `session_id`
- `user_id`
- `action` (create, delete, access, etc.)

## Migration from Phase 3

1. Deploy Phase 4 code
2. Existing users will start fresh (no migration needed)
3. All users get new sessions automatically
4. No data loss (sessions were ephemeral anyway)

## Known Limitations

### No Persistence Across Restarts
- Sessions stored in memory only
- App restart clears all sessions
- Future: Add Redis/database backend

### Session Limits
- Hard limit of 5 sessions per user
- Old sessions must be deleted manually
- Future: Auto-archive old sessions

## Future Enhancements

1. **Session Persistence**: Redis or database
2. **Session Naming**: User-defined session names
3. **Session Sharing**: Share sessions with other users
4. **Session Export**: Download session history
5. **Session Templates**: Save common workflows
```

---

## Phase 4 Complete Checklist

### Backend
- [ ] SessionManager implemented with user isolation
- [ ] Session CRUD endpoints
- [ ] Cleanup background task working
- [ ] All APIs updated to use session_id
- [ ] Session limits enforced
- [ ] Session statistics available

### Frontend
- [ ] SessionContext implemented
- [ ] SessionSidebar UI created
- [ ] Session creation/selection working
- [ ] localStorage persistence working
- [ ] All APIs updated to pass session_id
- [ ] Error handling for expired sessions

### Integration
- [ ] Session isolation verified
- [ ] Multiple users tested
- [ ] Session persistence tested
- [ ] Session cleanup verified
- [ ] All features work with sessions

### Documentation
- [ ] Usage guide complete
- [ ] Configuration documented
- [ ] Monitoring guide updated
- [ ] Known limitations documented

---

## Estimated Total Time: 16-21 hours

- Backend Session Manager: 4-5 hours
- Backend API Updates: 3-4 hours
- Frontend Session Management: 5-6 hours
- Testing: 3-4 hours
- Documentation: 1-2 hours

---

## Success!

All phases complete! The AI Slide Generator now has:
- Full-featured chat interface
- Rich slide editing capabilities
- Drag-and-drop reordering
- Databricks Apps deployment
- Multi-session support with user isolation

Ready for production use!

