"""End-to-end state-matrix tests for design-system-driven generation.

The states, None/empty-safe (no exotic edge cases):

1. NO design_system_id       -> no search_brand_assets tool, no DS injection, the
                                legacy slide_style path is byte-for-byte unchanged.
2. design_system_id set       -> FULL brand manual + tokens + fonts + asset CONTRACT
                                in the prompt, AND the search_brand_assets tool.
3. design_system_id + template_id (Phase 4) -> a valid pin appends the
   SELECTED-TEMPLATE block at prompt-assembly time; an absent/invalid pin is
   byte-identical to the no-template path (ignored + logged, never a 500); tool
   registration stays gated on design_system_id ALONE.
4. design_system_id set, but the PERSISTED ``compiled_style_content`` predates the
   current compiler (stale/missing version marker) or was never compiled -> the
   factory recompiles it lazily from the row's persisted tokens/files/assets at
   consumption time (no batch backfill), so an active DS ALWAYS injects the
   current guardrail blocks.

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
        """The tool builder takes ONLY a design_system_id (no template arg), and
        registration keys on design_system_id ALONE — a pinned template_id
        (Phase 4) shapes prompt assembly, never tool registration."""
        from src.api.schemas.agent_config import AgentConfig
        from src.services.agent_factory import _build_tools
        from src.services.tools import build_ds_asset_tool

        assert list(inspect.signature(build_ds_asset_tool).parameters) == ["design_system_id"]

        config = AgentConfig(design_system_id=5)
        assert "search_brand_assets" in [t.name for t in _build_tools(config, {})]


class TestStateTemplatePinned:
    """Phase 4 states: an optional ``template_id`` pins ONE of the design
    system's templates. Pinned + valid -> a SELECTED-TEMPLATE block is appended
    at prompt-assembly time (never into the stored artifact). Absent/invalid ->
    byte-identical no-template behavior, ignored + logged, never a 500."""

    def _templated_ds(self, session):
        from src.database.models.design_system import DesignSystemTemplate

        ds = _full_ds(session)
        logo_id = next(a.id for a in ds.assets if a.kind == "logo")
        ds.templates.append(DesignSystemTemplate(
            name="Acme Corporate",
            description="Cover + agenda, content, closing.",
            entry_path="templates/corporate/index.html",
            layout_html=(
                '<section class="slide"><img src="{{ds-asset:%d}}" alt="Acme logo" />'
                "<h1>Sample title</h1></section>" % logo_id
            ),
            token_css=":root { --acme-navy: #0B1F3A; }",
        ))
        session.commit()
        session.refresh(ds)
        return ds

    def _prompt(self, ds, template_id=None):
        from src.api.schemas.agent_config import AgentConfig

        config = AgentConfig(design_system_id=ds.id, template_id=template_id)
        return _prompts_with_db(config, _dispatching_db(design_system=ds))["system_prompt"]

    def test_pinned_template_appends_block_after_compiled_artifact(self, session):
        from src.core.prompt_modules import build_generation_system_prompt
        from src.services.design_system_templates import build_selected_template_block

        ds = self._templated_ds(session)
        template = ds.templates[0]
        sp = self._prompt(ds, template_id=template.id)

        block = build_selected_template_block(template)
        expected = build_generation_system_prompt(
            slide_style=f"{ds.compiled_style_content}\n\n{block}",
            deck_prompt=None,
            image_guidelines=None,
            design_system_active=True,
        )
        assert sp == expected  # block appended at assembly, byte-exact
        assert "SELECTED SLIDE TEMPLATE: Acme Corporate" in sp
        logo_id = next(a.id for a in ds.assets if a.kind == "logo")
        assert f"{{{{ds-asset:{logo_id}}}}}" in sp  # rewritten refs ride into the prompt

    def test_no_template_id_is_byte_identical_to_ds_only_path(self, session):
        from src.core.prompt_modules import build_generation_system_prompt

        ds = self._templated_ds(session)
        sp = self._prompt(ds, template_id=None)
        expected = build_generation_system_prompt(
            slide_style=ds.compiled_style_content,
            deck_prompt=None,
            image_guidelines=None,
            design_system_active=True,
        )
        assert sp == expected
        assert "SELECTED SLIDE TEMPLATE" not in sp

    def test_stored_artifact_never_carries_the_template_block(self, session):
        ds = self._templated_ds(session)
        self._prompt(ds, template_id=ds.templates[0].id)
        assert "SELECTED SLIDE TEMPLATE" not in ds.compiled_style_content

    def test_template_of_other_design_system_ignored_and_logged(self, session, caplog):
        import logging

        from src.database.models.design_system import DesignSystem, DesignSystemTemplate

        ds_a = self._templated_ds(session)
        ds_b = DesignSystem(name="Acme Second DS")
        ds_b.templates.append(DesignSystemTemplate(
            name="Acme Other",
            entry_path="templates/other/index.html",
            layout_html="<section>other</section>",
        ))
        session.add(ds_b)
        session.commit()

        with caplog.at_level(logging.WARNING):
            sp = self._prompt(ds_a, template_id=ds_b.templates[0].id)
        assert "SELECTED SLIDE TEMPLATE" not in sp
        assert "BRAND MANUAL" in sp  # design system itself still fully applied

    def test_missing_template_falls_back_gracefully(self, session, caplog):
        import logging

        ds = self._templated_ds(session)
        with caplog.at_level(logging.WARNING):
            sp = self._prompt(ds, template_id=424242)
        assert "SELECTED SLIDE TEMPLATE" not in sp
        assert "BRAND MANUAL" in sp

    def test_template_id_never_changes_tool_registration(self, session):
        from src.api.schemas.agent_config import AgentConfig
        from src.services.agent_factory import _build_tools

        ds = self._templated_ds(session)
        with_template = AgentConfig(design_system_id=ds.id, template_id=ds.templates[0].id)
        without = AgentConfig(design_system_id=ds.id)
        assert (
            [t.name for t in _build_tools(with_template, {})]
            == [t.name for t in _build_tools(without, {})]
        )


class TestStateStaleCompiledContent:
    """State 4: a PERSISTED row whose ``compiled_style_content`` was produced by an
    OLDER compiler (no version marker — e.g. compiled before the SLIDE FRAME
    CONSTRAINTS block existed) or never compiled at all. The factory must NOT
    inject the stale artifact verbatim: it recompiles from the row's persisted
    tokens/files/assets so the active DS always carries the current blocks.
    All fixtures SYNTHETIC."""

    # A pre-guardrail artifact shape: header without a version marker, no frame block.
    _STALE_ARTIFACT = (
        "SLIDE VISUAL STYLE: Acme DS\n\n"
        "BRAND COLOR TOKENS:\n- core:\n  - primary: #123456"
    )

    def _prompt_for(self, ds):
        from src.api.schemas.agent_config import AgentConfig

        return _prompts_with_db(
            AgentConfig(design_system_id=ds.id), _dispatching_db(design_system=ds)
        )["system_prompt"]

    def test_stale_row_recompiles_and_prompt_carries_frame_constraints(self, session):
        ds = _full_ds(session)
        ds.compiled_style_content = self._STALE_ARTIFACT  # simulate a pre-guardrail row
        session.commit()

        sp = self._prompt_for(ds)
        assert "SLIDE FRAME CONSTRAINTS" in sp
        assert "1280x720" in sp
        assert "BRAND IMAGE ASSETS" in sp        # asset contract restored too
        assert "Brand manual prose here." in sp  # rebuilt from the persisted files

    def test_stale_row_is_refreshed_in_place_for_persistence(self, session):
        from src.services.design_system_compiler import compiled_style_content_is_current

        ds = _full_ds(session)
        ds.compiled_style_content = self._STALE_ARTIFACT
        session.commit()

        self._prompt_for(ds)
        # The factory refreshed the record in place; in production get_db_session
        # commits on exit, persisting the recompute (lazy backfill-on-read).
        assert compiled_style_content_is_current(ds.compiled_style_content)
        assert "SLIDE FRAME CONSTRAINTS" in ds.compiled_style_content

    def test_never_compiled_row_compiles_at_consumption(self, session):
        from src.database.models.design_system import DesignSystem, DesignSystemToken

        ds = DesignSystem(name="Uncompiled DS")
        ds.tokens.append(DesignSystemToken(group="core", name="primary", value="#123456"))
        session.add(ds)
        session.commit()
        session.refresh(ds)
        assert ds.compiled_style_content is None

        sp = self._prompt_for(ds)
        assert "SLIDE FRAME CONSTRAINTS" in sp
        assert "--brand-core-primary: #123456;" in sp

    def test_stale_row_without_retained_files_recompiles_degraded(self, session):
        """Pre-Phase-1 imports retained NO ``design_system_file`` rows: the lazy
        recompute must still yield a valid artifact (no BRAND MANUAL, no crash)."""
        from src.database.models.design_system import DesignSystem, DesignSystemToken

        ds = DesignSystem(name="Legacy Import DS", compiled_style_content=self._STALE_ARTIFACT)
        ds.tokens.append(DesignSystemToken(group="core", name="primary", value="#123456"))
        session.add(ds)
        session.commit()
        session.refresh(ds)

        sp = self._prompt_for(ds)
        assert "SLIDE FRAME CONSTRAINTS" in sp
        assert "--brand-core-primary: #123456;" in sp
        assert "BRAND MANUAL" not in sp  # degraded (no retained README/SKILL) but valid

    def test_current_row_injected_verbatim_without_recompute(self, session):
        from src.api.schemas.agent_config import AgentConfig

        ds = _full_ds(session)  # freshly compiled -> carries the current marker
        with patch(
            "src.services.design_system_compiler.recompute_compiled_style_content"
        ) as recompute_spy:
            sp = _prompts_with_db(
                AgentConfig(design_system_id=ds.id), _dispatching_db(design_system=ds)
            )["system_prompt"]
        recompute_spy.assert_not_called()
        assert ds.compiled_style_content in sp  # stored artifact injected verbatim
