"""Integration tests for sequential slide replacement flow.

Tests the full flow of:
1. Parsing original HTML into SlideDeck
2. Parsing update HTMLs into replacement slides
3. Applying replacements sequentially
4. Validating final output matches expected HTML

Uses sample_htmls fixtures that represent a realistic editing session.
"""

import pytest

from src.domain.slide import Slide
from src.domain.slide_deck import SlideDeck
from src.services.agent import SlideGeneratorAgent
from tests.fixtures.sample_htmls import (
    get_update_config,
    load_final_html,
    load_original_deck,
    load_sample_html,
    normalize_html,
)


@pytest.fixture
def agent_stub() -> SlideGeneratorAgent:
    """Provide a SlideGeneratorAgent instance without running __init__."""
    return SlideGeneratorAgent.__new__(SlideGeneratorAgent)


@pytest.fixture
def original_deck() -> SlideDeck:
    """Load and parse original_deck.html into SlideDeck."""
    return SlideDeck.from_html_string(load_original_deck())


class TestSlideReplacementFlow:
    """Integration tests for sequential slide replacements."""

    def test_original_deck_structure(self, original_deck: SlideDeck) -> None:
        """Verify original deck parses correctly before applying updates."""
        # Should have 15 slides
        assert len(original_deck.slides) == 15
        
        # Should have 8 slides with scripts attached
        # (10 script blocks but some cover multiple charts on same slide)
        slides_with_scripts = [s for s in original_deck.slides if s.scripts.strip()]
        assert len(slides_with_scripts) == 8
        
        # Verify specific canvas IDs are in scripts
        assert "historicalSpendChart" in original_deck.slides[2].scripts
        assert "retailChart" in original_deck.slides[5].scripts

    def test_apply_sequential_updates(
        self,
        agent_stub: SlideGeneratorAgent,
        original_deck: SlideDeck,
    ) -> None:
        """Apply update1 -> update2 -> update3 sequentially and verify structure."""
        update_configs = get_update_config()
        deck = original_deck
        
        # Track expected slide count after each update
        # Original: 15 slides
        # After update1: 15 (1 replaced with 1)
        # After update2: 15 (1 replaced with 1) 
        # After update3: 13 (3 replaced with 1)
        expected_counts = [15, 15, 13]
        
        for i, (update_name, config) in enumerate(update_configs.items()):
            # Parse update HTML
            update_html = load_sample_html(config["path"])
            result = agent_stub._parse_slide_replacements(
                update_html, config["original_indices"]
            )
            
            # Verify parsing result
            assert result["success"] is True
            assert len(result["replacement_slides"]) == config["expected_replacement_count"]
            
            # Apply replacement to deck
            deck = self._apply_replacement(deck, result, config["original_indices"])
            
            # Verify slide count after this update
            assert len(deck.slides) == expected_counts[i], (
                f"After {update_name}: expected {expected_counts[i]} slides, got {len(deck.slides)}"
            )
        
        # Final deck should have 13 slides
        assert len(deck.slides) == 13

    def test_sequential_updates_exact_match(
        self,
        agent_stub: SlideGeneratorAgent,
        original_deck: SlideDeck,
    ) -> None:
        """Apply all updates and compare to final_html.html with exact match."""
        update_configs = get_update_config()
        deck = original_deck
        
        # Apply each update sequentially
        for update_name, config in update_configs.items():
            update_html = load_sample_html(config["path"])
            result = agent_stub._parse_slide_replacements(
                update_html, config["original_indices"]
            )
            
            # Apply replacement
            deck = self._apply_replacement(deck, result, config["original_indices"])
            
            # Merge CSS if present
            if result.get("replacement_css"):
                deck.update_css(result["replacement_css"])
        
        # Generate final HTML
        actual_html = deck.knit()
        expected_html = load_final_html()
        
        # Normalize both for comparison
        actual_normalized = normalize_html(actual_html)
        expected_normalized = normalize_html(expected_html)
        
        # Compare
        assert actual_normalized == expected_normalized, (
            "Generated HTML does not match expected final_html.html. "
            f"Actual slides: {len(deck.slides)}, "
            f"Actual HTML length: {len(actual_html)}, "
            f"Expected HTML length: {len(expected_html)}"
        )

    def test_script_assignment_after_replacement(
        self,
        agent_stub: SlideGeneratorAgent,
        original_deck: SlideDeck,
    ) -> None:
        """Verify scripts are correctly assigned to replacement slides."""
        update_configs = get_update_config()
        deck = original_deck
        
        # Apply update1 (replaces slide 3 with same canvas ID)
        config = update_configs["update1"]
        update_html = load_sample_html(config["path"])
        result = agent_stub._parse_slide_replacements(update_html, config["original_indices"])
        
        # Replacement slide should have historicalSpendChart script
        replacement_slide = result["replacement_slides"][0]
        assert "historicalSpendChart" in replacement_slide.scripts
        
        # Apply replacement
        deck = self._apply_replacement(deck, result, config["original_indices"])
        
        # After replacement, slide at index 2 should have the new script
        assert "historicalSpendChart" in deck.slides[2].scripts
        
        # Apply update2 (replaces slide 6 with same canvas ID)
        config = update_configs["update2"]
        update_html = load_sample_html(config["path"])
        result = agent_stub._parse_slide_replacements(update_html, config["original_indices"])
        
        # Replacement slide should have retailChart script
        replacement_slide = result["replacement_slides"][0]
        assert "retailChart" in replacement_slide.scripts
        
        deck = self._apply_replacement(deck, result, config["original_indices"])
        
        # After replacement, slide at index 5 should have the new script
        assert "retailChart" in deck.slides[5].scripts
        
        # Apply update3 (consolidates 3 slides into 1, no canvas)
        config = update_configs["update3"]
        update_html = load_sample_html(config["path"])
        result = agent_stub._parse_slide_replacements(update_html, config["original_indices"])
        
        # Replacement slide should have no scripts (text-only)
        replacement_slide = result["replacement_slides"][0]
        assert replacement_slide.scripts.strip() == ""
        
        deck = self._apply_replacement(deck, result, config["original_indices"])
        
        # After replacement, slide at index 12 should have no script
        assert deck.slides[12].scripts.strip() == ""

    def test_no_duplicate_canvas_ids_after_replacement(
        self,
        agent_stub: SlideGeneratorAgent,
        original_deck: SlideDeck,
    ) -> None:
        """Verify no duplicate canvas ID declarations after replacements."""
        update_configs = get_update_config()
        deck = original_deck
        
        # Apply all updates
        for update_name, config in update_configs.items():
            update_html = load_sample_html(config["path"])
            result = agent_stub._parse_slide_replacements(update_html, config["original_indices"])
            deck = self._apply_replacement(deck, result, config["original_indices"])
        
        # Collect all scripts
        all_scripts = deck.scripts
        
        # Count occurrences of key canvas IDs
        canvas_ids = [
            "historicalSpendChart",
            "retailChart",
            "lobPieChart",
            "financialServicesChart",
        ]
        
        for canvas_id in canvas_ids:
            # Each canvas ID should appear exactly once in getElementById calls
            occurrences = all_scripts.count(f"getElementById('{canvas_id}')")
            assert occurrences <= 1, (
                f"Canvas ID '{canvas_id}' appears {occurrences} times in scripts"
            )

    def _apply_replacement(
        self,
        deck: SlideDeck,
        replacement_info: dict,
        original_indices: list[int],
    ) -> SlideDeck:
        """Apply slide replacement to deck.
        
        This simulates what ChatService._apply_slide_replacements does.
        """
        start_idx = min(original_indices)
        original_count = len(original_indices)
        replacement_slides = replacement_info["replacement_slides"]
        
        # Remove original slides
        for _ in range(original_count):
            deck.remove_slide(start_idx)
        
        # Insert replacement slides
        for idx, slide in enumerate(replacement_slides):
            slide.slide_id = f"slide_{start_idx + idx}"
            deck.insert_slide(slide, start_idx + idx)
        
        return deck


class TestUpdateHTMLParsing:
    """Test parsing of individual update HTML files."""

    def test_update1_parsing(self, agent_stub: SlideGeneratorAgent) -> None:
        """update1.html should parse as single slide with historicalSpendChart."""
        from tests.fixtures.sample_htmls import load_update1
        
        result = agent_stub._parse_slide_replacements(load_update1(), [2])
        
        assert result["success"] is True
        assert result["replacement_count"] == 1
        assert len(result["replacement_slides"]) == 1
        
        slide = result["replacement_slides"][0]
        assert isinstance(slide, Slide)
        assert "historicalSpendChart" in slide.scripts
        assert "chartA" not in slide.html.lower()  # No chartA in update1

    def test_update2_parsing(self, agent_stub: SlideGeneratorAgent) -> None:
        """update2.html should parse as single slide with retailChart."""
        from tests.fixtures.sample_htmls import load_update2
        
        result = agent_stub._parse_slide_replacements(load_update2(), [5])
        
        assert result["success"] is True
        assert result["replacement_count"] == 1
        assert len(result["replacement_slides"]) == 1
        
        slide = result["replacement_slides"][0]
        assert isinstance(slide, Slide)
        assert "retailChart" in slide.scripts
        # Verify chart type changed to line (update2 changes bar to line)
        assert "type: 'line'" in slide.scripts

    def test_update3_parsing(self, agent_stub: SlideGeneratorAgent) -> None:
        """update3.html should parse as single slide with no scripts."""
        from tests.fixtures.sample_htmls import load_update3
        
        result = agent_stub._parse_slide_replacements(load_update3(), [12, 13, 14])
        
        assert result["success"] is True
        assert result["replacement_count"] == 1
        assert result["original_count"] == 3
        assert len(result["replacement_slides"]) == 1
        
        slide = result["replacement_slides"][0]
        assert isinstance(slide, Slide)
        # No canvas in update3, so no scripts
        assert slide.scripts.strip() == ""
        # Should have consolidated content
        assert "Strategic recommendations" in slide.html

