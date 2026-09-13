"""Tests for assemble_skill_prompt in agent_resolution.py — C3.

Covers:
- Payload appears in the assembled prompt (guards the central defect the plan warns about)
- Frame constraints injected when design_system_active=False (cases 2 and 3)
- Frame constraints NOT injected (not duplicated) when design_system_active=True (case 1)
- DESIGN_SYSTEM_PRECEDENCE present only when design_system_active=True
- All three style cases are reachable and land in the correct bucket

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

Sabotage targets used during development (results in task-C3-report.md):
- S1: drop payload → test_payload_appears_in_assembled_prompt red
- S2: inject constraints unconditionally → test_frame_constraints_not_injected_case1 red
"""

import pytest

from src.core.prompt_modules import DESIGN_SYSTEM_PRECEDENCE
from src.core.skills import load_skill
from src.services.agent_resolution import assemble_skill_prompt
from src.services.design_system_compiler import _SLIDE_FRAME_CONSTRAINTS


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

    # --- Frame constraint injection: the three cases ---

    def test_frame_constraints_injected_when_no_design_system(self):
        """Cases 2 and 3: design_system_active=False → inject _SLIDE_FRAME_CONSTRAINTS."""
        skill = load_skill("builder")
        for dsa in (False,):  # both case 2 and 3 have dsa=False
            prompt = assemble_skill_prompt(skill, {}, design_system_active=dsa)
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

    # --- All three cases reachable via the one boolean ---

    def test_all_three_style_cases_reachable(self):
        """Each case is reachable and lands in the correct injection bucket.

        Cases 2 and 3 both map to design_system_active=False; case 1 maps to True.
        The plan's test intent — 'injected in cases 2 and 3 and not duplicated in
        case 1' — is satisfied by the single flag.
        """
        skill = load_skill("build_reviewer")
        case1 = assemble_skill_prompt(skill, {}, design_system_active=True)
        case2 = assemble_skill_prompt(skill, {}, design_system_active=False)
        # case 3 is identical to case 2 from the flag's perspective
        case3 = assemble_skill_prompt(skill, {}, design_system_active=False)

        # Case 1: no frame constraints injection; DS precedence present
        assert _SLIDE_FRAME_CONSTRAINTS not in case1, "case 1 must not inject constraints"
        assert DESIGN_SYSTEM_PRECEDENCE in case1, "case 1 must inject DS precedence"

        # Cases 2 and 3: frame constraints injected; no DS precedence
        for i, case in enumerate((case2, case3), start=2):
            assert _SLIDE_FRAME_CONSTRAINTS in case, f"case {i} must inject constraints"
            assert DESIGN_SYSTEM_PRECEDENCE not in case, f"case {i} must not inject DS precedence"

    # --- Skill instructions always present ---

    def test_skill_instructions_in_assembled_prompt(self):
        for name in ["architect", "builder", "fixer"]:
            skill = load_skill(name)
            prompt = assemble_skill_prompt(skill, {}, design_system_active=False)
            assert skill.instructions in prompt, (
                f"Skill {name!r} instructions not found in assembled prompt"
            )
