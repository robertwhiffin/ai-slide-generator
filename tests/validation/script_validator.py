"""JavaScript syntax validation for Chart.js scripts.

Uses esprima to parse JavaScript and catch syntax errors that would
cause chart initialization to fail at runtime.
"""

import re
from typing import List, Optional

import esprima

from .result import ValidationResult


def validate_javascript_syntax(script: str) -> ValidationResult:
    """Validate that JavaScript code has valid syntax.

    Uses esprima to parse the script and catch syntax errors like:
    - Missing/extra brackets, braces, parentheses
    - Invalid tokens
    - Unterminated strings
    - Invalid JSON in Chart.js config

    Args:
        script: JavaScript code to validate

    Returns:
        ValidationResult with syntax error details if any found
    """
    if not script or not script.strip():
        # Empty script is valid
        return ValidationResult.success({"has_content": False})

    errors: List[str] = []
    warnings: List[str] = []

    try:
        # Parse with esprima - this will throw on syntax errors
        esprima.parseScript(script, {"tolerant": False})
    except esprima.Error as e:
        # Extract useful error information
        error_msg = str(e)

        # Try to extract line number from error
        line_match = re.search(r"Line (\d+)", error_msg)
        line_num = int(line_match.group(1)) if line_match else None

        # Get context around the error
        context = _get_error_context(script, line_num) if line_num else None

        errors.append(f"JavaScript syntax error: {error_msg}")
        if context:
            errors.append(f"Context: {context}")

        return ValidationResult.failure(
            errors,
            {
                "error_line": line_num,
                "error_message": error_msg,
            },
        )
    except Exception as e:
        # Catch any other parsing errors
        errors.append(f"JavaScript parsing failed: {str(e)}")
        return ValidationResult.failure(errors)

    # Additional heuristic checks for common Chart.js issues
    warnings.extend(_check_common_issues(script))

    result = ValidationResult.success(
        {
            "has_content": True,
            "char_count": len(script),
            "line_count": script.count("\n") + 1,
        }
    )
    result.warnings = warnings
    return result


def _get_error_context(script: str, line_num: int, context_lines: int = 2) -> Optional[str]:
    """Get a few lines of context around an error.

    Args:
        script: Full script content
        line_num: 1-indexed line number of error
        context_lines: Number of lines before/after to include

    Returns:
        String with context lines, or None if line_num is invalid
    """
    lines = script.split("\n")
    if line_num < 1 or line_num > len(lines):
        return None

    start = max(0, line_num - 1 - context_lines)
    end = min(len(lines), line_num + context_lines)

    context_parts = []
    for i in range(start, end):
        prefix = ">>> " if i == line_num - 1 else "    "
        context_parts.append(f"{prefix}{i + 1}: {lines[i]}")

    return "\n".join(context_parts)


def _check_common_issues(script: str) -> List[str]:
    """Check for common Chart.js configuration issues.

    These are warnings, not errors - the code may still work
    but could indicate potential problems.

    Args:
        script: JavaScript code to check

    Returns:
        List of warning messages
    """
    warnings: List[str] = []

    # Check for common Chart.js issues

    # Missing Chart constructor
    if "canvas" in script.lower() and "Chart" not in script:
        warnings.append(
            "Script references canvas but doesn't use Chart constructor"
        )

    # Check for getElementById without null check
    # (This is a common source of silent failures)
    if "getElementById" in script and "if" not in script:
        warnings.append(
            "getElementById used without null check - may fail silently if canvas not found"
        )

    # Check for potential undefined variable issues
    # (Looking for assignments to undeclared variables)
    if re.search(r"^\s*[a-zA-Z_]\w*\s*=\s*[^=]", script, re.MULTILINE):
        # This pattern matches assignments that might be to global/undeclared vars
        # Skip if const/let/var is present on same line
        lines_with_assignments = re.findall(
            r"^\s*([a-zA-Z_]\w*)\s*=\s*[^=].*$", script, re.MULTILINE
        )
        for var_name in lines_with_assignments:
            # Check if this variable is declared elsewhere
            decl_pattern = rf"\b(const|let|var)\s+{re.escape(var_name)}\b"
            if not re.search(decl_pattern, script):
                # Could be a property assignment, which is fine
                if "." not in var_name:
                    warnings.append(
                        f"Possible undeclared variable: '{var_name}' - consider using const/let"
                    )
                break  # Only report first occurrence

    return warnings


def validate_chart_js_config(script: str) -> ValidationResult:
    """Specifically validate Chart.js configuration objects.

    This checks that Chart.js initialization calls have valid config.

    Args:
        script: JavaScript containing Chart.js code

    Returns:
        ValidationResult with Chart.js specific issues
    """
    if not script or not script.strip():
        return ValidationResult.success({"chart_count": 0})

    # First validate basic syntax
    syntax_result = validate_javascript_syntax(script)
    if not syntax_result.valid:
        return syntax_result

    errors: List[str] = []
    warnings: List[str] = []

    # Count Chart constructors
    chart_matches = re.findall(r"new\s+Chart\s*\(", script)
    chart_count = len(chart_matches)

    if chart_count == 0 and "chart" in script.lower():
        warnings.append(
            "Script mentions 'chart' but no 'new Chart()' constructor found"
        )

    # Check for common Chart.js configuration issues
    if chart_count > 0:
        # Check for missing type
        if "type:" not in script and "'type'" not in script and '"type"' not in script:
            warnings.append(
                "Chart.js config may be missing 'type' property"
            )

        # Check for missing data
        if "data:" not in script and "'data'" not in script and '"data"' not in script:
            warnings.append(
                "Chart.js config may be missing 'data' property"
            )

    if errors:
        return ValidationResult.failure(errors, {"chart_count": chart_count})

    result = ValidationResult.success({"chart_count": chart_count})
    result.warnings = warnings
    return result
