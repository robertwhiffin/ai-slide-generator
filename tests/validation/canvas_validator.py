"""Canvas ID validation for Chart.js integrity.

This is one of the most critical validators - duplicate canvas IDs
are a common source of corruption that causes charts to fail to render.
"""

from collections import Counter
from typing import Dict, List, Set

from bs4 import BeautifulSoup

from src.utils.html_utils import extract_canvas_ids_from_html, extract_canvas_ids_from_script

from .result import ValidationResult


def validate_no_duplicate_canvas_ids(html: str) -> ValidationResult:
    """Validate that no canvas ID appears more than once in the HTML.

    This is the most common source of deck corruption - when the same
    canvas ID is used multiple times, only the last chart will render
    and others will be blank or show errors.

    Args:
        html: HTML string to validate

    Returns:
        ValidationResult with duplicate details if any found
    """
    if not html or not html.strip():
        return ValidationResult.failure(["Empty HTML content"])

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as e:
        return ValidationResult.failure([f"HTML parsing failed: {str(e)}"])

    # Find all canvas elements and collect their IDs
    canvas_elements = soup.find_all("canvas")
    canvas_ids: List[str] = []

    for canvas in canvas_elements:
        canvas_id = canvas.get("id")
        if canvas_id:
            canvas_ids.append(canvas_id)

    # Count occurrences
    id_counts = Counter(canvas_ids)
    duplicates = {id_: count for id_, count in id_counts.items() if count > 1}

    if duplicates:
        error_messages = [
            f"Duplicate canvas ID '{canvas_id}' appears {count} times"
            for canvas_id, count in duplicates.items()
        ]
        return ValidationResult.failure(
            error_messages,
            {
                "total_canvas_elements": len(canvas_elements),
                "unique_ids": len(set(canvas_ids)),
                "duplicates": duplicates,
            },
        )

    return ValidationResult.success(
        {
            "total_canvas_elements": len(canvas_elements),
            "canvas_ids": canvas_ids,
        }
    )


def validate_canvas_ids(html: str, scripts: str = "") -> ValidationResult:
    """Validate canvas-script associations.

    Checks:
    - No duplicate canvas IDs
    - Every canvas with an ID has a corresponding script reference
    - Every script reference has a corresponding canvas element

    Args:
        html: HTML string containing canvas elements
        scripts: JavaScript string containing Chart.js initialization

    Returns:
        ValidationResult with mismatch details if any found
    """
    # First check for duplicates
    dup_result = validate_no_duplicate_canvas_ids(html)
    if not dup_result.valid:
        return dup_result

    # Extract canvas IDs from HTML
    html_canvas_ids = set(extract_canvas_ids_from_html(html))

    # Extract canvas IDs referenced in scripts
    script_canvas_ids = set(extract_canvas_ids_from_script(scripts)) if scripts else set()

    errors: List[str] = []
    warnings: List[str] = []

    # Canvas in HTML but not in scripts (missing chart initialization)
    canvas_without_scripts = html_canvas_ids - script_canvas_ids
    if canvas_without_scripts:
        # This is a warning, not an error - canvases might be used for non-Chart.js purposes
        warnings.append(
            f"Canvas IDs without script references: {sorted(canvas_without_scripts)}"
        )

    # Scripts referencing non-existent canvas (definite error)
    scripts_without_canvas = script_canvas_ids - html_canvas_ids
    if scripts_without_canvas:
        errors.append(
            f"Script references non-existent canvas IDs: {sorted(scripts_without_canvas)}"
        )

    if errors:
        return ValidationResult.failure(
            errors,
            {
                "html_canvas_ids": sorted(html_canvas_ids),
                "script_canvas_ids": sorted(script_canvas_ids),
                "missing_scripts": sorted(canvas_without_scripts),
                "missing_canvas": sorted(scripts_without_canvas),
            },
        )

    result = ValidationResult.success(
        {
            "html_canvas_ids": sorted(html_canvas_ids),
            "script_canvas_ids": sorted(script_canvas_ids),
            "matched_count": len(html_canvas_ids & script_canvas_ids),
        }
    )
    result.warnings = warnings
    return result


def validate_deck_canvas_integrity(deck) -> ValidationResult:
    """Validate canvas integrity for an entire SlideDeck object.

    This is the preferred entry point when you have a SlideDeck instance.

    Args:
        deck: SlideDeck instance to validate

    Returns:
        ValidationResult with comprehensive canvas analysis
    """
    all_canvas_ids: List[str] = []
    all_script_canvas_ids: List[str] = []
    errors: List[str] = []
    warnings: List[str] = []

    # Check each slide
    for i, slide in enumerate(deck.slides):
        # Get canvas IDs from slide HTML
        slide_canvas_ids = extract_canvas_ids_from_html(slide.html)
        all_canvas_ids.extend(slide_canvas_ids)

        # Get canvas IDs from slide scripts
        slide_script_ids = extract_canvas_ids_from_script(slide.scripts)
        all_script_canvas_ids.extend(slide_script_ids)

        # Check for canvas without scripts in this slide
        slide_canvas_set = set(slide_canvas_ids)
        slide_script_set = set(slide_script_ids)

        missing_scripts = slide_canvas_set - slide_script_set
        if missing_scripts:
            warnings.append(
                f"Slide {i}: Canvas IDs without scripts: {sorted(missing_scripts)}"
            )

        orphan_scripts = slide_script_set - slide_canvas_set
        if orphan_scripts:
            errors.append(
                f"Slide {i}: Scripts reference missing canvas: {sorted(orphan_scripts)}"
            )

    # Check for duplicate canvas IDs across entire deck
    id_counts = Counter(all_canvas_ids)
    duplicates = {id_: count for id_, count in id_counts.items() if count > 1}

    if duplicates:
        for canvas_id, count in duplicates.items():
            errors.append(f"Duplicate canvas ID '{canvas_id}' appears {count} times across deck")

    if errors:
        return ValidationResult.failure(
            errors,
            {
                "total_canvas_count": len(all_canvas_ids),
                "unique_canvas_count": len(set(all_canvas_ids)),
                "duplicates": duplicates,
            },
        )

    result = ValidationResult.success(
        {
            "total_canvas_count": len(all_canvas_ids),
            "unique_canvas_count": len(set(all_canvas_ids)),
            "canvas_ids": sorted(set(all_canvas_ids)),
        }
    )
    result.warnings = warnings
    return result
