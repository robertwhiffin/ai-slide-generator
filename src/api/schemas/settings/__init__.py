"""Configuration API schemas."""
from src.api.schemas.settings.requests import (
    GenieSpaceCreate,
    GenieSpaceUpdate,
    ProfileCreate,
    ProfileCreateWithConfig,
    ProfileDuplicate,
    ProfileUpdate,
    PromptsConfigUpdate,
)
from src.api.schemas.settings.responses import (
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
    "GenieSpaceCreate",
    "GenieSpaceUpdate",
    "PromptsConfigUpdate",
    # Responses
    "ProfileSummary",
    "ProfileDetail",
    "GenieSpace",
    "PromptsConfig",
    "ErrorResponse",
    "ValidationErrorResponse",
]

