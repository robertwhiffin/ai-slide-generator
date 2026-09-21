from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError

from src.core.database import _run_migrations
from src.database.models.graph_configuration import (
    AgentDefinitionRevision,
    GraphDraft,
    GraphRelease,
    GraphReleaseAgent,
)

pytestmark = pytest.mark.postgres


def _revision_values(agent_key: str, *, digest_char: str = "a") -> dict[str, object]:
    return {
        "agent_key": agent_key,
        "definition_version": 2,
        "content_hash": digest_char * 64,
        "prompt_text": f"prompt for {agent_key}",
        "endpoint_name": "databricks-claude-opus-4-6",
        "temperature": 0.7,
        "max_tokens": 60000,
        "top_p": 0.95,
        "schema_overlay": {"field_overrides": {}, "additional_optional_fields": []},
        "assembly_rules": {"format_version": 1, "blocks": []},
        "protected_assembly_version": 1,
        "protected_assembly_digest": "b" * 64,
        "schema_contract_version": 1,
        "schema_contract_digest": "c" * 64,
        "created_by": "test:postgres",
    }


def _release_values(version_number: int, *, active: bool = True) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    return {
        "version_number": version_number,
        "previous_release_id": None,
        "restored_from_release_id": None,
        "release_note": f"release {version_number}",
        "published_by": "test:postgres",
        "published_at": now,
        "effective_from": now,
        "effective_to": None if active else now + timedelta(seconds=1),
    }


def _insert_revision(conn, agent_key: str, digest_char: str = "a") -> int:
    return conn.execute(
        AgentDefinitionRevision.__table__.insert()
        .values(**_revision_values(agent_key, digest_char=digest_char))
        .returning(AgentDefinitionRevision.id)
    ).scalar_one()


def _insert_release(conn, version_number: int, *, active: bool = True) -> int:
    return conn.execute(
        GraphRelease.__table__.insert()
        .values(**_release_values(version_number, active=active))
        .returning(GraphRelease.id)
    ).scalar_one()


def _expect_integrity_error(engine, statement) -> None:
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(statement)


def test_postgres_rejects_unknown_role_duplicate_hash_and_cross_role_mapping(
    postgres_engine,
) -> None:
    with postgres_engine.begin() as conn:
        architect_revision_id = _insert_revision(conn, "architect")
        release_id = _insert_release(conn, 1)

    _expect_integrity_error(
        postgres_engine,
        AgentDefinitionRevision.__table__.insert().values(
            **_revision_values("foreman", digest_char="f")
        ),
    )
    _expect_integrity_error(
        postgres_engine,
        AgentDefinitionRevision.__table__.insert().values(**_revision_values("architect")),
    )
    _expect_integrity_error(
        postgres_engine,
        GraphReleaseAgent.__table__.insert().values(
            graph_release_id=release_id,
            agent_key="builder",
            agent_definition_revision_id=architect_revision_id,
        ),
    )

    with postgres_engine.connect() as conn:
        assert conn.scalar(select(GraphReleaseAgent.graph_release_id)) is None
        assert (
            conn.scalar(
                select(AgentDefinitionRevision.id).where(
                    AgentDefinitionRevision.agent_key == "foreman"
                )
            )
            is None
        )
        assert conn.scalars(select(AgentDefinitionRevision.id)).all() == [architect_revision_id]


def test_postgres_enforces_one_active_release_valid_intervals_and_singleton_draft(
    postgres_engine,
) -> None:
    with postgres_engine.begin() as conn:
        closed_id = _insert_release(conn, 1, active=False)
        active_id = _insert_release(conn, 2, active=True)

    _expect_integrity_error(
        postgres_engine,
        GraphRelease.__table__.insert().values(**_release_values(3, active=True)),
    )
    invalid_interval = _release_values(4, active=False)
    invalid_interval["effective_to"] = invalid_interval["effective_from"]
    _expect_integrity_error(
        postgres_engine,
        GraphRelease.__table__.insert().values(**invalid_interval),
    )

    with postgres_engine.begin() as conn:
        conn.execute(
            GraphDraft.__table__.insert().values(
                id=1,
                base_release_id=active_id,
                lock_version=0,
                updated_by="test:postgres",
            )
        )
    _expect_integrity_error(
        postgres_engine,
        GraphDraft.__table__.insert().values(
            id=2,
            base_release_id=closed_id,
            lock_version=0,
            updated_by="test:postgres",
        ),
    )

    with postgres_engine.connect() as conn:
        assert conn.scalars(
            select(GraphRelease.version_number).order_by(GraphRelease.version_number)
        ).all() == [1, 2]
        assert conn.scalars(select(GraphDraft.id)).all() == [1]


def test_postgres_restricts_deletion_of_referenced_release_and_revision(postgres_engine) -> None:
    with postgres_engine.begin() as conn:
        revision_id = _insert_revision(conn, "architect")
        release_id = _insert_release(conn, 1)
        conn.execute(
            GraphReleaseAgent.__table__.insert().values(
                graph_release_id=release_id,
                agent_key="architect",
                agent_definition_revision_id=revision_id,
            )
        )

    _expect_integrity_error(
        postgres_engine,
        delete(AgentDefinitionRevision).where(AgentDefinitionRevision.id == revision_id),
    )
    _expect_integrity_error(
        postgres_engine,
        delete(GraphRelease).where(GraphRelease.id == release_id),
    )

    with postgres_engine.connect() as conn:
        assert conn.scalar(select(AgentDefinitionRevision.id)) == revision_id
        assert conn.scalar(select(GraphRelease.id)) == release_id


def test_postgres_mutation_guards_execute_trigger_bodies_and_allow_only_first_close(
    postgres_engine,
) -> None:
    with postgres_engine.begin() as conn:
        revision_id = _insert_revision(conn, "architect")
        release_id = _insert_release(conn, 1)
        conn.execute(
            GraphReleaseAgent.__table__.insert().values(
                graph_release_id=release_id,
                agent_key="architect",
                agent_definition_revision_id=revision_id,
            )
        )

    forbidden = (
        update(AgentDefinitionRevision)
        .where(AgentDefinitionRevision.id == revision_id)
        .values(prompt_text="mutated"),
        delete(AgentDefinitionRevision).where(AgentDefinitionRevision.id == revision_id),
        update(GraphReleaseAgent)
        .where(GraphReleaseAgent.graph_release_id == release_id)
        .values(agent_key="builder"),
        delete(GraphReleaseAgent).where(GraphReleaseAgent.graph_release_id == release_id),
        update(GraphRelease).where(GraphRelease.id == release_id).values(release_note="mutated"),
        delete(GraphRelease).where(GraphRelease.id == release_id),
    )
    for statement in forbidden:
        _expect_integrity_error(postgres_engine, statement)

    closed_at = datetime.now(timezone.utc) + timedelta(seconds=5)
    with postgres_engine.begin() as conn:
        assert (
            conn.execute(
                update(GraphRelease)
                .where(GraphRelease.id == release_id)
                .values(effective_to=closed_at)
            ).rowcount
            == 1
        )

    _expect_integrity_error(
        postgres_engine,
        update(GraphRelease).where(GraphRelease.id == release_id).values(effective_to=None),
    )
    _expect_integrity_error(
        postgres_engine,
        update(GraphRelease)
        .where(GraphRelease.id == release_id)
        .values(effective_to=closed_at + timedelta(seconds=1)),
    )

    with postgres_engine.connect() as conn:
        assert conn.scalar(select(AgentDefinitionRevision.prompt_text)) == "prompt for architect"
        assert conn.scalar(select(GraphRelease.release_note)) == "release 1"
        assert conn.scalar(select(GraphRelease.effective_to)) == closed_at
        assert conn.scalar(select(GraphReleaseAgent.agent_key)) == "architect"


def test_postgres_mutation_guard_migration_is_idempotent_and_schema_objects_are_active(
    postgres_engine,
) -> None:
    _run_migrations(postgres_engine)
    _run_migrations(postgres_engine)

    with postgres_engine.connect() as conn:
        triggers = conn.execute(
            text(
                "SELECT c.relname, t.tgname FROM pg_trigger t "
                "JOIN pg_class c ON c.oid = t.tgrelid "
                "WHERE NOT t.tgisinternal AND c.relname IN "
                "('agent_definition_revision', 'graph_release_agent', 'graph_release') "
                "ORDER BY c.relname, t.tgname"
            )
        ).all()
    assert triggers == [
        ("agent_definition_revision", "trg_agent_definition_revision_immutable"),
        ("graph_release", "trg_graph_release_immutable"),
        ("graph_release_agent", "trg_graph_release_agent_immutable"),
    ]

    with postgres_engine.begin() as conn:
        revision_id = _insert_revision(conn, "builder")
    _expect_integrity_error(
        postgres_engine,
        update(AgentDefinitionRevision)
        .where(AgentDefinitionRevision.id == revision_id)
        .values(prompt_text="body disabled"),
    )
