"""Identity provider implementations for different data sources."""

from src.services.identity_providers.workspace_provider import WorkspaceIdentityProvider
from src.services.identity_providers.local_provider import LocalIdentityProvider

__all__ = [
    "WorkspaceIdentityProvider",
    "LocalIdentityProvider",
]
