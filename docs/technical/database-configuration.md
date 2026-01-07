# Database Configuration System

**Status:** Complete - Configuration & Session Models  
**Last Updated:** January 7, 2026

## Overview

The AI Slide Generator uses a PostgreSQL database to manage configuration profiles. This replaces the previous YAML-based configuration system and enables:

- Multiple configuration profiles
- Hot-reload without application restart
- Configuration history and audit trail
- Dynamic profile switching
- Centralized configuration management

## Architecture

### Database Schema

The database consists of configuration and session tables:

**Configuration Tables:**
1. **`config_profiles`** - Configuration profiles (e.g., "production", "development")
2. **`config_ai_infra`** - AI/LLM settings (endpoint, temperature, max tokens)
3. **`config_genie_spaces`** - Databricks Genie space configurations
4. **`config_mlflow`** - MLflow experiment settings
5. **`config_prompts`** - System prompts and deck prompt selection
6. **`config_history`** - Audit trail of all configuration changes
7. **`slide_deck_prompt_library`** - Global deck prompt templates (shared across profiles)

**Session Tables:**
7. **`user_sessions`** - User conversation sessions with processing locks
8. **`session_messages`** - Chat messages with request_id for polling
9. **`session_slide_decks`** - Slide deck state per session
10. **`chat_requests`** - Async chat request tracking for polling mode

### Entity Relationships

**Configuration Tables:**
```
config_profiles (1) ──┬── (1) config_ai_infra
                      ├── (1) config_genie_spaces
                      ├── (1) config_mlflow
                      ├── (1) config_prompts ──── (0..1) slide_deck_prompt_library
                      └── (n) config_history

slide_deck_prompt_library (global) ──── (n) config_prompts (via selected_deck_prompt_id FK)
```

**Session Tables:**
```
user_sessions (1) ──┬── (n) session_messages
                    ├── (1) session_slide_decks
                    └── (n) chat_requests
```

- One profile has exactly one AI infrastructure config
- One profile has exactly one Genie space
- One profile has exactly one MLflow config
- One profile has exactly one prompts config
- All changes are tracked in history

### Key Constraints

1. **Unique Profile Names**: Each profile must have a unique name
2. **Single Default Profile**: Only one profile can be marked as default (enforced by trigger)
3. **One Genie Space Per Profile**: Each profile can have only one Genie space (enforced by unique constraint)
4. **Cascade Delete**: Deleting a profile cascades to all related configurations
5. **Temperature Range**: LLM temperature must be between 0 and 1
6. **Positive Max Tokens**: LLM max_tokens must be greater than 0

## Database Connection

### Configuration

Database connection is configured via environment variable:

```bash
# .env
DATABASE_URL=postgresql://localhost:5432/ai_slide_generator
```

Default: `postgresql://localhost:5432/ai_slide_generator`

### Connection Pooling

```python
from src.core.database import engine, SessionLocal, get_db, get_db_session

# Engine with connection pooling
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,  # Verify connections before use
    pool_size=10,  # Maintain 10 connections
    max_overflow=20,  # Allow 20 additional connections
)
```

### Session Management

**For FastAPI routes:**

```python
from fastapi import Depends
from src.core.database import get_db


@app.get("/profiles")
def list_profiles(db: Session = Depends(get_db)):
    return db.query(ConfigProfile).all()
```

**For standalone scripts:**

```python
from src.core.database import get_db_session

with get_db_session() as db:
    profile = db.query(ConfigProfile).first()
    # Changes are automatically committed on exit
```

## Models

### ConfigProfile

Main profile entity containing metadata about a configuration set.

```python
class ConfigProfile(Base):
    id: int
    name: str                    # Unique profile name
    description: str | None
    is_default: bool             # Only one can be True
    created_at: datetime
    created_by: str | None
    updated_at: datetime
    updated_by: str | None
    
    # Relationships
    ai_infra: ConfigAIInfra
    genie_spaces: list[ConfigGenieSpace]
    mlflow: ConfigMLflow
    prompts: ConfigPrompts
    history: list[ConfigHistory]
```

### ConfigAIInfra

LLM and AI infrastructure settings.

```python
class ConfigAIInfra(Base):
    id: int
    profile_id: int              # Foreign key to config_profiles
    llm_endpoint: str            # e.g., "databricks-claude-sonnet-4-5"
    llm_temperature: Decimal     # 0.0 to 1.0
    llm_max_tokens: int          # Must be positive
    created_at: datetime
    updated_at: datetime
```

### ConfigGenieSpace

Databricks Genie space configuration. Each profile has exactly one Genie space.

```python
class ConfigGenieSpace(Base):
    id: int
    profile_id: int              # Foreign key to config_profiles (unique)
    space_id: str                # Genie space ID
    space_name: str              # Display name
    description: str | None
    created_at: datetime
    updated_at: datetime
```

### ConfigMLflow

MLflow experiment tracking settings.

```python
class ConfigMLflow(Base):
    id: int
    profile_id: int              # Foreign key to config_profiles
    experiment_name: str         # MLflow experiment path
    created_at: datetime
    updated_at: datetime
```

### ConfigPrompts

System prompts and deck prompt selection for the LLM.

```python
class ConfigPrompts(Base):
    id: int
    profile_id: int                      # Foreign key to config_profiles
    selected_deck_prompt_id: int | None  # FK to slide_deck_prompt_library (optional)
    system_prompt: str                   # Main system prompt (advanced)
    slide_editing_instructions: str      # Editing mode instructions (advanced)
    created_at: datetime
    updated_at: datetime
```

### SlideDeckPromptLibrary

Global deck prompt templates shared across all profiles.

```python
class SlideDeckPromptLibrary(Base):
    id: int
    name: str                    # Template name (e.g., "Quarterly Business Review")
    description: str | None      # What this template is for
    category: str | None         # Grouping (e.g., "Report", "Review", "Summary")
    prompt_content: str          # Full prompt instructions for the AI
    is_active: bool              # Whether available for selection
    created_by: str | None       # Who created it
    created_at: datetime
    updated_by: str | None       # Who last updated it
    updated_at: datetime
```

**How deck prompts work:**
1. Deck prompts are created globally (not per-profile)
2. Each profile can select one deck prompt via `config_prompts.selected_deck_prompt_id`
3. When generating slides, the deck prompt content is prepended to the system prompt
4. This enables standardized presentations without users retyping instructions each time

### ConfigHistory

Audit trail of all configuration changes.

```python
class ConfigHistory(Base):
    id: int
    profile_id: int              # Foreign key to config_profiles
    domain: str                  # 'ai_infra', 'genie', 'mlflow', 'prompts', 'profile'
    action: str                  # 'create', 'update', 'delete', 'activate'
    changed_by: str              # User who made the change
    changes: dict                # {"field": {"old": "...", "new": "..."}}
    snapshot: dict | None        # Full settings snapshot at time of change
    timestamp: datetime
```

## Session Models

### UserSession

User conversation sessions with processing lock support.

```python
class UserSession(Base):
    id: int
    session_id: str              # Unique session identifier
    user_id: str | None          # Optional user identification
    title: str                   # Session title
    created_at: datetime
    last_activity: datetime
    genie_conversation_id: str | None  # Genie conversation ID (saved on first query, persists for source data links)
    is_processing: bool          # Lock flag for concurrent requests
    processing_started_at: datetime | None
```

### SessionMessage

Chat messages within a session.

```python
class SessionMessage(Base):
    id: int
    session_id: int              # Foreign key to user_sessions
    role: str                    # 'user', 'assistant', 'tool'
    content: str                 # Message content
    message_type: str | None     # 'user_input', 'reasoning', 'tool_call', etc.
    metadata_json: str | None    # JSON with tool_name, tool_input
    request_id: str | None       # Links to chat_requests for polling
    created_at: datetime
```

### SessionSlideDeck

Slide deck state for a session, including LLM as Judge verification results.

```python
class SessionSlideDeck(Base):
    id: int
    session_id: int              # Foreign key to user_sessions (unique)
    title: str | None            # Deck title
    html_content: str            # Full HTML content (knitted slides)
    scripts_content: str | None  # JavaScript content (Chart.js, etc.)
    slide_count: int             # Number of slides
    deck_json: str | None        # JSON blob with full SlideDeck structure (slides, css, scripts)
    verification_map: str | None # JSON: {"content_hash": VerificationResult} - separate from deck_json
    created_at: datetime
    updated_at: datetime
```

**deck_json Structure:**

The `deck_json` field stores the slide deck structure (without verification):
- **slides[]**: Array of slide objects with `html` and `scripts`
- **css**: Global CSS styles
- **external_scripts**: External library URLs (Chart.js)
- **scripts**: Global JavaScript

**Verification Persistence (verification_map):**

LLM as Judge verification is stored **separately** in `verification_map`, keyed by content hash:

```json
{
  "a1b2c3d4e5f67890": {
    "score": 95,
    "rating": "excellent",
    "explanation": "All data accurate...",
    "issues": [],
    "duration_ms": 1523,
    "trace_id": "tr-abc123...",
    "genie_conversation_id": "01j...",
    "error": false,
    "timestamp": "2024-12-15T10:30:00Z"
  },
  "f9e8d7c6b5a43210": {
    "score": 80,
    "rating": "good",
    ...
  }
}
```

**Why separate storage?** When chat regenerates slides (e.g., "add a title slide"), `deck_json` is overwritten. By storing verification in a separate column keyed by content hash, existing verification survives deck regeneration. On load, verification is merged back into slides by matching content hashes.

See [LLM as Judge Verification](llm-as-judge-verification.md) for details on the verification system.

### ChatRequest

Tracks async chat requests for polling-based streaming.

```python
class ChatRequest(Base):
    id: int
    request_id: str              # Unique request identifier
    session_id: int              # Foreign key to user_sessions
    status: str                  # 'pending', 'running', 'completed', 'error'
    error_message: str | None    # Error details if status=error
    result_json: str | None      # JSON with slides, raw_html, replacement_info
    created_at: datetime
    completed_at: datetime | None
```

## Schema Management

### Pre-Release Approach

**Current Status:** Pre-release - schema is actively evolving.

Tables are automatically created from SQLAlchemy models using:

```python
from src.core.database import init_db

init_db()  # Creates all tables from Base.metadata
```

This is called automatically by:
- `scripts/init_database.py` - Ensures tables exist before seeding data
- `quickstart/setup_database.sh` - Creates tables during initial setup

### When to Add Migrations

**Migrations will be added when:**
- Application reaches production with real user data
- Schema changes need to preserve existing data
- Deploying to Databricks Lakebase with established datasets

**For now:** Schema changes are handled by dropping and recreating the database during development.

**Future Migration Setup:**
When ready for production, [Alembic](https://alembic.sqlalchemy.org/) can be added back:
1. Install: `pip install alembic`
2. Initialize: `alembic init alembic`
3. Configure `alembic.ini` with `DATABASE_URL` from environment
4. Generate initial migration: `alembic revision --autogenerate -m "initial schema"`
5. Apply migrations: `alembic upgrade head`

## Database Initialization

### Default Profile

On first run, initialize the database with a default profile:

```bash
python scripts/init_database.py
```

This creates:
- A "default" profile marked as the default
- Default AI infrastructure settings (LLM endpoint: `databricks-claude-sonnet-4-5`)
- Default Genie space configuration (one per profile)
- Default MLflow experiment name
- Default system prompts
- Seed deck prompts (Consumption Review, QBR, Executive Summary, Use Case Analysis)

### Profile Creation

Profiles are created via a 6-step wizard that collects all required configuration:

1. **Basic Info** - Name and description
2. **Genie Space** - Required data source with AI description
3. **LLM Settings** - Defaults to `databricks-claude-sonnet-4-5`
4. **MLflow** - Auto-populated with `/Workspace/Users/{username}/ai-slide-generator`
5. **Deck Prompt** - Optional template selection
6. **Review** - Confirmation before creation

The wizard creates the profile and all configurations in a single transaction via `ProfileService.create_profile_with_config()`. This ensures profiles are always complete and usable immediately after creation.

### Default Values

Defined in `src/core/defaults.py`:

```python
DEFAULT_CONFIG = {
    "llm": {
        "endpoint": "databricks-claude-sonnet-4-5",
        "temperature": 0.7,
        "max_tokens": 60000,
    },
    # No default Genie space - must be explicitly configured per profile
    "prompts": {
        "system_prompt": "...",
        "slide_editing_instructions": "...",
    },
}
```

**Note:** Genie space must be explicitly configured for each profile. MLflow experiment name is auto-set based on the profile creator's username.

### Default Deck Prompts

The database is seeded with default deck prompt templates:

| Name | Category | Description |
|------|----------|-------------|
| Consumption Review | Review | Analyze usage trends and optimization opportunities |
| Quarterly Business Review | Report | QBR structure with metrics, achievements, and outlook |
| Executive Summary | Summary | Concise 5-7 slide format for leadership |
| Use Case Analysis | Analysis | Portfolio overview with blocker identification |

Run `python scripts/init_database.py --reset` to recreate the database with seed data.

## Testing

### Unit Tests

Located in `tests/unit/config/test_models.py`:

```bash
# Run all settings model tests
pytest tests/unit/settings/test_models.py -v

# Run specific test
pytest tests/unit/settings/test_models.py::test_create_profile -v
```

**Test Coverage:**
- Profile creation and uniqueness
- Relationships between models
- Genie space management
- MLflow configuration
- Prompts configuration
- Complete profile with all configs

**Note:** Tests use SQLite in-memory database for speed. Some PostgreSQL-specific features (like JSONB and cascade deletes) are tested separately in integration tests.

## Next Steps

**Phase 2: Backend Services** (Days 3-5)
- ProfileService for CRUD operations
- ConfigService for configuration management
- GenieService for Genie space operations
- ConfigValidator for validation logic
- Configuration history tracking

See `docs/backend-database-implementation/PHASE_2_BACKEND_SERVICES.md` for details.

## References

- [SQLAlchemy 2.0 Documentation](https://docs.sqlalchemy.org/en/20/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [Phase 1 Implementation Plan](../backend-database-implementation/PHASE_1_DATABASE_SETUP.md)

