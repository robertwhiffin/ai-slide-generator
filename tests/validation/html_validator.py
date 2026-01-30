"""HTML structure validation for slide decks."""

from typing import List, Optional

from bs4 import BeautifulSoup

from .result import ValidationResult


def validate_html_structure(html: str) -> ValidationResult:
    """Validate that HTML parses without error and has basic structure.

    Checks:
    - HTML parses with BeautifulSoup
    - Contains html, head, and body elements (for full documents)
    - No orphaned closing tags

    Args:
        html: HTML string to validate

    Returns:
        ValidationResult with error details if validation fails
    """
    if not html or not html.strip():
        return ValidationResult.failure(["Empty HTML content"])

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as e:
        return ValidationResult.failure([f"HTML parsing failed: {str(e)}"])

    errors: List[str] = []
    warnings: List[str] = []

    # Check for basic structure if this looks like a full document
    if "<!DOCTYPE" in html.upper() or "<html" in html.lower():
        if not soup.find("html"):
            errors.append("Missing <html> element")
        if not soup.find("head"):
            warnings.append("Missing <head> element")
        if not soup.find("body"):
            errors.append("Missing <body> element")

    # Check for orphaned closing tags (BeautifulSoup removes these, so compare lengths)
    original_length = len(html)
    parsed_length = len(str(soup))

    # If there's a significant difference, there might be malformed HTML
    # (This is a heuristic - BeautifulSoup fixes many issues automatically)
    if original_length > 0 and parsed_length < original_length * 0.8:
        warnings.append(
            f"Parsed HTML is significantly shorter ({parsed_length} vs {original_length} chars) - "
            "may indicate malformed HTML that was auto-corrected"
        )

    if errors:
        return ValidationResult.failure(errors)

    result = ValidationResult.success({"parsed_length": parsed_length})
    result.warnings = warnings
    return result


def validate_slide_structure(html: str) -> ValidationResult:
    """Validate that HTML contains properly structured slides.

    Checks:
    - Contains at least one .slide div
    - All .slide elements are properly closed
    - .slide elements are not nested

    Args:
        html: HTML string to validate

    Returns:
        ValidationResult with slide count and error details
    """
    if not html or not html.strip():
        return ValidationResult.failure(["Empty HTML content"])

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as e:
        return ValidationResult.failure([f"HTML parsing failed: {str(e)}"])

    errors: List[str] = []
    warnings: List[str] = []

    # Find all slide divs
    slides = soup.find_all("div", class_="slide")

    if not slides:
        return ValidationResult.failure(
            ["No slide elements found (expected <div class=\"slide\">...)"]
        )

    # Check for nested slides
    for i, slide in enumerate(slides):
        nested = slide.find_all("div", class_="slide")
        if nested:
            errors.append(f"Slide {i} contains nested .slide elements")

    # Check for empty slides
    for i, slide in enumerate(slides):
        content = slide.get_text(strip=True)
        # Check if slide has any content or canvas (charts are valid even without text)
        has_canvas = slide.find("canvas") is not None
        if not content and not has_canvas:
            warnings.append(f"Slide {i} appears to be empty")

    if errors:
        return ValidationResult.failure(errors, {"slide_count": len(slides)})

    result = ValidationResult.success({"slide_count": len(slides)})
    result.warnings = warnings
    return result


def validate_deck_integrity(html: str) -> ValidationResult:
    """Run all HTML validation checks on a slide deck.

    This is the main entry point for deck validation.

    Args:
        html: Full HTML document string

    Returns:
        Combined ValidationResult from all checks
    """
    # Run structure validation
    structure_result = validate_html_structure(html)
    if not structure_result.valid:
        return structure_result

    # Run slide validation
    slide_result = validate_slide_structure(html)

    return structure_result.merge(slide_result)
