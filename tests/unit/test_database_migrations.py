"""Tests for database migrations (Phase 4: google_credentials_encrypted → global).

Migration logic:
- Copies first non-null google_credentials_encrypted from config_profiles to google_global_credentials
- Nulls out google_credentials_encrypted on all profile rows after copy
- Handles profile_id removal from google_oauth_tokens (SQLite: recreate table)
- All steps idempotent
"""

import os
import tempfile

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

import src.database.models  # noqa: F401 - register models with Base
from src.core.database import Base, init_db, _run_migrations


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sqlite_engine():
    """SQLite engine for migration tests.

    Uses a temp file so the DB persists across connection open/close
    (engine.begin() closes its connection on exit; in-memory would be destroyed).
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    yield engine
    engine.dispose()
    try:
        os.unlink(path)
    except OSError:
        pass


def _create_old_config_profiles(conn, qualified_table: str):
    """Create config_profiles with OLD schema including google_credentials_encrypted."""
    conn.execute(text(f"""
        CREATE TABLE {qualified_table} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(100) NOT NULL UNIQUE,
            description TEXT,
            is_default BOOLEAN DEFAULT FALSE NOT NULL,
            is_deleted BOOLEAN DEFAULT FALSE NOT NULL,
            deleted_at TIMESTAMP NULL,
            created_at DATETIME NOT NULL,
            created_by VARCHAR(255),
            updated_at DATETIME NOT NULL,
            updated_by VARCHAR(255),
            google_credentials_encrypted TEXT
        )
    """))
    conn.commit()


def _create_google_global_credentials(conn, qualified_table: str):
    """Create empty google_global_credentials table."""
    conn.execute(text(f"""
        CREATE TABLE {qualified_table} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            credentials_encrypted TEXT NOT NULL,
            uploaded_by VARCHAR(255),
            created_at DATETIME,
            updated_at DATETIME
        )
    """))
    conn.commit()


# ---------------------------------------------------------------------------
# Test: migration creates google_global_credentials table
# ---------------------------------------------------------------------------

def test_migration_creates_google_global_credentials_table(sqlite_engine):
    """init_db (create_all + migrations) ensures google_global_credentials table exists."""
    with patch("src.core.database.get_engine", return_value=sqlite_engine):
        init_db()

    inspector = inspect(sqlite_engine)
    assert "google_global_credentials" in inspector.get_table_names()


# ---------------------------------------------------------------------------
# Test: migration copies first non-null credentials to global
# ---------------------------------------------------------------------------

def test_migration_copies_first_credentials_to_global(sqlite_engine):
    """Migration copies first non-null google_credentials_encrypted from config_profiles to global table."""
    with sqlite_engine.connect() as conn:
        _create_old_config_profiles(conn, "config_profiles")
        _create_google_global_credentials(conn, "google_global_credentials")
        conn.execute(text("""
            INSERT INTO config_profiles (name, is_default, is_deleted, created_at, updated_at, google_credentials_encrypted)
            VALUES ('p1', 0, 0, datetime('now'), datetime('now'), 'encrypted-blob-1'),
                   ('p2', 1, 0, datetime('now'), datetime('now'), 'encrypted-blob-2')
        """))
        conn.commit()

    _run_migrations(sqlite_engine, schema=None)

    with sqlite_engine.connect() as conn:
        result = conn.execute(text("SELECT credentials_encrypted FROM google_global_credentials")).fetchone()
        assert result is not None, "Migration should have copied credentials to global table"
        assert result[0] == "encrypted-blob-1"


# ---------------------------------------------------------------------------
# Test: migration nulls out credentials on all profile rows
# ---------------------------------------------------------------------------

def test_migration_nulls_all_profile_credentials(sqlite_engine):
    """Migration nulls out google_credentials_encrypted on all profile rows after copy."""
    with sqlite_engine.connect() as conn:
        _create_old_config_profiles(conn, "config_profiles")
        _create_google_global_credentials(conn, "google_global_credentials")
        conn.execute(text("""
            INSERT INTO config_profiles (name, is_default, is_deleted, created_at, updated_at, google_credentials_encrypted)
            VALUES ('p1', 0, 0, datetime('now'), datetime('now'), 'encrypted-blob')
        """))
        conn.commit()

    _run_migrations(sqlite_engine, schema=None)

    with sqlite_engine.connect() as conn:
        rows = conn.execute(text("SELECT google_credentials_encrypted FROM config_profiles")).fetchall()
        assert all(r[0] is None for r in rows)


# ---------------------------------------------------------------------------
# Test: migration is idempotent
# ---------------------------------------------------------------------------

def test_migration_is_idempotent(sqlite_engine):
    """Running migration twice is safe; no duplicate rows, no errors."""
    with sqlite_engine.connect() as conn:
        _create_old_config_profiles(conn, "config_profiles")
        _create_google_global_credentials(conn, "google_global_credentials")
        conn.execute(text("""
            INSERT INTO config_profiles (name, is_default, is_deleted, created_at, updated_at, google_credentials_encrypted)
            VALUES ('p1', 0, 0, datetime('now'), datetime('now'), 'encrypted-blob')
        """))
        conn.commit()

    _run_migrations(sqlite_engine, schema=None)
    _run_migrations(sqlite_engine, schema=None)

    with sqlite_engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM google_global_credentials")).scalar()
        assert count == 1
        rows = conn.execute(text("SELECT google_credentials_encrypted FROM config_profiles")).fetchall()
        assert all(r[0] is None for r in rows)
