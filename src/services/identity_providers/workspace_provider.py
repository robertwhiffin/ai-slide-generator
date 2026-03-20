"""
Workspace-level identity provider using Databricks SDK.

Uses the Workspace SCIM API via the app's service principal (system client)
to fetch users and groups. No separate admin PAT required.

API Reference: https://docs.databricks.com/api/workspace/users/list
"""

import logging
from typing import List, Optional

from databricks.sdk import WorkspaceClient

logger = logging.getLogger(__name__)


class WorkspaceIdentityError(Exception):
    """Error interacting with Databricks Workspace identity APIs."""
    pass


class WorkspaceIdentityProvider:
    """
    Fetch identities from Databricks Workspace SCIM API using the SDK.

    Accepts a WorkspaceClient (typically the app's service principal)
    instead of a raw PAT — no admin tokens required.
    """

    def __init__(self, client: WorkspaceClient):
        self._client = client
        logger.info("WorkspaceIdentityProvider initialized (SDK / system client)")

    def list_users(
        self,
        filter_query: Optional[str] = None,
        max_results: int = 100,
    ) -> List[dict]:
        """
        List workspace users via SCIM API.

        Args:
            filter_query: Optional search string (matched against userName and displayName)
            max_results: Maximum number of results

        Returns:
            List of user dictionaries with id, userName, displayName, type
        """
        try:
            kwargs: dict = {"attributes": "id,userName,displayName"}
            if filter_query:
                kwargs["filter"] = (
                    f'userName co "{filter_query}" or displayName co "{filter_query}"'
                )

            users: List[dict] = []
            for u in self._client.users.list(**kwargs):
                users.append({
                    "id": u.id,
                    "userName": u.user_name,
                    "displayName": u.display_name or u.user_name,
                    "type": "USER",
                })
                if len(users) >= max_results:
                    break

            logger.debug(f"Fetched {len(users)} users from Workspace SCIM API")
            return users

        except Exception as e:
            logger.error(f"Failed to fetch users from Workspace SCIM API: {e}")
            raise WorkspaceIdentityError(f"Failed to fetch users: {e}") from e

    def list_groups(
        self,
        filter_query: Optional[str] = None,
        max_results: int = 100,
    ) -> List[dict]:
        """
        List workspace groups via SCIM API.

        Args:
            filter_query: Optional search string (matched against displayName)
            max_results: Maximum number of results

        Returns:
            List of group dictionaries with id, displayName, type
        """
        try:
            kwargs: dict = {"attributes": "id,displayName"}
            if filter_query:
                kwargs["filter"] = f'displayName co "{filter_query}"'

            groups: List[dict] = []
            for g in self._client.groups.list(**kwargs):
                groups.append({
                    "id": g.id,
                    "displayName": g.display_name,
                    "type": "GROUP",
                })
                if len(groups) >= max_results:
                    break

            logger.debug(f"Fetched {len(groups)} groups from Workspace SCIM API")
            return groups

        except Exception as e:
            logger.error(f"Failed to fetch groups from Workspace SCIM API: {e}")
            raise WorkspaceIdentityError(f"Failed to fetch groups: {e}") from e

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
        results: List[dict] = []

        if include_users:
            try:
                users = self.list_users(filter_query=query, max_results=max_results)
                results.extend(users)
            except WorkspaceIdentityError as e:
                logger.warning(f"Failed to search users in Workspace SCIM API: {e}")

        if include_groups:
            try:
                groups = self.list_groups(filter_query=query, max_results=max_results)
                results.extend(groups)
            except WorkspaceIdentityError as e:
                logger.warning(f"Failed to search groups in Workspace SCIM API: {e}")

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
            u = self._client.users.get(user_id)
            return {
                "id": u.id,
                "userName": u.user_name,
                "displayName": u.display_name or u.user_name,
                "type": "USER",
            }
        except Exception as e:
            error_str = str(e).lower()
            if "404" in error_str or "not found" in error_str:
                return None
            logger.error(f"Failed to get user {user_id} from Workspace SCIM API: {e}")
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
            g = self._client.groups.get(group_id)
            return {
                "id": g.id,
                "displayName": g.display_name,
                "type": "GROUP",
            }
        except Exception as e:
            error_str = str(e).lower()
            if "404" in error_str or "not found" in error_str:
                return None
            logger.error(f"Failed to get group {group_id} from Workspace SCIM API: {e}")
            return None

    def get_user_groups(self, user_id: str) -> List[str]:
        """
        Get list of group IDs that a user belongs to.

        Args:
            user_id: Databricks user ID

        Returns:
            List of group IDs
        """
        try:
            u = self._client.users.get(user_id)
            if u.groups:
                return [g.value for g in u.groups if g.value]
            return []
        except Exception as e:
            error_str = str(e).lower()
            if "404" in error_str or "not found" in error_str:
                logger.warning(f"User {user_id} not found in Workspace SCIM API")
                return []
            logger.error(f"Failed to get groups for user {user_id}: {e}")
            return []
