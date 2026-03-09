"""Tests for Google OAuth models, credential endpoints, and auth service.

Covers:
- GoogleOAuthToken model CRUD (user_identity only, no profile_id)
- GoogleSlidesAuth DB-backed mode (from_global)
- Google Slides auth status endpoint (no profile_id)
"""

import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from src.core.database import Base, get_db
from src.core.encryption import encrypt_data
from src.database.models import ConfigProfile, GoogleGlobalCredentials, GoogleOAuthToken


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
        conn.execute(text("DELETE FROM google_global_credentials"))
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
        conn.execute(text("DELETE FROM google_global_credentials"))
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
    """Test GoogleOAuthToken model (user_identity only, no profile_id)."""

    def test_google_oauth_token_crud(self, db_session):
        """GoogleOAuthToken can be created, queried, and its repr works."""
        token = GoogleOAuthToken(
            user_identity="user@example.com",
            token_encrypted="enc-token",
        )
        db_session.add(token)
        db_session.commit()

        loaded = (
            db_session.query(GoogleOAuthToken)
            .filter_by(user_identity="user@example.com")
            .first()
        )
        assert loaded is not None
        assert loaded.token_encrypted == "enc-token"
        assert "user@example.com" in repr(loaded)

    def test_google_oauth_token_unique_constraint(self, db_session):
        """Unique constraint on user_identity only."""
        from sqlalchemy.exc import IntegrityError

        t1 = GoogleOAuthToken(
            user_identity="dup@test.com",
            token_encrypted="a",
        )
        db_session.add(t1)
        db_session.commit()

        t2 = GoogleOAuthToken(
            user_identity="dup@test.com",
            token_encrypted="b",
        )
        db_session.add(t2)
        with pytest.raises(IntegrityError):
            db_session.commit()


# ---------------------------------------------------------------------------
# GoogleSlidesAuth.from_global tests
# ---------------------------------------------------------------------------

def _seed_global_credentials(db_session) -> None:
    """Insert global credentials into GoogleGlobalCredentials."""
    creds = GoogleGlobalCredentials(
        credentials_encrypted=encrypt_data(VALID_CREDENTIALS),
        uploaded_by="admin@test.com",
    )
    db_session.add(creds)
    db_session.commit()


class TestGoogleSlidesAuthFromGlobal:
    """Test DB-backed GoogleSlidesAuth construction via from_global()."""

    def test_from_global_loads_credentials_and_builds_auth(self, db_session):
        """from_global loads global credentials from GoogleGlobalCredentials, builds auth instance."""
        from src.services.google_slides_auth import GoogleSlidesAuth

        _seed_global_credentials(db_session)

        auth = GoogleSlidesAuth.from_global("user@test.com", db_session)
        assert auth is not None
        assert auth._db_mode is True
        assert auth.is_authorized() is False  # No token yet

    def test_from_global_raises_when_no_global_credentials(self, db_session):
        """from_global raises GoogleSlidesAuthError when no global credentials exist."""
        from src.services.google_slides_auth import GoogleSlidesAuth, GoogleSlidesAuthError

        with pytest.raises(GoogleSlidesAuthError, match="No global Google OAuth credentials"):
            GoogleSlidesAuth.from_global("user@test.com", db_session)

    def test_from_global_loads_and_decrypts_existing_user_token(self, db_session):
        """from_global loads and decrypts existing user token (user_identity only, no profile_id)."""
        from src.services.google_slides_auth import GoogleSlidesAuth

        _seed_global_credentials(db_session)
        token_json = json.dumps({
            "token": "valid",
            "refresh_token": "rt",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "x",
            "client_secret": "y",
            "scopes": ["https://www.googleapis.com/auth/presentations"],
            "expiry": None,
        })
        db_session.add(GoogleOAuthToken(
            user_identity="user@test.com",
            token_encrypted=encrypt_data(token_json),
        ))
        db_session.commit()

        auth = GoogleSlidesAuth.from_global("user@test.com", db_session)
        assert auth is not None
        assert auth._token_json == token_json
        assert auth._load_token() is not None  # Token loaded and decrypted

    def test_from_global_deletes_stale_token_on_decryption_failure(self, db_session):
        """from_global deletes stale tokens on decryption failure."""
        from src.services.google_slides_auth import GoogleSlidesAuth

        _seed_global_credentials(db_session)
        db_session.add(GoogleOAuthToken(
            user_identity="user@test.com",
            token_encrypted="not-a-valid-fernet-token",
        ))
        db_session.commit()

        auth = GoogleSlidesAuth.from_global("user@test.com", db_session)
        assert auth.is_authorized() is False

        # Stale token row should be cleaned up
        remaining = (
            db_session.query(GoogleOAuthToken)
            .filter_by(user_identity="user@test.com")
            .first()
        )
        assert remaining is None


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
# Google Slides auth status endpoint (no profile_id)
# ---------------------------------------------------------------------------

class TestGoogleSlidesAuthStatusEndpoint:
    """Test /api/export/google-slides/auth/status returns gracefully (no profile_id param)."""

    def test_auth_status_no_credentials(self, test_client):
        """Returns authorized=false when no global credentials are uploaded."""
        resp = test_client.get("/api/export/google-slides/auth/status")
        assert resp.status_code == 200
        assert resp.json()["authorized"] is False

    def test_auth_status_with_global_creds_but_no_token(self, test_client, session_factory):
        """Returns authorized=false when global creds exist but user has no token."""
        db = session_factory()
        creds = GoogleGlobalCredentials(
            credentials_encrypted=encrypt_data(VALID_CREDENTIALS),
            uploaded_by="admin@test.com",
        )
        db.add(creds)
        db.commit()
        db.close()

        resp = test_client.get("/api/export/google-slides/auth/status")
        assert resp.status_code == 200
        assert resp.json()["authorized"] is False
