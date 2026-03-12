"""
Identity provider using the app's service principal (system client).

Users and groups are retrieved via the Workspace SCIM API using the
system client (the app's service principal).  No separate admin PATs
are required.

Falls back to the local identity table only when the system client
is unavailable (e.g. local development without Databricks).
"""

import logging
from enum import Enum
from functools import lru_cache
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def resolve_display_name(email: str) -> str:
    """Return SCIM displayName for an email, falling back to the email itself.

    No derivation or post-processing — only direct SCIM values are used.
    """
    if not email or "@" not in email:
        return email or "Unknown"
    return _resolve_cached(email)


@lru_cache(maxsize=256)
def _resolve_cached(email: str) -> str:
    try:
        provider = get_identity_provider()
        users = provider.list_users(filter_query=f'userName eq "{email}"', max_results=1)
        if users and users[0].get("displayName"):
            return users[0]["displayName"]
    except Exception:
        pass
    return email


def resolve_display_names(emails: List[str]) -> Dict[str, str]:
    """Batch-resolve emails to display names."""
    return {e: resolve_display_name(e) for e in emails if e}


class IdentityProviderMode(Enum):
    """Identity provider source mode."""
    WORKSPACE = "workspace"  # Workspace SCIM API via system client (SP)
    LOCAL = "local"          # Local Lakebase table (dev fallback)


# Singleton instance
_identity_provider: Optional["IdentityProvider"] = None


def get_identity_provider() -> "IdentityProvider":
    """Get the singleton identity provider instance."""
    global _identity_provider
    if _identity_provider is None:
        _identity_provider = IdentityProvider()
    return _identity_provider


def reset_identity_provider() -> None:
    """Reset the identity provider (for testing)."""
    global _identity_provider
    _identity_provider = None


class IdentityProvider:
    """
    Unified identity provider backed by the app's service principal.

    On initialization it tries to obtain the system WorkspaceClient.
    If successful, all user/group queries go through the Workspace
    SCIM API.  Otherwise it falls back to the local identity table.
    """

    def __init__(self):
        self._mode = self._determine_mode()
        self._provider = self._create_provider()
        logger.info(f"Identity provider initialized in {self._mode.value} mode")

    @property
    def mode(self) -> IdentityProviderMode:
        return self._mode

    def _determine_mode(self) -> IdentityProviderMode:
        """Use the system client when available, else fall back to local."""
        try:
            from src.core.databricks_client import get_system_client
            client = get_system_client()
            if client is not None:
                logger.info("System client available — using Workspace SCIM API for identity")
                return IdentityProviderMode.WORKSPACE
        except Exception as e:
            logger.warning(f"System client unavailable ({e}) — falling back to local identity table")

        return IdentityProviderMode.LOCAL

    def _create_provider(self):
        if self._mode == IdentityProviderMode.WORKSPACE:
            from src.core.databricks_client import get_system_client
            from src.services.identity_providers.workspace_provider import WorkspaceIdentityProvider
            return WorkspaceIdentityProvider(client=get_system_client())

        from src.services.identity_providers.local_provider import LocalIdentityProvider
        return LocalIdentityProvider()

    # ------------------------------------------------------------------
    # Public API — delegates to the underlying provider
    # ------------------------------------------------------------------

    def list_users(
        self,
        filter_query: Optional[str] = None,
        max_results: int = 100,
    ) -> List[dict]:
        return self._provider.list_users(filter_query=filter_query, max_results=max_results)

    def list_groups(
        self,
        filter_query: Optional[str] = None,
        max_results: int = 100,
    ) -> List[dict]:
        return self._provider.list_groups(filter_query=filter_query, max_results=max_results)

    def search_identities(
        self,
        query: str,
        include_users: bool = True,
        include_groups: bool = True,
        max_results: int = 50,
    ) -> List[dict]:
        return self._provider.search_identities(
            query=query,
            include_users=include_users,
            include_groups=include_groups,
            max_results=max_results,
        )

    def get_user_groups(self, user_id: str) -> List[str]:
        return self._provider.get_user_groups(user_id)

    def get_user_by_id(self, user_id: str) -> Optional[dict]:
        return self._provider.get_user_by_id(user_id)

    def get_group_by_id(self, group_id: str) -> Optional[dict]:
        return self._provider.get_group_by_id(group_id)

    def record_user_login(
        self,
        user_id: str,
        user_name: str,
        display_name: Optional[str] = None,
    ) -> None:
        """Record a user identity on login (populates local table as cache)."""
        try:
            from src.services.identity_providers.local_provider import LocalIdentityProvider
            local = LocalIdentityProvider()
            local.record_identity(
                identity_id=user_id,
                identity_type="USER",
                identity_name=user_name,
                display_name=display_name or user_name,
            )
        except Exception as e:
            logger.warning(f"Failed to record user login: {e}")
