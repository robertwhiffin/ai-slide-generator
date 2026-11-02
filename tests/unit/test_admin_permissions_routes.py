"""Task 4: the admin API behind the Admins tab.

``GET /api/admin/admins``, ``POST /api/admin/admins`` and
``DELETE /api/admin/admins/{permission_id}``
(docs/superpowers/plans/2026-11-02-admin-permissions.md Task 4; spec §5).

Wiring:

- ``TestClient`` on the real ``src.api.main.app`` (no lifespan), with
  ``get_db`` overridden to an in-memory SQLite database (StaticPool,
  ``autoflush=False`` as production's ``get_session_local``). Each request
  gets its own session, closed when the request ends, and every assertion on
  stored state reads the rows back with a fresh session. A route that forgot
  ``db.commit()`` therefore loses its write and fails here.
- The gate is the real ``require_admin``: ``_authz._is_production`` is forced
  True and ``_authz._admin_acl_probe`` is stubbed True (admin) or False. The
  verdict cache is process-global, so it is cleared in setup and teardown.
- ``reset_admin_cache`` is replaced on the name the route module calls
  (``src.api.routes.admin_permissions.reset_admin_cache``) by a recorder that
  shares an event list with an ``after_commit`` listener on each request's
  session, so the tests can see that the reset came after the commit.
- ``get_current_user`` is replaced in the route module, so ``created_by``
  must come from that call (the middleware's dev identity differs).

Until the route module exists those two patches are skipped and the routes
404, which is the expected red.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import ModuleType

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 — register every model before create_all
from src.api.routes import _authz
from src.core.database import Base, get_db
from src.database.models.permission import Permission, PermissionSyncState

ROUTE_MODULE = "src.api.routes.admin_permissions"
ADMINS_URL = "/api/admin/admins"

# The caller as both the gate and the route module see it. Deliberately not the
# middleware's dev identity (DEV_USER_ID / dev@local.dev), so ``created_by``
# can only equal it if the route reads its own ``get_current_user``.
CALLER = "admin-caller@example.com"

CAN_MANAGE_409_DETAIL = (
    "This admin comes from CAN_MANAGE on the app. "
    "Change it in the app's Permissions in Databricks."
)
ADMIN_403_DETAIL = "Admin access required"

ENTRY_KEYS = {
    "identity_type",
    "identity_name",
    "identity_id",
    "sources",
    "manual_permission_id",
    "added_by",
    "added_at",
}
SYNC_KEYS = {"last_attempt_at", "last_success_at", "last_error"}

T_SYNCED = datetime(2026, 11, 2, 8, 0, 0)
T_ADDED = datetime(2026, 11, 2, 8, 30, 0)
T_ATTEMPT = datetime(2026, 11, 2, 9, 15, 0)
T_SUCCESS = datetime(2026, 11, 2, 9, 10, 0)
SYNC_ERROR = (
    "PermissionDenied: apps.ruleSets/get is not allowed for the app's "
    "service principal"
)

_RESET = "reset_admin_cache"
_COMMIT = "commit"


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


@dataclass
class Harness:
    client: TestClient
    factory: sessionmaker
    # "commit" for every commit of a request's session, "reset_admin_cache"
    # for every call of the route module's reset_admin_cache, in call order.
    events: list[str] = field(default_factory=list)

    @property
    def reset_calls(self) -> int:
        return self.events.count(_RESET)


def _import_route_module() -> ModuleType | None:
    """The route module, or None while it does not exist yet (the red phase)."""
    try:
        return importlib.import_module(ROUTE_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name != ROUTE_MODULE:
            raise
        return None


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Iterator[Harness]:
    from src.api.main import app

    _authz.reset_admin_cache()

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    events: list[str] = []

    def _override_get_db() -> Iterator:
        db = factory()
        event.listen(db, "after_commit", lambda _session: events.append(_COMMIT))
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db

    monkeypatch.setattr(_authz, "_is_production", lambda: True)
    monkeypatch.setattr(_authz, "get_current_user", lambda: CALLER)
    monkeypatch.setattr(_authz, "_admin_acl_probe", lambda _user: True)

    route_module = _import_route_module()
    if route_module is not None:
        # raising=True (the default) on purpose: the route module must call
        # these by these names, or the patches would silently miss.
        monkeypatch.setattr(
            route_module, "reset_admin_cache", lambda: events.append(_RESET)
        )
        monkeypatch.setattr(route_module, "get_current_user", lambda: CALLER)

    try:
        yield Harness(client=TestClient(app), factory=factory, events=events)
    finally:
        app.dependency_overrides.clear()
        _authz.reset_admin_cache()
        engine.dispose()


def _make_non_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_authz, "_admin_acl_probe", lambda _user: False)
    _authz.reset_admin_cache()


# ---------------------------------------------------------------------------
# Seeding and read-back, written directly against the tables (independent of
# the store service under the routes).
# ---------------------------------------------------------------------------


def _seed_admin(
    factory: sessionmaker,
    *,
    identity_name: str,
    source: str,
    identity_type: str = "USER",
    identity_id: str | None = None,
    created_by: str | None = None,
    created_at: datetime | None = None,
) -> int:
    values = {
        "resource_type": "app",
        "resource_id": "",
        "identity_type": identity_type,
        "identity_id": identity_id,
        "identity_name": identity_name,
        "identity_key": identity_name.strip().lower(),
        "privilege": "admin",
        "source": source,
        "created_by": created_by,
    }
    if created_at is not None:
        values["created_at"] = created_at
    with factory() as session:
        row = Permission(**values)
        session.add(row)
        session.commit()
        return row.id


def _seed_sync_failure(factory: sessionmaker) -> None:
    with factory() as session:
        session.add(
            PermissionSyncState(
                sync_key="app_can_manage",
                last_attempt_at=T_ATTEMPT,
                last_success_at=None,
                last_error=SYNC_ERROR,
            )
        )
        session.commit()


def _rows(factory: sessionmaker) -> list[dict]:
    """Every ``permissions`` row, read with a fresh session."""
    with factory() as session:
        return [
            dict(m)
            for m in session.execute(
                select(Permission.__table__).order_by(Permission.id)
            ).mappings()
        ]


def _parse_iso(value: object) -> datetime:
    """Parse an ISO 8601 response value to a naive UTC datetime."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _assert_one_reset_after_a_commit(events: list[str]) -> None:
    assert events.count(_RESET) == 1, (
        f"expected exactly one reset_admin_cache call, got events {events}"
    )
    assert _COMMIT in events[: events.index(_RESET)], (
        f"reset_admin_cache ran before db.commit(): events {events}"
    )


def _entries_for(admins: list[dict], identity_type: str, name: str) -> list[dict]:
    return [
        a
        for a in admins
        if a["identity_type"] == identity_type
        and a["identity_name"].strip().lower() == name.strip().lower()
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_non_admin_gets_403_on_every_admin_route(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    manual_id = _seed_admin(
        harness.factory,
        identity_name="lee@x.com",
        source="manual",
        created_by="owner@x.com",
    )
    before = _rows(harness.factory)
    _make_non_admin(monkeypatch)

    responses = {
        "GET": harness.client.get(ADMINS_URL),
        "POST": harness.client.post(
            ADMINS_URL,
            json={
                "identity_type": "USER",
                "identity_name": "mallory@example.com",
                "identity_id": None,
            },
        ),
        "DELETE": harness.client.delete(f"{ADMINS_URL}/{manual_id}"),
    }

    assert {m: r.status_code for m, r in responses.items()} == {
        "GET": 403,
        "POST": 403,
        "DELETE": 403,
    }, {m: r.text for m, r in responses.items()}
    for method, response in responses.items():
        assert response.json()["detail"] == ADMIN_403_DETAIL, method
    assert _rows(harness.factory) == before, "a non-admin request changed rows"
    assert harness.reset_calls == 0


def test_list_returns_merged_entries_and_sync_status(harness: Harness) -> None:
    _seed_admin(
        harness.factory,
        identity_name="sam@x.com",
        source="can_manage_sync",
        created_by="can_manage_sync",
        created_at=T_SYNCED,
    )
    manual_id = _seed_admin(
        harness.factory,
        identity_name="sam@x.com",
        source="manual",
        identity_id="7001",
        created_by="owner@x.com",
        created_at=T_ADDED,
    )
    _seed_admin(
        harness.factory,
        identity_name="Tellr Owners",
        identity_type="GROUP",
        source="can_manage_sync",
        created_by="can_manage_sync",
        created_at=T_SYNCED,
    )
    _seed_sync_failure(harness.factory)

    response = harness.client.get(ADMINS_URL)

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"admins", "sync"}
    admins = body["admins"]
    assert len(admins) == 2, admins

    sams = _entries_for(admins, "USER", "sam@x.com")
    assert len(sams) == 1, f"expected one merged Sam entry, got {sams}"
    sam = sams[0]
    assert set(sam) == ENTRY_KEYS
    assert sam["identity_name"] == "sam@x.com"
    assert sam["identity_id"] == "7001"
    assert sam["sources"] == ["can_manage_sync", "manual"]
    assert sam["manual_permission_id"] == manual_id
    assert sam["added_by"] == "owner@x.com"
    assert _parse_iso(sam["added_at"]) == T_ADDED

    groups = _entries_for(admins, "GROUP", "Tellr Owners")
    assert len(groups) == 1, admins
    group = groups[0]
    assert set(group) == ENTRY_KEYS
    assert group["sources"] == ["can_manage_sync"]
    assert group["manual_permission_id"] is None
    assert group["added_by"] is None
    assert group["added_at"] is None

    sync = body["sync"]
    assert set(sync) == SYNC_KEYS
    assert sync["last_error"] == SYNC_ERROR
    assert sync["last_success_at"] is None
    assert _parse_iso(sync["last_attempt_at"]) == T_ATTEMPT


def test_list_timestamps_carry_utc_offset(harness: Harness) -> None:
    """The DB stores naive UTC, and the browser's ``new Date()`` reads an
    offset-less ISO string as LOCAL time. So every non-null datetime has to
    leave the API with an explicit UTC offset and mean the stored instant."""
    _seed_admin(
        harness.factory,
        identity_name="sam@x.com",
        source="manual",
        created_by="owner@x.com",
        created_at=T_ADDED,
    )
    # A success at T_SUCCESS, then a failed attempt at T_ATTEMPT.
    with harness.factory() as session:
        session.add(
            PermissionSyncState(
                sync_key="app_can_manage",
                last_attempt_at=T_ATTEMPT,
                last_success_at=T_SUCCESS,
                last_error=SYNC_ERROR,
            )
        )
        session.commit()

    response = harness.client.get(ADMINS_URL)

    assert response.status_code == 200, response.text
    body = response.json()
    sams = _entries_for(body["admins"], "USER", "sam@x.com")
    assert len(sams) == 1, body
    sent = {
        "admins[].added_at": (sams[0]["added_at"], T_ADDED),
        "sync.last_attempt_at": (body["sync"]["last_attempt_at"], T_ATTEMPT),
        "sync.last_success_at": (body["sync"]["last_success_at"], T_SUCCESS),
    }
    for label, (value, stored) in sent.items():
        assert isinstance(value, str), f"{label}: expected a string, got {value!r}"
        assert value.endswith(("+00:00", "Z")), (
            f"{label}: {value!r} carries no UTC offset"
        )
        assert datetime.fromisoformat(value.replace("Z", "+00:00")) == stored.replace(
            tzinfo=timezone.utc
        ), f"{label}: {value!r} is not the stored instant {stored} UTC"


def test_add_then_list_shows_added_in_tellr(harness: Harness) -> None:
    response = harness.client.post(
        ADMINS_URL,
        json={
            "identity_type": "USER",
            "identity_name": "priya@example.com",
            "identity_id": "5551",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {"permission_id"}
    permission_id = body["permission_id"]
    assert isinstance(permission_id, int) and not isinstance(permission_id, bool)

    rows = _rows(harness.factory)
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["id"] == permission_id
    assert row["resource_type"] == "app"
    assert row["resource_id"] == ""
    assert row["privilege"] == "admin"
    assert row["source"] == "manual"
    assert row["identity_type"] == "USER"
    assert row["identity_name"] == "priya@example.com"
    assert row["identity_key"] == "priya@example.com"
    assert row["identity_id"] == "5551"
    assert row["created_by"] == CALLER
    _assert_one_reset_after_a_commit(harness.events)

    listed = harness.client.get(ADMINS_URL)

    assert listed.status_code == 200, listed.text
    priyas = _entries_for(listed.json()["admins"], "USER", "priya@example.com")
    assert len(priyas) == 1, listed.json()
    priya = priyas[0]
    assert priya["sources"] == ["manual"]
    assert priya["added_by"] == CALLER
    assert priya["manual_permission_id"] == permission_id
    assert priya["identity_id"] == "5551"
    _parse_iso(priya["added_at"])


def test_add_validation_422(harness: Harness) -> None:
    responses = {
        "type SP": harness.client.post(
            ADMINS_URL,
            json={
                "identity_type": "SP",
                "identity_name": "robot@example.com",
                "identity_id": None,
            },
        ),
        "blank name": harness.client.post(
            ADMINS_URL,
            json={"identity_type": "USER", "identity_name": "  ", "identity_id": None},
        ),
    }

    assert {k: r.status_code for k, r in responses.items()} == {
        "type SP": 422,
        "blank name": 422,
    }, {k: r.text for k, r in responses.items()}
    assert _rows(harness.factory) == []


def test_add_rejects_overlong_identity_fields_422(harness: Harness) -> None:
    """identity_name and identity_id are String(255). SQLite does not enforce
    the length, but Postgres raises and the route would 500, so the API must
    refuse an over-long value with 422 itself."""
    name_256 = "u" * 244 + "@example.com"
    name_255 = "v" * 243 + "@example.com"
    other_255 = "w" * 243 + "@example.com"
    assert (len(name_256), len(name_255), len(other_255)) == (256, 255, 255)

    rejected = {
        "256-char name": harness.client.post(
            ADMINS_URL,
            json={"identity_type": "USER", "identity_name": name_256, "identity_id": None},
        ),
        "256-char id": harness.client.post(
            ADMINS_URL,
            json={
                "identity_type": "USER",
                "identity_name": "priya@example.com",
                "identity_id": "7" * 256,
            },
        ),
    }

    assert {k: r.status_code for k, r in rejected.items()} == {
        "256-char name": 422,
        "256-char id": 422,
    }, {k: r.text for k, r in rejected.items()}
    assert _rows(harness.factory) == []

    accepted = {
        "255-char name": harness.client.post(
            ADMINS_URL,
            json={"identity_type": "USER", "identity_name": name_255, "identity_id": None},
        ),
        "255-char name and id": harness.client.post(
            ADMINS_URL,
            json={
                "identity_type": "USER",
                "identity_name": other_255,
                "identity_id": "8" * 255,
            },
        ),
    }

    assert {k: r.status_code for k, r in accepted.items()} == {
        "255-char name": 201,
        "255-char name and id": 201,
    }, {k: r.text for k, r in accepted.items()}
    assert sorted((r["identity_name"], r["identity_id"]) for r in _rows(harness.factory)) == [
        (name_255, None),
        (other_255, "8" * 255),
    ]


def test_delete_manual_row_204_and_cache_reset(harness: Harness) -> None:
    sync_id = _seed_admin(
        harness.factory,
        identity_name="lee@x.com",
        source="can_manage_sync",
        created_by="can_manage_sync",
    )
    manual_id = _seed_admin(
        harness.factory,
        identity_name="lee@x.com",
        source="manual",
        created_by="owner@x.com",
    )

    response = harness.client.delete(f"{ADMINS_URL}/{manual_id}")

    assert response.status_code == 204, response.text
    assert response.content == b""
    # Only the manual row goes; Lee's CAN_MANAGE row is untouched.
    assert [r["id"] for r in _rows(harness.factory)] == [sync_id]
    _assert_one_reset_after_a_commit(harness.events)


def test_delete_sync_row_409_and_row_kept(harness: Harness) -> None:
    sync_id = _seed_admin(
        harness.factory,
        identity_name="sam@x.com",
        source="can_manage_sync",
        created_by="can_manage_sync",
    )
    before = _rows(harness.factory)

    response = harness.client.delete(f"{ADMINS_URL}/{sync_id}")

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == CAN_MANAGE_409_DETAIL
    assert _rows(harness.factory) == before


def test_delete_missing_404(harness: Harness) -> None:
    from src.api.main import app

    # Without the route a DELETE also 404s (from the router), so first prove
    # the 404 below can only come from the handler.
    registered = {
        (method, route.path)
        for route in app.routes
        for method in (getattr(route, "methods", None) or ())
        if hasattr(route, "path")
    }
    assert ("DELETE", f"{ADMINS_URL}/{{permission_id}}") in registered, (
        "DELETE /api/admin/admins/{permission_id} is not registered on the app"
    )
    kept_id = _seed_admin(
        harness.factory,
        identity_name="lee@x.com",
        source="manual",
        created_by="owner@x.com",
    )
    before = _rows(harness.factory)

    response = harness.client.delete(f"{ADMINS_URL}/{kept_id + 1000}")

    assert response.status_code == 404, response.text
    assert _rows(harness.factory) == before
