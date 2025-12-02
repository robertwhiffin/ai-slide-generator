"""Tests for database-backed settings."""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.core.database import Base
from src.core.defaults import DEFAULT_CONFIG
from src.core.settings_db import get_settings, load_settings_from_database, reload_settings
from src.database.models import (
    ConfigAIInfra,
    ConfigGenieSpace,
    ConfigMLflow,
    ConfigProfile,
    ConfigPrompts,
)


@pytest.fixture(scope="function")
def test_db_engine():
    """Create test database engine with SQLite in-memory."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    
    # Create tables (excluding config_history which uses PostgreSQL-specific JSONB)
    tables_to_create = [
        table for table in Base.metadata.sorted_tables
        if table.name != 'config_history'
    ]
    
    for table in tables_to_create:
        table.create(bind=engine, checkfirst=True)
    
    # Create simplified history table for tests
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE config_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL,
                domain VARCHAR(50) NOT NULL,
                action VARCHAR(50) NOT NULL,
                changed_by VARCHAR(255) NOT NULL,
                changes TEXT NOT NULL,
                snapshot TEXT,
                timestamp DATETIME NOT NULL,
                FOREIGN KEY (profile_id) REFERENCES config_profiles (id) ON DELETE CASCADE
            )
        """))
        conn.commit()
    
    yield engine
    
    # Cleanup
    for table in reversed(tables_to_create):
        table.drop(bind=engine, checkfirst=True)
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS config_history"))
        conn.commit()
    engine.dispose()


@pytest.fixture(scope="function")
def test_db(test_db_engine):
    """Create test database session."""
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_db_engine)
    db = SessionLocal()
    
    yield db
    
    db.close()


@pytest.fixture(scope="function")
def test_profile(test_db):
    """Create a test profile with all configurations."""
    # Create profile
    profile = ConfigProfile(
        name="test-profile",
        description="Test profile",
        is_default=True,
        created_by="test",
        updated_by="test",
    )
    test_db.add(profile)
    test_db.flush()
    
    # Add AI db_app_deployment settings
    ai_infra = ConfigAIInfra(
        profile_id=profile.id,
        llm_endpoint="databricks-meta-llama-3-1-70b-instruct",
        llm_temperature=0.7,
        llm_max_tokens=4096,
    )
    test_db.add(ai_infra)
    
    # Add Genie space (one per profile)
    genie_space = ConfigGenieSpace(
        profile_id=profile.id,
        space_id="test-space-id",
        space_name="Test Space",
        description="Test data space",
    )
    test_db.add(genie_space)
    
    # Add MLflow settings
    mlflow = ConfigMLflow(
        profile_id=profile.id,
        experiment_name="/test/experiment",
    )
    test_db.add(mlflow)
    
    # Add prompts
    prompts = ConfigPrompts(
        profile_id=profile.id,
        system_prompt=DEFAULT_CONFIG["prompts"]["system_prompt"],
        slide_editing_instructions=DEFAULT_CONFIG["prompts"]["slide_editing_instructions"],
        user_prompt_template=DEFAULT_CONFIG["prompts"]["user_prompt_template"],
    )
    test_db.add(prompts)
    
    test_db.commit()
    test_db.refresh(profile)
    
    return profile


def test_load_settings_from_database(test_db, test_profile, monkeypatch):
    """Test loading settings from database."""
    # Mock get_db_session to return our test database
    def mock_get_db_session():
        class MockContextManager:
            def __enter__(self):
                return test_db
            def __exit__(self, *args):
                pass
        return MockContextManager()
    
    monkeypatch.setattr("src.settings.settings_db.get_db_session", mock_get_db_session)
    
    # Load settings
    settings = load_settings_from_database()
    
    # Verify settings loaded correctly
    assert settings.profile_id == test_profile.id
    assert settings.profile_name == "test-profile"
    assert settings.llm.endpoint == "databricks-meta-llama-3-1-70b-instruct"
    assert settings.llm.temperature == 0.7
    assert settings.llm.max_tokens == 4096
    assert settings.genie.space_id == "test-space-id"
    assert settings.mlflow.experiment_name == "/test/experiment"
    assert "{max_slides}" in settings.prompts["system_prompt"]


def test_load_settings_specific_profile(test_db, test_profile, monkeypatch):
    """Test loading settings for specific profile."""
    # Mock get_db_session
    def mock_get_db_session():
        class MockContextManager:
            def __enter__(self):
                return test_db
            def __exit__(self, *args):
                pass
        return MockContextManager()
    
    monkeypatch.setattr("src.settings.settings_db.get_db_session", mock_get_db_session)
    
    # Load specific profile
    settings = load_settings_from_database(profile_id=test_profile.id)
    
    assert settings.profile_id == test_profile.id
    assert settings.profile_name == "test-profile"


def test_load_settings_no_default_profile(test_db, monkeypatch):
    """Test error when no default profile exists."""
    # Mock get_db_session
    def mock_get_db_session():
        class MockContextManager:
            def __enter__(self):
                return test_db
            def __exit__(self, *args):
                pass
        return MockContextManager()
    
    monkeypatch.setattr("src.settings.settings_db.get_db_session", mock_get_db_session)
    
    # Should raise ValueError
    with pytest.raises(ValueError, match="No default profile found"):
        load_settings_from_database()


def test_load_settings_profile_not_found(test_db, monkeypatch):
    """Test error when specified profile doesn't exist."""
    # Mock get_db_session
    def mock_get_db_session():
        class MockContextManager:
            def __enter__(self):
                return test_db
            def __exit__(self, *args):
                pass
        return MockContextManager()
    
    monkeypatch.setattr("src.settings.settings_db.get_db_session", mock_get_db_session)
    
    # Should raise ValueError
    with pytest.raises(ValueError, match="Profile 9999 not found"):
        load_settings_from_database(profile_id=9999)


def test_settings_validation(test_db, test_profile, monkeypatch):
    """Test that Pydantic validation works on loaded settings."""
    # Mock get_db_session
    def mock_get_db_session():
        class MockContextManager:
            def __enter__(self):
                return test_db
            def __exit__(self, *args):
                pass
        return MockContextManager()
    
    monkeypatch.setattr("src.settings.settings_db.get_db_session", mock_get_db_session)
    
    settings = load_settings_from_database()
    
    # Verify Pydantic validation worked
    assert 0.0 <= settings.llm.temperature <= 2.0
    assert settings.llm.max_tokens > 0

