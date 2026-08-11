"""Unit tests for tag-agnostic slide-root detection.

A pinned design-system template makes the model emit the template's own
structure: a semantic ``<section>`` wrapper around the ``div.slide`` body.
The parser used to hardcode ``find_all('div', class_='slide')``, so the
wrapper was discarded while every ``<style>`` block was copied verbatim —
keeping a ``section { ... }`` rule whose only possible match had just been
deleted. Those declarations (background, color, font-family) then never
reached the slide subtree.

These tests pin the wrapper-preserving behaviour, the "one slide, not two"
invariant, and byte-identical output for the shapes that emit no wrapper.
All fixtures are synthetic: no real brand palette, font, or naming.
"""

from bs4 import BeautifulSoup

from src.domain.slide_deck import SlideDeck

# A pinned-template shape: the only slide-root style rule is `section { ... }`,
# and the inner div.slide carries no background of its own, so the near-black
# page background would otherwise show through behind the title.
PINNED_SHAPE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Acme Pinned</title>
    <style>
        html, body { background: #010203; margin: 0; }
        section { background: #123456; color: #ffffff; font-family: 'Acme Sans'; overflow: hidden; }
        .slide { position: relative; padding: 10px; display: flex; }
        .action-title { font-size: 40px; }
    </style>
</head>
<body>
<section data-label="Acme layout">
<div class="slide">
<div class="action-title">Acme progressive refinement title</div>
</div>
</section>
</body>
</html>"""


# The measured-healthy shapes: no wrapper is emitted at all. Output for these
# must not move by a single byte.
UNPINNED_SHAPE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Acme Unpinned</title>
    <style>
        html, body { background: #010203; margin: 0; }
        .slide { position: relative; padding: 10px; background: #123456; }
        .slide.dark { background: #654321; }
    </style>
</head>
<body>
<div class="slide dark">
    <div class="action-title">Acme cover</div>
</div>
<div class="slide">
    <canvas id="acmeChart"></canvas>
</div>
</body>
</html>"""

# Byte-exact slide HTML the parser produced for UNPINNED_SHAPE_HTML before
# tag-agnostic root detection was introduced. Any drift here is a regression
# on a path that is known-healthy in production.
UNPINNED_EXPECTED_SLIDE_HTML = [
    '<div class="slide dark">\n<div class="action-title">Acme cover</div>\n</div>',
    '<div class="slide">\n<canvas id="acmeChart"></canvas>\n</div>',
]


def _declarations_for_selector(css: str, selector: str) -> str:
    """Return the declaration block of the first rule with exactly `selector`."""
    for rule in css.split("}"):
        if "{" not in rule:
            continue
        head, _, body = rule.partition("{")
        if head.strip() == selector:
            return body
    return ""


class TestPinnedSectionWrapperPreserved:
    """The <section> wrapper must survive ingest so `section {}` still matches."""

    def test_wrapper_is_the_stored_slide_root(self):
        deck = SlideDeck.from_html_string(PINNED_SHAPE_HTML)

        assert len(deck.slides) == 1
        root = BeautifulSoup(deck.slides[0].html, "html.parser").find()
        assert root.name == "section", (
            f"slide root should be the emitted <section> wrapper, got <{root.name}>"
        )

    def test_wrapper_attributes_preserved(self):
        deck = SlideDeck.from_html_string(PINNED_SHAPE_HTML)

        root = BeautifulSoup(deck.slides[0].html, "html.parser").find()
        assert root.get("data-label") == "Acme layout"

    def test_all_three_properties_reach_the_title(self):
        """background, color and font-family must be delivered to the title.

        The `section {}` rule sets all three. color and font-family inherit;
        background paints behind descendants. So all three reach the title if
        and only if some element matching the `section` selector is an
        ancestor-or-self of the title element in the rendered document.
        """
        deck = SlideDeck.from_html_string(PINNED_SHAPE_HTML)
        rendered = BeautifulSoup(deck.render_slide(0), "html.parser")

        declarations = _declarations_for_selector(deck.css, "section")
        assert "background: #123456" in declarations
        assert "color: #ffffff" in declarations
        assert "font-family: 'Acme Sans'" in declarations

        matched = rendered.select("section")
        assert matched, "the `section` rule has no element to match after ingest"

        title = rendered.select_one(".action-title")
        assert title is not None
        ancestors = {id(parent) for parent in title.parents}
        assert any(id(element) in ancestors for element in matched), (
            "no element matching `section` is an ancestor of the title, so the "
            "rule's background/color/font-family never reach it"
        )

    def test_inner_slide_body_still_nested_inside_wrapper(self):
        deck = SlideDeck.from_html_string(PINNED_SHAPE_HTML)

        root = BeautifulSoup(deck.slides[0].html, "html.parser").find()
        inner = root.find("div", class_="slide")
        assert inner is not None, "the div.slide body must be kept inside the wrapper"
        assert inner.select_one(".action-title") is not None


class TestNoDoubleCounting:
    """A wrapper plus its slide body is ONE slide, never two."""

    def test_five_wrapped_slides_yield_five_slides(self):
        body = "\n".join(
            f'<section data-label="Layout {i}">\n'
            f'<div class="slide"><div class="action-title">Acme {i}</div></div>\n'
            f"</section>"
            for i in range(5)
        )
        html = (
            "<html><head><style>section { background: #123456; }</style></head>"
            f"<body>{body}</body></html>"
        )

        deck = SlideDeck.from_html_string(html)

        assert len(deck.slides) == 5
        assert [slide.slide_id for slide in deck.slides] == [
            f"slide_{i}" for i in range(5)
        ]

    def test_wrapper_and_body_both_classed_slide_yield_one_slide(self):
        """Outermost wins when both elements carry the `slide` class."""
        html = (
            "<html><body>"
            '<section class="slide" data-label="Acme layout">'
            '<div class="slide"><div class="action-title">Acme</div></div>'
            "</section>"
            "</body></html>"
        )

        deck = SlideDeck.from_html_string(html)

        assert len(deck.slides) == 1
        root = BeautifulSoup(deck.slides[0].html, "html.parser").find()
        assert root.name == "section"

    def test_canvas_index_and_scripts_survive_the_wrapper(self):
        html = """<html><body>
<section data-label="Acme one">
<div class="slide"><canvas id="acmeFirst"></canvas></div>
</section>
<section data-label="Acme two">
<div class="slide"><canvas id="acmeSecond"></canvas></div>
</section>
<script>
const a = document.getElementById('acmeSecond');
</script>
</body></html>"""

        deck = SlideDeck.from_html_string(html)

        assert len(deck.slides) == 2
        assert "acmeSecond" in deck.slides[1].scripts
        assert "acmeSecond" not in deck.slides[0].scripts


class TestNoRegressionOnWrapperlessShapes:
    """Shapes that emit no wrapper must be byte-identical to pre-fix output."""

    def test_unpinned_shape_slide_html_byte_identical(self):
        deck = SlideDeck.from_html_string(UNPINNED_SHAPE_HTML)

        assert len(deck.slides) == 2
        assert [slide.html for slide in deck.slides] == UNPINNED_EXPECTED_SLIDE_HTML

    def test_unpinned_shape_slide_ids_unchanged(self):
        deck = SlideDeck.from_html_string(UNPINNED_SHAPE_HTML)

        assert [slide.slide_id for slide in deck.slides] == ["slide_0", "slide_1"]

    def test_bare_section_without_a_slide_body_is_not_a_slide(self):
        """A <section> that wraps no slide must not become a slide itself."""
        html = (
            "<html><body>"
            "<section data-label=\"Acme notes\"><p>Acme speaker notes</p></section>"
            '<div class="slide"><div class="action-title">Acme</div></div>'
            "</body></html>"
        )

        deck = SlideDeck.from_html_string(html)

        assert len(deck.slides) == 1
        root = BeautifulSoup(deck.slides[0].html, "html.parser").find()
        assert root.name == "div"

    def test_multi_slide_section_is_not_promoted(self):
        """A wrapper holding several slides is a container, not a slide root."""
        html = (
            "<html><body><section data-label=\"Acme deck\">"
            '<div class="slide"><div class="action-title">Acme one</div></div>'
            '<div class="slide"><div class="action-title">Acme two</div></div>'
            "</section></body></html>"
        )

        deck = SlideDeck.from_html_string(html)

        assert len(deck.slides) == 2
        for slide in deck.slides:
            root = BeautifulSoup(slide.html, "html.parser").find()
            assert root.name == "div"
