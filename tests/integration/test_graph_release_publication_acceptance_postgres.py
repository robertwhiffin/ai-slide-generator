"""#269 Task 8: real-PostgreSQL HTTP acceptance for Graph Release publication.

The #271 AC7 seam.  Everything goes through the shipped admin router
(``src.api.routes.agent_definitions.router``) over a throwaway PostgreSQL
database: draft saves, #267's candidate test-run route, #268's verdict and
readiness routes, and #269's preview and publish routes.  The only doubles are:

* ``get_db`` bound to the throwaway database;
* the remote endpoint validator (the PUT's workspace-client check) accepting;
* ``get_agent_test_workbench`` returning an ``AgentTestWorkbench`` whose runtime
  loads the persisted release and answers through the deterministic fake model
  adapter (Correction 53 / C38 fake-adapter row).  Readiness is reached through
  this same dependency (C39), so the route's production readiness binding is
  exercised, not faked.

The ``real_route_stack`` recipe is copied (not imported) from
``test_agent_definition_workbench_postgres.py`` so none of that module's tests
are re-collected here (C53).

Also here: the preview's shared parent lock (``FOR SHARE``) and its no-write
property, observed on real PostgreSQL (Task 5 review m4).
"""

from __future__ import annotations

import contextlib
import contextvars
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from sqlalchemy.orm import sessionmaker

from src.api.routes import _authz
from src.api.routes import agent_definitions as agent_definition_routes
from src.api.routes.agent_definitions import router as agent_definition_router
from src.api.services.session_manager import SessionManager
from src.core.database import get_db
from src.core.user_context import set_current_user
from src.database.models.graph_configuration import (
    AgentTestCase,
    GraphRelease,
    GraphReleaseAgent,
)
from src.database.models.session import UserSession
from src.services.agent_runtime import AgentRuntime
from src.services.agent_runtime_identity import RecordingAgentInvocationIdentitySink
from src.services.agent_test_workbench import AgentTestWorkbench
from src.services.conversation_pins import (
    ConversationGraphVersion,
    get_conversation_graph_version,
)
from src.services.graph_configuration import CatalogRemoteEndpointDraftValidator, GraphConfiguration
from src.services.graph_definition_manifest import GRAPH_V1_AGENT_KEYS
from src.services.model_endpoint_catalog import FakeModelEndpointCatalog
from src.services.persisted_graph_release import PersistedGraphReleaseLoader
from tests.fixtures.deterministic_model_adapter import DeterministicFakeModelAdapter
from tests.integration.postgres_concurrency_helpers import (
    _WAIT_SECONDS,
    _await_blocked_by,
)

pytestmark = pytest.mark.postgres

_PREFIX = "/api/admin/agent-definitions"
_ADMIN = "task8-admin@example.com"
_OWNER = "owner@example.com"
_ARCHITECT_TUNE = "\n\nAcceptance: tune the architect."
_BUILDER_TUNE = "\n\nAcceptance: tune the builder."
_SHARED_PARENT_LOCK_TAIL = "FOR SHARE OF GRAPH_RELEASE, GRAPH_DRAFT"


# ---------------------------------------------------------------------------
# Harness: the shipped router over real PostgreSQL (copied recipe, C53)
# ---------------------------------------------------------------------------


def _fake_adapter_workbench(factory, adapter) -> AgentTestWorkbench:
    """The ``_pg_executor`` recipe: persisted-release runtime, fake model adapter."""
    runtime = AgentRuntime(
        persisted_release_loader=PersistedGraphReleaseLoader(session_factory=factory),
        model_adapter=adapter,
        identity_sink=RecordingAgentInvocationIdentitySink(),
    )
    return AgentTestWorkbench(runtime=runtime)


@pytest.fixture
def acceptance_stack(postgres_engine, monkeypatch):
    """Yields ``(factory, client, adapter)`` for the one admin router on PostgreSQL."""
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    GraphConfiguration().bootstrap_v1(factory)
    adapter = DeterministicFakeModelAdapter()
    workbench = _fake_adapter_workbench(factory, adapter)

    app = FastAPI()
    app.include_router(agent_definition_router)

    def _override_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[agent_definition_routes.get_remote_endpoint_draft_validator] = (
        lambda: CatalogRemoteEndpointDraftValidator(FakeModelEndpointCatalog)
    )
    # One override covers runs, verdicts, readiness, preview and publish (C39/C53).
    app.dependency_overrides[agent_definition_routes.get_agent_test_workbench] = lambda: workbench
    monkeypatch.setenv("ENVIRONMENT", "production")
    set_current_user(_ADMIN)
    monkeypatch.setattr(_authz, "_admin_acl_probe", lambda _user: True)
    _authz.reset_admin_cache()
    try:
        with TestClient(app) as client:
            yield factory, client, adapter
    finally:
        set_current_user(None)
        _authz.reset_admin_cache()


@contextlib.contextmanager
def _session_manager_on(factory):
    """``SessionManager`` writes through the throwaway database."""

    @contextlib.contextmanager
    def managed_session():
        db = factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    with patch("src.api.services.session_manager.get_db_session", managed_session):
        yield SessionManager()


def _workbench(client: TestClient) -> dict:
    response = client.get(f"{_PREFIX}/workbench")
    assert response.status_code == 200, response.text
    return response.json()


def _node(body: dict, agent_key: str) -> dict:
    return next(node for node in body["nodes"] if node["agent_key"] == agent_key)


def _save(client: TestClient, agent_key: str, suffix: str) -> dict:
    body = _workbench(client)
    draft = _node(body, agent_key)["draft"]
    response = client.put(
        f"{_PREFIX}/draft/{agent_key}",
        json={
            "lock_version": body["draft"]["lock_version"],
            "candidate": {
                "prompt_text": draft["prompt_text"] + suffix,
                "model": {
                    key: draft["model"][key]
                    for key in ("endpoint_name", "temperature", "max_tokens", "top_p")
                },
            },
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _required_case_id(factory, agent_key: str) -> int:
    with factory() as db:
        case_ids = list(
            db.scalars(
                select(AgentTestCase.id).where(
                    AgentTestCase.agent_key == agent_key,
                    AgentTestCase.is_active.is_(True),
                    AgentTestCase.is_required.is_(True),
                )
            )
        )
    assert len(case_ids) == 1, case_ids
    return case_ids[0]


def _run(client: TestClient, agent_key: str, case_id: int) -> dict:
    lock = _workbench(client)["draft"]["lock_version"]
    response = client.post(
        f"{_PREFIX}/draft/{agent_key}/test-runs",
        json={"test_case_id": case_id, "lock_version": lock},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _approve(client: TestClient, run_id: int) -> dict:
    response = client.post(
        f"{_PREFIX}/test-runs/{run_id}/verdict",
        json={"verdict": "approved", "notes": None},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _publish(client: TestClient, lock: int, note: str = "Tune architect and builder"):
    return client.post(f"{_PREFIX}/releases", json={"lock_version": lock, "release_note": note})


def _mapping_rows(factory, release_id: int) -> dict[str, int]:
    with factory() as db:
        return {
            row.agent_key: row.agent_definition_revision_id
            for row in db.scalars(
                select(GraphReleaseAgent).where(GraphReleaseAgent.graph_release_id == release_id)
            )
        }


def _release_ids(factory) -> list[tuple[int, int, bool]]:
    with factory() as db:
        return [
            (row.id, row.version_number, row.effective_to is None)
            for row in db.scalars(select(GraphRelease).order_by(GraphRelease.id))
        ]


def _pin_of(factory, session_id: str) -> int | None:
    with factory() as db:
        return db.scalar(
            select(UserSession.graph_release_id).where(UserSession.session_id == session_id)
        )


def _projected_version(factory, session_id: str) -> ConversationGraphVersion:
    with factory() as db:
        session = db.scalar(select(UserSession).where(UserSession.session_id == session_id))
        return get_conversation_graph_version(db, session)


# ---------------------------------------------------------------------------
# The acceptance flow
# ---------------------------------------------------------------------------


def test_edit_test_approve_preview_publish_pin_flow(acceptance_stack) -> None:
    """Edit -> test -> approve -> preview -> publish -> pin, all over real routes.

    Corrections applied: C10 (publish is 200), C12 (builder is run and approved
    twice, and a not-ready POST precedes architect's approval, so the route's
    production readiness binding and the newest-approval selection are both
    load-bearing), C53 (the one workbench override).
    """
    factory, client, adapter = acceptance_stack

    # -- Bootstrap state: v1 active, draft at lock 0, an old conversation on v1.
    initial = _workbench(client)
    v1_id = initial["active_release"]["release_id"]
    assert initial["active_release"]["version_number"] == 1
    assert initial["draft"]["lock_version"] == 0
    v1_mappings = _mapping_rows(factory, v1_id)
    assert set(v1_mappings) == set(GRAPH_V1_AGENT_KEYS)
    published_prompts = {
        key: _node(initial, key)["published"]["prompt_text"] for key in ("architect", "builder")
    }

    with _session_manager_on(factory) as manager:
        old_root = manager.create_session(
            session_id="old-root", created_by=_OWNER, graph_capable=True
        )
    assert (old_root["graph_version"], old_root["is_older_than_active"]) == (1, False)
    assert _pin_of(factory, "old-root") == v1_id

    # -- Edit two roles through the shipped PUT.
    _save(client, "architect", _ARCHITECT_TUNE)
    saved_builder = _save(client, "builder", _BUILDER_TUNE)
    assert saved_builder["draft"]["lock_version"] == 2
    architect_case = _required_case_id(factory, "architect")
    builder_case = _required_case_id(factory, "builder")

    # -- Builder's required case, run and approved twice (C12 item 1).  Builder
    # approvability under the fake adapter was a Task 0 open question: the run
    # must complete with passing deterministic checks, or the verdict route
    # refuses the approval.
    builder_first = _run(client, "builder", builder_case)
    assert (
        builder_first["execution_status"],
        builder_first["deterministic_checks_passed"],
    ) == ("completed", True), builder_first
    assert (
        builder_first["candidate_hash"]
        == _node(_workbench(client), "builder")["draft"]["candidate_hash"]
    )
    _approve(client, builder_first["run_id"])
    builder_second = _run(client, "builder", builder_case)
    assert builder_second["run_id"] > builder_first["run_id"]
    assert (
        builder_second["execution_status"],
        builder_second["deterministic_checks_passed"],
    ) == ("completed", True)
    _approve(client, builder_second["run_id"])

    architect_run = _run(client, "architect", architect_case)
    assert (
        architect_run["execution_status"],
        architect_run["deterministic_checks_passed"],
    ) == ("completed", True)
    assert [call.agent_key for call in adapter.calls] == ["builder", "builder", "architect"]

    # -- Not ready yet: architect's run awaits review (C12 item 2).  The 409's
    # readiness comes from #268's real readiness through the route's binding.
    lock = _workbench(client)["draft"]["lock_version"]
    assert lock == 2, "test runs and verdicts must not move the draft lock (C41)"
    not_ready = _publish(client, lock)
    assert not_ready.status_code == 409, not_ready.text
    not_ready_body = not_ready.json()
    assert not_ready_body["code"] == "publication_not_ready"
    assert not_ready_body["gaps"] == [
        {
            "agent_key": "architect",
            "test_case_id": architect_case,
            "code": "no_eligible_approval",
        }
    ]
    readiness = not_ready_body["readiness"]
    assert readiness["blocking_agents"] == ["architect"]
    assert readiness["all_ready"] is False
    readiness_by_role = {agent["agent_key"]: agent for agent in readiness["agents"]}
    architect_cases = {
        case["test_case_id"]: case for case in readiness_by_role["architect"]["cases"]
    }
    assert architect_cases[architect_case]["status"] == "awaiting_review"
    assert architect_cases[architect_case]["blocking"] is True
    assert architect_cases[architect_case]["run_id"] == architect_run["run_id"]
    builder_cases = {case["test_case_id"]: case for case in readiness_by_role["builder"]["cases"]}
    assert builder_cases[builder_case]["status"] == "approved"
    assert builder_cases[builder_case]["run_id"] == builder_second["run_id"]
    # The informational readiness route agrees with the not-ready body.
    readiness_route = client.get(f"{_PREFIX}/readiness")
    assert readiness_route.status_code == 200
    assert readiness_route.json() == readiness
    assert _release_ids(factory) == [(v1_id, 1, True)]

    # -- Approve architect; the preview is now publishable.
    _approve(client, architect_run["run_id"])
    preview = client.get(f"{_PREFIX}/release-preview")
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert [item["agent_key"] for item in preview_body["changed"]] == ["architect", "builder"]
    for item in preview_body["changed"]:
        key = item["agent_key"]
        assert item["published_revision_id"] == v1_mappings[key]
        assert item["field_diffs"][0] == {
            "field": "prompt_text",
            "published": published_prompts[key],
            "candidate": published_prompts[key]
            + (_ARCHITECT_TUNE if key == "architect" else _BUILDER_TUNE),
        }
        assert [diff["field"] for diff in item["field_diffs"]] == ["prompt_text"]
    assert preview_body["next_version_number"] == 2
    assert preview_body["publishable"] is True
    assert preview_body["validation_issues"] == []
    assert preview_body["readiness"]["blocking_agents"] == []
    assert preview_body["draft"]["lock_version"] == lock

    # -- The previous lock is stale: exact 409, nothing written.
    stale = _publish(client, lock - 1)
    assert stale.status_code == 409, stale.text
    assert stale.json() == {
        "code": "stale_publication",
        "expected_lock_version": lock - 1,
        "current_lock_version": lock,
        "active_release": {"release_id": v1_id, "version_number": 1},
        "draft": preview_body["draft"],
    }
    assert _release_ids(factory) == [(v1_id, 1, True)]

    # -- Publish with the current lock: exact 200 (C10).
    published = _publish(client, lock)
    assert published.status_code == 200, published.text
    body = published.json()
    v2_id = body["release"]["release_id"]
    assert v2_id != v1_id
    assert body["release"]["version_number"] == 2
    assert body["release"]["previous_release_id"] == v1_id
    assert body["release"]["published_by"] == _ADMIN
    assert body["release"]["release_note"] == "Tune architect and builder"
    assert body["previous_release_id"] == v1_id
    assert body["changed_agents"] == ["architect", "builder"]
    assert list(body["mappings"]) == list(GRAPH_V1_AGENT_KEYS)
    assert len(body["mappings"]) == 7
    reused = {key for key, mapping in body["mappings"].items() if mapping["reused"]}
    assert reused == set(GRAPH_V1_AGENT_KEYS) - {"architect", "builder"}
    assert len(reused) == 5
    for key in reused:
        assert body["mappings"][key]["agent_definition_revision_id"] == v1_mappings[key]
    new_revisions = {
        key: body["mappings"][key]["agent_definition_revision_id"]
        for key in ("architect", "builder")
    }
    # Each changed role gets a revision no release has mapped before.
    assert len(set(new_revisions.values())) == 2
    assert not set(new_revisions.values()) & set(v1_mappings.values())
    assert _mapping_rows(factory, v2_id) == {
        key: mapping["agent_definition_revision_id"] for key, mapping in body["mappings"].items()
    }
    # Evidence: exactly architect's approved run and builder's SECOND (newest)
    # approved run (C12 item 3).
    assert sorted(
        (item["agent_key"], item["agent_test_run_id"], item["test_case_id"], item["evidence_kind"])
        for item in body["evidence"]
    ) == [
        ("architect", architect_run["run_id"], architect_case, "approval"),
        ("builder", builder_second["run_id"], builder_case, "approval"),
    ]
    assert body["draft"]["base_release_id"] == v2_id
    assert body["draft"]["lock_version"] == lock + 1
    assert _release_ids(factory) == [(v1_id, 1, False), (v2_id, 2, True)]

    # -- The workbench now bases on v2 with nothing changed.
    after = _workbench(client)
    assert after["active_release"]["release_id"] == v2_id
    assert after["draft"]["base_release_id"] == v2_id
    assert after["draft"]["base_version_number"] == 2
    assert after["draft"]["lock_version"] == lock + 1
    assert [node["agent_key"] for node in after["nodes"] if node["changed"]] == []

    # -- Conversations: a new root pins v2; the old root keeps v1.
    with _session_manager_on(factory) as manager:
        new_root = manager.create_session(
            session_id="new-root", created_by=_OWNER, graph_capable=True
        )
        old_again = manager.create_session(
            session_id="old-root", created_by=_OWNER, graph_capable=True
        )
    assert _pin_of(factory, "new-root") == v2_id
    assert (new_root["graph_version"], new_root["is_older_than_active"]) == (2, False)
    assert _pin_of(factory, "old-root") == v1_id
    assert (
        old_again["graph_version"],
        old_again["active_graph_version"],
        old_again["is_older_than_active"],
    ) == (1, 2, True)
    assert _projected_version(factory, "old-root") == ConversationGraphVersion(
        graph_version=1, active_graph_version=2, is_older_than_active=True
    )

    # -- The runtime's loader resolves v2's builder to the mapped revision.
    resolved = PersistedGraphReleaseLoader(session_factory=factory).resolve(v2_id, "builder")
    assert (
        resolved.graph_release_id,
        resolved.graph_version,
        resolved.agent_key,
        resolved.agent_definition_revision_id,
        resolved.content_hash,
    ) == (
        v2_id,
        2,
        "builder",
        new_revisions["builder"],
        body["mappings"]["builder"]["content_hash"],
    )
    assert resolved.content.prompt_text == published_prompts["builder"] + _BUILDER_TUNE
    old_builder = PersistedGraphReleaseLoader(session_factory=factory).resolve(v1_id, "builder")
    assert old_builder.agent_definition_revision_id == v1_mappings["builder"]

    # -- A second POST: the spent lock is stale; the current lock has nothing.
    replay = _publish(client, lock)
    assert replay.status_code == 409, replay.text
    assert replay.json() == {
        "code": "stale_publication",
        "expected_lock_version": lock,
        "current_lock_version": lock + 1,
        "active_release": {"release_id": v2_id, "version_number": 2},
        "draft": after["draft"],
    }
    nothing = _publish(client, lock + 1)
    assert nothing.status_code == 409, nothing.text
    assert nothing.json() == {
        "code": "nothing_to_publish",
        "active_release": {"release_id": v2_id, "version_number": 2},
        "draft": after["draft"],
    }
    assert _release_ids(factory) == [(v1_id, 1, False), (v2_id, 2, True)]


# ---------------------------------------------------------------------------
# The preview's shared parent lock on real PostgreSQL (Task 5 review m4)
# ---------------------------------------------------------------------------

_SNAPSHOT_QUERIES = {
    "graph_release": "SELECT xmin::text, * FROM graph_release ORDER BY id",
    "graph_draft": "SELECT xmin::text, * FROM graph_draft ORDER BY id",
    "graph_draft_agent": "SELECT xmin::text, * FROM graph_draft_agent ORDER BY agent_key",
    "graph_release_agent": (
        "SELECT xmin::text, * FROM graph_release_agent ORDER BY graph_release_id, agent_key"
    ),
    "agent_definition_revision": (
        "SELECT xmin::text, * FROM agent_definition_revision ORDER BY id"
    ),
    "agent_test_case": "SELECT xmin::text, * FROM agent_test_case ORDER BY id",
    "agent_test_run": "SELECT xmin::text, * FROM agent_test_run ORDER BY id",
    "graph_release_test_run": (
        "SELECT xmin::text, * FROM graph_release_test_run "
        "ORDER BY graph_release_id, agent_test_run_id"
    ),
}


def _graph_rows(engine) -> dict[str, list[tuple[object, ...]]]:
    """Every graph row with its ``xmin``: any write, even a no-op UPDATE, moves it."""
    with engine.connect() as conn:
        return {
            table: [tuple(row) for row in conn.execute(text(query))]
            for table, query in _SNAPSHOT_QUERIES.items()
        }


def _preview_ready_state(factory, client) -> None:
    """One changed, approved role, so the preview does real work on every path."""
    _save(client, "architect", _ARCHITECT_TUNE)
    run = _run(client, "architect", _required_case_id(factory, "architect"))
    _approve(client, run["run_id"])


def test_preview_takes_the_shared_parent_lock_first_and_writes_nothing(
    acceptance_stack, postgres_engine
) -> None:
    factory, client, _adapter = acceptance_stack
    _preview_ready_state(factory, client)
    before = _graph_rows(postgres_engine)
    statements: list[str] = []

    def _record(_conn, _cursor, statement, _params, _context, _executemany):
        statements.append(" ".join(statement.upper().split()))

    event.listen(postgres_engine, "after_cursor_execute", _record)
    try:
        preview = client.get(f"{_PREFIX}/release-preview")
    finally:
        event.remove(postgres_engine, "after_cursor_execute", _record)

    assert preview.status_code == 200, preview.text
    assert preview.json()["publishable"] is True
    assert statements, "the preview issued no statement"
    assert all(statement.startswith("SELECT") for statement in statements), [
        statement for statement in statements if not statement.startswith("SELECT")
    ]
    locking = [
        (index, statement)
        for index, statement in enumerate(statements)
        if " FOR SHARE" in statement or " FOR UPDATE" in statement
    ]
    assert [index for index, _ in locking] == [0], locking
    assert locking[0][1].endswith(_SHARED_PARENT_LOCK_TAIL)
    assert "WHERE GRAPH_RELEASE.EFFECTIVE_TO IS NULL" in locking[0][1]
    assert _graph_rows(postgres_engine) == before


def _capture_preview_pid(engine, pids: dict[str, int], parent_lock_seen: threading.Event):
    """Record the backend PID of the connection that sends the parent lock."""

    def _before(conn, _cursor, statement, _params, _context, _executemany):
        if _SHARED_PARENT_LOCK_TAIL in " ".join(statement.upper().split()):
            pids["preview"] = conn.connection.driver_connection.get_backend_pid()
            parent_lock_seen.set()

    event.listen(engine, "before_cursor_execute", _before)
    return _before


def _preview_in_this_context(client: TestClient):
    """A preview GET for a worker thread, carrying the admin user contextvar."""
    context = contextvars.copy_context()
    return lambda: context.run(client.get, f"{_PREFIX}/release-preview")


def test_preview_shares_the_parents_with_a_reader_and_waits_for_a_writer(
    acceptance_stack, postgres_engine
) -> None:
    """Behavioural half of the shared lock.

    * A concurrent ``FOR SHARE`` holder of both parents does not delay the
      preview: an exclusive preview would wait on it.
    * A ``FOR UPDATE`` holder of the draft (a publisher or save) makes the
      preview wait, observed by PID in ``pg_blocking_pids``: a preview that
      locked nothing would not.
    Every wait is bounded, and each holder is rolled back in an inner ``finally``.
    """
    factory, client, _adapter = acceptance_stack
    _preview_ready_state(factory, client)
    before = _graph_rows(postgres_engine)

    # 1. Compatible with a shared holder.
    reader = postgres_engine.connect()
    reader_transaction = reader.begin()
    try:
        reader.execute(text("SET LOCAL lock_timeout = '30s'"))
        assert reader.execute(
            text(
                "SELECT graph_release.id FROM graph_release JOIN graph_draft "
                "ON graph_draft.base_release_id = graph_release.id "
                "WHERE graph_release.effective_to IS NULL "
                "FOR SHARE OF graph_release, graph_draft"
            )
        ).all()
        with ThreadPoolExecutor(max_workers=1) as pool:
            shared = pool.submit(_preview_in_this_context(client))
            try:
                shared_response = shared.result(timeout=_WAIT_SECONDS)
            finally:
                reader_transaction.rollback()
    finally:
        reader.close()
    assert shared_response.status_code == 200, shared_response.text
    assert shared_response.json()["publishable"] is True

    # 2. Waits behind an exclusive draft holder.
    pids: dict[str, int] = {}
    parent_lock_seen = threading.Event()
    listener = _capture_preview_pid(postgres_engine, pids, parent_lock_seen)
    writer = postgres_engine.connect()
    writer_transaction = writer.begin()
    try:
        writer_pid = writer.execute(text("SELECT pg_backend_pid()")).scalar()
        assert writer.execute(text("SELECT id FROM graph_draft FOR UPDATE")).all()
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(_preview_in_this_context(client))
            try:
                assert parent_lock_seen.wait(_WAIT_SECONDS), "preview never sent L0"
                assert _await_blocked_by(
                    postgres_engine, waiter_pid=pids["preview"], blocker_pid=writer_pid
                ), "the preview was never blocked by the exclusive draft holder"
                assert not waiting.done()
            finally:
                writer_transaction.rollback()
            waited_response = waiting.result(timeout=_WAIT_SECONDS)
    finally:
        event.remove(postgres_engine, "before_cursor_execute", listener)
        writer.close()
    assert waited_response.status_code == 200, waited_response.text
    assert waited_response.json()["publishable"] is True
    assert _graph_rows(postgres_engine) == before
