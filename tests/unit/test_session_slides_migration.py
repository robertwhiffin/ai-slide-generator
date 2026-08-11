"""Tests for the row-per-slide schema migration.

Task 2 of PR1 (row-per-slide rebuild). Tests are written TDD-style: they
must FAIL until _migrate_row_per_slide_schema is implemented in database.py.

Design:
- Each test creates a fresh in-memory / temp-file SQLite engine.
- To exercise the real ALTER path (not just create_all), most tests:
    1. Call Base.metadata.create_all() so the tables exist with current ORM schema.
    2. DROP the target columns (simulating a pre-migration production DB).
    3. Call _run_migrations() and assert the columns reappear.
- The idempotency test calls _run_migrations() twice and asserts no error.
- A separate test exercises _migrate_row_per_slide_schema directly without
  pre-dropping columns, confirming it is a no-op when columns already exist.
"""

import os
import tempfile

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register all models with Base
from src.core.database import Base, _run_migrations, _migrate_row_per_slide_schema


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_engine():
    """Isolated temp-file SQLite engine that persists across engine.begin() calls.

    In-memory SQLite would be destroyed on connection close, but _run_migrations
    uses engine.begin() which closes its connection on exit.
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _drop_column_if_exists(engine, table, column):
    """Drop a column from a table (SQLite >= 3.35 required; we have 3.51)."""
    with engine.begin() as conn:
        cols = {c["name"] for c in inspect(conn).get_columns(table)}
        if column in cols:
            conn.execute(text(f'ALTER TABLE "{table}" DROP COLUMN "{column}"'))


def _get_columns(engine, table):
    with engine.connect() as conn:
        return {c["name"] for c in inspect(conn).get_columns(table)}


# ---------------------------------------------------------------------------
# Test: session_slides table is created by create_all (ORM-driven)
# ---------------------------------------------------------------------------


def test_session_slides_table_created(sqlite_engine):
    """session_slides table is present after Base.metadata.create_all()."""
    Base.metadata.create_all(bind=sqlite_engine)
    with sqlite_engine.connect() as conn:
        tables = inspect(conn).get_table_names()
    assert "session_slides" in tables


# ---------------------------------------------------------------------------
# Test: _migrate_row_per_slide_schema adds missing columns
# ---------------------------------------------------------------------------


def test_migration_adds_deck_spec_json_to_session_slide_decks(sqlite_engine):
    """_run_migrations adds deck_spec_json to session_slide_decks when missing."""
    Base.metadata.create_all(bind=sqlite_engine)
    # Simulate old DB: drop the new column
    _drop_column_if_exists(sqlite_engine, "session_slide_decks", "deck_spec_json")
    assert "deck_spec_json" not in _get_columns(sqlite_engine, "session_slide_decks")

    _run_migrations(sqlite_engine, schema=None)

    assert "deck_spec_json" in _get_columns(sqlite_engine, "session_slide_decks")


def test_migration_adds_css_to_session_slide_decks(sqlite_engine):
    """_run_migrations adds css to session_slide_decks when missing."""
    Base.metadata.create_all(bind=sqlite_engine)
    _drop_column_if_exists(sqlite_engine, "session_slide_decks", "css")
    assert "css" not in _get_columns(sqlite_engine, "session_slide_decks")

    _run_migrations(sqlite_engine, schema=None)

    assert "css" in _get_columns(sqlite_engine, "session_slide_decks")


def test_migration_adds_external_scripts_json_to_session_slide_decks(sqlite_engine):
    """_run_migrations adds external_scripts_json to session_slide_decks when missing."""
    Base.metadata.create_all(bind=sqlite_engine)
    _drop_column_if_exists(sqlite_engine, "session_slide_decks", "external_scripts_json")
    assert "external_scripts_json" not in _get_columns(sqlite_engine, "session_slide_decks")

    _run_migrations(sqlite_engine, schema=None)

    assert "external_scripts_json" in _get_columns(sqlite_engine, "session_slide_decks")


def test_migration_adds_head_meta_json_to_session_slide_decks(sqlite_engine):
    """_run_migrations adds head_meta_json to session_slide_decks when missing.

    Final review F5: head_meta is a real deck field (charset/viewport) that the row
    read path dropped.  It now has a dedicated column like css and
    external_scripts_json, so the ALTER path must cover it for live databases.
    """
    Base.metadata.create_all(bind=sqlite_engine)
    _drop_column_if_exists(sqlite_engine, "session_slide_decks", "head_meta_json")
    assert "head_meta_json" not in _get_columns(sqlite_engine, "session_slide_decks")

    _run_migrations(sqlite_engine, schema=None)

    assert "head_meta_json" in _get_columns(sqlite_engine, "session_slide_decks")


def test_migration_adds_deck_spec_json_to_slide_deck_versions(sqlite_engine):
    """_run_migrations adds deck_spec_json to slide_deck_versions when missing."""
    Base.metadata.create_all(bind=sqlite_engine)
    _drop_column_if_exists(sqlite_engine, "slide_deck_versions", "deck_spec_json")
    assert "deck_spec_json" not in _get_columns(sqlite_engine, "slide_deck_versions")

    _run_migrations(sqlite_engine, schema=None)

    assert "deck_spec_json" in _get_columns(sqlite_engine, "slide_deck_versions")


# ---------------------------------------------------------------------------
# Test: migration is idempotent (core requirement)
# ---------------------------------------------------------------------------


def test_migration_is_idempotent(sqlite_engine):
    """Running _run_migrations twice does not raise and leaves columns in place.

    Drop the target columns BEFORE the first run so the first call must add them
    and the second call is a true no-op against already-present columns.
    This proves: (a) the migration adds columns when absent, and (b) it does not
    error when they already exist — the real production idempotency property.
    """
    Base.metadata.create_all(bind=sqlite_engine)
    # Simulate pre-migration live DB: drop the columns Task 2 is responsible for
    _drop_column_if_exists(sqlite_engine, "session_slide_decks", "deck_spec_json")
    _drop_column_if_exists(sqlite_engine, "session_slide_decks", "css")
    _drop_column_if_exists(sqlite_engine, "session_slide_decks", "external_scripts_json")
    _drop_column_if_exists(sqlite_engine, "session_slide_decks", "head_meta_json")
    _drop_column_if_exists(sqlite_engine, "slide_deck_versions", "deck_spec_json")

    # First call — adds the columns
    _run_migrations(sqlite_engine, schema=None)
    # Second call — must not raise (idempotency)
    _run_migrations(sqlite_engine, schema=None)

    assert "deck_spec_json" in _get_columns(sqlite_engine, "session_slide_decks")
    assert "css" in _get_columns(sqlite_engine, "session_slide_decks")
    assert "external_scripts_json" in _get_columns(sqlite_engine, "session_slide_decks")
    assert "head_meta_json" in _get_columns(sqlite_engine, "session_slide_decks")
    assert "deck_spec_json" in _get_columns(sqlite_engine, "slide_deck_versions")


# ---------------------------------------------------------------------------
# Test: migration no-ops when all columns already exist
# ---------------------------------------------------------------------------


def test_migration_noop_when_columns_already_present(sqlite_engine):
    """_migrate_row_per_slide_schema is a no-op when all columns already exist.

    Exercises the helper directly (columns present from create_all, not dropped).
    """
    Base.metadata.create_all(bind=sqlite_engine)

    with sqlite_engine.begin() as conn:
        inspector = inspect(conn)
        # Call helper directly; must not raise even when all columns exist
        _migrate_row_per_slide_schema(conn, inspector, schema=None, _qual=lambda t: f'"{t}"', is_sqlite=True)

    # Columns still present
    assert "deck_spec_json" in _get_columns(sqlite_engine, "session_slide_decks")
    assert "css" in _get_columns(sqlite_engine, "session_slide_decks")
    assert "external_scripts_json" in _get_columns(sqlite_engine, "session_slide_decks")
    assert "deck_spec_json" in _get_columns(sqlite_engine, "slide_deck_versions")
