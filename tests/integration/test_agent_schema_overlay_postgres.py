"""PostgreSQL coverage for #264's schema-overlay writer and v2 contract upgrade.

Why PostgreSQL and not the SQLite unit suite: every assertion here is about
behaviour SQLite cannot express — real row-level locking, two backends with
distinct PIDs, one of them observably *waiting*, and a rollback that must leave
the immutable revision/release artifacts byte-identical.  The unit suite proves
the ordering logic; this file proves the ordering survives a real lock.

Concurrency assertions deliberately cover identities, content, hash, actor,
locks, backend PIDs, observed waiting and no-write behaviour — never counts.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import MappingProxyType

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.orm import sessionmaker

from src.database.models.graph_configuration import (
    AgentDefinitionRevision,
    GraphDraft,
    GraphDraftAgent,
    GraphRelease,
    GraphReleaseAgent,
)
from src.services.agent_schema_registry import AgentSchemaRegistry
from src.services.agent_schema_types import SchemaOverlay, thaw_json_containers
from src.services.graph_configuration import (
    DraftContentRejected,
    DraftSaveConflict,
    DraftSaveResult,
    EditableModelDraft,
    GraphConfiguration,
)
from src.services.graph_configuration_content import definition_content_from_row
from src.services.graph_definition_manifest import (
    GRAPH_V1_AGENT_KEYS,
    ContentIdentity,
    DefinitionContent,
    definition_content_hash,
)

pytestmark = pytest.mark.postgres

DIAGNOSTIC_NOTES = "diagnostic_notes"

#: Literals, not imports from the module under test — a test that imports the
#: constant it asserts is not a guard for that constant's value.
OVERLAY_INELIGIBLE_TUPLE = (
    (
        "candidate.schema_overlay.additional_optional_fields.0",
        "overlay_optional_field_ineligible",
        "Optional field is not available for this agent.",
    ),
)
SCHEMA_ALREADY_CURRENT_TUPLE = (
    (
        "schema_contract",
        "already_current",
        "Schema contract is already current.",
    ),
)


def _overlay(**payload: object) -> SchemaOverlay:
    return SchemaOverlay.model_validate(payload)


def _select_notes() -> SchemaOverlay:
    return _overlay(additional_optional_fields=[DIAGNOSTIC_NOTES])


def _editable(
    content: DefinitionContent, **updates: object
) -> EditableModelDraft:
    values: dict[str, object] = {
        "prompt_text": content.prompt_text,
        "endpoint_name": content.model.endpoint_name,
        "temperature": float(content.model.temperature),
        "max_tokens": content.model.max_tokens,
        "top_p": float(content.model.top_p),
    }
    values.update(updates)
    return EditableModelDraft(**values)


def _issue_tuples(caught) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (issue.field, issue.code, issue.message) for issue in caught.value.issues
    )


def _stored_draft(factory, agent_key: str) -> tuple[DefinitionContent, str]:
    with factory() as session:
        row = session.scalar(
            select(GraphDraftAgent).where(GraphDraftAgent.agent_key == agent_key)
        )
        assert row is not None
        return definition_content_from_row(row), row.candidate_hash


def _draft_meta(factory) -> tuple[int, str, object]:
    with factory() as session:
        row = session.get(GraphDraft, 1)
        assert row is not None
        return row.lock_version, row.updated_by, row.updated_at


def _immutable_graph_artifacts(factory) -> dict[str, list[tuple[object, ...]]]:
    """Every artifact a draft write must never touch."""
    with factory() as session:
        return {
            "revisions": list(
                session.execute(
                    select(
                        AgentDefinitionRevision.id,
                        AgentDefinitionRevision.agent_key,
                        AgentDefinitionRevision.content_hash,
                        AgentDefinitionRevision.schema_overlay,
                        AgentDefinitionRevision.schema_contract_version,
                        AgentDefinitionRevision.schema_contract_digest,
                    ).order_by(AgentDefinitionRevision.id)
                )
            ),
            "release_mappings": list(
                session.execute(
                    select(
                        GraphReleaseAgent.graph_release_id,
                        GraphReleaseAgent.agent_key,
                        GraphReleaseAgent.agent_definition_revision_id,
                    ).order_by(GraphReleaseAgent.agent_key)
                )
            ),
            "release_interval": list(
                session.execute(
                    select(
                        GraphRelease.id,
                        GraphRelease.effective_from,
                        GraphRelease.effective_to,
                    ).order_by(GraphRelease.id)
                )
            ),
        }


def _v2_schema_identity(agent_key: str) -> ContentIdentity:
    identity = AgentSchemaRegistry().identity_for(agent_key, 2)
    return ContentIdentity(version=identity.version, digest=identity.digest)


def _observe_lock_waiter(engine, pid: int, *, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with engine.connect() as observer:
            waiting = bool(
                observer.scalar(
                    text(
                        "SELECT EXISTS ("
                        " SELECT 1 FROM pg_stat_activity"
                        " WHERE pid = :pid AND wait_event_type = 'Lock'"
                        ")"
                    ),
                    {"pid": pid},
                )
            )
        if waiting:
            return True
        time.sleep(0.02)
    return False


# ---------------------------------------------------------------------------
# The upgrade, against a real database
# ---------------------------------------------------------------------------


def test_persisted_schema_upgrade_installs_v2_and_retains_v1_history(
    postgres_engine,
) -> None:
    """Catches a client-supplied identity or a draft write reaching published history."""
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    service = GraphConfiguration()
    service.bootstrap_v1(factory)
    artifacts_before = _immutable_graph_artifacts(factory)
    before, before_hash = _stored_draft(factory, "architect")
    assert before.schema_contract.version == 1

    with factory() as session:
        result = service.upgrade_draft_schema_contract(
            session,
            agent_key="architect",
            expected_lock_version=0,
            actor="pg:schema-upgrade",
        )

    after, after_hash = _stored_draft(factory, "architect")
    assert isinstance(result, DraftSaveResult)
    assert result.changed is True
    assert after.schema_contract == _v2_schema_identity("architect")
    assert after.schema_contract.version == 2
    assert after.prompt_text == before.prompt_text
    assert after.protected_assembly == before.protected_assembly
    assert after.schema_overlay == before.schema_overlay
    assert after_hash == definition_content_hash(after)
    assert after_hash != before_hash
    assert _draft_meta(factory)[:2] == (1, "pg:schema-upgrade")
    # Retained v1 history and release: the published revision keeps v1 material.
    assert _immutable_graph_artifacts(factory) == artifacts_before
    with factory() as session:
        published = session.scalar(
            select(AgentDefinitionRevision).where(
                AgentDefinitionRevision.agent_key == "architect"
            )
        )
        assert published is not None
        assert published.schema_contract_version == 1


def test_persisted_invalid_overlay_writes_nothing_at_all(postgres_engine) -> None:
    """A rejected overlay changes no candidate, hash, lock, audit, revision or release."""
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    service = GraphConfiguration()
    service.bootstrap_v1(factory)
    artifacts_before = _immutable_graph_artifacts(factory)
    before, before_hash = _stored_draft(factory, "architect")
    meta_before = _draft_meta(factory)

    with factory() as session, pytest.raises(DraftContentRejected) as caught:
        service.save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=0,
            candidate=_editable(
                before, prompt_text="rejected", schema_overlay=_select_notes()
            ),
            actor="pg:invalid-overlay",
        )

    assert _issue_tuples(caught) == OVERLAY_INELIGIBLE_TUPLE
    assert _stored_draft(factory, "architect") == (before, before_hash)
    assert _draft_meta(factory) == meta_before
    assert _immutable_graph_artifacts(factory) == artifacts_before


def test_persisted_optional_selection_round_trips_jsonb_only_after_the_upgrade(
    postgres_engine,
) -> None:
    """Proves the first non-empty overlay survives the real JSONB column."""
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    service = GraphConfiguration()
    service.bootstrap_v1(factory)
    before, _ = _stored_draft(factory, "architect")

    with factory() as session, pytest.raises(DraftContentRejected) as caught:
        service.save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=0,
            candidate=_editable(before, schema_overlay=_select_notes()),
            actor="pg:before-upgrade",
        )
    assert _issue_tuples(caught) == OVERLAY_INELIGIBLE_TUPLE

    with factory() as session:
        service.upgrade_draft_schema_contract(
            session,
            agent_key="architect",
            expected_lock_version=0,
            actor="pg:upgrade",
        )
    upgraded, _ = _stored_draft(factory, "architect")

    with factory() as session:
        result = service.save_editable_model_draft(
            session,
            agent_key="architect",
            expected_lock_version=1,
            candidate=_editable(
                upgraded,
                schema_overlay=_overlay(
                    field_overrides={
                        "intent": {
                            "description": "Persisted guidance.",
                            "examples": ["one", 2, None, {"nested": [1, 2]}],
                        }
                    },
                    additional_optional_fields=[DIAGNOSTIC_NOTES],
                ),
            ),
            actor="pg:after-upgrade",
        )

    persisted, persisted_hash = _stored_draft(factory, "architect")
    assert isinstance(result, DraftSaveResult)
    assert persisted.schema_overlay.additional_optional_fields == (DIAGNOSTIC_NOTES,)
    guidance = persisted.schema_overlay.field_overrides["intent"]
    assert guidance.description == "Persisted guidance."
    # Values come back deep-FROZEN: nested lists are tuples and nested objects are
    # mapping proxies.  That is Task 1's frozen-container contract, so the semantic
    # comparison thaws first and the frozen types are asserted separately rather
    # than papered over.
    # Passed as the tuple it actually is: ``thaw_json_containers`` recurses into
    # Mapping and tuple but NOT list, so wrapping it in ``list(...)`` first would
    # return the frozen children unchanged and the comparison would pass for the
    # wrong reason.
    assert thaw_json_containers(guidance.examples) == [
        "one",
        2,
        None,
        {"nested": [1, 2]},
    ]
    assert isinstance(guidance.examples[3], MappingProxyType)
    assert isinstance(guidance.examples[3]["nested"], tuple)
    assert persisted_hash == definition_content_hash(persisted)
    # The raw JSONB document, read without the content mapper.
    with factory() as session:
        raw = session.scalar(
            select(GraphDraftAgent.schema_overlay).where(
                GraphDraftAgent.agent_key == "architect"
            )
        )
    assert raw["additional_optional_fields"] == [DIAGNOSTIC_NOTES]
    assert raw["field_overrides"]["intent"]["description"] == "Persisted guidance."


def test_persisted_repeated_schema_upgrade_is_already_current_and_writes_nothing(
    postgres_engine,
) -> None:
    """Catches a second upgrade advancing the shared lock."""
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    service = GraphConfiguration()
    service.bootstrap_v1(factory)
    with factory() as session:
        service.upgrade_draft_schema_contract(
            session,
            agent_key="architect",
            expected_lock_version=0,
            actor="pg:first-upgrade",
        )
    upgraded, upgraded_hash = _stored_draft(factory, "architect")
    meta_before = _draft_meta(factory)
    artifacts_before = _immutable_graph_artifacts(factory)

    with factory() as session, pytest.raises(DraftContentRejected) as caught:
        service.upgrade_draft_schema_contract(
            session,
            agent_key="architect",
            expected_lock_version=1,
            actor="pg:repeat-upgrade",
        )

    assert _issue_tuples(caught) == SCHEMA_ALREADY_CURRENT_TUPLE
    assert _stored_draft(factory, "architect") == (upgraded, upgraded_hash)
    assert _draft_meta(factory) == meta_before
    assert _immutable_graph_artifacts(factory) == artifacts_before


# ---------------------------------------------------------------------------
# Forced two-session serialization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("agent_key", ["architect", "deck_reviewer"])
def test_two_sessions_serialize_two_schema_upgrades_and_reject_the_waiter(
    postgres_engine, agent_key, monkeypatch
) -> None:
    """Catches a double write, a masked stale lock, or an incoherent loser snapshot.

    The loser must observably WAIT on the winner's row lock — asserted from a
    third connection by backend PID, not inferred from timing.
    """
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    service = GraphConfiguration()
    service.bootstrap_v1(factory)
    bootstrap_content, bootstrap_hash = _stored_draft(factory, agent_key)
    artifacts_before = _immutable_graph_artifacts(factory)

    winner_locked = threading.Event()
    release_winner = threading.Event()
    loser_started = threading.Event()
    guard = threading.Lock()
    pids: dict[str, int] = {}
    outcomes: dict[str, object] = {}
    rejections: dict[str, DraftContentRejected] = {}
    writes: list[str] = []

    original_write = GraphConfiguration._write_locked_content

    def _recording_write(session, *, locked, content, actor):
        with guard:
            writes.append(actor)
        return original_write(session, locked=locked, content=content, actor=actor)

    monkeypatch.setattr(
        GraphConfiguration, "_write_locked_content", staticmethod(_recording_write)
    )

    class ObservedGraphConfiguration(GraphConfiguration):
        def _lock_current_parents(self, session, *, exclusive):
            pid = session.scalar(text("SELECT pg_backend_pid()"))
            with guard:
                pids[threading.current_thread().name] = pid
            if threading.current_thread().name == "schema-loser":
                loser_started.set()
            return super()._lock_current_parents(session, exclusive=exclusive)

    observed = ObservedGraphConfiguration()

    @event.listens_for(postgres_engine, "after_cursor_execute")
    def _pause_winner(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        normalized = " ".join(statement.upper().split())
        if (
            threading.current_thread().name == "schema-winner"
            and "FOR UPDATE" in normalized
            and "FROM GRAPH_DRAFT_AGENT" in normalized
        ):
            winner_locked.set()
            assert release_winner.wait(timeout=20), "test never released the winner"

    def _run(name: str) -> None:
        threading.current_thread().name = name
        with factory() as session:
            try:
                outcomes[name] = observed.upgrade_draft_schema_contract(
                    session,
                    agent_key=agent_key,
                    expected_lock_version=0,
                    actor=name,
                )
            except DraftContentRejected as exc:
                rejections[name] = exc

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            winner = pool.submit(_run, "schema-winner")
            assert winner_locked.wait(timeout=10), "winner never held the selected-row lock"
            loser = pool.submit(_run, "schema-loser")
            assert loser_started.wait(timeout=10), "loser never attempted the parent lock"
            with guard:
                loser_pid = pids.get("schema-loser")
            assert loser_pid is not None
            observed_waiter = _observe_lock_waiter(postgres_engine, loser_pid)
            with guard:
                winner_pid = pids.get("schema-winner")
            assert winner_pid is not None
            assert winner_pid != loser_pid
            assert observed_waiter is True
            release_winner.set()
            winner.result(timeout=20)
            loser.result(timeout=20)
    finally:
        release_winner.set()
        event.remove(postgres_engine, "after_cursor_execute", _pause_winner)

    assert rejections == {}
    winner_outcome = outcomes["schema-winner"]
    loser_outcome = outcomes["schema-loser"]

    # Exactly one write, by the winner.
    assert writes == ["schema-winner"]
    assert isinstance(winner_outcome, DraftSaveResult)
    assert winner_outcome.changed is True
    assert winner_outcome.draft.lock_version == 1
    assert winner_outcome.draft.updated_by == "schema-winner"

    persisted, persisted_hash = _stored_draft(factory, agent_key)
    assert persisted.schema_contract == _v2_schema_identity(agent_key)
    assert persisted.prompt_text == bootstrap_content.prompt_text
    assert persisted_hash == definition_content_hash(persisted)
    assert persisted_hash != bootstrap_hash
    assert _draft_meta(factory)[:2] == (1, "schema-winner")

    # The loser gets a coherent exact-seven snapshot showing the winner's effect.
    assert isinstance(loser_outcome, DraftSaveConflict)
    assert loser_outcome.expected_lock_version == 0
    assert loser_outcome.current_lock_version == 1
    assert loser_outcome.client_candidate is None
    assert set(loser_outcome.server.definitions) == set(GRAPH_V1_AGENT_KEYS)
    assert len(loser_outcome.server.definitions) == 7
    selected = loser_outcome.server.definitions[agent_key].content
    assert selected.schema_contract == _v2_schema_identity(agent_key)
    assert loser_outcome.server.definitions[agent_key].candidate_hash == persisted_hash
    assert loser_outcome.server.draft.lock_version == 1
    assert loser_outcome.server.draft.updated_by == "schema-winner"
    # Every other role is still v1 — the upgrade is per-role.
    for other_key, node in loser_outcome.server.definitions.items():
        if other_key != agent_key:
            assert node.content.schema_contract.version == 1

    assert _immutable_graph_artifacts(factory) == artifacts_before


@pytest.mark.parametrize(
    ("loser_overlay_payload", "expected"),
    [
        # Invalid under BOTH contracts, so validation must win whichever identity
        # the loser reads once the winner's upgrade commits.
        (
            {"field_overrides": {"no_such_field": {"description": "x"}}},
            (
                (
                    "candidate.schema_overlay.field_overrides.no_such_field",
                    "overlay_unknown_canonical_field",
                    "Canonical field is not available for this agent.",
                ),
            ),
        ),
        (
            {"field_overrides": {"intent": {"description": "   "}}},
            (
                (
                    "candidate.schema_overlay.field_overrides.intent.description",
                    "overlay_description_blank",
                    "Description must not be blank.",
                ),
            ),
        ),
    ],
)
def test_two_sessions_serialize_an_invalid_overlay_save_against_an_upgrade(
    postgres_engine, monkeypatch, loser_overlay_payload, expected
) -> None:
    """The rejected writer must leave the winner's committed upgrade untouched.

    The loser here fails validation rather than staleness, which is the ordering
    #264 mandates: it never reaches the stale comparison, so it produces neither a
    conflict nor a write while still observing the winner's lock.

    The loser's overlay is chosen to be invalid under v1 *and* v2 on purpose.  A
    payload that is invalid only under v1 would become valid the moment the
    winner's upgrade commits, because the candidate is rebuilt from the content
    the loser reads under the lock — see the sibling test for that property.
    """
    agent_key = "architect"
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    service = GraphConfiguration()
    service.bootstrap_v1(factory)
    bootstrap_content, _ = _stored_draft(factory, agent_key)
    artifacts_before = _immutable_graph_artifacts(factory)

    winner_locked = threading.Event()
    release_winner = threading.Event()
    loser_started = threading.Event()
    guard = threading.Lock()
    pids: dict[str, int] = {}
    outcomes: dict[str, object] = {}
    rejections: dict[str, tuple[tuple[str, str, str], ...]] = {}
    writes: list[str] = []

    original_write = GraphConfiguration._write_locked_content

    def _recording_write(session, *, locked, content, actor):
        with guard:
            writes.append(actor)
        return original_write(session, locked=locked, content=content, actor=actor)

    monkeypatch.setattr(
        GraphConfiguration, "_write_locked_content", staticmethod(_recording_write)
    )

    class ObservedGraphConfiguration(GraphConfiguration):
        def _lock_current_parents(self, session, *, exclusive):
            pid = session.scalar(text("SELECT pg_backend_pid()"))
            with guard:
                pids[threading.current_thread().name] = pid
            if threading.current_thread().name == "overlay-loser":
                loser_started.set()
            return super()._lock_current_parents(session, exclusive=exclusive)

    observed = ObservedGraphConfiguration()

    @event.listens_for(postgres_engine, "after_cursor_execute")
    def _pause_winner(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        normalized = " ".join(statement.upper().split())
        if (
            threading.current_thread().name == "upgrade-winner"
            and "FOR UPDATE" in normalized
            and "FROM GRAPH_DRAFT_AGENT" in normalized
        ):
            winner_locked.set()
            assert release_winner.wait(timeout=20), "test never released the winner"

    def _run_winner() -> None:
        threading.current_thread().name = "upgrade-winner"
        with factory() as session:
            outcomes["upgrade-winner"] = observed.upgrade_draft_schema_contract(
                session,
                agent_key=agent_key,
                expected_lock_version=0,
                actor="upgrade-winner",
            )

    def _run_loser() -> None:
        threading.current_thread().name = "overlay-loser"
        with factory() as session:
            try:
                # Invalid under either contract, AND stale.  Validation must win.
                outcomes["overlay-loser"] = observed.save_editable_model_draft(
                    session,
                    agent_key=agent_key,
                    expected_lock_version=0,
                    candidate=_editable(
                        bootstrap_content,
                        schema_overlay=_overlay(**loser_overlay_payload),
                    ),
                    actor="overlay-loser",
                )
            except DraftContentRejected as exc:
                rejections["overlay-loser"] = tuple(
                    (issue.field, issue.code, issue.message) for issue in exc.issues
                )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            winner = pool.submit(_run_winner)
            assert winner_locked.wait(timeout=10), "winner never held the selected-row lock"
            loser = pool.submit(_run_loser)
            assert loser_started.wait(timeout=10), "loser never attempted the parent lock"
            with guard:
                loser_pid = pids.get("overlay-loser")
            assert loser_pid is not None
            observed_waiter = _observe_lock_waiter(postgres_engine, loser_pid)
            with guard:
                winner_pid = pids.get("upgrade-winner")
            assert winner_pid is not None
            assert winner_pid != loser_pid
            assert observed_waiter is True
            release_winner.set()
            winner.result(timeout=20)
            loser.result(timeout=20)
    finally:
        release_winner.set()
        event.remove(postgres_engine, "after_cursor_execute", _pause_winner)

    # The winner committed its upgrade; the loser rejected and wrote nothing.
    assert writes == ["upgrade-winner"]
    assert isinstance(outcomes["upgrade-winner"], DraftSaveResult)
    assert "overlay-loser" not in outcomes
    assert rejections["overlay-loser"] == expected

    persisted, persisted_hash = _stored_draft(factory, agent_key)
    assert persisted.schema_contract == _v2_schema_identity(agent_key)
    assert persisted.schema_overlay == bootstrap_content.schema_overlay
    assert persisted.prompt_text == bootstrap_content.prompt_text
    assert persisted_hash == definition_content_hash(persisted)
    assert _draft_meta(factory)[:2] == (1, "upgrade-winner")
    assert _immutable_graph_artifacts(factory) == artifacts_before


def test_a_client_overlay_is_validated_against_the_contract_read_under_the_lock(
    postgres_engine, monkeypatch
) -> None:
    """A client can never pin the contract version its overlay is judged against.

    ``save_editable_model_draft`` rebuilds the candidate from the content it reads
    *inside* the lock, so the identity used for overlay validation is always the
    server's committed one.  Demonstrated here at its sharpest: a loser selects
    ``diagnostic_notes`` while the stored contract is still v1 — ineligible at
    request time — and blocks on a concurrent upgrade.  Once that upgrade commits,
    the loser re-reads a v2 contract, the selection becomes eligible, and the
    request reports STALE rather than invalid.

    This is the property that makes the identity server-owned rather than
    client-asserted.  A regression that validated against a client-supplied
    identity would reject here instead, and would also let a client claim v2
    eligibility against a v1 draft.
    """
    agent_key = "architect"
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    service = GraphConfiguration()
    service.bootstrap_v1(factory)
    bootstrap_content, _ = _stored_draft(factory, agent_key)
    assert bootstrap_content.schema_contract.version == 1
    artifacts_before = _immutable_graph_artifacts(factory)

    winner_locked = threading.Event()
    release_winner = threading.Event()
    loser_started = threading.Event()
    guard = threading.Lock()
    pids: dict[str, int] = {}
    outcomes: dict[str, object] = {}
    rejections: dict[str, object] = {}
    writes: list[str] = []

    original_write = GraphConfiguration._write_locked_content

    def _recording_write(session, *, locked, content, actor):
        with guard:
            writes.append(actor)
        return original_write(session, locked=locked, content=content, actor=actor)

    monkeypatch.setattr(
        GraphConfiguration, "_write_locked_content", staticmethod(_recording_write)
    )

    class ObservedGraphConfiguration(GraphConfiguration):
        def _lock_current_parents(self, session, *, exclusive):
            pid = session.scalar(text("SELECT pg_backend_pid()"))
            with guard:
                pids[threading.current_thread().name] = pid
            if threading.current_thread().name == "select-loser":
                loser_started.set()
            return super()._lock_current_parents(session, exclusive=exclusive)

    observed = ObservedGraphConfiguration()

    @event.listens_for(postgres_engine, "after_cursor_execute")
    def _pause_winner(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        normalized = " ".join(statement.upper().split())
        if (
            threading.current_thread().name == "upgrade-winner"
            and "FOR UPDATE" in normalized
            and "FROM GRAPH_DRAFT_AGENT" in normalized
        ):
            winner_locked.set()
            assert release_winner.wait(timeout=20), "test never released the winner"

    def _run_winner() -> None:
        threading.current_thread().name = "upgrade-winner"
        with factory() as session:
            outcomes["upgrade-winner"] = observed.upgrade_draft_schema_contract(
                session,
                agent_key=agent_key,
                expected_lock_version=0,
                actor="upgrade-winner",
            )

    def _run_loser() -> None:
        threading.current_thread().name = "select-loser"
        with factory() as session:
            try:
                outcomes["select-loser"] = observed.save_editable_model_draft(
                    session,
                    agent_key=agent_key,
                    expected_lock_version=0,
                    candidate=_editable(
                        bootstrap_content, schema_overlay=_select_notes()
                    ),
                    actor="select-loser",
                )
            except DraftContentRejected as exc:
                rejections["select-loser"] = tuple(
                    (issue.field, issue.code, issue.message) for issue in exc.issues
                )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            winner = pool.submit(_run_winner)
            assert winner_locked.wait(timeout=10), "winner never held the selected-row lock"
            loser = pool.submit(_run_loser)
            assert loser_started.wait(timeout=10), "loser never attempted the parent lock"
            with guard:
                loser_pid = pids.get("select-loser")
            assert loser_pid is not None
            observed_waiter = _observe_lock_waiter(postgres_engine, loser_pid)
            with guard:
                winner_pid = pids.get("upgrade-winner")
            assert winner_pid is not None
            assert winner_pid != loser_pid
            assert observed_waiter is True
            release_winner.set()
            winner.result(timeout=20)
            loser.result(timeout=20)
    finally:
        release_winner.set()
        event.remove(postgres_engine, "after_cursor_execute", _pause_winner)

    # The selection was NOT rejected: it was judged against the v2 contract the
    # loser read under the lock, then reported stale.
    assert rejections == {}
    loser_outcome = outcomes["select-loser"]
    assert isinstance(loser_outcome, DraftSaveConflict)
    assert loser_outcome.expected_lock_version == 0
    assert loser_outcome.current_lock_version == 1
    assert loser_outcome.server.definitions[agent_key].content.schema_contract == (
        _v2_schema_identity(agent_key)
    )
    # And it is a no-write: only the winner's upgrade landed.
    assert writes == ["upgrade-winner"]
    persisted, persisted_hash = _stored_draft(factory, agent_key)
    assert persisted.schema_contract == _v2_schema_identity(agent_key)
    assert persisted.schema_overlay == bootstrap_content.schema_overlay
    assert persisted.schema_overlay.additional_optional_fields == ()
    assert persisted_hash == definition_content_hash(persisted)
    assert _draft_meta(factory)[:2] == (1, "upgrade-winner")
    assert _immutable_graph_artifacts(factory) == artifacts_before
