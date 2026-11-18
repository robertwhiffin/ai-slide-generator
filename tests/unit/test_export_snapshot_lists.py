"""Snapshot engine: list markers.

A list item's marker ("1.", "4." in a reversed list, "•", "◦", an image) is
no DOM text, so no Range can measure it, and the engine never counts it by
hand. It reads each ``::marker`` read-only through the DevTools protocol, as
it reads ``::before`` and ``::after`` (ruling R9): the protocol lists the
marker among the item's pseudo-elements (``pseudoType`` "marker"), its box is
``DOM.getBoxModel``'s, and its text is the layout text Chrome rendered for it,
the list's own ``start``, ``reversed`` and ``value`` numbering included. An
item whose ``list-style-type`` is ``none``, or whose ``::marker`` has
``content: none``, has no marker node, so it gets no marker.

How a marker is drawn:

* outside its item (the default), a marker is one single-line text item of
  its own, in the marker's own computed style (R9a), at the item's place in
  paint order and before the item's text. Its text is Chrome's marker text with
  its trailing white space trimmed. Left to right it is right-aligned, its
  right edge where the marker's glyphs end (its box's edge less the trailing
  space the box holds, which for a disc, circle or square is none) and its
  width slack (6% + 4 px) grown to the left; right to left it is the mirror
  (R9e′);
* ``list-style-position: inside`` puts the marker on the item's first line.
  Where the item's text runs straight on from it ("1. " and then the text),
  it is a token of that line: the item's first paragraph starts with it, and
  no item of its own holds it. Where a gap follows it (an inside disc's 20 px
  margin) the line is cut there: the marker is an item of its own and the
  text keeps its browser x (R9g);
* an image marker (``list-style-image``) is a picture of its own pixels at its
  box (R9d);
* no paragraph anywhere is a native PowerPoint bullet (``a:buChar``,
  ``a:buAutoNum``, ``a:buBlip``): markers are only ever items or tokens (R9f).

Every assertion reads the emitted slide XML and holds it against the browser's
own rendering of the very same document. ``browser_each_pseudo(..., "marker")``
reads each marker's box, text and computed style through the DevTools
protocol, and where its pixels are on screen (``ink``): a text marker's box
ends with the advance of its trailing space, and Chrome paints a disc, circle
or square as a shape in a box of the symbol's own size, so neither box is
where the glyphs end. Corpus slides are loaded by prefix (14's ordered list,
16's ``list-style: none`` list, 09's ``::before`` bullets); every other case is
a small inline document.

Slide script has already run in the page by the time anything is read: a
realm that lies about its nodes exports its list as its benign twin does.

Gating matches the sibling export suites: needs node, the extracted sidecar
``node_modules`` and a local Chrome/Chromium (skipped otherwise).
"""

from __future__ import annotations

import base64
import re
from collections.abc import Iterator
from dataclasses import dataclass
from io import BytesIO

import pytest
from PIL import Image

from src.services import pptx_from_html_huashu
from tests.fixtures.export_snapshot_support import (
    DECK_CSS,
    NAMESPACES,
    Shape,
    browser_each_pseudo,
    browser_each_rect,
    browser_line_boxes,
    browser_style,
    corpus_document,
    corpus_slide,
    export_corpus,
    export_slides,
    requires_huashu_sidecar,
    slide_document,
    slide_shapes,
    slide_xml,
)
from tests.unit.test_export_collection_iteration_hostile_realm import (
    HOSTILE_EXPORT_TIMEOUT_SECONDS,
)
from tests.unit.test_export_slide_root_background import FIXTURE_DIR as SLIDE_ROOT_FIXTURE_DIR
from tests.unit.test_export_svg_raster import structural_manifest

# Spec §3 Text, Wrapping: every text box gets 6 % plus 4 px of width slack.
SLACK_FRACTION = 0.06
SLACK_PX = 4.0
# The brief's tolerance: a marker's emitted edge is within 3 px of where the
# browser's glyphs end. An emitted edge is the text's advance; the browser's
# glyphs end a side bearing inside it (measured: 0.7 px for DM Sans's period,
# 1.8 px for Arial's at 24 px, 1.7 px for the arrow's fallback face).
MARKER_EDGE_TOLERANCE_PX = 3.0
# Boxes, and left-aligned text placed at a box, match the browser's within 0.5 px.
RECT_TOLERANCE_PX = 0.5
SIZE_TOLERANCE_PT = 0.01
PT_PER_PX = 0.75
# A marker outside its item sits in the list's start padding (40 px by
# default): a text item there, beside an item that has no marker, is one.
MARKER_BAND_PX = 40.0
# R9g: an inside marker joins its line only when the text starts within 1 px
# of where the marker ends; cut from it, the text keeps its browser x within 1 px.
INSIDE_JOIN_PX = 1.0
INSIDE_TEXT_TOLERANCE_PX = 1.0
# CSS white space: what Chrome's marker text ends with, and what is trimmed.
CSS_WHITE_SPACE = " \t\n\r\f"
# Native PowerPoint bullets, none of which a marker may become.
NATIVE_BULLETS = ("buChar", "buAutoNum", "buBlip")
# A text item that reads as a list marker alone: a counter with its suffix, or a symbol.
MARKER_LIKE = re.compile(r"^(?:\d+|[a-zA-Z]{1,4})[.)]$|^[\u2022\u25e6\u25aa\u25a0\u2192-]$")
COLOUR_TOLERANCE = 6
# Captures are taken at device scale 2.
CAPTURE_SCALE = 2
IMAGE_PIXEL_SHARE = 0.9

# Corpus slide 14: an ordered list of three items beside the KPI row.
ORDERED_LIST = "ol li"
ORDERED_MARKERS = ("1. ", "2. ", "3. ")
ORDERED_ITEMS = (
    "Hold price increases through H1",
    "Ramp the new tooling line in Q2",
    "Keep capex within the $75M envelope",
)
# Corpus slide 16: a list-style: none list on the dark closing slide.
UNMARKED_LIST = "ul li"
UNMARKED_ITEMS = ("$75M growth capex", "$40M debt paydown", "Dividend held at $28.8M")
# Corpus slide 09: .dk-list is list-style: none, its bullets ::before squares.
PSEUDO_BULLET_LIST = ".dk-list li"
PSEUDO_BULLET_ITEMS = 4

# Every kind of marker but the image one, each list in a column of its own.
KINDS_CSS = """
.lm-col { position: absolute; width: 240px; font-size: 20px; }
.lm-col ol, .lm-col ul { margin: 0; }
#lm-arrow li::marker { content: "\u2192 "; }
#lm-silent li::marker { content: none; }
#lm-styled li::marker { color:#FF3621; font-weight:700 }
#lm-restyled li::marker { font-family: 'DM Mono', monospace; font-size: 28px; font-style: italic; }
#lm-inside { list-style-position: inside; }
#lm-inside li::marker { color: #FF3621; }
#lm-inside-disc { list-style-position: inside; }
"""


@dataclass(frozen=True)
class MarkedList:
    """One list of the kinds slide: its id, where it stands, its markup and its items' labels."""

    list_id: str
    left: int
    top: int
    markup: str
    labels: tuple[str, ...]
    # What Chrome renders for each item's marker, None for none: a guard against fixture drift.
    markers: tuple[str | None, ...]


KIND_LISTS = (
    MarkedList(
        "lm-reversed",
        120,
        140,
        '<ol id="lm-reversed" start="4" reversed><li>Fourth</li><li>Third</li><li>Second</li></ol>',
        ("Fourth", "Third", "Second"),
        ("4. ", "3. ", "2. "),
    ),
    MarkedList(
        "lm-disc",
        420,
        140,
        '<ul id="lm-disc"><li>Pricing</li><li>Mix</li></ul>',
        ("Pricing", "Mix"),
        ("\u2022 ", "\u2022 "),
    ),
    MarkedList(
        "lm-nested",
        720,
        140,
        '<ul id="lm-nested"><li>Platform<ul><li>Unity Catalog</li><li>Lakeflow</li></ul></li>'
        "<li>People</li></ul>",
        ("Platform", "Unity Catalog", "Lakeflow", "People"),
        ("\u2022 ", "\u25e6 ", "\u25e6 ", "\u2022 "),
    ),
    MarkedList(
        "lm-arrow",
        1000,
        140,
        '<ul id="lm-arrow"><li>Next step</li><li>Then</li></ul>',
        ("Next step", "Then"),
        ("\u2192 ", "\u2192 "),
    ),
    MarkedList(
        "lm-inside",
        120,
        400,
        '<ol id="lm-inside"><li>Hold price</li><li>Ramp tooling</li></ol>',
        ("Hold price", "Ramp tooling"),
        ("1. ", "2. "),
    ),
    MarkedList(
        "lm-styled",
        420,
        400,
        '<ol id="lm-styled"><li>Revenue</li><li>Margin</li></ol>',
        ("Revenue", "Margin"),
        ("1. ", "2. "),
    ),
    MarkedList(
        "lm-restyled",
        720,
        400,
        '<ol id="lm-restyled"><li>Capex</li><li>Debt</li></ol>',
        ("Capex", "Debt"),
        ("1. ", "2. "),
    ),
    MarkedList(
        "lm-rtl",
        1000,
        400,
        '<ol id="lm-rtl" dir="rtl"><li>Right to left</li></ol>',
        ("Right to left",),
        ("1. ",),
    ),
    MarkedList(
        "lm-silent",
        120,
        600,
        '<ol id="lm-silent"><li>Unnumbered</li></ol>',
        ("Unnumbered",),
        (None,),
    ),
    MarkedList(
        "lm-inside-disc",
        420,
        600,
        '<ul id="lm-inside-disc"><li>Governed</li><li>Shared</li></ul>',
        ("Governed", "Shared"),
        ("\u2022 ", "\u2022 "),
    ),
)
KINDS = {kind.list_id: kind for kind in KIND_LISTS}
KINDS_BODY = (
    '<div class="slide"><p class="dk-eyebrow">List markers</p>'
    + "".join(
        f'<div class="lm-col" style="left: {kind.left}px; top: {kind.top}px;">{kind.markup}</div>'
        for kind in KIND_LISTS
    )
    + "</div>"
)
# The lists whose markers' own style differs from their items' (R9a): the
# ruling's rule verbatim, and a marker in another family, size and style.
STYLED_LISTS = ("lm-styled", "lm-restyled")
STYLED_MARKER = {"color": "rgb(255, 54, 33)", "fontWeight": "700"}
RESTYLED_MARKER = {"fontFamily": '"DM Mono", monospace', "fontSize": "28px", "fontStyle": "italic"}
INSIDE_MARKER_COLOUR = "rgb(255, 54, 33)"


def _png_data_uri(colour: str, side: int) -> str:
    """A ``side`` x ``side`` PNG of one colour, as a data: URI."""
    buffer = BytesIO()
    Image.new("RGB", (side, side), "#" + colour).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


# Image markers: each item's marker is a 16x16 data: PNG (7B2FBE), which has
# a box and no text, so only a picture can show it.
IMAGE_COLOUR = "7B2FBE"
IMAGE_SIDE_PX = 16
IMAGE_CSS = (
    f".lm-images {{ list-style-image: url('{_png_data_uri(IMAGE_COLOUR, IMAGE_SIDE_PX)}'); "
    "font-size: 20px; margin: 24px 0 0; }\n"
    ".lm-images li { margin-bottom: 12px; }\n"
)
IMAGE_ITEMS = ("Unity Catalog governs every table", "Lakeflow runs the pipelines")
IMAGE_BODY = (
    '<div class="slide"><p class="dk-eyebrow">Platform</p><ul class="lm-images">'
    + "".join(f"<li>{item}</li>" for item in IMAGE_ITEMS)
    + "</ul></div>"
)
# A capture is taken at device scale 2, so a 16 px image is 32x32 pixels.
IMAGE_PIXELS = (IMAGE_SIDE_PX * CAPTURE_SCALE) ** 2

# A numbered list added to the hostile-realm fixtures, after the prose.
HOSTILE_ANCHOR = '<div class="prose">Synthetic fixture slide.</div>'
HOSTILE_LIST = (
    '<ol class="hl-list" style="padding-left: 40px; font-size: 24px;">'
    "<li>Pass one</li><li>Pass two</li></ol>"
)
HOSTILE_MARKERS = ("1. ", "2. ")
HOSTILE_TEXT_NODES = "hostile_text_nodes"
BENIGN_TWIN = "collection_passes"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _export(body: str, monkeypatch: pytest.MonkeyPatch, *, css: str = DECK_CSS) -> bytes:
    pptx, failures = export_slides([body], css=css, engine="snapshot", monkeypatch=monkeypatch)
    assert failures == [], f"the export rejected the slide: {failures}"
    assert pptx, "the export produced no .pptx bytes"
    return pptx


def _document(body: str, *, css: str = DECK_CSS) -> str:
    """The document ``_export`` exported (``export_slides`` names slide 1 ``snapshot-1``)."""
    return slide_document(body, css=css, slide_id="snapshot-1")


def _hex(colour: str) -> str:
    """'RRGGBB' of a computed ``rgb(…)`` colour."""
    match = re.fullmatch(r"rgba?\(([^)]*)\)", colour.strip())
    assert match, f"not a computed rgb() colour: {colour!r}"
    channels = [part.strip() for part in match.group(1).replace("/", ",").split(",")]
    red, green, blue = (int(round(float(channel))) for channel in channels[:3])
    return f"{red:02X}{green:02X}{blue:02X}"


def _px(length: str) -> float:
    assert length.endswith("px"), f"not a computed px length: {length!r}"
    return float(length[:-2])


def _first_family(font_family: str) -> str:
    """The first family of a computed ``font-family``, unquoted."""
    return font_family.split(",")[0].strip().strip("\"'")


def _normalised(text: str) -> str:
    return " ".join(text.split())


def _trimmed(marker: dict) -> str:
    """The marker's text as it is exported: Chrome's, its trailing white space trimmed."""
    return marker["text"].rstrip(CSS_WHITE_SPACE)


def _rect(box: dict | None) -> dict | None:
    if box is None:
        return None
    return {key: round(box[key], 3) for key in ("x", "y", "w", "h")}


def _describe(shapes: list[Shape]) -> str:
    return "\n".join(
        f"  [{position}] {shape.kind} box=({shape.x:.2f}, {shape.y:.2f}, {shape.w:.2f}, "
        f"{shape.h:.2f}) wrap={shape.wrap} align={[para.align for para in shape.paras]} "
        f"rtl={[para.rtl for para in shape.paras]} text={shape.text[:40]!r}"
        for position, shape in enumerate(shapes)
    )


def _right(box: dict) -> float:
    return box["x"] + box["w"]


def _on_marker(shape: Shape, marker: dict) -> bool:
    """Whether a text item lies on a marker: over its glyphs, its middle on the marker's line.

    Horizontally the item overlaps where the marker paints (its ``ink``; its
    box for an image marker), so an outside marker's own item is on it and the
    item's text beside it is not.
    """
    area = marker["ink"] or marker
    middle = shape.y + shape.h / 2
    return (
        shape.kind == "text"
        and marker["y"] <= middle <= marker["y"] + marker["h"]
        and shape.x < _right(area)
        and shape.x + shape.w > area["x"]
    )


def _items_on(shapes: list[Shape], marker: dict) -> list[int]:
    return [position for position, shape in enumerate(shapes) if _on_marker(shape, marker)]


def _assert_outside_marker(shapes: list[Shape], marker: dict, what: str) -> int:
    """A marker outside its item is one single-line text item at its glyphs (R9e′).

    It reads the browser's marker text with the trailing white space trimmed.
    Left to right it is right-aligned, its right edge within 3 px of where the
    browser's glyphs end and its slack (at least 4 px) grown to the left of the
    glyphs; right to left it is left-aligned at the glyphs' left edge with its
    slack to the right, and its paragraph is right-to-left as the marker is.
    It is no wider than the browser's marker box with its slack: never a box
    across its item or its list. Returns its spTree index.
    """
    ink = marker["ink"]
    assert ink is not None, f"fixture drift: {what} paints no pixels the browser shows"
    found = _items_on(shapes, marker)
    assert len(found) == 1, (
        f"{what}: expected one text item on the browser's marker {_rect(marker)} "
        f"(its glyphs {_rect(ink)}), got {[shapes[position].text for position in found]}:\n"
        f"{_describe(shapes)}"
    )
    shape = shapes[found[0]]
    expected = _trimmed(marker)
    assert shape.text == expected, (
        f"{what}: the marker item reads {shape.text!r}; the browser renders {marker['text']!r}, "
        f"which is {expected!r} trimmed"
    )
    assert len(shape.paras) == 1 and shape.wrap == "none", (
        f"{what}: the marker item is {len(shape.paras)} paragraphs, wrap={shape.wrap}; a "
        "marker is a single line that never wraps"
    )
    para = shape.paras[0]
    right_to_left = marker["style"]["direction"] == "rtl"
    if right_to_left:
        assert para.align == "left", (
            f"{what}: a right-to-left marker is left-aligned at its glyphs, got {para.align}"
        )
        assert abs(shape.x - ink["x"]) <= MARKER_EDGE_TOLERANCE_PX, (
            f"{what}: the marker item's left edge is {shape.x:.2f}; the browser's glyphs start "
            f"at {ink['x']:.2f} (tolerance {MARKER_EDGE_TOLERANCE_PX} px)"
        )
        assert shape.x + shape.w >= _right(ink) + SLACK_PX - RECT_TOLERANCE_PX, (
            f"{what}: the marker item ends at {shape.x + shape.w:.2f}, the glyphs at "
            f"{_right(ink):.2f}: its slack is not grown to the right"
        )
        assert para.rtl, f"{what}: the marker is right to left, its paragraph is not"
    else:
        assert para.align == "right", (
            f"{what}: a marker is right-aligned at its glyphs, got {para.align}"
        )
        assert abs(shape.x + shape.w - _right(ink)) <= MARKER_EDGE_TOLERANCE_PX, (
            f"{what}: the marker item's right edge is {shape.x + shape.w:.2f}; the browser's "
            f"glyphs end at {_right(ink):.2f} (its box at {_right(marker):.2f}; tolerance "
            f"{MARKER_EDGE_TOLERANCE_PX} px)"
        )
        assert shape.x <= ink["x"] - SLACK_PX + RECT_TOLERANCE_PX, (
            f"{what}: the marker item starts at {shape.x:.2f}, the glyphs at {ink['x']:.2f}: "
            "its slack is not grown to the left"
        )
    widest = marker["w"] * (1 + SLACK_FRACTION) + SLACK_PX + RECT_TOLERANCE_PX
    assert shape.w <= widest, (
        f"{what}: the marker item is {shape.w:.2f} px wide; the browser's marker box is "
        f"{marker['w']:.2f} px, so with its slack the item is at most {widest:.2f}"
    )
    return found[0]


def _assert_no_marker_beside(shapes: list[Shape], item: dict, what: str) -> None:
    """Nothing is drawn where an outside marker would be: the list's start padding by the item."""
    beside = [
        shape
        for shape in shapes
        if shape.kind == "text"
        and item["x"] - MARKER_BAND_PX <= shape.x + shape.w / 2 <= item["x"]
        and item["y"] <= shape.y + shape.h / 2 <= item["y"] + item["h"]
    ]
    assert beside == [], (
        f"{what}: text is drawn beside the item, where a marker would be: "
        f"{[shape.text for shape in beside]}:\n{_describe(shapes)}"
    )


def _native_bullets(pptx: bytes) -> list[str]:
    """Every native bullet element anywhere in slide 1's XML, by name."""
    slide = slide_xml(pptx)
    return [name for name in NATIVE_BULLETS for _ in slide.iter(f"{{{NAMESPACES['a']}}}{name}")]


def _same_style(key: str, emitted: object, expected: object) -> bool:
    """Whether one run property is the browser's: a size within 0.01 pt, anything else equal."""
    if key == "size_pt":
        return emitted is not None and abs(float(emitted) - float(expected)) <= SIZE_TOLERANCE_PT
    return emitted == expected


def _is(pixel: tuple[int, int, int, int], colour: str) -> bool:
    expected = (int(colour[0:2], 16), int(colour[2:4], 16), int(colour[4:6], 16))
    return pixel[3] >= 250 and all(
        abs(channel - want) <= COLOUR_TOLERANCE for channel, want in zip(pixel[:3], expected)
    )


def _only(shapes: list[Shape], label: str, what: str) -> tuple[int, Shape]:
    """The one text item holding an item's label, and its spTree index."""
    found = [
        position
        for position, shape in enumerate(shapes)
        if shape.kind == "text" and label in shape.text
    ]
    assert len(found) == 1, (
        f"{what}: expected one text item holding {label!r}, got {len(found)}:\n{_describe(shapes)}"
    )
    return found[0], shapes[found[0]]


# ---------------------------------------------------------------------------
# Exports and browser geometry, read once per module
# ---------------------------------------------------------------------------


@dataclass
class Exported:
    """One exported slide, its spTree, and the browser geometry its tests compare against."""

    pptx: bytes
    shapes: list[Shape]
    geometry: dict


def _guard_markers(markers: list[dict | None], expected: tuple[str | None, ...], what: str) -> None:
    rendered = [None if marker is None else marker["text"] for marker in markers]
    assert rendered == list(expected), (
        f"fixture drift: the browser renders {what}'s markers as {rendered}, expected "
        f"{list(expected)}"
    )


@pytest.fixture(scope="module")
def fixture_14() -> Iterator[Exported]:
    """Corpus slide 14 exported once, with its ordered list's markers as the browser has them."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        pptx, failures = export_corpus(["14"], monkeypatch=monkeypatch)
    assert failures == [], f"the export rejected corpus slide 14: {failures}"
    markers = browser_each_pseudo(corpus_document("14"), ORDERED_LIST, "marker")
    _guard_markers(markers, ORDERED_MARKERS, "corpus slide 14's <ol>")
    yield Exported(pptx=pptx, shapes=slide_shapes(pptx), geometry={"markers": markers})


@pytest.fixture(scope="module")
def fixture_16() -> Iterator[Exported]:
    """Corpus slide 16 exported once, with its ``list-style: none`` list's item boxes."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        pptx, failures = export_corpus(["16"], monkeypatch=monkeypatch)
    assert failures == [], f"the export rejected corpus slide 16: {failures}"
    document = corpus_document("16")
    markers = browser_each_pseudo(document, UNMARKED_LIST, "marker")
    _guard_markers(markers, (None,) * len(UNMARKED_ITEMS), "corpus slide 16's <ul>")
    yield Exported(
        pptx=pptx,
        shapes=slide_shapes(pptx),
        geometry={"markers": markers, "items": browser_each_rect(document, UNMARKED_LIST)},
    )


@pytest.fixture(scope="module")
def fixture_09() -> Iterator[Exported]:
    """Corpus slide 09 exported once, with its ``::before``-bulleted list's items."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        pptx, failures = export_corpus(["09"], monkeypatch=monkeypatch)
    assert failures == [], f"the export rejected corpus slide 09: {failures}"
    document = corpus_document("09")
    markers = browser_each_pseudo(document, PSEUDO_BULLET_LIST, "marker")
    _guard_markers(markers, (None,) * PSEUDO_BULLET_ITEMS, "corpus slide 09's .dk-list")
    yield Exported(
        pptx=pptx,
        shapes=slide_shapes(pptx),
        geometry={"markers": markers, "items": browser_each_rect(document, PSEUDO_BULLET_LIST)},
    )


@pytest.fixture(scope="module")
def kinds() -> Iterator[Exported]:
    """The kinds slide exported once, with every list's markers as the browser renders them."""
    css = DECK_CSS + KINDS_CSS
    with pytest.MonkeyPatch.context() as monkeypatch:
        pptx = _export(KINDS_BODY, monkeypatch, css=css)
    document = _document(KINDS_BODY, css=css)
    every = browser_each_pseudo(document, ".lm-col li", "marker")
    assert len(every) == sum(len(kind.labels) for kind in KIND_LISTS), (
        f"fixture drift: the kinds slide has {len(every)} list items"
    )
    markers = {}
    start = 0
    for kind in KIND_LISTS:
        markers[kind.list_id] = every[start : start + len(kind.labels)]
        start += len(kind.labels)
        _guard_markers(markers[kind.list_id], kind.markers, f"#{kind.list_id}")
    yield Exported(
        pptx=pptx,
        shapes=slide_shapes(pptx),
        geometry={
            "markers": markers,
            "item_styles": {
                list_id: browser_style(document, f"#{list_id} li") for list_id in STYLED_LISTS
            },
            "silent_items": browser_each_rect(document, "#lm-silent li"),
            "inside_disc_lines": [
                browser_line_boxes(document, "#lm-inside-disc li", index)[0]
                for index in range(len(KINDS["lm-inside-disc"].labels))
            ],
        },
    )


@pytest.fixture(scope="module")
def image_markers() -> Iterator[Exported]:
    """The image-marker slide exported once, with each item's marker box."""
    css = DECK_CSS + IMAGE_CSS
    with pytest.MonkeyPatch.context() as monkeypatch:
        pptx = _export(IMAGE_BODY, monkeypatch, css=css)
    markers = browser_each_pseudo(_document(IMAGE_BODY, css=css), ".lm-images li", "marker")
    _guard_markers(markers, ("",) * len(IMAGE_ITEMS), "the image list")
    yield Exported(pptx=pptx, shapes=slide_shapes(pptx), geometry={"markers": markers})


def _marked(exported: Exported, list_id: str) -> list[tuple[dict, str]]:
    """The markers of one list of the kinds slide, each with its item's label."""
    return list(zip(exported.geometry["markers"][list_id], KINDS[list_id].labels))


def _all_markers(exported: Exported) -> list[dict]:
    """Every marker the browser renders on an exported slide."""
    markers = exported.geometry["markers"]
    lists = markers.values() if isinstance(markers, dict) else [markers]
    return [marker for found in lists for marker in found if marker is not None]


# ---------------------------------------------------------------------------
# Ordered lists number their items as the browser does
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestOrderedListMarkers:
    def test_the_ordered_list_is_numbered_1_2_3_at_its_glyphs(self, fixture_14: Exported) -> None:
        """Corpus slide 14's ``<ol>``: three marker items "1.", "2." and "3.", not bullets.

        The numbers are Chrome's own (its marker text, read through the
        DevTools protocol), each a single-line text item of its own on its
        item's first line, right-aligned, its right edge within 3 px of where
        the browser's glyphs end (its box ends 5.5 px past them: the trailing
        space's 4.8 px advance and the period's side bearing), its slack grown
        to the left. No other text item on the slide reads as a marker, and
        none is a bullet.
        """
        shapes = fixture_14.shapes
        markers = fixture_14.geometry["markers"]

        for number, marker in enumerate(markers, start=1):
            _assert_outside_marker(shapes, marker, f"slide 14's marker {number}")
        numbers = [
            shape.text
            for shape in shapes
            if shape.kind == "text" and MARKER_LIKE.match(_normalised(shape.text))
        ]
        assert numbers == [_trimmed(marker) for marker in markers], (
            f"slide 14's marker items read {numbers}; the browser numbers the list "
            f"{[marker['text'] for marker in markers]}:\n{_describe(shapes)}"
        )

    def test_each_marker_paints_with_its_item_before_the_items_text(
        self, fixture_14: Exported
    ) -> None:
        """A marker takes its item's place in paint order, ahead of the item's text.

        Back to front the slide paints marker 1, item 1's text, marker 2, item
        2's text, marker 3, item 3's text: each marker is the first thing its
        item paints, as the browser paints it in the item's first line.
        """
        shapes = fixture_14.shapes
        order = []
        for number, (marker, label) in enumerate(
            zip(fixture_14.geometry["markers"], ORDERED_ITEMS), start=1
        ):
            found = _items_on(shapes, marker)
            assert len(found) == 1, (
                f"marker {number} is not one text item on its browser box {_rect(marker)}:\n"
                f"{_describe(shapes)}"
            )
            text_index, _ = _only(shapes, label, f"item {number}")
            order += [found[0], text_index]
        assert order == sorted(order), (
            f"spTree order of (marker, text) per item is {order}; the browser paints each "
            "marker, then its item's text, item by item"
        )

    def test_start_and_reversed_count_down_from_4(self, kinds: Exported) -> None:
        """``<ol start="4" reversed>`` reads "4.", "3.", "2.", as Chrome numbers it.

        The index is Chrome's (the list's ``start`` and ``reversed``), never
        counted by the export: each marker is its outside item at its glyphs.
        """
        shapes = kinds.shapes
        for marker, label in _marked(kinds, "lm-reversed"):
            _assert_outside_marker(shapes, marker, f"the {label!r} item's marker")


# ---------------------------------------------------------------------------
# Unordered lists: discs, circles and custom content
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestUnorderedListMarkers:
    def test_a_default_list_is_marked_with_discs(self, kinds: Exported) -> None:
        """A plain ``<ul>``'s items read "•", each at the disc the browser paints.

        Chrome paints a disc as a shape in a box of its own, 9 px wide here,
        whose right edge is its glyph's: the gap to the item's text is a margin
        and no trailing space is in the box. Each disc is a right-aligned "•"
        whose right edge is within 3 px of the browser's disc.
        """
        shapes = kinds.shapes
        for marker, label in _marked(kinds, "lm-disc"):
            _assert_outside_marker(shapes, marker, f"the {label!r} item's disc")

    def test_a_nested_list_is_marked_with_circles(self, kinds: Exported) -> None:
        """A ``<ul>`` inside an item gets Chrome's second-level marker, "◦" (R9c).

        The outer items read "•" and the nested ones "◦", each at its own
        browser marker, every one an outside marker at its glyphs.
        """
        shapes = kinds.shapes
        for marker, label in _marked(kinds, "lm-nested"):
            _assert_outside_marker(shapes, marker, f"the {label!r} item's marker")

    def test_custom_marker_content_is_exported_as_the_browser_renders_it(
        self, kinds: Exported
    ) -> None:
        """``li::marker { content: "→ " }`` exports "→" (R9b).

        The text is the browser's rendering of the marker's ``content``, never
        computed by the export: each item's marker reads "→", an outside marker
        at its glyphs.
        """
        shapes = kinds.shapes
        for marker, label in _marked(kinds, "lm-arrow"):
            _assert_outside_marker(shapes, marker, f"the {label!r} item's arrow")


# ---------------------------------------------------------------------------
# A marker's own style
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestMarkerStyle:
    @pytest.mark.parametrize("list_id", STYLED_LISTS)
    def test_a_marker_is_written_in_its_own_computed_style(
        self, kinds: Exported, list_id: str
    ) -> None:
        """The marker item is in the ``::marker``'s computed style, never its item's (R9a).

        ``#lm-styled li::marker { color:#FF3621; font-weight:700 }`` is the
        ruling's rule: its markers are FF3621 and bold. ``#lm-restyled``'s
        markers are DM Mono, 28 px (21 pt) and italic. Each marker run carries
        the marker's colour, weight, style, size and family, and each item's
        text keeps its own (the deck's ink, DM Sans, 15 pt, upright, regular).
        """
        markers = kinds.geometry["markers"][list_id]
        item_style = kinds.geometry["item_styles"][list_id]
        guard = STYLED_MARKER if list_id == "lm-styled" else RESTYLED_MARKER
        drift = {
            key: marker["style"][key]
            for marker in markers
            for key in guard
            if marker["style"][key] != guard[key]
        }
        assert not drift, f"fixture drift: #{list_id}'s markers compute {drift}, expected {guard}"
        shapes = kinds.shapes

        wrong = []
        for marker, label in _marked(kinds, list_id):
            for style, runs, what in (
                (marker["style"], self._marker_runs(shapes, marker, label), "marker"),
                (item_style, self._label_runs(shapes, label), "text"),
            ):
                expected = {
                    "color": _hex(style["color"]),
                    "bold": int(style["fontWeight"]) >= 600,
                    "italic": style["fontStyle"] == "italic",
                    "size_pt": _px(style["fontSize"]) * PT_PER_PX,
                    "typeface": _first_family(style["fontFamily"]),
                }
                for run in runs:
                    emitted = {
                        "color": run.color,
                        "bold": run.bold,
                        "italic": run.italic,
                        "size_pt": run.size_pt,
                        "typeface": run.typeface,
                    }
                    off = {
                        key: (emitted[key], value)
                        for key, value in expected.items()
                        if not _same_style(key, emitted[key], value)
                    }
                    if off:
                        wrong.append(
                            f"the {label!r} item's {what} run {run.text!r}: "
                            f"(emitted, browser) {off}"
                        )
        assert not wrong, "\n".join([*wrong, _describe(shapes)])

    @staticmethod
    def _marker_runs(shapes: list[Shape], marker: dict, label: str) -> list:
        found = _items_on(shapes, marker)
        assert len(found) == 1, (
            f"the {label!r} item's marker is not one text item on its browser box "
            f"{_rect(marker)}: {[shapes[position].text for position in found]}:\n"
            f"{_describe(shapes)}"
        )
        runs = [run for para in shapes[found[0]].paras for run in para.runs if run.text.strip()]
        assert runs, f"the {label!r} item's marker item has no text runs"
        return runs

    @staticmethod
    def _label_runs(shapes: list[Shape], label: str) -> list:
        _, item = _only(shapes, label, f"the {label!r} item")
        return [run for para in item.paras for run in para.runs if run.text.strip()]


# ---------------------------------------------------------------------------
# list-style-position: inside
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestInsideMarkers:
    def test_an_inside_marker_opens_its_items_first_line(self, kinds: Exported) -> None:
        """An inside marker the text runs on from is a token of its item's first line (R9g).

        ``list-style-position: inside`` lays the marker out on the item's first
        line, its "1. " running straight into the text (it starts where the
        marker's box, trailing space and all, ends), so it joins. The item's one text
        item starts at the marker's browser box (within 0.5 px), its first
        paragraph reads the marker's text and then the item's ("1. Hold
        price"), and no other text item lies on the marker.
        """
        shapes = kinds.shapes
        for marker, label in _marked(kinds, "lm-inside"):
            index, item = _only(shapes, label, f"the inside {label!r} item")
            first_line = "".join(run.text for run in item.paras[0].runs) if item.paras else ""
            expected = _normalised(marker["text"] + label)
            assert _normalised(first_line) == expected, (
                f"the inside {label!r} item's first paragraph reads {first_line!r}; the browser's "
                f"line reads {expected!r}:\n{_describe(shapes)}"
            )
            assert abs(item.x - marker["x"]) <= RECT_TOLERANCE_PX, (
                f"the inside {label!r} item starts at x={item.x:.2f}; its line starts with the "
                f"marker at {marker['x']:.2f}"
            )
            on = _items_on(shapes, marker)
            assert on == [index], (
                f"the inside {label!r} item's marker is drawn by items {on}, not the item's own "
                f"line ({index}):\n{_describe(shapes)}"
            )

    def test_an_inside_markers_token_keeps_the_markers_own_colour(self, kinds: Exported) -> None:
        """The inside marker's token is in the ``::marker``'s colour, its item's text in its own.

        ``#lm-inside li::marker { color: #FF3621 }``: in each item's first
        paragraph the runs that hold the marker's "1." are FF3621, and the runs
        that hold the item's own text are the deck's ink, as the browser paints
        them. A run never holds both.
        """
        markers = kinds.geometry["markers"]["lm-inside"]
        assert all(marker["style"]["color"] == INSIDE_MARKER_COLOUR for marker in markers), (
            "fixture drift: the inside markers do not compute FF3621"
        )
        marker_colour = _hex(INSIDE_MARKER_COLOUR)
        shapes = kinds.shapes

        wrong = []
        for marker, label in _marked(kinds, "lm-inside"):
            _, item = _only(shapes, label, f"the inside {label!r} item")
            runs = item.paras[0].runs if item.paras else []
            line = "".join(run.text for run in runs)
            token = _trimmed(marker)
            if not line.startswith(token) or label not in line[len(token) :]:
                wrong.append(
                    f"the inside {label!r} item's line {line!r} is not {token!r} and then {label!r}"
                )
                continue
            label_start = line.index(label, len(token))
            offset = 0
            for run in runs:
                start, end = offset, offset + len(run.text)
                offset = end
                if not run.text.strip():
                    continue
                in_token = start < len(token)
                in_label = end > label_start
                if in_token and in_label:
                    wrong.append(f"{label!r}: run {run.text!r} holds the marker and the text")
                elif in_token and run.color != marker_colour:
                    wrong.append(f"{label!r}: the marker run {run.text!r} is {run.color}")
                elif in_label and run.color == marker_colour:
                    wrong.append(f"{label!r}: the text run {run.text!r} takes the marker's colour")
        assert not wrong, "\n".join([*wrong, _describe(shapes)])

    def test_an_inside_marker_a_gap_follows_is_cut_from_its_line(self, kinds: Exported) -> None:
        """An inside disc, which a margin parts from its text, is an item of its own (R9g).

        Chrome lays an inside disc out as a 9 px shape and leaves a 20 px
        margin before the item's text, so the text does not run on from the
        marker. The line is cut at the marker. Each "•" is a single-line text
        item of its own on the marker, the edge its alignment writes it from
        within 3 px of the browser's disc. The item's text is an item of its
        own that reads the label alone and starts at the browser's text x
        within 1 px, where a token "• " would have pulled it 16 px left.
        """
        shapes = kinds.shapes
        lines = kinds.geometry["inside_disc_lines"]
        for (marker, label), line in zip(_marked(kinds, "lm-inside-disc"), lines):
            what = f"the inside {label!r} item's disc"
            gap = line["x"] - _right(marker)
            assert line["text"] == label and gap > INSIDE_JOIN_PX, (
                f"fixture drift: {what}'s text starts {gap:.2f} px after it ({line})"
            )
            ink = marker["ink"]
            assert ink is not None, f"fixture drift: {what} paints no pixels the browser shows"
            found = _items_on(shapes, marker)
            assert len(found) == 1, (
                f"{what}: expected one text item on the browser's disc {_rect(marker)} (its "
                f"glyph {_rect(ink)}), got {[shapes[position].text for position in found]}:\n"
                f"{_describe(shapes)}"
            )
            disc = shapes[found[0]]
            assert disc.text == _trimmed(marker), (
                f"{what}: the item on the disc reads {disc.text!r}, not {_trimmed(marker)!r}"
            )
            assert len(disc.paras) == 1 and disc.wrap == "none", (
                f"{what}: the disc's item is {len(disc.paras)} paragraphs, wrap={disc.wrap}; "
                "it is a single line that never wraps"
            )
            align = disc.paras[0].align
            if align == "right":
                edge, browser = disc.x + disc.w, _right(ink)
            elif align == "center":
                edge, browser = disc.x + disc.w / 2, ink["x"] + ink["w"] / 2
            else:
                edge, browser = disc.x, ink["x"]
            assert abs(edge - browser) <= MARKER_EDGE_TOLERANCE_PX, (
                f"{what}: the {align}-aligned item is written from {edge:.2f}; the browser's "
                f"disc there is at {browser:.2f} (tolerance {MARKER_EDGE_TOLERANCE_PX} px)"
            )
            _, item = _only(shapes, label, f"the inside {label!r} item")
            assert _normalised(item.text) == label, (
                f"the inside {label!r} item reads {item.text!r}: the disc is joined to its line"
            )
            assert abs(item.x - line["x"]) <= INSIDE_TEXT_TOLERANCE_PX, (
                f"the inside {label!r} item starts at x={item.x:.2f}; the browser's text starts "
                f"at {line['x']:.2f} (tolerance {INSIDE_TEXT_TOLERANCE_PX} px)"
            )


# ---------------------------------------------------------------------------
# Right to left
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestRightToLeftMarkers:
    def test_a_right_to_left_marker_is_the_mirror_at_its_glyphs_left_edge(
        self, kinds: Exported
    ) -> None:
        """``<ol dir="rtl">``: the marker is right of its item, left-aligned at its glyphs (R9e′).

        Chrome puts the trailing space of "1. " on the marker's left, next to
        the item's text. The marker item reads "1.", is left-aligned with its
        left edge within 3 px of the browser's glyphs and its slack grown to the
        right, and its paragraph is right to left, as the marker's computed
        direction is, so the period stays left of the number as the browser
        paints it.
        """
        marker = kinds.geometry["markers"]["lm-rtl"][0]
        assert marker["style"]["direction"] == "rtl", "fixture drift: the marker is not rtl"
        _assert_outside_marker(kinds.shapes, marker, "the right-to-left marker")


# ---------------------------------------------------------------------------
# Image markers
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestImageMarkers:
    def test_an_image_marker_is_a_picture_of_its_own_pixels(self, image_markers: Exported) -> None:
        """``list-style-image: url(data:image/png…)``: each marker a picture at its box (R9d).

        An image marker has a box and no text. Each is one picture at its
        marker's browser box within 0.5 px, holding the marker's pixels (at
        least 90% of the 32x32 a 2x capture of the 16 px image has), and no
        text item stands in for it.
        """
        shapes = image_markers.shapes
        for marker, item in zip(image_markers.geometry["markers"], IMAGE_ITEMS):
            what = f"the {item!r} item's image marker"
            assert abs(marker["w"] - IMAGE_SIDE_PX) < 0.01, (
                f"fixture drift: {what} is {_rect(marker)}"
            )
            pictures = [
                shape
                for shape in shapes
                if shape.kind == "picture"
                and all(
                    abs(getattr(shape, key) - marker[key]) <= RECT_TOLERANCE_PX
                    for key in ("x", "y", "w", "h")
                )
            ]
            assert len(pictures) == 1, (
                f"{what}: expected one picture at its browser box {_rect(marker)}, got "
                f"{len(pictures)}:\n{_describe(shapes)}"
            )
            assert pictures[0].image, f"{what}: the picture embeds no image data"
            image = Image.open(BytesIO(pictures[0].image)).convert("RGBA")
            painted = sum(1 for pixel in image.getdata() if _is(pixel, IMAGE_COLOUR))
            assert painted >= IMAGE_PIXEL_SHARE * IMAGE_PIXELS, (
                f"{what}'s picture holds {painted} {IMAGE_COLOUR} pixels; the image is "
                f"{IMAGE_PIXELS} at 2x"
            )
            stand_ins = [shapes[position].text for position in _items_on(shapes, marker)]
            assert stand_ins == [], f"{what} is drawn as text {stand_ins}"


# ---------------------------------------------------------------------------
# Items with no marker
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestNoMarker:
    def test_list_style_none_gets_no_marker(self, fixture_16: Exported) -> None:
        """Corpus slide 16's ``list-style: none`` ``<ul>``: no marker items, no bullet.

        The browser generates no marker for its items. Each item's text is one
        text item reading the item alone, nothing is drawn where a marker would
        be, no text item reads as a marker, and no paragraph is a native bullet.
        Passes before Task 9 too: a guard that the new markers honour
        ``list-style: none``.
        """
        for item in UNMARKED_ITEMS:
            assert f"<li>{item}</li>" in corpus_slide("16"), (
                f"fixture drift: slide 16 has no item {item!r}"
            )
        shapes = fixture_16.shapes
        for label, item in zip(UNMARKED_ITEMS, fixture_16.geometry["items"]):
            _, shape = _only(shapes, label, f"slide 16's {label!r} item")
            assert _normalised(shape.text) == label, (
                f"slide 16's {label!r} item reads {shape.text!r}"
            )
            _assert_no_marker_beside(shapes, item, f"slide 16's {label!r} item")
        marker_like = [
            shape.text
            for shape in shapes
            if shape.kind == "text" and MARKER_LIKE.match(_normalised(shape.text))
        ]
        assert marker_like == [], f"slide 16 has marker items {marker_like}:\n{_describe(shapes)}"
        assert _native_bullets(fixture_16.pptx) == [], "slide 16 carries native bullets"

    def test_marker_content_none_gets_no_marker(self, kinds: Exported) -> None:
        """``li::marker { content: none }``: the browser draws no marker, and nor does the export.

        The item's text is one text item reading the item alone, and nothing
        is drawn in the list's start padding beside it. Passes before Task 9
        too: a guard.
        """
        shapes = kinds.shapes
        (label,) = KINDS["lm-silent"].labels
        _, shape = _only(shapes, label, f"the {label!r} item")
        assert _normalised(shape.text) == label, f"the {label!r} item reads {shape.text!r}"
        _assert_no_marker_beside(shapes, kinds.geometry["silent_items"][0], f"the {label!r} item")

    def test_pseudo_element_bullets_gain_no_marker(self, fixture_09: Exported) -> None:
        """Corpus slide 09's ``.dk-list``: its ``::before`` squares are its only bullets.

        ``.dk-list`` is ``list-style: none``, so the browser generates no
        marker: nothing is drawn beside any item where a marker would be, no
        text item reads as a marker, and no paragraph is a native bullet.
        Passes before Task 9 too: a regression guard on Task 8's bullets.
        """
        shapes = fixture_09.shapes
        for number, item in enumerate(fixture_09.geometry["items"], start=1):
            _assert_no_marker_beside(shapes, item, f"slide 09's item {number}")
        marker_like = [
            shape.text
            for shape in shapes
            if shape.kind == "text" and MARKER_LIKE.match(_normalised(shape.text))
        ]
        assert marker_like == [], f"slide 09 has marker items {marker_like}:\n{_describe(shapes)}"
        assert _native_bullets(fixture_09.pptx) == [], "slide 09 carries native bullets"


# ---------------------------------------------------------------------------
# No native bullets
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestNoNativeBullets:
    @pytest.mark.parametrize(
        "slide", ("fixture_14", "fixture_16", "fixture_09", "kinds", "image_markers")
    )
    def test_markers_are_items_or_tokens_never_native_bullets(
        self, slide: str, request: pytest.FixtureRequest
    ) -> None:
        """No paragraph carries ``a:buChar``, ``a:buAutoNum`` or ``a:buBlip`` (R9f).

        Each text marker the browser renders is on the slide as text on its
        marker (an item of its own, or its item's first-line token), so a deck
        whose markers are native bullets, or are missing, fails. Slides 16 and
        09 and the image slide have no text marker: for them this is a guard
        that passes before Task 9 too.
        """
        exported: Exported = request.getfixturevalue(slide)
        bullets = _native_bullets(exported.pptx)
        assert bullets == [], f"{slide}: paragraphs carry native bullets {bullets}"
        shapes = exported.shapes
        missing = [
            marker["text"]
            for marker in _all_markers(exported)
            if _trimmed(marker)
            and not any(
                _trimmed(marker) in shapes[position].text for position in _items_on(shapes, marker)
            )
        ]
        assert missing == [], (
            f"{slide}: the browser's markers {missing} are not on the slide as text:\n"
            f"{_describe(shapes)}"
        )


# ---------------------------------------------------------------------------
# A hostile realm
# ---------------------------------------------------------------------------


def _with_list(name: str) -> str:
    """A slide-root fixture with a numbered list after its prose."""
    html = (SLIDE_ROOT_FIXTURE_DIR / f"{name}.html").read_text(encoding="utf-8")
    assert html.count(HOSTILE_ANCHOR) == 1, f"fixture drift: {name}.html has no single prose div"
    return html.replace(HOSTILE_ANCHOR, HOSTILE_ANCHOR + HOSTILE_LIST, 1)


def _export_document(monkeypatch: pytest.MonkeyPatch, html: str) -> tuple[bytes, list[dict]]:
    """Export one complete document with the snapshot engine, bounded so a hang fails in seconds."""
    monkeypatch.setenv("HUASHU_PIPELINE_ENABLED", "1")
    monkeypatch.setenv("TELLR_EXPORT_ENGINE", "snapshot")
    monkeypatch.setattr(
        pptx_from_html_huashu, "SIDECAR_TIMEOUT_SECONDS", HOSTILE_EXPORT_TIMEOUT_SECONDS
    )
    return pptx_from_html_huashu.build_pptx_huashu(
        "snapshot list markers", [{"html": html}], bypass_validation=True
    )


@pytest.mark.slow
@requires_huashu_sidecar
class TestMarkersInAHostileRealm:
    def test_a_realm_that_lies_about_its_nodes_exports_its_list_as_a_benign_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``hostile_text_nodes`` with a numbered list exports as its benign twin with one.

        Its slide script replaces every node-level read (``firstChild`` and
        ``nextSibling`` return the node itself, ``childNodes`` claims a billion
        entries, ``textContent`` and ``data`` return a decoy). Markers are read
        from outside the page's realm, so none of that reaches them: the export
        completes within the hostile bound, its whole artifact equals the
        benign twin's, and the benign twin's markers are "1." and "2." at the
        browser's glyphs.
        """
        benign_html = _with_list(BENIGN_TWIN)
        markers = browser_each_pseudo(benign_html, ".hl-list li", "marker")
        _guard_markers(markers, HOSTILE_MARKERS, "the hostile twin's list")

        benign, benign_failures = _export_document(monkeypatch, benign_html)
        hostile, hostile_failures = _export_document(monkeypatch, _with_list(HOSTILE_TEXT_NODES))

        assert benign and benign_failures == [], (
            f"the benign twin did not export: {benign_failures}"
        )
        assert hostile and hostile_failures == [], (
            f"the hostile deck did not export: {hostile_failures}"
        )
        benign_shapes = slide_shapes(benign)
        for number, marker in enumerate(markers, start=1):
            _assert_outside_marker(benign_shapes, marker, f"the benign twin's marker {number}")
        assert structural_manifest(hostile) == structural_manifest(benign), (
            "the hostile deck's list does not export as its benign twin's:\n"
            f"hostile:\n{_describe(slide_shapes(hostile))}\nbenign:\n{_describe(benign_shapes)}"
        )
