"""Tests for application wiring: model registration, route inclusion, exports.

Verifies that recent additions (GoogleOAuthToken model, google_credentials
router, google_slides router) are properly connected in the app.
"""

import pytest


class TestModelRegistration:
    """Ensure all models are importable from the models package."""

    def test_google_oauth_token_in_models_all(self):
        """GoogleOAuthToken is exported in database.models.__all__."""
        from src.database.models import __all__ as model_names
        assert "GoogleOAuthToken" in model_names

    def test_google_oauth_token_importable(self):
        """GoogleOAuthToken can be imported directly."""
        from src.database.models import GoogleOAuthToken
        assert GoogleOAuthToken.__tablename__ == "google_oauth_tokens"

    def test_config_profile_has_google_credentials_column(self):
        """ConfigProfile model includes google_credentials_encrypted."""
        from src.database.models import ConfigProfile
        assert hasattr(ConfigProfile, "google_credentials_encrypted")


class TestSettingsRouterExports:
    """Verify the settings __init__ exports all required routers."""

    def test_google_credentials_router_exported(self):
        """google_credentials_router is in settings __all__."""
        from src.api.routes.settings import __all__ as exports
        assert "google_credentials_router" in exports

    def test_all_routers_importable(self):
        """Every router listed in __all__ is importable."""
        from src.api.routes import settings
        for name in settings.__all__:
            assert hasattr(settings, name), f"{name} not importable from settings"


class TestAppRoutes:
    """Verify FastAPI app has the expected route prefixes registered."""

    def test_google_slides_routes_registered(self):
        """Google Slides auth + export routes are reachable."""
        from src.api.main import app

        route_paths = {r.path for r in app.routes if hasattr(r, "path")}
        assert "/api/export/google-slides/auth/status" in route_paths
        assert "/api/export/google-slides/auth/url" in route_paths
        assert "/api/export/google-slides/auth/callback" in route_paths
        assert "/api/export/google-slides" in route_paths

    def test_google_credentials_routes_registered(self):
        """Google credentials management routes are reachable."""
        from src.api.main import app

        route_paths = {r.path for r in app.routes if hasattr(r, "path")}
        assert "/api/settings/profiles/{profile_id}/google-credentials" in route_paths
        assert "/api/settings/profiles/{profile_id}/google-credentials/status" in route_paths

    def test_health_endpoint(self):
        """Health endpoint still works."""
        from src.api.main import app

        route_paths = {r.path for r in app.routes if hasattr(r, "path")}
        assert "/api/health" in route_paths
