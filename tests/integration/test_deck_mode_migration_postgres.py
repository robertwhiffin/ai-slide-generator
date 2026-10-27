"""The Deck Mode migration on real PostgreSQL (spec 2026-10-22 §6).

The PostgreSQL branch adds ``user_sessions.deck_mode`` with a constant
``DEFAULT 'legacy'`` (which fills every existing row as part of the add) and then
drops the default, so decks created afterwards land NULL (not chosen yet).  The
SQLite unit tests cannot reach that branch.

Self-skips when no PostgreSQL is reachable (``postgres_engine``).
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, text

from src.core.database import _run_migrations

pytestmark = pytest.mark.postgres


def _restore_pre_column_schema(engine) -> None:
    """Make the fixture exercise the ALTER path even though create_all built the column."""
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE user_sessions DROP COLUMN IF EXISTS deck_mode"))
    assert "deck_mode" not in {
        column["name"] for column in inspect(engine).get_columns("user_sessions")
    }


def _insert_session(conn, session_id: str) -> None:
    """Raw SQL that omits deck_mode: only a database-side default could fill it."""
    conn.execute(
        text(
            "INSERT INTO user_sessions "
            "(session_id, created_by, created_at, last_activity, is_processing) "
            "VALUES (:sid, 'deck-mode-migration@example.com', CURRENT_TIMESTAMP, "
            "CURRENT_TIMESTAMP, false)"
        ),
        {"sid": session_id},
    )


def _deck_modes(engine) -> dict:
    with engine.connect() as conn:
        return dict(
            conn.execute(
                text("SELECT session_id, deck_mode FROM user_sessions")
            ).fetchall()
        )


def _deck_mode_column(engine):
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT column_default, is_nullable, data_type, "
                "character_maximum_length "
                "FROM information_schema.columns "
                "WHERE table_schema = current_schema() "
                "AND table_name = 'user_sessions' AND column_name = 'deck_mode'"
            )
        ).one_or_none()


def test_postgres_deck_mode_migration_fills_old_rows_once_and_drops_the_default(
    postgres_engine,
):
    _restore_pre_column_schema(postgres_engine)
    with postgres_engine.begin() as conn:
        _insert_session(conn, "old-deck-1")
        _insert_session(conn, "old-deck-2")

    _run_migrations(postgres_engine)
    _run_migrations(postgres_engine)

    assert _deck_modes(postgres_engine) == {
        "old-deck-1": "legacy",
        "old-deck-2": "legacy",
    }
    column = _deck_mode_column(postgres_engine)
    assert column is not None, "user_sessions.deck_mode was not added"
    assert column.column_default is None, (
        f"deck_mode kept a default ({column.column_default!r}): new decks would be "
        "born legacy"
    )
    assert column.is_nullable == "YES"
    assert column.data_type == "character varying"
    assert column.character_maximum_length == 16

    with postgres_engine.begin() as conn:
        _insert_session(conn, "new-deck")
    assert _deck_modes(postgres_engine)["new-deck"] is None

    with postgres_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE user_sessions SET deck_mode = 'agent' "
                "WHERE session_id = 'old-deck-1'"
            )
        )

    _run_migrations(postgres_engine)  # a later boot must not touch any row

    assert _deck_modes(postgres_engine) == {
        "old-deck-1": "agent",
        "old-deck-2": "legacy",
        "new-deck": None,
    }
