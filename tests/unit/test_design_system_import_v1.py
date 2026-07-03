"""Unit tests for the v1 Phase 1 "import foundation" additions.

Covers the three v1 Phase 1 deliverables layered on top of the Phase-3 importer:

1. The ONE canonical token parser: manifest grouping read from ``kind``
   (color/font/spacing/shadow), leading ``--`` / ``brand-`` stripped so manifest
   tokens dedup against the identical CSS ``:root`` vars, shadow tokens emitted.
   Regression target: the real manifest carries grouping in ``kind`` (not the
   ``group`` key the old code read), which mis-bucketed ~34 non-color tokens as
   colors, doubled 72 tokens to 144, and left spacing empty.
2. Source-file retention into ``design_system_file`` (README/SKILL/CSS/template
   HTML) with zip-slip path-safety, and NO double-store of asset/font bytes.
3. Font / brandFont mapping (family -> variants + token linkage).

All fixtures are SYNTHETIC (fake "Acme" brand, dummy hex, placeholder bytes) —
no real brand content, per the public-repo hygiene rule.
"""

import io
import json
import zipfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register models with Base.metadata
from src.core.database import Base
from tests.unit.conftest_design_system import (
    COLORS_AND_TYPE_CSS,
    REALISTIC_CSS,
    SVG_LOGO,
    SYNTHETIC_README,
    SYNTHETIC_SKILL,
    SYNTHETIC_TEMPLATE_HTML,
    default_manifest,
    make_bundle_zip,
    png_bytes,
    realistic_manifest,
)


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


def _import_realistic(session, **overrides):
    """Import a synthetic kind-based (real-shape) bundle end-to-end."""
    from src.services.design_system_service import import_bundle

    files = {
        "fonts/acme-sans-regular.woff2": b"font-a",
        "fonts/acme-sans-bold.woff2": b"font-b",
        "fonts/acme-mono.woff2": b"font-c",
        "assets/logo.svg": SVG_LOGO,
        "README.md": SYNTHETIC_README,
        "SKILL.md": SYNTHETIC_SKILL,
        "templates/corporate/index.html": SYNTHETIC_TEMPLATE_HTML,
    }
    zip_bytes = make_bundle_zip(
        manifest=realistic_manifest(), css=REALISTIC_CSS, files=files
    )
    return import_bundle(session, zip_bytes=zip_bytes, user="u", **overrides)


# ---------------------------------------------------------------------------
# Canonical token parser — pure function
# ---------------------------------------------------------------------------


class TestCanonicalizeTokenUnit:
    def test_kind_maps_to_group(self):
        from src.services.design_system_service import _canonicalize_token

        assert _canonicalize_token("--acme-navy", "#0B1F3A", "color") == ("core", "acme-navy")
        assert _canonicalize_token("--font-sans", "X, sans", "font") == ("type", "font-sans")
        assert _canonicalize_token("--fs-12", "12px", "spacing") == ("spacing", "fs-12")
        assert _canonicalize_token("--shadow-sm", "0 1px 2px", "shadow") == (
            "shadow",
            "shadow-sm",
        )

    def test_manifest_and_css_forms_canonicalize_equal(self):
        """--brand-core-primary (manifest) and the bare CSS var primary dedup."""
        from src.services.design_system_service import _canonicalize_token

        manifest_form = _canonicalize_token("--brand-core-primary", "#fff", "color")
        css_form = _canonicalize_token("primary", "#fff")
        assert manifest_form == css_form == ("core", "primary")

    def test_name_encoded_color_subgroup(self):
        from src.services.design_system_service import _canonicalize_token

        # A name-encoded subgroup wins for colors regardless of source.
        assert _canonicalize_token("--brand-accents-lava", "#EB4A34") == ("accents", "lava")

    def test_legacy_group_key_honored(self):
        from src.services.design_system_service import _canonicalize_token

        # Backward-compatible: an explicit recognized ``group`` is honored.
        assert _canonicalize_token("md", "16px", None, "spacing") == ("spacing", "md")

    def test_value_inference_for_bare_css_var(self):
        from src.services.design_system_service import _canonicalize_token

        assert _canonicalize_token("mystery", "#123456") == ("core", "mystery")
        assert _canonicalize_token("mystery", "1.5rem") == ("type", "mystery")

    def test_strip_token_ident(self):
        from src.services.design_system_service import _strip_token_ident

        assert _strip_token_ident("--font-sans") == "font-sans"
        assert _strip_token_ident("--brand-foo") == "foo"
        assert _strip_token_ident("plain") == "plain"


# ---------------------------------------------------------------------------
# Canonical token parser — end-to-end through import (the real bug)
# ---------------------------------------------------------------------------


class TestCanonicalTokenParserImport:
    def test_no_duplication_and_correct_group_counts(self, session):
        """72->144 regression: the 7 realistic tokens (defined in BOTH manifest and
        the identical CSS :root) dedup to exactly 7 rows in the right groups."""
        from src.database.models.design_system import DesignSystemToken

        ds = _import_realistic(session)
        tokens = session.query(DesignSystemToken).filter_by(design_system_id=ds.id).all()

        assert len(tokens) == 7  # NOT 14
        by_group = {}
        for t in tokens:
            by_group.setdefault(t.group, set()).add(t.name)
        assert by_group["core"] == {"acme-navy", "acme-ink-deep"}
        assert by_group["type"] == {"font-sans", "font-mono"}
        assert by_group["spacing"] == {"fs-12", "fs-16"}
        assert by_group["shadow"] == {"shadow-sm"}

    def test_no_fonts_bucketed_as_colors(self, session):
        """The 34-non-color regression: font tokens must NOT land in a color group."""
        from src.database.models.design_system import DesignSystemToken

        ds = _import_realistic(session)
        tokens = session.query(DesignSystemToken).filter_by(design_system_id=ds.id).all()

        color_names = {t.name for t in tokens if t.group in ("core", "accents", "ink", "tints")}
        assert "font-sans" not in color_names
        assert "font-mono" not in color_names
        # And they are present in the type group.
        type_names = {t.name for t in tokens if t.group == "type"}
        assert {"font-sans", "font-mono"} <= type_names

    def test_spacing_group_populated(self, session):
        """The 'spacing ends up empty' regression: spacing tokens are present."""
        from src.database.models.design_system import DesignSystemToken

        ds = _import_realistic(session)
        spacing = (
            session.query(DesignSystemToken)
            .filter_by(design_system_id=ds.id, group="spacing")
            .all()
        )
        assert {t.name for t in spacing} == {"fs-12", "fs-16"}

    def test_shadow_tokens_emitted(self, session):
        from src.database.models.design_system import DesignSystemToken

        ds = _import_realistic(session)
        shadow = (
            session.query(DesignSystemToken)
            .filter_by(design_system_id=ds.id, group="shadow")
            .all()
        )
        assert [(t.name, t.value) for t in shadow] == [("shadow-sm", "0 1px 2px rgba(0,0,0,0.1)")]

    def test_no_token_name_keeps_leading_dashes(self, session):
        """Names are canonicalized: no stored token keeps the raw ``--`` prefix."""
        from src.database.models.design_system import DesignSystemToken

        ds = _import_realistic(session)
        tokens = session.query(DesignSystemToken).filter_by(design_system_id=ds.id).all()
        assert all(not t.name.startswith("--") for t in tokens)

    def test_legacy_group_manifest_still_works(self, session):
        """The default (legacy ``group``-keyed) fixture still buckets correctly."""
        from src.database.models.design_system import DesignSystemToken
        from src.services.design_system_service import import_bundle

        ds = import_bundle(session, zip_bytes=make_bundle_zip(), user="u")
        by_key = {
            (t.group, t.name): t.value
            for t in session.query(DesignSystemToken).filter_by(design_system_id=ds.id)
        }
        assert by_key[("core", "primary")] == "#123456"
        assert by_key[("spacing", "md")] == "16px"
        assert by_key[("accents", "lava")] == "#EB4A34"


# ---------------------------------------------------------------------------
# Source-file retention
# ---------------------------------------------------------------------------


class TestSourceFileRetention:
    def test_source_files_retained_with_bytes(self, session):
        from src.database.models.design_system import DesignSystemFile
        from src.services.design_system_service import import_bundle

        ds = import_bundle(session, zip_bytes=make_bundle_zip(), user="u")
        by_path = {
            f.path: f
            for f in session.query(DesignSystemFile).filter_by(design_system_id=ds.id)
        }

        assert by_path["README.md"].kind == "readme"
        assert by_path["README.md"].data == SYNTHETIC_README
        assert by_path["SKILL.md"].kind == "skill"
        assert by_path["SKILL.md"].data == SYNTHETIC_SKILL
        # The CSS token source is retained as a source file.
        assert by_path["colors_and_type.css"].kind == "css"
        assert by_path["colors_and_type.css"].data is not None
        # Template LAYOUT html is retained; the sibling .js is NOT.
        assert by_path["templates/corporate/index.html"].kind == "template"
        assert by_path["templates/corporate/index.html"].data == SYNTHETIC_TEMPLATE_HTML
        assert "templates/corporate/ds-base.js" not in by_path

    def test_previews_and_screenshots_not_retained(self, session):
        from src.database.models.design_system import DesignSystemFile
        from src.services.design_system_service import import_bundle

        ds = import_bundle(session, zip_bytes=make_bundle_zip(), user="u")
        paths = {
            f.path for f in session.query(DesignSystemFile).filter_by(design_system_id=ds.id)
        }
        assert "assets/preview.png" not in paths
        assert "templates/title-shot.png" not in paths

    def test_manifest_not_retained_as_file(self, session):
        """The manifest lives (parsed) in manifest_json; it is not duplicated as a file."""
        from src.database.models.design_system import DesignSystemFile
        from src.services.design_system_service import import_bundle

        ds = import_bundle(session, zip_bytes=make_bundle_zip(), user="u")
        paths = {
            f.path for f in session.query(DesignSystemFile).filter_by(design_system_id=ds.id)
        }
        assert "_ds_manifest.json" not in paths


# ---------------------------------------------------------------------------
# Path safety (zip-slip)
# ---------------------------------------------------------------------------


class TestPathSafety:
    def test_parent_traversal_rejected(self, session):
        from src.services.design_system_service import (
            DesignSystemImportError,
            import_bundle,
        )

        zip_bytes = make_bundle_zip(files={"assets/../../evil.png": png_bytes(4, 4)})
        with pytest.raises(DesignSystemImportError) as exc:
            import_bundle(session, zip_bytes=zip_bytes, user="u")
        assert "unsafe path" in str(exc.value).lower()

    def test_absolute_path_rejected(self, session):
        from src.services.design_system_service import (
            DesignSystemImportError,
            import_bundle,
        )

        zip_bytes = make_bundle_zip(files={"/etc/evil.png": png_bytes(4, 4)})
        with pytest.raises(DesignSystemImportError):
            import_bundle(session, zip_bytes=zip_bytes, user="u")

    def test_safe_relpath_helper(self):
        from src.services.design_system_service import _safe_relpath

        assert _safe_relpath("assets/logo.svg") == "assets/logo.svg"
        assert _safe_relpath("a\\b\\c.png") == "a/b/c.png"  # backslashes normalized
        assert _safe_relpath("./assets/./logo.svg") == "assets/logo.svg"
        assert _safe_relpath("assets/../../evil") is None
        assert _safe_relpath("/etc/passwd") is None
        assert _safe_relpath("C:/Windows/x") is None


# ---------------------------------------------------------------------------
# No double-store: asset/font bytes are referenced, never duplicated
# ---------------------------------------------------------------------------


class TestNoDoubleStore:
    def test_asset_and_font_files_are_references(self, session):
        from src.database.models.design_system import DesignSystemFile
        from src.services.design_system_service import import_bundle

        ds = import_bundle(session, zip_bytes=make_bundle_zip(), user="u")
        by_path = {
            f.path: f
            for f in session.query(DesignSystemFile).filter_by(design_system_id=ds.id)
        }

        # Font file: a reference row (no bytes) linked to its asset row.
        font_ref = by_path["fonts/acme-sans.woff2"]
        assert font_ref.kind == "font"
        assert font_ref.data is None
        assert font_ref.asset_id is not None
        assert font_ref.asset is not None
        assert font_ref.asset.data == b"OTTO synthetic-font-bytes"

        # Brand asset: a reference row (no bytes) linked to its asset row.
        logo_ref = by_path["assets/logo.svg"]
        assert logo_ref.kind == "asset"
        assert logo_ref.data is None
        assert logo_ref.asset is not None
        assert logo_ref.asset.filename == "logo.svg"
        assert logo_ref.asset.data == SVG_LOGO

    def test_no_reference_row_stores_bytes(self, session):
        """The core no-double-store invariant: every asset/font file row has NULL
        bytes; the payload lives once, in design_system_asset."""
        from src.database.models.design_system import DesignSystemFile
        from src.services.design_system_service import import_bundle

        ds = import_bundle(session, zip_bytes=make_bundle_zip(), user="u")
        files = session.query(DesignSystemFile).filter_by(design_system_id=ds.id).all()

        for f in files:
            if f.kind in ("asset", "font"):
                assert f.data is None, f"reference row {f.path} must not store bytes"
            else:
                assert f.data is not None, f"source row {f.path} must store bytes"

        # There is exactly one asset-reference file per stored asset.
        ref_asset_ids = {f.asset_id for f in files if f.asset_id is not None}
        assert ref_asset_ids == {a.id for a in ds.assets}


# ---------------------------------------------------------------------------
# Font / brandFont mapping
# ---------------------------------------------------------------------------


class TestFontMapping:
    def test_build_font_mapping_joins_variants_and_tokens(self):
        from src.services.design_system_service import build_font_mapping

        fm = build_font_mapping(realistic_manifest())
        families = {f["family"]: f for f in fm["families"]}
        assert set(families) == {"Acme Sans", "Acme Mono"}

        # family -> weight/style variants, sorted, files joined from fonts[].
        assert families["Acme Sans"]["variants"] == [
            {"weight": "400", "style": "normal", "files": ["fonts/acme-sans-regular.woff2"]},
            {"weight": "700", "style": "normal", "files": ["fonts/acme-sans-bold.woff2"]},
        ]
        # token linkage from brandFonts[], canonicalized to match token names.
        assert families["Acme Sans"]["tokens"] == ["font-sans"]
        assert families["Acme Mono"]["tokens"] == ["font-mono"]

    def test_build_font_mapping_none_when_no_fonts(self):
        from src.services.design_system_service import build_font_mapping

        assert build_font_mapping({"name": "x"}) is None
        assert build_font_mapping({"fonts": [], "brandFonts": []}) is None

    def test_font_mapping_persisted_on_import(self, session):
        ds = _import_realistic(session)
        assert ds.font_mapping_json is not None
        families = {f["family"] for f in ds.font_mapping_json["families"]}
        assert families == {"Acme Sans", "Acme Mono"}

    def test_font_mapping_tokens_join_to_token_rows(self, session):
        """The linkage token names line up with design_system_token.name so a
        family can be joined to the token(s) that reference it."""
        from src.database.models.design_system import DesignSystemToken

        ds = _import_realistic(session)
        token_names = {
            t.name
            for t in session.query(DesignSystemToken).filter_by(
                design_system_id=ds.id, group="type"
            )
        }
        linked = {
            tok for fam in ds.font_mapping_json["families"] for tok in fam["tokens"]
        }
        assert linked <= token_names  # every linked token exists as a token row
        assert {"font-sans", "font-mono"} == linked


# ---------------------------------------------------------------------------
# Cross-vendor review fixes — BLOCKING 1-3: zip-slip + symlink hardening
# ---------------------------------------------------------------------------


def _raw_bundle_zip(entries: dict) -> bytes:
    """Build a zip verbatim from ``{arcname: bytes|str}`` (no prefixing).

    Lets a test place entries at EXACT paths — including outside a wrapper root or
    at unsafe paths — that ``make_bundle_zip``'s uniform prefixing cannot express.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, data in entries.items():
            zf.writestr(arcname, data)
    return buf.getvalue()


class TestZipSlipHardening:
    def test_manifest_at_parent_traversal_path_rejected(self, session):
        """BLOCKING 1: a manifest at ../_ds_manifest.json must not be adopted as root."""
        from src.services.design_system_service import (
            DesignSystemImportError,
            import_bundle,
        )

        zip_bytes = make_bundle_zip(root_prefix="../")
        with pytest.raises(DesignSystemImportError) as exc:
            import_bundle(session, zip_bytes=zip_bytes, user="u")
        assert "unsafe" in str(exc.value).lower()

    def test_manifest_at_absolute_path_rejected(self, session):
        """BLOCKING 1: an absolute-path manifest must be rejected."""
        from src.services.design_system_service import (
            DesignSystemImportError,
            import_bundle,
        )

        zip_bytes = make_bundle_zip(root_prefix="/abs/")
        with pytest.raises(DesignSystemImportError) as exc:
            import_bundle(session, zip_bytes=zip_bytes, user="u")
        assert "unsafe" in str(exc.value).lower()

    def test_unsafe_entry_outside_wrapper_root_rejected(self, session):
        """BLOCKING 2: a wrapper-rooted (safe/) bundle with a sibling ../evil.png
        entry OUTSIDE the root must be REJECTED, not silently skipped."""
        from src.services.design_system_service import (
            DesignSystemImportError,
            import_bundle,
        )

        zip_bytes = _raw_bundle_zip({
            "safe/_ds_manifest.json": json.dumps(default_manifest()),
            "safe/colors_and_type.css": COLORS_AND_TYPE_CSS,
            "safe/assets/logo.svg": SVG_LOGO,
            "../evil.png": b"pwned",  # OUTSIDE the safe/ root -> old code skipped it
        })
        with pytest.raises(DesignSystemImportError) as exc:
            import_bundle(session, zip_bytes=zip_bytes, user="u")
        assert "unsafe" in str(exc.value).lower()

    def test_absolute_entry_outside_wrapper_root_rejected(self, session):
        """BLOCKING 2: an absolute-path entry outside the wrapper root is rejected."""
        from src.services.design_system_service import (
            DesignSystemImportError,
            import_bundle,
        )

        zip_bytes = _raw_bundle_zip({
            "safe/_ds_manifest.json": json.dumps(default_manifest()),
            "safe/colors_and_type.css": COLORS_AND_TYPE_CSS,
            "/etc/abs.png": b"pwned",
        })
        with pytest.raises(DesignSystemImportError):
            import_bundle(session, zip_bytes=zip_bytes, user="u")

    def test_symlink_entry_rejected(self, session):
        """BLOCKING 3: a symlink entry (stores its link target as bytes) is rejected
        before any bytes are read."""
        from src.services.design_system_service import (
            DesignSystemImportError,
            import_bundle,
        )

        buf = io.BytesIO(make_bundle_zip())
        with zipfile.ZipFile(buf, "a", zipfile.ZIP_DEFLATED) as zf:
            zi = zipfile.ZipInfo("assets/evil-link.png")
            zi.external_attr = 0o120777 << 16  # S_IFLNK
            zf.writestr(zi, b"../../../etc/passwd")
        with pytest.raises(DesignSystemImportError) as exc:
            import_bundle(session, zip_bytes=buf.getvalue(), user="u")
        assert "symlink" in str(exc.value).lower()

    def test_symlink_detector_unit(self):
        from src.services.design_system_service import _is_symlink

        link = zipfile.ZipInfo("x")
        link.external_attr = 0o120777 << 16
        assert _is_symlink(link) is True
        regular = zipfile.ZipInfo("y")
        regular.external_attr = 0o100644 << 16
        assert _is_symlink(regular) is False
        assert _is_symlink(zipfile.ZipInfo("z")) is False  # default: not a symlink


# ---------------------------------------------------------------------------
# Cross-vendor review fix — BLOCKING 4: dedup keeps genuinely-distinct tokens
# ---------------------------------------------------------------------------


class TestTokenDedupKeepsDistinct:
    def test_distinct_tokens_sharing_name_both_kept(self, session):
        """A manifest token and a CSS var that canonicalize to the same NAME but
        differ in value are BOTH retained (name-only dedup used to drop one)."""
        from src.database.models.design_system import DesignSystemToken
        from src.services.design_system_service import import_bundle

        manifest = {
            "name": "Acme Distinct DS",
            "tokens": [{"name": "--brand-primary", "value": "#111111", "kind": "color"}],
            "globalCssPaths": ["colors_and_type.css"],
        }
        css = ":root { --primary: #222222; }"
        zip_bytes = make_bundle_zip(manifest=manifest, css=css, files={})
        ds = import_bundle(session, zip_bytes=zip_bytes, user="u")

        values = {
            t.value
            for t in session.query(DesignSystemToken).filter_by(
                design_system_id=ds.id, name="primary"
            )
        }
        assert values == {"#111111", "#222222"}  # BOTH kept, neither dropped

    def test_identical_manifest_and_css_token_still_dedups(self, session):
        """Preserve the correct dedup: the SAME name+value in manifest and CSS
        collapses to one row (manifest's authoritative group wins)."""
        from src.database.models.design_system import DesignSystemToken
        from src.services.design_system_service import import_bundle

        manifest = {
            "name": "Acme Dedup DS",
            "tokens": [{"name": "--fs-12", "value": "12px", "kind": "spacing"}],
            "globalCssPaths": ["colors_and_type.css"],
        }
        css = ":root { --fs-12: 12px; }"
        zip_bytes = make_bundle_zip(manifest=manifest, css=css, files={})
        ds = import_bundle(session, zip_bytes=zip_bytes, user="u")

        rows = (
            session.query(DesignSystemToken)
            .filter_by(design_system_id=ds.id, name="fs-12")
            .all()
        )
        assert len(rows) == 1
        assert rows[0].group == "spacing"  # manifest kind wins over CSS value-inference


# ---------------------------------------------------------------------------
# Cross-vendor review fix — NON-BLOCKING 6: only DECLARED CSS retained
# ---------------------------------------------------------------------------


class TestCssRetentionScope:
    def test_only_declared_css_retained(self, session):
        from src.database.models.design_system import DesignSystemFile
        from src.services.design_system_service import import_bundle

        files = {
            "assets/logo.svg": SVG_LOGO,
            "extra/notes.css": b":root { --nope: #000000; }",  # UNDECLARED extra .css
        }
        zip_bytes = make_bundle_zip(files=files)  # default manifest declares colors_and_type.css
        ds = import_bundle(session, zip_bytes=zip_bytes, user="u")

        css_paths = {
            f.path
            for f in session.query(DesignSystemFile).filter_by(
                design_system_id=ds.id, kind="css"
            )
        }
        assert css_paths == {"colors_and_type.css"}  # only the declared source
        all_paths = {
            f.path
            for f in session.query(DesignSystemFile).filter_by(design_system_id=ds.id)
        }
        assert "extra/notes.css" not in all_paths  # undeclared .css not retained


# ---------------------------------------------------------------------------
# Cross-vendor review fix — NON-BLOCKING 5: font path normalization
# ---------------------------------------------------------------------------


class TestFontPathSafety:
    def test_unsafe_font_paths_dropped_and_normalized(self):
        from src.services.design_system_service import build_font_mapping

        manifest = {
            "fonts": [
                {
                    "family": "Acme Sans",
                    "weight": "400",
                    "style": "normal",
                    "files": ["../evil.woff2", "fonts\\acme-sans.woff2", "/abs/x.woff2"],
                }
            ],
        }
        fm = build_font_mapping(manifest)
        files = [f for fam in fm["families"] for v in fam["variants"] for f in v["files"]]
        assert "../evil.woff2" not in files  # traversal dropped
        assert "/abs/x.woff2" not in files  # absolute dropped
        assert "fonts/acme-sans.woff2" in files  # backslashes normalized, kept


# ---------------------------------------------------------------------------
# Cross-vendor review fix — NON-BLOCKING 7: CSS not double-counted in budget
# ---------------------------------------------------------------------------


class TestCssSizeBudget:
    def test_css_not_double_counted_against_bundle_cap(self, session, monkeypatch):
        """A bundle that fits when its CSS is charged ONCE must import — even under
        a cap it would exceed if the CSS were counted twice (parse + retention)."""
        from src.database.models.design_system import DesignSystemFile
        from src.services import design_system_service as svc
        from src.services.design_system_service import import_bundle

        big_css = ":root { --acme-navy: #0B1F3A; }\n/* pad " + ("a" * 6000) + " */"
        css_len = len(big_css.encode("utf-8"))
        cap = css_len + 2000  # above (manifest + css-once), below (css-twice)
        assert 2 * css_len > cap  # test is only meaningful if double-count would fail
        monkeypatch.setattr(svc, "MAX_BUNDLE_SIZE_BYTES", cap)

        manifest = {"name": "Acme Budget DS", "globalCssPaths": ["colors_and_type.css"]}
        zip_bytes = make_bundle_zip(manifest=manifest, css=big_css, files={})
        ds = import_bundle(session, zip_bytes=zip_bytes, user="u")  # succeeds: CSS charged once

        assert ds.id is not None
        css_files = (
            session.query(DesignSystemFile)
            .filter_by(design_system_id=ds.id, kind="css")
            .all()
        )
        assert len(css_files) == 1  # still retained
