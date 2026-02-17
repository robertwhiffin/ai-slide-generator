"""Tests for prompt default constants.

Verifies the refactored PPTX and new Google Slides prompt modules
export the expected constants with correct structure.
"""

from src.services.pptx_prompts_defaults import (
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_USER_PROMPT_TEMPLATE,
    DEFAULT_MULTI_SLIDE_SYSTEM_PROMPT,
    DEFAULT_MULTI_SLIDE_USER_PROMPT,
)
from src.services.google_slides_prompts_defaults import (
    DEFAULT_GSLIDES_SYSTEM_PROMPT,
    DEFAULT_GSLIDES_USER_PROMPT,
    DEFAULT_GSLIDES_SINGLE_SYSTEM_PROMPT,
    DEFAULT_GSLIDES_SINGLE_USER_PROMPT,
)


class TestPptxPrompts:
    """Verify PPTX prompt constants exist and contain key instructions."""

    def test_single_slide_prompts(self):
        """Single-slide system + user prompt templates are valid."""
        assert isinstance(DEFAULT_SYSTEM_PROMPT, str)
        assert "convert_to_pptx" in DEFAULT_SYSTEM_PROMPT
        assert "{html_content}" in DEFAULT_USER_PROMPT_TEMPLATE
        assert "{screenshot_note}" in DEFAULT_USER_PROMPT_TEMPLATE

    def test_multi_slide_prompts(self):
        """Multi-slide system + user prompt templates are valid."""
        assert isinstance(DEFAULT_MULTI_SLIDE_SYSTEM_PROMPT, str)
        assert "add_slide_to_presentation" in DEFAULT_MULTI_SLIDE_SYSTEM_PROMPT
        assert "{html_content}" in DEFAULT_MULTI_SLIDE_USER_PROMPT

    def test_shared_rules_included(self):
        """Shared layout rules are embedded in both system prompts."""
        for prompt in (DEFAULT_SYSTEM_PROMPT, DEFAULT_MULTI_SLIDE_SYSTEM_PROMPT):
            assert "OVERFLOW PREVENTION" in prompt
            assert "FONT SIZE GUIDE" in prompt
            assert "METRIC CARDS" in prompt
            assert "TABLES" in prompt


class TestGoogleSlidesPrompts:
    """Verify Google Slides prompt constants exist and contain key instructions."""

    def test_multi_slide_prompts(self):
        """Multi-slide system + user prompt templates are valid."""
        assert isinstance(DEFAULT_GSLIDES_SYSTEM_PROMPT, str)
        assert "add_slide_to_presentation" in DEFAULT_GSLIDES_SYSTEM_PROMPT
        assert "{html_content}" in DEFAULT_GSLIDES_USER_PROMPT
        assert "{screenshot_note}" in DEFAULT_GSLIDES_USER_PROMPT

    def test_single_slide_prompts(self):
        """Single-slide system + user prompt templates are valid."""
        assert isinstance(DEFAULT_GSLIDES_SINGLE_SYSTEM_PROMPT, str)
        assert "convert_to_google_slides" in DEFAULT_GSLIDES_SINGLE_SYSTEM_PROMPT
        assert "{html_content}" in DEFAULT_GSLIDES_SINGLE_USER_PROMPT

    def test_shared_rules_included(self):
        """Shared rules are embedded in both Google Slides system prompts."""
        for prompt in (DEFAULT_GSLIDES_SYSTEM_PROMPT, DEFAULT_GSLIDES_SINGLE_SYSTEM_PROMPT):
            assert "OVERFLOW PREVENTION" in prompt
            assert "FONT SIZE GUIDE" in prompt
            assert "METRIC CARDS" in prompt
            assert "API PATTERNS" in prompt

    def test_google_slides_specific_content(self):
        """Google Slides prompts reference Slides API patterns, not python-pptx."""
        assert "batchUpdate" in DEFAULT_GSLIDES_SYSTEM_PROMPT
        assert "createShape" in DEFAULT_GSLIDES_SYSTEM_PROMPT
        assert "emu(" in DEFAULT_GSLIDES_SYSTEM_PROMPT
        # Should NOT reference python-pptx concepts
        assert "Presentation()" not in DEFAULT_GSLIDES_SYSTEM_PROMPT
        assert "slide_layouts" not in DEFAULT_GSLIDES_SYSTEM_PROMPT
