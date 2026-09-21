from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

from src.database.models.graph_configuration import (
    AgentDefinitionRevision,
    AgentTestCase,
    GraphDraft,
    GraphDraftAgent,
    GraphRelease,
    GraphReleaseAgent,
)
from src.services.graph_configuration import GraphConfiguration
from src.services.graph_definition_manifest import GRAPH_V1_AGENT_KEYS

pytestmark = pytest.mark.postgres


def _identities(factory):
    with factory() as session:
        return {
            "revisions": session.execute(
                select(
                    AgentDefinitionRevision.id,
                    AgentDefinitionRevision.agent_key,
                    AgentDefinitionRevision.content_hash,
                ).order_by(AgentDefinitionRevision.agent_key)
            ).all(),
            "releases": session.execute(
                select(GraphRelease.id, GraphRelease.version_number)
            ).all(),
            "mappings": session.execute(
                select(
                    GraphReleaseAgent.graph_release_id,
                    GraphReleaseAgent.agent_key,
                    GraphReleaseAgent.agent_definition_revision_id,
                ).order_by(GraphReleaseAgent.agent_key)
            ).all(),
            "drafts": session.execute(
                select(GraphDraft.id, GraphDraft.base_release_id)
            ).all(),
            "draft_agents": session.execute(
                select(
                    GraphDraftAgent.graph_draft_id,
                    GraphDraftAgent.agent_key,
                    GraphDraftAgent.candidate_hash,
                ).order_by(GraphDraftAgent.agent_key)
            ).all(),
            "cases": session.execute(
                select(
                    AgentTestCase.agent_key,
                    AgentTestCase.name,
                    AgentTestCase.version,
                ).order_by(AgentTestCase.agent_key)
            ).all(),
        }


def test_two_bootstraps_observe_second_backend_waiting_on_advisory_lock(
    postgres_engine,
):
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    first_has_lock = threading.Event()
    release_first = threading.Event()
    pids: dict[str, int] = {}
    pids_lock = threading.Lock()

    class HoldingGraphConfiguration(GraphConfiguration):
        def _take_bootstrap_lock(self, session) -> None:
            pid = session.scalar(text("SELECT pg_backend_pid()"))
            with pids_lock:
                pids[threading.current_thread().name] = pid
            super()._take_bootstrap_lock(session)
            if threading.current_thread().name == "bootstrap-first":
                first_has_lock.set()
                assert release_first.wait(timeout=20), "observer never released first lock"

    service = HoldingGraphConfiguration()

    def run(name):
        threading.current_thread().name = name
        return service.bootstrap_v1(factory)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(run, "bootstrap-first")
        assert first_has_lock.wait(timeout=10), "first backend did not acquire advisory lock"
        second_future = pool.submit(run, "bootstrap-second")

        deadline = time.monotonic() + 10
        observed_waiter = False
        second_pid = None
        while time.monotonic() < deadline:
            with pids_lock:
                first_pid = pids.get("bootstrap-first")
                second_pid = pids.get("bootstrap-second")
            if first_pid is not None and second_pid is not None:
                with postgres_engine.connect() as observer:
                    observed_waiter = bool(
                        observer.execute(
                            text(
                                "SELECT EXISTS ("
                                " SELECT 1 FROM pg_locks waiting "
                                " JOIN pg_stat_activity activity ON activity.pid = waiting.pid "
                                " WHERE waiting.locktype = 'advisory' "
                                " AND waiting.granted = false "
                                " AND waiting.pid = :second_pid "
                                " AND activity.wait_event_type = 'Lock'"
                                ")"
                            ),
                            {"second_pid": second_pid},
                        ).scalar_one()
                    )
                    first_granted = bool(
                        observer.execute(
                            text(
                                "SELECT EXISTS (SELECT 1 FROM pg_locks "
                                "WHERE locktype = 'advisory' AND granted = true "
                                "AND pid = :first_pid)"
                            ),
                            {"first_pid": first_pid},
                        ).scalar_one()
                    )
                if observed_waiter and first_granted:
                    break
            time.sleep(0.02)

        assert first_pid != second_pid
        assert observed_waiter is True
        release_first.set()
        first = first_future.result(timeout=20)
        second = second_future.result(timeout=20)

    assert first.created is True
    assert second.created is False
    assert (first.release_id, first.version_number) == (
        second.release_id,
        second.version_number,
    )
    final = _identities(factory)
    assert len(final["revisions"]) == 7
    assert len(final["releases"]) == 1
    assert len(final["mappings"]) == 7
    assert len(final["drafts"]) == 1
    assert len(final["draft_agents"]) == 7
    assert len(final["cases"]) == 7
    assert {row.agent_key for row in final["revisions"]} == set(GRAPH_V1_AGENT_KEYS)
    assert {row.agent_key for row in final["mappings"]} == set(GRAPH_V1_AGENT_KEYS)
    assert {row.agent_key for row in final["draft_agents"]} == set(GRAPH_V1_AGENT_KEYS)
    assert {
        (row.agent_key, row.name, row.version) for row in final["cases"]
    } == {
        (agent_key, f"{agent_key}_required_smoke_v1", 1)
        for agent_key in GRAPH_V1_AGENT_KEYS
    }
    revision_hashes = {
        row.agent_key: row.content_hash for row in final["revisions"]
    }
    assert {
        row.agent_key: row.candidate_hash for row in final["draft_agents"]
    } == revision_hashes
    assert {row.graph_release_id for row in final["mappings"]} == {first.release_id}
