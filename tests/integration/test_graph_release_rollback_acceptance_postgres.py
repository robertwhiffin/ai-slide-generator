"""#270 Task 9: real-PostgreSQL HTTP acceptance — restoring v3 while v7 is active produces v8.

Everything goes through the shipped admin router over a throwaway PostgreSQL database:
draft saves, candidate test-run route, verdict route, publication route, and #270's
history, comparison, preview and rollback routes.  The only doubles are the same as
#269's Task 8 acceptance:

* ``get_db`` bound to the throwaway database;
* the remote endpoint validator accepting (``FakeModelEndpointCatalog``);
* ``get_agent_test_workbench`` returning an ``AgentTestWorkbench`` whose runtime
  loads the persisted release and answers through the deterministic fake model
  adapter (Correction 53 / C38 fake-adapter row).

The ``acceptance_stack`` fixture is copied (not imported) from
``test_graph_release_publication_acceptance_postgres.py`` so none of that module's
tests are re-collected here (C53).

Correction 5 (I4) governs the expected values for builder:
* builder is changed only at n == 3; v4-v7 reuse v3's builder revision.
* Step 5 comparison: architect ``same_revision: false``; builder and the other five
  ``same_revision: true``.
* Step 6 draft_effect: ``architect: "reset"``, ``fixer: "kept"``,
  all five others (including builder): ``"unchanged"``.

A burned id (id 2) is produced before the first publish by installing a deferred
commit trigger, so ids and version numbers diverge throughout:
  v1=id 1, id 2 burned, v2=id 3, v3=id 4, v4=id 5, v5=id 6, v6=id 7, v7=id 8, v8=id 9.
"""

from __future__ import annotations

import contextlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.api.routes import _authz
from src.api.routes import agent_definitions as agent_definition_routes
from src.api.routes.agent_definitions import router as agent_definition_router
from src.api.services.session_manager import SessionManager
from src.core.database import get_db
from src.core.user_context import set_current_user
from src.services.agent_runtime import AgentRuntime
from src.services.agent_runtime_identity import RecordingAgentInvocationIdentitySink
from src.services.agent_test_workbench import AgentTestWorkbench
from src.services.graph_configuration import CatalogRemoteEndpointDraftValidator, GraphConfiguration
from src.services.graph_definition_manifest import GRAPH_V1_AGENT_KEYS
from src.services.model_endpoint_catalog import FakeModelEndpointCatalog
from src.services.persisted_graph_release import PersistedGraphReleaseLoader
from tests.fixtures.deterministic_model_adapter import DeterministicFakeModelAdapter
from tests.integration.test_graph_release_publication_acceptance_postgres import (
    _approve,
    _mapping_rows,
    _pin_of,
    _publish,
    _release_ids,
    _required_case_id,
    _run,
    _save,
    _workbench,
)
from tests.integration.test_graph_release_publication_postgres import (
    _drop_commit_failure,
    _install_commit_failure,
)

pytestmark = pytest.mark.postgres

_PREFIX = "/api/admin/agent-definitions"
_ADMIN = "task9-admin@example.com"
_OWNER = "owner@example.com"

#: Expected (id, version, is_active) sequence after v7, with burned id 2.
_V1_TO_V7_PAIRS = [
    (1, 1, False),
    (3, 2, False),
    (4, 3, False),
    (5, 4, False),
    (6, 5, False),
    (7, 6, False),
    (8, 7, True),
]
_V3_ID = 4
_V7_ID = 8
_V8_ID = 9


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
    # One override covers runs, verdicts, readiness, preview, publish and rollback (C53).
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

    from unittest.mock import patch

    with patch("src.api.services.session_manager.get_db_session", managed_session):
        yield SessionManager()


# ---------------------------------------------------------------------------
# The acceptance flow
# ---------------------------------------------------------------------------


def test_restore_v3_while_v7_active_over_http(acceptance_stack, postgres_engine) -> None:
    """Restoring v3 while v7 is active produces v8, all over the shipped admin HTTP routes.

    Corrections applied:
    * C1  — real clock used throughout (Correction 1 step 4: PostgreSQL only);
    * C5  — builder changed at v3 only; draft_effect for builder is "unchanged";
    * C53 — one workbench override covers runs, verdicts, readiness and publish.

    Ids diverge from versions: id 2 is burned by a deferred commit trigger before v2's
    first publish, so the (id, version) pairs are (1,1), (3,2), (4,3), …, (8,7), (9,8).
    """
    factory, client, _adapter = acceptance_stack

    # -- Initial state: v1 active, lock 0, one required case per role.
    initial = _workbench(client)
    v1_id = initial["active_release"]["release_id"]
    assert initial["active_release"]["version_number"] == 1
    assert v1_id == 1

    arch_case = _required_case_id(factory, "architect")
    builder_case = _required_case_id(factory, "builder")
    fixer_case = _required_case_id(factory, "fixer")
    v1_mappings = _mapping_rows(factory, v1_id)
    assert set(v1_mappings) == set(GRAPH_V1_AGENT_KEYS)

    # -- Build v2..v7: architect changes at every step; builder changes at v3 only.
    run_ids: dict[int, int] = {}  # version_number -> architect's approved run id
    builder_run_id: int | None = None

    for n in range(2, 8):
        # Save architect draft (+n suffix, cumulative over the active content).
        _save(client, "architect", f"\n\n+{n}")

        # At v3: also save builder.
        if n == 3:
            _save(client, "builder", "\n\n+3")

        # Run and approve architect's required case.
        arch_run = _run(client, "architect", arch_case)
        assert (
            arch_run["execution_status"],
            arch_run["deterministic_checks_passed"],
        ) == ("completed", True), arch_run
        _approve(client, arch_run["run_id"])
        run_ids[n] = arch_run["run_id"]

        # At v3: run and approve builder's required case.
        if n == 3:
            b_run = _run(client, "builder", builder_case)
            assert (
                b_run["execution_status"],
                b_run["deterministic_checks_passed"],
            ) == ("completed", True), b_run
            _approve(client, b_run["run_id"])
            builder_run_id = b_run["run_id"]

        # At v2: burn id 2 with a deferred commit trigger so ids ≠ versions throughout.
        if n == 2:
            lock = _workbench(client)["draft"]["lock_version"]
            _install_commit_failure(postgres_engine)
            with pytest.raises(IntegrityError, match="injected commit failure"):
                _publish(client, lock, note="v2-burn-id2")
            assert _drop_commit_failure(postgres_engine) == 1
            # id 2 is now burned; the next publish allocates id 3 for v2.

        # Publish; re-read lock (burn attempt did not change it).
        lock = _workbench(client)["draft"]["lock_version"]
        result = _publish(client, lock, note=f"publish v{n}")
        assert result.status_code == 200, result.text
        body = result.json()
        assert body["release"]["version_number"] == n

    assert builder_run_id is not None, "builder_run_id was never set (v3 path not reached)"

    # Verify the (id, version, is_active) sequence.
    assert _release_ids(factory) == _V1_TO_V7_PAIRS
    v3_mappings = _mapping_rows(factory, _V3_ID)

    # -- Step 2: create conversation c7 (pins v7).
    with _session_manager_on(factory) as manager:
        manager.create_session(session_id="c7-t9", created_by=_OWNER, graph_capable=True)
    assert _pin_of(factory, "c7-t9") == _V7_ID

    # -- Step 3: PUT a pending fixer edit — no approval.
    _save(client, "fixer", "\n\npending-fixer")

    # -- Step 4: GET /releases — versions [7..1], v7 active.
    history_resp = client.get(f"{_PREFIX}/releases")
    assert history_resp.status_code == 200, history_resp.text
    history_body = history_resp.json()
    assert history_body["active_release"] == {"release_id": _V7_ID, "version_number": 7}
    versions = [e["version_number"] for e in history_body["releases"]]
    assert versions == list(range(7, 0, -1)), versions

    # -- Step 5: GET /releases/3/comparison — architect differs; builder and other five same.
    #
    # Derivation per C5:
    #   same_revision is (v7 revision id == v3 revision id).
    #   architect: v3 got a new revision; v4-v7 each changed it again → NOT same.
    #   builder: v3 introduced the only new builder revision; v4-v7 reused it → SAME.
    #   other five: never changed → always SAME.
    comp_resp = client.get(f"{_PREFIX}/releases/3/comparison")
    assert comp_resp.status_code == 200, comp_resp.text
    comp = comp_resp.json()
    assert comp["active_release"] == {"release_id": _V7_ID, "version_number": 7}
    assert comp["release"] == {"release_id": _V3_ID, "version_number": 3}

    agents_by_key = {a["agent_key"]: a for a in comp["agents"]}
    assert [a["agent_key"] for a in comp["agents"]] == list(GRAPH_V1_AGENT_KEYS)

    arch_comp = agents_by_key["architect"]
    assert arch_comp["same_revision"] is False, arch_comp
    assert len(arch_comp["field_diffs"]) == 1, arch_comp["field_diffs"]
    diff = arch_comp["field_diffs"][0]
    assert diff["field"] == "prompt_text"
    # Read v3 and v7 texts from the history detail endpoints (avoids hard-coding the seed).
    v3_detail = client.get(f"{_PREFIX}/releases/3").json()
    v7_detail = client.get(f"{_PREFIX}/releases/7").json()
    arch_v3_prompt = v3_detail["definitions"]["architect"]["content"]["prompt_text"]
    arch_v7_prompt = v7_detail["definitions"]["architect"]["content"]["prompt_text"]
    assert diff == {
        "field": "prompt_text",
        "active": arch_v7_prompt,
        "historical": arch_v3_prompt,
    }

    for role in (
        "data_analyst",
        "builder",
        "build_reviewer",
        "fixer",
        "fix_reviewer",
        "deck_reviewer",
    ):
        assert agents_by_key[role]["same_revision"] is True, agents_by_key[role]
        assert agents_by_key[role]["field_diffs"] == [], agents_by_key[role]

    # -- Step 6: GET /releases/3/rollback-preview.
    #
    # draft_effect derivation (Q7 default, Correction 35):
    #   architect: draft == v7's published; v3 differs from v7 → "reset"
    #   builder:   draft == v3's builder == v7's builder (same revision); v3 restored hash
    #              == v7's published hash → "unchanged"
    #   fixer:     draft has a pending edit (PUT above) → draft ≠ v7's published → "kept"
    #   other four (data_analyst, build_reviewer, fix_reviewer, deck_reviewer):
    #              draft == v7's published == v3's published → "unchanged"
    preview_resp = client.get(f"{_PREFIX}/releases/3/rollback-preview")
    assert preview_resp.status_code == 200, preview_resp.text
    preview = preview_resp.json()

    assert preview["source"] == {"release_id": _V3_ID, "version_number": 3}
    assert preview["active_release"] == {"release_id": _V7_ID, "version_number": 7}
    assert preview["next_version_number"] == 8
    assert preview["restorable"] is True
    assert preview["blocked"] is None
    assert preview["issues"] == []
    assert preview["warnings"] == []

    expected_effect = {
        "architect": "reset",
        "data_analyst": "unchanged",
        "builder": "unchanged",
        "build_reviewer": "unchanged",
        "fixer": "kept",
        "fix_reviewer": "unchanged",
        "deck_reviewer": "unchanged",
    }
    assert preview["draft_effect"] == expected_effect

    # Evidence: v3's two approval runs (architect R3, builder B3).
    assert sorted(
        (item["agent_key"], item["agent_test_run_id"], item["test_case_id"])
        for item in preview["evidence"]
    ) == sorted([
        ("architect", run_ids[3], arch_case),
        ("builder", builder_run_id, builder_case),
    ])

    # -- Step 7: POST /releases/3/rollback — exact 200 with all assertions.
    lock_for_rollback = preview["lock_version"]
    rollback_resp = client.post(
        f"{_PREFIX}/releases/3/rollback",
        json={
            "lock_version": lock_for_rollback,
            "release_note": "Roll back to Graph Version 3.",
        },
    )
    assert rollback_resp.status_code == 200, rollback_resp.text
    rb = rollback_resp.json()

    assert rb["release"]["version_number"] == 8
    assert rb["release"]["release_id"] == _V8_ID
    assert rb["restored_from"] == {"release_id": _V3_ID, "version_number": 3}
    assert rb["previous_release_id"] == _V7_ID

    # Seven mappings reused, each equal to v3's mapping.
    assert list(rb["mappings"]) == list(GRAPH_V1_AGENT_KEYS)
    for key in GRAPH_V1_AGENT_KEYS:
        assert rb["mappings"][key]["reused"] is True, key
        assert rb["mappings"][key]["agent_definition_revision_id"] == v3_mappings[key], key

    # Evidence: v3's two approval runs linked as historical_restore with source_release_id = v3.
    assert sorted(
        (
            item["agent_key"],
            item["agent_test_run_id"],
            item["test_case_id"],
            item["evidence_kind"],
            item["source_release_id"],
        )
        for item in rb["evidence"]
    ) == sorted([
        ("architect", run_ids[3], arch_case, "historical_restore", _V3_ID),
        ("builder", builder_run_id, builder_case, "historical_restore", _V3_ID),
    ])

    assert rb["draft_effect"] == expected_effect

    # -- Step 8: A second identical POST — exact 409 stale_rollback naming v8.
    second_post = client.post(
        f"{_PREFIX}/releases/3/rollback",
        json={
            "lock_version": lock_for_rollback,
            "release_note": "Roll back to Graph Version 3.",
        },
    )
    assert second_post.status_code == 409, second_post.text
    stale = second_post.json()
    assert stale["code"] == "stale_rollback"
    assert stale["active_release"] == {"release_id": _V8_ID, "version_number": 8}

    # -- Step 9: GET /releases — v8 first; v3 restored_by [v8]; no other restores.
    history2_resp = client.get(f"{_PREFIX}/releases")
    assert history2_resp.status_code == 200, history2_resp.text
    history2 = history2_resp.json()
    assert history2["active_release"] == {"release_id": _V8_ID, "version_number": 8}
    versions2 = [e["version_number"] for e in history2["releases"]]
    assert versions2 == list(range(8, 0, -1)), versions2

    entries_by_version = {e["version_number"]: e for e in history2["releases"]}

    v8_entry = entries_by_version[8]
    assert v8_entry["is_active"] is True
    assert v8_entry["restored_from"] == {"release_id": _V3_ID, "version_number": 3}
    assert v8_entry["previous"] == {"release_id": _V7_ID, "version_number": 7}
    assert v8_entry["restored_by"] == []

    v3_entry = entries_by_version[3]
    assert v3_entry["restored_by"] == [{"release_id": _V8_ID, "version_number": 8}]
    assert v3_entry["restored_from"] is None
    assert v3_entry["is_active"] is False

    for version in range(1, 8):
        entry = entries_by_version[version]
        assert entry["is_active"] is False
        if version != 3:
            assert entry["restored_by"] == [], version
        assert entry["restored_from"] is None, version

    # Exact (id, version, is_active) sequence including v8.
    assert _release_ids(factory) == [
        *_V1_TO_V7_PAIRS[:-1],  # v1..v6 all inactive
        (_V7_ID, 7, False),     # v7 now closed
        (_V8_ID, 8, True),      # v8 active
    ]

    # -- Step 10: c7 still pins v7; a new conversation pins v8.
    assert _pin_of(factory, "c7-t9") == _V7_ID

    with _session_manager_on(factory) as manager:
        manager.create_session(session_id="c8-t9", created_by=_OWNER, graph_capable=True)
    assert _pin_of(factory, "c8-t9") == _V8_ID

    # -- Step 11: GET workbench — base v8; architect and builder clean; fixer changed.
    post_rb_wb = _workbench(client)
    assert post_rb_wb["active_release"]["version_number"] == 8
    assert post_rb_wb["active_release"]["release_id"] == _V8_ID
    assert post_rb_wb["draft"]["base_release_id"] == _V8_ID

    changed_by_role = {n["agent_key"]: n["changed"] for n in post_rb_wb["nodes"]}
    assert changed_by_role["architect"] is False, "architect must be clean after rollback reset"
    assert changed_by_role["builder"] is False, "builder must be clean (restored == unchanged)"
    assert changed_by_role["fixer"] is True, "fixer's pending edit must survive the rollback"

    # -- Step 12: POST /releases — 409 publication_not_ready naming fixer's case only.
    current_lock = post_rb_wb["draft"]["lock_version"]
    not_ready_resp = _publish(client, current_lock, note="should not publish")
    assert not_ready_resp.status_code == 409, not_ready_resp.text
    not_ready = not_ready_resp.json()
    assert not_ready["code"] == "publication_not_ready"
    gap_keys = [gap["agent_key"] for gap in not_ready["gaps"]]
    assert gap_keys == ["fixer"], f"expected only fixer's gap, got {gap_keys}"
    assert not_ready["gaps"][0]["test_case_id"] == fixer_case
    assert not_ready["gaps"][0]["code"] == "no_eligible_approval"
