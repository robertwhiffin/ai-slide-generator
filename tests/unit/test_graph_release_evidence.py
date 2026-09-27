"""#269 Task 4: the approval evidence gate, evidence links and the linked-verdict
refusal, on SQLite.

SQLite renders no ``FOR SHARE`` / ``FOR UPDATE`` and has no mutation-guard
triggers, so this file proves the gate's *selection*: which runs satisfy a
changed role's required cases, which cases are gaps and in what order, and that
the gate reuses #268's one eligibility predicate term for term (Correction 45).
The PostgreSQL twin (``tests/integration/test_graph_release_evidence_postgres.py``)
proves the locks, the races and the trigger.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, event, func, select, text, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register the complete ORM metadata
from src.api.routes import agent_definitions as routes
from src.api.schemas.agent_definitions import IneligibleForApprovalResponse
from src.core.database import Base
from src.database.models.graph_configuration import (
    AgentTestCase,
    AgentTestRun,
    GraphDraftAgent,
    GraphRelease,
    GraphReleaseAgent,
    GraphReleaseTestRun,
)
from src.services.agent_runtime import AgentRuntime
from src.services.agent_runtime_identity import RecordingAgentInvocationIdentitySink
from src.services.agent_test_workbench import (
    AgentTestWorkbench,
    DraftReadinessResult,
    IneligibleForApprovalError,
)
from src.services.graph_configuration import (
    DraftSaveResult,
    EditableModelDraft,
    EvidenceLink,
    GraphConfiguration,
    GraphConfigurationIntegrityError,
    PublicationGap,
    PublicationNotReady,
    PublishedRelease,
)
from src.services.graph_release_evidence import (
    ApprovalEvidenceGate,
    link_release_evidence,
)
from src.services.persisted_graph_release import PersistedGraphReleaseLoader
from tests.fixtures.deterministic_model_adapter import DeterministicFakeModelAdapter

REVIEWER = "reviewer@example.com"
RUNNER = "runner@example.com"
_T0 = datetime(2030, 1, 1, 0, 0, 0)
_APPROVED = {
    "verdict": "approved",
    "verdict_reviewer": REVIEWER,
    "verdict_at": datetime(2030, 1, 1),
    "verdict_notes": None,
}
_UNREVIEWED = {
    "verdict": None,
    "verdict_reviewer": None,
    "verdict_at": None,
    "verdict_notes": None,
}


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
    # SQLite's CURRENT_TIMESTAMP has one-second resolution; publication needs a
    # strictly later timestamp than v1 (Correction 4's backdating).
    with session_factory.begin() as db:
        db.execute(
            text(
                "UPDATE graph_release SET effective_from = datetime('now','-1 hour'), "
                "published_at = datetime('now','-1 hour') WHERE version_number = 1"
            )
        )
    try:
        yield session_factory
    finally:
        engine.dispose()


# --- helpers ------------------------------------------------------------------


def _at(seconds: int) -> datetime:
    return _T0 + timedelta(seconds=seconds)


def _save(factory, agent_key: str, prompt_text: str) -> DraftSaveResult:
    service = GraphConfiguration()
    with factory() as db:
        snap = service.read_workbench(db)
        db.rollback()
    content = next(n for n in snap.nodes if n.agent_key == agent_key).draft.content
    with factory() as db:
        out = service.save_editable_model_draft(
            db,
            agent_key=agent_key,
            expected_lock_version=snap.draft.lock_version,
            actor="editor@example.com",
            candidate=EditableModelDraft(
                prompt_text=prompt_text,
                endpoint_name=content.model.endpoint_name,
                temperature=float(content.model.temperature),
                max_tokens=content.model.max_tokens,
                top_p=float(content.model.top_p),
            ),
        )
    assert isinstance(out, DraftSaveResult)
    return out


def _seed_case_id(factory, agent_key: str = "architect") -> int:
    with factory() as db:
        return db.scalar(
            select(AgentTestCase.id).where(
                AgentTestCase.agent_key == agent_key,
                AgentTestCase.name == f"{agent_key}_required_smoke_v1",
            )
        )


def _workbench(factory) -> AgentTestWorkbench:
    runtime = AgentRuntime(
        persisted_release_loader=PersistedGraphReleaseLoader(session_factory=factory),
        model_adapter=DeterministicFakeModelAdapter(),
        identity_sink=RecordingAgentInvocationIdentitySink(),
    )
    return AgentTestWorkbench(runtime=runtime)


def _real_run(factory, agent_key: str = "architect", test_case_id: int | None = None) -> int:
    """One completed, passing, unreviewed candidate run through #267's executor."""
    with factory() as db:
        lock = db.scalar(text("SELECT lock_version FROM graph_draft"))
    with factory() as db:
        evidence = _workbench(factory).execute_candidate_run(
            db,
            agent_key=agent_key,
            test_case_id=test_case_id or _seed_case_id(factory, agent_key),
            expected_lock_version=lock,
            actor=RUNNER,
        )
    assert evidence.execution_status == "completed"
    assert evidence.deterministic_checks_passed is True
    return evidence.run_id


def _approve(factory, run_id: int, verdict: str = "approved"):
    with factory() as db:
        return AgentTestWorkbench().record_verdict(
            db, run_id=run_id, verdict=verdict, reviewer=REVIEWER, notes=None
        )


def _row(factory, run_id: int) -> dict[str, object]:
    with factory() as db:
        row = db.get(AgentTestRun, run_id)
        return {c.key: getattr(row, c.key) for c in AgentTestRun.__table__.columns}


def _insert_run_like(factory, source_run_id: int, *, ignore_checks=False, **overrides) -> int:
    """An INSERT-only copy of a real run (never an UPDATE of a run)."""
    values = _row(factory, source_run_id)
    del values["id"]
    values.update(overrides)
    with factory() as db:
        if ignore_checks:
            # Builds a row the DDL would refuse, to prove the predicate term on
            # its own (the approved-only-if-completed-and-passing CHECK).
            db.execute(text("PRAGMA ignore_check_constraints = ON"))
        row = AgentTestRun(**values)
        db.add(row)
        db.commit()
        if ignore_checks:
            db.execute(text("PRAGMA ignore_check_constraints = OFF"))
            db.commit()
        return row.id


def _readiness_spy():
    calls: list[object] = []
    workbench = AgentTestWorkbench()

    def _readiness(session):
        result = workbench.readiness_under_parent_lock(session)
        calls.append(result)
        return result

    return _readiness, calls


def _publish(factory, gate=None):
    gate = gate or ApprovalEvidenceGate(
        readiness=AgentTestWorkbench().readiness_under_parent_lock
    )
    with factory() as db:
        lock = db.scalar(text("SELECT lock_version FROM graph_draft"))
    with factory() as db:
        return GraphConfiguration().publish_draft(
            db,
            expected_lock_version=lock,
            release_note="Tune roles",
            actor="publisher@example.com",
            evidence_gate=gate,
        )


def _links(factory) -> list[tuple[object, ...]]:
    with factory() as db:
        return [
            tuple(row)
            for row in db.execute(
                select(
                    GraphReleaseTestRun.graph_release_id,
                    GraphReleaseTestRun.agent_test_run_id,
                    GraphReleaseTestRun.evidence_kind,
                    GraphReleaseTestRun.source_release_id,
                ).order_by(GraphReleaseTestRun.agent_test_run_id)
            )
        ]


def _release_count(factory) -> int:
    with factory() as db:
        return db.scalar(select(func.count()).select_from(GraphRelease))


def _changed_architect(factory) -> int:
    """Architect changed by a real save; one real run of the new hash, unreviewed."""
    _save(factory, "architect", "A changed architect prompt for publication.")
    return _real_run(factory)


def _case_status(result: DraftReadinessResult, test_case_id: int) -> str:
    for agent in result.agents:
        for case in agent.cases:
            if case.test_case_id == test_case_id:
                return case.status
    raise AssertionError(f"case {test_case_id} is not in readiness")


# --- selection: the newest eligible approval per required case ---------------


def test_publication_links_the_newest_eligible_approval_of_each_changed_role(factory):
    source = _changed_architect(factory)
    older = _insert_run_like(factory, source, run_at=_at(1), **_APPROVED)
    newer = _insert_run_like(factory, source, run_at=_at(2), **_APPROVED)
    case_id = _seed_case_id(factory)

    result = _publish(factory)

    assert isinstance(result, PublishedRelease)
    assert result.evidence == (EvidenceLink(newer, "architect", case_id, "approval", None),)
    assert _links(factory) == [(result.release.release_id, newer, "approval", None)]
    assert older != newer


def test_newest_is_run_at_first_then_the_higher_id(factory):
    source = _changed_architect(factory)
    # Inserted newest-first, so id order disagrees with run_at order.
    by_run_at = _insert_run_like(factory, source, run_at=_at(9), **_APPROVED)
    _insert_run_like(factory, source, run_at=_at(5), **_APPROVED)
    highest_id = _insert_run_like(factory, source, run_at=_at(3), **_APPROVED)

    result = _publish(factory)

    assert isinstance(result, PublishedRelease)
    assert highest_id > by_run_at
    assert [link.agent_test_run_id for link in result.evidence] == [by_run_at]


def test_a_tied_run_at_links_the_higher_id(factory):
    source = _changed_architect(factory)
    _insert_run_like(factory, source, run_at=_at(3), **_APPROVED)
    higher = _insert_run_like(factory, source, run_at=_at(3), **_APPROVED)

    result = _publish(factory)

    assert [link.agent_test_run_id for link in result.evidence] == [higher]


def test_every_changed_role_is_linked_in_role_order_and_unchanged_roles_never(factory):
    _save(factory, "builder", "A changed builder prompt for publication.")
    _save(factory, "architect", "A changed architect prompt for publication.")
    architect_run = _real_run(factory, "architect")
    builder_run = _real_run(factory, "builder")
    _approve(factory, builder_run)
    _approve(factory, architect_run)
    # An approved run of an UNCHANGED role is never linked.
    unchanged = _real_run(factory, "data_analyst")
    _approve(factory, unchanged)

    result = _publish(factory)

    assert isinstance(result, PublishedRelease)
    assert result.changed_agent_keys == ("architect", "builder")
    assert result.evidence == (
        EvidenceLink(architect_run, "architect", _seed_case_id(factory), "approval", None),
        EvidenceLink(builder_run, "builder", _seed_case_id(factory, "builder"), "approval", None),
    )
    assert {row[1] for row in _links(factory)} == {architect_run, builder_run}


# --- Correction 45: the shared eligibility clause, term for term -------------


def _other_role_revision(factory) -> dict[str, object]:
    with factory() as db:
        release_id = db.scalar(select(GraphRelease.id).where(GraphRelease.effective_to.is_(None)))
        revision_id = db.scalar(
            select(GraphReleaseAgent.agent_definition_revision_id).where(
                GraphReleaseAgent.graph_release_id == release_id,
                GraphReleaseAgent.agent_key == "builder",
            )
        )
    return {"agent_key": "builder", "compared_definition_revision_id": revision_id}


def _other_role_hash(factory) -> dict[str, object]:
    with factory() as db:
        builder_hash = db.scalar(
            select(GraphDraftAgent.candidate_hash).where(GraphDraftAgent.agent_key == "builder")
        )
    return {"candidate_hash": builder_hash}


def _optional_case_id(factory) -> dict[str, object]:
    with factory() as db:
        case = AgentTestCase(
            agent_key="architect",
            name="architect_parity_other_case",
            version=1,
            is_active=True,
            is_required=False,
            synthetic_payload={"message": "other"},
            assembly_context={"design_system_active": False},
            created_by="admin@example.com",
            updated_by="admin@example.com",
        )
        db.add(case)
        db.commit()
        return {"test_case_id": case.id}


_PARITY_TERMS = [
    pytest.param("eligible", {}, id="eligible-control"),
    pytest.param("run_kind", {"run_kind": "published_baseline"}, id="run_kind"),
    pytest.param("test_case_id", _optional_case_id, id="test_case_id"),
    pytest.param("test_case_version", {"test_case_version": 99}, id="test_case_version"),
    pytest.param("run.agent_key", _other_role_revision, id="run-agent_key"),
    pytest.param("draft_agent.agent_key", _other_role_hash, id="draft_agent-agent_key"),
    pytest.param("candidate_hash", {"candidate_hash": "f" * 64}, id="candidate_hash"),
    pytest.param("verdict", {"verdict": "rejected"}, id="verdict-rejected"),
    pytest.param("verdict", {"verdict": None, "verdict_reviewer": None, "verdict_at": None},
                 id="verdict-unreviewed"),
    pytest.param(
        "execution_status",
        {"execution_status": "incomplete"},
        id="execution_status",
    ),
    pytest.param(
        "deterministic_checks_passed",
        {"deterministic_checks_passed": False},
        id="deterministic_checks_passed",
    ),
]


@pytest.mark.parametrize(("term", "mismatch"), _PARITY_TERMS)
def test_gate_and_readiness_agree_on_every_eligibility_term(factory, term, mismatch):
    """C45: one approved run that differs from an eligible one in exactly one
    term of ``eligible_approval_clause`` is refused by BOTH #268's readiness and
    the gate; the control row is accepted by both.  (The draft-agent join term
    is exercised by a run carrying another role's current draft hash.)"""
    _save(factory, "architect", "A changed architect prompt for parity.")
    source = _real_run(factory)  # unreviewed: never evidence itself
    overrides = mismatch(factory) if callable(mismatch) else mismatch
    ignore = term in ("execution_status", "deterministic_checks_passed")
    probe = _insert_run_like(
        factory, source, run_at=_at(1), ignore_checks=ignore, **{**_APPROVED, **overrides}
    )
    case_id = _seed_case_id(factory)
    readiness, calls = _readiness_spy()

    with factory() as db:
        with db.begin():
            GraphConfiguration()._lock_current_parents(db, exclusive=False)
            status = _case_status(AgentTestWorkbench().readiness_under_parent_lock(db), case_id)

    result = _publish(factory, ApprovalEvidenceGate(readiness=readiness))

    if term == "eligible":
        assert status == "approved"
        assert isinstance(result, PublishedRelease)
        assert [link.agent_test_run_id for link in result.evidence] == [probe]
        assert calls == []
    else:
        assert status != "approved", term
        assert isinstance(result, PublicationNotReady), term
        assert result.locked_gaps == (
            PublicationGap("architect", case_id, "no_eligible_approval"),
        )
        assert _links(factory) == []
        assert _release_count(factory) == 1


# --- which cases count: required, active, of a changed role -----------------


def test_optional_and_inactive_cases_never_block_and_are_never_linked(factory):
    source = _changed_architect(factory)
    _approve(factory, source)
    workbench = AgentTestWorkbench()
    with factory() as db:
        optional_unrun = workbench.create_test_case(
            db,
            agent_key="architect",
            name="architect_optional_unrun",
            synthetic_payload={"message": "never run"},
            assembly_context={"design_system_active": False},
            is_required=False,
            actor="admin@example.com",
        )
    with factory() as db:
        optional_run = workbench.create_test_case(
            db,
            agent_key="architect",
            name="architect_optional_run",
            synthetic_payload={"message": "run"},
            assembly_context={"design_system_active": False},
            is_required=False,
            actor="admin@example.com",
        )
    optional_approved = _real_run(factory, test_case_id=optional_run.id)
    _approve(factory, optional_approved)
    # A required-but-inactive case, reachable only past #267's writers.
    with factory() as db:
        inactive = AgentTestCase(
            agent_key="architect",
            name="architect_inactive_required",
            version=1,
            is_active=False,
            is_required=True,
            synthetic_payload={"message": "inactive"},
            assembly_context={"design_system_active": False},
            created_by="admin@example.com",
            updated_by="admin@example.com",
        )
        db.add(inactive)
        db.commit()
        inactive_id = inactive.id

    result = _publish(factory)

    assert isinstance(result, PublishedRelease)
    assert result.evidence == (
        EvidenceLink(source, "architect", _seed_case_id(factory), "approval", None),
    )
    linked = {row[1] for row in _links(factory)}
    assert linked == {source}
    assert optional_approved not in linked
    assert optional_unrun.id != inactive_id


def test_no_required_case_then_stale_hash_gaps_are_ordered_by_role(factory):
    """C1 unit: architect has no active required case (a direct write past
    #267's refusal); builder has only an approval of its pre-save hash."""
    builder_case = _seed_case_id(factory, "builder")
    stale = _real_run(factory, "builder")
    _approve(factory, stale)
    _save(factory, "builder", "A changed builder prompt for gaps.")
    _save(factory, "architect", "A changed architect prompt for gaps.")
    with factory() as db:
        db.execute(
            update(AgentTestCase)
            .where(AgentTestCase.id == _seed_case_id(factory))
            .values(is_active=False)
        )
        db.commit()
    readiness, calls = _readiness_spy()

    result = _publish(factory, ApprovalEvidenceGate(readiness=readiness))

    assert isinstance(result, PublicationNotReady)
    assert result.locked_gaps == (
        PublicationGap("architect", None, "no_required_case"),
        PublicationGap("builder", builder_case, "no_eligible_approval"),
    )
    assert len(calls) == 1 and result.readiness is calls[0]
    assert isinstance(result.readiness, DraftReadinessResult)
    assert set(result.readiness.blocking_agents) == {"architect", "builder"}
    assert _links(factory) == [] and _release_count(factory) == 1


def test_a_later_roles_missing_case_sorts_after_an_earlier_roles_case_gap(factory):
    """C1 order is role order first: builder's ``no_required_case`` follows
    architect's ``no_eligible_approval`` even though it is emitted first."""
    _save(factory, "architect", "A changed architect prompt for gap order.")
    _save(factory, "builder", "A changed builder prompt for gap order.")
    with factory() as db:
        db.execute(
            update(AgentTestCase)
            .where(AgentTestCase.id == _seed_case_id(factory, "builder"))
            .values(is_active=False)
        )
        db.commit()

    result = _publish(factory)

    assert isinstance(result, PublicationNotReady)
    assert result.locked_gaps == (
        PublicationGap("architect", _seed_case_id(factory), "no_eligible_approval"),
        PublicationGap("builder", None, "no_required_case"),
    )


def test_several_required_cases_of_one_role_are_gaps_in_id_order(factory):
    _save(factory, "architect", "A changed architect prompt for two cases.")
    workbench = AgentTestWorkbench()
    with factory() as db:
        second = workbench.create_test_case(
            db,
            agent_key="architect",
            name="architect_second_required",
            synthetic_payload={"message": "second"},
            assembly_context={"design_system_active": False},
            is_required=True,
            actor="admin@example.com",
        )
    seed = _seed_case_id(factory)

    result = _publish(factory)

    assert isinstance(result, PublicationNotReady)
    assert result.locked_gaps == (
        PublicationGap("architect", seed, "no_eligible_approval"),
        PublicationGap("architect", second.id, "no_eligible_approval"),
    )


def test_a_role_with_two_required_cases_needs_both_approved(factory):
    _save(factory, "architect", "A changed architect prompt for two cases.")
    workbench = AgentTestWorkbench()
    with factory() as db:
        second = workbench.create_test_case(
            db,
            agent_key="architect",
            name="architect_second_required",
            synthetic_payload={"message": "second"},
            assembly_context={"design_system_active": False},
            is_required=True,
            actor="admin@example.com",
        )
    first_run = _real_run(factory)
    _approve(factory, first_run)
    assert isinstance(_publish(factory), PublicationNotReady)
    second_run = _real_run(factory, test_case_id=second.id)
    _approve(factory, second_run)

    result = _publish(factory)

    assert isinstance(result, PublishedRelease)
    assert result.evidence == (
        EvidenceLink(first_run, "architect", _seed_case_id(factory), "approval", None),
        EvidenceLink(second_run, "architect", second.id, "approval", None),
    )


def test_a_superseded_case_version_is_not_evidence(factory):
    """Q8 on SQLite: the approval of row X does not satisfy its successor Y."""
    source = _changed_architect(factory)
    _approve(factory, source)
    seed = _seed_case_id(factory)
    with factory() as db:
        successor = AgentTestWorkbench().update_test_case(
            db,
            test_case_id=seed,
            synthetic_payload={"message": "a revised synthetic input"},
            assembly_context={"design_system_active": False},
            is_required=True,
            actor="admin@example.com",
        )

    result = _publish(factory)

    assert isinstance(result, PublicationNotReady)
    assert result.locked_gaps == (
        PublicationGap("architect", successor.id, "no_eligible_approval"),
    )


# --- readiness is informational only (C32, C39) -------------------------------


def test_readiness_is_called_only_on_the_not_ready_path(factory):
    source = _changed_architect(factory)
    readiness, calls = _readiness_spy()
    not_ready = _publish(factory, ApprovalEvidenceGate(readiness=readiness))
    assert isinstance(not_ready, PublicationNotReady) and len(calls) == 1
    assert _case_status(not_ready.readiness, _seed_case_id(factory)) == "awaiting_review"

    _approve(factory, source)
    published = _publish(factory, ApprovalEvidenceGate(readiness=readiness))

    assert isinstance(published, PublishedRelease)
    assert len(calls) == 1, "readiness must never be read after a publication write"


def test_the_gate_decides_even_when_readiness_says_ready(factory):
    """C32: a readiness callable that claims all-ready decides nothing."""
    _changed_architect(factory)

    result = _publish(factory, ApprovalEvidenceGate(readiness=lambda session: "all ready"))

    assert isinstance(result, PublicationNotReady)
    assert result.readiness == "all ready"
    assert result.locked_gaps == (
        PublicationGap("architect", _seed_case_id(factory), "no_eligible_approval"),
    )


def test_the_production_readiness_binding_refuses_to_run_outside_a_transaction(factory):
    """C39: the binding raises outside a transaction, so the gate can only use it
    inside ``publish_draft``'s own transaction."""
    gate = ApprovalEvidenceGate(readiness=AgentTestWorkbench().readiness_under_parent_lock)
    with factory() as db:
        with pytest.raises(RuntimeError, match="needs the caller's open transaction"):
            gate._readiness(db)


def test_the_gate_writes_nothing_on_either_path(factory):
    source = _changed_architect(factory)
    engine = factory.kw["bind"]
    writes: list[str] = []
    gate = ApprovalEvidenceGate(readiness=AgentTestWorkbench().readiness_under_parent_lock)
    snapshot_holder: dict[str, object] = {}

    @event.listens_for(engine, "before_cursor_execute")
    def _capture(_conn, _cursor, statement, _params, _context, _many):
        if snapshot_holder.get("inside"):
            head = statement.lstrip().split(None, 1)[0].upper()
            if head in ("INSERT", "UPDATE", "DELETE"):
                writes.append(statement)

    class _Observed:
        def lock_and_verify(self, session, *, snapshot, changed_agent_keys):
            snapshot_holder["inside"] = True
            try:
                return gate.lock_and_verify(
                    session, snapshot=snapshot, changed_agent_keys=changed_agent_keys
                )
            finally:
                snapshot_holder["inside"] = False

    try:
        assert isinstance(_publish(factory, _Observed()), PublicationNotReady)
        _approve(factory, source)
        assert isinstance(_publish(factory, _Observed()), PublishedRelease)
    finally:
        event.remove(engine, "before_cursor_execute", _capture)
    assert writes == []


# --- link_release_evidence -----------------------------------------------------


def _v1_id(factory) -> int:
    with factory() as db:
        return db.scalar(select(GraphRelease.id))


def test_link_release_evidence_inserts_and_reads_back_exactly(factory):
    source = _changed_architect(factory)
    _approve(factory, source)
    case_id = _seed_case_id(factory)
    release_id = _v1_id(factory)
    with factory() as db:
        with db.begin():
            link_release_evidence(
                db,
                release_id=release_id,
                evidence=(EvidenceLink(source, "architect", case_id, "approval", None),),
            )
    assert _links(factory) == [(release_id, source, "approval", None)]


def test_link_release_evidence_refuses_a_read_back_that_is_not_exactly_its_links(factory):
    source = _changed_architect(factory)
    other = _insert_run_like(factory, source, run_at=_at(1), **_APPROVED)
    case_id = _seed_case_id(factory)
    release_id = _v1_id(factory)
    with factory() as db:
        with db.begin():
            link_release_evidence(
                db,
                release_id=release_id,
                evidence=(EvidenceLink(source, "architect", case_id, "approval", None),),
            )
    with factory() as db:
        with pytest.raises(GraphConfigurationIntegrityError, match="release evidence"):
            with db.begin():
                link_release_evidence(
                    db,
                    release_id=release_id,
                    evidence=(EvidenceLink(other, "architect", case_id, "approval", None),),
                )
    assert _links(factory) == [(release_id, source, "approval", None)]


def test_link_release_evidence_refuses_a_missing_run(factory):
    case_id = _seed_case_id(factory)
    release_id = _v1_id(factory)
    with factory() as db:
        with pytest.raises(GraphConfigurationIntegrityError, match="release evidence"):
            with db.begin():
                link_release_evidence(
                    db,
                    release_id=release_id,
                    evidence=(EvidenceLink(987654, "architect", case_id, "approval", None),),
                )
    assert _links(factory) == []


# --- Correction 48: a linked run's verdict is a typed refusal -----------------


def test_a_verdict_on_a_published_evidence_run_is_refused_as_linked(factory):
    source = _changed_architect(factory)
    _approve(factory, source)
    unlinked = _insert_run_like(factory, source, run_at=_at(-5), **_UNREVIEWED)
    assert isinstance(_publish(factory), PublishedRelease)
    before = _row(factory, source)

    for verdict in ("rejected", "approved"):
        with pytest.raises(IneligibleForApprovalError) as caught:
            _approve(factory, source, verdict)
        assert (caught.value.run_id, caught.value.reason) == (source, "linked_to_release")
    assert _row(factory, source) == before
    # An unlinked run still takes a verdict.
    assert _approve(factory, unlinked, "rejected").verdict == "rejected"


def test_the_linked_refusal_is_a_422_ineligible_body_with_its_message():
    response = routes._ineligible_response(IneligibleForApprovalError(7, "linked_to_release"))

    assert response.status_code == 422
    body = IneligibleForApprovalResponse.model_validate_json(response.body)
    assert body.model_dump() == {
        "code": "ineligible_for_approval",
        "reason": "linked_to_release",
        "message": "This run is evidence for a published Graph Version; its verdict cannot change.",
    }
