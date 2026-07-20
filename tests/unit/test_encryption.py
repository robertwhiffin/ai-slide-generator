"""Tests for the Lakebase-backed Fernet encryption utility (SDR-4437 CRITICAL-3)."""

from contextlib import contextmanager

import pytest
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.core.encryption import (
    decrypt_data,
    encrypt_data,
    get_encryption_key,
)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """In-memory DB with all tables + patched session factory and key file."""
    from src.core.database import Base
    import src.database.models  # noqa: F401 — registers all models

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    # init_db() may have stamped schemas onto shared metadata in another test;
    # unit tests run with LAKEBASE_SCHEMA unset so schemas are None here.
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

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
    monkeypatch.setattr("src.core.encryption._KEY_FILE", tmp_path / ".encryption_key")
    get_encryption_key.cache_clear()
    yield engine, _session
    get_encryption_key.cache_clear()


def _stored_key(engine) -> str | None:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT key_value FROM encryption_keys WHERE id = 1")
        ).first()
    return row[0] if row else None


def test_fresh_install_generates_and_persists_key(db):
    engine, _ = db
    key = get_encryption_key()
    Fernet(key)  # valid Fernet key
    assert _stored_key(engine) == key.decode()
    # Cached and stable across calls
    get_encryption_key.cache_clear()
    assert get_encryption_key() == key


def test_existing_row_wins_over_everything(db, tmp_path):
    engine, session = db
    existing = Fernet.generate_key().decode()
    with session() as s:
        s.execute(
            text(
                "INSERT INTO encryption_keys (id, key_value, created_at) "
                "VALUES (1, :k, CURRENT_TIMESTAMP)"
            ),
            {"k": existing},
        )
    # A stray legacy file must be ignored when the DB already has a key
    (tmp_path / ".encryption_key").write_text(Fernet.generate_key().decode())
    assert get_encryption_key() == existing.encode()


def test_legacy_key_file_seeds_empty_table(db, tmp_path):
    engine, _ = db
    legacy = Fernet.generate_key().decode()
    (tmp_path / ".encryption_key").write_text(legacy)
    assert get_encryption_key() == legacy.encode()
    assert _stored_key(engine) == legacy


def test_env_var_seeds_empty_table(db, monkeypatch):
    """SDR-4437: the one-time legacy→table migration. An empty table plus a
    GOOGLE_OAUTH_ENCRYPTION_KEY env var seeds the table from that env value."""
    engine, _ = db
    legacy = Fernet.generate_key().decode()
    monkeypatch.setenv("GOOGLE_OAUTH_ENCRYPTION_KEY", legacy)
    assert get_encryption_key() == legacy.encode()
    assert _stored_key(engine) == legacy


def test_env_var_takes_priority_over_key_file(db, tmp_path, monkeypatch):
    """When both are present on an empty table, the env var (migration source)
    wins over the legacy key file."""
    engine, _ = db
    env_key = Fernet.generate_key().decode()
    file_key = Fernet.generate_key().decode()
    (tmp_path / ".encryption_key").write_text(file_key)
    monkeypatch.setenv("GOOGLE_OAUTH_ENCRYPTION_KEY", env_key)
    assert get_encryption_key() == env_key.encode()
    assert _stored_key(engine) == env_key


def test_existing_row_ignores_env_var(db, monkeypatch):
    """One-time cutover: once the row exists, the env var is never consulted."""
    engine, session = db
    existing = Fernet.generate_key().decode()
    with session() as s:
        s.execute(
            text(
                "INSERT INTO encryption_keys (id, key_value, created_at) "
                "VALUES (1, :k, CURRENT_TIMESTAMP)"
            ),
            {"k": existing},
        )
    monkeypatch.setenv("GOOGLE_OAUTH_ENCRYPTION_KEY", Fernet.generate_key().decode())
    assert get_encryption_key() == existing.encode()


def test_concurrent_seed_converges_on_winner(db, monkeypatch):
    """If another worker inserts between our SELECT and INSERT, read-back wins."""
    engine, session = db
    winner = Fernet.generate_key().decode()
    loser = Fernet.generate_key()

    import src.core.encryption as enc

    def race_seed():
        with session() as s:
            s.execute(
                text(
                    "INSERT INTO encryption_keys (id, key_value, created_at) "
                    "VALUES (1, :k, CURRENT_TIMESTAMP)"
                ),
                {"k": winner},
            )
        return loser

    monkeypatch.setattr(enc, "_seed_value", race_seed)
    assert get_encryption_key() == winner.encode()


def test_encrypt_decrypt_roundtrip(db):
    for plaintext in ["hello world", '{"installed":{"client_id":"abc"}}', "", "a" * 10_000]:
        ciphertext = encrypt_data(plaintext)
        assert ciphertext != plaintext
        assert decrypt_data(ciphertext) == plaintext


def test_decrypt_with_wrong_key_raises(db):
    engine, session = db
    ciphertext = encrypt_data("secret")
    # Swap the stored key (simulates orphaned ciphertext)
    with session() as s:
        s.execute(
            text("UPDATE encryption_keys SET key_value = :k WHERE id = 1"),
            {"k": Fernet.generate_key().decode()},
        )
    get_encryption_key.cache_clear()
    with pytest.raises(InvalidToken):
        decrypt_data(ciphertext)


def test_corrupt_stored_key_fails_loudly(db, monkeypatch):
    engine, session = db
    with session() as s:
        s.execute(
            text(
                "INSERT INTO encryption_keys (id, key_value, created_at) "
                "VALUES (1, 'not-a-fernet-key', CURRENT_TIMESTAMP)"
            )
        )
    with pytest.raises(RuntimeError, match="not a valid Fernet key"):
        get_encryption_key()


def test_encryption_keys_table_created_by_create_all():
    """EncryptionKey is registered on Base so init_db's create_all creates it."""
    from sqlalchemy import inspect

    from src.core.database import Base
    import src.database.models  # noqa: F401

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    assert "encryption_keys" in insp.get_table_names()
    cols = {c["name"] for c in insp.get_columns("encryption_keys")}
    assert cols == {"id", "key_value", "created_at"}


def _load_run_module():
    """Load run.py by path: databricks-tellr-app is not installed in the venv
    (its editable install triggers the frontend/sidecar build)."""
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2]
        / "packages" / "databricks-tellr-app" / "databricks_tellr_app" / "run.py"
    )
    spec = importlib.util.spec_from_file_location("tellr_run", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_init_database_invokes_encryption_boot_hook(monkeypatch):
    """run.py::init_database must call ensure_encryption_key pre-fork."""
    run = _load_run_module()
    calls = []
    monkeypatch.setattr("src.core.database.init_db", lambda: None)
    monkeypatch.setattr(
        "src.core.init_default_profile.seed_defaults",
        lambda include_databricks: None,
    )
    monkeypatch.setattr(
        "src.core.encryption.ensure_encryption_key", lambda: calls.append(1)
    )
    run.init_database()
    assert calls == [1]


def test_init_database_exits_1_when_key_seed_fails(monkeypatch):
    """A key load/seed failure must abort the set -e boot command."""
    run = _load_run_module()
    monkeypatch.setattr("src.core.database.init_db", lambda: None)
    monkeypatch.setattr(
        "src.core.init_default_profile.seed_defaults",
        lambda include_databricks: None,
    )

    def _boom():
        raise RuntimeError("no grant")

    monkeypatch.setattr("src.core.encryption.ensure_encryption_key", _boom)
    with pytest.raises(SystemExit) as exc:
        run.init_database()
    assert exc.value.code == 1
