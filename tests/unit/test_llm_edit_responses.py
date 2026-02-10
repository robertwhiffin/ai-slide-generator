"""Test handling of LLM edit responses.

These tests validate that mock LLM responses (simulating real edits like
chart recoloring, content rewording, etc.) can be correctly parsed and
integrated into existing decks without corruption.

The key invariant: Original_Deck + LLM_Edit_Response = Valid_Deck
"""

import pytest

from src.domain.slide import Slide
from src.domain.slide_deck import SlideDeck
from src.services.agent import SlideGeneratorAgent

from tests.validation import (
    validate_no_duplicate_canvas_ids,
    validate_html_structure,
    validate_javascript_syntax,
)
from tests.validation.canvas_validator import validate_deck_canvas_integrity
from tests.fixtures.html import (
    load_6_slide_deck,
    load_9_slide_deck,
    get_recolor_chart_response,
    get_reword_content_response,
    get_add_slide_response,
    get_consolidate_slides_response,
)
from tests.fixtures.html.edit_responses import (
    get_expand_slide_response,
    get_malformed_response_duplicate_canvas,
    get_malformed_response_syntax_error,
)
from tests.fixtures.css import load_databricks_theme


@pytest.fixture
def agent_stub() -> SlideGeneratorAgent:
    """Provide a SlideGeneratorAgent instance without running __init__."""
    return SlideGeneratorAgent.__new__(SlideGeneratorAgent)


@pytest.fixture
def deck_with_charts():
    """Create a deck with chart slides for testing."""
    html = load_6_slide_deck(css=load_databricks_theme())
    return SlideDeck.from_html_string(html)


class TestRecolorChartResponse:
    """Test handling of chart recolor edit responses."""

    def test_recolor_preserves_canvas_id(self, agent_stub, deck_with_charts):
        """Recolor response should preserve the original canvas ID."""
        # Find a chart slide
        chart_slide_idx = None
        original_canvas_id = None
        for i, slide in enumerate(deck_with_charts.slides):
            from src.utils.html_utils import extract_canvas_ids_from_html
            canvas_ids = extract_canvas_ids_from_html(slide.html)
            if canvas_ids:
                chart_slide_idx = i
                original_canvas_id = canvas_ids[0]
                break

        if chart_slide_idx is None:
            pytest.skip("No chart slides in test deck")

        # Get recolor response with same canvas ID
        response = get_recolor_chart_response(canvas_id=original_canvas_id)

        # Parse the response
        result = agent_stub._parse_slide_replacements(response, [chart_slide_idx])

        assert result["success"]
        assert result["replacement_count"] == 1

        # Canvas ID should be preserved
        assert original_canvas_id in result["canvas_ids"]

        # Replacement slide should have scripts with correct canvas ID
        replacement_slide = result["replacement_slides"][0]
        assert original_canvas_id in replacement_slide.scripts

    def test_recolor_produces_valid_javascript(self, agent_stub):
        """Recolor response should have valid JavaScript."""
        response = get_recolor_chart_response(canvas_id="testChart123")

        result = agent_stub._parse_slide_replacements(response, [0])
        assert result["success"]

        # Validate JavaScript in replacement
        replacement_slide = result["replacement_slides"][0]
        js_result = validate_javascript_syntax(replacement_slide.scripts)
        assert js_result.valid, f"JavaScript invalid: {js_result.errors}"


class TestRewordContentResponse:
    """Test handling of content rewording edit responses."""

    def test_reword_produces_valid_html(self, agent_stub):
        """Reword response should produce valid HTML."""
        response = get_reword_content_response(
            new_title="Updated Analysis",
            new_bullet_points=["Point 1", "Point 2", "Point 3"],
        )

        result = agent_stub._parse_slide_replacements(response, [0])

        assert result["success"]
        assert result["replacement_count"] == 1

        # Validate HTML structure
        replacement_slide = result["replacement_slides"][0]
        html_result = validate_html_structure(replacement_slide.html)
        assert html_result.valid, f"HTML invalid: {html_result.errors}"

    def test_reword_no_canvas_no_scripts(self, agent_stub):
        """Content-only reword should not have canvas or scripts."""
        response = get_reword_content_response()

        result = agent_stub._parse_slide_replacements(response, [0])

        assert result["success"]
        assert result["canvas_ids"] == []

        replacement_slide = result["replacement_slides"][0]
        # Scripts should be empty or very minimal
        assert "Chart" not in replacement_slide.scripts


class TestAddSlideResponse:
    """Test handling of add slide responses."""

    def test_add_slide_with_chart_preserves_integrity(self, agent_stub, deck_with_charts):
        """Adding a slide with a new chart should not create duplicates."""
        original_count = len(deck_with_charts.slides)

        # Get add response with unique canvas ID
        response = get_add_slide_response(canvas_id="brandNewChart999")

        result = agent_stub._parse_slide_replacements(response, [])

        assert result["success"]

        # New canvas ID should be unique
        assert "brandNewChart999" in result["canvas_ids"]

        # Verify no duplicates when integrated
        existing_canvas_ids = set()
        for slide in deck_with_charts.slides:
            from src.utils.html_utils import extract_canvas_ids_from_html
            existing_canvas_ids.update(extract_canvas_ids_from_html(slide.html))

        new_canvas_ids = set(result["canvas_ids"])
        duplicates = existing_canvas_ids & new_canvas_ids
        assert not duplicates, f"Canvas IDs would duplicate: {duplicates}"

    def test_add_content_slide_without_chart(self, agent_stub):
        """Adding a content-only slide should have no canvas."""
        response = get_add_slide_response(include_chart=False)

        result = agent_stub._parse_slide_replacements(response, [])

        assert result["success"]
        assert result["canvas_ids"] == []


class TestConsolidateResponse:
    """Test handling of consolidate (many-to-one) responses."""

    def test_consolidate_reduces_slide_count(self, agent_stub):
        """Consolidating 3 slides to 1 should have net_change of -2."""
        response = get_consolidate_slides_response()

        # Simulating consolidation of indices 2, 3, 4
        result = agent_stub._parse_slide_replacements(response, [2, 3, 4])

        assert result["success"]
        assert result["original_count"] == 3
        assert result["replacement_count"] == 1
        assert result["net_change"] == -2

    def test_consolidate_produces_valid_html(self, agent_stub):
        """Consolidated slide should be valid HTML."""
        response = get_consolidate_slides_response()

        result = agent_stub._parse_slide_replacements(response, [0, 1, 2])

        replacement_slide = result["replacement_slides"][0]
        html_result = validate_html_structure(replacement_slide.html)
        assert html_result.valid


class TestExpandResponse:
    """Test handling of expand (one-to-many) responses."""

    def test_expand_increases_slide_count(self, agent_stub):
        """Expanding 1 slide to 2 should have net_change of +1."""
        response = get_expand_slide_response()

        result = agent_stub._parse_slide_replacements(response, [0])

        assert result["success"]
        assert result["original_count"] == 1
        assert result["replacement_count"] == 2
        assert result["net_change"] == 1

    def test_expand_creates_unique_canvas_ids(self, agent_stub):
        """Expanded slides should each have unique canvas IDs."""
        response = get_expand_slide_response(
            canvas_id_1="expandedChart1",
            canvas_id_2="expandedChart2",
        )

        result = agent_stub._parse_slide_replacements(response, [0])

        assert result["success"]
        canvas_ids = result["canvas_ids"]

        # Should have 2 unique canvas IDs
        assert len(canvas_ids) == 2
        assert len(set(canvas_ids)) == 2  # All unique


class TestMalformedResponses:
    """Test that validation catches malformed LLM responses."""

    def test_duplicate_canvas_id_detected(self):
        """Duplicate canvas IDs should be detected by validation."""
        response = get_malformed_response_duplicate_canvas()

        # Direct HTML validation should catch duplicates
        result = validate_no_duplicate_canvas_ids(response)
        assert not result.valid
        assert "duplicate" in str(result.errors).lower()

    def test_javascript_syntax_error_detected(self):
        """JavaScript syntax errors should be detected."""
        response = get_malformed_response_syntax_error()

        # Extract scripts from response
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response, "html.parser")
        script_tag = soup.find("script")
        script_content = script_tag.string if script_tag else ""

        result = validate_javascript_syntax(script_content)
        assert not result.valid
        assert len(result.errors) > 0


class TestCSSInEditResponses:
    """Test CSS handling in edit responses."""

    def test_edit_response_css_extracted(self, agent_stub):
        """CSS in edit response should be extracted."""
        response = get_recolor_chart_response(canvas_id="test")

        result = agent_stub._parse_slide_replacements(response, [0])

        css = result.get("replacement_css", "")
        assert len(css) > 0
        assert ".chart-container" in css

    def test_edit_css_is_valid(self, agent_stub):
        """Extracted CSS should be valid."""
        response = get_consolidate_slides_response()

        result = agent_stub._parse_slide_replacements(response, [0, 1, 2])

        css = result.get("replacement_css", "")
        from tests.validation import validate_css_syntax
        css_result = validate_css_syntax(css)
        assert css_result.valid, f"CSS invalid: {css_result.errors}"


class TestEdgeCase:
    """Test edge cases in edit response handling."""

    def test_empty_response_handled(self, agent_stub):
        """Empty response should be handled gracefully."""
        from src.services.agent import AgentError

        with pytest.raises(AgentError):
            agent_stub._parse_slide_replacements("", [0])

    def test_no_slide_divs_handled(self, agent_stub):
        """Response without .slide divs should error."""
        from src.services.agent import AgentError

        response = "<div>Not a slide</div><p>Some content</p>"
        with pytest.raises(AgentError, match="No slide divs"):
            agent_stub._parse_slide_replacements(response, [0])

    def test_script_without_canvas_handled(self, agent_stub):
        """Script referencing non-existent canvas should warn/error."""
        response = '''
        <div class="slide">
            <h2>No Canvas Here</h2>
        </div>
        <script>
        // This references a canvas that doesn't exist
        const ctx = document.getElementById('nonExistentCanvas');
        if (ctx) { new Chart(ctx, {}); }
        </script>
        '''

        result = agent_stub._parse_slide_replacements(response, [0])

        # Should succeed but with orphan script reference
        assert result["success"]
        # Script should still be captured
        assert len(result["replacement_slides"]) == 1
