"""Unit tests for the chatbot functionality."""

import json
import pytest
from unittest.mock import Mock, patch

from slide_generator.core.chatbot import Chatbot
from slide_generator.tools.html_slides import HtmlDeck


class TestChatbot:
    """Test the Chatbot class."""
    
    def test_chatbot_initialization(self, mock_workspace_client):
        """Test chatbot initialization."""
        deck = HtmlDeck()
        chatbot = Chatbot(
            html_deck=deck,
            llm_endpoint_name="test-endpoint",
            ws=mock_workspace_client
        )
        
        assert chatbot.html_deck is deck
        assert chatbot.llm_endpoint_name == "test-endpoint"
        assert chatbot.ws is mock_workspace_client
        assert len(chatbot.tools) > 0
    
    def test_tool_execution_title_slide(self, mock_workspace_client):
        """Test executing the title slide tool."""
        deck = HtmlDeck()
        chatbot = Chatbot(
            html_deck=deck,
            llm_endpoint_name="test-endpoint",
            ws=mock_workspace_client
        )
        
        result = chatbot._execute_tool_from_dict(
            "tool_add_title_slide",
            {
                "title": "Test Title",
                "subtitle": "Test Subtitle",
                "authors": ["Test Author"],
                "date": "2024"
            }
        )
        
        assert "Title slide added/replaced at position 0" in result
        assert len(deck._slides_html) == 1
        html = deck.to_html()
        assert "Test Title" in html
    
    def test_tool_execution_agenda_slide(self, mock_workspace_client):
        """Test executing the agenda slide tool."""
        deck = HtmlDeck()
        chatbot = Chatbot(
            html_deck=deck,
            llm_endpoint_name="test-endpoint",
            ws=mock_workspace_client
        )
        
        result = chatbot._execute_tool_from_dict(
            "tool_add_agenda_slide",
            {"agenda_points": ["Point 1", "Point 2", "Point 3"]}
        )
        
        assert "Agenda slide added/replaced at position 1" in result
        html = deck.to_html()
        assert "Point 1" in html
        assert "Point 2" in html
    
    def test_tool_execution_content_slide(self, mock_workspace_client):
        """Test executing the content slide tool."""
        deck = HtmlDeck()
        chatbot = Chatbot(
            html_deck=deck,
            llm_endpoint_name="test-endpoint",
            ws=mock_workspace_client
        )
        
        result = chatbot._execute_tool_from_dict(
            "tool_add_content_slide",
            {
                "title": "Content Title",
                "subtitle": "Content Subtitle",
                "num_columns": 2,
                "column_contents": [["Item 1", "Item 2"], ["Item 3", "Item 4"]]
            }
        )
        
        assert "Content slide added" in result
        html = deck.to_html()
        assert "Content Title" in html
        assert "Item 1" in html
    
    def test_tool_execution_reorder_slide(self, mock_workspace_client):
        """Test executing the reorder slide tool."""
        deck = HtmlDeck()
        chatbot = Chatbot(
            html_deck=deck,
            llm_endpoint_name="test-endpoint",
            ws=mock_workspace_client
        )
        
        # Add some slides first
        deck.add_title_slide(title="Title", subtitle="Sub", authors=["Author"], date="2024")
        deck.add_agenda_slide(agenda_points=["Item 1"])
        deck.add_content_slide(title="Content", subtitle="Sub", num_columns=1, column_contents=[["Test"]])
        
        result = chatbot._execute_tool_from_dict(
            "tool_reorder_slide",
            {"from_position": 2, "to_position": 1}
        )
        
        assert "Moved slide from position 2 to position 1" in result
    
    def test_tool_execution_unknown_tool(self, mock_workspace_client):
        """Test executing an unknown tool."""
        deck = HtmlDeck()
        chatbot = Chatbot(
            html_deck=deck,
            llm_endpoint_name="test-endpoint",
            ws=mock_workspace_client
        )
        
        result = chatbot._execute_tool_from_dict(
            "unknown_tool",
            {"param": "value"}
        )
        
        assert "Unknown tool: unknown_tool" in result
    
    def test_execute_tool_call_format(self, mock_workspace_client):
        """Test the execute_tool_call method with proper format."""
        deck = HtmlDeck()
        chatbot = Chatbot(
            html_deck=deck,
            llm_endpoint_name="test-endpoint",
            ws=mock_workspace_client
        )
        
        tool_call_dict = {
            "id": "call_123",
            "function": {
                "name": "tool_add_title_slide",
                "arguments": json.dumps({
                    "title": "Test Title",
                    "subtitle": "Test Subtitle", 
                    "authors": ["Test Author"],
                    "date": "2024"
                })
            }
        }
        
        result = chatbot.execute_tool_call(tool_call_dict)
        
        assert result["role"] == "tool"
        assert result["tool_call_id"] == "call_123"
        assert "Title slide added" in result["content"]
    
    @patch('slide_generator.core.chatbot.Chatbot._call_llm')
    def test_call_llm_with_tool_response(self, mock_call_llm, mock_workspace_client, mock_llm_response):
        """Test call_llm method with tool call response."""
        # Setup mock response with tool calls
        mock_tool_call = Mock()
        mock_tool_call.id = "call_123"
        mock_tool_call.function.name = "tool_add_title_slide"
        mock_tool_call.function.arguments = '{"title": "Test", "subtitle": "Test", "authors": ["Test"], "date": "2024"}'
        
        mock_llm_response.choices[0].message.tool_calls = [mock_tool_call]
        mock_llm_response.choices[0].message.content = "Creating title slide"
        mock_call_llm.return_value = (mock_llm_response, None)
        
        deck = HtmlDeck()
        chatbot = Chatbot(
            html_deck=deck,
            llm_endpoint_name="test-endpoint",
            ws=mock_workspace_client
        )
        
        conversation = [{"role": "user", "content": "Create a title slide"}]
        result, stop = chatbot.call_llm(conversation)
        
        assert result["role"] == "assistant"
        assert "tool_calls" in result
        assert len(result["tool_calls"]) == 1
        assert not stop  # Should not stop when tool calls are present
    
    @patch('slide_generator.core.chatbot.Chatbot._call_llm')
    def test_call_llm_with_regular_response(self, mock_call_llm, mock_workspace_client, mock_llm_response):
        """Test call_llm method with regular text response."""
        mock_llm_response.choices[0].message.tool_calls = None
        mock_llm_response.choices[0].message.content = "Here's your slide deck!"
        mock_call_llm.return_value = (mock_llm_response, None)
        
        deck = HtmlDeck()
        chatbot = Chatbot(
            html_deck=deck,
            llm_endpoint_name="test-endpoint",
            ws=mock_workspace_client
        )
        
        conversation = [{"role": "user", "content": "Show me the deck"}]
        result, stop = chatbot.call_llm(conversation)
        
        assert result["role"] == "assistant"
        assert result["content"] == "Here's your slide deck!"
        assert "tool_calls" not in result
        assert stop  # Should stop when no tool calls are present
    
    @patch('slide_generator.core.chatbot.Chatbot._call_llm')
    def test_call_llm_with_error(self, mock_call_llm, mock_workspace_client):
        """Test call_llm method with error response."""
        mock_call_llm.return_value = (None, "Connection error")
        
        deck = HtmlDeck()
        chatbot = Chatbot(
            html_deck=deck,
            llm_endpoint_name="test-endpoint",
            ws=mock_workspace_client
        )
        
        conversation = [{"role": "user", "content": "Create slides"}]
        result, stop = chatbot.call_llm(conversation)
        
        assert result["role"] == "assistant"
        assert "Error: Connection error" in result["content"]
        assert stop  # Should stop on error


