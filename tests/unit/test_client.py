"""
Unit tests for Databricks client singleton.
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from src.core.databricks_client import (
    DatabricksClientError,
    get_databricks_client,
    reset_client,
    verify_connection,
)


class TestGetDatabricksClient:
    """Tests for get_databricks_client function."""

    def test_get_client_success(self, mock_workspace_client, mock_config_loader, mock_env_vars):
        """Test successful client creation with default settings."""
        client = get_databricks_client()
        assert client is not None
        assert client == mock_workspace_client

    def test_get_client_with_env_vars(self):
        """Test client creation with environment variables."""
        mock_client = MagicMock()
        mock_user = Mock()
        mock_user.user_name = "env_user@example.com"
        mock_client.current_user.me.return_value = mock_user

        with patch("src.settings.client.WorkspaceClient", return_value=mock_client) as mock_ws:
            client = get_databricks_client()
            
            # Verify WorkspaceClient was called with no args (uses Databricks default auth chain)
            mock_ws.assert_called_once_with()
            assert client is not None

    def test_get_client_singleton_pattern(
        self, mock_workspace_client, mock_config_loader, mock_env_vars
    ):
        """Test client uses singleton pattern."""
        client1 = get_databricks_client()
        client2 = get_databricks_client()

        # Should be the same instance
        assert client1 is client2

    def test_get_client_force_new(
        self, mock_workspace_client, mock_config_loader, mock_env_vars
    ):
        """Test force_new creates new instance."""
        client1 = get_databricks_client()

        # Reset to allow force_new to work
        reset_client()

        client2 = get_databricks_client(force_new=True)

        # Should be different instances (though both mocked)
        assert client1 is not None
        assert client2 is not None

    def test_get_client_verifies_connection(
        self, mock_config_loader, mock_env_vars
    ):
        """Test client initialization verifies connection."""
        mock_client = MagicMock()
        mock_user = Mock()
        mock_user.user_name = "test@example.com"
        mock_client.current_user.me.return_value = mock_user

        with patch("src.settings.client.WorkspaceClient", return_value=mock_client):
            client = get_databricks_client()
            # Verify that current_user.me() was called
            mock_client.current_user.me.assert_called_once()

    def test_get_client_connection_verification_fails(
        self, mock_config_loader, mock_env_vars
    ):
        """Test error when connection verification fails."""
        mock_client = MagicMock()
        mock_client.current_user.me.side_effect = Exception("Auth failed")

        with patch("src.settings.client.WorkspaceClient", return_value=mock_client):
            with pytest.raises(DatabricksClientError, match="Failed to verify"):
                get_databricks_client()

    def test_get_client_initialization_error(
        self, mock_config_loader, mock_env_vars
    ):
        """Test error handling when client initialization fails."""
        with patch(
            "src.settings.client.WorkspaceClient",
            side_effect=Exception("Network error"),
        ):
            with pytest.raises(DatabricksClientError, match="Failed to initialize"):
                get_databricks_client()


class TestResetClient:
    """Tests for reset_client function."""

    def test_reset_client(self, mock_workspace_client, mock_config_loader, mock_env_vars):
        """Test resetting client."""
        # Create client
        client1 = get_databricks_client()
        assert client1 is not None

        # Reset
        reset_client()

        # Create new client
        client2 = get_databricks_client()
        assert client2 is not None

    def test_reset_client_when_none(self):
        """Test resetting client when no client exists."""
        reset_client()
        # Should not raise any errors

    def test_reset_client_thread_safe(self, mock_workspace_client, mock_config_loader, mock_env_vars):
        """Test reset_client is thread-safe."""
        import threading

        get_databricks_client()

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

        with patch("src.settings.client.WorkspaceClient", return_value=mock_client):
            # Initial call will fail, but that's expected
            try:
                get_databricks_client()
            except DatabricksClientError:
                pass

            # Reset and create a client that will fail on verification
            reset_client()
            with patch(
                "src.settings.client.get_databricks_client",
                side_effect=Exception("Connection error"),
            ):
                result = verify_connection()
                assert result is False


