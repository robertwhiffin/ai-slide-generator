"""#269 Task 5: the admin preview and publish routes, on SQLite.

Both handlers live on the one admin router in ``agent_definitions.py`` (C31/C35).
Only the route module's ``_readiness_callable`` is faked (C21): the POST builds the
real ``ApprovalEvidenceGate``, so not-ready and success come from real evidence
(#267's executor on the fake model adapter, #268's verdict writer).
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import create_engine, event, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register the complete ORM metadata
from src.api.routes import _authz
from src.api.routes import agent_definitions as routes
from src.api.schemas import graph_releases as release_schemas
from src.core.database import Base, get_db
from src.core.user_context import set_current_user
from src.database.models.graph_configuration import (
    AgentTestCase,
    GraphDraftAgent,
    GraphRelease,
)
from src.services.agent_runtime import AgentRuntime
from src.services.agent_runtime_identity import RecordingAgentInvocationIdentitySink
from src.services.agent_test_workbench import (
    AgentReadinessItem,
    AgentTestWorkbench,
    DraftReadinessResult,
    TestCaseReadinessItem,
)
from src.services.graph_configuration import (
    CatalogRemoteEndpointDraftValidator,
    DraftValidationIssue,
    GraphConfiguration,
    GraphConfigurationIntegrityError,
    PublicationRejected,
)
from src.services.graph_configuration_content import definition_content_from_row
from src.services.graph_configuration_publication import DIFF_FIELD_NAMES
from src.services.graph_definition_manifest import (
    GRAPH_V1_AGENT_KEYS,
    definition_content_hash,
)
from src.services.graph_release_evidence import ApprovalEvidenceGate
from src.services.model_endpoint_catalog import FakeModelEndpointCatalog
from src.services.persisted_graph_release import PersistedGraphReleaseLoader
from tests.fixtures.deterministic_model_adapter import DeterministicFakeModelAdapter

PREVIEW_URL = "/api/admin/agent-definitions/release-preview"
RELEASES_URL = "/api/admin/agent-definitions/releases"
WORKBENCH_URL = "/api/admin/agent-definitions/workbench"
ADMIN = "task5-admin@example.com"

#: The deterministic readiness the faked ``_readiness_callable`` returns: every
#: value differs from what #268 would compute here, so an embedded body proves it
#: came from the binding.
FAKE_READINESS = DraftReadinessResult(
    draft_lock_version=4242,
    base_release_id=777,
    all_ready=False,
    blocking_agents=("deck_reviewer",),
    agents=tuple(
        AgentReadinessItem(
            agent_key=key,
            candidate_hash="c" * 64,
            is_changed_from_base=key == "deck_reviewer",
            ready=key != "deck_reviewer",
            missing_required_case=False,
            cases=(
                (
                    TestCaseReadinessItem(
                        agent_key=key,
                        test_case_id=999,
                        test_case_name="fake_case",
                        test_case_version=3,
                        status="awaiting_review",
                        blocking=True,
                        run_id=888,
                        run_verdict=None,
                        run_checks_passed=True,
                    ),
                )
                if key == "deck_reviewer"
                else ()
            ),
        )
        for key in GRAPH_V1_AGENT_KEYS
    ),
)


def _json_shape(value: object) -> object:
    if isinstance(value, dict):
        return {key: _json_shape(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_shape(item) for item in value]
    return value


FAKE_READINESS_BODY = _json_shape(dataclasses.asdict(FAKE_READINESS))


# --- harness (copied from test_agent_definition_workbench_routes.py, C53) ----


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
    _backdate_v1(factory)
    try:
        yield factory
    finally:
        engine.dispose()


def _backdate_v1(factory) -> None:
    """SQLite's one-second timestamps: publication must follow v1 strictly (C4)."""
    with factory.begin() as db:  # SQLite has no mutation-guard triggers
        db.execute(
            text(
                "UPDATE graph_release SET effective_from = datetime('now','-1 hour'), "
                "published_at = datetime('now','-1 hour') WHERE version_number = 1"
            )
        )


def _force_admin(monkeypatch: pytest.MonkeyPatch, *, is_admin: bool) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    set_current_user(ADMIN)
    monkeypatch.setattr(_authz, "_admin_acl_probe", lambda _user: is_admin)
    _authz.reset_admin_cache()


class _ReadinessBinding:
    """The faked ``_readiness_callable``: records what it was bound to and when."""

    def __init__(self) -> None:
        self.bound_to: list[object] = []
        self.calls: list[bool] = []

    def __call__(self, workbench):
        self.bound_to.append(workbench)
        return self.readiness

    def readiness(self, session: Session) -> DraftReadinessResult:
        self.calls.append(session.in_transaction())
        return FAKE_READINESS


@pytest.fixture
def readiness(monkeypatch) -> _ReadinessBinding:
    binding = _ReadinessBinding()
    monkeypatch.setattr(routes, "_readiness_callable", binding)
    return binding


def _test_workbench(session_factory) -> AgentTestWorkbench:
    return AgentTestWorkbench(
        runtime=AgentRuntime(
            persisted_release_loader=PersistedGraphReleaseLoader(
                session_factory=session_factory
            ),
            model_adapter=DeterministicFakeModelAdapter(),
            identity_sink=RecordingAgentInvocationIdentitySink(),
        )
    )


def _app(
    session_factory: sessionmaker,
    *,
    raise_server_exceptions: bool = True,
    workbench: AgentTestWorkbench | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(routes.router)

    def _override_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    validator = CatalogRemoteEndpointDraftValidator(FakeModelEndpointCatalog)
    app.dependency_overrides[routes.get_remote_endpoint_draft_validator] = (
        lambda: validator
    )
    resolved = workbench if workbench is not None else _test_workbench(session_factory)
    app.dependency_overrides[routes.get_agent_test_workbench] = lambda: resolved
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


# --- evidence helpers (real #267/#268 writers over HTTP) ----------------------


def _workbench(client: TestClient) -> dict:
    response = client.get(WORKBENCH_URL)
    assert response.status_code == 200
    return response.json()


def _node(body: dict, agent_key: str) -> dict:
    return next(node for node in body["nodes"] if node["agent_key"] == agent_key)


def _save(client: TestClient, agent_key: str, prompt_text: str) -> dict:
    body = _workbench(client)
    draft = _node(body, agent_key)["draft"]
    response = client.put(
        f"/api/admin/agent-definitions/draft/{agent_key}",
        json={
            "lock_version": body["draft"]["lock_version"],
            "candidate": {
                "prompt_text": prompt_text,
                "model": {
                    key: draft["model"][key]
                    for key in ("endpoint_name", "temperature", "max_tokens", "top_p")
                },
            },
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _case_id(session_factory, agent_key: str) -> int:
    with session_factory() as db:
        return db.scalar(
            select(AgentTestCase.id).where(
                AgentTestCase.agent_key == agent_key,
                AgentTestCase.name == f"{agent_key}_required_smoke_v1",
            )
        )


def _approve(client: TestClient, session_factory, agent_key: str) -> int:
    lock = _workbench(client)["draft"]["lock_version"]
    run = client.post(
        f"/api/admin/agent-definitions/draft/{agent_key}/test-runs",
        json={"test_case_id": _case_id(session_factory, agent_key), "lock_version": lock},
    )
    assert run.status_code == 201, run.text
    run_id = run.json()["run_id"]
    verdict = client.post(
        f"/api/admin/agent-definitions/test-runs/{run_id}/verdict",
        json={"verdict": "approved", "notes": None},
    )
    assert verdict.status_code == 200, verdict.text
    return run_id


def _lock(client: TestClient) -> int:
    return _workbench(client)["draft"]["lock_version"]


def _release_count(session_factory) -> int:
    with session_factory() as db:
        return len(list(db.scalars(select(GraphRelease.id))))


def _publish_body(lock: int, note: str = "Tune the architect") -> dict:
    return {"lock_version": lock, "release_note": note}


_TIMESTAMP_KEYS = {"published_at", "effective_from", "effective_to", "updated_at"}


def _utc_naive(value: object) -> object:
    """SQLite reads timestamps back naive while the publish returns the aware
    transaction timestamp; PostgreSQL returns both aware.  Compare instants."""
    if isinstance(value, dict):
        return {
            key: (
                item.removesuffix("Z")
                if key in _TIMESTAMP_KEYS and isinstance(item, str)
                else _utc_naive(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_utc_naive(item) for item in value]
    return value


def _identity(body: dict) -> dict:
    return {
        "release_id": body["active_release"]["release_id"],
        "version_number": body["active_release"]["version_number"],
    }


# --- registration --------------------------------------------------------------


def test_main_app_registers_release_routes():
    """Catches a late or duplicated registration (C35): the real app, not a copy."""
    from src.api.main import app

    pairs = [
        (method, route.path)
        for route in app.routes
        for method in sorted(getattr(route, "methods", None) or ())
    ]
    assert pairs.count(("GET", PREVIEW_URL)) == 1
    assert pairs.count(("POST", RELEASES_URL)) == 1


def test_release_routes_are_on_the_one_admin_router():
    pairs = {
        (method, route.path)
        for route in routes.router.routes
        for method in getattr(route, "methods", set())
    }
    assert {("GET", PREVIEW_URL), ("POST", RELEASES_URL)} <= pairs
    assert routes.router.prefix == "/api/admin/agent-definitions"


# --- authorization before the body or the service -----------------------------


def _forbid_services(monkeypatch, calls: list[str]) -> None:
    def _must_not(name):
        def _refuse(*_args, **_kwargs):
            calls.append(name)
            raise AssertionError(f"authorization reached {name}")

        return _refuse

    async def _must_not_parse_json(_request):
        calls.append("body")
        raise AssertionError("authorization parsed the raw request body")

    monkeypatch.setattr(GraphConfiguration, "publish_draft", _must_not("publish_draft"))
    monkeypatch.setattr(GraphConfiguration, "preview_release", _must_not("preview_release"))
    monkeypatch.setattr(routes, "_readiness_callable", _must_not("_readiness_callable"))
    monkeypatch.setattr(routes.Request, "json", _must_not_parse_json)


@pytest.mark.parametrize(("method", "url"), [("GET", PREVIEW_URL), ("POST", RELEASES_URL)])
def test_non_admin_is_denied_before_the_body_or_any_service(
    session_factory, monkeypatch, method, url
):
    _force_admin(monkeypatch, is_admin=False)
    calls: list[str] = []
    _forbid_services(monkeypatch, calls)
    with _app(session_factory, raise_server_exceptions=False) as client:
        response = client.request(
            method,
            url,
            content=b"{not json; SECRET_NOTE}",
            headers={"content-type": "application/json"},
        )

    assert calls == []
    assert response.status_code == 403
    assert response.json() == {"detail": "Admin access required"}
    assert "SECRET_NOTE" not in response.text


@pytest.mark.parametrize("principal", [None, "", " \t "])
def test_publish_requires_a_nonblank_principal_before_the_body(
    session_factory, monkeypatch, principal
):
    _force_admin(monkeypatch, is_admin=True)
    set_current_user(principal)
    calls: list[str] = []
    _forbid_services(monkeypatch, calls)
    client = _app(session_factory, raise_server_exceptions=False)
    # The admin gate is satisfied, so only the principal gate can refuse.
    client.app.dependency_overrides[routes.require_admin] = lambda: None
    with client:
        response = client.post(
            RELEASES_URL,
            content=b"{not json; should not be parsed}",
            headers={"content-type": "application/json"},
        )

    assert calls == []
    assert response.status_code == 403
    assert response.json() == {"detail": "Authenticated principal required"}


def test_the_actor_is_the_principal_never_the_body(
    session_factory, monkeypatch, readiness
):
    _force_admin(monkeypatch, is_admin=True)
    seen: list[str] = []
    original = GraphConfiguration.publish_draft

    def _spy(self, session, **kwargs):
        seen.append(kwargs["actor"])
        return original(self, session, **kwargs)

    monkeypatch.setattr(GraphConfiguration, "publish_draft", _spy)
    with _app(session_factory) as client:
        response = client.post(
            RELEASES_URL, json={**_publish_body(_lock(client)), "actor": "mallory"}
        )
        assert response.status_code == 422
        assert seen == []
        response = client.post(RELEASES_URL, json=_publish_body(_lock(client)))

    assert response.status_code == 409
    assert seen == [ADMIN]


# --- 422 invalid_publication ---------------------------------------------------


def _invalid(*errors: tuple[str, str, str]) -> dict:
    return {
        "code": "invalid_publication",
        "errors": [
            {"field": field, "code": code, "message": message}
            for field, code, message in errors
        ],
    }


def test_malformed_json_is_the_exact_invalid_publication_422(
    session_factory, monkeypatch, readiness
):
    _force_admin(monkeypatch, is_admin=True)
    calls: list[str] = []
    monkeypatch.setattr(
        GraphConfiguration, "publish_draft", lambda *a, **k: calls.append("publish")
    )
    with _app(session_factory) as client:
        response = client.post(
            RELEASES_URL, content=b"{not json", headers={"content-type": "application/json"}
        )

    assert response.status_code == 422
    assert response.json() == _invalid(
        ("$", "invalid_json", "Request body must be valid JSON.")
    )
    assert calls == []


_FIELD_REQUIRED = "Field required"
_BAD_BODIES = [
    (
        "extra_key",
        {"lock_version": 0, "release_note": "n", "force": True},
        [("force", "extra_forbidden", "Extra inputs are not permitted")],
    ),
    (
        "string_lock",
        {"lock_version": "0", "release_note": "n"},
        [("lock_version", "strict_type", "Input should be a valid integer")],
    ),
    (
        "bool_lock",
        {"lock_version": True, "release_note": "n"},
        [("lock_version", "strict_type", "Input should be a valid integer")],
    ),
    (
        "float_lock",
        {"lock_version": 1.0, "release_note": "n"},
        [("lock_version", "strict_type", "Input should be a valid integer")],
    ),
    (
        "missing_note",
        {"lock_version": 0},
        [("release_note", "strict_type", _FIELD_REQUIRED)],
    ),
    (
        "non_string_note",
        {"lock_version": 0, "release_note": 7},
        [("release_note", "strict_type", "Input should be a valid string")],
    ),
    (
        "everything_wrong_in_field_order",
        {"release_note": None, "lock_version": "x", "extra": 1},
        [
            ("lock_version", "strict_type", "Input should be a valid integer"),
            ("release_note", "strict_type", "Input should be a valid string"),
            ("extra", "extra_forbidden", "Extra inputs are not permitted"),
        ],
    ),
    (
        "not_an_object",
        ["lock_version", 0],
        [
            (
                "$",
                "strict_type",
                "Input should be a valid dictionary or instance of PublishReleaseRequest",
            )
        ],
    ),
]


@pytest.mark.parametrize(
    ("body", "errors"),
    [case[1:] for case in _BAD_BODIES],
    ids=[case[0] for case in _BAD_BODIES],
)
def test_a_bad_body_is_the_ordered_invalid_publication_422(
    session_factory, monkeypatch, readiness, body, errors
):
    _force_admin(monkeypatch, is_admin=True)
    calls: list[str] = []
    monkeypatch.setattr(
        GraphConfiguration, "publish_draft", lambda *a, **k: calls.append("publish")
    )
    with _app(session_factory) as client:
        response = client.post(RELEASES_URL, json=body)

    assert response.status_code == 422
    assert response.json() == _invalid(*errors)
    assert calls == []


@pytest.mark.parametrize("note", ["", "   ", "\n\t "])
def test_a_blank_note_is_the_exact_service_422(session_factory, monkeypatch, readiness, note):
    _force_admin(monkeypatch, is_admin=True)
    with _app(session_factory) as client:
        _save(client, "architect", "A tuned architect prompt.")
        response = client.post(RELEASES_URL, json=_publish_body(_lock(client), note))

    assert response.status_code == 422
    assert response.json() == _invalid(
        ("release_note", "blank", "Release note must not be blank.")
    )
    assert _release_count(session_factory) == 1
    assert readiness.calls == []


def test_a_2001_character_note_is_the_exact_too_long_422(
    session_factory, monkeypatch, readiness
):
    _force_admin(monkeypatch, is_admin=True)
    with _app(session_factory) as client:
        too_long = client.post(RELEASES_URL, json=_publish_body(_lock(client), "n" * 2001))
        at_cap = client.post(RELEASES_URL, json=_publish_body(_lock(client), "n" * 2000))

    assert too_long.status_code == 422
    assert too_long.json() == _invalid(
        ("release_note", "too_long", "Release note must be at most 2000 characters.")
    )
    # 2000 passes validation and reaches the lock (nothing changed here).
    assert at_cap.status_code == 409
    assert at_cap.json()["code"] == "nothing_to_publish"


def test_a_negative_lock_is_the_service_lock_rule_422(session_factory, monkeypatch, readiness):
    """The lock range is ``_lock_version_issues``' rule, not a second wire rule (C36)."""
    _force_admin(monkeypatch, is_admin=True)
    with _app(session_factory) as client:
        response = client.post(RELEASES_URL, json=_publish_body(-1, "  "))

    assert response.status_code == 422
    assert response.json() == _invalid(
        ("lock_version", "out_of_range", "Lock version must be greater than or equal to 0."),
        ("release_note", "blank", "Release note must not be blank."),
    )


def test_an_invalid_candidate_is_the_verbatim_prefixed_422(
    session_factory, monkeypatch, readiness
):
    _force_admin(monkeypatch, is_admin=True)
    with session_factory.begin() as db:
        row = db.scalar(select(GraphDraftAgent).where(GraphDraftAgent.agent_key == "builder"))
        row.endpoint_name = "https://x/y"
        row.candidate_hash = definition_content_hash(definition_content_from_row(row))
    with _app(session_factory) as client:
        response = client.post(RELEASES_URL, json=_publish_body(_lock(client)))

    assert response.status_code == 422
    assert response.json() == _invalid(
        (
            "definitions.builder.candidate.model.endpoint_name",
            "endpoint_url_not_allowed",
            "Endpoint must be a Databricks endpoint name, not a URL.",
        )
    )
    assert _release_count(session_factory) == 1


def test_an_actor_rejection_is_the_principal_403_not_a_client_422(
    session_factory, monkeypatch, readiness
):
    _force_admin(monkeypatch, is_admin=True)

    def _reject(*_args, **_kwargs):
        raise PublicationRejected(
            DraftValidationIssue("actor", "blank", "Actor must not be blank.")
        )

    monkeypatch.setattr(GraphConfiguration, "publish_draft", _reject)
    with _app(session_factory) as client:
        response = client.post(RELEASES_URL, json=_publish_body(0))

    assert response.status_code == 403
    assert response.json() == {"detail": "Authenticated principal required"}


# --- 409 outcomes ---------------------------------------------------------------


def test_a_stale_lock_is_the_exact_stale_publication_409(
    session_factory, monkeypatch, readiness
):
    _force_admin(monkeypatch, is_admin=True)
    with _app(session_factory) as client:
        stale = _lock(client)
        _save(client, "architect", "A tuned architect prompt.")
        current = _workbench(client)
        response = client.post(RELEASES_URL, json=_publish_body(stale))

    assert response.status_code == 409
    assert response.json() == {
        "code": "stale_publication",
        "expected_lock_version": stale,
        "current_lock_version": stale + 1,
        "active_release": _identity(current),
        "draft": current["draft"],
    }
    assert readiness.calls == []
    assert _release_count(session_factory) == 1


def test_an_unchanged_draft_is_the_exact_nothing_to_publish_409(
    session_factory, monkeypatch, readiness
):
    _force_admin(monkeypatch, is_admin=True)
    with _app(session_factory) as client:
        current = _workbench(client)
        response = client.post(RELEASES_URL, json=_publish_body(current["draft"]["lock_version"]))

    assert response.status_code == 409
    assert response.json() == {
        "code": "nothing_to_publish",
        "active_release": _identity(current),
        "draft": current["draft"],
    }
    assert readiness.calls == []


def test_a_changed_role_without_approval_is_the_exact_not_ready_409(
    session_factory, monkeypatch, readiness
):
    _force_admin(monkeypatch, is_admin=True)
    with _app(session_factory) as client:
        _save(client, "architect", "A tuned architect prompt.")
        response = client.post(RELEASES_URL, json=_publish_body(_lock(client)))

    assert response.status_code == 409
    assert response.json() == {
        "code": "publication_not_ready",
        "gaps": [
            {
                "agent_key": "architect",
                "test_case_id": _case_id(session_factory, "architect"),
                "code": "no_eligible_approval",
            }
        ],
        "readiness": FAKE_READINESS_BODY,
    }
    # Called once, inside publication's transaction, before any write (C32).
    assert readiness.calls == [True]
    assert _release_count(session_factory) == 1


def test_a_changed_role_without_a_required_case_is_a_null_case_gap(
    session_factory, monkeypatch, readiness
):
    _force_admin(monkeypatch, is_admin=True)
    with _app(session_factory) as client:
        _save(client, "architect", "A tuned architect prompt.")
        _save(client, "builder", "A tuned builder prompt.")
        builder_run = _approve(client, session_factory, "builder")
        with session_factory.begin() as db:
            db.execute(
                update(AgentTestCase)
                .where(AgentTestCase.agent_key == "architect")
                .values(is_active=False)
            )
        response = client.post(RELEASES_URL, json=_publish_body(_lock(client)))

    assert builder_run is not None
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "publication_not_ready"
    assert body["gaps"] == [
        {"agent_key": "architect", "test_case_id": None, "code": "no_required_case"}
    ]
    assert list(body["gaps"][0]) == ["agent_key", "test_case_id", "code"]
    assert _release_count(session_factory) == 1


# --- 200 published --------------------------------------------------------------


def test_an_approved_change_publishes_the_exact_200_body(
    session_factory, monkeypatch, readiness
):
    _force_admin(monkeypatch, is_admin=True)
    with _app(session_factory) as client:
        before = _workbench(client)
        _save(client, "architect", "A tuned architect prompt.")
        run_id = _approve(client, session_factory, "architect")
        lock = _lock(client)
        response = client.post(RELEASES_URL, json=_publish_body(lock, "Tune the architect"))
        after = _workbench(client)

    assert response.status_code == 200, response.text
    body = response.json()
    assert list(body) == [
        "release",
        "previous_release_id",
        "changed_agents",
        "mappings",
        "evidence",
        "draft",
    ]
    assert _utc_naive(body) == _utc_naive({
        "release": after["active_release"],
        "previous_release_id": before["active_release"]["release_id"],
        "changed_agents": ["architect"],
        "mappings": {
            key: {
                "agent_definition_revision_id": _node(after, key)["published"]["revision_id"],
                "content_hash": _node(after, key)["published"]["content_hash"],
                "reused": key != "architect",
            }
            for key in GRAPH_V1_AGENT_KEYS
        },
        "evidence": [
            {
                "agent_test_run_id": run_id,
                "agent_key": "architect",
                "test_case_id": _case_id(session_factory, "architect"),
                "evidence_kind": "approval",
            }
        ],
        "draft": after["draft"],
    })
    assert list(body["mappings"]) == list(GRAPH_V1_AGENT_KEYS)
    assert body["release"]["version_number"] == 2
    assert body["release"]["release_note"] == "Tune the architect"
    assert body["release"]["published_by"] == ADMIN
    assert body["draft"]["lock_version"] == lock + 1
    assert body["draft"]["base_release_id"] == body["release"]["release_id"]
    for key in GRAPH_V1_AGENT_KEYS:
        if key != "architect":
            assert (
                body["mappings"][key]["agent_definition_revision_id"]
                == _node(before, key)["published"]["revision_id"]
            )
    assert readiness.calls == []


def test_the_route_constructs_the_production_gate_bound_to_the_readiness_callable(
    session_factory, monkeypatch, readiness
):
    _force_admin(monkeypatch, is_admin=True)
    captured: list[ApprovalEvidenceGate] = []
    original_init = ApprovalEvidenceGate.__init__

    def _spy_init(self, *args, **kwargs):
        captured.append(self)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(ApprovalEvidenceGate, "__init__", _spy_init)
    workbench = _test_workbench(session_factory)
    with _app(session_factory, workbench=workbench) as client:
        _save(client, "architect", "A tuned architect prompt.")
        response = client.post(RELEASES_URL, json=_publish_body(_lock(client)))

    assert response.status_code == 409
    (captured_gate,) = captured
    assert type(captured_gate) is ApprovalEvidenceGate
    assert captured_gate._readiness == readiness.readiness
    # The binding was resolved from the route's own workbench dependency.
    assert readiness.bound_to == [workbench]


def test_the_production_readiness_binding_is_the_dependency_workbench(
    session_factory, monkeypatch
):
    """C39: ``readiness_under_parent_lock`` of the ``get_agent_test_workbench``
    dependency, so one override covers runs, verdicts and readiness (Task 8)."""
    _force_admin(monkeypatch, is_admin=True)
    captured: list[ApprovalEvidenceGate] = []
    original_init = ApprovalEvidenceGate.__init__

    def _spy_init(self, *args, **kwargs):
        captured.append(self)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(ApprovalEvidenceGate, "__init__", _spy_init)
    workbench = _test_workbench(session_factory)
    with _app(session_factory, workbench=workbench) as client:
        _save(client, "architect", "A tuned architect prompt.")
        response = client.post(RELEASES_URL, json=_publish_body(_lock(client)))

    (gate,) = captured
    assert gate._readiness == workbench.readiness_under_parent_lock
    assert gate._readiness.__self__ is workbench
    assert response.status_code == 409
    readiness_body = response.json()["readiness"]
    assert readiness_body["blocking_agents"] == ["architect"]
    assert readiness_body["draft_lock_version"] == 1
    assert routes._readiness_callable(workbench) == workbench.readiness_under_parent_lock


# --- 500s -----------------------------------------------------------------------


def test_an_integrity_failure_is_the_existing_500(session_factory, monkeypatch, readiness, caplog):
    _force_admin(monkeypatch, is_admin=True)

    def _broken(*_args, **_kwargs):
        raise GraphConfigurationIntegrityError("published release mapping is incomplete")

    monkeypatch.setattr(GraphConfiguration, "publish_draft", _broken)
    with caplog.at_level(logging.ERROR, logger=routes.logger.name):
        with _app(session_factory) as client:
            response = client.post(RELEASES_URL, json=_publish_body(0))

    assert response.status_code == 500
    assert response.json() == {"detail": "Graph configuration is incomplete"}
    assert any(record.exc_info for record in caplog.records)


def test_a_database_integrity_error_is_never_translated(
    session_factory, monkeypatch, readiness
):
    """#268 C7: an ``IntegrityError`` stays a 500, never a friendly code."""
    _force_admin(monkeypatch, is_admin=True)

    def _violates(*_args, **_kwargs):
        raise IntegrityError("INSERT", {}, Exception("ck_violated"))

    monkeypatch.setattr(GraphConfiguration, "publish_draft", _violates)
    with _app(session_factory, raise_server_exceptions=False) as client:
        response = client.post(RELEASES_URL, json=_publish_body(0))

    assert response.status_code == 500
    assert "code" not in response.text
    assert "ck_violated" not in response.text


def test_an_unknown_outcome_is_a_500(session_factory, monkeypatch, readiness):
    _force_admin(monkeypatch, is_admin=True)
    monkeypatch.setattr(GraphConfiguration, "publish_draft", lambda *a, **k: object())
    with _app(session_factory, raise_server_exceptions=False) as client:
        response = client.post(RELEASES_URL, json=_publish_body(0))

    assert response.status_code == 500


def test_publish_runs_the_service_off_the_event_loop(session_factory, monkeypatch, readiness):
    """C46: publication can wait on L0 behind a save's remote check."""
    _force_admin(monkeypatch, is_admin=True)
    loop_running: list[bool] = []
    original = GraphConfiguration.publish_draft

    def _observing(self, *args, **kwargs):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            loop_running.append(False)
        else:
            loop_running.append(True)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(GraphConfiguration, "publish_draft", _observing)
    with _app(session_factory) as client:
        response = client.post(RELEASES_URL, json=_publish_body(_lock(client)))

    assert response.status_code == 409
    assert loop_running == [False]


# --- the preview ------------------------------------------------------------------


def test_the_preview_is_the_exact_body_for_an_approved_change(
    session_factory, monkeypatch, readiness
):
    _force_admin(monkeypatch, is_admin=True)
    with _app(session_factory) as client:
        before = _workbench(client)
        _save(client, "builder", "A tuned builder prompt.")
        _save(client, "architect", "A tuned architect prompt.")
        response = client.get(PREVIEW_URL)
        after = _workbench(client)

    assert response.status_code == 200, response.text
    body = response.json()
    assert list(body) == [
        "draft",
        "active_release",
        "next_version_number",
        "changed",
        "readiness",
        "validation_issues",
        "publishable",
    ]
    assert body == {
        "draft": after["draft"],
        "active_release": after["active_release"],
        "next_version_number": 2,
        "changed": [
            {
                "agent_key": key,
                "published_revision_id": _node(before, key)["published"]["revision_id"],
                "published_content_hash": _node(before, key)["published"]["content_hash"],
                "candidate_hash": _node(after, key)["draft"]["candidate_hash"],
                "field_diffs": [
                    {
                        "field": "prompt_text",
                        "published": _node(before, key)["published"]["prompt_text"],
                        "candidate": f"A tuned {key} prompt.",
                    }
                ],
            }
            for key in ("architect", "builder")
        ],
        "readiness": FAKE_READINESS_BODY,
        "validation_issues": [],
        # The fake readiness blocks only unchanged deck_reviewer; both changed
        # roles have an active required case; no issues (C22).
        "publishable": True,
    }
    assert readiness.calls == [True]


def test_the_preview_serves_the_services_publishable_verbatim(
    session_factory, monkeypatch, readiness
):
    """One definition of ``publishable`` (C22): the route never recomputes it."""
    _force_admin(monkeypatch, is_admin=True)
    monkeypatch.setattr(
        "src.services.graph_configuration_publication.release_is_publishable",
        lambda **_kwargs: True,
    )
    with _app(session_factory) as client:
        response = client.get(PREVIEW_URL)

    assert response.status_code == 200
    assert response.json()["changed"] == []
    assert response.json()["publishable"] is True


def test_the_preview_serves_validation_issues_and_is_not_publishable(
    session_factory, monkeypatch, readiness
):
    _force_admin(monkeypatch, is_admin=True)
    with session_factory.begin() as db:
        row = db.scalar(select(GraphDraftAgent).where(GraphDraftAgent.agent_key == "builder"))
        row.endpoint_name = "https://x/y"
        row.candidate_hash = definition_content_hash(definition_content_from_row(row))
    with _app(session_factory) as client:
        response = client.get(PREVIEW_URL)

    body = response.json()
    assert response.status_code == 200
    assert [item["agent_key"] for item in body["changed"]] == ["builder"]
    assert [diff["field"] for diff in body["changed"][0]["field_diffs"]] == [
        "model.endpoint_name"
    ]
    assert body["validation_issues"] == [
        {
            "field": "definitions.builder.candidate.model.endpoint_name",
            "code": "endpoint_url_not_allowed",
            "message": "Endpoint must be a Databricks endpoint name, not a URL.",
        }
    ]
    assert body["publishable"] is False


def test_the_preview_integrity_failure_is_the_existing_500(
    session_factory, monkeypatch, readiness
):
    _force_admin(monkeypatch, is_admin=True)

    def _broken(*_args, **_kwargs):
        raise GraphConfigurationIntegrityError(
            "graph configuration parent snapshot is inconsistent"
        )

    monkeypatch.setattr(GraphConfiguration, "preview_release", _broken)
    with _app(session_factory) as client:
        response = client.get(PREVIEW_URL)

    assert response.status_code == 500
    assert response.json() == {"detail": "Graph configuration is incomplete"}


def test_the_preview_reads_off_the_event_loop(session_factory, monkeypatch, readiness):
    _force_admin(monkeypatch, is_admin=True)
    loop_running: list[bool] = []
    original = GraphConfiguration.preview_release

    def _observing(self, *args, **kwargs):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            loop_running.append(False)
        else:
            loop_running.append(True)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(GraphConfiguration, "preview_release", _observing)
    with _app(session_factory) as client:
        response = client.get(PREVIEW_URL)

    assert response.status_code == 200
    assert loop_running == [False]


# --- the wire models -----------------------------------------------------------


def _wire_models() -> list[type[BaseModel]]:
    return [
        value
        for value in vars(release_schemas).values()
        if isinstance(value, type)
        and issubclass(value, BaseModel)
        and value.__module__ == release_schemas.__name__
    ]


def test_every_release_wire_model_forbids_extra_keys():
    models = _wire_models()
    assert {model.__name__ for model in models} >= {
        "FieldDiffResponse",
        "ChangedDefinitionResponse",
        "ReleasePreviewResponse",
        "PublishReleaseRequest",
        "PublishedMappingResponse",
        "ReleaseEvidenceResponse",
        "PublishReleaseSuccessResponse",
        "ReleaseIdentityResponse",
        "StalePublicationResponse",
        "NothingToPublishResponse",
        "PublicationGapResponse",
        "PublicationNotReadyResponse",
        "PublicationValidationErrorResponse",
    }
    for model in models:
        assert model.model_config.get("extra") == "forbid", model.__name__


def test_the_request_is_strict_and_carries_no_second_note_or_lock_rule():
    """C10/C36: the service owns the note cap and the lock range."""
    fields = release_schemas.PublishReleaseRequest.model_fields
    assert list(fields) == ["lock_version", "release_note"]
    assert release_schemas.PublishReleaseRequest.model_config.get("strict") is True
    assert fields["lock_version"].metadata == []
    assert fields["release_note"].metadata == []


def test_the_diff_field_literal_is_the_service_vocabulary():
    literal = release_schemas.FieldDiffResponse.model_fields["field"].annotation
    assert literal.__args__ == DIFF_FIELD_NAMES


def test_the_gap_wire_refuses_a_case_id_that_disagrees_with_its_code():
    gap = release_schemas.PublicationGapResponse
    gap(agent_key="architect", test_case_id=None, code="no_required_case")
    gap(agent_key="architect", test_case_id=3, code="no_eligible_approval")
    for bad in (
        {"agent_key": "architect", "test_case_id": 3, "code": "no_required_case"},
        {"agent_key": "architect", "test_case_id": None, "code": "no_eligible_approval"},
        {"agent_key": "architect", "test_case_id": 3, "code": "stale_hash"},
    ):
        with pytest.raises(ValueError):
            gap(**bad)


def test_the_success_wire_requires_exactly_the_seven_mappings():
    mapping = {"agent_definition_revision_id": 1, "content_hash": "a" * 64, "reused": True}
    with pytest.raises(ValueError):
        release_schemas.PublishReleaseSuccessResponse.model_validate(
            {
                "release": {
                    "release_id": 2,
                    "version_number": 2,
                    "previous_release_id": 1,
                    "restored_from_release_id": None,
                    "release_note": "n",
                    "published_by": ADMIN,
                    "published_at": "2030-01-01T00:00:00Z",
                    "effective_from": "2030-01-01T00:00:00Z",
                    "effective_to": None,
                },
                "previous_release_id": 1,
                "changed_agents": ["architect"],
                "mappings": {key: mapping for key in GRAPH_V1_AGENT_KEYS[:-1]},
                "evidence": [],
                "draft": {
                    "draft_id": 1,
                    "base_release_id": 2,
                    "base_version_number": 2,
                    "lock_version": 3,
                    "updated_by": ADMIN,
                    "updated_at": "2030-01-01T00:00:00Z",
                },
            }
        )
