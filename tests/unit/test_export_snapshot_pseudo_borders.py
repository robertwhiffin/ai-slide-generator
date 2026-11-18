"""Snapshot engine: pseudo-elements, per-side borders and outline shadows.

What a deck paints with ``::before`` and ``::after`` (square bullets, accent
bars, milestone and journey dots, step numbers) is no element, so no DOM walk
can read it. The engine reads each pseudo-element whose ``content`` is not
``none`` or ``normal`` read-only, from Node through the DevTools protocol: its
box, its rendered text (Chrome's own evaluation of ``content``, counter values
included) and its computed style. It writes nothing into the page for them, so
no deck rule can match differently because of the export, and the export
draws each one like an element at its host's place in paint order (``::before``
as the host's first child, ``::after`` as its last):

* an empty-content pseudo-element is a native shape at its own box: a
  rounded-square bullet, a coral accent bar, a circle dot with its ring;
* a gradient one is a picture, captured in isolation like any gradient box;
* its text is the browser's own: string escapes, quotes, ``attr()``, and
  ``counter()``/``counters()`` in every counter style the slide uses, with
  resets, sets and increments on elements and on pseudo-elements, and nested
  scopes;
* it paints where the browser paints it: under the dots raised over it, over
  the rule it sits on.

The page the pseudo-elements are read from gains no node: the slide's own
script watches body for any node added or removed and would show it in the
deck. And a structural selector keeps matching the real elements it matched,
so the design system's ``:nth-child``-coloured milestone dots keep their
colours beside a ``::before`` track.

Boxes gain the rest of their CSS borders: a border that differs between sides
is one line per painted side, its centre inset by half the width, with
``dashed`` and ``dotted`` kept as the line's dash; a spread-only
``box-shadow: 0 0 0 Npx C`` is the shape's outline, N wide and outside the box,
or, when the box has a uniform border of its own, a second shape.

Every assertion reads the emitted slide XML (``slide_shapes``) and holds it
against the browser's own rendering of the very same document. A
pseudo-element's box, rendered text and computed style come from
``browser_each_pseudo``, which reads them from the browser's layout of the
untouched page through the DevTools protocol (no page API reports them).
Corpus slides are loaded by prefix; the milestone and journey dots are
``tests/fixtures/export_snapshot/pseudo_dots.html``, written in the design
system's slide-journey and slide-milestones patterns.

Slide script has already run in the page by the time anything is read: a
realm that lies about its nodes exports as its benign twin, and one that lies
about a computed style's length cannot stall the export.

Gating matches the sibling export suites: needs node, the extracted sidecar
``node_modules`` and a local Chrome/Chromium (skipped otherwise).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from io import BytesIO

import pytest
from lxml import etree
from PIL import Image

from src.services import pptx_from_html_huashu
from tests.fixtures.export_snapshot_support import (
    DECK_CSS,
    EMU_PER_PX,
    NAMESPACES,
    PERCENT_UNITS,
    SNAPSHOT_FIXTURE_DIR,
    Shape,
    browser_client_rects,
    browser_each_pseudo,
    browser_each_rect,
    browser_rect,
    browser_style,
    browser_text,
    corpus_document,
    export_corpus,
    export_slides,
    requires_huashu_sidecar,
    slide_document,
    slide_shape_elements,
    slide_shapes,
    text_shapes,
)
from tests.unit.test_export_collection_iteration_hostile_realm import (
    HOSTILE_EXPORT_TIMEOUT_SECONDS,
)
from tests.unit.test_export_slide_root_background import FIXTURE_DIR as SLIDE_ROOT_FIXTURE_DIR
from tests.unit.test_export_svg_raster import structural_manifest

# An emitted box matches the browser's within 0.5 px.
RECT_TOLERANCE_PX = 0.5
# A ring's outline grows its box by half the spread, which for a 2 px spread is
# 1 px: well over this tolerance, so an un-grown or fully-grown box fails.
OUTLINE_TOLERANCE_PX = 0.1
# Left-aligned text is placed at the browser's text left within this.
TEXT_LEFT_TOLERANCE_PX = 0.5
# A line is drawn along one axis: its other extent is zero, give or take EMU rounding.
LINE_THICKNESS_PX = 0.01
LINE_WIDTH_TOLERANCE_PT = 0.01
# roundRect adj is the radius over the short side, in 1/100000; within one point of it.
ADJ_TOLERANCE = 1000
ALPHA_TOLERANCE = 0.01
PT_PER_PX = 0.75
# Captures are taken at device scale 2: a picture's PNG is twice its box, give
# or take the one device pixel a fractional rect rounds to.
CAPTURE_SCALE = 2
PNG_SIZE_TOLERANCE_PX = 1
COLOUR_TOLERANCE = 6
# A gradient is sampled on its middle row, this far in from each end.
GRADIENT_END_INSET_PX = 3.0

# The corpus deck's colours (deck.css :root), each guarded against drift.
ACCENT = "FF5F46"  # --accent, the deck's coral
ACCENT_2 = "FF3621"  # --accent-2
RULE = "DCE0E2"  # --rule
DECK_RULES = {
    "accent": "--accent: #FF5F46;",
    "accent-2": "--accent-2: #FF3621;",
    "paper": "--paper: #F9F7F4;",
    "rule": "--rule: #DCE0E2;",
    "good": "--good: #00A972;",
    "bullet": ".dk-list li::before { content: ''; position: absolute; left: 0; top: 11px; "
    "width: 12px; height: 12px; border-radius: 3px; background: var(--accent); }",
    "accent-bar": ".dk-accent-bar::before { content: ''; position: absolute; left: 0; top: 4px; "
    "bottom: 4px; width: 5px; background: var(--accent); border-radius: 3px; }",
    "quote": ".dk-quote { font-size: 30px; font-weight: 500; line-height: 1.3; "
    "border-left: 6px solid var(--accent); padding: 6px 0 6px 28px; }",
}

# Fixture 09: four square-bulleted list items, an accent-barred paragraph and a
# blockquote with a 6 px coral left border.
BULLET_HOST = ".dk-list li"
BULLET_SIDE_PX = 12.0
BULLET_RADIUS_PX = 3.0
BULLET_ITEM_TEXTS = ("Pricing discipline", "Mix shift", "Operating leverage", "Interest expense")
ACCENT_BAR_HOST = ".dk-accent-bar"
ACCENT_BAR_WIDTH_PX = 5.0
# top: 4px and bottom: 4px: the bar is its host's full height less 8 px.
ACCENT_BAR_INSET_PX = 8.0
QUOTE = "blockquote.dk-quote"
QUOTE_BORDER_PX = 6.0

# The design-system milestone and journey dots.
PSEUDO_DOTS_BODY = (SNAPSHOT_FIXTURE_DIR / "pseudo_dots.html").read_text(encoding="utf-8")
MILESTONES = ".pd-milestones"
MILESTONE_NODE = ".pd-node"
JOURNEY = ".pd-journey"
JOURNEY_ROW = ".pd-row"
# Each milestone's dot colour, by its position among the row's children.
MILESTONE_DOT_FILLS = (ACCENT, ACCENT_2, "1B5162", "00A972")
# The third milestone is the current one: a halo instead of a ring of its own.
CURRENT_MILESTONE = 2
JOURNEY_BORDER_PX = 2.0
JOURNEY_DOT_SIDE_PX = 12.0

# Step numbers drawn by a decimal-leading-zero counter, laid out as the design
# system lays out numbered steps (the number a flex item beside its label).
COUNTER_CSS = (
    ".steps { counter-reset: s }\n"
    ".step::before { counter-increment: s; content: counter(s, decimal-leading-zero) }\n"
    ".steps { display: flex; flex-direction: column; gap: 16px; margin-top: 24px; }\n"
    ".step { display: flex; gap: 16px; align-items: baseline; font-size: 24px; }\n"
    ".step::before { color: #FF5F46; font-weight: 700; }\n"
)
COUNTER_BODY = (
    '<div class="slide"><p class="dk-eyebrow">How we work</p><div class="steps">'
    '<div class="step"><span>Discover</span></div>'
    '<div class="step"><span>Design</span></div>'
    '<div class="step"><span>Deliver</span></div>'
    "</div></div>"
)
COUNTER_TEXTS = ("01", "02", "03")
COUNTER_LABELS = ("Discover", "Design", "Deliver")
COUNTER_SIZE_PT = 24 * PT_PER_PX

# Every form of generated text the engine exports, one
# pseudo-element per case, each absolutely positioned so it is a text block of
# its own beside its host's label. The browser renders each; the literal
# beside each case is what Chrome renders, a guard against fixture drift.
CONTENT_FORMS_CSS = r"""
.cf-grid { display: grid; grid-template-columns: repeat(3, 1fr); column-gap: 32px;
  margin-top: 12px; }
.cf { position: relative; padding-left: 72px; min-height: 26px; font-size: 16px;
  line-height: 26px; }
.cf::before { position: absolute; left: 0; top: 0; color: #FF5F46; font-weight: 700; }
.cf-styles { counter-reset: f; }
.cf-styles > .cf { counter-increment: f; }
#cf-decimal::before { content: counter(f) "."; }
#cf-leading-zero::before { content: counter(f, decimal-leading-zero); }
#cf-lower-alpha::before { content: counter(f, lower-alpha) ")"; }
#cf-upper-alpha::before { content: counter(f, upper-alpha); }
#cf-lower-roman::before { content: counter(f, lower-roman); }
#cf-upper-roman::before { content: counter(f, upper-roman); }
#cf-disc::before { content: counter(f, disc); }
#cf-circle::before { content: counter(f, circle); }
#cf-square::before { content: counter(f, square); }
.cf-steps { counter-reset: g 10; }
.cf-steps > .cf::before { counter-increment: g 5; content: counter(g); }
#cf-set { counter-set: g 100; }
#cf-set-pseudo::before { counter-increment: none; counter-set: g 7; }
.cf-tree { counter-reset: t; }
.cf-tree > .cf { counter-increment: t; }
.cf-tree > .cf::before { content: counters(t, ".") " "; }
.cf-doc { counter-reset: major; }
.cf-major { counter-increment: major; counter-reset: minor; }
.cf-major::before { content: counter(major, upper-roman); }
.cf-minor { counter-increment: minor; }
.cf-minor::before { content: counter(major) "." counter(minor); }
#cf-escape::before { content: "\2192\20 next"; }
#cf-attr::before { content: attr(data-owner) ":"; }
.cf-quote { font-size: 20px; margin: 16px 0 0; }
.cf-quote::before { content: open-quote; }
.cf-quote::after { content: close-quote; }
"""
CONTENT_FORMS_BODY = (
    '<div class="slide"><p class="dk-eyebrow">Generated content</p><div class="cf-grid">'
    '<div class="cf-styles">'
    '<div class="cf" id="cf-decimal">decimal</div>'
    '<div class="cf" id="cf-leading-zero">decimal-leading-zero</div>'
    '<div class="cf" id="cf-lower-alpha">lower-alpha</div>'
    '<div class="cf" id="cf-upper-alpha">upper-alpha</div>'
    '<div class="cf" id="cf-lower-roman">lower-roman</div>'
    '<div class="cf" id="cf-upper-roman">upper-roman</div>'
    '<div class="cf" id="cf-disc">disc</div>'
    '<div class="cf" id="cf-circle">circle</div>'
    '<div class="cf" id="cf-square">square</div>'
    "</div><div>"
    '<div class="cf-steps">'
    '<div class="cf" id="cf-step-1">reset 10, then +5</div>'
    '<div class="cf" id="cf-step-2">+5</div>'
    '<div class="cf" id="cf-set">set 100, then +5</div>'
    '<div class="cf" id="cf-set-pseudo">set 7 on the pseudo-element</div>'
    '<div class="cf" id="cf-after-set">+5</div>'
    "</div>"
    '<div class="cf-tree">'
    '<div class="cf" id="cf-t1">Plan<div class="cf-tree">'
    '<div class="cf" id="cf-t11">Scope</div>'
    '<div class="cf" id="cf-t12">Budget</div>'
    "</div></div>"
    '<div class="cf" id="cf-t2">Build</div>'
    "</div></div><div>"
    '<div class="cf-doc">'
    '<div class="cf cf-major" id="cf-major-1">Results</div>'
    '<div class="cf cf-minor" id="cf-minor-11">Revenue</div>'
    '<div class="cf cf-minor" id="cf-minor-12">Margin</div>'
    '<div class="cf cf-major" id="cf-major-2">Outlook</div>'
    '<div class="cf cf-minor" id="cf-minor-21">Guidance</div>'
    "</div>"
    '<div class="cf" id="cf-escape">escaped string</div>'
    '<div class="cf" id="cf-attr" data-owner="Finance">attr()</div>'
    '<p class="cf-quote" id="cf-quote">Quoted words</p>'
    "</div></div></div>"
)
# The ids of the `.cf` hosts, in document order (the quoted paragraph is no `.cf`).
CONTENT_FORM_HOSTS = tuple(re.findall(r'class="cf(?: [^"]*)?" id="([^"]+)"', CONTENT_FORMS_BODY))
CONTENT_FORMS = {
    # Every counter style, on the counter's consecutive values, incremented on the element.
    "cf-decimal": "1.",
    "cf-leading-zero": "02",
    "cf-lower-alpha": "c)",
    "cf-upper-alpha": "D",
    "cf-lower-roman": "v",
    "cf-upper-roman": "VI",
    "cf-disc": "\u2022",
    "cf-circle": "\u25e6",
    "cf-square": "\u25a0",
    # counter-reset with a start, incremented on the pseudo-element by a step;
    # counter-set on an element, and on a pseudo-element, seen by what follows.
    "cf-step-1": "15",
    "cf-step-2": "20",
    "cf-set": "105",
    "cf-set-pseudo": "7",
    "cf-after-set": "12",
    # counters() through a nested counter-reset, and the outer scope after it.
    "cf-t1": "1",
    "cf-t11": "1.1",
    "cf-t12": "1.2",
    "cf-t2": "2",
    # A counter-reset's scope runs on through its element's following siblings.
    "cf-major-1": "I",
    "cf-minor-11": "1.1",
    "cf-minor-12": "1.2",
    "cf-major-2": "II",
    "cf-minor-21": "2.1",
    # String literals with CSS escapes, and attr().
    "cf-escape": "\u2192 next",
    "cf-attr": "Finance:",
}
INLINE_QUOTE_HOST = "#cf-quote"
INLINE_QUOTE_TEXT = "\u201cQuoted words\u201d"

# Pseudo-elements are read, never written: nothing is inserted into the page
# for them. The slide's own script watches body's subtree for any node added
# or removed once the page has loaded (the export's own probes and Playwright's
# screenshot styles go on documentElement and head, outside it). On the first
# change it recolours a native probe (read by the snapshot) and a gradient
# probe (a capture, taken after the snapshot) to #00FF00, and writes what
# changed into the native probe's text, so the exported deck shows whether
# anything was inserted, before the snapshot or before a capture.
NO_INSERTION_CSS = (
    ".ni-list { list-style: none; padding: 0; margin: 24px 0 0; font-size: 20px; }\n"
    ".ni-list li { position: relative; padding-left: 28px; margin-bottom: 12px; }\n"
    '.ni-list li::before { content: ""; position: absolute; left: 0; top: 8px; width: 12px; '
    "height: 12px; background: #FF5F46; }\n"
    ".ni-probe { width: 320px; height: 40px; margin-top: 24px; background: #5A6F77; "
    "color: #FFFFFF; font-size: 16px; }\n"
    ".ni-gradient-probe { width: 320px; height: 40px; margin-top: 16px; "
    "background: linear-gradient(90deg, #5A6F77, #1B5162); }\n"
)
NO_INSERTION_PROBE_TEXT = "body unchanged"
NO_INSERTION_WATCH_SCRIPT = (
    "<script>(function () {"
    "var nativeProbe = document.getElementById('ni-probe');"
    "var capturedProbe = document.getElementById('ni-gradient-probe');"
    "var report = nativeProbe.firstChild;"
    "var added = 0, removed = 0, first = '';"
    "function describe(node) {"
    "if (node.nodeType !== 1) return '#' + node.nodeName.toLowerCase();"
    "var name = node.tagName.toLowerCase();"
    "for (var index = 0; index < node.attributes.length; index++) {"
    "var attribute = node.attributes[index];"
    "if (attribute.name.indexOf('data-') === 0) {"
    "name += '[' + attribute.name + '=' + attribute.value + ']';"
    "}"
    "}"
    "return name;"
    "}"
    "function watch() {"
    "new MutationObserver(function (records) {"
    "for (var index = 0; index < records.length; index++) {"
    "added += records[index].addedNodes.length;"
    "removed += records[index].removedNodes.length;"
    "if (!first && records[index].addedNodes.length) {"
    "first = describe(records[index].addedNodes[0]);"
    "}"
    "}"
    "if (!added && !removed) return;"
    "nativeProbe.style.background = '#00FF00';"
    "capturedProbe.style.background = 'linear-gradient(90deg, #00FF00, #00FF00)';"
    "report.data = 'body changed: ' + added + ' added, ' + removed + ' removed, first ' + first;"
    "}).observe(document.body, { childList: true, subtree: true });"
    "}"
    "if (document.readyState === 'complete') watch(); else window.addEventListener('load', watch);"
    "})();</script>"
)
NO_INSERTION_CONTENT = (
    '<p class="dk-eyebrow">Read, never written</p>'
    '<ul class="ni-list"><li>Pricing held</li><li>Mix improved</li></ul>'
    f'<div id="ni-probe" class="ni-probe">{NO_INSERTION_PROBE_TEXT}</div>'
    '<div id="ni-gradient-probe" class="ni-gradient-probe"></div>'
    f"{NO_INSERTION_WATCH_SCRIPT}"
)
NO_INSERTION_BODY = f'<div class="slide">{NO_INSERTION_CONTENT}</div>'
# The same slide with one node inserted under body after the watch starts: it
# proves the watch bites, so a clean probe is evidence and not a dead observer.
NO_INSERTION_BITE_SCRIPT = (
    "<script>window.addEventListener('load', function () { setTimeout(function () {"
    "document.querySelector('.slide').appendChild(document.createElement('span'));"
    "}, 0); });</script>"
)
NO_INSERTION_BITTEN_BODY = (
    f'<div class="slide">{NO_INSERTION_CONTENT}{NO_INSERTION_BITE_SCRIPT}</div>'
)
NO_INSERTION_PROBE_FILL = "5A6F77"
INSERTION_SIGNAL = "00FF00"
NO_INSERTION_BULLETS = 2

# The design system's slide-milestones pattern: the track is the row's
# ::before and the dots are real elements coloured by their milestone's
# position among the row's children (`.node:nth-child(2) .dot`). Anything
# inserted first in the row for the track would shift every milestone's
# position by one.
STRUCTURAL_CSS = (
    ".ds-milestones { position: relative; display: grid; grid-template-columns: repeat(4, 1fr); "
    "margin-top: 40px; }\n"
    '.ds-milestones::before { content: ""; position: absolute; left: 0; right: 0; top: 13px; '
    "height: 2px; background: var(--rule); }\n"
    ".ds-node { display: flex; flex-direction: column; align-items: flex-start; gap: 14px; "
    "padding-right: 28px; position: relative; }\n"
    ".ds-dot { width: 28px; height: 28px; border-radius: 50%; background: var(--accent); "
    "z-index: 1; }\n"
    ".ds-node:nth-child(2) .ds-dot { background: var(--accent-2); }\n"
    ".ds-node:nth-child(3) .ds-dot { background: #1B5162; }\n"
    ".ds-node:nth-child(4) .ds-dot { background: var(--good); }\n"
    ".ds-date { font-family: var(--mono); font-size: 14px; color: var(--accent-2); }\n"
)
STRUCTURAL_BODY = (
    '<div class="slide"><p class="dk-eyebrow">Milestones</p><div class="ds-milestones">'
    + "".join(
        f'<div class="ds-node"><div class="ds-dot"></div><div class="ds-date">{quarter}</div></div>'
        for quarter in ("Q1 2025", "Q2 2025", "Q3 2025", "Q4 2025")
    )
    + "</div></div>"
)
STRUCTURAL_DOT = ".ds-dot"

# Boxes with borders on some sides, and rings drawn with a spread-only shadow.
BORDERS_BODY = (
    '<div class="slide">'
    '<div id="dashed" style="position: absolute; left: 88px; top: 80px; width: 400px; '
    'height: 48px; border-bottom: 2px dashed #1B5162;"></div>'
    '<div id="dotted" style="position: absolute; left: 88px; top: 180px; width: 400px; '
    'height: 48px; border-top: 3px dotted #00A972;"></div>'
    '<div id="solid" style="position: absolute; left: 88px; top: 280px; width: 400px; '
    'height: 48px; border-right: 4px solid #5A6F77;"></div>'
    '<div id="sided" style="position: absolute; left: 600px; top: 80px; width: 300px; '
    "height: 120px; background: #CDEDE1; border-style: solid dashed dashed dotted; "
    'border-width: 2px 4px 6px 8px; border-color: #D0302A transparent #7B2FBE #2F5BEA;"></div>'
    '<div id="ringed" style="position: absolute; left: 600px; top: 300px; width: 240px; '
    'height: 96px; background: #FFFFFF; box-shadow: 0 0 0 2px #1B3139;"></div>'
    '<div id="ringed-round" style="position: absolute; left: 900px; top: 300px; width: 240px; '
    "height: 96px; border-radius: 12px; background: #F8D3D0; "
    'box-shadow: 0 0 0 6px rgba(255, 54, 33, 0.18);"></div>'
    '<div id="ringed-dot" style="position: absolute; left: 600px; top: 460px; width: 28px; '
    "height: 28px; border-radius: 50%; background: #FF5F46; border: 5px solid #F9F7F4; "
    'box-shadow: 0 0 0 1px #DCE0E2;"></div>'
    "</div>"
)
SIDED_FILL = "CDEDE1"
# The design system's milestone dot: a uniform border and, outside it, a 1 px
# spread-only ring. One shape has one outline, so the ring is a second shape.
RINGED_DOT = "ringed-dot"
RINGED_DOT_FILL = "FF5F46"
RINGED_DOT_BORDER = ("F9F7F4", 5.0)
RINGED_DOT_RING = ("DCE0E2", 1.0)


@dataclass(frozen=True)
class SideLine:
    """One painted border side, as the browser paints it."""

    side: str  # 'top' | 'right' | 'bottom' | 'left'
    colour: str
    width_px: float
    dash: str  # the emitted prstDash


# The single-side boxes: the side painted, its colour, width and emitted dash.
SINGLE_SIDES = {
    "dashed": SideLine("bottom", "1B5162", 2.0, "dash"),
    "dotted": SideLine("top", "00A972", 3.0, "sysDot"),
    "solid": SideLine("right", "5A6F77", 4.0, "solid"),
}
# The four-sided box: its right side is transparent, so it paints three lines.
SIDED_LINES = (
    SideLine("top", "D0302A", 2.0, "solid"),
    SideLine("bottom", "7B2FBE", 6.0, "dash"),
    SideLine("left", "2F5BEA", 8.0, "sysDot"),
)
SIDED_WIDTHS = {"top": 2.0, "right": 4.0, "bottom": 6.0, "left": 8.0}

# A CSS triangle, as an arrowhead is drawn: a box with no content whose one
# painted side, a 70 px coral left border, lies between transparent 40 px top
# and bottom sides, so that side has no inner edge for a line to run along.
TRIANGLE_BODY = (
    '<div class="slide"><div id="arrowhead" style="position: absolute; left: 200px; top: 200px; '
    "width: 0; height: 0; border-left: 70px solid #FF5F46; border-top: 40px solid transparent; "
    'border-bottom: 40px solid transparent;"></div></div>'
)
TRIANGLE_SIZE = (70.0, 80.0)
# An inline box whose border differs by side, wrapping over lines.
SLICED_BODY = (
    '<div class="slide"><p style="width: 280px; font-size: 20px; line-height: 34px; '
    'margin: 40px 0 0;">Lead <span id="sliced" style="border-left: 4px solid #7B2FBE; '
    'border-right: 4px solid #2F5BEA; border-bottom: 2px solid #00A972;">an accented phrase '
    "long enough to run onto a second line</span> and its tail.</p></div>"
)
SLICED_LEFT = SideLine("left", "7B2FBE", 4.0, "solid")
SLICED_RIGHT = SideLine("right", "2F5BEA", 4.0, "solid")
SLICED_BOTTOM = SideLine("bottom", "00A972", 2.0, "solid")
# Two spread-only rings around one box: the first listed paints on top.
STACKED_BODY = (
    '<div class="slide"><div id="stacked" style="position: absolute; left: 200px; top: 200px; '
    "width: 160px; height: 60px; background: #CDEDE1; "
    'box-shadow: 0 0 0 2px #FFFFFF, 0 0 0 5px #1B5162;"></div></div>'
)
STACKED_FILL = "CDEDE1"
STACKED_RINGS = (("FFFFFF", 2.0), ("1B5162", 5.0))


@dataclass(frozen=True)
class Ring:
    """A box ringed by ``box-shadow: 0 0 0 <spread> <colour>``."""

    fill: str
    colour: str
    alpha: float | None  # None for an opaque ring
    spread_px: float
    radius_px: float


RINGS = {
    "ringed": Ring("FFFFFF", "1B3139", None, 2.0, 0.0),
    "ringed-round": Ring("F8D3D0", "FF3621", 0.18, 6.0, 12.0),
}

# Pseudo-elements added to the hostile-realm fixtures: text before the heading
# and an empty swatch after the prose, in the deck's coral.
HOSTILE_PSEUDO_RULES = (
    '.slide h1::before { content: "\\2014\\20"; color: #FF5F46; }\n'
    '.prose::after { content: ""; display: inline-block; width: 24px; height: 24px; '
    "margin-left: 12px; vertical-align: middle; background: #FF5F46; }\n"
)
HOSTILE_HEADING_TEXT = "Acme Collection Passes"
# What the heading's ::before puts on screen before it.
HOSTILE_BEFORE_TEXT = "\u2014"
HOSTILE_TEXT_NODES = "hostile_text_nodes"
BENIGN_TWIN = "collection_passes"
HOSTILE_SWATCH_SIDE_PX = 24.0
# Slide script that makes every CSSStyleDeclaration claim a billion
# properties. A read that trusts the length to walk a computed style never
# ends; one that reads named properties, or a bounded one, ends with the
# real values all the same. It
# publishes on document.title whether the replacement took.
LYING_STYLE_LENGTH_SCRIPT = (
    "<script>\n"
    "  var report = { configurable: false, bites: false, redefineResult: 'ok' };\n"
    "  var descriptor = Object.getOwnPropertyDescriptor(CSSStyleDeclaration.prototype, 'length');\n"
    "  report.configurable = !!(descriptor && descriptor.configurable);\n"
    "  try {\n"
    "    Object.defineProperty(CSSStyleDeclaration.prototype, 'length', "
    "{ configurable: true, get: function () { return 1e9; } });\n"
    "  } catch (error) {\n"
    "    report.redefineResult = 'refused: ' + error.message;\n"
    "  }\n"
    "  report.bites = getComputedStyle(document.documentElement).length === 1e9;\n"
    "  document.title = JSON.stringify(report);\n"
    "</script>\n"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_deck_rule(*names: str) -> None:
    for name in names:
        assert DECK_RULES[name] in DECK_CSS, (
            f"fixture drift: deck.css no longer holds {DECK_RULES[name]!r}, "
            "which this test's expectation comes from"
        )


def _export(body: str, monkeypatch: pytest.MonkeyPatch, *, css: str = DECK_CSS) -> bytes:
    pptx, failures = export_slides([body], css=css, engine="snapshot", monkeypatch=monkeypatch)
    assert failures == [], f"the export rejected the slide: {failures}"
    assert pptx, "the export produced no .pptx bytes"
    return pptx


def _document(body: str, *, css: str = DECK_CSS) -> str:
    """The document ``_export`` exported (``export_slides`` names slide 1 ``snapshot-1``)."""
    return slide_document(body, css=css, slide_id="snapshot-1")


def _hex(colour: str) -> tuple[str, float]:
    """('RRGGBB', alpha) of a computed ``rgb(…)`` / ``rgba(…)`` colour."""
    match = re.fullmatch(r"rgba?\(([^)]*)\)", colour.strip())
    assert match, f"not a computed rgb() colour: {colour!r}"
    channels = [part.strip() for part in match.group(1).replace("/", ",").split(",")]
    red, green, blue = (int(round(float(channel))) for channel in channels[:3])
    alpha = float(channels[3]) if len(channels) > 3 else 1.0
    return f"{red:02X}{green:02X}{blue:02X}", alpha


def _px(length: str) -> float:
    assert length.endswith("px"), f"not a computed px length: {length!r}"
    return float(length[:-2])


def _ring(box_shadow: str) -> tuple[str, float] | None:
    """(computed colour, spread px) of a single spread-only shadow layer, else None."""
    if box_shadow == "none":
        return None
    match = re.fullmatch(r"(rgba?\([^)]*\))\s+0px\s+0px\s+0px\s+([\d.]+)px", box_shadow.strip())
    assert match, f"not a single spread-only shadow: {box_shadow!r}"
    return match.group(1), float(match.group(2))


def _grown(rect: dict, by: float) -> dict:
    """``rect`` moved out by ``by`` px on every side (in, for a negative ``by``)."""
    return {
        "x": rect["x"] - by,
        "y": rect["y"] - by,
        "w": rect["w"] + 2 * by,
        "h": rect["h"] + 2 * by,
    }


def _centre(rect: dict) -> tuple[float, float]:
    return rect["x"] + rect["w"] / 2, rect["y"] + rect["h"] / 2


def _describe(shapes: list[Shape]) -> str:
    return "\n".join(
        f"  [{position}] {shape.kind} {shape.geometry} fill={shape.fill} "
        f"line={shape.line}/{shape.line_w_pt}/{shape.line_dash} "
        f"box=({shape.x:.2f}, {shape.y:.2f}, {shape.w:.2f}, {shape.h:.2f}) text={shape.text[:30]!r}"
        for position, shape in enumerate(shapes)
    )


def _rect(box: dict | None) -> dict | None:
    """The ``{"x", "y", "w", "h"}`` of a box, without a pseudo-element's text and style."""
    if box is None:
        return None
    return {key: box[key] for key in ("x", "y", "w", "h") if key in box}


def _off(shape: Shape, expected: dict) -> dict:
    emitted = {"x": shape.x, "y": shape.y, "w": shape.w, "h": shape.h}
    return {key: round(emitted[key] - value, 3) for key, value in _rect(expected).items()}


def _assert_box(shape: Shape, expected: dict, tolerance: float, what: str) -> None:
    off = _off(shape, expected)
    assert all(abs(delta) <= tolerance for delta in off.values()), (
        f"{what}: emitted box ({shape.x:.3f}, {shape.y:.3f}, {shape.w:.3f}, {shape.h:.3f}) "
        f"differs from the expected {_rect(expected)} by {off} (tolerance {tolerance} px)"
    )


def _at(shapes: list[Shape], rect: dict, tolerance: float = RECT_TOLERANCE_PX) -> list[int]:
    """spTree indices of the shapes whose box is ``rect`` within ``tolerance``."""
    return [
        position
        for position, shape in enumerate(shapes)
        if all(abs(delta) <= tolerance for delta in _off(shape, rect).values())
    ]


def _centred_on(shapes: list[Shape], rect: dict, **match: object) -> list[int]:
    """spTree indices of the shapes matching ``match`` whose centre is ``rect``'s within 1 px."""
    centre_x, centre_y = _centre(rect)
    found = []
    for position, shape in enumerate(shapes):
        if any(getattr(shape, key) != value for key, value in match.items()):
            continue
        if (
            abs(shape.x + shape.w / 2 - centre_x) <= 1
            and abs(shape.y + shape.h / 2 - centre_y) <= 1
        ):
            found.append(position)
    return found


def _lines(shapes: list[Shape], colour: str) -> list[tuple[int, Shape]]:
    return [
        (position, shape)
        for position, shape in enumerate(shapes)
        if shape.kind == "line" and shape.line == colour
    ]


def _outline_alpha(element: etree._Element) -> float | None:
    """The <a:alpha> of a shape's outline colour; None when the outline is opaque."""
    alpha = element.find("p:spPr/a:ln/a:solidFill/a:srgbClr/a:alpha", NAMESPACES)
    return None if alpha is None else int(alpha.get("val")) / PERCENT_UNITS


def _picture_at(shapes: list[Shape], rect: dict, what: str) -> tuple[int, Shape]:
    found = [position for position in _at(shapes, rect) if shapes[position].kind == "picture"]
    assert len(found) == 1, (
        f"expected exactly one picture at the browser rect of {what} {rect}, got {len(found)}:\n"
        f"{_describe(shapes)}"
    )
    return found[0], shapes[found[0]]


def _image(picture: Shape, what: str) -> Image.Image:
    assert picture.image, f"{what}: the picture embeds no image data"
    return Image.open(BytesIO(picture.image)).convert("RGBA")


def _pixel(image: Image.Image, picture: Shape, x: float, y: float) -> tuple[int, int, int, int]:
    """The PNG pixel under the slide point (x, y), through the picture's emitted rect."""
    column = int((x - picture.x) / picture.w * image.width)
    row = int((y - picture.y) / picture.h * image.height)
    column = min(max(column, 0), image.width - 1)
    row = min(max(row, 0), image.height - 1)
    return image.getpixel((column, row))


def _is(pixel: tuple[int, int, int, int], colour: str) -> bool:
    expected = (int(colour[0:2], 16), int(colour[2:4], 16), int(colour[4:6], 16))
    return pixel[3] >= 250 and all(
        abs(channel - want) <= COLOUR_TOLERANCE for channel, want in zip(pixel[:3], expected)
    )


def _normalised(text: str) -> str:
    return " ".join(text.split())


def _text_items_at(shapes: list[Shape], box: dict) -> list[Shape]:
    """Text items placed at a text block's box: left edge on its left, centre inside it."""
    return [
        shape
        for shape in shapes
        if shape.kind == "text"
        and abs(shape.x - box["x"]) <= TEXT_LEFT_TOLERANCE_PX
        and box["y"] <= shape.y + shape.h / 2 <= box["y"] + box["h"]
    ]


def _shape_signature(shape: Shape) -> tuple:
    return (
        shape.kind,
        shape.geometry,
        shape.fill,
        shape.fill_alpha,
        shape.line,
        shape.line_w_pt,
        shape.line_dash,
        shape.text,
    )


# ---------------------------------------------------------------------------
# Exports and browser geometry, read once per module
# ---------------------------------------------------------------------------


@dataclass
class Exported:
    """One exported slide, its spTree, and the browser geometry its tests compare against."""

    shapes: list[Shape]
    elements: list[etree._Element]
    geometry: dict


@pytest.fixture(scope="module")
def fixture_09() -> Iterator[Exported]:
    """Corpus slide 09 exported once, with its pseudo-elements and quote as the browser has them."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        pptx, failures = export_corpus(["09"], monkeypatch=monkeypatch)
    assert failures == [], f"the export rejected corpus slide 09: {failures}"
    document = corpus_document("09")
    yield Exported(
        shapes=slide_shapes(pptx),
        elements=slide_shape_elements(pptx),
        geometry={
            "bullets": browser_each_pseudo(document, BULLET_HOST),
            "bar": browser_each_pseudo(document, ACCENT_BAR_HOST)[0],
            "bar_host": browser_rect(document, ACCENT_BAR_HOST),
            "quote": browser_rect(document, QUOTE),
        },
    )


@pytest.fixture(scope="module")
def pseudo_dots() -> Iterator[Exported]:
    """The milestone and journey dots slide exported once, with its browser pseudo-element boxes."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        pptx = _export(PSEUDO_DOTS_BODY, monkeypatch)
    document = _document(PSEUDO_DOTS_BODY)
    yield Exported(
        shapes=slide_shapes(pptx),
        elements=slide_shape_elements(pptx),
        geometry={
            "track": browser_each_pseudo(document, MILESTONES)[0],
            "progress": browser_each_pseudo(document, MILESTONES, "after")[0],
            "milestone_dots": browser_each_pseudo(document, MILESTONE_NODE),
            "journey": browser_rect(document, JOURNEY),
            "journey_dots": browser_each_pseudo(document, JOURNEY_ROW),
        },
    )


@pytest.fixture(scope="module")
def content_forms() -> Iterator[Exported]:
    """The generated-content slide exported once, with each case's rendered pseudo-element."""
    css = DECK_CSS + CONTENT_FORMS_CSS
    with pytest.MonkeyPatch.context() as monkeypatch:
        pptx = _export(CONTENT_FORMS_BODY, monkeypatch, css=css)
    document = _document(CONTENT_FORMS_BODY, css=css)
    pseudos = browser_each_pseudo(document, ".cf")
    assert len(pseudos) == len(CONTENT_FORM_HOSTS), (
        f"fixture drift: .cf matched {len(pseudos)} hosts, the body names {len(CONTENT_FORM_HOSTS)}"
    )
    yield Exported(
        shapes=slide_shapes(pptx),
        elements=slide_shape_elements(pptx),
        geometry={
            "pseudos": dict(zip(CONTENT_FORM_HOSTS, pseudos)),
            "quote_before": browser_each_pseudo(document, INLINE_QUOTE_HOST)[0],
            "quote_after": browser_each_pseudo(document, INLINE_QUOTE_HOST, "after")[0],
            "quote_text": browser_text(document, INLINE_QUOTE_HOST),
        },
    )


@pytest.fixture(scope="module")
def borders() -> Iterator[Exported]:
    """The bordered and ringed boxes exported once, with their browser border boxes."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        pptx = _export(BORDERS_BODY, monkeypatch)
    document = _document(BORDERS_BODY)
    names = (*SINGLE_SIDES, "sided", *RINGS, RINGED_DOT)
    yield Exported(
        shapes=slide_shapes(pptx),
        elements=slide_shape_elements(pptx),
        geometry={name: browser_rect(document, f"#{name}") for name in names},
    )


# ---------------------------------------------------------------------------
# Pseudo-elements become native shapes and pictures
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestPseudoElementBoxes:
    def test_square_bullets_are_rounded_squares_beside_their_text(
        self, fixture_09: Exported
    ) -> None:
        """Fixture 09's ``.dk-list li::before``: four 12x12 coral ``roundRect`` bullets.

        Each is filled FF5F46 at its pseudo-element's browser box within 0.5 px,
        its 3 px corner as the roundRect adjustment over the 12 px side, and each
        lies left of its list item's text, on that text's first line.
        """
        _assert_deck_rule("accent", "bullet")
        bullets = fixture_09.geometry["bullets"]
        assert len(bullets) == len(BULLET_ITEM_TEXTS) and all(bullets), (
            f"fixture drift: the list items' ::before boxes are {bullets}"
        )
        shapes = fixture_09.shapes

        emitted = [
            position
            for position, shape in enumerate(shapes)
            if shape.kind == "shape"
            and shape.fill == ACCENT
            and abs(shape.w - BULLET_SIDE_PX) <= RECT_TOLERANCE_PX
            and abs(shape.h - BULLET_SIDE_PX) <= RECT_TOLERANCE_PX
        ]
        assert len(emitted) == len(bullets), (
            f"expected {len(bullets)} 12x12 FF5F46 bullets, got {len(emitted)}:\n"
            f"{_describe(shapes)}"
        )
        expected_adj = round(BULLET_RADIUS_PX / BULLET_SIDE_PX * 100000)
        for bullet, item_text in zip(bullets, BULLET_ITEM_TEXTS):
            matches = [position for position in _at(shapes, bullet) if position in emitted]
            assert len(matches) == 1, (
                f"no bullet at the browser box {_rect(bullet)} of the {item_text!r} item:\n"
                f"{_describe(shapes)}"
            )
            shape = shapes[matches[0]]
            assert shape.geometry == "roundRect", (
                f"the {item_text!r} bullet is a {shape.geometry}; a 3 px corner on a 12 px "
                "square is a roundRect"
            )
            assert shape.adj is not None and abs(shape.adj - expected_adj) <= ADJ_TOLERANCE, (
                f"the {item_text!r} bullet's roundRect adj is {shape.adj}, expected "
                f"{expected_adj} (3 px over its 12 px side)"
            )
            texts = text_shapes(shapes, item_text)
            assert texts, f"the {item_text!r} item's text is not exported:\n{_describe(shapes)}"
            text = min(texts, key=lambda candidate: candidate.x)
            _, bullet_middle = _centre(bullet)
            assert text.x >= shape.x + shape.w - RECT_TOLERANCE_PX, (
                f"the {item_text!r} text starts at x={text.x:.2f}, over its bullet, which ends "
                f"at {shape.x + shape.w:.2f}"
            )
            assert text.y <= bullet_middle <= text.y + text.h, (
                f"the {item_text!r} bullet's middle y={bullet_middle:.2f} is not beside its text "
                f"({text.y:.2f}..{text.y + text.h:.2f})"
            )

    def test_accent_bar_is_one_coral_bar_four_px_in_from_each_end(
        self, fixture_09: Exported
    ) -> None:
        """Fixture 09's ``.dk-accent-bar::before``: one 5 px-wide FF5F46 bar, its host's height - 8.

        The shape is at the pseudo-element's browser box within 0.5 px. Its
        3 px corners exceed half the 5 px width, so CSS shrinks them to 2.5 px:
        a roundRect whose adjustment is half the short side.
        """
        _assert_deck_rule("accent", "accent-bar")
        bar = fixture_09.geometry["bar"]
        host = fixture_09.geometry["bar_host"]
        assert bar is not None and abs(bar["w"] - ACCENT_BAR_WIDTH_PX) < 0.01, (
            f"fixture drift: the accent bar's ::before box is {_rect(bar)}"
        )
        assert abs(bar["h"] - (host["h"] - ACCENT_BAR_INSET_PX)) < 0.01, (
            f"fixture drift: the bar is {bar['h']} px high in a {host['h']} px host"
        )
        shapes = fixture_09.shapes

        bars = [
            position
            for position, shape in enumerate(shapes)
            if shape.kind == "shape"
            and shape.fill == ACCENT
            and abs(shape.w - ACCENT_BAR_WIDTH_PX) <= RECT_TOLERANCE_PX
        ]
        assert len(bars) == 1, (
            f"expected exactly one 5 px-wide FF5F46 bar, got {len(bars)}:\n{_describe(shapes)}"
        )
        shape = shapes[bars[0]]
        _assert_box(shape, bar, RECT_TOLERANCE_PX, "the accent bar")
        assert abs(shape.h - (host["h"] - ACCENT_BAR_INSET_PX)) <= RECT_TOLERANCE_PX, (
            f"the accent bar is {shape.h:.2f} px high; its host is {host['h']} px, less 8"
        )
        assert shape.geometry == "roundRect" and shape.adj is not None, (
            f"the accent bar is a {shape.geometry} (adj {shape.adj}); its rounded ends make it "
            "a roundRect"
        )
        assert abs(shape.adj - 50000) <= ADJ_TOLERANCE, (
            f"the accent bar's adj is {shape.adj}: its corners are half its 5 px width (50000)"
        )

    def test_milestone_track_is_a_native_rule(self, pseudo_dots: Exported) -> None:
        """The milestone row's ``::before`` track is one DCE0E2 rect at its browser box."""
        _assert_deck_rule("rule")
        track = pseudo_dots.geometry["track"]
        assert track is not None and _hex(track["style"]["backgroundColor"])[0] == RULE, (
            f"fixture drift: the milestone track is {_rect(track)}"
        )
        shapes = pseudo_dots.shapes

        filled = [
            position
            for position, shape in enumerate(shapes)
            if shape.kind == "shape" and shape.fill == RULE
        ]
        assert len(filled) == 1, (
            f"expected exactly one DCE0E2 track, got {len(filled)}:\n{_describe(shapes)}"
        )
        shape = shapes[filled[0]]
        assert shape.geometry == "rect", f"the square-ended track is a {shape.geometry}"
        _assert_box(shape, track, RECT_TOLERANCE_PX, "the milestone track")

    def test_gradient_progress_is_a_picture_of_the_pseudo_element(
        self, pseudo_dots: Exported
    ) -> None:
        """The row's ``::after`` progress, a linear gradient, is a box capture: a picture.

        A gradient pseudo-element is captured in isolation like any gradient
        box: one picture at its browser box within 0.5 px, its PNG twice that
        box, FF3621 at its left end and FF5F46 at its right on its middle row,
        and no native shape drawn for it. The first milestone's dot paints over
        its left end on screen; the picture holds the gradient there, not the
        dot's paper ring.
        """
        _assert_deck_rule("accent", "accent-2")
        progress = pseudo_dots.geometry["progress"]
        assert progress is not None and "linear-gradient" in progress["style"]["backgroundImage"], (
            f"fixture drift: the progress ::after is {_rect(progress)}"
        )
        shapes = pseudo_dots.shapes

        _, picture = _picture_at(shapes, progress, "the progress gradient")
        image = _image(picture, "the progress gradient")
        expected_size = (progress["w"] * CAPTURE_SCALE, progress["h"] * CAPTURE_SCALE)
        assert (
            abs(image.width - expected_size[0]) <= PNG_SIZE_TOLERANCE_PX
            and abs(image.height - expected_size[1]) <= PNG_SIZE_TOLERANCE_PX
        ), f"the progress PNG is {image.size}, not 2x its {progress['w']}x{progress['h']} box"
        _, middle = _centre(progress)
        left = _pixel(image, picture, progress["x"] + GRADIENT_END_INSET_PX, middle)
        right = _pixel(
            image, picture, progress["x"] + progress["w"] - GRADIENT_END_INSET_PX, middle
        )
        assert _is(left, ACCENT_2) and _is(right, ACCENT), (
            f"the progress picture runs {left} to {right}; the gradient runs {ACCENT_2} to {ACCENT}"
        )
        native = [
            position for position in _at(shapes, progress) if shapes[position].kind != "picture"
        ]
        assert native == [], (
            f"the captured progress is drawn natively as well:\n{_describe(shapes)}"
        )

    def test_milestone_dots_are_circles_in_their_own_colours(self, pseudo_dots: Exported) -> None:
        """Each milestone's ``::before`` dot is one ellipse in its own colour, ring and all.

        The colours come from ``.pd-node:nth-child(n)::before``: FF5F46,
        FF3621, 1B5162 and 00A972, as the browser computes them on the
        untouched page. A dot with a 4 px paper ring is an ellipse with that
        outline (3 pt F9F7F4), its box inset by half the ring. The current
        milestone's dot has a halo instead, ``box-shadow: 0 0 0 4px
        rgba(27, 81, 98, 0.2)``: an outline of 3 pt at alpha 0.2, outside the
        dot, its box grown by 2 px.
        """
        _assert_deck_rule("accent", "accent-2", "paper", "good")
        dots = pseudo_dots.geometry["milestone_dots"]
        assert len(dots) == len(MILESTONE_DOT_FILLS) and all(dots), (
            f"fixture drift: the milestone dots are {dots}"
        )
        shapes = pseudo_dots.shapes
        elements = pseudo_dots.elements

        wrong = []
        for index, (dot, fill) in enumerate(zip(dots, MILESTONE_DOT_FILLS)):
            style = dot["style"]
            assert _hex(style["backgroundColor"])[0] == fill, (
                f"fixture drift: milestone {index + 1}'s dot computes {style['backgroundColor']}"
            )
            ring = _ring(style["boxShadow"])
            border_px = _px(style["borderTopWidth"])
            assert (ring is not None) == (index == CURRENT_MILESTONE) and (border_px > 0) == (
                index != CURRENT_MILESTONE
            ), f"fixture drift: milestone {index + 1}'s dot has ring {ring}, border {border_px}"
            if ring is None:
                expected_box = _grown(dot, -border_px / 2)
                outline, outline_alpha = _hex(style["borderTopColor"])
                outline_pt = border_px * PT_PER_PX
            else:
                expected_box = _grown(dot, ring[1] / 2)
                outline, outline_alpha = _hex(ring[0])
                outline_pt = ring[1] * PT_PER_PX

            found = _centred_on(shapes, dot, kind="shape", fill=fill)
            if len(found) != 1:
                wrong.append(
                    f"milestone {index + 1}: {len(found)} {fill} shapes centred on {_rect(dot)}"
                )
                continue
            shape = shapes[found[0]]
            emitted_alpha = _outline_alpha(elements[found[0]])
            off = _off(shape, expected_box)
            if shape.geometry != "ellipse":
                wrong.append(f"milestone {index + 1}: a {shape.geometry}, not an ellipse")
            if any(abs(delta) > RECT_TOLERANCE_PX for delta in off.values()):
                wrong.append(f"milestone {index + 1}: box off {expected_box} by {off}")
            if (
                shape.line != outline
                or shape.line_w_pt is None
                or (abs(shape.line_w_pt - outline_pt) > LINE_WIDTH_TOLERANCE_PT)
            ):
                wrong.append(
                    f"milestone {index + 1}: outline {shape.line} {shape.line_w_pt} pt, "
                    f"expected {outline} {outline_pt} pt"
                )
            expected_alpha = None if outline_alpha >= 1 else outline_alpha
            if (emitted_alpha is None) != (expected_alpha is None) or (
                expected_alpha is not None and abs(emitted_alpha - expected_alpha) > ALPHA_TOLERANCE
            ):
                wrong.append(
                    f"milestone {index + 1}: outline alpha {emitted_alpha}, "
                    f"expected {expected_alpha}"
                )
            if index == CURRENT_MILESTONE and shape.shadow is not None:
                wrong.append(
                    f"milestone {index + 1}: its halo is a shadow {shape.shadow}, not an outline"
                )
        assert not wrong, "the milestone dots differ from the browser:\n" + "\n".join(
            [*wrong, _describe(shapes)]
        )

    def test_milestone_dots_paint_over_the_track_and_the_progress(
        self, pseudo_dots: Exported
    ) -> None:
        """Paint order: the track, then the progress over it, then the raised dots.

        The track and the progress are the row's positioned ``::before`` and
        ``::after``, painted in tree order; the dots have ``z-index: 1``, so
        each paints over both, as the browser paints them.
        """
        geometry = pseudo_dots.geometry
        shapes = pseudo_dots.shapes
        track = [
            position for position in _at(shapes, geometry["track"]) if shapes[position].fill == RULE
        ]
        progress = [
            position
            for position in _at(shapes, geometry["progress"])
            if shapes[position].kind == "picture"
        ]
        dots = [
            found[0]
            for dot, fill in zip(geometry["milestone_dots"], MILESTONE_DOT_FILLS)
            if len(found := _centred_on(shapes, dot, kind="shape", fill=fill)) == 1
        ]
        assert len(track) == 1 and len(progress) == 1 and len(dots) == len(MILESTONE_DOT_FILLS), (
            f"expected the track, the progress picture and four dots; got track {track}, "
            f"progress {progress}, dots {dots}:\n{_describe(shapes)}"
        )
        assert track[0] < progress[0] < min(dots), (
            f"back to front the browser paints the track, the progress, then the dots; emitted "
            f"track at {track[0]}, progress at {progress[0]}, dots at {dots}"
        )

    def test_journey_dots_sit_on_the_lists_left_border(self, pseudo_dots: Exported) -> None:
        """The journey's rule is its list's 2 px left border; each row's ``::before`` dot is on it.

        The border is one vertical DCE0E2 line of 1.5 pt, its centre 1 px in
        from the list's left edge, over the list's full height. Each dot is a
        12x12 FF5F46 ellipse at its browser box within 0.5 px, painted after the
        line (a positioned pseudo-element over its list's border).
        """
        _assert_deck_rule("accent", "rule")
        journey = pseudo_dots.geometry["journey"]
        dots = pseudo_dots.geometry["journey_dots"]
        assert len(dots) == 3 and all(
            dot is not None and abs(dot["w"] - JOURNEY_DOT_SIDE_PX) < 0.01 for dot in dots
        ), f"fixture drift: the journey dots are {dots}"
        shapes = pseudo_dots.shapes

        lines = _lines(shapes, RULE)
        assert len(lines) == 1, (
            f"expected the journey's left border as one DCE0E2 line, got {len(lines)}:\n"
            f"{_describe(shapes)}"
        )
        line_index, line = lines[0]
        assert line.w <= LINE_THICKNESS_PX, f"the left border is not vertical: w={line.w}"
        assert line.line_w_pt is not None and (
            abs(line.line_w_pt - JOURNEY_BORDER_PX * PT_PER_PX) <= LINE_WIDTH_TOLERANCE_PT
        ), f"a 2 px border is a 1.5 pt line, got {line.line_w_pt}"
        expected = {
            "x": journey["x"] + JOURNEY_BORDER_PX / 2,
            "y": journey["y"],
            "h": journey["h"],
        }
        off = {key: round(getattr(line, key) - value, 3) for key, value in expected.items()}
        assert all(abs(delta) <= RECT_TOLERANCE_PX for delta in off.values()), (
            f"the left border's line is off its centre line {expected} by {off}"
        )

        for number, dot in enumerate(dots, start=1):
            found = [
                position
                for position in _at(shapes, dot)
                if shapes[position].kind == "shape" and shapes[position].fill == ACCENT
            ]
            assert len(found) == 1, (
                f"no FF5F46 dot at the browser box {_rect(dot)} of journey row {number}:\n"
                f"{_describe(shapes)}"
            )
            assert shapes[found[0]].geometry == "ellipse", (
                f"journey row {number}'s round dot is a {shapes[found[0]].geometry}"
            )
            assert found[0] > line_index, (
                f"journey row {number}'s dot (spTree {found[0]}) paints under the border it "
                f"sits on (spTree {line_index})"
            )


# ---------------------------------------------------------------------------
# Generated text
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestGeneratedContent:
    def test_counter_numbers_the_steps_01_02_03(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``counter(s, decimal-leading-zero)`` over three steps reads "01", "02" and "03".

        The steps are numbered by ``.steps { counter-reset: s }`` and
        ``.step::before { counter-increment: s; content: counter(s,
        decimal-leading-zero) }``. Each number is a text item of its own (a flex
        item beside its label), at the pseudo-element's browser box, in the
        pseudo-element's computed colour and size (FF5F46, 18 pt), left of its
        label. The numbers are Chrome's own counter values: counting a step
        twice would read "02", "04", "06".
        """
        css = DECK_CSS + COUNTER_CSS
        document = _document(COUNTER_BODY, css=css)
        numbers = browser_each_pseudo(document, ".step")
        assert [box["text"] if box else None for box in numbers] == list(COUNTER_TEXTS), (
            f"fixture drift: the browser numbers the steps {numbers}"
        )
        shapes = slide_shapes(_export(COUNTER_BODY, monkeypatch, css=css))

        emitted = [_normalised(shape.text) for shape in shapes if shape.kind == "text"]
        numbers_read = [text for text in emitted if re.fullmatch(r"\d+", text)]
        assert numbers_read == list(COUNTER_TEXTS), (
            f"the step numbers read {numbers_read} (every text item: {emitted}); the browser "
            f"shows {list(COUNTER_TEXTS)}"
        )
        for number, box, label in zip(COUNTER_TEXTS, numbers, COUNTER_LABELS):
            items = [
                item for item in _text_items_at(shapes, box) if _normalised(item.text) == number
            ]
            assert len(items) == 1, (
                f"no text item {number!r} at its pseudo-element's browser box {_rect(box)}:\n"
                f"{_describe(shapes)}"
            )
            runs = [run for para in items[0].paras for run in para.runs if run.text.strip()]
            assert runs and all(run.color == ACCENT for run in runs), (
                f"step {number} is coloured {[run.color for run in runs]}; its ::before is FF5F46"
            )
            assert all(
                run.size_pt is not None and abs(run.size_pt - COUNTER_SIZE_PT) < 0.01
                for run in runs
            ), f"step {number} is {[run.size_pt for run in runs]} pt; its ::before is 18 pt"
            labels = text_shapes(shapes, label)
            assert labels and all(
                _normalised(item.text) == label and item.x > items[0].x for item in labels
            ), (
                f"step {number}'s label {label!r} is not its own item right of the number:\n"
                f"{_describe(shapes)}"
            )

    @pytest.mark.parametrize("host", tuple(CONTENT_FORMS))
    def test_generated_text_is_what_the_browser_renders(
        self, content_forms: Exported, host: str
    ) -> None:
        """Each pseudo-element's text item reads what the browser renders for its ``content``.

        Every counter style on consecutive values (decimal, decimal-leading-zero,
        lower-/upper-alpha, lower-/upper-roman, disc, circle, square), resets
        with a start, increments by a step on the pseudo-element, ``counter-set``
        on an element and on a pseudo-element, ``counters()`` through a nested
        scope and out of it, a reset whose scope runs through its element's
        following siblings, a string with CSS escapes, and ``attr()``. The text
        item sits at the pseudo-element's browser box (left edge within 0.5 px,
        centre inside it), and its text, white space collapsed, is the browser's.
        """
        assert set(CONTENT_FORMS) == set(CONTENT_FORM_HOSTS), (
            "fixture drift: the cases and the body's hosts differ"
        )
        box = content_forms.geometry["pseudos"][host]
        assert box is not None and _normalised(box["text"]) == CONTENT_FORMS[host], (
            f"fixture drift: the browser renders #{host}::before as {_rect(box)}"
        )
        shapes = content_forms.shapes

        items = _text_items_at(shapes, box)
        texts = [_normalised(item.text) for item in items]
        assert texts == [CONTENT_FORMS[host]], (
            f"#{host}::before: the text at its browser box {_rect(box)} reads {texts}; the browser "
            f"renders {CONTENT_FORMS[host]!r}:\n{_describe(shapes)}"
        )

    def test_inline_generated_text_joins_its_sentence(self, content_forms: Exported) -> None:
        """Inline ``open-quote`` / ``close-quote`` read “ and ” inside the paragraph's text item.

        The quotes are inline ``::before`` and ``::after``, so they are part of
        the paragraph's line: one text item reads “Quoted words”, the browser's
        quotes around the browser's text, and no item holds a quote alone.
        """
        geometry = content_forms.geometry
        before, after = geometry["quote_before"], geometry["quote_after"]
        expected = before["text"] + _normalised(geometry["quote_text"]) + after["text"]
        assert expected == INLINE_QUOTE_TEXT, (
            f"fixture drift: the browser renders the quoted paragraph as {expected!r}"
        )
        shapes = content_forms.shapes

        items = [shape for shape in shapes if shape.kind == "text" and "Quoted words" in shape.text]
        assert [_normalised(item.text) for item in items] == [INLINE_QUOTE_TEXT], (
            f"the quoted paragraph reads {[item.text for item in items]}; the browser shows "
            f"{INLINE_QUOTE_TEXT!r}:\n{_describe(shapes)}"
        )
        alone = [
            shape
            for shape in shapes
            if shape.kind == "text" and _normalised(shape.text) in ("\u201c", "\u201d")
        ]
        assert alone == [], f"a quote is exported as a text item of its own:\n{_describe(shapes)}"


# ---------------------------------------------------------------------------
# Pseudo-elements are read, never written
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestReadOnlyPseudoElements:
    def test_the_export_inserts_nothing_into_the_page_for_pseudo_elements(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The bullets export, and the page they are read from gains no node.

        The slide's own script watches body's subtree once the page has
        loaded: any node added or removed recolours a native probe and a
        captured gradient probe #00FF00 and writes what changed into the native
        probe's text. So the export shows its own page: the list's two
        ``::before`` bullets are 12x12 FF5F46 shapes at their browser boxes,
        the native probe is still 5A6F77 and reads "body unchanged", and the
        gradient probe's picture holds no #00FF00 pixel. A node inserted for a
        pseudo-element, before the snapshot or before a capture and whether or
        not it is removed again, fails the probes. A variant that inserts one
        node after load proves the watch fires.
        """
        css = DECK_CSS + NO_INSERTION_CSS
        document = _document(NO_INSERTION_BODY, css=css)
        bullets = browser_each_pseudo(document, ".ni-list li")
        assert len(bullets) == NO_INSERTION_BULLETS and all(bullets), (
            f"fixture drift: the list's ::before bullets are {[_rect(box) for box in bullets]}"
        )
        native_probe = browser_rect(document, "#ni-probe")
        captured_probe = browser_rect(document, "#ni-gradient-probe")
        clean_fill = _hex(browser_style(document, "#ni-probe")["backgroundColor"])[0]
        assert clean_fill == NO_INSERTION_PROBE_FILL, (
            f"fixture drift: the untouched page's probe is {clean_fill}"
        )
        bitten = _document(NO_INSERTION_BITTEN_BODY, css=css)
        assert _hex(browser_style(bitten, "#ni-probe")["backgroundColor"])[0] == INSERTION_SIGNAL, (
            "fixture drift: a node inserted under body after load does not set off the watch"
        )

        pptx = _export(NO_INSERTION_BODY, monkeypatch, css=css)
        shapes = slide_shapes(pptx)

        probes = [position for position in _at(shapes, native_probe) if shapes[position].fill]
        reports = [
            _normalised(shape.text)
            for shape in shapes
            if shape.kind == "text" and "body" in shape.text
        ]
        assert [shapes[position].fill for position in probes] == [NO_INSERTION_PROBE_FILL] and (
            reports == [NO_INSERTION_PROBE_TEXT]
        ), (
            f"the page gained or lost nodes during the export: the probe is filled "
            f"{[shapes[position].fill for position in probes]} and reads {reports}:\n"
            f"{_describe(shapes)}"
        )
        _, picture = _picture_at(shapes, captured_probe, "the gradient probe")
        image = _image(picture, "the gradient probe")
        signalled = sum(1 for pixel in image.getdata() if _is(pixel, INSERTION_SIGNAL))
        assert signalled == 0, (
            f"the gradient probe's picture holds {signalled} #00FF00 pixels: the page gained or "
            "lost nodes before the capture"
        )
        for number, bullet in enumerate(bullets, start=1):
            found = [
                position
                for position in _at(shapes, bullet)
                if shapes[position].kind == "shape" and shapes[position].fill == ACCENT
            ]
            assert len(found) == 1, (
                f"bullet {number} is not exported at its browser box {_rect(bullet)}:\n"
                f"{_describe(shapes)}"
            )

    def test_structural_selectors_keep_painting_their_elements_as_on_screen(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The milestone track exports, and each real dot keeps the colour its position gives it.

        The design system's milestones colour each real dot by its
        milestone's place in the row (``.ds-node:nth-child(2) .ds-dot``) and
        draw the track as the row's ``::before``. Anything inserted first in
        the row for the track would shift every milestone's ``:nth-child`` by
        one, and every dot would take its neighbour's colour though nothing
        moved. Each dot is exported as the browser paints it on screen
        (FF5F46, FF3621, 1B5162, 00A972), and the track is a DCE0E2 shape at
        its browser box.
        """
        _assert_deck_rule("accent", "accent-2", "good", "rule")
        css = DECK_CSS + STRUCTURAL_CSS
        document = _document(STRUCTURAL_BODY, css=css)
        dots = browser_each_rect(document, STRUCTURAL_DOT)
        fills = [
            _hex(browser_style(document, STRUCTURAL_DOT, index)["backgroundColor"])[0]
            for index in range(len(dots))
        ]
        assert fills == list(MILESTONE_DOT_FILLS), f"fixture drift: the dots compute {fills}"
        track = browser_each_pseudo(document, ".ds-milestones")[0]
        assert track is not None, "fixture drift: the milestone row has no ::before track"

        shapes = slide_shapes(_export(STRUCTURAL_BODY, monkeypatch, css=css))

        wrong = []
        for number, (dot, fill) in enumerate(zip(dots, fills), start=1):
            found = [
                position
                for position in _at(shapes, dot)
                if shapes[position].kind == "shape" and shapes[position].geometry == "ellipse"
            ]
            painted = [shapes[position].fill for position in found]
            if painted != [fill]:
                wrong.append(
                    f"milestone {number}'s dot is filled {painted}; the browser paints {fill}"
                )
        assert not wrong, "\n".join([*wrong, _describe(shapes)])
        track_shapes = [
            position for position in _at(shapes, track) if shapes[position].fill == RULE
        ]
        assert len(track_shapes) == 1, (
            f"the milestone track is not exported at its browser box {_rect(track)}:\n"
            f"{_describe(shapes)}"
        )


# ---------------------------------------------------------------------------
# Per-side borders
# ---------------------------------------------------------------------------


def _side_line_box(rect: dict, side: SideLine) -> dict:
    """Where a full-edge line for ``side`` runs: its centre inset by half the width."""
    half = side.width_px / 2
    if side.side == "top":
        return {"x": rect["x"], "y": rect["y"] + half, "w": rect["w"], "h": 0.0}
    if side.side == "bottom":
        return {"x": rect["x"], "y": rect["y"] + rect["h"] - half, "w": rect["w"], "h": 0.0}
    if side.side == "left":
        return {"x": rect["x"] + half, "y": rect["y"], "w": 0.0, "h": rect["h"]}
    return {"x": rect["x"] + rect["w"] - half, "y": rect["y"], "w": 0.0, "h": rect["h"]}


def _assert_line_style(line: Shape, side: SideLine, what: str) -> None:
    assert line.line_w_pt is not None and (
        abs(line.line_w_pt - side.width_px * PT_PER_PX) <= LINE_WIDTH_TOLERANCE_PT
    ), (
        f"{what}: a {side.width_px} px border is a {side.width_px * PT_PER_PX} pt line, "
        f"got {line.line_w_pt}"
    )
    emitted_dash = line.line_dash or "solid"
    assert emitted_dash == side.dash, f"{what}: prstDash {emitted_dash}, expected {side.dash}"


@pytest.mark.slow
@requires_huashu_sidecar
class TestPerSideBorders:
    def test_blockquote_left_border_is_one_vertical_line(self, fixture_09: Exported) -> None:
        """Fixture 09's ``border-left: 6px solid #FF5F46`` blockquote: one vertical 4.5 pt line.

        The line's centre runs 3 px in from the quote's left edge, over its full
        height, within 0.5 px; it is solid and coral, and it is the slide's only
        line.
        """
        _assert_deck_rule("accent", "quote")
        quote = fixture_09.geometry["quote"]
        shapes = fixture_09.shapes

        lines = [shape for shape in shapes if shape.kind == "line"]
        assert len(lines) == 1 and lines[0].line == ACCENT, (
            f"expected the quote's left border as the slide's one FF5F46 line, got "
            f"{[(line.line, line.line_w_pt) for line in lines]}:\n{_describe(shapes)}"
        )
        line = lines[0]
        side = SideLine("left", ACCENT, QUOTE_BORDER_PX, "solid")
        _assert_line_style(line, side, "the quote's left border")
        assert line.w <= LINE_THICKNESS_PX, f"the quote's left border is not vertical: w={line.w}"
        _assert_box(line, _side_line_box(quote, side), RECT_TOLERANCE_PX, "the quote's left border")

    @pytest.mark.parametrize("name", tuple(SINGLE_SIDES))
    def test_a_single_side_border_is_one_line_in_its_style(
        self, borders: Exported, name: str
    ) -> None:
        """A border on one side is one line along that edge, in its colour, width and dash.

        ``dashed`` is prstDash ``dash``, ``dotted`` is ``sysDot`` (round dots
        one width apart, as CSS spaces them) and ``solid`` is solid. The line's
        centre is inset by half the width and it spans the whole edge, within
        0.5 px.
        """
        side = SINGLE_SIDES[name]
        rect = borders.geometry[name]
        shapes = borders.shapes

        lines = _lines(shapes, side.colour)
        assert len(lines) == 1, (
            f"#{name}: expected its {side.side} border as one {side.colour} line, got "
            f"{len(lines)}:\n{_describe(shapes)}"
        )
        _, line = lines[0]
        _assert_line_style(line, side, f"#{name}'s {side.side} border")
        _assert_box(
            line, _side_line_box(rect, side), RECT_TOLERANCE_PX, f"#{name}'s {side.side} border"
        )
        outlined = [
            shape for shape in shapes if shape.kind == "shape" and shape.line == side.colour
        ]
        assert outlined == [], f"#{name}'s one-side border is also drawn as a shape outline"

    def test_each_painted_side_is_its_own_line_over_the_fill(self, borders: Exported) -> None:
        """Four different sides: a line per painted side over the fill, and none for a clear side.

        ``#sided`` has a 2 px solid D0302A top, a 4 px transparent right, a
        6 px dashed 7B2FBE bottom and an 8 px dotted 2F5BEA left over a CDEDE1
        fill. Each painted side is a line of its own colour, width and dash,
        its centre half its width in from its edge within 0.5 px, lying along
        that edge inside the border box and covering at least the edge between
        the neighbouring borders (corner joins are the emitter's choice). The
        transparent side paints nothing. The fill is a shape with no outline,
        and every line is painted after it, as CSS paints a border over its
        background.
        """
        rect = borders.geometry["sided"]
        shapes = borders.shapes

        filled = [position for position, shape in enumerate(shapes) if shape.fill == SIDED_FILL]
        assert len(filled) == 1, f"expected the CDEDE1 fill once:\n{_describe(shapes)}"
        fill_index = filled[0]
        assert shapes[fill_index].line is None, (
            f"#sided's borders differ by side, so its fill has no outline; got "
            f"{shapes[fill_index].line}"
        )
        painted = [side.colour for side in (*SINGLE_SIDES.values(), *SIDED_LINES)]
        drawn = [shape.line for shape in shapes if shape.kind == "line"]
        assert sorted(drawn) == sorted(painted), (
            f"the slide's lines are {drawn}: expected one per painted side, {painted}, and "
            f"none for #sided's transparent right side:\n{_describe(shapes)}"
        )

        for side in SIDED_LINES:
            lines = _lines(shapes, side.colour)
            assert len(lines) == 1, (
                f"#sided: expected its {side.side} border as one {side.colour} line, got "
                f"{len(lines)}:\n{_describe(shapes)}"
            )
            index, line = lines[0]
            what = f"#sided's {side.side} border"
            _assert_line_style(line, side, what)
            assert index > fill_index, (
                f"{what} (spTree {index}) paints under its fill ({fill_index})"
            )
            expected = _side_line_box(rect, side)
            if side.side in ("top", "bottom"):
                across, along, length, thickness = "y", "x", "w", "h"
                start, edge = rect["x"], rect["w"]
                neighbours = SIDED_WIDTHS["left"] + SIDED_WIDTHS["right"]
            else:
                across, along, length, thickness = "x", "y", "h", "w"
                start, edge = rect["y"], rect["h"]
                neighbours = SIDED_WIDTHS["top"] + SIDED_WIDTHS["bottom"]
            assert getattr(line, thickness) <= LINE_THICKNESS_PX, (
                f"{what} does not run along its edge: its {thickness} is {getattr(line, thickness)}"
            )
            assert abs(getattr(line, across) - expected[across]) <= RECT_TOLERANCE_PX, (
                f"{what}'s centre is at {across}={getattr(line, across):.3f}, expected "
                f"{expected[across]:.3f}"
            )
            line_start = getattr(line, along)
            line_end = line_start + getattr(line, length)
            assert (
                start - RECT_TOLERANCE_PX <= line_start
                and line_end <= start + edge + RECT_TOLERANCE_PX
            ), (
                f"{what} runs {line_start:.2f}..{line_end:.2f}, outside its edge "
                f"{start}..{start + edge}"
            )
            assert line_end - line_start >= edge - neighbours - RECT_TOLERANCE_PX, (
                f"{what} is {line_end - line_start:.2f} px long; its edge is {edge} px, "
                f"{edge - neighbours} between the neighbouring borders"
            )


# ---------------------------------------------------------------------------
# Outline shadows
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestOutlineShadows:
    @pytest.mark.parametrize("name", tuple(RINGS))
    def test_spread_only_shadow_is_an_outline_outside_the_box(
        self, borders: Exported, name: str
    ) -> None:
        """``box-shadow: 0 0 0 Npx C`` is the shape's outline: N px of C, outside the box.

        ``#ringed`` is ringed by ``0 0 0 2px #1B3139``: an outline of 1.5 pt.
        ``#ringed-round`` is a 12 px-radius card with a translucent halo,
        ``0 0 0 6px rgba(255, 54, 33, 0.18)``: 4.5 pt of FF3621 at alpha 0.18.
        Each shape keeps its fill, its box is the border box grown by N/2 on
        every side (so the stroke's inner edge is the box's edge), a rounded
        box's corner grows with it (radius + N/2 over the grown short side),
        and the ring is no shadow.
        """
        ring = RINGS[name]
        rect = borders.geometry[name]
        shapes = borders.shapes
        elements = borders.elements

        found = [
            position
            for position, shape in enumerate(shapes)
            if shape.kind == "shape" and shape.fill == ring.fill
        ]
        assert len(found) == 1, f"#{name}: expected its {ring.fill} box once:\n{_describe(shapes)}"
        shape = shapes[found[0]]
        assert shape.line == ring.colour, (
            f"#{name}: its outline is {shape.line}, the ring is {ring.colour}"
        )
        assert shape.line_w_pt is not None and (
            abs(shape.line_w_pt - ring.spread_px * PT_PER_PX) <= LINE_WIDTH_TOLERANCE_PT
        ), (
            f"#{name}: a {ring.spread_px} px ring is a {ring.spread_px * PT_PER_PX} pt outline, "
            f"got {shape.line_w_pt}"
        )
        assert (shape.line_dash or "solid") == "solid", (
            f"#{name}: the ring is dashed {shape.line_dash}"
        )
        alpha = _outline_alpha(elements[found[0]])
        assert (alpha is None) == (ring.alpha is None) and (
            ring.alpha is None or abs(alpha - ring.alpha) <= ALPHA_TOLERANCE
        ), f"#{name}: the outline's alpha is {alpha}, the ring's {ring.alpha}"
        assert shape.shadow is None, (
            f"#{name}: a spread-only ring is exported as a shadow {shape.shadow}"
        )
        grown = _grown(rect, ring.spread_px / 2)
        _assert_box(shape, grown, OUTLINE_TOLERANCE_PX, f"#{name}, grown by half its ring")
        if ring.radius_px:
            expected_adj = round(
                (ring.radius_px + ring.spread_px / 2) / min(grown["w"], grown["h"]) * 100000
            )
            assert (
                shape.geometry == "roundRect"
                and shape.adj is not None
                and (abs(shape.adj - expected_adj) <= ADJ_TOLERANCE)
            ), (
                f"#{name}: a {shape.geometry} with adj {shape.adj}, "
                f"expected roundRect adj {expected_adj}"
            )
        else:
            assert shape.geometry == "rect", f"#{name}: a square box's ring is a {shape.geometry}"

    def test_a_ring_around_a_bordered_box_is_a_second_shape(self, borders: Exported) -> None:
        """A box with a uniform border and a spread-only ring is two shapes, one outline each.

        ``#ringed-dot`` is the design system's milestone dot: a FF5F46 circle
        with a 5 px F9F7F4 border and ``box-shadow: 0 0 0 1px #DCE0E2``. The
        border stays the circle's outline (3.75 pt, its box inset by 2.5 px);
        the ring is a second ellipse with no fill and a 0.75 pt DCE0E2
        outline, its box the border box grown by 0.5 px, and no shadow. Both
        are centred on the dot, within 0.1 px.
        """
        rect = borders.geometry[RINGED_DOT]
        shapes = borders.shapes
        border_colour, border_px = RINGED_DOT_BORDER
        ring_colour, spread_px = RINGED_DOT_RING

        circles = [
            shapes[position]
            for position in _centred_on(shapes, rect, kind="shape", geometry="ellipse")
        ]
        assert len(circles) == 2, (
            f"#{RINGED_DOT}: expected two ellipses (the bordered dot and its ring) centred on "
            f"{rect}, got {len(circles)}:\n{_describe(shapes)}"
        )
        dots = [circle for circle in circles if circle.fill == RINGED_DOT_FILL]
        rings = [circle for circle in circles if circle.fill is None]
        assert len(dots) == 1 and len(rings) == 1, (
            f"#{RINGED_DOT}: expected one {RINGED_DOT_FILL} dot and one unfilled ring, got fills "
            f"{[circle.fill for circle in circles]}"
        )
        dot, ring = dots[0], rings[0]
        assert (
            dot.line == border_colour
            and dot.line_w_pt is not None
            and (abs(dot.line_w_pt - border_px * PT_PER_PX) <= LINE_WIDTH_TOLERANCE_PT)
        ), f"#{RINGED_DOT}: the dot's outline is {dot.line} {dot.line_w_pt} pt, its border"
        _assert_box(dot, _grown(rect, -border_px / 2), OUTLINE_TOLERANCE_PX, "the bordered dot")
        assert (
            ring.line == ring_colour
            and ring.line_w_pt is not None
            and (abs(ring.line_w_pt - spread_px * PT_PER_PX) <= LINE_WIDTH_TOLERANCE_PT)
        ), f"#{RINGED_DOT}: the ring's outline is {ring.line} {ring.line_w_pt} pt"
        assert ring.shadow is None, f"#{RINGED_DOT}: the ring is exported as a shadow"
        _assert_box(ring, _grown(rect, spread_px / 2), OUTLINE_TOLERANCE_PX, "the dot's ring")

    def test_stacked_rings_are_shapes_from_the_box_outwards(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two spread-only rings: the first listed outlines the box, the second is a shape under it.

        ``box-shadow: 0 0 0 2px #FFFFFF, 0 0 0 5px #1B5162`` paints a 5 px
        1B5162 ring around the box, and the 2 px white ring over its inner part
        (the first layer listed is on top). The box is its CDEDE1 rect
        outlined in 1.5 pt FFFFFF, grown by 1 px; painted before it is one
        unfilled rect outlined in 3.75 pt 1B5162, grown by 2.5 px. Neither is a
        shadow.
        """
        rect = browser_rect(_document(STACKED_BODY), "#stacked")
        shapes = slide_shapes(_export(STACKED_BODY, monkeypatch))

        (top_colour, top_px), (under_colour, under_px) = STACKED_RINGS
        boxes = [position for position, shape in enumerate(shapes) if shape.fill == STACKED_FILL]
        unders = [
            position
            for position, shape in enumerate(shapes)
            if shape.kind == "shape" and shape.fill is None and shape.line == under_colour
        ]
        assert len(boxes) == 1 and len(unders) == 1, (
            f"expected the box once and its outer ring once:\n{_describe(shapes)}"
        )
        box, under = shapes[boxes[0]], shapes[unders[0]]
        for shape, colour, spread, what in (
            (box, top_colour, top_px, "the box (its top ring)"),
            (under, under_colour, under_px, "the outer ring"),
        ):
            assert shape.geometry == "rect" and shape.shadow is None, (
                f"{what} is a {shape.geometry} with shadow {shape.shadow}"
            )
            assert (
                shape.line == colour
                and shape.line_w_pt is not None
                and (abs(shape.line_w_pt - spread * PT_PER_PX) <= LINE_WIDTH_TOLERANCE_PT)
            ), f"{what}: outline {shape.line} {shape.line_w_pt} pt, expected {colour}"
            _assert_box(shape, _grown(rect, spread / 2), OUTLINE_TOLERANCE_PX, what)
        assert unders[0] < boxes[0], (
            f"the outer ring (spTree {unders[0]}) paints over the box and its top ring ({boxes[0]})"
        )


# ---------------------------------------------------------------------------
# Border regions a line cannot draw, and borders of wrapping inline boxes
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestBorderRegions:
    def test_a_side_with_no_inner_edge_is_the_triangle_css_paints(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A CSS triangle (an arrowhead) exports as the triangle the browser paints, not a bar.

        ``#arrowhead`` is all border, and its painted left side has no inner
        edge. CSS joins neighbouring sides along the corner diagonals, so it
        paints the triangle between that side's outer edge and where the two
        diagonals meet: (x, y), (x + 70, y + 40) and (x, y + 80) of its 70x80
        border box. It is one coral filled path through exactly those corners,
        within 0.5 px, and no line.
        """
        document = _document(TRIANGLE_BODY)
        rect = browser_rect(document, "#arrowhead")
        assert (rect["w"], rect["h"]) == TRIANGLE_SIZE, f"fixture drift: the arrowhead is {rect}"
        pptx = _export(TRIANGLE_BODY, monkeypatch)
        shapes = slide_shapes(pptx)
        elements = slide_shape_elements(pptx)

        coral = [position for position, shape in enumerate(shapes) if shape.fill == ACCENT]
        assert len(coral) == 1 and shapes[coral[0]].geometry == "custGeom", (
            f"expected the arrowhead as one FF5F46 path:\n{_describe(shapes)}"
        )
        assert [shape for shape in shapes if shape.kind == "line"] == [], (
            f"the arrowhead is drawn as a line:\n{_describe(shapes)}"
        )
        shape = shapes[coral[0]]
        points = [
            (
                shape.x + int(point.get("x")) / EMU_PER_PX,
                shape.y + int(point.get("y")) / EMU_PER_PX,
            )
            for point in elements[coral[0]].iterfind(
                "p:spPr/a:custGeom/a:pathLst/a:path//a:pt", NAMESPACES
            )
        ]
        width, height = TRIANGLE_SIZE
        expected = [
            (rect["x"], rect["y"]),
            (rect["x"] + width, rect["y"] + height / 2),
            (rect["x"], rect["y"] + height),
        ]
        unmatched = [
            corner
            for corner in expected
            if not any(
                abs(x - corner[0]) <= RECT_TOLERANCE_PX and abs(y - corner[1]) <= RECT_TOLERANCE_PX
                for x, y in points
            )
        ]
        assert len(points) == len(expected) and not unmatched, (
            f"the arrowhead's path runs through {points}; the browser paints the triangle "
            f"{expected} (missing {unmatched})"
        )

    def test_a_wrapping_inline_boxs_side_borders_are_sliced_between_its_fragments(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A wrapping inline box's side borders are where the browser paints them: sliced.

        Under the default ``box-decoration-break: slice`` a wrapping inline
        box's left border is on its first fragment only and its right border
        on its last; its bottom border runs under every fragment. ``#sliced``
        exports one 7B2FBE line at its first fragment's left edge and one
        2F5BEA line at its last fragment's right edge, each half its width in,
        and one 00A972 line under each fragment, each at its browser fragment
        within 0.5 px.
        """
        fragments = [
            fragment
            for fragment in browser_client_rects(_document(SLICED_BODY), "#sliced")
            if fragment["w"] > 0
        ]
        assert len(fragments) >= 2, f"fixture drift: #sliced does not wrap: {fragments}"
        shapes = slide_shapes(_export(SLICED_BODY, monkeypatch))

        for side, fragment, what in (
            (SLICED_LEFT, fragments[0], "its first fragment's left border"),
            (SLICED_RIGHT, fragments[-1], "its last fragment's right border"),
        ):
            lines = _lines(shapes, side.colour)
            assert len(lines) == 1, (
                f"#sliced: expected {what} as one {side.colour} line, got {len(lines)}:\n"
                f"{_describe(shapes)}"
            )
            _assert_line_style(lines[0][1], side, f"#sliced: {what}")
            _assert_box(lines[0][1], _side_line_box(fragment, side), RECT_TOLERANCE_PX, what)
        bottoms = [line for _, line in _lines(shapes, SLICED_BOTTOM.colour)]
        assert len(bottoms) == len(fragments), (
            f"#sliced: expected one 00A972 bottom line per fragment ({len(fragments)}), got "
            f"{len(bottoms)}:\n{_describe(shapes)}"
        )
        for number, fragment in enumerate(fragments, start=1):
            expected = _side_line_box(fragment, SLICED_BOTTOM)
            assert _at(bottoms, expected), (
                f"#sliced: no bottom line under fragment {number} at {expected}:\n"
                f"{_describe(shapes)}"
            )


# ---------------------------------------------------------------------------
# A hostile realm
# ---------------------------------------------------------------------------


def _slide_root_fixture(name: str, *, script: str = "") -> str:
    """A slide-root fixture with the pseudo-element rules in its stylesheet, ``script`` after it."""
    html = (SLIDE_ROOT_FIXTURE_DIR / f"{name}.html").read_text(encoding="utf-8")
    assert html.count("</style>") == 1, f"fixture drift: {name}.html has no single stylesheet"
    return html.replace("</style>", HOSTILE_PSEUDO_RULES + "</style>\n" + script, 1)


def _export_document(monkeypatch: pytest.MonkeyPatch, html: str) -> tuple[bytes, list[dict]]:
    """Export one complete document with the snapshot engine, bounded so a hang fails in seconds."""
    monkeypatch.setenv("HUASHU_PIPELINE_ENABLED", "1")
    monkeypatch.setenv("TELLR_EXPORT_ENGINE", "snapshot")
    monkeypatch.setattr(
        pptx_from_html_huashu, "SIDECAR_TIMEOUT_SECONDS", HOSTILE_EXPORT_TIMEOUT_SECONDS
    )
    return pptx_from_html_huashu.build_pptx_huashu(
        "snapshot pseudo-elements", [{"html": html}], bypass_validation=True
    )


def _assert_pseudo_content(shapes: list[Shape], swatch: dict, what: str) -> None:
    """The heading's ``::before`` text and the prose's ``::after`` swatch are on the slide."""
    texts = [_normalised(shape.text) for shape in shapes if shape.kind == "text"]
    assert any(HOSTILE_HEADING_TEXT in text for text in texts) and any(
        HOSTILE_BEFORE_TEXT in text for text in texts
    ), (
        f"{what}: the slide's text is {texts}; the heading's ::before puts "
        f"{HOSTILE_BEFORE_TEXT!r} on screen before {HOSTILE_HEADING_TEXT!r}:\n{_describe(shapes)}"
    )
    swatches = [
        position
        for position in _at(shapes, swatch)
        if shapes[position].kind == "shape" and shapes[position].fill == ACCENT
    ]
    assert len(swatches) == 1, (
        f"{what}: no FF5F46 swatch at the prose's ::after box {_rect(swatch)}:\n{_describe(shapes)}"
    )


@pytest.mark.slow
@requires_huashu_sidecar
class TestPseudoElementsInAHostileRealm:
    def test_a_realm_that_lies_about_its_nodes_exports_as_a_benign_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``hostile_text_nodes`` with pseudo-elements exports as its benign twin with them.

        Its slide script replaces every node-level read (``firstChild`` and
        ``nextSibling`` return the node itself, ``childNodes`` claims a billion
        entries, ``textContent`` and ``data`` return a decoy). Pseudo-elements
        are read from outside the page's realm, so none of that reaches them:
        the export completes within the hostile bound, and its whole artifact
        equals the benign twin's, which shows the heading's ``::before`` text
        and the prose's ``::after`` swatch.
        """
        benign_html = _slide_root_fixture(BENIGN_TWIN)
        swatch = browser_each_pseudo(benign_html, ".prose", "after")[0]
        assert swatch is not None and abs(swatch["w"] - HOSTILE_SWATCH_SIDE_PX) < 0.01, (
            f"fixture drift: the prose's ::after is {_rect(swatch)}"
        )

        benign, benign_failures = _export_document(monkeypatch, benign_html)
        hostile, hostile_failures = _export_document(
            monkeypatch, _slide_root_fixture(HOSTILE_TEXT_NODES)
        )

        assert benign and benign_failures == [], (
            f"the benign twin did not export: {benign_failures}"
        )
        assert hostile and hostile_failures == [], (
            f"the hostile deck did not export: {hostile_failures}"
        )
        _assert_pseudo_content(slide_shapes(benign), swatch, "the benign twin")
        assert structural_manifest(hostile) == structural_manifest(benign), (
            "the hostile deck's pseudo-elements do not export as its benign twin's:\n"
            f"hostile:\n{_describe(slide_shapes(hostile))}\nbenign:\n{_describe(slide_shapes(benign))}"
        )

    def test_a_style_that_lies_about_its_length_cannot_stall_the_read(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every ``CSSStyleDeclaration`` claims a billion properties; the read stays bounded.

        A pseudo-element's computed style, read through the page's own
        declaration, has a ``length`` slide script can replace. The export
        completes within the hostile bound, and the pseudo-elements are still
        exported from their real computed style: the heading's ``::before``
        text and the prose's ``::after`` swatch at its browser box.
        """
        html = _slide_root_fixture(BENIGN_TWIN, script=LYING_STYLE_LENGTH_SCRIPT)
        report = json.loads(browser_text(html, "title"))
        assert report["redefineResult"] == "ok" and report["configurable"] and report["bites"], (
            f"fixture drift: the length replacement did not take: {report}"
        )
        swatch = browser_each_pseudo(html, ".prose", "after")[0]
        assert swatch is not None, "fixture drift: the prose has no ::after swatch"

        pptx, failures = _export_document(monkeypatch, html)

        assert pptx and failures == [], f"the export did not complete: {failures}"
        _assert_pseudo_content(slide_shapes(pptx), swatch, "the lying-length deck")
