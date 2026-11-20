"""Snapshot engine: run typography (spec §3 Text "Runs carry", §5 Emitter "Weights").

Every run the snapshot engine emits carries the browser's typography:

* **Weights.** 400 is the family and 700 is the family plus bold. Every other
  weight of a webfont the page loaded is a weight-named typeface ("DM Sans
  SemiBold", "DM Sans Medium"), never bold. A family the page did not load as
  a webfont keeps its own name and is bold from 600 ("Arial" plus bold, never
  "Arial SemiBold", which PowerPoint would replace with a default font: Review
  Focus 3).
* **Family.** The stack's first real face: ``system-ui``, ``-apple-system`` and
  ``BlinkMacSystemFont`` are skipped, and a stack of generics maps to Arial,
  Times New Roman or Courier New. A run inside an element keeps its own family
  (a DM Mono chip in a DM Sans sentence).
* **Element style reaches every run**: a heading's weight survives its
  ``<br>`` and its inline children.
* **Letter spacing** as ``spc``, plus at title sizes the optical-size
  delta (``scripts/export_fidelity/CALIBRATION.md`` A1); ``text-transform`` applied to the run text;
  super- and subscript as a baseline offset; italic, underline and
  strike-through.
* **Colour is solid and pre-blended**, because Drive drops text alpha: the
  colour's alpha times the cumulative opacity is blended over the resolved
  backdrop, with no ``<a:alpha>`` left on the run. Opacity groups composite
  layer by layer: the text's own alpha over its backdrop inside its innermost
  opacity group, then each group, inner to outer, at its opacity over the
  backdrop beneath that group. Gradient text (``background-clip: text``) takes
  the gradient's middle colour, and transparent text is never opaque black.
* **CJK, emoji and right-to-left text** keep their characters and their order.

Every assertion reads the emitted run XML (``slide_shapes``): ``a:latin`` /
``a:ea`` / ``a:cs`` typefaces, ``b``, ``i``, ``u``, ``strike``, ``spc``,
``baseline``, the ``srgbClr`` and any ``<a:alpha>``, and the paragraph's ``rtl``.
Where a test compares with the browser, the browser's own rendering of the
very same document is read back (``browser_lines``, ``browser_text``,
``browser_style``, ``browser_loaded_weights``), and each test first guards the
fixture's computed style so a failure is never fixture drift. Expected blended
colours are computed here from ``blendOver``'s formula and the
fixture's colours.

Corpus slides come from ``tests/fixtures/export_fidelity`` by prefix
(``corpus_document``): 09 holds the eyebrow, the footnote marker, the DM Mono
chip and italic text; 13 holds the gradient headline words and a faded
paragraph. ``emit_typography.cjs``'s pure mapping (``typefaceFor``,
``blendOver``) is also pinned in Node, without a browser.

Gating matches the sibling export suites: the export tests need node, the
extracted sidecar ``node_modules`` and a local Chrome/Chromium; the Node tests
need node alone (skipped otherwise). The weight-named faces depend on the
deck's Google Fonts import loading, which the weight tests guard explicitly.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from lxml import etree

from src.services import pptx_from_html_huashu
from tests.fixtures.export_snapshot_support import (
    DECK_CSS,
    Run,
    Shape,
    browser_line_boxes,
    browser_lines,
    browser_loaded_weights,
    browser_probes,
    browser_style,
    browser_text,
    corpus_document,
    export_corpus,
    export_slides,
    node_json,
    requires_huashu_sidecar,
    requires_node,
    slide_document,
    slide_shapes,
    text_loss,
    text_shapes,
)

TYPOGRAPHY_MODULE = Path(pptx_from_html_huashu.SIDECAR_DIR) / "emit_typography.cjs"

PT_PER_PX = 0.75
HUNDREDTHS = 100
# A superscript is baseline="30000" (1000ths of a percent).
SUPERSCRIPT_BASELINE = 30000
# spc = round(size x em x 0.75 x 100) +/- 1.
SPC_TOLERANCE_HUNDREDTHS = 1.0
# CALIBRATION.md A1: a run whose width at the browser's automatic optical size
# and at the static opsz-14 cut (what PowerPoint and Google Slides draw) differ
# by more than 0.5% carries an optical-size delta on top of its CSS tracking.
OPTICAL_SIZE_THRESHOLD = 0.005
EXPORT_CUT_OPTICAL_SIZE = 14
# A colour blended twice, or a gradient's midpoint, may round its exact value
# either way; one unit per channel allows for that and nothing more.
CHANNEL_TOLERANCE = 1.0

# deck.css: --paper is the .slide background, --ink its text colour.
PAPER = "F9F7F4"
INK = "1B3139"
OPAQUE_BLACK = "000000"

# Spec §5 Weights, and emit_typography.cjs WEIGHT_NAMES: 400 and 700 have no name.
WEIGHT_NAMES = {
    100: "Thin",
    200: "ExtraLight",
    300: "Light",
    500: "Medium",
    600: "SemiBold",
    800: "ExtraBold",
    900: "Black",
}
ALL_WEIGHTS = list(range(100, 1000, 100))
# The DM Sans weights the deck imports from Google Fonts.
DM_SANS_WEIGHTS = [400, 500, 600, 700]

# ---------------------------------------------------------------------------
# Custom slides, exported once per module in this order
# ---------------------------------------------------------------------------

# Weights: a .dk-title (42 px, 600) and DM Sans at 400, 500 and 700, plus a
# stack of a generic and a face the page did not load (system-ui, Arial).
SEMIBOLD_TITLE = "Revenue grew in every segment"
REGULAR_TEXT = "Regular four hundred"
MEDIUM_TEXT = "Medium five hundred"
BOLD_TEXT = "Bold seven hundred"
SYSTEM_ARIAL_TEXT = "System stack semibold"
WEIGHTS_SLIDE = (
    '<div class="slide">'
    f'<h2 id="semibold" class="dk-title">{SEMIBOLD_TITLE}</h2>'
    f'<p id="regular" style="font-size: 24px; font-weight: 400;">{REGULAR_TEXT}</p>'
    f'<p id="medium" style="font-size: 24px; font-weight: 500;">{MEDIUM_TEXT}</p>'
    f'<p id="bold" style="font-size: 24px; font-weight: 700;">{BOLD_TEXT}</p>'
    '<p id="system-arial" style="font-family: system-ui, Arial; font-size: 24px; '
    f'font-weight: 600;">{SYSTEM_ARIAL_TEXT}</p>'
    "</div>"
)

# Families: stacks with no webfont first. (element id, font-family, text, typeface)
FAMILY_CASES = (
    ("generic-sans", "sans-serif", "Generic sans text", "Arial"),
    ("generic-serif", "serif", "Generic serif text", "Times New Roman"),
    ("generic-mono", "monospace", "Generic mono text", "Courier New"),
    (
        "platform-stack",
        "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
        "Platform stack text",
        "Segoe UI",
    ),
)
FAMILIES_SLIDE = (
    '<div class="slide">'
    + "".join(
        f'<p id="{element_id}" style="font-family: {family}; font-size: 20px;">{text}</p>'
        for element_id, family, text, _ in FAMILY_CASES
    )
    + "</div>"
)

# Element style inherited into runs (upstream PR #10).
STACKED_LINES = ("Top", "Bottom")
ACCENTED_TITLE = "Margin rose to 59%"
ACCENT_FIGURE = "59%"
ACCENT_COLOR = "FF3621"
INHERITED_SLIDE = (
    '<div class="slide">'
    '<h1 id="stacked" style="font-weight: 700;">Top<br>Bottom</h1>'
    '<h2 id="accented" class="dk-title">Margin rose to '
    f'<span style="color: #{ACCENT_COLOR};">{ACCENT_FIGURE}</span></h2>'
    "</div>"
)

# Decorations and subscript.
DECORATED_TEXT = "Underlined then struck then plain"
NESTED_UNDERLINE_TEXT = "Underlined bold words"
CHEMISTRY_TEXT = "Water is H2O"
DECORATIONS_SLIDE = (
    '<div class="slide">'
    '<p id="decorated" style="font-size: 20px;"><u>Underlined</u> then <s>struck</s> then plain</p>'
    '<p id="nested" style="font-size: 20px;"><u>Underlined <b>bold</b> words</u></p>'
    '<p id="chemistry" style="font-size: 20px;">Water is H<sub>2</sub>O</p>'
    "</div>"
)

# Opacity and alpha. The slide background is --paper; the cards set their own.
NAVY = "1B3139"
TINT = ("FF5F46", 0.10)  # the .dk-table .hl tint: rgba(255, 95, 70, .10)
FADED_TEXT = "Faded note"
ON_NAVY_TEXT = "Navy note"
TINTED_TEXT = "Tinted note"
INVISIBLE_TEXT = "Invisible note"
OPACITY_SLIDE = (
    '<div class="slide">'
    f'<p id="faded" style="opacity: .5; color: #1B3139; font-size: 20px;">{FADED_TEXT}</p>'
    f'<div id="navy-card" style="background: #{NAVY}; padding: 24px; width: 420px;">'
    '<p id="on-navy" style="color: rgba(255, 255, 255, .7); font-size: 20px; margin: 0;">'
    f"{ON_NAVY_TEXT}</p></div>"
    '<div id="tint-card" style="background: rgba(255, 95, 70, .10); padding: 24px; width: 420px; '
    'margin-top: 16px;">'
    '<p id="tinted" style="opacity: .6; color: #1B3139; font-size: 20px; margin: 0;">'
    f"{TINTED_TEXT}</p></div>"
    f'<p id="invisible" style="color: transparent; font-size: 20px;">{INVISIBLE_TEXT}</p>'
    "</div>"
)

# Gradient text whose stops are unambiguous: three, evenly spaced, the middle
# one a colour used nowhere else on the slide (--good), and a nested inline
# child whose own background is none.
THREE_STOPS = ("FF3621", "00A972", "FFB347")
THREE_STOP_GRADIENT = (
    "linear-gradient(90deg, rgb(255, 54, 33), rgb(0, 169, 114), rgb(255, 179, 71))"
)
THREE_STOP_TEXT = "Three stop headline"
GRADIENT_SLIDE = (
    '<div class="slide">'
    '<h2 id="three-stop" style="font-size: 40px; font-weight: 600; '
    "background: linear-gradient(90deg, #FF3621, #00A972, #FFB347); "
    '-webkit-background-clip: text; background-clip: text; color: transparent;">'
    "Three stop <em>headline</em></h2>"
    "</div>"
)

# CJK, emoji and right-to-left text.
CJK_TEXT = "季度收入增长 12% 🎉"
RTL_TEXT = "مرحبا بالعالم"
SCRIPTS_SLIDE = (
    '<div class="slide">'
    f'<p id="cjk" style="font-size: 24px;">{CJK_TEXT}</p>'
    f'<p id="rtl" dir="rtl" style="font-size: 24px;">{RTL_TEXT}</p>'
    "</div>"
)

# Opacity groups that paint their own background. The
# faded card is a .5 group whose navy background sits under its white text.
# The nested case is a translucent card (a .8 group with an opaque white
# background) holding accent text, inside a faded section (a .5 group with a
# navy background), on the paper slide.
WHITE = "FFFFFF"
GROUP_ACCENT = "FF3621"
FADED_CARD_OPACITY = 0.5
FADED_CARD_TEXT = "Faded card text"
FADED_SECTION_OPACITY = 0.5
TRANSLUCENT_CARD_OPACITY = 0.8
NESTED_CARD_TEXT = "Nested card text"
GROUPS_SLIDE = (
    '<div class="slide">'
    f'<div id="faded-card" style="opacity: .5; background: #{NAVY}; padding: 24px; '
    'width: 420px;">'
    '<p id="faded-card-text" style="color: #fff; font-size: 20px; margin: 0;">'
    f"{FADED_CARD_TEXT}</p></div>"
    f'<section id="faded-section" style="opacity: .5; background: #{NAVY}; padding: 24px; '
    'width: 520px; margin-top: 24px;">'
    f'<div id="translucent-card" style="opacity: .8; background: #{WHITE}; padding: 16px;">'
    f'<p id="nested-card-text" style="color: #{GROUP_ACCENT}; font-size: 20px; margin: 0;">'
    f"{NESTED_CARD_TEXT}</p></div></section>"
    "</div>"
)

# Gradient text whose stops sit at lengths, not percentages. Chrome computes
# both the px and the em form to px ("rgb(255, 54, 33) 0px"). A length's place
# on the gradient line is not known, so the stops are spaced evenly and the
# middle is the mix of the two, the same colour as .dk-gradtext's.
# (element id, background, text)
LENGTH_STOP_CASES = (
    ("px-stops", "linear-gradient(90deg, #FF3621 0px, #FFB347 300px)", "Pixel stop headline"),
    ("em-stops", "linear-gradient(90deg, #FF3621 0em, #FFB347 20em)", "Em stop headline"),
)
LENGTH_STOPS_SLIDE = (
    '<div class="slide">'
    + "".join(
        f'<h2 id="{element_id}" style="font-size: 40px; font-weight: 600; background: {gradient}; '
        f'-webkit-background-clip: text; background-clip: text; color: transparent;">{text}</h2>'
        for element_id, gradient, text in LENGTH_STOP_CASES
    )
    + "</div>"
)

# text-transform: capitalize at the browser's word boundaries: a letter after
# anything but a letter, a digit or an apostrophe starts a word. The second
# paragraph is too narrow for "x-ray", so the browser breaks it after the hyphen.
CAPITALIZE_SOURCE = "well-known (hello) 1st o’neil x-ray e.g. foo"
CAPITALIZE_RENDERED = "Well-Known (Hello) 1st O’neil X-Ray E.G. Foo"
CAPITALIZE_WRAPPED_SOURCE = "x-ray"
CAPITALIZE_WRAPPED_RENDERED = "X-Ray"
CAPITALIZE_SLIDE = (
    '<div class="slide">'
    '<p id="capitalized" style="font-size: 24px; text-transform: capitalize;">'
    f"{CAPITALIZE_SOURCE}</p>"
    '<p id="capitalized-wrap" style="font-size: 24px; text-transform: capitalize; width: 1.6em;">'
    f"{CAPITALIZE_WRAPPED_SOURCE}</p>"
    "</div>"
)

# The common gradient-text idiom: the glyphs are cleared with
# -webkit-text-fill-color while `color` stays the opaque ink, and a
# background-color sits under the gradient as a fallback. Both background
# layers are clipped to the glyphs.
FILL_IDIOM_TEXT = "Fill colour headline"
FILL_IDIOM_FALLBACK = "FF3621"
FILL_IDIOM_SLIDE = (
    '<div class="slide">'
    '<h2 id="fill-idiom" style="font-size: 40px; font-weight: 600; color: #1B3139; '
    f"background-color: #{FILL_IDIOM_FALLBACK}; "
    "background-image: linear-gradient(90deg, #FF3621, #00A972, #FFB347); "
    "-webkit-background-clip: text; background-clip: text; "
    f'-webkit-text-fill-color: transparent;">{FILL_IDIOM_TEXT}</h2>'
    "</div>"
)

SLIDES = {
    "weights": WEIGHTS_SLIDE,
    "families": FAMILIES_SLIDE,
    "inherited": INHERITED_SLIDE,
    "decorations": DECORATIONS_SLIDE,
    "opacity": OPACITY_SLIDE,
    "gradient": GRADIENT_SLIDE,
    "scripts": SCRIPTS_SLIDE,
    "groups": GROUPS_SLIDE,
    "length-stops": LENGTH_STOPS_SLIDE,
    "capitalize": CAPITALIZE_SLIDE,
    "fill-idiom": FILL_IDIOM_SLIDE,
}

# ---------------------------------------------------------------------------
# Corpus slides, exported once per module in this order
# ---------------------------------------------------------------------------

CORPUS_PREFIXES = ("09", "13")

# Fixture 09: the eyebrow (13 px, 700, letter-spacing .16em, uppercase) and the
# .dk-title (42 px, 600, letter-spacing -.01em).
EYEBROW = ".dk-eyebrow"
EYEBROW_SOURCE_TEXT = "What changed"
CORPUS_TITLE = ".dk-title"
CORPUS_TITLE_TEXT = "Three drivers explain the margin step-up"
# Fixture 09's list: the chip line, the footnote marker line and the italic line.
CHIP_LINE = "Mix shift"
CHIP_TEXT = "SKU-7"
CHIP_SENTENCE_REST = "now 31% of revenue"
FOOTNOTE_LINE = "Operating leverage"
FOOTNOTE_MARKER = "1"
ITALIC_LINE = "Interest expense fell as"
ITALIC_TEXT = "debt was repaid early"
# Fixture 09's .dk-source footnote is italic.
SOURCE_TEXT = "1. Excluding one-off restructuring costs."

# Fixture 13: the .dk-gradtext span inside the .dk-title, a two-stop gradient
# from --accent-2 to #FFB347; and a paragraph at opacity .6 on the paper slide.
GRADTEXT = ".dk-gradtext"
GRADTEXT_WORDS = "from the ledger"
GRADTEXT_TITLE_RUNS = ("Margins are computed", ", not estimated")
GRADTEXT_STOPS = ("FF3621", "FFB347")
GRADTEXT_GRADIENT = "linear-gradient(90deg, rgb(255, 54, 33), rgb(255, 179, 71))"
FADED_CORPUS_TEXT = "Restated FY23 figures use the same query."
FADED_CORPUS_OPACITY = 0.6


# ---------------------------------------------------------------------------
# Exports and lookups
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def typography_pptx() -> Iterator[bytes]:
    """The custom slides in ``SLIDES``, exported once through the snapshot engine."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        pptx, failures = export_slides(
            list(SLIDES.values()), css=DECK_CSS, monkeypatch=monkeypatch
        )
    assert failures == [], f"the export rejected a slide: {failures}"
    yield pptx


@pytest.fixture(scope="module")
def corpus_pptx() -> Iterator[bytes]:
    """Corpus slides 09 and 13, exported once through the snapshot engine."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        pptx, failures = export_corpus(
            list(CORPUS_PREFIXES), monkeypatch=monkeypatch
        )
    assert failures == [], f"the export rejected a corpus slide: {failures}"
    yield pptx


def _slide_index(name: str) -> int:
    return list(SLIDES).index(name)


def _document(name: str) -> str:
    """The document ``typography_pptx`` exported as slide ``name``, with its slide id."""
    return slide_document(SLIDES[name], css=DECK_CSS, slide_id=f"snapshot-{_slide_index(name) + 1}")


def _shapes(pptx: bytes, name: str) -> list[Shape]:
    return slide_shapes(pptx, _slide_index(name))


def _corpus_shapes(pptx: bytes, prefix: str) -> list[Shape]:
    return slide_shapes(pptx, CORPUS_PREFIXES.index(prefix))


def _runs(shape: Shape) -> list[Run]:
    return [run for para in shape.paras for run in para.runs]


def _describe_run(run: Run) -> str:
    return (
        f"{run.text!r}: typeface={run.typeface!r} ea={run.east_asian_typeface!r} "
        f"cs={run.complex_script_typeface!r} b={run.bold} i={run.italic} sz={run.size_pt} "
        f"color={run.color} alpha={run.color_alpha} spc={run.spc_pt} "
        f"baseline={run.baseline_offset} u={run.underline} strike={run.strike}"
    )


def _describe(shapes: list[Shape]) -> str:
    lines = []
    for position, shape in enumerate(shapes):
        if shape.kind != "text":
            continue
        lines.append(f"  [{position}] text box {shape.text[:60]!r}")
        lines.extend(f"      {_describe_run(run)}" for run in _runs(shape))
    return "\n".join(lines) or "  (no text boxes)"


def _box(shapes: list[Shape], fragment: str) -> Shape:
    """The one text box whose text contains ``fragment``, compared case-insensitively.

    Case-insensitive so a box is found before and after ``text-transform``.
    """
    matches = [
        shape for shape in text_shapes(shapes, "") if fragment.casefold() in shape.text.casefold()
    ]
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


def _runs_containing(shape: Shape, fragment: str) -> list[Run]:
    return [run for run in _runs(shape) if fragment in run.text]


def _box_runs(shape: Shape) -> str:
    return "\n".join(f"  {_describe_run(run)}" for run in _runs(shape))


# ---------------------------------------------------------------------------
# Colour arithmetic: blendOver, computed here independently
# ---------------------------------------------------------------------------


def _js_round(value: float) -> int:
    """JavaScript's ``Math.round``: a half rounds up, where Python's ``round`` rounds to even."""
    return math.floor(value + 0.5)


def _channels(color: str) -> tuple[int, int, int]:
    return tuple(int(color[position : position + 2], 16) for position in (0, 2, 4))


def blend_over(color: str, alpha: float, backdrop: str) -> str:
    """``blendOver(color, alpha, backdrop)``: each channel ``round(c*a + b*(1-a))``."""
    return "".join(
        f"{_js_round(channel * alpha + under * (1 - alpha)):02X}"
        for channel, under in zip(_channels(color), _channels(backdrop))
    )


def _gradient_midpoint(stops: tuple[str, ...]) -> tuple[float, ...]:
    """The exact colour at 50 % of a gradient line whose stops are evenly spaced.

    With an odd number of stops this is the middle stop itself; with an even
    number it lies halfway between the two middle stops.
    """
    position = (len(stops) - 1) / 2
    lower = math.floor(position)
    upper = math.ceil(position)
    fraction = position - lower
    return tuple(
        low + (high - low) * fraction
        for low, high in zip(_channels(stops[lower]), _channels(stops[upper]))
    )


def _channel_distance(color: str, expected: tuple[float, ...]) -> float:
    return max(abs(channel - target) for channel, target in zip(_channels(color), expected))


def _off_colour(shape: Shape, expected: str) -> list[str]:
    """The runs of ``shape`` that are not solid ``expected``, within one unit per channel."""
    return [
        _describe_run(run)
        for run in _runs(shape)
        if run.color is None
        or run.color_alpha is not None
        or _channel_distance(run.color, _channels(expected)) > CHANNEL_TOLERANCE
    ]


# ---------------------------------------------------------------------------
# Browser-side fixture guards
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def weights_fonts() -> dict[str, list[int]]:
    """The webfont weights the weights slide's page loaded, per family."""
    return browser_loaded_weights(_document("weights"))


def _guard_loaded(loaded: dict[str, list[int]], family: str, weight: int) -> None:
    assert weight in loaded.get(family, []), (
        f"environment: the page did not load {family} {weight} as a webfont (document.fonts "
        f"reports {loaded}); the deck's Google Fonts import must load for the weight-named "
        "typefaces to apply. Is fonts.googleapis.com reachable?"
    )


def _guard_style(document: str, selector: str, **expected: str) -> dict[str, str]:
    style = browser_style(document, selector)
    drift = {name: (style[name], value) for name, value in expected.items() if style[name] != value}
    assert not drift, f"fixture drift: {selector}'s computed (got, expected): {drift}"
    return style


def _tracked_cut_widths(
    document: str, style: dict[str, str], texts: list[str]
) -> list[tuple[float, float]]:
    """(browser cut, export cut) widths of each text in the element's face, with its tracking.

    Read with offscreen probes in the same page (``browser_probes``): the
    browser cut at the face's automatic optical size, as the page draws it; the
    export cut at ``font-variation-settings: 'opsz' 14``, the static cut
    PowerPoint and Google Slides draw (CALIBRATION.md A1). Both carry the
    element's own letter-spacing.
    """
    face = (
        f"font: {style['fontStyle']} {style['fontWeight']} {style['fontSize']} "
        f"{style['fontFamily']}; letter-spacing: {style['letterSpacing']}"
    )
    export_cut = f"{face}; font-variation-settings: 'opsz' {EXPORT_CUT_OPTICAL_SIZE}"
    sizes = browser_probes(document, [(text, css) for text in texts for css in (face, export_cut)])
    return [
        (sizes[position]["w"], sizes[position + 1]["w"]) for position in range(0, len(sizes), 2)
    ]


# ---------------------------------------------------------------------------
# Weights (spec §5 Weights)
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotRunWeights:
    @pytest.mark.parametrize(
        ("selector", "text", "weight", "typeface", "bold"),
        [
            pytest.param("#semibold", SEMIBOLD_TITLE, 600, "DM Sans SemiBold", False, id="600"),
            pytest.param("#medium", MEDIUM_TEXT, 500, "DM Sans Medium", False, id="500"),
            pytest.param("#bold", BOLD_TEXT, 700, "DM Sans", True, id="700"),
            pytest.param("#regular", REGULAR_TEXT, 400, "DM Sans", False, id="400"),
        ],
    )
    def test_webfont_weight_is_its_named_typeface(
        self,
        typography_pptx: bytes,
        weights_fonts: dict[str, list[int]],
        selector: str,
        text: str,
        weight: int,
        typeface: str,
        bold: bool,
    ) -> None:
        """DM Sans, a webfont the page loaded, at 400, 500, 600 and 700.

        Every run of the block is:

        * 600 (a 42 px ``.dk-title``): typeface ``DM Sans SemiBold``, ``b``
          absent or false, at 31.5 pt;
        * 500: ``DM Sans Medium``, not bold;
        * 700: ``DM Sans`` plus ``b="1"``, never a "DM Sans Bold" face;
        * 400: ``DM Sans``, not bold.

        A bold flag from 600 up turns the semibold title
        into a 700 rendering in PowerPoint. The static DM Sans fonts carry the
        weight-named legacy family names, so the named face renders the real
        weight. The guards first pin the computed weight and that the page
        loaded that weight as a webfont, the condition for naming it.
        """
        document = _document("weights")
        style = _guard_style(document, selector, fontWeight=str(weight))
        assert style["fontFamily"].startswith('"DM Sans"'), (
            f"fixture drift: {selector}'s family is {style['fontFamily']}"
        )
        if weight in WEIGHT_NAMES:
            _guard_loaded(weights_fonts, "DM Sans", weight)
        box = _box(_shapes(typography_pptx, "weights"), text)

        wrong = [
            _describe_run(run) for run in _runs(box) if (run.typeface, run.bold) != (typeface, bold)
        ]
        assert not wrong, (
            f"weight {weight}: every run must be typeface {typeface!r} with bold={bold}; "
            "these are not:\n  " + "\n  ".join(wrong)
        )
        if weight == 600:
            _guard_style(document, selector, fontSize="42px")
            sizes = {run.size_pt for run in _runs(box)}
            assert sizes == {42 * PT_PER_PX}, f"the 42 px title's runs are {sizes} pt"

    def test_non_webfont_family_at_600_is_bold_never_weight_named(
        self, typography_pptx: bytes, weights_fonts: dict[str, list[int]]
    ) -> None:
        """``font-family: system-ui, Arial`` at weight 600.

        ``system-ui`` is skipped, so the family is ``Arial``. Arial is not a
        webfont the page loaded, so the weight goes on the bold flag: every run
        is typeface ``Arial`` with ``b="1"``. Never "Arial SemiBold", a face no
        machine has, which PowerPoint replaces with its default font; never
        ``system-ui``, which no importer resolves.
        """
        _guard_style(
            _document("weights"), "#system-arial", fontWeight="600", fontFamily="system-ui, Arial"
        )
        assert "Arial" not in weights_fonts, (
            f"fixture drift: the page loaded Arial as a webfont: {weights_fonts}"
        )
        box = _box(_shapes(typography_pptx, "weights"), SYSTEM_ARIAL_TEXT)

        wrong = [
            _describe_run(run) for run in _runs(box) if (run.typeface, run.bold) != ("Arial", True)
        ]
        assert not wrong, (
            "system-ui, Arial at 600: every run must be typeface 'Arial' with bold; these are "
            "not:\n  " + "\n  ".join(wrong)
        )

    @pytest.mark.parametrize(
        ("element_id", "family", "text", "typeface"),
        [pytest.param(*case, id=case[0]) for case in FAMILY_CASES],
    )
    def test_family_is_the_first_real_face_with_generics_mapped(
        self, typography_pptx: bytes, element_id: str, family: str, text: str, typeface: str
    ) -> None:
        """The family is the first face in the stack that is not a generic keyword or a
        system alias, and a stack of generics alone maps to a face every machine has.

        * ``sans-serif`` is ``Arial``, ``serif`` is ``Times New Roman`` and
          ``monospace`` is ``Courier New``;
        * ``-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`` (the
          common platform stack) is ``Segoe UI``.

        A generic keyword or ``-apple-system`` written as a typeface name is
        a face no importer resolves.
        """
        box = _box(_shapes(typography_pptx, "families"), text)

        wrong = [_describe_run(run) for run in _runs(box) if run.typeface != typeface]
        assert not wrong, (
            f"font-family: {family}: every run must be typeface {typeface!r}; these are not:\n  "
            + "\n  ".join(wrong)
        )


# ---------------------------------------------------------------------------
# Element style inherited into runs, and per-run family
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotRunInheritance:
    def test_heading_weight_survives_its_line_break(self, typography_pptx: bytes) -> None:
        """Upstream PR #10: ``<h1 style="font-weight:700">Top<br>Bottom</h1>``.

        Both lines are bold ``DM Sans``. The legacy converter dropped an
        element's own bold as soon as it held any inline tag, ``<br>``
        included, so ``<br>`` titles came out regular.
        """
        box = _box(_shapes(typography_pptx, "inherited"), "Bottom")
        assert box.text.split("\n") == list(STACKED_LINES), f"the heading reads {box.text!r}"

        wrong = [
            _describe_run(run)
            for run in _runs(box)
            if run.text.strip() and (run.typeface, run.bold) != ("DM Sans", True)
        ]
        assert not wrong, (
            "every run of the 700 heading must be bold 'DM Sans'; these are not:\n  "
            + "\n  ".join(wrong)
        )

    def test_semibold_heading_reaches_its_coloured_span(self, typography_pptx: bytes) -> None:
        """A ``.dk-title`` ``<h2>`` (600) holding ``<span style="color:#FF3621">59%</span>``.

        Every run, the span's included, is ``DM Sans SemiBold`` and not bold:
        the heading's weight reaches its inline child. The span's run is
        ``FF3621`` and the rest keeps the heading's ink.
        """
        box = _box(_shapes(typography_pptx, "inherited"), ACCENTED_TITLE)

        wrong = [
            _describe_run(run)
            for run in _runs(box)
            if (run.typeface, run.bold) != ("DM Sans SemiBold", False)
        ]
        assert not wrong, (
            "every run of the 600 heading must be 'DM Sans SemiBold', not bold; these are not:\n  "
            + "\n  ".join(wrong)
        )
        assert _run(box, ACCENT_FIGURE).color == ACCENT_COLOR, (
            f"the span's run is not {ACCENT_COLOR}:\n{_box_runs(box)}"
        )
        others = [
            _describe_run(run)
            for run in _runs(box)
            if ACCENT_FIGURE not in run.text and run.color != INK
        ]
        assert not others, f"the heading's own text is not ink {INK}:\n  " + "\n  ".join(others)

    def test_chip_run_keeps_its_own_family(self, corpus_pptx: bytes) -> None:
        """Fixture 09: a DM Sans list item holding ``<code class="dk-chip">SKU-7</code>``.

        The ``SKU-7`` run is typeface ``DM Mono`` (the chip's ``var(--mono)``)
        while the sentence around it stays ``DM Sans``: the family is per run,
        so mono numerals never turn sans. The chip's padding cuts its line into
        items of their own, so the
        chip's run is in its own item and the sentence's are in the items of
        its two lines.
        """
        shapes = _corpus_shapes(corpus_pptx, "09")
        chip = _box(shapes, CHIP_TEXT)

        assert _run(chip, CHIP_TEXT).typeface == "DM Mono", (
            f"the {CHIP_TEXT} chip is not DM Mono:\n{_box_runs(chip)}"
        )
        sans = [
            _describe_run(run)
            for box in (_box(shapes, CHIP_LINE), _box(shapes, CHIP_SENTENCE_REST))
            for run in _runs(box)
            if run.text.strip() and run.typeface != "DM Sans"
        ]
        assert not sans, "the sentence around the chip is not DM Sans:\n  " + "\n  ".join(sans)


# ---------------------------------------------------------------------------
# Tracking, transforms, super/subscript and decorations
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotRunStyle:
    @pytest.mark.parametrize(
        ("selector", "text", "size_px", "em", "optical_size_delta"),
        [
            pytest.param(EYEBROW, EYEBROW_SOURCE_TEXT, 13, 0.16, False, id="eyebrow"),
            pytest.param(CORPUS_TITLE, CORPUS_TITLE_TEXT, 42, -0.01, True, id="title"),
        ],
    )
    def test_letter_spacing_is_spc(
        self,
        corpus_pptx: bytes,
        selector: str,
        text: str,
        size_px: float,
        em: float,
        optical_size_delta: bool,
    ) -> None:
        """Fixture 09: ``letter-spacing`` as ``spc``, in hundredths of a point.

        * the ``.dk-eyebrow`` (13 px, ``.16em``) has ``spc`` = round(13 x 0.16 x
          0.75 x 100) = 156, within 1. At 13 px the browser's automatic
          optical size is next to the export cut's 14, so the two widths agree
          within 0.5% (guarded here) and no optical-size delta applies;
        * the ``.dk-title`` (42 px, ``-.01em``) is drawn at the large optical
          size, and the static opsz-14 cut PowerPoint and Google Slides draw is
          about 10% wider (guarded here). So its ``spc`` is its CSS tracking plus
          the optical-size delta of CALIBRATION.md A1: (letterSpacingPx +
          (renderedWidth - exportCutWidth) / n) x 0.75 x 100, within 1, about
          -170. renderedWidth is the browser's width of the run, exportCutWidth
          the run's text at ``'opsz' 14`` with its own letter-spacing (a probe
          in the same page), and n its characters.

        Every run of the block carries it; a run without ``spc`` is untracked
        in PowerPoint.
        """
        document = corpus_document("09")
        style = _guard_style(document, selector, fontSize=f"{size_px}px")
        tracking_px = float(style["letterSpacing"].removesuffix("px"))
        assert math.isclose(tracking_px, size_px * em, abs_tol=0.005), (
            f"fixture drift: {selector}'s letter-spacing is {style['letterSpacing']}, expected "
            f"{size_px * em:.2f}px"
        )
        box = _box(_corpus_shapes(corpus_pptx, "09"), text)
        runs = _runs(box)
        widths = _tracked_cut_widths(document, style, [run.text for run in runs])
        differences = [
            (run.text, browser_cut, export_cut, abs(export_cut - browser_cut) / browser_cut)
            for run, (browser_cut, export_cut) in zip(runs, widths)
        ]
        if not optical_size_delta:
            expected = size_px * em * PT_PER_PX * HUNDREDTHS
            differ = [entry for entry in differences if entry[3] > OPTICAL_SIZE_THRESHOLD]
            assert not differ, (
                f"fixture drift: {selector}'s two optical-size cuts must agree within "
                f"{OPTICAL_SIZE_THRESHOLD:.1%}, so no delta applies; these do not (text, "
                f"browser px, export px, difference): {differ}"
            )
        else:
            agree = [entry for entry in differences if entry[3] <= OPTICAL_SIZE_THRESHOLD]
            assert not agree, (
                f"environment: {selector} is drawn at its automatic optical size, so the "
                f"opsz-{EXPORT_CUT_OPTICAL_SIZE} cut must be more than "
                f"{OPTICAL_SIZE_THRESHOLD:.1%} wider; these are not (text, browser px, export "
                f"px, difference): {agree}. Did the deck's Google Fonts import (DM Sans with "
                "its opsz axis) load?"
            )
            lines = browser_line_boxes(document, selector)
            assert [line["text"] for line in lines] == [text] and len(runs) == 1, (
                f"fixture drift: the title must render as one line and export as one run, so "
                f"the run's rendered width is the line's; it renders {lines} and exports "
                f"{[run.text for run in runs]}"
            )
            assert runs[0].text.isascii(), (
                "fixture drift: the title is no longer ASCII, so its characters are not its "
                "graphemes"
            )
            rendered = lines[0]["w"]
            export_cut = widths[0][1]
            delta_px = (rendered - export_cut) / len(runs[0].text)
            expected = (tracking_px + delta_px) * PT_PER_PX * HUNDREDTHS

        wrong = [
            _describe_run(run)
            for run in runs
            if abs(run.spc_pt * HUNDREDTHS - expected) > SPC_TOLERANCE_HUNDREDTHS
        ]
        assert not wrong, (
            f"{selector}: every run's spc must be {expected:.1f} hundredths of a point, within "
            f"{SPC_TOLERANCE_HUNDREDTHS:g}; these are not:\n  " + "\n  ".join(wrong)
        )

    def test_uppercase_transform_is_applied_to_the_run_text(self, corpus_pptx: bytes) -> None:
        """Fixture 09: the ``.dk-eyebrow`` source reads "What changed" under
        ``text-transform: uppercase``.

        The box reads exactly what the browser renders, "WHAT CHANGED"
        (``innerText``, which applies the transform), and every run is
        upper-case. The source text would export in mixed case.
        """
        document = corpus_document("09")
        _guard_style(document, EYEBROW, textTransform="uppercase")
        rendered = browser_text(document, EYEBROW)
        assert rendered == EYEBROW_SOURCE_TEXT.upper(), (
            f"fixture drift: the eyebrow renders {rendered!r}"
        )
        box = _box(_corpus_shapes(corpus_pptx, "09"), EYEBROW_SOURCE_TEXT)

        assert box.text == rendered, f"the eyebrow box reads {box.text!r}; the browser {rendered!r}"
        lower = [_describe_run(run) for run in _runs(box) if run.text != run.text.upper()]
        assert not lower, "runs are not upper-case:\n  " + "\n  ".join(lower)

    def test_capitalize_follows_the_browsers_word_boundaries(self, typography_pptx: bytes) -> None:
        """``text-transform: capitalize`` on "well-known (hello) 1st o’neil x-ray e.g. foo".

        The browser upper-cases a letter that follows anything other than a
        letter, a digit or an apostrophe, so it renders "Well-Known (Hello) 1st
        O’neil X-Ray E.G. Foo" (``innerText``). The box reads exactly that.
        Upper-casing only a letter after a space gives "Well-known … X-ray E.g.".
        """
        document = _document("capitalize")
        _guard_style(document, "#capitalized", textTransform="capitalize")
        rendered = browser_text(document, "#capitalized")
        assert rendered == CAPITALIZE_RENDERED, f"fixture drift: the paragraph renders {rendered!r}"
        box = _box(_shapes(typography_pptx, "capitalize"), "1st")

        assert box.text == rendered, f"the box reads {box.text!r}; the browser {rendered!r}"

    def test_capitalize_carries_across_a_wrapped_word(self, typography_pptx: bytes) -> None:
        """ "x-ray" under ``capitalize`` in a box too narrow for it.

        The browser breaks the word after its hyphen, so the word's range
        paints on two lines and the snapshot measures it code point by code
        point. The "r" after the hyphen still follows a non-letter: the box
        reads "X-Ray" across its two lines, as ``innerText`` does. Deciding each
        code point on its own upper-cases only the first and gives "X-ray".
        """
        document = _document("capitalize")
        lines = browser_lines(document, "#capitalized-wrap")
        assert len(lines) == 2, f"fixture drift: the word renders on the lines {lines}"
        rendered = browser_text(document, "#capitalized-wrap")
        assert rendered == CAPITALIZE_WRAPPED_RENDERED, (
            f"fixture drift: the word renders {rendered!r}"
        )
        shapes = _shapes(typography_pptx, "capitalize")
        boxes = [
            shape
            for shape in text_shapes(shapes, "")
            if shape.text.replace("\n", "").casefold() == CAPITALIZE_WRAPPED_SOURCE
        ]
        assert len(boxes) == 1, f"expected one box reading the wrapped word:\n{_describe(shapes)}"

        assert boxes[0].text.replace("\n", "") == rendered, (
            f"the wrapped word's box reads {boxes[0].text!r}; the browser {rendered!r}"
        )

    def test_footnote_marker_is_a_superscript_run(self, corpus_pptx: bytes) -> None:
        """Fixture 09: "gross profit<sup>1</sup>".

        The marker is its own run "1" with ``baseline="30000"``, and the
        "profit" before it sits on the baseline. A marker at the baseline reads
        as "profit1".
        """
        box = _box(_corpus_shapes(corpus_pptx, "09"), FOOTNOTE_LINE)

        marker = _run(box, FOOTNOTE_MARKER)
        assert marker.baseline_offset == SUPERSCRIPT_BASELINE, (
            f"the footnote marker's baseline is {marker.baseline_offset}, expected "
            f"{SUPERSCRIPT_BASELINE}:\n{_box_runs(box)}"
        )
        raised = [
            _describe_run(run)
            for run in _runs(box)
            if run is not marker and run.baseline_offset != 0
        ]
        assert not raised, "text other than the marker is off the baseline:\n  " + "\n  ".join(
            raised
        )

    def test_subscript_is_lowered(self, typography_pptx: bytes) -> None:
        """ "Water is H<sub>2</sub>O": the "2" is its own run with a negative ``baseline``
        (subscript), and the text around it sits on the baseline.
        """
        box = _box(_shapes(typography_pptx, "decorations"), CHEMISTRY_TEXT)

        digit = _run(box, "2")
        assert digit.baseline == "sub", (
            f"the subscript's baseline is {digit.baseline_offset}, expected a negative offset:\n"
            f"{_box_runs(box)}"
        )
        others = [
            _describe_run(run)
            for run in _runs(box)
            if run is not digit and run.baseline_offset != 0
        ]
        assert not others, "text other than the subscript is off the baseline:\n  " + "\n  ".join(
            others
        )

    def test_italic_runs_are_italic(self, corpus_pptx: bytes) -> None:
        """Fixture 09: ``<em>debt was repaid early</em>`` and the italic ``.dk-source`` line.

        Their runs carry ``i="1"``; "Interest expense fell as" before the
        ``<em>`` does not.
        """
        shapes = _corpus_shapes(corpus_pptx, "09")
        line = _box(shapes, ITALIC_LINE)
        source = _box(shapes, SOURCE_TEXT)

        assert _run(line, ITALIC_TEXT).italic, f"the <em> run is not italic:\n{_box_runs(line)}"
        assert not any(run.italic for run in _runs_containing(line, ITALIC_LINE)), (
            f"the text before the <em> is italic:\n{_box_runs(line)}"
        )
        upright = [_describe_run(run) for run in _runs(source) if not run.italic]
        assert not upright, "the .dk-source line is not italic:\n  " + "\n  ".join(upright)

    def test_underline_and_strike_through(self, typography_pptx: bytes) -> None:
        """``<u>Underlined</u> then <s>struck</s> then plain``.

        "Underlined" is underlined (``u`` other than ``none``), "struck" is
        struck through (``strike`` other than ``noStrike``), and the plain text
        is neither.
        """
        box = _box(_shapes(typography_pptx, "decorations"), DECORATED_TEXT)

        underlined = _run(box, "Underlined")
        struck = _run(box, "struck")
        assert (underlined.underline, underlined.strike) == (True, False), (
            f"'Underlined' is not underlined only:\n{_box_runs(box)}"
        )
        assert (struck.underline, struck.strike) == (False, True), (
            f"'struck' is not struck through only:\n{_box_runs(box)}"
        )
        plain = [
            _describe_run(run)
            for run in _runs(box)
            if run not in (underlined, struck) and (run.underline or run.strike)
        ]
        assert not plain, "plain text carries a decoration:\n  " + "\n  ".join(plain)

    def test_underline_reaches_a_nested_inline_child(self, typography_pptx: bytes) -> None:
        """``<u>Underlined <b>bold</b> words</u>``: the browser underlines "bold" too.

        A text decoration propagates to the inline content of the element that
        sets it, although ``text-decoration-line`` is not inherited: the
        ``<b>``'s own computed value is ``none``. So every run, "bold" (which is
        also bold) included, is underlined. Reading the decoration from the text
        node's parent alone drops it from "bold"; the same holds for a link's
        ``<strong>`` child.
        """
        box = _box(_shapes(typography_pptx, "decorations"), NESTED_UNDERLINE_TEXT)

        assert _run(box, "bold").bold, f"the <b> run is not bold:\n{_box_runs(box)}"
        plain = [_describe_run(run) for run in _runs(box) if run.text.strip() and not run.underline]
        assert not plain, "runs inside the <u> are not underlined:\n  " + "\n  ".join(plain)

    def test_text_loss_oracle_reports_nothing_missing(self, corpus_pptx: bytes) -> None:
        """The export fidelity harness's text-loss oracle on fixtures 09 and 13.

        Every word the browser renders (``innerText``, SVG and canvas excluded)
        is in the exported slide's text, including fixture 09's footnote
        marker ("profit1"), its uppercase eyebrow and its chip, and fixture 13's
        gradient words.
        """
        missing = text_loss(corpus_pptx, [corpus_document(prefix) for prefix in CORPUS_PREFIXES])

        lost = {prefix: words for prefix, words in zip(CORPUS_PREFIXES, missing) if words}
        assert not lost, f"words the browser renders are missing from the export: {lost}"


# ---------------------------------------------------------------------------
# Colour: pre-blended opacity and alpha, gradient and transparent text
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotRunColour:
    def test_faded_paragraph_is_blended_over_the_slide(self, typography_pptx: bytes) -> None:
        """A paragraph at ``opacity: .5`` in ``#1B3139`` on the ``#F9F7F4`` slide.

        Its run colour is ``blendOver('1B3139', .5, 'F9F7F4')``, solid, with no
        ``<a:alpha>``: Drive drops text alpha, so faded text would export at
        full strength.
        """
        _guard_style(_document("opacity"), "#faded", opacity="0.5", color="rgb(27, 49, 57)")
        expected = blend_over(INK, 0.5, PAPER)
        box = _box(_shapes(typography_pptx, "opacity"), FADED_TEXT)

        wrong = [
            _describe_run(run)
            for run in _runs(box)
            if (run.color, run.color_alpha) != (expected, None)
        ]
        assert not wrong, (
            f"the faded runs must be solid {expected} = blendOver({INK}, .5, {PAPER}) with no "
            "<a:alpha>; these are not:\n  " + "\n  ".join(wrong)
        )

    def test_translucent_colour_is_blended_over_its_card(self, typography_pptx: bytes) -> None:
        """``color: rgba(255, 255, 255, .7)`` inside a navy (``#1B3139``) card on the paper slide.

        The backdrop is the nearest ancestor with an opaque background, the
        card, not the slide: the run is ``blendOver('FFFFFF', .7, '1B3139')``,
        with no ``<a:alpha>``.
        """
        document = _document("opacity")
        _guard_style(document, "#on-navy", color="rgba(255, 255, 255, 0.7)")
        _guard_style(document, "#navy-card", backgroundColor="rgb(27, 49, 57)")
        expected = blend_over("FFFFFF", 0.7, NAVY)
        box = _box(_shapes(typography_pptx, "opacity"), ON_NAVY_TEXT)

        wrong = [
            _describe_run(run)
            for run in _runs(box)
            if (run.color, run.color_alpha) != (expected, None)
        ]
        assert not wrong, (
            f"the runs on navy must be solid {expected} = blendOver(FFFFFF, .7, {NAVY}) with no "
            "<a:alpha>; these are not:\n  " + "\n  ".join(wrong)
        )

    def test_translucent_backdrop_is_blended_over_its_own_backdrop(
        self, typography_pptx: bytes
    ) -> None:
        """``#1B3139`` text at ``opacity: .6`` inside a ``rgba(255, 95, 70, .10)`` tint on paper.

        The tint is first blended over the slide it sits on, and the text is
        blended over that: ``blendOver('1B3139', .6, blendOver('FF5F46', .1,
        'F9F7F4'))``, within one unit per channel for the intermediate
        rounding. Blending over the bare slide, or over the tint as if it were
        opaque, misses by several units.
        """
        document = _document("opacity")
        _guard_style(document, "#tinted", opacity="0.6", color="rgb(27, 49, 57)")
        _guard_style(document, "#tint-card", backgroundColor="rgba(255, 95, 70, 0.1)")
        tint, tint_alpha = TINT
        backdrop = blend_over(tint, tint_alpha, PAPER)
        expected = blend_over(INK, 0.6, backdrop)
        box = _box(_shapes(typography_pptx, "opacity"), TINTED_TEXT)

        wrong = [
            _describe_run(run)
            for run in _runs(box)
            if run.color is None
            or run.color_alpha is not None
            or _channel_distance(run.color, _channels(expected)) > CHANNEL_TOLERANCE
        ]
        assert not wrong, (
            f"the tinted runs must be solid {expected} = blendOver({INK}, .6, {backdrop}), where "
            f"{backdrop} = blendOver({tint}, {tint_alpha}, {PAPER}); these are not:\n  "
            + "\n  ".join(wrong)
        )

    def test_opacity_group_composites_its_own_background_first(
        self, typography_pptx: bytes
    ) -> None:
        """White text in a navy card that is itself at ``opacity: .5``, on the paper slide.

        The card is one opacity group. Inside it the opaque white text paints
        over the card's navy, and the whole group is then faded over the paper
        beneath it. So the text is ``blendOver(blendOver('FFFFFF', 1,
        '1B3139'), .5, 'F9F7F4')``, which is ``blendOver('FFFFFF', .5,
        'F9F7F4')``: near-white, within one unit per channel.

        Applying the cumulative opacity in one step over the nearest opaque
        background, the card's own navy, gives the mid-grey
        ``blendOver('FFFFFF', .5, '1B3139')``, which the browser never shows:
        the navy under the text is faded by the same group.
        """
        document = _document("groups")
        _guard_style(document, "#faded-card", opacity="0.5", backgroundColor="rgb(27, 49, 57)")
        _guard_style(document, "#faded-card-text", opacity="1", color="rgb(255, 255, 255)")
        inside_group = blend_over(WHITE, 1.0, NAVY)
        expected = blend_over(inside_group, FADED_CARD_OPACITY, PAPER)
        single_step = blend_over(WHITE, FADED_CARD_OPACITY, NAVY)
        assert _channel_distance(single_step, _channels(expected)) > 2 * CHANNEL_TOLERANCE, (
            f"the expected {expected} and the single-step {single_step} are too close to tell apart"
        )
        box = _box(_shapes(typography_pptx, "groups"), FADED_CARD_TEXT)

        grey = [
            _describe_run(run)
            for run in _runs(box)
            if run.color is not None
            and _channel_distance(run.color, _channels(single_step)) <= CHANNEL_TOLERANCE
        ]
        assert not grey, (
            f"the faded card's text is the single-step mid-grey {single_step} = blendOver({WHITE}, "
            f"{FADED_CARD_OPACITY}, {NAVY}); the group fades its own navy too:\n  "
            + "\n  ".join(grey)
        )
        wrong = _off_colour(box, expected)
        assert not wrong, (
            f"the faded card's runs must be solid {expected} = blendOver({inside_group}, "
            f"{FADED_CARD_OPACITY}, {PAPER}), where {inside_group} = "
            f"blendOver({WHITE}, 1, {NAVY}); these are not:\n  " + "\n  ".join(wrong)
        )

    def test_nested_opacity_groups_composite_inner_to_outer(self, typography_pptx: bytes) -> None:
        """Accent text in a translucent card (``opacity: .8``, white background) inside a
        faded section (``opacity: .5``, navy background), on the paper slide.

        Layer by layer, inner to outer:

        1. inside the card, the opaque ``#FF3621`` text over the card's white
           is ``FF3621``;
        2. the card group at .8 over the section's navy beneath it is
           ``blendOver('FF3621', .8, '1B3139')`` = ``D13526``;
        3. the section group at .5 over the paper beneath it is
           ``blendOver('D13526', .5, 'F9F7F4')`` = ``E5968D``.

        The run is that, solid, within one unit per channel. None of the
        shortcuts is: the cumulative .4 in one step over the card's white (the
        nearest opaque background), over the section's navy or over the paper,
        or the card's step with the section's fade dropped.
        """
        document = _document("groups")
        _guard_style(document, "#faded-section", opacity="0.5", backgroundColor="rgb(27, 49, 57)")
        _guard_style(
            document, "#translucent-card", opacity="0.8", backgroundColor="rgb(255, 255, 255)"
        )
        _guard_style(document, "#nested-card-text", opacity="1", color="rgb(255, 54, 33)")
        inside_card = blend_over(GROUP_ACCENT, 1.0, WHITE)
        card_over_section = blend_over(inside_card, TRANSLUCENT_CARD_OPACITY, NAVY)
        expected = blend_over(card_over_section, FADED_SECTION_OPACITY, PAPER)
        cumulative = TRANSLUCENT_CARD_OPACITY * FADED_SECTION_OPACITY
        shortcuts = {
            "the cumulative opacity over the card's white": blend_over(
                GROUP_ACCENT, cumulative, WHITE
            ),
            "the cumulative opacity over the section's navy": blend_over(
                GROUP_ACCENT, cumulative, NAVY
            ),
            "the cumulative opacity over the slide": blend_over(GROUP_ACCENT, cumulative, PAPER),
            "the card's step alone, the section's fade dropped": card_over_section,
        }
        close = {
            name: color
            for name, color in shortcuts.items()
            if _channel_distance(color, _channels(expected)) <= 2 * CHANNEL_TOLERANCE
        }
        assert not close, f"shortcuts too close to the expected {expected} to tell apart: {close}"
        box = _box(_shapes(typography_pptx, "groups"), NESTED_CARD_TEXT)

        shortcut_runs = [
            f"{_describe_run(run)} (= {name})"
            for run in _runs(box)
            for name, color in shortcuts.items()
            if run.color is not None
            and _channel_distance(run.color, _channels(color)) <= CHANNEL_TOLERANCE
        ]
        assert not shortcut_runs, (
            "the nested card's text took a one-step shortcut:\n  " + "\n  ".join(shortcut_runs)
        )
        wrong = _off_colour(box, expected)
        assert not wrong, (
            f"the nested card's runs must be solid {expected} = blendOver({card_over_section}, "
            f"{FADED_SECTION_OPACITY}, {PAPER}), where {card_over_section} = "
            f"blendOver({inside_card}, {TRANSLUCENT_CARD_OPACITY}, {NAVY}); these are not:\n  "
            + "\n  ".join(wrong)
        )

    def test_corpus_faded_paragraph_is_blended(self, corpus_pptx: bytes) -> None:
        """Fixture 13: "Restated FY23 figures use the same query." at ``opacity: 0.6``.

        Its runs are ``blendOver('1B3139', .6, 'F9F7F4')``, solid, with no
        ``<a:alpha>``: the corpus's own faded text.
        """
        expected = blend_over(INK, FADED_CORPUS_OPACITY, PAPER)
        box = _box(_corpus_shapes(corpus_pptx, "13"), FADED_CORPUS_TEXT)

        wrong = [
            _describe_run(run)
            for run in _runs(box)
            if (run.color, run.color_alpha) != (expected, None)
        ]
        assert not wrong, (
            f"the faded runs must be solid {expected} = blendOver({INK}, {FADED_CORPUS_OPACITY}, "
            f"{PAPER}) with no <a:alpha>; these are not:\n  " + "\n  ".join(wrong)
        )

    def test_transparent_text_is_never_opaque_black(self, typography_pptx: bytes) -> None:
        """``color: transparent`` text on the paper slide.

        The browser paints nothing. The export either leaves it out or writes
        it in its backdrop's colour, which is what ``blendOver`` gives at alpha
        0: solid ``F9F7F4``, no ``<a:alpha>``. Never the ``000000`` an
        unparseable or transparent colour used to fall back to, which paints
        black words the slide never showed.
        """
        _guard_style(_document("opacity"), "#invisible", color="rgba(0, 0, 0, 0)")
        boxes = [
            shape
            for shape in _shapes(typography_pptx, "opacity")
            if shape.kind == "text" and INVISIBLE_TEXT.casefold() in shape.text.casefold()
        ]
        assert len(boxes) <= 1, f"the transparent text is in {len(boxes)} boxes"

        visible = [
            _describe_run(run)
            for box in boxes
            for run in _runs(box)
            if (run.color, run.color_alpha) != (blend_over(OPAQUE_BLACK, 0.0, PAPER), None)
        ]
        assert not visible, (
            f"transparent text must be absent or solid {PAPER} (its backdrop); these runs would "
            "paint:\n  " + "\n  ".join(visible)
        )

    def test_gradient_text_is_the_gradients_middle_colour(self, corpus_pptx: bytes) -> None:
        """Fixture 13: ``.dk-gradtext`` "from the ledger", ``background-clip: text`` over
        ``linear-gradient(90deg, #FF3621, #FFB347)`` with ``color: transparent``.

        Its run is visible: a solid colour (no ``<a:alpha>``, never the
        ``000000`` a transparent colour fell back to) at the gradient's middle,
        within one unit per channel. With two stops the middle lies halfway
        between them, FF + FF, 36 + B3, 21 + 47 over two, so about ``FF7534``.
        The title's other runs keep the ink.
        """
        _guard_style(
            corpus_document("13"),
            GRADTEXT,
            backgroundImage=GRADTEXT_GRADIENT,
            backgroundClip="text",
            color="rgba(0, 0, 0, 0)",
        )
        middle = _gradient_midpoint(GRADTEXT_STOPS)
        box = _box(_corpus_shapes(corpus_pptx, "13"), GRADTEXT_WORDS)

        gradient = _run(box, GRADTEXT_WORDS)
        assert gradient.color is not None and gradient.color_alpha is None, (
            f"the gradient words are not a solid colour:\n{_box_runs(box)}"
        )
        assert _channel_distance(gradient.color, middle) <= CHANNEL_TOLERANCE, (
            f"the gradient words are {gradient.color}; the gradient's middle is "
            f"({', '.join(f'{channel:g}' for channel in middle)}) between {GRADTEXT_STOPS}:\n"
            f"{_box_runs(box)}"
        )
        for fragment in GRADTEXT_TITLE_RUNS:
            for run in _runs_containing(box, fragment):
                assert run.color == INK, (
                    f"the title's own text {run.text!r} is {run.color}, not ink {INK}"
                )

    def test_gradient_text_with_three_stops_is_the_middle_stop(
        self, typography_pptx: bytes
    ) -> None:
        """A heading clipped to ``linear-gradient(90deg, #FF3621, #00A972, #FFB347)``, holding
        an ``<em>``.

        Every run is the middle stop ``00A972`` (within one unit), solid: the
        heading's own text, and the ``<em>``'s, whose own ``background-image``
        is ``none`` and whose colour is the inherited transparent, because the
        browser paints the heading's gradient through all of its text.
        """
        _guard_style(
            _document("gradient"),
            "#three-stop",
            backgroundImage=THREE_STOP_GRADIENT,
            backgroundClip="text",
            color="rgba(0, 0, 0, 0)",
        )
        middle = _gradient_midpoint(THREE_STOPS)
        box = _box(_shapes(typography_pptx, "gradient"), THREE_STOP_TEXT)

        wrong = [
            _describe_run(run)
            for run in _runs(box)
            if run.color is None
            or run.color_alpha is not None
            or _channel_distance(run.color, middle) > CHANNEL_TOLERANCE
        ]
        assert not wrong, (
            f"every run must be the middle stop {THREE_STOPS[1]}, solid; these are not:\n  "
            + "\n  ".join(wrong)
        )

    @pytest.mark.parametrize(
        ("element_id", "gradient", "text"),
        [pytest.param(*case, id=case[0]) for case in LENGTH_STOP_CASES],
    )
    def test_gradient_text_with_length_stops_is_visible(
        self, typography_pptx: bytes, element_id: str, gradient: str, text: str
    ) -> None:
        """Gradient text whose stops sit at lengths: ``#FF3621 0px, #FFB347 300px``, and in em.

        Chrome computes both to px stops ("rgb(255, 54, 33) 0px"). The run still
        shows the gradient: solid, never the paper the transparent text would
        otherwise take from its backdrop, and within one unit per channel of the
        gradient's middle with its two stops spaced evenly (about ``FF7534``).
        """
        style = _guard_style(
            _document("length-stops"),
            f"#{element_id}",
            backgroundClip="text",
            color="rgba(0, 0, 0, 0)",
        )
        assert re.search(r"\) [\d.]+px,", style["backgroundImage"]), (
            f"fixture drift: {gradient} computes to {style['backgroundImage']}, "
            "not stops placed in px"
        )
        middle = _gradient_midpoint(GRADTEXT_STOPS)
        box = _box(_shapes(typography_pptx, "length-stops"), text)

        invisible = [_describe_run(run) for run in _runs(box) if run.color == PAPER]
        assert not invisible, (
            f"the length-stop gradient text is the paper {PAPER}, so it is invisible:\n  "
            + "\n  ".join(invisible)
        )
        wrong = [
            _describe_run(run)
            for run in _runs(box)
            if run.color is None
            or run.color_alpha is not None
            or _channel_distance(run.color, middle) > CHANNEL_TOLERANCE
        ]
        assert not wrong, (
            f"every run must be the gradient's middle "
            f"({', '.join(f'{channel:g}' for channel in middle)}), solid; these are not:\n  "
            + "\n  ".join(wrong)
        )

    def test_text_fill_colour_idiom_shows_the_gradient(self, typography_pptx: bytes) -> None:
        """``-webkit-text-fill-color: transparent`` over an opaque ink ``color``.

        The headline has a ``background-color`` fallback under its gradient, and
        both are clipped to the glyphs. The glyphs paint with the fill colour,
        not ``color``, so the gradient shows through them. Every run is the
        gradient's middle stop ``00A972`` (it covers the fallback), solid, and
        never the ink that ``color`` alone would give.
        """
        _guard_style(
            _document("fill-idiom"),
            "#fill-idiom",
            color="rgb(27, 49, 57)",
            webkitTextFillColor="rgba(0, 0, 0, 0)",
            backgroundColor="rgb(255, 54, 33)",
            backgroundImage=THREE_STOP_GRADIENT,
            backgroundClip="text",
        )
        middle = _gradient_midpoint(THREE_STOPS)
        box = _box(_shapes(typography_pptx, "fill-idiom"), FILL_IDIOM_TEXT)

        inked = [_describe_run(run) for run in _runs(box) if run.color == INK]
        assert not inked, (
            "the headline is painted in its `color` ink, not its transparent fill:\n  "
            + "\n  ".join(inked)
        )
        wrong = [
            _describe_run(run)
            for run in _runs(box)
            if run.color is None
            or run.color_alpha is not None
            or _channel_distance(run.color, middle) > CHANNEL_TOLERANCE
        ]
        assert not wrong, (
            f"every run must be the gradient's middle stop {THREE_STOPS[1]}, solid; these are "
            "not:\n  " + "\n  ".join(wrong)
        )

    def test_text_clipped_background_paints_no_box(self, typography_pptx: bytes) -> None:
        """The same headline's ``background-color`` (``FF3621``) is clipped to its glyphs.

        ``background-clip: text`` paints the background inside the letters
        only, where the run's colour already carries it. So no shape is drawn
        behind the headline: a solid box there would hide the gradient text, and
        the browser paints none.
        """
        shapes = _shapes(typography_pptx, "fill-idiom")
        box = _box(shapes, FILL_IDIOM_TEXT)

        behind = [
            f"{shape.geometry} fill={shape.fill} at ({shape.x:.0f}, {shape.y:.0f}) "
            f"{shape.w:.0f}x{shape.h:.0f}"
            for shape in shapes
            if shape.kind == "shape"
            and min(shape.x + shape.w, box.x + box.w) > max(shape.x, box.x)
            and min(shape.y + shape.h, box.y + box.h) > max(shape.y, box.y)
        ]
        assert not behind, "a shape is drawn behind the text-clipped headline:\n  " + "\n  ".join(
            behind
        )


# ---------------------------------------------------------------------------
# CJK, emoji and right-to-left text
# ---------------------------------------------------------------------------


@pytest.mark.slow
@requires_huashu_sidecar
class TestSnapshotRunScripts:
    def test_cjk_and_emoji_text_is_intact_and_in_order(self, typography_pptx: bytes) -> None:
        """A paragraph ``季度收入增长 12% 🎉``.

        Its box reads exactly that, as the browser renders it, with every
        character in order, and its runs name the CSS family in ``a:latin`` and
        ``a:ea``, so the East Asian text keeps the deck's face.
        """
        lines = browser_lines(_document("scripts"), "#cjk")
        assert lines == [CJK_TEXT], f"fixture drift: the paragraph renders {lines}"
        box = _box(_shapes(typography_pptx, "scripts"), "12%")

        assert box.text == CJK_TEXT, f"the box reads {box.text!r}; the browser {CJK_TEXT!r}"
        faces = [
            _describe_run(run)
            for run in _runs(box)
            if (run.typeface, run.east_asian_typeface) != ("DM Sans", "DM Sans")
        ]
        assert not faces, "runs do not name DM Sans for latin and ea:\n  " + "\n  ".join(faces)

    def test_rtl_paragraph_is_rtl_with_its_text_intact(self, typography_pptx: bytes) -> None:
        """``<p dir="rtl">مرحبا بالعالم</p>``.

        Its one paragraph has ``rtl="1"``, its text reads exactly the source in
        logical order (as the browser renders it), and its runs name the CSS
        family in ``a:cs``, so the complex-script text keeps the deck's face.
        """
        lines = browser_lines(_document("scripts"), "#rtl")
        assert lines == [RTL_TEXT], f"fixture drift: the paragraph renders {lines}"
        _guard_style(_document("scripts"), "#rtl", direction="rtl")
        box = _box(_shapes(typography_pptx, "scripts"), RTL_TEXT)

        assert box.text == RTL_TEXT, f"the box reads {box.text!r}; the browser {RTL_TEXT!r}"
        assert [para.rtl for para in box.paras] == [True], (
            f"the paragraph's rtl flags are {[para.rtl for para in box.paras]}"
        )
        faces = [
            _describe_run(run)
            for run in _runs(box)
            if (run.typeface, run.complex_script_typeface) != ("DM Sans", "DM Sans")
        ]
        assert not faces, "runs do not name DM Sans for latin and cs:\n  " + "\n  ".join(faces)


# ---------------------------------------------------------------------------
# emit_typography.cjs in Node, without a browser
# ---------------------------------------------------------------------------


def _typography(call: str) -> object:
    """Evaluate ``call``, an expression over the module bound as ``typography``, in Node."""
    script = (
        f"const typography = require({json.dumps(str(TYPOGRAPHY_MODULE))});"
        f"process.stdout.write(JSON.stringify({call}));"
    )
    return node_json(script)


def _typeface_for(family: str, weight: int, loaded: list[int]) -> object:
    return _typography(
        f"typography.typefaceFor({json.dumps(family)}, {weight}, {json.dumps(loaded)})"
    )


@requires_node
class TestTypographyModule:
    @pytest.mark.parametrize(
        ("family", "weight", "loaded", "expected"),
        [
            pytest.param(
                "DM Sans",
                600,
                DM_SANS_WEIGHTS,
                {"fontFace": "DM Sans SemiBold", "bold": False},
                id="dm-sans-600",
            ),
            pytest.param(
                "DM Sans",
                700,
                DM_SANS_WEIGHTS,
                {"fontFace": "DM Sans", "bold": True},
                id="dm-sans-700",
            ),
            pytest.param(
                "Arial", 600, [], {"fontFace": "Arial", "bold": True}, id="arial-600-not-loaded"
            ),
            pytest.param(
                "Impact", 700, [], {"fontFace": "Impact", "bold": False}, id="impact-single-weight"
            ),
        ],
    )
    def test_typeface_for_the_briefs_examples(
        self, family: str, weight: int, loaded: list[int], expected: dict
    ) -> None:
        """``typefaceFor(family, weight, loadedWeights)`` for four kinds of face.

        * DM Sans 600, loaded: the ``DM Sans SemiBold`` face, not bold;
        * DM Sans 700: ``DM Sans`` plus bold;
        * Arial 600, not a loaded webfont: ``Arial`` plus bold, never "Arial SemiBold";
        * Impact 700, a single-weight face: ``Impact``, not bold.

        ``bold`` is a boolean either way, never absent.
        """
        result = _typeface_for(family, weight, loaded)

        assert isinstance(result, dict), f"typefaceFor returned {result!r}"
        assert {key: result.get(key) for key in expected} == expected, (
            f"typefaceFor({family!r}, {weight}, {loaded}) is {result}, expected {expected}"
        )

    @pytest.mark.parametrize("weight", ALL_WEIGHTS)
    def test_typeface_for_names_every_loaded_weight(self, weight: int) -> None:
        """Spec §5 Weights, ``WEIGHT_NAMES``, for a webfont loaded at every weight.

        400 is ``DM Sans`` and 700 is ``DM Sans`` plus bold; every other weight
        is ``DM Sans <name>`` (Thin, ExtraLight, Light, Medium, SemiBold,
        ExtraBold, Black) and not bold, so 800 and 900 are never bold-synthesised.
        """
        name = WEIGHT_NAMES.get(weight)
        expected = {
            "fontFace": "DM Sans" if name is None else f"DM Sans {name}",
            "bold": weight == 700,
        }

        result = _typeface_for("DM Sans", weight, ALL_WEIGHTS)

        assert isinstance(result, dict), f"typefaceFor returned {result!r}"
        assert {key: result.get(key) for key in expected} == expected, (
            f"typefaceFor('DM Sans', {weight}, all weights) is {result}, expected {expected}"
        )

    @pytest.mark.parametrize(
        ("weight", "expected"),
        [
            pytest.param(600, {"fontFace": "DM Sans", "bold": True}, id="600-paints-700"),
            pytest.param(800, {"fontFace": "DM Sans", "bold": True}, id="800-paints-700"),
            pytest.param(300, {"fontFace": "DM Sans", "bold": False}, id="300-paints-400"),
        ],
    )
    def test_typeface_for_an_unloaded_weight_is_the_face_the_browser_paints(
        self, weight: int, expected: dict
    ) -> None:
        """DM Sans with only 400 and 700 loaded, asked for a weight the page did not load.

        CSS font matching (CSS Fonts 4 §5.2) paints 600 and 800 with the 700
        face and 300 with the 400 face, so the typeface is the matched face's:
        ``DM Sans`` plus bold, or ``DM Sans``. Naming the requested weight
        instead ("DM Sans SemiBold", "DM Sans ExtraBold", "DM Sans Light")
        writes a weight the slide never showed.
        """
        result = _typeface_for("DM Sans", weight, [400, 700])

        assert isinstance(result, dict), f"typefaceFor returned {result!r}"
        assert {key: result.get(key) for key in expected} == expected, (
            f"typefaceFor('DM Sans', {weight}, [400, 700]) is {result}, expected {expected}"
        )

    def test_typeface_for_arial_black_is_never_bold(self) -> None:
        """Arial Black ships one weight, so a bold flag would only smear it.

        At 900, a weight the browser paints with that one face, the typeface is
        ``Arial Black`` and not bold, like Impact.
        """
        result = _typeface_for("Arial Black", 900, [])

        assert result == {"fontFace": "Arial Black", "bold": False}, (
            f"typefaceFor('Arial Black', 900, []) is {result}"
        )

    def test_run_options_escape_the_typeface_for_xml(self) -> None:
        """A CSS family named with ``&``, ``"`` and ``<``.

        pptxgenjs writes the typeface into ``typeface="…"`` as is, so
        ``runOptions`` escapes it. Written that way, the attribute parses as XML
        and reads back the family exactly. Unescaped, the slide part would not
        parse.
        """
        family = 'Ben & "Jerry" <Sans>'
        run = {
            "text": "x",
            "family": family,
            "weight": 400,
            "italic": False,
            "sizePx": 20,
            "color": INK,
            "letterSpacingPx": 0,
            "underline": False,
            "strike": False,
            "baseline": None,
        }

        result = _typography(f"typography.runOptions({json.dumps(run)}, {{}})")

        assert isinstance(result, dict), f"runOptions returned {result!r}"
        attribute = f'<latin typeface="{result["fontFace"]}"/>'
        try:
            parsed = etree.fromstring(attribute)
        except etree.XMLSyntaxError as error:
            pytest.fail(f"the typeface as pptxgenjs writes it, {attribute}, is not XML: {error}")
        assert parsed.get("typeface") == family, (
            f"the typeface reads back {parsed.get('typeface')!r}, not {family!r}"
        )

    @pytest.mark.parametrize(
        ("color", "alpha", "backdrop"),
        [
            pytest.param(INK, 0.5, PAPER, id="brief-example"),
            pytest.param("FFFFFF", 0.7, NAVY, id="white-on-navy"),
            pytest.param("FF3621", 1.0, PAPER, id="opaque-is-the-colour"),
            pytest.param(INK, 0.0, PAPER, id="transparent-is-the-backdrop"),
        ],
    )
    def test_blend_over(self, color: str, alpha: float, backdrop: str) -> None:
        """``blendOver(color, alpha, backdrop)``: each channel ``round(c*a + b*(1-a))`` as hex.

        The example ``blendOver('1B3139', 0.5, 'F9F7F4')``, plus the
        white-on-navy case and the two ends: alpha 1 is the colour itself and
        alpha 0 is the backdrop.
        """
        expected = blend_over(color, alpha, backdrop)

        result = _typography(
            f"typography.blendOver({json.dumps(color)}, {alpha}, {json.dumps(backdrop)})"
        )

        assert isinstance(result, str) and result.upper() == expected, (
            f"blendOver({color!r}, {alpha}, {backdrop!r}) is {result!r}, expected {expected}"
        )
