"""
Unit tests for local/Homebrew version check endpoint.

Tests the /api/version/local-check endpoint that checks GitHub releases
for newer versions (separate from the PyPI version check).
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.api.routes.local_version import (
    _get_local_version,
    _is_update_available,
    _parse_version_tag,
    router,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def local_version_app():
    """Create a minimal FastAPI app with only the local_version router."""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(local_version_app):
    """Provide a TestClient for the local_version router."""
    with TestClient(local_version_app) as c:
        yield c


@pytest.fixture(autouse=True)
def clear_github_cache():
    """Reset GitHub cache between tests."""
    from src.api.routes import local_version

    local_version._github_cache = {"version": None, "timestamp": 0}
    yield
    local_version._github_cache = {"version": None, "timestamp": 0}


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestParseVersionTag:
    """Tests for git tag to version parsing."""

    def test_parse_version_tag_valid_scenarios(self):
        """Test parsing valid version tags in various formats."""
        assert _parse_version_tag("v1.0.0") == "1.0.0"
        assert _parse_version_tag("1.2.3") == "1.2.3"
        assert _parse_version_tag("  v2.0.0  ") == "2.0.0"

    def test_parse_version_tag_error_handling(self):
        """Test parsing invalid and empty tags returns None."""
        assert _parse_version_tag("not-a-version") is None
        assert _parse_version_tag("") is None


class TestIsUpdateAvailable:
    """Tests for version comparison logic."""

    def test_is_update_available_valid_scenarios(self):
        """Test update detection for newer versions."""
        assert _is_update_available("0.1.0", "0.2.0") is True
        assert _is_update_available("1.0.0", "1.0.1") is True

    def test_is_update_available_edge_cases(self):
        """Test no update for same, older, or invalid versions."""
        assert _is_update_available("1.0.0", "1.0.0") is False
        assert _is_update_available("2.0.0", "1.0.0") is False
        assert _is_update_available("invalid", "1.0.0") is False


class TestGetLocalVersion:
    """Tests for local version detection."""

    def test_get_local_version_valid_scenarios(self):
        """Returns the version string from src.__version__."""
        version = _get_local_version()
        assert isinstance(version, str)
        assert version != ""
        assert version != "unknown"

    def test_get_local_version_error_handling(self):
        """Returns 'unknown' when src.__version__ is unavailable."""
        import src

        original = getattr(src, "__version__", None)
        try:
            delattr(src, "__version__")
            assert _get_local_version() == "unknown"
        finally:
            if original is not None:
                src.__version__ = original


# ---------------------------------------------------------------------------
# GET /api/version/local-check
# ---------------------------------------------------------------------------


class TestLocalVersionCheckEndpoint:
    """Tests for the local version check API endpoint."""

    def test_local_check_valid_scenarios(self, client):
        """Test update detection and no-update when current."""
        # Update available when newer release exists (simulate Homebrew install)
        with patch(
            "src.api.routes.local_version._get_latest_github_release",
            return_value={
                "tag_name": "v1.0.0",
                "html_url": "https://github.com/repo/releases/v1.0.0",
            },
        ):
            with patch(
                "src.api.routes.local_version._get_local_version",
                return_value="0.1.0",
            ):
                with patch(
                    "src.api.routes.local_version._is_homebrew_install",
                    return_value=True,
                ):
                    response = client.get("/api/version/local-check")
                    assert response.status_code == 200
                    data = response.json()
                    assert data["update_available"] is True
                    assert data["latest_version"] == "1.0.0"
                    assert data["update_command"] == "brew upgrade tellr"
                    assert data["release_url"] == "https://github.com/repo/releases/v1.0.0"

        # Git-clone install shows git pull command
        with patch(
            "src.api.routes.local_version._get_latest_github_release",
            return_value={
                "tag_name": "v1.0.0",
                "html_url": "https://github.com/repo/releases/v1.0.0",
            },
        ):
            with patch(
                "src.api.routes.local_version._get_local_version",
                return_value="0.1.0",
            ):
                with patch(
                    "src.api.routes.local_version._is_homebrew_install",
                    return_value=False,
                ):
                    response = client.get("/api/version/local-check")
                    assert response.status_code == 200
                    assert response.json()["update_command"] == "git pull && ./start_app.sh"

        # No update when already on latest
        with patch(
            "src.api.routes.local_version._get_latest_github_release",
            return_value={
                "tag_name": "v0.1.0",
                "html_url": "https://github.com/repo/releases/v0.1.0",
            },
        ):
            with patch(
                "src.api.routes.local_version._get_local_version",
                return_value="0.1.0",
            ):
                response = client.get("/api/version/local-check")
                assert response.status_code == 200
                assert response.json()["update_available"] is False

    def test_local_check_error_handling(self, client):
        """Test graceful handling when GitHub or local version unavailable."""
        # No GitHub release available
        with patch(
            "src.api.routes.local_version._get_latest_github_release",
            return_value=None,
        ):
            with patch(
                "src.api.routes.local_version._get_local_version",
                return_value="0.1.0",
            ):
                response = client.get("/api/version/local-check")
                assert response.status_code == 200
                data = response.json()
                assert data["update_available"] is False
                assert data["installed_version"] == "0.1.0"
                assert data["latest_version"] is None

        # Unknown local version
        with patch(
            "src.api.routes.local_version._get_latest_github_release",
            return_value={
                "tag_name": "v1.0.0",
                "html_url": "https://github.com/repo/releases/v1.0.0",
            },
        ):
            with patch(
                "src.api.routes.local_version._get_local_version",
                return_value="unknown",
            ):
                response = client.get("/api/version/local-check")
                assert response.status_code == 200
                data = response.json()
                assert data["update_available"] is False
                assert data["installed_version"] == "unknown"
