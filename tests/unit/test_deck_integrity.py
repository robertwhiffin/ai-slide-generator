"""Core deck integrity tests.

These tests validate the fundamental invariant:
    Original_Deck + Operation(add|delete|edit|reorder) = Valid_Renderable_Deck

Each test ensures that after an operation, the deck:
1. Parses without error
2. Has no duplicate canvas IDs
3. Has valid JavaScript syntax
4. Has valid CSS
"""

import pytest

from src.domain.slide import Slide
from src.domain.slide_deck import SlideDeck

from tests.validation import (
    validate_canvas_ids,
    validate_no_duplicate_canvas_ids,
    validate_html_structure,
    validate_slide_structure,
    validate_javascript_syntax,
    validate_css_syntax,
)
from tests.validation.canvas_validator import validate_deck_canvas_integrity
from tests.fixtures.html import (
    load_3_slide_deck,
    load_6_slide_deck,
    load_9_slide_deck,
    load_12_slide_deck,
    generate_chart_slide,
    generate_content_slide,
)
from tests.fixtures.css import load_databricks_theme, load_minimal_theme


class TestDeckParsing:
    """Test that decks parse correctly across different sizes and themes."""

    @pytest.mark.parametrize("slide_count,loader", [
        (3, load_3_slide_deck),
        (6, load_6_slide_deck),
        (9, load_9_slide_deck),
        (12, load_12_slide_deck),
    ])
    def test_parse_deck_various_sizes(self, slide_count, loader):
        """Decks of various sizes should parse without error."""
        html = loader()
        deck = SlideDeck.from_html_string(html)

        assert len(deck.slides) >= 1
        assert deck.title is not None

        # Validate structure
        result = validate_slide_structure(html)
        assert result.valid, f"Structure validation failed: {result.errors}"

    @pytest.mark.parametrize("css_loader,theme_name", [
        (load_databricks_theme, "databricks"),
        (load_minimal_theme, "minimal"),
        (lambda: "", "no_css"),
    ])
    def test_parse_deck_various_themes(self, css_loader, theme_name):
        """Decks should parse correctly regardless of CSS theme."""
        css = css_loader()
        html = load_6_slide_deck(css=css)
        deck = SlideDeck.from_html_string(html)

        assert len(deck.slides) >= 1

        # Validate CSS if present
        if css:
            css_result = validate_css_syntax(css)
            assert css_result.valid, f"CSS validation failed: {css_result.errors}"

    def test_parse_deck_with_charts_extracts_canvas_ids(self):
        """Parsing should correctly extract canvas IDs and associate scripts."""
        html = load_6_slide_deck()
        deck = SlideDeck.from_html_string(html)

        # Check canvas integrity
        result = validate_deck_canvas_integrity(deck)
        assert result.valid, f"Canvas integrity failed: {result.errors}"

        # There should be chart slides with canvas IDs
        canvas_count = result.details.get("total_canvas_count", 0)
        assert canvas_count >= 1, "Expected at least one canvas in 6-slide deck"


class TestDeleteOperation:
    """Test that delete operations preserve deck integrity."""

    @pytest.mark.parametrize("slide_count,loader", [
        (6, load_6_slide_deck),
        (9, load_9_slide_deck),
        (12, load_12_slide_deck),
    ])
    def test_delete_preserves_integrity(self, slide_count, loader):
        """Deleting a slide should not corrupt the deck."""
        html = loader()
        deck = SlideDeck.from_html_string(html)
        original_count = len(deck.slides)

        # Delete middle slide
        middle_idx = len(deck.slides) // 2
        deck.remove_slide(middle_idx)

        # Verify count decreased
        assert len(deck.slides) == original_count - 1

        # Validate integrity after delete
        knitted = deck.knit()
        assert validate_html_structure(knitted).valid
        assert validate_slide_structure(knitted).valid
        assert validate_no_duplicate_canvas_ids(knitted).valid

        # Validate scripts
        if deck.scripts:
            assert validate_javascript_syntax(deck.scripts).valid

    def test_delete_chart_slide_removes_script(self):
        """Deleting a chart slide should also remove its script."""
        html = load_6_slide_deck()
        deck = SlideDeck.from_html_string(html)

        # Find a slide with scripts
        chart_slide_idx = None
        for i, slide in enumerate(deck.slides):
            if slide.scripts and "Chart" in slide.scripts:
                chart_slide_idx = i
                break

        if chart_slide_idx is not None:
            # Get canvas IDs before delete
            from src.utils.html_utils import extract_canvas_ids_from_html
            canvas_ids_before = extract_canvas_ids_from_html(deck[chart_slide_idx].html)

            # Delete the chart slide
            deck.remove_slide(chart_slide_idx)

            # Verify scripts no longer reference those canvas IDs
            for canvas_id in canvas_ids_before:
                assert canvas_id not in deck.scripts

            # Validate final integrity
            result = validate_deck_canvas_integrity(deck)
            assert result.valid, f"Canvas integrity failed after delete: {result.errors}"

    def test_delete_all_slides_except_one(self):
        """Deleting until one slide remains should still be valid."""
        html = load_6_slide_deck()
        deck = SlideDeck.from_html_string(html)

        # Delete all but first slide
        while len(deck.slides) > 1:
            deck.remove_slide(1)

        assert len(deck.slides) == 1

        knitted = deck.knit()
        assert validate_html_structure(knitted).valid
        assert validate_slide_structure(knitted).valid


class TestAddOperation:
    """Test that add operations preserve deck integrity."""

    def test_add_content_slide_preserves_integrity(self):
        """Adding a content slide should not corrupt the deck."""
        html = load_6_slide_deck()
        deck = SlideDeck.from_html_string(html)
        original_count = len(deck.slides)

        # Create and add new slide
        new_slide = Slide(
            html=generate_content_slide(title="New Slide", slide_number=99),
            slide_id="new_slide",
        )
        deck.append_slide(new_slide)

        # Verify count increased
        assert len(deck.slides) == original_count + 1

        # Validate integrity
        knitted = deck.knit()
        assert validate_html_structure(knitted).valid
        assert validate_slide_structure(knitted).valid
        assert validate_no_duplicate_canvas_ids(knitted).valid

    def test_add_chart_slide_preserves_integrity(self):
        """Adding a chart slide should correctly integrate scripts."""
        html = load_6_slide_deck()
        deck = SlideDeck.from_html_string(html)

        # Generate chart slide with unique ID
        slide_html, script_js = generate_chart_slide(
            title="New Chart",
            canvas_id="newUniqueChart123",
        )

        new_slide = Slide(
            html=slide_html,
            slide_id="new_chart_slide",
            scripts=script_js,
        )
        deck.append_slide(new_slide)

        # Validate canvas integrity
        result = validate_deck_canvas_integrity(deck)
        assert result.valid, f"Canvas integrity failed: {result.errors}"

        # Verify new canvas ID is in scripts
        assert "newUniqueChart123" in deck.scripts

        # Validate JavaScript syntax
        js_result = validate_javascript_syntax(deck.scripts)
        assert js_result.valid, f"JavaScript validation failed: {js_result.errors}"

    def test_insert_slide_at_position_preserves_integrity(self):
        """Inserting at a specific position should not corrupt the deck."""
        html = load_6_slide_deck()
        deck = SlideDeck.from_html_string(html)

        # Insert at position 2
        new_slide = Slide(
            html=generate_content_slide(title="Inserted Slide"),
            slide_id="inserted",
        )
        deck.insert_slide(new_slide, position=2)

        # Validate integrity
        knitted = deck.knit()
        assert validate_html_structure(knitted).valid
        assert validate_slide_structure(knitted).valid
        assert validate_no_duplicate_canvas_ids(knitted).valid


class TestEditOperation:
    """Test that edit operations preserve deck integrity."""

    def test_edit_slide_html_preserves_integrity(self):
        """Directly editing slide HTML should preserve deck integrity."""
        html = load_6_slide_deck()
        deck = SlideDeck.from_html_string(html)

        # Edit a non-chart slide's HTML
        for i, slide in enumerate(deck.slides):
            if not slide.scripts:  # Non-chart slide
                # Modify the HTML
                original_html = slide.html
                slide.html = original_html.replace("Key", "Updated")
                break

        # Validate integrity
        knitted = deck.knit()
        assert validate_html_structure(knitted).valid
        assert validate_slide_structure(knitted).valid

    def test_edit_slide_scripts_preserves_integrity(self):
        """Editing slide scripts should preserve canvas associations."""
        html = load_6_slide_deck()
        deck = SlideDeck.from_html_string(html)

        # Find chart slide and modify its script (valid color change)
        for i, slide in enumerate(deck.slides):
            if slide.scripts and "Chart" in slide.scripts:
                # Change colors in script - replace one color array with another
                slide.scripts = slide.scripts.replace(
                    "'#FF3621'",
                    "'#0000FF'"  # Change red to blue
                )
                break

        # Validate JavaScript syntax
        js_result = validate_javascript_syntax(deck.scripts)
        assert js_result.valid, f"JavaScript validation failed: {js_result.errors}"

        # Validate canvas integrity
        result = validate_deck_canvas_integrity(deck)
        assert result.valid, f"Canvas integrity failed: {result.errors}"


class TestReorderOperation:
    """Test that reorder operations preserve deck integrity."""

    def test_move_slide_preserves_integrity(self):
        """Moving a slide should preserve all content and associations."""
        html = load_6_slide_deck()
        deck = SlideDeck.from_html_string(html)

        # Get canvas IDs before reorder
        from src.utils.html_utils import extract_canvas_ids_from_html
        canvas_ids_before = set()
        for slide in deck.slides:
            canvas_ids_before.update(extract_canvas_ids_from_html(slide.html))

        # Move first content slide to end
        deck.move_slide(1, len(deck.slides) - 1)

        # Get canvas IDs after reorder
        canvas_ids_after = set()
        for slide in deck.slides:
            canvas_ids_after.update(extract_canvas_ids_from_html(slide.html))

        # Canvas IDs should be preserved
        assert canvas_ids_before == canvas_ids_after

        # Validate integrity
        knitted = deck.knit()
        assert validate_html_structure(knitted).valid
        assert validate_no_duplicate_canvas_ids(knitted).valid

        # Validate scripts still work
        if deck.scripts:
            js_result = validate_javascript_syntax(deck.scripts)
            assert js_result.valid

    def test_swap_slides_preserves_integrity(self):
        """Swapping slides should preserve all associations."""
        html = load_6_slide_deck()
        deck = SlideDeck.from_html_string(html)

        # Get slide contents before swap
        slide_1_html = deck.slides[1].html
        slide_3_html = deck.slides[3].html

        # Swap slides 1 and 3
        deck.swap_slides(1, 3)

        # Verify swap happened
        assert deck.slides[1].html == slide_3_html
        assert deck.slides[3].html == slide_1_html

        # Validate integrity
        result = validate_deck_canvas_integrity(deck)
        assert result.valid, f"Canvas integrity failed after swap: {result.errors}"

    def test_multiple_reorders_preserve_integrity(self):
        """Multiple reorder operations should not accumulate corruption."""
        html = load_9_slide_deck()
        deck = SlideDeck.from_html_string(html)

        # Perform multiple reorders
        for _ in range(5):
            deck.move_slide(0, len(deck.slides) - 1)
            deck.swap_slides(1, 2)

        # Validate final integrity
        knitted = deck.knit()
        assert validate_html_structure(knitted).valid
        assert validate_slide_structure(knitted).valid
        assert validate_no_duplicate_canvas_ids(knitted).valid

        result = validate_deck_canvas_integrity(deck)
        assert result.valid, f"Canvas integrity failed after multiple reorders: {result.errors}"


class TestCSSMerging:
    """Test that CSS merging preserves validity."""

    def test_update_css_preserves_validity(self):
        """Updating CSS should produce valid merged result."""
        html = load_6_slide_deck(css=load_databricks_theme())
        deck = SlideDeck.from_html_string(html)

        # Update with new CSS
        new_css = '''
        .slide { background: #f0f0f0; }
        .new-class { color: blue; }
        '''
        deck.update_css(new_css)

        # Validate CSS
        css_result = validate_css_syntax(deck.css)
        assert css_result.valid, f"CSS validation failed: {css_result.errors}"

    def test_css_merge_preserves_existing_rules(self):
        """CSS merge should preserve rules not in replacement."""
        from tests.fixtures.css import load_databricks_theme

        original_css = load_databricks_theme()
        html = load_6_slide_deck(css=original_css)
        deck = SlideDeck.from_html_string(html)

        # Update just one rule
        deck.update_css(".slide { padding: 100px; }")

        # Original rules should still be present
        assert ".title-slide" in deck.css or "title-slide" in deck.css
        # Updated rule should be applied
        assert "padding: 100px" in deck.css or "padding:100px" in deck.css


class TestKnitOutput:
    """Test that knit produces valid complete HTML documents."""

    @pytest.mark.parametrize("loader", [
        load_3_slide_deck,
        load_6_slide_deck,
        load_9_slide_deck,
        load_12_slide_deck,
    ])
    def test_knit_produces_valid_html(self, loader):
        """Knitted output should be valid HTML."""
        html = loader()
        deck = SlideDeck.from_html_string(html)
        knitted = deck.knit()

        # Validate structure
        result = validate_html_structure(knitted)
        assert result.valid, f"Knit output invalid: {result.errors}"

        # Should have DOCTYPE
        assert "<!DOCTYPE html>" in knitted

        # Should have Chart.js CDN
        assert "chart.js" in knitted.lower()

    def test_knit_aggregates_scripts_correctly(self):
        """Knit should aggregate all slide scripts into one script block."""
        html = load_6_slide_deck()
        deck = SlideDeck.from_html_string(html)
        knitted = deck.knit()

        # Count script tags in knitted output
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(knitted, "html.parser")
        script_tags = soup.find_all("script", src=False)

        # Should have exactly one inline script tag (plus external CDN)
        inline_scripts = [s for s in script_tags if s.string and s.string.strip()]
        assert len(inline_scripts) <= 1, "Should aggregate scripts into one block"

    def test_render_single_slide_valid(self):
        """Rendering a single slide should produce valid HTML."""
        html = load_6_slide_deck()
        deck = SlideDeck.from_html_string(html)

        # Render just the first slide
        single = deck.render_slide(0)

        # Should be valid HTML
        result = validate_html_structure(single)
        assert result.valid, f"Single slide render invalid: {result.errors}"

        # Should contain only one .slide element
        slide_result = validate_slide_structure(single)
        assert slide_result.valid
        assert slide_result.details["slide_count"] == 1
