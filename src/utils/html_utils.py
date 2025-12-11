"""Utilities for parsing slide HTML and script content."""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

from bs4 import BeautifulSoup

CANVAS_ID_PATTERN = re.compile(r"getElementById\s*\(\s*['\"]([\w\-.:]+)['\"]\s*\)")
QUERY_SELECTOR_PATTERN = re.compile(r"querySelector\s*\(\s*['\"]#([\w\-.:]+)['\"]\s*\)")
CANVAS_COMMENT_PATTERN = re.compile(r"//\s*Canvas:\s*([\w\-.:]+)", re.IGNORECASE)

# Pattern to detect chart block boundaries (comments like "// Chart 1:" or "// Canvas: foo")
CHART_BLOCK_COMMENT_PATTERN = re.compile(
    r"^\s*//\s*(?:Chart\s*\d+\s*[:\-]|Canvas\s*[:\-])",
    re.IGNORECASE | re.MULTILINE,
)


def extract_canvas_ids_from_script(script_text: str) -> List[str]:
    """Return canvas ids referenced via document.getElementById calls."""

    if not script_text:
        return []

    matches = CANVAS_ID_PATTERN.findall(script_text)
    matches.extend(QUERY_SELECTOR_PATTERN.findall(script_text))
    matches.extend(CANVAS_COMMENT_PATTERN.findall(script_text))
    # Preserve order while removing duplicates
    seen: set[str] = set()
    ordered: list[str] = []
    for canvas_id in matches:
        if canvas_id not in seen:
            seen.add(canvas_id)
            ordered.append(canvas_id)
    return ordered


def extract_canvas_ids_from_html(html_content: str) -> List[str]:
    """Collect canvas ids defined within arbitrary HTML content."""

    if not html_content:
        return []

    soup = BeautifulSoup(html_content, "html.parser")
    canvas_ids: list[str] = []
    for canvas in soup.find_all("canvas"):
        canvas_id = canvas.get("id")
        if canvas_id:
            canvas_ids.append(canvas_id)
    return canvas_ids


def split_script_by_canvas(script_text: str) -> List[Tuple[str, List[str]]]:
    """Split a multi-canvas script into individual per-canvas segments.

    Detects chart block boundaries by looking for patterns like:
    - `// Chart 1:` or `// Chart 2 -`
    - `// Canvas: chartId`
    - getElementById/querySelector calls

    Each segment is associated with the canvas IDs it references.

    Args:
        script_text: JavaScript code that may contain multiple chart definitions

    Returns:
        List of (script_segment, canvas_ids) tuples. If the script cannot be
        meaningfully split, returns a single tuple with all canvas IDs.
    """
    if not script_text or not script_text.strip():
        return []

    all_canvas_ids = extract_canvas_ids_from_script(script_text)

    # If 0 or 1 canvas, no splitting needed
    if len(all_canvas_ids) <= 1:
        return [(script_text.strip(), all_canvas_ids)]

    # Try to split by finding canvas-specific code blocks
    segments = _split_by_canvas_boundaries(script_text, all_canvas_ids)

    if segments:
        return segments

    # Fallback: return as single block (legacy behavior)
    return [(script_text.strip(), all_canvas_ids)]


def _find_canvas_code_start(script_text: str, canvas_id: str) -> int:
    """Find the start position of code for a specific canvas.

    Looks for patterns in order of specificity:
    1. `// Canvas: <id>` comment marker (most specific)
    2. `// Chart N:` comment before the getElementById call
    3. Variable declaration like `const canvasN = document.getElementById`
    """
    # Look for explicit Canvas comment marker
    marker_pattern = re.compile(
        rf"//\s*Canvas:\s*{re.escape(canvas_id)}\b",
        re.IGNORECASE,
    )
    marker_match = marker_pattern.search(script_text)
    if marker_match:
        # Find start of line
        line_start = script_text.rfind("\n", 0, marker_match.start())
        return line_start + 1 if line_start >= 0 else 0

    # Look for getElementById call and find preceding comment/block start
    get_elem_pattern = re.compile(
        rf"getElementById\s*\(\s*['\"]({re.escape(canvas_id)})['\"]",
    )
    get_elem_match = get_elem_pattern.search(script_text)

    if get_elem_match:
        pos = get_elem_match.start()
        # Walk backward to find block start (comment or variable declaration)
        block_start = _find_block_start_before_position(script_text, pos)
        return block_start

    return -1


def _find_block_start_before_position(script_text: str, pos: int) -> int:
    """Find the start of a code block before the given position.

    Looks for:
    - Comment lines like `// Chart N:`
    - Variable declarations like `const canvas`
    - Start of script
    """
    # Get text before position
    preceding = script_text[:pos]

    # Find the last newline before position to get start of current line
    last_newline = preceding.rfind("\n")
    if last_newline < 0:
        return 0

    # Look for chart comment in preceding lines
    lines_before = preceding[:last_newline]
    comment_pattern = re.compile(
        r"^\s*//\s*(?:Chart\s*\d+\s*[:\-]|Canvas\s*[:\-])",
        re.IGNORECASE | re.MULTILINE,
    )

    # Find the last chart comment before this position
    last_comment = None
    for match in comment_pattern.finditer(lines_before):
        # Check if there's a blank line between comment and current position
        text_between = lines_before[match.end() :]
        if "\n\n" not in text_between:  # No blank line gap
            last_comment = match

    if last_comment:
        # Return start of comment line
        line_start = lines_before.rfind("\n", 0, last_comment.start())
        return line_start + 1 if line_start >= 0 else 0

    # Look for variable declaration on lines leading up to getElementById
    var_pattern = re.compile(
        r"^\s*(?:const|let|var)\s+\w+\s*=",
        re.MULTILINE,
    )
    # Find the last variable declaration before the getElementById line
    for match in var_pattern.finditer(lines_before):
        text_after = lines_before[match.end() :]
        # If this var declaration is close to our target (within a few lines)
        if text_after.count("\n") <= 2:
            line_start = lines_before.rfind("\n", 0, match.start())
            return line_start + 1 if line_start >= 0 else 0

    # Default: start from beginning of current logical block
    return last_newline + 1


def _split_by_canvas_boundaries(
    script_text: str,
    canvas_ids: List[str],
) -> List[Tuple[str, List[str]]]:
    """Split script into segments based on canvas code boundaries.

    Returns:
        List of (segment_text, [canvas_id]) tuples, or empty list if
        splitting fails.
    """
    # Find start positions for each canvas
    positions: List[Tuple[int, str]] = []

    for canvas_id in canvas_ids:
        start = _find_canvas_code_start(script_text, canvas_id)
        if start >= 0:
            positions.append((start, canvas_id))

    # Need at least 2 distinct positions to split
    if len(positions) < 2:
        return []

    # Sort by position
    positions.sort(key=lambda x: x[0])

    # Check for overlapping positions (same start = can't split)
    unique_starts = {pos for pos, _ in positions}
    if len(unique_starts) < len(positions):
        return []

    # Extract segments
    segments: List[Tuple[str, List[str]]] = []

    for i, (start, canvas_id) in enumerate(positions):
        if i + 1 < len(positions):
            end = positions[i + 1][0]
        else:
            end = len(script_text)

        segment_text = script_text[start:end].strip()
        if segment_text:
            segments.append((segment_text, [canvas_id]))

    return segments


