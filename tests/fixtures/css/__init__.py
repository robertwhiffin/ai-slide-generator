"""CSS theme fixtures for testing.

Provides three CSS variants:
1. databricks_theme - Full Databricks brand CSS (from user)
2. minimal_theme - Minimal structural CSS
3. ai_generated - No custom CSS (tests inline/generated styles)
"""

from pathlib import Path

_CSS_DIR = Path(__file__).parent


def load_databricks_theme() -> str:
    """Load the full Databricks brand CSS theme."""
    return (_CSS_DIR / "databricks_theme.css").read_text()


def load_minimal_theme() -> str:
    """Load minimal structural CSS."""
    return (_CSS_DIR / "minimal_theme.css").read_text()


def get_ai_generated_css() -> str:
    """Return empty string for AI-generated styling tests.

    When this is used, slides will either have inline styles
    or the LLM will generate its own CSS.
    """
    return ""


__all__ = ["load_databricks_theme", "load_minimal_theme", "get_ai_generated_css"]
