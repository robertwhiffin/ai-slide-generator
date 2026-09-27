from __future__ import annotations

import builtins
import json
import math
import pathlib
import re
import sys
from collections.abc import Callable, Iterator
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, event, select, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register the complete ORM metadata
from src.api.routes import _authz
from src.api.routes import agent_definitions as agent_definition_routes
from src.api.routes.agent_definitions import router
from src.api.schemas.agent_definitions import (
    CustomTextBlockRequest,
    DraftDefinitionResponse,
    DraftLockRequest,
    DraftSaveConflictResponse,
    DraftSaveConflictServerResponse,
    DraftSaveRequest,
    EditableAssemblyRulesRequest,
    EditableModelDraftModelRequest,
    EditableModelDraftRequest,
    EditableSchemaOverlayRequest,
)
from src.core.database import Base, get_db
from src.core.prompt_modules import DESIGN_SYSTEM_PRECEDENCE
from src.core.skills.build_reviewer import (
    BUILD_REVIEWER_CRITERIA_STAGE,
    DECK_BRIEF_REVIEW,
)
from src.core.skills.build_reviewer import (
    INSTRUCTIONS as BUILD_REVIEWER_V1_PROMPT,
)
from src.core.skills.data_analyst import ANALYST_AUTHORED_INSTRUCTIONS
from src.core.skills.data_analyst import (
    INSTRUCTIONS as ANALYST_V1_PROMPT,
)
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
    DraftValidationIssue,
    GraphConfiguration,
    GraphConfigurationIntegrityError,
)
from src.services.agent_schema_registry import (
    SCHEMA_CONTRACT_BUNDLES,
)
from src.services.graph_configuration_content import definition_content_from_row
from src.services.graph_definition_manifest import load_graph_v1_manifest
from src.services.model_endpoint_catalog import (
    EndpointValidationFailure,
    FakeModelEndpointCatalog,
    ModelEndpointCatalogFailure,
    SystemModelDiscovery,
    SystemModelEndpoint,
)
from src.services.model_endpoint_probe import (
    DatabricksStructuredOutputProbe,
    FakeStructuredOutputProbe,
    StructuredOutputProbeFailure,
)
from src.services.prompt_assembler import ROLE_UNTRUSTED_DATA_NOTICE

EXPECTED_TOPOLOGY_ORDER = [
    "architect",
    "data_analyst",
    "builder",
    "build_reviewer",
    "foreman",
    "fixer",
    "fix_reviewer",
    "deck_reviewer",
]
EXPECTED_DISPLAY_NAMES = [
    "Architect",
    "Data Analyst",
    "Builder",
    "Build Reviewer",
    "Foreman",
    "Fixer",
    "Fix Reviewer",
    "Deck Reviewer",
]
EXPECTED_FOREMAN_NODE = {
    "agent_key": "foreman",
    "display_name": "Foreman",
    "execution_kind": "deterministic",
    "editable": False,
    "changed": False,
    "published": None,
    "draft": None,
    "read_only_reason": (
        "Foreman is deterministic scheduling and routing code; it has no Agent Definition."
    ),
}
LOWERCASE_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@pytest.fixture(autouse=True)
def _reset_admin_identity() -> Iterator[None]:
    set_current_user(None)
    _authz.reset_admin_cache()
    try:
        yield
    finally:
        set_current_user(None)
        _authz.reset_admin_cache()


@pytest.fixture
def session_factory() -> Iterator[sessionmaker]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    GraphConfiguration().bootstrap_v1(factory)
    try:
        yield factory
    finally:
        engine.dispose()


def _accepting_remote_endpoint_validator() -> CatalogRemoteEndpointDraftValidator:
    """Route-test default: every remote endpoint check accepts, with no SDK client."""
    return CatalogRemoteEndpointDraftValidator(FakeModelEndpointCatalog)


def _app_for(
    session_factory: sessionmaker,
    *,
    raise_server_exceptions: bool = True,
    catalog: object | None = None,
    remote_endpoint_validator: object | None = None,
    production_endpoint_validation: bool = False,
    probe: object | None = None,
    production_probe: bool = False,
) -> TestClient:
    """Build the admin router over SQLite.

    The PUT's production remote endpoint validator is replaced by an accepting
    fake unless a test injects its own or asks for the production dependency;
    a discovery catalog is injected only when a test supplies one.  The
    structured-output probe is likewise a succeeding fake unless a test injects
    its own or asks for the production dependency, so no test reaches Databricks.
    """
    app = FastAPI()
    app.include_router(router)

    def _override_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    if not production_endpoint_validation:
        validator = (
            remote_endpoint_validator
            if remote_endpoint_validator is not None
            else _accepting_remote_endpoint_validator()
        )
        app.dependency_overrides[
            agent_definition_routes.get_remote_endpoint_draft_validator
        ] = lambda: validator
    if catalog is not None:
        app.dependency_overrides[agent_definition_routes.get_model_endpoint_catalog] = (
            lambda: catalog
        )
    if not production_probe:
        structured_output_probe = probe if probe is not None else FakeStructuredOutputProbe()
        app.dependency_overrides[agent_definition_routes.get_structured_output_probe] = (
            lambda: structured_output_probe
        )
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def _force_admin(monkeypatch: pytest.MonkeyPatch, *, is_admin: bool) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    set_current_user("task4-user@example.com")
    monkeypatch.setattr(_authz, "_admin_acl_probe", lambda _user: is_admin)
    _authz.reset_admin_cache()


def _model_nodes(body: dict[str, object]) -> list[dict[str, object]]:
    nodes = body["nodes"]
    assert isinstance(nodes, list)
    return [node for node in nodes if node["execution_kind"] == "model"]


def _draft_save_url(agent_key: str = "architect") -> str:
    return f"/api/admin/agent-definitions/draft/{agent_key}"


def _editable_candidate(node: dict[str, object], **updates: object) -> dict[str, object]:
    draft = node["draft"]
    assert isinstance(draft, dict)
    model = draft["model"]
    assert isinstance(model, dict)
    candidate: dict[str, object] = {
        "prompt_text": draft["prompt_text"],
        "model": {
            "endpoint_name": model["endpoint_name"],
            "temperature": model["temperature"],
            "max_tokens": model["max_tokens"],
            "top_p": model["top_p"],
        },
    }
    for path, value in updates.items():
        if path.startswith("model."):
            candidate_model = candidate["model"]
            assert isinstance(candidate_model, dict)
            candidate_model[path.removeprefix("model.")] = value
        else:
            candidate[path] = value
    return candidate


def _workbench(client: TestClient) -> dict[str, object]:
    response = client.get("/api/admin/agent-definitions/workbench")
    assert response.status_code == 200
    return response.json()


def _model_node(body: dict[str, object], agent_key: str) -> dict[str, object]:
    return next(node for node in _model_nodes(body) if node["agent_key"] == agent_key)


def test_admin_workbench_returns_exact_typed_v1_contract(session_factory, monkeypatch):
    _force_admin(monkeypatch, is_admin=True)

    with _app_for(session_factory) as client:
        response = client.get("/api/admin/agent-definitions/workbench")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"active_release", "draft", "nodes"}
    assert set(body["active_release"]) == {
        "release_id",
        "version_number",
        "previous_release_id",
        "restored_from_release_id",
        "release_note",
        "published_by",
        "published_at",
        "effective_from",
        "effective_to",
    }
    assert body["active_release"]["version_number"] == 1
    assert body["active_release"]["previous_release_id"] is None
    assert body["active_release"]["restored_from_release_id"] is None
    assert body["active_release"]["published_by"] == "system:bootstrap"
    assert body["active_release"]["effective_to"] is None
    assert set(body["draft"]) == {
        "draft_id",
        "base_release_id",
        "base_version_number",
        "lock_version",
        "updated_by",
        "updated_at",
    }
    assert body["draft"]["base_release_id"] == body["active_release"]["release_id"]
    assert body["draft"]["base_version_number"] == 1
    assert body["draft"]["lock_version"] == 0
    assert body["draft"]["updated_by"] == "system:bootstrap"

    assert [node["agent_key"] for node in body["nodes"]] == EXPECTED_TOPOLOGY_ORDER
    assert [node["display_name"] for node in body["nodes"]] == EXPECTED_DISPLAY_NAMES
    assert body["nodes"][4] == EXPECTED_FOREMAN_NODE

    assert len(_model_nodes(body)) == 7
    for node in _model_nodes(body):
        assert set(node) == {
            "agent_key",
            "display_name",
            "execution_kind",
            "editable",
            "changed",
            "published",
            "draft",
            "read_only_reason",
        }
        assert node["editable"] is True
        assert node["changed"] is False
        assert node["read_only_reason"] is None
        published = node["published"]
        draft = node["draft"]
        assert set(published) == {
            "revision_id",
            "content_hash",
            "definition_version",
            "prompt_text",
            "model",
            "schema_overlay",
            "assembly_rules",
            "protected_assembly",
            "schema_contract",
            "protected_stage_view",
            "selectable_optional_fields",
            "canonical_fields",
        }
        assert set(draft) == {
            "base_revision_id",
            "candidate_hash",
            "definition_version",
            "prompt_text",
            "model",
            "schema_overlay",
            "assembly_rules",
            "protected_assembly",
            "schema_contract",
            "protected_stage_view",
            "selectable_optional_fields",
            "canonical_fields",
        }
        assert draft["base_revision_id"] == published["revision_id"]
        assert published["definition_version"] == 2
        assert draft["definition_version"] == 2
        assert LOWERCASE_SHA256.fullmatch(published["content_hash"])
        assert LOWERCASE_SHA256.fullmatch(draft["candidate_hash"])
        assert published["content_hash"] == draft["candidate_hash"]
        assert published["prompt_text"]
        assert draft["prompt_text"] == published["prompt_text"]
        assert published["model"] == {
            "endpoint_name": "databricks-claude-opus-4-6",
            "temperature": 0.7,
            "max_tokens": 60000,
            "top_p": 0.95,
        }
        assert set(published["schema_overlay"]) == {
            "field_overrides",
            "additional_optional_fields",
        }
        assert published["selectable_optional_fields"] == []
        assert set(published["assembly_rules"]) == {
            "format_version",
            "separator",
            "blocks",
        }
        assert published["assembly_rules"]["format_version"] == 1
        assert published["assembly_rules"]["separator"] == "\n\n"
        assert set(published["protected_assembly"]) == {"version", "digest"}
        assert set(published["schema_contract"]) == {"version", "digest"}


def test_base_revision_is_derived_from_base_release_mapping(session_factory, monkeypatch):
    with session_factory.begin() as session:
        draft = session.scalar(
            select(GraphDraftAgent).where(GraphDraftAgent.agent_key == "architect")
        )
        assert draft is not None
        content = definition_content_from_row(draft).model_copy(
            update={"prompt_text": draft.prompt_text + "\n\nCandidate edit."}
        )
        draft.prompt_text = content.prompt_text
        from src.services.graph_definition_manifest import definition_content_hash

        draft.candidate_hash = definition_content_hash(content)
        session.get(GraphDraft, 1).lock_version = 1

    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        response = client.get("/api/admin/agent-definitions/workbench")

    assert response.status_code == 200
    body = response.json()
    architect = body["nodes"][0]
    assert architect["changed"] is True
    assert architect["draft"]["base_revision_id"] == architect["published"]["revision_id"]
    assert architect["draft"]["candidate_hash"] != architect["published"]["content_hash"]
    assert body["draft"]["lock_version"] == 1


def test_non_admin_is_denied_before_prompts_or_service_are_loaded(session_factory, monkeypatch):
    _force_admin(monkeypatch, is_admin=False)
    calls: list[str] = []

    def _must_not_read(_service, _session):
        calls.append("read_workbench")
        raise AssertionError("authorization reached the graph read service")

    monkeypatch.setattr(GraphConfiguration, "read_workbench", _must_not_read)
    with _app_for(session_factory, raise_server_exceptions=False) as client:
        response = client.get("/api/admin/agent-definitions/workbench")

    assert calls == []
    assert response.status_code == 403
    assert "prompt_text" not in response.text


def test_read_workbench_does_not_import_or_fallback_to_v1_manifest(session_factory, monkeypatch):
    generated_module = "src.services.agent_definition_manifest_v1"
    load_graph_v1_manifest.cache_clear()
    sys.modules.pop(generated_module, None)
    real_import = builtins.__import__
    attempted: list[str] = []

    def _guarded_import(name, *args, **kwargs):
        if name == generated_module:
            attempted.append(name)
            raise AssertionError("read path imported the frozen v1 manifest")
        return real_import(name, *args, **kwargs)

    try:
        monkeypatch.setattr(builtins, "__import__", _guarded_import)
        with session_factory() as session:
            snapshot = GraphConfiguration().read_workbench(session)

        assert snapshot.active_release.version_number == 1
        assert attempted == []
        assert generated_module not in sys.modules
    finally:
        load_graph_v1_manifest.cache_clear()
        sys.modules.pop(generated_module, None)


Mutation = Callable[[sessionmaker], None]


def _remove_release_mapping(factory: sessionmaker) -> None:
    with factory.begin() as session:
        session.execute(delete(GraphReleaseAgent).where(GraphReleaseAgent.agent_key == "architect"))


def _remove_draft_agent(factory: sessionmaker) -> None:
    with factory.begin() as session:
        session.execute(delete(GraphDraftAgent).where(GraphDraftAgent.agent_key == "architect"))


def _corrupt_revision_hash(factory: sessionmaker) -> None:
    with factory.begin() as session:
        session.execute(
            update(AgentDefinitionRevision)
            .where(AgentDefinitionRevision.agent_key == "architect")
            .values(prompt_text="corrupt published prompt")
        )


def _corrupt_draft_hash(factory: sessionmaker) -> None:
    with factory.begin() as session:
        session.execute(
            update(GraphDraftAgent)
            .where(GraphDraftAgent.agent_key == "architect")
            .values(prompt_text="corrupt draft prompt")
        )


def _remove_active_release(factory: sessionmaker) -> None:
    with factory.begin() as session:
        release = session.scalar(select(GraphRelease))
        release.effective_to = release.effective_from + timedelta(seconds=1)


def _make_mapping_role_incompatible(factory: sessionmaker) -> None:
    engine = factory.kw["bind"]
    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute(
            "UPDATE agent_definition_revision SET agent_key = 'builder' "
            "WHERE agent_key = 'architect'"
        )
        raw.commit()
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        raw.close()


def _insert_extra_draft_parent(factory: sessionmaker) -> None:
    engine = factory.kw["bind"]
    raw = engine.raw_connection()
    cursor = raw.cursor()
    try:
        cursor.execute("PRAGMA ignore_check_constraints=ON")
        cursor.execute(
            "INSERT INTO graph_draft "
            "(id, base_release_id, lock_version, updated_by, updated_at) "
            "SELECT 2, base_release_id, lock_version, updated_by, updated_at "
            "FROM graph_draft WHERE id = 1"
        )
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        cursor.execute("PRAGMA ignore_check_constraints=OFF")
        raw.close()


def _insert_out_of_singleton_draft_agent(factory: sessionmaker) -> None:
    engine = factory.kw["bind"]
    raw = engine.raw_connection()
    cursor = raw.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute(
            "INSERT INTO graph_draft_agent ("
            "graph_draft_id, agent_key, candidate_hash, definition_version, "
            "prompt_text, endpoint_name, temperature, max_tokens, top_p, "
            "schema_overlay, assembly_rules, protected_assembly_version, "
            "protected_assembly_digest, schema_contract_version, "
            "schema_contract_digest"
            ") SELECT 2, agent_key, candidate_hash, definition_version, "
            "prompt_text, endpoint_name, temperature, max_tokens, top_p, "
            "schema_overlay, assembly_rules, protected_assembly_version, "
            "protected_assembly_digest, schema_contract_version, "
            "schema_contract_digest FROM graph_draft_agent "
            "WHERE graph_draft_id = 1 AND agent_key = 'architect'"
        )
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        cursor.execute("PRAGMA foreign_keys=ON")
        raw.close()


def _rekey_singleton_draft_to_two(factory: sessionmaker) -> None:
    engine = factory.kw["bind"]
    raw = engine.raw_connection()
    cursor = raw.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("PRAGMA ignore_check_constraints=ON")
        cursor.execute("UPDATE graph_draft_agent SET graph_draft_id = 2 WHERE graph_draft_id = 1")
        cursor.execute("UPDATE graph_draft SET id = 2 WHERE id = 1")
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        cursor.execute("PRAGMA ignore_check_constraints=OFF")
        cursor.execute("PRAGMA foreign_keys=ON")
        raw.close()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (_remove_release_mapping, "active release does not have the exact role mapping set"),
        (_remove_draft_agent, "shared draft does not have the exact role key set"),
        (_corrupt_revision_hash, "revision 1 content hash does not match persisted content"),
        (_corrupt_draft_hash, "draft role architect content hash does not match persisted content"),
        (_remove_active_release, "graph configuration must have exactly one active release"),
        (_make_mapping_role_incompatible, "active release has a role-incompatible mapping"),
        (
            _insert_extra_draft_parent,
            "graph configuration must have exactly one singleton draft",
        ),
        (
            _insert_out_of_singleton_draft_agent,
            "shared draft agents must all belong to the singleton draft",
        ),
        (
            _rekey_singleton_draft_to_two,
            "graph configuration must have exactly one singleton draft",
        ),
    ],
)
def test_corrupt_current_graph_fails_closed_with_precise_domain_cause(
    session_factory, mutation: Mutation, message: str
):
    mutation(session_factory)

    with session_factory() as session:
        with pytest.raises(GraphConfigurationIntegrityError, match=f"^{message}$"):
            GraphConfiguration().read_workbench(session)


@pytest.mark.parametrize(
    "mutation",
    [
        _remove_release_mapping,
        _insert_extra_draft_parent,
        _insert_out_of_singleton_draft_agent,
        _rekey_singleton_draft_to_two,
    ],
)
def test_corrupt_graph_maps_to_stable_nonleaking_500(
    session_factory, monkeypatch, mutation: Mutation
):
    mutation(session_factory)
    _force_admin(monkeypatch, is_admin=True)

    with _app_for(session_factory, raise_server_exceptions=False) as client:
        response = client.get("/api/admin/agent-definitions/workbench")

    assert response.status_code == 500
    assert response.json() == {"detail": "Graph configuration is incomplete"}
    assert "architect" not in response.text
    assert "hash" not in response.text


def test_main_app_registers_the_dedicated_workbench_route():
    from src.api.main import app

    expected_methods = {
        "/api/admin/agent-definitions/workbench": {"GET"},
        "/api/admin/agent-definitions/model-endpoints": {"GET"},
        "/api/admin/agent-definitions/draft/{agent_key}": {"PUT"},
        "/api/admin/agent-definitions/draft/{agent_key}/protected-assembly-upgrade": {
            "POST"
        },
        "/api/admin/agent-definitions/draft/{agent_key}/schema-contract-upgrade": {
            "POST"
        },
        "/api/admin/agent-definitions/draft/{agent_key}/legacy-prompt-source": {"POST"},
        "/api/admin/agent-definitions/draft/{agent_key}/model-endpoint-probe": {"POST"},
        "/api/admin/agent-definitions/test-cases": {"GET", "POST"},
        "/api/admin/agent-definitions/test-cases/{test_case_id}": {"PUT", "DELETE"},
        "/api/admin/agent-definitions/draft/{agent_key}/test-runs": {"POST"},
        "/api/admin/agent-definitions/published/{agent_key}/test-runs": {"POST"},
        "/api/admin/agent-definitions/test-runs/{run_id}": {"GET"},
        "/api/admin/agent-definitions/test-cases/{test_case_id}/runs": {"GET"},
        "/api/admin/agent-definitions/test-runs/{run_id}/verdict": {"POST"},
        "/api/admin/agent-definitions/readiness": {"GET"},
        # #269 Task 5: on the one admin router (C31/C35).
        "/api/admin/agent-definitions/release-preview": {"GET"},
        "/api/admin/agent-definitions/releases": {"POST"},
    }
    for path, methods in expected_methods.items():
        matches = [
            route for route in app.routes if getattr(route, "path", None) == path
        ]
        # One route object per method: a path serving two methods has two.
        assert len(matches) == len(methods), path
        assert all(len(route.methods) == 1 for route in matches), path
        assert set().union(*(route.methods for route in matches)) == methods, path
    assert (
        len(
            [
                route
                for route in app.routes
                if str(getattr(route, "path", "")).startswith(
                    "/api/admin/agent-definitions"
                )
            ]
        )
        == sum(len(methods) for methods in expected_methods.values())
    )


def test_put_save_draft_returns_exact_changed_contract_and_preserves_release(
    session_factory, monkeypatch
):
    _force_admin(monkeypatch, is_admin=True)
    submitted_prompt = "Architect draft changed through the admin route."
    submitted_endpoint = " custom-endpoint-name "
    submitted_temperature = 0.25
    submitted_max_tokens = 4096
    submitted_top_p = 0.8
    with _app_for(session_factory) as client:
        before = _workbench(client)
        architect = _model_node(before, "architect")
        payload = {
            "lock_version": before["draft"]["lock_version"],
            "candidate": _editable_candidate(
                architect,
                prompt_text=submitted_prompt,
                **{
                    "model.endpoint_name": submitted_endpoint,
                    "model.temperature": submitted_temperature,
                    "model.max_tokens": submitted_max_tokens,
                    "model.top_p": submitted_top_p,
                },
            ),
        }
        response = client.put(_draft_save_url(), json=payload)
        after = _workbench(client)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"draft", "definition", "changed"}
    assert body["changed"] is True
    assert body["draft"]["lock_version"] == 1
    assert body["draft"]["updated_by"] == "task4-user@example.com"
    assert body["definition"] == _model_node(after, "architect")["draft"]
    for definition in (body["definition"], _model_node(after, "architect")["draft"]):
        assert definition["prompt_text"] == submitted_prompt
        assert definition["model"] == {
            "endpoint_name": submitted_endpoint,
            "temperature": submitted_temperature,
            "max_tokens": submitted_max_tokens,
            "top_p": submitted_top_p,
        }
    assert after["active_release"] == before["active_release"]
    assert after["draft"]["base_release_id"] == before["draft"]["base_release_id"]


def test_put_identical_draft_advances_lock_and_audit_but_reports_unchanged(
    session_factory, monkeypatch
):
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        before = _workbench(client)
        architect = _model_node(before, "architect")
        response = client.put(
            _draft_save_url(),
            json={
                "lock_version": 0,
                "candidate": _editable_candidate(architect),
            },
        )
        after = _workbench(client)

    assert response.status_code == 200
    assert response.json()["changed"] is False
    assert response.json()["draft"]["lock_version"] == 1
    assert response.json()["draft"]["updated_by"] == "task4-user@example.com"
    assert after["draft"]["lock_version"] == 1


def test_put_stale_draft_returns_exact_seven_role_conflict_without_mutation(
    session_factory, monkeypatch
):
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        before = _workbench(client)
        architect = _model_node(before, "architect")
        winning = client.put(
            _draft_save_url(),
            json={
                "lock_version": 0,
                "candidate": _editable_candidate(architect, prompt_text="Winning Architect edit."),
            },
        )
        assert winning.status_code == 200
        stale = client.put(
            _draft_save_url(),
            json={
                "lock_version": 0,
                "candidate": _editable_candidate(architect, prompt_text="Losing Architect edit."),
            },
        )
        after = _workbench(client)

    assert stale.status_code == 409
    body = stale.json()
    assert set(body) == {
        "code",
        "expected_lock_version",
        "current_lock_version",
        "client_candidate",
        "server",
    }
    assert body["code"] == "stale_draft"
    assert body["expected_lock_version"] == 0
    assert body["current_lock_version"] == 1
    assert body["client_candidate"]["prompt_text"] == "Losing Architect edit."
    assert body["server"]["draft"] == after["draft"]
    definitions = body["server"]["definitions"]
    assert set(definitions) == {
        "architect",
        "data_analyst",
        "builder",
        "build_reviewer",
        "fixer",
        "fix_reviewer",
        "deck_reviewer",
    }
    for agent_key, definition in definitions.items():
        assert definition == _model_node(after, agent_key)["draft"]
    assert _model_node(after, "architect")["draft"]["prompt_text"] == "Winning Architect edit."


def test_put_stale_cross_agent_conflict_has_all_current_candidates(session_factory, monkeypatch):
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        initial = _workbench(client)
        architect = _model_node(initial, "architect")
        builder = _model_node(initial, "builder")
        winning = client.put(
            _draft_save_url("builder"),
            json={
                "lock_version": 0,
                "candidate": _editable_candidate(builder, prompt_text="Builder B1."),
            },
        )
        assert winning.status_code == 200
        stale = client.put(
            _draft_save_url("architect"),
            json={
                "lock_version": 0,
                "candidate": _editable_candidate(architect, prompt_text="Architect A2."),
            },
        )
        current = _workbench(client)

    assert stale.status_code == 409
    conflict = stale.json()
    assert conflict["current_lock_version"] == 1
    definitions = conflict["server"]["definitions"]
    assert definitions["architect"]["prompt_text"] == architect["draft"]["prompt_text"]
    assert definitions["builder"]["prompt_text"] == "Builder B1."
    for key in set(definitions) - {"architect", "builder"}:
        assert definitions[key] == _model_node(current, key)["draft"]


@pytest.mark.parametrize(
    ("path", "value", "field", "code", "message"),
    [
        ("lock_version", -1, "lock_version", "out_of_range", ""),
        ("lock_version", "0", "lock_version", "strict_type", ""),
        (
            "candidate.prompt_text",
            " \t ",
            "candidate.prompt_text",
            "blank",
            "Prompt text must not be blank.",
        ),
        ("candidate.prompt_text", 1, "candidate.prompt_text", "strict_type", ""),
        (
            "candidate.model.endpoint_name",
            "\n",
            "candidate.model.endpoint_name",
            "blank",
            "Endpoint name must not be blank.",
        ),
        ("candidate.model.endpoint_name", 1, "candidate.model.endpoint_name", "strict_type", ""),
        (
            "candidate.model.temperature",
            -0.01,
            "candidate.model.temperature",
            "out_of_range",
            "Temperature must be between 0 and 1.",
        ),
        (
            "candidate.model.temperature",
            float("inf"),
            "candidate.model.temperature",
            "finite_number",
            "Temperature must be between 0 and 1.",
        ),
        ("candidate.model.temperature", "0.5", "candidate.model.temperature", "strict_type", ""),
        (
            "candidate.model.max_tokens",
            0,
            "candidate.model.max_tokens",
            "positive_integer",
            "Maximum tokens must be a positive integer.",
        ),
        ("candidate.model.max_tokens", 1.5, "candidate.model.max_tokens", "strict_type", ""),
        (
            "candidate.model.top_p",
            1.1,
            "candidate.model.top_p",
            "out_of_range",
            "Top-p must be between 0 and 1.",
        ),
        (
            "candidate.model.top_p",
            float("nan"),
            "candidate.model.top_p",
            "finite_number",
            "Top-p must be between 0 and 1.",
        ),
        ("candidate.model.top_p", "0.5", "candidate.model.top_p", "strict_type", ""),
        (
            "candidate.model.model_alias",
            "secret",
            "candidate.model.model_alias",
            "extra_forbidden",
            "",
        ),
        ("updated_by", "attacker", "updated_by", "extra_forbidden", ""),
        ("candidate_hash", "f" * 64, "candidate_hash", "extra_forbidden", ""),
        ("release_id", 999, "release_id", "extra_forbidden", ""),
    ],
)
def test_put_rejects_every_protected_or_server_owned_field(
    session_factory, monkeypatch, path, value, field, code, message
):
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        before = _workbench(client)
        payload: dict[str, object] = {
            "lock_version": 0,
            "candidate": _editable_candidate(_model_node(before, "architect")),
        }
        target: dict[str, object] = payload
        parts = path.split(".")
        for part in parts[:-1]:
            next_target = target[part]
            assert isinstance(next_target, dict)
            target = next_target
        target[parts[-1]] = value
        if isinstance(value, float) and not math.isfinite(value):
            response = client.put(
                _draft_save_url(),
                content=json.dumps(payload).encode(),
                headers={"content-type": "application/json"},
            )
        else:
            response = client.put(_draft_save_url(), json=payload)
        after = _workbench(client)

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_draft"
    error = response.json()["errors"][0]
    assert error["field"] == field
    assert error["code"] == code
    if message:
        assert error["message"] == message
    assert after == before


@pytest.mark.parametrize("agent_key", ["unknown", "foreman"])
def test_put_rejects_unknown_or_deterministic_agent_key(session_factory, monkeypatch, agent_key):
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        before = _workbench(client)
        response = client.put(
            _draft_save_url(agent_key),
            json={
                "lock_version": 0,
                "candidate": _editable_candidate(_model_node(before, "architect")),
            },
        )

    assert response.status_code == 422
    assert response.json() == {
        "code": "invalid_draft",
        "errors": [
            {
                "field": "agent_key",
                "code": "unknown_agent",
                "message": "Agent key must identify an editable model role.",
            }
        ],
    }


def test_put_malformed_json_has_stable_root_error(session_factory, monkeypatch):
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        response = client.put(
            _draft_save_url(),
            content=b'{"candidate": ',
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 422
    assert response.json() == {
        "code": "invalid_draft",
        "errors": [
            {
                "field": "$",
                "code": "invalid_json",
                "message": "Request body must be valid JSON.",
            }
        ],
    }


def test_non_admin_put_rejects_before_body_or_writer_and_does_not_echo_secrets(
    session_factory, monkeypatch
):
    _force_admin(monkeypatch, is_admin=False)
    calls: list[str] = []

    def _must_not_write(*_args, **_kwargs):
        calls.append("write")
        raise AssertionError("authorization reached the draft writer")

    async def _must_not_parse_json(_request):
        calls.append("body")
        raise AssertionError("authorization parsed the raw request body")

    monkeypatch.setattr(GraphConfiguration, "save_editable_model_draft", _must_not_write)
    monkeypatch.setattr(agent_definition_routes.Request, "json", _must_not_parse_json)
    with _app_for(session_factory, raise_server_exceptions=False) as client:
        response = client.put(
            _draft_save_url(),
            content=b"{not json; SUPER_SECRET_PROMPT; private-endpoint}",
            headers={"content-type": "application/json"},
        )

    assert calls == []
    assert response.status_code == 403
    assert response.json() == {"detail": "Admin access required"}
    assert "SUPER_SECRET_PROMPT" not in response.text
    assert "private-endpoint" not in response.text


def test_put_projects_ordered_domain_rejection_verbatim_at_route_boundary(
    session_factory, monkeypatch
):
    _force_admin(monkeypatch, is_admin=True)
    first_issue = DraftValidationIssue(
        field="candidate.prompt_text",
        code="policy_rejected",
        message="Prompt violates the configured policy.",
    )
    second_issue = DraftValidationIssue(
        field="candidate.model.endpoint_name",
        code="endpoint_rejected",
        message="Endpoint is not approved for this draft.",
    )

    def _reject_draft(*_args, **_kwargs):
        raise DraftContentRejected(first_issue, second_issue)

    monkeypatch.setattr(GraphConfiguration, "save_editable_model_draft", _reject_draft)
    with _app_for(session_factory) as client:
        before = _workbench(client)
        response = client.put(
            _draft_save_url(),
            json={
                "lock_version": before["draft"]["lock_version"],
                "candidate": _editable_candidate(_model_node(before, "architect")),
            },
        )

    assert response.status_code == 422
    assert response.json() == {
        "code": "invalid_draft",
        "errors": [
            {
                "field": "candidate.prompt_text",
                "code": "policy_rejected",
                "message": "Prompt violates the configured policy.",
            },
            {
                "field": "candidate.model.endpoint_name",
                "code": "endpoint_rejected",
                "message": "Endpoint is not approved for this draft.",
            },
        ],
    }


@pytest.mark.parametrize("principal", [None, " \t "])
def test_put_requires_nonblank_trusted_principal_before_write(
    session_factory, monkeypatch, principal
):
    _force_admin(monkeypatch, is_admin=True)
    set_current_user(principal)
    calls: list[str] = []

    def _must_not_write(*_args, **_kwargs):
        calls.append("write")
        raise AssertionError("missing principal reached the draft writer")

    monkeypatch.setattr(GraphConfiguration, "save_editable_model_draft", _must_not_write)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[agent_definition_routes.require_admin] = lambda: None

    def _override_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.put(
            _draft_save_url(),
            content=b"{not json; should not be parsed}",
            headers={"content-type": "application/json"},
        )

    assert calls == []
    assert response.status_code == 403
    assert response.json() == {"detail": "Authenticated principal required"}


def test_put_persisted_integrity_error_is_nonleaking(session_factory, monkeypatch):
    _force_admin(monkeypatch, is_admin=True)
    _remove_draft_agent(session_factory)
    with _app_for(session_factory, raise_server_exceptions=False) as client:
        response = client.put(
            _draft_save_url(),
            json={
                "lock_version": 0,
                "candidate": {
                    "prompt_text": "candidate secret",
                    "model": {
                        "endpoint_name": "candidate-endpoint",
                        "temperature": 0.7,
                        "max_tokens": 10,
                        "top_p": 0.9,
                    },
                },
            },
        )

    assert response.status_code == 500
    assert response.json() == {"detail": "Graph configuration is incomplete"}
    assert "candidate secret" not in response.text
    assert "candidate-endpoint" not in response.text


# ---------------------------------------------------------------------------
# #265 declarative prompt assembly: strict request parsing, the protected
# assembly upgrade POST, read-only legacy prompt-source POST, and the
# server-derived protected stage view in every definition serializer.
# ---------------------------------------------------------------------------


DUPLICATE_BLOCK_ID = "00000000-0000-0000-0000-000000000001"
SECOND_BLOCK_ID = "00000000-0000-0000-0000-000000000002"
V1_PAYLOAD_DISPLAY = "json.dumps(payload, indent=2, default=str)"
V2_PAYLOAD_DISPLAY = (
    'json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)'
)
TERMINAL_BINDING = "langchain.with_structured_output"

FIVE_ISSUE_ERRORS = [
    {
        "field": "candidate.assembly_rules.custom_blocks.0.text",
        "code": "blank",
        "message": "Custom block text must not be blank.",
    },
    {
        "field": "candidate.assembly_rules.custom_blocks.0.anchor",
        "code": "invalid_anchor_for_role",
        "message": "The deck-brief anchor is available only to Build Reviewer.",
    },
    {
        "field": "candidate.assembly_rules.custom_blocks.0.condition",
        "code": "invalid_condition_for_anchor",
        "message": "The deck-brief anchor requires payload_has_deck_brief.",
    },
    {
        "field": "candidate.assembly_rules.custom_blocks.1.block_id",
        "code": "duplicate_block_id",
        "message": "Custom block IDs must be unique.",
    },
    {
        "field": "candidate.assembly_rules.custom_blocks.1.anchor",
        "code": "invalid_anchor_order",
        "message": "Custom blocks must be ordered by protected anchor.",
    },
]
BUNDLE_MISMATCH_ERRORS = [
    {
        "field": "candidate.assembly_rules.format_version",
        "code": "assembly_bundle_mismatch",
        "message": "Assembly rules format must match the protected assembly bundle.",
    }
]
ALREADY_CURRENT_ERRORS = [
    {
        "field": "protected_assembly.version",
        "code": "already_current",
        "message": "Protected assembly is already current.",
    }
]
SCHEMA_ALREADY_CURRENT_ERRORS = [
    {
        "field": "schema_contract",
        "code": "already_current",
        "message": "Schema contract is already current.",
    }
]
MANUAL_RESOLUTION_ERRORS = [
    {
        "field": "prompt_text",
        "code": "legacy_prompt_manual_resolution_required",
        "message": (
            "Legacy protected prompt content was edited. Restore the exact Graph Version 1 "
            "prompt before upgrading, then reapply authored edits."
        ),
    }
]
LEGACY_SOURCE_UNSUPPORTED_ERRORS = [
    {
        "field": "agent_key",
        "code": "legacy_prompt_source_unsupported",
        "message": (
            "Legacy Graph Version 1 prompt recovery is supported only for Data Analyst "
            "and Build Reviewer."
        ),
    }
]
LEGACY_SOURCE_NOT_REQUIRED_ERRORS = [
    {
        "field": "prompt_text",
        "code": "legacy_prompt_source_not_required",
        "message": "The draft already uses the exact Graph Version 1 prompt.",
    }
]
LEGACY_SOURCE_UNAVAILABLE_ERRORS = [
    {
        "field": "prompt_text",
        "code": "legacy_prompt_source_unavailable",
        "message": (
            "The exact published Graph Version 1 prompt source is unavailable for this draft."
        ),
    }
]
MALFORMED_JSON_BODY = {
    "code": "invalid_draft",
    "errors": [
        {
            "field": "$",
            "code": "invalid_json",
            "message": "Request body must be valid JSON.",
        }
    ],
}


def _upgrade_url(agent_key: str = "architect") -> str:
    return f"/api/admin/agent-definitions/draft/{agent_key}/protected-assembly-upgrade"


def _schema_contract_upgrade_url(agent_key: str = "architect") -> str:
    return f"/api/admin/agent-definitions/draft/{agent_key}/schema-contract-upgrade"


def _source_url(agent_key: str = "data_analyst") -> str:
    return f"/api/admin/agent-definitions/draft/{agent_key}/legacy-prompt-source"


def _custom_block_payload(
    block_id: str,
    text: str,
    *,
    anchor: str = "after_authored_prompt",
    condition: str = "always",
) -> dict[str, object]:
    return {
        "kind": "custom_text",
        "block_id": block_id,
        "anchor": anchor,
        "condition": condition,
        "text": text,
    }


def _v2_rules_payload(*blocks: dict[str, object]) -> dict[str, object]:
    return {"format_version": 2, "custom_blocks": list(blocks)}


def _five_issue_rules_payload() -> dict[str, object]:
    return _v2_rules_payload(
        _custom_block_payload(
            DUPLICATE_BLOCK_ID, "   ", anchor="after_deck_brief", condition="always"
        ),
        _custom_block_payload(DUPLICATE_BLOCK_ID, "second"),
    )


def _stage_view(node_definition: dict[str, object]) -> dict[str, dict[str, object]]:
    rows = node_definition["protected_stage_view"]
    assert isinstance(rows, list)
    return {row["stage_id"]: row for row in rows}


def _stage_ids(node_definition: dict[str, object]) -> list[str]:
    rows = node_definition["protected_stage_view"]
    assert isinstance(rows, list)
    return [row["stage_id"] for row in rows]


def _post_upgrade(client: TestClient, agent_key: str, lock_version: int):
    return client.post(_upgrade_url(agent_key), json={"lock_version": lock_version})


def _post_schema_contract_upgrade(client: TestClient, agent_key: str, lock_version: int):
    return client.post(
        _schema_contract_upgrade_url(agent_key), json={"lock_version": lock_version}
    )


def _edit_prompt_by_one_code_point(
    client: TestClient, agent_key: str, lock_version: int
) -> None:
    node = _model_node(_workbench(client), agent_key)
    draft = node["draft"]
    assert isinstance(draft, dict)
    response = client.put(
        _draft_save_url(agent_key),
        json={
            "lock_version": lock_version,
            "candidate": _editable_candidate(
                node, prompt_text=str(draft["prompt_text"]) + "!"
            ),
        },
    )
    assert response.status_code == 200


def test_workbench_get_exposes_the_exact_server_derived_v1_protected_stage_view(
    session_factory, monkeypatch
):
    """Catches a hidden, editable, or live-payload protected view in the read model."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        body = _workbench(client)

    for node in _model_nodes(body):
        for definition in (node["published"], node["draft"]):
            assert isinstance(definition, dict)
            expected_ids = ["slide_frame_constraints", "design_system_precedence"]
            if node["agent_key"] == "build_reviewer":
                expected_ids.insert(0, "build_reviewer_deck_brief")
            expected_ids.extend(["runtime_payload", "structured_output_binding"])
            assert _stage_ids(definition) == expected_ids
            rows = _stage_view(definition)
            assert all(row["locked"] is True for row in rows.values())
            assert all(row["bundle_version"] == 1 for row in rows.values())
            assert all(
                row["legal_adjacent_custom_anchors"] == [] for row in rows.values()
            )
            assert set(rows["runtime_payload"]) == {
                "stage_id",
                "label",
                "condition",
                "locked",
                "display_text",
                "bundle_version",
                "bundle_digest",
                "legal_adjacent_custom_anchors",
            }
            assert rows["slide_frame_constraints"]["display_text"] == _SLIDE_FRAME_CONSTRAINTS
            assert rows["slide_frame_constraints"]["condition"] == "design_system_inactive"
            assert rows["design_system_precedence"]["display_text"] == DESIGN_SYSTEM_PRECEDENCE
            assert rows["design_system_precedence"]["condition"] == "design_system_active"
            assert rows["runtime_payload"]["display_text"] == V1_PAYLOAD_DISPLAY
            assert rows["structured_output_binding"]["display_text"] == TERMINAL_BINDING
            if node["agent_key"] == "build_reviewer":
                assert rows["build_reviewer_deck_brief"]["display_text"] == DECK_BRIEF_REVIEW
                assert (
                    rows["build_reviewer_deck_brief"]["condition"] == "payload_has_deck_brief"
                )
            assert "untrusted_data_notice" not in rows
            assert "build_reviewer_criteria" not in rows


@pytest.mark.parametrize("agent_key", ["architect", "build_reviewer"])
def test_v2_serializers_expose_only_legal_pre_payload_anchors_and_exact_display(
    session_factory, monkeypatch, agent_key
):
    """Catches a v2 admin view that hides literals or invents custom anchors."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        upgrade = _post_upgrade(client, agent_key, 0)
        assert upgrade.status_code == 200
        success_definition = upgrade.json()["definition"]
        body = _workbench(client)

    node = _model_node(body, agent_key)
    for definition in (node["draft"], success_definition):
        assert isinstance(definition, dict)
        expected_ids = [
            "slide_frame_constraints",
            "design_system_precedence",
            "untrusted_data_notice",
            "untrusted_data_open",
            "runtime_payload",
            "untrusted_data_close",
            "structured_output_binding",
        ]
        if agent_key == "build_reviewer":
            expected_ids = [
                "build_reviewer_criteria",
                "build_reviewer_deck_brief",
            ] + expected_ids
        assert _stage_ids(definition) == expected_ids
        rows = _stage_view(definition)
        assert all(row["locked"] is True for row in rows.values())
        assert all(row["bundle_version"] == 2 for row in rows.values())
        assert rows["untrusted_data_notice"]["display_text"] == ROLE_UNTRUSTED_DATA_NOTICE[
            agent_key
        ]
        assert rows["untrusted_data_open"]["display_text"] == "<untrusted-data>"
        assert rows["untrusted_data_close"]["display_text"] == "</untrusted-data>"
        assert rows["runtime_payload"]["display_text"] == V2_PAYLOAD_DISPLAY
        assert rows["structured_output_binding"]["display_text"] == TERMINAL_BINDING
        assert rows["slide_frame_constraints"]["display_text"] == _SLIDE_FRAME_CONSTRAINTS
        assert rows["design_system_precedence"]["display_text"] == DESIGN_SYSTEM_PRECEDENCE
        assert rows["slide_frame_constraints"]["legal_adjacent_custom_anchors"] == [
            "after_environment_constraints"
        ]
        assert rows["design_system_precedence"]["legal_adjacent_custom_anchors"] == [
            "after_environment_constraints"
        ]
        assert rows["untrusted_data_notice"]["legal_adjacent_custom_anchors"] == []
        assert rows["runtime_payload"]["legal_adjacent_custom_anchors"] == []
        assert rows["structured_output_binding"]["legal_adjacent_custom_anchors"] == []
        if agent_key == "build_reviewer":
            assert rows["build_reviewer_criteria"]["display_text"] == BUILD_REVIEWER_CRITERIA_STAGE
            assert rows["build_reviewer_criteria"]["legal_adjacent_custom_anchors"] == []
            assert rows["build_reviewer_deck_brief"]["display_text"] == DECK_BRIEF_REVIEW
            assert rows["build_reviewer_deck_brief"]["legal_adjacent_custom_anchors"] == [
                "after_deck_brief"
            ]
    assert node["draft"]["assembly_rules"] == {"format_version": 2, "custom_blocks": []}


def test_conflict_serializer_exposes_the_protected_stage_view_for_all_seven_roles(
    session_factory, monkeypatch
):
    """Catches a conflict envelope that drops the server-derived protected view."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        before = _workbench(client)
        winning = client.put(
            _draft_save_url(),
            json={
                "lock_version": 0,
                "candidate": _editable_candidate(
                    _model_node(before, "architect"), prompt_text="Winner."
                ),
            },
        )
        assert winning.status_code == 200
        stale = client.put(
            _draft_save_url(),
            json={
                "lock_version": 0,
                "candidate": _editable_candidate(
                    _model_node(before, "architect"), prompt_text="Loser."
                ),
            },
        )
        after = _workbench(client)

    assert stale.status_code == 409
    definitions = stale.json()["server"]["definitions"]
    assert set(definitions) == set(EXPECTED_TOPOLOGY_ORDER) - {"foreman"}
    for agent_key, definition in definitions.items():
        assert definition == _model_node(after, agent_key)["draft"]
        assert _stage_ids(definition)


def test_no_request_model_accepts_a_protected_stage_view_or_display_field(
    session_factory, monkeypatch
):
    """Catches a client-supplied protected view, digest, or display override."""
    server_owned = {
        "protected_stage_view",
        "selectable_optional_fields",
        "canonical_fields",
        "display_text",
        "locked",
        "bundle_version",
        "bundle_digest",
        "legal_adjacent_custom_anchors",
        "separator",
        "blocks",
        "terminal",
        "binding",
        "protected_assembly",
        "schema_contract",
        "definition_version",
    }
    for model in (
        DraftSaveRequest,
        EditableModelDraftRequest,
        EditableModelDraftModelRequest,
        EditableAssemblyRulesRequest,
        EditableSchemaOverlayRequest,
        CustomTextBlockRequest,
        DraftLockRequest,
    ):
        assert set(model.model_fields) & server_owned == set()

    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        before = _workbench(client)
        payload = {
            "lock_version": 0,
            "candidate": _editable_candidate(_model_node(before, "architect")),
        }
        candidate = payload["candidate"]
        assert isinstance(candidate, dict)
        candidate["assembly_rules"] = {
            "format_version": 2,
            "custom_blocks": [],
            "protected_stage_view": [],
        }
        response = client.put(_draft_save_url(), json=payload)
        after = _workbench(client)

    assert response.status_code == 422
    assert response.json() == {
        "code": "invalid_draft",
        "errors": [
            {
                "field": "candidate.assembly_rules.protected_stage_view",
                "code": "extra_forbidden",
                "message": "Extra inputs are not permitted",
            }
        ],
    }
    assert after == before


@pytest.mark.parametrize(
    ("rules", "expected"),
    [
        (
            [],
            [
                {
                    "field": "candidate.assembly_rules",
                    "code": "strict_type",
                    "message": "Assembly rules must be an object.",
                }
            ],
        ),
        (
            {"format_version": 1, "custom_blocks": []},
            [
                {
                    "field": "candidate.assembly_rules.format_version",
                    "code": "unsupported_assembly_version",
                    "message": "Editable assembly rules must use format version 2.",
                }
            ],
        ),
        (
            {"format_version": "2", "custom_blocks": []},
            [
                {
                    "field": "candidate.assembly_rules.format_version",
                    "code": "unsupported_assembly_version",
                    "message": "Editable assembly rules must use format version 2.",
                }
            ],
        ),
        (
            {"format_version": 2, "custom_blocks": {}},
            [
                {
                    "field": "candidate.assembly_rules.custom_blocks",
                    "code": "strict_type",
                    "message": "Custom blocks must be an array.",
                }
            ],
        ),
        (
            {"format_version": 2, "separator": "\n\n", "custom_blocks": []},
            [
                {
                    "field": "candidate.assembly_rules.separator",
                    "code": "extra_forbidden",
                    "message": "Extra inputs are not permitted",
                }
            ],
        ),
        (
            {
                "format_version": 2,
                "custom_blocks": [
                    {
                        "kind": "protected",
                        "block_id": DUPLICATE_BLOCK_ID,
                        "anchor": "after_authored_prompt",
                        "condition": "always",
                        "text": "t",
                    }
                ],
            },
            [
                {
                    "field": "candidate.assembly_rules.custom_blocks.0.kind",
                    "code": "unknown_block_kind",
                    "message": "Custom block kind must be custom_text.",
                }
            ],
        ),
        (
            {
                "format_version": 2,
                "custom_blocks": [
                    {
                        "kind": 7,
                        "block_id": DUPLICATE_BLOCK_ID,
                        "anchor": "after_authored_prompt",
                        "condition": "always",
                        "text": "t",
                    }
                ],
            },
            [
                {
                    "field": "candidate.assembly_rules.custom_blocks.0.kind",
                    "code": "unknown_block_kind",
                    "message": "Custom block kind must be custom_text.",
                }
            ],
        ),
        (
            {
                "format_version": 2,
                "custom_blocks": [
                    {
                        "kind": "custom_text",
                        "block_id": "not-a-uuid",
                        "anchor": "after_authored_prompt",
                        "condition": "always",
                        "text": "t",
                    }
                ],
            },
            [
                {
                    "field": "candidate.assembly_rules.custom_blocks.0.block_id",
                    "code": "strict_type",
                    "message": "Custom block ID must be a UUID string.",
                }
            ],
        ),
        (
            {
                "format_version": 2,
                "custom_blocks": [
                    {
                        "kind": "custom_text",
                        "block_id": 7,
                        "anchor": "after_authored_prompt",
                        "condition": "always",
                        "text": "t",
                    }
                ],
            },
            [
                {
                    "field": "candidate.assembly_rules.custom_blocks.0.block_id",
                    "code": "strict_type",
                    "message": "Custom block ID must be a UUID string.",
                }
            ],
        ),
        (
            {
                "format_version": 2,
                "custom_blocks": [
                    {
                        "kind": "custom_text",
                        "block_id": DUPLICATE_BLOCK_ID,
                        "anchor": "after_payload",
                        "condition": "always",
                        "text": "t",
                    }
                ],
            },
            [
                {
                    "field": "candidate.assembly_rules.custom_blocks.0.anchor",
                    "code": "unknown_anchor",
                    "message": "Custom block anchor is not supported.",
                }
            ],
        ),
        (
            {
                "format_version": 2,
                "custom_blocks": [
                    {
                        "kind": "custom_text",
                        "block_id": DUPLICATE_BLOCK_ID,
                        "anchor": 3,
                        "condition": "always",
                        "text": "t",
                    }
                ],
            },
            [
                {
                    "field": "candidate.assembly_rules.custom_blocks.0.anchor",
                    "code": "strict_type",
                    "message": "Custom block anchor must be a string.",
                }
            ],
        ),
        (
            {
                "format_version": 2,
                "custom_blocks": [
                    {
                        "kind": "custom_text",
                        "block_id": DUPLICATE_BLOCK_ID,
                        "anchor": "after_authored_prompt",
                        "condition": "sometimes",
                        "text": "t",
                    }
                ],
            },
            [
                {
                    "field": "candidate.assembly_rules.custom_blocks.0.condition",
                    "code": "unknown_condition",
                    "message": "Custom block condition is not supported.",
                }
            ],
        ),
        (
            {
                "format_version": 2,
                "custom_blocks": [
                    {
                        "kind": "custom_text",
                        "block_id": DUPLICATE_BLOCK_ID,
                        "anchor": "after_authored_prompt",
                        "condition": False,
                        "text": "t",
                    }
                ],
            },
            [
                {
                    "field": "candidate.assembly_rules.custom_blocks.0.condition",
                    "code": "strict_type",
                    "message": "Custom block condition must be a string.",
                }
            ],
        ),
        (
            {
                "format_version": 2,
                "custom_blocks": [
                    {
                        "kind": "custom_text",
                        "block_id": DUPLICATE_BLOCK_ID,
                        "anchor": "after_authored_prompt",
                        "condition": "always",
                        "text": 5,
                    }
                ],
            },
            [
                {
                    "field": "candidate.assembly_rules.custom_blocks.0.text",
                    "code": "strict_type",
                    "message": "Custom block text must be a string.",
                }
            ],
        ),
        (
            {
                "format_version": 2,
                "custom_blocks": [
                    {
                        "kind": "custom_text",
                        "block_id": DUPLICATE_BLOCK_ID,
                        "anchor": "after_authored_prompt",
                        "condition": "always",
                    }
                ],
            },
            [
                {
                    "field": "candidate.assembly_rules.custom_blocks.0.text",
                    "code": "strict_type",
                    "message": "Field required",
                }
            ],
        ),
        (
            {
                "format_version": 2,
                "custom_blocks": [
                    {
                        "kind": "custom_text",
                        "block_id": DUPLICATE_BLOCK_ID,
                        "anchor": "after_authored_prompt",
                        "condition": "always",
                        "text": "t",
                        "display_text": "spoofed",
                    }
                ],
            },
            [
                {
                    "field": "candidate.assembly_rules.custom_blocks.0.display_text",
                    "code": "extra_forbidden",
                    "message": "Extra inputs are not permitted",
                }
            ],
        ),
    ],
)
def test_put_assembly_rules_parser_rows_are_exact_and_stop_before_domain_validation(
    session_factory, monkeypatch, rules, expected
):
    """Catches a parser row with the wrong dotted path, code, message, or ordering."""
    _force_admin(monkeypatch, is_admin=True)
    calls: list[str] = []

    def _must_not_write(*_args, **_kwargs):
        calls.append("write")
        raise AssertionError("request parsing reached the locked draft writer")

    monkeypatch.setattr(GraphConfiguration, "save_editable_model_draft", _must_not_write)
    with _app_for(session_factory) as client:
        before = _workbench(client)
        payload: dict[str, object] = {
            "lock_version": 0,
            "candidate": _editable_candidate(_model_node(before, "architect")),
        }
        candidate = payload["candidate"]
        assert isinstance(candidate, dict)
        candidate["assembly_rules"] = rules
        response = client.put(_draft_save_url(), json=payload)

    assert calls == []
    assert response.status_code == 422
    assert response.json() == {"code": "invalid_draft", "errors": expected}


def test_put_assembly_parser_errors_retain_request_traversal_order(
    session_factory, monkeypatch
):
    """Catches sorted or regrouped parser errors across custom block indices."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        before = _workbench(client)
        payload: dict[str, object] = {
            "lock_version": 0,
            "candidate": _editable_candidate(_model_node(before, "architect")),
        }
        candidate = payload["candidate"]
        assert isinstance(candidate, dict)
        candidate["assembly_rules"] = {
            "format_version": 2,
            "custom_blocks": [
                {
                    "kind": "custom_text",
                    "block_id": DUPLICATE_BLOCK_ID,
                    "anchor": "nowhere",
                    "condition": "always",
                    "text": 1,
                },
                {
                    "kind": "custom_text",
                    "block_id": "still-not-a-uuid",
                    "anchor": "after_authored_prompt",
                    "condition": "never",
                    "text": "t",
                },
            ],
        }
        response = client.put(_draft_save_url(), json=payload)

    assert response.status_code == 422
    assert [
        (error["field"], error["code"]) for error in response.json()["errors"]
    ] == [
        ("candidate.assembly_rules.custom_blocks.0.anchor", "unknown_anchor"),
        ("candidate.assembly_rules.custom_blocks.0.text", "strict_type"),
        ("candidate.assembly_rules.custom_blocks.1.block_id", "strict_type"),
        ("candidate.assembly_rules.custom_blocks.1.condition", "unknown_condition"),
    ]


def test_put_five_issue_v2_candidate_with_stale_lock_returns_ordered_422_envelope(
    session_factory, monkeypatch
):
    """Catches a generic content error, reordering, or stale precedence at the route."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        assert _post_upgrade(client, "architect", 0).status_code == 200
        before = _workbench(client)
        node = _model_node(before, "architect")
        candidate = _editable_candidate(node)
        candidate["assembly_rules"] = _five_issue_rules_payload()
        response = client.put(
            _draft_save_url(), json={"lock_version": 0, "candidate": candidate}
        )
        after = _workbench(client)

    assert response.status_code == 422
    assert response.json() == {"code": "invalid_draft", "errors": FIVE_ISSUE_ERRORS}
    assert after == before


def test_put_v2_rules_on_a_v1_draft_is_the_sole_bundle_mismatch_row(
    session_factory, monkeypatch
):
    """Catches an ordinary route save transitioning a stored v1 draft."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        before = _workbench(client)
        candidate = _editable_candidate(_model_node(before, "architect"))
        candidate["assembly_rules"] = _v2_rules_payload()
        current = client.put(
            _draft_save_url(), json={"lock_version": 0, "candidate": candidate}
        )
        stale = client.put(
            _draft_save_url(), json={"lock_version": 5, "candidate": candidate}
        )
        after = _workbench(client)

    for response in (current, stale):
        assert response.status_code == 422
        assert response.json() == {"code": "invalid_draft", "errors": BUNDLE_MISMATCH_ERRORS}
    assert after == before


def test_put_valid_v2_custom_block_save_round_trips_through_the_route(
    session_factory, monkeypatch
):
    """Catches a rehydration that loses block identity, anchor, condition, or text."""
    _force_admin(monkeypatch, is_admin=True)
    block = _custom_block_payload(
        SECOND_BLOCK_ID,
        "Operator guidance.",
        anchor="after_environment_constraints",
        condition="design_system_active",
    )
    with _app_for(session_factory) as client:
        assert _post_upgrade(client, "architect", 0).status_code == 200
        node = _model_node(_workbench(client), "architect")
        candidate = _editable_candidate(node)
        candidate["assembly_rules"] = _v2_rules_payload(block)
        response = client.put(
            _draft_save_url(), json={"lock_version": 1, "candidate": candidate}
        )
        after = _workbench(client)

    assert response.status_code == 200
    body = response.json()
    assert body["changed"] is True
    assert body["draft"]["lock_version"] == 2
    assert body["definition"]["assembly_rules"] == {
        "format_version": 2,
        "custom_blocks": [block],
    }
    assert body["definition"] == _model_node(after, "architect")["draft"]


def test_upgrade_route_returns_the_exact_success_contract_and_preserves_release(
    session_factory, monkeypatch
):
    """Catches an upgrade route that writes twice, mutates a release, or leaks state."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        before = _workbench(client)
        response = _post_upgrade(client, "data_analyst", 0)
        after = _workbench(client)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"draft", "definition", "changed"}
    assert body["changed"] is True
    assert body["draft"]["lock_version"] == 1
    assert body["draft"]["updated_by"] == "task4-user@example.com"
    assert body["definition"] == _model_node(after, "data_analyst")["draft"]
    assert body["definition"]["prompt_text"] == ANALYST_AUTHORED_INSTRUCTIONS
    assert body["definition"]["assembly_rules"] == {"format_version": 2, "custom_blocks": []}
    assert body["definition"]["protected_assembly"]["version"] == 2
    assert after["active_release"] == before["active_release"]
    assert (
        _model_node(after, "data_analyst")["published"]
        == _model_node(before, "data_analyst")["published"]
    )
    for agent_key in set(EXPECTED_TOPOLOGY_ORDER) - {"foreman", "data_analyst"}:
        assert _model_node(after, agent_key)["draft"] == _model_node(before, agent_key)["draft"]


def test_upgrade_route_copies_already_current_and_stale_without_deriving_state(
    session_factory, monkeypatch
):
    """Catches a route that infers transition state instead of copying the facade result."""
    _force_admin(monkeypatch, is_admin=True)
    observed: list[tuple[str, int]] = []
    original = GraphConfiguration.upgrade_draft_protected_assembly

    def _spy(self, session, *, agent_key, expected_lock_version, actor):
        observed.append((agent_key, expected_lock_version))
        return original(
            self,
            session,
            agent_key=agent_key,
            expected_lock_version=expected_lock_version,
            actor=actor,
        )

    monkeypatch.setattr(GraphConfiguration, "upgrade_draft_protected_assembly", _spy)
    with _app_for(session_factory) as client:
        assert _post_upgrade(client, "architect", 0).status_code == 200
        repeated = _post_upgrade(client, "architect", 1)
        stale = _post_upgrade(client, "architect", 0)
        after = _workbench(client)

    assert observed == [("architect", 0), ("architect", 1), ("architect", 0)]
    assert repeated.status_code == 422
    assert repeated.json() == {"code": "invalid_draft", "errors": ALREADY_CURRENT_ERRORS}
    assert stale.status_code == 409
    stale_body = stale.json()
    assert set(stale_body) == {
        "code",
        "expected_lock_version",
        "current_lock_version",
        "client_candidate",
        "server",
    }
    assert stale_body["code"] == "stale_draft"
    assert stale_body["expected_lock_version"] == 0
    assert stale_body["current_lock_version"] == 1
    assert stale_body["client_candidate"] is None
    assert stale_body["server"]["draft"] == after["draft"]
    assert set(stale_body["server"]["definitions"]) == set(EXPECTED_TOPOLOGY_ORDER) - {"foreman"}
    for agent_key, definition in stale_body["server"]["definitions"].items():
        assert definition == _model_node(after, agent_key)["draft"]


@pytest.mark.parametrize("agent_key", ["data_analyst", "build_reviewer"])
def test_upgrade_route_manual_resolution_and_stale_precedence(
    session_factory, monkeypatch, agent_key
):
    """Catches a transition issue masking staleness at the route boundary."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        _edit_prompt_by_one_code_point(client, agent_key, 0)
        before = _workbench(client)
        current = _post_upgrade(client, agent_key, 1)
        stale = _post_upgrade(client, agent_key, 0)
        after = _workbench(client)

    assert current.status_code == 422
    assert current.json() == {"code": "invalid_draft", "errors": MANUAL_RESOLUTION_ERRORS}
    assert stale.status_code == 409
    assert stale.json()["client_candidate"] is None
    assert stale.json()["current_lock_version"] == 1
    assert after == before


EXTRA_FORBIDDEN_MESSAGE = "Extra inputs are not permitted"


def _extra_forbidden_errors(field: str) -> list[dict[str, str]]:
    return [
        {
            "field": field,
            "code": "extra_forbidden",
            "message": EXTRA_FORBIDDEN_MESSAGE,
        }
    ]


@pytest.mark.parametrize("url_builder", [_upgrade_url, _source_url])
@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            {"lock_version": -1},
            [
                {
                    "field": "lock_version",
                    "code": "out_of_range",
                    "message": "Input should be greater than or equal to 0",
                }
            ],
        ),
        (
            {"lock_version": "0"},
            [
                {
                    "field": "lock_version",
                    "code": "strict_type",
                    "message": "Input should be a valid integer",
                }
            ],
        ),
        (
            {},
            [
                {
                    "field": "lock_version",
                    "code": "strict_type",
                    "message": "Field required",
                }
            ],
        ),
        ({"lock_version": 0, "actor": "attacker"}, _extra_forbidden_errors("actor")),
        (
            {"lock_version": 0, "protected_assembly": {"version": 2, "digest": "f" * 64}},
            _extra_forbidden_errors("protected_assembly"),
        ),
        (
            {"lock_version": 0, "prompt_text": "spoofed"},
            _extra_forbidden_errors("prompt_text"),
        ),
        (
            {"lock_version": 0, "protected_stage_view": []},
            _extra_forbidden_errors("protected_stage_view"),
        ),
        (
            {"lock_version": 0, "assembly_rules": {"format_version": 2, "custom_blocks": []}},
            _extra_forbidden_errors("assembly_rules"),
        ),
        (
            {"lock_version": 0, "display_text": "x"},
            _extra_forbidden_errors("display_text"),
        ),
        ({"lock_version": 0, "terminal": True}, _extra_forbidden_errors("terminal")),
        (
            {"lock_version": 0, "digest": "f" * 64, "format_version": 2},
            _extra_forbidden_errors("digest") + _extra_forbidden_errors("format_version"),
        ),
    ],
)
def test_both_post_routes_accept_only_a_strict_lock_version_body(
    session_factory, monkeypatch, url_builder, body, expected
):
    """Catches either POST route accepting protected, prompt, or actor input."""
    _force_admin(monkeypatch, is_admin=True)
    calls: list[str] = []

    def _must_not_reach(*_args, **_kwargs):
        calls.append("facade")
        raise AssertionError("strict parsing reached the facade")

    monkeypatch.setattr(
        GraphConfiguration, "upgrade_draft_protected_assembly", _must_not_reach
    )
    monkeypatch.setattr(
        GraphConfiguration, "get_draft_legacy_prompt_source", _must_not_reach
    )
    with _app_for(session_factory) as client:
        response = client.post(url_builder("data_analyst"), json=body)

    assert calls == []
    assert response.status_code == 422
    assert response.json() == {"code": "invalid_draft", "errors": expected}


@pytest.mark.parametrize("url_builder", [_upgrade_url, _source_url])
def test_both_post_routes_reject_malformed_json_for_admin_callers(
    session_factory, monkeypatch, url_builder
):
    """Catches a POST route losing the deterministic malformed-body parser error."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        response = client.post(
            url_builder("data_analyst"),
            content=b'{"lock_version": ',
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 422
    assert response.json() == MALFORMED_JSON_BODY


@pytest.mark.parametrize("url_builder", [_upgrade_url, _source_url])
@pytest.mark.parametrize(
    "body",
    [
        b"{not json; SUPER_SECRET_PROMPT; private-endpoint}",
        b'{"lock_version": 0, "prompt_text": "SUPER_SECRET_PROMPT", '
        b'"endpoint_name": "private-endpoint"}',
    ],
)
def test_both_post_routes_deny_non_admins_before_parsing_any_body(
    session_factory, monkeypatch, url_builder, body
):
    """Catches authorization running after body parsing or echoing request bytes."""
    _force_admin(monkeypatch, is_admin=False)
    calls: list[str] = []

    def _must_not_reach(*_args, **_kwargs):
        calls.append("facade")
        raise AssertionError("authorization reached the facade")

    async def _must_not_parse_json(_request):
        calls.append("body")
        raise AssertionError("authorization parsed the raw request body")

    monkeypatch.setattr(
        GraphConfiguration, "upgrade_draft_protected_assembly", _must_not_reach
    )
    monkeypatch.setattr(
        GraphConfiguration, "get_draft_legacy_prompt_source", _must_not_reach
    )
    monkeypatch.setattr(agent_definition_routes.Request, "json", _must_not_parse_json)
    with _app_for(session_factory, raise_server_exceptions=False) as client:
        response = client.post(
            url_builder("data_analyst"),
            content=body,
            headers={"content-type": "application/json"},
        )

    assert calls == []
    assert response.status_code == 403
    assert response.json() == {"detail": "Admin access required"}
    assert "SUPER_SECRET_PROMPT" not in response.text
    assert "private-endpoint" not in response.text


@pytest.mark.parametrize("url_builder", [_upgrade_url, _source_url])
@pytest.mark.parametrize("agent_key", ["unknown", "foreman"])
def test_both_post_routes_reject_unknown_or_deterministic_agent_keys(
    session_factory, monkeypatch, url_builder, agent_key
):
    """Catches a POST route reaching the facade for a non-editable role."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        response = client.post(url_builder(agent_key), json={"lock_version": 0})

    assert response.status_code == 422
    assert response.json() == {
        "code": "invalid_draft",
        "errors": [
            {
                "field": "agent_key",
                "code": "unknown_agent",
                "message": "Agent key must identify an editable model role.",
            }
        ],
    }


@pytest.mark.parametrize("agent_key", ["data_analyst", "build_reviewer"])
def test_legacy_prompt_source_route_returns_the_exact_read_only_dto(
    session_factory, monkeypatch, agent_key
):
    """Catches a recovery route that writes, derives bytes, or reshapes the DTO."""
    _force_admin(monkeypatch, is_admin=True)
    observed: list[tuple[str, int]] = []
    original = GraphConfiguration.get_draft_legacy_prompt_source

    def _spy(self, session, *, agent_key, expected_lock_version, actor):
        observed.append((agent_key, expected_lock_version))
        return original(
            self,
            session,
            agent_key=agent_key,
            expected_lock_version=expected_lock_version,
            actor=actor,
        )

    monkeypatch.setattr(GraphConfiguration, "get_draft_legacy_prompt_source", _spy)
    source_prompt = (
        ANALYST_V1_PROMPT if agent_key == "data_analyst" else BUILD_REVIEWER_V1_PROMPT
    )
    with _app_for(session_factory) as client:
        _edit_prompt_by_one_code_point(client, agent_key, 0)
        before = _workbench(client)
        response = client.post(_source_url(agent_key), json={"lock_version": 1})
        after = _workbench(client)

    assert observed == [(agent_key, 1)]
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"draft", "agent_key", "lock_version", "source"}
    assert body["agent_key"] == agent_key
    assert body["lock_version"] == 1
    assert body["draft"] == before["draft"]
    assert set(body["source"]) == {"prompt_text", "revision_id", "content_hash"}
    assert body["source"]["prompt_text"] == source_prompt
    published = _model_node(before, agent_key)["published"]
    assert isinstance(published, dict)
    assert body["source"]["revision_id"] == published["revision_id"]
    assert body["source"]["content_hash"] == published["content_hash"]
    assert after == before


@pytest.mark.parametrize(
    ("agent_key", "setup", "lock_version", "expected"),
    [
        ("architect", "none", 0, LEGACY_SOURCE_UNSUPPORTED_ERRORS),
        ("data_analyst", "none", 0, LEGACY_SOURCE_NOT_REQUIRED_ERRORS),
        ("data_analyst", "upgrade", 1, LEGACY_SOURCE_UNAVAILABLE_ERRORS),
        ("build_reviewer", "upgrade", 1, LEGACY_SOURCE_UNAVAILABLE_ERRORS),
    ],
)
def test_legacy_prompt_source_route_copies_every_recovery_422(
    session_factory, monkeypatch, agent_key, setup, lock_version, expected
):
    """Catches a route that invents, reorders, or reworded a recovery precondition."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        if setup == "upgrade":
            assert _post_upgrade(client, agent_key, 0).status_code == 200
        before = _workbench(client)
        response = client.post(
            _source_url(agent_key), json={"lock_version": lock_version}
        )
        after = _workbench(client)

    assert response.status_code == 422
    assert response.json() == {"code": "invalid_draft", "errors": expected}
    assert after == before


@pytest.mark.parametrize("agent_key", ["data_analyst", "build_reviewer"])
def test_legacy_prompt_source_route_stale_lock_is_the_null_candidate_conflict(
    session_factory, monkeypatch, agent_key
):
    """Catches recovery preconditions being evaluated before the lock comparison."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        _edit_prompt_by_one_code_point(client, agent_key, 0)
        before = _workbench(client)
        response = client.post(_source_url(agent_key), json={"lock_version": 0})
        after = _workbench(client)

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "stale_draft"
    assert body["client_candidate"] is None
    assert body["expected_lock_version"] == 0
    assert body["current_lock_version"] == 1
    assert body["server"]["draft"] == after["draft"]
    assert set(body["server"]["definitions"]) == set(EXPECTED_TOPOLOGY_ORDER) - {"foreman"}
    assert after == before


def test_conflict_schema_accepts_ordinary_and_null_upgrade_candidates(session_factory):
    """Catches a conflict union that loses either candidate variant."""
    with session_factory() as session:
        snapshot = GraphConfiguration().read_workbench(session)
    definitions = {
        node.agent_key: DraftDefinitionResponse.model_validate(node.draft, from_attributes=True)
        for node in snapshot.nodes
        if node.execution_kind == "model"
    }
    server = DraftSaveConflictServerResponse(draft=snapshot.draft, definitions=definitions)
    ordinary = DraftSaveConflictResponse(
        code="stale_draft",
        expected_lock_version=0,
        current_lock_version=1,
        client_candidate=EditableModelDraftRequest(
            prompt_text="p",
            model=EditableModelDraftModelRequest(
                endpoint_name="e", temperature=0.5, max_tokens=10, top_p=0.5
            ),
        ),
        server=server,
    )
    upgrade = DraftSaveConflictResponse(
        code="stale_draft",
        expected_lock_version=0,
        current_lock_version=1,
        client_candidate=None,
        server=server,
    )
    assert ordinary.model_dump(mode="json")["client_candidate"]["prompt_text"] == "p"
    assert ordinary.model_dump(mode="json")["client_candidate"]["assembly_rules"] is None
    assert upgrade.model_dump(mode="json")["client_candidate"] is None


def test_upgrade_route_persisted_integrity_error_is_nonleaking(session_factory, monkeypatch):
    """Catches a leaking 500 from the new POST routes."""
    _force_admin(monkeypatch, is_admin=True)
    _remove_draft_agent(session_factory)
    with _app_for(session_factory, raise_server_exceptions=False) as client:
        upgrade = client.post(_upgrade_url("architect"), json={"lock_version": 0})
        source = client.post(_source_url("data_analyst"), json={"lock_version": 0})

    for response in (upgrade, source):
        assert response.status_code == 500
        assert response.json() == {"detail": "Graph configuration is incomplete"}


def test_stale_v2_save_conflict_echoes_the_facade_candidate_rules(
    session_factory, monkeypatch
):
    """Catches a conflict echo built from the raw body instead of the facade result."""
    _force_admin(monkeypatch, is_admin=True)
    block = _custom_block_payload(SECOND_BLOCK_ID, "Retained operator guidance.")
    with _app_for(session_factory) as client:
        assert _post_upgrade(client, "architect", 0).status_code == 200
        node = _model_node(_workbench(client), "architect")
        candidate = _editable_candidate(node, prompt_text="Stale v2 edit.")
        candidate["assembly_rules"] = _v2_rules_payload(block)
        response = client.put(
            _draft_save_url(), json={"lock_version": 0, "candidate": candidate}
        )
        after = _workbench(client)

    assert response.status_code == 409
    body = response.json()
    assert body["client_candidate"] == {
        "prompt_text": "Stale v2 edit.",
        "model": candidate["model"],
        "assembly_rules": {"format_version": 2, "custom_blocks": [block]},
        "schema_overlay": None,
    }
    assert body["expected_lock_version"] == 0
    assert body["current_lock_version"] == 1
    assert _model_node(after, "architect")["draft"]["assembly_rules"] == {
        "format_version": 2,
        "custom_blocks": [],
    }


@pytest.mark.parametrize("url_builder", [_upgrade_url, _source_url])
@pytest.mark.parametrize("principal", [None, " \t "])
def test_both_post_routes_require_a_trusted_principal_before_any_body_parse(
    session_factory, monkeypatch, url_builder, principal
):
    """Catches a POST route parsing a body without a trusted audit actor."""
    _force_admin(monkeypatch, is_admin=True)
    set_current_user(principal)
    calls: list[str] = []

    def _must_not_reach(*_args, **_kwargs):
        calls.append("facade")
        raise AssertionError("missing principal reached the facade")

    monkeypatch.setattr(
        GraphConfiguration, "upgrade_draft_protected_assembly", _must_not_reach
    )
    monkeypatch.setattr(
        GraphConfiguration, "get_draft_legacy_prompt_source", _must_not_reach
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[agent_definition_routes.require_admin] = lambda: None

    def _override_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            url_builder("data_analyst"),
            content=b"{not json; should not be parsed}",
            headers={"content-type": "application/json"},
        )

    assert calls == []
    assert response.status_code == 403
    assert response.json() == {"detail": "Authenticated principal required"}


# ===========================================================================
# Task 5: Schema contract upgrade route and schema overlay PUT editing
# ===========================================================================


def test_schema_contract_upgrade_route_returns_exact_success_and_preserves_release(
    session_factory, monkeypatch
):
    """Catches a schema-contract upgrade route that writes twice or mutates the release."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        before = _workbench(client)
        response = _post_schema_contract_upgrade(client, "architect", 0)
        after = _workbench(client)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"draft", "definition", "changed"}
    assert body["changed"] is True
    assert body["draft"]["lock_version"] == 1
    assert body["draft"]["updated_by"] == "task4-user@example.com"
    assert body["definition"] == _model_node(after, "architect")["draft"]
    assert body["definition"]["schema_contract"]["version"] == 2
    assert after["active_release"] == before["active_release"]
    assert (
        _model_node(after, "architect")["published"]
        == _model_node(before, "architect")["published"]
    )
    for agent_key in set(EXPECTED_TOPOLOGY_ORDER) - {"foreman", "architect"}:
        assert (
            _model_node(after, agent_key)["draft"]
            == _model_node(before, agent_key)["draft"]
        )


def test_schema_contract_upgrade_route_already_current_returns_ordered_422(
    session_factory, monkeypatch
):
    """Catches a route that reports a missing contract check or the wrong field/code."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        assert _post_schema_contract_upgrade(client, "architect", 0).status_code == 200
        repeated = _post_schema_contract_upgrade(client, "architect", 1)
        after = _workbench(client)

    assert repeated.status_code == 422
    assert repeated.json() == {"code": "invalid_draft", "errors": SCHEMA_ALREADY_CURRENT_ERRORS}
    assert after["draft"]["lock_version"] == 1


def test_schema_contract_upgrade_route_stale_returns_coherent_409_with_null_candidate(
    session_factory, monkeypatch
):
    """Catches a stale upgrade route returning 422 or echoing a non-null candidate."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        assert _post_schema_contract_upgrade(client, "architect", 0).status_code == 200
        stale = _post_schema_contract_upgrade(client, "architect", 0)
        after = _workbench(client)

    assert stale.status_code == 409
    stale_body = stale.json()
    assert set(stale_body) == {
        "code",
        "expected_lock_version",
        "current_lock_version",
        "client_candidate",
        "server",
    }
    assert stale_body["code"] == "stale_draft"
    assert stale_body["expected_lock_version"] == 0
    assert stale_body["current_lock_version"] == 1
    assert stale_body["client_candidate"] is None
    assert stale_body["server"]["draft"] == after["draft"]
    assert set(stale_body["server"]["definitions"]) == set(EXPECTED_TOPOLOGY_ORDER) - {"foreman"}
    for agent_key, definition in stale_body["server"]["definitions"].items():
        assert definition == _model_node(after, agent_key)["draft"]


def test_schema_contract_upgrade_already_current_plus_stale_is_coherent_409(
    session_factory, monkeypatch
):
    """Pins stale-before-already-current ordering in the schema-contract upgrade route.

    Corrections 52/53: the stale check outranks the already_current check, so
    already-current+stale returns 409 (not 422).  The 409 body carries
    schema_contract.version so the client needs no second round trip to discover
    the contract is already current.
    """
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        assert _post_schema_contract_upgrade(client, "architect", 0).status_code == 200
        # lock is now 1; send stale lock=0 on already-v2 content
        stale_and_current = _post_schema_contract_upgrade(client, "architect", 0)
        after = _workbench(client)

    assert stale_and_current.status_code == 409
    body = stale_and_current.json()
    assert body["code"] == "stale_draft"
    assert body["expected_lock_version"] == 0
    assert body["current_lock_version"] == 1
    assert body["client_candidate"] is None
    # The conflict body carries schema_contract.version so client infers already current
    assert (
        body["server"]["definitions"]["architect"]["schema_contract"]["version"] == 2
    )
    assert body["server"]["draft"] == after["draft"]


def test_schema_contract_upgrade_route_non_admin_denied_before_body_parse(
    session_factory, monkeypatch
):
    """Catches a schema-contract upgrade route that parses the body before auth."""
    _force_admin(monkeypatch, is_admin=False)
    with _app_for(session_factory) as client:
        response = client.post(
            _schema_contract_upgrade_url(),
            content=b"{not json; should not be parsed}",
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 403


def test_schema_contract_upgrade_route_requires_trusted_principal_before_body_parse(
    session_factory, monkeypatch
):
    """Catches a schema-contract upgrade route that reaches the facade without a principal."""
    _force_admin(monkeypatch, is_admin=True)
    set_current_user(None)
    calls: list[str] = []

    def _must_not_reach(*_args, **_kwargs):
        calls.append("facade")
        raise AssertionError("missing principal reached the facade")

    monkeypatch.setattr(
        GraphConfiguration, "upgrade_draft_schema_contract", _must_not_reach
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[agent_definition_routes.require_admin] = lambda: None

    def _override_db_t5() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db_t5
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            _schema_contract_upgrade_url("data_analyst"),
            content=b"{not json; should not be parsed}",
            headers={"content-type": "application/json"},
        )

    assert calls == []
    assert response.status_code == 403
    assert response.json() == {"detail": "Authenticated principal required"}


@pytest.mark.parametrize("agent_key", ["unknown", "foreman"])
def test_schema_contract_upgrade_route_rejects_unknown_or_deterministic_agent_key(
    session_factory, monkeypatch, agent_key
):
    """Catches a schema-contract upgrade route that ignores the agent_key guard."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        before = _workbench(client)
        response = client.post(
            _schema_contract_upgrade_url(agent_key), json={"lock_version": 0}
        )
        after = _workbench(client)

    assert response.status_code == 422
    assert response.json() == {
        "code": "invalid_draft",
        "errors": [
            {
                "field": "agent_key",
                "code": "unknown_agent",
                "message": "Agent key must identify an editable model role.",
            }
        ],
    }
    assert after == before


def test_schema_contract_upgrade_route_accepts_only_strict_lock_version_body(
    session_factory, monkeypatch
):
    """Catches a schema-contract upgrade accepting anything beyond a lock_version body."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        response = client.post(
            _schema_contract_upgrade_url(),
            json={"lock_version": 0, "schema_overlay": {"field_overrides": {}}},
        )
    assert response.status_code == 422
    assert response.json() == {
        "code": "invalid_draft",
        "errors": _extra_forbidden_errors("schema_overlay"),
    }


def test_schema_contract_upgrade_route_rejects_malformed_json(
    session_factory, monkeypatch
):
    """Catches a schema-contract upgrade route that swallows JSON parse errors."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        before = _workbench(client)
        response = client.post(
            _schema_contract_upgrade_url(),
            content=b'{"lock_version": ',
            headers={"content-type": "application/json"},
        )
        after = _workbench(client)

    assert response.status_code == 422
    assert response.json() == MALFORMED_JSON_BODY
    assert after == before


def test_schema_contract_upgrade_route_persisted_integrity_error_is_nonleaking(
    session_factory, monkeypatch
):
    """Catches a leaking 500 from the schema-contract upgrade route."""
    _force_admin(monkeypatch, is_admin=True)
    _remove_draft_agent(session_factory)
    with _app_for(session_factory, raise_server_exceptions=False) as client:
        response = client.post(
            _schema_contract_upgrade_url("architect"), json={"lock_version": 0}
        )

    assert response.status_code == 500
    assert response.json() == {"detail": "Graph configuration is incomplete"}


def test_put_accepts_schema_overlay_and_round_trips_via_workbench(
    session_factory, monkeypatch
):
    """Catches a PUT route that ignores or drops the schema_overlay field."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        assert _post_schema_contract_upgrade(client, "architect", 0).status_code == 200
        node = _model_node(_workbench(client), "architect")
        candidate = _editable_candidate(node)
        candidate["schema_overlay"] = {
            "field_overrides": {},
            "additional_optional_fields": ["diagnostic_notes"],
        }
        response = client.put(
            _draft_save_url(),
            json={"lock_version": 1, "candidate": candidate},
        )
        after = _workbench(client)

    assert response.status_code == 200
    body = response.json()
    assert body["definition"]["schema_overlay"]["additional_optional_fields"] == [
        "diagnostic_notes"
    ]
    assert _model_node(after, "architect")["draft"]["schema_overlay"][
        "additional_optional_fields"
    ] == ["diagnostic_notes"]


def test_put_null_schema_overlay_retains_stored_overlay(
    session_factory, monkeypatch
):
    """Catches a route that clears the overlay when schema_overlay is omitted."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        assert _post_schema_contract_upgrade(client, "architect", 0).status_code == 200
        node = _model_node(_workbench(client), "architect")
        # First save: add optional field
        first = _editable_candidate(node)
        first["schema_overlay"] = {
            "field_overrides": {},
            "additional_optional_fields": ["diagnostic_notes"],
        }
        r1 = client.put(_draft_save_url(), json={"lock_version": 1, "candidate": first})
        assert r1.status_code == 200
        # Second save: omit schema_overlay entirely — must retain prior value
        second = _editable_candidate(_model_node(_workbench(client), "architect"))
        assert "schema_overlay" not in second
        r2 = client.put(_draft_save_url(), json={"lock_version": 2, "candidate": second})
        after = _workbench(client)

    assert r2.status_code == 200
    assert _model_node(after, "architect")["draft"]["schema_overlay"][
        "additional_optional_fields"
    ] == ["diagnostic_notes"]


def test_put_schema_overlay_same_content_reports_unchanged(
    session_factory, monkeypatch
):
    """Catches a route that marks every overlay save as changed."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        assert _post_schema_contract_upgrade(client, "architect", 0).status_code == 200
        node = _model_node(_workbench(client), "architect")
        candidate = _editable_candidate(node)
        candidate["schema_overlay"] = {
            "field_overrides": {},
            "additional_optional_fields": ["diagnostic_notes"],
        }
        r1 = client.put(_draft_save_url(), json={"lock_version": 1, "candidate": candidate})
        assert r1.status_code == 200
        assert r1.json()["changed"] is True
        # Resend the same overlay — must report unchanged
        same_candidate = _editable_candidate(_model_node(_workbench(client), "architect"))
        same_candidate["schema_overlay"] = {
            "field_overrides": {},
            "additional_optional_fields": ["diagnostic_notes"],
        }
        r2 = client.put(
            _draft_save_url(), json={"lock_version": 2, "candidate": same_candidate}
        )

    assert r2.status_code == 200
    assert r2.json()["changed"] is False


def test_put_schema_overlay_type_field_is_rejected_as_extra_forbidden(
    session_factory, monkeypatch
):
    """Catches a route that admits a protected top-level key inside schema_overlay.

    Controller sabotage: switch EditableSchemaOverlayRequest from extra='forbid'
    to extra='allow'.  A 'type' key at the overlay root then passes through silently.
    """
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        before = _workbench(client)
        node = _model_node(before, "architect")
        candidate = _editable_candidate(node)
        candidate["schema_overlay"] = {
            "field_overrides": {},
            "additional_optional_fields": [],
            "type": "object",
        }
        response = client.put(
            _draft_save_url(),
            json={"lock_version": 0, "candidate": candidate},
        )
        after = _workbench(client)

    assert response.status_code == 422
    assert response.json() == {
        "code": "invalid_draft",
        "errors": _extra_forbidden_errors("candidate.schema_overlay.type"),
    }
    assert after == before


@pytest.mark.parametrize(
    ("schema_overlay", "expected_field", "expected_message"),
    [
        # Top-level schema_overlay is not a dict — fires _OWNED_SCHEMA_OVERLAY_MESSAGES
        # key ("candidate.schema_overlay", "strict_type")
        (
            [],
            "candidate.schema_overlay",
            "Schema overlay must be an object.",
        ),
        # field_overrides value is not a dict — fires key
        # ("candidate.schema_overlay.field_overrides", "strict_type")
        (
            {"field_overrides": "string"},
            "candidate.schema_overlay.field_overrides",
            "Field overrides must be an object.",
        ),
        # additional_optional_fields value is not a list — fires key
        # ("candidate.schema_overlay.additional_optional_fields", "strict_type")
        (
            {"additional_optional_fields": {}},
            "candidate.schema_overlay.additional_optional_fields",
            "Additional optional fields must be an array.",
        ),
    ],
)
def test_put_schema_overlay_wire_type_error_uses_owned_message(
    session_factory, monkeypatch, schema_overlay, expected_field, expected_message
):
    """Catches removal of _OWNED_SCHEMA_OVERLAY_MESSAGES or its lookup branch.

    Each case is caught by DraftSaveRequest.model_validate (wire layer) and routed
    through _request_error_message.  Without the overlay_msg lookup branch, the
    function falls through to _OWNED_ASSEMBLY_MESSAGES then to Pydantic's default
    message, which differs from the owned string.

    Mutation: delete the overlay_msg lookup branch in _request_error_message.
    Result: each case returns Pydantic's default message — assertion fails.
    """
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        before = _workbench(client)
        candidate = _editable_candidate(_model_node(before, "architect"))
        candidate["schema_overlay"] = schema_overlay
        response = client.put(
            _draft_save_url(),
            json={"lock_version": 0, "candidate": candidate},
        )
        after = _workbench(client)

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "invalid_draft"
    assert body["errors"][0]["field"] == expected_field
    assert body["errors"][0]["code"] == "strict_type"
    assert body["errors"][0]["message"] == expected_message
    assert after == before


def test_put_schema_overlay_domain_rejections_carry_candidate_prefix(
    session_factory, monkeypatch
):
    """Catches a route that strips or mis-prefixes overlay domain issues."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        before = _workbench(client)
        node = _model_node(before, "architect")
        candidate = _editable_candidate(node)
        candidate["schema_overlay"] = {
            "field_overrides": {"no_such_field": {"description": "x"}},
            "additional_optional_fields": [],
        }
        response = client.put(
            _draft_save_url(),
            json={"lock_version": 0, "candidate": candidate},
        )
        after = _workbench(client)

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "invalid_draft"
    assert (
        body["errors"][0]["field"]
        == "candidate.schema_overlay.field_overrides.no_such_field"
    )
    assert body["errors"][0]["code"] == "overlay_unknown_canonical_field"
    assert after == before


def test_put_schema_overlay_guidance_forbidden_property_is_domain_rejected(
    session_factory, monkeypatch
):
    """Catches a route that passes a 'type' guidance property without domain rejection."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        # Guidance property checks are reachable only under schema contract v2
        # (#264 I1: under v1 every override is an unavailable canonical field).
        upgraded = client.post(_schema_contract_upgrade_url(), json={"lock_version": 0})
        assert upgraded.status_code == 200
        before = _workbench(client)
        # architect has 'intent' as a canonical field; 'type' inside guidance is forbidden
        candidate = _editable_candidate(_model_node(before, "architect"))
        candidate["schema_overlay"] = {
            "field_overrides": {"intent": {"type": "string"}},
            "additional_optional_fields": [],
        }
        response = client.put(
            _draft_save_url(),
            json={"lock_version": 1, "candidate": candidate},
        )
        after = _workbench(client)

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "invalid_draft"
    errors = body["errors"]
    assert len(errors) == 1
    assert errors[0]["field"] == "candidate.schema_overlay.field_overrides.intent.type"
    assert errors[0]["code"] == "overlay_guidance_property_forbidden"
    assert errors[0]["message"] == "Only description and examples are editable."
    assert after == before


def test_put_schema_overlay_invalid_plus_stale_returns_ordered_422(
    session_factory, monkeypatch
):
    """Catches a route that returns 409 instead of 422 for invalid+stale overlay.

    Correction 16: local_candidate_validators run before the stale check, so an
    invalid candidate returns 422 even when the lock is stale.
    """
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        # Advance the lock so lock=0 is stale
        _edit_prompt_by_one_code_point(client, "architect", 0)
        before = _workbench(client)
        node = _model_node(before, "architect")
        candidate = _editable_candidate(node)
        # Invalid overlay: no_such_field does not exist
        candidate["schema_overlay"] = {
            "field_overrides": {"no_such_field": {"description": "x"}},
            "additional_optional_fields": [],
        }
        response = client.put(
            _draft_save_url(),
            json={"lock_version": 0, "candidate": candidate},
        )
        after = _workbench(client)

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "invalid_draft"
    assert (
        body["errors"][0]["field"]
        == "candidate.schema_overlay.field_overrides.no_such_field"
    )
    assert body["errors"][0]["code"] == "overlay_unknown_canonical_field"
    assert after == before


def test_put_valid_schema_overlay_plus_stale_lock_returns_coherent_409(
    session_factory, monkeypatch
):
    """Catches a route that 422s a valid overlay with a stale lock.

    Correction 16: a valid candidate with a stale lock returns 409.
    """
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        _edit_prompt_by_one_code_point(client, "architect", 0)
        before = _workbench(client)
        node = _model_node(before, "architect")
        candidate = _editable_candidate(node)
        # Valid but empty overlay; stale lock=0
        candidate["schema_overlay"] = {"field_overrides": {}, "additional_optional_fields": []}
        response = client.put(
            _draft_save_url(),
            json={"lock_version": 0, "candidate": candidate},
        )
        after = _workbench(client)

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "stale_draft"
    assert body["expected_lock_version"] == 0
    assert body["current_lock_version"] == 1
    # schema_overlay is echoed as part of the candidate
    assert body["client_candidate"]["schema_overlay"] == {
        "field_overrides": {},
        "additional_optional_fields": [],
    }
    assert set(body["server"]["definitions"]) == set(EXPECTED_TOPOLOGY_ORDER) - {"foreman"}
    assert after == before


def test_put_schema_overlay_stale_conflict_echoes_overlay_in_client_candidate(
    session_factory, monkeypatch
):
    """Catches a stale echo built without the schema_overlay field."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        _edit_prompt_by_one_code_point(client, "architect", 0)
        node = _model_node(_workbench(client), "architect")
        candidate = _editable_candidate(node)
        candidate["schema_overlay"] = {
            "field_overrides": {},
            "additional_optional_fields": [],
        }
        response = client.put(
            _draft_save_url(),
            json={"lock_version": 0, "candidate": candidate},
        )

    assert response.status_code == 409
    body = response.json()
    assert "schema_overlay" in body["client_candidate"]
    assert body["client_candidate"]["schema_overlay"] == {
        "field_overrides": {},
        "additional_optional_fields": [],
    }


@pytest.mark.parametrize(
    ("schema_overlay", "expected_field"),
    [
        # A: field_overrides value is a string (model_type at SchemaOverlay.model_validate)
        (
            {"field_overrides": {"intent": "not-a-dict"}, "additional_optional_fields": []},
            "candidate.schema_overlay.field_overrides.intent",
        ),
        # B: field_overrides value is a list (model_type)
        (
            {"field_overrides": {"intent": [1, 2, 3]}, "additional_optional_fields": []},
            "candidate.schema_overlay.field_overrides.intent",
        ),
        # C: field_overrides value is an int (model_type)
        (
            {"field_overrides": {"intent": 42}, "additional_optional_fields": []},
            "candidate.schema_overlay.field_overrides.intent",
        ),
        # D: inner description is an int, not a string (string_type)
        (
            {
                "field_overrides": {
                    "intent": {"description": 99, "examples": ["ok"]}
                },
                "additional_optional_fields": [],
            },
            "candidate.schema_overlay.field_overrides.intent.description",
        ),
        # E: inner examples is a string, not a sequence (tuple_type)
        (
            {
                "field_overrides": {
                    "intent": {"description": "ok", "examples": "not-a-list"}
                },
                "additional_optional_fields": [],
            },
            "candidate.schema_overlay.field_overrides.intent.examples",
        ),
        # F: field_overrides value is null (model_type)
        (
            {"field_overrides": {"intent": None}, "additional_optional_fields": []},
            "candidate.schema_overlay.field_overrides.intent",
        ),
    ],
)
def test_put_schema_overlay_domain_conversion_type_error_returns_ordered_422(
    session_factory, monkeypatch, schema_overlay, expected_field
):
    """Catches an unhandled ValidationError from _domain_schema_overlay.

    Shapes A-F pass the wire model (field_overrides: dict[str, object]) but fail at
    SchemaOverlay.model_validate, producing HTTP 500 without the try/except catch.
    With the catch, each returns an ordered 422 with the error field rooted at
    candidate.schema_overlay, and no write occurs.

    Mutation: remove the try/except around _domain_schema_overlay in
    save_agent_definition_draft.  Each parametrised case returns 500 (or raises),
    not 422.
    """
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory, raise_server_exceptions=False) as client:
        before = _workbench(client)
        candidate = _editable_candidate(_model_node(before, "architect"))
        candidate["schema_overlay"] = schema_overlay
        response = client.put(
            _draft_save_url(),
            json={"lock_version": 0, "candidate": candidate},
        )
        after = _workbench(client)

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "invalid_draft"
    assert body["errors"][0]["field"] == expected_field
    assert body["errors"][0]["code"] == "strict_type"
    assert after == before


def test_schema_upgrade_exposes_v2_selectable_optional_field_descriptors(
    session_factory, monkeypatch
):
    """Catches a response that omits or corrupts optional field descriptor display data."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        assert _post_schema_contract_upgrade(client, "architect", 0).status_code == 200
        after = _workbench(client)

    node = _model_node(after, "architect")
    # v2 draft must expose exactly one descriptor -- diagnostic_notes
    draft_descriptors = node["draft"]["selectable_optional_fields"]
    assert len(draft_descriptors) == 1
    descriptor = draft_descriptors[0]
    expected = {
        "name": "diagnostic_notes",
        "description": (
            "Concise assumptions or ambiguities that influenced the selected intent; "
            "never substitute for `message`, `deck_spec`, `data_request`, targets, or a "
            "design proposal."
        ),
        "examples": [
            "Assumed the request refers to the existing Q2 deck; no target slide numbers "
            "were supplied."
        ],
        "schema": {
            "type": ["array", "null"],
            "default": None,
            "max_items": 8,
            "items": {
                "type": "string",
                "strip_whitespace": True,
                "min_length": 1,
                "max_length": 280,
            },
        },
    }
    assert descriptor == expected
    # published is still v1 -- no descriptors
    assert node["published"]["selectable_optional_fields"] == []
    # Other roles with v1 schema_contract still have no descriptors
    data_analyst = _model_node(after, "data_analyst")
    assert data_analyst["draft"]["selectable_optional_fields"] == []


def test_v1_schema_has_no_selectable_optional_fields(
    session_factory, monkeypatch
):
    """Catches a response that returns descriptors for v1 schemas."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        body = _workbench(client)

    for node in _model_nodes(body):
        assert node["draft"]["selectable_optional_fields"] == []
        assert node["published"]["selectable_optional_fields"] == []


def test_schema_contract_upgrade_response_includes_selectable_optional_fields(
    session_factory, monkeypatch
):
    """Catches an upgrade success response that omits the descriptor display data."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        response = _post_schema_contract_upgrade(client, "data_analyst", 0)

    assert response.status_code == 200
    definition = response.json()["definition"]
    assert "selectable_optional_fields" in definition
    assert len(definition["selectable_optional_fields"]) == 1
    expected = {
        "name": "diagnostic_notes",
        "description": (
            "Concise retrieval limitations, source disagreement, or interpretation "
            "assumptions; never replace `outcome`, `synthesis`, `sources`, `gap`, "
            "`reason`, or `tried_tools`."
        ),
        "examples": [
            "The two sources use different fiscal calendars; synthesis compares "
            "calendar-quarter totals."
        ],
        "schema": {
            "type": ["array", "null"],
            "default": None,
            "max_items": 8,
            "items": {
                "type": "string",
                "strip_whitespace": True,
                "min_length": 1,
                "max_length": 280,
            },
        },
    }
    assert definition["selectable_optional_fields"][0] == expected


def test_schema_contract_upgrade_route_exact_seven_stale_conflict_snapshot(
    session_factory, monkeypatch
):
    """Catches a stale schema-contract upgrade that drops definitions or mixes roles."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        # Advance the lock so lock=0 is stale
        assert _post_schema_contract_upgrade(client, "architect", 0).status_code == 200
        stale = _post_schema_contract_upgrade(client, "architect", 0)
        after = _workbench(client)

    assert stale.status_code == 409
    server = stale.json()["server"]
    assert set(server["definitions"]) == set(EXPECTED_TOPOLOGY_ORDER) - {"foreman"}
    for agent_key, definition in server["definitions"].items():
        assert definition == _model_node(after, agent_key)["draft"]
        # Every definition in the snapshot must carry selectable_optional_fields
        assert "selectable_optional_fields" in definition


# ── #264 Task 6 fix round 1, I4: read-only canonical-field display data ──────────

#: Hand-typed per correction C-24: the canonical output fields each role's code-owned
#: Pydantic output schema declares, in model field order.  ``default`` is present only
#: for a field that is not required.  Nothing here is imported from the code under test.
def _required(name: str, type_: str, enum: list[str] | None = None) -> dict[str, object]:
    return {"name": name, "type": type_, "required": True, "enum": enum}


def _optional(name: str, type_: str, default: object) -> dict[str, object]:
    return {"name": name, "type": type_, "required": False, "enum": None, "default": default}


_VERDICTS = ["clean", "fixed", "surfaced"]
EXPECTED_CANONICAL_FIELDS: dict[str, list[dict[str, object]]] = {
    "architect": [
        _required(
            "intent",
            "string",
            ["discuss", "ask_data", "build", "edit", "confirm_design_contract"],
        ),
        _required("message", "string"),
        _optional("deck_spec", "DeckSpec | null", None),
        _optional("data_request", "DataRequest | null", None),
        _optional("target_positions", "array<integer>", []),
        _optional("proposed_design_contract", "DesignContractRef | null", None),
    ],
    "data_analyst": [
        _required("outcome", "string", ["success", "missing_data", "no_tool"]),
        _optional("synthesis", "string | null", None),
        _optional("sources", "array<string> | null", None),
        _optional("gap", "string | null", None),
        _optional("tried_tools", "array<string>", []),
        _optional("reason", "string | null", None),
    ],
    "builder": [
        _required("position", "integer"),
        _required("html", "string"),
        _optional("scripts", "string", ""),
    ],
    "build_reviewer": [
        _required("slide_index", "integer"),
        _required("verdict", "string", _VERDICTS),
        _optional("findings", "array<Finding>", []),
    ],
    "fixer": [
        _required("position", "integer"),
        _required("html", "string"),
        _optional("scripts", "string", ""),
        _required("changed", "boolean"),
        _optional("change_summary", "string", ""),
    ],
    "fix_reviewer": [
        _required("slide_index", "integer"),
        _required("verdict", "string", _VERDICTS),
        _optional("findings", "array<Finding>", []),
    ],
    "deck_reviewer": [
        _optional("findings", "array<Finding>", []),
    ],
}


def test_every_role_exposes_its_code_owned_canonical_fields_read_only(
    session_factory, monkeypatch
):
    """Catches a missing, reordered, or mis-derived canonical-field display list."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        body = _workbench(client)

    assert [node["agent_key"] for node in _model_nodes(body)] == list(EXPECTED_CANONICAL_FIELDS)
    for node in _model_nodes(body):
        expected = EXPECTED_CANONICAL_FIELDS[node["agent_key"]]
        assert node["draft"]["canonical_fields"] == expected, node["agent_key"]
        assert node["published"]["canonical_fields"] == expected, node["agent_key"]


def test_canonical_fields_survive_schema_upgrade_and_change_no_stored_identity(
    session_factory, monkeypatch
):
    """Catches display data that moves with the contract or leaks into hashed content."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        before = _workbench(client)
        response = _post_schema_contract_upgrade(client, "fixer", 0)
        after = _workbench(client)

    assert response.status_code == 200
    assert response.json()["definition"]["canonical_fields"] == EXPECTED_CANONICAL_FIELDS["fixer"]
    for node in _model_nodes(after):
        assert node["draft"]["canonical_fields"] == EXPECTED_CANONICAL_FIELDS[node["agent_key"]]
    # Identical display data before and after, while the only content that changed is
    # the upgraded role's contract: the list is derived, never stored or hashed.
    for agent_key in EXPECTED_CANONICAL_FIELDS:
        old = _model_node(before, agent_key)
        new = _model_node(after, agent_key)
        assert old["published"] == new["published"]
        if agent_key != "fixer":
            assert old["draft"] == new["draft"]


def test_canonical_fields_are_in_every_seven_role_conflict_snapshot(
    session_factory, monkeypatch
):
    """Catches a 409 snapshot definition that drops the display list."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        assert _post_schema_contract_upgrade(client, "architect", 0).status_code == 200
        stale = _post_schema_contract_upgrade(client, "builder", 0)

    assert stale.status_code == 409
    definitions = stale.json()["server"]["definitions"]
    for agent_key, definition in definitions.items():
        assert definition["canonical_fields"] == EXPECTED_CANONICAL_FIELDS[agent_key]


_CLIENT_MOCKS = (
    pathlib.Path(__file__).resolve().parents[2] / "frontend" / "tests" / "fixtures" / "mocks.ts"
)


def _client_json_fixture(declaration: str) -> object:
    """The JSON-literal body of one ``export const NAME: T = {...};`` block in mocks.ts.

    Reads ``frontend/tests/fixtures/mocks.ts`` as text.  The fixture body is written as
    strict JSON (double quotes, no trailing commas, no comments) so this can load it
    without a TypeScript parser; a body that is not strict JSON fails loudly here.
    """
    source = _CLIENT_MOCKS.read_text(encoding="utf-8")
    start = source.index(f"export const {declaration}:")
    opening = source.index("= {", start) + 2
    closing = source.index("\n};", opening)
    return json.loads(source[opening : closing + 2])


def test_client_canonical_field_fixture_is_the_server_display_data(
    session_factory, monkeypatch
):
    """Joins the client's hand-typed canonical-field fixture to the live route output."""
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        body = _workbench(client)

    fixture = _client_json_fixture("CANONICAL_FIELD_DESCRIPTORS")
    assert list(fixture) == [node["agent_key"] for node in _model_nodes(body)]
    for node in _model_nodes(body):
        assert fixture[node["agent_key"]] == node["draft"]["canonical_fields"]


def test_client_diagnostic_notes_fixture_is_the_server_descriptor_for_all_seven_roles(
    session_factory, monkeypatch
):
    """Joins the client's seven per-role ``diagnostic_notes`` descriptors to the route."""
    _force_admin(monkeypatch, is_admin=True)
    fixture = _client_json_fixture("DIAGNOSTIC_NOTES_DESCRIPTORS")
    with _app_for(session_factory) as client:
        roles = [node["agent_key"] for node in _model_nodes(_workbench(client))]
        assert list(fixture) == roles
        for agent_key in roles:
            response = _post_schema_contract_upgrade(
                client, agent_key, roles.index(agent_key)
            )
            assert response.status_code == 200, agent_key
            assert response.json()["definition"]["selectable_optional_fields"] == [
                fixture[agent_key]
            ], agent_key


def test_a_dict_type_wire_error_is_strict_type_through_the_terminal_default(
    session_factory, monkeypatch
):
    """#264 m1: ``dict_type`` needs no entry in the explicit strict-type set.

    The explicit set in ``_validation_error_code`` used to list ``dict_type``, but
    the function's terminal default already returns ``strict_type``, so the entry
    was dead (correction 63).  This pins the observable result — a non-object
    ``field_overrides`` is ``strict_type`` with the owned message — and pins that
    the terminal default is what now serves it.
    """
    assert agent_definition_routes._validation_error_code(
        "candidate.schema_overlay.field_overrides", "dict_type", "string"
    ) == "strict_type"
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        before = _workbench(client)
        candidate = _editable_candidate(_model_node(before, "architect"))
        candidate["schema_overlay"] = {"field_overrides": ["not", "an", "object"]}
        response = client.put(
            _draft_save_url(), json={"lock_version": 0, "candidate": candidate}
        )
        after = _workbench(client)

    assert response.status_code == 422
    assert response.json()["errors"] == [
        {
            "field": "candidate.schema_overlay.field_overrides",
            "code": "strict_type",
            "message": "Field overrides must be an object.",
        }
    ]
    assert after == before


def test_the_overlay_type_error_catch_wraps_only_the_overlay_conversion(
    session_factory, monkeypatch
):
    """#264 m5: a ValidationError from the ASSEMBLY conversion is never reported as
    an overlay issue.

    The C1 catch renders its errors under the ``candidate.schema_overlay`` prefix,
    so it must wrap the overlay conversion alone.  An assembly conversion failure
    (not reachable from a valid wire body today, so it is forced here) must escape
    that catch rather than come back as a mislabelled ``candidate.schema_overlay``
    422; the overlay's own type errors still do (the sibling tests).
    """
    from pydantic import ValidationError

    from src.services.graph_definition_manifest import AssemblyRulesV2

    def _raising(rules):
        AssemblyRulesV2.model_validate({"format_version": 2, "custom_blocks": "not-a-list"})

    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory, raise_server_exceptions=False) as client:
        before = _workbench(client)
        candidate = _editable_candidate(_model_node(before, "architect"))
        candidate["assembly_rules"] = {"format_version": 2, "custom_blocks": []}
        with pytest.raises(ValidationError):
            _raising(None)
        monkeypatch.setattr(agent_definition_routes, "_domain_assembly_rules", _raising)
        response = client.put(
            _draft_save_url(), json={"lock_version": 0, "candidate": candidate}
        )
        monkeypatch.undo()
        _force_admin(monkeypatch, is_admin=True)
        after = _workbench(client)

    assert response.status_code == 500
    assert "candidate.schema_overlay" not in response.text
    assert after == before


# ===========================================================================
# #266 Task 3: read-only model endpoint discovery and the PUT's production
# remote endpoint validator
# ===========================================================================

_MODEL_ENDPOINTS_URL = "/api/admin/agent-definitions/model-endpoints"
_SEED_ENDPOINT = "databricks-claude-opus-4-6"
_CUSTOM_ENDPOINT = "Custom-Endpoint_266"
_CATALOG_FORBIDDEN = ModelEndpointCatalogFailure(
    "catalog_forbidden",
    "Model endpoint discovery is not permitted with this workspace identity.",
    False,
)
_CATALOG_UNAVAILABLE = ModelEndpointCatalogFailure(
    "catalog_unavailable",
    "Model endpoint discovery is temporarily unavailable. Retry the request.",
    True,
)
_ENDPOINT_UNAVAILABLE_MESSAGE = (
    "Endpoint validation is temporarily unavailable. Retry the save."
)


def _populated_discovery() -> SystemModelDiscovery:
    """Already in the catalog's `(display_name or name).casefold(), name` order."""
    return SystemModelDiscovery(
        endpoints=(
            SystemModelEndpoint(
                name=_SEED_ENDPOINT,
                display_name="Claude Opus 4.6",
                description="Anthropic frontier model",
                docs="https://docs.databricks.com/claude",
            ),
            SystemModelEndpoint(
                name="Databricks-GTE-Large_EN",
                display_name=None,
                description=None,
                docs=None,
            ),
            SystemModelEndpoint(
                name="databricks-meta-llama-3-3-70b-instruct",
                display_name="Meta Llama 3.3 70B Instruct",
                description=None,
                docs="https://docs.databricks.com/llama",
            ),
        )
    )


_EXPECTED_POPULATED_ITEMS = [
    {
        "name": _SEED_ENDPOINT,
        "display_name": "Claude Opus 4.6",
        "description": "Anthropic frontier model",
        "docs": "https://docs.databricks.com/claude",
    },
    {
        "name": "Databricks-GTE-Large_EN",
        "display_name": None,
        "description": None,
        "docs": None,
    },
    {
        "name": "databricks-meta-llama-3-3-70b-instruct",
        "display_name": "Meta Llama 3.3 70B Instruct",
        "description": None,
        "docs": "https://docs.databricks.com/llama",
    },
]


def _revision_count(factory: sessionmaker) -> int:
    with factory() as session:
        return len(session.scalars(select(AgentDefinitionRevision.id)).all())


def _endpoint_save_body(before: dict[str, object], endpoint_name: str) -> dict[str, object]:
    return {
        "lock_version": before["draft"]["lock_version"],
        "candidate": _editable_candidate(
            _model_node(before, "architect"), **{"model.endpoint_name": endpoint_name}
        ),
    }


def _one_endpoint_issue(code: str, message: str) -> dict[str, object]:
    return {
        "code": "invalid_draft",
        "errors": [
            {
                "field": "candidate.model.endpoint_name",
                "code": code,
                "message": message,
            }
        ],
    }


def _offline_system_client(monkeypatch: pytest.MonkeyPatch):
    """A real PAT-configured WorkspaceClient that performs no network I/O."""
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.config import Config

    # Host-metadata discovery is the only network step in PAT config resolution.
    monkeypatch.setattr(Config, "_resolve_host_metadata", lambda self: None)
    return WorkspaceClient(config=Config(host="https://unit.invalid", token="dapi-unit"))


def _assert_bounded_derivation(
    derived, system_client, system_inner, *, retry: int, http: int
) -> None:
    """The path's own bound, the system credentials, and an unchanged system client."""
    assert derived is not system_client
    assert derived.config.retry_timeout_seconds == retry
    assert derived.config.http_timeout_seconds == http
    assert derived.config.host == system_client.config.host
    assert derived.config._header_factory is system_client.config._header_factory
    assert system_client.config._inner == system_inner
    assert system_client.config.retry_timeout_seconds is None
    assert system_client.config.http_timeout_seconds is None


def test_model_endpoints_populated_response_is_exact_items_only_and_deterministic(
    session_factory, monkeypatch
):
    """Catches extra envelope keys, extra item metadata, rewritten names, or reordering."""
    _force_admin(monkeypatch, is_admin=True)
    catalog = FakeModelEndpointCatalog(
        discovery_outcomes=[_populated_discovery(), _populated_discovery()]
    )
    with _app_for(session_factory, catalog=catalog) as client:
        first = client.get(_MODEL_ENDPOINTS_URL)
        second = client.get(_MODEL_ENDPOINTS_URL)

    assert first.status_code == 200
    body = first.json()
    assert set(body) == {"items"}
    assert body == {"items": _EXPECTED_POPULATED_ITEMS}
    for item in body["items"]:
        assert set(item) == {"name", "display_name", "description", "docs"}
        assert not {"task", "provider", "id", "endpoint_id"} & set(item)
    assert body["items"][0]["name"] == _SEED_ENDPOINT
    assert second.status_code == 200
    assert second.content == first.content
    assert catalog.list_calls == 2


def test_model_endpoints_empty_catalog_is_200_empty_items(session_factory, monkeypatch):
    """Catches an empty discovery reported as an error or with extra keys."""
    _force_admin(monkeypatch, is_admin=True)
    catalog = FakeModelEndpointCatalog(discovery_outcomes=[SystemModelDiscovery(())])
    with _app_for(session_factory, catalog=catalog) as client:
        response = client.get(_MODEL_ENDPOINTS_URL)

    assert response.status_code == 200
    assert response.json() == {"items": []}
    assert catalog.list_calls == 1


@pytest.mark.parametrize(
    ("failure", "status"),
    [(_CATALOG_FORBIDDEN, 403), (_CATALOG_UNAVAILABLE, 503)],
    ids=["forbidden", "unavailable"],
)
def test_model_endpoints_catalog_failure_is_only_the_documented_envelope(
    session_factory, monkeypatch, failure, status
):
    """Catches a typed catalog failure collapsed into empty success or another status."""
    _force_admin(monkeypatch, is_admin=True)
    catalog = FakeModelEndpointCatalog(discovery_outcomes=[failure])
    with _app_for(session_factory, catalog=catalog) as client:
        response = client.get(_MODEL_ENDPOINTS_URL)

    assert response.status_code == status
    assert response.json() == {
        "code": failure.code,
        "message": str(failure),
        "retryable": failure.retryable,
    }
    assert "items" not in response.json()
    assert catalog.list_calls == 1


def test_model_endpoints_openapi_documents_only_200_403_and_503(session_factory):
    """Catches an undocumented or mis-modelled discovery error status."""
    app = FastAPI()
    app.include_router(router)
    operation = app.openapi()["paths"][_MODEL_ENDPOINTS_URL]["get"]
    responses = operation["responses"]

    assert set(responses) == {"200", "403", "503"}
    assert responses["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SystemModelDiscoveryResponse"
    }
    for status in ("403", "503"):
        assert responses[status]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ModelEndpointCatalogErrorResponse"
        }
    assert "parameters" not in operation
    assert "requestBody" not in operation


def test_model_endpoints_unexpected_catalog_error_is_a_nonleaking_500(
    session_factory, monkeypatch
):
    """Catches a broad catch that turns an unexpected fault into a typed 503 or 200."""
    _force_admin(monkeypatch, is_admin=True)
    catalog = FakeModelEndpointCatalog(
        discovery_outcomes=[ValueError("SECRET_TOKEN_266 https://secret-host.example")]
    )
    with _app_for(session_factory, raise_server_exceptions=False, catalog=catalog) as client:
        response = client.get(_MODEL_ENDPOINTS_URL)

    assert response.status_code == 500
    assert "SECRET_TOKEN_266" not in response.text
    assert "secret-host" not in response.text
    assert "catalog_unavailable" not in response.text


def test_non_admin_model_endpoints_is_denied_before_the_catalog_is_obtained(
    session_factory, monkeypatch
):
    """Catches a discovery route that resolves or calls the catalog before authorization."""
    import src.core.databricks_client as databricks_client
    from src.services import model_endpoint_catalog as catalog_module

    _force_admin(monkeypatch, is_admin=False)
    injected = FakeModelEndpointCatalog(discovery_outcomes=[_populated_discovery()])
    resolved: list[str] = []
    production: list[str] = []

    def _recording_catalog():
        resolved.append("catalog")
        return injected

    def _must_not_build(*_args, **_kwargs):
        production.append("built")
        raise AssertionError("authorization reached the production catalog")

    monkeypatch.setattr(databricks_client, "get_system_client", _must_not_build)
    monkeypatch.setattr(catalog_module, "DatabricksModelEndpointCatalog", _must_not_build)
    with _app_for(session_factory, raise_server_exceptions=False) as client:
        production_response = client.get(_MODEL_ENDPOINTS_URL)
        client.app.dependency_overrides[
            agent_definition_routes.get_model_endpoint_catalog
        ] = _recording_catalog
        injected_response = client.get(_MODEL_ENDPOINTS_URL)

    for response in (production_response, injected_response):
        assert response.status_code == 403
        assert response.json() == {"detail": "Admin access required"}
        assert _SEED_ENDPOINT not in response.text
    assert resolved == []
    assert production == []
    assert injected.list_calls == 0


def test_model_endpoints_production_dependency_lists_through_the_bounded_system_catalog(
    session_factory, monkeypatch
):
    """Catches discovery skipping its own 30 s/30 s bound or mutating the system client."""
    import src.core.databricks_client as databricks_client
    from src.services import model_endpoint_catalog as catalog_module

    _force_admin(monkeypatch, is_admin=True)
    system_client = _offline_system_client(monkeypatch)
    system_inner = dict(system_client.config._inner)
    catalog = FakeModelEndpointCatalog(discovery_outcomes=[_populated_discovery()])
    calls: list[tuple[str, object]] = []

    def _get_system_client():
        calls.append(("system", None))
        return system_client

    def _catalog(workspace_client):
        calls.append(("catalog", workspace_client))
        return catalog

    monkeypatch.setattr(databricks_client, "get_system_client", _get_system_client)
    monkeypatch.setattr(catalog_module, "DatabricksModelEndpointCatalog", _catalog)
    with _app_for(session_factory) as client:
        response = client.get(_MODEL_ENDPOINTS_URL)

    assert response.status_code == 200
    assert response.json() == {"items": _EXPECTED_POPULATED_ITEMS}
    assert [name for name, _ in calls] == ["system", "catalog"]
    _assert_bounded_derivation(calls[1][1], system_client, system_inner, retry=30, http=30)
    assert catalog.list_calls == 1


def test_model_endpoints_system_client_failure_is_the_typed_503(
    session_factory, monkeypatch
):
    """Catches a system-client construction failure escaping discovery as a 500."""
    import src.core.databricks_client as databricks_client

    _force_admin(monkeypatch, is_admin=True)

    def _failing_system_client():
        raise databricks_client.DatabricksClientError(
            "Failed to initialize system Databricks client: SECRET_TOKEN_266"
        )

    monkeypatch.setattr(databricks_client, "get_system_client", _failing_system_client)
    with _app_for(session_factory, raise_server_exceptions=False) as client:
        response = client.get(_MODEL_ENDPOINTS_URL)

    assert response.status_code == 503
    assert response.json() == {
        "code": "catalog_unavailable",
        "message": "Model endpoint discovery is temporarily unavailable. Retry the request.",
        "retryable": True,
    }
    assert "SECRET_TOKEN_266" not in response.text


def test_model_endpoints_catalog_is_never_invoked_by_workbench_or_tools_routes(
    session_factory, monkeypatch
):
    """Catches the workbench read or the generic tools discovery reusing this catalog."""
    import src.core.databricks_client as databricks_client
    from src.api.routes import tools as tools_routes
    from src.services import model_endpoint_catalog as catalog_module

    _force_admin(monkeypatch, is_admin=True)
    catalog = FakeModelEndpointCatalog(discovery_outcomes=[_populated_discovery()])
    production: list[str] = []

    def _must_not_build(*_args, **_kwargs):
        production.append("built")
        raise AssertionError("a non-discovery route reached the model endpoint catalog")

    class _ServingEndpoints:
        def list(self):
            return []

    class _UserClient:
        serving_endpoints = _ServingEndpoints()

    monkeypatch.setattr(databricks_client, "get_system_client", _must_not_build)
    monkeypatch.setattr(catalog_module, "DatabricksModelEndpointCatalog", _must_not_build)
    monkeypatch.setattr(tools_routes, "get_user_client", lambda: _UserClient())
    with _app_for(session_factory, catalog=catalog) as client:
        client.app.include_router(tools_routes.router)
        workbench = client.get("/api/admin/agent-definitions/workbench")
        tools_models = client.get("/api/tools/discover/model-endpoints")
        tools_agents = client.get("/api/tools/discover/agent-bricks")

    assert workbench.status_code == 200
    assert tools_models.status_code == 200
    assert tools_agents.status_code == 200
    assert catalog.list_calls == 0
    assert catalog.validated_names == []
    assert production == []


def test_non_admin_endpoint_validation_put_rejects_before_body_catalog_or_writer(
    session_factory, monkeypatch
):
    """Catches a PUT that parses, validates remotely, or writes before authorization."""
    import src.core.databricks_client as databricks_client

    _force_admin(monkeypatch, is_admin=False)
    catalog = FakeModelEndpointCatalog()
    calls: list[str] = []

    def _recording_validator():
        calls.append("validator")
        return CatalogRemoteEndpointDraftValidator(lambda: catalog)

    def _must_not_write(*_args, **_kwargs):
        calls.append("write")
        raise AssertionError("authorization reached the draft writer")

    def _must_not_build(*_args, **_kwargs):
        calls.append("system-client")
        raise AssertionError("authorization reached the production catalog")

    monkeypatch.setattr(GraphConfiguration, "save_editable_model_draft", _must_not_write)
    monkeypatch.setattr(databricks_client, "get_system_client", _must_not_build)
    secret_url = "https://SECRET-HOST-266.cloud.databricks.com/serving-endpoints/x?token=dapiSECRET"
    bodies = [
        b'{"lock_version": 0, "candidate": {"prompt_text": "SUPER_SECRET_PROMPT", '
        b'"model": {"endpoint_name": "' + secret_url.encode() + b'"',
        json.dumps(
            {
                "lock_version": 0,
                "candidate": {
                    "prompt_text": "SUPER_SECRET_PROMPT",
                    "model": {
                        "endpoint_name": secret_url,
                        "temperature": 0.1,
                        "max_tokens": 10,
                        "top_p": 0.9,
                    },
                },
            }
        ).encode(),
    ]
    responses = []
    for production in (True, False):
        with _app_for(
            session_factory,
            raise_server_exceptions=False,
            production_endpoint_validation=production,
        ) as client:
            if not production:
                client.app.dependency_overrides[
                    agent_definition_routes.get_remote_endpoint_draft_validator
                ] = _recording_validator
            for body in bodies:
                responses.append(
                    client.put(
                        _draft_save_url(),
                        content=body,
                        headers={"content-type": "application/json"},
                    )
                )

    assert calls == []
    assert catalog.validated_names == []
    for response in responses:
        assert response.status_code == 403
        assert response.json() == {"detail": "Admin access required"}
        assert "SUPER_SECRET_PROMPT" not in response.text
        assert "SECRET-HOST-266" not in response.text
        assert "dapiSECRET" not in response.text


_ENDPOINT_TABLE = [
    (
        "endpoint_url_not_allowed",
        "Endpoint must be a Databricks endpoint name, not a URL.",
        False,
    ),
    ("endpoint_unknown", "Endpoint name was not found.", False),
    (
        "endpoint_forbidden",
        "Endpoint cannot be validated with this workspace identity.",
        False,
    ),
    ("endpoint_unavailable", _ENDPOINT_UNAVAILABLE_MESSAGE, True),
    (
        "endpoint_name_mismatch",
        "Endpoint validation did not return the exact requested name.",
        False,
    ),
    ("endpoint_not_ready", "Endpoint is not ready for invocation.", True),
    (
        "endpoint_update_in_progress",
        "Endpoint configuration update is in progress.",
        True,
    ),
    ("endpoint_update_failed", "Endpoint configuration update failed.", False),
    (
        "endpoint_update_canceled",
        "Endpoint configuration update was canceled.",
        False,
    ),
]


@pytest.mark.parametrize(
    ("code", "message", "retryable"),
    _ENDPOINT_TABLE,
    ids=[row[0] for row in _ENDPOINT_TABLE],
)
def test_endpoint_validation_table_outcomes_are_one_item_invalid_draft_with_no_mutation(
    session_factory, monkeypatch, code, message, retryable
):
    """Catches a remote or local endpoint rejection that leaks, reshapes, or writes."""
    _force_admin(monkeypatch, is_admin=True)
    if code == "endpoint_url_not_allowed":
        endpoint_name = "https://SECRET-HOST-266.example/serving-endpoints/x"
        catalog = FakeModelEndpointCatalog()
    else:
        endpoint_name = _CUSTOM_ENDPOINT
        catalog = FakeModelEndpointCatalog(
            validation_outcomes={
                endpoint_name: [EndpointValidationFailure(code, message, retryable)]
            }
        )
    validator = CatalogRemoteEndpointDraftValidator(lambda: catalog)
    revisions_before = _revision_count(session_factory)
    with _app_for(session_factory, remote_endpoint_validator=validator) as client:
        before = _workbench(client)
        response = client.put(_draft_save_url(), json=_endpoint_save_body(before, endpoint_name))
        after = _workbench(client)

    assert response.status_code == 422
    assert response.json() == _one_endpoint_issue(code, message)
    assert endpoint_name not in response.text
    assert after == before
    assert _revision_count(session_factory) == revisions_before
    expected_calls = [] if code == "endpoint_url_not_allowed" else [endpoint_name]
    assert catalog.validated_names == expected_calls


def test_endpoint_validation_accepted_save_validates_the_exact_submitted_name(
    session_factory, monkeypatch
):
    """Catches a PUT that rewrites the endpoint or bypasses the injected validator."""
    _force_admin(monkeypatch, is_admin=True)
    catalog = FakeModelEndpointCatalog()
    validator = CatalogRemoteEndpointDraftValidator(lambda: catalog)
    with _app_for(session_factory, remote_endpoint_validator=validator) as client:
        before = _workbench(client)
        response = client.put(
            _draft_save_url(), json=_endpoint_save_body(before, _CUSTOM_ENDPOINT)
        )
        after = _workbench(client)

    assert response.status_code == 200
    assert response.json()["definition"]["model"]["endpoint_name"] == _CUSTOM_ENDPOINT
    assert _model_node(after, "architect")["draft"]["model"]["endpoint_name"] == (
        _CUSTOM_ENDPOINT
    )
    assert catalog.validated_names == [_CUSTOM_ENDPOINT]


def test_endpoint_validation_production_dependency_supplies_the_remote_validator(
    session_factory, monkeypatch
):
    """Catches the PUT's production wiring failing open or losing the 5 s/3 s save bound."""
    import src.core.databricks_client as databricks_client
    from src.services import model_endpoint_catalog as catalog_module

    _force_admin(monkeypatch, is_admin=True)
    system_client = _offline_system_client(monkeypatch)
    system_inner = dict(system_client.config._inner)
    catalog = FakeModelEndpointCatalog(
        validation_outcomes={
            _CUSTOM_ENDPOINT: [
                EndpointValidationFailure(
                    "endpoint_unknown", "Endpoint name was not found.", False
                )
            ]
        }
    )
    calls: list[tuple[str, object]] = []

    def _get_system_client():
        calls.append(("system", None))
        return system_client

    def _catalog(workspace_client):
        calls.append(("catalog", workspace_client))
        return catalog

    monkeypatch.setattr(databricks_client, "get_system_client", _get_system_client)
    monkeypatch.setattr(catalog_module, "DatabricksModelEndpointCatalog", _catalog)
    revisions_before = _revision_count(session_factory)
    with _app_for(session_factory, production_endpoint_validation=True) as client:
        before = _workbench(client)
        assert calls == []
        response = client.put(
            _draft_save_url(), json=_endpoint_save_body(before, _CUSTOM_ENDPOINT)
        )
        after = _workbench(client)

    assert response.status_code == 422
    assert response.json() == _one_endpoint_issue(
        "endpoint_unknown", "Endpoint name was not found."
    )
    assert [name for name, _ in calls] == ["system", "catalog"]
    _assert_bounded_derivation(calls[1][1], system_client, system_inner, retry=5, http=3)
    assert catalog.validated_names == [_CUSTOM_ENDPOINT]
    assert after == before
    assert _revision_count(session_factory) == revisions_before


def test_endpoint_validation_system_client_failure_is_typed_endpoint_unavailable(
    session_factory, monkeypatch
):
    """Catches a system-client construction failure escaping the PUT as a 500."""
    import src.core.databricks_client as databricks_client

    _force_admin(monkeypatch, is_admin=True)

    def _failing_system_client():
        raise databricks_client.DatabricksClientError(
            "Failed to initialize system Databricks client: SECRET_TOKEN_266"
        )

    monkeypatch.setattr(databricks_client, "get_system_client", _failing_system_client)
    revisions_before = _revision_count(session_factory)
    with _app_for(
        session_factory,
        raise_server_exceptions=False,
        production_endpoint_validation=True,
    ) as client:
        before = _workbench(client)
        response = client.put(
            _draft_save_url(), json=_endpoint_save_body(before, _CUSTOM_ENDPOINT)
        )
        after = _workbench(client)

    assert response.status_code == 422
    assert response.json() == _one_endpoint_issue(
        "endpoint_unavailable", _ENDPOINT_UNAVAILABLE_MESSAGE
    )
    assert "SECRET_TOKEN_266" not in response.text
    assert _CUSTOM_ENDPOINT not in response.text
    assert after == before
    assert _revision_count(session_factory) == revisions_before


def test_endpoint_validation_dependency_is_resolved_only_by_the_draft_put(
    session_factory, monkeypatch
):
    """Catches the remote validator wired into the upgrade, source, or read routes."""
    _force_admin(monkeypatch, is_admin=True)
    resolved: list[str] = []

    def _recording_validator():
        resolved.append("validator")
        return _accepting_remote_endpoint_validator()

    catalog = FakeModelEndpointCatalog(discovery_outcomes=[SystemModelDiscovery(())])
    with _app_for(session_factory, catalog=catalog) as client:
        client.app.dependency_overrides[
            agent_definition_routes.get_remote_endpoint_draft_validator
        ] = _recording_validator
        before = _workbench(client)
        client.get(_MODEL_ENDPOINTS_URL)
        _post_upgrade(client, "architect", before["draft"]["lock_version"])
        _post_schema_contract_upgrade(client, "architect", before["draft"]["lock_version"])
        client.post(_source_url(), json={"lock_version": before["draft"]["lock_version"]})
        assert resolved == []
        current = _workbench(client)
        response = client.put(
            _draft_save_url(), json=_endpoint_save_body(current, _SEED_ENDPOINT)
        )

    assert response.status_code == 200
    assert resolved == ["validator"]


@pytest.mark.parametrize(
    ("dto_name", "valid"),
    [
        (
            "SystemModelEndpointResponse",
            {"name": _SEED_ENDPOINT, "display_name": None, "description": None, "docs": None},
        ),
        ("SystemModelDiscoveryResponse", {"items": []}),
        (
            "ModelEndpointCatalogErrorResponse",
            {"code": "catalog_unavailable", "message": "m", "retryable": True},
        ),
    ],
)
def test_model_endpoints_dtos_are_strict_siblings_that_forbid_extra_keys(dto_name, valid):
    """Catches a discovery DTO that accepts task/provider/ID keys or extends a #263 DTO."""
    from pydantic import ValidationError

    from src.api.schemas import agent_definitions as schemas

    dto = getattr(schemas, dto_name)
    dto.model_validate(valid)
    with pytest.raises(ValidationError):
        dto.model_validate({**valid, "task": "llm/v1/chat"})
    assert dto.__mro__[1] is schemas.BaseModel


# ---------------------------------------------------------------------------
# #266 Task 5: POST /draft/{agent_key}/model-endpoint-probe
# ---------------------------------------------------------------------------

_PROBE_FAILURE_CASES = {
    "unsupported_structured_output": (422, "Unsupported copy.", False),
    "endpoint_probe_forbidden": (403, "Forbidden copy.", False),
    "structured_output_probe_failed": (503, "Unavailable copy.", True),
}
_PROBE_SECRET = "PROBE_SECRET_https://leak.example/token"


def _probe_url(agent_key: str = "architect") -> str:
    return f"/api/admin/agent-definitions/draft/{agent_key}/model-endpoint-probe"


def _all_table_rows(session_factory: sessionmaker) -> dict[str, list[tuple[object, ...]]]:
    with session_factory() as session:
        return {
            table.name: [tuple(row) for row in session.execute(select(table))]
            for table in Base.metadata.sorted_tables
        }


def _save_role_endpoint(client: TestClient, agent_key: str, endpoint_name: str) -> dict:
    body = _workbench(client)
    node = _model_node(body, agent_key)
    response = client.put(
        _draft_save_url(agent_key),
        json={
            "lock_version": body["draft"]["lock_version"],
            "candidate": _editable_candidate(
                node,
                **{
                    "model.endpoint_name": endpoint_name,
                    "model.temperature": 0.125,
                    "model.max_tokens": 777,
                    "model.top_p": 0.875,
                },
            ),
        },
    )
    assert response.status_code == 200
    return response.json()


def test_model_endpoint_probe_route_probes_each_selected_roles_saved_candidate(
    session_factory, monkeypatch
):
    """Catches the route probing another role's endpoint, a default, or a stale copy."""
    _force_admin(monkeypatch, is_admin=True)
    probe = FakeStructuredOutputProbe()
    with _app_for(session_factory, probe=probe) as client:
        _save_role_endpoint(client, "architect", "architect exact endpoint")
        _save_role_endpoint(client, "builder", "builder exact endpoint")
        body = _workbench(client)
        builder = client.post(_probe_url("builder"), json={"lock_version": 2})
        architect = client.post(_probe_url("architect"), json={"lock_version": 2})

    assert [call.endpoint_name for call in probe.calls] == [
        "builder exact endpoint",
        "architect exact endpoint",
    ]
    assert [
        (call.temperature, call.max_tokens, call.top_p) for call in probe.calls
    ] == [(0.125, 777, 0.875), (0.125, 777, 0.875)]
    for response, agent_key, endpoint_name in (
        (builder, "builder", "builder exact endpoint"),
        (architect, "architect", "architect exact endpoint"),
    ):
        assert response.status_code == 200
        assert response.json() == {
            "code": "structured_output_probe_succeeded",
            "endpoint_name": endpoint_name,
            "candidate_hash": _model_node(body, agent_key)["draft"]["candidate_hash"],
            "lock_version": 2,
        }
        assert list(response.json()) == [
            "code",
            "endpoint_name",
            "candidate_hash",
            "lock_version",
        ]


@pytest.mark.parametrize("code", sorted(_PROBE_FAILURE_CASES))
def test_model_endpoint_probe_route_maps_each_typed_failure_exactly(
    session_factory, monkeypatch, code
):
    """Catches a wrong status, a lost identity, or a message not copied verbatim."""
    _force_admin(monkeypatch, is_admin=True)
    status, message, retryable = _PROBE_FAILURE_CASES[code]
    probe = FakeStructuredOutputProbe([StructuredOutputProbeFailure(code, message, retryable)])
    with _app_for(session_factory, probe=probe) as client:
        body = _workbench(client)
        response = client.post(_probe_url("architect"), json={"lock_version": 0})

    assert len(probe.calls) == 1
    assert response.status_code == status
    assert response.json() == {
        "code": code,
        "message": message,
        "retryable": retryable,
        "endpoint_name": _model_node(body, "architect")["draft"]["model"]["endpoint_name"],
        "candidate_hash": _model_node(body, "architect")["draft"]["candidate_hash"],
        "lock_version": 0,
    }
    assert list(response.json()) == [
        "code",
        "message",
        "retryable",
        "endpoint_name",
        "candidate_hash",
        "lock_version",
    ]


@pytest.mark.parametrize(
    "extra",
    [
        {"endpoint_name": "client-chosen"},
        {"endpoint": "client-chosen"},
        {"url": "https://leak.example/serving-endpoints/x"},
        {"host": "leak.example"},
        {"token": "dapi-secret"},
        {"prompt": "client prompt"},
        {"schema": {"type": "object"}},
        {"payload": {"x": 1}},
        {"identity": {"session_id": "s"}},
        {"session_id": "s"},
        {"candidate": {"model": {"endpoint_name": "client-chosen"}}},
    ],
    ids=lambda extra: next(iter(extra)),
)
def test_model_endpoint_probe_route_rejects_every_client_field_but_the_lock(
    session_factory, monkeypatch, extra
):
    """Catches the probe accepting a client endpoint, prompt, schema or identity.

    The body is exactly ``{"lock_version": n}``: every other key is the strict
    DTO's ``extra_forbidden`` 422 and the probe is never called.
    """
    _force_admin(monkeypatch, is_admin=True)
    probe = FakeStructuredOutputProbe()
    key = next(iter(extra))
    with _app_for(session_factory, probe=probe) as client:
        response = client.post(_probe_url(), json={"lock_version": 0, **extra})

    assert probe.calls == []
    assert response.status_code == 422
    assert response.json() == {
        "code": "invalid_draft",
        "errors": [
            {"field": key, "code": "extra_forbidden", "message": "Extra inputs are not permitted"}
        ],
    }
    assert "client-chosen" not in response.text
    assert "leak.example" not in response.text
    assert "dapi-secret" not in response.text


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (b"{not json", [("$", "invalid_json")]),
        (b"{}", [("lock_version", "strict_type")]),
        (b'{"lock_version": "0"}', [("lock_version", "strict_type")]),
        (b'{"lock_version": true}', [("lock_version", "strict_type")]),
        (b'{"lock_version": -1}', [("lock_version", "out_of_range")]),
        (b"[]", [("$", "strict_type")]),
    ],
)
def test_model_endpoint_probe_route_rejects_malformed_bodies_without_probing(
    session_factory, monkeypatch, body, expected
):
    """Catches a malformed body defaulting the lock or reaching the probe."""
    _force_admin(monkeypatch, is_admin=True)
    probe = FakeStructuredOutputProbe()
    with _app_for(session_factory, probe=probe) as client:
        response = client.post(
            _probe_url(), content=body, headers={"content-type": "application/json"}
        )

    assert probe.calls == []
    assert response.status_code == 422
    assert [(e["field"], e["code"]) for e in response.json()["errors"]] == expected


@pytest.mark.parametrize("agent_key", ["foreman", "unknown"])
def test_model_endpoint_probe_route_rejects_non_editable_roles(
    session_factory, monkeypatch, agent_key
):
    """Catches a deterministic or unknown role reaching the probe."""
    _force_admin(monkeypatch, is_admin=True)
    probe = FakeStructuredOutputProbe()
    with _app_for(session_factory, probe=probe) as client:
        response = client.post(_probe_url(agent_key), json={"lock_version": 0})

    assert probe.calls == []
    assert response.status_code == 422
    assert response.json() == {
        "code": "invalid_draft",
        "errors": [
            {
                "field": "agent_key",
                "code": "unknown_agent",
                "message": "Agent key must identify an editable model role.",
            }
        ],
    }


def test_model_endpoint_probe_route_stale_lock_is_the_coherent_null_candidate_409(
    session_factory, monkeypatch
):
    """Catches a stale request probing before the lock comparison."""
    _force_admin(monkeypatch, is_admin=True)
    probe = FakeStructuredOutputProbe()
    with _app_for(session_factory, probe=probe) as client:
        _save_role_endpoint(client, "architect", "moved on")
        after = _workbench(client)
        response = client.post(_probe_url("architect"), json={"lock_version": 0})

    assert probe.calls == []
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "stale_draft"
    assert body["client_candidate"] is None
    assert (body["expected_lock_version"], body["current_lock_version"]) == (0, 1)
    assert body["server"]["draft"] == after["draft"]
    assert set(body["server"]["definitions"]) == set(EXPECTED_TOPOLOGY_ORDER) - {"foreman"}
    assert (
        body["server"]["definitions"]["architect"]["model"]["endpoint_name"] == "moved on"
    )


def test_model_endpoint_probe_route_policy_recheck_is_the_ordered_422(
    session_factory, monkeypatch
):
    """Catches a URL-shaped saved name reaching the provider through the route."""
    import src.services.graph_configuration_draft as draft_module

    _force_admin(monkeypatch, is_admin=True)
    probe = FakeStructuredOutputProbe()
    original = draft_module.validate_endpoint_name_policy
    # Simulate a saved name that predates the policy: the stored seed name is
    # checked as if it were URL-shaped, without rewriting any row.
    monkeypatch.setattr(
        draft_module,
        "validate_endpoint_name_policy",
        lambda name: original("https://" + name),
    )
    with _app_for(session_factory, probe=probe) as client:
        response = client.post(_probe_url("architect"), json={"lock_version": 0})

    assert probe.calls == []
    assert response.status_code == 422
    assert response.json() == {
        "code": "invalid_draft",
        "errors": [
            {
                "field": "candidate.model.endpoint_name",
                "code": "endpoint_url_not_allowed",
                "message": "Endpoint must be a Databricks endpoint name, not a URL.",
            }
        ],
    }


@pytest.mark.parametrize("outcome", ["success", "failure"])
def test_model_endpoint_probe_route_writes_no_row_of_any_kind(
    session_factory, monkeypatch, outcome
):
    """Catches a probe that saves, audits, advances the lock, or records a run/chat/deck."""
    _force_admin(monkeypatch, is_admin=True)
    queued = (
        []
        if outcome == "success"
        else [StructuredOutputProbeFailure("structured_output_probe_failed", "m", True)]
    )
    probe = FakeStructuredOutputProbe(queued)
    before = _all_table_rows(session_factory)
    with _app_for(session_factory, probe=probe) as client:
        response = client.post(_probe_url("architect"), json={"lock_version": 0})

    assert response.status_code == (200 if outcome == "success" else 503)
    assert _all_table_rows(session_factory) == before


def test_model_endpoint_probe_route_calls_the_model_off_the_event_loop(
    session_factory, monkeypatch
):
    """Catches a remote model call blocking the server's event loop."""
    import asyncio

    _force_admin(monkeypatch, is_admin=True)
    loop_running: list[bool] = []

    class _LoopObservingProbe:
        def probe(self, configuration) -> None:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                loop_running.append(False)
            else:
                loop_running.append(True)

    with _app_for(session_factory, probe=_LoopObservingProbe()) as client:
        response = client.post(_probe_url(), json={"lock_version": 0})

    assert response.status_code == 200
    assert loop_running == [False]


def test_draft_save_route_runs_remote_endpoint_validation_off_the_event_loop(
    session_factory, monkeypatch
):
    """Catches the save PUT's lock-held remote endpoint check blocking the event loop."""
    import asyncio

    _force_admin(monkeypatch, is_admin=True)
    loop_running: list[bool] = []
    validated: list[str] = []

    class _LoopObservingRemoteValidator:
        def validate(self, content) -> None:
            validated.append(content.model.endpoint_name)
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                loop_running.append(False)
            else:
                loop_running.append(True)

    with _app_for(
        session_factory, remote_endpoint_validator=_LoopObservingRemoteValidator()
    ) as client:
        before = _workbench(client)
        response = client.put(
            _draft_save_url(), json=_endpoint_save_body(before, _CUSTOM_ENDPOINT)
        )

    assert response.status_code == 200
    assert validated == [_CUSTOM_ENDPOINT]
    assert loop_running == [False], (
        f"remote endpoint validation ran on the event loop: {loop_running}"
    )


def test_model_endpoint_probe_route_later_save_cannot_change_the_reported_identity(
    session_factory, monkeypatch
):
    """Catches identity read back after the call instead of copied before it."""
    _force_admin(monkeypatch, is_admin=True)
    saved: list[int] = []

    with _app_for(session_factory) as client:
        before = _workbench(client)

        class _SavingProbe:
            def probe(self, configuration) -> None:
                with session_factory() as session:
                    outcome = GraphConfiguration().save_editable_model_draft(
                        session,
                        agent_key="architect",
                        expected_lock_version=0,
                        candidate=_domain_candidate(before, "architect", "saved mid-probe"),
                        actor="concurrent-admin@example.com",
                    )
                saved.append(outcome.draft.lock_version)

        client.app.dependency_overrides[
            agent_definition_routes.get_structured_output_probe
        ] = lambda: _SavingProbe()
        response = client.post(_probe_url("architect"), json={"lock_version": 0})
        after = _workbench(client)

    assert saved == [1]
    assert _model_node(after, "architect")["draft"]["model"]["endpoint_name"] == (
        "saved mid-probe"
    )
    assert response.status_code == 200
    assert response.json() == {
        "code": "structured_output_probe_succeeded",
        "endpoint_name": _model_node(before, "architect")["draft"]["model"]["endpoint_name"],
        "candidate_hash": _model_node(before, "architect")["draft"]["candidate_hash"],
        "lock_version": 0,
    }


def _domain_candidate(body: dict, agent_key: str, endpoint_name: str):
    from src.services.graph_configuration import EditableModelDraft

    draft = _model_node(body, agent_key)["draft"]
    return EditableModelDraft(
        prompt_text=draft["prompt_text"],
        endpoint_name=endpoint_name,
        temperature=float(draft["model"]["temperature"]),
        max_tokens=int(draft["model"]["max_tokens"]),
        top_p=float(draft["model"]["top_p"]),
    )


@pytest.mark.parametrize(
    "body",
    [
        b"{not json; PROBE_SECRET_https://leak.example/token",
        b'{"lock_version": 0, "endpoint_name": "PROBE_SECRET_https://leak.example/token"}',
        b'{"lock_version": 0}',
    ],
    ids=["malformed", "extra", "valid"],
)
def test_auth_before_probe_body_non_admin_is_denied_without_parsing(
    session_factory, monkeypatch, body
):
    """Catches authorization after body parsing, a probe call, or a body echo."""
    _force_admin(monkeypatch, is_admin=False)
    calls: list[str] = []

    async def _must_not_parse_json(_request):
        calls.append("body")
        raise AssertionError("authorization parsed the raw request body")

    def _must_not_resolve_probe():
        calls.append("probe-dependency")
        raise AssertionError("authorization resolved the probe")

    monkeypatch.setattr(agent_definition_routes.Request, "json", _must_not_parse_json)
    with _app_for(session_factory, raise_server_exceptions=False, production_probe=True) as client:
        client.app.dependency_overrides[
            agent_definition_routes.get_structured_output_probe
        ] = _must_not_resolve_probe
        response = client.post(
            _probe_url("architect"),
            content=body,
            headers={"content-type": "application/json"},
        )

    assert calls == []
    assert response.status_code == 403
    assert response.json() == {"detail": "Admin access required"}
    assert _PROBE_SECRET not in response.text
    assert "leak.example" not in response.text


def test_model_endpoint_probe_route_production_dependency_is_the_databricks_probe():
    """Catches the production route wired to a fake, None, or a second model factory."""
    from src.services.agent_runtime import DatabricksModelAdapter

    probe = agent_definition_routes.get_structured_output_probe()

    assert isinstance(probe, DatabricksStructuredOutputProbe)
    assert probe._model_factory is DatabricksModelAdapter._default_model_factory
    assert probe._client_factory is DatabricksModelAdapter._default_client_factory


@pytest.mark.parametrize(
    ("dto_name", "valid"),
    [
        (
            "StructuredOutputProbeSuccessResponse",
            {
                "code": "structured_output_probe_succeeded",
                "endpoint_name": _SEED_ENDPOINT,
                "candidate_hash": "a" * 64,
                "lock_version": 0,
            },
        ),
        (
            "StructuredOutputProbeFailureResponse",
            {
                "code": "structured_output_probe_failed",
                "message": "m",
                "retryable": True,
                "endpoint_name": _SEED_ENDPOINT,
                "candidate_hash": "a" * 64,
                "lock_version": 0,
            },
        ),
    ],
)
def test_model_endpoint_probe_dtos_are_strict_siblings_that_forbid_extra_keys(dto_name, valid):
    """Catches a probe DTO that accepts extra keys or extends a #263 DTO (c9)."""
    from pydantic import ValidationError

    from src.api.schemas import agent_definitions as schemas

    dto = getattr(schemas, dto_name)
    dto.model_validate(valid)
    with pytest.raises(ValidationError):
        dto.model_validate({**valid, "approved": True})
    assert dto.__mro__[1] is schemas.BaseModel
    assert not issubclass(dto, schemas.DraftLockRequest)


_REAL_PROVIDER_ROUTE_EXPECTATIONS = {
    "unsupported_structured_output": (422, False),
    "endpoint_probe_forbidden": (403, False),
    "structured_output_probe_failed": (503, True),
}


def _real_provider_cases():
    from tests.unit.test_model_endpoint_probe import REAL_PROVIDER_CASES

    return REAL_PROVIDER_CASES


@pytest.mark.parametrize(("outcome", "code"), _real_provider_cases(), ids=str)
def test_model_endpoint_probe_route_maps_real_provider_errors(
    session_factory, monkeypatch, outcome, code
):
    """Fix round 1: the real ``ChatDatabricks`` over a mock transport, through the route.

    Catches a real provider rejection surfacing as the retryable 503, and any
    provider text, mock host or request detail reaching the response.
    """
    from tests.unit.test_model_endpoint_probe import (
        MOCK_HOST,
        PROVIDER_SECRET,
        MockTransportWorkspace,
        real_provider_probe,
    )

    _force_admin(monkeypatch, is_admin=True)
    workspace = MockTransportWorkspace(outcome)
    with _app_for(session_factory, probe=real_provider_probe(workspace)) as client:
        body = _workbench(client)
        response = client.post(_probe_url("architect"), json={"lock_version": 0})

    status, retryable = _REAL_PROVIDER_ROUTE_EXPECTATIONS[code]
    assert len(workspace.requests) == 1
    assert workspace.requests[0].url.host == MOCK_HOST
    assert response.status_code == status
    payload = response.json()
    assert (payload["code"], payload["retryable"]) == (code, retryable)
    assert payload["endpoint_name"] == _model_node(body, "architect")["draft"]["model"][
        "endpoint_name"
    ]
    assert PROVIDER_SECRET not in response.text
    assert "leak.example" not in response.text
    assert MOCK_HOST not in response.text
    assert "unit-test-dummy-key" not in response.text


# ===========================================================================
# #267 Task 2: Agent Test Case CRUD routes on the one admin router (C9, C22, C23)
# ===========================================================================

from src.database.models.graph_configuration import AgentTestCase  # noqa: E402
from src.services.agent_test_workbench import AgentTestWorkbench  # noqa: E402

_TEST_CASES_URL = "/api/admin/agent-definitions/test-cases"
_TEST_CASE_KEYS = {
    "id",
    "agent_key",
    "name",
    "version",
    "is_active",
    "is_required",
    "synthetic_payload",
    "assembly_context",
    "created_by",
    "created_at",
    "updated_by",
    "updated_at",
    "is_synthetic_data_warning",
}
_LAST_REQUIRED_MESSAGE = (
    "A role must keep at least one active required test case. "
    "Add its replacement before retiring this one."
)


def _test_case_url(test_case_id: int) -> str:
    return f"{_TEST_CASES_URL}/{test_case_id}"


def _seed_test_case_id(session_factory: sessionmaker, agent_key: str = "architect") -> int:
    with session_factory() as session:
        return session.scalar(
            select(AgentTestCase.id).where(
                AgentTestCase.agent_key == agent_key,
                AgentTestCase.name == f"{agent_key}_required_smoke_v1",
            )
        )


def _test_case_rows(session_factory: sessionmaker) -> list[tuple[object, ...]]:
    with session_factory() as session:
        return [
            tuple(row)
            for row in session.execute(
                select(
                    AgentTestCase.id,
                    AgentTestCase.agent_key,
                    AgentTestCase.name,
                    AgentTestCase.version,
                    AgentTestCase.is_active,
                    AgentTestCase.is_required,
                    AgentTestCase.synthetic_payload,
                    AgentTestCase.assembly_context,
                    AgentTestCase.created_by,
                    AgentTestCase.updated_by,
                    AgentTestCase.updated_at,
                ).order_by(AgentTestCase.id)
            )
        ]


def _create_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "agent_key": "architect",
        "name": "architect_extra",
        "synthetic_payload": {"message": "Synthetic smoke input."},
        "assembly_context": {"design_system_active": False},
        "is_required": False,
    }
    body.update(overrides)
    return body


def _update_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "synthetic_payload": {"message": "revised"},
        "assembly_context": {"design_system_active": True},
        "is_required": True,
    }
    body.update(overrides)
    return body


def _without_timestamps(body: dict[str, object]) -> dict[str, object]:
    assert set(body) == _TEST_CASE_KEYS
    assert isinstance(body["created_at"], str) and body["created_at"]
    assert isinstance(body["updated_at"], str) and body["updated_at"]
    return {key: value for key, value in body.items() if not key.endswith("_at")}


def _invalid_test_case(*issues: tuple[str, str, str]) -> dict[str, object]:
    return {
        "code": "invalid_test_case",
        "issues": [
            {"field": field, "code": code, "message": message}
            for field, code, message in issues
        ],
    }


_TEST_CASE_ROUTES = [
    ("POST", lambda _id: _TEST_CASES_URL),
    ("GET", lambda _id: _TEST_CASES_URL),
    ("PUT", _test_case_url),
    ("DELETE", _test_case_url),
]
_TEST_CASE_ROUTE_IDS = ["POST-list", "GET-list", "PUT-item", "DELETE-item"]
_TEST_CASE_WRITE_ROUTES = [route for route in _TEST_CASE_ROUTES if route[0] != "GET"]
_TEST_CASE_WRITE_ROUTE_IDS = [
    iid for route, iid in zip(_TEST_CASE_ROUTES, _TEST_CASE_ROUTE_IDS) if route[0] != "GET"
]


def _forbid_test_case_service(monkeypatch, calls: list[str]) -> None:
    def _must_not_reach(*_args, **_kwargs):
        calls.append("service")
        raise AssertionError("authorization reached the test-case service")

    for method in (
        "list_test_cases",
        "create_test_case",
        "update_test_case",
        "deactivate_test_case",
    ):
        monkeypatch.setattr(AgentTestWorkbench, method, _must_not_reach)


@pytest.mark.parametrize(("method", "url_for"), _TEST_CASE_ROUTES, ids=_TEST_CASE_ROUTE_IDS)
def test_test_case_routes_deny_non_admins_before_body_or_service(
    session_factory, monkeypatch, method, url_for
):
    """Catches a test-case route outside the admin router or parsing before auth (C23)."""
    _force_admin(monkeypatch, is_admin=False)
    calls: list[str] = []

    async def _must_not_parse_json(_request):
        calls.append("body")
        raise AssertionError("authorization parsed the raw request body")

    _forbid_test_case_service(monkeypatch, calls)
    monkeypatch.setattr(agent_definition_routes.Request, "json", _must_not_parse_json)
    seed_id = _seed_test_case_id(session_factory)
    before = _test_case_rows(session_factory)
    with _app_for(session_factory, raise_server_exceptions=False) as client:
        response = client.request(
            method,
            url_for(seed_id),
            content=b'{not json; "name": "SUPER_SECRET_CASE"}',
            headers={"content-type": "application/json"},
        )

    assert calls == []
    assert response.status_code == 403
    assert response.json() == {"detail": "Admin access required"}
    assert "SUPER_SECRET_CASE" not in response.text
    assert _test_case_rows(session_factory) == before


@pytest.mark.parametrize(
    ("method", "url_for"), _TEST_CASE_WRITE_ROUTES, ids=_TEST_CASE_WRITE_ROUTE_IDS
)
@pytest.mark.parametrize("principal", [None, " \t "])
def test_test_case_writes_require_a_trusted_principal_before_body_or_service(
    session_factory, monkeypatch, method, url_for, principal
):
    _force_admin(monkeypatch, is_admin=True)
    set_current_user(principal)
    calls: list[str] = []

    async def _must_not_parse_json(_request):
        calls.append("body")
        raise AssertionError("a missing principal parsed the body")

    _forbid_test_case_service(monkeypatch, calls)
    monkeypatch.setattr(agent_definition_routes.Request, "json", _must_not_parse_json)
    seed_id = _seed_test_case_id(session_factory)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[agent_definition_routes.require_admin] = lambda: None

    def _override_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.request(
            method,
            url_for(seed_id),
            content=b"{not json; should not be parsed}",
            headers={"content-type": "application/json"},
        )

    assert calls == []
    assert response.status_code == 403
    assert response.json() == {"detail": "Authenticated principal required"}


def test_post_test_case_returns_201_with_the_exact_snapshot(session_factory, monkeypatch):
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        response = client.post(_TEST_CASES_URL, json=_create_body(name="  architect_extra "))

    assert response.status_code == 201
    body = response.json()
    assert isinstance(body["id"], int)
    assert _without_timestamps(body) == {
        "id": body["id"],
        "agent_key": "architect",
        "name": "architect_extra",
        "version": 1,
        "is_active": True,
        "is_required": False,
        "synthetic_payload": {"message": "Synthetic smoke input."},
        "assembly_context": {"design_system_active": False},
        "created_by": "task4-user@example.com",
        "updated_by": "task4-user@example.com",
        "is_synthetic_data_warning": True,
    }


def test_post_test_case_projects_the_ordered_domain_rejection(session_factory, monkeypatch):
    _force_admin(monkeypatch, is_admin=True)
    before = _test_case_rows(session_factory)
    with _app_for(session_factory) as client:
        response = client.post(
            _TEST_CASES_URL,
            json=_create_body(name="  ", synthetic_payload={"k": "x" * 70_000}),
        )

    assert response.status_code == 422
    assert response.json() == _invalid_test_case(
        ("name", "blank", "Test case name must not be blank."),
        (
            "synthetic_payload",
            "too_large",
            "Synthetic payload must be at most 65536 bytes as JSON.",
        ),
    )
    assert _test_case_rows(session_factory) == before


@pytest.mark.parametrize("agent_key", ["unknown", "foreman"])
def test_post_test_case_rejects_an_unknown_or_deterministic_role(
    session_factory, monkeypatch, agent_key
):
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        response = client.post(_TEST_CASES_URL, json=_create_body(agent_key=agent_key))

    assert response.status_code == 422
    assert response.json() == _invalid_test_case(
        ("agent_key", "unknown_agent", "Agent key must identify an editable model role.")
    )


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            _create_body(sentinel="x"),
            [("sentinel", "extra_forbidden", "Extra inputs are not permitted")],
        ),
        (
            _create_body(is_active=False),
            [("is_active", "extra_forbidden", "Extra inputs are not permitted")],
        ),
        (
            _create_body(assembly_context={"design_system_active": False, "x": 1}),
            [("assembly_context.x", "extra_forbidden", "Extra inputs are not permitted")],
        ),
        (
            _create_body(is_required="yes"),
            [("is_required", "strict_type", "Input should be a valid boolean")],
        ),
        (
            {"agent_key": "architect"},
            [
                ("name", "strict_type", "Field required"),
                ("synthetic_payload", "strict_type", "Field required"),
                ("assembly_context", "strict_type", "Field required"),
                ("is_required", "strict_type", "Field required"),
            ],
        ),
    ],
    ids=["unknown-field", "is-active", "context-extra", "required-type", "missing"],
)
def test_post_test_case_accepts_only_the_strict_create_body(
    session_factory, monkeypatch, body, expected
):
    _force_admin(monkeypatch, is_admin=True)
    before = _test_case_rows(session_factory)
    with _app_for(session_factory) as client:
        response = client.post(_TEST_CASES_URL, json=body)

    assert response.status_code == 422
    assert response.json() == _invalid_test_case(*expected)
    assert _test_case_rows(session_factory) == before


@pytest.mark.parametrize(
    ("method", "url_for"), [("POST", lambda _id: _TEST_CASES_URL), ("PUT", _test_case_url)]
)
def test_test_case_body_routes_reject_malformed_json(
    session_factory, monkeypatch, method, url_for
):
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        response = client.request(
            method,
            url_for(_seed_test_case_id(session_factory)),
            content=b"{not json",
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 422
    assert response.json() == _invalid_test_case(
        ("$", "invalid_json", "Request body must be valid JSON.")
    )


def test_put_test_case_returns_the_new_version_and_retires_the_old(
    session_factory, monkeypatch
):
    _force_admin(monkeypatch, is_admin=True)
    seed_id = _seed_test_case_id(session_factory)
    with _app_for(session_factory) as client:
        response = client.put(_test_case_url(seed_id), json=_update_body())
        listed = client.get(
            _TEST_CASES_URL, params={"agent_key": "architect", "include_inactive": True}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] != seed_id
    assert _without_timestamps(body) == {
        "id": body["id"],
        "agent_key": "architect",
        "name": "architect_required_smoke_v1",
        "version": 2,
        "is_active": True,
        "is_required": True,
        "synthetic_payload": {"message": "revised"},
        "assembly_context": {"design_system_active": True},
        "created_by": "task4-user@example.com",
        "updated_by": "task4-user@example.com",
        "is_synthetic_data_warning": True,
    }
    assert listed.status_code == 200
    assert [
        (item["id"], item["version"], item["is_active"]) for item in listed.json()["items"]
    ] == [(seed_id, 1, False), (body["id"], 2, True)]


def test_put_test_case_rename_and_last_required_are_one_ordered_422(
    session_factory, monkeypatch
):
    """Catches a rename or an un-require of the last required case slipping through (C9, C22)."""
    _force_admin(monkeypatch, is_admin=True)
    seed_id = _seed_test_case_id(session_factory)
    before = _test_case_rows(session_factory)
    with _app_for(session_factory) as client:
        response = client.put(
            _test_case_url(seed_id), json=_update_body(name="renamed", is_required=False)
        )

    assert response.status_code == 422
    assert response.json() == _invalid_test_case(
        ("name", "name_immutable", "A test case name cannot be changed."),
        ("is_required", "last_required_case", _LAST_REQUIRED_MESSAGE),
    )
    assert _test_case_rows(session_factory) == before


def test_put_test_case_unrequiring_the_last_required_case_is_the_exact_422(
    session_factory, monkeypatch
):
    _force_admin(monkeypatch, is_admin=True)
    seed_id = _seed_test_case_id(session_factory)
    before = _test_case_rows(session_factory)
    with _app_for(session_factory) as client:
        response = client.put(_test_case_url(seed_id), json=_update_body(is_required=False))

    assert response.status_code == 422
    assert response.json() == _invalid_test_case(
        ("is_required", "last_required_case", _LAST_REQUIRED_MESSAGE)
    )
    assert _test_case_rows(session_factory) == before
    assert GraphConfiguration().bootstrap_v1(session_factory).created is False


def test_put_test_case_on_a_superseded_version_is_409_stale(session_factory, monkeypatch):
    _force_admin(monkeypatch, is_admin=True)
    seed_id = _seed_test_case_id(session_factory)
    with _app_for(session_factory) as client:
        assert client.put(_test_case_url(seed_id), json=_update_body()).status_code == 200
        before = _test_case_rows(session_factory)
        response = client.put(_test_case_url(seed_id), json=_update_body())

    assert response.status_code == 409
    assert response.json() == {
        "code": "stale_test_case",
        "test_case_id": seed_id,
        "message": "This test case version is no longer active. Reload and retry.",
    }
    assert _test_case_rows(session_factory) == before


def test_put_test_case_rejects_an_unknown_field_before_the_service(
    session_factory, monkeypatch
):
    _force_admin(monkeypatch, is_admin=True)
    calls: list[str] = []
    _forbid_test_case_service(monkeypatch, calls)
    with _app_for(session_factory) as client:
        response = client.put(
            _test_case_url(_seed_test_case_id(session_factory)),
            json=_update_body(agent_key="builder"),
        )

    assert calls == []
    assert response.status_code == 422
    assert response.json() == _invalid_test_case(
        ("agent_key", "extra_forbidden", "Extra inputs are not permitted")
    )


@pytest.mark.parametrize(
    ("method", "body"), [("PUT", _update_body()), ("DELETE", None)]
)
def test_test_case_writes_on_an_unknown_id_are_404(session_factory, monkeypatch, method, body):
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        response = client.request(method, _test_case_url(999_999), json=body)

    assert response.status_code == 404
    assert response.json() == {"detail": "Test case not found"}


def test_delete_test_case_deactivates_and_returns_the_snapshot(session_factory, monkeypatch):
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        created = client.post(_TEST_CASES_URL, json=_create_body()).json()
        response = client.delete(_test_case_url(created["id"]))
        again = client.delete(_test_case_url(created["id"]))

    assert response.status_code == 200
    expected = {**_without_timestamps(created), "is_active": False}
    assert _without_timestamps(response.json()) == expected
    assert again.status_code == 200
    assert again.json() == response.json()
    with session_factory() as session:
        assert session.get(AgentTestCase, created["id"]) is not None


def test_delete_test_case_of_the_last_required_case_is_the_exact_422(
    session_factory, monkeypatch
):
    """Catches the one admin click that makes the next boot exit (C9)."""
    _force_admin(monkeypatch, is_admin=True)
    seed_id = _seed_test_case_id(session_factory, "deck_reviewer")
    before = _test_case_rows(session_factory)
    with _app_for(session_factory) as client:
        response = client.delete(_test_case_url(seed_id))

    assert response.status_code == 422
    assert response.json() == _invalid_test_case(
        ("is_active", "last_required_case", _LAST_REQUIRED_MESSAGE)
    )
    assert _test_case_rows(session_factory) == before
    assert GraphConfiguration().bootstrap_v1(session_factory).created is False


def test_get_test_cases_lists_active_versions_with_the_exact_item_shape(
    session_factory, monkeypatch
):
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        response = client.get(_TEST_CASES_URL)
        builder_only = client.get(_TEST_CASES_URL, params={"agent_key": "builder"})

    assert response.status_code == 200
    assert set(response.json()) == {"items"}
    items = response.json()["items"]
    assert [item["agent_key"] for item in items] == list(
        ("architect", "data_analyst", "builder", "build_reviewer", "fixer", "fix_reviewer",
         "deck_reviewer")
    )
    assert all(_without_timestamps(item)["is_synthetic_data_warning"] is True for item in items)
    assert [item["name"] for item in builder_only.json()["items"]] == [
        "builder_required_smoke_v1"
    ]


@pytest.mark.parametrize("agent_key", ["unknown", "foreman"])
def test_get_test_cases_rejects_an_unknown_role_filter(session_factory, monkeypatch, agent_key):
    _force_admin(monkeypatch, is_admin=True)
    with _app_for(session_factory) as client:
        response = client.get(_TEST_CASES_URL, params={"agent_key": agent_key})

    assert response.status_code == 422
    assert response.json() == _invalid_test_case(
        ("agent_key", "unknown_agent", "Agent key must identify an editable model role.")
    )


@pytest.mark.parametrize(
    ("method", "url_for", "body", "service_method"),
    [
        ("POST", lambda _id: _TEST_CASES_URL, _create_body(), "create_test_case"),
        ("PUT", _test_case_url, _update_body(), "update_test_case"),
        ("DELETE", _test_case_url, None, "deactivate_test_case"),
        ("GET", lambda _id: _TEST_CASES_URL, None, "list_test_cases"),
    ],
    ids=["POST", "PUT", "DELETE", "GET"],
)
def test_test_case_routes_run_the_locking_writer_off_the_event_loop(
    session_factory, monkeypatch, method, url_for, body, service_method
):
    """Catches a case write that can wait on the L2 row lock on the event loop."""
    import asyncio

    _force_admin(monkeypatch, is_admin=True)
    loop_running: list[bool] = []
    original = getattr(AgentTestWorkbench, service_method)

    def _observing(self, *args, **kwargs):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            loop_running.append(False)
        else:
            loop_running.append(True)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(AgentTestWorkbench, service_method, _observing)
    with _app_for(session_factory) as client:
        if method == "DELETE":
            created = client.post(_TEST_CASES_URL, json=_create_body(name="to_retire"))
            target = created.json()["id"]
        else:
            target = _seed_test_case_id(session_factory)
        loop_running.clear()
        response = client.request(method, url_for(target), json=body)

    assert response.status_code in {200, 201}
    assert loop_running == [False]


def test_put_identical_content_to_a_superseded_version_is_409_stale(
    session_factory, monkeypatch
):
    """Catches an identical PUT to a superseded id returning 200 (fix round 2)."""
    _force_admin(monkeypatch, is_admin=True)
    seed_id = _seed_test_case_id(session_factory)
    with _app_for(session_factory) as client:
        listed = client.get(_TEST_CASES_URL, params={"agent_key": "architect"}).json()
        seed = next(item for item in listed["items"] if item["id"] == seed_id)
        identical = {
            "name": seed["name"],
            "synthetic_payload": seed["synthetic_payload"],
            "assembly_context": seed["assembly_context"],
            "is_required": seed["is_required"],
        }
        assert client.put(_test_case_url(seed_id), json=_update_body()).status_code == 200
        before = _test_case_rows(session_factory)
        response = client.put(_test_case_url(seed_id), json=identical)

    assert response.status_code == 409
    assert response.json() == {
        "code": "stale_test_case",
        "test_case_id": seed_id,
        "message": "This test case version is no longer active. Reload and retry.",
    }
    assert _test_case_rows(session_factory) == before


# ===========================================================================
# #267 Task 5: test-run execute and read routes on the one admin router
# (C16, C23, C32, C36, C38)
# ===========================================================================

import asyncio  # noqa: E402
import dataclasses  # noqa: E402

from sqlalchemy.exc import OperationalError  # noqa: E402

import src.services.agent_test_workbench as test_workbench_module  # noqa: E402
from src.database.models.graph_configuration import AgentTestRun  # noqa: E402
from src.services.agent_model_payload import model_payload_for  # noqa: E402
from src.services.agent_runtime import AgentRuntime  # noqa: E402
from src.services.agent_runtime_identity import (  # noqa: E402
    RecordingAgentInvocationIdentitySink,
)
from src.services.agent_test_workbench import TestRunUnavailable  # noqa: E402
from src.services.graph_configuration_seed import REQUIRED_SMOKE_PAYLOADS  # noqa: E402
from src.services.graph_definition_manifest import (  # noqa: E402
    GRAPH_V1_AGENT_KEYS as _GRAPH_V1_AGENT_KEYS,
)
from src.services.persisted_graph_release import (  # noqa: E402
    PersistedGraphReleaseLoader,
)
from tests.fixtures.deterministic_model_adapter import (  # noqa: E402
    DeterministicFakeModelAdapter,
    fake_output,
)

_TEST_RUN_PREFIX = "/api/admin/agent-definitions"
_TEST_RUN_KEYS = {
    "run_id",
    "run_kind",
    "test_case_id",
    "test_case_version",
    "agent_key",
    "candidate_hash",
    "compared_release_id",
    "compared_definition_revision_id",
    "synthetic_payload",
    "model_payload",
    "assembled_prompt",
    "execution_status",
    "error_detail",
    "deterministic_checks_passed",
    "deterministic_check_results",
    "candidate_raw_output",
    "candidate_structured_output",
    "baseline_raw_output",
    "baseline_structured_output",
    "latency_ms",
    "input_tokens",
    "output_tokens",
    "run_by",
    "run_at",
    "verdict",
    "verdict_reviewer",
    "verdict_at",
    "verdict_notes",
    "candidate_is_current",
    "base_release_is_current",
}
_ROW_COLUMNS = (
    "test_case_id",
    "test_case_version",
    "agent_key",
    "run_kind",
    "candidate_hash",
    "compared_release_id",
    "compared_definition_revision_id",
    "model_payload",
    "assembled_prompt",
    "execution_status",
    "error_detail",
    "deterministic_checks_passed",
    "deterministic_check_results",
    "candidate_raw_output",
    "candidate_structured_output",
    "baseline_raw_output",
    "baseline_structured_output",
    "latency_ms",
    "input_tokens",
    "output_tokens",
    "run_by",
)
_ROUTE_ACTOR = "task4-user@example.com"  # what ``_force_admin`` authenticates
_SEEDED_SESSION_IDENTIFIERS = (
    "synthetic-architect",
    "synthetic-data-analyst",
    "synthetic-builder",
    "synthetic-turn",
    "system:bootstrap",
    "synthetic-deck-reviewer",
)
_TEST_RUN_UNAVAILABLE = {
    "code": "test_run_unavailable",
    "message": "Test run storage is temporarily unavailable. Retry the request.",
    "retryable": True,
}
_INT32_MAX = 2**31 - 1


def _candidate_run_url(agent_key: str = "architect") -> str:
    return f"{_TEST_RUN_PREFIX}/draft/{agent_key}/test-runs"


def _baseline_run_url(agent_key: str = "architect") -> str:
    return f"{_TEST_RUN_PREFIX}/published/{agent_key}/test-runs"


def _run_url(run_id: int) -> str:
    return f"{_TEST_RUN_PREFIX}/test-runs/{run_id}"


def _case_runs_url(test_case_id: int) -> str:
    return f"{_TEST_RUN_PREFIX}/test-cases/{test_case_id}/runs"


def _draft_lock_version(session_factory: sessionmaker) -> int:
    with session_factory() as session:
        return session.scalar(select(GraphDraft.lock_version))


def _candidate_body(session_factory, agent_key="architect", **overrides) -> dict[str, object]:
    body: dict[str, object] = {
        "test_case_id": _seed_test_case_id(session_factory, agent_key),
        "lock_version": _draft_lock_version(session_factory),
    }
    body.update(overrides)
    return body


def _baseline_body(session_factory, agent_key="architect", **overrides) -> dict[str, object]:
    body: dict[str, object] = {"test_case_id": _seed_test_case_id(session_factory, agent_key)}
    body.update(overrides)
    return body


def _test_run_rows(session_factory: sessionmaker) -> list[AgentTestRun]:
    with session_factory() as session:
        return list(session.scalars(select(AgentTestRun).order_by(AgentTestRun.id)))


def _test_workbench(session_factory, adapter) -> AgentTestWorkbench:
    return AgentTestWorkbench(
        runtime=AgentRuntime(
            persisted_release_loader=PersistedGraphReleaseLoader(
                session_factory=session_factory
            ),
            model_adapter=adapter,
            identity_sink=RecordingAgentInvocationIdentitySink(),
        )
    )


def _run_app(
    session_factory: sessionmaker,
    adapter: object | None = None,
    *,
    raise_server_exceptions: bool = True,
) -> TestClient:
    """The admin router with the executor on a fake model adapter (never Databricks)."""
    adapter = adapter if adapter is not None else DeterministicFakeModelAdapter()
    client = _app_for(session_factory, raise_server_exceptions=raise_server_exceptions)
    workbench = _test_workbench(session_factory, adapter)
    client.app.dependency_overrides[agent_definition_routes.get_agent_test_workbench] = (
        lambda: workbench
    )
    return client


def _identity_row(session_factory: sessionmaker, agent_key: str = "architect") -> dict:
    with session_factory() as session:
        release_id = session.scalar(
            select(GraphRelease.id).where(GraphRelease.effective_to.is_(None))
        )
        revision_id = session.scalar(
            select(GraphReleaseAgent.agent_definition_revision_id).where(
                GraphReleaseAgent.graph_release_id == release_id,
                GraphReleaseAgent.agent_key == agent_key,
            )
        )
        revision_hash = session.scalar(
            select(AgentDefinitionRevision.content_hash).where(
                AgentDefinitionRevision.id == revision_id
            )
        )
        draft = session.scalar(
            select(GraphDraftAgent).where(GraphDraftAgent.agent_key == agent_key)
        )
        return {
            "release_id": release_id,
            "revision_id": revision_id,
            "revision_hash": revision_hash,
            "draft_hash": draft.candidate_hash,
            "endpoint_name": definition_content_from_row(draft).model.endpoint_name,
        }


def _assert_body_is_the_row(body: dict[str, object], row: AgentTestRun) -> None:
    """The response serializes the immutable evidence row, and nothing else."""
    assert set(body) == _TEST_RUN_KEYS
    for column in _ROW_COLUMNS:
        assert body[column] == getattr(row, column), column
    assert body["run_id"] == row.id
    assert isinstance(body["run_at"], str) and body["run_at"]
    for column in ("verdict", "verdict_reviewer", "verdict_notes"):
        assert body[column] == getattr(row, column), column
    assert (body["verdict_at"] is None) == (row.verdict_at is None)


def _integers_in(document: object) -> list[int]:
    if isinstance(document, bool):
        return []
    if isinstance(document, int):
        return [document]
    if isinstance(document, dict):
        return [value for item in document.values() for value in _integers_in(item)]
    if isinstance(document, list):
        return [value for item in document for value in _integers_in(item)]
    return []


_TEST_RUN_ROUTES = [
    ("POST", lambda case_id, run_id: _candidate_run_url()),
    ("POST", lambda case_id, run_id: _baseline_run_url()),
    ("GET", lambda case_id, run_id: _run_url(run_id)),
    ("GET", lambda case_id, run_id: _case_runs_url(case_id)),
]
_TEST_RUN_ROUTE_IDS = ["candidate", "baseline", "get_run", "list_runs"]
_TEST_RUN_SERVICE_METHODS = (
    "execute_candidate_run",
    "execute_baseline_rerun",
    "get_test_run",
    "list_test_runs",
)


def _forbid_test_run_service(monkeypatch, calls: list[str]) -> None:
    def _must_not_reach(*_args, **_kwargs):
        calls.append("service")
        raise AssertionError("authorization reached the test-run service")

    for method in _TEST_RUN_SERVICE_METHODS:
        monkeypatch.setattr(AgentTestWorkbench, method, _must_not_reach)


@pytest.mark.parametrize(("method", "url_for"), _TEST_RUN_ROUTES, ids=_TEST_RUN_ROUTE_IDS)
def test_test_run_routes_deny_non_admins_before_body_or_service(
    session_factory, monkeypatch, method, url_for
):
    """Catches a test-run route outside the admin router or parsing before auth (C23)."""
    _force_admin(monkeypatch, is_admin=False)
    calls: list[str] = []

    async def _must_not_parse_json(_request):
        calls.append("body")
        raise AssertionError("authorization parsed the raw request body")

    _forbid_test_run_service(monkeypatch, calls)
    monkeypatch.setattr(agent_definition_routes.Request, "json", _must_not_parse_json)
    adapter = DeterministicFakeModelAdapter()
    seed_id = _seed_test_case_id(session_factory)
    before = _all_table_rows(session_factory)
    with _run_app(session_factory, adapter, raise_server_exceptions=False) as client:
        response = client.request(
            method,
            url_for(seed_id, 1),
            content=b'{not json; "test_case_id": "SUPER_SECRET_RUN"}',
            headers={"content-type": "application/json"},
        )

    assert calls == []
    assert adapter.calls == []
    assert response.status_code == 403
    assert response.json() == {"detail": "Admin access required"}
    assert "SUPER_SECRET_RUN" not in response.text
    assert _all_table_rows(session_factory) == before


@pytest.mark.parametrize(
    ("method", "url_for"), _TEST_RUN_ROUTES[:2], ids=_TEST_RUN_ROUTE_IDS[:2]
)
@pytest.mark.parametrize("principal", [None, " \t "])
def test_test_run_executes_require_a_trusted_principal_before_body_or_service(
    session_factory, monkeypatch, method, url_for, principal
):
    """Catches a run that reaches the model with no audit actor for ``run_by``."""
    _force_admin(monkeypatch, is_admin=True)
    set_current_user(principal)
    calls: list[str] = []

    async def _must_not_parse_json(_request):
        calls.append("body")
        raise AssertionError("a missing principal parsed the body")

    _forbid_test_run_service(monkeypatch, calls)
    monkeypatch.setattr(agent_definition_routes.Request, "json", _must_not_parse_json)
    adapter = DeterministicFakeModelAdapter()
    with _run_app(session_factory, adapter, raise_server_exceptions=False) as client:
        client.app.dependency_overrides[agent_definition_routes.require_admin] = lambda: None
        response = client.request(
            method,
            url_for(1, 1),
            content=b"{not json; should not be parsed}",
            headers={"content-type": "application/json"},
        )

    assert calls == []
    assert adapter.calls == []
    assert response.status_code == 403
    assert response.json() == {"detail": "Authenticated principal required"}


def test_candidate_run_returns_201_with_the_exact_evidence_row(session_factory, monkeypatch):
    """Catches a route that reshapes, drops or invents evidence, or invents a verdict."""
    _force_admin(monkeypatch, is_admin=True)
    adapter = DeterministicFakeModelAdapter()
    identity = _identity_row(session_factory)
    case_id = _seed_test_case_id(session_factory)
    with _run_app(session_factory, adapter) as client:
        response = client.post(_candidate_run_url(), json=_candidate_body(session_factory))

    assert response.status_code == 201
    body = response.json()
    rows = _test_run_rows(session_factory)
    assert len(rows) == 1
    _assert_body_is_the_row(body, rows[0])
    # #268 C16: the four verdict keys are always present, and null until a verdict.
    for verdict_field in ("verdict", "verdict_reviewer", "verdict_at", "verdict_notes"):
        assert verdict_field in body
        assert body[verdict_field] is None
    assert body["run_kind"] == "candidate"
    assert (body["test_case_id"], body["test_case_version"]) == (case_id, 1)
    assert body["agent_key"] == "architect"
    assert body["candidate_hash"] == identity["draft_hash"]
    assert body["compared_release_id"] == identity["release_id"]
    assert body["compared_definition_revision_id"] == identity["revision_id"]
    assert body["synthetic_payload"] == REQUIRED_SMOKE_PAYLOADS["architect"]
    assert body["model_payload"] == model_payload_for(
        "architect", REQUIRED_SMOKE_PAYLOADS["architect"]
    )
    assert body["assembled_prompt"] == adapter.calls[0].prompt
    assert body["execution_status"] == "completed"
    assert body["error_detail"] is None
    assert body["deterministic_checks_passed"] is True
    assert body["deterministic_check_results"] == [
        {"name": "output_contract", "passed": True, "message": None, "issues": []}
    ]
    assert body["candidate_raw_output"] == fake_output("architect")
    assert body["candidate_structured_output"]["message"] == "an answer"
    assert (body["baseline_raw_output"], body["baseline_structured_output"]) == (None, None)
    assert (body["input_tokens"], body["output_tokens"]) == (None, None)
    assert body["run_by"] == _ROUTE_ACTOR
    assert (body["candidate_is_current"], body["base_release_is_current"]) == (True, True)


def test_baseline_rerun_returns_201_with_published_identity(session_factory, monkeypatch):
    """Catches the baseline route running the draft, or recording the draft's identity."""
    _force_admin(monkeypatch, is_admin=True)
    adapter = DeterministicFakeModelAdapter()
    identity = _identity_row(session_factory)
    with _run_app(session_factory, adapter) as client:
        response = client.post(_baseline_run_url(), json=_baseline_body(session_factory))

    assert response.status_code == 201
    body = response.json()
    rows = _test_run_rows(session_factory)
    assert len(rows) == 1
    _assert_body_is_the_row(body, rows[0])
    assert body["run_kind"] == "published_baseline"
    assert body["candidate_hash"] == identity["revision_hash"]
    assert body["compared_release_id"] == identity["release_id"]
    assert body["compared_definition_revision_id"] == identity["revision_id"]
    assert body["execution_status"] == "completed"
    assert body["assembled_prompt"] == adapter.calls[0].prompt
    assert (body["baseline_raw_output"], body["baseline_structured_output"]) == (None, None)
    assert (body["candidate_is_current"], body["base_release_is_current"]) == (True, True)


def test_a_candidate_run_after_a_baseline_carries_the_stored_baseline(
    session_factory, monkeypatch
):
    """Catches the Compare view's baseline columns not reaching the response."""
    _force_admin(monkeypatch, is_admin=True)
    with _run_app(session_factory) as client:
        baseline = client.post(_baseline_run_url(), json=_baseline_body(session_factory))
        candidate = client.post(_candidate_run_url(), json=_candidate_body(session_factory))

    assert (baseline.status_code, candidate.status_code) == (201, 201)
    body = candidate.json()
    assert body["baseline_raw_output"] == baseline.json()["candidate_raw_output"]
    assert body["baseline_structured_output"] == baseline.json()["candidate_structured_output"]
    assert body["baseline_raw_output"] is not None


@pytest.mark.parametrize("route", ["candidate", "baseline"])
def test_a_model_failure_is_201_evidence_with_a_code_and_no_provider_text(
    session_factory, monkeypatch, route
):
    """Catches a provider failure mapped to an HTTP error, or its text in the body (C33)."""
    _force_admin(monkeypatch, is_admin=True)
    identity = _identity_row(session_factory)
    adapter = DeterministicFakeModelAdapter(mode="provider_unavailable")
    with _run_app(session_factory, adapter) as client:
        if route == "candidate":
            response = client.post(
                _candidate_run_url(), json=_candidate_body(session_factory)
            )
        else:
            response = client.post(_baseline_run_url(), json=_baseline_body(session_factory))

    assert response.status_code == 201
    body = response.json()
    assert body["execution_status"] == "model_error"
    assert body["error_detail"] == f"endpoint_unavailable:{identity['endpoint_name']}"
    assert body["deterministic_checks_passed"] is False
    assert body["deterministic_check_results"] == [
        {
            "name": "execution",
            "passed": False,
            "message": "The run produced no model output to check.",
            "issues": [],
        }
    ]
    assert "pinned model provider unavailable" not in response.text
    assert "Traceback" not in response.text
    _assert_body_is_the_row(body, _test_run_rows(session_factory)[0])


def test_an_incomplete_run_serializes_its_check_issues(session_factory, monkeypatch):
    """Catches the Checks view losing the issue list of a failed output contract."""
    _force_admin(monkeypatch, is_admin=True)
    adapter = DeterministicFakeModelAdapter(mode="invalid_optional_field")
    with _run_app(session_factory, adapter) as client:
        response = client.post(_candidate_run_url(), json=_candidate_body(session_factory))

    assert response.status_code == 201
    body = response.json()
    assert body["execution_status"] == "incomplete"
    [check] = body["deterministic_check_results"]
    assert check["name"] == "output_contract"
    assert check["passed"] is False
    assert check["issues"] and set(check["issues"][0]) == {"code", "field"}
    assert body["candidate_structured_output"] is None
    assert body["candidate_raw_output"] is not None
    _assert_body_is_the_row(body, _test_run_rows(session_factory)[0])


def test_a_run_body_carries_no_sentinel_session_or_extra_user_identifier(
    session_factory, monkeypatch
):
    """Catches a ``-1`` sentinel, a seeded session id, or the actor leaking (M-1, P6)."""
    _force_admin(monkeypatch, is_admin=True)
    with _run_app(session_factory) as client:
        for agent_key in ("architect", "data_analyst", "builder", "deck_reviewer"):
            response = client.post(
                _candidate_run_url(agent_key),
                json=_candidate_body(session_factory, agent_key),
            )
            assert response.status_code == 201
            body = response.json()
            assert all(value >= 0 for value in _integers_in(body)), body
            # Prompt and output text may legitimately say "-1"; identity may not.
            identity = {
                key: body[key]
                for key in (
                    "run_id",
                    "test_case_id",
                    "test_case_version",
                    "compared_release_id",
                    "compared_definition_revision_id",
                    "error_detail",
                    "candidate_hash",
                )
            }
            assert "-1" not in json.dumps(identity)
            sent = json.dumps([body["model_payload"], body["assembled_prompt"]])
            for identifier in _SEEDED_SESSION_IDENTIFIERS:
                assert identifier not in sent, (agent_key, identifier)
            without_actor = {key: value for key, value in body.items() if key != "run_by"}
            assert _ROUTE_ACTOR not in json.dumps(without_actor)


def test_a_sentinel_identity_never_serializes(session_factory, monkeypatch):
    """Catches a response schema that would pass a ``-1`` revision id to the client."""
    _force_admin(monkeypatch, is_admin=True)
    with _run_app(session_factory, raise_server_exceptions=False) as client:
        real = client.post(_candidate_run_url(), json=_candidate_body(session_factory))
        evidence = AgentTestWorkbench().get_test_run(
            session_factory(), run_id=real.json()["run_id"]
        )
        forged = dataclasses.replace(
            evidence, compared_release_id=-1, compared_definition_revision_id=-1
        )
        monkeypatch.setattr(
            AgentTestWorkbench, "get_test_run", lambda self, session, *, run_id: forged
        )
        response = client.get(_run_url(real.json()["run_id"]))

    assert response.status_code == 500
    assert "-1" not in response.text


def test_get_test_run_returns_the_stored_evidence_with_null_currency(
    session_factory, monkeypatch
):
    """Catches a read that recomputes or fabricates the write-time currency flags."""
    _force_admin(monkeypatch, is_admin=True)
    with _run_app(session_factory) as client:
        created = client.post(_candidate_run_url(), json=_candidate_body(session_factory))
        response = client.get(_run_url(created.json()["run_id"]))

    assert response.status_code == 200
    expected = dict(created.json())
    expected.update(candidate_is_current=None, base_release_is_current=None)
    assert response.json() == expected


@pytest.mark.parametrize("run_id", [424242, 0, -3, _INT32_MAX + 1, 2**63])
def test_get_test_run_of_an_unknown_or_unstorable_id_is_404(
    session_factory, monkeypatch, run_id
):
    """Catches an unknown or out-of-range id reaching the database as a 500."""
    _force_admin(monkeypatch, is_admin=True)
    with _run_app(session_factory) as client:
        response = client.get(_run_url(run_id))

    assert response.status_code == 404
    assert response.json() == {"detail": "Test run not found"}


def test_list_case_runs_returns_newest_first_bounded_by_limit(session_factory, monkeypatch):
    """Catches a history list in the wrong order, unbounded, or leaking another case."""
    _force_admin(monkeypatch, is_admin=True)
    case_id = _seed_test_case_id(session_factory)
    with _run_app(session_factory) as client:
        first = client.post(_candidate_run_url(), json=_candidate_body(session_factory))
        second = client.post(_baseline_run_url(), json=_baseline_body(session_factory))
        third = client.post(_candidate_run_url(), json=_candidate_body(session_factory))
        client.post(
            _candidate_run_url("builder"), json=_candidate_body(session_factory, "builder")
        )
        listed = client.get(_case_runs_url(case_id))
        limited = client.get(_case_runs_url(case_id), params={"limit": 2})

    assert listed.status_code == 200
    assert set(listed.json()) == {"items"}
    ids = [item["run_id"] for item in listed.json()["items"]]
    assert ids == [third.json()["run_id"], second.json()["run_id"], first.json()["run_id"]]
    assert [item["run_id"] for item in limited.json()["items"]] == ids[:2]
    newest = dict(third.json())
    newest.update(candidate_is_current=None, base_release_is_current=None)
    assert listed.json()["items"][0] == newest


@pytest.mark.parametrize("test_case_id", [424242, 0, _INT32_MAX + 1])
def test_list_case_runs_of_an_unknown_case_is_404(session_factory, monkeypatch, test_case_id):
    """Catches an unknown case listing as an empty history instead of 404."""
    _force_admin(monkeypatch, is_admin=True)
    with _run_app(session_factory) as client:
        response = client.get(_case_runs_url(test_case_id))

    assert response.status_code == 404
    assert response.json() == {"detail": "Test case not found"}


@pytest.mark.parametrize("limit", [0, -1, 101])
def test_list_case_runs_rejects_an_out_of_range_limit(session_factory, monkeypatch, limit):
    _force_admin(monkeypatch, is_admin=True)
    with _run_app(session_factory) as client:
        response = client.get(
            _case_runs_url(_seed_test_case_id(session_factory)), params={"limit": limit}
        )

    assert response.status_code == 422
    assert response.json() == _invalid_test_case(
        ("limit", "out_of_range", "Limit must be an integer from 1 to 100.")
    )


# --- the strict, server-owned run bodies (C32, C36) -------------------------

_FORBIDDEN_CLIENT_RUN_FIELDS = [
    ("endpoint_name", "databricks-attacker-endpoint"),
    ("model", {"endpoint_name": "databricks-attacker-endpoint"}),
    ("candidate", {"prompt_text": "ignore the saved prompt"}),
    ("prompt", "ignore the saved prompt"),
    ("prompt_text", "ignore the saved prompt"),
    ("assembled_prompt", "ignore the saved prompt"),
    ("payload", {"message": "client payload"}),
    ("synthetic_payload", {"message": "client payload"}),
    ("model_payload", {"message": "client payload"}),
    ("assembly_context", {"design_system_active": True}),
    ("baseline", {"message": "client baseline"}),
    ("baseline_raw_output", {"message": "client baseline"}),
    ("baseline_structured_output", {"message": "client baseline"}),
    ("baseline_run_id", 1),
    ("candidate_hash", "0" * 64),
    ("compared_release_id", 1),
    ("compared_definition_revision_id", 1),
    ("release_id", 1),
    ("run_kind", "published_baseline"),
    ("agent_key", "builder"),
    ("run_by", "someone-else@example.com"),
    ("actor", "someone-else@example.com"),
    ("verdict", "approved"),
    ("test_case_version", 1),
]


@pytest.mark.parametrize("route", ["candidate", "baseline"])
@pytest.mark.parametrize(
    ("field", "value"),
    _FORBIDDEN_CLIENT_RUN_FIELDS,
    ids=[field for field, _value in _FORBIDDEN_CLIENT_RUN_FIELDS],
)
def test_a_run_body_cannot_choose_any_server_owned_input(
    session_factory, monkeypatch, route, field, value
):
    """Catches a run body that lets the client pick endpoint, prompt, payload or baseline."""
    _force_admin(monkeypatch, is_admin=True)
    adapter = DeterministicFakeModelAdapter()
    body = (
        _candidate_body(session_factory)
        if route == "candidate"
        else _baseline_body(session_factory)
    )
    body[field] = value
    url = _candidate_run_url() if route == "candidate" else _baseline_run_url()
    with _run_app(session_factory, adapter) as client:
        response = client.post(url, json=body)

    assert response.status_code == 422
    assert response.json() == {
        "code": "invalid_draft",
        "errors": [
            {"field": field, "code": "extra_forbidden", "message": "Extra inputs are not permitted"}
        ],
    }
    assert adapter.calls == []
    assert _test_run_rows(session_factory) == []


def test_a_baseline_body_does_not_accept_a_lock_version(session_factory, monkeypatch):
    """Catches the baseline route reading, or pretending to pin, the draft (C32)."""
    _force_admin(monkeypatch, is_admin=True)
    adapter = DeterministicFakeModelAdapter()
    with _run_app(session_factory, adapter) as client:
        response = client.post(
            _baseline_run_url(), json=_baseline_body(session_factory, lock_version=0)
        )

    assert response.status_code == 422
    assert response.json()["errors"] == [
        {
            "field": "lock_version",
            "code": "extra_forbidden",
            "message": "Extra inputs are not permitted",
        }
    ]
    assert adapter.calls == []


@pytest.mark.parametrize(
    ("overrides", "missing", "expected"),
    [
        ({"test_case_id": "1"}, (), [("test_case_id", "strict_type")]),
        ({"test_case_id": True}, (), [("test_case_id", "strict_type")]),
        ({"test_case_id": 1.0}, (), [("test_case_id", "strict_type")]),
        ({"test_case_id": 0}, (), [("test_case_id", "out_of_range")]),
        ({"test_case_id": _INT32_MAX + 1}, (), [("test_case_id", "out_of_range")]),
        ({"lock_version": -1}, (), [("lock_version", "out_of_range")]),
        ({"lock_version": "0"}, (), [("lock_version", "strict_type")]),
        ({}, ("test_case_id",), [("test_case_id", "strict_type")]),
        ({}, ("lock_version",), [("lock_version", "strict_type")]),
    ],
    ids=[
        "id-string",
        "id-bool",
        "id-float",
        "id-zero",
        "id-over-int32",
        "lock-negative",
        "lock-string",
        "id-missing",
        "lock-missing",
    ],
)
def test_a_candidate_body_is_strictly_typed(
    session_factory, monkeypatch, overrides, missing, expected
):
    """Catches a coerced id or lock reaching the executor or the database."""
    _force_admin(monkeypatch, is_admin=True)
    adapter = DeterministicFakeModelAdapter()
    body = _candidate_body(session_factory, **overrides)
    for field in missing:
        del body[field]
    with _run_app(session_factory, adapter) as client:
        response = client.post(_candidate_run_url(), json=body)

    assert response.status_code == 422
    payload = response.json()
    assert payload["code"] == "invalid_draft"
    assert [(error["field"], error["code"]) for error in payload["errors"]] == expected
    assert adapter.calls == []
    assert _test_run_rows(session_factory) == []


@pytest.mark.parametrize("route", ["candidate", "baseline"])
def test_a_run_body_must_be_valid_json_and_a_json_object(session_factory, monkeypatch, route):
    _force_admin(monkeypatch, is_admin=True)
    adapter = DeterministicFakeModelAdapter()
    url = _candidate_run_url() if route == "candidate" else _baseline_run_url()
    with _run_app(session_factory, adapter) as client:
        malformed = client.post(
            url, content=b"{not json", headers={"content-type": "application/json"}
        )
        not_an_object = client.post(url, json=[1, 2])

    assert malformed.status_code == 422
    assert malformed.json() == {
        "code": "invalid_draft",
        "errors": [
            {"field": "$", "code": "invalid_json", "message": "Request body must be valid JSON."}
        ],
    }
    assert not_an_object.status_code == 422
    assert not_an_object.json()["code"] == "invalid_draft"
    assert adapter.calls == []


@pytest.mark.parametrize("route", ["candidate", "baseline"])
@pytest.mark.parametrize("agent_key", ["foreman", "nope"])
def test_a_run_of_an_unknown_or_deterministic_role_is_the_unknown_agent_422(
    session_factory, monkeypatch, route, agent_key
):
    """Catches a run of a role with no Agent Definition reaching the service."""
    _force_admin(monkeypatch, is_admin=True)
    adapter = DeterministicFakeModelAdapter()
    url = _candidate_run_url(agent_key) if route == "candidate" else _baseline_run_url(agent_key)
    with _run_app(session_factory, adapter) as client:
        response = client.post(url, json={"unexpected": True})

    assert response.status_code == 422
    assert response.json() == {
        "code": "invalid_draft",
        "errors": [
            {
                "field": "agent_key",
                "code": "unknown_agent",
                "message": "Agent key must identify an editable model role.",
            }
        ],
    }
    assert adapter.calls == []


# --- refusals, in the executor's order ------------------------------------


def test_a_stale_lock_is_the_probes_409_with_no_model_call_or_row(session_factory, monkeypatch):
    """Catches a run of a candidate other than the one on the admin's screen (C32)."""
    _force_admin(monkeypatch, is_admin=True)
    adapter = DeterministicFakeModelAdapter()
    current = _draft_lock_version(session_factory)
    with _run_app(session_factory, adapter) as client:
        response = client.post(
            _candidate_run_url(), json=_candidate_body(session_factory, lock_version=current + 1)
        )

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "stale_draft"
    assert body["expected_lock_version"] == current + 1
    assert body["current_lock_version"] == current
    assert body["client_candidate"] is None
    assert set(body["server"]["definitions"]) == set(_GRAPH_V1_AGENT_KEYS)
    assert adapter.calls == []
    assert _test_run_rows(session_factory) == []


def test_a_stale_lock_is_refused_before_an_unknown_case(session_factory, monkeypatch):
    """Catches the refusal order moving the case lookup ahead of the lock (Task 4 order)."""
    _force_admin(monkeypatch, is_admin=True)
    current = _draft_lock_version(session_factory)
    with _run_app(session_factory) as client:
        response = client.post(
            _candidate_run_url(),
            json={"test_case_id": 424242, "lock_version": current + 1},
        )

    assert response.status_code == 409
    assert response.json()["code"] == "stale_draft"


def test_a_url_shaped_saved_endpoint_is_the_422_with_no_model_call(
    session_factory, monkeypatch
):
    """Catches a URL-shaped stored endpoint name reaching the provider via a run."""
    import src.services.graph_configuration_draft as draft_module

    _force_admin(monkeypatch, is_admin=True)
    adapter = DeterministicFakeModelAdapter()
    original = draft_module.validate_endpoint_name_policy
    monkeypatch.setattr(
        draft_module,
        "validate_endpoint_name_policy",
        lambda name: original("https://" + name),
    )
    with _run_app(session_factory, adapter) as client:
        response = client.post(_candidate_run_url(), json=_candidate_body(session_factory))

    assert response.status_code == 422
    assert response.json() == {
        "code": "invalid_draft",
        "errors": [
            {
                "field": "candidate.model.endpoint_name",
                "code": "endpoint_url_not_allowed",
                "message": "Endpoint must be a Databricks endpoint name, not a URL.",
            }
        ],
    }
    assert adapter.calls == []
    assert _test_run_rows(session_factory) == []


def test_a_url_shaped_published_endpoint_is_the_422_with_no_model_call(
    session_factory, monkeypatch
):
    """Catches a baseline rerun sending a URL-shaped published endpoint name."""
    _force_admin(monkeypatch, is_admin=True)
    adapter = DeterministicFakeModelAdapter()
    original = test_workbench_module.validate_endpoint_name_policy
    monkeypatch.setattr(
        test_workbench_module,
        "validate_endpoint_name_policy",
        lambda name: original("https://" + name),
    )
    with _run_app(session_factory, adapter) as client:
        response = client.post(_baseline_run_url(), json=_baseline_body(session_factory))

    assert response.status_code == 422
    assert response.json() == {
        "code": "invalid_draft",
        "errors": [
            {
                "field": "published.model.endpoint_name",
                "code": "endpoint_url_not_allowed",
                "message": "Endpoint must be a Databricks endpoint name, not a URL.",
            }
        ],
    }
    assert adapter.calls == []
    assert _test_run_rows(session_factory) == []


@pytest.mark.parametrize("case_state", ["missing", "other_role", "inactive"])
def test_a_baseline_rerun_refuses_the_published_endpoint_before_the_case(
    session_factory, monkeypatch, case_state
):
    """Catches the two run routes refusing in different orders (fix round 1, I-1)."""
    _force_admin(monkeypatch, is_admin=True)
    adapter = DeterministicFakeModelAdapter()
    original = test_workbench_module.validate_endpoint_name_policy
    monkeypatch.setattr(
        test_workbench_module,
        "validate_endpoint_name_policy",
        lambda name: original("https://" + name),
    )
    with _run_app(session_factory, adapter) as client:
        if case_state == "missing":
            test_case_id = 424242
        elif case_state == "other_role":
            test_case_id = _seed_test_case_id(session_factory, "builder")
        else:
            test_case_id = _seed_test_case_id(session_factory)
            assert client.put(_test_case_url(test_case_id), json=_update_body()).status_code == 200
        response = client.post(_baseline_run_url(), json={"test_case_id": test_case_id})

    assert response.status_code == 422
    assert response.json() == {
        "code": "invalid_draft",
        "errors": [
            {
                "field": "published.model.endpoint_name",
                "code": "endpoint_url_not_allowed",
                "message": "Endpoint must be a Databricks endpoint name, not a URL.",
            }
        ],
    }
    assert adapter.calls == []
    assert _test_run_rows(session_factory) == []


@pytest.mark.parametrize("case_state", ["missing", "other_role", "inactive"])
def test_a_candidate_run_refuses_the_saved_endpoint_before_the_case(
    session_factory, monkeypatch, case_state
):
    """The candidate twin of the baseline ordering test: endpoint 422 before the case."""
    import src.services.graph_configuration_draft as draft_module

    _force_admin(monkeypatch, is_admin=True)
    adapter = DeterministicFakeModelAdapter()
    original = draft_module.validate_endpoint_name_policy
    monkeypatch.setattr(
        draft_module,
        "validate_endpoint_name_policy",
        lambda name: original("https://" + name),
    )
    with _run_app(session_factory, adapter) as client:
        if case_state == "missing":
            test_case_id = 424242
        elif case_state == "other_role":
            test_case_id = _seed_test_case_id(session_factory, "builder")
        else:
            test_case_id = _seed_test_case_id(session_factory)
            assert client.put(_test_case_url(test_case_id), json=_update_body()).status_code == 200
        response = client.post(
            _candidate_run_url(),
            json={
                "test_case_id": test_case_id,
                "lock_version": _draft_lock_version(session_factory),
            },
        )

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "candidate.model.endpoint_name"
    assert adapter.calls == []
    assert _test_run_rows(session_factory) == []


@pytest.mark.parametrize("route", ["candidate", "baseline"])
def test_a_run_of_an_unknown_case_is_404_with_no_model_call(session_factory, monkeypatch, route):
    _force_admin(monkeypatch, is_admin=True)
    adapter = DeterministicFakeModelAdapter()
    with _run_app(session_factory, adapter) as client:
        if route == "candidate":
            response = client.post(
                _candidate_run_url(), json=_candidate_body(session_factory, test_case_id=424242)
            )
        else:
            response = client.post(
                _baseline_run_url(), json=_baseline_body(session_factory, test_case_id=424242)
            )

    assert response.status_code == 404
    assert response.json() == {"detail": "Test case not found"}
    assert adapter.calls == []
    assert _test_run_rows(session_factory) == []


@pytest.mark.parametrize("route", ["candidate", "baseline"])
def test_a_run_of_another_roles_case_is_the_ordered_case_422(session_factory, monkeypatch, route):
    """Catches a builder case run through the architect's definition."""
    _force_admin(monkeypatch, is_admin=True)
    adapter = DeterministicFakeModelAdapter()
    builder_case = _seed_test_case_id(session_factory, "builder")
    with _run_app(session_factory, adapter) as client:
        if route == "candidate":
            response = client.post(
                _candidate_run_url(),
                json=_candidate_body(session_factory, test_case_id=builder_case),
            )
        else:
            response = client.post(
                _baseline_run_url(),
                json=_baseline_body(session_factory, test_case_id=builder_case),
            )

    assert response.status_code == 422
    assert response.json() == _invalid_test_case(
        (
            "test_case_id",
            "agent_key_mismatch",
            "This test case belongs to another agent role.",
        )
    )
    assert adapter.calls == []
    assert _test_run_rows(session_factory) == []


@pytest.mark.parametrize("route", ["candidate", "baseline"])
def test_a_run_of_a_superseded_case_version_is_409_stale(session_factory, monkeypatch, route):
    """Catches a run of a historical case version (ruling P5)."""
    _force_admin(monkeypatch, is_admin=True)
    adapter = DeterministicFakeModelAdapter()
    seed_id = _seed_test_case_id(session_factory)
    with _run_app(session_factory, adapter) as client:
        assert client.put(_test_case_url(seed_id), json=_update_body()).status_code == 200
        if route == "candidate":
            response = client.post(
                _candidate_run_url(), json=_candidate_body(session_factory, test_case_id=seed_id)
            )
        else:
            response = client.post(
                _baseline_run_url(), json=_baseline_body(session_factory, test_case_id=seed_id)
            )

    assert response.status_code == 409
    assert response.json() == {
        "code": "stale_test_case",
        "test_case_id": seed_id,
        "message": "This test case version is no longer active. Reload and retry.",
    }
    assert adapter.calls == []
    assert _test_run_rows(session_factory) == []


@pytest.mark.parametrize("route", ["candidate", "baseline"])
def test_a_database_failure_after_the_model_call_is_503_with_no_row(
    session_factory, monkeypatch, route
):
    """Catches a persistence outage surfacing as a 500 or with driver text (C16)."""
    _force_admin(monkeypatch, is_admin=True)
    adapter = DeterministicFakeModelAdapter()

    original = GraphConfiguration._lock_current_parents

    def _outage_after_the_model_call(self, session, *, exclusive):
        if not adapter.calls:  # transaction 1's reads still succeed
            return original(self, session, exclusive=exclusive)
        raise OperationalError("SELECT secret", {}, Exception("SECRET_DRIVER_TEXT"))

    monkeypatch.setattr(
        GraphConfiguration, "_lock_current_parents", _outage_after_the_model_call
    )
    with _run_app(session_factory, adapter, raise_server_exceptions=False) as client:
        if route == "candidate":
            response = client.post(
                _candidate_run_url(), json=_candidate_body(session_factory)
            )
        else:
            response = client.post(_baseline_run_url(), json=_baseline_body(session_factory))

    assert len(adapter.calls) == 1
    assert response.status_code == 503
    assert response.json() == _TEST_RUN_UNAVAILABLE
    assert "SECRET" not in response.text
    assert _test_run_rows(session_factory) == []


@pytest.mark.parametrize("route", ["candidate", "baseline"])
def test_test_run_unavailable_from_any_phase_is_the_503(session_factory, monkeypatch, route):
    _force_admin(monkeypatch, is_admin=True)
    method = "execute_candidate_run" if route == "candidate" else "execute_baseline_rerun"

    def _unavailable(self, session, **_kwargs):
        raise TestRunUnavailable("read_case")

    monkeypatch.setattr(AgentTestWorkbench, method, _unavailable)
    with _run_app(session_factory) as client:
        if route == "candidate":
            response = client.post(
                _candidate_run_url(), json=_candidate_body(session_factory)
            )
        else:
            response = client.post(_baseline_run_url(), json=_baseline_body(session_factory))

    assert response.status_code == 503
    assert response.json() == _TEST_RUN_UNAVAILABLE
    assert "read_case" not in response.text


@pytest.mark.parametrize("route", ["candidate", "baseline"])
def test_an_incomplete_persisted_configuration_is_the_existing_500(
    session_factory, monkeypatch, route
):
    _force_admin(monkeypatch, is_admin=True)
    method = "execute_candidate_run" if route == "candidate" else "execute_baseline_rerun"

    def _incomplete(self, session, **_kwargs):
        raise GraphConfigurationIntegrityError("SECRET_INTEGRITY_TEXT")

    monkeypatch.setattr(AgentTestWorkbench, method, _incomplete)
    with _run_app(session_factory, raise_server_exceptions=False) as client:
        if route == "candidate":
            response = client.post(
                _candidate_run_url(), json=_candidate_body(session_factory)
            )
        else:
            response = client.post(_baseline_run_url(), json=_baseline_body(session_factory))

    assert response.status_code == 500
    assert response.json() == {"detail": "Graph configuration is incomplete"}
    assert "SECRET" not in response.text


# --- off the event loop (C36) and the production dependency (C33) ----------


@pytest.mark.parametrize("route", ["candidate", "baseline"])
def test_test_run_routes_call_the_model_off_the_event_loop(session_factory, monkeypatch, route):
    """Catches a live model call blocking the server's event loop (C36)."""
    _force_admin(monkeypatch, is_admin=True)
    loop_running: list[bool] = []

    class _LoopObservingAdapter(DeterministicFakeModelAdapter):
        def invoke(self, **kwargs):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                loop_running.append(False)
            else:
                loop_running.append(True)
            return super().invoke(**kwargs)

    with _run_app(session_factory, _LoopObservingAdapter()) as client:
        if route == "candidate":
            response = client.post(
                _candidate_run_url(), json=_candidate_body(session_factory)
            )
        else:
            response = client.post(_baseline_run_url(), json=_baseline_body(session_factory))

    assert response.status_code == 201
    assert loop_running == [False]


def test_the_production_workbench_dependency_uses_the_bounded_test_runtime(
    session_factory, monkeypatch
):
    """Catches the run routes binding the unbounded production runtime (C33)."""
    adapter = DeterministicFakeModelAdapter()
    runtime = AgentRuntime(
        persisted_release_loader=PersistedGraphReleaseLoader(session_factory=session_factory),
        model_adapter=adapter,
        identity_sink=RecordingAgentInvocationIdentitySink(),
    )
    calls: list[str] = []

    def _bounded() -> AgentRuntime:
        calls.append("bounded")
        return runtime

    monkeypatch.setattr(test_workbench_module, "get_agent_test_runtime", _bounded)
    _force_admin(monkeypatch, is_admin=True)
    workbench = agent_definition_routes.get_agent_test_workbench()
    assert isinstance(workbench, AgentTestWorkbench)
    assert calls == [], "building the dependency must not build a runtime"

    with _app_for(session_factory) as client:
        response = client.post(_candidate_run_url(), json=_candidate_body(session_factory))

    assert response.status_code == 201
    assert calls == ["bounded"]
    assert len(adapter.calls) == 1


def test_test_run_paths_do_not_collide_with_existing_admin_routes():
    """Catches a #267 path shadowing #266's discovery, probe or the case routes (C38)."""
    pairs = [
        (method, route.path)
        for route in router.routes
        for method in sorted(getattr(route, "methods", set()))
    ]
    assert len(pairs) == len(set(pairs)), "two handlers share one method and path"
    new_routes = {
        ("POST", "/api/admin/agent-definitions/draft/{agent_key}/test-runs"),
        ("POST", "/api/admin/agent-definitions/published/{agent_key}/test-runs"),
        ("GET", "/api/admin/agent-definitions/test-runs/{run_id}"),
        ("GET", "/api/admin/agent-definitions/test-cases/{test_case_id}/runs"),
    }
    assert new_routes <= set(pairs)
    for _method, path in new_routes:
        for reserved in ("model-endpoints", "model-endpoint-probe", "structured"):
            assert reserved not in path


# ===========================================================================
# #268 Task 3: the verdict and readiness routes on the one admin router
# (C15, C16, C17)
# ===========================================================================

from sqlalchemy.exc import IntegrityError  # noqa: E402

from src.services.agent_test_workbench import (  # noqa: E402
    IneligibleForApprovalError,
)

_READINESS_URL = f"{_TEST_RUN_PREFIX}/readiness"
_VERDICT_BODY = {"verdict": "approved", "notes": "Looks right."}
_NOT_COMPLETED_MESSAGE = "Only a completed run can take a verdict."
_CHECKS_FAILED_MESSAGE = "A run whose deterministic checks failed cannot be approved."


def _verdict_url(run_id: int) -> str:
    return f"{_TEST_RUN_PREFIX}/test-runs/{run_id}/verdict"


def _new_candidate_run(client: TestClient, session_factory, agent_key="architect") -> dict:
    response = client.post(
        _candidate_run_url(agent_key), json=_candidate_body(session_factory, agent_key)
    )
    assert response.status_code == 201
    return response.json()


def _insert_run_like(session_factory, source_run_id: int, **overrides) -> int:
    """An INSERT-only copy of a real run (#268 C8): never an UPDATE of a run row."""
    with session_factory() as session:
        source = session.get(AgentTestRun, source_run_id)
        values = {
            column.key: getattr(source, column.key)
            for column in AgentTestRun.__table__.columns
            if column.key != "id"
        }
    values.update(overrides)
    with session_factory() as session:
        row = AgentTestRun(**values)
        session.add(row)
        session.commit()
        return row.id


def _verdict_columns(session_factory, run_id: int) -> tuple[object, ...]:
    with session_factory() as session:
        row = session.get(AgentTestRun, run_id)
        return (row.verdict, row.verdict_reviewer, row.verdict_at, row.verdict_notes)


def _change_role_prompt(client: TestClient, agent_key: str = "architect") -> None:
    """A real draft save (#268 C13): the role's candidate hash moves off the base."""
    body = _workbench(client)
    node = _model_node(body, agent_key)
    response = client.put(
        _draft_save_url(agent_key),
        json={
            "lock_version": body["draft"]["lock_version"],
            "candidate": _editable_candidate(
                node, prompt_text=f"{node['draft']['prompt_text']}\n\nA #268 change."
            ),
        },
    )
    assert response.status_code == 200


def _json_shape(value: object) -> object:
    """``dataclasses.asdict`` output as the wire renders it (tuples are arrays)."""
    if isinstance(value, dict):
        return {key: _json_shape(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_shape(item) for item in value]
    return value


_VERDICT_AND_READINESS_ROUTES = [
    ("POST", lambda run_id: _verdict_url(run_id), "record_verdict"),
    ("GET", lambda _run_id: _READINESS_URL, "draft_readiness"),
]
_VERDICT_AND_READINESS_IDS = ["verdict", "readiness"]


def _forbid_verdict_and_readiness_service(monkeypatch, calls: list[str]) -> None:
    def _must_not_reach(*_args, **_kwargs):
        calls.append("service")
        raise AssertionError("authorization reached the verdict or readiness service")

    for method in ("record_verdict", "draft_readiness", "readiness_under_parent_lock"):
        monkeypatch.setattr(AgentTestWorkbench, method, _must_not_reach)


# --- authorization before the body or the service (C15) ---------------------


@pytest.mark.parametrize(
    ("method", "url_for", "_service"),
    _VERDICT_AND_READINESS_ROUTES,
    ids=_VERDICT_AND_READINESS_IDS,
)
def test_verdict_and_readiness_routes_deny_non_admins_before_body_or_service(
    session_factory, monkeypatch, method, url_for, _service
):
    """Catches either route outside the admin router, or a body read before auth."""
    _force_admin(monkeypatch, is_admin=False)
    calls: list[str] = []

    async def _must_not_parse_json(_request):
        calls.append("body")
        raise AssertionError("authorization parsed the raw request body")

    _forbid_verdict_and_readiness_service(monkeypatch, calls)
    monkeypatch.setattr(agent_definition_routes.Request, "json", _must_not_parse_json)
    before = _all_table_rows(session_factory)
    with _run_app(session_factory, raise_server_exceptions=False) as client:
        response = client.request(
            method,
            url_for(1),
            content=b'{not json; "verdict": "SUPER_SECRET_VERDICT"}',
            headers={"content-type": "application/json"},
        )

    assert calls == []
    assert response.status_code == 403
    assert response.json() == {"detail": "Admin access required"}
    assert "SUPER_SECRET_VERDICT" not in response.text
    assert _all_table_rows(session_factory) == before


@pytest.mark.parametrize("principal", [None, " \t "])
def test_the_verdict_route_requires_a_trusted_principal_before_body_or_service(
    session_factory, monkeypatch, principal
):
    """Catches a verdict recorded, or its body read, with no reviewer to audit."""
    _force_admin(monkeypatch, is_admin=True)
    set_current_user(principal)
    calls: list[str] = []

    async def _must_not_parse_json(_request):
        calls.append("body")
        raise AssertionError("a missing principal parsed the body")

    _forbid_verdict_and_readiness_service(monkeypatch, calls)
    monkeypatch.setattr(agent_definition_routes.Request, "json", _must_not_parse_json)
    with _run_app(session_factory, raise_server_exceptions=False) as client:
        client.app.dependency_overrides[agent_definition_routes.require_admin] = lambda: None
        response = client.post(
            _verdict_url(1),
            content=b"{not json; should not be parsed}",
            headers={"content-type": "application/json"},
        )

    assert calls == []
    assert response.status_code == 403
    assert response.json() == {"detail": "Authenticated principal required"}


def test_a_blank_reviewer_reaching_the_writer_is_the_principal_403(
    session_factory, monkeypatch
):
    """Catches the writer's blank-``actor`` issue leaking out as a client 422.

    The principal dependency already refuses a blank principal, so this is the
    route's second line: the reviewer is never the client's to fix.
    """
    _force_admin(monkeypatch, is_admin=True)
    with _run_app(session_factory) as client:
        run = _new_candidate_run(client, session_factory)
        client.app.dependency_overrides[
            agent_definition_routes.require_draft_write_principal
        ] = lambda: "   "
        response = client.post(_verdict_url(run["run_id"]), json=_VERDICT_BODY)

    assert response.status_code == 403
    assert response.json() == {"detail": "Authenticated principal required"}
    assert _verdict_columns(session_factory, run["run_id"]) == (None, None, None, None)


# --- the verdict write (C15, C16) -------------------------------------------


@pytest.mark.parametrize(
    ("verdict", "notes"),
    [("approved", "Looks right."), ("rejected", None)],
    ids=["approve", "reject-without-notes"],
)
def test_a_verdict_returns_200_evidence_with_the_principal_as_reviewer(
    session_factory, monkeypatch, verdict, notes
):
    """Catches a verdict route that returns 201, loses the evidence, or audits
    anyone but the authenticated principal."""
    _force_admin(monkeypatch, is_admin=True)
    with _run_app(session_factory) as client:
        run = _new_candidate_run(client, session_factory)
        response = client.post(
            _verdict_url(run["run_id"]), json={"verdict": verdict, "notes": notes}
        )
        read_back = client.get(_run_url(run["run_id"]))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == _TEST_RUN_KEYS
    assert body["verdict"] == verdict
    assert body["verdict_reviewer"] == _ROUTE_ACTOR
    assert body["verdict_notes"] == notes
    assert isinstance(body["verdict_at"], str) and body["verdict_at"]
    assert (body["candidate_is_current"], body["base_release_is_current"]) == (None, None)
    _assert_body_is_the_row(body, _test_run_rows(session_factory)[0])
    expected = dict(run)
    expected.update(
        verdict=verdict,
        verdict_reviewer=_ROUTE_ACTOR,
        verdict_at=body["verdict_at"],
        verdict_notes=notes,
        candidate_is_current=None,
        base_release_is_current=None,
    )
    assert body == expected
    assert read_back.json() == body


def test_a_verdict_route_passes_exactly_the_body_and_the_principal(
    session_factory, monkeypatch
):
    """Catches a reviewer, run id or notes taken from anywhere but their owner."""
    _force_admin(monkeypatch, is_admin=True)
    calls: list[dict[str, object]] = []
    original = AgentTestWorkbench.record_verdict

    def _recording(self, session, **kwargs):
        calls.append(dict(kwargs))
        return original(self, session, **kwargs)

    monkeypatch.setattr(AgentTestWorkbench, "record_verdict", _recording)
    with _run_app(session_factory) as client:
        run = _new_candidate_run(client, session_factory)
        response = client.post(
            _verdict_url(run["run_id"]), json={"verdict": "rejected", "notes": "  Kept.  "}
        )

    assert response.status_code == 200
    assert calls == [
        {
            "run_id": run["run_id"],
            "verdict": "rejected",
            "reviewer": _ROUTE_ACTOR,
            "notes": "  Kept.  ",
        }
    ]


def test_an_approval_of_a_run_with_failed_checks_is_the_exact_ineligible_422(
    session_factory, monkeypatch
):
    """Catches an ineligible approval written, or refused without its exact reason."""
    _force_admin(monkeypatch, is_admin=True)
    with _run_app(session_factory) as client:
        source = _new_candidate_run(client, session_factory)
        failing = _insert_run_like(
            session_factory, source["run_id"], deterministic_checks_passed=False
        )
        response = client.post(_verdict_url(failing), json=_VERDICT_BODY)

    assert response.status_code == 422
    assert response.json() == {
        "code": "ineligible_for_approval",
        "reason": "checks_failed",
        "message": _CHECKS_FAILED_MESSAGE,
    }
    assert _verdict_columns(session_factory, failing) == (None, None, None, None)


@pytest.mark.parametrize("verdict", ["approved", "rejected"])
def test_a_verdict_on_a_run_that_did_not_complete_is_the_exact_not_completed_422(
    session_factory, monkeypatch, verdict
):
    """Catches a model-error run taking either verdict (#268 C5)."""
    _force_admin(monkeypatch, is_admin=True)
    adapter = DeterministicFakeModelAdapter(mode="provider_unavailable")
    with _run_app(session_factory, adapter) as client:
        run = _new_candidate_run(client, session_factory)
        assert run["execution_status"] == "model_error"
        response = client.post(
            _verdict_url(run["run_id"]), json={"verdict": verdict, "notes": None}
        )

    assert response.status_code == 422
    assert response.json() == {
        "code": "ineligible_for_approval",
        "reason": "not_completed",
        "message": _NOT_COMPLETED_MESSAGE,
    }
    assert _verdict_columns(session_factory, run["run_id"]) == (None, None, None, None)


@pytest.mark.parametrize("run_id", [424242, 0, -3, _INT32_MAX + 1, 2**63])
def test_a_verdict_on_an_unknown_or_unstorable_run_is_404(session_factory, monkeypatch, run_id):
    """Catches an unknown run id reaching the database as a 500, or as a write."""
    _force_admin(monkeypatch, is_admin=True)
    before = _all_table_rows(session_factory)
    with _run_app(session_factory) as client:
        response = client.post(_verdict_url(run_id), json=_VERDICT_BODY)

    assert response.status_code == 404
    assert response.json() == {"detail": "Test run not found"}
    assert _all_table_rows(session_factory) == before


_FORBIDDEN_VERDICT_BODY_FIELDS = [
    ("reviewer", "someone-else@example.com"),
    ("verdict_reviewer", "someone-else@example.com"),
    ("actor", "someone-else@example.com"),
    ("run_by", "someone-else@example.com"),
    ("verdict_at", "2020-01-01T00:00:00Z"),
    ("run_id", 1),
    ("verdict_notes", "a second notes field"),
    ("execution_status", "completed"),
    ("deterministic_checks_passed", True),
]


@pytest.mark.parametrize(
    ("field", "value"),
    _FORBIDDEN_VERDICT_BODY_FIELDS,
    ids=[field for field, _value in _FORBIDDEN_VERDICT_BODY_FIELDS],
)
def test_a_verdict_body_cannot_choose_any_server_owned_value(
    session_factory, monkeypatch, field, value
):
    """Catches a verdict body that lets the client name the reviewer, the time,
    the run or its eligibility (plan sabotage S3)."""
    _force_admin(monkeypatch, is_admin=True)
    with _run_app(session_factory) as client:
        run = _new_candidate_run(client, session_factory)
        response = client.post(_verdict_url(run["run_id"]), json={**_VERDICT_BODY, field: value})

    assert response.status_code == 422
    assert response.json() == {
        "code": "invalid_verdict",
        "errors": [
            {"field": field, "code": "extra_forbidden", "message": "Extra inputs are not permitted"}
        ],
    }
    assert _verdict_columns(session_factory, run["run_id"]) == (None, None, None, None)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"verdict": "maybe", "notes": None}, [("verdict", "invalid_choice")]),
        ({"verdict": "Approved", "notes": None}, [("verdict", "invalid_choice")]),
        ({"verdict": 1, "notes": None}, [("verdict", "strict_type")]),
        ({"verdict": None, "notes": None}, [("verdict", "strict_type")]),
        ({"notes": None}, [("verdict", "strict_type")]),
        ({"verdict": "approved"}, [("notes", "strict_type")]),
        ({"verdict": "approved", "notes": 3}, [("notes", "strict_type")]),
        ({"verdict": "approved", "notes": "  "}, [("notes", "blank")]),
        ({"verdict": "approved", "notes": "x" * 2001}, [("notes", "too_long")]),
        (
            {"verdict": "maybe", "notes": ""},
            [("verdict", "invalid_choice"), ("notes", "blank")],
        ),
    ],
    ids=[
        "unknown-verdict",
        "wrong-case-verdict",
        "number-verdict",
        "null-verdict",
        "missing-verdict",
        "missing-notes",
        "number-notes",
        "blank-notes",
        "long-notes",
        "both-ordered",
    ],
)
def test_an_invalid_verdict_body_is_the_ordered_invalid_verdict_422(
    session_factory, monkeypatch, body, expected
):
    """Catches a coerced or unvalidated verdict body reaching the row."""
    _force_admin(monkeypatch, is_admin=True)
    with _run_app(session_factory) as client:
        run = _new_candidate_run(client, session_factory)
        response = client.post(_verdict_url(run["run_id"]), json=body)

    assert response.status_code == 422
    payload = response.json()
    assert set(payload) == {"code", "errors"}
    assert payload["code"] == "invalid_verdict"
    assert [(error["field"], error["code"]) for error in payload["errors"]] == expected
    for error in payload["errors"]:
        assert isinstance(error["message"], str) and error["message"]
    assert _verdict_columns(session_factory, run["run_id"]) == (None, None, None, None)


def test_a_verdict_body_must_be_valid_json_and_a_json_object(session_factory, monkeypatch):
    _force_admin(monkeypatch, is_admin=True)
    with _run_app(session_factory) as client:
        run = _new_candidate_run(client, session_factory)
        malformed = client.post(
            _verdict_url(run["run_id"]),
            content=b"{not json",
            headers={"content-type": "application/json"},
        )
        not_an_object = client.post(_verdict_url(run["run_id"]), json=["approved"])

    assert malformed.status_code == 422
    assert malformed.json() == {
        "code": "invalid_verdict",
        "errors": [
            {"field": "$", "code": "invalid_json", "message": "Request body must be valid JSON."}
        ],
    }
    assert not_an_object.status_code == 422
    assert not_an_object.json()["code"] == "invalid_verdict"
    assert _verdict_columns(session_factory, run["run_id"]) == (None, None, None, None)


def test_the_verdict_body_is_validated_before_the_run_is_looked_up(session_factory, monkeypatch):
    """Catches a body error hidden behind a 404, or a lookup made for a bad body."""
    _force_admin(monkeypatch, is_admin=True)
    calls: list[str] = []
    monkeypatch.setattr(
        AgentTestWorkbench,
        "record_verdict",
        lambda *_a, **_k: calls.append("service"),
    )
    with _run_app(session_factory) as client:
        response = client.post(_verdict_url(424242), json={"verdict": 1, "notes": None})

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_verdict"
    assert calls == []


def test_a_verdict_integrity_error_is_never_translated(session_factory, monkeypatch):
    """Catches #269's linked-verdict trigger (23514) swallowed into a 409 or a 422
    ineligibility (#268 C7): it propagates, and the server renders its 500."""
    _force_admin(monkeypatch, is_admin=True)

    def _trigger(self, session, **_kwargs):
        raise IntegrityError("UPDATE agent_test_run", {}, Exception("SECRET_TRIGGER_TEXT"))

    monkeypatch.setattr(AgentTestWorkbench, "record_verdict", _trigger)
    with _run_app(session_factory) as client, pytest.raises(IntegrityError):
        client.post(_verdict_url(1), json=_VERDICT_BODY)
    with _run_app(session_factory, raise_server_exceptions=False) as client:
        response = client.post(_verdict_url(1), json=_VERDICT_BODY)

    assert response.status_code == 500
    assert "SECRET_TRIGGER_TEXT" not in response.text
    assert "ineligible" not in response.text


def test_an_ineligibility_reason_the_wire_does_not_know_is_not_rendered(
    session_factory, monkeypatch
):
    """Catches a new service reason serialized as an undocumented 422 code."""
    _force_admin(monkeypatch, is_admin=True)

    def _unknown(self, session, **kwargs):
        # ``linked_to_release`` became a wire reason in #269 (C48).
        raise IneligibleForApprovalError(kwargs["run_id"], "withdrawn")

    monkeypatch.setattr(AgentTestWorkbench, "record_verdict", _unknown)
    with _run_app(session_factory, raise_server_exceptions=False) as client:
        response = client.post(_verdict_url(1), json=_VERDICT_BODY)

    assert response.status_code == 500
    assert "withdrawn" not in response.text


def test_the_verdict_route_waits_on_the_run_row_lock_off_the_event_loop(
    session_factory, monkeypatch
):
    """Catches the L3 ``FOR UPDATE`` wait blocking the server's event loop."""
    _force_admin(monkeypatch, is_admin=True)
    loop_running: list[bool] = []
    original = AgentTestWorkbench.record_verdict

    def _observing(self, *args, **kwargs):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            loop_running.append(False)
        else:
            loop_running.append(True)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(AgentTestWorkbench, "record_verdict", _observing)
    with _run_app(session_factory) as client:
        run = _new_candidate_run(client, session_factory)
        response = client.post(_verdict_url(run["run_id"]), json=_VERDICT_BODY)

    assert response.status_code == 200
    assert loop_running == [False]


# --- readiness (C15, C17) ---------------------------------------------------


def _readiness_of(session_factory) -> dict[str, object]:
    with session_factory() as session:
        result = AgentTestWorkbench().draft_readiness(session)
    return _json_shape(dataclasses.asdict(result))


def _readiness_case(body: dict, agent_key: str) -> dict:
    agent = next(item for item in body["agents"] if item["agent_key"] == agent_key)
    assert len(agent["cases"]) == 1
    return agent["cases"][0]


def test_readiness_of_an_unchanged_draft_is_200_all_ready_with_the_exact_shape(
    session_factory, monkeypatch
):
    """Catches a readiness wire that relabels, camel-cases or reshapes the result."""
    _force_admin(monkeypatch, is_admin=True)
    identity = _identity_row(session_factory)
    with _run_app(session_factory) as client:
        response = client.get(_READINESS_URL)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "draft_lock_version",
        "base_release_id",
        "all_ready",
        "blocking_agents",
        "agents",
    }
    assert body == _readiness_of(session_factory)
    assert body["draft_lock_version"] == _draft_lock_version(session_factory)
    assert body["base_release_id"] == identity["release_id"]
    assert (body["all_ready"], body["blocking_agents"]) == (True, [])
    assert [agent["agent_key"] for agent in body["agents"]] == list(_GRAPH_V1_AGENT_KEYS)
    for agent in body["agents"]:
        assert set(agent) == {
            "agent_key",
            "candidate_hash",
            "is_changed_from_base",
            "ready",
            "missing_required_case",
            "cases",
        }
        assert (agent["is_changed_from_base"], agent["ready"]) == (False, True)
        case = _readiness_case(body, agent["agent_key"])
        assert set(case) == {
            "agent_key",
            "test_case_id",
            "test_case_name",
            "test_case_version",
            "status",
            "blocking",
            "run_id",
            "run_verdict",
            "run_checks_passed",
        }
        assert case["test_case_id"] == _seed_test_case_id(session_factory, agent["agent_key"])
        assert (case["status"], case["blocking"], case["run_id"]) == ("needs_test", False, None)


def test_readiness_names_the_one_blocking_role_and_case(session_factory, monkeypatch):
    """Catches readiness that hides the changed role, or blocks an unchanged one."""
    _force_admin(monkeypatch, is_admin=True)
    with _run_app(session_factory) as client:
        _change_role_prompt(client, "architect")
        response = client.get(_READINESS_URL)

    assert response.status_code == 200
    body = response.json()
    assert body == _readiness_of(session_factory)
    assert (body["all_ready"], body["blocking_agents"]) == (False, ["architect"])
    architect = next(agent for agent in body["agents"] if agent["agent_key"] == "architect")
    assert (architect["is_changed_from_base"], architect["ready"]) == (True, False)
    assert architect["missing_required_case"] is False
    case = _readiness_case(body, "architect")
    assert case["test_case_id"] == _seed_test_case_id(session_factory, "architect")
    assert case["test_case_name"] == "architect_required_smoke_v1"
    assert (case["status"], case["blocking"], case["run_id"]) == ("needs_test", True, None)
    for agent in body["agents"]:
        if agent["agent_key"] != "architect":
            assert (agent["is_changed_from_base"], agent["ready"]) == (False, True)


def test_readiness_follows_a_run_and_its_verdict_through_the_routes(session_factory, monkeypatch):
    """Catches the readiness wire losing a status code, a run id or the verdict."""
    _force_admin(monkeypatch, is_admin=True)
    with _run_app(session_factory) as client:
        _change_role_prompt(client, "architect")
        run = _new_candidate_run(client, session_factory)
        awaiting = client.get(_READINESS_URL).json()
        client.post(_verdict_url(run["run_id"]), json={"verdict": "rejected", "notes": None})
        rejected = client.get(_READINESS_URL).json()
        client.post(_verdict_url(run["run_id"]), json=_VERDICT_BODY)
        approved = client.get(_READINESS_URL).json()

    assert _readiness_case(awaiting, "architect") == {
        "agent_key": "architect",
        "test_case_id": run["test_case_id"],
        "test_case_name": "architect_required_smoke_v1",
        "test_case_version": 1,
        "status": "awaiting_review",
        "blocking": True,
        "run_id": run["run_id"],
        "run_verdict": None,
        "run_checks_passed": True,
    }
    assert _readiness_case(rejected, "architect")["status"] == "test_failed"
    assert _readiness_case(rejected, "architect")["run_verdict"] == "rejected"
    assert (approved["all_ready"], approved["blocking_agents"]) == (True, [])
    assert _readiness_case(approved, "architect")["status"] == "approved"
    assert _readiness_case(approved, "architect")["blocking"] is False
    assert _readiness_case(approved, "architect")["run_id"] == run["run_id"]


def test_readiness_status_codes_are_the_service_codes_not_labels():
    """Catches display labels ('Needs test') or a drifted code set on the wire (C17)."""
    from typing import get_args

    from src.api.schemas.agent_definitions import DraftReadinessResponse
    from src.services.agent_test_workbench import ReadinessStatus

    agent_model = DraftReadinessResponse.model_fields["agents"].annotation.__args__[0]
    case_model = agent_model.model_fields["cases"].annotation.__args__[0]
    assert set(get_args(case_model.model_fields["status"].annotation)) == set(
        get_args(ReadinessStatus)
    )
    assert set(get_args(ReadinessStatus)) == {
        "needs_test",
        "test_failed",
        "awaiting_review",
        "approved",
    }
    for model in (DraftReadinessResponse, agent_model, case_model):
        assert model.model_config.get("extra") == "forbid", model.__name__
        assert all(name == name.lower() for name in model.model_fields), model.__name__


def test_readiness_of_an_incomplete_configuration_is_the_existing_500(
    session_factory, monkeypatch
):
    """Catches the un-retried parent-handoff error escaping as a raw traceback."""
    _force_admin(monkeypatch, is_admin=True)

    def _incomplete(self, session):
        raise GraphConfigurationIntegrityError(
            "graph configuration parent snapshot is inconsistent"
        )

    monkeypatch.setattr(AgentTestWorkbench, "draft_readiness", _incomplete)
    with _run_app(session_factory, raise_server_exceptions=False) as client:
        response = client.get(_READINESS_URL)

    assert response.status_code == 500
    assert response.json() == {"detail": "Graph configuration is incomplete"}
    assert "parent snapshot" not in response.text


def test_readiness_reads_off_the_event_loop(session_factory, monkeypatch):
    """Catches the shared parent-lock wait blocking the server's event loop."""
    _force_admin(monkeypatch, is_admin=True)
    loop_running: list[bool] = []
    original = AgentTestWorkbench.draft_readiness

    def _observing(self, *args, **kwargs):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            loop_running.append(False)
        else:
            loop_running.append(True)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(AgentTestWorkbench, "draft_readiness", _observing)
    with _run_app(session_factory) as client:
        response = client.get(_READINESS_URL)

    assert response.status_code == 200
    assert loop_running == [False]


def test_verdict_and_readiness_paths_are_on_the_one_router_and_collide_with_nothing():
    """Catches the plan's off-router paths, or a GET that shadows ``/readiness`` (C15)."""
    pairs = [
        (method, route.path)
        for route in router.routes
        for method in sorted(getattr(route, "methods", set()))
    ]
    assert len(pairs) == len(set(pairs)), "two handlers share one method and path"
    assert ("POST", "/api/admin/agent-definitions/test-runs/{run_id}/verdict") in pairs
    assert ("GET", "/api/admin/agent-definitions/readiness") in pairs
    assert [path for method, path in pairs if path.endswith("/readiness")] == [
        "/api/admin/agent-definitions/readiness"
    ]
    for _method, path in pairs:
        assert "agent-test-runs" not in path and "graph-draft" not in path
