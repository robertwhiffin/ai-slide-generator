"""Live page-number tokens for graph slides.

Graph slides carry ``{{slide:number}}`` and ``{{slide:count}}`` in their footers.
Every reader boundary renders them as marker spans from the slide's position in
the deck's current order::

    {{slide:number}}  ->  <span data-tellr-slide="number">N</span>
    {{slide:count}}   ->  <span data-tellr-slide="count">M</span>

Every save path turns a marker span back into its token before storing, so a
hand-edited slide (saved with the rendered numbers in it) still renumbers after
a move.

Substitution is markup-safe. A token is replaced only in text content. One inside
a tag (an attribute value, even one holding ``>``), inside a whole
``<script>``/``<style>`` element (whatever its body holds, ``<`` or a stray
``</style>`` included) or inside a comment is left literal. Tags are found as a
browser finds them: a ``<`` that starts no tag name is text (``x < 10``), and only
an attribute value after ``=`` is quoted, so an apostrophe in text never hides
the footer. The values are
coerced to ``int``, so nothing but digits is ever emitted. Substitution is
idempotent, and HTML with no token (or no marker) comes back as an equal string.

Retokenising accepts any plain inner text (the user may have retyped the digit)
and normalises the kind to lower case. A marker whose content holds a tag, for
example a number the visual editor bolded inside the span
(``<span data-tellr-slide="number"><b>3</b></span>``), is not recognised: that
slide keeps the number baked in. This is accepted, like an editor stripping the
marker.

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
#: Inside a tag, as the HTML tokenizer reads it: a quoted attribute value (after
#: ``=``) is taken whole, to its closing quote or the end of the input, so a ``>``
#: inside it does not end the tag; any other character but ``>`` is plain, a quote
#: included (``don't`` in text a browser reads as a tag opens no quoted run).  The
#: alternatives cannot both match at one place, so a scan never backtracks.
_IN_TAG = r"""(?:[^>=]|=\s*"[^"]*(?:"|\Z)|=\s*'[^']*(?:'|\Z)|=(?!\s*["']))*"""
#: The stretches substitution never touches: a whole script or style element
#: (an unclosed one runs to the end, as a browser reads it), a comment, a tag.  A
#: tag starts only where a tag name, ``/``, ``!`` or ``?`` follows the ``<``; any
#: other ``<`` is text (``x < 10``), as it is to a browser.  An unclosed tag runs
#: to the end.
_SKIP_RE = re.compile(
    r"<(script|style)\b" + _IN_TAG + r">.*?(?:</\1\s*>|\Z)"
    r"|<!--.*?(?:-->|\Z)"
    r"|<(?=[A-Za-z/!?])" + _IN_TAG + r"(?:>|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_MARKER_RE = re.compile(
    r"""<span\b[^>]*?\bdata-tellr-slide\s*=\s*(?P<q>["'])(?P<kind>number|count)(?P=q)[^>]*>"""
    r"""[^<]*</span\s*>""",
    re.IGNORECASE,
)


def substitute_slide_numbers(html: str, number: int, count: int) -> str:
    """Render the page tokens in *html* as marker spans for slide *number* of *count*."""
    if not html or "{{slide:" not in html:
        return html
    values = {"number": int(number), "count": int(count)}

    def _span(m: "re.Match[str]") -> str:
        kind = m.group(1)
        return f'<span data-tellr-slide="{kind}">{values[kind]}</span>'

    out = []
    pos = 0
    for skip in _SKIP_RE.finditer(html):
        out.append(_TOKEN_RE.sub(_span, html[pos : skip.start()]))
        out.append(skip.group(0))
        pos = skip.end()
    out.append(_TOKEN_RE.sub(_span, html[pos:]))
    return "".join(out)


def retokenise_slide_numbers(html: str) -> str:
    """Turn page-number marker spans back into their tokens (the save-path inverse)."""
    if not html or "data-tellr-slide" not in html:
        return html
    return _MARKER_RE.sub(lambda m: "{{slide:%s}}" % m.group("kind").lower(), html)


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
