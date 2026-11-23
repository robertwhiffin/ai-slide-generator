"""Snapshot engine: list markers.

A list item's marker ("1.", "4." in a reversed list, "•", "◦", an image) is
no DOM text, so no Range can measure it, and the engine never counts it by
hand. It reads each ``::marker`` read-only through the DevTools protocol, as
it reads ``::before`` and ``::after``: the protocol lists the
marker among the item's pseudo-elements (``pseudoType`` "marker"), its box is
``DOM.getBoxModel``'s, and its text is the layout text Chrome rendered for it,
the list's own ``start``, ``reversed`` and ``value`` numbering included. An
item whose ``list-style-type`` is ``none``, or whose ``::marker`` has
``content: none``, has no marker node, so it gets no marker.

How a marker is drawn:

* outside its item (the default), a marker is one single-line text item of
  its own, in the marker's own computed style, at the item's place in
  paint order and before the item's text. Its text is Chrome's marker text with
  its trailing white space trimmed. Left to right it is right-aligned, its
  right edge where the marker's glyphs end (its box's edge less the trailing
  space the box holds, which for a disc, circle or square is none) and its
  width slack (6% + 4 px) grown to the left; right to left it is the mirror;
* ``list-style-position: inside`` puts the marker on the item's first line.
  Where the item's text runs straight on from it ("1. " and then the text),
  it is a token of that line: the item's first paragraph starts with it, and
  no item of its own holds it. Where a gap follows it (an inside disc's 20 px
  margin) the line is cut there: the marker is an item of its own and the
  text keeps its browser x;
* an image marker (``list-style-image``) is a picture of its own pixels at its
  box, and only one: where its item is a picture of its own box that
  already holds the marker, that picture is the marker's;
* no paragraph anywhere is a native PowerPoint bullet (``a:buChar``,
  ``a:buAutoNum``, ``a:buBlip``): markers are only ever items or tokens.

A marker outside its item paints outside the item's box, so its colour is
composited over what the item sits on, never over the item's own background.
The engine measures marker advances with probes it adds to the page and takes
off again before it reads a style: a deck rule that matches while anything is
left after body shows a probe that stayed, as does a page that disables the
DOM's own removal.

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
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

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
    browser_pixel,
    browser_style,
    corpus_document,
    corpus_slide,
    export_corpus,
    export_documents,
    export_slides,
    node_json,
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
# The marker tolerance: a marker's emitted edge is within 3 px of where the
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
# An inside marker joins its line only when the text starts within 1 px
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
    MarkedList(
        "lm-value",
        720,
        560,
        '<ol id="lm-value"><li>Kickoff</li><li value="7">Seventh</li><li>Eighth</li></ol>',
        ("Kickoff", "Seventh", "Eighth"),
        ("1. ", "7. ", "8. "),
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
# The lists whose markers' own style differs from their items': a coloured bold
# marker, and a marker in another family, size and style.
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

# An outside marker beside a white item on a navy panel, both in a translucent
# colour: the browser composites the marker over the panel, the item's text
# over the white. A 40 px disc covers its middle pixels fully, so a screenshot
# sample there is the composited colour.
BACKDROP_CSS = """
.lm-panel { position: absolute; left: 80px; top: 120px; width: 560px; padding: 24px 0;
            background: #1B3139; }
.lm-panel ul, .lm-panel ol { margin: 0 0 16px; font-size: 40px; }
.lm-panel li { background: #FFFFFF; color: rgba(0, 0, 0, 0.5); }
"""
BACKDROP_BODY = (
    '<div class="slide"><div class="lm-panel">'
    '<ul id="lm-on-white"><li>Over white</li></ul>'
    '<ol id="lm-numbered-on-white"><li>Numbered</li></ol>'
    "</div></div>"
)
BACKDROP_LISTS = {"lm-on-white": "Over white", "lm-numbered-on-white": "Numbered"}

# A deck rule that matches only while body is not html's last child: a probe or
# an iframe the export leaves on the document element while it reads the page
# turns every item and marker it reads green.
LEFTOVER_DETECTOR_CSS = (
    "\nhtml > body:not(:last-child) li { color:#00FF00 !important }\n"
    "#lm-left-inside { list-style-position: inside; }\n"
)
LEFTOVER_GREEN = "00FF00"
LEFTOVER_BODY = (
    '<div class="slide"><p class="dk-eyebrow">Nothing left behind</p>'
    '<div class="lm-col" style="left: 120px; top: 160px;">'
    '<ol id="lm-left-outside"><li>Outside one</li><li>Outside two</li></ol></div>'
    '<div class="lm-col" style="left: 520px; top: 160px;">'
    '<ol id="lm-left-inside"><li>Inside one</li></ol></div>'
    "</div>"
)
LEFTOVER_LISTS = {
    "lm-left-outside": ("Outside one", "Outside two"),
    "lm-left-inside": ("Inside one",),
}
# Slide script that takes away the DOM's own removal before the export runs:
# a node the export adds stays unless it is removed through a realm page
# script never touched. Slide scripts go in the slide root as an inline
# <script> (_with_script): the deck's scripts run only once Chart.js loads.
DISABLE_REMOVAL_SCRIPT = """(function() {
  Element.prototype.remove = function () {};
  Node.prototype.removeChild = function (child) { return child; };
})();"""

# Image markers whose items are pictures of their own boxes (a gradient
# background): one inside its item's box, one outside it but inside the reach
# of the item's shadow. Either way the item's picture holds the marker.
BOXED_IMAGE_CSS = (
    f".lm-boxed {{ position: absolute; width: 360px; margin: 0; font-size: 20px; "
    f"list-style-image: url('{_png_data_uri(IMAGE_COLOUR, IMAGE_SIDE_PX)}'); }}\n"
    ".lm-boxed li { background: linear-gradient(90deg, #FFE7DF, #FFFFFF); }\n"
    "#lm-boxed-inside { left: 120px; top: 160px; list-style-position: inside; }\n"
    "#lm-boxed-shadow { left: 560px; top: 160px; }\n"
    "#lm-boxed-shadow li { box-shadow: 0 0 24px 16px rgba(27, 49, 57, 0.2); }\n"
)
BOXED_IMAGE_BODY = (
    '<div class="slide"><p class="dk-eyebrow">Pictures</p>'
    '<ul class="lm-boxed" id="lm-boxed-inside"><li>Governed inside</li></ul>'
    '<ul class="lm-boxed" id="lm-boxed-shadow"><li>Shadowed outside</li></ul>'
    "</div>"
)
BOXED_IMAGE_LISTS = ("lm-boxed-inside", "lm-boxed-shadow")

# Slide script that lies about the size of every offscreen probe the export
# measures with (they sit at left: -10000px), so no marker advance is finite.
LYING_PROBES_SCRIPT = """(function() {
  var measure = Element.prototype.getBoundingClientRect;
  Element.prototype.getBoundingClientRect = function () {
    var rect = measure.call(this);
    if (String(this.getAttribute('style') || '').indexOf('-10000px') < 0) return rect;
    return { left: NaN, top: NaN, right: NaN, bottom: NaN, width: NaN, height: NaN };
  };
})();"""
# The same lie with zero sizes, as a probe the page hides or empties measures.
LYING_ZERO_PROBES_SCRIPT = LYING_PROBES_SCRIPT.replace("NaN", "0")
UNMEASURED_LINE = "[html2pptx] list markers:"
# What the export says of a probe pass some of whose probes measured nothing
# (snapshot_text_metrics.mjs measureProbes), and the pass that reads line
# spacing and tracking.
UNMEASURED_PROBES_LINE = "[html2pptx] text metric probes:"
UNMEASURED_SPACING = "line spacing"
UNMEASURED_BODY = (
    '<div class="slide"><p class="dk-eyebrow">Unmeasured</p>'
    '<div class="lm-col" style="left: 120px; top: 160px;">'
    '<ol id="lm-unmeasured"><li>Unmeasured one</li><li>Unmeasured two</li></ol></div>'
    "</div>"
)

# The export with a DevTools session whose box reads of ::marker nodes, and of
# nothing else, reject: the markers are left out, said so in the count line,
# and the rest of the slide, a ::before included, exports.
UNREAD_BOXES_LINE = "[html2pptx] pseudo-elements:"
UNREAD_BOXES_CSS = '\n.lm-tagged::before { content: "\\2605 "; color: #FF3621; }\n'
UNREAD_BOXES_BODY = (
    '<div class="slide"><p class="dk-eyebrow lm-tagged">Unread boxes</p>'
    '<div class="lm-col" style="left: 120px; top: 160px;">'
    '<ol id="lm-unread"><li>Unread one</li><li>Unread two</li></ol></div>'
    "</div>"
)
UNREAD_BOXES_SCRIPT = """
(async () => {
  const documentPath = %(document)s;
  const lines = [];
  const originalError = console.error;
  const originalLog = console.log;
  console.error = (...parts) => { lines.push(parts.join(' ')); };
  console.log = () => {};
  try {
    const playwright = require('playwright');
    const launch = playwright.chromium.launch.bind(playwright.chromium);
    playwright.chromium.launch = async (options) => {
      const browser = await launch(options);
      const newContext = browser.newContext.bind(browser);
      browser.newContext = async (...args) => {
        const context = await newContext(...args);
        const newSession = context.newCDPSession.bind(context);
        context.newCDPSession = async (target) => {
          const session = await newSession(target);
          const markers = new Set();
          const collect = (node, depth) => {
            if (!node || depth > 64) return;
            for (const pseudo of node.pseudoElements || []) {
              if (pseudo.pseudoType === 'marker') markers.add(pseudo.nodeId);
            }
            for (const child of node.children || []) collect(child, depth + 1);
          };
          return {
            send: async (method, params) => {
              if (method === 'DOM.getBoxModel' && markers.has(params.nodeId)) {
                throw new Error('the box of a ::marker is unreadable (test stub)');
              }
              const result = await session.send(method, params);
              if (method === 'DOM.getDocument') collect(result.root, 0);
              return result;
            },
            detach: () => session.detach(),
          };
        };
        return context;
      };
      return browser;
    };
    const { renderSlide } = require('./render_slide.cjs');
    const PptxGenJS = require('pptxgenjs');
    const pres = new PptxGenJS();
    pres.layout = 'LAYOUT_WIDE';
    const { summary } = await renderSlide(documentPath, pres, { bypassValidation: true });
    const pptx = await pres.write({ outputType: 'base64' });
    console.error = originalError;
    console.log = originalLog;
    process.stdout.write(JSON.stringify({ summary, lines, pptx }));
  } catch (error) {
    console.error = originalError;
    console.error(error);
    process.exit(1);
  }
})();
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _export(body: str, monkeypatch: pytest.MonkeyPatch, *, css: str = DECK_CSS) -> bytes:
    pptx, failures = export_slides([body], css=css, monkeypatch=monkeypatch)
    assert failures == [], f"the export rejected the slide: {failures}"
    assert pptx, "the export produced no .pptx bytes"
    return pptx


def _with_script(body: str, script: str) -> str:
    """``body`` with ``script`` inline at the end of its slide root.

    It runs as the page is parsed, before any export pass, and body's one
    element child stays the slide root.
    """
    assert body.endswith("</div>"), "fixture drift: the body does not end with its slide root"
    return body[: -len("</div>")] + f"<script>{script}</script></div>"


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
    """A marker outside its item is one single-line text item at its glyphs.

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


def _rgba(colour: str) -> tuple[float, float, float, float]:
    """The channels and alpha of a computed ``rgb(…)`` or ``rgba(…)`` colour."""
    match = re.fullmatch(r"rgba?\(([^)]*)\)", colour.strip())
    assert match, f"not a computed rgb() colour: {colour!r}"
    channels = [float(part) for part in match.group(1).replace("/", ",").split(",")]
    return channels[0], channels[1], channels[2], channels[3] if len(channels) > 3 else 1.0


def _composite(colour: str, ground: str) -> tuple[int, int, int]:
    """``colour`` (computed, perhaps translucent) painted over the opaque ``ground``."""
    red, green, blue, alpha = _rgba(colour)
    under = _rgba(ground)
    return tuple(
        int(round(channel * alpha + beneath * (1 - alpha)))
        for channel, beneath in zip((red, green, blue), under[:3])
    )


def _channels(hex_colour: str | None) -> tuple[int, int, int] | None:
    if hex_colour is None:
        return None
    return int(hex_colour[0:2], 16), int(hex_colour[2:4], 16), int(hex_colour[4:6], 16)


def _near(colour: tuple[int, int, int] | None, expected: tuple[int, int, int]) -> bool:
    return colour is not None and all(
        abs(channel - want) <= COLOUR_TOLERANCE for channel, want in zip(colour, expected)
    )


def _text_runs(shape: Shape) -> list:
    return [run for para in shape.paras for run in para.runs if run.text.strip()]


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


@pytest.fixture(scope="module")
def backdrop() -> Iterator[Exported]:
    """The translucent-marker panel exported once, with the colours the browser paints."""
    css = DECK_CSS + BACKDROP_CSS
    with pytest.MonkeyPatch.context() as monkeypatch:
        pptx = _export(BACKDROP_BODY, monkeypatch, css=css)
    document = _document(BACKDROP_BODY, css=css)
    markers = {
        list_id: browser_each_pseudo(document, f"#{list_id} li", "marker")[0]
        for list_id in BACKDROP_LISTS
    }
    disc = markers["lm-on-white"]
    assert disc is not None and disc["ink"] is not None, (
        f"fixture drift: the panel's disc paints nothing: {disc}"
    )
    ink = disc["ink"]
    yield Exported(
        pptx=pptx,
        shapes=slide_shapes(pptx),
        geometry={
            "markers": markers,
            "panel": browser_style(document, ".lm-panel"),
            "item": browser_style(document, "#lm-on-white li"),
            "disc_pixel": browser_pixel(document, ink["x"] + ink["w"] / 2, ink["y"] + ink["h"] / 2),
        },
    )


@pytest.fixture(scope="module")
def boxed_images() -> Iterator[Exported]:
    """The image markers whose items are pictures of their own boxes, exported once."""
    css = DECK_CSS + BOXED_IMAGE_CSS
    with pytest.MonkeyPatch.context() as monkeypatch:
        pptx = _export(BOXED_IMAGE_BODY, monkeypatch, css=css)
    document = _document(BOXED_IMAGE_BODY, css=css)
    markers = {
        list_id: browser_each_pseudo(document, f"#{list_id} li", "marker")[0]
        for list_id in BOXED_IMAGE_LISTS
    }
    for list_id, marker in markers.items():
        assert marker is not None and marker["text"] == "", (
            f"fixture drift: #{list_id}'s marker is no image marker: {marker}"
        )
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

    def test_a_value_attribute_renumbers_the_list_from_it(self, kinds: Exported) -> None:
        """``<li value="7">`` in an ``<ol>`` reads "1.", "7.", "8.", as Chrome numbers it.

        The item's ``value`` sets its own number and the count goes on from it:
        Chrome's text, never counted by the export, each marker an outside
        marker at its glyphs.
        """
        shapes = kinds.shapes
        for marker, label in _marked(kinds, "lm-value"):
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
        """A ``<ul>`` inside an item gets Chrome's second-level marker, "◦".

        The outer items read "•" and the nested ones "◦", each at its own
        browser marker, every one an outside marker at its glyphs.
        """
        shapes = kinds.shapes
        for marker, label in _marked(kinds, "lm-nested"):
            _assert_outside_marker(shapes, marker, f"the {label!r} item's marker")

    def test_custom_marker_content_is_exported_as_the_browser_renders_it(
        self, kinds: Exported
    ) -> None:
        """``li::marker { content: "→ " }`` exports "→".

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
        """The marker item is in the ``::marker``'s computed style, never its item's.

        ``#lm-styled li::marker { color:#FF3621; font-weight:700 }``: its markers
        are FF3621 and bold. ``#lm-restyled``'s
        markers are DM Mono, 28 px (21 pt) and italic. Each marker run carries
        the marker's colour, weight, style, size and family, and each item's
        text keeps its own (the deck's ink, DM Sans, 15 pt, upright, regular).
        This deck is written for PowerPoint, so an italic 400 run of a webfont
        the page loaded is its italic static, ``DM Mono Italic``, with ``i``
        off (CALIBRATION.md D1: PowerPoint draws that as DM Mono's own italic,
        and ``DM Sans`` plus ``i`` as Bold Italic).
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
                italic = style["fontStyle"] == "italic"
                assert not italic or style["fontWeight"] == "400", (
                    f"fixture drift: the italic {what} of {label!r} is weight "
                    f"{style['fontWeight']}, not 400, which its typeface is named for"
                )
                family = _first_family(style["fontFamily"])
                expected = {
                    "color": _hex(style["color"]),
                    "bold": int(style["fontWeight"]) >= 600,
                    "italic": False,
                    "size_pt": _px(style["fontSize"]) * PT_PER_PX,
                    "typeface": f"{family} Italic" if italic else family,
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


@pytest.mark.slow
@requires_huashu_sidecar
class TestOutsideMarkerBackdrop:
    def test_an_outside_marker_is_composited_over_what_its_item_sits_on(
        self, backdrop: Exported
    ) -> None:
        """A translucent outside marker is blended over its item's parent, not its item's box.

        Chrome lays an outside marker out before its item's border box, so the
        item's own background is never under it: beside a white item on a navy
        panel, both in ``rgba(0, 0, 0, 0.5)``, the browser paints the disc and
        the "1." navy-blended and the item's text white-blended. The fixture's
        reading of the browser is checked against a screenshot sample in the
        disc's middle. Each marker run is the colour composited over the
        panel, and each item's text the colour composited over the white,
        within 6 per channel.
        """
        panel = backdrop.geometry["panel"]["backgroundColor"]
        item_ground = backdrop.geometry["item"]["backgroundColor"]
        disc = backdrop.geometry["markers"]["lm-on-white"]
        over_panel = _composite(disc["style"]["color"], panel)
        over_item = _composite(disc["style"]["color"], item_ground)
        assert not _near(over_item, over_panel), (
            f"fixture drift: over the panel {over_panel} and over the item {over_item} are alike"
        )
        assert _near(backdrop.geometry["disc_pixel"], over_panel), (
            f"fixture drift: the browser paints the disc {backdrop.geometry['disc_pixel']}, "
            f"not {over_panel} over the panel"
        )
        shapes = backdrop.shapes

        wrong = []
        for list_id, label in BACKDROP_LISTS.items():
            marker = backdrop.geometry["markers"][list_id]
            expected = _composite(marker["style"]["color"], panel)
            found = _items_on(shapes, marker)
            assert len(found) == 1, (
                f"#{list_id}'s marker is not one text item on its browser box {_rect(marker)}:\n"
                f"{_describe(shapes)}"
            )
            for run in _text_runs(shapes[found[0]]):
                if not _near(_channels(run.color), expected):
                    wrong.append(
                        f"#{list_id}'s marker run {run.text!r} is {run.color}, not {expected}"
                    )
            _, item = _only(shapes, label, f"#{list_id}'s item")
            item_expected = _composite(backdrop.geometry["item"]["color"], item_ground)
            for run in _text_runs(item):
                if not _near(_channels(run.color), item_expected):
                    wrong.append(
                        f"#{list_id}'s item run {run.text!r} is {run.color}, not {item_expected}"
                    )
        assert not wrong, "\n".join([*wrong, _describe(shapes)])


# ---------------------------------------------------------------------------
# list-style-position: inside
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestInsideMarkers:
    def test_an_inside_marker_opens_its_items_first_line(self, kinds: Exported) -> None:
        """An inside marker the text runs on from is a token of its item's first line.

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
        """An inside disc, which a margin parts from its text, is an item of its own.

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
        """``<ol dir="rtl">``: the marker is right of its item, left-aligned at its glyphs.

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
        """``list-style-image: url(data:image/png…)``: each marker a picture at its box.

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

    @pytest.mark.parametrize("list_id", BOXED_IMAGE_LISTS)
    def test_an_image_marker_its_items_picture_holds_is_drawn_once(
        self, boxed_images: Exported, list_id: str
    ) -> None:
        """An image marker inside its item's own picture is in that picture alone.

        An item whose background is a gradient is a picture of its own box,
        which shows the marker it holds: one inside the item's box, and one
        outside it but inside the reach of the item's shadow. Exactly one
        picture holds the marker's pixels (at least 90% of the 32x32 of a 2x
        capture), it covers the marker's browser box, and the marker's middle
        is the marker's colour in it.
        """
        marker = boxed_images.geometry["markers"][list_id]
        holding = []
        for shape in boxed_images.shapes:
            if shape.kind != "picture" or not shape.image:
                continue
            image = Image.open(BytesIO(shape.image)).convert("RGBA")
            painted = sum(1 for pixel in image.getdata() if _is(pixel, IMAGE_COLOUR))
            if painted >= IMAGE_PIXEL_SHARE * IMAGE_PIXELS:
                holding.append((shape, image))
        covering = [
            (shape, image)
            for shape, image in holding
            if shape.x <= marker["x"] + RECT_TOLERANCE_PX
            and shape.y <= marker["y"] + RECT_TOLERANCE_PX
            and shape.x + shape.w >= _right(marker) - RECT_TOLERANCE_PX
            and shape.y + shape.h >= marker["y"] + marker["h"] - RECT_TOLERANCE_PX
        ]
        assert len(covering) == 1, (
            f"#{list_id}'s image marker {_rect(marker)}: {len(covering)} pictures over it hold its "
            f"pixels, expected exactly one:\n{_describe(boxed_images.shapes)}"
        )
        shape, image = covering[0]
        column = int((marker["x"] + marker["w"] / 2 - shape.x) / shape.w * image.width)
        row = int((marker["y"] + marker["h"] / 2 - shape.y) / shape.h * image.height)
        assert _is(image.getpixel((column, row)), IMAGE_COLOUR), (
            f"#{list_id}'s picture does not show the marker at the marker's middle: "
            f"{image.getpixel((column, row))}"
        )


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
        A guard that holds whether or not markers are drawn: the markers honour
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
        is drawn in the list's start padding beside it. A guard that holds
        whether or not markers are drawn.
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
        A guard on the slide's pseudo-element bullets, which no marker doubles.
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
        """No paragraph carries ``a:buChar``, ``a:buAutoNum`` or ``a:buBlip``.

        Each text marker the browser renders is on the slide as text on its
        marker (an item of its own, or its item's first-line token), so a deck
        whose markers are native bullets, or are missing, fails. Slides 16 and
        09 and the image slide have no text marker: for them this is a guard
        that holds whether or not markers are drawn.
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
    """Export one complete document, bounded so a hang fails in seconds, its model whole.

    A slide model the model check dropped part of fails the export
    (``export_documents``): the hostile twin and its benign one losing the
    same item would otherwise still compare equal.
    """
    monkeypatch.setattr(
        pptx_from_html_huashu, "SIDECAR_TIMEOUT_SECONDS", HOSTILE_EXPORT_TIMEOUT_SECONDS
    )
    return export_documents([html], monkeypatch=monkeypatch, title="snapshot list markers")


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


# ---------------------------------------------------------------------------
# Nothing the export adds stays in the page it reads
# ---------------------------------------------------------------------------


def _leftover_runs(pptx: bytes) -> list[tuple[str, str | None]]:
    """Every text run of the slide, (text, colour), in spTree order."""
    return [
        (run.text, run.color)
        for shape in slide_shapes(pptx)
        if shape.kind == "text"
        for run in _text_runs(shape)
    ]


@pytest.mark.slow
@requires_huashu_sidecar
class TestNothingLeftInThePage:
    def _browser_colours(self, document: str) -> dict:
        """What the browser paints each list's markers and items in, guarded against green."""
        colours = {}
        for list_id in LEFTOVER_LISTS:
            markers = browser_each_pseudo(document, f"#{list_id} li", "marker")
            item = browser_style(document, f"#{list_id} li")
            colours[list_id] = {"markers": markers, "item": _hex(item["color"])}
            painted = [_hex(marker["style"]["color"]) for marker in markers] + [
                colours[list_id]["item"]
            ]
            assert LEFTOVER_GREEN not in painted, (
                f"fixture drift: the browser paints #{list_id} green ({painted}) before any export"
            )
        return colours

    def test_no_probe_is_left_in_the_page_while_it_is_read(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A rule that turns lists green while anything follows body leaves the export's colours.

        ``html > body:not(:last-child) li { color: #00FF00 !important }``
        matches only while a node the export added to the document element (a
        marker probe, the pristine-realm iframe) is still there. Every such
        node is taken off before the walk reads a style, so the outside
        markers, the inside marker's token and every item's text keep the
        colours the browser paints them in, and no run on the slide is green.
        """
        css = DECK_CSS + KINDS_CSS + LEFTOVER_DETECTOR_CSS
        colours = self._browser_colours(_document(LEFTOVER_BODY, css=css))
        pptx = _export(LEFTOVER_BODY, monkeypatch, css=css)
        shapes = slide_shapes(pptx)

        wrong = [
            f"run {text!r} is green"
            for text, colour in _leftover_runs(pptx)
            if colour == LEFTOVER_GREEN
        ]
        for marker, label in zip(
            colours["lm-left-outside"]["markers"], LEFTOVER_LISTS["lm-left-outside"]
        ):
            found = _items_on(shapes, marker)
            assert len(found) == 1, f"the {label!r} item's marker is {found}:\n{_describe(shapes)}"
            for run in _text_runs(shapes[found[0]]):
                if run.color != _hex(marker["style"]["color"]):
                    wrong.append(f"the {label!r} item's marker run {run.text!r} is {run.color}")
        inside_marker = colours["lm-left-inside"]["markers"][0]
        _, inside = _only(shapes, "Inside one", "the inside item")
        line = "".join(run.text for run in inside.paras[0].runs) if inside.paras else ""
        if not line.startswith(_trimmed(inside_marker)):
            wrong.append(f"the inside item's line {line!r} does not open with its marker")
        painted = {_hex(inside_marker["style"]["color"]), colours["lm-left-inside"]["item"]}
        for run in _text_runs(inside):
            if run.color not in painted:
                wrong.append(f"the inside item's run {run.text!r} is {run.color}, not {painted}")
        for list_id, labels in LEFTOVER_LISTS.items():
            for label in labels:
                _, item = _only(shapes, label, f"the {label!r} item")
                for run in _text_runs(item):
                    if label in run.text and run.color != colours[list_id]["item"]:
                        wrong.append(f"the {label!r} item's run {run.text!r} is {run.color}")
        assert not wrong, "\n".join([*wrong, _describe(shapes)])

    def test_a_page_that_takes_away_removal_keeps_its_colours(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Slide script that disables ``remove`` and ``removeChild`` cannot keep a probe in.

        With the same green-while-anything-follows-body rule, a page whose
        script replaces ``Element.prototype.remove`` and
        ``Node.prototype.removeChild`` with ones that do nothing exports every
        run in the colour its benign twin (the same page without the script)
        exports it in, and none is green: the export adds and removes its
        nodes through a realm no page script has run in.
        """
        css = DECK_CSS + KINDS_CSS + LEFTOVER_DETECTOR_CSS
        self._browser_colours(_document(LEFTOVER_BODY, css=css))
        benign, failures = export_slides([LEFTOVER_BODY], css=css, monkeypatch=monkeypatch)
        assert failures == [] and benign, f"the benign twin did not export: {failures}"
        hostile, failures = export_slides(
            [_with_script(LEFTOVER_BODY, DISABLE_REMOVAL_SCRIPT)], css=css, monkeypatch=monkeypatch
        )
        assert failures == [] and hostile, f"the page without removal did not export: {failures}"

        benign_runs = _leftover_runs(benign)
        hostile_runs = _leftover_runs(hostile)
        assert all(colour != LEFTOVER_GREEN for _, colour in benign_runs), (
            f"the benign twin exports green runs: {benign_runs}"
        )
        assert hostile_runs == benign_runs, (
            f"a page without removal exports its runs as {hostile_runs}; its benign twin as "
            f"{benign_runs}"
        )


# Deck rules on the document element's div children, which are the offscreen
# probes the text metrics are read with (snapshot_text_metrics.mjs
# measureProbes) and nothing on a slide: one that hides the probes, one that
# restyles their text, and two that take their width away.
PROBE_RULES = {
    "hidden": "display: none",
    "restyled": "font-size: 40px; letter-spacing: 6px; font-family: serif",
    "size-contained": "contain: size",
    "scaled": "transform: scale(0)",
}
PROBED_CSS = DECK_CSS + KINDS_CSS + "\n#lm-left-inside { list-style-position: inside; }\n"
PROBED_TWIN_TEXT = "AVATAR Toyota WAVE"
PROBED_TWIN_FACES = ("Semi;colon Sans", "Plain Sans")


def _probe_rule_css(rule: str) -> str:
    """``html > div`` set to each declaration of ``rule``, every one ``!important``."""
    declarations = "; ".join(f"{part.strip()} !important" for part in rule.split(";"))
    return f"\nhtml > div {{ {declarations} }}\n"


@pytest.mark.slow
@requires_huashu_sidecar
class TestProbeStyle:
    @pytest.mark.parametrize("rule", list(PROBE_RULES.values()), ids=list(PROBE_RULES))
    def test_a_deck_rule_on_the_probes_leaves_the_slide_as_it_is_without_it(
        self, monkeypatch: pytest.MonkeyPatch, rule: str
    ) -> None:
        """A deck's ``html > div { … !important }`` exports the slide its twin without it does.

        The rule matches no element of the slide (each list item's box is the
        same with and without it), only the probes the export adds to the
        document element. The probes' own style is ``!important``, which a
        style attribute's declaration wins with over any rule's, so the slide
        with the rule (an outside and an inside list, and their text) exports
        a whole artifact equal to its twin's. A probe style a rule outranks
        measures nothing hidden, contained or scaled to nothing, and the
        restyled one the wrong face, so the markers, the line spacing and the
        tracking move.
        """
        css = PROBED_CSS + _probe_rule_css(rule)
        benign_document = _document(LEFTOVER_BODY, css=PROBED_CSS)
        ruled_document = _document(LEFTOVER_BODY, css=css)
        assert browser_each_rect(ruled_document, "li") == browser_each_rect(benign_document, "li"), (
            "fixture drift: the rule moves the slide's own list items"
        )
        benign = _export(LEFTOVER_BODY, monkeypatch, css=PROBED_CSS)
        ruled = _export(LEFTOVER_BODY, monkeypatch, css=css)

        assert structural_manifest(ruled) == structural_manifest(benign), (
            f"html > div {{ {rule} }} changes the export:\nruled:\n{_describe(slide_shapes(ruled))}\n"
            f"benign:\n{_describe(slide_shapes(benign))}"
        )

    def test_a_family_named_with_a_semicolon_is_probed_in_its_face(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A webfont named "Semi;colon Sans" is tracked as its twin of another name is.

        Two paragraphs of the same text, each in a webfont the page loads from
        the same local face: "Semi;colon Sans" and "Plain Sans". The probes
        that measure their tracking set each run's own face. A semicolon
        inside a quoted family name ends no declaration of a probe's style, so
        both runs are written in their own faces with the same size and
        tracking. Splitting the style there renames the probe's face to one
        the page did not load, and its run is tracked to another face's widths.
        """
        faces = "".join(
            f"@font-face {{ font-family: '{name}'; "
            "src: local('Helvetica'), local('Arial'), local('Liberation Sans'); }"
            for name in PROBED_TWIN_FACES
        )
        paragraph = (
            '<p style="font-family: &quot;%s&quot;, &quot;DM Sans&quot;; font-size: 28px;">'
            f"{PROBED_TWIN_TEXT}</p>"
        )
        body = (
            f'<div class="slide"><style>{faces}</style>'
            + "".join(paragraph % name for name in PROBED_TWIN_FACES)
            + "</div>"
        )
        shapes = slide_shapes(_export(body, monkeypatch))
        boxes = sorted(
            (shape for shape in shapes if shape.kind == "text" and PROBED_TWIN_TEXT in shape.text),
            key=lambda shape: shape.y,
        )
        assert len(boxes) == 2, f"expected the two paragraphs' boxes:\n{_describe(shapes)}"
        semicolon, plain = (
            [(run.typeface, run.size_pt, run.spc_pt) for run in _text_runs(box)] for box in boxes
        )
        assert plain and all(spc != 0 for _, _, spc in plain), (
            f"fixture drift: the plain twin is written untracked: {plain}"
        )
        assert [typeface for typeface, _, _ in semicolon] == [PROBED_TWIN_FACES[0]] * len(semicolon)
        assert [run[1:] for run in semicolon] == [run[1:] for run in plain]


# ---------------------------------------------------------------------------
# What the export cannot read of a marker it says
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestMarkerReadFailures:
    @pytest.mark.parametrize(
        "script", [LYING_PROBES_SCRIPT, LYING_ZERO_PROBES_SCRIPT], ids=["nan", "zero"]
    )
    def test_marker_widths_that_cannot_be_measured_are_announced(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], script: str
    ) -> None:
        """A page that lies about its probes' sizes exports its markers, and the export says so.

        Its slide script makes every offscreen probe (left: -10000px) report
        NaN sizes, or zero sizes, as a probe the page hides measures: a probe
        of text that paints measured no width, so neither counts as measured.
        No marker's advance can be measured. The markers still export as text
        items on their browser boxes, one ``[html2pptx] list markers:`` line
        counts the markers left unmeasured, and an ``[html2pptx] text metric
        probes:`` line says the slide's line spacing went unmeasured.
        Counting a zero width as measured places every marker at no advance
        and says nothing.
        """
        css = DECK_CSS + KINDS_CSS
        markers = browser_each_pseudo(
            _document(UNMEASURED_BODY, css=css), "#lm-unmeasured li", "marker"
        )
        _guard_markers(markers, ("1. ", "2. "), "the unmeasured list")
        capsys.readouterr()
        pptx, failures = export_slides(
            [_with_script(UNMEASURED_BODY, script)],
            css=css,
            monkeypatch=monkeypatch,
            debug_text=True,
        )
        stderr = capsys.readouterr().err
        assert failures == [] and pptx, f"the lying page did not export: {failures}"

        lines = [line for line in stderr.splitlines() if UNMEASURED_LINE in line]
        assert len(lines) == 1 and "2 " in lines[0], (
            f"expected one {UNMEASURED_LINE!r} line counting 2 markers, got {lines}"
        )
        probe_lines = [line for line in stderr.splitlines() if UNMEASURED_PROBES_LINE in line]
        assert [line for line in probe_lines if UNMEASURED_SPACING in line], (
            f"no {UNMEASURED_PROBES_LINE!r} line says the line spacing went unmeasured: {probe_lines}"
        )
        shapes = slide_shapes(pptx)
        for marker in markers:
            on = [shapes[position].text for position in _items_on(shapes, marker)]
            assert on == [_trimmed(marker)], (
                f"the unmeasured marker {marker['text']!r} is drawn as {on}:\n{_describe(shapes)}"
            )

    def test_unreadable_marker_boxes_leave_the_markers_out_and_say_so(self, tmp_path: Path) -> None:
        """A session whose box reads of ::marker nodes reject exports the slide without them.

        Every ``DOM.getBoxModel`` of a marker node fails, and nothing else does.
        No marker is drawn (no text item reads as one), the ``[html2pptx]
        pseudo-elements:`` count line says the box reads failed, the items'
        text exports, and the slide's ``::before`` is still read and walked.
        """
        document = tmp_path / "slide.html"
        css = DECK_CSS + KINDS_CSS + UNREAD_BOXES_CSS
        document.write_text(_document(UNREAD_BOXES_BODY, css=css), encoding="utf-8")

        result = node_json(UNREAD_BOXES_SCRIPT % {"document": json.dumps(str(document))})

        lines = [line for line in result["lines"] if UNREAD_BOXES_LINE in line]
        assert len(lines) == 1 and "2 box read(s) failed" in lines[0], (
            f"expected one count line with 2 failed box reads, got {lines}"
        )
        assert result["summary"]["pseudoElements"] == {"read": 1, "walked": 1}, (
            f"the ::before was not read and walked alone: {result['summary']['pseudoElements']}"
        )
        shapes = slide_shapes(base64.b64decode(result["pptx"]))
        marker_like = [
            shape.text
            for shape in shapes
            if shape.kind == "text" and MARKER_LIKE.match(_normalised(shape.text))
        ]
        assert marker_like == [], f"markers whose boxes were unread are drawn: {marker_like}"
        for label in ("Unread one", "Unread two"):
            _, item = _only(shapes, label, f"the {label!r} item")
            assert _normalised(item.text) == label, f"the {label!r} item reads {item.text!r}"
