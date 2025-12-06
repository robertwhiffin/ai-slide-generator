<!-- 99dce6e4-505c-4f85-96c7-f2379e31f35e 217cb016-19b7-4438-b920-a50b71bf3037 -->
# Phase 2: Real-Time Streaming + Conversation Persistence

## Goals

1. **Real-time progress:** Show LLM messages, tool calls, and results as they happen via SSE
2. **Conversation persistence:** Save all messages to database, restore on session load
3. **Agent state restoration:** Hydrate agent's ChatMessageHistory from DB when resuming session
4. **Navigation lock:** Prevent user from navigating away during generation

---

## Architecture

```
Frontend                    Backend SSE Endpoint                Agent Thread
    │                              │                                  │
    │  POST /api/chat/stream       │                                  │
    │─────────────────────────────►│                                  │
    │  [Navigation disabled]       │   Start agent in thread          │
    │                              │─────────────────────────────────►│
    │                              │                                  │
    │   event: assistant           │◄── callback: emit + persist ─────│
    │◄─────────────────────────────│         ▼                        │
    │                              │    [Write to DB]                 │
    │                              │                                  │
    │   event: complete            │◄── agent finished ───────────────│
    │◄─────────────────────────────│                                  │
    │  [Navigation re-enabled]     │                                  │
```

---

## Implementation Details

### 2a. Create SSE Event Types

**File:** `src/api/schemas/streaming.py` (new file)

```python
from enum import Enum
from pydantic import BaseModel
from typing import Any, Optional

class StreamEventType(str, Enum):
    ASSISTANT = "assistant"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ERROR = "error"
    COMPLETE = "complete"

class StreamEvent(BaseModel):
    type: StreamEventType
    content: Optional[str] = None
    tool_name: Optional[str] = None
    tool_input: Optional[dict] = None
    tool_output: Optional[str] = None
    slides: Optional[dict] = None
    error: Optional[str] = None
    message_id: Optional[int] = None
```

---

### 2b. Create Streaming + Persisting Callback Handler

**File:** `src/services/streaming_callback.py` (new file)

```python
import queue
from typing import Any, Dict
from langchain_core.callbacks import BaseCallbackHandler
from src.api.schemas.streaming import StreamEvent, StreamEventType
from src.api.services.session_manager import get_session_manager

class StreamingCallbackHandler(BaseCallbackHandler):
    """Callback that emits SSE events AND persists messages to database."""
    
    def __init__(self, event_queue: queue.Queue, session_id: str):
        self.event_queue = event_queue
        self.session_id = session_id
        self.session_manager = get_session_manager()
    
    def on_llm_end(self, response, **kwargs):
        if response.generations:
            text = response.generations[0][0].text
            msg = self.session_manager.add_message(
                session_id=self.session_id,
                role="assistant",
                content=text,
                message_type="llm_response",
            )
            self.event_queue.put(StreamEvent(
                type=StreamEventType.ASSISTANT,
                content=text,
                message_id=msg.get("id"),
            ))
    
    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs):
        tool_name = serialized.get("name", "unknown")
        msg = self.session_manager.add_message(
            session_id=self.session_id,
            role="assistant",
            content=f"Calling {tool_name}",
            message_type="tool_call",
            metadata={"tool_name": tool_name, "tool_input": input_str},
        )
        self.event_queue.put(StreamEvent(
            type=StreamEventType.TOOL_CALL,
            tool_name=tool_name,
            tool_input={"query": input_str},
            message_id=msg.get("id"),
        ))
    
    def on_tool_end(self, output: str, **kwargs):
        preview = output[:500] + "..." if len(output) > 500 else output
        msg = self.session_manager.add_message(
            session_id=self.session_id,
            role="tool",
            content=preview,
            message_type="tool_result",
        )
        self.event_queue.put(StreamEvent(
            type=StreamEventType.TOOL_RESULT,
            tool_output=preview,
            message_id=msg.get("id"),
        ))
    
    def on_chain_error(self, error: Exception, **kwargs):
        self.event_queue.put(StreamEvent(
            type=StreamEventType.ERROR,
            error=str(error),
        ))
```

---

### 2c. Add Streaming Method to Agent

**File:** `src/services/agent.py` - Add `generate_slides_streaming()` method

Pass callback handler to AgentExecutor for real-time event emission.

---

### 2d. Persist User Messages + Hydrate History

**File:** `src/api/services/chat_service.py`

1. `send_message_streaming()` - Persist user message before calling agent
2. `_ensure_agent_session()` - Load messages from DB into ChatHistory on session restore

```python
def _ensure_agent_session(self, session_id: str, ...):
    if session_id in self.agent.sessions:
        return
    
    # Load existing messages from database
    db_messages = session_manager.get_messages(session_id)
    
    chat_history = ChatMessageHistory()
    for msg in db_messages:
        if msg["role"] == "user":
            chat_history.add_message(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            chat_history.add_message(AIMessage(content=msg["content"]))
    
    # Register with agent including hydrated history
    self.agent.sessions[session_id] = {
        "chat_history": chat_history,
        ...
    }
```

---

### 2e. Update Session Endpoint to Return Messages

**File:** `src/api/routes/sessions.py`

```python
@router.get("/{session_id}")
async def get_session(session_id: str):
    session = await asyncio.to_thread(session_manager.get_session, session_id)
    messages = await asyncio.to_thread(session_manager.get_messages, session_id)
    slides = await asyncio.to_thread(session_manager.get_slide_deck, session_id)
    
    return {
        **session,
        "messages": messages,
        "slide_deck": slides,
    }
```

---

### 2f. Create SSE Streaming Endpoint

**File:** `src/api/routes/chat.py` - Add `POST /api/chat/stream`

SSE endpoint that yields events as agent executes, with session locking.

---

### 2g. Frontend: Disable Navigation During Generation

**File:** `frontend/src/components/Sidebar.tsx` (or navigation component)

Grey out and disable navigation buttons while generation is in progress:

```typescript
interface SidebarProps {
  isGenerating: boolean;
}

export function Sidebar({ isGenerating }: SidebarProps) {
  return (
    <nav className={isGenerating ? 'nav-disabled' : ''}>
      <button 
        disabled={isGenerating}
        className={isGenerating ? 'greyed-out' : ''}
        onClick={() => navigate('/history')}
      >
        History
      </button>
      <button 
        disabled={isGenerating}
        className={isGenerating ? 'greyed-out' : ''}
        onClick={() => navigate('/settings')}
      >
        Settings
      </button>
      {isGenerating && (
        <div className="generation-notice">
          Generation in progress...
        </div>
      )}
    </nav>
  );
}
```

**File:** `frontend/src/App.tsx` or layout component

Lift `isGenerating` state to app level so Sidebar can access it:

```typescript
function App() {
  const [isGenerating, setIsGenerating] = useState(false);
  
  return (
    <GenerationContext.Provider value={{ isGenerating, setIsGenerating }}>
      <Sidebar isGenerating={isGenerating} />
      <MainContent />
    </GenerationContext.Provider>
  );
}
```

**CSS:**
```css
.nav-disabled button {
  opacity: 0.5;
  cursor: not-allowed;
  pointer-events: none;
}

.generation-notice {
  padding: 8px;
  background: var(--warning-bg);
  color: var(--warning-text);
  font-size: 0.875rem;
}
```

---

### 2h. Frontend: Load Messages on Session Restore

**File:** `frontend/src/components/ChatPanel.tsx`

```typescript
useEffect(() => {
  if (sessionId) {
    getSession(sessionId).then(data => {
      setMessages(data.messages || []);
      setSlideDeck(data.slide_deck);
    });
  }
}, [sessionId]);
```

---

### 2i. Frontend: Use Streaming API

**File:** `frontend/src/services/api.ts` - Add `streamChat()`

**File:** `frontend/src/components/ChatPanel.tsx` - Use streaming, set `isGenerating` state

```typescript
const handleSendMessage = async () => {
  setIsGenerating(true);  // Disable navigation
  
  const cancel = streamChat(
    sessionId,
    message,
    (event) => {
      // Handle events...
      if (event.type === 'complete' || event.type === 'error') {
        setIsGenerating(false);  // Re-enable navigation
      }
    },
    (error) => {
      setIsGenerating(false);  // Re-enable on error
      setError(error.message);
    }
  );
};
```

---

## Files Summary

| File | Change |
|------|--------|
| `src/api/schemas/streaming.py` | New - Event types |
| `src/services/streaming_callback.py` | New - Callback that emits + persists |
| `src/services/agent.py` | Add `generate_slides_streaming()` |
| `src/api/routes/chat.py` | Add `POST /api/chat/stream` |
| `src/api/services/chat_service.py` | Streaming method, hydrate history |
| `src/api/routes/sessions.py` | Return messages in session response |
| `frontend/src/services/api.ts` | Add `streamChat()` |
| `frontend/src/components/Sidebar.tsx` | Disable nav during generation |
| `frontend/src/App.tsx` | Add GenerationContext for isGenerating state |
| `frontend/src/components/ChatPanel.tsx` | Use streaming, manage isGenerating |

---

## Testing

1. **Navigation lock:** Start generation, verify nav buttons are greyed/disabled
2. **Streaming:** Send message, verify events appear in real-time
3. **Persistence:** Send message, reload page, verify messages persist
4. **Session restore:** Click session in History, verify messages + slides load
5. **Continue conversation:** After restore, send new message, verify agent has context


### To-dos

- [ ] Create streaming.py with StreamEvent and StreamEventType
- [ ] Create streaming_callback.py - emits events AND persists to DB
- [ ] Add generate_slides_streaming() to SlideGeneratorAgent
- [ ] Add send_message_streaming() - persists user message first
- [ ] Update _ensure_agent_session to load messages from DB into ChatHistory
- [ ] Update GET /sessions/{id} to return messages array
- [ ] Add POST /api/chat/stream SSE endpoint
- [ ] Grey out and disable navigation buttons while isGenerating=true
- [ ] Add GenerationContext to App.tsx for isGenerating state
- [ ] Update ChatPanel to load messages on session restore
- [ ] Update ChatPanel to use streamChat() and manage isGenerating
- [ ] Test: nav lock, streaming, persistence, restore, continue conversation