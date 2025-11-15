"""Utilities for parsing slide HTML and script content."""

from __future__ import annotations

import re
from typing import Iterable, List

from bs4 import BeautifulSoup

CANVAS_ID_PATTERN = re.compile(r"getElementById\(['\"]([\w-]+)['\"]\)")


def extract_canvas_ids_from_script(script_text: str) -> List[str]:
    """Return canvas ids referenced via document.getElementById calls."""

    if not script_text:
        return []

    matches = CANVAS_ID_PATTERN.findall(script_text)
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


