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

import re

import pytest

from src.core.skills import load_skill
from src.core.skills.fixer import INSTRUCTIONS as FIXER_INSTRUCTIONS
from src.services.graph_definition_manifest import load_graph_v1_manifest


# ---------------------------------------------------------------------------
# build_reviewer — generated criteria block
# ---------------------------------------------------------------------------


class TestBuildReviewerProse:
    """The build_reviewer's criteria block is generated, not hand-written."""

    def test_template_shipped_colours_are_not_findings_in_v1_and_v2(self):
        """Deck-parity: without the rule the reviewer flagged the template's own
        coral labels and the fixer turned them navy.  A fresh install bootstraps
        the v1 composite; an upgraded reviewer runs the v2 target."""
        from src.core.skills.build_reviewer import BUILD_REVIEWER_AUTHORED_INSTRUCTIONS

        rule = "every colour that section_html itself ships"
        assert rule in load_skill("build_reviewer").instructions
        assert rule in BUILD_REVIEWER_AUTHORED_INSTRUCTIONS

    def test_build_reviewer_all_criterion_names_in_instructions(self):
        """Every CRITERIA name appears in the generated v2 criteria stage.

        ``load_skill(...).instructions`` is the frozen Graph Version 1 composite,
        so it cannot carry criteria added after v1 shipped.
        """
        from src.core.skills.build_reviewer import BUILD_REVIEWER_CRITERIA_STAGE
        from src.domain.finding import CRITERIA

        instructions = BUILD_REVIEWER_CRITERIA_STAGE
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


class TestBuildReviewerAuthoredPrefix:
    """The authored prefix tells the reviewer how to judge a bound slide.

    Each rule must be stated in ONE sentence, so a prefix that mentions the
    words in unrelated places does not pass.  The criteria lines are not part
    of the prefix; they stay generated from ``CRITERIA``.
    """

    @staticmethod
    def _sentences():
        import re

        from src.core.skills.build_reviewer import BUILD_REVIEWER_AUTHORED_PREFIX

        return [
            s.lower()
            for s in re.split(r"(?<=[.!?])\s+|\n+", BUILD_REVIEWER_AUTHORED_PREFIX)
            if s.strip()
        ]

    def _one_sentence_with(self, *patterns):
        import re

        return any(
            all(re.search(p, sentence) for p in patterns)
            for sentence in self._sentences()
        )

    def test_judge_the_cascade_not_class_names(self):
        assert self._one_sentence_with(
            r"\bcascade\b",
            r"class[ -]?names?",
            r"\b(not|never|rather than|instead of)\b",
        ), "prefix must say: judge the computed cascade, not class names"

    def test_compare_built_html_to_section_html_and_slide_type(self):
        assert self._one_sentence_with(
            r"compar",
            r"section_html",
            r"slide_type",
            r"\bhtml\b|built",
        ), (
            "prefix must tell the reviewer to compare the built HTML with "
            "section_html and slide_spec.slide_type"
        )

    def test_never_propose_a_replacement_colour_or_layout(self):
        assert self._one_sentence_with(
            r"\bnever\b",
            r"propos",
            r"replacement",
            r"colou?r",
            r"layout",
        ), "prefix must forbid proposing a replacement colour or layout"
        assert self._one_sentence_with(r"\bnever\b", r"propos", r"message"), (
            "the prohibition must be about the finding message"
        )

    def test_the_prefix_does_not_hand_write_criteria_lines(self):
        from src.core.skills.build_reviewer import BUILD_REVIEWER_AUTHORED_PREFIX
        from src.domain.finding import CRITERIA

        assert "CRITERIA:" not in BUILD_REVIEWER_AUTHORED_PREFIX
        for name in CRITERIA:
            assert f"{name} (" not in BUILD_REVIEWER_AUTHORED_PREFIX, name


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

    def test_builder_never_asks_for_a_missing_data_callout(self):
        """Deck-parity: "Add a callout explaining why the visualization is absent"
        put an inline-styled "No ... data was available" panel on 3 of 18 slides."""
        instructions = load_skill("builder").instructions
        assert "callout explaining why" not in instructions
        assert "Do not add a note, callout or caption about missing data" in instructions

    def test_builder_treats_sample_furniture_as_placeholder(self):
        """Deck-parity: the cover kept "Databricks · Brand Design" and every divider
        kept the template's Unity Catalog lockup whatever its topic."""
        assert "Sample furniture is placeholder too" in load_skill("builder").instructions

    def test_builder_adds_a_source_line_for_sourced_figures(self):
        """Genie One (Task 8): a slide that shows resolved_data.figures cites each
        figure's source field, and only that.  Both the skill body and the packaged
        v1 builder prompt carry the rule, so neither can drift from the other."""
        heading = "SOURCE LINE (only when the slide shows figures from resolved_data.figures):"
        no_invention = "never invent a source"
        instructions = load_skill("builder").instructions
        assert heading in instructions
        assert no_invention in instructions

        manifest = load_graph_v1_manifest()
        builder = next(d for d in manifest.definitions if d.agent_key == "builder")
        assert heading in builder.prompt_text
        assert no_invention in builder.prompt_text


class TestArchitectProse:
    """The architect plans a full deck from reusable sections (deck-parity loop)."""

    def test_architect_plans_a_full_length_deck_by_default(self):
        """Without it the architect planned 8 slides, one per template section,
        against the monolith's 19 for the same prompt."""
        instructions = load_skill("architect").instructions
        assert "14 to 20 slides" in instructions
        assert "reusable layouts, not a one-of-each menu" in instructions

    def test_architect_self_checks_each_binding_pair(self):
        """One mismatched slide_type/index pair rejects the whole plan."""
        assert (
            "its slide_type must equal the label of the template_sections entry"
            in load_skill("architect").instructions
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

    def test_fixer_does_not_require_a_div_slide_outer_root(self):
        """A bound template slide may be a <section> wrapping div.slide.

        Requiring an outer <div class="slide"> unwraps the bound section and
        drops the treatment the deck CSS paints.
        """
        body = re.sub(r"\s+", " ", FIXER_INSTRUCTIONS.replace("`", "")).strip().lower()
        assert re.search(
            r"<section>|outer root|keep (the |its )?(same |original )?(outer |root )",
            body,
        ), "fixer must allow a <section> outer root, not only <div class=\"slide\">"
        assert not re.search(
            r"return only the slide div:\s*<div class=.slide.>",
            body,
        ), "fixer still requires the outer root to be exactly <div class=\"slide\">"

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

    def test_manifest_fixer_prompt_is_the_skill_instructions(self):
        manifest = load_graph_v1_manifest()
        fixer = next(d for d in manifest.definitions if d.agent_key == "fixer")
        assert fixer.prompt_text == FIXER_INSTRUCTIONS


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
