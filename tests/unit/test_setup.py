"""
Unit tests for setup API routes (first-time configuration).

Tests the /api/setup/* endpoints that handle workspace configuration
for local/Homebrew installations.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.routes.setup import (
    ConfigureWorkspaceRequest,
    router,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def setup_app():
    """Create a minimal FastAPI app with only the setup router for testing."""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(setup_app):
    """Provide a TestClient for the setup router."""
    with TestClient(setup_app) as c:
        yield c


# ---------------------------------------------------------------------------
# GET /api/setup/status
# ---------------------------------------------------------------------------


class TestGetSetupStatus:
    """Tests for the setup status endpoint."""

    def test_status_valid_scenarios(self, client):
        """Test status returns configured=True via tellr config and env var."""
        # Configured via ~/.tellr/config.yaml
        with patch("src.api.routes.setup.is_tellr_configured", return_value=True):
            with patch(
                "src.api.routes.setup.get_tellr_config",
                return_value={"databricks": {"host": "https://my.cloud.databricks.com"}},
            ):
                response = client.get("/api/setup/status")
                assert response.status_code == 200
                data = response.json()
                assert data["configured"] is True
                assert data["host"] == "https://my.cloud.databricks.com"

        # Configured via DATABRICKS_HOST env var
        with patch("src.api.routes.setup.is_tellr_configured", return_value=False):
            with patch.dict(
                "os.environ",
                {"DATABRICKS_HOST": "https://env.cloud.databricks.com"},
                clear=False,
            ):
                response = client.get("/api/setup/status")
                assert response.status_code == 200
                data = response.json()
                assert data["configured"] is True
                assert data["host"] == "https://env.cloud.databricks.com"

    def test_status_not_configured(self, client):
        """Test status returns configured=False when no config exists."""
        with patch("src.api.routes.setup.is_tellr_configured", return_value=False):
            with patch.dict("os.environ", {}, clear=True):
                import os

                os.environ.pop("DATABRICKS_HOST", None)
                response = client.get("/api/setup/status")
                assert response.status_code == 200
                data = response.json()
                assert data["configured"] is False
                assert data["host"] is None


# ---------------------------------------------------------------------------
# POST /api/setup/configure
# ---------------------------------------------------------------------------


class TestConfigureWorkspace:
    """Tests for the workspace configuration endpoint."""

    def test_configure_valid_scenarios(self, client):
        """Test configure with various valid inputs (AWS, Azure, GCP, normalisation)."""
        with patch("src.api.routes.setup.save_tellr_config") as mock_save:
            with patch("src.api.routes.setup.reset_client"):
                # AWS URL
                response = client.post(
                    "/api/setup/configure",
                    json={"host": "https://mycompany.cloud.databricks.com"},
                )
                assert response.status_code == 200
                assert response.json()["success"] is True
                assert response.json()["host"] == "https://mycompany.cloud.databricks.com"
                mock_save.assert_called_with(
                    host="https://mycompany.cloud.databricks.com",
                    auth_type="external-browser",
                )

                # Azure URL
                response = client.post(
                    "/api/setup/configure",
                    json={"host": "https://adb-1234567890.18.azuredatabricks.net"},
                )
                assert response.status_code == 200
                assert response.json()["success"] is True

                # GCP URL
                response = client.post(
                    "/api/setup/configure",
                    json={"host": "https://myworkspace.gcp.databricks.com"},
                )
                assert response.status_code == 200
                assert response.json()["success"] is True

                # Auto-adds https:// prefix
                response = client.post(
                    "/api/setup/configure",
                    json={"host": "mycompany.cloud.databricks.com"},
                )
                assert response.status_code == 200
                assert response.json()["host"] == "https://mycompany.cloud.databricks.com"

                # Strips trailing slash
                response = client.post(
                    "/api/setup/configure",
                    json={"host": "https://mycompany.cloud.databricks.com/"},
                )
                assert response.status_code == 200
                assert response.json()["host"] == "https://mycompany.cloud.databricks.com"

    def test_configure_error_handling(self, client):
        """Test configure rejects invalid input and handles save failures."""
        # Invalid non-Databricks URL
        response = client.post(
            "/api/setup/configure",
            json={"host": "https://example.com"},
        )
        assert response.status_code == 422

        # Empty host
        response = client.post(
            "/api/setup/configure",
            json={"host": ""},
        )
        assert response.status_code == 422

        # Save failure returns 500
        with patch(
            "src.api.routes.setup.save_tellr_config",
            side_effect=IOError("Permission denied"),
        ):
            with patch("src.api.routes.setup.reset_client"):
                response = client.post(
                    "/api/setup/configure",
                    json={"host": "https://mycompany.cloud.databricks.com"},
                )
                assert response.status_code == 500
                assert "Failed to save" in response.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/setup/test-connection
# ---------------------------------------------------------------------------


class TestTestConnection:
    """Tests for the connection test endpoint."""

    def test_connection_valid_scenarios(self, client):
        """Test successful connection returns user info."""
        mock_user = MagicMock()
        mock_user.user_name = "testuser@company.com"
        mock_user.display_name = "Test User"

        mock_client = MagicMock()
        mock_client.current_user.me.return_value = mock_user

        with patch(
            "src.core.databricks_client.get_system_client",
            return_value=mock_client,
        ):
            response = client.post("/api/setup/test-connection")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["user"]["username"] == "testuser@company.com"
            assert data["user"]["display_name"] == "Test User"

    def test_connection_error_handling(self, client):
        """Test connection failure returns 400."""
        with patch(
            "src.core.databricks_client.get_system_client",
            side_effect=Exception("Authentication failed"),
        ):
            response = client.post("/api/setup/test-connection")
            assert response.status_code == 400
            assert "Connection failed" in response.json()["detail"]


# ---------------------------------------------------------------------------
# URL Validation
# ---------------------------------------------------------------------------


class TestUrlValidation:
    """Tests for workspace URL validation logic."""

    def test_valid_urls(self):
        """Accepts various valid Databricks URL formats."""
        valid_urls = [
            "https://company.cloud.databricks.com",
            "https://adb-1234567890123456.14.azuredatabricks.net",
            "https://workspace.gcp.databricks.com",
            "company.cloud.databricks.com",  # auto-adds https://
            "https://my-workspace.cloud.databricks.com",
        ]
        for url in valid_urls:
            req = ConfigureWorkspaceRequest(host=url)
            assert req.host.startswith("https://"), f"Failed for {url}"

    def test_invalid_urls(self):
        """Rejects invalid URL formats."""
        invalid_urls = [
            "https://google.com",
            "https://not-databricks.com",
            "ftp://company.cloud.databricks.com",
        ]
        for url in invalid_urls:
            with pytest.raises(Exception):
                ConfigureWorkspaceRequest(host=url)
