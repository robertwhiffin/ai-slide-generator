"""Design-system mutation routes are admin-gated (SDR-4437 HIGH-3 alignment).

Aligns ``design_systems.py`` with the admin pattern robert established in
``slide_styles.py`` / ``deck_prompts.py``: org-wide mutations are admin-only,
reads stay open. The design-system router post-dates that sweep, so it was
never gated.

Test idiom copied from ``tests/unit/test_authz_settings_admin.py`` (the
parametrized 403 table covering the slide-style / deck-prompt admin routes),
with the ``production`` / ``non_admin`` / ``admin`` fixture triple from
``tests/unit/test_authz_admin_feedback.py`` so the admin-still-succeeds half
can be asserted too. The real in-memory SQLite ``get_db`` override follows
``tests/unit/test_design_systems_routes.py``.

Every route is exercised against a REAL seeded design system, so an ungated
mutation would answer 200/204 — a 403 therefore proves the gate fired, and
cannot be a 404-by-accident on a missing row. All fixtures are SYNTHETIC.
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


@pytest.fixture
def seeded_ds(db_session):
    """A real, active design system so mutations have a live target to hit."""
    ds = DesignSystem(
        name="Synthetic DS",
        description="synthetic fixture",
        created_by="owner@test.com",
        updated_by="owner@test.com",
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


def _mutations(ds_id: int):
    """(method, path, body) for the three org-wide design-system mutations."""
    return [
        ("POST", f"{BASE}/{ds_id}/set-default", None),
        ("PUT", f"{BASE}/{ds_id}", {"description": "renamed by caller"}),
        ("DELETE", f"{BASE}/{ds_id}", None),
    ]


@pytest.mark.parametrize("index", [0, 1, 2], ids=["set-default", "update", "delete"])
def test_design_system_mutations_403_for_non_admin(client, seeded_ds, non_admin, index):
    method, path, body = _mutations(int(seeded_ds.id))[index]
    resp = client.request(method, path, json=body)
    assert resp.status_code == 403, f"{method} {path} -> {resp.status_code} {resp.text}"


@pytest.mark.parametrize("index", [0, 1, 2], ids=["set-default", "update", "delete"])
def test_design_system_mutations_succeed_for_admin(client, seeded_ds, admin, index):
    """Behavior preserved: the gate must not break the admin path."""
    method, path, body = _mutations(int(seeded_ds.id))[index]
    resp = client.request(method, path, json=body)
    assert resp.status_code in (200, 204), (
        f"{method} {path} -> {resp.status_code} {resp.text}"
    )


def test_import_stays_open_for_non_admin(client, non_admin):
    """Explicit product decision: any user may contribute a design system."""
    resp = client.post(
        f"{BASE}/import",
        files={"file": ("synthetic.zip", make_bundle_zip(), "application/zip")},
    )
    assert resp.status_code == 201, resp.text


def test_create_stays_open_for_non_admin(client, non_admin):
    """Explicit product decision: any user may contribute a design system."""
    resp = client.post(BASE, json={"name": "Contributed by a regular user"})
    assert resp.status_code == 201, resp.text


@pytest.mark.parametrize("path", ["", "/{ds_id}"])
def test_design_system_reads_stay_open_for_non_admin(client, seeded_ds, non_admin, path):
    resp = client.get(BASE + path.format(ds_id=int(seeded_ds.id)))
    assert resp.status_code != 403, resp.text
