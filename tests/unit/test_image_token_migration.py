"""Tests for the image_assets.token backfill migration (SDR-4437 F-TM-7)."""
import os
import tempfile

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register models with Base
from src.core.database import Base, _migrate_image_assets_add_token, _run_migrations


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


def _qual(t: str) -> str:
    return f'"{t}"'


class TestTokenBackfillMigration:
    def test_adds_token_column_and_backfills_legacy_rows(self, sqlite_engine):
        # Simulate a legacy image_assets table with NO token column.
        with sqlite_engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE image_assets ("
                "id INTEGER PRIMARY KEY, filename TEXT, category TEXT)"
            ))
            conn.execute(text(
                "INSERT INTO image_assets (id, filename) "
                "VALUES (1, 'a.png'), (2, 'b.png')"
            ))

        with sqlite_engine.begin() as conn:
            _migrate_image_assets_add_token(
                conn, inspect(conn), None, _qual, is_sqlite=True
            )

        with sqlite_engine.connect() as conn:
            cols = {c["name"] for c in inspect(conn).get_columns("image_assets")}
            assert "token" in cols
            rows = conn.execute(
                text("SELECT id, token FROM image_assets ORDER BY id")
            ).fetchall()

        tokens = [r[1] for r in rows]
        assert all(t and len(t) >= 20 for t in tokens)  # every row backfilled
        assert len(set(tokens)) == len(tokens)  # tokens are unique

    def test_migration_is_idempotent(self, sqlite_engine):
        with sqlite_engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE image_assets (id INTEGER PRIMARY KEY, filename TEXT)"
            ))
            conn.execute(text("INSERT INTO image_assets (id, filename) VALUES (1, 'a.png')"))

        with sqlite_engine.begin() as conn:
            _migrate_image_assets_add_token(conn, inspect(conn), None, _qual, is_sqlite=True)
        first = None
        with sqlite_engine.connect() as conn:
            first = conn.execute(text("SELECT token FROM image_assets WHERE id=1")).scalar()

        # Second run must be a no-op (must not re-add the column or change the token).
        with sqlite_engine.begin() as conn:
            _migrate_image_assets_add_token(conn, inspect(conn), None, _qual, is_sqlite=True)
        with sqlite_engine.connect() as conn:
            second = conn.execute(text("SELECT token FROM image_assets WHERE id=1")).scalar()

        assert first == second

    def test_run_migrations_leaves_token_present_on_fresh_schema(self, sqlite_engine):
        # Fresh create_all already includes the token column; migrations must not error.
        Base.metadata.create_all(bind=sqlite_engine)
        _run_migrations(sqlite_engine, schema=None)
        _run_migrations(sqlite_engine, schema=None)  # idempotent

        with sqlite_engine.connect() as conn:
            cols = {c["name"] for c in inspect(conn).get_columns("image_assets")}
        assert "token" in cols
