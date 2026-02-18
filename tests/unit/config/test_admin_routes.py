"""Tests for admin API routes (global Google credentials)."""

import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from src.core.database import Base, get_db
from src.database.models import GoogleGlobalCredentials

VALID_CREDENTIALS = json.dumps({
    "installed": {
        "client_id": "test-id.apps.googleusercontent.com",
        "client_secret": "test-secret",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }
})


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
    for table in reversed(tables_to_create):
        table.drop(bind=engine, checkfirst=True)
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS config_history"))
        conn.commit()
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
        conn.execute(text("DELETE FROM google_global_credentials"))
        conn.execute(text("DELETE FROM google_oauth_tokens"))
        conn.execute(text("DELETE FROM config_history"))
        conn.execute(text("DELETE FROM config_genie_spaces"))
        conn.execute(text("DELETE FROM config_prompts"))
        conn.execute(text("DELETE FROM config_ai_infra"))
        conn.execute(text("DELETE FROM config_profiles"))
        conn.commit()


def test_post_google_credentials_valid_encrypts_and_stores(test_client, session_factory):
    """POST /api/admin/google-credentials with valid file encrypts and stores."""
    resp = test_client.post(
        "/api/admin/google-credentials",
        files={"file": ("credentials.json", VALID_CREDENTIALS, "application/json")},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["has_credentials"] is True

    db = session_factory()
    row = db.query(GoogleGlobalCredentials).first()
    db.close()
    assert row is not None
    assert row.credentials_encrypted is not None
    assert row.credentials_encrypted != VALID_CREDENTIALS


def test_post_google_credentials_invalid_json_returns_400(test_client):
    """POST /api/admin/google-credentials with invalid JSON returns 400."""
    resp = test_client.post(
        "/api/admin/google-credentials",
        files={"file": ("bad.json", "not json", "application/json")},
    )
    assert resp.status_code == 400


def test_post_google_credentials_missing_keys_returns_400(test_client):
    """POST /api/admin/google-credentials without installed/web key returns 400."""
    bad = json.dumps({"some_key": "some_val"})
    resp = test_client.post(
        "/api/admin/google-credentials",
        files={"file": ("creds.json", bad, "application/json")},
    )
    assert resp.status_code == 400
    assert "installed" in resp.json()["detail"]


def test_get_google_credentials_status_returns_true_when_exists(test_client):
    """GET /api/admin/google-credentials/status returns has_credentials=true when present."""
    test_client.post(
        "/api/admin/google-credentials",
        files={"file": ("credentials.json", VALID_CREDENTIALS, "application/json")},
    )
    resp = test_client.get("/api/admin/google-credentials/status")
    assert resp.status_code == 200
    assert resp.json()["has_credentials"] is True


def test_get_google_credentials_status_returns_false_when_empty(test_client):
    """GET /api/admin/google-credentials/status returns has_credentials=false when empty."""
    resp = test_client.get("/api/admin/google-credentials/status")
    assert resp.status_code == 200
    assert resp.json()["has_credentials"] is False


def test_delete_google_credentials_removes_and_returns_204(test_client):
    """DELETE /api/admin/google-credentials removes credentials and returns 204."""
    test_client.post(
        "/api/admin/google-credentials",
        files={"file": ("credentials.json", VALID_CREDENTIALS, "application/json")},
    )
    resp = test_client.delete("/api/admin/google-credentials")
    assert resp.status_code == 204

    status_resp = test_client.get("/api/admin/google-credentials/status")
    assert status_resp.json()["has_credentials"] is False


def test_upload_replaces_existing_credentials(test_client, session_factory):
    """Upload replaces existing credentials (upsert, no duplicate rows)."""
    creds_v1 = json.dumps({"installed": {"client_id": "v1"}})
    creds_v2 = json.dumps({"web": {"client_id": "v2"}})

    test_client.post(
        "/api/admin/google-credentials",
        files={"file": ("creds.json", creds_v1, "application/json")},
    )
    test_client.post(
        "/api/admin/google-credentials",
        files={"file": ("creds.json", creds_v2, "application/json")},
    )

    db = session_factory()
    rows = db.query(GoogleGlobalCredentials).all()
    db.close()
    assert len(rows) == 1
    # Decrypt and verify we have v2
    from src.core.encryption import decrypt_data
    decrypted = decrypt_data(rows[0].credentials_encrypted)
    assert "v2" in decrypted
    assert "web" in decrypted
