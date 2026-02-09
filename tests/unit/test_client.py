"""
Unit tests for Databricks client module (dual-client architecture).

Tests both the system client (singleton, service principal) and
user client (request-scoped, user token) patterns.
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from src.core.databricks_client import (
    DatabricksClientError,
    create_user_client,
    get_databricks_client,
    get_system_client,
    get_user_client,
    reset_client,
    reset_user_client,
    set_user_client,
    verify_connection,
)


class TestSystemClient:
    """Tests for system client (service principal) functions."""

    def test_get_system_client_valid_scenarios(
        self, mock_workspace_client, mock_config_loader, mock_env_vars
    ):
        """Test system client with various valid scenarios."""
        # Test successful client creation
        client = get_system_client()
        assert client is not None
        assert client == mock_workspace_client

        # Test singleton pattern - same instance returned
        client2 = get_system_client()
        assert client is client2

        # Test backward compatibility alias
        client3 = get_databricks_client()
        assert client3 == mock_workspace_client

    def test_get_system_client_error_handling(self, mock_config_loader, mock_env_vars):
        """Test system client error handling."""
        # Test connection verification failure
        # Must set ENVIRONMENT to non-test value to trigger verification code path
        mock_client = MagicMock()
        mock_client.current_user.me.side_effect = Exception("Auth failed")

        with patch.dict("os.environ", {"ENVIRONMENT": "production"}):
            with patch("src.core.databricks_client.WorkspaceClient", return_value=mock_client):
                with pytest.raises(DatabricksClientError, match="Failed to verify"):
                    get_system_client()

        # Reset for next test
        reset_client()

        # Test initialization failure
        with patch(
            "src.core.databricks_client.WorkspaceClient",
            side_effect=Exception("Network error"),
        ):
            with pytest.raises(DatabricksClientError, match="Failed to initialize"):
                get_system_client()


class TestUserClient:
    """Tests for user client (request-scoped, user token) functions."""

    def test_get_user_client_valid_scenarios(
        self, mock_workspace_client, mock_config_loader, mock_env_vars
    ):
        """Test user client with various valid scenarios."""
        # When no user client is set, should fallback to system client
        client = get_user_client()
        assert client is not None
        assert client == mock_workspace_client  # Falls back to system

        # Test with explicitly set user client
        mock_user_client = MagicMock()
        set_user_client(mock_user_client)
        
        client = get_user_client()
        assert client is mock_user_client
        assert client is not mock_workspace_client

        # Clean up
        reset_user_client()

        # Verify fallback after reset
        client = get_user_client()
        assert client == mock_workspace_client

    def test_create_user_client_valid_scenarios(self, mock_env_vars):
        """Test user client creation with valid inputs (two-stage creation)."""
        mock_initial_client = MagicMock()
        mock_initial_client.current_user.me.return_value = MagicMock(
            user_name="test.user@company.com"
        )
        mock_final_client = MagicMock()

        with patch(
            "src.core.databricks_client.WorkspaceClient",
            side_effect=[mock_initial_client, mock_final_client],
        ) as mock_ws:
            with patch(
                "src.core.databricks_client._get_package_version", return_value="1.0.0"
            ):
                client = create_user_client("test-user-token-123")

                # Verify two-stage creation: initial client then final with product tracking
                assert mock_ws.call_count == 2

                # Stage 1: Initial client to get username
                mock_ws.assert_any_call(
                    host="https://test.cloud.databricks.com",
                    token="test-user-token-123",
                    auth_type="pat",
                )

                # Stage 2: Final client with product tracking (hashed "test.user")
                mock_ws.assert_any_call(
                    host="https://test.cloud.databricks.com",
                    token="test-user-token-123",
                    auth_type="pat",
                    product="tellr-app-07460583da32",  # SHA-256 of "test.user"[:12]
                    product_version="1.0.0",
                )
                assert client is mock_final_client

    def test_create_user_client_error_handling(self):
        """Test user client creation error handling."""
        # Test missing DATABRICKS_HOST
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(DatabricksClientError, match="DATABRICKS_HOST"):
                create_user_client("test-token")

        # Test WorkspaceClient creation failure
        with patch.dict(
            "os.environ", {"DATABRICKS_HOST": "https://test.databricks.com"}, clear=False
        ):
            with patch(
                "src.core.databricks_client.WorkspaceClient",
                side_effect=Exception("Invalid token"),
            ):
                with pytest.raises(DatabricksClientError, match="Failed to create user"):
                    create_user_client("bad-token")


class TestClientContextVarBehavior:
    """Tests for request-scoped context variable behavior."""

    def test_user_client_context_isolation(
        self, mock_workspace_client, mock_config_loader, mock_env_vars
    ):
        """Test that user client context is properly isolated."""
        # Start with no user client
        assert get_user_client() == mock_workspace_client

        # Set a user client
        mock_user = MagicMock()
        set_user_client(mock_user)
        assert get_user_client() is mock_user

        # Clear user client
        set_user_client(None)
        assert get_user_client() == mock_workspace_client

    def test_reset_user_client(self, mock_workspace_client, mock_config_loader, mock_env_vars):
        """Test reset_user_client function."""
        mock_user = MagicMock()
        set_user_client(mock_user)
        assert get_user_client() is mock_user

        reset_user_client()
        assert get_user_client() == mock_workspace_client


class TestResetClient:
    """Tests for reset_client function."""

    def test_reset_client(self, mock_workspace_client, mock_config_loader, mock_env_vars):
        """Test resetting client."""
        # Create client
        client1 = get_system_client()
        assert client1 is not None

        # Reset
        reset_client()

        # Create new client
        client2 = get_system_client()
        assert client2 is not None

    def test_reset_client_when_none(self):
        """Test resetting client when no client exists."""
        reset_client()
        # Should not raise any errors

    def test_reset_client_thread_safe(self, mock_workspace_client, mock_config_loader, mock_env_vars):
        """Test reset_client is thread-safe."""
        import threading

        get_system_client()

        errors = []

        def reset_in_thread():
            try:
                reset_client()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reset_in_thread) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


class TestVerifyConnection:
    """Tests for verify_connection function."""

    def test_verify_connection_success(
        self, mock_workspace_client, mock_config_loader, mock_env_vars
    ):
        """Test successful connection verification."""
        result = verify_connection()
        assert result is True

    def test_verify_connection_failure(self, mock_config_loader, mock_env_vars):
        """Test connection verification failure."""
        mock_client = MagicMock()
        mock_client.current_user.me.side_effect = Exception("Connection failed")

        with patch("src.core.databricks_client.WorkspaceClient", return_value=mock_client):
            # Initial call will fail, but that's expected
            try:
                get_system_client()
            except DatabricksClientError:
                pass

            # Reset and create a client that will fail on verification
            reset_client()
            with patch(
                "src.core.databricks_client.get_system_client",
                side_effect=Exception("Connection error"),
            ):
                result = verify_connection()
                assert result is False
