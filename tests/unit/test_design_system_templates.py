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
    SVG_LOGO,
    TEMPLATED_TEMPLATE_HTML,
    make_bundle_zip,
    template_preview_png,
    templated_bundle_files,
    templated_manifest,
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

    def test_oversized_layout_falls_back_to_none_with_warning(self, session, caplog):
        from src.services.design_system_templates import (
            MAX_TEMPLATE_LAYOUT_CHARS,
            build_selected_template_block,
        )

        _, template = self._template(session)
        template.layout_html = "x" * (MAX_TEMPLATE_LAYOUT_CHARS + 1)
        with caplog.at_level(logging.WARNING, logger="src.services.design_system_templates"):
            assert build_selected_template_block(template) is None
        assert "layout" in caplog.text.lower()
