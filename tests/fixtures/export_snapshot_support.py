"""Shared helpers for the snapshot-engine export tests (``tests/unit/test_export_snapshot_*.py``).

The snapshot engine (``services/pptx-emit-huashu/render_slide.cjs``) reads the
rendered page and emits what the browser painted. Its tests are behavioural:
they export real slide documents through the production wrapper and read the
emitted slide XML back, comparing geometry, colours and stacking order against
what the browser itself laid out for the same document.

* ``export_slides`` / ``export_corpus`` run the production export
  (``build_slide_html`` then ``build_pptx_huashu``) with the engine selected
  through ``TELLR_EXPORT_ENGINE``; ``export_documents`` exports complete
  documents (corpus and inline slides mixed in one deck).
* ``slide_shapes`` parses one slide's ``spTree`` with lxml into ``Shape``
  records, in z-order, with geometry in CSS px (``EMU / 9525``);
  ``slide_xml`` is the slide part itself and ``slide_shape_elements`` each
  record's own XML, for what the records do not model. A native table
  (``p:graphicFrame`` holding ``a:tbl``) is a ``Shape`` of kind ``table``
  whose ``Table`` holds every grid slot as a ``Cell`` (merged slots included);
  ``table_frames``, ``table_extent``, ``table_column_edges``,
  ``table_row_edges``, ``table_slot_owner`` and ``table_cell_rect`` read its
  grid back in CSS px.
* ``browser_tables`` reads every table the browser laid out, each cell with
  its box, its grid slot under the HTML table model, its spans, padding,
  own borders and text style, from one page load; ``browser_pixels`` reads
  many screen colours from one screenshot (what a collapsed border painted).
* ``requires_google_slides`` skips unless ``TELLR_GOOGLE_TESTS=1`` and gcloud
  application-default credentials work, so no ordinary run uploads to Drive;
  ``google_slides_presentation`` converts a deck through Drive with the
  fidelity harness and returns the Slides API JSON (which
  ``slides_api_tables`` and ``slides_api_color`` read) with the presentation's
  id, and ``delete_drive_file`` deletes it afterwards.
* ``browser_rect`` measures an element in the same browser build and channel
  the sidecar uses, through ``tests/fixtures/export_snapshot/measure.cjs``
  (Python has no Playwright in this repo, so measurement goes through Node);
  ``browser_client_rects`` reads its box fragments, one per line an inline
  element spans, and ``browser_padding_box`` the box its overflow clips to.
  ``browser_each_rect`` and ``browser_each_padding_box`` read the same boxes
  for every match of a selector from one page load.
  ``browser_hit_id`` says what the browser shows at a point, by hit testing.
  ``browser_each_pseudo`` reads the box and rendered text of each match's
  ``::before``, ``::after`` or ``::marker``, which no page API reports, from
  the browser's own layout through the DevTools protocol, and for a marker
  where its pixels are on screen.
  ``browser_line_boxes`` and ``browser_lines`` read the element's rendered text
  lines from the same page, with a ``Range`` per character. ``browser_style``
  reads its computed typography, ``browser_text`` its rendered ``innerText``
  and ``browser_loaded_weights`` the webfont weights the page loaded.
  ``browser_probes`` sets text offscreen in the page's own fonts and reads its
  size; ``browser_natural_line_height`` is the ``line-height: normal`` probe.
* ``text_loss`` runs the export fidelity harness's text-loss oracle
  (``scripts/export_fidelity/run.py::check_text_loss``) on an exported deck;
  ``slide_text_loss`` runs it on one slide of a deck.
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
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
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


def export_documents(
    documents: list[str],
    *,
    monkeypatch: pytest.MonkeyPatch,
    engine: str = "snapshot",
) -> tuple[bytes, list[dict]]:
    """Export complete slide documents, one slide each and in order, through the production wrapper.

    Each document is exported exactly as given, so corpus documents
    (``corpus_document``) and inline ones (``slide_document``) can share one
    deck. Returns ``(pptx_bytes, failures)`` as ``export_slides`` does.
    """
    return _export_documents(
        documents, title=TEST_DECK_TITLE, engine=engine, monkeypatch=monkeypatch
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


def browser_each_rect(document_html: str, selector: str) -> list[dict]:
    """``getBoundingClientRect()`` of EVERY match of ``selector``, in document order, in CSS px.

    One ``{"x", "y", "w", "h"}`` per match, measured on one settled page (the
    page ``browser_rect`` reads), so measuring many elements of a slide costs
    one browser launch. ``browser_each_rect(d, s)[i]`` equals
    ``browser_rect(d, s, i)``. SVG elements report their geometry's bounds
    (a horizontal ``<line>`` is zero-high at its ``y``).
    """
    rects = json.loads(_run_measure(document_html, selector, "--mode=each-rect"))
    return [{key: float(rect[key]) for key in ("x", "y", "w", "h")} for rect in rects]


def browser_each_padding_box(document_html: str, selector: str) -> list[dict]:
    """The padding box of EVERY match of ``selector``, in document order, in CSS px.

    ``browser_each_padding_box(d, s)[i]`` equals ``browser_padding_box(d, s, i)``,
    all read from one settled page.
    """
    boxes = json.loads(_run_measure(document_html, selector, "--mode=each-padding-box"))
    return [{key: float(box[key]) for key in ("x", "y", "w", "h")} for box in boxes]


def _measured_rect(rect: dict | None) -> dict | None:
    return None if rect is None else {key: float(rect[key]) for key in ("x", "y", "w", "h")}


def browser_each_pseudo(
    document_html: str, selector: str, pseudo: str = "before"
) -> list[dict | None]:
    """The ``::before``, ``::after`` or ``::marker`` of EVERY match of ``selector``, as rendered.

    One entry per match, in document order: None when the element generates
    no such pseudo-element box (its ``content`` is ``none`` or ``normal``, or
    it is ``display: none``), else ``{"x", "y", "w", "h", "text", "style"}``:
    the pseudo-element's own border box in CSS px, the text its ``content``
    rendered (string escapes decoded, quotes, ``attr()``, ``counter()`` and
    ``counters()`` evaluated by the browser) before white space collapses, and
    its computed style: ``browser_style``'s keys plus ``borderTopWidth``,
    ``borderTopStyle``, ``borderTopColor``, ``boxShadow``, ``zIndex``,
    ``display`` and ``position``, as ``getComputedStyle(element, '::before')``
    serialises them. No page API reports the box or the text, so
    ``measure.cjs --mode=each-pseudo`` reads them from the browser's layout of
    the untouched page through the DevTools protocol (``DOM.getBoxModel`` and
    ``DOMSnapshot.captureSnapshot``), on the settled page ``browser_rect`` reads.

    With ``pseudo="marker"`` it reads each list item's ``::marker``: None for
    an item that has none (``list-style-type: none``, or ``::marker { content:
    none }``), else the entry above, whose ``text`` is Chrome's own marker
    with its trailing space ("1. ", "4. " in ``<ol start="4" reversed>``,
    "• ", "◦ ", "" for an image marker), plus ``"ink"``: the ``{"x", "y", "w",
    "h"}`` bounds of the pixels the marker paints, or None when it paints none
    that its colour sets (an image marker). The box is not the glyphs: a text
    marker's box ends with the advance of its trailing space, while Chrome
    paints a disc, circle or square in a box of the symbol's own size and
    leaves the gap to the item's text as a margin. So where a marker's glyphs
    are is read from the screen: ``measure.cjs`` screenshots the settled page
    as it is and with every ``::marker`` transparent, and ``ink`` is where the
    two differ inside the marker's band, in CSS px at device scale 2.
    """
    payload = json.dumps({"selector": selector, "pseudo": pseudo})
    boxes = json.loads(_run_measure(document_html, payload, "--mode=each-pseudo"))
    measured: list[dict | None] = []
    for box in boxes:
        if box is None:
            measured.append(None)
            continue
        entry = {"text": box["text"], "style": dict(box["style"]), **_measured_rect(box)}
        if "ink" in box:
            entry["ink"] = _measured_rect(box["ink"])
        measured.append(entry)
    return measured


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


def browser_pixel(document_html: str, x: float, y: float) -> tuple[int, int, int]:
    """The colour the settled page shows at ``(x, y)``, as ``(r, g, b)``.

    The device pixel of the page's screenshot (device scale 2) that covers the
    CSS px point. Sample where a glyph or shape fully covers its pixels (the
    middle of a disc, a wide stroke), so the colour is what the browser
    composited there and not an anti-aliased edge. The point must lie in the
    1280x720 viewport.
    """
    point = json.dumps({"x": x, "y": y})
    measured = json.loads(_run_measure(document_html, point, "--mode=pixel"))
    return measured["r"], measured["g"], measured["b"]


def browser_pixels(
    document_html: str, points: list[tuple[float, float]]
) -> list[tuple[int, int, int]]:
    """The colour the settled page shows at each ``(x, y)``, as ``(r, g, b)``, in order.

    ``browser_pixel`` for many points, read from one screenshot of one page
    load. The same sampling rule holds: sample where what is measured fully
    covers its device pixels.
    """
    payload = json.dumps([{"x": x, "y": y} for x, y in points])
    colours = json.loads(_run_measure(document_html, payload, "--mode=pixels"))
    return [(colour["r"], colour["g"], colour["b"]) for colour in colours]


@dataclass(frozen=True)
class BrowserBorder:
    """One side of a cell's own border, as the cascade computes it (not the collapsed winner)."""

    width_px: float
    style: str  # 'none' | 'solid' | 'dashed' | 'dotted' | 'double' | ...
    color: str  # as getComputedStyle serialises it: 'rgb(27, 49, 57)'


@dataclass(frozen=True)
class BrowserCell:
    """A ``<td>`` or ``<th>`` as the browser laid it out."""

    row: int  # the grid slot of its top left corner, by the HTML table model
    col: int
    row_span: int  # the rows and columns it covers in that grid
    col_span: int
    x: float  # its border box, CSS px
    y: float
    w: float
    h: float
    tag: str  # 'td' | 'th'
    text: str  # innerText
    padding: dict[str, float]  # computed, CSS px; keys 'top' 'right' 'bottom' 'left'
    borders: dict[str, BrowserBorder]  # its own; keys 'top' 'right' 'bottom' 'left'
    # getComputedStyle: verticalAlign, textAlign, backgroundColor, color,
    # fontFamily, fontWeight, fontStyle, as the browser serialises them
    style: dict[str, str]

    @property
    def rect(self) -> dict:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


@dataclass(frozen=True)
class BrowserTable:
    """A ``<table>`` as the browser laid it out: its box, caption, rows and cells."""

    x: float  # its border box, CSS px (a <caption> lies inside it)
    y: float
    w: float
    h: float
    border_collapse: str  # 'collapse' | 'separate'
    border_spacing: str  # as serialised: '2px' (both axes alike) or '2px 4px'
    background: str  # computed backgroundColor
    caption: dict | None  # {"x","y","w","h","text","side"} or None
    rows: list[dict]  # each row's border box {"x","y","w","h"}, in HTMLTableElement.rows order
    cells: list[BrowserCell]  # in row order, then cell order
    columns: int  # the grid's column count under the HTML table model
    # Each row's own computed border, in row order; keys 'top' 'right' 'bottom'
    # 'left'. A row's border paints only by taking part in border collapsing.
    row_borders: list[dict[str, BrowserBorder]]

    @property
    def rect(self) -> dict:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}

    def cell_at(self, row: int, col: int) -> BrowserCell:
        """The cell whose top left grid slot is ``(row, col)``."""
        for cell in self.cells:
            if (cell.row, cell.col) == (row, col):
                return cell
        raise AssertionError(f"no browser cell starts at grid slot ({row}, {col})")

    def cells_reading(self, text: str) -> list[BrowserCell]:
        """The cells whose innerText, white space collapsed, equals ``text``."""
        return [cell for cell in self.cells if " ".join(cell.text.split()) == text]


def _grid_slots(rows: list[dict]) -> tuple[list[tuple[int, int, int, int]], int]:
    """Each cell's (row, col, row_span, col_span) under the HTML table model, and the column count.

    The model's slot assignment (HTML §4.9.12, "forming a table"): each row's
    cells take, in order, the first grid columns no cell from a row above
    still covers; ``rowspan`` reaches at most the end of the cell's row group,
    and ``rowspan="0"`` reaches exactly that far.
    """
    group_end: list[int] = []
    for index, row in enumerate(rows):
        end = index + 1
        while end < len(rows) and rows[end]["group"] == row["group"]:
            end += 1
        group_end.append(end)
    occupied: set[tuple[int, int]] = set()
    slots = []
    for row_index, row in enumerate(rows):
        column = 0
        for cell in row["cells"]:
            while (row_index, column) in occupied:
                column += 1
            reach = group_end[row_index] - row_index
            row_span = reach if cell["rowSpan"] == 0 else min(cell["rowSpan"], reach)
            col_span = max(1, cell["colSpan"])
            for row_offset in range(row_span):
                for column_offset in range(col_span):
                    occupied.add((row_index + row_offset, column + column_offset))
            slots.append((row_index, column, row_span, col_span))
            column += col_span
    columns = 1 + max((column for _, column in occupied), default=-1)
    return slots, columns


def _browser_borders(measured: dict) -> dict[str, BrowserBorder]:
    return {
        side: BrowserBorder(
            width_px=float(border["width"]), style=border["style"], color=border["color"]
        )
        for side, border in measured.items()
    }


def browser_tables(document_html: str, selector: str = "table") -> list[BrowserTable]:
    """Every ``<table>`` matching ``selector``, in document order, as the browser laid it out.

    One ``measure.cjs --mode=tables`` page load reads each table's border
    box, computed ``border-collapse``, ``border-spacing`` and background, its
    ``<caption>`` (box, text, ``caption-side``), its rows' boxes in
    ``HTMLTableElement.rows`` order, and every cell's border box, spans,
    innerText, computed padding, own per-side borders and text style, and
    every row's own computed borders. Each
    cell's grid slot is derived here from the rows, spans and row groups by
    the HTML table model, so a test can hold an emitted grid slot by slot
    against the browser's cells. Under ``border-collapse: collapse`` a cell's
    reported border is its own, not the edge's winner: what the browser
    painted on a shared edge is on the screen (``browser_pixels``).
    """
    measured = json.loads(_run_measure(document_html, selector, "--mode=tables"))
    tables = []
    for table in measured:
        slots, columns = _grid_slots(table["rows"])
        raw_cells = [cell for row in table["rows"] for cell in row["cells"]]
        cells = [
            BrowserCell(
                row=row,
                col=col,
                row_span=row_span,
                col_span=col_span,
                x=float(cell["x"]),
                y=float(cell["y"]),
                w=float(cell["w"]),
                h=float(cell["h"]),
                tag=cell["tag"],
                text=cell["text"],
                padding={side: float(value) for side, value in cell["padding"].items()},
                borders=_browser_borders(cell["borders"]),
                style=dict(cell["style"]),
            )
            for (row, col, row_span, col_span), cell in zip(slots, raw_cells)
        ]
        caption = table["caption"]
        tables.append(
            BrowserTable(
                x=float(table["x"]),
                y=float(table["y"]),
                w=float(table["w"]),
                h=float(table["h"]),
                border_collapse=table["borderCollapse"],
                border_spacing=table["borderSpacing"],
                background=table["backgroundColor"],
                caption=(
                    None
                    if caption is None
                    else {
                        "text": caption["text"],
                        "side": caption["side"],
                        **{key: float(caption[key]) for key in ("x", "y", "w", "h")},
                    }
                ),
                rows=[
                    {key: float(row[key]) for key in ("x", "y", "w", "h")} for row in table["rows"]
                ],
                cells=cells,
                columns=columns,
                row_borders=[_browser_borders(row["borders"]) for row in table["rows"]],
            )
        )
    return tables


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


def slide_text_loss(pptx: bytes, index: int, document: str) -> list[str]:
    """The words the browser renders for ``document`` that slide ``index`` (0-based) lacks.

    ``text_loss`` for one slide of a deck: ``document`` is the complete
    document exported as that slide. The harness pairs references with slides
    by position, so the slides before it are given an empty reference, which
    holds no word to lose.
    """
    harness = fidelity_harness()
    names = [f"slide-{position}" for position in range(1, index + 2)]
    with tempfile.TemporaryDirectory(prefix="tellr-text-loss-") as directory:
        out_dir = Path(directory)
        truth_dir = out_dir / "truth"
        truth_dir.mkdir()
        for name in names[:-1]:
            (truth_dir / f"{name}.txt").write_text("", encoding="utf-8")
        (truth_dir / f"{names[-1]}.txt").write_text(browser_text(document), encoding="utf-8")
        pptx_path = out_dir / "export.pptx"
        pptx_path.write_bytes(pptx)
        missing = harness.check_text_loss(pptx_path, names, out_dir)
    return missing.get(names[-1], [])


# ---------------------------------------------------------------------------
# Google Slides: the Drive conversion the Google Slides export uses
# ---------------------------------------------------------------------------

# Minting a token refreshes the credentials over the network: bounded, so an
# offline machine skips rather than hangs.
GCLOUD_TOKEN_TIMEOUT_SECONDS = 60
# Google tests upload to the owner's Drive, so they run only when asked to.
GOOGLE_TESTS_SWITCH = "TELLR_GOOGLE_TESTS"
# The quota project run.py::_google_request bills when GOOGLE_QUOTA_PROJECT is
# unset; the Drive calls made here send the same headers as it does.
GOOGLE_QUOTA_PROJECT_DEFAULT = "gcp-dev-field-eng-aiapiquota"
DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
GOOGLE_REQUEST_TIMEOUT_SECONDS = 60


@functools.cache
def google_slides_available() -> bool:
    """Whether ``gcloud auth application-default print-access-token`` exits 0.

    Run once per session, and only when a test marked ``requires_google_slides``
    is about to run: the command takes seconds.
    """
    if shutil.which("gcloud") is None:
        return False
    try:
        process = subprocess.run(
            ["gcloud", "auth", "application-default", "print-access-token"],
            capture_output=True,
            text=True,
            timeout=GCLOUD_TOKEN_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return process.returncode == 0


def google_tests_enabled() -> bool:
    """Whether Google tests run: ``TELLR_GOOGLE_TESTS=1`` AND gcloud can mint a token.

    The switch is read first, so a run that has not opted in never calls gcloud.
    """
    return os.environ.get(GOOGLE_TESTS_SWITCH) == "1" and google_slides_available()


# A string condition is evaluated when a marked test is set up (with ``sys`` in
# its namespace), not when this module is imported, so collecting the suite
# never waits on gcloud.
requires_google_slides: pytest.MarkDecorator = pytest.mark.skipif(
    f"not sys.modules[{__name__!r}].google_tests_enabled()",
    reason=(
        f"uploads to Google Drive: opt in with {GOOGLE_TESTS_SWITCH}=1, with gcloud "
        "application-default credentials (gcloud auth application-default login) and the "
        "quota project in GOOGLE_QUOTA_PROJECT"
    ),
)


@dataclass(frozen=True)
class GoogleSlidesConversion:
    """A deck Drive converted: the Slides API presentation, its URL and its Drive file id."""

    presentation: dict
    url: str
    presentation_id: str


def _google_headers() -> dict[str, str]:
    """The headers run.py::_google_request sends: a fresh ADC token and the quota project."""
    return {
        "Authorization": f"Bearer {fidelity_harness()._google_token()}",
        "x-goog-user-project": os.environ.get("GOOGLE_QUOTA_PROJECT", GOOGLE_QUOTA_PROJECT_DEFAULT),
    }


def _drive_file_url(file_id: str) -> str:
    return f"{DRIVE_FILES_URL}/{urllib.parse.quote(file_id, safe='')}"


def delete_drive_file(file_id: str) -> None:
    """Delete a Drive file for good, by its id: Drive v3 ``files.delete``, which skips the trash."""
    request = urllib.request.Request(
        _drive_file_url(file_id), headers=_google_headers(), method="DELETE"
    )
    with urllib.request.urlopen(request, timeout=GOOGLE_REQUEST_TIMEOUT_SECONDS) as response:
        response.read()


def drive_file_exists(file_id: str) -> bool:
    """Whether Drive still holds the file: ``files.get`` answers 404 once it is deleted."""
    request = urllib.request.Request(
        f"{_drive_file_url(file_id)}?fields=id", headers=_google_headers(), method="GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=GOOGLE_REQUEST_TIMEOUT_SECONDS) as response:
            response.read()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return False
        raise
    return True


def google_slides_presentation(pptx: bytes, names: list[str]) -> GoogleSlidesConversion:
    """Convert a deck through Drive, as the Google Slides export does.

    Runs the fidelity harness's ``render_with_google_slides``: the deck is
    uploaded to Drive as a Google Slides presentation (named
    ``tellr-export-fidelity <timestamp>``), whose URL the harness records in
    ``gslides_url.txt`` at once, then read back through the Slides API
    (``gslides.json``) and thumbnailed (one name per slide). The presentation
    stays in Drive: the caller deletes it with ``delete_drive_file`` once it
    has read the JSON, in a ``finally``. When the harness fails at any point
    after the upload, the presentation the recorded URL names is deleted here
    before the error propagates.
    """
    harness = fidelity_harness()
    with tempfile.TemporaryDirectory(prefix="tellr-gslides-") as directory:
        out_dir = Path(directory)
        pptx_path = out_dir / "export.pptx"
        pptx_path.write_bytes(pptx)
        recorded = out_dir / "gslides_url.txt"
        try:
            url = harness.render_with_google_slides(pptx_path, names, out_dir)
        except BaseException:
            if recorded.exists():
                delete_drive_file(_presentation_id(recorded.read_text(encoding="utf-8")))
            raise
        presentation = json.loads((out_dir / "gslides.json").read_text(encoding="utf-8"))
    return GoogleSlidesConversion(
        presentation=presentation, url=url, presentation_id=presentation["presentationId"]
    )


PRESENTATION_URL = re.compile(r"https://docs\.google\.com/presentation/d/([^/\s]+)/edit")


def _presentation_id(recorded_url: str) -> str:
    """The Drive file id of the presentation ``gslides_url.txt`` names."""
    match = PRESENTATION_URL.search(recorded_url)
    assert match, f"gslides_url.txt names no presentation: {recorded_url!r}"
    return match.group(1)


def slides_api_tables(presentation: dict, index: int) -> list[dict]:
    """The table page elements of slide ``index`` (0-based) of a Slides API presentation.

    Each is the page element itself (``size``, ``transform``, ``table``). In a
    ``table``, ``horizontalBorderRows[i]`` is the line along the TOP of row
    ``i`` (one more than the rows), ``verticalBorderRows[r]
    .tableBorderCells[c]`` the line along the LEFT of column ``c`` in row ``r``,
    and a zero row or column index is omitted from a ``location``.
    """
    slides = presentation.get("slides", [])
    assert 0 <= index < len(slides), (
        f"slide index {index} is out of range: the presentation has {len(slides)} slides"
    )
    return [element for element in slides[index].get("pageElements", []) if "table" in element]


def slides_api_color(fill: dict | None) -> str | None:
    """'RRGGBB' of a Slides API fill (``{"solidFill": {"color": {"rgbColor": …}, "alpha": …}}``).

    None when it paints nothing: no solid fill, alpha 0 (how Drive reads an
    ``a:noFill`` border), or no RGB colour. A channel the API omits is 0.
    """
    solid = (fill or {}).get("solidFill")
    if not solid or solid.get("alpha", 1) == 0:
        return None
    rgb = solid.get("color", {}).get("rgbColor")
    if rgb is None:
        return None
    return "".join(
        f"{round(rgb.get(channel, 0) * 255):02X}" for channel in ("red", "green", "blue")
    )


def slides_api_cell_text(cell: dict) -> str:
    """The text of a Slides API table cell, its text runs concatenated."""
    return "".join(
        element.get("textRun", {}).get("content", "")
        for element in cell.get("text", {}).get("textElements", [])
    )


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
    # keys 'left' 'right' 'top' 'bottom'; None when the side is absent or a:noFill
    borders: dict[str, Border | None]
    # The sides whose a:lnL/lnR/lnT/lnB the a:tcPr writes at all, a:noFill ones
    # included: a side left out is no line in PowerPoint but Drive's default.
    sides_written: frozenset[str] = frozenset()


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
        sides_written=frozenset(
            side
            for side, element in sides.items()
            if properties is not None and properties.find(f"a:{element}", NAMESPACES) is not None
        ),
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


# ---------------------------------------------------------------------------
# Native tables: the a:tbl grid of a graphicFrame, in CSS px
# ---------------------------------------------------------------------------


def table_frames(shapes: list[Shape]) -> list[tuple[int, Shape]]:
    """(spTree index, shape) of every native table (a ``p:graphicFrame`` with ``a:tbl``), by z.

    In spTree order, back to front.
    """
    return [(position, shape) for position, shape in enumerate(shapes) if shape.kind == "table"]


def table_extent(frame: Shape) -> dict:
    """``{"x", "y", "w", "h"}`` of a native table as PowerPoint lays it out, in CSS px.

    Its frame's offset, and the sums of its ``gridCol`` widths and ``a:tr``
    heights: PowerPoint sizes a table from its grid, not from the frame's
    ``a:ext``.
    """
    assert frame.table is not None, f"{frame.kind} {frame.name!r} is not a native table"
    return {
        "x": frame.x,
        "y": frame.y,
        "w": sum(frame.table.col_widths),
        "h": sum(frame.table.row_heights),
    }


def _edges(start: float, sizes: list[float]) -> list[float]:
    edges = [start]
    for size in sizes:
        edges.append(edges[-1] + size)
    return edges


def table_column_edges(frame: Shape) -> list[float]:
    """The x of every vertical grid line of a native table, left to right, in CSS px.

    One more than its columns.
    """
    assert frame.table is not None, f"{frame.kind} {frame.name!r} is not a native table"
    return _edges(frame.x, frame.table.col_widths)


def table_row_edges(frame: Shape) -> list[float]:
    """The y of every horizontal grid line of a native table, top to bottom, in CSS px.

    One more than its rows.
    """
    assert frame.table is not None, f"{frame.kind} {frame.name!r} is not a native table"
    return _edges(frame.y, frame.table.row_heights)


def table_slot_owner(table: Table, row: int, col: int) -> tuple[int, int]:
    """The grid slot of the cell that covers slot ``(row, col)``: itself, or the merge's origin.

    Every slot of an ``a:tbl`` is an ``a:tc``. One a merge covers is a
    placeholder: ``hMerge`` continues the cell to its left, ``vMerge`` the
    cell above (a slot under a cell spanning both ways is both), so the owner
    is found by walking left over ``hMerge`` and up over ``vMerge``.
    """
    assert 0 <= row < len(table.rows) and 0 <= col < len(table.rows[row]), (
        f"grid slot ({row}, {col}) is outside the {len(table.rows)}-row table"
    )
    while True:
        cell = table.rows[row][col]
        if cell.h_merge and col > 0:
            col -= 1
        elif cell.v_merge and row > 0:
            row -= 1
        else:
            return row, col


def table_cell_rect(frame: Shape, row: int, col: int) -> dict:
    """``{"x", "y", "w", "h"}`` of the cell covering slot ``(row, col)``, spans included.

    In CSS px, from the grid lines PowerPoint lays the table out on.
    """
    assert frame.table is not None, f"{frame.kind} {frame.name!r} is not a native table"
    owner_row, owner_col = table_slot_owner(frame.table, row, col)
    owner = frame.table.rows[owner_row][owner_col]
    columns = table_column_edges(frame)
    rows = table_row_edges(frame)
    right = columns[min(owner_col + owner.grid_span, len(columns) - 1)]
    bottom = rows[min(owner_row + owner.row_span, len(rows) - 1)]
    return {
        "x": columns[owner_col],
        "y": rows[owner_row],
        "w": right - columns[owner_col],
        "h": bottom - rows[owner_row],
    }


def overlaps(a: Shape, b: Shape, tolerance_px: float = 0.5) -> bool:
    """Whether the boxes of ``a`` and ``b`` intersect by more than ``tolerance_px`` on both axes.

    Boxes are compared axis-aligned, ignoring rotation.
    """
    horizontal = min(a.x + a.w, b.x + b.w) - max(a.x, b.x)
    vertical = min(a.y + a.h, b.y + b.h) - max(a.y, b.y)
    return horizontal > tolerance_px and vertical > tolerance_px
