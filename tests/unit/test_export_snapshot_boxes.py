"""Snapshot engine: boxes, the slide background and CSS paint order.

The snapshot engine reads the rendered page and emits each painted box as a
native shape:

* a circle (all four radii at least half the matching side) is an ``ellipse``,
  not a rounded rectangle with a 50 % corner;
* a rounded card keeps its radius as the ``roundRect`` adjustment relative to
  the short side, its outer shadow, and its uniform border as the shape line,
  with the box inset by half the border width so the stroke centre sits where
  CSS paints it;
* fill alpha comes from the background colour's alpha times the cumulative
  opacity;
* the slide root's background is the slide's ``<p:bg>``, not a slide-sized
  shape on top of it;
* shapes follow CSS painting order (z-index, negative z-index, atomic flex
  items, atomic floats), not DOM order;
* entrance animations are finished before the snapshot, so a fade-in exports
  its settled, opaque state;
* the page is read as the browser laid it out: nothing that moves layout
  runs before the snapshot, so a monospace code panel keeps each line's own
  box;
* a box whose corners round by different radii (a card header's
  ``16px 16px 0 0``) keeps each corner's own: the ``round2SameRect`` preset
  when its top corners are one circle and its bottom ones another, each at
  most half the short side, and otherwise a custom path of one quarter arc per
  rounded corner (Task 14 B4, D11: before, one ``roundRect`` rounded all four
  by the largest).

Every assertion reads the emitted slide XML (``slide_shapes``) and, where the
geometry matters, compares it with the browser's own layout of the very same
document (``browser_rect``). Shapes are identified by a fill colour used once
per slide, so a lookup can only match the element under test.

Gating matches the sibling export suites: needs node, the extracted sidecar
``node_modules`` and a local Chrome/Chromium (skipped otherwise).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import pytest
from lxml import etree

from tests.fixtures.export_snapshot_support import (
    DECK_CSS,
    EMU_PER_PX,
    NAMESPACES,
    Shape,
    browser_rect,
    export_slides,
    node_json,
    requires_huashu_sidecar,
    slide_background,
    slide_document,
    slide_shape_elements,
    slide_shapes,
)

# The browser rect and the emitted box agree within this much (EMU rounding is
# 1/9525 px, so anything larger is a real geometry difference).
BOX_TOLERANCE_PX = 0.5
# The card's border inset is exactly 0.5 px per side, so the inset check needs a
# tolerance well below it to tell an inset box from an un-inset one.
INSET_TOLERANCE_PX = 0.1
ALPHA_TOLERANCE = 0.01

FADE_IN_KEYFRAMES = "@keyframes tellr-fade-in { from { opacity: 0; } to { opacity: 1; } }"


def _export_one(body: str, monkeypatch: pytest.MonkeyPatch, *, css: str = DECK_CSS) -> bytes:
    pptx, failures = export_slides([body], css=css, monkeypatch=monkeypatch)
    assert failures == [], f"the export rejected the slide: {failures}"
    assert pptx, "the export produced no .pptx bytes"
    return pptx


def _document(body: str, *, css: str = DECK_CSS) -> str:
    """The document ``_export_one`` exported (``export_slides`` names slide 1 ``snapshot-1``)."""
    return slide_document(body, css=css, slide_id="snapshot-1")


def _describe(shapes: list[Shape]) -> str:
    return "\n".join(
        f"  [{position}] {shape.kind} {shape.geometry} {shape.name!r} fill={shape.fill} "
        f"alpha={shape.fill_alpha} line={shape.line} shadow={shape.shadow} "
        f"box=({shape.x:.2f}, {shape.y:.2f}, {shape.w:.2f}, {shape.h:.2f}) text={shape.text[:30]!r}"
        for position, shape in enumerate(shapes)
    )


def _filled(shapes: list[Shape], fill: str) -> tuple[int, Shape]:
    """(spTree index, shape) of the one element filled ``fill``."""
    matches = [(position, shape) for position, shape in enumerate(shapes) if shape.fill == fill]
    assert len(matches) == 1, (
        f"expected exactly one element filled {fill}, got {len(matches)}:\n{_describe(shapes)}"
    )
    return matches[0]


def _assert_box(shape: Shape, expected: dict, tolerance: float, what: str) -> None:
    emitted = {"x": shape.x, "y": shape.y, "w": shape.w, "h": shape.h}
    off = {key: round(emitted[key] - expected[key], 3) for key in expected}
    assert all(abs(delta) <= tolerance for delta in off.values()), (
        f"{what}: emitted box {emitted} differs from the expected {expected} by {off} "
        f"(tolerance {tolerance} px)"
    )


def _assert_paint_order(shapes: list[Shape], fills: list[tuple[str, str]], rule: str) -> None:
    """The elements named by ``fills`` ((label, fill) pairs) appear in spTree in this order."""
    positions = [(label, _filled(shapes, fill)[0]) for label, fill in fills]
    order = [label for label, _ in sorted(positions, key=lambda pair: pair[1])]
    assert order == [label for label, _ in fills], (
        f"{rule}: expected back-to-front {[label for label, _ in fills]}, "
        f"emitted {order} (spTree indices {dict(positions)}):\n{_describe(shapes)}"
    )


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotBoxes:
    def test_circle_is_an_ellipse_at_the_browser_rect(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 40x40 ``border-radius: 50%`` dot is one ``ellipse`` filled FF5F46 at the browser rect.

        Today's engine emits a ``roundRect`` with a 50 % corner instead.
        """
        body = (
            '<div class="slide">'
            '<div id="dot" style="width: 40px; height: 40px; border-radius: 50%; '
            'background: #FF5F46;"></div>'
            "</div>"
        )
        shapes = slide_shapes(_export_one(body, monkeypatch))
        expected = browser_rect(_document(body), "#dot")

        _, dot = _filled(shapes, "FF5F46")
        assert dot.kind == "shape", f"the dot is a {dot.kind}, not a shape:\n{_describe(shapes)}"
        assert dot.geometry == "ellipse", (
            f"a border-radius: 50% circle must be an ellipse, got {dot.geometry} (adj={dot.adj})"
        )
        assert [shape.geometry for shape in shapes].count("ellipse") == 1, (
            f"expected exactly one ellipse on the slide:\n{_describe(shapes)}"
        )
        _assert_box(dot, expected, BOX_TOLERANCE_PX, "the dot")

    def test_card_keeps_radius_shadow_and_border_with_the_stroke_inset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The corpus card style on a 200x100 border box.

        * ``roundRect`` whose adj is 12 px over the short side, within one percent
          of the short side: ``round(12 / 100 * 100000)`` ± 1000. (The border inset
          makes the short side 99 px, so the exact value is 12121.)
        * an outer shadow in 1B3139 at alpha 0.08, 2 px straight down;
        * the 1 px DCE0E2 border as a 0.75 pt solid line;
        * the box inset by half the border width on every side, so the stroke
          centre sits on the CSS border's centre line. Today's engine emits the
          un-inset border box, which draws the stroke half a pixel too far out.
        """
        body = (
            '<div class="slide">'
            '<div id="card" style="box-sizing: border-box; width: 200px; height: 100px; '
            "border-radius: 12px; background: #fff; box-shadow: 0 2px 8px rgba(27,49,57,.08); "
            'border: 1px solid #DCE0E2;"></div>'
            "</div>"
        )
        shapes = slide_shapes(_export_one(body, monkeypatch))
        border_box = browser_rect(_document(body), "#card")
        assert (border_box["w"], border_box["h"]) == (200.0, 100.0), (
            f"fixture drift: the card's border box measured {border_box}"
        )

        _, card = _filled(shapes, "FFFFFF")
        assert card.kind == "shape", f"the card is a {card.kind}, not a shape:\n{_describe(shapes)}"
        assert len(shapes) == 1, (
            f"a one-layer shadow is the card's own: expected the card alone:\n{_describe(shapes)}"
        )
        assert card.geometry == "roundRect", (
            f"a 12px-radius card must be a roundRect, got {card.geometry}"
        )
        expected_adj = round(12 / 100 * 100000)
        assert card.adj is not None and abs(card.adj - expected_adj) <= 1000, (
            f"roundRect adj {card.adj} is more than one percent of the short side "
            f"away from {expected_adj}"
        )

        shadow = card.shadow
        assert shadow is not None and shadow.kind == "outer", (
            f"the card lost its outer shadow: {shadow}"
        )
        assert shadow.color == "1B3139", f"shadow colour {shadow.color}, expected 1B3139"
        assert shadow.alpha is not None and abs(shadow.alpha - 0.08) <= ALPHA_TOLERANCE, (
            f"shadow alpha {shadow.alpha}, expected 0.08"
        )
        assert abs(shadow.angle - 90) <= 1 and abs(shadow.dist_px - 2) <= 0.5, (
            f"a 0 2px shadow falls 2 px straight down; "
            f"got {shadow.dist_px} px at {shadow.angle} degrees"
        )

        assert card.line == "DCE0E2", f"border colour {card.line}, expected DCE0E2"
        assert card.line_w_pt is not None and abs(card.line_w_pt - 0.75) <= 0.01, (
            f"a 1 px border is 0.75 pt, got {card.line_w_pt}"
        )
        assert card.line_dash in (None, "solid"), f"a solid border emitted dash {card.line_dash}"

        half_border = 0.5
        inset = {
            "x": border_box["x"] + half_border,
            "y": border_box["y"] + half_border,
            "w": border_box["w"] - 2 * half_border,
            "h": border_box["h"] - 2 * half_border,
        }
        _assert_box(card, inset, INSET_TOLERANCE_PX, "the card, inset by half its 1 px border")

    def test_fill_alpha_is_colour_alpha_times_cumulative_opacity(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``rgba(255,95,70,0.10)`` is a FF5F46 fill at alpha 0.10.

        The same rule under an ``opacity: 0.5`` ancestor: ``rgba(0,169,114,0.40)``
        paints at 0.40 x 0.5 = 0.20 on screen, so its fill alpha is 0.20. Today's
        engine keeps the colour alpha but ignores the ancestor's opacity (0.40).
        """
        body = (
            '<div class="slide">'
            '<div id="tint" style="width: 300px; height: 120px; '
            'background: rgba(255,95,70,0.10);"></div>'
            '<div style="opacity: 0.5; margin-top: 24px;">'
            '<div id="faded-tint" style="width: 300px; height: 120px; '
            'background: rgba(0,169,114,0.40);"></div>'
            "</div>"
            "</div>"
        )
        shapes = slide_shapes(_export_one(body, monkeypatch))

        _, tint = _filled(shapes, "FF5F46")
        assert tint.fill_alpha is not None and abs(tint.fill_alpha - 0.10) <= ALPHA_TOLERANCE, (
            f"rgba(255,95,70,0.10) exported fill alpha {tint.fill_alpha}, expected 0.10"
        )
        _, faded_tint = _filled(shapes, "00A972")
        assert (
            faded_tint.fill_alpha is not None
            and abs(faded_tint.fill_alpha - 0.20) <= ALPHA_TOLERANCE
        ), (
            f"rgba(0,169,114,0.40) under opacity 0.5 exported fill alpha {faded_tint.fill_alpha}, "
            "expected 0.20"
        )

    def test_slide_root_background_is_the_slide_background(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A ``.slide.dark`` root's 1B3139 ground is ``<p:bg>`` and is not repeated as a shape.

        Today's engine also paints the ground as a slide-sized rectangle over the
        background, which PowerPoint users then select and drag by accident.
        """
        body = (
            '<div class="slide dark">'
            '<div id="block" style="width: 200px; height: 80px; background: #FF5F46;"></div>'
            "</div>"
        )
        pptx = _export_one(body, monkeypatch)
        shapes = slide_shapes(pptx)

        assert slide_background(pptx) == "1B3139", (
            f"the slide root's ground did not land in <p:bg>: {slide_background(pptx)}"
        )
        grounds = [shape for shape in shapes if shape.fill == "1B3139"]
        assert grounds == [], (
            f"the slide root's ground is repeated as {len(grounds)} shape(s) over <p:bg>:\n"
            f"{_describe(shapes)}"
        )
        _, block = _filled(shapes, "FF5F46")
        assert block.kind == "shape", (
            f"the slide content did not export as a shape:\n{_describe(shapes)}"
        )

    def test_entrance_animations_export_their_settled_state(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A deck that fades content in exports it opaque.

        * ``#fade`` is the plain case, a 1 s fade-in from opacity 0 to 1;
        * ``#late-fade`` is a staggered entrance: the same 1 s fade, delayed past
          any settle and filled backwards, so it is still at opacity 0 when the
          snapshot runs unless the animations are finished first;
        * ``#translucent`` is the control, a static ``opacity: 0.5`` box that
          must keep alpha 0.5. Without it, an engine that ignored opacity
          altogether (today's engine does) would pass the two fade checks
          without finishing anything.
        """
        css = DECK_CSS + FADE_IN_KEYFRAMES
        body = (
            '<div class="slide">'
            '<div id="fade" style="width: 300px; height: 100px; background: #FF5F46; '
            'animation: tellr-fade-in 1s;"></div>'
            '<div id="late-fade" style="width: 300px; height: 100px; background: #00A972; '
            'animation: tellr-fade-in 1s ease-out 30s both;"></div>'
            '<div id="translucent" style="width: 300px; height: 100px; background: #5A6F77; '
            'opacity: 0.5;"></div>'
            "</div>"
        )
        shapes = slide_shapes(_export_one(body, monkeypatch, css=css))

        _, control = _filled(shapes, "5A6F77")
        assert (
            control.fill_alpha is not None and abs(control.fill_alpha - 0.5) <= ALPHA_TOLERANCE
        ), f"a static opacity: 0.5 box exported fill alpha {control.fill_alpha}, expected 0.5"
        for label, fill in (("#fade", "FF5F46"), ("#late-fade", "00A972")):
            _, faded = _filled(shapes, fill)
            assert faded.fill_alpha is None or faded.fill_alpha >= 1 - ALPHA_TOLERANCE, (
                f"{label} exported mid-animation with fill alpha {faded.fill_alpha}; "
                "a finished fade-in is fully opaque"
            )

    def test_code_panel_lines_keep_their_own_boxes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No pass that moves layout runs before the snapshot.

        A monospace panel holding one ``<div>`` per code line is exactly what the
        retired converter's preprocess collapsed into a single ``<p>``, taking
        every line's own background with it. The export runs only the
        background transfer, so each line's box is still on the page when it is
        read and exports as its own shape.
        """
        body = (
            '<div class="slide">'
            '<div style="font-family: monospace; font-size: 14px;">'
            '<div style="width: 300px; height: 24px; background: #FF5F46;">SELECT 1</div>'
            '<div style="width: 300px; height: 24px; background: #00A972;">FROM t</div>'
            "</div>"
            "</div>"
        )
        shapes = slide_shapes(_export_one(body, monkeypatch))

        for line, fill in (("SELECT 1", "FF5F46"), ("FROM t", "00A972")):
            _, box = _filled(shapes, fill)
            assert box.kind == "shape", (
                f"the {line!r} code line's background is a {box.kind}, not a shape:\n"
                f"{_describe(shapes)}"
            )


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotPaintOrder:
    def test_positive_z_index_paints_after_a_later_static_sibling(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A ``z-index: 2`` absolute box earlier in the DOM paints over a later static box."""
        body = (
            '<div class="slide">'
            '<div id="raised" style="position: absolute; z-index: 2; left: 120px; top: 120px; '
            'width: 240px; height: 120px; background: #FF5F46;"></div>'
            '<div id="ground" style="width: 480px; height: 240px; background: #1B3139;"></div>'
            "</div>"
        )
        shapes = slide_shapes(_export_one(body, monkeypatch))

        _assert_paint_order(
            shapes,
            [("#ground", "1B3139"), ("#raised", "FF5F46")],
            "a positive z-index paints after in-flow content of its stacking context",
        )

    def test_negative_z_index_paints_under_its_parents_in_flow_sibling(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A ``z-index: -1`` child paints after its stacking context's own background and before
        the in-flow sibling of its parent, even though that sibling comes first in the DOM.

        ``#stage`` (``position: relative; z-index: 0``) is the stacking context;
        ``#parent`` is positioned with ``z-index: auto``, so it forms none, and
        ``#sunken`` joins ``#stage``'s negative layer.
        """
        body = (
            '<div class="slide">'
            '<div id="stage" style="position: relative; z-index: 0; width: 640px; height: 300px; '
            'background: #DCE0E2;">'
            '<div id="sibling" style="width: 400px; height: 160px; background: #5A6F77;"></div>'
            '<div id="parent" style="position: relative; width: 400px; height: 100px;">'
            '<div id="sunken" style="position: absolute; z-index: -1; left: 200px; top: -80px; '
            'width: 300px; height: 140px; background: #FF5F46;"></div>'
            "</div>"
            "</div>"
            "</div>"
        )
        shapes = slide_shapes(_export_one(body, monkeypatch))

        _assert_paint_order(
            shapes,
            [("#stage", "DCE0E2"), ("#sunken", "FF5F46"), ("#sibling", "5A6F77")],
            "a stacking context paints its background, then negative z-index, then in-flow blocks",
        )

    def test_flex_items_paint_atomically_unlike_block_siblings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Flex items paint atomically: card A's inline content follows card A's background and
        precedes card B's background.

        The block siblings below are the contrast that makes this observable:
        blocks paint every background first and their inline content after, so
        block B's background comes before block A's inline content. DOM order
        happens to satisfy the flex half and fails the block half.

        The inline content is an ``inline-block`` chip, which paints in the same
        inline layer as a block's text.
        """
        chip = "display: inline-block; width: 80px; height: 24px;"
        body = (
            '<div class="slide">'
            '<div id="row" style="display: flex; gap: 24px;">'
            '<div id="card-a" style="width: 240px; height: 120px; background: #DCE0E2;">'
            f'<div id="chip-a" style="{chip} background: #FF5F46;"></div></div>'
            '<div id="card-b" style="width: 240px; height: 120px; background: #5A6F77;">'
            f'<div id="chip-b" style="{chip} background: #00A972;"></div></div>'
            "</div>"
            '<div id="stack" style="margin-top: 24px;">'
            '<div id="block-a" style="width: 240px; height: 80px; background: #CDEDE1;">'
            f'<div id="mark-a" style="{chip} background: #D0302A;"></div></div>'
            '<div id="block-b" style="width: 240px; height: 80px; background: #F8D3D0;">'
            f'<div id="mark-b" style="{chip} background: #FFB347;"></div></div>'
            "</div>"
            "</div>"
        )
        shapes = slide_shapes(_export_one(body, monkeypatch))

        _assert_paint_order(
            shapes,
            [
                ("#card-a", "DCE0E2"),
                ("#chip-a", "FF5F46"),
                ("#card-b", "5A6F77"),
                ("#chip-b", "00A972"),
            ],
            "flex items paint atomically, each with its own content",
        )
        _assert_paint_order(
            shapes,
            [
                ("#block-a", "CDEDE1"),
                ("#block-b", "F8D3D0"),
                ("#mark-a", "D0302A"),
                ("#mark-b", "FFB347"),
            ],
            "block backgrounds paint before the inline content of any block",
        )

    def test_floats_paint_atomically_above_in_flow_blocks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A float paints atomically, after the in-flow blocks of its context (CSS 2.1
        Appendix E): its own block child paints over its background, and the in-flow
        block it overlaps paints under it even though that block is later in the DOM.

        ``#after`` is an in-flow block, so its box starts beside the float's top
        and the float covers its left part, exactly as the browser draws it.
        """
        body = (
            '<div class="slide">'
            '<div id="floated" style="float: left; width: 240px; height: 160px; '
            'background: #DCE0E2;">'
            '<div id="band" style="height: 24px; background: #FF5F46;"></div>'
            "</div>"
            '<div id="after" style="width: 480px; height: 200px; background: #5A6F77;"></div>'
            "</div>"
        )
        shapes = slide_shapes(_export_one(body, monkeypatch))

        _assert_paint_order(
            shapes,
            [("#after", "5A6F77"), ("#floated", "DCE0E2"), ("#band", "FF5F46")],
            "in-flow block backgrounds paint first, then each float with its own content",
        )


# ---------------------------------------------------------------------------
# Shadow layers
# ---------------------------------------------------------------------------

# One shape carries one outer shadow (a:outerShdw), in PowerPoint and in Google
# Slides alike, and that is how a person gives a box a shadow in either app. So
# a box's box-shadow layers are written as one shadow on the box's own shape:
# its one layer as it is, and two or more (or a layer with a spread, which an
# outer shadow has none of) as the one layer closest to them all together, the
# fitted shadow (CALIBRATION.md, D4 and D5). No shape is drawn for a shadow
# alone. Neither app casts a shadow from an unfilled shape (measured: B2), and
# an unfilled shape's outline would cast only a thin frame of itself, so a box
# that paints no fill casts none.
SHADOW_SHAPE_NAME = "Shadow"
# The design system's --shadow-md and --shadow-sm, each two layers (deck.css).
SHADOW_MD = "0 2px 6px rgba(27,49,57,.08), 0 8px 20px rgba(27,49,57,.08)"
SHADOW_SM = "0 1px 2px rgba(27,49,57,.06), 0 1px 3px rgba(27,49,57,.08)"
# Tailwind's shadow-lg: two layers with negative spreads.
TAILWIND_SHADOW_LG = "0 10px 15px -3px rgba(0,0,0,.1), 0 4px 6px -4px rgba(0,0,0,.1)"
# The fitted layer of each design-system shadow, as CALIBRATION.md records it:
# (offset down px, blur px, alpha), in 1B3139.
FITTED_SHADOW_MD = (5.13, 14.34, 0.139)
FITTED_SHADOW_SM = (1.0, 2.58, 0.137)
# A solid ground for the boxes under test.
PANEL_FILL = "CDEDE1"
PANEL = (
    '<div id="panel" style="position: absolute; left: 80px; top: 80px; width: 1000px; '
    'height: 520px; background: #CDEDE1;">'
)
SHADOW_ANGLE_TOLERANCE_DEG = 1
SHADOW_LENGTH_TOLERANCE_PX = 0.05
# A fitted length or alpha agrees with this test's own model within its grid's
# last step (CALIBRATION.md: about 0.01 px) and EMU rounding.
FIT_LENGTH_TOLERANCE_PX = 0.1
FIT_ALPHA_TOLERANCE = 0.003


@dataclass(frozen=True)
class Layer:
    """One box-shadow layer as an exported shadow: colour, alpha, blur, offset down."""

    colour: str
    alpha: float
    blur_px: float
    down_px: float


@dataclass(frozen=True)
class CssLayer:
    """One CSS box-shadow layer: offset, blur, spread (px), colour and alpha."""

    x: float
    y: float
    blur: float
    spread: float
    colour: str
    alpha: float


def _assert_shadow(
    shape: Shape,
    layer: Layer,
    what: str,
    tolerance_px: float = SHADOW_LENGTH_TOLERANCE_PX,
    alpha_tolerance: float = ALPHA_TOLERANCE,
) -> None:
    shadow = shape.shadow
    assert shadow is not None and shadow.kind == "outer", f"{what}: no outer shadow ({shadow})"
    assert shadow.color == layer.colour, f"{what}: shadow colour {shadow.color}, not {layer.colour}"
    assert shadow.alpha is not None and abs(shadow.alpha - layer.alpha) <= alpha_tolerance, (
        f"{what}: shadow alpha {shadow.alpha}, not {layer.alpha}"
    )
    assert abs(shadow.blur_px - layer.blur_px) <= tolerance_px, (
        f"{what}: shadow blur {shadow.blur_px} px, not {layer.blur_px}"
    )
    assert abs(shadow.dist_px - layer.down_px) <= tolerance_px and (
        abs(shadow.angle - 90) <= SHADOW_ANGLE_TOLERANCE_DEG
    ), f"{what}: shadow {shadow.dist_px} px at {shadow.angle} degrees, not {layer.down_px} down"


def _assert_no_shadow_shape(shapes: list[Shape]) -> None:
    """No shape is drawn for a shadow alone: none is named "Shadow", and every shape paints."""
    named = [shape for shape in shapes if shape.name == SHADOW_SHAPE_NAME]
    assert named == [], f"a shadow shape was drawn:\n{_describe(shapes)}"
    blank = [
        shape for shape in shapes if shape.kind == "shape" and not shape.fill and not shape.line
    ]
    assert blank == [], f"a shape paints nothing of its own:\n{_describe(blank)}"


# The fitted shadow's model, written here from CALIBRATION.md D4 and D5 for the
# tests to hold the export against: a layer covers a point d px outside a long
# edge of the box, n its outward normal, alpha * Q((d - offset.n - spread) /
# sigma), sigma = blur / 2, Q the standard normal's upper tail; layers compose
# as 1 - prod(1 - c); the error of a single layer is the summed squared
# difference over the four edges at d = k R / 64, k = 0..64, R the layers'
# reach. EDGES are the outward normals: bottom, top, right, left.
FIT_SAMPLES = 64
EDGES = ((0, 1), (0, -1), (1, 0), (-1, 0))


def _cover(d: float, along: float, blur: float, spread: float, alpha: float) -> float:
    edge = d - along - spread
    sigma = blur / 2
    if sigma <= 0:
        return alpha * (1.0 if edge < 0 else 0.5 if edge == 0 else 0.0)
    return alpha * 0.5 * math.erfc(edge / sigma / math.sqrt(2))


def _fit_points(layers: list[CssLayer]) -> list[float]:
    reach = max(
        abs(layer.x) + abs(layer.y) + max(layer.spread, 0) + 2 * layer.blur for layer in layers
    )
    return [k * (reach + 1) / FIT_SAMPLES for k in range(FIT_SAMPLES + 1)]


def _composite(layers: list[CssLayer], points: list[float]) -> list[float]:
    profile = []
    for nx, ny in EDGES:
        for d in points:
            keep = 1.0
            for layer in layers:
                keep *= 1 - _cover(
                    d, layer.x * nx + layer.y * ny, layer.blur, layer.spread, layer.alpha
                )
            profile.append(1 - keep)
    return profile


def _fit_error(layers: list[CssLayer], x: float, y: float, blur: float, alpha: float) -> float:
    points = _fit_points(layers)
    target = _composite(layers, points)
    single = [_cover(d, x * nx + y * ny, blur, 0, alpha) for nx, ny in EDGES for d in points]
    return sum((a - b) ** 2 for a, b in zip(single, target))


def _fitted_down(shape: Shape) -> tuple[float, float, float]:
    """(offset down, blur, alpha) of a shape's shadow that falls straight down."""
    shadow = shape.shadow
    assert shadow is not None and abs(shadow.angle - 90) <= SHADOW_ANGLE_TOLERANCE_DEG, shadow
    return shadow.dist_px, shadow.blur_px, shadow.alpha


def _card(shadow: str, *, extra: str = "", fill: str = "#fff") -> str:
    return (
        '<div class="slide"><div id="card" style="position: absolute; left: 100px; top: 100px; '
        f"width: 300px; height: 200px; border-radius: 14px; background: {fill}; {extra}"
        f'box-shadow: {shadow};"></div></div>'
    )


@pytest.mark.slow
@requires_huashu_sidecar
class TestShadowLayers:
    def test_a_multi_layer_card_is_one_shape_with_one_fitted_shadow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The design system's ``--shadow-md`` card: one shape, one shadow, nothing else.

        ``0 2px 6px rgba(27,49,57,.08), 0 8px 20px rgba(27,49,57,.08)`` on a
        white 14 px-radius card. The card is one roundRect at its border box,
        carrying one outer shadow, the fitted layer CALIBRATION.md records for
        ``--shadow-md``: 14.34 px of blur, 5.13 px down, 1B3139 at alpha
        0.139. No other shape is drawn: none named "Shadow", none under the
        card.
        """
        body = _card(SHADOW_MD)
        shapes = slide_shapes(_export_one(body, monkeypatch))
        border_box = browser_rect(_document(body), "#card")

        _assert_no_shadow_shape(shapes)
        assert len(shapes) == 1 and shapes[0].fill == "FFFFFF", (
            f"expected the card alone:\n{_describe(shapes)}"
        )
        card = shapes[0]
        assert card.geometry == "roundRect", f"the card is a {card.geometry}"
        _assert_box(card, border_box, INSET_TOLERANCE_PX, "the card")
        down, blur, alpha = FITTED_SHADOW_MD
        _assert_shadow(
            card,
            Layer("1B3139", alpha, blur, down),
            "the card's fitted shadow",
            FIT_LENGTH_TOLERANCE_PX,
            FIT_ALPHA_TOLERANCE,
        )

    def test_a_shadow_sm_card_carries_its_pinned_fitted_shadow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The design system's KPI card: ``--shadow-sm`` on a bordered white card.

        One roundRect outlined 0.75 pt DCE0E2, carrying the fitted layer
        CALIBRATION.md records for ``--shadow-sm``: 2.58 px of blur, 1 px
        down, 1B3139 at alpha 0.137.
        """
        body = _card(SHADOW_SM, extra="border: 1px solid #DCE0E2; ")
        shapes = slide_shapes(_export_one(body, monkeypatch))

        _assert_no_shadow_shape(shapes)
        assert len(shapes) == 1 and shapes[0].line == "DCE0E2", (
            f"expected the card alone:\n{_describe(shapes)}"
        )
        down, blur, alpha = FITTED_SHADOW_SM
        _assert_shadow(
            shapes[0],
            Layer("1B3139", alpha, blur, down),
            "the card's fitted shadow",
            FIT_LENGTH_TOLERANCE_PX,
            FIT_ALPHA_TOLERANCE,
        )

    def test_the_fitted_shadow_is_the_least_squares_single_layer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tailwind's ``shadow-lg``, two layers with negative spreads, fitted by the model.

        The card's one shadow is a least-squares minimum of this test's own
        model of the layers (CALIBRATION.md): moving its offset or blur by
        0.25 px, or its alpha by 0.003, makes the error no smaller; and it is
        closer to the two layers together than either layer alone, each at
        its own offset, blur and alpha.
        """
        layers = [
            CssLayer(0, 10, 15, -3, "000000", 0.1),
            CssLayer(0, 4, 6, -4, "000000", 0.1),
        ]
        shapes = slide_shapes(_export_one(_card(TAILWIND_SHADOW_LG), monkeypatch))

        _assert_no_shadow_shape(shapes)
        assert len(shapes) == 1, f"expected the card alone:\n{_describe(shapes)}"
        assert shapes[0].shadow is not None and shapes[0].shadow.color == "000000"
        down, blur, alpha = _fitted_down(shapes[0])
        error = _fit_error(layers, 0, down, blur, alpha)
        for d_down, d_blur, d_alpha in (
            (0.25, 0, 0),
            (-0.25, 0, 0),
            (0, 0.25, 0),
            (0, -0.25, 0),
            (0, 0, 0.003),
            (0, 0, -0.003),
        ):
            moved = _fit_error(layers, 0, down + d_down, max(0, blur + d_blur), alpha + d_alpha)
            assert moved >= error - 1e-9, (
                f"the fitted ({down:.2f}, {blur:.2f}, {alpha:.3f}) is no minimum: moving it by "
                f"({d_down}, {d_blur}, {d_alpha}) lowers the error from {error:.3e} to {moved:.3e}"
            )
        for layer in layers:
            alone = _fit_error(layers, layer.x, layer.y, layer.blur, layer.alpha)
            assert error < alone, (
                f"the fitted shadow's error {error:.3e} is no smaller than that of {layer} "
                f"alone, {alone:.3e}"
            )

    def test_layers_of_two_colours_fit_their_weighted_colour(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``0 2px 4px rgba(255,0,0,.3), 0 6px 12px rgba(0,0,255,.15)``: one shadow, both colours.

        The fitted colour is the layers' colours weighted by how much each
        covers alone, summed over the model's points (CALIBRATION.md), each
        channel rounded.
        """
        layers = [CssLayer(0, 2, 4, 0, "FF0000", 0.3), CssLayer(0, 6, 12, 0, "0000FF", 0.15)]
        body = _card("0 2px 4px rgba(255,0,0,.3), 0 6px 12px rgba(0,0,255,.15)")
        shapes = slide_shapes(_export_one(body, monkeypatch))

        points = _fit_points(layers)
        weights = [
            sum(
                _cover(d, layer.x * nx + layer.y * ny, layer.blur, layer.spread, layer.alpha)
                for nx, ny in EDGES
                for d in points
            )
            for layer in layers
        ]
        channels = [
            sum(weight * int(layer.colour[i : i + 2], 16) for weight, layer in zip(weights, layers))
            / sum(weights)
            for i in (0, 2, 4)
        ]
        expected = "".join(f"{round(channel):02X}" for channel in channels)
        _assert_no_shadow_shape(shapes)
        assert len(shapes) == 1 and shapes[0].shadow is not None, _describe(shapes)
        assert shapes[0].shadow.color == expected, (
            f"the fitted colour is {shapes[0].shadow.color}, the layers' weighted {expected}"
        )

    def test_a_ring_between_two_shadows_paints_under_the_box_and_its_shadow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``0 4px 10px rgba(0,0,0,.2), 0 0 0 3px #1B5162, 0 12px 30px rgba(0,0,0,.1)``.

        The first shadow is listed before the ring, so it paints over it: the
        ring is an unfilled rect of its own, 3 px of 1B5162 outside the box,
        under the box, which carries the two shadows fitted to one. Two shapes,
        no more.
        """
        body = (
            '<div class="slide"><div id="box" style="position: absolute; left: 200px; top: 150px; '
            "width: 320px; height: 180px; border-radius: 10px; background: #fff; box-shadow: "
            "0 4px 10px rgba(0,0,0,.2), 0 0 0 3px #1B5162, "
            '0 12px 30px rgba(0,0,0,.1);"></div></div>'
        )
        layers = [CssLayer(0, 4, 10, 0, "000000", 0.2), CssLayer(0, 12, 30, 0, "000000", 0.1)]
        shapes = slide_shapes(_export_one(body, monkeypatch))
        border_box = browser_rect(_document(body), "#box")

        _assert_no_shadow_shape(shapes)
        rings = [position for position, shape in enumerate(shapes) if shape.line == "1B5162"]
        boxes = [position for position, shape in enumerate(shapes) if shape.fill == "FFFFFF"]
        assert len(shapes) == 2 and len(rings) == 1 and len(boxes) == 1, _describe(shapes)
        assert rings[0] < boxes[0], f"the ring (spTree {rings[0]}) paints over the box"
        ring, box = shapes[rings[0]], shapes[boxes[0]]
        assert (
            ring.fill is None
            and ring.shadow is None
            and ring.line_w_pt is not None
            and (abs(ring.line_w_pt - 2.25) <= 0.01)
        ), f"the ring is {ring.line_w_pt} pt, shadow {ring.shadow}"
        _assert_box(
            ring,
            {
                "x": border_box["x"] - 1.5,
                "y": border_box["y"] - 1.5,
                "w": border_box["w"] + 3,
                "h": border_box["h"] + 3,
            },
            INSET_TOLERANCE_PX,
            "the ring",
        )
        assert box.line is None, f"the box is outlined {box.line}"
        down, blur, alpha = _fitted_down(box)
        error = _fit_error(layers, 0, down, blur, alpha)
        for layer in layers:
            assert error < _fit_error(layers, layer.x, layer.y, layer.blur, layer.alpha), (
                f"the box's shadow ({down:.2f}, {blur:.2f}, {alpha:.3f}) is no fit of both layers"
            )

    def test_a_ring_listed_before_the_shadow_paints_over_the_box(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tailwind's ring-then-shadow order: ``0 0 0 3px <translucent>, 0 8px 20px <shadow>``.

        CSS paints the ring, listed first, over the shadow. The box carries its
        one shadow as it is, so the ring, an unfilled rect 3 px wide at alpha
        0.3, is drawn over the box, where the box's shadow lies under it (it
        lies outside the border box, so it covers nothing of the box). Two
        shapes: the box, then the ring.
        """
        body = _card("0 0 0 3px rgba(27, 81, 98, 0.3), 0 8px 20px rgba(0, 0, 0, 0.2)")
        shapes = slide_shapes(_export_one(body, monkeypatch))

        _assert_no_shadow_shape(shapes)
        rings = [position for position, shape in enumerate(shapes) if shape.line == "1B5162"]
        boxes = [position for position, shape in enumerate(shapes) if shape.fill == "FFFFFF"]
        assert len(shapes) == 2 and len(rings) == 1 and len(boxes) == 1, _describe(shapes)
        assert boxes[0] < rings[0], (
            f"the box (spTree {boxes[0]}) and its shadow paint over the ring ({rings[0]})"
        )
        assert shapes[rings[0]].shadow is None, "the ring casts a shadow"
        _assert_shadow(shapes[boxes[0]], Layer("000000", 0.2, 20, 8), "the box's own shadow")

    @pytest.mark.parametrize(
        "place", ["panel", "under-a-neighbours-shadow", "rounded-corner", "turned"]
    )
    def test_a_translucent_box_carries_its_own_shadow(
        self, monkeypatch: pytest.MonkeyPatch, place: str
    ) -> None:
        """A translucent box keeps its one shadow on itself, wherever it lies; nothing is added.

        On a CDEDE1 panel; under a neighbour's long shadow; in the corner of a
        panel rounded 60 px; turned 30 degrees. Each is one shape at alpha
        0.4, carrying ``0 4px 12px rgba(0,0,0,.25)`` (turned with it, at 120
        degrees, when it is turned). Both apps draw that shadow scaled by the
        fill's alpha and through it (B2, measured): the box as it was exported
        before the shadow shapes. No shape is drawn for a shadow alone.
        """
        glass = "background: rgba(255, 255, 255, 0.4); box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);"
        box = (
            '<div id="glass" style="position: absolute; left: 380px; top: 100px; width: 280px; '
            f'height: 140px; {glass}"></div>'
        )
        if place == "panel":
            body = f'<div class="slide">{PANEL}{box}</div></div>'
        elif place == "under-a-neighbours-shadow":
            neighbour = (
                '<div style="position: absolute; left: 40px; top: 40px; width: 300px; '
                "height: 200px; background: rgba(255, 255, 255, 0.4); "
                'box-shadow: 0 24px 48px rgba(0, 0, 0, 0.35);"></div>'
            )
            body = f'<div class="slide">{PANEL}{neighbour}{box}</div></div>'
        elif place == "rounded-corner":
            body = (
                '<div class="slide"><div style="position: absolute; left: 100px; top: 100px; '
                'width: 600px; height: 400px; border-radius: 60px; background: #CDEDE1;">'
                '<div style="position: absolute; left: 4px; top: 4px; width: 200px; '
                f'height: 120px; {glass}"></div></div></div>'
            )
        else:
            body = (
                f'<div class="slide">{PANEL}<div style="position: absolute; left: 220px; '
                f'top: 120px; width: 300px; height: 160px; transform: rotate(30deg); {glass}">'
                "</div></div></div>"
            )
        shapes = slide_shapes(_export_one(body, monkeypatch))

        _assert_no_shadow_shape(shapes)
        glasses = [
            shape
            for shape in shapes
            if shape.fill == "FFFFFF" and shape.shadow is not None and shape.shadow.blur_px < 20
        ]
        assert len(glasses) == 1, f"expected the box once, with its shadow:\n{_describe(shapes)}"
        glass_shape = glasses[0]
        assert (
            glass_shape.fill_alpha is not None
            and abs(glass_shape.fill_alpha - 0.4) <= ALPHA_TOLERANCE
        )
        shadow = glass_shape.shadow
        angle = 120 if place == "turned" else 90
        assert (
            abs(shadow.alpha - 0.25) <= ALPHA_TOLERANCE
            and abs(shadow.blur_px - 12) <= SHADOW_LENGTH_TOLERANCE_PX
            and abs(shadow.dist_px - 4) <= SHADOW_LENGTH_TOLERANCE_PX
            and abs(shadow.angle - angle) <= SHADOW_ANGLE_TOLERANCE_DEG
        ), f"the box's own shadow is {shadow}"

    @pytest.mark.parametrize("box", ["frame", "bordered", "wrapper-on-the-slide"])
    def test_an_unfilled_box_casts_no_shadow(
        self, monkeypatch: pytest.MonkeyPatch, box: str
    ) -> None:
        """A box that paints no fill casts no shadow, and no shape is drawn for one.

        An unfilled rounded frame with ``--shadow-sm`` holding a coral child
        (the data-table wrapper's pattern) on the panel; an unfilled box with a
        1 px border on the panel (the design system's ``.med-frame``); the
        frame directly on the slide. Neither app casts a shadow from an
        unfilled shape, and an outline's own shadow would be a thin frame of
        itself, which the browser does not paint. So no shape carries a
        shadow, and the slide holds only what the browser paints: the panel,
        the child and the border.
        """
        frame = (
            '<div style="position: absolute; left: 40px; top: 40px; width: 300px; height: 160px; '
            f'border-radius: 8px; overflow: hidden; box-shadow: {SHADOW_SM};">'
            '<div style="height: 160px; background: #FF5F46;"></div></div>'
        )
        if box == "frame":
            body = f'<div class="slide">{PANEL}{frame}</div></div>'
            painted = {"CDEDE1", "FF5F46"}
        elif box == "bordered":
            body = (
                f'<div class="slide">{PANEL}<div style="position: absolute; left: 60px; top: 60px; '
                "width: 280px; height: 140px; border: 1px solid #DCE0E2; border-radius: 12px; "
                f'box-shadow: {SHADOW_SM};"></div></div></div>'
            )
            painted = {"CDEDE1", "DCE0E2"}
        else:
            body = f'<div class="slide">{frame}</div>'
            painted = {"FF5F46"}
        shapes = slide_shapes(_export_one(body, monkeypatch))

        _assert_no_shadow_shape(shapes)
        casting = [shape for shape in shapes if shape.shadow is not None]
        assert casting == [], f"a shape casts a shadow:\n{_describe(casting)}"
        assert {shape.fill or shape.line for shape in shapes} == painted and len(shapes) == len(
            painted
        ), f"expected exactly what the browser paints, {sorted(painted)}:\n{_describe(shapes)}"


# ---------------------------------------------------------------------------
# Corners of different radii (D11)
# ---------------------------------------------------------------------------

CORNERS = ("top-left", "top-right", "bottom-right", "bottom-left")
# The corner a custom path's quarter arc rounds, by its start angle (60000ths of
# a degree, clockwise from 3 o'clock): the path runs clockwise from the top edge.
ARC_CORNERS = {
    270 * 60000: "top-right",
    0: "bottom-right",
    90 * 60000: "bottom-left",
    180 * 60000: "top-left",
}
QUARTER_TURN = 90 * 60000
# A preset adjustment agrees with its radius over the short side within EMU rounding.
ADJ_TOLERANCE = 2
# Radii and vertices agree with the browser's within EMU and arc rounding.
RADIUS_TOLERANCE_PX = 0.05
VERTEX_TOLERANCE_PX = 0.1


def _mixed_export(body: str, monkeypatch: pytest.MonkeyPatch, *, target: str | None = None):
    """(shapes, their XML elements, the browser's document) for one exported slide."""
    pptx, failures = export_slides([body], css=DECK_CSS, monkeypatch=monkeypatch, target=target)
    assert failures == [] and pptx, f"the export rejected the slide: {failures}"
    return slide_shapes(pptx), slide_shape_elements(pptx), _document(body)


def _adjustments(element: etree._Element) -> dict[str, int]:
    """A preset shape's adjustments, by guide name."""
    guides = element.iterfind("p:spPr/a:prstGeom/a:avLst/a:gd", NAMESPACES)
    return {guide.get("name"): int(guide.get("fmla").removeprefix("val ")) for guide in guides}


def _arc_radii(element: etree._Element) -> dict[str, tuple[float, float]]:
    """Each corner's (horizontal, vertical) radius as a custom path's quarter arc draws it, px.

    A corner no arc rounds is square, (0, 0). Every arc is a quarter turn clockwise.
    """
    radii = {corner: (0.0, 0.0) for corner in CORNERS}
    for arc in element.iterfind("p:spPr/a:custGeom/a:pathLst/a:path/a:arcTo", NAMESPACES):
        assert int(arc.get("swAng")) == QUARTER_TURN, f"an arc sweeps {arc.get('swAng')}"
        corner = ARC_CORNERS[int(arc.get("stAng"))]
        radii[corner] = (int(arc.get("wR")) / EMU_PER_PX, int(arc.get("hR")) / EMU_PER_PX)
    return radii


def _path_vertices(element: etree._Element, shape: Shape) -> list[tuple[float, float]]:
    """Every point of a custom path, in slide px (its space is its EMU)."""
    return [
        (shape.x + int(point.get("x")) / EMU_PER_PX, shape.y + int(point.get("y")) / EMU_PER_PX)
        for point in element.iterfind("p:spPr/a:custGeom/a:pathLst/a:path//a:pt", NAMESPACES)
    ]


def _corner_centres(box: dict, radii: dict) -> dict[str, tuple[float, float, float, float]]:
    """Each rounded corner's arc: (centre x, centre y, horizontal radius, vertical radius)."""
    centres = {}
    for corner, (horizontal, vertical) in radii.items():
        if not (horizontal > 0 and vertical > 0):
            continue
        left, top = "left" in corner, "top" in corner
        centre_x = box["x"] + horizontal if left else box["x"] + box["w"] - horizontal
        centre_y = box["y"] + vertical if top else box["y"] + box["h"] - vertical
        centres[corner] = (centre_x, centre_y, horizontal, vertical)
    return centres


def _beyond(corner: str, centre: tuple, point: tuple[float, float]) -> bool:
    """Whether ``point`` lies past a corner arc's centre on both axes, towards the corner."""
    centre_x, centre_y = centre[0], centre[1]
    outward_x = point[0] < centre_x if "left" in corner else point[0] > centre_x
    outward_y = point[1] < centre_y if "top" in corner else point[1] > centre_y
    return outward_x and outward_y


def _ellipse_distance(centre: tuple, point: tuple[float, float]) -> float:
    """How far ``point`` lies from a corner's arc, along the ray from its centre, px."""
    centre_x, centre_y, horizontal, vertical = centre
    reach = math.hypot((point[0] - centre_x) / horizontal, (point[1] - centre_y) / vertical)
    return abs(reach - 1) * math.hypot(point[0] - centre_x, point[1] - centre_y) / max(reach, 1e-9)


def _inside_corners(point: tuple[float, float], box: dict, radii: dict) -> bool:
    """Whether ``point`` lies in ``box``, each corner rounded by its own radii, give or take."""
    x, y = point
    tolerance = VERTEX_TOLERANCE_PX
    if not (
        box["x"] - tolerance <= x <= box["x"] + box["w"] + tolerance
        and box["y"] - tolerance <= y <= box["y"] + box["h"] + tolerance
    ):
        return False
    for corner, centre in _corner_centres(box, radii).items():
        if not _beyond(corner, centre, point):
            continue
        inside = math.hypot((x - centre[0]) / centre[2], (y - centre[1]) / centre[3]) <= 1
        if not inside and _ellipse_distance(centre, point) > tolerance:
            return False
    return True


def _on_outline(point: tuple[float, float], box: dict, radii: dict) -> bool:
    """Whether ``point`` lies on the outline of ``box`` with its corners rounded by ``radii``."""
    for corner, centre in _corner_centres(box, radii).items():
        if _beyond(corner, centre, point):
            return _ellipse_distance(centre, point) <= VERTEX_TOLERANCE_PX
    x, y = point
    edges = (
        abs(x - box["x"]),
        abs(x - box["x"] - box["w"]),
        abs(y - box["y"]),
        abs(y - box["y"] - box["h"]),
    )
    return _inside_corners(point, box, radii) and min(edges) <= VERTEX_TOLERANCE_PX


def _has_vertex(points: list[tuple[float, float]], at: tuple[float, float]) -> bool:
    return any(math.hypot(x - at[0], y - at[1]) <= VERTEX_TOLERANCE_PX for x, y in points)


def _walk_path(element: etree._Element, shape: Shape) -> list[dict]:
    """A custom path's segments in order, walked as the apps draw it, in slide px.

    Each is {kind, start, end}: 'move', 'line' and 'close' (back to the move's
    point), and 'arc', which also holds its centre, its (horizontal, vertical)
    radii, its middle point and the corner its start angle names. An arcTo
    starts at the current point, which lies on its ellipse at its start angle,
    so its centre is that point less the radii along the start angle, and it
    ends at the start angle plus its sweep (angles clockwise from 3 o'clock).
    """
    path = element.find("p:spPr/a:custGeom/a:pathLst/a:path", NAMESPACES)
    assert path is not None, "the shape holds no custom path"
    segments: list[dict] = []
    current = start = None
    for command in path:
        name = etree.QName(command).localname
        if name in ("moveTo", "lnTo"):
            point = command.find("a:pt", NAMESPACES)
            end = (
                shape.x + int(point.get("x")) / EMU_PER_PX,
                shape.y + int(point.get("y")) / EMU_PER_PX,
            )
            if name == "moveTo":
                start = end
            segments.append(
                {"kind": "move" if name == "moveTo" else "line", "start": current, "end": end}
            )
            current = end
        elif name == "arcTo":
            horizontal = int(command.get("wR")) / EMU_PER_PX
            vertical = int(command.get("hR")) / EMU_PER_PX
            angle = math.radians(int(command.get("stAng")) / 60000)
            sweep = math.radians(int(command.get("swAng")) / 60000)
            centre = (
                current[0] - horizontal * math.cos(angle),
                current[1] - vertical * math.sin(angle),
            )

            def at(theta: float, centre=centre, horizontal=horizontal, vertical=vertical):
                return (
                    centre[0] + horizontal * math.cos(theta),
                    centre[1] + vertical * math.sin(theta),
                )

            segments.append(
                {
                    "kind": "arc",
                    "start": current,
                    "end": at(angle + sweep),
                    "middle": at(angle + sweep / 2),
                    "centre": centre,
                    "radii": (horizontal, vertical),
                    "corner": ARC_CORNERS.get(int(command.get("stAng"))),
                }
            )
            current = segments[-1]["end"]
        elif name == "close":
            segments.append({"kind": "close", "start": current, "end": start})
            current = start
    return segments


def _misdrawn(segments: list[dict], box: dict, radii: dict) -> list[str]:
    """How a walked custom path (_walk_path) strays from ``box`` with its corners rounded by
    ``radii``: an arc not centred on its CSS corner's centre or not of its radii, a corner CSS
    rounds with no arc, a vertex, a straight side's middle or an arc's middle or end off the
    outline, or a close that draws a side of its own. Empty when the path is the outline."""
    problems = []
    centres = _corner_centres(box, radii)
    arcs = [segment for segment in segments if segment["kind"] == "arc"]
    if sorted(arc["corner"] or "?" for arc in arcs) != sorted(centres):
        problems.append(f"arcs at {[arc['corner'] for arc in arcs]}, CSS rounds {sorted(centres)}")
    for segment in segments:
        kind, start, end = segment["kind"], segment["start"], segment["end"]
        if kind == "arc":
            expected = centres.get(segment["corner"])
            if (
                expected is None
                or math.hypot(
                    segment["centre"][0] - expected[0], segment["centre"][1] - expected[1]
                )
                > VERTEX_TOLERANCE_PX
                or any(
                    abs(a - b) > RADIUS_TOLERANCE_PX for a, b in zip(segment["radii"], expected[2:])
                )
            ):
                problems.append(
                    f"the {segment['corner']} arc is centred at {segment['centre']} with radii "
                    f"{segment['radii']}; CSS's is {expected}"
                )
            points = (segment["middle"], end)
        elif kind == "close":
            if math.hypot(end[0] - start[0], end[1] - start[1]) > VERTEX_TOLERANCE_PX:
                problems.append(f"the path closes with a side from {start} to {end}")
            points = ()
        elif kind == "line":
            points = (start, ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2), end)
        else:
            points = (end,)
        problems += [
            f"a {kind}'s point {point} is off the outline"
            for point in points
            if not _on_outline(point, box, radii)
        ]
    return problems


def _circles(*radii: float) -> dict[str, tuple[float, float]]:
    """Corner radii top left, top right, bottom right, bottom left, each a circle's."""
    return {corner: (radius, radius) for corner, radius in zip(CORNERS, radii)}


# (border-radius, width, height, each corner's (horizontal, vertical) radius): boxes no
# preset draws exactly, so each is a custom path of one quarter arc per rounded corner.
CUSTOM_CORNERS = {
    "left-only": ("16px 0 0 16px", 200, 60, _circles(16, 0, 0, 16)),
    "all-different": ("4px 12px 24px 36px", 240, 120, _circles(4, 12, 24, 36)),
    "elliptical": (
        "48px 0 0 0 / 24px 0 0 0",
        240,
        120,
        {"top-left": (48, 24), "top-right": (0, 0), "bottom-right": (0, 0), "bottom-left": (0, 0)},
    ),
    # Its 16 px corners are past half its 20 px height, which round2SameRect pins them to.
    "top-past-half-the-short-side": ("16px 16px 0 0", 300, 20, _circles(16, 16, 0, 0)),
    # The same past round1Rect's and round2DiagRect's pin.
    "top-right-past-half-the-short-side": ("0 16px 0 0", 300, 20, _circles(0, 16, 0, 0)),
    "diagonal-past-half-the-short-side": ("16px 0", 300, 20, _circles(16, 0, 16, 0)),
}

# (border-radius, width, height, the preset, each adjustment as a share of the short side):
# boxes a preset draws exactly, each corner a circle of at most half the short side.
PRESET_CORNERS = {
    "top-and-bottom-pairs": (
        "16px 16px 4px 4px",
        240,
        120,
        "round2SameRect",
        {"adj1": 16 / 120, "adj2": 4 / 120},
    ),
    "top-right-only": ("0 16px 0 0", 240, 120, "round1Rect", {"adj": 16 / 120}),
    "one-diagonal-pair": ("16px 0", 240, 120, "round2DiagRect", {"adj1": 16 / 120, "adj2": 0}),
    "two-diagonal-pairs": (
        "24px 8px",
        240,
        120,
        "round2DiagRect",
        {"adj1": 24 / 120, "adj2": 8 / 120},
    ),
    "the-other-diagonal-pair": (
        "0 20px",
        240,
        120,
        "round2DiagRect",
        {"adj1": 0, "adj2": 20 / 120},
    ),
}


@pytest.mark.slow
@requires_huashu_sidecar
class TestMixedCornerRadii:
    def test_a_top_rounded_header_is_the_preset_that_rounds_its_top_corners_alone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 360x60 card header, ``border-radius: 16px 16px 0 0``: ``round2SameRect``.

        Its top corners round by 16 px and its bottom ones are square: adj1 is
        16 px over the 60 px short side, adj2 0, at the browser rect. Before,
        one roundRect rounded all four corners by 16 px.
        """
        body = (
            '<div class="slide"><div id="head" style="position: absolute; left: 80px; top: 100px; '
            'width: 360px; height: 60px; border-radius: 16px 16px 0 0; background: #0B2026;">'
            "</div></div>"
        )
        shapes, elements, document = _mixed_export(body, monkeypatch)
        position, head = _filled(shapes, "0B2026")
        assert head.geometry == "round2SameRect", (
            f"the header is a {head.geometry}, not round2SameRect:\n{_describe(shapes)}"
        )
        adjustments = _adjustments(elements[position])
        expected = {"adj1": round(16 / 60 * 100000), "adj2": 0}
        assert set(adjustments) == set(expected) and all(
            abs(adjustments[name] - value) <= ADJ_TOLERANCE for name, value in expected.items()
        ), f"the header's adjustments are {adjustments}, expected {expected}"
        _assert_box(head, browser_rect(document, "#head"), BOX_TOLERANCE_PX, "the header")

    @pytest.mark.parametrize("case", tuple(CUSTOM_CORNERS))
    def test_corners_no_preset_draws_are_each_their_own_quarter_arc(
        self, monkeypatch: pytest.MonkeyPatch, case: str
    ) -> None:
        """Left-only, all-different, elliptical and too-deep corners: one arc per rounded corner.

        The box is a custom path at the browser rect whose quarter arcs round
        exactly the corners CSS rounds, each by its own horizontal and vertical
        radius, and leave the others square.
        """
        radius, width, height, expected = CUSTOM_CORNERS[case]
        body = (
            '<div class="slide"><div id="box" style="position: absolute; left: 80px; top: 100px; '
            f"width: {width}px; height: {height}px; border-radius: {radius}; "
            'background: #2E7D6B;"></div></div>'
        )
        shapes, elements, document = _mixed_export(body, monkeypatch)
        position, box = _filled(shapes, "2E7D6B")
        assert box.geometry == "custGeom", (
            f"the {case} box is a {box.geometry}, not a custom path:\n{_describe(shapes)}"
        )
        drawn = _arc_radii(elements[position])
        wrong = {
            corner: drawn[corner]
            for corner in CORNERS
            if any(
                abs(a - b) > RADIUS_TOLERANCE_PX for a, b in zip(drawn[corner], expected[corner])
            )
        }
        assert not wrong, f"the {case} box rounds its corners {drawn}, expected {expected}"
        rect = browser_rect(document, "#box")
        _assert_box(box, rect, BOX_TOLERANCE_PX, f"the {case} box")
        problems = _misdrawn(_walk_path(elements[position], box), rect, expected)
        assert not problems, f"the {case} box's path is not CSS's outline:\n  " + "\n  ".join(
            problems
        )

    @pytest.mark.parametrize("case", tuple(PRESET_CORNERS))
    def test_corners_a_preset_draws_exactly_are_that_preset(
        self, monkeypatch: pytest.MonkeyPatch, case: str
    ) -> None:
        """A top pair and a bottom pair, a top-right corner alone, one or two diagonal pairs.

        Each is the preset that draws it exactly, its adjustments each radius
        over the short side, at the browser rect: ``round2SameRect`` (adj1 the
        top corners, adj2 the bottom), ``round1Rect`` (adj, the top right) and
        ``round2DiagRect`` (adj1 the top left and bottom right, adj2 the top
        right and bottom left).
        """
        radius, width, height, preset, expected = PRESET_CORNERS[case]
        body = (
            '<div class="slide"><div id="box" style="position: absolute; left: 80px; top: 100px; '
            f"width: {width}px; height: {height}px; border-radius: {radius}; "
            'background: #2E7D6B;"></div></div>'
        )
        shapes, elements, document = _mixed_export(body, monkeypatch)
        position, box = _filled(shapes, "2E7D6B")
        assert box.geometry == preset, (
            f"the {case} box is a {box.geometry}, not {preset}:\n{_describe(shapes)}"
        )
        adjustments = _adjustments(elements[position])
        wanted = {name: round(share * 100000) for name, share in expected.items()}
        assert set(adjustments) == set(wanted) and all(
            abs(adjustments[name] - value) <= ADJ_TOLERANCE for name, value in wanted.items()
        ), f"the {case} box's adjustments are {adjustments}, expected {wanted}"
        _assert_box(box, browser_rect(document, "#box"), BOX_TOLERANCE_PX, f"the {case} box")

    def test_a_bordered_top_rounded_box_strokes_its_corners_on_the_borders_centre_line(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 2 px border on ``16px 16px 0 0``: the preset inset by 1 px, its top radius 15 px.

        The stroke is centred on the shape's edge, so the shape is the border
        box inset by half the border, and each corner's radius the border
        radius less half the border (the stroke-centre rule, per corner).
        """
        body = (
            '<div class="slide"><div id="card" style="position: absolute; left: 80px; top: 100px; '
            "box-sizing: border-box; width: 200px; height: 80px; border-radius: 16px 16px 0 0; "
            'background: #FFFFFF; border: 2px solid #FF3621;"></div></div>'
        )
        shapes, elements, document = _mixed_export(body, monkeypatch)
        position, card = _filled(shapes, "FFFFFF")
        border_box = browser_rect(document, "#card")
        assert (border_box["w"], border_box["h"]) == (200.0, 80.0), (
            f"fixture drift: the card's border box measured {border_box}"
        )
        inset = {
            "x": border_box["x"] + 1,
            "y": border_box["y"] + 1,
            "w": border_box["w"] - 2,
            "h": border_box["h"] - 2,
        }
        assert card.geometry == "round2SameRect" and card.line == "FF3621", (
            f"the card is a {card.geometry} outlined {card.line}:\n{_describe(shapes)}"
        )
        adjustments = _adjustments(elements[position])
        expected = round(15 / 78 * 100000)
        assert abs(adjustments.get("adj1", -1) - expected) <= ADJ_TOLERANCE, adjustments
        assert adjustments.get("adj2") == 0, adjustments
        _assert_box(card, inset, INSET_TOLERANCE_PX, "the card, inset by half its border")

    def test_a_clip_cutting_a_top_left_rounded_box_keeps_its_square_corners_square(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An overflow box cuts a box rounded only at its top left: the cut keeps each corner.

        What the clip shows is one custom path whose every vertex lies inside
        the box with its own corners, with vertices along the 24 px top-left
        arc and one at the square bottom-left corner itself.
        """
        body = (
            '<div class="slide"><div style="position: absolute; left: 80px; top: 100px; '
            'width: 300px; height: 200px; overflow: hidden;">'
            '<div id="cut" style="position: absolute; left: 0; top: 40px; width: 400px; '
            'height: 100px; border-radius: 24px 0 0 0; background: #2E7D6B;"></div></div></div>'
        )
        shapes, elements, document = _mixed_export(body, monkeypatch)
        position, cut = _filled(shapes, "2E7D6B")
        assert cut.geometry == "custGeom", f"the cut box is a {cut.geometry}:\n{_describe(shapes)}"
        box = browser_rect(document, "#cut")
        radii = _circles(24, 0, 0, 0)
        points = _path_vertices(elements[position], cut)
        outside = [point for point in points if not _inside_corners(point, box, radii)]
        centre = _corner_centres(box, radii)["top-left"]
        on_arc = [
            point
            for point in points
            if _beyond("top-left", centre, point) and _ellipse_distance(centre, point) <= 0.1
        ]
        assert not outside and on_arc, f"vertices outside {outside[:4]}, on the arc {len(on_arc)}"
        assert _has_vertex(points, (box["x"], box["y"] + box["h"])), (
            f"the square bottom-left corner {(box['x'], box['y'] + box['h'])} is no vertex"
        )

    @pytest.mark.parametrize(
        ("frame_place", "frame_radius"),
        [("left: 0; bottom: 0;", "0"), ("left: 0; top: 0;", "24px 24px 0 0")],
        ids=["square-frame-at-the-square-corner", "rounded-frame-at-the-rounded-corner"],
    )
    def test_an_unfilled_shadowed_frame_on_a_top_rounded_panel_casts_no_shadow(
        self, monkeypatch: pytest.MonkeyPatch, frame_place: str, frame_radius: str
    ) -> None:
        """An unfilled shadowed frame on a panel rounded ``24px 24px 0 0``: no shadow, no shape.

        A square frame in the panel's square bottom-left corner, and a frame
        rounded as the panel is in its rounded top-left corner. The frame
        paints no fill, so it casts no shadow, and no shape is drawn for its
        layers: the slide holds the panel and the frame's coral child alone.
        """
        body = (
            '<div class="slide"><div style="position: absolute; left: 80px; top: 80px; '
            'width: 600px; height: 400px; border-radius: 24px 24px 0 0; background: #CDEDE1;">'
            f'<div style="position: absolute; {frame_place} width: 200px; height: 100px; '
            f'border-radius: {frame_radius}; overflow: hidden; box-shadow: {SHADOW_SM};">'
            '<div style="height: 100px; background: #FF5F46;"></div></div></div></div>'
        )
        shapes, _, _ = _mixed_export(body, monkeypatch)
        _assert_no_shadow_shape(shapes)
        assert [shape for shape in shapes if shape.shadow is not None] == [], _describe(shapes)
        assert sorted(shape.fill for shape in shapes) == ["CDEDE1", "FF5F46"], _describe(shapes)

    def test_the_google_deck_dots_a_top_rounded_border_along_its_own_corners(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """For Google Slides a dotted border is a stroke of its own: along the box's own corners.

        The 2 px dotted border of a ``16px 16px 0 0`` box is drawn twice along
        its centre line (emit_dotted.cjs): every vertex of that stroke lies on
        the box inset by 1 px with its top corners rounded by 15 px, and its
        square bottom corners are vertices.
        """
        body = (
            '<div class="slide"><div id="dotted" style="position: absolute; left: 80px; '
            "top: 100px; width: 240px; height: 100px; border-radius: 16px 16px 0 0; "
            'background: #FFFFFF; border: 2px dotted #FF3621;"></div></div>'
        )
        shapes, elements, document = _mixed_export(body, monkeypatch, target="gslides")
        strokes = [
            (position, shape)
            for position, shape in enumerate(shapes)
            if shape.geometry == "custGeom" and shape.line == "FF3621" and shape.fill is None
        ]
        assert len(strokes) == 1, f"expected one dotted stroke:\n{_describe(shapes)}"
        position, stroke = strokes[0]
        border_box = browser_rect(document, "#dotted")
        centre_line = {
            "x": border_box["x"] + 1,
            "y": border_box["y"] + 1,
            "w": border_box["w"] - 2,
            "h": border_box["h"] - 2,
        }
        radii = _circles(15, 15, 0, 0)
        points = _path_vertices(elements[position], stroke)
        off = [point for point in points if not _on_outline(point, centre_line, radii)]
        assert not off, f"stroke vertices off the box's own outline: {off[:4]}"
        bottom = centre_line["y"] + centre_line["h"]
        for corner in ((centre_line["x"], bottom), (centre_line["x"] + centre_line["w"], bottom)):
            assert _has_vertex(points, corner), f"the square corner {corner} is no stroke vertex"


EMIT_MODEL_MODULE = (
    Path(__file__).resolve().parents[2] / "services" / "pptx-emit-huashu" / "emit_model.cjs"
)


def _emitted(items: list[dict], tmp_path: Path) -> bytes:
    """The deck ``emit_model.cjs emitSlide`` writes for a model holding ``items``."""
    deck_path = tmp_path / "emitted.pptx"
    model = {
        "width": 1280,
        "height": 720,
        "background": {"color": "FFFFFF"},
        "items": items,
        "captures": [],
        "fonts": {},
        "italicFonts": {},
    }
    node_json(
        "const fs = require('fs'); const pptxgen = require('pptxgenjs');"
        f"const {{ emitSlide }} = require({json.dumps(str(EMIT_MODEL_MODULE))});"
        "const pres = new pptxgen(); pres.layout = 'LAYOUT_WIDE';"
        f"emitSlide(pres, {json.dumps(model)}, new Map(), {{ target: 'pptx' }});"
        "pres.write({ outputType: 'nodebuffer' }).then((deck) => {"
        f"fs.writeFileSync({json.dumps(str(deck_path))}, deck);"
        "process.stdout.write(JSON.stringify({ written: deck.length })); });"
    )
    return deck_path.read_bytes()


@requires_huashu_sidecar
class TestCornerEmitter:
    def test_a_corner_with_one_radius_zero_is_drawn_square(self, tmp_path: Path) -> None:
        """A roundCorners item whose top-right corner is {h: 16, v: 0}: that corner is square.

        CSS draws a corner square when either of its radii is 0, as the
        snapshot writes it and Google's dotted stroke draws it; the custom
        path must not cut it with a chamfer from 16 px along the top edge.
        """
        item = {
            "kind": "shape",
            "id": 0,
            "order": [0],
            "x": 80,
            "y": 100,
            "w": 240,
            "h": 120,
            "geometry": "roundCorners",
            "radius": 0,
            "radii": [{"h": 0, "v": 0}, {"h": 16, "v": 0}, {"h": 24, "v": 24}, {"h": 0, "v": 0}],
            "fill": {"color": "2E7D6B", "alpha": 1},
            "line": None,
            "shadow": None,
            "rotate": None,
        }
        pptx = _emitted([item], tmp_path)
        (shape,) = slide_shapes(pptx)
        (element,) = slide_shape_elements(pptx)
        assert shape.geometry == "custGeom", f"the box is a {shape.geometry}"
        box = {"x": 80, "y": 100, "w": 240, "h": 120}
        problems = _misdrawn(_walk_path(element, shape), box, _circles(0, 0, 24, 0))
        assert not problems, "the half-square corner is not drawn square:\n  " + "\n  ".join(
            problems
        )
