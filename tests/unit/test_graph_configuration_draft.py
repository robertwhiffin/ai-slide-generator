from __future__ import annotations

from collections.abc import Iterator
from dataclasses import asdict

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401
from src.core.database import Base
from src.database.models.graph_configuration import (
    AgentDefinitionRevision,
    GraphDraft,
    GraphDraftAgent,
    GraphRelease,
    GraphReleaseAgent,
)
from src.services.graph_configuration import (
    DraftContentRejected,
    DraftSaveConflict,
    EditableModelDraft,
    GraphConfiguration,
)
from src.services.graph_configuration_content import definition_content_from_row
from src.services.graph_definition_manifest import (
    GRAPH_V1_AGENT_KEYS,
    DefinitionContent,
    definition_content_hash,
    load_graph_v1_manifest,
)


@pytest.fixture
def session_factory() -> Iterator[sessionmaker]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    GraphConfiguration().bootstrap_v1(factory)
    try:
        yield factory
    finally:
        engine.dispose()


def _editable(content: DefinitionContent, **updates: object) -> EditableModelDraft:
    values = {
        "prompt_text": content.prompt_text,
        "endpoint_name": content.model.endpoint_name,
        "temperature": float(content.model.temperature),
        "max_tokens": content.model.max_tokens,
        "top_p": float(content.model.top_p),
    }
    values.update(updates)
    return EditableModelDraft(**values)


def _database_snapshot(factory: sessionmaker) -> dict[str, list[tuple[object, ...]]]:
    with factory() as session:
        return {
            "revisions": list(
                session.execute(
                    select(*AgentDefinitionRevision.__table__.columns).order_by(
                        AgentDefinitionRevision.id
                    )
                ).all()
            ),
            "releases": list(
                session.execute(
                    select(*GraphRelease.__table__.columns).order_by(GraphRelease.id)
                ).all()
            ),
            "mappings": list(
                session.execute(
                    select(*GraphReleaseAgent.__table__.columns).order_by(
                        GraphReleaseAgent.graph_release_id, GraphReleaseAgent.agent_key
                    )
                ).all()
            ),
            "draft": list(session.execute(select(*GraphDraft.__table__.columns)).all()),
            "draft_agents": list(
                session.execute(
                    select(*GraphDraftAgent.__table__.columns).order_by(
                        GraphDraftAgent.agent_key
                    )
                ).all()
            ),
        }


def _stored_content(factory: sessionmaker, agent_key: str = "architect"):
    with factory() as session:
        row = session.scalar(
            select(GraphDraftAgent).where(GraphDraftAgent.agent_key == agent_key)
        )
        assert row is not None
        return definition_content_from_row(row), row.candidate_hash


def test_exact_five_field_save_preserves_every_server_owned_value_and_artifact(
    session_factory,
) -> None:
    before_db = _database_snapshot(session_factory)
    before, old_hash = _stored_content(session_factory)
    candidate = EditableModelDraft(
        prompt_text="Architect draft changed by #263",
        endpoint_name=" custom-endpoint-name ",
        temperature=0.25,
        max_tokens=4096,
        top_p=0.8,
    )

    with session_factory() as session:
        result = GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=0,
            candidate=candidate,
            actor="test:task-263",
        )

    after, new_hash = _stored_content(session_factory)
    after_db = _database_snapshot(session_factory)
    assert result.changed is True
    assert new_hash != old_hash
    assert asdict(candidate) == {
        "prompt_text": after.prompt_text,
        "endpoint_name": after.model.endpoint_name,
        "temperature": float(after.model.temperature),
        "max_tokens": after.model.max_tokens,
        "top_p": float(after.model.top_p),
    }
    assert after.model.endpoint_name == " custom-endpoint-name "
    assert after.agent_key == before.agent_key
    assert after.definition_version == before.definition_version
    assert after.schema_overlay == before.schema_overlay
    assert after.assembly_rules == before.assembly_rules
    assert after.protected_assembly == before.protected_assembly
    assert after.schema_contract == before.schema_contract
    assert new_hash == definition_content_hash(after)
    assert result.definition.candidate_hash == new_hash
    assert result.draft.lock_version == 1
    assert result.draft.updated_by == "test:task-263"
    assert result.draft.updated_at.tzinfo is not None
    assert after_db["revisions"] == before_db["revisions"]
    assert after_db["releases"] == before_db["releases"]
    assert after_db["mappings"] == before_db["mappings"]


@pytest.mark.parametrize(
    "updates",
    [
        {"prompt_text": "changed prompt"},
        {"endpoint_name": " changed endpoint "},
        {"temperature": 0.11},
        {"max_tokens": 3210},
        {"top_p": 0.22},
    ],
)
def test_each_editable_field_rebuilds_the_complete_canonical_hash(
    session_factory, updates
) -> None:
    before, old_hash = _stored_content(session_factory)

    with session_factory() as session:
        result = GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=0,
            candidate=_editable(before, **updates),
            actor="test:hash",
        )

    persisted, persisted_hash = _stored_content(session_factory)
    assert result.changed is True
    assert persisted_hash != old_hash
    assert persisted_hash == definition_content_hash(persisted)
    assert result.definition.candidate_hash == persisted_hash


def test_same_content_advances_audit_metadata_but_reports_unchanged(session_factory) -> None:
    before, old_hash = _stored_content(session_factory)

    with session_factory() as session:
        result = GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=0,
            candidate=_editable(before),
            actor="test:no-op",
        )

    after, new_hash = _stored_content(session_factory)
    assert result.changed is False
    assert after == before
    assert new_hash == old_hash
    assert result.draft.lock_version == 1
    assert result.draft.updated_by == "test:no-op"
    assert result.draft.updated_at.tzinfo is not None


@pytest.mark.parametrize(
    ("overrides", "actor", "lock_version", "expected"),
    [
        (
            {"prompt_text": "   "},
            "actor",
            0,
            ("candidate.prompt_text", "blank", "Prompt text must not be blank."),
        ),
        (
            {"endpoint_name": "\t"},
            "actor",
            0,
            (
                "candidate.model.endpoint_name",
                "blank",
                "Endpoint name must not be blank.",
            ),
        ),
        (
            {"temperature": float("nan")},
            "actor",
            0,
            (
                "candidate.model.temperature",
                "finite_number",
                "Temperature must be finite.",
            ),
        ),
        (
            {"temperature": float("inf")},
            "actor",
            0,
            (
                "candidate.model.temperature",
                "finite_number",
                "Temperature must be finite.",
            ),
        ),
        (
            {"temperature": 1.1},
            "actor",
            0,
            (
                "candidate.model.temperature",
                "out_of_range",
                "Temperature must be between 0 and 1.",
            ),
        ),
        (
            {"max_tokens": 0},
            "actor",
            0,
            (
                "candidate.model.max_tokens",
                "positive_integer",
                "Maximum tokens must be a positive integer.",
            ),
        ),
        (
            {"max_tokens": 2.5},
            "actor",
            0,
            (
                "candidate.model.max_tokens",
                "strict_type",
                "Maximum tokens must be an integer.",
            ),
        ),
        (
            {"top_p": float("-inf")},
            "actor",
            0,
            (
                "candidate.model.top_p",
                "finite_number",
                "Top-p must be finite.",
            ),
        ),
        (
            {"top_p": -0.1},
            "actor",
            0,
            (
                "candidate.model.top_p",
                "out_of_range",
                "Top-p must be between 0 and 1.",
            ),
        ),
        ({}, " ", 0, ("actor", "blank", "Actor must not be blank.")),
        (
            {},
            "actor",
            -1,
            (
                "lock_version",
                "out_of_range",
                "Lock version must be greater than or equal to 0.",
            ),
        ),
        (
            {},
            "actor",
            True,
            (
                "lock_version",
                "strict_type",
                "Lock version must be an integer.",
            ),
        ),
    ],
)
def test_invalid_editable_commands_return_exact_issue_without_mutation(
    session_factory, overrides, actor, lock_version, expected
) -> None:
    before_db = _database_snapshot(session_factory)
    content, _ = _stored_content(session_factory)

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=lock_version,
            candidate=_editable(content, **overrides),
            actor=actor,
        )

    assert tuple(tuple(asdict(issue).values()) for issue in caught.value.issues) == (
        expected,
    )
    assert _database_snapshot(session_factory) == before_db


def test_editable_validation_accumulates_issues_in_declared_order(session_factory) -> None:
    before_db = _database_snapshot(session_factory)
    candidate = EditableModelDraft(None, None, True, False, "bad")  # type: ignore[arg-type]

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="unknown",  # type: ignore[arg-type]
            expected_lock_version=True,
            candidate=candidate,
            actor=123,  # type: ignore[arg-type]
        )

    assert [(issue.field, issue.code) for issue in caught.value.issues] == [
        ("actor", "strict_type"),
        ("lock_version", "strict_type"),
        ("agent_key", "unknown_agent"),
        ("candidate.prompt_text", "strict_type"),
        ("candidate.model.endpoint_name", "strict_type"),
        ("candidate.model.temperature", "strict_type"),
        ("candidate.model.max_tokens", "strict_type"),
        ("candidate.model.top_p", "strict_type"),
    ]
    assert _database_snapshot(session_factory) == before_db


def test_trusted_full_content_writer_carries_schema_overlay_through_shared_hash_seam(
    session_factory,
) -> None:
    before, old_hash = _stored_content(session_factory)
    changed_overlay = before.schema_overlay.model_copy(
        update={"additional_optional_fields": ("task_263_added",)}
    )
    proposed = before.model_copy(update={"schema_overlay": changed_overlay})

    with session_factory() as session:
        result = GraphConfiguration().save_draft_content(
            session,
            agent_key="architect",
            expected_lock_version=0,
            content=proposed,
            actor="test:trusted",
        )

    persisted, persisted_hash = _stored_content(session_factory)
    assert result.changed is True
    assert persisted_hash != old_hash
    assert persisted == proposed
    assert persisted_hash == definition_content_hash(persisted)


def test_trusted_full_content_writer_rejects_protected_identity_changes(
    session_factory,
) -> None:
    current, _ = _stored_content(session_factory)
    builder = load_graph_v1_manifest().definitions[2].model_copy(
        update={
            "protected_assembly": current.protected_assembly,
            "schema_contract": current.schema_contract,
        }
    )
    cases = [
        (
            builder,
            ("agent_key", "immutable_field", "Agent key must match the targeted draft definition."),
        ),
        (
            current.model_copy(update={"definition_version": current.definition_version + 1}),
            (
                "definition_version",
                "immutable_field",
                "Definition version is immutable in a draft save.",
            ),
        ),
        (
            current.model_copy(
                update={
                    "protected_assembly": current.protected_assembly.model_copy(
                        update={"version": current.protected_assembly.version + 1}
                    )
                }
            ),
            (
                "protected_assembly",
                "immutable_field",
                "Protected assembly identity is immutable in a draft save.",
            ),
        ),
        (
            current.model_copy(
                update={
                    "schema_contract": current.schema_contract.model_copy(
                        update={"version": current.schema_contract.version + 1}
                    )
                }
            ),
            (
                "schema_contract",
                "immutable_field",
                "Schema contract identity is immutable in a draft save.",
            ),
        ),
    ]
    for proposed, expected in cases:
        before_db = _database_snapshot(session_factory)
        with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
            GraphConfiguration().save_draft_content(
                session,
                agent_key="architect",
                expected_lock_version=0,
                content=proposed,
                actor="test:immutable",
            )
        assert tuple(tuple(asdict(issue).values()) for issue in caught.value.issues) == (
            expected,
        )
        assert _database_snapshot(session_factory) == before_db


def test_trusted_writer_forced_round_trip_rejects_invalid_copied_content(
    session_factory,
) -> None:
    current, _ = _stored_content(session_factory)
    invalid = current.model_copy(update={"prompt_text": ""})
    before_db = _database_snapshot(session_factory)

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        GraphConfiguration().save_draft_content(
            session,
            agent_key="architect",
            expected_lock_version=0,
            content=invalid,
            actor="test:invalid-content",
        )

    assert tuple(tuple(asdict(issue).values()) for issue in caught.value.issues) == (
        (
            "content",
            "invalid_content",
            "Draft content must satisfy the DefinitionContent contract.",
        ),
    )
    assert _database_snapshot(session_factory) == before_db


def test_stale_save_returns_exact_seven_locked_definitions_without_mutation(
    session_factory,
) -> None:
    current, _ = _stored_content(session_factory)
    candidate = _editable(current, prompt_text="stale client candidate")
    before_db = _database_snapshot(session_factory)

    with session_factory() as session:
        result = GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=7,
            candidate=candidate,
            actor="test:stale",
        )

    assert isinstance(result, DraftSaveConflict)
    assert result.expected_lock_version == 7
    assert result.current_lock_version == 0
    assert result.client_candidate is candidate
    assert set(result.server.definitions) == set(GRAPH_V1_AGENT_KEYS)
    assert len(result.server.definitions) == 7
    assert result.server.draft.lock_version == 0
    assert _database_snapshot(session_factory) == before_db


def test_flush_failure_rolls_back_content_hash_audit_and_all_graph_artifacts(
    session_factory,
) -> None:
    current, _ = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)

    with session_factory() as session:
        def _fail_flush(_session: Session, _context, _instances) -> None:
            raise RuntimeError("forced flush failure")

        event.listen(session, "before_flush", _fail_flush, once=True)
        with pytest.raises(RuntimeError, match="forced flush failure"):
            GraphConfiguration().save_editable_model_draft(
                session,
                agent_key="architect",
                expected_lock_version=0,
                candidate=_editable(current, prompt_text="must roll back"),
                actor="test:rollback",
            )

    assert _database_snapshot(session_factory) == before_db
