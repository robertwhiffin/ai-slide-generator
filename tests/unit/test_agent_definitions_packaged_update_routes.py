"""Prompt shipping Task 3: the admin packaged-update status and adopt routes.

``GET  /api/admin/graph-shipping/packaged-update``
``POST /api/admin/graph-shipping/packaged-update/adopt``

SQLite, with #269's fixture (v1 bootstrapped from the packaged manifest, so a
fresh install matches it).  The routes reach the packaged manifest only through
the facade helpers ``read_packaged_update_status`` and ``adopt_packaged_update``,
which import ``load_graph_v1_manifest`` from ``graph_definition_manifest`` at call
time, so a test manifest is installed by patching that module's attribute
(``_install_manifest``).  Every publication after v1 runs under
``install_release_clock`` (SQLite timestamps have one-second resolution).

The client and fixture setup mirror ``test_graph_release_history_routes.py``
(Plan correction C3).  The handlers are on the one admin router in
``agent_definitions.py``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

import src.database.models  # noqa: F401 - register the complete ORM metadata
import src.services.graph_configuration as facade
import src.services.graph_definition_manifest as manifest_module
from src.api.routes import _authz
from src.api.routes import agent_definitions as routes
from src.api.routes import graph_shipping
from src.core.database import get_db
from src.core.user_context import set_current_user
from src.database.models.graph_configuration import GraphRelease
from src.services.graph_configuration import (
    DraftValidationIssue,
    GraphConfiguration,
    PublicationRejected,
)
from src.services.graph_definition_manifest import GRAPH_V1_AGENT_KEYS, GraphV1Manifest
from tests.unit import test_graph_release_publication as publication_tests
from tests.unit.test_graph_configuration_shipping import (
    _manifest,
    _shipped_text,
    _v1_prompt,
    hand_publish_prompt,
)
from tests.unit.test_graph_release_publication import _artifacts, _save_prompt
from tests.unit.test_graph_release_rollback import current_lock, install_release_clock
from tests.unit.test_graph_release_routes import _force_admin, _utc_naive

#: #269's SQLite fixture: in-memory, foreign keys on, v1 bootstrapped.
factory = publication_tests.factory

BASE = "/api/admin/agent-definitions"
SHIPPING_BASE = "/api/admin/graph-shipping"
STATUS_URL = f"{SHIPPING_BASE}/packaged-update"
ADOPT_URL = f"{SHIPPING_BASE}/packaged-update/adopt"
ADMIN = "task5-admin@example.com"  # ``_force_admin``'s principal
#: The installed ``databricks-tellr-app`` version the facade reports
#: (``_with_app_version``).  Neither ``src.__version__`` ("0.1.0") nor "unknown".
APP_VERSION = "8.8.8"
ADOPT_NOTE = f"Adopted shipped version (Tellr {APP_VERSION})"
_OTHERS = ("data_analyst", "build_reviewer", "fixer", "fix_reviewer", "deck_reviewer")
_ISSUE = DraftValidationIssue(
    "definitions.architect.model.endpoint_name", "endpoint_policy", "Endpoint is not allowed."
)
_STATUS_KEYS = [
    "available",
    "differing_agents",
    "blocked_reason",
    "hand_edited_agents",
    "validation_issues",
    "diffs",
    "active_version_number",
    "lock_version",
]


# --- harness -------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_admin_identity() -> Iterator[None]:
    set_current_user(None)
    _authz.reset_admin_cache()
    try:
        yield
    finally:
        set_current_user(None)
        _authz.reset_admin_cache()


class _PassingValidator:
    """A remote endpoint validator that records calls; every endpoint resolves."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def validate(self, content) -> None:
        self.calls.append(content.model.endpoint_name)


def _app(
    factory: sessionmaker,
    *,
    validator: object | None = None,
    raise_server_exceptions: bool = True,
) -> TestClient:
    app = FastAPI()
    app.include_router(routes.router)
    app.include_router(graph_shipping.router)

    def _override_db() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    resolved = _PassingValidator() if validator is None else validator
    app.dependency_overrides[routes.get_remote_endpoint_draft_validator] = lambda: resolved
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def _workbench(client: TestClient) -> dict:
    response = client.get(f"{BASE}/workbench")
    assert response.status_code == 200, response.text
    return response.json()


def _install_manifest(monkeypatch, manifest: GraphV1Manifest) -> None:
    """Where the facade helpers look the loader up (they import it at call time)."""
    monkeypatch.setattr(manifest_module, "load_graph_v1_manifest", lambda: manifest)


def _changed_architect(monkeypatch) -> GraphV1Manifest:
    """The packaged manifest with one changed role: the architect's prompt."""
    manifest = _manifest(architect=_shipped_text("architect", "R"))
    _install_manifest(monkeypatch, manifest)
    return manifest


def _with_app_version(monkeypatch, version: str = APP_VERSION) -> None:
    """The installed ``databricks-tellr-app`` distribution reports ``version``."""
    original = facade.metadata.version

    def _version(name):
        return version if name == "databricks-tellr-app" else original(name)

    monkeypatch.setattr(facade.metadata, "version", _version)


def _release_versions(factory) -> list[int]:
    with factory() as db:
        return sorted(db.scalars(select(GraphRelease.version_number)))


def _status(client: TestClient) -> dict:
    response = client.get(STATUS_URL)
    assert response.status_code == 200, response.text
    body = response.json()
    assert list(body) == _STATUS_KEYS
    return body


def _prompt_diff(published: str, candidate: str) -> dict:
    """One ``FieldDiffResponse``: a role whose only difference is its prompt."""
    return {"field": "prompt_text", "published": published, "candidate": candidate}


def _record_service_calls(monkeypatch, calls: list[str]) -> None:
    """Record (and refuse) any reach into the shipping service or the manifest."""

    def _must_not(name):
        def _refuse(*_args, **_kwargs):
            calls.append(name)
            raise AssertionError(f"the route reached {name}")

        return _refuse

    for name in ("packaged_update_status", "adopt_packaged_manifest"):
        monkeypatch.setattr(GraphConfiguration, name, _must_not(name))
    monkeypatch.setattr(
        manifest_module, "load_graph_v1_manifest", _must_not("load_graph_v1_manifest")
    )


# --- authorization before the body or the service ------------------------------------


@pytest.mark.parametrize(("method", "url"), [("GET", STATUS_URL), ("POST", ADOPT_URL)])
def test_non_admin_is_denied_before_the_body_or_any_service(
    factory, monkeypatch, method, url
):
    _force_admin(monkeypatch, is_admin=False)
    calls: list[str] = []
    _record_service_calls(monkeypatch, calls)

    async def _must_not_parse_json(_request):
        calls.append("body")
        raise AssertionError("authorization parsed the raw request body")

    monkeypatch.setattr(routes.Request, "json", _must_not_parse_json)
    before = _artifacts(factory)
    with _app(factory, raise_server_exceptions=False) as client:
        response = client.request(
            method,
            url,
            content=b'{"lock_version": 0, "note": "SECRET_NOTE"',
            headers={"content-type": "application/json"},
        )

    assert calls == []
    assert response.status_code == 403
    assert response.json() == {"detail": "Admin access required"}
    assert "SECRET_NOTE" not in response.text
    assert _artifacts(factory) == before


@pytest.mark.parametrize("principal", [None, "", " \t "])
def test_adopt_requires_a_nonblank_principal_before_the_body(
    factory, monkeypatch, principal
):
    _force_admin(monkeypatch, is_admin=True)
    set_current_user(principal)
    calls: list[str] = []
    _record_service_calls(monkeypatch, calls)

    async def _must_not_parse_json(_request):
        calls.append("body")
        raise AssertionError("the principal gate parsed the raw request body")

    monkeypatch.setattr(routes.Request, "json", _must_not_parse_json)
    client = _app(factory, raise_server_exceptions=False)
    # The admin gate is satisfied, so only the principal gate can refuse.
    client.app.dependency_overrides[routes.require_admin] = lambda: None
    with client:
        response = client.post(
            ADOPT_URL,
            content=b"{not json; should not be parsed}",
            headers={"content-type": "application/json"},
        )

    assert calls == []
    assert response.status_code == 403
    assert response.json() == {"detail": "Authenticated principal required"}


def test_an_actor_rejection_from_adopt_is_the_principal_403(factory, monkeypatch):
    _force_admin(monkeypatch, is_admin=True)
    _changed_architect(monkeypatch)

    def _reject(*_args, **_kwargs):
        raise PublicationRejected(
            DraftValidationIssue("actor", "blank", "Actor must not be blank.")
        )

    monkeypatch.setattr(GraphConfiguration, "adopt_packaged_manifest", _reject)
    with _app(factory) as client:
        response = client.post(ADOPT_URL, json={"lock_version": current_lock(factory)})

    assert response.status_code == 403
    assert response.json() == {"detail": "Authenticated principal required"}


# --- status ------------------------------------------------------------------------


def test_status_on_a_fresh_install_is_nothing_available(factory, monkeypatch):
    _force_admin(monkeypatch, is_admin=True)
    before = _artifacts(factory)
    with _app(factory) as client:
        workbench = _workbench(client)
        body = _status(client)

    assert body == {
        "available": False,
        "differing_agents": [],
        "blocked_reason": None,
        "hand_edited_agents": [],
        "validation_issues": [],
        "diffs": [],
        "active_version_number": 1,
        "lock_version": workbench["draft"]["lock_version"],
    }
    assert workbench["active_release"]["version_number"] == 1
    assert _artifacts(factory) == before


def test_status_reports_one_changed_role_with_its_diff(factory, monkeypatch):
    _force_admin(monkeypatch, is_admin=True)
    # Two pending draft saves move the lock off 0 and off the active version
    # number, so a swapped or hard-coded field is caught.
    _save_prompt(factory, "fixer", "\n\nPending.", lock=current_lock(factory))
    _save_prompt(factory, "deck_reviewer", "\n\nPending.", lock=current_lock(factory))
    _changed_architect(monkeypatch)
    before = _artifacts(factory)
    with _app(factory) as client:
        workbench = _workbench(client)
        body = _status(client)

    lock = workbench["draft"]["lock_version"]
    assert lock == current_lock(factory) == 2
    assert body == {
        "available": True,
        "differing_agents": ["architect"],
        "blocked_reason": None,
        "hand_edited_agents": [],
        "validation_issues": [],
        "diffs": [
            {
                "agent_key": "architect",
                "field_diffs": [
                    _prompt_diff(_v1_prompt("architect"), _shipped_text("architect", "R"))
                ],
            }
        ],
        "active_version_number": 1,
        "lock_version": lock,
    }
    # The status reads; it writes nothing.
    assert _artifacts(factory) == before


def test_status_on_a_hand_edited_install_is_blocked_and_names_the_role(
    factory, monkeypatch
):
    _force_admin(monkeypatch, is_admin=True)
    install_release_clock(monkeypatch, factory)
    hand_text = _v1_prompt("builder") + "\n\nAn admin's builder."
    hand_publish_prompt(factory, "builder", prompt_text=hand_text)
    _changed_architect(monkeypatch)
    with _app(factory) as client:
        body = _status(client)

    assert body == {
        "available": True,
        # ``GRAPH_V1_AGENT_KEYS`` order, not alphabetical or insertion order.
        "differing_agents": ["architect", "builder"],
        "blocked_reason": "hand_edited",
        "hand_edited_agents": ["builder"],
        "validation_issues": [],
        "diffs": [
            {
                "agent_key": "architect",
                "field_diffs": [
                    _prompt_diff(_v1_prompt("architect"), _shipped_text("architect", "R"))
                ],
            },
            {
                "agent_key": "builder",
                "field_diffs": [_prompt_diff(hand_text, _v1_prompt("builder"))],
            },
        ],
        "active_version_number": 2,
        "lock_version": current_lock(factory),
    }


# --- adopt -------------------------------------------------------------------------


def test_adopt_publishes_the_shipped_version_then_nothing_is_available(
    factory, monkeypatch
):
    _force_admin(monkeypatch, is_admin=True)
    install_release_clock(monkeypatch, factory)
    _with_app_version(monkeypatch)
    # A pending fixer edit, so the rebase reports all three effects.
    _save_prompt(factory, "fixer", "\n\nPending.", lock=current_lock(factory))
    _changed_architect(monkeypatch)
    with _app(factory) as client:
        before = _workbench(client)
        lock = before["draft"]["lock_version"]
        response = client.post(ADOPT_URL, json={"lock_version": lock})
        after = _workbench(client)
        status_after = _status(client)

    assert response.status_code == 200, response.text
    body = response.json()
    assert list(body) == ["release", "changed_agent_keys", "draft_effect"]
    previous = before["active_release"]
    assert _utc_naive(body["release"]) == _utc_naive(after["active_release"])
    release = body["release"]
    assert release["version_number"] == previous["version_number"] + 1 == 2
    assert release["previous_release_id"] == previous["release_id"]
    assert release["restored_from_release_id"] is None
    assert release["published_by"] == ADMIN
    assert release["release_note"] == ADOPT_NOTE
    assert release["effective_to"] is None
    assert body["changed_agent_keys"] == ["architect"]
    assert body["draft_effect"] == {
        "architect": "reset",
        "data_analyst": "unchanged",
        "builder": "unchanged",
        "build_reviewer": "unchanged",
        "fixer": "kept",
        "fix_reviewer": "unchanged",
        "deck_reviewer": "unchanged",
    }
    assert list(body["draft_effect"]) == list(GRAPH_V1_AGENT_KEYS)
    assert after["draft"]["lock_version"] == lock + 1
    assert after["draft"]["updated_by"] == ADMIN
    assert _release_versions(factory) == [1, 2]

    assert status_after == {
        "available": False,
        "differing_agents": [],
        "blocked_reason": None,
        "hand_edited_agents": [],
        "validation_issues": [],
        "diffs": [],
        "active_version_number": 2,
        "lock_version": lock + 1,
    }


def test_adopt_overrides_a_hand_edit_under_the_admin(factory, monkeypatch):
    """A hand edit blocks the startup ship but never the adopt."""
    _force_admin(monkeypatch, is_admin=True)
    install_release_clock(monkeypatch, factory)
    _with_app_version(monkeypatch)
    hand_publish_prompt(factory, "builder")
    _changed_architect(monkeypatch)
    with _app(factory) as client:
        assert _status(client)["blocked_reason"] == "hand_edited"
        response = client.post(ADOPT_URL, json={"lock_version": current_lock(factory)})
        status_after = _status(client)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["release"]["version_number"] == 3
    assert body["release"]["published_by"] == ADMIN
    assert body["release"]["release_note"] == ADOPT_NOTE
    assert body["changed_agent_keys"] == ["architect", "builder"]
    assert body["draft_effect"] == {
        "architect": "reset",
        "builder": "reset",
        **{key: "unchanged" for key in _OTHERS},
    }
    assert (status_after["available"], status_after["active_version_number"]) == (False, 3)


def test_a_stale_lock_is_the_exact_stale_publication_409(factory, monkeypatch):
    _force_admin(monkeypatch, is_admin=True)
    _save_prompt(factory, "fixer", "\n\nPending.", lock=current_lock(factory))
    _changed_architect(monkeypatch)
    lock = current_lock(factory)
    assert lock == 1
    before = _artifacts(factory)
    with _app(factory) as client:
        workbench = _workbench(client)
        responses = {
            sent: client.post(ADOPT_URL, json={"lock_version": sent})
            for sent in (lock - 1, lock + 1)
        }

    for sent, response in responses.items():
        assert response.status_code == 409, (sent, response.text)
        assert _utc_naive(response.json()) == _utc_naive(
            {
                "code": "stale_publication",
                "expected_lock_version": sent,
                "current_lock_version": lock,
                "active_release": {
                    "release_id": workbench["active_release"]["release_id"],
                    "version_number": 1,
                },
                "draft": workbench["draft"],
            }
        )
    assert _artifacts(factory) == before


def test_nothing_to_adopt_is_the_exact_409(factory, monkeypatch):
    """The packaged manifest is the one v1 was bootstrapped from."""
    _force_admin(monkeypatch, is_admin=True)
    before = _artifacts(factory)
    with _app(factory) as client:
        response = client.post(ADOPT_URL, json={"lock_version": current_lock(factory)})

    assert response.status_code == 409
    assert response.json() == {"code": "nothing_to_adopt"}
    assert _artifacts(factory) == before


def test_invalid_packaged_content_is_the_exact_422_and_the_status_says_so(
    factory, monkeypatch
):
    _force_admin(monkeypatch, is_admin=True)
    monkeypatch.setattr(
        GraphConfiguration, "_candidate_contents_issues", lambda self, contents: [_ISSUE]
    )
    _changed_architect(monkeypatch)
    before = _artifacts(factory)
    issue = {"field": _ISSUE.field, "code": _ISSUE.code, "message": _ISSUE.message}
    with _app(factory) as client:
        response = client.post(ADOPT_URL, json={"lock_version": current_lock(factory)})
        body = _status(client)

    assert response.status_code == 422
    assert response.json() == {"code": "packaged_invalid", "errors": [issue]}
    assert _artifacts(factory) == before
    assert body["available"] is True
    assert body["blocked_reason"] == "invalid"
    assert body["validation_issues"] == [issue]
    assert body["differing_agents"] == ["architect"]


_BAD_BODIES = [
    (
        "malformed_json",
        b"{not json",
        [("$", "invalid_json", "Request body must be valid JSON.")],
    ),
    (
        "unknown_key",
        {"lock_version": "LOCK", "force": True},
        [("force", "extra_forbidden", "Extra inputs are not permitted")],
    ),
    (
        # The actor is the principal, never the body.
        "actor_key",
        {"lock_version": "LOCK", "actor": "mallory@example.com"},
        [("actor", "extra_forbidden", "Extra inputs are not permitted")],
    ),
    (
        # The release note is the server's.
        "release_note_key",
        {"lock_version": "LOCK", "release_note": "My own note"},
        [("release_note", "extra_forbidden", "Extra inputs are not permitted")],
    ),
    (
        "string_lock",
        {"lock_version": "1"},
        [("lock_version", "strict_type", "Input should be a valid integer")],
    ),
    (
        "bool_lock",
        {"lock_version": True},
        [("lock_version", "strict_type", "Input should be a valid integer")],
    ),
    (
        "missing_lock",
        {},
        [("lock_version", "strict_type", "Field required")],
    ),
]


@pytest.mark.parametrize(
    ("body", "errors"),
    [case[1:] for case in _BAD_BODIES],
    ids=[case[0] for case in _BAD_BODIES],
)
def test_a_bad_body_is_a_422_before_the_service(factory, monkeypatch, body, errors):
    """The body is exactly ``{"lock_version": int}``: strict, extra keys forbidden.

    The service and the manifest loader refuse, so a body the route wrongly
    accepted fails loudly.  The top-level ``code`` is the route's own request
    code, never the packaged-content one.
    """
    _force_admin(monkeypatch, is_admin=True)
    _save_prompt(factory, "fixer", "\n\nPending.", lock=current_lock(factory))
    lock = current_lock(factory)
    if isinstance(body, dict) and body.get("lock_version") == "LOCK":
        body = {**body, "lock_version": lock}
    calls: list[str] = []
    _record_service_calls(monkeypatch, calls)
    before = _artifacts(factory)
    with _app(factory) as client:
        if isinstance(body, bytes):
            response = client.post(
                ADOPT_URL, content=body, headers={"content-type": "application/json"}
            )
        else:
            response = client.post(ADOPT_URL, json=body)

    assert response.status_code == 422, response.text
    payload = response.json()
    assert list(payload) == ["code", "errors"]
    assert isinstance(payload["code"], str)
    assert payload["code"] != "packaged_invalid"
    assert payload["errors"] == [
        {"field": field, "code": code, "message": message}
        for field, code, message in errors
    ]
    assert calls == []
    assert _artifacts(factory) == before


def test_a_service_request_rejection_is_the_422_with_its_errors(factory, monkeypatch):
    """A non-actor ``PublicationRejected`` (the service owns the lock range) is a
    422 carrying the service's issues, in the same envelope as a bad body."""
    _force_admin(monkeypatch, is_admin=True)
    _changed_architect(monkeypatch)
    before = _artifacts(factory)
    with _app(factory) as client:
        response = client.post(ADOPT_URL, json={"lock_version": -1})
        unknown_key = client.post(
            ADOPT_URL, json={"lock_version": current_lock(factory), "force": True}
        )

    assert response.status_code == 422, response.text
    payload = response.json()
    assert list(payload) == ["code", "errors"]
    assert payload["errors"] == [
        {
            "field": "lock_version",
            "code": "out_of_range",
            "message": "Lock version must be greater than or equal to 0.",
        }
    ]
    assert unknown_key.status_code == 422
    assert payload["code"] == unknown_key.json()["code"] != "packaged_invalid"
    assert _artifacts(factory) == before


# --- threadpool, and no model or remote work -----------------------------------------


def test_both_routes_run_the_service_off_the_event_loop(factory, monkeypatch):
    """Adopt takes L0 exclusive and status the shared parent lock: either can wait."""
    _force_admin(monkeypatch, is_admin=True)
    install_release_clock(monkeypatch, factory)
    _changed_architect(monkeypatch)
    loop_running: list[tuple[str, bool]] = []

    def _observing(name):
        original = getattr(GraphConfiguration, name)

        def _observe(self, *args, **kwargs):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                loop_running.append((name, False))
            else:
                loop_running.append((name, True))
            return original(self, *args, **kwargs)

        return _observe

    for name in ("packaged_update_status", "adopt_packaged_manifest"):
        monkeypatch.setattr(GraphConfiguration, name, _observing(name))
    with _app(factory) as client:
        assert client.get(STATUS_URL).status_code == 200
        response = client.post(ADOPT_URL, json={"lock_version": current_lock(factory)})

    assert response.status_code == 200, response.text
    assert loop_running == [
        ("packaged_update_status", False),
        ("adopt_packaged_manifest", False),
    ]


def _raising(name: str):
    def _dependency():
        raise AssertionError(f"{name} must not be resolved by this route")

    return _dependency


def test_the_packaged_update_routes_do_no_model_or_remote_work(factory, monkeypatch):
    """Shipping makes no model, runtime or remote-endpoint call at all."""
    _force_admin(monkeypatch, is_admin=True)
    install_release_clock(monkeypatch, factory)
    _changed_architect(monkeypatch)
    client = _app(factory)
    for dependency in (
        routes.get_remote_endpoint_draft_validator,
        routes.get_model_endpoint_catalog,
        routes.get_structured_output_probe,
        routes.get_agent_test_workbench,
    ):
        client.app.dependency_overrides[dependency] = _raising(dependency.__name__)
    with client:
        assert client.get(STATUS_URL).status_code == 200
        response = client.post(ADOPT_URL, json={"lock_version": current_lock(factory)})

    assert response.status_code == 200, response.text
