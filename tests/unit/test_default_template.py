"""A design system's default template: storage, resolution and admin routes.

The default template is what a new session on a design system is pinned to, and
what the architect falls back to for an unpinned session, so a deck binds to a
template's labelled sections instead of improvising markup. Session seeding is
covered in ``test_chat_session_creation.py`` / ``test_mcp_server.py`` and the
architect fallback in ``test_graph_nodes.py``. All fixtures are SYNTHETIC.
"""

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.main import app
from src.core.database import Base, get_db
from src.database.models.design_system import DesignSystem, DesignSystemTemplate

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
    session = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)()
    yield session
    session.close()


@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def _design_system(db, name: str, *, is_active: bool = True, templates=("Corporate", "Events")):
    ds = DesignSystem(
        name=name,
        description="synthetic fixture",
        created_by="owner@test.com",
        updated_by="owner@test.com",
        version=1,
        published=False,
        is_default=False,
        is_active=is_active,
    )
    for tmpl in templates:
        ds.templates.append(
            DesignSystemTemplate(
                name=tmpl,
                entry_path=f"templates/{tmpl.lower()}/index.html",
                layout_html=f"<section data-label='{tmpl}'><div class='slide'></div></section>",
            )
        )
    db.add(ds)
    db.commit()
    db.refresh(ds)
    return ds


@pytest.fixture
def two_systems(db_session):
    return _design_system(db_session, "Brand A"), _design_system(db_session, "Brand B")


@pytest.fixture
def production(monkeypatch):
    from src.api.routes import _authz

    monkeypatch.setattr(_authz, "_is_production", lambda: True)
    monkeypatch.setattr(_authz, "get_current_user", lambda: "user@test.com")
    _authz.reset_admin_cache()
    yield _authz
    _authz.reset_admin_cache()


@pytest.fixture
def admin(production, monkeypatch):
    monkeypatch.setattr(production, "_admin_acl_probe", lambda user: True)


@pytest.fixture
def non_admin(production, monkeypatch):
    monkeypatch.setattr(production, "_admin_acl_probe", lambda user: False)


def _defaults(db, ds_id: int) -> list[str]:
    db.expire_all()
    return [
        t.name
        for t in db.query(DesignSystemTemplate)
        .filter(DesignSystemTemplate.design_system_id == ds_id)
        .order_by(DesignSystemTemplate.id)
        if t.is_default
    ]


# ---- admin routes ------------------------------------------------------------


def test_set_default_marks_one_template_and_lists_it(client, db_session, two_systems, admin):
    ds, _ = two_systems
    corporate, events = sorted(ds.templates, key=lambda t: t.id)

    resp = client.post(f"{BASE}/{ds.id}/templates/{corporate.id}/set-default")

    assert resp.status_code == 200, resp.text
    listed = {t["name"]: t["is_default"] for t in resp.json()["templates"]}
    assert listed == {"Corporate": True, "Events": False}
    assert _defaults(db_session, ds.id) == ["Corporate"]
    # The listing GET carries the same flag.
    listed = client.get(f"{BASE}/{ds.id}/templates").json()["templates"]
    assert {t["name"]: t["is_default"] for t in listed} == {"Corporate": True, "Events": False}


def test_set_default_moves_the_flag_within_one_design_system_only(
    client, db_session, two_systems, admin
):
    """At most one default per design system, and setting one never touches a
    different system's default."""
    ds_a, ds_b = two_systems
    a_corp, a_events = sorted(ds_a.templates, key=lambda t: t.id)
    b_corp, _ = sorted(ds_b.templates, key=lambda t: t.id)

    assert client.post(f"{BASE}/{ds_b.id}/templates/{b_corp.id}/set-default").status_code == 200
    assert client.post(f"{BASE}/{ds_a.id}/templates/{a_corp.id}/set-default").status_code == 200
    assert client.post(f"{BASE}/{ds_a.id}/templates/{a_events.id}/set-default").status_code == 200

    assert _defaults(db_session, ds_a.id) == ["Events"]
    assert _defaults(db_session, ds_b.id) == ["Corporate"]


def test_set_default_is_idempotent(client, db_session, two_systems, admin):
    ds, _ = two_systems
    corporate = min(ds.templates, key=lambda t: t.id)
    for _ in range(2):
        assert client.post(f"{BASE}/{ds.id}/templates/{corporate.id}/set-default").status_code == 200
    assert _defaults(db_session, ds.id) == ["Corporate"]


def test_clear_default_returns_the_system_to_no_default(client, db_session, two_systems, admin):
    ds, _ = two_systems
    corporate = min(ds.templates, key=lambda t: t.id)
    client.post(f"{BASE}/{ds.id}/templates/{corporate.id}/set-default")

    for _ in range(2):  # idempotent
        resp = client.post(f"{BASE}/{ds.id}/templates/{corporate.id}/clear-default")
        assert resp.status_code == 200, resp.text
    assert _defaults(db_session, ds.id) == []


def test_a_template_of_another_design_system_is_404(client, two_systems, admin):
    ds_a, ds_b = two_systems
    b_template = min(ds_b.templates, key=lambda t: t.id)
    for action in ("set-default", "clear-default"):
        resp = client.post(f"{BASE}/{ds_a.id}/templates/{b_template.id}/{action}")
        assert resp.status_code == 404, resp.text
    assert client.post(f"{BASE}/99999/templates/{b_template.id}/set-default").status_code == 404


def test_set_default_refuses_an_inactive_design_system(client, db_session, admin):
    ds = _design_system(db_session, "Retired", is_active=False)
    template = min(ds.templates, key=lambda t: t.id)
    resp = client.post(f"{BASE}/{ds.id}/templates/{template.id}/set-default")
    assert resp.status_code == 400, resp.text
    assert _defaults(db_session, ds.id) == []


@pytest.mark.parametrize("action", ["set-default", "clear-default"])
def test_default_template_routes_are_admin_only(client, db_session, two_systems, non_admin, action):
    ds, _ = two_systems
    template = min(ds.templates, key=lambda t: t.id)
    resp = client.post(f"{BASE}/{ds.id}/templates/{template.id}/{action}")
    assert resp.status_code == 403, resp.text
    assert _defaults(db_session, ds.id) == []


# ---- resolver ----------------------------------------------------------------


@pytest.fixture
def resolver_db(db_engine, monkeypatch):
    """Point ``settings_db.get_db_session`` at the in-memory database."""
    from src.core import settings_db

    factory = sessionmaker(bind=db_engine)

    @contextmanager
    def _session():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(settings_db, "get_db_session", _session)
    return settings_db


def test_resolver_returns_the_design_systems_default(db_session, two_systems, resolver_db):
    ds_a, ds_b = two_systems
    a_events = max(ds_a.templates, key=lambda t: t.id)
    a_events.is_default = True
    db_session.commit()

    assert resolver_db.get_default_template_id(ds_a.id) == a_events.id
    # Another design system's default never leaks across.
    assert resolver_db.get_default_template_id(ds_b.id) is None


def test_resolver_has_no_fallback_to_an_arbitrary_template(two_systems, resolver_db):
    ds_a, _ = two_systems
    assert resolver_db.get_default_template_id(ds_a.id) is None
    assert resolver_db.get_default_template_id(None) is None


def test_resolver_ignores_an_inactive_design_system(db_session, resolver_db):
    ds = _design_system(db_session, "Retired", is_active=False)
    min(ds.templates, key=lambda t: t.id).is_default = True
    db_session.commit()

    assert resolver_db.get_default_template_id(ds.id) is None


# ---- migration ---------------------------------------------------------------


def test_migration_adds_is_default_to_a_pre_existing_table():
    """A ``design_system_template`` table from an earlier deploy gains the
    column, defaulting existing rows to not-default; a second run is a no-op."""
    from src.core.database import _migrate_design_system_template_default

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE design_system_template (id INTEGER PRIMARY KEY, name TEXT)"
        ))
        conn.execute(text("INSERT INTO design_system_template (id, name) VALUES (1, 'Old')"))

    for _ in range(2):
        with engine.begin() as conn:
            _migrate_design_system_template_default(
                conn, inspect(conn), schema=None, _qual=lambda t: f'"{t}"', is_sqlite=True
            )

    cols = {c["name"] for c in inspect(engine).get_columns("design_system_template")}
    assert "is_default" in cols
    with engine.connect() as conn:
        assert conn.execute(text("SELECT is_default FROM design_system_template")).scalar() == 0
