"""Response schemas for configuration API."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class ProfileSummary(BaseModel):
    """Summary view of a profile."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str]
    is_default: bool
    created_at: datetime
    created_by: Optional[str]
    updated_at: datetime
    updated_by: Optional[str]


class AIInfraConfig(BaseModel):
    """AI infrastructure configuration."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    profile_id: int
    llm_endpoint: str
    llm_temperature: float
    llm_max_tokens: int
    created_at: datetime
    updated_at: datetime


class GenieSpace(BaseModel):
    """
    Genie space configuration.
    
    Each profile has exactly one Genie space.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    profile_id: int
    space_id: str
    space_name: str
    description: Optional[str]
    created_at: datetime
    updated_at: datetime


class MLflowConfig(BaseModel):
    """MLflow configuration."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    profile_id: int
    experiment_name: str
    created_at: datetime
    updated_at: datetime


class PromptsConfig(BaseModel):
    """Prompts configuration."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    profile_id: int
    system_prompt: str
    slide_editing_instructions: str
    user_prompt_template: str
    created_at: datetime
    updated_at: datetime


class ProfileDetail(BaseModel):
    """Detailed view of a profile with all configurations."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str]
    is_default: bool
    created_at: datetime
    created_by: Optional[str]
    updated_at: datetime
    updated_by: Optional[str]
    ai_infra: AIInfraConfig
    genie_spaces: List[GenieSpace]
    mlflow: MLflowConfig
    prompts: PromptsConfig


class ConfigHistoryEntry(BaseModel):
    """Configuration change history entry."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    profile_id: int
    domain: str
    action: str
    changed_by: str
    changes: dict
    timestamp: datetime


class EndpointsList(BaseModel):
    """List of available serving endpoints."""

    endpoints: List[str]


class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str
    error_type: Optional[str] = None


class ValidationErrorDetail(BaseModel):
    """Validation error detail."""

    loc: List[str]
    msg: str
    type: str


class ValidationErrorResponse(BaseModel):
    """Validation error response."""

    detail: List[ValidationErrorDetail]

