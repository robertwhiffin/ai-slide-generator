"""Integration tests for configuration API endpoints."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.main import app
from src.core.database import Base, get_db
from src.core.defaults import DEFAULT_CONFIG
# Import schemas to register them with Base
from src.database.models import (  # noqa: F401
    ConfigAIInfra,
    ConfigGenieSpace,
    ConfigHistory,
    ConfigProfile,
    ConfigPrompts,
)


@pytest.fixture(scope="function")
def test_db_engine():
    """Create test database engine with SQLite in-memory."""
    # Use StaticPool to ensure all connections use the same in-memory database
    # check_same_thread=False allows SQLite to work with FastAPI TestClient threading
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
    
    # Create simplified history table for tests (TEXT instead of JSONB)
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
def db_session(test_db):
    """Alias for test_db fixture for consistency with other test files."""
    return test_db


@pytest.fixture(scope="function")
def client(test_db):
    """Create test client with dependency override."""
    def override_get_db():
        try:
            yield test_db
        finally:
            pass  # Don't close here, let test_db fixture handle it
    
    app.dependency_overrides[get_db] = override_get_db
    
    with TestClient(app) as test_client:
        yield test_client
    
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def default_profile(client):
    """Create a default profile for testing."""
    response = client.post(
        "/api/settings/profiles",
        json={
            "name": "default",
            "description": "Default profile",
            "copy_from_profile_id": None,
        }
    )
    assert response.status_code == 201
    profile = response.json()
    
    # Set as default
    response = client.post(f"/api/settings/profiles/{profile['id']}/set-default")
    assert response.status_code == 200
    
    return profile


# Profile Tests

def test_list_profiles_empty(client):
    """Test listing profiles when none exist."""
    response = client.get("/api/settings/profiles")
    assert response.status_code == 200
    assert response.json() == []


def test_create_profile_valid(client):
    """Test creating a profile with valid data."""
    response = client.post(
        "/api/settings/profiles",
        json={
            "name": "test-profile",
            "description": "Test description",
            "copy_from_profile_id": None,
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "test-profile"
    assert data["description"] == "Test description"
    assert "ai_infra" in data
    assert "genie_spaces" in data
    assert "prompts" in data


def test_get_profile_valid(client, default_profile):
    """Test getting a profile by ID."""
    response = client.get(f"/api/settings/profiles/{default_profile['id']}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == default_profile["id"]
    assert data["name"] == default_profile["name"]


def test_get_profile_not_found(client):
    """Test getting non-existent profile."""
    response = client.get("/api/settings/profiles/9999")
    assert response.status_code == 404


def test_get_default_profile_valid(client, default_profile):
    """Test getting default profile."""
    response = client.get("/api/settings/profiles/default")
    assert response.status_code == 200
    data = response.json()
    assert data["is_default"] is True
    assert data["id"] == default_profile["id"]


def test_update_profile_valid(client, default_profile):
    """Test updating profile metadata."""
    response = client.put(
        f"/api/settings/profiles/{default_profile['id']}",
        json={
            "name": "updated-name",
            "description": "Updated description",
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "updated-name"
    assert data["description"] == "Updated description"


def test_duplicate_profile_valid(client, default_profile):
    """Test duplicating a profile."""
    response = client.post(
        f"/api/settings/profiles/{default_profile['id']}/duplicate",
        json={"new_name": "duplicated-profile"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "duplicated-profile"
    assert data["ai_infra"]["llm_endpoint"] == default_profile["ai_infra"]["llm_endpoint"]


def test_delete_profile_valid(client):
    """Test deleting a non-default profile."""
    # Create profile
    response = client.post(
        "/api/settings/profiles",
        json={"name": "to-delete", "description": None, "copy_from_profile_id": None}
    )
    assert response.status_code == 201
    profile_id = response.json()["id"]
    
    # Delete it
    response = client.delete(f"/api/settings/profiles/{profile_id}")
    assert response.status_code == 204


def test_delete_default_profile_forbidden(client, default_profile):
    """Test that deleting default profile is forbidden."""
    response = client.delete(f"/api/settings/profiles/{default_profile['id']}")
    assert response.status_code == 403


# AI Infrastructure Tests

def test_get_ai_infra_config_valid(client, default_profile):
    """Test getting AI infrastructure settings."""
    response = client.get(f"/api/settings/ai-db_app_deployment/{default_profile['id']}")
    assert response.status_code == 200
    data = response.json()
    assert "llm_endpoint" in data
    assert "llm_temperature" in data
    assert "llm_max_tokens" in data


def test_update_ai_infra_config_valid(client, default_profile, monkeypatch):
    """Test updating AI infrastructure settings."""
    # Mock validator to avoid Databricks connection
    # Note: ai_infra uses ConfigValidator from src.services.validator (different from ConfigurationValidator)
    from src.services.validator import ValidationResult
    
    def mock_validate(self, endpoint, temp, tokens):
        return ValidationResult(valid=True)
    
    # Patch the method at the module where it's used
    monkeypatch.setattr(
        "src.api.routes.settings.ai_infra.ConfigValidator.validate_ai_infra", 
        mock_validate
    )
    
    response = client.put(
        f"/api/settings/ai-db_app_deployment/{default_profile['id']}",
        json={
            "llm_endpoint": "new-endpoint",
            "llm_temperature": 0.8,
            "llm_max_tokens": 2000,
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["llm_endpoint"] == "new-endpoint"
    assert data["llm_temperature"] == 0.8
    assert data["llm_max_tokens"] == 2000


def test_update_ai_infra_config_invalid_temperature(client, default_profile):
    """Test updating with invalid temperature."""
    response = client.put(
        f"/api/settings/ai-db_app_deployment/{default_profile['id']}",
        json={"llm_temperature": 1.5}  # Invalid: > 1.0
    )
    assert response.status_code == 422  # Pydantic validation error


def test_get_available_endpoints(client, monkeypatch):
    """Test getting available endpoints."""
    # Mock the service method
    from src.services.config_service import ConfigService
    
    def mock_get_endpoints(self):
        return ["databricks-meta-llama", "custom-endpoint"]
    
    monkeypatch.setattr(ConfigService, "get_available_endpoints", mock_get_endpoints)
    
    response = client.get("/api/settings/ai-db_app_deployment/endpoints/available")
    assert response.status_code == 200
    data = response.json()
    assert "endpoints" in data
    assert isinstance(data["endpoints"], list)


# Genie Space Tests
# Each profile has exactly one Genie space
# Note: Creating a profile always creates default configs including a genie space

def test_get_genie_space_404_for_nonexistent_profile(client, test_db):
    """Test getting Genie space for non-existent profile returns 404."""
    response = client.get("/api/settings/genie/9999")
    assert response.status_code == 404


def test_profile_has_no_default_genie_space(client, test_db):
    """Test that creating a profile does NOT include a default genie space."""
    # Create profile via API
    response = client.post(
        "/api/settings/profiles",
        json={
            "name": "test_default_genie",
            "description": "Profile should NOT have default genie space",
            "copy_from_profile_id": None,
        }
    )
    assert response.status_code == 201
    profile = response.json()

    # Profile should NOT have genie space by default
    assert "genie_spaces" in profile
    assert len(profile["genie_spaces"]) == 0

    # Also verify via genie endpoint - should return 404
    response = client.get(f"/api/settings/genie/{profile['id']}")
    assert response.status_code == 404


def test_add_genie_space_valid(client, default_profile):
    """Test adding a Genie space to a profile."""
    # Profile should not have a Genie space by default
    response = client.get(f"/api/settings/genie/{default_profile['id']}")
    assert response.status_code == 404

    # Add a Genie space
    response = client.post(
        f"/api/settings/genie/{default_profile['id']}",
        json={
            "space_id": "test-space-123",
            "space_name": "Test Space",
            "description": "Test description",
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert data["space_id"] == "test-space-123"
    assert data["space_name"] == "Test Space"


def test_get_genie_space_valid(client, default_profile):
    """Test getting the Genie space for a profile."""
    # First add a Genie space
    response = client.post(
        f"/api/settings/genie/{default_profile['id']}",
        json={
            "space_id": "test-space-456",
            "space_name": "Test Space for Get",
            "description": "Test",
        }
    )
    assert response.status_code == 201

    # Now get it
    response = client.get(f"/api/settings/genie/{default_profile['id']}")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)  # Single space, not list
    assert "space_id" in data


def test_update_genie_space_valid(client, default_profile):
    """Test updating the Genie space."""
    # First add a Genie space
    response = client.post(
        f"/api/settings/genie/{default_profile['id']}",
        json={
            "space_id": "test-space-789",
            "space_name": "Original Name",
            "description": "Original",
        }
    )
    assert response.status_code == 201
    space_id = response.json()["id"]

    # Update it
    response = client.put(
        f"/api/settings/genie/space/{space_id}",
        json={
            "space_name": "Updated Space Name",
            "description": "Updated description",
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["space_name"] == "Updated Space Name"


def test_delete_genie_space_valid(client, default_profile):
    """Test deleting the Genie space."""
    # First add a Genie space
    response = client.post(
        f"/api/settings/genie/{default_profile['id']}",
        json={
            "space_id": "test-space-delete",
            "space_name": "To Delete",
            "description": "Will be deleted",
        }
    )
    assert response.status_code == 201
    space_id = response.json()["id"]

    # Delete it
    response = client.delete(f"/api/settings/genie/space/{space_id}")
    assert response.status_code == 204

    # Verify it's gone
    response = client.get(f"/api/settings/genie/{default_profile['id']}")
    assert response.status_code == 404


# Prompts Tests

def test_get_prompts_config_valid(client, default_profile):
    """Test getting prompts settings."""
    response = client.get(f"/api/settings/prompts/{default_profile['id']}")
    assert response.status_code == 200
    data = response.json()
    assert "system_prompt" in data
    assert "slide_editing_instructions" in data


def test_update_prompts_config_valid(client, default_profile):
    """Test updating prompts settings."""
    response = client.put(
        f"/api/settings/prompts/{default_profile['id']}",
        json={
            "system_prompt": "Updated system prompt",
            "slide_editing_instructions": "Updated instructions",
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "Updated system prompt" in data["system_prompt"]
    assert "Updated instructions" in data["slide_editing_instructions"]

