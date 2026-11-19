"""Snapshot engine: text blocks, the browser's line breaks and text-box geometry.

The snapshot engine (``TELLR_EXPORT_ENGINE=snapshot``) groups the rendered text
into text blocks and emits each block as one text box (spec §3 Text):

* every flex or grid item is its own block, so a footer's brand line and page
  number, or an agenda row's number and title, never merge into one paragraph
  (RC2);
* bare text after a block child, or beside an icon, is its own anonymous block
  and is never dropped (upstream issue #56);
* text inside an ``<svg>`` is part of the drawing, never slide text (RC3);
* the line breaks are the browser's: a title that wraps on screen is one
  paragraph whose second line starts with a soft break (a paragraph of its
  own where the browser grew it, written for PowerPoint), and a one-line label
  is unwrapped;
* a box's geometry comes from its text's own rects, not the element box, plus
  6 % + 4 px of width slack on the side its alignment lets the text grow;
* white space collapses the way the browser collapses it, and
  ``white-space: pre`` keeps its spaces as NBSP;
* a flex item paints atomically: its text box sits between its own background
  and the next item's.

Every assertion reads the emitted slide XML (``slide_shapes``). Where the
geometry or the line breaks matter, it is held against the browser's own
layout of the very same document (``browser_rect``, ``browser_line_boxes``,
``browser_lines``). Corpus slides are loaded from ``tests/fixtures/export_fidelity``
by prefix (PLAN-CORRECTIONS C4): 02 is the agenda grid, 03 the footer and the
SVG chart, 17 the bare-text and icon cases.

Gating matches the sibling export suites: needs node, the extracted sidecar
``node_modules`` and a local Chrome/Chromium (skipped otherwise).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.fixtures.export_snapshot_support import (
    DECK_CSS,
    Shape,
    browser_line_boxes,
    browser_lines,
    browser_rect,
    browser_style,
    corpus_document,
    export_corpus,
    export_slides,
    overlaps,
    requires_huashu_sidecar,
    slide_document,
    slide_shapes,
    text_bounds,
)

NBSP = "\u00a0"
# What the deck for PowerPoint writes after a script run that ends its line (emit_text.cjs).
WORD_JOINER = "\u2060"
PT_PER_PX = 0.75
# A line the browser set this much past its line height grew (snapshot_text.mjs).
LINE_GROWTH_MIN_PX = 0.5
# spcBef is hundredths of a point; one unit is the rounding pptxgenjs does.
SPACE_BEFORE_TOLERANCE_PT = 0.01

# Spec §3 Text, Wrapping: every text box gets 6 % plus 4 px of width slack.
SLACK_FRACTION = 0.06
SLACK_PX = 4.0
# EMU rounding moves an emitted edge by at most 1/19050 px; a lower bound on an
# emitted width needs only this much give.
EMU_ROUNDING_PX = 0.01
# Tolerances from the plan's Task 2 Step 1.
TEXT_LEFT_TOLERANCE_PX = 0.5
ALIGNED_EDGE_TOLERANCE_PX = 1.0
FOOTER_EDGE_TOLERANCE_PX = 2.0
# Browser line rects and emitted boxes are both sub-pixel; "below" allows this much.
BELOW_TOLERANCE_PX = 0.5

# The corpus slides the text-block tests read, exported once per module in this order.
CORPUS_PREFIXES = ("02", "03", "17")

# Fixture 03 and every corpus footer: a space-between flex row holding the brand
# (itself a flex row of the logo <img> and a text span) and the page number.
FOOTER = ".dk-footer"
FOOTER_LOGO = ".dk-footer img"
FOOTER_PAGE_NUMBER = ".dk-footer .pg"
FOOTER_BRAND = "Meridian Components \u00b7 FY2024 review"

# Fixture 02: each agenda row is a two-column grid, the number then a block of
# title and description.
AGENDA_ROWS = (
    ("01", "Financial position"),
    ("02", "Performance"),
    ("03", "Analysis and outlook"),
    ("04", "FY2025 capital plan"),
)

# Fixture 17's body: the icon row (two inline-flex items, each an <svg> then bare
# text), then the container holding a block child followed by bare text.
ICON_ROW_ICONS = ".slide > div:nth-of-type(1) svg"
ICON_LABELS = ("Open source", "+7.5 vs baseline")
BARE_TEXT_CONTAINER = ".slide > div:nth-of-type(2)"
BLOCK_CHILD = "Block child first"
BARE_TEXT_START = "Then bare text that follows"

# Fixture 03's chart: the legend and source line are HTML text; the bar values,
# axis years and margin labels are SVG <text>. The SVG labels listed here are
# the ones no HTML text on the slide contains, even as a substring (the
# visually-hidden data table repeats FY20, 905, FY24 and 1,240, and its
# visibility belongs to Task 6). Leaked SVG labels glue together with no white
# space between them ("905FY20968FY21"), so a leak is found by containment.
CHART_SVG = "svg.chart-svg"
CHART_HTML_TEXT = (
    "Revenue ($M)",
    "FY2024 revenue",
    "Operating margin (%)",
    "Source: Illustrative (fictional)",
)
SVG_ONLY_LABELS = ("968", "FY21", "1,042", "FY22", "1,120", "FY23", "8.1%", "8.8%", "9.4%", "9.9%")

# Slack and alignment: a 600 px content box inside asymmetric padding and a
# border, so a box taken from the border box, or from the wrong edge, misses.
ALIGNED_CONTENT_WIDTH_PX = 600.0
ALIGNED_BOX_STYLE = (
    "width: 600px; padding: 8px 40px 8px 24px; border: 2px solid #DCE0E2; font-size: 20px;"
)


def _slack(width: float) -> float:
    return width * SLACK_FRACTION + SLACK_PX


def _export_one(body: str, monkeypatch: pytest.MonkeyPatch) -> bytes:
    pptx, failures = export_slides([body], css=DECK_CSS, engine="snapshot", monkeypatch=monkeypatch)
    assert failures == [], f"the export rejected the slide: {failures}"
    assert pptx, "the export produced no .pptx bytes"
    return pptx


def _document(body: str) -> str:
    """The document ``_export_one`` exported (``export_slides`` names slide 1 ``snapshot-1``)."""
    return slide_document(body, css=DECK_CSS, slide_id="snapshot-1")


@pytest.fixture(scope="module")
def corpus_pptx() -> Iterator[bytes]:
    """Corpus slides 02, 03 and 17, exported once through the snapshot engine."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        pptx, failures = export_corpus(
            list(CORPUS_PREFIXES), monkeypatch=monkeypatch, engine="snapshot"
        )
    assert failures == [], f"the export rejected a corpus slide: {failures}"
    yield pptx


def _corpus_shapes(pptx: bytes, prefix: str) -> list[Shape]:
    return slide_shapes(pptx, CORPUS_PREFIXES.index(prefix))


def _normalised(text: str) -> str:
    return " ".join(text.split())


def _describe(shapes: list[Shape]) -> str:
    lines = []
    for position, shape in enumerate(shapes):
        if shape.kind == "text":
            detail = f"wrap={shape.wrap} paras={len(shape.paras)} text={shape.text[:60]!r}"
        else:
            detail = f"fill={shape.fill}"
        lines.append(
            f"  [{position}] {shape.kind} box=({shape.x:.2f}, {shape.y:.2f}, "
            f"{shape.w:.2f}, {shape.h:.2f}) {detail}"
        )
    return "\n".join(lines) or "  (no shapes)"


def _text_box(shapes: list[Shape], text: str) -> tuple[int, Shape]:
    """(spTree index, shape) of the one text box whose whitespace-normalised text is ``text``."""
    matches = [
        (position, shape)
        for position, shape in enumerate(shapes)
        if shape.kind == "text" and _normalised(shape.text) == text
    ]
    assert len(matches) == 1, (
        f"expected exactly one text box reading {text!r}, got {len(matches)}:\n{_describe(shapes)}"
    )
    return matches[0]


def _text_box_containing(shapes: list[Shape], fragment: str) -> tuple[int, Shape]:
    """(spTree index, shape) of the one text box whose text contains ``fragment``."""
    matches = [
        (position, shape)
        for position, shape in enumerate(shapes)
        if shape.kind == "text" and fragment in shape.text
    ]
    assert len(matches) == 1, (
        f"expected exactly one text box containing {fragment!r}, got {len(matches)}:\n"
        f"{_describe(shapes)}"
    )
    return matches[0]


def _filled(shapes: list[Shape], fill: str) -> tuple[int, Shape]:
    """(spTree index, shape) of the one element filled ``fill``."""
    matches = [(position, shape) for position, shape in enumerate(shapes) if shape.fill == fill]
    assert len(matches) == 1, (
        f"expected exactly one element filled {fill}, got {len(matches)}:\n{_describe(shapes)}"
    )
    return matches[0]


def _browser_box(rect: dict, what: str) -> Shape:
    """A browser rect as a bare ``Shape``, so ``overlaps`` can hold it against emitted boxes."""
    return Shape(
        kind=what,
        geometry=None,
        x=rect["x"],
        y=rect["y"],
        w=rect["w"],
        h=rect["h"],
        rotation=0.0,
        wrap=None,
        fill=None,
        fill_alpha=None,
        line=None,
        line_w_pt=None,
        line_dash=None,
        paras=[],
        text="",
        image=None,
        table=None,
        adj=None,
    )


def _box(shape: Shape) -> dict:
    return {
        "x": round(shape.x, 3),
        "y": round(shape.y, 3),
        "w": round(shape.w, 3),
        "h": round(shape.h, 3),
    }


def _run_texts(shapes: list[Shape]) -> list[str]:
    return [
        run.text
        for shape in shapes
        if shape.kind == "text"
        for para in shape.paras
        for run in para.runs
    ]


def _single_line(document: str, selector: str) -> dict:
    """The text bounds of ``selector``'s one rendered line (a fixture guard asserts it is one)."""
    lines = browser_line_boxes(document, selector)
    assert len(lines) == 1, f"fixture drift: {selector} renders {len(lines)} lines: {lines}"
    return text_bounds(lines)


def _aligned_body(element_id: str, align: str, text: str) -> str:
    return (
        '<div class="slide">'
        f'<p id="{element_id}" style="{ALIGNED_BOX_STYLE} text-align: {align};">{text}</p>'
        "</div>"
    )


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotTextBlocks:
    def test_footer_brand_and_page_number_are_separate_boxes_clear_of_the_logo(
        self, corpus_pptx: bytes
    ) -> None:
        """RC2, fixture 03's footer: each flex item is its own text block.

        * No text box holds both the brand line and the page number (real decks
          showed "review12 / 15").
        * The brand line and the page number are one text box each.
        * The brand box starts after the logo, so it does not overlap the logo's
          browser rect.
        * The page number is left-aligned text at the row's right end, so its box
          grows rightward: its right edge is the footer's right content edge plus
          its slack, within 2 px.

        The plan also lists the logo itself as a picture item. Its source is an
        SVG ``data:`` URI, which is only embeddable once captures exist (Task 7),
        so the non-overlap check uses the logo's browser rect, which is where that
        picture will sit.
        """
        document = corpus_document("03")
        shapes = _corpus_shapes(corpus_pptx, "03")

        merged = [
            shape.text
            for shape in shapes
            if shape.kind == "text" and "review" in shape.text and "3 / 16" in shape.text
        ]
        assert merged == [], f"the brand line and the page number share a text box: {merged}"
        _, brand = _text_box(shapes, FOOTER_BRAND)
        _, page = _text_box(shapes, "3 / 16")

        logo = browser_rect(document, FOOTER_LOGO)
        assert not overlaps(brand, _browser_box(logo, "logo")), (
            f"the brand text box {_box(brand)} overlaps the footer logo at {logo}"
        )

        footer = browser_rect(document, FOOTER)
        # The deck's footer has no padding or border, so its border box's right
        # edge is its content edge; the guard pins the page number ending there.
        footer_right = footer["x"] + footer["w"]
        page_text = _single_line(document, FOOTER_PAGE_NUMBER)
        assert abs(page_text["x"] + page_text["w"] - footer_right) <= TEXT_LEFT_TOLERANCE_PX, (
            f"fixture drift: the page number {page_text} does not end at the footer's right "
            f"content edge {footer_right}"
        )
        expected_right = footer_right + _slack(page_text["w"])
        emitted_right = page.x + page.w
        assert abs(emitted_right - expected_right) <= FOOTER_EDGE_TOLERANCE_PX, (
            f"the page-number box {_box(page)} ends at {emitted_right:.2f}; expected the footer's "
            f"right content edge {footer_right:.2f} plus slack {_slack(page_text['w']):.2f} "
            f"= {expected_right:.2f} (within {FOOTER_EDGE_TOLERANCE_PX} px)"
        )

    def test_agenda_number_and_title_are_separate_boxes(self, corpus_pptx: bytes) -> None:
        """RC2, fixture 02's agenda grid: each grid item is its own text block.

        In every row the number ("01") and the title ("Financial position") are
        separate text boxes, the number's box ends left of where the title's
        starts, and no box glues them together ("01Financial").
        """
        shapes = _corpus_shapes(corpus_pptx, "02")

        for number, title in AGENDA_ROWS:
            glued = number + title.split()[0]
            merged = [
                shape.text
                for shape in shapes
                if shape.kind == "text" and glued in "".join(shape.text.split())
            ]
            assert merged == [], f"row {number}: the number and the title share a box: {merged}"
            _, number_box = _text_box(shapes, number)
            _, title_box = _text_box(shapes, title)
            assert number_box.x + number_box.w <= title_box.x, (
                f"row {number}: the number's box {_box(number_box)} reaches past the left edge "
                f"of the title's box {_box(title_box)}"
            )

    def test_bare_text_after_a_block_child_is_its_own_box(self, corpus_pptx: bytes) -> None:
        """Upstream #56, fixture 17: text that follows a block child in the same container.

        The bare text is an anonymous block. It is present, in its own box, with
        the browser's lines, and that box sits below the block child's box. It
        follows the block child in the spTree too: line boxes paint in tree
        order, which is also the slide's reading order.
        """
        lines = browser_lines(corpus_document("17"), BARE_TEXT_CONTAINER)
        assert len(lines) >= 2 and lines[0] == BLOCK_CHILD, (
            f"fixture drift: the container's lines are {lines}"
        )
        shapes = _corpus_shapes(corpus_pptx, "17")

        block_index, block = _text_box(shapes, BLOCK_CHILD)
        bare_index, bare = _text_box_containing(shapes, BARE_TEXT_START)
        assert bare_index > block_index, (
            f"the bare text (spTree index {bare_index}) is emitted before the block child it "
            f"follows (index {block_index}):\n{_describe(shapes)}"
        )
        assert BLOCK_CHILD not in bare.text, (
            f"the bare text shares a box with its block sibling: {bare.text!r}"
        )
        assert bare.text.split("\n") == lines[1:], (
            f"the bare text box reads {bare.text.split(chr(10))}; the browser's lines are "
            f"{lines[1:]}"
        )
        assert bare.y >= block.y + block.h - BELOW_TOLERANCE_PX, (
            f"the bare text box {_box(bare)} is not below the block child's box {_box(block)}"
        )

    def test_bare_text_beside_an_icon_is_kept_clear_of_the_icon(self, corpus_pptx: bytes) -> None:
        """Upstream #56, fixture 17's icon row: an ``<svg>`` icon then bare text, in an
        inline-flex item.

        "Open source" and "+7.5 vs baseline" are each present as their own text
        box, and the box is placed by the text's rects, so it does not overlap
        the icon beside it.
        """
        document = corpus_document("17")
        shapes = _corpus_shapes(corpus_pptx, "17")

        for position, label in enumerate(ICON_LABELS):
            _, box = _text_box(shapes, label)
            icon = browser_rect(document, ICON_ROW_ICONS, position)
            assert not overlaps(box, _browser_box(icon, "icon")), (
                f"the {label!r} text box {_box(box)} overlaps its icon at {icon}"
            )

    def test_svg_chart_text_is_never_slide_text(self, corpus_pptx: bytes) -> None:
        """RC3, fixture 03: the walk never descends into an ``<svg>`` for text.

        The chart's HTML legend and source line are text boxes. None of the SVG's
        own ``<text>`` labels (bar values, axis years, margin labels) appears in
        any text box, not even glued to its neighbours, no text box lies over
        the chart, and no run carries the SVG source's raw white space.
        """
        document = corpus_document("03")
        shapes = _corpus_shapes(corpus_pptx, "03")

        for text in CHART_HTML_TEXT:
            _text_box(shapes, text)
        leaked = [
            (label, shape.text)
            for shape in shapes
            if shape.kind == "text"
            for label in SVG_ONLY_LABELS
            if label in shape.text
        ]
        assert leaked == [], f"SVG chart labels leaked into slide text: {leaked}"
        chart = browser_rect(document, CHART_SVG)
        over_chart = [
            (_box(shape), shape.text[:60])
            for shape in shapes
            if shape.kind == "text" and overlaps(shape, _browser_box(chart, "chart"))
        ]
        assert over_chart == [], f"text boxes lie over the SVG chart at {chart}: {over_chart}"
        raw = [text for text in _run_texts(shapes) if "\n" in text or "  " in text]
        assert raw == [], f"runs carry raw source white space: {raw}"


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotTextLines:
    def test_wrapped_title_is_one_box_broken_where_the_browser_breaks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 900 px-wide corpus title (42 px, line-height 1.08) that wraps to two lines on
        screen and ends in a footnote marker.

        It is one text box whose lines read exactly as the browser's, and it
        wraps (``wrap="square"``). Its lines are one paragraph, the second
        starting with a soft break (``<a:br/>``), but where the browser grew
        the second line: the footnote marker, raised with a line height of its
        own, sets it lower than the line height puts it. There, written for
        PowerPoint, the second line opens a paragraph of its own with that
        growth as space before, at the title's 90% spacing, and the marker that
        ends it is followed by a zero-width word joiner (task-11 findings r4,
        Important 2), which the lines are read without.

        Two layouts here defeat a line clustering that is not by vertical overlap:

        * at line-height 1.08 the glyph rects of consecutive lines overlap
          vertically (55 px tall on a 45.36 px pitch), so requiring a rect to start
          below the previous line's bottom finds one line;
        * the ``<sup>`` marker's rect starts 8 px above its line's other rects, so
          counting distinct ``top`` values finds three lines.
        """
        body = (
            '<div class="slide">'
            '<h2 id="title" class="dk-title" style="width: 900px; max-width: 900px;">'
            '<span id="first">FY2024</span> delivered the largest margin step-up in '
            '<span id="second">five</span> years<sup>1</sup></h2>'
            "</div>"
        )
        document = _document(body)
        lines = browser_lines(document, "#title")
        assert len(lines) == 2 and lines[1].startswith("five"), (
            f"fixture drift: the title renders {len(lines)} lines: {lines}"
        )
        pitch = float(browser_style(document, "#title")["lineHeight"].removesuffix("px"))
        growth = browser_rect(document, "#second")["y"] - browser_rect(document, "#first")["y"]
        growth -= pitch
        assert growth >= LINE_GROWTH_MIN_PX, (
            f"fixture drift: the footnote marker no longer grows the second line ({growth:.2f} px)"
        )
        shapes = slide_shapes(_export_one(body, monkeypatch))

        _, title = _text_box_containing(shapes, "FY2024")
        written = [line.removesuffix(WORD_JOINER) for line in title.text.split("\n")]
        assert written == lines, f"the title's lines are {written}; the browser's are {lines}"
        assert len(title.paras) == 2 and not any(
            run.soft_break_before for paragraph in title.paras for run in paragraph.runs
        ), (
            f"the grown second line must open a paragraph of its own: "
            f"{[[run.text for run in paragraph.runs] for paragraph in title.paras]}"
        )
        second = title.paras[1]
        assert (
            second.space_before_pt is not None
            and abs(second.space_before_pt - growth * PT_PER_PX) <= SPACE_BEFORE_TOLERANCE_PT
        ), (
            f"the browser grew the second line {growth:.2f} px, so its paragraph needs spcBef "
            f"{growth * PT_PER_PX:.3f} pt; it has {second.space_before_pt}"
        )
        assert [paragraph.line_spacing_pct for paragraph in title.paras] == [90.0, 90.0], (
            f"both paragraphs keep the title's 90% spacing: {title.paras}"
        )
        assert title.wrap == "square", f"a two-line title must wrap, got wrap={title.wrap!r}"

    def test_blank_line_keeps_the_size_of_its_block(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A blank line (``<br><br>``) is as tall as its block's text, not PowerPoint's 18 pt.

        A bare ``<a:br/>`` carries no run properties, so PowerPoint sizes the
        blank line at its 18 pt default and every later line shifts down. The
        blank line is therefore a run of its own, sized like the line before
        it: in a 13 px paragraph every run, the blank line's included, is
        ``sz="975"`` (13 x 0.75 pt), and none is at the default. The run starts
        its line: after a soft break, or, where the block's leading is looser
        than the renderers' single spacing and every line is a paragraph of its
        own (Task 4, ruling R2), as the first run of a paragraph after the first.
        """
        body = (
            '<div class="slide">'
            '<p id="gap" style="font-size: 13px;">First line<br><br>Third line</p>'
            "</div>"
        )
        line_boxes = browser_line_boxes(_document(body), "#gap")
        assert [line["text"] for line in line_boxes] == ["First line", "Third line"], (
            f"fixture drift: the paragraph renders {line_boxes}"
        )
        assert line_boxes[1]["y"] - line_boxes[0]["y"] > 1.5 * line_boxes[0]["h"], (
            f"fixture drift: no blank line between the two painted lines: {line_boxes}"
        )
        shapes = slide_shapes(_export_one(body, monkeypatch))

        _, box = _text_box_containing(shapes, "First line")
        runs = [run for para in box.paras for run in para.runs]
        line_starts = [
            run
            for position, para in enumerate(box.paras)
            for index, run in enumerate(para.runs)
            if run.soft_break_before or (index == 0 and position > 0)
        ]
        blank = [run for run in line_starts if not run.text.strip()]
        assert len(blank) == 1, (
            f"expected one run for the blank line, got {len(blank)}: "
            f"{[(run.text, run.size_pt) for run in runs]}"
        )
        expected_pt = 13 * 0.75
        assert blank[0].size_pt == expected_pt, (
            f"the blank line's run is {blank[0].size_pt} pt; the paragraph is {expected_pt} pt"
        )
        assert all(run.size_pt == expected_pt for run in runs), (
            f"a run in the box is not at the paragraph's {expected_pt} pt (an absent sz is "
            f"PowerPoint's 18 pt default): {[(run.text, run.size_pt) for run in runs]}"
        )
        lines = [line.strip() for line in box.text.split("\n")]
        assert lines == ["First line", "", "Third line"], f"the box reads {box.text!r}"

    def test_single_line_label_is_unwrapped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A label that is one line in the browser gets ``wrap="none"`` (PowerPoint honours it)."""
        body = (
            '<div class="slide"><p id="label" style="font-size: 16px;">Quarterly revenue</p></div>'
        )
        lines = browser_lines(_document(body), "#label")
        assert lines == ["Quarterly revenue"], f"fixture drift: the label renders {lines}"
        shapes = slide_shapes(_export_one(body, monkeypatch))

        _, label = _text_box(shapes, "Quarterly revenue")
        assert label.wrap == "none", f"a one-line label must not wrap, got wrap={label.wrap!r}"

    def test_left_aligned_box_starts_at_the_text_and_carries_slack(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Left-aligned text is placed by its own bounds, not its container's.

        * ``x`` is the browser's text left within 0.5 px (inside the padding and
          border, not at the border box);
        * ``w`` is at least 1.06 x the text width + 4 px, the slack Drive needs
          because it ignores ``wrap="none"``;
        * ``w`` stays under the container's 600 px content width: the box is
          sized from the text.
        """
        body = _aligned_body("left", "left", "Left aligned label")
        text = _single_line(_document(body), "#left")
        shapes = slide_shapes(_export_one(body, monkeypatch))

        _, box = _text_box(shapes, "Left aligned label")
        assert abs(box.x - text["x"]) <= TEXT_LEFT_TOLERANCE_PX, (
            f"the box {_box(box)} starts at {box.x:.2f}; the browser's text starts at "
            f"{text['x']:.2f}"
        )
        minimum = (1 + SLACK_FRACTION) * text["w"] + SLACK_PX
        assert box.w >= minimum - EMU_ROUNDING_PX, (
            f"the box is {box.w:.2f} px wide; the text is {text['w']:.2f} px, so with slack it "
            f"needs at least {minimum:.2f}"
        )
        assert box.w < ALIGNED_CONTENT_WIDTH_PX, (
            f"the box {_box(box)} is as wide as its container; left-aligned text is sized from "
            "its own bounds"
        )

    def test_centred_box_keeps_the_browser_centre(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Centred text keeps its centre within 1 px of the browser's.

        The box spans its container's content box plus slack on both sides, so
        the centring survives a slightly wider font.
        """
        body = _aligned_body("centre", "center", "Centred label")
        text = _single_line(_document(body), "#centre")
        shapes = slide_shapes(_export_one(body, monkeypatch))

        _, box = _text_box(shapes, "Centred label")
        browser_centre = text["x"] + text["w"] / 2
        emitted_centre = box.x + box.w / 2
        assert abs(emitted_centre - browser_centre) <= ALIGNED_EDGE_TOLERANCE_PX, (
            f"the box {_box(box)} is centred at {emitted_centre:.2f}; the browser's text is "
            f"centred at {browser_centre:.2f}"
        )
        assert box.w >= ALIGNED_CONTENT_WIDTH_PX, (
            f"the centred box {_box(box)} is narrower than its container's "
            f"{ALIGNED_CONTENT_WIDTH_PX:.0f} px content box"
        )

    def test_right_aligned_box_keeps_the_browser_right_edge_and_grows_leftward(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Right-aligned text keeps its right edge within 1 px of the browser's.

        Its slack goes on the left: the box spans the container's content box
        and reaches further left than the text by at least the slack.
        """
        body = _aligned_body("right", "right", "Right aligned label")
        text = _single_line(_document(body), "#right")
        shapes = slide_shapes(_export_one(body, monkeypatch))

        _, box = _text_box(shapes, "Right aligned label")
        browser_right = text["x"] + text["w"]
        emitted_right = box.x + box.w
        assert abs(emitted_right - browser_right) <= ALIGNED_EDGE_TOLERANCE_PX, (
            f"the box {_box(box)} ends at {emitted_right:.2f}; the browser's text ends at "
            f"{browser_right:.2f}"
        )
        assert box.w >= ALIGNED_CONTENT_WIDTH_PX, (
            f"the right-aligned box {_box(box)} is narrower than its container's "
            f"{ALIGNED_CONTENT_WIDTH_PX:.0f} px content box"
        )
        assert box.x <= text["x"] - _slack(text["w"]) + EMU_ROUNDING_PX, (
            f"the right-aligned box {_box(box)} does not grow leftward past the text's left "
            f"{text['x']:.2f} by its slack {_slack(text['w']):.2f}"
        )

    def test_source_white_space_collapses_like_the_browser(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """RC3's raw white space: ``white-space: normal`` content with source newlines,
        indentation and runs of spaces.

        The box reads exactly the browser's collapsed line, and no run carries a
        newline or two consecutive spaces.
        """
        body = (
            '<div class="slide">'
            '<p id="spaced" style="font-size: 18px; width: 700px;">\n'
            "      Revenue   grew\n"
            "      strongly   this    year\n"
            "    </p>"
            "</div>"
        )
        lines = browser_lines(_document(body), "#spaced")
        assert lines == ["Revenue grew strongly this year"], (
            f"fixture drift: the paragraph renders {lines}"
        )
        shapes = slide_shapes(_export_one(body, monkeypatch))

        _, box = _text_box_containing(shapes, "Revenue")
        assert box.text.split("\n") == lines, (
            f"the box reads {box.text!r}; the browser renders {lines}"
        )
        raw = [text for text in _run_texts(shapes) if "\n" in text or "  " in text]
        assert raw == [], f"runs carry raw source white space: {raw}"

    def test_pre_keeps_its_spaces_as_nbsp(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``white-space: pre``: a ``<pre>`` block whose lines start with spaces.

        * Each line's leading spaces are NBSPs in the run text, so no importer
          collapses or trims them.
        * Each line reads as the browser's once NBSP is read as a space, so the
          inner run of two spaces survives too, and it is never two plain spaces.
        """
        body = (
            '<div class="slide">'
            '<pre id="code" style="font-family: var(--mono); font-size: 15px;">'
            "  first line\n    second  line</pre>"
            "</div>"
        )
        lines = browser_lines(_document(body), "#code")
        assert lines == ["  first line", "    second  line"], (
            f"fixture drift: the pre block renders {lines}"
        )
        shapes = slide_shapes(_export_one(body, monkeypatch))

        _, box = _text_box_containing(shapes, "first")
        emitted = box.text.split("\n")
        assert [line.replace(NBSP, " ") for line in emitted] == lines, (
            f"the pre box reads {emitted}; the browser renders {lines}"
        )
        for emitted_line, browser_line in zip(emitted, lines):
            indent = len(browser_line) - len(browser_line.lstrip(" "))
            assert emitted_line[:indent] == NBSP * indent, (
                f"the line {emitted_line!r} does not start with {indent} NBSP(s)"
            )
        doubled = [text for text in _run_texts(shapes) if "  " in text]
        assert doubled == [], f"preserved spaces were written as plain spaces: {doubled}"


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotTextPaintOrder:
    def test_flex_items_paint_atomically_with_their_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Flex items paint atomically: card A's text box follows card A's background and
        precedes card B's background.

        This is the text variant of the Task 1 chip test. The block siblings below
        are the contrast that makes "atomic" observable. Blocks paint every
        background first and their text after, so block B's background comes
        before block A's text. A text box ordered by DOM position satisfies the
        flex half and fails the block half.
        """
        card = "width: 240px; height: 120px;"
        block = "width: 240px; height: 80px;"
        body = (
            '<div class="slide">'
            '<div id="row" style="display: flex; gap: 24px;">'
            f'<div id="card-a" style="{card} background: #DCE0E2;">Card A label</div>'
            f'<div id="card-b" style="{card} background: #5A6F77;">Card B label</div>'
            "</div>"
            '<div id="stack" style="margin-top: 24px;">'
            f'<div id="block-a" style="{block} background: #CDEDE1;">Block A label</div>'
            f'<div id="block-b" style="{block} background: #F8D3D0;">Block B label</div>'
            "</div>"
            "</div>"
        )
        shapes = slide_shapes(_export_one(body, monkeypatch))

        flex_order = [
            ("#card-a background", _filled(shapes, "DCE0E2")[0]),
            ("card A's text", _text_box(shapes, "Card A label")[0]),
            ("#card-b background", _filled(shapes, "5A6F77")[0]),
            ("card B's text", _text_box(shapes, "Card B label")[0]),
        ]
        block_order = [
            ("#block-a background", _filled(shapes, "CDEDE1")[0]),
            ("#block-b background", _filled(shapes, "F8D3D0")[0]),
            ("block A's text", _text_box(shapes, "Block A label")[0]),
            ("block B's text", _text_box(shapes, "Block B label")[0]),
        ]
        for rule, expected in (
            ("flex items paint atomically, each with its own text", flex_order),
            ("block backgrounds paint before the text of any block", block_order),
        ):
            emitted = [label for label, _ in sorted(expected, key=lambda pair: pair[1])]
            assert emitted == [label for label, _ in expected], (
                f"{rule}: expected back-to-front {[label for label, _ in expected]}, emitted "
                f"{emitted} (spTree indices {dict(expected)}):\n{_describe(shapes)}"
            )

    def test_text_after_a_block_child_follows_that_childs_whole_subtree(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bare text after a block child paints after everything inside that child.

        ``#outer`` holds the block ``#block`` (its own text, then the nested
        block ``#nested``) followed by bare text. Line boxes paint in tree order,
        so the emitted order is "Block", then "Nested", then "Bare tail". Placing
        the bare text by its container's position puts it first; placing it
        right after ``#block`` itself, rather than after ``#block``'s whole
        subtree, puts it before "Nested".
        """
        body = (
            '<div class="slide">'
            '<div id="outer" style="font-size: 20px;">'
            '<div id="block">Block<div id="nested">Nested</div></div>Bare tail'
            "</div>"
            "</div>"
        )
        shapes = slide_shapes(_export_one(body, monkeypatch))

        expected = [
            ("Block", _text_box(shapes, "Block")[0]),
            ("Nested", _text_box(shapes, "Nested")[0]),
            ("Bare tail", _text_box(shapes, "Bare tail")[0]),
        ]
        emitted = [label for label, _ in sorted(expected, key=lambda pair: pair[1])]
        assert emitted == [label for label, _ in expected], (
            f"text in tree order: expected {[label for label, _ in expected]}, emitted "
            f"{emitted} (spTree indices {dict(expected)}):\n{_describe(shapes)}"
        )
