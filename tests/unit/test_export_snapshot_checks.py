"""Snapshot engine: the per-slide checks.

The snapshot engine checks every slide it writes, so text loss is visible in
the app log and in the export fidelity harness (spec §6):

* ``services/pptx-emit-huashu/text_check.cjs`` holds the comparison.
  ``missingWords(reference, emitted, hidden)`` returns the reference words,
  as the reference spells them and in its order, whose normalised form (white
  space and default-ignorable code points removed, lower-cased) is in no
  emitted text, each compared alone, leaving out the slide's hidden words.
  ``textLossLine(reference, items, hidden)`` collects the text of each of a
  slide model's items (text items, which hold every list marker, outside ones
  as items of their own and inside ones as tokens of their line, and native
  table cells) and returns ``[html2pptx] text missing: <json array>`` naming
  the words in none of them that are not written across neighbours either,
  or null when nothing is missing. An atomic inline (an inline-block numeral,
  a chip) is an item of its own, so innerText's "1Financials" or "Iceberg," is
  written in two items, which are neighbours on the slide; a lost chip's two
  sides are not, so its letters at their ends are no excuse (Task 15 H2, fix
  round 1; *Words across neighbours* below). Both are pure, so they are
  tested here in Node over hand-built item arrays, with no browser, on the
  one table of cases the harness's twin reads as hand-built decks.
* ``render_slide.cjs`` reads the reference after the captures (the body's
  ``innerText`` with every ``<svg>`` and ``<canvas>`` hidden, through the
  pristine-realm accessors), logs the ``text missing`` line when a word is
  missing, and always one ``[html2pptx] slide summary <json>`` line per slide
  on stderr. The summary keeps every key ``summarise()`` returns
  (``bgTransferred``, ``animations``, ``elements``, ``pseudoElements {read,
  walked}``, ``kinds``, ``pictures``, ``skippedPictures``, ``captures``,
  ``captureFailures``) and adds ``text``, ``shapes``, ``lines``, ``tables``
  (item counts), ``captureMs`` (the wall time of the slide's captures),
  ``hiddenText`` (``model.reference.hiddenText``) and ``target`` (the renderer
  the deck is written for). ``captureMs`` is a clock reading: it goes to
  stderr only, so repeated exports stay byte-identical.
* ``scripts/export_fidelity/run.py`` reads those lines.
  ``export_pptx`` tees stderr and records the summaries in
  ``summaries{suffix}.json`` beside ``failures{suffix}.json``: one entry per
  document in slide order, null for a slide the sidecar wrote no summary for.
  ``check_text_loss(pptx_path, names, out_dir, hidden_text=None)`` excludes
  ``hidden_text[i]``'s words from slide ``names[i]``, and reports every word
  of a slide the ``.pptx`` lacks (upstream PR #59), wherever the gap falls.
  Its normalisation removes default-ignorable code points too: the PowerPoint
  deck writes a word joiner (U+2060) after a line-ending script run.
* Every line the sidecar prints is ONE line as Python's ``str.splitlines()``
  reads it (``services/pptx-emit-huashu/log_line.cjs``: ``logJson`` and
  ``oneLine``), so a slide's console text holding a line break cannot print a
  line of the sidecar's own: a slide summary, a text-loss line or the
  ``__HUASHU_RESULT__`` failure list ``build_pptx_huashu`` returns. Node and
  Python normalise with the same sets, pinned by enumerating every code point,
  and every text reference (the sidecar's, ``render_truth.cjs``'s and
  ``measure.cjs``'s) hides the graphics the same way, against a deck's
  ``!important`` display rule and a display transition alike.
* The slide's realm builds the model (with an ``Array.prototype.push`` slide
  script can replace), so Node checks it before any use
  (``services/pptx-emit-huashu/model_check.cjs``): a capture or
  item the snapshot could not have written is dropped, counted in one
  ``[html2pptx] model: …`` line and in the summary's ``modelDrops``, and the
  rest of the slide exports. A real slide's model drops nothing: the shared
  export helpers fail on any such line (``allow_model_drops`` opts out), and
  the harness names each slide that dropped in a ``MODEL DROPS:`` warning.

The hidden words are pinned per case: opacity 0 inline,
block and inline-block, nested, a word split over two text nodes, a table
cell, off-slide text, a zero-width clip, fixture 03's screen-reader-only
table, and the characters a ``text-overflow: ellipsis`` hides. Text at
``visibility: hidden`` is not hidden text: ``innerText`` leaves it out too.
Every case's words come from the browser's own reading of the very document
exported (``render_truth.cjs`` for the harness reference, ``browser_ellipsis``
for an ellipsis cut).

Gating matches the sibling export suites: the Node tests need node; the export
tests need node, the extracted sidecar ``node_modules`` and a local
Chrome/Chromium (skipped otherwise). Corpus slides come from
``tests/fixtures/export_fidelity`` by prefix (``corpus_document``).
"""

from __future__ import annotations

import functools
import io
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from PIL import Image

from src.services import pptx_from_html_huashu
from tests.fixtures.export_snapshot_support import (
    CORPUS_DIR,
    DECK_CSS,
    EMU_PER_PX,
    LoggedExport,
    browser_ellipsis,
    browser_lines,
    browser_text,
    browser_title,
    corpus_document,
    corpus_slide,
    export_logged,
    fidelity_harness,
    node_json,
    pinned_font_css,
    reference_text_loss,
    requires_huashu_sidecar,
    requires_node,
    slide_background,
    slide_document,
    slide_shapes,
    slide_summaries,
    teed_stderr,
    text_loss,
    text_missing_reports,
)
from tests.unit.test_export_svg_raster import structural_manifest

TEXT_CHECK_MODULE = Path(pptx_from_html_huashu.SIDECAR_DIR) / "text_check.cjs"
TEXT_MISSING_PREFIX = "[html2pptx] text missing: "

# The keys render_slide.cjs summarise() returns today, which the logged summary keeps.
EXISTING_SUMMARY_KEYS = (
    "bgTransferred",
    "animations",
    "elements",
    "pseudoElements",
    "kinds",
    "pictures",
    "skippedPictures",
    "captures",
    "captureFailures",
)
# The keys the checks add to the summary: the item counts, the capture time, the
# hidden text and the target. modelDrops is the model check's count (model_check.cjs).
ADDED_SUMMARY_KEYS = (
    "text",
    "shapes",
    "lines",
    "tables",
    "captureMs",
    "hiddenText",
    "target",
    "modelDrops",
)
# No `pseudo` key: the pseudo-element count is the existing pseudoElements.
REPLACED_SUMMARY_KEY = "pseudo"

# Default-ignorable code points (Unicode Default_Ignorable_Code_Point) the
# comparison must see through: the word joiner the PowerPoint deck writes after
# a line-ending script run, and the invisible characters authored text carries.
DEFAULT_IGNORABLE_CODE_POINTS = {
    "word-joiner-U+2060": "⁠",
    "zero-width-space-U+200B": "​",
    "soft-hyphen-U+00AD": "­",
    "zero-width-no-break-space-U+FEFF": "﻿",
}
WORD_JOINER = "⁠"

# Every synthetic slide carries this paragraph, so an export that drops
# everything cannot pass for one that drops only the hidden content.
LEAD = '<p id="lead" style="font-size: 20px;">Quarterly results at a glance</p>'

# Fixture 03's screen-reader-only data table (deck.css .sr-only), in reading order.
SR_ONLY_WORDS = ("Year", "Revenue", "FY20", "905", "FY24", "1,240")


@dataclass(frozen=True)
class HiddenCase:
    """A document whose only text the slide does not show is ``hidden_words``, in reading order."""

    document: str
    hidden_words: tuple[str, ...]


def _case_document(body: str) -> str:
    return slide_document(body, css=DECK_CSS, slide_id="snapshot-1")


# The pinned hiddenText cases. Each hidden
# word appears nowhere visible on its slide, so the harness's bare oracle
# reports it, which proves the case bites.
HIDDEN_CASES: dict[str, HiddenCase] = {
    "inline-opacity-zero": HiddenCase(
        _case_document(
            '<div class="slide"><p style="font-size: 20px;">Revenue '
            '<span style="opacity: 0;">secretword</span> grew</p></div>'
        ),
        ("secretword",),
    ),
    "block-opacity-zero": HiddenCase(
        _case_document(
            f'<div class="slide">{LEAD}<div style="opacity: 0; font-size: 20px;">'
            "Ghost <b>heading</b><div>Phantom child</div></div></div>"
        ),
        ("Ghost", "heading", "Phantom", "child"),
    ),
    "inline-block-opacity-zero": HiddenCase(
        _case_document(
            '<div class="slide"><p style="font-size: 20px;">Before '
            '<span style="display: inline-block; opacity: 0;">blockword</span> after</p></div>'
        ),
        ("blockword",),
    ),
    # Opacity multiplies: 0.5 then 0 is 0; the sibling at 0.5 still shows.
    "nested-opacity": HiddenCase(
        _case_document(
            f'<div class="slide">{LEAD}<div style="opacity: 0.5;">'
            '<p style="opacity: 0; font-size: 20px;">Nested zero</p>'
            '<p style="font-size: 20px;">Half shown</p></div></div>'
        ),
        ("Nested", "zero"),
    ),
    # One word over two text nodes is one hidden word, not "Rev enue".
    "split-word-join": HiddenCase(
        _case_document(
            '<div class="slide"><p style="font-size: 20px;">Total '
            '<span style="opacity: 0;">Rev<b>enue</b></span> up</p></div>'
        ),
        ("Revenue",),
    ),
    "hidden-table-cell": HiddenCase(
        _case_document(
            f'<div class="slide">{LEAD}<table style="font-size: 18px;"><tr><td>Shown</td>'
            '<td style="opacity: 0;">Gone cell</td></tr></table></div>'
        ),
        ("Gone", "cell"),
    ),
    "off-slide": HiddenCase(
        _case_document(
            f'<div class="slide">{LEAD}<div style="position: absolute; left: 80px; top: 740px; '
            'font-size: 20px;">Offstage Quokka</div></div>'
        ),
        ("Offstage", "Quokka"),
    ),
    # An overflow box of no width: its text overflows into a clip of nothing.
    "zero-width-clip": HiddenCase(
        _case_document(
            f'<div class="slide">{LEAD}<div style="position: absolute; left: 600px; top: 200px; '
            'width: 0; overflow: hidden; white-space: nowrap; font-size: 20px;">'
            "Zerowidth clipped</div></div>"
        ),
        ("Zerowidth", "clipped"),
    ),
    "screen-reader-only-fixture-03": HiddenCase(corpus_document("03"), SR_ONLY_WORDS),
}

# visibility: hidden text is in neither innerText nor hiddenText.
VISIBILITY_HIDDEN = "visibility-hidden"
VISIBILITY_HIDDEN_DOCUMENT = _case_document(
    f'<div class="slide">{LEAD}<div style="visibility: hidden; font-size: 20px;">'
    "Invisible words</div></div>"
)
VISIBILITY_HIDDEN_WORDS = ("Invisible", "words")

# The deck the hidden cases are exported in, in slide order.
HIDDEN_DECK = (*HIDDEN_CASES, VISIBILITY_HIDDEN)

# A one-line title that text-overflow: ellipsis cuts inside a word.
ELLIPSIS_SELECTOR = "#title"
ELLIPSIS_TITLE = "Quarterly liquidity overview for every regional segment"
ELLIPSIS_DOCUMENT = _case_document(
    '<div class="slide"><h1 id="title" style="width: 420px; white-space: nowrap; '
    'overflow: hidden; text-overflow: ellipsis; font-size: 40px; margin: 0;">'
    f"{ELLIPSIS_TITLE}</h1></div>"
)

# One of each item kind, by construction, on a slide with no deck CSS (Arial,
# no webfont): two paragraphs, a filled box (a shape), a box with one bordered
# side (a line), a collapsed bordered table (a native table), an inline SVG (a
# captured picture) and a one-item list (its ::marker is a text item of its own
# beside the item's text, and the one pseudo-element read).
COUNTS_BODY = (
    '<div style="position: absolute; left: 0; top: 0; width: 1280px; height: 720px; '
    'font-family: Arial;">'
    '<p style="position: absolute; left: 80px; top: 60px; font-size: 24px; margin: 0;">'
    "Alpha heading</p>"
    '<p style="position: absolute; left: 80px; top: 120px; font-size: 20px; margin: 0;">'
    "Beta body</p>"
    '<div style="position: absolute; left: 80px; top: 200px; width: 200px; height: 80px; '
    'background: #123456;"></div>'
    '<div style="position: absolute; left: 400px; top: 200px; width: 200px; height: 80px; '
    'border-bottom: 3px solid #FF0000;"></div>'
    '<table style="position: absolute; left: 80px; top: 320px; border-collapse: collapse; '
    'font-size: 16px;"><tr>'
    '<td style="border: 1px solid #000000; padding: 4px;">Cell one</td>'
    '<td style="border: 1px solid #000000; padding: 4px;">Cell two</td></tr></table>'
    '<svg style="position: absolute; left: 700px; top: 200px;" width="120" height="60">'
    '<rect width="120" height="60" fill="#00A972"/></svg>'
    '<ul style="position: absolute; left: 80px; top: 460px; margin: 0; font-size: 20px;">'
    "<li>Gamma item</li></ul>"
    "</div>"
)
COUNTS_DOCUMENT = slide_document(COUNTS_BODY, css="", slide_id="snapshot-1")
# The SVG's one solid fill, opaque: what its captured picture shows at its centre.
COUNTS_SVG_FILL = (0x00, 0xA9, 0x72, 255)
# What COUNTS_BODY is built from: (summary count key, model item kind, pptx Shape kind, count).
COUNTS = (
    ("text", "text", "text", 4),
    ("shapes", "shape", "shape", 1),
    ("lines", "line", "line", 1),
    ("tables", "table", "table", 1),
    ("pictures", "image", "picture", 1),
)
# Repeated exports until two capture times differ: the clock rarely repeats a reading.
MAX_DETERMINISM_EXPORTS = 3

# A <select> shows its selected option, which innerText reads, but the export
# draws the control's box only: real, visible text loss. The slide also holds
# an <svg>, captured as a picture with its label inside it, so the reference
# read once the captures are taken is shown to read the slide's text, and to
# leave the picture's text out.
SELECT_WORD = "Liquidityoption"
SELECT_SVG_LABEL = "Svglabel"
SELECT_DOCUMENT = _case_document(
    f'<div class="slide">{LEAD}<select style="font-size: 20px;">'
    f"<option>{SELECT_WORD}</option></select>"
    '<svg width="200" height="60"><rect width="200" height="60" fill="#00A972"/>'
    f'<text x="10" y="40" font-size="20">{SELECT_SVG_LABEL}</text></svg></div>'
)

# Unspaced (CJK) text whose first line ends with a superscript: the PowerPoint
# deck writes a word joiner after it, inside what innerText reads as one word.
JOINED_SELECTOR = "#joined"
JOINED_LINES = ["收入增长1", "同比上升"]
JOINED_BODY = (
    f'<div class="slide">{LEAD}<p id="joined" style="width: 96px; font-size: 20px; '
    'margin: 0;">收入增长<sup>1</sup>同比上升</p></div>'
)
JOINED_DOCUMENT = _case_document(JOINED_BODY)

# Words the page runs across an atomic inline's edge, as real decks write them
# (the Task 15 matrix): an inline-block numeral before its item's first word
# (long-off 02), and a chip followed by a comma (dense-tpl18 03). The export
# writes each atomic inline as an item of its own, painted after the text
# around it, so innerText's "1Financials" and "Iceberg," are written in two
# items each.
ATOMIC_JOINED_WORDS = ("1Financials", "2Operations", "Iceberg,")
ATOMIC_CHIP = (
    'style="display: inline-block; padding: 0 8px; border-radius: 999px; '
    'background: #EEECE6; border: 1px solid #DCE0E2;"'
)
ATOMIC_NUMERAL = 'style="display: inline-block; min-width: 28px;"'
ATOMIC_BODY = (
    f'<div class="slide">{LEAD}<ol style="list-style: none; margin: 0; padding: 0; '
    'font-size: 18px;">'
    f"<li><b {ATOMIC_NUMERAL}>1</b><b>Financials</b> — Revenue up 9% to $1.80B</li>"
    f"<li><b {ATOMIC_NUMERAL}>2</b><b>Operations</b> — On-time delivery held</li></ol>"
    '<p style="width: 900px; font-size: 20px;">Open table formats such as '
    f"<span {ATOMIC_CHIP}>Delta Lake</span> and <span {ATOMIC_CHIP}>Apache Iceberg</span>, "
    f"together with <span {ATOMIC_CHIP}>MLflow</span>, shorten the path.</p></div>"
)
ATOMIC_DOCUMENT = _case_document(ATOMIC_BODY)

# ---------------------------------------------------------------------------
# Words across neighbours (Task 15 H2, fix round 1)
# ---------------------------------------------------------------------------
# A word no item holds whole is still written when it lies across the joins of
# a chain of neighbouring text items, each item's text run on into the next's.
# Two items are neighbours when both are unturned and of one line, run the same
# way, share a line (overlap by more than half the shorter's height, as
# snapshot_text.mjs groups tokens into lines) and the head's text starts from
# NEIGHBOUR_OVERLAP_EM before the tail's text ends to NEIGHBOUR_GAP_EM after
# it, in ems of the larger of the two items' sizes: the room an atomic
# inline's edge (its padding, border and margin, and the room its content box
# leaves its text) makes. A lost chip leaves both its edges and its own text
# between the boxes either side of it. A text's ends are its box's less the
# slack snapshot_text.mjs gives the box on the side its alignment grows.
#
# Each case is one slide of boxes that both checks read: the sidecar's as text
# items of a slide model (_model_item), the harness's as a deck's text boxes
# (_deck_of_boxes). The real cases' boxes are the export's own, measured on
# the Task 15 matrix decks (long-off 02, dense-tpl18 03) and on a slide laying
# out the review's probe (its seven boxes; the "AI", "ML" and "KPI" chips
# between the boxes whose ends spell them), each read from the slide model the
# sidecar wrote for it.


# The slide model's units: pt = px * 0.75 (units.cjs).
PT_PER_PX = 0.75


@dataclass(frozen=True)
class Box:
    """One text box of a hand-built slide, in CSS px, as snapshot_text.mjs lays it out.

    ``x, y, w, h`` is the box, its slack included, and ``size`` its runs'
    font size. A ``text`` holding a newline is a box of more than one line
    (wrapped). ``script`` is a superscript run ending it, ``(text, size)`` at
    the browser's size, which the deck writes larger (emit_typography.cjs
    SUPERSCRIPT_SIZE_FACTOR).
    """

    text: str
    x: float
    y: float
    w: float
    h: float
    size: float
    align: str = "left"
    rtl: bool = False
    rotate: float = 0
    script: tuple[str, float] | None = None


def _snapshot_text_constant(name: str) -> float:
    """The value of ``const NAME = <number>;`` in snapshot_text.mjs's text layout."""
    source = (Path(pptx_from_html_huashu.SIDECAR_DIR) / "snapshot_text.mjs").read_text()
    found = re.findall(rf"^\s*const {re.escape(name)} = (-?[\d.]+);", source, re.MULTILINE)
    assert len(found) == 1, (
        f"snapshot_text.mjs defines `const {name} = <number>;` {len(found)} times"
    )
    return float(found[0])


def _box_around(
    text: str,
    start: float,
    end: float,
    *,
    y: float = 100,
    h: float = 21,
    size: float = 18,
    align: str = "left",
    rtl: bool = False,
    rotate: float = 0,
    script: tuple[str, float] | None = None,
) -> Box:
    """The box snapshot_text.mjs textBlock lays out for text (or the content box of a
    centred or right-aligned block) from ``start`` to ``end`` px: widened by its slack
    on the side its alignment grows."""
    extra = (end - start) * _snapshot_text_constant("SLACK_FRACTION") + _snapshot_text_constant(
        "SLACK_PX"
    )
    shift = extra / 2 if align == "center" else extra if align == "right" else 0
    return Box(text, start - shift, y, end - start + extra, h, size, align, rtl, rotate, script)


# long-off 02's first two rows: each item's inline-block numeral (min-width
# 28px at 18px, its text 10 px wide) is a text item of its own, after its row's.
NUMERAL_ROWS = (
    Box(
        "Financials — Revenue up 9% to $1.80B with a 14.0% EBITDA margin",
        138,
        156,
        601.11125,
        21,
        18,
    ),
    Box("1", 110, 156, 14.6165625, 21, 18),
    Box(
        "Operations — On-time delivery, fleet and warehouse performance",
        138,
        217,
        566.7771875,
        21,
        18,
    ),
    Box("2", 110, 217, 14.6165625, 21, 18),
)
NUMERAL_REFERENCE = (
    "1Financials — Revenue up 9% to $1.80B with a 14.0% EBITDA margin "
    "2Operations — On-time delivery, fleet and warehouse performance"
)
# dense-tpl18 03's two cut lines: the four chips (16 px, padding 8 px, border
# 1 px) are text items of their own, after their lines' segments.
CHIP_LINES = (
    Box(
        "Vendor A leads on speed, cost and time to value. Open table formats such as",
        88,
        366.59375,
        777.700625,
        26,
        20,
    ),
    Box("and", 925.265625, 366.59375, 40.9178125, 26, 20),
    Box(",", 1102.8125, 366.59375, 7.77625, 26, 20),
    Box("together with", 88, 398.59375, 134.0984375, 26, 20),
    Box("and", 292.90625, 398.59375, 40.9178125, 26, 20),
    Box(
        ", shorten the path to a first model. Pipeline reliability is the one trade-off",
        452.78125,
        398.59375,
        709.330625,
        26,
        20,
    ),
    Box("Delta Lake", 832.21875, 370.59375, 87.475, 21, 16),
    Box("Apache Iceberg", 974.390625, 370.59375, 130.5871875, 21, 16),
    Box("MLflow", 225.03125, 402.59375, 60.7928125, 21, 16),
    Box("Unity Catalog", 342.03125, 402.59375, 111.855, 21, 16),
)
CHIP_REFERENCE = (
    "Vendor A leads on speed, cost and time to value. Open table formats such as Delta Lake "
    "and Apache Iceberg, together with MLflow and Unity Catalog, shorten the path to a first "
    "model. Pipeline reliability is the one trade-off"
)
# The review's probe: its seven boxes, laid out on a slide with each lost chip
# between the two boxes whose ends spell it ("Customer Data" [AI] "Insights for
# every team", "Platform" [ML] "Lakehouse governance", "Risk" [KPI] "Pipeline
# health"), in the order the slide paints them; each chip comes after its line.
PROBE_BOXES = {
    "Revenue grew 12%": Box("Revenue grew 12%", 88, 72, 353.9159375, 52, 40),
    "Customer Data": Box("Customer Data", 88, 156, 152.0853125, 26, 20),
    "Insights for every team": Box("Insights for every team", 270.65625, 156, 227.6765625, 26, 20),
    "AI": Box("AI", 242, 160, 19.2209375, 21, 16),
    "Platform": Box("Platform", 88, 202, 86.415, 26, 20),
    "Lakehouse governance": Box("Lakehouse governance", 216.265625, 202, 227.4778125, 26, 20),
    "ML": Box("ML", 180.0625, 206, 27.220625, 21, 16),
    "Risk": Box("Risk", 88, 248, 42.9715625, 26, 20),
    "Pipeline health": Box("Pipeline health", 175.71875, 248, 147.16625, 26, 20),
    "KPI": Box("KPI", 139.0625, 252, 27.7009375, 21, 16),
}
PROBE_CHIPS = ("AI", "ML", "KPI")
# The review's own reference and its boxes' order.
PROBE_REFERENCE = (
    "Customer Data AI Revenue grew 12% Insights for every team Platform ML Lakehouse "
    "governance Risk KPI Pipeline health"
)
PROBE_REVIEW_ORDER = (
    "Platform",
    "Customer Data",
    "Risk",
    "Revenue grew 12%",
    "Lakehouse governance",
    "Insights for every team",
    "Pipeline health",
)


def _probe(names: tuple[str, ...]) -> tuple[Box, ...]:
    return tuple(PROBE_BOXES[name] for name in names)


PROBE_PAINT_ORDER = tuple(PROBE_BOXES)
PROBE_LOST_IN_PAINT_ORDER = tuple(name for name in PROBE_PAINT_ORDER if name not in PROBE_CHIPS)
# The slide the probe's boxes were measured on, for the real export.
PROBE_CHIP = (
    'style="display: inline-block; padding: 0 8px; border-radius: 999px; '
    'background: #EEECE6; border: 1px solid #DCE0E2; font-size: 16px;"'
)
PROBE_PARAGRAPH = 'style="font-size: 20px; margin: 0 0 20px;"'
PROBE_BODY = (
    '<div class="slide"><h1 style="font-size: 40px; margin: 0 0 32px;">Revenue grew 12%</h1>'
    f"<p {PROBE_PARAGRAPH}>Customer Data <span {PROBE_CHIP}>AI</span> Insights for every team</p>"
    f"<p {PROBE_PARAGRAPH}>Platform <span {PROBE_CHIP}>ML</span> Lakehouse governance</p>"
    f"<p {PROBE_PARAGRAPH}>Risk <span {PROBE_CHIP}>KPI</span> Pipeline health</p></div>"
)

# A synthetic line at 18 px, the numeral's text from 110 to 120 px: an edge of
# NEIGHBOUR_GAP_EM (1.5) is 27 px, the overlap NEIGHBOUR_OVERLAP_EM (0.25) 4.5 px.
NUMERAL = _box_around("1", 110, 120)
NUMERAL_END = 120


def _financials(start: float, **layout: object) -> Box:
    """The word after the numeral, its text starting at ``start`` px."""
    return _box_around("Financials", start, start + 90, **layout)


# Name -> (the slide's boxes, in the order it paints them; its reference; the
# words both checks report missing).
ACROSS_CASES: dict[str, tuple[tuple[Box, ...], str, list[str]]] = {
    # The two patterns of the Task 15 matrix, on the export's own boxes.
    "an inline-block numeral and its word (long-off 02)": (NUMERAL_ROWS, NUMERAL_REFERENCE, []),
    "chips and the commas after them (dense-tpl18 03)": (CHIP_LINES, CHIP_REFERENCE, []),
    "the review's probe, its chips written": (_probe(PROBE_PAINT_ORDER), PROBE_REFERENCE, []),
    # REAL LOSS: the review's probe with its chips lost. Each chip's letters
    # end and start the boxes either side of where it was, which are no
    # neighbours: the chip's room lies between them.
    "the review's probe, its chips lost, in the review's order": (
        _probe(PROBE_REVIEW_ORDER),
        PROBE_REFERENCE,
        ["AI", "ML", "KPI"],
    ),
    "the review's probe, its chips lost, in the order the slide paints": (
        _probe(PROBE_LOST_IN_PAINT_ORDER),
        PROBE_REFERENCE,
        ["AI", "ML", "KPI"],
    ),
    # A chip between two pieces of one word: a chain of three neighbours.
    "a chip inside a word": (
        (
            _box_around("(", 100, 106, size=20, h=26),
            _box_around(")", 143, 149, size=20, h=26),
            _box_around("AI", 115, 134, size=16),
        ),
        "(AI)",
        [],
    ),
    "a chip inside a word, lost": (
        (_box_around("(", 100, 106, size=20, h=26), _box_around(")", 143, 149, size=20, h=26)),
        "(AI)",
        ["(AI)"],
    ),
    # Every piece must be written, and as its own item's end.
    "the word after the numeral lost": (
        (
            Box("— Revenue up 9% to $1.80B with a 14.0% EBITDA margin", 138, 156, 520.3, 21, 18),
            Box("1", 110, 156, 14.6165625, 21, 18),
        ),
        "1Financials",
        ["1Financials"],
    ),
    "the numeral lost": (NUMERAL_ROWS[:1], "1Financials", ["1Financials"]),
    "the comma after the chip lost": (
        tuple(box for box in CHIP_LINES if box.text != ","),
        CHIP_REFERENCE,
        ["Iceberg,"],
    ),
    "the pieces inside other text": (
        (
            _box_around("a total of 1 shown", 110, 260),
            _box_around("the Financials team", 269, 420),
        ),
        "1Financials",
        ["1Financials"],
    ),
    # The edge: from NEIGHBOUR_OVERLAP_EM before the tail's text ends to
    # NEIGHBOUR_GAP_EM after, each a px inside or outside it.
    "an atomic edge apart": ((_financials(NUMERAL_END + 27 - 1), NUMERAL), "1Financials", []),
    "past an atomic edge": (
        (_financials(NUMERAL_END + 27 + 1), NUMERAL),
        "1Financials",
        ["1Financials"],
    ),
    "overlapping within the tolerance": (
        (_financials(NUMERAL_END - 4.5 + 1), NUMERAL),
        "1Financials",
        [],
    ),
    "overlapping past the tolerance": (
        (_financials(NUMERAL_END - 4.5 - 1), NUMERAL),
        "1Financials",
        ["1Financials"],
    ),
    # The em is the larger of the two items' sizes: a 16 px chip before 20 px text.
    "an edge of the larger size": (
        (_box_around("1", 110, 119, size=16), _box_around("Financials", 147, 237, size=20)),
        "1Financials",
        [],
    ),
    "past an edge of the larger size": (
        (_box_around("1", 110, 119, size=16), _box_around("Financials", 150, 240, size=20)),
        "1Financials",
        ["1Financials"],
    ),
    # A superscript run is no size of its item's: the deck writes it larger
    # than the browser draws it. The tail's text is 10 px; its superscript is
    # 14 px in the browser, so its em is 10 px and the head 16 px on is past it.
    "a superscript run's size is not its item's": (
        (
            _box_around("Revenue", 110, 160, size=10, h=12, script=("1", 14)),
            _box_around("Financials", 176, 226, size=10, h=12),
        ),
        "Revenue1Financials",
        ["Revenue1Financials"],
    ),
    # One line: overlapping by more than half the shorter's height (21 px).
    "sharing more than half a line": (
        (_financials(138, y=100 + 10.5 - 1), NUMERAL),
        "1Financials",
        [],
    ),
    "sharing less than half a line": (
        (_financials(138, y=100 + 10.5 + 1), NUMERAL),
        "1Financials",
        ["1Financials"],
    ),
    "on the next line": ((_financials(138, y=161), NUMERAL), "1Financials", ["1Financials"]),
    "the head before the tail": ((_financials(10), NUMERAL), "1Financials", ["1Financials"]),
    # Only unturned one-line items: a turned item's box is not where its text
    # runs, and a wrapped one's ends are not its box's.
    "a wrapped tail": (
        (_financials(138), Box("0\n1", 110, 100, 14.6165625, 42, 18)),
        "1Financials",
        ["1Financials"],
    ),
    "a turned tail": (
        (_financials(138), _box_around("1", 110, 120, rotate=90)),
        "1Financials",
        ["1Financials"],
    ),
    "a turned head": (
        (_financials(138, rotate=270), NUMERAL),
        "1Financials",
        ["1Financials"],
    ),
    # Right to left, the tail's text ends at its left and the head's starts at its right.
    "right to left": (
        (
            _box_around("שלום", 1060, 1140, align="right", rtl=True),
            _box_around("1", 1150, 1160, align="right", rtl=True),
        ),
        "1שלום",
        [],
    ),
    "right to left, read as left to right": (
        (
            _box_around("שלום", 1060, 1140, align="right"),
            _box_around("1", 1150, 1160, align="right"),
        ),
        "1שלום",
        ["1שלום"],
    ),
    # Two directions are two lines, whatever their places: a right-to-left
    # tail at the slide's left edge, where its mirrored ends meet a
    # left-to-right head's, 4 px on.
    "of two directions": (
        (_financials(14), _box_around("1", 0, 10, rtl=True)),
        "1Financials",
        ["1Financials"],
    ),
    # Each tail runs on into its nearest head, and each head follows its
    # nearest tail: a tall box shares a line with three boxes, one above the
    # other, no two of which share one. The nearest is painted between the others.
    "one tail, three heads: the nearest": (
        (
            _box_around("1", 110, 120, h=63),
            _financials(135),
            _box_around("Operations", 125, 215, y=121),
            _box_around("Customers", 130, 210, y=142),
        ),
        "1Operations",
        [],
    ),
    "three tails, one head: the nearest": (
        (
            _financials(130, h=63),
            _box_around("2", 100, 110),
            _box_around("1", 115, 125, y=121),
            _box_around("3", 105, 115, y=142),
        ),
        "1Financials",
        [],
    ),
    # Two boxes in one place, each within the overlap of the other: one chain
    # of the two, the nearer join first, never a loop (which no chain starts).
    "two narrow boxes in one place": (
        (_box_around("a", 100, 102), _box_around("b", 100, 102)),
        "ab",
        [],
    ),
    # A long line's slack is no edge: the tail's box runs 52 px past its text,
    # over the 60 px a lost chip left.
    "a long line's slack over a lost chip": (
        (
            _box_around("The platform joins every source of Customer Data", 88, 888, size=20, h=26),
            _box_around("Insights for every team", 948, 1180, size=20, h=26),
        ),
        "Customer Data AI Insights for every team",
        ["AI"],
    ),
}
# A centred or right-aligned block's box spans its content box, widened by its
# slack on both sides or on the left: the text's end is the content box's.
for _align in ("center", "right"):
    _tail = _box_around("1", 110, 140, align=_align)
    ACROSS_CASES[f"a {_align} tail an atomic edge apart"] = (
        (_financials(140 + 27 - 1), _tail),
        "1Financials",
        [],
    )
    ACROSS_CASES[f"a {_align} tail past an atomic edge"] = (
        (_financials(140 + 27 + 1), _tail),
        "1Financials",
        ["1Financials"],
    )
    ACROSS_CASES[f"a {_align} head an atomic edge apart"] = (
        (_financials(NUMERAL_END + 27 - 1, align=_align), NUMERAL),
        "1Financials",
        [],
    )
    ACROSS_CASES[f"a {_align} head past an atomic edge"] = (
        (_financials(NUMERAL_END + 27 + 1, align=_align), NUMERAL),
        "1Financials",
        ["1Financials"],
    )

# A slide realm that lies about the text a reader of it sees: innerText
# returns a decoy, and both querySelectorAll copies find nothing, so a reference
# read through the page's own accessors would hold the decoy and the SVG's
# label. It publishes on document.title what it replaced and what a reader
# then sees. The twins are compared whole, the label's picture included, so
# they are set on the deck's fonts pinned (pinned_font_css): Google Fonts now
# and then serves another DM Sans file for the deck's @import, whose glyphs
# the captured picture would draw a few anti-aliased pixels apart.
HOSTILE_DECOY = "Forgedword decoy"
# The corpus deck's --paper, the ground its .slide paints.
PAPER = "F9F7F4"
HOSTILE_SLIDE = (
    f'<div class="slide">{LEAD}'
    '<svg width="200" height="60"><text x="10" y="40" font-size="20">Svgword</text></svg>'
    "<script>{script}</script></div>"
)
HOSTILE_SCRIPT = """(function () {
  var report = { replaced: {}, sees: {} };
  function replace(name, proto, property, descriptor) {
    try {
      Object.defineProperty(proto, property, Object.assign({ configurable: true }, descriptor));
      report.replaced[name] = true;
    } catch (error) {
      report.replaced[name] = 'refused: ' + error.message;
    }
  }
  var decoyBody = document.createElement('div');
  decoyBody.textContent = 'Forgedbody';
  replace('HTMLElement.innerText', HTMLElement.prototype, 'innerText',
          { get: function () { return '%(decoy)s'; } });
  replace('Document.querySelectorAll', Document.prototype, 'querySelectorAll',
          { value: function () { return { length: 0 }; } });
  replace('Element.querySelectorAll', Element.prototype, 'querySelectorAll',
          { value: function () { return { length: 0 }; } });
  if (%(body)s) {
    replace('Document.body', Document.prototype, 'body',
            { get: function () { return decoyBody; } });
  }
  report.sees.innerText = document.documentElement.innerText;
  report.sees.svgCount = document.querySelectorAll('svg').length;
  report.sees.bodyIsDecoy = document.body === decoyBody;
  document.title = JSON.stringify(report);
})();"""
# The benign twin runs a script too, so both pages hold the same elements.
BENIGN_SCRIPT = "(function () { document.title = 'benign'; })();"


def _pinned_case_document(body: str) -> str:
    """A case document on the deck's fonts pinned: two loads of it render alike."""
    return slide_document(body, css=pinned_font_css(), slide_id="snapshot-1")


HOSTILE_TEXT_DOCUMENT = _pinned_case_document(
    HOSTILE_SLIDE.format(script=HOSTILE_SCRIPT % {"decoy": HOSTILE_DECOY, "body": "false"})
)
HOSTILE_BODY_DOCUMENT = _pinned_case_document(
    HOSTILE_SLIDE.format(script=HOSTILE_SCRIPT % {"decoy": HOSTILE_DECOY, "body": "true"})
)
BENIGN_DOCUMENT = _pinned_case_document(HOSTILE_SLIDE.format(script=BENIGN_SCRIPT))
HOSTILE_REPLACED = (
    "HTMLElement.innerText",
    "Document.querySelectorAll",
    "Element.querySelectorAll",
)

# A slide script that logs lines shaped like the sidecar's own summary and
# text-loss lines; render_slide.cjs forwards them as "Browser console: …".
FORGED_HIDDEN_TEXT = "Forgedword"
FORGING_SCRIPT = (
    "<script>(function () {"
    " var forged = { hiddenText: '" + FORGED_HIDDEN_TEXT + "', target: 'pptx', text: 0 };"
    " console.log('[html2pptx] slide summary ' + JSON.stringify(forged));"
    " console.error('[html2pptx] slide summary ' + JSON.stringify(forged));"
    " console.error('[html2pptx] text missing: [\"" + FORGED_HIDDEN_TEXT + "\"]');"
    "})();</script>"
)

# The harness deck: a slide with hidden text whose script forges summary lines,
# an empty document (the sidecar fails it: "slide.html is empty"), then corpus
# slide 03. Its reference adds a fourth slide the deck never had.
HARNESS_FORGED = "01-forged"
HARNESS_FAILED = "02-failed"
HARNESS_SCREEN_READER = "03-screen-reader"
HARNESS_BEYOND = "04-beyond"
HARNESS_FORGED_DOCUMENT = _case_document(
    '<div class="slide"><p style="font-size: 20px;">Revenue '
    f'<span style="opacity: 0;">secretword</span> grew</p>{FORGING_SCRIPT}</div>'
)
HARNESS_FORGED_HIDDEN = "secretword"
# The failed slide's words all appear on corpus slide 03, which follows it, so
# pairing references with slides by position alone hides its loss.
HARNESS_FAILED_REFERENCE = "Operating margin rose"
HARNESS_BEYOND_REFERENCE = "Delta Echo Kilo"

# The harness run: corpus slide 03, a slide hiding text five ways, and the joined script.
HARNESS_RUN_HIDDEN_BODY = (
    '<div class="slide">'
    '<h1 id="title" style="width: 420px; white-space: nowrap; overflow: hidden; '
    f'text-overflow: ellipsis; font-size: 40px; margin: 0;">{ELLIPSIS_TITLE}</h1>'
    '<p style="font-size: 20px;">Revenue <span style="opacity: 0;">secretword</span> grew</p>'
    '<p style="font-size: 20px;">Total <span style="opacity: 0;">Mar<b>gin</b></span> up</p>'
    '<div style="position: absolute; left: 80px; top: 740px; font-size: 20px;">'
    "Offstage Quokka</div></div>"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text_check(function: str, *arguments: object) -> object:
    """``textCheck.<function>(...arguments)`` from ``text_check.cjs``, in Node, as JSON."""
    script = (
        f"const textCheck = require({json.dumps(str(TEXT_CHECK_MODULE))});"
        f"process.stdout.write(JSON.stringify(textCheck.{function}(...{json.dumps(list(arguments))})));"
    )
    return node_json(script)


def _missing_words(reference: str, emitted: str, hidden: str) -> object:
    return _text_check("missingWords", reference, emitted, hidden)


def _text_loss_line(reference: str, items: list[dict], hidden: str) -> object:
    return _text_check("textLossLine", reference, items, hidden)


def _paragraphs(*lines: tuple[str, ...]) -> list[dict]:
    """One paragraph whose lines hold these run texts, as snapshot_text.mjs lays text out."""
    return [{"lines": [{"runs": [{"text": text} for text in line]} for line in lines]}]


def _text_item(*lines: tuple[str, ...]) -> dict:
    return {"kind": "text", "paragraphs": _paragraphs(*lines)}


def _table_item(*cells: list[dict] | None) -> dict:
    """A native table item whose cells hold these paragraphs (None: overlay text, []: none)."""
    return {"kind": "table", "cells": [{"paragraphs": cell} for cell in cells]}


def _model_item(box: Box) -> dict:
    """``box`` as the sidecar's slide model holds it: a text item (snapshot_text.mjs TextBlock)."""
    lines = [
        {"runs": [{"text": line, "sizePx": box.size, "baseline": None}]}
        for line in box.text.split("\n")
    ]
    if box.script:
        text, size = box.script
        lines[-1]["runs"].append({"text": text, "sizePx": size, "baseline": "super"})
    return {
        "kind": "text",
        "x": box.x,
        "y": box.y,
        "w": box.w,
        "h": box.h,
        "rotate": box.rotate or None,
        "wrap": len(lines) > 1,
        "align": box.align,
        "rtl": box.rtl,
        "paragraphs": [{"sizePx": box.size, "lines": lines}],
    }


def _sidecar_missing(boxes: tuple[Box, ...], reference: str) -> list[str]:
    """The words the sidecar's check (textLossLine) reports missing from a slide of ``boxes``."""
    line = _text_loss_line(reference, [_model_item(box) for box in boxes], "")
    return [] if line is None else _missing_from_line(line)


def _deck_of_boxes(slides: list[tuple[Box, ...]]) -> bytes:
    """A .pptx of these slides' boxes, each a text box as the export writes it (python-pptx).

    A one-line box does not wrap (``wrap="none"``), a box of more lines does;
    each line is a paragraph aligned and run as its box is; a superscript run
    is written as emit_typography.cjs writes it, larger than the browser draws
    it, at baseline 30000.
    """
    from pptx import Presentation
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Emu, Pt

    alignments = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}
    superscript_factor = _emit_typography_constant("SUPERSCRIPT_SIZE_FACTOR")
    presentation = Presentation()
    presentation.slide_width = Emu(1280 * EMU_PER_PX)
    presentation.slide_height = Emu(720 * EMU_PER_PX)
    blank = presentation.slide_layouts[6]
    for boxes in slides:
        slide = presentation.slides.add_slide(blank)
        for box in boxes:
            geometry = (Emu(round(value * EMU_PER_PX)) for value in (box.x, box.y, box.w, box.h))
            shape = slide.shapes.add_textbox(*geometry)
            shape.rotation = box.rotate
            frame = shape.text_frame
            lines = box.text.split("\n")
            frame.word_wrap = len(lines) > 1
            for index, line in enumerate(lines):
                paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
                paragraph.alignment = alignments[box.align]
                if box.rtl:
                    paragraph._p.get_or_add_pPr().set("rtl", "1")
                run = paragraph.add_run()
                run.text = line
                run.font.size = Pt(box.size * PT_PER_PX)
            if box.script:
                text, size = box.script
                run = paragraph.add_run()
                run.text = text
                run.font.size = Pt(size / superscript_factor * PT_PER_PX)
                run.font._rPr.set("baseline", "30000")
    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()


def _harness_missing(boxes: tuple[Box, ...], reference: str) -> list[str]:
    """The words the harness's check (check_text_loss) reports missing from a slide of ``boxes``."""
    return reference_text_loss(_deck_of_boxes([boxes]), [reference])[0]


def _boxes_of_slide(pptx: bytes) -> tuple[Box, ...]:
    """The text boxes of a written deck's first slide, as Boxes, in the order it paints them.

    Each box's size is its largest run that is no superscript or subscript;
    a justified box is aligned as the export writes one, from its start.
    """
    boxes = []
    for shape in slide_shapes(pptx):
        if shape.kind != "text" or not shape.text:
            continue
        sizes = [
            run.size_pt / PT_PER_PX
            for para in shape.paras
            for run in para.runs
            if run.size_pt is not None and run.baseline is None
        ]
        first = shape.paras[0]
        align = first.align if first.align in ("center", "right") else "left"
        boxes.append(
            Box(
                shape.text,
                shape.x,
                shape.y,
                shape.w,
                shape.h,
                max(sizes, default=0),
                align,
                first.rtl,
                shape.rotation,
            )
        )
    return tuple(boxes)


def _without_text_boxes(pptx: bytes, texts: tuple[str, ...]) -> bytes:
    """The deck with its first slide's text boxes that hold one of ``texts`` taken out."""
    from pptx import Presentation

    presentation = Presentation(io.BytesIO(pptx))
    slide = presentation.slides[0]
    taken = [
        shape
        for shape in slide.shapes
        if shape.has_text_frame and shape.text_frame.text.strip() in texts
    ]
    assert sorted(shape.text_frame.text.strip() for shape in taken) == sorted(texts), (
        f"fixture drift: the deck's text boxes for {texts} are {[s.text_frame.text for s in taken]}"
    )
    for shape in taken:
        shape._element.getparent().remove(shape._element)
    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()


def _emit_typography_constant(name: str) -> float:
    """The value of ``const NAME = <number>;`` in the sidecar's ``emit_typography.cjs``."""
    source = (Path(pptx_from_html_huashu.SIDECAR_DIR) / "emit_typography.cjs").read_text()
    found = re.findall(rf"^const {re.escape(name)} = (-?[\d.]+);", source, re.MULTILINE)
    assert len(found) == 1, (
        f"emit_typography.cjs defines `const {name} = <number>;` {len(found)} times"
    )
    return float(found[0])


# The neighbour rule's constants, by their names in text_check.cjs and run.py.
NEIGHBOUR_CONSTANTS = (
    "SLACK_FRACTION",
    "SLACK_PX",
    "SAME_LINE_OVERLAP",
    "NEIGHBOUR_GAP_EM",
    "NEIGHBOUR_OVERLAP_EM",
    "ACROSS_ITEM_LIMIT",
)


def _text_check_constants() -> dict[str, float]:
    """The neighbour rule's constants as text_check.cjs exports them."""
    script = (
        f"const textCheck = require({json.dumps(str(TEXT_CHECK_MODULE))});"
        f"process.stdout.write(JSON.stringify(Object.fromEntries("
        f"{json.dumps(list(NEIGHBOUR_CONSTANTS))}.map((name) => [name, textCheck[name]]))));"
    )
    return node_json(script)


def _missing_from_line(line: object) -> list[str]:
    assert isinstance(line, str) and line.startswith(TEXT_MISSING_PREFIX), (
        f"textLossLine returned {line!r}, not a line starting {TEXT_MISSING_PREFIX!r}"
    )
    return json.loads(line.removeprefix(TEXT_MISSING_PREFIX))


def _only_summary(logged: LoggedExport) -> dict:
    """The one slide summary a one-slide export logs."""
    assert logged.failures == [], f"the export rejected the slide: {logged.failures}"
    summaries = slide_summaries(logged.stderr)
    assert len(summaries) == 1, (
        f"a one-slide export logged {len(summaries)} '[html2pptx] slide summary' lines, "
        f"expected 1; sidecar stderr:\n{logged.stderr[-3000:]}"
    )
    return summaries[0]


def _deck_of_texts(slides: list[list[str]]) -> bytes:
    """A .pptx with one text box per string, slide by slide (python-pptx, no browser)."""
    from pptx import Presentation
    from pptx.util import Inches

    presentation = Presentation()
    blank = presentation.slide_layouts[6]
    for texts in slides:
        slide = presentation.slides.add_slide(blank)
        for position, text in enumerate(texts):
            box = slide.shapes.add_textbox(Inches(1), Inches(1 + position), Inches(8), Inches(1))
            box.text_frame.text = text
    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()


def _word_spans(text: str) -> list[tuple[str, int, int]]:
    """Each whitespace-separated word of ``text`` with its start and end offsets."""
    spans = []
    position = 0
    for word in text.split():
        start = text.index(word, position)
        spans.append((word, start, start + len(word)))
        position = start + len(word)
    return spans


@functools.cache
def _ellipsis_words(document: str) -> tuple[list[str], list[str], list[str]]:
    """(wholly shown, cut, wholly hidden) words of the ellipsis title, from the browser's cut."""
    cut = browser_ellipsis(document, ELLIPSIS_SELECTOR)
    assert cut.text == ELLIPSIS_TITLE and cut.text.startswith(cut.visible), (
        f"fixture drift: the browser reads {cut.text!r} and shows {cut.visible!r}"
    )
    shown_length = len(cut.visible)
    spans = _word_spans(cut.text)
    shown = [word for word, _, end in spans if end <= shown_length]
    cut_words = [word for word, start, end in spans if start < shown_length < end]
    hidden = [word for word, start, _ in spans if start >= shown_length]
    assert shown and len(cut_words) == 1 and hidden, (
        f"fixture drift: the ellipsis must cut inside one word with words on each side; "
        f"the browser shows {cut.visible!r} of {cut.text!r}"
    )
    return shown, cut_words, hidden


# ---------------------------------------------------------------------------
# text_check.cjs in Node: missingWords
# ---------------------------------------------------------------------------


@requires_node
class TestMissingWords:
    """``missingWords(reference, emitted, hidden) -> string[]``."""

    def test_words_the_emitted_text_runs_together_are_not_missing(self) -> None:
        assert _missing_words("Revenue up 10.7%", "Revenueup10.7%", "") == []

    def test_a_word_only_partly_emitted_is_missing(self) -> None:
        assert _missing_words("profit1", "profit", "") == ["profit1"]

    def test_hidden_words_are_not_missing(self) -> None:
        assert _missing_words("Revenue secretword grew", "Revenue grew", "") == ["secretword"]
        assert _missing_words("Revenue secretword grew", "Revenue grew", "secretword") == []

    def test_hidden_words_excuse_no_other_word(self) -> None:
        assert _missing_words(
            "Revenue secretword grew Liquidity", "Revenue grew", "secretword"
        ) == ["Liquidity"]

    def test_missing_words_are_named_as_the_reference_spells_them_in_its_order(self) -> None:
        """Matching ignores case; what is reported is the reference's own words."""
        assert _missing_words("Cash Liquidity reserves Solvency", "cash RESERVES", "") == [
            "Liquidity",
            "Solvency",
        ]

    def test_a_word_joiner_after_a_superscript_is_no_difference(self) -> None:
        """A superscript "1": U+00B9 in the reference, "1" + U+2060 emitted."""
        assert _missing_words("Revenue grew¹", f"Revenue grew1{WORD_JOINER}", "") == []

    def test_a_word_joiner_inside_unspaced_text_is_no_difference(self) -> None:
        """CJK has no spaces, so the joiner after a line-ending script falls inside a word."""
        assert _missing_words("收入增长1同比上升", f"收入增长1{WORD_JOINER}同比上升", "") == []

    @pytest.mark.parametrize("code_point", tuple(DEFAULT_IGNORABLE_CODE_POINTS))
    def test_default_ignorable_code_points_are_no_difference(self, code_point: str) -> None:
        character = DEFAULT_IGNORABLE_CODE_POINTS[code_point]
        assert _missing_words("Revenue grew", f"Reve{character}nue grew", "") == [], (
            f"{code_point} inside an emitted word"
        )
        assert _missing_words(f"Reve{character}nue grew", "Revenue grew", "") == [], (
            f"{code_point} inside a reference word"
        )


# ---------------------------------------------------------------------------
# text_check.cjs in Node: textLossLine over hand-built slide models
# ---------------------------------------------------------------------------


@requires_node
class TestTextLossLine:
    """``textLossLine(reference, items, hidden) -> string | null``: what render_slide.cjs logs."""

    def test_a_model_that_omits_a_word_names_it(self) -> None:
        line = _text_loss_line(
            "Cash Liquidity ratio", [_text_item(("Cash",)), _text_item(("ratio",))], ""
        )
        assert _missing_from_line(line) == ["Liquidity"]

    def test_a_complete_model_logs_nothing(self) -> None:
        items = [_text_item(("Cash ", "Liquidity")), _text_item(("ratio",))]
        assert _text_loss_line("Cash Liquidity ratio", items, "") is None

    def test_every_line_and_paragraph_of_a_text_item_is_read(self) -> None:
        item = {
            "kind": "text",
            "paragraphs": [*_paragraphs(("Cash",), ("Liquidity",)), *_paragraphs(("ratio",))],
        }
        assert _text_loss_line("Cash Liquidity ratio", [item], "") is None

    def test_native_table_cells_are_emitted_text(self) -> None:
        """A cell's paragraphs are its text; an overlay cell (null) or empty one ([]) has none."""
        table = _table_item(_paragraphs(("Liquidity",)), None, [], _paragraphs(("ratio",)))
        assert _text_loss_line("Cash Liquidity ratio", [_text_item(("Cash",)), table], "") is None
        short_table = _table_item(_paragraphs(("ratio",)), None, [])
        line = _text_loss_line("Cash Liquidity ratio", [_text_item(("Cash",)), short_table], "")
        assert _missing_from_line(line) == ["Liquidity"]

    def test_list_markers_are_emitted_text(self) -> None:
        """An outside marker is a text item of its own; an inside one is a token of its line."""
        items = [
            _text_item(("1.",)),
            _text_item(("Liquidity",)),
            _text_item(("• ", "Reserves")),
        ]
        assert _text_loss_line("1. Liquidity • Reserves", items, "") is None

    def test_hidden_words_are_not_named(self) -> None:
        items = [_text_item(("Revenue",)), _text_item(("grew",))]
        assert _missing_from_line(_text_loss_line("Revenue secretword grew", items, "")) == [
            "secretword"
        ]
        assert _text_loss_line("Revenue secretword grew", items, "secretword") is None

    def test_items_that_hold_no_text_are_ignored(self) -> None:
        items = [
            {"kind": "shape", "x": 0, "y": 0, "w": 10, "h": 10},
            {"kind": "line", "x1": 0, "y1": 0, "x2": 10, "y2": 0},
            {"kind": "image", "x": 0, "y": 0, "w": 10, "h": 10, "src": None, "captureId": "c1"},
            _text_item(("Liquidity",)),
        ]
        assert _text_loss_line("Liquidity", items, "") is None
        assert _missing_from_line(_text_loss_line("Liquidity Solvency", items, "")) == ["Solvency"]

    def test_items_without_a_box_are_no_neighbours(self) -> None:
        """GUARD: a text item with no box (x, y, w, h) has no place on the slide to be beside."""
        items = [_text_item(("Financials — Revenue up 9%",)), _text_item(("1",))]
        assert _missing_from_line(_text_loss_line("1Financials", items, "")) == ["1Financials"]


@requires_node
class TestWordsAcrossNeighbours:
    """``textLossLine`` finds a word written across neighbours, and only there (Task 15 H2).

    Each case of ACROSS_CASES is a slide of boxes, given as a slide model's
    text items; TestHarnessWordsAcrossNeighbours reads the same cases as decks.
    """

    @pytest.mark.parametrize("case", tuple(ACROSS_CASES))
    def test_a_word_is_written_across_neighbours_only(self, case: str) -> None:
        boxes, reference, missing = ACROSS_CASES[case]
        assert _sidecar_missing(boxes, reference) == missing

    def test_the_slack_and_the_line_are_the_snapshots(self) -> None:
        """A box's slack and what one line is are snapshot_text.mjs's own, which lays them out."""
        constants = _text_check_constants()
        for name in ("SLACK_FRACTION", "SLACK_PX", "SAME_LINE_OVERLAP"):
            assert constants[name] == _snapshot_text_constant(name), name

    def test_the_neighbour_search_reads_at_most_its_limit_of_items(self) -> None:
        """BOUND: every item the rule reads is compared with every other, so it reads a bounded
        number, ACROSS_ITEM_LIMIT, the first the slide paints: no slide the matrix or the
        corpora hold paints more than 51 text items.

        Below the numeral and its word, fillers each a line of their own, none a
        neighbour of anything: with the pair the last two items read, the word
        is written; one filler more, and the word's head is past the limit.
        """
        limit = int(_text_check_constants()["ACROSS_ITEM_LIMIT"])

        def slide(fillers: int) -> list[dict]:
            spacing = 600 / fillers
            filled = [
                _model_item(_box_around("f", 10, 15, y=110 + index * spacing, h=spacing / 2))
                for index in range(fillers)
            ]
            return [*filled, _model_item(NUMERAL), _model_item(_financials(130))]

        assert _text_loss_line("1Financials", slide(limit - 2), "") is None
        assert _missing_from_line(_text_loss_line("1Financials", slide(limit - 1), "")) == [
            "1Financials"
        ]

    def test_a_slide_of_stacked_neighbours_is_checked_in_time(self) -> None:
        """BOUND: ACROSS_ITEM_LIMIT items in one place, each a neighbour of every other, and a
        reference of 2,000 words none of them holds, are checked inside the Node call's timeout."""
        limit = int(_text_check_constants()["ACROSS_ITEM_LIMIT"])
        items = [_model_item(_box_around("xy", 100, 110, size=100, h=100)) for _ in range(limit)]
        words = [f"w{index}" for index in range(2000)]
        assert _missing_from_line(_text_loss_line(" ".join(words), items, "")) == words

    def test_a_page_long_word_written_across_neighbours_is_found(self) -> None:
        """A word of any length is looked for: the chains' text is no longer than the slide's.

        20,000 x's, written as two neighbours of 10,000 each that the slide does
        not paint one after the other.
        """
        items = [
            _model_item(_box_around("x" * 10000, 100, 600)),
            _model_item(_box_around("filler", 100, 160, y=300)),
            _model_item(_box_around("x" * 10000, 609, 1100)),
        ]
        assert _text_loss_line("x" * 20000, items, "") is None


# ---------------------------------------------------------------------------
# The slide summary line
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def counts_export() -> Iterator[LoggedExport]:
    """COUNTS_DOCUMENT exported once for PowerPoint (the default target)."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        yield export_logged([COUNTS_DOCUMENT], monkeypatch=monkeypatch)


@pytest.fixture(scope="module")
def counts_gslides_export() -> Iterator[LoggedExport]:
    """COUNTS_DOCUMENT exported once for Google Slides."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        yield export_logged([COUNTS_DOCUMENT], monkeypatch=monkeypatch, target="gslides")


@pytest.mark.slow
@requires_huashu_sidecar
class TestSlideSummary:
    """One ``[html2pptx] slide summary <json>`` line per slide, every key named."""

    def test_the_summary_keeps_every_existing_key(self, counts_export: LoggedExport) -> None:
        summary = _only_summary(counts_export)
        missing = [key for key in EXISTING_SUMMARY_KEYS if key not in summary]
        assert not missing, f"the summary dropped {missing}: {summary}"
        assert set(summary["animations"]) >= {"finished", "cancelled", "unfinished"}, summary
        assert summary["pseudoElements"] == {"read": 1, "walked": 1}, (
            "the slide's one list item has one ::marker, read and drawn"
        )

    def test_the_summary_adds_the_counts_and_the_checks(self, counts_export: LoggedExport) -> None:
        summary = _only_summary(counts_export)
        missing = [key for key in ADDED_SUMMARY_KEYS if key not in summary]
        assert not missing, f"the summary lacks {missing}: {summary}"
        assert REPLACED_SUMMARY_KEY not in summary, (
            "the pseudo-element count is the existing pseudoElements, not a `pseudo` key"
        )

    def test_the_counts_are_the_items_the_slide_was_written_with(
        self, counts_export: LoggedExport
    ) -> None:
        """Each count is what COUNTS_BODY is built from, and what the emitted slide holds."""
        shapes = slide_shapes(counts_export.pptx, 0)
        for _, _, shape_kind, count in COUNTS:
            emitted = sum(1 for shape in shapes if shape.kind == shape_kind)
            assert emitted == count, (
                f"fixture drift: the emitted slide holds {emitted} {shape_kind} shapes, "
                f"COUNTS_BODY is built with {count}"
            )
        summary = _only_summary(counts_export)
        for key, item_kind, _, count in COUNTS:
            assert summary[key] == count, f"summary {key} = {summary[key]!r}, expected {count}"
            assert summary["kinds"].get(item_kind) == count, (
                f"summary kinds[{item_kind!r}] = {summary['kinds'].get(item_kind)!r}, "
                f"expected {count}"
            )
        assert summary["captures"] == 1 and summary["captureFailures"] == 0, summary
        assert summary["skippedPictures"] == 0, summary

    def test_the_reference_is_read_after_the_captures(self, counts_export: LoggedExport) -> None:
        """Hiding SVG and canvas for the reference read changes no picture.

        The read runs after every capture (brief), so the SVG's picture still
        shows its fill, not the transparent page a hidden SVG leaves.
        """
        _only_summary(counts_export)
        shapes = slide_shapes(counts_export.pptx, 0)
        pictures = [shape for shape in shapes if shape.kind == "picture"]
        assert len(pictures) == 1 and pictures[0].image, pictures
        image = Image.open(io.BytesIO(pictures[0].image)).convert("RGBA")
        centre = image.getpixel((image.width // 2, image.height // 2))
        assert centre == COUNTS_SVG_FILL, (
            f"the SVG's picture shows {centre} at its centre, not its fill {COUNTS_SVG_FILL}"
        )

    def test_the_capture_time_is_recorded(self, counts_export: LoggedExport) -> None:
        summary = _only_summary(counts_export)
        capture_ms = summary["captureMs"]
        assert isinstance(capture_ms, (int, float)) and not isinstance(capture_ms, bool), summary
        assert capture_ms > 0, f"one capture was taken, yet captureMs is {capture_ms}"

    def test_a_valid_slide_drops_nothing_of_its_model(self, counts_export: LoggedExport) -> None:
        """Every item and capture the snapshot writes for a real slide passes the model check."""
        assert _only_summary(counts_export)["modelDrops"] == 0

    def test_a_slide_that_hides_nothing_has_no_hidden_text(
        self, counts_export: LoggedExport
    ) -> None:
        assert _only_summary(counts_export)["hiddenText"] == ""

    def test_the_summary_records_the_powerpoint_target(self, counts_export: LoggedExport) -> None:
        assert _only_summary(counts_export)["target"] == "pptx"

    def test_the_summary_records_the_google_slides_target(
        self, counts_gslides_export: LoggedExport
    ) -> None:
        assert _only_summary(counts_gslides_export)["target"] == "gslides"

    def test_fixture_03_logs_one_summary_with_its_pictures_and_no_text_loss(self) -> None:
        """Corpus slide 03 alone: its chart and icons captured, nothing lost."""
        with pytest.MonkeyPatch.context() as monkeypatch:
            logged = export_logged([corpus_document("03")], monkeypatch=monkeypatch)
        summary = _only_summary(logged)
        assert summary["pictures"] >= 2, summary
        assert summary["captureFailures"] == 0, summary
        assert text_missing_reports(logged.stderr) == [], (
            f"fixture 03 loses no visible text; stderr:\n{logged.stderr[-3000:]}"
        )


@pytest.mark.slow
@requires_huashu_sidecar
class TestDeterminism:
    def test_repeated_exports_are_identical_although_their_capture_times_differ(
        self, counts_export: LoggedExport
    ) -> None:
        """``captureMs`` is a clock reading: it goes to stderr and never into the .pptx.

        COUNTS_DOCUMENT (one capture, system fonts only) is exported until two
        exports report different capture times, at most
        ``MAX_DETERMINISM_EXPORTS`` times; every deck must be byte-identical
        to the first, docProps timestamps masked (``structural_manifest``).
        """
        first = structural_manifest(counts_export.pptx)
        exports = [counts_export]
        with pytest.MonkeyPatch.context() as monkeypatch:
            while len(exports) < MAX_DETERMINISM_EXPORTS:
                logged = export_logged([COUNTS_DOCUMENT], monkeypatch=monkeypatch)
                exports.append(logged)
                assert structural_manifest(logged.pptx) == first, (
                    f"export {len(exports)} of the same slide differs from export 1"
                )
                times = [_only_summary(export)["captureMs"] for export in exports]
                if len(set(times)) > 1:
                    break
        assert len(set(times)) > 1, (
            f"{len(exports)} exports all reported captureMs {times[0]}; a wall time of "
            "real captures does not repeat, so it is not being measured"
        )


# ---------------------------------------------------------------------------
# hiddenText: the pinned cases, in one deck
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HiddenDeck:
    """HIDDEN_DECK exported once, its slides' harness references beside the .pptx."""

    logged: LoggedExport
    out_dir: Path  # truth/<name>.txt (render_truth.cjs) and export.pptx
    names: tuple[str, ...]  # one per slide, in slide order

    @property
    def pptx_path(self) -> Path:
        return self.out_dir / "export.pptx"

    def summaries(self) -> list[dict]:
        summaries = slide_summaries(self.logged.stderr)
        assert len(summaries) == len(self.names), (
            f"a {len(self.names)}-slide deck logged {len(summaries)} slide summary lines; "
            f"sidecar stderr:\n{self.logged.stderr[-3000:]}"
        )
        return summaries

    def summary(self, case: str) -> dict:
        return self.summaries()[HIDDEN_DECK.index(case)]

    def name(self, case: str) -> str:
        return self.names[HIDDEN_DECK.index(case)]


@pytest.fixture(scope="module")
def hidden_deck(tmp_path_factory: pytest.TempPathFactory) -> Iterator[HiddenDeck]:
    documents = [
        HIDDEN_CASES[case].document if case in HIDDEN_CASES else VISIBILITY_HIDDEN_DOCUMENT
        for case in HIDDEN_DECK
    ]
    with pytest.MonkeyPatch.context() as monkeypatch:
        logged = export_logged(documents, monkeypatch=monkeypatch)
    assert logged.failures == [], f"the export rejected a slide: {logged.failures}"
    out_dir = tmp_path_factory.mktemp("hidden-deck")
    documents_dir = out_dir / "documents"
    documents_dir.mkdir()
    names = tuple(f"{position:02d}-{case}" for position, case in enumerate(HIDDEN_DECK, start=1))
    paths = []
    for name, document in zip(names, documents):
        path = documents_dir / f"{name}.html"
        path.write_text(document, encoding="utf-8")
        paths.append(path)
    # The harness's own reference: one browser renders every document.
    fidelity_harness().render_truth(paths, out_dir)
    (out_dir / "export.pptx").write_bytes(logged.pptx)
    yield HiddenDeck(logged=logged, out_dir=out_dir, names=names)


@pytest.mark.slow
@requires_huashu_sidecar
class TestHiddenText:
    """The summary's ``hiddenText`` holds the words each case hides, and nothing it shows."""

    def test_the_deck_logs_one_summary_per_slide(self, hidden_deck: HiddenDeck) -> None:
        assert len(hidden_deck.summaries()) == len(HIDDEN_DECK)

    @pytest.mark.parametrize("case", tuple(HIDDEN_CASES))
    def test_the_summary_holds_the_hidden_words(self, hidden_deck: HiddenDeck, case: str) -> None:
        hidden_text = hidden_deck.summary(case)["hiddenText"]
        assert hidden_text.split() == list(HIDDEN_CASES[case].hidden_words), (
            f"{case}: hiddenText is {hidden_text!r}"
        )

    def test_visibility_hidden_text_is_not_hidden_text(self, hidden_deck: HiddenDeck) -> None:
        """``innerText`` leaves it out, so recording it could only mask a real loss."""
        hidden_text = hidden_deck.summary(VISIBILITY_HIDDEN)["hiddenText"]
        assert hidden_text == "", f"hiddenText is {hidden_text!r}"

    def test_no_slide_of_the_deck_logs_text_missing(self, hidden_deck: HiddenDeck) -> None:
        """The in-pipeline check excludes each slide's hidden words, and reads its table cells."""
        hidden_deck.summaries()
        assert text_missing_reports(hidden_deck.logged.stderr) == [], (
            f"sidecar stderr:\n{hidden_deck.logged.stderr[-3000:]}"
        )

    @pytest.mark.parametrize("case", tuple(HIDDEN_CASES))
    def test_the_harness_reports_none_of_them_missing(
        self, hidden_deck: HiddenDeck, case: str
    ) -> None:
        """``check_text_loss`` with each slide's ``hiddenText`` reports nothing for the case.

        Without it, the bare oracle reports the case's hidden words (those no
        visible text contains): the reference is innerText, which reads them.
        """
        harness = fidelity_harness()
        name = hidden_deck.name(case)
        bare = harness.check_text_loss(
            hidden_deck.pptx_path, list(hidden_deck.names), hidden_deck.out_dir
        ).get(name, [])
        assert bare and set(bare) <= set(HIDDEN_CASES[case].hidden_words), (
            f"fixture drift: without hidden text the oracle reports {bare} for {case}"
        )
        hidden_text = [summary["hiddenText"] for summary in hidden_deck.summaries()]
        missing = harness.check_text_loss(
            hidden_deck.pptx_path,
            list(hidden_deck.names),
            hidden_deck.out_dir,
            hidden_text=hidden_text,
        )
        assert name not in missing, f"{case}: the harness reports {missing[name]} missing"

    def test_visibility_hidden_text_is_not_in_the_reference(self, hidden_deck: HiddenDeck) -> None:
        """GUARD: the harness reference never held it."""
        reference = hidden_deck.out_dir / "truth" / f"{hidden_deck.name(VISIBILITY_HIDDEN)}.txt"
        text = reference.read_text(encoding="utf-8")
        assert not set(VISIBILITY_HIDDEN_WORDS) & set(text.split()), text


@pytest.fixture(scope="module")
def ellipsis_export() -> Iterator[LoggedExport]:
    with pytest.MonkeyPatch.context() as monkeypatch:
        yield export_logged([ELLIPSIS_DOCUMENT], monkeypatch=monkeypatch)


@pytest.mark.slow
@requires_huashu_sidecar
class TestEllipsis:
    """Characters a ``text-overflow: ellipsis`` hides are hidden text, not lost text."""

    def test_an_ellipsis_title_logs_no_text_missing(self, ellipsis_export: LoggedExport) -> None:
        _only_summary(ellipsis_export)
        assert text_missing_reports(ellipsis_export.stderr) == [], (
            f"sidecar stderr:\n{ellipsis_export.stderr[-3000:]}"
        )

    def test_its_hidden_tail_is_hidden_text(self, ellipsis_export: LoggedExport) -> None:
        """Every word the browser shows none of is in ``hiddenText``; no word it shows whole is."""
        shown, _, hidden = _ellipsis_words(ELLIPSIS_DOCUMENT)
        hidden_words = _only_summary(ellipsis_export)["hiddenText"].split()
        assert [word for word in hidden if word not in hidden_words] == [], (
            f"hiddenText {hidden_words} lacks words the ellipsis hides: {hidden}"
        )
        assert [word for word in shown if word in hidden_words] == [], (
            f"hiddenText {hidden_words} holds words the browser shows whole: {shown}"
        )

    def test_the_harness_reports_nothing_missing(self, ellipsis_export: LoggedExport) -> None:
        _, cut_words, hidden = _ellipsis_words(ELLIPSIS_DOCUMENT)
        reference = browser_text(ELLIPSIS_DOCUMENT)
        bare = reference_text_loss(ellipsis_export.pptx, [reference])[0]
        assert set(bare) == set(cut_words + hidden), (
            f"fixture drift: without hidden text the oracle reports {bare}"
        )
        summary = _only_summary(ellipsis_export)
        assert reference_text_loss(
            ellipsis_export.pptx, [reference], hidden_text=[summary["hiddenText"]]
        ) == [[]]


@pytest.mark.slow
@requires_huashu_sidecar
class TestTextLossIsLogged:
    """A slide that loses visible text says so on stderr, as the harness does."""

    @pytest.fixture(scope="class")
    def select_export(self) -> Iterator[LoggedExport]:
        with pytest.MonkeyPatch.context() as monkeypatch:
            yield export_logged([SELECT_DOCUMENT], monkeypatch=monkeypatch)

    def test_a_slide_that_loses_visible_text_names_it(self, select_export: LoggedExport) -> None:
        """On a slide with a capture: the reference is read once the picture is taken.

        The svg's label travels inside its picture, so it is no loss; the
        option's text is.
        """
        summary = _only_summary(select_export)
        assert summary["captures"] == 1 and summary["pictures"] == 1, (
            f"fixture drift: the svg must be captured as the slide's one picture: {summary}"
        )
        assert text_missing_reports(select_export.stderr) == [[SELECT_WORD]], (
            f"sidecar stderr:\n{select_export.stderr[-3000:]}"
        )

    def test_the_log_and_the_harness_agree(self, select_export: LoggedExport) -> None:
        reference = browser_text(SELECT_DOCUMENT)
        assert reference_text_loss(select_export.pptx, [reference]) == [[SELECT_WORD]], (
            "fixture drift: the export must lose exactly the selected option's text"
        )
        summary = _only_summary(select_export)
        harness_missing = reference_text_loss(
            select_export.pptx, [reference], hidden_text=[summary["hiddenText"]]
        )
        assert harness_missing == [[SELECT_WORD]]
        assert text_missing_reports(select_export.stderr) == harness_missing


@pytest.mark.slow
@requires_huashu_sidecar
class TestHostileRealm:
    """The reference is read through the pristine-realm accessors, like every page-side read."""

    @pytest.fixture(scope="class")
    def twins(self) -> Iterator[tuple[LoggedExport, LoggedExport]]:
        with pytest.MonkeyPatch.context() as monkeypatch:
            hostile = export_logged([HOSTILE_TEXT_DOCUMENT], monkeypatch=monkeypatch)
            benign = export_logged([BENIGN_DOCUMENT], monkeypatch=monkeypatch)
        yield hostile, benign

    def test_the_poisoning_takes(self) -> None:
        """Before anything else: a reader of the realm sees the decoy and finds no SVG."""
        report = json.loads(browser_title(HOSTILE_BODY_DOCUMENT))
        for name in (*HOSTILE_REPLACED, "Document.body"):
            assert report["replaced"].get(name) is True, f"{name} was not replaced: {report}"
        assert report["sees"] == {
            "innerText": HOSTILE_DECOY,
            "svgCount": 0,
            "bodyIsDecoy": True,
        }, report

    def test_a_realm_that_lies_about_its_text_exports_as_the_benign_one(
        self, twins: tuple[LoggedExport, LoggedExport]
    ) -> None:
        hostile, benign = twins
        assert hostile.failures == [] and benign.failures == [], (hostile.failures, benign.failures)
        assert structural_manifest(hostile.pptx) == structural_manifest(benign.pptx), (
            "the hostile slide does not export as its benign twin"
        )
        hostile_summary = _only_summary(hostile)
        benign_summary = _only_summary(benign)
        assert text_missing_reports(hostile.stderr) == [], (
            f"a decoy innerText or a querySelectorAll that finds nothing fed the reference; "
            f"stderr:\n{hostile.stderr[-3000:]}"
        )
        without_clock = {key: value for key, value in hostile_summary.items() if key != "captureMs"}
        assert without_clock == {
            key: value for key, value in benign_summary.items() if key != "captureMs"
        }

    def test_a_replaced_document_body_does_not_feed_the_reference(self) -> None:
        """``document.body`` returns a detached decoy: the reference reads the real body."""
        with pytest.MonkeyPatch.context() as monkeypatch:
            logged = export_logged([HOSTILE_BODY_DOCUMENT], monkeypatch=monkeypatch)
        _only_summary(logged)
        assert text_missing_reports(logged.stderr) == [], f"stderr:\n{logged.stderr[-3000:]}"

    def test_a_replaced_document_body_keeps_the_slide_ground(
        self, twins: tuple[LoggedExport, LoggedExport]
    ) -> None:
        """``document.body`` returns a detached decoy: the slide keeps its F9F7F4 ground.

        The background transfer copies the slide root's ground onto body, where
        the snapshot reads the slide background, and marks the root so its
        ground is not drawn twice. Written to the decoy instead, the ground
        reaches no page the snapshot reads, and the slide exports white. The
        whole artifact is the benign twin's.
        """
        _, benign = twins
        with pytest.MonkeyPatch.context() as monkeypatch:
            hostile = export_logged([HOSTILE_BODY_DOCUMENT], monkeypatch=monkeypatch)
        assert hostile.failures == [], hostile.failures
        assert slide_background(hostile.pptx) == PAPER, (
            f"the slide exports on {slide_background(hostile.pptx)}, not its {PAPER} ground"
        )
        assert structural_manifest(hostile.pptx) == structural_manifest(benign.pptx), (
            "the slide whose script replaces document.body does not export as its benign twin"
        )


# ---------------------------------------------------------------------------
# The harness's text-loss oracle (scripts/export_fidelity/run.py), no browser
# ---------------------------------------------------------------------------


class TestHarnessOracle:
    """``check_text_loss`` over decks python-pptx builds, so each case is exact."""

    def test_a_deck_one_slide_short_reports_all_of_the_missing_slides_words(self) -> None:
        """GUARD: the reference's second slide has no slide."""
        pptx = _deck_of_texts([["Alpha Bravo"]])
        assert reference_text_loss(pptx, ["Alpha Bravo", "Charlie Delta"]) == [
            [],
            ["Charlie", "Delta"],
        ]

    def test_without_hidden_text_the_oracle_is_unchanged(self) -> None:
        """GUARD: the three-argument call the support helpers make."""
        pptx = _deck_of_texts([["Revenue grew"]])
        assert reference_text_loss(pptx, ["Revenue secretword grew"]) == [["secretword"]]

    def test_each_slides_hidden_words_excuse_that_slide_only(self) -> None:
        pptx = _deck_of_texts([["Revenue grew"], ["Total up"]])
        references = ["Revenue secretword grew", "Total Margin up"]
        assert reference_text_loss(pptx, references, hidden_text=["secretword", "Margin"]) == [
            [],
            [],
        ]
        assert reference_text_loss(pptx, references, hidden_text=["Margin", "secretword"]) == [
            ["secretword"],
            ["Margin"],
        ]

    @pytest.mark.parametrize("code_point", tuple(DEFAULT_IGNORABLE_CODE_POINTS))
    def test_default_ignorable_code_points_are_no_difference(self, code_point: str) -> None:
        character = DEFAULT_IGNORABLE_CODE_POINTS[code_point]
        emitted = _deck_of_texts([[f"Reve{character}nue grew"]])
        assert reference_text_loss(emitted, ["Revenue grew"]) == [[]], (
            f"{code_point} inside an emitted word"
        )
        plain = _deck_of_texts([["Revenue grew"]])
        assert reference_text_loss(plain, [f"Reve{character}nue grew"]) == [[]], (
            f"{code_point} inside a reference word"
        )

    def test_a_word_joiner_after_a_superscript_is_no_difference(self) -> None:
        """A superscript "1" and its word joiner, for the harness's ``_normalise_text``."""
        pptx = _deck_of_texts([[f"Revenue grew1{WORD_JOINER}"]])
        assert reference_text_loss(pptx, ["Revenue grew¹"]) == [[]]

    def test_a_hyphen_written_as_hyphen_minus_is_no_difference(self) -> None:
        """U+2010 HYPHEN and U+2011 NON-BREAKING HYPHEN, which the decks write as U+002D
        where an app would draw them from another font (CALIBRATION.md D8), are the
        hyphen-minus they are drawn as, for the harness's ``_normalise_text``. A dash
        stays a dash."""
        pptx = _deck_of_texts([["end-to-end left-to-right"]])
        assert reference_text_loss(pptx, ["end\u2011to\u2011end left\u2010to\u2010right"]) == [[]]
        dashed = _deck_of_texts([["end-to-end"]])
        assert reference_text_loss(dashed, ["end\u2013to\u2013end"]) == [["end\u2013to\u2013end"]]

    def test_boxes_the_slide_paints_one_after_the_other_are_no_neighbours(self) -> None:
        """GUARD: a word is in one box's text or across neighbours, never across boxes merely
        written one after the other (python-pptx stacks _deck_of_texts' boxes a line apart)."""
        pptx = _deck_of_texts([["Customer Data", "Insights for every team"]])
        assert reference_text_loss(pptx, ["Customer Data AI Insights"]) == [["AI"]]


class TestHarnessWordsAcrossNeighbours:
    """``check_text_loss`` reads ACROSS_CASES as ``textLossLine`` does, each slide a deck."""

    @pytest.mark.parametrize("case", tuple(ACROSS_CASES))
    def test_a_word_is_written_across_neighbours_only(self, case: str) -> None:
        boxes, reference, missing = ACROSS_CASES[case]
        assert _harness_missing(boxes, reference) == missing

    @requires_node
    def test_the_harness_reads_neighbours_as_the_sidecar_does(self) -> None:
        """The two checks report the same words: one rule, with the sidecar's constants."""
        harness = fidelity_harness()
        assert {name: getattr(harness, name) for name in NEIGHBOUR_CONSTANTS} == (
            _text_check_constants()
        )

    def test_the_neighbour_search_reads_at_most_its_limit_of_boxes(self) -> None:
        """BOUND: as the sidecar's, the first ACROSS_ITEM_LIMIT boxes the rule can read."""
        limit = fidelity_harness().ACROSS_ITEM_LIMIT

        def deck(fillers: int) -> bytes:
            spacing = 600 / fillers
            filled = [
                _box_around("f", 10, 15, y=110 + index * spacing, h=spacing / 2)
                for index in range(fillers)
            ]
            return _deck_of_boxes([(*filled, NUMERAL, _financials(130))])

        assert reference_text_loss(deck(limit - 2), ["1Financials"]) == [[]]
        assert reference_text_loss(deck(limit - 1), ["1Financials"]) == [["1Financials"]]


@pytest.mark.slow
@requires_huashu_sidecar
class TestHarnessJoinedScript:
    def test_a_line_ending_superscript_in_unspaced_text_is_not_reported_missing(self) -> None:
        """The PowerPoint deck's word joiner, in a real export, is no lost word.

        The superscript ends the browser's first line, so the deck writes
        U+2060 after it; innerText reads the paragraph as one unspaced word.
        """
        assert browser_lines(JOINED_DOCUMENT, JOINED_SELECTOR) == JOINED_LINES, (
            "fixture drift: the superscript must end the first line"
        )
        with pytest.MonkeyPatch.context() as monkeypatch:
            logged = export_logged([JOINED_DOCUMENT], monkeypatch=monkeypatch)
        assert logged.failures == [], logged.failures
        joined = [shape for shape in slide_shapes(logged.pptx, 0) if "收入增长" in shape.text]
        assert len(joined) == 1 and WORD_JOINER in joined[0].text, (
            f"fixture drift: the PowerPoint deck writes no word joiner: {[s.text for s in joined]}"
        )
        assert text_loss(logged.pptx, [JOINED_DOCUMENT]) == [[]]


@pytest.mark.slow
@requires_huashu_sidecar
class TestWordsAcrossAtomicInlines:
    def test_a_numeral_and_a_chip_joined_to_their_text_are_not_reported_missing(self) -> None:
        """Through a real export, neither check reports what every item writes.

        innerText reads "1Financials", "2Operations" and "Iceberg," as words
        (checked first); the export writes the numerals and the chip as items of
        their own. The sidecar logs no ``text missing`` line, and the harness's
        oracle reports nothing lost.
        """
        words = browser_text(ATOMIC_DOCUMENT).split()
        assert all(word in words for word in ATOMIC_JOINED_WORDS), (
            f"fixture drift: innerText no longer runs the words together: {words}"
        )
        with pytest.MonkeyPatch.context() as monkeypatch:
            logged = export_logged([ATOMIC_DOCUMENT], monkeypatch=monkeypatch)
        assert logged.failures == [], logged.failures
        assert text_missing_reports(logged.stderr) == [], f"stderr:\n{logged.stderr[-3000:]}"
        assert text_loss(logged.pptx, [ATOMIC_DOCUMENT]) == [[]]

    def test_chips_lost_from_a_real_export_are_reported_by_both_checks(self) -> None:
        """REAL LOSS: the review's probe, exported, then its chips taken out of the deck.

        Exported whole, neither check reports a word. With the chips' text boxes
        taken out, each chip's letters still end and start the boxes either
        side of where it was ("Customer Dat[a] | [I]nsights"), and both checks
        report the three chips: the harness's over the deck, the sidecar's over
        the deck's own boxes read as a slide model's items, so both read the
        geometry the real engine wrote.
        """
        document = _pinned_case_document(PROBE_BODY)
        reference = browser_text(document)
        assert all(chip in reference.split() for chip in PROBE_CHIPS), (
            f"fixture drift: innerText no longer reads the chips as words: {reference!r}"
        )
        with pytest.MonkeyPatch.context() as monkeypatch:
            logged = export_logged([document], monkeypatch=monkeypatch)
        assert logged.failures == [], logged.failures
        assert text_missing_reports(logged.stderr) == [], f"stderr:\n{logged.stderr[-3000:]}"
        assert text_loss(logged.pptx, [document]) == [[]]
        assert _sidecar_missing(_boxes_of_slide(logged.pptx), reference) == []

        lost = _without_text_boxes(logged.pptx, PROBE_CHIPS)
        assert text_loss(lost, [document]) == [list(PROBE_CHIPS)]
        assert _sidecar_missing(_boxes_of_slide(lost), reference) == list(PROBE_CHIPS)


# ---------------------------------------------------------------------------
# The harness reads the summaries
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HarnessDeck:
    """The harness deck exported through ``run.py::export_pptx``, with its references."""

    pptx_path: Path
    out_dir: Path
    stderr: str  # what export_pptx left on stderr
    names: tuple[str, ...]  # the reference's slides, one more than the documents

    def recorded_summaries(self) -> list:
        path = self.out_dir / "summaries.json"
        assert path.exists(), f"export_pptx wrote no {path.name} beside failures.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def logged_hidden_text(self) -> list[str]:
        """Each reference slide's hiddenText from the summary lines; '' where no slide was."""
        summaries = slide_summaries(self.stderr)
        assert len(summaries) == 2, (
            f"two of the three documents export, yet {len(summaries)} summary lines were "
            f"logged:\n{self.stderr[-3000:]}"
        )
        return [summaries[0]["hiddenText"], "", summaries[1]["hiddenText"], ""]


@pytest.fixture(scope="module")
def harness_deck(tmp_path_factory: pytest.TempPathFactory) -> Iterator[HarnessDeck]:
    harness = fidelity_harness()
    out_dir = tmp_path_factory.mktemp("harness-deck")
    documents_dir = out_dir / "documents"
    documents_dir.mkdir()
    documents = {
        HARNESS_FORGED: HARNESS_FORGED_DOCUMENT,
        HARNESS_FAILED: "",
        HARNESS_SCREEN_READER: corpus_document("03"),
    }
    paths = []
    for name, document in documents.items():
        path = documents_dir / f"{name}.html"
        path.write_text(document, encoding="utf-8")
        paths.append(path)
    # References: the browser's for the slides that render, hand-written for the rest.
    harness.render_truth([paths[0], paths[2]], out_dir)
    (out_dir / "truth" / f"{HARNESS_FAILED}.txt").write_text(
        HARNESS_FAILED_REFERENCE, encoding="utf-8"
    )
    (out_dir / "truth" / f"{HARNESS_BEYOND}.txt").write_text(
        HARNESS_BEYOND_REFERENCE, encoding="utf-8"
    )
    with pytest.MonkeyPatch.context() as monkeypatch:
        # export_pptx sets it in os.environ; the context restores it.
        monkeypatch.setenv("HUASHU_PIPELINE_ENABLED", "1")
        with teed_stderr() as buffer:
            pptx_path = harness.export_pptx({"title": "harness deck"}, paths, out_dir)
    failures = json.loads((out_dir / "failures.json").read_text(encoding="utf-8"))
    assert [failure["slide_index"] for failure in failures] == [1], (
        f"fixture drift: only the empty document fails: {failures}"
    )
    yield HarnessDeck(
        pptx_path=pptx_path,
        out_dir=out_dir,
        stderr=buffer.getvalue(),
        names=(HARNESS_FORGED, HARNESS_FAILED, HARNESS_SCREEN_READER, HARNESS_BEYOND),
    )


@pytest.mark.slow
@requires_huashu_sidecar
class TestHarnessExport:
    """``export_pptx`` tees stderr and records each document's summary, in slide order."""

    def test_the_sidecar_log_still_reaches_stderr(self, harness_deck: HarnessDeck) -> None:
        assert len(slide_summaries(harness_deck.stderr)) == 2, (
            f"stderr while export_pptx ran:\n{harness_deck.stderr[-3000:]}"
        )

    def test_no_slide_model_is_dropped(self, harness_deck: HarnessDeck) -> None:
        """No slide's script forges its model, so the harness warns of no model drops."""
        assert fidelity_harness().MODEL_DROPS_WARNING not in harness_deck.stderr, (
            f"stderr while export_pptx ran:\n{harness_deck.stderr[-3000:]}"
        )
        assert all(
            entry is None or entry["modelDrops"] == 0 for entry in harness_deck.recorded_summaries()
        ), harness_deck.recorded_summaries()

    def test_one_summary_is_recorded_per_document_in_slide_order(
        self, harness_deck: HarnessDeck
    ) -> None:
        recorded = harness_deck.recorded_summaries()
        assert len(recorded) == 3, f"three documents, {len(recorded)} entries: {recorded}"
        assert recorded[1] is None, f"the failed document has no summary: {recorded[1]}"
        assert recorded[0]["hiddenText"] == HARNESS_FORGED_HIDDEN, recorded[0]
        assert recorded[2]["hiddenText"].split() == list(SR_ONLY_WORDS), recorded[2]
        assert recorded[0]["target"] == recorded[2]["target"] == "pptx"

    def test_a_summary_logged_by_slide_script_is_not_read(self, harness_deck: HarnessDeck) -> None:
        """Slide script's lookalike lines reach stderr behind "Browser console:"; none is read."""
        assert "Browser console: [html2pptx] slide summary" in harness_deck.stderr, (
            "fixture drift: the forged line never reached stderr"
        )
        recorded = harness_deck.recorded_summaries()
        assert all(
            entry is None or entry["hiddenText"] != FORGED_HIDDEN_TEXT for entry in recorded
        ), recorded

    def test_a_slide_the_export_failed_loses_all_its_words(self, harness_deck: HarnessDeck) -> None:
        """Its words appear on the slide after it, so position-only pairing would hide the loss."""
        missing = fidelity_harness().check_text_loss(
            harness_deck.pptx_path, list(harness_deck.names), harness_deck.out_dir
        )
        assert missing.get(HARNESS_FAILED) == HARNESS_FAILED_REFERENCE.split(), missing

    def test_the_slide_after_a_failed_one_is_compared_with_its_own_slide(
        self, harness_deck: HarnessDeck
    ) -> None:
        """Without hidden text, corpus slide 03 can lose only its screen-reader-only words."""
        missing = fidelity_harness().check_text_loss(
            harness_deck.pptx_path, list(harness_deck.names), harness_deck.out_dir
        )
        lost = missing.get(HARNESS_SCREEN_READER, [])
        assert set(lost) <= set(SR_ONLY_WORDS), (
            f"slide 03 was compared with another slide's text: {lost}"
        )

    def test_a_slide_past_the_end_of_the_deck_loses_all_its_words(
        self, harness_deck: HarnessDeck
    ) -> None:
        """GUARD: the reference's fourth slide has none in the deck."""
        missing = fidelity_harness().check_text_loss(
            harness_deck.pptx_path, list(harness_deck.names), harness_deck.out_dir
        )
        assert missing.get(HARNESS_BEYOND) == HARNESS_BEYOND_REFERENCE.split(), missing

    def test_with_each_slides_hidden_text_only_the_absent_slides_lose_words(
        self, harness_deck: HarnessDeck
    ) -> None:
        missing = fidelity_harness().check_text_loss(
            harness_deck.pptx_path,
            list(harness_deck.names),
            harness_deck.out_dir,
            hidden_text=harness_deck.logged_hidden_text(),
        )
        assert missing == {
            HARNESS_FAILED: HARNESS_FAILED_REFERENCE.split(),
            HARNESS_BEYOND: HARNESS_BEYOND_REFERENCE.split(),
        }

    def test_the_google_slides_export_records_its_own_summaries(self, tmp_path: Path) -> None:
        document = tmp_path / "01-off-slide.html"
        document.write_text(HIDDEN_CASES["off-slide"].document, encoding="utf-8")
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setenv("HUASHU_PIPELINE_ENABLED", "1")
            with teed_stderr() as buffer:
                fidelity_harness().export_pptx(
                    {"title": "harness deck"}, [document], tmp_path, target="gslides"
                )
        stderr = buffer.getvalue()
        assert fidelity_harness().MODEL_DROPS_WARNING not in stderr, stderr[-3000:]
        path = tmp_path / "summaries-gslides.json"
        assert path.exists(), "export_pptx wrote no summaries-gslides.json"
        recorded = json.loads(path.read_text(encoding="utf-8"))
        assert len(recorded) == 1 and recorded[0]["target"] == "gslides", recorded
        assert recorded[0]["hiddenText"].split() == list(HIDDEN_CASES["off-slide"].hidden_words)


@pytest.mark.slow
@requires_huashu_sidecar
class TestHarnessRun:
    def test_the_harness_reports_no_hidden_or_joined_word_missing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``run.py`` end to end: hidden text and the word joiner are no text loss.

        A fixture deck of corpus slide 03 (its screen-reader-only table), a
        slide hiding words by opacity, a split word, off-slide text and an
        ellipsis, and the joined superscript, exported for PowerPoint. No
        slide's script forges its model, so the harness warns of no model drops.
        """
        fixture_dir = tmp_path / "fixture"
        slides_dir = fixture_dir / "slides"
        slides_dir.mkdir(parents=True)
        shutil.copyfile(CORPUS_DIR / "deck.json", fixture_dir / "deck.json")
        shutil.copyfile(CORPUS_DIR / "deck.css", fixture_dir / "deck.css")
        bodies = {
            "01-screen-reader": corpus_slide("03"),
            "02-hidden": HARNESS_RUN_HIDDEN_BODY,
            "03-joined": JOINED_BODY,
        }
        for name, body in bodies.items():
            (slides_dir / f"{name}.html").write_text(body, encoding="utf-8")
        out_dir = tmp_path / "out"
        # main() sets it in os.environ; monkeypatch restores it.
        monkeypatch.setenv("HUASHU_PIPELINE_ENABLED", "1")
        monkeypatch.setattr(sys, "argv", ["run.py", str(fixture_dir), "--out", str(out_dir)])

        assert fidelity_harness().main() == 0

        lost = json.loads((out_dir / "text_loss.json").read_text(encoding="utf-8"))
        assert lost == {}, f"the harness reports hidden or joined words missing: {lost}"
        printed = capsys.readouterr()
        assert "Text missing from the export: none" in printed.out
        assert fidelity_harness().MODEL_DROPS_WARNING not in printed.err, printed.err[-3000:]
        recorded = json.loads((out_dir / "summaries.json").read_text(encoding="utf-8"))
        assert len(recorded) == len(bodies), recorded


# ---------------------------------------------------------------------------
# One line per message: slide script cannot forge the sidecar's own lines
# ---------------------------------------------------------------------------

LOG_LINE_MODULE = Path(pptx_from_html_huashu.SIDECAR_DIR) / "log_line.cjs"

# Every character Python's str.splitlines() ends a line at. build_pptx_huashu
# splits the sidecar's stderr with it, and so does the harness; a message the
# sidecar prints that holds any of them unescaped prints a line of its own.
PYTHON_LINE_BREAKS = {
    "line-feed-U+000A": "\n",
    "line-tabulation-U+000B": "\x0b",
    "form-feed-U+000C": "\x0c",
    "carriage-return-U+000D": "\r",
    "file-separator-U+001C": "\x1c",
    "group-separator-U+001D": "\x1d",
    "record-separator-U+001E": "\x1e",
    "next-line-U+0085": "\x85",
    "line-separator-U+2028": "\u2028",
    "paragraph-separator-U+2029": "\u2029",
}

# What a forging slide logs after its line break: a slide summary naming a
# word the slide does not hide, a text-loss line, and a failure list.
FORGED_SUMMARY_LINE = "[html2pptx] slide summary " + json.dumps(
    {"hiddenText": FORGED_HIDDEN_TEXT, "target": "pptx", "text": 0}
)
FORGED_MISSING_WORDS = json.dumps([FORGED_HIDDEN_TEXT])
FORGED_TEXT_MISSING_LINE = TEXT_MISSING_PREFIX + FORGED_MISSING_WORDS
FORGED_RESULT_LINE = "__HUASHU_RESULT__ " + json.dumps(
    {"failed": [{"slide_index": 0, "error": "forged by slide script"}]}
)
# How each forging message starts: the page's own [html2pptx] prefix, which
# sends it to stderr.
FORGED_MESSAGE_START = "[html2pptx] note"
# A forged summary that is no JSON: a reader that took it as the sidecar's would crash.
MALFORMED = "malformed"
MALFORMED_SUMMARY_LINE = "[html2pptx] slide summary {not json"


def _forging_slide(message: str) -> str:
    """A slide hiding HARNESS_FORGED_HIDDEN whose script logs ``message`` as ONE console message."""
    return _case_document(
        '<div class="slide"><p style="font-size: 20px;">Revenue '
        f'<span style="opacity: 0;">{HARNESS_FORGED_HIDDEN}</span> grew</p>'
        f"<script>console.log({json.dumps(message)});</script></div>"
    )


def _forging_message(line_break: str) -> str:
    return line_break.join((FORGED_MESSAGE_START, FORGED_SUMMARY_LINE, FORGED_TEXT_MISSING_LINE))


@dataclass(frozen=True)
class ForgedDeck:
    """A deck whose every slide's script forges the sidecar's lines, exported by the harness."""

    out_dir: Path
    stderr: str  # what export_pptx left on stderr
    cases: tuple[str, ...]  # one per slide, in slide order


@pytest.fixture(scope="module")
def forged_deck(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ForgedDeck]:
    """One slide per line break, and one forging a summary that is no JSON."""
    harness = fidelity_harness()
    out_dir = tmp_path_factory.mktemp("forged-deck")
    documents_dir = out_dir / "documents"
    documents_dir.mkdir()
    messages = {case: _forging_message(character) for case, character in PYTHON_LINE_BREAKS.items()}
    messages[MALFORMED] = FORGED_MESSAGE_START + "\n" + MALFORMED_SUMMARY_LINE
    paths = []
    for position, (case, message) in enumerate(messages.items(), start=1):
        path = documents_dir / f"{position:02d}-{case}.html"
        path.write_text(_forging_slide(message), encoding="utf-8")
        paths.append(path)
    with pytest.MonkeyPatch.context() as monkeypatch:
        # export_pptx sets it in os.environ; the context restores it.
        monkeypatch.setenv("HUASHU_PIPELINE_ENABLED", "1")
        with teed_stderr() as buffer:
            harness.export_pptx({"title": "forged deck"}, paths, out_dir)
    yield ForgedDeck(out_dir=out_dir, stderr=buffer.getvalue(), cases=tuple(messages))


@pytest.mark.slow
@requires_huashu_sidecar
class TestForgedLines:
    """A console message is one stderr line, whatever line break the slide's script puts in it."""

    def test_every_slide_records_its_own_summary(self, forged_deck: ForgedDeck) -> None:
        recorded = json.loads((forged_deck.out_dir / "summaries.json").read_text(encoding="utf-8"))
        assert [None if entry is None else entry["hiddenText"] for entry in recorded] == [
            HARNESS_FORGED_HIDDEN
        ] * len(forged_deck.cases), dict(zip(forged_deck.cases, recorded))

    def test_no_forged_line_is_read(self, forged_deck: ForgedDeck) -> None:
        summaries = slide_summaries(forged_deck.stderr)
        assert [summary["hiddenText"] for summary in summaries] == [HARNESS_FORGED_HIDDEN] * len(
            forged_deck.cases
        ), f"stderr:\n{forged_deck.stderr[-3000:]}"
        assert text_missing_reports(forged_deck.stderr) == [], (
            f"a forged text-loss line was read; stderr:\n{forged_deck.stderr[-3000:]}"
        )

    def test_each_console_message_reaches_stderr_whole(self, forged_deck: ForgedDeck) -> None:
        """The message is kept, all of it on the one line that starts it."""
        lines = [
            line
            for line in forged_deck.stderr.splitlines()
            if f"Browser console: {FORGED_MESSAGE_START}" in line
        ]
        assert len(lines) == len(forged_deck.cases), lines
        for case, line in zip(forged_deck.cases, lines):
            # A whole message ends with its forged text-loss line's words.
            expected = "{not json" if case == MALFORMED else FORGED_MISSING_WORDS
            assert line.endswith(expected), f"{case}: the message was cut: {line!r}"


LINE_BREAK_CASES = ("line-feed-U+000A", "line-separator-U+2028")


@pytest.mark.slow
@requires_huashu_sidecar
class TestForgedResultLine:
    """``build_pptx_huashu`` reports the failures the sidecar found, not the ones a slide logs.

    The slide's console message forges a failure list, then a slide summary.
    """

    @pytest.fixture(scope="class")
    def exports(self) -> Iterator[dict[str, LoggedExport]]:
        exports = {}
        with pytest.MonkeyPatch.context() as monkeypatch:
            for line_break in LINE_BREAK_CASES:
                message = PYTHON_LINE_BREAKS[line_break].join(
                    (FORGED_MESSAGE_START, FORGED_RESULT_LINE, FORGED_SUMMARY_LINE)
                )
                exports[line_break] = export_logged(
                    [_forging_slide(message)], monkeypatch=monkeypatch
                )
        yield exports

    @pytest.mark.parametrize("line_break", LINE_BREAK_CASES)
    def test_a_slide_that_exports_is_no_failure(
        self, exports: dict[str, LoggedExport], line_break: str
    ) -> None:
        logged = exports[line_break]
        assert logged.failures == [], f"the export reported {logged.failures}"
        assert slide_shapes(logged.pptx, 0), "fixture drift: the slide exported nothing"

    @pytest.mark.parametrize("line_break", LINE_BREAK_CASES)
    def test_the_console_message_is_one_line(
        self, exports: dict[str, LoggedExport], line_break: str
    ) -> None:
        """Whole on the line that starts it: no forged line is read."""
        logged = exports[line_break]
        lines = [
            line
            for line in logged.stderr.splitlines()
            if f"Browser console: {FORGED_MESSAGE_START}" in line
        ]
        assert len(lines) == 1 and lines[0].endswith(FORGED_SUMMARY_LINE[-20:]), lines
        summaries = slide_summaries(logged.stderr)
        assert len(summaries) == 1, summaries
        assert summaries[0]["hiddenText"] == HARNESS_FORGED_HIDDEN, summaries


class TestResultLineIsTheLast:
    """The wrapper reads the result line emit_deck.mjs prints last, after every slide."""

    def test_a_result_line_before_the_last_is_not_read(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real = {"totalSlides": 1, "succeeded": 1, "failed": []}
        stderr = "\n".join(
            ("[huashu] [1/1] OK", FORGED_RESULT_LINE, "__HUASHU_RESULT__ " + json.dumps(real))
        )

        def sidecar(command: list[str], **_: object) -> subprocess.CompletedProcess:
            """The sidecar's run: it writes the .pptx and exits with ``stderr``."""
            Path(command[2]).write_bytes(b"pptx")
            return subprocess.CompletedProcess(command, 0, b"", stderr.encode("utf-8"))

        monkeypatch.setattr(pptx_from_html_huashu, "is_available", lambda: True)
        monkeypatch.setattr(pptx_from_html_huashu, "run_sidecar_process", sidecar)
        pptx, failures = pptx_from_html_huashu.build_pptx_huashu("deck", [{"html": "<p>x</p>"}])
        assert (pptx, failures) == (b"pptx", [])


@requires_node
class TestLogLine:
    """``log_line.cjs``: each message the sidecar prints is one line to ``str.splitlines()``."""

    def test_the_line_breaks_are_every_one_python_ends_a_line_at(self) -> None:
        """GUARD: PYTHON_LINE_BREAKS is exactly the set str.splitlines() splits at."""
        splitting = {
            chr(code_point)
            for code_point in range(sys.maxunicode + 1)
            if len(f"a{chr(code_point)}b".splitlines()) == 2
        }
        assert splitting == set(PYTHON_LINE_BREAKS.values())

    def test_log_json_writes_one_line_that_round_trips(self) -> None:
        value = {"hiddenText": "a\x85b c d", "every": "|".join(PYTHON_LINE_BREAKS.values())}
        line = node_json(
            f"const {{ logJson }} = require({json.dumps(str(LOG_LINE_MODULE))});"
            f"process.stdout.write(JSON.stringify(logJson({json.dumps(value)})));"
        )
        assert isinstance(line, str) and len(line.splitlines()) == 1, repr(line)
        assert json.loads(line) == value

    @pytest.mark.parametrize("line_break", tuple(PYTHON_LINE_BREAKS))
    def test_one_line_keeps_all_of_a_message_on_one_line(self, line_break: str) -> None:
        message = f"before{PYTHON_LINE_BREAKS[line_break]}after"
        line = node_json(
            f"const {{ oneLine }} = require({json.dumps(str(LOG_LINE_MODULE))});"
            f"process.stdout.write(JSON.stringify(oneLine({json.dumps(message)})));"
        )
        assert isinstance(line, str) and len(line.splitlines()) == 1, repr(line)
        assert line.startswith("before") and line.endswith("after"), repr(line)


@pytest.mark.slow
@requires_huashu_sidecar
class TestHiddenTextOnOneLine:
    def test_hidden_text_holding_a_next_line_is_one_summary(self) -> None:
        """U+0085, which JSON.stringify leaves as it is, splits no summary line."""
        document = _case_document(
            '<div class="slide"><p style="font-size: 20px;">Revenue '
            '<span style="opacity: 0;">alpha\x85beta</span> grew</p></div>'
        )
        with pytest.MonkeyPatch.context() as monkeypatch:
            logged = export_logged([document], monkeypatch=monkeypatch)
        summary = _only_summary(logged)
        assert summary["hiddenText"] == "alpha\x85beta", summary
        assert text_missing_reports(logged.stderr) == [], logged.stderr[-3000:]


# ---------------------------------------------------------------------------
# Every text reference hides the graphics the same way
# ---------------------------------------------------------------------------

GRAPHIC_LABEL = "Chartlabel"
GRAPHIC_BODY = (
    '<div class="slide"><p style="font-size: 20px;">Revenue grew</p>'
    '<svg width="300" height="60"><rect width="300" height="60" fill="#00A972"/>'
    f'<text x="10" y="40" font-size="20">{GRAPHIC_LABEL}</text></svg></div>'
)
# Deck CSS that keeps a graphic shown against an inline display: none, each
# its own way: an !important rule, and a display that transitions discretely
# (it stays shown until the transition ends).
GRAPHIC_KEEPERS = {
    "important-display-rule": "svg { display: block !important; }",
    "display-transition": "svg { transition: display 60s allow-discrete; }",
}


def _graphic_document(case: str) -> str:
    return slide_document(
        GRAPHIC_BODY, css=DECK_CSS + "\n" + GRAPHIC_KEEPERS[case] + "\n", slide_id="snapshot-1"
    )


@pytest.mark.slow
@requires_huashu_sidecar
class TestGraphicsHiddenAlike:
    """The sidecar's, the harness's and the tests' references all leave a graphic's text out."""

    @pytest.fixture(scope="class")
    def exports(self) -> Iterator[dict[str, LoggedExport]]:
        with pytest.MonkeyPatch.context() as monkeypatch:
            yield {
                case: export_logged([_graphic_document(case)], monkeypatch=monkeypatch)
                for case in GRAPHIC_KEEPERS
            }

    @pytest.mark.parametrize("case", tuple(GRAPHIC_KEEPERS))
    def test_the_sidecar_reports_no_loss(self, exports: dict[str, LoggedExport], case: str) -> None:
        summary = _only_summary(exports[case])
        assert summary["pictures"] == 1, f"fixture drift: the svg must be captured: {summary}"
        assert text_missing_reports(exports[case].stderr) == [], exports[case].stderr[-3000:]

    @pytest.mark.parametrize("case", tuple(GRAPHIC_KEEPERS))
    def test_the_test_reference_leaves_the_label_out(self, case: str) -> None:
        """``browser_text`` (measure.cjs), which ``text_loss`` compares with."""
        assert GRAPHIC_LABEL not in browser_text(_graphic_document(case)).split()

    @pytest.mark.parametrize("case", tuple(GRAPHIC_KEEPERS))
    def test_the_harness_reports_no_loss(
        self, exports: dict[str, LoggedExport], case: str, tmp_path: Path
    ) -> None:
        """``render_truth.cjs``'s reference, compared by ``check_text_loss``."""
        harness = fidelity_harness()
        path = tmp_path / "01-graphic.html"
        path.write_text(_graphic_document(case), encoding="utf-8")
        harness.render_truth([path], tmp_path)
        reference = (tmp_path / "truth" / "01-graphic.txt").read_text(encoding="utf-8")
        assert GRAPHIC_LABEL not in reference.split(), reference
        (tmp_path / "export.pptx").write_bytes(exports[case].pptx)
        assert harness.check_text_loss(tmp_path / "export.pptx", ["01-graphic"], tmp_path) == {}


# ---------------------------------------------------------------------------
# Node and Python normalise with the same sets, over every code point
# ---------------------------------------------------------------------------


@functools.cache
def _node_character_sets() -> dict[str, list[int]]:
    """The code points text_check.cjs takes as white space, and as default-ignorable."""
    script = (
        f"const textCheck = require({json.dumps(str(TEXT_CHECK_MODULE))});"
        "const sets = { whiteSpace: [], defaultIgnorable: [] };"
        "for (let code = 0; code <= 0x10ffff; code++) {"
        "  if (code >= 0xd800 && code <= 0xdfff) continue;"
        "  const character = String.fromCodePoint(code);"
        "  if (textCheck.isWhiteSpace(character)) sets.whiteSpace.push(code);"
        "  if (textCheck.isDefaultIgnorable(character)) sets.defaultIgnorable.push(code);"
        "}"
        "process.stdout.write(JSON.stringify(sets));"
    )
    return node_json(script)


def _python_code_points() -> range:
    return range(sys.maxunicode + 1)


def _is_surrogate(code_point: int) -> bool:
    return 0xD800 <= code_point <= 0xDFFF


@requires_node
class TestNormalisationSets:
    """``missingWords`` and the harness's ``_normalise_text`` see through the same characters."""

    def test_both_split_words_at_the_same_white_space(self) -> None:
        python = {
            code_point
            for code_point in _python_code_points()
            if not _is_surrogate(code_point) and chr(code_point).isspace()
        }
        assert set(_node_character_sets()["whiteSpace"]) == python

    def test_both_remove_the_same_default_ignorable_code_points(self) -> None:
        harness = fidelity_harness()
        python = {
            code_point
            for start, end in harness._DEFAULT_IGNORABLE_RANGES
            for code_point in range(start, end + 1)
        }
        assert set(_node_character_sets()["defaultIgnorable"]) == python


# ---------------------------------------------------------------------------
# The page-built model, validated in Node
# ---------------------------------------------------------------------------

MODEL_CHECK_MODULE = Path(pptx_from_html_huashu.SIDECAR_DIR) / "model_check.cjs"
EMIT_MODEL_MODULE = Path(pptx_from_html_huashu.SIDECAR_DIR) / "emit_model.cjs"
CAPTURE_MODULE = Path(pptx_from_html_huashu.SIDECAR_DIR) / "capture.cjs"

# The id a slide that owns Array.prototype.push gives the capture the snapshot pushes.
FORGED_CAPTURE_ID_PAYLOAD = (FORGED_RESULT_LINE, FORGED_SUMMARY_LINE)


def _forged_capture_id(line_break: str) -> str:
    return line_break.join(("c0", *FORGED_CAPTURE_ID_PAYLOAD))


def _run(text: str, **style: object) -> dict:
    run = {
        "text": text,
        "family": "Arial",
        "weight": 400,
        "italic": False,
        "sizePx": 20,
        "color": "1B3139",
        "letterSpacingPx": 0,
        "underline": False,
        "strike": False,
        "baseline": None,
        "opticalTrackingPx": 0,
        "unkernedTrackingPx": 0,
    }
    run.update(style)
    return run


def _paragraph(*runs: dict, **fields: object) -> dict:
    paragraph = {"sizePx": 20, "lineHeightPx": 24, "ascentPx": 18, "lines": [{"runs": list(runs)}]}
    paragraph.update(fields)
    return paragraph


def _border() -> dict:
    """A fresh border, so a mutation of one cell's reaches no other model."""
    return {"color": "000000", "alpha": 1, "widthPx": 1, "dash": "solid"}


def _cell(row: int, col: int, **fields: object) -> dict:
    cell = {
        "row": row,
        "col": col,
        "rowspan": 1,
        "colspan": 1,
        "fill": None,
        "borders": {"top": _border(), "right": None, "bottom": _border(), "left": None},
        "margin": {"top": 0.04, "right": 0.04, "bottom": 0.04, "left": 0.04},
        "valign": "top",
        "align": "left",
        "rtl": False,
        "font": {"family": "Arial", "weight": 400, "italic": False, "sizePx": 16},
        "paragraphs": [_paragraph(_run("Cell"))],
    }
    cell.update(fields)
    return cell


def _ground_capture(capture_id: str) -> dict:
    """The slide root's image ground as the snapshot names it: a whole-slide ``ground`` capture."""
    return {
        "id": capture_id,
        "x": 0,
        "y": 0,
        "w": 1280,
        "h": 720,
        "mode": "ground",
        "selector": f'[data-tellr-capture="{capture_id}"]',
        "pseudo": None,
        "hiddenWithin": False,
        "paint": {"borderColors": ["rgb(0, 0, 0)"] * 4, "boxShadow": "none"},
        "bordersHidden": True,
    }


def _valid_model() -> dict:
    """One item of every kind, every optional field the snapshot writes, and two captures."""
    return {
        "width": 1280,
        "height": 720,
        "background": {"color": "F9F7F4"},
        "fonts": {"DM Sans": [400, 700]},
        "italicFonts": {"DM Sans": [400]},
        "reference": {"hiddenText": "secretword"},
        "stats": {"elements": 12, "pseudoElements": 1, "truncated": False},
        "captures": [
            {
                "id": "c0",
                "x": 700,
                "y": 200,
                "w": 120,
                "h": 60,
                "mode": "subtree",
                "selector": '[data-tellr-capture="c0"]',
                "pseudo": None,
                "hiddenWithin": False,
                "paint": None,
                "bordersHidden": False,
            },
            {
                "id": "c1",
                "x": 80,
                "y": 500,
                "w": 40,
                "h": 40,
                "mode": "box",
                "selector": '[data-tellr-pseudo-host="p1"]',
                "pseudo": "before",
                "hiddenWithin": False,
                "paint": {"borderColors": ["rgb(0, 0, 0)"] * 4, "boxShadow": "none"},
                "bordersHidden": False,
            },
        ],
        "items": [
            {
                "kind": "shape",
                "id": 0,
                "order": [0],
                "x": 80,
                "y": 200,
                "w": 200,
                "h": 80,
                "geometry": "roundRect",
                "radius": 8,
                "fill": {"color": "123456", "alpha": 1},
                "line": {"color": "FF0000", "alpha": 0.5, "widthPx": 2, "dash": "dash"},
                "shadow": {
                    "color": "000000",
                    "alpha": 0.25,
                    "blurPx": 4,
                    "offsetPx": 2,
                    "angle": 90,
                },
                "rotate": None,
            },
            {
                "kind": "shape",
                "id": 1,
                "order": [1],
                "x": 300,
                "y": 200,
                "w": 40,
                "h": 40,
                "geometry": "path",
                "radius": 0,
                "fill": {"color": "00A972", "alpha": 1},
                "line": None,
                "shadow": None,
                "rotate": 15,
                "path": [[{"x": 0, "y": 0}, {"x": 40, "y": 0}, {"x": 20, "y": 40}]],
                "closed": True,
            },
            {
                "kind": "line",
                "id": 2,
                "order": [2],
                "x1": 400,
                "y1": 280,
                "x2": 600,
                "y2": 280,
                "color": "FF0000",
                "alpha": 1,
                "widthPx": 3,
                "dash": "dot",
            },
            {
                "kind": "image",
                "id": 3,
                "order": [3],
                "x": 700,
                "y": 200,
                "w": 120,
                "h": 60,
                "src": None,
                "captureId": "c0",
                "alpha": 1,
                "rotate": None,
            },
            {
                "kind": "image",
                "id": 4,
                "order": [4],
                "x": 900,
                "y": 200,
                "w": 60,
                "h": 60,
                "src": "data:image/png;base64,iVBORw0KGgo=",
                "captureId": None,
                "alpha": 0.8,
                "rotate": 30,
            },
            {
                "kind": "text",
                "id": 5,
                "order": [5],
                "x": 80,
                "y": 60,
                "w": 400,
                "h": 30,
                "rotate": None,
                "wrap": True,
                "align": "left",
                "rtl": False,
                "paragraphs": [
                    _paragraph(_run("Alpha "), _run("1", baseline="super", sizePx=14)),
                    {
                        "sizePx": 18,
                        "lineHeightPx": None,
                        "ascentPx": None,
                        "lines": [
                            {"runs": [_run("Beta", sizePx=18, underline=True)]},
                            {"runs": [], "growthPx": 2.5},
                        ],
                    },
                ],
            },
            {
                "kind": "text",
                "id": 6,
                "order": [6],
                "x": 1000,
                "y": 300,
                "w": 30,
                "h": 200,
                "rotate": 90,
                "wrap": True,
                "align": "center",
                "rtl": True,
                "inset": {"left": 2, "top": 4, "right": 2, "bottom": 0},
                "paragraphs": [_paragraph(_run("Turned"))],
            },
            {
                "kind": "table",
                "id": 7,
                "order": [7],
                "x": 80,
                "y": 320,
                "colWidths": [100, 120],
                "rowHeights": [30],
                "cells": [
                    _cell(0, 0, fill={"color": "EEEEEE", "alpha": 1}),
                    _cell(0, 1, paragraphs=None),
                ],
            },
            {
                # A filled box casting its one shadow.
                "kind": "shape",
                "id": 9,
                "order": [8],
                "x": 80,
                "y": 420,
                "w": 200,
                "h": 80,
                "geometry": "roundRect",
                "radius": 8,
                "fill": {"color": "FFFFFF", "alpha": 1},
                "line": None,
                "shadow": {
                    "color": "1B3139",
                    "alpha": 0.08,
                    "blurPx": 20,
                    "offsetPx": 8,
                    "angle": 90,
                },
                "rotate": None,
            },
            {
                # A box whose corners round by different radii: a card header's
                # 16 px top corners over square bottom ones, its top left elliptical.
                "kind": "shape",
                "id": 10,
                "order": [9],
                "x": 300,
                "y": 420,
                "w": 360,
                "h": 60,
                "geometry": "roundCorners",
                "radius": 0,
                "radii": [
                    {"h": 24, "v": 16},
                    {"h": 16, "v": 16},
                    {"h": 0, "v": 0},
                    {"h": 0, "v": 0},
                ],
                "fill": {"color": "0B2026", "alpha": 1},
                "line": None,
                "shadow": None,
                "rotate": None,
            },
        ],
    }


def _check_model(model: dict) -> dict:
    """``checkModel(model)`` in Node, the model written as a JavaScript literal (NaN, Infinity)."""
    return node_json(
        f"const {{ checkModel }} = require({json.dumps(str(MODEL_CHECK_MODULE))});"
        f"process.stdout.write(JSON.stringify(checkModel({json.dumps(model)})));"
    )


def _set(path: str, value: object):
    """A mutation of the valid model: ``path`` (dotted, list indices as digits) set to ``value``."""

    def mutate(model: dict) -> None:
        *parents, last = path.split(".")
        target = model
        for key in parents:
            target = target[int(key)] if isinstance(target, list) else target[key]
        if isinstance(target, list):
            target[int(last)] = value
        else:
            target[last] = value

    return mutate


def _set_each(*changes: tuple[str, object]):
    """A mutation of the valid model: each ``(path, value)`` set in turn, as ``_set`` sets one."""

    def mutate(model: dict) -> None:
        for path, value in changes:
            _set(path, value)(model)

    return mutate


def _in_turn(*mutations):
    """A mutation of the valid model: each of ``mutations`` made in turn."""

    def mutate(model: dict) -> None:
        for mutation in mutations:
            mutation(model)

    return mutate


def _append(path: str, value: object):
    def mutate(model: dict) -> None:
        target = model
        for key in path.split("."):
            target = target[int(key)] if isinstance(target, list) else target[key]
        target.append(value)

    return mutate


def _remove(path: str, index: int):
    def mutate(model: dict) -> None:
        target = model
        for key in path.split("."):
            target = target[int(key)] if isinstance(target, list) else target[key]
        del target[index]

    return mutate


NAN = float("nan")
INFINITY = float("inf")
INJECTED_COLOUR = '000000"/><a:latin typeface="x'

# (mutation, item ids dropped, captures dropped). Items are listed by id; the
# image item 3 shows capture c0, so dropping c0 drops it too.
MODEL_DEFECTS = {
    "capture-id-forged": (_set("captures.0.id", _forged_capture_id("\n")), {3}, 1),
    "capture-id-not-c-n": (_set("captures.1.id", "x1"), set(), 1),
    "capture-id-not-a-string": (_set("captures.1.id", 1), set(), 1),
    "capture-id-shared": (_set("captures.1.id", "c0"), {3}, 2),
    "capture-x-not-a-number": (_set("captures.0.x", "not a number"), {3}, 1),
    "capture-w-infinite": (_set("captures.0.w", INFINITY), {3}, 1),
    "capture-h-nan": (_set("captures.0.h", NAN), {3}, 1),
    "capture-mode-unknown": (_set("captures.0.mode", "everything"), {3}, 1),
    "capture-selector-not-a-string": (_set("captures.0.selector", None), {3}, 1),
    "capture-pseudo-unknown": (_set("captures.1.pseudo", "first-line"), set(), 1),
    "capture-not-an-object": (_append("captures", "c9"), set(), 1),
    # The snapshot takes one ground capture at most (the slide root's): a model
    # holding two did not come from it, so neither is kept.
    "capture-ground-twice": (
        _in_turn(
            _append("captures", _ground_capture("c2")), _append("captures", _ground_capture("c3"))
        ),
        set(),
        2,
    ),
    "item-kind-unknown": (_append("items", {"kind": "script", "id": 8, "x": 0, "y": 0}), {8}, 0),
    "item-not-an-object": (_append("items", None), {None}, 0),
    "image-capture-missing": (_set("items.3.captureId", "c9"), {3}, 0),
    "image-x-not-a-number": (_set("items.4.x", "10"), {4}, 0),
    "image-alpha-nan": (_set("items.4.alpha", NAN), {4}, 0),
    "image-src-not-a-string": (_set("items.4.src", 7), {4}, 0),
    "shape-x-not-a-number": (_set("items.0.x", "80"), {0}, 0),
    "shape-w-infinite": (_set("items.0.w", INFINITY), {0}, 0),
    "shape-rotate-nan": (_set("items.1.rotate", NAN), {1}, 0),
    "shape-geometry-unknown": (_set("items.0.geometry", "star"), {0}, 0),
    "shape-radius-missing": (_set("items.0.radius", None), {0}, 0),
    "shape-fill-colour-injected": (_set("items.0.fill.color", INJECTED_COLOUR), {0}, 0),
    "shape-outline-width-nan": (_set("items.0.line.widthPx", NAN), {0}, 0),
    "shape-outline-dash-unknown": (_set("items.0.line.dash", "wavy"), {0}, 0),
    "shape-shadow-angle-not-a-number": (_set("items.0.shadow.angle", "90"), {0}, 0),
    "shape-path-point-nan": (_set("items.1.path.0.1.x", NAN), {1}, 0),
    "shape-path-closed-not-a-boolean": (_set("items.1.closed", "yes"), {1}, 0),
    # Each corner of a box whose corners differ is its radii {h, v}, top left first.
    "shape-corner-radii-missing": (_set("items.9.radii", None), {10}, 0),
    "shape-corner-radii-three": (_remove("items.9.radii", 3), {10}, 0),
    "shape-corner-radius-nan": (_set("items.9.radii.1.v", NAN), {10}, 0),
    "shape-corner-radius-negative": (_set("items.9.radii.0.h", -4), {10}, 0),
    "shape-corner-radius-a-string": (_set("items.9.radii.2.h", "0"), {10}, 0),
    # A corner either radius of which is 0 is square: the snapshot writes it {0, 0}.
    "shape-corner-radius-half-square": (_set("items.9.radii.1", {"h": 16, "v": 0}), {10}, 0),
    "line-x1-nan": (_set("items.2.x1", NAN), {2}, 0),
    "line-colour-short": (_set("items.2.color", "F00"), {2}, 0),
    "text-x-infinite": (_set("items.5.x", INFINITY), {5}, 0),
    "text-rotate-not-a-number": (_set("items.6.rotate", "90"), {6}, 0),
    "text-align-unknown": (_set("items.5.align", "start"), {5}, 0),
    "text-wrap-not-a-boolean": (_set("items.5.wrap", 1), {5}, 0),
    "text-inset-nan": (_set("items.6.inset.top", NAN), {6}, 0),
    "text-paragraph-size-not-a-number": (_set("items.5.paragraphs.0.sizePx", "20"), {5}, 0),
    "text-paragraph-line-height-nan": (_set("items.5.paragraphs.0.lineHeightPx", NAN), {5}, 0),
    "text-line-growth-nan": (_set("items.5.paragraphs.1.lines.1.growthPx", NAN), {5}, 0),
    "text-run-text-not-a-string": (_set("items.5.paragraphs.0.lines.0.runs.0.text", 5), {5}, 0),
    "text-run-size-infinite": (
        _set("items.5.paragraphs.0.lines.0.runs.0.sizePx", INFINITY),
        {5},
        0,
    ),
    "text-run-colour-injected": (
        _set("items.5.paragraphs.0.lines.0.runs.0.color", INJECTED_COLOUR),
        {5},
        0,
    ),
    "text-run-unkerned-tracking-nan": (
        _set("items.5.paragraphs.0.lines.0.runs.0.unkernedTrackingPx", NAN),
        {5},
        0,
    ),
    "text-run-baseline-unknown": (
        _set("items.5.paragraphs.0.lines.0.runs.1.baseline", "top"),
        {5},
        0,
    ),
    "table-column-width-nan": (_set("items.7.colWidths.1", NAN), {7}, 0),
    "table-cell-row-outside-the-grid": (_set("items.7.cells.0.row", 1), {7}, 0),
    "table-cell-span-zero": (_set("items.7.cells.1.colspan", 0), {7}, 0),
    "table-cell-border-colour-injected": (
        _set("items.7.cells.0.borders.top.color", INJECTED_COLOUR),
        {7},
        0,
    ),
    "table-cell-margin-nan": (_set("items.7.cells.0.margin.left", NAN), {7}, 0),
    "table-cell-valign-unknown": (_set("items.7.cells.0.valign", "baseline"), {7}, 0),
    "table-cell-run-colour-injected": (
        _set("items.7.cells.0.paragraphs.0.lines.0.runs.0.color", INJECTED_COLOUR),
        {7},
        0,
    ),
    # The grid: each cell's spans inside it, every slot covered by exactly one cell.
    "table-cell-column-span-past-the-grid": (_set("items.7.cells.1.colspan", 5), {7}, 0),
    "table-cell-row-span-past-the-grid": (_set("items.7.cells.0.rowspan", 2), {7}, 0),
    "table-slot-shared": (_append("items.7.cells", _cell(0, 0)), {7}, 0),
    "table-slot-uncovered": (_remove("items.7.cells", 1), {7}, 0),
    # A grid with no slots: no cell covers one twice or misses one, yet the
    # snapshot never writes it, and pptxgenjs fails the slide on a table with no rows.
    "table-grid-empty": (
        _set_each(("items.7.colWidths", []), ("items.7.rowHeights", []), ("items.7.cells", [])),
        {7},
        0,
    ),
    "table-grid-no-rows": (
        _set_each(("items.7.rowHeights", []), ("items.7.cells", [])),
        {7},
        0,
    ),
    "table-grid-no-columns": (
        _set_each(("items.7.colWidths", []), ("items.7.cells", [])),
        {7},
        0,
    ),
}

# (mutation, the field reset, as an empty slide has it).
MODEL_FIELD_DEFECTS = {
    "background-colour-injected": (
        _set("background", {"color": INJECTED_COLOUR}),
        "background",
        None,
    ),
    # An image that is no raster data: URI is no background (emit_model.cjs
    # applyBackground), so the colour beside it must be one.
    "background-image-not-raster-colour-injected": (
        _set("background", {"image": "x", "color": "<script>"}),
        "background",
        None,
    ),
    "background-image-not-a-data-uri": (
        _set("background", {"image": "https://example.test/ground.png"}),
        "background",
        None,
    ),
    # A ground picture names a capture the check kept, beside the colour the
    # slide falls back to without it.
    "background-ground-capture-unknown": (
        _set("background", {"color": "F9F7F4", "captureId": "c9"}),
        "background",
        None,
    ),
    "background-ground-capture-not-a-string": (
        _set("background", {"color": "F9F7F4", "captureId": 0}),
        "background",
        None,
    ),
    # The ground picture is the slide root's ground capture, never a chart's or a box's.
    "background-capture-not-a-ground": (
        _set("background", {"color": "F9F7F4", "captureId": "c0"}),
        "background",
        None,
    ),
    "background-ground-colour-injected": (
        _set("background", {"color": INJECTED_COLOUR, "captureId": "c0"}),
        "background",
        None,
    ),
    "fonts-not-a-map": (_set("fonts", ["DM Sans"]), "fonts", {}),
    "fonts-weight-nan": (_set("fonts", {"DM Sans": [NAN]}), "fonts", {}),
    "italic-fonts-not-a-map": (_set("italicFonts", ["DM Sans"]), "italicFonts", {}),
    "italic-fonts-weight-a-string": (_set("italicFonts", {"DM Sans": ["400"]}), "italicFonts", {}),
    "hidden-text-not-a-string": (
        _set("reference", {"hiddenText": ["Forgedword"]}),
        "reference",
        {"hiddenText": ""},
    ),
    "element-count-nan": (_set("stats.elements", NAN), "stats", None),
}


@requires_node
class TestModelCheck:
    """``model_check.cjs checkModel``: Node keeps only what the snapshot could have written."""

    def test_a_valid_model_passes_untouched(self) -> None:
        model = _valid_model()
        checked = _check_model(model)
        assert checked["dropped"] == {"items": 0, "captures": 0, "fields": 0}
        assert checked["model"] == model

    def test_a_raster_background_passes_untouched(self) -> None:
        """A gradient ground the snapshot rasterised: a data: PNG, as applyBackground embeds."""
        model = _valid_model()
        model["background"] = {"image": "data:image/png;base64,iVBORw0KGgo="}
        checked = _check_model(model)
        assert checked["dropped"] == {"items": 0, "captures": 0, "fields": 0}
        assert checked["model"] == model

    def test_a_ground_picture_background_passes_untouched(self) -> None:
        """The slide root's image ground: a whole-slide ``ground`` capture the background names."""
        model = _valid_model()
        model["captures"].append(_ground_capture("c2"))
        model["background"] = {"color": "F9F7F4", "captureId": "c2"}
        checked = _check_model(model)
        assert checked["dropped"] == {"items": 0, "captures": 0, "fields": 0}
        assert checked["model"] == model

    def test_a_background_naming_one_of_two_ground_captures_is_reset(self) -> None:
        """Two ground captures: both are dropped, so the background naming one is reset."""
        model = _valid_model()
        model["captures"] += [_ground_capture("c2"), _ground_capture("c3")]
        model["background"] = {"color": "F9F7F4", "captureId": "c2"}
        checked = _check_model(model)
        assert checked["dropped"] == {"items": 0, "captures": 2, "fields": 1}, checked["dropped"]
        assert [capture["id"] for capture in checked["model"]["captures"]] == ["c0", "c1"]
        assert checked["model"]["background"] is None

    def test_a_table_whose_spans_fill_its_grid_passes_untouched(self) -> None:
        """A 2 by 2 grid: a cell spanning both rows, and one cell in each row beside it."""
        model = _valid_model()
        model["items"][7] = {
            **model["items"][7],
            "colWidths": [100, 120],
            "rowHeights": [30, 30],
            "cells": [_cell(0, 0, rowspan=2), _cell(0, 1), _cell(1, 1)],
        }
        checked = _check_model(model)
        assert checked["dropped"] == {"items": 0, "captures": 0, "fields": 0}
        assert checked["model"] == model

    @pytest.mark.parametrize("defect", tuple(MODEL_DEFECTS))
    def test_each_invalid_part_is_dropped_and_counted(self, defect: str) -> None:
        mutate, dropped_items, dropped_captures = MODEL_DEFECTS[defect]
        model = _valid_model()
        mutate(model)
        checked = _check_model(model)
        assert checked["dropped"] == {
            "items": len(dropped_items),
            "captures": dropped_captures,
            "fields": 0,
        }, checked["dropped"]
        kept_ids = [item["id"] for item in checked["model"]["items"]]
        valid = _valid_model()
        assert kept_ids == [
            item["id"] for item in valid["items"] if item["id"] not in dropped_items
        ]
        # What is kept is kept as it was.
        by_id = {item["id"]: item for item in valid["items"]}
        for item in checked["model"]["items"]:
            assert item == by_id[item["id"]], item

    @pytest.mark.parametrize("defect", tuple(MODEL_FIELD_DEFECTS))
    def test_each_invalid_field_is_reset_and_counted(self, defect: str) -> None:
        mutate, field, reset = MODEL_FIELD_DEFECTS[defect]
        model = _valid_model()
        mutate(model)
        checked = _check_model(model)
        assert checked["dropped"] == {"items": 0, "captures": 0, "fields": 1}, checked["dropped"]
        if field == "stats":
            assert checked["model"]["stats"]["elements"] == 0
            assert checked["model"]["stats"]["pseudoElements"] == 0
        else:
            assert checked["model"][field] == reset
        assert checked["model"]["items"] == _valid_model()["items"]

    @pytest.mark.parametrize(
        "defect", ["table-grid-empty", "table-grid-no-rows", "table-grid-no-columns"]
    )
    def test_a_forged_empty_grid_does_not_fail_its_slide(self, defect: str) -> None:
        """The checked model of a slide holding a table with no slots writes, the table dropped.

        pptxgenjs throws on a table with no rows, which fails the whole slide,
        and writes a row of no cells for a table with no columns: the model
        check drops the item first, and counts it, so the rest of the slide exports.
        """
        model = _valid_model()
        MODEL_DEFECTS[defect][0](model)
        written = node_json(
            "const pptxgen = require('pptxgenjs');"
            f"const {{ checkModel }} = require({json.dumps(str(MODEL_CHECK_MODULE))});"
            f"const {{ emitSlide }} = require({json.dumps(str(EMIT_MODEL_MODULE))});"
            f"const {{ model, dropped }} = checkModel({json.dumps(model)});"
            "const pres = new pptxgen(); pres.layout = 'LAYOUT_WIDE';"
            "emitSlide(pres, model, new Map(), { target: 'pptx' });"
            "pres.write({ outputType: 'nodebuffer' }).then((deck) =>"
            " process.stdout.write(JSON.stringify({ dropped, tables: model.items.filter("
            "(item) => item.kind === 'table').length, bytes: deck.length })));"
        )
        assert written["dropped"] == {"items": 1, "captures": 0, "fields": 0}, written
        assert written["tables"] == 0 and written["bytes"] > 0, written

    def test_no_shape_is_written_for_a_shadow_alone(self) -> None:
        """A shape is never named for a shadow, whatever the model says of it.

        The export draws no shape for a shadow alone (one fitted shadow is the
        box's own), so the emitter names no shape "Shadow", and a model field
        claiming a shape is one (``role``) is no field it reads.
        """
        model = _valid_model()
        model["items"][8]["role"] = "shadow"
        written = node_json(
            "const pptxgen = require('pptxgenjs');"
            "const JSZip = require('jszip');"
            f"const {{ checkModel }} = require({json.dumps(str(MODEL_CHECK_MODULE))});"
            f"const {{ emitSlide }} = require({json.dumps(str(EMIT_MODEL_MODULE))});"
            f"const {{ model }} = checkModel({json.dumps(model)});"
            "const pres = new pptxgen(); pres.layout = 'LAYOUT_WIDE';"
            "emitSlide(pres, model, new Map(), { target: 'pptx' });"
            "pres.write({ outputType: 'nodebuffer' }).then((deck) => JSZip.loadAsync(deck))"
            ".then((zip) => zip.file('ppt/slides/slide1.xml').async('string'))"
            ".then((xml) => process.stdout.write(JSON.stringify({"
            ' named: (xml.match(/name="Shadow"/g) || []).length,'
            " shapes: (xml.match(/<p:sp>/g) || []).length })));"
        )
        assert written["named"] == 0 and written["shapes"] > 0, written

    @pytest.mark.parametrize("field", ["items", "captures"])
    def test_a_list_that_is_not_one_is_empty(self, field: str) -> None:
        model = _valid_model()
        model[field] = {"0": model[field][0]}
        checked = _check_model(model)
        assert checked["model"][field] == []
        assert checked["dropped"]["fields"] == 1

    def test_the_drop_line(self) -> None:
        lines = node_json(
            f"const {{ dropLine }} = require({json.dumps(str(MODEL_CHECK_MODULE))});"
            "process.stdout.write(JSON.stringify(["
            " dropLine({ items: 0, captures: 0, fields: 0 }),"
            " dropLine({ items: 2, captures: 1, fields: 0 }),"
            " dropLine({ items: 0, captures: 0, fields: 1 })]));"
        )
        assert lines == [
            None,
            "[html2pptx] model: 2 item(s) and 1 capture(s) failed validation and were dropped",
            "[html2pptx] model: 0 item(s) and 0 capture(s) failed validation and were dropped; "
            "1 model field(s) were reset",
        ]


@requires_node
class TestCaptureFailureLines:
    """capture.cjs prints a capture's id, which the page made, on one line whatever it holds."""

    @staticmethod
    def _logged(script_body: str) -> list[str]:
        return node_json(
            f"const {{ captureAll }} = require({json.dumps(str(CAPTURE_MODULE))});"
            "const logged = [];"
            "console.error = (...parts) => logged.push(parts.join(' '));"
            f"{script_body}"
        )

    @staticmethod
    def _capture(capture_id: str) -> dict:
        return {
            "id": capture_id,
            "x": 0,
            "y": 0,
            "w": 10,
            "h": 10,
            "mode": "box",
            "selector": '[data-tellr-capture="c0"]',
            "pseudo": None,
        }

    @pytest.mark.parametrize("line_break", ["line-feed-U+000A", "line-separator-U+2028"])
    def test_a_failed_capture_is_one_line(self, line_break: str) -> None:
        forged = self._capture(_forged_capture_id(PYTHON_LINE_BREAKS[line_break]))
        logged = self._logged(
            "const page = { viewportSize: () => ({ width: 1280, height: 720 }),"
            " screenshot: async () => { throw new Error('the shot failed'); } };"
            f"captureAll(page, [{json.dumps(forged)}])"
            ".then(() => process.stdout.write(JSON.stringify(logged)));"
        )
        assert len(logged) == 1 and logged[0].startswith("[html2pptx] capture failed: c0"), logged
        assert len(logged[0].splitlines()) == 1, logged

    @pytest.mark.parametrize("line_break", ["line-feed-U+000A", "line-separator-U+2028"])
    def test_a_capture_not_attempted_is_one_line(self, line_break: str) -> None:
        """After a timeout the rest are not attempted, and each says so on one line."""
        forged = self._capture(_forged_capture_id(PYTHON_LINE_BREAKS[line_break]))
        logged = self._logged(
            "const page = { viewportSize: () => ({ width: 1280, height: 720 }),"
            " screenshot: async () => {"
            "  const error = new Error('Timeout 5000ms exceeded');"
            "  error.name = 'TimeoutError'; throw error; } };"
            f"captureAll(page, [{json.dumps(self._capture('c0'))}, {json.dumps(forged)}])"
            ".then(() => process.stdout.write(JSON.stringify(logged)));"
        )
        assert len(logged) == 2 and "not attempted" in logged[1], logged
        assert all(len(line.splitlines()) == 1 for line in logged), logged


# The patched-push slide: every capture object the
# snapshot pushes as c0 gets a forged id, and, in the broken forms, a rect that
# is no numbers, so its capture fails and capture.cjs prints the id.
FORGED_CAPTURE_FORMS = {
    "line-feed": ("line-feed-U+000A", True),
    "line-separator": ("line-separator-U+2028", True),
    "line-feed-rect-intact": ("line-feed-U+000A", False),
}
FORGED_CAPTURE_TEXT = "Revenue grew"
# How run.py export_pptx starts its warning for each slide whose model dropped anything.
HARNESS_MODEL_DROPS_PREFIX = "MODEL DROPS: "
FORGED_CAPTURE_DROP_LINE = (
    "[html2pptx] model: 1 item(s) and 1 capture(s) failed validation and were dropped"
)


def _forged_capture_slide(line_break: str, break_rect: bool) -> str:
    forged_id = json.dumps(_forged_capture_id(PYTHON_LINE_BREAKS[line_break]))
    rect = " value.x = 'not a number'; value.w = 'not a number';" if break_rect else ""
    return _case_document(
        f'<div class="slide"><p style="font-size: 20px;">{FORGED_CAPTURE_TEXT}</p>'
        '<svg width="200" height="60"><rect width="200" height="60" fill="#00A972"/></svg>'
        "<script>"
        "const realPush = Array.prototype.push;"
        "Array.prototype.push = function () {"
        "  for (let index = 0; index < arguments.length; index++) {"
        "    const value = arguments[index];"
        "    if (value && typeof value === 'object' && 'mode' in value && 'selector' in value"
        f"        && value.id === 'c0') {{ value.id = {forged_id};{rect} }}"
        "  }"
        "  return realPush.apply(this, arguments);"
        "};"
        "</script></div>"
    )


@dataclass(frozen=True)
class ForgedCaptureDeck:
    out_dir: Path
    stderr: str
    forms: tuple[str, ...]

    def recorded(self, name: str) -> object:
        return json.loads((self.out_dir / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def forged_capture_deck(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ForgedCaptureDeck]:
    """One slide per form, exported by the harness (run.py export_pptx), stderr teed."""
    harness = fidelity_harness()
    out_dir = tmp_path_factory.mktemp("forged-capture-deck")
    documents_dir = out_dir / "documents"
    documents_dir.mkdir()
    paths = []
    for position, (form, (line_break, break_rect)) in enumerate(
        FORGED_CAPTURE_FORMS.items(), start=1
    ):
        path = documents_dir / f"{position:02d}-{form}.html"
        path.write_text(_forged_capture_slide(line_break, break_rect), encoding="utf-8")
        paths.append(path)
    with pytest.MonkeyPatch.context() as monkeypatch:
        # export_pptx sets it in os.environ; the context restores it.
        monkeypatch.setenv("HUASHU_PIPELINE_ENABLED", "1")
        with teed_stderr() as buffer:
            harness.export_pptx({"title": "forged captures"}, paths, out_dir)
    yield ForgedCaptureDeck(
        out_dir=out_dir, stderr=buffer.getvalue(), forms=tuple(FORGED_CAPTURE_FORMS)
    )


@pytest.mark.slow
@requires_huashu_sidecar
class TestForgedCaptureId:
    """A slide that owns Array.prototype.push forges no line and fails no slide."""

    def test_no_slide_is_reported_failed(self, forged_capture_deck: ForgedCaptureDeck) -> None:
        """``build_pptx_huashu``'s failures, as export_pptx records them."""
        assert forged_capture_deck.recorded("failures.json") == []

    def test_no_forged_line_is_read(self, forged_capture_deck: ForgedCaptureDeck) -> None:
        summaries = slide_summaries(forged_capture_deck.stderr)
        assert [summary["hiddenText"] for summary in summaries] == [""] * len(
            forged_capture_deck.forms
        ), f"stderr:\n{forged_capture_deck.stderr[-3000:]}"
        starts = [
            line
            for line in forged_capture_deck.stderr.splitlines()
            if FORGED_HIDDEN_TEXT in line
            and line.startswith("[huashu-emit] [html2pptx] slide summary")
        ]
        assert starts == [], starts

    def test_the_harness_records_each_real_summary(
        self, forged_capture_deck: ForgedCaptureDeck
    ) -> None:
        recorded = forged_capture_deck.recorded("summaries.json")
        assert [entry["hiddenText"] for entry in recorded] == [""] * len(forged_capture_deck.forms)
        assert [entry["modelDrops"] for entry in recorded] == [2] * len(forged_capture_deck.forms)

    def test_the_forged_capture_is_dropped_and_counted(
        self, forged_capture_deck: ForgedCaptureDeck
    ) -> None:
        """The capture and the picture that shows it: one drop line per slide, and none drawn."""
        drop_lines = [
            line
            for line in forged_capture_deck.stderr.splitlines()
            if line == "[huashu-emit] " + FORGED_CAPTURE_DROP_LINE
        ]
        assert len(drop_lines) == len(forged_capture_deck.forms), forged_capture_deck.stderr[-3000:]
        for summary in slide_summaries(forged_capture_deck.stderr):
            assert summary["modelDrops"] == 2, summary
            assert summary["captures"] == 0 and summary["pictures"] == 0, summary
            assert "image" not in summary["kinds"], summary
        assert "capture failed" not in forged_capture_deck.stderr

    def test_the_harness_warns_of_each_slide_that_dropped(
        self, forged_capture_deck: ForgedCaptureDeck
    ) -> None:
        """run.py export_pptx says it loudly, slide by slide, beside the summaries it records."""
        warnings = [
            line
            for line in forged_capture_deck.stderr.splitlines()
            if line.startswith(HARNESS_MODEL_DROPS_PREFIX)
        ]
        assert warnings == [
            f"{HARNESS_MODEL_DROPS_PREFIX}{position:02d}-{form}: 2 part(s) of its slide model "
            "failed validation and were dropped; the slide exported without them"
            for position, form in enumerate(forged_capture_deck.forms, start=1)
        ], forged_capture_deck.stderr[-3000:]

    def test_the_valid_content_still_exports(self, forged_capture_deck: ForgedCaptureDeck) -> None:
        pptx = (forged_capture_deck.out_dir / "export.pptx").read_bytes()
        for index, form in enumerate(forged_capture_deck.forms):
            texts = [shape.text for shape in slide_shapes(pptx, index) if shape.kind == "text"]
            assert texts == [FORGED_CAPTURE_TEXT], f"{form}: {texts}"


# ---------------------------------------------------------------------------
# A real slide's model drops nothing: the export helpers fail loudly if it does
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestModelDropGuard:
    """``export_snapshot_support``'s exports fail on any ``[html2pptx] model:`` line.

    Every module that exports through the shared helpers (``export_slides``,
    ``export_corpus``, ``export_documents``, ``export_logged``) checks this way
    that the model check keeps the whole of each real slide: a test that means
    to drop part of one says so with ``allow_model_drops=True``.
    """

    def test_an_export_whose_model_drops_anything_fails(self) -> None:
        document = _forged_capture_slide("line-feed-U+000A", True)
        with pytest.MonkeyPatch.context() as monkeypatch:
            with pytest.raises(AssertionError, match=re.escape(FORGED_CAPTURE_DROP_LINE)):
                export_logged([document], monkeypatch=monkeypatch)

    def test_a_caller_that_means_to_drop_says_so(self) -> None:
        document = _forged_capture_slide("line-feed-U+000A", True)
        with pytest.MonkeyPatch.context() as monkeypatch:
            logged = export_logged([document], monkeypatch=monkeypatch, allow_model_drops=True)
        assert _only_summary(logged)["modelDrops"] == 2


# A native table whose spans overlap: the first row's second cell spans both
# rows, and the second row's cell spans both columns, so both cover slot (1, 1).
# The browser draws it; an a:tbl cannot hold it.
OVERLAPPING_SPANS_WORDS = ("Alpha", "Bravo", "Charlie", "overlapping")
OVERLAPPING_SPANS_DOCUMENT = slide_document(
    '<div style="position: absolute; left: 80px; top: 80px; font-family: Arial; '
    'font-size: 16px;"><table style="border-collapse: collapse"><tr>'
    '<td style="border: 1px solid #000000;">Alpha</td>'
    '<td rowspan="2" style="border: 1px solid #000000;">Bravo</td></tr>'
    '<tr><td colspan="2" style="border: 1px solid #000000;">Charlie overlapping</td></tr>'
    "</table></div>",
    css="",
    slide_id="snapshot-1",
)


@pytest.mark.slow
@requires_huashu_sidecar
class TestOverlappingSpans:
    def test_a_table_whose_cells_share_a_slot_exports_as_positioned_text(self) -> None:
        """No a:tbl whose grid is not one; its text is all still there."""
        with pytest.MonkeyPatch.context() as monkeypatch:
            logged = export_logged([OVERLAPPING_SPANS_DOCUMENT], monkeypatch=monkeypatch)
        shapes = slide_shapes(logged.pptx, 0)
        assert [shape for shape in shapes if shape.kind == "table"] == [], (
            "a table two of whose cells cover one grid slot reached the deck as an a:tbl"
        )
        texts = " ".join(shape.text for shape in shapes if shape.kind == "text").split()
        assert [word for word in OVERLAPPING_SPANS_WORDS if word not in texts] == [], texts
        assert text_missing_reports(logged.stderr) == []
