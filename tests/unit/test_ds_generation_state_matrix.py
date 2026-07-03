"""End-to-end state-matrix tests for design-system-driven generation (Phase 2 reset).

The three states, None/empty-safe (no exotic edge cases):

1. NO design_system_id       -> no search_brand_assets tool, no DS injection, the
                                legacy slide_style path is byte-for-byte unchanged.
2. design_system_id set       -> FULL brand manual + tokens + fonts + asset CONTRACT
                                in the prompt, AND the search_brand_assets tool.
3. design_system_id + (future) template_id -> a CLEAN None-safe hook: registration
   is gated on design_system_id ALONE, with no template coupling to break later.

All fixtures are SYNTHETIC.
"""
import inspect
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register models with Base.metadata
from src.core.database import Base


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


def _full_ds(session):
    """A synthetic design system exercising manual + tokens + fonts + image."""
    from src.database.models.design_system import (
        DesignSystem,
        DesignSystemAsset,
        DesignSystemFile,
        DesignSystemToken,
    )
    from src.services.design_system_compiler import recompute_compiled_style_content

    ds = DesignSystem(
        name="Acme DS",
        description="Synthetic.",
        font_mapping_json={
            "families": [
                {"family": "Acme Sans",
                 "variants": [{"weight": "400", "style": "normal", "files": []}],
                 "tokens": ["font-sans"]}
            ]
        },
    )
    ds.tokens.append(DesignSystemToken(group="core", name="primary", value="#123456"))
    ds.assets.append(DesignSystemAsset(
        kind="logo", filename="logo.svg", mime="image/svg+xml", data=b"<svg/>", size_bytes=6))
    ds.assets.append(DesignSystemAsset(
        kind="font", filename="acme.woff2", mime="font/woff2", data=b"f", size_bytes=1))
    ds.files.append(DesignSystemFile(
        path="README.md", kind="readme", mime="text/markdown",
        data=b"# Acme\n\nBrand manual prose here.\n", size_bytes=32))
    ds.files.append(DesignSystemFile(
        path="SKILL.md", kind="skill", mime="text/markdown",
        data=b"Always place the logo top-left.\n", size_bytes=32))
    session.add(ds)
    session.flush()  # assign asset ids for @font-face references
    recompute_compiled_style_content(ds)
    session.commit()
    session.refresh(ds)
    return ds


def _dispatching_db(*, design_system=None, slide_style=None):
    """MagicMock DB whose query(Model).filter_by(...).first() dispatches by model."""
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


def _prompts_with_db(config, db):
    from src.services.agent_factory import _get_prompt_content

    with patch("src.core.database.get_db_session") as mock_get_db:
        mock_get_db.return_value.__enter__ = MagicMock(return_value=db)
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
        return _get_prompt_content(config)


class TestStateNoDesignSystem:
    def test_legacy_path_unchanged_and_no_brand_asset_tool(self):
        from src.api.schemas.agent_config import AgentConfig
        from src.core.prompt_modules import build_generation_system_prompt
        from src.services.agent_factory import _build_tools

        style = MagicMock()
        style.style_content = "LEGACY-STYLE-MARKER"
        style.image_guidelines = None
        config = AgentConfig(slide_style_id=42)

        prompts = _prompts_with_db(config, _dispatching_db(slide_style=style))
        expected = build_generation_system_prompt(
            slide_style="LEGACY-STYLE-MARKER", deck_prompt=None, image_guidelines=None
        )
        assert prompts["system_prompt"] == expected  # byte-identical legacy path
        assert "BRAND MANUAL" not in prompts["system_prompt"]
        assert "search_brand_assets" not in prompts["system_prompt"]

        names = [t.name for t in _build_tools(config, {})]
        assert "search_images" in names
        assert "search_brand_assets" not in names


class TestStateDesignSystemSelected:
    def test_full_injection_and_tool(self, session):
        from src.api.schemas.agent_config import AgentConfig
        from src.services.agent_factory import _build_tools

        ds = _full_ds(session)
        config = AgentConfig(design_system_id=ds.id)

        sp = _prompts_with_db(config, _dispatching_db(design_system=ds))["system_prompt"]
        assert "BRAND MANUAL" in sp
        assert "Brand manual prose here." in sp          # FULL README
        assert "Always place the logo top-left." in sp   # FULL SKILL
        assert "BRAND COLOR TOKENS" in sp
        assert "--brand-core-primary: #123456;" in sp
        assert "BRAND FONTS:" in sp                       # font @font-face inline
        assert "BRAND FONT FAMILIES" in sp
        assert "BRAND IMAGE ASSETS" in sp                 # asset contract
        assert "search_brand_assets" in sp               # contract names the tool

        names = [t.name for t in _build_tools(config, {})]
        assert "search_brand_assets" in names
        assert "search_images" in names

    def test_empty_design_system_is_safe(self, session):
        """Empty DS: prompt still valid (header + contract); tool present and its
        no-op search degrades gracefully (verified in the tool's own tests)."""
        from src.api.schemas.agent_config import AgentConfig
        from src.database.models.design_system import DesignSystem
        from src.services.agent_factory import _build_tools
        from src.services.design_system_compiler import recompute_compiled_style_content

        ds = DesignSystem(name="Empty DS")
        session.add(ds)
        session.flush()
        recompute_compiled_style_content(ds)
        session.commit()
        session.refresh(ds)
        config = AgentConfig(design_system_id=ds.id)

        sp = _prompts_with_db(config, _dispatching_db(design_system=ds))["system_prompt"]
        assert "BRAND IMAGE ASSETS" in sp  # contract always present
        assert "search_brand_assets" in [t.name for t in _build_tools(config, {})]


class TestStateTemplateHook:
    def test_registration_gated_on_design_system_id_alone(self):
        """State 3 hook: the tool builder takes ONLY a design_system_id (no template
        arg), and registration keys on design_system_id ALONE — so a future
        template_id is a clean, None-safe addition, not a breaking change."""
        from src.api.schemas.agent_config import AgentConfig
        from src.services.agent_factory import _build_tools
        from src.services.tools import build_ds_asset_tool

        assert list(inspect.signature(build_ds_asset_tool).parameters) == ["design_system_id"]

        config = AgentConfig(design_system_id=5)
        assert "search_brand_assets" in [t.name for t in _build_tools(config, {})]
