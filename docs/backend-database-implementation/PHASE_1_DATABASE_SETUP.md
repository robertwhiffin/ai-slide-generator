# Phase 1: Database Setup & Models

**Duration:** Days 1-2  
**Status:** Not Started

## Objectives

- Set up PostgreSQL database schema
- Implement SQLAlchemy ORM models
- Create Alembic migrations
- Implement database connection and session management
- Create hardcoded defaults for initial setup
- Initialize database with default profile

## Prerequisites

- PostgreSQL 14+ installed and running (or Docker container)
- Python environment with SQLAlchemy 2.0+, Alembic 1.12+, psycopg2-binary

## Files to Create

```
src/
├── models/
│   └── config/
│       ├── __init__.py
│       ├── profile.py
│       ├── ai_infra.py
│       ├── genie_space.py
│       ├── mlflow.py
│       ├── prompts.py
│       └── history.py
├── config/
│   ├── database.py
│   └── defaults.py
alembic/
├── env.py
├── script.py.mako
└── versions/
    └── 001_initial_schema.py
```

## Step-by-Step Implementation

### Step 1: Database Connection Setup

**File:** `src/config/database.py`

```python
"""Database connection and session management."""
import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker

# Database URL from environment
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://localhost:5432/ai_slide_generator"
)

# Create engine
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=os.getenv("SQL_ECHO", "false").lower() == "true",
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """
    Dependency for FastAPI routes.
    Yields database session and ensures cleanup.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """
    Context manager for database sessions.
    Use in standalone scripts and services.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    """Create all tables (for development only)."""
    Base.metadata.create_all(bind=engine)
```

**Testing:**
```python
# Test database connection
from src.config.database import engine, SessionLocal

def test_database_connection():
    # Test connection
    with engine.connect() as conn:
        result = conn.execute("SELECT 1")
        assert result.fetchone()[0] == 1
    
    # Test session creation
    session = SessionLocal()
    session.close()
```

---

### Step 2: Create SQLAlchemy Models

**File:** `src/models/config/profile.py`

```python
"""Configuration profile model."""
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Integer, String, Text
from sqlalchemy.orm import relationship

from src.config.database import Base


class ConfigProfile(Base):
    """Configuration profile."""
    
    __tablename__ = "config_profiles"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True, index=True)
    description = Column(Text)
    is_default = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_by = Column(String(255))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    updated_by = Column(String(255))
    
    # Relationships
    ai_infra = relationship("ConfigAIInfra", back_populates="profile", uselist=False, cascade="all, delete-orphan")
    genie_spaces = relationship("ConfigGenieSpace", back_populates="profile", cascade="all, delete-orphan")
    mlflow = relationship("ConfigMLflow", back_populates="profile", uselist=False, cascade="all, delete-orphan")
    prompts = relationship("ConfigPrompts", back_populates="profile", uselist=False, cascade="all, delete-orphan")
    history = relationship("ConfigHistory", back_populates="profile", cascade="all, delete-orphan")
    
    # Note: single_default_profile constraint handled in migration
    
    def __repr__(self):
        return f"<ConfigProfile(id={self.id}, name='{self.name}', is_default={self.is_default})>"
```

**File:** `src/models/config/ai_infra.py`

```python
"""AI Infrastructure configuration model."""
from datetime import datetime

from sqlalchemy import Column, DateTime, DECIMAL, ForeignKey, Integer, String, CheckConstraint
from sqlalchemy.orm import relationship

from src.config.database import Base


class ConfigAIInfra(Base):
    """AI Infrastructure configuration."""
    
    __tablename__ = "config_ai_infra"
    
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("config_profiles.id", ondelete="CASCADE"), nullable=False, unique=True)
    
    # LLM settings
    llm_endpoint = Column(String(255), nullable=False)
    llm_temperature = Column(DECIMAL(3, 2), nullable=False)
    llm_max_tokens = Column(Integer, nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    profile = relationship("ConfigProfile", back_populates="ai_infra")
    
    # Constraints
    __table_args__ = (
        CheckConstraint("llm_temperature >= 0 AND llm_temperature <= 1", name="check_temperature_range"),
        CheckConstraint("llm_max_tokens > 0", name="check_max_tokens_positive"),
    )
    
    def __repr__(self):
        return f"<ConfigAIInfra(id={self.id}, profile_id={self.profile_id}, endpoint='{self.llm_endpoint}')>"
```

**File:** `src/models/config/genie_space.py`

```python
"""Genie space configuration model."""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, Index
from sqlalchemy.orm import relationship

from src.config.database import Base


class ConfigGenieSpace(Base):
    """Genie space configuration."""
    
    __tablename__ = "config_genie_spaces"
    
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("config_profiles.id", ondelete="CASCADE"), nullable=False)
    
    space_id = Column(String(255), nullable=False)
    space_name = Column(String(255), nullable=False)
    description = Column(Text)
    is_default = Column(Boolean, default=False, nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    profile = relationship("ConfigProfile", back_populates="genie_spaces")
    
    # Indexes
    __table_args__ = (
        Index("idx_config_genie_spaces_profile", "profile_id"),
        Index("idx_config_genie_spaces_default", "profile_id", "is_default", 
              postgresql_where=(is_default == True)),
        # Note: single_default_space_per_profile constraint handled in migration
    )
    
    def __repr__(self):
        return f"<ConfigGenieSpace(id={self.id}, space_name='{self.space_name}', is_default={self.is_default})>"
```

**File:** `src/models/config/mlflow.py`

```python
"""MLflow configuration model."""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from src.config.database import Base


class ConfigMLflow(Base):
    """MLflow configuration."""
    
    __tablename__ = "config_mlflow"
    
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("config_profiles.id", ondelete="CASCADE"), nullable=False, unique=True)
    
    experiment_name = Column(String(255), nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    profile = relationship("ConfigProfile", back_populates="mlflow")
    
    def __repr__(self):
        return f"<ConfigMLflow(id={self.id}, profile_id={self.profile_id}, experiment='{self.experiment_name}')>"
```

**File:** `src/models/config/prompts.py`

```python
"""Prompts configuration model."""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship

from src.config.database import Base


class ConfigPrompts(Base):
    """Prompts configuration."""
    
    __tablename__ = "config_prompts"
    
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("config_profiles.id", ondelete="CASCADE"), nullable=False, unique=True)
    
    system_prompt = Column(Text, nullable=False)
    slide_editing_instructions = Column(Text, nullable=False)
    user_prompt_template = Column(Text, nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    profile = relationship("ConfigProfile", back_populates="prompts")
    
    def __repr__(self):
        return f"<ConfigPrompts(id={self.id}, profile_id={self.profile_id})>"
```

**File:** `src/models/config/history.py`

```python
"""Configuration history model."""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from src.config.database import Base


class ConfigHistory(Base):
    """Configuration change history."""
    
    __tablename__ = "config_history"
    
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("config_profiles.id", ondelete="CASCADE"), nullable=False)
    domain = Column(String(50), nullable=False)  # 'ai_infra', 'genie', 'mlflow', 'prompts', 'profile'
    action = Column(String(50), nullable=False)  # 'create', 'update', 'delete', 'activate'
    changed_by = Column(String(255), nullable=False)
    changes = Column(JSONB, nullable=False)  # {"field": {"old": "...", "new": "..."}}
    snapshot = Column(JSONB)  # Full config snapshot at time of change
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    profile = relationship("ConfigProfile", back_populates="history")
    
    # Indexes
    __table_args__ = (
        Index("idx_config_history_profile", "profile_id"),
        Index("idx_config_history_timestamp", "timestamp", postgresql_ops={"timestamp": "DESC"}),
        Index("idx_config_history_domain", "domain"),
    )
    
    def __repr__(self):
        return f"<ConfigHistory(id={self.id}, domain='{self.domain}', action='{self.action}', timestamp={self.timestamp})>"
```

**File:** `src/models/config/__init__.py`

```python
"""Configuration models."""
from src.models.config.ai_infra import ConfigAIInfra
from src.models.config.genie_space import ConfigGenieSpace
from src.models.config.history import ConfigHistory
from src.models.config.mlflow import ConfigMLflow
from src.models.config.profile import ConfigProfile
from src.models.config.prompts import ConfigPrompts

__all__ = [
    "ConfigProfile",
    "ConfigAIInfra",
    "ConfigGenieSpace",
    "ConfigMLflow",
    "ConfigPrompts",
    "ConfigHistory",
]
```

---

### Step 3: Create Default Configuration

**File:** `src/config/defaults.py`

```python
"""Default configuration values for initial setup."""

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
        "system_prompt": """You are an expert data analyst and presentation creator with access to tools. You respond only valid HTML. Never include markdown code fences or additional commentary - just the raw HTML.

Your goal is to create compelling, data-driven slide presentations by:
1. Understanding the user's question about data
2. Using the query_genie_space tool strategically to retrieve relevant data
3. Analyzing the data to identify key insights and patterns
4. Constructing a clear, logical narrative for the presentation
5. Generating professional HTML slides with the narrative and data visualizations

Generate a maximum of {max_slides} slides.""",
        "slide_editing_instructions": """SLIDE EDITING MODE:

When you receive slide context, you are editing existing slides.
Follow these rules:
1. Return ONLY slide divs: <div class="slide">...</div>
2. You can return MORE or FEWER slides than provided
3. Each slide should be complete and self-contained
4. Maintain 1280x720 dimensions per slide""",
        "user_prompt_template": "{question}",
    },
}
```

---

### Step 4: Set Up Alembic Migrations

**Initialize Alembic:**

```bash
cd /Users/robert.whiffin/Documents/slide-generator/ai-slide-generator
alembic init alembic
```

**File:** `alembic/env.py`

```python
"""Alembic environment configuration."""
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Import all models
from src.config.database import Base
from src.models.config import (
    ConfigProfile,
    ConfigAIInfra,
    ConfigGenieSpace,
    ConfigMLflow,
    ConfigPrompts,
    ConfigHistory,
)

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target metadata for autogenerate
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

**Update:** `alembic.ini`

```ini
# Set the database URL (or use environment variable)
sqlalchemy.url = postgresql://localhost:5432/ai_slide_generator
```

**Create Initial Migration:**

```bash
alembic revision --autogenerate -m "Initial schema with config tables"
```

**Manually add constraints to generated migration:**

**File:** `alembic/versions/001_initial_schema.py` (edit after generation)

```python
# Find and add these constraints manually if not generated:

# Single default profile constraint
op.execute("""
    CREATE OR REPLACE FUNCTION check_single_default_profile()
    RETURNS TRIGGER AS $$
    BEGIN
        IF NEW.is_default = TRUE THEN
            IF EXISTS (SELECT 1 FROM config_profiles 
                      WHERE is_default = TRUE AND id != NEW.id) THEN
                RAISE EXCEPTION 'Only one profile can be default';
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
""")

op.execute("""
    CREATE TRIGGER enforce_single_default_profile
    BEFORE INSERT OR UPDATE ON config_profiles
    FOR EACH ROW EXECUTE FUNCTION check_single_default_profile();
""")

# Single default Genie space per profile constraint
op.execute("""
    CREATE OR REPLACE FUNCTION check_single_default_genie_space()
    RETURNS TRIGGER AS $$
    BEGIN
        IF NEW.is_default = TRUE THEN
            IF EXISTS (SELECT 1 FROM config_genie_spaces 
                      WHERE profile_id = NEW.profile_id 
                      AND is_default = TRUE 
                      AND id != NEW.id) THEN
                RAISE EXCEPTION 'Only one Genie space can be default per profile';
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
""")

op.execute("""
    CREATE TRIGGER enforce_single_default_genie_space
    BEFORE INSERT OR UPDATE ON config_genie_spaces
    FOR EACH ROW EXECUTE FUNCTION check_single_default_genie_space();
""")
```

**Run Migration:**

```bash
alembic upgrade head
```

---

### Step 5: Database Initialization Script

**File:** `scripts/init_database.py`

```python
"""Initialize database with default profile."""
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.config.database import get_db_session
from src.config.defaults import DEFAULT_CONFIG
from src.models.config import (
    ConfigProfile,
    ConfigAIInfra,
    ConfigGenieSpace,
    ConfigMLflow,
    ConfigPrompts,
)


def initialize_database():
    """Initialize database with default profile on first run."""
    
    with get_db_session() as db:
        # Check if any profiles exist
        existing = db.query(ConfigProfile).first()
        if existing:
            print("✓ Database already initialized")
            return
        
        print("Initializing database with default profile...")
        
        # Create default profile
        profile = ConfigProfile(
            name="default",
            description="Default configuration profile",
            is_default=True,
            created_by="system",
        )
        db.add(profile)
        db.flush()
        
        # Create AI infrastructure config
        ai_infra = ConfigAIInfra(
            profile_id=profile.id,
            llm_endpoint=DEFAULT_CONFIG["llm"]["endpoint"],
            llm_temperature=DEFAULT_CONFIG["llm"]["temperature"],
            llm_max_tokens=DEFAULT_CONFIG["llm"]["max_tokens"],
        )
        db.add(ai_infra)
        
        # Create default Genie space
        genie_space = ConfigGenieSpace(
            profile_id=profile.id,
            space_id=DEFAULT_CONFIG["genie"]["space_id"],
            space_name=DEFAULT_CONFIG["genie"]["space_name"],
            description=DEFAULT_CONFIG["genie"]["description"],
            is_default=True,
        )
        db.add(genie_space)
        
        # Create MLflow config
        # Replace {username} with actual username from environment
        username = os.getenv("USER", "default_user")
        experiment_name = DEFAULT_CONFIG["mlflow"]["experiment_name"].format(username=username)
        
        mlflow = ConfigMLflow(
            profile_id=profile.id,
            experiment_name=experiment_name,
        )
        db.add(mlflow)
        
        # Create prompts config
        prompts = ConfigPrompts(
            profile_id=profile.id,
            system_prompt=DEFAULT_CONFIG["prompts"]["system_prompt"],
            slide_editing_instructions=DEFAULT_CONFIG["prompts"]["slide_editing_instructions"],
            user_prompt_template=DEFAULT_CONFIG["prompts"]["user_prompt_template"],
        )
        db.add(prompts)
        
        db.commit()
        print(f"✓ Created default profile: {profile.name}")


if __name__ == "__main__":
    try:
        initialize_database()
    except Exception as e:
        print(f"✗ Error initializing database: {e}")
        sys.exit(1)
```

---

## Testing Requirements

### Unit Tests

**File:** `tests/unit/config/test_models.py`

```python
"""Test configuration models."""
import pytest
from sqlalchemy.exc import IntegrityError

from src.config.database import Base, engine, SessionLocal
from src.models.config import (
    ConfigProfile,
    ConfigAIInfra,
    ConfigGenieSpace,
    ConfigMLflow,
    ConfigPrompts,
)


@pytest.fixture(scope="function")
def db_session():
    """Create a test database session."""
    # Create tables
    Base.metadata.create_all(bind=engine)
    
    session = SessionLocal()
    yield session
    
    # Cleanup
    session.close()
    Base.metadata.drop_all(bind=engine)


def test_create_profile(db_session):
    """Test creating a profile."""
    profile = ConfigProfile(
        name="test-profile",
        description="Test profile",
        is_default=False,
        created_by="test",
    )
    db_session.add(profile)
    db_session.commit()
    
    assert profile.id is not None
    assert profile.name == "test-profile"


def test_unique_profile_name(db_session):
    """Test profile name uniqueness."""
    profile1 = ConfigProfile(name="test", created_by="test")
    db_session.add(profile1)
    db_session.commit()
    
    profile2 = ConfigProfile(name="test", created_by="test")
    db_session.add(profile2)
    
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_cascade_delete(db_session):
    """Test cascade delete of profile configs."""
    profile = ConfigProfile(name="test", created_by="test")
    db_session.add(profile)
    db_session.flush()
    
    ai_infra = ConfigAIInfra(
        profile_id=profile.id,
        llm_endpoint="test-endpoint",
        llm_temperature=0.7,
        llm_max_tokens=1000,
    )
    db_session.add(ai_infra)
    db_session.commit()
    
    # Delete profile
    db_session.delete(profile)
    db_session.commit()
    
    # AI infra should be deleted
    assert db_session.query(ConfigAIInfra).filter_by(profile_id=profile.id).first() is None


def test_temperature_constraint(db_session):
    """Test temperature range constraint."""
    profile = ConfigProfile(name="test", created_by="test")
    db_session.add(profile)
    db_session.flush()
    
    # Invalid temperature
    ai_infra = ConfigAIInfra(
        profile_id=profile.id,
        llm_endpoint="test",
        llm_temperature=1.5,  # Invalid
        llm_max_tokens=1000,
    )
    db_session.add(ai_infra)
    
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_default_genie_space_constraint(db_session):
    """Test only one default Genie space per profile."""
    profile = ConfigProfile(name="test", created_by="test")
    db_session.add(profile)
    db_session.flush()
    
    space1 = ConfigGenieSpace(
        profile_id=profile.id,
        space_id="space1",
        space_name="Space 1",
        is_default=True,
    )
    db_session.add(space1)
    db_session.commit()
    
    # Try to add another default space
    space2 = ConfigGenieSpace(
        profile_id=profile.id,
        space_id="space2",
        space_name="Space 2",
        is_default=True,
    )
    db_session.add(space2)
    
    with pytest.raises(IntegrityError):
        db_session.commit()
```

**Run tests:**

```bash
pytest tests/unit/config/test_models.py -v
```

---

## Verification Steps

1. **Database Connection:**
   ```bash
   python -c "from src.config.database import engine; engine.connect(); print('✓ Connected')"
   ```

2. **Run Migrations:**
   ```bash
   alembic upgrade head
   ```

3. **Initialize Database:**
   ```bash
   python scripts/init_database.py
   ```

4. **Verify Data:**
   ```bash
   psql ai_slide_generator -c "SELECT * FROM config_profiles;"
   psql ai_slide_generator -c "SELECT * FROM config_ai_infra;"
   psql ai_slide_generator -c "SELECT * FROM config_genie_spaces;"
   ```

5. **Run Tests:**
   ```bash
   pytest tests/unit/config/ -v
   ```

---

## Deliverables

- [  ] PostgreSQL database created and accessible
- [ ] All SQLAlchemy models implemented with proper relationships
- [ ] Alembic migrations created and applied
- [ ] Database constraints working (unique names, cascading deletes, single defaults)
- [ ] Default configuration values defined
- [ ] Database initialization script working
- [ ] Unit tests passing (>80% coverage)
- [ ] Database can be queried and returns default profile

---

## Success Criteria

1. Can connect to PostgreSQL database
2. All tables created with correct schema
3. Default profile exists with all configurations
4. Constraints prevent invalid data
5. Models have proper relationships and cascade behavior
6. Unit tests pass
7. Can query profile and get all related configs

---

## Next Steps

After completing Phase 1, proceed to **Phase 2: Backend Services** to implement business logic for managing configurations.

