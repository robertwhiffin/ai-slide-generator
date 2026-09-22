from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.orm import sessionmaker

from src.database.models.graph_configuration import (
    GraphDraft,
    GraphDraftAgent,
    GraphRelease,
)
from src.services.graph_configuration import GraphConfiguration
from src.services.graph_configuration_content import definition_content_from_row
from src.services.graph_definition_manifest import definition_content_hash

pytestmark = pytest.mark.postgres


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
