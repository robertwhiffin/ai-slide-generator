"""Snapshot engine: native, editable tables.

A ``<table>`` whose cells hold text, with any inline formatting, becomes one
native PowerPoint table: a ``p:graphicFrame`` holding ``a:tbl``, editable in
PowerPoint and after Drive converts it for Google Slides. Its grid is the
browser's own:

* the column and row lines are where the browser put the cells' edges, each on
  the whole px nearest it (as Chrome paints a box edge, so abutting fills meet
  on a pixel and show no seam), so each ``gridCol`` width and ``a:tr`` height is
  the browser's to within a px, and the frame stands at the table's rect;
* ``colspan`` is a cell with ``gridSpan`` and ``hMerge`` placeholders after it;
  ``rowspan`` a cell with ``rowSpan`` and ``vMerge`` placeholders below it, its
  text written once;
* a cell's margin on each side (``marL`` ``marR`` ``marT`` ``marB``) is its
  padding plus half the collapsed border on that side, from the browser's cell
  edge, which is where the browser puts the cell's content. The margins go in
  the unit pptxgenjs reads them in: it reads all four as points when the TOP
  one is at least 1, and as inches otherwise, so a cell whose top margin is an
  inch or more passes points, and every other cell inches, uncapped;
* ``vertical-align`` is the cell's ``anchor`` (``t``, ``ctr``, ``b``);
* the fill is the cell's own, else its row's, else its row group's; the
  table's own background (and its radius and shadow) is a shape under the
  frame;
* under ``border-collapse: collapse`` every shared edge has ONE line, the
  winner CSS 2.1 picks: ``hidden`` over anything; then the wider border; on
  equal widths the style (double over solid over dashed over dotted); then
  the origin (a cell's border over its row's); then the cell further up, and
  further left (right, in a right-to-left table). That winner is written on
  BOTH cells' sides. Neither PowerPoint nor Drive then
  sees one cell's ``noFill`` contradicting its neighbour's line. Every cell
  writes all four sides, a dotted one ``sysDot`` (pptxgenjs writes only solid
  and ``sysDash``, so the deck's XML is rewritten for it);
* under ``border-collapse: separate`` with no spacing, two cells' borders
  that meet paint side by side: alike, they are one line as wide as both;
  in different colours, no ``a:tbl`` edge draws them;
* the text runs follow the text-block rules (weights as named faces, bold
  only at 700, colours).

What sits in a cell and is no text (a Harvey ball's picture, a delta pill's
shape, a cell's ``::before`` dot) is its own item, overlaid on the table at its
browser rect inside its cell. A cell whose line holds such an atomic inline
gives up its native text: the line's text is overlay text items, and the
cell's ``a:tc`` holds none, so nothing is written twice. So does a cell holding
block layout (a ``<div>``, a ``<p>``, a float), whose content is overlaid at its
measured place, and a cell whose own overflow clip cuts its text, whose
overlays are cut as any others are: the table stays native, the cell's fill
and borders on its ``a:tc``. Text and boxes the table owns appear nowhere else.

A table is emitted as positioned items instead (cell boxes as shapes, cell
text as text items, all still editable) when ``a:tbl`` cannot draw it: it
holds a nested table, or its cells stand apart (``border-collapse: separate``
with visible ``border-spacing``: a filled or bordered cell, whose gaps no
``a:tbl`` has), or two separated borders side by side differ. Spacing nothing
shows (no cell fill, no cell border) keeps it
native. So is a table an ancestor's clip cuts (an ``a:tbl`` cannot be
clipped): its items are clipped as any others are, and what the clip hides is
absent. A ``<caption>`` is no grid cell: it is a text item at its rendered
rect, above the frame or, with ``caption-side: bottom``, below it.

Every assertion reads the emitted slide XML (``slide_shapes``: the ``a:tbl``
grid, each ``a:tc`` with its spans, margins, anchor, borders, fill and runs) and
holds it against the browser's rendering of the very same document:
``browser_tables`` reads every cell's box, grid slot, spans, padding and text
style from one page load, and ``browser_pixels`` what the screen shows on a
collapsed edge, which is the only place the winner of an edge is visible.
Corpus slides 04 (the Harvey-ball scorecard and its source line), 05 (the
balance sheet's two tables), 06 (the delta-pills table beside the "So what"
callout) and 15 (the dense zebra table with badges) are loaded by prefix; the
other cases are small inline documents. One case converts through Drive and
reads the Slides API's table borders back. It runs only with
``TELLR_GOOGLE_TESTS=1`` and gcloud application-default credentials, and it
deletes the presentation it created once it has read it.

Gating matches the sibling export suites: needs node, the extracted sidecar
``node_modules`` and a local Chrome/Chromium (skipped otherwise).
"""

from __future__ import annotations

import json
import math
import re
import subprocess
from collections import Counter
from collections.abc import Callable, Iterator
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from src.services import pptx_from_html_huashu
from tests.fixtures.export_snapshot_support import (
    DECK_CSS,
    EMU_PER_PX,
    NAMESPACES,
    Border,
    BrowserBorder,
    BrowserCell,
    BrowserTable,
    Cell,
    Shape,
    browser_ascent,
    browser_each_pseudo,
    browser_each_rect,
    browser_line_boxes,
    browser_padding_box,
    browser_pixels,
    browser_rect,
    browser_style,
    browser_tables,
    browser_text,
    corpus_document,
    delete_drive_file,
    export_corpus,
    export_documents,
    export_slides,
    fidelity_harness,
    google_slides_presentation,
    node_json,
    overlaps,
    requires_google_slides,
    requires_huashu_sidecar,
    run_node,
    single_line_box_top,
    slide_document,
    slide_shape_elements,
    slide_shapes,
    slide_text_loss,
    slides_api_cell_text,
    slides_api_color,
    slides_api_tables,
    table_cell_rect,
    table_column_edges,
    table_extent,
    table_frames,
    table_row_edges,
    table_slot_owner,
)
from tests.unit.test_export_collection_iteration_hostile_realm import (
    HOSTILE_EXPORT_TIMEOUT_SECONDS,
)
from tests.unit.test_export_slide_root_background import FIXTURE_DIR as SLIDE_ROOT_FIXTURE_DIR

# The grid, the frame and every overlaid item match the browser's rects within 1 px.
RECT_TOLERANCE_PX = 1.0
# An item "inside" a rect may touch its edge, give or take EMU rounding.
INSIDE_TOLERANCE_PX = 0.5
# A margin equals its expected size within 1 % of it (EMU rounding is far
# finer), and within this much where 1 % is less.
MARGIN_TOLERANCE_FRACTION = 0.01
MARGIN_TOLERANCE_FLOOR_PX = 0.05
PX_PER_INCH = 96.0
PT_PER_PX = 0.75
WIDTH_TOLERANCE_PT = 0.01
ALPHA_TOLERANCE = 0.005
# A CSS border-spacing above this on either axis is a gap the eye sees.
VISIBLE_SPACING_PX = 0.5
# The Slides API states border weights in EMU.
EMU_PER_PT = 12700
WEIGHT_TOLERANCE_EMU = 127

TRANSPARENT = "rgba(0, 0, 0, 0)"
CSS_COLOUR = re.compile(r"rgba?\(\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\s*\)")
# How the browser serialises text-align, by the paragraph alignment it means (left to right).
PARAGRAPH_ALIGNMENT = {
    "start": "left",
    "left": "left",
    "-webkit-left": "left",
    "right": "right",
    "end": "right",
    "-webkit-right": "right",
    "center": "center",
    "-webkit-center": "center",
    "justify": "justify",
}
# The a:tcPr anchor each vertical-align gives; top is also the OOXML default, written or not.
ANCHORS = {"top": ("t", None), "middle": ("ctr",), "bottom": ("b",)}
SIDES = ("top", "right", "bottom", "left")

# ---------------------------------------------------------------------------
# Corpus slides
# ---------------------------------------------------------------------------

# Fixture 05: two balance-sheet tables side by side in a two-column grid.
BALANCE_TABLES = "table.dk-bs"
SECTION_LABELS = ("Current assets", "Non-current assets", "Liabilities")
# Each table's total row, whose top edge it shares with the row above it.
TOTAL_LABELS = ("Total current assets", "Total liabilities")
GRAND_LABELS = ("Total assets", "Total liabilities and equity")
HEADER_FILL = "FF5F46"
INK = "1B3139"
RULE = "DCE0E2"
WHITE = "FFFFFF"
ACCENT = "FF5F46"
# .dk-bs tr.indent td:first-child { padding-left: 26px }
INDENT_PADDING_PX = 26.0
# The colours that meet on a total row's top edge: the row above's own bottom
# rule and the total row's own top border, both 1 px solid. On equal widths and
# styles CSS gives the edge to the cell earlier in the document, so the browser
# paints the rule there, not the total's ink: the screen decides, and the
# export follows it.
TOTAL_EDGE_CANDIDATES = {RULE, INK}

# Fixture 04: the Harvey-ball scorecard, then its source line (a <p>).
SCORECARD_TABLE = "table.dk-table"
SOURCE_LINE = ".dk-source"
SOURCE_TEXT = "Source: Illustrative (fictional)."
HARVEY = ".dk-harvey"
HARVEY_COUNT = 8
ROW_LABELS = ("Liquidity", "Leverage", "Profitability", "Working-capital efficiency")
VERDICT_TEXT = "Strength \u00b7 current ratio 2.47x, up from 2.17x"
VERDICT_STRONG = "Strength"
VERDICT_STRONG_SELECTOR = ".dk-table tbody tr:first-child td:last-child strong"
HIGHLIGHT_BACKGROUND = "rgba(255, 95, 70, 0.1)"
HIGHLIGHT_FILL = "FF5F46"
HIGHLIGHT_ALPHA = 0.10
HIGHLIGHT_COLUMN = 2

# Fixture 06: the measures table beside the "So what" callout.
PILLS_TABLE = "table.dk-table"
CALLOUT = ".dk-callout"
CALLOUT_FILL = INK
DELTA_PILL = ".dk-pill"
DELTA_PILLS = ("\u25b2 0.30x", "\u25b2 0.32x", "\u25bc 0.17x", "\u25b2 2.7x")
CHANGE_COLUMN = 3
MEASURE_LABELS = ("Current ratio", "Quick ratio", "Debt-to-equity", "Interest coverage")

# Fixture 15: one dense table, zebra rows filled by their <tr>, a badge per row.
DENSE_TABLE = "table.dk-bs"
DENSE_BADGES = (
    "\u25b2 10.7%",
    "\u25bc 7.4%",
    "\u25b2 17.4%",
    "\u25bc 10.4%",
    "\u25b2 33.8%",
    "\u25b2 44.0%",
)
DENSE_CHANGE_COLUMN = 3
ZEBRA_FILL = "F1EFEB"
# The slide's ground (deck.css --paper): a cell it shows through is unfilled.
PAPER = "F9F7F4"

# ---------------------------------------------------------------------------
# Inline documents, one slide each
# ---------------------------------------------------------------------------

TABLES_CSS = (
    DECK_CSS
    + """
.ruled { position: absolute; border-collapse: collapse; font-size: 18px; }
.ruled th, .ruled td { padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--rule); }
.ruled th { font-weight: 600; }
.ruled .num { text-align: right; font-family: var(--mono); }
.ruled caption { font-size: 14px; color: var(--ink-2); text-align: left; padding: 6px 0; }
.boxed { border-collapse: collapse; font-size: 15px; }
.boxed td { padding: 4px 8px; border: 1px solid var(--rule); }
.edges { position: absolute; border-collapse: collapse; font-size: 18px; }
.edges td { padding: 10px 14px; }
.edges tr.first td { border-bottom: 1px solid #DCE0E2; }
.edges tr.total td { border-top: 2px solid #1B3139; border-bottom: 2px dashed #FF5F46; }
.edges tr.after td { border-top: 2px solid #00A972; }
.edges td:first-child { border-right: 1px solid #5A6F77; }
.edges td + td { border-left: 1px solid #FF3621; }
#cards { position: absolute; border-collapse: separate; border-spacing: 8px; font-size: 18px; }
#cards td { background: #FFFFFF; border-radius: 10px; padding: 14px 18px; }
.rounded-table { border-collapse: collapse; width: 100%; font-size: 16px; }
.rounded-table th { background: #FF5F46; color: #fff; text-align: left; padding: 13px 18px; }
.rounded-table td { padding: 13px 18px; }
.rounded-table tbody tr:nth-child(odd) { background: #fff; }
.rounded-table tbody tr:nth-child(even) { background: #F3F3F3; }
.rounded-table tr.rule td { height: 1px; padding: 0; background: #DCE0E2;
                            font-size: 0; line-height: 0; }
.rounded-table.fixed-grid { table-layout: fixed; }
.rounded-table.fixed-grid tr { height: 50px; }
#plain { position: absolute; font-size: 18px; background: #FFFFFF; border-radius: 12px;
         box-shadow: 0 2px 8px rgba(27, 49, 57, 0.12); }
#plain th, #plain td { padding: 10px 16px; text-align: left; }
.origin { position: absolute; border-collapse: collapse; font-size: 18px; }
.origin td { padding: 10px 14px; }
.origin tr.above { border-bottom: 2px solid #FF5F46; }
.origin tr.below td { border-top: 2px solid #1B3139; }
.clipbox { position: absolute; overflow: hidden; width: 560px; }
.clipped { border-collapse: collapse; font-size: 18px; width: 520px; }
.clipped th, .clipped td { padding: 8px 12px; text-align: left;
                           border-bottom: 1px solid var(--rule); }
.clipped tr.tall td { height: 80px; background: #F1EFEB; }
.hidden-edge { position: absolute; border-collapse: collapse; font-size: 18px;
               background: #FFFFFF; }
.hidden-edge td { padding: 10px 14px; }
.hidden-edge tr.upper td { border-bottom: 4px solid #1B3139; }
.hidden-edge tr.lower td { border-top: hidden; }
.rtl-edge { position: absolute; border-collapse: collapse; font-size: 18px; direction: rtl; }
.rtl-edge td { padding: 10px 14px; }
.rtl-edge td:first-child { border-left: 2px solid #FF5F46; }
.rtl-edge td + td { border-right: 2px solid #1B3139; }
.colrow { position: absolute; border-collapse: collapse; font-size: 18px; }
.colrow td { padding: 10px 14px; }
.colrow col.first { border-left: 4px solid #FF5F46; }
.colrow tr { border-left: 4px solid #1B3139; }
.ruled .sub { font-size: 13px; color: var(--ink-2); }
.dots { position: absolute; border-collapse: collapse; font-size: 18px; }
.dots td { padding: 8px 12px; border-bottom: 1px solid var(--rule); }
#dots-inline td:first-child::before { content: ''; display: inline-block; width: 8px; height: 8px;
  border-radius: 50%; background: #FF5F46; margin-right: 8px; }
#dots-absolute td:first-child { padding-left: 28px; }
#dots-absolute td:first-child::before { content: ''; position: absolute; margin-left: -16px;
  margin-top: 8px; width: 8px; height: 8px; border-radius: 50%; background: #FF5F46; }
.loose { position: absolute; border-collapse: collapse; font-size: 18px; table-layout: fixed; }
.loose td { padding: 8px 12px; border-bottom: 1px solid var(--rule); }
#relative td { position: relative; }
#overflow td.ellipsis { overflow: hidden; text-overflow: clip; white-space: nowrap; }
#overflow td.fits { overflow: hidden; }
.grad { position: absolute; border-collapse: collapse; font-size: 18px;
        background: linear-gradient(90deg, #FFFFFF, #F1EFEB); border: 3px solid #1B3139; }
.grad td { padding: 8px 12px; border-bottom: 1px solid #DCE0E2; }
.foreign td { display: table-cell; padding: 8px 12px; }
#area td { padding: 0; }
.doubled { position: absolute; border-collapse: separate; border-spacing: 0; font-size: 18px; }
.doubled td { padding: 10px 14px; }
.doubled tr.upper td { border-bottom: 2px solid #1B3139; }
#alike tr.lower td { border-top: 2px solid #1B3139; }
#unlike tr.lower td { border-top: 2px solid #FF5F46; }
.snap { position: absolute; border-collapse: collapse; font-size: 17.3px; background: #F7F5F2; }
.snap th { background: #FF5F46; color: #FFFFFF; padding: 9.3px 13.4px; text-align: left; }
.snap td { padding: 7.7px 13.4px; border-bottom: 1px solid #DCE0E2; }
.snap tr.total td { background: #1B3139; color: #FFFFFF; border-bottom: 0; }
#snap-tie td { border-bottom: 0; }
#snap-tie tr.ruled-half td:last-child { border-bottom: 1px solid #DCE0E2; }
.ground-table { border-collapse: collapse; width: 100%; font-size: 16px; background: #F3F3F3; }
.ground-table td { padding: 13px 18px; }
.dotted { position: absolute; border-collapse: collapse; font-size: 18px; }
.dotted td { padding: 10px 14px; }
.dotted tr.first td { border-bottom: 2px dotted #1B3139; }
.dotted tr.second td { border-bottom: 2px dashed #FF5F46; }
.dotted td + td { border-left: 1px dotted #5A6F77; }
.app-rows { position: absolute; border-collapse: collapse; width: 360px; }
.app-rows th { font-size: 12px; font-weight: 700; text-transform: uppercase; text-align: left;
               padding: 6px 10px; border-bottom: 2px solid #1B3139; }
.app-rows td { padding: 6px 10px; border-bottom: 1px solid #E3E7E8; }
#rows-sans { font-family: Inter, 'SF Pro Display', Helvetica, Arial, sans-serif; font-size: 15px; }
#rows-tight { font-family: Arial, sans-serif; font-size: 16px; line-height: 1.0; }
#rows-tight td { vertical-align: top; }
#rows-loose { font-family: 'DM Sans', sans-serif; font-size: 15px; }
.double-rows { position: absolute; border-collapse: collapse; width: 360px;
               font: 15px Arial, sans-serif; color: #2B3940; }
.double-rows td { padding: 6px 10px; border-bottom: 1px solid #E3E7E8; }
.double-rows tr.total td { font-weight: 800; border-top: 2px solid #102025;
                           border-bottom: 3px double #102025; }
.double-rows tr.net td { border-bottom: 6px double #EB4A34; }
.double-rows tr.thin td { border-bottom: 2px double #3C71AF; }
.cell-rounds { position: absolute; border-collapse: collapse; width: 480px; font-size: 16px; }
.cell-rounds th { background: #FF5F46; color: #FFFFFF; text-align: left; padding: 13px 18px; }
.cell-rounds td { padding: 13px 18px; }
.cell-rounds tbody tr:nth-child(odd) { background: #FFFFFF; }
.cell-rounds tbody tr:nth-child(even) { background: #F3F3F3; }
.cell-rounds th:first-child { border-top-left-radius: 8px; }
.cell-rounds th:last-child { border-top-right-radius: 8px; }
.hl-table { position: absolute; border-collapse: collapse; width: 560px; font-size: 15px; }
.hl-table th { background: #FF5F46; color: #FFFFFF; text-align: left; padding: 12px 16px; }
.hl-table th.hl { background: #102025; }
.hl-table td { padding: 12px 16px; border-bottom: 1px solid #DCE0E2; }
.hl-table tbody tr:nth-child(odd) { background: #FFFFFF; }
.hl-table tbody tr:nth-child(even) { background: #F3F3F3; }
.hl-table .hl-cell { box-shadow: inset 2px 0 0 #EB4A34, inset -2px 0 0 #EB4A34; }
"""
)

CAPTION_BODY = """<div class="slide">
  <p class="dk-eyebrow">Captions</p>
  <table id="cap-top" class="ruled" style="left: 88px; top: 160px; width: 480px;">
    <caption>Revenue by region ($M)</caption>
    <thead><tr><th>Region</th><th class="num">FY24</th></tr></thead>
    <tbody>
      <tr><td>EMEA</td><td class="num">412.0</td></tr>
      <tr><td>Americas</td><td class="num">655.0</td></tr>
    </tbody>
  </table>
  <table id="cap-bottom" class="ruled"
         style="left: 680px; top: 160px; width: 480px; caption-side: bottom;">
    <caption>Source: regional ledgers</caption>
    <thead><tr><th>Segment</th><th class="num">FY24</th></tr></thead>
    <tbody>
      <tr><td>Industrial</td><td class="num">632.4</td></tr>
      <tr><td>Automotive</td><td class="num">359.6</td></tr>
    </tbody>
  </table>
</div>"""
# Each captioned table: its caption's text, and where the caption renders.
CAPTIONS = {
    "#cap-top": ("Revenue by region ($M)", "top"),
    "#cap-bottom": ("Source: regional ledgers", "bottom"),
}

ROWSPAN_BODY = """<div class="slide">
  <table id="rowspan" class="ruled" style="left: 88px; top: 120px; width: 600px;">
    <thead><tr><th>Segment</th><th>Quarter</th><th class="num">Revenue</th></tr></thead>
    <tbody>
      <tr><td rowspan="2">Industrial</td><td>Q1</td><td class="num">120.0</td></tr>
      <tr><td>Q2</td><td class="num">131.5</td></tr>
      <tr><td>Automotive</td><td>Q1</td><td class="num">88.2</td></tr>
    </tbody>
  </table>
</div>"""
ROWSPAN_LABEL = "Industrial"
# Its grid slot: the first body row (the header is row 0), first column.
ROWSPAN_SLOT = (1, 0)

VALIGN_BODY = """<div class="slide">
  <table id="valign" class="ruled" style="left: 88px; top: 120px; width: 800px;">
    <tbody><tr>
      <td style="height: 140px;">A tall cell sets the row</td>
      <td style="vertical-align: top;">Top</td>
      <td style="vertical-align: middle;">Middle</td>
      <td style="vertical-align: bottom;">Bottom</td>
    </tr></tbody>
  </table>
</div>"""
# The grid column of each aligned cell, by its vertical-align.
VALIGN_COLUMNS = {"top": 1, "middle": 2, "bottom": 3}

MARGINS_BODY = """<div class="slide">
  <table id="margins" class="ruled" style="left: 88px; top: 100px; width: 520px;">
    <tbody>
      <tr><td style="padding: 100px 12px 8px 30px; border: 0;">Deep top padding</td></tr>
      <tr><td style="padding: 8px 12px 8px 120px; border: 0;">Wide left padding</td></tr>
    </tbody>
  </table>
</div>"""
# Each row's one cell: its padding (top, right, bottom, left) in px. The first
# has an inch or more on top, so its margins go to pptxgenjs in points; the
# second has under an inch on top and 1.25 in on the left, which goes in
# inches, uncapped.
MARGIN_PADDINGS = {0: (100.0, 12.0, 8.0, 30.0), 1: (8.0, 12.0, 8.0, 120.0)}

COLLAPSE_BODY = """<div class="slide">
  <table id="collapse" class="edges" style="left: 88px; top: 120px; width: 640px;">
    <tbody>
      <tr class="first"><td>Revenue</td><td>1,240.0</td></tr>
      <tr class="total"><td>Gross profit</td><td>434.0</td></tr>
      <tr class="after"><td>Gross margin</td><td>35.0%</td></tr>
    </tbody>
  </table>
</div>"""
# The shared edges whose winner CSS decides three different ways, and the
# colour and width (px) the browser paints on each (a guard: the screen is read regardless).
#   along the top of row 1: 1 px solid DCE0E2 against 2 px solid 1B3139, the wider wins;
#   along the top of row 2: 2 px dashed FF5F46 against 2 px solid 00A972, solid wins;
#   along the left of column 1: 1 px solid 5A6F77 against 1 px solid FF3621, the
#   earlier (left) cell wins.
COLLAPSE_ROW_EDGES = {1: ("1B3139", 2.0), 2: ("00A972", 2.0)}
COLLAPSE_COLUMN_EDGES = {1: ("5A6F77", 1.0)}

CARDS_BODY = """<div class="slide">
  <table id="cards" style="left: 88px; top: 120px; width: 760px;">
    <tbody>
      <tr><td>Unity Catalog</td><td>Governs every table</td></tr>
      <tr><td>Lakeflow</td><td>Runs the pipelines</td></tr>
    </tbody>
  </table>
</div>"""
CARD_FILL = WHITE

PLAIN_BODY = """<div class="slide">
  <table id="plain" style="left: 88px; top: 120px;">
    <tbody>
      <tr><th>Region</th><th>FY24</th><th>FY23</th></tr>
      <tr><td>EMEA</td><td>412.0</td><td>389.5</td></tr>
      <tr><td>Americas</td><td>655.0</td><td>610.2</td></tr>
    </tbody>
  </table>
</div>"""
PLAIN_FILL = WHITE

NESTED_BODY = """<div class="slide">
  <table id="outer" class="ruled" style="left: 88px; top: 120px; width: 900px;">
    <thead><tr><th>Programme</th><th>Detail</th></tr></thead>
    <tbody>
      <tr><td>Platform</td><td>
        <table id="inner" class="boxed"><tbody>
          <tr><td>Unity Catalog</td><td>GA</td></tr>
          <tr><td>Lakeflow</td><td>Preview</td></tr>
        </tbody></table>
      </td></tr>
      <tr><td>People</td><td>Hiring plan on track</td></tr>
    </tbody>
  </table>
</div>"""
OUTER_TEXTS = ("Programme", "Detail", "Platform", "People", "Hiring plan on track")

BLOCKS_BODY = """<div class="slide">
  <table id="blocks" class="ruled" style="left: 88px; top: 120px; width: 700px;">
    <thead><tr><th>Programme</th><th>Detail</th></tr></thead>
    <tbody>
      <tr><td>Platform</td><td id="block-cell"><div id="block-first">Unity Catalog</div><div
        id="block-second" class="sub">Governs every table and model</div></td></tr>
      <tr><td>People</td><td>Hiring plan on track</td></tr>
    </tbody>
  </table>
  <table id="trap" class="ruled" style="left: 88px; top: 380px; width: 700px;">
    <tbody>
      <tr><td>Segment</td><td id="trap-cell">Revenue<div class="sub">FY24 restated</div></td></tr>
      <tr><td>Industrial</td><td>632.4</td></tr>
    </tbody>
  </table>
</div>"""
# A cell holding two stacked <div>s: block layout, which keeps the table native
# and is overlaid at its measured place.
BLOCKS_TABLE = "#blocks"
BLOCK_CELL_SLOT = (1, 1)
BLOCK_TEXTS = (
    ("#block-first", "Unity Catalog"),
    ("#block-second", "Governs every table and model"),
)
# A cell's own text with no white space before the block that follows it: the
# text is an anonymous block of the cell, overlaid once, never its a:tc paragraph.
TRAP_TABLE = "#trap"
TRAP_CELL = "#trap-cell"
TRAP_SLOT = (0, 1)
# Each of the cell's lines, and the element its text is set in.
TRAP_LINES = (("Revenue", TRAP_CELL), ("FY24 restated", f"{TRAP_CELL} .sub"))

FILLS_BODY = """<div class="slide">
  <table id="fills" class="ruled"
         style="left: 88px; top: 120px; width: 700px; background: #FFFFFF;">
    <thead style="background: #1B3139; color: #FFFFFF;">
      <tr><th>Line</th><th class="num">FY24</th><th class="num">FY23</th></tr>
    </thead>
    <tbody>
      <tr><td>Revenue</td><td class="num">1,240.0</td><td class="num">1,120.0</td></tr>
      <tr style="background: #F1EFEB;">
        <td>Cost of goods sold</td>
        <td class="num" style="background: #FFE3DE;">806.0</td>
        <td class="num">750.4</td>
      </tr>
    </tbody>
  </table>
</div>"""
# The colour each cell shows, by grid slot: the row group's for the header, the
# table's own (a shape under the frame) for the Revenue row, the row's for the
# zebra row except where its cell has its own.
FILLS_SHOWN = {
    (0, 0): INK,
    (0, 1): INK,
    (0, 2): INK,
    (1, 0): WHITE,
    (1, 1): WHITE,
    (1, 2): WHITE,
    (2, 0): "F1EFEB",
    (2, 1): "FFE3DE",
    (2, 2): "F1EFEB",
}
# What each cell's a:tc must be filled with: the table's own fill is not a cell
# fill (an unfilled cell over the white shape shows white, as does one filled white).
FILLS_EMITTED = {
    slot: ((None, WHITE) if shown == WHITE else (shown,)) for slot, shown in FILLS_SHOWN.items()
}
FILLS_TABLE_FILL = WHITE

ORIGIN_BODY = """<div class="slide">
  <table id="origin" class="origin" style="left: 88px; top: 120px; width: 640px;">
    <tbody>
      <tr class="above"><td>Revenue</td><td>1,240.0</td></tr>
      <tr class="below"><td>Gross profit</td><td>434.0</td></tr>
    </tbody>
  </table>
</div>"""
# Along the top of row 1: the row above's own 2 px solid FF5F46 (a <tr> border)
# against the cell's own 2 px solid 1B3139. Equal width and style, so origin
# decides before position: the cell beats the row, though the row is further up.
ORIGIN_ROW_BORDER = "FF5F46"
ORIGIN_CELL_BORDER = "1B3139"
ORIGIN_EDGE_ROW = 1

CLIP_BODY = """<div class="slide">
  <div id="cut-box" class="clipbox" style="left: 88px; top: 120px; height: 170px;">
    <table id="cut" class="clipped">
      <thead><tr><th>Line</th><th>FY24</th></tr></thead>
      <tbody>
        <tr><td>Revenue</td><td>1,240.0</td></tr>
        <tr><td>Gross profit</td><td>434.0</td></tr>
        <tr class="tall">
          <td style="vertical-align: top;"><span id="cut-shown">Shown above the cut</span></td>
          <td style="vertical-align: bottom;"><span id="cut-hidden">Hidden below the cut</span></td>
        </tr>
      </tbody>
    </table>
  </div>
  <div id="whole-box" class="clipbox" style="left: 680px; top: 120px; height: 300px;">
    <table id="whole" class="clipped">
      <thead><tr><th>Segment</th><th>FY24</th></tr></thead>
      <tbody>
        <tr><td>Industrial</td><td>632.4</td></tr>
        <tr><td>Automotive</td><td>359.6</td></tr>
        <tr class="tall">
          <td style="vertical-align: top;">Aerospace</td>
          <td style="vertical-align: bottom;">148.8</td>
        </tr>
      </tbody>
    </table>
  </div>
</div>"""
# The overflow: hidden box whose bottom cuts the last row of #cut in half: the
# row's top-aligned text shows, its bottom-aligned text lies wholly below the cut.
CUT_BOX = "#cut-box"
CUT_SHOWN = "#cut-shown"
CUT_HIDDEN = "#cut-hidden"
CUT_TEXTS_SHOWN = (
    "Line",
    "FY24",
    "Revenue",
    "1,240.0",
    "Gross profit",
    "434.0",
    "Shown above the cut",
)
CUT_TEXT_HIDDEN = "Hidden below the cut"
CUT_ROW_FILL = "F1EFEB"
# The same table, whole inside an overflow: hidden box tall enough to hold it.
WHOLE_BOX = "#whole-box"

PRECEDENCE_BODY = """<div class="slide">
  <table id="hidden-edge" class="hidden-edge" style="left: 88px; top: 120px; width: 480px;">
    <tbody>
      <tr class="upper"><td>Revenue</td><td>1,240.0</td></tr>
      <tr class="lower"><td>Gross profit</td><td>434.0</td></tr>
    </tbody>
  </table>
  <table id="rtl-edge" class="rtl-edge" style="left: 680px; top: 120px; width: 480px;">
    <tbody>
      <tr><td>Revenue</td><td>1,240.0</td></tr>
      <tr><td>Gross profit</td><td>434.0</td></tr>
    </tbody>
  </table>
  <table id="colrow" class="colrow" style="left: 88px; top: 360px; width: 480px;">
    <colgroup><col class="first"><col></colgroup>
    <tbody>
      <tr><td>Operating income</td><td>148.8</td></tr>
      <tr><td>Net income</td><td>97.8</td></tr>
    </tbody>
  </table>
</div>"""
# Along the table's left edge: the first column's own 4 px solid FF5F46 left
# border against each row's own 4 px solid 1B3139 left border. Equal width and
# style, so origin decides: a row beats a column.
COLROW_TABLE = "#colrow"
COLROW_WINNER = (INK, 4.0)
COLROW_LOSER = ACCENT
# Along the top of row 1: the upper cells' own 4 px solid 1B3139 bottom against
# the lower cells' border-top: hidden. hidden wins before width: no line.
HIDDEN_EDGE_TABLE = "#hidden-edge"
HIDDEN_EDGE_ROW = 1
HIDDEN_EDGE_LOSER = ("solid", 4.0, INK)
# A right-to-left table: each row's first cell is on the right. Along the edge
# between its columns the right cell's own left border (2 px solid FF5F46)
# against the left cell's own right border (2 px solid 1B3139): equal width,
# style and origin, so the cell further right (in right to left) wins.
RTL_EDGE_TABLE = "#rtl-edge"
RTL_EDGE_WINNER = (ACCENT, 2.0)

DOUBLED_BODY = """<div class="slide">
  <table id="alike" class="doubled" style="left: 88px; top: 120px; width: 480px;">
    <tbody>
      <tr class="upper"><td>Revenue</td><td>1,240.0</td></tr>
      <tr class="lower"><td>Gross profit</td><td>434.0</td></tr>
    </tbody>
  </table>
  <table id="unlike" class="doubled" style="left: 680px; top: 120px; width: 480px;">
    <tbody>
      <tr class="upper"><td>Operating income</td><td>148.8</td></tr>
      <tr class="lower"><td>Net income</td><td>97.8</td></tr>
    </tbody>
  </table>
</div>"""
# border-collapse: separate, border-spacing: 0: along the top of row 1 the upper
# cells' own 2 px solid 1B3139 bottoms and the lower cells' own 2 px tops paint
# side by side. In #alike both are 1B3139, one 4 px rule; in #unlike the lower
# ones are FF5F46, two lines.
ALIKE_TABLE = "#alike"
UNLIKE_TABLE = "#unlike"
DOUBLED_ROW = 1
DOUBLED_SIDE_PX = 2.0
DOUBLED_WIDTH_TOLERANCE_PX = 0.5
# A line item lies along its band within this, and a text box at its browser line box.
LINE_TOLERANCE_PX = 1.0
LINE_BOX_TOLERANCE_PX = 1.0

DOTS_BODY = """<div class="slide">
  <table id="dots-inline" class="dots" style="left: 88px; top: 120px; width: 480px;">
    <tbody>
      <tr><td>On track</td><td>Platform</td></tr>
      <tr><td>At risk</td><td>People</td></tr>
    </tbody>
  </table>
  <table id="dots-absolute" class="dots" style="left: 680px; top: 120px; width: 480px;">
    <tbody>
      <tr><td>Shipped</td><td>Lakeflow</td></tr>
      <tr><td>Blocked</td><td>Hiring</td></tr>
    </tbody>
  </table>
</div>"""
# Each first cell's ::before status dot: an inline-block in its line, or out of
# the flow (position: absolute). Both are items of their own over the table.
DOT_TABLES = ("#dots-inline", "#dots-absolute")
DOT_FILL = ACCENT
# A dot's shape is its CDP box within this.
DOT_TOLERANCE_PX = 0.5

LOOSE_BODY = """<div class="slide">
  <table id="relative" class="loose" style="left: 88px; top: 120px; width: 480px;">
    <tbody>
      <tr><td>Revenue</td><td>1,240.0</td></tr>
      <tr><td>Gross profit</td><td>434.0</td></tr>
    </tbody>
  </table>
  <table id="overflow" class="loose" style="left: 680px; top: 120px; width: 480px;">
    <tbody>
      <tr><td>Programme</td><td id="ellipsis-cell" class="ellipsis"><span class="w">Unity</span>
        <span class="w">Catalog</span> <span class="w">governs</span> <span class="w">every</span>
        <span class="w">table,</span> <span class="w">view</span> <span class="w">and</span>
        <span class="w">model</span> <span class="w">across</span>
        <span class="w">clouds</span></td></tr>
      <tr><td>People</td><td id="fits-cell" class="fits">Hiring plan on track</td></tr>
    </tbody>
  </table>
</div>"""
RELATIVE_TABLE = "#relative"
OVERFLOW_TABLE = "#overflow"
ELLIPSIS_CELL = "#ellipsis-cell"
ELLIPSIS_WORDS = "#ellipsis-cell .w"
ELLIPSIS_WORD_TEXTS = (
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
ELLIPSIS_SLOT = (0, 1)
FITS_SLOT = (1, 1)
# A word a clip shows less than this of, along the axis it cuts, is not slide text.
MINIMUM_VISIBLE_PX = 2.0

CAPTURED_BODY = """<div class="slide">
  <table id="grad" class="grad" style="left: 88px; top: 120px; width: 640px;">
    <tbody>
      <tr><td>Revenue</td><td>1,240.0</td></tr>
      <tr><td>Gross profit</td><td>434.0</td></tr>
      <tr><td>Operating income</td><td>148.8</td></tr>
    </tbody>
  </table>
</div>"""
# A collapsed table whose own background is a gradient, so its box is a
# box-only picture under the frame: 1 px DCE0E2 rules between its rows and a
# 3 px 1B3139 border around it, which the a:tbl draws and the picture must not.
GRAD_TABLE = "#grad"
GRAD_BORDER = (INK, 3.0)
# A picture pixel is a colour within this per channel.
PIXEL_TOLERANCE = 8

# The design system's data table: a collapsed table filling an unfilled wrapper
# that rounds its corners by clipping (``border-radius: 8px; overflow: hidden``)
# and casts --shadow-sm. The corner cells' fills reach into the wrapper's
# rounded corners, which the browser clips away.
ROUNDED_WRAPPER = "#rounded-wrapper"
ROUNDED_RADIUS_PX = 8.0
ROUNDED_BODY = (
    '<div class="slide"><div id="rounded-wrapper" style="position: absolute; left: 88px; '
    "top: 160px; width: 900px; border-radius: 8px; overflow: hidden; "
    'box-shadow: 0 1px 2px rgba(27,49,57,.06), 0 1px 3px rgba(27,49,57,.08);">'
    '<table class="rounded-table"><thead><tr><th>Use case</th><th>Measurement</th>'
    "<th>Cost</th></tr></thead><tbody><tr><td>UC 1</td><td>Batch load</td><td>$184</td></tr>"
    "<tr><td>UC 2</td><td>DLT run</td><td>$142</td></tr></tbody></table></div></div>"
)
# Each slot's fill as the browser paints it: the header row coral, the body rows
# white, then F3F3F3.
ROUNDED_FILLS = (("FF5F46",) * 3, ("FFFFFF",) * 3, ("F3F3F3",) * 3)
# The slots the wrapper's corners cut: the grid's four corners.
ROUNDED_CORNERS = {
    (0, 0): "top-left",
    (0, 2): "top-right",
    (2, 0): "bottom-left",
    (2, 2): "bottom-right",
}
# The same wrapper laid out between pixels: its padding box, and so the table's
# first grid line, start 0.4 px below a whole px, which the grid snaps up to.
OFFSET_BODY = ROUNDED_BODY.replace("top: 160px;", "top: 160.4px;").replace(
    'id="rounded-wrapper"', 'id="offset-wrapper"'
)
# The same table in a wrapper whose padding keeps every cell clear of its corners.
CLEAR_BODY = ROUNDED_BODY.replace(
    "overflow: hidden; ", "overflow: hidden; padding: 12px; background: #FFFFFF; "
).replace('id="rounded-wrapper"', 'id="clear-wrapper"')
# The rounded data table with two translucent cells: the header's middle cell, and
# the first body row's middle cell, its row painting nothing. In the deck for Google
# Slides a corner cell's shape runs 1 px under each opaque native neighbour (D13):
# not under the translucent header cell, and with the corner square under the
# translucent body cell, the bottom corners' diagonal neighbour, left out.
TRANSLUCENT_BODY = (
    '<div class="slide"><div id="translucent-wrapper" style="position: absolute; left: 88px; '
    'top: 160px; width: 900px; border-radius: 8px; overflow: hidden;">'
    '<table class="rounded-table"><thead><tr><th>Use case</th>'
    '<th style="background: rgba(255, 95, 70, 0.5);">Measurement</th><th>Cost</th></tr></thead>'
    '<tbody><tr style="background: none;"><td style="background: #FFFFFF;">UC 1</td>'
    '<td style="background: rgba(27, 49, 57, 0.1);">Batch load</td>'
    '<td style="background: #FFFFFF;">$184</td></tr>'
    "<tr><td>UC 2</td><td>DLT run</td><td>$142</td></tr></tbody></table></div></div>"
)
# The slots TRANSLUCENT_BODY paints translucent.
TRANSLUCENT_SLOTS = ((0, 1), (1, 1))
# The rounded data table with a 1 px rule row under its header (``tr.rule``, DCE0E2):
# a corner piece runs under an opaque row that thin by half its height, so it ends
# inside that row, short of the line beneath it.
THIN_BODY = (
    '<div class="slide"><div id="thin-wrapper" style="position: absolute; left: 88px; '
    'top: 160px; width: 900px; border-radius: 8px; overflow: hidden;">'
    '<table class="rounded-table"><thead><tr><th>Use case</th><th>Measurement</th>'
    '<th>Cost</th></tr><tr class="rule"><td></td><td></td><td></td></tr></thead>'
    "<tbody><tr><td>UC 1</td><td>Batch load</td><td>$184</td></tr>"
    "<tr><td>UC 2</td><td>DLT run</td><td>$142</td></tr></tbody></table></div></div>"
)
# The rounded data table in two columns: its corner cells meet each other, and a corner
# cell's shape runs under no other corner cell, which the table leaves unfilled too.
PAIR_BODY = (
    '<div class="slide"><div id="pair-wrapper" style="position: absolute; left: 88px; '
    'top: 160px; width: 600px; border-radius: 8px; overflow: hidden;">'
    '<table class="rounded-table"><thead><tr><th>Use case</th><th>Cost</th></tr></thead>'
    "<tbody><tr><td>UC 1</td><td>$184</td></tr><tr><td>UC 2</td><td>$142</td></tr>"
    "</tbody></table></div></div>"
)
# The rounded data table under a header whose first cell spans two columns: the corner
# cell's bottom side lies along two slots, the second translucent (the first body row's
# middle cell, its row painting nothing), so that side runs under neither.
SPAN_CORNER_BODY = (
    '<div class="slide"><div id="span-corner-wrapper" style="position: absolute; left: 88px; '
    'top: 160px; width: 900px; border-radius: 8px; overflow: hidden;">'
    '<table class="rounded-table"><thead><tr><th colspan="2">Use case and measurement</th>'
    '<th>Cost</th></tr></thead><tbody><tr style="background: none;">'
    '<td style="background: #FFFFFF;">UC 1</td><td style="background: rgba(27, 49, 57, 0.1);">'
    'Batch load</td><td style="background: #FFFFFF;">$184</td></tr>'
    "<tr><td>UC 2</td><td>DLT run</td><td>$142</td></tr></tbody></table></div></div>"
)
# A two-row header: the first corner cell spans both rows; across its right side, the
# top slot is a header cell spanning two columns, opaque, and the slot below it a
# translucent cell, so that side runs under neither; the other top corner runs under
# the spanning cell, its neighbour by its second slot.
SPAN_NEIGHBOUR_BODY = (
    '<div class="slide"><div id="span-neighbour-wrapper" style="position: absolute; left: 88px; '
    'top: 160px; width: 900px; border-radius: 8px; overflow: hidden;">'
    '<table class="rounded-table"><thead><tr><th rowspan="2">Use case</th>'
    '<th colspan="2">Measurement</th><th>Cost</th></tr>'
    '<tr><th style="background: rgba(255, 95, 70, 0.5);">Run</th><th>Load</th><th>List</th></tr>'
    "</thead><tbody><tr><td>UC 1</td><td>Batch</td><td>4 TB</td><td>$184</td></tr>"
    "<tr><td>UC 2</td><td>DLT</td><td>1 TB</td><td>$142</td></tr></tbody></table></div></div>"
)
# The rounded data table with a short first body row: two cells, its last slot
# covered by no cell, which paints nothing. The slide model's cells hold such a
# slot after every cell the page has (snapshot_table.mjs), so the cells the
# corner pieces' neighbours are read from are in another order than the
# table's, which is sorted by row and column: the top right corner cell's
# neighbour below is that empty slot, and runs under nothing there.
SHORT_ROW_BODY = (
    '<div class="slide"><div id="short-row-wrapper" style="position: absolute; left: 88px; '
    'top: 160px; width: 900px; border-radius: 8px; overflow: hidden;">'
    '<table class="rounded-table"><thead><tr><th>Use case</th><th>Measurement</th>'
    "<th>Cost</th></tr></thead><tbody><tr><td>UC 1</td><td>Batch load</td></tr>"
    "<tr><td>UC 2</td><td>DLT run</td><td>$142</td></tr></tbody></table></div></div>"
)
# The rounded data table laid out right to left: each row's first cell is its
# rightmost, so its cells are read in the reverse of the table's order. The first
# body row paints nothing of its own, its cells white but the last, at the
# table's left, translucent: the top left corner cell's neighbour below.
RTL_BODY = (
    '<div class="slide"><div id="rtl-wrapper" style="position: absolute; left: 88px; '
    'top: 160px; width: 900px; border-radius: 8px; overflow: hidden;">'
    '<table class="rounded-table" style="direction: rtl;"><thead><tr><th>Use case</th>'
    "<th>Measurement</th><th>Cost</th></tr></thead><tbody>"
    '<tr style="background: none;"><td style="background: #FFFFFF;">UC 1</td>'
    '<td style="background: #FFFFFF;">Batch load</td>'
    '<td style="background: rgba(27, 49, 57, 0.1);">$184</td></tr>'
    "<tr><td>UC 2</td><td>DLT run</td><td>$142</td></tr></tbody></table></div></div>"
)
# The slots each body paints translucent.
TRANSLUCENT_SLOTS_OF = {
    "translucent": TRANSLUCENT_SLOTS,
    "span-corner": ((1, 1),),
    "span-neighbour": ((1, 1),),
    "fixed-span": ((1, 1),),
    "rtl": ((1, 0),),
}
# The slots a short row leaves no cell in, which the table writes unfilled.
EMPTY_SLOTS_OF = {"short-row": ((1, 2),)}
# The spanning cells of the span bodies, (row, col) -> (grid_span, row_span): a
# fixture-drift guard, since a body whose cells no longer span tests nothing of it.
SPANS_OF = {
    "span-corner": {(0, 0): (2, 1)},
    "span-neighbour": {(0, 0): (1, 2), (0, 1): (2, 1)},
    "fixed-span": {(0, 0): (1, 2), (0, 1): (2, 1)},
}
# Each Google-deck corner body's corner slots and the fill its piece paints.
CORNER_PIECE_FILLS = {
    "rounded": {(0, 0): "FF5F46", (0, 2): "FF5F46", (2, 0): "F3F3F3", (2, 2): "F3F3F3"},
    "translucent": {(0, 0): "FF5F46", (0, 2): "FF5F46", (2, 0): "F3F3F3", (2, 2): "F3F3F3"},
    "thin": {(0, 0): "FF5F46", (0, 2): "FF5F46", (3, 0): "F3F3F3", (3, 2): "F3F3F3"},
    "pair": {(0, 0): "FF5F46", (0, 1): "FF5F46", (2, 0): "F3F3F3", (2, 1): "F3F3F3"},
    "span-corner": {(0, 0): "FF5F46", (0, 2): "FF5F46", (2, 0): "F3F3F3", (2, 2): "F3F3F3"},
    "span-neighbour": {(0, 0): "FF5F46", (0, 3): "FF5F46", (3, 0): "F3F3F3", (3, 3): "F3F3F3"},
    "fixed": {(0, 0): "FF5F46", (0, 2): "FF5F46", (2, 0): "F3F3F3", (2, 2): "F3F3F3"},
    "fixed-span": {(0, 0): "FF5F46", (0, 3): "FF5F46", (3, 0): "F3F3F3", (3, 3): "F3F3F3"},
    "short-row": {(0, 0): "FF5F46", (0, 2): "FF5F46", (2, 0): "F3F3F3", (2, 2): "F3F3F3"},
    "rtl": {(0, 0): "FF5F46", (0, 2): "FF5F46", (2, 0): "F3F3F3", (2, 2): "F3F3F3"},
}
# The rounded data table on a grid no font moves (``table-layout: fixed``, ``<col>``
# widths, rows 50 px tall): its lines are 88 / 388 / 688 / 988 and 160 / 210 / 260 / 310.
FIXED_BODY = (
    '<div class="slide"><div id="fixed-wrapper" style="position: absolute; left: 88px; '
    'top: 160px; width: 900px; border-radius: 8px; overflow: hidden;">'
    '<table class="rounded-table fixed-grid"><colgroup><col style="width: 300px;">'
    '<col style="width: 300px;"><col style="width: 300px;"></colgroup><thead><tr>'
    "<th>Use case</th><th>Measurement</th><th>Cost</th></tr></thead>"
    "<tbody><tr><td>UC 1</td><td>Batch load</td><td>$184</td></tr>"
    "<tr><td>UC 2</td><td>DLT run</td><td>$142</td></tr></tbody></table></div></div>"
)
# SPAN_NEIGHBOUR_BODY on such a grid, four 225 px columns (each header cell's width plus
# its 36 px of padding; ``<col>`` widths here would lay the grid 1/64 px wider than the
# wrapper, which would then cut the table): lines 88 / 313 / 538 / 763 / 988 and
# 160 / 210 / 260 / 310 / 360.
FIXED_SPAN_BODY = (
    '<div class="slide"><div id="fixed-span-wrapper" style="position: absolute; left: 88px; '
    'top: 160px; width: 900px; border-radius: 8px; overflow: hidden;">'
    '<table class="rounded-table fixed-grid"><thead><tr>'
    '<th rowspan="2" style="width: 189px;">Use case</th>'
    '<th colspan="2" style="width: 414px;">Measurement</th><th style="width: 189px;">Cost</th>'
    '</tr><tr><th style="background: rgba(255, 95, 70, 0.5);">Run</th><th>Load</th>'
    "<th>List</th></tr></thead><tbody><tr><td>UC 1</td><td>Batch</td><td>4 TB</td>"
    "<td>$184</td></tr><tr><td>UC 2</td><td>DLT</td><td>1 TB</td><td>$142</td></tr>"
    "</tbody></table></div></div>"
)
# The top left corner piece's box (left, top, right, bottom, CSS px) in the deck for
# Google Slides, worked out by hand from those lines: ``fixed``'s 1 px past its right
# line (388) and its bottom line (210); ``fixed-span``'s (the cell spanning two rows,
# 160 to 260) on its right line (313), a translucent slot across that side, and 1 px past
# its bottom line.
GOOGLE_CORNER_BOXES = {
    "fixed": (88.0, 160.0, 389.0, 211.0),
    "fixed-span": (88.0, 160.0, 313.0, 261.0),
}
# The browser's lines those boxes are worked out from: the corner cell's right column
# line and bottom row line.
GOOGLE_CORNER_GRID = {"fixed": (388.0, 210.0), "fixed-span": (313.0, 260.0)}
# How far, in the deck for Google Slides, a corner cell's shape runs under each opaque
# native neighbour (snapshot.mjs CORNER_RUN_UNDER_PX; CALIBRATION.md D13).
CORNER_RUN_UNDER_PX = 1.0
# A vertex within this of the corner arc lies on it (the arc is drawn as a polygon).
ARC_TOLERANCE_PX = 0.1
# A table whose own background (F3F3F3, under unfilled cells) fills a wrapper
# that rounds its 12 px corners by clipping: the browser shows that ground cut
# to the wrapper's corners.
GROUND_WRAPPER = "#ground-wrapper"
GROUND_RADIUS_PX = 12.0
GROUND_FILL = "F3F3F3"
GROUND_BODY = (
    '<div class="slide"><div id="ground-wrapper" style="position: absolute; left: 88px; '
    'top: 160px; width: 900px; border-radius: 12px; overflow: hidden;">'
    '<table class="ground-table"><tbody><tr><td>UC 1</td><td>Batch load</td><td>$184</td></tr>'
    "<tr><td>UC 2</td><td>DLT run</td><td>$142</td></tr></tbody></table></div></div>"
)
# The same wrapper 0.4 px below a whole px: its padding box, the table's own
# ground and the grid's first line start there, and the grid snaps up to 160.
GROUND_OFFSET_WRAPPER = "#ground-offset-wrapper"
GROUND_OFFSET_BODY = GROUND_BODY.replace("top: 160px;", "top: 160.4px;").replace(
    'id="ground-wrapper"', 'id="ground-offset-wrapper"'
)

# A filled header and total row on a table the browser lays out at fractional
# px on both axes: its offset, its width, its font size and its padding all
# fall between whole pixels, so its grid lines do too.
SNAP_BODY = """<div class="slide">
  <table id="snap" class="snap" style="left: 88.3px; top: 120.4px; width: 700.7px;">
    <thead><tr><th>Line</th><th>FY24</th><th>FY23</th></tr></thead>
    <tbody>
      <tr><td>Revenue</td><td>1,240.0</td><td>1,120.0</td></tr>
      <tr><td>Cost of goods sold</td><td>806.0</td><td>750.4</td></tr>
      <tr class="total"><td>Net income</td><td>97.8</td><td>88.1</td></tr>
    </tbody>
  </table>
  <table id="snap-tie" class="snap"
         style="left: 860.6px; top: 120.4px; width: 320.3px; background: none;">
    <tbody>
      <tr class="ruled-half"><td>Margin</td><td>34.9%</td></tr>
      <tr><td>Growth</td><td>10.7%</td></tr>
    </tbody>
  </table>
</div>"""
SNAP_TABLE = "#snap"
# Beside it, a two-column table with no ground of its own, whose one rule runs
# under its second column only: along that line its first slot is not ruled and
# its second is, 1 px.
SNAP_TIE_TABLE = "#snap-tie"
SNAP_TIE_LINE = 1
# A table whose rules are dotted (row 0's bottom, 2 px; the column rule, 1 px)
# and dashed (row 1's bottom, 2 px); below it a second, whose dotted rule runs
# under a cell spanning both columns; and, ahead of both in paint order, a
# table with no dotted rule.
DOTTED_BODY = """<div class="slide">
  <table id="undotted" class="ruled" style="left: 800px; top: 120px; width: 380px;">
    <tbody>
      <tr><td>Region</td><td>FY24</td></tr>
      <tr><td>EMEA</td><td>412.0</td></tr>
    </tbody>
  </table>
  <table id="dotted" class="dotted" style="left: 88px; top: 120px; width: 640px;">
    <tbody>
      <tr class="first"><td>Revenue</td><td>1,240.0</td></tr>
      <tr class="second"><td>Gross profit</td><td>434.0</td></tr>
      <tr><td>Operating income</td><td>148.8</td></tr>
    </tbody>
  </table>
  <table id="dotted-span" class="dotted" style="left: 88px; top: 420px; width: 640px;">
    <tbody>
      <tr class="first"><td colspan="2">Statement of income</td></tr>
      <tr><td>Net income</td><td>97.8</td></tr>
    </tbody>
  </table>
</div>"""
# The snapped table's own background, under its unfilled body cells.
SNAP_GROUND = "F7F5F2"
# A grid line agrees with where it belongs within this: EMU rounding, 1/9525 px a
# value, which a half px (4762.5 EMU) meets only to the EMU, row after row.
WHOLE_PX_TOLERANCE = 0.001
CONTENT_TOLERANCE_PX = 0.05

# Three tables of one-line and two-line cells. Chrome sets Arial and Helvetica at line-height:
# normal at 1.15 em, and the tight table at 1.0, both under the apps' single spacing of 1.2 em;
# DM Sans at normal is 1.30 em, over it.
APP_ROWS_TABLE = (
    "<thead><tr><th>$M</th><th>Q3 FY25</th></tr></thead><tbody>"
    "<tr><td>Cash &amp; equivalents</td><td>412</td></tr>"
    "<tr><td>Accounts receivable</td><td>186</td></tr>"
    "<tr><td>Two-line cell<br>second line</td><td>894</td></tr>"
    "<tr><td><b>Total assets</b></td><td><b>3,874</b></td></tr></tbody>"
)
APP_ROWS_BODY = f"""<div class="slide">
  <table id="rows-sans" class="app-rows" style="left: 88px; top: 80px;">{APP_ROWS_TABLE}</table>
  <table id="rows-tight" class="app-rows" style="left: 520px; top: 80px;">{APP_ROWS_TABLE}</table>
  <table id="rows-loose" class="app-rows" style="left: 88px; top: 400px;">{APP_ROWS_TABLE}</table>
</div>"""
APP_ROWS_TIGHT = ("#rows-sans", "#rows-tight")
APP_ROWS_LOOSE = "#rows-loose"

# A collapsed data table whose header cells round its top corners themselves (the long
# deck's coral headers), with no wrapper to clip them.
CELL_ROUNDS_BODY = """<div class="slide" style="background: #E9ECEF;">
  <table id="cell-rounds" class="cell-rounds" style="left: 88px; top: 120px;">
    <thead><tr><th>Assets</th><th>Type</th><th>$M</th></tr></thead>
    <tbody><tr><td>Cash</td><td>Current</td><td>240</td></tr>
    <tr><td>Fleet</td><td>Long</td><td>980</td></tr></tbody>
  </table>
</div>"""
CELL_ROUND_RADIUS_PX = 8.0
CELL_ROUND_CORNERS = {(0, 0): "top-left", (0, 2): "top-right"}
CELL_ROUND_FILLS = (("FF5F46",) * 3, ("FFFFFF",) * 3, ("F3F3F3",) * 3)

# A pricing table whose middle column is highlighted by inset rules on its cells (the edited
# deck's Pro column): `inset 2px 0 0` and `inset -2px 0 0`, a 2 px band at each side.
INSET_HIGHLIGHT_BODY = """<div class="slide">
  <table id="highlight" class="hl-table" style="left: 88px; top: 110px;">
    <thead><tr><th>Plan</th><th class="hl">Pro</th><th>Enterprise</th></tr></thead>
    <tbody><tr><td>Price</td><td class="hl-cell">TBD</td><td>TBD</td></tr>
    <tr><td>Users</td><td class="hl-cell">Growing teams</td><td>Organisation</td></tr>
    <tr><td>Support</td><td class="hl-cell">Business hours</td><td>24x7</td></tr></tbody>
  </table>
</div>"""
INSET_HIGHLIGHT_COLUMN = 1
INSET_HIGHLIGHT_ROWS = (1, 2, 3)
INSET_HIGHLIGHT_COLOUR = "EB4A34"
INSET_HIGHLIGHT_BAND_PX = 2.0

# A balance sheet's total row ruled 3px double under, a 6px double rule, and a 2px one, which
# Chrome paints solid (a double border needs a px each for its two lines and its gap).
DOUBLE_ROWS_BODY = """<div class="slide">
  <table id="double-rows" class="double-rows" style="left: 88px; top: 90px;"><tbody>
    <tr><td>Cash</td><td>412</td></tr>
    <tr class="total"><td>Total assets</td><td>3,874</td></tr>
    <tr class="net"><td>Net income</td><td>186</td></tr>
    <tr class="thin"><td>Margin</td><td>12%</td></tr>
    <tr><td>Shares</td><td>40</td></tr>
  </tbody></table>
</div>"""
# (row whose bottom edge is double, its colour, its width in px)
DOUBLE_EDGES = ((1, "102025", 3.0), (2, "EB4A34", 6.0))
# The 2px double rule's row: drawn solid.
THIN_DOUBLE_ROW = 3

INLINE_BODIES = {
    "app-rows": APP_ROWS_BODY,
    "highlight": INSET_HIGHLIGHT_BODY,
    "cell-rounds": CELL_ROUNDS_BODY,
    "double-rows": DOUBLE_ROWS_BODY,
    "caption": CAPTION_BODY,
    "rowspan": ROWSPAN_BODY,
    "valign": VALIGN_BODY,
    "margins": MARGINS_BODY,
    "collapse": COLLAPSE_BODY,
    "cards": CARDS_BODY,
    "plain": PLAIN_BODY,
    "nested": NESTED_BODY,
    "blocks": BLOCKS_BODY,
    "fills": FILLS_BODY,
    "origin": ORIGIN_BODY,
    "clip": CLIP_BODY,
    "rounded": ROUNDED_BODY,
    "offset": OFFSET_BODY,
    "clear": CLEAR_BODY,
    "translucent": TRANSLUCENT_BODY,
    "thin": THIN_BODY,
    "pair": PAIR_BODY,
    "span-corner": SPAN_CORNER_BODY,
    "span-neighbour": SPAN_NEIGHBOUR_BODY,
    "fixed": FIXED_BODY,
    "fixed-span": FIXED_SPAN_BODY,
    "short-row": SHORT_ROW_BODY,
    "rtl": RTL_BODY,
    "precedence": PRECEDENCE_BODY,
    "doubled": DOUBLED_BODY,
    "dots": DOTS_BODY,
    "loose": LOOSE_BODY,
    "captured": CAPTURED_BODY,
    "snap": SNAP_BODY,
    "ground": GROUND_BODY,
    "ground-offset": GROUND_OFFSET_BODY,
}

# A two-cell table added to the hostile-realm fixtures, after the prose.
HOSTILE_ANCHOR = '<div class="prose">Synthetic fixture slide.</div>'
HOSTILE_TABLE = (
    '<table class="hl-table" style="border-collapse: collapse; font-size: 24px;"><tbody><tr>'
    '<td style="padding: 4px 12px; border-bottom: 2px solid #ffffff;">Pass one</td>'
    '<td style="padding: 4px 12px; border-bottom: 2px solid #ffffff;">Pass two</td>'
    "</tr></tbody></table>"
)
HOSTILE_CELLS = ("Pass one", "Pass two")
HOSTILE_TEXT_NODES = "hostile_text_nodes"

# A table with a rowspan, a colspan and a <col span="2">, its third column filled.
SPANS_BODY = """<div class="slide">
  <table id="spans" class="ruled" style="left: 88px; top: 120px; width: 640px;">
    <colgroup><col span="2"><col style="background: #F1EFEB;"></colgroup>
    <thead><tr><th>Segment</th><th>Quarter</th><th class="num">Revenue</th></tr></thead>
    <tbody>
      <tr><td rowspan="2">Industrial</td><td>Q1</td><td class="num">120.0</td></tr>
      <tr><td>Q2</td><td class="num">131.5</td></tr>
      <tr><td colspan="2">Total</td><td class="num">251.5</td></tr>
    </tbody>
  </table>
</div>"""
SPANS_TABLE = "#spans"
SPANS_COLUMN_FILL = ("F1EFEB", 2)
# Slide script that makes the page realm's span getters lie: every cell spans 7
# rows and 9 columns, every column 5. It publishes on document.title what it
# replaced and what a reader of the realm now sees.
POISONED_SPANS_SCRIPT = (
    "<script>(function () {"
    "var report = { configurable: {}, bites: {}, redefineResult: 'ok' };"
    "function poison(proto, name, label, value) {"
    " var descriptor = Object.getOwnPropertyDescriptor(proto, name);"
    " report.configurable[label] = !!(descriptor && descriptor.configurable);"
    " try { Object.defineProperty(proto, name, { configurable: true,"
    "   get: function () { return value; } }); }"
    " catch (error) { report.redefineResult = 'refused ' + label + ': ' + error.message; } }"
    "poison(HTMLTableCellElement.prototype, 'rowSpan', 'HTMLTableCellElement.rowSpan', 7);"
    "poison(HTMLTableCellElement.prototype, 'colSpan', 'HTMLTableCellElement.colSpan', 9);"
    "poison(HTMLTableColElement.prototype, 'span', 'HTMLTableColElement.span', 5);"
    "var cell = document.createElement('td'); var column = document.createElement('col');"
    "report.bites = { rowSpan: cell.rowSpan === 7, colSpan: cell.colSpan === 9,"
    " span: column.span === 5 };"
    "document.title = JSON.stringify(report);"
    "})();</script>"
)
POISONED_SPANS = (
    "HTMLTableCellElement.rowSpan",
    "HTMLTableCellElement.colSpan",
    "HTMLTableColElement.span",
)

# A row whose second cell slide script makes in another namespace: tagged td and
# laid out as a table cell (the deck's td rule), but no HTMLTableCellElement, so
# no span of it can be read.
FOREIGN_BODY = """<div class="slide">
  <table id="foreign" class="ruled foreign" style="left: 88px; top: 120px; width: 640px;">
    <tbody><tr id="foreign-row"><td>Native cell</td></tr></tbody>
  </table>
  <script>(function () {
    var cell = document.createElementNS('http://example.com/not-html', 'td');
    cell.appendChild(document.createTextNode('Foreign cell'));
    document.getElementById('foreign-row').appendChild(cell);
  })();</script>
</div>"""
FOREIGN_TABLE = "#foreign"
FOREIGN_TEXTS = ("Native cell", "Foreign cell")

# A table slide script grows to 1,001 rows over 1,000 columns: a grid of
# 1,001,000 slots, past COLLECTION_ITEM_LIMIT (1,000,000), though only one row
# shows (the rest are empty and unpadded).
AREA_BODY = """<div class="slide">
  <table id="area" style="position: absolute; left: 88px; top: 120px; border-collapse: collapse;
                          font-size: 18px;">
    <tbody id="area-body"><tr><td colspan="1000" style="padding: 4px 8px;">Wide</td></tr></tbody>
  </table>
  <script>(function () {
    var body = document.getElementById('area-body');
    for (var row = 0; row < 1000; row++) body.insertRow().insertCell();
  })();</script>
</div>"""
AREA_TABLE = "#area"
AREA_TEXT = "Wide"
SLIDE_WIDTH_PX = 1280
SLIDE_HEIGHT_PX = 720
# What the snapshot announces when a table is past a bound or unreadable.
NATIVE_TABLE_LINE = "[html2pptx] native table"

# The Drive round trip converts fixture 05 and the collapse document in one deck.
GOOGLE_SLIDE_NAMES = ("05-balance-sheet", "collapse")


# ---------------------------------------------------------------------------
# Reading helpers
# ---------------------------------------------------------------------------


def _normalised(text: str) -> str:
    return " ".join(text.split())


def _css_colour(value: str) -> tuple[str, float]:
    """('RRGGBB', alpha) of a colour as getComputedStyle serialises it."""
    match = CSS_COLOUR.fullmatch(value.strip())
    assert match, f"unexpected computed colour {value!r}"
    red, green, blue = (round(float(match.group(index))) for index in (1, 2, 3))
    alpha = 1.0 if match.group(4) is None else float(match.group(4))
    return f"{red:02X}{green:02X}{blue:02X}", alpha


def _hex(pixel: tuple[int, int, int]) -> str:
    return "".join(f"{channel:02X}" for channel in pixel)


def _rect(shape: Shape) -> str:
    return f"({shape.x:.2f}, {shape.y:.2f}, {shape.w:.2f}x{shape.h:.2f})"


def _describe(shapes: list[Shape]) -> str:
    lines = []
    for position, shape in enumerate(shapes):
        line = f"  [{position}] {shape.kind} {shape.geometry} {_rect(shape)}"
        if shape.fill:
            line += f" fill={shape.fill}"
            if shape.fill_alpha is not None:
                line += f"@{shape.fill_alpha:.2f}"
        if shape.line:
            line += f" line={shape.line}"
        if shape.table is not None:
            line += (
                f" grid={len(shape.table.row_heights)}x{len(shape.table.col_widths)}"
                f" cells={[_normalised(cell.text) for row in shape.table.rows for cell in row]}"
            )
        elif shape.text:
            line += f" {_normalised(shape.text)[:60]!r}"
        lines.append(line)
    return "\n".join(lines)


def _inside(inner: dict, outer: dict, tolerance: float = INSIDE_TOLERANCE_PX) -> bool:
    return (
        inner["x"] >= outer["x"] - tolerance
        and inner["y"] >= outer["y"] - tolerance
        and inner["x"] + inner["w"] <= outer["x"] + outer["w"] + tolerance
        and inner["y"] + inner["h"] <= outer["y"] + outer["h"] + tolerance
    )


def _box(shape: Shape) -> dict:
    return {"x": shape.x, "y": shape.y, "w": shape.w, "h": shape.h}


def _same_rect(a: dict, b: dict, tolerance: float = RECT_TOLERANCE_PX) -> bool:
    return all(abs(a[key] - b[key]) <= tolerance for key in ("x", "y", "w", "h"))


def _centre_inside(shape: Shape, area: dict, tolerance: float = RECT_TOLERANCE_PX) -> bool:
    centre_x = shape.x + shape.w / 2
    centre_y = shape.y + shape.h / 2
    return (
        area["x"] - tolerance <= centre_x <= area["x"] + area["w"] + tolerance
        and area["y"] - tolerance <= centre_y <= area["y"] + area["h"] + tolerance
    )


def _grid_rect(table: BrowserTable) -> dict:
    """The union of the browser's cell boxes: the grid, without the caption the table box holds."""
    left = min(cell.x for cell in table.cells)
    top = min(cell.y for cell in table.cells)
    right = max(cell.x + cell.w for cell in table.cells)
    bottom = max(cell.y + cell.h for cell in table.cells)
    return {"x": left, "y": top, "w": right - left, "h": bottom - top}


def _frame_for(shapes: list[Shape], grid: dict, what: str) -> tuple[int, Shape]:
    """(spTree index, frame) of the one native table whose grid starts where the browser's does."""
    frames = table_frames(shapes)
    at = [
        (position, frame)
        for position, frame in frames
        if abs(frame.x - grid["x"]) <= RECT_TOLERANCE_PX
        and abs(frame.y - grid["y"]) <= RECT_TOLERANCE_PX
    ]
    assert len(at) == 1, (
        f"{what}: expected one native table (p:graphicFrame with a:tbl) whose grid starts at "
        f"the browser's ({grid['x']:.2f}, {grid['y']:.2f}); found {len(at)} there, of the "
        f"slide's {len(frames)} native tables. The slide holds:\n{_describe(shapes)}"
    )
    return at[0]


def _owner(frame: Shape, row: int, col: int) -> Cell:
    assert frame.table is not None
    owner_row, owner_col = table_slot_owner(frame.table, row, col)
    return frame.table.rows[owner_row][owner_col]


def _origin_cells(frame: Shape) -> list[tuple[int, int, Cell]]:
    """(row, col, cell) of every a:tc that is a cell, not a merge placeholder."""
    assert frame.table is not None
    return [
        (row, col, cell)
        for row, cells in enumerate(frame.table.rows)
        for col, cell in enumerate(cells)
        if not (cell.h_merge or cell.v_merge)
    ]


def _cell_texts(shapes: list[Shape]) -> list[str]:
    """The normalised text of every native table cell on the slide."""
    return [
        _normalised(cell.text)
        for _, frame in table_frames(shapes)
        for _, _, cell in _origin_cells(frame)
    ]


def _text_items(shapes: list[Shape], words: str) -> list[tuple[int, Shape]]:
    """(spTree index, shape) of every text item whose text contains ``words``."""
    return [
        (position, shape)
        for position, shape in enumerate(shapes)
        if shape.kind == "text" and words in _normalised(shape.text)
    ]


def _runs(cell: Cell) -> list:
    return [run for para in cell.paras for run in para.runs if run.text]


def _describe_runs(cell: Cell) -> str:
    return ", ".join(f"{run.text!r} {run.typeface} b={run.bold} {run.color}" for run in _runs(cell))


def _border_key(border: Border | None) -> tuple | None:
    if border is None:
        return None
    return (border.color, round(border.width_pt or 0.0, 2), border.dash or "solid")


def _shared_edge_contradictions(frame: Shape) -> list[str]:
    """Every shared edge whose two cells' sides differ (one's line against the other's)."""
    assert frame.table is not None
    table = frame.table
    problems = []
    for row, cells in enumerate(table.rows):
        for col in range(len(cells)):
            owner = table_slot_owner(table, row, col)
            here = table.rows[owner[0]][owner[1]]
            if col + 1 < len(cells):
                right = table_slot_owner(table, row, col + 1)
                if right != owner:
                    there = table.rows[right[0]][right[1]]
                    if _border_key(here.borders["right"]) != _border_key(there.borders["left"]):
                        problems.append(
                            f"slot ({row}, {col}) | ({row}, {col + 1}): lnR "
                            f"{_border_key(here.borders['right'])} against lnL "
                            f"{_border_key(there.borders['left'])}"
                        )
            if row + 1 < len(table.rows):
                below = table_slot_owner(table, row + 1, col)
                if below != owner:
                    there = table.rows[below[0]][below[1]]
                    if _border_key(here.borders["bottom"]) != _border_key(there.borders["top"]):
                        problems.append(
                            f"slot ({row}, {col}) over ({row + 1}, {col}): lnB "
                            f"{_border_key(here.borders['bottom'])} against lnT "
                            f"{_border_key(there.borders['top'])}"
                        )
    return problems


def _cells_missing_sides(frame: Shape) -> list[str]:
    return [
        f"slot ({row}, {col}) {_normalised(cell.text)!r} writes only {sorted(cell.sides_written)}"
        for row, col, cell in _origin_cells(frame)
        if cell.sides_written != frozenset(SIDES)
    ]


def _assert_grid_matches(frame: Shape, browser: BrowserTable, what: str) -> None:
    """The emitted grid is the browser's: line for line, span for span, merge for merge."""
    assert frame.table is not None
    table = frame.table
    assert len(table.col_widths) == browser.columns and len(table.row_heights) == len(
        browser.rows
    ), (
        f"{what}: the a:tbl grid is {len(table.row_heights)} rows by {len(table.col_widths)} "
        f"columns; the browser's is {len(browser.rows)} by {browser.columns}"
    )
    columns = table_column_edges(frame)
    rows = table_row_edges(frame)
    problems = []
    for cell in browser.cells:
        label = f"cell ({cell.row}, {cell.col}) {_normalised(cell.text)!r}"
        for side, emitted, measured in (
            ("left", columns[cell.col], cell.x),
            ("right", columns[cell.col + cell.col_span], cell.x + cell.w),
            ("top", rows[cell.row], cell.y),
            ("bottom", rows[cell.row + cell.row_span], cell.y + cell.h),
        ):
            if abs(emitted - measured) > RECT_TOLERANCE_PX:
                problems.append(
                    f"{label}: grid line on its {side} at {emitted:.2f}, browser edge "
                    f"{measured:.2f}"
                )
        origin = table.rows[cell.row][cell.col]
        if origin.h_merge or origin.v_merge:
            problems.append(f"{label}: its own slot is a merge placeholder")
        elif (origin.row_span, origin.grid_span) != (cell.row_span, cell.col_span):
            problems.append(
                f"{label}: a:tc rowSpan={origin.row_span} gridSpan={origin.grid_span}; the "
                f"browser's cell spans {cell.row_span} rows and {cell.col_span} columns"
            )
        for row_offset in range(cell.row_span):
            for col_offset in range(cell.col_span):
                slot = (cell.row + row_offset, cell.col + col_offset)
                owner = table_slot_owner(table, *slot)
                if owner != (cell.row, cell.col):
                    problems.append(f"{label}: slot {slot} belongs to {owner}, not to it")
    assert not problems, f"{what}: the grid is not the browser's:\n  " + "\n  ".join(problems)


def _edge_winner(
    pixel: tuple[int, int, int], candidates: list[BrowserBorder], what: str
) -> BrowserBorder:
    """The cell border the browser painted on a collapsed edge: the one in the screen's colour."""
    painted = _hex(pixel)
    matching = [
        border
        for border in candidates
        if border.style != "none"
        and border.width_px > 0
        and _css_colour(border.color)[0] == painted
    ]
    assert matching, (
        f"fixture drift: {what}: the browser paints #{painted} on the edge, which is neither "
        f"cell's own border: {candidates}"
    )
    return max(matching, key=lambda border: border.width_px)


def _assert_side(cell: Cell, side: str, winner: BrowserBorder, what: str) -> None:
    border = cell.borders[side]
    colour = _css_colour(winner.color)[0]
    width_pt = winner.width_px * PT_PER_PX
    assert border is not None, (
        f"{what}: the {side} side carries no line; the browser paints {winner.width_px:g} px "
        f"{winner.style} #{colour} there"
    )
    assert (
        border.color == colour and abs((border.width_pt or 0.0) - width_pt) <= WIDTH_TOLERANCE_PT
    ), (
        f"{what}: the {side} side is {border.width_pt} pt #{border.color}; the browser paints "
        f"{winner.width_px:g} px ({width_pt:g} pt) #{colour}"
    )
    if winner.style == "solid":
        assert border.dash in (None, "solid"), (
            f"{what}: the {side} side is dashed {border.dash!r}; the browser's line is solid"
        )


def _margin_problem(cell: Cell, side: str, expected: float, what: str) -> str | None:
    """Why ``cell``'s margin on ``side`` is not ``expected`` px (within tolerance), if it is not."""
    margin = cell.margins_px[side]
    tolerance = max(expected * MARGIN_TOLERANCE_FRACTION, MARGIN_TOLERANCE_FLOOR_PX)
    if margin is None or abs(margin - expected) > tolerance:
        return f"{what}: {side} margin {margin}; the browser starts its content {expected:g} px in"
    return None


def _slot_under(frame: Shape, cell: BrowserCell) -> tuple[int, int]:
    """The a:tbl slot whose grid cell is the browser cell's box: columns run left to right."""
    assert frame.table is not None
    under = [
        (row, col)
        for row, col, _ in _origin_cells(frame)
        if _same_rect(table_cell_rect(frame, row, col), cell.rect)
    ]
    assert len(under) == 1, (
        f"the browser cell {cell.text!r} at {cell.rect} lies on {len(under)} grid cells"
    )
    return under[0]


def _frames_over(shapes: list[Shape], area: dict) -> list[tuple[int, dict]]:
    """(spTree index, grid extent) of every native table whose grid overlaps ``area``."""
    return [
        (position, table_extent(frame))
        for position, frame in table_frames(shapes)
        if overlaps(SimpleNamespace(**table_extent(frame)), SimpleNamespace(**area))
    ]


def _assert_text_at_line(
    shapes: list[Shape], line: dict, area: dict, what: str, document: str, styled: str
) -> int:
    """The one text item reading a browser line box's text in ``area``: at that line within 1 px.

    Its box starts at the line's left, is the line's height, and its top is
    where ``emit_text.cjs`` places a one-line box over that line's glyphs
    (``single_line_box_top``, from the face ``styled``, the selector of the
    element the line's text is set in, measured in the browser), each within
    ``LINE_BOX_TOLERANCE_PX``. Returns its spTree index.
    """
    items = [
        (position, shape)
        for position, shape in _text_items(shapes, line["text"])
        if _centre_inside(shape, area, 0.0)
    ]
    assert len(items) == 1, (
        f"{what}: expected one text box reading {line['text']!r} in {area}, found "
        f"{len(items)}:\n{_describe(shapes)}"
    )
    position, item = items[0]
    style = browser_style(document, styled)
    family = style["fontFamily"].split(",")[0].strip().strip("\"'")
    size_px = float(style["fontSize"].removesuffix("px"))
    ascent = browser_ascent(document, family, int(style["fontWeight"]), size_px, style["fontStyle"])
    top = single_line_box_top(line["y"], size_px, ascent)
    edges = ((item.x, line["x"]), (item.y, top), (item.h, line["h"]))
    assert all(abs(emitted - measured) <= LINE_BOX_TOLERANCE_PX for emitted, measured in edges), (
        f"{what}: the text box {_rect(item)} is not at its browser line box {line}, whose "
        f"one-line box top is {top:.2f}"
    )
    return position


def _cell_text_written_once(shapes: list[Shape], text: str) -> int:
    """How many times ``text`` is written: as a native cell's text, plus text boxes holding it."""
    return _cell_texts(shapes).count(text) + len(_text_items(shapes, text))


def _picture_pixel(image: Image.Image, picture: Shape, x: float, y: float) -> tuple[int, ...]:
    """The pixel of ``picture``'s PNG that shows slide point (x, y)."""
    column = int((x - picture.x) / picture.w * image.width)
    row = int((y - picture.y) / picture.h * image.height)
    return image.getpixel(
        (min(max(column, 0), image.width - 1), min(max(row, 0), image.height - 1))
    )


def _near(pixel: tuple[int, ...], colour: str) -> bool:
    """Whether ``pixel`` paints ``colour``, within ``PIXEL_TOLERANCE`` per channel."""
    expected = (int(colour[0:2], 16), int(colour[2:4], 16), int(colour[4:6], 16))
    painted = len(pixel) < 4 or pixel[3] > 0
    return painted and all(
        abs(channel - want) <= PIXEL_TOLERANCE for channel, want in zip(pixel, expected)
    )


def _with_script(body: str, script: str) -> str:
    """A slide body with ``script`` as the last thing its slide holds."""
    head, tail = body.rsplit("</div>", 1)
    return head + script + "</div>" + tail


def _cell_holding(browser: BrowserTable, point_x: float, point_y: float) -> BrowserCell:
    """The browser cell whose box holds the point."""
    holding = [
        cell
        for cell in browser.cells
        if cell.x <= point_x <= cell.x + cell.w and cell.y <= point_y <= cell.y + cell.h
    ]
    assert len(holding) == 1, f"the point ({point_x:.1f}, {point_y:.1f}) is in {len(holding)} cells"
    return holding[0]


# ---------------------------------------------------------------------------
# Exports, read once per module
# ---------------------------------------------------------------------------


def _inline_document(name: str) -> str:
    """The complete document the inline export of ``name`` renders (its only slide)."""
    return slide_document(INLINE_BODIES[name], css=TABLES_CSS, slide_id="snapshot-1")


@pytest.fixture(scope="module")
def corpus_export() -> Iterator[Callable[[str], list[Shape]]]:
    """Corpus slide ``prefix`` exported alone through the snapshot engine, read once per module."""
    exported: dict[str, list[Shape]] = {}
    with pytest.MonkeyPatch.context() as monkeypatch:

        def export(prefix: str) -> list[Shape]:
            if prefix not in exported:
                pptx, failures = export_corpus([prefix], monkeypatch=monkeypatch)
                assert failures == [], f"the export rejected corpus slide {prefix}: {failures}"
                exported[prefix] = slide_shapes(pptx)
            return exported[prefix]

        yield export


@pytest.fixture(scope="module")
def inline_export() -> Iterator[Callable[[str], bytes]]:
    """Inline document ``name`` exported alone (one slide) through the snapshot engine, once."""
    exported: dict[str, bytes] = {}
    with pytest.MonkeyPatch.context() as monkeypatch:

        def export(name: str) -> bytes:
            if name not in exported:
                pptx, failures = export_slides(
                    [INLINE_BODIES[name]], css=TABLES_CSS, monkeypatch=monkeypatch
                )
                assert failures == [] and pptx, f"the export rejected the {name} slide: {failures}"
                exported[name] = pptx
            return exported[name]

        yield export


@pytest.fixture(scope="module")
def google_inline_export() -> Iterator[Callable[[str], bytes]]:
    """Inline document ``name`` exported alone for Google Slides (``target="gslides"``), once."""
    exported: dict[str, bytes] = {}
    with pytest.MonkeyPatch.context() as monkeypatch:

        def export(name: str) -> bytes:
            if name not in exported:
                pptx, failures = export_slides(
                    [INLINE_BODIES[name]], css=TABLES_CSS, monkeypatch=monkeypatch, target="gslides"
                )
                assert failures == [] and pptx, f"the export rejected the {name} slide: {failures}"
                exported[name] = pptx
            return exported[name]

        yield export


@pytest.fixture(scope="module")
def balance_tables() -> list[BrowserTable]:
    """Fixture 05's two tables as the browser laid them out, left then right."""
    tables = browser_tables(corpus_document("05"), BALANCE_TABLES)
    assert len(tables) == 2, f"fixture drift: fixture 05 has {len(tables)} balance-sheet tables"
    assert tables[0].x + tables[0].w < tables[1].x, (
        "fixture drift: fixture 05's tables are not side by side: "
        f"{tables[0].rect}, {tables[1].rect}"
    )
    for table in tables:
        assert table.border_collapse == "collapse" and table.caption is None, (
            f"fixture drift: a balance-sheet table is {table.border_collapse} with caption "
            f"{table.caption}"
        )
    return tables


@pytest.fixture(scope="module")
def scorecard_table() -> BrowserTable:
    """Fixture 04's scorecard as the browser laid it out."""
    tables = browser_tables(corpus_document("04"), SCORECARD_TABLE)
    assert len(tables) == 1, f"fixture drift: fixture 04 has {len(tables)} scorecard tables"
    return tables[0]


@pytest.fixture(scope="module")
def pills_table() -> BrowserTable:
    """Fixture 06's measures table as the browser laid it out."""
    tables = browser_tables(corpus_document("06"), PILLS_TABLE)
    assert len(tables) == 1, f"fixture drift: fixture 06 has {len(tables)} measures tables"
    return tables[0]


@pytest.fixture(scope="module")
def dense_table() -> BrowserTable:
    """Fixture 15's table as the browser laid it out."""
    tables = browser_tables(corpus_document("15"), DENSE_TABLE)
    assert len(tables) == 1, f"fixture drift: fixture 15 has {len(tables)} tables"
    return tables[0]


def _balance_frames(
    shapes: list[Shape], tables: list[BrowserTable]
) -> list[tuple[int, Shape, BrowserTable]]:
    return [
        (*_frame_for(shapes, _grid_rect(table), f"fixture 05's table {number}"), table)
        for number, table in enumerate(tables, start=1)
    ]


def _assert_pills_overlaid(
    shapes: list[Shape],
    frame_position: int,
    frame: Shape,
    table: BrowserTable,
    pills: list[dict],
    labels: tuple[str, ...],
    column: int,
) -> None:
    """Each pill is one item inside its own cell, over the table, and its label is written once.

    One shape or picture lies at each pill's browser rect within 1 px, inside
    the browser box of the cell holding it and inside the grid cell the frame
    lays out, after the frame in the spTree. A pill is an atomic inline, so its
    line is overlay text: its label is exactly one text box, centred on the
    pill, and its cell's ``a:tc`` holds no text.
    """
    assert len(pills) == len(labels), f"fixture drift: {len(pills)} pills for labels {labels}"
    for label, pill in zip(labels, pills):
        what = f"pill {label!r} at {pill}"
        cell = _cell_holding(table, pill["x"] + pill["w"] / 2, pill["y"] + pill["h"] / 2)
        assert cell.col == column and _normalised(cell.text) == label, (
            f"fixture drift: {what} sits in cell ({cell.row}, {cell.col}) {cell.text!r}"
        )
        at_pill = [
            (position, shape)
            for position, shape in enumerate(shapes)
            if shape.kind in ("shape", "picture") and _same_rect(_box(shape), pill)
        ]
        assert len(at_pill) == 1, (
            f"{what}: expected one shape or picture at its rect, found {len(at_pill)}:\n"
            f"{_describe(shapes)}"
        )
        position, item = at_pill[0]
        grid_cell = table_cell_rect(frame, cell.row, cell.col)
        assert _inside(_box(item), cell.rect) and _inside(
            _box(item), grid_cell, RECT_TOLERANCE_PX
        ), f"{what}: {_rect(item)} leaves its cell (browser {cell.rect}, grid {grid_cell})"
        assert position > frame_position, (
            f"{what}: at spTree {position}, under the table at {frame_position}"
        )
        texts = _text_items(shapes, label)
        assert len(texts) == 1 and _centre_inside(texts[0][1], pill), (
            f"{what}: its label must be one text box centred on it; found "
            f"{[_rect(shape) for _, shape in texts]}"
        )
        origin = frame.table.rows[cell.row][cell.col]
        assert not _normalised(origin.text), (
            f"{what}: its cell's a:tc also reads {origin.text!r}; its line is overlay text"
        )


# ---------------------------------------------------------------------------
# The balance sheet (fixture 05): two tables side by side
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestBalanceSheet:
    def test_each_table_is_one_native_frame_at_its_browser_rect(
        self, corpus_export: Callable[[str], list[Shape]], balance_tables: list[BrowserTable]
    ) -> None:
        """The two tables are two native frames, side by side as the browser draws them.

        Exactly two ``a:tbl`` frames, with disjoint x ranges (never one table
        stacked on the other), each at its browser table's rect within
        1 px: the frame's offset and extent, and the grid PowerPoint lays out
        (its ``gridCol`` widths sum to the table's width, its ``a:tr`` heights to
        its height).
        """
        shapes = corpus_export("05")
        frames = table_frames(shapes)
        assert len(frames) == 2, (
            f"fixture 05: expected 2 native tables, found {len(frames)}:\n{_describe(shapes)}"
        )
        placed = sorted((frame for _, frame in frames), key=lambda frame: frame.x)
        assert placed[0].x + placed[0].w <= placed[1].x + INSIDE_TOLERANCE_PX, (
            f"fixture 05: the frames' x ranges overlap: {_rect(placed[0])} and {_rect(placed[1])}"
        )
        for number, (frame, table) in enumerate(zip(placed, balance_tables), start=1):
            extent = table_extent(frame)
            assert _same_rect(_box(frame), table.rect), (
                f"table {number}: the frame is at {_rect(frame)}; the browser's table at "
                f"{table.rect}"
            )
            assert _same_rect(extent, table.rect), (
                f"table {number}: the grid lays out at {extent} (gridCol widths "
                f"{frame.table.col_widths}, row heights {frame.table.row_heights}); the browser's "
                f"table is {table.rect}"
            )

    def test_grid_lines_are_the_browser_cell_edges(
        self, corpus_export: Callable[[str], list[Shape]], balance_tables: list[BrowserTable]
    ) -> None:
        """Every grid line is where the browser put a cell edge, and every span is the browser's.

        For every cell, the ``gridCol`` lines on its left and right and the
        ``a:tr`` lines above and below it lie within 1 px of its browser box,
        its own slot carries its ``gridSpan`` and ``rowSpan``, and every slot it
        covers is a merge placeholder that belongs to it.
        """
        shapes = corpus_export("05")
        for position, frame, table in _balance_frames(shapes, balance_tables):
            _assert_grid_matches(frame, table, f"fixture 05's table at spTree {position}")

    def test_each_section_row_is_one_cell_spanning_three_columns(
        self, corpus_export: Callable[[str], list[Shape]], balance_tables: list[BrowserTable]
    ) -> None:
        """The section rows ("Current assets", "Non-current assets", "Liabilities") span the table.

        Each section label's ``a:tc`` has ``gridSpan="3"``, the two slots after it
        are ``hMerge`` placeholders, it is filled as the browser fills it
        (``EEEDE9``), and it is the only cell reading that label.
        """
        shapes = corpus_export("05")
        frames = _balance_frames(shapes, balance_tables)
        texts = _cell_texts(shapes)
        found = []
        for _, frame, table in frames:
            for cell in table.cells:
                label = _normalised(cell.text)
                if label not in SECTION_LABELS:
                    continue
                found.append(label)
                assert cell.col_span == 3, f"fixture drift: {label!r} spans {cell.col_span} columns"
                origin = frame.table.rows[cell.row][cell.col]
                assert origin.grid_span == 3 and _normalised(origin.text) == label, (
                    f"{label!r}: slot ({cell.row}, {cell.col}) reads {_normalised(origin.text)!r} "
                    f"with gridSpan={origin.grid_span}; expected one cell spanning 3 columns"
                )
                placeholders = [frame.table.rows[cell.row][col] for col in (1, 2)]
                assert all(placeholder.h_merge for placeholder in placeholders), (
                    f"{label!r}: the slots after it are not hMerge placeholders: "
                    f"{[(p.h_merge, _normalised(p.text)) for p in placeholders]}"
                )
                fill = _css_colour(cell.style["backgroundColor"])[0]
                assert origin.fill == fill, f"{label!r} is filled {origin.fill}, not {fill}"
                assert texts.count(label) == 1, (
                    f"{label!r} is the text of {texts.count(label)} table cells: {texts}"
                )
        assert sorted(found) == sorted(SECTION_LABELS), f"fixture drift: section rows {found}"

    def test_header_cells_are_filled_with_white_semibold_runs(
        self, corpus_export: Callable[[str], list[Shape]], balance_tables: list[BrowserTable]
    ) -> None:
        """The header row is filled ``FF5F46`` and its text is white; DM Sans at 600 is SemiBold.

        Every header ``a:tc`` is filled the accent, every run of it is white,
        and the DM Sans header cells' runs are typeface ``DM Sans SemiBold``,
        not bold (600 is a named face, never the bold flag).
        """
        shapes = corpus_export("05")
        for _, frame, table in _balance_frames(shapes, balance_tables):
            header = [cell for cell in table.cells if cell.row == 0]
            assert header and all(cell.tag == "th" for cell in header), "fixture drift: no th row"
            for cell in header:
                what = f"header {_normalised(cell.text)!r}"
                assert _css_colour(cell.style["backgroundColor"])[0] == HEADER_FILL, (
                    f"fixture drift: {what} is {cell.style['backgroundColor']}"
                )
                origin = frame.table.rows[cell.row][cell.col]
                assert (
                    origin.fill == HEADER_FILL and (origin.fill_alpha or 1.0) >= 1 - ALPHA_TOLERANCE
                ), f"{what}: filled {origin.fill} at {origin.fill_alpha}, not {HEADER_FILL}"
                runs = _runs(origin)
                assert runs and all(run.color == WHITE for run in runs), (
                    f"{what}: runs {_describe_runs(origin)}; every run must be #{WHITE}"
                )
                if cell.style["fontFamily"].startswith('"DM Sans"'):
                    assert cell.style["fontWeight"] == "600", f"fixture drift: {what} weight"
                    assert all(
                        (run.typeface, run.bold) == ("DM Sans SemiBold", False) for run in runs
                    ), f"{what}: runs {_describe_runs(origin)}; expected DM Sans SemiBold, not bold"

    def test_total_row_edge_is_written_on_both_cells(
        self, corpus_export: Callable[[str], list[Shape]], balance_tables: list[BrowserTable]
    ) -> None:
        """The edge above each total row is ONE line, on both cells, as the browser paints it.

        The row above's own bottom rule (1 px ``DCE0E2``) meets the total row's
        own top border (1 px ``1B3139``). The edge's winner is read off the
        screen at the middle of each column, and it is the row above's: equal
        widths and styles go to the cell earlier in the document. The winner is
        written on the total cell's ``lnT`` AND on the ``lnB`` of the cell above
        it, in every column; written as each cell's own, the two sides would
        contradict each other. Beyond the total rows, no shared edge of either
        table has two different sides, and every cell writes all four sides.
        """
        document = corpus_document("05")
        shapes = corpus_export("05")
        frames = _balance_frames(shapes, balance_tables)
        edges = []
        for _, frame, table in frames:
            (total,) = [cell for cell in table.cells if _normalised(cell.text) in TOTAL_LABELS]
            for lower in (cell for cell in table.cells if cell.row == total.row):
                upper = _cell_holding(table, lower.x + lower.w / 2, lower.y - 1.0)
                edges.append((frame, upper, lower))
        pixels = browser_pixels(
            document, [(lower.x + lower.w / 2, lower.y) for _, _, lower in edges]
        )

        for (frame, upper, lower), pixel in zip(edges, pixels):
            what = f"the edge between {_normalised(upper.text)!r} and {_normalised(lower.text)!r}"
            candidates = [upper.borders["bottom"], lower.borders["top"]]
            assert {
                _css_colour(border.color)[0] for border in candidates
            } == TOTAL_EDGE_CANDIDATES, f"fixture drift: {what} meets {candidates}"
            winner = _edge_winner(pixel, candidates, what)
            _assert_side(frame.table.rows[lower.row][lower.col], "top", winner, f"{what}, lnT")
            _assert_side(frame.table.rows[upper.row][upper.col], "bottom", winner, f"{what}, lnB")
        for position, frame, _ in frames:
            contradictions = _shared_edge_contradictions(frame)
            assert not contradictions, (
                f"fixture 05's table at spTree {position}: shared edges with two different "
                "sides:\n  " + "\n  ".join(contradictions)
            )
            missing = _cells_missing_sides(frame)
            assert not missing, (
                f"fixture 05's table at spTree {position}: cells that leave a side out:\n  "
                + "\n  ".join(missing)
            )

    def test_grand_row_is_filled_ink_with_white_runs(
        self, corpus_export: Callable[[str], list[Shape]], balance_tables: list[BrowserTable]
    ) -> None:
        """Each table's grand-total row is filled ``1B3139`` in every column; its text is white."""
        shapes = corpus_export("05")
        for _, frame, table in _balance_frames(shapes, balance_tables):
            (grand,) = [cell for cell in table.cells if _normalised(cell.text) in GRAND_LABELS]
            for cell in (cell for cell in table.cells if cell.row == grand.row):
                what = f"grand-row cell {_normalised(cell.text)!r}"
                assert _css_colour(cell.style["backgroundColor"])[0] == INK, (
                    f"fixture drift: {what}"
                )
                origin = frame.table.rows[cell.row][cell.col]
                assert origin.fill == INK, f"{what}: filled {origin.fill}, not {INK}"
                runs = _runs(origin)
                assert runs and all(run.color == WHITE for run in runs), (
                    f"{what}: runs {_describe_runs(origin)}; every run must be #{WHITE}"
                )

    def test_cell_margins_are_the_browser_padding(
        self, corpus_export: Callable[[str], list[Shape]], balance_tables: list[BrowserTable]
    ) -> None:
        """Every margin is the padding plus half the collapsed border; the indent is exactly 26 px.

        On each side of each cell the margin is its computed padding plus half
        the width of the border written on that side (the collapsed edge's
        winner, which the edge tests hold to the screen), within 1 %, measured
        from the browser's cell edge: that is where the browser puts the cell's
        content. The grid line lies on the whole px nearest that edge
        (``TestWholePixelGrid``), so the margin also takes up the part of a px
        between the two. The indented rows' first cells (``padding-left:
        26px``, no border on the table's left edge) have ``marL`` equal to that
        26 px in EMU within 1 %, and every margin is under an inch.
        """
        shapes = corpus_export("05")
        indented = 0
        problems = []
        for _, frame, table in _balance_frames(shapes, balance_tables):
            columns = table_column_edges(frame)
            rows = table_row_edges(frame)
            for cell in table.cells:
                origin = frame.table.rows[cell.row][cell.col]
                label = f"{_normalised(cell.text)!r}"
                # How far each side's grid line lies outside the browser's cell edge.
                snap = {
                    "left": cell.x - columns[cell.col],
                    "right": columns[cell.col + cell.col_span] - (cell.x + cell.w),
                    "top": cell.y - rows[cell.row],
                    "bottom": rows[cell.row + cell.row_span] - (cell.y + cell.h),
                }
                for side in SIDES:
                    margin = origin.margins_px[side]
                    padding = cell.padding[side]
                    if margin is None:
                        problems.append(f"{label}: no mar{side[0].upper()}")
                        continue
                    if not margin < PX_PER_INCH:
                        problems.append(
                            f"{label}: {side} margin {margin:.2f} px is an inch or more"
                        )
                    border = origin.borders[side]
                    half_border = (
                        0.0 if border is None else (border.width_pt or 0.0) / PT_PER_PX / 2
                    )
                    expected = padding + half_border + snap[side]
                    tolerance = max(expected * MARGIN_TOLERANCE_FRACTION, MARGIN_TOLERANCE_FLOOR_PX)
                    if abs(margin - expected) > tolerance:
                        problems.append(
                            f"{label}: {side} margin {margin:.3f} px; padding {padding:g} px plus "
                            f"half the {2 * half_border:g} px border written there, from a grid "
                            f"line {snap[side]:+.3f} px outside the browser's edge, is "
                            f"{expected:g} px"
                        )
                if cell.padding["left"] == INDENT_PADDING_PX:
                    indented += 1
                    margin_emu = (origin.margins_px["left"] or 0.0) * EMU_PER_PX
                    expected_emu = (INDENT_PADDING_PX + snap["left"]) * EMU_PER_PX
                    if abs(margin_emu - expected_emu) > expected_emu * MARGIN_TOLERANCE_FRACTION:
                        problems.append(
                            f"{label}: marL {margin_emu:.0f} EMU; the 26 px indent is "
                            f"{expected_emu:.0f} EMU"
                        )
        assert indented >= 2, f"fixture drift: {indented} indented cells"
        assert not problems, "cell margins differ from where the browser puts the text:\n  " + (
            "\n  ".join(problems)
        )

    def test_cell_text_and_boxes_belong_to_the_table(
        self, corpus_export: Callable[[str], list[Shape]], balance_tables: list[BrowserTable]
    ) -> None:
        """Each cell's text is its ``a:tc`` text, aligned as the browser aligns it, nowhere else.

        Every cell's ``a:tc`` reads the browser's text for that cell, with its
        paragraphs aligned by the cell's ``text-align`` (the ``.num`` columns
        right). The table owns its cells' text, fills and borders, so no text
        box, shape, line or picture lies on either table.
        """
        shapes = corpus_export("05")
        frames = _balance_frames(shapes, balance_tables)
        problems = []
        for _, frame, table in frames:
            for cell in table.cells:
                origin = frame.table.rows[cell.row][cell.col]
                label = _normalised(cell.text)
                if _normalised(origin.text) != label:
                    problems.append(
                        f"slot ({cell.row}, {cell.col}) reads {_normalised(origin.text)!r}, "
                        f"the browser {label!r}"
                    )
                    continue
                align = PARAGRAPH_ALIGNMENT[cell.style["textAlign"]]
                aligned = [para.align for para in origin.paras if para.runs]
                if not aligned or any(value != align for value in aligned):
                    problems.append(f"{label!r}: paragraphs aligned {aligned}, the browser {align}")
        assert not problems, "cell text differs from the browser's:\n  " + "\n  ".join(problems)
        extents = [table_extent(frame) for _, frame, _ in frames]
        on_tables = [
            f"[{position}] {shape.kind} {_rect(shape)} {_normalised(shape.text)[:40]!r}"
            for position, shape in enumerate(shapes)
            if shape.kind != "table"
            and any(_centre_inside(shape, extent, 0.0) for extent in extents)
        ]
        assert not on_tables, (
            "items lie on the tables, which own their cells' text, fills and borders:\n  "
            + "\n  ".join(on_tables)
        )


# ---------------------------------------------------------------------------
# The scorecard (fixture 04): Harvey balls in cells, a source line below
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestScorecard:
    def test_source_line_lies_below_the_table(
        self, corpus_export: Callable[[str], list[Shape]], scorecard_table: BrowserTable
    ) -> None:
        """The source line under the table stays under it, where the browser renders it.

        Its text box starts at or below the native table's bottom edge (the
        grid PowerPoint lays out, and the browser's table box), and its middle
        lies inside the line's browser rect.
        """
        document = corpus_document("04")
        shapes = corpus_export("04")
        _, frame = _frame_for(shapes, _grid_rect(scorecard_table), "fixture 04's scorecard")
        source = browser_rect(document, SOURCE_LINE)
        items = _text_items(shapes, SOURCE_TEXT)
        assert len(items) == 1, (
            f"expected one text box holding {SOURCE_TEXT!r}, found {len(items)}:\n"
            f"{_describe(shapes)}"
        )
        _, item = items[0]
        extent = table_extent(frame)
        bottom = max(extent["y"] + extent["h"], scorecard_table.y + scorecard_table.h)
        assert item.y >= bottom - INSIDE_TOLERANCE_PX, (
            f"the source line's box {_rect(item)} starts above the table's bottom edge {bottom:.2f}"
        )
        assert _centre_inside(item, source), (
            f"the source line's box {_rect(item)} is not where the browser renders it, {source}"
        )

    def test_row_labels_are_semibold_table_text(
        self, corpus_export: Callable[[str], list[Shape]], scorecard_table: BrowserTable
    ) -> None:
        """The row labels (``td:first-child``, weight 600) are native cell text in DM Sans SemiBold.

        Each body row's first ``a:tc`` reads its label and every run of it is
        typeface ``DM Sans SemiBold``, not bold: the weight is the cell's own
        style, carried into its runs.
        """
        shapes = corpus_export("04")
        _, frame = _frame_for(shapes, _grid_rect(scorecard_table), "fixture 04's scorecard")
        labels = [cell for cell in scorecard_table.cells if cell.col == 0 and cell.row > 0]
        assert tuple(_normalised(cell.text) for cell in labels) == ROW_LABELS, (
            f"fixture drift: row labels {[cell.text for cell in labels]}"
        )
        for cell in labels:
            assert cell.style["fontWeight"] == "600", f"fixture drift: {cell.text!r} weight"
            origin = frame.table.rows[cell.row][cell.col]
            runs = _runs(origin)
            assert _normalised(origin.text) == _normalised(cell.text) and runs, (
                f"the row label {cell.text!r} is not its cell's text: slot ({cell.row}, 0) reads "
                f"{origin.text!r}"
            )
            assert all((run.typeface, run.bold) == ("DM Sans SemiBold", False) for run in runs), (
                f"the row label {cell.text!r}: runs {_describe_runs(origin)}; expected DM Sans "
                "SemiBold, not bold"
            )

    def test_fy2024_column_is_filled_accent_at_ten_percent(
        self, corpus_export: Callable[[str], list[Shape]], scorecard_table: BrowserTable
    ) -> None:
        """The highlighted column's cells are filled ``FF5F46`` at alpha 0.10, and no other cell."""
        shapes = corpus_export("04")
        _, frame = _frame_for(shapes, _grid_rect(scorecard_table), "fixture 04's scorecard")
        highlighted = [
            cell
            for cell in scorecard_table.cells
            if cell.style["backgroundColor"] == HIGHLIGHT_BACKGROUND
        ]
        assert len(highlighted) == len(scorecard_table.rows) and all(
            cell.col == HIGHLIGHT_COLUMN for cell in highlighted
        ), f"fixture drift: highlighted cells at {[(cell.row, cell.col) for cell in highlighted]}"
        problems = []
        for cell in scorecard_table.cells:
            origin = frame.table.rows[cell.row][cell.col]
            if cell in highlighted:
                if (
                    origin.fill != HIGHLIGHT_FILL
                    or origin.fill_alpha is None
                    or abs(origin.fill_alpha - HIGHLIGHT_ALPHA) > ALPHA_TOLERANCE
                ):
                    problems.append(
                        f"slot ({cell.row}, {cell.col}): filled {origin.fill} at "
                        f"{origin.fill_alpha}; expected {HIGHLIGHT_FILL} at {HIGHLIGHT_ALPHA}"
                    )
            elif cell.style["backgroundColor"] == TRANSPARENT and origin.fill is not None:
                problems.append(
                    f"slot ({cell.row}, {cell.col}) {_normalised(cell.text)!r}: filled "
                    f"{origin.fill}; the browser's cell is transparent"
                )
        assert not problems, "cell fills differ from the browser's:\n  " + "\n  ".join(problems)

    def test_harvey_balls_are_pictures_overlaid_inside_their_cells(
        self, corpus_export: Callable[[str], list[Shape]], scorecard_table: BrowserTable
    ) -> None:
        """Each Harvey ball is a picture at its browser rect, inside its cell, over the table.

        One picture lies at each ball's browser rect within 1 px; it lies inside
        the browser box of the cell holding the ball and inside the grid cell
        the frame lays out for it; and it follows the frame in the spTree, so it
        paints over the cell's fill.
        """
        shapes = corpus_export("04")
        frame_position, frame = _frame_for(
            shapes, _grid_rect(scorecard_table), "fixture 04's scorecard"
        )
        balls = browser_each_rect(corpus_document("04"), HARVEY)
        assert len(balls) == HARVEY_COUNT, f"fixture drift: {len(balls)} Harvey balls"
        for number, ball in enumerate(balls):
            what = f"Harvey ball {number} at {ball}"
            pictures = [
                (position, shape)
                for position, shape in enumerate(shapes)
                if shape.kind == "picture" and _same_rect(_box(shape), ball)
            ]
            assert len(pictures) == 1, (
                f"{what}: expected one picture at its rect, found {len(pictures)}:\n"
                f"{_describe(shapes)}"
            )
            position, picture = pictures[0]
            cell = _cell_holding(
                scorecard_table, ball["x"] + ball["w"] / 2, ball["y"] + ball["h"] / 2
            )
            assert _inside(_box(picture), cell.rect), (
                f"{what}: the picture {_rect(picture)} leaves its browser cell {cell.rect}"
            )
            grid_cell = table_cell_rect(frame, cell.row, cell.col)
            assert _inside(_box(picture), grid_cell, RECT_TOLERANCE_PX), (
                f"{what}: the picture {_rect(picture)} leaves its grid cell {grid_cell}"
            )
            assert position > frame_position, (
                f"{what}: the picture is at spTree {position}, under the table at {frame_position}"
            )

    def test_verdict_cell_is_native_text_with_its_strong_word_bold(
        self, corpus_export: Callable[[str], list[Shape]], scorecard_table: BrowserTable
    ) -> None:
        """The verdict "Strength · current ratio 2.47x, …" is its cell's own text, "Strength" bold.

        The verdict cell's ``a:tc`` reads the browser's sentence; its
        ``<strong>`` (700) is the only bold run and reads "Strength", and every
        run is typeface ``DM Sans`` (400 and 700 are the family, 700 with the
        bold flag). No text box repeats the sentence.
        """
        shapes = corpus_export("04")
        _, frame = _frame_for(shapes, _grid_rect(scorecard_table), "fixture 04's scorecard")
        assert (
            browser_style(corpus_document("04"), VERDICT_STRONG_SELECTOR)["fontWeight"] == "700"
        ), "fixture drift: the verdict's <strong> is not 700"
        (cell,) = scorecard_table.cells_reading(VERDICT_TEXT)
        origin = frame.table.rows[cell.row][cell.col]
        assert _normalised(origin.text) == VERDICT_TEXT, (
            f"slot ({cell.row}, {cell.col}) reads {origin.text!r}; the browser's cell reads "
            f"{VERDICT_TEXT!r}"
        )
        runs = _runs(origin)
        bold = _normalised("".join(run.text for run in runs if run.bold))
        assert bold == VERDICT_STRONG, (
            f"the verdict's bold runs read {bold!r}, not {VERDICT_STRONG!r}: "
            f"{_describe_runs(origin)}"
        )
        assert all(run.typeface == "DM Sans" for run in runs), (
            f"the verdict's runs must all be typeface DM Sans: {_describe_runs(origin)}"
        )
        repeated = _text_items(shapes, "current ratio 2.47x")
        assert not repeated, (
            f"text boxes repeat the verdict cell's text: {[_rect(shape) for _, shape in repeated]}"
        )


# ---------------------------------------------------------------------------
# The pills table (fixture 06): pills in cells, a callout beside the table
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestPillsTable:
    def test_callout_stays_clear_of_the_table(
        self, corpus_export: Callable[[str], list[Shape]], pills_table: BrowserTable
    ) -> None:
        """The "So what" callout beside the table does not overlap the table's frame.

        The frame is at the browser table's rect within 1 px, the callout's
        shape (filled ``1B3139``) at the callout's, and the two do not overlap:
        the callout is the flex item beside the table, not a box ballooning over it.
        """
        document = corpus_document("06")
        shapes = corpus_export("06")
        _, frame = _frame_for(shapes, _grid_rect(pills_table), "fixture 06's table")
        extent = table_extent(frame)
        assert _same_rect(extent, pills_table.rect), (
            f"the table lays out at {extent}; the browser's table is {pills_table.rect}"
        )
        callout = browser_rect(document, CALLOUT)
        boxes = [
            shape
            for shape in shapes
            if shape.kind == "shape"
            and shape.fill == CALLOUT_FILL
            and _same_rect(_box(shape), callout)
        ]
        assert len(boxes) == 1, (
            f"expected the callout's shape at its browser rect {callout}, found {len(boxes)}:\n"
            f"{_describe(shapes)}"
        )
        assert not overlaps(boxes[0], SimpleNamespace(**extent)), (
            f"the callout {_rect(boxes[0])} overlaps the table {extent}"
        )

    def test_pills_lie_inside_their_change_cells_and_their_text_is_written_once(
        self, corpus_export: Callable[[str], list[Shape]], pills_table: BrowserTable
    ) -> None:
        """Each delta pill is its own item inside its "Change" cell, over the table.

        One shape or picture lies at each pill's browser rect within 1 px,
        inside the browser box of its "Change" cell and inside the grid cell the
        frame lays out, after the frame in the spTree. A pill is an atomic
        inline, so its line is overlay text: the pill's label is in exactly one
        text box, centred on the pill, and the "Change" cell's ``a:tc`` holds
        no text, so nothing is written twice.
        """
        document = corpus_document("06")
        shapes = corpus_export("06")
        frame_position, frame = _frame_for(shapes, _grid_rect(pills_table), "fixture 06's table")
        pills = browser_each_rect(document, DELTA_PILL)
        assert len(pills) == len(DELTA_PILLS), f"fixture drift: {len(pills)} pills"
        _assert_pills_overlaid(
            shapes, frame_position, frame, pills_table, pills, DELTA_PILLS, CHANGE_COLUMN
        )

    def test_measure_labels_are_table_text_at_their_own_weight(
        self, corpus_export: Callable[[str], list[Shape]], pills_table: BrowserTable
    ) -> None:
        """The measure labels are native cell text at the weight the cell itself sets.

        ``td:first-child`` is 600 in the deck, but each label cell sets
        ``font-weight: 400`` on itself, and the browser draws them regular: each
        label's ``a:tc`` reads it, in typeface ``DM Sans``, not bold.
        """
        shapes = corpus_export("06")
        _, frame = _frame_for(shapes, _grid_rect(pills_table), "fixture 06's table")
        labels = [cell for cell in pills_table.cells if cell.col == 0 and cell.row > 0]
        assert tuple(_normalised(cell.text) for cell in labels) == MEASURE_LABELS and all(
            cell.style["fontWeight"] == "400" for cell in labels
        ), f"fixture drift: measure labels {[(c.text, c.style['fontWeight']) for c in labels]}"
        for cell in labels:
            origin = frame.table.rows[cell.row][cell.col]
            runs = _runs(origin)
            assert (
                _normalised(origin.text) == _normalised(cell.text)
                and runs
                and all((run.typeface, run.bold) == ("DM Sans", False) for run in runs)
            ), (
                f"the measure label {cell.text!r}: slot ({cell.row}, 0) reads {origin.text!r} with "
                f"runs {_describe_runs(origin)}; expected DM Sans, not bold"
            )


# ---------------------------------------------------------------------------
# The dense table (fixture 15): zebra rows and a badge in every row
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestDenseTable:
    def test_fixture_15_is_one_native_table_filled_as_the_screen_shows(
        self, corpus_export: Callable[[str], list[Shape]], dense_table: BrowserTable
    ) -> None:
        """Fixture 15 is ONE native table, each cell filled with the colour the screen shows.

        Exactly one ``a:tbl`` on the slide, at the browser's grid line for line
        and span for span. Each cell's fill is the colour its corner shows on
        screen: the header's accent, the zebra rows' ``F1EFEB`` (set on their
        ``tr``), and the grand row's ink, which its cells set over their zebra
        ``tr``. A cell the slide's paper shows through is unfilled.
        """
        document = corpus_document("15")
        shapes = corpus_export("15")
        frames = table_frames(shapes)
        assert len(frames) == 1, (
            f"fixture 15: expected one native table, found {len(frames)}:\n{_describe(shapes)}"
        )
        _, frame = _frame_for(shapes, _grid_rect(dense_table), "fixture 15's table")
        _assert_grid_matches(frame, dense_table, "fixture 15's table")
        corners = browser_pixels(document, [(cell.x + 3, cell.y + 3) for cell in dense_table.cells])
        shown = {_hex(pixel) for pixel in corners}
        assert {HEADER_FILL, ZEBRA_FILL, INK, PAPER} <= shown, (
            f"fixture drift: fixture 15's cells show {sorted(shown)}"
        )
        problems = []
        for cell, pixel in zip(dense_table.cells, corners):
            expected = None if _hex(pixel) == PAPER else _hex(pixel)
            origin = frame.table.rows[cell.row][cell.col]
            opaque = origin.fill_alpha is None or origin.fill_alpha >= 1 - ALPHA_TOLERANCE
            if origin.fill != expected or not opaque:
                problems.append(
                    f"slot ({cell.row}, {cell.col}) {_normalised(cell.text)!r}: filled "
                    f"{origin.fill} at {origin.fill_alpha}; the screen shows #{_hex(pixel)}"
                )
        assert not problems, "cell fills differ from the screen:\n  " + "\n  ".join(problems)

    def test_fixture_15_badges_lie_inside_their_own_cells(
        self, corpus_export: Callable[[str], list[Shape]], dense_table: BrowserTable
    ) -> None:
        """Each badge is one shape or picture inside its own "Change" cell, over the table.

        As fixture 06's pills: inside the browser box and the grid cell of the
        cell holding it, after the frame in the spTree, its label one text box
        centred on it, and its cell's ``a:tc`` holding no text.
        """
        document = corpus_document("15")
        shapes = corpus_export("15")
        frame_position, frame = _frame_for(shapes, _grid_rect(dense_table), "fixture 15's table")
        badges = browser_each_rect(document, DELTA_PILL)
        _assert_pills_overlaid(
            shapes, frame_position, frame, dense_table, badges, DENSE_BADGES, DENSE_CHANGE_COLUMN
        )


# ---------------------------------------------------------------------------
# Spans, captions, margins, anchors, fills and collapsed borders
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestTableStructure:
    def test_caption_is_a_text_box_outside_the_grid(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """A ``<caption>`` is no grid row: it is a text box above the frame, or below it.

        For a table captioned on top and one with ``caption-side: bottom``: the
        frame's grid is the browser's cells alone (its rows, its rect), no
        ``a:tc`` holds the caption's text, and the caption is one text box,
        entirely above the frame (or entirely below it), its middle inside the
        caption's browser rect.
        """
        document = _inline_document("caption")
        shapes = slide_shapes(inline_export("caption"))
        cell_texts = _cell_texts(shapes)
        tables = browser_tables(document, ", ".join(CAPTIONS))
        assert len(tables) == len(CAPTIONS), f"fixture drift: {len(tables)} captioned tables"
        for (selector, (caption_text, side)), table in zip(CAPTIONS.items(), tables):
            assert (
                table.caption is not None and _normalised(table.caption["text"]) == caption_text
            ), f"fixture drift: {selector}'s caption is {table.caption}"
            assert table.caption["side"] == side, f"fixture drift: {selector} caption-side"
            _, frame = _frame_for(shapes, _grid_rect(table), f"{selector}")
            _assert_grid_matches(frame, table, selector)
            assert not any(caption_text in text for text in cell_texts), (
                f"{selector}: a table cell holds the caption {caption_text!r}: {cell_texts}"
            )
            items = _text_items(shapes, caption_text)
            assert len(items) == 1, (
                f"{selector}: expected one text box holding the caption, found {len(items)}:\n"
                f"{_describe(shapes)}"
            )
            _, item = items[0]
            extent = table_extent(frame)
            if side == "top":
                outside, where = item.y + item.h <= extent["y"] + INSIDE_TOLERANCE_PX, "above"
            else:
                outside, where = item.y >= extent["y"] + extent["h"] - INSIDE_TOLERANCE_PX, "below"
            assert outside, (
                f"{selector}: the caption's box {_rect(item)} is not entirely {where} the frame "
                f"{extent}"
            )
            caption_rect = {key: table.caption[key] for key in ("x", "y", "w", "h")}
            assert _centre_inside(item, caption_rect), (
                f"{selector}: the caption's box {_rect(item)} is not at its browser rect "
                f"{caption_rect}"
            )

    def test_rowspan_is_one_cell_over_a_vertical_merge(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """``rowspan="2"`` is one ``a:tc`` with ``rowSpan="2"`` over a ``vMerge`` placeholder.

        The spanning cell reads "Industrial" and the slot below it is a
        ``vMerge`` placeholder holding no text; the whole grid is the browser's;
        and "Industrial" is written once on the slide.
        """
        document = _inline_document("rowspan")
        shapes = slide_shapes(inline_export("rowspan"))
        (table,) = browser_tables(document, "#rowspan")
        (spanning,) = table.cells_reading(ROWSPAN_LABEL)
        assert ((spanning.row, spanning.col), spanning.row_span) == (ROWSPAN_SLOT, 2), (
            f"fixture drift: {ROWSPAN_LABEL!r} is at ({spanning.row}, {spanning.col}) spanning "
            f"{spanning.row_span} rows"
        )
        _, frame = _frame_for(shapes, _grid_rect(table), "the rowspan table")
        row, col = ROWSPAN_SLOT
        origin = frame.table.rows[row][col]
        below = frame.table.rows[row + 1][col]
        assert origin.row_span == 2 and _normalised(origin.text) == ROWSPAN_LABEL, (
            f"slot {ROWSPAN_SLOT} reads {origin.text!r} with rowSpan={origin.row_span}; expected "
            f"{ROWSPAN_LABEL!r} spanning 2 rows"
        )
        assert below.v_merge and not _normalised(below.text), (
            f"the slot below {ROWSPAN_LABEL!r} is vMerge={below.v_merge} reading {below.text!r}; "
            "expected an empty vMerge placeholder"
        )
        _assert_grid_matches(frame, table, "the rowspan table")
        written = _cell_texts(shapes).count(ROWSPAN_LABEL) + len(_text_items(shapes, ROWSPAN_LABEL))
        assert written == 1, f"{ROWSPAN_LABEL!r} is written {written} times:\n{_describe(shapes)}"

    @pytest.mark.parametrize("alignment", tuple(VALIGN_COLUMNS))
    def test_vertical_alignment_is_the_cell_anchor(
        self, inline_export: Callable[[str], bytes], alignment: str
    ) -> None:
        """``vertical-align: middle`` anchors the cell ``ctr``, ``bottom`` anchors it ``b``.

        ``top`` anchors it ``t``, which is also what an ``a:tcPr`` without an
        anchor means.
        """
        document = _inline_document("valign")
        shapes = slide_shapes(inline_export("valign"))
        (table,) = browser_tables(document, "#valign")
        cell = table.cell_at(0, VALIGN_COLUMNS[alignment])
        assert cell.style["verticalAlign"] == alignment, (
            f"fixture drift: column {cell.col} is vertical-align {cell.style['verticalAlign']}"
        )
        _, frame = _frame_for(shapes, _grid_rect(table), "the valign table")
        origin = frame.table.rows[cell.row][cell.col]
        assert origin.anchor in ANCHORS[alignment], (
            f"the {alignment} cell {cell.text!r} is anchored {origin.anchor!r}; expected one of "
            f"{ANCHORS[alignment]}"
        )

    def test_margins_keep_their_size_in_either_unit(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """Margins equal the padding whichever unit pptxgenjs reads them in.

        pptxgenjs reads all four margins as points when the top one is at
        least 1, and as inches otherwise. A cell padded ``100px 12px 8px 30px``
        (an inch and more on top) and one padded ``8px 12px 8px 120px`` (1.25 in
        on the left, under an inch on top) both get ``marT`` ``marR`` ``marB``
        ``marL`` equal to their padding in EMU within 1 %.
        """
        document = _inline_document("margins")
        shapes = slide_shapes(inline_export("margins"))
        (table,) = browser_tables(document, "#margins")
        _, frame = _frame_for(shapes, _grid_rect(table), "the margins table")
        problems = []
        for row, padding in MARGIN_PADDINGS.items():
            cell = table.cell_at(row, 0)
            measured = tuple(cell.padding[side] for side in SIDES)
            assert measured == padding, f"fixture drift: row {row} is padded {measured}"
            origin = frame.table.rows[row][0]
            for side, expected in zip(SIDES, padding):
                margin = origin.margins_px[side]
                if margin is None or abs(margin - expected) > expected * MARGIN_TOLERANCE_FRACTION:
                    problems.append(
                        f"row {row} {_normalised(cell.text)!r}: {side} margin "
                        f"{'absent' if margin is None else f'{margin * EMU_PER_PX:.0f} EMU'}; "
                        f"padding {expected:g} px is {expected * EMU_PER_PX:.0f} EMU"
                    )
        assert not problems, "margins differ from the padding:\n  " + "\n  ".join(problems)

    def test_collapsed_edges_take_the_css_winner_on_both_cells(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """Each shared edge is the border CSS collapses it to, written on both of its cells.

        Three edges, each decided a different way and each read off the screen:
        a wider border beats a thinner one, ``solid`` beats ``dashed`` at equal
        width, and at equal width and style the earlier (left) cell's border
        wins. On each, the winner (colour, width, solid) is the ``lnB`` of the
        cell above and the ``lnT`` of the cell below, or the ``lnR`` of the left
        cell and the ``lnL`` of the right one, in every row and column. No shared
        edge has two different sides, and every cell writes all four sides.
        """
        document = _inline_document("collapse")
        shapes = slide_shapes(inline_export("collapse"))
        (table,) = browser_tables(document, "#collapse")
        _, frame = _frame_for(shapes, _grid_rect(table), "the collapse table")
        edges = []
        for row, (colour, width_px) in COLLAPSE_ROW_EDGES.items():
            for col in range(table.columns):
                upper, lower = table.cell_at(row - 1, col), table.cell_at(row, col)
                edges.append(
                    (
                        (colour, width_px),
                        (lower.x + lower.w / 2, lower.y),
                        (upper, "bottom", upper.borders["bottom"]),
                        (lower, "top", lower.borders["top"]),
                    )
                )
        for col, (colour, width_px) in COLLAPSE_COLUMN_EDGES.items():
            for row in range(len(table.rows)):
                left, right = table.cell_at(row, col - 1), table.cell_at(row, col)
                edges.append(
                    (
                        (colour, width_px),
                        (right.x, right.y + right.h / 2),
                        (left, "right", left.borders["right"]),
                        (right, "left", right.borders["left"]),
                    )
                )
        pixels = browser_pixels(document, [point for _, point, _, _ in edges])
        for ((colour, width_px), _, first, second), pixel in zip(edges, pixels):
            what = f"the edge between {first[0].text!r} and {second[0].text!r}"
            winner = _edge_winner(pixel, [first[2], second[2]], what)
            assert (_css_colour(winner.color)[0], winner.width_px) == (colour, width_px), (
                f"fixture drift: {what} is painted #{_hex(pixel)} by the {winner.width_px:g} px "
                f"border, not #{colour} at {width_px:g} px"
            )
            for cell, side, _ in (first, second):
                _assert_side(frame.table.rows[cell.row][cell.col], side, winner, f"{what}, {side}")
        contradictions = _shared_edge_contradictions(frame)
        assert not contradictions, "shared edges with two different sides:\n  " + "\n  ".join(
            contradictions
        )
        missing = _cells_missing_sides(frame)
        assert not missing, "cells that leave a side out:\n  " + "\n  ".join(missing)

    def test_a_cells_border_beats_its_rows_on_both_cells(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """At equal width and style, a cell's border beats a row's, though the row's is further up.

        Along the top of row 1 the row above's own ``tr`` bottom border (2 px
        solid ``FF5F46``) meets the lower cells' own top border (2 px solid
        ``1B3139``). CSS decides by origin before position, so the cell's
        colour wins, as the screen shows in every column. It is written on the
        lower cell's ``lnT`` and on the upper cell's ``lnB``, though the upper
        cell's own bottom is none.
        """
        document = _inline_document("origin")
        shapes = slide_shapes(inline_export("origin"))
        (table,) = browser_tables(document, "#origin")
        _, frame = _frame_for(shapes, _grid_rect(table), "the origin table")
        row_border = table.row_borders[ORIGIN_EDGE_ROW - 1]["bottom"]
        lowers = [cell for cell in table.cells if cell.row == ORIGIN_EDGE_ROW]
        pixels = browser_pixels(document, [(cell.x + cell.w / 2, cell.y) for cell in lowers])
        for lower, pixel in zip(lowers, pixels):
            upper = table.cell_at(ORIGIN_EDGE_ROW - 1, lower.col)
            cell_border = lower.borders["top"]
            what = f"the edge between {upper.text!r} and {lower.text!r}"
            assert (
                (row_border.width_px, row_border.style) == (cell_border.width_px, cell_border.style)
                and _css_colour(row_border.color)[0] == ORIGIN_ROW_BORDER
                and _css_colour(cell_border.color)[0] == ORIGIN_CELL_BORDER
                and upper.borders["bottom"].style == "none"
            ), f"fixture drift: {what} meets the row's {row_border} and the cell's {cell_border}"
            winner = _edge_winner(pixel, [row_border, cell_border], what)
            assert _css_colour(winner.color)[0] == ORIGIN_CELL_BORDER, (
                f"fixture drift: the browser paints #{_hex(pixel)} on {what}, the row's colour"
            )
            _assert_side(frame.table.rows[lower.row][lower.col], "top", winner, f"{what}, lnT")
            _assert_side(frame.table.rows[upper.row][upper.col], "bottom", winner, f"{what}, lnB")
        contradictions = _shared_edge_contradictions(frame)
        assert not contradictions, "shared edges with two different sides:\n  " + "\n  ".join(
            contradictions
        )

    def test_a_hidden_border_beats_a_wider_solid_one_on_both_cells(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """``hidden`` on one side of an edge beats a wider solid border: no line on either cell.

        Along the top of row 1 the upper cells' own 4 px solid ``1B3139``
        bottom meets the lower cells' ``border-top: hidden``. CSS decides
        ``hidden`` before width, and the browser paints no line there. In every
        column the upper cell's ``lnB`` and the lower cell's ``lnT`` are written
        and draw no line, and each margin along the edge is the cell's padding
        alone: a hidden edge takes no width into either cell.
        """
        document = _inline_document("precedence")
        shapes = slide_shapes(inline_export("precedence"))
        (table,) = browser_tables(document, HIDDEN_EDGE_TABLE)
        _, frame = _frame_for(shapes, _grid_rect(table), "the hidden-edge table")
        _assert_grid_matches(frame, table, "the hidden-edge table")
        lowers = [cell for cell in table.cells if cell.row == HIDDEN_EDGE_ROW]
        pixels = browser_pixels(document, [(cell.x + cell.w / 2, cell.y) for cell in lowers])
        problems = []
        for lower, pixel in zip(lowers, pixels):
            upper = table.cell_at(HIDDEN_EDGE_ROW - 1, lower.col)
            what = f"the edge between {upper.text!r} and {lower.text!r}"
            loser = upper.borders["bottom"]
            meeting = (
                (loser.style, loser.width_px, _css_colour(loser.color)[0]),
                lower.borders["top"],
            )
            assert meeting[0] == HIDDEN_EDGE_LOSER and meeting[1].style == "hidden", (
                f"fixture drift: {what} meets {loser} and {meeting[1]}"
            )
            assert _hex(pixel) != INK, f"fixture drift: the browser paints #{INK} on {what}"
            for cell, side in ((upper, "bottom"), (lower, "top")):
                origin = frame.table.rows[cell.row][cell.col]
                if side not in origin.sides_written or origin.borders[side] is not None:
                    problems.append(
                        f"{what}: {cell.text!r} writes its {side} side as {origin.borders[side]} "
                        f"(written: {sorted(origin.sides_written)}); the browser draws no line"
                    )
                problem = _margin_problem(
                    origin, side, cell.padding[side], f"{what}, {cell.text!r}"
                )
                if problem:
                    problems.append(problem)
        assert not problems, "the hidden edge is not one unlined edge:\n  " + "\n  ".join(problems)
        contradictions = _shared_edge_contradictions(frame)
        assert not contradictions, "shared edges with two different sides:\n  " + "\n  ".join(
            contradictions
        )

    def test_in_right_to_left_the_cell_further_right_wins_a_tie(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """In a right-to-left table an equal tie goes to the cell further right, on both cells.

        ``direction: rtl`` puts each row's first cell on the right. Along the
        edge between the two columns the right cell's own left border (2 px
        solid ``FF5F46``) meets the left cell's own right border (2 px solid
        ``1B3139``): equal width, style and origin, so position decides, and in
        a right-to-left table the cell further right wins, as the screen shows.
        The a:tbl's columns run left to right on the slide, each cell in the
        grid cell under its browser box, and the winner is the right cell's
        ``lnL`` and the left cell's ``lnR`` in every row.
        """
        document = _inline_document("precedence")
        shapes = slide_shapes(inline_export("precedence"))
        (table,) = browser_tables(document, RTL_EDGE_TABLE)
        _, frame = _frame_for(shapes, _grid_rect(table), "the right-to-left table")
        assert len(frame.table.col_widths) == table.columns and len(frame.table.row_heights) == len(
            table.rows
        ), f"the right-to-left grid is {frame.table.row_heights} by {frame.table.col_widths}"
        edges = []
        for row in range(len(table.rows)):
            first, second = table.cell_at(row, 0), table.cell_at(row, 1)
            assert first.x > second.x, (
                f"fixture drift: row {row}'s first cell {first.rect} is not right of {second.rect}"
            )
            edges.append((first, second))
        pixels = browser_pixels(document, [(right.x, right.y + right.h / 2) for right, _ in edges])
        for (right, left), pixel in zip(edges, pixels):
            what = f"the edge between {right.text!r} (right) and {left.text!r} (left)"
            winner = _edge_winner(pixel, [right.borders["left"], left.borders["right"]], what)
            assert (_css_colour(winner.color)[0], winner.width_px) == RTL_EDGE_WINNER, (
                f"fixture drift: the browser paints #{_hex(pixel)} on {what}"
            )
            right_slot = _slot_under(frame, right)
            left_slot = _slot_under(frame, left)
            assert right_slot[0] == left_slot[0] and right_slot[1] > left_slot[1], (
                f"{what}: the right cell is in slot {right_slot}, the left one in {left_slot}"
            )
            right_cell = frame.table.rows[right_slot[0]][right_slot[1]]
            left_cell = frame.table.rows[left_slot[0]][left_slot[1]]
            _assert_side(right_cell, "left", winner, f"{what}, lnL")
            _assert_side(left_cell, "right", winner, f"{what}, lnR")
        contradictions = _shared_edge_contradictions(frame)
        assert not contradictions, "shared edges with two different sides:\n  " + "\n  ".join(
            contradictions
        )

    def test_alike_separated_borders_side_by_side_are_one_line_as_wide_as_both(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """Separated, unspaced cells whose meeting borders are alike are one native line, both wide.

        ``border-collapse: separate`` with ``border-spacing: 0``: the upper
        cells' own 2 px solid ``1B3139`` bottoms and the lower cells' own 2 px
        solid ``1B3139`` tops paint side by side, one 4 px rule on screen. The
        table stays native, and in every column the upper cell's ``lnB`` and the
        lower cell's ``lnT`` are that colour at the two widths' sum (within
        0.5 px). The margin on each side of the edge is the cell's padding plus
        its own whole border, where the browser starts its content.
        """
        document = _inline_document("doubled")
        shapes = slide_shapes(inline_export("doubled"))
        (table,) = browser_tables(document, ALIKE_TABLE)
        assert table.border_collapse == "separate" and table.border_spacing == "0px", (
            f"fixture drift: the alike table is {table.border_collapse} {table.border_spacing}"
        )
        _, frame = _frame_for(shapes, _grid_rect(table), "the alike doubled table")
        _assert_grid_matches(frame, table, "the alike doubled table")
        lowers = [cell for cell in table.cells if cell.row == DOUBLED_ROW]
        band = [(cell.x + cell.w / 2, cell.y + offset) for cell in lowers for offset in (-1.5, 1.5)]
        assert {_hex(pixel) for pixel in browser_pixels(document, band)} == {INK}, (
            "fixture drift: the browser does not paint one 4 px ink rule along the edge"
        )
        problems = []
        for lower in lowers:
            upper = table.cell_at(DOUBLED_ROW - 1, lower.col)
            what = f"the edge between {upper.text!r} and {lower.text!r}"
            for cell, side in ((upper, "bottom"), (lower, "top")):
                own = cell.borders[side]
                assert (own.style, own.width_px, _css_colour(own.color)[0]) == (
                    "solid",
                    DOUBLED_SIDE_PX,
                    INK,
                ), f"fixture drift: {cell.text!r}'s {side} border is {own}"
                origin = frame.table.rows[cell.row][cell.col]
                border = origin.borders[side]
                expected_pt = 2 * DOUBLED_SIDE_PX * PT_PER_PX
                if (
                    border is None
                    or border.color != INK
                    or abs((border.width_pt or 0.0) - expected_pt)
                    > DOUBLED_WIDTH_TOLERANCE_PX * PT_PER_PX
                ):
                    problems.append(
                        f"{what}: {cell.text!r}'s {side} side is {border}; the browser paints "
                        f"{2 * DOUBLED_SIDE_PX:g} px ({expected_pt:g} pt) #{INK}"
                    )
                problem = _margin_problem(
                    origin, side, cell.padding[side] + own.width_px, f"{what}, {cell.text!r}"
                )
                if problem:
                    problems.append(problem)
        assert not problems, "the doubled rule is not one line as wide as both:\n  " + (
            "\n  ".join(problems)
        )

    def test_fill_is_the_cells_then_the_rows_then_the_row_groups(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """A cell is filled with its own background, else its row's, else its row group's.

        The ``thead``'s ink fills the header cells, the zebra row's colour fills
        its cells but the one with a background of its own, and the table's own
        white is a shape at the table's rect under the frame, not a cell fill.
        The colours are guarded against the screen: each cell's corner shows
        the colour it is expected to be filled with.
        """
        document = _inline_document("fills")
        shapes = slide_shapes(inline_export("fills"))
        (table,) = browser_tables(document, "#fills")
        corners = browser_pixels(document, [(cell.x + 3, cell.y + 3) for cell in table.cells])
        for cell, pixel in zip(table.cells, corners):
            assert _hex(pixel) == FILLS_SHOWN[(cell.row, cell.col)], (
                f"fixture drift: cell ({cell.row}, {cell.col}) shows #{_hex(pixel)}"
            )
        frame_position, frame = _frame_for(shapes, _grid_rect(table), "the fills table")
        problems = [
            f"slot {slot}: filled {_owner(frame, *slot).fill}; expected one of {emitted}"
            for slot, emitted in FILLS_EMITTED.items()
            if _owner(frame, *slot).fill not in emitted
        ]
        assert not problems, "cell fills differ:\n  " + "\n  ".join(problems)
        grounds = [
            (position, shape)
            for position, shape in enumerate(shapes)
            if shape.kind == "shape"
            and shape.fill == FILLS_TABLE_FILL
            and _same_rect(_box(shape), table.rect)
        ]
        assert len(grounds) == 1 and grounds[0][0] < frame_position, (
            f"the table's own fill must be one {FILLS_TABLE_FILL} shape at {table.rect} under the "
            f"frame (spTree {frame_position}); found {[(p, _rect(s)) for p, s in grounds]}"
        )

    def test_a_rows_border_beats_its_columns_at_the_tables_edge(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """At equal width and style, a row's border beats a column's on the table's own edge.

        Along the table's left edge each row's own left border (4 px solid
        ``1B3139``) meets the first column's own left border (4 px solid
        ``FF5F46``). Width and style tie, so origin decides: a row beats a
        column, as the screen shows in every row. Each row's first cell writes
        the row's line as its ``lnL``.
        """
        document = _inline_document("precedence")
        shapes = slide_shapes(inline_export("precedence"))
        (table,) = browser_tables(document, COLROW_TABLE)
        _, frame = _frame_for(shapes, _grid_rect(table), "the column-and-row table")
        firsts = [cell for cell in table.cells if cell.col == 0]
        pixels = browser_pixels(document, [(cell.x + 1, cell.y + cell.h / 2) for cell in firsts])
        for cell, pixel in zip(firsts, pixels):
            row_border = table.row_borders[cell.row]["left"]
            what = f"the table's left edge beside {cell.text!r}"
            assert (
                row_border.style,
                row_border.width_px,
                _css_colour(row_border.color)[0],
            ) == ("solid", COLROW_WINNER[1], COLROW_WINNER[0]) and cell.borders["left"].style == (
                "none"
            ), f"fixture drift: {what} meets the row's {row_border} and {cell.borders['left']}"
            assert _hex(pixel) == COLROW_WINNER[0] != COLROW_LOSER, (
                f"fixture drift: the browser paints #{_hex(pixel)} on {what}"
            )
            _assert_side(frame.table.rows[cell.row][0], "left", row_border, f"{what}, lnL")
        contradictions = _shared_edge_contradictions(frame)
        assert not contradictions, "shared edges with two different sides:\n  " + "\n  ".join(
            contradictions
        )

    def test_a_cell_holding_block_layout_keeps_the_table_native(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """A cell holding block layout keeps its table native, its content overlaid.

        One cell holds two stacked ``<div>``s. The table is ONE native
        ``a:tbl`` on the browser's grid; that cell's ``a:tc`` holds no text;
        each div's line is one text box inside the cell, at its browser line
        box within 1 px; and every other cell keeps its text in its own ``a:tc``.
        """
        document = _inline_document("blocks")
        shapes = slide_shapes(inline_export("blocks"))
        (table,) = browser_tables(document, BLOCKS_TABLE)
        grid = _grid_rect(table)
        on_the_table = _frames_over(shapes, grid)
        assert len(on_the_table) == 1, (
            f"expected one native table on the table whose cell holds blocks, found "
            f"{on_the_table}:\n{_describe(shapes)}"
        )
        _, frame = _frame_for(shapes, grid, "the table whose cell holds blocks")
        _assert_grid_matches(frame, table, "the table whose cell holds blocks")
        block = table.cell_at(*BLOCK_CELL_SLOT)
        origin = frame.table.rows[block.row][block.col]
        assert not _normalised(origin.text), (
            f"the cell holding blocks writes {origin.text!r} in its a:tc; its content is overlaid"
        )
        for selector, text in BLOCK_TEXTS:
            lines = browser_line_boxes(document, selector)
            assert [line["text"] for line in lines] == [text], f"fixture drift: {selector} {lines}"
            _assert_text_at_line(
                shapes, lines[0], block.rect, f"the block {selector}", document, selector
            )
        for cell in table.cells:
            if (cell.row, cell.col) == BLOCK_CELL_SLOT:
                continue
            written = frame.table.rows[cell.row][cell.col]
            assert _normalised(written.text) == _normalised(cell.text), (
                f"slot ({cell.row}, {cell.col}) reads {written.text!r}, the browser {cell.text!r}"
            )

    def test_text_running_into_a_block_in_a_cell_is_overlay_text_written_once(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """A cell's own text that runs straight into a block child is overlaid once, not its a:tc's.

        ``<td>Revenue<div>FY24 restated</div></td>``: "Revenue" is the cell's
        own text and the div a block after it, with no white space between.
        The cell holds block layout, so the table stays native and the cell's
        ``a:tc`` holds no text (not "Revenue" alone, as one paragraph of its
        own): each of the cell's two browser lines is one text box at its line
        box within 1 px, and neither is written anywhere else.
        """
        document = _inline_document("blocks")
        shapes = slide_shapes(inline_export("blocks"))
        (table,) = browser_tables(document, TRAP_TABLE)
        _, frame = _frame_for(shapes, _grid_rect(table), "the table whose cell runs into a block")
        trap = table.cell_at(*TRAP_SLOT)
        lines = browser_line_boxes(document, TRAP_CELL)
        assert tuple(line["text"] for line in lines) == tuple(text for text, _ in TRAP_LINES), (
            f"fixture drift: {lines}"
        )
        origin = frame.table.rows[trap.row][trap.col]
        assert not _normalised(origin.text), (
            f"the cell writes {origin.text!r} in its a:tc; its content is overlaid"
        )
        for line, (_, styled) in zip(lines, TRAP_LINES):
            _assert_text_at_line(
                shapes, line, trap.rect, f"the cell's line {line['text']!r}", document, styled
            )
            written = _cell_text_written_once(shapes, line["text"])
            assert written == 1, (
                f"{line['text']!r} is written {written} times:\n{_describe(shapes)}"
            )

    @pytest.mark.parametrize("selector", DOT_TABLES)
    def test_a_cells_pseudo_element_dot_is_an_item_over_the_native_table(
        self, inline_export: Callable[[str], bytes], selector: str
    ) -> None:
        """A cell's ``::before`` dot is an item of its own over the table, which stays native.

        Each first cell draws a status dot as its ``::before``: an inline-block
        in its line, or an absolutely positioned box. The table is one native
        frame on the browser's grid; each dot is one shape filled ``FF5F46`` at
        its pseudo-element's box within 0.5 px, inside its cell, after the frame
        in the spTree; each cell's text is written exactly once.
        """
        document = _inline_document("dots")
        shapes = slide_shapes(inline_export("dots"))
        (table,) = browser_tables(document, selector)
        frame_position, frame = _frame_for(shapes, _grid_rect(table), f"the {selector} table")
        _assert_grid_matches(frame, table, f"the {selector} table")
        hosts = [cell for cell in table.cells if cell.col == 0]
        dots = browser_each_pseudo(document, f"{selector} td:first-child", "before")
        assert len(dots) == len(hosts) and all(dots), f"fixture drift: {selector} dots {dots}"
        for host, dot in zip(hosts, dots):
            box = {key: dot[key] for key in ("x", "y", "w", "h")}
            what = f"{host.text!r}'s dot at {box}"
            at_dot = [
                (position, shape)
                for position, shape in enumerate(shapes)
                if shape.kind == "shape"
                and shape.fill == DOT_FILL
                and _same_rect(_box(shape), box, DOT_TOLERANCE_PX)
            ]
            assert len(at_dot) == 1, (
                f"{what}: expected one {DOT_FILL} shape at its box, found {len(at_dot)}:\n"
                f"{_describe(shapes)}"
            )
            position, item = at_dot[0]
            assert _inside(_box(item), host.rect) and position > frame_position, (
                f"{what}: the shape {_rect(item)} at spTree {position} is not inside its cell "
                f"{host.rect} over the table at {frame_position}"
            )
        for cell in table.cells:
            written = _cell_text_written_once(shapes, _normalised(cell.text))
            assert written == 1, f"{cell.text!r} is written {written} times:\n{_describe(shapes)}"

    def test_relatively_positioned_cells_keep_the_table_native(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """Cells with ``position: relative`` and no offset lie on the grid: the table is native.

        One native frame on the browser's grid, each ``a:tc`` reading its cell.
        """
        document = _inline_document("loose")
        shapes = slide_shapes(inline_export("loose"))
        (table,) = browser_tables(document, RELATIVE_TABLE)
        _, frame = _frame_for(shapes, _grid_rect(table), "the relatively positioned table")
        _assert_grid_matches(frame, table, "the relatively positioned table")
        for cell in table.cells:
            written = frame.table.rows[cell.row][cell.col]
            assert _normalised(written.text) == _normalised(cell.text), (
                f"slot ({cell.row}, {cell.col}) reads {written.text!r}, the browser {cell.text!r}"
            )

    def test_a_cell_that_clips_its_overflow_keeps_the_table_native(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """A cell whose own overflow clip cuts its text keeps the table native, its text overlaid.

        The table is one native frame on the browser's grid. One cell
        (``overflow: hidden``, ``text-overflow: clip``, ``nowrap``) holds a
        line far wider than its padding box: its ``a:tc`` holds no text, and its
        overlay text reads exactly the words its clip shows at least 2 px of,
        in order; no word past the clip is on the slide. The cell beside it
        clips too, but its text fits: it stays the ``a:tc``'s own. A cell cut by
        ``text-overflow: ellipsis`` instead reads as the screen shows it
        (``test_export_snapshot_rotation.py``).
        """
        document = _inline_document("loose")
        shapes = slide_shapes(inline_export("loose"))
        (table,) = browser_tables(document, OVERFLOW_TABLE)
        _, frame = _frame_for(shapes, _grid_rect(table), "the table whose cell clips")
        _assert_grid_matches(frame, table, "the table whose cell clips")
        clip = browser_padding_box(document, ELLIPSIS_CELL)
        words = browser_each_rect(document, ELLIPSIS_WORDS)
        assert len(words) == len(ELLIPSIS_WORD_TEXTS), f"fixture drift: {len(words)} words"
        right = clip["x"] + clip["w"]
        shown = [
            text
            for text, rect in zip(ELLIPSIS_WORD_TEXTS, words)
            if min(rect["x"] + rect["w"], right) - max(rect["x"], clip["x"]) >= MINIMUM_VISIBLE_PX
        ]
        hidden = [text for text in ELLIPSIS_WORD_TEXTS if text not in shown]
        assert shown and hidden, f"fixture drift: the clip shows {shown} and hides {hidden}"
        cell = table.cell_at(*ELLIPSIS_SLOT)
        origin = frame.table.rows[cell.row][cell.col]
        assert not _normalised(origin.text), (
            f"the clipped cell writes {origin.text!r} in its a:tc; its text is overlaid"
        )
        overlay = sorted(
            (
                shape
                for shape in shapes
                if shape.kind == "text"
                and cell.y <= shape.y + shape.h / 2 <= cell.y + cell.h
                and cell.x - INSIDE_TOLERANCE_PX <= shape.x < right
            ),
            key=lambda shape: shape.x,
        )
        read = " ".join(_normalised(shape.text) for shape in overlay)
        assert read == " ".join(shown), (
            f"the clipped cell's overlay reads {read!r}; its clip shows {' '.join(shown)!r}"
        )
        leaked = [
            word
            for word in hidden
            if any(
                word in _normalised(shape.text).split() for shape in shapes if shape.kind == "text"
            )
            or any(word in text.split() for text in _cell_texts(shapes))
        ]
        assert not leaked, f"words past the clip are on the slide: {leaked}"
        fits = table.cell_at(*FITS_SLOT)
        written = frame.table.rows[fits.row][fits.col]
        assert _normalised(written.text) == _normalised(fits.text), (
            f"the cell whose text fits reads {written.text!r}, the browser {fits.text!r}"
        )

    def test_a_captured_table_box_holds_none_of_the_lines_its_grid_draws(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """A collapsed native table whose own box is a picture leaves its lines to the grid.

        The table's background is a gradient, so its box is a box-only picture
        under the frame. Its 1 px ``DCE0E2`` rules and its 3 px ``1B3139``
        border are drawn by the ``a:tbl``: the picture shows none of them where
        the screen does (it would draw every line twice), and the grid writes
        them, the rules on both cells of each edge and the border on its outer
        cells.
        """
        document = _inline_document("captured")
        shapes = slide_shapes(inline_export("captured"))
        (table,) = browser_tables(document, GRAD_TABLE)
        frame_position, frame = _frame_for(shapes, _grid_rect(table), "the captured table")
        pictures = [
            (position, shape)
            for position, shape in enumerate(shapes)
            if shape.kind == "picture" and _same_rect(_box(shape), table.rect)
        ]
        assert len(pictures) == 1 and pictures[0][0] < frame_position, (
            f"expected the table's box as one picture at {table.rect} under the frame (spTree "
            f"{frame_position}):\n{_describe(shapes)}"
        )
        picture = pictures[0][1]
        image = Image.open(BytesIO(picture.image)).convert("RGBA")
        lowers = [cell for cell in table.cells if cell.row > 0]
        rule_points = [
            (lower, (lower.x + lower.w / 2, lower.y + offset))
            for lower in lowers
            for offset in (-1.0, -0.5, 0.0, 0.5)
        ]
        firsts = [cell for cell in table.cells if cell.col == 0]
        border_points = [(cell, (cell.x, cell.y + cell.h / 2)) for cell in firsts]
        pixels = browser_pixels(document, [point for _, point in rule_points + border_points])
        on_rules = [
            (lower, point)
            for (lower, point), pixel in zip(rule_points, pixels[: len(rule_points)])
            if _hex(pixel) == RULE
        ]
        assert {id(lower) for lower, _ in on_rules} == {id(lower) for lower in lowers}, (
            "fixture drift: the browser does not paint a DCE0E2 rule along every row edge"
        )
        assert all(_hex(pixel) == INK for pixel in pixels[len(rule_points) :]), (
            "fixture drift: the browser does not paint the 1B3139 border along the left edge"
        )
        drawn_twice = [
            f"{colour} at {point}"
            for colour, points in ((RULE, on_rules), (INK, border_points))
            for _, point in points
            if _near(_picture_pixel(image, picture, *point), colour)
        ]
        assert not drawn_twice, "the table's picture paints lines its grid draws too: " + ", ".join(
            drawn_twice
        )
        for lower in lowers:
            upper = table.cell_at(lower.row - 1, lower.col)
            what = f"the edge between {upper.text!r} and {lower.text!r}"
            rule = upper.borders["bottom"]
            _assert_side(frame.table.rows[upper.row][upper.col], "bottom", rule, f"{what}, lnB")
            _assert_side(frame.table.rows[lower.row][lower.col], "top", rule, f"{what}, lnT")
        border = BrowserBorder(width_px=GRAD_BORDER[1], style="solid", color="rgb(27, 49, 57)")
        for cell in firsts:
            _assert_side(frame.table.rows[cell.row][0], "left", border, f"{cell.text!r}, lnL")


# ---------------------------------------------------------------------------
# When a:tbl cannot draw a table: positioned items, all editable
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestPositionedTables:
    def test_cells_with_visible_gaps_are_positioned_items(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """Filled cards in a ``border-spacing: 8px`` table become shapes and text boxes.

        No ``a:tbl`` has gaps between its cells, so the table is no native
        frame: each card is one white shape at its browser cell rect within
        1 px, and every word of the table is on the slide as editable text.
        """
        document = _inline_document("cards")
        pptx = inline_export("cards")
        shapes = slide_shapes(pptx)
        (table,) = browser_tables(document, "#cards")
        assert table.border_collapse == "separate" and table.border_spacing == "8px", (
            f"fixture drift: the cards table is {table.border_collapse} {table.border_spacing}"
        )
        assert not table_frames(shapes), (
            f"the cards table has gaps no a:tbl can draw, yet the slide holds a native table:\n"
            f"{_describe(shapes)}"
        )
        for cell in table.cells:
            assert _css_colour(cell.style["backgroundColor"])[0] == CARD_FILL, "fixture drift"
            cards = [
                shape
                for shape in shapes
                if shape.kind == "shape"
                and shape.fill == CARD_FILL
                and _same_rect(_box(shape), cell.rect)
            ]
            assert len(cards) == 1, (
                f"the card {cell.text!r}: expected one {CARD_FILL} shape at {cell.rect}, found "
                f"{len(cards)}:\n{_describe(shapes)}"
            )
            assert _text_items(shapes, _normalised(cell.text)), (
                f"the card {cell.text!r} is not an editable text box:\n{_describe(shapes)}"
            )
        assert slide_text_loss(pptx, 0, document) == [], "the cards table lost text"

    def test_spacing_nothing_shows_keeps_the_table_native(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """A plain table (``separate``, default 2 px spacing, no cell fill or border) stays native.

        Its gaps show only the table's own background, so they are invisible:
        it is one ``a:tbl`` of the browser's three columns and three rows, each
        ``a:tc`` reading its cell, every inner grid line inside the gap between
        the browser's cells it separates, and the outer lines between the
        table's box and its outer cells. The table's own white, rounded and
        shadowed background is a shape at its rect under the frame.
        """
        document = _inline_document("plain")
        shapes = slide_shapes(inline_export("plain"))
        (table,) = browser_tables(document, "#plain")
        spacing = [float(value.removesuffix("px")) for value in table.border_spacing.split()]
        assert table.border_collapse == "separate" and max(spacing) > VISIBLE_SPACING_PX, (
            f"fixture drift: the plain table is {table.border_collapse} {table.border_spacing}"
        )
        for cell in table.cells:
            assert cell.style["backgroundColor"] == TRANSPARENT and all(
                border.style == "none" for border in cell.borders.values()
            ), f"fixture drift: the plain cell {cell.text!r} paints a fill or border"
        grid = _grid_rect(table)
        frames = table_frames(shapes)
        assert len(frames) == 1, (
            f"the plain table's spacing shows nothing, so it must be one native table; found "
            f"{len(frames)}:\n{_describe(shapes)}"
        )
        frame_position, frame = frames[0]
        assert len(frame.table.col_widths) == table.columns and len(frame.table.row_heights) == len(
            table.rows
        ), (
            f"the plain table's grid is {len(frame.table.row_heights)}x"
            f"{len(frame.table.col_widths)}; "
            f"the browser's is {len(table.rows)}x{table.columns} (no column or row for a gap)"
        )
        for cell in table.cells:
            origin = frame.table.rows[cell.row][cell.col]
            assert _normalised(origin.text) == _normalised(cell.text), (
                f"slot ({cell.row}, {cell.col}) reads {origin.text!r}, the browser {cell.text!r}"
            )
        columns = table_column_edges(frame)
        rows = table_row_edges(frame)
        problems = []
        for index, edge in enumerate(columns):
            before = [cell.x + cell.w for cell in table.cells if cell.col + cell.col_span == index]
            after = [cell.x for cell in table.cells if cell.col == index]
            low = max(before) if before else table.x
            high = min(after) if after else table.x + table.w
            if not low - RECT_TOLERANCE_PX <= edge <= high + RECT_TOLERANCE_PX:
                problems.append(
                    f"column line {index} at {edge:.2f}, outside the gap {low:.2f}..{high:.2f}"
                )
        for index, edge in enumerate(rows):
            before = [cell.y + cell.h for cell in table.cells if cell.row + cell.row_span == index]
            after = [cell.y for cell in table.cells if cell.row == index]
            low = max(before) if before else table.y
            high = min(after) if after else table.y + table.h
            if not low - RECT_TOLERANCE_PX <= edge <= high + RECT_TOLERANCE_PX:
                problems.append(
                    f"row line {index} at {edge:.2f}, outside the gap {low:.2f}..{high:.2f}"
                )
        assert not problems, (
            f"the plain table's grid lines are not in the browser's gaps (grid {grid}):\n  "
            + "\n  ".join(problems)
        )
        grounds = [
            (position, shape)
            for position, shape in enumerate(shapes)
            if shape.kind == "shape"
            and shape.fill == PLAIN_FILL
            and _same_rect(_box(shape), table.rect)
        ]
        assert len(grounds) == 1, (
            f"expected the table's background as one {PLAIN_FILL} shape at {table.rect}, found "
            f"{len(grounds)}:\n{_describe(shapes)}"
        )
        position, ground = grounds[0]
        assert (
            ground.geometry == "roundRect"
            and ground.shadow is not None
            and position < frame_position
        ), (
            f"the table's background is a {ground.geometry} with shadow {ground.shadow} at spTree "
            f"{position}; expected a shadowed roundRect under the frame at {frame_position}"
        )

    def test_a_table_its_ancestor_cuts_is_positioned_items_clipped_to_the_cut(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """A table whose last row an ``overflow: hidden`` box cuts in half is no native table.

        An ``a:tbl`` cannot be clipped, so the cut table is positioned items,
        clipped as any others are: no native frame stands on it; every word the
        box shows is a text box inside it, the cut row's top-aligned text
        included; the cut row's bottom-aligned text, wholly below the cut, is
        on the slide nowhere; and the cut row's fill is on the slide, ending at
        the cut.
        """
        document = _inline_document("clip")
        shapes = slide_shapes(inline_export("clip"))
        (table,) = browser_tables(document, "#cut")
        box = browser_padding_box(document, CUT_BOX)
        cut = box["y"] + box["h"]
        last = table.rows[-1]
        shown = browser_rect(document, CUT_SHOWN)
        hidden = browser_rect(document, CUT_HIDDEN)
        assert last["y"] < cut < last["y"] + last["h"], (
            f"fixture drift: the box's bottom {cut:.2f} does not cut the last row {last}"
        )
        assert shown["y"] + shown["h"] <= cut <= hidden["y"], (
            f"fixture drift: the shown text {shown} and the hidden text {hidden} are not either "
            f"side of the cut at {cut:.2f}"
        )
        grid = _grid_rect(table)
        on_the_cut_table = [
            (position, table_extent(frame))
            for position, frame in table_frames(shapes)
            if overlaps(SimpleNamespace(**table_extent(frame)), SimpleNamespace(**grid))
        ]
        assert not on_the_cut_table, (
            f"a native table stands on the table the box cuts ({on_the_cut_table}); an a:tbl "
            f"cannot be clipped:\n{_describe(shapes)}"
        )
        in_box = [shape for shape in shapes if _centre_inside(shape, box, 0.0)]
        missing = [text for text in CUT_TEXTS_SHOWN if not _text_items(in_box, text)]
        assert not missing, (
            f"the box shows {missing}, which no text box inside it reads:\n{_describe(shapes)}"
        )
        leaked = [_rect(shape) for _, shape in _text_items(shapes, CUT_TEXT_HIDDEN)] + [
            text for text in _cell_texts(shapes) if CUT_TEXT_HIDDEN in text
        ]
        assert not leaked, f"the text below the cut is on the slide: {leaked}"
        fills = [shape for shape in in_box if shape.kind == "shape" and shape.fill == CUT_ROW_FILL]
        assert fills and all(shape.y + shape.h <= cut + INSIDE_TOLERANCE_PX for shape in fills), (
            f"the cut row's {CUT_ROW_FILL} fill must be on the slide and end at the cut "
            f"{cut:.2f}; found {[_rect(shape) for shape in fills]}"
        )

    def test_a_table_its_ancestor_does_not_cut_stays_native(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """The same table in an ``overflow: hidden`` box tall enough to hold it stays native.

        Only a clip that cuts the table makes it positioned items: the twin
        beside the cut table, whole inside its box, is one ``a:tbl`` whose grid
        is the browser's and whose cells read the browser's text.
        """
        document = _inline_document("clip")
        shapes = slide_shapes(inline_export("clip"))
        (table,) = browser_tables(document, "#whole")
        box = browser_padding_box(document, WHOLE_BOX)
        assert _inside(table.rect, box, 0.0), f"fixture drift: {table.rect} leaves its box {box}"
        _, frame = _frame_for(shapes, _grid_rect(table), "the uncut twin")
        _assert_grid_matches(frame, table, "the uncut twin")
        for cell in table.cells:
            origin = frame.table.rows[cell.row][cell.col]
            assert _normalised(origin.text) == _normalised(cell.text), (
                f"slot ({cell.row}, {cell.col}) reads {origin.text!r}, the browser {cell.text!r}"
            )

    def test_unlike_separated_borders_side_by_side_are_positioned_items(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """Separated, unspaced cells whose meeting borders differ in colour are positioned items.

        With ``border-spacing: 0`` the upper cells' own 2 px solid ``1B3139``
        bottoms meet the lower cells' own 2 px solid ``FF5F46`` tops: two
        lines side by side, the ink above the edge and the accent below it,
        which no one ``a:tbl`` edge draws. No native frame stands on the table;
        in every column both lines are line items along their own 2 px bands,
        and every cell's text is a text box.
        """
        document = _inline_document("doubled")
        pptx = inline_export("doubled")
        shapes = slide_shapes(pptx)
        (table,) = browser_tables(document, UNLIKE_TABLE)
        assert table.border_collapse == "separate" and table.border_spacing == "0px", (
            f"fixture drift: the unlike table is {table.border_collapse} {table.border_spacing}"
        )
        grid = _grid_rect(table)
        on_the_table = [
            (position, table_extent(frame))
            for position, frame in table_frames(shapes)
            if overlaps(SimpleNamespace(**table_extent(frame)), SimpleNamespace(**grid))
        ]
        assert not on_the_table, (
            f"a native table stands on the unlike table ({on_the_table}); no a:tbl edge draws "
            f"two lines side by side:\n{_describe(shapes)}"
        )
        lowers = [cell for cell in table.cells if cell.row == DOUBLED_ROW]
        bands = []
        for lower in lowers:
            upper = table.cell_at(DOUBLED_ROW - 1, lower.col)
            bands.append((upper, INK, lower.y - DOUBLED_SIDE_PX / 2))
            bands.append((lower, ACCENT, lower.y + DOUBLED_SIDE_PX / 2))
        pixels = browser_pixels(document, [(cell.x + cell.w / 2, y) for cell, _, y in bands])
        for (cell, colour, y), pixel in zip(bands, pixels):
            assert _hex(pixel) == colour, (
                f"fixture drift: the browser paints #{_hex(pixel)} along {cell.text!r}'s band at "
                f"{y:g}, not #{colour}"
            )
            along = [
                shape
                for shape in shapes
                if shape.kind == "line"
                and shape.line == colour
                and abs(shape.h) <= LINE_TOLERANCE_PX
                and abs(shape.y + shape.h / 2 - y) <= LINE_TOLERANCE_PX
                and shape.x <= cell.x + LINE_TOLERANCE_PX
                and shape.x + shape.w >= cell.x + cell.w - LINE_TOLERANCE_PX
            ]
            assert len(along) == 1, (
                f"{cell.text!r}: expected one #{colour} line along its band at {y:g}, found "
                f"{len(along)}:\n{_describe(shapes)}"
            )
        for cell in table.cells:
            assert _text_items(shapes, _normalised(cell.text)), (
                f"the cell {cell.text!r} is not an editable text box:\n{_describe(shapes)}"
            )

    def test_a_nested_table_makes_the_outer_table_positioned_items(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """A ``<table>`` inside a ``<td>`` makes the outer table positioned items, every word kept.

        No native frame holds the outer table's own cells: each outer cell's
        text is an editable text box. A native frame on the slide can only be
        the inner table, inside its browser rect. No word of either table is lost.
        """
        document = _inline_document("nested")
        pptx = inline_export("nested")
        shapes = slide_shapes(pptx)
        outer, inner = browser_tables(document, "#outer, #inner")
        assert _inside(inner.rect, outer.rect), "fixture drift: the inner table is not inside"
        for position, frame in table_frames(shapes):
            assert _inside(table_extent(frame), inner.rect, RECT_TOLERANCE_PX), (
                f"a native table at spTree {position} ({table_extent(frame)}) is not the inner "
                f"table at {inner.rect}: the outer table holds a nested table\n{_describe(shapes)}"
            )
        for text in OUTER_TEXTS:
            assert text not in _cell_texts(shapes) and _text_items(shapes, text), (
                f"the outer cell {text!r} must be an editable text box, not a native cell:\n"
                f"{_describe(shapes)}"
            )
        assert slide_text_loss(pptx, 0, document) == [], "the nested tables lost text"


# ---------------------------------------------------------------------------
# A hostile realm
# ---------------------------------------------------------------------------


def _custom_geometry_points(element, shape: Shape) -> list[tuple[float, float]]:
    """Every point of a custGeom shape's path, in order, in slide px (its space is its EMU)."""
    return [
        (shape.x + int(point.get("x")) / EMU_PER_PX, shape.y + int(point.get("y")) / EMU_PER_PX)
        for point in element.iterfind("p:spPr/a:custGeom/a:pathLst/a:path//a:pt", NAMESPACES)
    ]


def _inside_rounded(point: tuple[float, float], box: dict, radius: float, tolerance: float) -> bool:
    """Whether ``point`` lies in ``box``, corners rounded by ``radius``, within ``tolerance``."""
    x, y = point
    left, top = box["x"], box["y"]
    right, bottom = left + box["w"], top + box["h"]
    if not (
        left - tolerance <= x <= right + tolerance and top - tolerance <= y <= bottom + tolerance
    ):
        return False
    centre_x = min(max(x, left + radius), right - radius)
    centre_y = min(max(y, top + radius), bottom - radius)
    return ((x - centre_x) ** 2 + (y - centre_y) ** 2) ** 0.5 <= radius + tolerance


def _against_rounded_box(
    points: list[tuple[float, float]], box: dict, radius: float
) -> tuple[list[tuple[float, float]], dict[str, int]]:
    """The points outside ``box`` rounded by ``radius``, and how many lie on each corner's arc."""
    outside = [
        point for point in points if not _inside_rounded(point, box, radius, ARC_TOLERANCE_PX)
    ]
    arcs = {}
    for corner in ("top-left", "top-right", "bottom-left", "bottom-right"):
        corner_x, corner_y = _corner_of(box, corner)
        centre_x = corner_x + (radius if "left" in corner else -radius)
        centre_y = corner_y + (radius if "top" in corner else -radius)
        arcs[corner] = len(
            [
                point
                for point in points
                if abs(math.hypot(point[0] - centre_x, point[1] - centre_y) - radius)
                <= ARC_TOLERANCE_PX
                and abs(point[0] - centre_x) > ARC_TOLERANCE_PX
                and abs(point[1] - centre_y) > ARC_TOLERANCE_PX
            ]
        )
    return outside, arcs


def _corner_of(rect: dict, corner: str) -> tuple[float, float]:
    vertical, horizontal = corner.split("-")
    return (
        rect["x"] + (rect["w"] if horizontal == "right" else 0),
        rect["y"] + (rect["h"] if vertical == "bottom" else 0),
    )


def _inside_polygon(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    """Whether ``point`` lies inside the closed ``polygon`` (even-odd ray casting)."""
    x, y = point
    inside = False
    for index, (x1, y1) in enumerate(polygon):
        x2, y2 = polygon[index - 1]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _opaque_slot(frame: Shape, row: int, col: int) -> bool:
    """Whether grid slot ``(row, col)`` lies in the table and its a:tc paints an opaque fill."""
    assert frame.table is not None
    if not (0 <= row < len(frame.table.row_heights) and 0 <= col < len(frame.table.col_widths)):
        return False
    owner_row, owner_col = table_slot_owner(frame.table, row, col)
    cell = frame.table.rows[owner_row][owner_col]
    return cell.fill is not None and cell.fill_alpha is None


def _corner_piece_position(shapes: list[Shape], frame_position: int, fill: str, rect: dict) -> int:
    """The position in paint order of the one custom shape under the frame filled ``fill``
    whose box holds the centre of the cell ``rect``: the corner cell's piece."""
    centre = (rect["x"] + rect["w"] / 2, rect["y"] + rect["h"] / 2)
    found = [
        position
        for position, shape in enumerate(shapes[:frame_position])
        if shape.geometry == "custGeom"
        and shape.fill == fill
        and shape.x <= centre[0] <= shape.x + shape.w
        and shape.y <= centre[1] <= shape.y + shape.h
    ]
    assert len(found) == 1, (
        f"expected one {fill} custom shape under the table at {rect}, got {len(found)}:\n"
        f"{_describe(shapes)}"
    )
    return found[0]


def _corner_piece(
    shapes: list[Shape], elements: list, frame_position: int, fill: str, rect: dict
) -> list[tuple[float, float]]:
    """The vertices of the corner cell's piece (_corner_piece_position)."""
    position = _corner_piece_position(shapes, frame_position, fill, rect)
    return _custom_geometry_points(elements[position], shapes[position])


@pytest.mark.slow
@requires_huashu_sidecar
class TestRoundedWrapper:
    def test_corner_cells_are_filled_by_shapes_cut_to_the_wrappers_corners(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """The data table in its rounded wrapper: its four corner cells round with the wrapper.

        The wrapper clips the table to its padding box, 8 px round at each
        corner, so the browser shows the coral header's top corners and the
        last row's bottom corners round. An a:tc cannot be clipped. So the
        table stays one native frame on the browser's grid, every cell's text
        its own, and each corner cell's a:tc is unfilled; under the frame, one
        custom shape per corner cell paints its fill: its cell's rect within
        0.5 px, every vertex inside the wrapper's rounded box, the cell's
        corner itself replaced by the 8 px arc (a vertex on the arc, none at
        the corner). Every other cell keeps its own fill.
        """
        document = _inline_document("rounded")
        pptx = inline_export("rounded")
        shapes = slide_shapes(pptx)
        elements = slide_shape_elements(pptx)
        (table,) = browser_tables(document, "table")
        wrapper = browser_rect(document, ROUNDED_WRAPPER)
        frame_position, frame = _frame_for(shapes, _grid_rect(table), "the rounded data table")
        _assert_grid_matches(frame, table, "the rounded data table")

        wrong = []
        for row, fills in enumerate(ROUNDED_FILLS):
            for col, fill in enumerate(fills):
                cell = frame.table.rows[row][col]
                corner = ROUNDED_CORNERS.get((row, col))
                expected = None if corner else fill
                if cell.fill != expected:
                    wrong.append(f"slot ({row}, {col}): a:tc fill {cell.fill}, expected {expected}")
                if not corner:
                    continue
                rect = table_cell_rect(frame, row, col)
                under = [
                    position
                    for position, shape in enumerate(shapes[:frame_position])
                    if shape.kind == "shape"
                    and shape.geometry == "custGeom"
                    and shape.fill == fill
                    and _same_rect(_box(shape), rect, 0.5)
                ]
                if len(under) != 1:
                    wrong.append(
                        f"slot ({row}, {col}): {len(under)} {fill} custom shapes at its rect "
                        f"{rect} "
                        "under the table"
                    )
                    continue
                shape = shapes[under[0]]
                points = _custom_geometry_points(elements[under[0]], shape)
                outside = [
                    point
                    for point in points
                    if not _inside_rounded(point, wrapper, ROUNDED_RADIUS_PX, ARC_TOLERANCE_PX)
                ]
                corner_x, corner_y = _corner_of(rect, corner)
                at_corner = [
                    point
                    for point in points
                    if abs(point[0] - corner_x) <= ARC_TOLERANCE_PX
                    and abs(point[1] - corner_y) <= ARC_TOLERANCE_PX
                ]
                centre_x = corner_x + (
                    ROUNDED_RADIUS_PX if "left" in corner else -ROUNDED_RADIUS_PX
                )
                centre_y = corner_y + (ROUNDED_RADIUS_PX if "top" in corner else -ROUNDED_RADIUS_PX)
                on_arc = [
                    point
                    for point in points
                    if abs(
                        ((point[0] - centre_x) ** 2 + (point[1] - centre_y) ** 2) ** 0.5
                        - ROUNDED_RADIUS_PX
                    )
                    <= ARC_TOLERANCE_PX
                    and abs(point[0] - centre_x) > ARC_TOLERANCE_PX
                    and abs(point[1] - centre_y) > ARC_TOLERANCE_PX
                ]
                if outside or at_corner or not on_arc or shape.line is not None:
                    wrong.append(
                        f"slot ({row}, {col}) {corner}: vertices outside the wrapper "
                        f"{outside[:3]}, "
                        f"at the square corner {at_corner}, on the arc {len(on_arc)}, outline "
                        f"{shape.line}"
                    )
        assert not wrong, "the corner cells do not round with the wrapper:\n" + "\n".join(
            [*wrong, _describe(shapes)]
        )
        for cell in table.cells:
            origin = frame.table.rows[cell.row][cell.col]
            assert _normalised(origin.text) == _normalised(cell.text), (
                f"slot ({cell.row}, {cell.col}) reads {origin.text!r}, the browser {cell.text!r}"
            )

    def test_the_unfilled_wrapper_casts_no_shadow_and_draws_no_shape_for_one(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """The wrapper paints no background, so it casts no shadow, and no shape stands in for one.

        Neither app casts a shadow from an unfilled shape, and the export
        draws no shape for a shadow alone. So no shape on the slide is named
        "Shadow", none carries a shadow, and nothing but the corner shapes lies
        under the table.
        """
        document = _inline_document("rounded")
        shapes = slide_shapes(inline_export("rounded"))
        (table,) = browser_tables(document, "table")
        frame_position, _ = _frame_for(shapes, _grid_rect(table), "the rounded data table")

        named = [shape for shape in shapes if shape.name == "Shadow"]
        casting = [shape for shape in shapes if shape.shadow is not None]
        assert named == [] and casting == [], (
            f"a shape stands in for the wrapper's shadow:\n{_describe(shapes)}"
        )
        under = [shape for shape in shapes[:frame_position] if shape.geometry != "custGeom"]
        assert under == [], (
            f"something other than the corner shapes lies under the table:\n{_describe(under)}"
        )

    def test_cells_the_wrappers_corners_do_not_reach_keep_their_fills(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """The same table 12 px inside its rounded wrapper: no corner cuts a cell, so none changes.

        Every a:tc keeps its fill and no custom shape is drawn.
        """
        document = _inline_document("clear")
        shapes = slide_shapes(inline_export("clear"))
        (table,) = browser_tables(document, "table")
        _, frame = _frame_for(shapes, _grid_rect(table), "the padded data table")
        for row, fills in enumerate(ROUNDED_FILLS):
            for col, fill in enumerate(fills):
                assert frame.table.rows[row][col].fill == fill, (
                    f"slot ({row}, {col}): a:tc fill {frame.table.rows[row][col].fill}, not {fill}"
                )
        assert [shape for shape in shapes if shape.geometry == "custGeom"] == [], (
            f"a custom shape was drawn for a cell no corner cuts:\n{_describe(shapes)}"
        )

    def test_a_wrapper_between_pixels_still_cuts_only_its_corner_cells(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """The rounded wrapper 0.4 px off a whole px: still only its four corner cells are cut.

        The table's grid lies on whole px, and the wrapper's clip is drawn where
        Chrome paints it, on whole px too, so the grid's first line, snapped
        0.4 px above the wrapper's padding box, still lies on the clip. Every
        cell but the four corner ones keeps its own fill on its ``a:tc``, and
        each corner cell's custom shape stands on the cell's snapped grid
        rect, its edges on whole px.
        """
        document = _inline_document("offset")
        (table,) = browser_tables(document, "table")
        wrapper = browser_rect(document, "#offset-wrapper")
        assert abs(wrapper["y"] - round(wrapper["y"])) > 0.3, (
            f"fixture drift: the wrapper {wrapper} lies on a whole px"
        )
        shapes = slide_shapes(inline_export("offset"))
        frame_position, frame = _frame_for(shapes, _grid_rect(table), "the offset table")
        wrong = []
        for row, fills in enumerate(ROUNDED_FILLS):
            for col, fill in enumerate(fills):
                corner = ROUNDED_CORNERS.get((row, col))
                cell = frame.table.rows[row][col]
                expected = None if corner else fill
                if cell.fill != expected:
                    wrong.append(f"slot ({row}, {col}): a:tc fill {cell.fill}, expected {expected}")
                if not corner:
                    continue
                rect = table_cell_rect(frame, row, col)
                under = [
                    shape
                    for shape in shapes[:frame_position]
                    if shape.geometry == "custGeom"
                    and shape.fill == fill
                    and _same_rect(_box(shape), rect, WHOLE_PX_TOLERANCE)
                ]
                if len(under) != 1:
                    wrong.append(f"slot ({row}, {col}): {len(under)} {fill} shapes at {rect}")
        assert not wrong, "the offset wrapper cuts other cells than its corners:\n" + "\n".join(
            [*wrong, _describe(shapes)]
        )

    def test_the_tables_own_ground_is_cut_to_the_wrappers_corners(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """A table's own background in a rounded wrapper rounds with the wrapper, as its cells do.

        The table paints F3F3F3 under unfilled cells, which the wrapper clips to
        its 12 px rounded padding box. Under the frame, that ground is one
        ``a:custGeom`` path at the table's rect within 0.5 px, every vertex
        inside the wrapper's rounded box and vertices on each of its four corner
        arcs; the table stays one native frame with unfilled cells.
        """
        document = _inline_document("ground")
        (table,) = browser_tables(document, "table")
        wrapper = browser_rect(document, GROUND_WRAPPER)
        shapes = slide_shapes(inline_export("ground"))
        elements = slide_shape_elements(inline_export("ground"))
        frame_position, frame = _frame_for(shapes, _grid_rect(table), "the grounded table")
        assert all(cell.fill is None for _, _, cell in _origin_cells(frame)), (
            f"a cell of the grounded table is filled:\n{_describe(shapes)}"
        )
        grounds = [
            (position, shape) for position, shape in enumerate(shapes) if shape.fill == GROUND_FILL
        ]
        assert len(grounds) == 1, f"expected one {GROUND_FILL} ground:\n{_describe(shapes)}"
        position, ground = grounds[0]
        assert ground.geometry == "custGeom" and position < frame_position, (
            f"the table's ground is a {ground.geometry} at spTree {position}, not a path cut to "
            f"the wrapper's corners under the frame ({frame_position}):\n{_describe(shapes)}"
        )
        assert _same_rect(_box(ground), table.rect, INSIDE_TOLERANCE_PX), (
            f"the table's ground is at {_rect(ground)}, the table at {table.rect}"
        )
        points = _custom_geometry_points(elements[position], ground)
        outside, arcs = _against_rounded_box(points, wrapper, GROUND_RADIUS_PX)
        assert not outside and all(arcs.values()), (
            f"the table's ground has vertices outside the wrapper's rounded box {outside[:4]}; "
            f"on its arcs: {arcs}"
        )

    def test_a_wrapper_between_pixels_cuts_the_tables_own_ground_on_the_snapped_grid(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """The grounded table's wrapper 0.4 px below a whole px: its ground still meets the grid.

        The grid's first line snaps up to the whole px above the wrapper's
        padding box, and Chrome paints the wrapper's clip on whole px as well.
        So in the deck for PowerPoint the table's own background is cut by the
        clip as snapped: its path spans the frame's extent exactly, leaving no
        sliver of the grid unpainted along its top, and its corners are the
        snapped wrapper's arcs, the boxes that cut the corner cells too.
        """
        document = _inline_document("ground-offset")
        (table,) = browser_tables(document, "table")
        wrapper = browser_rect(document, GROUND_OFFSET_WRAPPER)
        assert abs(wrapper["y"] - round(wrapper["y"])) > 0.3, (
            f"fixture drift: the wrapper {wrapper} lies on a whole px"
        )
        shapes = slide_shapes(inline_export("ground-offset"))
        elements = slide_shape_elements(inline_export("ground-offset"))
        frame_position, frame = _frame_for(shapes, _grid_rect(table), "the offset grounded table")
        grounds = [
            (position, shape) for position, shape in enumerate(shapes) if shape.fill == GROUND_FILL
        ]
        assert len(grounds) == 1 and grounds[0][0] < frame_position, (
            f"expected the table's {GROUND_FILL} ground under its frame:\n{_describe(shapes)}"
        )
        position, ground = grounds[0]
        extent = table_extent(frame)
        off = {key: round(_box(ground)[key] - extent[key], 4) for key in ("x", "y", "w", "h")}
        assert all(abs(delta) <= WHOLE_PX_TOLERANCE for delta in off.values()), (
            f"the table's ground {_rect(ground)} is off its snapped grid {extent} by {off}"
        )
        snapped = {
            "x": round(wrapper["x"]),
            "y": round(wrapper["y"]),
            "w": round(wrapper["x"] + wrapper["w"]) - round(wrapper["x"]),
            "h": round(wrapper["y"] + wrapper["h"]) - round(wrapper["y"]),
        }
        points = _custom_geometry_points(elements[position], ground)
        outside, arcs = _against_rounded_box(points, snapped, GROUND_RADIUS_PX)
        assert not outside and all(arcs.values()), (
            f"the table's ground has vertices outside the snapped wrapper {snapped} "
            f"{outside[:4]}; on its arcs: {arcs}"
        )

    @pytest.mark.parametrize(
        "name",
        [
            "rounded",
            "translucent",
            "thin",
            "pair",
            "span-corner",
            "span-neighbour",
            "fixed",
            "fixed-span",
            "short-row",
            "rtl",
        ],
    )
    def test_in_the_deck_for_google_a_corner_piece_runs_under_its_opaque_neighbours(
        self, google_inline_export: Callable[[str], bytes], name: str
    ) -> None:
        """D13: Google draws a native cell on whole pixels, a shape anti-aliased.

        In Drive's thumbnail a native cell fills each pixel whose top left
        corner it holds, so its edge moves off a corner piece's anti-aliased
        one, and where it moves away a light seam shows (the data table's coral
        header, 73 levels; CALIBRATION.md D13). So in the deck for Google
        Slides, which keeps the browser's grid, each corner cell's custom shape
        runs under every opaque native cell beside it, which paints over the
        overlap:
        * a side whose neighbour is an opaque native cell runs 1 px past the
          cell's grid line, or half that row's height where the row is under
          2 px (``thin``: a 1 px rule row under the header), so it ends inside
          the neighbour; the shape's box is the cell's rect grown so, and it
          covers the strip there;
        * a side on the table's outer edge, or whose neighbour is translucent
          (``translucent``: the header's middle cell), stays on the line;
        * between two grown sides the corner square is covered where the cell
          across that corner is opaque too, and left out where it is not
          (``translucent``: the first body row's middle cell);
        * a corner cell's shape runs under a corner cell's shape drawn after
          it, which paints over it as a native cell does, and not under one
          drawn before it: two pieces meeting each anti-aliased their edge, and
          Google's thumbnail showed a light seam between them (``pair``: a
          two-column table, each left piece under the right one;
          ``span-corner``: the spanning header piece under the Cost one);
        * a side runs under only where every slot across it is opaque: a corner
          cell spanning two columns, the second slot below it translucent
          (``span-corner``), and one spanning two rows beside a header cell
          spanning two columns over a translucent slot (``span-neighbour``),
          runs under neither; the spanning neighbour is opaque by both its
          slots, so the other corner runs under it;
        * the neighbours are the table's own slots, whatever order the page's
          cells are read in: a short row's empty slot (``short-row``: the top
          right corner runs under no slot below it) and a right-to-left row
          (``rtl``: the top left corner runs under no slot below it, the
          translucent one at the table's left);
        * the outer corner is still cut to the wrapper's 8 px arc, and the
          corner cell's own a:tc is unfilled.
        """
        document = _inline_document(name)
        pptx = google_inline_export(name)
        shapes = slide_shapes(pptx)
        elements = slide_shape_elements(pptx)
        (table,) = browser_tables(document, "table")
        frame_position, frame = _frame_for(shapes, _grid_rect(table), f"the {name} data table")
        assert frame.table is not None
        heights, widths = frame.table.row_heights, frame.table.col_widths
        if name in TRANSLUCENT_SLOTS_OF:
            alphas = {
                slot: frame.table.rows[slot[0]][slot[1]].fill_alpha
                for slot in TRANSLUCENT_SLOTS_OF[name]
            }
            assert all(alpha is not None and alpha < 1 for alpha in alphas.values()), (
                f"fixture drift: the translucent slots' fill alphas are {alphas}"
            )
        for slot in EMPTY_SLOTS_OF.get(name, ()):
            assert frame.table.rows[slot[0]][slot[1]].fill is None, (
                f"fixture drift: the empty slot {slot} is filled "
                f"{frame.table.rows[slot[0]][slot[1]].fill}"
            )
        for (row, col), span in SPANS_OF.get(name, {}).items():
            cell = frame.table.rows[row][col]
            assert (cell.grid_span, cell.row_span) == span, (
                f"fixture drift: slot ({row}, {col}) spans {(cell.grid_span, cell.row_span)} "
                f"(columns, rows), not {span}"
            )
        if name == "thin":
            assert abs(heights[1] - 1) < 0.05 and _opaque_slot(frame, 1, 0), (
                f"fixture drift: the rule row is {heights[1]:.3f} px tall, filled "
                f"{frame.table.rows[1][0].fill}"
            )
        # Each corner piece's place in paint order: a piece drawn later covers its slots.
        positions = {
            slot: _corner_piece_position(
                shapes, frame_position, fill, table_cell_rect(frame, *slot)
            )
            for slot, fill in CORNER_PIECE_FILLS[name].items()
        }

        def covers(row: int, col: int, below: int) -> bool:
            """Whether slot ``(row, col)`` is painted opaquely over the piece at ``below``:
            by its native cell, or by a corner piece drawn after it."""
            if not (0 <= row < len(heights) and 0 <= col < len(widths)):
                return False
            owner = table_slot_owner(frame.table, row, col)
            if owner in positions:
                return positions[owner] > below
            return _opaque_slot(frame, row, col)

        wrong = []
        for (row, col), fill in CORNER_PIECE_FILLS[name].items():
            corner = ("top" if row == 0 else "bottom") + "-" + ("left" if col == 0 else "right")
            cell = frame.table.rows[row][col]
            if cell.fill is not None:
                wrong.append(f"slot ({row}, {col}): its a:tc is filled {cell.fill}")
            rect = table_cell_rect(frame, row, col)
            points = _corner_piece(shapes, elements, frame_position, fill, rect)
            left, top = rect["x"], rect["y"]
            right, bottom = left + rect["w"], top + rect["h"]

            last_row, last_col = row + cell.row_span, col + cell.grid_span

            def reach(opaque: bool, size: float) -> float:
                return min(CORNER_RUN_UNDER_PX, size / 2) if opaque else 0.0

            def across(rows: range, cols: range) -> bool:
                return all(covers(r, c, positions[(row, col)]) for r in rows for c in cols)

            reaches = {
                "top": reach(
                    across(range(row - 1, row), range(col, last_col)),
                    heights[row - 1] if row else 0,
                ),
                "bottom": reach(
                    across(range(last_row, last_row + 1), range(col, last_col)),
                    heights[last_row] if last_row < len(heights) else 0,
                ),
                "left": reach(
                    across(range(row, last_row), range(col - 1, col)),
                    widths[col - 1] if col else 0,
                ),
                "right": reach(
                    across(range(row, last_row), range(last_col, last_col + 1)),
                    widths[last_col] if last_col < len(widths) else 0,
                ),
            }
            # Inside the run-under, half way; or, where a side does not run under, 0.5 px past it.
            depth = {side: reaches[side] / 2 if reaches[side] else -0.5 for side in reaches}
            middle_x, middle_y = (left + right) / 2, (top + bottom) / 2
            probes = {
                "top strip": ((middle_x, top - abs(depth["top"])), bool(reaches["top"])),
                "bottom strip": (
                    (middle_x, bottom + abs(depth["bottom"])),
                    bool(reaches["bottom"]),
                ),
                "left strip": ((left - abs(depth["left"]), middle_y), bool(reaches["left"])),
                "right strip": ((right + abs(depth["right"]), middle_y), bool(reaches["right"])),
                "the cell's middle": ((middle_x, middle_y), True),
            }
            for vertical, horizontal in (
                ("top", "left"),
                ("top", "right"),
                ("bottom", "left"),
                ("bottom", "right"),
            ):
                if reaches[vertical] and reaches[horizontal]:
                    x = left - depth["left"] if horizontal == "left" else right + depth["right"]
                    y = top - depth["top"] if vertical == "top" else bottom + depth["bottom"]
                    diagonal = covers(
                        row - 1 if vertical == "top" else last_row,
                        col - 1 if horizontal == "left" else last_col,
                        positions[(row, col)],
                    )
                    probes[f"the {vertical}-{horizontal} corner square"] = ((x, y), diagonal)
            corner_x, corner_y = _corner_of(rect, corner)
            inward = (0.5 if "left" in corner else -0.5, 0.5 if "top" in corner else -0.5)
            probes["the square corner the arc cuts"] = (
                (corner_x + inward[0], corner_y + inward[1]),
                False,
            )
            for what, (point, expected) in probes.items():
                if _inside_polygon(point, points) != expected:
                    wrong.append(
                        f"slot ({row}, {col}) {corner}: {what} {point} is "
                        f"{'not ' if expected else ''}covered; its run-under per side: {reaches}"
                    )
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            box = {"left": min(xs), "top": min(ys), "right": max(xs), "bottom": max(ys)}
            expected_box = {
                "left": left - reaches["left"],
                "top": top - reaches["top"],
                "right": right + reaches["right"],
                "bottom": bottom + reaches["bottom"],
            }
            off = {side: round(box[side] - expected_box[side], 4) for side in box}
            if any(abs(delta) > 0.01 for delta in off.values()):
                wrong.append(
                    f"slot ({row}, {col}) {corner}: its box {box} is off {expected_box} by {off}"
                )
        assert not wrong, f"the {name} table's corner pieces in the Google deck:\n" + "\n".join(
            [*wrong, _describe(shapes)]
        )

    @pytest.mark.parametrize("name", sorted(GOOGLE_CORNER_BOXES))
    def test_in_the_deck_for_google_the_top_left_corner_piece_has_its_measured_box(
        self, google_inline_export: Callable[[str], bytes], name: str
    ) -> None:
        """D13 in literal px: the top left corner piece's box in the deck for Google Slides.

        On grids no font moves (``table-layout: fixed`` and 50 px rows; ``fixed``
        sets its widths on ``<col>``, ``fixed-span`` on its header cells), each
        box is worked out by hand from the lines, not from the engine's rule:
        ``fixed``'s piece runs 1 px past its right line (388) and its bottom
        line (210); ``fixed-span``'s, the cell spanning two rows, stays on its
        right line (313), a header cell spanning two columns above a
        translucent slot across that side, and runs 1 px past its bottom line
        (260). Each side within 0.01 px. (The auto-laid bodies' lines fall
        where their text's widths put them, between whole px, so their boxes
        are checked against the deck's own grid instead.)
        """
        document = _inline_document(name)
        (table,) = browser_tables(document, "table")
        columns, rows = _browser_grid_lines(table)
        right_line, bottom_line = GOOGLE_CORNER_GRID[name]
        origin = next(cell for cell in table.cells if cell.row == 0 and cell.col == 0)
        measured = (columns[origin.col + origin.col_span], rows[origin.row + origin.row_span])
        assert abs(measured[0] - right_line) < 0.01 and abs(measured[1] - bottom_line) < 0.01, (
            f"fixture drift: the {name} corner cell's right and bottom lines are {measured}, "
            f"the boxes were measured from {GOOGLE_CORNER_GRID[name]}"
        )
        pptx = google_inline_export(name)
        shapes = slide_shapes(pptx)
        frame_position, frame = _frame_for(shapes, _grid_rect(table), f"the {name} data table")
        points = _corner_piece(
            shapes,
            slide_shape_elements(pptx),
            frame_position,
            CORNER_PIECE_FILLS[name][(0, 0)],
            table_cell_rect(frame, 0, 0),
        )
        box = (
            min(point[0] for point in points),
            min(point[1] for point in points),
            max(point[0] for point in points),
            max(point[1] for point in points),
        )
        expected = GOOGLE_CORNER_BOXES[name]
        assert all(abs(a - b) <= 0.01 for a, b in zip(box, expected)), (
            f"the {name} table's top left corner piece spans {tuple(round(v, 4) for v in box)}; "
            f"expected {expected} (left, top, right, bottom)"
        )


# ---------------------------------------------------------------------------
# The grid on whole pixels
# ---------------------------------------------------------------------------


def _browser_grid_lines(table: BrowserTable) -> tuple[list[float], list[float]]:
    """The browser's column and row lines, left to right and top to bottom: its cells' box edges."""
    columns: list[float | None] = [None] * (table.columns + 1)
    rows: list[float | None] = [None] * (len(table.rows) + 1)
    for cell in table.cells:
        columns[cell.col] = cell.x
        columns[cell.col + cell.col_span] = cell.x + cell.w
        rows[cell.row] = cell.y
        rows[cell.row + cell.row_span] = cell.y + cell.h
    assert None not in columns and None not in rows, (
        f"fixture drift: a grid line no cell edge lies on: {columns} {rows}"
    )
    return columns, rows


def _nearest_px(value: float) -> float:
    """The whole px nearest ``value``, a half rounding up (as Chrome snaps a box edge)."""
    return float(math.floor(value + 0.5))


def _line_widths(frame: Shape, horizontal: bool) -> list[float]:
    """The width of the border written along each grid line, in CSS px: the width most of its
    slots carry (none counting as 0), the wider on a tie. Each slot's border is read from the
    cell after the line (below it, or right of it), or before it on the table's last line."""
    assert frame.table is not None
    table = frame.table
    rows, columns = len(table.row_heights), len(table.col_widths)
    lines, slots = (rows, columns) if horizontal else (columns, rows)
    widths = []
    for line in range(lines + 1):
        tally: Counter[float] = Counter()
        for slot in range(slots):
            after = line < lines
            index = line if after else line - 1
            row, col = (index, slot) if horizontal else (slot, index)
            side = ("top" if after else "bottom") if horizontal else ("left" if after else "right")
            owner_row, owner_col = table_slot_owner(table, row, col)
            border = table.rows[owner_row][owner_col].borders[side]
            tally[0.0 if border is None else round((border.width_pt or 0.0) / PT_PER_PX, 4)] += 1
        widths.append(max(tally.items(), key=lambda item: (item[1], item[0]))[0])
    return widths


def _off_the_snapped_grid(frame: Shape, table: BrowserTable, what: str) -> list[str]:
    """Every emitted grid line whose border does not start on the whole px nearest the
    browser's: a line with no border on that px, one with a border of width w w/2 past it."""
    columns, rows = _browser_grid_lines(table)
    problems = []
    for axis, emitted, measured, widths in (
        ("column", table_column_edges(frame), columns, _line_widths(frame, False)),
        ("row", table_row_edges(frame), rows, _line_widths(frame, True)),
    ):
        assert len(emitted) == len(measured), (
            f"{what}: {len(emitted)} {axis} lines emitted, the browser has {len(measured)}"
        )
        for index, (line, browser, width) in enumerate(zip(emitted, measured, widths)):
            expected = _nearest_px(browser - width / 2) + width / 2
            if abs(line - expected) > WHOLE_PX_TOLERANCE:
                problems.append(
                    f"{what}: {axis} line {index} (a {width:g} px border) at {line:.4f} px; the "
                    f"browser's is at {browser:.4f}, so its border starts on the whole px "
                    f"{_nearest_px(browser - width / 2):g} and the line lies at {expected:g}"
                )
    return problems


@pytest.mark.slow
@requires_huashu_sidecar
class TestWholePixelGrid:
    def test_grid_lines_lie_where_chrome_paints_them(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """A table laid out between pixels: each grid line where Chrome paints it, on whole px.

        Cell fills that meet between two pixels anti-alias into a light seam in
        PowerPoint's PDF, under Quartz and MuPDF alike, where Chrome snaps each box
        edge to a whole pixel and paints none. So in the deck for PowerPoint
        every grid line, the frame's first column and row lines included, lies
        where Chrome puts it: a line with no border on the whole px nearest the
        browser's line, and one whose border is w px wide w/2 past the whole px
        nearest that border's edge (a 1 px rule's centre half a px past it), so
        the rule covers whole pixels. Each line is snapped where it lies rather
        than each width rounded: the frame stands at the snapped first lines,
        every ``gridCol`` and ``a:tr`` spans two snapped lines, and the table's
        width and height are its snapped outer lines apart, however many columns
        and rows it has.
        """
        document = _inline_document("snap")
        (table,) = browser_tables(document, SNAP_TABLE)
        columns, rows = _browser_grid_lines(table)
        between = [line for line in columns + rows if abs(line - round(line)) > 0.05]
        assert len(between) >= 4, (
            f"fixture drift: the browser lays the table's lines {columns} {rows} on whole px"
        )
        shapes = slide_shapes(inline_export("snap"))
        _, frame = _frame_for(shapes, _grid_rect(table), "the snapped table")
        problems = _off_the_snapped_grid(frame, table, "the snapped table")
        assert 1.0 in _line_widths(frame, True), (
            "fixture drift: no row line of the snapped table carries its 1 px rule"
        )
        extent = table_extent(frame)
        for size, emitted, lines in (
            ("width", extent["w"], columns),
            ("height", extent["h"], rows),
        ):
            snapped = _nearest_px(lines[-1]) - _nearest_px(lines[0])
            if abs(emitted - snapped) > WHOLE_PX_TOLERANCE:
                problems.append(
                    f"the table's {size} is {emitted:.4f} px; its snapped outer lines are "
                    f"{snapped:g} px apart"
                )
        assert not problems, "the grid does not lie on whole px:\n  " + "\n  ".join(problems)

    def test_a_line_ruled_on_half_its_slots_lies_as_its_rule_does(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """A line one slot of which is ruled 1 px and one not: it lies as the rule does.

        A line takes the width most of its slots draw, the wider on a tie, so
        this one's 1 px rule covers a whole pixel: the line lies half a px past
        a whole one.
        """
        document = _inline_document("snap")
        (table,) = browser_tables(document, SNAP_TIE_TABLE)
        shapes = slide_shapes(inline_export("snap"))
        _, frame = _frame_for(shapes, _grid_rect(table), "the tie table")
        assert _line_widths(frame, True)[SNAP_TIE_LINE] == 1.0, (
            f"the tie line carries {_line_widths(frame, True)}, not its 1 px rule"
        )
        line = table_row_edges(frame)[SNAP_TIE_LINE]
        assert abs(line - math.floor(line) - 0.5) <= WHOLE_PX_TOLERANCE, (
            f"the tie line lies at {line:.4f} px, not half a px past a whole one"
        )
        problems = _off_the_snapped_grid(frame, table, "the tie table")
        assert not problems, "the tie table's grid:\n  " + "\n  ".join(problems)

    def test_cell_text_starts_where_the_browser_starts_it(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """The snap moves the grid lines, not the text: each cell's margins take up the difference.

        On every side of every cell, the emitted grid line and the margin on that
        side meet where the browser starts the cell's content: its box edge, in
        by half the collapsed border written there and by its padding, within
        0.05 px.
        """
        document = _inline_document("snap")
        (table,) = browser_tables(document, SNAP_TABLE)
        shapes = slide_shapes(inline_export("snap"))
        _, frame = _frame_for(shapes, _grid_rect(table), "the snapped table")
        columns = table_column_edges(frame)
        rows = table_row_edges(frame)
        problems = []
        for cell in table.cells:
            origin = frame.table.rows[cell.row][cell.col]
            half = {
                side: 0.0
                if origin.borders[side] is None
                else (origin.borders[side].width_pt or 0.0) / PT_PER_PX / 2
                for side in SIDES
            }
            edges = {
                "left": (columns[cell.col], cell.x, 1),
                "right": (columns[cell.col + cell.col_span], cell.x + cell.w, -1),
                "top": (rows[cell.row], cell.y, 1),
                "bottom": (rows[cell.row + cell.row_span], cell.y + cell.h, -1),
            }
            for side, (line, box_edge, inward) in edges.items():
                margin = origin.margins_px[side]
                if margin is None:
                    problems.append(f"cell ({cell.row}, {cell.col}): no {side} margin")
                    continue
                browser = box_edge + inward * (half[side] + cell.padding[side])
                emitted = line + inward * margin
                if abs(emitted - browser) > CONTENT_TOLERANCE_PX:
                    problems.append(
                        f"cell ({cell.row}, {cell.col}) {_normalised(cell.text)!r}: its {side} "
                        f"content edge is at {emitted:.3f} px (line {line:.3f}, margin "
                        f"{margin:.3f}); the browser's at {browser:.3f}"
                    )
        assert not problems, "the cells' text moved with the grid:\n  " + "\n  ".join(problems)

    def test_the_tables_own_ground_lies_on_its_snapped_grid(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """The table's own background, under its unfilled body cells, stands on its whole-px grid.

        Chrome paints the table's box and its cells' on whole px alike, so the
        ground shows nowhere past the grid: its shape under the frame is the
        frame's own extent, exactly.
        """
        document = _inline_document("snap")
        (table,) = browser_tables(document, SNAP_TABLE)
        shapes = slide_shapes(inline_export("snap"))
        frame_position, frame = _frame_for(shapes, _grid_rect(table), "the snapped table")
        grounds = [
            (position, shape) for position, shape in enumerate(shapes) if shape.fill == SNAP_GROUND
        ]
        assert len(grounds) == 1 and grounds[0][0] < frame_position, (
            f"expected the table's {SNAP_GROUND} ground under its frame:\n{_describe(shapes)}"
        )
        ground = grounds[0][1]
        extent = table_extent(frame)
        off = {key: round(_box(ground)[key] - extent[key], 4) for key in ("x", "y", "w", "h")}
        assert all(abs(delta) <= WHOLE_PX_TOLERANCE for delta in off.values()), (
            f"the table's ground {_rect(ground)} is off its snapped grid {extent} by {off}"
        )

    def test_the_deck_for_google_slides_keeps_the_browsers_grid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The deck for Google Slides lays the snapped table on the browser's own lines.

        Google Slides draws no seam between cell fills, and none of its views
        shows a CSS px as a whole pixel, so its deck keeps every grid line where
        the browser put it, within 0.01 px.
        """
        document = _inline_document("snap")
        (table,) = browser_tables(document, SNAP_TABLE)
        columns, rows = _browser_grid_lines(table)
        pptx, failures = export_slides(
            [SNAP_BODY], css=TABLES_CSS, monkeypatch=monkeypatch, target="gslides"
        )
        assert failures == [], failures
        _, frame = _frame_for(slide_shapes(pptx), _grid_rect(table), "the Google table")
        off = [
            f"{axis} line {index} at {line:.4f}; the browser's at {browser:.4f}"
            for axis, emitted, measured in (
                ("column", table_column_edges(frame), columns),
                ("row", table_row_edges(frame), rows),
            )
            for index, (line, browser) in enumerate(zip(emitted, measured))
            if abs(line - browser) > 0.01
        ]
        assert not off, "the Google deck's grid is not the browser's:\n  " + "\n  ".join(off)

    @pytest.mark.parametrize("prefix", ["05", "15"])
    def test_corpus_tables_lie_on_whole_px(
        self, corpus_export: Callable[[str], list[Shape]], prefix: str
    ) -> None:
        """Fixtures 05 (two balance sheets) and 15 (the zebra table): grids where Chrome paints.

        Their header and total rows are the filled cells that showed seams in
        PowerPoint; every line of each table lies as the snapped table's do, its
        1 px rules on whole pixels.
        """
        document = corpus_document(prefix)
        tables = browser_tables(document, BALANCE_TABLES)
        assert tables, f"fixture drift: corpus slide {prefix} has no {BALANCE_TABLES}"
        shapes = corpus_export(prefix)
        problems = []
        for index, table in enumerate(tables):
            what = f"corpus {prefix} table {index}"
            _, frame = _frame_for(shapes, _grid_rect(table), what)
            problems.extend(_off_the_snapped_grid(frame, table, what))
        assert not problems, "the corpus tables' grids do not lie on whole px:\n  " + (
            "\n  ".join(problems)
        )


# ---------------------------------------------------------------------------
# Dotted cell borders
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def dotted_export() -> Iterator[Callable[[str], list[Shape]]]:
    """The dotted table exported for ``target`` (``pptx`` or ``gslides``), once each."""
    exported: dict[str, list[Shape]] = {}
    with pytest.MonkeyPatch.context() as monkeypatch:

        def export(target: str) -> list[Shape]:
            if target not in exported:
                pptx, failures = export_slides(
                    [DOTTED_BODY], css=TABLES_CSS, monkeypatch=monkeypatch, target=target
                )
                assert failures == [] and pptx, f"the export rejected the dotted table: {failures}"
                exported[target] = slide_shapes(pptx)
            return exported[target]

        yield export


# PowerPoint and Google Slides draw single spacing at 1.2 x the font size whatever the face
# (scripts/export_fidelity/CALIBRATION.md, the rules), and lay a native table's row out to hold
# each of its cells' lines at that spacing (times the paragraph's lnSpc percentage) plus their
# space before, inside the cell's margins: a row whose cells need more is grown.
APP_SINGLE_SPACING_EM = 1.2
PX_PER_PT = 1 / PT_PER_PX
# A row may come out this much taller than written: the EMU rounding of its margins and sizes.
ROW_GROWTH_TOLERANCE_PX = 0.25


def _app_row_heights(frame: Shape) -> list[float]:
    """Each row's height as the apps lay it out: its written height, or the most any cell of
    that row alone (no row span) needs at their single spacing, whichever is more."""
    assert frame.table is not None
    heights = []
    for row, cells in enumerate(frame.table.rows):
        need = frame.table.row_heights[row]
        for cell in cells:
            if cell.h_merge or cell.v_merge or cell.row_span > 1:
                continue
            text = 0.0
            for para in cell.paras:
                sizes = [run.size_pt * PX_PER_PT for run in para.runs if run.size_pt]
                if not sizes:
                    continue
                lines = 1 + sum(1 for run in para.runs if run.soft_break_before)
                pct = (para.line_spacing_pct or 100.0) / 100
                text += lines * APP_SINGLE_SPACING_EM * max(sizes) * pct
                text += (para.space_before_pt or 0.0) * PX_PER_PT
            margins = (cell.margins_px["top"] or 0.0) + (cell.margins_px["bottom"] or 0.0)
            need = max(need, margins + text)
        heights.append(need)
    return heights


@pytest.mark.slow
@requires_huashu_sidecar
class TestRowsHoldTheirCellsAtTheAppsSpacing:
    @pytest.mark.parametrize("target", ["pptx", "gslides"])
    def test_a_row_of_cells_set_under_single_spacing_is_not_grown(
        self,
        target: str,
        inline_export: Callable[[str], bytes],
        google_inline_export: Callable[[str], bytes],
    ) -> None:
        """Arial-family rows keep the browser's height in both apps, one-line cells and two.

        Chrome sets Arial and Helvetica at line-height: normal at 1.15 em (the tight table at
        1.0), under the apps' single spacing of 1.2 em. A cell paragraph with no lnSpc is set at
        1.2 em, so with its margins it needed more than the row the browser laid out, and both
        apps grew every such row about a px (the finance deck's balance sheet, 8 px over 8
        rows). So every cell's paragraph, one line or more, is spaced as a block of several
        lines is (emit_text.cjs, a percentage of single spacing): each row of both tables,
        laid out as the apps lay rows out, is its written height, which is the browser's.
        """
        document = _inline_document("app-rows")
        pptx = (google_inline_export if target == "gslides" else inline_export)("app-rows")
        shapes = slide_shapes(pptx)
        problems = []
        for selector in APP_ROWS_TIGHT:
            (table,) = browser_tables(document, selector)
            _, frame = _frame_for(shapes, _grid_rect(table), selector)
            _assert_grid_matches(frame, table, selector)
            written = frame.table.row_heights
            for row, (height, laid_out) in enumerate(zip(written, _app_row_heights(frame))):
                if laid_out - height > ROW_GROWTH_TOLERANCE_PX:
                    problems.append(
                        f"{selector} row {row}: written {height:.2f} px, the apps lay it out "
                        f"{laid_out:.2f} px (+{laid_out - height:.2f})"
                    )
        assert not problems, f"rows the apps grow ({target}):\n  " + "\n  ".join(problems)

    def test_a_cell_set_over_single_spacing_keeps_its_line_natural(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """DM Sans at line-height: normal is 1.30 em, over single spacing: its one-line cells
        carry no lnSpc, and its rows still hold them (the control for the spacing above)."""
        document = _inline_document("app-rows")
        shapes = slide_shapes(inline_export("app-rows"))
        (table,) = browser_tables(document, APP_ROWS_LOOSE)
        _, frame = _frame_for(shapes, _grid_rect(table), APP_ROWS_LOOSE)
        # A cell of one line: one paragraph and no soft break (a looser two-line cell is a
        # paragraph a line, single spaced, emit_text.cjs).
        spaced = [
            f"row {row} {_normalised(cell.text)!r}: lnSpc {cell.paras[0].line_spacing_pct}"
            for row, cells in enumerate(frame.table.rows)
            for cell in cells
            if len(cell.paras) == 1
            and cell.paras[0].line_spacing_pct is not None
            and not any(run.soft_break_before for run in cell.paras[0].runs)
        ]
        assert not spaced, "one-line DM Sans cells carry line spacing:\n  " + "\n  ".join(spaced)
        grown = [
            (row, height, laid_out)
            for row, (height, laid_out) in enumerate(
                zip(frame.table.row_heights, _app_row_heights(frame))
            )
            if laid_out - height > ROW_GROWTH_TOLERANCE_PX
        ]
        assert not grown, f"DM Sans rows the apps grow: {grown}"


def _cell_round_pieces(
    shapes: list[Shape], elements: list, frame_position: int, frame: Shape
) -> tuple[list[str], dict]:
    """What is wrong with the corner cells of the cell-rounds table, and each corner piece (its
    shape, its points and its cell's rect, by slot): every corner cell unfilled in the a:tbl,
    one custom shape of its fill under the frame, every vertex within the cell's rect grown by
    at most 1.5 px, a vertex on the cell's 8 px arc and none at its square corner, and no
    outline; every other cell its own fill."""
    wrong, pieces = [], {}
    for row, fills in enumerate(CELL_ROUND_FILLS):
        for col, fill in enumerate(fills):
            cell = frame.table.rows[row][col]
            corner = CELL_ROUND_CORNERS.get((row, col))
            if cell.fill != (None if corner else fill):
                wrong.append(f"slot ({row}, {col}): a:tc fill {cell.fill}")
            if not corner:
                continue
            rect = table_cell_rect(frame, row, col)
            grown = {
                "x": rect["x"] - 1.5,
                "y": rect["y"] - 1.5,
                "w": rect["w"] + 3,
                "h": rect["h"] + 3,
            }
            under = [
                position
                for position, shape in enumerate(shapes[:frame_position])
                if shape.kind == "shape"
                and shape.geometry == "custGeom"
                and shape.fill == fill
                and _centre_inside(shape, rect, 0.5)
            ]
            if len(under) != 1:
                wrong.append(f"slot ({row}, {col}): {len(under)} {fill} pieces under the table")
                continue
            shape = shapes[under[0]]
            points = _custom_geometry_points(elements[under[0]], shape)
            outside = [point for point in points if not _inside_rounded(point, grown, 0, 0.01)]
            corner_x, corner_y = _corner_of(rect, corner)
            at_corner = [
                point
                for point in points
                if abs(point[0] - corner_x) <= ARC_TOLERANCE_PX
                and abs(point[1] - corner_y) <= ARC_TOLERANCE_PX
            ]
            centre_x = corner_x + (
                CELL_ROUND_RADIUS_PX if "left" in corner else -CELL_ROUND_RADIUS_PX
            )
            centre_y = corner_y + CELL_ROUND_RADIUS_PX
            on_arc = [
                point
                for point in points
                if abs(math.hypot(point[0] - centre_x, point[1] - centre_y) - CELL_ROUND_RADIUS_PX)
                <= ARC_TOLERANCE_PX
                and abs(point[0] - centre_x) > ARC_TOLERANCE_PX
                and abs(point[1] - centre_y) > ARC_TOLERANCE_PX
            ]
            if outside or at_corner or not on_arc or shape.line is not None:
                wrong.append(
                    f"slot ({row}, {col}) {corner}: points past its rect {outside[:3]}, at the "
                    f"square corner {at_corner}, on the arc {len(on_arc)}, outline {shape.line}"
                )
            pieces[(row, col)] = (shape, points, rect)
    return wrong, pieces


@pytest.mark.slow
@requires_huashu_sidecar
class TestCollapsedCellRadii:
    def test_a_collapsed_cells_own_radius_cuts_its_fill_to_the_arc(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """A collapsed header cell's own ``border-top-left-radius`` rounds its fill, as in Chrome.

        Under ``border-collapse: collapse`` Chrome rounds a cell's background by its own radius
        (its collapsed borders stay straight), so the long deck's coral headers have round top
        corners; an a:tc is square. So, as a rounded wrapper's corner cells are (D5), each such
        cell is unfilled in the native table and its fill is a custom shape under it: the
        cell's rect, its corner replaced by the 8 px arc. The table stays one native frame, on
        the browser's grid, every cell's text its own.
        """
        document = _inline_document("cell-rounds")
        pptx = inline_export("cell-rounds")
        shapes = slide_shapes(pptx)
        (table,) = browser_tables(document, "#cell-rounds")
        frame_position, frame = _frame_for(shapes, _grid_rect(table), "#cell-rounds")
        _assert_grid_matches(frame, table, "#cell-rounds")
        wrong, pieces = _cell_round_pieces(
            shapes, slide_shape_elements(pptx), frame_position, frame
        )
        for (row, col), (shape, _, rect) in pieces.items():
            if not _same_rect(_box(shape), rect, 0.5):
                wrong.append(
                    f"slot ({row}, {col}): the piece is at {_box(shape)}, its cell at {rect}"
                )
        assert not wrong, "the rounded header cells:\n  " + "\n  ".join([*wrong, _describe(shapes)])

    def test_in_the_deck_for_google_a_cells_own_round_runs_under_its_neighbours(
        self, google_inline_export: Callable[[str], bytes]
    ) -> None:
        """In the Google deck the piece runs 1 px under each opaque native neighbour (D13).

        Its side beside the next header cell and its side over the first body row run 1 px
        past the cell's grid lines; its sides on the table's outer edge stay on them, and its
        arc is the cell's own, about its own corner.
        """
        document = _inline_document("cell-rounds")
        pptx = google_inline_export("cell-rounds")
        shapes = slide_shapes(pptx)
        (table,) = browser_tables(document, "#cell-rounds")
        frame_position, frame = _frame_for(shapes, _grid_rect(table), "#cell-rounds")
        wrong, pieces = _cell_round_pieces(
            shapes, slide_shape_elements(pptx), frame_position, frame
        )
        for (row, col), (shape, points, rect) in pieces.items():
            inner = (
                rect["x"] + rect["w"] + CORNER_RUN_UNDER_PX
                if col == 0
                else rect["x"] - CORNER_RUN_UNDER_PX
            )
            outer = rect["x"] if col == 0 else rect["x"] + rect["w"]
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            inner_side = max(xs) if col == 0 else min(xs)
            if abs(inner_side - inner) > 0.01:
                wrong.append(f"slot ({row}, {col}): its inner side at {inner_side}, not {inner}")
            if (
                abs((min(xs) if col == 0 else max(xs)) - outer) > 0.01
                or abs(min(ys) - rect["y"]) > 0.01
            ):
                wrong.append(f"slot ({row}, {col}): its outer sides moved off the grid")
            if abs(max(ys) - (rect["y"] + rect["h"] + CORNER_RUN_UNDER_PX)) > 0.01:
                wrong.append(
                    f"slot ({row}, {col}): its bottom at {max(ys)}, not 1 px under the row below"
                )
        assert not wrong, "the Google deck's rounded header cells:\n  " + "\n  ".join(
            [*wrong, _describe(shapes)]
        )


@pytest.mark.slow
@requires_huashu_sidecar
class TestInsetShadowedCells:
    @pytest.mark.parametrize("target", ["pptx", "gslides"])
    def test_a_cells_inset_rules_are_bands_over_a_native_table(
        self,
        target: str,
        inline_export: Callable[[str], bytes],
        google_inline_export: Callable[[str], bytes],
    ) -> None:
        """A column its cells' inset box-shadow highlights stays one native table, its rules drawn.

        ``inset 2px 0 0`` and ``inset -2px 0 0`` paint a 2 px band inside each cell's padding
        box, at its left and its right. A box-shadow used to cost the whole table its
        nativeness (the edited deck's pricing table: 38 text boxes and 12 shapes), and the
        bands were not drawn. Now the table is one native frame on the browser's grid, its
        cells' text its own, and over it each highlighted cell's two bands are rects of the
        rule's colour, 2 px wide, at its grid rect's sides and its whole height (but the half
        collapsed rule its padding box leaves out).
        """
        document = _inline_document("highlight")
        pptx = (google_inline_export if target == "gslides" else inline_export)("highlight")
        shapes = slide_shapes(pptx)
        (table,) = browser_tables(document, "#highlight")
        frame_position, frame = _frame_for(shapes, _grid_rect(table), "#highlight")
        _assert_grid_matches(frame, table, "#highlight")
        texts = [shape for shape in shapes if shape.kind == "text" and shape.text.strip()]
        assert not texts, f"cell text left the table: {[shape.text for shape in texts]}"
        bands = [
            shape
            for position, shape in enumerate(shapes)
            if position > frame_position
            and shape.kind == "shape"
            and shape.fill == INSET_HIGHLIGHT_COLOUR
        ]
        wrong = []
        for row in INSET_HIGHLIGHT_ROWS:
            rect = table_cell_rect(frame, row, INSET_HIGHLIGHT_COLUMN)
            for side, x in (
                ("left", rect["x"]),
                ("right", rect["x"] + rect["w"] - INSET_HIGHLIGHT_BAND_PX),
            ):
                found = [
                    band
                    for band in bands
                    if abs(band.x - x) <= 0.1
                    and abs(band.w - INSET_HIGHLIGHT_BAND_PX) <= 0.1
                    and rect["y"] - 0.1 <= band.y <= rect["y"] + 1
                    and abs(band.h - rect["h"]) <= 1.1
                ]
                if len(found) != 1:
                    wrong.append(
                        f"row {row}, its {side} band: {len(found)} at x {x:.2f} over {rect}"
                    )
        assert len(bands) == 2 * len(INSET_HIGHLIGHT_ROWS) and not wrong, (
            f"the highlight's bands ({target}): {len(bands)} drawn\n  " + "\n  ".join(wrong)
        )


@pytest.mark.slow
@requires_huashu_sidecar
class TestDoubleCellBorders:
    def test_the_powerpoint_deck_writes_a_double_side_as_a_double_compound_line(
        self, inline_export: Callable[[str], bytes]
    ) -> None:
        """A ``3px double`` (and ``6px``) edge is ``cmpd="dbl"`` on both its cells, its width whole.

        Chrome paints a double border as two lines with a gap, each a third of its width;
        DrawingML's double compound line is the same (PowerPoint draws it so: CALIBRATION.md T7).
        So the cell above the edge writes it on its ``lnB`` and the cell below on its ``lnT``,
        double, at the border's whole width. The 2 px double rule, which Chrome paints solid,
        stays a single line.
        """
        document = _inline_document("double-rows")
        shapes = slide_shapes(inline_export("double-rows"))
        (table,) = browser_tables(document, "#double-rows")
        _, frame = _frame_for(shapes, _grid_rect(table), "#double-rows")
        wrong = []
        for row, colour, width in DOUBLE_EDGES:
            pairs = zip(frame.table.rows[row], frame.table.rows[row + 1])
            for col, (above, below) in enumerate(pairs):
                sides = (
                    ("lnB above", above.borders["bottom"]),
                    ("lnT below", below.borders["top"]),
                )
                for name, border in sides:
                    if (
                        border is None
                        or border.compound != "dbl"
                        or border.color != colour
                        or abs((border.width_pt or 0) - width * PT_PER_PX) > WIDTH_TOLERANCE_PT
                    ):
                        wrong.append(f"edge under row {row}, column {col}, {name}: {border}")
        thin = frame.table.rows[THIN_DOUBLE_ROW][0].borders["bottom"]
        if thin is None or thin.compound == "dbl":
            wrong.append(f"the 2px double rule is not one solid line: {thin}")
        assert not wrong, "double table borders, PowerPoint deck:\n  " + "\n  ".join(wrong)

    def test_the_google_deck_draws_a_double_edge_as_its_two_lines_over_the_table(
        self, google_inline_export: Callable[[str], bytes]
    ) -> None:
        """Drive makes a double table border one solid line, so the Google deck draws its lines.

        Each double edge is no line on either cell (its ``lnB`` and ``lnT`` unfilled), and over
        the table, after it, one unfilled custom shape per cell along the edge strokes the edge's
        outer and inner thirds: two subpaths a third of the border's width apart from the edge's
        centre line, each a third of its width wide, in its colour. The 2 px double rule stays
        the cells' own solid line, with no shape over it.
        """
        document = _inline_document("double-rows")
        pptx = google_inline_export("double-rows")
        shapes = slide_shapes(pptx)
        elements = slide_shape_elements(pptx)
        (table,) = browser_tables(document, "#double-rows")
        frame_position, frame = _frame_for(shapes, _grid_rect(table), "#double-rows")
        rows, columns = table_row_edges(frame), table_column_edges(frame)
        wrong = []
        for row, colour, width in DOUBLE_EDGES:
            line = rows[row + 1]
            pairs = zip(frame.table.rows[row], frame.table.rows[row + 1])
            for col, (above, below) in enumerate(pairs):
                if above.borders["bottom"] is not None or below.borders["top"] is not None:
                    wrong.append(f"edge under row {row}, column {col}: a line on the cells")
                strokes = [
                    (position, shape)
                    for position, shape in enumerate(shapes)
                    if position > frame_position
                    and shape.geometry == "custGeom"
                    and shape.line == colour
                    and shape.fill is None
                    and abs(shape.x - columns[col]) <= 0.5
                    and abs(shape.w - (columns[col + 1] - columns[col])) <= 0.5
                    and abs(shape.y - (line - width / 3)) <= 0.1
                    and abs(shape.h - 2 * width / 3) <= 0.1
                ]
                if len(strokes) != 1:
                    wrong.append(
                        f"edge under row {row}, column {col}: {len(strokes)} strokes over it"
                    )
                    continue
                position, stroke = strokes[0]
                moves = elements[position].findall(".//a:custGeom//a:moveTo", NAMESPACES)
                third = width / 3 * PT_PER_PX
                if len(moves) != 2 or abs((stroke.line_w_pt or 0) - third) > WIDTH_TOLERANCE_PT:
                    wrong.append(
                        f"edge under row {row}, column {col}: {len(moves)} subpaths, "
                        f"{stroke.line_w_pt} pt (a third of {width} px is {third:.3f} pt)"
                    )
        thin = frame.table.rows[THIN_DOUBLE_ROW][0].borders["bottom"]
        if thin is None or thin.compound == "dbl":
            wrong.append(f"the 2px double rule is not the cells' own solid line: {thin}")
        assert not wrong, "double table borders, Google deck:\n  " + "\n  ".join(wrong)


@pytest.mark.slow
@requires_huashu_sidecar
class TestDottedCellBorders:
    @pytest.mark.parametrize("target", ["pptx", "gslides"])
    def test_a_dotted_cell_border_is_written_dotted(
        self, dotted_export: Callable[[str], list[Shape]], target: str
    ) -> None:
        """Each dotted edge is ``sysDot`` on both its cells, in the deck for either app.

        PowerPoint draws ``sysDot`` one width on and one off, as CSS paints a
        dotted border; Drive converts it to its ``DOT`` (one on and three off),
        the nearest dash a Google table border has. Row 0's 2 px dotted rule and
        the 1 px dotted column rule are ``sysDot`` on both sides of every
        edge; row 1's dashed rule stays ``sysDash``. In the table below it, the
        dotted rule under a cell spanning both columns is ``sysDot`` on that
        cell and on both cells beneath it. The table ahead of them, which has
        no dotted rule, keeps its solid rules.
        """
        document = slide_document(DOTTED_BODY, css=TABLES_CSS, slide_id="snapshot-1")
        shapes = dotted_export(target)
        plain = [((row, 0, "right"), "sysDot") for row in range(3)]
        plain += [((row, 1, "left"), "sysDot") for row in range(3)]
        for col in range(2):
            plain += [((0, col, "bottom"), "sysDot"), ((1, col, "top"), "sysDot")]
            plain += [((1, col, "bottom"), "sysDash"), ((2, col, "top"), "sysDash")]
        spanned = [((0, 0, "bottom"), "sysDot"), ((1, 0, "top"), "sysDot")]
        spanned += [((1, 1, "top"), "sysDot"), ((1, 0, "right"), "sysDot")]
        spanned += [((1, 1, "left"), "sysDot")]
        wrong = []
        for selector, expected in (("#dotted", plain), ("#dotted-span", spanned)):
            (table,) = browser_tables(document, selector)
            _, frame = _frame_for(shapes, _grid_rect(table), selector)
            rows = frame.table.rows
            wrong += [
                f"{selector} slot ({row}, {col}) {side}: "
                f"{getattr(rows[row][col].borders[side], 'dash', None)}, expected {dash}"
                for (row, col, side), dash in expected
                if rows[row][col].borders[side] is None or rows[row][col].borders[side].dash != dash
            ]
        (undotted,) = browser_tables(document, "#undotted")
        _, frame = _frame_for(shapes, _grid_rect(undotted), "#undotted")
        wrong += [
            f"#undotted slot ({row}, {col}) {side}: {border.dash}"
            for row, cells in enumerate(frame.table.rows)
            for col, cell in enumerate(cells)
            for side, border in cell.borders.items()
            if border is not None and border.dash not in (None, "solid")
        ]
        assert not wrong, f"the {target} deck's dotted tables: " + "; ".join(wrong)


# The rewrite that writes the dotted sides sysDot (emit_rewrite.cjs rewriteDeck), and the
# deck script that runs it once pptxgenjs has written the deck.
EMIT_TABLE_MODULE = pptx_from_html_huashu.SIDECAR_DIR / "emit_table.cjs"
# A module node preloads (--require) before emit_deck.mjs: it makes the zip library the
# rewrite reads the deck with refuse to read one. pptxgenjs writes a deck with it but never
# reads one (JSZip.loadAsync), so the rewrite alone fails.
FAILING_REWRITE_PRELOAD = """
const path = require('path');
const sidecar = process.cwd();
const pptxgenjs = require.resolve('pptxgenjs', { paths: [sidecar] });
const JSZip = require(require.resolve('jszip', { paths: [path.dirname(pptxgenjs)] }));
JSZip.loadAsync = () => Promise.reject(new Error('the test refuses to read the deck'));
"""
REWRITE_FAILURE_REASON = "the test refuses to read the deck"


def run_sidecar_with_preload(
    preload: Path, out_path: Path, payload: dict, *, timeout: float
) -> subprocess.CompletedProcess[str]:
    """``emit_deck.mjs`` on ``payload``, run as the wrapper runs it, ``preload`` required first.

    Through ``run_node``, in the sidecar's directory with its environment: past ``timeout``
    node is ended through its exit path, which takes the browsers it launched with it, and
    ``subprocess.TimeoutExpired`` is raised.
    """
    return run_node(
        ["--require", str(preload), str(pptx_from_html_huashu.SIDECAR_SCRIPT), str(out_path)],
        input=json.dumps(payload).encode("utf-8"),
        timeout=timeout,
    )


@requires_huashu_sidecar
class TestDottedRewriteZip:
    def test_the_rewrite_resolves_the_zip_library_pptxgenjs_loads(self) -> None:
        """The rewrite's jszip, resolved from pptxgenjs, is the very file pptxgenjs loads.

        ``package.json`` names no jszip: the rewrite reads and writes the deck
        with the zip library pptxgenjs writes it with, resolved from
        pptxgenjs's own directory. Imported as ``emit_deck.mjs`` imports it,
        pptxgenjs loads one jszip module, and it is that file.
        """
        found = node_json(
            "(async () => {"
            "const path = require('path');"
            f"const {{ pptxgenjsZipPath }} = require({json.dumps(str(EMIT_TABLE_MODULE))});"
            "await import('pptxgenjs');"
            "const loader = require.cache[require.resolve('pptxgenjs')];"
            "const loaded = loader.children.map((child) => child.filename)"
            ".filter((file) => file.split(path.sep).includes('jszip'));"
            "process.stdout.write(JSON.stringify({ resolved: pptxgenjsZipPath(), loaded }));"
            "})();"
        )
        assert found["loaded"] == [found["resolved"]], (
            f"the rewrite resolves {found['resolved']}; pptxgenjs loads {found['loaded']}"
        )


@pytest.mark.slow
@requires_huashu_sidecar
class TestFailedDottedRewrite:
    def test_a_failed_rewrite_writes_the_deck_with_its_dotted_sides_dashed(
        self, tmp_path: Path
    ) -> None:
        """The rewrite fails: one ``[huashu]`` line, and the deck as pptxgenjs wrote it.

        ``emit_deck.mjs`` runs as the wrapper runs it, with the rewrite's zip
        library refusing to read the deck. The export still succeeds: exit 0,
        its one slide written, and the slide's dotted sides dashed (``sysDash``,
        as pptxgenjs writes a dotted side), its solid ones solid. The failure is
        one ``[huashu]`` line naming the dotted borders and its reason.
        """
        preload = tmp_path / "failing_rewrite.cjs"
        preload.write_text(FAILING_REWRITE_PRELOAD, encoding="utf-8")
        out_path = tmp_path / "out.pptx"
        payload = {
            "title": "dotted",
            "slides": [
                {"html": slide_document(DOTTED_BODY, css=TABLES_CSS, slide_id="snapshot-1")}
            ],
            "bypassValidation": True,
            "target": "pptx",
        }
        process = run_sidecar_with_preload(
            preload, out_path, payload, timeout=pptx_from_html_huashu.SIDECAR_TIMEOUT_SECONDS
        )
        stderr = process.stderr
        assert process.returncode == 0 and out_path.is_file(), (
            f"the deck was not written (exit {process.returncode}):\n{stderr[-2000:]}"
        )
        result = json.loads(
            next(
                line
                for line in reversed(stderr.splitlines())
                if line.startswith("__HUASHU_RESULT__")
            ).removeprefix("__HUASHU_RESULT__")
        )
        assert result["succeeded"] == 1 and result["failed"] == [], result
        reported = [
            line for line in stderr.splitlines() if line.startswith("[huashu]") and "dotted" in line
        ]
        assert len(reported) == 1 and REWRITE_FAILURE_REASON in reported[0], (
            f"expected one [huashu] line for the failed rewrite, got {reported}"
        )
        document = slide_document(DOTTED_BODY, css=TABLES_CSS, slide_id="snapshot-1")
        shapes = slide_shapes(out_path.read_bytes())
        (table,) = browser_tables(document, "#dotted")
        _, frame = _frame_for(shapes, _grid_rect(table), "#dotted")
        dashes = {
            (row, col, side): border.dash
            for row, cells in enumerate(frame.table.rows)
            for col, cell in enumerate(cells)
            for side, border in cell.borders.items()
            if border is not None
        }
        assert dashes[(0, 0, "bottom")] == "sysDash" and dashes[(0, 0, "right")] == "sysDash", (
            f"a dotted side is not written dashed, as pptxgenjs writes it: {dashes}"
        )
        assert "sysDot" not in dashes.values(), f"the deck was rewritten after all: {dashes}"


def _with_table(name: str) -> str:
    """A slide-root fixture with a two-cell table after its prose."""
    html = (SLIDE_ROOT_FIXTURE_DIR / f"{name}.html").read_text(encoding="utf-8")
    assert html.count(HOSTILE_ANCHOR) == 1, f"fixture drift: {name}.html has no single prose div"
    return html.replace(HOSTILE_ANCHOR, HOSTILE_ANCHOR + HOSTILE_TABLE, 1)


@pytest.mark.slow
@requires_huashu_sidecar
class TestTablesInAHostileRealm:
    def test_a_realm_that_lies_about_its_nodes_still_exports_a_native_table(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``hostile_text_nodes`` with a table: the export ends in time and the table is native.

        Its slide script replaces every node-level read (``firstChild`` and
        ``nextSibling`` return the node itself, ``childNodes`` claims a billion
        entries, ``textContent`` and ``data`` return a decoy). The export
        completes within the hostile bound, and the table is one native frame
        whose cells read the slide's real text, not the decoy; its model whole,
        so no item is dropped from it (``export_documents``).
        """
        monkeypatch.setattr(
            pptx_from_html_huashu, "SIDECAR_TIMEOUT_SECONDS", HOSTILE_EXPORT_TIMEOUT_SECONDS
        )
        pptx, failures = export_documents(
            [_with_table(HOSTILE_TEXT_NODES)], monkeypatch=monkeypatch, title="snapshot tables"
        )

        assert pptx and failures == [], f"the hostile deck did not export: {failures}"
        shapes = slide_shapes(pptx)
        frames = table_frames(shapes)
        assert len(frames) == 1, (
            f"expected the hostile slide's table as one native table, found {len(frames)}:\n"
            f"{_describe(shapes)}"
        )
        cells = tuple(_normalised(cell.text) for _, _, cell in _origin_cells(frames[0][1]))
        assert cells == HOSTILE_CELLS, (
            f"the hostile slide's table reads {cells}, not the slide's {HOSTILE_CELLS}"
        )

    def test_span_getters_that_lie_leave_the_grid_the_browsers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Slide script makes ``rowSpan``, ``colSpan`` and column ``span`` lie: the grid holds.

        Its script replaces the page realm's ``HTMLTableCellElement`` ``rowSpan``
        and ``colSpan`` getters (7 and 9) and ``HTMLTableColElement``'s ``span``
        (5), and publishes on ``document.title`` that a reader of the realm now
        sees them. The export reads the spans the browser lays the table out
        with: one native frame on the benign twin's grid, span for span, and
        only the third column, which its second ``<col>`` fills, filled.
        """
        hostile_body = _with_script(SPANS_BODY, POISONED_SPANS_SCRIPT)
        report = json.loads(browser_text(slide_document(hostile_body, css=TABLES_CSS), "title"))
        assert report["redefineResult"] == "ok" and all(
            report["configurable"].get(name) for name in POISONED_SPANS
        ), f"the poisoning was refused: {report}"
        assert all(report["bites"].values()), f"a replacement did not take effect: {report}"
        (benign,) = browser_tables(slide_document(SPANS_BODY, css=TABLES_CSS), SPANS_TABLE)
        monkeypatch.setattr(
            pptx_from_html_huashu, "SIDECAR_TIMEOUT_SECONDS", HOSTILE_EXPORT_TIMEOUT_SECONDS
        )
        pptx, failures = export_slides([hostile_body], css=TABLES_CSS, monkeypatch=monkeypatch)
        assert pptx and failures == [], f"the hostile slide did not export: {failures}"
        shapes = slide_shapes(pptx)
        _, frame = _frame_for(shapes, _grid_rect(benign), "the table with lying span getters")
        _assert_grid_matches(frame, benign, "the table with lying span getters")
        fill, column = SPANS_COLUMN_FILL
        filled = {
            (cell.row, cell.col): _owner(frame, cell.row, cell.col).fill for cell in benign.cells
        }
        problems = [
            f"slot {slot} is filled {found}"
            for slot, found in filled.items()
            if found != (fill if slot[1] == column else None)
        ]
        assert not problems, f"only column {column} is #{fill}:\n  " + "\n  ".join(problems)

    def test_a_cell_whose_spans_cannot_be_read_makes_its_table_positioned_items(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A row cell slide script makes in another namespace leaves its table positioned items.

        The element is tagged ``td`` and laid out as a table cell, but it is no
        ``HTMLTableCellElement``, so no span of it can be read. The slide still
        exports, with no native frame on the table, every cell's text as a text
        box, and the reason announced with an ``[html2pptx]`` line.
        """
        document = slide_document(FOREIGN_BODY, css=TABLES_CSS)
        assert browser_rect(document, "#foreign-row > :last-child")["w"] > 0, (
            "fixture drift: the foreign cell is not laid out"
        )
        area = browser_rect(document, FOREIGN_TABLE)
        monkeypatch.setattr(
            pptx_from_html_huashu, "SIDECAR_TIMEOUT_SECONDS", HOSTILE_EXPORT_TIMEOUT_SECONDS
        )
        capsys.readouterr()
        pptx, failures = export_slides([FOREIGN_BODY], css=TABLES_CSS, monkeypatch=monkeypatch)
        stderr = capsys.readouterr().err
        assert pptx and failures == [], f"the slide did not export: {failures}"
        shapes = slide_shapes(pptx)
        assert not _frames_over(shapes, area), (
            f"a native table stands on the table whose cell spans are unreadable:\n"
            f"{_describe(shapes)}"
        )
        for text in FOREIGN_TEXTS:
            assert _text_items(shapes, text), f"{text!r} is not a text box:\n{_describe(shapes)}"
        assert NATIVE_TABLE_LINE in stderr, f"no {NATIVE_TABLE_LINE!r} line on stderr"

    def test_a_grid_past_the_slot_limit_is_positioned_items(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A table whose grid passes ``COLLECTION_ITEM_LIMIT`` slots is positioned items, announced.

        Slide script grows the table to 1,001 rows over 1,000 columns, though
        only one row shows. Its grid is never built: the slide exports within
        the hostile bound, with no native frame, its one line of text a text
        box, and an ``[html2pptx]`` line saying why.
        """
        document = slide_document(AREA_BODY, css=TABLES_CSS)
        area = browser_rect(document, AREA_TABLE)
        assert 0 < area["h"] < SLIDE_HEIGHT_PX and 0 < area["w"] < SLIDE_WIDTH_PX, (
            f"fixture drift: the grown table is {area}, not inside the slide"
        )
        monkeypatch.setattr(
            pptx_from_html_huashu, "SIDECAR_TIMEOUT_SECONDS", HOSTILE_EXPORT_TIMEOUT_SECONDS
        )
        capsys.readouterr()
        pptx, failures = export_slides([AREA_BODY], css=TABLES_CSS, monkeypatch=monkeypatch)
        stderr = capsys.readouterr().err
        assert pptx and failures == [], f"the slide did not export: {failures}"
        shapes = slide_shapes(pptx)
        assert not _frames_over(shapes, area), (
            f"a native table stands on the table past the slot limit:\n{_describe(shapes)}"
        )
        assert _text_items(shapes, AREA_TEXT), f"{AREA_TEXT!r} is not a text box"
        assert NATIVE_TABLE_LINE in stderr, f"no {NATIVE_TABLE_LINE!r} line on stderr"


# ---------------------------------------------------------------------------
# Through Drive: the borders Google Slides keeps
# ---------------------------------------------------------------------------


def _slides_api_border(border_cell: dict) -> tuple[str | None, float]:
    """(colour, weight in EMU) of one Slides API table border cell."""
    properties = border_cell.get("tableBorderProperties", {})
    weight = properties.get("weight", {})
    assert weight.get("unit", "EMU") == "EMU", f"unexpected border weight {weight}"
    return slides_api_color(properties.get("tableBorderFill")), float(weight.get("magnitude", 0))


def _slides_api_table_reading(tables: list[dict], text: str) -> tuple[dict, int]:
    """(table, row index) of the converted table whose row starts with a cell reading ``text``."""
    read = []
    for element in tables:
        rows = element["table"].get("tableRows", [])
        for row_index, row in enumerate(rows):
            cells = row.get("tableCells", [])
            if cells and _normalised(slides_api_cell_text(cells[0])) == text:
                return element["table"], row_index
        read.append(
            [
                _normalised(slides_api_cell_text(cell))
                for row in rows
                for cell in row.get("tableCells", [])
            ]
        )
    raise AssertionError(f"no converted table has a row starting {text!r}; the tables read {read}")


def _drive_border_problems(
    presentation: dict,
    balance_tables: list[BrowserTable],
    balance_document: str,
    collapse_document: str,
) -> list[str]:
    """Every converted border line that differs from what the browser paints there.

    A slide Drive did not convert into its tables is reported, not raised, so
    the caller's message names the presentation it deleted.
    """
    balance = slides_api_tables(presentation, 0)
    collapse = slides_api_tables(presentation, 1)
    if len(balance) != 2 or len(collapse) != 1:
        return [
            f"Drive converted fixture 05 into {len(balance)} tables (not 2) and the collapse "
            f"document into {len(collapse)} (not 1)"
        ]
    # Fixture 05: the line along the top and the bottom of each total row.
    points = []
    expectations = []
    for table, label in zip(balance_tables, TOTAL_LABELS):
        (total,) = table.cells_reading(label)
        converted, row_index = _slides_api_table_reading(balance, label)
        for boundary, edge_y in ((row_index, total.y), (row_index + 1, total.y + total.h)):
            for cell in (cell for cell in table.cells if cell.row == total.row):
                points.append((cell.x + cell.w / 2, edge_y))
                expectations.append((converted, boundary, cell.col, f"{label!r} line {boundary}"))
    pixels = browser_pixels(balance_document, points)
    problems = []
    for (converted, boundary, col, what), pixel in zip(expectations, pixels):
        border_cells = converted["horizontalBorderRows"][boundary]["tableBorderCells"]
        colour, _ = _slides_api_border(border_cells[col])
        if colour != _hex(pixel):
            problems.append(
                f"{what}, column {col}: Drive keeps #{colour}, the browser paints #{_hex(pixel)}"
            )

    # The collapse document: each edge's colour and width in every column or row.
    (collapse_table,) = browser_tables(collapse_document, "#collapse")
    (converted,) = collapse
    for row, (colour, width_px) in COLLAPSE_ROW_EDGES.items():
        for col in range(collapse_table.columns):
            found = _slides_api_border(
                converted["table"]["horizontalBorderRows"][row]["tableBorderCells"][col]
            )
            problems.extend(
                _weighed(found, colour, width_px, f"collapse row line {row}, column {col}")
            )
    for col, (colour, width_px) in COLLAPSE_COLUMN_EDGES.items():
        for row in range(len(collapse_table.rows)):
            found = _slides_api_border(
                converted["table"]["verticalBorderRows"][row]["tableBorderCells"][col]
            )
            problems.extend(
                _weighed(found, colour, width_px, f"collapse column line {col}, row {row}")
            )
    return problems


@pytest.mark.slow
@requires_huashu_sidecar
@requires_google_slides
class TestTablesThroughGoogleSlides:
    def test_collapsed_edges_survive_the_drive_conversion_in_every_column(
        self, monkeypatch: pytest.MonkeyPatch, balance_tables: list[BrowserTable]
    ) -> None:
        """Converted by Drive, each collapsed edge is the browser's line in every column.

        Fixture 05 and the collapse document are exported in one deck and
        converted through Drive, and the Slides API's table borders are read
        back (``horizontalBorderRows[i]`` is the line along the top of row
        ``i``). The lines along the top and the bottom of each balance-sheet
        total row ("Total current assets", "Total liabilities"), and the
        collapse document's three edges, are in every column (or row) the
        colour the browser paints there, and the collapse edges also its width.
        A side written as a cell's own, against a neighbour's ``noFill`` or
        other colour, is what Drive drops or picks the wrong side of. The
        presentation the conversion created is deleted once it has been read,
        whatever the outcome.
        """
        balance_document = corpus_document("05")
        collapse_document = _inline_document("collapse")
        pptx, failures = export_documents(
            [balance_document, collapse_document], monkeypatch=monkeypatch
        )
        assert pptx and failures == [], f"the export rejected a slide: {failures}"
        conversion = google_slides_presentation(pptx, list(GOOGLE_SLIDE_NAMES))
        try:
            problems = _drive_border_problems(
                conversion.presentation, balance_tables, balance_document, collapse_document
            )
        finally:
            delete_drive_file(conversion.presentation_id)
        assert not problems, (
            f"Drive's table borders differ from the browser's (presentation "
            f"{conversion.presentation_id}, deleted after reading):\n  " + "\n  ".join(problems)
        )

    def test_a_rounded_tables_corner_pieces_meet_their_neighbours_as_its_cells_do(
        self, google_inline_export: Callable[[str], bytes]
    ) -> None:
        """D13, opt-in (``TELLR_GOOGLE_TESTS=1``): the rounded data table in Drive's thumbnail.

        The table's deck for Google Slides, converted through Drive and read
        back as its LARGE thumbnail. Every inner edge of each corner piece (its
        side beside the header or body cell, and its side above or below the
        next row) shows no more than the 2 levels native cells show: no light
        column where a coral piece meets the coral header cell, and the piece's
        edge above the white row drawn as the header cell's beside it. The
        table's first inner column line lies 0.44 of a thumbnail pixel past
        one, where the piece meeting its neighbour on the line seamed by 104
        levels, and its header's bottom 0.75 past one, where the piece's row
        was 46 levels lighter than the header cell's (CALIBRATION.md D13). The
        presentation is deleted afterwards.
        """
        document = _inline_document("rounded")
        (table,) = browser_tables(document, "table")
        pptx = google_inline_export("rounded")
        _, frame = _frame_for(slide_shapes(pptx), _grid_rect(table), "the rounded data table")
        phase = (table_column_edges(frame)[1] * THUMBNAIL_SCALE) % 1
        assert 0.05 < phase < 0.95, (
            f"fixture drift: the first inner column line lies {phase:.2f} past a thumbnail pixel"
        )
        conversion = google_slides_presentation(pptx, ["rounded"])
        try:
            image = _google_thumbnail(conversion.presentation, 0)
        finally:
            delete_drive_file(conversion.presentation_id)
        problems = _corner_piece_edges_in_google(image, frame)
        assert not problems, "Google's thumbnail shows the corner pieces' edges:\n  " + (
            "\n  ".join(problems)
        )


# Drive's LARGE thumbnail is 1600 px wide: 1.25 of its pixels to a CSS px.
THUMBNAIL_SCALE = 1.25
# A boundary within this many levels (any channel) of what Google draws between two native
# cells: native cell boundaries show 0 in the thumbnail (CALIBRATION.md D13).
THUMBNAIL_SEAM_LEVELS = 2


def _google_thumbnail(presentation: dict, index: int) -> Image.Image:
    """Slide ``index`` of a converted presentation as Drive's LARGE (1600 px) thumbnail."""
    harness = fidelity_harness()
    token = harness._google_token()
    page = presentation["slides"][index]["objectId"]
    thumbnail = json.loads(
        harness._google_request(
            f"https://slides.googleapis.com/v1/presentations/{presentation['presentationId']}"
            f"/pages/{page}/thumbnail?thumbnailProperties.thumbnailSize=LARGE",
            token,
        )
    )
    return Image.open(BytesIO(harness._google_request(thumbnail["contentUrl"], token))).convert(
        "RGB"
    )


def _thumbnail_profile(
    image: Image.Image, line: float, span: tuple[float, float], vertical: bool
) -> list[tuple[int, ...]]:
    """The thumbnail's pixels across the grid ``line`` (CSS px; a column line when ``vertical``),
    two either side of it, each the per-channel median along ``span`` (CSS px) of the line."""
    centre = int(line * THUMBNAIL_SCALE)
    first, last = int(span[0] * THUMBNAIL_SCALE), int(span[1] * THUMBNAIL_SCALE)
    profile = []
    for offset in range(centre - 2, centre + 3):
        samples = [
            image.getpixel((offset, along) if vertical else (along, offset))
            for along in range(first, last)
        ]
        profile.append(
            tuple(
                sorted(sample[channel] for sample in samples)[len(samples) // 2]
                for channel in range(3)
            )
        )
    return profile


def _corner_piece_edges_in_google(image: Image.Image, frame: Shape) -> list[str]:
    """Every inner edge of each corner piece of the rounded data table, in Google's thumbnail.

    An edge between two fills alike (a coral piece beside the coral header cell) is a seam
    where any pixel across it strays from that fill; an edge between two fills (the coral
    piece above the white body cell) is a seam where its profile differs from the native
    neighbour's on the same line (the header cell beside the piece, above the same white row).
    Each beyond THUMBNAIL_SEAM_LEVELS, the levels native cells show, is listed."""
    columns, rows = table_column_edges(frame), table_row_edges(frame)
    margin = ROUNDED_RADIUS_PX + 3
    problems = []
    for (row, col), corner in ROUNDED_CORNERS.items():
        fill = tuple(int(ROUNDED_FILLS[row][col][i : i + 2], 16) for i in (0, 2, 4))
        across_col = col + (1 if "left" in corner else -1)
        line = columns[col + 1] if "left" in corner else columns[col]
        span = (rows[row] + margin, rows[row + 1] - margin)
        neighbour = tuple(int(ROUNDED_FILLS[row][across_col][i : i + 2], 16) for i in (0, 2, 4))
        assert neighbour == fill, f"fixture drift: slot ({row}, {across_col}) is not {fill}"
        profile = _thumbnail_profile(image, line, span, vertical=True)
        stray = max(
            abs(pixel[channel] - fill[channel]) for pixel in profile for channel in range(3)
        )
        if stray > THUMBNAIL_SEAM_LEVELS:
            problems.append(
                f"slot ({row}, {col}) {corner}: across column line {line:.3f} the thumbnail strays "
                f"{stray} levels from #{ROUNDED_FILLS[row][col]}: {profile}"
            )
        across_row = row + (1 if "top" in corner else -1)
        line = rows[row + 1] if "top" in corner else rows[row]
        piece_span = (columns[col] + margin, columns[col + 1] - margin)
        native_span = (columns[across_col] + margin, columns[across_col + 1] - margin)
        piece = _thumbnail_profile(image, line, piece_span, vertical=False)
        native = _thumbnail_profile(image, line, native_span, vertical=False)
        differs = max(abs(a - b) for p, q in zip(piece, native) for a, b in zip(p, q))
        if differs > THUMBNAIL_SEAM_LEVELS:
            problems.append(
                f"slot ({row}, {col}) {corner}: across row line {line:.3f} (toward row "
                f"{across_row}) the piece's profile {piece} differs from the native cell's "
                f"{native} by {differs} levels"
            )
    return problems


def _weighed(found: tuple[str | None, float], colour: str, width_px: float, what: str) -> list[str]:
    """What is wrong with a converted border against the browser's colour and width, if anything."""
    found_colour, weight = found
    expected_weight = width_px * PT_PER_PX * EMU_PER_PT
    if found_colour != colour or abs(weight - expected_weight) > WEIGHT_TOLERANCE_EMU:
        return [
            f"{what}: Drive keeps #{found_colour} at {weight:.0f} EMU; the browser paints "
            f"#{colour} at {width_px:g} px ({expected_weight:.0f} EMU)"
        ]
    return []
