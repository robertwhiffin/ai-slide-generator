# Phase 1: MVP - Chat Interface and Basic Slide Rendering

## Goal
Build a minimal viable product that demonstrates the core functionality: chat with the LLM agent and view generated slides. No drag-and-drop, no multi-session support yet, but designed with extensibility in mind.

## Success Criteria
- ✅ User can send a message to the agent
- ✅ Agent generates slides from the message
- ✅ Chat messages (user, assistant, tool calls) are displayed
- ✅ Generated slides are rendered as tiles
- ✅ Each slide tile shows a preview of the slide
- ✅ Application runs locally (localhost:8000 backend, localhost:3000 frontend)

## Architecture Simplifications for Phase 1
- **Single Session Only**: Hardcoded or single session ID
- **No Session Persistence**: Session exists only while app is running
- **No User Authentication**: Use placeholder user info
- **No Drag-and-Drop**: Slides displayed in fixed order
- **No HTML Editing**: View-only mode
- **Simple Error Handling**: Basic error messages

## Implementation Steps

---

### Step 1: Backend Setup (Estimated: 4-6 hours)

#### 1.1 FastAPI Project Structure

Create the following directory structure:

```
src/
├── api/
│   ├── __init__.py
│   ├── main.py              # FastAPI app initialization
│   ├── routes/
│   │   ├── __init__.py
│   │   └── chat.py          # Single endpoint for chat
│   ├── models/
│   │   ├── __init__.py
│   │   ├── requests.py      # Pydantic request models
│   │   └── responses.py     # Pydantic response models
│   └── services/
│       ├── __init__.py
│       └── chat_service.py  # Wrapper around agent
```

**Files to Create:**

**`src/api/main.py`**
- Initialize FastAPI app
- Add CORS middleware (allow localhost:3000)
- Include chat router
- Basic health check endpoint

**Key Points:**
- CORS configured for local development
- No authentication middleware yet (Phase 3)
- Simple logging (print statements OK for now)

#### 1.2 API Models

**`src/api/models/requests.py`**

Define request models:
```python
class ChatRequest(BaseModel):
    message: str
    max_slides: int = 10
    # session_id: Optional[str] = None  # Placeholder for Phase 4
```

**`src/api/models/responses.py`**

Define response models:
```python
class MessageResponse(BaseModel):
    role: str  # "user", "assistant", "tool"
    content: str
    timestamp: str
    tool_call: Optional[dict] = None
    tool_call_id: Optional[str] = None

class ChatResponse(BaseModel):
    messages: List[MessageResponse]
    slide_deck: Optional[dict] = None  # SlideDeck.to_dict()
    metadata: dict
```

#### 1.3 Chat Service

**`src/api/services/chat_service.py`**

Create a simple wrapper around the existing agent:

```python
class ChatService:
    def __init__(self):
        self.agent = create_agent()  # From existing agent.py
        # For Phase 1: Create single session on startup
        self.session_id = self.agent.create_session()
        self.slide_deck = None  # Store current slide deck
    
    def send_message(self, message: str, max_slides: int) -> dict:
        """
        Send message to agent and return response.
        
        Args:
            message: User message
            max_slides: Max slides to generate
            # session_id: Optional[str] = None  # For Phase 4
        
        Returns:
            Dict with messages, slide_deck, metadata
        """
        # Call agent.generate_slides()
        result = self.agent.generate_slides(
            question=message,
            session_id=self.session_id,
            max_slides=max_slides
        )
        
        # Parse HTML into SlideDeck
        if result["html"]:
            self.slide_deck = SlideDeck.from_html_string(result["html"])
        
        return {
            "messages": result["messages"],
            "slide_deck": self.slide_deck.to_dict() if self.slide_deck else None,
            "metadata": result["metadata"]
        }
```

**Key Design Notes:**
- Single global `ChatService` instance for Phase 1
- `session_id` parameter commented/optional for future phases
- Stores slide deck in memory (single session)
- Returns parsed slide deck structure

#### 1.4 Chat Endpoint

**`src/api/routes/chat.py`**

Create single endpoint:

```python
from fastapi import APIRouter, HTTPException
from ..models.requests import ChatRequest
from ..models.responses import ChatResponse
from ..services.chat_service import ChatService

router = APIRouter(prefix="/api", tags=["chat"])

# Global service instance (Phase 1 only)
chat_service = ChatService()

@router.post("/chat", response_model=ChatResponse)
async def send_message(request: ChatRequest):
    """
    Send a message to the AI agent and get response with generated slides.
    
    Phase 1: Single session only
    Phase 4: Add session_id to request
    """
    try:
        result = chat_service.send_message(
            message=request.message,
            max_slides=request.max_slides
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}
```

**Key Points:**
- Single `/api/chat` endpoint
- Global service instance (simplified for Phase 1)
- Basic error handling
- Health check for testing

#### 1.5 Update Dependencies

**`requirements.txt`**

Add new dependencies:
```
# Existing dependencies...

# New for Phase 1
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
python-multipart>=0.0.6
```

---

### Step 2: Backend Testing (Estimated: 1-2 hours)

#### 2.1 Manual Testing

**Start Backend:**
```bash
# Activate virtual environment
source .venv/bin/activate  # or use uv

# Run FastAPI
uvicorn src.api.main:app --reload --port 8000
```

**Test Endpoints:**

```bash
# Health check
curl http://localhost:8000/api/health

# Send message (test with existing demo question)
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Create slides about Q3 sales performance",
    "max_slides": 5
  }'
```

**Expected Response:**
- Messages array with user/assistant/tool messages
- slide_deck object with title, slides array, css, scripts
- metadata with latency, tool_calls

#### 2.2 Verify Slide Parsing

Check that:
- HTML is parsed into SlideDeck correctly
- `slide_deck.slides` array contains all slides
- Each slide has `index`, `slide_id`, `html`
- CSS and scripts are extracted

---

### Step 3: Create Helper Scripts (Estimated: 30 min)

Create scripts to simplify starting and stopping the application during development.

#### 3.1 Create Start Script

**`start_app.sh`**

```bash
#!/bin/bash

# AI Slide Generator - Start Script
# Starts both backend and frontend servers

set -e

echo "🚀 Starting AI Slide Generator..."
echo ""

# Color codes for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get project root directory
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

# Check if .venv exists
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}⚠️  Virtual environment not found. Creating one...${NC}"
    python3 -m venv .venv
    echo -e "${GREEN}✅ Virtual environment created${NC}"
fi

# Activate virtual environment
echo -e "${BLUE}🔧 Activating virtual environment...${NC}"
source .venv/bin/activate

# Check if requirements are installed
if ! python -c "import fastapi" 2>/dev/null; then
    echo -e "${YELLOW}⚠️  Dependencies not installed. Installing...${NC}"
    pip install -r requirements.txt
    echo -e "${GREEN}✅ Dependencies installed${NC}"
fi

# Set environment variables for development
export ENVIRONMENT="development"
export DEV_USER_ID="dev@local.dev"
export DEV_USER_EMAIL="dev@local.dev"
export DEV_USERNAME="Dev User"

# Check if frontend dependencies are installed
if [ ! -d "frontend/node_modules" ]; then
    echo -e "${YELLOW}⚠️  Frontend dependencies not installed. Installing...${NC}"
    cd frontend
    npm install
    cd ..
    echo -e "${GREEN}✅ Frontend dependencies installed${NC}"
fi

# Create log directory
mkdir -p logs

# Start backend in background
echo -e "${BLUE}🔧 Starting backend on port 8000...${NC}"
nohup uvicorn src.api.main:app --reload --port 8000 > logs/backend.log 2>&1 &
BACKEND_PID=$!
echo $BACKEND_PID > logs/backend.pid
echo -e "${GREEN}✅ Backend started (PID: $BACKEND_PID)${NC}"

# Wait for backend to be ready
echo -e "${BLUE}⏳ Waiting for backend to be ready...${NC}"
for i in {1..30}; do
    if curl -s http://localhost:8000/api/health > /dev/null 2>&1; then
        echo -e "${GREEN}✅ Backend is ready${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${YELLOW}⚠️  Backend health check timeout. Check logs/backend.log${NC}"
    fi
    sleep 1
done

# Start frontend in background
echo -e "${BLUE}🔧 Starting frontend on port 3000...${NC}"
cd frontend
nohup npm run dev > ../logs/frontend.log 2>&1 &
FRONTEND_PID=$!
echo $FRONTEND_PID > ../logs/frontend.pid
cd ..
echo -e "${GREEN}✅ Frontend started (PID: $FRONTEND_PID)${NC}"

echo ""
echo -e "${GREEN}✨ AI Slide Generator is running!${NC}"
echo ""
echo "📍 URLs:"
echo "   Frontend: http://localhost:3000"
echo "   Backend:  http://localhost:8000"
echo "   API Docs: http://localhost:8000/docs"
echo ""
echo "📋 Process IDs:"
echo "   Backend:  $BACKEND_PID"
echo "   Frontend: $FRONTEND_PID"
echo ""
echo "📝 Logs:"
echo "   Backend:  tail -f logs/backend.log"
echo "   Frontend: tail -f logs/frontend.log"
echo ""
echo "🛑 To stop: ./stop_app.sh"
echo ""
```

#### 3.2 Create Stop Script

**`stop_app.sh`**

```bash
#!/bin/bash

# AI Slide Generator - Stop Script
# Stops both backend and frontend servers gracefully

set -e

echo "🛑 Stopping AI Slide Generator..."
echo ""

# Color codes for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get project root directory
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

# Function to stop a process
stop_process() {
    local name=$1
    local pid_file=$2
    
    if [ -f "$pid_file" ]; then
        PID=$(cat "$pid_file")
        if ps -p $PID > /dev/null 2>&1; then
            echo -e "${YELLOW}⏳ Stopping $name (PID: $PID)...${NC}"
            kill $PID
            
            # Wait for process to stop (max 10 seconds)
            for i in {1..10}; do
                if ! ps -p $PID > /dev/null 2>&1; then
                    echo -e "${GREEN}✅ $name stopped${NC}"
                    rm "$pid_file"
                    return 0
                fi
                sleep 1
            done
            
            # Force kill if still running
            if ps -p $PID > /dev/null 2>&1; then
                echo -e "${RED}⚠️  Force killing $name...${NC}"
                kill -9 $PID
                rm "$pid_file"
            fi
        else
            echo -e "${YELLOW}⚠️  $name not running (stale PID file)${NC}"
            rm "$pid_file"
        fi
    else
        echo -e "${YELLOW}⚠️  $name PID file not found${NC}"
    fi
}

# Stop backend
stop_process "Backend" "logs/backend.pid"

# Stop frontend
stop_process "Frontend" "logs/frontend.pid"

# Also kill any remaining processes on ports 8000 and 3000
echo ""
echo -e "${YELLOW}🔍 Checking for any remaining processes...${NC}"

# Kill any process on port 8000 (backend)
BACKEND_PORT_PID=$(lsof -ti:8000 2>/dev/null || true)
if [ ! -z "$BACKEND_PORT_PID" ]; then
    echo -e "${YELLOW}⚠️  Found process on port 8000 (PID: $BACKEND_PORT_PID), killing...${NC}"
    kill $BACKEND_PORT_PID 2>/dev/null || true
fi

# Kill any process on port 3000 (frontend)
FRONTEND_PORT_PID=$(lsof -ti:3000 2>/dev/null || true)
if [ ! -z "$FRONTEND_PORT_PID" ]; then
    echo -e "${YELLOW}⚠️  Found process on port 3000 (PID: $FRONTEND_PORT_PID), killing...${NC}"
    kill $FRONTEND_PORT_PID 2>/dev/null || true
fi

echo ""
echo -e "${GREEN}✨ AI Slide Generator stopped${NC}"
echo ""
```

#### 3.3 Make Scripts Executable

```bash
chmod +x start_app.sh
chmod +x stop_app.sh
```

#### 3.4 Add to .gitignore

**`.gitignore`**

Add the following lines:

```
# Application logs
logs/
*.log
*.pid

# Virtual environment
.venv/
venv/
env/
```

#### 3.5 Test Scripts

**Start the application:**
```bash
./start_app.sh
```

**Expected output:**
- Virtual environment activated
- Dependencies checked
- Backend starts on port 8000
- Frontend starts on port 3000
- URLs displayed
- PID files created in logs/

**Stop the application:**
```bash
./stop_app.sh
```

**Expected output:**
- Both processes stopped gracefully
- PID files removed
- Any remaining processes on ports killed

**View logs:**
```bash
# Watch backend logs
tail -f logs/backend.log

# Watch frontend logs
tail -f logs/frontend.log
```

---

### Step 4: Frontend Setup (Estimated: 3-4 hours)

#### 4.1 Initialize React Project

```bash
# Create React app with Vite + TypeScript
npm create vite@latest frontend -- --template react-ts

cd frontend

# Install dependencies
npm install

# Install Tailwind CSS
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p

# Install additional dependencies
npm install react-icons
```

#### 4.2 Configure Tailwind

**`tailwind.config.js`**
```js
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}
```

**`src/index.css`**
```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

#### 4.3 Environment Configuration

**`.env.local`**
```
VITE_API_URL=http://localhost:8000
```

#### 4.4 Project Structure

Create the following structure:

```
frontend/src/
├── App.tsx                  # Main app component
├── main.tsx                 # Entry point
├── index.css                # Global styles (Tailwind)
├── components/
│   ├── ChatPanel/
│   │   ├── ChatPanel.tsx
│   │   ├── MessageList.tsx
│   │   ├── Message.tsx
│   │   └── ChatInput.tsx
│   ├── SlidePanel/
│   │   ├── SlidePanel.tsx
│   │   └── SlideTile.tsx
│   └── Layout/
│       └── AppLayout.tsx
├── services/
│   └── api.ts               # API client
└── types/
    ├── message.ts
    └── slide.ts
```

---

### Step 5: Frontend - Type Definitions (Estimated: 30 min)

#### 5.1 Message Types

**`src/types/message.ts`**
```typescript
export type MessageRole = 'user' | 'assistant' | 'tool';

export interface ToolCall {
  name: string;
  arguments: Record<string, any>;
}

export interface Message {
  role: MessageRole;
  content: string;
  timestamp: string;
  tool_call?: ToolCall;
  tool_call_id?: string;
}

export interface ChatResponse {
  messages: Message[];
  slide_deck: SlideDeck | null;
  metadata: {
    latency_seconds: number;
    tool_calls: number;
  };
}
```

#### 5.2 Slide Types

**`src/types/slide.ts`**
```typescript
export interface Slide {
  index: number;
  slide_id: string;
  html: string;
}

export interface SlideDeck {
  title: string;
  slide_count: number;
  css: string;
  external_scripts: string[];
  scripts: string;
  slides: Slide[];
}
```

---

### Step 6: Frontend - API Client (Estimated: 1 hour)

**`src/services/api.ts`**

```typescript
import { ChatResponse } from '../types/message';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

export const api = {
  /**
   * Send a message to the chat API
   * 
   * Phase 1: No session_id parameter
   * Phase 4: Add session_id parameter
   */
  async sendMessage(
    message: string, 
    maxSlides: number = 10
    // sessionId?: string  // For Phase 4
  ): Promise<ChatResponse> {
    const response = await fetch(`${API_BASE_URL}/api/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        message,
        max_slides: maxSlides,
        // session_id: sessionId  // For Phase 4
      }),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new ApiError(
        response.status,
        error.detail || 'Failed to send message'
      );
    }

    return response.json();
  },

  async healthCheck(): Promise<{ status: string }> {
    const response = await fetch(`${API_BASE_URL}/api/health`);
    if (!response.ok) {
      throw new ApiError(response.status, 'Health check failed');
    }
    return response.json();
  },
};
```

**Key Points:**
- Simple fetch-based API client
- Error handling with custom ApiError
- Placeholder comments for Phase 4 session support
- Health check for testing

---

### Step 7: Frontend - Chat Components (Estimated: 4-5 hours)

#### 7.1 Chat Panel Container

**`src/components/ChatPanel/ChatPanel.tsx`**

```typescript
import React, { useState } from 'react';
import { Message, ChatResponse } from '../../types/message';
import { SlideDeck } from '../../types/slide';
import { MessageList } from './MessageList';
import { ChatInput } from './ChatInput';
import { api } from '../../services/api';

interface ChatPanelProps {
  onSlidesGenerated: (slideDeck: SlideDeck) => void;
}

export const ChatPanel: React.FC<ChatPanelProps> = ({ onSlidesGenerated }) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSendMessage = async (content: string, maxSlides: number) => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await api.sendMessage(content, maxSlides);
      
      // Add new messages to chat
      setMessages(prev => [...prev, ...response.messages]);
      
      // Pass slide deck to parent
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

  return (
    <div className="flex flex-col h-full bg-gray-50">
      {/* Header */}
      <div className="p-4 border-b bg-white">
        <h2 className="text-lg font-semibold">Chat</h2>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto">
        <MessageList messages={messages} isLoading={isLoading} />
      </div>

      {/* Error Display */}
      {error && (
        <div className="p-4 bg-red-50 border-t border-red-200">
          <p className="text-sm text-red-600">{error}</p>
        </div>
      )}

      {/* Input */}
      <ChatInput onSend={handleSendMessage} disabled={isLoading} />
    </div>
  );
};
```

#### 7.2 Message List

**`src/components/ChatPanel/MessageList.tsx`**

```typescript
import React, { useEffect, useRef } from 'react';
import { Message as MessageType } from '../../types/message';
import { Message } from './Message';

interface MessageListProps {
  messages: MessageType[];
  isLoading: boolean;
}

export const MessageList: React.FC<MessageListProps> = ({ messages, isLoading }) => {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  return (
    <div className="p-4 space-y-4">
      {messages.map((message, index) => (
        <Message key={index} message={message} />
      ))}
      
      {isLoading && (
        <div className="flex items-center space-x-2 text-gray-500">
          <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-500"></div>
          <span className="text-sm">Generating slides...</span>
        </div>
      )}
      
      <div ref={bottomRef} />
    </div>
  );
};
```

#### 7.3 Individual Message

**`src/components/ChatPanel/Message.tsx`**

```typescript
import React, { useState } from 'react';
import { Message as MessageType } from '../../types/message';

interface MessageProps {
  message: MessageType;
}

export const Message: React.FC<MessageProps> = ({ message }) => {
  const [isExpanded, setIsExpanded] = useState(false);

  // Style based on role
  const getMessageStyle = () => {
    switch (message.role) {
      case 'user':
        return 'bg-blue-100 ml-auto';
      case 'assistant':
        return 'bg-white';
      case 'tool':
        return 'bg-gray-100';
      default:
        return 'bg-gray-50';
    }
  };

  const getMessageLabel = () => {
    switch (message.role) {
      case 'user':
        return 'You';
      case 'assistant':
        return 'AI Assistant';
      case 'tool':
        return 'Tool Result';
      default:
        return message.role;
    }
  };

  // For tool messages, make them collapsible
  if (message.role === 'tool') {
    return (
      <div className={`max-w-3xl rounded-lg p-3 ${getMessageStyle()}`}>
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="flex items-center space-x-2 text-sm font-medium text-gray-600 hover:text-gray-800"
        >
          <span>{isExpanded ? '▼' : '▶'}</span>
          <span>{getMessageLabel()}</span>
        </button>
        
        {isExpanded && (
          <div className="mt-2 text-sm text-gray-600 font-mono whitespace-pre-wrap">
            {message.content}
          </div>
        )}
      </div>
    );
  }

  // For assistant messages that are HTML (very long), truncate display
  const isHtmlContent = message.content.includes('<!DOCTYPE html>');
  const displayContent = isHtmlContent 
    ? 'Generated slide deck HTML (view in Slides panel →)'
    : message.content;

  return (
    <div className={`max-w-3xl rounded-lg p-4 ${getMessageStyle()}`}>
      <div className="text-xs font-semibold text-gray-500 mb-1">
        {getMessageLabel()}
      </div>
      <div className="text-sm text-gray-800 whitespace-pre-wrap">
        {displayContent}
      </div>
      {message.tool_call && (
        <div className="mt-2 text-xs text-gray-500">
          Tool: {message.tool_call.name}
        </div>
      )}
    </div>
  );
};
```

#### 7.4 Chat Input

**`src/components/ChatPanel/ChatInput.tsx`**

```typescript
import React, { useState } from 'react';

interface ChatInputProps {
  onSend: (message: string, maxSlides: number) => void;
  disabled: boolean;
}

export const ChatInput: React.FC<ChatInputProps> = ({ onSend, disabled }) => {
  const [message, setMessage] = useState('');
  const [maxSlides, setMaxSlides] = useState(10);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (message.trim() && !disabled) {
      onSend(message.trim(), maxSlides);
      setMessage('');
    }
  };

  return (
    <form onSubmit={handleSubmit} className="p-4 bg-white border-t">
      <div className="flex items-end space-x-2">
        <div className="flex-1">
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSubmit(e);
              }
            }}
            placeholder="Ask me to create slides..."
            disabled={disabled}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
            rows={3}
          />
        </div>
        
        <div className="flex flex-col space-y-2">
          <input
            type="number"
            value={maxSlides}
            onChange={(e) => setMaxSlides(parseInt(e.target.value) || 10)}
            min="1"
            max="50"
            disabled={disabled}
            className="w-20 px-2 py-1 text-sm border border-gray-300 rounded"
            title="Max slides"
          />
          
          <button
            type="submit"
            disabled={disabled || !message.trim()}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
          >
            Send
          </button>
        </div>
      </div>
      
      <div className="mt-1 text-xs text-gray-500">
        Press Enter to send, Shift+Enter for new line
      </div>
    </form>
  );
};
```

---

### Step 8: Frontend - Slide Components (Estimated: 3-4 hours)

#### 8.1 Slide Panel Container

**`src/components/SlidePanel/SlidePanel.tsx`**

```typescript
import React from 'react';
import { SlideDeck } from '../../types/slide';
import { SlideTile } from './SlideTile';

interface SlidePanelProps {
  slideDeck: SlideDeck | null;
}

export const SlidePanel: React.FC<SlidePanelProps> = ({ slideDeck }) => {
  if (!slideDeck) {
    return (
      <div className="flex items-center justify-center h-full bg-gray-50">
        <div className="text-center text-gray-500">
          <p className="text-lg font-medium">No slides yet</p>
          <p className="text-sm mt-2">Send a message to generate slides</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto bg-gray-50">
      {/* Header */}
      <div className="sticky top-0 z-10 p-4 bg-white border-b">
        <h2 className="text-lg font-semibold">{slideDeck.title}</h2>
        <p className="text-sm text-gray-500">
          {slideDeck.slide_count} slide{slideDeck.slide_count !== 1 ? 's' : ''}
        </p>
      </div>

      {/* Slide Tiles */}
      <div className="p-4 space-y-4">
        {slideDeck.slides.map((slide, index) => (
          <SlideTile
            key={slide.slide_id}
            slide={slide}
            slideDeck={slideDeck}
            index={index}
          />
        ))}
      </div>
    </div>
  );
};
```

#### 8.2 Slide Tile

**`src/components/SlidePanel/SlideTile.tsx`**

```typescript
import React, { useMemo } from 'react';
import { Slide, SlideDeck } from '../../types/slide';

interface SlideTileProps {
  slide: Slide;
  slideDeck: SlideDeck;
  index: number;
}

export const SlideTile: React.FC<SlideTileProps> = ({ slide, slideDeck, index }) => {
  // Build complete HTML for iframe
  const slideHTML = useMemo(() => {
    return `
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  ${slideDeck.external_scripts.map(src => 
    `<script src="${src}"></script>`
  ).join('\n  ')}
  <style>${slideDeck.css}</style>
</head>
<body>
  ${slide.html}
  <script>${slideDeck.scripts}</script>
</body>
</html>
    `.trim();
  }, [slide.html, slideDeck.css, slideDeck.scripts, slideDeck.external_scripts]);

  return (
    <div className="bg-white rounded-lg shadow-md overflow-hidden">
      {/* Slide Header */}
      <div className="px-4 py-2 bg-gray-100 border-b flex items-center justify-between">
        <span className="text-sm font-medium text-gray-700">
          Slide {index + 1}
        </span>
        {/* Phase 2: Add edit/delete buttons here */}
      </div>

      {/* Slide Preview */}
      <div className="relative bg-gray-200" style={{ paddingBottom: '56.25%' }}>
        <iframe
          srcDoc={slideHTML}
          title={`Slide ${index + 1}`}
          className="absolute top-0 left-0 w-full h-full border-0"
          sandbox="allow-scripts"
          style={{
            transform: 'scale(1)',
            transformOrigin: 'top left',
          }}
        />
      </div>
    </div>
  );
};
```

**Key Points:**
- Renders slide in iframe for style isolation
- Injects CSS, scripts, and external scripts
- 16:9 aspect ratio container
- Placeholder comment for Phase 2 edit buttons

---

### Step 9: Frontend - App Layout (Estimated: 1-2 hours)

**`src/components/Layout/AppLayout.tsx`**

```typescript
import React, { useState } from 'react';
import { ChatPanel } from '../ChatPanel/ChatPanel';
import { SlidePanel } from '../SlidePanel/SlidePanel';
import { SlideDeck } from '../../types/slide';

export const AppLayout: React.FC = () => {
  const [slideDeck, setSlideDeck] = useState<SlideDeck | null>(null);

  return (
    <div className="h-screen flex flex-col">
      {/* Header */}
      <header className="bg-blue-600 text-white px-6 py-4 shadow-md">
        <h1 className="text-xl font-bold">AI Slide Generator</h1>
        <p className="text-sm text-blue-100">Phase 1 MVP - Single Session</p>
      </header>

      {/* Main Content: Two Panel Layout */}
      <div className="flex-1 flex overflow-hidden">
        {/* Chat Panel - Left 30% */}
        <div className="w-[30%] border-r">
          <ChatPanel onSlidesGenerated={setSlideDeck} />
        </div>

        {/* Slide Panel - Right 70% */}
        <div className="flex-1">
          <SlidePanel slideDeck={slideDeck} />
        </div>
      </div>
    </div>
  );
};
```

**`src/App.tsx`**

```typescript
import React from 'react';
import { AppLayout } from './components/Layout/AppLayout';
import './index.css';

function App() {
  return <AppLayout />;
}

export default App;
```

**`src/main.tsx`**

```typescript
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

---

### Step 10: Testing and Validation (Estimated: 2-3 hours)

#### 10.1 Start Both Servers

**Using Helper Script (Recommended):**
```bash
./start_app.sh
```

**Manual Start (Alternative):**

**Terminal 1 - Backend:**
```bash
cd /path/to/project
source .venv/bin/activate
uvicorn src.api.main:app --reload --port 8000
```

**Terminal 2 - Frontend:**
```bash
cd frontend
npm run dev
# Usually starts on http://localhost:3000
```

#### 10.2 Test Flow

1. **Open Browser**: Navigate to http://localhost:3000

2. **Test Health Check**: 
   - Open browser console
   - Should see no CORS errors

3. **Send Test Message**:
   - Type: "Create slides about Q3 sales performance"
   - Set max slides: 5
   - Click Send

4. **Verify Chat Display**:
   - User message appears (blue, right-aligned)
   - Tool call message appears (gray, collapsible)
   - Assistant message appears (white, left-aligned)
   - HTML content shows friendly message

5. **Verify Slide Display**:
   - Slides panel shows title
   - Slide count is correct
   - Each slide renders in iframe
   - Slides match the generated HTML

6. **Test Follow-up Message**:
   - Type: "Add a slide comparing to Q2"
   - Messages should append to existing chat
   - Slides should update with new deck

#### 10.3 Debug Checklist

**If no slides appear:**
- Check browser console for errors
- Check backend logs for HTML parsing errors
- Verify `SlideDeck.from_html_string()` works
- Check iframe sandbox restrictions

**If chat doesn't work:**
- Check CORS configuration
- Check API endpoint URL in .env.local
- Check backend is running
- Check request/response in Network tab

**If styles are broken:**
- Check Tailwind CSS is configured
- Check CSS is imported in main.tsx
- Check for CSS conflicts

---

### Step 11: Documentation (Estimated: 1 hour)

#### 11.1 Update README

Create/update `README_PHASE1.md`:

```markdown
# AI Slide Generator - Phase 1 MVP

## What Works in Phase 1
- ✅ Send messages to AI agent
- ✅ View chat history with tool calls
- ✅ View generated slides as tiles
- ✅ Single session (no persistence)

## What's NOT in Phase 1
- ❌ No drag-and-drop reordering
- ❌ No HTML editing
- ❌ No multi-session support
- ❌ No user authentication
- ❌ No session persistence

## Setup

### Quick Start
```bash
# Start application (backend + frontend)
./start_app.sh

# Stop application
./stop_app.sh
```

### Manual Setup

#### Backend
```bash
# Install dependencies
pip install -r requirements.txt

# Run server
uvicorn src.api.main:app --reload --port 8000
```

#### Frontend
```bash
cd frontend
npm install
npm run dev
```

## Testing
1. Start the app: `./start_app.sh`
2. Open http://localhost:3000
3. Type a message: "Create slides about sales data"
4. Click Send
5. View generated slides on the right
6. Stop the app: `./stop_app.sh`

## Architecture Notes
- Single global session (created on startup)
- No session persistence (restarts clear state)
- Comments indicate where Phase 4 changes needed
```

---

## Phase 1 Complete Checklist

### Backend
- [ ] FastAPI app created with CORS
- [ ] Chat endpoint implemented
- [ ] ChatService wraps existing agent
- [ ] SlideDeck parsing works
- [ ] Health check endpoint works
- [ ] Manual curl tests pass

### Helper Scripts
- [ ] start_app.sh created and executable
- [ ] stop_app.sh created and executable
- [ ] Scripts tested (start, stop, logs)
- [ ] logs/ directory added to .gitignore

### Frontend
- [ ] React + TypeScript + Vite setup
- [ ] Tailwind CSS configured
- [ ] API client with error handling
- [ ] Chat panel with message display
- [ ] Slide panel with iframe rendering
- [ ] Two-panel layout (30/70 split)
- [ ] Loading states work
- [ ] Error messages display

### Integration
- [ ] CORS allows frontend to call backend
- [ ] Messages send and receive correctly
- [ ] Slides render with correct styling
- [ ] Tool calls display properly
- [ ] Follow-up messages work
- [ ] No console errors

### Documentation
- [ ] README updated with Phase 1 status
- [ ] Setup instructions clear
- [ ] Known limitations documented
- [ ] Comments indicate Phase 4 extension points

---

## Estimated Total Time: 20.5-27.5 hours

- Backend: 5-8 hours
- Helper Scripts: 0.5 hours
- Frontend: 8-11 hours  
- Integration & Testing: 5-6 hours
- Documentation: 2-2.5 hours

---

## Next Steps

After Phase 1 is complete and tested:
1. Review with stakeholders
2. Gather feedback on UX
3. Proceed to **Phase 2**: Enhanced UI with drag-and-drop and editing

