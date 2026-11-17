"""Shared helpers for the snapshot-engine export tests (``tests/unit/test_export_snapshot_*.py``).

The snapshot engine (``services/pptx-emit-huashu/render_slide.cjs``) reads the
rendered page and emits what the browser painted. Its tests are behavioural:
they export real slide documents through the production wrapper and read the
emitted slide XML back, comparing geometry, colours and stacking order against
what the browser itself laid out for the same document.

* ``export_slides`` / ``export_corpus`` run the production export
  (``build_slide_html`` then ``build_pptx_huashu``) with the engine selected
  through ``TELLR_EXPORT_ENGINE``.
* ``slide_shapes`` parses one slide's ``spTree`` with lxml into ``Shape``
  records, in z-order, with geometry in CSS px (``EMU / 9525``);
  ``slide_xml`` is the slide part itself and ``slide_shape_elements`` each
  record's own XML, for what the records do not model.
* ``browser_rect`` measures an element in the same browser build and channel
  the sidecar uses, through ``tests/fixtures/export_snapshot/measure.cjs``
  (Python has no Playwright in this repo, so measurement goes through Node);
  ``browser_client_rects`` reads its box fragments, one per line an inline
  element spans, and ``browser_padding_box`` the box its overflow clips to.
  ``browser_hit_id`` says what the browser shows at a point, by hit testing.
  ``browser_line_boxes`` and ``browser_lines`` read the element's rendered text
  lines from the same page, with a ``Range`` per character. ``browser_style``
  reads its computed typography, ``browser_text`` its rendered ``innerText``
  and ``browser_loaded_weights`` the webfont weights the page loaded.
  ``browser_probes`` sets text offscreen in the page's own fonts and reads its
  size; ``browser_natural_line_height`` is the ``line-height: normal`` probe.
* ``text_loss`` runs the export fidelity harness's text-loss oracle
  (``scripts/export_fidelity/run.py::check_text_loss``) on an exported deck.
* ``node_json`` evaluates a script in the sidecar directory with ``node -e``,
  so a sidecar module's pure functions are testable without a browser.
* ``corpus_slide`` / ``corpus_document`` load the committed brand corpus in
  ``tests/fixtures/export_fidelity`` by its numeric prefix, so no test copies
  corpus HTML.

Gating matches the sibling export suites: ``requires_huashu_sidecar`` skips
unless node, the extracted sidecar ``node_modules`` and a local
Chrome/Chromium are present; ``requires_node`` needs node alone.
"""

from __future__ import annotations

import functools
import importlib.util
import json
import os
import posixpath
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from types import ModuleType
from unittest import mock

import pytest
from lxml import etree

from src.api.routes.export import build_slide_html
from src.services import pptx_from_html_huashu

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = REPO_ROOT / "tests" / "fixtures" / "export_fidelity"
SNAPSHOT_FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "export_snapshot"
MEASURE_SCRIPT = SNAPSHOT_FIXTURE_DIR / "measure.cjs"
FIDELITY_HARNESS = REPO_ROOT / "scripts" / "export_fidelity" / "run.py"

DECK_CSS: str = (CORPUS_DIR / "deck.css").read_text(encoding="utf-8")
# deck.json carries the corpus deck's ``title``, ``scripts`` and ``external_scripts``.
CORPUS_DECK: dict = json.loads((CORPUS_DIR / "deck.json").read_text(encoding="utf-8"))

TEST_DECK_TITLE = "export snapshot test"

# OOXML units. One CSS px is 1/96 in; one inch is 914400 EMU; one point is 12700 EMU.
EMU_PER_PX = 9525
EMU_PER_PT = 12700
# Rotation and shadow direction are written in 60000ths of a degree.
ANGLE_UNITS_PER_DEGREE = 60000
# Alpha, line spacing and other percentages are written in 1000ths of a percent.
PERCENT_UNITS = 100000
# a:rPr sz and spc are written in hundredths of a point.
HUNDREDTHS = 100
MEASURE_TIMEOUT_SECONDS = 120
NODE_TIMEOUT_SECONDS = 30
# CSS font weights are multiples of 100 from 100 to 900; a variable face's
# weight is a range of them ("100 900").
FONT_WEIGHT_STEP = 100
FONT_WEIGHT_MIN = 100
FONT_WEIGHT_MAX = 900

NAMESPACES = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
PACKAGE_RELATIONSHIPS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
RELATIONSHIP_ID = f"{{{NAMESPACES['r']}}}id"
RELATIONSHIP_EMBED = f"{{{NAMESPACES['r']}}}embed"

PARAGRAPH_ALIGNMENTS = {
    "l": "left",
    "ctr": "center",
    "r": "right",
    "just": "justify",
    "dist": "distributed",
}
# spTree children that are the tree's own properties, not drawn content.
SHAPE_TREE_PROPERTIES = {"nvGrpSpPr", "grpSpPr", "extLst"}


def _huashu_available() -> bool:
    with mock.patch.dict(os.environ, {"HUASHU_PIPELINE_ENABLED": "1"}):
        return pptx_from_html_huashu.is_available()


requires_huashu_sidecar: pytest.MarkDecorator = pytest.mark.skipif(
    not _huashu_available(),
    reason=(
        "requires node, services/pptx-emit-huashu/node_modules (run setup.sh) "
        "and a local Chrome/Chromium"
    ),
)

requires_node: pytest.MarkDecorator = pytest.mark.skipif(
    shutil.which("node") is None, reason="requires node"
)


# ---------------------------------------------------------------------------
# Building and exporting slide documents
# ---------------------------------------------------------------------------


def slide_document(
    body: str,
    *,
    css: str = DECK_CSS,
    scripts: str = "",
    external_scripts: tuple[str, ...] = (),
    title: str = TEST_DECK_TITLE,
    slide_id: str = "snapshot-1",
) -> str:
    """The complete export document for one slide body, exactly as the export routes build it.

    ``export_slides`` builds its documents with this function, so a test that
    measures ``slide_document(body)`` with ``browser_rect`` measures the very
    page the sidecar rendered.
    """
    return build_slide_html(
        {"slide_id": slide_id, "html": body},
        {
            "css": css,
            "scripts": scripts,
            "external_scripts": list(external_scripts),
            "title": title,
        },
    )


def _export_documents(
    documents: list[str],
    *,
    title: str,
    engine: str,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[bytes, list[dict]]:
    monkeypatch.setenv("HUASHU_PIPELINE_ENABLED", "1")
    monkeypatch.setenv("TELLR_EXPORT_ENGINE", engine)
    return pptx_from_html_huashu.build_pptx_huashu(
        title,
        [{"html": document} for document in documents],
        bypass_validation=True,
    )


def export_slides(
    bodies: list[str],
    *,
    css: str = DECK_CSS,
    scripts: str = "",
    external_scripts: tuple[str, ...] = (),
    engine: str = "snapshot",
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[bytes, list[dict]]:
    """Export slide bodies through the production wrapper with the chosen engine.

    Each body becomes ``slide_document(body, ..., slide_id=f"snapshot-{n}")``
    (1-based ``n``), so ``slide_document(bodies[i], ..., slide_id=f"snapshot-{i + 1}")``
    reproduces the exported page exactly. Returns ``(pptx_bytes, failures)``
    from ``build_pptx_huashu(..., bypass_validation=True)``.
    """
    documents = [
        slide_document(
            body,
            css=css,
            scripts=scripts,
            external_scripts=external_scripts,
            slide_id=f"snapshot-{position}",
        )
        for position, body in enumerate(bodies, start=1)
    ]
    return _export_documents(
        documents, title=TEST_DECK_TITLE, engine=engine, monkeypatch=monkeypatch
    )


def _corpus_path(prefix: str) -> Path:
    matches = sorted((CORPUS_DIR / "slides").glob(f"{prefix}-*.html"))
    assert len(matches) == 1, (
        f"corpus prefix {prefix!r} matched {len(matches)} slides in "
        f"{CORPUS_DIR / 'slides'}: {[path.name for path in matches]}"
    )
    return matches[0]


def corpus_slide(prefix: str) -> str:
    """The body of corpus slide ``tests/fixtures/export_fidelity/slides/<prefix>-*.html``."""
    return _corpus_path(prefix).read_text(encoding="utf-8")


def corpus_document(prefix: str) -> str:
    """The complete export document for a corpus slide, built with the corpus deck."""
    path = _corpus_path(prefix)
    return slide_document(
        path.read_text(encoding="utf-8"),
        css=DECK_CSS,
        scripts=CORPUS_DECK.get("scripts", ""),
        external_scripts=tuple(CORPUS_DECK.get("external_scripts", [])),
        title=CORPUS_DECK.get("title", TEST_DECK_TITLE),
        slide_id=path.stem,
    )


def export_corpus(
    prefixes: list[str],
    *,
    monkeypatch: pytest.MonkeyPatch,
    engine: str = "snapshot",
) -> tuple[bytes, list[dict]]:
    """Export corpus slides (by prefix, in the given order) with the corpus deck CSS and scripts."""
    return _export_documents(
        [corpus_document(prefix) for prefix in prefixes],
        title=CORPUS_DECK.get("title", TEST_DECK_TITLE),
        engine=engine,
        monkeypatch=monkeypatch,
    )


# ---------------------------------------------------------------------------
# Browser measurement (C3): measure.cjs on the sidecar's own Playwright
# ---------------------------------------------------------------------------


def _run_measure(document_html: str, *arguments: str) -> str:
    with tempfile.TemporaryDirectory(prefix="tellr-measure-") as directory:
        document_path = Path(directory) / "document.html"
        document_path.write_text(document_html, encoding="utf-8")
        process = subprocess.run(
            ["node", str(MEASURE_SCRIPT), str(document_path), *arguments],
            cwd=pptx_from_html_huashu.SIDECAR_DIR,
            env=pptx_from_html_huashu.sidecar_subprocess_env(),
            capture_output=True,
            text=True,
            timeout=MEASURE_TIMEOUT_SECONDS,
            check=False,
        )
    assert process.returncode == 0, (
        f"measure.cjs {' '.join(arguments)} exited {process.returncode}: {process.stderr.strip()}"
    )
    return process.stdout


def browser_rect(document_html: str, selector: str, index: int = 0) -> dict:
    """``getBoundingClientRect()`` of the ``index``-th match of ``selector``, in CSS px.

    Returns ``{"x", "y", "w", "h"}`` measured after the sidecar's settle
    (networkidle, ``document.fonts.ready``, the canvas wait, finished
    animations) on a 1280x720 viewport.
    """
    rect = json.loads(_run_measure(document_html, selector, str(index)))
    return {key: float(rect[key]) for key in ("x", "y", "w", "h")}


def browser_client_rects(document_html: str, selector: str, index: int = 0) -> list[dict]:
    """``getClientRects()`` of the ``index``-th match of ``selector``: its box fragments, in CSS px.

    One ``{"x", "y", "w", "h"}`` border-box rect per fragment, in the order the
    browser lists them, measured on the same settled page as ``browser_rect``.
    An inline element that wraps has one fragment per line it lies on; under
    the default ``box-decoration-break: slice`` its start padding is on the
    first fragment only and its end padding on the last. Zero-width rects are
    reported too.
    """
    rects = json.loads(_run_measure(document_html, selector, str(index), "--mode=rects"))
    return [{key: float(rect[key]) for key in ("x", "y", "w", "h")} for rect in rects]


def browser_padding_box(document_html: str, selector: str, index: int = 0) -> dict:
    """The padding box of the ``index``-th match of ``selector``, in CSS px.

    ``{"x", "y", "w", "h"}``: the border box (``browser_rect``) less the
    computed border width on each side. An element whose ``overflow`` is
    ``hidden``, ``clip``, ``auto`` or ``scroll`` clips what it holds to this
    box (its overflow clip edge, under the default ``overflow-clip-margin``
    of 0). Measured on the same settled page as ``browser_rect``; the element
    must not be transformed.
    """
    box = json.loads(_run_measure(document_html, selector, str(index), "--mode=padding-box"))
    return {key: float(box[key]) for key in ("x", "y", "w", "h")}


def browser_hit_id(document_html: str, x: float, y: float) -> str | None:
    """The id of what the browser shows at ``(x, y)``, by hit testing.

    ``document.elementFromPoint(x, y)`` on the settled page gives the topmost
    element painted at the point; this returns its id, or the id of its
    nearest ancestor that has one, and None when neither has. Hit testing
    honours whatever clips or hides an element (an ``overflow`` ancestor,
    ``clip``, ``clip-path``, ``visibility: hidden``) but not ``opacity``, so it
    tells whether the browser shows an element at a point without trusting any
    reading of the CSS. It tells shown from hidden, not where a clip's edge
    lies: Chrome hit-tests an ``overflow`` clip at the clipping element's
    border box, while it paints the clip at the padding box
    (``browser_padding_box``). The point must lie in the 1280x720 viewport,
    outside which nothing is hit.
    """
    point = json.dumps({"x": x, "y": y})
    return json.loads(_run_measure(document_html, point, "--mode=hit"))["id"]


def browser_line_boxes(document_html: str, selector: str, index: int = 0) -> list[dict]:
    """The rendered text lines of the ``index``-th match of ``selector``, in reading order.

    Each line is ``{"text", "x", "y", "w", "h"}``: its text as painted and the
    union of its character rects in CSS px. ``measure.cjs --mode=lines`` reads
    every character with a ``Range`` and clusters the painted ones into lines
    by vertical overlap, so the line breaks are the browser's own:

    * collapsible white space reads as the single space it renders as, and a
      line is trimmed at both ends; ``pre``, ``pre-wrap`` and ``break-spaces``
      keep their spaces as written;
    * text inside ``<svg>`` is not part of any line;
    * side-by-side flex or grid items on one band cluster into one line, so
      measure one text block at a time.
    """
    lines = json.loads(_run_measure(document_html, selector, str(index), "--mode=lines"))
    return [
        {"text": line["text"], **{key: float(line[key]) for key in ("x", "y", "w", "h")}}
        for line in lines
    ]


def browser_lines(document_html: str, selector: str, index: int = 0) -> list[str]:
    """The rendered line texts of the ``index``-th match of ``selector``.

    The ``text`` of each ``browser_line_boxes`` line, in reading order.
    """
    return [line["text"] for line in browser_line_boxes(document_html, selector, index)]


def text_bounds(line_boxes: list[dict]) -> dict:
    """The union ``{"x", "y", "w", "h"}`` of ``browser_line_boxes`` lines: the text's own bounds."""
    assert line_boxes, "no rendered text lines to bound"
    left = min(line["x"] for line in line_boxes)
    top = min(line["y"] for line in line_boxes)
    right = max(line["x"] + line["w"] for line in line_boxes)
    bottom = max(line["y"] + line["h"] for line in line_boxes)
    return {"x": left, "y": top, "w": right - left, "h": bottom - top}


def browser_style(document_html: str, selector: str, index: int = 0) -> dict[str, str]:
    """The computed typography of the ``index``-th match of ``selector``.

    Keys are the camelCase ``getComputedStyle`` names ``measure.cjs`` lists in
    ``STYLE_PROPERTIES`` (``fontFamily``, ``fontWeight``, ``letterSpacing``,
    ``textTransform``, ``color``, ``opacity``, ``backgroundColor``,
    ``backgroundImage``, ``backgroundClip`` and so on), each value as the
    browser serialises it (``"600"``, ``"2.08px"``, ``"rgb(27, 49, 57)"``).
    """
    return json.loads(_run_measure(document_html, selector, str(index), "--mode=style"))


def browser_text(document_html: str, selector: str = "body", index: int = 0) -> str:
    """The ``innerText`` of the ``index``-th match of ``selector``, as the browser renders it.

    ``innerText`` applies ``text-transform`` and the rendered line breaks.
    Every ``<svg>`` and ``<canvas>`` is hidden first, so with the default
    selector this is exactly the export fidelity harness's text-loss reference
    (``scripts/export_fidelity/render_truth.cjs``).
    """
    return json.loads(_run_measure(document_html, selector, str(index), "--mode=text"))["text"]


def _face_weights(weight: str) -> list[int]:
    """The hundreds a FontFace ``weight`` descriptor covers: ``"600"`` or a range ``"100 900"``."""
    bounds = [int(round(float(value))) for value in weight.split()]
    low, high = min(bounds), max(bounds)
    return [
        hundred
        for hundred in range(FONT_WEIGHT_MIN, FONT_WEIGHT_MAX + 1, FONT_WEIGHT_STEP)
        if low <= hundred <= high
    ]


def browser_loaded_weights(document_html: str) -> dict[str, list[int]]:
    """Family -> the weights of its faces in ``document.fonts`` whose status is ``loaded``.

    A face is ``loaded`` only once the page used it, so this is the set of
    webfont weights the page really painted with. A variable face's weight
    range (``"100 900"``) contributes every hundred inside it. Family names are
    unquoted; weights are sorted and distinct.
    """
    faces = json.loads(_run_measure(document_html, "--mode=fonts"))
    loaded: dict[str, set[int]] = {}
    for face in faces:
        if face["status"] != "loaded":
            continue
        family = face["family"].strip().strip("\"'")
        loaded.setdefault(family, set()).update(_face_weights(face["weight"]))
    return {family: sorted(weights) for family, weights in sorted(loaded.items())}


def browser_probes(document_html: str, probes: list[tuple[str, str]]) -> list[dict]:
    """The size of each ``(text, css)`` probe, set offscreen in the document's own fonts.

    ``measure.cjs --mode=probe`` appends one hidden, absolutely positioned
    ``<div>`` per probe to ``documentElement`` (``white-space: pre``, no margin,
    padding or border) with ``css`` as its inline style, waits for
    ``document.fonts.ready``, and reads each border box. Returns one
    ``{"w", "h"}`` per probe, in CSS px and in order: ``w`` is the advance width
    of the text, and under ``line-height: normal`` ``h`` is the font's natural
    line height. The page is the settled page ``browser_rect`` reads, so its
    webfonts are the ones the export saw.
    """
    payload = json.dumps([{"text": text, "css": css} for text, css in probes])
    sizes = json.loads(_run_measure(document_html, payload, "--mode=probe"))
    return [{key: float(size[key]) for key in ("w", "h")} for size in sizes]


def browser_natural_line_height(
    document_html: str, family: str, weight: int, size_px: float, style: str = "normal"
) -> float:
    """The browser's ``line-height: normal`` for one face and size, in CSS px.

    The snapshot's own probe, read independently: "Hg" set in
    ``font: <style> <weight> <size>px '<family>'; line-height: normal``
    (``browser_probes``), whose height is the natural line height.
    """
    css = f"font: {style} {weight} {size_px}px '{family}'; line-height: normal"
    return browser_probes(document_html, [("Hg", css)])[0]["h"]


def browser_ascent(
    document_html: str, family: str, weight: int, size_px: float, style: str = "normal"
) -> float:
    """The browser's ascent for one face and size: its glyph top down to its baseline, in CSS px.

    "Hg" set in ``font: <style> <weight> <size>px '<family>'; line-height:
    normal`` behind a zero-size inline-block on the baseline (``measure.cjs
    --mode=probe`` with ``"baseline": true``): the marker's top less the top of
    a Range over the text, the glyph top a text box's ``y`` is read from.
    """
    css = f"font: {style} {weight} {size_px}px '{family}'; line-height: normal"
    payload = json.dumps([{"text": "Hg", "css": css, "baseline": True}])
    sizes = json.loads(_run_measure(document_html, payload, "--mode=probe"))
    return float(sizes[0]["ascent"])


# ---------------------------------------------------------------------------
# The export fidelity harness's text-loss oracle, and sidecar modules in Node
# ---------------------------------------------------------------------------


@functools.cache
def fidelity_harness() -> ModuleType:
    """``scripts/export_fidelity/run.py``, imported by path (it is a script, not a package)."""
    spec = importlib.util.spec_from_file_location("export_fidelity_harness", FIDELITY_HARNESS)
    assert spec is not None and spec.loader is not None, f"cannot load {FIDELITY_HARNESS}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def text_loss(pptx: bytes, documents: list[str]) -> list[list[str]]:
    """Per slide, the words the browser renders that the exported slide lacks.

    ``documents[i]`` is the complete document exported as slide ``i`` (0-based),
    so the list covers the deck's first ``len(documents)`` slides in order. The
    comparison is the harness's own, ``check_text_loss``: each reference word,
    whitespace removed and lower-cased, must be a substring of the slide's
    concatenated text-frame and table text, likewise normalised. The reference
    is the one ``render_truth.cjs`` writes, the body's ``innerText`` with SVG and
    canvas hidden (``browser_text``), measured on the sidecar's settled page.
    An empty list for a slide means nothing it renders is missing.
    """
    harness = fidelity_harness()
    names = [f"slide-{position}" for position in range(1, len(documents) + 1)]
    with tempfile.TemporaryDirectory(prefix="tellr-text-loss-") as directory:
        out_dir = Path(directory)
        truth_dir = out_dir / "truth"
        truth_dir.mkdir()
        for name, document in zip(names, documents):
            (truth_dir / f"{name}.txt").write_text(browser_text(document), encoding="utf-8")
        pptx_path = out_dir / "export.pptx"
        pptx_path.write_bytes(pptx)
        missing = harness.check_text_loss(pptx_path, names, out_dir)
    return [missing.get(name, []) for name in names]


def node_json(script: str) -> object:
    """Run ``node -e script`` in the sidecar directory and parse what it prints as JSON.

    The script's working directory is the sidecar's, with the sidecar's own
    environment, so it can ``require`` a sidecar module by absolute path and
    print ``JSON.stringify`` of what that module returns.
    """
    process = subprocess.run(
        ["node", "-e", script],
        cwd=pptx_from_html_huashu.SIDECAR_DIR,
        env=pptx_from_html_huashu.sidecar_subprocess_env(),
        capture_output=True,
        text=True,
        timeout=NODE_TIMEOUT_SECONDS,
        check=False,
    )
    assert process.returncode == 0, (
        f"node -e exited {process.returncode}: {process.stderr.strip()}\nscript: {script}"
    )
    return json.loads(process.stdout)


# ---------------------------------------------------------------------------
# Reading the emitted .pptx
# ---------------------------------------------------------------------------


@dataclass
class Run:
    text: str
    typeface: str | None  # a:latin typeface; None when the run names none
    bold: bool
    italic: bool
    size_pt: float | None  # None when the run carries no sz
    color: str | None  # srgbClr of the run's solidFill
    spc_pt: float  # letter spacing; 0.0 when absent
    baseline: str | None  # 'super' | 'sub' | None
    underline: bool
    strike: bool
    soft_break_before: bool  # an <a:br/> separates this run from the previous one
    # a:rPr baseline in 1000ths of a percent (30000 is superscript); 0 when absent
    baseline_offset: int = 0
    color_alpha: float | None = None  # 0..1 <a:alpha> of the run colour; None when absent
    east_asian_typeface: str | None = None  # a:ea typeface; None when the run names none
    complex_script_typeface: str | None = None  # a:cs typeface; None when the run names none


@dataclass
class Para:
    runs: list[Run]
    align: str  # 'left' (the OOXML default) | 'center' | 'right' | 'justify' | 'distributed'
    line_spacing_pct: float | None  # a:lnSpc/a:spcPct as a percentage (100.0 is single)
    rtl: bool


@dataclass
class Shadow:
    kind: str  # 'outer' | 'inner'
    color: str | None
    alpha: float | None  # 0..1; None when the colour carries no <a:alpha>
    blur_px: float
    dist_px: float
    angle: float  # degrees, clockwise from the positive x axis (90 is straight down)


@dataclass
class Border:
    color: str | None
    width_pt: float | None
    dash: str | None


@dataclass
class Cell:
    text: str
    paras: list[Para]
    fill: str | None
    fill_alpha: float | None
    grid_span: int
    row_span: int
    h_merge: bool
    v_merge: bool
    margins_px: dict[str, float | None]  # keys 'left' 'right' 'top' 'bottom'
    anchor: str | None
    borders: dict[str, Border | None]  # keys 'left' 'right' 'top' 'bottom'


@dataclass
class Table:
    col_widths: list[float]  # CSS px
    row_heights: list[float]  # CSS px
    rows: list[list[Cell]]


@dataclass
class Shape:
    kind: str  # 'text' | 'shape' | 'line' | 'picture' | 'table'
    geometry: str | None  # prstGeom name: 'rect' | 'roundRect' | 'ellipse' | 'line' | ...
    x: float  # CSS px
    y: float
    w: float
    h: float
    rotation: float  # degrees
    wrap: str | None  # bodyPr wrap: 'square' | 'none'
    fill: str | None
    fill_alpha: float | None  # 0..1; None when the fill carries no <a:alpha> (fully opaque)
    line: str | None
    line_w_pt: float | None
    line_dash: str | None
    paras: list[Para]
    text: str  # runs concatenated; <a:br/> and paragraph ends become "\n"
    image: bytes | None
    table: Table | None
    adj: int | None  # prstGeom avLst adj value (roundRect: radius / short side * 100000)
    shadow: Shadow | None = None
    flip_h: bool = False
    flip_v: bool = False
    name: str = ""  # cNvPr name


def _qualified(prefix: str, local: str) -> str:
    return f"{{{NAMESPACES[prefix]}}}{local}"


def _local_name(element: etree._Element) -> str:
    return etree.QName(element).localname


def _read_xml(archive: zipfile.ZipFile, name: str) -> etree._Element:
    return etree.fromstring(archive.read(name))


def _relationships(archive: zipfile.ZipFile, part_name: str) -> dict[str, str]:
    """rId -> absolute part name, for the part ``part_name``."""
    directory, base = posixpath.split(part_name)
    rels_name = posixpath.join(directory, "_rels", f"{base}.rels")
    if rels_name not in archive.namelist():
        return {}
    targets = {}
    for relationship in _read_xml(archive, rels_name).iter(
        f"{{{PACKAGE_RELATIONSHIPS_NS}}}Relationship"
    ):
        if relationship.get("TargetMode") == "External":
            continue
        target = relationship.get("Target", "")
        targets[relationship.get("Id")] = posixpath.normpath(
            target.lstrip("/") if target.startswith("/") else posixpath.join(directory, target)
        )
    return targets


def _slide_part(archive: zipfile.ZipFile, index: int) -> str:
    """Part name of the ``index``-th slide (0-based) in presentation order."""
    presentation = _read_xml(archive, "ppt/presentation.xml")
    targets = _relationships(archive, "ppt/presentation.xml")
    slide_ids = presentation.findall("p:sldIdLst/p:sldId", NAMESPACES)
    assert 0 <= index < len(slide_ids), (
        f"slide index {index} is out of range: the deck has {len(slide_ids)} slides"
    )
    return targets[slide_ids[index].get(RELATIONSHIP_ID)]


def _open_pptx(pptx: bytes) -> zipfile.ZipFile:
    assert pptx, "the export produced no .pptx bytes"
    return zipfile.ZipFile(BytesIO(pptx))


def _px(emu: str | None) -> float:
    return int(emu or 0) / EMU_PER_PX


def _alpha(color: etree._Element | None) -> float | None:
    if color is None:
        return None
    alpha = color.find("a:alpha", NAMESPACES)
    return None if alpha is None else int(alpha.get("val")) / PERCENT_UNITS


def _solid_color(parent: etree._Element | None) -> tuple[str | None, float | None]:
    """(RRGGBB, alpha) of ``parent``'s direct a:solidFill/a:srgbClr, else (None, None)."""
    if parent is None:
        return None, None
    color = parent.find("a:solidFill/a:srgbClr", NAMESPACES)
    if color is None:
        return None, None
    return color.get("val").upper(), _alpha(color)


def _line(line: etree._Element | None) -> Border | None:
    """An a:ln (or table-cell a:lnL/R/T/B); None when absent or explicitly unfilled."""
    if line is None or line.find("a:noFill", NAMESPACES) is not None:
        return None
    color, _ = _solid_color(line)
    width = line.get("w")
    dash = line.find("a:prstDash", NAMESPACES)
    return Border(
        color=color,
        width_pt=None if width is None else int(width) / EMU_PER_PT,
        dash=None if dash is None else dash.get("val"),
    )


def _shadow(shape_properties: etree._Element | None) -> Shadow | None:
    if shape_properties is None:
        return None
    for kind in ("outer", "inner"):
        effect = shape_properties.find(f"a:effectLst/a:{kind}Shdw", NAMESPACES)
        if effect is None:
            continue
        color = effect.find("a:srgbClr", NAMESPACES)
        return Shadow(
            kind=kind,
            color=None if color is None else color.get("val").upper(),
            alpha=_alpha(color),
            blur_px=_px(effect.get("blurRad")),
            dist_px=_px(effect.get("dist")),
            angle=int(effect.get("dir") or 0) / ANGLE_UNITS_PER_DEGREE,
        )
    return None


def _run(run: etree._Element, soft_break_before: bool) -> Run:
    properties = run.find("a:rPr", NAMESPACES)
    attributes = {} if properties is None else properties.attrib
    latin = None if properties is None else properties.find("a:latin", NAMESPACES)
    east_asian = None if properties is None else properties.find("a:ea", NAMESPACES)
    complex_script = None if properties is None else properties.find("a:cs", NAMESPACES)
    color, color_alpha = _solid_color(properties)
    baseline = int(attributes.get("baseline", 0))
    size = attributes.get("sz")
    return Run(
        text="".join(text.text or "" for text in run.findall("a:t", NAMESPACES)),
        typeface=None if latin is None else latin.get("typeface"),
        bold=attributes.get("b") in ("1", "true"),
        italic=attributes.get("i") in ("1", "true"),
        size_pt=None if size is None else int(size) / HUNDREDTHS,
        color=color,
        spc_pt=int(attributes.get("spc", 0)) / HUNDREDTHS,
        baseline="super" if baseline > 0 else "sub" if baseline < 0 else None,
        underline=attributes.get("u", "none") != "none",
        strike=attributes.get("strike", "noStrike") != "noStrike",
        soft_break_before=soft_break_before,
        baseline_offset=baseline,
        color_alpha=color_alpha,
        east_asian_typeface=None if east_asian is None else east_asian.get("typeface"),
        complex_script_typeface=None if complex_script is None else complex_script.get("typeface"),
    )


def _paragraph(paragraph: etree._Element) -> tuple[Para, str]:
    """The paragraph and its text, with each <a:br/> as "\n"."""
    properties = paragraph.find("a:pPr", NAMESPACES)
    attributes = {} if properties is None else properties.attrib
    spacing = None if properties is None else properties.find("a:lnSpc/a:spcPct", NAMESPACES)
    runs: list[Run] = []
    text_parts: list[str] = []
    pending_break = False
    for child in paragraph:
        name = _local_name(child)
        if name == "br":
            pending_break = True
            text_parts.append("\n")
        elif name in ("r", "fld"):
            run = _run(child, pending_break)
            runs.append(run)
            text_parts.append(run.text)
            pending_break = False
    para = Para(
        runs=runs,
        align=PARAGRAPH_ALIGNMENTS.get(attributes.get("algn", "l"), attributes.get("algn")),
        line_spacing_pct=(
            None if spacing is None else int(spacing.get("val")) * 100 / PERCENT_UNITS
        ),
        rtl=attributes.get("rtl") in ("1", "true"),
    )
    return para, "".join(text_parts)


def _text_body(text_body: etree._Element | None) -> tuple[list[Para], str, str | None]:
    """(paragraphs, text, bodyPr wrap) of an a:txBody / p:txBody."""
    if text_body is None:
        return [], "", None
    paragraphs = []
    texts = []
    for paragraph in text_body.findall("a:p", NAMESPACES):
        para, text = _paragraph(paragraph)
        paragraphs.append(para)
        texts.append(text)
    body_properties = text_body.find("a:bodyPr", NAMESPACES)
    wrap = None if body_properties is None else body_properties.get("wrap")
    return paragraphs, "\n".join(texts), wrap


def _cell(cell: etree._Element) -> Cell:
    paragraphs, text, _ = _text_body(cell.find("a:txBody", NAMESPACES))
    properties = cell.find("a:tcPr", NAMESPACES)
    fill, fill_alpha = _solid_color(properties)
    sides = {"left": "lnL", "right": "lnR", "top": "lnT", "bottom": "lnB"}
    margins = {"left": "marL", "right": "marR", "top": "marT", "bottom": "marB"}
    return Cell(
        text=text,
        paras=paragraphs,
        fill=fill,
        fill_alpha=fill_alpha,
        grid_span=int(cell.get("gridSpan", 1)),
        row_span=int(cell.get("rowSpan", 1)),
        h_merge=cell.get("hMerge") in ("1", "true"),
        v_merge=cell.get("vMerge") in ("1", "true"),
        margins_px={
            side: (
                None
                if properties is None or properties.get(attribute) is None
                else _px(properties.get(attribute))
            )
            for side, attribute in margins.items()
        },
        anchor=None if properties is None else properties.get("anchor"),
        borders={
            side: (
                None if properties is None else _line(properties.find(f"a:{element}", NAMESPACES))
            )
            for side, element in sides.items()
        },
    )


def _table(table: etree._Element) -> Table:
    return Table(
        col_widths=[
            _px(column.get("w")) for column in table.findall("a:tblGrid/a:gridCol", NAMESPACES)
        ],
        row_heights=[_px(row.get("h")) for row in table.findall("a:tr", NAMESPACES)],
        rows=[
            [_cell(cell) for cell in row.findall("a:tc", NAMESPACES)]
            for row in table.findall("a:tr", NAMESPACES)
        ],
    )


def _transform(transform: etree._Element | None) -> dict:
    if transform is None:
        return {
            "x": 0.0,
            "y": 0.0,
            "w": 0.0,
            "h": 0.0,
            "rotation": 0.0,
            "flip_h": False,
            "flip_v": False,
        }
    offset = transform.find("a:off", NAMESPACES)
    extent = transform.find("a:ext", NAMESPACES)
    return {
        "x": _px(None if offset is None else offset.get("x")),
        "y": _px(None if offset is None else offset.get("y")),
        "w": _px(None if extent is None else extent.get("cx")),
        "h": _px(None if extent is None else extent.get("cy")),
        "rotation": int(transform.get("rot", 0)) / ANGLE_UNITS_PER_DEGREE,
        "flip_h": transform.get("flipH") in ("1", "true"),
        "flip_v": transform.get("flipV") in ("1", "true"),
    }


def _preset_geometry(shape_properties: etree._Element | None) -> tuple[str | None, int | None]:
    if shape_properties is None:
        return None, None
    if shape_properties.find("a:custGeom", NAMESPACES) is not None:
        return "custGeom", None
    preset = shape_properties.find("a:prstGeom", NAMESPACES)
    if preset is None:
        return None, None
    adjust = preset.find("a:avLst/a:gd[@name='adj']", NAMESPACES)
    adj = None
    if adjust is not None:
        formula = adjust.get("fmla", "")
        assert formula.startswith("val "), f"unexpected adj formula {formula!r}"
        adj = int(formula.removeprefix("val ").strip())
    return preset.get("prst"), adj


def _drawing_shape(
    element: etree._Element,
    archive: zipfile.ZipFile,
    relationships: dict[str, str],
) -> Shape:
    """One spTree child (p:sp, p:cxnSp, p:pic or p:graphicFrame) as a Shape."""
    name = _local_name(element)
    properties_name = {"sp": "p:spPr", "cxnSp": "p:spPr", "pic": "p:spPr"}.get(name)
    shape_properties = (
        None if properties_name is None else element.find(properties_name, NAMESPACES)
    )
    non_visual = element.find("*/p:cNvPr", NAMESPACES)
    if name == "graphicFrame":
        transform = _transform(element.find("p:xfrm", NAMESPACES))
    else:
        transform = _transform(
            None if shape_properties is None else shape_properties.find("a:xfrm", NAMESPACES)
        )
    geometry, adj = _preset_geometry(shape_properties)
    fill, fill_alpha = _solid_color(shape_properties)
    line = _line(None if shape_properties is None else shape_properties.find("a:ln", NAMESPACES))
    paragraphs, text, wrap = _text_body(element.find("p:txBody", NAMESPACES))
    image = None
    table = None

    if name == "sp":
        is_text_box = element.find("p:nvSpPr/p:cNvSpPr[@txBox='1']", NAMESPACES) is not None
        if geometry == "line":
            kind = "line"
        elif text.strip() or is_text_box:
            kind = "text"
        else:
            kind = "shape"
    elif name == "cxnSp":
        kind = "line"
    elif name == "pic":
        kind = "picture"
        blip = element.find("p:blipFill/a:blip", NAMESPACES)
        target = None if blip is None else relationships.get(blip.get(RELATIONSHIP_EMBED))
        image = None if target is None else archive.read(target)
    elif name == "graphicFrame":
        grid = element.find("a:graphic/a:graphicData/a:tbl", NAMESPACES)
        if grid is None:
            raise ValueError("graphicFrame without a:tbl: only native tables are expected")
        kind = "table"
        table = _table(grid)
    else:
        raise ValueError(f"unexpected spTree element p:{name}")

    return Shape(
        kind=kind,
        geometry=geometry,
        x=transform["x"],
        y=transform["y"],
        w=transform["w"],
        h=transform["h"],
        rotation=transform["rotation"],
        wrap=wrap,
        fill=fill,
        fill_alpha=fill_alpha,
        line=None if line is None else line.color,
        line_w_pt=None if line is None else line.width_pt,
        line_dash=None if line is None else line.dash,
        paras=paragraphs,
        text=text,
        image=image,
        table=table,
        adj=adj,
        shadow=_shadow(shape_properties),
        flip_h=transform["flip_h"],
        flip_v=transform["flip_v"],
        name="" if non_visual is None else non_visual.get("name", ""),
    )


def slide_shapes(pptx: bytes, index: int = 0) -> list[Shape]:
    """Every drawn element of slide ``index`` (0-based), in spTree order (back to front)."""
    with _open_pptx(pptx) as archive:
        part = _slide_part(archive, index)
        relationships = _relationships(archive, part)
        tree = _read_xml(archive, part).find("p:cSld/p:spTree", NAMESPACES)
        assert tree is not None, f"{part} has no p:spTree"
        return [
            _drawing_shape(child, archive, relationships)
            for child in tree
            if isinstance(child.tag, str) and _local_name(child) not in SHAPE_TREE_PROPERTIES
        ]


def slide_xml(pptx: bytes, index: int = 0) -> etree._Element:
    """The parsed XML of slide ``index`` (0-based, presentation order).

    For assertions about the whole slide part that ``slide_shapes`` does not
    model, such as an element that must appear nowhere in it.
    """
    with _open_pptx(pptx) as archive:
        return _read_xml(archive, _slide_part(archive, index))


def slide_shape_elements(pptx: bytes, index: int = 0) -> list[etree._Element]:
    """The spTree children ``slide_shapes`` reads, in the same order.

    ``slide_shape_elements(pptx, i)[n]`` is the XML of ``slide_shapes(pptx, i)[n]``,
    for assertions about markup the ``Shape`` record does not model.
    """
    tree = slide_xml(pptx, index).find("p:cSld/p:spTree", NAMESPACES)
    assert tree is not None, f"slide {index} has no p:spTree"
    return [
        child
        for child in tree
        if isinstance(child.tag, str) and _local_name(child) not in SHAPE_TREE_PROPERTIES
    ]


def slide_background(pptx: bytes, index: int = 0) -> str | None:
    """The solid srgbClr of slide ``index``'s ``<p:bg>``; None without a solid background."""
    with _open_pptx(pptx) as archive:
        slide = _read_xml(archive, _slide_part(archive, index))
    color = slide.find("p:cSld/p:bg/p:bgPr/a:solidFill/a:srgbClr", NAMESPACES)
    return None if color is None else color.get("val").upper()


def text_shapes(shapes: list[Shape], contains: str) -> list[Shape]:
    """The text shapes whose text contains ``contains``, in z-order."""
    return [shape for shape in shapes if shape.kind == "text" and contains in shape.text]


def overlaps(a: Shape, b: Shape, tolerance_px: float = 0.5) -> bool:
    """Whether the boxes of ``a`` and ``b`` intersect by more than ``tolerance_px`` on both axes.

    Boxes are compared axis-aligned, ignoring rotation.
    """
    horizontal = min(a.x + a.w, b.x + b.w) - max(a.x, b.x)
    vertical = min(a.y + a.h, b.y + b.h) - max(a.y, b.y)
    return horizontal > tolerance_px and vertical > tolerance_px
