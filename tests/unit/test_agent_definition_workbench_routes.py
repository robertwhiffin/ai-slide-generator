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
from src.core.database import Base, get_db
from src.core.user_context import set_current_user
from src.database.models.graph_configuration import (
    AgentDefinitionRevision,
    GraphDraft,
    GraphDraftAgent,
    GraphRelease,
    GraphReleaseAgent,
)
from src.services.graph_configuration import (
    GraphConfiguration,
    GraphConfigurationIntegrityError,
)
from src.services.graph_configuration_content import definition_content_from_row
from src.services.graph_definition_manifest import load_graph_v1_manifest

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
    with _app_for(session_factory) as client:
        before = _workbench(client)
        architect = _model_node(before, "architect")
        payload = {
            "lock_version": before["draft"]["lock_version"],
            "candidate": _editable_candidate(
                architect,
                prompt_text="Architect draft changed through the admin route.",
                **{
                    "model.endpoint_name": " custom-endpoint-name ",
                    "model.temperature": 0.25,
                    "model.max_tokens": 4096,
                    "model.top_p": 0.8,
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
    assert response.json()["code"] == "invalid_draft"
    assert response.json()["errors"][0]["field"] == "$"


def test_non_admin_put_rejects_before_body_or_writer_and_does_not_echo_secrets(
    session_factory, monkeypatch
):
    _force_admin(monkeypatch, is_admin=False)
    calls: list[str] = []

    def _must_not_write(*_args, **_kwargs):
        calls.append("write")
        raise AssertionError("authorization reached the draft writer")

    monkeypatch.setattr(GraphConfiguration, "save_editable_model_draft", _must_not_write)
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
