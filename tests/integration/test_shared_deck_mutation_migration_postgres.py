from __future__ import annotations

import importlib
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.core.database import _run_migrations
from src.database.models.graph_configuration import GraphRelease
from src.database.models.session import SessionSlideDeck, UserSession

pytestmark = pytest.mark.postgres


def _restore_pre_table_schema(engine) -> None:
    """Force the real additive migration path after fixture create_all."""
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS shared_deck_mutation_event CASCADE"))
        conn.execute(
            text(
                "DROP TRIGGER IF EXISTS "
                "trg_user_sessions_collaboration_identity_immutable ON user_sessions"
            )
        )
        conn.execute(
            text(
                "DROP TRIGGER IF EXISTS "
                "trg_session_slide_decks_collaboration_identity_immutable "
                "ON session_slide_decks"
            )
        )
        conn.execute(
            text("ALTER TABLE user_sessions DROP COLUMN IF EXISTS collaboration_identity CASCADE")
        )
        conn.execute(
            text(
                "ALTER TABLE session_slide_decks "
                "DROP COLUMN IF EXISTS collaboration_identity CASCADE"
            )
        )


def _expect_integrity_error(engine, statement: str) -> None:
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(statement))


def _normalized(sql: str) -> str:
    return " ".join(sql.lower().replace('"', "").split())


def test_postgres_migrates_append_only_evidence_and_allows_only_parent_delete_set_null(
    postgres_engine,
):
    """Break caught: replay/backfill drift, mutable evidence, or FK SET NULL blocked/bypassed."""
    _restore_pre_table_schema(postgres_engine)
    now = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)
    with postgres_engine.begin() as conn:
        release_id = conn.execute(
            GraphRelease.__table__.insert()
            .values(
                version_number=7,
                previous_release_id=None,
                restored_from_release_id=None,
                release_note="migration lifecycle release",
                published_by="test:shared-deck-migration",
                published_at=now,
                effective_from=now,
                effective_to=None,
            )
            .returning(GraphRelease.id)
        ).scalar_one()
        root_id = conn.execute(
            text(
                "INSERT INTO user_sessions "
                "(session_id, created_by, graph_release_id, created_at, last_activity, is_processing) "
                "VALUES ('migration-root', 'owner@example.com', :release_id, :now, :now, false) "
                "RETURNING id"
            ),
            {"release_id": release_id, "now": now},
        ).scalar_one()
        actor_id = conn.execute(
            text(
                "INSERT INTO user_sessions "
                "(session_id, created_by, graph_release_id, created_at, last_activity, is_processing) "
                "VALUES ('migration-actor', 'actor@example.com', :release_id, :now, :now, false) "
                "RETURNING id"
            ),
            {"release_id": release_id, "now": now},
        ).scalar_one()
        deck_id = conn.execute(
            text(
                "INSERT INTO session_slide_decks "
                "(session_id, title, version, created_at, updated_at) "
                "VALUES (:root_id, 'Legacy shared deck', 0, :now, :now) RETURNING id"
            ),
            {"root_id": root_id, "now": now},
        ).scalar_one()

    _run_migrations(postgres_engine)
    with postgres_engine.connect() as conn:
        first_identities = conn.execute(
            text(
                "SELECT "
                "(SELECT collaboration_identity FROM user_sessions WHERE id = :root_id), "
                "(SELECT collaboration_identity FROM user_sessions WHERE id = :actor_id), "
                "(SELECT collaboration_identity FROM session_slide_decks WHERE id = :deck_id)"
            ),
            {"root_id": root_id, "actor_id": actor_id, "deck_id": deck_id},
        ).one()
    _run_migrations(postgres_engine)
    with postgres_engine.connect() as conn:
        second_identities = conn.execute(
            text(
                "SELECT "
                "(SELECT collaboration_identity FROM user_sessions WHERE id = :root_id), "
                "(SELECT collaboration_identity FROM user_sessions WHERE id = :actor_id), "
                "(SELECT collaboration_identity FROM session_slide_decks WHERE id = :deck_id)"
            ),
            {"root_id": root_id, "actor_id": actor_id, "deck_id": deck_id},
        ).one()
    assert second_identities == first_identities
    assert len({uuid.UUID(str(value)) for value in first_identities}) == 3

    inspector = inspect(postgres_engine)
    for table_name in ("user_sessions", "session_slide_decks"):
        identity_column = next(
            column
            for column in inspector.get_columns(table_name)
            if column["name"] == "collaboration_identity"
        )
        assert identity_column["nullable"] is False
        assert identity_column["default"] is not None

    event_columns = {
        column["name"]: column
        for column in inspector.get_columns("shared_deck_mutation_event")
    }
    assert event_columns["root_session_id"]["nullable"] is True
    assert event_columns["root_deck_id"]["nullable"] is True
    assert event_columns["actor_session_id"]["nullable"] is True
    for required in (
        "root_session_identity",
        "root_deck_identity",
        "actor_session_identity",
    ):
        assert event_columns[required]["nullable"] is False

    foreign_keys = {
        tuple(foreign_key["constrained_columns"]): foreign_key
        for foreign_key in inspector.get_foreign_keys("shared_deck_mutation_event")
    }
    for column in (("root_session_id",), ("root_deck_id",), ("actor_session_id",)):
        assert foreign_keys[column]["options"]["ondelete"] == "SET NULL"

    index_columns = {
        tuple(index["column_names"])
        for index in inspector.get_indexes("shared_deck_mutation_event")
    }
    assert (
        "root_deck_identity",
        "actor_session_identity",
        "graph_release_id",
    ) in index_columns
    assert (
        "root_session_identity",
        "actor_session_identity",
        "graph_release_id",
        "occurred_at",
    ) in index_columns

    checks = "\n".join(
        _normalized(check["sqltext"])
        for check in inspector.get_check_constraints("shared_deck_mutation_event")
    )
    assert "graph_release_id is null" in checks
    assert "graph_version is null" in checks
    for operation in (
        "save_deck",
        "save_deck_slides",
        "write_slide",
        "delete_slide",
        "write_deck_level",
        "insert_slide",
        "update_slide",
        "duplicate_slide",
        "reorder_slides",
        "restore_version",
    ):
        assert operation in checks
    assert "object_type" in checks

    with postgres_engine.connect() as conn:
        assert conn.scalar(
            text(
                "SELECT count(*) FROM pg_trigger "
                "WHERE tgrelid = 'shared_deck_mutation_event'::regclass "
                "AND tgname = 'trg_shared_deck_mutation_event_append_only' "
                "AND NOT tgisinternal"
            )
        ) == 1

    module = importlib.import_module("src.services.shared_deck_attribution")
    event_model = getattr(
        importlib.import_module("src.database.models.session"),
        "SharedDeckMutationEvent",
    )
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    with factory.begin() as db:
        root = db.get(UserSession, root_id)
        actor_session = db.get(UserSession, actor_id)
        deck = db.get(SessionSlideDeck, deck_id)
        event = module.record_shared_deck_mutation(
            db,
            requesting_session=actor_session,
            deck_owner=root,
            deck=deck,
            actor=module.MutationActor("migration-actor", release_id),
            operation="update_slide",
            object_type="deck",
            object_id="slide-4",
        )
        event_id = event.id

    with factory() as db:
        event = db.get(event_model, event_id)
        immutable_before = (
            event.root_session_identity,
            event.root_deck_identity,
            event.actor_session_identity,
            event.graph_release_id,
            event.graph_version,
            event.operation,
            event.object_type,
            event.object_id,
            event.occurred_at,
        )

    _expect_integrity_error(
        postgres_engine,
        f"UPDATE shared_deck_mutation_event SET operation = 'reorder_slides' WHERE id = {event_id}",
    )
    _expect_integrity_error(
        postgres_engine,
        f"UPDATE shared_deck_mutation_event SET root_session_id = NULL WHERE id = {event_id}",
    )
    _expect_integrity_error(
        postgres_engine,
        f"DELETE FROM shared_deck_mutation_event WHERE id = {event_id}",
    )

    with postgres_engine.begin() as conn:
        conn.execute(text("DELETE FROM session_slide_decks WHERE id = :id"), {"id": deck_id})
        conn.execute(text("DELETE FROM user_sessions WHERE id = :id"), {"id": root_id})
        conn.execute(text("DELETE FROM user_sessions WHERE id = :id"), {"id": actor_id})

    with factory() as db:
        event = db.get(event_model, event_id)
        assert (event.root_session_id, event.root_deck_id, event.actor_session_id) == (
            None,
            None,
            None,
        )
        assert (
            event.root_session_identity,
            event.root_deck_identity,
            event.actor_session_identity,
            event.graph_release_id,
            event.graph_version,
            event.operation,
            event.object_type,
            event.object_id,
            event.occurred_at,
        ) == immutable_before
        assert db.scalar(select(event_model.id).where(event_model.id == event_id)) == event_id
