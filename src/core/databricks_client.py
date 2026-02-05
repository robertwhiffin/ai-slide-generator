"""
Databricks client management with dual-client architecture.

This module provides two types of WorkspaceClient:
1. System Client (singleton): Uses service principal credentials for system operations
2. User Client (request-scoped): Uses forwarded user token for Genie/LLM/MLflow

The user client is set per-request via middleware and stored in a ContextVar.

Both client types set product tracking headers for API call attribution:
- System client: product="tellr-app-system", product_version from package
- User client: product="tellr-app-{hashed_user_id}"
"""

import hashlib
import logging
import os
import threading
from contextvars import ContextVar
from typing import Optional

from databricks.sdk import WorkspaceClient

logger = logging.getLogger(__name__)

# =============================================================================
# Product Tracking Constants
# =============================================================================

PRODUCT_NAME_SYSTEM = "tellr-app-system"
PRODUCT_NAME_USER_PREFIX = "tellr-app-"


def _get_package_version() -> str:
    """
    Get the package version for product tracking.

    Tries setuptools_scm generated _version.py first, falls back to __init__.py.

    Returns:
        Version string (e.g., "0.1.0" or "0.1.0.dev0")
    """
    try:
        # Try setuptools_scm generated version first (available after build)
        from src._version import version

        return version
    except ImportError:
        pass

    try:
        # Fall back to __init__.py version
        from src import __version__

        return __version__
    except ImportError:
        pass

    # Ultimate fallback
    return "unknown"


def _hash_username(username: str) -> str:
    """
    Create a short hash of the username for product tracking.

    Extracts the local part from email addresses (before @) before hashing.
    Uses first 12 characters of SHA-256 hash for a balance of
    uniqueness and readability in logs/metrics.

    Args:
        username: User's email (e.g., "john.doe@company.com") or plain username

    Returns:
        12-character hex hash string
    """
    # Extract local part from email address
    local_part = username.split("@")[0] if "@" in username else username
    return hashlib.sha256(local_part.encode()).hexdigest()[:12]

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
            version = _get_package_version()
            logger.info(
                "Initializing system Databricks client from environment",
                extra={"product": PRODUCT_NAME_SYSTEM, "product_version": version},
            )
            _system_client = WorkspaceClient(
                product=PRODUCT_NAME_SYSTEM,
                product_version=version,
            )

            # Skip verification in development/test mode - allows local dev and tests without valid token
            if os.getenv("ENVIRONMENT") in ("development", "test"):
                logger.info("Dev/test mode: skipping Databricks connection verification")
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

    Uses a two-stage creation process:
    1. Create initial client to fetch the username
    2. Recreate client with product tracking using hashed username

    Args:
        token: User's access token from request headers

    Returns:
        WorkspaceClient configured with user's credentials and product tracking

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
        # Stage 1: Create initial client to get username
        initial_client = WorkspaceClient(
            host=host,
            token=token,
            auth_type="pat",
        )

        # Get username for product tracking
        try:
            current_user = initial_client.current_user.me()
            username = current_user.user_name or "unknown"
            user_hash = _hash_username(username)
            product_name = f"{PRODUCT_NAME_USER_PREFIX}{user_hash}"
            logger.info(
                "create_user_client: got username for product tracking",
                extra={"username": username, "user_hash": user_hash},
            )
        except Exception as e:
            # If we can't get username, use fallback product name
            logger.warning(
                f"create_user_client: couldn't get username for product tracking: {e}"
            )
            product_name = f"{PRODUCT_NAME_USER_PREFIX}unknown"

        # Stage 2: Create final client with product tracking
        version = _get_package_version()
        client = WorkspaceClient(
            host=host,
            token=token,
            auth_type="pat",
            product=product_name,
            product_version=version,
        )

        logger.warning(
            "create_user_client: client created successfully",
            extra={"product": product_name, "product_version": version},
        )
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
