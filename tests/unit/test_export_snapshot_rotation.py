"""Snapshot engine: rotated text, vertical writing modes and ``text-overflow: ellipsis``.

Text under a rotation is one text item, the way PowerPoint and Google Slides
hold it: the element's UNROTATED box, turned by its angle, holding its lines.
Range rects cannot give those lines, because under a rotation each character's
rect is the axis-aligned bounds of the turned glyph, so line clustering splits
a label into one line per word. So the nearest rotated element's text is one
item:

* its box is the element's untransformed layout box, ``offsetWidth`` x
  ``offsetHeight`` (times any scale), centred where its bounding rect is
  centred (a rotated rectangle's bounds share its centre), grown along its
  width by the usual slack on the side its alignment grows, with that layout
  box kept in place (R11f: Google Slides wraps a line at its box's exact width);
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

import dataclasses
import json
import math
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.services import pptx_from_html_huashu
from tests.fixtures.export_snapshot_support import (
    ANGLE_UNITS_PER_DEGREE,
    DECK_CSS,
    DRIVE_FILES_URL,
    EMU_PER_PX,
    NAMESPACES,
    BrowserEllipsis,
    Run,
    Shape,
    browser_ascent,
    browser_each_layout_box,
    browser_each_rect,
    browser_ellipsis,
    browser_lines,
    browser_probes,
    browser_style,
    browser_tables,
    browser_text,
    corpus_document,
    delete_drive_file,
    drive_file_exists,
    emit_text_constant,
    export_corpus,
    export_documents,
    export_slides,
    fidelity_harness,
    google_slides_presentation,
    node_json,
    requires_google_slides,
    requires_huashu_sidecar,
    single_line_box_top,
    slide_document,
    slide_shape_elements,
    slide_shapes,
    table_extent,
    table_frames,
)
from tests.unit.test_export_collection_iteration_hostile_realm import (
    HOSTILE_EXPORT_TIMEOUT_SECONDS,
)
from tests.unit.test_export_slide_root_background import FIXTURE_DIR
from tests.unit.test_export_snapshot_line_spacing import _assert_script_run_size, _script_factor
from tests.unit.test_export_svg_raster import structural_manifest

ENGINE = "snapshot"

# The brief: the unrotated box and its centre agree with the browser within 1 px
# (offsetWidth and offsetHeight are whole px; the bounds are not).
GEOMETRY_TOLERANCE_PX = 1.0
# rot is written in 60000ths of a degree, so a right angle is exact and any
# other angle is within a 60000th.
ANGLE_TOLERANCE_DEGREES = 0.01
# R11f: a turned box keeps the usual width slack (spec §3 Text, Wrapping), at
# most this fraction of its inline length plus this many px.
SLACK_FRACTION = 0.06
SLACK_PX = 4.0
# Where the slack lies along the box's inline axis, as the shift from the box's
# centre to its layout box's centre, in units of the slack: right of
# left-aligned text, left of right-aligned text, half each side of centred.
LAYOUT_SHIFT_PER_SLACK = {"left": -0.5, "right": 0.5, "center": 0.0}
# The side of the turned box each of its local sides lies on in the page, per
# writing mode: its left is the line-left side, its right the line-right side
# (CSS Writing Modes 4). Horizontal text keeps its own.
LINE_SIDES = {
    "horizontal-tb": ("left", "right"),
    "vertical-rl": ("top", "bottom"),
    "vertical-lr": ("top", "bottom"),
    "sideways-rl": ("top", "bottom"),
    "sideways-lr": ("bottom", "top"),
}
# A computed text-align as the alignment a turned box's paragraphs are written
# with, left to right ("start" and "end" follow the direction; justify is
# written from its start side).
TEXT_ALIGN_WRITTEN = {
    ("start", "ltr"): "left",
    ("start", "rtl"): "right",
    ("end", "ltr"): "right",
    ("end", "rtl"): "left",
    ("left", "ltr"): "left",
    ("left", "rtl"): "left",
    ("right", "ltr"): "right",
    ("right", "rtl"): "right",
    ("center", "ltr"): "center",
    ("center", "rtl"): "center",
    ("justify", "ltr"): "left",
    ("justify", "rtl"): "right",
}
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
/* Tailwind's Preflight sub and sup, as Tellr's prompts offer it, scoped to .preflight. */
.preflight sub, .preflight sup { font-size: 75%; line-height: 0; position: relative;
                                 vertical-align: baseline; }
.preflight sup { top: -0.5em; }
.preflight sub { bottom: -0.25em; }
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


# Fix round 1's turned labels: absolutely placed and turned a quarter left.
TURNED_LABEL = "position:absolute; transform:rotate(-90deg); font-size:16px;"
SOFT_WRAP_TEXT = "Quarterly revenue by region and product line"
TURNED_TABLE_CELLS = ("North", "42", "South", "17")


# Fix round 2: a turned label (#t) beside its unturned twin (#w), the same
# content; a transform moves no layout, so the twin is the turned label's oracle.
TWIN_ANGLES = {"12": "12deg", "40": "40deg"}
TWIN_ANGLE_DEGREES = {"12": 12.0, "40": 40.0}
TWIN_CHIP = '<span style="display:inline-block; padding:0 10px; background:#DDDDDD">LIVE</span>'
MIXED_SEGMENT_LINE = (
    f'Status {TWIN_CHIP} <span style="font-size:12px">since</span> '
    '<span style="font-size:28px">May</span>'
)
MIXED_SEGMENT = "since May"
TWIN_LIST_ITEMS = "<li>First step</li><li>Second step</li>"
TWIN_LIST_MARKERS = ("1.", "2.")
SUPERSCRIPT_LINE = '<span id="{prefix}lead">Revenue</span><sup>1</sup> grew'
SUPERSCRIPT_SIZE_PX = 20.0
ELLIPSIS_SUPERSCRIPT_LINE = (
    '<span id="lead">Revenue</span><sup>1</sup> grew in every region this quarter'
)
# Preflight's script lines, and of each its lead word, its script run's text and baseline shift.
PREFLIGHT_LINES = {
    "sup": '<span id="lead">Revenue</span><sup>1</sup> grew',
    "sub": '<span id="lead">CO</span><sub>2</sub> output fell',
}
PREFLIGHT_SCRIPTS = {"sup": ("Revenue", "1", "super"), "sub": ("CO", "2", "sub")}
# A script run on a paragraph's second line (20 px, line-height 29 px): the
# browser's own superscript grows that line's box, Preflight's and a subscript
# do not move its baseline. Each: its class and its second line.
LATER_SCRIPT_LINES = {
    "sup": ("", "margin<sup>1</sup> held"),
    "preflight": ("preflight", "margin<sup>1</sup> held"),
    "sub": ("", "CO<sub>2</sub> fell"),
}
LATER_LINE_HEIGHT_PX = 29.0
# A line the browser set this much past its line height grew (snapshot_text.mjs).
LINE_GROWTH_MIN_PX = 0.5
# A script run's written size, in pt, within this of the rule's.
SCRIPT_SIZE_TOLERANCE_PT = 0.05
# a:rPr baseline is in 1000ths of a percent of the run's size.
BASELINE_UNITS = 100000
TYPOGRAPHY_MODULE = Path(pptx_from_html_huashu.SIDECAR_DIR) / "emit_typography.cjs"
SLIDE_WIDTH_PX = 1280
# R11g: a script line's baseline in Google Slides is the browser's within this.
GOOGLE_BASELINE_TOLERANCE_PX = 1.5


def _twin_pair(
    angle_css: str, inner: str, *, font_size: int = 16, tag: str = "div", extra: str = ""
) -> str:
    """A slide holding ``inner`` turned by ``angle_css`` as #t, and unturned as #w.

    ``{prefix}`` in ``inner`` names its ids apart: "t-" in the turned label,
    "w-" in its twin.
    """
    base = f"position:absolute; white-space:nowrap; font-size:{font_size}px; {extra}"
    turned = inner.replace("{prefix}", "t-")
    twin = inner.replace("{prefix}", "w-")
    return (
        f'<div class="slide"><{tag} id="t" style="{base} left:640px; top:250px; '
        f'transform:rotate({angle_css});">{turned}</{tag}>'
        f'<{tag} id="w" style="{base} left:60px; top:560px;">{twin}</{tag}></div>'
    )


def _twin_list(angle_css: str) -> str:
    """A 24 px ordered list turned by ``angle_css`` as #t, beside its unturned twin #w."""
    base = "position:absolute; white-space:nowrap; font-size:24px; margin:0; padding-left:34px;"
    return (
        f'<div class="slide"><ol id="t" style="{base} left:640px; top:250px; '
        f'transform:rotate({angle_css});">{TWIN_LIST_ITEMS}</ol>'
        f'<ol id="w" style="{base} left:60px; top:540px;">{TWIN_LIST_ITEMS}</ol></div>'
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
    # Fix round 1. The rotation is the parent's: its in-flow child joins its
    # text, its positioned child is a turned item of its own.
    "ancestor-block": (
        f'<div class="slide"><div id="parent" style="{TURNED_LABEL} left:300px; top:300px; '
        'white-space:nowrap;"><p id="child" style="margin:0">Child block text</p></div></div>'
    ),
    "ancestor-positioned": (
        '<div class="slide"><div id="parent" style="position:absolute; left:600px; top:300px; '
        'width:220px; height:40px; transform:rotate(-90deg); background:#EEEEEE;">'
        '<div id="child" style="position:absolute; left:10px; top:8px; font-size:16px; '
        'white-space:nowrap;">Positioned child</div></div></div>'
    ),
    # A turned line cut by an inline-block chip and by a hidden word.
    "gap-chip": (
        f'<div class="slide"><div id="target" style="{TURNED_LABEL} left:700px; top:300px; '
        'white-space:nowrap;"><span id="before">Status</span> <span id="chip" '
        'style="display:inline-block; padding:0 10px; background:#DDDDDD">LIVE</span> '
        '<span id="after">since May</span></div></div>'
    ),
    "gap-hidden": (
        f'<div class="slide"><div id="target" style="{TURNED_LABEL} left:700px; top:300px; '
        'white-space:nowrap;"><span id="before">Before</span> '
        '<span style="visibility:hidden">secret</span> <span id="after">after</span></div></div>'
    ),
    "rotated-table": (
        '<div class="slide"><table id="target" style="position:absolute; left:400px; top:300px; '
        'transform:rotate(-90deg); border-collapse:collapse; font-size:16px;">'
        '<tr><td style="padding:4px 10px">North</td><td style="padding:4px 10px">42</td></tr>'
        '<tr><td style="padding:4px 10px">South</td><td style="padding:4px 10px">17</td></tr>'
        "</table></div>"
    ),
    "rotated-list": (
        f'<div class="slide"><ul id="target" style="{TURNED_LABEL} left:900px; top:250px; '
        'margin:0; padding-left:24px; white-space:nowrap;">'
        '<li><span id="alpha">Alpha item</span></li><li><span id="beta">Beta item</span></li>'
        "</ul></div>"
    ),
    "trailing-br": (
        f'<div class="slide"><div id="target" style="{TURNED_LABEL} left:600px; top:300px; '
        'white-space:nowrap;"><div>Line one<br></div><div>Line two</div></div></div>'
    ),
    "align-right": (
        f'<div class="slide"><div id="target" style="{TURNED_LABEL} left:200px; top:300px; '
        'width:240px; text-align:right;">Right aligned</div></div>'
    ),
    "align-center": (
        f'<div class="slide"><div id="target" style="{TURNED_LABEL} left:500px; top:300px; '
        'width:240px; text-align:center;">Centred label</div></div>'
    ),
    # The same 150 px paragraph turned and, as the browser's line oracle, not.
    "soft-wrap": (
        f'<div class="slide"><div id="target" style="{TURNED_LABEL} left:900px; top:300px; '
        f'width:150px;">{SOFT_WRAP_TEXT}</div>'
        '<div id="twin" style="position:absolute; left:100px; top:500px; font-size:16px; '
        f'width:150px;">{SOFT_WRAP_TEXT}</div></div>'
    ),
    # Fix round 2. A blank line a <br> opens inside a turned root.
    "leading-br": _twin_pair(
        "-90deg",
        '<div><span id="{prefix}a">Alpha</span></div>'
        '<div><br><span id="{prefix}b">Beta</span></div>',
    ),
    "double-br": _twin_pair(
        "-90deg",
        '<div><span id="{prefix}a">Alpha</span><br><br></div>'
        '<div><span id="{prefix}b">Beta</span></div>',
    ),
    # A vertical-rl inline padded along its inline axis (its top and bottom).
    "vertical-pad": (
        '<div class="slide"><div id="target" style="position:absolute; left:640px; top:150px; '
        'font-size:16px; white-space:nowrap; writing-mode:vertical-rl;">'
        '<span id="status">Status</span> <span style="padding-top:24px; padding-bottom:24px;">'
        '<span id="mid">mid</span></span> <span id="end">end</span></div></div>'
    ),
    # A segment mixing 12 px and 28 px text, and a 24 px ordered list, each
    # turned 12 and 40 degrees beside an unturned twin.
    **{f"mixed-{name}": _twin_pair(css, MIXED_SEGMENT_LINE) for name, css in TWIN_ANGLES.items()},
    **{f"ol-{name}": _twin_list(css) for name, css in TWIN_ANGLES.items()},
    # A 20 px paragraph holding a superscript, unturned, and turned beside its twin.
    "superscript": (
        '<div class="slide"><p id="target" style="position:absolute; left:100px; top:150px; '
        f'margin:0; font-size:20px; white-space:nowrap;">'
        f"{SUPERSCRIPT_LINE.replace('{prefix}', '')}</p></div>"
    ),
    "superscript-turned": _twin_pair(
        "-90deg", SUPERSCRIPT_LINE, font_size=20, tag="p", extra="margin:0;"
    ),
    # Fix round 3. A superscript line cut by an ellipsis, and Preflight's sub and sup.
    "ellipsis-superscript": (
        '<div class="slide"><p id="target" style="position:absolute; left:100px; top:150px; '
        "width:300px; margin:0; font-size:20px; white-space:nowrap; overflow:hidden; "
        f'text-overflow:ellipsis;">{ELLIPSIS_SUPERSCRIPT_LINE}</p></div>'
    ),
    **{
        f"later-{name}": (
            f'<div class="slide"><p id="target" class="{css_class}" style="position:absolute; '
            "left:100px; top:150px; margin:0; font-size:20px; line-height:29px; "
            f'white-space:nowrap;"><span id="first">Alpha</span> revenue grew<br>'
            f'<span id="second">Gamma</span> {line}</p></div>'
        )
        for name, (css_class, line) in LATER_SCRIPT_LINES.items()
    },
    **{
        f"preflight-{script}": (
            '<div class="slide"><p id="target" class="preflight" style="position:absolute; '
            'left:100px; top:150px; margin:0; font-size:20px; white-space:nowrap;">'
            f"{line}</p></div>"
        )
        for script, line in PREFLIGHT_LINES.items()
    },
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
    """``item`` is its element's unrotated box plus its slack, turned by ``angle``.

    The unrotated layout box is ``offsetWidth`` x ``offsetHeight``; under a
    vertical writing mode it is the inline length by the block length,
    ``offsetHeight`` x ``offsetWidth`` (R11a). R11f: the item's box is that
    box grown along its own inline axis by its slack, which lies on the side
    its alignment grows (right of left-aligned text, left of right-aligned,
    half each side of centred) and is between 0 and 6% + 4 px of the inline
    length (plus 1 px). So the box LESS its slack is the layout box, within
    1 px, centred on the bounds' centre within 1 px: the layout box, and the
    text's start with it, stays where the browser has it. A slack grown on
    the other side, or a box grown about its own centre, moves the layout part
    off the bounds' centre by half the slack.

    The alignment is the browser's: the element's computed text-align and
    direction, which the item's paragraphs must be written with (Minor 7).
    R11f′: the room on the growth side, its padding plus the box's growth
    there, reaches the usual slack, 6% of the content's inline length + 4 px,
    within 1 px; a box that drops the slack has none.
    """
    _assert_angle(item, angle, what)
    width, height = (
        (layout["offset_h"], layout["offset_w"])
        if vertical
        else (layout["offset_w"], layout["offset_h"])
    )
    slack = item.w - width
    most = width * SLACK_FRACTION + SLACK_PX + GEOMETRY_TOLERANCE_PX
    assert (
        -GEOMETRY_TOLERANCE_PX <= slack <= most and abs(item.h - height) <= GEOMETRY_TOLERANCE_PX
    ), (
        f"{what}: its unrotated box is {item.w:.2f} x {item.h:.2f}; expected the "
        f"{'inline by block length' if vertical else 'offset size'} {width:g} x {height:g} plus a "
        f"slack of 0 to {most:.2f} px along its width (it is {slack:.2f}), height within "
        f"{GEOMETRY_TOLERANCE_PX} px. The bounds are {layout['w']:.2f} x {layout['h']:.2f}."
    )
    key = (layout["text_align"], layout["direction"])
    assert key in TEXT_ALIGN_WRITTEN and layout["writing_mode"] in LINE_SIDES, (
        f"fixture drift: {what} computes text-align {key} in {layout['writing_mode']}"
    )
    align = TEXT_ALIGN_WRITTEN[key]
    alignments = {paragraph.align for paragraph in item.paras}
    assert alignments == {align}, (
        f"{what}: its paragraphs are aligned {alignments}; the browser computes text-align "
        f"{layout['text_align']} ({layout['direction']}), written {align!r}"
    )
    line_left, line_right = LINE_SIDES[layout["writing_mode"]]
    padding = layout["padding"]
    content = (
        width
        - padding[line_left]
        - padding[line_right]
        - layout["border"][line_left]
        - layout["border"][line_right]
    )
    needed = content * SLACK_FRACTION + SLACK_PX - GEOMETRY_TOLERANCE_PX
    padding_room = {
        "left": padding[line_right],
        "right": padding[line_left],
        "center": padding[line_left] + padding[line_right],
    }[align]
    assert padding_room + slack >= needed, (
        f"{what}: the room on its {align}-aligned growth side is {padding_room:g} px of padding "
        f"plus {slack:.2f} px the box grew, under the {needed + GEOMETRY_TOLERANCE_PX:.2f} px "
        f"slack its {content:.2f} px content needs (6% + {SLACK_PX:g} px, tolerance "
        f"{GEOMETRY_TOLERANCE_PX} px): Google Slides would wrap its line"
    )
    shift = LAYOUT_SHIFT_PER_SLACK[align] * slack
    radians = math.radians(item.rotation)
    centre = _centre(item)
    emitted = (centre[0] + shift * math.cos(radians), centre[1] + shift * math.sin(radians))
    expected = _centre(layout)
    off = (round(emitted[0] - expected[0], 3), round(emitted[1] - expected[1], 3))
    assert all(abs(delta) <= GEOMETRY_TOLERANCE_PX for delta in off), (
        f"{what}: its layout box (its box less the {slack:.2f} px slack on the {align}-aligned "
        f"growth side) is centred at {emitted}, the browser bounds at {expected} (off by {off}, "
        f"tolerance {GEOMETRY_TOLERANCE_PX} px)"
    )


def _assert_one_line(item: Shape, expected: str, what: str) -> None:
    assert _lines(item) == [expected], (
        f"{what}: the item's lines are {_lines(item)}, expected the one line {[expected]}"
    )
    assert len(item.paras) == 1, f"{what}: {len(item.paras)} paragraphs, expected one"
    assert item.wrap == "none", f"{what}: bodyPr wrap is {item.wrap!r}, expected 'none'"


def _along(point: tuple[float, float], rotation: float) -> float:
    """Where a slide point lies along the line axis of a box turned by ``rotation`` degrees."""
    radians = math.radians(rotation)
    return point[0] * math.cos(radians) + point[1] * math.sin(radians)


def _span_along(rect: dict, rotation: float) -> tuple[float, float]:
    """(start, end) of a browser rect along the line axis of ``rotation``: its corners' extremes.

    Under a quarter turn the rect of a turned run is the run's own box, so its
    extent along the axis is exact.
    """
    corners = [
        (rect["x"] + dx, rect["y"] + dy) for dx in (0.0, rect["w"]) for dy in (0.0, rect["h"])
    ]
    values = [_along(corner, rotation) for corner in corners]
    return min(values), max(values)


def _box_start_along(item: Shape) -> float:
    """Where an item's box starts along its own line axis: its left side, turned with it."""
    return _along(_centre(item), item.rotation) - item.w / 2


def _inset_px(pptx: bytes, name: str, position: int, attribute: str) -> float:
    """The bodyPr ``attribute`` (lIns, tIns...) of spTree element ``position`` of ``name``, px."""
    element = slide_shape_elements(pptx, _slide_index(name))[position]
    body = element.find("p:txBody/a:bodyPr", NAMESPACES)
    assert body is not None, f"spTree element {position} of {name} has no bodyPr"
    return int(body.get(attribute, 0)) / EMU_PER_PX


def _turned_local(centre: tuple[float, float], angle: float, point: tuple[float, float]) -> tuple:
    """(along, across) of a slide point in the frame turned by ``angle`` about ``centre``."""
    radians = math.radians(angle)
    dx, dy = point[0] - centre[0], point[1] - centre[1]
    return (
        dx * math.cos(radians) + dy * math.sin(radians),
        -dx * math.sin(radians) + dy * math.cos(radians),
    )


def _items_reading(shapes: list[Shape], text: str, angle: float) -> list[tuple[int, Shape]]:
    """(spTree index, shape) of each text item turned by ``angle`` reading exactly ``text``."""
    return [
        (position, shape)
        for position, shape in enumerate(shapes)
        if shape.kind == "text"
        and _normalised(shape.text) == text
        and _angle_off(shape.rotation, angle) <= ANGLE_TOLERANCE_DEGREES
    ]


def _assert_matches_twin(
    shapes: list[Shape], document: str, angle: float, text: str, what: str
) -> None:
    """The turned item reading ``text`` sits in #t's frame where #w's unturned one sits in #w's.

    A transform moves no layout, so the turned label #t and its unturned twin
    #w lay their text out alike, each about its own bounds' centre. The turned
    item, turned back by ``angle`` about #t's centre, must start along its line,
    start across it and run as long as the twin's unturned item does about
    #w's centre, each within 1 px. Both boxes are the emitter's, the first-line
    raise included, so the twin also checks the raise of a turned box along its
    own up.
    """
    turned = _items_reading(shapes, text, angle)
    twin = _items_reading(shapes, text, 0.0)
    assert len(turned) == 1 and len(twin) == 1, (
        f"{what}: expected one item reading {text!r} turned {angle:g} degrees and one unturned, "
        f"got {len(turned)} and {len(twin)}:\n{_describe(shapes)}"
    )
    item = turned[0][1]
    unturned = twin[0][1]
    turned_centre = _centre(_layout(document, "#t"))
    twin_centre = _centre(_layout(document, "#w"))
    along, across = _turned_local(turned_centre, angle, _centre(item))
    emitted = (along - item.w / 2, across - item.h / 2, item.w)
    expected = (unturned.x - twin_centre[0], unturned.y - twin_centre[1], unturned.w)
    off = tuple(round(value - oracle, 3) for value, oracle in zip(emitted, expected))
    assert all(abs(delta) <= GEOMETRY_TOLERANCE_PX for delta in off), (
        f"{what}: in its label's frame the turned item starts at {emitted[:2]} and is "
        f"{emitted[2]:.2f} long; its unturned twin at {expected[:2]}, {expected[2]:.2f} long "
        f"(along, across, length off by {off}, tolerance {GEOMETRY_TOLERANCE_PX} px)"
    )


def _assert_starts_at(item: Shape, rect: dict, what: str, inset: float = 0.0) -> None:
    """``item``'s text (its box start plus ``inset``) starts along its line where ``rect`` does."""
    start = _box_start_along(item) + inset
    expected, _ = _span_along(rect, item.rotation)
    assert abs(start - expected) <= GEOMETRY_TOLERANCE_PX, (
        f"{what}: its text starts {start:.2f} px along its line, the browser's at "
        f"{expected:.2f} (off by {start - expected:.2f}, tolerance {GEOMETRY_TOLERANCE_PX} px)"
    )


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


@pytest.mark.slow
@requires_huashu_sidecar
class TestAncestorRotation:
    def test_an_in_flow_child_of_a_rotated_parent_joins_its_turned_item(
        self, rotation_pptx: bytes
    ) -> None:
        """The brief: the rotation may be an ancestor's. A turned parent's in-flow ``<p>``.

        The ``<p>`` has no transform of its own; its parent is turned by
        ``rotate(-90deg)``. Its text is the parent's ONE turned item: ``rot``
        270 degrees, one line, on the parent's layout box (the parent holds
        nothing else). Read from the child's own transform, the text would be
        an unturned box clustered from turned rects.
        """
        document = _document("ancestor-block")
        parent = _layout(document, "#parent")
        child = _layout(document, "#child")
        assert (
            child["transform"] == "none" and parent["transform"] == "matrix(0, -1, 1, 0, 0, 0)"
        ), (
            f"fixture drift: the child computes {child['transform']}, "
            f"the parent {parent['transform']}"
        )
        _, item = _text_item(_shapes(rotation_pptx, "ancestor-block"), "Child", "the in-flow child")

        _assert_one_line(item, "Child block text", "the in-flow child")
        _assert_turned_box(item, parent, 270.0, "the in-flow child")

    def test_a_positioned_child_of_a_rotated_parent_is_its_own_turned_item(
        self, rotation_pptx: bytes
    ) -> None:
        """The brief: an absolutely positioned child of a turned parent is turned with it.

        It paints in a group of its own, so its text is a turned item of its
        own: ``rot`` 270 degrees, one line, on ITS layout box, centred on its
        own bounds, not on its parent's.
        """
        document = _document("ancestor-positioned")
        child = _layout(document, "#child")
        assert child["transform"] == "none", (
            f"fixture drift: the child computes {child['transform']}"
        )
        _, item = _text_item(
            _shapes(rotation_pptx, "ancestor-positioned"), "Positioned", "the positioned child"
        )

        _assert_one_line(item, "Positioned child", "the positioned child")
        _assert_turned_box(item, child, 270.0, "the positioned child")


@pytest.mark.slow
@requires_huashu_sidecar
class TestTurnedLineCuts:
    def test_a_chip_cuts_a_turned_line_into_turned_segments(self, rotation_pptx: bytes) -> None:
        """A turned "Status [LIVE] since May" is three turned items, each where the browser has it.

        The inline-block chip leaves a gap in the line, as in unturned text
        (RC13), so the text on each side of it is a segment of its own:
        "Status", the chip's own text "LIVE" on its own box, then "since May".
        Each is turned 270 degrees and one line; each segment starts along the
        line where the browser draws its text, within 1 px, and the chip passes
        the turned-box check. Joined over the gap, "since May" would start about
        the chip's width early, over the chip.
        """
        document = _document("gap-chip")
        shapes = _shapes(rotation_pptx, "gap-chip")
        expected = {"before": "Status", "chip": "LIVE", "after": "since May"}
        items = {}
        for name, text in expected.items():
            _, items[name] = _text_item(shapes, text.split()[0], f"the {text!r} segment")
            _assert_angle(items[name], 270.0, f"the {text!r} segment")
            _assert_one_line(items[name], text, f"the {text!r} segment")
        _assert_starts_at(items["before"], _layout(document, "#before"), "'Status'")
        _assert_starts_at(items["after"], _layout(document, "#after"), "'since May'")
        _assert_turned_box(items["chip"], _layout(document, "#chip"), 270.0, "the chip's text")
        starts = [_box_start_along(items[name]) for name in expected]
        assert starts == sorted(starts), f"the segments are out of line order: {starts}"
        chips = [shape for shape in shapes if shape.fill == "DDDDDD"]
        assert (
            len(chips) == 1 and _angle_off(chips[0].rotation, 270.0) <= ANGLE_TOLERANCE_DEGREES
        ), f"expected the chip's turned background as one shape:\n{_describe(shapes)}"

    def test_text_after_a_hidden_word_starts_where_the_browser_has_it(
        self, rotation_pptx: bytes
    ) -> None:
        """A hidden word keeps its room in a turned line too (the Task 5 ruling).

        "Before [secret, visibility: hidden] after" turned 270 degrees: "secret"
        is on no shape, "Before" and "after" are separate turned items, and
        "after" starts along the line where the browser draws it, within 1 px.
        """
        document = _document("gap-hidden")
        shapes = _shapes(rotation_pptx, "gap-hidden")
        assert not [shape for shape in shapes if "secret" in shape.text], (
            f"the hidden word is on the slide:\n{_describe(shapes)}"
        )
        _, before = _text_item(shapes, "Before", "the text before the hidden word")
        _, after = _text_item(shapes, "after", "the text after the hidden word")

        assert before is not after, "the text either side of the hidden word must be two items"
        _assert_one_line(after, "after", "the text after the hidden word")
        _assert_angle(after, 270.0, "the text after the hidden word")
        _assert_starts_at(before, _layout(document, "#before"), "'Before'")
        _assert_starts_at(after, _layout(document, "#after"), "'after'")


@pytest.mark.slow
@requires_huashu_sidecar
class TestRotatedTable:
    def test_each_cell_of_a_rotated_table_is_its_own_turned_item(
        self, rotation_pptx: bytes
    ) -> None:
        """Minor 4: a ``rotate(-90deg)`` 2x2 table is positioned items, one turned item per cell.

        No a:tbl turns, so the table is no native table. Each cell's text is a
        turned item of its own, one line, on the cell's layout box, centred on
        its bounds within 1 px. Joined into the table's text, the four cells
        would stack as four lines of one item.
        """
        document = _document("rotated-table")
        cells = browser_each_layout_box(document, "#target td")
        assert len(cells) == len(TURNED_TABLE_CELLS), f"fixture drift: {len(cells)} cells"
        shapes = _shapes(rotation_pptx, "rotated-table")
        assert not table_frames(shapes), f"a turned table is no native table:\n{_describe(shapes)}"

        for text, cell in zip(TURNED_TABLE_CELLS, cells):
            _, item = _text_item(shapes, text, f"the cell {text!r}")
            _assert_one_line(item, text, f"the cell {text!r}")
            _assert_turned_box(item, cell, 270.0, f"the cell {text!r}")


@pytest.mark.slow
@requires_huashu_sidecar
class TestTurnedListMarkers:
    def test_a_rotated_lists_markers_are_items_of_their_own(self, rotation_pptx: bytes) -> None:
        """Minor 5: a turned list's markers are turned items of their own, as outside markers are.

        A ``rotate(-90deg)`` ``<ul>``: each "•" is a turned text item of its own,
        lying before its text along the line; the list's text reads "Alpha
        item" then "Beta item" with no marker in it, and starts along the line
        where the browser draws "Alpha item", within 1 px. Led by its marker,
        the text would start where the marker does.
        """
        document = _document("rotated-list")
        shapes = _shapes(rotation_pptx, "rotated-list")
        markers = [shape for shape in shapes if shape.kind == "text" and shape.text.strip() == "•"]
        assert len(markers) == 2, f"expected two marker items:\n{_describe(shapes)}"
        position, text = _text_item(shapes, "Alpha", "the list's text")
        assert [_normalised(line) for line in _lines(text)] == ["Alpha item", "Beta item"], (
            f"the list's text reads {_lines(text)}"
        )
        inset = _inset_px(rotation_pptx, "rotated-list", position, "lIns")

        _assert_starts_at(text, _layout(document, "#alpha"), "the list's text", inset)
        starts = _box_start_along(text) + inset
        for marker in markers:
            _assert_angle(marker, 270.0, "a marker")
            assert _box_start_along(marker) + marker.w <= starts + GEOMETRY_TOLERANCE_PX, (
                f"a marker's box ends {_box_start_along(marker) + marker.w:.2f} px along the "
                f"line, past where its text starts ({starts:.2f})"
            )


@pytest.mark.slow
@requires_huashu_sidecar
class TestTurnedLines:
    def test_a_trailing_br_in_a_block_child_adds_no_line(self, rotation_pptx: bytes) -> None:
        """Minor 6: "Line one<br>" then a block "Line two", turned, is two lines, no blank between.

        A <br> that ends its block breaks no further line: the browser shows two
        lines, so the item reads two.
        """
        _, item = _text_item(_shapes(rotation_pptx, "trailing-br"), "one", "the turned blocks")

        assert [_normalised(line) for line in _lines(item)] == ["Line one", "Line two"], (
            f"the turned blocks' lines are {_lines(item)}"
        )

    @pytest.mark.parametrize(
        ("name", "text", "text_align"),
        [("align-right", "Right aligned", "right"), ("align-center", "Centred label", "center")],
    )
    def test_an_aligned_turned_label_keeps_its_alignment_and_layout_box(
        self, rotation_pptx: bytes, name: str, text: str, text_align: str
    ) -> None:
        """Minor 7: right- and centre-aligned 240 px turned labels.

        Each item is written with the browser's computed text-align, its slack
        on that alignment's growth side (left for right-aligned text, half each
        side when centred), and its layout box where the browser has it
        (``_assert_turned_box``).
        """
        document = _document(name)
        layout = _layout(document, "#target")
        assert layout["text_align"] == text_align, (
            f"fixture drift: {name} computes text-align {layout['text_align']}"
        )
        _, item = _text_item(_shapes(rotation_pptx, name), text.split()[0], f"the {name} label")

        _assert_one_line(item, text, f"the {name} label")
        _assert_turned_box(item, layout, 270.0, f"the {name} label")

    def test_a_turned_paragraph_keeps_the_browsers_soft_wraps(self, rotation_pptx: bytes) -> None:
        """Minor 8: a 150 px paragraph turned 270 degrees wraps where the browser wraps it.

        The browser's lines are read from its unturned twin (a turn does not
        change where a line breaks): three of them. The turned item holds those
        three lines, on its layout box.
        """
        document = _document("soft-wrap")
        expected = [_normalised(line) for line in browser_lines(document, "#twin")]
        assert len(expected) == 3, f"fixture drift: the paragraph wraps to {expected}"
        shapes = _shapes(rotation_pptx, "soft-wrap")
        turned = [
            shape
            for shape in shapes
            if shape.kind == "text"
            and "Quarterly" in shape.text
            and _angle_off(shape.rotation, 270.0) <= ANGLE_TOLERANCE_DEGREES
        ]
        assert len(turned) == 1, f"expected one turned paragraph:\n{_describe(shapes)}"

        assert [_normalised(line) for line in _lines(turned[0])] == expected, (
            f"the turned paragraph's lines are {_lines(turned[0])}, the browser's {expected}"
        )
        _assert_turned_box(turned[0], _layout(document, "#target"), 270.0, "the turned paragraph")


@pytest.mark.slow
@requires_huashu_sidecar
class TestTurnedBlankLines:
    @pytest.mark.parametrize("name", ["leading-br", "double-br"])
    def test_a_blank_line_a_br_opens_keeps_its_place(self, rotation_pptx: bytes, name: str) -> None:
        """Round 2, item 1: only the empty line after a run's FINAL <br> paints nothing.

        * "leading-br": ``<div>Alpha</div><div><br>Beta</div>``: the second
          block's leading <br> opens an empty line, so Beta is a line further on;
        * "double-br": ``<div>Alpha<br><br></div><div>Beta</div>``: the second
          <br> opens an empty line, and the final one opens none.

        The unturned twin shows each: Beta starts two lines after Alpha. The
        turned item reads Alpha, a blank line, then Beta, on its layout box.
        """
        document = _document(name)
        alpha = browser_each_rect(document, "#w-a")[0]
        beta = browser_each_rect(document, "#w-b")[0]
        assert round((beta["y"] - alpha["y"]) / alpha["h"]) == 2, (
            f"fixture drift: the twin's Beta starts {beta['y'] - alpha['y']:.2f} px after Alpha "
            f"({alpha['h']:.2f} px lines), not two lines on"
        )
        shapes = _shapes(rotation_pptx, name)
        turned = [shape for shape in shapes if "Alpha" in shape.text and shape.rotation]
        assert len(turned) == 1, f"expected one turned item:\n{_describe(shapes)}"

        assert [_normalised(line) for line in _lines(turned[0])] == ["Alpha", "", "Beta"], (
            f"the turned item's lines are {_lines(turned[0])}: two lines apart, Alpha and Beta "
            "need the blank line between them"
        )
        _assert_turned_box(turned[0], _layout(document, "#t"), 270.0, f"the {name} item")

    def test_a_vertical_inline_padded_along_its_line_cuts_it(self, rotation_pptx: bytes) -> None:
        """Round 2, item 2: under vertical-rl an inline's inline sides are its top and bottom.

        "Status [mid, 24 px padding top and bottom] end" in a vertical-rl label:
        the padding takes room along the line, so the line is cut there, and
        "Status", "mid" and "end" are turned items of their own, each starting
        along the line where the browser draws it. Read from the physical left
        and right, the padding would cut nothing and "end" would start about
        47 px early.
        """
        document = _document("vertical-pad")
        shapes = _shapes(rotation_pptx, "vertical-pad")
        for text in ("Status", "mid", "end"):
            _, item = _text_item(shapes, text, f"the {text!r} segment")
            _assert_one_line(item, text, f"the {text!r} segment")
            _assert_angle(item, 90.0, f"the {text!r} segment")
            _assert_starts_at(item, _layout(document, f"#{text.lower()}"), f"{text!r}")


@pytest.mark.slow
@requires_huashu_sidecar
class TestTurnedPiecesMatchTheirTwins:
    @pytest.mark.parametrize("angle", list(TWIN_ANGLES))
    def test_a_mixed_size_segment_matches_its_twin(self, rotation_pptx: bytes, angle: str) -> None:
        """Round 2, items 3 and 4: a cut segment of 12 px and 28 px text, turned 12 and 40 degrees.

        Off a quarter turn, a line of runs of different sizes is no one
        rectangle as tall as its largest face. Each run is placed by its own
        face's height: so in its label's frame the segment "since May" starts
        along its line, starts across it and runs as long as its unturned
        twin's, within 1 px. Across, the twin also checks the first-line raise
        of a turned box, along its own up.
        """
        name = f"mixed-{angle}"
        shapes = _shapes(rotation_pptx, name)
        degrees = TWIN_ANGLE_DEGREES[angle]

        _assert_matches_twin(shapes, _document(name), degrees, MIXED_SEGMENT, "the mixed segment")
        _assert_matches_twin(shapes, _document(name), degrees, "Status", "the 'Status' segment")

    @pytest.mark.parametrize("angle", list(TWIN_ANGLES))
    def test_turned_list_markers_match_their_twins(self, rotation_pptx: bytes, angle: str) -> None:
        """Round 2, item 4: a 24 px ordered list's markers, turned 12 and 40 degrees.

        Each "1." and "2." is a turned item of its own that, in its list's frame,
        starts along and across its line and runs as long as its unturned
        twin's marker, within 1 px: placed at its box from the DevTools
        protocol and raised by the first-line offset along its own up.
        """
        name = f"ol-{angle}"
        shapes = _shapes(rotation_pptx, name)
        for marker in TWIN_LIST_MARKERS:
            _assert_matches_twin(
                shapes, _document(name), TWIN_ANGLE_DEGREES[angle], marker, f"the {marker} marker"
            )


@pytest.mark.slow
@requires_huashu_sidecar
class TestSuperscriptLines:
    def test_a_superscript_line_is_placed_from_its_baseline(self, rotation_pptx: bytes) -> None:
        """Round 2, item 5: "Revenue<sup>1</sup> grew" in 20 px, unturned.

        The raised "1" stands above the line, but the line is where its own
        20 px text is: the box's top is the calibrated first-line offset above
        "Revenue"'s glyph top (``single_line_box_top``), within 1 px. Placed by
        the superscript's top, the whole line would draw about 3.3 px high. The
        "1" keeps its baseline shift and is sized for the renderers' shrink.
        """
        document = _document("superscript")
        lead = _layout(document, "#lead")
        style = browser_style(document, "#target")
        family = style["fontFamily"].split(",")[0].strip().strip("\"'")
        ascent = browser_ascent(document, family, int(style["fontWeight"]), SUPERSCRIPT_SIZE_PX)
        expected = single_line_box_top(lead["y"], SUPERSCRIPT_SIZE_PX, ascent)
        _, item = _text_item(_shapes(rotation_pptx, "superscript"), "Revenue", "the paragraph")

        assert abs(item.y - expected) <= GEOMETRY_TOLERANCE_PX, (
            f"the paragraph's box top is {item.y:.2f}; placed from its own 20 px text it is "
            f"{expected:.2f} (off by {item.y - expected:.2f}, tolerance {GEOMETRY_TOLERANCE_PX} px)"
        )
        script = next(run for paragraph in item.paras for run in paragraph.runs if run.text == "1")
        sup_px = _px(browser_style(document, "#target sup")["fontSize"])
        _assert_script_run_size(item, script, "super", sup_px, SUPERSCRIPT_SIZE_PX)

    def test_a_turned_superscript_line_sits_where_its_twin_does(self, rotation_pptx: bytes) -> None:
        """Round 2, item 5, turned 270 degrees: the line is placed across by its own text.

        In its label's frame, the turned paragraph's text starts across its line
        (its box's top plus its top inset) where its unturned twin's box starts,
        within 1 px (the reviewer allowed half the superscript's 3.3 px
        overhang; the placement does better).
        """
        document = _document("superscript-turned")
        shapes = _shapes(rotation_pptx, "superscript-turned")
        turned = _items_reading(shapes, "Revenue1 grew", 270.0)
        twin = _items_reading(shapes, "Revenue1 grew", 0.0)
        assert len(turned) == 1 and len(twin) == 1, (
            f"expected a turned item and its twin:\n{_describe(shapes)}"
        )
        position, item = turned[0]
        _, across = _turned_local(_centre(_layout(document, "#t")), 270.0, _centre(item))
        top = across - item.h / 2 + _inset_px(rotation_pptx, "superscript-turned", position, "tIns")
        expected = twin[0][1].y - _centre(_layout(document, "#w"))[1]

        assert abs(top - expected) <= GEOMETRY_TOLERANCE_PX, (
            f"the turned paragraph's text starts {top:.2f} px across its frame, its twin's at "
            f"{expected:.2f} (off by {top - expected:.2f}, tolerance {GEOMETRY_TOLERANCE_PX} px)"
        )


def _written_script_size_pt(run: dict, sizing: dict | None) -> float:
    """``runOptions(run, {}, sizing).fontSize`` of emit_typography.cjs, in Node.

    ``sizing`` None calls it with two arguments, as every caller did before R11g.
    """
    arguments = json.dumps(run) + ", {}" + ("" if sizing is None else ", " + json.dumps(sizing))
    script = (
        f"const typography = require({json.dumps(str(TYPOGRAPHY_MODULE))});"
        f"process.stdout.write(JSON.stringify(typography.runOptions({arguments}).fontSize));"
    )
    return float(node_json(script))


def _script_run(item: Shape, text: str) -> Run:
    """The one run of ``item`` reading ``text``."""
    runs = [run for paragraph in item.paras for run in paragraph.runs if run.text == text]
    assert len(runs) == 1, f"expected one run reading {text!r}: {item.paras}"
    return runs[0]


def _shift_px(run: Run) -> float:
    """The baseline shift a run is written with, in px: its a:rPr baseline percent of its size."""
    return run.baseline_offset / BASELINE_UNITS * (run.size_pt or 0.0) / PT_PER_PX


def _assert_placed_from_its_text(item: Shape, document: str, what: str) -> None:
    """``item``, a one-line unturned box, is placed from #lead's 20 px glyph top, within 1 px."""
    lead = _layout(document, "#lead")
    style = browser_style(document, "#target")
    family = style["fontFamily"].split(",")[0].strip().strip("\"'")
    ascent = browser_ascent(document, family, int(style["fontWeight"]), SUPERSCRIPT_SIZE_PX)
    expected = single_line_box_top(lead["y"], SUPERSCRIPT_SIZE_PX, ascent)
    assert abs(item.y - expected) <= GEOMETRY_TOLERANCE_PX, (
        f"{what}: its box top is {item.y:.2f}; placed from its own 20 px text it is "
        f"{expected:.2f} (off by {item.y - expected:.2f}, tolerance {GEOMETRY_TOLERANCE_PX} px)"
    )


@pytest.mark.slow
@requires_huashu_sidecar
class TestScriptRunsPerRenderer:
    """R11g: a script run's written size, per the renderer the deck is written for.

    PowerPoint shrinks a superscript or subscript run to about 0.646 of its
    written size and places its line by its other runs, so the run is written
    at the browser's size over that factor (calibration A2), and PowerPoint
    draws it at the browser's size on the browser's baseline. Google Slides
    shrinks it alike but sizes the LINE by the written size, which pushes a
    line holding one down by about 0.28 em: so for Google (``target
    'gslides'``) the written size is capped at the line's largest size of the
    other runs, which keeps the baseline (option A, measured: within 1.5 px in
    both apps, but the script glyph 20% small, so only Google takes it).
    """

    @pytest.mark.parametrize("baseline", ["super", "sub"])
    def test_the_written_script_size_rule_per_target(self, baseline: str) -> None:
        """The pure rule (emit_typography.cjs runOptions), for a 16.67 px script in a 20 px line.

        * pptx, and no target at all: the browser's size over the factor;
        * gslides: capped at its line's cap (``capPx``): 20 px, 15 pt; a line
          the browser grew has a larger cap (24.5 px); a script run already
          under the cap (8 px) keeps the factor's size;
        * a run with no baseline shift is its size in every target.
        """
        _, factor = _script_factor(baseline)
        script = {
            "text": "1",
            "family": "DM Sans",
            "weight": 400,
            "italic": False,
            "sizePx": 50 / 3,
            "color": "1B3139",
            "letterSpacingPx": 0,
            "baseline": baseline,
        }
        calibrated = 50 / 3 * PT_PER_PX / factor
        cases = [
            (None, calibrated),
            ({"target": "pptx", "capPx": 20}, calibrated),
            ({"target": "gslides", "capPx": 20}, 20 * PT_PER_PX),
            ({"target": "gslides", "capPx": 24.5}, 24.5 * PT_PER_PX),
            ({"target": "gslides", "capPx": 20}, 8 * PT_PER_PX / factor, {"sizePx": 8}),
            ({"target": "gslides", "capPx": 20}, 20 * PT_PER_PX, {"sizePx": 20, "baseline": None}),
        ]
        for case in cases:
            sizing, expected = case[0], case[1]
            run = {**script, **(case[2] if len(case) > 2 else {})}
            written = _written_script_size_pt(run, sizing)
            assert abs(written - expected) <= 0.01, (
                f"a {run['sizePx']:.2f} px {run['baseline']} run under {sizing} is written at "
                f"{written:.3f} pt, expected {expected:.3f}"
            )

    def test_a_deck_for_google_slides_caps_its_script_runs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``build_pptx_huashu(target='gslides')``: a 20 px and a 40 px line's superscript.

        Each "1" stays a superscript and is written at its line's size (15 pt,
        30 pt); for PowerPoint (``target='pptx'``) at the browser's size over
        the factor, as before.
        """
        bodies = [SLIDES["superscript"], SLIDES["superscript"].replace("20px", "40px")]
        _, factor = _script_factor("super")
        for target in ("gslides", "pptx"):
            pptx, failures = export_slides(
                bodies, css=DECK_CSS + ROTATION_CSS, monkeypatch=monkeypatch, target=target
            )
            assert failures == [], failures
            for index, line_px in enumerate((20.0, 40.0)):
                document = slide_document(
                    bodies[index], css=DECK_CSS + ROTATION_CSS, slide_id=f"snapshot-{index + 1}"
                )
                script_px = _px(browser_style(document, "#target sup")["fontSize"])
                _, item = _text_item(
                    slide_shapes(pptx, index), "Revenue", f"the {line_px:g} px line"
                )
                run = _script_run(item, "1")
                expected = (
                    line_px * PT_PER_PX if target == "gslides" else script_px * PT_PER_PX / factor
                )
                assert run.baseline == "super" and abs((run.size_pt or 0.0) - expected) <= 0.01, (
                    f"{target}: the {line_px:g} px line's superscript is {_describe_run(run)}, "
                    f"expected a superscript at {expected:.2f} pt"
                )

    @pytest.mark.parametrize("name", list(LATER_SCRIPT_LINES))
    def test_a_later_lines_script_cap_is_its_lines_size_and_growth(
        self, monkeypatch: pytest.MonkeyPatch, name: str
    ) -> None:
        """R11g, lines after the first: Google grows a script line as the browser did.

        "Alpha revenue grew<br>Gamma ..." in 20 px, line-height 29 px, a script
        run on the second line. The browser's own superscript grows that line's
        box, so "Gamma" starts lower than the line height puts it (its growth);
        Preflight's sup (line-height 0) and a subscript grow nothing there.
        Written for Google, the script run is capped at the line's 20 px plus
        that growth over Google's growth per px (``GOOGLE_LINE_GROWTH_PER_PX``),
        and no larger than PowerPoint's size: so Google grows the line as the
        browser did. Capped at 20 px alone, the superscript's line would be
        drawn some 6 px high.
        """
        body = SLIDES[f"later-{name}"]
        css = DECK_CSS + ROTATION_CSS
        document = slide_document(body, css=css, slide_id="snapshot-1")
        first, second = _layout(document, "#first"), _layout(document, "#second")
        growth = second["y"] - first["y"] - LATER_LINE_HEIGHT_PX
        tag, script, baseline = ("sub", "2", "sub") if name == "sub" else ("sup", "1", "super")
        script_px = _px(browser_style(document, f"#target {tag}")["fontSize"])
        _, factor = _script_factor(baseline)
        per_px = emit_text_constant("GOOGLE_LINE_GROWTH_PER_PX")
        cap = SUPERSCRIPT_SIZE_PX + (growth if growth >= LINE_GROWTH_MIN_PX else 0.0) / per_px
        expected = min(script_px / factor, cap) * PT_PER_PX
        pptx, failures = export_slides([body], css=css, monkeypatch=monkeypatch, target="gslides")
        assert failures == [], failures
        _, item = _text_item(slide_shapes(pptx, 0), "Alpha", "the paragraph")
        run = _script_run(item, script)

        assert abs((run.size_pt or 0.0) - expected) <= SCRIPT_SIZE_TOLERANCE_PT, (
            f"{name}: the second line grew {growth:.2f} px in the browser, so its script run is "
            f"written at {expected:.2f} pt for Google; it is {_describe_run(run)}"
        )

    def test_the_pptx_target_writes_what_the_default_does(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``target='pptx'`` is the default, byte for byte; 'gslides' changes script sizes alone.

        For a deck with no script run and one with them, the export with no
        target and with ``target='pptx'`` are the same artifact (every part
        identical, ``docProps/core.xml`` canonicalised: ``structural_manifest``).
        Written for Google, the deck with no script run is the same artifact
        too, and the one with them differs only in its script runs' sizes.
        """
        css = DECK_CSS + ROTATION_CSS
        decks = {
            "no scripts": [SLIDES["tag"], SLIDES["br-lines"]],
            "scripts": [SLIDES["superscript"], SLIDES["preflight-sub"]],
        }
        for deck, bodies in decks.items():
            exports = {}
            for target in (None, "pptx", "gslides"):
                exports[target], failures = export_slides(
                    bodies, css=css, monkeypatch=monkeypatch, target=target
                )
                assert failures == [], failures
            assert structural_manifest(exports[None]) == structural_manifest(exports["pptx"]), (
                f"{deck}: target='pptx' does not export what the default does"
            )
            if deck == "no scripts":
                assert structural_manifest(exports["gslides"]) == structural_manifest(
                    exports["pptx"]
                ), "with no script run, the Google deck must equal the PowerPoint deck"
                continue
            for index in range(len(bodies)):
                pptx_shapes = slide_shapes(exports["pptx"], index)
                google_shapes = slide_shapes(exports["gslides"], index)
                assert _without_script_sizes(google_shapes) == _without_script_sizes(pptx_shapes), (
                    f"{deck}, slide {index}: the Google deck differs beyond its script runs' sizes"
                )
                assert google_shapes != pptx_shapes, (
                    f"{deck}, slide {index}: no script run was resized"
                )


def _without_script_sizes(shapes: list[Shape]) -> list[Shape]:
    """``shapes`` with every script run's size taken out, the one thing the targets differ in."""
    return [
        dataclasses.replace(
            shape,
            paras=[
                dataclasses.replace(
                    paragraph,
                    runs=[
                        dataclasses.replace(run, size_pt=None) if run.baseline else run
                        for run in paragraph.runs
                    ],
                )
                for paragraph in shape.paras
            ],
        )
        for shape in shapes
    ]


@pytest.mark.slow
@requires_huashu_sidecar
@requires_google_slides
class TestScriptRunsInGoogleSlides:
    def test_a_script_line_sits_on_the_browsers_baseline_in_google_slides(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R11g, opt-in (``TELLR_GOOGLE_TESTS=1``, run with ``uv run --with pymupdf``).

        Written for Google (``target='gslides'``) and converted through Drive,
        in Drive's PDF of the presentation each line's baseline is the
        browser's (its glyph top plus its ascent), within 1.5 px:
        * "Revenue" of a 20 px and a 40 px "Revenue<sup>1</sup> grew".
          Written at the browser's size over the factor, Google draws it 6 px
          low at 20 px and 12 px low at 40 px;
        * "Gamma", the second line of a paragraph holding a script run there:
          the browser's superscript, Preflight's, and a subscript. Capped at
          the line's size alone, the browser's superscript line is drawn 6 px
          high; written for PowerPoint, Preflight's 3.6 px and the subscript's
          6 px low.
        The presentation is deleted afterwards.
        """
        fitz = pytest.importorskip("fitz", reason="reads Drive's PDF: run with --with pymupdf")
        later = [f"later-{name}" for name in LATER_SCRIPT_LINES]
        bodies = [SLIDES["superscript"], SLIDES["superscript"].replace("20px", "40px")]
        bodies += [SLIDES[name] for name in later]
        # Each slide: the word whose baseline is read, its selector and its line's size.
        words = [("Revenue", "#lead", 20.0), ("Revenue", "#lead", 40.0)]
        words += [("Gamma", "#second", 20.0)] * len(later)
        css = DECK_CSS + ROTATION_CSS
        pptx, failures = export_slides(bodies, css=css, monkeypatch=monkeypatch, target="gslides")
        assert failures == [], failures
        conversion = google_slides_presentation(pptx, ["sup-20", "sup-40", *later])
        try:
            harness = fidelity_harness()
            pdf_bytes = harness._google_request(
                f"{DRIVE_FILES_URL}/{conversion.presentation_id}/export?mimeType=application/pdf",
                harness._google_token(),
            )
            pdf = fitz.open(stream=pdf_bytes, filetype="pdf")
            for index, (word, selector, line_px) in enumerate(words):
                document = slide_document(bodies[index], css=css, slide_id=f"snapshot-{index + 1}")
                style = browser_style(document, "#target")
                family = style["fontFamily"].split(",")[0].strip().strip("\"'")
                expected = _layout(document, selector)["y"] + browser_ascent(
                    document, family, int(style["fontWeight"]), line_px
                )
                page = pdf[index]
                scale = SLIDE_WIDTH_PX / page.rect.width
                origins = [
                    span["origin"][1] * scale
                    for block in page.get_text("rawdict")["blocks"]
                    for line in block.get("lines", [])
                    for span in line["spans"]
                    if "".join(char["c"] for char in span["chars"]).lstrip().startswith(word)
                ]
                assert len(origins) == 1, f"slide {index}'s PDF holds {len(origins)} {word!r}"
                assert abs(origins[0] - expected) <= GOOGLE_BASELINE_TOLERANCE_PX, (
                    f"slide {index}: Google draws {word!r}'s baseline at {origins[0]:.2f}, the "
                    f"browser at {expected:.2f} (off by {origins[0] - expected:+.2f}, tolerance "
                    f"{GOOGLE_BASELINE_TOLERANCE_PX} px)"
                )
        finally:
            delete_drive_file(conversion.presentation_id)
        assert not drive_file_exists(conversion.presentation_id), (
            "the presentation is still in Drive"
        )


@pytest.mark.slow
@requires_huashu_sidecar
class TestScriptLinesPlacedByBaseline:
    def test_an_ellipsis_line_with_a_superscript_is_placed_from_its_text(
        self, rotation_pptx: bytes
    ) -> None:
        """Round 3, item 2: "Revenue<sup>1</sup> grew in every region…", cut by its ellipsis.

        The "…" takes the line's own baseline extent, not the superscript's
        raised top, so the line is placed from its 20 px text within 1 px.
        """
        document = _document("ellipsis-superscript")
        _, item = _text_item(_shapes(rotation_pptx, "ellipsis-superscript"), "Revenue", "the line")
        assert item.text.endswith(ELLIPSIS), f"fixture drift: the line is not cut: {item.text!r}"

        _assert_placed_from_its_text(item, document, "the ellipsis line")

    @pytest.mark.parametrize("script", list(PREFLIGHT_LINES))
    def test_a_preflight_script_is_a_baseline_shift(
        self, rotation_pptx: bytes, script: str
    ) -> None:
        """Round 3, item 3: Tailwind Preflight's ``position: relative`` sub and sup.

        Preflight sets ``vertical-align: baseline`` and moves the script by
        ``top: -0.5em`` (sup) or ``bottom: -0.25em`` (sub). That is a baseline
        shift: the line is placed from its own 20 px text within 1 px, and the
        script run carries a superscript (or subscript) shift at its own 75%
        size, sized for the renderers' shrink.
        """
        name = f"preflight-{script}"
        document = _document(name)
        lead, text, baseline = PREFLIGHT_SCRIPTS[script]
        _, item = _text_item(_shapes(rotation_pptx, name), lead, name)

        _assert_placed_from_its_text(item, document, f"the Preflight {script} line")
        script_px = _px(browser_style(document, f"#target {script}")["fontSize"])
        _assert_script_run_size(
            item, _script_run(item, text), baseline, script_px, SUPERSCRIPT_SIZE_PX
        )

    def test_a_preflight_sup_shifts_as_its_vertical_align_twin(self, rotation_pptx: bytes) -> None:
        """Round 3, item 3: Preflight's sup and the browser's own ``vertical-align: super`` one.

        Both "1"s of "Revenue1 grew" in 20 px are written with the same
        baseline shift, within 1 px.
        """
        _, preflight = _text_item(_shapes(rotation_pptx, "preflight-sup"), "Revenue", "Preflight")
        _, twin = _text_item(_shapes(rotation_pptx, "superscript"), "Revenue", "the twin")
        shifts = (_shift_px(_script_run(preflight, "1")), _shift_px(_script_run(twin, "1")))

        assert shifts[0] > 0 and abs(shifts[0] - shifts[1]) <= GEOMETRY_TOLERANCE_PX, (
            f"the Preflight sup is shifted {shifts[0]:.2f} px, its vertical-align twin "
            f"{shifts[1]:.2f} px"
        )


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
