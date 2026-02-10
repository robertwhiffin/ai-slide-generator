"""HTML fixture generators for testing.

Provides functions to generate realistic slide deck HTML with:
- Variable slide counts (3, 6, 9, 12)
- Different slide types (title, content, chart, table)
- Multiple CSS themes
- Canvas elements for Chart.js testing
"""

from pathlib import Path
from typing import Optional

from .generators import (
    generate_deck_html,
    generate_chart_slide,
    generate_content_slide,
    generate_title_slide,
    generate_table_slide,
)
from .edit_responses import (
    get_recolor_chart_response,
    get_reword_content_response,
    get_add_slide_response,
    get_consolidate_slides_response,
)

_HTML_DIR = Path(__file__).parent


def load_3_slide_deck(css: str = "") -> str:
    """Generate a 3-slide deck (title + 2 content)."""
    return generate_deck_html(slide_count=3, css=css)


def load_6_slide_deck(css: str = "") -> str:
    """Generate a 6-slide deck (title + section + 4 content)."""
    return generate_deck_html(slide_count=6, css=css)


def load_9_slide_deck(css: str = "") -> str:
    """Generate a 9-slide deck (title + 2 sections + 6 content)."""
    return generate_deck_html(slide_count=9, css=css)


def load_12_slide_deck(css: str = "") -> str:
    """Generate a 12-slide deck (title + 3 sections + 8 content)."""
    return generate_deck_html(slide_count=12, css=css)


__all__ = [
    "load_3_slide_deck",
    "load_6_slide_deck",
    "load_9_slide_deck",
    "load_12_slide_deck",
    "generate_deck_html",
    "generate_chart_slide",
    "generate_content_slide",
    "generate_title_slide",
    "generate_table_slide",
    "get_recolor_chart_response",
    "get_reword_content_response",
    "get_add_slide_response",
    "get_consolidate_slides_response",
]
