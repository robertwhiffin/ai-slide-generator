"""Tests for GoogleGlobalCredentials model and GoogleOAuthToken without profile_id.

Phase 1: Global Credentials Model
- GoogleGlobalCredentials model (app-wide credentials storage)
- GoogleOAuthToken scoped by user_identity only (no profile_id)
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.core.database import Base
from src.database.models import GoogleGlobalCredentials, GoogleOAuthToken


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

    with db_engine.connect() as conn:
        conn.execute(text("DELETE FROM google_oauth_tokens"))
        conn.execute(text("DELETE FROM google_global_credentials"))
        conn.execute(text("DELETE FROM config_history"))
        conn.execute(text("DELETE FROM config_genie_spaces"))
        conn.execute(text("DELETE FROM config_prompts"))
        conn.execute(text("DELETE FROM config_ai_infra"))
        conn.execute(text("DELETE FROM config_profiles"))
        conn.commit()


# ---------------------------------------------------------------------------
# GoogleGlobalCredentials model tests
# ---------------------------------------------------------------------------

class TestGoogleGlobalCredentials:
    """Test GoogleGlobalCredentials model."""

    def test_model_creation_columns(self, db_session):
        """GoogleGlobalCredentials has id, credentials_encrypted, uploaded_by, created_at, updated_at."""
        creds = GoogleGlobalCredentials(
            credentials_encrypted="encrypted-blob",
            uploaded_by="admin@test.com",
        )
        db_session.add(creds)
        db_session.commit()

        loaded = db_session.get(GoogleGlobalCredentials, creds.id)
        assert loaded and loaded.id == creds.id
        assert loaded.credentials_encrypted == "encrypted-blob"
        assert loaded.uploaded_by == "admin@test.com"
        assert loaded.created_at is not None
        assert loaded.updated_at is not None

    def test_single_row_upsert_behavior(self, db_session):
        """Uploading a second time replaces, doesn't create duplicate."""
        g1 = GoogleGlobalCredentials(
            credentials_encrypted="enc1",
            uploaded_by="u1",
        )
        db_session.add(g1)
        db_session.commit()

        # Simulate second upload: update existing row
        row = db_session.query(GoogleGlobalCredentials).first()
        row.credentials_encrypted = "enc2"
        row.uploaded_by = "u2"
        db_session.commit()

        count = db_session.query(GoogleGlobalCredentials).count()
        assert count == 1
        assert row.credentials_encrypted == "enc2"
        assert row.uploaded_by == "u2"


# ---------------------------------------------------------------------------
# GoogleOAuthToken without profile_id tests
# ---------------------------------------------------------------------------

class TestGoogleOAuthTokenWithoutProfile:
    """Test GoogleOAuthToken with unique constraint on user_identity only."""

    def test_token_creation_without_profile_id(self, db_session):
        """GoogleOAuthToken can be created without profile_id."""
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

    def test_token_unique_constraint_on_user_identity(self, db_session):
        """Unique constraint on user_identity only (no profile_id)."""
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
