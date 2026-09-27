"""#270 Task 3b: restoring a historical Graph Release, on real PostgreSQL.

Every release is built through #269's real ``publish_draft`` and its real
``ApprovalEvidenceGate``; every approval is #267's real ``execute_candidate_run``
(``DeterministicFakeModelAdapter``) approved through #268's real
``record_verdict`` (Correction 45).  The real clock is used throughout
(Correction 1 step 4).

Ids diverge from version numbers: before v2 one publication is rolled back by
#269's deferred commit trigger, which burns ``graph_release.id`` 2, so the
releases are (id, version) = (1, 1), (3, 2), (4, 3) ... (8, 7), and every
assertion names the exact pair.

Every lock wait is bounded (``_setup`` sets the database's ``lock_timeout``) and
every call runs on a bounded future (``_run_named``), so a regression goes RED
rather than hanging.  This file has no ordering test; those are Task 4's.
"""

from __future__ import annotations

import threading

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import IntegrityError

from src.api.services.session_manager import SessionManager
from src.database.models.graph_configuration import (
    AgentDefinitionRevision,
    AgentTestCase,
    AgentTestRun,
    GraphDraft,
    GraphDraftAgent,
)
from src.database.models.session import UserSession
from src.services.agent_runtime import AgentAssemblyContext, AgentRuntime
from src.services.agent_runtime_identity import RecordingAgentInvocationIdentitySink
from src.services.agent_test_workbench import AgentTestWorkbench, DraftReadinessResult
from src.services.conversation_pins import (
    get_conversation_graph_version,
    load_conversation_pin,
)
from src.services.graph_configuration import (
    EvidenceLink,
    GraphConfiguration,
    PublicationGap,
    PublicationNotReady,
    PublishedRelease,
    RestoredRelease,
)
from src.services.graph_definition_manifest import GRAPH_V1_AGENT_KEYS
from src.services.graph_release_history import ReleaseRef, list_release_history
from src.services.persisted_graph_release import PersistedGraphReleaseLoader
from tests.fixtures.deterministic_model_adapter import DeterministicFakeModelAdapter
from tests.integration.test_conversation_pin_acceptance_postgres import _database_context
from tests.integration.test_graph_release_evidence_postgres import (
    _approve,
    _everything,
    _links,
    _lock,
    _publish,
    _run,
    _seed_case_id,
    _setup,
)
from tests.integration.test_graph_release_publication_postgres import (
    _STAGE_MATCHERS,
    _drop_commit_failure,
    _fresh_active_pin,
    _install_commit_failure,
    _mappings,
    _normalized,
    _release,
    _run_named,
    _save_prompt,
)

pytestmark = pytest.mark.postgres

_ONCALL = "oncall@example.com"
_NOTE = "Emergency: back to 3"
_ROLLBACK_THREAD = "rollback"
_OTHERS = tuple(k for k in GRAPH_V1_AGENT_KEYS if k not in ("architect", "builder"))

#: v1..v7 after the burned id 2 (the module docstring).
_V1_TO_V7 = [(1, 1), *((version + 1, version) for version in range(2, 8))]

#: C42: the core's four write seams, the rollback's own draft-agent reset, and
#: the deferred commit trigger.  Six stages; Correction 15's assertions apply to
#: each.
_ROLLBACK_STAGES = {
    **_STAGE_MATCHERS,
    "evidence_linked": "INSERT INTO GRAPH_RELEASE_TEST_RUN",
    "draft_reset": "UPDATE GRAPH_DRAFT_AGENT SET",
}


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _approved_run(factory, agent_key: str) -> int:
    run_id = _run(factory, agent_key)
    _approve(factory, run_id)
    return run_id


def _publish_version(factory, version: int, expected_runs: list[int]) -> PublishedRelease:
    result = _publish(factory)
    assert isinstance(result, PublishedRelease), result
    assert result.release.version_number == version
    assert sorted(link.agent_test_run_id for link in result.evidence) == sorted(expected_runs)
    assert {link.evidence_kind for link in result.evidence} == {"approval"}
    return result


def _build_v2_to_v7(postgres_engine, *, builder_in_v3: bool = False) -> dict[str, object]:
    """v2..v7 each change architect (``+2`` .. ``+7``), each approved by its own
    run ``R<v>``; ``builder_in_v3`` also changes builder in v3 (run ``B3``).

    Before v2 one publication is rolled back at commit, burning id 2.
    """
    factory = _setup(postgres_engine)
    runs: dict[int, int] = {}
    _save_prompt(factory, "architect", "\n\n+2", lock=_lock(factory))
    runs[2] = _approved_run(factory, "architect")
    _install_commit_failure(postgres_engine)
    with pytest.raises(IntegrityError, match="injected commit failure"):
        _publish(factory)
    assert _drop_commit_failure(postgres_engine) == 1
    _publish_version(factory, 2, [runs[2]])

    builder_run = None
    for version in range(3, 8):
        _save_prompt(factory, "architect", f"\n\n+{version}", lock=_lock(factory))
        runs[version] = _approved_run(factory, "architect")
        expected = [runs[version]]
        if version == 3 and builder_in_v3:
            _save_prompt(factory, "builder", "\n\n+3", lock=_lock(factory))
            builder_run = _approved_run(factory, "builder")
            expected.append(builder_run)
        _publish_version(factory, version, expected)

    assert _pairs(factory) == _V1_TO_V7
    return {
        "factory": factory,
        "v": {version: _release(factory, version) for version in range(1, 8)},
        "runs": runs,
        "builder_run": builder_run,
    }


def _pairs(factory) -> list[tuple[int, int]]:
    with factory() as db:
        return [
            tuple(row)
            for row in db.execute(
                text("SELECT id, version_number FROM graph_release ORDER BY version_number")
            )
        ]


def _restore_fn(factory, version_number: int, *, lock: int | None = None, note=_NOTE):
    def _call():
        with factory() as db:
            return GraphConfiguration().restore_release(
                db,
                version_number=version_number,
                expected_lock_version=_lock(factory) if lock is None else lock,
                release_note=note,
                actor=_ONCALL,
            )

    return _call


def _restore(factory, version_number: int, **kwargs):
    """Restore on a bounded pool thread named ``rollback``."""
    return _run_named(_ROLLBACK_THREAD, _restore_fn(factory, version_number, **kwargs))


def _runs(factory) -> list[dict[str, object]]:
    """Every ``agent_test_run`` row, every column."""
    table = AgentTestRun.__table__
    with factory() as db:
        return [dict(row) for row in db.execute(select(table).order_by(table.c.id)).mappings()]


def _draft_agents(factory) -> dict[str, tuple[str, str]]:
    with factory() as db:
        return {
            row.agent_key: (row.candidate_hash, row.prompt_text)
            for row in db.scalars(select(GraphDraftAgent))
        }


def _revision_hash(factory, revision_id: int) -> str:
    with factory() as db:
        return db.get(AgentDefinitionRevision, revision_id).content_hash


def _history(factory) -> dict[int, object]:
    with factory() as db:
        return {entry.version_number: entry for entry in list_release_history(db)}


# ---------------------------------------------------------------------------
# The headline restore (plan Step 4, C16)
# ---------------------------------------------------------------------------


def test_v8_restores_v3_with_exact_intervals_mappings_and_evidence(postgres_engine):
    built = _build_v2_to_v7(postgres_engine)
    factory, v, runs = built["factory"], built["v"], built["runs"]
    case_id = _seed_case_id(factory)
    # A pending builder edit, so the Q7 rebase has all three effects.
    _save_prompt(factory, "builder", "\n\npending", lock=_lock(factory))
    lock = _lock(factory)
    drafts_before = _draft_agents(factory)
    v3_mapping = _mappings(factory, v[3].id)
    links_before = _links(factory)
    runs_before = _runs(factory)
    with factory() as db:
        revisions_before = list(
            db.scalars(select(AgentDefinitionRevision.id).order_by(AgentDefinitionRevision.id))
        )
    assert (v[3].id, v[7].id) == (4, 8)
    assert (v[3].id, runs[3], "approval", None) in links_before

    outcome = _restore(factory, 3, lock=lock)

    assert isinstance(outcome, RestoredRelease), outcome
    published = outcome.published
    assert outcome.source == ReleaseRef(4, 3)
    assert (published.release.release_id, published.release.version_number) == (9, 8)
    assert published.previous_release_id == 8
    assert published.release.restored_from_release_id == 4
    assert (published.release.release_note, published.release.published_by) == (_NOTE, _ONCALL)
    assert {k: m.agent_definition_revision_id for k, m in published.mappings.items()} == (
        v3_mapping
    )
    assert all(m.reused is True for m in published.mappings.values())
    assert published.changed_agent_keys == ("architect",)
    assert published.evidence == (
        EvidenceLink(runs[3], "architect", case_id, "historical_restore", 4),
    )
    assert dict(outcome.draft_effect) == {
        "architect": "reset",
        "builder": "kept",
        **dict.fromkeys(_OTHERS, "unchanged"),
    }

    # Rows: exact (id, version) pairs, the v3 mapping, no new revision.
    assert _pairs(factory) == [*_V1_TO_V7, (9, 8)]
    assert _mappings(factory, 9) == v3_mapping
    with factory() as db:
        assert (
            list(
                db.scalars(select(AgentDefinitionRevision.id).order_by(AgentDefinitionRevision.id))
            )
            == revisions_before
        )

    # Intervals: v7 closed exactly at v8's start; v3's untouched.
    v3_after, v7_after, v8 = _release(factory, 3), _release(factory, 7), _release(factory, 8)
    with factory() as db:
        draft = db.get(GraphDraft, 1)
    assert v8.effective_from.tzinfo is not None
    assert v7_after.effective_to == v8.effective_from == v8.published_at == draft.updated_at
    assert v8.effective_to is None
    assert v3_after.effective_to == v[3].effective_to
    assert v3_after.effective_from == v[3].effective_from
    assert (v8.previous_release_id, v8.restored_from_release_id) == (8, 4)
    assert _fresh_active_pin(factory).release_id == 9

    # Evidence: exactly one new link; v3's own approval link is unchanged;
    # every run row is byte-identical and no run was added.
    assert _links(factory) == sorted([*links_before, (9, runs[3], "historical_restore", 4)])
    assert [row for row in _links(factory) if row[0] == 9] == [
        (9, runs[3], "historical_restore", 4)
    ]
    assert (4, runs[3], "approval", None) in _links(factory)
    assert _runs(factory) == runs_before

    # Draft: based on v8, advanced once; clean architect reset to v3's content,
    # the pending builder edit kept exactly, the rest untouched.
    assert (draft.base_release_id, draft.lock_version, draft.updated_by) == (9, lock + 1, _ONCALL)
    drafts_after = _draft_agents(factory)
    assert drafts_after["architect"][0] == _revision_hash(factory, v3_mapping["architect"])
    assert drafts_after["architect"] != drafts_before["architect"]
    assert drafts_after["builder"] == drafts_before["builder"]
    assert drafts_after["builder"][0] != _revision_hash(factory, v3_mapping["builder"])
    for key in _OTHERS:
        assert drafts_after[key] == drafts_before[key]
    with factory() as db:
        snapshot = GraphConfiguration().read_workbench(db)
        db.rollback()
    changed = {n.agent_key: n.changed for n in snapshot.nodes if n.execution_kind == "model"}
    assert changed == {key: key == "builder" for key in GRAPH_V1_AGENT_KEYS}

    # History: v8 restoring v3, newest first.
    history = _history(factory)
    assert next(iter(history)) == 8
    assert history[8].restored_from == ReleaseRef(4, 3)
    assert history[8].previous == ReleaseRef(8, 7)
    assert history[3].restored_by == (ReleaseRef(9, 8),)
    assert (history[8].is_active, history[7].is_active) == (True, False)


# ---------------------------------------------------------------------------
# Full rollback at every stage, then a gap-free retry (C42, C15)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stage",
    [
        "interval_closed",
        "mappings_read_back",
        "evidence_linked",
        "draft_rebased",
        "draft_reset",
        "commit",
    ],
)
def test_injected_failure_rolls_back_every_row(postgres_engine, stage):
    built = _build_v2_to_v7(postgres_engine)
    factory, runs = built["factory"], built["runs"]
    lock = _lock(factory)
    before = _everything(factory)
    runs_before = _runs(factory)
    fired: list[str] = []

    if stage == "commit":
        _install_commit_failure(postgres_engine)
        with pytest.raises(IntegrityError, match="injected commit failure"):
            _restore(factory, 3, lock=lock)
        fired_count = _drop_commit_failure(postgres_engine)
    else:
        matcher = _ROLLBACK_STAGES[stage]
        # Every stage but the first write is armed only after the interval close,
        # so a read that happens to share a matcher before any write cannot fire it.
        armed = [stage == "interval_closed"]

        def _inject(_conn, _cursor, statement, _params, _context, _many):
            if threading.current_thread().name != _ROLLBACK_THREAD or fired:
                return
            normalized = _normalized(statement)
            if matcher in normalized and armed[0]:
                fired.append(normalized)
                raise RuntimeError(f"injected at {stage}")
            if _STAGE_MATCHERS["interval_closed"] in normalized:
                armed[0] = True

        event.listen(postgres_engine, "after_cursor_execute", _inject)
        try:
            with pytest.raises(RuntimeError, match=f"^injected at {stage}$"):
                _restore(factory, 3, lock=lock)
        finally:
            event.remove(postgres_engine, "after_cursor_execute", _inject)
        fired_count = len(fired)

    assert fired_count == 1
    assert _everything(factory) == before
    assert _runs(factory) == runs_before
    with postgres_engine.connect() as conn:
        assert (
            conn.scalar(
                text(
                    "SELECT count(*) FROM graph_release_test_run "
                    "WHERE evidence_kind = 'historical_restore'"
                )
            )
            == 0
        )
    pin = _fresh_active_pin(factory)
    assert (pin.release_id, pin.graph_version) == (8, 7)

    retried = _restore(factory, 3, lock=lock)

    assert isinstance(retried, RestoredRelease), retried
    # A stage after the release INSERT burned id 9; the version has no gap.
    new_id = 9 if stage == "interval_closed" else 10
    assert (retried.published.release.release_id, retried.published.release.version_number) == (
        new_id,
        8,
    )
    assert _pairs(factory) == [*_V1_TO_V7, (new_id, 8)]
    assert [row for row in _links(factory) if row[0] == new_id] == [
        (new_id, runs[3], "historical_restore", 4)
    ]
    assert _runs(factory) == runs_before


# ---------------------------------------------------------------------------
# Review Focus 1 and 2
# ---------------------------------------------------------------------------


def test_restore_a_restoration_links_its_links_with_the_selected_source(postgres_engine):
    built = _build_v2_to_v7(postgres_engine)
    factory, runs = built["factory"], built["runs"]
    assert isinstance(_restore(factory, 3), RestoredRelease)  # v8 = id 9
    v8_mapping = _mappings(factory, 9)
    _save_prompt(factory, "architect", "\n\n+9", lock=_lock(factory))
    r9 = _approved_run(factory, "architect")
    _publish_version(factory, 9, [r9])  # v9 = id 10
    links_before = _links(factory)

    outcome = _restore(factory, 8)

    assert isinstance(outcome, RestoredRelease), outcome
    assert outcome.source == ReleaseRef(9, 8)
    release = outcome.published.release
    assert (release.release_id, release.version_number) == (11, 10)
    assert release.restored_from_release_id == 9
    assert _mappings(factory, 11) == v8_mapping
    assert [row for row in _links(factory) if row[0] == 11] == [
        (11, runs[3], "historical_restore", 9)
    ]
    assert _links(factory) == sorted([*links_before, (11, runs[3], "historical_restore", 9)])
    history = _history(factory)
    assert history[10].restored_from == ReleaseRef(9, 8)
    assert history[8].restored_by == (ReleaseRef(11, 10),)
    assert history[3].restored_by == (ReleaseRef(9, 8),)


def test_restore_v1_links_no_evidence(postgres_engine):
    built = _build_v2_to_v7(postgres_engine)
    factory = built["factory"]
    v1_mapping = _mappings(factory, 1)
    links_before = _links(factory)
    with factory() as db:
        revisions_before = list(db.scalars(select(AgentDefinitionRevision.id)))

    outcome = _restore(factory, 1)

    assert isinstance(outcome, RestoredRelease), outcome
    assert outcome.source == ReleaseRef(1, 1)
    release = outcome.published.release
    assert (release.release_id, release.version_number) == (9, 8)
    assert release.restored_from_release_id == 1
    assert outcome.published.evidence == ()
    assert _mappings(factory, 9) == v1_mapping
    assert all(m.reused is True for m in outcome.published.mappings.values())
    with factory() as db:
        assert (
            db.scalar(
                text("SELECT count(*) FROM graph_release_test_run WHERE graph_release_id = 9")
            )
            == 0
        )
        assert sorted(db.scalars(select(AgentDefinitionRevision.id))) == sorted(revisions_before)
    assert _links(factory) == links_before


# ---------------------------------------------------------------------------
# Pinned conversations and the runtime (plan Step 4)
# ---------------------------------------------------------------------------


def _graph_version(factory, session_id: str):
    with factory() as db:
        row = db.scalar(select(UserSession).where(UserSession.session_id == session_id))
        return get_conversation_graph_version(db, row)


def test_pinned_historical_releases_remain_readable_and_executable(postgres_engine, monkeypatch):
    built = _build_v2_to_v7(postgres_engine)
    factory = built["factory"]
    managed_session = _database_context(factory)
    for target in (
        "src.api.services.session_manager.get_db_session",
        "src.api.services.slide_repository.get_db_session",
        "src.api.services.deck_level_writer.get_db_session",
        "src.services.graph.nodes.get_db_session",
    ):
        monkeypatch.setattr(target, managed_session)
    monkeypatch.setattr("src.services.identity_provider.resolve_display_names", lambda emails: {})
    manager = SessionManager()
    created = manager.create_session(
        session_id="pinned-v7", created_by="pinned@example.com", graph_capable=True
    )
    assert created["graph_version"] == 7
    assert load_conversation_pin(factory, "pinned-v7") == 8

    assert isinstance(_restore(factory, 3), RestoredRelease)

    assert load_conversation_pin(factory, "pinned-v7") == 8
    version = _graph_version(factory, "pinned-v7")
    assert (version.graph_version, version.active_graph_version, version.is_older_than_active) == (
        7,
        8,
        True,
    )
    created_v8 = manager.create_session(
        session_id="pinned-v8", created_by="pinned@example.com", graph_capable=True
    )
    assert (created_v8["graph_version"], created_v8["active_graph_version"]) == (8, 8)
    assert load_conversation_pin(factory, "pinned-v8") == 9

    with factory() as db:
        case = db.get(AgentTestCase, _seed_case_id(factory))
        payload = dict(case.synthetic_payload)
        context = AgentAssemblyContext(
            design_system_active=bool(case.assembly_context["design_system_active"])
        )
    sink = RecordingAgentInvocationIdentitySink()
    runtime = AgentRuntime(
        persisted_release_loader=PersistedGraphReleaseLoader(session_factory=factory),
        model_adapter=DeterministicFakeModelAdapter(),
        identity_sink=sink,
    )
    for release_id in (8, 4, 9):  # closed v7, closed v3, active v8
        runtime.run("architect", release_id, payload, context)

    identities = [
        (
            s.identity.graph_release_id,
            s.identity.graph_version,
            s.identity.agent_definition_revision_id,
        )
        for s in sink.successes
    ]
    architect = {rid: _mappings(factory, rid)["architect"] for rid in (8, 4, 9)}
    assert identities == [(8, 7, architect[8]), (4, 3, architect[4]), (9, 8, architect[9])]
    assert architect[9] == architect[4] != architect[8]
    assert sink.error_classes == []


# ---------------------------------------------------------------------------
# Review Focus 4 / Correction 30: restored links never satisfy readiness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("variant", ["new_edit_after_rollback", "kept_edit_from_before"])
def test_historical_restore_evidence_never_satisfies_readiness(postgres_engine, variant):
    """The refusal comes from the gate's content-hash key, not from any link
    filter: the gate never reads ``graph_release_test_run`` (Correction 30).
    v8's ``historical_restore`` links name approved runs of v3's architect and
    builder, and neither makes a new hash ready."""
    built = _build_v2_to_v7(postgres_engine, builder_in_v3=True)
    factory, runs, builder_run = built["factory"], built["runs"], built["builder_run"]
    if variant == "kept_edit_from_before":
        _save_prompt(factory, "builder", "\n\nkept", lock=_lock(factory))

    outcome = _restore(factory, 3)

    assert isinstance(outcome, RestoredRelease), outcome
    assert sorted(row for row in _links(factory) if row[0] == 9) == sorted(
        [(9, runs[3], "historical_restore", 4), (9, builder_run, "historical_restore", 4)]
    )
    if variant == "new_edit_after_rollback":
        assert outcome.draft_effect["builder"] == "unchanged"
        _save_prompt(factory, "architect", "\n\nH", lock=_lock(factory))
        blocking = "architect"
    else:
        assert outcome.draft_effect["builder"] == "kept"
        blocking = "builder"
    with factory() as db:
        readiness = AgentTestWorkbench().draft_readiness(db)
    assert isinstance(readiness, DraftReadinessResult)
    assert (readiness.all_ready, readiness.blocking_agents) == (False, (blocking,))
    before = _everything(factory)

    result = _publish(factory)

    assert isinstance(result, PublicationNotReady), result
    assert result.locked_gaps == (
        PublicationGap(blocking, _seed_case_id(factory, blocking), "no_eligible_approval"),
    )
    assert _everything(factory) == before
    pin = _fresh_active_pin(factory)
    assert (pin.release_id, pin.graph_version) == (9, 8)
