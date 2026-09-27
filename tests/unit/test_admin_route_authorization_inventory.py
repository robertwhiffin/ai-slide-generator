"""Task 9: admin route authorization inventory (#271 AC6).

Enumerates every (method, path) pair under /api/admin/agent-definitions from
the live ``src.api.main.app.routes`` and asserts the exact 24-pair set,
``require_admin`` in every route's dependant tree, and single-router ownership.

The non-admin 403 parametric test covers all 24 routes and asserts that
authorization fires before any body is parsed, any manifest prompt text is
serialised in the response, or any service is invoked.

Fix round 1: the require_admin check now scans the full /api/admin namespace
(not just /api/admin/agent-definitions) so an unguarded route registered
directly on ``app`` at any /api/admin/* path is caught.  A second test asserts
the full /api/admin/* route set equals the known 35 pairs.

Known /api/admin/* routes outside agent-definitions (all carry require_admin):
  src.api.routes.admin        — judge-backend (GET, PUT), google-credentials
                                (POST, GET /status, DELETE)
  src.api.routes.admin_usage  — usage/summary, daily, top-users, funnel,
                                retention, heatmap (all GET)
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 — register ORM metadata before create_all
from src.api.routes import _authz
from src.api.routes import agent_definitions as routes_module
from src.api.routes._authz import require_admin
from src.core.database import Base, get_db
from src.core.user_context import set_current_user
from src.services.agent_test_workbench import AgentTestWorkbench
from src.services.graph_configuration import GraphConfiguration
from src.services.graph_definition_manifest import load_graph_v1_manifest

# ---------------------------------------------------------------------------
# The exact 24 (method, path) pairs under /api/admin/agent-definitions (C36).
# ---------------------------------------------------------------------------

EXPECTED_ADMIN_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("DELETE", "/api/admin/agent-definitions/test-cases/{test_case_id}"),
        ("GET", "/api/admin/agent-definitions/model-endpoints"),
        ("GET", "/api/admin/agent-definitions/readiness"),
        ("GET", "/api/admin/agent-definitions/release-preview"),
        ("GET", "/api/admin/agent-definitions/releases"),
        ("GET", "/api/admin/agent-definitions/releases/{version_number}"),
        ("GET", "/api/admin/agent-definitions/releases/{version_number}/comparison"),
        (
            "GET",
            "/api/admin/agent-definitions/releases/{version_number}/rollback-preview",
        ),
        ("GET", "/api/admin/agent-definitions/test-cases"),
        ("GET", "/api/admin/agent-definitions/test-cases/{test_case_id}/runs"),
        ("GET", "/api/admin/agent-definitions/test-runs/{run_id}"),
        ("GET", "/api/admin/agent-definitions/workbench"),
        (
            "POST",
            "/api/admin/agent-definitions/draft/{agent_key}/legacy-prompt-source",
        ),
        (
            "POST",
            "/api/admin/agent-definitions/draft/{agent_key}/model-endpoint-probe",
        ),
        (
            "POST",
            "/api/admin/agent-definitions/draft/{agent_key}/protected-assembly-upgrade",
        ),
        (
            "POST",
            "/api/admin/agent-definitions/draft/{agent_key}/schema-contract-upgrade",
        ),
        ("POST", "/api/admin/agent-definitions/draft/{agent_key}/test-runs"),
        ("POST", "/api/admin/agent-definitions/published/{agent_key}/test-runs"),
        ("POST", "/api/admin/agent-definitions/releases"),
        ("POST", "/api/admin/agent-definitions/releases/{version_number}/rollback"),
        ("POST", "/api/admin/agent-definitions/test-cases"),
        ("POST", "/api/admin/agent-definitions/test-runs/{run_id}/verdict"),
        ("PUT", "/api/admin/agent-definitions/draft/{agent_key}"),
        ("PUT", "/api/admin/agent-definitions/test-cases/{test_case_id}"),
    }
)

# Prefix for the agent-definitions router (used by inventory and 403 tests).
_ADMIN_PREFIX = "/api/admin/agent-definitions"
# Broader prefix used by the full-namespace require_admin sweep (fix round 1).
_ALL_ADMIN_PREFIX = "/api/admin"
_SINGLE_ROUTER_MODULE = "src.api.routes.agent_definitions"
_TEST_USER = "task9-user@example.com"

# ---------------------------------------------------------------------------
# All 35 known /api/admin/* (method, path) pairs — the agent-definitions 24
# plus the 11 routes from src.api.routes.admin and src.api.routes.admin_usage.
# A route registered at /api/admin/* that is absent from this set is a gap
# in the inventory and must be enrolled here before it ships.
# ---------------------------------------------------------------------------

EXPECTED_ALL_ADMIN_ROUTES: frozenset[tuple[str, str]] = frozenset(
    EXPECTED_ADMIN_ROUTES
    | {
        # src.api.routes.admin
        ("DELETE", "/api/admin/google-credentials"),
        ("GET", "/api/admin/google-credentials/status"),
        ("GET", "/api/admin/judge-backend"),
        ("POST", "/api/admin/google-credentials"),
        ("PUT", "/api/admin/judge-backend"),
        # src.api.routes.admin_usage
        ("GET", "/api/admin/usage/daily"),
        ("GET", "/api/admin/usage/funnel"),
        ("GET", "/api/admin/usage/heatmap"),
        ("GET", "/api/admin/usage/retention"),
        ("GET", "/api/admin/usage/summary"),
        ("GET", "/api/admin/usage/top-users"),
    }
)


# ---------------------------------------------------------------------------
# Harness — recipe from test_agent_definition_workbench_routes.py:155 (C36).
# ---------------------------------------------------------------------------


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


def _force_admin(monkeypatch: pytest.MonkeyPatch, *, is_admin: bool) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    set_current_user(_TEST_USER)
    monkeypatch.setattr(_authz, "_admin_acl_probe", lambda _user: is_admin)
    _authz.reset_admin_cache()


def _non_admin_app(
    session_factory: sessionmaker,
    *,
    raise_server_exceptions: bool = False,
) -> TestClient:
    """Build the admin router over SQLite with fake dependency overrides."""
    from src.services.graph_configuration import CatalogRemoteEndpointDraftValidator
    from src.services.model_endpoint_catalog import FakeModelEndpointCatalog
    from src.services.model_endpoint_probe import FakeStructuredOutputProbe

    app = FastAPI()
    app.include_router(routes_module.router)

    def _override_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[routes_module.get_remote_endpoint_draft_validator] = (
        lambda: CatalogRemoteEndpointDraftValidator(FakeModelEndpointCatalog)
    )
    app.dependency_overrides[routes_module.get_structured_output_probe] = (
        lambda: FakeStructuredOutputProbe()
    )
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


# ---------------------------------------------------------------------------
# Inventory tests — structural assertions on the live app.
# ---------------------------------------------------------------------------


def test_app_has_exactly_the_expected_24_admin_route_pairs() -> None:
    """Any route added or removed without updating EXPECTED_ADMIN_ROUTES fails here.

    Enumerates ``src.api.main.app.routes`` at import time so it catches the
    real registered set, not a local router copy.
    """
    from src.api.main import app

    actual = frozenset(
        (method, route.path)
        for route in app.routes
        for method in sorted(getattr(route, "methods", None) or ())
        if hasattr(route, "path") and route.path.startswith(_ADMIN_PREFIX)
    )
    surplus = actual - EXPECTED_ADMIN_ROUTES
    missing = EXPECTED_ADMIN_ROUTES - actual
    assert actual == EXPECTED_ADMIN_ROUTES, (
        f"Route set mismatch — surplus {surplus!r}, missing {missing!r}"
    )


def test_every_api_admin_route_is_in_the_known_set() -> None:
    """A new /api/admin/* route not enrolled in EXPECTED_ALL_ADMIN_ROUTES fails here.

    Scans the full /api/admin namespace (not just /api/admin/agent-definitions)
    so a route registered directly on ``app`` without going through a named
    router is caught.  The surplus/missing diff identifies the gap.
    """
    from src.api.main import app

    actual = frozenset(
        (method, route.path)
        for route in app.routes
        for method in sorted(getattr(route, "methods", None) or ())
        if hasattr(route, "path") and route.path.startswith(_ALL_ADMIN_PREFIX)
    )
    surplus = actual - EXPECTED_ALL_ADMIN_ROUTES
    missing = EXPECTED_ALL_ADMIN_ROUTES - actual
    assert actual == EXPECTED_ALL_ADMIN_ROUTES, (
        f"Admin route set mismatch — surplus (unenrolled) {surplus!r}, "
        f"missing {missing!r}"
    )


def test_every_admin_route_declares_require_admin() -> None:
    """A route that omits require_admin from its dependant tree is an auth hole.

    Scans the full /api/admin namespace (fix round 1: previously only
    /api/admin/agent-definitions) so a route registered directly on ``app``
    at any /api/admin/* path is caught.

    Walks ``route.dependant.dependencies`` (the flat dependency list FastAPI
    builds per-route, which includes the router-level dependency) and asserts
    ``require_admin`` appears on every route.
    """
    from src.api.main import app

    without: list[tuple[str, str]] = []
    for route in app.routes:
        if not (hasattr(route, "path") and route.path.startswith(_ALL_ADMIN_PREFIX)):
            continue
        deps = getattr(getattr(route, "dependant", None), "dependencies", []) or []
        has_admin = any(getattr(d, "call", None) is require_admin for d in deps)
        if not has_admin:
            for method in sorted(getattr(route, "methods", None) or ()):
                without.append((method, route.path))
    assert without == [], f"Routes without require_admin in dependant tree: {without}"


def test_all_admin_routes_are_from_the_one_agent_definitions_router() -> None:
    """A second router at the same prefix would split authorization ownership.

    Checks two things:
    1. Every endpoint's ``__module__`` is the single expected module.
    2. The ``agent_definitions.router`` object owns exactly the 24 expected
       pairs — generalising ``test_graph_release_routes.py:343``.
    """
    from src.api.main import app

    modules = {
        route.endpoint.__module__
        for route in app.routes
        if hasattr(route, "path")
        and route.path.startswith(_ADMIN_PREFIX)
        and hasattr(route, "endpoint")
    }
    unexpected = modules - {_SINGLE_ROUTER_MODULE}
    assert not unexpected, f"Admin routes from unexpected module(s): {unexpected}"

    router_pairs = frozenset(
        (method, route.path)
        for route in routes_module.router.routes
        for method in sorted(getattr(route, "methods", None) or ())
    )
    surplus = router_pairs - EXPECTED_ADMIN_ROUTES
    missing = EXPECTED_ADMIN_ROUTES - router_pairs
    assert router_pairs == EXPECTED_ADMIN_ROUTES, (
        f"Router route set mismatch — surplus {surplus!r}, missing {missing!r}"
    )


# ---------------------------------------------------------------------------
# Non-admin 403 gate — parametric over all 24 routes.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("method", "url"), sorted(EXPECTED_ADMIN_ROUTES))
def test_non_admin_is_denied_before_body_or_service_is_read(
    session_factory: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    url: str,
) -> None:
    """require_admin fires before any body parse, manifest read, or service call.

    Covers all 24 routes so a newly added route cannot silently bypass the gate
    without also triggering the inventory test above.

    The Request.json patch turns any body parse into a hard test failure.
    The GraphConfiguration and AgentTestWorkbench spies turn any service
    invocation into a hard test failure.
    The manifest check proves the response body leaks no prompt text.
    """
    _force_admin(monkeypatch, is_admin=False)
    calls: list[str] = []

    # --- spy on the two services the admin router uses ----------------------

    def _must_not(label: str) -> Any:
        def _refuse(*_a: Any, **_kw: Any) -> None:
            calls.append(label)
            raise AssertionError(f"authorization reached {label!r}")
        return _refuse

    for attr in (
        "read_workbench",
        "publish_draft",
        "preview_release",
        "preview_rollback",
        "compare_with_active",
        "get_draft_legacy_prompt_source",
    ):
        monkeypatch.setattr(
            GraphConfiguration, attr, _must_not(f"GraphConfiguration.{attr}")
        )

    for attr in (
        "list_test_cases",
        "create_test_case",
        "update_test_case",
        "deactivate_test_case",
        "execute_candidate_run",
        "execute_baseline_rerun",
        "get_test_run",
        "list_test_runs",
        "draft_readiness",
    ):
        monkeypatch.setattr(
            AgentTestWorkbench, attr, _must_not(f"AgentTestWorkbench.{attr}")
        )

    # Patch Request.json: any body parse before authorization is a failure.
    async def _must_not_parse(_request: Request) -> Any:
        calls.append("body")
        raise AssertionError("authorization parsed the request body before 403")

    monkeypatch.setattr(Request, "json", _must_not_parse)

    # Load manifest prompt texts BEFORE the call so the cache is warm and
    # we can probe the 403 body for leakage.
    load_graph_v1_manifest.cache_clear()
    manifest = load_graph_v1_manifest()
    prompt_excerpts = [defn.prompt_text[:40] for defn in manifest.definitions]

    with _non_admin_app(session_factory) as client:
        response = client.request(
            method,
            url,
            content=b'{"lock_version":0}',
            headers={"content-type": "application/json"},
        )

    assert calls == [], (
        f"[{method} {url}] services/body were reached before 403: {calls}"
    )
    assert response.status_code == 403, (
        f"[{method} {url}] expected 403, got {response.status_code}: {response.text}"
    )
    body_text = response.text
    for excerpt in prompt_excerpts:
        assert excerpt not in body_text, (
            f"[{method} {url}] manifest prompt text leaked into 403 body: {excerpt!r}"
        )
    assert "endpoint_name" not in body_text, (
        f"[{method} {url}] 'endpoint_name' leaked into 403 body"
    )
    assert "content_hash" not in body_text, (
        f"[{method} {url}] 'content_hash' leaked into 403 body"
    )
