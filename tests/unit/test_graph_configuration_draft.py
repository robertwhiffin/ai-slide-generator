from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from dataclasses import asdict

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401
from src.core.database import Base
from src.core.prompt_modules import UNTRUSTED_DATA_NOTICE
from src.core.skills.build_reviewer import (
    BUILD_REVIEWER_AUTHORED_PREFIX,
    BUILD_REVIEWER_CRITERIA_STAGE,
    BUILD_REVIEWER_V1_AUTHORED_SUFFIX,
    BUILD_REVIEWER_V2_AUTHORED_SUFFIX,
)
from src.core.skills.data_analyst import ANALYST_AUTHORED_INSTRUCTIONS
from src.database.models.graph_configuration import (
    AgentDefinitionRevision,
    GraphDraft,
    GraphDraftAgent,
    GraphRelease,
    GraphReleaseAgent,
)
from src.services import graph_configuration_draft as draft_module
from src.services.agent_schema_registry import AgentSchemaRegistry
from src.services.agent_schema_types import SchemaOverlay
from src.services.graph_configuration import (
    DraftContentRejected,
    DraftLegacyPromptSource,
    DraftSaveConflict,
    DraftSaveResult,
    DraftValidationIssue,
    EditableModelDraft,
    GraphConfiguration,
)
from src.services.graph_configuration_content import (
    definition_content_from_row,
    definition_content_values,
)
from src.services.graph_definition_manifest import (
    GRAPH_V1_AGENT_KEYS,
    AssemblyRulesV2,
    ContentIdentity,
    CustomTextBlock,
    DefinitionContent,
    definition_content_hash,
    load_graph_v1_manifest,
)
from src.services.prompt_assembler import (
    ROLE_UNTRUSTED_DATA_NOTICE,
    V1_PROTECTED_ASSEMBLY_IDENTITY,
    V2_PROTECTED_ASSEMBLY_IDENTITY,
    PromptAssembler,
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
    values: dict[str, object] = {
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
        "assembly_rules": None,
        "schema_overlay": None,
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
    # Canonical-field guidance is editable only under schema contract v2 (#264 I1:
    # v1 has no overlay grammar and the runtime refuses any non-empty v1 overlay),
    # so the draft is upgraded first.  #263 used an invented name here because
    # nothing validated the overlay yet; #264 closed the catalog and then the v1
    # guidance hole, so the premise had to become a legal v2 edit.
    assert isinstance(_upgrade_schema(session_factory, lock_version=0), DraftSaveResult)
    before, old_hash = _stored_content(session_factory)
    changed_overlay = SchemaOverlay.model_validate(
        {"field_overrides": {"intent": {"description": "Task 263 intent guidance."}}}
    )
    proposed = before.model_copy(update={"schema_overlay": changed_overlay})

    with session_factory() as session:
        result = GraphConfiguration().save_draft_content(
            session,
            agent_key="architect",
            expected_lock_version=1,
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


# ---------------------------------------------------------------------------
# #265 declarative prompt assembly: local/post-stale validator phases,
# the protected-assembly upgrade, and read-only legacy prompt-source recovery.
# ---------------------------------------------------------------------------


DUPLICATE_BLOCK_ID = "00000000-0000-0000-0000-000000000001"
SECOND_BLOCK_ID = "00000000-0000-0000-0000-000000000002"

FIVE_ISSUE_TUPLE = (
    (
        "candidate.assembly_rules.custom_blocks.0.text",
        "blank",
        "Custom block text must not be blank.",
    ),
    (
        "candidate.assembly_rules.custom_blocks.0.anchor",
        "invalid_anchor_for_role",
        "The deck-brief anchor is available only to Build Reviewer.",
    ),
    (
        "candidate.assembly_rules.custom_blocks.0.condition",
        "invalid_condition_for_anchor",
        "The deck-brief anchor requires payload_has_deck_brief.",
    ),
    (
        "candidate.assembly_rules.custom_blocks.1.block_id",
        "duplicate_block_id",
        "Custom block IDs must be unique.",
    ),
    (
        "candidate.assembly_rules.custom_blocks.1.anchor",
        "invalid_anchor_order",
        "Custom blocks must be ordered by protected anchor.",
    ),
)
BUNDLE_MISMATCH_TUPLE = (
    (
        "candidate.assembly_rules.format_version",
        "assembly_bundle_mismatch",
        "Assembly rules format must match the protected assembly bundle.",
    ),
)
MANUAL_RESOLUTION_TUPLE = (
    (
        "prompt_text",
        "legacy_prompt_manual_resolution_required",
        "Legacy protected prompt content was edited. Restore the exact Graph Version 1 "
        "prompt before upgrading, then reapply authored edits.",
    ),
)
ALREADY_CURRENT_TUPLE = (
    (
        "protected_assembly.version",
        "already_current",
        "Protected assembly is already current.",
    ),
)
LEGACY_SOURCE_UNSUPPORTED_TUPLE = (
    (
        "agent_key",
        "legacy_prompt_source_unsupported",
        "Legacy Graph Version 1 prompt recovery is supported only for Data Analyst "
        "and Build Reviewer.",
    ),
)
LEGACY_SOURCE_NOT_REQUIRED_TUPLE = (
    (
        "prompt_text",
        "legacy_prompt_source_not_required",
        "The draft already uses the exact Graph Version 1 prompt.",
    ),
)
LEGACY_SOURCE_UNAVAILABLE_TUPLE = (
    (
        "prompt_text",
        "legacy_prompt_source_unavailable",
        "The exact published Graph Version 1 prompt source is unavailable for this draft.",
    ),
)


#: Recomposed from the reviewed skill constants, never from ``PromptAssembler``, so a wrong
#: retained literal cannot round-trip undetected through the assembler's own output.
INDEPENDENT_TRANSITION_LITERALS = {
    "data_analyst": (
        UNTRUSTED_DATA_NOTICE + "\n\n" + ANALYST_AUTHORED_INSTRUCTIONS,
        ANALYST_AUTHORED_INSTRUCTIONS,
    ),
    "build_reviewer": (
        BUILD_REVIEWER_AUTHORED_PREFIX
        + "\n\n"
        + BUILD_REVIEWER_CRITERIA_STAGE
        + "\n\n"
        + BUILD_REVIEWER_V1_AUTHORED_SUFFIX,
        BUILD_REVIEWER_AUTHORED_PREFIX + "\n\n" + BUILD_REVIEWER_V2_AUTHORED_SUFFIX,
    ),
}


@dataclasses.dataclass(frozen=True)
class _Context:
    design_system_active: bool


def _issue_tuples(caught) -> tuple[tuple[str, str, str], ...]:
    return tuple(tuple(asdict(issue).values()) for issue in caught.value.issues)


def _custom_block(
    block_id: str,
    text: str,
    *,
    anchor: str = "after_authored_prompt",
    condition: str = "always",
) -> CustomTextBlock:
    return CustomTextBlock.model_validate(
        {
            "kind": "custom_text",
            "block_id": block_id,
            "anchor": anchor,
            "condition": condition,
            "text": text,
        }
    )


def _v2_rules(*blocks: CustomTextBlock) -> AssemblyRulesV2:
    return AssemblyRulesV2(format_version=2, custom_blocks=tuple(blocks))


def _five_issue_rules() -> AssemblyRulesV2:
    return _v2_rules(
        _custom_block(
            DUPLICATE_BLOCK_ID, "   ", anchor="after_deck_brief", condition="always"
        ),
        _custom_block(DUPLICATE_BLOCK_ID, "second", anchor="after_authored_prompt"),
    )


def _overwrite_draft_row(
    factory: sessionmaker, agent_key: str, content: DefinitionContent
) -> None:
    """Seed one persisted candidate row directly, bypassing the locked facade."""
    with factory.begin() as session:
        row = session.scalar(
            select(GraphDraftAgent).where(GraphDraftAgent.agent_key == agent_key)
        )
        assert row is not None
        for column_name, value in definition_content_values(content).items():
            setattr(row, column_name, value)
        row.candidate_hash = definition_content_hash(content)


def _draft_audit(factory: sessionmaker) -> tuple[int, str, object]:
    with factory() as session:
        row = session.get(GraphDraft, 1)
        assert row is not None
        return row.lock_version, row.updated_by, row.updated_at


def _published_content(
    factory: sessionmaker, agent_key: str
) -> tuple[DefinitionContent, str, int]:
    with factory() as session:
        row = session.scalar(
            select(AgentDefinitionRevision).where(
                AgentDefinitionRevision.agent_key == agent_key
            )
        )
        assert row is not None
        return definition_content_from_row(row), row.content_hash, row.id


def _upgrade(
    factory: sessionmaker,
    agent_key: str,
    *,
    lock_version: int,
    actor: str = "test:upgrade",
):
    with factory() as session:
        return GraphConfiguration().upgrade_draft_protected_assembly(
            session,
            agent_key=agent_key,
            expected_lock_version=lock_version,
            actor=actor,
        )


def _recording_validator(log: list[str], name: str, *issues: tuple[str, str, str]):
    def _validator(content: DefinitionContent) -> tuple[DraftValidationIssue, ...]:
        log.append(name)
        return tuple(DraftValidationIssue(*issue) for issue in issues)

    return _validator


def _install_write_spy(monkeypatch: pytest.MonkeyPatch, log: list[str]) -> None:
    original = GraphConfiguration._write_locked_content

    def _spy(session, *, locked, content, actor):
        log.append("write")
        return original(session, locked=locked, content=content, actor=actor)

    monkeypatch.setattr(GraphConfiguration, "_write_locked_content", staticmethod(_spy))


def test_valid_v2_editable_save_uses_one_mapper_hash_and_audit(
    session_factory,
) -> None:
    """Catches a second writer, a skipped hash rebuild, or lost schema identity."""
    before_db = _database_snapshot(session_factory)
    upgraded = _upgrade(session_factory, "architect", lock_version=0)
    assert isinstance(upgraded, DraftSaveResult)
    after_upgrade, upgrade_hash = _stored_content(session_factory)
    block = _custom_block(SECOND_BLOCK_ID, "Operator guidance for Architect.")

    with session_factory() as session:
        result = GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=1,
            candidate=_editable(after_upgrade, assembly_rules=_v2_rules(block)),
            actor="test:v2-save",
        )

    persisted, persisted_hash = _stored_content(session_factory)
    after_db = _database_snapshot(session_factory)
    assert isinstance(result, DraftSaveResult)
    assert result.changed is True
    assert persisted.assembly_rules == _v2_rules(block)
    assert persisted.prompt_text == after_upgrade.prompt_text
    assert persisted.protected_assembly == V2_PROTECTED_ASSEMBLY_IDENTITY
    assert persisted.definition_version == after_upgrade.definition_version
    assert persisted.schema_overlay == after_upgrade.schema_overlay
    assert persisted.schema_contract == after_upgrade.schema_contract
    assert persisted.model == after_upgrade.model
    assert persisted_hash == definition_content_hash(persisted)
    assert persisted_hash != upgrade_hash
    assert result.definition.candidate_hash == persisted_hash
    assert _draft_audit(session_factory)[:2] == (2, "test:v2-save")
    assert after_db["revisions"] == before_db["revisions"]
    assert after_db["releases"] == before_db["releases"]
    assert after_db["mappings"] == before_db["mappings"]


def test_repeated_valid_same_content_v2_save_increments_lock_once_without_hash_change(
    session_factory,
) -> None:
    """Catches a same-content v2 save that rewrites the hash or skips its audit."""
    _upgrade(session_factory, "architect", lock_version=0)
    current, current_hash = _stored_content(session_factory)

    with session_factory() as session:
        result = GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=1,
            candidate=_editable(current, assembly_rules=current.assembly_rules),
            actor="test:v2-no-op",
        )

    persisted, persisted_hash = _stored_content(session_factory)
    assert result.changed is False
    assert persisted == current
    assert persisted_hash == current_hash
    assert _draft_audit(session_factory)[:2] == (2, "test:v2-no-op")


def test_command_validation_precedes_both_registered_validator_phases(
    session_factory, monkeypatch
) -> None:
    """Catches a validator phase that runs before #263's own command checks."""
    log: list[str] = []
    monkeypatch.setattr(
        GraphConfiguration,
        "local_candidate_validators",
        (_recording_validator(log, "local-1"),),
    )
    monkeypatch.setattr(
        GraphConfiguration,
        "post_stale_validators",
        (_recording_validator(log, "post-1"),),
    )
    _install_write_spy(monkeypatch, log)
    content, _ = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=0,
            candidate=_editable(content),
            actor="  ",
        )

    assert _issue_tuples(caught) == (("actor", "blank", "Actor must not be blank."),)
    assert log == []
    assert _database_snapshot(session_factory) == before_db


def test_registered_validator_phases_run_in_order_around_stale_comparison(
    session_factory, monkeypatch
) -> None:
    """Catches reordered phases or a post-stale validator running after the writer."""
    log: list[str] = []
    monkeypatch.setattr(
        GraphConfiguration,
        "local_candidate_validators",
        (
            _recording_validator(log, "local-1"),
            _recording_validator(log, "local-2"),
        ),
    )
    monkeypatch.setattr(
        GraphConfiguration,
        "post_stale_validators",
        (
            _recording_validator(log, "post-1"),
            _recording_validator(log, "post-2"),
        ),
    )
    _install_write_spy(monkeypatch, log)
    content, _ = _stored_content(session_factory)

    with session_factory() as session:
        result = GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=0,
            candidate=_editable(content, prompt_text="ordered phase edit"),
            actor="test:phases",
        )

    assert isinstance(result, DraftSaveResult)
    assert log == ["local-1", "local-2", "post-1", "post-2", "write"]


def test_local_invalid_stale_request_is_ordered_422_without_post_stale_or_mutation(
    session_factory, monkeypatch
) -> None:
    """Catches stale comparison outranking a local rejection or leaking a write."""
    log: list[str] = []
    monkeypatch.setattr(
        GraphConfiguration,
        "local_candidate_validators",
        (
            _recording_validator(
                log,
                "local-1",
                ("candidate.first", "first_code", "First recorded issue."),
                ("candidate.second", "second_code", "Second recorded issue."),
            ),
            _recording_validator(
                log, "local-2", ("candidate.third", "third_code", "Third recorded issue.")
            ),
        ),
    )
    monkeypatch.setattr(
        GraphConfiguration,
        "post_stale_validators",
        (_recording_validator(log, "post-1"),),
    )
    _install_write_spy(monkeypatch, log)
    content, _ = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=7,
            candidate=_editable(content, prompt_text="local invalid and stale"),
            actor="test:local-invalid-stale",
        )

    assert _issue_tuples(caught) == (
        ("candidate.first", "first_code", "First recorded issue."),
        ("candidate.second", "second_code", "Second recorded issue."),
        ("candidate.third", "third_code", "Third recorded issue."),
    )
    assert log == ["local-1", "local-2"]
    assert _database_snapshot(session_factory) == before_db


def test_local_valid_stale_request_is_coherent_409_without_post_stale_validators(
    session_factory, monkeypatch
) -> None:
    """Catches a post-stale validator running for a stale request."""
    log: list[str] = []
    monkeypatch.setattr(
        GraphConfiguration,
        "local_candidate_validators",
        (_recording_validator(log, "local-1"),),
    )
    monkeypatch.setattr(
        GraphConfiguration,
        "post_stale_validators",
        (_recording_validator(log, "post-1"),),
    )
    _install_write_spy(monkeypatch, log)
    content, _ = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)

    with session_factory() as session:
        result = GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=4,
            candidate=_editable(content, prompt_text="local valid but stale"),
            actor="test:local-valid-stale",
        )

    assert isinstance(result, DraftSaveConflict)
    assert result.expected_lock_version == 4
    assert result.current_lock_version == 0
    assert log == ["local-1"]
    assert _database_snapshot(session_factory) == before_db


def test_post_stale_rejection_is_a_total_row_hash_lock_and_audit_no_op(
    session_factory, monkeypatch
) -> None:
    """Catches a post-stale rejection landing after the mapper or audit write."""
    log: list[str] = []
    monkeypatch.setattr(
        GraphConfiguration,
        "local_candidate_validators",
        (_recording_validator(log, "local-1"),),
    )
    monkeypatch.setattr(
        GraphConfiguration,
        "post_stale_validators",
        (
            _recording_validator(
                log, "post-1", ("candidate.remote", "remote_code", "Remote recorded issue.")
            ),
        ),
    )
    _install_write_spy(monkeypatch, log)
    content, _ = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=0,
            candidate=_editable(content, prompt_text="post stale rejection"),
            actor="test:post-stale",
        )

    assert _issue_tuples(caught) == (
        ("candidate.remote", "remote_code", "Remote recorded issue."),
    )
    assert log == ["local-1", "post-1"]
    assert _database_snapshot(session_factory) == before_db


def test_five_issue_v2_candidate_with_stale_lock_is_ordered_422_at_the_facade(
    session_factory, monkeypatch
) -> None:
    """Catches generic content translation, reordering, or stale precedence."""
    _upgrade(session_factory, "architect", lock_version=0)
    current, _ = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)
    validate_calls: list[str] = []
    post_calls: list[str] = []
    original_validate = PromptAssembler.validate

    def _spy_validate(self, *, definition):
        validate_calls.append(definition.agent_key)
        return original_validate(self, definition=definition)

    monkeypatch.setattr(PromptAssembler, "validate", _spy_validate)
    monkeypatch.setattr(
        GraphConfiguration,
        "post_stale_validators",
        (_recording_validator(post_calls, "post-1"),),
    )

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=0,
            candidate=_editable(current, assembly_rules=_five_issue_rules()),
            actor="test:five-issue",
        )

    assert _issue_tuples(caught) == FIVE_ISSUE_TUPLE
    assert validate_calls == ["architect"]
    assert post_calls == []
    assert _database_snapshot(session_factory) == before_db


@pytest.mark.parametrize(
    ("blocks", "expected"),
    [
        (
            (_custom_block(DUPLICATE_BLOCK_ID, "a"), _custom_block(DUPLICATE_BLOCK_ID, "b")),
            (
                (
                    "candidate.assembly_rules.custom_blocks.1.block_id",
                    "duplicate_block_id",
                    "Custom block IDs must be unique.",
                ),
            ),
        ),
        (
            (_custom_block(DUPLICATE_BLOCK_ID, " \t "),),
            (
                (
                    "candidate.assembly_rules.custom_blocks.0.text",
                    "blank",
                    "Custom block text must not be blank.",
                ),
            ),
        ),
        (
            (
                _custom_block(
                    DUPLICATE_BLOCK_ID,
                    "deck",
                    anchor="after_deck_brief",
                    condition="payload_has_deck_brief",
                ),
            ),
            (
                (
                    "candidate.assembly_rules.custom_blocks.0.anchor",
                    "invalid_anchor_for_role",
                    "The deck-brief anchor is available only to Build Reviewer.",
                ),
            ),
        ),
        (
            (
                _custom_block(
                    DUPLICATE_BLOCK_ID,
                    "environment",
                    anchor="after_environment_constraints",
                ),
                _custom_block(SECOND_BLOCK_ID, "authored"),
            ),
            (
                (
                    "candidate.assembly_rules.custom_blocks.1.anchor",
                    "invalid_anchor_order",
                    "Custom blocks must be ordered by protected anchor.",
                ),
            ),
        ),
        (
            (
                _custom_block(DUPLICATE_BLOCK_ID, "after payload").model_copy(
                    update={"anchor": "after_payload"}
                ),
            ),
            (
                (
                    "candidate.assembly_rules",
                    "invalid_protected_placement",
                    "Assembly rules must satisfy the persisted assembly contract.",
                ),
            ),
        ),
    ],
)
def test_assembler_owned_semantic_rows_are_copied_verbatim_without_mutation(
    session_factory, blocks, expected
) -> None:
    """Catches the writer inventing, dropping, or rewording assembler semantics."""
    _upgrade(session_factory, "architect", lock_version=0)
    current, _ = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=1,
            candidate=_editable(current, assembly_rules=_v2_rules(*blocks)),
            actor="test:semantic",
        )

    assert _issue_tuples(caught) == expected
    assert _database_snapshot(session_factory) == before_db


@pytest.mark.parametrize(
    ("identity", "expected_field"),
    [
        (ContentIdentity(version=999, digest="0" * 64), "protected_assembly.version"),
        (ContentIdentity(version=1, digest="0" * 64), "protected_assembly.digest"),
    ],
)
def test_unregistered_persisted_bundle_identity_is_copied_as_typed_row(
    session_factory, identity, expected_field
) -> None:
    """Catches a fake persisted version/digest reaching the mapper or hash write."""
    current, _ = _stored_content(session_factory)
    _overwrite_draft_row(
        session_factory,
        "architect",
        current.model_copy(update={"protected_assembly": identity}),
    )
    seeded, _ = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=0,
            candidate=_editable(seeded, prompt_text="fake identity edit"),
            actor="test:fake-identity",
        )

    assert _issue_tuples(caught) == (
        (
            expected_field,
            "protected_bundle_unavailable",
            "Protected assembly bundle is unavailable.",
        ),
    )
    assert _database_snapshot(session_factory) == before_db


@pytest.mark.parametrize(
    ("removed", "duplicated", "expected"),
    [
        (
            "untrusted_data_close",
            None,
            (
                (
                    "protected_assembly.stages.untrusted_data_close",
                    "missing_protected_stage",
                    "Required protected stage is missing.",
                ),
            ),
        ),
        (
            None,
            "untrusted_data_notice",
            (
                (
                    "protected_assembly.stages.untrusted_data_notice",
                    "duplicate_protected_stage",
                    "Protected singleton stage must appear exactly once.",
                ),
            ),
        ),
        (
            "runtime_payload",
            None,
            (
                (
                    "protected_assembly.stages.runtime_payload",
                    "invalid_payload_stage",
                    "Runtime payload must appear exactly once between the protected delimiters.",
                ),
            ),
        ),
        (
            "structured_output_binding",
            None,
            (
                (
                    "protected_assembly.stages.structured_output_binding",
                    "invalid_terminal_binding",
                    "Structured-output binding must be the final non-prompt protected stage.",
                ),
            ),
        ),
    ],
)
def test_server_owned_protected_plan_failures_reach_the_writer_as_copied_rows(
    session_factory, monkeypatch, removed, duplicated, expected
) -> None:
    """Catches the writer trusting a corrupt code-owned protected stage plan."""
    _upgrade(session_factory, "architect", lock_version=0)
    current, _ = _stored_content(session_factory)
    baseline = PromptAssembler()
    bundle = baseline.resolve_bundle(V2_PROTECTED_ASSEMBLY_IDENTITY)
    stages = list(bundle.stages)
    if removed is not None:
        stages = [stage for stage in stages if stage.stage_id != removed]
    if duplicated is not None:
        index = next(i for i, s in enumerate(stages) if s.stage_id == duplicated)
        stages.insert(index, stages[index])
    corrupt = dataclasses.replace(bundle, stages=tuple(stages))
    monkeypatch.setattr(
        draft_module,
        "_PROMPT_ASSEMBLER",
        PromptAssembler(bundles={bundle.identity_key: corrupt}),
    )
    before_db = _database_snapshot(session_factory)

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=1,
            candidate=_editable(current, prompt_text="corrupt plan edit"),
            actor="test:corrupt-plan",
        )

    assert _issue_tuples(caught) == expected
    assert _database_snapshot(session_factory) == before_db


def test_v2_rules_on_a_stored_v1_draft_are_the_sole_bundle_mismatch_row(
    session_factory,
) -> None:
    """Catches an ordinary save silently transitioning a v1 draft to v2 rules."""
    current, _ = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=0,
            candidate=_editable(current, assembly_rules=_v2_rules()),
            actor="test:forward-mismatch",
        )

    assert _issue_tuples(caught) == BUNDLE_MISMATCH_TUPLE
    assert _database_snapshot(session_factory) == before_db


def test_stale_v2_rules_on_a_stored_v1_draft_still_return_the_local_mismatch(
    session_factory, monkeypatch
) -> None:
    """Catches stale comparison outranking the local assembly pairing rejection."""
    post_calls: list[str] = []
    monkeypatch.setattr(
        GraphConfiguration,
        "post_stale_validators",
        (_recording_validator(post_calls, "post-1"),),
    )
    current, _ = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=9,
            candidate=_editable(current, assembly_rules=_v2_rules()),
            actor="test:stale-forward-mismatch",
        )

    assert _issue_tuples(caught) == BUNDLE_MISMATCH_TUPLE
    assert post_calls == []
    assert _database_snapshot(session_factory) == before_db


def test_corrupted_v2_identity_with_v1_rules_rejects_an_ordinary_save(session_factory) -> None:
    """Catches the writer repairing or ignoring a corrupted persisted rules pair."""
    current, _ = _stored_content(session_factory)
    _overwrite_draft_row(
        session_factory,
        "architect",
        current.model_copy(update={"protected_assembly": V2_PROTECTED_ASSEMBLY_IDENTITY}),
    )
    seeded, seeded_hash = _stored_content(session_factory)
    assert seeded.protected_assembly == V2_PROTECTED_ASSEMBLY_IDENTITY
    assert seeded.assembly_rules == current.assembly_rules
    before_db = _database_snapshot(session_factory)

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=0,
            candidate=_editable(seeded, prompt_text="ordinary prompt edit"),
            actor="test:reverse-mismatch",
        )

    assert _issue_tuples(caught) == BUNDLE_MISMATCH_TUPLE
    reloaded, reloaded_hash = _stored_content(session_factory)
    assert reloaded == seeded
    assert reloaded_hash == seeded_hash
    assert _database_snapshot(session_factory) == before_db


@pytest.mark.parametrize("agent_key", GRAPH_V1_AGENT_KEYS)
def test_upgrade_changes_only_the_transition_fields_for_every_role(
    session_factory, agent_key
) -> None:
    """Catches upgrade touching model/overlay/schema/published/release state."""
    before_db = _database_snapshot(session_factory)
    before, before_hash = _stored_content(session_factory, agent_key)
    published_before, published_hash_before, revision_id = _published_content(
        session_factory, agent_key
    )
    transition_roles = {"data_analyst", "build_reviewer"}

    result = _upgrade(session_factory, agent_key, lock_version=0, actor="test:role-upgrade")

    after, after_hash = _stored_content(session_factory, agent_key)
    published_after, published_hash_after, revision_id_after = _published_content(
        session_factory, agent_key
    )
    after_db = _database_snapshot(session_factory)
    assert isinstance(result, DraftSaveResult)
    assert result.changed is True
    assert after.protected_assembly == V2_PROTECTED_ASSEMBLY_IDENTITY
    assert after.assembly_rules == AssemblyRulesV2(format_version=2, custom_blocks=())
    assert after.agent_key == before.agent_key
    assert after.definition_version == before.definition_version
    assert after.model == before.model
    assert after.schema_overlay == before.schema_overlay
    assert after.schema_contract == before.schema_contract
    if agent_key in transition_roles:
        transition = PromptAssembler().legacy_v1_prompt_source(agent_key=agent_key)
        assert before.prompt_text == transition.source_composite_prompt
        assert after.prompt_text == transition.target_authored_prompt
        assert after.prompt_text != before.prompt_text
    else:
        assert after.prompt_text == before.prompt_text
    assert after_hash == definition_content_hash(after)
    assert after_hash != before_hash
    assert result.definition.candidate_hash == after_hash
    assert result.definition.base_revision_id == revision_id
    assert _draft_audit(session_factory)[:2] == (1, "test:role-upgrade")
    assert published_after == published_before
    assert published_hash_after == published_hash_before
    assert revision_id_after == revision_id
    assert published_before.protected_assembly == V1_PROTECTED_ASSEMBLY_IDENTITY
    assert after_db["revisions"] == before_db["revisions"]
    assert after_db["releases"] == before_db["releases"]
    assert after_db["mappings"] == before_db["mappings"]


@pytest.mark.parametrize("agent_key", ["data_analyst", "build_reviewer"])
def test_persisted_upgrade_reloads_authored_only_with_exactly_once_protected_stage(
    session_factory, agent_key
) -> None:
    """Catches legacy composite text surviving in editable prompt or rendering twice."""
    transition = PromptAssembler().legacy_v1_prompt_source(agent_key=agent_key)
    displaced = (
        UNTRUSTED_DATA_NOTICE if agent_key == "data_analyst" else BUILD_REVIEWER_CRITERIA_STAGE
    )
    protected_stage_id = (
        "untrusted_data_notice" if agent_key == "data_analyst" else "build_reviewer_criteria"
    )
    rendered = (
        ROLE_UNTRUSTED_DATA_NOTICE[agent_key]
        if agent_key == "data_analyst"
        else BUILD_REVIEWER_CRITERIA_STAGE
    )
    published_before, published_hash_before, _ = _published_content(session_factory, agent_key)

    _upgrade(session_factory, agent_key, lock_version=0)

    reloaded, reloaded_hash = _stored_content(session_factory, agent_key)
    assert reloaded.prompt_text == transition.target_authored_prompt
    assert displaced not in reloaded.prompt_text
    assert reloaded.assembly_rules == AssemblyRulesV2(format_version=2, custom_blocks=())
    assert reloaded.protected_assembly == V2_PROTECTED_ASSEMBLY_IDENTITY
    assert reloaded_hash == definition_content_hash(reloaded)

    assembled = PromptAssembler().assemble(
        definition=reloaded, payload={"x": 1}, context=_Context(False)
    )
    stage_ids = [stage.stage_id for stage in assembled.stages]
    expected_ids = ["authored_prompt"]
    if agent_key == "build_reviewer":
        expected_ids.append("build_reviewer_criteria")
    expected_ids.extend(
        [
            "slide_frame_constraints",
            "untrusted_data_notice",
            "untrusted_data_open",
            "runtime_payload",
            "untrusted_data_close",
            "structured_output_binding",
        ]
    )
    assert stage_ids == expected_ids
    assert stage_ids.count(protected_stage_id) == 1
    assert assembled.prompt.count(rendered) == 1
    assert assembled.terminal_binding == "langchain.with_structured_output"
    terminal = assembled.stages[-1]
    assert terminal.stage_id == "structured_output_binding"
    assert terminal.contributes_to_prompt is False
    assert terminal.rendered_text not in assembled.prompt
    published_after, published_hash_after, _ = _published_content(session_factory, agent_key)
    assert published_after == published_before
    assert published_hash_after == published_hash_before
    assert published_after.prompt_text == transition.source_composite_prompt
    assert published_after.assembly_rules == transition.source_assembly_rules
    assert published_after.protected_assembly == V1_PROTECTED_ASSEMBLY_IDENTITY


@pytest.mark.parametrize("agent_key", ["data_analyst", "build_reviewer"])
def test_edited_legacy_prompt_upgrade_requires_manual_resolution_without_write(
    session_factory, monkeypatch, agent_key
) -> None:
    """Catches lossy extraction from an edited legacy composite prompt."""
    before, _ = _stored_content(session_factory, agent_key)
    with session_factory() as session:
        edited = GraphConfiguration().save_editable_model_draft(
            session,
            agent_key=agent_key,
            expected_lock_version=0,
            candidate=_editable(before, prompt_text=before.prompt_text + "!"),
            actor="test:one-code-point",
        )
    assert isinstance(edited, DraftSaveResult)
    before_db = _database_snapshot(session_factory)
    stored_before, hash_before = _stored_content(session_factory, agent_key)
    local_calls: list[str] = []
    post_calls: list[str] = []
    monkeypatch.setattr(
        GraphConfiguration,
        "local_candidate_validators",
        (_recording_validator(local_calls, "local-1"),),
    )
    monkeypatch.setattr(
        GraphConfiguration,
        "post_stale_validators",
        (_recording_validator(post_calls, "post-1"),),
    )
    write_log: list[str] = []
    _install_write_spy(monkeypatch, write_log)

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        GraphConfiguration().upgrade_draft_protected_assembly(
            session,
            agent_key=agent_key,
            expected_lock_version=1,
            actor="test:manual-resolution",
        )

    assert _issue_tuples(caught) == MANUAL_RESOLUTION_TUPLE
    assert local_calls == []
    assert post_calls == []
    assert write_log == []
    stored_after, hash_after = _stored_content(session_factory, agent_key)
    assert stored_after == stored_before
    assert hash_after == hash_before
    assert _database_snapshot(session_factory) == before_db


@pytest.mark.parametrize("agent_key", ["data_analyst", "build_reviewer"])
def test_stale_upgrade_never_reaches_the_transition_authority(
    session_factory, monkeypatch, agent_key
) -> None:
    """Catches transition issues masking a stale request."""
    before, _ = _stored_content(session_factory, agent_key)
    with session_factory() as session:
        GraphConfiguration().save_editable_model_draft(
            session,
            agent_key=agent_key,
            expected_lock_version=0,
            candidate=_editable(before, prompt_text=before.prompt_text + "!"),
            actor="test:one-code-point",
        )
    before_db = _database_snapshot(session_factory)
    upgrade_calls: list[str] = []
    original = PromptAssembler.upgrade_definition_to_v2

    def _spy(self, *, definition):
        upgrade_calls.append(definition.agent_key)
        return original(self, definition=definition)

    monkeypatch.setattr(PromptAssembler, "upgrade_definition_to_v2", _spy)

    result = _upgrade(session_factory, agent_key, lock_version=0, actor="test:stale-upgrade")

    assert isinstance(result, DraftSaveConflict)
    assert result.expected_lock_version == 0
    assert result.current_lock_version == 1
    assert result.client_candidate is None
    assert set(result.server.definitions) == set(GRAPH_V1_AGENT_KEYS)
    assert len(result.server.definitions) == 7
    assert result.server.draft.lock_version == 1
    assert upgrade_calls == []
    assert _database_snapshot(session_factory) == before_db


def test_repeated_upgrade_is_already_current_only_for_a_current_request(
    session_factory, monkeypatch
) -> None:
    """Catches a facade or route deriving already-current state for itself."""
    _upgrade(session_factory, "architect", lock_version=0)
    before_db = _database_snapshot(session_factory)
    upgrade_calls: list[str] = []
    local_calls: list[str] = []
    original = PromptAssembler.upgrade_definition_to_v2

    def _spy(self, *, definition):
        upgrade_calls.append(definition.agent_key)
        return original(self, definition=definition)

    monkeypatch.setattr(PromptAssembler, "upgrade_definition_to_v2", _spy)
    monkeypatch.setattr(
        GraphConfiguration,
        "local_candidate_validators",
        (_recording_validator(local_calls, "local-1"),),
    )

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        GraphConfiguration().upgrade_draft_protected_assembly(
            session,
            agent_key="architect",
            expected_lock_version=1,
            actor="test:already-current",
        )

    assert _issue_tuples(caught) == ALREADY_CURRENT_TUPLE
    assert upgrade_calls == ["architect"]
    assert local_calls == []
    assert _database_snapshot(session_factory) == before_db

    upgrade_calls.clear()
    stale = _upgrade(session_factory, "architect", lock_version=0, actor="test:stale-repeat")
    assert isinstance(stale, DraftSaveConflict)
    assert stale.client_candidate is None
    assert stale.expected_lock_version == 0
    assert stale.current_lock_version == 1
    assert upgrade_calls == []
    assert _database_snapshot(session_factory) == before_db


@pytest.mark.parametrize("agent_key", ["data_analyst", "build_reviewer"])
def test_legacy_prompt_source_returns_the_exact_published_v1_bytes(
    session_factory, monkeypatch, agent_key
) -> None:
    """Catches a facade that derives, slices, or persists recovery source bytes."""
    transition = PromptAssembler().legacy_v1_prompt_source(agent_key=agent_key)
    before, _ = _stored_content(session_factory, agent_key)
    with session_factory() as session:
        GraphConfiguration().save_editable_model_draft(
            session,
            agent_key=agent_key,
            expected_lock_version=0,
            candidate=_editable(before, prompt_text=before.prompt_text + "!"),
            actor="test:one-code-point",
        )
    before_db = _database_snapshot(session_factory)
    _published, published_hash, revision_id = _published_content(session_factory, agent_key)
    write_log: list[str] = []
    _install_write_spy(monkeypatch, write_log)
    source_calls: list[str] = []
    original = PromptAssembler.legacy_v1_prompt_source

    def _spy(self, *, agent_key):
        source_calls.append(agent_key)
        return original(self, agent_key=agent_key)

    monkeypatch.setattr(PromptAssembler, "legacy_v1_prompt_source", _spy)

    with session_factory() as session:
        result = GraphConfiguration().get_draft_legacy_prompt_source(
            session,
            agent_key=agent_key,
            expected_lock_version=1,
            actor="test:source",
        )

    assert isinstance(result, DraftLegacyPromptSource)
    assert result.agent_key == agent_key
    assert result.lock_version == 1
    assert result.draft.lock_version == 1
    assert result.draft.updated_by == "test:one-code-point"
    assert result.source.prompt_text == transition.source_composite_prompt
    assert result.source.revision_id == revision_id
    assert result.source.content_hash == published_hash
    assert source_calls == [agent_key]
    assert write_log == []
    assert _database_snapshot(session_factory) == before_db


@pytest.mark.parametrize("agent_key", ["data_analyst", "build_reviewer"])
def test_stale_legacy_prompt_source_is_the_coherent_null_candidate_conflict(
    session_factory, agent_key
) -> None:
    """Catches recovery preconditions outranking a stale request."""
    before, _ = _stored_content(session_factory, agent_key)
    with session_factory() as session:
        GraphConfiguration().save_editable_model_draft(
            session,
            agent_key=agent_key,
            expected_lock_version=0,
            candidate=_editable(before, prompt_text=before.prompt_text + "!"),
            actor="test:one-code-point",
        )
    before_db = _database_snapshot(session_factory)

    with session_factory() as session:
        result = GraphConfiguration().get_draft_legacy_prompt_source(
            session,
            agent_key=agent_key,
            expected_lock_version=0,
            actor="test:stale-source",
        )

    assert isinstance(result, DraftSaveConflict)
    assert result.expected_lock_version == 0
    assert result.current_lock_version == 1
    assert result.client_candidate is None
    assert set(result.server.definitions) == set(GRAPH_V1_AGENT_KEYS)
    assert len(result.server.definitions) == 7
    assert _database_snapshot(session_factory) == before_db


def test_legacy_prompt_source_rejects_an_unsupported_role(session_factory) -> None:
    """Catches recovery leaking onto roles with no retained transition record."""
    before_db = _database_snapshot(session_factory)

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        GraphConfiguration().get_draft_legacy_prompt_source(
            session,
            agent_key="architect",
            expected_lock_version=0,
            actor="test:unsupported",
        )

    assert _issue_tuples(caught) == LEGACY_SOURCE_UNSUPPORTED_TUPLE
    assert _database_snapshot(session_factory) == before_db


@pytest.mark.parametrize("agent_key", ["data_analyst", "build_reviewer"])
def test_legacy_prompt_source_rejects_an_unedited_draft(session_factory, agent_key) -> None:
    """Catches recovery offering bytes the draft already holds exactly."""
    before_db = _database_snapshot(session_factory)

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        GraphConfiguration().get_draft_legacy_prompt_source(
            session,
            agent_key=agent_key,
            expected_lock_version=0,
            actor="test:not-required",
        )

    assert _issue_tuples(caught) == LEGACY_SOURCE_NOT_REQUIRED_TUPLE
    assert _database_snapshot(session_factory) == before_db


@pytest.mark.parametrize("agent_key", ["data_analyst", "build_reviewer"])
def test_legacy_prompt_source_is_unavailable_for_a_draft_pair_mismatch(
    session_factory, agent_key
) -> None:
    """Catches recovery running against a draft that is no longer the v1 pair."""
    _upgrade(session_factory, agent_key, lock_version=0)
    upgraded, _ = _stored_content(session_factory, agent_key)
    with session_factory() as session:
        GraphConfiguration().save_editable_model_draft(
            session,
            agent_key=agent_key,
            expected_lock_version=1,
            candidate=_editable(upgraded, prompt_text=upgraded.prompt_text + "!"),
            actor="test:v2-edit",
        )
    before_db = _database_snapshot(session_factory)

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        GraphConfiguration().get_draft_legacy_prompt_source(
            session,
            agent_key=agent_key,
            expected_lock_version=2,
            actor="test:unavailable-draft",
        )

    assert _issue_tuples(caught) == LEGACY_SOURCE_UNAVAILABLE_TUPLE
    assert _database_snapshot(session_factory) == before_db


@pytest.mark.parametrize("agent_key", ["data_analyst", "build_reviewer"])
def test_legacy_prompt_source_is_unavailable_for_a_published_source_mismatch(
    session_factory, agent_key
) -> None:
    """Catches recovery trusting a published revision that is not the retained source."""
    before, _ = _stored_content(session_factory, agent_key)
    with session_factory() as session:
        GraphConfiguration().save_editable_model_draft(
            session,
            agent_key=agent_key,
            expected_lock_version=0,
            candidate=_editable(before, prompt_text=before.prompt_text + "!"),
            actor="test:one-code-point",
        )
    with session_factory.begin() as session:
        row = session.scalar(
            select(AgentDefinitionRevision).where(
                AgentDefinitionRevision.agent_key == agent_key
            )
        )
        published = definition_content_from_row(row).model_copy(
            update={"prompt_text": before.prompt_text + " published drift"}
        )
        for column_name, value in definition_content_values(published).items():
            setattr(row, column_name, value)
        row.content_hash = definition_content_hash(published)
    before_db = _database_snapshot(session_factory)

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        GraphConfiguration().get_draft_legacy_prompt_source(
            session,
            agent_key=agent_key,
            expected_lock_version=1,
            actor="test:unavailable-published",
        )

    assert _issue_tuples(caught) == LEGACY_SOURCE_UNAVAILABLE_TUPLE
    assert _database_snapshot(session_factory) == before_db


@pytest.mark.parametrize("agent_key", ["data_analyst", "build_reviewer"])
def test_persisted_upgrade_matches_independent_literal_transition_bytes(
    session_factory, agent_key
) -> None:
    """Catches a wrong retained literal that round-trips through the assembler's own output."""
    source_literal, target_literal = INDEPENDENT_TRANSITION_LITERALS[agent_key]
    generated = next(
        item
        for item in load_graph_v1_manifest().definitions
        if item.agent_key == agent_key
    )
    bootstrapped, _ = _stored_content(session_factory, agent_key)
    assert generated.prompt_text == source_literal
    assert bootstrapped.prompt_text == source_literal

    _upgrade(session_factory, agent_key, lock_version=0)

    persisted, _ = _stored_content(session_factory, agent_key)
    assert persisted.prompt_text == target_literal
    assert persisted.prompt_text != source_literal
    published, _, _ = _published_content(session_factory, agent_key)
    assert published.prompt_text == source_literal


def test_valid_v2_trusted_content_save_uses_one_mapper_hash_and_audit(
    session_factory, monkeypatch
) -> None:
    """Catches a second writer, hash, or audit increment on the trusted-content path."""
    before_db = _database_snapshot(session_factory)
    _upgrade(session_factory, "architect", lock_version=0)
    # Guidance is legal only under schema contract v2 (#264 I1), so the schema
    # contract is upgraded too; the save under test is then a v2-assembly,
    # v2-schema trusted edit carrying both a custom block and canonical guidance.
    assert isinstance(_upgrade_schema(session_factory, lock_version=1), DraftSaveResult)
    after_upgrade, upgrade_hash = _stored_content(session_factory)
    block = _custom_block(SECOND_BLOCK_ID, "Trusted operator guidance.")
    proposed = after_upgrade.model_copy(
        update={
            "assembly_rules": _v2_rules(block),
            "schema_overlay": SchemaOverlay.model_validate(
                {"field_overrides": {"intent": {"description": "Task 265 guidance."}}}
            ),
        }
    )
    write_log: list[str] = []
    _install_write_spy(monkeypatch, write_log)

    with session_factory() as session:
        result = GraphConfiguration().save_draft_content(
            session,
            agent_key="architect",
            expected_lock_version=2,
            content=proposed,
            actor="test:trusted-v2",
        )

    persisted, persisted_hash = _stored_content(session_factory)
    after_db = _database_snapshot(session_factory)
    assert isinstance(result, DraftSaveResult)
    assert result.changed is True
    assert write_log == ["write"]
    assert persisted == proposed
    assert persisted.assembly_rules == _v2_rules(block)
    assert persisted.protected_assembly == V2_PROTECTED_ASSEMBLY_IDENTITY
    assert persisted.definition_version == after_upgrade.definition_version
    assert persisted.schema_contract == after_upgrade.schema_contract
    assert persisted_hash == definition_content_hash(persisted)
    assert persisted_hash != upgrade_hash
    assert result.definition.candidate_hash == persisted_hash
    assert _draft_audit(session_factory)[:2] == (3, "test:trusted-v2")
    assert after_db["revisions"] == before_db["revisions"]
    assert after_db["releases"] == before_db["releases"]
    assert after_db["mappings"] == before_db["mappings"]


def test_trusted_content_validator_phases_run_in_order_around_stale_comparison(
    session_factory, monkeypatch
) -> None:
    """Catches reordered phases or a post-stale validator running after the writer."""
    log: list[str] = []
    monkeypatch.setattr(
        GraphConfiguration,
        "local_candidate_validators",
        (
            _recording_validator(log, "local-1"),
            _recording_validator(log, "local-2"),
        ),
    )
    monkeypatch.setattr(
        GraphConfiguration,
        "post_stale_validators",
        (
            _recording_validator(log, "post-1"),
            _recording_validator(log, "post-2"),
        ),
    )
    _install_write_spy(monkeypatch, log)
    current, _ = _stored_content(session_factory)

    with session_factory() as session:
        result = GraphConfiguration().save_draft_content(
            session,
            agent_key="architect",
            expected_lock_version=0,
            content=current.model_copy(update={"prompt_text": "trusted ordered edit"}),
            actor="test:trusted-phases",
        )

    assert isinstance(result, DraftSaveResult)
    assert log == ["local-1", "local-2", "post-1", "post-2", "write"]


def test_trusted_content_local_invalid_stale_request_is_ordered_422(
    session_factory, monkeypatch
) -> None:
    """Catches stale comparison outranking a local rejection on the trusted path."""
    log: list[str] = []
    monkeypatch.setattr(
        GraphConfiguration,
        "local_candidate_validators",
        (
            _recording_validator(
                log,
                "local-1",
                ("candidate.first", "first_code", "First recorded issue."),
                ("candidate.second", "second_code", "Second recorded issue."),
            ),
            _recording_validator(
                log, "local-2", ("candidate.third", "third_code", "Third recorded issue.")
            ),
        ),
    )
    monkeypatch.setattr(
        GraphConfiguration,
        "post_stale_validators",
        (_recording_validator(log, "post-1"),),
    )
    _install_write_spy(monkeypatch, log)
    current, current_hash = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)
    before_audit = _draft_audit(session_factory)

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        GraphConfiguration().save_draft_content(
            session,
            agent_key="architect",
            expected_lock_version=7,
            content=current.model_copy(
                update={"prompt_text": "trusted local invalid and stale"}
            ),
            actor="test:trusted-local-invalid-stale",
        )

    assert _issue_tuples(caught) == (
        ("candidate.first", "first_code", "First recorded issue."),
        ("candidate.second", "second_code", "Second recorded issue."),
        ("candidate.third", "third_code", "Third recorded issue."),
    )
    assert log == ["local-1", "local-2"]
    assert _stored_content(session_factory) == (current, current_hash)
    assert _draft_audit(session_factory) == before_audit
    assert _database_snapshot(session_factory) == before_db


def test_trusted_content_local_valid_stale_request_is_coherent_409(
    session_factory, monkeypatch
) -> None:
    """Catches a post-stale validator running for a stale trusted-content request."""
    log: list[str] = []
    monkeypatch.setattr(
        GraphConfiguration,
        "local_candidate_validators",
        (_recording_validator(log, "local-1"),),
    )
    monkeypatch.setattr(
        GraphConfiguration,
        "post_stale_validators",
        (_recording_validator(log, "post-1"),),
    )
    _install_write_spy(monkeypatch, log)
    current, current_hash = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)
    before_audit = _draft_audit(session_factory)

    with session_factory() as session:
        result = GraphConfiguration().save_draft_content(
            session,
            agent_key="architect",
            expected_lock_version=4,
            content=current.model_copy(
                update={"prompt_text": "trusted local valid but stale"}
            ),
            actor="test:trusted-local-valid-stale",
        )

    assert isinstance(result, DraftSaveConflict)
    assert result.expected_lock_version == 4
    assert result.current_lock_version == 0
    assert set(result.server.definitions) == set(GRAPH_V1_AGENT_KEYS)
    assert len(result.server.definitions) == 7
    assert log == ["local-1"]
    assert _stored_content(session_factory) == (current, current_hash)
    assert _draft_audit(session_factory) == before_audit
    assert _database_snapshot(session_factory) == before_db


# ===========================================================================
# #264 Task 4 — schema-overlay validation in the locked writer, and the one
# server-owned v2 schema-contract upgrade.
#
# Every expected field/code/message below is written as a LITERAL rather than
# imported from the module under test: a test that imports the constant it
# asserts cannot guard that constant's value.
# ===========================================================================

#: The registry's v1 bundle declares no optional field, so selecting the v2
#: catalog name before the upgrade is ineligible.  This is the whole mechanism
#: behind "v1 until upgrade".
OVERLAY_INELIGIBLE_TUPLE = (
    (
        "candidate.schema_overlay.additional_optional_fields.0",
        "overlay_optional_field_ineligible",
        "Optional field is not available for this agent.",
    ),
)
OVERLAY_UNKNOWN_FIELD_TUPLE = (
    (
        "candidate.schema_overlay.field_overrides.no_such_field",
        "overlay_unknown_canonical_field",
        "Canonical field is not available for this agent.",
    ),
)
OVERLAY_BLANK_DESCRIPTION_TUPLE = (
    (
        "candidate.schema_overlay.field_overrides.intent.description",
        "overlay_description_blank",
        "Description must not be blank.",
    ),
)
#: The one unlocated overlay issue.  It is server state, not candidate content,
#: so it is reported on the protected identity's own unprefixed field.
OVERLAY_CONTRACT_UNAVAILABLE_TUPLE = (
    (
        "schema_contract",
        "overlay_schema_contract_unavailable",
        "Schema contract bundle is unavailable.",
    ),
)
SCHEMA_ALREADY_CURRENT_TUPLE = (
    (
        "schema_contract",
        "already_current",
        "Schema contract is already current.",
    ),
)
#: #263's landed immutable-identity rejection, which Task 4 consumes rather than
#: re-implements.  Note the field is unprefixed and the code is `immutable_field`
#: — NOT an `overlay_*` code and NOT under the `candidate.` prefix.
SCHEMA_CONTRACT_IMMUTABLE_TUPLE = (
    (
        "schema_contract",
        "immutable_field",
        "Schema contract identity is immutable in a draft save.",
    ),
)

DIAGNOSTIC_NOTES = "diagnostic_notes"


def _overlay(**payload: object) -> SchemaOverlay:
    return SchemaOverlay.model_validate(payload)


def _select_notes() -> SchemaOverlay:
    return _overlay(additional_optional_fields=[DIAGNOSTIC_NOTES])


def _upgrade_schema(
    factory: sessionmaker,
    agent_key: str = "architect",
    *,
    lock_version: int,
    actor: str = "test:schema-upgrade",
):
    with factory() as session:
        return GraphConfiguration().upgrade_draft_schema_contract(
            session,
            agent_key=agent_key,
            expected_lock_version=lock_version,
            actor=actor,
        )


# Literal v2 digests, kept honest by AgentSchemaRegistry.__init__'s frozen-digest
# check which fails closed at module import (M19 confirmed: changing any digest here
# produces SchemaContractMaterialChangedError before a single test runs).
# Source of truth: src/services/agent_schema_registry._V2_DIGESTS.
_V2_SCHEMA_DIGESTS: dict[str, str] = {
    "architect": "a03aefb1735275226fe58c2edd04605e7f4126710c7023caf0e676126fbf4122",
    "data_analyst": "0543006dd98d1d84dc72c1f9b918a97daa93a3020d31e3557b2af8a91715b6c5",
    "builder": "65f29cb9774f96f131dba7dfe48ff04b8775dc0960f95a3c6efc19f326ba6aad",
    "build_reviewer": "20f69d5e65e0b94d4401b0645d16f8b238acd8b4571f9ce184b9d7d9956fc6b1",
    "fixer": "a77a9896705534109179e75a542eec212dbb25fd78582dff256d6b6c976a6143",
    "fix_reviewer": "bbe6bf025d5c2e5dcbe1c23db029caff425890602f7e3819c6472c46e7fdfd99",
    "deck_reviewer": "c466043b24678ceef8c80d3707f7e80672275415a8b1c0e4385f94bfea7104d3",
}


def _v2_schema_identity(agent_key: str = "architect") -> ContentIdentity:
    return ContentIdentity(version=2, digest=_V2_SCHEMA_DIGESTS[agent_key])


# ---------------------------------------------------------------------------
# Which validator tuple the overlay validator is registered in (correction 16)
# ---------------------------------------------------------------------------


def test_overlay_validation_is_registered_in_the_pre_stale_tuple_only() -> None:
    """Catches the overlay validator moving to the post-stale phase.

    Registering it post-stale would make an invalid-plus-stale request return 409
    instead of the mandated ordered 422, and would make every overlay issue
    invisible because the stale check short-circuits first.
    """
    local = GraphConfiguration.local_candidate_validators
    assert local == (
        draft_module._assembly_candidate_validator,
        draft_module._schema_overlay_candidate_validator,
    )
    assert GraphConfiguration.post_stale_validators == ()
    # Order within the pre-stale tuple is part of the contract: #265's assembly
    # validator keeps first position, so its issues precede overlay issues.
    assert local.index(draft_module._assembly_candidate_validator) == 0
    assert local.index(draft_module._schema_overlay_candidate_validator) == 1


def test_invalid_overlay_and_stale_lock_is_an_ordered_422_with_no_write(
    session_factory, monkeypatch
) -> None:
    """The measured 422-before-409 evidence for the real overlay validator.

    This is the correction-16 defect made observable: with the validator in the
    pre-stale tuple an invalid-plus-stale request rejects; moving it post-stale
    returns a conflict and drops the issues entirely.
    """
    current, _ = _stored_content(session_factory)
    # Advance the shared lock so the request below is BOTH invalid and stale.
    with session_factory() as session:
        GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=0,
            candidate=_editable(current, prompt_text="advance the lock"),
            actor="test:advance",
        )
    seeded, seeded_hash = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)
    before_audit = _draft_audit(session_factory)
    # Spy installed AFTER the setup save, so the log covers only the request
    # under test.  Installing it earlier records the setup's own write.
    write_log: list[str] = []
    _install_write_spy(monkeypatch, write_log)

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=0,
            candidate=_editable(
                seeded, prompt_text="invalid and stale", schema_overlay=_select_notes()
            ),
            actor="test:invalid-stale-overlay",
        )

    assert _issue_tuples(caught) == OVERLAY_INELIGIBLE_TUPLE
    assert write_log == []
    assert _stored_content(session_factory) == (seeded, seeded_hash)
    assert _draft_audit(session_factory) == before_audit
    assert _database_snapshot(session_factory) == before_db


def test_valid_overlay_with_stale_lock_is_a_coherent_409(session_factory) -> None:
    """A valid candidate that is merely stale still conflicts rather than rejecting.

    Guidance is valid only under schema contract v2 (#264 I1), and the schema
    upgrade is itself the write that makes ``lock_version=0`` stale.
    """
    assert isinstance(_upgrade_schema(session_factory, lock_version=0), DraftSaveResult)
    seeded, seeded_hash = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)

    with session_factory() as session:
        result = GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=0,
            candidate=_editable(
                seeded,
                prompt_text="valid but stale",
                schema_overlay=_overlay(
                    field_overrides={"intent": {"description": "Valid guidance."}}
                ),
            ),
            actor="test:valid-stale-overlay",
        )

    assert isinstance(result, DraftSaveConflict)
    assert result.expected_lock_version == 0
    assert result.current_lock_version == 1
    assert set(result.server.definitions) == set(GRAPH_V1_AGENT_KEYS)
    assert len(result.server.definitions) == 7
    assert _stored_content(session_factory) == (seeded, seeded_hash)
    assert _database_snapshot(session_factory) == before_db


# ---------------------------------------------------------------------------
# Invalid overlay is a total no-write, on both save paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("schema_version", "overlay_payload", "expected"),
    [
        (1, {"additional_optional_fields": [DIAGNOSTIC_NOTES]}, OVERLAY_INELIGIBLE_TUPLE),
        (
            1,
            {"field_overrides": {"no_such_field": {"description": "x"}}},
            OVERLAY_UNKNOWN_FIELD_TUPLE,
        ),
        # #264 I1: a v1 contract has no overlay grammar, so even well-formed
        # canonical guidance is unavailable until the schema upgrade.
        (1, {"field_overrides": {"intent": {"description": "Legal under v2."}}}, (
            (
                "candidate.schema_overlay.field_overrides.intent",
                "overlay_unknown_canonical_field",
                "Canonical field is not available for this agent.",
            ),
        )),
        (
            2,
            {"field_overrides": {"intent": {"description": "   "}}},
            OVERLAY_BLANK_DESCRIPTION_TUPLE,
        ),
        (2, {"field_overrides": {"intent": {"examples": []}}}, (
            (
                "candidate.schema_overlay.field_overrides.intent.examples",
                "overlay_examples_empty",
                "Examples must contain at least one item.",
            ),
        )),
    ],
)
def test_invalid_client_overlay_rejects_with_no_state_change(
    session_factory, monkeypatch, schema_version, overlay_payload, expected
) -> None:
    """Catches an overlay issue reaching the writer or losing its wire field."""
    lock_version = 0
    if schema_version == 2:
        # Guidance property checks are reachable only under v2 (#264 I1).
        assert isinstance(_upgrade_schema(session_factory, lock_version=0), DraftSaveResult)
        lock_version = 1
    write_log: list[str] = []
    _install_write_spy(monkeypatch, write_log)
    current, current_hash = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)
    before_audit = _draft_audit(session_factory)

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=lock_version,
            candidate=_editable(
                current,
                prompt_text="rejected overlay",
                schema_overlay=_overlay(**overlay_payload),
            ),
            actor="test:invalid-overlay",
        )

    assert _issue_tuples(caught) == expected
    assert write_log == []
    assert _stored_content(session_factory) == (current, current_hash)
    assert _draft_audit(session_factory) == before_audit
    assert _database_snapshot(session_factory) == before_db


def test_invalid_trusted_overlay_rejects_with_no_state_change(
    session_factory, monkeypatch
) -> None:
    """The same guarantee on the trusted full-content path."""
    write_log: list[str] = []
    _install_write_spy(monkeypatch, write_log)
    current, current_hash = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)
    before_audit = _draft_audit(session_factory)

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        GraphConfiguration().save_draft_content(
            session,
            agent_key="architect",
            expected_lock_version=0,
            content=current.model_copy(update={"schema_overlay": _select_notes()}),
            actor="test:trusted-invalid-overlay",
        )

    assert _issue_tuples(caught) == OVERLAY_INELIGIBLE_TUPLE
    assert write_log == []
    assert _stored_content(session_factory) == (current, current_hash)
    assert _draft_audit(session_factory) == before_audit
    assert _database_snapshot(session_factory) == before_db


def test_a_stored_contract_that_does_not_resolve_is_reported_on_the_identity_field(
    session_factory,
) -> None:
    """Catches the unlocated overlay issue being silently dropped or mis-prefixed."""
    current, _ = _stored_content(session_factory)
    unresolvable = current.model_copy(
        update={"schema_contract": ContentIdentity(version=1, digest="0" * 64)}
    )
    _overwrite_draft_row(session_factory, "architect", unresolvable)
    seeded, seeded_hash = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=0,
            candidate=_editable(seeded, prompt_text="unresolvable contract"),
            actor="test:unresolvable",
        )

    assert _issue_tuples(caught) == OVERLAY_CONTRACT_UNAVAILABLE_TUPLE
    assert _stored_content(session_factory) == (seeded, seeded_hash)
    assert _database_snapshot(session_factory) == before_db


# ---------------------------------------------------------------------------
# Ordinary identity rejection — consumed, not re-implemented (correction 18)
# ---------------------------------------------------------------------------


def test_trusted_save_rejects_a_schema_contract_change_with_the_landed_code(
    session_factory,
) -> None:
    """Catches Task 4 adding a second code for the one immutable-identity condition."""
    current, current_hash = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        GraphConfiguration().save_draft_content(
            session,
            agent_key="architect",
            expected_lock_version=0,
            content=current.model_copy(update={"schema_contract": _v2_schema_identity()}),
            actor="test:identity-change",
        )

    assert _issue_tuples(caught) == SCHEMA_CONTRACT_IMMUTABLE_TUPLE
    assert _stored_content(session_factory) == (current, current_hash)
    assert _database_snapshot(session_factory) == before_db


def test_the_client_candidate_cannot_name_the_protected_identity_at_all() -> None:
    """The client path's identity rejection is STRUCTURAL, not a validator.

    ``_immutable_content_issues`` has exactly one call site, inside the trusted
    ``save_draft_content``.  ``save_editable_model_draft`` never calls it, because
    it rebuilds the payload from stored content — so the identity is unreachable
    rather than rejected.  A client that names ``schema_contract`` is refused by
    the editable candidate's own field set, one layer earlier.  Task 4
    deliberately does NOT add a second `immutable_field` guard here.
    """
    field_names = {field.name for field in dataclasses.fields(EditableModelDraft)}
    assert "schema_contract" not in field_names
    assert "definition_version" not in field_names
    assert "protected_assembly" not in field_names
    # The overlay IS editable; the identity that versions it is not.
    assert "schema_overlay" in field_names
    with pytest.raises(TypeError):
        EditableModelDraft(
            prompt_text="x",
            endpoint_name="e",
            temperature=0.1,
            max_tokens=10,
            top_p=0.5,
            schema_contract=ContentIdentity(version=2, digest="a" * 64),
        )


def test_a_client_overlay_never_reaches_the_protected_identity(session_factory) -> None:
    """A client overlay edit leaves every server-owned identity byte-identical."""
    # Guidance is a legal client edit only under schema contract v2 (#264 I1).
    assert isinstance(_upgrade_schema(session_factory, lock_version=0), DraftSaveResult)
    before, _ = _stored_content(session_factory)

    with session_factory() as session:
        result = GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=1,
            candidate=_editable(
                before,
                schema_overlay=_overlay(
                    field_overrides={"intent": {"description": "Client guidance."}}
                ),
            ),
            actor="test:client-overlay",
        )

    assert isinstance(result, DraftSaveResult)
    after, _ = _stored_content(session_factory)
    assert after.schema_contract == before.schema_contract
    assert after.protected_assembly == before.protected_assembly
    assert after.definition_version == before.definition_version
    assert after.schema_overlay != before.schema_overlay


def test_content_identity_cannot_carry_a_role_so_the_pydantic_carrier_gate_is_safe() -> None:
    """Pins the field set of ContentIdentity so that widening it is loud rather than silent.

    The registry's carrier gate (``_replacement_schema_contract_identity``) revalidates
    only ``version`` and ``digest``; a carrier that also held ``agent_key`` would
    silently retain its own role.  The primary safety guard is the
    protected-assembly digest check, which fails closed at **import** time if
    ``ContentIdentity`` is widened (confirmed by M17).  This assertion is belt-and-braces:
    it pins the exact field set so a widening is visible at the unit-test gate rather
    than discovered only at import.
    """
    assert set(ContentIdentity.model_fields) == {"version", "digest"}


# ---------------------------------------------------------------------------
# The server-owned v2 schema-contract upgrade
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("agent_key", list(GRAPH_V1_AGENT_KEYS))
def test_schema_upgrade_installs_the_server_owned_v2_identity_for_every_role(
    session_factory, monkeypatch, agent_key
) -> None:
    """Catches a client-supplied identity, a lost overlay, or a second write."""
    before_db = _database_snapshot(session_factory)
    before, before_hash = _stored_content(session_factory, agent_key)
    write_log: list[str] = []
    _install_write_spy(monkeypatch, write_log)

    result = _upgrade_schema(session_factory, agent_key, lock_version=0)

    after, after_hash = _stored_content(session_factory, agent_key)
    assert isinstance(result, DraftSaveResult)
    assert result.changed is True
    assert write_log == ["write"]
    assert after.schema_contract == _v2_schema_identity(agent_key)
    assert after.schema_contract.version == 2
    assert after.schema_contract != before.schema_contract
    # Everything else is preserved byte-for-byte.
    assert after.prompt_text == before.prompt_text
    assert after.model == before.model
    assert after.assembly_rules == before.assembly_rules
    assert after.protected_assembly == before.protected_assembly
    assert after.definition_version == before.definition_version
    assert after.schema_overlay == before.schema_overlay
    assert after_hash == definition_content_hash(after)
    assert after_hash != before_hash
    assert result.definition.candidate_hash == after_hash
    assert result.draft.lock_version == 1
    # Retained v1 history and release (plan: "retained v1 history/release").
    after_db = _database_snapshot(session_factory)
    assert after_db["revisions"] == before_db["revisions"]
    assert after_db["releases"] == before_db["releases"]
    assert after_db["mappings"] == before_db["mappings"]


def test_the_optional_catalog_becomes_selectable_only_after_the_schema_upgrade(
    session_factory,
) -> None:
    """The one behaviour the whole upgrade exists to enable."""
    before, _ = _stored_content(session_factory)
    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=0,
            candidate=_editable(before, schema_overlay=_select_notes()),
            actor="test:before-upgrade",
        )
    assert _issue_tuples(caught) == OVERLAY_INELIGIBLE_TUPLE

    assert isinstance(_upgrade_schema(session_factory, lock_version=0), DraftSaveResult)

    upgraded, _ = _stored_content(session_factory)
    with session_factory() as session:
        result = GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=1,
            candidate=_editable(upgraded, schema_overlay=_select_notes()),
            actor="test:after-upgrade",
        )

    persisted, persisted_hash = _stored_content(session_factory)
    assert isinstance(result, DraftSaveResult)
    assert result.changed is True
    assert persisted.schema_overlay.additional_optional_fields == (DIAGNOSTIC_NOTES,)
    assert persisted.schema_contract == _v2_schema_identity()
    assert persisted_hash == definition_content_hash(persisted)
    assert _draft_audit(session_factory)[:2] == (2, "test:after-upgrade")


def test_a_repeated_schema_upgrade_reports_already_current_and_writes_nothing(
    session_factory, monkeypatch
) -> None:
    """Catches a second upgrade advancing the lock or rewriting the identity."""
    assert isinstance(_upgrade_schema(session_factory, lock_version=0), DraftSaveResult)
    upgraded, upgraded_hash = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)
    before_audit = _draft_audit(session_factory)
    write_log: list[str] = []
    _install_write_spy(monkeypatch, write_log)

    with pytest.raises(DraftContentRejected) as caught:
        _upgrade_schema(session_factory, lock_version=1, actor="test:already-current")

    assert _issue_tuples(caught) == SCHEMA_ALREADY_CURRENT_TUPLE
    assert write_log == []
    assert _stored_content(session_factory) == (upgraded, upgraded_hash)
    assert _draft_audit(session_factory) == before_audit
    assert _database_snapshot(session_factory) == before_db


def test_a_stale_schema_upgrade_is_a_coherent_409_that_writes_nothing(
    session_factory, monkeypatch
) -> None:
    """A valid stale upgrade conflicts; it never reaches the transition."""
    current, _ = _stored_content(session_factory)
    with session_factory() as session:
        GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=0,
            candidate=_editable(current, prompt_text="advance the lock"),
            actor="test:advance",
        )
    seeded, seeded_hash = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)
    write_log: list[str] = []
    _install_write_spy(monkeypatch, write_log)

    result = _upgrade_schema(session_factory, lock_version=0, actor="test:stale-upgrade")

    assert isinstance(result, DraftSaveConflict)
    assert result.expected_lock_version == 0
    assert result.current_lock_version == 1
    assert result.client_candidate is None
    assert set(result.server.definitions) == set(GRAPH_V1_AGENT_KEYS)
    assert len(result.server.definitions) == 7
    assert result.server.definitions["architect"].content.schema_contract.version == 1
    assert write_log == []
    assert _stored_content(session_factory) == (seeded, seeded_hash)
    assert _database_snapshot(session_factory) == before_db


def test_stale_schema_upgrade_is_a_conflict_even_when_content_is_already_current(
    session_factory, monkeypatch
) -> None:
    """Pins the stale-before-already-current ordering in upgrade_draft_schema_contract.

    Correction 52 rules: the stale check must outrank ``already_current``.  R2 (flip
    ``already_current`` ahead of the stale check) REDs 0/116 focused tests without
    this guard — any later agent can silently revert the ruling.  Modelled on the
    sibling precedent
    ``test_repeated_upgrade_is_already_current_only_for_a_current_request`` (line
    1560), which tests the same combination for ``upgrade_draft_protected_assembly``.

    The conflict body must carry ``schema_contract.version`` so the client can infer
    the contract is already current without a second round trip.
    """
    # First upgrade brings content to v2; lock_version advances from 0 to 1.
    assert isinstance(_upgrade_schema(session_factory, lock_version=0), DraftSaveResult)
    before_db = _database_snapshot(session_factory)
    upgrade_calls: list[str] = []
    original_upgrade = draft_module.upgrade_content_to_v2

    def _spy_upgrade(content):
        upgrade_calls.append(content.agent_key)
        return original_upgrade(content)

    # Spy on the upgrade authority: the stale short-circuit must fire before any
    # upgrade is attempted.
    monkeypatch.setattr(draft_module, "upgrade_content_to_v2", _spy_upgrade)

    # Stale request (lock_version=0) on content that is already v2 (current lock=1).
    result = _upgrade_schema(
        session_factory, lock_version=0, actor="test:already-current-stale"
    )

    assert isinstance(result, DraftSaveConflict)
    assert result.expected_lock_version == 0
    assert result.current_lock_version == 1
    assert result.client_candidate is None
    # The 409 body carries schema_contract.version: one round trip suffices.
    assert result.server.definitions["architect"].content.schema_contract.version == 2
    assert upgrade_calls == []
    assert _database_snapshot(session_factory) == before_db


def test_schema_upgrade_path_performs_exactly_one_row_lookup(
    session_factory, monkeypatch
) -> None:
    """Pins the no-second-lookup clause on the new upgrade entry point.

    The plan forbids a second row lookup on the draft-write path.  R1 adding a second
    writer REDs 12 across two scopes; R7 adding a second lookup REDs 0 without this
    test.  This makes the lookup clause as enforceable as the writer clause.
    """
    read_log: list[str] = []
    original_read = GraphConfiguration._read_workbench_for_draft_write

    def _spy_read(self, session, *, agent_key):
        read_log.append("read")
        return original_read(self, session, agent_key=agent_key)

    monkeypatch.setattr(GraphConfiguration, "_read_workbench_for_draft_write", _spy_read)

    result = _upgrade_schema(session_factory, lock_version=0, actor="test:one-lookup")

    assert isinstance(result, DraftSaveResult)
    assert read_log == ["read"]


def test_an_invalid_plus_stale_schema_upgrade_is_an_ordered_422(
    session_factory, monkeypatch
) -> None:
    """Catches the stale comparison outranking existing-content validation."""
    log: list[str] = []
    monkeypatch.setattr(
        GraphConfiguration,
        "local_candidate_validators",
        (
            _recording_validator(
                log,
                "local-1",
                ("candidate.first", "first_code", "First recorded issue."),
                ("candidate.second", "second_code", "Second recorded issue."),
            ),
            _recording_validator(
                log, "local-2", ("candidate.third", "third_code", "Third recorded issue.")
            ),
        ),
    )
    monkeypatch.setattr(
        GraphConfiguration,
        "post_stale_validators",
        (_recording_validator(log, "post-1"),),
    )
    _install_write_spy(monkeypatch, log)
    current, current_hash = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)

    with pytest.raises(DraftContentRejected) as caught:
        _upgrade_schema(session_factory, lock_version=7, actor="test:invalid-stale")

    assert _issue_tuples(caught) == (
        ("candidate.first", "first_code", "First recorded issue."),
        ("candidate.second", "second_code", "Second recorded issue."),
        ("candidate.third", "third_code", "Third recorded issue."),
    )
    assert log == ["local-1", "local-2"]
    assert _stored_content(session_factory) == (current, current_hash)
    assert _database_snapshot(session_factory) == before_db


def test_the_two_upgrades_deliberately_differ_in_precedence(
    session_factory, monkeypatch
) -> None:
    """The correction-17 guard: the siblings must NOT be harmonised.

    For one identical request shape — locally invalid AND stale — the landed
    protected-assembly upgrade returns #265's shipped 409 while the new
    schema-contract upgrade returns the mandated ordered 422.  Moving the stale
    check in either method REDs this test.  Harmonising them would ship a #265
    regression under a #264 commit.
    """
    monkeypatch.setattr(
        GraphConfiguration,
        "local_candidate_validators",
        (
            _recording_validator(
                [], "local-1", ("candidate.x", "x_code", "Recorded issue.")
            ),
        ),
    )
    write_log: list[str] = []
    _install_write_spy(monkeypatch, write_log)
    current, current_hash = _stored_content(session_factory, "data_analyst")
    before_db = _database_snapshot(session_factory)

    # Sibling: stale BEFORE validation -> 409, issues never computed.
    assembly_outcome = _upgrade(
        session_factory, "data_analyst", lock_version=7, actor="test:assembly-precedence"
    )
    assert isinstance(assembly_outcome, DraftSaveConflict)
    assert assembly_outcome.current_lock_version == 0

    # New method: validation BEFORE stale -> ordered 422.
    with pytest.raises(DraftContentRejected) as caught:
        _upgrade_schema(
            session_factory,
            "data_analyst",
            lock_version=7,
            actor="test:schema-precedence",
        )
    assert _issue_tuples(caught) == (
        ("candidate.x", "x_code", "Recorded issue."),
    )

    assert write_log == []
    assert _stored_content(session_factory, "data_analyst") == (current, current_hash)
    assert _database_snapshot(session_factory) == before_db


def test_the_schema_upgrade_validates_before_reporting_already_current(
    session_factory, monkeypatch
) -> None:
    """Mirrors the assembler's inner ordering: validation outranks already_current."""
    assert isinstance(_upgrade_schema(session_factory, lock_version=0), DraftSaveResult)
    upgraded, upgraded_hash = _stored_content(session_factory)
    # Seed an overlay that is invalid even under v2, on already-current content.
    _overwrite_draft_row(
        session_factory,
        "architect",
        upgraded.model_copy(
            update={
                "schema_overlay": _overlay(
                    field_overrides={"no_such_field": {"description": "x"}}
                )
            }
        ),
    )
    seeded, seeded_hash = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)

    with pytest.raises(DraftContentRejected) as caught:
        _upgrade_schema(session_factory, lock_version=1, actor="test:invalid-current")

    assert _issue_tuples(caught) == OVERLAY_UNKNOWN_FIELD_TUPLE
    assert _stored_content(session_factory) == (seeded, seeded_hash)
    assert _database_snapshot(session_factory) == before_db


def test_a_same_content_overlay_save_advances_the_lock_once_and_reports_unchanged(
    session_factory, monkeypatch
) -> None:
    """The landed same-content contract, exercised through a v2 overlay."""
    assert isinstance(_upgrade_schema(session_factory, lock_version=0), DraftSaveResult)
    upgraded, _ = _stored_content(session_factory)
    with session_factory() as session:
        GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=1,
            candidate=_editable(upgraded, schema_overlay=_select_notes()),
            actor="test:select-notes",
        )
    selected, selected_hash = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)
    write_log: list[str] = []
    _install_write_spy(monkeypatch, write_log)

    with session_factory() as session:
        result = GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=2,
            candidate=_editable(selected, schema_overlay=_select_notes()),
            actor="test:same-overlay",
        )

    after, after_hash = _stored_content(session_factory)
    assert isinstance(result, DraftSaveResult)
    assert result.changed is False
    assert write_log == ["write"]
    assert after == selected
    assert after_hash == selected_hash
    assert _draft_audit(session_factory)[:2] == (3, "test:same-overlay")
    assert _database_snapshot(session_factory)["revisions"] == before_db["revisions"]
    assert _database_snapshot(session_factory)["releases"] == before_db["releases"]


def test_an_absent_client_overlay_retains_the_stored_overlay(session_factory) -> None:
    """Absent never means "clear it": a five-field save keeps the stored overlay."""
    assert isinstance(_upgrade_schema(session_factory, lock_version=0), DraftSaveResult)
    upgraded, _ = _stored_content(session_factory)
    with session_factory() as session:
        GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=1,
            candidate=_editable(upgraded, schema_overlay=_select_notes()),
            actor="test:select-notes",
        )
    selected, _ = _stored_content(session_factory)
    assert selected.schema_overlay.additional_optional_fields == (DIAGNOSTIC_NOTES,)

    with session_factory() as session:
        GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=2,
            candidate=_editable(selected, prompt_text="prompt only edit"),
            actor="test:prompt-only",
        )

    after, _ = _stored_content(session_factory)
    assert after.schema_overlay == selected.schema_overlay
    assert after.prompt_text == "prompt only edit"


def test_an_empty_overlay_document_validates_with_both_fields_defaulted() -> None:
    """Pins correction 30: the converged carrier defaults two formerly-required fields.

    Disclosed and untested before Task 4, which introduces the first non-empty
    overlays.  Pinned here so a later change to either default is loud.
    """
    empty = SchemaOverlay.model_validate({})
    assert dict(empty.field_overrides) == {}
    assert empty.additional_optional_fields == ()
    assert SchemaOverlay.model_fields["field_overrides"].is_required() is False
    assert SchemaOverlay.model_fields["additional_optional_fields"].is_required() is False


def test_only_diagnostic_notes_is_ever_eligible_and_speaker_notes_never_is() -> None:
    """Pins the closed catalog with literals, for every role."""
    registry = AgentSchemaRegistry()
    assert len(GRAPH_V1_AGENT_KEYS) == 7
    for agent_key in GRAPH_V1_AGENT_KEYS:
        v2 = registry.identity_for(agent_key, 2)
        assert registry.validate_overlay(
            agent_key, v2, _overlay(additional_optional_fields=["diagnostic_notes"])
        ) == ()
        refused = registry.validate_overlay(
            agent_key, v2, _overlay(additional_optional_fields=["speaker_notes"])
        )
        assert tuple(
            (issue.code, issue.path) for issue in refused
        ) == (("overlay_optional_field_ineligible", ("additional_optional_fields", 0)),)


# ---------------------------------------------------------------------------
# #264 I1 — the writer and the runtime agree on every overlay shape, per role
# and per schema contract version.
# ---------------------------------------------------------------------------

#: One valid canonical answer per role, so an accepted overlay can actually run.
#: Literal rather than imported from another test module (correction 39).
_CROSS_SEAM_OUTPUT = {
    "architect": {"intent": "discuss", "message": "an answer"},
    "data_analyst": {
        "outcome": "success",
        "synthesis": "a finding",
        "sources": ["warehouse.sales"],
    },
    "builder": {"position": 3, "html": "<section></section>"},
    "build_reviewer": {"slide_index": 2, "verdict": "clean"},
    "fixer": {"position": 3, "html": "<section></section>", "changed": False},
    "fix_reviewer": {"slide_index": 2, "verdict": "clean"},
    "deck_reviewer": {},
}


def _cross_seam_shapes(agent_key: str) -> dict[str, dict[str, object]]:
    """Every overlay shape class the writer distinguishes, for one role."""
    from src.domain.skill_io import OUTPUT_SCHEMAS

    field = next(iter(OUTPUT_SCHEMAS[agent_key].model_fields))
    return {
        "empty": {},
        "description": {"field_overrides": {field: {"description": "Guidance."}}},
        "examples": {"field_overrides": {field: {"examples": ["an example", {"k": 1}]}}},
        "description_and_examples": {
            "field_overrides": {field: {"description": "Both.", "examples": ["x"]}}
        },
        "optional": {"additional_optional_fields": [DIAGNOSTIC_NOTES]},
        "guidance_and_optional": {
            "field_overrides": {field: {"description": "With notes."}},
            "additional_optional_fields": [DIAGNOSTIC_NOTES],
        },
        "unknown_field": {"field_overrides": {"not_a_field": {"description": "x"}}},
        "forbidden_property": {"field_overrides": {field: {"type": "integer"}}},
        "blank_description": {"field_overrides": {field: {"description": "  "}}},
        "empty_examples": {"field_overrides": {field: {"examples": []}}},
        "ineligible_optional": {"additional_optional_fields": ["speaker_notes"]},
        "duplicate_optional": {
            "additional_optional_fields": [DIAGNOSTIC_NOTES, DIAGNOSTIC_NOTES]
        },
        "canonical_collision": {"additional_optional_fields": [field]},
    }


_V2_LEGAL_SHAPES = {
    "empty",
    "description",
    "examples",
    "description_and_examples",
    "optional",
    "guidance_and_optional",
}


@pytest.mark.parametrize("agent_key", GRAPH_V1_AGENT_KEYS)
def test_every_overlay_the_writer_accepts_runs_and_every_one_the_runtime_refuses_is_rejected(
    session_factory, agent_key
) -> None:
    """#264 I1's cross-seam guarantee, for all seven roles under v1 and v2.

    For every overlay shape the writer's client save path either accepts (and
    stores) the overlay, in which case the STORED content composes and runs through
    ``AgentRuntime`` with the model adapter called exactly once; or it rejects it,
    in which case the runtime refuses the same content before the model.  Writer
    acceptance and runtime execution are asserted equal shape by shape, so neither
    seam can admit what the other refuses.  The final assertions pin which shapes
    are legal under each version: under v1 only the empty overlay is.
    """
    from src.domain.skill_io import OUTPUT_SCHEMAS
    from src.services.agent_runtime import (
        AgentAssemblyContext,
        AgentRuntime,
        RecordingAgentInvocationIdentitySink,
    )
    from src.services.persisted_graph_release import (
        PersistedConfigurationUnavailableError,
        ResolvedDefinition,
    )

    class _Loader:
        definition: ResolvedDefinition

        def resolve(self, graph_release_id: int, key: str) -> ResolvedDefinition:
            return self.definition

    class _Adapter:
        def __init__(self) -> None:
            self.calls = 0

        def invoke(self, *, agent_key, configuration, schema, prompt):
            self.calls += 1
            return schema.model_validate(_CROSS_SEAM_OUTPUT[agent_key])

    def _runs(content: DefinitionContent) -> bool:
        loader, adapter = _Loader(), _Adapter()
        loader.definition = ResolvedDefinition(
            graph_version=2,
            graph_release_id=88,
            agent_key=agent_key,
            agent_definition_revision_id=309,
            content_hash=definition_content_hash(content),
            content=content,
        )
        runtime = AgentRuntime(
            persisted_release_loader=loader,
            model_adapter=adapter,
            identity_sink=RecordingAgentInvocationIdentitySink(),
        )
        try:
            result = runtime.run(agent_key, 88, {"x": 1}, AgentAssemblyContext(False))
        except PersistedConfigurationUnavailableError:
            assert adapter.calls == 0
            return False
        assert adapter.calls == 1
        assert type(result.output) is OUTPUT_SCHEMAS[agent_key]
        return True

    accepted_by_version: dict[int, set[str]] = {}
    lock_version = 0
    for version in (1, 2):
        if version == 2:
            upgraded = _upgrade_schema(
                session_factory, agent_key, lock_version=lock_version
            )
            assert isinstance(upgraded, DraftSaveResult)
            lock_version += 1
        accepted: set[str] = set()
        for name, payload in _cross_seam_shapes(agent_key).items():
            overlay = _overlay(**payload)
            current, _ = _stored_content(session_factory, agent_key)
            assert current.schema_contract.version == version
            try:
                with session_factory() as session:
                    result = GraphConfiguration().save_editable_model_draft(
                        session,
                        agent_key=agent_key,
                        expected_lock_version=lock_version,
                        candidate=_editable(current, schema_overlay=overlay),
                        actor="test:cross-seam",
                    )
            except DraftContentRejected:
                writer_accepts = False
                runtime_runs = _runs(current.model_copy(update={"schema_overlay": overlay}))
            else:
                assert isinstance(result, DraftSaveResult), name
                lock_version += 1
                writer_accepts = True
                stored, _ = _stored_content(session_factory, agent_key)
                assert stored.schema_overlay == overlay, name
                runtime_runs = _runs(stored)
            assert writer_accepts == runtime_runs, (version, name)
            if writer_accepts:
                accepted.add(name)
        accepted_by_version[version] = accepted

    assert accepted_by_version == {1: {"empty"}, 2: _V2_LEGAL_SHAPES}


def _raw_draft_overlay(factory: sessionmaker, agent_key: str) -> str:
    """The stored ``schema_overlay`` column, serialized in its stored key order."""
    import json

    with factory() as session:
        return json.dumps(
            session.scalar(
                select(GraphDraftAgent.schema_overlay).where(
                    GraphDraftAgent.agent_key == agent_key
                )
            )
        )


def test_a_legacy_v1_draft_with_guidance_is_rejected_by_the_upgrade_and_kept_byte_for_byte(
    session_factory, monkeypatch
) -> None:
    """#264 I3, as ruled against I1.

    Since I1 the writer cannot SAVE canonical guidance under v1, and bootstrap
    writes only empty v1 overlays, so a v1 draft carrying guidance can only be
    pre-existing data seeded behind the writer.  The upgrade validates the
    existing content first, and that content breaks the one v1 rule every other
    writer and the runtime enforce, so the upgrade REJECTS it with the ordered
    overlay issue rather than silently carrying an illegal state forward — and
    the rejection leaves the stored overlay byte-for-byte as it was, with no
    write at all.  Clearing it with an explicit empty-overlay save is the way out,
    and the upgrade then succeeds (asserted last).
    """
    current, _ = _stored_content(session_factory)
    legacy = current.model_copy(
        update={
            "schema_overlay": _overlay(
                field_overrides={
                    "message": {"description": "Legacy guidance.", "examples": [{"a": [1]}]},
                    "intent": {"description": "Second legacy guidance."},
                }
            )
        }
    )
    assert legacy.schema_contract.version == 1
    _overwrite_draft_row(session_factory, "architect", legacy)
    seeded, seeded_hash = _stored_content(session_factory)
    raw_before = _raw_draft_overlay(session_factory, "architect")
    before_db = _database_snapshot(session_factory)
    before_audit = _draft_audit(session_factory)
    write_log: list[str] = []
    _install_write_spy(monkeypatch, write_log)

    with pytest.raises(DraftContentRejected) as caught:
        _upgrade_schema(session_factory, lock_version=0)

    assert _issue_tuples(caught) == (
        (
            "candidate.schema_overlay.field_overrides.message",
            "overlay_unknown_canonical_field",
            "Canonical field is not available for this agent.",
        ),
        (
            "candidate.schema_overlay.field_overrides.intent",
            "overlay_unknown_canonical_field",
            "Canonical field is not available for this agent.",
        ),
    )
    assert write_log == []
    assert _raw_draft_overlay(session_factory, "architect") == raw_before
    assert _stored_content(session_factory) == (seeded, seeded_hash)
    assert _draft_audit(session_factory) == before_audit
    assert _database_snapshot(session_factory) == before_db

    # The way out: an explicit empty overlay is a legal v1 save, and then the
    # upgrade succeeds.
    with session_factory() as session:
        cleared = GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=0,
            candidate=_editable(seeded, schema_overlay=SchemaOverlay()),
            actor="test:clear-legacy",
        )
    assert isinstance(cleared, DraftSaveResult)
    assert isinstance(_upgrade_schema(session_factory, lock_version=1), DraftSaveResult)
    assert write_log == ["write", "write"]


@pytest.mark.parametrize("phase", ["local_candidate_validators", "post_stale_validators"])
def test_the_schema_upgrade_revalidates_its_target_before_writing(
    session_factory, monkeypatch, phase
) -> None:
    """#264 m2: F5's post-upgrade re-validation is kept and pinned.

    Today's catalogs make it redundant, which is exactly why it needs a test: the
    writer invariant is that every write's content passed the validator tuple, so
    the UPGRADED content must pass both phases too.  A validator that rejects only
    the v2 target (the current v1 content passes it) must stop the upgrade with no
    write, whichever phase it is registered in.
    """
    target_issue = ("schema_contract", "target_rejected", "Only the upgraded target fails.")
    seen: list[int] = []

    def _target_only(content: DefinitionContent) -> tuple[DraftValidationIssue, ...]:
        seen.append(content.schema_contract.version)
        if content.schema_contract.version == 2:
            return (DraftValidationIssue(*target_issue),)
        return ()

    monkeypatch.setattr(
        GraphConfiguration, phase, (*getattr(GraphConfiguration, phase), _target_only)
    )
    write_log: list[str] = []
    _install_write_spy(monkeypatch, write_log)
    current, current_hash = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)
    before_audit = _draft_audit(session_factory)

    with pytest.raises(DraftContentRejected) as caught:
        _upgrade_schema(session_factory, lock_version=0)

    assert _issue_tuples(caught) == (target_issue,)
    assert seen[-1] == 2
    if phase == "local_candidate_validators":
        # It ran on the current content first, and that passed.
        assert seen == [1, 2]
    assert write_log == []
    assert _stored_content(session_factory) == (current, current_hash)
    assert _draft_audit(session_factory) == before_audit
    assert _database_snapshot(session_factory) == before_db


# ===========================================================================
# #266 Task 2 — exact endpoint validation composed into the two save paths.
#
# Local phase: the pure endpoint-name policy joins the ordered pre-stale
# aggregate of both saves (never the class tuples, so upgrades do no endpoint
# work).  Remote phase: the injected validator runs once, only for a current
# locked candidate, immediately before the one writer.  Expected codes and
# messages are literals from the plan's table, not imports.
# ===========================================================================

ENDPOINT_FIELD = "candidate.model.endpoint_name"
ENDPOINT_URL_TUPLE = (
    (
        ENDPOINT_FIELD,
        "endpoint_url_not_allowed",
        "Endpoint must be a Databricks endpoint name, not a URL.",
    ),
)
CUSTOM_ENDPOINT = "custom endpoint name"
SAVE_PATHS = ("editable", "trusted")


class _RecordingRemoteEndpointValidator:
    """Deterministic remote phase: records each complete candidate it sees."""

    def __init__(self, log: list[str] | None = None, outcome: Exception | None = None):
        self.contents: list[DefinitionContent] = []
        self._log = log
        self._outcome = outcome

    def validate(self, content: DefinitionContent) -> None:
        self.contents.append(content)
        if self._log is not None:
            self._log.append(f"remote:{content.model.endpoint_name}")
        if self._outcome is not None:
            raise self._outcome


class _RecordingServingEndpoints:
    """Fake SDK surface for the production catalog; no SDK mock library."""

    def __init__(self, *, detail=None, error: Exception | None = None):
        self.detail = detail
        self.error = error
        self.get_calls: list[str] = []

    def get(self, name: str):
        self.get_calls.append(name)
        if self.error is not None:
            raise self.error
        return self.detail


def _endpoint_candidate(
    current: DefinitionContent,
    path: str,
    *,
    endpoint_name: str,
    prompt_text: str | None = None,
    schema_overlay: SchemaOverlay | None = None,
):
    prompt = current.prompt_text if prompt_text is None else prompt_text
    if path == "editable":
        return _editable(
            current,
            prompt_text=prompt,
            endpoint_name=endpoint_name,
            schema_overlay=schema_overlay,
        )
    update: dict[str, object] = {
        "prompt_text": prompt,
        "model": current.model.model_copy(update={"endpoint_name": endpoint_name}),
    }
    if schema_overlay is not None:
        update["schema_overlay"] = schema_overlay
    return current.model_copy(update=update)


def _save_endpoint_candidate(
    session: Session,
    service: GraphConfiguration,
    path: str,
    candidate,
    *,
    lock_version: int,
    actor: str,
):
    if path == "editable":
        return service.save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=lock_version,
            candidate=candidate,
            actor=actor,
        )
    return service.save_draft_content(
        session,
        agent_key="architect",
        expected_lock_version=lock_version,
        content=candidate,
        actor=actor,
    )


def _advance_lock(factory: sessionmaker) -> None:
    current, _ = _stored_content(factory)
    with factory() as session:
        result = GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=0,
            candidate=_editable(current, prompt_text="advance the shared lock"),
            actor="test:advance",
        )
    assert isinstance(result, DraftSaveResult)


@pytest.mark.parametrize("path", SAVE_PATHS)
@pytest.mark.parametrize(
    "endpoint_name",
    ["https://workspace.example/serving-endpoints/x", "../../2.0/secrets/scopes/list"],
)
def test_endpoint_url_plus_stale_lock_is_ordered_422_with_zero_remote_calls(
    session_factory, monkeypatch, path, endpoint_name
) -> None:
    """Catches the endpoint policy running after the stale comparison (a 409)."""
    _advance_lock(session_factory)
    seeded, seeded_hash = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)
    before_audit = _draft_audit(session_factory)
    write_log: list[str] = []
    _install_write_spy(monkeypatch, write_log)
    remote = _RecordingRemoteEndpointValidator(write_log)
    candidate = _endpoint_candidate(
        seeded, path, endpoint_name=endpoint_name, prompt_text="url and stale"
    )

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        _save_endpoint_candidate(
            session,
            GraphConfiguration(remote_endpoint_validator=remote),
            path,
            candidate,
            lock_version=0,
            actor="test:endpoint-url-stale",
        )

    assert _issue_tuples(caught) == ENDPOINT_URL_TUPLE
    assert remote.contents == []
    assert write_log == []
    assert _stored_content(session_factory) == (seeded, seeded_hash)
    assert _draft_audit(session_factory) == before_audit
    assert _database_snapshot(session_factory) == before_db


@pytest.mark.parametrize("path", SAVE_PATHS)
def test_locally_valid_endpoint_plus_stale_lock_is_seven_role_409_with_zero_remote_calls(
    session_factory, monkeypatch, path
) -> None:
    """Catches the remote endpoint check running before the stale return."""
    _advance_lock(session_factory)
    seeded, seeded_hash = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)
    write_log: list[str] = []
    _install_write_spy(monkeypatch, write_log)
    remote = _RecordingRemoteEndpointValidator(write_log)
    candidate = _endpoint_candidate(
        seeded, path, endpoint_name=CUSTOM_ENDPOINT, prompt_text="valid but stale"
    )

    with session_factory() as session:
        result = _save_endpoint_candidate(
            session,
            GraphConfiguration(remote_endpoint_validator=remote),
            path,
            candidate,
            lock_version=0,
            actor="test:endpoint-valid-stale",
        )

    assert isinstance(result, DraftSaveConflict)
    assert result.expected_lock_version == 0
    assert result.current_lock_version == 1
    assert set(result.server.definitions) == set(GRAPH_V1_AGENT_KEYS)
    assert len(result.server.definitions) == 7
    assert result.server.draft.lock_version == 1
    assert remote.contents == []
    assert write_log == []
    assert _stored_content(session_factory) == (seeded, seeded_hash)
    assert _database_snapshot(session_factory) == before_db


@pytest.mark.parametrize("path", SAVE_PATHS)
def test_endpoint_policy_issue_follows_the_overlay_issue_in_one_ordered_422(
    session_factory, monkeypatch, path
) -> None:
    """Catches the endpoint policy leaving the ordered local aggregate."""
    current, _ = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)
    write_log: list[str] = []
    _install_write_spy(monkeypatch, write_log)
    remote = _RecordingRemoteEndpointValidator(write_log)
    candidate = _endpoint_candidate(
        current,
        path,
        endpoint_name="https://workspace.example/x",
        schema_overlay=_select_notes(),
    )

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        _save_endpoint_candidate(
            session,
            GraphConfiguration(remote_endpoint_validator=remote),
            path,
            candidate,
            lock_version=7,
            actor="test:endpoint-aggregate",
        )

    assert _issue_tuples(caught) == OVERLAY_INELIGIBLE_TUPLE + ENDPOINT_URL_TUPLE
    assert remote.contents == []
    assert write_log == []
    assert _database_snapshot(session_factory) == before_db


def test_editable_command_checks_precede_the_endpoint_phases(session_factory) -> None:
    """Catches the endpoint policy or remote check running before #263's command checks."""
    current, _ = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)
    remote = _RecordingRemoteEndpointValidator()

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        GraphConfiguration(remote_endpoint_validator=remote).save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=0,
            candidate=_editable(current, endpoint_name="https://workspace.example/x"),
            actor="  ",
        )

    assert _issue_tuples(caught) == (("actor", "blank", "Actor must not be blank."),)
    assert remote.contents == []
    assert _database_snapshot(session_factory) == before_db


def test_trusted_immutable_checks_precede_the_endpoint_phases(session_factory) -> None:
    """Catches the endpoint policy outranking #263's round-trip/immutable checks."""
    current, _ = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)
    remote = _RecordingRemoteEndpointValidator()
    proposed = _endpoint_candidate(
        current, "trusted", endpoint_name="https://workspace.example/x"
    ).model_copy(update={"definition_version": current.definition_version + 1})

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        GraphConfiguration(remote_endpoint_validator=remote).save_draft_content(
            session,
            agent_key="architect",
            expected_lock_version=0,
            content=proposed,
            actor="test:endpoint-immutable",
        )

    assert _issue_tuples(caught) == (
        (
            "definition_version",
            "immutable_field",
            "Definition version is immutable in a draft save.",
        ),
    )
    assert remote.contents == []
    assert _database_snapshot(session_factory) == before_db


@pytest.mark.parametrize("path", SAVE_PATHS)
def test_current_endpoint_candidate_is_remotely_validated_once_immediately_before_the_writer(
    session_factory, monkeypatch, path
) -> None:
    """Catches a skipped, repeated, partial, or post-write remote endpoint check."""
    current, _ = _stored_content(session_factory)
    log: list[str] = []
    monkeypatch.setattr(
        GraphConfiguration,
        "post_stale_validators",
        (_recording_validator(log, "post-1"),),
    )
    _install_write_spy(monkeypatch, log)
    remote = _RecordingRemoteEndpointValidator(log)
    candidate = _endpoint_candidate(
        current, path, endpoint_name=CUSTOM_ENDPOINT, prompt_text="current edit"
    )

    with session_factory() as session:
        result = _save_endpoint_candidate(
            session,
            GraphConfiguration(remote_endpoint_validator=remote),
            path,
            candidate,
            lock_version=0,
            actor="test:endpoint-current",
        )

    persisted, persisted_hash = _stored_content(session_factory)
    assert isinstance(result, DraftSaveResult)
    assert result.changed is True
    assert log == ["post-1", f"remote:{CUSTOM_ENDPOINT}", "write"]
    assert len(remote.contents) == 1
    assert isinstance(remote.contents[0], DefinitionContent)
    # The complete reconstructed candidate, not a fragment, reaches the remote
    # phase: it hashes to exactly what the one writer then persisted.
    assert definition_content_hash(remote.contents[0]) == persisted_hash
    assert persisted.model.endpoint_name == CUSTOM_ENDPOINT
    assert persisted_hash == definition_content_hash(persisted)
    assert _draft_audit(session_factory)[:2] == (1, "test:endpoint-current")


def _catalog_remote_validator(serving_endpoints: _RecordingServingEndpoints):
    from types import SimpleNamespace

    from src.services.graph_configuration import CatalogRemoteEndpointDraftValidator
    from src.services.model_endpoint_catalog import DatabricksModelEndpointCatalog

    catalog = DatabricksModelEndpointCatalog(
        SimpleNamespace(serving_endpoints=serving_endpoints)
    )
    return CatalogRemoteEndpointDraftValidator(lambda: catalog)


def _endpoint_detail(name: str, *, ready: str = "READY", update: str = "NOT_UPDATING"):
    from types import SimpleNamespace

    from databricks.sdk.service.serving import (
        EndpointStateConfigUpdate,
        EndpointStateReady,
    )

    return SimpleNamespace(
        name=name,
        state=SimpleNamespace(
            ready=EndpointStateReady[ready],
            config_update=EndpointStateConfigUpdate[update],
        ),
    )


def _remote_table_cases():
    from databricks.sdk.errors import (
        DatabricksError,
        PermissionDenied,
        ResourceDoesNotExist,
    )

    return [
        pytest.param(
            {"error": ResourceDoesNotExist("missing")},
            "endpoint_unknown",
            "Endpoint name was not found.",
            id="unknown",
        ),
        pytest.param(
            {"error": PermissionDenied("denied")},
            "endpoint_forbidden",
            "Endpoint cannot be validated with this workspace identity.",
            id="forbidden",
        ),
        pytest.param(
            {"error": DatabricksError("unavailable")},
            "endpoint_unavailable",
            "Endpoint validation is temporarily unavailable. Retry the save.",
            id="unavailable",
        ),
        pytest.param(
            {"error": TimeoutError("Timed out after 0:00:05")},
            "endpoint_unavailable",
            "Endpoint validation is temporarily unavailable. Retry the save.",
            id="transport-timeout",
        ),
        pytest.param(
            {"detail": _endpoint_detail("alias")},
            "endpoint_name_mismatch",
            "Endpoint validation did not return the exact requested name.",
            id="name-mismatch",
        ),
        pytest.param(
            {"detail": _endpoint_detail(CUSTOM_ENDPOINT, ready="NOT_READY")},
            "endpoint_not_ready",
            "Endpoint is not ready for invocation.",
            id="not-ready",
        ),
        pytest.param(
            {"detail": _endpoint_detail(CUSTOM_ENDPOINT, update="IN_PROGRESS")},
            "endpoint_update_in_progress",
            "Endpoint configuration update is in progress.",
            id="update-in-progress",
        ),
        pytest.param(
            {"detail": _endpoint_detail(CUSTOM_ENDPOINT, update="UPDATE_FAILED")},
            "endpoint_update_failed",
            "Endpoint configuration update failed.",
            id="update-failed",
        ),
        pytest.param(
            {"detail": _endpoint_detail(CUSTOM_ENDPOINT, update="UPDATE_CANCELED")},
            "endpoint_update_canceled",
            "Endpoint configuration update was canceled.",
            id="update-canceled",
        ),
    ]


@pytest.mark.parametrize("path", SAVE_PATHS)
@pytest.mark.parametrize(("outcome", "code", "message"), _remote_table_cases())
def test_every_remote_endpoint_failure_is_one_ordered_issue_with_no_mutation(
    session_factory, monkeypatch, path, outcome, code, message
) -> None:
    """Catches a bypassed, mistranslated, or partially written remote rejection."""
    current, current_hash = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)
    before_audit = _draft_audit(session_factory)
    write_log: list[str] = []
    _install_write_spy(monkeypatch, write_log)
    serving_endpoints = _RecordingServingEndpoints(**outcome)
    candidate = _endpoint_candidate(
        current, path, endpoint_name=CUSTOM_ENDPOINT, prompt_text="remote rejected"
    )

    with session_factory() as session, pytest.raises(DraftContentRejected) as caught:
        _save_endpoint_candidate(
            session,
            GraphConfiguration(
                remote_endpoint_validator=_catalog_remote_validator(serving_endpoints)
            ),
            path,
            candidate,
            lock_version=0,
            actor="test:endpoint-remote-rejected",
        )

    assert _issue_tuples(caught) == ((ENDPOINT_FIELD, code, message),)
    # Exactly one exact-name lookup; the stored text is never rewritten.
    assert serving_endpoints.get_calls == [CUSTOM_ENDPOINT]
    assert write_log == []
    assert _stored_content(session_factory) == (current, current_hash)
    assert _draft_audit(session_factory) == before_audit
    # Revisions, releases (with their effective interval), mappings and draft rows.
    assert _database_snapshot(session_factory) == before_db


@pytest.mark.parametrize("path", SAVE_PATHS)
def test_valid_same_content_endpoint_save_validates_and_advances_audit_unchanged(
    session_factory, path
) -> None:
    """Catches a same-content save that skips remote validation or its audit."""
    current, current_hash = _stored_content(session_factory)
    serving_endpoints = _RecordingServingEndpoints(
        detail=_endpoint_detail(current.model.endpoint_name)
    )
    candidate = _endpoint_candidate(
        current, path, endpoint_name=current.model.endpoint_name
    )

    with session_factory() as session:
        result = _save_endpoint_candidate(
            session,
            GraphConfiguration(
                remote_endpoint_validator=_catalog_remote_validator(serving_endpoints)
            ),
            path,
            candidate,
            lock_version=0,
            actor="test:endpoint-same-content",
        )

    assert isinstance(result, DraftSaveResult)
    assert result.changed is False
    assert result.draft.lock_version == 1
    assert serving_endpoints.get_calls == [current.model.endpoint_name]
    assert _stored_content(session_factory) == (current, current_hash)
    assert _draft_audit(session_factory)[:2] == (1, "test:endpoint-same-content")


@pytest.mark.parametrize("path", SAVE_PATHS)
def test_flush_failure_after_endpoint_validation_rolls_back_from_a_fresh_session(
    session_factory, path
) -> None:
    """Catches remote validation that commits anything before the flush succeeds."""
    current, _ = _stored_content(session_factory)
    before_db = _database_snapshot(session_factory)
    remote = _RecordingRemoteEndpointValidator()
    candidate = _endpoint_candidate(
        current, path, endpoint_name=CUSTOM_ENDPOINT, prompt_text="must roll back"
    )

    with session_factory() as session:
        def _fail_flush(_session: Session, _context, _instances) -> None:
            raise RuntimeError("forced flush failure")

        event.listen(session, "before_flush", _fail_flush, once=True)
        with pytest.raises(RuntimeError, match="forced flush failure"):
            _save_endpoint_candidate(
                session,
                GraphConfiguration(remote_endpoint_validator=remote),
                path,
                candidate,
                lock_version=0,
                actor="test:endpoint-rollback",
            )

    assert [content.model.endpoint_name for content in remote.contents] == [
        CUSTOM_ENDPOINT
    ]
    assert _database_snapshot(session_factory) == before_db


@pytest.mark.parametrize("upgrade", ["protected_assembly", "schema_contract"])
def test_endpoint_checks_are_composed_only_into_the_two_save_paths(
    session_factory, upgrade
) -> None:
    """Catches endpoint checks registered class-wide, where both upgrades run them.

    A legacy row whose stored endpoint fails today's policy must still upgrade,
    and neither upgrade may perform remote endpoint I/O (correction 6).
    """
    current, _ = _stored_content(session_factory)
    legacy_endpoint = "https://legacy.example/serving-endpoints/x"
    _overwrite_draft_row(
        session_factory,
        "architect",
        current.model_copy(
            update={
                "model": current.model.model_copy(
                    update={"endpoint_name": legacy_endpoint}
                )
            }
        ),
    )
    remote = _RecordingRemoteEndpointValidator()
    service = GraphConfiguration(remote_endpoint_validator=remote)

    with session_factory() as session:
        operation = getattr(service, f"upgrade_draft_{upgrade}")
        result = operation(
            session,
            agent_key="architect",
            expected_lock_version=0,
            actor="test:endpoint-upgrade",
        )

    assert isinstance(result, DraftSaveResult)
    assert result.definition.content.model.endpoint_name == legacy_endpoint
    assert remote.contents == []
    assert GraphConfiguration.local_candidate_validators == (
        draft_module._assembly_candidate_validator,
        draft_module._schema_overlay_candidate_validator,
    )
    assert GraphConfiguration.post_stale_validators == ()


def test_default_facade_has_no_remote_endpoint_validator_and_injection_is_keyword_only(
    session_factory,
) -> None:
    """Catches a production-default remote validator or a positional injection seam."""
    remote = _RecordingRemoteEndpointValidator()
    with pytest.raises(TypeError):
        GraphConfiguration(remote)  # type: ignore[misc]
    current, _ = _stored_content(session_factory)

    with session_factory() as session:
        result = GraphConfiguration().save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=0,
            candidate=_editable(current, endpoint_name=CUSTOM_ENDPOINT),
            actor="test:endpoint-default",
        )

    assert isinstance(result, DraftSaveResult)
    assert result.definition.content.model.endpoint_name == CUSTOM_ENDPOINT
    assert remote.contents == []


def test_catalog_remote_endpoint_validator_delegates_the_exact_unchanged_name() -> None:
    """Catches trimming, aliasing, or a second lookup in the production adapter."""
    from src.services.graph_configuration import CatalogRemoteEndpointDraftValidator
    from src.services.model_endpoint_catalog import FakeModelEndpointCatalog

    content = load_graph_v1_manifest().definitions[0]
    exact = "  exact endpoint name  "
    content = content.model_copy(
        update={"model": content.model.model_copy(update={"endpoint_name": exact})}
    )
    fake = FakeModelEndpointCatalog()
    built: list[int] = []

    def _catalog():
        built.append(1)
        return fake

    validator = CatalogRemoteEndpointDraftValidator(_catalog)
    assert built == []  # construction does no catalog/client work
    validator.validate(content)

    assert fake.validated_names == [exact]
    assert fake.list_calls == 0
    assert built == [1]


def test_production_remote_endpoint_validator_uses_a_bounded_system_client(
    monkeypatch,
) -> None:
    """Catches the production factory using the unbounded system client or eager I/O."""
    import src.core.databricks_client as databricks_client
    from src.services import graph_configuration
    from src.services import model_endpoint_catalog as catalog_module

    system_client = object()
    bounded_client = object()
    calls: list[tuple[str, object]] = []

    def _get_system_client():
        calls.append(("system", None))
        return system_client

    def _bounded(client):
        calls.append(("bounded", client))
        return bounded_client

    class _RecordingCatalog:
        def __init__(self, workspace_client):
            calls.append(("catalog", workspace_client))

        def validate_custom_endpoint_remote(self, name):
            calls.append(("validate", name))

    monkeypatch.setattr(databricks_client, "get_system_client", _get_system_client)
    monkeypatch.setattr(catalog_module, "bounded_catalog_workspace_client", _bounded)
    monkeypatch.setattr(catalog_module, "DatabricksModelEndpointCatalog", _RecordingCatalog)

    validator = graph_configuration.build_remote_endpoint_draft_validator()
    assert calls == []

    content = load_graph_v1_manifest().definitions[0]
    validator.validate(content)

    assert calls == [
        ("system", None),
        ("bounded", system_client),
        ("catalog", bounded_client),
        ("validate", content.model.endpoint_name),
    ]


def test_production_remote_endpoint_validator_maps_a_system_client_failure_to_unavailable(
    monkeypatch,
) -> None:
    """Catches a system-client construction failure escaping the save as a 500."""
    import src.core.databricks_client as databricks_client
    from src.services import graph_configuration
    from src.services import model_endpoint_catalog as catalog_module

    built: list[object] = []

    def _failing_system_client():
        raise databricks_client.DatabricksClientError("SECRET_TOKEN_266")

    monkeypatch.setattr(databricks_client, "get_system_client", _failing_system_client)
    monkeypatch.setattr(
        catalog_module, "DatabricksModelEndpointCatalog", lambda client: built.append(client)
    )

    validator = graph_configuration.build_remote_endpoint_draft_validator()
    content = load_graph_v1_manifest().definitions[0]
    with pytest.raises(catalog_module.EndpointValidationFailure) as raised:
        validator.validate(content)

    assert raised.value.code == "endpoint_unavailable"
    assert raised.value.message == (
        "Endpoint validation is temporarily unavailable. Retry the save."
    )
    assert raised.value.retryable is True
    assert "SECRET_TOKEN_266" not in str(raised.value)
    assert isinstance(raised.value.__cause__, databricks_client.DatabricksClientError)
    assert built == []
