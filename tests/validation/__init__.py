"""Validation utilities for testing slide deck integrity.

This module provides validators that check for common corruption patterns:
- Duplicate canvas IDs
- Invalid JavaScript syntax
- Malformed HTML structure
- Invalid CSS

All validators return ValidationResult objects with success status and error details.
"""

from .result import ValidationResult
from .canvas_validator import validate_canvas_ids, validate_no_duplicate_canvas_ids
from .css_validator import validate_css_syntax
from .html_validator import validate_html_structure, validate_slide_structure
from .script_validator import validate_javascript_syntax

__all__ = [
    "ValidationResult",
    "validate_canvas_ids",
    "validate_no_duplicate_canvas_ids",
    "validate_css_syntax",
    "validate_html_structure",
    "validate_slide_structure",
    "validate_javascript_syntax",
]
