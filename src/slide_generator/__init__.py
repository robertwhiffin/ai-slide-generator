"""
Slide Generator - AI-powered slide deck creation tool.

This package provides tools for creating professional slide decks using natural language
and AI assistance, with support for HTML and PowerPoint output formats.
"""

__version__ = "0.1.0"
__author__ = "Your Name"

# Main exports
from .core.chatbot import Chatbot
from .tools.html_slides import HtmlDeck, SlideTheme

__all__ = [
    "Chatbot", 
    "HtmlDeck", 
    "SlideTheme",
    "__version__",
]

