"""Tests for application wiring: model registration, route inclusion, exports.

Verifies that recent additions (GoogleOAuthToken model, admin google-credentials,
google_slides router) are properly connected in the app.
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

    def test_google_global_credentials_model_exists(self):
        """GoogleGlobalCredentials model exists for app-wide credentials."""
        from src.database.models import GoogleGlobalCredentials
        assert GoogleGlobalCredentials.__tablename__ == "google_global_credentials"
        assert hasattr(GoogleGlobalCredentials, "credentials_encrypted")


class TestSettingsRouterExports:
    """Verify the settings __init__ exports all required routers."""

    def test_all_routers_importable(self):
        """Every router listed in __all__ is importable."""
        from src.api.routes import settings
        for name in settings.__all__:
            assert hasattr(settings, name), f"{name} not importable from settings"


class TestAppRoutes:
    """Verify FastAPI app has the expected route prefixes registered."""

    def test_google_slides_routes_registered(self):
        """Google Slides auth + export routes are reachable."""
        import sys
        import src.api.main as main_mod
        from src.api.main import app
        from src.api.routes import admin as admin_mod, google_slides as gs_mod

        route_paths = {r.path for r in app.routes if hasattr(r, "path")}
        diag = (
            f"\n[DIAG] id(app)={id(app)} id(main.app)={id(main_mod.app)} "
            f"same_obj={app is main_mod.app}\n"
            f"[DIAG] main in sys.modules id={id(sys.modules.get('src.api.main'))}\n"
            f"[DIAG] total app.routes={len(app.routes)}\n"
            f"[DIAG] admin.router routes={len(admin_mod.router.routes)} "
            f"id(admin_mod)={id(admin_mod)}\n"
            f"[DIAG] gs.router routes={len(gs_mod.router.routes)} "
            f"id(gs_mod)={id(gs_mod)}\n"
            f"[DIAG] admin_mod is main's admin? "
            f"{getattr(main_mod, 'admin', None) is admin_mod}\n"
            f"[DIAG] sorted paths={sorted(route_paths)}\n"
        )
        assert "/api/export/google-slides/auth/status" in route_paths, diag
        assert "/api/export/google-slides/auth/url" in route_paths
        assert "/api/export/google-slides/auth/callback" in route_paths
        assert "/api/export/google-slides" in route_paths

    def test_admin_google_credentials_routes_registered(self):
        """Admin Google credentials management routes are reachable."""
        from src.api.main import app

        route_paths = {r.path for r in app.routes if hasattr(r, "path")}
        assert "/api/admin/google-credentials" in route_paths
        assert "/api/admin/google-credentials/status" in route_paths
        assert "/api/admin/judge-backend" in route_paths

    def test_health_endpoint(self):
        """Health endpoint still works."""
        from src.api.main import app

        route_paths = {r.path for r in app.routes if hasattr(r, "path")}
        assert "/api/health" in route_paths
