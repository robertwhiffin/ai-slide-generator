"""Integration tests for end-to-end functionality."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch

from slide_generator.tools.html_slides import HtmlDeck
from slide_generator.core.chatbot import Chatbot
from slide_generator.config import get_output_path


@pytest.mark.integration
class TestEndToEndSlideGeneration:
    """Test complete slide generation workflow."""
    
    def test_complete_slide_deck_creation(self, mock_workspace_client, temp_output_dir):
        """Test creating a complete slide deck through the workflow."""
        # Initialize components
        deck = HtmlDeck()
        chatbot = Chatbot(
            html_deck=deck,
            llm_endpoint_name="test-endpoint",
            ws=mock_workspace_client
        )
        
        # Simulate conversation workflow
        conversation = [
            {"role": "system", "content": "You are a slide assistant"},
            {"role": "user", "content": "Create a deck about Python programming"}
        ]
        
        # Step 1: Add title slide
        chatbot._execute_tool_from_dict(
            "tool_add_title_slide",
            {
                "title": "Python Programming",
                "subtitle": "An Introduction to Python",
                "authors": ["AI Assistant"],
                "date": "2024"
            }
        )
        
        # Step 2: Add agenda slide  
        chatbot._execute_tool_from_dict(
            "tool_add_agenda_slide",
            {
                "agenda_points": [
                    "What is Python?",
                    "Key Features",
                    "Getting Started",
                    "Best Practices"
                ]
            }
        )
        
        # Step 3: Add content slides
        chatbot._execute_tool_from_dict(
            "tool_add_content_slide",
            {
                "title": "What is Python?",
                "subtitle": "Introduction to Python Programming",
                "num_columns": 2,
                "column_contents": [
                    ["High-level programming language", "Easy to learn and use"],
                    ["Versatile and powerful", "Large community support"]
                ]
            }
        )
        
        chatbot._execute_tool_from_dict(
            "tool_add_content_slide",
            {
                "title": "Key Features",
                "subtitle": "Why Choose Python?",
                "num_columns": 1,
                "column_contents": [
                    [
                        "Simple and readable syntax",
                        "Cross-platform compatibility", 
                        "Extensive standard library",
                        "Active development community"
                    ]
                ]
            }
        )
        
        # Verify the deck was created correctly
        html_content = deck.to_html()
        
        # Check that all slides are present
        assert "Python Programming" in html_content  # Title slide
        assert "An Introduction to Python" in html_content  # Subtitle
        assert "What is Python?" in html_content  # Agenda item
        assert "Key Features" in html_content  # Content slide
        assert "Simple and readable syntax" in html_content  # Content point
        
        # Check HTML structure
        assert "<!doctype html>" in html_content
        assert "reveal.js" in html_content
        assert "<section>" in html_content
        
        # Test saving to file
        output_file = temp_output_dir / "python_presentation.html"
        result = chatbot._execute_tool_from_dict(
            "tool_write_html",
            {"output_path": str(output_file)}
        )
        
        assert "HTML written to" in result
        assert output_file.exists()
        
        # Verify file contents
        saved_content = output_file.read_text()
        assert saved_content == html_content
    
    def test_slide_reordering_workflow(self, mock_workspace_client):
        """Test the slide reordering functionality in a workflow."""
        deck = HtmlDeck()
        chatbot = Chatbot(
            html_deck=deck,
            llm_endpoint_name="test-endpoint",
            ws=mock_workspace_client
        )
        
        # Create multiple slides
        slides_data = [
            ("tool_add_title_slide", {
                "title": "Main Title",
                "subtitle": "Subtitle",
                "authors": ["Author"],
                "date": "2024"
            }),
            ("tool_add_agenda_slide", {
                "agenda_points": ["Topic 1", "Topic 2", "Topic 3"]
            }),
            ("tool_add_content_slide", {
                "title": "Content A",
                "subtitle": "First content",
                "num_columns": 1,
                "column_contents": [["Point A1", "Point A2"]]
            }),
            ("tool_add_content_slide", {
                "title": "Content B", 
                "subtitle": "Second content",
                "num_columns": 1,
                "column_contents": [["Point B1", "Point B2"]]
            })
        ]
        
        # Add all slides
        for tool_name, args in slides_data:
            chatbot._execute_tool_from_dict(tool_name, args)
        
        # Verify initial order
        assert len(deck._slides_html) == 4
        html_before = deck.to_html()
        
        # Reorder: move slide 3 (Content B) to position 2 (before Content A)
        result = chatbot._execute_tool_from_dict(
            "tool_reorder_slide",
            {"from_position": 3, "to_position": 2}
        )
        
        assert "Moved slide from position 3 to position 2" in result
        
        # Verify the deck still has 4 slides
        assert len(deck._slides_html) == 4
        
        # Verify content is still present
        html_after = deck.to_html()
        assert "Main Title" in html_after
        assert "Content A" in html_after
        assert "Content B" in html_after
    
    @pytest.mark.slow
    def test_large_deck_performance(self, mock_workspace_client):
        """Test performance with a larger number of slides."""
        deck = HtmlDeck()
        chatbot = Chatbot(
            html_deck=deck,
            llm_endpoint_name="test-endpoint",
            ws=mock_workspace_client
        )
        
        # Add title and agenda
        chatbot._execute_tool_from_dict(
            "tool_add_title_slide",
            {
                "title": "Large Presentation",
                "subtitle": "Performance Test",
                "authors": ["Test Runner"],
                "date": "2024"
            }
        )
        
        chatbot._execute_tool_from_dict(
            "tool_add_agenda_slide",
            {"agenda_points": [f"Section {i+1}" for i in range(10)]}
        )
        
        # Add many content slides
        for i in range(20):
            chatbot._execute_tool_from_dict(
                "tool_add_content_slide",
                {
                    "title": f"Content Slide {i+1}",
                    "subtitle": f"Section {i+1} Details",
                    "num_columns": 2,
                    "column_contents": [
                        [f"Point {i+1}.1", f"Point {i+1}.2"],
                        [f"Point {i+1}.3", f"Point {i+1}.4"]
                    ]
                }
            )
        
        # Verify all slides were added
        assert len(deck._slides_html) == 22  # title + agenda + 20 content
        
        # Test HTML generation performance
        html_content = deck.to_html()
        assert len(html_content) > 1000  # Should be substantial
        
        # Test that all content is present
        assert "Large Presentation" in html_content
        assert "Content Slide 1" in html_content
        assert "Content Slide 20" in html_content



