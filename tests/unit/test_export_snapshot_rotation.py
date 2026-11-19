"""Snapshot engine: rotated text, vertical writing modes and ``text-overflow: ellipsis``.

Text under a rotation is one text item, the way PowerPoint and Google Slides
hold it: the element's UNROTATED box, turned by its angle, holding its lines.
Range rects cannot give those lines, because under a rotation each character's
rect is the axis-aligned bounds of the turned glyph, so line clustering splits
a label into one line per word. So the nearest rotated element's text is one
item:

* its box is the element's untransformed layout box, ``offsetWidth`` x
  ``offsetHeight`` (times any scale), centred where its bounding rect is
  centred (a rotated rectangle's bounds share its centre);
* its ``rot`` is the cumulative angle, normalised to 0-359 and written in
  60000ths of a degree: ``rotate(-90deg)`` is 270 degrees, 16200000;
* its lines are the element's own, in DOM order, split by ``<br>`` and block
  children. A one-line label is one paragraph with ``wrap="none"``;
* its runs keep the typography of any other text (Task 3): text-transform,
  letter spacing as ``spc`` in points, the colour (R11b);
* a rotated box that paints a background is a shape AND a text item, both
  with the same ``rot`` about the same centre, the shape first (R11d).

Vertical writing modes (R11a) rotate too. Under ``writing-mode: vertical-rl``
or ``vertical-lr`` the browser sets Latin glyphs sideways, turned 90 degrees
clockwise, so the text is one item turned 90 degrees on top of the element's
own angle; ``sideways-lr`` turns them the other way, 270 degrees. Its unrotated
box is the element's inline length by its block length: w = ``offsetHeight``,
h = ``offsetWidth``. A box turned clockwise by an angle stacks its paragraphs
along its own downward axis, which on the slide points along (-sin, cos) of
the angle: right to left at 90 degrees. ``vertical-lr`` stacks its lines left to
right, so with more than one line its paragraph order is reversed.

``text-overflow: ellipsis`` (R11e) exports what the browser shows: the visible
characters, then "…". The visible characters come from the screen
(``browser_ellipsis``), not from Range rects, which report every character
where it was laid out, hidden or not: three screenshots of the element,
as it is, with ``text-overflow: clip`` and with its glyphs transparent, are
compared column by column, and the characters left of the first column where
the first two differ are the visible ones. Chrome ends the "…" at the line's
content-box edge, not at the padding box its overflow clips to. The "…" takes
the style of the line's containing BLOCK, which is what Chrome paints even
when the cut falls inside a differently styled inline; the screen's own "…"
colour (``BrowserEllipsis.ellipsis_ink_colour``) proves it for each case. So the
exported glyphs end where Chrome's do, inside the clip; the item's box keeps
its usual slack, which may reach past the clip (R11e″). This holds for text
items and for a native table's cut cells.

Rotated text in a HOSTILE realm (``hostile_text_nodes``, which replaces every
node-level read the text walk could make) still exports, and exports as its
benign twin does.

Every assertion reads the emitted slide XML (``slide_shapes``) and holds it
against the browser's own layout of the very same document:
``browser_each_layout_box`` reads an element's bounds, offset size and writing
mode from one page load. Corpus slide 13 (the "Governed data" margin label) is
loaded by prefix; the other cases are small inline documents, among them a
2x2 prioritisation matrix written after the design system's (``.mtx``, whose
``.axis-y`` label is turned by ``rotate(-90deg) translateX(50%)`` about its
left centre).

Gating matches the sibling export suites: needs node, the extracted sidecar
``node_modules`` and a local Chrome/Chromium (skipped otherwise).
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator

import pytest

from src.services import pptx_from_html_huashu
from tests.fixtures.export_snapshot_support import (
    ANGLE_UNITS_PER_DEGREE,
    DECK_CSS,
    BrowserEllipsis,
    Run,
    Shape,
    browser_each_layout_box,
    browser_each_rect,
    browser_ellipsis,
    browser_probes,
    browser_style,
    browser_tables,
    browser_text,
    corpus_document,
    export_corpus,
    export_documents,
    export_slides,
    requires_huashu_sidecar,
    slide_document,
    slide_shapes,
    table_extent,
    table_frames,
)
from tests.unit.test_export_collection_iteration_hostile_realm import (
    HOSTILE_EXPORT_TIMEOUT_SECONDS,
)
from tests.unit.test_export_slide_root_background import FIXTURE_DIR
from tests.unit.test_export_svg_raster import structural_manifest

ENGINE = "snapshot"

# The brief: the unrotated box and its centre agree with the browser within 1 px
# (offsetWidth and offsetHeight are whole px; the bounds are not).
GEOMETRY_TOLERANCE_PX = 1.0
# rot is written in 60000ths of a degree, so a right angle is exact and any
# other angle is within a 60000th.
ANGLE_TOLERANCE_DEGREES = 0.01
# The middle of a "…" dot is fully covered, so the screen shows its colour
# exactly; a few units allow for colour management and nothing more.
SCREEN_CHANNEL_TOLERANCE = 8
PT_PER_PX = 0.75
# spc is written in hundredths of a point: one hundredth either way.
SPC_TOLERANCE_PT = 0.01
# task-4-addendum A1: a run whose width at the browser's automatic optical size
# and at the static opsz-14 cut differ by more than 0.5% carries an optical-size
# delta on top of its CSS tracking; within it, spc is the CSS tracking alone.
OPTICAL_SIZE_THRESHOLD = 0.005
EXPORT_CUT_OPTICAL_SIZE = 14
ELLIPSIS = "…"

# Corpus slide 13: the margin label, turned by rotate(-90deg) about its right top.
GOVERNED_LABEL = '.slide > div[style*="rotate(-90deg)"]'
GOVERNED_TEXT = "GOVERNED DATA"
GOVERNED_ROT_UNITS = 16200000  # 270 degrees in PowerPoint units

ROTATION_CSS = """
.tag { position: absolute; left: 560px; top: 320px; transform: rotate(12deg);
       font-size: 18px; font-weight: 600; color: #1B3139; white-space: nowrap; }
.mtx { position: relative; width: 640px; aspect-ratio: 1.7; margin: 24px 0 0 40px; }
.mtx .quad { position: absolute; width: 50%; height: 50%; box-sizing: border-box;
             border: 1px solid #DCE0E2; padding: 18px 20px; display: flex;
             flex-direction: column; gap: 6px; }
.mtx .q1 { left: 50%; top: 0; background: #F9F7F4; }
.mtx .q2 { left: 0; top: 0; background: #FFFFFF; }
.mtx .q3 { left: 0; top: 50%; background: #FFFFFF; }
.mtx .q4 { left: 50%; top: 50%; background: #FF5F46; }
.mtx .q4 * { color: #FFFFFF !important; }
.mtx .qh { font-size: 16px; font-weight: 700; }
.mtx .qd { font-size: 13px; line-height: 1.4; color: var(--ink-2); }
.mtx .axis-y { position: absolute; top: 50%; left: -30px;
               transform: rotate(-90deg) translateX(50%); transform-origin: left center;
               font-size: 13px; font-weight: 700; letter-spacing: .08em;
               text-transform: uppercase; color: var(--ink-2); white-space: nowrap; }
.axis-x { width: 640px; margin: 14px 0 0 40px; text-align: center; font-size: 13px;
          font-weight: 700; letter-spacing: .08em; text-transform: uppercase;
          color: var(--ink-2); }
.vertical { position: absolute; left: 160px; top: 180px; font-size: 16px; font-weight: 600;
            color: var(--ink-2); white-space: nowrap; }
.pill { position: absolute; left: 700px; top: 300px; transform: rotate(-8deg);
        display: inline-block; padding: 4px 12px; border-radius: 999px; background: #FF5F46;
        color: #FFFFFF; font-size: 14px; font-weight: 700; letter-spacing: .06em; }
.br-label { position: absolute; left: 900px; top: 300px; transform: rotate(-90deg);
            font-size: 16px; color: var(--ink); }
.card { position: absolute; left: 88px; top: 120px; width: 360px; box-sizing: border-box;
        padding: 24px; background: #FFFFFF; border-radius: 12px; }
.card .ct { font-size: 24px; font-weight: 600; white-space: nowrap; overflow: hidden; }
.card .ct.ellipsis { text-overflow: ellipsis; }
.card .lead { color: #FF5F46; }
.card .ct.mixed { color: #1F4FD8; font-weight: 700; font-size: 28px; }
.card .mixed .tail { color: #D0302A; font-weight: 400; }
.card .cb { font-size: 15px; color: var(--ink-2); margin-top: 8px; }
.grid { position: absolute; left: 88px; top: 120px; width: 640px; table-layout: fixed;
        border-collapse: collapse; font-size: 18px; }
.grid td { padding: 8px 12px; border-bottom: 1px solid #DCE0E2; }
.grid td.cut { overflow: hidden; white-space: nowrap; }
.grid td.cut.ellipsis { text-overflow: ellipsis; }
"""

CELL_WORDS = (
    "Unity",
    "Catalog",
    "governs",
    "every",
    "table,",
    "view",
    "and",
    "model",
    "across",
    "clouds",
)


def _card(title: str, title_class: str) -> str:
    return (
        '<div class="slide"><div class="card">'
        f'<div id="title" class="{title_class}">{title}</div>'
        '<div class="cb">Two waves, finishing in the third quarter.</div>'
        "</div></div>"
    )


def _grid(cell: str, cell_class: str) -> str:
    return (
        '<div class="slide"><table id="grid" class="grid">'
        '<colgroup><col style="width: 200px"><col style="width: 440px"></colgroup><tbody>'
        f'<tr><td>Programme</td><td id="cell" class="{cell_class}">{cell}</td></tr>'
        "<tr><td>People</td><td>Hiring plan on track</td></tr>"
        "</tbody></table></div>"
    )


# Each inline slide, by name, in deck order.
SLIDES: dict[str, str] = {
    "tag": '<div class="slide"><div id="tag" class="tag">Beta preview</div></div>',
    "axis-2x2": (
        '<div class="slide">'
        '<div class="mtx">'
        '<div class="quad q2"><div class="qh">Quick wins</div>'
        '<div class="qd">Low effort, lower value.</div></div>'
        '<div class="quad q1"><div class="qh">Do first</div>'
        '<div class="qd">High value, low effort.</div></div>'
        '<div class="quad q3"><div class="qh">Deprioritize</div>'
        '<div class="qd">Low value, high effort.</div></div>'
        '<div class="quad q4"><div class="qh">Strategic bets</div>'
        '<div class="qd">High value, higher effort.</div></div>'
        '<div id="axis-y" class="axis-y">Effort &rarr;</div>'
        "</div>"
        '<div id="axis-x" class="axis-x">Business value &rarr;</div>'
        "</div>"
    ),
    "vertical-rl": (
        '<div class="slide"><div id="label" class="vertical" style="writing-mode: vertical-rl;">'
        "Revenue ($M)</div></div>"
    ),
    "vertical-rl-turned": (
        '<div class="slide"><div id="label" class="vertical" '
        'style="writing-mode: vertical-rl; transform: rotate(180deg);">Margin (%)</div></div>'
    ),
    "sideways-lr": (
        '<div class="slide"><div id="label" class="vertical" style="writing-mode: sideways-lr;">'
        "Units shipped</div></div>"
    ),
    "vertical-lr": (
        '<div class="slide"><div id="label" class="vertical" style="writing-mode: vertical-lr;">'
        "<span>First column</span><br><span>Second column</span></div></div>"
    ),
    "br-lines": (
        '<div class="slide"><div id="lines" class="br-label">Line one<br>Line two</div></div>'
    ),
    "pill": '<div class="slide"><div id="pill" class="pill">NEW</div></div>',
    "ellipsis-title": _card(
        '<span class="lead">Lakehouse</span> migration for regional distribution centres',
        "ct ellipsis",
    ),
    "ellipsis-mixed": _card(
        'Pipeline <span class="tail">throughput for every regional centre</span>',
        "ct ellipsis mixed",
    ),
    "ellipsis-cell": _grid(" ".join(CELL_WORDS), "cut ellipsis"),
}

# R11a: each single-line vertical label, its text and the angle it is turned by.
VERTICAL_LABELS = {
    "vertical-rl": ("Revenue ($M)", "vertical-rl", 90.0),
    "vertical-rl-turned": ("Margin (%)", "vertical-rl", 270.0),
    "sideways-lr": ("Units shipped", "sideways-lr", 270.0),
}
VERTICAL_LR_LINES = ("First column", "Second column")

# The hostile-realm case: a rotated label added to the hostile text-node fixture
# and, identically, to its benign twin, inside the slide root.
HOSTILE_FIXTURE = "hostile_text_nodes"
BENIGN_TWIN = "collection_passes"
HOSTILE_LABEL_TEXT = "Rotated label"
HOSTILE_LABEL = (
    '<div id="rotated-label" style="position: absolute; left: 1060px; top: 360px; '
    f'transform: rotate(-90deg); font-size: 20px; white-space: nowrap;">{HOSTILE_LABEL_TEXT}</div>'
)
SLIDE_ROOT_END = "    </div>\n  </body>"


@pytest.fixture(scope="module")
def rotation_pptx() -> Iterator[bytes]:
    """The inline slides in ``SLIDES``, exported once through the snapshot engine."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        pptx, failures = export_slides(
            list(SLIDES.values()),
            css=DECK_CSS + ROTATION_CSS,
            engine=ENGINE,
            monkeypatch=monkeypatch,
        )
    assert failures == [], f"the export rejected a slide: {failures}"
    yield pptx


@pytest.fixture(scope="module")
def corpus_pptx() -> Iterator[bytes]:
    """Corpus slide 13, exported once through the snapshot engine."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        pptx, failures = export_corpus(["13"], monkeypatch=monkeypatch, engine=ENGINE)
    assert failures == [], f"the export rejected corpus slide 13: {failures}"
    yield pptx


def _slide_index(name: str) -> int:
    return list(SLIDES).index(name)


def _document(name: str) -> str:
    """The document ``rotation_pptx`` exported as slide ``name``."""
    return slide_document(
        SLIDES[name], css=DECK_CSS + ROTATION_CSS, slide_id=f"snapshot-{_slide_index(name) + 1}"
    )


def _shapes(pptx: bytes, name: str) -> list[Shape]:
    return slide_shapes(pptx, _slide_index(name))


def _describe(shapes: list[Shape]) -> str:
    return "\n".join(
        f"  [{position}] {shape.kind} {shape.geometry} fill={shape.fill} rot={shape.rotation} "
        f"wrap={shape.wrap} box=({shape.x:.2f}, {shape.y:.2f}, {shape.w:.2f}, {shape.h:.2f}) "
        f"text={shape.text[:60]!r}"
        for position, shape in enumerate(shapes)
    )


def _normalised(text: str) -> str:
    return " ".join(text.split())


def _hex(css_colour: str) -> str:
    """'RRGGBB' of a computed ``rgb(r, g, b)``."""
    channels = re.fullmatch(r"rgba?\((\d+), (\d+), (\d+)(?:, [\d.]+)?\)", css_colour)
    assert channels, f"not a computed rgb() colour: {css_colour!r}"
    return "".join(f"{int(channel):02X}" for channel in channels.groups())


def _px(css_length: str) -> float:
    assert css_length.endswith("px"), f"not a computed px length: {css_length!r}"
    return float(css_length.removesuffix("px"))


def _layout(document: str, selector: str) -> dict:
    """The one match of ``selector``'s layout box (``browser_each_layout_box``)."""
    boxes = browser_each_layout_box(document, selector)
    assert len(boxes) == 1, f"fixture drift: {selector} matched {len(boxes)} elements"
    return boxes[0]


def _text_item(shapes: list[Shape], contains: str, what: str) -> tuple[int, Shape]:
    """(spTree index, shape) of the ONE text item whose text contains ``contains``."""
    matches = [
        (position, shape)
        for position, shape in enumerate(shapes)
        if shape.kind == "text" and contains in shape.text
    ]
    assert len(matches) == 1, (
        f"{what}: expected one text item holding {contains!r}, got {len(matches)}:\n"
        f"{_describe(shapes)}"
    )
    return matches[0]


def _lines(shape: Shape) -> list[str]:
    """The item's lines as written: every paragraph end and ``<a:br/>`` ends one."""
    return shape.text.split("\n")


def _angle_off(emitted: float, expected: float) -> float:
    """How far apart two angles are, in degrees, across the 0/360 seam."""
    return abs((emitted - expected + 180) % 360 - 180)


def _centre(box: dict | Shape) -> tuple[float, float]:
    if isinstance(box, Shape):
        return box.x + box.w / 2, box.y + box.h / 2
    return box["x"] + box["w"] / 2, box["y"] + box["h"] / 2


def _assert_angle(item: Shape, angle: float, what: str) -> None:
    assert _angle_off(item.rotation, angle) <= ANGLE_TOLERANCE_DEGREES, (
        f"{what}: rot is {item.rotation:g} degrees "
        f"({round(item.rotation * ANGLE_UNITS_PER_DEGREE)} in PowerPoint units), expected "
        f"{angle:g} ({round(angle * ANGLE_UNITS_PER_DEGREE)})"
    )


def _assert_centred(item: Shape, layout: dict, what: str) -> None:
    emitted = _centre(item)
    expected = _centre(layout)
    off = (round(emitted[0] - expected[0], 3), round(emitted[1] - expected[1], 3))
    assert all(abs(delta) <= GEOMETRY_TOLERANCE_PX for delta in off), (
        f"{what}: its box is centred at {emitted}, the browser bounds at {expected} "
        f"(off by {off}, tolerance {GEOMETRY_TOLERANCE_PX} px)"
    )


def _assert_turned_box(
    item: Shape, layout: dict, angle: float, what: str, *, vertical: bool = False
) -> None:
    """``item`` is its element's unrotated box, turned by ``angle`` about the bounds' centre.

    The unrotated box is ``offsetWidth`` x ``offsetHeight``; under a vertical
    writing mode it is the inline length by the block length, ``offsetHeight``
    x ``offsetWidth`` (R11a).
    """
    _assert_angle(item, angle, what)
    width, height = (
        (layout["offset_h"], layout["offset_w"])
        if vertical
        else (layout["offset_w"], layout["offset_h"])
    )
    off = (round(item.w - width, 3), round(item.h - height, 3))
    assert all(abs(delta) <= GEOMETRY_TOLERANCE_PX for delta in off), (
        f"{what}: its unrotated box is {item.w:.2f} x {item.h:.2f}, expected {width:g} x "
        f"{height:g} (the element's {'inline by block length' if vertical else 'offset size'}; "
        f"off by {off}, tolerance {GEOMETRY_TOLERANCE_PX} px). The bounds are "
        f"{layout['w']:.2f} x {layout['h']:.2f}."
    )
    _assert_centred(item, layout, what)


def _assert_one_line(item: Shape, expected: str, what: str) -> None:
    assert _lines(item) == [expected], (
        f"{what}: the item's lines are {_lines(item)}, expected the one line {[expected]}"
    )
    assert len(item.paras) == 1, f"{what}: {len(item.paras)} paragraphs, expected one"
    assert item.wrap == "none", f"{what}: bodyPr wrap is {item.wrap!r}, expected 'none'"


def _stacking_order(rects: list[dict], angle: float) -> list[int]:
    """The order a text box turned clockwise by ``angle`` stacks lines in, from where they are.

    The box stacks its paragraphs along its own downward axis, which on the
    slide (y down) points along (-sin angle, cos angle). So the paragraph order
    is the browser's lines sorted by where their centres project on that axis.
    """
    radians = math.radians(angle)
    axis = (-math.sin(radians), math.cos(radians))
    return sorted(
        range(len(rects)),
        key=lambda index: _centre(rects[index])[0] * axis[0] + _centre(rects[index])[1] * axis[1],
    )


def _run_style(run: Run) -> tuple:
    return run.typeface, run.size_pt, run.bold, run.italic, run.color


def _describe_run(run: Run) -> str:
    return (
        f"{run.text!r} typeface={run.typeface} size={run.size_pt} bold={run.bold} "
        f"italic={run.italic} color={run.color} spc={run.spc_pt}"
    )


def _cell_texts(shapes: list[Shape]) -> list[str]:
    """The text of every ``a:tc`` of every native table on the slide."""
    return [
        _normalised(cell.text)
        for _, frame in table_frames(shapes)
        for row in frame.table.rows
        for cell in row
        if _normalised(cell.text)
    ]


def _cut_text(shapes: list[Shape], first_word: str, what: str) -> tuple[str, Shape | None]:
    """The text a cut line exported as, and its overlay item (None when an ``a:tc`` holds it).

    The line is written exactly once: as one text item, or as one native
    cell's own text.
    """
    items = [shape for shape in shapes if shape.kind == "text" and first_word in shape.text]
    cells = [text for text in _cell_texts(shapes) if first_word in text]
    assert len(items) + len(cells) == 1, (
        f"{what}: the line starting {first_word!r} must be written exactly once; it is in "
        f"{len(items)} text item(s) and {len(cells)} table cell(s) {cells}:\n{_describe(shapes)}"
    )
    if items:
        return items[0].text, items[0]
    return cells[0], None


def _ellipsis_runs(item: Shape, what: str) -> tuple[list[Run], Run]:
    """The item's runs, and the ONE run holding the "…"."""
    runs = [run for paragraph in item.paras for run in paragraph.runs if run.text]
    holding = [run for run in runs if ELLIPSIS in run.text]
    assert len(holding) == 1, (
        f"{what}: {len(holding)} runs hold the ellipsis: {[_describe_run(run) for run in runs]}"
    )
    return runs, holding[0]


def _run_holding(runs: list[Run], text: str, what: str) -> Run:
    """The first run whose text contains ``text``."""
    for run in runs:
        if text in run.text:
            return run
    raise AssertionError(f"{what}: no run holds {text!r}: {[run.text for run in runs]}")


def _rgb(hex_colour: str) -> tuple[int, int, int]:
    return int(hex_colour[0:2], 16), int(hex_colour[2:4], 16), int(hex_colour[4:6], 16)


def _shows_colour(colour: tuple[int, int, int] | None, hex_colour: str) -> bool:
    """Whether a screen colour is ``hex_colour``, within ``SCREEN_CHANNEL_TOLERANCE``."""
    return colour is not None and all(
        abs(shown - expected) <= SCREEN_CHANNEL_TOLERANCE
        for shown, expected in zip(colour, _rgb(hex_colour))
    )


def _assert_block_style_ellipsis(
    item: Shape, cut: BrowserEllipsis, block_colour: str, block_word: str, what: str
) -> Run:
    """The "…" run is in the style of the line's block, as the screen paints it (R11e″).

    The screen's "…" is guarded to be ``block_colour``. The run holding the
    "…" then has the style (typeface, size, weight, italic, colour) of the run
    holding ``block_word``, a word set in the block's own style, and the
    block's colour. Returns the "…" run.
    """
    assert _shows_colour(cut.ellipsis_ink_colour, block_colour), (
        f"fixture drift: the screen paints {what}'s ellipsis {cut.ellipsis_ink_colour}, not the "
        f"block's {block_colour}"
    )
    runs, ellipsis_run = _ellipsis_runs(item, what)
    block_run = _run_holding(runs, block_word, what)
    assert _run_style(ellipsis_run) == _run_style(block_run) and (
        ellipsis_run.color == block_colour
    ), (
        f"{what}: the ellipsis run {_describe_run(ellipsis_run)} must take the block's style, "
        f"that of {_describe_run(block_run)}, in the {block_colour} the screen paints it in"
    )
    return ellipsis_run


def _assert_ellipsis_cut(
    document: str, selector: str, what: str
) -> tuple[BrowserEllipsis, dict[str, str]]:
    """The browser's ellipsis cut of ``selector``, guarded: it cuts its one line mid-word."""
    style = browser_style(document, selector)
    cut = browser_ellipsis(document, selector)
    assert cut.style["textOverflow"] == "ellipsis" and cut.style["overflowX"] == "hidden", (
        f"fixture drift: {what} computes {cut.style}"
    )
    assert cut.cut is not None and cut.ink_end is not None, (
        f"fixture drift: the screen shows no ellipsis cut on {what}: {cut}"
    )
    assert cut.visible and len(cut.visible) < len(cut.text) and cut.text.startswith(cut.visible), (
        f"fixture drift: {what} shows {cut.visible!r} of {cut.text!r}; it must cut its line"
    )
    assert cut.visible[-1] != " " and cut.text[len(cut.visible)] != " ", (
        f"fixture drift: {what}'s cut falls at a space ({cut.visible!r} | "
        f"{cut.text[len(cut.visible) :]!r}); the cases are written to cut mid-word"
    )
    assert cut.ellipsis_ink_start is not None and cut.ink_end <= cut.clip["x"] + cut.clip["w"], (
        f"fixture drift: {what}'s ellipsis ink {cut.ellipsis_ink_start}..{cut.ink_end} is not "
        f"inside its clip {cut.clip}"
    )
    return cut, style


@pytest.mark.slow
@requires_huashu_sidecar
class TestRotatedText:
    def test_fixture_13_label_is_one_turned_item_on_its_unrotated_box(
        self, corpus_pptx: bytes
    ) -> None:
        """Fixture 13 (RC12): the ``rotate(-90deg)`` label "GOVERNED DATA" is ONE text item.

        * ``rot`` is 270 degrees, 16200000 in PowerPoint units;
        * it is a single line in one paragraph, ``wrap="none"``;
        * its unrotated box ``w`` x ``h`` is the label's ``offsetWidth`` x
          ``offsetHeight`` within 1 px, and its centre is the browser bounding
          box's centre within 1 px.

        Laid out from its turned glyphs' axis-aligned rects instead, the label
        is an unturned 21 x 126 box reading "GOVERNED" over "DATA".
        """
        document = corpus_document("13")
        layout = _layout(document, GOVERNED_LABEL)
        assert layout["transform"] == "matrix(0, -1, 1, 0, 0, 0)", (
            f"fixture drift: the label computes transform {layout['transform']}"
        )
        shapes = slide_shapes(corpus_pptx, 0)
        _, label = _text_item(shapes, "GOVERNED", "the fixture 13 label")

        assert round(label.rotation * ANGLE_UNITS_PER_DEGREE) == GOVERNED_ROT_UNITS, (
            f"the label's rot is {round(label.rotation * ANGLE_UNITS_PER_DEGREE)} "
            f"({label.rotation:g} degrees), expected {GOVERNED_ROT_UNITS} (270 degrees)"
        )
        _assert_one_line(label, GOVERNED_TEXT, "the fixture 13 label")
        _assert_turned_box(label, layout, 270.0, "the fixture 13 label")

    def test_fixture_13_label_keeps_its_typography_under_rotation(self, corpus_pptx: bytes) -> None:
        """R11b, a guard: the turned label keeps Task 3's run rules.

        Its runs read "GOVERNED DATA", upper-cased by ``text-transform`` as the
        browser renders it (``innerText``); each run's letter spacing is the
        computed 0.2em (2.4 px) as ``spc`` in points, 1.8 pt, with no
        optical-size delta (the two optical cuts agree within 0.5%, guarded);
        each is the computed ``--ink-2`` colour, 9 pt DM Sans, not bold. A
        rotated text path that builds its runs anew must not lose any of it.
        """
        document = corpus_document("13")
        style = browser_style(document, GOVERNED_LABEL)
        rendered = browser_text(document, GOVERNED_LABEL)
        assert _normalised(rendered) == GOVERNED_TEXT and style["textTransform"] == "uppercase", (
            f"fixture drift: the label renders {rendered!r} under text-transform "
            f"{style['textTransform']}"
        )
        tracking_px = _px(style["letterSpacing"])
        size_px = _px(style["fontSize"])
        assert math.isclose(tracking_px, 0.2 * size_px, abs_tol=0.005), (
            f"fixture drift: the label's letter-spacing is {style['letterSpacing']} at {size_px} px"
        )
        face = (
            f"font: {style['fontStyle']} {style['fontWeight']} {style['fontSize']} "
            f"{style['fontFamily']}; letter-spacing: {style['letterSpacing']}"
        )
        browser_cut, export_cut = (
            size["w"]
            for size in browser_probes(
                document,
                [
                    (GOVERNED_TEXT, face),
                    (
                        GOVERNED_TEXT,
                        f"{face}; font-variation-settings: 'opsz' {EXPORT_CUT_OPTICAL_SIZE}",
                    ),
                ],
            )
        )
        assert abs(export_cut - browser_cut) / browser_cut <= OPTICAL_SIZE_THRESHOLD, (
            f"fixture drift: the label's optical cuts differ by more than "
            f"{OPTICAL_SIZE_THRESHOLD:.1%} ({browser_cut} vs {export_cut} px), so an "
            "optical-size delta would apply"
        )
        family = style["fontFamily"].split(",")[0].strip().strip("\"'")
        expected_colour = _hex(style["color"])

        _, label = _text_item(slide_shapes(corpus_pptx, 0), "GOVERNED", "the fixture 13 label")
        runs = [run for paragraph in label.paras for run in paragraph.runs if run.text.strip()]
        assert _normalised(" ".join(run.text for run in runs)) == GOVERNED_TEXT, (
            f"the label's runs read {[run.text for run in runs]}, expected {GOVERNED_TEXT!r}"
        )
        expected_spc = tracking_px * PT_PER_PX
        wrong = [
            _describe_run(run)
            for run in runs
            if not run.text.isupper()
            or abs(run.spc_pt - expected_spc) > SPC_TOLERANCE_PT
            or run.color != expected_colour
            or run.typeface != family
            or not math.isclose(run.size_pt or 0.0, size_px * PT_PER_PX, abs_tol=0.01)
            or run.bold
        ]
        assert not wrong, (
            f"every run must be upper case, spc {expected_spc:.2f} pt, colour {expected_colour}, "
            f"{family} at {size_px * PT_PER_PX:g} pt and not bold; these are not:\n  "
            + "\n  ".join(wrong)
        )

    def test_an_arbitrary_angle_is_the_items_rot(self, rotation_pptx: bytes) -> None:
        """A ``rotate(12deg)`` tag is one text item with ``rot`` 12 degrees.

        Its unrotated box is the tag's ``offsetWidth`` x ``offsetHeight`` and
        its centre the bounds' centre, each within 1 px; it is one line.
        """
        document = _document("tag")
        layout = _layout(document, "#tag")
        shapes = _shapes(rotation_pptx, "tag")
        _, tag = _text_item(shapes, "Beta", "the 12 degree tag")

        _assert_turned_box(tag, layout, 12.0, "the 12 degree tag")
        _assert_one_line(tag, "Beta preview", "the 12 degree tag")

    def test_a_2x2_axis_label_is_one_line(self, rotation_pptx: bytes) -> None:
        """The design system's 2x2 matrix: its y axis label "EFFORT →" is one line.

        ``.axis-y`` is turned by ``rotate(-90deg) translateX(50%)`` about its
        left centre, so it is one text item reading "EFFORT →" (as the browser
        renders it, upper-cased) in one paragraph, ``rot`` 270 degrees, on its
        unrotated box centred on its bounds. The x axis label under the matrix
        stays one unturned line. Clustered from its turned glyphs' rects, the y
        label would be "EFFORT" over "→".
        """
        document = _document("axis-2x2")
        layout = _layout(document, "#axis-y")
        rendered = _normalised(browser_text(document, "#axis-y"))
        assert rendered == "EFFORT →", f"fixture drift: the y axis label renders {rendered!r}"
        shapes = _shapes(rotation_pptx, "axis-2x2")
        _, label = _text_item(shapes, "EFFORT", "the 2x2 y axis label")

        _assert_one_line(label, rendered, "the 2x2 y axis label")
        _assert_turned_box(label, layout, 270.0, "the 2x2 y axis label")
        _, axis_x = _text_item(shapes, "BUSINESS", "the 2x2 x axis label")
        _assert_one_line(axis_x, "BUSINESS VALUE →", "the 2x2 x axis label")
        _assert_angle(axis_x, 0.0, "the 2x2 x axis label")

    def test_br_lines_of_a_rotated_element_are_its_lines_in_dom_order(
        self, rotation_pptx: bytes
    ) -> None:
        """R11c: a ``rotate(-90deg)`` "Line one<br>Line two" is one item with two lines.

        The lines are "Line one" then "Line two", in DOM order (a turned box
        stacks them left to right on the slide, as the browser does); its
        unrotated height holds both lines, ``offsetHeight`` within 1 px, and its
        ``rot`` is 270 degrees. A line ends at a paragraph end or an
        ``<a:br/>``: both render as the browser's line break. Clustered from the
        turned glyphs' rects, each word would be a line of its own.
        """
        document = _document("br-lines")
        layout = _layout(document, "#lines")
        shapes = _shapes(rotation_pptx, "br-lines")
        _, label = _text_item(shapes, "one", "the rotated two-line label")

        assert [_normalised(line) for line in _lines(label)] == ["Line one", "Line two"], (
            f"the rotated label's lines are {_lines(label)}, expected ['Line one', 'Line two']"
        )
        _assert_turned_box(label, layout, 270.0, "the rotated two-line label")


@pytest.mark.slow
@requires_huashu_sidecar
class TestVerticalWritingModes:
    @pytest.mark.parametrize("name", tuple(VERTICAL_LABELS))
    def test_a_vertical_label_is_one_item_turned_by_its_writing_mode(
        self, rotation_pptx: bytes, name: str
    ) -> None:
        """R11a: a vertical label is one text item, turned by its writing mode.

        * ``vertical-rl`` "Revenue ($M)": ``rot`` 90 degrees;
        * ``vertical-rl`` under ``rotate(180deg)`` "Margin (%)": 90 on top of
          180, ``rot`` 270 degrees;
        * ``sideways-lr`` "Units shipped": its glyphs turn the other way, ``rot``
          270 degrees.

        Its unrotated box is the label's inline length by its block length,
        w = ``offsetHeight`` (the browser rect's height) and h = ``offsetWidth``
        (its width), within 1 px, centred on the bounds within 1 px; it is one
        line. Clustered from the sideways glyphs' rects, each word would be a
        line of an unturned box.
        """
        text, writing_mode, angle = VERTICAL_LABELS[name]
        document = _document(name)
        layout = _layout(document, "#label")
        assert layout["writing_mode"] == writing_mode, (
            f"environment: the browser computes writing-mode {layout['writing_mode']!r} for "
            f"{writing_mode} (does this Chrome support it?)"
        )
        shapes = _shapes(rotation_pptx, name)
        _, label = _text_item(shapes, text.split()[0], f"the {name} label")

        _assert_turned_box(label, layout, angle, f"the {name} label", vertical=True)
        _assert_one_line(label, text, f"the {name} label")

    def test_vertical_lr_stacks_its_lines_left_to_right(self, rotation_pptx: bytes) -> None:
        """R11a: under ``vertical-lr`` the paragraph order is reversed.

        The browser stacks "First column" LEFT of "Second column" (read from
        each line's rect). A box turned 90 degrees stacks its paragraphs right
        to left, so the item, ``rot`` 90 degrees on its inline-by-block box,
        reads "Second column" then "First column": the browser's lines in the
        order the turned box stacks them, which is DOM order reversed.
        """
        document = _document("vertical-lr")
        layout = _layout(document, "#label")
        assert layout["writing_mode"] == "vertical-lr", (
            f"environment: the browser computes writing-mode {layout['writing_mode']!r}"
        )
        line_rects = browser_each_rect(document, "#label span")
        assert line_rects[0]["x"] + line_rects[0]["w"] <= line_rects[1]["x"] + 0.5, (
            f"fixture drift: vertical-lr must stack 'First column' left of 'Second column': "
            f"{line_rects}"
        )
        expected = [VERTICAL_LR_LINES[index] for index in _stacking_order(line_rects, 90.0)]
        assert expected == list(reversed(VERTICAL_LR_LINES)), (
            f"oracle: a 90 degree box stacks the browser's lines as {expected}"
        )
        shapes = _shapes(rotation_pptx, "vertical-lr")
        _, label = _text_item(shapes, "column", "the vertical-lr label")

        assert [_normalised(line) for line in _lines(label)] == expected, (
            f"the vertical-lr label's lines are {_lines(label)}, expected {expected}: the order "
            "a 90 degree box must stack them in to put 'First column' on the left"
        )
        _assert_turned_box(label, layout, 90.0, "the vertical-lr label", vertical=True)


@pytest.mark.slow
@requires_huashu_sidecar
class TestRotatedBoxWithBackground:
    def test_a_rotated_pill_is_a_shape_and_its_text_turned_alike(
        self, rotation_pptx: bytes
    ) -> None:
        """R11d: a ``rotate(-8deg)`` pill "NEW" with a background is a shape AND a text item.

        Both have ``rot`` 352 degrees and are centred on the pill's bounds
        within 1 px; the shape (its FF5F46 fill) comes before the text in
        paint order; the text stays editable (a text run, no picture on the
        slide). A shape turned under unturned text would cross the pill's edge.
        """
        document = _document("pill")
        layout = _layout(document, "#pill")
        shapes = _shapes(rotation_pptx, "pill")
        filled = [
            (position, shape) for position, shape in enumerate(shapes) if shape.fill == "FF5F46"
        ]
        assert len(filled) == 1 and filled[0][1].kind == "shape", (
            f"expected the pill's background as one shape filled FF5F46:\n{_describe(shapes)}"
        )
        shape_index, pill = filled[0]
        text_index, text = _text_item(shapes, "NEW", "the pill's text")

        assert text is not pill, "the pill's text and its background must be two items"
        _assert_angle(pill, 352.0, "the pill's shape")
        _assert_angle(text, 352.0, "the pill's text")
        _assert_centred(pill, layout, "the pill's shape")
        _assert_centred(text, layout, "the pill's text")
        assert shape_index < text_index, (
            f"the pill's shape (spTree {shape_index}) must paint before its text "
            f"(spTree {text_index}):\n{_describe(shapes)}"
        )
        assert [run.text for paragraph in text.paras for run in paragraph.runs] == ["NEW"], (
            f"the pill's text is not one editable run: {text.paras}"
        )
        pictures = [shape for shape in shapes if shape.kind == "picture"]
        assert not pictures, f"the pill slide holds a picture:\n{_describe(shapes)}"


@pytest.mark.slow
@requires_huashu_sidecar
class TestEllipsis:
    def test_an_ellipsis_title_exports_what_the_screen_shows(self, rotation_pptx: bytes) -> None:
        """R11e: a card title cut by ``text-overflow: ellipsis`` reads as Chrome shows it.

        The screen (``browser_ellipsis``) shows the title's visible characters,
        cut mid-word, then "…". The exported item reads exactly those characters
        and "…", so its glyphs end where Chrome's do; no hidden character is on
        the slide; and the "…" takes the block's style: the title's ink, which
        the screen paints it in, not the coral of the title's first word. The
        hard-clip word rule would instead keep every word the clip shows 2 px
        of, with no "…".
        """
        document = _document("ellipsis-title")
        cut, style = _assert_ellipsis_cut(document, "#title", "the card title")
        shapes = _shapes(rotation_pptx, "ellipsis-title")

        exported, item = _cut_text(shapes, "Lakehouse", "the card title")
        assert exported == cut.visible + ELLIPSIS, (
            f"the card title exports {exported!r}; the screen shows {cut.visible + ELLIPSIS!r} "
            f"(cut at x={cut.cut}, the last glyph's ink ends at {cut.glyph_ink_end}, the "
            f"ellipsis ink at {cut.ink_end})"
        )
        hidden_words = cut.text[len(cut.visible) :].split()[1:]
        leaked = [
            word
            for word in hidden_words
            if any(word in shape.text for shape in shapes if shape.kind == "text")
        ]
        assert not leaked, f"hidden words are on the slide: {leaked}"
        assert item is not None, "the card title is no text item"
        lead = _run_holding(_ellipsis_runs(item, "the card title")[0], "Lakehouse", "the title")
        assert lead.color == "FF5F46" and _hex(style["color"]) != "FF5F46", (
            f"fixture drift: the title's first word must be coral and the title not: "
            f"{_describe_run(lead)}, title colour {style['color']}"
        )
        _assert_block_style_ellipsis(item, cut, _hex(style["color"]), "migration", "the card title")

    def test_the_ellipsis_takes_the_blocks_style_not_the_cut_inlines(
        self, rotation_pptx: bytes
    ) -> None:
        """R11e″: the "…" is in the BLOCK's style even when the cut falls inside a styled span.

        A blue, bold title holds a red, regular-weight ``<span>``, and the
        ellipsis cuts its line inside the span. Chrome paints the "…" blue and
        bold, in the title's own style, not the style of the last visible
        character (the screen's "…" colour is guarded to be the block's and not
        the span's). The exported item reads the visible characters and "…";
        the span's text keeps its red regular run; and the run holding the "…"
        is in the block's style, that of "Pipeline": blue and bold.
        """
        document = _document("ellipsis-mixed")
        cut, block = _assert_ellipsis_cut(document, "#title", "the mixed title")
        span = browser_style(document, "#title .tail")
        block_colour, span_colour = _hex(block["color"]), _hex(span["color"])
        assert (block["fontWeight"], span["fontWeight"]) == ("700", "400") and (
            block_colour != span_colour
        ), (
            f"fixture drift: the title must be bold and the span regular, in other colours: "
            f"{block_colour} {block['fontWeight']}, {span_colour} {span['fontWeight']}"
        )
        assert len(cut.visible) > len("Pipeline ") and not _shows_colour(
            cut.ellipsis_ink_colour, span_colour
        ), (
            f"fixture drift: the cut must fall inside the span and the screen paint its ellipsis "
            f"in another colour than the span's; it shows {cut.visible!r}, ellipsis "
            f"{cut.ellipsis_ink_colour}"
        )
        shapes = _shapes(rotation_pptx, "ellipsis-mixed")

        exported, item = _cut_text(shapes, "Pipeline", "the mixed title")
        assert exported == cut.visible + ELLIPSIS, (
            f"the mixed title exports {exported!r}; the screen shows {cut.visible + ELLIPSIS!r} "
            f"(cut at x={cut.cut}, the ellipsis ink ends at {cut.ink_end})"
        )
        assert item is not None, "the mixed title is no text item"
        runs, _ = _ellipsis_runs(item, "the mixed title")
        last_visible = cut.visible.split()[-1]
        span_run = _run_holding(runs, last_visible, "the mixed title")
        assert span_run.color == span_colour and not span_run.bold, (
            f"the span's last visible word must stay red and regular: {_describe_run(span_run)}"
        )
        ellipsis_run = _assert_block_style_ellipsis(
            item, cut, block_colour, "Pipeline", "the mixed title"
        )
        assert ellipsis_run.bold, f"the ellipsis run is not bold: {_describe_run(ellipsis_run)}"

    def test_an_ellipsis_cell_exports_what_the_screen_shows_and_stays_native(
        self, rotation_pptx: bytes
    ) -> None:
        """R11e: a table cell cut by ``text-overflow: ellipsis`` reads as Chrome shows it.

        The table is still one native table on the browser's rect. The cell's
        line (written once: as its ``a:tc``'s text or as one overlay item)
        reads exactly the visible characters the screen shows, then "…"; Chrome
        cuts it at the cell's content-box edge, 12 px inside its padding box (cut
        at the padding box, "mod" would read "mode" or "model"). No hidden word
        is on the slide. The hard-clip word rule would instead keep every word
        the clip shows 2 px of, with no "…".
        """
        document = _document("ellipsis-cell")
        cut, _ = _assert_ellipsis_cut(document, "#cell", "the cut cell")
        (table,) = browser_tables(document, "#grid")
        shapes = _shapes(rotation_pptx, "ellipsis-cell")

        frames = table_frames(shapes)
        assert len(frames) == 1, f"expected the table as one native table:\n{_describe(shapes)}"
        extent = table_extent(frames[0][1])
        off = {key: round(extent[key] - table.rect[key], 3) for key in ("x", "y", "w", "h")}
        assert all(abs(delta) <= GEOMETRY_TOLERANCE_PX for delta in off.values()), (
            f"the native table is at {extent}, the browser's at {table.rect} (off by {off})"
        )
        exported, _ = _cut_text(shapes, "Unity", "the cut cell")
        assert _normalised(exported) == cut.visible + ELLIPSIS, (
            f"the cut cell exports {exported!r}; the screen shows {cut.visible + ELLIPSIS!r} "
            f"(cut at x={cut.cut}, the ellipsis ink ends at {cut.ink_end}, the content box at "
            f"{cut.content['x'] + cut.content['w']})"
        )
        hidden_words = cut.text[len(cut.visible) :].split()[1:]
        leaked = [
            word
            for word in hidden_words
            if any(word in shape.text.split() for shape in shapes if shape.kind == "text")
            or any(word in text.split() for text in _cell_texts(shapes))
        ]
        assert not leaked, f"hidden words are on the slide: {leaked}"


def _with_rotated_label(fixture: str) -> str:
    """The legacy hostile-realm fixture ``fixture``, ``HOSTILE_LABEL`` closing its slide root."""
    html = (FIXTURE_DIR / f"{fixture}.html").read_text(encoding="utf-8")
    assert html.count(SLIDE_ROOT_END) == 1, f"fixture drift: {fixture}'s slide root end moved"
    return html.replace(SLIDE_ROOT_END, f"      {HOSTILE_LABEL}\n{SLIDE_ROOT_END}")


def _export_bounded(monkeypatch: pytest.MonkeyPatch, document: str) -> tuple[bytes, list[dict]]:
    """Export one complete document, bounded so a hang fails within the hostile-realm timeout."""
    monkeypatch.setattr(
        pptx_from_html_huashu, "SIDECAR_TIMEOUT_SECONDS", HOSTILE_EXPORT_TIMEOUT_SECONDS
    )
    return export_documents([document], monkeypatch=monkeypatch, engine=ENGINE)


@pytest.mark.slow
@requires_huashu_sidecar
class TestRotatedTextInAHostileRealm:
    def test_the_hostile_text_node_deck_with_a_rotated_label_terminates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A guard: with a rotated label added, the hostile deck still exports.

        ``hostile_text_nodes`` replaces ``firstChild``, ``nextSibling``,
        ``nodeType``, ``childNodes``, ``textContent`` and ``CharacterData.data``
        (``test_export_snapshot_hostile_realm.py`` proves each replacement
        bites). A rotated label's text is read by its own path; whatever that
        path reads, the export returns within the bound with the slide.
        """
        pptx, failures = _export_bounded(monkeypatch, _with_rotated_label(HOSTILE_FIXTURE))

        assert pptx and failures == [], f"the hostile deck did not export: {failures}"

    def test_a_rotated_label_in_the_hostile_realm_exports_as_its_benign_twin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The rotated label reads the pristine tree: one turned item, as in the benign twin.

        In the hostile deck the label is one text item reading "Rotated label"
        (never the realm's decoy), ``rot`` 270 degrees, on its unrotated box
        centred on its bounds (measured in the benign twin, whose layout is
        the same); and the whole hostile artifact equals the benign twin's,
        both with the label added.
        """
        hostile, hostile_failures = _export_bounded(
            monkeypatch, _with_rotated_label(HOSTILE_FIXTURE)
        )
        benign_document = _with_rotated_label(BENIGN_TWIN)
        benign, benign_failures = _export_bounded(monkeypatch, benign_document)
        assert hostile_failures == [] and benign_failures == [], (
            f"the export rejected a slide: {hostile_failures} / {benign_failures}"
        )
        layout = _layout(benign_document, "#rotated-label")
        shapes = slide_shapes(hostile, 0)
        decoys = [shape for shape in shapes if "decoy" in shape.text]
        assert not decoys, f"the hostile realm's decoy text is on the slide:\n{_describe(shapes)}"
        _, label = _text_item(shapes, "Rotated", "the hostile deck's rotated label")

        _assert_one_line(label, HOSTILE_LABEL_TEXT, "the hostile deck's rotated label")
        _assert_turned_box(label, layout, 270.0, "the hostile deck's rotated label")
        assert structural_manifest(hostile) == structural_manifest(benign), (
            f"with a rotated label, {HOSTILE_FIXTURE} does not export as its benign twin "
            f"{BENIGN_TWIN}"
        )
