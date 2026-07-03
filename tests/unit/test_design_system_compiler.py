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
    files=None,
    font_mapping_json=None,
):
    """Persist a synthetic DesignSystem (+ tokens/assets/files) and return it.

    Persisting is what assigns primary keys, so brand-asset references can point
    at real asset IDs. ``tokens``/``assets``/``files`` are lists of plain dicts;
    ``font_mapping_json`` is the normalized family mapping (Phase 1 column).
    """
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


class TestPhase3ReviewFixes:
    """Phase-2 review follow-ups folded in during Phase 3."""

    def test_unrecognized_token_group_logs_warning(self, session, caplog):
        """Tokens in a group the compiler doesn't emit are dropped — but no longer
        silently: a warning names the dropped groups so authors notice."""
        import logging

        from src.services.design_system_compiler import compile_design_system

        tokens = [
            {"group": "core", "name": "primary", "value": "#123456"},
            {"group": "elevation", "name": "shadow-1", "value": "0 1px 2px"},
            {"group": "motion", "name": "ease", "value": "ease-in-out"},
        ]
        ds = _make_ds(session, tokens=tokens)
        with caplog.at_level(logging.WARNING, logger="src.services.design_system_compiler"):
            out = compile_design_system(ds)

        # Recognized group still renders; unrecognized ones are absent from output.
        assert "#123456" in out
        assert "shadow-1" not in out
        assert "ease-in-out" not in out
        # ...but a single warning names the dropped groups (sorted, deterministic).
        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("elevation" in m and "motion" in m for m in warnings)

    def test_no_warning_when_all_groups_recognized(self, session, caplog):
        import logging

        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS)  # only core/accents/ink/tints/type/spacing
        with caplog.at_level(logging.WARNING, logger="src.services.design_system_compiler"):
            compile_design_system(ds)
        assert not [r for r in caplog.records if r.levelno == logging.WARNING]

    def test_slug_collision_deduped_in_root_block(self, session):
        """Two color-token names that slugify to the same identifier must not emit
        duplicate --brand-* custom properties (invalid/ambiguous CSS)."""
        from src.services.design_system_compiler import compile_design_system

        # "Primary" and "primary" (and "primary!") all slugify to 'primary'.
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


# ===========================================================================
# Phase 2 (v1): "Rules into generation" — BRAND RULES block (SKILL + README
# rule-sections) with a hard prompt-budget cap + truncation, shadow-token
# emission, font-mapping-driven typography, and asset curation/ranking.
#
# All fixtures remain SYNTHETIC (fake "Acme", dummy hex/paths/bytes) — no real
# brand content, per the public-repo hygiene rule.
# ===========================================================================


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


# SKILL.md is the concise, authoritative rules doc — injected in FULL.
_SKILL_MD = (
    "---\nname: acme-brand\n---\n\n"
    "# Acme brand skill\n"
    "- Always place the logo top-left with clear space.\n"
    "- Never recolor or stretch the logo.\n"
    "- Prefer the accent color for a single emphasis per slide.\n"
)

# README.md is long prose; ONLY its rule/guidance sections should be injected.
_README_MD = (
    "# Acme Design System\n\n"
    "## Overview\n"
    "Acme is a synthetic brand used only in tests. This overview is background "
    "prose and must NOT be injected into the prompt.\n\n"
    "## Voice & Tone\n"
    "Friendly, concise, confident. Avoid jargon.\n\n"
    "## Do's and Don'ts\n"
    "- Do use the brand color palette.\n"
    "- Don't place text over busy backgrounds.\n\n"
    "## Data Visualization Guidelines\n"
    "Use the accent palette for the primary series; keep gridlines subtle.\n\n"
    "## Company History\n"
    "Founded in a fixture in 2020. This is narrative, not a rule, and must be "
    "excluded from the compiled rules.\n"
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

_SHADOW_TOKENS = [
    {"group": "shadow", "name": "sm", "value": "0 1px 2px rgba(0,0,0,0.1)"},
    {"group": "shadow", "name": "lg", "value": "0 10px 20px rgba(0,0,0,0.2)"},
]

# Deliberately unsorted, mixed-kind image assets (+ a template_shot to exclude).
_CURATION_ASSETS = [
    {"kind": "icon", "filename": "icon-b.svg", "mime": "image/svg+xml",
     "data": b"<svg/>", "size_bytes": 6},
    {"kind": "logo", "filename": "logo-b.svg", "mime": "image/svg+xml",
     "data": b"<svg/>", "size_bytes": 6},
    {"kind": "icon", "filename": "icon-a.svg", "mime": "image/svg+xml",
     "data": b"<svg/>", "size_bytes": 6},
    {"kind": "logo", "filename": "logo-a.svg", "mime": "image/svg+xml",
     "data": b"<svg/>", "size_bytes": 6},
    {"kind": "illustration", "filename": "art.png", "mime": "image/png",
     "data": b"png", "size_bytes": 3},
    {"kind": "template_shot", "filename": "shot.png", "mime": "image/png",
     "data": b"png", "size_bytes": 3},
]


class TestBrandRules:
    """Item 1/2: a BRAND RULES / USAGE block from SKILL (full) + README rules."""

    def test_brand_rules_block_from_skill_and_readme(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS)
        out = compile_design_system(ds, skill_md=_SKILL_MD, readme_md=_README_MD)
        assert "BRAND RULES" in out
        # SKILL.md injected in full.
        assert "Always place the logo top-left" in out
        assert "Never recolor or stretch the logo." in out
        # README rule/guidance sections injected.
        assert "Voice & Tone" in out
        assert "Friendly, concise, confident." in out
        assert "Do's and Don'ts" in out
        assert "Don't place text over busy backgrounds." in out
        assert "Data Visualization Guidelines" in out
        assert "accent palette for the primary series" in out

    def test_readme_non_rule_prose_excluded(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS)
        out = compile_design_system(ds, skill_md=_SKILL_MD, readme_md=_README_MD)
        assert "This overview is background" not in out
        assert "Founded in a fixture" not in out

    def test_brand_rules_near_top_after_header(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS)
        out = compile_design_system(ds, skill_md=_SKILL_MD, readme_md=_README_MD)
        # After the visual-style header, before the color tokens.
        assert out.index("SLIDE VISUAL STYLE") < out.index("BRAND RULES")
        assert out.index("BRAND RULES") < out.index("BRAND COLOR TOKENS")

    def test_budget_cap_prioritizes_skill_and_truncates_readme(self, session, monkeypatch):
        import src.services.design_system_compiler as compiler

        monkeypatch.setattr(compiler, "MAX_BRAND_RULES_CHARS", 160)
        skill = "SKILL-HEAD keep me."
        readme = "## Rules\n" + ("acme-rule " * 400)  # far over the cap
        ds = _make_ds(session)
        out = compiler.compile_design_system(ds, skill_md=skill, readme_md=readme)
        assert "…[truncated]" in out
        # SKILL sits first, so its text survives while the README tail is dropped.
        assert "SKILL-HEAD keep me." in out
        assert out.count("acme-rule ") < 400

    def test_brand_rules_block_is_hard_capped(self, monkeypatch):
        """The FULL emitted block (heading + body + marker) never exceeds the cap —
        including caps smaller than the heading itself."""
        import src.services.design_system_compiler as compiler

        skill = "SK " * 60
        readme = "## Rules\n" + ("acme-rule " * 400)
        for cap in (30, 64, 200, 1000):
            monkeypatch.setattr(compiler, "MAX_BRAND_RULES_CHARS", cap)
            block = compiler._brand_rules_section(skill, readme)
            assert block is not None
            assert len(block) <= cap, f"block len {len(block)} exceeds cap {cap}"

    def test_compiled_brand_rules_block_within_cap(self, session, monkeypatch):
        """Same bound, verified end-to-end by extracting the block from compile output."""
        import src.services.design_system_compiler as compiler

        ds = _make_ds(session, description=None)  # no other sections follow the block
        skill = _SKILL_MD
        readme = _README_MD + "\n\n## Rules\n" + ("acme-rule " * 400)
        for cap in (160, 500):
            monkeypatch.setattr(compiler, "MAX_BRAND_RULES_CHARS", cap)
            out = compiler.compile_design_system(ds, skill_md=skill, readme_md=readme)
            block = out[out.index(compiler._BRAND_RULES_HEADING):]
            assert len(block) <= cap, f"block len {len(block)} exceeds cap {cap}"
            assert "…[truncated]" in block

    def test_brand_rules_block_bounded_for_tiny_caps(self, monkeypatch):
        """The hard cap holds for EVERY non-negative cap, including 0..12 where the
        13-char truncation marker itself must be truncated (or the block omitted)."""
        import src.services.design_system_compiler as compiler

        skill = "SK " * 60
        readme = "## Rules\n" + ("acme-rule " * 400)
        for cap in (0, 1, 5, 12, 13, 30):
            monkeypatch.setattr(compiler, "MAX_BRAND_RULES_CHARS", cap)
            block = compiler._brand_rules_section(skill, readme)
            assert block is None or len(block) <= cap, (
                f"cap {cap}: block len {None if block is None else len(block)}"
            )

    def test_only_skill_no_readme(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session)
        out = compile_design_system(ds, skill_md=_SKILL_MD, readme_md=None)
        assert "BRAND RULES" in out
        assert "Never recolor or stretch the logo." in out

    def test_readme_without_rule_sections_yields_no_block(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS)
        readme = "# Acme\n\n## Overview\nJust prose, no rule headings here.\n"
        out = compile_design_system(ds, skill_md=None, readme_md=readme)
        assert "BRAND RULES" not in out

    def test_nested_non_rule_subsection_excluded(self, session):
        """A non-rule subsection nested under a rule heading is dropped, while a
        nested RULE subsection is kept — extraction scopes to each heading's own
        direct content, not everything below a matched heading."""
        from src.services.design_system_compiler import compile_design_system

        readme = (
            "# Acme\n\n"
            "## Usage\n"
            "Use brand assets responsibly.\n\n"
            "### History\n"
            "Founded in a fixture in 2020 — narrative, not a rule.\n\n"
            "### Logo Rules\n"
            "Keep clear space around the logo.\n"
        )
        ds = _make_ds(session)
        out = compile_design_system(ds, skill_md=None, readme_md=readme)
        assert "Use brand assets responsibly." in out      # rule heading direct prose
        assert "Keep clear space around the logo." in out   # nested RULE subsection kept
        assert "Founded in a fixture in 2020" not in out     # nested NON-rule dropped


class TestBrandRulesWiring:
    """recompute reads SKILL/README from ``design_system_file`` rows and passes
    the text into the pure compiler (whose signature stays text-in)."""

    def test_recompute_injects_rules_from_files(self, session):
        from src.services.design_system_compiler import recompute_compiled_style_content

        ds = _make_ds(
            session,
            tokens=_TOKENS,
            files=[_file("skill", _SKILL_MD), _file("readme", _README_MD)],
        )
        recompute_compiled_style_content(ds)
        assert "BRAND RULES" in ds.compiled_style_content
        assert "Never recolor or stretch the logo." in ds.compiled_style_content
        assert "Voice & Tone" in ds.compiled_style_content

    def test_recompute_no_rules_without_source_files(self, session):
        from src.services.design_system_compiler import recompute_compiled_style_content

        ds = _make_ds(session, tokens=_TOKENS)  # no files
        recompute_compiled_style_content(ds)
        assert "BRAND RULES" not in ds.compiled_style_content
        assert ds.compiled_style_content.startswith("SLIDE VISUAL STYLE:")

    def test_recompute_ignores_reference_rows(self, session):
        """asset/font REFERENCE rows carry ``data=None`` and are never rules."""
        from src.services.design_system_compiler import recompute_compiled_style_content

        files = [
            {"path": "assets/logo.svg", "kind": "asset", "mime": "image/svg+xml",
             "data": None, "size_bytes": 6},
        ]
        ds = _make_ds(session, tokens=_TOKENS, files=files)
        recompute_compiled_style_content(ds)
        assert "BRAND RULES" not in ds.compiled_style_content


class TestShadowTokens:
    """Item 3: shadow tokens are emitted (no longer warn-and-dropped)."""

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

    def test_shadow_section_capped_with_disclosure(self, session, monkeypatch):
        """A pathological manifest with many shadow tokens is bounded per section."""
        import src.services.design_system_compiler as compiler

        monkeypatch.setattr(compiler, "MAX_SHADOW_TOKENS", 2)
        tokens = [
            {"group": "shadow", "name": f"s{i}", "value": f"0 {i}px {i}px #000000"}
            for i in range(5)
        ]
        ds = _make_ds(session, tokens=tokens)
        out = compiler.compile_design_system(ds)
        assert "--brand-shadow-s0:" in out
        assert "--brand-shadow-s1:" in out
        assert "--brand-shadow-s4:" not in out  # beyond the cap
        assert "shadow token(s) omitted" in out


class TestFontMapping:
    """Item 4: font_mapping_json drives a richer TYPOGRAPHY family listing."""

    def test_font_families_rendered_in_typography(self, session):
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

    def test_font_families_capped_with_disclosure(self, session, monkeypatch):
        """A pathological manifest with many families is bounded per section."""
        import src.services.design_system_compiler as compiler

        monkeypatch.setattr(compiler, "MAX_FONT_FAMILIES", 2)
        mapping = {
            "families": [
                {"family": f"Fam{i}", "tokens": [],
                 "variants": [{"weight": "400", "style": "normal", "files": []}]}
                for i in range(5)
            ]
        }
        ds = _make_ds(session, font_mapping_json=mapping)
        out = compiler.compile_design_system(ds)
        assert "- Fam0" in out and "- Fam1" in out
        assert "- Fam4" not in out  # beyond the cap
        assert "font families omitted" in out

    def test_font_variants_capped_per_family(self, session, monkeypatch):
        """Variants per family are bounded too (one family can't blow up a line)."""
        import src.services.design_system_compiler as compiler

        monkeypatch.setattr(compiler, "MAX_FONT_VARIANTS_PER_FAMILY", 2)
        mapping = {
            "families": [{
                "family": "Fam", "tokens": [],
                "variants": [{"weight": str(w), "style": "normal", "files": []}
                             for w in (100, 200, 300, 400, 500)],
            }]
        }
        ds = _make_ds(session, font_mapping_json=mapping)
        out = compiler.compile_design_system(ds)
        assert "+3 more" in out  # 5 variants, cap 2 -> 3 omitted

    def test_font_tokens_capped_per_family(self, session, monkeypatch):
        """A family linked to many tokens is bounded per section (disclosed)."""
        import src.services.design_system_compiler as compiler

        monkeypatch.setattr(compiler, "MAX_FONT_TOKENS_PER_FAMILY", 2)
        mapping = {
            "families": [{
                "family": "Fam",
                "variants": [{"weight": "400", "style": "normal", "files": []}],
                "tokens": [f"tok{i}" for i in range(5)],
            }]
        }
        ds = _make_ds(session, font_mapping_json=mapping)
        out = compiler.compile_design_system(ds)
        assert "tok0" in out and "tok1" in out
        assert "tok4" not in out  # beyond the cap
        assert "+3 more" in out   # 5 tokens, cap 2 -> 3 omitted


class TestAssetCuration:
    """Item 5: rank (Logo > product shot > UI > …) and cap the asset references."""

    def test_ranked_logo_before_imagery_before_icon(self, session):
        """Real importer kinds: logo > illustration/background imagery > icon (UI).
        ``design_system_service._infer_asset_kind`` never emits a 'product'/'ui'
        kind, so illustration is the closest real imagery kind here; the spec's own
        product/ui vocabulary is exercised in the tests below."""
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, assets=_CURATION_ASSETS)
        out = compile_design_system(ds)
        assert out.index("logo-a.svg") < out.index("art.png")  # logo > imagery
        assert out.index("art.png") < out.index("icon-a.svg")  # imagery > UI icon

    def test_spec_vocabulary_kinds_ranked_logo_product_ui_icon(self, session):
        """Forward-compat: the spec §4 Core Asset Protocol vocabulary
        (Logo > product shot > UI > icon) ranks correctly for those kind strings,
        even though the v1 importer doesn't emit them (``kind`` is a free string)."""
        from src.services.design_system_compiler import compile_design_system

        assets = [
            {"kind": "icon", "filename": "i.svg", "mime": "image/svg+xml",
             "data": b"<svg/>", "size_bytes": 6},
            {"kind": "ui", "filename": "u.png", "mime": "image/png",
             "data": b"png", "size_bytes": 3},
            {"kind": "product", "filename": "p.png", "mime": "image/png",
             "data": b"png", "size_bytes": 3},
            {"kind": "logo", "filename": "l.svg", "mime": "image/svg+xml",
             "data": b"<svg/>", "size_bytes": 6},
        ]
        ds = _make_ds(session, assets=assets)
        out = compile_design_system(ds)
        assert out.index("l.svg") < out.index("p.png")  # logo > product shot
        assert out.index("p.png") < out.index("u.png")  # product shot > UI
        assert out.index("u.png") < out.index("i.svg")  # UI > icon

    def test_lower_ranked_kinds_not_starved_by_logos(self, session):
        """The reported defect: with a flat image cap, many logos crowded out every
        other kind. Per-kind caps guarantee non-logo kinds still appear."""
        from src.services.design_system_compiler import compile_design_system

        assets = [
            {"kind": "logo", "filename": f"logo-{i:02d}.svg", "mime": "image/svg+xml",
             "data": b"<svg/>", "size_bytes": 6}
            for i in range(30)
        ] + [
            {"kind": "icon", "filename": "icon-x.svg", "mime": "image/svg+xml",
             "data": b"<svg/>", "size_bytes": 6},
            {"kind": "illustration", "filename": "art-x.png", "mime": "image/png",
             "data": b"png", "size_bytes": 3},
            {"kind": "background", "filename": "bg-x.png", "mime": "image/png",
             "data": b"png", "size_bytes": 3},
        ]
        ds = _make_ds(session, assets=assets)
        out = compile_design_system(ds)
        # Non-logo kinds are represented despite 30 logos.
        assert "[icon]" in out and "icon-x.svg" in out
        assert "[illustration]" in out and "art-x.png" in out
        assert "[background]" in out and "bg-x.png" in out

    def test_per_kind_cap_bounds_and_discloses(self, session, monkeypatch):
        """Each kind is bounded by ITS OWN cap; exceeding it discloses the omission
        without affecting other kinds."""
        import src.services.design_system_compiler as compiler

        monkeypatch.setitem(compiler._IMAGE_KIND_CAPS, "icon", 2)
        assets = [
            {"kind": "icon", "filename": f"i{i}.svg", "mime": "image/svg+xml",
             "data": b"<svg/>", "size_bytes": 6}
            for i in range(5)
        ] + [
            {"kind": "logo", "filename": "l.svg", "mime": "image/svg+xml",
             "data": b"<svg/>", "size_bytes": 6},
        ]
        ds = _make_ds(session, assets=assets)
        out = compiler.compile_design_system(ds)
        assert out.count("[icon]") == 2       # bounded by icon's own cap
        assert "+3 more icon" in out          # 5 icons, cap 2 -> 3 disclosed
        assert "[logo]" in out                # a different kind is unaffected

    def test_every_present_kind_represented_and_bounded(self, session):
        """Many assets across ALL kinds: every present kind appears, each bounded by
        its per-kind cap, per-kind omission disclosed, and the total equals the sum
        of the per-kind caps (every kind here exceeds its cap)."""
        import src.services.design_system_compiler as compiler
        from src.services.design_system_compiler import compile_design_system

        counts = {"logo": 20, "lockup": 200, "icon": 90, "illustration": 40, "background": 10}
        assets: list[dict] = []
        for kind, n in counts.items():
            mime = "image/svg+xml" if kind in ("logo", "lockup", "icon") else "image/png"
            assets += [
                {"kind": kind, "filename": f"{kind}-{i:03d}.x", "mime": mime,
                 "data": b"x", "size_bytes": 1}
                for i in range(n)
            ]
        assets += [
            {"kind": "font", "filename": f"font-{i}.woff2", "mime": "font/woff2",
             "data": b"x", "size_bytes": 1}
            for i in range(10)
        ]
        ds = _make_ds(session, assets=assets)
        out = compile_design_system(ds)

        caps = compiler._IMAGE_KIND_CAPS
        # (1) every present kind is represented (including the non-logo kinds).
        for kind in counts:
            assert f"[{kind}]" in out, f"{kind} missing from listing"
        assert "[font]" in out
        # (2) each kind bounded by its cap; (3) per-kind omission disclosed.
        for kind, n in counts.items():
            assert out.count(f"[{kind}]") == min(n, caps[kind])
            assert f"more {kind} omitted" in out  # every kind here exceeds its cap
        assert out.count("[font]") == min(10, compiler.MAX_FONT_ASSET_REFERENCES)
        # (4) total entry count == sum of the per-kind caps.
        total_refs = out.count(" -> {{ds-asset:")
        expected = sum(caps[k] for k in counts) + compiler.MAX_FONT_ASSET_REFERENCES
        assert total_refs == expected

    def test_ds_asset_placeholder_kept(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, assets=_CURATION_ASSETS)
        out = compile_design_system(ds)
        logo = next(a for a in ds.assets if a.filename == "logo-a.svg")
        assert f"{{{{ds-asset:{logo.id}}}}}" in out


class TestBackwardCompatPhase2:
    """Item 6: a DS with no SKILL/README/font-mapping/shadow compiles as before."""

    def test_legacy_ds_has_no_phase2_sections(self, session):
        from src.services.design_system_compiler import compile_design_system

        ds = _make_ds(session, tokens=_TOKENS, assets=_ASSETS, manifest_json=_MANIFEST)
        out = compile_design_system(ds)
        assert "BRAND RULES" not in out
        assert "BRAND SHADOWS" not in out
        assert "BRAND FONT FAMILIES" not in out
        # Still a valid style block.
        assert out.startswith("SLIDE VISUAL STYLE:")
        assert "BRAND COLOR TOKENS" in out

    def test_recompute_no_files_equals_plain_compile(self, session):
        from src.services.design_system_compiler import (
            compile_design_system,
            recompute_compiled_style_content,
        )

        ds = _make_ds(session, tokens=_TOKENS, assets=_ASSETS, manifest_json=_MANIFEST)
        recompute_compiled_style_content(ds)
        assert ds.compiled_style_content == compile_design_system(ds)


class TestPhase2Determinism:
    def _full_ds(self, session):
        return _make_ds(
            session,
            tokens=_TOKENS + _SHADOW_TOKENS,
            assets=_CURATION_ASSETS,
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
