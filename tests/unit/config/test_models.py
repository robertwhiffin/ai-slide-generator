"""Test configuration schemas."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.core.database import Base
from src.database.models import (
    ConfigGenieSpace,
    ConfigProfile,
    ConfigPrompts,
)


@pytest.fixture(scope="function")
def db_session():
    """Create a test database session with in-memory SQLite."""
    # Use SQLite in-memory database for testing
    engine = create_engine("sqlite:///:memory:")
    
    Base.metadata.create_all(bind=engine)

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()

    yield session

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


def test_prompts_config(db_session):
    """Test prompts configuration."""
    profile = ConfigProfile(name="test", created_by="test")
    db_session.add(profile)
    db_session.flush()

    prompts = ConfigPrompts(
        profile_id=profile.id,
        system_prompt="System prompt",
        slide_editing_instructions="Editing instructions",
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
    
    # Add Genie space (one per profile)
    genie_space = ConfigGenieSpace(
        profile_id=profile.id,
        space_id="space123",
        space_name="Test Space",
        description="Test Genie space",
    )
    db_session.add(genie_space)
    
    # Add prompts
    prompts = ConfigPrompts(
        profile_id=profile.id,
        system_prompt="Test system prompt",
        slide_editing_instructions="Test editing instructions",
    )
    db_session.add(prompts)
    
    db_session.commit()
    
    # Verify all relationships
    assert len(profile.genie_spaces) == 1
    assert profile.prompts is not None

    # Verify data
    assert profile.genie_spaces[0].space_name == "Test Space"
    assert profile.prompts.system_prompt == "Test system prompt"

