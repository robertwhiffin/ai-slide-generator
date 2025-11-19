# Database Configuration System

**Status:** Phase 1 Complete - Database Setup & Models  
**Last Updated:** November 19, 2025

## Overview

The AI Slide Generator uses a PostgreSQL database to manage configuration profiles. This replaces the previous YAML-based configuration system and enables:

- Multiple configuration profiles
- Hot-reload without application restart
- Configuration history and audit trail
- Dynamic profile switching
- Centralized configuration management

## Architecture

### Database Schema

The database consists of 6 main tables:

1. **`config_profiles`** - Configuration profiles (e.g., "production", "development")
2. **`config_ai_infra`** - AI/LLM settings (endpoint, temperature, max tokens)
3. **`config_genie_spaces`** - Databricks Genie space configurations
4. **`config_mlflow`** - MLflow experiment settings
5. **`config_prompts`** - System prompts and templates
6. **`config_history`** - Audit trail of all configuration changes

### Entity Relationships

```
config_profiles (1) ──┬── (1) config_ai_infra
                      ├── (n) config_genie_spaces
                      ├── (1) config_mlflow
                      ├── (1) config_prompts
                      └── (n) config_history
```

- One profile has exactly one AI infrastructure config
- One profile can have multiple Genie spaces (but only one default)
- One profile has exactly one MLflow config
- One profile has exactly one prompts config
- All changes are tracked in history

### Key Constraints

1. **Unique Profile Names**: Each profile must have a unique name
2. **Single Default Profile**: Only one profile can be marked as default (enforced by trigger)
3. **Single Default Genie Space**: Only one Genie space per profile can be default (enforced by trigger)
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
from src.config.database import engine, SessionLocal, get_db, get_db_session

# Engine with connection pooling
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,      # Verify connections before use
    pool_size=10,            # Maintain 10 connections
    max_overflow=20,         # Allow 20 additional connections
)
```

### Session Management

**For FastAPI routes:**
```python
from fastapi import Depends
from src.config.database import get_db

@app.get("/profiles")
def list_profiles(db: Session = Depends(get_db)):
    return db.query(ConfigProfile).all()
```

**For standalone scripts:**
```python
from src.config.database import get_db_session

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

Databricks Genie space configuration.

```python
class ConfigGenieSpace(Base):
    id: int
    profile_id: int              # Foreign key to config_profiles
    space_id: str                # Genie space ID
    space_name: str              # Display name
    description: str | None
    is_default: bool             # Only one per profile can be True
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

System prompts and templates for the LLM.

```python
class ConfigPrompts(Base):
    id: int
    profile_id: int                      # Foreign key to config_profiles
    system_prompt: str                   # Main system prompt
    slide_editing_instructions: str      # Editing mode instructions
    user_prompt_template: str            # Template for user messages
    created_at: datetime
    updated_at: datetime
```

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
    snapshot: dict | None        # Full config snapshot at time of change
    timestamp: datetime
```

## Migrations

### Alembic Setup

Migrations are managed using Alembic:

```bash
# Initialize database (first time only)
alembic upgrade head

# Create new migration
alembic revision --autogenerate -m "Description of changes"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1
```

### Migration Files

- **Location:** `alembic/versions/`
- **Initial schema:** `001_initial_schema.py`

## Database Initialization

### Default Profile

On first run, initialize the database with a default profile:

```bash
python scripts/init_database.py
```

This creates:
- A "default" profile marked as the default
- Default AI infrastructure settings
- Default Genie space configuration
- Default MLflow experiment name
- Default system prompts

### Default Values

Defined in `src/config/defaults.py`:

```python
DEFAULT_CONFIG = {
    "llm": {
        "endpoint": "databricks-claude-sonnet-4-5",
        "temperature": 0.7,
        "max_tokens": 60000,
    },
    "genie": {
        "space_id": "01effebcc2781b6bbb749077a55d31e3",
        "space_name": "Databricks Usage Analytics",
        "description": "Databricks usage data space",
    },
    "mlflow": {
        "experiment_name": "/Workspace/Users/{username}/ai-slide-generator",
    },
    "prompts": {
        "system_prompt": "...",
        "slide_editing_instructions": "...",
        "user_prompt_template": "{question}",
    },
}
```

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
- [Alembic Migration Guide](https://alembic.sqlalchemy.org/en/latest/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [Phase 1 Implementation Plan](../backend-database-implementation/PHASE_1_DATABASE_SETUP.md)

