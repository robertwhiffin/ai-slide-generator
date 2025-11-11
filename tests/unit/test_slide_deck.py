"""Unit tests for SlideDeck class."""

import pytest
from pathlib import Path
from src.models.slide_deck import SlideDeck
from src.models.slide import Slide


@pytest.fixture
def sample_html():
    """Fixture providing sample HTML content."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Test Presentation</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { margin: 0; }
        .slide { width: 100vw; height: 100vh; }
    </style>
</head>
<body>

<div class="slide">
    <h1>Slide 1</h1>
</div>

<div class="slide">
    <h1>Slide 2</h1>
</div>

<script>
    console.log('test');
</script>

</body>
</html>"""


@pytest.fixture
def sample_deck():
    """Fixture providing a sample slide deck."""
    slide1 = Slide(html='<div class="slide"><h1>Slide 1</h1></div>')
    slide2 = Slide(html='<div class="slide"><h1>Slide 2</h1></div>')
    
    return SlideDeck(
        title="Test Deck",
        css="body { margin: 0; }",
        external_scripts=["https://cdn.tailwindcss.com"],
        scripts="console.log('test');",
        slides=[slide1, slide2]
    )


class TestSlideDeckCreation:
    """Test slide deck creation and initialization."""
    
    def test_create_empty_deck(self):
        """Test creating an empty slide deck."""
        deck = SlideDeck()
        
        assert deck.title is None
        assert deck.css == ""
        assert deck.external_scripts == []
        assert deck.scripts == ""
        assert deck.slides == []
        assert deck.head_meta == {}
    
    def test_create_deck_with_parameters(self, sample_deck):
        """Test creating a deck with parameters."""
        assert sample_deck.title == "Test Deck"
        assert sample_deck.css == "body { margin: 0; }"
        assert len(sample_deck.slides) == 2
        assert len(sample_deck.external_scripts) == 1


class TestHTMLParsing:
    """Test HTML parsing functionality."""
    
    def test_from_html_string(self, sample_html):
        """Test parsing HTML from string."""
        deck = SlideDeck.from_html_string(sample_html)
        
        assert deck.title == "Test Presentation"
        assert len(deck.slides) == 2
        assert "margin" in deck.css
        assert "https://cdn.tailwindcss.com" in deck.external_scripts
        assert "console.log" in deck.scripts
    
    def test_parse_title(self, sample_html):
        """Test extracting title from HTML."""
        deck = SlideDeck.from_html_string(sample_html)
        assert deck.title == "Test Presentation"
    
    def test_parse_css(self, sample_html):
        """Test extracting CSS from <style> tags."""
        deck = SlideDeck.from_html_string(sample_html)
        assert "body" in deck.css
        assert "margin" in deck.css
        assert ".slide" in deck.css
    
    def test_parse_external_scripts(self, sample_html):
        """Test extracting external script URLs."""
        deck = SlideDeck.from_html_string(sample_html)
        
        assert len(deck.external_scripts) == 2
        assert "https://cdn.tailwindcss.com" in deck.external_scripts
        assert "https://cdn.jsdelivr.net/npm/chart.js" in deck.external_scripts
    
    def test_parse_inline_scripts(self, sample_html):
        """Test extracting inline JavaScript."""
        deck = SlideDeck.from_html_string(sample_html)
        assert "console.log" in deck.scripts
    
    def test_parse_slides(self, sample_html):
        """Test extracting slides."""
        deck = SlideDeck.from_html_string(sample_html)
        
        assert len(deck.slides) == 2
        assert "Slide 1" in deck.slides[0].html
        assert "Slide 2" in deck.slides[1].html
    
    def test_parse_meta_tags(self, sample_html):
        """Test extracting metadata."""
        deck = SlideDeck.from_html_string(sample_html)
        
        assert deck.head_meta.get('charset') == 'UTF-8'
        assert 'viewport' in deck.head_meta
    
    def test_parse_slides_with_additional_classes(self):
        """Test parsing slides with additional CSS classes."""
        html = """<!DOCTYPE html>
<html><head><title>Test</title></head><body>
<div class="slide title-slide">
    <h1>Title</h1>
</div>
<div class="slide content-slide">
    <h1>Content</h1>
</div>
</body></html>"""
        
        deck = SlideDeck.from_html_string(html)
        
        assert len(deck.slides) == 2
        assert "title-slide" in deck.slides[0].html
        assert "content-slide" in deck.slides[1].html
    
    def test_parse_html_without_slides(self):
        """Test parsing HTML with no slides."""
        html = """<!DOCTYPE html>
<html><head><title>Test</title></head><body>
<div class="not-a-slide"><h1>Not a slide</h1></div>
</body></html>"""
        
        deck = SlideDeck.from_html_string(html)
        assert len(deck.slides) == 0


class TestSlideOperations:
    """Test slide manipulation operations."""
    
    def test_append_slide(self, sample_deck):
        """Test appending slide at end of deck."""
        new_slide = Slide(html='<div class="slide"><h1>New Slide</h1></div>')
        initial_count = len(sample_deck)
        
        sample_deck.append_slide(new_slide)
        
        assert len(sample_deck) == initial_count + 1
        assert sample_deck.slides[-1] == new_slide
    
    def test_insert_slide(self, sample_deck):
        """Test inserting slide at specific position."""
        new_slide = Slide(html='<div class="slide"><h1>Inserted</h1></div>')
        
        sample_deck.insert_slide(new_slide, position=1)
        
        assert len(sample_deck) == 3
        assert sample_deck.slides[1] == new_slide
        assert "Inserted" in sample_deck.slides[1].html
    
    def test_remove_slide(self, sample_deck):
        """Test removing slide by index."""
        initial_count = len(sample_deck)
        
        removed = sample_deck.remove_slide(0)
        
        assert len(sample_deck) == initial_count - 1
        assert "Slide 1" in removed.html
    
    def test_get_slide(self, sample_deck):
        """Test retrieving slide by index."""
        slide = sample_deck.get_slide(0)
        
        assert "Slide 1" in slide.html
    
    def test_move_slide(self, sample_deck):
        """Test moving slide from one position to another."""
        # Add a third slide for clearer testing
        sample_deck.append_slide(Slide(html='<div class="slide"><h1>Slide 3</h1></div>'))
        
        # Move slide from index 2 to index 0
        sample_deck.move_slide(from_index=2, to_index=0)
        
        assert "Slide 3" in sample_deck.slides[0].html
        assert "Slide 1" in sample_deck.slides[1].html
        assert "Slide 2" in sample_deck.slides[2].html
    
    def test_swap_slides(self, sample_deck):
        """Test swapping two slides."""
        original_first = sample_deck.slides[0].html
        original_second = sample_deck.slides[1].html
        
        sample_deck.swap_slides(0, 1)
        
        assert sample_deck.slides[0].html == original_second
        assert sample_deck.slides[1].html == original_first
    
    def test_len(self, sample_deck):
        """Test __len__ returns slide count."""
        assert len(sample_deck) == 2
    
    def test_iter(self, sample_deck):
        """Test iterating over slides."""
        slides = list(sample_deck)
        
        assert len(slides) == 2
        assert all(isinstance(s, Slide) for s in slides)
    
    def test_getitem(self, sample_deck):
        """Test accessing slides by index."""
        slide = sample_deck[0]
        
        assert "Slide 1" in slide.html
    
    def test_getitem_negative_index(self, sample_deck):
        """Test accessing slides with negative index."""
        last_slide = sample_deck[-1]
        
        assert "Slide 2" in last_slide.html


class TestKnitting:
    """Test HTML reconstruction (knitting)."""
    
    def test_knit_basic(self, sample_deck):
        """Test reconstructing HTML from deck."""
        html = sample_deck.knit()
        
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert sample_deck.title in html
        assert "Slide 1" in html
        assert "Slide 2" in html
    
    def test_knit_includes_css(self, sample_deck):
        """Test knitted HTML includes CSS."""
        html = sample_deck.knit()
        
        assert "<style>" in html
        assert sample_deck.css in html
    
    def test_knit_includes_scripts(self, sample_deck):
        """Test knitted HTML includes scripts."""
        html = sample_deck.knit()
        
        assert sample_deck.scripts in html
    
    def test_knit_includes_external_scripts(self, sample_deck):
        """Test knitted HTML includes external script tags."""
        html = sample_deck.knit()
        
        assert "https://cdn.tailwindcss.com" in html
        assert '<script src=' in html
    
    def test_render_single_slide(self, sample_deck):
        """Test rendering individual slide."""
        html = sample_deck.render_slide(0)
        
        assert "<!DOCTYPE html>" in html
        assert "Slide 1" in html
        assert "Slide 2" not in html  # Should only include one slide
        assert sample_deck.css in html
        assert sample_deck.scripts in html
    
    def test_render_slide_title(self, sample_deck):
        """Test rendered slide has correct title."""
        html = sample_deck.render_slide(1)
        
        assert "Test Deck - Slide 2" in html
    
    def test_round_trip(self, sample_html):
        """Test parse → knit → parse preserves structure."""
        deck1 = SlideDeck.from_html_string(sample_html)
        knitted = deck1.knit()
        deck2 = SlideDeck.from_html_string(knitted)
        
        assert deck1.title == deck2.title
        assert len(deck1.slides) == len(deck2.slides)
        # CSS might have formatting differences, but content should be similar
        assert len(deck1.css) > 0
        assert len(deck2.css) > 0


class TestWebAPISupport:
    """Test JSON serialization for web APIs."""
    
    def test_to_dict(self, sample_deck):
        """Test converting deck to dictionary."""
        data = sample_deck.to_dict()
        
        assert data['title'] == sample_deck.title
        assert data['slide_count'] == 2
        assert data['css'] == sample_deck.css
        assert data['scripts'] == sample_deck.scripts
        assert len(data['slides']) == 2
    
    def test_to_dict_slide_structure(self, sample_deck):
        """Test slide structure in dictionary."""
        data = sample_deck.to_dict()
        
        first_slide = data['slides'][0]
        assert 'index' in first_slide
        assert 'html' in first_slide
        assert 'slide_id' in first_slide
        assert first_slide['index'] == 0


class TestFileOperations:
    """Test file I/O operations."""
    
    def test_save(self, sample_deck, tmp_path):
        """Test saving deck to file."""
        output_file = tmp_path / "test_output.html"
        
        sample_deck.save(str(output_file))
        
        assert output_file.exists()
        content = output_file.read_text()
        assert "Slide 1" in content
        assert "Slide 2" in content
    
    def test_from_html_file(self, sample_html, tmp_path):
        """Test loading deck from HTML file."""
        input_file = tmp_path / "test_input.html"
        input_file.write_text(sample_html)
        
        deck = SlideDeck.from_html(str(input_file))
        
        assert deck.title == "Test Presentation"
        assert len(deck.slides) == 2
    
    def test_from_html_file_not_found(self):
        """Test loading from non-existent file raises error."""
        with pytest.raises(FileNotFoundError):
            SlideDeck.from_html("/nonexistent/path/file.html")


class TestStringRepresentation:
    """Test string representations of slide deck."""
    
    def test_str(self, sample_deck):
        """Test __str__ representation."""
        str_repr = str(sample_deck)
        
        assert "SlideDeck" in str_repr
        assert sample_deck.title in str_repr
        assert "2" in str_repr  # slide count
    
    def test_repr(self, sample_deck):
        """Test __repr__ representation."""
        repr_str = repr(sample_deck)
        
        assert "SlideDeck" in repr_str
        assert "title=" in repr_str
        assert "slides=" in repr_str


class TestEdgeCases:
    """Test edge cases and special scenarios."""
    
    def test_empty_deck_knit(self):
        """Test knitting empty deck."""
        deck = SlideDeck(title="Empty Deck")
        html = deck.knit()
        
        assert "<!DOCTYPE html>" in html
        assert "Empty Deck" in html
    
    def test_deck_with_no_css(self):
        """Test deck without CSS."""
        deck = SlideDeck(
            title="No CSS",
            slides=[Slide(html='<div class="slide"><h1>Test</h1></div>')]
        )
        html = deck.knit()
        
        assert "<!DOCTYPE html>" in html
        assert "Test" in html
    
    def test_deck_with_no_scripts(self):
        """Test deck without scripts."""
        deck = SlideDeck(
            title="No Scripts",
            slides=[Slide(html='<div class="slide"><h1>Test</h1></div>')]
        )
        html = deck.knit()
        
        assert "<!DOCTYPE html>" in html
        assert "Test" in html
    
    def test_complex_html_structure(self):
        """Test parsing complex nested HTML."""
        html = """<!DOCTYPE html>
<html><head><title>Complex</title><style>body{margin:0;}</style></head>
<body>
<div class="slide">
    <div class="header">
        <h1>Title</h1>
        <div class="subtitle">
            <span>Subtitle</span>
        </div>
    </div>
    <div class="content">
        <ul>
            <li><strong>Item 1</strong></li>
            <li><em>Item 2</em></li>
        </ul>
    </div>
</div>
</body></html>"""
        
        deck = SlideDeck.from_html_string(html)
        
        assert len(deck.slides) == 1
        assert "header" in deck.slides[0].html
        assert "subtitle" in deck.slides[0].html.lower()
        assert "Item 1" in deck.slides[0].html

