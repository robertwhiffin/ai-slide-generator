"""Configuration API schemas."""
from src.api.schemas.settings.requests import (
    AIInfraConfigUpdate,
    GenieSpaceCreate,
    GenieSpaceUpdate,
    ProfileCreate,
    ProfileCreateWithConfig,
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
    ProfileDetail,
    ProfileSummary,
    PromptsConfig,
    ValidationErrorResponse,
)

__all__ = [
    # Requests
    "ProfileCreate",
    "ProfileCreateWithConfig",
    "ProfileUpdate",
    "ProfileDuplicate",
    "AIInfraConfigUpdate",
    "GenieSpaceCreate",
    "GenieSpaceUpdate",
    "PromptsConfigUpdate",
    # Responses
    "ProfileSummary",
    "ProfileDetail",
    "AIInfraConfig",
    "GenieSpace",
    "PromptsConfig",
    "ConfigHistoryEntry",
    "EndpointsList",
    "ErrorResponse",
    "ValidationErrorResponse",
]

