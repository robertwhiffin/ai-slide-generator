"""Tests for the skill registry — C3.

Covers:
- All seven skills load and bind to their OUTPUT_SCHEMAS entry
- Each declares a version >= 1 and a non-empty instructions body
- data_analyst declares non-empty tool_grants; all others declare []
- list_skills() returns all seven names
- Unknown skill name raises KeyError
- No skill body contains the safe-area literals owned by _SLIDE_FRAME_CONSTRAINTS

Sabotage targets used during development (results in task-C3-report.md):
- S3: hardcode 88px into architect instructions → test_no_skill_body_contains_safe_area_literals red
- S4: give builder non-empty tool_grants → test_non_analyst_skills_declare_empty_tool_grants red
"""

import pytest

from src.core.skills import Skill, list_skills, load_skill
from src.domain.skill_io import OUTPUT_SCHEMAS

SEVEN_SKILL_NAMES = [
    "architect",
    "data_analyst",
    "builder",
    "fixer",
    "build_reviewer",
    "fix_reviewer",
    "deck_reviewer",
]

# Safe-area literals owned by _SLIDE_FRAME_CONSTRAINTS.  No skill body may
# contain them — that number would diverge independently of the compiler's
# copy, which is the defect COMPILER_VERSION exists to prevent.
_SAFE_AREA_LITERALS = ["88px", "72px", "56px", "1280x720"]


class TestSkillRegistry:
    """Skills load, bind, and satisfy their invariants."""

    def test_all_seven_skills_load(self):
        for name in SEVEN_SKILL_NAMES:
            skill = load_skill(name)
            assert isinstance(skill, Skill), f"{name!r} did not return a Skill instance"

    def test_output_schema_matches_domain_registry(self):
        for name in SEVEN_SKILL_NAMES:
            skill = load_skill(name)
            assert skill.output_schema is OUTPUT_SCHEMAS[name], (
                f"{name!r}.output_schema is {skill.output_schema!r}, "
                f"expected {OUTPUT_SCHEMAS[name]!r}"
            )

    def test_each_skill_has_positive_version(self):
        for name in SEVEN_SKILL_NAMES:
            skill = load_skill(name)
            assert isinstance(skill.version, int), f"{name!r}.version is not int"
            assert skill.version >= 1, f"{name!r}.version < 1"

    def test_each_skill_has_non_empty_instructions(self):
        """An empty prompt produces garbage that still parses (§15)."""
        for name in SEVEN_SKILL_NAMES:
            skill = load_skill(name)
            assert skill.instructions, f"Skill {name!r} has empty instructions"

    def test_list_skills_returns_all_seven(self):
        names = list_skills()
        assert set(names) == set(SEVEN_SKILL_NAMES), (
            f"list_skills() returned {sorted(names)!r}, "
            f"expected {sorted(SEVEN_SKILL_NAMES)!r}"
        )
        assert len(names) == 7, f"Expected 7 skills, got {len(names)}"

    def test_unknown_skill_raises_key_error(self):
        with pytest.raises(KeyError, match="unknown_skill"):
            load_skill("unknown_skill")

    def test_data_analyst_declares_non_empty_tool_grants(self):
        """§16 / Ruling C-11: analyst is the sole OBO boundary (§5.2.2)."""
        skill = load_skill("data_analyst")
        assert skill.tool_grants, "data_analyst must declare non-empty tool_grants (§5.2.2)"

    def test_non_analyst_skills_declare_empty_tool_grants(self):
        """§16 / Ruling C-11: architect and all reviewers/builders declare []."""
        non_analyst = [n for n in SEVEN_SKILL_NAMES if n != "data_analyst"]
        for name in non_analyst:
            skill = load_skill(name)
            assert skill.tool_grants == [], (
                f"{name!r} must declare [] tool_grants (§16 / Ruling C-11); "
                f"got {skill.tool_grants!r}"
            )

    def test_no_skill_body_contains_safe_area_literals(self):
        """Safe-area numbers are owned by _SLIDE_FRAME_CONSTRAINTS.

        Retyping them in a skill body creates a copy that diverges independently
        of the compiler's, which is the exact hazard COMPILER_VERSION exists
        to prevent.
        """
        for name in SEVEN_SKILL_NAMES:
            skill = load_skill(name)
            for literal in _SAFE_AREA_LITERALS:
                assert literal not in skill.instructions, (
                    f"Skill {name!r} instructions contain {literal!r}; "
                    "safe-area numbers must come only from _SLIDE_FRAME_CONSTRAINTS"
                )

    def test_skill_is_frozen(self):
        """frozen=True: callers cannot mutate a skill after load."""
        skill = load_skill("architect")
        with pytest.raises((AttributeError, TypeError)):
            skill.version = 99  # type: ignore[misc]
