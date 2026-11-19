"""Snapshot engine: the per-slide checks (Task 12).

The snapshot engine (``TELLR_EXPORT_ENGINE=snapshot``) checks every slide it
writes, so text loss is visible in the app log and in the export fidelity
harness (spec §6):

* ``services/pptx-emit-huashu/text_check.cjs`` holds the comparison.
  ``missingWords(reference, emitted, hidden)`` returns the reference words,
  as the reference spells them and in its order, whose normalised form (white
  space and default-ignorable code points removed, lower-cased) is no
  substring of the normalised emitted text, leaving out the slide's hidden
  words. ``textLossLine(reference, items, hidden)`` collects the emitted text
  of a slide model's items (text items, which hold every list marker, outside
  ones as items of their own and inside ones as tokens of their line, and
  native table cells) and returns ``[html2pptx] text missing: <json array>``,
  or null when nothing is missing. Both are pure, so they are tested here in
  Node over hand-built item arrays, with no browser.
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
* ``scripts/export_fidelity/run.py`` reads those lines (PLAN-CORRECTIONS C8).
  ``export_pptx`` tees stderr and records the summaries in
  ``summaries{suffix}.json`` beside ``failures{suffix}.json``: one entry per
  document in slide order, null for a slide the sidecar wrote no summary for.
  ``check_text_loss(pptx_path, names, out_dir, hidden_text=None)`` excludes
  ``hidden_text[i]``'s words from slide ``names[i]``, and reports every word
  of a slide the ``.pptx`` lacks (upstream PR #59), wherever the gap falls.
  Its normalisation removes default-ignorable code points too: the PowerPoint
  deck writes a word joiner (U+2060) after a line-ending script run.

The hidden words are pinned per case (task-12 addendum): opacity 0 inline,
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
``tests/fixtures/export_fidelity`` by prefix (PLAN-CORRECTIONS C4).
"""

from __future__ import annotations

import functools
import io
import json
import shutil
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
    reference_text_loss,
    requires_huashu_sidecar,
    requires_node,
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
# The keys Task 12 adds (the brief's counts, and the addendum's captureMs, hiddenText, target).
ADDED_SUMMARY_KEYS = ("text", "shapes", "lines", "tables", "captureMs", "hiddenText", "target")
# The brief's `pseudo` count is the existing pseudoElements (task-12 addendum).
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


# The pinned hiddenText cases (task-12 addendum; Task 6 review). Each hidden
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

# A one-line title that text-overflow: ellipsis cuts inside a word (R11e).
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
# draws the control's box only: real, visible text loss.
SELECT_WORD = "Liquidityoption"
SELECT_DOCUMENT = _case_document(
    f'<div class="slide">{LEAD}<select style="font-size: 20px;">'
    f"<option>{SELECT_WORD}</option></select></div>"
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

# A slide realm that lies about the text a reader of it sees: innerText
# returns a decoy, and both querySelectorAll copies find nothing, so a reference
# read through the page's own accessors would hold the decoy and the SVG's
# label. It publishes on document.title what it replaced and what a reader
# then sees.
HOSTILE_DECOY = "Forgedword decoy"
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
HOSTILE_TEXT_DOCUMENT = _case_document(
    HOSTILE_SLIDE.format(script=HOSTILE_SCRIPT % {"decoy": HOSTILE_DECOY, "body": "false"})
)
HOSTILE_BODY_DOCUMENT = _case_document(
    HOSTILE_SLIDE.format(script=HOSTILE_SCRIPT % {"decoy": HOSTILE_DECOY, "body": "true"})
)
BENIGN_DOCUMENT = _case_document(HOSTILE_SLIDE.format(script=BENIGN_SCRIPT))
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
        """The task-12 addendum's case, verbatim: U+00B9 in the reference, "1" + U+2060 emitted."""
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
            "the brief's `pseudo` count is the existing pseudoElements (task-12 addendum)"
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
        """The brief's case: corpus slide 03 alone, its chart and icons captured, nothing lost."""
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
        """GUARD (passes before Task 12): the harness reference never held it."""
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
    """Characters a ``text-overflow: ellipsis`` hides are hidden text, not lost text (R11e)."""

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
        _only_summary(select_export)
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


# ---------------------------------------------------------------------------
# The harness's text-loss oracle (scripts/export_fidelity/run.py), no browser
# ---------------------------------------------------------------------------


class TestHarnessOracle:
    """``check_text_loss`` over decks python-pptx builds, so each case is exact."""

    def test_a_deck_one_slide_short_reports_all_of_the_missing_slides_words(self) -> None:
        """GUARD (passes before Task 12): the reference's second slide has no slide."""
        pptx = _deck_of_texts([["Alpha Bravo"]])
        assert reference_text_loss(pptx, ["Alpha Bravo", "Charlie Delta"]) == [
            [],
            ["Charlie", "Delta"],
        ]

    def test_without_hidden_text_the_oracle_is_unchanged(self) -> None:
        """GUARD (passes before Task 12): the three-argument call the support helpers make."""
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
        """The task-12 addendum's case, verbatim, for the harness's ``_normalise_text``."""
        pptx = _deck_of_texts([[f"Revenue grew1{WORD_JOINER}"]])
        assert reference_text_loss(pptx, ["Revenue grew¹"]) == [[]]


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


# ---------------------------------------------------------------------------
# The harness reads the summaries (PLAN-CORRECTIONS C8)
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
        # export_pptx sets both in os.environ; the context restores them.
        monkeypatch.setenv("HUASHU_PIPELINE_ENABLED", "1")
        monkeypatch.setenv("TELLR_EXPORT_ENGINE", "snapshot")
        with teed_stderr() as buffer:
            pptx_path = harness.export_pptx(
                {"title": "harness deck"}, paths, out_dir, engine="snapshot"
            )
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
        """GUARD (passes before Task 12): the reference's fourth slide has none in the deck."""
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
            monkeypatch.setenv("TELLR_EXPORT_ENGINE", "snapshot")
            fidelity_harness().export_pptx(
                {"title": "harness deck"}, [document], tmp_path, engine="snapshot", target="gslides"
            )
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
        ellipsis, and the joined superscript, exported with the snapshot
        engine for PowerPoint.
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
        # main() sets both in os.environ; monkeypatch restores them.
        monkeypatch.setenv("HUASHU_PIPELINE_ENABLED", "1")
        monkeypatch.setenv("TELLR_EXPORT_ENGINE", "snapshot")
        monkeypatch.setattr(
            sys,
            "argv",
            ["run.py", str(fixture_dir), "--out", str(out_dir), "--engine", "snapshot"],
        )

        assert fidelity_harness().main() == 0

        lost = json.loads((out_dir / "text_loss.json").read_text(encoding="utf-8"))
        assert lost == {}, f"the harness reports hidden or joined words missing: {lost}"
        assert "Text missing from the export: none" in capsys.readouterr().out
        recorded = json.loads((out_dir / "summaries.json").read_text(encoding="utf-8"))
        assert len(recorded) == len(bodies), recorded
