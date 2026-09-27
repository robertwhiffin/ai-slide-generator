"""#270 Task 6: the admin history, comparison, rollback-preview and rollback routes.

SQLite, with #269's real ``publish_draft`` and ``_NoEvidenceGate`` for v2-v4.
Every publication (and the rollback) runs under Task 2's ``install_release_clock``
(Correction 1), and every release id is ``version + 10`` (``offset_release_ids``),
so no id equals a version number: a route that resolves a version by id is RED.

The handlers are on the one admin router in ``agent_definitions.py`` (C37).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, TypeAdapter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

import src.database.models  # noqa: F401 - register the complete ORM metadata
from src.api.routes import _authz
from src.api.routes import agent_definitions as routes
from src.api.schemas import graph_release_history as history_schemas
from src.api.schemas import graph_releases as release_schemas
from src.core.database import get_db
from src.core.user_context import set_current_user
from src.database.models.graph_configuration import AgentTestRun, GraphRelease
from src.services.graph_configuration import (
    DraftValidationIssue,
    GraphConfiguration,
    GraphConfigurationIntegrityError,
    PublicationRejected,
)
from src.services.graph_configuration_content import as_utc_aware
from src.services.graph_definition_manifest import GRAPH_V1_AGENT_KEYS
from src.services.graph_release_history import read_release_detail
from src.services.model_endpoint_catalog import EndpointValidationFailure
from tests.unit import test_graph_release_publication as publication_tests
from tests.unit.test_graph_release_rollback import (
    RELEASE_ID_OFFSET,
    _incompatible_bundles,
    _link_v2_runs,
    build_v2_v3_v4,
    current_lock,
    mapping,
    publish,
    refs,
    save_prompt_text,
)
from tests.unit.test_graph_release_routes import _force_admin, _utc_naive

#: #269's SQLite fixture: in-memory, foreign keys on, v1 bootstrapped.
factory = publication_tests.factory

BASE = "/api/admin/agent-definitions"
RELEASES_URL = f"{BASE}/releases"
ADMIN = "task5-admin@example.com"  # ``_force_admin``'s principal
NOTE = "Emergency: back to Graph Version 2"
OFFSET = RELEASE_ID_OFFSET
_OTHERS = ("data_analyst", "build_reviewer", "fixer", "fix_reviewer", "deck_reviewer")
_TS = TypeAdapter(datetime)
#: ``_link_v2_runs``' runs in (Graph role order, test case id, run id) order: the
#: run ids are created in another order, so a sort by id alone is RED.
_EVIDENCE_ORDER = ("architect_first", "architect_second", "architect_other", "builder")


def detail_url(version) -> str:
    return f"{RELEASES_URL}/{version}"


def comparison_url(version) -> str:
    return f"{RELEASES_URL}/{version}/comparison"


def preview_url(version) -> str:
    return f"{RELEASES_URL}/{version}/rollback-preview"


def rollback_url(version) -> str:
    return f"{RELEASES_URL}/{version}/rollback"


_READ_URLS = (RELEASES_URL, detail_url(2), comparison_url(2), preview_url(2))


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
    """The preview's remote endpoint validator: records calls, every endpoint resolves."""

    def __init__(self, failing: bool = False) -> None:
        self.failing = failing
        self.calls: list[str] = []

    def validate(self, content) -> None:
        self.calls.append(content.model.endpoint_name)
        if self.failing:
            raise EndpointValidationFailure(
                "endpoint_unavailable", "Endpoint is unavailable.", True
            )


def _app(
    factory: sessionmaker,
    *,
    validator: object | None = None,
    raise_server_exceptions: bool = True,
) -> TestClient:
    app = FastAPI()
    app.include_router(routes.router)

    def _override_db() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    resolved = _PassingValidator() if validator is None else validator
    app.dependency_overrides[routes.get_remote_endpoint_draft_validator] = lambda: resolved
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def _ts(value: datetime | None) -> str | None:
    """The wire's timestamp: stored instants labelled UTC (Task 1 ruling)."""
    return None if value is None else _TS.dump_python(as_utc_aware(value), mode="json")


def _ref(ref) -> dict:
    return {"release_id": ref.release_id, "version_number": ref.version_number}


def _workbench(client: TestClient) -> dict:
    response = client.get(f"{BASE}/workbench")
    assert response.status_code == 200, response.text
    return response.json()


def _rollback_body(lock: int, note: str = NOTE) -> dict:
    return {"lock_version": lock, "release_note": note}


def _release_rows(factory) -> dict[int, GraphRelease]:
    with factory() as db:
        return {row.version_number: row for row in db.scalars(select(GraphRelease))}


def _rollback_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.getMessage() == "graph_release_rollback"]


_STANDARD_RECORD_KEYS = set(
    logging.LogRecord("n", logging.INFO, "p", 1, "m", None, None).__dict__
) | {"message", "asctime", "taskName"}


def _extra(record: logging.LogRecord) -> dict:
    return {k: v for k, v in record.__dict__.items() if k not in _STANDARD_RECORD_KEYS}


def _one_log(caplog, outcome: str, agent_keys: list[str], *, level: str = "INFO") -> None:
    records = _rollback_records(caplog)
    assert len(records) == 1, [(_extra(r), r.levelname) for r in records]
    record = records[0]
    assert record.levelname == level
    assert record.exc_info is None
    assert _extra(record) == {"outcome": outcome, "agent_keys": agent_keys}


@pytest.fixture
def built(factory, monkeypatch) -> dict[str, object]:
    return build_v2_v3_v4(factory, monkeypatch)


# --- registration ----------------------------------------------------------------

_ROUTES = (
    ("GET", RELEASES_URL),
    ("GET", f"{RELEASES_URL}/{{version_number}}"),
    ("GET", f"{RELEASES_URL}/{{version_number}}/comparison"),
    ("GET", f"{RELEASES_URL}/{{version_number}}/rollback-preview"),
    ("POST", f"{RELEASES_URL}/{{version_number}}/rollback"),
)


def test_rollback_routes_register_once_on_the_one_router():
    """C37: the real app, not a copy; each method+path exactly once."""
    from src.api.main import app

    pairs = [
        (method, route.path)
        for route in app.routes
        for method in sorted(getattr(route, "methods", None) or ())
    ]
    for pair in _ROUTES:
        assert pairs.count(pair) == 1, pair
    own = {
        (method, route.path)
        for route in routes.router.routes
        for method in getattr(route, "methods", set())
    }
    assert set(_ROUTES) <= own
    assert routes.router.prefix == BASE


# --- authorization before the body or the service ------------------------------------


def _forbid_services(monkeypatch, calls: list[str]) -> None:
    def _must_not(name):
        def _refuse(*_args, **_kwargs):
            calls.append(name)
            raise AssertionError(f"authorization reached {name}")

        return _refuse

    async def _must_not_parse_json(_request):
        calls.append("body")
        raise AssertionError("authorization parsed the raw request body")

    for name in ("compare_with_active", "preview_rollback", "restore_release"):
        monkeypatch.setattr(GraphConfiguration, name, _must_not(name))
    for name in ("list_release_history", "read_release_detail"):
        monkeypatch.setattr(routes, name, _must_not(name))
    monkeypatch.setattr(routes.Request, "json", _must_not_parse_json)


@pytest.mark.parametrize(
    ("method", "url"),
    [("GET", url) for url in _READ_URLS] + [("POST", rollback_url(2))],
)
def test_non_admin_is_denied_before_the_body_or_any_service(
    factory, monkeypatch, method, url
):
    _force_admin(monkeypatch, is_admin=False)
    calls: list[str] = []
    _forbid_services(monkeypatch, calls)
    with _app(factory, raise_server_exceptions=False) as client:
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
def test_rollback_requires_a_nonblank_principal_before_the_body(
    factory, monkeypatch, principal
):
    _force_admin(monkeypatch, is_admin=True)
    set_current_user(principal)
    calls: list[str] = []
    _forbid_services(monkeypatch, calls)
    client = _app(factory, raise_server_exceptions=False)
    # The admin gate is satisfied, so only the principal gate can refuse.
    client.app.dependency_overrides[routes.require_admin] = lambda: None
    with client:
        response = client.post(
            rollback_url(2),
            content=b"{not json; should not be parsed}",
            headers={"content-type": "application/json"},
        )

    assert calls == []
    assert response.status_code == 403
    assert response.json() == {"detail": "Authenticated principal required"}


def test_the_actor_is_the_principal_never_the_body(factory, monkeypatch, built):
    _force_admin(monkeypatch, is_admin=True)
    seen: list[str] = []
    original = GraphConfiguration.restore_release

    def _spy(self, session, **kwargs):
        seen.append(kwargs["actor"])
        return original(self, session, **kwargs)

    monkeypatch.setattr(GraphConfiguration, "restore_release", _spy)
    lock = current_lock(factory)
    with _app(factory) as client:
        response = client.post(
            rollback_url(2), json={**_rollback_body(lock), "actor": "mallory"}
        )
        assert response.status_code == 422
        assert seen == []
        response = client.post(rollback_url(2), json=_rollback_body(lock))

    assert response.status_code == 200, response.text
    assert seen == [ADMIN]
    assert response.json()["release"]["published_by"] == ADMIN


def test_an_actor_rejection_is_the_principal_403_not_a_client_422(
    factory, monkeypatch, caplog
):
    _force_admin(monkeypatch, is_admin=True)

    def _reject(*_args, **_kwargs):
        raise PublicationRejected(
            DraftValidationIssue("actor", "blank", "Actor must not be blank.")
        )

    monkeypatch.setattr(GraphConfiguration, "restore_release", _reject)
    with caplog.at_level(logging.INFO, logger=routes.logger.name):
        with _app(factory) as client:
            response = client.post(rollback_url(2), json=_rollback_body(0))

    assert response.status_code == 403
    assert response.json() == {"detail": "Authenticated principal required"}
    _one_log(caplog, "rejected", [])


# --- reads -----------------------------------------------------------------------


def _entry(row: GraphRelease, *, is_active, previous, restored_from, restored_by, changed):
    return {
        "release_id": row.id,
        "version_number": row.version_number,
        "is_active": is_active,
        "release_note": row.release_note,
        "published_by": row.published_by,
        "published_at": _ts(row.published_at),
        "effective_from": _ts(row.effective_from),
        "effective_to": _ts(row.effective_to),
        "previous": previous,
        "restored_from": restored_from,
        "restored_by": restored_by,
        "changed_agents": changed,
    }


def _expected_entries(factory) -> dict[int, dict]:
    rows = _release_rows(factory)
    ref = {v: {"release_id": v + OFFSET, "version_number": v} for v in rows}
    return {
        4: _entry(rows[4], is_active=True, previous=ref[3], restored_from=None,
                  restored_by=[], changed=["architect"]),
        3: _entry(rows[3], is_active=False, previous=ref[2], restored_from=None,
                  restored_by=[], changed=["builder"]),
        2: _entry(rows[2], is_active=False, previous=ref[1], restored_from=None,
                  restored_by=[], changed=["architect"]),
        1: _entry(rows[1], is_active=False, previous=None, restored_from=None,
                  restored_by=[], changed=list(GRAPH_V1_AGENT_KEYS)),
    }


def test_the_history_list_is_the_exact_body_newest_first(factory, monkeypatch, built):
    _force_admin(monkeypatch, is_admin=True)
    with _app(factory) as client:
        response = client.get(RELEASES_URL)

    assert response.status_code == 200, response.text
    body = response.json()
    assert list(body) == ["active_release", "releases"]
    entries = _expected_entries(factory)
    assert body == {
        "active_release": {"release_id": 4 + OFFSET, "version_number": 4},
        "releases": [entries[4], entries[3], entries[2], entries[1]],
    }
    assert list(body["releases"][0]) == list(entries[4])
    assert body["releases"][0]["release_note"] == "v4"
    assert body["releases"][0]["published_by"] == "publisher@example.com"


def test_the_detail_is_the_exact_body_with_canonical_content(factory, monkeypatch, built):
    _force_admin(monkeypatch, is_admin=True)
    ids = _link_v2_runs(factory, refs(factory))
    with factory() as db:
        detail = read_release_detail(db, version_number=2)
        runs = {run.id: run for run in db.scalars(select(AgentTestRun))}
    with _app(factory) as client:
        response = client.get(detail_url(2))

    assert response.status_code == 200, response.text
    body = response.json()
    assert list(body) == ["release", "definitions", "evidence"]
    v2_mapping = mapping(factory, 2 + OFFSET)

    def evidence(run_id: int) -> dict:
        run = runs[run_id]
        return {
            "agent_test_run_id": run_id,
            "agent_key": run.agent_key,
            "test_case_id": run.test_case_id,
            "test_case_version": 1,
            "evidence_kind": "approval",
            "source": None,
            "verdict": "approved",
            "verdict_reviewer": run.verdict_reviewer,
            "verdict_at": _ts(run.verdict_at),
            "execution_status": "completed",
            "deterministic_checks_passed": True,
            "run_at": _ts(run.run_at),
        }

    assert body == {
        "release": _expected_entries(factory)[2],
        "definitions": {
            key: {
                "agent_definition_revision_id": v2_mapping[key],
                "content_hash": detail.definitions[key].content_hash,
                "content": detail.definitions[key].content.canonical_payload(),
            }
            for key in GRAPH_V1_AGENT_KEYS
        },
        "evidence": [evidence(ids[name]) for name in _EVIDENCE_ORDER],
    }
    assert list(body["definitions"]) == list(GRAPH_V1_AGENT_KEYS)
    assert body["definitions"]["architect"]["content"]["prompt_text"] == built["v2_architect"]


def test_a_restored_release_detail_names_its_source(factory, monkeypatch, built):
    _force_admin(monkeypatch, is_admin=True)
    ids = _link_v2_runs(factory, refs(factory))
    with _app(factory) as client:
        rolled = client.post(rollback_url(2), json=_rollback_body(current_lock(factory)))
        assert rolled.status_code == 200, rolled.text
        response = client.get(detail_url(5))
        history = client.get(RELEASES_URL).json()

    body = response.json()
    assert body["release"]["restored_from"] == {"release_id": 2 + OFFSET, "version_number": 2}
    assert body["release"]["previous"] == {"release_id": 4 + OFFSET, "version_number": 4}
    assert [
        (e["agent_test_run_id"], e["evidence_kind"], e["source"]) for e in body["evidence"]
    ] == [
        (ids[name], "historical_restore", {"release_id": 2 + OFFSET, "version_number": 2})
        for name in _EVIDENCE_ORDER
    ]
    by_version = {e["version_number"]: e for e in history["releases"]}
    assert by_version[2]["restored_by"] == [{"release_id": 5 + OFFSET, "version_number": 5}]
    assert by_version[5]["changed_agents"] == ["architect", "builder"]


def test_the_comparison_is_the_exact_body(factory, monkeypatch, built):
    _force_admin(monkeypatch, is_admin=True)
    v2, v4 = mapping(factory, 2 + OFFSET), mapping(factory, 4 + OFFSET)
    with _app(factory) as client:
        response = client.get(comparison_url(2))

    assert response.status_code == 200, response.text
    body = response.json()
    assert list(body) == ["active_release", "release", "agents"]
    diffs = {
        "architect": [
            {"field": "prompt_text", "active": built["v4_architect"],
             "historical": built["v2_architect"]}
        ],
        "builder": [
            {"field": "prompt_text", "active": built["v3_builder"],
             "historical": built["v1_texts"]["builder"]}
        ],
    }
    assert body == {
        "active_release": {"release_id": 4 + OFFSET, "version_number": 4},
        "release": {"release_id": 2 + OFFSET, "version_number": 2},
        "agents": [
            {
                "agent_key": key,
                "active_revision_id": v4[key],
                "historical_revision_id": v2[key],
                "same_revision": key in _OTHERS,
                "field_diffs": diffs.get(key, []),
            }
            for key in GRAPH_V1_AGENT_KEYS
        ],
    }


def _expected_agents(factory, built) -> list[dict]:
    with _app(factory) as client:
        return client.get(comparison_url(2)).json()["agents"]


def test_the_rollback_preview_is_the_exact_body(factory, monkeypatch, built):
    _force_admin(monkeypatch, is_admin=True)
    ids = _link_v2_runs(factory, refs(factory))
    save_prompt_text(factory, "fixer", "A pending fixer edit.")
    lock = current_lock(factory)
    validator = _PassingValidator()
    agents = _expected_agents(factory, built)
    with factory() as db:
        runs = {run.id: run for run in db.scalars(select(AgentTestRun))}
    with _app(factory, validator=validator) as client:
        response = client.get(preview_url(2))

    assert response.status_code == 200, response.text
    body = response.json()
    assert list(body) == [
        "source",
        "active_release",
        "next_version_number",
        "lock_version",
        "default_release_note",
        "restorable",
        "blocked",
        "issues",
        "warnings",
        "agents",
        "evidence",
        "draft_effect",
    ]
    assert body == {
        "source": {"release_id": 2 + OFFSET, "version_number": 2},
        "active_release": {"release_id": 4 + OFFSET, "version_number": 4},
        "next_version_number": 5,
        "lock_version": lock,
        "default_release_note": "Roll back to Graph Version 2.",
        "restorable": True,
        "blocked": None,
        "issues": [],
        "warnings": [],
        "agents": agents,
        "evidence": [
            {
                "agent_test_run_id": ids[name],
                "agent_key": runs[ids[name]].agent_key,
                "test_case_id": runs[ids[name]].test_case_id,
            }
            for name in _EVIDENCE_ORDER
        ],
        "draft_effect": {
            "architect": "reset",
            "builder": "reset",
            "data_analyst": "unchanged",
            "build_reviewer": "unchanged",
            "fixer": "kept",
            "fix_reviewer": "unchanged",
            "deck_reviewer": "unchanged",
        },
    }
    assert list(body["draft_effect"]) == list(GRAPH_V1_AGENT_KEYS)
    # C34: the preview composes the dependency's validator, once per distinct endpoint.
    assert validator.calls and len(validator.calls) == len(set(validator.calls))


def test_the_preview_serves_endpoint_warnings_that_never_block(factory, monkeypatch, built):
    _force_admin(monkeypatch, is_admin=True)
    with _app(factory, validator=_PassingValidator(failing=True)) as client:
        body = client.get(preview_url(2)).json()

    assert body["restorable"] is True
    assert body["blocked"] is None
    assert body["warnings"] == [
        {
            "field": f"definitions.{key}.candidate.model.endpoint_name",
            "code": "endpoint_unavailable",
            "message": "Endpoint is unavailable.",
        }
        for key in GRAPH_V1_AGENT_KEYS
    ]


def test_the_preview_serves_blocked_and_issues(factory, monkeypatch, built):
    _force_admin(monkeypatch, is_admin=True)
    with _app(factory) as client:
        active = client.get(preview_url(4)).json()
    assert (active["blocked"], active["restorable"], active["issues"]) == (
        "source_is_active",
        False,
        [],
    )
    _incompatible_bundles(factory, monkeypatch, refs(factory))
    with _app(factory) as client:
        body = client.get(preview_url(3)).json()
    assert body["blocked"] == "incompatible"
    assert body["restorable"] is False
    assert body["issues"][0] == {
        "field": "definitions.architect.protected_assembly.version",
        "code": "protected_bundle_unavailable",
        "message": "Protected assembly bundle is unavailable.",
    }


@pytest.mark.parametrize("version", [99, 2**31, 0, -1])
@pytest.mark.parametrize("url", [detail_url, comparison_url, preview_url])
def test_an_unknown_version_is_the_exact_404(factory, monkeypatch, built, url, version):
    _force_admin(monkeypatch, is_admin=True)
    with _app(factory) as client:
        response = client.get(url(version))

    assert response.status_code == 404
    assert response.json() == {"detail": "Graph Version not found"}


def test_a_version_equal_to_another_release_id_is_resolved_by_version(
    factory, monkeypatch, built
):
    """ids != versions: GET /releases/12 is version 12 (absent), never release id 12."""
    _force_admin(monkeypatch, is_admin=True)
    with _app(factory) as client:
        for url in (detail_url, comparison_url, preview_url):
            assert client.get(url(2 + OFFSET)).status_code == 404
        assert client.post(
            rollback_url(2 + OFFSET), json=_rollback_body(current_lock(factory))
        ).status_code == 404


@pytest.mark.parametrize(
    ("method", "url"),
    [("GET", RELEASES_URL), ("GET", detail_url(2)), ("GET", comparison_url(2)),
     ("GET", preview_url(2))],
)
def test_a_read_integrity_failure_is_the_existing_500(factory, monkeypatch, built, method, url):
    _force_admin(monkeypatch, is_admin=True)

    def _broken(*_args, **_kwargs):
        raise GraphConfigurationIntegrityError("release mapping rows are incomplete")

    for name in ("compare_with_active", "preview_rollback"):
        monkeypatch.setattr(GraphConfiguration, name, _broken)
    for name in ("list_release_history", "read_release_detail"):
        monkeypatch.setattr(routes, name, _broken)
    with _app(factory) as client:
        response = client.request(method, url)

    assert response.status_code == 500
    assert response.json() == {"detail": "Graph configuration is incomplete"}


# --- rollback outcomes -----------------------------------------------------------


def test_a_rollback_restores_the_exact_200_body(factory, monkeypatch, built, caplog):
    _force_admin(monkeypatch, is_admin=True)
    ids = _link_v2_runs(factory, refs(factory))
    lock = current_lock(factory)
    v2_mapping = mapping(factory, 2 + OFFSET)
    with factory() as db:
        runs = {run.id: run for run in db.scalars(select(AgentTestRun))}
        v2_detail = read_release_detail(db, version_number=2)
        hashes = {k: d.content_hash for k, d in v2_detail.definitions.items()}
    with caplog.at_level(logging.INFO, logger=routes.logger.name):
        with _app(factory) as client:
            response = client.post(rollback_url(2), json=_rollback_body(lock))
    with _app(factory) as client:
        after = _workbench(client)

    assert response.status_code == 200, response.text
    body = response.json()
    assert list(body) == [
        "release",
        "restored_from",
        "previous_release_id",
        "changed_agents",
        "mappings",
        "evidence",
        "draft",
        "draft_effect",
    ]
    assert _utc_naive(body) == _utc_naive({
        "release": after["active_release"],
        "restored_from": {"release_id": 2 + OFFSET, "version_number": 2},
        "previous_release_id": 4 + OFFSET,
        "changed_agents": ["architect", "builder"],
        "mappings": {
            key: {
                "agent_definition_revision_id": v2_mapping[key],
                "content_hash": hashes[key],
                "reused": True,
            }
            for key in GRAPH_V1_AGENT_KEYS
        },
        "evidence": [
            {
                "agent_test_run_id": ids[name],
                "agent_key": runs[ids[name]].agent_key,
                "test_case_id": runs[ids[name]].test_case_id,
                "evidence_kind": "historical_restore",
                "source_release_id": 2 + OFFSET,
            }
            for name in _EVIDENCE_ORDER
        ],
        "draft": after["draft"],
        "draft_effect": {
            "architect": "reset",
            "builder": "reset",
            **{key: "unchanged" for key in _OTHERS},
        },
    })
    assert list(body["draft_effect"]) == list(GRAPH_V1_AGENT_KEYS)
    assert body["release"]["release_id"] == 5 + OFFSET
    assert body["release"]["version_number"] == 5
    assert body["release"]["restored_from_release_id"] == 2 + OFFSET
    assert body["release"]["release_note"] == NOTE
    assert body["release"]["published_by"] == ADMIN
    assert body["draft"]["lock_version"] == lock + 1
    assert body["draft"]["base_release_id"] == 5 + OFFSET
    assert built["clock"].call_count == 4

    _one_log(caplog, "restored", ["architect", "builder"])
    # OQ7: no note, actor, hash, release id or version number in the record.
    (record,) = _rollback_records(caplog)
    rendered = [record.getMessage(), *map(str, _extra(record).values())]
    id_texts = [str(v + OFFSET) for v in range(1, 6)]
    forbidden = [NOTE, ADMIN, *hashes.values(), *id_texts, "2", "4", "5"]
    for text in rendered:
        for secret in forbidden:
            assert secret not in text, (secret, text)


def test_a_double_submit_is_the_exact_stale_409_naming_the_new_release(
    factory, monkeypatch, built, caplog
):
    """Review Focus 3: the retry never creates a second version."""
    _force_admin(monkeypatch, is_admin=True)
    lock = current_lock(factory)
    with _app(factory) as client:
        assert client.post(rollback_url(2), json=_rollback_body(lock)).status_code == 200
        with caplog.at_level(logging.INFO, logger=routes.logger.name):
            response = client.post(rollback_url(2), json=_rollback_body(lock))
        after = _workbench(client)

    assert response.status_code == 409
    assert _utc_naive(response.json()) == _utc_naive({
        "code": "stale_rollback",
        "expected_lock_version": lock,
        "current_lock_version": lock + 1,
        "active_release": {"release_id": 5 + OFFSET, "version_number": 5},
        "draft": after["draft"],
    })
    assert sorted(_release_rows(factory)) == [1, 2, 3, 4, 5]
    _one_log(caplog, "stale", [])


def test_a_stale_lock_is_the_exact_stale_409(factory, monkeypatch, built, caplog):
    _force_admin(monkeypatch, is_admin=True)
    lock = current_lock(factory)
    with caplog.at_level(logging.INFO, logger=routes.logger.name):
        with _app(factory) as client:
            response = client.post(rollback_url(2), json=_rollback_body(lock - 1))
            draft = _workbench(client)["draft"]

    assert response.status_code == 409
    assert response.json() == {
        "code": "stale_rollback",
        "expected_lock_version": lock - 1,
        "current_lock_version": lock,
        "active_release": {"release_id": 4 + OFFSET, "version_number": 4},
        "draft": draft,
    }
    assert sorted(_release_rows(factory)) == [1, 2, 3, 4]
    _one_log(caplog, "stale", [])


def test_an_unknown_version_with_a_stale_lock_is_404_not_409(factory, monkeypatch, built, caplog):
    """Task 3a concern 3: not-found precedes the conflict."""
    _force_admin(monkeypatch, is_admin=True)
    with caplog.at_level(logging.INFO, logger=routes.logger.name):
        with _app(factory) as client:
            response = client.post(rollback_url(99), json=_rollback_body(current_lock(factory) + 7))

    assert response.status_code == 404
    assert response.json() == {"detail": "Graph Version not found"}
    _one_log(caplog, "not_found", [])


@pytest.mark.parametrize("version", [99, 2**31, 0, -1])
def test_an_unknown_rollback_version_is_the_exact_404(factory, monkeypatch, built, caplog, version):
    _force_admin(monkeypatch, is_admin=True)
    with caplog.at_level(logging.INFO, logger=routes.logger.name):
        with _app(factory) as client:
            response = client.post(
                rollback_url(version), json=_rollback_body(current_lock(factory))
            )

    assert response.status_code == 404
    assert response.json() == {"detail": "Graph Version not found"}
    assert sorted(_release_rows(factory)) == [1, 2, 3, 4]
    _one_log(caplog, "not_found", [])


def test_rolling_back_to_the_active_release_is_the_exact_409(factory, monkeypatch, built, caplog):
    _force_admin(monkeypatch, is_admin=True)
    with caplog.at_level(logging.INFO, logger=routes.logger.name):
        with _app(factory) as client:
            response = client.post(rollback_url(4), json=_rollback_body(current_lock(factory)))

    assert response.status_code == 409
    assert response.json() == {
        "code": "rollback_source_active",
        "active_release": {"release_id": 4 + OFFSET, "version_number": 4},
    }
    _one_log(caplog, "source_active", [])


def test_rolling_back_to_a_mapping_equal_to_the_active_is_the_exact_409(
    factory, monkeypatch, built, caplog
):
    _force_admin(monkeypatch, is_admin=True)
    save_prompt_text(factory, "architect", built["v2_architect"])
    save_prompt_text(factory, "builder", built["v1_texts"]["builder"])
    publish(factory, "v5 = v2")
    assert mapping(factory, 5 + OFFSET) == mapping(factory, 2 + OFFSET)
    with caplog.at_level(logging.INFO, logger=routes.logger.name):
        with _app(factory) as client:
            response = client.post(rollback_url(2), json=_rollback_body(current_lock(factory)))

    assert response.status_code == 409
    assert response.json() == {
        "code": "rollback_matches_active",
        "active_release": {"release_id": 5 + OFFSET, "version_number": 5},
        "source": {"release_id": 2 + OFFSET, "version_number": 2},
    }
    _one_log(caplog, "matches_active", [])


def test_an_incompatible_release_is_the_exact_422(factory, monkeypatch, built, caplog):
    _force_admin(monkeypatch, is_admin=True)
    _incompatible_bundles(factory, monkeypatch, refs(factory))
    with caplog.at_level(logging.INFO, logger=routes.logger.name):
        with _app(factory) as client:
            response = client.post(rollback_url(3), json=_rollback_body(current_lock(factory)))

    assert response.status_code == 422
    body = response.json()
    assert list(body) == ["code", "source", "errors"]
    assert body["code"] == "rollback_incompatible"
    assert body["source"] == {"release_id": 3 + OFFSET, "version_number": 3}
    assert body["errors"][0] == {
        "field": "definitions.architect.protected_assembly.version",
        "code": "protected_bundle_unavailable",
        "message": "Protected assembly bundle is unavailable.",
    }
    assert [e["field"].split(".")[1] for e in body["errors"]] == list(GRAPH_V1_AGENT_KEYS)
    assert sorted(_release_rows(factory)) == [1, 2, 3, 4]
    _one_log(caplog, "incompatible", sorted(GRAPH_V1_AGENT_KEYS))


def _invalid(*errors: tuple[str, str, str]) -> dict:
    return {
        "code": "invalid_rollback",
        "errors": [
            {"field": field, "code": code, "message": message}
            for field, code, message in errors
        ],
    }


_BAD_BODIES = [
    (
        "malformed_json",
        b"{not json",
        [("$", "invalid_json", "Request body must be valid JSON.")],
    ),
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
        "missing_note",
        {"lock_version": 0},
        [("release_note", "strict_type", "Field required")],
    ),
    (
        "not_an_object",
        ["lock_version", 0],
        [("$", "strict_type", "Input should be a valid dictionary or instance of RollbackRequest")],
    ),
    (
        "blank_note",
        {"lock_version": "LOCK", "release_note": " \n\t"},
        [("release_note", "blank", "Release note must not be blank.")],
    ),
    (
        "too_long_note",
        {"lock_version": "LOCK", "release_note": "x" * 2001},
        [("release_note", "too_long", "Release note must be at most 2000 characters.")],
    ),
    (
        "negative_lock",
        {"lock_version": -1, "release_note": "n"},
        [("lock_version", "out_of_range", "Lock version must be greater than or equal to 0.")],
    ),
]


@pytest.mark.parametrize(
    ("body", "errors"),
    [case[1:] for case in _BAD_BODIES],
    ids=[case[0] for case in _BAD_BODIES],
)
def test_a_bad_body_is_the_exact_invalid_rollback_422(
    factory, monkeypatch, built, caplog, body, errors
):
    _force_admin(monkeypatch, is_admin=True)
    if isinstance(body, dict) and body.get("lock_version") == "LOCK":
        body = {**body, "lock_version": current_lock(factory)}
    with caplog.at_level(logging.INFO, logger=routes.logger.name):
        with _app(factory) as client:
            if isinstance(body, bytes):
                response = client.post(
                    rollback_url(2), content=body, headers={"content-type": "application/json"}
                )
            else:
                response = client.post(rollback_url(2), json=body)

    assert response.status_code == 422
    assert response.json() == _invalid(*errors)
    assert sorted(_release_rows(factory)) == [1, 2, 3, 4]
    _one_log(caplog, "rejected", [])


def test_a_rollback_integrity_failure_is_the_500_with_one_class_only_record(
    factory, monkeypatch, caplog
):
    """C13 + C37: one ERROR record, class name only, no traceback."""
    _force_admin(monkeypatch, is_admin=True)

    def _broken(*_args, **_kwargs):
        raise GraphConfigurationIntegrityError("SECRET release mapping is incomplete")

    monkeypatch.setattr(GraphConfiguration, "restore_release", _broken)
    with caplog.at_level(logging.INFO, logger=routes.logger.name):
        with _app(factory) as client:
            response = client.post(rollback_url(2), json=_rollback_body(0))

    assert response.status_code == 500
    assert response.json() == {"detail": "Graph configuration is incomplete"}
    records = [r for r in caplog.records if r.name == routes.logger.name]
    assert len(records) == 1
    (record,) = records
    assert record.getMessage() == "graph_release_rollback"
    assert record.levelname == "ERROR"
    assert record.exc_info is None
    assert _extra(record) == {
        "outcome": "integrity_error",
        "agent_keys": [],
        "error_class": "GraphConfigurationIntegrityError",
    }
    assert "SECRET" not in caplog.text


def test_a_database_integrity_error_is_never_translated(factory, monkeypatch):
    """#268 C7: an ``IntegrityError`` stays a 500, never a friendly code."""
    _force_admin(monkeypatch, is_admin=True)

    def _violates(*_args, **_kwargs):
        raise IntegrityError("INSERT", {}, Exception("ck_violated"))

    monkeypatch.setattr(GraphConfiguration, "restore_release", _violates)
    with _app(factory, raise_server_exceptions=False) as client:
        response = client.post(rollback_url(2), json=_rollback_body(0))

    assert response.status_code == 500
    assert "code" not in response.text
    assert "ck_violated" not in response.text


def test_an_unknown_outcome_is_a_500(factory, monkeypatch):
    _force_admin(monkeypatch, is_admin=True)
    monkeypatch.setattr(GraphConfiguration, "restore_release", lambda *a, **k: object())
    with _app(factory, raise_server_exceptions=False) as client:
        response = client.post(rollback_url(2), json=_rollback_body(0))

    assert response.status_code == 500


def test_rollback_runs_the_service_off_the_event_loop(factory, monkeypatch, built):
    """C37: rollback can wait on L0 behind a save's remote check."""
    _force_admin(monkeypatch, is_admin=True)
    loop_running: list[bool] = []
    original = GraphConfiguration.restore_release

    def _observing(self, *args, **kwargs):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            loop_running.append(False)
        else:
            loop_running.append(True)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(GraphConfiguration, "restore_release", _observing)
    with _app(factory) as client:
        response = client.post(rollback_url(2), json=_rollback_body(current_lock(factory)))

    assert response.status_code == 200, response.text
    assert loop_running == [False]


# --- no model or remote work (C2 step 4) -----------------------------------------------


def _raising(name: str):
    def _dependency():
        raise AssertionError(f"{name} must not be resolved by this route")

    return _dependency


def test_history_and_rollback_routes_do_no_model_or_remote_work(factory, monkeypatch, built):
    """Every new route except the preview (C34) resolves none of these dependencies."""
    _force_admin(monkeypatch, is_admin=True)
    client = _app(factory)
    for dependency in (
        routes.get_remote_endpoint_draft_validator,
        routes.get_model_endpoint_catalog,
        routes.get_structured_output_probe,
        routes.get_agent_test_workbench,
    ):
        client.app.dependency_overrides[dependency] = _raising(dependency.__name__)
    lock = current_lock(factory)
    with client:
        for url in (RELEASES_URL, detail_url(2), comparison_url(2)):
            assert client.get(url).status_code == 200, url
        response = client.post(rollback_url(2), json=_rollback_body(lock))
    assert response.status_code == 200, response.text


def test_the_preview_resolves_only_the_remote_validator(factory, monkeypatch, built):
    _force_admin(monkeypatch, is_admin=True)
    client = _app(factory)
    for dependency in (
        routes.get_model_endpoint_catalog,
        routes.get_structured_output_probe,
        routes.get_agent_test_workbench,
    ):
        client.app.dependency_overrides[dependency] = _raising(dependency.__name__)
    with client:
        assert client.get(preview_url(2)).status_code == 200


# --- wire models ---------------------------------------------------------------------


def _wire_models(module) -> list[type[BaseModel]]:
    return [
        value
        for value in vars(module).values()
        if isinstance(value, type)
        and issubclass(value, BaseModel)
        and value.__module__ == module.__name__
    ]


def test_every_history_wire_model_forbids_extra_keys():
    models = _wire_models(history_schemas)
    assert {model.__name__ for model in models} >= {
        "ReleaseHistoryEntryResponse",
        "ReleaseHistoryListResponse",
        "ReleaseDefinitionResponse",
        "ReleaseHistoryEvidenceResponse",
        "ReleaseDetailResponse",
        "ReleaseFieldDiffResponse",
        "AgentComparisonResponse",
        "ReleaseComparisonResponse",
        "RollbackPreviewEvidenceResponse",
        "RollbackPreviewResponse",
        "RollbackRequest",
        "RollbackSuccessResponse",
        "RollbackValidationErrorResponse",
        "RollbackIncompatibleResponse",
        "StaleRollbackResponse",
        "RollbackSourceActiveResponse",
        "RollbackMatchesActiveResponse",
    }
    for model in models:
        assert model.model_config.get("extra") == "forbid", model.__name__


def test_the_rollback_request_is_strict_and_carries_no_second_note_or_lock_rule():
    fields = history_schemas.RollbackRequest.model_fields
    assert list(fields) == ["lock_version", "release_note"]
    assert history_schemas.RollbackRequest.model_config.get("strict") is True
    assert fields["lock_version"].metadata == []
    assert fields["release_note"].metadata == []


def test_the_comparison_diff_uses_the_release_diff_vocabulary():
    """C46: its own active/historical keys over #269's ``DiffFieldName``."""
    model = history_schemas.ReleaseFieldDiffResponse
    assert list(model.model_fields) == ["field", "active", "historical"]
    assert model.model_fields["field"].annotation is release_schemas.DiffFieldName


def _evidence(**overrides) -> dict:
    return {
        "agent_test_run_id": 3,
        "agent_key": "architect",
        "test_case_id": 4,
        "evidence_kind": "approval",
        "source_release_id": None,
        **overrides,
    }


def test_release_evidence_pairs_the_kind_with_the_source():
    """C38: ``source_release_id`` is non-null iff the kind is ``historical_restore``."""
    wire = release_schemas.ReleaseEvidenceResponse
    assert list(wire.model_fields) == [
        "agent_test_run_id",
        "agent_key",
        "test_case_id",
        "evidence_kind",
        "source_release_id",
    ]
    wire(**_evidence())
    wire(**_evidence(evidence_kind="historical_restore", source_release_id=12))
    for bad in (
        _evidence(source_release_id=12),
        _evidence(evidence_kind="historical_restore"),
        _evidence(evidence_kind="restore", source_release_id=12),
    ):
        with pytest.raises(ValueError):
            wire(**bad)


def test_history_evidence_pairs_the_kind_with_the_source():
    wire = history_schemas.ReleaseHistoryEvidenceResponse
    common = {
        "agent_test_run_id": 3,
        "agent_key": "architect",
        "test_case_id": 4,
        "test_case_version": 1,
        "verdict": "approved",
        "verdict_reviewer": "r@example.com",
        "verdict_at": "2030-01-01T00:00:00Z",
        "execution_status": "completed",
        "deterministic_checks_passed": True,
        "run_at": "2030-01-01T00:00:00Z",
    }
    source = {"release_id": 12, "version_number": 2}
    wire(**common, evidence_kind="approval", source=None)
    wire(**common, evidence_kind="historical_restore", source=source)
    for kind, bad_source in (("approval", source), ("historical_restore", None)):
        with pytest.raises(ValueError):
            wire(**common, evidence_kind=kind, source=bad_source)


_RELEASE = {
    "release_id": 15,
    "version_number": 5,
    "previous_release_id": 14,
    "restored_from_release_id": 12,
    "release_note": "n",
    "published_by": ADMIN,
    "published_at": "2030-01-01T00:00:00Z",
    "effective_from": "2030-01-01T00:00:00Z",
    "effective_to": None,
}
_DRAFT = {
    "draft_id": 1,
    "base_release_id": 15,
    "base_version_number": 5,
    "lock_version": 3,
    "updated_by": ADMIN,
    "updated_at": "2030-01-01T00:00:00Z",
}
_MAPPING = {"agent_definition_revision_id": 1, "content_hash": "a" * 64, "reused": True}


def _publish_success(evidence: list[dict]) -> dict:
    return {
        "release": _RELEASE,
        "previous_release_id": 14,
        "changed_agents": ["architect"],
        "mappings": {key: _MAPPING for key in GRAPH_V1_AGENT_KEYS},
        "evidence": evidence,
        "draft": _DRAFT,
    }


def test_the_publish_success_wire_stays_approval_only():
    """C38: widening the evidence item does not widen publication."""
    wire = release_schemas.PublishReleaseSuccessResponse
    wire.model_validate(_publish_success([_evidence()]))
    with pytest.raises(ValueError):
        wire.model_validate(
            _publish_success(
                [_evidence(evidence_kind="historical_restore", source_release_id=12)]
            )
        )


def _rollback_success(**overrides) -> dict:
    return {
        "release": _RELEASE,
        "restored_from": {"release_id": 12, "version_number": 2},
        "previous_release_id": 14,
        "changed_agents": ["architect"],
        "mappings": {key: _MAPPING for key in GRAPH_V1_AGENT_KEYS},
        "evidence": [_evidence(evidence_kind="historical_restore", source_release_id=12)],
        "draft": _DRAFT,
        "draft_effect": {key: "unchanged" for key in GRAPH_V1_AGENT_KEYS},
        **overrides,
    }


def test_the_rollback_success_wire_is_restore_only_reused_and_exactly_seven():
    wire = history_schemas.RollbackSuccessResponse
    wire.model_validate(_rollback_success())
    for bad in (
        _rollback_success(evidence=[_evidence()]),
        _rollback_success(
            mappings={
                key: {**_MAPPING, "reused": key != "architect"} for key in GRAPH_V1_AGENT_KEYS
            }
        ),
        _rollback_success(mappings={key: _MAPPING for key in GRAPH_V1_AGENT_KEYS[:-1]}),
        _rollback_success(
            draft_effect={key: "unchanged" for key in reversed(GRAPH_V1_AGENT_KEYS)}
        ),
    ):
        with pytest.raises(ValueError):
            wire.model_validate(bad)


def test_the_preview_wire_derives_restorable_from_blocked():
    wire = history_schemas.RollbackPreviewResponse
    ref = {"release_id": 12, "version_number": 2}
    base = {
        "source": ref,
        "active_release": {"release_id": 14, "version_number": 4},
        "next_version_number": 5,
        "lock_version": 3,
        "default_release_note": "Roll back to Graph Version 2.",
        "restorable": True,
        "blocked": None,
        "issues": [],
        "warnings": [],
        "agents": [
            {
                "agent_key": key,
                "active_revision_id": 1,
                "historical_revision_id": 1,
                "same_revision": True,
                "field_diffs": [],
            }
            for key in GRAPH_V1_AGENT_KEYS
        ],
        "evidence": [],
        "draft_effect": {key: "unchanged" for key in GRAPH_V1_AGENT_KEYS},
    }
    wire.model_validate(base)
    wire.model_validate({**base, "restorable": False, "blocked": "matches_active"})
    for bad in (
        {**base, "restorable": False},
        {**base, "blocked": "incompatible"},
        {**base, "agents": base["agents"][:-1]},
    ):
        with pytest.raises(ValueError):
            wire.model_validate(bad)
