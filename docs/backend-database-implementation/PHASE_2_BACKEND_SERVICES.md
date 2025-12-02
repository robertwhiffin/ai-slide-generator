# Phase 2: Backend Services

**Duration:** Days 3-5  
**Status:** Not Started  
**Prerequisites:** Phase 1 Complete (Database & Models)

## Objectives

- Implement ProfileService for profile management
- Implement ConfigService for configuration CRUD
- Implement GenieService for Genie space management
- Implement ConfigValidator for validation logic
- Add endpoint listing functionality
- Implement configuration history tracking
- Add transaction support for atomic operations

## Files to Create

```
src/
└── services/
    └── config/
        ├── __init__.py
        ├── profile_service.py
        ├── config_service.py
        ├── genie_service.py
        └── validator.py
```

## Step-by-Step Implementation

### Step 1: Profile Service

**File:** `src/services/config/profile_service.py`

```python
"""Profile management service."""
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from src.models.config import (
    ConfigProfile,
    ConfigAIInfra,
    ConfigGenieSpace,
    ConfigMLflow,
    ConfigPrompts,
    ConfigHistory,
)
from src.core.defaults import DEFAULT_CONFIG


class ProfileService:
    """Manage configuration profiles."""

    def __init__(self, db: Session):
        self.db = db

    def list_profiles(self) -> List[ConfigProfile]:
        """Get all profiles."""
        return self.db.query(ConfigProfile).order_by(ConfigProfile.name).all()

    def get_profile(self, profile_id: int) -> Optional[ConfigProfile]:
        """
        Get profile with all configurations.
        
        Args:
            profile_id: Profile ID
            
        Returns:
            Profile with related configs loaded, or None
        """
        return (
            self.db.query(ConfigProfile)
            .options(
                joinedload(ConfigProfile.ai_infra),
                joinedload(ConfigProfile.genie_spaces),
                joinedload(ConfigProfile.mlflow),
                joinedload(ConfigProfile.prompts),
            )
            .filter(ConfigProfile.id == profile_id)
            .first()
        )

    def get_default_profile(self) -> Optional[ConfigProfile]:
        """Get default profile."""
        return (
            self.db.query(ConfigProfile)
            .options(
                joinedload(ConfigProfile.ai_infra),
                joinedload(ConfigProfile.genie_spaces),
                joinedload(ConfigProfile.mlflow),
                joinedload(ConfigProfile.prompts),
            )
            .filter(ConfigProfile.is_default == True)
            .first()
        )

    def create_profile(
            self,
            name: str,
            description: Optional[str],
            copy_from_id: Optional[int],
            user: str,
    ) -> ConfigProfile:
        """
        Create new profile.
        
        Args:
            name: Profile name
            description: Profile description
            copy_from_id: If provided, copy configs from this profile
            user: User creating the profile
            
        Returns:
            Created profile
        """
        # Create profile
        profile = ConfigProfile(
            name=name,
            description=description,
            is_default=False,
            created_by=user,
            updated_by=user,
        )
        self.db.add(profile)
        self.db.flush()

        if copy_from_id:
            # Copy from existing profile
            source_profile = self.get_profile(copy_from_id)
            if not source_profile:
                raise ValueError(f"Source profile {copy_from_id} not found")

            # Copy AI db_app_deployment
            ai_infra = ConfigAIInfra(
                profile_id=profile.id,
                llm_endpoint=source_profile.ai_infra.llm_endpoint,
                llm_temperature=source_profile.ai_infra.llm_temperature,
                llm_max_tokens=source_profile.ai_infra.llm_max_tokens,
            )
            self.db.add(ai_infra)

            # Copy Genie spaces
            for space in source_profile.genie_spaces:
                new_space = ConfigGenieSpace(
                    profile_id=profile.id,
                    space_id=space.space_id,
                    space_name=space.space_name,
                    description=space.description,
                    is_default=space.is_default,
                )
                self.db.add(new_space)

            # Copy MLflow
            mlflow = ConfigMLflow(
                profile_id=profile.id,
                experiment_name=source_profile.mlflow.experiment_name,
            )
            self.db.add(mlflow)

            # Copy prompts
            prompts = ConfigPrompts(
                profile_id=profile.id,
                system_prompt=source_profile.prompts.system_prompt,
                slide_editing_instructions=source_profile.prompts.slide_editing_instructions,
                user_prompt_template=source_profile.prompts.user_prompt_template,
            )
            self.db.add(prompts)
        else:
            # Use defaults
            ai_infra = ConfigAIInfra(
                profile_id=profile.id,
                llm_endpoint=DEFAULT_CONFIG["llm"]["endpoint"],
                llm_temperature=DEFAULT_CONFIG["llm"]["temperature"],
                llm_max_tokens=DEFAULT_CONFIG["llm"]["max_tokens"],
            )
            self.db.add(ai_infra)

            genie_space = ConfigGenieSpace(
                profile_id=profile.id,
                space_id=DEFAULT_CONFIG["genie"]["space_id"],
                space_name=DEFAULT_CONFIG["genie"]["space_name"],
                description=DEFAULT_CONFIG["genie"]["description"],
                is_default=True,
            )
            self.db.add(genie_space)

            mlflow = ConfigMLflow(
                profile_id=profile.id,
                experiment_name=DEFAULT_CONFIG["mlflow"]["experiment_name"],
            )
            self.db.add(mlflow)

            prompts = ConfigPrompts(
                profile_id=profile.id,
                system_prompt=DEFAULT_CONFIG["prompts"]["system_prompt"],
                slide_editing_instructions=DEFAULT_CONFIG["prompts"]["slide_editing_instructions"],
                user_prompt_template=DEFAULT_CONFIG["prompts"]["user_prompt_template"],
            )
            self.db.add(prompts)

        # Log creation
        history = ConfigHistory(
            profile_id=profile.id,
            domain="profile",
            action="create",
            changed_by=user,
            changes={"name": {"old": None, "new": name}},
        )
        self.db.add(history)

        self.db.commit()
        self.db.refresh(profile)

        return profile

    def update_profile(
            self,
            profile_id: int,
            name: Optional[str],
            description: Optional[str],
            user: str,
    ) -> ConfigProfile:
        """Update profile metadata."""
        profile = self.get_profile(profile_id)
        if not profile:
            raise ValueError(f"Profile {profile_id} not found")

        changes = {}

        if name and name != profile.name:
            changes["name"] = {"old": profile.name, "new": name}
            profile.name = name

        if description is not None and description != profile.description:
            changes["description"] = {"old": profile.description, "new": description}
            profile.description = description

        if changes:
            profile.updated_by = user

            history = ConfigHistory(
                profile_id=profile.id,
                domain="profile",
                action="update",
                changed_by=user,
                changes=changes,
            )
            self.db.add(history)

        self.db.commit()
        self.db.refresh(profile)

        return profile

    def delete_profile(self, profile_id: int, user: str) -> None:
        """
        Delete profile.
        
        Args:
            profile_id: Profile to delete
            user: User deleting the profile
            
        Raises:
            ValueError: If trying to delete default profile
        """
        profile = self.get_profile(profile_id)
        if not profile:
            raise ValueError(f"Profile {profile_id} not found")

        if profile.is_default:
            raise ValueError("Cannot delete default profile")

        # Log deletion before deleting
        history = ConfigHistory(
            profile_id=profile.id,
            domain="profile",
            action="delete",
            changed_by=user,
            changes={"name": {"old": profile.name, "new": None}},
        )
        self.db.add(history)
        self.db.flush()

        self.db.delete(profile)
        self.db.commit()

    def set_default_profile(self, profile_id: int, user: str) -> ConfigProfile:
        """
        Mark profile as default.
        
        Args:
            profile_id: Profile to mark as default
            user: User making the change
            
        Returns:
            Updated profile
        """
        profile = self.get_profile(profile_id)
        if not profile:
            raise ValueError(f"Profile {profile_id} not found")

        if profile.is_default:
            return profile  # Already default

        # Unmark other default profiles
        self.db.query(ConfigProfile).filter(
            ConfigProfile.is_default == True
        ).update({"is_default": False})

        # Mark this as default
        profile.is_default = True
        profile.updated_by = user

        history = ConfigHistory(
            profile_id=profile.id,
            domain="profile",
            action="set_default",
            changed_by=user,
            changes={"is_default": {"old": False, "new": True}},
        )
        self.db.add(history)

        self.db.commit()
        self.db.refresh(profile)

        return profile

    def duplicate_profile(
            self,
            profile_id: int,
            new_name: str,
            user: str,
    ) -> ConfigProfile:
        """
        Duplicate profile with new name.
        
        Args:
            profile_id: Profile to duplicate
            new_name: Name for new profile
            user: User creating the duplicate
            
        Returns:
            New profile
        """
        return self.create_profile(
            name=new_name,
            description=f"Copy of profile {profile_id}",
            copy_from_id=profile_id,
            user=user,
        )
```

---

### Step 2: Config Service

**File:** `src/services/config/config_service.py`

```python
"""Configuration service for managing settings within profiles."""
from typing import List

from databricks.sdk import WorkspaceClient
from sqlalchemy.orm import Session

from src.models.config import (
    ConfigAIInfra,
    ConfigMLflow,
    ConfigPrompts,
    ConfigHistory,
)


class ConfigService:
    """Manage configuration within profiles."""
    
    def __init__(self, db: Session):
        self.db = db
    
    # AI Infrastructure
    
    def get_ai_infra_config(self, profile_id: int) -> ConfigAIInfra:
        """Get AI db_app_deployment settings for specific profile."""
        config = self.db.query(ConfigAIInfra).filter_by(profile_id=profile_id).first()
        if not config:
            raise ValueError(f"AI db_app_deployment settings not found for profile {profile_id}")
        return config
    
    def update_ai_infra_config(
        self,
        profile_id: int,
        llm_endpoint: str = None,
        llm_temperature: float = None,
        llm_max_tokens: int = None,
        user: str = None,
    ) -> ConfigAIInfra:
        """Update AI infrastructure configuration."""
        config = self.get_ai_infra_config(profile_id)
        
        changes = {}
        
        if llm_endpoint is not None and llm_endpoint != config.llm_endpoint:
            changes["llm_endpoint"] = {"old": config.llm_endpoint, "new": llm_endpoint}
            config.llm_endpoint = llm_endpoint
        
        if llm_temperature is not None and llm_temperature != config.llm_temperature:
            changes["llm_temperature"] = {"old": float(config.llm_temperature), "new": llm_temperature}
            config.llm_temperature = llm_temperature
        
        if llm_max_tokens is not None and llm_max_tokens != config.llm_max_tokens:
            changes["llm_max_tokens"] = {"old": config.llm_max_tokens, "new": llm_max_tokens}
            config.llm_max_tokens = llm_max_tokens
        
        if changes:
            history = ConfigHistory(
                profile_id=profile_id,
                domain="ai_infra",
                action="update",
                changed_by=user or "system",
                changes=changes,
            )
            self.db.add(history)
        
        self.db.commit()
        self.db.refresh(config)
        
        return config
    
    def get_available_endpoints(self) -> List[str]:
        """
        Get list of available Databricks serving endpoints.
        Returns endpoints sorted with databricks- prefixed first.
        """
        try:
            client = WorkspaceClient()
            endpoints = client.serving_endpoints.list()
            names = [endpoint.name for endpoint in endpoints]
            
            # Sort: databricks- prefixed first, then others
            databricks_endpoints = sorted([n for n in names if n.startswith("databricks-")])
            other_endpoints = sorted([n for n in names if not n.startswith("databricks-")])
            
            return databricks_endpoints + other_endpoints
        except Exception as e:
            # Log error but don't fail
            print(f"Warning: Could not list endpoints: {e}")
            return []
    
    # MLflow
    
    def get_mlflow_config(self, profile_id: int) -> ConfigMLflow:
        """Get MLflow settings for specific profile."""
        config = self.db.query(ConfigMLflow).filter_by(profile_id=profile_id).first()
        if not config:
            raise ValueError(f"MLflow settings not found for profile {profile_id}")
        return config
    
    def update_mlflow_config(
        self,
        profile_id: int,
        experiment_name: str,
        user: str,
    ) -> ConfigMLflow:
        """Update MLflow configuration (experiment name only)."""
        config = self.get_mlflow_config(profile_id)
        
        changes = {}
        
        if experiment_name != config.experiment_name:
            changes["experiment_name"] = {"old": config.experiment_name, "new": experiment_name}
            config.experiment_name = experiment_name
        
        if changes:
            history = ConfigHistory(
                profile_id=profile_id,
                domain="mlflow",
                action="update",
                changed_by=user,
                changes=changes,
            )
            self.db.add(history)
        
        self.db.commit()
        self.db.refresh(config)
        
        return config
    
    # Prompts
    
    def get_prompts_config(self, profile_id: int) -> ConfigPrompts:
        """Get prompts settings for specific profile."""
        config = self.db.query(ConfigPrompts).filter_by(profile_id=profile_id).first()
        if not config:
            raise ValueError(f"Prompts settings not found for profile {profile_id}")
        return config
    
    def update_prompts_config(
        self,
        profile_id: int,
        system_prompt: str = None,
        slide_editing_instructions: str = None,
        user_prompt_template: str = None,
        user: str = None,
    ) -> ConfigPrompts:
        """Update prompts configuration."""
        config = self.get_prompts_config(profile_id)
        
        changes = {}
        
        if system_prompt is not None and system_prompt != config.system_prompt:
            changes["system_prompt"] = {"old": "...", "new": "..."}  # Don't log full prompts
            config.system_prompt = system_prompt
        
        if slide_editing_instructions is not None and slide_editing_instructions != config.slide_editing_instructions:
            changes["slide_editing_instructions"] = {"old": "...", "new": "..."}
            config.slide_editing_instructions = slide_editing_instructions
        
        if user_prompt_template is not None and user_prompt_template != config.user_prompt_template:
            changes["user_prompt_template"] = {"old": config.user_prompt_template, "new": user_prompt_template}
            config.user_prompt_template = user_prompt_template
        
        if changes:
            history = ConfigHistory(
                profile_id=profile_id,
                domain="prompts",
                action="update",
                changed_by=user or "system",
                changes=changes,
            )
            self.db.add(history)
        
        self.db.commit()
        self.db.refresh(config)
        
        return config
    
    # History
    
    def get_config_history(
        self,
        profile_id: int = None,
        domain: str = None,
        limit: int = 100,
    ) -> List[ConfigHistory]:
        """Get configuration change history."""
        query = self.db.query(ConfigHistory)
        
        if profile_id:
            query = query.filter(ConfigHistory.profile_id == profile_id)
        
        if domain:
            query = query.filter(ConfigHistory.domain == domain)
        
        return query.order_by(ConfigHistory.timestamp.desc()).limit(limit).all()
```

---

### Step 3: Genie Service

**File:** `src/services/config/genie_service.py`

```python
"""Genie space management service."""
from typing import List, Optional

from sqlalchemy.orm import Session

from src.models.config import ConfigGenieSpace, ConfigHistory


class GenieService:
    """Manage Genie spaces for profiles."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def list_genie_spaces(self, profile_id: int) -> List[ConfigGenieSpace]:
        """Get all Genie spaces for profile."""
        return (
            self.db.query(ConfigGenieSpace)
            .filter(ConfigGenieSpace.profile_id == profile_id)
            .order_by(ConfigGenieSpace.is_default.desc(), ConfigGenieSpace.space_name)
            .all()
        )
    
    def get_default_genie_space(self, profile_id: int) -> Optional[ConfigGenieSpace]:
        """Get default Genie space for profile."""
        return (
            self.db.query(ConfigGenieSpace)
            .filter(
                ConfigGenieSpace.profile_id == profile_id,
                ConfigGenieSpace.is_default == True,
            )
            .first()
        )
    
    def add_genie_space(
        self,
        profile_id: int,
        space_id: str,
        space_name: str,
        description: str = None,
        is_default: bool = False,
        user: str = None,
    ) -> ConfigGenieSpace:
        """Add Genie space to profile."""
        space = ConfigGenieSpace(
            profile_id=profile_id,
            space_id=space_id,
            space_name=space_name,
            description=description,
            is_default=is_default,
        )
        self.db.add(space)
        
        # Log creation
        history = ConfigHistory(
            profile_id=profile_id,
            domain="genie",
            action="create",
            changed_by=user or "system",
            changes={
                "space_id": {"old": None, "new": space_id},
                "space_name": {"old": None, "new": space_name},
            },
        )
        self.db.add(history)
        
        self.db.commit()
        self.db.refresh(space)
        
        return space
    
    def update_genie_space(
        self,
        space_id: int,
        space_name: str = None,
        description: str = None,
        user: str = None,
    ) -> ConfigGenieSpace:
        """Update Genie space metadata."""
        space = self.db.query(ConfigGenieSpace).filter_by(id=space_id).first()
        if not space:
            raise ValueError(f"Genie space {space_id} not found")
        
        changes = {}
        
        if space_name is not None and space_name != space.space_name:
            changes["space_name"] = {"old": space.space_name, "new": space_name}
            space.space_name = space_name
        
        if description is not None and description != space.description:
            changes["description"] = {"old": space.description, "new": description}
            space.description = description
        
        if changes:
            history = ConfigHistory(
                profile_id=space.profile_id,
                domain="genie",
                action="update",
                changed_by=user or "system",
                changes=changes,
            )
            self.db.add(history)
        
        self.db.commit()
        self.db.refresh(space)
        
        return space
    
    def delete_genie_space(self, space_id: int, user: str) -> None:
        """Remove Genie space from profile."""
        space = self.db.query(ConfigGenieSpace).filter_by(id=space_id).first()
        if not space:
            raise ValueError(f"Genie space {space_id} not found")
        
        if space.is_default:
            # Check if there are other spaces
            other_spaces = (
                self.db.query(ConfigGenieSpace)
                .filter(
                    ConfigGenieSpace.profile_id == space.profile_id,
                    ConfigGenieSpace.id != space_id,
                )
                .count()
            )
            
            if other_spaces == 0:
                raise ValueError("Cannot delete the only Genie space")
        
        # Log deletion
        history = ConfigHistory(
            profile_id=space.profile_id,
            domain="genie",
            action="delete",
            changed_by=user,
            changes={"space_name": {"old": space.space_name, "new": None}},
        )
        self.db.add(history)
        self.db.flush()
        
        self.db.delete(space)
        self.db.commit()
    
    def set_default_genie_space(self, space_id: int, user: str) -> ConfigGenieSpace:
        """Mark Genie space as default for its profile."""
        space = self.db.query(ConfigGenieSpace).filter_by(id=space_id).first()
        if not space:
            raise ValueError(f"Genie space {space_id} not found")
        
        if space.is_default:
            return space  # Already default
        
        # Unmark other default spaces in this profile
        self.db.query(ConfigGenieSpace).filter(
            ConfigGenieSpace.profile_id == space.profile_id,
            ConfigGenieSpace.is_default == True,
        ).update({"is_default": False})
        
        # Mark this as default
        space.is_default = True
        
        history = ConfigHistory(
            profile_id=space.profile_id,
            domain="genie",
            action="set_default",
            changed_by=user,
            changes={"is_default": {"old": False, "new": True}},
        )
        self.db.add(history)
        
        self.db.commit()
        self.db.refresh(space)
        
        return space
```

---

### Step 4: Validator Service

**File:** `src/services/config/validator.py`

```python
"""Configuration validation service."""
from dataclasses import dataclass
from typing import Optional

from databricks.sdk import WorkspaceClient


@dataclass
class ValidationResult:
    """Result of validation."""
    valid: bool
    error: Optional[str] = None


class ConfigValidator:
    """Validate configuration values."""
    
    def validate_ai_infra(
        self,
        llm_endpoint: str,
        llm_temperature: float,
        llm_max_tokens: int,
    ) -> ValidationResult:
        """
        Validate AI infrastructure configuration.
        
        Args:
            llm_endpoint: LLM endpoint name
            llm_temperature: Temperature value
            llm_max_tokens: Max tokens value
            
        Returns:
            ValidationResult
        """
        # Validate temperature range
        if not (0.0 <= llm_temperature <= 1.0):
            return ValidationResult(
                valid=False,
                error=f"Temperature must be between 0 and 1, got {llm_temperature}",
            )
        
        # Validate max tokens
        if llm_max_tokens <= 0:
            return ValidationResult(
                valid=False,
                error=f"Max tokens must be positive, got {llm_max_tokens}",
            )
        
        # Check if endpoint exists
        try:
            client = WorkspaceClient()
            endpoints = [e.name for e in client.serving_endpoints.list()]
            
            if llm_endpoint not in endpoints:
                return ValidationResult(
                    valid=False,
                    error=f"Endpoint '{llm_endpoint}' not found. Available: {', '.join(endpoints[:5])}...",
                )
        except Exception as e:
            # Don't fail validation if we can't check endpoints
            print(f"Warning: Could not validate endpoint: {e}")
        
        return ValidationResult(valid=True)
    
    def validate_genie_space(self, space_id: str) -> ValidationResult:
        """
        Validate Genie space.
        
        Args:
            space_id: Genie space ID
            
        Returns:
            ValidationResult
        """
        if not space_id or not space_id.strip():
            return ValidationResult(
                valid=False,
                error="Genie space ID cannot be empty",
            )
        
        # Could add more validation here (check if space exists)
        # For now, just basic validation
        
        return ValidationResult(valid=True)
    
    def validate_mlflow(self, experiment_name: str) -> ValidationResult:
        """
        Validate MLflow configuration.
        
        Args:
            experiment_name: Experiment name
            
        Returns:
            ValidationResult
        """
        if not experiment_name or not experiment_name.strip():
            return ValidationResult(
                valid=False,
                error="Experiment name cannot be empty",
            )
        
        # Validate format (should be a valid path)
        if not experiment_name.startswith("/"):
            return ValidationResult(
                valid=False,
                error="Experiment name must start with /",
            )
        
        return ValidationResult(valid=True)
    
    def validate_prompts(
        self,
        system_prompt: str = None,
        user_prompt_template: str = None,
    ) -> ValidationResult:
        """
        Validate prompts.
        
        Args:
            system_prompt: System prompt
            user_prompt_template: User prompt template
            
        Returns:
            ValidationResult
        """
        # Check required placeholders in user template
        if user_prompt_template is not None:
            if "{question}" not in user_prompt_template:
                return ValidationResult(
                    valid=False,
                    error="User prompt template must contain {question} placeholder",
                )
        
        # Check system prompt mentions max_slides
        if system_prompt is not None:
            if "{max_slides}" not in system_prompt:
                return ValidationResult(
                    valid=False,
                    error="System prompt should reference {max_slides} placeholder",
                )
        
        return ValidationResult(valid=True)
```

---

### Step 5: Service Package Init

**File:** `src/services/config/__init__.py`

```python
"""Configuration services."""
from src.services.config.config_service import ConfigService
from src.services.config.genie_service import GenieService
from src.services.profile_service import ProfileService
from src.services.config.validator import ConfigValidator, ValidationResult

__all__ = [
   "ProfileService",
   "ConfigService",
   "GenieService",
   "ConfigValidator",
   "ValidationResult",
]
```

---

## Testing Requirements

**File:** `tests/unit/config/test_services.py`

```python
"""Test configuration services."""
import pytest

from src.core.database import Base, engine, SessionLocal
from src.services.config import ProfileService, ConfigService, GenieService, ConfigValidator
from src.models.config import ConfigProfile


@pytest.fixture(scope="function")
def db_session():
    """Create a test database session."""
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


def test_create_profile_with_defaults(db_session):
    """Test creating profile with default configs."""
    service = ProfileService(db_session)

    profile = service.create_profile(
        name="test-profile",
        description="Test",
        copy_from_id=None,
        user="test_user",
    )

    assert profile.id is not None
    assert profile.name == "test-profile"
    assert profile.ai_infra is not None
    assert len(profile.genie_spaces) == 1
    assert profile.mlflow is not None
    assert profile.prompts is not None


def test_create_profile_copy(db_session):
    """Test creating profile by copying another."""
    service = ProfileService(db_session)

    # Create source profile
    source = service.create_profile("source", None, None, "test")

    # Copy it
    copy = service.create_profile("copy", "Copy of source", source.id, "test")

    assert copy.id != source.id
    assert copy.ai_infra.llm_endpoint == source.ai_infra.llm_endpoint
    assert len(copy.genie_spaces) == len(source.genie_spaces)


def test_set_default_profile(db_session):
    """Test setting default profile."""
    service = ProfileService(db_session)

    profile1 = service.create_profile("profile1", None, None, "test")
    profile1.is_default = True
    db_session.commit()

    profile2 = service.create_profile("profile2", None, None, "test")

    # Set profile2 as default
    service.set_default_profile(profile2.id, "test")

    db_session.refresh(profile1)
    assert not profile1.is_default
    assert profile2.is_default


def test_update_ai_infra(db_session):
    """Test updating AI db_app_deployment settings."""
    profile_service = ProfileService(db_session)
    config_service = ConfigService(db_session)

    profile = profile_service.create_profile("test", None, None, "test")

    updated = config_service.update_ai_infra_config(
        profile_id=profile.id,
        llm_temperature=0.8,
        user="test",
    )

    assert float(updated.llm_temperature) == 0.8


def test_genie_space_management(db_session):
    """Test Genie space CRUD."""
    profile_service = ProfileService(db_session)
    genie_service = GenieService(db_session)

    profile = profile_service.create_profile("test", None, None, "test")

    # Add space
    space = genie_service.add_genie_space(
        profile_id=profile.id,
        space_id="space123",
        space_name="Test Space",
        description="Test",
        is_default=False,
        user="test",
    )

    assert space.id is not None
    assert space.space_name == "Test Space"

    # List spaces
    spaces = genie_service.list_genie_spaces(profile.id)
    assert len(spaces) == 2  # Default + new one

    # Set as default
    genie_service.set_default_genie_space(space.id, "test")
    db_session.refresh(space)
    assert space.is_default


def test_validator(db_session):
    """Test configuration validator."""
    validator = ConfigValidator()

    # Valid temperature
    result = validator.validate_ai_infra("test-endpoint", 0.7, 1000)
    assert result.valid

    # Invalid temperature
    result = validator.validate_ai_infra("test-endpoint", 1.5, 1000)
    assert not result.valid
    assert "Temperature" in result.error

    # Invalid max tokens
    result = validator.validate_ai_infra("test-endpoint", 0.7, -100)
    assert not result.valid

    # Valid prompts
    result = validator.validate_prompts(
        system_prompt="Test {max_slides}",
        user_prompt_template="{question}",
    )
    assert result.valid

    # Missing placeholder
    result = validator.validate_prompts(
        user_prompt_template="No placeholder here",
    )
    assert not result.valid
```

---

## Verification Steps

1. **Run unit tests:**
   ```bash
   pytest tests/unit/settings/test_services.py -v
   ```

2. **Test profile creation:**
   ```python
   from src.core.database import get_db_session
   from src.services.config import ProfileService
   
   with get_db_session() as db:
       service = ProfileService(db)
       profile = service.create_profile("test", "Test profile", None, "admin")
       print(f"Created: {profile}")
   ```

3. **Test endpoint listing:**
   ```python
   from src.core.database import get_db_session
   from src.services.config import ConfigService
   
   with get_db_session() as db:
       service = ConfigService(db)
       endpoints = service.get_available_endpoints()
       print(f"Available endpoints: {endpoints}")
   ```

---

## Deliverables

- [ ] ProfileService implemented with all CRUD operations
- [ ] ConfigService implemented for AI infra, MLflow, prompts
- [ ] GenieService implemented for Genie space management
- [ ] ConfigValidator implemented with all validations
- [ ] Endpoint listing working (sorted correctly)
- [ ] Configuration history tracked for all changes
- [ ] Transaction support (atomic operations)
- [ ] Unit tests passing (>80% coverage)

---

## Success Criteria

1. Can create/read/update/delete profiles
2. Can copy profiles with all configurations
3. Can set default profile (only one at a time)
4. Can update AI infra, MLflow, prompts
5. Can manage multiple Genie spaces per profile
6. Endpoint listing returns sorted list
7. All changes logged in history table
8. Validation prevents invalid configurations
9. Unit tests pass

---

## Next Steps

Proceed to **Phase 3: API Endpoints** to expose services via REST API.

