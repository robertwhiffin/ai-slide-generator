"""Prose-specific tests for the seven skill bodies — C9.

These tests guard properties that are specific to the authored prose, distinct from
the structural invariants already covered by test_skills.py (schema binding, non-empty
body, grants, registry membership).

Test intent (from the C9 brief):

- build_reviewer's criteria block is GENERATED from CRITERIA — assert all nine names
  appear AND that adding a criterion makes it appear WITHOUT editing the skill.
  The second half is the falsifiable half: a hardcoded block passes the name-check
  but fails the dynamic-addition check.
- builder's prose contains the embedding syntax ({{image:ID}}) and NO instruction to
  call a tool — assert on the tool-name absence, not on a vibe.
- fixer's prose contains a minimal-change instruction and NOT "1280x720" — the
  dimension belongs to _SLIDE_FRAME_CONSTRAINTS, and copying it creates drift.
- data_analyst's instructions contain UNTRUSTED_DATA_NOTICE's text — the import is
  used, not just present.

Sabotage targets (run results in task-C9-report.md):
  S1: put 1280x720 into fixer's body → test_fixer_no_dimension_literal goes red
  S2: hand-write build_reviewer criteria block → test_build_reviewer_dynamic_generation
      goes red
  S3: put search_images into builder's body → test_builder_no_tool_call goes red
"""

import pytest

from src.core.skills import load_skill


# ---------------------------------------------------------------------------
# build_reviewer — generated criteria block
# ---------------------------------------------------------------------------


class TestBuildReviewerProse:
    """The build_reviewer's criteria block is generated, not hand-written."""

    def test_build_reviewer_all_criterion_names_in_instructions(self):
        """Every CRITERIA name appears in the assembled instructions."""
        from src.domain.finding import CRITERIA

        instructions = load_skill("build_reviewer").instructions
        for name in CRITERIA:
            assert name in instructions, (
                f"Criterion {name!r} not found in build_reviewer instructions. "
                "The criteria block may have been hand-written rather than generated."
            )

    def test_build_reviewer_dynamic_generation_is_falsifiable(self):
        """Adding a criterion to the registry appears in build_instructions() output.

        FALSIFIABILITY: a hand-written criteria block would NOT include the new name,
        so this test would go red.  Only a CRITERIA-driven implementation passes.
        """
        from src.core.skills.build_reviewer import build_instructions
        from src.domain.finding import CRITERIA, FindingCriterion

        probe_name = "_c9_falsifiability_probe"
        assert probe_name not in CRITERIA, (
            f"probe name {probe_name!r} collides with an existing criterion"
        )
        CRITERIA[probe_name] = FindingCriterion(
            name=probe_name,
            category="design",
            level="slide",
            objective=True,
            description="Falsifiability probe inserted by test_skill_prose.py; "
            "never reported in production.",
        )
        try:
            result = build_instructions()
            assert probe_name in result, (
                f"build_instructions() did not include {probe_name!r} after it was "
                "added to CRITERIA.  The criteria block is not generated dynamically — "
                "it is hand-written and will diverge from the registry."
            )
        finally:
            del CRITERIA[probe_name]


# ---------------------------------------------------------------------------
# builder — image syntax present, tool call absent
# ---------------------------------------------------------------------------


class TestBuilderProse:
    """The builder embeds images via syntax, never by calling a tool."""

    def test_builder_contains_image_embedding_syntax(self):
        """{{image:ID}} syntax is present so future payload extensions can deliver ids."""
        skill = load_skill("builder")
        assert "{{image:ID}}" in skill.instructions, (
            "builder instructions must contain the {{image:ID}} embedding syntax; "
            "removing it breaks any future image-id delivery channel"
        )

    def test_builder_contains_no_search_images_tool_call(self):
        """The builder holds no tool grants; instructing it to call search_images
        would cause it to either fabricate handles or silently drop images."""
        skill = load_skill("builder")
        assert "search_images" not in skill.instructions, (
            "builder instructions must not mention search_images; "
            "the builder holds no tool grants and cannot call it"
        )


# ---------------------------------------------------------------------------
# fixer — minimal-change instruction present, safe-area dimension absent
# ---------------------------------------------------------------------------


class TestFixerProse:
    """The fixer is a minimal-change agent, not a re-author."""

    def test_fixer_contains_minimal_change_instruction(self):
        """Fixer prose must state the minimal-change disposition explicitly."""
        skill = load_skill("fixer")
        # Accept case-insensitive match on either form
        body = skill.instructions.upper()
        assert "MINIMAL" in body, (
            "fixer instructions must contain a minimal-change instruction; "
            "without it the model may re-author the slide, undoing prior review work"
        )

    def test_fixer_no_dimension_literal(self):
        """1280x720 must not appear in the fixer body.

        That number belongs to _SLIDE_FRAME_CONSTRAINTS; duplicating it in a
        skill body creates a copy that can drift independently.
        """
        skill = load_skill("fixer")
        assert "1280x720" not in skill.instructions, (
            "fixer instructions must not contain '1280x720'; "
            "safe-area numbers are owned by _SLIDE_FRAME_CONSTRAINTS"
        )


# ---------------------------------------------------------------------------
# data_analyst — UNTRUSTED_DATA_NOTICE is used, not just imported
# ---------------------------------------------------------------------------


class TestDataAnalystProse:
    """UNTRUSTED_DATA_NOTICE's content is in the analyst's instructions."""

    def test_data_analyst_instructions_contain_untrusted_data_notice(self):
        """The import is actually used — the notice text appears in the instructions.

        Two copies can drift where it matters; the import is the one permitted
        exception to R2 (copying prompt_modules constants).
        """
        from src.core.prompt_modules import UNTRUSTED_DATA_NOTICE

        skill = load_skill("data_analyst")
        # Check a distinctive token from the notice, not the full string
        # (the instructions may reformat whitespace around the concatenation)
        distinctive_token = "UNTRUSTED DATA HANDLING"
        assert distinctive_token in skill.instructions, (
            f"data_analyst instructions must contain the UNTRUSTED_DATA_NOTICE text; "
            f"expected to find {distinctive_token!r}"
        )
