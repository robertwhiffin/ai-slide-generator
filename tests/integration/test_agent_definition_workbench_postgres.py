from __future__ import annotations

import dataclasses
import pathlib
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session, sessionmaker

from src.api.routes import _authz
from src.api.routes import agent_definitions as agent_definition_routes
from src.api.routes.agent_definitions import router as agent_definition_router
from src.api.schemas.agent_definitions import (
    DraftDefinitionResponse,
    DraftFieldErrorResponse,
    DraftSaveConflictResponse,
    DraftSaveConflictServerResponse,
    DraftSaveSuccessResponse,
    DraftValidationErrorResponse,
)
from src.core.database import get_db
from src.core.prompt_modules import DESIGN_SYSTEM_PRECEDENCE, UNTRUSTED_DATA_NOTICE
from src.core.skills.build_reviewer import (
    BUILD_REVIEWER_AUTHORED_PREFIX,
    BUILD_REVIEWER_CRITERIA_STAGE,
    BUILD_REVIEWER_V1_AUTHORED_SUFFIX,
    BUILD_REVIEWER_V2_AUTHORED_SUFFIX,
    DECK_BRIEF_REVIEW,
)
from src.core.skills.data_analyst import ANALYST_AUTHORED_INSTRUCTIONS
from src.core.user_context import set_current_user
from src.database.models.graph_configuration import (
    AgentDefinitionRevision,
    GraphDraft,
    GraphDraftAgent,
    GraphRelease,
    GraphReleaseAgent,
)
from src.services.design_system_compiler import _SLIDE_FRAME_CONSTRAINTS
from src.services.graph_configuration import (
    CatalogRemoteEndpointDraftValidator,
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
from src.services.model_endpoint_catalog import FakeModelEndpointCatalog
from src.services.prompt_assembler import (
    ROLE_UNTRUSTED_DATA_NOTICE,
    V1_PROTECTED_ASSEMBLY_IDENTITY,
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
#: Recomposed from the reviewed skill constants rather than from ``PromptAssembler``, so the
#: expected and actual sides of a transition assertion are not both the assembler's output.
INDEPENDENT_TRANSITION_LITERALS = {
    "data_analyst": (
        UNTRUSTED_DATA_NOTICE + "\n\n" + ANALYST_AUTHORED_INSTRUCTIONS,
        ANALYST_AUTHORED_INSTRUCTIONS,
    ),
    "build_reviewer": (
        BUILD_REVIEWER_AUTHORED_PREFIX
        + "\n\n"
        + BUILD_REVIEWER_CRITERIA_STAGE
        + "\n\n"
        + BUILD_REVIEWER_V1_AUTHORED_SUFFIX,
        BUILD_REVIEWER_AUTHORED_PREFIX + "\n\n" + BUILD_REVIEWER_V2_AUTHORED_SUFFIX,
    ),
}
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
    independent_source, independent_target = INDEPENDENT_TRANSITION_LITERALS[agent_key]
    assert reloaded.prompt_text == transition.target_authored_prompt
    assert reloaded.prompt_text == independent_target
    assert reloaded.prompt_text != independent_source
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
    assert bootstrap_content.prompt_text == INDEPENDENT_TRANSITION_LITERALS[agent_key][0]
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


# ---------------------------------------------------------------------------
# Task 6: the real route stack over real PostgreSQL.
#
# Everything above drives the locked facade directly. This section drives the
# shipped FastAPI routes, so the serializers, the strict envelopes, the real
# protected bundle text and the real persisted rows all participate at once.
#
# It is also the only place the Python and TypeScript literals meet. The client's
# 422 fixtures in ``frontend/tests/fixtures/mocks.ts`` are hand-typed literals
# that claim to be byte-identical to the server's; nothing in the frontend lane
# can check that claim, so a Python-side edit would otherwise leave both suites
# green. Here the expected side is the wire body a real route really produced.
# ---------------------------------------------------------------------------


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLIENT_MOCKS = _REPO_ROOT / "frontend" / "tests" / "fixtures" / "mocks.ts"
_TS_STRING = re.compile(r"'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"")

#: Real protected display bytes, named from the modules that own them rather than
#: from ``PromptAssembler``, so a wrong wiring in the assembler cannot make both
#: sides of the comparison agree.
_V1_PAYLOAD_DISPLAY = "json.dumps(payload, indent=2, default=str)"
_V2_PAYLOAD_DISPLAY = (
    'json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)'
)
_OPEN_DELIMITER = "<untrusted-data>"
_CLOSE_DELIMITER = "</untrusted-data>"
_TERMINAL_BINDING = "langchain.with_structured_output"


def _client_rejection_triple(name: str) -> dict[str, str]:
    """The hand-typed (field, code, message) of one client 422 fixture."""
    source = _CLIENT_MOCKS.read_text(encoding="utf-8")
    start = source.index(f"export const {name}")
    block = source[start : source.index("\n};", start)]
    errors = block[block.index("errors: [") :]

    def literals(fragment: str) -> list[str]:
        values = []
        for match in _TS_STRING.finditer(fragment):
            raw = match.group(1) if match.group(1) is not None else match.group(2)
            values.append(raw.replace("\\n", "\n").replace("\\'", "'").replace('\\"', '"'))
        return values

    field = literals(errors[errors.index("field:") : errors.index("code:")])
    code = literals(errors[errors.index("code:") : errors.index("message:")])
    message = "".join(literals(errors[errors.index("message:") :]))
    assert len(field) == 1 and len(code) == 1 and message, (
        f"client fixture {name} did not parse; the join would be vacuous"
    )
    return {"field": field[0], "code": code[0], "message": message}


def _expected_v1_rows(agent_key: str, digest: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    if agent_key == "build_reviewer":
        rows.append(
            {
                "stage_id": "build_reviewer_deck_brief",
                "label": "Deck-brief re-review",
                "condition": "payload_has_deck_brief",
                "display_text": DECK_BRIEF_REVIEW,
                "legal_adjacent_custom_anchors": [],
            }
        )
    rows.extend(
        [
            {
                "stage_id": "slide_frame_constraints",
                "label": "Slide frame constraints",
                "condition": "design_system_inactive",
                "display_text": _SLIDE_FRAME_CONSTRAINTS,
                "legal_adjacent_custom_anchors": [],
            },
            {
                "stage_id": "design_system_precedence",
                "label": "Design system precedence",
                "condition": "design_system_active",
                "display_text": DESIGN_SYSTEM_PRECEDENCE,
                "legal_adjacent_custom_anchors": [],
            },
            {
                "stage_id": "runtime_payload",
                "label": "Graph Version 1 runtime payload",
                "condition": "always",
                "display_text": _V1_PAYLOAD_DISPLAY,
                "legal_adjacent_custom_anchors": [],
            },
            {
                "stage_id": "structured_output_binding",
                "label": "Structured-output binding",
                "condition": "always",
                "display_text": _TERMINAL_BINDING,
                "legal_adjacent_custom_anchors": [],
            },
        ]
    )
    for row in rows:
        row.update({"locked": True, "bundle_version": 1, "bundle_digest": digest})
    return rows


def _expected_v2_rows(agent_key: str, digest: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    if agent_key == "build_reviewer":
        rows.extend(
            [
                {
                    "stage_id": "build_reviewer_criteria",
                    "label": "Build Reviewer criteria",
                    "condition": "always",
                    "display_text": BUILD_REVIEWER_CRITERIA_STAGE,
                    "legal_adjacent_custom_anchors": [],
                },
                {
                    "stage_id": "build_reviewer_deck_brief",
                    "label": "Deck-brief re-review",
                    "condition": "payload_has_deck_brief",
                    "display_text": DECK_BRIEF_REVIEW,
                    "legal_adjacent_custom_anchors": ["after_deck_brief"],
                },
            ]
        )
    rows.extend(
        [
            {
                "stage_id": "slide_frame_constraints",
                "label": "Slide frame constraints",
                "condition": "design_system_inactive",
                "display_text": _SLIDE_FRAME_CONSTRAINTS,
                "legal_adjacent_custom_anchors": ["after_environment_constraints"],
            },
            {
                "stage_id": "design_system_precedence",
                "label": "Design system precedence",
                "condition": "design_system_active",
                "display_text": DESIGN_SYSTEM_PRECEDENCE,
                "legal_adjacent_custom_anchors": ["after_environment_constraints"],
            },
            {
                "stage_id": "untrusted_data_notice",
                "label": "Role-specific untrusted-data notice",
                "condition": "always",
                "display_text": ROLE_UNTRUSTED_DATA_NOTICE[agent_key],
                "legal_adjacent_custom_anchors": [],
            },
            {
                "stage_id": "untrusted_data_open",
                "label": "Untrusted-data opening delimiter",
                "condition": "always",
                "display_text": _OPEN_DELIMITER,
                "legal_adjacent_custom_anchors": [],
            },
            {
                "stage_id": "runtime_payload",
                "label": "Canonical runtime payload",
                "condition": "always",
                "display_text": _V2_PAYLOAD_DISPLAY,
                "legal_adjacent_custom_anchors": [],
            },
            {
                "stage_id": "untrusted_data_close",
                "label": "Untrusted-data closing delimiter",
                "condition": "always",
                "display_text": _CLOSE_DELIMITER,
                "legal_adjacent_custom_anchors": [],
            },
            {
                "stage_id": "structured_output_binding",
                "label": "Structured-output binding",
                "condition": "always",
                "display_text": _TERMINAL_BINDING,
                "legal_adjacent_custom_anchors": [],
            },
        ]
    )
    for row in rows:
        row.update({"locked": True, "bundle_version": 2, "bundle_digest": digest})
    return rows


@pytest.fixture
def real_route_stack(postgres_engine, monkeypatch):
    """The shipped router over real PostgreSQL, authorized as a trusted admin."""
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    GraphConfiguration().bootstrap_v1(factory)

    app = FastAPI()
    app.include_router(agent_definition_router)

    def _override_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    # The PUT's production remote endpoint validator needs a workspace client;
    # this stack proves persistence, so every remote endpoint check accepts.
    app.dependency_overrides[
        agent_definition_routes.get_remote_endpoint_draft_validator
    ] = lambda: CatalogRemoteEndpointDraftValidator(FakeModelEndpointCatalog)
    monkeypatch.setenv("ENVIRONMENT", "production")
    set_current_user("task6-admin@example.com")
    monkeypatch.setattr(_authz, "_admin_acl_probe", lambda _user: True)
    _authz.reset_admin_cache()
    try:
        with TestClient(app) as client:
            yield factory, client
    finally:
        set_current_user(None)
        _authz.reset_admin_cache()


def _node(body: dict, agent_key: str) -> dict:
    return next(node for node in body["nodes"] if node["agent_key"] == agent_key)


def test_affected_role_constant_matches_the_canonical_transition_list(real_route_stack) -> None:
    """Joins this suite's own hand-typed affected-role tuple to the server's list.

    ``AFFECTED_ROLES`` is one of five hand-typed copies of the set across two
    languages. The other four are joined in ``test_prompt_assembler.py``; this closes
    the copy that decides which roles the real-route sequences below actually run for,
    so a narrowed tuple REDs instead of silently shrinking this suite.
    """
    factory, _client = real_route_stack
    canonical = tuple(
        record.agent_key
        for record in PromptAssembler()
        .resolve_bundle(V2_PROTECTED_ASSEMBLY_IDENTITY)
        .transitions
    )
    assert AFFECTED_ROLES == canonical
    assert len(AFFECTED_ROLES) == len(set(AFFECTED_ROLES))
    # And each named role really is persisted as a legacy composite to begin with.
    for agent_key in AFFECTED_ROLES:
        content, _hash = _stored_draft(factory, agent_key)
        assert content.protected_assembly.version == 1
        assert content.prompt_text == INDEPENDENT_TRANSITION_LITERALS[agent_key][0]
    assert set(INDEPENDENT_TRANSITION_LITERALS) == set(canonical)


def test_real_routes_serve_real_protected_text_for_every_model_role(real_route_stack) -> None:
    """Catches placeholder, reconstructed, empty, or duplicated protected rows.

    Task 5's browser fixtures carry synthetic ``display_text`` on purpose, so this
    is the first and only place the real bundle bytes reach a real HTTP response.
    """
    _factory, client = real_route_stack

    response = client.get("/api/admin/agent-definitions/workbench")
    assert response.status_code == 200
    body = response.json()
    v1_digest = PromptAssembler().protected_stage_view(
        agent_key="architect", identity=V1_PROTECTED_ASSEMBLY_IDENTITY
    )[0].bundle_digest

    for agent_key in GRAPH_V1_AGENT_KEYS:
        node = _node(body, agent_key)
        expected = _expected_v1_rows(agent_key, v1_digest)
        for source in ("published", "draft"):
            rows = node[source]["protected_stage_view"]
            # M-3's silent-empty-view case is impossible on the server side.
            assert rows, f"{agent_key}.{source} served an empty protected_stage_view"
            assert rows == expected
            stage_ids = [row["stage_id"] for row in rows]
            assert len(stage_ids) == len(set(stage_ids))
            assert stage_ids[-1] == "structured_output_binding"

    # The deterministic node still carries no definition and therefore no view.
    foreman = _node(body, "foreman")
    assert foreman["published"] is None and foreman["draft"] is None


@pytest.mark.parametrize("agent_key", AFFECTED_ROLES)
def test_real_route_sequence_from_persisted_v1_edit_to_authored_only_v2(
    real_route_stack, agent_key
) -> None:
    """Drives 422 -> read-only source -> ordinary Save -> Upgrade over real routes.

    Catches a lossy or automatic transition, a source route that writes, a
    published mutation, a re-baselined 422 literal, or protected text the client
    fixtures no longer describe.
    """
    factory, client = real_route_stack
    upgrade_url = f"/api/admin/agent-definitions/draft/{agent_key}/protected-assembly-upgrade"
    source_url = f"/api/admin/agent-definitions/draft/{agent_key}/legacy-prompt-source"
    save_url = f"/api/admin/agent-definitions/draft/{agent_key}"

    transition = PromptAssembler().legacy_v1_prompt_source(agent_key=agent_key)
    independent_source, independent_target = INDEPENDENT_TRANSITION_LITERALS[agent_key]
    published_content, published_hash, published_id = _published_revision(factory, agent_key)
    artifacts_before = _immutable_graph_artifacts(factory)
    assert published_content.prompt_text == independent_source

    # A persisted one-code-point edit of the published Graph Version 1 composite.
    edited_prompt = independent_source[:-1] + "é"
    assert edited_prompt != independent_source
    assert len(edited_prompt) == len(independent_source)

    saved = client.put(
        save_url,
        json={
            "lock_version": 0,
            "candidate": {
                "prompt_text": edited_prompt,
                "model": {
                    "endpoint_name": published_content.model.endpoint_name,
                    "temperature": float(published_content.model.temperature),
                    "max_tokens": published_content.model.max_tokens,
                    "top_p": float(published_content.model.top_p),
                },
            },
        },
    )
    assert saved.status_code == 200
    assert saved.json()["draft"]["lock_version"] == 1
    assert saved.json()["definition"]["prompt_text"] == edited_prompt

    # 1. The edited legacy composite is refused with the exact manual-resolution issue.
    rejected = client.post(upgrade_url, json={"lock_version": 1})
    assert rejected.status_code == 422
    assert rejected.json() == {
        "code": "invalid_draft",
        "errors": [_client_rejection_triple("MANUAL_RESOLUTION_REJECTION")],
    }
    after_rejection, hash_after_rejection = _stored_draft(factory, agent_key)
    assert after_rejection.prompt_text == edited_prompt
    assert after_rejection.protected_assembly == transition.source_protected_assembly
    assert _draft_meta(factory)[0] == 1

    # 2. The source route returns the exact published prompt and writes nothing.
    recovered = client.post(source_url, json={"lock_version": 1})
    assert recovered.status_code == 200
    source_body = recovered.json()
    assert source_body["agent_key"] == agent_key
    assert source_body["lock_version"] == 1
    assert source_body["draft"]["lock_version"] == 1
    assert source_body["source"] == {
        "prompt_text": independent_source,
        "revision_id": published_id,
        "content_hash": published_hash,
    }
    assert _stored_draft(factory, agent_key) == (after_rejection, hash_after_rejection)
    assert _draft_meta(factory)[0] == 1
    assert _immutable_graph_artifacts(factory) == artifacts_before

    # 3. An explicit ordinary Save reinstates the exact published composite.
    restored = client.put(
        save_url,
        json={
            "lock_version": 1,
            "candidate": {
                "prompt_text": source_body["source"]["prompt_text"],
                "model": {
                    "endpoint_name": published_content.model.endpoint_name,
                    "temperature": float(published_content.model.temperature),
                    "max_tokens": published_content.model.max_tokens,
                    "top_p": float(published_content.model.top_p),
                },
            },
        },
    )
    assert restored.status_code == 200
    assert restored.json()["draft"]["lock_version"] == 2
    assert restored.json()["definition"]["prompt_text"] == independent_source
    assert restored.json()["definition"]["assembly_rules"]["format_version"] == 1

    # 4. Only now does an explicit Upgrade produce the authored-only v2 definition.
    upgraded = client.post(upgrade_url, json={"lock_version": 2})
    assert upgraded.status_code == 200
    definition = upgraded.json()["definition"]
    assert upgraded.json()["draft"]["lock_version"] == 3
    assert definition["prompt_text"] == independent_target
    assert definition["prompt_text"] == transition.target_authored_prompt
    assert definition["assembly_rules"] == {"format_version": 2, "custom_blocks": []}
    assert definition["protected_assembly"] == {
        "version": V2_PROTECTED_ASSEMBLY_IDENTITY.version,
        "digest": V2_PROTECTED_ASSEMBLY_IDENTITY.digest,
    }
    assert definition["protected_stage_view"] == _expected_v2_rows(
        agent_key, V2_PROTECTED_ASSEMBLY_IDENTITY.digest
    )
    stage_ids = [row["stage_id"] for row in definition["protected_stage_view"]]
    assert len(stage_ids) == len(set(stage_ids))
    displaced = (
        UNTRUSTED_DATA_NOTICE if agent_key == "data_analyst" else BUILD_REVIEWER_CRITERIA_STAGE
    )
    assert displaced not in definition["prompt_text"]

    # 5. A second Upgrade is the exact already-current rejection and writes nothing.
    already = client.post(upgrade_url, json={"lock_version": 3})
    assert already.status_code == 422
    assert already.json() == {
        "code": "invalid_draft",
        "errors": [_client_rejection_triple("ALREADY_CURRENT_REJECTION")],
    }
    assert _draft_meta(factory)[0] == 3

    # 6. Nothing published moved at any point in the sequence.
    assert _published_revision(factory, agent_key) == (
        published_content,
        published_hash,
        published_id,
    )
    assert _immutable_graph_artifacts(factory) == artifacts_before


def test_real_upgrade_route_rejects_a_stale_lock_with_a_null_candidate_conflict(
    real_route_stack,
) -> None:
    """The upgrade conflict envelope carries exactly ``client_candidate: null``."""
    factory, client = real_route_stack
    published_content = _published_revision(factory, "architect")[0]

    bumped = client.put(
        "/api/admin/agent-definitions/draft/architect",
        json={
            "lock_version": 0,
            "candidate": {
                "prompt_text": published_content.prompt_text + " edited",
                "model": {
                    "endpoint_name": published_content.model.endpoint_name,
                    "temperature": float(published_content.model.temperature),
                    "max_tokens": published_content.model.max_tokens,
                    "top_p": float(published_content.model.top_p),
                },
            },
        },
    )
    assert bumped.status_code == 200

    stale = client.post(
        "/api/admin/agent-definitions/draft/data_analyst/protected-assembly-upgrade",
        json={"lock_version": 0},
    )
    assert stale.status_code == 409
    body = stale.json()
    assert body["code"] == "stale_draft"
    assert body["expected_lock_version"] == 0
    assert body["current_lock_version"] == 1
    assert body["client_candidate"] is None
    assert set(body["server"]["definitions"]) == set(GRAPH_V1_AGENT_KEYS)
    assert body["current_lock_version"] == body["server"]["draft"]["lock_version"]
    # A refused upgrade writes nothing of its own.
    assert _draft_meta(factory)[0] == 1
    assert _stored_draft(factory, "data_analyst")[0].protected_assembly.version == 1


# ---------------------------------------------------------------------------
# #266 Task 2: the remote endpoint phase under real PostgreSQL row locks.
# ---------------------------------------------------------------------------


def test_stale_endpoint_loser_waits_on_the_lock_and_never_reaches_remote_validation(
    postgres_engine, monkeypatch
) -> None:
    """Catches the remote endpoint check running for a stale concurrent loser.

    The winner blocks inside a deterministic remote validator while it holds the
    draft locks; a second, locally valid save against the same lock version
    waits on a real PostgreSQL lock, then sees the winner's commit and returns
    the coherent 409 without ever invoking remote validation or writing.
    """
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    GraphConfiguration().bootstrap_v1(factory)
    bootstrap_content, _ = _stored_draft(factory, "architect")
    artifacts_before = _immutable_graph_artifacts(factory)

    winner_validating = threading.Event()
    release_winner = threading.Event()
    loser_started = threading.Event()
    guard = threading.Lock()
    pids: dict[str, int] = {}
    outcomes: dict[str, object] = {}
    remote_calls: list[tuple[str, str]] = []
    writes: list[str] = []

    class BlockingRemoteEndpointValidator:
        def validate(self, content: DefinitionContent) -> None:
            with guard:
                remote_calls.append(
                    (threading.current_thread().name, content.model.endpoint_name)
                )
            if threading.current_thread().name == "endpoint-winner":
                winner_validating.set()
                assert release_winner.wait(timeout=20), "test never released the winner"

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
            if threading.current_thread().name == "endpoint-loser":
                loser_started.set()
            return super()._lock_current_parents(session, exclusive=exclusive)

    service = ObservedGraphConfiguration(
        remote_endpoint_validator=BlockingRemoteEndpointValidator()
    )
    loser_candidate = EditableModelDraft(
        prompt_text="stale loser edit",
        endpoint_name="loser endpoint name",
        temperature=float(bootstrap_content.model.temperature),
        max_tokens=bootstrap_content.model.max_tokens,
        top_p=float(bootstrap_content.model.top_p),
    )

    def _save(thread_name: str, candidate: EditableModelDraft) -> None:
        threading.current_thread().name = thread_name
        with factory() as session:
            outcomes[thread_name] = service.save_editable_model_draft(
                session,
                agent_key="architect",
                expected_lock_version=0,
                candidate=candidate,
                actor=thread_name,
            )

    winner_candidate = EditableModelDraft(
        prompt_text="winner edit",
        endpoint_name="winner endpoint name",
        temperature=float(bootstrap_content.model.temperature),
        max_tokens=bootstrap_content.model.max_tokens,
        top_p=float(bootstrap_content.model.top_p),
    )
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            winner = pool.submit(_save, "endpoint-winner", winner_candidate)
            assert winner_validating.wait(timeout=10), "winner never reached remote validation"
            loser = pool.submit(_save, "endpoint-loser", loser_candidate)
            assert loser_started.wait(timeout=10), "loser never attempted the parent lock"
            with guard:
                loser_pid = pids.get("endpoint-loser")
                winner_pid = pids.get("endpoint-winner")
            assert loser_pid is not None and winner_pid is not None
            assert winner_pid != loser_pid
            assert _observe_lock_waiter(postgres_engine, loser_pid) is True
            with guard:
                assert remote_calls == [("endpoint-winner", "winner endpoint name")]
            release_winner.set()
            winner.result(timeout=20)
            loser.result(timeout=20)
    finally:
        release_winner.set()

    won = outcomes["endpoint-winner"]
    lost = outcomes["endpoint-loser"]
    assert isinstance(won, DraftSaveResult)
    assert won.draft.lock_version == 1
    assert won.draft.updated_by == "endpoint-winner"
    persisted, persisted_hash = _stored_draft(factory, "architect")
    assert persisted.prompt_text == "winner edit"
    assert persisted.model.endpoint_name == "winner endpoint name"
    assert persisted_hash == definition_content_hash(persisted)
    assert _draft_meta(factory)[:2] == (1, "endpoint-winner")

    assert isinstance(lost, DraftSaveConflict)
    assert lost.expected_lock_version == 0
    assert lost.current_lock_version == 1
    assert lost.client_candidate is loser_candidate
    assert set(lost.server.definitions) == set(GRAPH_V1_AGENT_KEYS)
    assert len(lost.server.definitions) == 7
    assert lost.server.definitions["architect"].content.prompt_text == "winner edit"

    # The stale loser never reached the remote phase and never wrote.
    assert remote_calls == [("endpoint-winner", "winner endpoint name")]
    assert writes == ["endpoint-winner"]
    assert _immutable_graph_artifacts(factory) == artifacts_before


def test_model_endpoint_probe_holds_no_lock_while_the_model_call_is_in_flight(
    postgres_engine,
) -> None:
    """Correction 13: the probe's snapshot read releases every lock before the call.

    A deterministic probe blocks mid-call.  While it is in flight, the backend
    that took the snapshot's FOR SHARE parent locks must hold no lock and no open
    transaction, and a concurrent save (which needs FOR UPDATE on the same
    parents) must commit without waiting.  The probe then reports its copied
    pre-save identity, not the committed one.
    """
    from src.services.model_endpoint_probe import (
        ModelEndpointProbeService,
        SavedEndpointProbeIdentity,
    )

    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    GraphConfiguration().bootstrap_v1(factory)
    bootstrap_content, bootstrap_hash = _stored_draft(factory, "architect")
    artifacts_before = _immutable_graph_artifacts(factory)

    probe_in_flight = threading.Event()
    release_probe = threading.Event()
    guard = threading.Lock()
    pids: dict[str, int] = {}
    probed: list[str] = []

    class ObservedGraphConfiguration(GraphConfiguration):
        def _lock_current_parents(self, session, *, exclusive):
            pid = session.scalar(text("SELECT pg_backend_pid()"))
            with guard:
                pids.setdefault(threading.current_thread().name, pid)
            return super()._lock_current_parents(session, exclusive=exclusive)

    class BlockingProbe:
        def probe(self, configuration) -> None:
            with guard:
                probed.append(configuration.endpoint_name)
            probe_in_flight.set()
            assert release_probe.wait(timeout=20), "test never released the probe"

    service = ModelEndpointProbeService(
        BlockingProbe(), configuration_factory=ObservedGraphConfiguration
    )
    outcomes: dict[str, object] = {}

    def _probe() -> None:
        threading.current_thread().name = "probe"
        with factory() as session:
            outcomes["probe"] = service.probe_saved_candidate(
                session, agent_key="architect", expected_lock_version=0
            )

    def _save() -> None:
        threading.current_thread().name = "saver"
        with factory() as session:
            outcomes["save"] = GraphConfiguration().save_editable_model_draft(
                session,
                agent_key="architect",
                expected_lock_version=0,
                candidate=EditableModelDraft(
                    prompt_text=bootstrap_content.prompt_text,
                    endpoint_name="saved while probing",
                    temperature=float(bootstrap_content.model.temperature),
                    max_tokens=bootstrap_content.model.max_tokens,
                    top_p=float(bootstrap_content.model.top_p),
                ),
                actor="saver",
            )

    # The observer's connection is checked out before the probe starts, so the
    # pool cannot hand it the probe's released connection and have it count its
    # own locks.
    observer = postgres_engine.connect()
    observer_pid = observer.scalar(text("SELECT pg_backend_pid()"))
    observer.commit()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            probing = pool.submit(_probe)
            assert probe_in_flight.wait(timeout=10), "probe never reached the model call"
            with guard:
                probe_pid = pids["probe"]
            assert probe_pid != observer_pid
            held = observer.scalar(
                text("SELECT count(*) FROM pg_locks WHERE pid = :pid"),
                {"pid": probe_pid},
            )
            state = observer.scalar(
                text("SELECT state FROM pg_stat_activity WHERE pid = :pid"),
                {"pid": probe_pid},
            )
            observer.commit()
            assert held == 0
            assert state != "idle in transaction"
            saving = pool.submit(_save)
            # The save must finish while the probe is still blocked mid-call.
            saving.result(timeout=10)
            assert not probing.done()
            release_probe.set()
            probing.result(timeout=20)
    finally:
        release_probe.set()
        observer.close()

    saved = outcomes["save"]
    assert isinstance(saved, DraftSaveResult)
    assert saved.draft.lock_version == 1
    persisted, persisted_hash = _stored_draft(factory, "architect")
    assert persisted.model.endpoint_name == "saved while probing"
    assert persisted_hash != bootstrap_hash

    result = outcomes["probe"]
    assert probed == [bootstrap_content.model.endpoint_name]
    assert result.failure is None
    assert result.identity == SavedEndpointProbeIdentity(
        agent_key="architect",
        endpoint_name=bootstrap_content.model.endpoint_name,
        candidate_hash=bootstrap_hash,
        lock_version=0,
    )
    assert _immutable_graph_artifacts(factory) == artifacts_before
