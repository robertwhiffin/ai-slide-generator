"""Tests for prompt_modules: modular prompt assembly for generation vs editing."""

import pytest

from src.core.prompt_modules import (
    BASE_PROMPT,
    CHART_JS_RULES,
    DATA_ANALYSIS_GUIDELINES,
    EDITING_OUTPUT_FORMAT,
    EDITING_RULES,
    GENERATION_GOALS,
    HTML_OUTPUT_FORMAT,
    IMAGE_SUPPORT,
    PRESENTATION_GUIDELINES,
    SLIDE_GUIDELINES,
    build_editing_system_prompt,
    build_generation_system_prompt,
)

STUB_STYLE = "SLIDE VISUAL STYLE:\nTest style block"


class TestBuildGenerationSystemPrompt:
    def test_includes_generation_blocks_excludes_editing(self):
        """Generation prompt contains generation rules and HTML output
        format, and does NOT contain editing rules or editing output format."""
        result = build_generation_system_prompt(slide_style=STUB_STYLE)

        assert GENERATION_GOALS in result
        assert PRESENTATION_GUIDELINES in result
        assert "<!DOCTYPE html>" in result
        assert HTML_OUTPUT_FORMAT in result

        assert EDITING_RULES not in result
        assert EDITING_OUTPUT_FORMAT not in result

    def test_includes_shared_blocks(self):
        """Generation prompt includes all shared blocks."""
        result = build_generation_system_prompt(slide_style=STUB_STYLE)

        assert BASE_PROMPT in result
        assert DATA_ANALYSIS_GUIDELINES in result
        assert SLIDE_GUIDELINES in result
        assert CHART_JS_RULES in result
        assert IMAGE_SUPPORT in result
        assert STUB_STYLE in result

    def test_deck_prompt_optional(self):
        """Deck prompt is included only when provided."""
        without = build_generation_system_prompt(slide_style=STUB_STYLE)
        assert "PRESENTATION CONTEXT" not in without

        with_dp = build_generation_system_prompt(
            slide_style=STUB_STYLE, deck_prompt="Quarterly review"
        )
        assert "PRESENTATION CONTEXT:\nQuarterly review" in with_dp

    def test_image_guidelines_optional(self):
        """Image guidelines appear only when provided."""
        without = build_generation_system_prompt(slide_style=STUB_STYLE)
        assert "IMAGE GUIDELINES" not in without

        with_ig = build_generation_system_prompt(
            slide_style=STUB_STYLE, image_guidelines="Use logo.png"
        )
        assert "IMAGE GUIDELINES" in with_ig
        assert "Use logo.png" in with_ig


class TestBuildEditingSystemPrompt:
    def test_includes_editing_blocks_excludes_generation(self):
        """Editing prompt contains editing rules and editing output format,
        and does NOT contain generation-only blocks."""
        result = build_editing_system_prompt(slide_style=STUB_STYLE)

        assert EDITING_RULES in result
        assert EDITING_OUTPUT_FORMAT in result
        assert "slide-context" in result

        assert GENERATION_GOALS not in result
        assert PRESENTATION_GUIDELINES not in result
        # Generation-only HTML_OUTPUT_FORMAT should be absent; use a
        # generation-specific phrase to avoid false positives from the
        # editing output format (which mentions <!DOCTYPE html> in a
        # "do NOT" context).
        assert "Start directly with: <!DOCTYPE html>" not in result
        assert "Do NOT return a full HTML document" in result

    def test_includes_shared_blocks(self):
        """Editing prompt includes all shared blocks."""
        result = build_editing_system_prompt(slide_style=STUB_STYLE)

        assert BASE_PROMPT in result
        assert DATA_ANALYSIS_GUIDELINES in result
        assert SLIDE_GUIDELINES in result
        assert CHART_JS_RULES in result
        assert IMAGE_SUPPORT in result
        assert STUB_STYLE in result

    def test_deck_prompt_optional(self):
        """Deck prompt is included only when provided."""
        without = build_editing_system_prompt(slide_style=STUB_STYLE)
        assert "PRESENTATION CONTEXT" not in without

        with_dp = build_editing_system_prompt(
            slide_style=STUB_STYLE, deck_prompt="Sales deck"
        )
        assert "PRESENTATION CONTEXT:\nSales deck" in with_dp

    def test_image_guidelines_optional(self):
        """Image guidelines appear only when provided."""
        without = build_editing_system_prompt(slide_style=STUB_STYLE)
        assert "IMAGE GUIDELINES" not in without

        with_ig = build_editing_system_prompt(
            slide_style=STUB_STYLE, image_guidelines="Brand images only"
        )
        assert "IMAGE GUIDELINES" in with_ig
        assert "Brand images only" in with_ig


class TestModeExclusivity:
    def test_generation_and_editing_differ(self):
        """Generation and editing prompts are materially different."""
        gen = build_generation_system_prompt(slide_style=STUB_STYLE)
        edit = build_editing_system_prompt(slide_style=STUB_STYLE)

        assert gen != edit
        # Generation is longer because it includes full HTML doc template
        assert len(gen) > len(edit) * 0.5
