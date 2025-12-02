"""
Singleton Databricks client for efficient connection management.

This module provides a thread-safe singleton WorkspaceClient instance
that is shared across all services.
"""

import logging
import threading
from typing import Optional

from databricks.sdk import WorkspaceClient

logger = logging.getLogger(__name__)

# Global singleton instance
_client_instance: Optional[WorkspaceClient] = None
_client_lock = threading.Lock()


class DatabricksClientError(Exception):
    """Raised when Databricks client initialization or operations fail."""

    pass


def get_databricks_client(
    force_new: bool = False,
) -> WorkspaceClient:
    """
    Get the singleton Databricks WorkspaceClient instance.

    This function implements a thread-safe singleton pattern. The client is
    initialized lazily on first call and reused for all subsequent calls.

    Args:
        force_new: If True, create a new client instance (useful for testing)

    Authentication:
        Uses environment variables (DATABRICKS_HOST, DATABRICKS_TOKEN) or
        the default Databricks authentication chain (environment, settings file, etc.)

    Returns:
        WorkspaceClient instance configured with credentials

    Raises:
        DatabricksClientError: If client initialization fails
    """
    global _client_instance

    # Fast path: return existing instance without locking
    if _client_instance is not None and not force_new:
        return _client_instance

    # Slow path: create new instance with lock
    with _client_lock:
        # Double-check pattern: another thread may have created instance
        if _client_instance is not None and not force_new:
            return _client_instance

        try:
            # Initialize client from environment variables using Databricks SDK default auth chain
            logger.info("Initializing Databricks client from environment variables")
            _client_instance = WorkspaceClient()

            # Verify connection by making a simple API call
            try:
                current_user = _client_instance.current_user.me()
                logger.info(
                    "Databricks client initialized successfully",
                    extra={
                        "user": current_user.user_name,
                        "auth_method": "environment",
                    },
                )
            except Exception as e:
                _client_instance = None
                raise DatabricksClientError(
                    f"Failed to verify Databricks connection: {e}"
                ) from e

            return _client_instance

        except DatabricksClientError:
            raise
        except Exception as e:
            _client_instance = None
            raise DatabricksClientError(
                f"Failed to initialize Databricks client: {e}"
            ) from e


def reset_client() -> None:
    """
    Reset the singleton client instance.

    This is primarily useful for testing to ensure a clean state
    between test cases.
    """
    global _client_instance
    with _client_lock:
        if _client_instance is not None:
            logger.info("Resetting Databricks client instance")
            _client_instance = None


def verify_connection() -> bool:
    """
    Verify that the Databricks connection is working.

    Returns:
        True if connection is successful, False otherwise
    """
    try:
        client = get_databricks_client()
        # Try to get current user as a simple health check
        client.current_user.me()
        return True
    except Exception as e:
        logger.error(f"Databricks connection verification failed: {e}")
        return False

