"""Regression: a soft-deleted design system must not hold its name forever.

The reported sequence was a permanent dead end: import a bundle, delete the
design system through the admin UI (which calls DELETE with default parameters,
i.e. the SOFT-delete path), then re-import a corrected bundle carrying the SAME
manifest name. The row was gone from the picker, but every re-import was refused
with "A design system named '…' already exists (id=N). Choose a different name
to import a copy." — a name the user could no longer see, could no longer
delete, and could never reuse.

Three sites conspired:

1. ``DELETE /{ds_id}`` defaults to ``ds.is_active = False`` (a tombstone).
2. ``GET ""`` filters ``is_active == True``, so the tombstone is invisible.
3. The import/create/rename name pre-checks queried ``name ==`` with NO
   ``is_active`` filter, so they saw the invisible tombstone and refused.

Fixing only the pre-checks would have converted the clean 409 into an
IntegrityError at commit, because ``design_system.name`` carries a UNIQUE index.
So uniqueness itself is scoped to LIVE rows by a PARTIAL unique index
(``WHERE is_active``), and these tests pin both halves: a deleted name is
reusable, and a LIVE name still collides.

All fixtures are SYNTHETIC (invented brand, invented hex) per the public-repo
hygiene rule.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.main import app
from src.core.database import Base, get_db
from src.database.models.design_system import DesignSystem
from tests.unit.conftest_design_system import default_manifest, make_bundle_zip

BASE = "/api/settings/design-systems"

# Invented brand name — deliberately NOT any real company's design system.
FIXTURE_NAME = "Nimbus Widgets Design System"


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
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _import_named(client, name: str):
    """Import a bundle whose MANIFEST declares ``name`` (no name_override).

    The reported defect came in through the manifest name, not the optional
    ``name`` form field, so the fixture reproduces that exact path.
    """
    manifest = default_manifest()
    manifest["name"] = name
    zip_bytes = make_bundle_zip(manifest=manifest)
    return client.post(
        f"{BASE}/import",
        files={"file": ("bundle.zip", zip_bytes, "application/zip")},
    )


class TestNameReuseAfterSoftDelete:
    def test_reimport_after_ui_delete_succeeds(self, client, db_session):
        """The reported user sequence, end to end, through the real endpoints."""
        first = _import_named(client, FIXTURE_NAME)
        assert first.status_code == 201, first.text
        first_id = first.json()["id"]

        # Exactly what the admin UI calls: DELETE with DEFAULT parameters.
        # (frontend/src/api/config.ts passes no hard_delete, so this is the
        # soft-delete path.)
        assert client.delete(f"{BASE}/{first_id}").status_code == 204

        # The UI's list no longer shows it — the user has every reason to
        # believe the name is free.
        listed = client.get(BASE).json()
        assert [d["id"] for d in listed["design_systems"]] == []

        # Re-importing the corrected bundle under the SAME name must succeed.
        second = _import_named(client, FIXTURE_NAME)
        assert second.status_code == 201, second.text
        assert second.json()["name"] == FIXTURE_NAME
        assert second.json()["id"] != first_id

        # The tombstone is retained (history preserved), and the live row is the
        # new one.
        rows = db_session.query(DesignSystem).filter(DesignSystem.name == FIXTURE_NAME).all()
        assert sorted(r.is_active for r in rows) == [False, True]

    def test_repeated_delete_reimport_cycles_keep_working(self, client, db_session):
        """Two tombstones sharing one name must not deadlock the third import.

        A uniqueness rule scoped to live rows has to tolerate MANY dead rows
        holding the same name, not just one.
        """
        for _ in range(2):
            resp = _import_named(client, FIXTURE_NAME)
            assert resp.status_code == 201, resp.text
            assert client.delete(f"{BASE}/{resp.json()['id']}").status_code == 204

        third = _import_named(client, FIXTURE_NAME)
        assert third.status_code == 201, third.text

        rows = db_session.query(DesignSystem).filter(DesignSystem.name == FIXTURE_NAME).all()
        assert len(rows) == 3
        assert sum(1 for r in rows if r.is_active) == 1


class TestLiveNameStillCollides:
    """Do not fix the tombstone bug by dropping the uniqueness guarantee."""

    def test_import_over_live_name_returns_409(self, client):
        assert _import_named(client, FIXTURE_NAME).status_code == 201

        clash = _import_named(client, FIXTURE_NAME)
        assert clash.status_code == 409, clash.text
        assert "already exists" in clash.json()["detail"]

    def test_create_over_live_name_returns_409(self, client):
        assert _import_named(client, FIXTURE_NAME).status_code == 201

        clash = client.post(BASE, json={"name": FIXTURE_NAME})
        assert clash.status_code == 409, clash.text

    def test_rename_onto_live_name_returns_409(self, client):
        held = _import_named(client, FIXTURE_NAME).json()["id"]
        other = _import_named(client, "Other Live System").json()["id"]
        assert held and other

        clash = client.put(f"{BASE}/{other}", json={"name": FIXTURE_NAME})
        assert clash.status_code == 409, clash.text


class TestTombstonedNameIsFreeForEveryWriter:
    """Import is not the only writer of ``name``; all three must agree."""

    def test_create_can_reuse_a_deleted_name(self, client):
        ds_id = _import_named(client, FIXTURE_NAME).json()["id"]
        assert client.delete(f"{BASE}/{ds_id}").status_code == 204

        resp = client.post(BASE, json={"name": FIXTURE_NAME})
        assert resp.status_code == 201, resp.text

    def test_rename_can_reuse_a_deleted_name(self, client):
        ds_id = _import_named(client, FIXTURE_NAME).json()["id"]
        assert client.delete(f"{BASE}/{ds_id}").status_code == 204
        other = _import_named(client, "Other Live System").json()["id"]

        resp = client.put(f"{BASE}/{other}", json={"name": FIXTURE_NAME})
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == FIXTURE_NAME


class TestDanglingPinStillSelfHeals:
    """A session pinned to a deleted design system must degrade, never 422/500.

    Sessions store ``design_system_id`` inside an opaque JSON ``agent_config``
    column — there is NO foreign key — so nothing at the database level protects
    the pin. ``_sanitize_stale_pins`` is the only thing that does, and this fix
    makes the tombstoned state MORE common (a name can now be deleted and reused
    repeatedly), so the heal is pinned here rather than assumed.
    """

    def _patched_db(self, db_session):
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=db_session)
        cm.__exit__ = MagicMock(return_value=False)
        return patch("src.api.routes.agent_config.get_db_session", return_value=cm)

    def _sanitize(self, db_session, ds_id):
        from src.api.routes.agent_config import _sanitize_stale_pins
        from src.api.schemas.agent_config import AgentConfig

        config = AgentConfig(design_system_id=ds_id)
        with self._patched_db(db_session):
            cleared = _sanitize_stale_pins(config, session_id="synthetic-session")
        return config, cleared

    def test_live_pin_is_left_alone(self, client, db_session):
        ds_id = _import_named(client, FIXTURE_NAME).json()["id"]
        config, cleared = self._sanitize(db_session, ds_id)
        assert cleared is False
        assert config.design_system_id == ds_id

    def test_soft_deleted_pin_resolves_to_none(self, client, db_session):
        ds_id = _import_named(client, FIXTURE_NAME).json()["id"]
        assert client.delete(f"{BASE}/{ds_id}").status_code == 204

        config, cleared = self._sanitize(db_session, ds_id)
        assert cleared is True
        assert config.design_system_id is None

    def test_hard_deleted_pin_resolves_to_none(self, client, db_session):
        """The same heal covers a row that is physically gone (``hard_delete=true``)."""
        ds_id = _import_named(client, FIXTURE_NAME).json()["id"]
        assert client.delete(f"{BASE}/{ds_id}?hard_delete=true").status_code == 204

        config, cleared = self._sanitize(db_session, ds_id)
        assert cleared is True
        assert config.design_system_id is None
