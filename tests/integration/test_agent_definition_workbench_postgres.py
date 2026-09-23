from __future__ import annotations

import dataclasses
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session, sessionmaker

from src.api.schemas.agent_definitions import (
    DraftDefinitionResponse,
    DraftFieldErrorResponse,
    DraftSaveConflictResponse,
    DraftSaveConflictServerResponse,
    DraftSaveSuccessResponse,
    DraftValidationErrorResponse,
)
from src.core.prompt_modules import UNTRUSTED_DATA_NOTICE
from src.core.skills.build_reviewer import BUILD_REVIEWER_CRITERIA_STAGE
from src.database.models.graph_configuration import (
    AgentDefinitionRevision,
    GraphDraft,
    GraphDraftAgent,
    GraphRelease,
    GraphReleaseAgent,
)
from src.services.graph_configuration import (
    DraftContentRejected,
    DraftLegacyPromptSource,
    DraftSaveConflict,
    DraftSaveResult,
    EditableModelDraft,
    GraphConfiguration,
)
from src.services.graph_configuration_content import (
    definition_content_from_row,
    definition_content_values,
)
from src.services.graph_definition_manifest import (
    GRAPH_V1_AGENT_KEYS,
    AssemblyRulesV2,
    DefinitionContent,
    definition_content_hash,
)
from src.services.prompt_assembler import (
    ROLE_UNTRUSTED_DATA_NOTICE,
    V2_PROTECTED_ASSEMBLY_IDENTITY,
    PromptAssembler,
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
    winner_parent_locked = threading.Event()
    release_winner = threading.Event()
    loser_attempted = threading.Event()
    pids: dict[str, int] = {}
    outcomes: dict[str, DraftSaveResult | DraftSaveConflict[EditableModelDraft]] = {}
    sql_statements: list[str] = []
    returned_timestamps: dict[str, object] = {}
    guard = threading.Lock()

    class TimestampCapturingSession(Session):
        def scalar(self, statement, params=None, **kwargs):
            value = super().scalar(statement, params, **kwargs)
            if "CURRENT_TIMESTAMP" in str(statement).upper():
                with guard:
                    returned_timestamps[threading.current_thread().name] = value
            return value

    factory = sessionmaker(
        bind=postgres_engine,
        class_=TimestampCapturingSession,
        expire_on_commit=False,
    )
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
    database_timestamp = returned_timestamps["draft-winner"]
    assert database_timestamp == winner_outcome.draft.updated_at
    assert database_timestamp == after.draft.updated_at
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


# ---------------------------------------------------------------------------
# #265 declarative prompt assembly over real PostgreSQL: the locked persisted
# v1 -> v2 transition, read-only legacy source recovery, and two real
# two-session races that cross the shared draft lock.
# ---------------------------------------------------------------------------


AFFECTED_ROLES = ("data_analyst", "build_reviewer")
MANUAL_RESOLUTION_TUPLE = (
    (
        "prompt_text",
        "legacy_prompt_manual_resolution_required",
        "Legacy protected prompt content was edited. Restore the exact Graph Version 1 "
        "prompt before upgrading, then reapply authored edits.",
    ),
)
ALREADY_CURRENT_TUPLE = (
    (
        "protected_assembly.version",
        "already_current",
        "Protected assembly is already current.",
    ),
)


@dataclasses.dataclass(frozen=True)
class _Context:
    design_system_active: bool


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


def _published_revision(factory, agent_key: str) -> tuple[DefinitionContent, str, int]:
    with factory() as session:
        row = session.scalar(
            select(AgentDefinitionRevision).where(
                AgentDefinitionRevision.agent_key == agent_key
            )
        )
        assert row is not None
        return definition_content_from_row(row), row.content_hash, row.id


def _draft_meta(factory) -> tuple[int, str, object]:
    with factory() as session:
        row = session.get(GraphDraft, 1)
        assert row is not None
        return row.lock_version, row.updated_by, row.updated_at


def _reset_to_bootstrap(
    factory, agent_key: str, content: DefinitionContent, meta: tuple[int, str, object]
) -> None:
    """Restore exactly the bootstrap candidate row and shared draft audit state."""
    with factory.begin() as session:
        row = session.scalar(
            select(GraphDraftAgent).where(GraphDraftAgent.agent_key == agent_key)
        )
        assert row is not None
        for column_name, value in definition_content_values(content).items():
            setattr(row, column_name, value)
        row.candidate_hash = definition_content_hash(content)
        draft = session.get(GraphDraft, 1)
        draft.lock_version, draft.updated_by, draft.updated_at = meta


def _assert_authored_only_persisted_v2(
    factory, agent_key: str, transition
) -> None:
    reloaded, reloaded_hash = _stored_draft(factory, agent_key)
    displaced = (
        UNTRUSTED_DATA_NOTICE
        if agent_key == "data_analyst"
        else BUILD_REVIEWER_CRITERIA_STAGE
    )
    protected_stage_id = (
        "untrusted_data_notice"
        if agent_key == "data_analyst"
        else "build_reviewer_criteria"
    )
    rendered = (
        ROLE_UNTRUSTED_DATA_NOTICE[agent_key]
        if agent_key == "data_analyst"
        else BUILD_REVIEWER_CRITERIA_STAGE
    )
    assert reloaded.prompt_text == transition.target_authored_prompt
    assert displaced not in reloaded.prompt_text
    assert reloaded.assembly_rules == AssemblyRulesV2(format_version=2, custom_blocks=())
    assert reloaded.protected_assembly == V2_PROTECTED_ASSEMBLY_IDENTITY
    assert reloaded_hash == definition_content_hash(reloaded)

    assembled = PromptAssembler().assemble(
        definition=reloaded, payload={"x": 1}, context=_Context(False)
    )
    stage_ids = [stage.stage_id for stage in assembled.stages]
    expected_ids = ["authored_prompt"]
    if agent_key == "build_reviewer":
        expected_ids.append("build_reviewer_criteria")
    expected_ids.extend(
        [
            "slide_frame_constraints",
            "untrusted_data_notice",
            "untrusted_data_open",
            "runtime_payload",
            "untrusted_data_close",
            "structured_output_binding",
        ]
    )
    assert stage_ids == expected_ids
    assert stage_ids.count(protected_stage_id) == 1
    assert assembled.prompt.count(rendered) == 1
    assert assembled.stages[-1].stage_id == "structured_output_binding"
    assert assembled.stages[-1].contributes_to_prompt is False
    assert assembled.stages[-1].rendered_text not in assembled.prompt


@pytest.mark.parametrize("agent_key", AFFECTED_ROLES)
def test_locked_persisted_protected_assembly_transition_and_recovery(
    postgres_engine, agent_key, monkeypatch
) -> None:
    """Catches lossy persisted transitions, recovery writes, or published mutation."""
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    service = GraphConfiguration()
    service.bootstrap_v1(factory)
    transition = PromptAssembler().legacy_v1_prompt_source(agent_key=agent_key)

    bootstrap_content, bootstrap_hash = _stored_draft(factory, agent_key)
    bootstrap_meta = _draft_meta(factory)
    published_before = _published_revision(factory, agent_key)
    artifacts_before = _immutable_graph_artifacts(factory)
    assert bootstrap_content.agent_key == agent_key
    assert bootstrap_content.definition_version == transition.source_definition_version
    assert bootstrap_content.protected_assembly == transition.source_protected_assembly
    assert bootstrap_content.assembly_rules == transition.source_assembly_rules
    assert bootstrap_content.prompt_text == transition.source_composite_prompt
    assert bootstrap_hash == definition_content_hash(bootstrap_content)

    with factory() as session:
        upgraded = service.upgrade_draft_protected_assembly(
            session,
            agent_key=agent_key,
            expected_lock_version=0,
            actor="pg-upgrade",
        )
    assert isinstance(upgraded, DraftSaveResult)
    assert upgraded.changed is True
    _assert_authored_only_persisted_v2(factory, agent_key, transition)
    assert _draft_meta(factory)[:2] == (1, "pg-upgrade")
    assert _published_revision(factory, agent_key) == published_before
    assert _immutable_graph_artifacts(factory) == artifacts_before

    _reset_to_bootstrap(factory, agent_key, bootstrap_content, bootstrap_meta)
    assert _stored_draft(factory, agent_key) == (bootstrap_content, bootstrap_hash)
    edited_prompt = bootstrap_content.prompt_text + "!"
    with factory() as session:
        edited = service.save_editable_model_draft(
            session,
            agent_key=agent_key,
            expected_lock_version=0,
            candidate=_editable_candidate(bootstrap_content, prompt_text=edited_prompt),
            actor="pg-one-code-point",
        )
    assert isinstance(edited, DraftSaveResult)
    edited_content, edited_hash = _stored_draft(factory, agent_key)
    edited_meta = _draft_meta(factory)
    assert edited_content.prompt_text == edited_prompt

    with factory() as session, pytest.raises(DraftContentRejected) as caught:
        service.upgrade_draft_protected_assembly(
            session,
            agent_key=agent_key,
            expected_lock_version=1,
            actor="pg-manual-resolution",
        )
    assert _issue_tuples(caught) == MANUAL_RESOLUTION_TUPLE
    assert _stored_draft(factory, agent_key) == (edited_content, edited_hash)
    assert _draft_meta(factory) == edited_meta
    assert _published_revision(factory, agent_key) == published_before
    assert _immutable_graph_artifacts(factory) == artifacts_before

    writes: list[str] = []
    original_write = GraphConfiguration._write_locked_content

    def _recording_write(session, *, locked, content, actor):
        writes.append(actor)
        return original_write(session, locked=locked, content=content, actor=actor)

    monkeypatch.setattr(
        GraphConfiguration, "_write_locked_content", staticmethod(_recording_write)
    )
    with factory() as session:
        source = service.get_draft_legacy_prompt_source(
            session,
            agent_key=agent_key,
            expected_lock_version=1,
            actor="pg-source",
        )
    assert isinstance(source, DraftLegacyPromptSource)
    assert source.agent_key == agent_key
    assert source.lock_version == 1
    assert source.source.prompt_text == transition.source_composite_prompt
    assert source.source.revision_id == published_before[2]
    assert source.source.content_hash == published_before[1]
    assert writes == []
    assert _stored_draft(factory, agent_key) == (edited_content, edited_hash)
    assert _draft_meta(factory) == edited_meta
    assert _published_revision(factory, agent_key) == published_before
    assert _immutable_graph_artifacts(factory) == artifacts_before

    with factory() as session:
        restored = service.save_editable_model_draft(
            session,
            agent_key=agent_key,
            expected_lock_version=1,
            candidate=_editable_candidate(
                edited_content, prompt_text=source.source.prompt_text
            ),
            actor="pg-explicit-restore",
        )
    assert isinstance(restored, DraftSaveResult)
    assert _stored_draft(factory, agent_key) == (bootstrap_content, bootstrap_hash)
    with factory() as session:
        final = service.upgrade_draft_protected_assembly(
            session,
            agent_key=agent_key,
            expected_lock_version=2,
            actor="pg-final-upgrade",
        )
    assert isinstance(final, DraftSaveResult)
    assert writes == ["pg-explicit-restore", "pg-final-upgrade"]
    _assert_authored_only_persisted_v2(factory, agent_key, transition)
    final_content, _ = _stored_draft(factory, agent_key)
    assert final_content.prompt_text != edited_prompt
    assert edited_prompt == bootstrap_content.prompt_text + "!"
    assert _draft_meta(factory)[:2] == (3, "pg-final-upgrade")
    assert _published_revision(factory, agent_key) == published_before
    assert _immutable_graph_artifacts(factory) == artifacts_before


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


@pytest.mark.parametrize("agent_key", AFFECTED_ROLES)
def test_two_sessions_serialize_a_same_content_v1_save_against_an_upgrade(
    postgres_engine, agent_key, monkeypatch
) -> None:
    """Catches an upgrade that skips the lock comparison behind a same-content save."""
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    service = GraphConfiguration()
    service.bootstrap_v1(factory)
    transition = PromptAssembler().legacy_v1_prompt_source(agent_key=agent_key)
    bootstrap_content, bootstrap_hash = _stored_draft(factory, agent_key)
    published_before = _published_revision(factory, agent_key)
    artifacts_before = _immutable_graph_artifacts(factory)

    saver_locked = threading.Event()
    release_saver = threading.Event()
    upgrade_started = threading.Event()
    guard = threading.Lock()
    pids: dict[str, int] = {}
    outcomes: dict[str, object] = {}
    transition_calls: list[str] = []
    writes: list[str] = []

    original_upgrade = PromptAssembler.upgrade_definition_to_v2

    def _spy_upgrade(self, *, definition):
        with guard:
            transition_calls.append(threading.current_thread().name)
        return original_upgrade(self, definition=definition)

    original_write = GraphConfiguration._write_locked_content

    def _recording_write(session, *, locked, content, actor):
        with guard:
            writes.append(actor)
        return original_write(session, locked=locked, content=content, actor=actor)

    monkeypatch.setattr(PromptAssembler, "upgrade_definition_to_v2", _spy_upgrade)
    monkeypatch.setattr(
        GraphConfiguration, "_write_locked_content", staticmethod(_recording_write)
    )

    class ObservedGraphConfiguration(GraphConfiguration):
        def _lock_current_parents(self, session, *, exclusive):
            pid = session.scalar(text("SELECT pg_backend_pid()"))
            with guard:
                pids[threading.current_thread().name] = pid
            if threading.current_thread().name == "race-upgrade":
                upgrade_started.set()
            return super()._lock_current_parents(session, exclusive=exclusive)

    observed = ObservedGraphConfiguration()

    @event.listens_for(postgres_engine, "after_cursor_execute")
    def _pause_saver(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        normalized = " ".join(statement.upper().split())
        if (
            threading.current_thread().name == "race-saver"
            and "FOR UPDATE" in normalized
            and "FROM GRAPH_DRAFT_AGENT" in normalized
        ):
            saver_locked.set()
            assert release_saver.wait(timeout=20), "test never released the saver"

    def _same_content_save() -> None:
        threading.current_thread().name = "race-saver"
        with factory() as session:
            outcomes["saver"] = observed.save_editable_model_draft(
                session,
                agent_key=agent_key,
                expected_lock_version=0,
                candidate=_editable_candidate(
                    bootstrap_content, prompt_text=bootstrap_content.prompt_text
                ),
                actor="race-saver",
            )

    def _upgrade() -> None:
        threading.current_thread().name = "race-upgrade"
        with factory() as session:
            outcomes["upgrade"] = observed.upgrade_draft_protected_assembly(
                session,
                agent_key=agent_key,
                expected_lock_version=0,
                actor="race-upgrade",
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            saver = pool.submit(_same_content_save)
            assert saver_locked.wait(timeout=10), "saver never acquired the selected-row lock"
            upgrader = pool.submit(_upgrade)
            assert upgrade_started.wait(timeout=10), "upgrade never attempted the parent lock"
            with guard:
                upgrade_pid = pids.get("race-upgrade")
            assert upgrade_pid is not None
            observed_waiter = _observe_lock_waiter(postgres_engine, upgrade_pid)
            with guard:
                saver_pid = pids.get("race-saver")
            assert saver_pid is not None
            assert saver_pid != upgrade_pid
            assert observed_waiter is True
            release_saver.set()
            saver.result(timeout=20)
            upgrader.result(timeout=20)
    finally:
        release_saver.set()
        event.remove(postgres_engine, "after_cursor_execute", _pause_saver)

    winner = outcomes["saver"]
    loser = outcomes["upgrade"]
    assert isinstance(winner, DraftSaveResult)
    assert winner.changed is False
    assert winner.draft.lock_version == 1
    assert winner.draft.updated_by == "race-saver"
    preserved, preserved_hash = _stored_draft(factory, agent_key)
    assert preserved == bootstrap_content
    assert preserved.prompt_text == transition.source_composite_prompt
    assert preserved.assembly_rules == transition.source_assembly_rules
    assert preserved.protected_assembly == transition.source_protected_assembly
    assert preserved.definition_version == transition.source_definition_version
    assert preserved_hash == bootstrap_hash
    assert _published_revision(factory, agent_key) == published_before
    assert _immutable_graph_artifacts(factory) == artifacts_before

    assert isinstance(loser, DraftSaveConflict)
    assert loser.expected_lock_version == 0
    assert loser.current_lock_version == 1
    assert loser.client_candidate is None
    assert set(loser.server.definitions) == set(GRAPH_V1_AGENT_KEYS)
    assert len(loser.server.definitions) == 7
    assert loser.server.draft.lock_version == 1
    assert loser.server.definitions[agent_key].content == bootstrap_content
    assert transition_calls == []
    assert writes == ["race-saver"]

    with factory() as session:
        fresh = service.upgrade_draft_protected_assembly(
            session,
            agent_key=agent_key,
            expected_lock_version=1,
            actor="race-fresh-upgrade",
        )
    assert isinstance(fresh, DraftSaveResult)
    assert fresh.draft.lock_version == 2
    assert transition_calls == ["MainThread"]
    assert writes == ["race-saver", "race-fresh-upgrade"]
    _assert_authored_only_persisted_v2(factory, agent_key, transition)
    assert _published_revision(factory, agent_key) == published_before
    assert _immutable_graph_artifacts(factory) == artifacts_before


@pytest.mark.parametrize("agent_key", AFFECTED_ROLES)
def test_two_sessions_serialize_two_upgrades_and_reject_the_waiter(
    postgres_engine, agent_key, monkeypatch
) -> None:
    """Catches a second transition authority, a double write, or a masked stale lock."""
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    service = GraphConfiguration()
    service.bootstrap_v1(factory)
    transition = PromptAssembler().legacy_v1_prompt_source(agent_key=agent_key)
    bootstrap_content, _ = _stored_draft(factory, agent_key)
    published_before = _published_revision(factory, agent_key)
    artifacts_before = _immutable_graph_artifacts(factory)

    winner_locked = threading.Event()
    release_winner = threading.Event()
    loser_started = threading.Event()
    guard = threading.Lock()
    pids: dict[str, int] = {}
    outcomes: dict[str, object] = {}
    rejections: dict[str, DraftContentRejected] = {}
    transition_calls: list[str] = []
    writes: list[str] = []

    original_upgrade = PromptAssembler.upgrade_definition_to_v2

    def _spy_upgrade(self, *, definition):
        with guard:
            transition_calls.append(threading.current_thread().name)
        return original_upgrade(self, definition=definition)

    original_write = GraphConfiguration._write_locked_content

    def _recording_write(session, *, locked, content, actor):
        with guard:
            writes.append(actor)
        return original_write(session, locked=locked, content=content, actor=actor)

    monkeypatch.setattr(PromptAssembler, "upgrade_definition_to_v2", _spy_upgrade)
    monkeypatch.setattr(
        GraphConfiguration, "_write_locked_content", staticmethod(_recording_write)
    )

    class ObservedGraphConfiguration(GraphConfiguration):
        def _lock_current_parents(self, session, *, exclusive):
            pid = session.scalar(text("SELECT pg_backend_pid()"))
            with guard:
                pids[threading.current_thread().name] = pid
            if threading.current_thread().name == "upgrade-loser":
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

    def _run(name: str) -> None:
        threading.current_thread().name = name
        with factory() as session:
            try:
                outcomes[name] = observed.upgrade_draft_protected_assembly(
                    session,
                    agent_key=agent_key,
                    expected_lock_version=0,
                    actor=name,
                )
            except DraftContentRejected as exc:
                rejections[name] = exc

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            winner = pool.submit(_run, "upgrade-winner")
            assert winner_locked.wait(timeout=10), "winner never held the selected-row lock"
            loser = pool.submit(_run, "upgrade-loser")
            assert loser_started.wait(timeout=10), "loser never attempted the parent lock"
            with guard:
                loser_pid = pids.get("upgrade-loser")
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

    assert rejections == {}
    winner_outcome = outcomes["upgrade-winner"]
    loser_outcome = outcomes["upgrade-loser"]
    assert isinstance(winner_outcome, DraftSaveResult)
    assert winner_outcome.changed is True
    assert winner_outcome.draft.lock_version == 1
    _assert_authored_only_persisted_v2(factory, agent_key, transition)
    assert transition_calls == ["upgrade-winner"]
    assert writes == ["upgrade-winner"]

    assert isinstance(loser_outcome, DraftSaveConflict)
    assert loser_outcome.expected_lock_version == 0
    assert loser_outcome.current_lock_version == 1
    assert loser_outcome.client_candidate is None
    assert set(loser_outcome.server.definitions) == set(GRAPH_V1_AGENT_KEYS)
    assert len(loser_outcome.server.definitions) == 7
    selected = loser_outcome.server.definitions[agent_key].content
    assert selected.protected_assembly == V2_PROTECTED_ASSEMBLY_IDENTITY
    assert selected.assembly_rules == AssemblyRulesV2(format_version=2, custom_blocks=())
    assert selected.prompt_text == transition.target_authored_prompt
    assert selected.prompt_text != bootstrap_content.prompt_text
    assert _published_revision(factory, agent_key) == published_before
    assert _immutable_graph_artifacts(factory) == artifacts_before

    with factory() as session, pytest.raises(DraftContentRejected) as caught:
        service.upgrade_draft_protected_assembly(
            session,
            agent_key=agent_key,
            expected_lock_version=1,
            actor="upgrade-already-current",
        )
    assert _issue_tuples(caught) == ALREADY_CURRENT_TUPLE
    assert transition_calls == ["upgrade-winner", "MainThread"]
    assert writes == ["upgrade-winner"]
    assert _draft_meta(factory)[:2] == (1, "upgrade-winner")
    assert _published_revision(factory, agent_key) == published_before
    assert _immutable_graph_artifacts(factory) == artifacts_before

    success_body = DraftSaveSuccessResponse.model_validate(
        winner_outcome, from_attributes=True
    ).model_dump(mode="json")
    assert success_body["changed"] is True
    assert success_body["draft"]["lock_version"] == 1
    assert success_body["definition"]["prompt_text"] == transition.target_authored_prompt
    assert success_body["definition"]["assembly_rules"] == {
        "format_version": 2,
        "custom_blocks": [],
    }
    conflict_body = DraftSaveConflictResponse(
        code="stale_draft",
        expected_lock_version=loser_outcome.expected_lock_version,
        current_lock_version=loser_outcome.current_lock_version,
        client_candidate=None,
        server=DraftSaveConflictServerResponse(
            draft=loser_outcome.server.draft,
            definitions={
                key: DraftDefinitionResponse.model_validate(value, from_attributes=True)
                for key, value in loser_outcome.server.definitions.items()
            },
        ),
    ).model_dump(mode="json")
    assert conflict_body["client_candidate"] is None
    assert set(conflict_body["server"]["definitions"]) == set(GRAPH_V1_AGENT_KEYS)
    rejected_body = DraftValidationErrorResponse(
        code="invalid_draft",
        errors=[
            DraftFieldErrorResponse(
                field=issue.field, code=issue.code, message=issue.message
            )
            for issue in caught.value.issues
        ],
    ).model_dump(mode="json")
    assert rejected_body == {
        "code": "invalid_draft",
        "errors": [
            {
                "field": "protected_assembly.version",
                "code": "already_current",
                "message": "Protected assembly is already current.",
            }
        ],
    }
