"""
Account-level identity provider using Databricks Account API.

Uses the Account SCIM API to fetch users and groups across all workspaces.
Requires account admin credentials.

API Reference: https://docs.databricks.com/api/account/accountusers/list
"""

import logging
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)


class AccountIdentityError(Exception):
    """Error interacting with Databricks Account identity APIs."""
    pass


class AccountIdentityProvider:
    """
    Fetch identities from Databricks Account API.
    
    This provider uses the Account-level SCIM API which allows listing
    users and groups across the entire Databricks account (all workspaces).
    
    Environment Variables Required:
    - DATABRICKS_ACCOUNT_HOST: Account console URL (e.g., https://accounts.cloud.databricks.com)
    - DATABRICKS_ACCOUNT_ID: Your Databricks account ID
    - DATABRICKS_ACCOUNT_ADMIN_TOKEN: Account admin PAT
    """
    
    def __init__(
        self,
        account_host: str,
        account_id: str,
        token: str,
    ):
        """
        Initialize the account identity provider.
        
        Args:
            account_host: Account console URL (e.g., https://accounts.cloud.databricks.com)
            account_id: Databricks account ID
            token: Account admin PAT
        """
        self.account_host = account_host.rstrip("/")
        self.account_id = account_id
        self.token = token
        self.base_url = f"{self.account_host}/api/2.0/accounts/{self.account_id}"
        logger.info(f"AccountIdentityProvider initialized for account {account_id}")
    
    def _get_headers(self) -> dict:
        """Get headers for Account API requests."""
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/scim+json",
        }
    
    def list_users(
        self,
        filter_query: Optional[str] = None,
        max_results: int = 100,
    ) -> List[dict]:
        """
        List account users via Account SCIM API.
        
        API: GET /api/2.0/accounts/{account_id}/scim/v2/Users
        
        Args:
            filter_query: Optional SCIM filter (e.g., 'userName co "john"')
            max_results: Maximum number of results
            
        Returns:
            List of user dictionaries with id, userName, displayName, type
        """
        try:
            params = {
                "count": max_results,
            }
            if filter_query:
                params["filter"] = filter_query
            
            response = requests.get(
                f"{self.base_url}/scim/v2/Users",
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
            
            logger.debug(f"Fetched {len(users)} users from Account API")
            return users
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch users from Account API: {e}")
            raise AccountIdentityError(f"Failed to fetch users: {e}") from e
    
    def list_groups(
        self,
        filter_query: Optional[str] = None,
        max_results: int = 100,
    ) -> List[dict]:
        """
        List account groups via Account SCIM API.
        
        API: GET /api/2.0/accounts/{account_id}/scim/v2/Groups
        
        Args:
            filter_query: Optional SCIM filter (e.g., 'displayName co "admin"')
            max_results: Maximum number of results
            
        Returns:
            List of group dictionaries with id, displayName, type
        """
        try:
            params = {
                "count": max_results,
            }
            if filter_query:
                params["filter"] = filter_query
            
            response = requests.get(
                f"{self.base_url}/scim/v2/Groups",
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
            
            logger.debug(f"Fetched {len(groups)} groups from Account API")
            return groups
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch groups from Account API: {e}")
            raise AccountIdentityError(f"Failed to fetch groups: {e}") from e
    
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
            include_users: Whether to include users
            include_groups: Whether to include groups
            max_results: Maximum total results
            
        Returns:
            Combined list of matching users and groups
        """
        results = []
        
        if include_users:
            user_filter = f'userName co "{query}" or displayName co "{query}"'
            try:
                users = self.list_users(filter_query=user_filter, max_results=max_results)
                results.extend(users)
            except AccountIdentityError:
                logger.warning("Failed to search users in Account API")
        
        if include_groups:
            group_filter = f'displayName co "{query}"'
            try:
                groups = self.list_groups(filter_query=group_filter, max_results=max_results)
                results.extend(groups)
            except AccountIdentityError:
                logger.warning("Failed to search groups in Account API")
        
        # Sort by display name and limit
        results.sort(key=lambda x: x.get("displayName") or x.get("userName", ""))
        return results[:max_results]
    
    def get_user_by_id(self, user_id: str) -> Optional[dict]:
        """
        Get a specific user by ID.
        
        API: GET /api/2.0/accounts/{account_id}/scim/v2/Users/{user_id}
        
        Args:
            user_id: Databricks user ID
            
        Returns:
            User dictionary or None if not found
        """
        try:
            response = requests.get(
                f"{self.base_url}/scim/v2/Users/{user_id}",
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
            logger.error(f"Failed to get user {user_id} from Account API: {e}")
            return None
    
    def get_group_by_id(self, group_id: str) -> Optional[dict]:
        """
        Get a specific group by ID.
        
        API: GET /api/2.0/accounts/{account_id}/scim/v2/Groups/{group_id}
        
        Args:
            group_id: Databricks group ID
            
        Returns:
            Group dictionary or None if not found
        """
        try:
            response = requests.get(
                f"{self.base_url}/scim/v2/Groups/{group_id}",
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
            logger.error(f"Failed to get group {group_id} from Account API: {e}")
            return None
    
    def get_user_groups(self, user_id: str) -> List[str]:
        """
        Get list of group IDs that a user belongs to.
        
        API: GET /api/2.0/accounts/{account_id}/scim/v2/Users/{user_id}
        
        Args:
            user_id: Databricks user ID
            
        Returns:
            List of group IDs
        """
        try:
            response = requests.get(
                f"{self.base_url}/scim/v2/Users/{user_id}",
                headers=self._get_headers(),
                params={"attributes": "groups"},
                timeout=30,
            )
            if response.status_code == 404:
                logger.warning(f"User {user_id} not found in Account API")
                return []
            response.raise_for_status()
            
            data = response.json()
            groups = data.get("groups", [])
            group_ids = [g.get("value") for g in groups if g.get("value")]
            
            logger.debug(f"User {user_id} belongs to {len(group_ids)} groups (Account API)")
            return group_ids
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get groups for user {user_id} from Account API: {e}")
            return []

