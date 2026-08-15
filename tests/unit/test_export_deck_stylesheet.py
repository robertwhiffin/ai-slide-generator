"""WF-03: the deck's CSS is a STYLESHEET OF ITS OWN, so its leading ``@import`` survives.

THE DEFECT. ``build_slide_html`` used to emit ``*{}`` and ``html,body{}`` ahead of the
deck's CSS inside a SINGLE ``<style>``. ``@import`` is only valid before every other rule
of its own stylesheet, so a deck whose CSS opens with
``@import url('https://fonts.googleapis.com/css2?family=Inter…')`` had that rule DISCARDED
in the export while the UI kept it — measured as 0 font faces against 35, and the whole of
the 38.25 px per-component residual on the DS-OFF deck.

THE FIX IS STRUCTURAL, not a rewrite. Two ``<style>`` elements are two stylesheets, so the
deck gets its own: its leading ``@import`` is already first in that sheet. Cascade order
across separate ``<style>`` elements is DOCUMENT order, so resets -> deck -> resets keeps
exactly the precedence the one combined sheet had. Confirmed in Chromium under the real
SLIDE_CSP: combined = 1 sheet / 0 font faces / import dead; split = 2 sheets / font faces
registered / import applied; and with reset and deck setting one property at equal
specificity, the deck still wins.

WHAT REPLACED WHAT. This file used to test a hand-written leading-``@charset``/``@import``
scanner, including SEVEN pinned sha256 byte-identity digests. That scanner is DELETED and
those digests are RETIRED deliberately: the document now changes structurally for EVERY
deck, not only decks with an ``@import``, so byte-identity against the pre-WF-03 output is
no longer the right property to assert. What replaced it is RENDERING equivalence, measured
in Chromium on real DS and DS-OFF decks, plus the verbatim-passthrough contract below.

Three rounds of review found five tokenizer defects in that scanner — ``str.isspace()``
accepting NBSP, an unescaped top-level ``\\)``, a lone ``@charset`` rewriting the document,
an ASCII-only ident guard, and a missed ``@layer name;`` statement (which may legally
precede ``@import``). All five were bugs in DECIDING what the deck's CSS means. Not
deciding is what makes them unreachable, and that is what the parametrized test below
pins: the deck's CSS is emitted BYTE-FOR-BYTE, whatever it contains.
"""
import re

import pytest

from src.api.routes.export import build_slide_html
from src.utils.html_safety import SLIDE_ROOT_RESET_STYLE

_SLIDE = {"slide_id": "s1", "html": '<div class="slide">hi</div>'}

#: The real shape: a Google Fonts URL whose query contains SEMICOLONS.
_FONT_IMPORT = (
    "@import url('https://fonts.googleapis.com/css2?"
    "family=Inter:wght@400;500;600;700&display=swap');"
)

#: A realistic deck CSS body with NO ``@import`` — the majority case.
_REALISTIC_DECK_CSS = """/* Deck styles — generated */
.slide {
  width: 1280px;
  height: 720px;
  padding: 72px 88px;
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
  background: #0b1021;
  color: #f8fafc;
}
.slide h1 { font-size: 64px; line-height: 1.1; font-weight: 700; }
.slide .eyebrow::after { content: "; "; }
@media print { .slide { break-inside: avoid; } }
"""

# Every input that broke, or was argued about, across three rounds of review of the
# deleted scanner. Each is a case where deciding "is this a leading @import?" went wrong.
# The contract now is that NOTHING decides: the bytes go through untouched and the browser
# reads the deck's stylesheet exactly as the deck author wrote it.
_PASSTHROUGH_CASES = {
    "font-import": f"{_FONT_IMPORT}\n.slide {{ color: red }}",
    "realistic-no-import": _REALISTIC_DECK_CSS,
    "empty": "",
    "whitespace-only": "  \n\t\n",
    "comment-only": "/* nothing but a banner */",
    "comment-then-import": f"/* Brand fonts */\n{_FONT_IMPORT}\n.slide {{ color: red }}",
    "charset-only": '@charset "UTF-8";\n.x {}',
    "charset-then-import": f'@charset "UTF-8";\n{_FONT_IMPORT}\n.x {{ color: red }}',
    "mid-sheet-import": f".slide {{ color: red }}\n{_FONT_IMPORT}",
    "several-imports": f"{_FONT_IMPORT}\n@import url('https://example.test/b.css');\n.x {{}}",
    "unterminated-import": "@import url('https://example.test/a.css')\n.x { color: red }",
    "imports-plural": "@imports url('https://example.test/a.css');\n.x { color: red }",
    # `@layer name;` is a STATEMENT and may legally precede `@import`; the deleted scanner
    # stopped at it and re-lost the font for ordinary modern CSS.
    "layer-statement": (
        "@layer reset;\n"
        '@import url("data:text/css,.x%7Bcolor%3Argb(1%2C2%2C3)%7D") layer(reset);\n'
        ".x { background: red }"
    ),
    # The BLOCK form may NOT precede an import. Nothing here has to know that.
    "layer-block": "@layer reset { .x { color: red } }\n" + _FONT_IMPORT,
    # U+00A0 is an ident code point, not white space: the browser sees no leading at-rule
    # here at all. The scanner hoisted anyway and CHANGED COMPUTED STYLE.
    "nbsp-then-import": (
        "\u00a0@import url(https://example.invalid/x.css);\n.x { color: rgb(1, 2, 3); }"
    ),
    # `\)` is DATA inside an unquoted url(); reading it as the closing paren split a valid
    # rule and left `bar.css);` behind.
    "escaped-paren": (
        "@import url(https://example.invalid/foo\\);bar.css);\n.x { color: red }"
    ),
    # `@importé` is ONE unknown at-keyword, not `@import` plus junk.
    "non-ascii-ident": "@importé url('https://example.invalid/x.css');\n.x { color: red }",
    # CSS preprocessing turns NUL into U+FFFD, so this is a different at-keyword too.
    "nul-byte": "@import\x00url(x);.x{color:red}",
    # Top-level `<!--` is ignored by CSS parsing, so this DOES carry a valid leading import.
    "html-comment-open": "<!--@import url(x);\n.x { color: red }",
    # CSS normalises a lone CR to LF, which ends an unterminated string.
    "cr-in-string": '@import "x\r.x{color:red}";\n.y { color: blue }',
}


def _deck(css: str) -> dict:
    return {"title": "T", "css": css, "scripts": "", "external_scripts": []}


def _style_blocks(html: str) -> list[str]:
    """The document's <style> element contents, in document order."""
    return re.findall(r"<style>(.*?)</style>", html, re.DOTALL)


def _deck_stylesheet_index(blocks: list[str], css: str) -> int:
    """Index of the <style> element that is the deck's own stylesheet."""
    for index, block in enumerate(blocks):
        if block == css:
            return index
    raise AssertionError(
        f"no <style> element holds the deck CSS verbatim; blocks were "
        f"{[b[:60] for b in blocks]}"
    )


@pytest.mark.parametrize("case_name", sorted(_PASSTHROUGH_CASES))
def test_the_deck_css_is_emitted_byte_for_byte_in_its_own_stylesheet(case_name):
    """THE contract, and the whole reason no CSS parsing survives here.

    One `<style>` element holds the deck's CSS and NOTHING else — not a hoisted rule, not
    an injected reset, not added indentation. So whatever the deck wrote is what starts
    that stylesheet, and every question the deleted scanner used to answer wrongly (is
    this NBSP white space? is `@layer reset;` hoistable? is `\\)` a closing paren?) is the
    browser's to answer, exactly as it is for the deck's own sheet.
    """
    css = _PASSTHROUGH_CASES[case_name]
    blocks = _style_blocks(build_slide_html(_SLIDE, _deck(css)))

    assert css in blocks, (
        f"the deck CSS for {case_name!r} was not emitted verbatim as its own stylesheet; "
        f"blocks were {[b[:80] for b in blocks]}"
    )


def test_a_leading_import_is_the_first_thing_in_the_decks_stylesheet():
    """Why the structure fixes WF-03: `@import` only has to precede the other rules of ITS
    OWN sheet, and here it does, with nothing injected ahead of it."""
    css = f"{_FONT_IMPORT}\n.slide {{ color: red }}"
    blocks = _style_blocks(build_slide_html(_SLIDE, _deck(css)))

    deck_sheet = blocks[_deck_stylesheet_index(blocks, css)]
    assert deck_sheet.startswith("@import"), repr(deck_sheet[:120])
    # Exactly once, and only in the deck's own sheet: the old hoist could leave a copy
    # behind in an invalid position, which silently double-fetched the font. (Counted
    # within this sheet only — the post-deck sheet mentions `@import` in a comment.)
    assert deck_sheet.count("@import") == 1, deck_sheet.count("@import")
    assert not any(b.startswith("@import") for i, b in enumerate(blocks) if b != css)


def test_the_injected_resets_are_an_earlier_stylesheet_than_the_deck():
    """Cascade preservation, half one. The resets must still precede the deck so the deck
    can override them — now by DOCUMENT ORDER across sheets rather than within one."""
    css = _REALISTIC_DECK_CSS
    blocks = _style_blocks(build_slide_html(_SLIDE, _deck(css)))
    deck_index = _deck_stylesheet_index(blocks, css)

    assert deck_index > 0, "the deck's sheet must not be first"
    # Witnessed by the fixed-frame shell sizing, NOT by a `box-sizing` substring:
    # that reset is scoped to `html, body` now (it was universal, which made slide
    # descendants border-box in the export and content-box on screen), and the
    # comment explaining why quotes the old declaration — so a substring check
    # would pass on the prose alone.
    assert "html, body" in blocks[deck_index - 1]
    assert "width: 1280px" in blocks[deck_index - 1]
    assert "overflow: hidden" in blocks[deck_index - 1]


def test_the_post_deck_resets_are_a_later_stylesheet_than_the_deck():
    """Cascade preservation, half two. WM-01's restated `html, body` reset and the slide-
    root flattening must still come AFTER the deck, or a deck-authored body padding wins
    again and translates the whole slide down."""
    css = _REALISTIC_DECK_CSS
    blocks = _style_blocks(build_slide_html(_SLIDE, _deck(css)))
    deck_index = _deck_stylesheet_index(blocks, css)

    later = blocks[deck_index + 1 :]
    assert later, "nothing follows the deck's stylesheet"
    assert any("html, body" in b for b in later)
    assert any(SLIDE_ROOT_RESET_STYLE.strip() in b for b in later)


def test_the_document_carries_exactly_three_stylesheets():
    """Pins the shape itself: resets, the deck, post-deck resets. A fourth or a merge back
    into one would change which sheet an `@import` has to lead."""
    blocks = _style_blocks(build_slide_html(_SLIDE, _deck(_REALISTIC_DECK_CSS)))

    assert len(blocks) == 3, [b[:60] for b in blocks]
