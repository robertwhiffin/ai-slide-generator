"""Text metric calibration for the snapshot export engine, against PowerPoint and Google Slides.

The snapshot engine writes each text box at the browser's first glyph top,
raised by a first-line offset. Line spacing is written against the renderers'
single spacing, 1.2 x the font size: up to it as a percentage with soft
breaks, beyond it as single-spaced lines, each its own
paragraph, with the extra leading as space before (``emit_text.cjs``). Runs
carry optical-size tracking, and superscript and subscript runs are enlarged
for the renderers' own shrink. This script measures how PowerPoint for Mac and
Google Slides actually draw that, against the browser:

1. exports the probe deck ``tests/fixtures/export_snapshot/text_calibration.html``
   through the snapshot engine, with the corpus ``deck.css`` (DM Sans with its
   ``opsz`` axis, and DM Mono, from Google Fonts);
2. screenshots the browser truth at device scale 2, renders the deck written
   for PowerPoint (``target="pptx"``) in PowerPoint
   (``run.render_with_powerpoint``; its PDF is re-rasterised at 4x), and
   converts the deck written for Google Slides (``target="gslides"``, as the
   Google Slides export writes it) in Google Slides
   (``run.render_with_google_slides``, 1600 px thumbnails); each renderer's
   probes are read against its own deck's text boxes;
3. finds each probe's lines in all three images by pixel analysis: inside the
   probe's cell, the rows whose darkest pixel passes half the cell's peak ink
   are a line's ink band, from cap top to baseline, its edges interpolated to
   a fraction of a pixel;
4. prints, per renderer and in 1280 px units, every spacing probe's ink-top
   error (renderer minus browser) and pitch error, both at the constants the
   emitter has now and at offset 0, the least-squares ``A``, ``B`` and ``C`` of
   ``offset = A x (pct/100 - 1) x 1.2 x sizePx + B x sizePx + C x ascentPx``
   (``pct`` at most 100, ``ascentPx`` the browser's glyph top to baseline,
   measured in the page with ``tests/fixtures/export_snapshot/measure.cjs``),
   and the constants that minimise the largest error over both renderers;
5. prints the optical-size width residuals (A1), the renderers' superscript and
   subscript shrink (A2), and the render checks (A3): whether PowerPoint opens
   the deck without a repair prompt, whether either renderer outlines a box
   with no border, and whether justified lines stretch past the browser's.

Usage (from the repo root)::

    uv run --with pymupdf --with pillow python scripts/export_fidelity/calibrate_text.py \\
        --out /tmp/calib

``--no-powerpoint`` or ``--no-gslides`` skips a renderer. Everything measured is
also written to ``<out>/calibration.json`` and the tables to
``<out>/calibration.md``; the chosen constants and their residuals are
recorded by hand in ``scripts/export_fidelity/CALIBRATION.md``.
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import re
import subprocess
import threading
import time
import urllib.error
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from lxml import etree

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "export_snapshot" / "text_calibration.html"
CORPUS_DIR = REPO_ROOT / "tests" / "fixtures" / "export_fidelity"
SIDECAR_DIR = REPO_ROOT / "services" / "pptx-emit-huashu"
EMIT_TEXT_MODULE = SIDECAR_DIR / "emit_text.cjs"
EMIT_TYPOGRAPHY_MODULE = SIDECAR_DIR / "emit_typography.cjs"

SLIDE_WIDTH_PX = 1280
TRUTH_SCALE = 2
POWERPOINT_SCALE = 4
# PowerPoint opens, exports and closes the deck within this, or it is held by a dialog.
POWERPOINT_TIMEOUT_SECONDS = 240
# A refused Google API call (the thumbnail endpoint's per-minute limit) is retried after a pause.
GOOGLE_ATTEMPTS = 3
GOOGLE_RETRY_SECONDS = 45

EMU_PER_PX = 9525
NAMESPACES = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
# DrawingML percentages are 1000ths of a percent; sz is hundredths of a point.
PERCENT_UNITS = 100000
PT_PER_PX = 0.75

# A row or column is ink when its darkest pixel reaches this share of the cell's peak.
INK_THRESHOLD = 0.5
# Bands thinner than this (1280 px units) are antialiasing specks, not lines.
MIN_BAND_PX = 2.0
# The cell's outer edge is left out of its window: a neighbour's antialiasing may touch it.
WINDOW_INSET_PX = 2.0
# Acceptance at 1280 px width.
MAX_INK_TOP_ERROR_PX = 2.0
MAX_PITCH_ERROR_PX = 1.0
# An outline is a perimeter darker than both the fill and the ground by this much (0..255).
OUTLINE_CONTRAST = 40
# A justified line stretches when its ink ends this far past the browser's.
STRETCH_TOLERANCE_PX = 2.0
NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


def load_harness():
    """``scripts/export_fidelity/run.py``, imported by path (it is a script, not a package)."""
    spec = importlib.util.spec_from_file_location("export_fidelity_harness", SCRIPT_DIR / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# The probe deck
# ---------------------------------------------------------------------------


@dataclass
class Cell:
    slide: int
    kind: str
    attributes: dict[str, str]
    left: float
    top: float
    width: float
    height: float
    padding_top: float  # where the cell's text starts, below its top

    @property
    def label(self) -> str:
        attributes = self.attributes
        if self.kind == "spacing":
            return (
                f"{attributes['data-family']} {attributes['data-weight']} "
                f"{attributes['data-size']}px lh {attributes['data-line-height']} "
                f"x{attributes['data-lines']}"
            )
        if self.kind == "width":
            return attributes["data-name"]
        if self.kind == "script":
            return f"{attributes['data-script']} {attributes['data-size']}px"
        if self.kind == "outline":
            return "bordered" if attributes["data-bordered"] == "1" else "unbordered"
        return self.kind


@dataclass
class ProbeDeck:
    css: str = ""
    slides: list[tuple[str, str]] = field(default_factory=list)
    cells: list[Cell] = field(default_factory=list)


class _DeckParser(HTMLParser):
    """Splits the fixture into its slides, its calibration CSS and its cells."""

    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=True)
        self.source = source
        self.line_offsets = [0]
        for line in source.splitlines(keepends=True):
            self.line_offsets.append(self.line_offsets[-1] + len(line))
        self.deck = ProbeDeck()
        self.depth = 0
        self.slide_start: int | None = None
        self.slide_name = ""
        self.in_style = False

    def _offset(self) -> int:
        line, column = self.getpos()
        return self.line_offsets[line - 1] + column

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name: value or "" for name, value in attrs}
        if tag == "style" and "data-calibration-css" in attributes:
            self.in_style = True
        if tag != "div":
            return
        if self.depth == 0 and "data-calibration-slide" in attributes:
            self.slide_start = self._offset()
            self.slide_name = attributes["data-calibration-slide"]
        elif self.slide_start is not None and "data-probe" in attributes:
            style = dict(
                (name.strip(), value.strip())
                for name, value in (
                    part.split(":", 1) for part in attributes["style"].split(";") if ":" in part
                )
            )
            self.deck.cells.append(
                Cell(
                    slide=len(self.deck.slides),
                    kind=attributes["data-probe"],
                    attributes=attributes,
                    left=float(style["left"].removesuffix("px")),
                    top=float(style["top"].removesuffix("px")),
                    width=float(style["width"].removesuffix("px")),
                    height=float(style["height"].removesuffix("px")),
                    padding_top=float(style.get("padding", "0px").split()[0].removesuffix("px")),
                )
            )
        self.depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self.in_style = False
        if tag != "div":
            return
        self.depth -= 1
        if self.depth == 0 and self.slide_start is not None:
            end = self.source.index(">", self._offset()) + 1
            self.deck.slides.append((self.slide_name, self.source[self.slide_start : end]))
            self.slide_start = None

    def handle_data(self, data: str) -> None:
        if self.in_style:
            self.deck.css += data


def load_probe_deck(path: Path = FIXTURE) -> ProbeDeck:
    parser = _DeckParser(path.read_text(encoding="utf-8"))
    parser.feed(parser.source)
    parser.close()
    return parser.deck


# ---------------------------------------------------------------------------
# The emitter's constants and the exported boxes
# ---------------------------------------------------------------------------


def emitter_constant(module: Path, name: str) -> float | None:
    match = re.search(
        rf"^[ \t]*const[ \t]+{name}[ \t]*=[ \t]*({NUMBER})[ \t]*;",
        module.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    return float(match.group(1)) if match else None


def current_constants() -> dict[str, float]:
    superscript = emitter_constant(EMIT_TYPOGRAPHY_MODULE, "SUPERSCRIPT_SIZE_FACTOR")
    subscript = emitter_constant(EMIT_TYPOGRAPHY_MODULE, "SUBSCRIPT_SIZE_FACTOR")
    return {
        "FIRST_LINE_A": emitter_constant(EMIT_TEXT_MODULE, "FIRST_LINE_A") or 0.0,
        "FIRST_LINE_B": emitter_constant(EMIT_TEXT_MODULE, "FIRST_LINE_B") or 0.0,
        "FIRST_LINE_C": emitter_constant(EMIT_TEXT_MODULE, "FIRST_LINE_C") or 0.0,
        "SUPERSCRIPT_SIZE_FACTOR": superscript or 1.0,
        "SUBSCRIPT_SIZE_FACTOR": subscript or superscript or 1.0,
    }


@dataclass
class TextBox:
    x: float
    y: float
    w: float
    h: float
    spacing_pct: float | None  # the first paragraph's spcPct, as a percentage
    line_points: bool  # some paragraph's line spacing is in points (spcPts in lnSpc)
    before_pts: list[float | None]  # each paragraph's space before (spcBef spcPts), in pt
    runs: list[dict]
    paragraphs: int
    pprs: list[int]  # a:pPr count per a:p
    identical_pprs: bool  # every a:pPr inside one a:p is the same


def _slide_parts(archive: zipfile.ZipFile) -> list[str]:
    presentation = etree.fromstring(archive.read("ppt/presentation.xml"))
    relationships = etree.fromstring(archive.read("ppt/_rels/presentation.xml.rels"))
    targets = {
        relationship.get("Id"): "ppt/" + relationship.get("Target").lstrip("/").removeprefix("ppt/")
        for relationship in relationships
    }
    ids = presentation.findall("p:sldIdLst/p:sldId", NAMESPACES)
    return [targets[slide_id.get(f"{{{NAMESPACES['r']}}}id")] for slide_id in ids]


def _space_before(paragraph: etree._Element) -> float | None:
    points = paragraph.find("a:pPr/a:spcBef/a:spcPts", NAMESPACES)
    return None if points is None else int(points.get("val")) / 100


def exported_text_boxes(pptx_path: Path) -> list[list[TextBox]]:
    """Every slide's text boxes, with their geometry in px and what the calibration reads."""
    slides = []
    with zipfile.ZipFile(pptx_path) as archive:
        for part in _slide_parts(archive):
            root = etree.fromstring(archive.read(part))
            boxes = []
            for shape in root.iterfind(".//p:sp", NAMESPACES):
                body = shape.find("p:txBody", NAMESPACES)
                offset = shape.find("p:spPr/a:xfrm/a:off", NAMESPACES)
                extent = shape.find("p:spPr/a:xfrm/a:ext", NAMESPACES)
                if body is None or offset is None:
                    continue
                paragraphs = body.findall("a:p", NAMESPACES)
                spacing = body.find("a:p/a:pPr/a:lnSpc/a:spcPct", NAMESPACES)
                runs = []
                for run in body.iterfind(".//a:r", NAMESPACES):
                    properties = run.find("a:rPr", NAMESPACES)
                    attributes = {} if properties is None else properties.attrib
                    runs.append(
                        {
                            "text": "".join(
                                text.text or "" for text in run.iterfind("a:t", NAMESPACES)
                            ),
                            "sz": int(attributes.get("sz", 0)),
                            "spc": int(attributes.get("spc", 0)),
                            "baseline": int(attributes.get("baseline", 0)),
                        }
                    )
                boxes.append(
                    TextBox(
                        x=int(offset.get("x")) / EMU_PER_PX,
                        y=int(offset.get("y")) / EMU_PER_PX,
                        w=int(extent.get("cx")) / EMU_PER_PX,
                        h=int(extent.get("cy")) / EMU_PER_PX,
                        spacing_pct=(
                            None
                            if spacing is None
                            else int(spacing.get("val")) * 100 / PERCENT_UNITS
                        ),
                        line_points=body.find(".//a:lnSpc/a:spcPts", NAMESPACES) is not None,
                        before_pts=[_space_before(paragraph) for paragraph in paragraphs],
                        runs=runs,
                        paragraphs=len(paragraphs),
                        pprs=[
                            len(paragraph.findall("a:pPr", NAMESPACES)) for paragraph in paragraphs
                        ],
                        identical_pprs=all(
                            len(
                                {
                                    etree.tostring(ppr)
                                    for ppr in paragraph.findall("a:pPr", NAMESPACES)
                                }
                            )
                            <= 1
                            for paragraph in paragraphs
                        ),
                    )
                )
            slides.append(boxes)
    return slides


def box_in_cell(boxes: list[TextBox], cell: Cell) -> TextBox | None:
    """The cell's own text box: its left edge in the cell, its top nearest the cell's text.

    The top is the browser's glyph top raised by the first-line offset, so it
    sits near where the cell's padding puts the text, a little above or below.
    """
    text_top = cell.top + cell.padding_top
    candidates = [box for box in boxes if cell.left <= box.x <= cell.left + cell.width]
    if not candidates:
        return None
    nearest = min(candidates, key=lambda box: abs(box.y - text_top))
    return nearest if abs(nearest.y - text_top) < cell.height / 2 else None


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_truth(documents: list[Path], out_dir: Path) -> None:
    truth_dir = out_dir / "truth"
    truth_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "node",
            str(SCRIPT_DIR / "render_truth.cjs"),
            f"--scale={TRUTH_SCALE}",
            str(truth_dir),
            *map(str, documents),
        ],
        check=True,
        capture_output=True,
    )


def render_powerpoint(harness, pptx_path: Path, names: list[str], out_dir: Path) -> dict:
    """PowerPoint's render, or how it failed: a repair prompt holds the AppleScript ``open``.

    The harness renders through AppleScript (open, save as PDF, close). When
    that does not finish within POWERPOINT_TIMEOUT_SECONDS a dialog (a repair
    prompt) is holding it, and a watchdog closes the harness's own staged
    presentation (run.close_harness_presentations). PowerPoint is never quit:
    the owner's other documents stay open, unsaved work included, and the
    dialog is left for the owner to dismiss. The PDF the harness copied into
    ``out_dir`` (it returns its path) is re-rasterised at POWERPOINT_SCALE for
    sub-pixel edges.
    """
    import fitz  # pymupdf

    outcome: dict = {}

    def render() -> None:
        try:
            outcome["pdf"] = harness.render_with_powerpoint(pptx_path, names, out_dir)
            outcome["finished"] = True
        except subprocess.CalledProcessError as error:
            outcome["error"] = (error.stderr or b"").decode("utf-8", "replace").strip()
        except IndexError:
            outcome["error"] = "the PDF PowerPoint saved has more pages than the deck has slides"

    started = time.monotonic()
    worker = threading.Thread(target=render, daemon=True)
    worker.start()
    worker.join(POWERPOINT_TIMEOUT_SECONDS)
    seconds = round(time.monotonic() - started, 1)
    if worker.is_alive():
        closed = harness.close_harness_presentations()
        worker.join(harness.POWERPOINT_CLOSE_TIMEOUT_SECONDS)
        outcome_of_close = (
            "the harness's own presentation was closed"
            if closed
            else "PowerPoint did not answer, so its dialog needs dismissing by hand"
        )
        return {
            "opened": False,
            "seconds": seconds,
            "detail": f"no PDF within {POWERPOINT_TIMEOUT_SECONDS} s: PowerPoint was held, "
            f"a dialog such as a repair prompt; {outcome_of_close} (PowerPoint was not quit)",
        }
    if not outcome.get("finished"):
        return {"opened": False, "seconds": seconds, "detail": outcome.get("error", "failed")}
    pdf = fitz.open(outcome["pdf"])
    high_dir = out_dir / "powerpoint_x4"
    high_dir.mkdir(parents=True, exist_ok=True)
    for index, page in enumerate(pdf):
        zoom = SLIDE_WIDTH_PX * POWERPOINT_SCALE / page.rect.width
        page.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).save(str(high_dir / f"{names[index]}.png"))
    return {
        "opened": True,
        "seconds": seconds,
        "detail": "opened, saved as PDF and closed with no dialog",
    }


def render_google_slides(harness, pptx_path: Path, names: list[str], out_dir: Path) -> str:
    """The harness's Google Slides render, retried after a pause when an API call is refused.

    The thumbnail endpoint is rate limited per minute; a refused call is
    transient, so the whole conversion is redone (each attempt leaves its own
    presentation in Drive, as the harness does).
    """
    for attempt in range(1, GOOGLE_ATTEMPTS + 1):
        try:
            return harness.render_with_google_slides(pptx_path, names, out_dir)
        except urllib.error.HTTPError as error:
            if attempt == GOOGLE_ATTEMPTS:
                raise
            print(
                f"Google Slides refused a call (HTTP {error.code}); "
                f"retrying in {GOOGLE_RETRY_SECONDS} s"
            )
            time.sleep(GOOGLE_RETRY_SECONDS)
    raise AssertionError("unreachable")


# ---------------------------------------------------------------------------
# Ink
# ---------------------------------------------------------------------------


class Ink:
    """One image's ink, in 1280 px slide units: rows and columns where the glyphs are."""

    def __init__(self, path: Path) -> None:
        from PIL import Image, ImageOps

        image = Image.open(path).convert("L")
        self.scale = image.width / SLIDE_WIDTH_PX
        self.luminance = image
        # Coverage 0..255: white ground is 0, black ink 255.
        self.coverage = ImageOps.invert(image)

    def _box(self, left: float, top: float, right: float, bottom: float) -> tuple[int, ...]:
        return (
            max(0, int(left * self.scale)),
            max(0, int(top * self.scale)),
            min(self.coverage.width, int(right * self.scale + 0.999)),
            min(self.coverage.height, int(bottom * self.scale + 0.999)),
        )

    def _profile(self, box: tuple[int, ...], rows: bool) -> list[float]:
        left, top, right, bottom = box
        if rows:
            return [
                self.coverage.crop((left, y, right, y + 1)).getextrema()[1] / 255
                for y in range(top, bottom)
            ]
        return [
            self.coverage.crop((x, top, x + 1, bottom)).getextrema()[1] / 255
            for x in range(left, right)
        ]

    def bands(self, window: tuple[float, float, float, float]) -> list[dict]:
        """The ink bands in the window, top to bottom: ``{top, bottom, left, right}``, px.

        A band is a run of rows whose darkest pixel reaches INK_THRESHOLD of the
        window's darkest. Each edge is where the profile crosses that level,
        interpolated between pixel centres; left and right come from the
        band's own columns the same way.
        """
        box = self._box(*window)
        rows = self._profile(box, rows=True)
        peak = max(rows, default=0)
        if peak <= 0:
            return []
        level = peak * INK_THRESHOLD
        found = []
        start = None
        for index in range(len(rows) + 1):
            inked = index < len(rows) and rows[index] >= level
            if inked and start is None:
                start = index
            elif not inked and start is not None:
                found.append((start, index - 1))
                start = None
        bands = []
        for first, last in found:
            top = _crossing(rows, first, level, rising=True) + box[1]
            bottom = _crossing(rows, last, level, rising=False) + box[1]
            if (bottom - top) / self.scale < MIN_BAND_PX:
                continue
            band_box = (box[0], box[1] + first, box[2], box[1] + last + 1)
            columns = self._profile(band_box, rows=False)
            column_level = max(columns) * INK_THRESHOLD
            inked = [index for index, value in enumerate(columns) if value >= column_level]
            left = _crossing(columns, inked[0], column_level, rising=True) + box[0]
            right = _crossing(columns, inked[-1], column_level, rising=False) + box[0]
            bands.append(
                {
                    "top": top / self.scale,
                    "bottom": bottom / self.scale,
                    "left": left / self.scale,
                    "right": right / self.scale,
                }
            )
        return bands

    def luminance_in(self, window: tuple[float, float, float, float]) -> tuple[int, int]:
        """(darkest, lightest) luminance 0..255 in the window."""
        return self.luminance.crop(self._box(*window)).getextrema()


def _crossing(profile: list[float], index: int, level: float, rising: bool) -> float:
    """Where the profile crosses ``level`` at the band edge ``index``, in pixel coordinates.

    Pixel i spans [i, i + 1) with its centre at i + 0.5. A rising edge lies
    between the centre of the last row below the level and ``index``'s; a
    falling edge between ``index``'s and the next's.
    """
    neighbour = index - 1 if rising else index + 1
    inside = profile[index]
    outside = profile[neighbour] if 0 <= neighbour < len(profile) else 0.0
    if inside == outside:
        return float(index if rising else index + 1)
    fraction = (level - outside) / (inside - outside)
    return (neighbour + 0.5) + (index - neighbour) * fraction


def window_of(cell: Cell) -> tuple[float, float, float, float]:
    return (
        cell.left + WINDOW_INSET_PX,
        cell.top + WINDOW_INSET_PX,
        cell.left + cell.width - WINDOW_INSET_PX,
        cell.top + cell.height - WINDOW_INSET_PX,
    )


# ---------------------------------------------------------------------------
# Measurements
# ---------------------------------------------------------------------------


# The renderers' single spacing, as a multiple of the font size (emit_text.cjs).
RENDERER_SINGLE_SPACING_EM = 1.2
# Lawson's iteration for the minimax fit; it converges to the Chebyshev solution.
MINIMAX_ITERATIONS = 4000
MEASURE_SCRIPT = REPO_ROOT / "tests" / "fixtures" / "export_snapshot" / "measure.cjs"
OFFSET_TERMS = ("FIRST_LINE_A", "FIRST_LINE_B", "FIRST_LINE_C")


def page_ascents(documents: list[Path], cells: list[Cell]) -> dict[int, float]:
    """Each spacing cell's ascent in its own page, keyed by the cell's index.

    The browser's glyph top to baseline for the cell's face and size, read with
    ``measure.cjs --mode=probe`` and a baseline probe: the snapshot measures the
    same thing for every paragraph's largest run, and the fit's ascent term
    must see the value the export used.
    """
    ascents: dict[int, float] = {}
    for slide, document in enumerate(documents):
        indexed = [
            (index, cell)
            for index, cell in enumerate(cells)
            if cell.slide == slide and cell.kind == "spacing"
        ]
        if not indexed:
            continue
        probes = [
            {
                "text": "Hg",
                "css": (
                    f"font-family:'{cell.attributes['data-family']}'; "
                    f"font-weight:{cell.attributes['data-weight']}; "
                    f"font-size:{cell.attributes['data-size']}px; line-height:normal"
                ),
                "baseline": True,
            }
            for _, cell in indexed
        ]
        measured = subprocess.run(
            ["node", str(MEASURE_SCRIPT), str(document), json.dumps(probes), "--mode=probe"],
            cwd=SIDECAR_DIR,
            check=True,
            capture_output=True,
            text=True,
        )
        sizes = json.loads(measured.stdout)
        for (index, _), size in zip(indexed, sizes):
            ascents[index] = float(size["ascent"])
    return ascents


def spacing_probe(
    cell: Cell,
    box: TextBox | None,
    ascent: float,
    truth: list[dict],
    render: list[dict],
    constants: dict[str, float],
) -> dict:
    """One spacing probe in one renderer: ink-top and pitch errors, and the offset terms.

    ``u = (pct/100 - 1) x 1.2 x sizePx``, ``v = sizePx`` and ``w = ascentPx`` are
    the terms of the first-line offset (pct is the first paragraph's spcPct,
    100 without one); ``offset0Error`` is the error with no offset at all (the
    measured error plus the offset the box was emitted with), which the fit
    explains as ``A x u + B x v + C x w``. ``encoding`` is how the lines were
    written: ``single`` (one line), ``percent`` (spcPct with soft breaks) or
    ``space-before`` (a paragraph per line, spcBef on the lines after the first).
    """
    size = float(cell.attributes["data-size"])
    lines = int(cell.attributes["data-lines"])
    pct = box.spacing_pct if box and box.spacing_pct else 100.0
    u = (pct / 100 - 1) * RENDERER_SINGLE_SPACING_EM * size
    emitted_offset = (
        constants["FIRST_LINE_A"] * u
        + constants["FIRST_LINE_B"] * size
        + constants["FIRST_LINE_C"] * ascent
    )
    if box is None or lines == 1:
        encoding = "single"
    elif box.paragraphs > 1:
        encoding = "space-before"
    else:
        encoding = "percent"
    result = {
        "label": cell.label,
        "size": size,
        "lines": lines,
        "pct": pct,
        "encoding": encoding,
        "spaceBeforePt": [value for value in (box.before_pts if box else []) if value],
        "u": u,
        "v": size,
        "w": ascent,
        "emittedOffset": emitted_offset,
        "truthLines": len(truth),
        "renderLines": len(render),
    }
    if len(truth) != lines or len(render) != lines:
        result["error"] = f"expected {lines} line(s): browser {len(truth)}, renderer {len(render)}"
        return result
    result["inkTopError"] = render[0]["top"] - truth[0]["top"]
    result["offset0Error"] = result["inkTopError"] + emitted_offset
    result["pitchErrors"] = [
        (render[index + 1]["top"] - render[index]["top"])
        - (truth[index + 1]["top"] - truth[index]["top"])
        for index in range(lines - 1)
    ]
    return result


def _terms(row: dict) -> tuple[float, float, float]:
    return row["u"], row["v"], row["w"]


def residual(row: dict, constants: tuple[float, float, float]) -> float:
    """The ink-top error left with ``constants`` (A, B, C) applied."""
    return row["offset0Error"] - sum(c * t for c, t in zip(constants, _terms(row)))


def largest_residual(rows: list[dict], constants: tuple[float, float, float]) -> float:
    return max(abs(residual(row, constants)) for row in rows)


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting; a singular column solves to 0."""
    size = len(vector)
    rows = [matrix[index][:] + [vector[index]] for index in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda index: abs(rows[index][column]))
        rows[column], rows[pivot] = rows[pivot], rows[column]
        if abs(rows[column][column]) < 1e-12:
            continue
        for index in range(size):
            if index != column:
                factor = rows[index][column] / rows[column][column]
                rows[index] = [a - factor * b for a, b in zip(rows[index], rows[column])]
    return [
        rows[index][size] / rows[index][index] if abs(rows[index][index]) >= 1e-12 else 0.0
        for index in range(size)
    ]


def _weighted_least_squares(rows: list[dict], weights: list[float]) -> tuple[float, ...]:
    matrix = [[0.0] * 3 for _ in range(3)]
    vector = [0.0] * 3
    for row, weight in zip(rows, weights):
        terms = _terms(row)
        for i in range(3):
            vector[i] += weight * terms[i] * row["offset0Error"]
            for j in range(3):
                matrix[i][j] += weight * terms[i] * terms[j]
    return tuple(_solve(matrix, vector))


def least_squares(rows: list[dict]) -> tuple[float, ...]:
    """(A, B, C) minimising the squared offset-0 errors left after A x u + B x v + C x w."""
    return _weighted_least_squares(rows, [1.0] * len(rows))


def minimax(rows: list[dict]) -> tuple[float, ...]:
    """(A, B, C) minimising the largest residual over ``rows`` (Lawson's algorithm).

    Weighted least squares, reweighting every probe by its residual each round,
    converges to the Chebyshev (minimax) fit; the best constants seen are kept.
    """
    weights = [1.0 / len(rows)] * len(rows)
    best = least_squares(rows)
    best_error = largest_residual(rows, best)
    for _ in range(MINIMAX_ITERATIONS):
        constants = _weighted_least_squares(rows, weights)
        errors = [abs(residual(row, constants)) for row in rows]
        largest = max(errors)
        if largest < best_error:
            best, best_error = constants, largest
        total = sum(weight * error for weight, error in zip(weights, errors))
        if total <= 0:
            break
        weights = [weight * error / total for weight, error in zip(weights, errors)]
    return best


def width_probe(cell: Cell, box: TextBox | None, truth: list[dict], render: list[dict]) -> dict:
    """A1: line count and ink width per line, renderer against browser."""
    expected = int(cell.attributes["data-lines"])
    result = {
        "label": cell.label,
        "expectedLines": expected,
        "truthLines": len(truth),
        "renderLines": len(render),
        "wrapped": len(render) != len(truth),
        "spc": sorted({run["spc"] for run in box.runs}) if box else None,
        "lines": [],
    }
    for truth_line, render_line in zip(truth, render):
        truth_width = truth_line["right"] - truth_line["left"]
        render_width = render_line["right"] - render_line["left"]
        result["lines"].append(
            {
                "browserWidth": truth_width,
                "renderWidth": render_width,
                "residual": render_width - truth_width,
                "residualPct": 100 * (render_width / truth_width - 1),
                "leftError": render_line["left"] - truth_line["left"],
            }
        )
    return result


def script_heights(
    cells: list[Cell], images: dict[str, dict[str, Ink]], names: list[str]
) -> dict[str, dict]:
    """A2: each script probe's ink height in every image, keyed "super 64px" and so on.

    ``images`` is slide name -> image kind ("truth" and each renderer) -> Ink.
    """
    heights = {}
    for cell in cells:
        heights[cell.label] = {}
        for kind, ink in images[names[cell.slide]].items():
            bands = ink.bands(window_of(cell))
            if len(bands) == 1:
                heights[cell.label][kind] = bands[0]["bottom"] - bands[0]["top"]
    return heights


def script_factors(
    cells: list[Cell], heights: dict[str, dict], constants: dict[str, float], renderers: list[str]
) -> list[dict]:
    """The renderers' shrink for each script and size.

    The script run was emitted at the browser's size over the current factor,
    the plain probe at the browser's size itself, so the true factor is the
    current one times (script / plain in the renderer) / (script / plain in the
    browser).
    """
    factors = []
    sizes = sorted({cell.attributes["data-size"] for cell in cells}, key=float, reverse=True)
    for script, name in (("super", "SUPERSCRIPT_SIZE_FACTOR"), ("sub", "SUBSCRIPT_SIZE_FACTOR")):
        for size in sizes:
            measured = heights.get(f"{script} {size}px", {})
            plain = heights.get(f"plain {size}px", {})
            if "truth" not in measured or "truth" not in plain:
                continue
            browser_ratio = measured["truth"] / plain["truth"]
            for renderer in renderers:
                if renderer not in measured or renderer not in plain:
                    continue
                ratio = measured[renderer] / plain[renderer]
                factors.append(
                    {
                        "script": script,
                        "size": float(size),
                        "renderer": renderer,
                        "emittedFactor": constants[name],
                        "renderedOverBrowser": ratio / browser_ratio,
                        "factor": constants[name] * ratio / browser_ratio,
                    }
                )
    return factors


def outline_probe(cell: Cell, ink: Ink) -> dict:
    """A3: the darkest luminance along the box's edge against its fill and the ground."""
    x, y, w, h = (float(value) for value in cell.attributes["data-box"].split(","))
    ring = 2.0
    edges = [
        (x - ring, y - ring, x + w + ring, y + ring),
        (x - ring, y + h - ring, x + w + ring, y + h + ring),
        (x - ring, y - ring, x + ring, y + h + ring),
        (x + w - ring, y - ring, x + w + ring, y + h + ring),
    ]
    edge = min(ink.luminance_in(window)[0] for window in edges)
    fill = ink.luminance_in((x + w / 2 - 4, y + h / 2 - 4, x + w / 2 + 4, y + h / 2 + 4))[0]
    ground = ink.luminance_in((x - 30, y + h / 2 - 4, x - 22, y + h / 2 + 4))[0]
    return {
        "label": cell.label,
        "edgeDarkest": edge,
        "fill": fill,
        "ground": ground,
        "outlined": edge < min(fill, ground) - OUTLINE_CONTRAST,
    }


def justify_probe(cell: Cell, truth: list[dict], render: list[dict]) -> dict:
    """A3: each justified line's right ink edge, renderer against browser (the last is ragged)."""
    lines = []
    for index, (truth_line, render_line) in enumerate(zip(truth, render)):
        lines.append(
            {
                "line": index + 1,
                "browserRight": truth_line["right"],
                "renderRight": render_line["right"],
                "pastBrowser": render_line["right"] - truth_line["right"],
            }
        )
    stretched = [line for line in lines[:-1] if line["pastBrowser"] > STRETCH_TOLERANCE_PX]
    return {
        "truthLines": len(truth),
        "renderLines": len(render),
        "lines": lines,
        "stretched": bool(stretched) or len(render) != len(truth),
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _format(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:+.{digits}f}"


def _mean_pitch_error(row: dict) -> float:
    return sum(row["pitchErrors"]) / len(row["pitchErrors"])


def spacing_summary(rows: list[dict], constants: tuple[float, ...]) -> dict:
    """The largest errors over ``rows``: ink-top at the run's constants and after
    ``constants``, pitch per line pair and per probe (the mean of its pairs, free
    of the browser's own half-pixel snapping)."""
    multi = [row for row in rows if row["lines"] > 1]
    return {
        "probes": len(rows),
        "inkTop": max((abs(row["inkTopError"]) for row in rows), default=0.0),
        "inkTopAfter": max((abs(residual(row, constants)) for row in rows), default=0.0),
        "pitchPair": max((abs(v) for row in multi for v in row["pitchErrors"]), default=0.0),
        "pitchMean": max((abs(_mean_pitch_error(row)) for row in multi), default=0.0),
    }


def spacing_table(renderer: str, rows: list[dict], constants: tuple[float, ...]) -> list[str]:
    lines = [
        f"#### {renderer}: spacing probes (px at 1280 wide; + is lower in the renderer)",
        "",
        "| probe | encoding | pct | spcBef pt | ink-top error | at offset 0 | after chosen "
        "constants | pitch errors (mean) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        before = ", ".join(f"{value:g}" for value in row["spaceBeforePt"]) or "-"
        if "error" in row:
            lines.append(
                f"| {row['label']} | {row['encoding']} | {row['pct']:.1f} | {before} | "
                f"{row['error']} | | | |"
            )
            continue
        pitches = "-"
        if row["pitchErrors"]:
            pitches = ", ".join(_format(value) for value in row["pitchErrors"])
            pitches += f" ({_format(_mean_pitch_error(row))})"
        lines.append(
            f"| {row['label']} | {row['encoding']} | {row['pct']:.1f} | {before} | "
            f"{_format(row['inkTopError'])} | {_format(row['offset0Error'])} | "
            f"{_format(residual(row, constants))} | {pitches} |"
        )
    return lines


def _is_brief_probe(row: dict) -> bool:
    """The acceptance probe set: DM Sans and DM Mono (Arial and Georgia are extra)."""
    return row["label"].startswith("DM ")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--no-powerpoint", action="store_true", help="skip PowerPoint for Mac")
    parser.add_argument("--no-gslides", action="store_true", help="skip Google Slides")
    args = parser.parse_args()
    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    harness = load_harness()
    probe_deck = load_probe_deck()
    names = [name for name, _ in probe_deck.slides]
    deck = json.loads((CORPUS_DIR / "deck.json").read_text(encoding="utf-8"))
    deck["css"] = (CORPUS_DIR / "deck.css").read_text(encoding="utf-8") + "\n" + probe_deck.css
    # The probe deck draws no chart: the corpus's chart script would only look for its canvas.
    deck["scripts"] = ""
    deck["external_scripts"] = []
    documents = harness.build_documents(deck, probe_deck.slides, out_dir)
    render_truth(documents, out_dir)
    # Each app gets the deck written for it, as the two exports write them.
    pptx_path = harness.export_pptx(deck, documents, out_dir, target="pptx")
    gslides_path = harness.export_pptx(
        deck, documents, out_dir, target="gslides"
    )
    boxes = exported_text_boxes(pptx_path)
    renderer_boxes = {"powerpoint": boxes, "gslides": exported_text_boxes(gslides_path)}
    constants = current_constants()

    renderers: dict[str, Path] = {}
    report: dict = {
        "date": datetime.date.today().isoformat(),
        "constants": constants,
        "pptx": str(pptx_path),
        "gslidesPptx": str(gslides_path),
        "lineSpacingInPoints": any(box.line_points for slide in boxes for box in slide),
        "identicalPprs": all(box.identical_pprs for slide in boxes for box in slide),
        "maxPprPerParagraph": max(
            (count for slide in boxes for box in slide for count in box.pprs), default=0
        ),
    }
    if not args.no_powerpoint:
        report["powerpoint"] = render_powerpoint(harness, pptx_path, names, out_dir)
        print(
            "PowerPoint:", report["powerpoint"]["detail"], f"({report['powerpoint']['seconds']} s)"
        )
        if report["powerpoint"]["opened"]:
            renderers["powerpoint"] = out_dir / "powerpoint_x4"
    if not args.no_gslides:
        report["gslidesUrl"] = render_google_slides(harness, gslides_path, names, out_dir)
        print("Google Slides:", report["gslidesUrl"])
        renderers["gslides"] = out_dir / "gslides"

    images: dict[str, dict[str, Ink]] = {}
    for index, name in enumerate(names):
        images[name] = {"truth": Ink(out_dir / "truth" / f"{name}.png")}
        for renderer, directory in renderers.items():
            images[name][renderer] = Ink(directory / f"{name}.png")

    spacing: dict[str, list[dict]] = {renderer: [] for renderer in renderers}
    widths: dict[str, list[dict]] = {renderer: [] for renderer in renderers}
    outlines: dict[str, list[dict]] = {renderer: [] for renderer in renderers}
    justify: dict[str, dict] = {}
    ascents = page_ascents(documents, probe_deck.cells)
    for cell_index, cell in enumerate(probe_deck.cells):
        slide_images = images[names[cell.slide]]
        window = window_of(cell)
        if cell.kind in ("spacing", "width", "justify"):
            truth = slide_images["truth"].bands(window)
            for renderer in renderers:
                box = box_in_cell(renderer_boxes[renderer][cell.slide], cell)
                render = slide_images[renderer].bands(window)
                if cell.kind == "spacing":
                    spacing[renderer].append(
                        spacing_probe(cell, box, ascents[cell_index], truth, render, constants)
                    )
                elif cell.kind == "width":
                    widths[renderer].append(width_probe(cell, box, truth, render))
                else:
                    justify[renderer] = justify_probe(cell, truth, render)
        elif cell.kind == "outline":
            for renderer in renderers:
                outlines[renderer].append(outline_probe(cell, slide_images[renderer]))
    script_cells = [cell for cell in probe_deck.cells if cell.kind == "script"]
    heights = script_heights(script_cells, images, names)
    factors = script_factors(script_cells, heights, constants, list(renderers))

    measured = {
        renderer: [row for row in rows if "error" not in row] for renderer, rows in spacing.items()
    }
    fits = {renderer: least_squares(rows) for renderer, rows in measured.items() if rows}
    every = [row for rows in measured.values() for row in rows]
    chosen = minimax(every) if every else (0.0, 0.0, 0.0)
    current = tuple(constants[name] for name in OFFSET_TERMS)
    summaries = {
        renderer: {
            "brief": spacing_summary([row for row in rows if _is_brief_probe(row)], chosen),
            "all": spacing_summary(rows, chosen),
            "mismatchedLines": len(spacing[renderer]) - len(rows),
        }
        for renderer, rows in measured.items()
    }
    report.update(
        {
            "spacing": spacing,
            "leastSquares": fits,
            "minimax": chosen,
            "minimaxLargestResidual": largest_residual(every, chosen) if every else None,
            "summaries": summaries,
            "widths": widths,
            "scriptHeights": heights,
            "scriptFactors": factors,
            "outlines": outlines,
            "justify": justify,
        }
    )

    lines = [f"# Text calibration run, {report['date']}", ""]
    lines.append(
        "Emitter constants for this run: "
        + ", ".join(f"{name} = {constants[name]:g}" for name in OFFSET_TERMS)
        + f", SUPERSCRIPT_SIZE_FACTOR = {constants['SUPERSCRIPT_SIZE_FACTOR']:g}, subscript "
        f"factor = {constants['SUBSCRIPT_SIZE_FACTOR']:g}."
    )
    lines.append(
        f"Line spacing in points anywhere: {report['lineSpacingInPoints']}; every a:pPr in an "
        f"a:p identical: {report['identicalPprs']}; most a:pPr in one a:p: "
        f"{report['maxPprPerParagraph']}."
    )
    lines.append("")
    lines.append(
        "| renderer | probes | max ink-top error, this run | max ink-top error, chosen "
        "constants | max pitch error per pair | max pitch error per probe (mean) | "
        "line-count mismatches |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    for renderer, summary in summaries.items():
        for scope in ("brief", "all"):
            values = summary[scope]
            name = "DM Sans + DM Mono" if scope == "brief" else "all fonts"
            lines.append(
                f"| {renderer} | {name} ({values['probes']}) | {values['inkTop']:.2f} | "
                f"{values['inkTopAfter']:.2f} | {values['pitchPair']:.2f} | "
                f"{values['pitchMean']:.2f} | {summary['mismatchedLines']} |"
            )
    lines.append("")
    lines.append(f"Limits: ink-top {MAX_INK_TOP_ERROR_PX:g} px, pitch {MAX_PITCH_ERROR_PX:g} px.")
    lines.append("")
    for renderer, fitted in fits.items():
        lines.append(
            f"- Least squares, {renderer} alone: "
            + ", ".join(f"{name} = {value:.4f}" for name, value in zip(OFFSET_TERMS, fitted))
            + f"; largest residual {largest_residual(measured[renderer], fitted):.2f} px."
        )
    lines.append(
        "- **Minimax over both renderers:** "
        + ", ".join(f"{name} = {value:.4f}" for name, value in zip(OFFSET_TERMS, chosen))
        + f"; largest residual {report['minimaxLargestResidual'] or 0:.2f} px."
    )
    if every:
        lines.append(
            "- The run's own constants leave a largest residual of "
            f"{largest_residual(every, current):.2f} px."
        )
    lines.append("")
    for renderer, rows in spacing.items():
        lines.extend(spacing_table(renderer, rows, chosen))
        lines.append("")
    lines.append("#### Optical-size widths (A1)")
    lines.append("")
    lines.append(
        "| renderer | probe | lines (browser / renderer) | spc | per-line ink width residual |"
    )
    lines.append("|---|---|---|---|---|")
    for renderer, rows in widths.items():
        for row in rows:
            residuals = "; ".join(
                f"{line['browserWidth']:.1f} -> {line['renderWidth']:.1f} "
                f"({line['residual']:+.1f} px, {line['residualPct']:+.2f}%)"
                for line in row["lines"]
            )
            lines.append(
                f"| {renderer} | {row['label']} | {row['truthLines']} / {row['renderLines']} | "
                f"{row['spc']} | {residuals} |"
            )
    lines.append("")
    lines.append("#### Script size (A2)")
    lines.append("")
    lines.append("| script | size | renderer | emitted factor | rendered / browser | true factor |")
    lines.append("|---|---|---|---|---|---|")
    for row in factors:
        lines.append(
            f"| {row['script']} | {row['size']:g} | {row['renderer']} | {row['emittedFactor']:g} | "
            f"{row['renderedOverBrowser']:.4f} | {row['factor']:.4f} |"
        )
    lines.append("")
    lines.append("#### Render checks (A3)")
    lines.append("")
    if "powerpoint" in report:
        lines.append(f"- PowerPoint open: {report['powerpoint']['detail']}.")
    for renderer, rows in outlines.items():
        for row in rows:
            lines.append(
                f"- {renderer} {row['label']} box: edge darkest {row['edgeDarkest']}, fill "
                f"{row['fill']}, ground {row['ground']}: outlined = {row['outlined']}."
            )
    for renderer, row in justify.items():
        past = ", ".join(f"{line['pastBrowser']:+.1f}" for line in row["lines"])
        lines.append(
            f"- {renderer} justified paragraph: lines {row['truthLines']} / {row['renderLines']}, "
            f"right edge past the browser's per line: {past}: stretched = {row['stretched']}."
        )
    text = "\n".join(lines) + "\n"
    (out_dir / "calibration.md").write_text(text, encoding="utf-8")
    (out_dir / "calibration.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
