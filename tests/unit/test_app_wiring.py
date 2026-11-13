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
        from src.api.main import app

        route_paths = {r.path for r in app.routes if hasattr(r, "path")}
        assert "/api/export/google-slides/auth/status" in route_paths
        assert "/api/export/google-slides/auth/url" in route_paths
        assert "/api/export/google-slides/auth/callback" in route_paths
        assert "/api/export/google-slides/auth" in route_paths
        assert "/api/export/google-slides" in route_paths

    def test_admin_google_credentials_routes_registered(self):
        """Admin Google credentials management routes are reachable."""
        from src.api.main import app

        route_paths = {r.path for r in app.routes if hasattr(r, "path")}
        assert "/api/admin/google-credentials" in route_paths
        assert "/api/admin/google-credentials/status" in route_paths
        assert "/api/admin/judge-backend" in route_paths

    def test_image_generation_routes_registered(self):
        """The four image-generation routes are always mounted (the flag gates per request)."""
        from fastapi.routing import APIRoute

        from src.api.main import app

        expected = {
            ("GET", "/api/images/generate/available"),
            ("POST", "/api/images/generate"),
            ("POST", "/api/images/{token}/edit"),
            ("GET", "/api/images/generate/jobs/{job_id}"),
        }
        live = {
            (method, route.path): route
            for route in app.routes
            if isinstance(route, APIRoute)
            for method in route.methods
        }
        missing = sorted(expected - set(live))
        assert not missing, f"image-generation routes not registered: {missing}"
        for key in sorted(expected):
            module = live[key].endpoint.__module__
            assert module == "src.api.routes.image_generation", (key, module)

    def test_image_generation_router_precedes_images_router(self):
        """Included BEFORE images.router so its literal paths win over ``/{token}`` ones."""
        from fastapi.routing import APIRoute

        from src.api.main import app

        api_routes = [r for r in app.routes if isinstance(r, APIRoute)]
        positions = {
            (method, r.path): i for i, r in enumerate(api_routes) for method in r.methods
        }
        first_images_route = min(
            i for i, r in enumerate(api_routes)
            if r.endpoint.__module__ == "src.api.routes.images"
        )
        for key in (
            ("GET", "/api/images/generate/available"),
            ("POST", "/api/images/generate"),
            ("POST", "/api/images/{token}/edit"),
            ("GET", "/api/images/generate/jobs/{job_id}"),
        ):
            assert key in positions, f"{key} not registered"
            assert positions[key] < first_images_route, key

    def test_chat_routes_exclude_the_sync_legacy_bypass(self):
        """Only mode-aware transports may accept chat turns (#286)."""
        from fastapi.routing import APIRoute

        from src.api.main import app

        chat_posts = {
            route.path
            for route in app.routes
            if isinstance(route, APIRoute)
            and "POST" in route.methods
            and route.endpoint.__module__ == "src.api.routes.chat"
        }
        assert chat_posts == {"/api/chat/stream", "/api/chat/async"}

    def test_openapi_does_not_advertise_sync_chat(self):
        """API clients must discover the mode-aware chat endpoints, not the bypass."""
        from src.api.main import app

        paths = app.openapi()["paths"]
        assert "/api/chat" not in paths
        assert "post" in paths["/api/chat/stream"]
        assert "post" in paths["/api/chat/async"]

    def test_health_endpoint(self):
        """Health endpoint still works."""
        from src.api.main import app

        route_paths = {r.path for r in app.routes if hasattr(r, "path")}
        assert "/api/health" in route_paths
