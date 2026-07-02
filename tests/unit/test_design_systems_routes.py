"""API tests for the Design System settings router (Phase 3).

Endpoints under ``/api/settings/design-systems``: import (bundle upload), list,
get, create (structured), update, delete (soft), set-default, and serve-asset —
mirroring the slide-styles router. Plus design_system_id reference integrity in
the agent-config validator, and backward-compat guards.

Uses a real in-memory SQLite DB via a get_db dependency override (mirroring
tests/integration/test_image_api.py). All fixtures are SYNTHETIC.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.main import app
from src.core.database import Base, get_db
from tests.unit.conftest_design_system import make_bundle_zip


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


BASE = "/api/settings/design-systems"


def _import(client, **kwargs):
    zip_bytes = make_bundle_zip(**kwargs.pop("bundle_kwargs", {}))
    data = kwargs.pop("data", None)
    return client.post(
        f"{BASE}/import",
        files={"file": ("acme.zip", zip_bytes, "application/zip")},
        data=data,
    )


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


class TestImportEndpoint:
    def test_import_returns_201_with_detail(self, client):
        resp = _import(client)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["name"] == "Acme Design System"
        assert body["token_count"] >= 3
        assert body["asset_count"] >= 3
        assert body["template_count"] == 2
        assert "SLIDE VISUAL STYLE:" in body["compiled_style_content"]
        # brand assets referenced via the ds-asset namespace
        assert "{{ds-asset:" in body["compiled_style_content"]
        assert body["is_active"] is True
        assert body["is_default"] is False

    def test_import_persists_assets_retrievable_via_serve_endpoint(self, client):
        body = _import(client).json()
        asset = next(a for a in body["assets"] if a["filename"] == "logo.svg")
        resp = client.get(asset["url"])
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("image/svg+xml")

    def test_import_duplicate_name_returns_409(self, client):
        assert _import(client).status_code == 201
        resp = _import(client)
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]

    def test_import_name_override_via_form(self, client):
        assert _import(client).status_code == 201
        resp = _import(client, data={"name": "Acme Copy"})
        assert resp.status_code == 201
        assert resp.json()["name"] == "Acme Copy"

    def test_import_not_a_zip_returns_400(self, client):
        resp = client.post(
            f"{BASE}/import",
            files={"file": ("bad.zip", b"not a zip at all", "application/zip")},
        )
        assert resp.status_code == 400

    def test_import_missing_manifest_returns_400(self, client):
        zip_bytes = make_bundle_zip(include_manifest=False)
        resp = client.post(
            f"{BASE}/import",
            files={"file": ("acme.zip", zip_bytes, "application/zip")},
        )
        assert resp.status_code == 400
        assert "_ds_manifest.json" in resp.json()["detail"]

    def test_import_without_file_returns_422(self, client):
        assert client.post(f"{BASE}/import").status_code == 422


# ---------------------------------------------------------------------------
# List / Get
# ---------------------------------------------------------------------------


class TestListAndGet:
    def test_list_empty(self, client):
        resp = client.get(BASE)
        assert resp.status_code == 200
        assert resp.json() == {"design_systems": [], "total": 0}

    def test_list_returns_summaries(self, client):
        _import(client)
        _import(client, data={"name": "Second DS"})
        resp = client.get(BASE)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        summary = body["design_systems"][0]
        assert {"id", "name", "token_count", "asset_count", "template_count"} <= set(summary)

    def test_get_detail(self, client):
        ds_id = _import(client).json()["id"]
        resp = client.get(f"{BASE}/{ds_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["tokens"]) >= 3
        assert len(body["assets"]) >= 3
        assert body["manifest_json"]["version"] == "1.0.0"

    def test_get_404(self, client):
        assert client.get(f"{BASE}/999999").status_code == 404


# ---------------------------------------------------------------------------
# Create (structured) / Update
# ---------------------------------------------------------------------------


class TestCreateAndUpdate:
    def test_create_structured(self, client):
        resp = client.post(
            BASE,
            json={
                "name": "Structured DS",
                "description": "made in-app",
                "tokens": [{"group": "core", "name": "primary", "value": "#abcdef"}],
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["token_count"] == 1
        assert "--brand-core-primary: #abcdef;" in body["compiled_style_content"]

    def test_create_duplicate_name_409(self, client):
        client.post(BASE, json={"name": "Dup"})
        resp = client.post(BASE, json={"name": "Dup"})
        assert resp.status_code == 409

    def test_update_recompiles_and_bumps_version(self, client):
        create = client.post(
            BASE,
            json={
                "name": "Editable",
                "tokens": [{"group": "core", "name": "primary", "value": "#111111"}],
            },
        )
        ds_id = create.json()["id"]

        resp = client.put(
            f"{BASE}/{ds_id}",
            json={
                "description": "updated",
                "tokens": [{"group": "core", "name": "primary", "value": "#999999"}],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["description"] == "updated"
        assert body["version"] == 2
        assert "--brand-core-primary: #999999;" in body["compiled_style_content"]
        assert "#111111" not in body["compiled_style_content"]

    def test_update_404(self, client):
        assert client.put(f"{BASE}/999999", json={"description": "x"}).status_code == 404


# ---------------------------------------------------------------------------
# Delete (soft) / set-default
# ---------------------------------------------------------------------------


class TestDeleteAndDefault:
    def test_soft_delete_hides_from_list(self, client):
        ds_id = _import(client).json()["id"]
        assert client.delete(f"{BASE}/{ds_id}").status_code == 204
        assert client.get(BASE).json()["total"] == 0
        # include_inactive surfaces it again
        assert client.get(f"{BASE}?include_inactive=true").json()["total"] == 1

    def test_delete_404(self, client):
        assert client.delete(f"{BASE}/999999").status_code == 404

    def test_set_default_single_org_default(self, client):
        first = _import(client).json()["id"]
        second = _import(client, data={"name": "Second"}).json()["id"]

        assert client.post(f"{BASE}/{first}/set-default").json()["is_default"] is True
        # Switching default unsets the previous one.
        assert client.post(f"{BASE}/{second}/set-default").json()["is_default"] is True
        assert client.get(f"{BASE}/{first}").json()["is_default"] is False

    def test_set_default_inactive_returns_400(self, client):
        ds_id = _import(client).json()["id"]
        client.delete(f"{BASE}/{ds_id}")
        assert client.post(f"{BASE}/{ds_id}/set-default").status_code == 400


# ---------------------------------------------------------------------------
# Serve asset
# ---------------------------------------------------------------------------


class TestServeAsset:
    def test_serve_asset_returns_bytes(self, client):
        body = _import(client).json()
        asset = next(a for a in body["assets"] if a["filename"] == "logo.svg")
        resp = client.get(f"{BASE}/{body['id']}/assets/{asset['id']}")
        assert resp.status_code == 200
        assert resp.content  # raw bytes served
        assert resp.headers["content-type"].startswith("image/svg+xml")

    def test_serve_asset_404_for_wrong_ds(self, client):
        body = _import(client).json()
        asset = body["assets"][0]
        assert client.get(f"{BASE}/999999/assets/{asset['id']}").status_code == 404

    def test_svg_asset_forced_to_download(self, client):
        """SVG can carry inline <script>; the serve endpoint must not render it."""
        body = _import(client).json()
        svg = next(a for a in body["assets"] if a["filename"] == "logo.svg")
        resp = client.get(f"{BASE}/{body['id']}/assets/{svg['id']}")
        assert resp.status_code == 200
        assert resp.headers.get("content-disposition") == "attachment"
        assert resp.headers.get("x-content-type-options") == "nosniff"

    def test_raster_asset_served_inline(self, client):
        body = _import(client).json()
        png = next(a for a in body["assets"] if a["filename"] == "hero-bg.png")
        resp = client.get(f"{BASE}/{body['id']}/assets/{png['id']}")
        assert resp.status_code == 200
        assert "content-disposition" not in {k.lower() for k in resp.headers}


# ---------------------------------------------------------------------------
# Reference integrity (design_system_id in agent-config validator)
# ---------------------------------------------------------------------------


class TestReferenceValidation:
    def _patched_db(self, db_session):
        """Patch agent_config.get_db_session to yield the test session."""
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=db_session)
        cm.__exit__ = MagicMock(return_value=False)
        return patch("src.api.routes.agent_config.get_db_session", return_value=cm)

    def test_rejects_unknown_design_system_id(self, db_session):
        from fastapi import HTTPException

        from src.api.routes.agent_config import _validate_references
        from src.api.schemas.agent_config import AgentConfig

        with self._patched_db(db_session):
            with pytest.raises(HTTPException) as exc:
                _validate_references(AgentConfig(design_system_id=4242))
        assert exc.value.status_code == 422
        assert "4242" in exc.value.detail

    def test_accepts_active_design_system_id(self, db_session):
        from src.api.routes.agent_config import _validate_references
        from src.api.schemas.agent_config import AgentConfig
        from src.services.design_system_service import import_bundle

        ds = import_bundle(db_session, zip_bytes=make_bundle_zip(), user="u")
        with self._patched_db(db_session):
            _validate_references(AgentConfig(design_system_id=ds.id))  # no raise

    def test_rejects_soft_deleted_design_system_id(self, db_session):
        from fastapi import HTTPException

        from src.api.routes.agent_config import _validate_references
        from src.api.schemas.agent_config import AgentConfig
        from src.services.design_system_service import import_bundle

        ds = import_bundle(db_session, zip_bytes=make_bundle_zip(), user="u")
        ds.is_active = False
        db_session.commit()
        with self._patched_db(db_session):
            with pytest.raises(HTTPException) as exc:
                _validate_references(AgentConfig(design_system_id=ds.id))
        assert exc.value.status_code == 422


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    def test_legacy_slide_style_reference_still_validates(self, db_session):
        """A slide_style_id-only config path is unchanged by the new DS branch."""
        from src.api.routes.agent_config import _validate_references
        from src.api.schemas.agent_config import AgentConfig
        from src.database.models import SlideStyleLibrary

        style = SlideStyleLibrary(name="Legacy", style_content="body{}", is_active=True)
        db_session.add(style)
        db_session.commit()

        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=db_session)
        cm.__exit__ = MagicMock(return_value=False)
        with patch("src.api.routes.agent_config.get_db_session", return_value=cm):
            _validate_references(AgentConfig(slide_style_id=style.id))  # no raise
