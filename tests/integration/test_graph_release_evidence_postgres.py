"""#269 Task 4: the approval evidence gate, evidence links and their races, on
real PostgreSQL.

Evidence rows come from #267's real ``execute_candidate_run`` with the
deterministic fake adapter, approved through #268's real ``record_verdict``;
further history rows are INSERT-only copies of such a run (never an UPDATE of a
run, which #267's evidence trigger refuses).

Every ordering test goes RED rather than hanging: the database's
``lock_timeout`` is bounded for every connection, every future has a timeout,
the paused holder is released in an inner ``finally``, and each waiter's PID is
captured before its blocking statement (Correction 5).
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import IntegrityError

from src.core.database import _run_migrations
from src.database.models.graph_configuration import (
    AgentTestCase,
    AgentTestRun,
    GraphReleaseTestRun,
)
from src.services.agent_runtime import AgentRuntime
from src.services.agent_runtime_identity import RecordingAgentInvocationIdentitySink
from src.services.agent_test_workbench import (
    AgentTestWorkbench,
    DraftReadinessResult,
    IneligibleForApprovalError,
    TestRunEvidence,
)
from src.services.graph_configuration import (
    EvidenceLink,
    GraphConfiguration,
    PublicationGap,
    PublicationNotReady,
    PublishedRelease,
)
from src.services.graph_release_evidence import ApprovalEvidenceGate
from src.services.persisted_graph_release import PersistedGraphReleaseLoader
from tests.fixtures.deterministic_model_adapter import DeterministicFakeModelAdapter
from tests.integration.postgres_concurrency_helpers import (
    _WAIT_SECONDS,
    _await_blocked_by,
)
from tests.integration.test_graph_release_publication_postgres import (
    _STAGE_MATCHERS,
    _artifacts,
    _drop_commit_failure,
    _factory,
    _fresh_active_pin,
    _install_commit_failure,
    _normalized,
    _release,
    _run_named,
    _save_prompt,
)

pytestmark = pytest.mark.postgres

REVIEWER = "reviewer@example.com"
_VERDICT_COLUMNS = ("verdict", "verdict_reviewer", "verdict_at", "verdict_notes")
_L0_SHARE = "FOR SHARE OF GRAPH_RELEASE, GRAPH_DRAFT"
_L0_UPDATE = "FOR UPDATE OF GRAPH_RELEASE, GRAPH_DRAFT"


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _bound_lock_waits(engine) -> None:
    """Every later connection waits at most ``_WAIT_SECONDS`` on a lock."""
    with engine.connect() as conn:
        name = conn.scalar(text("SELECT current_database()"))
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(
            text(f'ALTER DATABASE "{name}" SET lock_timeout = \'{int(_WAIT_SECONDS)}s\'')
        )
    engine.dispose()


def _setup(postgres_engine):
    factory = _factory(postgres_engine)
    _bound_lock_waits(postgres_engine)
    return factory


class _Pids:
    """Backend PID per thread name, recorded before the thread's lock statement."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._pids: dict[str, int] = {}
        self._counts: dict[str, int] = {}
        self._events: dict[str, threading.Event] = {}

    def event(self, name: str) -> threading.Event:
        with self._guard:
            return self._events.setdefault(name, threading.Event())

    def record(self, name: str, pid: int) -> None:
        with self._guard:
            self._pids[name] = pid
            self._counts[name] = self._counts.get(name, 0) + 1
        self.event(name).set()

    def pid(self, name: str) -> int:
        with self._guard:
            return self._pids[name]

    def count(self, name: str) -> int:
        with self._guard:
            return self._counts.get(name, 0)


class _ObservedGraphConfiguration(GraphConfiguration):
    """Records the caller's PID before its L0 statement (publisher, cleanup, #267 T2)."""

    def __init__(self, pids: _Pids) -> None:
        super().__init__()
        self.observed_pids = pids

    def _lock_current_parents(self, session, *, exclusive):
        pid = session.scalar(text("SELECT pg_backend_pid()"))
        self.observed_pids.record(threading.current_thread().name, pid)
        return super()._lock_current_parents(session, exclusive=exclusive)


def _record_statement_pids(engine, pids: _Pids, names: tuple[str, ...]):
    """C41: a thread whose FIRST statement is its lock records its PID in
    ``before_cursor_execute`` (the ``test_mixed_release_creation_postgres`` recipe)."""

    def _before(conn, _cursor, _statement, _params, _context, _many):
        name = threading.current_thread().name
        if name in names:
            pids.record(name, conn.connection.driver_connection.get_backend_pid())

    event.listen(engine, "before_cursor_execute", _before)
    return lambda: event.remove(engine, "before_cursor_execute", _before)


def _named(name, fn):
    def _call():
        threading.current_thread().name = name
        return fn()

    return _call


def _activity_query(engine, pid: int) -> str:
    with engine.connect() as conn:
        return _normalized(
            conn.scalar(text("SELECT query FROM pg_stat_activity WHERE pid = :pid"), {"pid": pid})
            or ""
        )


def _race(engine, pids: _Pids, *, blocker, waiter, pause_when, waiting_on=()):
    """Pause ``blocker`` after its first statement matching ``pause_when``;
    prove ``waiter`` is blocked by it (and, for ``waiting_on``, on which
    statement); then release.  Returns ``(blocker_future, waiter_future, query)``."""
    blocker_name, blocker_fn = blocker
    waiter_name, waiter_fn = waiter
    paused = threading.Event()
    release = threading.Event()
    fired: list[str] = []
    observed: dict[str, str] = {}

    def _pause(_conn, _cursor, statement, _params, _context, _many):
        normalized = _normalized(statement)
        if threading.current_thread().name == blocker_name and not fired and pause_when(
            normalized
        ):
            fired.append(normalized)
            paused.set()
            assert release.wait(timeout=_WAIT_SECONDS), "the test never released the blocker"

    event.listen(engine, "after_cursor_execute", _pause)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            blocker_future = pool.submit(_named(blocker_name, blocker_fn))
            waiter_future = None
            try:
                assert paused.wait(timeout=_WAIT_SECONDS), f"{blocker_name} never paused"
                waiter_future = pool.submit(_named(waiter_name, waiter_fn))
                assert pids.event(waiter_name).wait(timeout=_WAIT_SECONDS), (
                    f"{waiter_name} never reached its lock"
                )
                assert _await_blocked_by(
                    engine,
                    waiter_pid=pids.pid(waiter_name),
                    blocker_pid=pids.pid(blocker_name),
                ), f"{waiter_name} was never blocked by {blocker_name}"
                observed["query"] = _activity_query(engine, pids.pid(waiter_name))
                observed["tuple_locks"] = _tuple_lock_modes(engine, pids.pid(waiter_name))
                for fragment in waiting_on:
                    assert fragment in observed["query"], (fragment, observed["query"])
                assert not waiter_future.done()
            finally:
                release.set()
            blocker_future.exception(timeout=_WAIT_SECONDS * 2)
            if waiter_future is not None:
                waiter_future.exception(timeout=_WAIT_SECONDS * 2)
    finally:
        event.remove(engine, "after_cursor_execute", _pause)
    assert len(fired) == 1
    return blocker_future, waiter_future, observed


def _tuple_lock_modes(engine, pid: int) -> list[str]:
    """The heavyweight tuple locks ``pid`` holds on ``agent_test_run`` while it
    waits for a row lock: ``AccessExclusiveLock`` for ``FOR UPDATE``,
    ``AccessShareLock`` for an FK check's ``FOR KEY SHARE``."""
    with engine.connect() as conn:
        return list(
            conn.scalars(
                text(
                    "SELECT l.mode FROM pg_locks l JOIN pg_class c ON c.oid = l.relation "
                    "WHERE l.pid = :pid AND l.locktype = 'tuple' "
                    "AND c.relname = 'agent_test_run' ORDER BY l.mode"
                ),
                {"pid": pid},
            )
        )


def _is_l3_lock(normalized: str) -> bool:
    return "FROM AGENT_TEST_RUN" in normalized and normalized.endswith("FOR UPDATE")


def _gate(readiness=None) -> ApprovalEvidenceGate:
    return ApprovalEvidenceGate(
        readiness=readiness or AgentTestWorkbench().readiness_under_parent_lock
    )


def _lock(factory) -> int:
    with factory() as db:
        return db.scalar(text("SELECT lock_version FROM graph_draft"))


def _publish_fn(factory, *, service=None, gate=None):
    service = service or GraphConfiguration()

    def _call():
        with factory() as db:
            return service.publish_draft(
                db,
                expected_lock_version=_lock(factory),
                release_note="Tune roles",
                actor="publisher@example.com",
                evidence_gate=gate or _gate(),
            )

    return _call


def _publish(factory, **kwargs):
    """Publish on a pool thread named ``publisher`` (never renames the main thread)."""
    return _run_named("publisher", _publish_fn(factory, **kwargs))


def _seed_case_id(factory, agent_key: str = "architect") -> int:
    with factory() as db:
        return db.scalar(
            select(AgentTestCase.id).where(
                AgentTestCase.agent_key == agent_key,
                AgentTestCase.name == f"{agent_key}_required_smoke_v1",
            )
        )


def _executor(factory, adapter=None, graph_configuration=None) -> AgentTestWorkbench:
    runtime = AgentRuntime(
        persisted_release_loader=PersistedGraphReleaseLoader(session_factory=factory),
        model_adapter=adapter or DeterministicFakeModelAdapter(),
        identity_sink=RecordingAgentInvocationIdentitySink(),
    )
    return AgentTestWorkbench(runtime=runtime, graph_configuration=graph_configuration)


def _run(factory, agent_key="architect", test_case_id=None, workbench=None) -> int:
    with factory() as db:
        evidence = (workbench or _executor(factory)).execute_candidate_run(
            db,
            agent_key=agent_key,
            test_case_id=test_case_id or _seed_case_id(factory, agent_key),
            expected_lock_version=_lock(factory),
            actor="runner@example.com",
        )
    assert isinstance(evidence, TestRunEvidence)
    assert (evidence.execution_status, evidence.deterministic_checks_passed) == (
        "completed",
        True,
    )
    return evidence.run_id


def _verdict_fn(factory, run_id, verdict="approved"):
    def _call():
        with factory() as db:
            return AgentTestWorkbench().record_verdict(
                db, run_id=run_id, verdict=verdict, reviewer=REVIEWER, notes=None
            )

    return _call


def _approve(factory, run_id, verdict="approved"):
    return _verdict_fn(factory, run_id, verdict)()


def _full_row(factory, run_id: int) -> dict[str, object]:
    with factory() as db:
        return dict(
            db.execute(select(AgentTestRun.__table__).where(AgentTestRun.__table__.c.id == run_id))
            .mappings()
            .one()
        )


def _insert_like(factory, source_run_id: int, **overrides) -> int:
    values = _full_row(factory, source_run_id)
    del values["id"]
    values.update(overrides)
    with factory() as db:
        row = AgentTestRun(**values)
        db.add(row)
        db.commit()
        return row.id


def _approved_overrides(factory) -> dict[str, object]:
    with factory() as db:
        stamp = db.scalar(text("SELECT now()"))
    return {
        "verdict": "approved",
        "verdict_reviewer": REVIEWER,
        "verdict_at": stamp,
        "verdict_notes": None,
    }


def _verdicts(factory) -> dict[int, tuple[object, ...]]:
    with factory() as db:
        return {
            row.id: tuple(getattr(row, column) for column in _VERDICT_COLUMNS)
            for row in db.scalars(select(AgentTestRun).order_by(AgentTestRun.id))
        }


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
                ).order_by(
                    GraphReleaseTestRun.graph_release_id, GraphReleaseTestRun.agent_test_run_id
                )
            )
        ]


def _cases(factory) -> list[tuple[object, ...]]:
    with factory() as db:
        return [
            tuple(row)
            for row in db.execute(
                select(
                    AgentTestCase.id,
                    AgentTestCase.version,
                    AgentTestCase.is_active,
                    AgentTestCase.is_required,
                ).order_by(AgentTestCase.id)
            )
        ]


def _everything(factory) -> dict[str, object]:
    """Every publication artefact, every link, every run verdict and every case."""
    return {
        **_artifacts(factory),
        "links": _links(factory),
        "verdicts": _verdicts(factory),
        "cases": _cases(factory),
    }


def _run_ids_of_case(factory, test_case_id: int) -> list[int]:
    with factory() as db:
        return list(
            db.scalars(
                select(AgentTestRun.id)
                .where(AgentTestRun.test_case_id == test_case_id)
                .order_by(AgentTestRun.run_at, AgentTestRun.id)
            )
        )


def _changed_architect_with_approval(factory) -> int:
    _save_prompt(factory, "architect", "\n\nTune A.", lock=_lock(factory))
    run_id = _run(factory)
    _approve(factory, run_id)
    return run_id


def _assert_not_ready_wrote_nothing(factory, before, result, gaps) -> None:
    assert isinstance(result, PublicationNotReady), result
    assert result.locked_gaps == gaps
    assert isinstance(result.readiness, DraftReadinessResult)
    assert _everything(factory) == before
    assert _fresh_active_pin(factory).graph_version == 1


# ---------------------------------------------------------------------------
# Selection, refusal and links (plan Step 1; C1, C19, C42, C43)
# ---------------------------------------------------------------------------


def test_publication_links_newest_eligible_approval_per_required_case(postgres_engine):
    factory = _setup(postgres_engine)
    a = _changed_architect_with_approval(factory)
    a_at = _full_row(factory, a)["run_at"]
    b = _insert_like(factory, a, run_at=a_at + timedelta(seconds=1), **_approved_overrides(factory))
    case_id = _seed_case_id(factory)
    assert a < b

    result = _publish(factory)

    assert isinstance(result, PublishedRelease)
    v2 = _release(factory, 2)
    assert result.evidence == (EvidenceLink(b, "architect", case_id, "approval", None),)
    assert _links(factory) == [(v2.id, b, "approval", None)]
    with pytest.raises(IntegrityError) as caught:
        with postgres_engine.begin() as conn:
            conn.execute(text("DELETE FROM agent_test_run WHERE id = :id"), {"id": b})
    assert caught.value.orig.pgcode == "23503"
    # The unlinked older approval is not a link, and unchanged roles have none.
    with postgres_engine.begin() as conn:
        conn.execute(text("DELETE FROM agent_test_run WHERE id = :id"), {"id": a})
    assert {link.agent_key for link in result.evidence} == {"architect"}


def test_stale_hash_approval_is_not_ready_and_writes_nothing(postgres_engine):
    factory = _setup(postgres_engine)
    stale = _run(factory)  # architect unchanged: the run is of the published hash
    _approve(factory, stale)
    _save_prompt(factory, "architect", "\n\nTune A.", lock=_lock(factory))
    before = _everything(factory)

    result = _publish(factory)

    _assert_not_ready_wrote_nothing(
        factory,
        before,
        result,
        (PublicationGap("architect", _seed_case_id(factory), "no_eligible_approval"),),
    )
    assert result.readiness.blocking_agents == ("architect",)


def test_case_version_bump_after_approval_is_not_ready(postgres_engine):
    """C42: a new case version is a new row; X's approval does not satisfy Y."""
    factory = _setup(postgres_engine)
    approved = _changed_architect_with_approval(factory)
    x = _seed_case_id(factory)
    with factory() as db:
        y = AgentTestWorkbench().update_test_case(
            db,
            test_case_id=x,
            synthetic_payload={"message": "A revised synthetic architect input."},
            assembly_context={"design_system_active": False},
            is_required=True,
            actor="admin@example.com",
        )
    assert (y.id != x, y.version) == (True, 2)
    before = _everything(factory)

    result = _publish(factory)

    _assert_not_ready_wrote_nothing(
        factory, before, result, (PublicationGap("architect", y.id, "no_eligible_approval"),)
    )
    assert approved not in {row[1] for row in _links(factory)}


def test_changed_role_without_active_required_case_is_not_ready(postgres_engine):
    """C1 / C43: produced by a direct write, because #267's writers refuse it."""
    factory = _setup(postgres_engine)
    _changed_architect_with_approval(factory)
    with postgres_engine.begin() as conn:
        conn.execute(
            text("UPDATE agent_test_case SET is_active = false WHERE id = :id"),
            {"id": _seed_case_id(factory)},
        )
    before = _everything(factory)

    result = _publish(factory)

    _assert_not_ready_wrote_nothing(
        factory, before, result, (PublicationGap("architect", None, "no_required_case"),)
    )
    architect = next(a for a in result.readiness.agents if a.agent_key == "architect")
    assert architect.missing_required_case is True


def test_gate_lock_statement_sequence(postgres_engine):
    """C29 / C33 / C45: L2 unfiltered ``FOR SHARE`` in id order, then a NEW
    unlocked re-select, then L3 ``FOR UPDATE`` in id order, then a NEW unlocked
    re-verify; the gate itself writes nothing."""
    factory = _setup(postgres_engine)
    _changed_architect_with_approval(factory)
    statements: list[str] = []
    inside: list[bool] = [False]
    inner = _gate()

    class _Recording:
        def lock_and_verify(self, session, *, snapshot, changed_agent_keys):
            inside[0] = True
            try:
                return inner.lock_and_verify(
                    session, snapshot=snapshot, changed_agent_keys=changed_agent_keys
                )
            finally:
                inside[0] = False

    def _record(_conn, _cursor, statement, _params, _context, _many):
        if threading.current_thread().name == "publisher" and inside[0]:
            statements.append(_normalized(statement))

    event.listen(postgres_engine, "after_cursor_execute", _record)
    try:
        result = _publish(factory, gate=_Recording())
    finally:
        event.remove(postgres_engine, "after_cursor_execute", _record)

    assert isinstance(result, PublishedRelease)
    assert len(statements) == 4, statements
    l2, reselect, l3, reverify = statements
    assert "FROM AGENT_TEST_CASE" in l2
    assert "IS_ACTIVE" not in l2.split(" FROM ", 1)[1]
    assert "IS_REQUIRED" not in l2.split(" FROM ", 1)[1]
    assert l2.endswith("ORDER BY AGENT_TEST_CASE.ID FOR SHARE")
    assert "FROM AGENT_TEST_CASE" in reselect and "IS_ACTIVE" in reselect
    assert " FOR " not in reselect
    assert "FROM AGENT_TEST_RUN" in l3 and "RUN_KIND" in l3.split(" WHERE ", 1)[1]
    assert l3.endswith("ORDER BY AGENT_TEST_RUN.ID FOR UPDATE")
    # C33 / C45: L3 is literal columns of agent_test_run only.  A join or a
    # correlated eligibility predicate inside the locking statement is not
    # re-evaluated by EvalPlanQual; that belongs in the NEW re-verify statement.
    assert " JOIN " not in l3, l3
    assert "GRAPH_DRAFT_AGENT" not in l3, l3
    assert "AGENT_TEST_CASE" not in l3, l3
    assert " EXISTS" not in l3, l3
    assert "FROM AGENT_TEST_RUN" in reverify and " FOR " not in reverify
    assert not any(s.startswith(("INSERT", "UPDATE", "DELETE")) for s in statements)


# ---------------------------------------------------------------------------
# Correction 8 part 2: rollback at every write seam, with evidence
# ---------------------------------------------------------------------------

_EVIDENCE_STAGES = {**_STAGE_MATCHERS, "evidence_linked": "INSERT INTO GRAPH_RELEASE_TEST_RUN"}


@pytest.mark.parametrize(
    "stage",
    ["interval_closed", "mappings_read_back", "evidence_linked", "draft_rebased", "commit"],
)
def test_injected_failure_with_evidence_rolls_back_every_row(postgres_engine, stage):
    factory = _setup(postgres_engine)
    approval = _changed_architect_with_approval(factory)
    before = _everything(factory)
    fired: list[str] = []

    if stage == "commit":
        _install_commit_failure(postgres_engine)
        with pytest.raises(IntegrityError, match="injected commit failure"):
            _publish(factory)
        fired_count = _drop_commit_failure(postgres_engine)
    else:
        matcher = _EVIDENCE_STAGES[stage]

        def _inject(_conn, _cursor, statement, _params, _context, _many):
            if (
                threading.current_thread().name == "publisher"
                and not fired
                and matcher in _normalized(statement)
            ):
                fired.append(_normalized(statement))
                raise RuntimeError(f"injected at {stage}")

        event.listen(postgres_engine, "after_cursor_execute", _inject)
        try:
            with pytest.raises(RuntimeError, match=f"^injected at {stage}$"):
                _publish(factory)
        finally:
            event.remove(postgres_engine, "after_cursor_execute", _inject)
        fired_count = len(fired)

    assert fired_count == 1
    assert _everything(factory) == before
    with postgres_engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM graph_release_test_run")) == 0
    assert _fresh_active_pin(factory).graph_version == 1

    retried = _publish(factory)
    assert isinstance(retried, PublishedRelease)
    assert retried.release.version_number == 2
    assert [link.agent_test_run_id for link in retried.evidence] == [approval]


# ---------------------------------------------------------------------------
# Correction 14 / 48: the linked-verdict trigger, through the migration path
# ---------------------------------------------------------------------------


def test_linked_verdict_trigger_rejects_a_direct_update_after_migration_rerun(postgres_engine):
    factory = _setup(postgres_engine)
    _run_migrations(postgres_engine)
    unlinked = _changed_architect_with_approval(factory)
    # A tied ``run_at`` and a higher id: this copy is the newest approval.
    linked = _insert_like(factory, unlinked, **_approved_overrides(factory))
    result = _publish(factory)
    assert [link.agent_test_run_id for link in result.evidence] == [linked]

    with pytest.raises(IntegrityError) as caught:
        with postgres_engine.begin() as conn:
            conn.execute(
                text("UPDATE agent_test_run SET verdict = 'rejected' WHERE id = :id"),
                {"id": linked},
            )
    assert caught.value.orig.pgcode == "23514"
    assert "is linked to a release; its verdict is immutable" in str(caught.value.orig)
    for column_sql in (
        "verdict_reviewer = 'other@example.com'",
        "verdict_at = now()",
        "verdict_notes = 'rewritten'",
    ):
        with pytest.raises(IntegrityError) as each:
            with postgres_engine.begin() as conn:
                conn.execute(
                    text(f"UPDATE agent_test_run SET {column_sql} WHERE id = :id"),
                    {"id": linked},
                )
        assert each.value.orig.pgcode == "23514"
    assert _verdicts(factory)[linked][0] == "approved"

    with postgres_engine.begin() as conn:
        conn.execute(
            text("UPDATE agent_test_run SET verdict = 'rejected' WHERE id = :id"),
            {"id": unlinked},
        )
    assert _verdicts(factory)[unlinked][0] == "rejected"


# ---------------------------------------------------------------------------
# Correction 29: a supersede committing while the gate's case lock waits
# ---------------------------------------------------------------------------


def test_supersede_while_the_gate_waits_is_seen_and_refused(postgres_engine):
    """A role with two required cases A and B, both approved.  #267's supersede
    of B holds the role's rows ``FOR UPDATE`` and pauses before commit; the
    publisher's L2 waits on it.  After the commit the gate must see B v2 (from
    its NEW re-select) and refuse it, not publish on the pre-wait set."""
    factory = _setup(postgres_engine)
    _save_prompt(factory, "architect", "\n\nTune A.", lock=_lock(factory))
    workbench = AgentTestWorkbench()
    with factory() as db:
        case_b = workbench.create_test_case(
            db,
            agent_key="architect",
            name="architect_second_required",
            synthetic_payload={"message": "Second required architect input."},
            assembly_context={"design_system_active": False},
            is_required=True,
            actor="admin@example.com",
        )
    case_a = _seed_case_id(factory)
    _approve(factory, _run(factory, test_case_id=case_a))
    _approve(factory, _run(factory, test_case_id=case_b.id))
    pids = _Pids()
    service = _ObservedGraphConfiguration(pids)
    stop = _record_statement_pids(postgres_engine, pids, ("case_writer",))
    before_links = _links(factory)

    def _supersede():
        with factory() as db:
            return AgentTestWorkbench().update_test_case(
                db,
                test_case_id=case_b.id,
                synthetic_payload={"message": "Superseded second input."},
                assembly_context={"design_system_active": False},
                is_required=True,
                actor="admin@example.com",
            )

    try:
        writer, publisher, query = _race(
            postgres_engine,
            pids,
            blocker=("case_writer", _supersede),
            waiter=("publisher", _publish_fn(factory, service=service)),
            pause_when=lambda s: s.startswith("INSERT INTO AGENT_TEST_CASE"),
            waiting_on=("FROM AGENT_TEST_CASE", "FOR SHARE"),
        )
    finally:
        stop()

    b_v2 = writer.result(timeout=0)
    assert b_v2.version == 2 and b_v2.id != case_b.id
    result = publisher.result(timeout=0)
    assert isinstance(result, PublicationNotReady), result
    assert result.locked_gaps == (PublicationGap("architect", b_v2.id, "no_eligible_approval"),)
    assert _links(factory) == before_links == []


# ---------------------------------------------------------------------------
# Cleanup races (C19 outcome (a), C40)
# ---------------------------------------------------------------------------


def _cleanup_history(factory):
    """C19: exactly 25 runs r1..r25 of architect's required case in strictly
    increasing ``(run_at, id)``; r1 is the only eligible approval, r2..r5 are
    rejected, r6..r25 are of a stale hash."""
    _save_prompt(factory, "architect", "\n\nTune A.", lock=_lock(factory))
    r1 = _run(factory)
    _approve(factory, r1)
    r1_at = _full_row(factory, r1)["run_at"]
    rejected = {**_approved_overrides(factory), "verdict": "rejected"}
    unreviewed = dict.fromkeys(_VERDICT_COLUMNS)
    ids = [r1]
    for index in range(2, 26):
        overrides = rejected if index <= 5 else {**unreviewed, "candidate_hash": "e" * 64}
        ids.append(
            _insert_like(factory, r1, run_at=r1_at + timedelta(seconds=index), **overrides)
        )
    assert _run_ids_of_case(factory, _seed_case_id(factory)) == ids
    return ids


def _cleanup_fn(factory, workbench):
    def _call():
        with factory() as db:
            return workbench.cleanup_unpublished_test_runs(db)

    return _call


def test_cleanup_first_then_publication(postgres_engine):
    factory = _setup(postgres_engine)
    ids = _cleanup_history(factory)
    pids = _Pids()
    observed = _ObservedGraphConfiguration(pids)

    cleanup, publisher, query = _race(
        postgres_engine,
        pids,
        blocker=("cleanup", _cleanup_fn(factory, AgentTestWorkbench(graph_configuration=observed))),
        waiter=("publisher", _publish_fn(factory, service=observed)),
        pause_when=lambda s: _L0_SHARE in s,
        waiting_on=(_L0_UPDATE,),
    )

    assert cleanup.result(timeout=0) == 4
    retained = _run_ids_of_case(factory, _seed_case_id(factory))
    assert retained == [ids[0], *ids[5:]]
    result = publisher.result(timeout=0)
    assert isinstance(result, PublishedRelease)
    assert [link.agent_test_run_id for link in result.evidence] == [ids[0]]
    assert _links(factory) == [(result.release.release_id, ids[0], "approval", None)]


def test_publication_first_then_cleanup(postgres_engine):
    factory = _setup(postgres_engine)
    ids = _cleanup_history(factory)
    pids = _Pids()
    observed = _ObservedGraphConfiguration(pids)

    publisher, cleanup, query = _race(
        postgres_engine,
        pids,
        blocker=("publisher", _publish_fn(factory, service=observed)),
        waiter=("cleanup", _cleanup_fn(factory, AgentTestWorkbench(graph_configuration=observed))),
        pause_when=_is_l3_lock,
        waiting_on=(_L0_SHARE,),
    )

    result = publisher.result(timeout=0)
    assert isinstance(result, PublishedRelease)
    assert [link.agent_test_run_id for link in result.evidence] == [ids[0]]
    assert cleanup.result(timeout=0) == 4
    retained = _run_ids_of_case(factory, _seed_case_id(factory))
    assert retained == [ids[0], *ids[5:]]
    assert ids[0] in retained
    assert _links(factory) == [(result.release.release_id, ids[0], "approval", None)]
    with pytest.raises(IntegrityError):
        with postgres_engine.begin() as conn:
            conn.execute(text("DELETE FROM agent_test_run WHERE id = :id"), {"id": ids[0]})


# ---------------------------------------------------------------------------
# Verdict races (C41, C47, C48)
# ---------------------------------------------------------------------------


def test_verdict_rejection_first_then_publication(postgres_engine):
    factory = _setup(postgres_engine)
    approval = _changed_architect_with_approval(factory)
    pids = _Pids()
    service = _ObservedGraphConfiguration(pids)
    stop = _record_statement_pids(postgres_engine, pids, ("verdict",))
    before = _everything(factory)

    try:
        verdict, publisher, query = _race(
            postgres_engine,
            pids,
            blocker=("verdict", _verdict_fn(factory, approval, "rejected")),
            waiter=("publisher", _publish_fn(factory, service=service)),
            pause_when=lambda s: s.startswith("UPDATE AGENT_TEST_RUN"),
            waiting_on=("FROM AGENT_TEST_RUN", "FOR UPDATE"),
        )
    finally:
        stop()

    assert verdict.result(timeout=0).verdict == "rejected"
    # C47: the publisher waits on its L3 FOR UPDATE, not on the link INSERT's FK check.
    assert query["query"].startswith("SELECT AGENT_TEST_RUN.ID FROM AGENT_TEST_RUN")
    assert query["tuple_locks"] == ["AccessExclusiveLock"], query
    result = publisher.result(timeout=0)
    assert isinstance(result, PublicationNotReady), result
    assert result.locked_gaps == (
        PublicationGap("architect", _seed_case_id(factory), "no_eligible_approval"),
    )
    after = _everything(factory)
    assert after["verdicts"][approval][0] == "rejected"
    after["verdicts"] = before["verdicts"]
    assert after == before
    assert _fresh_active_pin(factory).graph_version == 1


def test_publication_first_then_verdict_change(postgres_engine):
    factory = _setup(postgres_engine)
    approval = _changed_architect_with_approval(factory)
    before_verdict = _verdicts(factory)[approval]
    pids = _Pids()
    service = _ObservedGraphConfiguration(pids)
    stop = _record_statement_pids(postgres_engine, pids, ("verdict",))

    try:
        publisher, verdict, query = _race(
            postgres_engine,
            pids,
            blocker=("publisher", _publish_fn(factory, service=service)),
            waiter=("verdict", _verdict_fn(factory, approval, "rejected")),
            pause_when=_is_l3_lock,
            # The writer's L3 statement lists every column, past pg_stat_activity's
            # query-text limit, so its lock mode is read from pg_locks instead.
            waiting_on=("SELECT AGENT_TEST_RUN.ID",),
        )
    finally:
        stop()

    result = publisher.result(timeout=0)
    assert isinstance(result, PublishedRelease)
    assert query["tuple_locks"] == ["AccessExclusiveLock"], query
    assert _links(factory) == [(result.release.release_id, approval, "approval", None)]
    error = verdict.exception(timeout=0)
    assert isinstance(error, IneligibleForApprovalError), repr(error)
    assert (error.run_id, error.reason) == (approval, "linked_to_release")
    assert _verdicts(factory)[approval] == before_verdict


# ---------------------------------------------------------------------------
# Correction 13: #267's run insert and publication serialize without deadlock
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("order", ["run_first", "publication_first"])
def test_test_run_insert_and_publication_serialize_without_deadlock(postgres_engine, order):
    factory = _setup(postgres_engine)
    _changed_architect_with_approval(factory)
    v1 = _release(factory, 1)
    pids = _Pids()
    observed = _ObservedGraphConfiguration(pids)
    entered = threading.Event()
    release_model = threading.Event()
    adapter = DeterministicFakeModelAdapter(
        mode="pause", entered=entered, release=release_model, pause_timeout=_WAIT_SECONDS
    )
    runner = _executor(factory, adapter, graph_configuration=observed)
    t2_paused = threading.Event()
    release_t2 = threading.Event()
    publisher_paused = threading.Event()
    release_publisher = threading.Event()

    def _pause(_conn, _cursor, statement, _params, _context, _many):
        name = threading.current_thread().name
        normalized = _normalized(statement)
        if name == "runner" and order == "run_first" and release_model.is_set():
            if _L0_SHARE in normalized and not t2_paused.is_set():
                t2_paused.set()
                assert release_t2.wait(timeout=_WAIT_SECONDS)
        if name == "publisher" and order == "publication_first" and _is_l3_lock(normalized):
            if not publisher_paused.is_set():
                publisher_paused.set()
                assert release_publisher.wait(timeout=_WAIT_SECONDS)

    def _run_call():
        with factory() as db:
            return runner.execute_candidate_run(
                db,
                agent_key="architect",
                test_case_id=_seed_case_id(factory),
                expected_lock_version=_lock(factory),
                actor="runner@example.com",
            )

    publish = _named("publisher", _publish_fn(factory, service=observed))
    event.listen(postgres_engine, "after_cursor_execute", _pause)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            running = pool.submit(_named("runner", _run_call))
            publishing = None
            try:
                assert entered.wait(timeout=_WAIT_SECONDS), "the model call never started"
                t1_calls = pids.count("runner")
                if order == "run_first":
                    release_model.set()
                    assert t2_paused.wait(timeout=_WAIT_SECONDS), "transaction 2 never locked"
                    assert pids.count("runner") == t1_calls + 1
                    publishing = pool.submit(publish)
                    assert pids.event("publisher").wait(timeout=_WAIT_SECONDS)
                    waiter, blocker = "publisher", "runner"
                else:
                    publishing = pool.submit(publish)
                    assert publisher_paused.wait(timeout=_WAIT_SECONDS), "publisher never paused"
                    release_model.set()
                    assert _wait_until(lambda: pids.count("runner") > t1_calls), (
                        "transaction 2 never reached its parent lock"
                    )
                    waiter, blocker = "runner", "publisher"
                assert _await_blocked_by(
                    postgres_engine, waiter_pid=pids.pid(waiter), blocker_pid=pids.pid(blocker)
                ), f"{waiter} was never blocked by {blocker}"
                expected = _L0_UPDATE if waiter == "publisher" else _L0_SHARE
                assert expected in _activity_query(postgres_engine, pids.pid(waiter))
            finally:
                release_model.set()
                release_t2.set()
                release_publisher.set()
            run = running.result(timeout=_WAIT_SECONDS * 2)
            published = publishing.result(timeout=_WAIT_SECONDS * 2) if publishing else None
    finally:
        event.remove(postgres_engine, "after_cursor_execute", _pause)

    assert isinstance(published, PublishedRelease)
    assert published.release.version_number == 2
    assert run.compared_release_id == v1.id
    if order == "run_first":
        assert (run.candidate_is_current, run.base_release_is_current) == (True, True)
    else:
        # #267 C8.5: the run is persisted as what ran; the base moved on.
        assert (run.candidate_is_current, run.base_release_is_current) == (True, False)


def _wait_until(predicate) -> bool:
    deadline = time.monotonic() + _WAIT_SECONDS
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False
