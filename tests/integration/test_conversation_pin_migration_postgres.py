from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import sessionmaker

from src.core.database import _run_migrations
from src.database.models.session import SessionMessage, UserSession
from src.services.graph_configuration import bootstrap_graph_configuration

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


def test_postgres_migrates_and_backfills_conversation_pins_deterministically(
    postgres_engine,
):
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

    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    bootstrap = bootstrap_graph_configuration(factory)
    v1_id = bootstrap.release_id
    timestamp = datetime(2026, 9, 22, 10, 0, 0)

    with factory.begin() as db:
        roots = {
            name: UserSession(
                session_id=name,
                created_by="migration-test@example.com",
                created_at=timestamp,
                last_activity=timestamp,
            )
            for name in (
                "graph-root",
                "tie-graph-root",
                "tie-legacy-root",
                "later-marker-root",
                "empty-root",
                "historical-pre-pinned-root",
            )
        }
        roots["historical-pre-pinned-root"].graph_release_id = v1_id
        db.add_all(roots.values())
        db.flush()

        # A contributor's own marker never overrides its legacy root owner.
        graph_contributor = UserSession(
            session_id="graph-contributor",
            created_by="contributor@example.com",
            parent_session_id=roots["later-marker-root"].id,
            created_at=timestamp,
            last_activity=timestamp,
        )
        # A plain contributor inherits its graph root owner's V1 pin.
        legacy_contributor = UserSession(
            session_id="legacy-contributor",
            created_by="contributor@example.com",
            parent_session_id=roots["graph-root"].id,
            created_at=timestamp,
            last_activity=timestamp,
        )
        db.add_all((graph_contributor, legacy_contributor))
        db.flush()

        db.add_all(
            (
                SessionMessage(
                    id=101,
                    session_id=roots["graph-root"].id,
                    role="user",
                    content="USE AGENT MODE build a deck",
                    created_at=timestamp,
                ),
                SessionMessage(
                    id=102,
                    session_id=roots["tie-graph-root"].id,
                    role="user",
                    content="USE AGENT MODE first by id",
                    created_at=timestamp,
                ),
                SessionMessage(
                    id=103,
                    session_id=roots["tie-graph-root"].id,
                    role="user",
                    content="plain second by id",
                    created_at=timestamp,
                ),
                SessionMessage(
                    id=104,
                    session_id=roots["tie-legacy-root"].id,
                    role="user",
                    content="plain first by id",
                    created_at=timestamp,
                ),
                SessionMessage(
                    id=105,
                    session_id=roots["tie-legacy-root"].id,
                    role="user",
                    content="USE AGENT MODE second by id",
                    created_at=timestamp,
                ),
                SessionMessage(
                    id=106,
                    session_id=roots["later-marker-root"].id,
                    role="user",
                    content="plain first turn",
                    created_at=timestamp,
                ),
                SessionMessage(
                    id=107,
                    session_id=roots["later-marker-root"].id,
                    role="user",
                    content="USE AGENT MODE later turn",
                    created_at=timestamp + timedelta(seconds=1),
                ),
                SessionMessage(
                    id=108,
                    session_id=graph_contributor.id,
                    role="user",
                    content="USE AGENT MODE contributor-only marker",
                    created_at=timestamp,
                ),
                SessionMessage(
                    id=109,
                    session_id=legacy_contributor.id,
                    role="user",
                    content="plain contributor turn",
                    created_at=timestamp,
                ),
                SessionMessage(
                    id=110,
                    session_id=roots["historical-pre-pinned-root"].id,
                    role="user",
                    content="USE AGENT MODE already pinned",
                    created_at=timestamp,
                ),
            )
        )

    from src.services.conversation_pins import BackfillResult, backfill_conversation_pins

    assert backfill_conversation_pins(factory) == BackfillResult(v1_id, 1, 3)
    with factory() as db:
        identity_map = dict(
            db.execute(
                select(UserSession.session_id, UserSession.graph_release_id).order_by(
                    UserSession.session_id
                )
            ).all()
        )
    assert identity_map == {
        "empty-root": None,
        "graph-contributor": None,
        "graph-root": v1_id,
        "historical-pre-pinned-root": v1_id,
        "later-marker-root": None,
        "legacy-contributor": v1_id,
        "tie-graph-root": v1_id,
        "tie-legacy-root": None,
    }
    assert backfill_conversation_pins(factory) == BackfillResult(v1_id, 1, 0)
