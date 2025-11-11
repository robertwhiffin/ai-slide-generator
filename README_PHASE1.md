# AI Slide Generator - Phase 1 MVP

## Overview

Phase 1 MVP of the AI Slide Generator - a web application that generates presentation slides from natural language using AI. Chat with the agent and view generated slides in real-time.

## What Works in Phase 1

- ✅ Send messages to AI agent
- ✅ View chat history with tool calls
- ✅ View generated slides as tiles
- ✅ Single session (no persistence)
- ✅ Real-time slide preview
- ✅ Clean two-panel UI (Chat + Slides)

## What's NOT in Phase 1

- ❌ No drag-and-drop reordering
- ❌ No HTML editing
- ❌ No multi-session support
- ❌ No user authentication
- ❌ No session persistence (restarts clear state)

## Technologies Used

### Backend
- **FastAPI**: Modern Python web framework for APIs
- **LangChain**: LLM orchestration and agent framework
- **Databricks**: LLM hosting and Genie integration
- **MLflow**: Tracing and observability
- **Pydantic**: Data validation and serialization
- **BeautifulSoup4**: HTML parsing for slide deck manipulation

### Frontend
- **React**: UI library
- **TypeScript**: Type-safe JavaScript
- **Vite**: Fast build tool and dev server
- **Tailwind CSS**: Utility-first CSS framework

### Development
- **uvicorn**: ASGI server for FastAPI
- **pytest**: Testing framework
- **uv**: Python package manager

## Architecture

### Backend Structure
```
src/
├── api/                    # FastAPI application
│   ├── main.py            # App initialization
│   ├── models/            # Pydantic models
│   │   ├── requests.py    # Request schemas
│   │   └── responses.py   # Response schemas
│   ├── routes/            # API endpoints
│   │   └── chat.py        # Chat endpoint
│   └── services/          # Business logic
│       └── chat_service.py # Chat service wrapper
├── models/                # Data models
│   ├── slide_deck.py      # SlideDeck parser
│   └── slide.py           # Individual slide
└── services/              # Core services
    ├── agent.py           # LangChain agent
    └── tools.py           # Agent tools (Genie)
```

### Frontend Structure
```
frontend/src/
├── components/
│   ├── ChatPanel/         # Chat UI components
│   │   ├── ChatPanel.tsx
│   │   ├── MessageList.tsx
│   │   ├── Message.tsx
│   │   └── ChatInput.tsx
│   ├── SlidePanel/        # Slide display components
│   │   ├── SlidePanel.tsx
│   │   └── SlideTile.tsx
│   └── Layout/
│       └── AppLayout.tsx  # Main layout
├── services/
│   └── api.ts             # API client
└── types/
    ├── message.ts         # Message types
    └── slide.ts           # Slide types
```

## Setup

### Prerequisites
- Python 3.11+
- Node.js 18+
- npm or yarn
- Databricks workspace with Genie access

### Environment Configuration

1. **Backend Configuration** - Create `config/config.yaml`:
```yaml
# See config/config.example.yaml for template
```

2. **Frontend Configuration** - Already set in `frontend/vite.config.ts`:
- API URL: `http://localhost:8000`
- Dev port: `3000`

### Quick Start

The easiest way to run the application:

```bash
# Start both backend and frontend
./start_app.sh

# Stop the application
./stop_app.sh
```

The script will:
- Create virtual environment if needed
- Install dependencies
- Start backend on port 8000
- Start frontend on port 3000
- Check health status

Access the application at:
- **Frontend**: http://localhost:3000
- **Backend**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs

### Manual Setup

If you prefer to run services separately:

#### Backend

```bash
# Create virtual environment (if needed)
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run server
uvicorn src.api.main:app --reload --port 8000
```

#### Frontend

```bash
cd frontend

# Install dependencies
npm install

# Run dev server
npm run dev
```

## Usage

1. **Start the application**:
   ```bash
   ./start_app.sh
   ```

2. **Open your browser** to http://localhost:3000

3. **Send a message** in the chat panel:
   - Type a message like "Create slides about Q3 sales performance"
   - Set max slides (default: 10)
   - Press Enter or click Send

4. **View generated slides** in the slide panel:
   - Slides appear as tiles
   - Each slide shows a live preview
   - Tool calls are collapsible in chat

5. **Stop the application**:
   ```bash
   ./stop_app.sh
   ```

## Viewing Logs

```bash
# Backend logs
tail -f logs/backend.log

# Frontend logs
tail -f logs/frontend.log
```

## API Endpoints

### Health Check
```bash
GET /api/health
```
Returns service status.

### Chat
```bash
POST /api/chat
Content-Type: application/json

{
  "message": "Create slides about sales data",
  "max_slides": 10
}
```

Returns:
```json
{
  "messages": [...],
  "slide_deck": {...},
  "metadata": {
    "latency_seconds": 2.5,
    "tool_calls": 1
  }
}
```

### API Documentation
Interactive API docs available at: http://localhost:8000/docs

## Design Decisions (Phase 1)

### Single Session Architecture
- **Why**: Simplify Phase 1 implementation
- **Implementation**: Global service instance created on startup
- **Trade-off**: No multi-user support, session lost on restart
- **Future**: Phase 4 will add session management

### In-Memory State
- **Why**: Avoid database complexity in MVP
- **Implementation**: Slide deck stored in ChatService instance
- **Trade-off**: State lost on restart
- **Future**: Phase 4 will add persistence

### Two-Panel Layout
- **Why**: Clear separation of chat and slide viewing
- **Implementation**: 30% chat, 70% slides (fixed layout)
- **Trade-off**: Not responsive on mobile
- **Future**: Phase 2 will add responsive design

### Iframe Slide Rendering
- **Why**: Isolate slide CSS/JS from app
- **Implementation**: Each slide rendered in isolated iframe
- **Trade-off**: Some performance overhead
- **Benefit**: Prevents style conflicts

## Troubleshooting

### Backend won't start
- Check `logs/backend.log` for errors
- Verify virtual environment is activated
- Check Databricks credentials in config
- Ensure port 8000 is available

### Frontend won't start
- Check `logs/frontend.log` for errors
- Run `npm install` in frontend directory
- Ensure port 3000 is available
- Check `frontend/.gitignore` doesn't block required files

### CORS errors in browser
- Verify backend is running on port 8000
- Check CORS configuration in `src/api/main.py`
- Ensure frontend is on port 3000 or 5173

### Slides not rendering
- Check browser console for errors
- Verify `SlideDeck.to_dict()` returns valid structure
- Check iframe sandbox restrictions
- View backend logs for HTML parsing errors

### Agent errors
- Check Databricks credentials
- Verify Genie space ID in config
- Check MLflow tracking URI
- View backend logs for agent errors

## Testing

### Backend Tests
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src tests/
```

### Frontend Tests
```bash
cd frontend

# Run tests (when added in Phase 2)
npm test
```

### Manual Testing Checklist
- [ ] Backend health check responds
- [ ] Frontend loads without errors
- [ ] Send a message
- [ ] Slides appear in panel
- [ ] Tool calls are collapsible
- [ ] Follow-up messages work
- [ ] Error messages display properly

## Known Limitations

1. **Session Management**: Single session only, lost on restart
2. **No Persistence**: All data in memory
3. **No Authentication**: Development mode only
4. **Fixed Layout**: Not responsive
5. **No Slide Editing**: View-only mode
6. **No Reordering**: Fixed slide order

## Next Steps

After Phase 1 validation:

1. **Phase 2**: Enhanced UI
   - Drag-and-drop slide reordering
   - HTML editing capabilities
   - Responsive design
   - Better error handling

2. **Phase 3**: Databricks Deployment
   - Package as Databricks App
   - Databricks authentication
   - Unity Catalog integration
   - Production MLflow tracking

3. **Phase 4**: Multi-Session Support
   - Session management
   - Database persistence
   - User session history
   - Session switching UI

## Code Extension Points

Comments in the code indicate where Phase 4 changes are needed:

- `src/api/models/requests.py`: Add `session_id` parameter
- `src/api/services/chat_service.py`: Replace global instance with DI
- `src/api/routes/chat.py`: Add session_id handling
- `frontend/src/services/api.ts`: Add session_id parameter
- `frontend/src/components/ChatPanel/ChatPanel.tsx`: Pass session_id

## Development Notes

### Adding New API Endpoints
1. Create Pydantic models in `src/api/models/`
2. Add route in `src/api/routes/`
3. Include router in `src/api/main.py`
4. Update frontend API client

### Modifying Slide Rendering
1. Update `SlideDeck.to_dict()` in `src/models/slide_deck.py`
2. Update TypeScript types in `frontend/src/types/slide.ts`
3. Update `SlideTile` component as needed

### Changing LLM Behavior
1. Update system prompt in `config/prompts.yaml`
2. Modify agent configuration in `src/services/agent.py`
3. Adjust tool definitions in `src/services/tools.py`

## Contributing

1. Create feature branch from `main`
2. Make changes
3. Write/update tests
4. Ensure all tests pass
5. Update documentation
6. Submit PR

## License

[Add your license here]

## Contact

[Add contact information]

