"""#270 Task 4: rollback forced against every other L0 writer, on real PostgreSQL.

Each test pauses one transaction right after a named lock statement, proves the
other transaction is queued behind it (``pg_blocking_pids``, both PIDs captured
with ``pg_backend_pid()`` before the blocking statement, #269 C5), releases the
pause and asserts the exact linearized outcome: one stale conflict, the exact
``(id, version)`` pairs and no gap in the version numbers.

The seed is v1..v4, each changing architect and each approved by its own run
``R<v>`` through #267's real ``execute_candidate_run`` and #268's real
``record_verdict``, published through #269's real ``publish_draft`` and gate.
Before v2 one publication is rolled back by #269's deferred commit trigger,
which burns ``graph_release.id`` 2, so ids differ from versions: (1, 1),
(3, 2), (4, 3), (5, 4), and the next release is (6, 5).  Every test restores v2
(id 3) while v4 (id 5) is active unless it says otherwise, and never resolves a
version by id.

Every wait is bounded, so a broken ordering goes RED instead of hanging: #269's
``_setup`` sets the throwaway database's ``lock_timeout``, every future has a
timeout, and the paused holder is released in an inner ``finally``
(``_race``).  Helpers come from #269's files by underscore name (#269 C24).
"""

from __future__ import annotations

import re
import threading
from collections import Counter
from contextlib import contextmanager
from datetime import timedelta

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import IntegrityError

from src.database.models.graph_configuration import (
    AgentDefinitionRevision,
    GraphReleaseAgent,
)
from src.services.agent_test_workbench import (
    AgentTestWorkbench,
    IneligibleForApprovalError,
    TestRunEvidence,
)
from src.services.graph_configuration import (
    DraftSaveConflict,
    DraftSaveResult,
    EditableModelDraft,
    GraphConfigurationIntegrityError,
    PublicationConflict,
    PublishedRelease,
    RestoredRelease,
)
from src.services.graph_definition_manifest import GRAPH_V1_AGENT_KEYS
from src.services.graph_release_history import ReleaseRef
from tests.integration.test_graph_release_evidence_postgres import (
    _VERDICT_COLUMNS,
    _approve,
    _cleanup_fn,
    _full_row,
    _insert_like,
    _links,
    _lock,
    _ObservedGraphConfiguration,
    _Pids,
    _publish,
    _race,
    _record_statement_pids,
    _run,
    _run_ids_of_case,
    _seed_case_id,
    _setup,
    _verdict_fn,
    _verdicts,
)
from tests.integration.test_graph_release_publication_postgres import (
    _drop_commit_failure,
    _install_commit_failure,
    _publish_as,
    _release_set,
    _save_prompt,
)

pytestmark = pytest.mark.postgres

_ONCALL = "oncall@example.com"
_NOTE = "Emergency: back to 2"
_OTHERS = tuple(k for k in GRAPH_V1_AGENT_KEYS if k not in ("architect", "builder"))

#: v1..v4 after the burned id 2, and the next release (the module docstring).
_V1_TO_V4 = [(1, 1), (3, 2), (4, 3), (5, 4)]
_V5 = (6, 5)
_V2_ID, _V4_ID, _V5_ID = 3, 5, 6

_L0_UPDATE = "FOR UPDATE OF GRAPH_RELEASE, GRAPH_DRAFT"
_L0_SHARE = "FOR SHARE OF GRAPH_RELEASE, GRAPH_DRAFT"
_L3_UPDATE = "FOR UPDATE OF AGENT_TEST_RUN"
_ROW_LOCK = re.compile(r"\bFOR (UPDATE|SHARE|NO KEY UPDATE|KEY SHARE)\b")


# ---------------------------------------------------------------------------
# Matchers (Corrections 6 and 28)
# ---------------------------------------------------------------------------


def _is_l0(normalized: str) -> bool:
    """C6: the both-parents lock in ANY mode, so a shared-mode sabotage still
    pauses and is then caught by the mode assertion, not by a missed pause."""
    return (
        "FROM GRAPH_RELEASE" in normalized
        and "GRAPH_DRAFT" in normalized
        and "GRAPH_DRAFT_AGENT" not in normalized
        and _ROW_LOCK.search(normalized) is not None
    )


def _is_source_runs_read(normalized: str) -> bool:
    """C28: the rollback's L3 read of the source's linked runs, in any mode."""
    return "FROM AGENT_TEST_RUN JOIN GRAPH_RELEASE_TEST_RUN" in normalized


class _Recorder:
    """A pause predicate that also remembers the statement it fired on."""

    def __init__(self, predicate) -> None:
        self._predicate = predicate
        self.statement: str | None = None

    def __call__(self, normalized: str) -> bool:
        if self._predicate(normalized):
            self.statement = normalized
            return True
        return False


@contextmanager
def _l0_scans(engine):
    """Counts every L0 statement per thread name (the handoff rescan is a second)."""
    counts: Counter[str] = Counter()

    def _after(_conn, _cursor, statement, _params, _context, _many):
        if _is_l0(" ".join(statement.upper().split())):
            counts[threading.current_thread().name] += 1

    event.listen(engine, "after_cursor_execute", _after)
    try:
        yield counts
    finally:
        event.remove(engine, "after_cursor_execute", _after)


# ---------------------------------------------------------------------------
# Seed and calls
# ---------------------------------------------------------------------------


def _approved_run(factory, agent_key: str = "architect") -> int:
    run_id = _run(factory, agent_key)
    _approve(factory, run_id)
    return run_id


def _pairs(factory) -> list[tuple[int, int]]:
    with factory() as db:
        return [
            tuple(row)
            for row in db.execute(
                text("SELECT id, version_number FROM graph_release ORDER BY version_number")
            )
        ]


def _seed(postgres_engine) -> dict[str, object]:
    """v1..v4, architect ``+2`` .. ``+4``, each approved by ``R<v>``; id 2 burned."""
    factory = _setup(postgres_engine)
    runs: dict[int, int] = {}
    for version in (2, 3, 4):
        _save_prompt(factory, "architect", f"\n\n+{version}", lock=_lock(factory))
        runs[version] = _approved_run(factory)
        if version == 2:
            _install_commit_failure(postgres_engine)
            with pytest.raises(IntegrityError, match="injected commit failure"):
                _publish(factory)
            assert _drop_commit_failure(postgres_engine) == 1
        published = _publish(factory)
        assert isinstance(published, PublishedRelease), published
        assert published.release.version_number == version
        assert [link.agent_test_run_id for link in published.evidence] == [runs[version]]
    assert _pairs(factory) == _V1_TO_V4
    assert _links(factory) == [
        (_V2_ID, runs[2], "approval", None),
        (4, runs[3], "approval", None),
        (_V4_ID, runs[4], "approval", None),
    ]
    return {"factory": factory, "runs": runs}


def _mapping(factory, release_id: int) -> dict[str, int]:
    with factory() as db:
        return dict(
            db.execute(
                select(
                    GraphReleaseAgent.agent_key,
                    GraphReleaseAgent.agent_definition_revision_id,
                ).where(GraphReleaseAgent.graph_release_id == release_id)
            ).all()
        )


def _mapped_hash(factory, release_id: int, agent_key: str) -> str:
    with factory() as db:
        return db.scalar(
            select(AgentDefinitionRevision.content_hash)
            .join(
                GraphReleaseAgent,
                GraphReleaseAgent.agent_definition_revision_id == AgentDefinitionRevision.id,
            )
            .where(
                GraphReleaseAgent.graph_release_id == release_id,
                GraphReleaseAgent.agent_key == agent_key,
            )
        )


def _draft_hashes(factory) -> dict[str, str]:
    with factory() as db:
        return dict(
            db.execute(text("SELECT agent_key, candidate_hash FROM graph_draft_agent")).all()
        )


def _restore_as(service, factory, *, lock: int, version: int = 2, actor=_ONCALL, note=_NOTE):
    def _call():
        with factory() as db:
            return service.restore_release(
                db,
                version_number=version,
                expected_lock_version=lock,
                release_note=note,
                actor=actor,
            )

    return _call


def _save_as(service, factory, *, lock: int, agent_key: str = "builder", suffix: str):
    with factory() as db:
        snapshot = service.read_workbench(db)
        db.rollback()
    content = next(n for n in snapshot.nodes if n.agent_key == agent_key).draft.content
    candidate = EditableModelDraft(
        prompt_text=content.prompt_text + suffix,
        endpoint_name=content.model.endpoint_name,
        temperature=float(content.model.temperature),
        max_tokens=content.model.max_tokens,
        top_p=float(content.model.top_p),
    )

    def _call():
        with factory() as db:
            return service.save_editable_model_draft(
                db,
                agent_key=agent_key,
                expected_lock_version=lock,
                actor="editor@example.com",
                candidate=candidate,
            )

    return _call


def _read_as(service, factory):
    def _call():
        with factory() as db:
            snapshot = service.read_workbench(db)
            db.rollback()
            return snapshot

    return _call


def _assert_restored_v2(outcome, *, lock_before: int, actor=_ONCALL, note=_NOTE) -> None:
    assert isinstance(outcome, RestoredRelease), outcome
    release = outcome.published.release
    assert outcome.source == ReleaseRef(_V2_ID, 2)
    assert (release.release_id, release.version_number) == _V5
    assert outcome.published.previous_release_id == _V4_ID
    assert release.restored_from_release_id == _V2_ID
    assert (release.published_by, release.release_note) == (actor, note)
    assert outcome.published.draft.base_release_id == _V5_ID
    assert outcome.published.draft.lock_version == lock_before + 1


def _assert_stale_behind_v5(conflict, *, lock: int) -> None:
    assert isinstance(conflict, PublicationConflict), conflict
    assert conflict == PublicationConflict(
        expected_lock_version=lock,
        current_lock_version=lock + 1,
        active_release_id=_V5_ID,
        active_version_number=5,
        draft=conflict.draft,
    ), conflict
    assert (conflict.draft.base_release_id, conflict.draft.lock_version) == (_V5_ID, lock + 1)


def _assert_five_releases_v5_active(factory) -> None:
    assert _pairs(factory) == [*_V1_TO_V4, _V5]
    assert _release_set(factory) == {
        (1, 1, False),
        (3, 2, False),
        (4, 3, False),
        (5, 4, False),
        (_V5_ID, 5, True),
    }


# ---------------------------------------------------------------------------
# Rollback against publication
# ---------------------------------------------------------------------------


def test_rollback_first_then_publication_is_stale(postgres_engine):
    seeded = _seed(postgres_engine)
    factory = seeded["factory"]
    lock = _save_prompt(factory, "builder", "\n\npending", lock=_lock(factory)).draft.lock_version
    builder_pending = _draft_hashes(factory)["builder"]
    pids = _Pids()
    service = _ObservedGraphConfiguration(pids)
    paused_on = _Recorder(_is_l0)

    with _l0_scans(postgres_engine) as scans:
        rollback, publisher, _ = _race(
            postgres_engine,
            pids,
            blocker=("rollback", _restore_as(service, factory, lock=lock)),
            waiter=("publisher", _publish_as(service, factory, lock=lock)),
            pause_when=paused_on,
            waiting_on=(_L0_UPDATE,),
        )

    assert _L0_UPDATE in paused_on.statement
    outcome = rollback.result(timeout=0)
    _assert_restored_v2(outcome, lock_before=lock)
    assert dict(outcome.draft_effect) == {
        "architect": "reset",
        "builder": "kept",
        **dict.fromkeys(_OTHERS, "unchanged"),
    }
    _assert_stale_behind_v5(publisher.result(timeout=0), lock=lock)
    # The publisher queued on v4's row, which the rollback closed: the handoff rescan.
    assert (scans["rollback"], scans["publisher"]) == (1, 2)
    _assert_five_releases_v5_active(factory)
    assert _mapping(factory, _V5_ID) == _mapping(factory, _V2_ID)
    assert _draft_hashes(factory)["builder"] == builder_pending


def test_publication_first_then_rollback_is_stale_and_not_v6(postgres_engine):
    seeded = _seed(postgres_engine)
    factory = seeded["factory"]
    lock = _save_prompt(factory, "builder", "\n\n+5", lock=_lock(factory)).draft.lock_version
    v4_mapping = _mapping(factory, _V4_ID)
    pids = _Pids()
    service = _ObservedGraphConfiguration(pids)
    paused_on = _Recorder(_is_l0)

    with _l0_scans(postgres_engine) as scans:
        publisher, rollback, _ = _race(
            postgres_engine,
            pids,
            blocker=("publisher", _publish_as(service, factory, lock=lock)),
            waiter=("rollback", _restore_as(service, factory, lock=lock)),
            pause_when=paused_on,
            waiting_on=(_L0_UPDATE,),
        )

    assert _L0_UPDATE in paused_on.statement
    published = publisher.result(timeout=0)
    assert isinstance(published, PublishedRelease), published
    assert (published.release.release_id, published.release.version_number) == _V5
    assert published.release.restored_from_release_id is None
    _assert_stale_behind_v5(rollback.result(timeout=0), lock=lock)
    # The rollback queued on v4's row, which the publisher closed: scanned twice.
    assert (scans["publisher"], scans["rollback"]) == (1, 2)
    _assert_five_releases_v5_active(factory)
    v5_mapping = _mapping(factory, _V5_ID)
    assert {k for k in GRAPH_V1_AGENT_KEYS if v5_mapping[k] != v4_mapping[k]} == {"builder"}
    assert [link[0] for link in _links(factory)] == [_V2_ID, 4, _V4_ID]


# ---------------------------------------------------------------------------
# Rollback against rollback
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("winner", ["alpha", "beta"])
def test_two_rollbacks_one_winner_one_exact_stale_conflict(postgres_engine, winner):
    seeded = _seed(postgres_engine)
    factory, runs = seeded["factory"], seeded["runs"]
    lock = _lock(factory)
    loser = "beta" if winner == "alpha" else "alpha"
    pids = _Pids()
    service = _ObservedGraphConfiguration(pids)
    paused_on = _Recorder(_is_l0)

    def _as(name):
        return _restore_as(service, factory, lock=lock, actor=f"{name}@example.com", note=name)

    with _l0_scans(postgres_engine) as scans:
        won, lost, _ = _race(
            postgres_engine,
            pids,
            blocker=("rollback-winner", _as(winner)),
            waiter=("rollback-loser", _as(loser)),
            pause_when=paused_on,
            waiting_on=(_L0_UPDATE,),
        )

    assert _L0_UPDATE in paused_on.statement
    _assert_restored_v2(
        won.result(timeout=0), lock_before=lock, actor=f"{winner}@example.com", note=winner
    )
    _assert_stale_behind_v5(lost.result(timeout=0), lock=lock)
    assert (scans["rollback-winner"], scans["rollback-loser"]) == (1, 2)
    _assert_five_releases_v5_active(factory)
    assert _links(factory)[-1] == (_V5_ID, runs[2], "historical_restore", _V2_ID)
    assert len(_links(factory)) == 4


def test_sequential_rollback_retry_is_stale(postgres_engine):
    """Review Focus 3: a retried request (same lock) after success never makes v6."""
    seeded = _seed(postgres_engine)
    factory = seeded["factory"]
    lock = _lock(factory)
    service = _ObservedGraphConfiguration(_Pids())

    first = _restore_as(service, factory, lock=lock)()
    _assert_restored_v2(first, lock_before=lock)
    links_after_first = _links(factory)

    retry = _restore_as(service, factory, lock=lock)()

    _assert_stale_behind_v5(retry, lock=lock)
    _assert_five_releases_v5_active(factory)
    assert _links(factory) == links_after_first


# ---------------------------------------------------------------------------
# Rollback against draft saves
# ---------------------------------------------------------------------------


def test_draft_save_first_then_rollback_is_stale(postgres_engine):
    seeded = _seed(postgres_engine)
    factory = seeded["factory"]
    lock = _lock(factory)
    pids = _Pids()
    service = _ObservedGraphConfiguration(pids)
    paused_on = _Recorder(_is_l0)
    links_before = _links(factory)

    saved, rollback, _ = _race(
        postgres_engine,
        pids,
        blocker=("saver", _save_as(service, factory, lock=lock, suffix="\n\nWinning edit.")),
        waiter=("rollback", _restore_as(service, factory, lock=lock)),
        pause_when=paused_on,
        waiting_on=(_L0_UPDATE,),
    )

    assert _L0_UPDATE in paused_on.statement
    save = saved.result(timeout=0)
    assert isinstance(save, DraftSaveResult), save
    assert save.draft.lock_version == lock + 1
    conflict = rollback.result(timeout=0)
    assert isinstance(conflict, PublicationConflict), conflict
    assert conflict == PublicationConflict(
        expected_lock_version=lock,
        current_lock_version=lock + 1,
        active_release_id=_V4_ID,
        active_version_number=4,
        draft=conflict.draft,
    ), conflict
    assert (conflict.draft.base_release_id, conflict.draft.lock_version) == (_V4_ID, lock + 1)
    assert _pairs(factory) == _V1_TO_V4
    assert _links(factory) == links_before
    drafts = _draft_hashes(factory)
    assert drafts["builder"] == save.definition.candidate_hash
    assert drafts["builder"] != _mapped_hash(factory, _V4_ID, "builder")
    assert drafts["architect"] == _mapped_hash(factory, _V4_ID, "architect")


def test_rollback_first_then_draft_save_is_stale_not_500(postgres_engine):
    seeded = _seed(postgres_engine)
    factory = seeded["factory"]
    lock = _lock(factory)
    pids = _Pids()
    service = _ObservedGraphConfiguration(pids)
    paused_on = _Recorder(_is_l0)
    v2_architect = _mapped_hash(factory, _V2_ID, "architect")
    assert v2_architect != _mapped_hash(factory, _V4_ID, "architect")

    rollback, saved, _ = _race(
        postgres_engine,
        pids,
        blocker=("rollback", _restore_as(service, factory, lock=lock)),
        waiter=("saver", _save_as(service, factory, lock=lock, suffix="\n\nLate edit.")),
        pause_when=paused_on,
        waiting_on=(_L0_UPDATE,),
    )

    assert _L0_UPDATE in paused_on.statement
    outcome = rollback.result(timeout=0)
    _assert_restored_v2(outcome, lock_before=lock)
    assert dict(outcome.draft_effect) == {
        "architect": "reset",
        **dict.fromkeys(("builder", *_OTHERS), "unchanged"),
    }
    error = saved.exception(timeout=0)
    assert not isinstance(error, GraphConfigurationIntegrityError), repr(error)
    assert error is None, repr(error)
    conflict = saved.result(timeout=0)
    assert isinstance(conflict, DraftSaveConflict), conflict
    assert (conflict.expected_lock_version, conflict.current_lock_version) == (lock, lock + 1)
    server = conflict.server
    assert (server.draft.base_release_id, server.draft.base_version_number) == (_V5_ID, 5)
    assert server.draft.lock_version == lock + 1
    assert server.definitions["architect"].candidate_hash == v2_architect
    _assert_five_releases_v5_active(factory)
    assert _draft_hashes(factory) == {
        key: _mapped_hash(factory, _V5_ID, key) for key in GRAPH_V1_AGENT_KEYS
    }


def test_workbench_read_during_rollback_sees_coherent_new_release(postgres_engine):
    seeded = _seed(postgres_engine)
    factory = seeded["factory"]
    lock = _lock(factory)
    pids = _Pids()
    service = _ObservedGraphConfiguration(pids)
    paused_on = _Recorder(_is_l0)

    rollback, read, _ = _race(
        postgres_engine,
        pids,
        blocker=("rollback", _restore_as(service, factory, lock=lock)),
        waiter=("reader", _read_as(service, factory)),
        pause_when=paused_on,
        waiting_on=(_L0_SHARE,),
    )

    assert _L0_UPDATE in paused_on.statement
    outcome = rollback.result(timeout=0)
    _assert_restored_v2(outcome, lock_before=lock)
    snapshot = read.result(timeout=0)
    assert (snapshot.active_release.release_id, snapshot.active_release.version_number) == _V5
    assert (snapshot.draft.base_release_id, snapshot.draft.lock_version) == (_V5_ID, lock + 1)
    nodes = {node.agent_key: node for node in snapshot.nodes}
    assert [k for k, effect in outcome.draft_effect.items() if effect == "reset"] == ["architect"]
    assert nodes["architect"].changed is False
    assert nodes["architect"].draft.candidate_hash == _mapped_hash(factory, _V2_ID, "architect")
    assert [node.changed for node in snapshot.nodes] == [False] * len(snapshot.nodes)


# ---------------------------------------------------------------------------
# Rollback against #268's verdict writer (C28, C41, #269 C48)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "verdict", ["rejected", "approved"], ids=["change_refused", "identical_noop"]
)
def test_verdict_change_on_source_linked_run_waits_then_is_refused(postgres_engine, verdict):
    seeded = _seed(postgres_engine)
    factory, runs = seeded["factory"], seeded["runs"]
    r2 = runs[2]
    lock = _lock(factory)
    verdict_before = _verdicts(factory)[r2]
    assert verdict_before[0] == "approved"
    pids = _Pids()
    service = _ObservedGraphConfiguration(pids)
    paused_on = _Recorder(_is_source_runs_read)
    stop = _record_statement_pids(postgres_engine, pids, ("verdict",))

    try:
        rollback, writer, observed = _race(
            postgres_engine,
            pids,
            blocker=("rollback", _restore_as(service, factory, lock=lock)),
            waiter=("verdict", _verdict_fn(factory, r2, verdict)),
            pause_when=paused_on,
            # The writer's L3 lists every column, past pg_stat_activity's text
            # limit, so its lock mode is read from pg_locks below.
            waiting_on=("SELECT AGENT_TEST_RUN.ID",),
        )
    finally:
        stop()

    assert _L3_UPDATE in paused_on.statement
    assert observed["tuple_locks"] == ["AccessExclusiveLock"], observed
    outcome = rollback.result(timeout=0)
    _assert_restored_v2(outcome, lock_before=lock)
    assert [
        (link.agent_test_run_id, link.evidence_kind, link.source_release_id)
        for link in outcome.published.evidence
    ] == [(r2, "historical_restore", _V2_ID)]
    if verdict == "rejected":
        error = writer.exception(timeout=0)
        assert type(error) is IneligibleForApprovalError, repr(error)
        assert (error.run_id, error.reason) == (r2, "linked_to_release")
    else:
        evidence = writer.result(timeout=0)
        assert isinstance(evidence, TestRunEvidence), evidence
        assert (evidence.run_id, evidence.verdict) == (r2, "approved")
    assert _verdicts(factory)[r2] == verdict_before
    assert len(verdict_before) == len(_VERDICT_COLUMNS)
    r2_links = [link for link in _links(factory) if link[1] == r2]
    assert r2_links == [
        (_V2_ID, r2, "approval", None),
        (_V5_ID, r2, "historical_restore", _V2_ID),
    ]
    _assert_five_releases_v5_active(factory)


# ---------------------------------------------------------------------------
# Rollback against #268's cleanup (C9, C45)
# ---------------------------------------------------------------------------


def _unprotected_history(factory, runs) -> list[int]:
    """22 unreviewed, stale-hash copies of R4 after it: cleanup keeps the newest
    20 unprotected runs of the case and deletes exactly the oldest two; R2..R4
    are linked (protected)."""
    source = runs[4]
    at = _full_row(factory, source)["run_at"]
    copies = [
        _insert_like(
            factory,
            source,
            run_at=at + timedelta(seconds=index),
            candidate_hash="e" * 64,
            **dict.fromkeys(_VERDICT_COLUMNS),
        )
        for index in range(1, 23)
    ]
    assert _run_ids_of_case(factory, _seed_case_id(factory)) == [runs[2], runs[3], runs[4], *copies]
    return copies


@pytest.mark.parametrize("first", ["cleanup", "rollback"])
def test_rollback_and_cleanup_serialize_with_exact_deletions(postgres_engine, first):
    seeded = _seed(postgres_engine)
    factory, runs = seeded["factory"], seeded["runs"]
    copies = _unprotected_history(factory, runs)
    lock = _lock(factory)
    pids = _Pids()
    service = _ObservedGraphConfiguration(pids)
    cleanup = ("cleanup", _cleanup_fn(factory, AgentTestWorkbench(graph_configuration=service)))
    rollback = ("rollback", _restore_as(service, factory, lock=lock))
    paused_on = _Recorder(_is_l0)

    if first == "cleanup":
        cleaned, restored, _ = _race(
            postgres_engine,
            pids,
            blocker=cleanup,
            waiter=rollback,
            pause_when=paused_on,
            waiting_on=(_L0_UPDATE,),
        )
        assert _L0_SHARE in paused_on.statement
    else:
        restored, cleaned, _ = _race(
            postgres_engine,
            pids,
            blocker=rollback,
            waiter=cleanup,
            pause_when=paused_on,
            waiting_on=(_L0_SHARE,),
        )
        assert _L0_UPDATE in paused_on.statement

    assert cleaned.result(timeout=0) == 2
    assert _run_ids_of_case(factory, _seed_case_id(factory)) == [
        runs[2],
        runs[3],
        runs[4],
        *copies[2:],
    ]
    outcome = restored.result(timeout=0)
    _assert_restored_v2(outcome, lock_before=lock)
    assert [link.agent_test_run_id for link in outcome.published.evidence] == [runs[2]]
    # Task 5 Minor 4: R2's full link list in both orders (its approval link to v2
    # survives cleanup, plus the one restore link), and the whole link table.
    assert [link for link in _links(factory) if link[1] == runs[2]] == [
        (_V2_ID, runs[2], "approval", None),
        (_V5_ID, runs[2], "historical_restore", _V2_ID),
    ]
    assert _links(factory) == [
        (_V2_ID, runs[2], "approval", None),
        (4, runs[3], "approval", None),
        (_V4_ID, runs[4], "approval", None),
        (_V5_ID, runs[2], "historical_restore", _V2_ID),
    ]
    _assert_five_releases_v5_active(factory)
