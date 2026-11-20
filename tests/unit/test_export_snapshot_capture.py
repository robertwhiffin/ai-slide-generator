"""Snapshot engine: element-isolated 2x captures (Task 7).

What cannot be drawn natively becomes a picture, captured from the original,
untouched page (spec §4). An isolation stylesheet hides every element but the
capture target, the target's rect is screenshotted at device scale 2 on a
transparent background, and the stylesheet is removed. So a picture holds
exactly what the browser painted for that target (the deck's CSS, CSS
variables, webfonts, filters, clipping, opacity) and nothing that merely
overlaps it. The targets are:

* inline ``<svg>`` (charts, icons, legend markers) and ``<canvas>``, captured
  with their subtree (RC4: a standalone SVG serialization loses class and
  variable styles; a script-drawn canvas was missing);
* an ``<img>`` whose source is not a raster ``data:`` image (an SVG logo), or
  that has a ``filter``, a border radius, a ``box-shadow``, ``object-fit``
  cropping or a partial clip. A shadowed image is captured with its rect
  inflated, so the outline is in the picture. A plain raster ``data:`` image is
  embedded as it is;
* box-only targets, whose own box paints what a shape cannot: a gradient or
  ``url()`` background (progress fills, Harvey balls: RC8), or ``filter``,
  ``backdrop-filter``, ``mix-blend-mode``, ``clip-path`` or ``mask`` on a
  painted box. Only the box is captured, its text made transparent, so the
  text and the children stay native and editable. An outer shadow inflates the
  rect by ``max(|offset|) + blur + spread``. ``background-clip: text`` is not a
  box capture (Task 7 addendum C7.2): Task 3 exports gradient text as a solid
  colour run.

A picture holds all its target paints: an outer shadow grows its rect, and so
does a ``filter`` blur or drop shadow (2σ past the edge, the reach a shadow's
blur radius gives). The isolation changes nothing of the target's own
painting: a box target's border and shadow in ``currentColor`` keep their
colour although its text goes transparent, and an SVG part the slide hides
stays hidden although the isolation shows the target's whole subtree.

A target that an ``overflow`` ancestor cuts is captured cut, and its picture's
rect is the target rect intersected with the clip (C7.3). Captured pixels
already carry the target's cumulative opacity, so the picture is shown at the
browser's opacity, not that opacity twice. Repeated exports of one rendered
page are byte-identical (C7.4): the determinism test exports it five times,
three renders each, and pins the corpus deck's fonts, because Google Fonts now
and then serves another DM Sans file and so another page. A 20-slide chart
deck exports inside the sidecar's budget (Review Focus 1).

Isolation must hold against the deck's own CSS (Review Focus 5): a deck rule
``.x { visibility: visible !important }`` loses to the isolation stylesheet's
id-specificity boost. The brief's literal rule, ``.dk-legend { visibility:
visible !important }``, cannot show a leak in fixture 03: the legend lies
below the chart's rect, and the isolation rule's ``*`` matches the legend's
spans directly, so they stay hidden whatever ``.dk-legend`` says. Measured
with the brief's ``isolationCss``: zero leaked pixels even without the boost.
So the hostile rule here is ``.dk-legend, .dk-legend * { visibility: visible
!important }`` on a legend moved over the chart; with the boost dropped it
leaks the legend into the chart picture, and with the boost it does not. A
second hostile rule, ``html > body { background: … !important }``, outranks an
unboosted ``html, body`` reset and would paint the slide ground into every
picture. Two more ways a deck fights the isolation: ``* { transition: all 1s }``
turns the stylesheet's own changes into transitions (a visibility transition
keeps the hidden page visible while it runs), and slide script can replace
what a stylesheet added from the page's own realm, or a target's naming, relies
on (a style element's ``onload``, ``setAttribute``).

A script-drawn canvas must survive to the capture. The export document's chart
initialisation (``build_slide_html``) sizes the canvases once Chart.js is ready,
and setting a canvas's size clears its bitmap, even to the same value; the UI
runs no such step. So it leaves a canvas carrying a width or height attribute
alone (fixture 17's markup sets both; a script drawing at 2x for a sharp
display sets them too) and resizes any other only when its size differs. The
corpus tests need both that and the capture; a companion exports fixture 17's
body without the deck scripts to pin the capture alone.

Pixels are decoded with Pillow and sampled at positions computed from the
browser's own geometry of the very same document (``browser_rect``,
``browser_each_rect``, ``browser_padding_box``): a slide point maps into a
picture's PNG through the picture's emitted rect and the PNG's size. Expected
colours are the fixture CSS's (``tests/fixtures/export_fidelity/deck.css``),
each guarded against drift. Corpus slides are loaded by prefix
(PLAN-CORRECTIONS C4).

Gating matches the sibling export suites: needs node, the extracted sidecar
``node_modules`` and a local Chrome/Chromium (skipped otherwise).
"""

from __future__ import annotations

import base64
import math
import re
import time
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image, ImageChops

from src.services import pptx_from_html_huashu
from tests.fixtures.export_snapshot_support import (
    CORPUS_DECK,
    DECK_CSS,
    NAMESPACES,
    PERCENT_UNITS,
    Shape,
    browser_client_rects,
    browser_each_padding_box,
    browser_each_pseudo,
    browser_each_rect,
    browser_hit_id,
    browser_rect,
    corpus_document,
    corpus_slide,
    export_corpus,
    export_slides,
    overlaps,
    pinned_font_css,
    requires_huashu_sidecar,
    slide_document,
    slide_shape_elements,
    slide_shapes,
)
from tests.unit.test_export_collection_iteration_hostile_realm import (
    HOSTILE_EXPORT_TIMEOUT_SECONDS,
)
from tests.unit.test_export_svg_raster import structural_manifest

# Task 1's box tolerance: an emitted rect matches the browser's within 0.5 px.
RECT_TOLERANCE_PX = 0.5
# Captures are taken at device scale 2: a picture's PNG is twice its box, give
# or take the one device pixel a fractional rect rounds to.
CAPTURE_SCALE = 2
PNG_SIZE_TOLERANCE_PX = 1
# The brief's colour tolerance, per channel.
COLOUR_TOLERANCE = 6
# A pixel counts as opaque at this alpha or above, and as transparent at or below.
OPAQUE_ALPHA = 250
TRANSPARENT_ALPHA = 10
# The browser's opacity and the picture's shown alpha agree within this.
ALPHA_TOLERANCE = 0.04
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# Review Focus 1: a 20-slide chart deck must stay well inside the sidecar's
# 180 s timeout (SIDECAR_TIMEOUT_SECONDS); the plan's budget on the dev Mac.
TIMING_SLIDE_COUNT = 20
TIMING_BUDGET_SECONDS = 120.0

# The corpus deck's colours (deck.css :root and its chart and component rules).
INK = "1B3139"  # --ink
ACCENT = "FF5F46"  # --accent
ACCENT_2 = "FF3621"  # --accent-2
PAPER = "F9F7F4"  # --paper, the slide ground
RULE = "DCE0E2"  # --rule
GOOD = "00A972"  # --good
TRACK = "E6E3DE"  # .dk-bar-track
# The deck rules the expected colours come from; each test guards its own.
DECK_RULES = {
    "accent": "--accent: #FF5F46;",
    "accent-2": "--accent-2: #FF3621;",
    "ink": "--ink: #1B3139;",
    "rule": "--rule: #DCE0E2;",
    "good": "--good: #00A972;",
    "bar-hi": ".chart-svg .bar.hi { fill: var(--accent-2); }",
    "grid": ".chart-svg .grid { stroke: var(--rule); stroke-width: 1; }",
    "line": ".chart-svg .line { fill: none; stroke: var(--ink); stroke-width: 2.5; }",
    "harvey": "background: conic-gradient(var(--ink) calc(var(--p) * 1%), transparent 0);",
    "track": ".dk-bar-track { height: 12px; border-radius: 6px; background: #E6E3DE; "
    "overflow: hidden; }",
    "fill": ".dk-bar-fill { height: 100%; border-radius: 6px; "
    "background: linear-gradient(90deg, var(--accent-2), var(--accent)); }",
    "gradtext": ".dk-gradtext { background: linear-gradient(90deg, var(--accent-2), #FFB347); "
    "-webkit-background-clip: text; background-clip: text; color: transparent; }",
}

# Fixture 03: the chart, its third legend marker and the footer logo.
CHART = "svg.chart-svg"
CHART_VIEWBOX = (720.0, 330.0)
CHART_BARS = "svg.chart-svg rect.bar"
CHART_FY24_BAR = "svg.chart-svg rect.bar.hi"
CHART_GRIDLINES = "svg.chart-svg line.grid"
CHART_LINE = "svg.chart-svg polyline.line"
LEGEND = ".dk-legend"
LEGEND_MARKER = ".dk-legend svg"
FOOTER_LOGO = ".dk-footer img"
BRAND_TEXT = "Meridian Components"
# Between the line series and its closing chord: where SVG's default black
# fill would paint an open polyline whose class style ("fill: none") was lost
# (RC4 "filled black polylines"). A segment is sampled only where the chord
# lies this far from it, so the 2.5 px stroke leaves clear room.
CHORD_GAP_MIN_PX = 6.0

# A hue fixture 03's chart never paints: leaked deck content is unmistakable.
LEAK = "00FF00"
LEGEND_OVER_CHART_PX = 120
HOSTILE_RULES = {
    # The brief's rule on the legend, extended to its descendants (where its
    # text is) and with the legend moved over the chart (where a leak lands).
    "legend-forced-visible": (
        f".dk-legend {{ position: relative; top: -{LEGEND_OVER_CHART_PX}px; }}\n"
        f".dk-legend, .dk-legend * {{ visibility: visible !important; color: #{LEAK}; }}"
    ),
    # More specific than an unboosted "html, body" reset, so without the boost
    # the slide ground would paint the whole picture.
    "ground-forced": f"html > body {{ background: #{LEAK} !important; }}",
    # A pseudo-element of an unrelated element, laid over the chart, that
    # declares itself visible: `*` never matches ::before/::after, and a
    # pseudo-element's own declaration beats the visibility it would inherit
    # from its hidden element. Its specificity (0,2,2) outranks the isolation's
    # pseudo-element rule without its boost ((0,2,1) for a subtree target).
    "pseudo-forced-visible": (
        "body .slide .dk-legend::after { content: ''; position: fixed; left: 100px; top: 200px; "
        f"width: 500px; height: 150px; background: #{LEAK}; visibility: visible !important; }}"
    ),
}

# Fixture 04: Harvey balls, conic gradients clockwise from 12 o'clock.
HARVEY = ".dk-harvey"
HARVEY_SHARE = re.compile(r'class="dk-harvey" style="--p:(\d+)"')
HARVEY_SHARES = (50, 100, 50, 100, 50, 100, 25, 50)
HARVEY_ROW_LABELS = ("Liquidity", "Leverage", "Profitability", "Working-capital efficiency")
HARVEY_LABEL_CELLS = "table.dk-table tbody td:first-child"
# Sampled this far from a ball's centre, inside its 15 px padding box, at the
# middle of each quarter: 45 degrees from any boundary a share can put there.
HARVEY_SAMPLE_RADIUS_PX = 7.0
HARVEY_SAMPLE_ANGLES = (45.0, 135.0, 225.0, 315.0)

# Fixture 12: progress tracks, their gradient fills and the icons beside the labels.
TRACK_SELECTOR = ".dk-bar-track"
FILL_SELECTOR = ".dk-bar-fill"
ICON_SELECTOR = "svg"
ICON_LABELS = ("Plant automation", "ERP upgrade", "New tooling line", "Warehouse expansion")
# A fill is sampled on its middle row, this far in from each rounded end.
FILL_END_INSET_PX = 3.0

# Fixture 13's gradient text, and fixture 16's filtered logo.
GRADIENT_TEXT = ".dk-gradtext"
GRADIENT_WORDS = "from the ledger"
FILTERED_LOGO = "img"
WHITE_MIN = 240

# Fixture 17: its shown graphics, the hidden one (display: none, all #000) and the canvas.
FIXTURE_17_SVGS = "svg"
FIXTURE_17_HIDDEN_SVG = 2
FIXTURE_17_CANVAS = "canvas"
BLACK_MAX = 8

# Synthetic slides' own colours, used once per slide.
CAPTION_FILL = "7B2FBE"
BLUE = "2F5BEA"
CHIP_FILL = "FFD400"
PLAIN_FILL = "8A4FFF"
INVERTED_GOOD = "FF568D"  # filter: invert(1) of #00A972
HALF_BRIGHT_ACCENT_2 = "801B10"  # filter: brightness(0.5) of #FF3621


def _png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _data_uri(media_type: str, data: bytes) -> str:
    return f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"


def _rgb(colour: str) -> tuple[int, int, int]:
    return (int(colour[0:2], 16), int(colour[2:4], 16), int(colour[4:6], 16))


# A 100x100 raster in --good, and a 300x100 one in three vertical bands
# (accent-2 | good | blue): object-fit: cover in a square shows only the middle band.
GREEN_PNG = _png_bytes(Image.new("RGBA", (100, 100), _rgb(GOOD) + (255,)))
GREEN_PNG_URI = _data_uri("image/png", GREEN_PNG)
_BANDS = Image.new("RGBA", (300, 100), _rgb(ACCENT_2) + (255,))
_BANDS.paste(Image.new("RGBA", (100, 100), _rgb(GOOD) + (255,)), (100, 0))
_BANDS.paste(Image.new("RGBA", (100, 100), _rgb(BLUE) + (255,)), (200, 0))
BANDS_PNG_URI = _data_uri("image/png", _png_bytes(_BANDS))
GREEN_SVG_URI = _data_uri(
    "image/svg+xml",
    (
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100" '
        f'preserveAspectRatio="none"><rect width="100" height="100" fill="#{GOOD}"/></svg>'
    ).encode("utf-8"),
)

# A chart overlapped by an absolutely positioned caption over its bar.
OVERLAP_BODY = (
    '<div class="slide">'
    '<p class="dk-eyebrow">Overlap</p>'
    '<div style="position: relative; width: 600px; margin-top: 24px;">'
    '<svg id="overlap-chart" class="chart-svg" width="600" height="300" viewBox="0 0 600 300">'
    '<line class="grid" x1="20" y1="260" x2="580" y2="260"/>'
    '<rect class="bar hi" x="100" y="40" width="400" height="220" rx="3"/>'
    "</svg>"
    '<div id="caption" style="position: absolute; left: 200px; top: 100px; width: 200px; '
    f"height: 80px; box-sizing: border-box; padding: 10px; background: #{CAPTION_FILL}; "
    'color: #FFFFFF; font-size: 20px;">Caption on top</div>'
    "</div></div>"
)

# A deck rule that transitions every property: the isolation stylesheet's own
# changes (hiding the page is a visibility transition, which keeps an element
# visible while it runs) must not be caught mid-way.
TRANSITION_RULE = "* { transition: all 1s; }"

# Slide script aimed at the capture itself, run at parse time: a style
# element's onload that never fires (page.addStyleTag awaits it) and a
# setAttribute that does nothing (a target named through it answers to no
# selector, so its picture would come out empty).
HOSTILE_CAPTURE_BODY = (
    '<div class="slide">'
    "<script>(function () {"
    "Object.defineProperty(HTMLElement.prototype, 'onload', {configurable: true, "
    "get: function () { return null; }, set: function () {}});"
    "Object.defineProperty(Element.prototype, 'setAttribute', {configurable: true, "
    "value: function () {}});"
    "})();</script>"
    '<svg id="hostile-chart" width="400" height="200" viewBox="0 0 400 200" '
    'style="display: block; margin-top: 60px;">'
    f'<rect width="400" height="200" fill="#{ACCENT_2}"/></svg>'
    "</div>"
)

# An SVG whose group the slide hides, holding one part shown again: the
# browser paints the bar and the re-shown square, never the hidden square.
PARTED_BODY = (
    '<div class="slide">'
    '<svg id="parted-chart" width="400" height="200" viewBox="0 0 400 200" '
    'style="display: block; margin-top: 60px;">'
    f'<rect width="400" height="200" fill="#{ACCENT_2}"/>'
    '<g visibility="hidden">'
    f'<rect id="hidden-part" x="20" y="20" width="160" height="160" fill="#{LEAK}"/>'
    f'<rect id="shown-part" x="220" y="20" width="160" height="160" fill="#{BLUE}" '
    'visibility="visible"/>'
    "</g></svg></div>"
)

# A gradient box whose border and shadow are painted in currentColor (no colour
# of their own): box mode's transparent text colour must not take them away.
CURRENT_COLOUR_BODY = (
    '<div class="slide">'
    '<div id="current-colour-card" style="position: absolute; left: 200px; top: 200px; '
    "width: 300px; height: 150px; box-sizing: border-box; border: 6px solid; "
    f"color: #{BLUE}; background: linear-gradient(90deg, #{ACCENT_2}, #{ACCENT}); "
    'box-shadow: 0 10px 0 0; font-size: 24px;">Current colour</div></div>'
)
CURRENT_COLOUR_TEXT = "Current colour"
# box-shadow: 0 10px 0 0: max(|offset|) + blur + spread.
CURRENT_COLOUR_REACH_PX = 10

# An icon under filter: drop-shadow(0 12px 4px …): the shadow is offset 12 px
# and blurred with a standard deviation of 4 px, which paints 2σ past its edge.
DROP_SHADOW_BODY = (
    '<div class="slide">'
    '<svg id="shadowed-icon" width="120" height="120" viewBox="0 0 120 120" '
    'style="position: absolute; left: 300px; top: 200px; '
    'filter: drop-shadow(0 12px 4px rgba(27, 49, 57, 0.8));">'
    f'<rect width="120" height="120" fill="#{GOOD}"/></svg></div>'
)
DROP_SHADOW_REACH_PX = 12 + 2 * 4

# A canvas the slide's script draws at twice its CSS box (a hi-DPI bitmap,
# sized through canvas.width/height): #00A972 on its left three quarters,
# #2F5BEA on the right quarter. Its bitmap is not its box, so a resize to the
# box (the export document's chart initialisation) would clear it.
HIDPI_CANVAS_BODY = (
    '<div class="slide">'
    '<canvas id="hidpi-canvas" style="display: block; width: 160px; height: 80px; '
    'margin-top: 60px;"></canvas>'
    "<script>(function () {"
    "var canvas = document.getElementById('hidpi-canvas');"
    "canvas.width = 320; canvas.height = 160;"
    "var context = canvas.getContext('2d');"
    f"context.fillStyle = '#{GOOD}'; context.fillRect(0, 0, 240, 160);"
    f"context.fillStyle = '#{BLUE}'; context.fillRect(240, 0, 80, 160);"
    "})();</script></div>"
)
# Where the picture is sampled, as fractions of the canvas box across.
HIDPI_GREEN_AT = 0.375
HIDPI_BLUE_AT = 0.875

# Fixture 11's Chart.js doughnut, and the least share of its picture each of
# its two largest segments covers (measured: 18.5% and 10.6%).
CHARTJS_CANVAS = "canvas#segChart"
CHARTJS_MIN_SHARE = {"industrial": 0.10, "automotive": 0.05}

# C7.4 compares repeated exports of one rendered page, so it pins the corpus
# deck's fonts (export_snapshot_support.pinned_font_css): Google Fonts now and
# then names another DM Sans file for the deck's @import.


# C7.4: the determinism test makes DETERMINISM_EXPORTS exports, each of the
# slide DETERMINISM_SLIDES times (every slide renders in its own browser). A
# GPU rasterization draws one chart in about three a little differently, so
# one comparison of two single-slide exports misses it in most runs, and 5 of
# them in about one run in four (measured); 5 exports of 3 renders each miss
# it in under one run in a hundred.
DETERMINISM_EXPORTS = 5
DETERMINISM_SLIDES = 3

# A chart inside a half-transparent group.
FADE_OPACITY = 0.5
FADED_BODY = (
    '<div class="slide">'
    f'<div style="opacity: {FADE_OPACITY}; width: 400px; margin-top: 60px;">'
    '<svg id="faded-chart" width="400" height="200" viewBox="0 0 400 200">'
    f'<rect width="400" height="200" fill="#{ACCENT_2}"/></svg>'
    "</div></div>"
)


@dataclass(frozen=True)
class ClipCase:
    """A capture target spilling out of a bordered, padded ``overflow: hidden`` frame."""

    kind: str
    direction: str
    target: str  # the target's markup, with {style} for its size and margins


CLIP_TARGETS = {
    "raster-img": f'<img class="clip-target" src="{GREEN_PNG_URI}" alt="" style="{{style}}">',
    "svg-img": f'<img class="clip-target" src="{GREEN_SVG_URI}" alt="" style="{{style}}">',
    "inline-svg": (
        '<svg class="clip-target" style="{style}">'
        f'<rect width="100%" height="100%" fill="#{GOOD}"/></svg>'
    ),
}
# The frame's content box is 240x130; its padding box 8 px wider on each side.
CLIP_DIRECTIONS = {
    "right-and-down": "display: block; width: 300px; height: 170px; margin: 20px 0 0 30px;",
    "left-and-up": "display: block; width: 200px; height: 100px; margin: -40px 0 0 -50px;",
}
CLIP_CASES = [
    ClipCase(kind, direction, markup)
    for direction in CLIP_DIRECTIONS
    for kind, markup in CLIP_TARGETS.items()
]


def _clip_body() -> str:
    frames = []
    for position, case in enumerate(CLIP_CASES):
        left = 80 + (position % 3) * 400
        top = 120 + (position // 3) * 280
        frames.append(
            f'<div class="clip-frame" style="position: absolute; left: {left}px; top: {top}px; '
            "width: 240px; height: 130px; border: 4px solid #1B3139; padding: 8px; "
            'overflow: hidden; background: #F9F7F4;">'
            + case.target.format(style=CLIP_DIRECTIONS[case.direction])
            + "</div>"
        )
    return '<div class="slide">' + "".join(frames) + "</div>"


CLIP_BODY = _clip_body()

# Box-only targets the slide's own edge cuts at its right and at its bottom,
# from a fractional origin: the shown rect ends exactly at the viewport.
EDGE_CUT_BODY = (
    '<div class="slide">'
    '<div id="cut-right" style="position: absolute; left: 853.1px; top: 120.3px; width: 600px; '
    f'height: 100px; background: linear-gradient(90deg, #{ACCENT_2}, #{ACCENT});"></div>'
    '<div id="cut-bottom" style="position: absolute; left: 120.3px; top: 300.2px; width: 300px; '
    f'height: 600px; background: linear-gradient(180deg, #{ACCENT_2}, #{ACCENT});"></div>'
    "</div>"
)
SLIDE_RECT = {"x": 0.0, "y": 0.0, "w": 1280.0, "h": 720.0}

# Pseudo-elements on and inside capture targets. The slide hides two of them
# (#00FF00): one of a gradient box (a box target) and one of an HTML note in an
# SVG's foreignObject (inside a subtree target); neither may show anywhere.
# Two (#FFD400) the slide shows: the gradient box's is drawn natively over its
# picture, and the note's is in the SVG's picture.
PSEUDO_TARGETS_BODY = (
    '<div class="slide">'
    "<style>"
    "#pseudo-card::after { content: ''; position: absolute; left: 20px; top: 20px; "
    f"width: 100px; height: 60px; background: #{LEAK}; visibility: hidden; }}"
    "#pseudo-card::before { content: ''; position: absolute; right: 20px; bottom: 20px; "
    f"width: 60px; height: 40px; background: #{CHIP_FILL}; }}"
    ".fo-note::after { content: ''; display: block; width: 100px; height: 60px; "
    f"background: #{LEAK}; visibility: hidden; }}"
    ".fo-note::before { content: ''; display: block; width: 60px; height: 40px; "
    f"background: #{CHIP_FILL}; }}"
    "</style>"
    '<div id="pseudo-card" style="position: absolute; left: 80px; top: 120px; width: 300px; '
    f'height: 160px; background: linear-gradient(90deg, #{BLUE}, #{INK});"></div>'
    '<svg id="pseudo-svg" width="300" height="200" viewBox="0 0 300 200" '
    'style="position: absolute; left: 480px; top: 120px;">'
    f'<rect width="300" height="200" fill="#{BLUE}"/>'
    '<foreignObject x="20" y="20" width="200" height="160">'
    '<div xmlns="http://www.w3.org/1999/xhtml" class="fo-note"></div>'
    "</foreignObject></svg>"
    "</div>"
)


@dataclass(frozen=True)
class BoxProbe:
    """A box whose own painting a shape cannot draw: a box-only capture target."""

    style: str
    # (fraction across, fraction down, expected): a point of the box and what the
    # picture shows there; expected is 'RRGGBB' (opaque, within the tolerance),
    # 'transparent', or ('RRGGBB', alpha) for a translucent pixel.
    samples: tuple[tuple[float, float, object], ...]


BOX_PROBES = {
    "radial-gradient": BoxProbe(
        f"background: radial-gradient(circle, #{ACCENT_2} 0%, #{ACCENT_2} 30%, #{BLUE} 31%);",
        ((0.5, 0.5, ACCENT_2), (0.04, 0.08, BLUE)),
    ),
    "url-background": BoxProbe(
        # Single quotes: the style sits in a double-quoted attribute.
        f"background: url('{GREEN_PNG_URI}') center / cover no-repeat;",
        ((0.5, 0.5, GOOD), (0.1, 0.1, GOOD)),
    ),
    "filter": BoxProbe(
        f"background: #{ACCENT_2}; filter: brightness(0.5);",
        ((0.5, 0.5, HALF_BRIGHT_ACCENT_2),),
    ),
    "clip-path": BoxProbe(
        f"background: #{BLUE}; clip-path: polygon(50% 0, 100% 100%, 0 100%);",
        ((0.05, 0.08, "transparent"), (0.95, 0.08, "transparent"), (0.5, 0.9, BLUE)),
    ),
    "mask": BoxProbe(
        f"background: #{BLUE}; "
        "-webkit-mask-image: linear-gradient(to bottom, #000 0%, #000 50%, transparent 50%); "
        "mask-image: linear-gradient(to bottom, #000 0%, #000 50%, transparent 50%);",
        ((0.5, 0.2, BLUE), (0.5, 0.8, "transparent")),
    ),
    "mix-blend-mode": BoxProbe(
        f"background: #{ACCENT_2}; mix-blend-mode: multiply;",
        ((0.5, 0.5, ACCENT_2),),
    ),
    "backdrop-filter": BoxProbe(
        "background: rgba(47, 91, 234, 0.6); backdrop-filter: blur(6px);",
        ((0.5, 0.5, (BLUE, 0.6)),),
    ),
}
BOX_PROBE_SIZE = (160, 90)


def _box_probe_body() -> str:
    probes = []
    for position, (name, probe) in enumerate(BOX_PROBES.items()):
        left = 80 + (position % 4) * 240
        top = 110 + (position // 4) * 120
        probes.append(
            f'<div class="box-probe" id="probe-{name}" style="position: absolute; left: {left}px; '
            f"top: {top}px; width: {BOX_PROBE_SIZE[0]}px; height: {BOX_PROBE_SIZE[1]}px; "
            f'{probe.style}"></div>'
        )
    parts = [
        '<div class="slide">',
        *probes,
        # A plain fill: a native shape, never a picture.
        '<div id="probe-plain" style="position: absolute; left: 800px; top: 230px; '
        f'width: 160px; height: 90px; background: #{PLAIN_FILL};"></div>',
        # Gradient text (C7.2): a solid colour run, never a box capture; on an
        # inline span (fixture 13's form) and on a whole block.
        '<p style="position: absolute; left: 80px; top: 350px; margin: 0; font-size: 32px; '
        'font-weight: 700;">'
        '<span class="dk-gradtext" id="probe-gradtext">Gradient words</span></p>',
        '<p class="dk-gradtext" id="probe-gradtext-block" style="position: absolute; '
        'left: 640px; top: 350px; margin: 0; font-size: 32px; font-weight: 700;">'
        "Gradient heading</p>",
        # A gradient card holding text and a filled child: only its box is captured.
        '<div id="gradient-card" style="position: absolute; left: 80px; top: 420px; '
        "width: 420px; height: 180px; box-sizing: border-box; padding: 24px; "
        f"background: linear-gradient(90deg, #{INK}, #{BLUE}); color: #FFFFFF; "
        'font-size: 26px; font-weight: 600;">Card heading text'
        '<div id="card-chip" style="margin-top: 20px; width: 140px; height: 36px; '
        f'background: #{CHIP_FILL};"></div></div>',
        # A gradient box with an outer shadow: the rect grows to hold the shadow.
        '<div id="shadow-card" style="position: absolute; left: 640px; top: 420px; '
        "width: 300px; height: 140px; "
        f"background: linear-gradient(180deg, #{ACCENT_2}, #{ACCENT}); "
        'box-shadow: 0 6px 12px 2px rgba(27, 49, 57, 0.5);"></div>',
        "</div>",
    ]
    return "".join(parts)


BOX_PROBE_BODY = _box_probe_body()

# A gradient highlight on an inline span that wraps onto a second line. Its box
# is one box-only picture over both fragments (the union of its client rects);
# its words stay native.
HIGHLIGHT_BODY = (
    '<div class="slide">'
    '<p style="position: absolute; left: 80px; top: 200px; width: 520px; margin: 0; '
    f'font-size: 30px; line-height: 44px; color: #{INK};">Lead words then '
    f'<span id="highlight" style="background: linear-gradient(90deg, #{ACCENT_2}, #{BLUE}); '
    'color: #FFFFFF;">a highlighted phrase that wraps onto</span> a tail.</p>'
    "</div>"
)
HIGHLIGHT_WORD = "highlighted"
# A fragment is sampled on its middle row, this far in from the end the gradient starts or ends at.
HIGHLIGHT_END_INSET_PX = 3.0
CARD_TEXT = "Card heading text"
GRADIENT_PROBE_WORDS = "Gradient words"
GRADIENT_BLOCK_WORDS = "Gradient heading"
# box-shadow: 0 6px 12px 2px: max(|offset|) + blur + spread.
SHADOW_INFLATE_PX = 6 + 12 + 2


@dataclass(frozen=True)
class RasterCase:
    """A raster ``data:`` image: embedded as it is, or captured as the browser shows it."""

    style: str
    src: str
    inflate_px: float = 0.0


RASTER_CASES = {
    "plain": RasterCase("", GREEN_PNG_URI),
    "rounded": RasterCase("border-radius: 50%;", GREEN_PNG_URI),
    "cover": RasterCase("object-fit: cover;", BANDS_PNG_URI),
    "filtered": RasterCase("filter: invert(1);", GREEN_PNG_URI),
    "outlined": RasterCase(f"box-shadow: 0 0 0 4px #{INK};", GREEN_PNG_URI, inflate_px=4.0),
}


def _raster_body() -> str:
    images = []
    for position, (name, case) in enumerate(RASTER_CASES.items()):
        images.append(
            f'<img class="raster-probe" id="raster-{name}" src="{case.src}" alt="" '
            f'style="position: absolute; left: {100 + position * 200}px; top: 200px; '
            f'width: 100px; height: 100px; {case.style}">'
        )
    return '<div class="slide">' + "".join(images) + "</div>"


RASTER_BODY = _raster_body()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _export_one(body: str, monkeypatch: pytest.MonkeyPatch, *, css: str = DECK_CSS) -> bytes:
    pptx, failures = export_slides([body], css=css, monkeypatch=monkeypatch)
    assert failures == [], f"the export rejected the slide: {failures}"
    assert pptx, "the export produced no .pptx bytes"
    return pptx


def _document(body: str, *, css: str = DECK_CSS) -> str:
    """The document ``_export_one`` exported (``export_slides`` names slide 1 ``snapshot-1``)."""
    return slide_document(body, css=css, slide_id="snapshot-1")


def _assert_deck_rule(*names: str) -> None:
    for name in names:
        assert DECK_RULES[name] in DECK_CSS, (
            f"fixture drift: deck.css no longer holds {DECK_RULES[name]!r}, "
            "which this test's expected colour comes from"
        )


def _describe(shapes: list[Shape]) -> str:
    return "\n".join(
        f"  [{position}] {shape.kind} {shape.geometry} fill={shape.fill} "
        f"box=({shape.x:.2f}, {shape.y:.2f}, {shape.w:.2f}, {shape.h:.2f}) "
        f"image={'none' if shape.image is None else f'{len(shape.image)} B'} "
        f"text={shape.text[:30]!r}"
        for position, shape in enumerate(shapes)
    )


def _rect(shape: Shape) -> dict:
    return {"x": shape.x, "y": shape.y, "w": shape.w, "h": shape.h}


def _matches_rect(shape: Shape, rect: dict, tolerance: float = RECT_TOLERANCE_PX) -> bool:
    return all(abs(_rect(shape)[key] - rect[key]) <= tolerance for key in ("x", "y", "w", "h"))


def _inflated(rect: dict, by: float) -> dict:
    return {
        "x": rect["x"] - by,
        "y": rect["y"] - by,
        "w": rect["w"] + 2 * by,
        "h": rect["h"] + 2 * by,
    }


def _intersection(a: dict, b: dict) -> dict:
    left = max(a["x"], b["x"])
    top = max(a["y"], b["y"])
    right = min(a["x"] + a["w"], b["x"] + b["w"])
    bottom = min(a["y"] + a["h"], b["y"] + b["h"])
    return {"x": left, "y": top, "w": max(0.0, right - left), "h": max(0.0, bottom - top)}


def _centre(rect: dict) -> tuple[float, float]:
    return rect["x"] + rect["w"] / 2, rect["y"] + rect["h"] / 2


def _pictures(shapes: list[Shape]) -> list[tuple[int, Shape]]:
    return [(position, shape) for position, shape in enumerate(shapes) if shape.kind == "picture"]


def _picture_at(shapes: list[Shape], rect: dict, what: str) -> tuple[int, Shape]:
    """(spTree index, shape) of the one picture whose rect is ``rect`` within 0.5 px."""
    matches = [
        (position, shape) for position, shape in _pictures(shapes) if _matches_rect(shape, rect)
    ]
    assert len(matches) == 1, (
        f"{what}: expected exactly one picture at the browser rect "
        f"{ {key: round(value, 3) for key, value in rect.items()} } within {RECT_TOLERANCE_PX} px, "
        f"got {len(matches)}. The slide holds:\n{_describe(shapes)}"
    )
    return matches[0]


def _pictures_over(shapes: list[Shape], rect: dict) -> list[Shape]:
    """The pictures whose rect meets ``rect`` by more than 0.5 px on both axes (``overlaps``)."""
    area = SimpleNamespace(x=rect["x"], y=rect["y"], w=rect["w"], h=rect["h"])
    return [shape for _, shape in _pictures(shapes) if overlaps(shape, area)]


def _image(picture: Shape, what: str) -> Image.Image:
    assert picture.image is not None, f"{what}: the picture embeds no image"
    assert picture.image[:8] == PNG_SIGNATURE, (
        f"{what}: the picture is not a PNG (starts {picture.image[:8]!r})"
    )
    return Image.open(BytesIO(picture.image)).convert("RGBA")


def _assert_twice_its_box(image: Image.Image, rect: dict, what: str) -> None:
    expected = (rect["w"] * CAPTURE_SCALE, rect["h"] * CAPTURE_SCALE)
    assert (
        abs(image.width - expected[0]) <= PNG_SIZE_TOLERANCE_PX
        and abs(image.height - expected[1]) <= PNG_SIZE_TOLERANCE_PX
    ), (
        f"{what}: the PNG is {image.width}x{image.height}, not {CAPTURE_SCALE}x its "
        f"{rect['w']:.3f}x{rect['h']:.3f} box ({expected[0]:.1f}x{expected[1]:.1f} "
        f"± {PNG_SIZE_TOLERANCE_PX} px)"
    )


def _device_point(image: Image.Image, picture: Shape, x: float, y: float) -> tuple[int, int]:
    """The PNG pixel showing slide point (x, y), through the picture's rect and the PNG's size."""
    column = math.floor((x - picture.x) * image.width / picture.w)
    row = math.floor((y - picture.y) * image.height / picture.h)
    assert 0 <= column < image.width and 0 <= row < image.height, (
        f"slide point ({x:.2f}, {y:.2f}) lies outside the picture at "
        f"({picture.x:.2f}, {picture.y:.2f}, {picture.w:.2f}, {picture.h:.2f})"
    )
    return column, row


def _pixel(image: Image.Image, picture: Shape, x: float, y: float) -> tuple[int, int, int, int]:
    return image.getpixel(_device_point(image, picture, x, y))


def _pixels_near(
    image: Image.Image, picture: Shape, x: float, y: float, reach: int
) -> list[tuple[int, int, int, int]]:
    """Every PNG pixel within ``reach`` device px (a square) of the one showing (x, y)."""
    column, row = _device_point(image, picture, x, y)
    return [
        image.getpixel((c, r))
        for r in range(max(0, row - reach), min(image.height, row + reach + 1))
        for c in range(max(0, column - reach), min(image.width, column + reach + 1))
    ]


def _is(pixel: tuple[int, int, int, int], colour: str, tolerance: int = COLOUR_TOLERANCE) -> bool:
    """Whether ``pixel`` is opaque ``colour`` within ``tolerance`` per channel."""
    return pixel[3] >= OPAQUE_ALPHA and all(
        abs(channel - expected) <= tolerance for channel, expected in zip(pixel[:3], _rgb(colour))
    )


def _is_transparent(pixel: tuple[int, int, int, int]) -> bool:
    return pixel[3] <= TRANSPARENT_ALPHA


def _is_black(pixel: tuple[int, int, int, int]) -> bool:
    return pixel[3] >= OPAQUE_ALPHA and max(pixel[:3]) <= BLACK_MAX


def _is_white(pixel: tuple[int, int, int, int]) -> bool:
    return pixel[3] >= OPAQUE_ALPHA and min(pixel[:3]) >= WHITE_MIN


def _is_leak(pixel: tuple[int, int, int, int]) -> bool:
    """A pixel of the hostile rules' #00FF00, anti-aliased edges included."""
    return pixel[3] >= 128 and pixel[1] >= 200 and pixel[0] <= 90 and pixel[2] <= 90


def _show(pixel: tuple[int, int, int, int]) -> str:
    return f"#{pixel[0]:02X}{pixel[1]:02X}{pixel[2]:02X} alpha {pixel[3]}"


def _count(image: Image.Image, test: Callable[[tuple[int, int, int, int]], bool]) -> int:
    return sum(1 for pixel in image.getdata() if test(pixel))


def _normalised(text: str) -> str:
    return " ".join(text.split())


def _editable_texts(shapes: list[Shape]) -> list[str]:
    """The text of every text item and native table cell, whitespace collapsed."""
    texts = [shape.text for shape in shapes if shape.kind == "text"]
    for shape in shapes:
        if shape.table is not None:
            texts.extend(cell.text for row in shape.table.rows for cell in row)
    return [_normalised(text) for text in texts]


def _text_item(shapes: list[Shape], words: str) -> tuple[int, Shape]:
    """(spTree index, shape) of the first text item reading ``words``."""
    for position, shape in enumerate(shapes):
        if shape.kind == "text" and words in _normalised(shape.text):
            return position, shape
    raise AssertionError(f"no text item reads {words!r}. The slide holds:\n{_describe(shapes)}")


def _shape_filled(shapes: list[Shape], fill: str, what: str) -> tuple[int, Shape]:
    matches = [
        (position, shape)
        for position, shape in enumerate(shapes)
        if shape.kind == "shape" and shape.fill == fill
    ]
    assert len(matches) == 1, (
        f"{what}: expected exactly one native shape filled {fill}, got {len(matches)}:\n"
        f"{_describe(shapes)}"
    )
    return matches[0]


def _assert_box(shape: Shape, expected: dict, what: str) -> None:
    off = {key: round(_rect(shape)[key] - expected[key], 3) for key in ("x", "y", "w", "h")}
    assert all(abs(delta) <= RECT_TOLERANCE_PX for delta in off.values()), (
        f"{what}: emitted rect {_rect(shape)} differs from the browser's {expected} by {off} "
        f"(tolerance {RECT_TOLERANCE_PX} px)"
    )


def _media_difference(first: bytes, second: bytes, name: str) -> str:
    """How two exports' part ``name`` differs: for two same-sized PNGs, the pixels that do."""
    with zipfile.ZipFile(BytesIO(first)) as one, zipfile.ZipFile(BytesIO(second)) as other:
        if name not in one.namelist() or name not in other.namelist():
            return "in one export only"
        data = (one.read(name), other.read(name))
    if not all(blob[:8] == PNG_SIGNATURE for blob in data):
        return "content differs"
    images = [Image.open(BytesIO(blob)).convert("RGBA") for blob in data]
    if images[0].size != images[1].size:
        return f"PNG sizes {images[0].size} and {images[1].size}"
    deltas = [
        max(abs(a - b) for a, b in zip(left, right))
        for left, right in zip(images[0].getdata(), images[1].getdata())
        if left != right
    ]
    box = ImageChops.difference(images[0], images[1]).getbbox()
    return (
        f"{len(deltas)} pixels differ, by up to {max(deltas, default=0)} per channel, within {box}"
    )


def _picture_alpha(pptx: bytes, index: int) -> float:
    """The alpha the slide applies to picture ``index`` on top of its PNG (1 when none)."""
    element = slide_shape_elements(pptx)[index]
    modifier = element.find(".//a:blip/a:alphaModFix", NAMESPACES)
    return 1.0 if modifier is None else int(modifier.get("amt")) / PERCENT_UNITS


# ---------------------------------------------------------------------------
# Exports and browser geometry, read once per module
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def corpus_export() -> Iterator[Callable[[str], bytes]]:
    """Corpus slide ``prefix`` exported through the snapshot engine, once per module."""
    exported: dict[str, bytes] = {}
    with pytest.MonkeyPatch.context() as monkeypatch:

        def export(prefix: str) -> bytes:
            if prefix not in exported:
                pptx, failures = export_corpus([prefix], monkeypatch=monkeypatch)
                assert failures == [], f"the export rejected corpus slide {prefix}: {failures}"
                exported[prefix] = pptx
            return exported[prefix]

        yield export


@pytest.fixture(scope="module")
def chart_geometry() -> dict:
    """Fixture 03's chart geometry, as the browser laid it out."""
    document = corpus_document("03")
    chart = browser_rect(document, CHART)
    assert (
        abs(chart["w"] - CHART_VIEWBOX[0]) < 0.01 and abs(chart["h"] - CHART_VIEWBOX[1]) < 0.01
    ), f"fixture drift: the chart is {chart}, not drawn 1:1 from its {CHART_VIEWBOX} viewBox"
    return {
        "chart": chart,
        "bars": browser_each_rect(document, CHART_BARS),
        "fy24": browser_rect(document, CHART_FY24_BAR),
        "gridlines": browser_each_rect(document, CHART_GRIDLINES),
        "line": browser_rect(document, CHART_LINE),
        "marker": browser_rect(document, LEGEND_MARKER),
        "logo": browser_rect(document, FOOTER_LOGO),
    }


def _chart_picture(pptx: bytes, chart: dict) -> tuple[list[Shape], Shape, Image.Image]:
    shapes = slide_shapes(pptx)
    _, picture = _picture_at(shapes, chart, "the chart")
    image = _image(picture, "the chart")
    return shapes, picture, image


def _line_points(chart: dict, line: dict) -> list[tuple[float, float]]:
    """The line series' points on the slide: its viewBox points through the chart's 1:1 rect."""
    match = re.search(r'<polyline class="line" points="([^"]+)"', corpus_slide("03"))
    assert match, "fixture drift: fixture 03 has no line series polyline"
    points = [
        (chart["x"] + float(x), chart["y"] + float(y))
        for x, y in (pair.split(",") for pair in match.group(1).split())
    ]
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    bounds = {"x": min(xs), "y": min(ys), "w": max(xs) - min(xs), "h": max(ys) - min(ys)}
    assert all(abs(bounds[key] - line[key]) < 0.01 for key in bounds), (
        f"fixture drift: the line's points span {bounds}, the browser draws it at {line}"
    )
    return points


# ---------------------------------------------------------------------------
# The SVG chart (RC4, fixture 03) and its legend marker and footer logo (C7.1)
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotChartCapture:
    def test_chart_is_a_picture_twice_its_box(
        self, corpus_export: Callable[[str], bytes], chart_geometry: dict
    ) -> None:
        """Fixture 03's chart is one picture at the svg's browser rect, its PNG 2x the box."""
        chart = chart_geometry["chart"]
        _, _, image = _chart_picture(corpus_export("03"), chart)
        _assert_twice_its_box(image, chart, "the chart")

    def test_fy24_bar_is_its_css_colour(
        self, corpus_export: Callable[[str], bytes], chart_geometry: dict
    ) -> None:
        """The FY24 bar's class fill (``var(--accent-2)``) is in the picture, never black.

        Sampled at the bar's centre, from its browser rect: every pixel within
        one device px is ``FF3621`` within 6 per channel. A standalone SVG
        serialization loses the class and the variable and paints it black.
        """
        _assert_deck_rule("accent-2", "bar-hi")
        _, picture, image = _chart_picture(corpus_export("03"), chart_geometry["chart"])
        pixels = _pixels_near(image, picture, *_centre(chart_geometry["fy24"]), reach=1)
        wrong = [_show(pixel) for pixel in pixels if not _is(pixel, ACCENT_2)]
        assert not wrong, (
            f"the FY24 bar's centre is not #{ACCENT_2} (± {COLOUR_TOLERANCE}): {wrong}"
            + (" — black: the class fill was lost" if any(_is_black(p) for p in pixels) else "")
        )

    def test_gridlines_are_drawn_in_the_rule_colour(
        self, corpus_export: Callable[[str], bytes], chart_geometry: dict
    ) -> None:
        """Each gridline (``stroke: var(--rule)``, 1 px) shows ``DCE0E2`` between the bars.

        For every gridline, at the middle of each gap between neighbouring bars
        (browser rects), the PNG pixels within 2 device px of that point hold
        an opaque ``DCE0E2`` one (± 6). A 1 px line is two device rows, so one
        of them is fully covered however the rect's fraction falls.
        """
        _assert_deck_rule("rule", "grid")
        _, picture, image = _chart_picture(corpus_export("03"), chart_geometry["chart"])
        bars = sorted(chart_geometry["bars"], key=lambda bar: bar["x"])
        gaps = [(left["x"] + left["w"] + right["x"]) / 2 for left, right in zip(bars, bars[1:])]
        assert len(chart_geometry["gridlines"]) == 3 and len(gaps) == 4, (
            f"fixture drift: {len(chart_geometry['gridlines'])} gridlines, {len(gaps)} bar gaps"
        )
        missing = []
        for gridline in chart_geometry["gridlines"]:
            for x in gaps:
                square = _pixels_near(image, picture, x, gridline["y"], reach=2)
                if not any(_is(pixel, RULE) for pixel in square):
                    # The 5x5 square's middle column, top to bottom.
                    middle = [_show(pixel) for pixel in square[2::5]]
                    missing.append(f"({x:.1f}, {gridline['y']:.1f}): {middle}")
        assert not missing, f"no #{RULE} gridline pixel at: {missing}"

    def test_line_series_is_stroked_and_not_filled(
        self, corpus_export: Callable[[str], bytes], chart_geometry: dict
    ) -> None:
        """The polyline (``fill: none; stroke: var(--ink)``) is a line, not a filled area.

        * Where SVG's default black fill would paint it, between the line and
          its closing chord (sampled mid-segment where the chord is at least
          6 px away), the picture is transparent or the slide ground.
        * So it is between the line and the bars below it, mid-way down in the
          gap between the FY22 and FY23 bars.
        * The line itself is ``1B3139`` at those segments' midpoints.
        """
        _assert_deck_rule("ink", "line")
        chart = chart_geometry["chart"]
        _, picture, image = _chart_picture(corpus_export("03"), chart)
        points = _line_points(chart, chart_geometry["line"])
        first, last = points[0], points[-1]

        def chord_y(x: float) -> float:
            return first[1] + (last[1] - first[1]) * (x - first[0]) / (last[0] - first[0])

        filled, unstroked = [], []
        sampled = 0
        for start, end in zip(points, points[1:]):
            x = (start[0] + end[0]) / 2
            line_y = (start[1] + end[1]) / 2
            if abs(line_y - chord_y(x)) < CHORD_GAP_MIN_PX:
                continue
            sampled += 1
            inside = _pixel(image, picture, x, (line_y + chord_y(x)) / 2)
            if not (_is_transparent(inside) or _is(inside, PAPER)):
                filled.append(f"({x:.1f}, {(line_y + chord_y(x)) / 2:.1f}) {_show(inside)}")
            stroke = _pixel(image, picture, x, line_y)
            if not _is(stroke, INK):
                unstroked.append(f"({x:.1f}, {line_y:.1f}) {_show(stroke)}")
        assert sampled >= 2, f"fixture drift: only {sampled} segments lie clear of the chord"

        bars = sorted(chart_geometry["bars"], key=lambda bar: bar["x"])
        fy22, fy23 = bars[2], bars[3]
        gap_x = (fy22["x"] + fy22["w"] + fy23["x"]) / 2
        segment = next(
            (start, end) for start, end in zip(points, points[1:]) if start[0] <= gap_x <= end[0]
        )
        line_at_gap = segment[0][1] + (segment[1][1] - segment[0][1]) * (
            (gap_x - segment[0][0]) / (segment[1][0] - segment[0][0])
        )
        below = _pixel(image, picture, gap_x, (line_at_gap + min(fy22["y"], fy23["y"])) / 2)
        if not (_is_transparent(below) or _is(below, PAPER)):
            filled.append(f"under the line at x {gap_x:.1f}: {_show(below)}")

        assert not filled, f"the line series is filled: {filled}"
        assert not unstroked, f"the line series is not drawn in #{INK}: {unstroked}"

    def test_legend_marker_is_a_picture_of_its_line(
        self, corpus_export: Callable[[str], bytes], chart_geometry: dict
    ) -> None:
        """C7.1: the third legend entry's inline ``<svg>`` marker is a picture.

        At its browser rect within 0.5 px, and showing its class-styled line
        (``.chart-svg .line``: ``var(--ink)``) at its centre.
        """
        _assert_deck_rule("ink", "line")
        marker = chart_geometry["marker"]
        shapes = slide_shapes(corpus_export("03"))
        _, picture = _picture_at(shapes, marker, "the legend's line marker")
        image = _image(picture, "the legend's line marker")
        centre = _pixel(image, picture, *_centre(marker))
        assert _is(centre, INK), (
            f"the legend marker's line is {_show(centre)} at its centre, not #{INK}"
        )

    def test_footer_logo_is_a_picture_beside_the_brand_text(
        self, corpus_export: Callable[[str], bytes], chart_geometry: dict
    ) -> None:
        """C7.1: the footer logo (an SVG ``data:`` ``<img>``) is a picture at its browser rect.

        Within 0.5 px, its PNG 2x the box and holding the logo's own colours
        (its ``FF3621`` mark and ``1B3139`` wordmark), and the brand text box
        beside it does not overlap it.
        """
        logo = chart_geometry["logo"]
        shapes = slide_shapes(corpus_export("03"))
        _, picture = _picture_at(shapes, logo, "the footer logo")
        image = _image(picture, "the footer logo")
        _assert_twice_its_box(image, logo, "the footer logo")
        assert _count(image, lambda pixel: _is(pixel, ACCENT_2)) > 0, (
            f"the footer logo's picture holds none of its #{ACCENT_2} mark"
        )
        assert _count(image, lambda pixel: _is(pixel, INK)) > 0, (
            f"the footer logo's picture holds none of its #{INK} wordmark"
        )
        _, brand = _text_item(shapes, BRAND_TEXT)
        assert not overlaps(brand, picture), (
            f"the brand text box {_rect(brand)} overlaps the logo picture {_rect(picture)}"
        )


# ---------------------------------------------------------------------------
# Isolation (Review Focus 5)
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotCaptureIsolation:
    @pytest.mark.parametrize("rule", sorted(HOSTILE_RULES))
    def test_deck_css_forcing_visibility_does_not_leak_into_the_chart(
        self, monkeypatch: pytest.MonkeyPatch, rule: str
    ) -> None:
        """Deck CSS that fights the isolation stylesheet with ``!important`` loses to it.

        Fixture 03 with one more deck rule, painting in ``#00FF00``, a hue the
        chart never uses:

        * ``legend-forced-visible``: ``.dk-legend, .dk-legend * { visibility:
          visible !important }`` with the legend moved 120 px up, over the
          chart (the brief's ``.dk-legend`` rule alone leaks nothing even
          without the boost: see the module docstring);
        * ``ground-forced``: ``html > body { background: … !important }``;
        * ``pseudo-forced-visible``: a ``body .slide .dk-legend::after`` box fixed
          over the chart with ``visibility: visible !important`` on the
          pseudo-element itself, which no ``*`` rule matches.

        The chart is still captured (its FY24 bar shows ``FF3621``), and its
        picture holds no ``#00FF00`` pixel.
        """
        css = DECK_CSS + "\n" + HOSTILE_RULES[rule]
        body = corpus_slide("03")
        document = _document(body, css=css)
        chart = browser_rect(document, CHART)
        if rule == "legend-forced-visible":
            legend = browser_rect(document, LEGEND)
            covered = _intersection(legend, chart)
            assert covered["w"] * covered["h"] >= 0.99 * legend["w"] * legend["h"], (
                f"fixture drift: the moved legend {legend} does not lie over the chart {chart}"
            )

        pptx = _export_one(body, monkeypatch, css=css)
        _, picture, image = _chart_picture(pptx, chart)
        fy24 = browser_rect(document, CHART_FY24_BAR)
        centre = _pixel(image, picture, *_centre(fy24))
        assert _is(centre, ACCENT_2), f"{rule}: the FY24 bar's centre is {_show(centre)}"
        leaked = _count(image, _is_leak)
        assert leaked == 0, (
            f"{rule}: the chart picture holds {leaked} pixels of the deck's #{LEAK}: "
            "deck CSS defeated the capture isolation"
        )

    def test_overlapping_caption_is_not_baked_into_the_chart(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A caption box positioned over a chart stays native and out of the chart's picture.

        The caption (filled ``7B2FBE``, white text) lies over the chart's bar,
        on top of it in the browser. The chart's picture holds none of the
        caption's fill or text, and at the caption's centre shows the bar
        beneath it (``FF3621``). The caption itself is a native shape at its
        browser rect with its text as a text item, both above the picture.
        """
        document = _document(OVERLAP_BODY)
        chart = browser_rect(document, "#overlap-chart")
        caption = browser_rect(document, "#caption")
        assert browser_hit_id(document, *_centre(caption)) == "caption", (
            "fixture drift: the browser does not show the caption on top of the chart"
        )

        shapes = slide_shapes(_export_one(OVERLAP_BODY, monkeypatch))
        chart_index, picture = _picture_at(shapes, chart, "the overlapped chart")
        image = _image(picture, "the overlapped chart")
        baked_fill = _count(image, lambda pixel: _is(pixel, CAPTION_FILL, tolerance=24))
        baked_text = _count(image, _is_white)
        assert baked_fill == 0 and baked_text == 0, (
            f"the chart picture bakes in the caption: {baked_fill} caption-fill pixels, "
            f"{baked_text} white text pixels"
        )
        under = _pixel(image, picture, *_centre(caption))
        assert _is(under, ACCENT_2), (
            f"under the caption the chart picture shows {_show(under)}, not its bar #{ACCENT_2}"
        )

        caption_index, caption_shape = _shape_filled(shapes, CAPTION_FILL, "the caption")
        _assert_box(caption_shape, caption, "the caption box")
        text_index, _ = _text_item(shapes, "Caption on top")
        assert chart_index < caption_index and chart_index < text_index, (
            f"the caption (shape {caption_index}, text {text_index}) is not above the chart "
            f"picture ({chart_index}):\n{_describe(shapes)}"
        )

    def test_deck_transitions_do_not_leak_into_the_chart(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A deck that transitions every property cannot bake what overlaps a chart into it.

        Under ``* { transition: all 1s }`` the isolation stylesheet's own
        changes start transitions, and hiding an element is a visibility
        transition that keeps it visible while it runs. So the capture must
        take the isolated page at the end of every transition: the caption over
        the chart (as in ``test_overlapping_caption_is_not_baked_into_the_chart``)
        is not in the chart's picture, which shows the bar under it.
        """
        css = DECK_CSS + "\n" + TRANSITION_RULE
        document = _document(OVERLAP_BODY, css=css)
        chart = browser_rect(document, "#overlap-chart")
        caption = browser_rect(document, "#caption")
        shapes = slide_shapes(_export_one(OVERLAP_BODY, monkeypatch, css=css))
        _, picture = _picture_at(shapes, chart, "the chart of a transitioning deck")
        image = _image(picture, "the chart of a transitioning deck")
        baked_fill = _count(image, lambda pixel: _is(pixel, CAPTION_FILL, tolerance=24))
        baked_text = _count(image, _is_white)
        assert baked_fill == 0 and baked_text == 0, (
            f"a deck transition baked the caption into the chart picture: {baked_fill} "
            f"caption-fill pixels, {baked_text} white text pixels"
        )
        under = _pixel(image, picture, *_centre(caption))
        assert _is(under, ACCENT_2), (
            f"under the caption the chart picture shows {_show(under)}, not its bar #{ACCENT_2}"
        )

    def test_slide_script_cannot_stall_or_blank_a_capture(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Slide script aimed at the capture neither hangs the export nor empties the picture.

        The slide replaces ``HTMLElement.prototype.onload`` with a setter that
        does nothing (so a style element added from the page's own realm never
        reports loaded) and ``Element.prototype.setAttribute`` with a function
        that does nothing (so a target named through it answers to no
        selector). The export still finishes within the hostile-realm bound,
        and the chart is a picture showing its ``FF3621`` fill.
        """
        monkeypatch.setattr(
            pptx_from_html_huashu, "SIDECAR_TIMEOUT_SECONDS", HOSTILE_EXPORT_TIMEOUT_SECONDS
        )
        chart = browser_rect(_document(HOSTILE_CAPTURE_BODY), "#hostile-chart")
        shapes = slide_shapes(_export_one(HOSTILE_CAPTURE_BODY, monkeypatch))
        _, picture = _picture_at(shapes, chart, "the chart under hostile slide script")
        image = _image(picture, "the chart under hostile slide script")
        centre = _pixel(image, picture, *_centre(chart))
        assert _is(centre, ACCENT_2), (
            f"the chart picture shows {_show(centre)} at its centre, not #{ACCENT_2}: "
            "slide script defeated the capture"
        )

    def test_pseudo_elements_are_captured_as_the_slide_shows_them(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A box target's own pseudo-elements are native; a subtree target's are in its picture.

        A box-only capture holds its target's own box and nothing it paints
        around it: the target's ``::before`` and ``::after`` are drawn natively,
        and editable, like its text and children. So the gradient box's
        ``::before`` the slide shows (``FFD400``) is one native shape at its
        browser box, over the box's picture, and no pixel of that picture; its
        ``::after`` the slide hides (``#00FF00``) is nowhere, neither a shape
        nor a pixel. A subtree capture shows what its target holds as the slide
        does: in the SVG's picture, the foreignObject note's hidden ``::after``
        has no ``#00FF00`` pixel and its shown ``::before`` has ``FFD400``
        pixels, and that ``::before`` is not drawn natively a second time.
        """
        document = _document(PSEUDO_TARGETS_BODY)
        card = browser_rect(document, "#pseudo-card")
        svg = browser_rect(document, "#pseudo-svg")
        card_before = browser_each_pseudo(document, "#pseudo-card")[0]
        red, green, blue = _rgb(CHIP_FILL)
        assert card_before is not None and (
            card_before["style"]["backgroundColor"] == f"rgb({red}, {green}, {blue})"
        ), f"fixture drift: the gradient box's ::before is {card_before}"
        shapes = slide_shapes(_export_one(PSEUDO_TARGETS_BODY, monkeypatch))
        wrong = []

        card_index, card_picture = _picture_at(shapes, card, "the gradient box")
        card_image = _image(card_picture, "the gradient box")
        baked = _count(card_image, lambda pixel: _is(pixel, CHIP_FILL))
        hidden = _count(card_image, _is_leak)
        if baked or hidden:
            wrong.append(
                f"the gradient box's picture holds {baked} pixels of its ::before (drawn natively, "
                f"not in the picture) and {hidden} of the ::after the slide hides"
            )
        natives = [
            (position, shape)
            for position, shape in enumerate(shapes)
            if shape.kind == "shape" and shape.fill == CHIP_FILL
        ]
        native_rects = [(position, _rect(shape)) for position, shape in natives]
        if not (
            len(natives) == 1
            and _matches_rect(natives[0][1], card_before)
            and natives[0][0] > card_index
        ):
            wrong.append(
                f"expected the gradient box's ::before as one native {CHIP_FILL} shape at "
                f"{ {key: round(card_before[key], 3) for key in ('x', 'y', 'w', 'h')} } over its "
                f"picture (spTree {card_index}); got {native_rects}"
            )
        leaked = [_rect(shape) for shape in shapes if shape.fill == LEAK]
        if leaked:
            wrong.append(f"the ::after the slide hides is drawn as shapes {leaked}")

        _, svg_picture = _picture_at(shapes, svg, "the SVG")
        svg_image = _image(svg_picture, "the SVG")
        hidden = _count(svg_image, _is_leak)
        shown = _count(svg_image, lambda pixel: _is(pixel, CHIP_FILL))
        if hidden or not shown:
            wrong.append(
                f"the SVG: {hidden} pixels of the ::after the slide hides, "
                f"{shown} of the ::before it shows"
            )
        assert not wrong, (
            "the pseudo-elements are not drawn as the slide shows them:\n"
            + "\n".join(wrong)
            + f"\n{_describe(shapes)}"
        )

    def test_svg_parts_the_slide_hides_stay_hidden(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A subtree capture shows its target's descendants as the slide does, no more.

        The isolation shows a target's whole subtree, so an SVG group the
        slide hides (``visibility="hidden"``) must be hidden again: its square
        (``#00FF00``) is not in the picture, the bar beneath shows there, and
        the square the group shows again (``visibility="visible"``) is in it.
        """
        document = _document(PARTED_BODY)
        chart = browser_rect(document, "#parted-chart")
        hidden = browser_rect(document, "#hidden-part")
        shown = browser_rect(document, "#shown-part")
        assert browser_hit_id(document, *_centre(hidden)) != "hidden-part", (
            "fixture drift: the browser shows the hidden square"
        )
        assert browser_hit_id(document, *_centre(shown)) == "shown-part", (
            "fixture drift: the browser does not show the re-shown square"
        )
        shapes = slide_shapes(_export_one(PARTED_BODY, monkeypatch))
        _, picture = _picture_at(shapes, chart, "the parted chart")
        image = _image(picture, "the parted chart")
        leaked = _count(image, _is_leak)
        under = _pixel(image, picture, *_centre(hidden))
        again = _pixel(image, picture, *_centre(shown))
        assert leaked == 0 and _is(under, ACCENT_2), (
            f"the hidden square is in the picture: {leaked} #{LEAK} pixels, "
            f"{_show(under)} at its centre (want the bar #{ACCENT_2})"
        )
        assert _is(again, BLUE), f"the re-shown square is {_show(again)}, not #{BLUE}"


# ---------------------------------------------------------------------------
# Harvey balls (RC8, fixture 04)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def harvey_balls() -> list[dict]:
    """Fixture 04's Harvey balls in document order: their browser rects and shares."""
    _assert_deck_rule("ink", "harvey")
    shares = tuple(int(share) for share in HARVEY_SHARE.findall(corpus_slide("04")))
    assert shares == HARVEY_SHARES, f"fixture drift: the Harvey ball shares are {shares}"
    rects = browser_each_rect(corpus_document("04"), HARVEY)
    assert len(rects) == len(shares), f"fixture drift: {len(rects)} Harvey balls"
    return [{"rect": rect, "share": share} for rect, share in zip(rects, shares)]


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotHarveyBalls:
    @pytest.mark.parametrize("ball", range(len(HARVEY_SHARES)))
    def test_harvey_ball_is_a_picture_filled_to_its_share(
        self, corpus_export: Callable[[str], bytes], harvey_balls: list[dict], ball: int
    ) -> None:
        """Each ball's conic gradient is a box-only picture, dark exactly in its share.

        ``conic-gradient(var(--ink) calc(var(--p) * 1%), transparent 0)`` fills
        clockwise from 12 o'clock. Sampled 7 px from the ball's centre in the
        middle of each quarter: a quarter inside the share is ``1B3139``; one
        outside it is not dark (transparent, or a light ground).
        """
        rect = harvey_balls[ball]["rect"]
        share = harvey_balls[ball]["share"]
        _, picture = _picture_at(slide_shapes(corpus_export("04")), rect, f"Harvey ball {ball}")
        image = _image(picture, f"Harvey ball {ball}")
        centre_x, centre_y = _centre(rect)
        wrong = []
        for angle in HARVEY_SAMPLE_ANGLES:
            x = centre_x + HARVEY_SAMPLE_RADIUS_PX * math.sin(math.radians(angle))
            y = centre_y - HARVEY_SAMPLE_RADIUS_PX * math.cos(math.radians(angle))
            pixel = _pixel(image, picture, x, y)
            filled = angle < share / 100 * 360
            dark = pixel[3] >= 128 and min(pixel[:3]) < 150
            if filled and not _is(pixel, INK):
                wrong.append(f"{angle:g} degrees should be #{INK}, is {_show(pixel)}")
            if not filled and dark:
                wrong.append(f"{angle:g} degrees should be empty, is {_show(pixel)}")
        assert not wrong, f"Harvey ball {ball} (share {share}%): {wrong}"

    def test_harvey_row_labels_stay_editable_text(
        self, corpus_export: Callable[[str], bytes], harvey_balls: list[dict]
    ) -> None:
        """Each row's balls are pictures, and its label is editable text no picture covers.

        A box-only capture takes the ball's box, not its row: the label
        ("Liquidity", …) is a text item or a native table cell, and no picture
        meets the label cell's browser rect.
        """
        shapes = slide_shapes(corpus_export("04"))
        for ball, entry in enumerate(harvey_balls):
            _picture_at(shapes, entry["rect"], f"Harvey ball {ball}")
        cells = browser_each_rect(corpus_document("04"), HARVEY_LABEL_CELLS)
        assert len(cells) == len(HARVEY_ROW_LABELS), f"fixture drift: {len(cells)} label cells"
        texts = _editable_texts(shapes)
        for label, cell in zip(HARVEY_ROW_LABELS, cells):
            assert any(label in text for text in texts), (
                f"the row label {label!r} is not editable text:\n{_describe(shapes)}"
            )
            covering = [_rect(shape) for shape in _pictures_over(shapes, cell)]
            assert not covering, f"pictures cover the label cell of {label!r}: {covering}"


# ---------------------------------------------------------------------------
# Progress fills and icons (RC8, C7.1, fixture 12)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def progress_geometry() -> dict:
    document = corpus_document("12")
    geometry = {
        "tracks": browser_each_rect(document, TRACK_SELECTOR),
        "fills": browser_each_rect(document, FILL_SELECTOR),
        "icons": browser_each_rect(document, ICON_SELECTOR),
    }
    assert len(geometry["tracks"]) == len(geometry["fills"]) == len(geometry["icons"]) == 4, (
        f"fixture drift: {[(name, len(rects)) for name, rects in geometry.items()]}"
    )
    return geometry


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotProgressAndIcons:
    @pytest.mark.parametrize("bar", range(4))
    def test_progress_fill_is_a_gradient_picture_on_a_native_track(
        self, corpus_export: Callable[[str], bytes], progress_geometry: dict, bar: int
    ) -> None:
        """The fill's ``linear-gradient(90deg, accent-2, accent)`` is a box-only picture.

        At the fill's browser rect, its middle row is ``FF3621`` 3 px in from
        the left and ``FF5F46`` 3 px in from the right (± 6 each), so the
        gradient runs across it. Its track stays a native ``roundRect`` filled
        ``E6E3DE`` at the track's rect, behind the fill, and is no picture.
        """
        _assert_deck_rule("accent", "accent-2", "track", "fill")
        fill = progress_geometry["fills"][bar]
        track = progress_geometry["tracks"][bar]
        shapes = slide_shapes(corpus_export("12"))
        fill_index, picture = _picture_at(shapes, fill, f"progress fill {bar}")
        image = _image(picture, f"progress fill {bar}")
        middle = fill["y"] + fill["h"] / 2
        left = _pixel(image, picture, fill["x"] + FILL_END_INSET_PX, middle)
        right = _pixel(image, picture, fill["x"] + fill["w"] - FILL_END_INSET_PX, middle)
        assert _is(left, ACCENT_2) and _is(right, ACCENT), (
            f"progress fill {bar}: left {_show(left)} (want #{ACCENT_2}), "
            f"right {_show(right)} (want #{ACCENT})"
        )

        tracks = [
            (position, shape)
            for position, shape in enumerate(shapes)
            if shape.kind == "shape" and shape.fill == TRACK and _matches_rect(shape, track)
        ]
        assert len(tracks) == 1, (
            f"progress track {bar}: expected one native #{TRACK} shape at {track}:\n"
            f"{_describe(shapes)}"
        )
        track_index, track_shape = tracks[0]
        assert track_shape.geometry == "roundRect", (
            f"progress track {bar} is a {track_shape.geometry}, not a roundRect"
        )
        assert track_index < fill_index, (
            f"progress track {bar} (spTree {track_index}) is not behind its fill ({fill_index})"
        )
        assert not [shape for _, shape in _pictures(shapes) if _matches_rect(shape, track)], (
            f"progress track {bar} became a picture"
        )

    def test_inline_icons_are_pictures_left_of_their_labels(
        self, corpus_export: Callable[[str], bytes], progress_geometry: dict
    ) -> None:
        """C7.1: each inline icon is a picture at its rect, left of its label's text item.

        The icons stroke in ``currentColor``, set to ``var(--accent)`` on the
        ``<svg>`` itself, so each picture holds ``FF5F46`` strokes and no
        black (a standalone serialization loses the variable and strokes black).
        """
        _assert_deck_rule("accent")
        shapes = slide_shapes(corpus_export("12"))
        for icon, label in zip(progress_geometry["icons"], ICON_LABELS):
            _, picture = _picture_at(shapes, icon, f"the {label!r} icon")
            image = _image(picture, f"the {label!r} icon")
            assert _count(image, lambda pixel: _is(pixel, ACCENT)) > 0, (
                f"the {label!r} icon holds no #{ACCENT} stroke"
            )
            assert _count(image, _is_black) == 0, f"the {label!r} icon strokes black"
            _, text = _text_item(shapes, label)
            assert text.x >= picture.x + picture.w - RECT_TOLERANCE_PX, (
                f"the {label!r} text starts at x {text.x:.2f}, inside its icon "
                f"(right edge {picture.x + picture.w:.2f})"
            )


# ---------------------------------------------------------------------------
# Gradient text (C7.2), the filtered logo, and the canvas and hidden graphic
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotCorpusPictures:
    def test_gradient_text_is_not_a_box_capture(
        self, corpus_export: Callable[[str], bytes]
    ) -> None:
        """C7.2: fixture 13's ``.dk-gradtext`` (``background-clip: text``) makes no picture.

        Captures run on the slide (its footer logo is a picture), yet no
        picture meets any fragment of the gradient text: a box capture would
        paint a gradient rectangle under the words. The words stay a text run.
        """
        _assert_deck_rule("gradtext")
        document = corpus_document("13")
        shapes = slide_shapes(corpus_export("13"))
        _picture_at(shapes, browser_rect(document, FOOTER_LOGO), "fixture 13's footer logo")
        for fragment in browser_client_rects(document, GRADIENT_TEXT):
            covering = _pictures_over(shapes, fragment)
            assert not covering, (
                f"the gradient text at {fragment} became a picture: "
                f"{[_rect(shape) for shape in covering]}"
            )
        _text_item(shapes, GRADIENT_WORDS)

    def test_filtered_logo_is_white(self, corpus_export: Callable[[str], bytes]) -> None:
        """Fixture 16's logo under ``filter: brightness(0) invert(1)`` is captured white.

        A picture at the ``<img>``'s browser rect whose opaque pixels are all
        white (each channel at least 240), and there are some: the filter is
        in the picture, where embedding the source would show its red and navy.
        """
        document = corpus_document("16")
        logo = browser_rect(document, FILTERED_LOGO)
        _, picture = _picture_at(slide_shapes(corpus_export("16")), logo, "the filtered logo")
        image = _image(picture, "the filtered logo")
        opaque = [pixel for pixel in image.getdata() if pixel[3] >= OPAQUE_ALPHA]
        assert len(opaque) >= 0.02 * image.width * image.height, (
            f"the filtered logo's picture has only {len(opaque)} opaque pixels"
        )
        coloured = [_show(pixel) for pixel in opaque if min(pixel[:3]) < WHITE_MIN]
        assert not coloured, (
            f"{len(coloured)} opaque pixels of the filtered logo are not white, e.g. {coloured[:5]}"
        )

    def test_script_drawn_canvas_is_a_green_picture(
        self, corpus_export: Callable[[str], bytes]
    ) -> None:
        """Fixture 17's canvas, drawn by slide script in ``#00A972``, is a picture.

        At the canvas's browser rect, its PNG 2x the box, with ``00A972`` its
        main colour (the script fills the whole canvas, then writes on it),
        as the UI shows it. Exported with the corpus deck, whose Chart.js
        scripts make the export document's chart initialisation
        (``build_slide_html``) resize every canvas once Chart.js is ready, and
        setting a canvas's size clears what slide script drew on it. So this
        needs that document to leave a drawn canvas as it is, as well as the
        capture; ``test_script_drawn_canvas_capture`` pins the capture alone.
        """
        _assert_deck_rule("good")
        canvas = browser_rect(corpus_document("17"), FIXTURE_17_CANVAS)
        _, picture = _picture_at(slide_shapes(corpus_export("17")), canvas, "the canvas")
        image = _image(picture, "the canvas")
        _assert_twice_its_box(image, canvas, "the canvas")
        green = _count(image, lambda pixel: _is(pixel, GOOD))
        assert green >= 0.5 * image.width * image.height, (
            f"only {green} of {image.width * image.height} canvas pixels are #{GOOD}: "
            "the canvas the slide's script drew is blank in the export"
        )

    def test_script_drawn_canvas_capture(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The capture alone: fixture 17's body without the deck's Chart.js scripts.

        With no chart code on the page nothing resizes the canvas before the
        export reads it, so this isolates the capture: a picture at the
        canvas's browser rect, 2x the box, ``00A972`` its main colour.
        """
        _assert_deck_rule("good")
        body = corpus_slide("17")
        canvas = browser_rect(_document(body), FIXTURE_17_CANVAS)
        shapes = slide_shapes(_export_one(body, monkeypatch))
        _, picture = _picture_at(shapes, canvas, "the canvas")
        image = _image(picture, "the canvas")
        _assert_twice_its_box(image, canvas, "the canvas")
        green = _count(image, lambda pixel: _is(pixel, GOOD))
        assert green >= 0.5 * image.width * image.height, (
            f"only {green} of {image.width * image.height} canvas pixels are #{GOOD}"
        )

    def test_hidpi_script_drawn_canvas_keeps_its_drawing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A canvas the slide's script drew at twice its CSS box keeps its drawing.

        The script sizes the bitmap (``canvas.width``/``height``, 2x the box)
        and fills it, as a script drawing for a sharp display does. Exported
        with the corpus deck, so the export document's chart initialisation
        runs (``build_slide_html``) and finds a bitmap that is not its box: it
        must leave a canvas carrying a width or height attribute alone, since
        resizing it clears it. The picture, at the canvas's browser rect and 2x
        it, shows ``00A972`` and ``2F5BEA`` where the script put them.
        """
        _assert_deck_rule("good")
        scripts = CORPUS_DECK.get("scripts", "")
        external_scripts = tuple(CORPUS_DECK.get("external_scripts", []))
        assert any("chart.js" in script for script in external_scripts), (
            "fixture drift: the corpus deck no longer loads Chart.js, so the chart "
            "initialisation this test needs does not run"
        )
        document = slide_document(
            HIDPI_CANVAS_BODY, scripts=scripts, external_scripts=external_scripts
        )
        canvas = browser_rect(document, "#hidpi-canvas")
        pptx, failures = export_slides(
            [HIDPI_CANVAS_BODY],
            scripts=scripts,
            external_scripts=external_scripts,
            monkeypatch=monkeypatch,
        )
        assert failures == [], f"the export rejected the slide: {failures}"
        _, picture = _picture_at(slide_shapes(pptx), canvas, "the hi-DPI canvas")
        image = _image(picture, "the hi-DPI canvas")
        _assert_twice_its_box(image, canvas, "the hi-DPI canvas")
        middle = canvas["y"] + canvas["h"] / 2
        green = _pixel(image, picture, canvas["x"] + HIDPI_GREEN_AT * canvas["w"], middle)
        blue = _pixel(image, picture, canvas["x"] + HIDPI_BLUE_AT * canvas["w"], middle)
        assert _is(green, GOOD) and _is(blue, BLUE), (
            f"the hi-DPI canvas shows {_show(green)} (want #{GOOD}) and {_show(blue)} "
            f"(want #{BLUE}): the export document cleared the canvas the slide drew"
        )

    def test_chartjs_canvas_is_a_picture_of_its_chart(
        self, corpus_export: Callable[[str], bytes]
    ) -> None:
        """Fixture 11's Chart.js doughnut, drawn by the deck's script, is a picture of it.

        Its canvas carries no size attribute, so the export document's chart
        initialisation sizes it before Chart.js draws on it. The picture, at the
        canvas's browser rect and 2x it, holds the doughnut: Industrial
        (``FF5F46``, 51%) and Automotive (``1B3139``, 29%) segments, the first
        the larger.
        """
        for colour in (ACCENT, INK):
            assert f"'#{colour}'" in CORPUS_DECK.get("scripts", ""), (
                f"fixture drift: the corpus deck's chart no longer draws #{colour}"
            )
        canvas = browser_rect(corpus_document("11"), CHARTJS_CANVAS)
        _, picture = _picture_at(slide_shapes(corpus_export("11")), canvas, "the Chart.js canvas")
        image = _image(picture, "the Chart.js canvas")
        _assert_twice_its_box(image, canvas, "the Chart.js canvas")
        total = image.width * image.height
        industrial = _count(image, lambda pixel: _is(pixel, ACCENT))
        automotive = _count(image, lambda pixel: _is(pixel, INK))
        assert (
            industrial >= CHARTJS_MIN_SHARE["industrial"] * total
            and automotive >= CHARTJS_MIN_SHARE["automotive"] * total
            and industrial > automotive
        ), (
            f"the Chart.js picture holds {industrial} #{ACCENT} and {automotive} #{INK} "
            f"pixels of {total}: the doughnut is not drawn as the deck's script draws it"
        )

    def test_shown_graphics_are_pictures_and_the_hidden_svg_is_not(
        self, corpus_export: Callable[[str], bytes]
    ) -> None:
        """Fixture 17's pictures are exactly its shown graphics.

        Its four shown inline SVGs, the canvas and the footer logo each have
        one picture at their browser rect, and there is no other picture. The
        ``display: none`` SVG (all ``#000``) makes none: no picture holds an
        opaque black pixel.
        """
        document = corpus_document("17")
        svgs = browser_each_rect(document, FIXTURE_17_SVGS)
        hidden = svgs[FIXTURE_17_HIDDEN_SVG]
        assert hidden["w"] == 0 and hidden["h"] == 0, (
            f"fixture drift: the display: none SVG has the rect {hidden}"
        )
        shown = [rect for position, rect in enumerate(svgs) if position != FIXTURE_17_HIDDEN_SVG]
        shown += [browser_rect(document, FIXTURE_17_CANVAS), browser_rect(document, FOOTER_LOGO)]
        shapes = slide_shapes(corpus_export("17"))
        for rect in shown:
            _picture_at(shapes, rect, f"fixture 17's graphic at {rect}")
        extra = [
            _rect(shape)
            for _, shape in _pictures(shapes)
            if not any(_matches_rect(shape, rect) for rect in shown)
        ]
        assert not extra, f"fixture 17 has pictures that are no shown graphic: {extra}"
        for _, picture in _pictures(shapes):
            assert _count(_image(picture, f"picture {_rect(picture)}"), _is_black) == 0, (
                f"the picture at {_rect(picture)} holds the hidden SVG's black"
            )


# ---------------------------------------------------------------------------
# A target its overflow ancestor cuts (C7.3)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def clip_slide() -> dict:
    with pytest.MonkeyPatch.context() as monkeypatch:
        pptx = _export_one(CLIP_BODY, monkeypatch)
    document = _document(CLIP_BODY)
    targets = browser_each_rect(document, ".clip-target")
    frames = browser_each_padding_box(document, ".clip-frame")
    assert len(targets) == len(frames) == len(CLIP_CASES), (
        f"fixture drift: {len(targets)} targets, {len(frames)} frames"
    )
    return {"shapes": slide_shapes(pptx), "targets": targets, "frames": frames}


@pytest.fixture(scope="module")
def edge_cut_slide() -> dict:
    with pytest.MonkeyPatch.context() as monkeypatch:
        pptx = _export_one(EDGE_CUT_BODY, monkeypatch)
    document = _document(EDGE_CUT_BODY)
    return {
        "shapes": slide_shapes(pptx),
        "right": browser_rect(document, "#cut-right"),
        "bottom": browser_rect(document, "#cut-bottom"),
    }


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotClippedCapture:
    @pytest.mark.parametrize("edge", ["right", "bottom"])
    def test_target_cut_at_the_slide_edge_is_twice_its_shown_rect(
        self, edge_cut_slide: dict, edge: str
    ) -> None:
        """A target the slide's right or bottom edge cuts, from a fractional origin, is whole.

        Its picture is at the shown rect (the target's browser rect cut to the
        slide, ending exactly at the viewport's edge) within 0.5 px, and its
        PNG is twice that rect within one device pixel, so the part next to
        the edge is in it, not lost to a clip that cannot reach past the viewport.
        """
        target = edge_cut_slide[edge]
        shown = _intersection(target, SLIDE_RECT)
        cut = {
            "right": target["x"] + target["w"] > SLIDE_RECT["w"],
            "bottom": target["y"] + target["h"] > SLIDE_RECT["h"],
        }
        assert cut[edge] and sum(cut.values()) == 1, (
            f"fixture drift: the slide does not cut {target} at its {edge} alone"
        )
        _, picture = _picture_at(edge_cut_slide["shapes"], shown, f"the box cut at the {edge}")
        image = _image(picture, f"the box cut at the {edge}")
        _assert_twice_its_box(image, shown, f"the box cut at the {edge}")
        centre = _pixel(image, picture, *_centre(shown))
        assert centre[3] >= OPAQUE_ALPHA, f"the box cut at the {edge} is {_show(centre)} inside"

    @pytest.mark.parametrize("case", CLIP_CASES, ids=lambda case: f"{case.kind}-{case.direction}")
    def test_partly_clipped_target_is_its_visible_part(
        self, clip_slide: dict, case: ClipCase
    ) -> None:
        """A target spilling out of an ``overflow: hidden`` frame is captured as the frame shows it.

        The picture's rect is the frame's padding box intersected with the
        target's browser rect (within 0.5 px), never the whole target; its PNG
        is 2x that rect and opaque ``00A972`` throughout, because the cut part
        is not in it. Frames are bordered and padded, so the padding box is
        not the border box; the target spills right and down, or left and up.
        """
        position = CLIP_CASES.index(case)
        target = clip_slide["targets"][position]
        frame = clip_slide["frames"][position]
        visible = _intersection(target, frame)
        assert visible["w"] < target["w"] - 1 and visible["h"] < target["h"] - 1, (
            f"fixture drift: the frame {frame} does not cut the target {target}"
        )
        _, picture = _picture_at(clip_slide["shapes"], visible, f"{case.kind} cut {case.direction}")
        image = _image(picture, f"{case.kind} cut {case.direction}")
        _assert_twice_its_box(image, visible, f"{case.kind} cut {case.direction}")
        green = _count(image, lambda pixel: _is(pixel, GOOD))
        assert green >= 0.99 * image.width * image.height, (
            f"{case.kind} cut {case.direction}: only {green} of {image.width * image.height} "
            f"pixels are opaque #{GOOD}; the picture holds more than the frame shows"
        )


# ---------------------------------------------------------------------------
# Box-only captures: what triggers one, and what stays native
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def box_probe_slide() -> dict:
    with pytest.MonkeyPatch.context() as monkeypatch:
        pptx = _export_one(BOX_PROBE_BODY, monkeypatch)
    document = _document(BOX_PROBE_BODY)
    probes = browser_each_rect(document, ".box-probe")
    assert len(probes) == len(BOX_PROBES), f"fixture drift: {len(probes)} box probes"
    return {
        "pptx": pptx,
        "shapes": slide_shapes(pptx),
        "probes": dict(zip(BOX_PROBES, probes)),
        "plain": browser_rect(document, "#probe-plain"),
        "gradtext": browser_client_rects(document, "#probe-gradtext")
        + [browser_rect(document, "#probe-gradtext-block")],
        "card": browser_rect(document, "#gradient-card"),
        "chip": browser_rect(document, "#card-chip"),
        "shadow": browser_rect(document, "#shadow-card"),
    }


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotBoxOnlyCapture:
    @pytest.mark.parametrize("name", list(BOX_PROBES))
    def test_box_that_a_shape_cannot_paint_is_a_picture(
        self, box_probe_slide: dict, name: str
    ) -> None:
        """A gradient or ``url()`` background, or ``filter``, ``clip-path``, ``mask``,
        ``mix-blend-mode`` or ``backdrop-filter`` on a painted box, is a box-only picture.

        One picture at the box's browser rect, showing what the browser paints
        there: the radial gradient's centre and edge, the image, the halved
        brightness, the triangle ``clip-path`` leaves (its top corners
        transparent), the mask's opaque top and cleared bottom, the blended and
        the translucent fill.
        """
        rect = box_probe_slide["probes"][name]
        _, picture = _picture_at(box_probe_slide["shapes"], rect, f"the {name} box")
        image = _image(picture, f"the {name} box")
        wrong = []
        for across, down, expected in BOX_PROBES[name].samples:
            pixel = _pixel(
                image, picture, rect["x"] + across * rect["w"], rect["y"] + down * rect["h"]
            )
            if expected == "transparent":
                ok = _is_transparent(pixel)
            elif isinstance(expected, tuple):
                colour, alpha = expected
                ok = abs(pixel[3] / 255 - alpha) <= ALPHA_TOLERANCE and all(
                    abs(channel - value) <= COLOUR_TOLERANCE
                    for channel, value in zip(pixel[:3], _rgb(colour))
                )
            else:
                ok = _is(pixel, expected)
            if not ok:
                wrong.append(f"({across:g}, {down:g}) want {expected}, got {_show(pixel)}")
        assert not wrong, f"the {name} box's picture: {wrong}"

    def test_plain_fill_and_gradient_text_are_not_pictures(self, box_probe_slide: dict) -> None:
        """Beside the box captures, a plain fill stays a native shape and gradient text a text run.

        The plain ``8A4FFF`` box is a native shape at its rect, and no picture
        meets it. ``background-clip: text`` (C7.2) is no box capture, on an
        inline span or on a whole block: no picture meets either's words, and
        both are text items.
        """
        shapes = box_probe_slide["shapes"]
        for name, rect in box_probe_slide["probes"].items():
            _picture_at(shapes, rect, f"the {name} box")
        _, plain = _shape_filled(shapes, PLAIN_FILL, "the plain box")
        _assert_box(plain, box_probe_slide["plain"], "the plain box")
        assert not _pictures_over(shapes, box_probe_slide["plain"]), (
            "the plain box became a picture"
        )
        for fragment in box_probe_slide["gradtext"]:
            covering = _pictures_over(shapes, fragment)
            assert not covering, (
                f"the gradient text at {fragment} became a picture: {[_rect(s) for s in covering]}"
            )
        _text_item(shapes, GRADIENT_PROBE_WORDS)
        _text_item(shapes, GRADIENT_BLOCK_WORDS)

    def test_box_capture_leaves_text_and_children_native(self, box_probe_slide: dict) -> None:
        """A gradient card's capture is its box alone: its text and filled child stay native.

        The card's picture is at its browser rect and holds neither its white
        text nor its ``FFD400`` child (the gradient shows under both). The text
        is a text item and the child a native shape at its rect, both above
        the picture.
        """
        shapes = box_probe_slide["shapes"]
        card = box_probe_slide["card"]
        chip = box_probe_slide["chip"]
        card_index, picture = _picture_at(shapes, card, "the gradient card")
        image = _image(picture, "the gradient card")
        white = _count(image, _is_white)
        yellow = _count(image, lambda pixel: _is(pixel, CHIP_FILL, tolerance=40))
        assert white == 0 and yellow == 0, (
            f"the card's picture holds {white} white text pixels and {yellow} child-fill pixels"
        )
        under_chip = _pixel(image, picture, *_centre(chip))
        assert under_chip[3] >= OPAQUE_ALPHA, (
            f"the card's gradient does not show under its child: {_show(under_chip)}"
        )
        text_index, text = _text_item(shapes, CARD_TEXT)
        assert text.paras and all(
            run.color == "FFFFFF" for para in text.paras for run in para.runs if run.text.strip()
        ), "the card's text is not exported white"
        chip_index, chip_shape = _shape_filled(shapes, CHIP_FILL, "the card's child")
        _assert_box(chip_shape, chip, "the card's child")
        assert card_index < text_index and card_index < chip_index, (
            f"the card's text ({text_index}) and child ({chip_index}) are not above its "
            f"picture ({card_index}):\n{_describe(shapes)}"
        )

    def test_box_capture_with_a_shadow_holds_the_shadow(self, box_probe_slide: dict) -> None:
        """A box-only target with an outer shadow is captured with its rect inflated.

        ``box-shadow: 0 6px 12px 2px`` inflates the rect by max(|offset|) +
        blur + spread = 20 px on every side, so the picture holds the shadow:
        below the box it is dark and partly transparent, and the box's centre
        is its opaque gradient. The shadow is drawn once: no native shape over
        the box carries a shadow as well, which would darken it.
        """
        shapes = box_probe_slide["shapes"]
        shadow = box_probe_slide["shadow"]
        _, picture = _picture_at(shapes, _inflated(shadow, SHADOW_INFLATE_PX), "the shadowed box")
        image = _image(picture, "the shadowed box")
        centre_x, centre_y = _centre(shadow)
        inside = _pixel(image, picture, centre_x, centre_y)
        assert inside[3] >= OPAQUE_ALPHA and inside[0] >= 250, (
            f"the shadowed box's centre is {_show(inside)}, not its gradient"
        )
        below = _pixel(image, picture, centre_x, shadow["y"] + shadow["h"] + 8)
        assert 20 <= below[3] < OPAQUE_ALPHA and max(below[:3]) < 100, (
            f"under the shadowed box the picture shows {_show(below)}, not its shadow"
        )
        area = SimpleNamespace(**shadow)
        doubled = [
            _rect(shape)
            for shape in shapes
            if shape.kind != "picture" and shape.shadow is not None and overlaps(shape, area)
        ]
        assert not doubled, f"the box's shadow is drawn a second time, natively, at {doubled}"

    def test_inline_gradient_highlight_is_one_picture_under_its_words(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A wrapping inline span's gradient is one box-only picture, under its native words.

        The span's ``linear-gradient(90deg, FF3621, 2F5BEA)`` paints both of
        its line fragments. The engine captures the span's box once: one
        picture at the union of its client rects (within 0.5 px), 2x it. In it:
        * each fragment shows the gradient: with box-decoration-break: slice
          one gradient runs across the fragments, so the first fragment starts
          ``FF3621`` and the second ends ``2F5BEA``;
        * the union's other corners, where the paragraph's own words lie, are
          transparent: only the span's box is in the picture.
        The words stay an editable white run, above the picture.
        """
        document = _document(HIGHLIGHT_BODY)
        fragments = sorted(browser_client_rects(document, "#highlight"), key=lambda rect: rect["y"])
        assert len(fragments) == 2, f"fixture drift: the highlight has {len(fragments)} fragments"
        first, second = fragments
        left = min(rect["x"] for rect in fragments)
        top = min(rect["y"] for rect in fragments)
        right = max(rect["x"] + rect["w"] for rect in fragments)
        bottom = max(rect["y"] + rect["h"] for rect in fragments)
        union = {"x": left, "y": top, "w": right - left, "h": bottom - top}

        shapes = slide_shapes(_export_one(HIGHLIGHT_BODY, monkeypatch))
        picture_index, picture = _picture_at(shapes, union, "the highlight")
        image = _image(picture, "the highlight")
        _assert_twice_its_box(image, union, "the highlight")
        start = _pixel(
            image, picture, first["x"] + HIGHLIGHT_END_INSET_PX, first["y"] + first["h"] / 2
        )
        end = _pixel(
            image,
            picture,
            second["x"] + second["w"] - HIGHLIGHT_END_INSET_PX,
            second["y"] + second["h"] / 2,
        )
        assert _is(start, ACCENT_2) and _is(end, BLUE), (
            f"the highlight's gradient: first fragment starts {_show(start)} (want #{ACCENT_2}), "
            f"second ends {_show(end)} (want #{BLUE})"
        )
        before = _pixel(image, picture, left + HIGHLIGHT_END_INSET_PX, first["y"] + first["h"] / 2)
        after = _pixel(
            image, picture, right - HIGHLIGHT_END_INSET_PX, second["y"] + second["h"] / 2
        )
        assert _is_transparent(before) and _is_transparent(after), (
            f"the highlight's picture holds more than the span's box: {_show(before)} before "
            f"its first fragment, {_show(after)} after its second"
        )

        text_index, text = _text_item(shapes, HIGHLIGHT_WORD)
        highlighted = [
            run for para in text.paras for run in para.runs if HIGHLIGHT_WORD in run.text
        ]
        assert highlighted and all(run.color == "FFFFFF" for run in highlighted), (
            "the highlighted words are not an editable white run"
        )
        assert picture_index < text_index, (
            f"the highlight's words (spTree {text_index}) are not above its picture "
            f"({picture_index}):\n{_describe(shapes)}"
        )

    def test_box_capture_keeps_a_current_colour_border_and_shadow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A box capture's border and shadow painted in currentColor stay in its picture.

        Box mode makes the target's text transparent through ``color``, which a
        border or shadow with no colour of its own follows. The card's 6 px
        border and its ``0 10px 0 0`` shadow are ``2F5BEA`` (its text colour)
        in the picture, which holds the shadow (its rect grown by 10 px), and
        its text is still an editable ``2F5BEA`` run.
        """
        document = _document(CURRENT_COLOUR_BODY)
        card = browser_rect(document, "#current-colour-card")
        shapes = slide_shapes(_export_one(CURRENT_COLOUR_BODY, monkeypatch))
        _, picture = _picture_at(
            shapes, _inflated(card, CURRENT_COLOUR_REACH_PX), "the currentColor card"
        )
        image = _image(picture, "the currentColor card")
        middle_y = card["y"] + card["h"] / 2
        border = _pixel(image, picture, card["x"] + 3, middle_y)
        shadow = _pixel(image, picture, card["x"] + card["w"] / 2, card["y"] + card["h"] + 5)
        assert _is(border, BLUE) and _is(shadow, BLUE), (
            f"the card's currentColor paint is lost from its picture: border {_show(border)}, "
            f"shadow {_show(shadow)} (want #{BLUE} for both)"
        )
        _, text = _text_item(shapes, CURRENT_COLOUR_TEXT)
        assert text.paras and all(
            run.color == BLUE for para in text.paras for run in para.runs if run.text.strip()
        ), "the card's text is not exported in its colour"

    def test_filter_drop_shadow_grows_the_picture(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A target's ``filter: drop-shadow()`` paints past its box, so its picture holds it.

        ``drop-shadow(0 12px 4px …)`` offsets the shadow 12 px and blurs it with
        a standard deviation of 4 px; the picture grows by the offset plus 2σ,
        as a box-shadow's grows by its blur radius (2σ). Below the icon the
        picture is the shadow's dark ink, and its centre is the icon's ``00A972``.
        """
        icon = browser_rect(_document(DROP_SHADOW_BODY), "#shadowed-icon")
        shapes = slide_shapes(_export_one(DROP_SHADOW_BODY, monkeypatch))
        _, picture = _picture_at(
            shapes, _inflated(icon, DROP_SHADOW_REACH_PX), "the drop-shadowed icon"
        )
        image = _image(picture, "the drop-shadowed icon")
        centre = _pixel(image, picture, *_centre(icon))
        below = _pixel(image, picture, icon["x"] + icon["w"] / 2, icon["y"] + icon["h"] + 8)
        assert _is(centre, GOOD), f"the icon's centre is {_show(centre)}, not #{GOOD}"
        assert below[3] >= 64 and max(below[:3]) < 100, (
            f"under the icon the picture shows {_show(below)}, not its drop shadow"
        )


# ---------------------------------------------------------------------------
# Raster images: embedded as they are, or captured as shown
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def raster_slide() -> dict:
    with pytest.MonkeyPatch.context() as monkeypatch:
        pptx = _export_one(RASTER_BODY, monkeypatch)
    rects = browser_each_rect(_document(RASTER_BODY), ".raster-probe")
    assert len(rects) == len(RASTER_CASES), f"fixture drift: {len(rects)} raster images"
    return {"shapes": slide_shapes(pptx), "rects": dict(zip(RASTER_CASES, rects))}


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotRasterImages:
    @pytest.mark.parametrize("name", list(RASTER_CASES))
    def test_raster_image_is_embedded_or_captured_as_shown(
        self, raster_slide: dict, name: str
    ) -> None:
        """A raster ``data:`` ``<img>`` is embedded as is only when the browser shows it as is.

        * ``plain``: the picture's bytes are the source PNG's.
        * ``rounded`` (``border-radius: 50%``): captured with its corners cut
          (transparent) and its centre ``00A972``.
        * ``cover`` (``object-fit: cover`` of a three-band 3:1 image in a square):
          only the middle ``00A972`` band, at its left, centre and right.
        * ``filtered`` (``filter: invert(1)``): ``FF568D`` at its centre.
        * ``outlined`` (a 4 px spread ``box-shadow`` in ``1B3139``): the rect
          inflated by 4 px, the outline at its edge and ``00A972`` within.
        """
        case = RASTER_CASES[name]
        rect = raster_slide["rects"][name]
        expected = _inflated(rect, case.inflate_px)
        _, picture = _picture_at(raster_slide["shapes"], expected, f"the {name} image")
        if name == "plain":
            assert picture.image == GREEN_PNG, "the plain raster image is not embedded as it is"
            return
        image = _image(picture, f"the {name} image")
        _assert_twice_its_box(image, expected, f"the {name} image")
        centre_x, centre_y = _centre(rect)
        centre = _pixel(image, picture, centre_x, centre_y)
        if name == "rounded":
            corner = _pixel(image, picture, rect["x"] + 3, rect["y"] + 3)
            assert _is_transparent(corner) and _is(centre, GOOD), (
                f"rounded image: corner {_show(corner)} (want transparent), centre {_show(centre)}"
            )
        elif name == "cover":
            samples = [
                _pixel(image, picture, x, centre_y)
                for x in (rect["x"] + 5, centre_x, rect["x"] + rect["w"] - 5)
            ]
            assert all(_is(pixel, GOOD) for pixel in samples), (
                f"cover image: {[_show(pixel) for pixel in samples]} (want the middle band #{GOOD})"
            )
        elif name == "filtered":
            assert _is(centre, INVERTED_GOOD), f"filtered image: centre {_show(centre)}"
        elif name == "outlined":
            edge = _pixel(image, picture, rect["x"] - 2, centre_y)
            assert _is(edge, INK) and _is(centre, GOOD), (
                f"outlined image: edge {_show(edge)} (want #{INK}), centre {_show(centre)}"
            )

    def test_local_and_remote_sources_never_reach_the_deck(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SDR-4437: a source outside ``data:`` never reaches the deck, captured or not.

        A capture screenshots whatever the page loaded, so under the export
        document's CSP (``img-src data:``, from ``build_slide_html``) a local
        ``file://`` image or a remote one must load nowhere: not as an
        ``<img>`` (plain, or rounded, which would be captured), not as a
        box's ``url()`` background (a box capture), not as an SVG ``<image>``
        (a subtree capture). The local file is a ``#00FF00`` PNG: no media
        part holds its bytes, no picture holds a ``#00FF00`` pixel, and no
        picture lies at any of the three ``<img>`` rects.
        """
        local = tmp_path / "local-secret.png"
        local.write_bytes(_png_bytes(Image.new("RGBA", (64, 64), _rgb(LEAK) + (255,))))
        uri = local.as_uri()
        body = (
            '<div class="slide">'
            f'<img class="outside" src="{uri}" alt="" style="position: absolute; left: 80px; '
            'top: 120px; width: 160px; height: 160px;">'
            f'<img class="outside" src="{uri}" alt="" style="position: absolute; left: 280px; '
            'top: 120px; width: 160px; height: 160px; border-radius: 12px;">'
            '<img class="outside" src="https://example.com/a.png" alt="" style="position: '
            'absolute; left: 480px; top: 120px; width: 160px; height: 160px;">'
            '<div style="position: absolute; left: 80px; top: 340px; width: 240px; height: '
            f"160px; background: url('{uri}') center / cover;\"></div>"
            '<svg width="240" height="160" viewBox="0 0 240 160" style="position: absolute; '
            f'left: 380px; top: 340px;"><image href="{uri}" width="240" height="160"/></svg>'
            "</div>"
        )
        rects = browser_each_rect(_document(body), "img.outside")
        assert len(rects) == 3, f"fixture drift: {len(rects)} outside images"

        pptx = _export_one(body, monkeypatch)
        secret = local.read_bytes()
        with zipfile.ZipFile(BytesIO(pptx)) as archive:
            media = {
                name: archive.read(name)
                for name in archive.namelist()
                if name.startswith("ppt/media/") and not name.endswith("/")
            }
        holding = sorted(name for name, data in media.items() if secret in data)
        assert not holding, f"the local file's bytes are embedded in {holding}"
        leaking = {
            name: leaked
            for name, data in media.items()
            if data[:8] == PNG_SIGNATURE
            and (leaked := _count(Image.open(BytesIO(data)).convert("RGBA"), _is_leak))
        }
        assert not leaking, f"pictures show the local file's #{LEAK}: {leaking}"
        shapes = slide_shapes(pptx)
        placed = [_rect(shape) for rect in rects for shape in _pictures_over(shapes, rect)]
        assert not placed, f"pictures stand where the outside images are: {placed}"


# ---------------------------------------------------------------------------
# Opacity, determinism and timing
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotCaptureOutput:
    def test_captured_picture_shows_the_browser_opacity_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A chart inside an ``opacity: 0.5`` group shows at 0.5, not 0.25.

        The capture already carries the group's opacity, so the alpha the
        slide shows at the chart's centre (the PNG's alpha times any alpha the
        picture applies on top) is 0.5 within 0.04, and the colour is the
        chart's ``FF3621``.
        """
        document = _document(FADED_BODY)
        chart = browser_rect(document, "#faded-chart")
        pptx = _export_one(FADED_BODY, monkeypatch)
        index, picture = _picture_at(slide_shapes(pptx), chart, "the faded chart")
        pixel = _pixel(_image(picture, "the faded chart"), picture, *_centre(chart))
        shown = pixel[3] / 255 * _picture_alpha(pptx, index)
        assert abs(shown - FADE_OPACITY) <= ALPHA_TOLERANCE, (
            f"the faded chart shows at alpha {shown:.3f} (PNG {_show(pixel)}, picture alpha "
            f"{_picture_alpha(pptx, index):.3f}), not the browser's {FADE_OPACITY}"
        )
        assert all(
            abs(channel - value) <= COLOUR_TOLERANCE
            for channel, value in zip(pixel[:3], _rgb(ACCENT_2))
        ), f"the faded chart's colour is {_show(pixel)}, not #{ACCENT_2}"

    def test_repeated_exports_are_identical(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """C7.4: repeated exports of fixture 03, captures included, are byte-identical.

        Every export is of the same rendered page: fixture 03 on the corpus
        deck, its CSS and Chart.js scripts, with the deck's fonts pinned (the
        faces its Google Fonts @import loads, embedded as data:,
        ``pinned_font_css``), so no font the network serves can differ
        between them. A rasterization that is not deterministic (GPU
        anti-aliasing) draws one chart in a few differently, so there are
        ``DETERMINISM_EXPORTS`` exports, each holding the slide
        ``DETERMINISM_SLIDES`` times, and every export is held against the
        first: each slide holds the chart's picture, and each export's
        structural manifest (every part's SHA-256, ``docProps/core.xml``
        timestamps masked) equals the first's.
        """
        css = pinned_font_css()
        body = corpus_slide("03")
        scripts = CORPUS_DECK.get("scripts", "")
        external_scripts = tuple(CORPUS_DECK.get("external_scripts", []))
        document = slide_document(body, css=css, scripts=scripts, external_scripts=external_scripts)
        chart = browser_rect(document, CHART)
        exports = []
        for _ in range(DETERMINISM_EXPORTS):
            pptx, failures = export_slides(
                [body] * DETERMINISM_SLIDES,
                css=css,
                scripts=scripts,
                external_scripts=external_scripts,
                monkeypatch=monkeypatch,
            )
            assert failures == [], f"the export rejected corpus slide 03: {failures}"
            for index in range(DETERMINISM_SLIDES):
                _picture_at(slide_shapes(pptx, index), chart, f"slide {index + 1}'s chart")
            exports.append(pptx)
        first = exports[0]
        first_manifest = structural_manifest(first)
        mismatches = []
        for number, other in enumerate(exports[1:], start=2):
            manifest = structural_manifest(other)
            if manifest == first_manifest:
                continue
            differing = sorted(
                name
                for name in set(first_manifest["sha256"]) | set(manifest["sha256"])
                if first_manifest["sha256"].get(name) != manifest["sha256"].get(name)
            )
            mismatches.append(
                f"export {number} differs from export 1 in {differing}"
                + "".join(
                    f"\n  {name}: {_media_difference(first, other, name)}" for name in differing
                )
            )
        assert not mismatches, (
            f"{len(mismatches)} of {DETERMINISM_EXPORTS - 1} exports differ from the first:\n"
            + "\n".join(mismatches)
        )

    def test_twenty_chart_slides_export_within_budget(
        self, record_property: Callable[[str, object], None], chart_geometry: dict
    ) -> None:
        """Review Focus 1: 20 copies of fixture 03, one chart capture each, export in under 120 s.

        The sidecar's timeout is 180 s; the plan's budget on the dev Mac is
        120 s. The time is recorded as ``export_seconds`` (``record_property``),
        and every slide holds its chart's picture, so the time is that of a
        deck that really captured its charts.
        """
        start = time.monotonic()
        with pytest.MonkeyPatch.context() as monkeypatch:
            pptx, failures = export_corpus(["03"] * TIMING_SLIDE_COUNT, monkeypatch=monkeypatch)
        elapsed = time.monotonic() - start
        record_property("export_seconds", round(elapsed, 2))
        record_property("slides", TIMING_SLIDE_COUNT)
        assert failures == [], f"the export rejected slides: {failures}"
        chart = chart_geometry["chart"]
        for index in range(TIMING_SLIDE_COUNT):
            _picture_at(slide_shapes(pptx, index), chart, f"slide {index + 1}'s chart")
        assert elapsed < TIMING_BUDGET_SECONDS, (
            f"{TIMING_SLIDE_COUNT} chart slides took {elapsed:.1f} s, over the "
            f"{TIMING_BUDGET_SECONDS:g} s budget"
        )
