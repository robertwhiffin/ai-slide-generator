"""#269 Task 1: the atomic publication core on SQLite.

SQLite has no mutation-guard triggers and renders no ``FOR UPDATE``; the
PostgreSQL twin (``tests/integration/test_graph_release_publication_postgres.py``)
proves the locks, the guards and the rollback at every write seam.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event, select, text, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register the complete ORM metadata
import src.services.graph_configuration_publication as publication_module
from src.core.database import Base
from src.database.models.graph_configuration import (
    AgentDefinitionRevision,
    GraphDraft,
    GraphDraftAgent,
    GraphRelease,
    GraphReleaseAgent,
)
from src.services.graph_configuration import (
    BootstrapResult,
    DraftSaveResult,
    DraftValidationIssue,
    EditableModelDraft,
    GraphConfiguration,
    GraphConfigurationIntegrityError,
    NothingToPublish,
    PublicationConflict,
    PublicationGap,
    PublicationNotReady,
    PublicationRejected,
    PublishedMapping,
    PublishedRelease,
)
from src.services.graph_configuration_content import (
    as_utc_aware,
    definition_content_from_row,
)
from src.services.graph_configuration_publication import (
    _GraphConfigurationPublication,
)
from src.services.graph_definition_manifest import (
    GRAPH_V1_AGENT_KEYS,
    definition_content_hash,
)


class _NoEvidenceGate:
    """Phase A only. Publishes without approval evidence; never constructed by a route."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def lock_and_verify(self, session, *, snapshot, changed_agent_keys):
        self.calls.append(tuple(changed_agent_keys))
        return ()


class _FixedGate:
    def __init__(self, result) -> None:
        self.result = result
        self.calls: list[tuple[str, ...]] = []

    def lock_and_verify(self, session, *, snapshot, changed_agent_keys):
        self.calls.append(tuple(changed_agent_keys))
        return self.result


@pytest.fixture
def factory() -> Iterator[sessionmaker]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    GraphConfiguration().bootstrap_v1(session_factory)
    try:
        yield session_factory
    finally:
        engine.dispose()


def _backdate_v1(factory) -> None:
    with factory.begin() as db:  # SQLite has no mutation-guard triggers
        db.execute(
            text(
                "UPDATE graph_release SET effective_from = datetime('now','-1 hour'), "
                "published_at = datetime('now','-1 hour') WHERE version_number = 1"
            )
        )


def _save_prompt(factory, agent_key, suffix, *, lock, prompt_text=None):
    service = GraphConfiguration()
    with factory() as db:
        snap = service.read_workbench(db)
        db.rollback()
    content = next(n for n in snap.nodes if n.agent_key == agent_key).draft.content
    with factory() as db:
        out = service.save_editable_model_draft(
            db,
            agent_key=agent_key,
            expected_lock_version=lock,
            actor="editor@example.com",
            candidate=EditableModelDraft(
                prompt_text=(
                    content.prompt_text + suffix if prompt_text is None else prompt_text
                ),
                endpoint_name=content.model.endpoint_name,
                temperature=float(content.model.temperature),
                max_tokens=content.model.max_tokens,
                top_p=float(content.model.top_p),
            ),
        )
    assert isinstance(out, DraftSaveResult)
    return out


def _artifacts(factory) -> dict[str, list[tuple[object, ...]]]:
    with factory() as db:
        return {
            "revisions": [
                tuple(row)
                for row in db.execute(
                    select(
                        AgentDefinitionRevision.id,
                        AgentDefinitionRevision.agent_key,
                        AgentDefinitionRevision.content_hash,
                        AgentDefinitionRevision.created_by,
                        AgentDefinitionRevision.created_at,
                    ).order_by(AgentDefinitionRevision.id)
                )
            ],
            "releases": [
                tuple(row)
                for row in db.execute(
                    select(
                        GraphRelease.id,
                        GraphRelease.version_number,
                        GraphRelease.previous_release_id,
                        GraphRelease.restored_from_release_id,
                        GraphRelease.release_note,
                        GraphRelease.published_by,
                        GraphRelease.published_at,
                        GraphRelease.effective_from,
                        GraphRelease.effective_to,
                    ).order_by(GraphRelease.id)
                )
            ],
            "mappings": [
                tuple(row)
                for row in db.execute(
                    select(
                        GraphReleaseAgent.graph_release_id,
                        GraphReleaseAgent.agent_key,
                        GraphReleaseAgent.agent_definition_revision_id,
                    ).order_by(
                        GraphReleaseAgent.graph_release_id, GraphReleaseAgent.agent_key
                    )
                )
            ],
            "draft": [
                tuple(row)
                for row in db.execute(
                    select(
                        GraphDraft.id,
                        GraphDraft.base_release_id,
                        GraphDraft.lock_version,
                        GraphDraft.updated_by,
                        GraphDraft.updated_at,
                    )
                )
            ],
            "draft_agents": [
                tuple(row)
                for row in db.execute(
                    select(
                        GraphDraftAgent.graph_draft_id,
                        GraphDraftAgent.agent_key,
                        GraphDraftAgent.candidate_hash,
                        GraphDraftAgent.prompt_text,
                        GraphDraftAgent.endpoint_name,
                    ).order_by(GraphDraftAgent.agent_key)
                )
            ],
        }


def _v1(factory) -> GraphRelease:
    with factory() as db:
        return db.scalar(select(GraphRelease).where(GraphRelease.version_number == 1))


def _v1_mappings(factory) -> dict[str, int]:
    v1 = _v1(factory)
    with factory() as db:
        return dict(
            db.execute(
                select(
                    GraphReleaseAgent.agent_key,
                    GraphReleaseAgent.agent_definition_revision_id,
                ).where(GraphReleaseAgent.graph_release_id == v1.id)
            ).all()
        )


def _publish(factory, *, lock, gate, note="Tune two roles", actor="publisher@example.com",
             service=None):
    service = GraphConfiguration() if service is None else service
    with factory() as db:
        return service.publish_draft(
            db,
            expected_lock_version=lock,
            release_note=note,
            actor=actor,
            evidence_gate=gate,
        )


# ---------------------------------------------------------------------------
# as_utc_aware (Correction 3)
# ---------------------------------------------------------------------------


def test_as_utc_aware_labels_a_naive_value_utc_without_moving_it():
    naive = datetime(2026, 9, 26, 10, 11, 12, 345678)
    aware = as_utc_aware(naive)
    assert aware.utcoffset() == timedelta(0)
    assert aware.replace(tzinfo=None) == naive
    assert (aware.year, aware.month, aware.day, aware.hour, aware.minute) == (
        2026, 9, 26, 10, 11,
    )


def test_as_utc_aware_returns_an_aware_value_unchanged():
    aware = datetime(2026, 9, 26, 10, 0, tzinfo=timezone(timedelta(hours=2)))
    assert as_utc_aware(aware) is aware


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_publish_two_changed_roles_creates_v2_with_exact_seven_mappings(
    factory, monkeypatch
):
    _backdate_v1(factory)
    v1 = _v1(factory)
    v1_mappings = _v1_mappings(factory)
    architect = _save_prompt(factory, "architect", "\n\nTune A.", lock=0)
    builder = _save_prompt(factory, "builder", "\n\nTune B.", lock=1)
    gate = _NoEvidenceGate()

    aware_calls: list[tuple[datetime, datetime]] = []
    real_as_utc_aware = publication_module.as_utc_aware

    def _spy_as_utc_aware(value):
        result = real_as_utc_aware(value)
        aware_calls.append((value, result))
        return result

    monkeypatch.setattr(publication_module, "as_utc_aware", _spy_as_utc_aware)

    result = _publish(factory, lock=2, gate=gate)

    assert isinstance(result, PublishedRelease)
    assert len(aware_calls) == 1
    (argument, returned), = aware_calls
    assert argument.tzinfo is None
    assert returned.utcoffset() == timedelta(0)

    assert result.release.version_number == 2
    assert result.previous_release_id == v1.id
    assert result.release.previous_release_id == v1.id
    assert result.release.restored_from_release_id is None
    assert result.release.release_note == "Tune two roles"
    assert result.release.published_by == "publisher@example.com"
    assert result.release.effective_to is None
    assert result.changed_agent_keys == ("architect", "builder")
    assert result.evidence == ()
    assert gate.calls == [("architect", "builder")]
    assert tuple(result.mappings) == GRAPH_V1_AGENT_KEYS

    with factory() as db:
        v2_row = db.get(GraphRelease, result.release.release_id)
        v1_row = db.get(GraphRelease, v1.id)
        draft_row = db.get(GraphDraft, 1)
        v2_mappings = dict(
            db.execute(
                select(
                    GraphReleaseAgent.agent_key,
                    GraphReleaseAgent.agent_definition_revision_id,
                ).where(GraphReleaseAgent.graph_release_id == v2_row.id)
            ).all()
        )
        revisions = {
            key: db.get(AgentDefinitionRevision, revision_id)
            for key, revision_id in v2_mappings.items()
        }
    assert v2_row.version_number == 2
    assert v2_mappings == {
        key: mapping.agent_definition_revision_id
        for key, mapping in result.mappings.items()
    }
    for key in GRAPH_V1_AGENT_KEYS:
        mapping = result.mappings[key]
        assert mapping.agent_key == key
        assert mapping.content_hash == revisions[key].content_hash
        if key in ("architect", "builder"):
            assert mapping.reused is False
            assert mapping.agent_definition_revision_id not in v1_mappings.values()
        else:
            assert mapping == PublishedMapping(
                key, v1_mappings[key], revisions[key].content_hash, True
            )
    assert result.mappings["architect"].content_hash == definition_content_hash(
        architect.definition.content
    )
    assert result.mappings["builder"].content_hash == definition_content_hash(
        builder.definition.content
    )
    assert definition_content_from_row(revisions["architect"]).canonical_payload() == (
        architect.definition.content.canonical_payload()
    )

    # Contiguous interval, compared naive-to-naive as read back (Correction 3).
    assert v1_row.effective_to is not None
    assert v1_row.effective_to == v2_row.effective_from == v2_row.published_at
    assert draft_row.updated_at == v2_row.effective_from
    assert v2_row.effective_to is None

    assert draft_row.base_release_id == v2_row.id
    assert draft_row.lock_version == 3
    assert draft_row.updated_by == "publisher@example.com"
    assert result.draft.base_release_id == v2_row.id
    assert result.draft.base_version_number == 2
    assert result.draft.lock_version == 3
    assert result.draft.updated_by == "publisher@example.com"

    with factory() as db:
        after = GraphConfiguration().read_workbench(db)
        db.rollback()
    assert after.active_release.release_id == v2_row.id
    assert all(node.changed is False for node in after.nodes)
    assert GraphConfiguration().bootstrap_v1(factory) == BootstrapResult(
        False, v2_row.id, 2
    )


def test_note_is_stored_verbatim(factory):
    _backdate_v1(factory)
    _save_prompt(factory, "architect", "\n\nTune.", lock=0)
    result = _publish(factory, lock=1, gate=_NoEvidenceGate(), note="  keep  ")
    assert isinstance(result, PublishedRelease)
    with factory() as db:
        stored = db.scalar(
            select(GraphRelease.release_note).where(
                GraphRelease.id == result.release.release_id
            )
        )
    assert stored == "  keep  "
    assert result.release.release_note == "  keep  "


def test_a_2000_character_note_is_accepted_and_stored_verbatim(factory):
    _backdate_v1(factory)
    _save_prompt(factory, "architect", "\n\nTune.", lock=0)
    note = " " + "n" * 1998 + " "
    assert len(note) == 2000
    result = _publish(factory, lock=1, gate=_NoEvidenceGate(), note=note)
    assert isinstance(result, PublishedRelease)
    with factory() as db:
        stored = db.scalar(
            select(GraphRelease.release_note).where(
                GraphRelease.id == result.release.release_id
            )
        )
    assert stored == note


# ---------------------------------------------------------------------------
# Refusals that write nothing
# ---------------------------------------------------------------------------


def test_stale_lock_version_returns_conflict_and_writes_nothing(factory):
    _backdate_v1(factory)
    v1 = _v1(factory)
    _save_prompt(factory, "architect", "\n\nTune A.", lock=0)
    _save_prompt(factory, "builder", "\n\nTune B.", lock=1)
    before = _artifacts(factory)
    with factory() as db:
        current = GraphConfiguration().read_workbench(db).draft
        db.rollback()
    gate = _NoEvidenceGate()

    result = _publish(factory, lock=1, gate=gate)

    assert result == PublicationConflict(
        expected_lock_version=1,
        current_lock_version=2,
        active_release_id=v1.id,
        active_version_number=1,
        draft=current,
    )
    assert _artifacts(factory) == before
    assert gate.calls == []


def test_nothing_changed_returns_nothing_to_publish(factory):
    v1 = _v1(factory)
    before = _artifacts(factory)
    with factory() as db:
        current = GraphConfiguration().read_workbench(db).draft
        db.rollback()
    gate = _NoEvidenceGate()

    result = _publish(factory, lock=0, gate=gate)

    assert result == NothingToPublish(current, v1.id, 1)
    assert _artifacts(factory) == before
    assert gate.calls == []


def test_stale_lock_with_nothing_changed_is_a_conflict_not_nothing_to_publish(factory):
    """m1: stale is checked before nothing-to-publish.

    Admin B saves and then reverts to the published content (lock 0 -> 2), so no
    role differs from v1.  A publisher still holding lock 0 never previewed that
    draft history and must get the stale conflict.
    """
    v1 = _v1(factory)
    with factory() as db:
        published_prompt = next(
            n for n in GraphConfiguration().read_workbench(db).nodes
            if n.agent_key == "architect"
        ).published.content.prompt_text
        db.rollback()
    _save_prompt(factory, "architect", "\n\nTune A.", lock=0)
    _save_prompt(factory, "architect", "", lock=1, prompt_text=published_prompt)
    with factory() as db:
        current = GraphConfiguration().read_workbench(db)
        db.rollback()
    assert all(node.changed is False for node in current.nodes)
    assert current.draft.lock_version == 2
    before = _artifacts(factory)
    gate = _NoEvidenceGate()

    result = _publish(factory, lock=0, gate=gate)

    assert result == PublicationConflict(0, 2, v1.id, 1, current.draft)
    assert _artifacts(factory) == before
    assert gate.calls == []


_ACTOR_BLANK = DraftValidationIssue("actor", "blank", "Actor must not be blank.")
_LOCK_RANGE = DraftValidationIssue(
    "lock_version", "out_of_range", "Lock version must be greater than or equal to 0."
)
_LOCK_TYPE = DraftValidationIssue(
    "lock_version", "strict_type", "Lock version must be an integer."
)
_NOTE_TYPE = DraftValidationIssue(
    "release_note", "strict_type", "Release note must be a string."
)
_NOTE_BLANK = DraftValidationIssue(
    "release_note", "blank", "Release note must not be blank."
)
_NOTE_LONG = DraftValidationIssue(
    "release_note", "too_long", "Release note must be at most 2000 characters."
)


@pytest.mark.parametrize(
    ("actor", "lock", "note", "expected"),
    [
        pytest.param("p@example.com", 1, "", (_NOTE_BLANK,), id="note-empty"),
        pytest.param("p@example.com", 1, "   ", (_NOTE_BLANK,), id="note-spaces"),
        pytest.param("p@example.com", 1, None, (_NOTE_TYPE,), id="note-none"),
        pytest.param("p@example.com", 1, 7, (_NOTE_TYPE,), id="note-int"),
        pytest.param("p@example.com", -1, "ok", (_LOCK_RANGE,), id="lock-negative"),
        pytest.param("p@example.com", True, "ok", (_LOCK_TYPE,), id="lock-bool"),
        pytest.param("", 1, "ok", (_ACTOR_BLANK,), id="actor-blank"),
        pytest.param(
            "p@example.com", 1, "x" * 2001, (_NOTE_LONG,), id="note-2001"
        ),
        pytest.param(
            "", -1, "   ", (_ACTOR_BLANK, _LOCK_RANGE, _NOTE_BLANK), id="all-three"
        ),
        pytest.param(
            "", True, 7, (_ACTOR_BLANK, _LOCK_TYPE, _NOTE_TYPE), id="all-three-types"
        ),
    ],
)
def test_blank_note_and_bad_types_reject_before_any_lock(
    factory, monkeypatch, actor, lock, note, expected
):
    _backdate_v1(factory)
    _save_prompt(factory, "architect", "\n\nTune.", lock=0)
    before = _artifacts(factory)
    lock_calls: list[bool] = []
    original = GraphConfiguration._lock_current_parents

    def _spy(self, session, *, exclusive):
        lock_calls.append(exclusive)
        return original(self, session, exclusive=exclusive)

    monkeypatch.setattr(GraphConfiguration, "_lock_current_parents", _spy)
    gate = _NoEvidenceGate()

    with pytest.raises(PublicationRejected) as caught:
        _publish(factory, lock=lock, gate=gate, note=note, actor=actor)

    assert caught.value.issues == expected
    assert lock_calls == []
    assert gate.calls == []
    assert _artifacts(factory) == before


def test_publication_rejected_requires_an_issue():
    with pytest.raises(ValueError, match="requires at least one issue"):
        PublicationRejected()


def test_invalid_changed_candidate_rejects_with_prefixed_issues(factory, monkeypatch):
    _backdate_v1(factory)
    _save_prompt(factory, "architect", "\n\nTune A.", lock=0)
    _save_prompt(factory, "builder", "\n\nTune B.", lock=1)
    before = _artifacts(factory)
    monkeypatch.setattr(
        _GraphConfigurationPublication,
        "local_candidate_validators",
        (
            lambda c: (DraftValidationIssue("candidate.prompt_text", "x", "X."),)
            if c.agent_key == "builder"
            else (),
        ),
    )
    gate = _NoEvidenceGate()

    with pytest.raises(PublicationRejected) as caught:
        _publish(factory, lock=2, gate=gate)

    assert caught.value.issues == (
        DraftValidationIssue("definitions.builder.candidate.prompt_text", "x", "X."),
    )
    assert gate.calls == []
    assert _artifacts(factory) == before


def test_url_shaped_endpoint_written_past_the_save_is_rejected_at_publication(
    factory,
):
    """Correction 37: publication re-runs #266's local endpoint-name policy."""
    _backdate_v1(factory)
    _save_prompt(factory, "architect", "\n\nTune A.", lock=0)
    with factory.begin() as db:
        row = db.scalar(
            select(GraphDraftAgent).where(GraphDraftAgent.agent_key == "builder")
        )
        row.endpoint_name = "https://x/y"
        row.candidate_hash = definition_content_hash(definition_content_from_row(row))
    before = _artifacts(factory)
    gate = _NoEvidenceGate()

    with pytest.raises(PublicationRejected) as caught:
        _publish(factory, lock=1, gate=gate)

    assert caught.value.issues == (
        DraftValidationIssue(
            "definitions.builder.candidate.model.endpoint_name",
            "endpoint_url_not_allowed",
            "Endpoint must be a Databricks endpoint name, not a URL.",
        ),
    )
    assert gate.calls == []
    assert _artifacts(factory) == before


def test_publication_never_calls_the_remote_endpoint_validator(factory):
    """Correction 37: no network call while the release row is locked."""

    class _SpyRemoteValidator:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def validate(self, content) -> None:
            self.calls.append(content.agent_key)

    _backdate_v1(factory)
    _save_prompt(factory, "architect", "\n\nTune A.", lock=0)
    spy = _SpyRemoteValidator()

    result = _publish(
        factory,
        lock=1,
        gate=_NoEvidenceGate(),
        service=GraphConfiguration(remote_endpoint_validator=spy),
    )

    assert isinstance(result, PublishedRelease)
    assert result.changed_agent_keys == ("architect",)
    assert spy.calls == []


def test_gate_not_ready_writes_nothing(factory):
    _backdate_v1(factory)
    _save_prompt(factory, "architect", "\n\nTune A.", lock=0)
    before = _artifacts(factory)
    not_ready = PublicationNotReady(
        locked_gaps=(PublicationGap("architect", 1, "no_eligible_approval"),),
        readiness="sentinel",
    )
    gate = _FixedGate(not_ready)

    result = _publish(factory, lock=1, gate=gate)

    assert result is not_ready
    assert gate.calls == [("architect",)]
    assert _artifacts(factory) == before


@pytest.mark.parametrize(
    "gaps",
    [
        pytest.param((), id="empty"),
        pytest.param(
            (PublicationGap("architect", 1, "no_required_case"),),
            id="no-required-case-with-id",
        ),
        pytest.param(
            (PublicationGap("architect", None, "no_eligible_approval"),),
            id="no-eligible-approval-without-id",
        ),
    ],
)
def test_publication_not_ready_rejects_malformed_gaps(gaps):
    with pytest.raises(ValueError):
        PublicationNotReady(locked_gaps=gaps, readiness=None)


def test_publication_not_ready_accepts_both_gap_codes():
    value = PublicationNotReady(
        locked_gaps=(
            PublicationGap("architect", None, "no_required_case"),
            PublicationGap("builder", 4, "no_eligible_approval"),
        ),
        readiness="sentinel",
    )
    assert value.locked_gaps[0].test_case_id is None
    assert value.locked_gaps[1].test_case_id == 4


def test_evidence_from_a_phase_a_gate_is_refused_before_the_draft_rebases(factory):
    """Phase A has no evidence table; a gate that returns links cannot publish."""
    _backdate_v1(factory)
    _save_prompt(factory, "architect", "\n\nTune A.", lock=0)
    before = _artifacts(factory)
    link = publication_module.EvidenceLink(
        agent_test_run_id=1,
        agent_key="architect",
        test_case_id=1,
        evidence_kind="approval",
        source_release_id=None,
    )

    with pytest.raises(
        GraphConfigurationIntegrityError,
        match="^release evidence linking is not available$",
    ):
        _publish(factory, lock=1, gate=_FixedGate((link,)))

    assert _artifacts(factory) == before


# ---------------------------------------------------------------------------
# The #270 seam and the interval guard
# ---------------------------------------------------------------------------


def test_core_writes_restored_from_verbatim(factory):
    _backdate_v1(factory)
    v1 = _v1(factory)
    v1_mappings = _v1_mappings(factory)
    service = GraphConfiguration()

    with factory() as db:
        with db.begin():
            release_row, draft_row = service._lock_current_parents(db, exclusive=True)
            snapshot = service._snapshot_locked_workbench(
                db, release=release_row, draft=draft_row
            )
            contents = {
                node.agent_key: node.published.content
                for node in snapshot.nodes
                if node.execution_kind == "model"
            }
            result = service._commit_locked_publication(
                db,
                release_row=release_row,
                draft_row=draft_row,
                snapshot=snapshot,
                contents=contents,
                evidence=(),
                release_note="Restore v1",
                actor="restorer@example.com",
                restored_from_release_id=v1.id,
            )

    assert isinstance(result, PublishedRelease)
    assert result.release.version_number == 2
    assert result.release.restored_from_release_id == v1.id
    assert result.changed_agent_keys == ()
    assert all(mapping.reused is True for mapping in result.mappings.values())
    assert {
        key: mapping.agent_definition_revision_id
        for key, mapping in result.mappings.items()
    } == v1_mappings
    with factory() as db:
        stored = db.get(GraphRelease, result.release.release_id)
        draft = db.get(GraphDraft, 1)
    assert stored.restored_from_release_id == v1.id
    assert stored.previous_release_id == v1.id
    assert draft.base_release_id == stored.id


def test_core_refuses_an_incomplete_content_set_before_any_write(factory):
    _backdate_v1(factory)
    before = _artifacts(factory)
    service = GraphConfiguration()
    with factory() as db:
        with pytest.raises(
            GraphConfigurationIntegrityError,
            match="^publication requires exactly seven definitions$",
        ):
            with db.begin():
                release_row, draft_row = service._lock_current_parents(
                    db, exclusive=True
                )
                snapshot = service._snapshot_locked_workbench(
                    db, release=release_row, draft=draft_row
                )
                contents = {
                    node.agent_key: node.published.content
                    for node in snapshot.nodes
                    if node.execution_kind == "model" and node.agent_key != "fixer"
                }
                service._commit_locked_publication(
                    db,
                    release_row=release_row,
                    draft_row=draft_row,
                    snapshot=snapshot,
                    contents=contents,
                    evidence=(),
                    release_note="Six only",
                    actor="restorer@example.com",
                    restored_from_release_id=None,
                )
    assert _artifacts(factory) == before


@pytest.mark.parametrize(
    "offset",
    [pytest.param(timedelta(0), id="same"), pytest.param(timedelta(seconds=-1), id="before")],
)
def test_same_second_timestamp_raises_before_write(factory, monkeypatch, offset):
    """Correction 4: an injected transaction timestamp, not wall-clock luck."""
    _backdate_v1(factory)
    _save_prompt(factory, "architect", "\n\nTune A.", lock=0)
    v1_from = as_utc_aware(_v1(factory).effective_from)
    before = _artifacts(factory)
    calls: list[object] = []

    def _fixed_timestamp(session):
        calls.append(session)
        return v1_from + offset

    monkeypatch.setattr(
        publication_module, "database_transaction_timestamp", _fixed_timestamp
    )
    gate = _NoEvidenceGate()

    with pytest.raises(
        GraphConfigurationIntegrityError,
        match="^publication timestamp does not follow the active release interval$",
    ):
        _publish(factory, lock=1, gate=gate)

    assert len(calls) == 1
    assert len(gate.calls) <= 1
    assert _artifacts(factory) == before


def test_an_unchanged_role_that_does_not_reuse_its_revision_is_an_integrity_error(
    factory, monkeypatch
):
    """The reuse guard: an unchanged role must map to the published revision id."""
    _backdate_v1(factory)
    _save_prompt(factory, "architect", "\n\nTune A.", lock=0)
    before = _artifacts(factory)
    real = publication_module.materialize_or_reuse_revision

    def _fresh_for_fixer(session, content, *, actor, timestamp):
        revision, created = real(session, content, actor=actor, timestamp=timestamp)
        if content.agent_key == "fixer":
            # Detached and never added: it cannot reach a flush, so only the
            # core's reuse guard can stop it.
            clone = AgentDefinitionRevision(
                **{
                    column.name: getattr(revision, column.name)
                    for column in AgentDefinitionRevision.__table__.columns
                    if column.name != "id"
                },
                id=987654,
            )
            return clone, True
        return revision, created

    monkeypatch.setattr(
        publication_module, "materialize_or_reuse_revision", _fresh_for_fixer
    )
    with pytest.raises(
        GraphConfigurationIntegrityError,
        match="^unchanged role 'fixer' did not reuse its revision$",
    ):
        _publish(factory, lock=1, gate=_NoEvidenceGate())
    assert _artifacts(factory) == before


def test_materialize_reuse_detects_a_hash_collision_with_different_content(factory):
    from src.services.graph_configuration_content import (
        database_transaction_timestamp,
        materialize_or_reuse_revision,
    )

    with factory() as db:
        architect = db.scalar(
            select(AgentDefinitionRevision).where(
                AgentDefinitionRevision.agent_key == "architect"
            )
        )
        content = definition_content_from_row(architect)
        timestamp = database_transaction_timestamp(db)
        revision, created = materialize_or_reuse_revision(
            db, content, actor="a@example.com", timestamp=timestamp
        )
        assert (revision.id, created) == (architect.id, False)
        db.execute(
            update(AgentDefinitionRevision)
            .where(AgentDefinitionRevision.id == architect.id)
            .values(prompt_text=architect.prompt_text + " tampered")
        )
        db.expire_all()
        with pytest.raises(
            GraphConfigurationIntegrityError,
            match=f"^reusable revision {architect.id} content hash does not match",
        ):
            materialize_or_reuse_revision(
                db, content, actor="a@example.com", timestamp=timestamp
            )
        db.rollback()


def test_an_active_release_that_is_not_the_latest_version_is_an_integrity_error(
    factory,
):
    """The version guard: the next number is ``max + 1`` only when active is max."""
    _backdate_v1(factory)
    _save_prompt(factory, "architect", "\n\nTune A.", lock=0)
    with factory.begin() as db:  # SQLite has no history guards; force the state
        db.execute(
            text(
                "INSERT INTO graph_release (version_number, release_note, published_by, "
                "published_at, effective_from, effective_to) VALUES (9, 'stray', "
                "'x@example.com', datetime('now','-3 hour'), datetime('now','-3 hour'), "
                "datetime('now','-2 hour'))"
            )
        )
    before = _artifacts(factory)

    with pytest.raises(
        GraphConfigurationIntegrityError,
        match="^active release is not the latest Graph Version$",
    ):
        _publish(factory, lock=1, gate=_NoEvidenceGate())

    assert _artifacts(factory) == before
