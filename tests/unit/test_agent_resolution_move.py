"""ws4c C8 — the resolution move, and the four properties a careless move loses.

``_get_prompt_content``, ``_build_tools`` and ``_design_system_is_active`` moved from
``agent_factory`` to ``agent_resolution``, and the slide-style BRANCH was lifted out
of ``_get_prompt_content`` into ``resolve_style_source`` so the graph path and the
monolith share ONE copy of it. Everything here pins something that a plausible
version of that move silently breaks:

* the moved names are still reachable through ``agent_factory`` (five suites and
  ``chat_service`` import them from there), while construction stayed put — which is
  what keeps the ``_create_model`` / ``_get_prompt_content`` patch targets working;
* ``_build_tools`` now resolves its collaborators in ``agent_resolution``'s
  namespace, so patch targets naming ``agent_factory`` must be repointed;
* resolution is a BRANCH, not a ladder — asserted behaviourally against real rows;
* the brand gate keeps BOTH halves;
* the late type-scale re-assertion still reads the SENTINEL-BEARING copy;
* ``_get_prompt_content`` still goes THROUGH the extracted branch rather than
  carrying a second inlined copy of it.
"""

import inspect
from unittest.mock import MagicMock, patch

import pytest

MOVED_NAMES = ("_get_prompt_content", "_build_tools", "_design_system_is_active")
STAYED_NAMES = ("_create_model", "build_agent_for_request")


# ---------------------------------------------------------------------------
# The move itself
# ---------------------------------------------------------------------------


class TestTheMove:
    def test_moved_private_names_live_in_agent_resolution(self):
        """The private names are the point: 31 of the 38 imports that reach this
        surface name one of them."""
        from src.services import agent_resolution

        for name in MOVED_NAMES:
            assert hasattr(agent_resolution, name), f"{name} missing from agent_resolution"
            assert getattr(agent_resolution, name).__module__ == "src.services.agent_resolution"

    def test_moved_private_names_are_still_reachable_from_agent_factory(self):
        """Same objects, not copies — the shim is a re-export, so a test patching
        ``agent_factory._get_prompt_content`` still reaches the one implementation."""
        from src.services import agent_factory, agent_resolution

        for name in MOVED_NAMES:
            assert hasattr(agent_factory, name), f"{name} not re-exported by agent_factory"
            assert getattr(agent_factory, name) is getattr(agent_resolution, name)

    def test_construction_stayed_in_agent_factory(self):
        """§35: ``_create_model`` and ``build_agent_for_request`` are agent
        CONSTRUCTION and do not move. Load-bearing: it is why the ten patch targets
        naming those two keep working untouched."""
        from src.services import agent_factory

        for name in STAYED_NAMES:
            assert getattr(agent_factory, name).__module__ == "src.services.agent_factory"

    def test_extracted_branch_surface_exists(self):
        """The style branch has exactly one home, and it returns all five values it
        produces — not just the model-facing bytes."""
        from src.services.agent_resolution import (
            ResolvedStyle,
            resolve_slide_style,
            resolve_style_source,
        )

        assert ResolvedStyle._fields == (
            "slide_style",
            "design_system_active",
            "design_system_compiled",
            "template_pinned",
            "image_guidelines",
        )
        assert list(inspect.signature(resolve_style_source).parameters) == ["config"]
        assert list(inspect.signature(resolve_slide_style).parameters) == ["config"]

    def test_sole_production_importer_still_resolves(self):
        """``chat_service`` imports ``build_agent_for_request`` from ``agent_factory``
        (the module ws4d rewrites). The shim exists for that cutover window."""
        import src.api.services.chat_service as chat_service
        from src.services import agent_factory

        assert chat_service.build_agent_for_request is agent_factory.build_agent_for_request


# ---------------------------------------------------------------------------
# Which namespace a patch target must name, proved by consequence
# ---------------------------------------------------------------------------


class TestPatchTargetNamespaces:
    """``unittest.mock.patch`` on a name the code no longer reads does not error by
    itself — it applies to the wrong module's attribute and intercepts nothing. Both
    halves of the repointing are pinned here by consequence, not by grep.
    """

    def test_repointed_target_intercepts(self):
        from src.api.schemas.agent_config import AgentConfig
        from src.services.agent_resolution import _build_tools

        marker = MagicMock()
        marker.name = "search_brand_assets"
        with patch(
            "src.services.agent_resolution._design_system_is_active", return_value=True
        ), patch(
            "src.services.agent_resolution.build_ds_asset_tool", return_value=marker
        ) as mock_build:
            tools = _build_tools(AgentConfig(design_system_id=99), {})

        mock_build.assert_called_once_with(99)
        assert marker in tools

    def test_the_old_target_fails_loudly_instead_of_silently(self):
        """The tool builders are deliberately NOT re-exported by the shim, so a stale
        patch target raises rather than applying to an attribute nothing reads. A
        patch that applies and intercepts nothing is how a test starts passing
        vacuously against real tool construction."""
        with pytest.raises(AttributeError):
            with patch("src.services.agent_factory.build_ds_asset_tool"):
                pass

    def test_the_surviving_targets_still_intercept_build_agent_for_request(self):
        """§35's consequence: ``build_agent_for_request`` stayed, so it resolves both
        of these in ``agent_factory``'s namespace and the ten patch targets naming
        them keep working."""
        from src.api.schemas.agent_config import AgentConfig
        from src.services.agent_factory import build_agent_for_request

        prompts = {
            "system_prompt": "MOVE-TEST-PROMPT",
            "slide_editing_instructions": None,
            "deck_prompt": None,
            "slide_style": None,
            "image_guidelines": None,
            "pre_assembled": True,
        }
        with patch("src.services.agent_factory._create_model") as mock_model, \
             patch("src.services.agent_factory._get_prompt_content") as mock_prompts, \
             patch("src.services.agent.get_settings") as mock_settings, \
             patch("src.services.agent.get_databricks_client") as mock_client:
            mock_model.return_value = MagicMock()
            mock_prompts.return_value = prompts
            mock_settings.return_value = MagicMock()
            mock_client.return_value = MagicMock()

            agent = build_agent_for_request(AgentConfig(), {"session_id": "s1"})

        mock_model.assert_called_once()
        mock_prompts.assert_called_once()
        assert agent.system_prompt == "MOVE-TEST-PROMPT"


# ---------------------------------------------------------------------------
# The brand gate — BOTH halves
# ---------------------------------------------------------------------------


class TestBrandGateKeepsBothHalves:
    def test_gate_source_still_conjoins_the_id_check_and_the_active_check(self):
        """A source assertion, deliberately: the second half fixes a MEASURED defect
        (a session keeps its pin after a soft delete, and on the id alone generation
        got a fully working brand tool for a TOMBSTONE) and it is the kind of clause
        a rewrite drops as redundant. The behavioural coverage against real active /
        tombstoned / unknown / failing rows lives in
        ``test_agent_factory.py::TestBrandAssetToolRequiresAnActiveDesignSystem``."""
        from src.services import agent_resolution

        src = inspect.getsource(agent_resolution._build_tools)
        gate = src[src.index("if config.design_system_id is not None"):]
        gate = gate[: gate.index("tools.append(build_ds_asset_tool")]
        assert "and" in gate
        assert "_design_system_is_active(" in gate

    def test_docstring_does_not_understate_the_gate(self):
        """The docstring this move inherited said the tool is added "ONLY when
        ``design_system_id is not None``", which describes the pre-fix code. A future
        reader regenerating the condition from that sentence re-opens the tombstone
        defect."""
        from src.services import agent_resolution

        doc = agent_resolution._build_tools.__doc__ or ""
        assert "ACTIVE" in doc


class TestDesignSystemIsActiveFailsClosed:
    def test_none_id_fails_closed(self, session):
        """A ``None`` id must answer NO. Run against a real session so this proves the
        QUERY path returns no row, not merely that an unreachable DB throws."""
        from src.services.agent_resolution import _design_system_is_active

        _make_ds(session, name="Live DS", is_active=True)
        with _yield_session(session):
            assert _design_system_is_active(None) is False

    def test_unknown_id_fails_closed(self, session):
        from src.services.agent_resolution import _design_system_is_active

        with _yield_session(session):
            assert _design_system_is_active(424242) is False

    def test_a_lookup_failure_fails_closed(self):
        from src.services.agent_resolution import _design_system_is_active

        def _boom():
            raise RuntimeError("database unreachable")

        with patch("src.core.database.get_db_session", _boom):
            assert _design_system_is_active(7) is False


# ---------------------------------------------------------------------------
# Fixtures / helpers for the row-backed tests
# ---------------------------------------------------------------------------


def _yield_session(session):
    """Patch the CALL-TIME ``get_db_session`` import.

    ``agent_resolution`` imports it inside each function, so a module-level patch on
    ``agent_resolution.get_db_session`` would intercept nothing — this property moved
    across with the code.
    """
    from contextlib import contextmanager

    @contextmanager
    def _cm():
        yield session

    return patch("src.core.database.get_db_session", _cm)


@pytest.fixture
def session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    import src.database.models  # noqa: F401 - register models with Base.metadata
    from src.core.database import Base

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


def _make_style(session, *, name="Legacy Style", content="LEGACY-STYLE-MARKER"):
    from src.database.models import SlideStyleLibrary

    style = SlideStyleLibrary(name=name, style_content=content, is_active=True)
    session.add(style)
    session.commit()
    session.refresh(style)
    return style


def _make_ds(session, *, name, is_active, compiled=None):
    from src.database.models.design_system import DesignSystem

    ds = DesignSystem(name=name, is_active=is_active, compiled_style_content=compiled)
    session.add(ds)
    session.commit()
    session.refresh(ds)
    return ds


def _current_artifact(type_scale_lines):
    """A compiled artifact shaped like the compiler's real output.

    Carries the leading currency sentinel (what makes it CURRENT, so the lazy
    recompile is not triggered) and a control-character-delimited type-scale region
    (what the late re-assertion is read out of).
    """
    from src.services.design_system_compiler import (
        _COMPILER_VERSION_MARKER,
        _CURRENCY_SENTINEL,
        _REGION_BEGIN,
        _REGION_END,
    )

    return (
        _CURRENCY_SENTINEL
        + "SLIDE VISUAL STYLE: "
        + _COMPILER_VERSION_MARKER
        + " MOVE-TEST-DS\n\n"
        + _REGION_BEGIN
        + "BRAND TYPE SCALE:\n"
        + "\n".join(type_scale_lines)
        + "\n"
        + _REGION_END
    )


# ---------------------------------------------------------------------------
# Resolution is a BRANCH, not a ladder — behaviourally, against real rows
# ---------------------------------------------------------------------------


class TestResolutionIsABranchNotALadder:
    """An INACTIVE ``design_system_id`` lands on ``DEFAULT_SLIDE_STYLE``; the
    ``slide_style_id`` limb is never evaluated. A legacy style is the fallback for
    "no design system selected", not for "the selected one did not resolve".
    Asserted behaviourally — a source grep would pass against an ``if``/``if``
    ladder that reads identically.
    """

    def test_inactive_design_system_does_not_fall_through_to_the_slide_style(self, session):
        from src.api.schemas.agent_config import AgentConfig
        from src.core.defaults import DEFAULT_SLIDE_STYLE
        from src.services.agent_resolution import resolve_style_source

        ds = _make_ds(session, name="Dead DS", is_active=False)
        style = _make_style(session)
        config = AgentConfig(design_system_id=ds.id, slide_style_id=style.id)

        with _yield_session(session):
            resolved = resolve_style_source(config)

        assert resolved.slide_style == DEFAULT_SLIDE_STYLE
        assert "LEGACY-STYLE-MARKER" not in resolved.slide_style
        assert resolved.design_system_active is False
        # The legacy limb also contributes image_guidelines; it must not have run.
        assert resolved.image_guidelines is None

    def test_non_vacuity_that_same_style_row_is_reachable_with_no_design_system(
        self, session
    ):
        """Guards the test above against passing because the style row was
        unreachable in the first place: with no design system pinned, the very same
        row resolves."""
        from src.api.schemas.agent_config import AgentConfig
        from src.services.agent_resolution import resolve_style_source

        style = _make_style(session)
        with _yield_session(session):
            resolved = resolve_style_source(AgentConfig(slide_style_id=style.id))

        assert resolved.slide_style == "LEGACY-STYLE-MARKER"

    def test_unknown_design_system_id_also_does_not_fall_through(self, session):
        from src.api.schemas.agent_config import AgentConfig
        from src.core.defaults import DEFAULT_SLIDE_STYLE
        from src.services.agent_resolution import resolve_style_source

        style = _make_style(session)
        with _yield_session(session):
            resolved = resolve_style_source(
                AgentConfig(design_system_id=424242, slide_style_id=style.id)
            )

        assert resolved.slide_style == DEFAULT_SLIDE_STYLE

    def test_legacy_row_image_guidelines_travel_with_the_style(self, session):
        """The branch produces FIVE values, not four: the legacy limb sets
        ``image_guidelines`` alongside the bytes, and an extraction that returns only
        the four named in the plan drops a legacy row's image guidance out of the
        prompt entirely."""
        from src.api.schemas.agent_config import AgentConfig
        from src.database.models import SlideStyleLibrary
        from src.services.agent_resolution import _get_prompt_content, resolve_style_source

        style = SlideStyleLibrary(
            name="Guided Style",
            style_content="LEGACY-STYLE-MARKER",
            image_guidelines="Use logo.png",
            is_active=True,
        )
        session.add(style)
        session.commit()
        session.refresh(style)

        with _yield_session(session):
            resolved = resolve_style_source(AgentConfig(slide_style_id=style.id))
            prompts = _get_prompt_content(AgentConfig(slide_style_id=style.id))

        assert resolved.image_guidelines == "Use logo.png"
        assert "Use logo.png" in prompts["system_prompt"]


# ---------------------------------------------------------------------------
# The late type-scale re-assertion, and WHICH copy it reads
# ---------------------------------------------------------------------------


class TestTypeScaleReassertionStillWired:
    _RAMP = ["- Cover/hero titles: 64px", "- Section/slide titles: 40px"]

    def test_reassertion_reaches_the_assembled_prompt(self, session):
        from src.api.schemas.agent_config import AgentConfig
        from src.services.agent_resolution import _get_prompt_content
        from src.services.design_system_compiler import TYPE_SCALE_REASSERTION_HEADING

        ds = _make_ds(
            session,
            name="TypeScale DS",
            is_active=True,
            compiled=_current_artifact(self._RAMP),
        )
        with _yield_session(session):
            sp = _get_prompt_content(AgentConfig(design_system_id=ds.id))["system_prompt"]

        assert TYPE_SCALE_REASSERTION_HEADING in sp
        tail = sp[sp.index(TYPE_SCALE_REASSERTION_HEADING):]
        # The numbers restated LAST are this artifact's own.
        assert "64px" in tail
        assert "40px" in tail

    def test_the_region_is_read_from_the_sentinel_bearing_copy(self, session):
        """``design_system_compiled`` keeps the control sentinels; ``slide_style`` has
        had them stripped for the model. Reading the region out of the model-facing
        copy silently yields an EMPTY re-assertion — so the two must not be swapped.
        This asserts the difference is real, and the test above asserts the
        consequence."""
        from src.api.schemas.agent_config import AgentConfig
        from src.services.agent_resolution import resolve_style_source
        from src.services.design_system_compiler import extract_type_scale_block

        ds = _make_ds(
            session,
            name="Sentinel DS",
            is_active=True,
            compiled=_current_artifact(self._RAMP),
        )
        with _yield_session(session):
            resolved = resolve_style_source(AgentConfig(design_system_id=ds.id))

        assert extract_type_scale_block(resolved.design_system_compiled) is not None
        assert extract_type_scale_block(resolved.slide_style) is None
        assert resolved.design_system_active is True


# ---------------------------------------------------------------------------
# §33's replacement for the guard that could not fail
# ---------------------------------------------------------------------------


class TestPromptContentGoesThroughTheExtractedBranch:
    """The plan's guard was ``resolve_slide_style(config) ==
    _get_prompt_content(config)["slide_style"]`` — both sides are ``None`` on every
    config, so it could not fail. These two can: they pin that there is ONE
    implementation of the branch and that prompt assembly goes through it.
    """

    _MARKER = "MOVE-TEST-STYLE-MARKER-9f3a"

    def _marker_style(self):
        from src.services.agent_resolution import ResolvedStyle

        return ResolvedStyle(
            slide_style=self._MARKER,
            design_system_active=False,
            design_system_compiled=None,
            template_pinned=False,
            image_guidelines=None,
        )

    def test_the_resolved_style_reaches_the_assembled_system_prompt(self):
        """Re-inlining the branch inside ``_get_prompt_content`` — "optimising away
        the delegation" — makes this red."""
        from src.api.schemas.agent_config import AgentConfig
        from src.services.agent_resolution import _get_prompt_content

        with patch(
            "src.services.agent_resolution.resolve_style_source",
            return_value=self._marker_style(),
        ):
            result = _get_prompt_content(AgentConfig())

        assert self._MARKER in result["system_prompt"]

    def test_resolve_slide_style_is_a_wrapper_over_the_same_one_branch(self):
        """A second copy of the branch behind ``resolve_slide_style`` — the outcome
        §33 forbids — makes this red."""
        from src.api.schemas.agent_config import AgentConfig
        from src.services.agent_resolution import resolve_slide_style

        with patch(
            "src.services.agent_resolution.resolve_style_source",
            return_value=self._marker_style(),
        ):
            assert resolve_slide_style(AgentConfig()) == self._MARKER

    def test_the_returned_dict_still_pins_slide_style_to_none(self):
        """The extraction must not "helpfully" fill the key in: the null is a pinned
        contract (``test_agent_factory.py`` asserts it) and ``agent.py``'s legacy
        concatenation branch is the only other reader."""
        from src.api.schemas.agent_config import AgentConfig
        from src.services.agent_resolution import _get_prompt_content

        result = _get_prompt_content(AgentConfig())

        assert result["slide_style"] is None
        assert result["pre_assembled"] is True
