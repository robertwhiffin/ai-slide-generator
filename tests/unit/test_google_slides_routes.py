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
from src.database.models import ConfigProfile


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
        conn.execute(text("DELETE FROM config_history"))
        conn.execute(text("DELETE FROM config_genie_spaces"))
        conn.execute(text("DELETE FROM config_prompts"))
        conn.execute(text("DELETE FROM config_ai_infra"))
        conn.execute(text("DELETE FROM config_profiles"))
        conn.commit()


def _seed_profile_with_creds(session_factory) -> int:
    """Insert profile with encrypted Google credentials, return its ID."""
    db = session_factory()
    p = ConfigProfile(
        name="creds-profile",
        created_by="test",
        google_credentials_encrypted=encrypt_data(VALID_CREDENTIALS),
    )
    db.add(p)
    db.commit()
    pid = p.id
    db.close()
    return pid


def _seed_profile(session_factory) -> int:
    db = session_factory()
    p = ConfigProfile(name="bare-profile", created_by="test")
    db.add(p)
    db.commit()
    pid = p.id
    db.close()
    return pid


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

        mock_request = MagicMock()
        mock_request.base_url = "http://localhost:8000/"
        uri = _build_redirect_uri(mock_request)
        assert uri == "http://localhost:8000/api/export/google-slides/auth/callback"


# ---------------------------------------------------------------------------
# Auth status endpoint (extended)
# ---------------------------------------------------------------------------

class TestAuthStatus:

    def test_returns_false_for_no_creds(self, test_client, session_factory):
        pid = _seed_profile(session_factory)
        resp = test_client.get(
            "/api/export/google-slides/auth/status",
            params={"profile_id": pid},
        )
        assert resp.status_code == 200
        assert resp.json()["authorized"] is False

    def test_returns_false_with_creds_but_no_token(self, test_client, session_factory):
        """Profile has credentials but user hasn't authorized yet."""
        pid = _seed_profile_with_creds(session_factory)
        resp = test_client.get(
            "/api/export/google-slides/auth/status",
            params={"profile_id": pid},
        )
        assert resp.status_code == 200
        assert resp.json()["authorized"] is False


# ---------------------------------------------------------------------------
# Auth URL endpoint
# ---------------------------------------------------------------------------

class TestAuthUrl:

    def test_auth_url_no_credentials_returns_400(self, test_client, session_factory):
        """No credentials → 400."""
        pid = _seed_profile(session_factory)
        resp = test_client.get(
            "/api/export/google-slides/auth/url",
            params={"profile_id": pid},
        )
        assert resp.status_code == 400

    def test_auth_url_with_credentials(self, test_client, session_factory):
        """Valid credentials → returns a Google auth URL."""
        pid = _seed_profile_with_creds(session_factory)
        resp = test_client.get(
            "/api/export/google-slides/auth/url",
            params={"profile_id": pid},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "url" in data
        assert "accounts.google.com" in data["url"]

    def test_auth_url_missing_profile(self, test_client):
        """Non-existent profile → 400."""
        resp = test_client.get(
            "/api/export/google-slides/auth/url",
            params={"profile_id": 9999},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Export endpoint
# ---------------------------------------------------------------------------

class TestExportEndpoint:

    def test_export_no_credentials_returns_400(self, test_client, session_factory):
        """No credentials → 400."""
        pid = _seed_profile(session_factory)
        resp = test_client.post(
            "/api/export/google-slides",
            json={"session_id": "test-session", "profile_id": pid},
        )
        assert resp.status_code == 400

    def test_export_not_authorized_returns_401(self, test_client, session_factory):
        """Credentials exist but no token → 401."""
        pid = _seed_profile_with_creds(session_factory)
        resp = test_client.post(
            "/api/export/google-slides",
            json={"session_id": "test-session", "profile_id": pid},
        )
        assert resp.status_code == 401
        assert "OAuth" in resp.json()["detail"]

    def test_export_missing_profile(self, test_client):
        """Non-existent profile → 400."""
        resp = test_client.post(
            "/api/export/google-slides",
            json={"session_id": "s", "profile_id": 9999},
        )
        assert resp.status_code == 400
