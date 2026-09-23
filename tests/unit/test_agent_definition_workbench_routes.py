from __future__ import annotations

import builtins
import json
import math
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
    DraftContentRejected,
    DraftValidationIssue,
    GraphConfiguration,
    GraphConfigurationIntegrityError,
)
from src.services.graph_configuration_content import definition_content_from_row
from src.services.graph_definition_manifest import load_graph_v1_manifest
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


def _app_for(
    session_factory: sessionmaker,
    *,
    raise_server_exceptions: bool = True,
) -> TestClient:
    app = FastAPI()
    app.include_router(router)

    def _override_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
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

    matches = [
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/admin/agent-definitions/workbench"
    ]
    assert len(matches) == 1
    assert matches[0].methods == {"GET"}


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
        ("candidate.schema_overlay", {}, "candidate.schema_overlay", "extra_forbidden", ""),
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


@pytest.mark.parametrize("url_builder", [_upgrade_url, _source_url])
@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"lock_version": -1}, ("lock_version", "out_of_range")),
        ({"lock_version": "0"}, ("lock_version", "strict_type")),
        ({}, ("lock_version", "strict_type")),
        ({"lock_version": 0, "actor": "attacker"}, ("actor", "extra_forbidden")),
        (
            {"lock_version": 0, "protected_assembly": {"version": 2, "digest": "f" * 64}},
            ("protected_assembly", "extra_forbidden"),
        ),
        ({"lock_version": 0, "prompt_text": "spoofed"}, ("prompt_text", "extra_forbidden")),
        (
            {"lock_version": 0, "protected_stage_view": []},
            ("protected_stage_view", "extra_forbidden"),
        ),
        (
            {"lock_version": 0, "assembly_rules": {"format_version": 2, "custom_blocks": []}},
            ("assembly_rules", "extra_forbidden"),
        ),
        ({"lock_version": 0, "display_text": "x"}, ("display_text", "extra_forbidden")),
        ({"lock_version": 0, "terminal": True}, ("terminal", "extra_forbidden")),
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
    payload = response.json()
    assert payload["code"] == "invalid_draft"
    assert (payload["errors"][0]["field"], payload["errors"][0]["code"]) == expected


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
