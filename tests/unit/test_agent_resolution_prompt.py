"""Tests for assemble_skill_prompt in agent_resolution.py — C3.

Covers:
- Payload appears in the assembled prompt (guards the central defect the plan warns about)
- Frame constraints injected when design_system_active=False (cases 2 and 3)
- Frame constraints NOT injected (not duplicated) when design_system_active=True (case 1)
- DESIGN_SYSTEM_PRECEDENCE present only when design_system_active=True
- All three style cases are reachable through the real resolution path
- _SLIDE_FRAME_CONSTRAINTS provenance: imported from the compiler, not retyped locally

Why a bool, not a ResolvedStyle (Ruling C-21, corrections §46):
assemble_skill_prompt reads exactly one field of ResolvedStyle.  A NamedTuple in
GraphState would produce langgraph's "unregistered type" deserialisation warning on
turn 2 and will be blocked in a future version.  A plain bool never crosses a
checkpoint boundary as an object.

Style cases (§L5, task-C3-brief.md table):
  Case 1 — design system active    (design_system_active=True):
      compiled style already carries _SLIDE_FRAME_CONSTRAINTS; do NOT inject;
      DO inject DESIGN_SYSTEM_PRECEDENCE
  Case 2 — DEFAULT_SLIDE_STYLE     (design_system_active=False):
      no safe-area numbers; inject _SLIDE_FRAME_CONSTRAINTS
  Case 3 — legacy library style    (design_system_active=False):
      opaque content, usually no constraints; inject _SLIDE_FRAME_CONSTRAINTS
"""

from __future__ import annotations

import inspect
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.core.prompt_modules import DESIGN_SYSTEM_PRECEDENCE
from src.core.skills import load_skill
from src.services.agent_resolution import assemble_skill_prompt
from src.services.design_system_compiler import _SLIDE_FRAME_CONSTRAINTS


# ---------------------------------------------------------------------------
# DB fixture — only used in tests that exercise the real resolution path
# ---------------------------------------------------------------------------


@pytest.fixture
def _db_session():
    """In-memory SQLite session for resolution-path tests.

    Pattern from test_agent_resolution_move.py: file-backed OR StaticPool with
    a single thread — this fixture only drives sequential code, so StaticPool is
    safe here (unlike the compiled-graph tests which need multi-thread safety).
    """
    import src.database.models  # noqa: F401 — register models with Base.metadata
    from src.core.database import Base

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _yield_session(session):
    """Patch the call-time ``get_db_session`` import.

    ``agent_resolution`` imports ``get_db_session`` inside each function, so a
    module-level patch on ``agent_resolution.get_db_session`` would intercept
    nothing.  Patch the canonical location instead.
    """

    @contextmanager
    def _cm():
        yield session

    return patch("src.core.database.get_db_session", _cm)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAssembleSkillPrompt:

    def test_payload_appears_in_assembled_prompt(self):
        """The central defect the plan warns about by name (§29 of the plan).

        The obvious implementation returns instructions + conditionals and stops,
        so the builder never receives its section brief, the reviewer never
        receives the HTML it is reviewing, and the fixer never receives the
        finding.  This test ensures the payload is present.
        """
        skill = load_skill("builder")
        payload = {"section": "introduction", "user_request": "create a title slide"}
        prompt = assemble_skill_prompt(skill, payload, design_system_active=False)
        assert "introduction" in prompt, "section key not in prompt"
        assert "create a title slide" in prompt, "user_request value not in prompt"

    def test_payload_content_visible_for_reviewer(self):
        """Reviewer receives the HTML it is reviewing — not just its instructions.

        The payload is JSON-serialised, so double-quoted attributes appear as
        backslash-escaped strings.  Assert on a substring that survives intact.
        """
        skill = load_skill("build_reviewer")
        payload = {"html": "<h1>Sales Results</h1>", "position": 0}
        prompt = assemble_skill_prompt(skill, payload, design_system_active=False)
        assert "Sales Results" in prompt, "Reviewer payload HTML not in assembled prompt"

    # --- Frame constraint injection ---

    def test_frame_constraints_injected_when_no_design_system(self):
        """Cases 2 and 3: design_system_active=False → inject _SLIDE_FRAME_CONSTRAINTS."""
        skill = load_skill("builder")
        prompt = assemble_skill_prompt(skill, {}, design_system_active=False)
        assert _SLIDE_FRAME_CONSTRAINTS in prompt, (
            "Frame constraints must be injected when design_system_active=False"
        )

    def test_frame_constraints_not_injected_when_design_system_active(self):
        """Case 1: design_system_active=True → do NOT inject _SLIDE_FRAME_CONSTRAINTS.

        Not cosmetic: the build reviewer judges against these exact numbers, so
        a builder that never received them would be judged against numbers it was
        never shown — unfair by construction.
        """
        skill = load_skill("builder")
        prompt = assemble_skill_prompt(skill, {}, design_system_active=True)
        assert _SLIDE_FRAME_CONSTRAINTS not in prompt, (
            "Frame constraints must NOT be injected when design_system_active=True (case 1); "
            "the compiler already emits them inside the compiled style"
        )

    # --- Design-system precedence ---

    def test_design_system_precedence_present_when_active(self):
        """DESIGN_SYSTEM_PRECEDENCE injected for case 1 (design_system_active=True)."""
        skill = load_skill("architect")
        prompt = assemble_skill_prompt(skill, {}, design_system_active=True)
        assert DESIGN_SYSTEM_PRECEDENCE in prompt

    def test_design_system_precedence_absent_without_design_system(self):
        """DESIGN_SYSTEM_PRECEDENCE must not appear when design_system_active=False."""
        skill = load_skill("architect")
        prompt = assemble_skill_prompt(skill, {}, design_system_active=False)
        assert DESIGN_SYSTEM_PRECEDENCE not in prompt, (
            "DESIGN_SYSTEM_PRECEDENCE must be absent when design_system_active=False"
        )

    # --- All three cases reachable via the real resolution path ---

    def test_all_three_style_cases_reachable(self, _db_session):
        """All three cases are reachable and each yields the correct flag value.

        Case 1: design_system_active=True (passed directly — the DS-active branch
            requires a compiled DesignSystem row; the boolean is what matters here).
        Case 2: resolve_style_source(AgentConfig()) → DEFAULT_SLIDE_STYLE,
            design_system_active=False.  No DB access: no design_system_id or
            slide_style_id means both branches are skipped.
        Case 3: resolve_style_source(AgentConfig(slide_style_id=X)) with a real
            library row → design_system_active=False.  Uses the real DB path so the
            library-style limb is actually exercised, not just a second identical bool.
        """
        from src.api.schemas.agent_config import AgentConfig
        from src.database.models import SlideStyleLibrary
        from src.services.agent_resolution import resolve_style_source

        skill = load_skill("build_reviewer")

        # Case 1: design_system_active=True (prompt-assembly path only)
        case1 = assemble_skill_prompt(skill, {}, design_system_active=True)

        # Case 2: AgentConfig with no IDs → DEFAULT_SLIDE_STYLE, dsa=False (no DB)
        resolved2 = resolve_style_source(AgentConfig())
        assert resolved2.design_system_active is False, (
            "Case 2 sanity: no-style config must resolve design_system_active=False"
        )
        case2 = assemble_skill_prompt(skill, {}, resolved2.design_system_active)

        # Case 3: library slide-style row → dsa=False, through the real resolution path
        style = SlideStyleLibrary(
            name="Test Brand Style", style_content="BRAND-CSS", is_active=True
        )
        _db_session.add(style)
        _db_session.commit()
        _db_session.refresh(style)

        with _yield_session(_db_session):
            resolved3 = resolve_style_source(AgentConfig(slide_style_id=style.id))

        assert resolved3.design_system_active is False, (
            "Case 3 sanity: library-style config must resolve design_system_active=False"
        )
        case3 = assemble_skill_prompt(skill, {}, resolved3.design_system_active)

        # Case 1: no frame constraints injection; DS precedence present
        assert _SLIDE_FRAME_CONSTRAINTS not in case1, "case 1 must not inject constraints"
        assert DESIGN_SYSTEM_PRECEDENCE in case1, "case 1 must inject DS precedence"

        # Cases 2 and 3: frame constraints injected; no DS precedence
        for i, case in enumerate((case2, case3), start=2):
            assert _SLIDE_FRAME_CONSTRAINTS in case, f"case {i} must inject constraints"
            assert DESIGN_SYSTEM_PRECEDENCE not in case, (
                f"case {i} must not inject DS precedence"
            )

    # --- Skill instructions always present ---

    def test_skill_instructions_in_assembled_prompt(self):
        for name in ["architect", "builder", "fixer"]:
            skill = load_skill(name)
            prompt = assemble_skill_prompt(skill, {}, design_system_active=False)
            assert skill.instructions in prompt, (
                f"Skill {name!r} instructions not found in assembled prompt"
            )


# ---------------------------------------------------------------------------
# Provenance test — _SLIDE_FRAME_CONSTRAINTS is imported, not retyped
# ---------------------------------------------------------------------------


class TestSlideFrameConstraintsProvenance:
    """Asserts that _SLIDE_FRAME_CONSTRAINTS is imported from the compiler.

    WHY this test exists and is NOT banned:

    The plan bans *proving behaviour via source greps* — that ban applies to
    branch-vs-ladder structure (e.g. asserting ``if`` appears before ``elif``).
    This test proves *provenance*: both sites read the same bytes at request
    time because they read the same object.  Provenance is inherently not a
    behavioural property, and a value comparison (``str in str``) cannot detect
    a same-content retyped copy.

    A retyped copy is free to drift independently of the compiler's when the
    compiler is updated — and those numbers have already drifted once in this
    codebase.  The ``COMPILER_VERSION`` currency contract exists to prevent
    exactly that, and this test is its enforcement point for
    ``assemble_skill_prompt``.
    """

    def test_slide_frame_constraints_imported_from_compiler_not_retyped(self):
        """The import line must be present in agent_resolution's source.

        Sabotage: replace the local import with a retyped literal inside
        assemble_skill_prompt — the source-inspection assertion fires because the
        import line is absent.  A value-comparison test would NOT fire (the bytes
        are the same); this test does.
        """
        import src.services.agent_resolution as agent_resolution_module

        source = inspect.getsource(agent_resolution_module)
        assert (
            "from src.services.design_system_compiler import _SLIDE_FRAME_CONSTRAINTS"
            in source
        ), (
            "assemble_skill_prompt must import _SLIDE_FRAME_CONSTRAINTS from the compiler, "
            "not retype it locally. A retyped copy drifts independently when the compiler "
            "updates — the COMPILER_VERSION contract exists to prevent exactly this."
        )
