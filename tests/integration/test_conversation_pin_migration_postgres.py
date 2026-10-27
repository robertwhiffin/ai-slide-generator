"""The Conversation Pin column's migration on PostgreSQL.

The only Postgres proof of ``user_sessions.graph_release_id``: nullable, indexed,
and an ``ON DELETE RESTRICT`` foreign key, through a migration that is safe to run
twice.  (The startup pin backfill this file also covered was deleted with Deck
Mode: a deck is pinned only when it locks to agent mode.)
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, text

from src.core.database import _run_migrations

pytestmark = pytest.mark.postgres


def _restore_pre_column_schema(engine) -> None:
    """Make the fixture exercise ALTER migration even after the ORM gains the column."""
    if "graph_release_id" not in {
        column["name"] for column in inspect(engine).get_columns("user_sessions")
    }:
        return
    with engine.begin() as conn:
        conn.execute(
            text("ALTER TABLE user_sessions DROP COLUMN graph_release_id CASCADE")
        )


def test_postgres_migrates_the_conversation_pin_column_idempotently(postgres_engine):
    _restore_pre_column_schema(postgres_engine)
    _run_migrations(postgres_engine)
    _run_migrations(postgres_engine)

    inspector = inspect(postgres_engine)
    graph_release_column = next(
        column
        for column in inspector.get_columns("user_sessions")
        if column["name"] == "graph_release_id"
    )
    assert graph_release_column["nullable"] is True
    assert "ix_user_sessions_graph_release_id" in {
        index["name"] for index in inspector.get_indexes("user_sessions")
    }
    with postgres_engine.connect() as conn:
        assert conn.scalar(
            text(
                "SELECT confdeltype FROM pg_constraint "
                "WHERE conname = 'fk_user_sessions_graph_release'"
            )
        ) == "r"
