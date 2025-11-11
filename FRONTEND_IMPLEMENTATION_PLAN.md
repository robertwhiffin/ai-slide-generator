# Frontend Implementation Plan: AI Slide Generator Web App

## Executive Summary

This document outlines the implementation plan for a web-based interface for the AI Slide Generator. The application will feature a chatbot interface for conversing with the LLM and a slide editor for reviewing, editing, and reordering generated slides.

**Tech Stack:**
- **Backend:** FastAPI (Python)
- **Frontend:** React with TypeScript
- **State Management:** React Context API + local storage (no backend database)
- **Deployment Target:** Databricks Apps
- **Styling:** Tailwind CSS (already used in generated slides)

---

## 1. Architecture Overview

### 1.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Browser (React App)                      │
│  ┌──────────────────┐  ┌──────────────────────────────────┐│
│  │  Chatbot Panel   │  │   Slide Editor Panel              ││
│  │  (Left 30%)      │  │   (Right 70%)                     ││
│  │                  │  │                                    ││
│  │  - Messages      │  │  - Slide Tiles (drag-drop)        ││
│  │  - Input Box     │  │  - HTML Editor Modal              ││
│  │  - Send Button   │  │  - Slide Preview                  ││
│  └──────────────────┘  └──────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
                            │
                            │ HTTP/REST API
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Backend                           │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  API Endpoints                                         │ │
│  │  - POST /api/sessions                                  │ │
│  │  - GET  /api/sessions/{session_id}                     │ │
│  │  - POST /api/sessions/{session_id}/messages            │ │
│  │  - GET  /api/sessions/{session_id}/slides              │ │
│  │  - PUT  /api/sessions/{session_id}/slides              │ │
│  │  - GET  /api/user (headers extraction)                 │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Session Manager (In-Memory)                           │ │
│  │  - Dict[session_id, SessionState]                      │ │
│  │  - SessionState: {                                     │ │
│  │      agent_session_id: str                             │ │
│  │      slide_deck: SlideDeck                             │ │
│  │      user_id: str                                      │ │
│  │      created_at: datetime                              │ │
│  │  }                                                      │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Existing Components                                   │ │
│  │  - SlideGeneratorAgent (agent.py)                      │ │
│  │  - SlideDeck / Slide (slide_deck.py, slide.py)        │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 State Management Strategy

**Backend State (In-Memory):**
- Session ID → Session data mapping
- Each session contains:
  - Agent session ID (for LangChain agent)
  - Parsed SlideDeck object
  - User information (from headers)
  - Timestamps

**Frontend State (React Context):**
- Current session ID
- Chat messages (synced with backend)
- Slide deck structure (synced with backend)
- UI state (selected slide, edit mode, etc.)

**Local Storage (Browser):**
- Session ID (for page refresh persistence)
- User preferences (optional)

---

## 2. Backend Implementation Plan

### 2.1 Project Structure

```
src/
├── api/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app initialization
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── sessions.py            # Session management endpoints
│   │   ├── messages.py            # Chat message endpoints
│   │   ├── slides.py              # Slide manipulation endpoints
│   │   └── user.py                # User info extraction
│   ├── models/
│   │   ├── __init__.py
│   │   ├── requests.py            # Pydantic request models
│   │   └── responses.py           # Pydantic response models
│   ├── middleware/
│   │   ├── __init__.py
│   │   ├── auth.py                # Header extraction middleware
│   │   └── logging.py             # Logging middleware (stdout/stderr)
│   └── services/
│       ├── __init__.py
│       └── session_manager.py     # In-memory session management
├── services/
│   └── agent.py                   # Existing agent (no changes needed)
├── models/
│   ├── slide_deck.py              # Existing (no changes needed)
│   └── slide.py                   # Existing (no changes needed)
└── config/
    └── settings.py                # Existing settings
```

### 2.2 API Endpoints Design

#### 2.2.1 Session Management

**POST /api/sessions**
- **Purpose:** Create a new conversation session
- **Request:** 
  ```json
  {}  // Empty or optional initial parameters
  ```
- **Response:**
  ```json
  {
    "session_id": "uuid-string",
    "agent_session_id": "uuid-string",
    "user": {
      "user_id": "user@example.com",
      "username": "user",
      "email": "user@example.com"
    },
    "created_at": "2024-11-11T10:00:00Z"
  }
  ```
- **Implementation Notes:**
  - Extract user info from X-Forwarded-* headers
  - Create agent session via `agent.create_session()`
  - Initialize empty SlideDeck
  - Store in in-memory dict

**GET /api/sessions/{session_id}**
- **Purpose:** Retrieve session metadata
- **Response:**
  ```json
  {
    "session_id": "uuid-string",
    "agent_session_id": "uuid-string",
    "user": {...},
    "created_at": "2024-11-11T10:00:00Z",
    "last_activity": "2024-11-11T10:15:00Z",
    "slide_count": 5,
    "message_count": 3
  }
  ```

**DELETE /api/sessions/{session_id}**
- **Purpose:** Clean up session
- **Response:** `204 No Content`

#### 2.2.2 Chat Messages

**POST /api/sessions/{session_id}/messages**
- **Purpose:** Send user message and get agent response
- **Request:**
  ```json
  {
    "content": "Create slides about Q3 sales performance",
    "max_slides": 10
  }
  ```
- **Response:**
  ```json
  {
    "messages": [
      {
        "role": "user",
        "content": "Create slides...",
        "timestamp": "2024-11-11T10:00:00Z"
      },
      {
        "role": "assistant",
        "content": "Using tool: query_genie_space",
        "tool_call": {...},
        "timestamp": "2024-11-11T10:00:01Z"
      },
      {
        "role": "tool",
        "content": "Data retrieved...",
        "tool_call_id": "query_genie_space",
        "timestamp": "2024-11-11T10:00:05Z"
      },
      {
        "role": "assistant",
        "content": "<!DOCTYPE html>...",
        "timestamp": "2024-11-11T10:00:15Z"
      }
    ],
    "slide_deck": {
      "title": "Q3 Sales Performance",
      "slide_count": 5,
      "slides": [...]
    },
    "metadata": {
      "latency_seconds": 15.2,
      "tool_calls": 1
    }
  }
  ```
- **Implementation Notes:**
  - Call `agent.generate_slides(content, session_id, max_slides)`
  - Parse HTML response into SlideDeck using `SlideDeck.from_html_string()`
  - Store SlideDeck in session
  - Return messages + parsed slide structure

**GET /api/sessions/{session_id}/messages**
- **Purpose:** Retrieve chat history
- **Response:**
  ```json
  {
    "messages": [...]
  }
  ```

#### 2.2.3 Slide Manipulation

**GET /api/sessions/{session_id}/slides**
- **Purpose:** Get current slide deck structure
- **Response:**
  ```json
  {
    "title": "Presentation Title",
    "slide_count": 5,
    "css": "/* full CSS */",
    "external_scripts": ["https://cdn.tailwindcss.com"],
    "scripts": "/* JavaScript */",
    "slides": [
      {
        "index": 0,
        "slide_id": "slide_0",
        "html": "<div class='slide'>..."
      },
      ...
    ]
  }
  ```
- **Implementation Notes:**
  - Return `session.slide_deck.to_dict()`

**PUT /api/sessions/{session_id}/slides**
- **Purpose:** Update entire slide deck (after reordering)
- **Request:**
  ```json
  {
    "slides": [
      {"index": 0, "html": "..."},
      {"index": 1, "html": "..."}
    ]
  }
  ```
- **Response:** Same as GET /slides
- **Implementation Notes:**
  - Reconstruct SlideDeck from provided slide order
  - Validate all slides are present
  - Update session.slide_deck

**PATCH /api/sessions/{session_id}/slides/{slide_index}**
- **Purpose:** Update a single slide's HTML
- **Request:**
  ```json
  {
    "html": "<div class='slide'>...</div>"
  }
  ```
- **Response:** Updated slide object
- **Implementation Notes:**
  - Parse HTML to create new Slide object
  - Replace at index: `deck.slides[index] = new_slide`
  - Return updated slide

**POST /api/sessions/{session_id}/slides/{slide_index}/duplicate**
- **Purpose:** Clone a slide
- **Response:** New slide object with new index
- **Implementation Notes:**
  - Use `slide.clone()`
  - Insert after original: `deck.insert_slide(cloned, index + 1)`

**DELETE /api/sessions/{session_id}/slides/{slide_index}**
- **Purpose:** Remove a slide
- **Response:** `204 No Content`

**GET /api/sessions/{session_id}/slides/{slide_index}/render**
- **Purpose:** Get complete standalone HTML for a single slide
- **Response:** HTML string (Content-Type: text/html)
- **Implementation Notes:**
  - Use `deck.render_slide(index)`
  - For preview/download purposes

**POST /api/sessions/{session_id}/slides/export**
- **Purpose:** Export complete slide deck as HTML
- **Response:** HTML file download
- **Implementation Notes:**
  - Use `deck.knit()`
  - Return as downloadable file

#### 2.2.4 User Information

**GET /api/user**
- **Purpose:** Get current user information from headers
- **Response:**
  ```json
  {
    "user_id": "user@example.com",
    "username": "user",
    "email": "user@example.com",
    "ip_address": "192.168.1.1"
  }
  ```
- **Implementation Notes:**
  - Extract from X-Forwarded-* headers
  - For local dev, provide mock values or read from env

### 2.3 Middleware Implementation

#### 2.3.1 User Authentication Middleware

**File:** `src/api/middleware/auth.py`

**Purpose:**
- Extract user information from Databricks Apps headers
- Simulate headers in local development
- Attach user info to request state

**Headers to Extract:**
- `X-Forwarded-User` → user_id
- `X-Forwarded-Email` → email
- `X-Forwarded-Preferred-Username` → username
- `X-Real-Ip` → ip_address
- `X-Request-Id` → request_id (for logging correlation)

**Local Development Simulation:**
- Check if headers are present
- If not (local dev), read from environment variables:
  - `DEV_USER_ID`
  - `DEV_USER_EMAIL`
  - `DEV_USERNAME`
- Or use default: `dev_user@local.dev`

**Implementation Pattern:**
```python
# Pseudo-code
async def user_middleware(request: Request, call_next):
    # Extract from headers (Databricks Apps)
    user_id = request.headers.get("x-forwarded-user")
    
    # Fallback for local dev
    if not user_id:
        user_id = os.getenv("DEV_USER_ID", "dev_user@local.dev")
    
    # Attach to request state
    request.state.user = {
        "user_id": user_id,
        "email": email,
        "username": username,
        "ip_address": ip_address
    }
    
    response = await call_next(request)
    return response
```

#### 2.3.2 Logging Middleware

**File:** `src/api/middleware/logging.py`

**Purpose:**
- Log all requests/responses to stdout
- Use structured logging (JSON format)
- Include correlation IDs (X-Request-Id)
- Log errors to stderr

**Log Format:**
```json
{
  "timestamp": "2024-11-11T10:00:00Z",
  "level": "INFO",
  "request_id": "uuid",
  "user_id": "user@example.com",
  "method": "POST",
  "path": "/api/sessions/123/messages",
  "status_code": 200,
  "latency_ms": 150,
  "message": "Request completed"
}
```

**Configuration:**
- Use Python's `logging` module
- Handler: `logging.StreamHandler(sys.stdout)` for INFO/DEBUG
- Handler: `logging.StreamHandler(sys.stderr)` for WARNING/ERROR/CRITICAL
- Formatter: JSON structured logging

### 2.4 Session Manager Service

**File:** `src/api/services/session_manager.py`

**Purpose:**
- Manage in-memory session state
- Thread-safe operations (use locks)
- Session timeout and cleanup

**Session State Structure:**
```python
@dataclass
class WebSessionState:
    session_id: str
    agent_session_id: str  # For SlideGeneratorAgent
    slide_deck: Optional[SlideDeck]
    user_info: dict
    created_at: datetime
    last_activity: datetime
```

**Methods:**
- `create_session(user_info: dict) -> WebSessionState`
- `get_session(session_id: str) -> WebSessionState`
- `update_session(session_id: str, slide_deck: SlideDeck) -> None`
- `delete_session(session_id: str) -> None`
- `list_user_sessions(user_id: str) -> List[WebSessionState]`
- `cleanup_expired_sessions(timeout_minutes: int) -> int`

**Thread Safety:**
- Use `threading.Lock()` for session dict mutations
- Or use `asyncio.Lock()` if fully async

**Session Cleanup:**
- Optional background task to clean up expired sessions
- Configurable timeout (e.g., 1 hour of inactivity)

### 2.5 CORS Configuration

**Purpose:**
- Allow React frontend (different port in dev) to call API
- Restrict origins in production

**Configuration:**
```python
# Development: Allow localhost:3000 (React dev server)
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

# Production: Allow Databricks Apps domain
if settings.environment == "production":
    origins = [settings.app_domain]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 2.6 Error Handling

**Standard Error Response:**
```json
{
  "error": {
    "type": "ValidationError",
    "message": "Invalid session ID",
    "details": {...}
  }
}
```

**HTTP Status Codes:**
- 200: Success
- 201: Created (new session)
- 204: No Content (delete)
- 400: Bad Request (validation error)
- 404: Not Found (session/slide not found)
- 500: Internal Server Error (agent failure, etc.)

**Error Logging:**
- All errors logged to stderr with stack traces
- Include request_id for correlation

---

## 3. Frontend Implementation Plan

### 3.1 Project Structure

```
frontend/
├── public/
│   └── index.html
├── src/
│   ├── App.tsx                    # Main app component
│   ├── index.tsx                  # Entry point
│   ├── components/
│   │   ├── ChatPanel/
│   │   │   ├── ChatPanel.tsx      # Main chat container
│   │   │   ├── MessageList.tsx    # Scrollable message list
│   │   │   ├── Message.tsx        # Individual message component
│   │   │   ├── ToolCallMessage.tsx # Tool call display
│   │   │   └── ChatInput.tsx      # Input box + send button
│   │   ├── SlidePanel/
│   │   │   ├── SlidePanel.tsx     # Main slide editor container
│   │   │   ├── SlideTile.tsx      # Individual slide tile
│   │   │   ├── SlidePreview.tsx   # Rendered slide view
│   │   │   ├── HTMLEditor.tsx     # Code editor modal
│   │   │   └── SlideToolbar.tsx   # Actions (duplicate, delete, export)
│   │   ├── Layout/
│   │   │   ├── AppLayout.tsx      # Two-panel layout
│   │   │   └── Header.tsx         # App header with user info
│   │   └── Common/
│   │       ├── Button.tsx
│   │       ├── Modal.tsx
│   │       ├── Loading.tsx
│   │       └── ErrorBoundary.tsx
│   ├── contexts/
│   │   ├── SessionContext.tsx     # Session state management
│   │   ├── ChatContext.tsx        # Chat messages state
│   │   └── SlideContext.tsx       # Slide deck state
│   ├── hooks/
│   │   ├── useSession.ts          # Session management hook
│   │   ├── useChat.ts             # Chat operations hook
│   │   ├── useSlides.ts           # Slide manipulation hook
│   │   └── useUser.ts             # User info hook
│   ├── services/
│   │   └── api.ts                 # API client (fetch wrapper)
│   ├── types/
│   │   ├── session.ts             # Session type definitions
│   │   ├── message.ts             # Message type definitions
│   │   └── slide.ts               # Slide type definitions
│   └── utils/
│       ├── localStorage.ts        # Local storage helpers
│       └── constants.ts           # App constants
├── package.json
├── tsconfig.json
├── tailwind.config.js
└── vite.config.ts                 # Using Vite for fast dev
```

### 3.2 Component Design

#### 3.2.1 App Layout

**App.tsx**
- Two-panel layout: 30% chat, 70% slides
- Responsive: Stack vertically on mobile
- Header with user info and session status

**Layout:**
```
┌─────────────────────────────────────────────────────────┐
│  Header: AI Slide Generator | User: john@example.com   │
├──────────────────┬──────────────────────────────────────┤
│                  │                                       │
│   ChatPanel      │         SlidePanel                    │
│   (30% width)    │         (70% width)                   │
│                  │                                       │
│   ┌────────────┐ │  ┌──────────────────────────────┐   │
│   │ Messages   │ │  │  Slide Tile 1  [Edit] [Del]  │   │
│   │            │ │  │  [Rendered Preview]           │   │
│   │            │ │  └──────────────────────────────┘   │
│   │            │ │                                       │
│   │            │ │  ┌──────────────────────────────┐   │
│   │            │ │  │  Slide Tile 2  [Edit] [Del]  │   │
│   │            │ │  │  [Rendered Preview]           │   │
│   └────────────┘ │  └──────────────────────────────┘   │
│   ┌────────────┐ │                                       │
│   │ Input Box  │ │  ┌──────────────────────────────┐   │
│   │ [Send]     │ │  │  Slide Tile 3  [Edit] [Del]  │   │
│   └────────────┘ │  │  [Rendered Preview]           │   │
│                  │  └──────────────────────────────┘   │
└──────────────────┴──────────────────────────────────────┘
```

#### 3.2.2 Chat Panel Components

**ChatPanel.tsx**
- Container for entire chat interface
- Manages scroll behavior (auto-scroll to bottom)
- Shows loading indicator when waiting for response

**MessageList.tsx**
- Scrollable list of messages
- Virtual scrolling for performance (optional, if many messages)
- Group messages by role

**Message.tsx**
- Display individual message based on role:
  - **User message:** Right-aligned, blue background
  - **Assistant message:** Left-aligned, gray background
  - **Tool message:** Collapsed by default, expandable
- Timestamp display
- Markdown rendering for assistant messages (optional)

**ToolCallMessage.tsx**
- Special formatting for tool calls
- Collapsible section showing:
  - Tool name
  - Arguments (formatted JSON)
  - Response/observation
- Visual indicator (icon) for tool type

**ChatInput.tsx**
- Textarea for user input (auto-expand)
- Send button
- Character count (optional)
- Disabled while waiting for response
- "Max slides" input (number, default 10)

#### 3.2.3 Slide Panel Components

**SlidePanel.tsx**
- Container for slide tiles
- Drag-and-drop context provider
- Toolbar with actions:
  - Export HTML button
  - New slide button (manual HTML entry)
  - Settings (optional)

**SlideTile.tsx**
- Individual slide container
- Two modes: Preview and Edit
- Drag handle for reordering
- Actions toolbar:
  - Edit (switch to HTML editor)
  - Duplicate
  - Delete
  - Move up/down (alternative to drag-drop)
- Slide number indicator

**SlidePreview.tsx**
- Renders slide HTML in an iframe for isolation
- Injects deck CSS and scripts
- Scaled to fit tile (maintain aspect ratio)
- Click to expand (optional fullscreen mode)

**HTMLEditor.tsx**
- Modal with code editor
- Syntax highlighting (Monaco Editor or CodeMirror)
- Save/Cancel buttons
- Preview pane showing live changes
- Validation before save

**SlideToolbar.tsx**
- Actions that affect multiple slides:
  - Select all
  - Delete selected
  - Bulk operations
- Export options:
  - Download HTML
  - Copy to clipboard
  - Print preview

#### 3.2.4 Common Components

**Button.tsx**
- Reusable button with variants:
  - Primary (blue)
  - Secondary (gray)
  - Danger (red)
  - Ghost (transparent)
- Size variants (sm, md, lg)
- Loading state (spinner)
- Disabled state

**Modal.tsx**
- Reusable modal overlay
- Close on backdrop click
- Keyboard support (ESC to close)
- Accessibility (focus trap)

**Loading.tsx**
- Spinner component
- Various sizes
- Optional text

**ErrorBoundary.tsx**
- Catch React errors
- Display error message
- Reload button
- Log errors to console

### 3.3 State Management

#### 3.3.1 Context Providers

**SessionContext**
- Manages current session
- Provides:
  - `sessionId: string | null`
  - `userId: string | null`
  - `createSession: () => Promise<void>`
  - `loadSession: (id: string) => Promise<void>`
  - `clearSession: () => Promise<void>`

**ChatContext**
- Manages chat messages
- Provides:
  - `messages: Message[]`
  - `sendMessage: (content: string, maxSlides: number) => Promise<void>`
  - `isLoading: boolean`
  - `error: string | null`

**SlideContext**
- Manages slide deck
- Provides:
  - `slideDeck: SlideDeck | null`
  - `updateSlide: (index: number, html: string) => Promise<void>`
  - `reorderSlides: (newOrder: number[]) => Promise<void>`
  - `deleteSlide: (index: number) => Promise<void>`
  - `duplicateSlide: (index: number) => Promise<void>`
  - `exportHTML: () => string`

#### 3.3.2 Custom Hooks

**useSession.ts**
- Wraps SessionContext
- Handles session persistence to localStorage
- Auto-restore session on page load

**useChat.ts**
- Wraps ChatContext
- Handles message sending
- Manages loading states
- Error handling

**useSlides.ts**
- Wraps SlideContext
- Provides slide manipulation functions
- Optimistic updates for better UX
- Sync with backend

**useUser.ts**
- Fetches user info from /api/user
- Caches in React state
- Used in header display

### 3.4 API Client

**services/api.ts**

**Purpose:**
- Centralized API calls
- Error handling
- Request/response transformation
- Automatic session ID injection

**Functions:**
```typescript
// Sessions
createSession(): Promise<Session>
getSession(sessionId: string): Promise<Session>
deleteSession(sessionId: string): Promise<void>

// Messages
sendMessage(sessionId: string, content: string, maxSlides: number): Promise<MessageResponse>
getMessages(sessionId: string): Promise<Message[]>

// Slides
getSlides(sessionId: string): Promise<SlideDeck>
updateSlides(sessionId: string, slides: Slide[]): Promise<SlideDeck>
updateSlide(sessionId: string, index: number, html: string): Promise<Slide>
deleteSlide(sessionId: string, index: number): Promise<void>
duplicateSlide(sessionId: string, index: number): Promise<Slide>
exportHTML(sessionId: string): Promise<string>

// User
getUser(): Promise<User>
```

**Error Handling:**
- Wrap fetch calls in try-catch
- Parse error responses
- Throw custom errors with context
- Log errors to console

**Configuration:**
```typescript
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
```

### 3.5 Type Definitions

**types/session.ts**
```typescript
interface Session {
  session_id: string;
  agent_session_id: string;
  user: User;
  created_at: string;
  last_activity: string;
  slide_count: number;
  message_count: number;
}

interface User {
  user_id: string;
  username: string;
  email: string;
  ip_address?: string;
}
```

**types/message.ts**
```typescript
type MessageRole = 'user' | 'assistant' | 'tool';

interface Message {
  role: MessageRole;
  content: string;
  timestamp: string;
  tool_call?: ToolCall;
  tool_call_id?: string;
}

interface ToolCall {
  name: string;
  arguments: Record<string, any>;
}

interface MessageResponse {
  messages: Message[];
  slide_deck: SlideDeck;
  metadata: {
    latency_seconds: number;
    tool_calls: number;
  };
}
```

**types/slide.ts**
```typescript
interface SlideDeck {
  title: string;
  slide_count: number;
  css: string;
  external_scripts: string[];
  scripts: string;
  slides: Slide[];
}

interface Slide {
  index: number;
  slide_id: string;
  html: string;
}
```

### 3.6 Drag-and-Drop Implementation

**Library:** `@dnd-kit/core` and `@dnd-kit/sortable`

**Rationale:**
- Modern, performant, accessible
- TypeScript support
- Works with virtual scrolling
- Touch support for mobile

**Implementation:**
1. Wrap SlidePanel in `<DndContext>`
2. Wrap slide list in `<SortableContext>`
3. Each SlideTile is a `<SortableItem>`
4. Handle `onDragEnd` event:
   - Calculate new order
   - Update local state optimistically
   - Call API to persist: `PUT /api/sessions/{id}/slides`
   - Revert on error

**Visual Feedback:**
- Drag overlay showing dragged slide
- Placeholder showing drop position
- Smooth animations

### 3.7 HTML Editing

**Code Editor:** Monaco Editor (same as VS Code)

**Implementation:**
- Modal opens with current slide HTML
- Monaco editor with HTML syntax highlighting
- Live preview pane (optional)
- Validation on save:
  - Check for `<div class="slide">` wrapper
  - Validate HTML structure
  - Show errors if invalid
- On save:
  - Call API: `PATCH /api/sessions/{id}/slides/{index}`
  - Update local state
  - Close modal

**Alternative:** Simple textarea if Monaco is too heavy

### 3.8 Slide Rendering

**Strategy:** iframe isolation

**Rationale:**
- Slide HTML may contain arbitrary styles/scripts
- Prevent style conflicts with app UI
- Security isolation

**Implementation:**
- Each SlideTile contains an iframe
- Inject complete HTML with CSS and scripts
- Use `srcdoc` attribute for inline content
- Scale iframe content to fit tile using CSS transform

**Code:**
```typescript
const slideHTML = `
<!DOCTYPE html>
<html>
<head>
  <style>${slideDeck.css}</style>
  ${slideDeck.external_scripts.map(src => 
    `<script src="${src}"></script>`
  ).join('\n')}
</head>
<body>
  ${slide.html}
  <script>${slideDeck.scripts}</script>
</body>
</html>
`;

<iframe 
  srcDoc={slideHTML}
  style={{ transform: 'scale(0.25)', width: '400%', height: '400%' }}
/>
```

---

## 4. Development Workflow

### 4.1 Local Development Setup

**Backend:**
1. Create virtual environment
2. Install dependencies: `pip install -r requirements.txt`
3. Add FastAPI dependencies: `fastapi`, `uvicorn[standard]`, `python-multipart`
4. Set environment variables:
   ```bash
   export DEV_USER_ID="dev@local.dev"
   export DEV_USER_EMAIL="dev@local.dev"
   export DEV_USERNAME="Dev User"
   ```
5. Run: `uvicorn src.api.main:app --reload --port 8000`

**Frontend:**
1. Initialize React project: `npm create vite@latest frontend -- --template react-ts`
2. Install dependencies:
   ```bash
   npm install
   npm install -D tailwindcss postcss autoprefixer
   npm install @dnd-kit/core @dnd-kit/sortable
   npm install @monaco-editor/react  # or react-codemirror
   npm install react-icons
   ```
3. Configure Tailwind CSS
4. Set API URL in `.env.local`:
   ```
   VITE_API_URL=http://localhost:8000
   ```
5. Run: `npm run dev` (usually port 3000)

**Full Stack:**
- Backend on http://localhost:8000
- Frontend on http://localhost:3000
- Frontend proxies API calls to backend (CORS configured)

### 4.2 Testing Strategy

**Backend:**
- Unit tests for API endpoints (pytest + FastAPI TestClient)
- Test session management logic
- Mock SlideGeneratorAgent for faster tests
- Test header extraction middleware

**Frontend:**
- Component tests (React Testing Library)
- Integration tests for user flows
- Mock API responses (MSW - Mock Service Worker)
- E2E tests (Playwright) for critical paths

**Integration:**
- Full stack tests with real backend
- Test WebSocket fallback (if adding streaming)

### 4.3 Development Phases

**Phase 1: Backend Foundation (Week 1)**
- FastAPI app structure
- Session management endpoints
- User header middleware
- Logging configuration
- Basic session CRUD operations
- Integration with existing agent.py

**Phase 2: Chat API (Week 1-2)**
- Message endpoints
- Agent invocation
- HTML parsing into SlideDeck
- Error handling
- Testing with existing demo scripts

**Phase 3: Slide API (Week 2)**
- Slide CRUD endpoints
- Reordering logic
- HTML export
- Individual slide operations

**Phase 4: Frontend Foundation (Week 2-3)**
- React project setup
- Layout components
- Context providers
- API client
- Routing (if needed)

**Phase 5: Chat UI (Week 3)**
- Message display components
- Input component
- Tool call visualization
- Loading states
- Error handling

**Phase 6: Slide UI (Week 3-4)**
- Slide tiles
- Iframe rendering
- Drag-and-drop
- Basic toolbar

**Phase 7: HTML Editor (Week 4)**
- Monaco integration
- Edit modal
- Save/cancel logic
- Validation

**Phase 8: Polish & Testing (Week 4-5)**
- Error boundaries
- Loading states
- Responsive design
- Accessibility
- E2E tests
- Performance optimization

**Phase 9: Databricks Apps Deployment (Week 5)**
- Deployment configuration
- Header handling validation
- Logging verification
- Production testing

---

## 5. Databricks Apps Deployment

### 5.1 Deployment Architecture

**Structure:**
```
app/
├── backend/                # FastAPI app
│   └── (existing src/)
├── frontend/               # React built files
│   └── dist/               # npm run build output
├── app.yaml               # Databricks Apps config
└── requirements.txt       # Python dependencies
```

**Serving Strategy:**
- FastAPI serves both API and static frontend
- API routes: `/api/*`
- Static files: All other routes serve React app
- React handles routing (history API)

**main.py:**
```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

app = FastAPI()

# Mount API routes
app.include_router(sessions_router, prefix="/api")
app.include_router(messages_router, prefix="/api")
app.include_router(slides_router, prefix="/api")
app.include_router(user_router, prefix="/api")

# Mount static files (React build)
app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="static")
```

### 5.2 app.yaml Configuration

```yaml
name: ai-slide-generator
display_name: "AI Slide Generator"
description: "Generate and edit slide decks using AI"

command: ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8080"]

env:
  - name: ENVIRONMENT
    value: production
  - name: LOG_LEVEL
    value: INFO
  - name: MLFLOW_TRACKING_URI
    value: databricks

# Resources
compute:
  size: SMALL  # Adjust based on load

# Permissions
permissions:
  - level: CAN_USE
    group_name: users
```

### 5.3 Header Handling

**Production:**
- Headers automatically provided by Databricks Apps:
  - `X-Forwarded-User`
  - `X-Forwarded-Email`
  - `X-Forwarded-Preferred-Username`
  - `X-Real-Ip`
  - `X-Request-Id`

**Middleware Logic:**
```python
# Check for Databricks headers first
user_id = request.headers.get("x-forwarded-user")

# Fallback for local dev
if not user_id and settings.environment == "development":
    user_id = os.getenv("DEV_USER_ID", "dev@local.dev")

# Error if neither (shouldn't happen in production)
if not user_id:
    raise HTTPException(401, "User authentication failed")
```

**Testing Header Handling:**
- Use curl with custom headers:
  ```bash
  curl -H "X-Forwarded-User: test@example.com" \
       -H "X-Forwarded-Email: test@example.com" \
       http://localhost:8000/api/user
  ```

### 5.4 Logging Configuration

**Requirements:**
- All logs must go to stdout/stderr
- Structured JSON format for parsing
- Include correlation IDs

**Python Logging Setup:**
```python
import logging
import sys
import json

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_obj = {
            'timestamp': self.formatTime(record),
            'level': record.levelname,
            'message': record.getMessage(),
            'logger': record.name,
        }
        if hasattr(record, 'request_id'):
            log_obj['request_id'] = record.request_id
        if hasattr(record, 'user_id'):
            log_obj['user_id'] = record.user_id
        return json.dumps(log_obj)

# Configure handlers
stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setLevel(logging.INFO)
stdout_handler.addFilter(lambda record: record.levelno < logging.WARNING)

stderr_handler = logging.StreamHandler(sys.stderr)
stderr_handler.setLevel(logging.WARNING)

# Apply formatter
formatter = JSONFormatter()
stdout_handler.setFormatter(formatter)
stderr_handler.setFormatter(formatter)

# Root logger
logging.root.addHandler(stdout_handler)
logging.root.addHandler(stderr_handler)
logging.root.setLevel(logging.INFO)
```

**Request Logging:**
- Log every request start
- Log every request completion with latency
- Log errors with stack traces
- Include user_id and request_id in all logs

### 5.5 Build Process

**Frontend Build:**
```bash
cd frontend
npm run build
# Output: frontend/dist/
```

**Deployment Package:**
```bash
# Create deployment directory
mkdir -p deploy
cp -r src/ deploy/
cp -r config/ deploy/
cp -r frontend/dist/ deploy/frontend/dist/
cp requirements.txt deploy/
cp app.yaml deploy/
```

**Deployment:**
- Use Databricks CLI or UI to deploy
- Upload deployment package
- Databricks builds container and starts app

---

## 6. Additional Considerations

### 6.1 Performance Optimization

**Backend:**
- Session cleanup background task (prevent memory leaks)
- Connection pooling for any external services
- Response compression (gzip)
- Caching for frequently accessed data (if needed)

**Frontend:**
- Code splitting (lazy load editor, heavy components)
- Virtual scrolling for large slide decks (>50 slides)
- Image optimization (if slides contain images)
- Debounce API calls for live preview

### 6.2 Security

**Backend:**
- Validate all inputs (Pydantic models)
- Sanitize HTML (if allowing custom HTML input)
- Rate limiting (prevent abuse)
- Session hijacking prevention (validate user_id)
- CORS configuration (production only allows app domain)

**Frontend:**
- XSS prevention (iframe isolation for slide rendering)
- Content Security Policy headers
- No inline scripts in React app
- Sanitize any user-generated content

### 6.3 Accessibility

**Frontend:**
- Keyboard navigation (all interactive elements)
- ARIA labels for screen readers
- Focus management (modals, drawers)
- Color contrast (WCAG AA compliance)
- Alt text for images (if applicable)

### 6.4 Error Handling

**User-Facing Errors:**
- Clear error messages (no stack traces to users)
- Actionable guidance ("Try again" button)
- Fallback UI (ErrorBoundary)

**Developer Errors:**
- Detailed logs to stderr
- Correlation IDs for tracing
- Stack traces in logs (not UI)

### 6.5 Monitoring

**Metrics to Track:**
- Session creation rate
- Average session duration
- Slide generation latency
- Tool call success rate
- Error rates by endpoint
- User activity (messages sent, slides edited)

**Implementation:**
- Log metrics to stdout (JSON format)
- Databricks can ingest and visualize
- Set up alerts for error spikes

### 6.6 Future Enhancements

**Potential Features:**
1. **Real-time Collaboration:**
   - Multiple users editing same deck
   - WebSocket for live updates
   - Operational Transform for conflict resolution

2. **Slide Templates:**
   - Pre-built layouts
   - Drag-and-drop components
   - Style library

3. **Export Formats:**
   - PDF export
   - PowerPoint export
   - Google Slides integration

4. **Persistence:**
   - Save decks to Unity Catalog (Databricks)
   - Version history
   - Deck library/gallery

5. **Advanced Editing:**
   - Visual editor (no HTML knowledge needed)
   - Component library (charts, tables, etc.)
   - Theme customization

6. **Sharing:**
   - Share deck URL
   - Embed slides in other apps
   - Presentation mode (fullscreen, navigation)

7. **Analytics:**
   - Track which slides are viewed most
   - Time spent per slide
   - User engagement metrics

---

## 7. Timeline Estimate

**Total Estimated Time:** 4-5 weeks (1 developer)

**Week 1:**
- Backend API foundation
- Session management
- Message endpoints
- Header middleware
- Logging setup

**Week 2:**
- Slide endpoints
- Frontend project setup
- Layout components
- API client
- Context providers

**Week 3:**
- Chat UI components
- Slide tile components
- Basic drag-and-drop
- Integration testing

**Week 4:**
- HTML editor (Monaco)
- Polish and refinement
- Error handling
- Loading states
- Responsive design

**Week 5:**
- Testing (unit, integration, E2E)
- Databricks Apps deployment
- Production validation
- Documentation

---

## 8. Dependencies

### Backend (Python)
```
# Existing
databricks-langchain
langchain-classic
langchain-community
mlflow
pydantic
beautifulsoup4
lxml

# New for API
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
python-multipart>=0.0.6
```

### Frontend (Node.js)
```json
{
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "@dnd-kit/core": "^6.0.8",
    "@dnd-kit/sortable": "^7.0.2",
    "@monaco-editor/react": "^4.6.0",
    "react-icons": "^4.11.0"
  },
  "devDependencies": {
    "@types/react": "^18.2.0",
    "@types/react-dom": "^18.2.0",
    "@vitejs/plugin-react": "^4.2.0",
    "typescript": "^5.2.0",
    "vite": "^5.0.0",
    "tailwindcss": "^3.3.0",
    "autoprefixer": "^10.4.0",
    "postcss": "^8.4.0"
  }
}
```

---

## 9. Success Criteria

### Functional Requirements
- ✅ User can start a new conversation session
- ✅ User can send messages and receive AI-generated slides
- ✅ All chat messages (including tool calls) are displayed
- ✅ Generated slides appear in slide panel
- ✅ User can reorder slides via drag-and-drop
- ✅ User can edit individual slide HTML
- ✅ User can delete slides
- ✅ User can duplicate slides
- ✅ User can export complete HTML deck
- ✅ Session persists across page refreshes
- ✅ Multiple users can have independent sessions

### Non-Functional Requirements
- ✅ Response time < 20s for slide generation (depends on LLM)
- ✅ UI updates feel instant (optimistic updates)
- ✅ App works on desktop browsers (Chrome, Firefox, Safari)
- ✅ Mobile-responsive (basic support)
- ✅ All logs go to stdout/stderr (Databricks Apps compatible)
- ✅ User info extracted from headers in production
- ✅ Error messages are user-friendly
- ✅ Code is typed (TypeScript + Python type hints)
- ✅ Unit test coverage > 70% (backend critical paths)

### Deployment Requirements
- ✅ Deploys to Databricks Apps
- ✅ Single container deployment
- ✅ No external database required
- ✅ Environment variable configuration
- ✅ Supports multiple concurrent users (in-memory session limit acceptable)

---

## 10. Risk Mitigation

### Risk: In-Memory Session Loss on Restart
**Impact:** Users lose sessions when app restarts
**Mitigation:**
- Phase 1: Accept limitation, sessions are ephemeral
- Phase 2: Add Redis for session persistence (future)
- Communicate to users: "Sessions expire after 1 hour of inactivity"

### Risk: Large HTML Causing Performance Issues
**Impact:** Very large slide decks slow down UI
**Mitigation:**
- Limit max slides (configurable, default 50)
- Virtual scrolling for slide list
- Lazy render iframes (only visible slides)
- Pagination (if needed)

### Risk: Monaco Editor Bundle Size
**Impact:** Slow initial page load
**Mitigation:**
- Code splitting: Only load Monaco when editing
- Alternative: Use lightweight CodeMirror
- Fallback: Simple textarea with syntax highlighting

### Risk: Session Memory Exhaustion
**Impact:** Too many sessions cause OOM
**Mitigation:**
- Background cleanup task (every 10 minutes)
- Max sessions per user (e.g., 5)
- Session size limit (max slides per session)
- Monitor memory usage

### Risk: LLM Latency
**Impact:** Users wait too long for responses
**Mitigation:**
- Show progress indicators (loading spinner)
- Stream responses (future enhancement)
- Set reasonable timeout (60s)
- Clear error messages on timeout

---

## 11. Next Steps

1. **Review This Plan:** Stakeholder feedback, adjustments
2. **Set Up Repositories:** Backend and frontend repos (or monorepo)
3. **Environment Setup:** Dev environment for backend and frontend
4. **Phase 1 Implementation:** Start with backend API foundation
5. **Iterative Development:** Build, test, demo each phase
6. **Deployment Planning:** Databricks Apps account setup, testing environment
7. **Documentation:** API docs (OpenAPI/Swagger), user guide, deployment guide

---

## Appendix A: API Endpoint Summary

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/sessions` | Create new session |
| GET | `/api/sessions/{id}` | Get session metadata |
| DELETE | `/api/sessions/{id}` | Delete session |
| POST | `/api/sessions/{id}/messages` | Send message, get response |
| GET | `/api/sessions/{id}/messages` | Get chat history |
| GET | `/api/sessions/{id}/slides` | Get slide deck structure |
| PUT | `/api/sessions/{id}/slides` | Update slide order |
| PATCH | `/api/sessions/{id}/slides/{idx}` | Update single slide |
| DELETE | `/api/sessions/{id}/slides/{idx}` | Delete slide |
| POST | `/api/sessions/{id}/slides/{idx}/duplicate` | Duplicate slide |
| GET | `/api/sessions/{id}/slides/{idx}/render` | Render single slide HTML |
| POST | `/api/sessions/{id}/slides/export` | Export full deck HTML |
| GET | `/api/user` | Get current user info |

---

## Appendix B: Component Hierarchy

```
App
├── SessionProvider
│   ├── ChatProvider
│   │   └── SlideProvider
│   │       └── AppLayout
│   │           ├── Header
│   │           │   └── UserInfo
│   │           └── MainContent
│   │               ├── ChatPanel
│   │               │   ├── MessageList
│   │               │   │   └── Message[]
│   │               │   │       └── ToolCallMessage (conditional)
│   │               │   └── ChatInput
│   │               └── SlidePanel
│   │                   ├── SlideToolbar
│   │                   └── DndContext
│   │                       └── SortableContext
│   │                           └── SlideTile[]
│   │                               ├── SlidePreview (iframe)
│   │                               └── SlideActions
│   └── HTMLEditorModal (conditional)
│       └── MonacoEditor
```

---

## Appendix C: File Changes Summary

### New Files (Backend)
- `src/api/main.py`
- `src/api/routes/*.py` (sessions, messages, slides, user)
- `src/api/models/*.py` (requests, responses)
- `src/api/middleware/*.py` (auth, logging)
- `src/api/services/session_manager.py`

### Modified Files (Backend)
- `requirements.txt` (add fastapi, uvicorn)
- `src/config/settings.py` (add API settings)

### No Changes Needed (Backend)
- `src/services/agent.py` (use as-is)
- `src/models/slide_deck.py` (use as-is)
- `src/models/slide.py` (use as-is)

### New Files (Frontend)
- All files in `frontend/` directory (new React project)

### Deployment Files
- `app.yaml` (Databricks Apps config)

---

This plan provides a comprehensive roadmap for implementing the AI Slide Generator web application. The architecture is designed for simplicity (in-memory sessions), scalability (stateless API), and compatibility with Databricks Apps deployment requirements.

