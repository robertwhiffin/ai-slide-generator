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
from src.core.skills.build_reviewer import BUILD_REVIEWER_CRITERIA_STAGE
from src.database.models.graph_configuration import (
    AgentDefinitionRevision,
    GraphDraft,
    GraphDraftAgent,
    GraphRelease,
    GraphReleaseAgent,
)
from src.services import graph_configuration_draft as draft_module
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


def test_valid_v2_trusted_content_write_uses_one_mapper_hash_and_audit(
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
                    "invalid_content",
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
