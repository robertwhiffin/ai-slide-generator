"""Snapshot engine: line spacing, first-line placement and metric calibration.

Spec §3 Text "Spacing" and "Metrics", and the calibration record
(``scripts/export_fidelity/CALIBRATION.md`` A1, A2). The snapshot engine writes text so
that PowerPoint and Google Slides lay it out as the browser did:

* **Line spacing against the renderers' single spacing.** PowerPoint and Google
  Slides draw 100% spacing at 1.2 x the font size, whatever the font's metrics
  (``scripts/export_fidelity/CALIBRATION.md``). In a block the browser laid out
  on more than one line:

  - a line height up to 1.2 x the size is ``<a:lnSpc><a:spcPct>`` of
    ``cssLineHeight / (1.2 x fontSize)``, the lines soft breaks in one
    paragraph;
  - a looser one is single spacing (``spcPct`` 100%) with every line a
    paragraph of its own, and the leading beyond single,
    ``(cssLineHeight - 1.2 x fontSize) x 0.75`` pt, as ``<a:spcBef>`` on the
    lines after the first. Above 100% the renderers disagree on where the first
    line goes; with single spacing and space before they agree.

  Line spacing is never exact points: Drive converts ``spcPts`` in
  ``<a:lnSpc>`` into a percentage of the natural line height and mis-scales it.
  Single-line text has no ``<a:lnSpc>`` at all (upstream pitfall 6).
* **First-line placement.** The text box sits ``firstLineOffsetPx`` above the
  browser's first glyph top: ``A x (pct/100 - 1) x 1.2 x sizePx + B x sizePx +
  C x ascentPx``, where ``pct`` is the first paragraph's ``spcPct`` (at most
  100; 100 without one) and ``ascentPx`` the browser's ascent for its largest
  run, its glyph top to its baseline. ``A``, ``B`` and ``C`` (``FIRST_LINE_A``,
  ``FIRST_LINE_B``, ``FIRST_LINE_C`` in ``emit_text.cjs``) are fitted against
  PowerPoint and Google Slides renders.
* **Optical-size width compensation (A1).** The browser draws DM Sans at its
  automatic optical size, so a title uses the narrow large-size cut, while
  PowerPoint and Google Slides draw the static opsz-14 cut, about 10% wider.
  A run whose two widths differ by more than 0.5% gets a ``charSpacing`` delta
  so that its exported width equals the browser's. A 13 px run (opsz 13, next to
  14) and a font with no optical-size axis (Arial) keep their CSS tracking.
* **Superscript and subscript size (A2).** The renderers shrink a superscript
  or subscript run on top of the size the browser already reduced, so the
  emitter writes the browser's size divided by the calibrated shrink factor.

* **Render checks (A3),** pinned as the renders showed them: PowerPoint opened
  the calibration deck without a repair prompt although pptxgenjs repeats
  ``<a:pPr>`` inside a paragraph, so the repeats are identical; neither
  renderer outlines a shape with no border, so an unbordered shape keeps its
  fill-less ``<a:ln>``; both justify a line to the full box, slack included,
  so justified text is written left-aligned with the browser's line breaks.

Every expectation comes from the browser's own rendering of the exported
document: the ascent and the opsz-14 cut width are read with offscreen probes
in the page (``browser_probes``, ``browser_ascent``), and the line boxes and
computed style with ``browser_line_boxes`` and ``browser_style``. Each test first guards its
fixture's computed style, so a failure is never fixture drift. Where a test
pins an absence (no delta, no ``<a:lnSpc>``), it also asserts that the same
mechanism is present on a control in the same export, so it cannot pass only
because the mechanism is missing.

**The calibration record.** ``scripts/export_fidelity/CALIBRATION.md`` holds
the chosen constants, each on a line of its own in exactly this form,
optionally as a list item, in backticks or inside a fenced block, and exactly
once::

    FIRST_LINE_A = <number>
    FIRST_LINE_B = <number>
    FIRST_LINE_C = <number>
    SUPERSCRIPT_SIZE_FACTOR = <number>
    SUBSCRIPT_SIZE_FACTOR = <number>      (only when subscript needs its own)
    GOOGLE_LINE_GROWTH_PER_PX = <number>

``SUPERSCRIPT_SIZE_FACTOR`` is the fraction of a superscript run's emitted size
that the renderers draw it at (0 < factor <= 1), so rendered = emitted x
factor. A subscript run uses ``SUBSCRIPT_SIZE_FACTOR`` when the record holds
one, and ``SUPERSCRIPT_SIZE_FACTOR`` otherwise. The emitter defines each
constant as ``const NAME = <number>;``: the three ``FIRST_LINE_*`` in
``emit_text.cjs``, each script factor once in ``emit_text.cjs`` or
``emit_typography.cjs`` (``SUBSCRIPT_SIZE_FACTOR`` exactly when the record
holds it). ``GOOGLE_LINE_GROWTH_PER_PX`` is how far Google Slides lowers a
line per px its largest written run exceeds the line's other runs (the deck
written for Google Slides), defined once in ``emit_text.cjs``. The pins fail when the code
and the record disagree. The placement
and script-size tests read the record too, so the constants must also be the
ones the export applies.

Corpus slides come from ``tests/fixtures/export_fidelity`` by prefix
(``corpus_document``): 01 holds the 64 px cover title (``line-height: 1.08``,
two lines split by a ``<br>``) and the 13 px eyebrow; 09 holds the footnote
marker ``<sup>1</sup>``. The custom metrics slide holds the subscript,
"H<sub>2</sub>O".

Gating matches the sibling export suites: the export tests need node, the
extracted sidecar ``node_modules`` and a local Chrome/Chromium. The optical-size
tests also need the deck's Google Fonts import, which serves DM Sans with its
``opsz`` axis; they guard it explicitly. The calibration pins read files only.
"""

from __future__ import annotations

import functools
import math
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from lxml import etree

from src.services import pptx_from_html_huashu
from tests.fixtures.export_snapshot_support import (
    DECK_CSS,
    NAMESPACES,
    PERCENT_UNITS,
    REPO_ROOT,
    Run,
    Shape,
    browser_ascent,
    browser_line_boxes,
    browser_probes,
    browser_rect,
    browser_style,
    browser_text,
    corpus_document,
    cut_widths,
    export_corpus,
    export_slides,
    powerpoint_tracking_px,
    requires_huashu_sidecar,
    slide_document,
    slide_shape_elements,
    slide_shapes,
    slide_xml,
    text_shapes,
)

SIDECAR_DIR = Path(pptx_from_html_huashu.SIDECAR_DIR)
EMIT_TEXT_MODULE = SIDECAR_DIR / "emit_text.cjs"
EMIT_TYPOGRAPHY_MODULE = SIDECAR_DIR / "emit_typography.cjs"
CALIBRATION_RECORD = REPO_ROOT / "scripts" / "export_fidelity" / "CALIBRATION.md"

FIRST_LINE_CONSTANTS = ("FIRST_LINE_A", "FIRST_LINE_B", "FIRST_LINE_C")
SUPERSCRIPT_FACTOR = "SUPERSCRIPT_SIZE_FACTOR"
# Recorded only when the renders show subscript needs a factor of its own.
SUBSCRIPT_FACTOR = "SUBSCRIPT_SIZE_FACTOR"
GOOGLE_LINE_GROWTH = "GOOGLE_LINE_GROWTH_PER_PX"
# A decimal literal as Markdown or JavaScript writes it.
NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"

PT_PER_PX = 0.75
HUNDREDTHS = 100
# PowerPoint's and Google Slides' single spacing, as a multiple of the font size.
RENDERER_SINGLE_SPACING_EM = 1.2
# spcPct = round(cssLineHeight / (1.2 x fontSize) x 100000) +/- 500.
SPC_PCT_TOLERANCE = 500
# A paragraph without <a:lnSpc> is single spacing.
SINGLE_SPACING_PCT = 100.0
# spcBef is hundredths of a point; one unit is the rounding pptxgenjs does.
SPACE_BEFORE_TOLERANCE_HUNDREDTHS = 1.0
# spc and sz are hundredths of a point; one unit is the rounding pptxgenjs does.
SPC_TOLERANCE_HUNDREDTHS = 1.0
SIZE_TOLERANCE_HUNDREDTHS = 1.0
# The emitted box offset is exact up to the snapshot's 0.1% rounding of pct and
# the EMU rounding of the offset.
PLACEMENT_TOLERANCE_PX = 0.5
# A1: compensate when the two cuts differ by more than 0.5%; the run width the
# emitted tracking implies is within 1% of the browser's.
OPTICAL_SIZE_THRESHOLD = 0.005
WIDTH_TOLERANCE = 0.01
# The optical size of the static DM Sans cut PowerPoint and Google Slides draw.
EXPORT_CUT_OPTICAL_SIZE = 14

# ---------------------------------------------------------------------------
# Corpus slides, exported once per module in this order
# ---------------------------------------------------------------------------

CORPUS_PREFIXES = ("01", "09")

# Fixture 01: the cover title, 64 px DM Sans 600 at line-height 1.08 and
# letter-spacing -.01em, two lines split by a <br>; and the 13 px eyebrow
# (700, letter-spacing .16em, uppercase), one line.
COVER_TITLE = "h1.dk-title"
COVER_TITLE_SIZE_PX = 64
COVER_TITLE_WEIGHT = 600
COVER_TITLE_LINE_HEIGHT = 1.08
COVER_TITLE_LINES = ("Meridian Components", "FY2024 financial review")
COVER_EYEBROW = ".dk-eyebrow"
COVER_EYEBROW_SIZE_PX = 13
COVER_EYEBROW_TEXT = "FY2024 FINANCIAL REVIEW"  # as painted, after text-transform

# Fixture 09's accent-bar paragraph: 17 px at line-height 1.5, looser than the
# renderers' single spacing (25.5 px against 20.4 px), on more than one line.
ACCENT_BAR = ".dk-accent-bar"
ACCENT_BAR_SIZE_PX = 17
ACCENT_BAR_LINE_HEIGHT = 1.5
ACCENT_BAR_START = "Gross profit grew"

# Fixture 09: "gross profit<sup>1</sup>" in the third .dk-list item (20 px).
FOOTNOTE_ITEM = ".dk-list li"
FOOTNOTE_ITEM_INDEX = 2
FOOTNOTE_ITEM_SIZE_PX = 20
FOOTNOTE_MARKER_SELECTOR = ".dk-list sup"
FOOTNOTE_LINE = "Operating leverage"
FOOTNOTE_MARKER = "1"

# ---------------------------------------------------------------------------
# The custom metrics slide, exported once per module
# ---------------------------------------------------------------------------

# A single-line .dk-title (line-height 1.08, one line: pitfall 6) and a
# two-line paragraph as its control (20 px at line-height 1.45, so looser than
# single: its lines are paragraphs with space before); a 13 px body paragraph
# with CSS tracking; one 64 px headline style in DM Sans and in Arial (the DM
# Sans twin is the control the optical-size compensation must reach); and a
# 20 px paragraph with a subscript.
ONE_LINE_TITLE_TEXT = "Revenue grew in every segment"
WRAPPED_LINES = ("Margin rose in every quarter", "and cash conversion held")
BODY_13_TEXT = "Thirteen pixel body copy keeps its own tracking"
DM_SANS_HEADLINE_TEXT = "DM Sans headline"
ARIAL_HEADLINE_TEXT = "Arial headline"
CHEMISTRY = "#chemistry"
CHEMISTRY_SIZE_PX = 20
CHEMISTRY_TEXT = "Water is H2O"
SUBSCRIPT_SELECTOR = "#chemistry sub"
SUBSCRIPT_TEXT = "2"
# Placed absolutely in the right half, so nothing above moves: a justified
# paragraph (16 px, line-height 1.45), a box with a background and no border,
# and the same box with a border as its control (A3).
JUSTIFIED = "#justified"
JUSTIFIED_TEXT = (
    "Gross profit grew faster than revenue in every quarter, because the pricing "
    "actions held while input costs eased and operating expenses grew more slowly."
)
PLAIN_BOX = "#plain-box"
BORDERED_BOX = "#bordered-box"
METRICS_SLIDE = (
    '<div class="slide">'
    f'<h2 id="one-line-title" class="dk-title">{ONE_LINE_TITLE_TEXT}</h2>'
    '<p id="wrapped" style="font-size: 20px; line-height: 1.45; margin: 0 0 16px;">'
    f"{WRAPPED_LINES[0]}<br>{WRAPPED_LINES[1]}</p>"
    '<p id="body-13" style="font-size: 13px; letter-spacing: 0.02em; margin: 0 0 16px;">'
    f"{BODY_13_TEXT}</p>"
    '<p id="dm-sans-headline" style="font-size: 64px; letter-spacing: -0.01em; '
    f'line-height: 1.1; margin: 0;">{DM_SANS_HEADLINE_TEXT}</p>'
    '<p id="arial-headline" style="font-family: Arial; font-size: 64px; '
    f'letter-spacing: -0.01em; line-height: 1.1; margin: 0;">{ARIAL_HEADLINE_TEXT}</p>'
    f'<p id="chemistry" style="font-size: {CHEMISTRY_SIZE_PX}px; margin: 16px 0 0;">'
    f"Water is H<sub>{SUBSCRIPT_TEXT}</sub>O</p>"
    '<p id="justified" style="position: absolute; left: 760px; top: 80px; width: 400px; '
    f'margin: 0; font-size: 16px; line-height: 1.45; text-align: justify;">{JUSTIFIED_TEXT}</p>'
    '<div id="plain-box" style="position: absolute; left: 760px; top: 420px; width: 200px; '
    'height: 60px; background: #E4E4E4;"></div>'
    '<div id="bordered-box" style="position: absolute; left: 760px; top: 520px; width: 200px; '
    'height: 60px; box-sizing: border-box; background: #E4E4E4; border: 2px solid #1B3139;">'
    "</div>"
    "</div>"
)

# ---------------------------------------------------------------------------
# Exports and lookups
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def corpus_pptx() -> Iterator[bytes]:
    """Corpus slides 01 and 09, exported once through the snapshot engine."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        pptx, failures = export_corpus(
            list(CORPUS_PREFIXES), monkeypatch=monkeypatch
        )
    assert failures == [], f"the export rejected a corpus slide: {failures}"
    yield pptx


@pytest.fixture(scope="module")
def metrics_pptx() -> Iterator[bytes]:
    """The custom metrics slide, exported once through the snapshot engine."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        pptx, failures = export_slides(
            [METRICS_SLIDE], css=DECK_CSS, monkeypatch=monkeypatch
        )
    assert failures == [], f"the export rejected the metrics slide: {failures}"
    yield pptx


@pytest.fixture(scope="module")
def corpus_gslides_pptx() -> Iterator[bytes]:
    """Corpus slides 01 and 09, exported once for Google Slides (``target="gslides"``)."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        pptx, failures = export_corpus(
            list(CORPUS_PREFIXES), monkeypatch=monkeypatch, target="gslides"
        )
    assert failures == [], f"the export rejected a corpus slide: {failures}"
    yield pptx


@pytest.fixture(scope="module")
def metrics_gslides_pptx() -> Iterator[bytes]:
    """The custom metrics slide, exported once for Google Slides (``target="gslides"``)."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        pptx, failures = export_slides(
            [METRICS_SLIDE], css=DECK_CSS, monkeypatch=monkeypatch, target="gslides"
        )
    assert failures == [], f"the export rejected the metrics slide: {failures}"
    yield pptx


# The module fixture holding each source's deck, per target.
SOURCE_DECKS = {
    ("cover", "pptx"): "corpus_pptx",
    ("cover", "gslides"): "corpus_gslides_pptx",
    ("metrics", "pptx"): "metrics_pptx",
    ("metrics", "gslides"): "metrics_gslides_pptx",
}


def _metrics_document() -> str:
    """The document ``metrics_pptx`` exported, with its slide id."""
    return slide_document(METRICS_SLIDE, css=DECK_CSS, slide_id="snapshot-1")


# The pages are settled and deterministic, so one reading serves every test.
@functools.cache
def _style(document: str, selector: str, index: int = 0) -> dict[str, str]:
    return browser_style(document, selector, index)


@functools.cache
def _line_boxes(document: str, selector: str) -> tuple[dict, ...]:
    return tuple(browser_line_boxes(document, selector))


@functools.cache
def _ascent(document: str, family: str, weight: int, size_px: float, style: str) -> float:
    return browser_ascent(document, family, weight, size_px, style)


def _sources(
    request: pytest.FixtureRequest, source: str, target: str = "pptx"
) -> tuple[str, bytes, int]:
    """(document, pptx, slide index) of a source, "cover" (fixture 01) or "metrics", in the
    deck written for ``target``."""
    assert (source, target) in SOURCE_DECKS, f"unknown source {source!r} or target {target!r}"
    document = corpus_document("01") if source == "cover" else _metrics_document()
    return document, request.getfixturevalue(SOURCE_DECKS[(source, target)]), 0


def _runs(shape: Shape) -> list[Run]:
    return [run for para in shape.paras for run in para.runs]


def _describe_run(run: Run) -> str:
    return (
        f"{run.text!r}: typeface={run.typeface!r} sz={run.size_pt} spc={run.spc_pt} "
        f"baseline={run.baseline_offset}"
    )


def _describe(shapes: list[Shape]) -> str:
    lines = []
    for position, shape in enumerate(shapes):
        if shape.kind != "text":
            continue
        spacing = [para.line_spacing_pct for para in shape.paras]
        lines.append(
            f"  [{position}] text box y={shape.y:.2f} {shape.text[:60]!r} lnSpc%={spacing}"
        )
        lines.extend(f"      {_describe_run(run)}" for run in _runs(shape))
    return "\n".join(lines) or "  (no text boxes)"


def _box_reading(shapes: list[Shape], text: str) -> tuple[int, Shape]:
    """(spTree index, shape) of the one text box whose text is exactly ``text``."""
    matches = [
        (position, shape)
        for position, shape in enumerate(shapes)
        if shape.kind == "text" and shape.text == text
    ]
    assert len(matches) == 1, (
        f"expected exactly one text box reading {text!r}, got {len(matches)}:\n{_describe(shapes)}"
    )
    return matches[0]


def _box_containing(shapes: list[Shape], fragment: str) -> Shape:
    """The one text box whose text contains ``fragment``."""
    matches = text_shapes(shapes, fragment)
    assert len(matches) == 1, (
        f"expected exactly one text box containing {fragment!r}, got {len(matches)}:\n"
        f"{_describe(shapes)}"
    )
    return matches[0]


def _run(shape: Shape, text: str) -> Run:
    """The one run of ``shape`` whose text, stripped, is ``text``."""
    matches = [run for run in _runs(shape) if run.text.strip() == text]
    assert len(matches) == 1, (
        f"expected exactly one run reading {text!r} in the box {shape.text!r}, got "
        f"{len(matches)}:\n" + "\n".join(f"  {_describe_run(run)}" for run in _runs(shape))
    )
    return matches[0]


def _emitted_lines(shape: Shape) -> list[list[Run]]:
    """The box's runs grouped into its lines: a paragraph or an ``<a:br/>`` starts one."""
    lines: list[list[Run]] = []
    for para in shape.paras:
        for position, run in enumerate(para.runs):
            if position == 0 or run.soft_break_before:
                lines.append([])
            lines[-1].append(run)
    return lines


def _px(value: str) -> float:
    """A computed CSS length in px ("69.12px") as a number."""
    assert value.endswith("px"), f"expected a px length, got {value!r}"
    return float(value.removesuffix("px"))


def _guard_style(document: str, selector: str, index: int = 0, **expected: str) -> dict[str, str]:
    style = _style(document, selector, index)
    drift = {name: (style[name], value) for name, value in expected.items() if style[name] != value}
    assert not drift, f"fixture drift: {selector}[{index}]'s computed (got, expected): {drift}"
    return style


def _guard_family(style: str, family: str, selector: str) -> None:
    first = style.split(",")[0].strip().strip("\"'")
    assert first == family, f"fixture drift: {selector}'s font-family is {style!r}, not {family}"


# ---------------------------------------------------------------------------
# The calibration record and the emitter's constants
# ---------------------------------------------------------------------------


def _recorded_values(name: str) -> list[str]:
    """Every ``NAME = <number>`` line ``CALIBRATION.md`` holds for ``name``, as written."""
    record = CALIBRATION_RECORD.relative_to(REPO_ROOT)
    assert CALIBRATION_RECORD.is_file(), (
        f"{record} does not exist: the text calibration records the chosen constants there, "
        f"each on a line of its own as `{name} = <number>`"
    )
    pattern = re.compile(
        rf"^[ \t]*(?:[-*][ \t]+)?`?{name}`?[ \t]*=[ \t]*`?({NUMBER})`?[ \t]*$", re.MULTILINE
    )
    return pattern.findall(CALIBRATION_RECORD.read_text(encoding="utf-8"))


def _recorded_value(name: str) -> float:
    """The value ``CALIBRATION.md`` records for ``name``, on its one ``NAME = <number>`` line."""
    values = _recorded_values(name)
    assert len(values) == 1, (
        f"{CALIBRATION_RECORD.relative_to(REPO_ROOT)} must record {name} exactly once, on a "
        f"line of its own as `{name} = <number>`; found {len(values)}: {values}"
    )
    return float(values[0])


def _recorded_value_if_present(name: str) -> float | None:
    """The value ``CALIBRATION.md`` records for an optional ``name``; None when it holds none."""
    values = _recorded_values(name)
    assert len(values) <= 1, (
        f"{CALIBRATION_RECORD.relative_to(REPO_ROOT)} must record {name} at most once, on a "
        f"line of its own as `{name} = <number>`; found {len(values)}: {values}"
    )
    return float(values[0]) if values else None


def _script_factor(baseline: str) -> tuple[str, float]:
    """(name, value) of the recorded shrink factor for a 'super' or 'sub' run.

    Subscript takes ``SUBSCRIPT_SIZE_FACTOR`` when the record holds one, and
    ``SUPERSCRIPT_SIZE_FACTOR`` otherwise.
    """
    if baseline == "sub":
        subscript = _recorded_value_if_present(SUBSCRIPT_FACTOR)
        if subscript is not None:
            return SUBSCRIPT_FACTOR, subscript
    return SUPERSCRIPT_FACTOR, _recorded_value(SUPERSCRIPT_FACTOR)


def _script_factor_modules() -> tuple[Path, ...]:
    """The emitter modules a script-size factor may be defined in."""
    return (EMIT_TEXT_MODULE, EMIT_TYPOGRAPHY_MODULE)


def _emitter_definitions(name: str, modules: tuple[Path, ...]) -> list[tuple[str, str]]:
    """(module, value) of every ``const NAME = <number>;`` among ``modules``."""
    pattern = re.compile(rf"^[ \t]*const[ \t]+{name}[ \t]*=[ \t]*({NUMBER})[ \t]*;", re.MULTILINE)
    return [
        (module.name, value)
        for module in modules
        for value in pattern.findall(module.read_text(encoding="utf-8"))
    ]


def _emitter_constant(name: str, modules: tuple[Path, ...]) -> float:
    """The value of the one ``const NAME = <number>;`` among ``modules``."""
    found = _emitter_definitions(name, modules)
    names = " or ".join(module.name for module in modules)
    assert len(found) == 1, (
        f"the emitter must define `const {name} = <number>;` exactly once in {names}; "
        f"found {len(found)}: {found}"
    )
    return float(found[0][1])


class TestCalibratedConstants:
    @pytest.mark.parametrize("name", FIRST_LINE_CONSTANTS)
    def test_first_line_constant_is_the_recorded_calibration(self, name: str) -> None:
        """``FIRST_LINE_A`` and ``FIRST_LINE_B`` in ``emit_text.cjs`` equal ``CALIBRATION.md``.

        The constants are fitted against PowerPoint and Google Slides renders
        of the probe deck and written into the record with both renderers'
        residuals. Editing one without the other fails here.
        """
        recorded = _recorded_value(name)
        emitted = _emitter_constant(name, (EMIT_TEXT_MODULE,))

        assert emitted == recorded, (
            f"emit_text.cjs has {name} = {emitted:g}; CALIBRATION.md records {recorded:g}"
        )

    def test_superscript_size_factor_is_the_recorded_calibration(self) -> None:
        """A2: ``SUPERSCRIPT_SIZE_FACTOR`` in the emitter equals ``CALIBRATION.md``.

        It is the renderers' own superscript shrink: the fraction of the
        emitted size they draw a superscript run at. So it lies in (0, 1].
        """
        recorded = _recorded_value(SUPERSCRIPT_FACTOR)
        emitted = _emitter_constant(SUPERSCRIPT_FACTOR, _script_factor_modules())

        assert emitted == recorded, (
            f"the emitter has {SUPERSCRIPT_FACTOR} = {emitted:g}; CALIBRATION.md records "
            f"{recorded:g}"
        )
        assert 0 < recorded <= 1, (
            f"{SUPERSCRIPT_FACTOR} = {recorded:g} is not a shrink: it must lie in (0, 1]"
        )

    def test_google_line_growth_per_px_is_the_recorded_calibration(self) -> None:
        """``GOOGLE_LINE_GROWTH_PER_PX`` in ``emit_text.cjs`` equals ``CALIBRATION.md``.

        The deck written for Google Slides caps a script run at its line's
        size plus the browser's growth of the line over this constant: the px
        Google lowers a line per px its largest written run exceeds the line's
        other runs, measured at 20 and 40 px. It is a fraction of a px per px.
        """
        recorded = _recorded_value(GOOGLE_LINE_GROWTH)
        emitted = _emitter_constant(GOOGLE_LINE_GROWTH, (EMIT_TEXT_MODULE,))

        assert emitted == recorded, (
            f"emit_text.cjs has {GOOGLE_LINE_GROWTH} = {emitted:g}; CALIBRATION.md records "
            f"{recorded:g}"
        )
        assert 0 < recorded <= 1, (
            f"{GOOGLE_LINE_GROWTH} = {recorded:g} must lie in (0, 1]: a line is lowered by "
            "no more than the excess that lowers it"
        )

    def test_subscript_size_factor_is_the_recorded_calibration_or_absent(self) -> None:
        """A2: ``SUBSCRIPT_SIZE_FACTOR`` exists in the emitter exactly when ``CALIBRATION.md``
        records it, with the recorded value.

        The record holds it only when the renders show subscript needs a shrink
        of its own; otherwise subscript uses ``SUPERSCRIPT_SIZE_FACTOR``, and an
        emitter constant the record does not hold would size subscripts by an
        uncalibrated value. When recorded it is a shrink, so it lies in (0, 1].
        """
        recorded = _recorded_value_if_present(SUBSCRIPT_FACTOR)
        if recorded is None:
            defined = _emitter_definitions(SUBSCRIPT_FACTOR, _script_factor_modules())
            assert not defined, (
                f"CALIBRATION.md records no {SUBSCRIPT_FACTOR}, so subscript uses "
                f"{SUPERSCRIPT_FACTOR}; the emitter defines one anyway: {defined}"
            )
            return
        emitted = _emitter_constant(SUBSCRIPT_FACTOR, _script_factor_modules())

        assert emitted == recorded, (
            f"the emitter has {SUBSCRIPT_FACTOR} = {emitted:g}; CALIBRATION.md records {recorded:g}"
        )
        assert 0 < recorded <= 1, (
            f"{SUBSCRIPT_FACTOR} = {recorded:g} is not a shrink: it must lie in (0, 1]"
        )


# ---------------------------------------------------------------------------
# Percentage line spacing (upstream pitfall 6)
# ---------------------------------------------------------------------------


def _line_spacing_elements(element: etree._Element) -> list[etree._Element]:
    return element.findall(".//a:lnSpc", NAMESPACES)


def _space_before(paragraph: etree._Element) -> float | None:
    """A paragraph's ``<a:spcBef><a:spcPts>`` in hundredths of a point; None without one."""
    points = paragraph.find("a:pPr/a:spcBef/a:spcPts", NAMESPACES)
    return None if points is None else float(points.get("val"))


def _describe_spacing(elements: list[etree._Element]) -> str:
    return ", ".join(etree.tostring(element, encoding="unicode") for element in elements) or "none"


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotLineSpacing:
    def test_tight_title_spacing_is_a_percentage_of_the_renderers_single_spacing(
        self, corpus_pptx: bytes
    ) -> None:
        """Fixture 01's cover title: 64 px DM Sans 600 at ``line-height: 1.08``, two lines.

        Its line height (69.12 px) is tighter than the renderers' single
        spacing, 1.2 x 64 = 76.8 px, so the title stays one paragraph with its
        lines split by a soft break (``<a:br/>``), and that paragraph carries
        ``<a:lnSpc><a:spcPct>`` equal to round(1.08 x 64 / (1.2 x 64) x 100000)
        = 90000, within 500. PowerPoint and Google Slides then set the lines
        69.12 px apart, as the browser did. A percentage of the font's own
        natural line height (83 px) would set them 63.9 px apart in both.
        """
        document = corpus_document("01")
        style = _guard_style(
            document, COVER_TITLE, fontSize=f"{COVER_TITLE_SIZE_PX}px", fontWeight="600"
        )
        _guard_family(style["fontFamily"], "DM Sans", COVER_TITLE)
        line_height_px = COVER_TITLE_LINE_HEIGHT * COVER_TITLE_SIZE_PX
        assert math.isclose(_px(style["lineHeight"]), line_height_px, abs_tol=0.005), (
            f"fixture drift: the cover title's line-height is {style['lineHeight']}, expected "
            f"{line_height_px:.2f}px"
        )
        lines = [line["text"] for line in _line_boxes(document, COVER_TITLE)]
        assert lines == list(COVER_TITLE_LINES), f"fixture drift: the title renders {lines}"
        single = RENDERER_SINGLE_SPACING_EM * COVER_TITLE_SIZE_PX
        expected = round(line_height_px / single * PERCENT_UNITS)
        _, box = _box_reading(slide_shapes(corpus_pptx, 0), "\n".join(COVER_TITLE_LINES))

        assert len(box.paras) == 1, (
            f"a line height up to single keeps the title's lines in one paragraph with soft "
            f"breaks; the box has {len(box.paras)} paragraphs: {box.text!r}"
        )
        breaks = [run.text for run in box.paras[0].runs if run.soft_break_before]
        assert breaks == [COVER_TITLE_LINES[1]], (
            f"the title's second line must follow a soft break (<a:br/>); the runs after one "
            f"are {breaks}"
        )
        spacing = box.paras[0].line_spacing_pct
        assert (
            spacing is not None
            and abs(spacing * PERCENT_UNITS / 100 - expected) <= SPC_PCT_TOLERANCE
        ), (
            f"the cover title's paragraph must carry spcPct {expected} (1.08 x 64 / (1.2 x 64)), "
            f"within {SPC_PCT_TOLERANCE}; it carries {spacing} (as %, None for no spcPct)"
        )

    @pytest.mark.parametrize(
        ("source", "selector", "start", "size_px", "line_height"),
        [
            pytest.param("metrics", "#wrapped", WRAPPED_LINES[0], 20, 1.45, id="metrics-1.45"),
            pytest.param(
                "corpus-09",
                ACCENT_BAR,
                ACCENT_BAR_START,
                ACCENT_BAR_SIZE_PX,
                ACCENT_BAR_LINE_HEIGHT,
                id="fixture-09-accent-bar-1.5",
            ),
        ],
    )
    def test_loose_lines_are_single_spaced_paragraphs_with_space_before(
        self,
        request: pytest.FixtureRequest,
        source: str,
        selector: str,
        start: str,
        size_px: int,
        line_height: float,
    ) -> None:
        """A block whose line height is looser than the renderers' single spacing.

        * the metrics slide's two-line paragraph, 20 px at ``line-height: 1.45``
          (29 px against 24 px);
        * fixture 09's accent-bar paragraph, 17 px at ``line-height: 1.5``
          (25.5 px against 20.4 px).

        Every line the browser drew is a paragraph of its own, in order, each at
        single spacing (``<a:spcPct val="100000">``). The first carries no
        ``<a:spcBef>``; every later one carries the leading beyond single,
        (cssLineHeight - 1.2 x fontSize) x 0.75 pt (3.75 pt; 3.83 pt), within one
        hundredth of a point. Written as ``spcPct`` above 100%, the first line
        sits where each renderer puts the extra leading, and they disagree.
        """
        if source == "metrics":
            document, pptx, slide = _metrics_document(), request.getfixturevalue("metrics_pptx"), 0
        else:
            document, pptx, slide = corpus_document("09"), request.getfixturevalue("corpus_pptx"), 1
        style = _guard_style(document, selector, fontSize=f"{size_px}px")
        line_height_px = line_height * size_px
        assert math.isclose(_px(style["lineHeight"]), line_height_px, abs_tol=0.005), (
            f"fixture drift: {selector}'s line-height is {style['lineHeight']}, expected "
            f"{line_height_px:.2f}px"
        )
        lines = [line["text"] for line in _line_boxes(document, selector)]
        assert len(lines) > 1 and lines[0].startswith(start), (
            f"fixture drift: {selector} renders {lines}"
        )
        box = _box_containing(slide_shapes(pptx, slide), start)
        expected = (line_height_px - RENDERER_SINGLE_SPACING_EM * size_px) * PT_PER_PX * HUNDREDTHS
        element = next(
            element
            for shape, element in zip(slide_shapes(pptx, slide), slide_shape_elements(pptx, slide))
            if shape.kind == "text" and start in shape.text
        )
        befores = [_space_before(paragraph) for paragraph in element.iterfind(".//a:p", NAMESPACES)]

        assert box.text.split("\n") == lines, (
            f"the box's paragraphs read {box.text.split(chr(10))}; the browser's lines are {lines}"
        )
        assert len(box.paras) == len(lines), (
            f"every line must be a paragraph of its own: {len(box.paras)} paragraphs for "
            f"{len(lines)} lines"
        )
        not_single = [para.line_spacing_pct for para in box.paras if para.line_spacing_pct != 100]
        assert not not_single, (
            f"every line's paragraph must be single spacing (spcPct 100%); these are not: "
            f"{[para.line_spacing_pct for para in box.paras]}"
        )
        assert befores[0] is None, f"the first line carries space before: {befores}"
        wrong = [
            value
            for value in befores[1:]
            if value is None or abs(value - expected) > SPACE_BEFORE_TOLERANCE_HUNDREDTHS
        ]
        assert not wrong, (
            f"every line after the first must carry spcBef {expected:.1f} hundredths of a point "
            f"(({line_height_px:g} - 1.2 x {size_px}) x 0.75 x 100), within "
            f"{SPACE_BEFORE_TOLERANCE_HUNDREDTHS:g}; they carry {befores[1:]}"
        )

    def test_line_spacing_is_never_exact_points(self, corpus_pptx: bytes) -> None:
        """Fixture 01's slide expresses line spacing as percentages only.

        It carries ``<a:lnSpc>`` (the multi-line cover title needs one), every
        ``<a:lnSpc>`` holds an ``<a:spcPct>``, and no ``<a:lnSpc>`` holds an
        ``<a:spcPts>``: Drive converts exact-point line spacing into a
        percentage of the natural line height and mis-scales it (22.5 pt on
        13.5 pt became 166%). Space before a paragraph is another matter: the
        engine writes a loosely spaced block's leading beyond single as
        ``<a:spcBef><a:spcPts>``, which both renderers honour, so only
        ``<a:lnSpc>`` is held to percentages.
        """
        root = slide_xml(corpus_pptx, 0)
        spacings = _line_spacing_elements(root)

        assert spacings, (
            "fixture 01's slide has no <a:lnSpc> at all: its two-line cover title must carry "
            "percentage line spacing"
        )
        in_points = root.findall(".//a:lnSpc/a:spcPts", NAMESPACES)
        assert not in_points, "the slide writes line spacing in exact points: " + ", ".join(
            f"<a:lnSpc><a:spcPts val={element.get('val')!r}/>" for element in in_points
        )
        not_percent = [
            element for element in spacings if element.find("a:spcPct", NAMESPACES) is None
        ]
        assert not not_percent, (
            "every <a:lnSpc> must hold an <a:spcPct>; these do not: "
            + _describe_spacing(not_percent)
        )

    @pytest.mark.parametrize(
        ("source", "selector", "text", "control_selector", "control_text"),
        [
            pytest.param(
                "cover",
                COVER_EYEBROW,
                COVER_EYEBROW_TEXT,
                COVER_TITLE,
                "\n".join(COVER_TITLE_LINES),
                id="cover-eyebrow",
            ),
            pytest.param(
                "metrics",
                "#one-line-title",
                ONE_LINE_TITLE_TEXT,
                "#wrapped",
                "\n".join(WRAPPED_LINES),
                id="one-line-title-at-1.08",
            ),
        ],
    )
    def test_single_line_text_has_no_line_spacing(
        self,
        request: pytest.FixtureRequest,
        source: str,
        selector: str,
        text: str,
        control_selector: str,
        control_text: str,
    ) -> None:
        """Pitfall 6: text the browser laid out on one line has no ``<a:lnSpc>`` at all.

        * fixture 01's eyebrow, a 13 px label at ``line-height: normal``;
        * a single-line ``.dk-title`` at ``line-height: 1.08``, where a spacing
          derived from the CSS line height would shift the one line it has.

        Line spacing moves a single line's glyphs inside its box, so it must
        stay natural. The control is a multi-line block on the same slide (the
        cover title; a two-line paragraph): it carries ``<a:lnSpc>``, so the
        absence on the single line is the engine's decision, not a missing
        feature.
        """
        document, pptx, slide = _sources(request, source)
        lines = _line_boxes(document, selector)
        assert len(lines) == 1, f"fixture drift: {selector} renders {len(lines)} lines: {lines}"
        control_lines = _line_boxes(document, control_selector)
        assert len(control_lines) > 1, (
            f"fixture drift: the control {control_selector} renders one line: {control_lines}"
        )
        shapes = slide_shapes(pptx, slide)
        elements = slide_shape_elements(pptx, slide)
        control_index, _ = _box_reading(shapes, control_text)
        index, _ = _box_reading(shapes, text)

        assert _line_spacing_elements(elements[control_index]), (
            f"control: the multi-line {control_selector} box carries no <a:lnSpc>, so the "
            f"export writes no line spacing at all:\n{_describe(shapes)}"
        )
        spacing = _line_spacing_elements(elements[index])
        assert not spacing, (
            f"the single-line {selector} box carries line spacing: {_describe_spacing(spacing)}"
        )


# ---------------------------------------------------------------------------
# First-line placement
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotFirstLinePlacement:
    @pytest.mark.parametrize(
        ("source", "selector", "text", "size_px"),
        [
            pytest.param(
                "cover",
                COVER_TITLE,
                "\n".join(COVER_TITLE_LINES),
                COVER_TITLE_SIZE_PX,
                id="cover-title-spcPct",
            ),
            pytest.param(
                "cover",
                COVER_EYEBROW,
                COVER_EYEBROW_TEXT,
                COVER_EYEBROW_SIZE_PX,
                id="cover-eyebrow-single",
            ),
            pytest.param(
                "metrics",
                "#wrapped",
                "\n".join(WRAPPED_LINES),
                20,
                id="loose-space-before",
            ),
        ],
    )
    def test_box_top_is_the_calibrated_first_line_offset_above_the_glyphs(
        self, request: pytest.FixtureRequest, source: str, selector: str, text: str, size_px: int
    ) -> None:
        """The text box's top is ``firstLineOffsetPx`` above the browser's first line.

        The model, with ``A``, ``B`` and ``C`` as ``CALIBRATION.md`` records them:
        ``offset = A x (pct/100 - 1) x 1.2 x sizePx + B x sizePx + C x ascentPx``
        and ``y = firstLineTop - offset``, where firstLineTop is the top of the
        browser's first line of glyphs and ascentPx the browser's ascent for the
        run's face and size, its glyph top to its baseline, read with a
        baseline probe in the same page. pct is the first paragraph's spacing:
        the CSS line height over 1.2 x sizePx x 100 when that is at most 100
        (``spcPct``), and 100 for a single line, which has no ``<a:lnSpc>``, and
        for a looser block, whose first line is single spacing.

        * fixture 01's two-line cover title (pct 90) exercises all three terms;
        * fixture 01's single-line eyebrow exercises ``B`` and ``C``;
        * the metrics slide's two-line paragraph at 1.45 (pct 100, space before
          on its second line) does too.
        """
        document, pptx, slide = _sources(request, source)
        style = _guard_style(document, selector, fontSize=f"{size_px}px")
        _guard_family(style["fontFamily"], "DM Sans", selector)
        lines = _line_boxes(document, selector)
        pct = SINGLE_SPACING_PCT
        if len(lines) > 1:
            single = RENDERER_SINGLE_SPACING_EM * size_px
            pct = min(100 * _px(style["lineHeight"]) / single, SINGLE_SPACING_PCT)
        ascent = _ascent(document, "DM Sans", int(style["fontWeight"]), size_px, style["fontStyle"])
        first_line_a, first_line_b, first_line_c = (
            _recorded_value(name) for name in FIRST_LINE_CONSTANTS
        )
        offset = (
            first_line_a * (pct / 100 - 1) * RENDERER_SINGLE_SPACING_EM * size_px
            + first_line_b * size_px
            + first_line_c * ascent
        )
        expected_y = lines[0]["y"] - offset
        _, box = _box_reading(slide_shapes(pptx, slide), text)

        assert abs(box.y - expected_y) <= PLACEMENT_TOLERANCE_PX, (
            f"{selector}: the box top is {box.y:.2f} px; the first line's glyphs start at "
            f"{lines[0]['y']:.2f} px, so with A={first_line_a:g}, B={first_line_b:g}, "
            f"C={first_line_c:g}, pct={pct:.2f}, ascent={ascent:g} px the offset is "
            f"{offset:.2f} px and the top {expected_y:.2f} px (within {PLACEMENT_TOLERANCE_PX:g})"
        )


# ---------------------------------------------------------------------------
# Optical-size width compensation (A1)
# ---------------------------------------------------------------------------


def _font_css(style: dict[str, str]) -> str:
    """The element's own face and size, untracked: what a renderer draws before ``spc``."""
    return (
        f"font: {style['fontStyle']} {style['fontWeight']} {style['fontSize']} "
        f"{style['fontFamily']}; letter-spacing: 0"
    )


def _cut_widths(
    document: str, style: dict[str, str], texts: list[str]
) -> list[tuple[float, float]]:
    """(browser cut, export cut) advance widths of each text, untracked, in the element's face.

    The browser cut is the face at its automatic optical size, as the page
    draws it; the export cut the same face at ``font-variation-settings:
    'opsz' 14``, the static cut PowerPoint and Google Slides draw. One page
    reads both.
    """
    base = _font_css(style)
    export_cut = f"{base}; font-variation-settings: 'opsz' {EXPORT_CUT_OPTICAL_SIZE}"
    probes = [(text, css) for text in texts for css in (base, export_cut)]
    sizes = browser_probes(document, probes)
    return [
        (sizes[position]["w"], sizes[position + 1]["w"]) for position in range(0, len(sizes), 2)
    ]


def _unkerned_cut_widths(document: str, style: dict[str, str], texts: list[str]) -> list[float]:
    """The export cut's advance width of each text, untracked and with ``font-kerning: none``:
    what PowerPoint for Mac draws before ``spc`` (CALIBRATION.md X1)."""
    css = (
        f"{_font_css(style)}; font-variation-settings: 'opsz' {EXPORT_CUT_OPTICAL_SIZE}; "
        "font-kerning: none"
    )
    return [size["w"] for size in browser_probes(document, [(text, css) for text in texts])]


def _assert_powerpoint_tracking(
    document: str, selector: str, style: dict[str, str], runs: list[Run]
) -> None:
    """X1: each run of a block whose every line is one run carries, in the deck for
    PowerPoint, its CSS tracking plus ``powerpoint_tracking_px`` of its line (the
    optical-size delta with no dead band, plus its kerning per gap), within 1."""
    lines = _line_boxes(document, selector)
    # The lines read the source text, the runs the painted text (text-transform applied).
    read = [line["text"].casefold() for line in lines]
    assert read == [run.text.casefold() for run in runs], (
        f"fixture drift: {selector}'s lines {[line['text'] for line in lines]} are not its "
        f"runs {[run.text for run in runs]}, one each"
    )
    assert all(run.text.isascii() for run in runs), (
        f"fixture drift: {selector} is no longer ASCII, so its characters are not its graphemes"
    )
    widths = cut_widths(document, style, [run.text for run in runs])
    wrong = []
    for run, line, width in zip(runs, lines, widths):
        tracking = powerpoint_tracking_px(line["w"], width, len(run.text), True)
        expected = _css_spc(style) + tracking * PT_PER_PX * HUNDREDTHS
        if abs(run.spc_pt * HUNDREDTHS - expected) > SPC_TOLERANCE_HUNDREDTHS:
            wrong.append(f"{_describe_run(run)} (expected {expected:.1f}; {width})")
    assert not wrong, (
        f"{selector}, the deck for PowerPoint: every run's spc must be its CSS tracking plus "
        f"its optical-size delta and kerning, within {SPC_TOLERANCE_HUNDREDTHS:g}; these are "
        "not:\n  " + "\n  ".join(wrong)
    )


def _relative_difference(browser_cut: float, export_cut: float) -> float:
    return abs(export_cut - browser_cut) / browser_cut


def _css_spc(style: dict[str, str]) -> float:
    """The element's CSS letter-spacing as ``spc``, in hundredths of a point."""
    tracking = style["letterSpacing"]
    return 0.0 if tracking == "normal" else _px(tracking) * PT_PER_PX * HUNDREDTHS


def _untightened(runs: list[Run], css_spc: float) -> list[str]:
    """The runs whose ``spc`` is not tighter than the CSS tracking by more than rounding."""
    return [
        _describe_run(run)
        for run in runs
        if run.spc_pt * HUNDREDTHS >= css_spc - SPC_TOLERANCE_HUNDREDTHS
    ]


def _guard_cuts_differ(widths: list[tuple[float, float]], texts: list[str], what: str) -> None:
    narrow = [
        (text, browser_cut, export_cut)
        for text, (browser_cut, export_cut) in zip(texts, widths)
        if _relative_difference(browser_cut, export_cut) <= OPTICAL_SIZE_THRESHOLD
    ]
    assert not narrow, (
        f"environment: {what} is drawn at its automatic optical size, so the opsz-"
        f"{EXPORT_CUT_OPTICAL_SIZE} cut must be more than {OPTICAL_SIZE_THRESHOLD:.1%} wider; "
        f"these are not (text, browser px, export px): {narrow}. Did the deck's Google Fonts "
        "import (DM Sans with its opsz axis) load, or did the page fall back to a static font?"
    )


def _assert_compensated_control(
    document: str, selector: str, shapes: list[Shape], text: str
) -> None:
    """The control: a large DM Sans block on the same slide whose runs are tightened."""
    style = _style(document, selector, 0)
    _guard_family(style["fontFamily"], "DM Sans", selector)
    _, box = _box_reading(shapes, text)
    runs = _runs(box)
    texts = [run.text for run in runs]
    _guard_cuts_differ(_cut_widths(document, style, texts), texts, selector)
    untightened = _untightened(runs, _css_spc(style))
    assert not untightened, (
        f"control: {selector}'s export cut is wider than the browser's, so its runs must "
        f"be tracked tighter than the CSS {_css_spc(style):.1f}; these are not:\n  "
        + "\n  ".join(untightened)
    )


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotOpticalSizeCompensation:
    @pytest.mark.parametrize("target", ["pptx", "gslides"])
    def test_cover_title_tracking_restores_the_browsers_run_width(
        self, request: pytest.FixtureRequest, target: str
    ) -> None:
        """A1 (a) and X1: fixture 01's cover title, 64 px DM Sans 600, letter-spacing -.01em.

        The browser draws it at the automatic optical size, so the static
        opsz-14 cut PowerPoint and Google Slides use is about 9% wider. Every
        run therefore carries a negative ``spc`` delta on top of its CSS
        tracking (-0.48 pt). The width a renderer draws from the run is its
        cut's advance width plus n x spc: the untracked opsz-14 advance width
        of its text, read with a probe in the same page, plus the emitted
        tracking after each of its n characters. Google kerns, so its cut is
        the kerned one; PowerPoint for Mac draws DM Sans with no pair kerning,
        so for the deck written for it the cut is the ``font-kerning: none``
        one (X1). Summed over each line's runs, that is within 1% of the
        browser's own line width. Without the delta the line is about 9% wider
        and re-wraps in Slides. Counting the CSS tracking twice leaves it
        about 2% short.
        """
        document, pptx, slide = _sources(request, "cover", target)
        style = _guard_style(
            document,
            COVER_TITLE,
            fontSize=f"{COVER_TITLE_SIZE_PX}px",
            fontWeight="600",
            fontOpticalSizing="auto",
            fontVariationSettings="normal",
        )
        _guard_family(style["fontFamily"], "DM Sans", COVER_TITLE)
        browser_lines = _line_boxes(document, COVER_TITLE)
        assert [line["text"] for line in browser_lines] == list(COVER_TITLE_LINES), (
            f"fixture drift: the title renders {[line['text'] for line in browser_lines]}"
        )
        _, box = _box_reading(slide_shapes(pptx, slide), "\n".join(COVER_TITLE_LINES))
        lines = _emitted_lines(box)
        assert ["".join(run.text for run in line) for line in lines] == list(COVER_TITLE_LINES), (
            f"the title box's lines read {[[run.text for run in line] for line in lines]}"
        )
        runs = [run for line in lines for run in line]
        assert all(run.text.isascii() for run in runs), (
            "fixture drift: the title is no longer ASCII, so its characters are not its graphemes"
        )
        widths = _cut_widths(document, style, [run.text for run in runs])
        _guard_cuts_differ(widths, [run.text for run in runs], "the cover title")

        css_spc = _css_spc(style)
        untightened = _untightened(runs, css_spc)
        assert not untightened, (
            f"every run of the cover title must carry a negative spc delta on top of its CSS "
            f"tracking ({css_spc:.1f} hundredths of a point); these do not:\n  "
            + "\n  ".join(untightened)
        )
        drawn_cuts = (
            _unkerned_cut_widths(document, style, [run.text for run in runs])
            if target == "pptx"
            else [export_cut for _, export_cut in widths]
        )
        export_widths = iter(drawn_cuts)
        mismatched = []
        for line, browser_line in zip(lines, browser_lines):
            implied = sum(
                next(export_widths) + len(run.text) * run.spc_pt / PT_PER_PX for run in line
            )
            if abs(implied - browser_line["w"]) > WIDTH_TOLERANCE * browser_line["w"]:
                mismatched.append(
                    f"{browser_line['text']!r}: exported {implied:.2f} px, browser "
                    f"{browser_line['w']:.2f} px ({implied / browser_line['w'] - 1:+.2%})"
                )
        assert not mismatched, (
            f"{target}: each line's width at the export cut plus its emitted tracking must be "
            f"within {WIDTH_TOLERANCE:.0%} of the browser's:\n  "
            + "\n  ".join(mismatched)
            + "\nruns:\n  "
            + "\n  ".join(_describe_run(run) for run in runs)
        )

    @pytest.mark.parametrize(
        ("source", "selector", "text", "control_selector", "control_text"),
        [
            pytest.param(
                "cover",
                COVER_EYEBROW,
                COVER_EYEBROW_TEXT,
                COVER_TITLE,
                "\n".join(COVER_TITLE_LINES),
                id="cover-eyebrow",
            ),
            pytest.param(
                "metrics",
                "#body-13",
                BODY_13_TEXT,
                "#dm-sans-headline",
                DM_SANS_HEADLINE_TEXT,
                id="body-13",
            ),
        ],
    )
    @pytest.mark.parametrize("target", ["pptx", "gslides"])
    def test_13px_run_keeps_its_css_tracking_for_google(
        self,
        request: pytest.FixtureRequest,
        source: str,
        selector: str,
        text: str,
        control_selector: str,
        control_text: str,
        target: str,
    ) -> None:
        """A1 (b): in the deck for Google Slides a 13 px DM Sans run gets no delta beyond its
        CSS letter-spacing; in the deck for PowerPoint it carries X1's tracking.

        At 13 px the automatic optical size is 13, next to the export cut's
        14, so the two widths differ by well under 0.5% (guarded here with the
        page's own probes), and for Google, which kerns, the run's ``spc`` is
        exactly its CSS tracking:

        * fixture 01's eyebrow (700, ``.16em``): 156;
        * a 13 px body paragraph (400, ``.02em``): 19.5, within 1.

        For PowerPoint, which kerns no DM Sans, the run carries its CSS
        tracking plus its optical-size delta, with no dead band, and its
        kerning per gap (``_assert_powerpoint_tracking``; CALIBRATION.md X1).

        The control is a large DM Sans block on the same slide (the cover
        title; a 64 px headline), which is tightened in both decks. So the
        compensation is present, and for Google only skipped where it is not
        due.
        """
        document, pptx, slide = _sources(request, source, target)
        style = _guard_style(
            document,
            selector,
            fontSize="13px",
            fontOpticalSizing="auto",
            fontVariationSettings="normal",
        )
        _guard_family(style["fontFamily"], "DM Sans", selector)
        shapes = slide_shapes(pptx, slide)
        _, box = _box_reading(shapes, text)
        runs = _runs(box)
        widths = _cut_widths(document, style, [run.text for run in runs])
        wide = [
            (run.text, browser_cut, export_cut)
            for run, (browser_cut, export_cut) in zip(runs, widths)
            if _relative_difference(browser_cut, export_cut) > OPTICAL_SIZE_THRESHOLD
        ]
        assert not wide, (
            f"fixture drift: at 13 px the two cuts must differ by at most "
            f"{OPTICAL_SIZE_THRESHOLD:.1%}; these do (text, browser px, export px): {wide}"
        )
        _assert_compensated_control(document, control_selector, shapes, control_text)
        if target == "pptx":
            _assert_powerpoint_tracking(document, selector, style, runs)
            return

        expected = _css_spc(style)
        wrong = [
            _describe_run(run)
            for run in runs
            if abs(run.spc_pt * HUNDREDTHS - expected) > SPC_TOLERANCE_HUNDREDTHS
        ]
        assert not wrong, (
            f"{selector}: every run's spc must be its CSS tracking, {expected:.1f} hundredths "
            f"of a point within {SPC_TOLERANCE_HUNDREDTHS:g}; these are not:\n  "
            + "\n  ".join(wrong)
        )

    @pytest.mark.parametrize("target", ["pptx", "gslides"])
    def test_arial_run_never_gets_a_delta(
        self, request: pytest.FixtureRequest, target: str
    ) -> None:
        """A1 (c): a 64 px Arial headline gets no optical-size delta: for Google its CSS
        tracking, -0.48 pt; for PowerPoint that plus its kerning.

        Arial has no optical-size axis: the page's probes measure the same
        width at the automatic optical size and at ``'opsz' 14`` (guarded
        here). So for Google its ``spc`` is exactly its CSS letter-spacing,
        -.01em at 64 px = -48 hundredths of a point. The deck for PowerPoint
        writes ``kern="0"`` with every ``spc``, so PowerPoint kerns Arial no
        more than DM Sans (measured, CALIBRATION.md X1), and the run carries
        its kerning per gap besides (``_assert_powerpoint_tracking``). The
        control is the same headline style in DM Sans on the same slide, which
        is tightened.
        """
        document, metrics_pptx, _ = _sources(request, "metrics", target)
        style = _guard_style(
            document,
            "#arial-headline",
            fontSize="64px",
            fontFamily="Arial",
            letterSpacing="-0.64px",
        )
        shapes = slide_shapes(metrics_pptx, 0)
        _, box = _box_reading(shapes, ARIAL_HEADLINE_TEXT)
        runs = _runs(box)
        not_arial = [_describe_run(run) for run in runs if run.typeface != "Arial"]
        assert not not_arial, "fixture drift: the headline's runs are not Arial:\n  " + "\n  ".join(
            not_arial
        )
        widths = _cut_widths(document, style, [run.text for run in runs])
        varied = [
            (run.text, browser_cut, export_cut)
            for run, (browser_cut, export_cut) in zip(runs, widths)
            if _relative_difference(browser_cut, export_cut) > OPTICAL_SIZE_THRESHOLD
        ]
        assert not varied, (
            f"fixture drift: Arial must have no optical-size axis; these widths vary "
            f"(text, browser px, export px): {varied}"
        )
        _assert_compensated_control(document, "#dm-sans-headline", shapes, DM_SANS_HEADLINE_TEXT)
        if target == "pptx":
            _assert_powerpoint_tracking(document, "#arial-headline", style, runs)
            return

        expected = _css_spc(style)
        wrong = [
            _describe_run(run)
            for run in runs
            if abs(run.spc_pt * HUNDREDTHS - expected) > SPC_TOLERANCE_HUNDREDTHS
        ]
        assert not wrong, (
            f"every Arial run's spc must be its CSS tracking, {expected:.1f} hundredths of a "
            f"point within {SPC_TOLERANCE_HUNDREDTHS:g}; these are not:\n  " + "\n  ".join(wrong)
        )


# ---------------------------------------------------------------------------
# Superscript and subscript size (A2)
# ---------------------------------------------------------------------------


def _assert_script_run_size(
    box: Shape, script: Run, baseline: str, script_px: float, item_px: float
) -> None:
    """The script run keeps its baseline shift and is sized for the renderers' shrink.

    Its ``sz`` is the browser's ``script_px`` x 0.75 x 100 divided by the
    recorded factor (``_script_factor``), within 1 hundredth of a point; every
    other run of the box keeps the item's ``item_px``.
    """
    assert script.baseline == baseline, (
        f"the {baseline}script run lost its baseline shift: {_describe_run(script)}"
    )
    name, factor = _script_factor(baseline)
    expected = script_px * PT_PER_PX * HUNDREDTHS / factor
    assert script.size_pt is not None and (
        abs(script.size_pt * HUNDREDTHS - expected) <= SIZE_TOLERANCE_HUNDREDTHS
    ), (
        f"the {baseline}script run's sz must be the browser's {script_px:g} px x {PT_PER_PX} / "
        f"{name} {factor:g} = {expected:.1f} hundredths of a point, within "
        f"{SIZE_TOLERANCE_HUNDREDTHS:g}: {_describe_run(script)}"
    )
    item_size = item_px * PT_PER_PX * HUNDREDTHS
    resized = [
        _describe_run(run)
        for run in _runs(box)
        if run is not script
        and (
            run.size_pt is None
            or abs(run.size_pt * HUNDREDTHS - item_size) > SIZE_TOLERANCE_HUNDREDTHS
        )
    ]
    assert not resized, (
        f"text other than the {baseline}script must keep the item's {item_size:.0f} hundredths "
        "of a point:\n  " + "\n  ".join(resized)
    )


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotScriptSize:
    def test_superscript_size_is_the_browsers_over_the_renderers_shrink(
        self, corpus_pptx: bytes
    ) -> None:
        """A2: fixture 09's footnote marker, "gross profit<sup>1</sup>" in a 20 px item.

        The browser draws the marker at its computed ``font-size`` (``smaller``
        of 20 px, 16.67 px). PowerPoint and Google Slides shrink a superscript
        run again, to ``SUPERSCRIPT_SIZE_FACTOR`` of its emitted size. So the
        marker run stays a superscript (``baseline`` > 0) and its ``sz`` is
        the browser's size divided by the factor CALIBRATION.md records, within
        1 hundredth of a point: once the renderer shrinks it, it is the size
        the browser drew. The rest of the item keeps the browser's 20 px, 15 pt.
        """
        document = corpus_document("09")
        marker_style = _guard_style(document, FOOTNOTE_MARKER_SELECTOR, verticalAlign="super")
        assert browser_text(document, FOOTNOTE_MARKER_SELECTOR) == FOOTNOTE_MARKER, (
            f"fixture drift: the footnote marker no longer reads {FOOTNOTE_MARKER!r}"
        )
        _guard_style(
            document, FOOTNOTE_ITEM, FOOTNOTE_ITEM_INDEX, fontSize=f"{FOOTNOTE_ITEM_SIZE_PX}px"
        )
        box = _box_containing(slide_shapes(corpus_pptx, 1), FOOTNOTE_LINE)

        _assert_script_run_size(
            box,
            _run(box, FOOTNOTE_MARKER),
            "super",
            _px(marker_style["fontSize"]),
            FOOTNOTE_ITEM_SIZE_PX,
        )

    def test_subscript_size_is_the_browsers_over_the_renderers_shrink(
        self, metrics_pptx: bytes
    ) -> None:
        """A2, the subscript twin: "Water is H<sub>2</sub>O" in a 20 px paragraph.

        The browser draws the "2" at its computed ``font-size`` (``smaller`` of
        20 px, 16.67 px), lowered. The renderers shrink a subscript run again,
        so the run stays a subscript (``baseline`` < 0) and its ``sz`` is the
        browser's size divided by ``SUBSCRIPT_SIZE_FACTOR`` when CALIBRATION.md
        records one, else by ``SUPERSCRIPT_SIZE_FACTOR``, within 1 hundredth of
        a point. The rest of the paragraph keeps the browser's 20 px, 15 pt.
        """
        document = _metrics_document()
        subscript_style = _guard_style(document, SUBSCRIPT_SELECTOR, verticalAlign="sub")
        assert browser_text(document, CHEMISTRY) == CHEMISTRY_TEXT, (
            f"fixture drift: the paragraph renders {browser_text(document, CHEMISTRY)!r}"
        )
        _guard_style(document, CHEMISTRY, fontSize=f"{CHEMISTRY_SIZE_PX}px")
        _, box = _box_reading(slide_shapes(metrics_pptx, 0), CHEMISTRY_TEXT)

        _assert_script_run_size(
            box,
            _run(box, SUBSCRIPT_TEXT),
            "sub",
            _px(subscript_style["fontSize"]),
            CHEMISTRY_SIZE_PX,
        )


# ---------------------------------------------------------------------------
# Render checks (A3): the outcomes the first PowerPoint and Google renders showed
# ---------------------------------------------------------------------------

# A border is the shape's outline when its a:ln carries a fill.
LINE_FILLS = ("solidFill", "gradFill", "pattFill")
BORDER_COLOUR = "1B3139"
BOX_TOLERANCE_PX = 1.0


def _shape_at(shapes: list[Shape], rect: dict, inset: float = 0.0) -> int:
    """The spTree index of the one shape whose box is ``rect`` inset by ``inset`` px a side."""
    matches = [
        position
        for position, shape in enumerate(shapes)
        if shape.kind == "shape"
        and abs(shape.x - (rect["x"] + inset)) <= BOX_TOLERANCE_PX
        and abs(shape.y - (rect["y"] + inset)) <= BOX_TOLERANCE_PX
        and abs(shape.w - (rect["w"] - 2 * inset)) <= BOX_TOLERANCE_PX
        and abs(shape.h - (rect["h"] - 2 * inset)) <= BOX_TOLERANCE_PX
    ]
    assert len(matches) == 1, f"expected one shape at {rect} (inset {inset}), got {len(matches)}"
    return matches[0]


@pytest.mark.slow
@requires_huashu_sidecar
class TestRenderCheckOutcomes:
    def test_repeated_paragraph_properties_are_identical(
        self, corpus_pptx: bytes, metrics_pptx: bytes
    ) -> None:
        """No repair prompt: PowerPoint opened the calibration deck, saved it and closed it.

        pptxgenjs writes an ``<a:pPr>`` before every run of a paragraph, which
        the schema does not allow; PowerPoint and Google Slides read the deck
        anyway (``CALIBRATION.md``, A3). What keeps that harmless is that every
        ``<a:pPr>`` of one paragraph is the same, so the spacing and space before
        are the paragraph's whichever one a reader honours. Pinned on corpus
        slides 01 and 09 and the metrics slide; the control is that they do hold
        paragraphs with more than one ``<a:pPr>``.
        """
        slides = [(corpus_pptx, 0), (corpus_pptx, 1), (metrics_pptx, 0)]
        repeated = 0
        differing = []
        for pptx, index in slides:
            for paragraph in slide_xml(pptx, index).iterfind(".//a:p", NAMESPACES):
                properties = paragraph.findall("a:pPr", NAMESPACES)
                repeated += len(properties) > 1
                if len({etree.tostring(element) for element in properties}) > 1:
                    text = "".join(paragraph.itertext())
                    differing.append(f"slide {index}: {text[:50]!r}")

        assert repeated, "control: no paragraph repeats its <a:pPr>, so nothing is pinned"
        assert not differing, (
            "these paragraphs carry differing <a:pPr>, so a reader that honours another one "
            "gets another spacing:\n  " + "\n  ".join(differing)
        )

    def test_unbordered_shape_keeps_its_unfilled_line(self, metrics_pptx: bytes) -> None:
        """No default outline: a box with a background and no border keeps its fill-less ``<a:ln>``.

        Neither PowerPoint nor Google Slides draws an outline for
        ``<a:ln></a:ln>`` (``CALIBRATION.md``, A3), so the unbordered box's
        ``<a:ln>`` stays as it is: present, with no fill and no width. The
        control is the bordered twin, whose ``<a:ln>`` is filled with its border
        colour.
        """
        document = _metrics_document()
        shapes = slide_shapes(metrics_pptx, 0)
        elements = slide_shape_elements(metrics_pptx, 0)
        plain = elements[_shape_at(shapes, browser_rect(document, PLAIN_BOX))]
        bordered = elements[_shape_at(shapes, browser_rect(document, BORDERED_BOX), inset=1.0)]

        bordered_line = bordered.find("p:spPr/a:ln", NAMESPACES)
        assert bordered_line is not None and (
            bordered_line.find("a:solidFill/a:srgbClr", NAMESPACES) is not None
            and bordered_line.find("a:solidFill/a:srgbClr", NAMESPACES).get("val").upper()
            == BORDER_COLOUR
        ), "control: the bordered box's <a:ln> does not carry its border colour"
        line = plain.find("p:spPr/a:ln", NAMESPACES)
        assert line is not None, "the unbordered box has no <a:ln>"
        fills = [etree.QName(child).localname for child in line]
        assert not set(fills) & set(LINE_FILLS) and line.get("w") is None, (
            f"the unbordered box's <a:ln> draws a line: {etree.tostring(line, encoding='unicode')}"
        )

    def test_justified_text_is_written_left_aligned_with_the_browsers_lines(
        self, metrics_pptx: bytes
    ) -> None:
        """Justified text is written left-aligned, with the browser's line breaks.

        PowerPoint and Google Slides justify a line to the whole box, its slack
        included, so justified lines ran about 35 px past the browser's
        (``CALIBRATION.md``, A3). A ``text-align: justify`` paragraph therefore
        reads exactly the browser's lines, every paragraph of its box is
        left-aligned, and the box starts at the paragraph's left edge.
        """
        document = _metrics_document()
        _guard_style(document, JUSTIFIED, textAlign="justify")
        lines = [line["text"] for line in _line_boxes(document, JUSTIFIED)]
        assert len(lines) > 2, f"fixture drift: the justified paragraph renders {lines}"
        rect = browser_rect(document, JUSTIFIED)
        box = _box_containing(slide_shapes(metrics_pptx, 0), lines[0])

        assert box.text.split("\n") == lines, (
            f"the justified box reads {box.text.split(chr(10))}; the browser's lines are {lines}"
        )
        aligned = [para.align for para in box.paras]
        assert aligned and set(aligned) == {"left"}, (
            f"every paragraph of the justified box must be left-aligned; they are {aligned}"
        )
        assert abs(box.x - rect["x"]) <= PLACEMENT_TOLERANCE_PX, (
            f"the justified box starts at {box.x:.2f} px; the paragraph's left edge is "
            f"{rect['x']:.2f} px"
        )
