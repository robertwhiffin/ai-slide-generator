"""Fixtures and helpers for sample HTML test files.

This module provides:
- Path constants for all sample HTML files in tests/sample_htmls/
- Fixture functions to load file contents
- HTML normalization helper for exact-match comparison
"""

from pathlib import Path
from typing import Dict

from bs4 import BeautifulSoup, NavigableString


# Base path for sample HTML files
SAMPLE_HTMLS_DIR = Path(__file__).parent.parent / "sample_htmls"

# Path constants for each sample file
ORIGINAL_DECK_PATH = SAMPLE_HTMLS_DIR / "original_deck.html"
UPDATE1_PATH = SAMPLE_HTMLS_DIR / "update1.html"
UPDATE2_PATH = SAMPLE_HTMLS_DIR / "update2.html"
UPDATE3_PATH = SAMPLE_HTMLS_DIR / "update3.html"
FINAL_HTML_PATH = SAMPLE_HTMLS_DIR / "final_html.html"


def load_sample_html(path: Path) -> str:
    """Load sample HTML file content.
    
    Args:
        path: Path to the HTML file
        
    Returns:
        File content as string
        
    Raises:
        FileNotFoundError: If file doesn't exist
    """
    if not path.exists():
        raise FileNotFoundError(f"Sample HTML file not found: {path}")
    return path.read_text(encoding="utf-8")


def load_original_deck() -> str:
    """Load original_deck.html content."""
    return load_sample_html(ORIGINAL_DECK_PATH)


def load_update1() -> str:
    """Load update1.html content (replacement for slide 3)."""
    return load_sample_html(UPDATE1_PATH)


def load_update2() -> str:
    """Load update2.html content (replacement for slide 6)."""
    return load_sample_html(UPDATE2_PATH)


def load_update3() -> str:
    """Load update3.html content (replacement for slides 13-15)."""
    return load_sample_html(UPDATE3_PATH)


def load_final_html() -> str:
    """Load final_html.html content (expected output after all updates)."""
    return load_sample_html(FINAL_HTML_PATH)


def normalize_html(html: str) -> str:
    """Normalize HTML for exact-match comparison.
    
    Normalization steps:
    1. Parse with BeautifulSoup
    2. Remove whitespace-only text nodes
    3. Sort attributes alphabetically on each element
    4. Re-serialize with consistent formatting
    
    Args:
        html: Raw HTML string
        
    Returns:
        Normalized HTML string suitable for comparison
    """
    soup = BeautifulSoup(html, "html.parser")
    
    # Remove whitespace-only text nodes
    _remove_whitespace_nodes(soup)
    
    # Sort attributes on all elements
    _sort_attributes(soup)
    
    # Serialize with consistent formatting
    return soup.prettify()


def _remove_whitespace_nodes(soup: BeautifulSoup) -> None:
    """Remove text nodes that contain only whitespace."""
    for element in soup.find_all(string=True):
        if isinstance(element, NavigableString):
            if element.strip() == "":
                element.extract()


def _sort_attributes(soup: BeautifulSoup) -> None:
    """Sort attributes alphabetically on all elements."""
    for tag in soup.find_all(True):  # Find all tags
        if tag.attrs:
            # Sort attributes by key
            tag.attrs = dict(sorted(tag.attrs.items()))


def get_update_config() -> Dict[str, Dict]:
    """Get configuration for each update operation.
    
    Returns:
        Dictionary mapping update name to its configuration:
        - path: Path to update HTML file
        - original_indices: Indices of slides being replaced (0-indexed)
        - expected_replacement_count: Number of slides in replacement
    """
    return {
        "update1": {
            "path": UPDATE1_PATH,
            "original_indices": [2],  # Slide 3 (0-indexed)
            "expected_replacement_count": 1,
            "description": "Replace slide 3 with modified bar chart colors",
        },
        "update2": {
            "path": UPDATE2_PATH,
            "original_indices": [5],  # Slide 6 (0-indexed)
            "expected_replacement_count": 1,
            "description": "Replace slide 6 with line chart instead of bar",
        },
        "update3": {
            "path": UPDATE3_PATH,
            "original_indices": [12, 13, 14],  # Slides 13-15 (0-indexed)
            "expected_replacement_count": 1,
            "description": "Consolidate slides 13-15 into single slide",
        },
    }

