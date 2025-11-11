"""Unit tests for Slide class."""

import pytest
from src.models.slide import Slide


class TestSlideCreation:
    """Test slide creation and initialization."""
    
    def test_create_slide_with_html(self):
        """Test creating a slide with HTML content."""
        html = '<div class="slide"><h1>Test</h1></div>'
        slide = Slide(html=html)
        
        assert slide.html == html
        assert slide.slide_id is None
    
    def test_create_slide_with_id(self):
        """Test creating a slide with an ID."""
        html = '<div class="slide"><h1>Test</h1></div>'
        slide_id = "slide_1"
        slide = Slide(html=html, slide_id=slide_id)
        
        assert slide.html == html
        assert slide.slide_id == slide_id


class TestSlideOperations:
    """Test slide operations like cloning and HTML retrieval."""
    
    def test_to_html(self):
        """Test retrieving HTML from slide."""
        html = '<div class="slide"><h1>Test Content</h1></div>'
        slide = Slide(html=html)
        
        assert slide.to_html() == html
    
    def test_clone_slide(self):
        """Test cloning a slide creates independent copy."""
        original_html = '<div class="slide"><h1>Original</h1></div>'
        slide = Slide(html=original_html, slide_id="slide_1")
        
        cloned_slide = slide.clone()
        
        # Should have same content
        assert cloned_slide.html == slide.html
        assert cloned_slide.slide_id == slide.slide_id
        
        # Should be different Slide objects
        assert cloned_slide is not slide
    
    def test_clone_preserves_modifications(self):
        """Test that modifying cloned slide doesn't affect original."""
        original_html = '<div class="slide"><h1>Original</h1></div>'
        slide = Slide(html=original_html)
        
        cloned_slide = slide.clone()
        cloned_slide.html = '<div class="slide"><h1>Modified</h1></div>'
        
        # Original should be unchanged
        assert slide.html == original_html


class TestSlideStringRepresentation:
    """Test string representations of slides."""
    
    def test_str_short_html(self):
        """Test __str__ with short HTML (no truncation)."""
        html = '<div class="slide"><h1>Short</h1></div>'
        slide = Slide(html=html)
        
        str_repr = str(slide)
        assert "Slide:" in str_repr
        assert html in str_repr
    
    def test_str_long_html(self):
        """Test __str__ with long HTML (truncated)."""
        html = '<div class="slide">' + 'x' * 200 + '</div>'
        slide = Slide(html=html)
        
        str_repr = str(slide)
        assert "Slide:" in str_repr
        assert "..." in str_repr
        assert len(str_repr) < len(html)
    
    def test_str_with_slide_id(self):
        """Test __str__ includes slide ID when present."""
        html = '<div class="slide"><h1>Test</h1></div>'
        slide = Slide(html=html, slide_id="slide_42")
        
        str_repr = str(slide)
        assert "slide_42" in str_repr
    
    def test_repr(self):
        """Test __repr__ for debugging."""
        html = '<div class="slide"><h1>Test</h1></div>'
        slide = Slide(html=html, slide_id="slide_1")
        
        repr_str = repr(slide)
        assert "Slide(" in repr_str
        assert "slide_id=" in repr_str
        assert "html_length=" in repr_str


class TestSlideEdgeCases:
    """Test edge cases and special scenarios."""
    
    def test_empty_html(self):
        """Test slide with empty HTML."""
        slide = Slide(html="")
        
        assert slide.html == ""
        assert len(slide.html) == 0
    
    def test_html_with_special_characters(self):
        """Test slide with special characters in HTML."""
        html = '<div class="slide"><h1>Test & "quotes" <script></script></h1></div>'
        slide = Slide(html=html)
        
        assert slide.html == html
        assert slide.to_html() == html
    
    def test_multiline_html(self):
        """Test slide with multiline HTML."""
        html = """<div class="slide">
    <h1>Title</h1>
    <p>Content</p>
</div>"""
        slide = Slide(html=html)
        
        assert slide.html == html
        assert '\n' in slide.to_html()

