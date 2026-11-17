"""Snapshot engine: visibility, clipping and off-slide content.

The snapshot engine (``TELLR_EXPORT_ENGINE=snapshot``) emits only what the
browser shows (spec §3 *Visibility*, RC10). An element is skipped when it is
``visibility: hidden``, at cumulative opacity 0, entirely outside the slide, or
clipped to under 2 px by ``clip``, ``clip-path`` or an ``overflow`` ancestor
(the visually-hidden pattern). The walk carries a clip rect down the tree,
starting from the slide rect and narrowed by the padding box of every
``overflow`` ancestor and by ``clip: rect()`` on absolutely positioned ones:

* a shape is cut to that clip, so a box spilling out of an ``overflow: hidden``
  card is drawn only where the card shows it, and a decoration hanging past the
  slide's right edge stops at the edge. A cut plain rect stays a preset rect;
  a cut shape a rect cannot draw (a disc, a rounded or bordered card) is a
  custom-geometry path, the part of it the clip shows, with its border drawn
  only where its own edge remains;
* a text token whose rect meets the clip by less than 2 px is dropped, so a
  screen-reader-only table and the lines a card cuts off are not slide text;
* content cut to nothing, or lying wholly off the slide, produces no shape, no
  text and no picture, and its slide still exports.

Guards pin what a clip must NOT remove: a ``visibility: visible`` child of a
hidden parent shows, a zero-height box without ``overflow`` clipping keeps the
content it overflows with, and an absolutely positioned box whose containing
block lies outside an ``overflow: hidden`` ancestor is not clipped by it (CSS
2.1 §11.1.1). Hidden words that keep their room in a line (``visibility:
hidden``, ``opacity: 0``) leave the visible text after them where the browser
drew it.

Every case is anchored in the browser's own layout of the very same document:
``browser_rect`` and ``browser_padding_box`` for where a clip cuts,
``browser_line_boxes`` for the lines a clip keeps, and ``browser_hit_id`` (hit
testing, which honours every clip) to prove that the browser itself hides, or
shows, what a test says it does. Corpus slides are loaded from
``tests/fixtures/export_fidelity`` by prefix (PLAN-CORRECTIONS C4).

Hidden words and the text-loss oracle: the engine records the words it drops in
``model.reference.hiddenText``, which is internal to the sidecar. Until the
``[html2pptx] slide summary`` line carries it (Task 12, PLAN-CORRECTIONS C8)
this module asserts what is observable: the hidden words are in no exported text
item, and the harness's oracle reports nothing visible as missing.

Gating matches the sibling export suites: needs node, the extracted sidecar
``node_modules`` and a local Chrome/Chromium (skipped otherwise).
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from lxml import etree

from tests.fixtures.export_snapshot_support import (
    DECK_CSS,
    EMU_PER_PX,
    NAMESPACES,
    Shape,
    browser_hit_id,
    browser_line_boxes,
    browser_padding_box,
    browser_rect,
    browser_text,
    corpus_document,
    export_corpus,
    export_slides,
    requires_huashu_sidecar,
    slide_document,
    slide_shape_elements,
    slide_shapes,
    text_loss,
)
from tests.unit.test_pptx_from_html_huashu_image_src import PNG_DATA_URI

# The slide the engine exports: 1280x720 CSS px from the top left.
SLIDE_RECT = {"x": 0.0, "y": 0.0, "w": 1280.0, "h": 720.0}
# Task 1's box tolerance: an emitted box matches the browser's within 0.5 px.
RECT_TOLERANCE_PX = 0.5
# Task 2's placement of left-aligned text: x is the browser's text left within this.
TEXT_LEFT_TOLERANCE_PX = 0.5
# A cut line's text is placed within this of the browser's x (coordinator ruling
# on Task 5 concern 1, which this module applies to hidden words).
CUT_TEXT_X_TOLERANCE_PX = 1.0
# Spec §3 Visibility: content clipped to under 2 px is not shown.
MINIMUM_VISIBLE_PX = 2.0
# Punctuation around a word that is not part of it ("(fictional)", "years.").
WORD_PUNCTUATION = "()[]{}.,;:!?\"'"

# Every synthetic slide carries this paragraph, so an export that drops
# everything cannot pass for one that drops only the hidden content.
LEAD_TEXT = "Quarterly results at a glance"
LEAD = f'<p id="lead" style="font-size: 20px;">{LEAD_TEXT}</p>'

# Fixture 03's screen-reader-only data table (deck.css .sr-only: position
# absolute, 1 px box, overflow hidden, clip: rect(0, 0, 0, 0)). A table is never
# narrower than its content, so its border box stays 114x77 px and only the clip
# hides it.
SR_ONLY_TABLE = "table.sr-only"
SR_ONLY_WORDS = ("Year", "Revenue", "FY20", "905", "FY24", "1,240")

# The hidden content of the visually-hidden variants: a header cell with its own
# fill, cell text, a raster picture and an inline SVG icon. Its words appear
# nowhere else on the slide.
HIDDEN_WORDS = ("Quokka", "Zebu", "4,812")
HIDDEN_CELL_FILL = "C0FFEE"
HIDDEN_TABLE = (
    '<table id="hidden-table" style="font-size: 18px;"><tr>'
    f'<th id="hidden-cell" style="background: #{HIDDEN_CELL_FILL}; padding: 6px 12px;">Quokka</th>'
    '<td style="padding: 6px 12px;">Zebu 4,812</td></tr></table>'
    f'<img src="{PNG_DATA_URI}" width="40" height="40" alt="">'
    '<svg width="24" height="24"><circle cx="12" cy="12" r="10" fill="#BADA55"/></svg>'
)


@dataclass(frozen=True)
class VisuallyHidden:
    """One way of hiding content from sight but not from a screen reader."""

    body: str
    # The element whose centre the browser must not show (its hit-test target).
    probe: str
    # (selector, text): elements holding only visible text, each one browser line
    # reading its text, which together make up the lead paragraph. A line read
    # over the hidden content itself would count its characters too, because
    # clipped text still has rects.
    lead_parts: tuple[tuple[str, str], ...] = (("#lead", LEAD_TEXT),)


def _hidden_wrapper(style: str) -> VisuallyHidden:
    return VisuallyHidden(
        body=(
            f'<div class="slide">{LEAD}'
            f'<div id="hidden-wrapper" style="{style}">{HIDDEN_TABLE}</div></div>'
        ),
        probe="#hidden-cell",
    )


# Each variant hides the same content, by one mechanism or by the full pattern.
VISUALLY_HIDDEN = {
    # The classic pattern with the space-separated clip syntax.
    "sr-only-clip-rect-spaces": _hidden_wrapper(
        "position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; "
        "overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;"
    ),
    # The modern pattern: clip-path in place of the deprecated clip.
    "sr-only-clip-path-inset": _hidden_wrapper(
        "position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; "
        "overflow: hidden; clip-path: inset(50%); white-space: nowrap; border: 0;"
    ),
    # Each mechanism on its own, on a full-size box: only it can hide the content.
    "clip-rect-alone": _hidden_wrapper(
        "position: absolute; left: 88px; top: 300px; clip: rect(0 0 0 0);"
    ),
    "clip-path-inset-alone": _hidden_wrapper("clip-path: inset(50%);"),
    "one-pixel-overflow-alone": _hidden_wrapper(
        "position: absolute; width: 1px; height: 1px; overflow: hidden; white-space: nowrap;"
    ),
    # The deck's own .sr-only on a span inside a visible sentence ("Read more
    # <span class=sr-only>about …</span>"): out of flow, it leaves the line whole.
    "sr-only-span-in-a-sentence": VisuallyHidden(
        body=(
            '<div class="slide">'
            '<p id="lead" style="font-size: 20px;"><span id="lead-start">Quarterly results</span>'
            '<span id="hidden-span" class="sr-only"> for Quokka Zebu 4,812</span>'
            ' <span id="lead-end">at a glance</span></p></div>'
        ),
        probe="#hidden-span",
        lead_parts=(("#lead-start", "Quarterly results"), ("#lead-end", "at a glance")),
    ),
}
HIDDEN_IDS = {"hidden-wrapper", "hidden-table", "hidden-cell", "hidden-span"}

# A card hidden as a whole: its fill, border, shadow, an inline chip, a raster
# picture, an SVG icon and a child that sets opacity 1 for itself.
HIDDEN_CARD_FILLS = ("ABCDEF", "FACADE", "C0FFE3")
HIDDEN_CARD_LINE = "123456"
HIDDEN_CARD_WORDS = ("Ghost", "heading", "chipword", "Phantom", "child")
HIDDEN_CARD = (
    '<div class="slide">' + LEAD + '<div id="hidden-card" style="{hide} width: 420px; '
    "padding: 16px; background: #ABCDEF; border: 2px solid #123456; border-radius: 8px; "
    'box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2); font-size: 20px;">'
    'Ghost heading <span style="background: #FACADE; padding: 0 4px;">chipword</span> '
    f'<img src="{PNG_DATA_URI}" width="40" height="40" alt=""> '
    '<svg width="24" height="24"><circle cx="12" cy="12" r="10" fill="#BADA55"/></svg>'
    '<div style="opacity: 1; background: #C0FFE3; padding: 4px;">Phantom child</div>'
    "</div></div>"
)
HIDING_STYLES = {"visibility-hidden": "visibility: hidden;", "opacity-zero": "opacity: 0;"}

# visibility is inherited, and a descendant may set it back to visible.
SHOWN_CHILD_FILL = "FEDCBA"
HIDDEN_PARENT_FILL = "ABCDEF"
HIDDEN_PARENT_BODY = (
    '<div class="slide">'
    '<div id="hidden-parent" style="visibility: hidden; width: 420px; padding: 16px; '
    f'background: #{HIDDEN_PARENT_FILL}; font-size: 20px;">Hidden caption'
    '<div id="shown-child" style="visibility: visible; '
    f'background: #{SHOWN_CHILD_FILL}; padding: 8px;">Shown child</div>'
    "</div></div>"
)

# A hidden word keeps its room in the line: the text after it starts past it.
HIDDEN_WORD_SENTENCE = (
    '<div class="slide">'
    '<p id="sentence" style="font-size: 20px;">'
    '<span id="before-hidden">Revenue</span> '
    '<span id="hidden-word" style="{hide}">secretword</span> '
    '<span id="after-hidden">grew twelve percent</span></p>'
    "</div>"
)
HIDDEN_WORD = "secretword"
SENTENCE_WORDS = ("Revenue", "grew", "twelve", "percent")

# Content a clip cuts to nothing: a filled box with text, a raster picture and an icon.
CLIPPED_FILL = "00A972"
CLIPPED_WORDS = ("Clipped", "Quokka")


def _clipped_content(position: str = "") -> str:
    return (
        f'<div id="clipped" style="{position} background: #{CLIPPED_FILL}; padding: 8px; '
        'font-size: 20px; color: #FFFFFF;">Clipped Quokka '
        f'<img src="{PNG_DATA_URI}" width="40" height="40" alt=""> '
        '<svg width="24" height="24"><circle cx="12" cy="12" r="10" fill="#BADA55"/></svg></div>'
    )


ZERO_AREA_CLIPS = {
    # A collapsed accordion panel: height 0 and overflow hidden.
    "collapsed-to-zero-height": (
        f'<div class="slide">{LEAD}'
        '<div id="clipper" style="position: absolute; left: 600px; top: 140px; width: 300px; '
        f'height: 0; overflow: hidden;">{_clipped_content()}</div></div>'
    ),
    # Content placed below the bottom of the box that clips it, still on the slide.
    "scrolled-out-of-its-box": (
        f'<div class="slide">{LEAD}'
        '<div id="clipper" style="position: absolute; left: 600px; top: 140px; width: 300px; '
        'height: 100px; overflow: hidden; background: #F9F7F4;">'
        f"{_clipped_content('position: absolute; left: 20px; top: 140px; width: 240px;')}"
        "</div></div>"
    ),
    # Inside its nearest clip but outside the outer one: the clip is the
    # intersection of every overflow ancestor, not the nearest alone.
    "outside-the-outer-of-two-clips": (
        f'<div class="slide">{LEAD}'
        '<div id="outer" style="position: absolute; left: 100px; top: 140px; width: 300px; '
        'height: 200px; overflow: hidden;">'
        '<div id="clipper" style="position: absolute; left: 200px; top: 20px; width: 400px; '
        'height: 150px; overflow: hidden;">'
        f"{_clipped_content('position: absolute; left: 150px; top: 20px; width: 200px;')}"
        "</div></div></div>"
    ),
}

# A box spilling out of a bordered, padded frame on the right and at the bottom.
SPILL_FILL = "FF3621"
FRAME_BORDER_PX = 6.0
PARTIAL_CLIP = (
    '<div class="slide">'
    '<div id="frame" style="position: absolute; left: 100px; top: 120px; width: 300px; '
    f"height: 160px; border: {FRAME_BORDER_PX:g}px solid #1B3139; padding: 10px; "
    'overflow: {overflow}; background: #F9F7F4;">'
    '<div id="spill" style="width: 420px; height: 240px; margin-left: 40px; margin-top: 30px; '
    f'background: #{SPILL_FILL};"></div>'
    "</div></div>"
)
CLIPPING_OVERFLOWS = ("hidden", "clip")

# A paragraph taller than its fixed-height window: the window shows two lines.
CLIPPED_LINES = (
    '<div class="slide">'
    '<div id="window" style="position: absolute; left: 600px; top: 300px; width: 420px; '
    'height: 56px; overflow: hidden; font-size: 20px; line-height: 28px;">'
    '<p id="window-text" style="margin: 0;">Line one of the clipped paragraph runs on and on '
    "so that it wraps across several lines in the window box here</p>"
    "</div></div>"
)

# A zero-height box that does not clip: what overflows it shows.
OVERFLOWING_FILL = "00A973"
UNCLIPPED_ZERO_HEIGHT = (
    f'<div class="slide">{LEAD}'
    '<div id="zero" style="height: 0;">'
    f'<div id="overflowing" style="width: 300px; background: #{OVERFLOWING_FILL}; padding: 8px; '
    'font-size: 20px;">Overflowing child</div>'
    "</div></div>"
)

# An absolute box whose containing block (the positioned .slide) is outside the
# static overflow: hidden box it sits in, so that box does not clip it.
ESCAPED_FILL = "00A974"
ESCAPED_CLIP = (
    '<div class="slide">'
    '<div id="static-clipper" style="width: 200px; height: 60px; overflow: hidden; '
    'background: #F9F7F4;">'
    '<div id="escaped" style="position: absolute; left: 600px; top: 400px; width: 240px; '
    f'padding: 8px; background: #{ESCAPED_FILL}; font-size: 20px;">Escaped badge</div>'
    "</div></div>"
)

# A decorative bar hanging 40 px past the slide's right edge.
DECORATION_FILL = "FF3621"
OFF_EDGE_DECORATION = (
    '<div class="slide"{root_style}>' + LEAD + '<div id="decoration" style="position: absolute; '
    f'right: -40px; top: 120px; width: 160px; height: 24px; background: #{DECORATION_FILL};">'
    "</div></div>"
)
# The deck's .slide clips its own overflow; a root that does not leaves only the
# slide itself to clip.
SLIDE_ROOTS = {"root-clips": "", "root-overflow-visible": ' style="overflow: visible;"'}

# A filled box with text, a raster picture and an icon, wholly off the slide.
OFFSTAGE_FILL = "2B4A57"
OFFSTAGE_WORDS = ("Offstage", "Quokka")
OFFSTAGE_PLACES = {
    "below": "left: 80px; top: 740px;",
    "above": "left: 80px; top: -200px;",
    "right": "left: 1320px; top: 200px;",
    "left": "left: -500px; top: 200px;",
}
OFFSTAGE = (
    '<div class="slide"{root_style}>' + LEAD + '<div id="offstage" style="position: absolute; '
    "{place} width: 400px; height: 60px; background: #" + OFFSTAGE_FILL + "; color: #FFFFFF; "
    'font-size: 20px;">Offstage Quokka '
    f'<img src="{PNG_DATA_URI}" width="40" height="40" alt=""> '
    '<svg width="24" height="24"><circle cx="12" cy="12" r="10" fill="#BADA55"/></svg></div>'
    "</div>"
)
OFFSTAGE_CASES = {
    # The brief's case on the deck's own slide root.
    "below-root-clips": ("below", SLIDE_ROOTS["root-clips"]),
    # Every side, on a root that does not clip, so only the slide rect can.
    **{
        f"{side}-root-overflow-visible": (side, SLIDE_ROOTS["root-overflow-visible"])
        for side in OFFSTAGE_PLACES
    },
}

# A disc hanging 80 px past the slide's right edge (fixture 12's decorative circle).
DISC_FILL = "00A975"
DISC = (
    '<div class="slide">' + LEAD + '<div id="disc" style="position: absolute; right: -80px; '
    f'top: 220px; width: 240px; height: 240px; border-radius: 50%; background: #{DISC_FILL};">'
    "</div></div>"
)

# A bordered, rounded card spilling out of the bottom of an overflow: hidden window.
CARD_FILL = "F2E8D5"
CARD_LINE = "5A2D82"
CARD_BORDER_PX = 4.0
CUT_CARD = (
    '<div class="slide">'
    '<div id="window" style="position: absolute; left: 120px; top: 140px; width: 420px; '
    'height: 220px; overflow: hidden;">'
    '<div id="card" style="width: 300px; height: 260px; margin: 20px 0 0 30px; '
    f"border: {CARD_BORDER_PX:g}px solid #{CARD_LINE}; border-radius: 16px; "
    f'background: #{CARD_FILL};"></div>'
    "</div></div>"
)

# Plain unbordered rects a clip cuts: the spill out of an overflow: hidden frame,
# and the decoration past the right edge of a slide root that does not clip.
CUT_PLAIN_RECTS = {
    "spill-out-of-a-frame": (PARTIAL_CLIP.format(overflow="hidden"), "#spill", SPILL_FILL),
    "past-the-slide-edge": (
        OFF_EDGE_DECORATION.format(root_style=SLIDE_ROOTS["root-overflow-visible"]),
        "#decoration",
        DECORATION_FILL,
    ),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _export_one(body: str, monkeypatch: pytest.MonkeyPatch) -> bytes:
    pptx, failures = export_slides([body], css=DECK_CSS, engine="snapshot", monkeypatch=monkeypatch)
    assert failures == [], f"the export rejected the slide: {failures}"
    assert pptx, "the export produced no .pptx bytes"
    return pptx


def _document(body: str) -> str:
    """The document ``_export_one`` exported (``export_slides`` names slide 1 ``snapshot-1``)."""
    return slide_document(body, css=DECK_CSS, slide_id="snapshot-1")


@pytest.fixture(scope="module")
def fixture_03_pptx() -> Iterator[bytes]:
    """Corpus slide 03 exported once through the snapshot engine."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        pptx, failures = export_corpus(["03"], monkeypatch=monkeypatch, engine="snapshot")
    assert failures == [], f"the export rejected corpus slide 03: {failures}"
    yield pptx


def _normalised(text: str) -> str:
    return " ".join(text.split())


def _words(text: str) -> list[str]:
    """The whitespace-separated words of ``text``, without the punctuation around them."""
    return [word for word in (token.strip(WORD_PUNCTUATION) for token in text.split()) if word]


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
            detail = f"text={shape.text[:70]!r}"
        else:
            detail = f"{shape.geometry} fill={shape.fill} line={shape.line}"
        lines.append(f"  [{position}] {shape.kind} box={_box(shape)} {detail}")
    return "\n".join(lines) or "  (no shapes)"


def _slide_texts(shapes: list[Shape]) -> list[tuple[str, str]]:
    """(where, text) of every piece of slide text: each text item and each table cell."""
    texts = []
    for position, shape in enumerate(shapes):
        if shape.kind == "text":
            texts.append((f"text item [{position}] at {_box(shape)}", shape.text))
        if shape.table is not None:
            for row_number, row in enumerate(shape.table.rows):
                for column_number, cell in enumerate(row):
                    texts.append(
                        (f"table [{position}] cell r{row_number}c{column_number}", cell.text)
                    )
    return texts


def _slide_fills(shapes: list[Shape]) -> list[tuple[str, str]]:
    """(where, RRGGBB) of every fill on the slide: shapes, pictures, text items and table cells."""
    fills = []
    for position, shape in enumerate(shapes):
        if shape.fill is not None:
            fills.append((f"{shape.kind} [{position}] at {_box(shape)}", shape.fill))
        if shape.table is not None:
            for row_number, row in enumerate(shape.table.rows):
                for column_number, cell in enumerate(row):
                    if cell.fill is not None:
                        fills.append(
                            (f"table [{position}] cell r{row_number}c{column_number}", cell.fill)
                        )
    return fills


def _assert_no_words(shapes: list[Shape], words: tuple[str, ...], what: str) -> None:
    """None of ``words`` is a word of any slide text: they are not exported as text."""
    leaks = [
        (where, sorted(set(_words(text)) & set(words)), text)
        for where, text in _slide_texts(shapes)
        if set(_words(text)) & set(words)
    ]
    assert leaks == [], (
        f"{what}: the hidden words {list(words)} are exported as slide text:\n"
        + "\n".join(f"  {where} has {found}: {text!r}" for where, found, text in leaks)
        + f"\n{_describe(shapes)}"
    )


def _assert_not_filled(shapes: list[Shape], fills: tuple[str, ...], what: str) -> None:
    painted = [(where, fill) for where, fill in _slide_fills(shapes) if fill in fills]
    assert painted == [], (
        f"{what}: hidden fills {list(fills)} are painted on the slide: {painted}\n"
        f"{_describe(shapes)}"
    )


def _assert_no_pictures(shapes: list[Shape], what: str) -> None:
    pictures = [
        (position, _box(shape)) for position, shape in enumerate(shapes) if shape.kind == "picture"
    ]
    assert pictures == [], (
        f"{what}: the slide shows no picture, but the export has pictures at {pictures}\n"
        f"{_describe(shapes)}"
    )


def _assert_lead_kept(shapes: list[Shape]) -> None:
    """The slide's visible lead paragraph is still one text item reading its text."""
    leads = [
        shape for shape in shapes if shape.kind == "text" and _normalised(shape.text) == LEAD_TEXT
    ]
    assert len(leads) == 1, (
        f"the visible lead paragraph {LEAD_TEXT!r} must be exported exactly once, got "
        f"{len(leads)}:\n{_describe(shapes)}"
    )


def _filled(shapes: list[Shape], fill: str, what: str) -> Shape:
    """The one non-text element filled ``fill``."""
    matches = [shape for shape in shapes if shape.kind != "text" and shape.fill == fill]
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


def _assert_at(shape: Shape, rect: dict, what: str) -> None:
    off = _off_by(shape, rect)
    expected = {key: round(value, 3) for key, value in rect.items()}
    assert all(abs(delta) <= RECT_TOLERANCE_PX for delta in off.values()), (
        f"{what}: the emitted shape {_box(shape)} differs from the expected box {expected} by "
        f"{off} (tolerance {RECT_TOLERANCE_PX} px)"
    )


def _intersection(a: dict, b: dict) -> dict | None:
    """The overlap of two ``{"x", "y", "w", "h"}`` rects; None when they do not overlap."""
    left = max(a["x"], b["x"])
    top = max(a["y"], b["y"])
    right = min(a["x"] + a["w"], b["x"] + b["w"])
    bottom = min(a["y"] + a["h"], b["y"] + b["h"])
    if right <= left or bottom <= top:
        return None
    return {"x": left, "y": top, "w": right - left, "h": bottom - top}


def _contains(outer: dict, inner: dict) -> bool:
    return (
        outer["x"] <= inner["x"]
        and outer["y"] <= inner["y"]
        and inner["x"] + inner["w"] <= outer["x"] + outer["w"]
        and inner["y"] + inner["h"] <= outer["y"] + outer["h"]
    )


def _centre(rect: dict) -> tuple[float, float]:
    return rect["x"] + rect["w"] / 2, rect["y"] + rect["h"] / 2


def _single_line(document: str, selector: str) -> dict:
    lines = browser_line_boxes(document, selector)
    assert len(lines) == 1, f"fixture drift: {selector} renders {len(lines)} lines: {lines}"
    return lines[0]


def _text_item_containing(shapes: list[Shape], fragment: str) -> Shape:
    matches = [
        shape for shape in shapes if shape.kind == "text" and fragment in _normalised(shape.text)
    ]
    assert len(matches) == 1, (
        f"expected exactly one text item containing {fragment!r}, got {len(matches)}:\n"
        f"{_describe(shapes)}"
    )
    return matches[0]


def _filled_with_xml(
    pptx: bytes, fill: str, what: str
) -> tuple[Shape, list[Shape], etree._Element]:
    """The one non-text shape filled ``fill``, every shape, and the shape's spTree XML."""
    shapes = slide_shapes(pptx)
    shape = _filled(shapes, fill, what)
    return shape, shapes, slide_shape_elements(pptx)[shapes.index(shape)]


def _custom_path(element: etree._Element, what: str) -> etree._Element:
    """The single ``a:path`` of a shape's ``a:custGeom``, its path drawn in the shape's frame."""
    paths = element.findall("p:spPr/a:custGeom/a:pathLst/a:path", NAMESPACES)
    assert len(paths) == 1, f"{what}: expected one a:custGeom path, got {len(paths)}"
    return paths[0]


def _assert_path_fills_its_frame(element: etree._Element, what: str) -> etree._Element:
    """The custGeom path's coordinate space is the shape's extent, so its points are EMU from
    the shape's top left and no renderer rescales the path inside its box."""
    path = _custom_path(element, what)
    extent = element.find("p:spPr/a:xfrm/a:ext", NAMESPACES)
    assert extent is not None, f"{what}: the shape has no a:xfrm/a:ext"
    assert (path.get("w"), path.get("h")) == (extent.get("cx"), extent.get("cy")), (
        f"{what}: the path's w/h ({path.get('w')}, {path.get('h')}) differ from the shape's "
        f"extent ({extent.get('cx')}, {extent.get('cy')})"
    )
    return path


def _path_points(path: etree._Element, shape: Shape) -> list[tuple[float, float]]:
    """Every point of ``path``, in order, in slide px (its path space is the shape's EMU)."""
    return [
        (shape.x + int(point.get("x")) / EMU_PER_PX, shape.y + int(point.get("y")) / EMU_PER_PX)
        for point in path.iterfind(".//a:pt", NAMESPACES)
    ]


def _inset(rect: dict, by: float) -> dict:
    return {
        "x": rect["x"] + by,
        "y": rect["y"] + by,
        "w": rect["w"] - 2 * by,
        "h": rect["h"] - 2 * by,
    }


# ---------------------------------------------------------------------------
# Screen-reader-only content (RC10)
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotScreenReaderOnly:
    def test_fixture_03_screen_reader_table_is_not_slide_text(self, fixture_03_pptx: bytes) -> None:
        """RC10: fixture 03's ``.sr-only`` data table ("Year Revenue / FY20 905 / FY24 1,240").

        The browser does not show it: ``clip: rect(0, 0, 0, 0)`` cuts it to
        nothing. A screen reader still reads it, so it is in the page's
        ``innerText``, the text-loss oracle's reference.

        None of its words that the slide shows nowhere else ("Year", "FY20",
        "905", "FY24", "1,240") may be a word of any exported text item or
        table cell; so no text reads "Year" or "FY20 905". "Revenue" is also the
        visible legend's "Revenue ($M)", so it is not checked.
        """
        document = corpus_document("03")
        table_text = browser_text(document, SR_ONLY_TABLE)
        assert tuple(table_text.split()) == SR_ONLY_WORDS, (
            f"fixture drift: the sr-only table reads {table_text!r}"
        )
        reference = browser_text(document)
        assert table_text in reference, (
            "fixture drift: the sr-only table is no longer in the text-loss reference "
            f"(the page's innerText): {reference!r}"
        )
        visible_words = set(_words(browser_text(document, ".slide").replace(table_text, "")))
        exclusive = tuple(word for word in SR_ONLY_WORDS if word not in visible_words)
        assert exclusive == ("Year", "FY20", "905", "FY24", "1,240"), (
            f"fixture drift: the sr-only words the slide shows nowhere else are {exclusive}"
        )

        _assert_no_words(
            slide_shapes(fixture_03_pptx), exclusive, "fixture 03's screen-reader-only table"
        )

    def test_fixture_03_loses_no_visible_word(self, fixture_03_pptx: bytes) -> None:
        """Dropping the screen-reader table drops nothing the slide shows.

        The harness's text-loss oracle (``check_text_loss``) compares the page's
        ``innerText``, which includes the sr-only table, with the exported text.
        Every word it reports missing from fixture 03 must be one of the
        table's: a clip that also cut the legend, the callout or the footer
        would show up here. (Once the slide summary carries ``hiddenText``,
        Task 12, the oracle reports none of the table's words either.)
        """
        missing = text_loss(fixture_03_pptx, [corpus_document("03")])[0]
        visible_losses = [word for word in missing if word not in SR_ONLY_WORDS]
        assert visible_losses == [], (
            f"the export lost visible words of fixture 03: {visible_losses} "
            f"(all reported missing: {missing})"
        )

    @pytest.mark.parametrize("case", sorted(VISUALLY_HIDDEN))
    def test_visually_hidden_content_exports_nothing(
        self, monkeypatch: pytest.MonkeyPatch, case: str
    ) -> None:
        """The visually-hidden pattern and each of its mechanisms alone.

        The same content (a header cell filled ``C0FFEE`` reading "Quokka", a
        cell "Zebu 4,812", a raster picture and an SVG icon) is hidden by:
        ``clip: rect(0 0 0 0)`` or ``clip-path: inset(50%)`` in the full
        1 px / overflow pattern; ``clip`` alone, ``clip-path`` alone, or a 1 px
        ``overflow: hidden`` box alone, each on content that nothing else
        hides; and the deck's ``.sr-only`` on a span inside a visible sentence.
        The browser shows none of it (hit testing at its centre finds it not).

        The export has none of its words as slide text, no ``C0FFEE`` fill and
        no picture, and the visible lead paragraph reads whole, once.
        """
        variant = VISUALLY_HIDDEN[case]
        document = _document(variant.body)
        parts = [_single_line(document, selector) for selector, _ in variant.lead_parts]
        assert [part["text"] for part in parts] == [text for _, text in variant.lead_parts], (
            f"fixture drift: the lead reads {[part['text'] for part in parts]}"
        )
        assert all(abs(part["y"] - parts[0]["y"]) < 1 for part in parts), (
            f"fixture drift: the lead's parts {parts} are not on one line"
        )
        hit = browser_hit_id(document, *_centre(browser_rect(document, variant.probe)))
        assert hit is None or hit not in HIDDEN_IDS, (
            f"fixture drift: the browser shows the hidden content ({hit!r}) at {variant.probe}"
        )

        shapes = slide_shapes(_export_one(variant.body, monkeypatch))
        _assert_no_words(shapes, HIDDEN_WORDS, case)
        _assert_not_filled(shapes, (HIDDEN_CELL_FILL,), case)
        _assert_no_pictures(shapes, case)
        _assert_lead_kept(shapes)


# ---------------------------------------------------------------------------
# Hidden and transparent content
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotHiddenAndTransparent:
    @pytest.mark.parametrize("hiding", sorted(HIDING_STYLES))
    def test_a_hidden_or_transparent_card_exports_nothing(
        self, monkeypatch: pytest.MonkeyPatch, hiding: str
    ) -> None:
        """A card at ``visibility: hidden`` or ``opacity: 0`` paints nothing.

        The card has a fill (``ABCDEF``), a uniform border (``123456``), a
        shadow, an inline chip filled ``FACADE``, a raster picture, an SVG
        icon and a child filled ``C0FFE3`` that sets ``opacity: 1`` for itself
        (opacity applies to the whole subtree, so it stays invisible). None of
        its fills or its border colour is on the slide, none of its words is
        slide text and there is no picture; the visible lead paragraph is
        exported once.
        """
        body = HIDDEN_CARD.format(hide=HIDING_STYLES[hiding])
        shapes = slide_shapes(_export_one(body, monkeypatch))

        _assert_not_filled(shapes, HIDDEN_CARD_FILLS, hiding)
        outlined = [shape for shape in shapes if shape.line == HIDDEN_CARD_LINE]
        assert outlined == [], (
            f"{hiding}: the hidden card's border {HIDDEN_CARD_LINE} is drawn:\n{_describe(shapes)}"
        )
        _assert_no_words(shapes, HIDDEN_CARD_WORDS, hiding)
        _assert_no_pictures(shapes, hiding)
        _assert_lead_kept(shapes)

    def test_a_visible_child_of_a_hidden_parent_shows(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``visibility`` is inherited and a descendant may set it back: the child shows.

        A ``visibility: hidden`` parent (fill ``ABCDEF``, text "Hidden
        caption") holds a ``visibility: visible`` child (fill ``FEDCBA``, text
        "Shown child"). The browser shows the child and not the parent, so the
        export has exactly one ``FEDCBA`` shape at the child's browser rect
        within 0.5 px and a text item reading "Shown child", but no ``ABCDEF``
        fill and no "Hidden caption". Skipping a hidden element's whole subtree
        would lose the child.
        """
        document = _document(HIDDEN_PARENT_BODY)
        child = browser_rect(document, "#shown-child")
        parent = browser_rect(document, "#hidden-parent")
        assert browser_hit_id(document, *_centre(child)) == "shown-child", (
            "fixture drift: the browser does not show the visible child"
        )
        assert browser_hit_id(document, parent["x"] + 4, parent["y"] + 4) != "hidden-parent", (
            "fixture drift: the browser shows the hidden parent"
        )

        shapes = slide_shapes(_export_one(HIDDEN_PARENT_BODY, monkeypatch))
        _assert_at(
            _filled(shapes, SHOWN_CHILD_FILL, "the visible child"), child, "the visible child"
        )
        shown = [
            shape
            for shape in shapes
            if shape.kind == "text" and _normalised(shape.text) == "Shown child"
        ]
        assert len(shown) == 1, (
            f"the visible child's text must be exported once:\n{_describe(shapes)}"
        )
        _assert_not_filled(shapes, (HIDDEN_PARENT_FILL,), "the hidden parent")
        _assert_no_words(shapes, ("Hidden", "caption"), "the hidden parent")

    @pytest.mark.parametrize("hiding", sorted(HIDING_STYLES))
    def test_text_after_a_hidden_word_keeps_its_x(
        self, monkeypatch: pytest.MonkeyPatch, hiding: str
    ) -> None:
        """ "Revenue <hidden>secretword</hidden> grew twelve percent" on one line.

        ``visibility: hidden`` and ``opacity: 0`` paint nothing but keep their
        room in the line, so the browser draws "grew" past the hidden word's
        gap. PowerPoint and Google Slides lay a paragraph's runs out with no
        room for a word that is not there, so a line read as "Revenue grew …"
        would draw "grew" a whole word to the left. The hidden word cuts the
        line, as an atomic inline does (coordinator ruling on Task 5 concern 1):

        * "secretword" is not slide text, and the slide's words are exactly
          "Revenue grew twelve percent", each once;
        * "Revenue" starts at its browser x within 0.5 px;
        * the text item holding "grew twelve percent" starts at the browser x
          of "grew" within 1 px.
        """
        body = HIDDEN_WORD_SENTENCE.format(hide=HIDING_STYLES[hiding])
        document = _document(body)
        before = _single_line(document, "#before-hidden")
        after = _single_line(document, "#after-hidden")
        hidden = browser_rect(document, "#hidden-word")
        assert before["text"] == "Revenue" and after["text"] == "grew twelve percent", (
            f"fixture drift: the sentence reads {before['text']!r} | {after['text']!r}"
        )
        assert (
            hidden["w"] > 4 * CUT_TEXT_X_TOLERANCE_PX and after["x"] >= hidden["x"] + hidden["w"]
        ), f"fixture drift: the hidden word {hidden} does not keep its room before {after}"

        shapes = slide_shapes(_export_one(body, monkeypatch))
        _assert_no_words(shapes, (HIDDEN_WORD,), hiding)
        emitted = Counter(word for _, text in _slide_texts(shapes) for word in _words(text))
        assert emitted == Counter(SENTENCE_WORDS), (
            f"{hiding}: the slide's words are {dict(emitted)}, expected each of "
            f"{list(SENTENCE_WORDS)} once\n{_describe(shapes)}"
        )
        revenue = _text_item_containing(shapes, "Revenue")
        assert abs(revenue.x - before["x"]) <= TEXT_LEFT_TOLERANCE_PX, (
            f"{hiding}: 'Revenue' starts at {revenue.x:.2f}; the browser draws it at "
            f"{before['x']:.2f}"
        )
        grew = _text_item_containing(shapes, "grew twelve percent")
        assert abs(grew.x - after["x"]) <= CUT_TEXT_X_TOLERANCE_PX, (
            f"{hiding}: the text after the hidden word, {_box(grew)} {grew.text!r}, starts at "
            f"{grew.x:.2f}; the browser draws 'grew' at {after['x']:.2f}, past the hidden word "
            f"{hidden}\n{_describe(shapes)}"
        )


# ---------------------------------------------------------------------------
# Clipping by overflow ancestors
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotOverflowClipping:
    @pytest.mark.parametrize("case", sorted(ZERO_AREA_CLIPS))
    def test_content_clipped_to_nothing_exports_nothing(
        self, monkeypatch: pytest.MonkeyPatch, case: str
    ) -> None:
        """A box (fill ``00A972``, "Clipped Quokka", a raster picture, an icon)
        that its ``overflow: hidden`` ancestors clip to zero area, on the slide.

        Cases: a collapsed (height 0) panel; a box placed below the bottom of
        the box that clips it; and a box inside its nearest clip but outside the
        outer one, so only the intersection of every overflow ancestor's
        padding box hides it. The browser shows none of it at its centre.

        The export has no ``00A972`` fill, none of its words and no picture;
        the lead paragraph is exported once.
        """
        body = ZERO_AREA_CLIPS[case]
        document = _document(body)
        clipped = browser_rect(document, "#clipped")
        clipper = browser_padding_box(document, "#clipper")
        assert _contains(SLIDE_RECT, clipped), f"fixture drift: #clipped {clipped} leaves the slide"
        hit = browser_hit_id(document, *_centre(clipped))
        assert hit != "clipped", f"fixture drift: the browser shows #clipped {clipped}"
        if case == "outside-the-outer-of-two-clips":
            outer = browser_padding_box(document, "#outer")
            assert _contains(clipper, clipped) and _intersection(outer, clipped) is None, (
                f"fixture drift: #clipped {clipped} must lie inside its nearest clip {clipper} "
                f"and outside the outer one {outer}"
            )
        else:
            assert _intersection(clipper, clipped) is None, (
                f"fixture drift: #clipped {clipped} meets its clip {clipper}"
            )

        shapes = slide_shapes(_export_one(body, monkeypatch))
        _assert_not_filled(shapes, (CLIPPED_FILL,), case)
        _assert_no_words(shapes, CLIPPED_WORDS, case)
        _assert_no_pictures(shapes, case)
        _assert_lead_kept(shapes)

    @pytest.mark.parametrize("overflow", CLIPPING_OVERFLOWS)
    def test_a_partly_clipped_box_is_cut_to_its_parents_padding_box(
        self, monkeypatch: pytest.MonkeyPatch, overflow: str
    ) -> None:
        """A box (fill ``FF3621``) spilling out of a frame with ``overflow: hidden``
        or ``overflow: clip`` to the right and at the bottom.

        The frame has a 6 px border and 10 px padding, and an overflow clips to
        the padding box, inside the border (CSS Overflow 3, the overflow clip
        edge): the browser paints the frame's border, not the box, over the
        6 px past the padding box. Hit testing confirms the box shows inside
        the frame and not past it. (Chrome hit-tests an overflow clip at the
        border box, so hit testing cannot locate the padding edge itself.)

        So the box is exactly one ``FF3621`` shape whose box is the browser
        rect of the box intersected with the frame's browser padding box,
        within 0.5 px: not the whole box, and not cut at the frame's border box
        or content box.
        """
        body = PARTIAL_CLIP.format(overflow=overflow)
        document = _document(body)
        spill = browser_rect(document, "#spill")
        frame = browser_rect(document, "#frame")
        padding = browser_padding_box(document, "#frame")
        visible = _intersection(spill, padding)
        assert visible is not None and visible["x"] == spill["x"] and visible["y"] == spill["y"], (
            f"fixture drift: #spill {spill} must start inside the padding box {padding}"
        )
        assert spill["x"] + spill["w"] > frame["x"] + frame["w"] and (
            spill["y"] + spill["h"] > frame["y"] + frame["h"]
        ), f"fixture drift: #spill {spill} must spill past the frame {frame} right and below"
        assert abs(frame["w"] - padding["w"] - 2 * FRAME_BORDER_PX) < 0.01, (
            f"fixture drift: the frame's padding box {padding} is not its border box {frame} "
            f"less a {FRAME_BORDER_PX:g} px border"
        )
        assert browser_hit_id(document, *_centre(visible)) == "spill", (
            "fixture drift: the browser does not show the spilling box inside the frame"
        )
        past_the_frame = (spill["x"] + spill["w"] - FRAME_BORDER_PX, _centre(visible)[1])
        assert browser_hit_id(document, *past_the_frame) != "spill", (
            "fixture drift: the browser shows the spilling box past the frame that clips it"
        )

        shapes = slide_shapes(_export_one(body, monkeypatch))
        _assert_at(
            _filled(shapes, SPILL_FILL, f"the spilling box ({overflow})"),
            visible,
            (f"the box spilling out of an overflow: {overflow} frame"),
        )

    def test_lines_a_box_cuts_off_are_not_exported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A three-line paragraph in a 56 px window with ``overflow: hidden``.

        The window shows the lines whose glyph rects meet its padding box by
        2 px or more and none of the rest. Read from the browser's own line
        boxes: no line lies in between, at least one is shown and at least one
        is cut off.

        The text items in the window read exactly the shown lines, top to
        bottom, and no word found only on a cut-off line is slide text.
        """
        document = _document(CLIPPED_LINES)
        window = browser_padding_box(document, "#window")
        lines = browser_line_boxes(document, "#window-text")
        shown: list[dict] = []
        cut: list[dict] = []
        for line in lines:
            overlap = _intersection(line, window)
            if overlap is not None and min(overlap["w"], overlap["h"]) >= MINIMUM_VISIBLE_PX:
                shown.append(line)
            elif overlap is None:
                cut.append(line)
            else:
                pytest.fail(
                    f"fixture drift: the line {line} meets the window {window} by {overlap}"
                )
        assert shown and cut, f"fixture drift: the window {window} shows {shown} and cuts {cut}"
        shown_words = {word for line in shown for word in _words(line["text"])}
        cut_only = tuple(
            sorted({word for line in cut for word in _words(line["text"])} - shown_words)
        )

        shapes = slide_shapes(_export_one(CLIPPED_LINES, monkeypatch))
        in_window = sorted(
            (
                shape
                for shape in shapes
                if shape.kind == "text" and _intersection(_box(shape), window) is not None
            ),
            key=lambda shape: (shape.y, shape.x),
        )
        read = [
            _normalised(part)
            for shape in in_window
            for part in shape.text.split("\n")
            if _normalised(part)
        ]
        assert read == [line["text"] for line in shown], (
            f"the window's text items read {read}; the browser shows the lines "
            f"{[line['text'] for line in shown]} and cuts off {[line['text'] for line in cut]}\n"
            f"{_describe(shapes)}"
        )
        _assert_no_words(shapes, cut_only, "the cut-off lines")

    def test_a_zero_height_box_that_does_not_clip_keeps_what_overflows_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guard: zero area hides an element's own box, not what overflows it.

        A ``height: 0`` box with the default ``overflow: visible`` holds a filled
        (``00A973``) child reading "Overflowing child", which the browser shows.
        The child is one shape at its browser rect within 0.5 px, and its text
        is exported once.
        """
        document = _document(UNCLIPPED_ZERO_HEIGHT)
        child = browser_rect(document, "#overflowing")
        assert browser_rect(document, "#zero")["h"] == 0, "fixture drift: #zero is not zero-height"
        assert browser_hit_id(document, *_centre(child)) == "overflowing", (
            "fixture drift: the browser does not show the overflowing child"
        )

        shapes = slide_shapes(_export_one(UNCLIPPED_ZERO_HEIGHT, monkeypatch))
        _assert_at(
            _filled(shapes, OVERFLOWING_FILL, "the overflowing child"),
            child,
            ("the child overflowing a zero-height box"),
        )
        texts = [
            shape
            for shape in shapes
            if shape.kind == "text" and _normalised(shape.text) == "Overflowing child"
        ]
        assert len(texts) == 1, (
            f"the overflowing child's text must be exported once:\n{_describe(shapes)}"
        )

    def test_a_box_positioned_outside_its_clipping_ancestor_is_not_clipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guard: an ``overflow`` box clips only what its containing-block chain passes through.

        A static 200x60 ``overflow: hidden`` box holds an absolutely positioned
        badge (fill ``00A974``, "Escaped badge") placed far outside it. The
        badge's containing block is the positioned slide root, an ancestor of
        the clipping box, so that box does not clip it (CSS 2.1 §11.1.1) and
        the browser shows it. The badge is one shape at its browser rect within
        0.5 px, and its text is exported once.
        """
        document = _document(ESCAPED_CLIP)
        badge = browser_rect(document, "#escaped")
        clipper = browser_padding_box(document, "#static-clipper")
        assert _intersection(badge, clipper) is None, (
            f"fixture drift: the badge {badge} meets the clipping box {clipper}"
        )
        assert browser_hit_id(document, *_centre(badge)) == "escaped", (
            "fixture drift: the browser does not show the escaped badge"
        )

        shapes = slide_shapes(_export_one(ESCAPED_CLIP, monkeypatch))
        _assert_at(_filled(shapes, ESCAPED_FILL, "the escaped badge"), badge, "the escaped badge")
        texts = [
            shape
            for shape in shapes
            if shape.kind == "text" and _normalised(shape.text) == "Escaped badge"
        ]
        assert len(texts) == 1, (
            f"the escaped badge's text must be exported once:\n{_describe(shapes)}"
        )


# ---------------------------------------------------------------------------
# Off-slide content
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotOffSlide:
    @pytest.mark.parametrize("root", sorted(SLIDE_ROOTS))
    def test_a_decoration_past_the_right_edge_is_cut_to_the_slide(
        self, monkeypatch: pytest.MonkeyPatch, root: str
    ) -> None:
        """A 160x24 bar (fill ``FF3621``) at ``right: -40px`` hangs 40 px past the slide.

        The browser shows it up to the slide's right edge, whether the slide
        root clips its overflow (the deck's ``.slide``) or not. It is kept, as
        one ``FF3621`` shape whose box is its browser rect cut to the slide
        rect (0, 0, 1280, 720), within 0.5 px.
        """
        body = OFF_EDGE_DECORATION.format(root_style=SLIDE_ROOTS[root])
        document = _document(body)
        decoration = browser_rect(document, "#decoration")
        visible = _intersection(decoration, SLIDE_RECT)
        assert visible is not None and decoration["x"] + decoration["w"] > SLIDE_RECT["w"], (
            f"fixture drift: the decoration {decoration} does not straddle the right edge"
        )
        assert browser_hit_id(document, *_centre(visible)) == "decoration", (
            "fixture drift: the browser does not show the decoration on the slide"
        )

        shapes = slide_shapes(_export_one(body, monkeypatch))
        _assert_at(
            _filled(shapes, DECORATION_FILL, f"the decoration ({root})"),
            visible,
            ("the decoration past the right edge"),
        )
        _assert_lead_kept(shapes)

    @pytest.mark.parametrize("case", sorted(OFFSTAGE_CASES))
    def test_content_wholly_off_the_slide_exports_nothing(
        self, monkeypatch: pytest.MonkeyPatch, case: str
    ) -> None:
        """A filled box (``2B4A57``) with text, a raster picture and an icon, wholly off the slide.

        Below y = 720 (the brief's case) on the deck's slide root, and on every
        side of a slide root that does not clip its overflow, so only the slide
        rect can remove it. The export succeeds (no failure, the slide is
        written) and the box produces nothing: no ``2B4A57`` fill, none of its
        words, no picture. The lead paragraph is exported once.
        """
        side, root_style = OFFSTAGE_CASES[case]
        body = OFFSTAGE.format(root_style=root_style, place=OFFSTAGE_PLACES[side])
        offstage = browser_rect(_document(body), "#offstage")
        assert _intersection(offstage, SLIDE_RECT) is None, (
            f"fixture drift: the off-slide box {offstage} meets the slide"
        )

        shapes = slide_shapes(_export_one(body, monkeypatch))
        _assert_not_filled(shapes, (OFFSTAGE_FILL,), case)
        _assert_no_words(shapes, OFFSTAGE_WORDS, case)
        _assert_no_pictures(shapes, case)
        _assert_lead_kept(shapes)


# ---------------------------------------------------------------------------
# The geometry of a cut shape
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotClippedShapeGeometry:
    def test_a_disc_past_the_slide_edge_is_cut_not_squashed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 240 px ``border-radius: 50%`` disc (fill ``00A975``) hanging 80 px past the right edge.

        The browser shows the disc up to the slide edge: a circle with its
        right part cut off by a straight line. A preset ellipse in the visible
        box would be a squashed oval, and one in the whole box would hang off
        the slide, so the disc is one ``a:custGeom`` shape:

        * its box (``a:xfrm``) is the disc's browser rect cut to the slide rect,
          within 0.5 px;
        * its ``a:path`` coordinate space is the box's own extent (``w``/``h``
          equal ``a:ext`` ``cx``/``cy``), so no renderer rescales the path;
        * every point of the path lies on the disc's circle or on the slide's
          right edge, within 0.5 px, and the path reaches that edge.
        """
        document = _document(DISC)
        disc = browser_rect(document, "#disc")
        visible = _intersection(disc, SLIDE_RECT)
        assert visible is not None and disc["x"] + disc["w"] > SLIDE_RECT["w"], (
            f"fixture drift: the disc {disc} does not straddle the right edge"
        )
        assert abs(disc["w"] - disc["h"]) < 0.01, f"fixture drift: the disc {disc} is not round"
        assert browser_hit_id(document, *_centre(visible)) == "disc", (
            "fixture drift: the browser does not show the disc on the slide"
        )

        shape, shapes, element = _filled_with_xml(
            _export_one(DISC, monkeypatch), DISC_FILL, "the disc"
        )
        assert shape.geometry == "custGeom", (
            f"the disc the slide edge cuts must be a custom-geometry path, got {shape.geometry} "
            f"at {_box(shape)}\n{_describe(shapes)}"
        )
        _assert_at(shape, visible, "the disc cut to the slide")
        path = _assert_path_fills_its_frame(element, "the disc")
        centre_x, centre_y = _centre(disc)
        radius = disc["w"] / 2
        points = _path_points(path, shape)
        stray = [
            (round(x, 3), round(y, 3))
            for x, y in points
            if abs(math.hypot(x - centre_x, y - centre_y) - radius) > RECT_TOLERANCE_PX
            and abs(x - SLIDE_RECT["w"]) > RECT_TOLERANCE_PX
        ]
        assert points and stray == [], (
            f"the disc's path strays from its circle (centre {centre_x}, {centre_y}, radius "
            f"{radius}) and the slide edge at {stray[:8]} ({len(stray)} of {len(points)} points)"
        )
        assert any(abs(x - SLIDE_RECT["w"]) <= RECT_TOLERANCE_PX for x, _ in points), (
            "the disc's path never reaches the slide edge that cuts it"
        )

    def test_a_cut_bordered_card_keeps_its_border_off_the_cut(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A rounded card (fill ``F2E8D5``, 4 px border ``5A2D82``) spilling out of the bottom
        of an ``overflow: hidden`` window.

        The browser draws the card down to the window's padding box and no
        border along that cut: the card's own bottom edge, border and corners
        are clipped away. A preset roundRect cannot draw that, so the card is
        two ``a:custGeom`` paths, the outline painted over the fill:

        * the fill: a closed path (``a:close``) filled ``F2E8D5`` with no line,
          whose box is the card's outline box (its browser rect inset by half
          the border, where a shape's outline runs) cut to the window's padding
          box, within 0.5 px;
        * the outline: a path with ``a:noFill``, stroked ``5A2D82``, that is
          open (no ``a:close``) and has no segment along the cut, whose box is
          the outline box from its top down to the cut.
        """
        document = _document(CUT_CARD)
        card = browser_rect(document, "#card")
        window = browser_padding_box(document, "#window")
        assert _contains(window, {**card, "h": window["y"] + window["h"] - card["y"]}), (
            f"fixture drift: the card {card} must start inside the window {window}"
        )
        assert card["y"] + card["h"] > window["y"] + window["h"] + CARD_BORDER_PX, (
            f"fixture drift: the card {card} must spill below the window {window}"
        )
        cut = window["y"] + window["h"]
        assert browser_hit_id(document, *_centre(_intersection(card, window))) == "card", (
            "fixture drift: the browser does not show the card inside the window"
        )
        assert browser_hit_id(document, card["x"] + card["w"] / 2, cut + 10) != "card", (
            "fixture drift: the browser shows the card below the window that clips it"
        )

        pptx = _export_one(CUT_CARD, monkeypatch)
        fill, shapes, fill_element = _filled_with_xml(pptx, CARD_FILL, "the card's fill")
        outline_box = _inset(card, CARD_BORDER_PX / 2)
        assert fill.geometry == "custGeom", (
            f"the cut card's fill must be a custom-geometry path, got {fill.geometry} "
            f"at {_box(fill)}\n{_describe(shapes)}"
        )
        assert fill.line is None, f"the cut card's fill path is stroked {fill.line}"
        _assert_at(fill, _intersection(outline_box, window), "the cut card's fill")
        fill_path = _assert_path_fills_its_frame(fill_element, "the card's fill")
        assert fill_path.find("a:close", NAMESPACES) is not None, (
            "the cut card's fill path is not closed"
        )

        outlines = [index for index, shape in enumerate(shapes) if shape.line == CARD_LINE]
        assert len(outlines) == 1, (
            f"expected one shape stroked {CARD_LINE}, got {len(outlines)}:\n{_describe(shapes)}"
        )
        outline = shapes[outlines[0]]
        outline_element = slide_shape_elements(pptx)[outlines[0]]
        assert outline.geometry == "custGeom", (
            f"the cut card's outline must be a custom-geometry path, got {outline.geometry}"
        )
        assert outline_element.find("p:spPr/a:noFill", NAMESPACES) is not None, (
            f"the cut card's outline path is filled {outline.fill}: it must be a:noFill"
        )
        assert outlines[0] > shapes.index(fill), "the card's outline paints under its fill"
        _assert_at(
            outline,
            {**outline_box, "h": cut - outline_box["y"]},
            "the cut card's outline, from its top down to the cut",
        )
        outline_path = _assert_path_fills_its_frame(outline_element, "the card's outline")
        assert outline_path.find("a:close", NAMESPACES) is None, (
            "the cut card's outline path is closed, so it runs along the cut"
        )
        points = _path_points(outline_path, outline)
        along_the_cut = [
            (round(start[0], 3), round(end[0], 3))
            for start, end in zip(points, points[1:])
            if abs(start[1] - cut) <= RECT_TOLERANCE_PX and abs(end[1] - cut) <= RECT_TOLERANCE_PX
        ]
        assert along_the_cut == [], (
            f"the cut card's outline runs along the cut at y={cut:.2f} over x {along_the_cut}"
        )

    @pytest.mark.parametrize("case", sorted(CUT_PLAIN_RECTS))
    def test_a_cut_plain_rect_stays_a_preset_rect(
        self, monkeypatch: pytest.MonkeyPatch, case: str
    ) -> None:
        """Guard: a plain unbordered rect that a clip cuts is still a preset ``rect``.

        The part of it the clip shows is a rect too, so it stays the shape
        PowerPoint and Google Slides edit as a rectangle (``a:prstGeom
        prst="rect"``), at its browser rect cut to the clip within 0.5 px.
        Only a shape a rect cannot draw becomes a custom-geometry path. Cases:
        the box spilling out of an ``overflow: hidden`` frame, and the
        decoration past the right edge of a slide root that does not clip.
        """
        body, selector, fill = CUT_PLAIN_RECTS[case]
        document = _document(body)
        rect = browser_rect(document, selector)
        clip = browser_padding_box(document, "#frame") if selector == "#spill" else SLIDE_RECT
        visible = _intersection(rect, clip)
        assert visible is not None and (visible["w"] < rect["w"] or visible["h"] < rect["h"]), (
            f"fixture drift: the clip {clip} does not cut {selector} {rect}"
        )

        shape, shapes, element = _filled_with_xml(_export_one(body, monkeypatch), fill, case)
        preset = element.find("p:spPr/a:prstGeom", NAMESPACES)
        assert shape.geometry == "rect" and preset is not None, (
            f"{case}: the cut plain rect must stay a preset rect, got {shape.geometry}"
            f"\n{_describe(shapes)}"
        )
        _assert_at(shape, visible, f"{case}: the cut plain rect")
