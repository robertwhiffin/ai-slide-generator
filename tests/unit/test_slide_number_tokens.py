"""Live page-number tokens: the pure helper (Addendum A, Q2; Task B1).

Graph slides carry ``{{slide:number}}`` and ``{{slide:count}}`` in their footers.
Every reader boundary renders them as marker spans, from the slide's position in
the deck's current order::

    {{slide:number}}  ->  <span data-tellr-slide="number">N</span>
    {{slide:count}}   ->  <span data-tellr-slide="count">M</span>

Every save path turns a marker span back into its token before storing, so a
slide that was hand-edited (its HTML saved back with the rendered numbers in it)
still renumbers after a move.

What this file pins (PLAN-CORRECTIONS-A A4, A7; global constraints):

* the exact marker markup, and an exact round trip;
* HTML with no token (substitute) or no marker (retokenise) comes back as an
  EQUAL string: old decks are byte-identical;
* every token and every marker in a slide is handled, not just the first;
* a marker span is recognised through what the visual editor's DOMParser
  round-trip and a human in the HTML editor do to it: either quote style, extra
  attributes, extra whitespace, edited inner text;
* a value the user deliberately rewrote as plain text (the marker removed) stays
  plain: it is never turned back into a token;
* substitution is markup-safe: a token inside a tag (an attribute value) or
  inside a ``<script>``/``<style>`` body is left alone;
* substitution is idempotent (exports substitute an already-substituted deck);
* the deck helper numbers slides by their order in the dict and counts the dict's
  slides, never a stale ``index`` or ``slide_count``, and leaves every other key,
  including the knitted ``html_content``, untouched (A4).

Every oracle is a literal or a plain ``str.replace`` written here, never a value
computed by the code under test.
"""
from __future__ import annotations

import copy

import pytest
from src.utils.slide_number_tokens import (
    retokenise_slide_numbers,
    substitute_deck_slide_numbers,
    substitute_slide_numbers,
)

NUMBER = "{{slide:number}}"
COUNT = "{{slide:count}}"


def _number_span(n) -> str:
    return f'<span data-tellr-slide="number">{n}</span>'


def _count_span(m) -> str:
    return f'<span data-tellr-slide="count">{m}</span>'


def _rendered(html: str, number, count) -> str:
    """The oracle: what a reader must show for *html* at *number* of *count*."""
    return html.replace(NUMBER, _number_span(number)).replace(COUNT, _count_span(count))


#: Meridian's footer shape (evals/fixtures/meridian/bundle/templates/standard),
#: with the sample page number replaced by the tokens (A21).
FOOTER = (
    '<div class="slide-footer"><span>Meridian</span>'
    "<span>{{slide:number}} / {{slide:count}}</span></div>"
)
SLIDE = '<div class="slide"><h1>Revenue by region</h1><p>Body.</p>' + FOOTER + "</div>"


# ---------------------------------------------------------------------------
# The marker markup, exactly
# ---------------------------------------------------------------------------


class TestSubstitution:
    def test_each_token_renders_as_its_marker_span(self):
        assert substitute_slide_numbers(SLIDE, 3, 12) == (
            '<div class="slide"><h1>Revenue by region</h1><p>Body.</p>'
            '<div class="slide-footer"><span>Meridian</span>'
            '<span><span data-tellr-slide="number">3</span> / '
            '<span data-tellr-slide="count">12</span></span></div></div>'
        )

    def test_every_token_in_the_slide_is_substituted(self):
        html = (
            '<div class="slide"><p>{{slide:number}}</p>'
            "<p>Page {{slide:number}} of {{slide:count}}</p>"
            "<footer>{{slide:count}}{{slide:number}}</footer></div>"
        )
        assert substitute_slide_numbers(html, 7, 9) == (
            '<div class="slide"><p><span data-tellr-slide="number">7</span></p>'
            '<p>Page <span data-tellr-slide="number">7</span> of '
            '<span data-tellr-slide="count">9</span></p>'
            '<footer><span data-tellr-slide="count">9</span>'
            '<span data-tellr-slide="number">7</span></footer></div>'
        )

    def test_the_numbers_are_the_arguments_not_a_guess(self):
        """Two different positions of one slide render differently; a helper that
        ignored its arguments (or swapped them) cannot pass both."""
        assert substitute_slide_numbers(SLIDE, 1, 2) == _rendered(SLIDE, 1, 2)
        assert substitute_slide_numbers(SLIDE, 2, 1) == _rendered(SLIDE, 2, 1)
        assert _rendered(SLIDE, 1, 2) != _rendered(SLIDE, 2, 1)

    def test_substitution_is_idempotent(self):
        """Exports substitute a deck ``get_slides`` already substituted (A1, A7)."""
        once = substitute_slide_numbers(SLIDE, 4, 6)
        assert substitute_slide_numbers(once, 4, 6) == once == _rendered(SLIDE, 4, 6)

    def test_other_placeholders_beside_the_tokens_are_untouched(self):
        html = (
            '<div class="slide"><img src="{{ds-asset:9001}}" alt="logo">'
            '<img src="{{image:42}}"><span>{{slide:number}}</span></div>'
        )
        assert substitute_slide_numbers(html, 2, 5) == (
            '<div class="slide"><img src="{{ds-asset:9001}}" alt="logo">'
            '<img src="{{image:42}}"><span><span data-tellr-slide="number">2</span>'
            "</span></div>"
        )


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------


TOKEN_BEARING = [
    pytest.param(SLIDE, id="meridian-footer"),
    pytest.param(
        '<div class="slide">{{slide:number}}</div>', id="token-is-the-whole-text"
    ),
    pytest.param(
        '<div class="slide"><p>{{slide:number}}{{slide:count}}</p></div>',
        id="adjacent-tokens",
    ),
    pytest.param(
        '<div class="slide"><p>{{slide:number}}</p><p>{{slide:number}}</p>'
        "<p>{{slide:count}}</p><p>{{slide:count}}</p></div>",
        id="repeated-tokens",
    ),
    pytest.param(
        '<section data-label="Ground"><div class="slide white">'
        '<img src="{{ds-asset:7}}" alt="Acme">'
        '<div class="footer"><span>Acme <img src="{{ds-asset:8}}"></span>'
        "<span>{{slide:number}} / {{slide:count}}</span></div></div></section>",
        id="wrapper-with-logo-handles",
    ),
]


class TestRoundTrip:
    @pytest.mark.parametrize("html", TOKEN_BEARING)
    def test_retokenising_a_substituted_slide_gives_back_the_stored_html(self, html):
        rendered = substitute_slide_numbers(html, 3, 11)
        assert NUMBER not in rendered and COUNT not in rendered, (
            "precondition: substitution left a literal token"
        )
        assert retokenise_slide_numbers(rendered) == html

    @pytest.mark.parametrize("html", TOKEN_BEARING)
    def test_a_saved_slide_renumbers_at_its_new_position(self, html):
        """The move, in miniature: read at 2 of 5, saved back, read at 4 of 6."""
        saved = retokenise_slide_numbers(substitute_slide_numbers(html, 2, 5))
        assert substitute_slide_numbers(saved, 4, 6) == _rendered(html, 4, 6)


# ---------------------------------------------------------------------------
# Byte-identical without tokens / markers
# ---------------------------------------------------------------------------


LEGACY = [
    pytest.param("", id="empty"),
    pytest.param('<div class="slide"><h1>Title</h1></div>', id="plain"),
    pytest.param(
        "<div class='slide'  data-x = \"1\"><h1>Odd   spacing</h1>\n\t<p>x</p></div>",
        id="quirky-markup-is-not-normalised",
    ),
    pytest.param(
        '<div class="slide"><img src="{{image:12}}"><img src="{{ds-asset:9001}}">'
        "</div>",
        id="other-placeholders",
    ),
    pytest.param(
        '<div class="slide"><p>{slide:number} {{slide-number}} {slide:count}}'
        "</p></div>",
        id="near-miss-token-spellings",
    ),
    pytest.param(
        '<div class="slide"><div class="footer"><span>Databricks</span>'
        "<span>3 / 12</span></div></div>",
        id="a-baked-page-number",
    ),
    pytest.param(
        '<div class="slide"><span data-page="number">3</span>'
        '<span class="count">12</span></div>',
        id="spans-that-are-not-markers",
    ),
    pytest.param(
        '<div class="slide"><canvas id="c1"></canvas>'
        "<style>.k{color:red}</style><script>new Chart(c1, {});</script></div>",
        id="script-and-style",
    ),
]


class TestOldHtmlIsByteIdentical:
    @pytest.mark.parametrize("html", LEGACY)
    def test_substitution_returns_html_without_tokens_unchanged(self, html):
        assert substitute_slide_numbers(html, 4, 9) == html

    @pytest.mark.parametrize("html", LEGACY)
    def test_retokenising_returns_html_without_markers_unchanged(self, html):
        assert retokenise_slide_numbers(html) == html


# ---------------------------------------------------------------------------
# Retokenising what an editor hands back
# ---------------------------------------------------------------------------


def _in_footer(inner: str) -> str:
    return (
        '<div class="slide"><h2>Edited</h2><div class="slide-footer">'
        "<span>Acme</span><span>" + inner + "</span></div></div>"
    )


class TestRetokenising:
    @pytest.mark.parametrize(
        "marker, token",
        [
            pytest.param('<span data-tellr-slide="number">3</span>', NUMBER, id="number"),
            pytest.param('<span data-tellr-slide="count">12</span>', COUNT, id="count"),
            pytest.param(
                "<span data-tellr-slide='number'>3</span>", NUMBER, id="single-quotes"
            ),
            pytest.param(
                "<span data-tellr-slide='count'>12</span>",
                COUNT,
                id="single-quotes-count",
            ),
            pytest.param(
                '<span class="pg" data-tellr-slide="number">3</span>',
                NUMBER,
                id="attribute-before",
            ),
            pytest.param(
                '<span data-tellr-slide="count" style="font-weight: 700">12</span>',
                COUNT,
                id="attribute-after",
            ),
            pytest.param(
                '<span class="pg" data-tellr-slide="number" style="opacity:.6">3</span>',
                NUMBER,
                id="attributes-either-side",
            ),
            pytest.param(
                '<span  data-tellr-slide="number" >3</span>',
                NUMBER,
                id="whitespace-inside-the-tag",
            ),
            pytest.param(
                '<span data-tellr-slide="count">\n    12\n  </span>',
                COUNT,
                id="whitespace-around-the-value",
            ),
            pytest.param(
                '<span data-tellr-slide="number">03</span>',
                NUMBER,
                id="the-user-retyped-the-digit",
            ),
            pytest.param(
                '<span data-tellr-slide="count">twelve</span>',
                COUNT,
                id="the-user-reworded-the-value",
            ),
            pytest.param(
                '<span data-tellr-slide="number"></span>',
                NUMBER,
                id="the-user-cleared-the-value",
            ),
        ],
    )
    def test_a_marker_span_becomes_its_token(self, marker, token):
        assert retokenise_slide_numbers(_in_footer("p. " + marker + " end")) == (
            _in_footer("p. " + token + " end")
        )

    def test_every_marker_in_the_slide_is_retokenised(self):
        html = (
            '<div class="slide"><p><span data-tellr-slide="number">2</span></p>'
            "<footer><span data-tellr-slide='number'>2</span> of "
            '<span class="c" data-tellr-slide="count">8</span></footer>'
            '<aside><span data-tellr-slide="count">8</span></aside></div>'
        )
        assert retokenise_slide_numbers(html) == (
            '<div class="slide"><p>{{slide:number}}</p>'
            "<footer>{{slide:number}} of {{slide:count}}</footer>"
            "<aside>{{slide:count}}</aside></div>"
        )

    def test_only_the_marker_is_replaced_and_its_neighbours_survive(self):
        html = _in_footer(_number_span(5) + " / " + _count_span(9))
        assert retokenise_slide_numbers(html) == _in_footer(
            "{{slide:number}} / {{slide:count}}"
        )

    def test_a_value_rewritten_as_plain_text_stays_plain(self):
        """The user removed the number's marker and typed the number themselves;
        the count's marker survived.  Only the marker that is still there goes
        live again: the plain "3" is never turned back into a token."""
        html = _in_footer("<span>3</span> / " + _count_span(12))
        assert retokenise_slide_numbers(html) == _in_footer(
            "<span>3</span> / {{slide:count}}"
        )

    def test_a_data_tellr_slide_span_with_another_value_is_not_a_marker(self):
        html = _in_footer('<span data-tellr-slide="title">Intro</span>')
        assert retokenise_slide_numbers(html) == html


# ---------------------------------------------------------------------------
# Markup safety (A7)
# ---------------------------------------------------------------------------


class TestMarkupSafety:
    def test_a_token_inside_a_tag_is_left_alone(self):
        """A ``<span>`` inside an attribute value would break the markup."""
        html = (
            '<div class="slide" data-page="{{slide:number}}">'
            '<img src="x.png" alt="Slide {{slide:number}} of {{slide:count}}">'
            "<p>{{slide:number}}</p></div>"
        )
        assert substitute_slide_numbers(html, 2, 4) == (
            '<div class="slide" data-page="{{slide:number}}">'
            '<img src="x.png" alt="Slide {{slide:number}} of {{slide:count}}">'
            '<p><span data-tellr-slide="number">2</span></p></div>'
        )

    def test_a_token_inside_a_style_body_is_left_alone(self):
        html = (
            '<div class="slide"><style>.f::after{content:"{{slide:count}}"}</style>'
            "<p>{{slide:count}}</p></div>"
        )
        assert substitute_slide_numbers(html, 2, 4) == (
            '<div class="slide"><style>.f::after{content:"{{slide:count}}"}</style>'
            '<p><span data-tellr-slide="count">4</span></p></div>'
        )

    def test_a_token_inside_a_script_body_is_left_alone(self):
        html = (
            '<div class="slide"><script>window.page = "{{slide:number}}";</script>'
            "<p>{{slide:number}}</p></div>"
        )
        assert substitute_slide_numbers(html, 2, 4) == (
            '<div class="slide"><script>window.page = "{{slide:number}}";</script>'
            '<p><span data-tellr-slide="number">2</span></p></div>'
        )


# ---------------------------------------------------------------------------
# The deck helper
# ---------------------------------------------------------------------------


def _slide_html(marker: str) -> str:
    return (
        '<div class="slide"><h1>' + marker + "</h1>"
        '<div class="slide-footer"><span>Acme</span>'
        "<span>{{slide:number}} / {{slide:count}}</span></div></div>"
    )


COVER = '<div class="slide cover"><h1>The cover has no footer</h1></div>'


def _deck(htmls, *, indices=None, slide_count=None) -> dict:
    indices = list(range(len(htmls))) if indices is None else indices
    return {
        "title": "Deck",
        "slide_count": len(htmls) if slide_count is None else slide_count,
        "css": ".slide-footer{display:flex}",
        "external_scripts": ["https://cdn.jsdelivr.net/npm/chart.js"],
        "scripts": "",
        "head_meta": {"viewport": "width=device-width"},
        "html_content": "<html><body>"
        + "".join(htmls)
        + "</body></html>",  # the knitted whole deck: left as stored (A4)
        "version": 3,
        "slides": [
            {
                "index": index,
                "slide_id": f"sid-{i}",
                "html": html,
                "scripts": f"/* chart {i} */",
                "content_hash": f"hash-{i}",
                "verification": None,
            }
            for i, (index, html) in enumerate(zip(indices, htmls))
        ],
    }


def _expected(deck: dict, numbered_htmls) -> dict:
    """*deck* with only each slide's ``html`` replaced: every other key as is."""
    out = copy.deepcopy(deck)
    for slide, html in zip(out["slides"], numbered_htmls):
        slide["html"] = html
    return out


class TestDeckHelper:
    def test_slides_are_numbered_by_their_order_in_the_dict(self):
        htmls = [_slide_html("A"), _slide_html("B"), _slide_html("C")]
        deck = _deck(htmls)
        out = substitute_deck_slide_numbers(copy.deepcopy(deck))
        assert out == _expected(deck, [_rendered(h, i + 1, 3) for i, h in enumerate(htmls)])

    def test_a_stale_index_field_does_not_decide_the_number(self):
        """List order is the deck's current order (session_manager row path and
        ``SlideDeck.to_dict`` both emit it); a slide's ``index`` key is not."""
        htmls = [_slide_html("A"), _slide_html("B"), _slide_html("C")]
        deck = _deck(htmls, indices=[2, 0, 1])
        out = substitute_deck_slide_numbers(copy.deepcopy(deck))
        assert [s["html"] for s in out["slides"]] == [
            _rendered(htmls[0], 1, 3),
            _rendered(htmls[1], 2, 3),
            _rendered(htmls[2], 3, 3),
        ]

    def test_the_count_is_the_number_of_slides_not_a_stale_slide_count(self):
        htmls = [_slide_html("A"), _slide_html("B")]
        deck = _deck(htmls, slide_count=7)
        out = substitute_deck_slide_numbers(copy.deepcopy(deck))
        assert [s["html"] for s in out["slides"]] == [
            _rendered(htmls[0], 1, 2),
            _rendered(htmls[1], 2, 2),
        ]

    def test_a_slide_without_tokens_still_counts_and_keeps_its_place(self):
        """The cover carries no number but is slide 1: the next slide is 2 of 3."""
        htmls = [COVER, _slide_html("B"), _slide_html("C")]
        deck = _deck(htmls)
        out = substitute_deck_slide_numbers(copy.deepcopy(deck))
        assert [s["html"] for s in out["slides"]] == [
            COVER,
            _rendered(htmls[1], 2, 3),
            _rendered(htmls[2], 3, 3),
        ]

    def test_the_knitted_html_content_and_every_other_key_are_left_alone(self):
        htmls = [_slide_html("A"), _slide_html("B")]
        deck = _deck(htmls)
        out = substitute_deck_slide_numbers(copy.deepcopy(deck))
        assert out["html_content"] == deck["html_content"]
        assert NUMBER in out["html_content"], "precondition: the knit carries tokens"
        for key in deck:
            if key != "slides":
                assert out[key] == deck[key], key
        for before, after in zip(deck["slides"], out["slides"]):
            assert {k: v for k, v in after.items() if k != "html"} == {
                k: v for k, v in before.items() if k != "html"
            }

    def test_a_legacy_deck_comes_back_equal(self):
        htmls = [
            '<div class="slide"><h1>One</h1></div>',
            "<div class='slide'><img src=\"{{ds-asset:3}}\"><p>Two</p></div>",
            '<div class="slide"><div class="footer"><span>Databricks</span>'
            "<span>3</span></div></div>",
        ]
        deck = _deck(htmls)
        out = substitute_deck_slide_numbers(copy.deepcopy(deck))
        assert out == deck
        assert [s["html"] for s in out["slides"]] == htmls

    @pytest.mark.parametrize("deck", [{}, {"slides": []}, {"title": "T", "slides": []}])
    def test_a_deck_with_no_slides_comes_back_equal(self, deck):
        assert substitute_deck_slide_numbers(copy.deepcopy(deck)) == deck
