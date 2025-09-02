"""Unit tests for HTML slide generation."""

import pytest
from slide_generator.tools.html_slides import HtmlDeck, SlideTheme


class TestSlideTheme:
    """Test the SlideTheme class."""
    
    def test_default_theme_creation(self):
        """Test creating a theme with default values."""
        theme = SlideTheme()
        assert theme.background_rgb == (255, 255, 255)
        assert theme.title_color_rgb == (0, 0, 0)
        assert "font-family" in theme.build_base_css()
    
    def test_custom_theme_creation(self):
        """Test creating a theme with custom values."""
        theme = SlideTheme(
            background_rgb=(0, 0, 0),
            title_color_rgb=(255, 255, 255),
            title_font_size_px=48
        )
        assert theme.background_rgb == (0, 0, 0)
        assert theme.title_color_rgb == (255, 255, 255)
        assert theme.title_font_size_px == 48
    
    def test_rgb_method(self):
        """Test the RGB color formatting method."""
        theme = SlideTheme()
        assert theme.rgb((255, 0, 0)) == "rgb(255, 0, 0)"
        assert theme.rgb((0, 255, 0)) == "rgb(0, 255, 0)"


class TestHtmlDeck:
    """Test the HtmlDeck class."""
    
    def test_empty_deck_creation(self):
        """Test creating an empty deck."""
        deck = HtmlDeck()
        assert len(deck._slides_html) == 0
        html = deck.to_html()
        assert "<!doctype html>" in html
        assert "reveal.js" in html
    
    def test_title_slide_creation(self, sample_html_deck):
        """Test adding a title slide."""
        assert len(sample_html_deck._slides_html) >= 1
        html = sample_html_deck.to_html()
        assert "Test Presentation" in html
        assert "A sample deck for testing" in html
    
    def test_agenda_slide_creation(self, sample_html_deck):
        """Test adding an agenda slide."""
        html = sample_html_deck.to_html()
        assert "Agenda" in html
        assert "Introduction" in html
        assert "Main Content" in html
    
    def test_content_slide_creation(self):
        """Test adding a content slide."""
        deck = HtmlDeck()
        deck.add_content_slide(
            title="Test Content",
            subtitle="Test Subtitle",
            num_columns=2,
            column_contents=[
                ["Point 1", "Point 2"],
                ["Point 3", "Point 4"]
            ]
        )
        html = deck.to_html()
        assert "Test Content" in html
        assert "Point 1" in html
        assert "Point 3" in html
    
    def test_slide_reordering(self):
        """Test slide reordering functionality."""
        deck = HtmlDeck()
        
        # Add multiple slides
        deck.add_title_slide(title="Title", subtitle="Sub", authors=["Author"], date="2024")
        deck.add_agenda_slide(agenda_points=["Item 1", "Item 2"])
        deck.add_content_slide(title="Content 1", subtitle="Sub1", num_columns=1, column_contents=[["Content"]])
        deck.add_content_slide(title="Content 2", subtitle="Sub2", num_columns=1, column_contents=[["Content"]])
        
        # Initial state: 4 slides
        assert len(deck._slides_html) == 4
        
        # Move slide 3 to position 1 (should shift agenda slide down)
        deck.reorder_slide(3, 1)
        assert len(deck._slides_html) == 4
    
    def test_slide_positioning(self):
        """Test that title and agenda slides go to correct positions."""
        deck = HtmlDeck()
        
        # Add content slide first
        deck.add_content_slide(title="Content", subtitle="Sub", num_columns=1, column_contents=[["Test"]])
        assert len(deck._slides_html) == 1
        
        # Add title slide - should go to position 0
        deck.add_title_slide(title="Title", subtitle="Sub", authors=["Author"], date="2024")
        assert len(deck._slides_html) == 2
        assert "Title" in deck._slides_html[0]
        
        # Add agenda slide - should go to position 1
        deck.add_agenda_slide(agenda_points=["Item 1"])
        assert len(deck._slides_html) == 3
        assert "Agenda" in deck._slides_html[1]
    
    def test_invalid_reorder_positions(self):
        """Test error handling for invalid reorder positions."""
        deck = HtmlDeck()
        deck.add_title_slide(title="Title", subtitle="Sub", authors=["Author"], date="2024")
        
        # Test invalid from_position
        with pytest.raises(ValueError):
            deck.reorder_slide(5, 0)
        
        # Test negative from_position
        with pytest.raises(ValueError):
            deck.reorder_slide(-1, 0)
        
        # Test negative to_position
        with pytest.raises(ValueError):
            deck.reorder_slide(0, -1)




