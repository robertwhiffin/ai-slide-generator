"""Design-system template entities (Phase 4): model, migration, asset-ref
rewriting, materialization (import-time + lazy), and the SELECTED-TEMPLATE
prompt block.

All fixtures are SYNTHETIC — fake "Acme" brand, #123456-style hex, generated
PNG bytes — per the public-repo hygiene rule (no real brand content ever).
"""
import logging

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register models with Base.metadata
from src.core.database import Base
from tests.unit.conftest_design_system import (
    COLORS_AND_TYPE_CSS,
    DOT_THUMBNAIL_SLUGS,
    SVG_LOGO,
    TEMPLATED_TEMPLATE_HTML,
    dot_thumbnail_bundle_files,
    dot_thumbnail_manifest,
    gif_bytes,
    jpeg_bytes,
    make_bundle_zip,
    png_bytes,
    template_preview_png,
    templated_bundle_files,
    templated_manifest,
    webp_bytes,
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


def _import_templated_ds(session, *, files=None, manifest=None):
    """Import the synthetic template-bearing bundle and return the DesignSystem."""
    from src.services.design_system_service import import_bundle

    zip_bytes = make_bundle_zip(
        manifest=manifest if manifest is not None else templated_manifest(),
        files=files if files is not None else templated_bundle_files(),
    )
    return import_bundle(session, zip_bytes=zip_bytes, user="tester")


def _asset_id_by_filename(ds, filename):
    return next(a.id for a in ds.assets if a.filename == filename)


# ---------------------------------------------------------------------------
# Model + migration
# ---------------------------------------------------------------------------


class TestModelAndMigration:
    def test_model_registered_with_expected_columns(self):
        from src.database.models import DesignSystemTemplate

        assert DesignSystemTemplate.__tablename__ == "design_system_template"
        columns = {c.name for c in DesignSystemTemplate.__table__.columns}
        assert {
            "id",
            "design_system_id",
            "name",
            "description",
            "entry_path",
            "layout_html",
            "token_css",
            "thumbnail_asset_id",
        } <= columns

    def test_hand_rolled_migration_creates_table(self):
        from src.core.database import _migrate_design_system_tables

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        with engine.begin() as conn:
            _migrate_design_system_tables(conn)
        assert inspect(engine).has_table("design_system_template")
        engine.dispose()

    def test_foreign_keys_cascade_and_set_null(self):
        """Parent FK cascades with the design system; the thumbnail FK is SET
        NULL so replacing/deleting a screenshot never deletes the template.
        Asserted on the FK metadata (the repo's SQLite tests do not enforce
        FK pragmas; Lakebase/Postgres enforces the real ON DELETE)."""
        from src.database.models import DesignSystemTemplate

        by_column = {
            next(iter(fk.constraint.columns)).name: fk
            for fk in DesignSystemTemplate.__table__.foreign_keys
        }
        assert by_column["design_system_id"].ondelete == "CASCADE"
        assert by_column["thumbnail_asset_id"].ondelete == "SET NULL"


# ---------------------------------------------------------------------------
# Asset-ref rewriting
# ---------------------------------------------------------------------------


class TestRewriteTemplateAssetRefs:
    def _rewrite(self, text, *, base_dir="templates/corporate", ids=None):
        from src.services.design_system_templates import rewrite_template_asset_refs

        return rewrite_template_asset_refs(
            text,
            base_dir=base_dir,
            asset_ids_by_path=ids
            if ids is not None
            else {"assets/logo.svg": 7, "assets/backgrounds/hero-bg.png": 9},
        )

    def test_parent_relative_img_src_rewritten(self):
        out = self._rewrite('<img src="../assets/logo.svg" alt="Acme logo" />')
        assert '<img src="{{ds-asset:7}}" alt="Acme logo" />' == out

    def test_bundle_root_relative_src_falls_back_to_root(self):
        out = self._rewrite('<img src="assets/logo.svg" />')
        assert "{{ds-asset:7}}" in out

    def test_css_url_refs_rewritten_quoted_and_bare(self):
        css = (
            '.hero { background-image: url("../assets/backgrounds/hero-bg.png"); }\n'
            ".alt { background: url(../assets/logo.svg) no-repeat; }"
        )
        out = self._rewrite(css)
        assert 'url("{{ds-asset:9}}")' in out
        assert "url({{ds-asset:7}})" in out

    def test_query_and_fragment_stripped_for_lookup(self):
        out = self._rewrite('<img src="../assets/logo.svg?v=2#frag" />')
        assert "{{ds-asset:7}}" in out

    def test_unresolvable_refs_become_harmless_placeholder_and_log(self, caplog):
        with caplog.at_level(logging.WARNING, logger="src.services.design_system_templates"):
            out = self._rewrite(
                '<img src="../assets/missing-art.png" />'
                "<div style=\"background: url('../assets/also-missing.png')\"></div>"
            )
        assert "missing-art.png" not in out
        assert "also-missing.png" not in out
        assert out.count("data:,") == 2
        assert "missing-art.png" in caplog.text

    def test_external_data_anchor_and_placeholder_refs_left_alone(self):
        html = (
            '<img src="https://example.invalid/x.png" />'
            '<img src="data:image/png;base64,AAAA" />'
            '<a href="#section">jump</a>'
            '<img src="{{ds-asset:3}}" />'
        )
        assert self._rewrite(html) == html

    def test_script_tags_stripped(self):
        html = (
            '<script src="./ds-base.js"></script>'
            "<section>keep me</section>"
            "<script>window.__chrome = 1;</script>"
        )
        out = self._rewrite(html)
        assert "<script" not in out
        assert "ds-base.js" not in out
        assert "<section>keep me</section>" in out

    def test_href_resolving_to_asset_rewritten(self):
        out = self._rewrite('<link rel="icon" href="../assets/logo.svg" />')
        assert '<link rel="icon" href="{{ds-asset:7}}" />' in out

    def test_unresolvable_relative_href_neutralized_like_src(self, caplog):
        """Cross-review Blocking 2: an unresolvable RELATIVE href is an asset
        ref we claimed to cover — it must become the inert placeholder with a
        warning, exactly like src/poster (not silently left dangling)."""
        with caplog.at_level(logging.WARNING, logger="src.services.design_system_templates"):
            out = self._rewrite('<link rel="stylesheet" href="./deck.css" />')
        assert 'href="data:,"' in out
        assert "deck.css" not in out
        assert "deck.css" in caplog.text

    def test_absolute_href_anchors_left_untouched(self):
        html = (
            '<a href="https://example.invalid/docs">docs</a>'
            '<a href="mailto:brand@example.invalid">mail</a>'
            '<a href="#section">jump</a>'
        )
        assert self._rewrite(html) == html

    # --- hardening: org-trusted surface, belt-and-braces (no full sanitizer) ---

    def test_inline_event_handler_attributes_stripped(self):
        out = self._rewrite(
            '<img src="../assets/logo.svg" onerror="alert(1)" alt="Acme" />'
            "<section onclick='doThing()' class=\"slide\">keep</section>"
        )
        assert "onerror" not in out
        assert "onclick" not in out
        assert "alert(1)" not in out
        assert '<img src="{{ds-asset:7}}"' in out
        assert 'class="slide">keep</section>' in out

    def test_javascript_urls_neutralized(self, caplog):
        with caplog.at_level(logging.WARNING, logger="src.services.design_system_templates"):
            out = self._rewrite(
                '<a href="javascript:alert(1)">x</a>'
                '<img src="JaVaScRiPt:alert(2)" />'
                '<a href="java\nscript:alert(3)">y</a>'
            )
        assert "alert(1)" not in out
        assert "alert(2)" not in out
        assert "alert(3)" not in out
        assert out.count("data:,") == 3
        assert "javascript" in caplog.text.lower()

    def test_unquoted_script_scheme_attrs_neutralized(self, caplog):
        """Unquoted attribute values bypass the quoted-attr pattern — a bare
        ``href=javascript:...`` must be neutralized just like the quoted form
        (benign unquoted refs are out of scope; only script schemes)."""
        with caplog.at_level(logging.WARNING, logger="src.services.design_system_templates"):
            out = self._rewrite(
                "<a href=javascript:alert(1)>x</a>"
                "<img src=VbScRiPt:msgbox(2) />"
                '<a href=unquoted-plain.css rel="x">keep-ref</a>'
            )
        assert "alert(1)" not in out
        assert "msgbox(2)" not in out
        assert out.count("data:,") == 2
        # Non-script unquoted refs are left alone (this pass only defangs).
        assert "unquoted-plain.css" in out
        assert "script-scheme" in caplog.text.lower()

    def test_css_url_script_scheme_neutralized(self, caplog):
        """CSS ``url(javascript:...)`` is not an asset ref (absolute URI), so
        the rewrite used to leave it untouched — it must become the inert
        placeholder, in both <style> blocks and inline style attributes."""
        with caplog.at_level(logging.WARNING, logger="src.services.design_system_templates"):
            out = self._rewrite(
                "<style>.a { background: url(javascript:alert(1)); }\n"
                '.b { background-image: url("vbscript:Evil"); }</style>'
                '<div style="background: url(JAVASCRIPT:alert(2))"></div>'
            )
        assert "alert(1" not in out
        assert "alert(2" not in out
        assert "Evil" not in out
        assert out.count("data:,") == 3
        assert "script-scheme" in caplog.text.lower()

    def test_css_url_data_uri_left_untouched(self):
        """data: URIs in CSS url() are absolute non-script refs — unchanged."""
        css = ".a { background: url(data:image/png;base64,AAAA); }"
        assert self._rewrite(css) == css

    def test_css_url_quoted_script_scheme_with_parens_neutralized(self, caplog):
        """QUOTED script-scheme url() refs containing parentheses never match
        _CSS_URL_RE (its ref class excludes ``)``), so ``url("javascript:
        alert(1)")`` bypassed the neutralization branch entirely. Both quote
        forms must be defanged like the bare form."""
        with caplog.at_level(logging.WARNING, logger="src.services.design_system_templates"):
            out = self._rewrite(
                '<style>.a { background: url("javascript:alert(1)"); }\n'
                ".b { background-image: url('JaVaScRiPt:alert(2)'); }</style>"
                "<div style=\"background: url('vbscript:MsgBox(3)')\"></div>"
            )
        assert "alert(1" not in out
        assert "alert(2" not in out
        assert "MsgBox(3" not in out
        assert out.count("data:,") == 3
        assert "script-scheme" in caplog.text.lower()

    def test_css_url_quoted_benign_refs_keep_existing_treatment(self):
        """Defang-only scope control: a quoted benign ref still rewrites to its
        asset handle, and a quoted benign ref WITH parentheses (which the main
        pattern cannot represent) passes through untouched exactly as before."""
        out = self._rewrite('.hero { background: url("../assets/backgrounds/hero-bg.png"); }')
        assert 'url("{{ds-asset:9}}")' in out
        parens_css = '.odd { background: url("../assets/lo(go).png"); }'
        assert self._rewrite(parens_css) == parens_css

    def test_object_embed_iframe_stripped_like_script(self):
        out = self._rewrite(
            '<object data="../assets/logo.svg"><param name="x" /></object>'
            '<embed src="movie.swf">'
            '<iframe src="https://example.invalid/frame"></iframe>'
            "<section>keep me</section>"
        )
        assert "<object" not in out
        assert "<embed" not in out
        assert "<iframe" not in out
        assert "<section>keep me</section>" in out

    def test_srcset_resolvable_entries_rewritten(self):
        out = self._rewrite(
            '<img src="../assets/logo.svg" '
            'srcset="../assets/logo.svg 1x, assets/backgrounds/hero-bg.png 2x" />'
        )
        assert 'srcset="{{ds-asset:7}} 1x, {{ds-asset:9}} 2x"' in out

    def test_srcset_with_unresolvable_relative_entry_dropped(self, caplog):
        with caplog.at_level(logging.WARNING, logger="src.services.design_system_templates"):
            out = self._rewrite(
                '<img src="../assets/logo.svg" '
                'srcset="../assets/logo.svg 1x, ../assets/missing-art.png 2x" />'
            )
        assert "srcset" not in out
        assert "missing-art.png" not in out
        assert '<img src="{{ds-asset:7}}"' in out  # the src itself still rewrites
        assert "srcset" in caplog.text.lower()

    def test_srcset_with_only_absolute_entries_kept(self):
        html = '<img src="../assets/logo.svg" srcset="https://example.invalid/a.png 1x" />'
        out = self._rewrite(html)
        assert 'srcset="https://example.invalid/a.png 1x"' in out


# ---------------------------------------------------------------------------
# Materialization (derivation from manifest_json + design_system_file rows)
# ---------------------------------------------------------------------------


def _file_backed_ds(
    session,
    *,
    manifest,
    template_html=TEMPLATED_TEMPLATE_HTML,
    template_path="templates/corporate/index.html",
    with_preview=True,
    with_css=True,
):
    """Build a DesignSystem with retained file rows directly (no importer), the
    shape a system imported between Phase 1 and Phase 4 has persisted."""
    from src.database.models import DesignSystem, DesignSystemAsset, DesignSystemFile

    ds = DesignSystem(name=f"Acme Derived DS {id(manifest)}", manifest_json=manifest)
    logo = DesignSystemAsset(
        kind="logo", filename="logo.svg", mime="image/svg+xml",
        data=SVG_LOGO, size_bytes=len(SVG_LOGO),
    )
    ds.assets.append(logo)
    ds.files.append(DesignSystemFile(
        path="assets/logo.svg", kind="asset", mime="image/svg+xml",
        data=None, size_bytes=len(SVG_LOGO), asset=logo,
    ))
    font_bytes = b"OTTO synthetic-font-bytes"
    font = DesignSystemAsset(
        kind="font", filename="acme-sans.woff2", mime="font/woff2",
        data=font_bytes, size_bytes=len(font_bytes),
    )
    ds.assets.append(font)
    ds.files.append(DesignSystemFile(
        path="fonts/acme-sans.woff2", kind="font", mime="font/woff2",
        data=None, size_bytes=len(font_bytes), asset=font,
    ))
    if with_css:
        css = (
            COLORS_AND_TYPE_CSS
            + "\n@font-face { font-family: 'Acme Sans'; src: url('fonts/acme-sans.woff2'); }\n"
        ).encode("utf-8")
        ds.files.append(DesignSystemFile(
            path="colors_and_type.css", kind="css", mime="text/css",
            data=css, size_bytes=len(css),
        ))
    if template_html is not None:
        ds.files.append(DesignSystemFile(
            path=template_path, kind="template", mime="text/html",
            data=template_html, size_bytes=len(template_html),
        ))
    if with_preview:
        preview_bytes = template_preview_png()
        preview = DesignSystemAsset(
            kind="template_shot", filename="preview.png", mime="image/png",
            data=preview_bytes, width=6, height=4, size_bytes=len(preview_bytes),
        )
        ds.assets.append(preview)
        ds.files.append(DesignSystemFile(
            path="templates/corporate/preview.png", kind="asset", mime="image/png",
            data=None, size_bytes=len(preview_bytes), asset=preview,
        ))
    session.add(ds)
    session.flush()
    return ds


class TestMaterializeTemplates:
    def test_materializes_from_entry_path_with_rewritten_layout(self, session):
        from src.services.design_system_templates import materialize_templates

        ds = _file_backed_ds(session, manifest=templated_manifest())
        templates = materialize_templates(ds)

        assert len(templates) == 1
        template = templates[0]
        assert template.name == "Acme Corporate"
        assert template.description == "Cover + agenda, content, closing."
        assert template.entry_path == "templates/corporate/index.html"
        logo_id = _asset_id_by_filename(ds, "logo.svg")
        assert f"{{{{ds-asset:{logo_id}}}}}" in template.layout_html
        assert "../assets/logo.svg" not in template.layout_html
        assert "<script" not in template.layout_html
        assert "var(--acme-navy)" in template.layout_html  # template CSS kept intact

    def test_token_css_carried_and_rewritten(self, session):
        """The ORIGINAL retained stylesheets ride along verbatim (the template's
        var(--…) refs depend on their original names, which the compiled
        artifact renames to --brand-*), with their url() refs rewritten."""
        from src.services.design_system_templates import materialize_templates

        ds = _file_backed_ds(session, manifest=templated_manifest())
        template = materialize_templates(ds)[0]

        assert template.token_css is not None
        assert "--brand-core-primary: #123456" in template.token_css  # original text
        assert "--heading-font: 'Inter', sans-serif;" in template.token_css
        font_id = _asset_id_by_filename(ds, "acme-sans.woff2")
        assert f"{{{{ds-asset:{font_id}}}}}" in template.token_css
        assert "url('fonts/acme-sans.woff2')" not in template.token_css

    def test_thumbnail_linked_from_template_folder_preview(self, session):
        from src.services.design_system_templates import materialize_templates

        ds = _file_backed_ds(session, manifest=templated_manifest())
        template = materialize_templates(ds)[0]
        preview_id = _asset_id_by_filename(ds, "preview.png")
        assert template.thumbnail_asset_id == preview_id

    def test_no_preview_means_no_thumbnail(self, session):
        from src.services.design_system_templates import materialize_templates

        ds = _file_backed_ds(session, manifest=templated_manifest(), with_preview=False)
        template = materialize_templates(ds)[0]
        assert template.thumbnail_asset_id is None

    def test_idempotent_on_second_call(self, session):
        from src.services.design_system_templates import materialize_templates

        ds = _file_backed_ds(session, manifest=templated_manifest())
        first = materialize_templates(ds)
        second = materialize_templates(ds)
        assert len(first) == 1
        assert len(second) == 1
        assert second[0] is first[0]

    def test_folder_only_entry_resolves_index_html(self, session):
        from src.services.design_system_templates import materialize_templates

        manifest = templated_manifest()
        manifest["templates"] = [{"name": "Acme Corporate", "folder": "templates/corporate"}]
        ds = _file_backed_ds(session, manifest=manifest)
        templates = materialize_templates(ds)
        assert [t.entry_path for t in templates] == ["templates/corporate/index.html"]

    def test_bare_folder_name_resolves_under_templates_dir(self, session):
        from src.services.design_system_templates import materialize_templates

        manifest = templated_manifest()
        manifest["templates"] = [{"name": "Acme Corporate", "folder": "corporate"}]
        ds = _file_backed_ds(session, manifest=manifest)
        templates = materialize_templates(ds)
        assert [t.entry_path for t in templates] == ["templates/corporate/index.html"]

    def test_name_slug_fallback_matches_template_dir(self, session):
        from src.services.design_system_templates import materialize_templates

        manifest = templated_manifest()
        manifest["templates"] = [{"name": "Corporate", "description": "Slug-matched."}]
        ds = _file_backed_ds(session, manifest=manifest)
        templates = materialize_templates(ds)
        assert [t.entry_path for t in templates] == ["templates/corporate/index.html"]

    def test_entry_without_matching_file_is_skipped(self, session):
        from src.services.design_system_templates import materialize_templates

        manifest = templated_manifest()
        manifest["templates"].append(
            {"name": "Acme Ghost", "entryPath": "templates/ghost/index.html"}
        )
        ds = _file_backed_ds(session, manifest=manifest)
        templates = materialize_templates(ds)
        assert [t.name for t in templates] == ["Acme Corporate"]

    def test_duplicate_entries_collapse_to_one(self, session):
        from src.services.design_system_templates import materialize_templates

        manifest = templated_manifest()
        manifest["templates"].append(dict(manifest["templates"][0], name="Acme Duplicate"))
        ds = _file_backed_ds(session, manifest=manifest)
        assert len(materialize_templates(ds)) == 1

    def test_pre_phase1_system_without_files_has_no_templates(self, session):
        from src.database.models import DesignSystem
        from src.services.design_system_templates import materialize_templates

        ds = DesignSystem(name="Acme Legacy DS", manifest_json=templated_manifest())
        session.add(ds)
        session.flush()
        assert materialize_templates(ds) == []

    def test_none_manifest_and_missing_templates_key_are_safe(self, session):
        from src.database.models import DesignSystem
        from src.services.design_system_templates import materialize_templates

        for manifest in (None, {}, {"templates": None}, {"templates": "bogus"}):
            ds = DesignSystem(name=f"Acme NoTemplates {manifest!r}", manifest_json=manifest)
            session.add(ds)
            session.flush()
            assert materialize_templates(ds) == []


# ---------------------------------------------------------------------------
# Import-time population
# ---------------------------------------------------------------------------


SECTION_KEYED_TEMPLATE_HTML = b"""<!doctype html>
<html><head>
<style>
section { font-family: var(--heading-font); }
section .title { font-size: 42px; }
section.dark { background: #123456; }
.section-title { letter-spacing: 0.1em; }
body { margin: 0; }
@font-face { font-family: 'Acme Sans'; src: url('../fonts/acme-sans.woff2'); }
@media (min-width: 100px) {
  section .kicker { font-size: 14px; }
}
</style>
</head><body>
<section class="slide cover"><h1 class="title">Sample cover title</h1></section>
<section class="slide dark"><p class="kicker">Sample kicker</p></section>
</body></html>
"""


class TestRootTagSelectorNormalization:
    """dsv2 battery F7: templates key typography on their root TAG
    (``section { font-family: var(--font-sans) }``) but generated decks emit
    ``<div class="slide">`` roots — the selector never matches and every
    pinned deck fell back to UA serif. At materialization the template CSS
    gains ``.slide``-keyed parallel selectors for every tag the template
    itself uses as a slide root; already-imported rows self-heal lazily."""

    def _materialized_layout(self, session, template_html=SECTION_KEYED_TEMPLATE_HTML):
        from src.services.design_system_templates import materialize_templates

        ds = _file_backed_ds(
            session, manifest=templated_manifest(), template_html=template_html
        )
        return materialize_templates(ds)[0].layout_html

    def test_root_tag_selectors_gain_slide_class_parallels(self, session):
        import re

        layout = self._materialized_layout(session)
        assert re.search(r"section\s*,\s*\.slide\s*\{", layout)
        assert "section .title, .slide .title" in layout
        assert "section.dark, .slide.dark" in layout
        # rules inside @media blocks are normalized too
        assert "section .kicker, .slide .kicker" in layout

    def test_unrelated_selectors_and_at_rules_untouched(self, session):
        layout = self._materialized_layout(session)
        # class names CONTAINING the tag name are not selector keys
        assert ".section-title { letter-spacing: 0.1em; }" in layout
        assert ".slide-title" not in layout
        # non-root tags and at-rule preludes stay as authored
        assert "body { margin: 0; }" in layout
        assert "@font-face { font-family: 'Acme Sans';" in layout

    def test_tags_that_are_not_slide_roots_stay_untouched(self, session):
        html = (
            b"<!doctype html><html><head><style>\n"
            b"section { font-size: 18px; }\n"
            b"</style></head><body>\n"
            b'<div class="slide"><section><h1>Nested non-root section</h1></section></div>\n'
            b"</body></html>\n"
        )
        layout = self._materialized_layout(session, template_html=html)
        assert "section { font-size: 18px; }" in layout
        assert ".slide {" not in layout.replace("section, .slide {", "")

    def test_existing_rows_self_heal_on_read(self, session):
        """Rows materialized before this normalization existed carry tag-keyed
        CSS; reading them through materialize_templates rewrites them in
        place (persistence is the calling session's business, matching the
        compiler's lazy recompute discipline)."""
        from src.services.design_system_templates import materialize_templates

        ds = _file_backed_ds(
            session,
            manifest=templated_manifest(),
            template_html=SECTION_KEYED_TEMPLATE_HTML,
        )
        template = materialize_templates(ds)[0]
        # Regress the stored row to the pre-normalization shape.
        template.layout_html = template.layout_html.replace(
            "section, .slide {", "section {"
        ).replace(
            "section .title, .slide .title", "section .title"
        ).replace(
            "section.dark, .slide.dark", "section.dark"
        ).replace(
            "section .kicker, .slide .kicker", "section .kicker"
        )
        session.flush()

        healed = materialize_templates(ds)[0]
        assert "section .title, .slide .title" in healed.layout_html

    def test_normalization_is_idempotent_across_reads(self, session):
        from src.services.design_system_templates import materialize_templates

        ds = _file_backed_ds(
            session,
            manifest=templated_manifest(),
            template_html=SECTION_KEYED_TEMPLATE_HTML,
        )
        first = materialize_templates(ds)[0].layout_html
        second = materialize_templates(ds)[0].layout_html
        assert second == first
        assert "section, .slide, .slide" not in second


class TestAttributeSelectorValueSafety:
    """dsv2 cross-review F1: the root-tag rewrite matched the tag token inside
    quoted attribute-selector values (``section[data-kind="section"]`` gained
    the parallel ``.slide[data-kind=".slide"]``), so templates keyed on
    attribute selectors STILL never matched generated ``div.slide`` roots —
    the exact failure the rewrite exists to fix. The tag token is an element
    key only OUTSIDE quoted strings and ``[…]`` attribute blocks."""

    def _normalize(self, css):
        from src.services.design_system_templates import normalize_root_tag_selectors

        return normalize_root_tag_selectors(
            "<!doctype html><html><head><style>\n"
            f"{css}\n"
            "</style></head><body>\n"
            '<section class="slide"><h1>Root</h1></section>\n'
            "</body></html>\n"
        )

    def test_double_quoted_attribute_values_survive_the_rewrite(self):
        out = self._normalize('section[data-kind="section"] .title { color: #111; }')
        assert '.slide[data-kind="section"] .title' in out
        assert '".slide"' not in out

    def test_single_quoted_attribute_values_survive_the_rewrite(self):
        out = self._normalize("section[data-kind='section'] .title { color: #111; }")
        assert ".slide[data-kind='section'] .title" in out
        assert "'.slide'" not in out

    def test_bare_attribute_names_survive_the_rewrite(self):
        out = self._normalize("section[section] { color: #111; }")
        assert ".slide[section]" in out
        assert "[.slide]" not in out

    def test_every_element_position_is_rewritten_in_one_parallel(self):
        out = self._normalize("section [data-x] section.hero { color: #111; }")
        assert "section [data-x] section.hero, .slide [data-x] .slide.hero" in out

    def test_attribute_only_occurrences_gain_no_parallel(self):
        out = self._normalize('.card[data-kind="section"] { color: #111; }')
        assert '.card[data-kind="section"] { color: #111; }' in out
        assert out.count("data-kind") == 1

    def test_attribute_selector_normalization_is_idempotent(self):
        from src.services.design_system_templates import normalize_root_tag_selectors

        once = self._normalize('section[data-kind="section"] .title { color: #111; }')
        assert normalize_root_tag_selectors(once) == once


class TestEnsureDeckTokenCss:
    """dsv2 battery WB-1: a pinned generation referenced 57 var(--…) tokens
    while defining none — the model dropped the TOKEN STYLESHEET despite the
    prompt's carry instruction, washing out preview and both PPTX paths.
    ``ensure_deck_token_css`` is the deterministic backstop: if the deck CSS
    does not define what the template's token stylesheet defines, the token
    stylesheet is re-emitted (prepended, so deck CSS still wins the cascade).
    """

    TOKEN_CSS = (
        ":root { --acme-navy: #123456; --acme-lava: #654321; }\n"
        "@font-face { font-family: 'Acme Sans'; src: url('{{ds-asset:9}}'); }"
    )

    def _ensure(self, deck_css, token_css=TOKEN_CSS):
        from src.services.design_system_templates import ensure_deck_token_css

        return ensure_deck_token_css(deck_css, token_css)

    def test_missing_definitions_are_prepended(self):
        deck_css = ".dark { background: var(--acme-navy); }"
        out = self._ensure(deck_css)
        assert "--acme-navy: #123456" in out
        assert "@font-face" in out
        # Prepended: deck CSS keeps the last word in the cascade.
        assert out.index("--acme-navy: #123456") < out.index(".dark {")

    def test_compliant_deck_css_is_untouched(self):
        deck_css = self.TOKEN_CSS + "\n.dark { background: var(--acme-navy); }"
        assert self._ensure(deck_css) == deck_css

    def test_partially_dropped_tokens_still_re_emitted(self):
        deck_css = (
            ":root { --acme-navy: #123456; }\n"
            "@font-face { font-family: 'Acme Sans'; src: url('x'); }"
        )  # --acme-lava definition lost
        out = self._ensure(deck_css)
        assert "--acme-lava: #654321" in out

    def test_missing_font_faces_alone_trigger_re_emit(self):
        deck_css = ":root { --acme-navy: #123456; --acme-lava: #654321; }"
        out = self._ensure(deck_css)
        assert "@font-face" in out

    def test_foreign_font_face_does_not_mask_missing_brand_families(self):
        # dsv2 cross-review F3: the survival check was "ANY @font-face in the
        # deck" — a deck that kept only a foreign 'Other' face while dropping
        # the brand families slipped through, and the export lost brand type.
        deck_css = (
            ":root { --acme-navy: #123456; --acme-lava: #654321; }\n"
            "@font-face { font-family: 'Other'; src: url('other.woff2'); }"
        )
        out = self._ensure(deck_css)
        assert "font-family: 'Acme Sans'" in out

    def test_any_single_dropped_family_triggers_re_emit(self):
        token_css = (
            "@font-face { font-family: 'Acme Sans'; src: url('a'); }\n"
            "@font-face { font-family: 'Acme Mono'; src: url('b'); }"
        )
        deck_css = "@font-face { font-family: 'Acme Sans'; src: url('a'); }"
        out = self._ensure(deck_css, token_css=token_css)
        assert "'Acme Mono'" in out

    def test_family_survival_is_quote_and_case_insensitive(self):
        # CSS font-family matching is case-insensitive and quoting-agnostic;
        # a deck that re-declares the face as "ACME SANS" complied and must
        # not be re-emitted over.
        deck_css = (
            ":root { --acme-navy: #123456; --acme-lava: #654321; }\n"
            '@font-face { font-family: "ACME SANS"; src: url(\'x\'); }'
        )
        assert self._ensure(deck_css) == deck_css

    def test_font_face_re_emit_is_idempotent(self):
        deck_css = (
            ":root { --acme-navy: #123456; --acme-lava: #654321; }\n"
            "@font-face { font-family: 'Other'; src: url('other.woff2'); }"
        )
        once = self._ensure(deck_css)
        assert self._ensure(once) == once

    def test_no_token_css_is_identity(self):
        assert self._ensure(".x { color: red; }", token_css=None) == ".x { color: red; }"
        assert self._ensure(".x { color: red; }", token_css="   ") == ".x { color: red; }"

    def test_empty_deck_css_becomes_the_token_stylesheet(self):
        out = self._ensure("")
        assert "--acme-navy: #123456" in out

    def test_idempotent(self):
        deck_css = ".dark { color: var(--acme-lava); }"
        once = self._ensure(deck_css)
        assert self._ensure(once) == once


class TestImportPopulatesTemplates:
    def test_import_creates_template_entities(self, session):
        ds = _import_templated_ds(session)
        assert len(ds.templates) == 1
        template = ds.templates[0]
        assert template.name == "Acme Corporate"
        logo_id = _asset_id_by_filename(ds, "logo.svg")
        assert f"{{{{ds-asset:{logo_id}}}}}" in template.layout_html

    def test_import_retains_template_preview_as_template_shot_asset(self, session):
        ds = _import_templated_ds(session)
        previews = [a for a in ds.assets if a.kind == "template_shot"]
        assert [a.filename for a in previews] == ["preview.png"]
        reference_rows = [
            f for f in ds.files if f.path == "templates/corporate/preview.png"
        ]
        assert len(reference_rows) == 1
        assert reference_rows[0].asset_id == previews[0].id
        assert reference_rows[0].data is None  # reference row, bytes not double-stored
        assert ds.templates[0].thumbnail_asset_id == previews[0].id

    def test_template_shot_assets_hidden_from_brand_asset_search(self, session):
        from src.services.design_system_service import search_assets

        ds = _import_templated_ds(session)
        filenames = [a.filename for a in search_assets(session, ds.id)]
        assert "preview.png" not in filenames

    def test_bundle_without_template_files_imports_with_no_templates(self, session):
        files = templated_bundle_files()
        files.pop("templates/corporate/index.html")
        files.pop("templates/corporate/preview.png")
        ds = _import_templated_ds(session, files=files)
        assert ds.templates == []

    def test_compiled_style_content_stays_template_agnostic(self, session):
        ds = _import_templated_ds(session)
        assert "SELECTED SLIDE TEMPLATE" not in ds.compiled_style_content


# ---------------------------------------------------------------------------
# Real-export thumbnail shape: templates/<slug>/.thumbnail
#
# A real Claude-Design export ships ONE screenshot per template folder that is
# dot-prefixed, named ``thumbnail`` (not ``preview``), and carries NO extension —
# so its type is knowable only from its magic bytes. Every one of them used to be
# discarded (the dotfile skip in ``_iter_safe_entries`` dropped the entry before
# the preview recognizer ran, the recognizer would have rejected it anyway, and
# the thumbnail lookup only matched ``preview*``), leaving the picker with no
# thumbnail and ``thumbnail_url`` NULL.
# ---------------------------------------------------------------------------


def _import_dot_thumbnail_ds(session, *, files=None, manifest=None):
    """Import the real-export-shaped bundle (a ``.thumbnail`` per template)."""
    from src.services.design_system_service import import_bundle

    zip_bytes = make_bundle_zip(
        manifest=manifest if manifest is not None else dot_thumbnail_manifest(),
        files=files if files is not None else dot_thumbnail_bundle_files(),
    )
    return import_bundle(session, zip_bytes=zip_bytes, user="tester")


class TestImportDotPrefixedTemplateThumbnails:
    def test_every_dot_thumbnail_is_stored_as_a_template_shot(self, session):
        ds = _import_dot_thumbnail_ds(session)
        shots = [a for a in ds.assets if a.kind == "template_shot"]
        assert len(shots) == len(DOT_THUMBNAIL_SLUGS), (
            f"expected {len(DOT_THUMBNAIL_SLUGS)} stored thumbnails, "
            f"got {len(shots)}: {[a.filename for a in shots]}"
        )
        assert {a.filename for a in shots} == {".thumbnail"}

    def test_extension_less_thumbnail_content_type_is_sniffed_from_magic_bytes(
        self, session
    ):
        ds = _import_dot_thumbnail_ds(session)
        shots = [a for a in ds.assets if a.kind == "template_shot"]
        # No extension to guess from: the type comes from RIFF....WEBP, NOT from
        # a fallback like application/octet-stream.
        assert {a.mime for a in shots} == {"image/webp"}

    def test_thumbnail_reference_rows_do_not_double_store_bytes(self, session):
        ds = _import_dot_thumbnail_ds(session)
        shot_ids = {a.id for a in ds.assets if a.kind == "template_shot"}
        rows = [f for f in ds.files if f.path.endswith("/.thumbnail")]
        assert len(rows) == len(DOT_THUMBNAIL_SLUGS)
        assert {f.asset_id for f in rows} == shot_ids
        assert all(f.data is None for f in rows)

    def test_every_template_gets_a_non_null_thumbnail_asset(self, session):
        ds = _import_dot_thumbnail_ds(session)
        assert len(ds.templates) == len(DOT_THUMBNAIL_SLUGS)
        unlinked = [t.entry_path for t in ds.templates if t.thumbnail_asset_id is None]
        assert unlinked == [], f"templates with a NULL thumbnail: {unlinked}"

    def test_each_template_links_the_thumbnail_from_its_own_folder(self, session):
        """Per-folder, not first-wins: template N must not borrow template 1's shot."""
        ds = _import_dot_thumbnail_ds(session)
        asset_path_by_id = {
            f.asset_id: f.path for f in ds.files if f.asset_id is not None
        }
        for template in ds.templates:
            folder = template.entry_path.rsplit("/", 1)[0]
            assert asset_path_by_id[template.thumbnail_asset_id] == f"{folder}/.thumbnail"

    def test_intrinsic_dimensions_are_recorded_from_the_sniffed_image(self, session):
        ds = _import_dot_thumbnail_ds(session)
        shots = [a for a in ds.assets if a.kind == "template_shot"]
        # Fixture widths/heights are distinct per folder, so this also proves the
        # four rows carry four different images rather than one repeated blob.
        assert sorted((a.width, a.height) for a in shots) == [
            (10, 6), (11, 7), (12, 8), (13, 9)
        ]

    def test_dot_thumbnails_stay_hidden_from_brand_asset_search(self, session):
        """A thumbnail must never be placeable brand content in a slide."""
        from src.services.design_system_service import search_assets

        ds = _import_dot_thumbnail_ds(session)
        found = search_assets(session, ds.id)
        assert ".thumbnail" not in [a.filename for a in found]
        assert "template_shot" not in [a.kind for a in found]

    def test_re_import_does_not_duplicate_thumbnail_rows(self, session):
        """Two imports of the same bundle are two design systems, each with its
        own four thumbnails — never eight rows on one, never a second row per
        template folder."""
        first = _import_dot_thumbnail_ds(session)
        second_manifest = dot_thumbnail_manifest()
        second_manifest["name"] = "Acme Dot Thumbnail DS Copy"
        second = _import_dot_thumbnail_ds(session, manifest=second_manifest)

        for ds in (first, second):
            shots = [a for a in ds.assets if a.kind == "template_shot"]
            assert len(shots) == len(DOT_THUMBNAIL_SLUGS)
            assert len({t.thumbnail_asset_id for t in ds.templates}) == len(
                DOT_THUMBNAIL_SLUGS
            )
        assert first.id != second.id

    def test_repeated_materialize_keeps_one_thumbnail_per_template(self, session):
        """The lazy materializer is idempotent: re-running it over an already
        imported system neither adds template rows nor re-points thumbnails."""
        from src.services.design_system_templates import materialize_templates

        ds = _import_dot_thumbnail_ds(session)
        before = {t.id: t.thumbnail_asset_id for t in ds.templates}
        assert materialize_templates(ds) == list(ds.templates)
        session.commit()
        assert {t.id: t.thumbnail_asset_id for t in ds.templates} == before

    def test_preview_png_bundles_are_unaffected(self, session):
        """The documented ``templates/<slug>/preview.png`` shape keeps working."""
        ds = _import_templated_ds(session)
        shots = [a for a in ds.assets if a.kind == "template_shot"]
        assert [(a.filename, a.mime) for a in shots] == [("preview.png", "image/png")]
        assert ds.templates[0].thumbnail_asset_id == shots[0].id


# ---------------------------------------------------------------------------
# BYTE-IDENTICAL thumbnails in DIFFERENT template folders
# ---------------------------------------------------------------------------
#
# The real export ships four template thumbnails and two of them are GENUINELY
# byte-identical: ``templates/reference-architecture/.thumbnail`` and
# ``templates/strategy-consulting/.thumbnail`` are both 10,040 bytes with the same
# sha256, while ``corporate`` (11,526 B) and ``executive-events`` (7,870 B) differ.
#
# Identical content is precisely the case a content-keyed or first-wins lookup gets
# wrong: it binds one folder's thumbnail to another folder's template, or collapses
# two folders onto one asset row — and every template still LOOKS like it has a
# thumbnail, so the failure is invisible in a count.
#
# Neither existing test could see it.
# ``test_each_template_links_the_thumbnail_from_its_own_folder`` checks binding but
# with DISTINCT bytes per folder, and
# ``TestTemplateThumbnailFormatSniffing._shots`` uses identical bytes but only
# counts rows and checks their MIME. This closes the gap: own-folder binding, with
# identical bytes.
# ---------------------------------------------------------------------------

#: The two slugs whose thumbnails are byte-identical in the real export.
IDENTICAL_THUMBNAIL_SLUGS = ("reference-architecture", "strategy-consulting")

#: The shapes worth pinning: the real export's two-of-four, and the degenerate
#: all-four case where content carries no distinguishing information at all.
IDENTICAL_THUMBNAIL_CASES = [
    pytest.param(IDENTICAL_THUMBNAIL_SLUGS, id="two-identical-as-shipped"),
    pytest.param(DOT_THUMBNAIL_SLUGS, id="all-four-identical"),
]


class TestByteIdenticalThumbnailsStayBoundToTheirOwnFolder:
    IDENTICAL_BYTES = webp_bytes(10, 10)

    def _files(self, slugs):
        """Real-export-shaped bundle files with ``slugs`` sharing ONE payload."""
        files = dot_thumbnail_bundle_files()
        for slug in slugs:
            files[f"templates/{slug}/.thumbnail"] = self.IDENTICAL_BYTES
        return files

    def _import(self, session, slugs):
        return _import_dot_thumbnail_ds(session, files=self._files(slugs))

    def test_the_fixture_really_does_ship_identical_bytes(self):
        """Guard the guard: if the shared payload ever stops being shared, every
        test below keeps passing while testing nothing it exists to test."""
        files = self._files(IDENTICAL_THUMBNAIL_SLUGS)
        shared = {
            files[f"templates/{slug}/.thumbnail"]
            for slug in IDENTICAL_THUMBNAIL_SLUGS
        }
        assert len(shared) == 1, "the two 'identical' thumbnails are not identical"
        others = [
            files[f"templates/{slug}/.thumbnail"]
            for slug in DOT_THUMBNAIL_SLUGS
            if slug not in IDENTICAL_THUMBNAIL_SLUGS
        ]
        # ...and the other two still differ, from each other and from the pair, so
        # the fixture mirrors the export rather than flattening to one payload.
        assert len(set(others)) == len(others)
        assert not any(payload in shared for payload in others)

    @pytest.mark.parametrize("slugs", IDENTICAL_THUMBNAIL_CASES)
    def test_all_four_templates_resolve_their_own_folders_thumbnail(
        self, session, slugs
    ):
        ds = self._import(session, slugs)
        asset_path_by_id = {
            f.asset_id: f.path for f in ds.files if f.asset_id is not None
        }
        assert len(ds.templates) == len(DOT_THUMBNAIL_SLUGS)

        resolved = {}
        for template in ds.templates:
            folder = template.entry_path.rsplit("/", 1)[0]
            assert template.thumbnail_asset_id is not None, (
                f"{folder} resolved no thumbnail at all"
            )
            resolved[folder] = asset_path_by_id[template.thumbnail_asset_id]

        assert resolved == {
            f"templates/{slug}": f"templates/{slug}/.thumbnail"
            for slug in DOT_THUMBNAIL_SLUGS
        }, "a template is serving a thumbnail from another template's folder"

    @pytest.mark.parametrize("slugs", IDENTICAL_THUMBNAIL_CASES)
    def test_each_folder_keeps_its_own_asset_row(self, session, slugs):
        """Rows are per ENTRY, not per CONTENT. Two folders sharing bytes must not
        share an asset row — sharing is how one template comes to serve another's
        thumbnail URL, and how deleting one would blank the other."""
        ds = self._import(session, slugs)
        shots = [a for a in ds.assets if a.kind == "template_shot"]
        assert len(shots) == len(DOT_THUMBNAIL_SLUGS), (
            f"expected one thumbnail row per folder, got {len(shots)}"
        )
        linked = [t.thumbnail_asset_id for t in ds.templates]
        assert len(set(linked)) == len(DOT_THUMBNAIL_SLUGS), (
            f"templates share thumbnail asset rows: {linked}"
        )


class TestTemplateThumbnailFormatSniffing:
    """Only real PNG/JPEG/GIF/WebP bytes are stored; anything else is refused
    rather than persisted under a guessed content type."""

    def _shots(self, session, thumbnail_bytes, *, name="Acme Sniff DS"):
        files = dot_thumbnail_bundle_files()
        for slug in DOT_THUMBNAIL_SLUGS:
            files[f"templates/{slug}/.thumbnail"] = thumbnail_bytes
        manifest = dot_thumbnail_manifest()
        manifest["name"] = name
        ds = _import_dot_thumbnail_ds(session, files=files, manifest=manifest)
        return ds, [a for a in ds.assets if a.kind == "template_shot"]

    @pytest.mark.parametrize(
        "make_bytes,expected_mime",
        [
            (png_bytes, "image/png"),
            (jpeg_bytes, "image/jpeg"),
            (gif_bytes, "image/gif"),
            (webp_bytes, "image/webp"),
        ],
    )
    def test_each_supported_raster_format_is_sniffed(
        self, session, make_bytes, expected_mime
    ):
        _, shots = self._shots(session, make_bytes())
        assert len(shots) == len(DOT_THUMBNAIL_SLUGS)
        assert {a.mime for a in shots} == {expected_mime}

    def test_non_image_bytes_are_refused_not_stored_as_octet_stream(self, session):
        ds, shots = self._shots(session, b"#!/bin/sh\necho not an image\n")
        assert shots == []
        # The rest of the bundle still imports — one junk thumbnail must not
        # cost the whole upload — the templates simply carry no thumbnail.
        assert len(ds.templates) == len(DOT_THUMBNAIL_SLUGS)
        assert all(t.thumbnail_asset_id is None for t in ds.templates)

    def test_svg_thumbnail_is_refused(self, session):
        """SVG can carry inline script and is not a sniffable raster format."""
        _, shots = self._shots(session, SVG_LOGO)
        assert shots == []

    def test_riff_container_that_is_not_webp_is_refused(self, session):
        """``RIFF`` alone is not enough — bytes 8:12 must spell ``WEBP``
        (a RIFF/WAVE file must not be stored as image/webp)."""
        wav = b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt " + b"\0" * 24
        _, shots = self._shots(session, wav)
        assert shots == []

    def test_truncated_magic_bytes_are_refused(self, session):
        _, shots = self._shots(session, b"RIF")
        assert shots == []


class TestExtensionLessScreenshotBasenames:
    """The allowlisted shape is ``templates/<folder>/`` + an optional single dot +
    ``thumbnail``/``preview`` + nothing else. Each accepted spelling is covered so
    no branch of it is untested."""

    def _import_with_basename(self, session, basename):
        files = dot_thumbnail_bundle_files()
        for slug in DOT_THUMBNAIL_SLUGS:
            del files[f"templates/{slug}/.thumbnail"]
            files[f"templates/{slug}/{basename}"] = webp_bytes()
        manifest = dot_thumbnail_manifest()
        manifest["name"] = f"Acme {basename} DS"
        return _import_dot_thumbnail_ds(session, files=files, manifest=manifest)

    @pytest.mark.parametrize(
        "basename", [".thumbnail", "thumbnail", ".preview", "preview"]
    )
    def test_accepted_spelling_is_stored_and_linked(self, session, basename):
        ds = self._import_with_basename(session, basename)
        shots = [a for a in ds.assets if a.kind == "template_shot"]
        assert len(shots) == len(DOT_THUMBNAIL_SLUGS)
        assert {a.filename for a in shots} == {basename}
        assert {a.mime for a in shots} == {"image/webp"}
        assert all(t.thumbnail_asset_id is not None for t in ds.templates)

    @pytest.mark.parametrize(
        "basename", ["thumbnail.bak", "thumb", "screenshot", "previews", "thumbnails"]
    )
    def test_other_basenames_are_not_treated_as_screenshots(self, session, basename):
        ds = self._import_with_basename(session, basename)
        assert [a for a in ds.assets if a.kind == "template_shot"] == []
        assert all(t.thumbnail_asset_id is None for t in ds.templates)


# ---------------------------------------------------------------------------
# Generation lookup (validation: exists AND belongs, else None + log)
# ---------------------------------------------------------------------------


class TestGetTemplateForGeneration:
    def test_returns_owned_template(self, session):
        from src.services.design_system_templates import get_template_for_generation

        ds = _import_templated_ds(session)
        template = get_template_for_generation(ds, ds.templates[0].id)
        assert template is ds.templates[0]

    def test_template_of_other_design_system_ignored_and_logged(self, session, caplog):
        from src.services.design_system_templates import get_template_for_generation

        ds_a = _import_templated_ds(session)
        manifest_b = templated_manifest()
        manifest_b["name"] = "Acme Second DS"
        ds_b = _import_templated_ds(session, manifest=manifest_b)

        with caplog.at_level(logging.WARNING, logger="src.services.design_system_templates"):
            assert get_template_for_generation(ds_a, ds_b.templates[0].id) is None
        assert "template" in caplog.text.lower()

    def test_missing_template_id_ignored_and_logged(self, session, caplog):
        from src.services.design_system_templates import get_template_for_generation

        ds = _import_templated_ds(session)
        with caplog.at_level(logging.WARNING, logger="src.services.design_system_templates"):
            assert get_template_for_generation(ds, 424242) is None
        assert "424242" in caplog.text

    def test_lazily_materializes_pre_phase4_rows(self, session):
        from src.services.design_system_templates import get_template_for_generation

        ds = _file_backed_ds(session, manifest=templated_manifest())
        session.commit()
        assert ds.templates == []
        # Any id misses on a never-materialized system, but the call must
        # materialize the rows so subsequent lookups (list endpoint, retries)
        # can resolve them.
        get_template_for_generation(ds, 424242)
        assert len(ds.templates) == 1


# ---------------------------------------------------------------------------
# SELECTED-TEMPLATE prompt block (modular consumption seam)
# ---------------------------------------------------------------------------


class TestBuildSelectedTemplateBlock:
    def _template(self, session):
        ds = _import_templated_ds(session)
        return ds, ds.templates[0]

    def test_block_carries_layout_css_and_instructions(self, session):
        from src.services.design_system_compiler import DESIGN_SYSTEM_SCOPE_FIREWALL
        from src.services.design_system_templates import build_selected_template_block

        ds, template = self._template(session)
        block = build_selected_template_block(template)

        assert block.startswith("SELECTED SLIDE TEMPLATE: Acme Corporate")
        assert "Cover + agenda, content, closing." in block
        # Pinned-precedence over the compiled artifact's soft SLIDE TEMPLATES
        # list (kept from Round 1).
        assert "SLIDE TEMPLATES" in block
        # Round-2 framing (live Claude Design probe): the layout is an
        # edit-in-place STARTING FILE, not an exemplar catalog.
        assert "STARTING FILE" in block
        assert "produce the deck by editing it" in block
        assert "keep its classes, CSS, and structure intact" in block
        assert "trim or repeat its slide sections" in block
        assert "ARCHETYPE CATALOG" not in block
        assert "NOT a deck outline" not in block
        assert "TEMPLATE LAYOUT HTML" not in block
        assert "TEMPLATE STARTING FILE (edit this HTML in place):" in block
        # Guards, restated in the edit-in-place frame.
        assert "PLACEHOLDER, never fact" in block
        assert "Omit sample sections you have no content for" in block
        assert "never redefine the template's selectors" in block
        assert "vary which slide sections you reuse" in block
        # Scope firewall rides in the block too (and once in the artifact).
        assert DESIGN_SYSTEM_SCOPE_FIREWALL in block
        # Token definitions must be carried into the emitted deck's CSS.
        assert "TOKEN STYLESHEET" in block
        assert "into the emitted deck's CSS" in block
        assert "--brand-core-primary: #123456" in block
        # Rewritten layout HTML rides along with its asset handles.
        logo_id = _asset_id_by_filename(ds, "logo.svg")
        assert f"{{{{ds-asset:{logo_id}}}}}" in block
        assert "var(--acme-navy)" in block
        assert block.rstrip().endswith("END OF SELECTED SLIDE TEMPLATE.")

    def test_instructions_mandate_exact_native_sizes_on_cover_and_closing(self, session):
        """dsv2 F6: pinned generations under-obeyed template-native heading
        sizes precisely on cover/closing slides (64px where the template
        ships 72/80). The keep-sizes bullet must demand the template's OWN
        sizes exactly — cover and closing included, never a tier smaller."""
        from src.services.design_system_templates import build_selected_template_block

        _, template = self._template(session)
        block = build_selected_template_block(template)
        lowered = block.lower()
        assert "exactly" in lowered
        assert "cover" in lowered and "closing" in lowered
        assert "never a tier smaller" in lowered

    def test_block_without_token_css_omits_stylesheet_section(self, session):
        from src.services.design_system_templates import build_selected_template_block

        _, template = self._template(session)
        template.token_css = None
        block = build_selected_template_block(template)
        assert "TOKEN STYLESHEET" not in block
        assert "into the emitted deck's CSS" not in block  # carry bullet is conditional too
        assert "SELECTED SLIDE TEMPLATE" in block

    def test_empty_layout_returns_none(self, session):
        from src.services.design_system_templates import build_selected_template_block

        _, template = self._template(session)
        template.layout_html = "   "
        assert build_selected_template_block(template) is None

    @pytest.mark.parametrize("layout_chars", [120_000, 120_001, 500_000])
    def test_a_long_layout_is_never_turned_away(self, session, layout_chars):
        """SUPERSEDES ``test_oversized_layout_falls_back_to_none_with_warning``.

        That test asserted the DEFECT: a selected template whose layout exceeded
        120,000 characters was DROPPED ENTIRELY and the deck generated with no
        template at all. The layout is USER-SUPPLIED BRAND LAYOUT TEXT, and it is not
        one of the deliberate binary OOM guards (those are the per-asset and
        per-bundle BYTE limits, which stay), so per the hard requirement it must not
        be turned away or silently dropped.

        The boundary codex measured was ``120000 emitted=True / 120001
        emitted=False`` — one character deciding whether the user's pinned template
        reached the model. The new assertion is strictly stronger: it holds at the
        old boundary, one past it, and far past it.
        """
        from src.services.design_system_templates import build_selected_template_block

        _, template = self._template(session)
        template.layout_html = "<div>" + ("x" * (layout_chars - 11)) + "</div>"
        assert len(template.layout_html) == layout_chars

        block = build_selected_template_block(template)

        assert block is not None, (
            f"a {layout_chars}-character brand layout was dropped entirely; the user "
            "pinned this template and the deck would generate without it"
        )
        assert "SELECTED SLIDE TEMPLATE" in block
        # The layout itself is present, in full — not truncated.
        assert template.layout_html in block, (
            "the brand layout was altered or truncated on its way into the prompt"
        )

