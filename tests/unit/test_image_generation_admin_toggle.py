"""Unit D: the admin on/off switch for AI image generation.

Contract: ``docs/superpowers/plans/2026-11-08-ai-image-generation-CORRECTIONS.md``,
section "Unit D interface (admin toggle)".

Two gates with distinct jobs, both ON by default (user decision, 2026-11-09). The env var
``TELLR_IMAGE_GENERATION_ENABLED`` lets a DEPLOYMENT opt out (``0``/``false``/``no``/``off``);
the admin setting (``workspace_settings`` key ``image_generation_enabled``) lets an admin
turn it off for the workspace. Effective = env AND admin.

  - stored like the Genie One default (``src.services.workspace_settings``);
  - read and written by admins at ``/api/admin/image-generation``; a PUT when the
    deployment lacks the capability is a 409 and stores NOTHING;
  - read per request by the image routes (``/api/images/generate/available`` here;
    the generate/edit/poll gates are covered in ``test_image_generation_routes.py``).

Harness: an in-memory SQLite engine (``StaticPool``) with ``create_all``, and
``src.core.database.get_session_local`` patched onto it so ``get_db`` and
``get_db_session`` both land there whichever one the implementation uses. A bare
``FastAPI()`` holds only ``admin.router`` and ``image_generation.router`` with
``get_db`` overridden onto the same engine. Admin routes run either with
``require_admin`` overridden to allow (behaviour tests) or through the REAL
``require_admin`` in production mode with the ``_authz._admin_acl_probe`` seam
patched (authorization tests), the same mechanism as
``test_admin_route_authorization_inventory.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register the complete ORM metadata
from src.api.routes import _authz, admin, image_generation
from src.api.routes._authz import require_admin
from src.core.database import Base, get_db
from src.core.user_context import set_current_user
from src.database.models import WorkspaceSetting
from src.services import workspace_settings

FLAG = "TELLR_IMAGE_GENERATION_ENABLED"
KEY = "image_generation_enabled"
URL = "/api/admin/image-generation"
AVAILABLE_URL = "/api/images/generate/available"
ADMIN = "admin@example.com"
OTHER_ADMIN = "second-admin@example.com"
EARLIER_ADMIN = "earlier-admin@example.com"
NOT_AVAILABLE_PREFIX = "Image generation is not available on this deployment"

#: Marker for "no workspace_settings row for the key".
ABSENT = object()


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_identity() -> Iterator[None]:
    set_current_user(None)
    _authz.reset_admin_cache()
    try:
        yield
    finally:
        set_current_user(None)
        _authz.reset_admin_cache()


@pytest.fixture
def factory(monkeypatch: pytest.MonkeyPatch) -> Iterator[sessionmaker]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr("src.core.database.get_session_local", lambda: session_factory)
    try:
        yield session_factory
    finally:
        engine.dispose()


@pytest.fixture
def db(factory: sessionmaker) -> Iterator[Session]:
    session = factory()
    try:
        yield session
    finally:
        session.close()


def _app(factory: sessionmaker, *, allow_admin: bool) -> FastAPI:
    app = FastAPI()
    app.include_router(admin.router)
    app.include_router(image_generation.router)

    def override_get_db() -> Iterator[Session]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    if allow_admin:
        app.dependency_overrides[require_admin] = lambda: None
    return app


@pytest.fixture
def client(factory: sessionmaker) -> Iterator[TestClient]:
    """An admin caller (``require_admin`` allowed)."""
    set_current_user(ADMIN)
    with TestClient(_app(factory, allow_admin=True)) as c:
        yield c


def _env(monkeypatch: pytest.MonkeyPatch, value: Optional[str]) -> None:
    if value is None:
        monkeypatch.delenv(FLAG, raising=False)
    else:
        monkeypatch.setenv(FLAG, value)


def _stored(factory: sessionmaker) -> Any:
    """``(value, updated_by)`` of the stored row, read on a fresh session, or ABSENT."""
    session = factory()
    try:
        row = session.get(WorkspaceSetting, KEY)
        return ABSENT if row is None else (row.value, row.updated_by)
    finally:
        session.close()


def _seed(factory: sessionmaker, value: Any, *, by: str = EARLIER_ADMIN) -> None:
    session = factory()
    try:
        session.merge(WorkspaceSetting(key=KEY, value=value, updated_by=by))
        session.commit()
    finally:
        session.close()


def _force_admin(monkeypatch: pytest.MonkeyPatch, *, user: str, is_admin: bool) -> None:
    """The real ``require_admin`` path, as in the admin route inventory test."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    set_current_user(user)
    monkeypatch.setattr(_authz, "_admin_acl_probe", lambda _user: is_admin)
    _authz.reset_admin_cache()


# ---------------------------------------------------------------------------
# Storage (src.services.workspace_settings)
# ---------------------------------------------------------------------------


def test_the_setting_key_is_image_generation_enabled() -> None:
    assert workspace_settings.IMAGE_GENERATION_KEY == KEY


def test_on_when_never_set(db: Session) -> None:
    assert workspace_settings.image_generation_enabled(db) is True


def test_set_on_then_off(db: Session) -> None:
    assert workspace_settings.set_image_generation_enabled(db, enabled=True, user=ADMIN) is True
    assert workspace_settings.image_generation_enabled(db) is True
    assert workspace_settings.set_image_generation_enabled(db, enabled=False, user=ADMIN) is False
    assert workspace_settings.image_generation_enabled(db) is False


def test_set_stores_a_boolean_and_records_who_changed_it(
    db: Session, factory: sessionmaker
) -> None:
    workspace_settings.set_image_generation_enabled(db, enabled=True, user=ADMIN)
    assert _stored(factory) == (True, ADMIN)

    workspace_settings.set_image_generation_enabled(db, enabled=False, user=OTHER_ADMIN)
    assert _stored(factory) == (False, OTHER_ADMIN)


@pytest.mark.parametrize("value", [False, "false", "no", "0"])
def test_an_explicit_off_reads_as_off(
    db: Session, factory: sessionmaker, value: Any
) -> None:
    """On unless a row says off; the string forms of "off" count too."""
    _seed(factory, value)
    assert workspace_settings.image_generation_enabled(db) is False


def test_independent_of_the_genie_one_default(db: Session) -> None:
    workspace_settings.set_genie_one_default(db, enabled=False, user=ADMIN)
    assert workspace_settings.image_generation_enabled(db) is True

    workspace_settings.set_genie_one_default(db, enabled=True, user=ADMIN)
    workspace_settings.set_image_generation_enabled(db, enabled=False, user=ADMIN)
    assert workspace_settings.genie_one_default(db) is True
    assert workspace_settings.image_generation_enabled(db) is False


# ---------------------------------------------------------------------------
# GET /api/admin/image-generation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "env_value", [pytest.param(None, id="env-unset"), pytest.param("0", id="env-0"),
                  pytest.param("1", id="env-1")],
)
@pytest.mark.parametrize(
    "stored", [pytest.param(ABSENT, id="never-set"), pytest.param(True, id="stored-on"),
               pytest.param(False, id="stored-off")],
)
def test_get_reports_the_capability_and_the_setting(
    client: TestClient, factory: sessionmaker, monkeypatch: pytest.MonkeyPatch,
    env_value: Optional[str], stored: Any,
) -> None:
    _env(monkeypatch, env_value)
    if stored is not ABSENT:
        _seed(factory, stored)

    response = client.get(URL)

    assert response.status_code == 200, response.text
    assert response.json() == {"available": env_value != "0", "enabled": stored is not False}


# ---------------------------------------------------------------------------
# PUT /api/admin/image-generation (deployment offers the capability)
# ---------------------------------------------------------------------------


def test_put_turns_it_on_and_a_later_get_reflects_it(
    client: TestClient, factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env(monkeypatch, "1")

    response = client.put(URL, json={"enabled": True})

    assert response.status_code == 200, response.text
    assert response.json() == {"available": True, "enabled": True}
    assert client.get(URL).json() == {"available": True, "enabled": True}
    assert _stored(factory) == (True, ADMIN)


def test_put_turns_it_back_off(
    client: TestClient, factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env(monkeypatch, "1")
    assert client.put(URL, json={"enabled": True}).status_code == 200

    response = client.put(URL, json={"enabled": False})

    assert response.status_code == 200, response.text
    assert response.json() == {"available": True, "enabled": False}
    assert client.get(URL).json() == {"available": True, "enabled": False}
    assert _stored(factory) == (False, ADMIN)


def test_put_records_the_calling_admin(
    client: TestClient, factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env(monkeypatch, "1")
    client.put(URL, json={"enabled": True})
    assert _stored(factory) == (True, ADMIN)

    set_current_user(OTHER_ADMIN)
    client.put(URL, json={"enabled": False})
    assert _stored(factory) == (False, OTHER_ADMIN)


def test_put_rejects_a_missing_flag_and_stores_nothing(
    client: TestClient, factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env(monkeypatch, "1")

    response = client.put(URL, json={})

    assert response.status_code == 422, response.text
    assert _stored(factory) is ABSENT


# ---------------------------------------------------------------------------
# PUT when the deployment does not offer the capability: 409, nothing stored
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "env_value", [pytest.param("0", id="env-0"), pytest.param("false", id="env-false")]
)
@pytest.mark.parametrize("enabled", [True, False])
def test_put_is_409_and_stores_nothing_without_the_capability(
    client: TestClient, factory: sessionmaker, monkeypatch: pytest.MonkeyPatch,
    env_value: Optional[str], enabled: bool,
) -> None:
    _env(monkeypatch, env_value)

    response = client.put(URL, json={"enabled": enabled})

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, str)
    assert detail.startswith(NOT_AVAILABLE_PREFIX), detail
    assert _stored(factory) is ABSENT, "a refused PUT must not write the setting"
    assert client.get(URL).json() == {"available": False, "enabled": True}


@pytest.mark.parametrize("stored, attempted", [(True, False), (False, True), (True, True)])
def test_a_refused_put_leaves_an_existing_setting_untouched(
    client: TestClient, factory: sessionmaker, monkeypatch: pytest.MonkeyPatch,
    stored: bool, attempted: bool,
) -> None:
    _seed(factory, stored, by=EARLIER_ADMIN)
    _env(monkeypatch, "0")

    response = client.put(URL, json={"enabled": attempted})

    assert response.status_code == 409, response.text
    assert _stored(factory) == (stored, EARLIER_ADMIN), "value and updated_by unchanged"


# ---------------------------------------------------------------------------
# Authorization: the real require_admin gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method, body", [pytest.param("GET", None, id="GET"),
                     pytest.param("PUT", {"enabled": True}, id="PUT")],
)
def test_non_admin_is_403_and_stores_nothing(
    factory: sessionmaker, monkeypatch: pytest.MonkeyPatch,
    method: str, body: Optional[dict],
) -> None:
    _env(monkeypatch, "1")
    _force_admin(monkeypatch, user="regular-user@example.com", is_admin=False)

    with TestClient(_app(factory, allow_admin=False)) as c:
        response = c.request(method, URL, json=body)

    assert response.status_code == 403, response.text
    assert _stored(factory) is ABSENT
    assert "enabled" not in response.text


@pytest.mark.parametrize(
    "method, body", [pytest.param("GET", None, id="GET"),
                     pytest.param("PUT", {"enabled": True}, id="PUT")],
)
def test_admin_passes_the_real_gate(
    factory: sessionmaker, monkeypatch: pytest.MonkeyPatch,
    method: str, body: Optional[dict],
) -> None:
    _env(monkeypatch, "1")
    _force_admin(monkeypatch, user=ADMIN, is_admin=True)

    with TestClient(_app(factory, allow_admin=False)) as c:
        response = c.request(method, URL, json=body)

    assert response.status_code == 200, response.text
    if method == "PUT":
        assert response.json() == {"available": True, "enabled": True}
        assert _stored(factory) == (True, ADMIN)
    else:
        assert response.json() == {"available": True, "enabled": True}, "on by default"


# ---------------------------------------------------------------------------
# The admin switch drives what users are offered, with no restart
# ---------------------------------------------------------------------------


def test_the_admin_switch_drives_the_user_availability_probe(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env(monkeypatch, "1")

    default = client.get(AVAILABLE_URL)
    assert default.status_code == 200, default.text
    assert default.json()["available"] is True, "on by default on a capable deployment"
    assert default.json()["presets"], "an enabled workspace is offered the presets"

    assert client.put(URL, json={"enabled": False}).status_code == 200
    off = client.get(AVAILABLE_URL).json()
    assert off["available"] is False
    assert not off.get("presets")
    assert not off.get("edit")

    assert client.put(URL, json={"enabled": True}).status_code == 200
    assert client.get(AVAILABLE_URL).json()["available"] is True


# ---------------------------------------------------------------------------
# generation_available(db): the one gate the routes AND the chat tool share
#
# Chat image generation, Unit G (docs/superpowers/plans/2026-11-09-chat-image-generation-
# CORRECTIONS.md, "Unit G interface"): ``src.services.image_generation.generation_available(db)``
# is ``is_enabled() and workspace_settings.image_generation_enabled(db)``. It does NOT read the
# settings table when the env gate is off, and the routes' ``_effective_enabled(db)`` delegates
# to it, so the routes and the graph can never disagree.
# ---------------------------------------------------------------------------


class _UntouchableDb:
    """A db that records, and fails, any use: proof the settings table was not read.

    Uses are recorded as well as raised, so an implementation that swallowed the error
    (``try: ... except Exception: return False``) is still caught by ``touched``.
    """

    def __init__(self) -> None:
        self.touched: list[str] = []

    def __getattr__(self, name: str) -> Any:
        self.touched.append(name)
        raise AssertionError(f"the settings table was read (db.{name}) with the env gate off")


def _generation_available(db: Any) -> Any:
    from src.services import image_generation as service

    return service.generation_available(db)


@pytest.mark.parametrize("env_value", ["0", "false", "no", "off", " OFF "])
def test_generation_available_is_false_when_the_env_gate_is_off_without_reading_the_db(
    monkeypatch: pytest.MonkeyPatch, env_value: str
) -> None:
    _env(monkeypatch, env_value)
    db = _UntouchableDb()

    assert _generation_available(db) is False
    assert db.touched == [], "the env gate must short-circuit before the settings read"


@pytest.mark.parametrize("env_value", [None, "1"], ids=["env-unset", "env-1"])
@pytest.mark.parametrize(
    "stored, expected",
    [
        pytest.param(False, False, id="admin-off"),
        pytest.param("off", False, id="admin-off-string"),
        pytest.param(ABSENT, True, id="admin-never-set"),
        pytest.param(True, True, id="admin-on"),
    ],
)
def test_generation_available_truth_table_with_the_env_gate_on(
    db: Session, factory: sessionmaker, monkeypatch: pytest.MonkeyPatch,
    env_value: Optional[str], stored: Any, expected: bool,
) -> None:
    _env(monkeypatch, env_value)
    if stored is not ABSENT:
        _seed(factory, stored)

    assert _generation_available(db) is expected


def test_generation_available_follows_the_admin_switch_with_no_restart(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read on every call (R5: never cached)."""
    _env(monkeypatch, "1")
    assert _generation_available(db) is True

    workspace_settings.set_image_generation_enabled(db, enabled=False, user=ADMIN)
    assert _generation_available(db) is False

    workspace_settings.set_image_generation_enabled(db, enabled=True, user=ADMIN)
    assert _generation_available(db) is True


def _patch_generation_available(monkeypatch: pytest.MonkeyPatch, answer: dict) -> list:
    """Replace ``generation_available`` wherever the routes could look it up; return the
    dbs it was called with. ``answer["value"]`` is what it says."""
    from src.services import image_generation as service

    seen: list = []

    def fake(db: Any) -> bool:
        seen.append(db)
        return answer["value"]

    # raising=True on the service: the function must exist there.
    monkeypatch.setattr(service, "generation_available", fake)
    # The routes may import the name directly (``from ... import generation_available``).
    monkeypatch.setattr(image_generation, "generation_available", fake, raising=False)
    return seen


def test_the_routes_gate_follows_generation_available_not_their_own_checks(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With ``generation_available`` replaced, the routes follow it even where the real env
    and admin gates say the opposite, so ``_effective_enabled`` delegates to it."""
    started: list = []
    # Never start a real job, whatever the gate says.
    jobs = image_generation.jobs
    monkeypatch.setattr(jobs, "create_job", lambda **kw: started.append(kw) or "j1")
    monkeypatch.setattr(jobs, "submit", lambda *a, **kw: started.append(kw) or True)
    answer = {"value": False}
    seen = _patch_generation_available(monkeypatch, answer)

    # The real gates are both on (env 1, admin never set) but generation_available says no.
    _env(monkeypatch, "1")
    off = client.get(AVAILABLE_URL)
    assert off.status_code == 200, off.text
    assert off.json()["available"] is False
    assert not off.json().get("presets")
    refused = client.post("/api/images/generate", json={"prompt": "a lighthouse"})
    assert refused.status_code == 404, refused.text
    assert started == [], "a refused gate must not start a job"

    # The real env gate is off but generation_available says yes.
    _env(monkeypatch, "0")
    answer["value"] = True
    on = client.get(AVAILABLE_URL)
    assert on.status_code == 200, on.text
    assert on.json()["available"] is True
    assert on.json()["presets"], "an available deployment is offered the presets"

    assert len(seen) >= 3, "every gated request asks generation_available"
    assert all(isinstance(s, Session) for s in seen), "it is given the request's db session"
