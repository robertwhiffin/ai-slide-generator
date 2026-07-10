"""Unit tests for the Design System bundle importer + asset retrieval (Phase 3).

The importer accepts a ``.zip`` design-system project (``_ds_manifest.json`` +
``colors_and_type.css`` + ``fonts/`` + ``assets/**``), validates it, stores the
design system + tokens + assets in Lakebase, and compiles the prompt artifact.

All fixtures are SYNTHETIC (fake "Acme" brand, dummy hex, placeholder bytes) —
no real brand content, per the public-repo hygiene rule.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register models with Base.metadata
from src.core.database import Base
from tests.unit.conftest_design_system import make_bundle_zip


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


# ---------------------------------------------------------------------------
# Happy path: end-to-end import -> store -> recompute
# ---------------------------------------------------------------------------


class TestImportHappyPath:
    def test_import_creates_design_system(self, session):
        from src.services.design_system_service import import_bundle

        ds = import_bundle(session, zip_bytes=make_bundle_zip(), user="tester@example.com")

        assert ds.id is not None
        assert ds.name == "Acme Design System"
        assert ds.created_by == "tester@example.com"
        assert ds.is_active is True
        assert ds.published is False
        assert ds.is_default is False
        # The bundle's semantic version is preserved in the manifest.
        assert ds.manifest_json["version"] == "1.0.0"

    def test_import_stores_tokens_from_manifest_and_css(self, session):
        from src.database.models.design_system import DesignSystemToken
        from src.services.design_system_service import import_bundle

        ds = import_bundle(session, zip_bytes=make_bundle_zip(), user="u")

        tokens = session.query(DesignSystemToken).filter_by(design_system_id=ds.id).all()
        by_key = {(t.group, t.name): t.value for t in tokens}
        # From _ds_manifest.json tokens[]
        assert by_key[("core", "primary")] == "#123456"
        assert by_key[("spacing", "md")] == "16px"
        # From colors_and_type.css :root vars (the --brand-<group>-<name> convention)
        assert by_key[("accents", "lava")] == "#EB4A34"
        # A non-prefixed type var lands in the 'type' group.
        assert ("type", "heading-font") in by_key

    def test_import_stores_binary_assets_and_skips_preview_and_template_shot(self, session):
        from src.database.models.design_system import DesignSystemAsset
        from src.services.design_system_service import import_bundle

        ds = import_bundle(session, zip_bytes=make_bundle_zip(), user="u")

        assets = session.query(DesignSystemAsset).filter_by(design_system_id=ds.id).all()
        by_name = {a.filename: a for a in assets}
        # fonts/ -> kind=font, bytes stored
        assert by_name["acme-sans.woff2"].kind == "font"
        assert by_name["acme-sans.woff2"].data == b"OTTO synthetic-font-bytes"
        # assets/logo.svg -> image asset
        assert by_name["logo.svg"].kind == "logo"
        assert by_name["logo.svg"].mime == "image/svg+xml"
        # backgrounds/hero-bg.png -> background, with intrinsic dimensions
        assert by_name["hero-bg.png"].kind == "background"
        assert by_name["hero-bg.png"].width == 16
        # template screenshots and previews are NOT stored
        assert "title-shot.png" not in by_name
        assert "preview.png" not in by_name

    def test_import_populates_compiled_style_content(self, session):
        from src.database.models.design_system import DesignSystemAsset
        from src.services.design_system_service import import_bundle

        ds = import_bundle(session, zip_bytes=make_bundle_zip(), user="u")

        assert ds.compiled_style_content
        assert "SLIDE VISUAL STYLE:" in ds.compiled_style_content
        assert "--brand-core-primary: #123456;" in ds.compiled_style_content
        # Brand IMAGE assets are fetched on demand via the search_brand_assets tool
        # (the compiled prompt carries the contract), NOT enumerated by id.
        assert "search_brand_assets" in ds.compiled_style_content
        logo = session.query(DesignSystemAsset).filter_by(
            design_system_id=ds.id, filename="logo.svg"
        ).one()
        assert f"{{{{ds-asset:{logo.id}}}}}" not in ds.compiled_style_content
        # Fonts ARE wired inline via @font-face, referenced by their real DB id.
        font = session.query(DesignSystemAsset).filter_by(
            design_system_id=ds.id, filename="acme-sans.woff2"
        ).one()
        assert f"{{{{ds-asset:{font.id}}}}}" in ds.compiled_style_content
        # Uses the ds-asset namespace, never the unrelated image namespace.
        assert "{{image:" not in ds.compiled_style_content

    def test_import_handles_wrapping_root_folder(self, session):
        """A bundle zipped with a top-level directory still imports."""
        from src.services.design_system_service import import_bundle

        zip_bytes = make_bundle_zip(root_prefix="acme-bundle/")
        ds = import_bundle(session, zip_bytes=zip_bytes, user="u")
        assert ds.name == "Acme Design System"
        assert len(ds.tokens) >= 3
        assert len(ds.assets) >= 3

    def test_name_override_wins_over_manifest(self, session):
        from src.services.design_system_service import import_bundle

        ds = import_bundle(
            session, zip_bytes=make_bundle_zip(), user="u", name_override="Renamed DS"
        )
        assert ds.name == "Renamed DS"


# ---------------------------------------------------------------------------
# Validation / malformed bundles -> clear errors
# ---------------------------------------------------------------------------


class TestImportValidation:
    def test_not_a_zip_raises_import_error(self, session):
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        with pytest.raises(DesignSystemImportError):
            import_bundle(session, zip_bytes=b"this is not a zip", user="u")

    def test_missing_manifest_raises_import_error(self, session):
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        zip_bytes = make_bundle_zip(include_manifest=False)
        with pytest.raises(DesignSystemImportError) as exc:
            import_bundle(session, zip_bytes=zip_bytes, user="u")
        assert "_ds_manifest.json" in str(exc.value)

    def test_invalid_manifest_json_raises_import_error(self, session):
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        zip_bytes = make_bundle_zip(manifest="{not valid json")
        with pytest.raises(DesignSystemImportError):
            import_bundle(session, zip_bytes=zip_bytes, user="u")

    def test_per_asset_size_limit_enforced(self, session):
        from src.database.models.design_system import MAX_ASSET_SIZE_BYTES
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        big = b"x" * (MAX_ASSET_SIZE_BYTES + 1)
        zip_bytes = make_bundle_zip(files={"assets/huge.png": big})
        with pytest.raises(DesignSystemImportError) as exc:
            import_bundle(session, zip_bytes=zip_bytes, user="u")
        assert "too large" in str(exc.value).lower()

    def test_per_bundle_size_limit_enforced(self, session):
        from src.database.models.design_system import (
            MAX_ASSET_SIZE_BYTES,
            MAX_BUNDLE_SIZE_BYTES,
        )
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        # Several individually-legal assets whose sum exceeds the bundle cap.
        chunk = b"y" * (MAX_ASSET_SIZE_BYTES - 1)
        count = (MAX_BUNDLE_SIZE_BYTES // len(chunk)) + 2
        files = {f"assets/img-{i}.png": chunk for i in range(count)}
        zip_bytes = make_bundle_zip(files=files)
        with pytest.raises(DesignSystemImportError) as exc:
            import_bundle(session, zip_bytes=zip_bytes, user="u")
        assert "bundle" in str(exc.value).lower()

    def test_oversized_manifest_rejected_before_read(self, session):
        """Decompression-bomb guard: a manifest whose declared uncompressed size
        exceeds the per-asset limit is rejected BEFORE zf.read materialises it."""
        from src.database.models.design_system import MAX_ASSET_SIZE_BYTES
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        # Oversized (and never even parsed — the size guard fires first).
        huge_manifest = "{" + (" " * (MAX_ASSET_SIZE_BYTES + 1))
        zip_bytes = make_bundle_zip(manifest=huge_manifest)
        with pytest.raises(DesignSystemImportError) as exc:
            import_bundle(session, zip_bytes=zip_bytes, user="u")
        assert "too large" in str(exc.value).lower()

    def test_oversized_css_rejected_before_read(self, session):
        """Decompression-bomb guard: an oversized globalCssPaths/colors_and_type.css
        entry is rejected BEFORE zf.read materialises it."""
        from src.database.models.design_system import MAX_ASSET_SIZE_BYTES
        from src.services.design_system_service import DesignSystemImportError, import_bundle

        huge_css = ":root{}\n/*" + ("a" * (MAX_ASSET_SIZE_BYTES + 1)) + "*/"
        zip_bytes = make_bundle_zip(css=huge_css)
        with pytest.raises(DesignSystemImportError) as exc:
            import_bundle(session, zip_bytes=zip_bytes, user="u")
        assert "too large" in str(exc.value).lower()

    def test_duplicate_name_raises_conflict(self, session):
        from src.services.design_system_service import (
            DesignSystemNameConflictError,
            import_bundle,
        )

        import_bundle(session, zip_bytes=make_bundle_zip(), user="u")
        with pytest.raises(DesignSystemNameConflictError):
            import_bundle(session, zip_bytes=make_bundle_zip(), user="u")


# ---------------------------------------------------------------------------
# Asset retrieval (used by the {{ds-asset:ID}} resolver + serve endpoint)
# ---------------------------------------------------------------------------


class TestGetAssetBase64:
    def test_returns_base64_and_mime(self, session):
        import base64

        from src.database.models.design_system import DesignSystemAsset
        from src.services.design_system_service import get_asset_base64, import_bundle

        ds = import_bundle(session, zip_bytes=make_bundle_zip(), user="u")
        logo = session.query(DesignSystemAsset).filter_by(
            design_system_id=ds.id, filename="logo.svg"
        ).one()

        b64, mime = get_asset_base64(session, logo.id, design_system_id=ds.id)
        assert mime == "image/svg+xml"
        assert base64.b64decode(b64) == logo.data

    def test_missing_asset_raises(self, session):
        from src.services.design_system_service import get_asset_base64

        with pytest.raises(ValueError):
            get_asset_base64(session, 999999, design_system_id=1)

    def test_foreign_design_system_id_raises_not_found(self, session):
        """Confused-deputy guard: an asset id fetched under the WRONG design
        system id must be reported not-found (never returns the other system's
        bytes)."""
        from src.database.models.design_system import DesignSystemAsset
        from src.services.design_system_service import get_asset_base64, import_bundle

        ds = import_bundle(session, zip_bytes=make_bundle_zip(), user="u")
        logo = session.query(DesignSystemAsset).filter_by(
            design_system_id=ds.id, filename="logo.svg"
        ).one()

        with pytest.raises(ValueError):
            get_asset_base64(session, logo.id, design_system_id=ds.id + 1)

    def test_none_design_system_id_raises_not_found(self, session):
        """Fail-closed: a None scope resolves NO asset (the column is NOT NULL,
        so the IS NULL filter matches nothing)."""
        from src.database.models.design_system import DesignSystemAsset
        from src.services.design_system_service import get_asset_base64, import_bundle

        ds = import_bundle(session, zip_bytes=make_bundle_zip(), user="u")
        logo = session.query(DesignSystemAsset).filter_by(
            design_system_id=ds.id, filename="logo.svg"
        ).one()

        with pytest.raises(ValueError):
            get_asset_base64(session, logo.id, design_system_id=None)


class TestDefaultNamePrecedence:
    """Default name: override -> manifest name -> README H1 -> zip filename ->
    bundle root folder -> constant. All fixtures SYNTHETIC."""

    def _manifest_without_name(self):
        from tests.unit.conftest_design_system import default_manifest

        manifest = default_manifest()
        manifest.pop("name", None)
        return manifest

    def test_manifest_name_wins_over_readme_h1(self, session):
        from src.services.design_system_service import import_bundle

        ds = import_bundle(
            session,
            zip_bytes=make_bundle_zip(),  # manifest name + README H1 both present
            user="u",
            source_filename="acme-bundle.zip",
        )
        assert ds.name == "Acme Design System"  # manifest name

    def test_readme_h1_used_when_manifest_has_no_name(self, session):
        from tests.unit.conftest_design_system import SYNTHETIC_SKILL

        files = {
            "README.md": b"# Acme Brand Kit\n\nSynthetic readme.\n",
            "SKILL.md": SYNTHETIC_SKILL,
        }
        from src.services.design_system_service import import_bundle

        ds = import_bundle(
            session,
            zip_bytes=make_bundle_zip(manifest=self._manifest_without_name(), files=files),
            user="u",
            source_filename="whatever.zip",
        )
        assert ds.name == "Acme Brand Kit"

    def test_zip_filename_used_when_no_manifest_name_and_no_h1(self, session):
        files = {"README.md": b"No heading here, just prose.\n"}
        from src.services.design_system_service import import_bundle

        ds = import_bundle(
            session,
            zip_bytes=make_bundle_zip(manifest=self._manifest_without_name(), files=files),
            user="u",
            source_filename="acme-export-2026.zip",
        )
        assert ds.name == "acme-export-2026"

    def test_constant_fallback_when_nothing_available(self, session):
        from src.services.design_system_service import import_bundle

        ds = import_bundle(
            session,
            zip_bytes=make_bundle_zip(manifest=self._manifest_without_name(), files={}),
            user="u",
        )
        assert ds.name == "Imported Design System"

    def test_override_still_wins_over_everything(self, session):
        from src.services.design_system_service import import_bundle

        ds = import_bundle(
            session,
            zip_bytes=make_bundle_zip(),
            user="u",
            name_override="Explicit Name",
            source_filename="acme.zip",
        )
        assert ds.name == "Explicit Name"
