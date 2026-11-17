"""Snapshot engine: boxes, the slide background and CSS paint order.

The snapshot engine (``TELLR_EXPORT_ENGINE=snapshot``) reads the rendered page
and emits each painted box as a native shape:

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
  its settled, opaque state (Review Focus 2);
* the page is read as the browser laid it out: none of the legacy
  preprocess's DOM-mutating passes runs before the snapshot, so a monospace
  code panel keeps each line's own box (PLAN-CORRECTIONS C1).

Every assertion reads the emitted slide XML (``slide_shapes``) and, where the
geometry matters, compares it with the browser's own layout of the very same
document (``browser_rect``). Shapes are identified by a fill colour used once
per slide, so a lookup can only match the element under test.

Gating matches the sibling export suites: needs node, the extracted sidecar
``node_modules`` and a local Chrome/Chromium (skipped otherwise).
"""

from __future__ import annotations

import pytest

from tests.fixtures.export_snapshot_support import (
    DECK_CSS,
    Shape,
    browser_rect,
    export_slides,
    requires_huashu_sidecar,
    slide_background,
    slide_document,
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
    pptx, failures = export_slides([body], css=css, engine="snapshot", monkeypatch=monkeypatch)
    assert failures == [], f"the export rejected the slide: {failures}"
    assert pptx, "the export produced no .pptx bytes"
    return pptx


def _document(body: str, *, css: str = DECK_CSS) -> str:
    """The document ``_export_one`` exported (``export_slides`` names slide 1 ``snapshot-1``)."""
    return slide_document(body, css=css, slide_id="snapshot-1")


def _describe(shapes: list[Shape]) -> str:
    return "\n".join(
        f"  [{position}] {shape.kind} {shape.geometry} fill={shape.fill} alpha={shape.fill_alpha} "
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
        """Review Focus 2: a deck that fades content in exports it opaque.

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
        """PLAN-CORRECTIONS C1: no layout-mutating preprocess pass runs before the snapshot.

        A monospace panel holding one ``<div>`` per code line is exactly what the
        legacy ``flattenMonospaceCodeBlocks`` collapses into a single ``<p>``,
        taking every line's own background with it. The snapshot engine runs
        only the background transfer, so each line's box is still on the page
        when it is read and exports as its own shape.
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
        (today's engine) happens to satisfy the flex half and fails the block half.

        The inline content is an ``inline-block`` chip, which paints in the same
        inline layer as a block's text. Text items arrive in Task 2.
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
