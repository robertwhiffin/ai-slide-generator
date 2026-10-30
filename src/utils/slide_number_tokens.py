"""Live page-number tokens for graph slides.

Graph slides carry ``{{slide:number}}`` and ``{{slide:count}}`` in their footers.
Every reader boundary renders them as marker spans from the slide's position in
the deck's current order::

    {{slide:number}}  ->  <span data-tellr-slide="number">N</span>
    {{slide:count}}   ->  <span data-tellr-slide="count">M</span>

Every save path turns a marker span back into its token before storing, so a
hand-edited slide (saved with the rendered numbers in it) still renumbers after
a move.

Substitution is markup-safe: a token inside a tag (an attribute value) or inside
a ``<script>``/``<style>`` body is left literal. It is idempotent, and HTML with
no token (or no marker) comes back as an equal string.

``substitute_deck_slide_numbers`` numbers ``deck["slides"]`` by list order and
leaves everything else untouched, including the knitted ``html_content``: a
per-slide position cannot be read reliably from the knitted HTML, and no UI
renders it. It is for outgoing copies only, never for the deck the cache and
saves use.
"""
from __future__ import annotations

import re
from typing import Any, Dict

_TOKEN_RE = re.compile(r"\{\{slide:(number|count)\}\}")
_TAG_SPLIT_RE = re.compile(r"(<[^>]*>)")
_RAW_TEXT_OPEN_RE = re.compile(r"<\s*(script|style)\b", re.IGNORECASE)
_RAW_TEXT_CLOSE_RE = re.compile(r"<\s*/\s*(script|style)\b", re.IGNORECASE)
_MARKER_RE = re.compile(
    r"""<span\b[^>]*?\bdata-tellr-slide\s*=\s*(?P<q>["'])(?P<kind>number|count)(?P=q)[^>]*>"""
    r"""[^<]*</span\s*>""",
    re.IGNORECASE,
)


def substitute_slide_numbers(html: str, number: int, count: int) -> str:
    """Render the page tokens in *html* as marker spans for slide *number* of *count*."""
    if not html or "{{slide:" not in html:
        return html
    values = {"number": number, "count": count}

    def _span(m: "re.Match[str]") -> str:
        kind = m.group(1)
        return f'<span data-tellr-slide="{kind}">{values[kind]}</span>'

    out = []
    raw_depth = False
    for part in _TAG_SPLIT_RE.split(html):
        if not part:
            continue
        if part.startswith("<") and part.endswith(">"):
            if _RAW_TEXT_OPEN_RE.match(part):
                raw_depth = True
            elif _RAW_TEXT_CLOSE_RE.match(part):
                raw_depth = False
            out.append(part)
        elif raw_depth:
            out.append(part)
        else:
            out.append(_TOKEN_RE.sub(_span, part))
    return "".join(out)


def retokenise_slide_numbers(html: str) -> str:
    """Turn page-number marker spans back into their tokens (the save-path inverse)."""
    if not html or "data-tellr-slide" not in html:
        return html
    return _MARKER_RE.sub(lambda m: "{{slide:%s}}" % m.group("kind"), html)


def substitute_deck_slide_numbers(deck_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Substitute page tokens in each slide of *deck_dict* by its list position.

    Returns the dict (slides rebuilt as new dicts; other keys untouched).
    """
    slides = deck_dict.get("slides") if deck_dict else None
    if not slides:
        return deck_dict
    count = len(slides)
    deck_dict["slides"] = [
        {**s, "html": substitute_slide_numbers(s["html"], i + 1, count)}
        if isinstance(s, dict) and isinstance(s.get("html"), str)
        else s
        for i, s in enumerate(slides)
    ]
    return deck_dict
