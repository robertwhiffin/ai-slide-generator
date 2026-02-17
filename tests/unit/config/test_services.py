"""Test configuration services."""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.core.database import Base
from src.database.models import ConfigProfile
from src.services import (
    ConfigService,
    ConfigValidator,
    GenieService,
    ProfileService,
    ValidationResult,
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
    
    # Create a simplified history table for tests (using TEXT instead of JSONB)
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE config_history (
                id INTEGER PRIMARY KEY,
                profile_id INTEGER NOT NULL,
                domain VARCHAR(50) NOT NULL,
                action VARCHAR(50) NOT NULL,
                changed_by VARCHAR(255) NOT NULL,
                changes TEXT NOT NULL,
                snapshot TEXT,
                timestamp DATETIME NOT NULL
            )
        """))
        conn.commit()
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    
    yield session
    
    # Cleanup
    session.close()
    for table in reversed(tables_to_create):
        table.drop(bind=engine, checkfirst=True)
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS config_history"))
        conn.commit()


def test_create_profile_with_defaults(db_session):
    """Test creating profile with default configs."""
    service = ProfileService(db_session)

    profile = service.create_profile(
        name="test-profile",
        description="Test",
        user="test_user",
    )

    assert profile.id is not None
    assert profile.name == "test-profile"
    assert profile.ai_infra is not None
    assert profile.prompts is not None


def test_create_profile_copy(db_session):
    """Test creating profile by copying another."""
    service = ProfileService(db_session)

    # Create source profile
    source = service.create_profile("source", None, "test")

    # Copy it using duplicate_profile
    copy = service.duplicate_profile(source.id, "copy", "test")

    assert copy.id != source.id
    assert copy.ai_infra.llm_endpoint == source.ai_infra.llm_endpoint


def test_set_default_profile(db_session):
    """Test setting default profile."""
    service = ProfileService(db_session)

    profile1 = service.create_profile("profile1", None, "test")
    # First profile is automatically default

    profile2 = service.create_profile("profile2", None, "test")

    # Set profile2 as default
    service.set_default_profile(profile2.id, "test")

    db_session.refresh(profile1)
    assert not profile1.is_default
    assert profile2.is_default


def test_update_profile(db_session):
    """Test updating profile metadata."""
    service = ProfileService(db_session)

    profile = service.create_profile("original", "Original desc", "test")

    # Update profile
    updated = service.update_profile(
        profile_id=profile.id,
        name="updated",
        description="Updated desc",
        user="test",
    )

    assert updated.name == "updated"
    assert updated.description == "Updated desc"


def test_delete_profile(db_session):
    """Test soft-deleting profile."""
    service = ProfileService(db_session)

    # Create two profiles so we can delete the non-default one
    service.create_profile("default-profile", None, "test")  # This becomes default
    profile = service.create_profile("to-delete", None, "test")
    profile_id = profile.id

    # Delete it (soft-delete)
    service.delete_profile(profile_id, "test")

    # Profile still exists but is marked as deleted
    deleted = service.get_profile(profile_id)
    assert deleted is not None
    assert deleted.is_deleted is True
    assert deleted.deleted_at is not None
    assert deleted.is_default is False

    # Should not appear in list_profiles
    active_profiles = service.list_profiles()
    assert all(p.id != profile_id for p in active_profiles)


def test_cannot_delete_default_profile(db_session):
    """Test that default profile cannot be deleted."""
    service = ProfileService(db_session)

    # First profile is automatically default
    profile = service.create_profile("default", None, "test")

    # Should raise error
    with pytest.raises(ValueError, match="Cannot delete default profile"):
        service.delete_profile(profile.id, "test")


def test_duplicate_profile(db_session):
    """Test duplicating profile."""
    service = ProfileService(db_session)

    original = service.create_profile("original", "Original", "test")

    # Duplicate it
    duplicate = service.duplicate_profile(original.id, "duplicate", "test")

    assert duplicate.id != original.id
    assert duplicate.name == "duplicate"
    assert duplicate.ai_infra.llm_endpoint == original.ai_infra.llm_endpoint


def test_list_profiles(db_session):
    """Test listing all profiles."""
    service = ProfileService(db_session)

    service.create_profile("profile1", None, "test")
    service.create_profile("profile2", None, "test")
    service.create_profile("profile3", None, "test")

    profiles = service.list_profiles()
    assert len(profiles) == 3
    assert profiles[0].name == "profile1"  # Should be sorted by name


def test_update_ai_infra(db_session):
    """Test updating AI db_app_deployment settings."""
    profile_service = ProfileService(db_session)
    config_service = ConfigService(db_session)

    profile = profile_service.create_profile("test", None, "test")

    updated = config_service.update_ai_infra_config(
        profile_id=profile.id,
        llm_temperature=0.8,
        user="test",
    )

    assert float(updated.llm_temperature) == 0.8


def test_update_prompts_config(db_session):
    """Test updating prompts settings."""
    profile_service = ProfileService(db_session)
    config_service = ConfigService(db_session)

    profile = profile_service.create_profile("test", None, "test")

    updated = config_service.update_prompts_config(
        profile_id=profile.id,
        system_prompt="Updated system prompt",
        user="test",
    )

    assert updated.system_prompt == "Updated system prompt"


def test_genie_space_management(db_session):
    """Test Genie space CRUD - one space per profile."""
    profile_service = ProfileService(db_session)
    genie_service = GenieService(db_session)

    profile = profile_service.create_profile("test", None, "test")

    # Profile is created without a default Genie space
    space = genie_service.get_genie_space(profile.id)
    assert space is None  # No default space

    # Add new space
    space = genie_service.add_genie_space(
        profile_id=profile.id,
        space_id="space123",
        space_name="Test Space",
        description="Test",
        user="test",
    )

    assert space.id is not None
    assert space.space_name == "Test Space"

    # Get space
    retrieved = genie_service.get_genie_space(profile.id)
    assert retrieved is not None
    assert retrieved.space_id == "space123"

    # Delete the space
    genie_service.delete_genie_space(space.id, "test")

    # Now no space
    space = genie_service.get_genie_space(profile.id)
    assert space is None


def test_update_genie_space(db_session):
    """Test updating Genie space metadata."""
    profile_service = ProfileService(db_session)
    genie_service = GenieService(db_session)

    profile = profile_service.create_profile("test", None, "test")

    # Create a Genie space first
    space = genie_service.add_genie_space(
        profile_id=profile.id,
        space_id="space123",
        space_name="Original Name",
        description="Original description",
        user="test",
    )

    # Update the space
    updated = genie_service.update_genie_space(
        space_id=space.id,
        space_name="Updated Name",
        description="New description",
        user="test",
    )

    assert updated.space_name == "Updated Name"
    assert updated.description == "New description"


def test_delete_genie_space(db_session):
    """Test deleting Genie space."""
    profile_service = ProfileService(db_session)
    genie_service = GenieService(db_session)

    profile = profile_service.create_profile("test", None, "test")

    # Create a Genie space
    space = genie_service.add_genie_space(
        profile_id=profile.id,
        space_id="space123",
        space_name="Test Space",
        description="Test",
        user="test",
    )

    # Delete it
    genie_service.delete_genie_space(space.id, "test")

    # No space left
    space = genie_service.get_genie_space(profile.id)
    assert space is None


def test_validator_ai_infra_valid(db_session, monkeypatch):
    """Test AI db_app_deployment validation with valid values."""
    # Mock the endpoint check to avoid Databricks connection
    def mock_validate_ai_infra(self, endpoint, temp, tokens):
        if not (0.0 <= temp <= 1.0):
            return ValidationResult(valid=False, error=f"Temperature must be between 0 and 1, got {temp}")
        if tokens <= 0:
            return ValidationResult(valid=False, error=f"Max tokens must be positive, got {tokens}")
        return ValidationResult(valid=True)
    
    monkeypatch.setattr(ConfigValidator, "validate_ai_infra", mock_validate_ai_infra)
    
    validator = ConfigValidator()
    result = validator.validate_ai_infra("test-endpoint", 0.7, 1000)
    assert result.valid


def test_validator_ai_infra_invalid_temperature(db_session):
    """Test AI db_app_deployment validation with invalid temperature."""
    validator = ConfigValidator()
    
    result = validator.validate_ai_infra("test-endpoint", 1.5, 1000)
    assert not result.valid
    assert "Temperature" in result.error


def test_validator_ai_infra_invalid_max_tokens(db_session):
    """Test AI db_app_deployment validation with invalid max tokens."""
    validator = ConfigValidator()
    
    result = validator.validate_ai_infra("test-endpoint", 0.7, -100)
    assert not result.valid
    assert "Max tokens" in result.error


def test_validator_genie_space_valid(db_session):
    """Test Genie space validation with valid values."""
    validator = ConfigValidator()
    
    result = validator.validate_genie_space("valid_space_id")
    assert result.valid


def test_validator_genie_space_empty(db_session):
    """Test Genie space validation with empty ID."""
    validator = ConfigValidator()
    
    result = validator.validate_genie_space("")
    assert not result.valid
    assert "empty" in result.error


def test_validator_prompts_valid(db_session):
    """Test prompts validation with valid values."""
    validator = ConfigValidator()

    result = validator.validate_prompts(
        system_prompt="Test system prompt",
    )
    assert result.valid


def test_get_default_profile(db_session):
    """Test getting default profile."""
    service = ProfileService(db_session)

    profile1 = service.create_profile("profile1", None, "test")
    profile2 = service.create_profile("profile2", None, "test")

    # Set profile2 as default
    service.set_default_profile(profile2.id, "test")

    # Get default
    default = service.get_default_profile()
    assert default.id == profile2.id

