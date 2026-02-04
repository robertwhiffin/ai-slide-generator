"""User context management for access control.

Stores the current authenticated user's information in a ContextVar
for access control checks throughout the request lifecycle.
"""
import logging
from contextvars import ContextVar
from typing import Optional

from src.core.databricks_client import get_user_client

logger = logging.getLogger(__name__)

# Request-scoped current user information
_current_user_var: ContextVar[Optional[str]] = ContextVar("current_user", default=None)


def set_current_user(username: Optional[str]) -> None:
    """Set the current authenticated user for this request.
    
    Called by middleware after extracting user identity from headers.
    
    Args:
        username: User's email/username or None to clear
    """
    _current_user_var.set(username)
    if username:
        logger.info(f"Set current user context: {username}")


def get_current_user() -> Optional[str]:
    """Get the current authenticated user for this request.
    
    Returns:
        User's email/username or None if not authenticated
    """
    return _current_user_var.get()


def require_current_user() -> str:
    """Get the current user or raise an error if not authenticated.
    
    Use this in endpoints that require authentication.
    
    Returns:
        User's email/username
        
    Raises:
        PermissionError: If no authenticated user
    """
    user = get_current_user()
    if not user:
        raise PermissionError("Authentication required")
    return user


def reset_current_user() -> None:
    """Reset the current user context variable.
    
    Primarily useful for testing.
    """
    _current_user_var.set(None)


def get_current_user_from_client() -> Optional[str]:
    """Get current user's email from the user-scoped Databricks client.
    
    This queries the Databricks API to get the authenticated user's
    information from the forwarded token.
    
    Returns:
        User's email or None if unable to determine
    """
    try:
        client = get_user_client()
        current_user = client.current_user.me()
        username = current_user.user_name
        
        if username:
            logger.info(f"Retrieved current user from Databricks API: {username}")
            return username
        else:
            logger.warning("current_user.me() returned user without username")
            return None
            
    except Exception as e:
        logger.warning(f"Failed to get current user from Databricks API: {e}")
        return None
