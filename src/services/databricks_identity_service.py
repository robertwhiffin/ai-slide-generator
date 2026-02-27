"""Service for fetching Databricks workspace identities (users and groups) via SCIM API."""
import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class DatabricksIdentityError(Exception):
    """Error interacting with Databricks identity APIs."""

    pass


def _get_databricks_credentials() -> tuple[str, str]:
    """
    Get Databricks host and token from the authenticated client.
    
    Uses the same authentication source as the rest of the app:
    1. Tries to get from system client (which handles tellr config, env vars, etc.)
    2. Falls back to environment variables if available
    
    Returns:
        Tuple of (host, token)
        
    Raises:
        DatabricksIdentityError: If credentials cannot be obtained
    """
    # First try environment variables (may be set by system client init)
    host = os.getenv("DATABRICKS_HOST", "").rstrip("/")
    token = os.getenv("DATABRICKS_TOKEN", "")
    
    if host and token:
        return host, token
    
    # Try to get from system client
    try:
        from src.core.databricks_client import get_system_client
        client = get_system_client()
        
        # Get host from client config
        host = client.config.host
        if host:
            host = host.rstrip("/")
        
        # Get token from client's authenticate method
        headers = client.config.authenticate()
        bearer = headers.get("Authorization", "")
        if bearer.startswith("Bearer "):
            token = bearer[7:]
        
        if host and token:
            return host, token
            
    except Exception as e:
        logger.warning(f"Could not get credentials from system client: {e}")
    
    # Final check
    if not host:
        raise DatabricksIdentityError("DATABRICKS_HOST not configured. Ensure you're authenticated.")
    if not token:
        raise DatabricksIdentityError("DATABRICKS_TOKEN not configured. Ensure you're authenticated.")
    
    return host, token


class DatabricksIdentityService:
    """Service for fetching users and groups from Databricks workspace via SCIM API."""

    def __init__(self, host: Optional[str] = None, token: Optional[str] = None):
        """
        Initialize the identity service.
        
        Args:
            host: Databricks workspace URL (auto-detected if not provided)
            token: Databricks token (auto-detected if not provided)
        """
        if host and token:
            self.host = host.rstrip("/")
            self.token = token
        else:
            self.host, self.token = _get_databricks_credentials()

    def _get_headers(self) -> dict:
        """Get headers for SCIM API requests."""
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/scim+json",
        }

    def list_users(
        self, 
        filter_query: Optional[str] = None,
        max_results: int = 100,
    ) -> list[dict]:
        """
        List workspace users via SCIM API.
        
        Args:
            filter_query: Optional SCIM filter (e.g., 'userName co "john"')
            max_results: Maximum number of results to return
            
        Returns:
            List of user dictionaries with id, userName, displayName
        """
        try:
            params = {
                "attributes": "id,userName,displayName",
                "count": max_results,
            }
            if filter_query:
                params["filter"] = filter_query

            response = requests.get(
                f"{self.host}/api/2.0/preview/scim/v2/Users",
                headers=self._get_headers(),
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            
            data = response.json()
            users = []
            for resource in data.get("Resources", []):
                users.append({
                    "id": resource.get("id"),
                    "userName": resource.get("userName"),
                    "displayName": resource.get("displayName", resource.get("userName")),
                    "type": "USER",
                })
            
            logger.debug(f"Fetched {len(users)} users from Databricks")
            return users
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch users from Databricks: {e}")
            raise DatabricksIdentityError(f"Failed to fetch users: {e}") from e

    def list_groups(
        self,
        filter_query: Optional[str] = None,
        max_results: int = 100,
    ) -> list[dict]:
        """
        List workspace groups via SCIM API.
        
        Args:
            filter_query: Optional SCIM filter (e.g., 'displayName co "admin"')
            max_results: Maximum number of results to return
            
        Returns:
            List of group dictionaries with id, displayName
        """
        try:
            params = {
                "attributes": "id,displayName",
                "count": max_results,
            }
            if filter_query:
                params["filter"] = filter_query

            response = requests.get(
                f"{self.host}/api/2.0/preview/scim/v2/Groups",
                headers=self._get_headers(),
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            
            data = response.json()
            groups = []
            for resource in data.get("Resources", []):
                groups.append({
                    "id": resource.get("id"),
                    "displayName": resource.get("displayName"),
                    "type": "GROUP",
                })
            
            logger.debug(f"Fetched {len(groups)} groups from Databricks")
            return groups
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch groups from Databricks: {e}")
            raise DatabricksIdentityError(f"Failed to fetch groups: {e}") from e

    def search_identities(
        self,
        query: str,
        include_users: bool = True,
        include_groups: bool = True,
        max_results: int = 50,
    ) -> list[dict]:
        """
        Search for users and groups matching a query.
        
        Args:
            query: Search string to match against names/emails
            include_users: Whether to include users in results
            include_groups: Whether to include groups in results
            max_results: Maximum total results to return
            
        Returns:
            Combined list of matching users and groups
        """
        results = []
        
        if include_users:
            # Search users by userName (email) or displayName
            user_filter = f'userName co "{query}" or displayName co "{query}"'
            try:
                users = self.list_users(filter_query=user_filter, max_results=max_results)
                results.extend(users)
            except DatabricksIdentityError:
                logger.warning("Failed to search users, continuing with groups")
        
        if include_groups:
            # Search groups by displayName
            group_filter = f'displayName co "{query}"'
            try:
                groups = self.list_groups(filter_query=group_filter, max_results=max_results)
                results.extend(groups)
            except DatabricksIdentityError:
                logger.warning("Failed to search groups")
        
        # Sort by display name and limit total results
        results.sort(key=lambda x: x.get("displayName") or x.get("userName", ""))
        return results[:max_results]

    def get_user_by_id(self, user_id: str) -> Optional[dict]:
        """
        Get a specific user by ID.
        
        Args:
            user_id: Databricks user ID
            
        Returns:
            User dictionary or None if not found
        """
        try:
            response = requests.get(
                f"{self.host}/api/2.0/preview/scim/v2/Users/{user_id}",
                headers=self._get_headers(),
                timeout=30,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            
            data = response.json()
            return {
                "id": data.get("id"),
                "userName": data.get("userName"),
                "displayName": data.get("displayName", data.get("userName")),
                "type": "USER",
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get user {user_id}: {e}")
            return None

    def get_group_by_id(self, group_id: str) -> Optional[dict]:
        """
        Get a specific group by ID.
        
        Args:
            group_id: Databricks group ID
            
        Returns:
            Group dictionary or None if not found
        """
        try:
            response = requests.get(
                f"{self.host}/api/2.0/preview/scim/v2/Groups/{group_id}",
                headers=self._get_headers(),
                timeout=30,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            
            data = response.json()
            return {
                "id": data.get("id"),
                "displayName": data.get("displayName"),
                "type": "GROUP",
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get group {group_id}: {e}")
            return None

    def get_user_groups(self, user_id: str) -> list[str]:
        """
        Get list of group IDs that a user belongs to.
        
        Args:
            user_id: Databricks user ID
            
        Returns:
            List of group IDs the user is a member of
        """
        try:
            response = requests.get(
                f"{self.host}/api/2.0/preview/scim/v2/Users/{user_id}",
                headers=self._get_headers(),
                params={"attributes": "groups"},
                timeout=30,
            )
            if response.status_code == 404:
                logger.warning(f"User {user_id} not found in Databricks")
                return []
            response.raise_for_status()
            
            data = response.json()
            groups = data.get("groups", [])
            group_ids = [g.get("value") for g in groups if g.get("value")]
            
            logger.debug(f"User {user_id} belongs to {len(group_ids)} groups")
            return group_ids
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get groups for user {user_id}: {e}")
            return []

    def get_current_user_info(self) -> Optional[dict]:
        """
        Get information about the current authenticated user.
        
        Uses the system client to get the current user's details including
        their Databricks ID which is needed for permission matching.
        
        Returns:
            Dict with id, userName, displayName, groups or None if unavailable
        """
        try:
            from src.core.databricks_client import get_user_client
            client = get_user_client()
            current_user = client.current_user.me()
            
            user_id = current_user.id
            user_name = current_user.user_name
            display_name = current_user.display_name or user_name
            
            # Get group memberships
            group_ids = self.get_user_groups(user_id) if user_id else []
            
            return {
                "id": user_id,
                "userName": user_name,
                "displayName": display_name,
                "groupIds": group_ids,
            }
        except Exception as e:
            logger.error(f"Failed to get current user info: {e}")
            return None

