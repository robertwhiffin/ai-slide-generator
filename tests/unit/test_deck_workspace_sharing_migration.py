"""Tests for deck workspace sharing migration (user_sessions.global_permission)."""

import os
import tempfile

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register models with Base
from src.core.database import Base, _run_migrations


@pytest.fixture
def sqlite_engine():
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


class TestDeckWorkspaceSharingMigration:
    def test_global_permission_column_added(self, sqlite_engine):
        Base.metadata.create_all(bind=sqlite_engine)
        _run_migrations(sqlite_engine, schema=None)

        with sqlite_engine.connect() as conn:
            cols = {c["name"] for c in inspect(conn).get_columns("user_sessions")}
        assert "global_permission" in cols

    def test_migration_is_idempotent(self, sqlite_engine):
        Base.metadata.create_all(bind=sqlite_engine)
        _run_migrations(sqlite_engine, schema=None)
        _run_migrations(sqlite_engine, schema=None)

        with sqlite_engine.connect() as conn:
            cols = {c["name"] for c in inspect(conn).get_columns("user_sessions")}
        assert "global_permission" in cols

    def test_global_permission_accepts_deck_levels(self, sqlite_engine):
        Base.metadata.create_all(bind=sqlite_engine)
        _run_migrations(sqlite_engine, schema=None)

        with sqlite_engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO user_sessions "
                "(session_id, created_by, created_at, last_activity, is_processing, global_permission) "
                "VALUES ('sess-1', 'owner@test.com', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0, 'CAN_VIEW')"
            ))
            row = conn.execute(text(
                "SELECT global_permission FROM user_sessions WHERE session_id = 'sess-1'"
            )).fetchone()
        assert row[0] == "CAN_VIEW"
