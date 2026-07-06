"""Unit tests for the Design System compile-to-prompt serializer (Phase 2 RESET).

The compiler turns a structured design system into ``compiled_style_content`` — the
drop-in equivalent of ``slide_style_library.style_content``. The Phase-2 reset
makes it README/SKILL-central and UNCAPPED, matching the huashu / Claude-Design
"brand operating manual" model:

- The FULL README then the FULL SKILL.md are injected FIRST, UNFILTERED and
  UNTRUNCATED (no rule-only keyword filter, no char budget).
- ALL tokens (color/type/spacing/shadow) and ALL fonts (@font-face refs + family
  listing) are emitted UNCAPPED.
- Brand IMAGE assets are NOT enumerated: the compiled content carries a short
  CONTRACT telling the model to fetch them on demand via the ``search_brand_assets``
  tool (which returns ``{{ds-asset:ID}}`` handles). Fonts remain the one asset kind
  wired inline (via @font-face), because @font-face must resolve at generation time.

Everything is pure and deterministic. All fixtures are SYNTHETIC (fake "Acme"
brand, dummy hex, placeholder bytes) — no real brand content.
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
    files=None,
    font_mapping_json=None,
):
    """Persist a synthetic DesignSystem (+ tokens/assets/files) and return it."""
    from src.database.models.design_system import (
        DesignSystem,
        DesignSystemAsset,
        DesignSystemFile,
        DesignSystemToken,
    )

    ds = DesignSystem(
        name=name,
        description=description,
        manifest_json=manifest_json,
        font_mapping_json=font_mapping_json,
    )
    for tok in tokens or []:
        ds.tokens.append(DesignSystemToken(**tok))
    for asset in assets or []:
        ds.assets.append(DesignSystemAsset(**asset))
    for ds_file in files or []:
        ds.files.append(DesignSystemFile(**ds_file))
    session.add(ds)
    session.commit()
    session.refresh(ds)
    return ds


def _file(kind, text, *, path=None, mime="text/markdown"):
    """A synthetic ``design_system_file`` SOURCE row dict (bytes stored in-DB)."""
    data = text.encode("utf-8") if isinstance(text, str) else text
    return {
        "path": path or f"{kind.upper()}.md",
        "kind": kind,
        "mime": mime,
        "data": data,
        "size_bytes": len(data or b""),
    }


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

_SHADOW_TOKENS = [
    {"group": "shadow", "name": "sm", "value": "0 1px 2px rgba(0,0,0,0.1)"},
    {"group": "shadow", "name": "lg", "value": "0 10px 20px rgba(0,0,0,0.2)"},
]

# Brand IMAGE assets (never enumerated in compiled content — fetched via the tool).
_IMAGE_ASSETS = [
    {"kind": "background", "filename": "hero-bg.png", "mime": "image/png",
     "data": b"\x89PNG placeholder", "size_bytes": 16},
    {"kind": "logo", "filename": "acme-logo.svg", "mime": "image/svg+xml",
     "data": b"<svg/>", "size_bytes": 6},
    {"kind": "icon", "filename": "icon.svg", "mime": "image/svg+xml",
     "data": b"<svg/>", "size_bytes": 6},
]
# Font asset — the ONE kind still wired inline (via @font-face) in compiled content.
_FONT_ASSET = {"kind": "font", "filename": "acme.woff2", "mime": "font/woff2",
               "data": b"font-bytes", "size_bytes": 10}
# template_shot — reference-only, never referenced as brand content.
_TEMPLATE_SHOT = {"kind": "template_shot", "filename": "title-shot.png",
                  "mime": "image/png", "data": b"shot", "size_bytes": 4}

_MANIFEST = {
    "name": "Acme",
    "version": "1.0.0",
    "templates": [
        {"name": "Title Slide", "description": "Centered hero with logo lockup."},
        {"name": "Two Column", "description": "Left text, right chart."},
        {"name": "No Desc Template"},
    ],
}

# SKILL.md — the concise, authoritative rules doc (injected in FULL).
_SKILL_MD = (
    "---\nname: acme-brand\n---\n\n"
    "# Acme brand skill\n"
    "- Always place the logo top-left with clear space.\n"
    "- Never recolor or stretch the logo.\n"
    "- Prefer the accent color for a single emphasis per slide.\n"
)

# README.md — long prose. The reset injects it in FULL, including the overview /
# history sections the OLD rule-only filter used to drop.
_README_MD = (
    "# Acme Design System\n\n"
    "## Overview\n"
    "Acme is a synthetic brand used only in tests. This overview is background "
    "prose that the OLD filter dropped but the reset now injects in full.\n\n"
    "## Voice & Tone\n"
    "Friendly, concise, confident. Avoid jargon.\n\n"
    "## Do's and Don'ts\n"
    "- Do use the brand color palette.\n"
    "- Don't place text over busy backgrounds.\n\n"
    "## Data Visualization Guidelines\n"
    "Use the accent palette for the primary series; keep gridlines subtle.\n\n"
    "## Company History\n"
    "Founded in a fixture in 2020. Narrative prose, now injected in full.\n"
)

# Synthetic normalized font mapping (shape produced by ``build_font_mapping``).
_FONT_MAPPING = {
    "families": [
        {
            "family": "Acme Sans",
            "variants": [
                {"weight": "400", "style": "normal", "files": ["fonts/acme-sans-regular.woff2"]},
                {"weight": "700", "style": "normal", "files": ["fonts/acme-sans-bold.woff2"]},
            ],
            "tokens": ["font-sans"],
        },
        {
            "family": "Acme Mono",
            "variants": [
                {"weight": "400", "style": "normal", "files": ["fonts/acme-mono.woff2"]},
            ],
            "tokens": ["font-mono"],
        },
    ]
}


# ---------------------------------------------------------------------------
# Header + color tokens: textual spec + :root CSS vars (unchanged behavior)
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
        assert out.index("--brand-core-") < out.index("--brand-accents-")
        assert out.index("--brand-accents-") < out.index("--brand-ink-")
        assert out.index("--brand-ink-") < out.index("--brand-tints-")

    def test_token_names_sorted_within_group(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS)
        out = compile_design_system(ds)
        assert out.index("--brand-core-background") < out.index("--brand-core-primary")


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
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS)
        out = compile_design_system(ds)
        assert "--brand-type-" not in out
        assert "--brand-spacing-" not in out


class TestTemplates:
    """Templates remain rendered from the manifest (Phase 4 owns selection)."""

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
        assert "SLIDE TEMPLATES" not in out

    def test_malformed_template_entries_skipped(self, session):
        from src.services.design_system_compiler import compile_design_system

        manifest = {"templates": ["not-a-dict", {"description": "no name"}, {"name": "Good"}]}
        ds = _make_ds(session, manifest_json=manifest)
        out = compile_design_system(ds)
        assert "Good" in out
        assert "not-a-dict" not in out


# ---------------------------------------------------------------------------
# BRAND MANUAL: the FULL README + FULL SKILL.md, first, unfiltered/untruncated
# ---------------------------------------------------------------------------


class TestBrandManual:
    def test_manual_injects_full_readme_and_skill(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS)
        out = compile_design_system(ds, skill_md=_SKILL_MD, readme_md=_README_MD)
        assert "BRAND MANUAL" in out
        # FULL README — including the overview/history prose the OLD filter dropped.
        assert "This overview is background" in out
        assert "Founded in a fixture in 2020" in out
        assert "Voice & Tone" in out
        assert "Data Visualization Guidelines" in out
        # FULL SKILL.md.
        assert "Always place the logo top-left" in out
        assert "Never recolor or stretch the logo." in out

    def test_readme_before_skill(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS)
        out = compile_design_system(ds, skill_md=_SKILL_MD, readme_md=_README_MD)
        # README (its markdown H1) precedes SKILL (its frontmatter name).
        assert out.index("# Acme Design System") < out.index("acme-brand")

    def test_manual_first_before_tokens(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS)
        out = compile_design_system(ds, skill_md=_SKILL_MD, readme_md=_README_MD)
        assert out.index("SLIDE VISUAL STYLE") < out.index("BRAND MANUAL")
        assert out.index("BRAND MANUAL") < out.index("BRAND COLOR TOKENS")

    def test_manual_untruncated_for_large_docs(self, session):
        """A very long README is injected in FULL — no cap, no truncation marker."""
        from src.services.design_system_compiler import compile_design_system

        big_readme = "# Big Brand\n\n" + ("brand-para " * 5000)  # ~55K chars
        ds = _make_ds(session)
        out = compile_design_system(ds, skill_md=None, readme_md=big_readme)
        # Every occurrence survives (the manual is stripped, so count the token
        # without its trailing space to be whitespace-robust).
        assert out.count("brand-para") == 5000
        assert "…[truncated]" not in out
        assert "[truncated]" not in out

    def test_only_skill_no_readme(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session)
        out = compile_design_system(ds, skill_md=_SKILL_MD, readme_md=None)
        assert "BRAND MANUAL" in out
        assert "Never recolor or stretch the logo." in out

    def test_only_readme_no_skill(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session)
        out = compile_design_system(ds, skill_md=None, readme_md=_README_MD)
        assert "BRAND MANUAL" in out
        assert "Founded in a fixture in 2020" in out

    def test_no_manual_when_neither_source(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS)
        out = compile_design_system(ds)
        assert "BRAND MANUAL" not in out

    def test_description_then_manual_then_tokens(self, session):
        """FINAL order (option a): a short description caption comes first, THEN the
        full README/SKILL manual (still the first FULL/substantive block), then the
        tokens — mirroring the frontmatter-blurb -> manual skill convention."""
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, description="ACME-DESC-MARKER", tokens=_TOKENS)
        out = compile_design_system(ds, skill_md=_SKILL_MD, readme_md=_README_MD)
        assert out.index("SLIDE VISUAL STYLE") < out.index("ACME-DESC-MARKER")  # header first
        assert out.index("ACME-DESC-MARKER") < out.index("BRAND MANUAL")  # caption before manual
        assert out.index("BRAND MANUAL") < out.index("BRAND COLOR TOKENS")  # manual before tokens


class TestBrandManualWiring:
    """recompute reads SKILL/README from ``design_system_file`` rows and passes
    the text into the pure compiler (whose signature stays text-in)."""

    def test_recompute_injects_manual_from_files(self, session):
        from src.services.design_system_compiler import recompute_compiled_style_content

        ds = _make_ds(
            session,
            tokens=_TOKENS,
            files=[_file("skill", _SKILL_MD), _file("readme", _README_MD)],
        )
        recompute_compiled_style_content(ds)
        assert "BRAND MANUAL" in ds.compiled_style_content
        assert "Never recolor or stretch the logo." in ds.compiled_style_content
        # Full README prose reaches the compiled artifact.
        assert "Founded in a fixture in 2020" in ds.compiled_style_content

    def test_recompute_no_manual_without_source_files(self, session):
        from src.services.design_system_compiler import recompute_compiled_style_content

        ds = _make_ds(session, tokens=_TOKENS)  # no files
        recompute_compiled_style_content(ds)
        assert "BRAND MANUAL" not in ds.compiled_style_content
        assert ds.compiled_style_content.startswith("SLIDE VISUAL STYLE:")

    def test_recompute_ignores_reference_rows(self, session):
        """asset/font REFERENCE rows carry ``data=None`` and are never manual text."""
        from src.services.design_system_compiler import recompute_compiled_style_content

        files = [
            {"path": "assets/logo.svg", "kind": "asset", "mime": "image/svg+xml",
             "data": None, "size_bytes": 6},
        ]
        ds = _make_ds(session, tokens=_TOKENS, files=files)
        recompute_compiled_style_content(ds)
        assert "BRAND MANUAL" not in ds.compiled_style_content


# ---------------------------------------------------------------------------
# Shadow tokens — emitted UNCAPPED
# ---------------------------------------------------------------------------


class TestShadowTokens:
    def test_shadow_root_vars_and_spec(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS + _SHADOW_TOKENS)
        out = compile_design_system(ds)
        assert "BRAND SHADOWS" in out
        assert "--brand-shadow-sm: 0 1px 2px rgba(0,0,0,0.1);" in out
        assert "--brand-shadow-lg: 0 10px 20px rgba(0,0,0,0.2);" in out

    def test_shadow_group_no_longer_warns(self, session, caplog):
        import logging

        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_SHADOW_TOKENS)
        with caplog.at_level(logging.WARNING, logger="src.services.design_system_compiler"):
            compile_design_system(ds)
        assert not [r for r in caplog.records if r.levelno == logging.WARNING]

    def test_shadow_names_sorted(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_SHADOW_TOKENS)
        out = compile_design_system(ds)
        assert out.index("--brand-shadow-lg") < out.index("--brand-shadow-sm")

    def test_shadows_uncapped_large_count(self, session):
        """Every shadow token is emitted regardless of count — no cap, no omission."""
        from src.services.design_system_compiler import compile_design_system

        tokens = [
            {"group": "shadow", "name": f"s{i:03d}", "value": f"0 {i}px {i}px #000000"}
            for i in range(50)
        ]
        ds = _make_ds(session, tokens=tokens)
        out = compile_design_system(ds)
        assert out.count("--brand-shadow-s") == 50
        assert "omitted" not in out


# ---------------------------------------------------------------------------
# Font families — emitted UNCAPPED (families / variants / tokens)
# ---------------------------------------------------------------------------


class TestFontFamilies:
    def test_font_families_rendered(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS, font_mapping_json=_FONT_MAPPING)
        out = compile_design_system(ds)
        assert "BRAND FONT FAMILIES" in out
        assert "Acme Sans" in out
        assert "Acme Mono" in out
        assert "700" in out  # weight variant
        assert "font-sans" in out  # linked token

    def test_font_families_absent_without_mapping(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS, font_mapping_json=None)
        out = compile_design_system(ds)
        assert "BRAND FONT FAMILIES" not in out

    def test_font_families_sorted_by_name(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, font_mapping_json=_FONT_MAPPING)
        out = compile_design_system(ds)
        assert out.index("Acme Mono") < out.index("Acme Sans")

    def test_font_families_uncapped(self, session):
        from src.services.design_system_compiler import compile_design_system

        mapping = {
            "families": [
                {"family": f"Fam{i:03d}", "tokens": [f"tok{i:03d}"],
                 "variants": [{"weight": "400", "style": "normal", "files": []}]}
                for i in range(30)
            ]
        }
        ds = _make_ds(session, font_mapping_json=mapping)
        out = compile_design_system(ds)
        for i in range(30):
            assert f"Fam{i:03d}" in out
            assert f"tok{i:03d}" in out
        assert "omitted" not in out

    def test_font_variants_uncapped(self, session):
        from src.services.design_system_compiler import compile_design_system

        mapping = {
            "families": [{
                "family": "Fam", "tokens": [],
                "variants": [{"weight": str(w), "style": "normal", "files": []}
                             for w in range(100, 1000, 100)],  # 9 variants
            }]
        }
        ds = _make_ds(session, font_mapping_json=mapping)
        out = compile_design_system(ds)
        for w in range(100, 1000, 100):
            assert str(w) in out
        assert "more" not in out.split("BRAND FONT FAMILIES", 1)[1]


# ---------------------------------------------------------------------------
# Brand image assets: CONTRACT (not enumeration); fonts wired inline
# ---------------------------------------------------------------------------


class TestAssetContract:
    def test_contract_present_and_names_tool(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, assets=_IMAGE_ASSETS)
        out = compile_design_system(ds)
        assert "BRAND IMAGE ASSETS" in out
        assert "search_brand_assets" in out
        assert "{{ds-asset:ID}}" in out  # the handle example the tool returns
        assert "Never invent an ID" in out

    def test_image_assets_not_enumerated(self, session):
        """Brand IMAGES are fetched via the tool — NOT listed with their ids."""
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, assets=_IMAGE_ASSETS)
        out = compile_design_system(ds)
        for a in ds.assets:
            assert f"{{{{ds-asset:{a.id}}}}}" not in out  # no per-image id enumeration
        assert "acme-logo.svg" not in out
        assert "hero-bg.png" not in out
        assert "icon.svg" not in out
        # the old enumeration heading is gone
        assert "BRAND ASSETS:" not in out

    def test_contract_present_even_without_image_assets(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS)  # no image assets at all
        out = compile_design_system(ds)
        assert "BRAND IMAGE ASSETS" in out
        assert "search_brand_assets" in out

    def test_fonts_wired_inline_via_ds_asset(self, session):
        """Fonts are the ONE asset kind still referenced inline (via @font-face),
        so they carry a {{ds-asset:ID}}; images do NOT."""
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, assets=_IMAGE_ASSETS + [_FONT_ASSET])
        out = compile_design_system(ds)
        font = next(a for a in ds.assets if a.kind == "font")
        logo = next(a for a in ds.assets if a.kind == "logo")
        assert "BRAND FONTS" in out
        assert f"{{{{ds-asset:{font.id}}}}}" in out       # font wired inline
        assert f"{{{{ds-asset:{logo.id}}}}}" not in out   # image NOT wired inline
        assert "acme.woff2" in out                         # font filename listed

    def test_no_fonts_section_without_font_assets(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, assets=_IMAGE_ASSETS)  # images only, no font
        out = compile_design_system(ds)
        assert "BRAND FONTS:" not in out

    def test_fonts_uncapped(self, session):
        from src.services.design_system_compiler import compile_design_system

        assets = [
            {"kind": "font", "filename": f"f{i:03d}.woff2", "mime": "font/woff2",
             "data": b"x", "size_bytes": 1}
            for i in range(20)
        ]
        ds = _make_ds(session, assets=assets)
        out = compile_design_system(ds)
        for a in ds.assets:
            assert f"{{{{ds-asset:{a.id}}}}}" in out  # all 20 wired, none omitted
        assert "omitted" not in out

    def test_template_shot_not_referenced(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, assets=_IMAGE_ASSETS + [_TEMPLATE_SHOT])
        out = compile_design_system(ds)
        shot = next(a for a in ds.assets if a.kind == "template_shot")
        assert f"{{{{ds-asset:{shot.id}}}}}" not in out
        assert "title-shot.png" not in out

    def test_does_not_collide_with_image_placeholder(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, assets=_IMAGE_ASSETS + [_FONT_ASSET])
        out = compile_design_system(ds)
        assert "{{image:" not in out


# ---------------------------------------------------------------------------
# Section ordering: manual -> tokens -> fonts -> templates -> asset contract
# ---------------------------------------------------------------------------


class TestSectionOrdering:
    def test_full_order(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(
            session,
            tokens=_TOKENS + _SHADOW_TOKENS,
            assets=_IMAGE_ASSETS + [_FONT_ASSET],
            manifest_json=_MANIFEST,
            font_mapping_json=_FONT_MAPPING,
        )
        out = compile_design_system(ds, skill_md=_SKILL_MD, readme_md=_README_MD)
        order = [
            "SLIDE VISUAL STYLE",
            "BRAND MANUAL",
            "BRAND COLOR TOKENS",
            "TYPOGRAPHY TOKENS",
            "SPACING TOKENS",
            "BRAND SHADOWS",
            "BRAND FONTS:",
            "BRAND FONT FAMILIES",
            "SLIDE TEMPLATES",
            "BRAND IMAGE ASSETS",
        ]
        positions = [out.index(marker) for marker in order]
        assert positions == sorted(positions), f"out-of-order: {list(zip(order, positions))}"

    def test_contract_is_last(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS, assets=_IMAGE_ASSETS, manifest_json=_MANIFEST)
        out = compile_design_system(ds, skill_md=_SKILL_MD, readme_md=_README_MD)
        # nothing structural after the contract
        assert out.rstrip().index("BRAND IMAGE ASSETS") > out.index("BRAND COLOR TOKENS")
        assert "BRAND IMAGE ASSETS" in out.split("SLIDE TEMPLATES", 1)[1]


# ---------------------------------------------------------------------------
# Determinism + review fixes carried forward
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_compile_twice_identical(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS, assets=_IMAGE_ASSETS + [_FONT_ASSET],
                      manifest_json=_MANIFEST)
        assert compile_design_system(ds) == compile_design_system(ds)

    def test_output_independent_of_input_order(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS, assets=_IMAGE_ASSETS + [_FONT_ASSET],
                      manifest_json=_MANIFEST)
        out = compile_design_system(ds)
        ds.tokens.reverse()
        ds.assets.reverse()
        out_reversed = compile_design_system(ds)
        assert out == out_reversed

    def test_empty_design_system_has_header_and_contract(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, description=None, tokens=None, assets=None, manifest_json=None)
        out = compile_design_system(ds)
        assert out.startswith("SLIDE VISUAL STYLE:")
        assert "BRAND COLOR TOKENS" not in out
        assert "BRAND FONT" not in out
        assert "SLIDE TEMPLATES" not in out
        # The asset contract is always present (the tool is available for any DS).
        assert "BRAND IMAGE ASSETS" in out


class TestReviewFixesCarriedForward:
    def test_unrecognized_token_group_logs_warning(self, session, caplog):
        import logging

        from src.services.design_system_compiler import compile_design_system

        tokens = [
            {"group": "core", "name": "primary", "value": "#123456"},
            {"group": "elevation", "name": "raise-1", "value": "0 1px 2px"},
            {"group": "motion", "name": "ease", "value": "ease-in-out"},
        ]
        ds = _make_ds(session, tokens=tokens)
        with caplog.at_level(logging.WARNING, logger="src.services.design_system_compiler"):
            out = compile_design_system(ds)

        assert "#123456" in out
        assert "raise-1" not in out
        assert "ease-in-out" not in out
        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("elevation" in m and "motion" in m for m in warnings)

    def test_no_warning_when_all_groups_recognized(self, session, caplog):
        import logging

        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS + _SHADOW_TOKENS)
        with caplog.at_level(logging.WARNING, logger="src.services.design_system_compiler"):
            compile_design_system(ds)
        assert not [r for r in caplog.records if r.levelno == logging.WARNING]

    def test_slug_collision_deduped_in_root_block(self, session):
        from src.services.design_system_compiler import compile_design_system

        tokens = [
            {"group": "core", "name": "Primary", "value": "#111111"},
            {"group": "core", "name": "primary", "value": "#222222"},
            {"group": "core", "name": "primary!", "value": "#333333"},
        ]
        ds = _make_ds(session, tokens=tokens)
        out = compile_design_system(ds)
        assert out.count("--brand-core-primary:") == 1


class TestRecompute:
    def test_recompute_sets_compiled_style_content(self, session):
        from src.services.design_system_compiler import (
            compile_design_system,
            recompute_compiled_style_content,
        )

        ds = _make_ds(session, tokens=_TOKENS, assets=_IMAGE_ASSETS, manifest_json=_MANIFEST)
        assert ds.compiled_style_content is None
        result = recompute_compiled_style_content(ds)
        assert result == compile_design_system(ds)
        assert ds.compiled_style_content == result
        assert "SLIDE VISUAL STYLE:" in ds.compiled_style_content

    def test_recompute_is_idempotent(self, session):
        from src.services.design_system_compiler import recompute_compiled_style_content

        ds = _make_ds(session, tokens=_TOKENS, assets=_IMAGE_ASSETS, manifest_json=_MANIFEST)
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


class TestBackwardCompat:
    def test_legacy_ds_has_no_manual_shadow_or_fonts(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS, assets=_IMAGE_ASSETS, manifest_json=_MANIFEST)
        out = compile_design_system(ds)
        assert "BRAND MANUAL" not in out       # no skill/readme passed
        assert "BRAND SHADOWS" not in out      # no shadow tokens
        assert "BRAND FONT FAMILIES" not in out  # no font mapping
        assert "BRAND FONTS:" not in out       # no font assets
        assert out.startswith("SLIDE VISUAL STYLE:")
        assert "BRAND COLOR TOKENS" in out
        assert "BRAND IMAGE ASSETS" in out     # contract always present

    def test_recompute_no_files_equals_plain_compile(self, session):
        from src.services.design_system_compiler import (
            compile_design_system,
            recompute_compiled_style_content,
        )

        ds = _make_ds(session, tokens=_TOKENS, assets=_IMAGE_ASSETS, manifest_json=_MANIFEST)
        recompute_compiled_style_content(ds)
        assert ds.compiled_style_content == compile_design_system(ds)


class TestFullDeterminism:
    def _full_ds(self, session):
        return _make_ds(
            session,
            tokens=_TOKENS + _SHADOW_TOKENS,
            assets=_IMAGE_ASSETS + [_FONT_ASSET],
            manifest_json=_MANIFEST,
            font_mapping_json=_FONT_MAPPING,
            files=[_file("skill", _SKILL_MD), _file("readme", _README_MD)],
        )

    def test_recompute_twice_identical(self, session):
        from src.services.design_system_compiler import recompute_compiled_style_content

        ds = self._full_ds(session)
        first = recompute_compiled_style_content(ds)
        second = recompute_compiled_style_content(ds)
        assert first == second

    def test_compile_deterministic_under_input_reversal(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = self._full_ds(session)
        out = compile_design_system(ds, skill_md=_SKILL_MD, readme_md=_README_MD)
        ds.tokens.reverse()
        ds.assets.reverse()
        ds.files.reverse()
        out_rev = compile_design_system(ds, skill_md=_SKILL_MD, readme_md=_README_MD)
        assert out == out_rev


# ---------------------------------------------------------------------------
# Phase 3: SLIDE FRAME CONSTRAINTS + soft safe-area (frame guardrails)
# ---------------------------------------------------------------------------


class TestSlideFrameConstraints:
    """A DS deck bypasses ``DEFAULT_SLIDE_STYLE`` (the only place the slide frame +
    content limits used to live), so the compiler must re-assert frame awareness.

    The block is emitted into ``compiled_style_content`` itself (NOT prompt_modules)
    so the legacy custom-system-prompt path and the no-DS golden prompts stay
    byte-identical. It is ALWAYS present when a design system compiles (like the
    asset contract). It states a fixed 1280x720 (16:9) frame with overflow clipped,
    one slide per frame with no in-slide scrolling, and adds SOFT safe-area prose.
    The WHOLE block is PROSE ONLY: the model writes freehand HTML, so the block
    must state outcomes without prescribing CSS rules or assuming any wrapper
    class (``.slide``), and without injected padding CSS. All fixtures SYNTHETIC.
    """

    def test_frame_block_present_with_hard_frame_facts(self, session):
        from src.services.design_system_compiler import compile_design_system

        out = compile_design_system(_make_ds(session, tokens=_TOKENS))
        assert "SLIDE FRAME CONSTRAINTS" in out
        assert "1280x720" in out
        assert "16:9" in out
        # clip-not-scroll is stated as prose (no CSS rule — see the prose-only test)
        assert "CLIPPED" in out
        assert "never scrolled" in out

    def test_frame_block_states_one_slide_per_frame_fit_all(self, session):
        from src.services.design_system_compiler import compile_design_system

        out = compile_design_system(_make_ds(session, tokens=_TOKENS)).lower()
        assert "one slide per frame" in out
        assert "fit all" in out
        # per-slide, so it does not contradict the deck's vertically-stacked page
        assert "no in-slide scrolling" in out

    def test_frame_block_has_soft_safe_area_guidance(self, session):
        from src.services.design_system_compiler import compile_design_system

        out = compile_design_system(_make_ds(session, tokens=_TOKENS))
        assert "72px" in out and "88px" in out
        assert "safe area" in out.lower()
        assert "full-bleed" in out.lower()

    def test_safe_area_is_soft_prose_not_injected_css(self, session):
        """Deliverable #2 is SOFT prose ONLY — the compiler must NOT force-inject a
        padding rule or a .slide wrapper (that would break full-bleed backgrounds)."""
        from src.services.design_system_compiler import compile_design_system

        out = compile_design_system(_make_ds(session, tokens=_TOKENS))
        squished = out.replace(" ", "")
        assert "padding:72px88px" not in squished  # no forced safe-area padding CSS
        assert "padding:72px" not in squished

    def test_frame_block_is_pure_prose_no_css_prescriptions(self, session):
        """The frame block is a PROSE contract: the model writes freehand HTML, so
        the block must not prescribe concrete CSS rules (e.g. ``{ width:1280px``)
        or assume any particular wrapper class (``.slide``) — it states the
        outcome and leaves the markup to the model."""
        from src.services.design_system_compiler import compile_design_system

        out = compile_design_system(_make_ds(session, tokens=_TOKENS))
        block = out[out.index("SLIDE FRAME CONSTRAINTS"):out.index("BRAND IMAGE ASSETS")]
        assert ".slide" not in block  # no wrapper-class assumption
        assert "{" not in block and "}" not in block  # no CSS rule prescriptions
        squished = block.replace(" ", "").lower()
        for css_property_form in ("width:", "height:", "overflow:", "padding:"):
            assert css_property_form not in squished
        # the class-name independence is stated explicitly, not just implied
        assert "class name" in block

    def test_frame_block_always_present_even_for_empty_ds(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, description=None, tokens=None, assets=None, manifest_json=None)
        out = compile_design_system(ds)
        assert "SLIDE FRAME CONSTRAINTS" in out  # always on, like the asset contract

    def test_frame_block_after_templates_before_asset_contract(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS, assets=_IMAGE_ASSETS, manifest_json=_MANIFEST)
        out = compile_design_system(ds, skill_md=_SKILL_MD, readme_md=_README_MD)
        assert out.index("SLIDE TEMPLATES") < out.index("SLIDE FRAME CONSTRAINTS")
        assert out.index("SLIDE FRAME CONSTRAINTS") < out.index("BRAND IMAGE ASSETS")

    def test_asset_contract_remains_last(self, session):
        """Frame block must not displace the asset contract from its last position."""
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS, assets=_IMAGE_ASSETS, manifest_json=_MANIFEST)
        out = compile_design_system(ds, skill_md=_SKILL_MD, readme_md=_README_MD)
        assert out.index("BRAND IMAGE ASSETS") > out.index("SLIDE FRAME CONSTRAINTS")

    def test_frame_block_is_deterministic_static_text(self, session):
        from src.services.design_system_compiler import compile_design_system

        a = compile_design_system(_make_ds(session, tokens=_TOKENS))
        b = compile_design_system(_make_ds(session, tokens=_TOKENS, name="Other Brand"))
        frame_a = a[a.index("SLIDE FRAME CONSTRAINTS"):]
        frame_b = b[b.index("SLIDE FRAME CONSTRAINTS"):]
        # the frame block carries no per-DS data, so it is identical across systems
        # (compare from the frame heading to the shared trailing asset contract)
        assert frame_a == frame_b


# ---------------------------------------------------------------------------
# Compiled-artifact version marker (staleness detection for persisted rows)
# ---------------------------------------------------------------------------


class TestCompilerVersionMarker:
    """The compiler stamps a version marker into the header line so consumers of
    the PERSISTED ``compiled_style_content`` (``agent_factory``) can detect rows
    compiled by an OLDER compiler (e.g. before the frame guardrails existed) and
    lazily recompute them via ``recompute_compiled_style_content``."""

    def test_compiled_output_carries_marker_in_header_line(self, session):
        from src.services.design_system_compiler import (
            _COMPILER_VERSION_MARKER,
            compile_design_system,
        )

        out = compile_design_system(_make_ds(session, tokens=_TOKENS))
        header = out.splitlines()[0]
        assert header.startswith("SLIDE VISUAL STYLE: Acme Design System")
        assert _COMPILER_VERSION_MARKER in header

    def test_fresh_compile_and_recompute_are_current(self, session):
        from src.services.design_system_compiler import (
            compile_design_system,
            compiled_style_content_is_current,
            recompute_compiled_style_content,
        )

        ds = _make_ds(session, tokens=_TOKENS)
        assert compiled_style_content_is_current(compile_design_system(ds))
        recompute_compiled_style_content(ds)
        assert compiled_style_content_is_current(ds.compiled_style_content)

    def test_missing_empty_and_pre_marker_artifacts_are_stale(self):
        from src.services.design_system_compiler import compiled_style_content_is_current

        assert not compiled_style_content_is_current(None)
        assert not compiled_style_content_is_current("")
        assert not compiled_style_content_is_current("   \n")
        # A row compiled before version markers existed (the pre-guardrail
        # Phase 2/3 artifact shape) carries no marker and must read as stale.
        assert not compiled_style_content_is_current(
            "SLIDE VISUAL STYLE: Acme Design System\n\n"
            "BRAND COLOR TOKENS:\n- core:\n  - primary: #123456"
        )


class TestEnsureCompiledStyleContentCurrent:
    """Read-through seam for consumers of the PERSISTED artifact: returns the
    stored text when it is current, recomputes it in place when stale/missing."""

    def test_returns_stored_artifact_verbatim_when_current(self, session):
        from src.services.design_system_compiler import (
            ensure_compiled_style_content_current,
            recompute_compiled_style_content,
        )

        ds = _make_ds(session, tokens=_TOKENS)
        recompute_compiled_style_content(ds)
        stored = ds.compiled_style_content
        assert ensure_compiled_style_content_current(ds) == stored

    def test_recomputes_and_refreshes_record_when_stale(self, session):
        from src.services.design_system_compiler import (
            compiled_style_content_is_current,
            ensure_compiled_style_content_current,
        )

        ds = _make_ds(session, tokens=_TOKENS)
        ds.compiled_style_content = "SLIDE VISUAL STYLE: Acme Design System\n\n(old artifact)"
        out = ensure_compiled_style_content_current(ds)
        assert "SLIDE FRAME CONSTRAINTS" in out
        assert ds.compiled_style_content == out  # refreshed in place for persistence
        assert compiled_style_content_is_current(ds.compiled_style_content)
