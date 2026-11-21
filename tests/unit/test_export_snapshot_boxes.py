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

import math
from dataclasses import dataclass

import pytest
from lxml import etree

from tests.fixtures.export_snapshot_support import (
    DECK_CSS,
    EMU_PER_PX,
    NAMESPACES,
    Shape,
    browser_rect,
    export_slides,
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

# One shape carries one outer shadow, and neither app casts a shadow from a
# shape it does not fill, or more than a faint one from a translucent fill
# (measured: a fill at alpha 0.5 casts half the shadow, at 0.01 none to the
# eye). So every shadow layer the box's own shape cannot carry is a shape of its
# own under the box, filled so that nothing of it shows but its shadow, and named
# for what it is.
SHADOW_SHAPE_NAME = "Shadow"
# The design system's --shadow-md and --shadow-sm, each two layers (deck.css).
SHADOW_MD = "0 2px 6px rgba(27,49,57,.08), 0 8px 20px rgba(27,49,57,.08)"
SHADOW_SM = "0 1px 2px rgba(27,49,57,.06), 0 1px 3px rgba(27,49,57,.08)"
# A solid ground for the boxes under test, so what lies beneath them is one colour.
PANEL_FILL = "CDEDE1"
PANEL = (
    '<div id="panel" style="position: absolute; left: 80px; top: 80px; width: 1000px; '
    'height: 520px; background: #CDEDE1;">'
)
# The slide root's ground in the corpus deck (deck.css :root --paper, .slide).
DECK_PAPER_RULE = "--paper: #F9F7F4;"
SHADOW_ANGLE_TOLERANCE_DEG = 1
SHADOW_LENGTH_TOLERANCE_PX = 0.05


@dataclass(frozen=True)
class Layer:
    """One painted box-shadow layer as an exported shadow: colour, alpha, blur, offset down."""

    colour: str
    alpha: float
    blur_px: float
    down_px: float


def _assert_shadow(shape: Shape, layer: Layer, what: str) -> None:
    shadow = shape.shadow
    assert shadow is not None and shadow.kind == "outer", f"{what}: no outer shadow ({shadow})"
    assert shadow.color == layer.colour, f"{what}: shadow colour {shadow.color}, not {layer.colour}"
    assert shadow.alpha is not None and abs(shadow.alpha - layer.alpha) <= ALPHA_TOLERANCE, (
        f"{what}: shadow alpha {shadow.alpha}, not {layer.alpha}"
    )
    assert abs(shadow.blur_px - layer.blur_px) <= SHADOW_LENGTH_TOLERANCE_PX, (
        f"{what}: shadow blur {shadow.blur_px} px, not {layer.blur_px}"
    )
    assert abs(shadow.dist_px - layer.down_px) <= SHADOW_LENGTH_TOLERANCE_PX and (
        abs(shadow.angle - 90) <= SHADOW_ANGLE_TOLERANCE_DEG
    ), f"{what}: shadow {shadow.dist_px} px at {shadow.angle} degrees, not {layer.down_px} down"


def _shadow_shapes(shapes: list[Shape]) -> list[tuple[int, Shape]]:
    return [
        (position, shape)
        for position, shape in enumerate(shapes)
        if shape.name == SHADOW_SHAPE_NAME
    ]


def _assert_shadow_shape(
    shape: Shape, fill: str, border_box: dict, radius_px: float, layer: Layer, what: str
) -> None:
    """A shadow shape: the box's border box and corner, filled ``fill``, no outline, ``layer``.

    A box with no corner radius (``radius_px`` 0) is a rect.
    """
    assert shape.kind == "shape" and shape.fill == fill and shape.fill_alpha is None, (
        f"{what}: a {shape.kind} filled {shape.fill} at alpha {shape.fill_alpha}, not {fill}"
    )
    assert shape.line is None, f"{what}: outlined {shape.line}"
    _assert_box(shape, border_box, INSET_TOLERANCE_PX, what)
    if not radius_px:
        assert shape.geometry == "rect", (
            f"{what}: a square box's shadow shape is a {shape.geometry}"
        )
        _assert_shadow(shape, layer, what)
        return
    expected_adj = round(radius_px / min(border_box["w"], border_box["h"]) * 100000)
    assert (
        shape.geometry == "roundRect"
        and shape.adj is not None
        and (abs(shape.adj - expected_adj) <= 1000)
    ), f"{what}: a {shape.geometry} with adj {shape.adj}, expected roundRect adj {expected_adj}"
    _assert_shadow(shape, layer, what)


@pytest.mark.slow
@requires_huashu_sidecar
class TestShadowLayers:
    def test_each_further_layer_is_a_shadow_shape_under_the_box(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The design system's ``--shadow-md`` card: two layers, the second its own shape.

        ``0 2px 6px rgba(27,49,57,.08), 0 8px 20px rgba(27,49,57,.08)`` on a
        white 14 px-radius card. The card keeps the first layer (the one CSS
        paints on top); the second, the long soft tail, is one shape directly
        under the card, named "Shadow": the card's border box and corner, filled
        in the card's own white, which the card hides, with no outline, casting
        the second layer, 20 px of blur 8 px down. Nothing else is drawn.
        """
        body = (
            '<div class="slide"><div id="card" style="position: absolute; left: 100px; top: 100px; '
            "width: 300px; height: 200px; border-radius: 14px; background: #fff; "
            f"box-shadow: {SHADOW_MD};"
            '"></div></div>'
        )
        shapes = slide_shapes(_export_one(body, monkeypatch))
        border_box = browser_rect(_document(body), "#card")

        hidden = _shadow_shapes(shapes)
        cards = [
            (position, shape)
            for position, shape in enumerate(shapes)
            if shape.fill == "FFFFFF" and shape.name != SHADOW_SHAPE_NAME
        ]
        assert len(shapes) == 2 and len(hidden) == 1 and len(cards) == 1, (
            f"expected the card and one shadow shape:\n{_describe(shapes)}"
        )
        (card_position, card), (shadow_position, shadow_shape) = cards[0], hidden[0]
        _assert_box(card, border_box, INSET_TOLERANCE_PX, "the card")
        _assert_shadow(card, Layer("1B3139", 0.08, 6, 2), "the card's own shadow")
        _assert_shadow_shape(
            shadow_shape, "FFFFFF", border_box, 14, Layer("1B3139", 0.08, 20, 8), "the second layer"
        )
        assert shadow_position == card_position - 1, (
            f"the second layer (spTree {shadow_position}) is not directly under the card "
            f"({card_position})"
        )

    def test_layers_and_rings_paint_in_css_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Three layers, a ring between two shadows: each paints where CSS lists it.

        ``0 4px 10px rgba(0,0,0,.2), 0 0 0 3px #1B5162, 0 12px 30px
        rgba(0,0,0,.1)`` on a white box: CSS paints the last listed lowest, so
        back to front the third layer's shadow shape, the ring, then the box
        with the first layer. The ring is no outline of the box, because the
        first layer's shadow paints over it: it is an unfilled rect of its own,
        3 px of 1B5162 outside the box.
        """
        body = (
            '<div class="slide"><div id="box" style="position: absolute; left: 200px; top: 150px; '
            "width: 320px; height: 180px; border-radius: 10px; background: #fff; box-shadow: "
            "0 4px 10px rgba(0,0,0,.2), 0 0 0 3px #1B5162, "
            '0 12px 30px rgba(0,0,0,.1);"></div></div>'
        )
        shapes = slide_shapes(_export_one(body, monkeypatch))
        border_box = browser_rect(_document(body), "#box")

        hidden = _shadow_shapes(shapes)
        rings = [
            (position, shape)
            for position, shape in enumerate(shapes)
            if shape.fill is None and shape.line == "1B5162"
        ]
        boxes = [
            (position, shape)
            for position, shape in enumerate(shapes)
            if shape.fill == "FFFFFF" and shape.name != SHADOW_SHAPE_NAME
        ]
        assert len(shapes) == 3 and len(hidden) == 1 and len(rings) == 1 and len(boxes) == 1, (
            f"expected a shadow shape, a ring and the box:\n{_describe(shapes)}"
        )
        assert hidden[0][0] < rings[0][0] < boxes[0][0], (
            f"back to front CSS paints the third layer, the ring, then the box with the first; "
            f"emitted at {hidden[0][0]}, {rings[0][0]}, {boxes[0][0]}"
        )
        box = boxes[0][1]
        assert box.line is None, f"the box is outlined {box.line}: the ring is under the shadow"
        _assert_shadow(box, Layer("000000", 0.2, 10, 4), "the box's own shadow")
        _assert_shadow_shape(
            hidden[0][1], "FFFFFF", border_box, 10, Layer("000000", 0.1, 30, 12), "the third layer"
        )
        ring = rings[0][1]
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
        assert (
            ring.shadow is None
            and ring.line_w_pt is not None
            and abs(ring.line_w_pt - 2.25) <= 0.01
        ), f"the ring is {ring.line_w_pt} pt with shadow {ring.shadow}"

    def test_a_negative_spread_shrinks_its_shadow_shape(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tailwind's ``shadow-md``: its second layer ``0 2px 4px -2px`` shrinks its shape by 2 px.

        A negative spread draws the layer from the border box shrunk by the
        spread, its radius with it (8 - 2 = 6 px), so the shadow shape is that
        box, still under the card. The card's own first layer carries no spread
        (an outer shadow has none).
        """
        body = (
            '<div class="slide"><div id="card" style="position: absolute; left: 100px; top: 100px; '
            "width: 240px; height: 120px; border-radius: 8px; background: #fff; box-shadow: "
            '0 4px 6px -1px rgba(0,0,0,.1), 0 2px 4px -2px rgba(0,0,0,.1);"></div></div>'
        )
        shapes = slide_shapes(_export_one(body, monkeypatch))
        border_box = browser_rect(_document(body), "#card")

        hidden = _shadow_shapes(shapes)
        assert len(hidden) == 1, f"expected one shadow shape:\n{_describe(shapes)}"
        shrunk = {
            "x": border_box["x"] + 2,
            "y": border_box["y"] + 2,
            "w": border_box["w"] - 4,
            "h": border_box["h"] - 4,
        }
        _assert_shadow_shape(
            hidden[0][1], "FFFFFF", shrunk, 6, Layer("000000", 0.1, 4, 2), "the second layer"
        )

    def test_an_unfilled_box_casts_its_layers_from_shapes_in_the_colour_beneath(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unfilled rounded frame with ``--shadow-sm`` on a CDEDE1 panel: both layers drawn.

        The frame paints no background (the data-table wrapper's pattern:
        ``border-radius: 8px; overflow: hidden``, its child filling it). Each
        layer is a shadow shape at the frame's border box and corner, filled
        CDEDE1, the colour the panel paints beneath it, so that it shows
        nothing but its shadow wherever the child does not cover it; back to
        front the second layer, then the first, both over the panel and under
        the child. No other shape carries a shadow.
        """
        body = (
            f'<div class="slide">{PANEL}'
            '<div id="frame" style="position: absolute; left: 40px; top: 40px; width: 300px; '
            f'height: 160px; border-radius: 8px; overflow: hidden; box-shadow: {SHADOW_SM};">'
            '<div style="height: 160px; background: #FF5F46;"></div></div></div></div>'
        )
        shapes = slide_shapes(_export_one(body, monkeypatch))
        border_box = browser_rect(_document(body), "#frame")

        hidden = _shadow_shapes(shapes)
        assert len(hidden) == 2, f"expected two shadow shapes:\n{_describe(shapes)}"
        _assert_shadow_shape(
            hidden[0][1], PANEL_FILL, border_box, 8, Layer("1B3139", 0.08, 3, 1), "the second layer"
        )
        _assert_shadow_shape(
            hidden[1][1], PANEL_FILL, border_box, 8, Layer("1B3139", 0.06, 2, 1), "the first layer"
        )
        panels = [
            position
            for position, shape in enumerate(shapes)
            if shape.fill == PANEL_FILL and shape.name != SHADOW_SHAPE_NAME
        ]
        assert len(panels) == 1, f"expected the panel once:\n{_describe(shapes)}"
        panel = panels[0]
        child, _ = _filled(shapes, "FF5F46")
        assert panel < hidden[0][0] < hidden[1][0] < child, (
            f"expected the panel, the two layers and the child back to front; emitted at {panel}, "
            f"{hidden[0][0]}, {hidden[1][0]}, {child}"
        )
        others = [
            shape
            for shape in shapes
            if shape.shadow is not None and shape.name != SHADOW_SHAPE_NAME
        ]
        assert others == [], f"another shape carries a shadow:\n{_describe(others)}"

    def test_a_translucent_box_casts_its_shadow_from_beneath_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 60 % white box on the panel: its shadow from a CDEDE1 shape under it, none on it.

        Both apps draw a shadow under a translucent fill, so the box itself
        would show its own shadow through it, where the browser shows the
        panel. The box keeps its fill at alpha 0.6 and casts nothing; the shape
        under it, filled CDEDE1 as the panel beneath it, casts the shadow.
        """
        body = (
            f'<div class="slide">{PANEL}'
            '<div id="glass" style="position: absolute; left: 60px; top: 60px; width: 280px; '
            "height: 140px; border-radius: 12px; background: rgba(255, 255, 255, 0.6); "
            'box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);"></div></div></div>'
        )
        shapes = slide_shapes(_export_one(body, monkeypatch))
        border_box = browser_rect(_document(body), "#glass")

        hidden = _shadow_shapes(shapes)
        assert len(hidden) == 1, f"expected one shadow shape:\n{_describe(shapes)}"
        _assert_shadow_shape(
            hidden[0][1], PANEL_FILL, border_box, 12, Layer("000000", 0.25, 12, 4), "the shadow"
        )
        glass_position, glass = _filled(shapes, "FFFFFF")
        assert glass.fill_alpha is not None and abs(glass.fill_alpha - 0.6) <= ALPHA_TOLERANCE, (
            f"the box's fill alpha is {glass.fill_alpha}, not 0.6"
        )
        assert glass.shadow is None, f"the translucent box casts its own shadow {glass.shadow}"
        assert hidden[0][0] < glass_position, "the shadow shape paints over the box"

    def test_an_unfilled_bordered_box_casts_no_shadow_from_its_outline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unfilled box with a 1 px border: the outline casts nothing; a shape under it does.

        The design system's ``.med-frame``. An unfilled outline's shadow is a
        thin shadowed frame in both apps (measured), not the browser's soft
        shadow outside the box. The outline keeps no shadow; one CDEDE1 shape
        at the border box carries it.
        """
        body = (
            f'<div class="slide">{PANEL}'
            '<div id="outlined" style="position: absolute; left: 60px; top: 60px; width: 280px; '
            "height: 140px; border: 1px solid #DCE0E2; border-radius: 12px; "
            'box-shadow: 0 2px 8px rgba(27, 49, 57, 0.08);"></div></div></div>'
        )
        shapes = slide_shapes(_export_one(body, monkeypatch))
        border_box = browser_rect(_document(body), "#outlined")

        hidden = _shadow_shapes(shapes)
        assert len(hidden) == 1, f"expected one shadow shape:\n{_describe(shapes)}"
        _assert_shadow_shape(
            hidden[0][1], PANEL_FILL, border_box, 12, Layer("1B3139", 0.08, 8, 2), "the shadow"
        )
        outlines = [shape for shape in shapes if shape.line == "DCE0E2"]
        assert len(outlines) == 1 and outlines[0].shadow is None and outlines[0].fill is None, (
            f"expected the border once, unfilled and casting nothing:\n{_describe(shapes)}"
        )

    def test_over_a_translucent_panel_its_shapes_take_the_colour_it_shows(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unfilled frame on a 10 % 1B5162 panel over the slide's F9F7F4 paper.

        What lies beneath the frame is the panel's tint over the paper, one
        colour the browser shows: 1B5162 at alpha 0.1 composited over F9F7F4,
        each channel rounded. The frame's shadow shape takes exactly that, so
        it shows nothing but its shadow.
        """
        assert DECK_PAPER_RULE in DECK_CSS, "fixture drift: deck.css changed the slide's paper"
        body = (
            '<div class="slide"><div style="position: absolute; left: 80px; top: 80px; '
            'width: 900px; height: 480px; background: rgba(27, 81, 98, 0.1);">'
            '<div id="frame" style="position: absolute; left: 60px; top: 60px; width: 300px; '
            'height: 160px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);">'
            "</div></div></div>"
        )
        shapes = slide_shapes(_export_one(body, monkeypatch))
        border_box = browser_rect(_document(body), "#frame")

        tint, paper = "1B5162", "F9F7F4"
        channels = [
            round(int(tint[index : index + 2], 16) * 0.1 + int(paper[index : index + 2], 16) * 0.9)
            for index in (0, 2, 4)
        ]
        blended = "".join(f"{channel:02X}" for channel in channels)
        hidden = _shadow_shapes(shapes)
        assert len(hidden) == 1, f"expected one shadow shape:\n{_describe(shapes)}"
        _assert_shadow_shape(
            hidden[0][1], blended, border_box, 8, Layer("000000", 0.2, 8, 2), "the shadow"
        )

    @pytest.mark.parametrize("beneath", ["sibling", "picture-ground"])
    def test_where_no_one_colour_lies_beneath_the_box_keeps_its_shadow(
        self, monkeypatch: pytest.MonkeyPatch, beneath: str
    ) -> None:
        """No shadow shape where its fill could not be the slide beneath it: the box keeps its own.

        An unfilled bordered box over the edge of an earlier FFC000 block (a
        sibling under it), or on a slide whose ground is a picture (a gradient
        ground, which the export rasterises to the slide's background picture):
        a filled shape under the box would hide what shows through it. So the
        box is exported as before: its outline with its first shadow layer,
        and no shadow shape.
        """
        box = (
            '<div id="outlined" style="position: absolute; left: 200px; top: 200px; width: 280px; '
            "height: 140px; border: 1px solid #DCE0E2; "
            'box-shadow: 0 2px 8px rgba(27, 49, 57, 0.08);"></div>'
        )
        if beneath == "sibling":
            body = (
                '<div class="slide"><div style="position: absolute; left: 120px; top: 160px; '
                f'width: 200px; height: 120px; background: #FFC000;"></div>{box}</div>'
            )
        else:
            body = (
                '<div class="slide" style="background: linear-gradient(135deg, #CDEDE1, #1B5162);">'
                f"{box}</div>"
            )
        pptx = _export_one(body, monkeypatch)
        shapes = slide_shapes(pptx)
        if beneath == "picture-ground":
            assert slide_background(pptx) is None, (
                f"fixture drift: the slide's ground is the colour {slide_background(pptx)}"
            )

        assert _shadow_shapes(shapes) == [], f"a shadow shape was drawn:\n{_describe(shapes)}"
        outlines = [shape for shape in shapes if shape.line == "DCE0E2"]
        assert len(outlines) == 1, f"expected the border once:\n{_describe(shapes)}"
        _assert_shadow(outlines[0], Layer("1B3139", 0.08, 8, 2), "the outline's shadow")

    def test_a_ring_listed_before_the_first_shadow_paints_over_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tailwind's ring-then-shadow order: ``0 0 0 3px <translucent>, 0 8px 20px <shadow>``.

        CSS paints the ring, listed first, over the shadow. A box's own shadow
        paints with the box, over any shape under it, so the box carries none
        here: back to front the shadow shape (the box's border box in its white,
        casting the second layer), the ring (an unfilled rect 3 px wide at alpha
        0.3), then the box.
        """
        body = (
            '<div class="slide"><div id="box" style="position: absolute; left: 200px; top: 150px; '
            "width: 320px; height: 180px; border-radius: 10px; background: #fff; box-shadow: "
            '0 0 0 3px rgba(27, 81, 98, 0.3), 0 8px 20px rgba(0, 0, 0, 0.2);"></div></div>'
        )
        shapes = slide_shapes(_export_one(body, monkeypatch))
        border_box = browser_rect(_document(body), "#box")

        hidden = _shadow_shapes(shapes)
        rings = [
            (position, shape)
            for position, shape in enumerate(shapes)
            if shape.fill is None and shape.line == "1B5162"
        ]
        boxes = [
            (position, shape)
            for position, shape in enumerate(shapes)
            if shape.fill == "FFFFFF" and shape.name != SHADOW_SHAPE_NAME
        ]
        assert len(shapes) == 3 and len(hidden) == 1 and len(rings) == 1 and len(boxes) == 1, (
            f"expected a shadow shape, the ring and the box:\n{_describe(shapes)}"
        )
        assert hidden[0][0] < rings[0][0] < boxes[0][0], (
            "back to front CSS paints the shadow, the ring listed before it, then the box; "
            f"emitted at {hidden[0][0]}, {rings[0][0]}, {boxes[0][0]}"
        )
        assert boxes[0][1].shadow is None, (
            f"the box casts {boxes[0][1].shadow}, which would paint over the ring"
        )
        _assert_shadow_shape(
            hidden[0][1], "FFFFFF", border_box, 10, Layer("000000", 0.2, 20, 8), "the shadow"
        )

    def test_a_box_a_lower_shadow_reaches_keeps_its_own_shadow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two translucent boxes on the panel; the first box's long shadow reaches under the second.

        ``#upper``'s shadow (24 px down, 48 px of blur) falls under ``#lower``, so
        the browser shows it through ``#lower``: no one colour lies beneath
        ``#lower``, and a filled shape there would hide that shadow. ``#upper``
        has a shadow shape, filled CDEDE1; ``#lower`` has none and keeps its
        own shadow, as before.
        """
        body = (
            f'<div class="slide">{PANEL}'
            '<div id="upper" style="position: absolute; left: 40px; top: 40px; width: 300px; '
            "height: 200px; background: rgba(255, 255, 255, 0.4); "
            'box-shadow: 0 24px 48px rgba(0, 0, 0, 0.35);"></div>'
            '<div id="lower" style="position: absolute; left: 380px; top: 100px; width: 300px; '
            "height: 200px; background: rgba(255, 255, 255, 0.4); "
            'box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);"></div></div></div>'
        )
        document = _document(body)
        shapes = slide_shapes(_export_one(body, monkeypatch))
        upper, lower = browser_rect(document, "#upper"), browser_rect(document, "#lower")

        hidden = _shadow_shapes(shapes)
        assert len(hidden) == 1, f"expected #upper's shadow shape alone:\n{_describe(shapes)}"
        _assert_shadow_shape(
            hidden[0][1], PANEL_FILL, upper, 0, Layer("000000", 0.35, 48, 24), "#upper's shadow"
        )
        boxes = [
            shape
            for shape in shapes
            if shape.fill == "FFFFFF" and abs(shape.x - lower["x"]) <= INSET_TOLERANCE_PX
        ]
        assert len(boxes) == 1, f"expected #lower once:\n{_describe(shapes)}"
        _assert_shadow(boxes[0], Layer("000000", 0.2, 8, 2), "#lower's own shadow")

    def test_a_box_at_a_rounded_panels_corner_keeps_its_own_shadow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A translucent box in the corner of a CDEDE1 panel rounded 60 px.

        The box's own top left corner lies outside the panel's arc, where the
        browser shows the slide's paper through it, not the panel: no one colour
        lies beneath the box. So no shadow shape is drawn, and the box keeps its
        own shadow.
        """
        body = (
            '<div class="slide"><div style="position: absolute; left: 100px; top: 100px; '
            'width: 600px; height: 400px; border-radius: 60px; background: #CDEDE1;">'
            '<div id="cornered" style="position: absolute; left: 4px; top: 4px; width: 200px; '
            "height: 120px; background: rgba(255, 255, 255, 0.5); "
            'box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);"></div></div></div>'
        )
        shapes = slide_shapes(_export_one(body, monkeypatch))

        assert _shadow_shapes(shapes) == [], f"a shadow shape was drawn:\n{_describe(shapes)}"
        _, box = _filled(shapes, "FFFFFF")
        _assert_shadow(box, Layer("000000", 0.2, 8, 2), "the box's own shadow")

    def test_a_turned_translucent_box_keeps_its_own_shadow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A translucent box turned 30 degrees on the panel.

        What lies beneath a turned box is not read (its footprint is no
        unturned rect), so no shadow shape is drawn and the box keeps its own
        shadow, 12 px of blur 4 px along its turned down direction (120
        degrees on the slide).
        """
        body = (
            f'<div class="slide">{PANEL}'
            '<div id="turned" style="position: absolute; left: 220px; top: 120px; width: 300px; '
            "height: 160px; transform: rotate(30deg); background: rgba(255, 255, 255, 0.4); "
            'box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);"></div></div></div>'
        )
        shapes = slide_shapes(_export_one(body, monkeypatch))

        assert _shadow_shapes(shapes) == [], f"a shadow shape was drawn:\n{_describe(shapes)}"
        _, box = _filled(shapes, "FFFFFF")
        assert abs(box.rotation - 30) <= SHADOW_ANGLE_TOLERANCE_DEG, (
            f"fixture drift: the box is turned {box.rotation} degrees"
        )
        shadow = box.shadow
        assert (
            shadow is not None
            and shadow.alpha is not None
            and (
                abs(shadow.alpha - 0.3) <= ALPHA_TOLERANCE
                and abs(shadow.blur_px - 12) <= SHADOW_LENGTH_TOLERANCE_PX
                and abs(shadow.dist_px - 4) <= SHADOW_LENGTH_TOLERANCE_PX
                and abs(shadow.angle - 120) <= SHADOW_ANGLE_TOLERANCE_DEG
            )
        ), f"the turned box's own shadow is {shadow}"


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
    def test_a_shadowed_frame_a_top_rounded_panel_covers_takes_the_panels_colour(
        self, monkeypatch: pytest.MonkeyPatch, frame_place: str, frame_radius: str
    ) -> None:
        """An unfilled shadowed frame the panel (``24px 24px 0 0``) covers: layers in its colour.

        A square frame in the panel's square bottom-left corner, and a frame
        rounded as the panel is in its rounded top-left corner, each lie whole
        on the panel, judged corner by corner: so the frame's two shadow layers
        are shapes filled with the panel's colour. Rounding every corner by the
        largest radius would leave a square corner uncovered, or a rounded
        frame's corner point outside the panel's arc, and drop both layers.
        """
        body = (
            '<div class="slide"><div style="position: absolute; left: 80px; top: 80px; '
            'width: 600px; height: 400px; border-radius: 24px 24px 0 0; background: #CDEDE1;">'
            f'<div style="position: absolute; {frame_place} width: 200px; height: 100px; '
            f'border-radius: {frame_radius}; overflow: hidden; box-shadow: {SHADOW_SM};">'
            '<div style="height: 100px; background: #FF5F46;"></div></div></div></div>'
        )
        shapes, _, _ = _mixed_export(body, monkeypatch)
        hidden = _shadow_shapes(shapes)
        assert len(hidden) == 2 and all(shape.fill == PANEL_FILL for _, shape in hidden), (
            f"expected two shadow shapes filled {PANEL_FILL}:\n{_describe(shapes)}"
        )

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
