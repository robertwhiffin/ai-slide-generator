# Backend (`src/`)

Python backend for the AI Slide Generator. FastAPI + LangChain + Databricks.

## Quick Start

```bash
source .venv/bin/activate
uvicorn src.api.main:app --reload --port 8000
# API docs: http://localhost:8000/docs
```

---

## Directory Structure

```
src/
├── api/                    # FastAPI application
│   ├── main.py             # App entry point, CORS, routers
│   ├── routes/
│   │   ├── chat.py         # POST /api/chat
│   │   ├── slides.py       # Slide CRUD endpoints
│   │   ├── sessions.py     # Session management
│   │   └── settings/       # Config profile endpoints
│   ├── schemas/            # Pydantic request/response models
│   └── services/
│       ├── chat_service.py # Orchestrates agent + session state
│       └── session_manager.py # Database-backed sessions
│
├── services/               # Core business logic
│   ├── agent.py            # SlideGeneratorAgent (LangChain)
│   ├── tools.py            # Genie tool implementation
│   ├── genie_service.py    # Genie space operations
│   ├── profile_service.py  # Config profile CRUD
│   ├── config_service.py   # Settings management
│   └── config_validator.py # Validation logic
│
├── core/                   # Configuration and clients
│   ├── settings_db.py      # Database-backed settings
│   ├── databricks_client.py # Singleton WorkspaceClient
│   ├── database.py         # SQLAlchemy engine/session
│   └── lakebase.py         # Lakebase connection (production)
│
├── domain/                 # Domain models
│   ├── slide.py            # Slide class (single slide HTML)
│   └── slide_deck.py       # SlideDeck (parse/manipulate/render)
│
├── database/models/        # SQLAlchemy ORM models
│   ├── profile.py          # Configuration profiles
│   ├── session.py          # Chat sessions
│   ├── history.py          # Session history/snapshots
│   ├── ai_infra.py         # LLM endpoint settings
│   ├── genie_space.py      # Genie configuration
│   ├── mlflow.py           # MLflow settings
│   └── prompts.py          # System prompts
│
└── utils/
    ├── html_utils.py       # Canvas/script extraction
    ├── logging_config.py   # Structured logging setup
    └── error_handling.py   # Common error patterns
```

---

## Request Flow

```
HTTP Request
    │
    ▼
FastAPI Router (routes/*.py)
    │ Validates request via Pydantic schemas
    ▼
ChatService (api/services/chat_service.py)
    │ Manages session state, slide deck cache
    ▼
SlideGeneratorAgent (services/agent.py)
    │ LangChain AgentExecutor with tool-calling
    ▼
Genie Tool (services/tools.py)
    │ Natural language → SQL → data
    ▼
LLM generates HTML slides
    │
    ▼
SlideDeck parses response (domain/slide_deck.py)
    │
    ▼
Response returned to frontend
```

---

## Key Classes

### `SlideGeneratorAgent` (`services/agent.py`)

LangChain agent that generates slides. Uses:
- `ChatDatabricks` for LLM calls
- `StructuredTool` for Genie queries
- `ChatMessageHistory` for conversation state
- MLflow for tracing

```python
agent = create_agent(session_id, profile_id)
result = await agent.generate_slides(question, max_slides)
```

### `ChatService` (`api/services/chat_service.py`)

Orchestrates agent and session state:
- Creates/retrieves agents per session
- Caches current `SlideDeck` and raw HTML
- Applies slide replacements from edit requests
- Validates canvas/script integrity

### `SlideDeck` (`domain/slide_deck.py`)

Parses and manipulates HTML slide decks:
- `from_html_string()` / `from_html()` - Parse HTML
- `to_html()` - Reconstruct full HTML
- `to_dict()` - JSON serialization for API
- Slide operations: insert, remove, swap, move

### `SessionManager` (`api/services/session_manager.py`)

Database-backed session persistence:
- Create/get/list sessions
- Store slide deck state
- Auto-create on first message

---

## API Endpoints

| Method | Path | Handler | Purpose |
|--------|------|---------|---------|
| POST | `/api/chat` | `chat.send_message` | Generate or edit slides |
| GET | `/api/slides` | `slides.get_slides` | Get current deck |
| PUT | `/api/slides/reorder` | `slides.reorder_slides` | Reorder slides |
| PATCH | `/api/slides/{idx}` | `slides.update_slide` | Edit slide HTML |
| POST | `/api/slides/{idx}/duplicate` | `slides.duplicate_slide` | Clone slide |
| DELETE | `/api/slides/{idx}` | `slides.delete_slide` | Remove slide |
| GET | `/api/health` | `main.health` | Health check |
| GET/POST | `/api/settings/*` | `settings/*` | Config management |

---

## Configuration

**YAML files** (`config/`):
- `config.yaml` - LLM endpoint, Genie space, defaults (used for initial profile seeding)
- `seed_profiles.yaml` - Seed profiles for development (uses defaults from `src/core/defaults.py`)

**Environment variables** (override YAML):
- `DATABRICKS_HOST`, `DATABRICKS_TOKEN` - Auth
- `DATABASE_URL` - PostgreSQL connection
- `LOG_LEVEL` - Logging verbosity
- `ENVIRONMENT` - `development` or `production`

**Database-backed settings** (runtime):
- Profiles with LLM, Genie, MLflow, prompt configs
- Hot-reload without restart
- Managed via `/api/settings/*` endpoints

---

## Key Patterns

**Singleton clients**: `get_databricks_client()` returns shared `WorkspaceClient`

**Database sessions**: Use `get_db()` dependency for request-scoped sessions

**Settings loading**: `get_settings()` loads from database (YAML used only for initial seeding)

**Canvas/script validation**: Every `<canvas>` must have a matching Chart.js init script

**Slide context**: Edit requests include contiguous slide indices + HTML for replacement

---

## Testing

```bash
pytest tests/unit/          # Unit tests
pytest tests/integration/   # Integration tests
pytest --cov=src tests/     # With coverage
```

Tests mirror the `src/` structure in `tests/unit/` and `tests/integration/`.

