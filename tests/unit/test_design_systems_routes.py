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
from tests.unit.conftest_design_system import (
    make_bundle_zip,
    make_zip64_header_offset_archive,
)


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

    def test_name_taken_after_the_precheck_returns_409_not_500(self, client, db_session):
        """The RACE path must answer with the same 409 the sequential path does.

        The fail-fast name SELECT is a pre-check, not a lock. Here the name is
        taken AFTER that check and BEFORE the write, so the partial unique index
        ``uq_design_system_name_active`` is what refuses the import — which the
        route previously surfaced as an opaque
        ``500 {"detail":"Failed to import design system"}``.
        """
        from src.database.models.design_system import DesignSystem
        from src.services import design_system_service

        real_collect = design_system_service._collect_assets_and_files

        def _collect_then_take_the_name(*args, **kwargs):
            result = real_collect(*args, **kwargs)
            db_session.add(DesignSystem(name="Acme Design System", is_active=True))
            db_session.flush()
            return result

        with patch.object(
            design_system_service,
            "_collect_assets_and_files",
            _collect_then_take_the_name,
        ):
            resp = _import(client)

        assert resp.status_code == 409, resp.text
        assert "already exists" in resp.json()["detail"]
        assert "Acme Design System" in resp.json()["detail"]

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

    def test_import_hostile_zip64_header_offset_returns_400_not_500(self, client):
        """A 146-byte upload must not be able to choose the status code.

        The archive's central directory carries the ZIP64 offset sentinel plus an extra
        field replacing the local header offset with ``2**64 - 1``. Seeking there raises
        ``OverflowError`` — outside the importer's ``(OSError, ValueError)`` guard, so it
        escaped ``import_bundle`` entirely, missed this route's
        ``DesignSystemImportError`` handler and landed in the catch-all below it as a
        **500**.

        A malformed upload is the caller's to fix, so it has to arrive as a 400 with an
        explanation. Asserted as ``== 400`` rather than ``< 500``: the 500 is the whole
        finding, and a range check would pass on any of the codes that are not the bug.
        """
        resp = client.post(
            f"{BASE}/import",
            files={
                "file": (
                    "hostile.zip",
                    make_zip64_header_offset_archive(),
                    "application/zip",
                )
            },
        )
        assert resp.status_code == 400, resp.text
        assert resp.status_code != 500
        # The generic handler's opaque text is what a 500 would have said; the refusal
        # has to name the entry and the defect instead.
        detail = resp.json()["detail"]
        assert detail != "Failed to import design system"
        assert "local file header" in detail


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


@pytest.fixture(scope="function")
def fk_client(db_engine):
    """A client whose SQLite connection ENFORCES foreign keys.

    The design-system child relationships are declared ``passive_deletes=True``
    with ``ondelete="CASCADE"``, so a HARD delete revokes an asset's bytes via the
    DATABASE's cascade, not via the ORM. SQLite defaults ``PRAGMA foreign_keys``
    to OFF, which would leave that cascade silently inert and make the negative
    control below unable to fail — the orphaned asset row would keep answering
    200. Enabling the pragma makes SQLite enforce the same rule PostgreSQL does
    (the same reason the partial name index is declared with ``sqlite_where``).
    """
    from sqlalchemy import event
    from sqlalchemy import text as sa_text

    @event.listens_for(db_engine, "connect")
    def _enforce_foreign_keys(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    session_local = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = session_local()
    # Fixtures reuse a pooled connection opened before the listener was attached.
    session.execute(sa_text("PRAGMA foreign_keys=ON"))

    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    session.close()
    event.remove(db_engine, "connect", _enforce_foreign_keys)


class TestClearOrgDefault:
    """WD-01: the org default could be SET and SWITCHED, but never REMOVED.

    There was no route and no UI to return to "no default", so the lifecycle was
    asymmetric and the legacy-slide-style fallback — which D4 proved correct — was
    unreachable in practice: withdrawing a default meant DELETING the design system
    or promoting a different one. Clearing is admin-gated exactly like setting,
    because it changes what every user gets by default.
    """

    def test_clearing_returns_the_system_with_is_default_false(self, client):
        ds_id = _import(client).json()["id"]
        assert client.post(f"{BASE}/{ds_id}/set-default").json()["is_default"] is True

        resp = client.post(f"{BASE}/{ds_id}/clear-default")
        assert resp.status_code == 200, resp.text
        assert resp.json()["is_default"] is False

    def test_clearing_leaves_no_org_default_at_all(self, client):
        """The state D4 needs: not "a different default", but none."""
        first = _import(client).json()["id"]
        second = _import(client, data={"name": "Second"}).json()["id"]
        client.post(f"{BASE}/{first}/set-default")

        assert client.post(f"{BASE}/{first}/clear-default").status_code == 200

        listed = client.get(f"{BASE}?include_inactive=true").json()["design_systems"]
        assert [s["id"] for s in listed if s["is_default"]] == []
        assert client.get(f"{BASE}/{second}").json()["is_default"] is False

    def test_generation_falls_back_to_the_legacy_slide_style(self, client, db_session):
        """The consequence that matters (D4's discriminator): with no org default,
        the resolver returns None, so a new session gets no design system and the
        legacy slide-style path runs."""
        from src.core.settings_db import get_default_design_system_id

        ds_id = _import(client).json()["id"]
        client.post(f"{BASE}/{ds_id}/set-default")

        with patch("src.core.settings_db.get_db_session") as mock_db:
            mock_db.return_value.__enter__ = MagicMock(return_value=db_session)
            mock_db.return_value.__exit__ = MagicMock(return_value=False)
            assert get_default_design_system_id() == ds_id  # non-vacuity

            assert client.post(f"{BASE}/{ds_id}/clear-default").status_code == 200
            assert get_default_design_system_id() is None

    def test_clearing_is_idempotent(self, client):
        ds_id = _import(client).json()["id"]
        # Never was the default: clearing is still a no-op success, so a double
        # click cannot produce an error the user has to interpret.
        assert client.post(f"{BASE}/{ds_id}/clear-default").status_code == 200
        assert client.post(f"{BASE}/{ds_id}/clear-default").json()["is_default"] is False

    def test_clearing_an_unknown_design_system_is_404(self, client):
        assert client.post(f"{BASE}/999999/clear-default").status_code == 404

    def test_an_inactive_system_can_still_be_cleared(self, client, db_session):
        """Deliberately asymmetric with set-default, which 400s on an inactive row:
        PROMOTING a tombstone to org-wide state is wrong, but REMOVING org-wide
        state must never be blocked — that direction is always the safe one, and
        refusing it would strand the flag with no way to withdraw it."""
        from src.database.models.design_system import DesignSystem

        ds_id = _import(client).json()["id"]
        # Soft-delete already clears the flag, so force the awkward state directly.
        ds = db_session.query(DesignSystem).filter(DesignSystem.id == ds_id).one()
        ds.is_active = False
        ds.is_default = True
        db_session.commit()

        resp = client.post(f"{BASE}/{ds_id}/clear-default")
        assert resp.status_code == 200, resp.text
        assert resp.json()["is_default"] is False


class TestSoftDeleteRetainsAddressableBytes:
    """A soft-deleted design system is HIDDEN, not REVOKED — and that is the contract.

    WHY THIS IS PINNED: decks generated while a system was live keep
    ``{{ds-asset:ID}}`` handles in their STORED html and css, including
    ``@font-face { src: url('{{ds-asset:N}}') }``. The resolver reads those bytes
    back BY ID at every deck-response boundary (render, export, MCP). If a
    tombstone's bytes started returning 404, every historic deck and every export
    that used that brand would silently lose its fonts and images — a regression
    dressed up as a hardening. ``?hard_delete=true`` is the verb that really
    destroys the bytes, and it is exercised below so the distinction between the
    two verbs stays load-bearing rather than accidental.

    Retention is NOT a disclosure relaxation: every GET on this router is open by
    design (org-shared library), so a tombstone exposes no new data to no new
    principal, and the cross-design-system scoping guard still fails closed on a
    tombstone — also pinned below, in both directions.
    """

    def _asset(self, body, filename):
        return next(a for a in body["assets"] if a["filename"] == filename)

    def test_asset_bytes_are_byte_identical_after_soft_delete(self, client):
        body = _import(client).json()
        logo = self._asset(body, "logo.svg")
        before = client.get(logo["url"])
        assert before.status_code == 200
        assert before.content

        assert client.delete(f"{BASE}/{body['id']}").status_code == 204

        after = client.get(logo["url"])
        assert after.status_code == 200
        assert after.content == before.content
        assert after.headers["content-type"] == before.headers["content-type"]

    def test_asset_thumbnail_still_served_after_soft_delete(self, client):
        body = _import(client).json()
        png = self._asset(body, "hero-bg.png")
        before = client.get(png["thumbnail_url"])
        assert before.status_code == 200

        assert client.delete(f"{BASE}/{body['id']}").status_code == 204

        after = client.get(png["thumbnail_url"])
        assert after.status_code == 200
        assert after.content == before.content

    def test_font_file_bytes_still_served_after_soft_delete(self, client):
        """The `@font-face` case the ruling turns on: a font is a REFERENCE row
        whose bytes resolve through an ownership-checked asset lookup."""
        body = _import(client).json()
        font_url = f"{BASE}/{body['id']}/files/fonts/acme-sans.woff2"
        before = client.get(font_url)
        assert before.status_code == 200
        assert before.content

        assert client.delete(f"{BASE}/{body['id']}").status_code == 204

        after = client.get(font_url)
        assert after.status_code == 200
        assert after.content == before.content

    def test_hard_delete_revokes_the_same_bytes(self, fk_client):
        """The negative control: these routes CAN 404, so every 200 above is a
        property of the SOFT delete rather than of a route that cannot refuse.

        Uses the foreign-key-enforcing client because revocation is the DB's
        ``ON DELETE CASCADE`` doing the work (``passive_deletes=True``)."""
        body = _import(fk_client).json()
        logo = self._asset(body, "logo.svg")
        png = self._asset(body, "hero-bg.png")
        font_url = f"{BASE}/{body['id']}/files/fonts/acme-sans.woff2"
        assert fk_client.get(logo["url"]).status_code == 200

        resp = fk_client.delete(f"{BASE}/{body['id']}?hard_delete=true")
        assert resp.status_code == 204, resp.text

        assert fk_client.get(logo["url"]).status_code == 404
        assert fk_client.get(png["thumbnail_url"]).status_code == 404
        assert fk_client.get(font_url).status_code == 404

    def test_cross_design_system_reads_through_a_tombstone_are_404(self, client):
        """Scoping still fails closed BOTH ways once one side is a tombstone."""
        live = _import(client).json()
        dead = _import(client, data={"name": "Tombstoned"}).json()
        live_asset = self._asset(live, "logo.svg")
        dead_asset = self._asset(dead, "logo.svg")

        assert client.delete(f"{BASE}/{dead['id']}").status_code == 204

        # the tombstone's own id still serves its own bytes...
        assert client.get(dead_asset["url"]).status_code == 200
        # ...but it is not a path to anyone else's, and it is not reachable
        # through a live system's id either.
        assert (
            client.get(f"{BASE}/{dead['id']}/assets/{live_asset['id']}").status_code
            == 404
        )
        assert (
            client.get(f"{BASE}/{live['id']}/assets/{dead_asset['id']}").status_code
            == 404
        )


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


class TestDotPrefixedThumbnailEndToEnd:
    """A real export ships ``templates/<slug>/.thumbnail`` — dot-prefixed, named
    ``thumbnail``, no extension. The picker must get a URL per template and that
    URL must serve the stored bytes."""

    def _import_dot_thumbnail(self, client):
        from tests.unit.conftest_design_system import (
            dot_thumbnail_bundle_files,
            dot_thumbnail_manifest,
        )

        resp = _import(
            client,
            bundle_kwargs={
                "manifest": dot_thumbnail_manifest(),
                "files": dot_thumbnail_bundle_files(),
            },
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    def test_every_template_lists_a_thumbnail_url(self, client):
        from tests.unit.conftest_design_system import DOT_THUMBNAIL_SLUGS

        body = self._import_dot_thumbnail(client)
        data = client.get(f"{BASE}/{body['id']}/templates").json()
        assert data["total"] == len(DOT_THUMBNAIL_SLUGS)
        missing = [t["entry_path"] for t in data["templates"] if not t["thumbnail_url"]]
        assert missing == [], f"templates with no thumbnail_url: {missing}"

    def test_each_thumbnail_url_serves_the_stored_webp_bytes(self, client):
        from tests.unit.conftest_design_system import DOT_THUMBNAIL_SLUGS

        body = self._import_dot_thumbnail(client)
        templates = client.get(f"{BASE}/{body['id']}/templates").json()["templates"]
        served = []
        for template in templates:
            resp = client.get(template["thumbnail_url"])
            assert resp.status_code == 200, template["entry_path"]
            # Sniffed type, served inline (webp is raster-safe), nosniff header.
            assert resp.headers["content-type"].startswith("image/webp")
            assert resp.headers.get("x-content-type-options") == "nosniff"
            assert "content-disposition" not in resp.headers
            assert resp.content.startswith(b"RIFF")
            assert resp.content[8:12] == b"WEBP"
            served.append(resp.content)
        assert len(served) == len(DOT_THUMBNAIL_SLUGS)
        # One distinct screenshot per template folder, not the same blob reused.
        assert len(set(served)) == len(DOT_THUMBNAIL_SLUGS)

    def test_thumbnail_404_across_design_systems(self, client):
        from tests.unit.conftest_design_system import (
            dot_thumbnail_bundle_files,
            dot_thumbnail_manifest,
        )

        body_a = self._import_dot_thumbnail(client)
        manifest_b = dot_thumbnail_manifest()
        manifest_b["name"] = "Acme Dot Thumbnail DS B"
        body_b = _import(
            client,
            bundle_kwargs={
                "manifest": manifest_b,
                "files": dot_thumbnail_bundle_files(),
            },
        ).json()
        template_b = client.get(f"{BASE}/{body_b['id']}/templates").json()["templates"][0]
        resp = client.get(
            f"{BASE}/{body_a['id']}/templates/{template_b['id']}/thumbnail"
        )
        assert resp.status_code == 404


class TestImportReportsDroppedEntries:
    """A thumbnail whose bytes are not a recognizable raster is DROPPED so one junk
    screenshot cannot cost the whole upload — but the caller used to be told the
    import succeeded with no indication anything was ignored. The import response
    carries a non-fatal warning list naming each dropped entry and why."""

    def _bundle_with_unsniffable_thumbnail(self):
        from tests.unit.conftest_design_system import (
            dot_thumbnail_bundle_files,
            dot_thumbnail_manifest,
        )

        files = dot_thumbnail_bundle_files()
        files["templates/corporate/.thumbnail"] = b"this is not an image at all"
        return {"manifest": dot_thumbnail_manifest(), "files": files}

    def test_import_still_succeeds(self, client):
        resp = _import(client, bundle_kwargs=self._bundle_with_unsniffable_thumbnail())
        assert resp.status_code == 201, resp.text

    def test_response_names_the_dropped_entry_and_the_reason(self, client):
        resp = _import(client, bundle_kwargs=self._bundle_with_unsniffable_thumbnail())
        warnings = resp.json()["warnings"]
        paths = [w["path"] for w in warnings]
        assert "templates/corporate/.thumbnail" in paths, warnings
        reason = next(w["reason"] for w in warnings if w["path"].endswith(".thumbnail"))
        assert "image" in reason.lower()

    def test_only_the_unreadable_entry_is_reported(self, client):
        """The other three thumbnails imported fine, so the warning list is not a
        blanket complaint about the bundle."""
        resp = _import(client, bundle_kwargs=self._bundle_with_unsniffable_thumbnail())
        body = resp.json()
        assert len(body["warnings"]) == 1, body["warnings"]
        templates = client.get(f"{BASE}/{body['id']}/templates").json()["templates"]
        with_thumb = [t for t in templates if t["thumbnail_url"]]
        assert len(with_thumb) == 3

    def test_clean_bundle_reports_no_warnings(self, client):
        """Positive control: the field is present and EMPTY for a good bundle, so a
        passing assertion above is not just reading a missing key."""
        from tests.unit.conftest_design_system import (
            dot_thumbnail_bundle_files,
            dot_thumbnail_manifest,
        )

        resp = _import(
            client,
            bundle_kwargs={
                "manifest": dot_thumbnail_manifest(),
                "files": dot_thumbnail_bundle_files(),
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["warnings"] == []


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

    def test_clears_unknown_design_system_id(self, db_session):
        """An unresolvable design-system pin SELF-HEALS (it is not a client
        error: the row can be deleted by its creator under a live session).
        Previously a 422, which wedged every later save — see
        ``TestDeletedDesignSystemAndOtherUsersSessions``."""
        from src.api.routes.agent_config import _validate_references
        from src.api.schemas.agent_config import AgentConfig

        config = AgentConfig(design_system_id=4242)
        with self._patched_db(db_session):
            _validate_references(config)  # no raise
        assert config.design_system_id is None

    def test_accepts_active_design_system_id(self, db_session):
        from src.api.routes.agent_config import _validate_references
        from src.api.schemas.agent_config import AgentConfig
        from src.services.design_system_service import import_bundle

        ds = import_bundle(db_session, zip_bytes=make_bundle_zip(), user="u")
        with self._patched_db(db_session):
            _validate_references(AgentConfig(design_system_id=ds.id))  # no raise

    def test_clears_soft_deleted_design_system_id(self, db_session):
        """A soft-deleted design system is inactive, so the pin self-heals too."""
        from src.api.routes.agent_config import _validate_references
        from src.api.schemas.agent_config import AgentConfig
        from src.services.design_system_service import import_bundle

        ds = import_bundle(db_session, zip_bytes=make_bundle_zip(), user="u")
        ds.is_active = False
        db_session.commit()
        config = AgentConfig(design_system_id=ds.id)
        with self._patched_db(db_session):
            _validate_references(config)  # no raise
        assert config.design_system_id is None

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

    def test_reupload_scenario_stale_pin_autoclears_and_put_succeeds(
        self, db_session, monkeypatch
    ):
        """Regression for the wedged-config failure: delete+re-upload of a
        design system re-materializes templates with NEW ids, so a persisted
        config can hold a stale pin. Every later PUT must still succeed, with
        the stale pin auto-cleared, the sanitized config persisted, and the
        effective config returned so the frontend state syncs."""
        from src.database.models import DesignSystemTemplate, UserSession
        from src.services.design_system_templates import materialize_templates

        monkeypatch.setattr(
            "src.api.routes.agent_config._check_deck_permission_for_session",
            lambda *args, **kwargs: None,
        )

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

    def test_source_does_not_leak_foreign_design_system_asset_bytes(
        self, client, db_session
    ):
        """Confused-deputy guard: the /source route scopes the TEMPLATE row to
        (template_id, design_system_id), but asset resolution must ALSO be scoped
        to the owning design system. Otherwise a crafted bundle whose template
        HTML carries a literal ``{{ds-asset:<foreign_id>}}`` handle (in ``src=``
        AND in CSS ``url()``) would make the preview serve another design
        system's private asset bytes.

        Repro: a Victim DS with distinctive asset bytes, and an Attacker DS whose
        stored template references the Victim's asset id. GET the Attacker's
        /source: the Victim's bytes must be ABSENT and no raw handle may survive
        (it degrades to the inert ``data:,`` placeholder), while the Attacker's
        OWN assets still resolve to inline bytes.
        """
        import base64

        from src.database.models.design_system import (
            DesignSystemAsset,
            DesignSystemTemplate,
        )

        # Victim DS — give its logo distinctive bytes so any leak is unambiguous.
        victim = _import_templated(client, name="Victim DS")
        victim_logo = (
            db_session.query(DesignSystemAsset)
            .filter_by(design_system_id=victim["id"], filename="logo.svg")
            .one()
        )
        victim_secret = b'<svg xmlns="http://www.w3.org/2000/svg"><!--VICTIM-SECRET--></svg>'
        victim_logo.data = victim_secret
        db_session.commit()
        victim_asset_id = victim_logo.id
        victim_secret_b64 = base64.b64encode(victim_secret).decode()

        # Attacker DS — its stored template references the Victim's asset id in
        # both an <img src> and a CSS url() (mirrors a crafted bundle's handles).
        attacker = _import_templated(client, name="Attacker DS")
        attacker_tmpl = client.get(
            f"{BASE}/{attacker['id']}/templates"
        ).json()["templates"][0]
        stored = (
            db_session.query(DesignSystemTemplate)
            .filter_by(id=attacker_tmpl["id"])
            .one()
        )
        steal = (
            '<img src="{{ds-asset:%d}}" alt="stolen" />'
            "<div style=\"background-image:url('{{ds-asset:%d}}')\"></div></body>"
        ) % (victim_asset_id, victim_asset_id)
        stored.layout_html = stored.layout_html.replace("</body>", steal)
        db_session.commit()

        resp = client.get(
            f"{BASE}/{attacker['id']}/templates/{attacker_tmpl['id']}/source"
        )
        assert resp.status_code == 200
        data = resp.json()

        # The Victim's private bytes must NOT appear in the Attacker's preview.
        assert victim_secret_b64 not in data["layout_html"]
        # No fetch-shaped handle may ride into the sandboxed frame.
        assert "{{ds-asset:" not in data["layout_html"]
        # The foreign handle degraded to the inert placeholder (src= and url()).
        assert 'src="data:,"' in data["layout_html"]
        assert "url('data:,')" in data["layout_html"] or 'url("data:,")' in data["layout_html"]
        # The Attacker's OWN assets still resolve to inline bytes (legit case).
        assert "data:image/svg+xml;base64," in data["layout_html"]

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


# ---------------------------------------------------------------------------
# What OTHER users' sessions experience when a design system is DELETED
# ---------------------------------------------------------------------------
#
# The DELETE route is reachable by the row's creator (and by admins), so a
# design system that OTHER users have pinned in their sessions can disappear
# underneath them. These tests pin the parts of that behaviour that were
# measured SAFE, so a future change cannot silently make them unsafe. They do
# NOT assert a policy for the part that is NOT safe (the agent-config PUT 422s
# on a dangling design_system_id) — that is a product decision, reported
# separately rather than invented here.
#
# Measured empirically against a REAL deleted row (soft and hard), not mocks.


class TestDeletedDesignSystemAndOtherUsersSessions:
    """Regression pins for the DELETE path's effect on a foreign session."""

    def _patched_db(self, db_session):
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=db_session)
        cm.__exit__ = MagicMock(return_value=False)
        return patch("src.core.database.get_db_session", return_value=cm)

    def _import(self, db_session, name=None):
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
            user="creator@test.com",
        )

    def _prompt(self, db_session, config):
        from src.services.agent_factory import _get_prompt_content

        with self._patched_db(db_session):
            return _get_prompt_content(config, mode="generate")["system_prompt"]

    @pytest.mark.parametrize("hard", [False, True], ids=["soft_delete", "hard_delete"])
    def test_generation_for_a_deleted_pin_is_the_no_design_system_prompt(
        self, db_session, hard
    ):
        """GENERATION self-heals, and provably so: the assembled prompt is
        BYTE-IDENTICAL to what a session with no design system at all receives.

        Length or "does not crash" would not be enough — a partially-branded
        prompt, or one still carrying {{ds-asset:ID}} handles that can no longer
        resolve, would also "not crash" while sending the model a broken
        reference. Byte identity to the no-DS baseline is what rules that out.
        """
        from src.api.schemas.agent_config import AgentConfig
        from src.database.models import DesignSystem

        ds = self._import(db_session)
        ds_id, template_id = ds.id, ds.templates[0].id

        baseline = self._prompt(db_session, AgentConfig())
        branded = self._prompt(
            db_session, AgentConfig(design_system_id=ds_id, template_id=template_id)
        )
        # The control must actually differ, otherwise the assertion below is
        # vacuous (it would hold for a prompt builder that ignores design
        # systems entirely).
        assert branded != baseline, "control failed: a live design system must brand the prompt"
        assert "[ds-compiler" in branded

        if hard:
            db_session.query(DesignSystem).filter_by(id=ds_id).delete()
        else:
            ds.is_active = False
        db_session.commit()

        dangling = self._prompt(
            db_session, AgentConfig(design_system_id=ds_id, template_id=template_id)
        )
        assert dangling == baseline, (
            "a deleted design system must degrade to EXACTLY the no-design-system "
            "prompt, with no partial branding left behind"
        )
        assert "ds-asset" not in dangling, (
            "the fallback prompt must not carry {{ds-asset:ID}} handles that can "
            "no longer resolve"
        )

    @pytest.mark.parametrize("hard", [False, True], ids=["soft_delete", "hard_delete"])
    def test_deleted_design_system_disappears_from_the_picker_list(
        self, db_session, client, hard
    ):
        """The LIST endpoint stops offering it, so no other user can newly pin a
        deleted system (soft-deleted rows are excluded by default)."""
        from src.database.models import DesignSystem

        ds = self._import(db_session)
        survivor = self._import(db_session, name="Acme Survivor")
        assert {d["id"] for d in client.get("/api/settings/design-systems").json()[
            "design_systems"
        ]} == {ds.id, survivor.id}

        if hard:
            db_session.query(DesignSystem).filter_by(id=ds.id).delete()
        else:
            ds.is_active = False
        db_session.commit()

        visible = {
            d["id"]
            for d in client.get("/api/settings/design-systems").json()["design_systems"]
        }
        assert visible == {survivor.id}, "a deleted design system must leave the picker"

    def test_reading_a_foreign_sessions_agent_config_still_works_after_delete(
        self, db_session, client
    ):
        """B can still LOAD the session rather than being bricked. The GET now
        also SANITISES the dangling pin instead of echoing it, so the dropdown
        shows "None" instead of binding to an id that no longer exists (see
        ``test_config_load_returns_null_for_a_dangling_pin``).

        ``get_db_session`` must be patched alongside the two mocks below, and the
        ``client`` fixture is no substitute for it. That fixture overrides the
        ``get_db`` DEPENDENCY, which this endpoint never declares —
        ``get_agent_config`` at ``src/api/routes/agent_config.py:175`` takes
        ``session_id`` and no ``Depends`` at all — so the override is inert here.
        The endpoint reaches the database through the module-level
        ``get_db_session`` import instead, on two calls: ``_sanitize_stale_pins``
        opens one context (``agent_config.py:57``), and because the pin below IS
        cleared, the GET then persists that repair through ``_save_agent_config``,
        which opens another (``agent_config.py:152``). Patching the single name in
        the route module covers both.

        The sanitiser is the call that breaks unpatched: the GET runs it with no
        guard (``agent_config.py:198``), so its ``OperationalError: connection
        refused`` surfaces as a 500 anywhere nothing answers on the configured
        DATABASE_URL — CI included, which runs plain ``pytest tests/unit`` with no
        database service. The persist call sits behind a deliberate guard that must
        never fail a read (``agent_config.py:214``) and would only degrade to a
        warning, but unpatched it aims a WRITE at whatever DATABASE_URL points to,
        so it belongs on the test's own session as well. A locally running PostgreSQL
        serves both and hides the whole problem, so a green local run is not
        evidence of isolation.

        Patched exactly as every sibling here does it, which is also what makes the
        assertion below meaningful rather than incidental: the sanitiser reads the
        same in-memory SQLite session the rest of the test wrote to, so it clears
        the pin because THAT row is inactive, not because some unrelated database
        never held the row at all.

        What this buys is bounded to the RESPONSE PATH, which no longer depends on
        a reachable database. Request logging and usage logging still schedule
        best-effort background writes against DATABASE_URL
        (``src/api/middleware/request_logging.py:112`` and
        ``src/api/services/usage_events.py:47``); each swallows its own failure and
        neither feeds the response, so whether they connect is immaterial here.
        """
        from src.database.models import UserSession

        ds = self._import(db_session)
        ds_id, template_id = ds.id, ds.templates[0].id
        db_session.add(
            UserSession(
                session_id="sess-foreign",
                created_by="user-b@test.com",
                agent_config={"design_system_id": ds_id, "template_id": template_id},
            )
        )
        db_session.commit()

        ds.is_active = False
        db_session.commit()

        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=db_session)
        cm.__exit__ = MagicMock(return_value=False)
        with patch(
            "src.api.routes.agent_config._check_deck_permission_for_session",
            lambda *a, **k: None,
        ), patch("src.api.routes.agent_config.get_db_session", return_value=cm), patch(
            "src.api.routes.agent_config.get_session_manager"
        ) as mgr:
            mgr.return_value.get_session.return_value = {
                "session_id": "sess-foreign",
                "agent_config": {
                    "design_system_id": ds_id,
                    "template_id": template_id,
                },
            }
            resp = client.get("/api/sessions/sess-foreign/agent-config")

        assert resp.status_code == 200, resp.text
        assert resp.json()["design_system_id"] is None

    def test_template_pin_whose_parent_design_system_is_gone_is_auto_cleared(
        self, db_session
    ):
        """A template pin with NO surviving parent selection self-heals.

        This is the half of the Phase 4 auto-clear that DOES cover deletion: once
        ``design_system_id`` is absent, the stale ``template_id`` is cleared in
        place instead of rejected. (When the dangling design_system_id is ALSO
        still present, the strict design-system branch raises FIRST and this
        clear never runs — see the reported finding.)
        """
        from src.api.routes.agent_config import _validate_references
        from src.api.schemas.agent_config import AgentConfig
        from src.database.models import DesignSystem

        ds = self._import(db_session)
        template_id = ds.templates[0].id
        db_session.query(DesignSystem).filter_by(id=ds.id).delete()
        db_session.commit()

        config = AgentConfig(template_id=template_id)
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=db_session)
        cm.__exit__ = MagicMock(return_value=False)
        with patch("src.api.routes.agent_config.get_db_session", return_value=cm):
            _validate_references(config)  # must not raise
        assert config.template_id is None

    # --- A DANGLING design_system_id SELF-HEALS (product owner's decision) ---
    #
    # The previous round recorded, as characterization only, that the strict
    # design-system branch 422s a config carrying a deleted ``design_system_id``.
    # The product consequence was severe and is now ruled out: because the
    # frontend PUTs the WHOLE config, user A pinning a design system whose creator
    # later deletes it could no longer change slide style, deck prompt, template,
    # tools or model — every agent-config save failed 422 — and the dropdown
    # rendered blank with no explanation. Generation already degraded correctly to
    # the no-DS prompt (pinned above), so the pin was purely destructive.
    #
    # The design system pin now behaves EXACTLY like the template pin one branch
    # below: cleared in place with a warning, config persisted and returned
    # sanitized, 200. These tests are the deliberate replacement of that
    # characterization.

    @pytest.mark.parametrize("hard", [False, True], ids=["soft_delete", "hard_delete"])
    def test_dangling_design_system_pin_is_cleared_not_rejected(self, db_session, hard):
        """(i) The core reversal: validation SANITIZES instead of raising."""
        from src.api.routes.agent_config import _validate_references
        from src.api.schemas.agent_config import AgentConfig
        from src.database.models import DesignSystem

        ds = self._import(db_session)
        ds_id, template_id = ds.id, ds.templates[0].id
        if hard:
            db_session.query(DesignSystem).filter_by(id=ds_id).delete()
        else:
            ds.is_active = False
        db_session.commit()

        config = AgentConfig(design_system_id=ds_id, template_id=template_id)
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=db_session)
        cm.__exit__ = MagicMock(return_value=False)
        with patch("src.api.routes.agent_config.get_db_session", return_value=cm):
            _validate_references(config)  # must NOT raise

        assert config.design_system_id is None, "stale design-system pin was not cleared"
        # Its template pin cannot outlive it — the parent selection is gone.
        assert config.template_id is None

    def test_put_changing_only_slide_style_succeeds_and_persists(self, db_session, client):
        """(i) THE user-facing scenario: user A changes ONLY the slide style while
        holding a dangling design-system pin. It must save."""
        from src.api.schemas.agent_config import AgentConfig
        from src.database.models import DesignSystem, SlideStyleLibrary, UserSession

        ds = self._import(db_session)
        ds_id = ds.id
        style = SlideStyleLibrary(name="Acme Chosen Style", style_content="s")
        db_session.add(style)
        db_session.add(
            UserSession(
                session_id="sess-heal",
                created_by="user-a@test.com",
                agent_config={"design_system_id": ds_id, "tools": []},
            )
        )
        db_session.commit()
        style_id = style.id

        db_session.query(DesignSystem).filter_by(id=ds_id).delete()
        db_session.commit()

        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=db_session)
        cm.__exit__ = MagicMock(return_value=False)
        with patch(
            "src.api.routes.agent_config._check_deck_permission_for_session",
            lambda *a, **k: None,
        ), patch("src.api.routes.agent_config.get_db_session", return_value=cm):
            resp = client.put(
                "/api/sessions/sess-heal/agent-config",
                json={
                    "tools": [],
                    "design_system_id": ds_id,
                    "slide_style_id": style_id,
                },
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        # The change the user actually made persisted...
        assert body["slide_style_id"] == style_id
        # ...and the stale pin came back SANITISED, so the frontend state syncs.
        assert body["design_system_id"] is None

        stored = (
            db_session.query(UserSession)
            .filter_by(session_id="sess-heal")
            .one()
            .agent_config
        )
        assert stored["slide_style_id"] == style_id
        assert stored["design_system_id"] is None, (
            "the sanitised config must be what is PERSISTED, not just returned"
        )
        _ = AgentConfig.model_validate(stored)  # still a valid config

    def test_config_load_returns_null_for_a_dangling_pin(self, db_session, client):
        """(ii) LOAD self-heals too, so the dropdown shows 'None' rather than a
        blank select bound to an id that no longer exists."""
        from src.database.models import DesignSystem, UserSession

        ds = self._import(db_session)
        ds_id, template_id = ds.id, ds.templates[0].id
        db_session.add(
            UserSession(
                session_id="sess-load-heal",
                created_by="user-b@test.com",
                agent_config={"design_system_id": ds_id, "template_id": template_id},
            )
        )
        db_session.commit()
        db_session.query(DesignSystem).filter_by(id=ds_id).delete()
        db_session.commit()

        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=db_session)
        cm.__exit__ = MagicMock(return_value=False)
        with patch(
            "src.api.routes.agent_config._check_deck_permission_for_session",
            lambda *a, **k: None,
        ), patch("src.api.routes.agent_config.get_db_session", return_value=cm), patch(
            "src.api.routes.agent_config.get_session_manager"
        ) as mgr:
            mgr.return_value.get_session.return_value = {
                "session_id": "sess-load-heal",
                "agent_config": {
                    "design_system_id": ds_id,
                    "template_id": template_id,
                },
            }
            resp = client.get("/api/sessions/sess-load-heal/agent-config")

        assert resp.status_code == 200, resp.text
        assert resp.json()["design_system_id"] is None
        assert resp.json()["template_id"] is None

    # --- GET must PERSIST the heal, not merely mask it ----------------------
    #
    # Cross-vendor review: the GET sanitized a DETACHED Pydantic object and
    # returned it without saving, so the stored row kept the dangling ids
    # forever. The response looked healed while the database was not, and every
    # subsequent GET re-emitted the same warnings.
    #
    # A side-effecting read is not unprecedented here: the compiler already does
    # lazy recompute-on-read for compiled_style_content. This follows that
    # precedent, with three constraints — write ONLY when something was actually
    # cleared, stay idempotent, and degrade to the old masking behaviour rather
    # than 500ing the GET if the write fails.

    def _committing_db(self, db_session):
        """A ``get_db_session`` stand-in that COMMITS on exit, like the real one.

        ``MagicMock.__exit__`` returning False does not commit, so a write made
        inside the block stays pending and ``expire_all()`` discards it — which
        reads exactly like "the route never persisted" while the route is in fact
        correct. Any test asserting on the stored ROW must use this.
        """
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=db_session)

        def _exit(*_args):
            db_session.commit()
            return False

        cm.__exit__ = MagicMock(side_effect=_exit)
        return cm

    def test_get_persists_the_healed_config(self, db_session, client):
        """The ROW itself must be clean after one GET."""
        from src.database.models import DesignSystem, UserSession

        ds = self._import(db_session)
        ds_id, template_id = ds.id, ds.templates[0].id
        session_row = UserSession(
            session_id="sess-persist-heal",
            created_by="user-a@test.com",
            agent_config={
                "tools": [],
                "design_system_id": ds_id,
                "template_id": template_id,
            },
        )
        db_session.add(session_row)
        db_session.commit()
        db_session.query(DesignSystem).filter_by(id=ds_id).delete()
        db_session.commit()

        cm = self._committing_db(db_session)
        with patch(
            "src.api.routes.agent_config._check_deck_permission_for_session",
            lambda *a, **k: None,
        ), patch("src.api.routes.agent_config.get_db_session", return_value=cm), patch(
            "src.api.routes.agent_config.get_session_manager"
        ) as mgr:
            mgr.return_value.get_session.return_value = {
                "session_id": "sess-persist-heal",
                "agent_config": {
                    "tools": [],
                    "design_system_id": ds_id,
                    "template_id": template_id,
                },
            }
            resp = client.get("/api/sessions/sess-persist-heal/agent-config")

        assert resp.status_code == 200, resp.text
        assert resp.json()["design_system_id"] is None

        db_session.expire_all()
        stored = (
            db_session.query(UserSession)
            .filter_by(session_id="sess-persist-heal")
            .one()
            .agent_config
        )
        assert stored["design_system_id"] is None, (
            f"the GET masked the stale pin instead of persisting the heal: {stored}"
        )
        assert stored["template_id"] is None

    def test_second_get_emits_no_warning(self, db_session, client, caplog):
        """Because the row is genuinely healed, the second read is silent — the
        observable difference between healing and masking."""
        import logging

        from src.database.models import DesignSystem, UserSession

        ds = self._import(db_session)
        ds_id = ds.id
        db_session.add(
            UserSession(
                session_id="sess-quiet-heal",
                created_by="user-a@test.com",
                agent_config={"tools": [], "design_system_id": ds_id},
            )
        )
        db_session.commit()
        db_session.query(DesignSystem).filter_by(id=ds_id).delete()
        db_session.commit()

        cm = self._committing_db(db_session)

        def _do_get():
            with patch(
                "src.api.routes.agent_config._check_deck_permission_for_session",
                lambda *a, **k: None,
            ), patch(
                "src.api.routes.agent_config.get_db_session", return_value=cm
            ), patch("src.api.routes.agent_config.get_session_manager") as mgr:
                db_session.expire_all()
                current = (
                    db_session.query(UserSession)
                    .filter_by(session_id="sess-quiet-heal")
                    .one()
                    .agent_config
                )
                mgr.return_value.get_session.return_value = {
                    "session_id": "sess-quiet-heal",
                    "agent_config": current,
                }
                return client.get("/api/sessions/sess-quiet-heal/agent-config")

        with caplog.at_level(logging.WARNING, logger="src.api.routes.agent_config"):
            first = _do_get()
        assert first.status_code == 200
        assert any(
            str(ds_id) in record.getMessage() for record in caplog.records
        ), "the FIRST get should have warned about the stale id"

        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="src.api.routes.agent_config"):
            second = _do_get()
        assert second.status_code == 200
        assert second.json()["design_system_id"] is None
        assert [r.getMessage() for r in caplog.records] == [], (
            "a second GET still warned, so the row was not actually healed"
        )

    def test_clean_read_performs_no_write(self, db_session, client):
        """Never write on a clean read: reads stay reads unless there is a repair
        to make."""
        from src.database.models import UserSession

        ds = self._import(db_session)
        ds_id, template_id = ds.id, ds.templates[0].id  # both VALID
        db_session.add(
            UserSession(
                session_id="sess-clean-read",
                created_by="user-a@test.com",
                agent_config={
                    "tools": [],
                    "design_system_id": ds_id,
                    "template_id": template_id,
                },
            )
        )
        db_session.commit()

        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=db_session)
        cm.__exit__ = MagicMock(return_value=False)
        with patch(
            "src.api.routes.agent_config._check_deck_permission_for_session",
            lambda *a, **k: None,
        ), patch("src.api.routes.agent_config.get_db_session", return_value=cm), patch(
            "src.api.routes.agent_config.get_session_manager"
        ) as mgr, patch(
            "src.api.routes.agent_config._save_agent_config"
        ) as save:
            mgr.return_value.get_session.return_value = {
                "session_id": "sess-clean-read",
                "agent_config": {
                    "tools": [],
                    "design_system_id": ds_id,
                    "template_id": template_id,
                },
            }
            resp = client.get("/api/sessions/sess-clean-read/agent-config")

        assert resp.status_code == 200, resp.text
        assert resp.json()["design_system_id"] == ds_id
        save.assert_not_called()

    def test_a_failed_persist_degrades_to_masking_not_a_500(self, db_session, client):
        """If the repair write fails, the READ must still succeed with the
        sanitised view — never bubble a 500 out of a GET."""
        from src.database.models import DesignSystem, UserSession

        ds = self._import(db_session)
        ds_id = ds.id
        db_session.add(
            UserSession(
                session_id="sess-heal-fails",
                created_by="user-a@test.com",
                agent_config={"tools": [], "design_system_id": ds_id},
            )
        )
        db_session.commit()
        db_session.query(DesignSystem).filter_by(id=ds_id).delete()
        db_session.commit()

        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=db_session)
        cm.__exit__ = MagicMock(return_value=False)
        with patch(
            "src.api.routes.agent_config._check_deck_permission_for_session",
            lambda *a, **k: None,
        ), patch("src.api.routes.agent_config.get_db_session", return_value=cm), patch(
            "src.api.routes.agent_config.get_session_manager"
        ) as mgr, patch(
            "src.api.routes.agent_config._save_agent_config",
            side_effect=RuntimeError("write refused"),
        ):
            mgr.return_value.get_session.return_value = {
                "session_id": "sess-heal-fails",
                "agent_config": {"tools": [], "design_system_id": ds_id},
            }
            resp = client.get("/api/sessions/sess-heal-fails/agent-config")

        assert resp.status_code == 200, resp.text
        assert resp.json()["design_system_id"] is None

    def test_put_with_both_style_sources_normalises_to_design_system(
        self, db_session, client
    ):
        """Item 6, at the ROUTE: an API/MCP caller sending BOTH gets a
        deterministic design-system-wins result, persisted, with 200 — not a 422
        that would wedge legacy both-set rows on every save."""
        from src.database.models import SlideStyleLibrary, UserSession

        ds = self._import(db_session)
        ds_id = ds.id
        style = SlideStyleLibrary(name="Acme Both Style", style_content="s")
        db_session.add(style)
        db_session.add(
            UserSession(
                session_id="sess-both",
                created_by="api-caller@test.com",
                agent_config={"tools": []},
            )
        )
        db_session.commit()
        style_id = style.id

        cm = self._committing_db(db_session)
        with patch(
            "src.api.routes.agent_config._check_deck_permission_for_session",
            lambda *a, **k: None,
        ), patch("src.api.routes.agent_config.get_db_session", return_value=cm):
            resp = client.put(
                "/api/sessions/sess-both/agent-config",
                json={
                    "tools": [],
                    "design_system_id": ds_id,
                    "slide_style_id": style_id,
                },
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["design_system_id"] == ds_id
        assert body["slide_style_id"] is None, "both sources were persisted"

        db_session.expire_all()
        stored = (
            db_session.query(UserSession)
            .filter_by(session_id="sess-both")
            .one()
            .agent_config
        )
        assert stored["design_system_id"] == ds_id
        assert stored["slide_style_id"] is None

    def test_put_style_with_a_dangling_design_system_keeps_the_style(
        self, db_session, client
    ):
        """The ORDERING that makes exclusivity safe. Normalising BEFORE reference
        validation would drop a good slide style for a design system that is
        about to be cleared as dangling, leaving the user with NEITHER."""
        from src.database.models import DesignSystem, SlideStyleLibrary, UserSession

        ds = self._import(db_session)
        ds_id = ds.id
        style = SlideStyleLibrary(name="Acme Order Style", style_content="s")
        db_session.add(style)
        db_session.add(
            UserSession(
                session_id="sess-order",
                created_by="user-a@test.com",
                agent_config={"tools": [], "design_system_id": ds_id},
            )
        )
        db_session.commit()
        style_id = style.id
        db_session.query(DesignSystem).filter_by(id=ds_id).delete()
        db_session.commit()

        cm = self._committing_db(db_session)
        with patch(
            "src.api.routes.agent_config._check_deck_permission_for_session",
            lambda *a, **k: None,
        ), patch("src.api.routes.agent_config.get_db_session", return_value=cm):
            resp = client.put(
                "/api/sessions/sess-order/agent-config",
                json={
                    "tools": [],
                    "design_system_id": ds_id,
                    "slide_style_id": style_id,
                },
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["design_system_id"] is None, "the dangling pin was not cleared"
        assert body["slide_style_id"] == style_id, (
            "the user's slide style was dropped for a design system that no "
            "longer exists — they end up with no style source at all"
        )

    def test_clearing_a_dangling_pin_logs_a_warning_with_ids(self, db_session, client, caplog):
        """(iii) The clear is observable: the warning names the stale id AND the
        session, so support can tell why a user's selection disappeared."""
        import logging

        from src.database.models import DesignSystem, UserSession

        ds = self._import(db_session)
        ds_id = ds.id
        db_session.add(
            UserSession(
                session_id="sess-warn",
                created_by="user-a@test.com",
                agent_config={"design_system_id": ds_id, "tools": []},
            )
        )
        db_session.commit()
        db_session.query(DesignSystem).filter_by(id=ds_id).delete()
        db_session.commit()

        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=db_session)
        cm.__exit__ = MagicMock(return_value=False)
        with caplog.at_level(logging.WARNING, logger="src.api.routes.agent_config"):
            with patch(
                "src.api.routes.agent_config._check_deck_permission_for_session",
                lambda *a, **k: None,
            ), patch("src.api.routes.agent_config.get_db_session", return_value=cm):
                resp = client.put(
                    "/api/sessions/sess-warn/agent-config",
                    json={"tools": [], "design_system_id": ds_id},
                )

        assert resp.status_code == 200, resp.text
        warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert any(str(ds_id) in message for message in warnings), (
            f"no warning named the stale design-system id: {warnings}"
        )
        assert any("sess-warn" in message for message in warnings), (
            f"no warning named the session: {warnings}"
        )

    def test_a_valid_design_system_id_is_never_cleared(self, db_session):
        """(iv) The guard must be surgical: a live pin survives untouched, so
        this is a self-heal and not a blanket "clear the design system"."""
        from src.api.routes.agent_config import _validate_references
        from src.api.schemas.agent_config import AgentConfig

        ds = self._import(db_session)
        ds_id, template_id = ds.id, ds.templates[0].id

        config = AgentConfig(design_system_id=ds_id, template_id=template_id)
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=db_session)
        cm.__exit__ = MagicMock(return_value=False)
        with patch("src.api.routes.agent_config.get_db_session", return_value=cm):
            _validate_references(config)

        assert config.design_system_id == ds_id, "a LIVE design system was cleared"
        assert config.template_id == template_id, "a valid template pin was cleared"

    def test_other_strict_references_still_reject(self, db_session):
        """The leniency is scoped to design_system_id (which a foreign user can
        delete underneath you). A bogus slide style or deck prompt is a CLIENT
        error and still 422s, so this change does not silently widen input."""
        from fastapi import HTTPException

        from src.api.routes.agent_config import _validate_references
        from src.api.schemas.agent_config import AgentConfig

        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=db_session)
        cm.__exit__ = MagicMock(return_value=False)
        for field in ("slide_style_id", "deck_prompt_id"):
            config = AgentConfig(**{field: 987654})
            with patch("src.api.routes.agent_config.get_db_session", return_value=cm):
                with pytest.raises(HTTPException) as exc:
                    _validate_references(config)
            assert exc.value.status_code == 422, field
            assert "987654" in exc.value.detail
