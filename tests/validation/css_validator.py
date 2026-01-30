"""CSS syntax validation for slide deck styling.

Uses tinycss2 (already in project deps) to parse CSS and catch syntax errors.
"""

from typing import List

import tinycss2

from .result import ValidationResult


def validate_css_syntax(css: str) -> ValidationResult:
    """Validate that CSS code has valid syntax.

    Uses tinycss2 to parse the CSS and catch errors like:
    - Missing/extra braces
    - Invalid selectors
    - Malformed property values

    Args:
        css: CSS code to validate

    Returns:
        ValidationResult with syntax error details if any found
    """
    if not css or not css.strip():
        # Empty CSS is valid
        return ValidationResult.success({"has_content": False, "rule_count": 0})

    errors: List[str] = []
    warnings: List[str] = []

    try:
        # Parse CSS with tinycss2
        rules = tinycss2.parse_stylesheet(css, skip_whitespace=True)
    except Exception as e:
        return ValidationResult.failure([f"CSS parsing failed: {str(e)}"])

    # Count rule types and check for errors
    qualified_rule_count = 0
    at_rule_count = 0
    error_count = 0

    for rule in rules:
        if rule.type == "qualified-rule":
            qualified_rule_count += 1
        elif rule.type == "at-rule":
            at_rule_count += 1
        elif rule.type == "error":
            error_count += 1
            # Get error message
            error_msg = rule.message if hasattr(rule, "message") else str(rule)
            errors.append(f"CSS error at line {rule.source_line}: {error_msg}")

    # Check for essential selectors
    selector_texts = []
    for rule in rules:
        if rule.type == "qualified-rule":
            selector = tinycss2.serialize(rule.prelude).strip()
            selector_texts.append(selector)

    # Warn if .slide selector is missing
    if ".slide" not in " ".join(selector_texts):
        warnings.append("CSS does not contain a .slide selector - slides may not render correctly")

    if errors:
        return ValidationResult.failure(
            errors,
            {
                "rule_count": qualified_rule_count + at_rule_count,
                "error_count": error_count,
            },
        )

    result = ValidationResult.success(
        {
            "has_content": True,
            "qualified_rule_count": qualified_rule_count,
            "at_rule_count": at_rule_count,
            "selectors": selector_texts[:20],  # First 20 selectors
        }
    )
    result.warnings = warnings
    return result


def validate_css_for_slides(css: str) -> ValidationResult:
    """Validate CSS specifically for slide deck usage.

    In addition to basic syntax validation, checks for:
    - Required selectors (.slide)
    - Recommended dimensions
    - Common CSS patterns for presentations

    Args:
        css: CSS code to validate

    Returns:
        ValidationResult with slide-specific validation
    """
    # First do basic syntax validation
    syntax_result = validate_css_syntax(css)
    if not syntax_result.valid:
        return syntax_result

    if not css or not css.strip():
        return ValidationResult.success({"has_content": False})

    warnings: List[str] = []

    # Check for .slide selector with dimensions
    has_slide_width = "width" in css and ".slide" in css
    has_slide_height = "height" in css and ".slide" in css

    if not has_slide_width:
        warnings.append("Consider setting width on .slide (recommended: 1280px)")
    if not has_slide_height:
        warnings.append("Consider setting height on .slide (recommended: 720px)")

    # Check for responsive issues
    if "@media" not in css:
        warnings.append(
            "No @media queries found - CSS may not be responsive"
        )

    result = ValidationResult.success(
        {
            "has_slide_dimensions": has_slide_width and has_slide_height,
            "has_media_queries": "@media" in css,
        }
    )
    result.warnings = warnings
    return result
