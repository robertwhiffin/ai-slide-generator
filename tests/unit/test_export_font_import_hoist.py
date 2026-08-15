"""WF-03: a deck's leading ``@import`` must survive into the export document.

MEASURED, and it REPLACES an earlier wrong explanation. The stat-card theory did NOT
reproduce — card wrappers measure 363.59 px in the UI and 325.34 px in the export, equal
in both. The real cause is ORDERING: ``build_slide_html`` emits ``*{}`` and
``html,body{}`` BEFORE ``{deck_css}``, so a deck whose CSS opens with
``@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700')``
no longer has that ``@import`` as the first rule of the stylesheet. CSS requires
``@import`` to precede every other rule except ``@charset``, so the browser DISCARDS
it — measured as 0 font faces in the export against 35 in the UI.

That is the whole of the long-unexplained 38.25 px residual on the DS-OFF deck's slide
2, and it is crossorigin-independent: it survived WM-02 unchanged. Of the audited decks,
the ONE carrying a remote ``@import`` is precisely the one carrying the residual, and the
three DS decks (no ``@import``) measured 0.00 px throughout. MEASURED FIX: hoisting ONLY
that ``@import`` above the injected resets takes the drift to 0.00 px on 32/32 and 30/30.

WHAT THESE TESTS PIN, beyond the hoist itself: that it happens for a LEADING run only (an
``@import`` further down is already invalid in the deck's own sheet and must not be
promoted into validity), that the rule is followed through its own bracketing rather than
to the first ``;`` (a webfont URL carries semicolons in ``wght@400;500;600;700``), that
``@imports`` / ``@import-x`` are not mistaken for it, that an ``@import`` written inside a
comment or a string is not hoisted, and — the majority case — that a deck with no
``@import`` produces a BYTE-IDENTICAL document.
"""
import hashlib
import re

import pytest

from src.api.routes.export import build_slide_html

_SLIDE = {"slide_id": "s1", "html": '<div class="slide">hi</div>'}

#: The real shape: a Google Fonts URL whose query contains SEMICOLONS.
_FONT_IMPORT = (
    "@import url('https://fonts.googleapis.com/css2?"
    "family=Inter:wght@400;500;600;700&display=swap');"
)

#: A realistic deck CSS body with NO ``@import``: the majority case, and the fixture for
#: the byte-identical proof below. Deliberately carries the constructs that could tempt a
#: scanner into rewriting it — an opening comment, braces, a declaration string
#: containing a ``;``, and a block at-rule.
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

#: sha256 of the complete document ``build_slide_html`` produces for ``_SLIDE`` +
#: ``_REALISTIC_DECK_CSS``, CAPTURED FROM THE PRE-FIX CODE (export.py at 9cc36e7 with the
#: hoist absent). Its whole job is to prove the WF-03 change is a no-op for decks without
#: a leading ``@import``. If it ever fails, the generated document changed for every such
#: deck: re-pin ONLY once you intend that.
_PRE_FIX_DOCUMENT_SHA256 = "9f2cfc28c31c4519bee698db011e1b1ed9312f1ed95d6821f6b3cdc93d89356c"

#: Length of that same pre-fix document, restated so a failure says WHETHER bytes were
#: added as well as that they changed.
_PRE_FIX_DOCUMENT_LENGTH = 13514

# A CSS ident code point is [A-Za-z0-9_-], any code point >= U+0080, or an escape — so
# `@importé` is ONE unknown at-keyword, not `@import` plus junk, and moving it would
# reorder a rule the author placed deliberately.
_NON_ASCII_IDENT_IMPORT = "@import\u00e9 url('https://example.invalid/x.css');"

# U+00A0 NBSP is NOT CSS white space; it is an ident code point. A sheet opening with one
# therefore has NO leading at-rule at all — the NBSP starts an ident, which opens a
# QUALIFIED rule whose prelude runs to the next `{}` block, swallowing the `@import` on
# its way. BROWSER-VERIFIED: hoisting here does not merely fail to help, it CHANGES
# RENDERING. Before, the invalid construct swallows `.x`; after, it swallows the injected
# `*` reset instead, and computed style flips from border-box/black to
# content-box/rgb(1, 2, 3).
_NBSP_LEADING_CSS = (
    "\u00a0@import url(https://example.invalid/x.css);\n.x { color: rgb(1, 2, 3); }"
)

# `\)` is an ESCAPE, so it is DATA inside this unquoted url() and does not close it: the
# whole line is ONE valid `@import`. Reading the `\)` as the closing paren cuts the rule
# at the following `;`, hoisting `…/foo\);` and leaving `bar.css);` behind — a malformed
# remainder that can go on to swallow the injected reset block.
_ESCAPED_PAREN_IMPORT = "@import url(https://example.invalid/foo\\);bar.css);"


def _deck(css: str) -> dict:
    return {"title": "T", "css": css, "scripts": "", "external_scripts": []}


def _style_block(html: str) -> str:
    """The document's single <style> block."""
    match = re.search(r"<style>(.*?)</style>", html, re.DOTALL)
    assert match, "no <style> block in the export document"
    return match.group(1)


def _hoisted_region(style: str) -> str:
    """Everything the sheet emits AHEAD of the first injected reset rule.

    That is the only region a browser still honours an ``@import`` in.
    """
    return style[: style.index("* {")]


def test_a_leading_font_import_precedes_the_injected_resets():
    """The fix. Without this the @import is not the first rule and CSS discards it, so
    the export renders in a fallback face while the UI uses the webfont."""
    style = _style_block(
        build_slide_html(_SLIDE, _deck(f"{_FONT_IMPORT}\n.slide {{ color: red }}"))
    )

    assert _FONT_IMPORT in _hoisted_region(style), (
        "the deck's @import must precede the injected resets, or the browser drops "
        f"it:\n{style[:400]}"
    )
    # Nothing but whitespace/comments may precede it, which is what "first rule" means.
    assert "{" not in style[: style.index("@import")], style[: style.index("@import")]


def test_the_import_url_survives_intact_with_its_semicolons():
    """The rule must be followed through its bracketing, not to the first `;`. A webfont
    URL carries semicolons inside the query (wght@400;500;600;700), so cutting there
    would hoist a TRUNCATED url and leave an orphaned `500;600;700…` fragment behind."""
    style = _style_block(
        build_slide_html(_SLIDE, _deck(f"{_FONT_IMPORT}\n.slide {{ color: red }}"))
    )

    assert _FONT_IMPORT in _hoisted_region(style), f"the @import was cut:\n{style[:400]}"
    # Exactly once — hoisted, not copied. A copy left behind re-declares it in an
    # invalid position and is a silent way to double-fetch the font.
    assert style.count("@import") == 1, style.count("@import")
    assert style.count("display=swap") == 1, style.count("display=swap")


def test_a_quoted_url_containing_a_brace_is_followed_to_its_own_end():
    """GUARDRAIL A4, string case. The scan must skip string literals: a `{` inside the
    quoted url is DATA, and a scanner that saw it as the start of a block would give up
    and leave the font behind — the very bug being fixed."""
    awkward = "@import url(\"https://cdn.example.test/a{b};c.css\");"
    style = _style_block(
        build_slide_html(_SLIDE, _deck(f"{awkward}\n.slide {{ color: red }}"))
    )

    assert awkward in _hoisted_region(style), f"not hoisted intact:\n{style[:400]}"


def test_the_rest_of_the_deck_css_keeps_its_position_after_the_resets():
    """Only the @import moves. The deck's own rules must stay AFTER the injected resets,
    because that ordering is what lets a deck override them — and the post-deck WM-01
    rules must still come after the deck."""
    style = _style_block(
        build_slide_html(_SLIDE, _deck(f"{_FONT_IMPORT}\n.slide {{ color: red }}"))
    )

    assert style.index("* {") < style.index(".slide { color: red }")
    # The WM-01 body reset is restated after the deck and must remain last.
    assert style.index(".slide { color: red }") < style.rindex("html, body {")


#: Every deck CSS the hoist must pass through UNTOUCHED, against the length and sha256 of
#: the document the PRE-WF-03 code produced for it (export.py at 9cc36e7, hoist entirely
#: absent). "No-op" here means the same BYTES, not an equivalent sheet. The guarantee is
#: NOT only about a missing `@import`: a leading `@charset` ALONE is no reason to rewrite
#: the document either, and neither is a leading NBSP.
_NO_OP_FIXTURES = {
    "realistic-no-import": (
        _REALISTIC_DECK_CSS,
        _PRE_FIX_DOCUMENT_LENGTH,
        _PRE_FIX_DOCUMENT_SHA256,
    ),
    "empty": (
        "",
        13156,
        "faad92ddf28178233b251632aaa77f3eba490c0e4523d35349ca7ee49365739e",
    ),
    "whitespace-only": (
        "  \n\t\n",
        13161,
        "408ed51ac40196ce40eb2eb4433ed8353b7125ee4ea498ce75b9f3bc757724b9",
    ),
    "comment-only": (
        "/* nothing but a banner */",
        13182,
        "020d23b08ae3b25336747ab310c83205c9f3d4c5a4da5c266f88e2d243a6b471",
    ),
    "comment-then-rule": (
        "/* banner */\n.slide { color: red }",
        13190,
        "9ce3c8b0f15d115023c6363855ee3da0da528e67d4e5767bae23471607da0e61",
    ),
    "charset-only": (
        '@charset "UTF-8";\n.x {}',
        13179,
        "5d6d0367e79e18ff562633c9b2bb105a62c21689399764de6c3c0fb2443fe0e9",
    ),
    "nbsp-then-import": (
        _NBSP_LEADING_CSS,
        13228,
        "0d73ee728c5a939e3c145b0b00b07ce76d57d6147875beb2ab9d634608c1292f",
    ),
}


@pytest.mark.parametrize("fixture_name", sorted(_NO_OP_FIXTURES))
def test_a_deck_the_hoist_does_not_apply_to_is_byte_identical(fixture_name):
    """GUARDRAIL A5/C5, the majority case. Not "equivalent" — the same BYTES as the
    pre-fix code produced, so the change cannot have moved anything for a deck it does
    not apply to."""
    css, expected_length, expected_sha = _NO_OP_FIXTURES[fixture_name]
    document = build_slide_html(_SLIDE, _deck(css))

    digest = hashlib.sha256(document.encode("utf-8")).hexdigest()
    assert (len(document), digest) == (expected_length, expected_sha), (
        f"the generated document changed for fixture {fixture_name!r}, which the hoist "
        f"must not touch.\nexpected {expected_length} bytes / {expected_sha}\n"
        f"got      {len(document)} bytes / {digest}"
    )


def test_an_import_that_is_not_leading_is_left_where_it_is():
    """GUARDRAIL A1. An @import after another rule is ALREADY invalid per spec, in the
    deck's own CSS, before this document is built. Promoting it would change what the
    deck means rather than preserve it — so the scan only ever moves a LEADING rule."""
    css = f".slide {{ color: red }}\n{_FONT_IMPORT}"
    style = _style_block(build_slide_html(_SLIDE, _deck(css)))

    assert "@import" not in _hoisted_region(style), "a mid-sheet @import must not move"
    assert css in style, "the deck CSS must be passed through unchanged"


def test_an_at_rule_whose_name_merely_starts_with_import_is_not_hoisted():
    """GUARDRAIL A3. `@import` must be matched on a CSS ident boundary: `@imports` and
    `@import-x` are different at-keywords and moving them would reorder rules the deck
    author placed deliberately."""
    for keyword in ("@imports", "@import-x"):
        css = f"{keyword} url('https://example.test/a.css');\n.slide {{ color: red }}"
        style = _style_block(build_slide_html(_SLIDE, _deck(css)))

        assert keyword not in _hoisted_region(style), f"{keyword} was hoisted:\n{style[:300]}"
        assert style.lstrip().startswith("* {"), style[:200]


def test_an_import_written_inside_a_comment_is_not_hoisted():
    """GUARDRAIL A4, comment case. A commented-out @import is not a rule; hoisting it
    would resurrect a font the deck author switched off."""
    css = f"/* disabled: {_FONT_IMPORT} */\n.slide {{ color: red }}"
    style = _style_block(build_slide_html(_SLIDE, _deck(css)))

    assert "@import" not in _hoisted_region(style), style[:300]
    assert style.lstrip().startswith("* {"), style[:200]


def test_an_import_written_inside_a_declaration_string_is_not_hoisted():
    """GUARDRAIL A4, string case. `content: "@import …"` is text, not an at-rule."""
    css = f'.slide::after {{ content: "{_FONT_IMPORT}" }}'
    style = _style_block(build_slide_html(_SLIDE, _deck(css)))

    assert "@import" not in _hoisted_region(style), style[:300]
    assert css in style, "the deck CSS must be passed through unchanged"


def test_several_leading_imports_are_all_hoisted_in_order():
    """CSS allows a run of @import rules; hoisting only the first would leave the others
    invalid, which is the same defect one rule further along."""
    second = "@import url('https://example.test/b.css');"
    style = _style_block(
        build_slide_html(_SLIDE, _deck(f"{_FONT_IMPORT}\n{second}\n.slide {{ color: red }}"))
    )

    hoisted = _hoisted_region(style)
    assert _FONT_IMPORT in hoisted
    assert second in hoisted
    # Relative order preserved: @import is order-sensitive in the cascade.
    assert hoisted.index(_FONT_IMPORT) < hoisted.index(second)


def test_a_leading_charset_keeps_its_place_ahead_of_the_import():
    """`@charset` is the one thing allowed to precede `@import`, so it travels with the
    run and keeps its position — reversing them would invalidate the charset rule."""
    charset = '@charset "utf-8";'
    style = _style_block(
        build_slide_html(_SLIDE, _deck(f"{charset}\n{_FONT_IMPORT}\n.slide {{ color: red }}"))
    )

    hoisted = _hoisted_region(style)
    assert charset in hoisted
    assert hoisted.index(charset) < hoisted.index(_FONT_IMPORT)


def test_a_leading_comment_does_not_stop_the_hoist():
    """Comments are allowed before @import and do not make it non-leading, so a deck
    whose CSS opens with a banner comment must still get its font."""
    css = f"/* Brand fonts */\n{_FONT_IMPORT}\n.slide {{ color: red }}"
    style = _style_block(build_slide_html(_SLIDE, _deck(css)))

    assert _FONT_IMPORT in _hoisted_region(style), style[:300]


def test_a_nbsp_before_the_import_stops_the_hoist():
    """BLOCKER 1, browser-verified. U+00A0 is an ident code point, not CSS white space, so
    the browser does NOT see a leading at-rule here — the NBSP opens a qualified rule
    whose prelude swallows the `@import`. Hoisting anyway does not just fail to help, it
    CHANGES RENDERING: the invalid construct stops swallowing `.x` and starts swallowing
    the injected `*` reset, flipping computed style to content-box/rgb(1, 2, 3)."""
    style = _style_block(build_slide_html(_SLIDE, _deck(_NBSP_LEADING_CSS)))

    assert "@import" not in _hoisted_region(style), (
        f"a NBSP is not CSS white space; nothing here is leading:\n{style[:300]}"
    )
    assert _NBSP_LEADING_CSS in style, "the deck CSS must be passed through unchanged"
    # The injected reset must still be the first thing the sheet declares.
    assert style.lstrip().startswith("* {"), style[:200]


@pytest.mark.parametrize("space", [" ", "\t", "\n", "\r", "\f"])
def test_real_css_white_space_before_the_import_stays_transparent(space):
    """The five code points CSS actually calls white space — space, tab, LF, CR, FF — do
    not make an `@import` non-leading, so the font must still be rescued after any of
    them."""
    style = _style_block(
        build_slide_html(_SLIDE, _deck(f"{space}{_FONT_IMPORT}\n.x {{ color: red }}"))
    )

    assert _FONT_IMPORT in _hoisted_region(style), style[:300]


@pytest.mark.parametrize(
    "not_space",
    ["\u00a0", "\u000b", "\u0085"],
    ids=["nbsp", "vertical-tab", "next-line"],
)
def test_code_points_css_does_not_call_white_space_stop_the_hoist(not_space):
    """Each of these satisfies Python's `str.isspace()` and NONE of them is CSS white
    space, which is precisely why `str.isspace()` cannot be the test. To CSS they are an
    ident code point (NBSP, NEL) or a delim (VT) — either way they open a qualified rule
    whose prelude swallows the `@import`, so it is NOT leading and must not move."""
    css = f"{not_space}{_FONT_IMPORT}\n.x {{ color: red }}"
    style = _style_block(build_slide_html(_SLIDE, _deck(css)))

    assert "@import" not in _hoisted_region(style), style[:300]
    assert css in style, "the deck CSS must be passed through unchanged"


def test_an_escaped_paren_inside_an_unquoted_url_does_not_end_the_rule():
    """BLOCKER 2. `\\)` is an escape, so it is DATA inside this url() and the whole line is
    ONE valid `@import`. Cutting at the `;` that follows it hoists a truncated rule and
    leaves `bar.css);` behind — a malformed remainder that can swallow the reset block."""
    style = _style_block(
        build_slide_html(_SLIDE, _deck(f"{_ESCAPED_PAREN_IMPORT}\n.x {{ color: red }}"))
    )

    assert _ESCAPED_PAREN_IMPORT in _hoisted_region(style), (
        f"the rule was split mid-token:\n{style[:400]}"
    )
    # No orphaned fragment anywhere after the resets.
    assert "bar.css" not in style[style.index("* {"):], style[style.index("* {"):][:300]
    assert style.count("@import") == 1, style.count("@import")


def test_a_charset_alone_is_not_a_reason_to_rewrite_the_sheet():
    """BLOCKER 3. `@charset` is hoistable only as a TRAVELLING COMPANION to a real
    `@import`. On its own it must stay exactly where the author put it, or the byte-
    identical guarantee stops being true for a whole class of sheets."""
    css = '@charset "UTF-8";\n.x {}'
    style = _style_block(build_slide_html(_SLIDE, _deck(css)))

    assert "@charset" not in _hoisted_region(style), style[:300]
    assert css in style, "the deck CSS must be passed through unchanged"


def test_a_non_ascii_ident_is_not_mistaken_for_the_import_keyword():
    """A CSS ident code point includes anything >= U+0080, so `@importé` is ONE unknown
    at-keyword rather than `@import` followed by junk. Moving it would reorder a rule the
    author placed deliberately."""
    css = f"{_NON_ASCII_IDENT_IMPORT}\n.x {{ color: red }}"
    style = _style_block(build_slide_html(_SLIDE, _deck(css)))

    assert _NON_ASCII_IDENT_IMPORT not in _hoisted_region(style), style[:300]
    assert css in style, "the deck CSS must be passed through unchanged"


def test_an_unterminated_import_is_left_alone():
    """Fail safe: with no `;` the rule's extent is unknown, so moving it could carry the
    following rule along with it. Leave the sheet exactly as authored."""
    css = "@import url('https://example.test/a.css')\n.slide { color: red }"
    style = _style_block(build_slide_html(_SLIDE, _deck(css)))

    assert "@import" not in _hoisted_region(style), style[:300]
    assert css in style, "the deck CSS must be passed through unchanged"
