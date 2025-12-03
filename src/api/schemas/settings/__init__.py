"""Configuration API schemas."""
from src.api.schemas.settings.requests import (
    AIInfraConfigUpdate,
    GenieSpaceCreate,
    GenieSpaceUpdate,
    MLflowConfigUpdate,
    ProfileCreate,
    ProfileDuplicate,
    ProfileUpdate,
    PromptsConfigUpdate,
)
from src.api.schemas.settings.responses import (
    AIInfraConfig,
    ConfigHistoryEntry,
    EndpointsList,
    ErrorResponse,
    GenieSpace,
    MLflowConfig,
    ProfileDetail,
    ProfileSummary,
    PromptsConfig,
    ValidationErrorResponse,
)

__all__ = [
    # Requests
    "ProfileCreate",
    "ProfileUpdate",
    "ProfileDuplicate",
    "AIInfraConfigUpdate",
    "GenieSpaceCreate",
    "GenieSpaceUpdate",
    "MLflowConfigUpdate",
    "PromptsConfigUpdate",
    # Responses
    "ProfileSummary",
    "ProfileDetail",
    "AIInfraConfig",
    "GenieSpace",
    "MLflowConfig",
    "PromptsConfig",
    "ConfigHistoryEntry",
    "EndpointsList",
    "ErrorResponse",
    "ValidationErrorResponse",
]

