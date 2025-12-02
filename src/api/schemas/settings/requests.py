"""Request schemas for configuration API."""
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class ProfileCreate(BaseModel):
    """Request to create a new profile."""

    name: str = Field(..., min_length=1, max_length=100, description="Profile name")
    description: Optional[str] = Field(None, description="Profile description")
    copy_from_profile_id: Optional[int] = Field(None, description="Copy configs from this profile ID")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate profile name."""
        if not v.strip():
            raise ValueError("Profile name cannot be empty")
        return v.strip()


class ProfileUpdate(BaseModel):
    """Request to update profile metadata."""

    name: Optional[str] = Field(None, min_length=1, max_length=100, description="New profile name")
    description: Optional[str] = Field(None, description="New profile description")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        """Validate profile name if provided."""
        if v is not None and not v.strip():
            raise ValueError("Profile name cannot be empty")
        return v.strip() if v else None


class ProfileDuplicate(BaseModel):
    """Request to duplicate a profile."""

    new_name: str = Field(..., min_length=1, max_length=100, description="Name for duplicated profile")

    @field_validator("new_name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate profile name."""
        if not v.strip():
            raise ValueError("Profile name cannot be empty")
        return v.strip()


class AIInfraConfigUpdate(BaseModel):
    """Request to update AI infrastructure configuration."""

    llm_endpoint: Optional[str] = Field(None, description="LLM endpoint name")
    llm_temperature: Optional[float] = Field(None, ge=0.0, le=1.0, description="LLM temperature (0-1)")
    llm_max_tokens: Optional[int] = Field(None, gt=0, description="Max tokens (must be positive)")


class GenieSpaceCreate(BaseModel):
    """
    Request to create a Genie space.
    
    Each profile can have exactly one Genie space.
    """

    space_id: str = Field(..., min_length=1, description="Genie space ID")
    space_name: str = Field(..., min_length=1, max_length=255, description="Space display name")
    description: Optional[str] = Field(None, description="Space description")

    @field_validator("space_id", "space_name")
    @classmethod
    def validate_not_empty(cls, v: str) -> str:
        """Validate string is not empty."""
        if not v.strip():
            raise ValueError("Field cannot be empty")
        return v.strip()


class GenieSpaceUpdate(BaseModel):
    """Request to update Genie space."""

    space_name: Optional[str] = Field(None, min_length=1, max_length=255, description="New space name")
    description: Optional[str] = Field(None, description="New description")

    @field_validator("space_name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        """Validate space name if provided."""
        if v is not None and not v.strip():
            raise ValueError("Space name cannot be empty")
        return v.strip() if v else None


class MLflowConfigUpdate(BaseModel):
    """Request to update MLflow configuration."""

    experiment_name: str = Field(..., min_length=1, description="MLflow experiment name")

    @field_validator("experiment_name")
    @classmethod
    def validate_experiment_name(cls, v: str) -> str:
        """Validate experiment name."""
        if not v.strip():
            raise ValueError("Experiment name cannot be empty")
        if not v.startswith("/"):
            raise ValueError("Experiment name must start with /")
        return v.strip()


class PromptsConfigUpdate(BaseModel):
    """Request to update prompts configuration."""

    system_prompt: Optional[str] = Field(None, description="System prompt")
    slide_editing_instructions: Optional[str] = Field(None, description="Slide editing instructions")
    user_prompt_template: Optional[str] = Field(None, description="User prompt template")

    @field_validator("user_prompt_template")
    @classmethod
    def validate_user_template(cls, v: Optional[str]) -> Optional[str]:
        """Validate user prompt template has required placeholder."""
        if v is not None and "{question}" not in v:
            raise ValueError("User prompt template must contain {question} placeholder")
        return v

    @field_validator("system_prompt")
    @classmethod
    def validate_system_prompt(cls, v: Optional[str]) -> Optional[str]:
        """Validate system prompt has required placeholder."""
        if v is not None and "{max_slides}" not in v:
            raise ValueError("System prompt should reference {max_slides} placeholder")
        return v

