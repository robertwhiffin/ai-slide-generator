"""Tests for deck permissions migration (_migrate_deck_permissions_model).

Migration logic:
- Drop profile_id and profile_name from user_sessions
- Migrate CAN_VIEW → CAN_USE in config_profile_contributors
- Migrate CAN_VIEW → CAN_USE in config_profiles.global_permission
- All steps idempotent
"""
import os
import tempfile

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register models with Base
from src.core.database import Base, _run_migrations


@pytest.fixture
def sqlite_engine():
    """SQLite engine with temp file (survives connection open/close)."""
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


@pytest.fixture
def engine_with_legacy_columns(sqlite_engine):
    """Engine with tables created + legacy profile_id/profile_name columns added."""
    Base.metadata.create_all(bind=sqlite_engine)
    with sqlite_engine.begin() as conn:
        # Add legacy columns that the migration should drop
        insp = inspect(conn)
        cols = {c["name"] for c in insp.get_columns("user_sessions")}
        if "profile_id" not in cols:
            conn.execute(text(
                "ALTER TABLE user_sessions ADD COLUMN profile_id INTEGER"
            ))
        if "profile_name" not in cols:
            conn.execute(text(
                "ALTER TABLE user_sessions ADD COLUMN profile_name VARCHAR(255)"
            ))
        # Seed a profile with CAN_VIEW global_permission
        conn.execute(text(
            "INSERT INTO config_profiles (name, is_default, is_deleted, created_at, updated_at) "
            "VALUES ('test-profile', 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ))
        conn.execute(text(
            "UPDATE config_profiles SET global_permission = 'CAN_VIEW' WHERE name = 'test-profile'"
        ))
        # Seed a CAN_VIEW contributor
        conn.execute(text(
            "INSERT INTO config_profile_contributors "
            "(profile_id, identity_id, identity_type, identity_name, permission_level, created_at, updated_at) "
            "VALUES (1, 'user-1', 'USER', 'test@example.com', 'CAN_VIEW', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ))
    return sqlite_engine


class TestDeckPermissionsMigration:
    def test_profile_id_drop_attempted(self, engine_with_legacy_columns):
        """Migration attempts to drop profile_id. On SQLite < 3.35 this may silently
        fail (logged as warning). On PostgreSQL it will succeed. We verify the
        migration runs without raising."""
        _run_migrations(engine_with_legacy_columns, schema=None)
        # Migration should complete without error regardless of SQLite version

    def test_profile_name_drop_attempted(self, engine_with_legacy_columns):
        """Migration attempts to drop profile_name. Same SQLite caveat as above."""
        _run_migrations(engine_with_legacy_columns, schema=None)
        # On newer SQLite (3.35+), verify column is gone
        import sqlite3
        sqlite_version = tuple(int(x) for x in sqlite3.sqlite_version.split("."))
        if sqlite_version >= (3, 35, 0):
            with engine_with_legacy_columns.connect() as conn:
                insp = inspect(conn)
                columns = {c["name"] for c in insp.get_columns("user_sessions")}
            assert "profile_name" not in columns

    def test_global_permission_migrated_to_can_use(self, engine_with_legacy_columns):
        _run_migrations(engine_with_legacy_columns, schema=None)
        with engine_with_legacy_columns.connect() as conn:
            result = conn.execute(text(
                "SELECT global_permission FROM config_profiles WHERE name = 'test-profile'"
            )).fetchone()
        assert result[0] == "CAN_USE"

    def test_contributor_permission_migrated_to_can_use(self, engine_with_legacy_columns):
        _run_migrations(engine_with_legacy_columns, schema=None)
        with engine_with_legacy_columns.connect() as conn:
            result = conn.execute(text(
                "SELECT permission_level FROM config_profile_contributors WHERE identity_id = 'user-1'"
            )).fetchone()
        assert result[0] == "CAN_USE"

    def test_migration_is_idempotent(self, engine_with_legacy_columns):
        """Running migration twice should not raise."""
        _run_migrations(engine_with_legacy_columns, schema=None)
        _run_migrations(engine_with_legacy_columns, schema=None)  # Should not raise
        # Verify CAN_USE migration is still correct after second run
        with engine_with_legacy_columns.connect() as conn:
            result = conn.execute(text(
                "SELECT global_permission FROM config_profiles WHERE name = 'test-profile'"
            )).fetchone()
        assert result[0] == "CAN_USE"

    def test_can_edit_not_migrated(self, engine_with_legacy_columns):
        """CAN_EDIT should remain CAN_EDIT (only CAN_VIEW migrates)."""
        with engine_with_legacy_columns.begin() as conn:
            conn.execute(text(
                "INSERT INTO config_profile_contributors "
                "(profile_id, identity_id, identity_type, identity_name, permission_level, created_at, updated_at) "
                "VALUES (1, 'user-2', 'USER', 'editor@example.com', 'CAN_EDIT', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))
        _run_migrations(engine_with_legacy_columns, schema=None)
        with engine_with_legacy_columns.connect() as conn:
            result = conn.execute(text(
                "SELECT permission_level FROM config_profile_contributors WHERE identity_id = 'user-2'"
            )).fetchone()
        assert result[0] == "CAN_EDIT"
