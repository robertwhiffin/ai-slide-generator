"""Snapshot engine: inline decorations and atomic inline boxes.

The snapshot engine (``TELLR_EXPORT_ENGINE=snapshot``) keeps a sentence's text
in its sentence and draws what sits inside the line around it (spec §3 Text,
*Inline decorations* and *Inline boxes*):

* an inline element with a background, a border or padding (a pill, a code
  chip, ``<mark>``, ``<kbd>``) is one shape per box fragment the browser lays
  out (``getClientRects()``), so a chip that wraps is two shapes, one on each
  line, and never one box over both lines;
* an inline element with no text at all (an empty swatch or status dot) still
  paints, so it is still a shape (RC8);
* the decorations of a block paint under that block's own text and over every
  block background of their stacking context, as CSS paints inline content
  (CSS 2.1 Appendix E, step 7 after step 4): order key
  ``paint + [4, 0, blockSeq, 0, elSeq]`` for a decoration and
  ``paint + [4, 0, blockSeq, 1]`` for its block's text;
* an atomic inline (an inline ``<svg>`` icon, an ``inline-block`` pill or
  track) splits the line it sits on: the text on each side of it is its own
  single-line text item at its own browser x, so the text after an icon keeps
  its position instead of sliding left into the icon's gap (RC13);
* so does an inline element whose horizontal padding, border or margin take
  space (a code chip, a ``<kbd>``), at both its ends (coordinator ruling on
  Task 5 concern 1): its own text is an item inside its decoration, and the
  text after it keeps its x;
* a page that lies about an element's client rects cannot hang the export or
  lose the decoration silently: it is read correctly or the loss is announced.

Several checks pin layouts the engine must keep while it does this: every delta
pill is exactly one rounded shape under a one-line text box (fixture 06), the
code chip stays on its line and its sentence reads whole (fixture 09, RC13), the
empty legend swatches are filled shapes (fixture 03, RC8), and each icon
badge's label and value are separate items clear of the icon (fixture 12).

Every assertion reads the emitted slide XML (``slide_shapes``) and holds it
against the browser's own layout of the very same document: ``browser_rect``,
``browser_client_rects`` (one rect per box fragment) and
``browser_line_boxes``. Corpus slides are loaded from
``tests/fixtures/export_fidelity`` by prefix (PLAN-CORRECTIONS C4).

An inline ``<svg>`` icon is a capture target (spec §3 Pictures). Its picture
item is pinned with the captures, so here the icon is located by its browser
rect, which is where that picture sits.

Gating matches the sibling export suites: needs node, the extracted sidecar
``node_modules`` and a local Chrome/Chromium (skipped otherwise).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass

import pytest

from src.services import pptx_from_html_huashu
from tests.fixtures.export_snapshot_support import (
    DECK_CSS,
    Shape,
    browser_client_rects,
    browser_line_boxes,
    browser_rect,
    browser_style,
    browser_text,
    corpus_document,
    corpus_slide,
    export_corpus,
    export_slides,
    requires_huashu_sidecar,
    slide_document,
    slide_shapes,
)
from tests.unit.test_export_collection_iteration_hostile_realm import (
    HOSTILE_EXPORT_TIMEOUT_SECONDS,
)
from tests.unit.test_export_snapshot_hostile_realm import COLLECTION_LOSS_LINE

# Tolerances from the plan's Task 5 Step 1: a decoration's rect matches the
# browser's within 0.5 px, and a chip's top lies within 2 px of its line's
# text top.
DECORATION_RECT_TOLERANCE_PX = 0.5
LINE_TOP_TOLERANCE_PX = 2.0
# Task 2's placement of left-aligned text: x is the browser's text left within this.
TEXT_LEFT_TOLERANCE_PX = 0.5
# EMU rounding moves an emitted edge by at most 1/19050 px.
EMU_ROUNDING_PX = 0.01
# Spec §3 Text, Wrapping: every text box gets 6 % plus 4 px of width slack.
SLACK_FRACTION = 0.06
SLACK_PX = 4.0
# A fully round pill: the roundRect corner is half the short side (adj is the
# radius over the short side, in 1/100000), within one point of the side.
PILL_CORNER_ADJ = 50000
PILL_CORNER_ADJ_TOLERANCE = 1000

# The corpus slides this module reads, exported once in this order.
CORPUS_PREFIXES = ("03", "06", "09", "12")

# Fixture 06: the "Change" column's delta pills (inline-block .dk-pill), in
# document order. The up pills are the brief's "▲ 0.30x" pills, filled
# --good-bg (CDEDE1); the one down pill is filled --bad-bg.
DELTA_PILLS = ("▲ 0.30x", "▲ 0.32x", "▼ 0.17x", "▲ 2.7x")
DELTA_PILL = ".dk-pill"
UP_PILL_FILL = "CDEDE1"

# Fixture 09: the second list item holds an inline code chip (display: inline,
# background #EEEDE9, padding 1px 6px) on its first line.
CHIP_ITEM = ".dk-list li"
CHIP_ITEM_INDEX = 1
CHIP = ".dk-chip"
CHIP_LINE_START = "Mix shift toward"
CHIP_SENTENCE = "with SKU-7 now 31% of revenue"

# Fixture 03: the legend's empty inline-block swatches. The third legend marker
# is an inline <svg> line, a picture rather than a swatch.
LEGEND_SWATCH = ".dk-legend span.sw"
LEGEND_SWATCH_COUNT = 2

# Fixture 12: each row's badge is a flex span holding an <svg> icon then its
# label; the value is a sibling flex item. Rows in document order.
BADGE = ".slide span:has(> svg)"
BADGE_ICON = ".slide span:has(> svg) > svg"
BADGE_ROWS = (
    ("Plant automation", "80%"),
    ("ERP upgrade", "55%"),
    ("New tooling line", "62%"),
    ("Warehouse expansion", "35%"),
)

# A chip long enough to wrap inside a 300 px paragraph, so it has two box
# fragments: the first ends the first line, the second starts the next one.
WRAPPING_CHIP_BODY = (
    '<div class="slide">'
    '<p id="note" style="width: 300px; font-size: 20px; line-height: 1.45;">'
    'Ship the <code id="chip" class="dk-chip">premium bearing assembly</code> '
    "before the quarter ends</p>"
    "</div>"
)

# A key in a sentence: a bordered, padded inline <kbd>. The text after it is in an
# unstyled span only so that its browser x can be measured.
KEY_BORDER_PX = 1.0
KEY_SENTENCE_BODY = (
    '<div class="slide">'
    '<p id="press" style="font-size: 20px;">Press '
    '<kbd id="esc" style="font-family: var(--mono); background: #F9F7F4; '
    f'border: {KEY_BORDER_PX:g}px solid #5A6F77; border-radius: 4px; padding: 1px 5px;">'
    'Esc</kbd> <span id="after-key">to continue</span></p>'
    "</div>"
)
# A padded inline element's text and the text after it are placed within this of
# the browser's x (coordinator ruling on Task 5 concern 1).
PADDED_INLINE_X_TOLERANCE_PX = 1.0

# Insets with text on one side only on their line (Task 5 fix round 1). Under
# box-decoration-break: slice an inline element's start inset is on the line of
# its first fragment, before the text after it, and its end inset on the line of
# its last, after the text before it.
STATUS_DOT_STYLE = "background: #00A972; padding: 0 6px; border-radius: 6px; margin-right: 10px;"
# A status dot leading a paragraph that wraps: only its first line is pushed right.
DOT_LED_WRAPPED_BODY = (
    '<div class="slide">'
    '<p id="status" style="width: 320px; font-size: 18px;">'
    f'<span id="status-dot" style="{STATUS_DOT_STYLE}"></span>'
    "Plant automation is on schedule and tracking well ahead of the plan for the year</p>"
    "</div>"
)
# A padded highlight over a whole wrapped paragraph: its start padding pushes only
# its first line right, its end padding follows only its last.
HIGHLIGHT_SPANNING_BODY = (
    '<div class="slide">'
    '<p id="spanning" style="width: 320px; font-size: 18px;">'
    '<mark id="spanning-mark" style="background: #FFE08A; padding: 0 8px;">'
    "The highlight runs across every line of this wrapped paragraph to its very end</mark></p>"
    "</div>"
)
# A centred line led by the dot: the browser centres the dot and the text together,
# so the text sits right of the paragraph's centre.
DOT_LED_CENTRED_BODY = (
    '<div class="slide">'
    '<p id="centred" style="text-align: center; font-size: 18px;">'
    f'<span id="centred-dot" style="{STATUS_DOT_STYLE}"></span>Plant automation on track</p>'
    "</div>"
)
# The same line ended by a dot (its gap on its left): the text sits left of the
# centre, and the inset is on the line's end, after the text's last token.
TRAILING_DOT_STYLE = "background: #D0302A; padding: 0 6px; border-radius: 6px; margin-left: 10px;"
DOT_ENDED_CENTRED_BODY = (
    '<div class="slide">'
    '<p id="centred" style="text-align: center; font-size: 18px;">'
    f'ERP upgrade at risk<span id="centred-dot" style="{TRAILING_DOT_STYLE}"></span></p>'
    "</div>"
)
# Each centred case: its body, and the side of the paragraph's centre its text sits on.
CENTRED_DOT_LINES = {
    "led-by-the-dot": (DOT_LED_CENTRED_BODY, 1),
    "ended-by-the-dot": (DOT_ENDED_CENTRED_BODY, -1),
}
# A right-to-left sentence led by a padded chip that wraps: the chip's start (right)
# padding is on its first line, which holds nothing else.
RTL_CHIP_BODY = (
    '<div class="slide">'
    '<p id="rtl" dir="rtl" style="width: 300px; font-size: 20px; line-height: 1.45;">'
    '<code id="rtl-chip" class="dk-chip">מכלול המסבים המשופר של הקו החדש במפעל הצפוני</code> '
    '<span id="rtl-after">לפני סוף הרבעון</span></p>'
    "</div>"
)
# Fix round 1's tolerances: a left edge within 0.5 px, a centre or right edge within 1 px.
LINE_EDGE_TOLERANCE_PX = 0.5
LINE_CENTRE_TOLERANCE_PX = 1.0
RTL_EDGE_TOLERANCE_PX = 1.0

# Page script that replaces Element.prototype.getClientRects with one that
# reports a trillion rects and holds none, then publishes on document.title what
# it replaced and whether a reader of the realm now sees the lie, so the
# poisoning is proven rather than assumed.
HOSTILE_ELEMENT_RECTS_SCRIPT = (
    "<script>(function () {"
    "var report = { configurable: {}, bites: {}, redefineResult: 'ok' };"
    "var descriptor = Object.getOwnPropertyDescriptor(Element.prototype, 'getClientRects');"
    "report.configurable['Element.getClientRects'] = !!(descriptor && descriptor.configurable);"
    "try {"
    " Object.defineProperty(Element.prototype, 'getClientRects', {"
    "  configurable: true, writable: true,"
    "  value: function () { return { length: 1e12 }; } });"
    "} catch (error) { report.redefineResult = 'refused getClientRects: ' + error.message; }"
    "report.bites = {"
    " getClientRects: document.documentElement.getClientRects().length === 1e12 };"
    "document.title = JSON.stringify(report);"
    "})();</script>"
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
    """Corpus slides 03, 06, 09 and 12, exported once through the snapshot engine."""
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


def _box(shape: Shape) -> dict:
    return {
        "x": round(shape.x, 3),
        "y": round(shape.y, 3),
        "w": round(shape.w, 3),
        "h": round(shape.h, 3),
    }


def _describe(shapes: list[Shape]) -> str:
    lines = []
    for position, shape in enumerate(shapes):
        if shape.kind == "text":
            detail = f"wrap={shape.wrap} paras={len(shape.paras)} text={shape.text[:60]!r}"
        else:
            detail = f"{shape.geometry} fill={shape.fill} line={shape.line} adj={shape.adj}"
        lines.append(f"  [{position}] {shape.kind} box={_box(shape)} {detail}")
    return "\n".join(lines) or "  (no shapes)"


def _hex(css_colour: str) -> str:
    """'RRGGBB' of an opaque ``rgb(r, g, b)`` computed colour (a fixture guard)."""
    assert css_colour.startswith("rgb(") and css_colour.endswith(")"), (
        f"fixture drift: expected an opaque rgb() colour, got {css_colour!r}"
    )
    channels = [int(part.strip()) for part in css_colour[4:-1].split(",")]
    return "".join(f"{channel:02X}" for channel in channels)


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
    """(spTree index, shape) of the one text box whose normalised text contains ``fragment``."""
    matches = [
        (position, shape)
        for position, shape in enumerate(shapes)
        if shape.kind == "text" and fragment in _normalised(shape.text)
    ]
    assert len(matches) == 1, (
        f"expected exactly one text box containing {fragment!r}, got {len(matches)}:\n"
        f"{_describe(shapes)}"
    )
    return matches[0]


def _filled(shapes: list[Shape], fill: str) -> list[tuple[int, Shape]]:
    """(spTree index, shape) of every non-text element filled ``fill``, in spTree order."""
    return [
        (position, shape)
        for position, shape in enumerate(shapes)
        if shape.kind != "text" and shape.fill == fill
    ]


def _one_filled(shapes: list[Shape], fill: str, what: str) -> tuple[int, Shape]:
    matches = _filled(shapes, fill)
    assert len(matches) == 1, (
        f"{what}: expected exactly one shape filled {fill}, got {len(matches)}:\n"
        f"{_describe(shapes)}"
    )
    return matches[0]


def _off_by(shape: Shape, rect: dict) -> dict:
    return {
        "x": round(shape.x - rect["x"], 3),
        "y": round(shape.y - rect["y"], 3),
        "w": round(shape.w - rect["w"], 3),
        "h": round(shape.h - rect["h"], 3),
    }


def _matches(shape: Shape, rect: dict, tolerance: float) -> bool:
    return all(abs(delta) <= tolerance for delta in _off_by(shape, rect).values())


def _assert_at(shape: Shape, rect: dict, what: str) -> None:
    assert _matches(shape, rect, DECORATION_RECT_TOLERANCE_PX), (
        f"{what}: the emitted shape {_box(shape)} differs from the browser rect {rect} by "
        f"{_off_by(shape, rect)} (tolerance {DECORATION_RECT_TOLERANCE_PX} px)"
    )


def _shapes_at(shapes: list[Shape], rect: dict) -> list[tuple[int, Shape]]:
    """(spTree index, shape) of every non-text element whose box is ``rect`` within tolerance."""
    return [
        (position, shape)
        for position, shape in enumerate(shapes)
        if shape.kind != "text" and _matches(shape, rect, DECORATION_RECT_TOLERANCE_PX)
    ]


def _inset(rect: dict, by: float) -> dict:
    """``rect`` shrunk by ``by`` on every side: where a bordered shape's outline centre runs."""
    return {
        "x": rect["x"] + by,
        "y": rect["y"] + by,
        "w": rect["w"] - 2 * by,
        "h": rect["h"] - 2 * by,
    }


def _painted_fragments(document: str, selector: str) -> list[dict]:
    """The element's box fragments that have area, top to bottom."""
    rects = [
        rect for rect in browser_client_rects(document, selector) if rect["w"] > 0 and rect["h"] > 0
    ]
    return sorted(rects, key=lambda rect: (rect["y"], rect["x"]))


def _single_line(document: str, selector: str, index: int = 0) -> dict:
    """The one rendered line of the ``index``-th match of ``selector`` (a fixture guard)."""
    lines = browser_line_boxes(document, selector, index)
    assert len(lines) == 1, (
        f"fixture drift: {selector} [{index}] renders {len(lines)} lines: {lines}"
    )
    return lines[0]


def _vertical_overlap(a: dict, b: dict) -> float:
    return min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])


def _assert_back_to_front(shapes: list[Shape], expected: list[tuple[str, int]], rule: str) -> None:
    """The ``(label, spTree index)`` pairs appear in spTree in the listed order."""
    emitted = [label for label, _ in sorted(expected, key=lambda pair: pair[1])]
    assert emitted == [label for label, _ in expected], (
        f"{rule}: expected back-to-front {[label for label, _ in expected]}, emitted {emitted} "
        f"(spTree indices {dict(expected)}):\n{_describe(shapes)}"
    )


def _assert_one_unwrapped_line(box: Shape, what: str) -> None:
    soft_breaks = [run.text for para in box.paras for run in para.runs if run.soft_break_before]
    assert len(box.paras) == 1 and not soft_breaks and "\n" not in box.text, (
        f"{what}: expected one line in one paragraph, got {len(box.paras)} paragraph(s) and "
        f"soft breaks before {soft_breaks}: {box.text!r}"
    )
    assert box.wrap == "none", f"{what}: a one-line text item must not wrap, got wrap={box.wrap!r}"


def _assert_reads_as_lines(
    shapes: list[Shape], area: dict, lines: list[dict], what: str
) -> list[int]:
    """The text items of a paragraph a padded inline element cuts read the browser's lines.

    A padded, bordered or margined inline element cuts every line it is on
    (coordinator ruling on Task 5 concern 1), so its paragraph is several
    single-line items rather than one box. The items whose vertical middle
    lies in ``area`` (the paragraph's browser rect) must each be one unwrapped
    line lying on exactly one of the browser's ``lines``, and the items on each
    line, read left to right with single spaces, must be that line's text: no
    text lost, doubled, moved to another line or left with a two-space gap.
    These paragraphs are cut only at spaces, so a single space joins the items.
    Returns the items' spTree indices, in spTree order.
    """
    items = [
        (position, shape)
        for position, shape in enumerate(shapes)
        if shape.kind == "text"
        and area["y"] <= shape.y + shape.h / 2 <= area["y"] + area["h"]
        and shape.x < area["x"] + area["w"]
        and shape.x + shape.w > area["x"]
    ]
    on_line: dict[int, list[Shape]] = {number: [] for number in range(len(lines))}
    for _, shape in items:
        _assert_one_unwrapped_line(shape, f"{what}: the item {shape.text!r}")
        middle = shape.y + shape.h / 2
        holding = [
            number
            for number, line in enumerate(lines)
            if line["y"] <= middle <= line["y"] + line["h"]
        ]
        assert len(holding) == 1, (
            f"{what}: the item {_box(shape)} {shape.text!r} lies on browser lines {holding} of "
            f"{lines}"
        )
        on_line[holding[0]].append(shape)
    read = [
        " ".join(_normalised(shape.text) for shape in sorted(on_line[number], key=lambda s: s.x))
        for number in range(len(lines))
    ]
    assert read == [line["text"] for line in lines], (
        f"{what}: its items read {read} line by line; the browser's lines are "
        f"{[line['text'] for line in lines]}\n{_describe(shapes)}"
    )
    return [position for position, _ in items]


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotInlineDecorations:
    def test_delta_pills_are_one_round_shape_each_under_a_one_line_text_box(
        self, corpus_pptx: bytes
    ) -> None:
        """Fixture 06's delta pills (``inline-block``, ``border-radius: 999px``) in the table.

        For every pill:

        * exactly one shape lies at the pill's browser rect, within 0.5 px: a
          ``roundRect`` whose corners are fully round, filled the pill's
          colour (the up pills ``CDEDE1``), so no pill is drawn twice;
        * its text is one text box, reading the browser's one line: the arrow
          and the number share that line, in one paragraph with no soft break,
          and the box is unwrapped (``wrap="none"``);
        * that text box lies inside the pill rect, plus the box's width slack
          on the side left-aligned text grows;
        * the pill's shape precedes its text box in the spTree, so the pill
          paints under its text.
        """
        document = corpus_document("06")
        shapes = _corpus_shapes(corpus_pptx, "06")

        for index, label in enumerate(DELTA_PILLS):
            pill = browser_rect(document, DELTA_PILL, index)
            line = _single_line(document, DELTA_PILL, index)
            assert line["text"] == label, (
                f"fixture drift: pill {index} reads {line['text']!r}, expected {label!r}"
            )
            fill = _hex(browser_style(document, DELTA_PILL, index)["backgroundColor"])
            if label.startswith("▲"):
                assert fill == UP_PILL_FILL, (
                    f"fixture drift: the up pill {label!r} is filled {fill}, not {UP_PILL_FILL}"
                )

            at_pill = _shapes_at(shapes, pill)
            assert len(at_pill) == 1, (
                f"pill {label!r}: expected exactly one shape at its browser rect {pill}, got "
                f"{len(at_pill)}:\n{_describe(shapes)}"
            )
            shape_index, shape = at_pill[0]
            assert shape.fill == fill and shape.geometry == "roundRect", (
                f"pill {label!r}: the shape at its rect is {shape.geometry} filled {shape.fill}; "
                f"expected a roundRect filled {fill}"
            )
            assert shape.adj is not None and abs(shape.adj - PILL_CORNER_ADJ) <= (
                PILL_CORNER_ADJ_TOLERANCE
            ), (
                f"pill {label!r}: corner adj {shape.adj}; a fully round pill is "
                f"{PILL_CORNER_ADJ} (half its short side)"
            )

            text_index, text = _text_box(shapes, label)
            _assert_one_unwrapped_line(text, f"pill {label!r}")
            right_limit = pill["x"] + pill["w"] + _slack(line["w"])
            inside = (
                text.x >= pill["x"] - TEXT_LEFT_TOLERANCE_PX
                and text.y >= pill["y"] - TEXT_LEFT_TOLERANCE_PX
                and text.y + text.h <= pill["y"] + pill["h"] + TEXT_LEFT_TOLERANCE_PX
                and text.x + text.w <= right_limit + EMU_ROUNDING_PX
            )
            assert inside, (
                f"pill {label!r}: its text box {_box(text)} is not inside the pill {pill} plus "
                f"slack (right edge limit {right_limit:.2f})"
            )
            _assert_back_to_front(
                shapes,
                [(f"pill {label!r} shape", shape_index), (f"pill {label!r} text", text_index)],
                "a pill paints under its own text",
            )

    def test_code_chip_stays_on_its_line_and_its_sentence_reads_whole(
        self, corpus_pptx: bytes
    ) -> None:
        """RC13, fixture 09: the inline code chip "SKU-7" in a list item's sentence.

        * The chip is one shape filled ``EEEDE9`` at its browser fragment rect,
          within 0.5 px. It sits on the sentence's first line, "Mix shift
          toward…": its top is within 2 px of that line's text top and its
          vertical middle lies inside that line.
        * The chip's padding cuts its line (coordinator ruling on Task 5
          concern 1), so the sentence is several single-line items. They read
          the browser's lines, and "with SKU-7 now 31% of revenue" across its
          break with single spaces: the chip was not pulled out of its line,
          so no gap of two spaces is left ("with  now").
        * The chip's shape precedes every text item of its sentence in the
          spTree.
        """
        document = corpus_document("09")
        fragments = _painted_fragments(document, CHIP)
        assert len(fragments) == 1, f"fixture drift: the chip has fragments {fragments}"
        chip_rect = fragments[0]
        lines = browser_line_boxes(document, CHIP_ITEM, CHIP_ITEM_INDEX)
        assert len(lines) == 2 and lines[0]["text"].startswith(CHIP_LINE_START), (
            f"fixture drift: the chip's list item renders {lines}"
        )
        first_line = lines[0]
        fill = _hex(browser_style(document, CHIP)["backgroundColor"])
        shapes = _corpus_shapes(corpus_pptx, "09")

        chip_index, chip = _one_filled(shapes, fill, "the code chip")
        _assert_at(chip, chip_rect, "the code chip")
        assert abs(chip.y - first_line["y"]) <= LINE_TOP_TOLERANCE_PX, (
            f"the chip's top {chip.y:.2f} is not within {LINE_TOP_TOLERANCE_PX} px of its line's "
            f"text top {first_line['y']:.2f}"
        )
        middle = chip.y + chip.h / 2
        assert first_line["y"] <= middle <= first_line["y"] + first_line["h"], (
            f"the chip {_box(chip)} is not on the line {first_line}"
        )

        sentence = _assert_reads_as_lines(
            shapes, browser_rect(document, CHIP_ITEM, CHIP_ITEM_INDEX), lines, "the chip's item"
        )
        read = " ".join(_normalised(shapes[position].text) for position in sentence)
        assert CHIP_SENTENCE in read, (
            f"the sentence's items do not read {CHIP_SENTENCE!r} with single spaces: {read!r}"
        )
        for position in sentence:
            _assert_back_to_front(
                shapes,
                [("the chip", chip_index), (f"its sentence's {shapes[position].text!r}", position)],
                "a chip paints under the text of its own sentence",
            )

    def test_a_chip_that_wraps_is_one_shape_per_line_fragment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A ``.dk-chip`` long enough to wrap inside a 300 px paragraph has two box fragments.

        * It gives exactly two shapes, filled the chip's colour, each at one of
          the browser's fragment rects (``getClientRects()``) within 0.5 px: the
          first ends line 1, the second starts line 2. One shape at the chip's
          bounding rect would paint the chip's colour over both whole lines,
          under "Ship the" and "before the quarter" too.
        * Both shapes precede every text item of the sentence in the spTree.
        * The chip's text stays on the browser's lines: its padding cuts both
          lines it is on (coordinator ruling on Task 5 concern 1), and the
          sentence's items read the browser's lines.
        """
        document = _document(WRAPPING_CHIP_BODY)
        fragments = _painted_fragments(document, "#chip")
        assert len(fragments) == 2, f"fixture drift: the chip has fragments {fragments}"
        assert _vertical_overlap(fragments[0], fragments[1]) < fragments[0]["h"] / 2, (
            f"fixture drift: the chip's fragments {fragments} are not on two lines"
        )
        lines = browser_line_boxes(document, "#note")
        fill = _hex(browser_style(document, "#chip")["backgroundColor"])
        shapes = slide_shapes(_export_one(WRAPPING_CHIP_BODY, monkeypatch))

        chips = _filled(shapes, fill)
        assert len(chips) == 2, (
            f"expected one shape filled {fill} per chip fragment ({len(fragments)}: "
            f"{fragments}), got {len(chips)}:\n{_describe(shapes)}"
        )
        chips_top_down = sorted(chips, key=lambda pair: (pair[1].y, pair[1].x))
        for line_number, ((_, chip), fragment) in enumerate(
            zip(chips_top_down, fragments), start=1
        ):
            _assert_at(chip, fragment, f"the chip's line-{line_number} fragment")

        sentence = _assert_reads_as_lines(
            shapes, browser_rect(document, "#note"), lines, "the chip's sentence"
        )
        for line_number, (chip_index, _) in enumerate(chips_top_down, start=1):
            for position in sentence:
                _assert_back_to_front(
                    shapes,
                    [
                        (f"chip fragment {line_number}", chip_index),
                        (f"the sentence's {shapes[position].text!r}", position),
                    ],
                    "every chip fragment paints under the text of its sentence",
                )

    def test_inline_decorations_paint_under_their_own_text_and_over_block_backgrounds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CSS paints inline content after every block background of its stacking context
        (CSS 2.1 Appendix E, step 7 after step 4), one block's line boxes at a time.

        Two paragraphs, a ``<mark>`` in the first and a bordered ``<kbd>`` in the
        second, then a band (a later block with a background) pulled up under
        the second paragraph by a negative margin, so it overlaps the key. The
        back-to-front order is:

        1. the band's background (step 4, every block background first);
        2. the mark, then the first paragraph's text;
        3. the key, then the second paragraph's text: every item of it, since
           the key's border and padding cut its line (coordinator ruling on
           Task 5 concern 1).

        A decoration ordered as a block box in tree order paints under the band
        it should cover, and every decoration before the first paragraph's text.

        Each decoration sits at its browser fragment rect within 0.5 px; the key,
        whose 1 px border is its outline, is inset by half that border, where
        the outline's centre runs.
        """
        key_border_px = 1.0
        body = (
            '<div class="slide">'
            '<p id="first" style="font-size: 20px;">Alpha with a '
            '<mark id="mark" style="background: #FFE08A;">highlight</mark> inside</p>'
            '<p id="second" style="font-size: 20px;">Press '
            '<kbd id="key" style="font-family: var(--mono); background: #F9F7F4; '
            f'border: {key_border_px:g}px solid #5A6F77; border-radius: 4px; padding: 1px 5px;">'
            "Ctrl</kbd> to continue</p>"
            '<div id="band" style="height: 30px; margin-top: -40px; background: #DCE0E2;"></div>'
            "</div>"
        )
        document = _document(body)
        mark_fragments = _painted_fragments(document, "#mark")
        key_fragments = _painted_fragments(document, "#key")
        assert len(mark_fragments) == 1 and len(key_fragments) == 1, (
            f"fixture drift: the mark has fragments {mark_fragments}, the key {key_fragments}"
        )
        band = browser_rect(document, "#band")
        key_rect = key_fragments[0]
        assert _vertical_overlap(band, key_rect) > 0 and band["x"] <= key_rect["x"], (
            f"fixture drift: the band {band} does not overlap the key {key_rect}"
        )
        shapes = slide_shapes(_export_one(body, monkeypatch))

        mark_index, mark = _one_filled(shapes, "FFE08A", "the mark")
        key_index, key = _one_filled(shapes, "F9F7F4", "the key")
        band_index, _ = _one_filled(shapes, "DCE0E2", "the band")
        _assert_at(mark, mark_fragments[0], "the mark")
        _assert_at(key, _inset(key_rect, key_border_px / 2), "the key (outline centre)")
        assert key.line == "5A6F77", f"the key's outline is {key.line}, not its border 5A6F77"
        first_index, _ = _text_box(shapes, "Alpha with a highlight inside")
        second = _assert_reads_as_lines(
            shapes,
            browser_rect(document, "#second"),
            browser_line_boxes(document, "#second"),
            "the second paragraph",
        )
        # The earliest of its items: the key must precede every one of them.
        second_index = min(second)

        _assert_back_to_front(
            shapes,
            [
                ("the band's background", band_index),
                ("the mark", mark_index),
                ("the first paragraph's text", first_index),
                ("the key", key_index),
                ("the second paragraph's text", second_index),
            ],
            "inline decorations paint over block backgrounds, each under its own block's text",
        )

    def test_empty_inline_dots_are_shapes_painted_with_their_own_row(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An inline element with no text but a background and padding (a status dot) paints.

        Each row is a paragraph led by an empty ``<span>`` dot. Each dot is one
        shape filled its colour at its browser fragment rect, within 0.5 px, and
        paints with its own row: the first dot, the first row's text, the second
        dot, the second row's text.
        """
        dot = "padding: 0 6px; border-radius: 6px; margin-right: 10px;"
        body = (
            '<div class="slide">'
            '<p id="row-1" style="font-size: 18px;">'
            f'<span id="dot-1" style="background: #00A972; {dot}"></span>'
            "Plant automation on track</p>"
            '<p id="row-2" style="font-size: 18px;">'
            f'<span id="dot-2" style="background: #D0302A; {dot}"></span>'
            "ERP upgrade at risk</p>"
            "</div>"
        )
        document = _document(body)
        dots = {}
        for name in ("dot-1", "dot-2"):
            assert browser_text(document, f"#{name}") == "", f"fixture drift: #{name} has text"
            fragments = _painted_fragments(document, f"#{name}")
            assert len(fragments) == 1, f"fixture drift: #{name} has fragments {fragments}"
            dots[name] = fragments[0]
        shapes = slide_shapes(_export_one(body, monkeypatch))

        first_dot_index, first_dot = _one_filled(shapes, "00A972", "the first dot")
        second_dot_index, second_dot = _one_filled(shapes, "D0302A", "the second dot")
        _assert_at(first_dot, dots["dot-1"], "the first dot")
        _assert_at(second_dot, dots["dot-2"], "the second dot")
        first_row_index, _ = _text_box(shapes, "Plant automation on track")
        second_row_index, _ = _text_box(shapes, "ERP upgrade at risk")

        _assert_back_to_front(
            shapes,
            [
                ("the first dot", first_dot_index),
                ("the first row's text", first_row_index),
                ("the second dot", second_dot_index),
                ("the second row's text", second_row_index),
            ],
            "an empty inline decoration paints with its own block's text",
        )

    def test_empty_legend_swatches_are_filled_shapes(self, corpus_pptx: bytes) -> None:
        """RC8, fixture 03: the legend's empty ``span.sw`` swatches (``inline-block``, 14x14).

        Each swatch has no text and is exactly one shape at its browser rect,
        within 0.5 px, filled the colour the browser paints it. The legend's
        third marker is an inline ``<svg>`` line, a picture rather than a swatch.
        """
        assert corpus_slide("03").count('class="sw"') == LEGEND_SWATCH_COUNT, (
            f"fixture drift: fixture 03 no longer has {LEGEND_SWATCH_COUNT} legend swatches"
        )
        document = corpus_document("03")
        shapes = _corpus_shapes(corpus_pptx, "03")

        for index in range(LEGEND_SWATCH_COUNT):
            assert browser_text(document, LEGEND_SWATCH, index) == "", (
                f"fixture drift: swatch {index} has text"
            )
            swatch = browser_rect(document, LEGEND_SWATCH, index)
            fill = _hex(browser_style(document, LEGEND_SWATCH, index)["backgroundColor"])
            at_swatch = _shapes_at(shapes, swatch)
            assert len(at_swatch) == 1, (
                f"swatch {index}: expected exactly one shape at its browser rect {swatch}, got "
                f"{len(at_swatch)}:\n{_describe(shapes)}"
            )
            assert at_swatch[0][1].fill == fill, (
                f"swatch {index}: the shape at its rect is filled {at_swatch[0][1].fill}, "
                f"the browser paints {fill}"
            )


@dataclass(frozen=True)
class InlineGraphicLine:
    """A line that an atomic inline splits, and the browser selectors that locate its parts."""

    body: str
    paragraph: str  # the block holding the line
    before: str  # the text just left of the splitting graphic (an unstyled span)
    before_text: str
    graphic: str  # the atomic inline that splits the line
    after: str  # the text just right of it
    after_text: str
    leading_graphic: str | None = None  # a graphic the line starts with, left of `before`


ICON_PATH = '<circle cx="12" cy="12" r="9"/>'

INLINE_GRAPHIC_LINES = {
    # Fixture 12's badge row in inline flow: an icon, the label, a progress
    # track (an empty inline-block), then the value, all on one line.
    "icon-badge-inline": InlineGraphicLine(
        body=(
            '<div class="slide">'
            '<p id="row" style="font-size: 18px; font-weight: 600;">'
            '<svg id="icon" width="22" height="22" viewBox="0 0 24 24" fill="none" '
            'stroke="currentColor" stroke-width="2.2" '
            'style="vertical-align: middle; margin-right: 10px; color: var(--accent);">'
            f"{ICON_PATH}</svg>"
            '<span id="label">Plant automation</span>'
            '<span id="track" style="display: inline-block; width: 200px; height: 8px; '
            'margin: 0 16px; border-radius: 4px; background: #E6E3DE; vertical-align: middle;">'
            "</span>"
            '<span id="value" style="font-family: var(--mono); font-size: 16px; font-weight: 400;">'
            "80%</span>"
            "</p>"
            "</div>"
        ),
        paragraph="#row",
        before="#label",
        before_text="Plant automation",
        graphic="#track",
        after="#value",
        after_text="80%",
        leading_graphic="#icon",
    ),
    # A delta pill in the middle of a sentence.
    "pill-in-a-sentence": InlineGraphicLine(
        body=(
            '<div class="slide">'
            '<p id="sentence" style="font-size: 20px;">'
            '<span id="before">Revenue grew</span> '
            '<span id="pill" class="dk-pill up">▲ 4.2%</span> '
            '<span id="after">year on year</span>'
            "</p>"
            "</div>"
        ),
        paragraph="#sentence",
        before="#before",
        before_text="Revenue grew",
        graphic="#pill",
        after="#after",
        after_text="year on year",
    ),
    # A wrapped paragraph whose second line holds an icon between two words.
    "icon-on-a-wrapped-line": InlineGraphicLine(
        body=(
            '<div class="slide">'
            '<p id="wrapped" style="width: 320px; font-size: 18px;">'
            "Plant automation is on schedule and "
            '<span id="before">tracking at</span>'
            '<svg id="icon" width="20" height="20" viewBox="0 0 24 24" fill="none" '
            'stroke="#FF5F46" stroke-width="2.2" style="vertical-align: middle; margin: 0 8px;">'
            f"{ICON_PATH}</svg>"
            '<span id="after">80%</span>'
            "</p>"
            "</div>"
        ),
        paragraph="#wrapped",
        before="#before",
        before_text="tracking at",
        graphic="#icon",
        after="#after",
        after_text="80%",
    ),
}


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotAtomicInlines:
    def test_icon_badge_label_and_value_are_separate_items_clear_of_the_icon(
        self, corpus_pptx: bytes
    ) -> None:
        """Fixture 12's icon badges: in each row an ``<svg>`` icon, its label, then the value.

        * No text item holds both the label and the value; each is one
          unwrapped text item of its own.
        * The label's box starts at the label's browser text left, within
          0.5 px, which is right of the icon's browser rect: the label never
          overlaps its icon.
        """
        document = corpus_document("12")
        shapes = _corpus_shapes(corpus_pptx, "12")

        for row, (label, value) in enumerate(BADGE_ROWS):
            label_line = _single_line(document, BADGE, row)
            assert label_line["text"] == label, (
                f"fixture drift: badge {row} reads {label_line['text']!r}, not {label!r}"
            )
            icon = browser_rect(document, BADGE_ICON, row)
            icon_right = icon["x"] + icon["w"]
            assert label_line["x"] >= icon_right, (
                f"fixture drift: badge {row}'s label {label_line} starts left of its icon {icon}"
            )
            merged = [
                shape.text
                for shape in shapes
                if shape.kind == "text" and label in shape.text and value in shape.text
            ]
            assert merged == [], f"row {row}: the label and the value share a text item: {merged}"
            _, label_box = _text_box(shapes, label)
            _, value_box = _text_box(shapes, value)
            _assert_one_unwrapped_line(label_box, f"the {label!r} label")
            _assert_one_unwrapped_line(value_box, f"the {value!r} value")
            assert abs(label_box.x - label_line["x"]) <= TEXT_LEFT_TOLERANCE_PX, (
                f"the {label!r} box {_box(label_box)} starts at {label_box.x:.2f}; the browser's "
                f"label starts at {label_line['x']:.2f}"
            )
            assert label_box.x >= icon_right - EMU_ROUNDING_PX, (
                f"the {label!r} box {_box(label_box)} starts left of its icon's right edge "
                f"{icon_right:.2f} (icon {icon})"
            )

    @pytest.mark.parametrize("case", tuple(INLINE_GRAPHIC_LINES))
    def test_an_inline_graphic_splits_its_line_and_the_text_after_it_keeps_its_x(
        self, monkeypatch: pytest.MonkeyPatch, case: str
    ) -> None:
        """An atomic inline (an inline ``<svg>``, an ``inline-block`` pill or track) on a line.

        The tokens on each side of it are separate single-line text items at
        their own bounds, so in PowerPoint and Google Slides the text after the
        graphic is drawn where the browser drew it, not slid left into the
        graphic's gap:

        * no text item holds both the text before the graphic and the text after it;
        * each of the two is one unwrapped text item (``wrap="none"``) whose x
          is its browser text left within 0.5 px;
        * the text after the graphic starts right of the graphic's browser rect;
          with ``leading_graphic``, the text before it starts right of that one;
        * no character is lost or doubled by the split: the slide's text items
          hold exactly the characters the browser paints in the paragraph.

        Cases: fixture 12's badge row set in inline flow (``icon-badge-inline``),
        a delta pill inside a sentence, and an icon on the second line of a
        wrapped paragraph.
        """
        line = INLINE_GRAPHIC_LINES[case]
        document = _document(line.body)
        before = _single_line(document, line.before)
        after = _single_line(document, line.after)
        assert before["text"] == line.before_text and after["text"] == line.after_text, (
            f"fixture drift: the line reads {before['text']!r} | {after['text']!r}"
        )
        assert _vertical_overlap(before, after) > min(before["h"], after["h"]) / 2, (
            f"fixture drift: {before} and {after} are not on one line"
        )
        graphic = browser_rect(document, line.graphic)
        graphic_right = graphic["x"] + graphic["w"]
        assert before["x"] + before["w"] <= graphic["x"] and after["x"] >= graphic_right, (
            f"fixture drift: the graphic {graphic} does not sit between {before} and {after}"
        )
        painted = Counter(
            character
            for entry in browser_line_boxes(document, line.paragraph)
            for character in entry["text"]
            if not character.isspace()
        )
        shapes = slide_shapes(_export_one(line.body, monkeypatch))

        merged = [
            shape.text
            for shape in shapes
            if shape.kind == "text"
            and line.before_text in _normalised(shape.text)
            and line.after_text in _normalised(shape.text)
        ]
        assert merged == [], (
            f"the text either side of the graphic shares a text item: {merged}\n{_describe(shapes)}"
        )
        _, before_box = _text_box(shapes, line.before_text)
        _, after_box = _text_box(shapes, line.after_text)
        for what, box, browser in (
            ("before the graphic", before_box, before),
            ("after the graphic", after_box, after),
        ):
            _assert_one_unwrapped_line(box, f"the text {what}")
            assert abs(box.x - browser["x"]) <= TEXT_LEFT_TOLERANCE_PX, (
                f"the text {what} {_box(box)} starts at {box.x:.2f}; the browser draws it at "
                f"{browser['x']:.2f}"
            )
        assert after_box.x >= graphic_right - TEXT_LEFT_TOLERANCE_PX, (
            f"the text after the graphic {_box(after_box)} starts left of the graphic's right "
            f"edge {graphic_right:.2f} (graphic {graphic})"
        )
        if line.leading_graphic is not None:
            leading = browser_rect(document, line.leading_graphic)
            leading_right = leading["x"] + leading["w"]
            assert before_box.x >= leading_right - TEXT_LEFT_TOLERANCE_PX, (
                f"the text before the graphic {_box(before_box)} starts left of the leading "
                f"graphic's right edge {leading_right:.2f} (graphic {leading})"
            )
        emitted = Counter(
            character
            for shape in shapes
            if shape.kind == "text"
            for character in shape.text
            if not character.isspace()
        )
        assert emitted == painted, (
            f"the split lost or doubled text: missing {dict(painted - emitted)}, extra "
            f"{dict(emitted - painted)}\n{_describe(shapes)}"
        )


def _assert_padded_inline_is_cut(
    shapes: list[Shape],
    document: str,
    *,
    element: str,
    element_text: str,
    border_px: float,
    after_text: str,
    after_x: float,
) -> None:
    """A padded or bordered inline element cuts its line (coordinator ruling, Task 5 concern 1).

    * Its decoration is one shape at its browser fragment rect (inset by half
      its border, where the outline runs).
    * Its own text is a text item of its own, one unwrapped line, starting
      within 1 px of the browser x of that text, and lying inside the shape:
      within it vertically and from its left edge, and past its right edge by
      no more than the width slack every left-aligned box carries (spec §3
      Wrapping).
    * The text after it is a text item starting within 1 px of the browser x
      of that text's first fragment, not where a run laid out without the
      element's padding and border would put it.
    * The shape precedes both items in the spTree, so it paints under them.
    """
    fragments = _painted_fragments(document, element)
    assert len(fragments) == 1, f"fixture drift: {element} has fragments {fragments}"
    fill = _hex(browser_style(document, element)["backgroundColor"])
    text_line = _single_line(document, element)
    assert text_line["text"] == element_text, (
        f"fixture drift: {element} reads {text_line['text']!r}, not {element_text!r}"
    )

    shape_index, shape = _one_filled(shapes, fill, f"the {element} decoration")
    _assert_at(shape, _inset(fragments[0], border_px / 2), f"the {element} decoration")

    own_index, own = _text_box(shapes, element_text)
    _assert_one_unwrapped_line(own, f"the {element_text!r} text")
    assert abs(own.x - text_line["x"]) <= PADDED_INLINE_X_TOLERANCE_PX, (
        f"the {element_text!r} box {_box(own)} starts at {own.x:.2f}; the browser draws it at "
        f"{text_line['x']:.2f}"
    )
    right_limit = shape.x + shape.w + _slack(text_line["w"])
    inside = (
        own.x >= shape.x - EMU_ROUNDING_PX
        and own.y >= shape.y - TEXT_LEFT_TOLERANCE_PX
        and own.y + own.h <= shape.y + shape.h + TEXT_LEFT_TOLERANCE_PX
        and own.x + own.w <= right_limit + EMU_ROUNDING_PX
    )
    assert inside, (
        f"the {element_text!r} box {_box(own)} is not inside its decoration {_box(shape)} plus "
        f"slack (right edge limit {right_limit:.2f})"
    )

    after_index, after = _text_box_containing(shapes, after_text)
    assert element_text not in after.text, (
        f"the text after {element} shares an item with its text: {after.text!r}"
    )
    assert abs(after.x - after_x) <= PADDED_INLINE_X_TOLERANCE_PX, (
        f"the text after {element} {_box(after)} starts at {after.x:.2f}; the browser draws "
        f"{after_text!r} at {after_x:.2f}"
    )
    _assert_back_to_front(
        shapes,
        [
            (f"the {element} decoration", shape_index),
            (f"the {element_text!r} text", own_index),
        ],
        "a decoration paints under its own text",
    )
    _assert_back_to_front(
        shapes,
        [(f"the {element} decoration", shape_index), ("the text after it", after_index)],
        "a decoration paints under the text of its sentence",
    )


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotPaddedInlines:
    """Coordinator ruling on Task 5 concern 1: a padded, bordered or margined inline
    element is a cut in its line, like an atomic inline.

    PowerPoint and Google Slides lay a paragraph's runs out continuously, with no
    room for an inline element's horizontal padding, border or margin, so text
    inside a chip would start at its left edge and the text after it would slide
    left into it. Cut there, each piece of the line is its own single-line text
    item at the browser's x.
    """

    def test_fixture_09_code_chip_text_sits_in_its_chip(self, corpus_pptx: bytes) -> None:
        """Fixture 09's ``.dk-chip`` "SKU-7" (padding 1px 6px) ends the first line of its
        list item; "now 31% of revenue" starts the second."""
        document = corpus_document("09")
        lines = browser_line_boxes(document, CHIP_ITEM, CHIP_ITEM_INDEX)
        assert len(lines) == 2 and lines[1]["text"] == "now 31% of revenue", (
            f"fixture drift: the chip's list item renders {lines}"
        )
        _assert_padded_inline_is_cut(
            _corpus_shapes(corpus_pptx, "09"),
            document,
            element=CHIP,
            element_text="SKU-7",
            border_px=0.0,
            after_text="now 31% of revenue",
            after_x=lines[1]["x"],
        )

    def test_text_after_a_key_keeps_its_x(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A key in a sentence, "Press <kbd>Esc</kbd> to continue".

        The key has a 1 px border and 5 px side padding.
        """
        document = _document(KEY_SENTENCE_BODY)
        after = _single_line(document, "#after-key")
        assert after["text"] == "to continue", f"fixture drift: the key's sentence reads {after}"
        shapes = slide_shapes(_export_one(KEY_SENTENCE_BODY, monkeypatch))

        _assert_padded_inline_is_cut(
            shapes,
            document,
            element="#esc",
            element_text="Esc",
            border_px=KEY_BORDER_PX,
            after_text="to continue",
            after_x=after["x"],
        )
        painted = Counter(
            character
            for entry in browser_line_boxes(document, "#press")
            for character in entry["text"]
            if not character.isspace()
        )
        emitted = Counter(
            character
            for shape in shapes
            if shape.kind == "text"
            for character in shape.text
            if not character.isspace()
        )
        assert emitted == painted, (
            f"the cut lost or doubled text: missing {dict(painted - emitted)}, extra "
            f"{dict(emitted - painted)}\n{_describe(shapes)}"
        )


def _item_holding_line(shapes: list[Shape], line: dict) -> Shape:
    """The one text item one of whose lines reads the browser line ``line``."""
    holding = [
        shape
        for shape in shapes
        if shape.kind == "text"
        and line["text"] in [_normalised(part) for part in shape.text.split("\n")]
    ]
    assert len(holding) == 1, (
        f"expected exactly one text item holding the line {line['text']!r}, got "
        f"{len(holding)}:\n{_describe(shapes)}"
    )
    return holding[0]


def _assert_each_line_at_its_edge(
    shapes: list[Shape], lines: list[dict], edge: str, tolerance: float, what: str
) -> None:
    """Every browser line starts where the browser drew it, on the side its text grows from.

    PowerPoint and Google Slides start every line of a text item at the item's
    start edge: its left for left-aligned text, its right for right-aligned
    (right-to-left) text. So the item holding each of the browser's ``lines``
    must have that edge (``'left'`` or ``'right'``) at the line's own browser
    edge within ``tolerance``: a line an inset pushes in from its neighbours
    cannot share their item.
    """
    for line in lines:
        item = _item_holding_line(shapes, line)
        emitted = item.x if edge == "left" else item.x + item.w
        browser = line["x"] if edge == "left" else line["x"] + line["w"]
        assert abs(emitted - browser) <= tolerance, (
            f"{what}: the line {line['text']!r} is drawn from {edge} edge {emitted:.2f} "
            f"(item {_box(item)}); the browser draws it from {browser:.2f}"
        )


def _text_centre(shape: Shape) -> float:
    """Where the renderers centre a one-line text item's text, from its box and alignment.

    A left-aligned box is its text plus the width slack on its right (spec §3
    Wrapping), so its text is ``(w - SLACK_PX) / (1 + SLACK_FRACTION)`` wide
    from its left edge; a centred box centres its text in it.
    """
    align = shape.paras[0].align if shape.paras else "left"
    text_width = (shape.w - SLACK_PX) / (1 + SLACK_FRACTION)
    if align == "center":
        return shape.x + shape.w / 2
    if align == "right":
        return shape.x + shape.w - text_width / 2
    return shape.x + text_width / 2


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotInsetsAtLineEnds:
    """Task 5 fix round 1: an inset with text on only one side of it on its line.

    An inline element's start inset (``box-decoration-break: slice``) sits on
    the line of its first fragment, before the text that follows it there, and
    its end inset on the line of its last fragment, after the text before it.
    A line whose text is all on one side of the inset still has the inset on
    it, so it is cut like any line with an inset: it is its own text item.
    """

    def test_a_dot_led_wrapped_paragraph_starts_its_first_line_at_its_x(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(a) A status dot leads a 320 px paragraph that wraps: only its first line starts
        right of the dot. Each line starts at its browser x within 0.5 px."""
        document = _document(DOT_LED_WRAPPED_BODY)
        lines = browser_line_boxes(document, "#status")
        assert len(lines) >= 2 and lines[0]["x"] > lines[1]["x"] + 10, (
            f"fixture drift: the dot does not push only the first line in: {lines}"
        )
        shapes = slide_shapes(_export_one(DOT_LED_WRAPPED_BODY, monkeypatch))

        _assert_each_line_at_its_edge(
            shapes, lines, "left", LINE_EDGE_TOLERANCE_PX, "the dot-led paragraph"
        )

    def test_a_padded_highlight_spanning_lines_keeps_each_line_x(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(b) A highlight with 8 px side padding covers a whole wrapped paragraph: its first
        line starts 8 px in, the others at the paragraph's left. Each line starts at its
        browser x within 0.5 px."""
        document = _document(HIGHLIGHT_SPANNING_BODY)
        lines = browser_line_boxes(document, "#spanning")
        fragments = _painted_fragments(document, "#spanning-mark")
        assert len(lines) >= 3 and len(fragments) == len(lines), (
            f"fixture drift: the highlight does not span the paragraph's lines: {lines}, "
            f"fragments {fragments}"
        )
        assert lines[0]["x"] > lines[1]["x"] + 4, (
            f"fixture drift: the highlight's start padding does not push its first line: {lines}"
        )
        shapes = slide_shapes(_export_one(HIGHLIGHT_SPANNING_BODY, monkeypatch))

        _assert_each_line_at_its_edge(
            shapes, lines, "left", LINE_EDGE_TOLERANCE_PX, "the highlighted paragraph"
        )

    @pytest.mark.parametrize("case", tuple(CENTRED_DOT_LINES))
    def test_a_centred_dot_led_line_keeps_its_centre(
        self, monkeypatch: pytest.MonkeyPatch, case: str
    ) -> None:
        """(c) A centred one-line paragraph with a dot: the browser centres the dot and the
        text together, so the text sits off the paragraph's centre, right of it when the
        dot leads the line (the inset after an opening edge) and left of it when the dot
        ends it (the inset before a closing edge). The text's centre is the browser's
        within 1 px."""
        body, side = CENTRED_DOT_LINES[case]
        document = _document(body)
        line = _single_line(document, "#centred")
        paragraph = browser_rect(document, "#centred")
        browser_centre = line["x"] + line["w"] / 2
        assert side * (browser_centre - (paragraph["x"] + paragraph["w"] / 2)) > 5, (
            f"fixture drift: the dot does not move the centred text: {line} in {paragraph}"
        )
        shapes = slide_shapes(_export_one(body, monkeypatch))

        _, item = _text_box(shapes, line["text"])
        _assert_one_unwrapped_line(item, "the centred line")
        assert abs(_text_centre(item) - browser_centre) <= LINE_CENTRE_TOLERANCE_PX, (
            f"the centred line's text is centred at {_text_centre(item):.2f} (item {_box(item)}, "
            f"aligned {item.paras[0].align}); the browser centres it at {browser_centre:.2f}"
        )

    def test_an_rtl_chip_spanning_lines_keeps_each_right_edge(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(d) A right-to-left sentence led by a padded chip that wraps: the chip's first
        line ends 6 px short of the paragraph's right edge, where its start padding is.
        Every piece of every line ends at its browser right edge within 1 px."""
        document = _document(RTL_CHIP_BODY)
        chip_lines = browser_line_boxes(document, "#rtl-chip")
        after_lines = browser_line_boxes(document, "#rtl-after")
        paragraph = browser_rect(document, "#rtl")
        paragraph_right = paragraph["x"] + paragraph["w"]
        assert len(chip_lines) >= 2, f"fixture drift: the chip does not wrap: {chip_lines}"
        assert chip_lines[0]["x"] + chip_lines[0]["w"] < paragraph_right - 4, (
            f"fixture drift: the chip's start padding does not hold its first line in from "
            f"{paragraph_right}: {chip_lines}"
        )
        shapes = slide_shapes(_export_one(RTL_CHIP_BODY, monkeypatch))

        _assert_each_line_at_its_edge(
            shapes, chip_lines + after_lines, "right", RTL_EDGE_TOLERANCE_PX, "the RTL sentence"
        )


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotInlineDecorationsInAHostileRealm:
    def test_element_rects_that_lie_are_read_correctly_or_announced(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Page script replaces ``Element.prototype.getClientRects`` with one reporting a
        trillion rects and holding none (``SLIDE_CSP`` allows inline script).

        The wrapping chip's decoration reads its fragments from that method, so:

        * the export returns within ``HOSTILE_EXPORT_TIMEOUT_SECONDS`` with no
          failures: the read is bounded;
        * the chip is either exported exactly as in the benign document (one
          shape per true fragment, read through the pristine realm) or the loss
          is announced with the ``[html2pptx] collection`` line, never dropped
          or approximated in silence;
        * the sentence's text, measured with ``Range`` rects the script leaves
          alone, is still exported with the browser's lines (its items, which
          the chip's padding cuts, read them).

        The script publishes on ``document.title`` that it replaced the method
        and that a reader of the realm sees the lie, so the poisoning is proven.
        """
        hostile_body = WRAPPING_CHIP_BODY.replace(
            "</div>", f"{HOSTILE_ELEMENT_RECTS_SCRIPT}</div>", 1
        )
        assert hostile_body != WRAPPING_CHIP_BODY, "the hostile script was not inserted"
        report = json.loads(browser_text(_document(hostile_body), "title"))
        assert report["redefineResult"] == "ok", f"the poisoning was refused: {report}"
        assert report["configurable"].get("Element.getClientRects") is True, (
            f"Element.getClientRects was not configurable: {report}"
        )
        assert report["bites"].get("getClientRects") is True, (
            f"the replacement did not take effect for a reader of the realm: {report}"
        )
        benign = _document(WRAPPING_CHIP_BODY)
        fragments = _painted_fragments(benign, "#chip")
        assert len(fragments) == 2, f"fixture drift: the chip has fragments {fragments}"
        lines = browser_line_boxes(benign, "#note")
        note = browser_rect(benign, "#note")
        fill = _hex(browser_style(benign, "#chip")["backgroundColor"])

        monkeypatch.setattr(
            pptx_from_html_huashu, "SIDECAR_TIMEOUT_SECONDS", HOSTILE_EXPORT_TIMEOUT_SECONDS
        )
        capsys.readouterr()
        pptx, failures = export_slides(
            [hostile_body], css=DECK_CSS, engine="snapshot", monkeypatch=monkeypatch
        )
        assert pptx and failures == [], f"the export did not complete: {failures}"
        stderr = capsys.readouterr().err
        shapes = slide_shapes(pptx)

        chips = sorted((shape for _, shape in _filled(shapes, fill)), key=lambda s: (s.y, s.x))
        read_correctly = len(chips) == len(fragments) and all(
            _matches(chip, fragment, DECORATION_RECT_TOLERANCE_PX)
            for chip, fragment in zip(chips, fragments)
        )
        announced = COLLECTION_LOSS_LINE in stderr
        assert read_correctly or announced, (
            f"the lying getClientRects cost the chip silently: emitted {[_box(c) for c in chips]} "
            f"for the true fragments {fragments}, and no {COLLECTION_LOSS_LINE!r} line on "
            f"stderr:\n{stderr}"
        )
        _assert_reads_as_lines(shapes, note, lines, "the chip's sentence")
