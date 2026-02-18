"""Tests for Google Slides API route endpoints.

Covers:
- auth/status, auth/url, auth/callback
- export endpoint
- Helper functions (_get_user_identity, _build_redirect_uri)
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from src.core.database import Base, get_db
from src.core.encryption import encrypt_data
from src.database.models import GoogleGlobalCredentials


# Sample credentials.json — must include auth_uri/token_uri for Flow.from_client_config
VALID_CREDENTIALS = json.dumps({
    "installed": {
        "client_id": "test-id.apps.googleusercontent.com",
        "client_secret": "test-secret",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }
})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables_to_create = [
        t for t in Base.metadata.sorted_tables
        if t.name != "config_history"
    ]
    for table in tables_to_create:
        table.create(bind=engine, checkfirst=True)

    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS config_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL,
                domain VARCHAR(50) NOT NULL,
                action VARCHAR(50) NOT NULL,
                changed_by VARCHAR(255) NOT NULL,
                changes TEXT NOT NULL,
                snapshot TEXT,
                timestamp DATETIME NOT NULL,
                FOREIGN KEY (profile_id) REFERENCES config_profiles (id) ON DELETE CASCADE
            )
        """))
        conn.commit()

    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def session_factory(db_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=db_engine)


@pytest.fixture(scope="module")
def test_client(db_engine, session_factory):
    from src.api.main import app

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _clean_data(db_engine):
    yield
    with db_engine.connect() as conn:
        conn.execute(text("DELETE FROM google_oauth_tokens"))
        conn.execute(text("DELETE FROM google_global_credentials"))
        conn.execute(text("DELETE FROM config_history"))
        conn.execute(text("DELETE FROM config_genie_spaces"))
        conn.execute(text("DELETE FROM config_prompts"))
        conn.execute(text("DELETE FROM config_ai_infra"))
        conn.execute(text("DELETE FROM config_profiles"))
        conn.commit()


def _seed_global_credentials(session_factory) -> None:
    """Insert global Google credentials into GoogleGlobalCredentials table."""
    db = session_factory()
    creds = GoogleGlobalCredentials(
        credentials_encrypted=encrypt_data(VALID_CREDENTIALS),
        uploaded_by="admin@test.com",
    )
    db.add(creds)
    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestHelpers:

    def test_get_user_identity_in_test_env(self):
        """In test environment, _get_user_identity returns 'local_dev'."""
        from src.api.routes.google_slides import _get_user_identity
        assert _get_user_identity() == "local_dev"

    def test_build_redirect_uri(self):
        """_build_redirect_uri constructs the callback URL from request base."""
        from src.api.routes.google_slides import _build_redirect_uri

        # Local dev: no forwarded headers → uses base_url
        mock_request = MagicMock()
        mock_request.headers.get.return_value = None
        mock_request.base_url = "http://localhost:8000/"
        uri = _build_redirect_uri(mock_request)
        assert uri == "http://localhost:8000/api/export/google-slides/auth/callback"

        # Behind proxy: X-Forwarded-Host/Proto present → uses public URL
        mock_proxy = MagicMock()
        mock_proxy.headers.get.side_effect = lambda h: {
            "x-forwarded-host": "myapp.databricksapps.com",
            "x-forwarded-proto": "https",
        }.get(h)
        uri = _build_redirect_uri(mock_proxy)
        assert uri == "https://myapp.databricksapps.com/api/export/google-slides/auth/callback"


# ---------------------------------------------------------------------------
# Auth status endpoint (extended)
# ---------------------------------------------------------------------------

class TestAuthStatus:

    def test_returns_false_for_no_creds(self, test_client):
        """No global credentials → authorized=false."""
        resp = test_client.get("/api/export/google-slides/auth/status")
        assert resp.status_code == 200
        assert resp.json()["authorized"] is False

    def test_returns_false_with_creds_but_no_token(self, test_client, session_factory):
        """Global credentials exist but user hasn't authorized yet."""
        _seed_global_credentials(session_factory)
        resp = test_client.get("/api/export/google-slides/auth/status")
        assert resp.status_code == 200
        assert resp.json()["authorized"] is False


# ---------------------------------------------------------------------------
# Auth URL endpoint
# ---------------------------------------------------------------------------

class TestAuthUrl:

    def test_auth_url_no_credentials_returns_400(self, test_client):
        """No global credentials → 400."""
        resp = test_client.get("/api/export/google-slides/auth/url")
        assert resp.status_code == 400

    def test_auth_url_with_credentials(self, test_client, session_factory):
        """Global credentials exist → returns a Google auth URL."""
        _seed_global_credentials(session_factory)
        resp = test_client.get("/api/export/google-slides/auth/url")
        assert resp.status_code == 200
        data = resp.json()
        assert "url" in data
        assert "accounts.google.com" in data["url"]


# ---------------------------------------------------------------------------
# Export endpoint
# ---------------------------------------------------------------------------

class TestExportEndpoint:

    def test_export_no_credentials_returns_400(self, test_client):
        """No global credentials → 400."""
        resp = test_client.post(
            "/api/export/google-slides",
            json={"session_id": "test-session"},
        )
        assert resp.status_code == 400

    def test_export_not_authorized_returns_401(self, test_client, session_factory):
        """Global credentials exist but no token → 401."""
        _seed_global_credentials(session_factory)
        resp = test_client.post(
            "/api/export/google-slides",
            json={"session_id": "test-session"},
        )
        assert resp.status_code == 401
        assert "OAuth" in resp.json()["detail"]
