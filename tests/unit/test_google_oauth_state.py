"""SDR-4437 MEDIUM-3: OAuth state nonce + server-side PKCE + postMessage origin.

Spec acceptance list: valid nonce; double-consume; cross-user; expired;
unknown nonce; concurrent consume (exactly one winner).
"""

import json
import re
import threading
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.core.database import Base, get_db
from src.core.encryption import encrypt_data
from src.database.models import GoogleGlobalCredentials
from src.database.models.oauth_state import OAuthState

CALLBACK = "/api/export/google-slides/auth/callback"
AUTH_URL = "/api/export/google-slides/auth/url"

VALID_CREDENTIALS = json.dumps({
    "installed": {
        "client_id": "test-id.apps.googleusercontent.com",
        "client_secret": "test-secret",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }
})


@pytest.fixture
def db_setup():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield engine, factory
    engine.dispose()


@pytest.fixture(autouse=True)
def _encryption_db(db_setup, monkeypatch):
    """Route get_encryption_key's DB access to this test's engine (SDR-4437).

    Without this, ``encrypt_data`` in ``_seed_credentials`` reaches for the
    real global Postgres engine (``encryption_keys`` table absent).
    """
    from contextlib import contextmanager

    from src.core.encryption import get_encryption_key

    _, factory = db_setup

    @contextmanager
    def _session():
        s = factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    monkeypatch.setattr("src.core.database.get_db_session", _session)
    get_encryption_key.cache_clear()
    yield
    get_encryption_key.cache_clear()


@pytest.fixture
def client(db_setup):
    _, factory = db_setup
    from src.api.main import app

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


def _seed_credentials(factory):
    db = factory()
    db.add(
        GoogleGlobalCredentials(
            credentials_encrypted=encrypt_data(VALID_CREDENTIALS),
            uploaded_by="admin@test.com",
        )
    )
    db.commit()
    db.close()


def _insert_state(factory, nonce="nonce-1", user="local_dev",
                  verifier="verif-1", created_at=None):
    db = factory()
    row = OAuthState(nonce=nonce, user_identity=user, code_verifier=verifier)
    if created_at is not None:
        row.created_at = created_at
    db.add(row)
    db.commit()
    db.close()


@pytest.fixture
def fake_auth():
    """Patch the auth object the callback builds, recording authorize()."""
    auth = MagicMock()
    with patch(
        "src.api.routes.google_slides.GoogleSlidesAuth"
    ) as cls:
        cls.from_global.return_value = auth
        yield auth


# --- /auth/url stores a server-side row -------------------------------------


def test_auth_url_creates_nonce_row_with_server_side_verifier(client, db_setup):
    _, factory = db_setup
    _seed_credentials(factory)

    resp = client.get(AUTH_URL)
    assert resp.status_code == 200

    state = parse_qs(urlparse(resp.json()["url"]).query)["state"][0]
    # State is the bare nonce — a URL-safe token, not a JSON payload (no
    # user field, no code_verifier). Assert the shape rather than substring
    # absence: substring checks on a random token are theoretically flaky.
    assert re.fullmatch(r"[A-Za-z0-9_-]+", state)

    db = factory()
    row = db.query(OAuthState).filter(OAuthState.nonce == state).one()
    assert row.user_identity == "local_dev"  # ENVIRONMENT=test identity
    assert row.code_verifier  # verifier stored server-side only
    db.close()


# --- callback: the six spec cases --------------------------------------------


def test_callback_valid_nonce_authorizes_and_consumes(client, db_setup, fake_auth):
    _, factory = db_setup
    _insert_state(factory, nonce="nonce-ok", verifier="verif-xyz")

    resp = client.get(CALLBACK, params={"code": "code-1", "state": "nonce-ok"})
    assert resp.status_code == 200
    assert '"success": true' in resp.text  # json.dumps payload in the page
    fake_auth.authorize.assert_called_once()
    assert fake_auth.authorize.call_args.kwargs["code_verifier"] == "verif-xyz"

    db = factory()
    assert db.query(OAuthState).count() == 0  # consumed
    db.close()


def test_callback_double_consume_rejected(client, db_setup, fake_auth):
    _, factory = db_setup
    _insert_state(factory, nonce="nonce-once")

    first = client.get(CALLBACK, params={"code": "c", "state": "nonce-once"})
    second = client.get(CALLBACK, params={"code": "c", "state": "nonce-once"})
    assert first.status_code == 200 and second.status_code == 200
    assert fake_auth.authorize.call_count == 1  # replay did not re-authorize
    assert "Authorization Failed" in second.text


def test_callback_cross_user_nonce_rejected(client, db_setup, fake_auth):
    _, factory = db_setup
    _insert_state(factory, nonce="nonce-mallory", user="mallory@evil.test")

    resp = client.get(CALLBACK, params={"code": "c", "state": "nonce-mallory"})
    assert "Authorization Failed" in resp.text
    fake_auth.authorize.assert_not_called()


def test_callback_expired_nonce_rejected(client, db_setup, fake_auth):
    _, factory = db_setup
    _insert_state(
        factory,
        nonce="nonce-old",
        created_at=datetime.utcnow() - timedelta(minutes=30),
    )

    resp = client.get(CALLBACK, params={"code": "c", "state": "nonce-old"})
    assert "Authorization Failed" in resp.text
    fake_auth.authorize.assert_not_called()


def test_callback_unknown_or_missing_nonce_rejected(client, db_setup, fake_auth):
    resp = client.get(CALLBACK, params={"code": "c", "state": "never-issued"})
    assert "Authorization Failed" in resp.text
    resp = client.get(CALLBACK, params={"code": "c", "state": ""})
    assert "Authorization Failed" in resp.text
    fake_auth.authorize.assert_not_called()


def test_callback_consent_denied_no_code_returns_failure_page(
    client, db_setup, fake_auth
):
    """?error=...&state=... with NO code: popup-contract page, not a 422."""
    _, factory = db_setup
    _insert_state(factory, nonce="nonce-denied")

    resp = client.get(
        CALLBACK, params={"error": "access_denied", "state": "nonce-denied"}
    )
    assert resp.status_code == 200
    assert "Authorization Failed" in resp.text
    fake_auth.authorize.assert_not_called()

    db = factory()
    assert db.query(OAuthState).count() == 0  # nonce retired anyway
    db.close()


def test_concurrent_consume_exactly_one_winner(tmp_path):
    """Atomic DELETE ... RETURNING: one winner under concurrent callbacks."""
    from src.api.routes.google_slides import _consume_oauth_state

    engine = create_engine(
        f"sqlite:///{tmp_path / 'nonce.db'}", connect_args={"timeout": 10}
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)

    db = factory()
    db.add(OAuthState(nonce="race", user_identity="u", code_verifier="v"))
    db.commit()
    db.close()

    results = []
    barrier = threading.Barrier(2)

    def consume():
        session = factory()
        try:
            barrier.wait()
            results.append(_consume_oauth_state(session, "race"))
        finally:
            session.close()

    threads = [threading.Thread(target=consume) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(r is not None for r in results) == 1


# --- postMessage origin + no error reflection --------------------------------


def test_callback_html_uses_explicit_origin_not_wildcard(client, db_setup, fake_auth):
    _, factory = db_setup
    _insert_state(factory, nonce="nonce-origin")

    ok = client.get(CALLBACK, params={"code": "c", "state": "nonce-origin"})
    bad = client.get(CALLBACK, params={"code": "c", "state": "never-issued"})
    for resp in (ok, bad):
        assert "postMessage" in resp.text
        # No wildcard targetOrigin anywhere in the page.
        assert "'*'" not in resp.text and '"*"' not in resp.text
        # TestClient base_url origin appears as the explicit target.
        assert "http://testserver" in resp.text


def test_callback_failure_html_never_reflects_exception(client, db_setup, fake_auth):
    _, factory = db_setup
    _insert_state(factory, nonce="nonce-boom")
    fake_auth.authorize.side_effect = ValueError("SECRET-INTERNAL-DETAIL")

    resp = client.get(CALLBACK, params={"code": "c", "state": "nonce-boom"})
    assert resp.status_code == 200
    assert "Authorization Failed" in resp.text
    assert "SECRET-INTERNAL-DETAIL" not in resp.text
