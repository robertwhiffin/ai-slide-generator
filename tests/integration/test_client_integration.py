"""
Integration tests for Databricks client with real workspace connections.

These tests connect to an actual Databricks workspace and should be run explicitly:
    pytest tests/integration/test_client_integration.py

Requirements:
- Valid Databricks profile in ~/.databrickscfg, OR
- DATABRICKS_HOST and DATABRICKS_TOKEN environment variables set
"""

import os

import pytest

from src.config.client import (
    DatabricksClientError,
    get_databricks_client,
    reset_client,
    verify_connection,
)


def _has_databricks_credentials() -> bool:
    """Check if Databricks credentials are available."""
    # Check for environment variables
    if os.getenv("DATABRICKS_HOST") and os.getenv("DATABRICKS_TOKEN"):
        return True
    
    # Check for profile file
    profile_path = os.path.expanduser("~/.databrickscfg")
    return os.path.exists(profile_path)


# Skip all tests in this module if no credentials available
pytestmark = pytest.mark.skipif(
    not _has_databricks_credentials(),
    reason="No Databricks credentials available (no ~/.databrickscfg or env vars)"
)


@pytest.fixture(autouse=True)
def reset_client_after_test():
    """Reset client singleton after each test."""
    yield
    reset_client()


class TestDatabricksClientIntegration:
    """Integration tests for Databricks client with real connections."""

    def test_client_connection_and_authentication(self):
        """Test client connects successfully and can authenticate with various methods."""
        # Test 1: Default connection (uses profile or env vars)
        client = get_databricks_client()
        assert client is not None
        
        # Verify we can make actual API call
        current_user = client.current_user.me()
        assert current_user is not None
        assert current_user.user_name is not None
        print(f"✓ Connected as: {current_user.user_name}")
        
        # Test 2: Verify singleton pattern with real client
        reset_client()
        client1 = get_databricks_client()
        client2 = get_databricks_client()
        assert client1 is client2, "Singleton pattern should return same instance"
        
        # Test 3: Verify connection helper function
        reset_client()
        assert verify_connection() is True, "Connection verification should succeed"

    def test_client_workspace_operations(self):
        """Test client can perform basic workspace operations."""
        client = get_databricks_client()
        
        # Test current_user operations
        user = client.current_user.me()
        assert user.id is not None, "User should have an ID"
        assert user.user_name is not None, "User should have a username"
        
        # Test workspace list operation (should not raise error)
        try:
            # Just verify we can call the API, don't need to assert results. 
            current_metastore = client.metastores.current()
            print(f"✓ Workspace accessible, retrieved current metastore")
        except Exception as e:
            # Some workspaces may restrict this, just log it
            print(f"⚠ Workspace list not accessible: {e}")

    def test_client_force_new_and_reset(self):
        """Test client reset and force_new parameter work correctly."""
        # Create initial client
        client1 = get_databricks_client()
        user1 = client1.current_user.me()
        assert user1 is not None
        
        # Reset and create new client
        reset_client()
        client2 = get_databricks_client(force_new=True)
        user2 = client2.current_user.me()
        
        # Should connect to same workspace but be different client instances
        assert user2.user_name == user1.user_name
        assert client2 is not client1, "force_new should create new instance"


class TestDatabricksClientAuthenticationMethods:
    """Test different authentication methods (profile and env vars)."""

    @pytest.mark.skipif(
        not (os.getenv("DATABRICKS_HOST") and os.getenv("DATABRICKS_TOKEN")),
        reason="DATABRICKS_HOST and DATABRICKS_TOKEN environment variables not set"
    )
    def test_environment_variable_authentication(self):
        """Test authentication using environment variables."""
        # When no profile specified, should use environment variables
        client = get_databricks_client()
        assert client is not None
        
        user = client.current_user.me()
        assert user.user_name is not None
        print(f"✓ Env var auth as: {user.user_name}")


class TestDatabricksClientErrorHandling:
    """Test error handling with real client operations."""

    @pytest.mark.skipif(
        not os.path.exists(os.path.expanduser("~/.databrickscfg")),
        reason="No ~/.databrickscfg profile file available"
    )
    def test_invalid_profile_error(self):
        """Test that invalid profile name raises appropriate errors."""
        # Use a profile name that definitely doesn't exist
        with pytest.raises(DatabricksClientError, match="Failed to"):
            get_databricks_client(profile_name="nonexistent-profile-12345")

