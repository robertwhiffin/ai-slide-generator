"""Configuration management for the slide generator."""

import os
from pathlib import Path
from typing import Optional

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
SRC_DIR = PROJECT_ROOT / "src"
OUTPUT_DIR = PROJECT_ROOT / "output"
TESTS_DIR = PROJECT_ROOT / "tests"

# Ensure output directory exists
OUTPUT_DIR.mkdir(exist_ok=True)

# Environment settings
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# LLM Configuration
DEFAULT_LLM_ENDPOINT = "databricks-claude-sonnet-4"
LLM_ENDPOINT = os.getenv("LLM_ENDPOINT", DEFAULT_LLM_ENDPOINT)

# Databricks settings
DATABRICKS_HOST = os.getenv("DATABRICKS_HOST")
DATABRICKS_TOKEN = os.getenv("DATABRICKS_TOKEN")

# Gradio settings
GRADIO_HOST = os.getenv("GRADIO_HOST", "127.0.0.1")
GRADIO_PORT = int(os.getenv("GRADIO_PORT", "7860"))
GRADIO_SHARE = os.getenv("GRADIO_SHARE", "false").lower() == "true"

# Slide generation settings
DEFAULT_SLIDE_THEME = "default"
MAX_SLIDES_PER_DECK = int(os.getenv("MAX_SLIDES_PER_DECK", "50"))
DEFAULT_OUTPUT_FORMAT = os.getenv("DEFAULT_OUTPUT_FORMAT", "html")

# System prompt for the slide assistant
SYSTEM_PROMPT = """You are a slide creation assistant. Users interact with you to create their slide decks with natural language. You have access to a set of tools that can update a HTML slide deck. There are 6 tools available to you;

tool_add_title_slide: Add or replace the title slide at position 0 (first slide).
tool_add_agenda_slide: Add or replace the agenda slide at position 1 (second slide).
tool_add_content_slide: Add a content slide with 1–3 columns of bullets.
tool_reorder_slide: Move a slide from one position to another.
tool_get_html: Get the current HTML of the deck.
tool_write_html: Write the current HTML to a file.

You need to decide which tool to use to update the deck. When you have completed the user's request, you should provide a final summary of what was created and suggest using tool_write_html to save the deck to a file."""


def get_output_path(filename: str) -> Path:
    """Get a path in the output directory."""
    return OUTPUT_DIR / filename


def get_test_fixture_path(filename: str) -> Path:
    """Get a path to a test fixture."""
    return TESTS_DIR / "fixtures" / filename


class Config:
    """Configuration class for the slide generator."""
    
    def __init__(self):
        self.debug = DEBUG
        self.log_level = LOG_LEVEL
        self.llm_endpoint = LLM_ENDPOINT
        self.gradio_host = GRADIO_HOST
        self.gradio_port = GRADIO_PORT
        self.gradio_share = GRADIO_SHARE
        self.output_dir = OUTPUT_DIR
        self.system_prompt = SYSTEM_PROMPT
        
    def validate(self) -> bool:
        """Validate the configuration."""
        if not self.llm_endpoint:
            raise ValueError("LLM_ENDPOINT must be specified")
        
        if not OUTPUT_DIR.exists():
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            
        return True


# Global config instance
config = Config()

