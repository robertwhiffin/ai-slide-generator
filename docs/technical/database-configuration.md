# Database Configuration System

**Status:** Complete - Configuration & Session Models  
**Last Updated:** April 2, 2026

## Overview

The AI Slide Generator uses a PostgreSQL database to manage configuration profiles. This replaces the previous YAML-based configuration system and enables:

- Session-bound agent configuration via `agent_config` JSON column
- Named profile snapshots for reusable configurations
- Deck prompt and slide style libraries
- Dynamic configuration per session

## Architecture

### Database Schema

The database consists of configuration and session tables:

**Configuration Tables:**
1. **`config_profiles`** - Named configuration snapshots with `agent_config` JSON
2. **`config_genie_spaces`** - Genie space configuration (one per profile)
3. **`config_prompts`** - Prompt configuration (system prompt, deck prompt/style references)
4. **`config_profile_contributors`** - Profile-level sharing permissions (user/group access)
5. **`slide_deck_prompt_library`** - Global deck prompt templates
6. **`slide_style_library`** - Global slide style library (CSS styles, image guidelines)
7. **`google_global_credentials`** - App-wide encrypted Google OAuth credentials.json (single row)
8. **`google_oauth_tokens`** - Per-user encrypted Google OAuth tokens (unique on `user_identity` only)
9. **`user_profile_preferences`** - Per-user default profile preferences

**Session Tables:**
10. **`user_sessions`** - User conversation sessions with processing locks and contributor support
11. **`session_messages`** - Chat messages with request_id for polling
12. **`session_slide_decks`** - Slide deck state per session with editing locks and optimistic concurrency
13. **`slide_deck_versions`** - Save point snapshots (up to 40 per session)
14. **`chat_requests`** - Async chat request tracking for polling mode
15. **`export_jobs`** - Async PPTX export job tracking
16. **`deck_contributors`** - Deck sharing/collaboration permissions (user/group access)

**Asset Tables:**
17. **`image_assets`** - Uploaded images with binary data and thumbnails

**Feedback & Monitoring Tables:**
18. **`feedback_conversations`** - AI-assisted feedback chat storage with structured summaries
19. **`survey_responses`** - User satisfaction survey data
20. **`request_logs`** - Per-request performance metrics

**Identity Tables:**
21. **`app_identities`** - Databricks UC identity cache (users/groups seen by the app)

### Entity Relationships

**Configuration Tables:**
```
config_profiles (1) ──┬── (n) config_genie_spaces
                      ├── (1) config_prompts ──┬── (?) slide_deck_prompt_library
                      │                        └── (?) slide_style_library
                      ├── (n) config_profile_contributors
                      └── (n) user_profile_preferences (via FK)

google_global_credentials (standalone, single row)
google_oauth_tokens (standalone, per user_identity, no profile FK)

slide_deck_prompt_library (global, referenced by config_prompts and agent_config.deck_prompt_id)
slide_style_library (global, referenced by config_prompts and agent_config.slide_style_id)
```

**Session Tables:**
```
user_sessions (1) ──┬── (n) session_messages
                    ├── (1) session_slide_decks
                    ├── (n) slide_deck_versions
                    ├── (n) chat_requests
                    ├── (n) deck_contributors
                    └── (n) user_sessions (self-referential via parent_session_id)

export_jobs (standalone, references session_id as string)
```

**Asset Tables:**
```
image_assets (standalone, no foreign keys)
```

**Feedback & Monitoring Tables:**
```
feedback_conversations (standalone)
survey_responses (standalone)
request_logs (standalone)
```

**Identity Tables:**
```
app_identities (standalone, no foreign keys)
```

- Each session carries its own `agent_config` JSON column with tools, style, prompt, and overrides
- Profiles are simplified named snapshots containing `agent_config` JSON
- Deck prompt and slide style libraries are global (referenced by ID from `agent_config`)
- Contributor sessions link to a parent session via `parent_session_id` and share the parent's slide deck
- Deck contributors and profile contributors both support USER and GROUP identity types

### Key Constraints

1. **Unique Profile Names**: Each profile must have a unique name
2. **Agent Config Validation**: Pydantic validates `agent_config` JSON on every write

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
from src.core.database import get_engine, get_session_local, get_db, get_db_session

# Engine with connection pooling (created lazily via get_engine())
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,  # Verify connections before use
    pool_size=80,  # Maintain 80 connections
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

Named configuration snapshot containing an `agent_config` JSON blob.

```python
class ConfigProfile(Base):
    id: int
    name: str                    # Unique profile name
    description: str | None
    is_default: bool             # Whether this is the system default profile
    global_permission: str | None # Global access level (e.g., 'CAN_USE')
    is_deleted: bool             # Soft delete flag
    deleted_at: datetime | None  # When soft-deleted
    agent_config: dict           # JSON: tools, slide_style_id, deck_prompt_id, system_prompt, etc.
    created_at: datetime
    created_by: str | None
    updated_at: datetime
    updated_by: str | None
```

**Agent config schema:**
```json
{
  "tools": [{"type": "genie", "space_id": "...", "space_name": "...", "description": "...", "conversation_id": "..."}],
  "slide_style_id": 3,
  "deck_prompt_id": 7,
  "system_prompt": null,
  "slide_editing_instructions": null
}
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
1. Deck prompts are created globally
2. Each session can select one deck prompt via `agent_config.deck_prompt_id`
3. When generating slides, the deck prompt content is prepended to the system prompt
4. This enables standardized presentations without users retyping instructions each time

### SlideStyleLibrary

Global slide style library shared across all profiles.

```python
class SlideStyleLibrary(Base):
    id: int
    name: str                    # Style name (e.g., "Databricks Brand"), unique
    description: str | None
    category: str | None         # e.g., "Brand", "Minimal", "Dark"
    style_content: str           # CSS/typography/layout rules for the AI
    image_guidelines: str | None # Markdown instructions for image usage in slides
    is_active: bool              # Whether available for selection
    is_system: bool              # Protected system styles (cannot be edited/deleted)
    is_default: bool             # System-wide default. Exactly one row is true at a time; settable only from the /admin "Slide Style" tab. Read by the server-side default resolver and by MCP create_deck when the caller omits slide_style_id.
    created_by: str | None
    created_at: datetime
    updated_by: str | None
    updated_at: datetime
```

**How slide styles work:**
1. Styles are created globally
2. Each session can select one style via `agent_config.slide_style_id`
3. When generating slides, the style content is included in the system prompt
4. `is_system=True` styles (e.g., "System Default") are protected from user modification

### GoogleGlobalCredentials

App-wide Google OAuth credentials (single row). Uploaded via admin page.

```python
class GoogleGlobalCredentials(Base):
    id: int
    credentials_encrypted: str    # Fernet-encrypted credentials.json
    uploaded_by: str | None       # User who uploaded
    created_at: datetime
    updated_at: datetime
```

### GoogleOAuthToken

Per-user encrypted Google OAuth tokens. Scoped by `user_identity` only (no `profile_id`).

```python
class GoogleOAuthToken(Base):
    id: int
    user_identity: str           # Databricks username or "local_dev"
    token_encrypted: str         # Fernet-encrypted JSON token
    created_at: datetime
    updated_at: datetime
    # UNIQUE (user_identity)
```

## Session Models

### UserSession

User conversation sessions with processing lock support and session-bound agent configuration.

```python
class UserSession(Base):
    id: int
    session_id: str              # Unique session identifier
    user_id: str | None          # Optional user identification (legacy)
    created_by: str | None       # Username of session creator (used for user-scoped filtering)
    parent_session_id: int | None # FK to user_sessions.id — contributor session support
    title: str                   # Session title
    created_at: datetime
    last_activity: datetime
    genie_conversation_id: str | None         # Genie conversation tracking (persists across profile switches)
    experiment_id: str | None                 # MLflow experiment tracking (per-session)
    google_slides_presentation_id: str | None # Reuse existing presentation on re-export
    google_slides_url: str | None             # URL to the exported Google Slides presentation
    agent_config: dict | None    # JSON: tools, slide_style_id, deck_prompt_id, prompts
    is_processing: bool          # Lock flag for concurrent requests
    processing_started_at: datetime | None
```

**`parent_session_id` column:** When set, this session is a contributor session that shares the parent's slide deck but has its own private chat history. `NULL` means this is an owner (root) session.

**`agent_config` column:** Stores the session's complete agent configuration as JSON. The agent is built per-request from this config via `build_agent_for_request()`. Each Genie space tool tracks its own `conversation_id` within the config. See [Agent Config Flow](profile-switch-genie-flow.md) for details.

### SessionMessage

Chat messages within a session.

```python
class SessionMessage(Base):
    id: int
    session_id: int              # Foreign key to user_sessions
    role: str                    # 'user', 'assistant', 'system'
    content: str                 # Message content
    message_type: str | None     # 'chat', 'slide_update', 'error', etc.
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
    locked_by: str | None        # Username holding deck-level editing lock
    locked_at: datetime | None   # When the editing lock was acquired (auto-expires after timeout)
    version: int                 # Optimistic locking counter — incremented on every write
    modified_by: str | None      # Username of last modifier
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

### SlideDeckVersion

Save point snapshots for deck versioning (up to 40 per session).

```python
class SlideDeckVersion(Base):
    id: int
    session_id: int              # Foreign key to user_sessions
    version_number: int          # Sequential version number within session
    description: str             # Human-readable description (e.g., "Generated 5 slides")
    deck_json: str               # Full SlideDeck structure as JSON
    verification_map_json: str | None  # Verification results keyed by content hash
    chat_history_json: str | None      # Chat messages at this point in time
    created_at: datetime
```

Indexed on `(session_id, version_number)` and `(session_id, created_at)`.

### ExportJob

Tracks async PPTX export jobs for polling.

```python
class ExportJob(Base):
    id: int
    job_id: str                  # Unique job identifier (UUID)
    session_id: str              # Session string ID (not FK — standalone)
    status: str                  # 'pending', 'running', 'completed', 'error'
    progress: int                # Slides processed so far
    total_slides: int            # Total slides to export
    title: str | None            # Deck title for filename
    output_path: str | None      # Path to generated PPTX file
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None
```

### ImageAsset

Uploaded images with binary data stored directly in PostgreSQL.

```python
class ImageAsset(Base):
    id: int
    filename: str                # Generated unique filename
    original_filename: str       # User's original filename
    mime_type: str               # e.g., "image/png"
    size_bytes: int
    image_data: bytes            # Binary image data (LargeBinary)
    thumbnail_base64: str | None # Base64-encoded thumbnail for previews
    tags: list                   # JSON array of tags
    description: str | None
    category: str | None
    uploaded_by: str | None
    is_active: bool
    created_by: str | None
    created_at: datetime
    updated_by: str | None
    updated_at: datetime
```

### DeckContributor

Deck sharing permissions — grants users or groups access to a deck (user session).

```python
class DeckContributor(Base):
    id: int
    user_session_id: int         # Foreign key to user_sessions (CASCADE delete)
    identity_type: str           # 'USER' or 'GROUP'
    identity_id: str             # Databricks user/group ID
    identity_name: str           # Display name (email or group name)
    permission_level: str        # 'CAN_USE', 'CAN_MANAGE', 'CAN_EDIT', 'CAN_VIEW'
    created_by: str | None       # Who added this contributor
    created_at: datetime
    updated_at: datetime
    # UNIQUE (user_session_id, identity_id)
```

### ConfigGenieSpace

Genie space configuration. Each profile has exactly one Genie space, enforced by a unique constraint on `profile_id`.

```python
class ConfigGenieSpace(Base):
    id: int
    profile_id: int              # Foreign key to config_profiles (CASCADE delete, unique)
    space_id: str                # Genie space ID
    space_name: str              # Genie space display name
    description: str | None
    created_at: datetime
    updated_at: datetime
```

### ConfigPrompts

Prompt configuration linking a profile to optional deck prompt and slide style from the global libraries, plus advanced system prompt overrides.

```python
class ConfigPrompts(Base):
    id: int
    profile_id: int              # Foreign key to config_profiles (CASCADE delete, unique)
    selected_deck_prompt_id: int | None  # FK to slide_deck_prompt_library (SET NULL on delete)
    selected_slide_style_id: int | None  # FK to slide_style_library (SET NULL on delete)
    system_prompt: str           # System-level prompt for slide generation
    slide_editing_instructions: str  # Instructions for editing slides
    created_at: datetime
    updated_at: datetime
```

### ConfigProfileContributor

Profile-level sharing permissions — grants users or groups access to a profile.

```python
class ConfigProfileContributor(Base):
    id: int
    profile_id: int              # Foreign key to config_profiles (CASCADE delete)
    identity_id: str             # Databricks user/group ID
    identity_type: str           # 'USER' or 'GROUP'
    identity_name: str           # Display name (email or group name)
    permission_level: str        # 'CAN_USE', 'CAN_MANAGE', 'CAN_EDIT', 'CAN_VIEW'
    created_by: str | None       # Who added this contributor
    created_at: datetime
    updated_at: datetime
    # UNIQUE (profile_id, identity_id)
```

### FeedbackConversation

Stores AI-assisted feedback conversations with structured summaries.

```python
class FeedbackConversation(Base):
    id: int
    category: str                # 'Bug Report', 'Feature Request', 'UX Issue', 'Performance', 'Content Quality', 'Other'
    summary: str                 # Structured summary of the feedback
    severity: str                # 'Low', 'Medium', 'High'
    raw_conversation: dict       # JSON: full conversation history
    created_at: datetime
```

### SurveyResponse

Stores periodic user satisfaction survey responses.

```python
class SurveyResponse(Base):
    id: int
    star_rating: int             # 1-5 star rating
    time_saved_minutes: int | None  # 15, 30, 60, 120, 240, or 480
    nps_score: int | None        # 0-10 Net Promoter Score
    created_at: datetime
```

### RequestLog

Per-request performance metrics for monitoring.

```python
class RequestLog(Base):
    id: int
    timestamp: datetime          # When the request was processed
    method: str                  # HTTP method (GET, POST, etc.)
    path: str                    # Request path
    status_code: int             # HTTP response status code
    duration_ms: float           # Request duration in milliseconds
    request_id: str | None       # Correlation ID
```

Indexed on `timestamp` for time-range queries.

### AppIdentity

Local cache of Databricks UC identities (users and groups) that have been seen by the app. Used as a fallback identity source when no admin token is configured.

```python
class AppIdentity(Base):
    id: int
    identity_id: str             # Databricks user/group ID (unique)
    identity_type: str           # 'USER' or 'GROUP'
    identity_name: str           # Email for users, name for groups
    display_name: str | None     # Friendly display name
    first_seen_at: datetime
    last_seen_at: datetime
    is_active: bool              # Soft delete flag
```

### UserProfilePreference

Per-user default profile preference. Replaces the global `is_default` flag on `config_profiles` with a per-user choice. Falls back to the system default when no preference is set.

```python
class UserProfilePreference(Base):
    id: int
    user_name: str               # Databricks username (unique)
    default_profile_id: int | None  # FK to config_profiles (SET NULL on delete)
    updated_at: datetime
```

## Database Connection: Lakebase Support

In addition to standard PostgreSQL, the database layer supports **Databricks Lakebase** as a production backend. Lakebase is detected automatically when `LAKEBASE_TYPE` is set or `PGHOST`/`PGUSER` environment variables are present (auto-injected by Databricks Apps).

**Key Lakebase features in `src/core/database.py`:**
- **OAuth token injection:** A `do_connect` event listener on the SQLAlchemy engine injects a fresh OAuth token as the PostgreSQL password for each new connection.
- **Background token refresh:** Tokens expire after 1 hour. An async background task refreshes them every ~50 minutes (with jitter) via `start_token_refresh()` / `stop_token_refresh()`.
- **Two Lakebase modes:** `autoscaling` (uses `ws.postgres.generate_database_credential`) and `provisioned` (uses `ws.database.generate_database_credential`).
- **Schema support:** `LAKEBASE_SCHEMA` env var (default: `app_data`) is appended to the connection URL's `search_path` and applied to all table metadata during `init_db()`.

## Schema Management

### Table Creation

Tables are created from SQLAlchemy models using `init_db()`:

```python
from src.core.database import init_db

init_db()  # Creates all tables from Base.metadata
```

This is called automatically by:
- `scripts/init_database.py` — Ensures tables exist before seeding data
- `quickstart/setup_database.sh` — Creates tables during initial setup
- Databricks App startup via `app.yaml` — `init_database()` in `databricks_tellr_app.run`

**Important limitation:** `init_db()` (which calls `Base.metadata.create_all()`) only creates tables that don't already exist. It does **not** add columns to existing tables. For that, `init_db()` calls `_run_migrations()` after `create_all()`.

### Schema Migrations

For adding columns to existing tables in production, a private `_run_migrations()` function in `src/core/database.py` runs idempotent `ALTER TABLE` statements. It is called automatically by `init_db()` after table creation.

**Migration steps handled by `_run_migrations()`:**
1. Adds `is_deleted`, `deleted_at`, `global_permission` columns to `config_profiles`
2. Adds `modified_by`, `locked_by`, `locked_at`, `version` columns to `session_slide_decks`
3. Migrates `google_credentials_encrypted` from per-profile to global table (`_migrate_google_credentials_to_global()`)
4. Removes `profile_id` from `google_oauth_tokens` (`_migrate_drop_profile_id_from_oauth_tokens()`)
5. Adds `image_guidelines` to `slide_style_library`, truncates session data (v0.2 breaking change)
6. Adds `created_by`, `google_slides_presentation_id`, `google_slides_url`, `agent_config` to `user_sessions`
7. Adds `is_default` to `slide_style_library` and seeds system style as default
8. Adds `parent_session_id` to `user_sessions` with FK and composite index for contributor sessions
9. Drops legacy `profile_id`/`profile_name` from `user_sessions`; migrates `CAN_VIEW` to `CAN_USE` in contributor tables

```python
# src/core/database.py
def init_db():
    """Create all tables in the database."""
    import src.database.models  # noqa: F401

    engine = get_engine()
    schema = os.getenv("LAKEBASE_SCHEMA")

    if schema:
        # For Lakebase: set schema on all tables
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text(f'SET search_path TO "{schema}"'))
            conn.commit()
        for table in Base.metadata.tables.values():
            if table.schema is None:
                table.schema = schema

    Base.metadata.create_all(bind=engine)

    # Run migrations for columns that create_all() won't add to existing tables
    _run_migrations(engine, schema)
```

Each migration step checks for column existence before running, making all operations idempotent and safe to run on every startup.

**Manual migrations:** Some schema changes require standalone SQL scripts (placed in `scripts/`).

## Database Initialization

### Database Initialization

On first run, initialize the database:

```bash
python scripts/init_database.py
```

This creates:
- Seed deck prompts (Consumption Review, QBR, Executive Summary, Use Case Analysis)
- Default slide styles

### Profile Creation

Profiles are created by saving a session's agent configuration as a named snapshot via `POST /api/profiles/save-from-session/{session_id}`. The profile stores the session's `agent_config` JSON (tools, slide style, deck prompt, prompt overrides).

Profiles can also be loaded into any session via `POST /api/sessions/{id}/load-profile/{profile_id}`.

**LLM is a fixed backend default** (not user-configurable). Sessions without Genie tools run in **prompt-only mode**.

### Default Values

The LLM endpoint and model parameters are fixed backend defaults (not stored in agent config or profiles). Sessions start with an empty `agent_config` (no tools, default style and prompt) and can be configured via the AgentConfigBar or by loading a profile.

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
# Run all config model tests
pytest tests/unit/config/test_models.py -v

# Run specific test
pytest tests/unit/config/test_models.py::test_create_profile -v
```

**Test Coverage:**
- Profile creation and uniqueness
- Relationships between models
- Genie space management
- MLflow configuration
- Prompts configuration
- Complete profile with all configs

**Note:** Tests use SQLite in-memory database for speed. Some PostgreSQL-specific features (like JSONB and cascade deletes) are tested separately in integration tests.

## References

- [SQLAlchemy 2.0 Documentation](https://docs.sqlalchemy.org/en/20/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)

