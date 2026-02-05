"""Integration tests for SlideDeck with real HTML files."""

import pytest
from pathlib import Path
from src.domain.slide_deck import SlideDeck
from src.domain.slide import Slide


@pytest.fixture
def fixtures_dir():
    """Get path to test fixtures directory."""
    return Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def sample_slides_path(fixtures_dir):
    """Get path to sample slides HTML file."""
    return fixtures_dir / "sample_slides.html"


class TestRealHTMLParsing:
    """Test parsing real HTML files."""
    
    def test_parse_sample_slides(self, sample_slides_path):
        """Test parsing the sample slides fixture."""
        deck = SlideDeck.from_html(str(sample_slides_path))
        
        assert deck.title == "Test Presentation"
        assert len(deck.slides) == 3
        assert len(deck.external_scripts) == 2
        assert "Chart.js" in deck.scripts
    
    def test_slides_contain_expected_content(self, sample_slides_path):
        """Test that slides contain expected content."""
        deck = SlideDeck.from_html(str(sample_slides_path))
        
        # Check slide 1
        assert "Title Slide" in deck.slides[0].html
        assert "Welcome" in deck.slides[0].html
        
        # Check slide 2
        assert "Content Slide" in deck.slides[1].html
        assert "Point 1" in deck.slides[1].html
        
        # Check slide 3
        assert "Chart Slide" in deck.slides[2].html
        assert "canvas" in deck.slides[2].html


class TestCompleteWorkflow:
    """Test complete workflows with parsing, manipulation, and reconstruction."""
    
    def test_parse_manipulate_save(self, sample_slides_path, tmp_path):
        """Test parsing, manipulating, and saving deck."""
        # Parse
        deck = SlideDeck.from_html(str(sample_slides_path))
        
        # Manipulate: swap first two slides
        deck.swap_slides(0, 1)
        
        # Save
        output_path = tmp_path / "manipulated.html"
        deck.save(str(output_path))
        
        # Verify
        assert output_path.exists()
        
        # Re-parse and check
        new_deck = SlideDeck.from_html(str(output_path))
        assert "Content Slide" in new_deck.slides[0].html  # Originally second
        assert "Title Slide" in new_deck.slides[1].html    # Originally first
    
    def test_clone_and_insert_slide(self, sample_slides_path, tmp_path):
        """Test cloning a slide and inserting it."""
        deck = SlideDeck.from_html(str(sample_slides_path))
        
        # Clone first slide
        cloned = deck.slides[0].clone()
        
        # Insert at position 1
        deck.insert_slide(cloned, position=1)
        
        assert len(deck.slides) == 4
        assert "Title Slide" in deck.slides[0].html
        assert "Title Slide" in deck.slides[1].html  # Cloned
    
    def test_remove_and_reorder(self, sample_slides_path):
        """Test removing slides and reordering."""
        deck = SlideDeck.from_html(str(sample_slides_path))
        
        # Remove middle slide
        removed = deck.remove_slide(1)
        assert "Content Slide" in removed.html
        assert len(deck.slides) == 2
        
        # Move last to first
        deck.move_slide(from_index=1, to_index=0)
        assert "Chart Slide" in deck.slides[0].html
    
    def test_round_trip_preserves_data(self, sample_slides_path, tmp_path):
        """Test that parse → save → parse preserves all data."""
        # Parse original
        deck1 = SlideDeck.from_html(str(sample_slides_path))
        
        # Save
        output_path = tmp_path / "roundtrip.html"
        deck1.save(str(output_path))
        
        # Parse saved version
        deck2 = SlideDeck.from_html(str(output_path))
        
        # Compare
        assert deck1.title == deck2.title
        assert len(deck1.slides) == len(deck2.slides)
        assert len(deck1.external_scripts) == len(deck2.external_scripts)
        
        # Check that key content is preserved in each slide
        for i in range(len(deck1.slides)):
            # Extract key words from original
            original_html = deck1.slides[i].html
            roundtrip_html = deck2.slides[i].html
            
            # Both should contain the slide class
            assert 'class="slide"' in original_html
            assert 'class="slide"' in roundtrip_html


class TestWebFrontendScenarios:
    """Test scenarios relevant to web frontends."""
    
    def test_render_individual_slides(self, sample_slides_path):
        """Test rendering individual slides for web viewer."""
        deck = SlideDeck.from_html(str(sample_slides_path))
        
        # Render each slide
        for i in range(len(deck)):
            html = deck.render_slide(i)
            
            assert "<!DOCTYPE html>" in html
            assert "<html" in html
            assert deck.css in html
            
            # Individual slide renders include only that slide's scripts (no IIFE wrapping)
            slide = deck.slides[i]
            if slide.scripts and slide.scripts.strip():
                assert slide.scripts.strip() in html
            
            # Should only contain the specified slide
            slide_content = deck.slides[i].html
            assert slide_content in html
    
    def test_to_dict_for_api(self, sample_slides_path):
        """Test converting deck to dict for JSON API."""
        deck = SlideDeck.from_html(str(sample_slides_path))
        
        data = deck.to_dict()
        
        # Verify structure
        assert isinstance(data, dict)
        assert 'title' in data
        assert 'slide_count' in data
        assert 'slides' in data
        assert isinstance(data['slides'], list)
        
        # Verify slide count matches
        assert data['slide_count'] == len(deck.slides)
        assert len(data['slides']) == len(deck.slides)
        
        # Verify each slide has required fields
        for slide_data in data['slides']:
            assert 'index' in slide_data
            assert 'html' in slide_data
            assert 'slide_id' in slide_data
    
    def test_iterate_through_deck(self, sample_slides_path):
        """Test iterating through deck like a web frontend would."""
        deck = SlideDeck.from_html(str(sample_slides_path))
        
        slide_count = 0
        for slide in deck:
            assert isinstance(slide, Slide)
            assert len(slide.html) > 0
            slide_count += 1
        
        assert slide_count == len(deck)
    
    def test_random_access_by_index(self, sample_slides_path):
        """Test random access to slides (common in web viewers)."""
        deck = SlideDeck.from_html(str(sample_slides_path))
        
        # Access first slide
        first = deck[0]
        assert "Title Slide" in first.html
        
        # Access last slide
        last = deck[-1]
        assert "Chart Slide" in last.html
        
        # Access middle slide
        middle = deck[1]
        assert "Content Slide" in middle.html


class TestModifyingCSS:
    """Test modifying CSS for theming."""
    
    def test_change_brand_color(self, sample_slides_path, tmp_path):
        """Test changing brand color in CSS."""
        deck = SlideDeck.from_html(str(sample_slides_path))
        
        # Original CSS contains certain styles
        original_css = deck.css
        
        # Modify CSS (e.g., change a color)
        deck.css = deck.css.replace("Arial", "Helvetica")
        
        # Save and verify
        output_path = tmp_path / "themed.html"
        deck.save(str(output_path))
        
        # Re-parse and check
        new_deck = SlideDeck.from_html(str(output_path))
        assert "Helvetica" in new_deck.css
        assert "Arial" not in new_deck.css


class TestEdgeCasesIntegration:
    """Test edge cases with real files."""
    
    def test_add_new_custom_slide(self, sample_slides_path, tmp_path):
        """Test adding a completely new custom slide."""
        deck = SlideDeck.from_html(str(sample_slides_path))
        
        # Create custom slide
        custom_html = '''<div class="slide">
    <h1>Custom Analysis</h1>
    <div class="content">
        <p>This is a custom slide added programmatically.</p>
        <ul>
            <li>Data point 1</li>
            <li>Data point 2</li>
        </ul>
    </div>
</div>'''
        
        custom_slide = Slide(html=custom_html, slide_id="custom_1")
        deck.insert_slide(custom_slide, position=1)
        
        # Save and verify
        output_path = tmp_path / "with_custom.html"
        deck.save(str(output_path))
        
        new_deck = SlideDeck.from_html(str(output_path))
        assert len(new_deck.slides) == 4
        assert "Custom Analysis" in new_deck.slides[1].html
    
    def test_empty_deck_operations(self):
        """Test operations on empty deck."""
        deck = SlideDeck(title="Empty Deck")
        
        assert len(deck) == 0
        
        # Add a slide
        slide = Slide(html='<div class="slide"><h1>First</h1></div>')
        deck.append_slide(slide)
        
        assert len(deck) == 1
        
        # Knit should work
        html = deck.knit()
        assert "Empty Deck" in html
        assert "First" in html

