"""
Multi-source identity provider with automatic fallback.

Priority order:
1. Account Admin API (if DATABRICKS_ACCOUNT_HOST + DATABRICKS_ACCOUNT_ADMIN_TOKEN set)
2. Workspace Admin API (if DATABRICKS_WORKSPACE_ADMIN_TOKEN set)
3. Local identity table (Lakebase - always available, populated on user login)

Environment Variables:
- DATABRICKS_ACCOUNT_HOST: Account console URL (e.g., https://accounts.cloud.databricks.com)
- DATABRICKS_ACCOUNT_ID: Databricks account ID (required for account API)
- DATABRICKS_ACCOUNT_ADMIN_TOKEN: Account admin PAT for cross-workspace identity lookup
- DATABRICKS_WORKSPACE_ADMIN_TOKEN: Workspace admin PAT for workspace SCIM API
- DATABRICKS_HOST: Workspace URL (required for workspace API)
"""

import logging
import os
from enum import Enum
from typing import List, Optional

logger = logging.getLogger(__name__)


class IdentityProviderMode(Enum):
    """Identity provider source mode."""
    ACCOUNT = "account"      # Databricks Account API
    WORKSPACE = "workspace"  # Databricks Workspace SCIM API
    LOCAL = "local"          # Local Lakebase table


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
    Unified identity provider with automatic source selection.
    
    Checks environment variables and uses the highest-priority available source.
    """
    
    def __init__(self):
        """Initialize identity provider and determine the mode."""
        self._mode = self._determine_mode()
        self._provider = self._create_provider()
        logger.info(f"Identity provider initialized in {self._mode.value} mode")
    
    @property
    def mode(self) -> IdentityProviderMode:
        """Get the current identity provider mode."""
        return self._mode
    
    def _determine_mode(self) -> IdentityProviderMode:
        """
        Determine which identity source to use based on environment variables.
        
        Priority:
        1. Account API (DATABRICKS_ACCOUNT_HOST + DATABRICKS_ACCOUNT_ID + DATABRICKS_ACCOUNT_ADMIN_TOKEN)
        2. Workspace API (DATABRICKS_WORKSPACE_ADMIN_TOKEN + DATABRICKS_HOST)
        3. Local table (always available)
        """
        # Check for Account API credentials
        account_host = os.getenv("DATABRICKS_ACCOUNT_HOST")
        account_id = os.getenv("DATABRICKS_ACCOUNT_ID")
        account_token = os.getenv("DATABRICKS_ACCOUNT_ADMIN_TOKEN")
        
        if account_host and account_id and account_token:
            logger.info("Using Account API mode for identity provider")
            return IdentityProviderMode.ACCOUNT
        
        # Check for Workspace API credentials
        workspace_token = os.getenv("DATABRICKS_WORKSPACE_ADMIN_TOKEN")
        workspace_host = os.getenv("DATABRICKS_HOST")
        
        if workspace_token and workspace_host:
            logger.info("Using Workspace API mode for identity provider")
            return IdentityProviderMode.WORKSPACE
        
        # Fall back to local table
        logger.info("Using Local table mode for identity provider")
        return IdentityProviderMode.LOCAL
    
    def _create_provider(self):
        """Create the appropriate provider based on mode."""
        if self._mode == IdentityProviderMode.ACCOUNT:
            from src.services.identity_providers.account_provider import AccountIdentityProvider
            return AccountIdentityProvider(
                account_host=os.getenv("DATABRICKS_ACCOUNT_HOST"),
                account_id=os.getenv("DATABRICKS_ACCOUNT_ID"),
                token=os.getenv("DATABRICKS_ACCOUNT_ADMIN_TOKEN"),
            )
        
        elif self._mode == IdentityProviderMode.WORKSPACE:
            from src.services.identity_providers.workspace_provider import WorkspaceIdentityProvider
            return WorkspaceIdentityProvider(
                host=os.getenv("DATABRICKS_HOST"),
                token=os.getenv("DATABRICKS_WORKSPACE_ADMIN_TOKEN"),
            )
        
        else:  # LOCAL mode
            from src.services.identity_providers.local_provider import LocalIdentityProvider
            return LocalIdentityProvider()
    
    def list_users(
        self,
        filter_query: Optional[str] = None,
        max_results: int = 100,
    ) -> List[dict]:
        """
        List users from the configured identity source.
        
        Args:
            filter_query: Optional search filter
            max_results: Maximum number of results
            
        Returns:
            List of user dictionaries with id, userName, displayName, type
        """
        return self._provider.list_users(filter_query=filter_query, max_results=max_results)
    
    def list_groups(
        self,
        filter_query: Optional[str] = None,
        max_results: int = 100,
    ) -> List[dict]:
        """
        List groups from the configured identity source.
        
        Args:
            filter_query: Optional search filter
            max_results: Maximum number of results
            
        Returns:
            List of group dictionaries with id, displayName, type
        """
        return self._provider.list_groups(filter_query=filter_query, max_results=max_results)
    
    def search_identities(
        self,
        query: str,
        include_users: bool = True,
        include_groups: bool = True,
        max_results: int = 50,
    ) -> List[dict]:
        """
        Search for users and groups matching a query.
        
        Args:
            query: Search string to match against names/emails
            include_users: Whether to include users in results
            include_groups: Whether to include groups in results
            max_results: Maximum total results
            
        Returns:
            Combined list of matching users and groups
        """
        return self._provider.search_identities(
            query=query,
            include_users=include_users,
            include_groups=include_groups,
            max_results=max_results,
        )
    
    def get_user_groups(self, user_id: str) -> List[str]:
        """
        Get list of group IDs that a user belongs to.
        
        Args:
            user_id: Databricks user ID
            
        Returns:
            List of group IDs
        """
        return self._provider.get_user_groups(user_id)
    
    def get_user_by_id(self, user_id: str) -> Optional[dict]:
        """
        Get a specific user by ID.
        
        Args:
            user_id: Databricks user ID
            
        Returns:
            User dictionary or None if not found
        """
        return self._provider.get_user_by_id(user_id)
    
    def get_group_by_id(self, group_id: str) -> Optional[dict]:
        """
        Get a specific group by ID.
        
        Args:
            group_id: Databricks group ID
            
        Returns:
            Group dictionary or None if not found
        """
        return self._provider.get_group_by_id(group_id)
    
    def record_user_login(
        self,
        user_id: str,
        user_name: str,
        display_name: Optional[str] = None,
    ) -> None:
        """
        Record a user identity on login (populates local table).
        
        This is called by middleware on every successful authentication
        to ensure the local identity table is populated.
        
        Args:
            user_id: Databricks user ID
            user_name: User's email/username
            display_name: User's display name
        """
        # Always record to local table regardless of mode
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

