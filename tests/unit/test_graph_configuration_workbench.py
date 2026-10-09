"""#266 Task 5: the facade's read-only saved-candidate snapshot for the probe.

Correction 14: this file did not exist before Task 5.  It owns the facade-level
contract of ``GraphConfiguration.read_draft_probe_candidate``: the selected
role's exact saved model configuration, hash and lock, copied and released
before any caller does network work, with the coherent seven-role conflict for a
stale lock and no write of any kind.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event, select, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register the complete ORM metadata
from src.core.database import Base
from src.database.models.graph_configuration import GraphDraftAgent
from src.services.graph_configuration import (
    DraftContentRejected,
    DraftProbeCandidate,
    DraftSaveConflict,
    DraftSaveResult,
    EditableModelDraft,
    GraphConfiguration,
)
from src.services.graph_configuration_content import definition_content_values
from src.services.graph_definition_manifest import (
    GRAPH_V1_AGENT_KEYS,
    ModelConfiguration,
    definition_content_hash,
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


def _all_rows(factory) -> dict[str, list[tuple[object, ...]]]:
    with factory() as session:
        return {
            table.name: [tuple(row) for row in session.execute(select(table))]
            for table in Base.metadata.sorted_tables
        }


def _draft_node(factory, agent_key: str):
    with factory() as session:
        return next(
            node
            for node in GraphConfiguration().read_workbench(session).nodes
            if node.agent_key == agent_key
        )


def _save(factory, agent_key: str, endpoint_name: str, lock_version: int) -> DraftSaveResult:
    current = _draft_node(factory, agent_key).draft.content
    with factory() as session:
        outcome = GraphConfiguration().save_editable_model_draft(
            session,
            agent_key=agent_key,
            expected_lock_version=lock_version,
            candidate=EditableModelDraft(
                prompt_text=current.prompt_text,
                endpoint_name=endpoint_name,
                temperature=0.375,
                max_tokens=2048,
                top_p=0.625,
            ),
            actor="seed-admin@example.com",
        )
    assert isinstance(outcome, DraftSaveResult)
    return outcome


def _read(factory, agent_key: str, lock_version: int):
    with factory() as session:
        return GraphConfiguration().read_draft_probe_candidate(
            session, agent_key=agent_key, expected_lock_version=lock_version
        )


def test_model_endpoint_probe_snapshot_is_the_selected_roles_exact_saved_candidate(
    session_factory,
):
    """Catches a snapshot of another role, the published revision, or a default."""
    _save(session_factory, "architect", "system.ai.architect-exact-endpoint", 0)
    _save(session_factory, "fixer", "system.ai.fixer-exact-endpoint", 1)

    for agent_key, endpoint_name in (
        ("architect", "system.ai.architect-exact-endpoint"),
        ("fixer", "system.ai.fixer-exact-endpoint"),
    ):
        node = _draft_node(session_factory, agent_key)
        snapshot = _read(session_factory, agent_key, 2)
        assert snapshot == DraftProbeCandidate(
            agent_key=agent_key,
            lock_version=2,
            candidate_hash=node.draft.candidate_hash,
            model=ModelConfiguration(
                endpoint_name=endpoint_name,
                temperature=0.375,
                max_tokens=2048,
                top_p=0.625,
            ),
        )
        assert snapshot.candidate_hash != node.published.content_hash


def test_model_endpoint_probe_snapshot_stale_lock_is_the_null_candidate_conflict(
    session_factory,
):
    """Catches a stale probe read returning a snapshot instead of the 409 outcome."""
    _save(session_factory, "builder", "system.ai.builder-moved", 0)

    outcome = _read(session_factory, "builder", 0)

    assert isinstance(outcome, DraftSaveConflict)
    assert outcome.client_candidate is None
    assert (outcome.expected_lock_version, outcome.current_lock_version) == (0, 1)
    assert set(outcome.server.definitions) == set(GRAPH_V1_AGENT_KEYS)
    assert (
        outcome.server.definitions["builder"].content.model.endpoint_name
        == "system.ai.builder-moved"
    )


def test_model_endpoint_probe_snapshot_writes_nothing(session_factory):
    """Catches a read that advances the lock, stamps an actor, or rewrites a row."""
    before = _all_rows(session_factory)

    _read(session_factory, "architect", 0)
    _read(session_factory, "architect", 5)

    assert _all_rows(session_factory) == before


def test_model_endpoint_probe_snapshot_releases_its_transaction(session_factory):
    """Catches the snapshot's share locks outliving the read (correction 13)."""
    with session_factory() as session:
        GraphConfiguration().read_draft_probe_candidate(
            session, agent_key="architect", expected_lock_version=0
        )
        assert session.in_transaction() is False


def _store_endpoint_directly(factory, agent_key: str, endpoint_name: str) -> None:
    """Seed a pre-policy saved name coherently: content columns and hash agree."""
    content = _draft_node(factory, agent_key).draft.content.model_copy(
        update={
            "model": ModelConfiguration(
                endpoint_name=endpoint_name,
                temperature=0.5,
                max_tokens=10,
                top_p=0.5,
            )
        }
    )
    with factory.begin() as session:
        session.execute(
            update(GraphDraftAgent)
            .where(GraphDraftAgent.agent_key == agent_key)
            .values(
                **definition_content_values(content),
                candidate_hash=definition_content_hash(content),
            )
        )


@pytest.mark.parametrize(
    "stored",
    ["https://host.example/serving-endpoints/x", "../../2.0/secrets", "a?b", ".."],
)
def test_model_endpoint_probe_snapshot_rechecks_the_saved_name_policy(
    session_factory, stored
):
    """Catches a URL- or path-shaped stored name reaching the probe (correction 4)."""
    _store_endpoint_directly(session_factory, "architect", stored)

    with pytest.raises(DraftContentRejected) as caught:
        _read(session_factory, "architect", 0)

    assert [(i.field, i.code) for i in caught.value.issues] == [
        ("candidate.model.endpoint_name", "endpoint_url_not_allowed")
    ]
    assert stored not in caught.value.issues[0].message


def test_model_endpoint_probe_snapshot_stale_precedes_the_policy_recheck(session_factory):
    """Catches the policy re-check pre-empting the coherent stale conflict."""
    _save(session_factory, "architect", "system.ai.fine", 0)
    _store_endpoint_directly(session_factory, "architect", "https://h.example/x")

    outcome = _read(session_factory, "architect", 0)

    assert isinstance(outcome, DraftSaveConflict)


@pytest.mark.parametrize(
    ("agent_key", "lock_version", "expected"),
    [
        ("foreman", 0, [("agent_key", "unknown_agent")]),
        ("unknown", 0, [("agent_key", "unknown_agent")]),
        ("architect", -1, [("lock_version", "out_of_range")]),
        ("architect", True, [("lock_version", "strict_type")]),
        ("architect", "0", [("lock_version", "strict_type")]),
    ],
)
def test_model_endpoint_probe_snapshot_rejects_invalid_requests_before_reading(
    session_factory, agent_key, lock_version, expected
):
    """Catches a non-editable role or malformed lock reaching the aggregate read."""
    with pytest.raises(DraftContentRejected) as caught:
        _read(session_factory, agent_key, lock_version)

    assert [(i.field, i.code) for i in caught.value.issues] == expected
