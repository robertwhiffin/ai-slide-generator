"""Tests for Google OAuth models, credential endpoints, and auth service.

Covers:
- GoogleOAuthToken model CRUD
- ConfigProfile.google_credentials_encrypted column
- Google credentials upload / status / delete API routes
- GoogleSlidesAuth DB-backed mode (from_profile)
- Google Slides auth status endpoint
"""

import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from src.core.database import Base, get_db
from src.database.models import ConfigProfile, GoogleOAuthToken


# Sample credentials.json matching Google OAuth format.
# Must include auth_uri and token_uri for Flow.from_client_config to work.
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
    """In-memory SQLite engine shared across the module."""
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

    # Simplified history table (TEXT instead of JSONB)
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

    for table in reversed(tables_to_create):
        table.drop(bind=engine, checkfirst=True)
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS config_history"))
        conn.commit()
    engine.dispose()


@pytest.fixture(scope="module")
def session_factory(db_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=db_engine)


@pytest.fixture(scope="function")
def db_session(session_factory, db_engine):
    """Function-scoped session with data cleanup between tests."""
    session = session_factory()
    yield session
    session.rollback()
    session.close()

    # Clean data between tests
    with db_engine.connect() as conn:
        conn.execute(text("DELETE FROM google_oauth_tokens"))
        conn.execute(text("DELETE FROM config_history"))
        conn.execute(text("DELETE FROM config_genie_spaces"))
        conn.execute(text("DELETE FROM config_prompts"))
        conn.execute(text("DELETE FROM config_ai_infra"))
        conn.execute(text("DELETE FROM config_profiles"))
        conn.commit()


@pytest.fixture
def profile(db_session):
    """Create a basic profile for tests."""
    p = ConfigProfile(name="test-profile", created_by="test")
    db_session.add(p)
    db_session.commit()
    return p


@pytest.fixture(scope="module")
def test_client(db_engine, session_factory):
    """FastAPI TestClient with overridden get_db dependency."""
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
def _clean_data_for_api_tests(db_engine):
    """Ensure clean state before every test (including API tests)."""
    yield
    with db_engine.connect() as conn:
        conn.execute(text("DELETE FROM google_oauth_tokens"))
        conn.execute(text("DELETE FROM config_history"))
        conn.execute(text("DELETE FROM config_genie_spaces"))
        conn.execute(text("DELETE FROM config_prompts"))
        conn.execute(text("DELETE FROM config_ai_infra"))
        conn.execute(text("DELETE FROM config_profiles"))
        conn.commit()


def _seed_profile(session_factory) -> int:
    """Insert a profile and return its ID."""
    db = session_factory()
    p = ConfigProfile(name="test-profile", created_by="test")
    db.add(p)
    db.commit()
    pid = p.id
    db.close()
    return pid


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestGoogleOAuthModels:
    """Test the new DB model and column additions."""

    def test_profile_google_credentials_column(self, db_session, profile):
        """google_credentials_encrypted column stores and retrieves data."""
        profile.google_credentials_encrypted = "encrypted-blob"
        db_session.commit()

        loaded = db_session.get(ConfigProfile, profile.id)
        assert loaded.google_credentials_encrypted == "encrypted-blob"

        # Null by default on a fresh profile
        p2 = ConfigProfile(name="empty-creds", created_by="test")
        db_session.add(p2)
        db_session.commit()
        assert p2.google_credentials_encrypted is None

    def test_google_oauth_token_crud(self, db_session, profile):
        """GoogleOAuthToken can be created, queried, and its repr works."""
        token = GoogleOAuthToken(
            user_identity="user@example.com",
            profile_id=profile.id,
            token_encrypted="enc-token",
        )
        db_session.add(token)
        db_session.commit()

        loaded = (
            db_session.query(GoogleOAuthToken)
            .filter_by(user_identity="user@example.com", profile_id=profile.id)
            .first()
        )
        assert loaded is not None
        assert loaded.token_encrypted == "enc-token"
        assert "user@example.com" in repr(loaded)

    def test_google_oauth_token_unique_constraint(self, db_session, profile):
        """Composite unique constraint on (user_identity, profile_id)."""
        from sqlalchemy.exc import IntegrityError

        t1 = GoogleOAuthToken(
            user_identity="dup@test.com",
            profile_id=profile.id,
            token_encrypted="a",
        )
        db_session.add(t1)
        db_session.commit()

        t2 = GoogleOAuthToken(
            user_identity="dup@test.com",
            profile_id=profile.id,
            token_encrypted="b",
        )
        db_session.add(t2)
        with pytest.raises(IntegrityError):
            db_session.commit()


# ---------------------------------------------------------------------------
# Credential upload / status / delete API tests
# ---------------------------------------------------------------------------

class TestGoogleCredentialsAPI:
    """Test the /api/settings/profiles/{id}/google-credentials endpoints."""

    def test_status_no_credentials(self, test_client, session_factory):
        """Status returns has_credentials=false for a fresh profile."""
        pid = _seed_profile(session_factory)
        resp = test_client.get(f"/api/settings/profiles/{pid}/google-credentials/status")
        assert resp.status_code == 200
        assert resp.json()["has_credentials"] is False

    def test_upload_valid_credentials(self, test_client, session_factory):
        """Uploading valid credentials.json succeeds and status flips to true."""
        pid = _seed_profile(session_factory)
        resp = test_client.post(
            f"/api/settings/profiles/{pid}/google-credentials",
            files={"file": ("credentials.json", VALID_CREDENTIALS, "application/json")},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        status = test_client.get(f"/api/settings/profiles/{pid}/google-credentials/status")
        assert status.json()["has_credentials"] is True

    def test_upload_invalid_json(self, test_client, session_factory):
        """Uploading non-JSON is rejected with 400."""
        pid = _seed_profile(session_factory)
        resp = test_client.post(
            f"/api/settings/profiles/{pid}/google-credentials",
            files={"file": ("bad.json", "not json", "application/json")},
        )
        assert resp.status_code == 400

    def test_upload_missing_keys(self, test_client, session_factory):
        """JSON without 'installed' or 'web' key is rejected."""
        pid = _seed_profile(session_factory)
        bad = json.dumps({"some_key": "some_val"})
        resp = test_client.post(
            f"/api/settings/profiles/{pid}/google-credentials",
            files={"file": ("creds.json", bad, "application/json")},
        )
        assert resp.status_code == 400
        assert "installed" in resp.json()["detail"]

    def test_delete_credentials(self, test_client, session_factory):
        """Deleting credentials clears the stored data."""
        pid = _seed_profile(session_factory)
        # Upload first
        test_client.post(
            f"/api/settings/profiles/{pid}/google-credentials",
            files={"file": ("credentials.json", VALID_CREDENTIALS, "application/json")},
        )
        # Delete
        resp = test_client.delete(f"/api/settings/profiles/{pid}/google-credentials")
        assert resp.status_code == 204

        # Verify gone
        status = test_client.get(f"/api/settings/profiles/{pid}/google-credentials/status")
        assert status.json()["has_credentials"] is False

    def test_upload_profile_not_found(self, test_client):
        """Uploading to a non-existent profile returns 404."""
        resp = test_client.post(
            "/api/settings/profiles/999/google-credentials",
            files={"file": ("creds.json", VALID_CREDENTIALS, "application/json")},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GoogleSlidesAuth.from_profile tests
# ---------------------------------------------------------------------------

class TestGoogleSlidesAuthFromProfile:
    """Test DB-backed GoogleSlidesAuth construction."""

    def test_from_profile_no_credentials_raises(self, db_session, profile):
        """from_profile raises when profile has no credentials."""
        from src.services.google_slides_auth import GoogleSlidesAuth, GoogleSlidesAuthError

        with pytest.raises(GoogleSlidesAuthError, match="no Google OAuth credentials"):
            GoogleSlidesAuth.from_profile(profile.id, "user@test.com", db_session)

    def test_from_profile_with_credentials(self, db_session, profile):
        """from_profile succeeds and returns a DB-mode auth instance."""
        from src.core.encryption import encrypt_data
        from src.services.google_slides_auth import GoogleSlidesAuth

        profile.google_credentials_encrypted = encrypt_data(VALID_CREDENTIALS)
        db_session.commit()

        auth = GoogleSlidesAuth.from_profile(profile.id, "user@test.com", db_session)
        assert auth is not None
        assert auth._db_mode is True
        assert auth.is_authorized() is False  # No token yet

    def test_from_profile_stale_token_deleted(self, db_session, profile):
        """from_profile deletes a token it cannot decrypt instead of crashing."""
        from src.core.encryption import encrypt_data
        from src.services.google_slides_auth import GoogleSlidesAuth

        profile.google_credentials_encrypted = encrypt_data(VALID_CREDENTIALS)
        db_session.add(GoogleOAuthToken(
            user_identity="user@test.com",
            profile_id=profile.id,
            token_encrypted="not-a-valid-fernet-token",
        ))
        db_session.commit()

        auth = GoogleSlidesAuth.from_profile(profile.id, "user@test.com", db_session)
        assert auth.is_authorized() is False

        # Stale token row should be cleaned up
        remaining = (
            db_session.query(GoogleOAuthToken)
            .filter_by(user_identity="user@test.com", profile_id=profile.id)
            .first()
        )
        assert remaining is None

    def test_from_profile_nonexistent_profile(self, db_session):
        """from_profile raises for a missing profile ID."""
        from src.services.google_slides_auth import GoogleSlidesAuth, GoogleSlidesAuthError

        with pytest.raises(GoogleSlidesAuthError, match="not found"):
            GoogleSlidesAuth.from_profile(999, "user@test.com", db_session)


# ---------------------------------------------------------------------------
# GoogleSlidesAuth constructor and public API tests
# ---------------------------------------------------------------------------

class TestGoogleSlidesAuthUnit:
    """Unit tests for GoogleSlidesAuth constructor modes and public methods."""

    def test_db_mode_constructor(self):
        """DB-mode sets _db_mode=True and stores credentials in memory."""
        from src.services.google_slides_auth import GoogleSlidesAuth

        auth = GoogleSlidesAuth(credentials_json=VALID_CREDENTIALS)
        assert auth._db_mode is True
        assert auth._credentials_json == VALID_CREDENTIALS
        assert auth._token_json is None
        assert auth.is_authorized() is False

    def test_file_mode_constructor(self, tmp_path):
        """File-mode constructor uses file paths, warns if file missing."""
        from src.services.google_slides_auth import GoogleSlidesAuth

        auth = GoogleSlidesAuth(
            credentials_path=str(tmp_path / "nonexistent.json"),
            token_path=str(tmp_path / "token.json"),
        )
        assert auth._db_mode is False
        assert auth.is_authorized() is False

    def test_get_auth_url_db_mode(self):
        """get_auth_url generates a Google consent URL in DB mode."""
        from src.services.google_slides_auth import GoogleSlidesAuth

        auth = GoogleSlidesAuth(credentials_json=VALID_CREDENTIALS)
        url = auth.get_auth_url(redirect_uri="http://localhost/callback")
        assert "accounts.google.com" in url
        assert "http://localhost/callback" in url or "redirect_uri" in url

    def test_get_credentials_raises_when_no_token(self):
        """get_credentials raises GoogleSlidesAuthError when not authorized."""
        from src.services.google_slides_auth import GoogleSlidesAuth, GoogleSlidesAuthError

        auth = GoogleSlidesAuth(credentials_json=VALID_CREDENTIALS)
        with pytest.raises(GoogleSlidesAuthError, match="Not authorized"):
            auth.get_credentials()

    def test_on_token_changed_callback(self):
        """_save_token invokes the on_token_changed callback in DB mode."""
        from unittest.mock import MagicMock
        from google.oauth2.credentials import Credentials
        from src.services.google_slides_auth import GoogleSlidesAuth

        callback = MagicMock()
        auth = GoogleSlidesAuth(
            credentials_json=VALID_CREDENTIALS,
            on_token_changed=callback,
        )

        # Simulate saving a token
        mock_creds = MagicMock(spec=Credentials)
        mock_creds.to_json.return_value = '{"token": "test"}'
        auth._save_token(mock_creds)

        callback.assert_called_once_with('{"token": "test"}')
        assert auth._token_json == '{"token": "test"}'

    def test_load_token_returns_none_when_empty(self):
        """_load_token returns None when no token_json is set."""
        from src.services.google_slides_auth import GoogleSlidesAuth

        auth = GoogleSlidesAuth(credentials_json=VALID_CREDENTIALS)
        assert auth._load_token() is None

    def test_load_token_returns_none_for_invalid_json(self):
        """_load_token returns None for malformed token JSON."""
        from src.services.google_slides_auth import GoogleSlidesAuth

        auth = GoogleSlidesAuth(
            credentials_json=VALID_CREDENTIALS,
            token_json="not valid json",
        )
        assert auth._load_token() is None


# ---------------------------------------------------------------------------
# Google Slides auth status endpoint
# ---------------------------------------------------------------------------

class TestGoogleSlidesAuthStatusEndpoint:
    """Test /api/export/google-slides/auth/status returns gracefully."""

    def test_auth_status_no_credentials(self, test_client, session_factory):
        """Returns authorized=false when no credentials are uploaded."""
        pid = _seed_profile(session_factory)
        resp = test_client.get(
            "/api/export/google-slides/auth/status",
            params={"profile_id": pid},
        )
        assert resp.status_code == 200
        assert resp.json()["authorized"] is False

    def test_auth_status_nonexistent_profile(self, test_client):
        """Returns authorized=false (not 500) for missing profile."""
        resp = test_client.get(
            "/api/export/google-slides/auth/status",
            params={"profile_id": 999},
        )
        assert resp.status_code == 200
        assert resp.json()["authorized"] is False
