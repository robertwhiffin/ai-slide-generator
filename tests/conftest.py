"""Pytest configuration and fixtures."""

import pytest
from pathlib import Path
from unittest.mock import Mock

from slide_generator.tools.html_slides import HtmlDeck, SlideTheme
from slide_generator.config import get_test_fixture_path


@pytest.fixture
def sample_html_deck():
    """Create a sample HTML deck for testing."""
    deck = HtmlDeck()
    deck.add_title_slide(
        title="Test Presentation",
        subtitle="A sample deck for testing",
        authors=["Test Author"],
        date="2024"
    )
    deck.add_agenda_slide(agenda_points=["Introduction", "Main Content", "Conclusion"])
    return deck


@pytest.fixture
def sample_theme():
    """Create a sample slide theme for testing."""
    return SlideTheme(
        background_rgb=(255, 255, 255),
        title_color_rgb=(0, 0, 0),
        subtitle_color_rgb=(80, 80, 80)
    )


@pytest.fixture
def mock_workspace_client():
    """Create a mock Databricks WorkspaceClient."""
    mock_client = Mock()
    mock_serving_client = Mock()
    mock_client.serving_endpoints.get_open_ai_client.return_value = mock_serving_client
    return mock_client


@pytest.fixture
def mock_llm_response():
    """Create a mock LLM response."""
    mock_response = Mock()
    mock_response.choices = [Mock()]
    mock_response.choices[0].message = Mock()
    mock_response.choices[0].message.content = "Test response"
    mock_response.choices[0].message.tool_calls = None
    mock_response.choices[0].finish_reason = "stop"
    return mock_response


@pytest.fixture
def temp_output_dir(tmp_path):
    """Create a temporary output directory for testing."""
    return tmp_path / "test_output"


@pytest.fixture(scope="session")
def test_data_dir():
    """Get the test data directory."""
    return Path(__file__).parent / "fixtures"


