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
# Templates (Phase 4): list + thumbnail endpoints
# ---------------------------------------------------------------------------


def _import_templated(client, name=None):
    from tests.unit.conftest_design_system import templated_bundle_files, templated_manifest

    manifest = templated_manifest()
    if name:
        manifest["name"] = name
    resp = _import(
        client,
        bundle_kwargs={"manifest": manifest, "files": templated_bundle_files()},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestTemplateEndpoints:
    def test_list_templates_returns_entities_with_thumbnail_url(self, client):
        body = _import_templated(client)
        resp = client.get(f"{BASE}/{body['id']}/templates")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        template = data["templates"][0]
        assert template["name"] == "Acme Corporate"
        assert template["description"] == "Cover + agenda, content, closing."
        assert template["entry_path"] == "templates/corporate/index.html"
        assert template["thumbnail_url"] == (
            f"/api/settings/design-systems/{body['id']}/templates/"
            f"{template['id']}/thumbnail"
        )
        # Layout HTML rides only on the dedicated /source JSON endpoint —
        # the listing must not carry it.
        assert "layout_html" not in template

    def test_list_templates_404_for_unknown_design_system(self, client):
        assert client.get(f"{BASE}/999999/templates").status_code == 404

    def test_list_templates_empty_for_system_without_templates(self, client):
        body = _import(client).json()  # default bundle: no folder/entryPath templates
        resp = client.get(f"{BASE}/{body['id']}/templates")
        assert resp.status_code == 200
        assert resp.json() == {"templates": [], "total": 0}

    def test_list_templates_materializes_lazily_for_pre_phase4_rows(self, client, db_session):
        from src.database.models import DesignSystemTemplate

        body = _import_templated(client)
        # Simulate a system imported between Phase 1 and Phase 4: retained file
        # rows exist, but no template entities were materialized.
        db_session.query(DesignSystemTemplate).delete()
        db_session.commit()

        resp = client.get(f"{BASE}/{body['id']}/templates")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["templates"][0]["name"] == "Acme Corporate"

    def test_thumbnail_served_with_image_type_and_nosniff(self, client):
        body = _import_templated(client)
        template = client.get(f"{BASE}/{body['id']}/templates").json()["templates"][0]
        resp = client.get(f"{BASE}/{body['id']}/templates/{template['id']}/thumbnail")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("image/png")
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.content.startswith(b"\x89PNG")

    def test_thumbnail_404_when_template_belongs_to_other_design_system(self, client):
        body_a = _import_templated(client, name="Acme Templated A")
        body_b = _import_templated(client, name="Acme Templated B")
        template_b = client.get(f"{BASE}/{body_b['id']}/templates").json()["templates"][0]
        resp = client.get(f"{BASE}/{body_a['id']}/templates/{template_b['id']}/thumbnail")
        assert resp.status_code == 404

    def test_thumbnail_404_when_template_has_no_preview(self, client):
        from tests.unit.conftest_design_system import templated_bundle_files

        files = templated_bundle_files()
        files.pop("templates/corporate/preview.png")
        from tests.unit.conftest_design_system import templated_manifest

        resp = _import(
            client,
            bundle_kwargs={"manifest": templated_manifest(), "files": files},
        )
        body = resp.json()
        listing = client.get(f"{BASE}/{body['id']}/templates").json()
        template = listing["templates"][0]
        assert template["thumbnail_url"] is None
        resp = client.get(f"{BASE}/{body['id']}/templates/{template['id']}/thumbnail")
        assert resp.status_code == 404


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

    def _templated_ds(self, db_session, name=None):
        from src.services.design_system_service import import_bundle
        from tests.unit.conftest_design_system import (
            templated_bundle_files,
            templated_manifest,
        )

        manifest = templated_manifest()
        if name:
            manifest["name"] = name
        return import_bundle(
            db_session,
            zip_bytes=make_bundle_zip(manifest=manifest, files=templated_bundle_files()),
            user="u",
        )

    def test_valid_template_pin_is_preserved(self, db_session):
        from src.api.routes.agent_config import _validate_references
        from src.api.schemas.agent_config import AgentConfig

        ds = self._templated_ds(db_session)
        config = AgentConfig(design_system_id=ds.id, template_id=ds.templates[0].id)
        with self._patched_db(db_session):
            _validate_references(config)  # no raise
        assert config.template_id == ds.templates[0].id  # kept

    def test_foreign_template_pin_is_cleared_not_rejected(self, db_session, caplog):
        """The template pin is SELF-HEALING at save time (unlike the strict
        library ids): a pin that doesn't belong to the selected design system is
        nulled out + logged, never a 422 — a stale pin must not wedge the
        config."""
        import logging

        from src.api.routes.agent_config import _validate_references
        from src.api.schemas.agent_config import AgentConfig

        ds_a = self._templated_ds(db_session, name="Acme Validator A")
        ds_b = self._templated_ds(db_session, name="Acme Validator B")
        config = AgentConfig(design_system_id=ds_a.id, template_id=ds_b.templates[0].id)
        with self._patched_db(db_session):
            with caplog.at_level(logging.WARNING, logger="src.api.routes.agent_config"):
                _validate_references(config)  # no raise
        assert config.template_id is None
        assert "template" in caplog.text.lower()

    def test_template_pin_without_design_system_is_cleared(self, db_session, caplog):
        import logging

        from src.api.routes.agent_config import _validate_references
        from src.api.schemas.agent_config import AgentConfig

        ds = self._templated_ds(db_session)
        config = AgentConfig(template_id=ds.templates[0].id)
        with self._patched_db(db_session):
            with caplog.at_level(logging.WARNING, logger="src.api.routes.agent_config"):
                _validate_references(config)  # no raise
        assert config.template_id is None
        assert "template" in caplog.text.lower()

    def test_unknown_template_pin_is_cleared(self, db_session, caplog):
        import logging

        from src.api.routes.agent_config import _validate_references
        from src.api.schemas.agent_config import AgentConfig

        ds = self._templated_ds(db_session)
        config = AgentConfig(design_system_id=ds.id, template_id=424242)
        with self._patched_db(db_session):
            with caplog.at_level(logging.WARNING, logger="src.api.routes.agent_config"):
                _validate_references(config)  # no raise
        assert config.template_id is None
        assert "424242" in caplog.text

    def test_reupload_scenario_stale_pin_autoclears_and_put_succeeds(self, db_session):
        """Regression for the wedged-config failure: delete+re-upload of a
        design system re-materializes templates with NEW ids, so a persisted
        config can hold a stale pin. Every later PUT must still succeed, with
        the stale pin auto-cleared, the sanitized config persisted, and the
        effective config returned so the frontend state syncs."""
        from src.database.models import DesignSystemTemplate, UserSession
        from src.services.design_system_templates import materialize_templates

        ds = self._templated_ds(db_session)
        old_template_id = ds.templates[0].id
        db_session.add(UserSession(session_id="sess-reupload"))
        db_session.commit()

        from src.api.main import app  # client fixture app — reuse for clarity

        client = TestClient(app)
        base = "/api/sessions/sess-reupload/agent-config"
        with self._patched_db(db_session):
            # Valid pin round-trips.
            resp = client.put(
                base, json={"design_system_id": ds.id, "template_id": old_template_id}
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["template_id"] == old_template_id

            # Simulate the sanctioned delete+re-upload workflow: template rows
            # are re-materialized with NEW ids. A second (surviving) system
            # keeps the SQLite rowid watermark high so the re-materialized rows
            # genuinely get fresh ids rather than reusing the deleted ones.
            self._templated_ds(db_session, name="Acme Reupload Filler")
            db_session.query(DesignSystemTemplate).filter(
                DesignSystemTemplate.design_system_id == ds.id
            ).delete()
            db_session.commit()
            materialize_templates(ds)
            db_session.commit()
            assert ds.templates[0].id != old_template_id

            # The next PUT (still carrying the stale pin) SUCCEEDS: the pin is
            # auto-cleared in the response AND in the persisted row.
            resp = client.put(
                base, json={"design_system_id": ds.id, "template_id": old_template_id}
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["template_id"] is None
            session_row = (
                db_session.query(UserSession)
                .filter(UserSession.session_id == "sess-reupload")
                .first()
            )
            assert session_row.agent_config["template_id"] is None

            # And a fresh, valid pin still saves normally afterwards.
            resp = client.put(
                base, json={"design_system_id": ds.id, "template_id": ds.templates[0].id}
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["template_id"] == ds.templates[0].id


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


# ---------------------------------------------------------------------------
# Serve asset thumbnail (downscaled grid variant)
# ---------------------------------------------------------------------------


class TestServeAssetThumbnail:
    """Large systems ship hundreds of full-size assets; the detail grid loads
    a <=128px cached PNG variant instead. Security policy identical to the
    full endpoint (nosniff; non-raster forced to download, never rendered)."""

    def _import_with_big_png(self, client):
        from tests.unit.conftest_design_system import (
            SVG_LOGO,
            SYNTHETIC_README,
            SYNTHETIC_SKILL,
            png_bytes,
        )

        files = {
            "assets/logo.svg": SVG_LOGO,
            "assets/backgrounds/hero-bg.png": png_bytes(400, 300),
            "README.md": SYNTHETIC_README,
            "SKILL.md": SYNTHETIC_SKILL,
        }
        return _import(client, bundle_kwargs={"files": files}).json()

    def test_raster_thumbnail_is_downscaled_png(self, client):
        import struct

        body = self._import_with_big_png(client)
        png = next(a for a in body["assets"] if a["filename"] == "hero-bg.png")
        assert png["thumbnail_url"] == f"{png['url']}/thumbnail"
        resp = client.get(png["thumbnail_url"])
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert "content-disposition" not in {k.lower() for k in resp.headers}
        # PNG IHDR dims: downscaled to fit 128, aspect preserved (400x300 -> 128x96)
        assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"
        width, height = struct.unpack(">II", resp.content[16:24])
        assert (width, height) == (128, 96)
        assert len(resp.content) < png["size_bytes"]

    def test_svg_thumbnail_keeps_download_policy(self, client):
        """SVG has no scaled variant (small, and can carry script): the
        endpoint serves the original bytes with the exact full-endpoint
        policy — attachment + nosniff — so no new render surface exists."""
        body = self._import_with_big_png(client)
        svg = next(a for a in body["assets"] if a["filename"] == "logo.svg")
        assert svg["thumbnail_url"] is None  # grid uses the plain url
        resp = client.get(f"{svg['url']}/thumbnail")
        assert resp.status_code == 200
        assert resp.headers.get("content-disposition") == "attachment"
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers["content-type"].startswith("image/svg+xml")

    def test_thumbnail_404_for_wrong_ds(self, client):
        body = self._import_with_big_png(client)
        asset = body["assets"][0]
        resp = client.get(f"{BASE}/999999/assets/{asset['id']}/thumbnail")
        assert resp.status_code == 404

    def test_undecodable_raster_falls_back_to_original_bytes(self, client):
        """Corrupt image bytes must degrade to exactly the pre-thumbnail
        behavior: the original bytes, inline, nosniff."""
        from tests.unit.conftest_design_system import (
            SYNTHETIC_README,
            SYNTHETIC_SKILL,
        )

        files = {
            "assets/broken.png": b"\x89PNG\r\n\x1a\nnot really a png",
            "README.md": SYNTHETIC_README,
            "SKILL.md": SYNTHETIC_SKILL,
        }
        body = _import(client, bundle_kwargs={"files": files}).json()
        broken = next(a for a in body["assets"] if a["filename"] == "broken.png")
        resp = client.get(f"{broken['url']}/thumbnail")
        assert resp.status_code == 200
        assert resp.content == b"\x89PNG\r\n\x1a\nnot really a png"


# ---------------------------------------------------------------------------
# Template source (JSON for the live-rendered preview cards)
# ---------------------------------------------------------------------------


def _import_templated_with_fontface(client):
    """Templated bundle whose token stylesheet ships an @font-face pointing at
    the bundled font file — the real Claude-Design shape. The import rewrite
    turns the src url into a ``{{ds-asset:ID}}`` handle in the stored
    ``token_css``."""
    from tests.unit.conftest_design_system import templated_bundle_files, templated_manifest

    resp = _import(
        client,
        bundle_kwargs={
            "manifest": templated_manifest(),
            "files": templated_bundle_files(),
            "css": (
                "@font-face { font-family: 'Acme Sans'; "
                'src: url("fonts/acme-sans.woff2") format("woff2"); }\n'
                ":root { --brand-core-primary: #123456; }"
            ),
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestTemplateSourceEndpoint:
    """Real Claude Design bundles ship no screenshots; the frontend fetches
    the stored layout as JSON and renders it in a fully-sandboxed iframe.
    JSON keeps the response non-renderable from the app origin (Phase-6
    rule: user markup is never served as text/html)."""

    def test_source_returns_layout_and_token_css_as_json(self, client):
        body = _import_templated(client)
        tmpl = client.get(f"{BASE}/{body['id']}/templates").json()["templates"][0]
        resp = client.get(f"{BASE}/{body['id']}/templates/{tmpl['id']}/source")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")
        data = resp.json()
        assert data["id"] == tmpl["id"]
        assert data["name"] == "Acme Corporate"
        assert "<" in data["layout_html"]  # the stored (rewritten) entry HTML
        assert data["token_css"]  # retained CSS token sources

    def test_source_resolves_asset_placeholders_to_data_uris(self, client, db_session):
        """The live preview renders inside ``sandbox=""`` plus a no-egress CSP:
        the frame can fetch NOTHING, so every ``{{ds-asset:ID}}`` handle must
        arrive as an inline ``data:`` URI (dsv2 battery F8 — raw handles broke
        every image in every card). Resolution is serve-time only: the STORED
        row keeps its handles for the generation pipeline."""
        import base64

        from src.database.models.design_system import DesignSystemTemplate
        from tests.unit.conftest_design_system import SVG_LOGO

        body = _import_templated(client)
        tmpl = client.get(f"{BASE}/{body['id']}/templates").json()["templates"][0]
        resp = client.get(f"{BASE}/{body['id']}/templates/{tmpl['id']}/source")
        assert resp.status_code == 200
        data = resp.json()

        # <img src="{{ds-asset:ID}}"> handles -> byte-exact data: URIs.
        logo_b64 = base64.b64encode(SVG_LOGO).decode()
        assert f"data:image/svg+xml;base64,{logo_b64}" in data["layout_html"]
        # CSS url() handle (the hero background in the template <style>) too.
        assert 'url("data:image/png;base64,' in data["layout_html"]
        # Nothing placeholder-shaped survives into the sandboxed document.
        assert "{{ds-asset:" not in data["layout_html"]

        # Serve-time only: the stored layout keeps its handles for generation.
        stored = db_session.query(DesignSystemTemplate).filter_by(id=tmpl["id"]).one()
        assert "{{ds-asset:" in stored.layout_html

    def test_source_inlines_font_face_sources_in_token_css(self, client):
        """Template-relative @font-face refs are import-rewritten to
        ``{{ds-asset:ID}}`` handles in the stored ``token_css``; the preview CSP
        allows ``font-src data:`` ONLY, so the served source must inline the
        stored font bytes the same way as images."""
        import base64

        body = _import_templated_with_fontface(client)
        tmpl = client.get(f"{BASE}/{body['id']}/templates").json()["templates"][0]
        resp = client.get(f"{BASE}/{body['id']}/templates/{tmpl['id']}/source")
        assert resp.status_code == 200
        data = resp.json()

        font_b64 = base64.b64encode(b"OTTO synthetic-font-bytes").decode()
        assert f"data:font/woff2;base64,{font_b64}" in data["token_css"]
        assert "{{ds-asset:" not in data["token_css"]

    def test_source_neutralizes_unresolvable_asset_ids(self, client, db_session):
        """Graceful degradation: a handle whose asset row no longer exists must
        not crash the card or ride into the frame as fetch-shaped text — it
        degrades to the inert ``data:,`` placeholder (the import rewrite's own
        convention for unresolvable refs), while real handles still resolve."""
        from src.database.models.design_system import DesignSystemTemplate

        body = _import_templated(client)
        tmpl = client.get(f"{BASE}/{body['id']}/templates").json()["templates"][0]

        stored = db_session.query(DesignSystemTemplate).filter_by(id=tmpl["id"]).one()
        stored.layout_html = stored.layout_html.replace(
            "</body>", '<img src="{{ds-asset:987654}}" alt="ghost" /></body>'
        )
        db_session.commit()

        resp = client.get(f"{BASE}/{body['id']}/templates/{tmpl['id']}/source")
        assert resp.status_code == 200
        data = resp.json()
        assert "{{ds-asset:" not in data["layout_html"]
        assert 'src="data:,"' in data["layout_html"]
        # The surviving real assets still resolve to inline bytes.
        assert "data:image/png;base64," in data["layout_html"]

    def test_source_404_for_wrong_ds(self, client):
        body = _import_templated(client)
        tmpl = client.get(f"{BASE}/{body['id']}/templates").json()["templates"][0]
        resp = client.get(f"{BASE}/999999/templates/{tmpl['id']}/source")
        assert resp.status_code == 404

    def test_source_404_for_unknown_template(self, client):
        body = _import_templated(client)
        resp = client.get(f"{BASE}/{body['id']}/templates/999999/source")
        assert resp.status_code == 404


def _bomb_png(width: int, height: int) -> bytes:
    """Tiny-bytes PNG whose HEADER declares huge dimensions (valid CRCs, bogus
    pixel data) — the classic small-payload decompression-bomb shape. PIL's
    ``Image.open`` parses the header fine; any actual decode would fail."""
    import struct
    import zlib

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(b"\x00"))
    iend = chunk(b"IEND", b"")
    return signature + ihdr + idat + iend


class TestThumbnailPixelCeiling:
    """A crafted small-bytes/huge-dimensions image must never buy a pixel
    decode: the header-declared size is checked BEFORE any decode work and
    the endpoint degrades to the existing serve-original fallback — never a
    500, never an unbounded decode. 12000x12000 (144MP) sits above our 64MP
    ceiling but below PIL's own bomb error threshold, so only the explicit
    guard can stop it pre-decode."""

    def _import_with_bomb(self, client):
        from tests.unit.conftest_design_system import (
            SYNTHETIC_README,
            SYNTHETIC_SKILL,
        )

        files = {
            "assets/huge-claim.png": _bomb_png(12000, 12000),
            "README.md": SYNTHETIC_README,
            "SKILL.md": SYNTHETIC_SKILL,
        }
        return _import(client, bundle_kwargs={"files": files}).json()

    def test_oversized_header_dims_skip_decode_and_serve_original(
        self, client, caplog
    ):
        import logging

        body = self._import_with_bomb(client)
        bomb = next(a for a in body["assets"] if a["filename"] == "huge-claim.png")

        with caplog.at_level(logging.WARNING):
            resp = client.get(f"{bomb['url']}/thumbnail")

        assert resp.status_code == 200  # never a 500
        assert resp.content == _bomb_png(12000, 12000)  # original-bytes fallback
        # The CEILING guard (pre-decode) handled it — not a decode error.
        assert any("pixel ceiling" in r.message for r in caplog.records)

    def test_import_records_no_dimensions_for_bomb_headers(self, client):
        body = self._import_with_bomb(client)
        bomb = next(a for a in body["assets"] if a["filename"] == "huge-claim.png")
        assert bomb["width"] is None
        assert bomb["height"] is None
