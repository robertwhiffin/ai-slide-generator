"""Unit tests for the Design System compile-to-prompt serializer.

Phase 2 of the Design System Library feature (see
``docs/technical/design-system-library-spec.md`` §8). The compiler turns a
structured design system (tokens + templates + brand assets) into the
``compiled_style_content`` prompt text that maps to today's
``slide_style_library.style_content``.

Coverage:
- Color tokens render as a textual spec grouped by group AND as a
  ``:root { --brand-* }`` CSS-var block.
- Typography + spacing tokens render as rules.
- Template names/descriptions (from the manifest) render as layout guidance.
- Brand assets render as ``{{ds-asset:ID}}`` references (a distinct namespace
  from the ``{{image:ID}}`` used for the ``image_assets`` table) so real assets
  can be embedded via the existing placeholder mechanism.
- Output is deterministic regardless of token/asset input order.
- ``recompute_compiled_style_content`` stores the compiled text on the record.

All fixtures are SYNTHETIC (fake "Acme" brand, dummy hex, placeholder bytes) —
no real brand content, per the public-repo hygiene rule.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register models with Base.metadata
from src.core.database import Base


@pytest.fixture
def session():
    """In-memory SQLite session (StaticPool keeps one connection alive)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


def _make_ds(
    session,
    *,
    name="Acme Design System",
    description="Synthetic fixture brand — not real.",
    tokens=None,
    assets=None,
    manifest_json=None,
):
    """Persist a synthetic DesignSystem (+ tokens/assets) and return it.

    Persisting is what assigns primary keys, so brand-asset references can point
    at real asset IDs. ``tokens``/``assets`` are lists of plain dicts.
    """
    from src.database.models.design_system import (
        DesignSystem,
        DesignSystemAsset,
        DesignSystemToken,
    )

    ds = DesignSystem(
        name=name,
        description=description,
        manifest_json=manifest_json,
    )
    for tok in tokens or []:
        ds.tokens.append(DesignSystemToken(**tok))
    for asset in assets or []:
        ds.assets.append(DesignSystemAsset(**asset))
    session.add(ds)
    session.commit()
    session.refresh(ds)
    return ds


# Synthetic token/asset fixtures deliberately in UNSORTED order so tests prove
# the compiler imposes deterministic ordering itself.
_TOKENS = [
    {"group": "accents", "name": "lava", "value": "#EB4A34"},
    {"group": "core", "name": "primary", "value": "#123456"},
    {"group": "core", "name": "background", "value": "#F9FAFB"},
    {"group": "ink", "name": "body", "value": "#5D6D71"},
    {"group": "tints", "name": "tint-10", "value": "#EEEEEE"},
    {"group": "type", "name": "heading-font", "value": "Inter, sans-serif"},
    {"group": "type", "name": "h1-size", "value": "48px"},
    {"group": "spacing", "name": "md", "value": "16px"},
    {"group": "spacing", "name": "lg", "value": "24px"},
]

_ASSETS = [
    {"kind": "background", "filename": "hero-bg.png", "mime": "image/png",
     "data": b"\x89PNG placeholder", "size_bytes": 16},
    {"kind": "logo", "filename": "acme-logo.svg", "mime": "image/svg+xml",
     "data": b"<svg/>", "size_bytes": 6},
    {"kind": "font", "filename": "acme.woff2", "mime": "font/woff2",
     "data": b"font-bytes", "size_bytes": 10},
    {"kind": "template_shot", "filename": "title-shot.png", "mime": "image/png",
     "data": b"shot", "size_bytes": 4},
]

_MANIFEST = {
    "name": "Acme",
    "version": "1.0.0",
    "templates": [
        {"name": "Title Slide", "description": "Centered hero with logo lockup."},
        {"name": "Two Column", "description": "Left text, right chart."},
        {"name": "No Desc Template"},
    ],
}


# ---------------------------------------------------------------------------
# Color tokens: textual spec + :root CSS vars
# ---------------------------------------------------------------------------


class TestColorTokens:
    def test_header_and_name(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS)
        out = compile_design_system(ds)
        assert out.startswith("SLIDE VISUAL STYLE: Acme Design System")

    def test_color_values_present(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS)
        out = compile_design_system(ds)
        assert "#123456" in out
        assert "#EB4A34" in out
        assert "primary" in out
        assert "lava" in out

    def test_root_css_vars_present(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS)
        out = compile_design_system(ds)
        assert ":root {" in out
        assert "--brand-core-primary: #123456;" in out
        assert "--brand-accents-lava: #EB4A34;" in out
        assert "--brand-ink-body: #5D6D71;" in out

    def test_color_groups_ordered_core_before_accents(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS)
        out = compile_design_system(ds)
        # core group listed before accents before ink before tints
        assert out.index("--brand-core-") < out.index("--brand-accents-")
        assert out.index("--brand-accents-") < out.index("--brand-ink-")
        assert out.index("--brand-ink-") < out.index("--brand-tints-")

    def test_token_names_sorted_within_group(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS)
        out = compile_design_system(ds)
        # within core: background sorts before primary
        assert out.index("--brand-core-background") < out.index("--brand-core-primary")


# ---------------------------------------------------------------------------
# Typography + spacing
# ---------------------------------------------------------------------------


class TestTypographyAndSpacing:
    def test_typography_rendered(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS)
        out = compile_design_system(ds)
        assert "TYPOGRAPHY" in out
        assert "heading-font" in out
        assert "Inter, sans-serif" in out
        assert "48px" in out

    def test_spacing_rendered(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS)
        out = compile_design_system(ds)
        assert "SPACING" in out
        assert "md" in out
        assert "16px" in out
        assert "24px" in out

    def test_type_and_spacing_not_in_css_root_block(self, session):
        """type/spacing are rules, not --brand-* color vars."""
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS)
        out = compile_design_system(ds)
        assert "--brand-type-" not in out
        assert "--brand-spacing-" not in out


# ---------------------------------------------------------------------------
# Templates (from the manifest)
# ---------------------------------------------------------------------------


class TestTemplates:
    def test_template_names_and_descriptions(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS, manifest_json=_MANIFEST)
        out = compile_design_system(ds)
        assert "TEMPLATES" in out
        assert "Title Slide" in out
        assert "Centered hero with logo lockup." in out
        assert "Two Column" in out
        assert "No Desc Template" in out

    def test_no_templates_section_when_manifest_absent(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS, manifest_json=None)
        out = compile_design_system(ds)
        assert "TEMPLATES" not in out

    def test_malformed_template_entries_skipped(self, session):
        from src.services.design_system_compiler import compile_design_system

        manifest = {"templates": ["not-a-dict", {"description": "no name"}, {"name": "Good"}]}
        ds = _make_ds(session, manifest_json=manifest)
        out = compile_design_system(ds)
        assert "Good" in out
        assert "not-a-dict" not in out


# ---------------------------------------------------------------------------
# Brand assets: {{ds-asset:ID}} references
# ---------------------------------------------------------------------------


class TestBrandAssets:
    def test_image_assets_referenced_by_ds_asset_placeholder(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, assets=_ASSETS)
        out = compile_design_system(ds)
        logo = next(a for a in ds.assets if a.kind == "logo")
        bg = next(a for a in ds.assets if a.kind == "background")
        assert "BRAND ASSETS" in out
        assert f"{{{{ds-asset:{logo.id}}}}}" in out
        assert f"{{{{ds-asset:{bg.id}}}}}" in out
        assert "acme-logo.svg" in out

    def test_does_not_collide_with_image_placeholder(self, session):
        """Design-system assets must NOT use the {{image:ID}} namespace, which
        resolves against the unrelated image_assets table."""
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, assets=_ASSETS)
        out = compile_design_system(ds)
        assert "{{image:" not in out

    def test_font_assets_rendered_separately(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, assets=_ASSETS)
        out = compile_design_system(ds)
        font = next(a for a in ds.assets if a.kind == "font")
        assert "FONT" in out.upper()
        assert f"{{{{ds-asset:{font.id}}}}}" in out
        assert "acme.woff2" in out

    def test_template_shot_not_embedded_as_brand_asset(self, session):
        """template_shot assets are preview/reference material, not embeddable
        slide content, so their placeholder must not be emitted."""
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, assets=_ASSETS)
        out = compile_design_system(ds)
        shot = next(a for a in ds.assets if a.kind == "template_shot")
        assert f"{{{{ds-asset:{shot.id}}}}}" not in out

    def test_no_brand_assets_section_when_none(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS)
        out = compile_design_system(ds)
        assert "BRAND ASSETS" not in out


# ---------------------------------------------------------------------------
# Determinism + empty
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_compile_twice_identical(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS, assets=_ASSETS, manifest_json=_MANIFEST)
        assert compile_design_system(ds) == compile_design_system(ds)

    def test_output_independent_of_input_order(self, session):
        """Reversing the loaded token/asset relationship lists must not change
        the compiled output — the compiler imposes its own deterministic order."""
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS, assets=_ASSETS, manifest_json=_MANIFEST)
        out = compile_design_system(ds)
        ds.tokens.reverse()
        ds.assets.reverse()
        out_reversed = compile_design_system(ds)
        assert out == out_reversed

    def test_empty_design_system_has_header_only(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, description=None, tokens=None, assets=None, manifest_json=None)
        out = compile_design_system(ds)
        assert out.startswith("SLIDE VISUAL STYLE:")
        assert "BRAND COLOR TOKENS" not in out
        assert "BRAND ASSETS" not in out
        assert "TEMPLATES" not in out


# ---------------------------------------------------------------------------
# recompute + store
# ---------------------------------------------------------------------------


class TestRecompute:
    def test_recompute_sets_compiled_style_content(self, session):
        from src.services.design_system_compiler import (
            compile_design_system,
            recompute_compiled_style_content,
        )

        ds = _make_ds(session, tokens=_TOKENS, assets=_ASSETS, manifest_json=_MANIFEST)
        assert ds.compiled_style_content is None
        result = recompute_compiled_style_content(ds)
        assert result == compile_design_system(ds)
        assert ds.compiled_style_content == result
        assert "SLIDE VISUAL STYLE:" in ds.compiled_style_content

    def test_recompute_is_idempotent(self, session):
        from src.services.design_system_compiler import recompute_compiled_style_content

        ds = _make_ds(session, tokens=_TOKENS, assets=_ASSETS, manifest_json=_MANIFEST)
        first = recompute_compiled_style_content(ds)
        second = recompute_compiled_style_content(ds)
        assert first == second

    def test_recompute_persists_through_session(self, session):
        from src.database.models.design_system import DesignSystem
        from src.services.design_system_compiler import recompute_compiled_style_content

        ds = _make_ds(session, tokens=_TOKENS)
        recompute_compiled_style_content(ds)
        session.commit()
        ds_id = ds.id
        session.expire_all()
        reloaded = session.get(DesignSystem, ds_id)
        assert reloaded.compiled_style_content is not None
        assert "--brand-core-primary" in reloaded.compiled_style_content
