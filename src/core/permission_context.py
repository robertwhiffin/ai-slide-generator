"""Request-scoped permission context for user identity and group memberships.

This module provides a ContextVar-based storage for the current user's:
- Databricks user ID (for matching USER-type contributors)
- Group IDs (for matching GROUP-type contributors)
- Username (for display and logging)

The middleware populates this context at the start of each request.
Group memberships are cached to avoid repeated Databricks API calls.
"""

import logging
import os
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

# Cache TTL for group memberships (5 minutes)
GROUP_CACHE_TTL_SECONDS = 300


@dataclass
class PermissionContext:
    """User permission context for the current request.
    
    Contains all identity information needed for permission checks:
    - user_id: Databricks user ID (matches identity_id for USER type)
    - user_name: Email/username (for display and fallback matching)
    - group_ids: List of Databricks group IDs user belongs to
    - fetched_at: Timestamp when group memberships were fetched (for caching)
    """
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    group_ids: List[str] = field(default_factory=list)
    fetched_at: float = 0.0
    
    @property
    def is_authenticated(self) -> bool:
        """Check if user is authenticated (has user_id or user_name)."""
        return bool(self.user_id or self.user_name)
    
    @property
    def is_cache_stale(self) -> bool:
        """Check if group membership cache is stale."""
        if self.fetched_at == 0:
            return True
        return (time.time() - self.fetched_at) > GROUP_CACHE_TTL_SECONDS


# Request-scoped context variable
_permission_context_var: ContextVar[Optional[PermissionContext]] = ContextVar(
    "permission_context", default=None
)

# In-memory cache for group memberships (keyed by user_id)
# This survives across requests for the same user
_group_cache: dict[str, tuple[List[str], float]] = {}


def set_permission_context(ctx: Optional[PermissionContext]) -> None:
    """Set the permission context for the current request.
    
    Called by middleware at the start of each request.
    
    Args:
        ctx: Permission context or None to clear
    """
    _permission_context_var.set(ctx)


def get_permission_context() -> Optional[PermissionContext]:
    """Get the permission context for the current request.
    
    Returns:
        PermissionContext or None if not set
    """
    return _permission_context_var.get()


def require_permission_context() -> PermissionContext:
    """Get the permission context or raise if not available.
    
    Returns:
        PermissionContext
        
    Raises:
        RuntimeError: If no permission context is set
    """
    ctx = _permission_context_var.get()
    if not ctx:
        raise RuntimeError("No permission context available - user not authenticated")
    return ctx


def get_cached_groups(user_id: str) -> Optional[List[str]]:
    """Get cached group memberships for a user.
    
    Args:
        user_id: Databricks user ID
        
    Returns:
        List of group IDs or None if not cached or stale
    """
    if user_id not in _group_cache:
        return None
    
    group_ids, fetched_at = _group_cache[user_id]
    if (time.time() - fetched_at) > GROUP_CACHE_TTL_SECONDS:
        # Cache is stale, remove it
        del _group_cache[user_id]
        return None
    
    return group_ids


def cache_groups(user_id: str, group_ids: List[str]) -> None:
    """Cache group memberships for a user.
    
    Args:
        user_id: Databricks user ID
        group_ids: List of group IDs
    """
    _group_cache[user_id] = (group_ids, time.time())
    logger.debug(f"Cached {len(group_ids)} groups for user {user_id}")


def clear_group_cache() -> None:
    """Clear the group membership cache.
    
    Useful for testing or when group memberships are known to have changed.
    """
    _group_cache.clear()
    logger.debug("Cleared group membership cache")


def build_permission_context(
    user_id: Optional[str],
    user_name: Optional[str],
    fetch_groups: bool = True,
) -> PermissionContext:
    """Build a permission context for a user.
    
    Fetches group memberships from Databricks if not cached.
    
    Args:
        user_id: Databricks user ID
        user_name: User's email/username
        fetch_groups: Whether to fetch group memberships (disable for dev/test)
        
    Returns:
        PermissionContext with all identity information
    """
    group_ids: List[str] = []
    fetched_at = 0.0
    
    # Skip group fetching in development/test mode or if no user_id
    if not fetch_groups or os.getenv("ENVIRONMENT") in ("development", "test"):
        logger.debug("Skipping group fetch (dev/test mode or disabled)")
    elif user_id:
        # Check cache first
        cached = get_cached_groups(user_id)
        if cached is not None:
            group_ids = cached
            logger.debug(f"Using cached groups for user {user_id}: {len(group_ids)} groups")
        else:
            # Fetch from Databricks
            try:
                from src.services.databricks_identity_service import DatabricksIdentityService
                service = DatabricksIdentityService()
                group_ids = service.get_user_groups(user_id)
                cache_groups(user_id, group_ids)
                fetched_at = time.time()
                logger.info(f"Fetched {len(group_ids)} groups for user {user_id}")
            except Exception as e:
                logger.warning(f"Failed to fetch groups for user {user_id}: {e}")
    
    return PermissionContext(
        user_id=user_id,
        user_name=user_name,
        group_ids=group_ids,
        fetched_at=fetched_at,
    )

