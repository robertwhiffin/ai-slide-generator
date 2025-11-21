"""Test configuration models."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.config.database import Base
from src.models.config import (
    ConfigAIInfra,
    ConfigGenieSpace,
    ConfigMLflow,
    ConfigProfile,
    ConfigPrompts,
)


@pytest.fixture(scope="function")
def db_session():
    """Create a test database session with in-memory SQLite."""
    # Use SQLite in-memory database for testing
    engine = create_engine("sqlite:///:memory:")
    
    # Create tables (excluding history table which uses PostgreSQL-specific JSONB)
    tables_to_create = [
        table for table in Base.metadata.sorted_tables
        if table.name != 'config_history'
    ]
    
    for table in tables_to_create:
        table.create(bind=engine, checkfirst=True)
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    
    yield session
    
    # Cleanup
    session.close()
    for table in reversed(tables_to_create):
        table.drop(bind=engine, checkfirst=True)


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
    assert profile.is_default is False


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
    """Test that profile has proper foreign key relationships.
    
    Note: Cascade delete behavior is tested in PostgreSQL integration tests.
    SQLite doesn't enforce foreign key cascades the same way.
    """
    profile = ConfigProfile(name="test", created_by="test")
    db_session.add(profile)
    db_session.flush()
    
    profile_id = profile.id
    
    ai_infra = ConfigAIInfra(
        profile_id=profile_id,
        llm_endpoint="test-endpoint",
        llm_temperature=0.7,
        llm_max_tokens=1000,
    )
    db_session.add(ai_infra)
    db_session.commit()
    
    # Verify AI infra exists and is linked to profile
    saved_infra = db_session.query(ConfigAIInfra).filter_by(profile_id=profile_id).first()
    assert saved_infra is not None
    assert saved_infra.profile_id == profile_id
    assert saved_infra.llm_endpoint == "test-endpoint"


def test_ai_infra_relationships(db_session):
    """Test AI infrastructure relationships."""
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
    
    # Test relationship
    assert profile.ai_infra.llm_endpoint == "test-endpoint"
    assert ai_infra.profile.name == "test"


def test_genie_space_creation(db_session):
    """Test creating Genie space (one per profile)."""
    profile = ConfigProfile(name="test", created_by="test")
    db_session.add(profile)
    db_session.flush()
    
    # Each profile has exactly one Genie space
    space = ConfigGenieSpace(
        profile_id=profile.id,
        space_id="space1",
        space_name="Space 1",
    )
    db_session.add(space)
    db_session.commit()
    
    # Test relationships
    assert len(profile.genie_spaces) == 1
    assert profile.genie_spaces[0].space_name == "Space 1"


def test_mlflow_config(db_session):
    """Test MLflow configuration."""
    profile = ConfigProfile(name="test", created_by="test")
    db_session.add(profile)
    db_session.flush()
    
    mlflow = ConfigMLflow(
        profile_id=profile.id,
        experiment_name="/Users/test/experiment",
    )
    db_session.add(mlflow)
    db_session.commit()
    
    # Test relationship
    assert profile.mlflow.experiment_name == "/Users/test/experiment"
    assert mlflow.profile.name == "test"


def test_prompts_config(db_session):
    """Test prompts configuration."""
    profile = ConfigProfile(name="test", created_by="test")
    db_session.add(profile)
    db_session.flush()
    
    prompts = ConfigPrompts(
        profile_id=profile.id,
        system_prompt="System prompt",
        slide_editing_instructions="Editing instructions",
        user_prompt_template="{question}",
    )
    db_session.add(prompts)
    db_session.commit()
    
    # Test relationship
    assert profile.prompts.system_prompt == "System prompt"
    assert prompts.profile.name == "test"


def test_profile_repr(db_session):
    """Test profile string representation."""
    profile = ConfigProfile(
        name="test-profile",
        is_default=True,
        created_by="test",
    )
    db_session.add(profile)
    db_session.commit()
    
    repr_str = repr(profile)
    assert "test-profile" in repr_str
    assert "is_default=True" in repr_str


def test_ai_infra_repr(db_session):
    """Test AI infrastructure string representation."""
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
    
    repr_str = repr(ai_infra)
    assert "test-endpoint" in repr_str


def test_complete_profile_with_all_configs(db_session):
    """Test creating a complete profile with all configurations."""
    # Create profile
    profile = ConfigProfile(
        name="complete-profile",
        description="A complete profile with all configs",
        is_default=False,
        created_by="test",
    )
    db_session.add(profile)
    db_session.flush()
    
    # Add AI infrastructure
    ai_infra = ConfigAIInfra(
        profile_id=profile.id,
        llm_endpoint="databricks-claude",
        llm_temperature=0.7,
        llm_max_tokens=60000,
    )
    db_session.add(ai_infra)
    
    # Add Genie space (one per profile)
    genie_space = ConfigGenieSpace(
        profile_id=profile.id,
        space_id="space123",
        space_name="Test Space",
        description="Test Genie space",
    )
    db_session.add(genie_space)
    
    # Add MLflow config
    mlflow = ConfigMLflow(
        profile_id=profile.id,
        experiment_name="/Users/test/experiment",
    )
    db_session.add(mlflow)
    
    # Add prompts
    prompts = ConfigPrompts(
        profile_id=profile.id,
        system_prompt="Test system prompt",
        slide_editing_instructions="Test editing instructions",
        user_prompt_template="{question}",
    )
    db_session.add(prompts)
    
    db_session.commit()
    
    # Verify all relationships
    assert profile.ai_infra is not None
    assert len(profile.genie_spaces) == 1
    assert profile.mlflow is not None
    assert profile.prompts is not None
    
    # Verify data
    assert profile.ai_infra.llm_endpoint == "databricks-claude"
    assert profile.genie_spaces[0].space_name == "Test Space"
    assert profile.mlflow.experiment_name == "/Users/test/experiment"
    assert profile.prompts.system_prompt == "Test system prompt"

