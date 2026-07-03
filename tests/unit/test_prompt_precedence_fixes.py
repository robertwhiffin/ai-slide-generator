"""Tests for the 4 prompt-precedence fixes layered on the Phase-2 reset.

The fixes close conflicts where generic prompt blocks could override the user's
selected design system. HARD RULE: the no-DS / legacy slide-style / default
generation prompt stays BYTE-IDENTICAL — every fix is gated on a design system
actually being selected (``design_system_active``). All fixtures are SYNTHETIC.

Fixes:
1. Generic 'modern' aesthetic must not be authoritative over a selected DS.
2. A precedence statement must emit for EVERY selected DS (incl. token-only).
3. Generation gets a defer-to-DS line mirroring editing mode.
4. The image block must not discourage proactive brand-asset placement.
"""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register models with Base.metadata
from src.core.database import Base

_GOLDEN = json.loads(
    (Path(__file__).parent / "data" / "generation_prompt_golden.json").read_text()
)

_PRECEDENCE_MARKER = "DESIGN SYSTEM PRECEDENCE"


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


def _token_only_ds(session):
    """A design system with tokens but NO README/SKILL files (token-only) → its
    compiled content has no BRAND MANUAL block."""
    from src.database.models.design_system import DesignSystem, DesignSystemToken
    from src.services.design_system_compiler import recompute_compiled_style_content

    ds = DesignSystem(name="Token Only DS")
    ds.tokens.append(DesignSystemToken(group="core", name="primary", value="#123456"))
    session.add(ds)
    session.flush()
    recompute_compiled_style_content(ds)
    session.commit()
    session.refresh(ds)
    return ds


def _readme_ds(session):
    from src.database.models.design_system import DesignSystem, DesignSystemFile, DesignSystemToken
    from src.services.design_system_compiler import recompute_compiled_style_content

    ds = DesignSystem(name="Readme DS")
    ds.tokens.append(DesignSystemToken(group="core", name="primary", value="#123456"))
    ds.files.append(DesignSystemFile(
        path="README.md", kind="readme", mime="text/markdown",
        data=b"# Brand\n\nManual prose.\n", size_bytes=24))
    session.add(ds)
    session.flush()
    recompute_compiled_style_content(ds)
    session.commit()
    session.refresh(ds)
    return ds


def _dispatching_db(*, design_system=None, slide_style=None):
    from src.database.models import DesignSystem, SlideDeckPromptLibrary, SlideStyleLibrary

    mapping = {
        DesignSystem: design_system,
        SlideStyleLibrary: slide_style,
        SlideDeckPromptLibrary: None,
    }
    db = MagicMock()

    def _query(model):
        q = MagicMock()
        q.filter_by.return_value.first.return_value = mapping.get(model)
        return q

    db.query.side_effect = _query
    return db


def _prompts_with_db(config, db, mode="generate"):
    from src.services.agent_factory import _get_prompt_content

    with patch("src.core.database.get_db_session") as mock_get_db:
        mock_get_db.return_value.__enter__ = MagicMock(return_value=db)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
        return _get_prompt_content(config, mode=mode)


# ---------------------------------------------------------------------------
# (a) HARD RULE — no-DS / legacy / default byte-identical to pre-fix (8245925)
# ---------------------------------------------------------------------------


class TestByteIdenticalNoDS:
    def test_generation_default_and_legacy_byte_identical(self):
        from src.core.defaults import DEFAULT_SLIDE_STYLE
        from src.core.prompt_modules import build_generation_system_prompt

        assert build_generation_system_prompt(
            slide_style=DEFAULT_SLIDE_STYLE
        ) == _GOLDEN["gen_default"]
        assert build_generation_system_prompt(
            slide_style=DEFAULT_SLIDE_STYLE, deck_prompt="Quarterly review deck"
        ) == _GOLDEN["gen_default_deck"]
        assert build_generation_system_prompt(
            slide_style="LEGACY-STYLE-MARKER", deck_prompt=None, image_guidelines="Use logo.png"
        ) == _GOLDEN["gen_legacy_img"]
        assert build_generation_system_prompt(
            slide_style="LEGACY-STYLE-MARKER"
        ) == _GOLDEN["gen_legacy_plain"]

    def test_editing_byte_identical(self):
        from src.core.defaults import DEFAULT_SLIDE_STYLE
        from src.core.prompt_modules import build_editing_system_prompt

        assert build_editing_system_prompt(
            slide_style=DEFAULT_SLIDE_STYLE
        ) == _GOLDEN["edit_default"]
        assert build_editing_system_prompt(
            slide_style="LEGACY-STYLE-MARKER", image_guidelines="Use logo.png"
        ) == _GOLDEN["edit_legacy_img"]

    def test_no_ds_prompt_has_no_ds_only_blocks(self):
        from src.core.defaults import DEFAULT_SLIDE_STYLE
        from src.core.prompt_modules import build_generation_system_prompt

        out = build_generation_system_prompt(slide_style=DEFAULT_SLIDE_STYLE)
        assert _PRECEDENCE_MARKER not in out
        assert "search_brand_assets" not in out

    def test_get_prompt_content_no_ds_byte_identical(self):
        from src.api.schemas.agent_config import AgentConfig
        from src.services.agent_factory import _get_prompt_content

        result = _get_prompt_content(AgentConfig())  # no DS, no legacy style → default
        assert result["system_prompt"] == _GOLDEN["gen_default"]

    def test_get_prompt_content_legacy_style_byte_identical(self):
        from src.api.schemas.agent_config import AgentConfig
        from src.core.prompt_modules import build_generation_system_prompt

        style = MagicMock()
        style.style_content = "LEGACY-STYLE-MARKER"
        style.image_guidelines = "Use logo.png"
        result = _prompts_with_db(
            AgentConfig(slide_style_id=42), _dispatching_db(slide_style=style)
        )
        expected = build_generation_system_prompt(
            slide_style="LEGACY-STYLE-MARKER", deck_prompt=None, image_guidelines="Use logo.png"
        )
        assert result["system_prompt"] == expected  # legacy path unchanged


# ---------------------------------------------------------------------------
# (b) Fix 2 — unconditional precedence for EVERY selected DS (incl token-only)
# ---------------------------------------------------------------------------


class TestUnconditionalPrecedence:
    def test_precedence_block_emitted_when_ds_active(self):
        from src.core.prompt_modules import build_generation_system_prompt

        out = build_generation_system_prompt(
            slide_style="SLIDE VISUAL STYLE: X", design_system_active=True
        )
        assert _PRECEDENCE_MARKER in out

    def test_precedence_covers_all_visual_styling(self):
        from src.core.prompt_modules import build_generation_system_prompt

        out = build_generation_system_prompt(slide_style="X", design_system_active=True)
        block = out[out.index(_PRECEDENCE_MARKER):].lower()
        for term in ("color", "typograph", "layout"):  # not just rules text
            assert term in block

    def test_token_only_ds_emits_precedence(self, session):
        from src.api.schemas.agent_config import AgentConfig

        ds = _token_only_ds(session)
        # token-only DS: compiled content has NO brand manual block...
        assert "BRAND MANUAL" not in ds.compiled_style_content
        # ...but the assembled prompt STILL emits the precedence statement.
        result = _prompts_with_db(
            AgentConfig(design_system_id=ds.id), _dispatching_db(design_system=ds)
        )
        assert _PRECEDENCE_MARKER in result["system_prompt"]

    def test_no_duplicate_precedence_compiler_heading_subsumed(self, session):
        """Fix 2: the compiler manual heading no longer states precedence (moved to
        the unconditional prompt block) — so no duplicate for a README DS."""
        from src.api.schemas.agent_config import AgentConfig

        ds = _readme_ds(session)
        assert "BRAND MANUAL" in ds.compiled_style_content
        assert "takes precedence" not in ds.compiled_style_content  # subsumed
        result = _prompts_with_db(
            AgentConfig(design_system_id=ds.id), _dispatching_db(design_system=ds)
        )
        sp = result["system_prompt"]
        assert sp.count("takes precedence") == 1  # exactly one, from the block


# ---------------------------------------------------------------------------
# (c) Fix 1 — 'modern' is not authoritative over a selected DS
# ---------------------------------------------------------------------------


class TestModernNotAuthoritativeOverDS:
    def test_ds_prompt_declares_authority_and_curbs_modern(self):
        from src.core.prompt_modules import build_generation_system_prompt

        out = build_generation_system_prompt(slide_style="X", design_system_active=True)
        block = out[out.index(_PRECEDENCE_MARKER):].lower()
        assert "authoritative" in block
        assert "modern" in block  # explicitly names the generic aesthetic to avoid
        # HTML_OUTPUT_FORMAT's generic 'modern' still present (byte-identical), but
        # the DS-authority block comes AFTER it and overrides it.
        assert out.index("professional modern styling") < out.index(_PRECEDENCE_MARKER)

    def test_no_ds_keeps_modern_and_no_authority_block(self):
        from src.core.defaults import DEFAULT_SLIDE_STYLE
        from src.core.prompt_modules import build_generation_system_prompt

        out = build_generation_system_prompt(slide_style=DEFAULT_SLIDE_STYLE)
        assert "professional modern styling" in out  # unchanged
        assert _PRECEDENCE_MARKER not in out


# ---------------------------------------------------------------------------
# (d) Fix 4 — image block does not suppress brand-asset placement when DS active
# ---------------------------------------------------------------------------


class TestImageCarveOut:
    def test_ds_image_section_encourages_brand_assets(self):
        from src.core.prompt_modules import _build_image_section

        out = _build_image_section(image_guidelines=None, design_system_active=True)
        assert "search_brand_assets" in out
        # search_images's own 'only when explicitly requested' tone is left intact.
        assert "ONLY when the user explicitly requests images" in out

    def test_no_ds_image_section_has_no_carveout(self):
        from src.core.prompt_modules import _build_image_section

        assert "search_brand_assets" not in _build_image_section()
        assert "search_brand_assets" not in _build_image_section(design_system_active=False)

    def test_ds_generation_prompt_has_brand_asset_carveout(self):
        from src.core.prompt_modules import build_generation_system_prompt

        out = build_generation_system_prompt(slide_style="X", design_system_active=True)
        assert "search_brand_assets" in out
        assert "on-brand" in out.lower()
