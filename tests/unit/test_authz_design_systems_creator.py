"""Design-system rename/delete are CREATOR-OR-ADMIN gated (Option C).

Supersedes the admin-only half of ``test_authz_design_systems_admin.py`` for
PUT/DELETE. The product model design systems actually implement:

    all GETs              OPEN
    POST /import          OPEN  — any user may CONTRIBUTE
    POST ""    (create)   OPEN  — any user may CONTRIBUTE
    PUT    /{ds_id}       CREATOR OR ADMIN  — manage what you uploaded
    DELETE /{ds_id}       CREATOR OR ADMIN  — manage what you uploaded
    POST /{ds_id}/set-default   ADMIN ONLY  — org-wide blast radius

Design systems are org-shared, user-contributed content: any user may add one
AND manage the ones they uploaded, nobody may touch someone else's, and admins
may manage anything.

IDENTITY (why these tests are honest): the caller is resolved server-side from
``get_permission_context().user_name``, which the OBO middleware
(``src/api/main.py``) populates from the authenticated token — in production
from ``user_client.current_user.me()``, and in dev/test from ``DEV_USER_ID``.
These tests therefore steer identity by setting ``DEV_USER_ID`` and letting the
REAL middleware build the permission context, rather than monkeypatching the
guard or the getter. Nothing the client sends (body, query, header) can change
the verdict, so there is no spoofable seam for a test to accidentally bless.

Every case runs against a REAL seeded design system, so a missing gate answers
200/204 rather than 403 — a 403 proves the gate fired and cannot be a
404-by-accident on an absent row. All fixtures are SYNTHETIC.

Fixture idiom (in-memory SQLite ``get_db`` override + the
``production``/``non_admin``/``admin`` monkeypatch triple) copied from
``tests/unit/test_authz_design_systems_admin.py``.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.main import app
from src.core.database import Base, get_db
from src.database.models.design_system import DesignSystem
from tests.unit.conftest_design_system import make_bundle_zip

BASE = "/api/settings/design-systems"

CREATOR = "creator@test.com"
OTHER = "someone-else@test.com"


@pytest.fixture(scope="function")
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine):
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = session_local()
    yield session
    session.close()


@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def _seed(db_session, created_by, name="Acme Synthetic DS"):
    """Seed a real, active design system authored by ``created_by``."""
    ds = DesignSystem(
        name=name,
        description="synthetic fixture",
        created_by=created_by,
        updated_by=created_by,
        version=1,
        published=False,
        is_default=False,
        is_active=True,
    )
    db_session.add(ds)
    db_session.commit()
    db_session.refresh(ds)
    return ds


@pytest.fixture
def production(monkeypatch):
    """Turn OFF the dev-mode admin bypass so the admin verdict is real."""
    from src.api.routes import _authz

    monkeypatch.setattr(_authz, "_is_production", lambda: True)
    monkeypatch.setattr(_authz, "get_current_user", lambda: "user@test.com")
    _authz.reset_admin_cache()
    yield _authz
    _authz.reset_admin_cache()


@pytest.fixture
def non_admin(production, monkeypatch):
    monkeypatch.setattr(production, "_admin_acl_probe", lambda user: False)


@pytest.fixture
def admin(production, monkeypatch):
    monkeypatch.setattr(production, "_admin_acl_probe", lambda user: True)


@pytest.fixture
def as_creator(monkeypatch):
    """Authenticate the request AS the seeded design system's author."""
    monkeypatch.setenv("DEV_USER_ID", CREATOR)


@pytest.fixture
def as_other_user(monkeypatch):
    """Authenticate the request as a DIFFERENT user than the author."""
    monkeypatch.setenv("DEV_USER_ID", OTHER)


# --- (a)/(b) the creator may manage their OWN design system -----------------


def test_creator_non_admin_can_rename_own_design_system(
    client, db_session, non_admin, as_creator
):
    """(a) A plain user renames the design system they uploaded."""
    ds = _seed(db_session, CREATOR)
    resp = client.put(f"{BASE}/{ds.id}", json={"name": "Acme DS renamed by its author"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Acme DS renamed by its author"


def test_creator_non_admin_can_delete_own_design_system(
    client, db_session, non_admin, as_creator
):
    """(b) A plain user deletes the design system they uploaded."""
    ds = _seed(db_session, CREATOR)
    resp = client.delete(f"{BASE}/{ds.id}")
    assert resp.status_code == 204, resp.text


# --- (c)/(d) nobody may touch someone else's -------------------------------


def test_non_creator_non_admin_cannot_rename_other_users_design_system(
    client, db_session, non_admin, as_other_user
):
    """(c) A plain user may NOT rename a design system they did not upload."""
    ds = _seed(db_session, CREATOR)
    resp = client.put(f"{BASE}/{ds.id}", json={"name": "Hijacked by a stranger"})
    assert resp.status_code == 403, resp.text
    db_session.refresh(ds)
    assert ds.name == "Acme Synthetic DS", "denied rename must not mutate the row"


def test_non_creator_non_admin_cannot_delete_other_users_design_system(
    client, db_session, non_admin, as_other_user
):
    """(d) A plain user may NOT delete a design system they did not upload."""
    ds = _seed(db_session, CREATOR)
    resp = client.delete(f"{BASE}/{ds.id}")
    assert resp.status_code == 403, resp.text
    db_session.refresh(ds)
    assert ds.is_active is True, "denied delete must not deactivate the row"


# --- (e) admins may manage ANY design system, including others' ------------


def test_admin_can_rename_design_system_they_did_not_create(
    client, db_session, admin, as_other_user
):
    """(e) Admin overrides authorship on rename."""
    ds = _seed(db_session, CREATOR)
    resp = client.put(f"{BASE}/{ds.id}", json={"name": "Renamed by an admin"})
    assert resp.status_code == 200, resp.text


def test_admin_can_delete_design_system_they_did_not_create(
    client, db_session, admin, as_other_user
):
    """(e) Admin overrides authorship on delete."""
    ds = _seed(db_session, CREATOR)
    resp = client.delete(f"{BASE}/{ds.id}")
    assert resp.status_code == 204, resp.text


# --- (f) set-default stays ADMIN-ONLY (org-wide blast radius) --------------


def test_creator_non_admin_cannot_set_default_on_own_design_system(
    client, db_session, non_admin, as_creator
):
    """(f) Authorship does NOT buy set-default — it changes what EVERYONE gets."""
    ds = _seed(db_session, CREATOR)
    resp = client.post(f"{BASE}/{ds.id}/set-default")
    assert resp.status_code == 403, resp.text
    db_session.refresh(ds)
    assert ds.is_default is False, "denied set-default must not flip the org default"


def test_admin_can_set_default(client, db_session, admin, as_other_user):
    """(f) Behavior preserved for the admin half of set-default."""
    ds = _seed(db_session, CREATOR)
    resp = client.post(f"{BASE}/{ds.id}/set-default")
    assert resp.status_code == 200, resp.text


# --- (g) the core user story: contributing stays OPEN ----------------------


def test_non_admin_can_still_import_bundle(client, non_admin, as_other_user):
    """(g) Any authenticated user may CONTRIBUTE a design system by upload."""
    resp = client.post(
        f"{BASE}/import",
        files={"file": ("synthetic.zip", make_bundle_zip(), "application/zip")},
    )
    assert resp.status_code == 201, resp.text


def test_non_admin_can_still_create(client, non_admin, as_other_user):
    """(g) Any authenticated user may CONTRIBUTE a design system via create."""
    resp = client.post(BASE, json={"name": "Contributed by a regular user"})
    assert resp.status_code == 201, resp.text


# --- (h) blank authorship falls back to ADMIN-ONLY (security requirement) --
#
# ``design_system.created_by`` is nullable and legacy rows may carry NULL or a
# blank string. A blank author must NEVER resolve to "anyone may manage this":
# an unauthenticated/blank CALLER must not match a blank OWNER either, so the
# comparison can never be satisfied by two empty values.


@pytest.mark.parametrize(
    "blank", [None, "", "   "], ids=["null", "empty", "whitespace"]
)
def test_creatorless_design_system_is_admin_only_for_non_admin(
    client, db_session, non_admin, as_creator, blank
):
    """(h) NULL/blank ``created_by`` -> admin-only, so a non-admin gets 403."""
    ds = _seed(db_session, blank)
    put = client.put(f"{BASE}/{ds.id}", json={"name": "Claimed via blank authorship"})
    assert put.status_code == 403, f"PUT on blank-author DS -> {put.status_code} {put.text}"
    delete = client.delete(f"{BASE}/{ds.id}")
    assert delete.status_code == 403, (
        f"DELETE on blank-author DS -> {delete.status_code} {delete.text}"
    )
    db_session.refresh(ds)
    assert ds.name == "Acme Synthetic DS"
    assert ds.is_active is True


@pytest.mark.parametrize(
    "blank", [None, "", "   "], ids=["null", "empty", "whitespace"]
)
def test_creatorless_design_system_is_still_manageable_by_admin(
    client, db_session, admin, as_creator, blank
):
    """(h) The admin-only fallback still lets an ADMIN clean up legacy rows."""
    ds = _seed(db_session, blank)
    resp = client.put(f"{BASE}/{ds.id}", json={"name": "Adopted by an admin"})
    assert resp.status_code == 200, resp.text


def test_blank_caller_cannot_match_blank_creator(client, db_session, non_admin, monkeypatch):
    """(h) A blank CALLER must not match a blank OWNER — the both-empty trap.

    Belt-and-braces on the fallback: even if identity resolution yields an
    empty username, `"" == ""` must not be read as "the caller is the author".
    """
    monkeypatch.setenv("DEV_USER_ID", "")
    ds = _seed(db_session, "")
    resp = client.delete(f"{BASE}/{ds.id}")
    assert resp.status_code == 403, resp.text
    db_session.refresh(ds)
    assert ds.is_active is True
