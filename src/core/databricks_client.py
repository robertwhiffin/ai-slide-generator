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

            # Skip verification in development mode - allows local dev without valid token
            if os.getenv("ENVIRONMENT") == "development":
                logger.info("Development mode: skipping Databricks connection verification")
                return _system_client

            # Verify connection (production/staging only)
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

    # Diagnostic logging: check if token looks like service principal ID
    client_id_env = os.getenv("DATABRICKS_CLIENT_ID", "")
    token_prefix = token[:20] if len(token) > 20 else token
    is_sp_token = client_id_env and token.startswith(client_id_env)

    logger.warning(
        "create_user_client: creating client",
        extra={
            "token_prefix": token_prefix,
            "token_length": len(token),
            "is_service_principal": is_sp_token,
            "host": host,
        },
    )

    if is_sp_token:
        logger.warning(
            "create_user_client: token appears to be service principal ID!"
        )

    try:
        client = WorkspaceClient(
            host=host,
            token=token,
            auth_type="pat",  # Required for user token authentication
        )

        logger.warning("create_user_client: client created successfully")
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
        logger.warning("get_user_client: returning user-scoped client from ContextVar")
        return client

    # Fallback to system client for local development
    logger.warning(
        "get_user_client: ContextVar empty, falling back to system client"
    )
    return get_system_client()


def reset_user_client() -> None:
    """
    Reset the user client context variable.

    Primarily useful for testing.
    """
    _user_client_var.set(None)


# =============================================================================
# Service Principal Helpers
# =============================================================================


def get_service_principal_client_id() -> Optional[str]:
    """
    Get the app service principal's client ID from environment.

    Used for constructing experiment paths in the SP's workspace folder.
    Returns None for local development (fallback to user-based paths).

    Returns:
        Client ID string or None if not set
    """
    return os.getenv("DATABRICKS_CLIENT_ID")


def get_service_principal_folder() -> Optional[str]:
    """
    Get the workspace folder path for the app service principal.

    Used as the root for per-session MLflow experiments when running
    as a Databricks App with service principal authentication.

    Returns:
        Workspace folder path like "/Workspace/Users/{client_id}" or None if
        DATABRICKS_CLIENT_ID is not set (local development)
    """
    client_id = get_service_principal_client_id()
    if not client_id:
        return None
    return f"/Workspace/Users/{client_id}"


def get_current_username() -> str:
    """
    Get the current user's username from the user client.

    Uses the request-scoped user client if available, falls back to
    system client for local development.

    Returns:
        Username string (email format)

    Raises:
        DatabricksClientError: If unable to get current user
    """
    try:
        client = get_user_client()
        current_user = client.current_user.me()
        username = current_user.user_name
        if not username:
            raise DatabricksClientError("Current user has no username")
        return username
    except Exception as e:
        raise DatabricksClientError(f"Failed to get current username: {e}") from e


def ensure_workspace_folder(folder_path: str) -> None:
    """
    Ensure a workspace folder exists, creating parent directories as needed.

    Uses the system client (service principal) to create folders, which is
    required when creating folders under the SP's home directory.

    Args:
        folder_path: Full workspace path like "/Workspace/Users/{client_id}/{username}"

    Raises:
        DatabricksClientError: If folder creation fails
    """
    from databricks.sdk.service.workspace import ImportFormat

    try:
        client = get_system_client()

        # Check if folder already exists
        try:
            client.workspace.get_status(folder_path)
            logger.debug(f"Workspace folder already exists: {folder_path}")
            return
        except Exception:
            # Folder doesn't exist, need to create it
            pass

        # Create the folder (mkdirs creates parent directories too)
        logger.info(f"Creating workspace folder: {folder_path}")
        client.workspace.mkdirs(folder_path)
        logger.info(f"Created workspace folder: {folder_path}")

    except Exception as e:
        raise DatabricksClientError(f"Failed to create workspace folder {folder_path}: {e}") from e
