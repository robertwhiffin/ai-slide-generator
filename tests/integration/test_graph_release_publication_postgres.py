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
    DraftSaveResult,
    EditableModelDraft,
    GraphConfiguration,
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
    """Correction 13 sub-item 2: the L0 statement holds the release while it waits."""
    factory = _factory(postgres_engine)
    _save_prompt(factory, "architect", "\n\nTune A.", lock=0)
    v1 = _release(factory, 1)
    pids: dict[str, int] = {}
    attempted = threading.Event()

    class ObservedGraphConfiguration(GraphConfiguration):
        def _lock_current_parents(self, session, *, exclusive):
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
            assert attempted.wait(timeout=_WAIT_SECONDS), "publisher never reached L0"
            assert _await_blocked_by(
                postgres_engine, waiter_pid=pids["publisher"], blocker_pid=holder_pid
            )
            with postgres_engine.connect() as third:
                skipped = third.execute(
                    text(
                        "SELECT id FROM graph_release WHERE effective_to IS NULL "
                        "FOR UPDATE SKIP LOCKED"
                    )
                ).all()
                third.rollback()
            assert skipped == [], "the waiting L0 statement must already hold the release"
            assert not future.done()
            holder_transaction.commit()
            result = future.result(timeout=_WAIT_SECONDS)
    finally:
        if holder_transaction.is_active:
            holder_transaction.rollback()
        holder.close()

    assert isinstance(result, PublishedRelease)
    assert result.release.version_number == 2
    assert result.previous_release_id == v1.id
