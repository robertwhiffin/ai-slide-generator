"""
Databricks client management with dual-client architecture.

This module provides two types of WorkspaceClient:
1. System Client (singleton): Uses service principal credentials for system operations
2. User Client (request-scoped): Uses forwarded user token for Genie/LLM/MLflow

The user client is set per-request via middleware and stored in a ContextVar.
"""

import logging
import os
import threading
from contextvars import ContextVar
from typing import Optional

from databricks.sdk import WorkspaceClient

logger = logging.getLogger(__name__)

# =============================================================================
# System Client (Singleton - Service Principal)
# =============================================================================

# Global singleton instance for system operations
_system_client: Optional[WorkspaceClient] = None
_system_lock = threading.Lock()


class DatabricksClientError(Exception):
    """Raised when Databricks client initialization or operations fail."""

    pass


def get_system_client(force_new: bool = False) -> WorkspaceClient:
    """
    Get the system-level WorkspaceClient (service principal).

    Used for system operations like loading settings, health checks,
    and database operations. Uses environment variables for authentication.

    Args:
        force_new: If True, create a new client instance (useful for testing)

    Returns:
        WorkspaceClient instance with service principal credentials

    Raises:
        DatabricksClientError: If client initialization fails
    """
    global _system_client

    # Fast path: return existing instance without locking
    if _system_client is not None and not force_new:
        return _system_client

    # Slow path: create new instance with lock
    with _system_lock:
        # Double-check pattern: another thread may have created instance
        if _system_client is not None and not force_new:
            return _system_client

        try:
            logger.info("Initializing system Databricks client from environment")
            _system_client = WorkspaceClient()

            # Verify connection
            try:
                current_user = _system_client.current_user.me()
                logger.info(
                    "System Databricks client initialized",
                    extra={
                        "user": current_user.user_name,
                        "auth_method": "service_principal",
                    },
                )
            except Exception as e:
                _system_client = None
                raise DatabricksClientError(
                    f"Failed to verify system Databricks connection: {e}"
                ) from e

            return _system_client

        except DatabricksClientError:
            raise
        except Exception as e:
            _system_client = None
            raise DatabricksClientError(
                f"Failed to initialize system Databricks client: {e}"
            ) from e


# Backward compatibility alias
def get_databricks_client(force_new: bool = False) -> WorkspaceClient:
    """
    Alias for get_system_client() - maintains backward compatibility.

    For user-scoped operations (Genie, LLM, MLflow), use get_user_client() instead.
    """
    return get_system_client(force_new)


def reset_client() -> None:
    """
    Reset the system client instance.

    Primarily useful for testing to ensure a clean state between test cases.
    """
    global _system_client
    with _system_lock:
        if _system_client is not None:
            logger.info("Resetting system Databricks client instance")
            _system_client = None


def verify_connection() -> bool:
    """
    Verify that the system Databricks connection is working.

    Returns:
        True if connection is successful, False otherwise
    """
    try:
        client = get_system_client()
        client.current_user.me()
        return True
    except Exception as e:
        logger.error(f"System Databricks connection verification failed: {e}")
        return False


# =============================================================================
# User Client (Request-Scoped - User Token)
# =============================================================================

# Request-scoped user client stored in ContextVar
_user_client_var: ContextVar[Optional[WorkspaceClient]] = ContextVar(
    "user_client", default=None
)


def create_user_client(token: str) -> WorkspaceClient:
    """
    Create a user-scoped WorkspaceClient from forwarded token.

    Used for user-specific operations (Genie queries, LLM calls, MLflow).
    The token comes from the x-forwarded-access-token header set by
    the Databricks Apps proxy.

    Args:
        token: User's access token from request headers

    Returns:
        WorkspaceClient configured with user's credentials

    Raises:
        DatabricksClientError: If client creation fails
    """
    host = os.getenv("DATABRICKS_HOST")
    if not host:
        raise DatabricksClientError("DATABRICKS_HOST environment variable not set")

    try:
        client = WorkspaceClient(
            host=host,
            token=token,
            auth_type="pat",  # Required for user token authentication
        )
        logger.debug("Created user-scoped Databricks client")
        return client
    except Exception as e:
        raise DatabricksClientError(
            f"Failed to create user Databricks client: {e}"
        ) from e


def set_user_client(client: Optional[WorkspaceClient]) -> None:
    """
    Set the request-scoped user client.

    Called by middleware to set the user client at the start of a request
    and clear it (set to None) at the end.

    Args:
        client: User's WorkspaceClient or None to clear
    """
    _user_client_var.set(client)


def get_user_client() -> WorkspaceClient:
    """
    Get the user-scoped WorkspaceClient for Genie/LLM/MLflow operations.

    Returns the request-scoped user client if available (set by middleware),
    otherwise falls back to the system client (for local development).

    Returns:
        WorkspaceClient for user operations
    """
    client = _user_client_var.get()
    if client is not None:
        return client

    # Fallback to system client for local development
    logger.debug("No user client in context, falling back to system client")
    return get_system_client()


def reset_user_client() -> None:
    """
    Reset the user client context variable.

    Primarily useful for testing.
    """
    _user_client_var.set(None)
