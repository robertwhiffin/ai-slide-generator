"""#269 Task 1: atomic single-publisher behaviour on real PostgreSQL.

``_NoEvidenceGate`` and ``_save_prompt`` are defined here once (Correction 24):
Task 2 appends to this file and reuses them; Task 3 imports them by underscore
name.  They are test-only and never imported by ``src``.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.database.models.graph_configuration import (
    AgentDefinitionRevision,
    GraphDraft,
    GraphDraftAgent,
    GraphRelease,
    GraphReleaseAgent,
)
from src.services.conversation_pins import lock_active_graph_release
from src.services.graph_configuration import (
    BootstrapResult,
    DraftSaveConflict,
    DraftSaveResult,
    EditableModelDraft,
    GraphConfiguration,
    PublicationConflict,
    PublishedRelease,
)
from src.services.graph_definition_manifest import (
    GRAPH_V1_AGENT_KEYS,
    definition_content_hash,
)
from src.services.persisted_graph_release import PersistedGraphReleaseLoader
from tests.integration.postgres_concurrency_helpers import (
    _WAIT_SECONDS,
    _await_blocked_by,
)

pytestmark = pytest.mark.postgres


class _NoEvidenceGate:
    """Phase A only. Publishes without approval evidence; never constructed by a route."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def lock_and_verify(self, session, *, snapshot, changed_agent_keys):
        self.calls.append(tuple(changed_agent_keys))
        return ()


def _save_prompt(factory, agent_key, suffix, *, lock, prompt_text=None):
    """Save one role's prompt (``content.prompt_text + suffix`` unless given)."""
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


def _factory(postgres_engine) -> sessionmaker:
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    GraphConfiguration().bootstrap_v1(factory)
    return factory


def _publish(factory, *, lock, gate=None, note="Tune roles", service=None):
    service = GraphConfiguration() if service is None else service
    with factory() as db:
        return service.publish_draft(
            db,
            expected_lock_version=lock,
            release_note=note,
            actor="publisher@example.com",
            evidence_gate=_NoEvidenceGate() if gate is None else gate,
        )


def _run_named(name, fn):
    """Run ``fn`` on a thread called ``name`` and return its result (or raise)."""
    with ThreadPoolExecutor(max_workers=1) as pool:

        def _call():
            threading.current_thread().name = name
            return fn()

        return pool.submit(_call).result(timeout=_WAIT_SECONDS * 2)


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
                    ).order_by(GraphDraftAgent.agent_key)
                )
            ],
        }


def _release(factory, version_number) -> GraphRelease:
    with factory() as db:
        return db.scalar(
            select(GraphRelease).where(GraphRelease.version_number == version_number)
        )


def _mappings(factory, release_id) -> dict[str, int]:
    with factory() as db:
        return dict(
            db.execute(
                select(
                    GraphReleaseAgent.agent_key,
                    GraphReleaseAgent.agent_definition_revision_id,
                ).where(GraphReleaseAgent.graph_release_id == release_id)
            ).all()
        )


def _fresh_active_pin(factory):
    with factory() as db:
        with db.begin():
            return lock_active_graph_release(db)


def _normalized(statement: str) -> str:
    return " ".join(statement.upper().split())


# ---------------------------------------------------------------------------
# Exact, contiguous publication
# ---------------------------------------------------------------------------


def test_publication_is_exact_and_contiguous_on_postgresql(postgres_engine):
    factory = _factory(postgres_engine)
    v1 = _release(factory, 1)
    v1_mappings = _mappings(factory, v1.id)
    architect = _save_prompt(factory, "architect", "\n\nTune A.", lock=0)
    builder = _save_prompt(factory, "builder", "\n\nTune B.", lock=1)
    gate = _NoEvidenceGate()

    result = _publish(factory, lock=2, gate=gate, note="Tune two roles")

    assert isinstance(result, PublishedRelease)
    assert result.release.version_number == 2
    assert result.previous_release_id == v1.id
    assert result.release.previous_release_id == v1.id
    assert result.changed_agent_keys == ("architect", "builder")
    assert gate.calls == [("architect", "builder")]
    assert result.evidence == ()
    v2 = _release(factory, 2)
    assert result.release.release_id == v2.id
    v2_mappings = _mappings(factory, v2.id)
    assert v2_mappings == {
        key: mapping.agent_definition_revision_id
        for key, mapping in result.mappings.items()
    }
    for key in GRAPH_V1_AGENT_KEYS:
        if key in ("architect", "builder"):
            assert result.mappings[key].reused is False
            assert v2_mappings[key] != v1_mappings[key]
        else:
            assert result.mappings[key].reused is True
            assert v2_mappings[key] == v1_mappings[key]
    assert result.mappings["architect"].content_hash == definition_content_hash(
        architect.definition.content
    )
    assert result.mappings["builder"].content_hash == definition_content_hash(
        builder.definition.content
    )

    with factory() as db:
        v1_row = db.get(GraphRelease, v1.id)
        draft = db.get(GraphDraft, 1)
    assert v1_row.effective_to is not None
    assert v1_row.effective_to.tzinfo is not None
    assert v1_row.effective_to == v2.effective_from == v2.published_at == draft.updated_at
    assert result.release.effective_from == v2.effective_from
    assert v2.effective_to is None
    assert v2.previous_release_id == v1.id
    assert v2.restored_from_release_id is None
    assert (draft.base_release_id, draft.lock_version, draft.updated_by) == (
        v2.id,
        3,
        "publisher@example.com",
    )

    loader = PersistedGraphReleaseLoader(session_factory=factory)
    assert (
        loader.resolve(v2.id, "architect").agent_definition_revision_id
        == result.mappings["architect"].agent_definition_revision_id
    )
    assert (
        loader.resolve(v1.id, "architect").agent_definition_revision_id
        == v1_mappings["architect"]
    )
    assert _fresh_active_pin(factory).release_id == v2.id


# ---------------------------------------------------------------------------
# Full rollback at every write seam (Correction 8 part 1)
# ---------------------------------------------------------------------------

_STAGE_MATCHERS = {
    "interval_closed": "UPDATE GRAPH_RELEASE SET EFFECTIVE_TO",
    "mappings_read_back": "SELECT GRAPH_RELEASE_AGENT.AGENT_KEY",
    "draft_rebased": "UPDATE GRAPH_DRAFT SET",
}


def _install_commit_failure(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE SEQUENCE test_fail_publication_fired"))
        conn.execute(
            text(
                """
                CREATE FUNCTION test_fail_publication_at_commit() RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    PERFORM nextval('test_fail_publication_fired');
                    RAISE EXCEPTION 'injected commit failure' USING ERRCODE = '23514';
                END;
                $$
                """
            )
        )
        conn.execute(
            text(
                "CREATE CONSTRAINT TRIGGER test_fail_publication_at_commit "
                "AFTER INSERT ON graph_release DEFERRABLE INITIALLY DEFERRED "
                "FOR EACH ROW EXECUTE FUNCTION test_fail_publication_at_commit()"
            )
        )


def _drop_commit_failure(engine) -> int:
    """Remove the injection and return how many times it fired (non-transactional)."""
    with engine.begin() as conn:
        last_value, is_called = conn.execute(
            text("SELECT last_value, is_called FROM test_fail_publication_fired")
        ).one()
        conn.execute(
            text("DROP TRIGGER test_fail_publication_at_commit ON graph_release")
        )
        conn.execute(text("DROP FUNCTION test_fail_publication_at_commit()"))
        conn.execute(text("DROP SEQUENCE test_fail_publication_fired"))
    return last_value if is_called else 0


@pytest.mark.parametrize(
    "stage", ["interval_closed", "mappings_read_back", "draft_rebased", "commit"]
)
def test_injected_failure_rolls_back_every_row(postgres_engine, stage):
    factory = _factory(postgres_engine)
    v1 = _release(factory, 1)
    _save_prompt(factory, "architect", "\n\nTune A.", lock=0)
    _save_prompt(factory, "builder", "\n\nTune B.", lock=1)
    before = _artifacts(factory)
    fired: list[str] = []

    if stage == "commit":
        _install_commit_failure(postgres_engine)
        with pytest.raises(IntegrityError, match="injected commit failure"):
            _run_named("publisher", lambda: _publish(factory, lock=2))
        fired_count = _drop_commit_failure(postgres_engine)
    else:
        matcher = _STAGE_MATCHERS[stage]

        @event.listens_for(postgres_engine, "after_cursor_execute")
        def _inject(_conn, _cursor, statement, _params, _context, _executemany):
            if (
                threading.current_thread().name == "publisher"
                and not fired
                and matcher in _normalized(statement)
            ):
                fired.append(_normalized(statement))
                raise RuntimeError(f"injected at {stage}")

        try:
            with pytest.raises(RuntimeError, match=f"^injected at {stage}$"):
                _run_named("publisher", lambda: _publish(factory, lock=2))
        finally:
            event.remove(postgres_engine, "after_cursor_execute", _inject)
        fired_count = len(fired)

    assert fired_count == 1
    assert _artifacts(factory) == before
    assert _fresh_active_pin(factory).release_id == v1.id

    retried = _publish(factory, lock=2)
    assert isinstance(retried, PublishedRelease)
    assert retried.release.version_number == 2
    assert retried.previous_release_id == v1.id


# ---------------------------------------------------------------------------
# Reuse, lock statements, and published-history guards
# ---------------------------------------------------------------------------


def test_reverted_content_reuses_the_older_revision(postgres_engine):
    factory = _factory(postgres_engine)
    v1 = _release(factory, 1)
    v1_architect_id = _mappings(factory, v1.id)["architect"]
    with factory() as db:
        v1_prompt = db.get(AgentDefinitionRevision, v1_architect_id).prompt_text
    _save_prompt(factory, "architect", "\n\nTune A.", lock=0)
    v2 = _publish(factory, lock=1)
    assert isinstance(v2, PublishedRelease)
    assert v2.mappings["architect"].agent_definition_revision_id != v1_architect_id
    _save_prompt(factory, "architect", "", lock=2, prompt_text=v1_prompt)
    with factory() as db:
        architect_revisions_before = list(
            db.scalars(
                select(AgentDefinitionRevision.id)
                .where(AgentDefinitionRevision.agent_key == "architect")
                .order_by(AgentDefinitionRevision.id)
            )
        )

    v3 = _publish(factory, lock=3)

    assert isinstance(v3, PublishedRelease)
    assert v3.release.version_number == 3
    assert v3.changed_agent_keys == ("architect",)
    assert v3.mappings["architect"].agent_definition_revision_id == v1_architect_id
    assert v3.mappings["architect"].reused is True
    with factory() as db:
        architect_revisions_after = list(
            db.scalars(
                select(AgentDefinitionRevision.id)
                .where(AgentDefinitionRevision.agent_key == "architect")
                .order_by(AgentDefinitionRevision.id)
            )
        )
    assert architect_revisions_after == architect_revisions_before
    assert architect_revisions_after == [
        v1_architect_id,
        v2.mappings["architect"].agent_definition_revision_id,
    ]


def test_publication_lock_statement_sequence(postgres_engine):
    factory = _factory(postgres_engine)
    _save_prompt(factory, "architect", "\n\nTune A.", lock=0)
    statements: list[str] = []

    @event.listens_for(postgres_engine, "after_cursor_execute")
    def _record(_conn, _cursor, statement, _params, _context, _executemany):
        if threading.current_thread().name == "publisher":
            statements.append(_normalized(statement))

    try:
        result = _run_named("publisher", lambda: _publish(factory, lock=1))
    finally:
        event.remove(postgres_engine, "after_cursor_execute", _record)

    assert isinstance(result, PublishedRelease)
    locking = [
        (index, statement)
        for index, statement in enumerate(statements)
        if " FOR UPDATE" in statement or " FOR SHARE" in statement
    ]
    assert len(locking) == 2, locking
    (parent_index, parent), (agents_index, agents) = locking
    assert parent_index == 0, "the parent lock must be the publisher's first statement"
    assert parent.endswith("FOR UPDATE OF GRAPH_RELEASE, GRAPH_DRAFT")
    assert "FROM GRAPH_RELEASE JOIN GRAPH_DRAFT" in parent
    assert "WHERE GRAPH_RELEASE.EFFECTIVE_TO IS NULL" in parent
    assert agents_index == 1, "the draft-agent lock must follow the parent lock"
    assert "FROM GRAPH_DRAFT_AGENT" in agents
    assert "ORDER BY GRAPH_DRAFT_AGENT.AGENT_KEY" in agents
    assert agents.endswith("FOR UPDATE")


def test_published_history_rejects_reopen_and_second_close(postgres_engine):
    factory = _factory(postgres_engine)
    _save_prompt(factory, "architect", "\n\nTune A.", lock=0)
    result = _publish(factory, lock=1)
    assert isinstance(result, PublishedRelease)
    v1 = _release(factory, 1)

    for statement in (
        "UPDATE graph_release SET effective_to = NULL WHERE id = :id",
        "UPDATE graph_release SET effective_to = now() + interval '1 hour' "
        "WHERE id = :id",
    ):
        with pytest.raises(
            IntegrityError,
            match="graph_release rows are immutable except for their first close",
        ):
            with postgres_engine.begin() as conn:
                conn.execute(text(statement), {"id": v1.id})

    v1_after = _release(factory, 1)
    v2 = _release(factory, 2)
    assert v1_after.effective_to == v1.effective_to == v2.effective_from


def test_parent_lock_statement_takes_release_before_draft(postgres_engine):
    """Correction 13 sub-item 2: the L0 statement holds the release while it waits.

    Bounded on failure: the holder is released inside the executor block (so an
    assertion never leaves the publisher waiting on it forever), and the
    publisher's transaction carries ``lock_timeout``.
    """
    factory = _factory(postgres_engine)
    _save_prompt(factory, "architect", "\n\nTune A.", lock=0)
    v1 = _release(factory, 1)
    pids: dict[str, int] = {}
    attempted = threading.Event()

    class ObservedGraphConfiguration(GraphConfiguration):
        def _lock_current_parents(self, session, *, exclusive):
            session.execute(text(f"SET LOCAL lock_timeout = '{int(_WAIT_SECONDS)}s'"))
            pids[threading.current_thread().name] = session.scalar(
                text("SELECT pg_backend_pid()")
            )
            attempted.set()
            return super()._lock_current_parents(session, exclusive=exclusive)

    holder = postgres_engine.connect()
    holder_transaction = holder.begin()
    try:
        holder_pid = holder.execute(text("SELECT pg_backend_pid()")).scalar()
        assert holder.execute(text("SELECT id FROM graph_draft FOR SHARE")).all() == [
            (1,)
        ]
        with ThreadPoolExecutor(max_workers=1) as pool:

            def _publisher():
                threading.current_thread().name = "publisher"
                return _publish(factory, lock=1, service=ObservedGraphConfiguration())

            future = pool.submit(_publisher)
            try:
                assert attempted.wait(timeout=_WAIT_SECONDS), (
                    "publisher never reached L0"
                )
                assert _await_blocked_by(
                    postgres_engine,
                    waiter_pid=pids["publisher"],
                    blocker_pid=holder_pid,
                )
                with postgres_engine.connect() as third:
                    skipped = third.execute(
                        text(
                            "SELECT id FROM graph_release WHERE effective_to IS NULL "
                            "FOR UPDATE SKIP LOCKED"
                        )
                    ).all()
                    third.rollback()
                assert skipped == [], (
                    "the waiting L0 statement must already hold the release"
                )
                assert not future.done()
                holder_transaction.commit()
            finally:
                # Release the holder before the executor joins the publisher.
                if holder_transaction.is_active:
                    holder_transaction.rollback()
            result = future.result(timeout=_WAIT_SECONDS * 2)
    finally:
        if holder_transaction.is_active:
            holder_transaction.rollback()
        holder.close()

    assert isinstance(result, PublishedRelease)
    assert result.release.version_number == 2
    assert result.previous_release_id == v1.id


def test_shared_parent_lock_names_release_before_draft(postgres_engine):
    """Concern-1 ruling (a): PostgreSQL takes L0 row locks in ``OF`` list order.

    The ``FOR SHARE`` path (``read_workbench``, bootstrap, #267/#268 readers) must
    render ``OF graph_release, graph_draft`` in that order, like the exclusive one.
    """
    factory = _factory(postgres_engine)
    statements: list[str] = []

    @event.listens_for(postgres_engine, "after_cursor_execute")
    def _record(_conn, _cursor, statement, _params, _context, _executemany):
        if threading.current_thread().name == "reader":
            statements.append(_normalized(statement))

    def _read():
        with factory() as db:
            snapshot = GraphConfiguration().read_workbench(db)
            db.rollback()
            return snapshot

    try:
        snapshot = _run_named("reader", _read)
    finally:
        event.remove(postgres_engine, "after_cursor_execute", _record)

    assert snapshot.active_release.version_number == 1
    locking = [s for s in statements if " FOR SHARE" in s or " FOR UPDATE" in s]
    assert len(locking) == 1, locking
    assert statements[0] == locking[0], "the shared parent lock is the first statement"
    assert locking[0].endswith("FOR SHARE OF GRAPH_RELEASE, GRAPH_DRAFT")


# ---------------------------------------------------------------------------
# Task 2: the publication handoff, and writer / reader / publisher races
# ---------------------------------------------------------------------------

_PARENT_HANDOFF_DIAGNOSIS = "graph configuration parent snapshot is inconsistent"


def _is_parent_lock(normalized: str) -> bool:
    return (
        "FOR UPDATE" in normalized
        and "GRAPH_RELEASE" in normalized
        and "GRAPH_DRAFT" in normalized
    )


class _RaceObservedGraphConfiguration(GraphConfiguration):
    """Records each thread's backend PID *before* its L0 statement (Correction 5).

    ``SET LOCAL lock_timeout`` bounds every L0 wait, so a broken ordering goes RED
    instead of hanging the run.
    """

    def __init__(self) -> None:
        super().__init__()
        self.pids: dict[str, int] = {}
        self.attempted: dict[str, threading.Event] = {}
        self._guard = threading.Lock()

    def attempted_event(self, name: str) -> threading.Event:
        with self._guard:
            return self.attempted.setdefault(name, threading.Event())

    def _record_pid(self, session) -> None:
        session.execute(text(f"SET LOCAL lock_timeout = '{int(_WAIT_SECONDS)}s'"))
        name = threading.current_thread().name
        pid = session.scalar(text("SELECT pg_backend_pid()"))
        with self._guard:
            self.pids.setdefault(name, pid)
        self.attempted_event(name).set()

    def _take_bootstrap_lock(self, session):
        self._record_pid(session)
        return super()._take_bootstrap_lock(session)

    def _lock_current_parents(self, session, *, exclusive):
        self._record_pid(session)
        return super()._lock_current_parents(session, exclusive=exclusive)


def _named(name, fn):
    def _call():
        threading.current_thread().name = name
        return fn()

    return _call


def _race(
    engine,
    service: _RaceObservedGraphConfiguration,
    *,
    blocker: tuple[str, object],
    waiter: tuple[str, object],
    pause_when=_is_parent_lock,
):
    """Pause ``blocker`` after its first matching statement; prove ``waiter`` queues.

    Returns ``(blocker_future, waiter_future)`` after both finish.  The blocker is
    released in an inner ``finally`` before the executor joins, so an assertion
    never leaves a thread waiting forever.
    """
    blocker_name, blocker_fn = blocker
    waiter_name, waiter_fn = waiter
    paused = threading.Event()
    release = threading.Event()
    fired: list[str] = []

    @event.listens_for(engine, "after_cursor_execute")
    def _pause(_conn, _cursor, statement, _params, _context, _executemany):
        normalized = _normalized(statement)
        if (
            threading.current_thread().name == blocker_name
            and not fired
            and pause_when(normalized)
        ):
            fired.append(normalized)
            paused.set()
            assert release.wait(timeout=_WAIT_SECONDS), "test never released blocker"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            blocker_future = pool.submit(_named(blocker_name, blocker_fn))
            waiter_future = None
            try:
                assert paused.wait(timeout=_WAIT_SECONDS), "blocker never paused"
                waiter_future = pool.submit(_named(waiter_name, waiter_fn))
                assert service.attempted_event(waiter_name).wait(
                    timeout=_WAIT_SECONDS
                ), "waiter never reached its lock"
                assert _await_blocked_by(
                    engine,
                    waiter_pid=service.pids[waiter_name],
                    blocker_pid=service.pids[blocker_name],
                ), f"{waiter_name} was never blocked by {blocker_name}"
                assert not waiter_future.done()
            finally:
                release.set()
            done = [blocker_future.exception(timeout=_WAIT_SECONDS * 2)]
            if waiter_future is not None:
                done.append(waiter_future.exception(timeout=_WAIT_SECONDS * 2))
    finally:
        event.remove(engine, "after_cursor_execute", _pause)
    assert len(fired) == 1
    return blocker_future, waiter_future


def _publish_as(service, factory, *, lock, actor="publisher@example.com", note="Tune"):
    def _call():
        with factory() as db:
            return service.publish_draft(
                db,
                expected_lock_version=lock,
                release_note=note,
                actor=actor,
                evidence_gate=_NoEvidenceGate(),
            )

    return _call


def _release_set(factory) -> set[tuple[int, int, bool]]:
    with factory() as db:
        return {
            (row.id, row.version_number, row.effective_to is None)
            for row in db.scalars(select(GraphRelease))
        }


def _revision_ids(factory) -> set[int]:
    with factory() as db:
        return set(db.scalars(select(AgentDefinitionRevision.id)))


def _draft_role(factory, agent_key) -> tuple[object, ...]:
    with factory() as db:
        row = db.scalar(
            select(GraphDraftAgent).where(GraphDraftAgent.agent_key == agent_key)
        )
        return (row.candidate_hash, row.prompt_text)


def test_publication_first_then_draft_save_gets_stale_not_500(postgres_engine):
    factory = _factory(postgres_engine)
    lock = _save_prompt(factory, "architect", "\n\nTune A.", lock=0).draft.lock_version
    v1 = _release(factory, 1)
    with factory() as db:
        snap = GraphConfiguration().read_workbench(db)
        db.rollback()
    builder = next(n for n in snap.nodes if n.agent_key == "builder").draft.content
    builder_before = _draft_role(factory, "builder")
    service = _RaceObservedGraphConfiguration()

    def _save():
        with factory() as db:
            return service.save_editable_model_draft(
                db,
                agent_key="builder",
                expected_lock_version=lock,
                actor="editor@example.com",
                candidate=EditableModelDraft(
                    prompt_text=builder.prompt_text + "\n\nLate edit.",
                    endpoint_name=builder.model.endpoint_name,
                    temperature=float(builder.model.temperature),
                    max_tokens=builder.model.max_tokens,
                    top_p=float(builder.model.top_p),
                ),
            )

    published, saved = _race(
        postgres_engine,
        service,
        blocker=("publisher", _publish_as(service, factory, lock=lock)),
        waiter=("saver", _save),
    )

    result = published.result()
    assert isinstance(result, PublishedRelease)
    assert result.release.version_number == 2
    assert result.previous_release_id == v1.id
    conflict = saved.result()
    assert isinstance(conflict, DraftSaveConflict)
    assert conflict.expected_lock_version == lock
    assert conflict.current_lock_version == lock + 1
    assert conflict.server.draft.base_release_id == result.release.release_id
    assert conflict.server.draft.base_version_number == 2
    assert conflict.server.draft.lock_version == lock + 1
    assert _draft_role(factory, "builder") == builder_before


def test_draft_save_first_then_publication_is_stale(postgres_engine):
    factory = _factory(postgres_engine)
    lock = _save_prompt(factory, "architect", "\n\nTune A.", lock=0).draft.lock_version
    v1 = _release(factory, 1)
    with factory() as db:
        snap = GraphConfiguration().read_workbench(db)
        db.rollback()
    builder = next(n for n in snap.nodes if n.agent_key == "builder").draft.content
    revisions_before = _revision_ids(factory)
    service = _RaceObservedGraphConfiguration()

    def _save():
        with factory() as db:
            return service.save_editable_model_draft(
                db,
                agent_key="builder",
                expected_lock_version=lock,
                actor="editor@example.com",
                candidate=EditableModelDraft(
                    prompt_text=builder.prompt_text + "\n\nWinning edit.",
                    endpoint_name=builder.model.endpoint_name,
                    temperature=float(builder.model.temperature),
                    max_tokens=builder.model.max_tokens,
                    top_p=float(builder.model.top_p),
                ),
            )

    saved, published = _race(
        postgres_engine,
        service,
        blocker=("draft-winner", _save),
        waiter=("publisher", _publish_as(service, factory, lock=lock)),
    )

    save_result = saved.result()
    assert isinstance(save_result, DraftSaveResult)
    assert save_result.draft.lock_version == lock + 1
    conflict = published.result()
    assert conflict == PublicationConflict(
        expected_lock_version=lock,
        current_lock_version=lock + 1,
        active_release_id=v1.id,
        active_version_number=1,
        draft=conflict.draft,
    )
    assert conflict.draft.lock_version == lock + 1
    assert conflict.draft.base_release_id == v1.id
    assert _release_set(factory) == {(v1.id, 1, True)}
    assert _revision_ids(factory) == revisions_before


def test_publication_first_then_workbench_read_sees_new_release(postgres_engine):
    factory = _factory(postgres_engine)
    lock = _save_prompt(factory, "architect", "\n\nTune A.", lock=0).draft.lock_version
    service = _RaceObservedGraphConfiguration()

    def _read():
        with factory() as db:
            snapshot = service.read_workbench(db)
            db.rollback()
            return snapshot

    published, read = _race(
        postgres_engine,
        service,
        blocker=("publisher", _publish_as(service, factory, lock=lock)),
        waiter=("reader", _read),
    )

    result = published.result()
    assert isinstance(result, PublishedRelease)
    snapshot = read.result()
    assert snapshot.active_release.release_id == result.release.release_id
    assert snapshot.active_release.version_number == 2
    assert snapshot.draft.base_release_id == result.release.release_id
    assert snapshot.draft.lock_version == lock + 1
    assert [node.changed for node in snapshot.nodes] == [False] * len(snapshot.nodes)


@pytest.mark.parametrize("winner", ["alpha", "beta"])
def test_two_publishers_one_winner_one_exact_stale_conflict(postgres_engine, winner):
    factory = _factory(postgres_engine)
    lock = _save_prompt(factory, "architect", "\n\nTune A.", lock=0).draft.lock_version
    v1 = _release(factory, 1)
    revisions_before = _revision_ids(factory)
    loser = "beta" if winner == "alpha" else "alpha"
    service = _RaceObservedGraphConfiguration()

    won, lost = _race(
        postgres_engine,
        service,
        blocker=(
            "publisher-winner",
            _publish_as(
                service, factory, lock=lock, actor=f"{winner}@example.com", note=winner
            ),
        ),
        waiter=(
            "publisher-loser",
            _publish_as(
                service, factory, lock=lock, actor=f"{loser}@example.com", note=loser
            ),
        ),
    )

    result = won.result()
    assert isinstance(result, PublishedRelease)
    assert result.release.version_number == 2
    assert result.previous_release_id == v1.id
    assert result.release.published_by == f"{winner}@example.com"
    assert result.release.release_note == winner
    v2_id = result.release.release_id
    conflict = lost.result()
    assert conflict == PublicationConflict(
        expected_lock_version=lock,
        current_lock_version=lock + 1,
        active_release_id=v2_id,
        active_version_number=2,
        draft=conflict.draft,
    )
    assert conflict.draft.base_release_id == v2_id
    assert _release_set(factory) == {(v1.id, 1, False), (v2_id, 2, True)}
    assert len(_mappings(factory, v2_id)) == len(GRAPH_V1_AGENT_KEYS) == 7
    assert _revision_ids(factory) == revisions_before | {
        mapping.agent_definition_revision_id for mapping in result.mappings.values()
    }


def test_sequential_retry_after_success_is_stale(postgres_engine):
    factory = _factory(postgres_engine)
    lock = _save_prompt(factory, "architect", "\n\nTune A.", lock=0).draft.lock_version
    v1 = _release(factory, 1)
    first = _publish(factory, lock=lock)
    assert isinstance(first, PublishedRelease)
    revisions_after_first = _revision_ids(factory)

    retry = _publish(factory, lock=lock)

    assert retry == PublicationConflict(
        expected_lock_version=lock,
        current_lock_version=lock + 1,
        active_release_id=first.release.release_id,
        active_version_number=2,
        draft=retry.draft,
    )
    assert _release_set(factory) == {
        (v1.id, 1, False),
        (first.release.release_id, 2, True),
    }
    assert _revision_ids(factory) == revisions_after_first


def test_stale_publisher_after_intervening_save_is_conflict_not_v3(postgres_engine):
    """Correction 9: a stale request must never publish content it never previewed."""
    factory = _factory(postgres_engine)
    lock = _save_prompt(factory, "architect", "\n\nTune A.", lock=0).draft.lock_version
    v1 = _release(factory, 1)
    v2 = _publish(factory, lock=lock)
    assert isinstance(v2, PublishedRelease)
    _save_prompt(factory, "architect", "\n\nTune again.", lock=lock + 1)
    revisions_before = _revision_ids(factory)
    with factory() as db:
        current = GraphConfiguration().read_workbench(db).draft
        db.rollback()
    assert current.lock_version == lock + 2

    stale = _publish(factory, lock=lock)

    assert stale == PublicationConflict(
        expected_lock_version=lock,
        current_lock_version=lock + 2,
        active_release_id=v2.release.release_id,
        active_version_number=2,
        draft=current,
    )
    assert _release_set(factory) == {
        (v1.id, 1, False),
        (v2.release.release_id, 2, True),
    }
    assert _revision_ids(factory) == revisions_before


# ---------------------------------------------------------------------------
# Correction 2: boot validation reads under one consistent parent lock
# ---------------------------------------------------------------------------

_MAPPING_READ_BACK = "SELECT GRAPH_RELEASE_AGENT.AGENT_KEY"
_BOOT_RELEASE_LIST = "FROM GRAPH_RELEASE ORDER BY GRAPH_RELEASE.ID"


def _boot(service, factory):
    def _call():
        return service.bootstrap_v1(factory)

    return _call


def test_boot_validation_queued_behind_publication_sees_new_release(postgres_engine):
    factory = _factory(postgres_engine)
    lock = _save_prompt(factory, "architect", "\n\nTune A.", lock=0).draft.lock_version
    v1 = _release(factory, 1)
    service = _RaceObservedGraphConfiguration()

    published, booted = _race(
        postgres_engine,
        service,
        blocker=("publisher", _publish_as(service, factory, lock=lock)),
        waiter=("boot", _boot(service, factory)),
        pause_when=lambda normalized: _MAPPING_READ_BACK in normalized,
    )

    result = published.result()
    assert isinstance(result, PublishedRelease)
    assert result.release.version_number == 2
    assert result.previous_release_id == v1.id
    assert booted.result() == BootstrapResult(False, result.release.release_id, 2)


def test_publication_during_boot_validation_waits_for_boot(postgres_engine):
    factory = _factory(postgres_engine)
    lock = _save_prompt(factory, "architect", "\n\nTune A.", lock=0).draft.lock_version
    v1 = _release(factory, 1)
    service = _RaceObservedGraphConfiguration()
    fired: list[str] = []
    blocked: list[bool] = []
    publisher: dict[str, object] = {}

    with ThreadPoolExecutor(max_workers=2) as pool:

        @event.listens_for(postgres_engine, "after_cursor_execute")
        def _start_publisher(_conn, _cursor, statement, _params, _context, _many):
            normalized = _normalized(statement)
            if (
                threading.current_thread().name != "boot"
                or fired
                or _BOOT_RELEASE_LIST not in normalized
                or " FOR " in normalized
            ):
                return
            fired.append(normalized)
            publisher["future"] = pool.submit(
                _named("publisher", _publish_as(service, factory, lock=lock))
            )
            if service.attempted_event("publisher").wait(timeout=_WAIT_SECONDS):
                blocked.append(
                    _await_blocked_by(
                        postgres_engine,
                        waiter_pid=service.pids["publisher"],
                        blocker_pid=service.pids["boot"],
                    )
                )

        try:
            boot_future = pool.submit(_named("boot", _boot(service, factory)))
            boot_error = boot_future.exception(timeout=_WAIT_SECONDS * 3)
            publish_future = publisher.get("future")
            publish_error = (
                None
                if publish_future is None
                else publish_future.exception(timeout=_WAIT_SECONDS * 2)
            )
        finally:
            event.remove(postgres_engine, "after_cursor_execute", _start_publisher)

    assert boot_error is None, boot_error
    assert boot_future.result() == BootstrapResult(False, v1.id, 1)
    assert len(fired) == 1
    assert blocked == [True], "the publisher must queue behind boot validation"
    assert publish_error is None, publish_error
    result = publish_future.result()
    assert isinstance(result, PublishedRelease)
    assert result.release.version_number == 2
    assert result.previous_release_id == v1.id
