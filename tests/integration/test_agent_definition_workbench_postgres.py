from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

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
from src.services.graph_configuration import (
    DraftSaveConflict,
    DraftSaveResult,
    EditableModelDraft,
    GraphConfiguration,
)
from src.services.graph_configuration_content import definition_content_from_row
from src.services.graph_definition_manifest import (
    GRAPH_V1_AGENT_KEYS,
    DefinitionContent,
    definition_content_hash,
)

pytestmark = pytest.mark.postgres


def _editable_candidate(
    content: DefinitionContent, *, prompt_text: str
) -> EditableModelDraft:
    return EditableModelDraft(
        prompt_text=prompt_text,
        endpoint_name=content.model.endpoint_name,
        temperature=float(content.model.temperature),
        max_tokens=content.model.max_tokens,
        top_p=float(content.model.top_p),
    )


def _immutable_graph_artifacts(factory) -> dict[str, list[tuple[object, ...]]]:
    with factory() as session:
        return {
            "revisions": list(
                session.execute(
                    select(
                        AgentDefinitionRevision.id,
                        AgentDefinitionRevision.agent_key,
                        AgentDefinitionRevision.content_hash,
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


@pytest.mark.parametrize(
    ("winner_key", "loser_key"),
    [("architect", "builder"), ("builder", "architect")],
)
def test_two_writers_serialize_at_postgresql_locks_and_rollback_loser(
    postgres_engine, winner_key, loser_key
) -> None:
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    GraphConfiguration().bootstrap_v1(factory)
    service = GraphConfiguration()

    with factory.begin() as session:
        before = service.read_workbench(session)
    original_by_key = {
        node.agent_key: node.draft.content
        for node in before.nodes
        if node.execution_kind == "model"
    }
    winner_candidate = _editable_candidate(
        original_by_key[winner_key],
        prompt_text=original_by_key[winner_key].prompt_text + "\n\nWinner edit.",
    )
    expected_winner_content = original_by_key[winner_key].model_copy(
        update={"prompt_text": winner_candidate.prompt_text}
    )
    loser_candidate = _editable_candidate(
        original_by_key[loser_key],
        prompt_text=original_by_key[loser_key].prompt_text + "\n\nLoser edit.",
    )
    before_artifacts = _immutable_graph_artifacts(factory)
    winner_parent_locked = threading.Event()
    release_winner = threading.Event()
    loser_attempted = threading.Event()
    pids: dict[str, int] = {}
    outcomes: dict[str, DraftSaveResult | DraftSaveConflict[EditableModelDraft]] = {}
    sql_statements: list[str] = []
    guard = threading.Lock()

    class ObservedGraphConfiguration(GraphConfiguration):
        def _lock_current_parents(self, session, *, exclusive):
            pid = session.scalar(text("SELECT pg_backend_pid()"))
            with guard:
                pids[threading.current_thread().name] = pid
            if threading.current_thread().name == "draft-loser":
                loser_attempted.set()
            return super()._lock_current_parents(session, exclusive=exclusive)

    observed_service = ObservedGraphConfiguration()

    @event.listens_for(postgres_engine, "after_cursor_execute")
    def _record_sql_and_pause_winner(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        normalized = " ".join(statement.upper().split())
        with guard:
            sql_statements.append(normalized)
        if (
            threading.current_thread().name == "draft-winner"
            and "FOR UPDATE" in normalized
            and "GRAPH_RELEASE" in normalized
            and "GRAPH_DRAFT" in normalized
        ):
            winner_parent_locked.set()
            assert release_winner.wait(timeout=20), "test never released winning writer"

    def _save(name, agent_key, candidate, actor) -> None:
        threading.current_thread().name = name
        with factory() as session:
            outcomes[name] = observed_service.save_editable_model_draft(
                session,
                agent_key=agent_key,
                expected_lock_version=0,
                candidate=candidate,
                actor=actor,
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            winner = pool.submit(
                _save, "draft-winner", winner_key, winner_candidate, "winner-admin"
            )
            assert winner_parent_locked.wait(timeout=10), "winner never acquired parent lock"
            loser = pool.submit(
                _save, "draft-loser", loser_key, loser_candidate, "loser-admin"
            )
            assert loser_attempted.wait(timeout=10), "loser never attempted the parent lock"

            deadline = time.monotonic() + 10
            observed_waiter = False
            while time.monotonic() < deadline:
                with guard:
                    loser_pid = pids.get("draft-loser")
                if loser_pid is not None:
                    with postgres_engine.connect() as observer:
                        observed_waiter = bool(
                            observer.scalar(
                                text(
                                    "SELECT EXISTS ("
                                    " SELECT 1 FROM pg_stat_activity"
                                    " WHERE pid = :loser_pid"
                                    " AND wait_event_type = 'Lock'"
                                    ")"
                                ),
                                {"loser_pid": loser_pid},
                            )
                        )
                    if observed_waiter:
                        break
                time.sleep(0.02)

            with guard:
                winner_pid = pids.get("draft-winner")
                loser_pid = pids.get("draft-loser")
            assert winner_pid is not None and loser_pid is not None
            assert winner_pid != loser_pid
            assert observed_waiter is True
            release_winner.set()
            winner.result(timeout=20)
            loser.result(timeout=20)
    finally:
        release_winner.set()
        event.remove(postgres_engine, "after_cursor_execute", _record_sql_and_pause_winner)

    winner_outcome = outcomes["draft-winner"]
    loser_outcome = outcomes["draft-loser"]
    assert isinstance(winner_outcome, DraftSaveResult)
    assert winner_outcome.changed is True
    assert isinstance(loser_outcome, DraftSaveConflict)
    assert loser_outcome.expected_lock_version == 0
    assert loser_outcome.current_lock_version == 1
    assert loser_outcome.client_candidate == loser_candidate
    assert set(loser_outcome.server.definitions) == set(GRAPH_V1_AGENT_KEYS)
    assert (
        loser_outcome.server.definitions[winner_key].content.prompt_text
        == winner_candidate.prompt_text
    )
    assert loser_outcome.server.definitions[loser_key].content == original_by_key[loser_key]
    assert any(
        "FOR UPDATE" in statement
        and "GRAPH_RELEASE" in statement
        and "GRAPH_DRAFT" in statement
        for statement in sql_statements
    )
    assert any(
        "FOR UPDATE" in statement and "FROM GRAPH_DRAFT_AGENT" in statement
        for statement in sql_statements
    )
    assert any("CURRENT_TIMESTAMP" in statement for statement in sql_statements)

    with factory.begin() as session:
        after = service.read_workbench(session)
    after_by_key = {
        node.agent_key: node.draft
        for node in after.nodes
        if node.execution_kind == "model"
    }
    assert after.draft.lock_version == 1
    assert after.draft.updated_by == "winner-admin"
    assert after.draft.updated_at.tzinfo is not None
    assert winner_outcome.draft == after.draft
    assert after.draft.updated_at == winner_outcome.draft.updated_at
    assert after_by_key[winner_key].content == expected_winner_content
    assert after_by_key[winner_key].candidate_hash == definition_content_hash(
        expected_winner_content
    )
    assert after_by_key[loser_key].content == original_by_key[loser_key]
    assert set(after_by_key) == set(GRAPH_V1_AGENT_KEYS)
    after_artifacts = _immutable_graph_artifacts(factory)
    assert {
        agent_key for _release_id, agent_key, _revision_id in after_artifacts["release_mappings"]
    } == set(GRAPH_V1_AGENT_KEYS)
    assert len(after_artifacts["release_mappings"]) == 7
    assert after_artifacts == before_artifacts
    assert loser_outcome.server.draft == after.draft
    assert loser_outcome.server.definitions == after_by_key


def test_postgresql_flush_failure_rolls_back_draft_audit_and_immutable_artifacts(
    postgres_engine,
) -> None:
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    service = GraphConfiguration()
    service.bootstrap_v1(factory)
    with factory.begin() as session:
        before = service.read_workbench(session)
    before_by_key = {
        node.agent_key: node.draft
        for node in before.nodes
        if node.execution_kind == "model"
    }
    before_artifacts = _immutable_graph_artifacts(factory)

    with factory() as session:
        def _fail_flush(_session, _context, _instances) -> None:
            raise RuntimeError("forced PostgreSQL flush failure")

        event.listen(session, "before_flush", _fail_flush, once=True)
        with pytest.raises(RuntimeError, match="forced PostgreSQL flush failure"):
            service.save_editable_model_draft(
                session,
                agent_key="architect",
                expected_lock_version=0,
                candidate=_editable_candidate(
                    before_by_key["architect"].content,
                    prompt_text="must roll back in PostgreSQL",
                ),
                actor="rollback-admin",
            )

    with factory.begin() as session:
        after = service.read_workbench(session)
    after_by_key = {
        node.agent_key: node.draft
        for node in after.nodes
        if node.execution_kind == "model"
    }
    assert after.draft == before.draft
    assert after_by_key == before_by_key
    assert _immutable_graph_artifacts(factory) == before_artifacts


def test_workbench_parent_share_lock_prevents_mixed_read_committed_snapshot(
    postgres_engine,
):
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    GraphConfiguration().bootstrap_v1(factory)

    parent_locked = threading.Event()
    release_reader = threading.Event()
    writer_started = threading.Event()
    writer_has_parents = threading.Event()
    pids: dict[str, int] = {}
    pids_guard = threading.Lock()

    @event.listens_for(postgres_engine, "after_cursor_execute")
    def _pause_after_parent_lock(
        connection, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        normalized = " ".join(statement.upper().split())
        if (
            threading.current_thread().name == "workbench-reader"
            and "FOR SHARE" in normalized
            and "GRAPH_RELEASE" in normalized
            and "GRAPH_DRAFT" in normalized
        ):
            with pids_guard:
                pids["reader"] = connection.execute(
                    text("SELECT pg_backend_pid()")
                ).scalar_one()
            parent_locked.set()
            assert release_reader.wait(timeout=20), "test never released parent read lock"

    def _read_snapshot():
        threading.current_thread().name = "workbench-reader"
        with factory.begin() as session:
            return GraphConfiguration().read_workbench(session)

    def _write_candidate():
        threading.current_thread().name = "workbench-writer"
        with factory.begin() as session:
            with pids_guard:
                pids["writer"] = session.scalar(text("SELECT pg_backend_pid()"))
            writer_started.set()
            _release, draft_parent = session.execute(
                select(GraphRelease, GraphDraft)
                .select_from(GraphRelease)
                .join(GraphDraft, GraphDraft.id == 1)
                .where(GraphRelease.effective_to.is_(None))
                .with_for_update(of=(GraphRelease, GraphDraft))
            ).one()
            writer_has_parents.set()
            draft = session.scalar(
                select(GraphDraftAgent).where(
                    GraphDraftAgent.agent_key == "architect"
                )
            )
            content = definition_content_from_row(draft).model_copy(
                update={"prompt_text": draft.prompt_text + "\n\nConcurrent edit."}
            )
            draft.prompt_text = content.prompt_text
            draft.candidate_hash = definition_content_hash(content)
            draft_parent.lock_version += 1

    with ThreadPoolExecutor(max_workers=2) as pool:
        reader = pool.submit(_read_snapshot)
        assert parent_locked.wait(timeout=10), "reader never acquired parent share locks"
        writer = pool.submit(_write_candidate)
        assert writer_started.wait(timeout=10), "writer did not attempt the parent lock"

        deadline = time.monotonic() + 10
        observed_waiter = False
        while time.monotonic() < deadline:
            with pids_guard:
                reader_pid = pids.get("reader")
                writer_pid = pids.get("writer")
            if reader_pid is not None and writer_pid is not None:
                with postgres_engine.connect() as observer:
                    observed_waiter = bool(
                        observer.scalar(
                            text(
                                "SELECT EXISTS ("
                                " SELECT 1 FROM pg_stat_activity"
                                " WHERE pid = :writer_pid"
                                " AND wait_event_type = 'Lock'"
                                ")"
                            ),
                            {"writer_pid": writer_pid},
                        )
                    )
                if observed_waiter:
                    break
            time.sleep(0.02)

        assert reader_pid != writer_pid
        assert observed_waiter is True
        assert writer_has_parents.is_set() is False
        release_reader.set()
        before = reader.result(timeout=20)
        writer.result(timeout=20)

    before_architect = before.nodes[0]
    assert before.draft.lock_version == 0
    assert before_architect.changed is False

    with factory.begin() as session:
        after = GraphConfiguration().read_workbench(session)
    after_architect = after.nodes[0]
    assert after.draft.lock_version == 1
    assert after_architect.changed is True
    assert after_architect.draft.candidate_hash != before_architect.draft.candidate_hash
