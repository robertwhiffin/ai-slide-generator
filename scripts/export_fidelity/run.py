"""Export fidelity harness: what the user sees vs what the export produces.

For a fixture deck (``deck.css`` + ``deck.json`` + ``slides/*.html``) this:

1. builds every slide's export document with the production
   ``build_slide_html`` (so the harness exercises exactly what the export
   routes feed the sidecar);
2. renders the ground truth: a 1280x720 Chromium screenshot of that document;
3. runs the production export (``build_pptx_huashu``) to a .pptx,
   written for PowerPoint (``target="pptx"``), recording the snapshot
   engine's per-slide summary lines in ``summaries.json``, and reports the
   words the browser renders that the .pptx lacks (``text_loss.json``),
   leaving out each slide's hidden text, the words the page reads but the
   slide does not show;
4. renders the .pptx with LibreOffice (``--lo``) and/or PowerPoint
   (``--powerpoint``), each app's PDF rasterised at 4x and box-filtered to
   1280x720 (``rasterise_pdf``), and/or converts a deck written for Google
   Slides (``target="gslides"``, ``export-gslides.pptx``) through Drive and
   downloads the slide thumbnails (``--gslides``): the deck and the conversion
   the Google Slides export uses, whose text loss is checked as well
   (``text_loss-gslides.json``);
5. writes one side-by-side comparison PNG per slide plus a ``scores.json``
   holding a per-slide visual difference score (lower is closer), and a
   ``summary.md`` table of every slide's scores, against a baseline run's
   with ``--baseline``, its text loss, MODEL DROPS and captures, per deck.

Usage (from the repo root)::

    uv run --with pymupdf --with pillow python scripts/export_fidelity/run.py \
        tests/fixtures/export_fidelity --out /tmp/fidelity --lo --gslides

The Google Slides path uses gcloud application-default credentials and the
quota project in ``GOOGLE_QUOTA_PROJECT``. Converted presentations are left in
Drive (named ``tellr-export-fidelity <timestamp>``) so they can be opened
and inspected; delete them by hand when finished.

``--pin-fonts`` replaces the deck CSS's Google Fonts ``@import`` lines with the
same faces from committed files (``pinned_fonts_css``), so two runs, before and
after a change, render with one font binary per face. ``--baseline DIR`` names
an earlier run's ``--out``, whose scores ``summary.md`` sets each of this run's
against.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import datetime
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import urllib.request
from pathlib import Path
from typing import TextIO

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.api.routes.export import build_slide_html  # noqa: E402
from src.services import pptx_from_html_huashu  # noqa: E402

SLIDE_WIDTH_PX = 1280
SLIDE_HEIGHT_PX = 720

# PowerPoint's PDF embeds each picture at twice its slide size, with an alpha
# mask and /Interpolate true. MuPDF drawing such a page at the slide's own
# 1280 px draws a picture's light rules dark (corpus slide 03's two rows of
# EBEBEB gridline at B2B2B1 and B4B4B2) and a fringe round a mark in the
# ground's own colour, which neither the UI nor Apple's Quartz drawing the same
# PDF shows: an artefact of the harness's raster, not of the export (Task 14
# Phase A, H1). Drawn at this many times the slide's size and box-filtered
# down, each pixel the mean of the 16 it covers, the page comes out closer to
# Quartz's (E9EAE9 and D0D1D0; CALIBRATION.md H1). The method is recorded in
# each run's harness.json (HARNESS_RECORD), so a summary can tell a baseline
# rasterised another way, whose PowerPoint scores do not compare.
PDF_RASTER_SCALE = 4
PDF_RASTER = f"MuPDF at {PDF_RASTER_SCALE}x, box-filtered to {SLIDE_WIDTH_PX}x{SLIDE_HEIGHT_PX}"
HARNESS_RECORD = "harness.json"


# A fixture deck loads its webfonts with a Google Fonts @import, and Google now
# and then answers one with another stylesheet naming another font file, so two
# runs of one deck can render it differently (text widths move PowerPoint scores
# by about 0.08). --pin-fonts replaces each import with the faces Google serves
# for it, as data: (the slide CSP's font-src allows it): the latin files, the
# only subset the corpora's text reaches, committed with their OFL licences
# under tests/fixtures/export_snapshot/fonts and declared as Google declares
# them. The corpus deck's import pins to the faces the snapshot tests pin
# (tests/fixtures/export_snapshot_support.py pinned_font_css).
PINNED_FONT_DIR = REPO_ROOT / "tests" / "fixtures" / "export_snapshot" / "fonts"
GOOGLE_FONTS_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com")
GOOGLE_FONTS_IMPORT = re.compile(
    r"^@import url\('(https://fonts\.googleapis\.com/[^']*)'\);\n", re.M
)
LATIN_UNICODE_RANGE = (
    "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, "
    "U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, "
    "U+FEFF, U+FFFD"
)
# tests/fixtures/export_fidelity/deck.css. DM Sans with its optical-size axis:
# gstatic /s/dmsans/v17/rP2Hp2ywxg089UriCZOIHTWEBlw.woff2; DM Mono 400 and 500:
# /s/dmmono/v16/aFTU7PB1QTsUX8KYthqQBK6PYK0 and aFTR7PB1QTsUX8KYvumzEYOtbYf-Vlg.
CORPUS_FONTS_IMPORT = (
    "https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:"
    "opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700&display=swap"
)
# The design-system corpus's deck.css. Its DM Sans names no optical-size axis,
# so Google serves another file, with a weight axis only:
# /s/dmsans/v17/rP2Yp2ywxg089UriI5-g4vlH9VoD8Cmcqbu0-K6z9mXg.woff2; its italic,
# rP2rp2ywxg089UriCZaSExd86J3t9jz86Mvy4qCRAL19DksVat-JDV30TGcro9o45zw; DM Mono
# 300: /s/dmmono/v16/aFTR7PB1QTsUX8KYvrGyEYOtbYf-Vlg; Barlow 400 to 700:
# /s/barlow/v13/7cHpv4kjgoGqM7E_DMs5ynghnQ, 7cHqv4kjgoGqM7E3_-gs51ostz0rdg,
# 7cHqv4kjgoGqM7E30-8s51ostz0rdg and 7cHqv4kjgoGqM7E3t-4s51ostz0rdg.
DESIGN_SYSTEM_FONTS_IMPORT = (
    "https://fonts.googleapis.com/css2?family=DM+Mono:wght@300;400;500&family=DM+Sans:"
    "ital,wght@0,400;0,500;0,600;0,700;1,400&display=swap"
)
DESIGN_SYSTEM_DISPLAY_FONTS_IMPORT = (
    "https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600;700&display=swap"
)
# Import URL -> its faces, as Google declares them: (family, style, weight, file
# under PINNED_FONT_DIR).
PINNED_FONT_IMPORTS: dict[str, tuple[tuple[str, str, int, str], ...]] = {
    CORPUS_FONTS_IMPORT: (
        ("DM Mono", "normal", 400, "dm-mono/DMMono-400-latin.woff2"),
        ("DM Mono", "normal", 500, "dm-mono/DMMono-500-latin.woff2"),
        ("DM Sans", "normal", 400, "dm-sans/DMSans-latin.woff2"),
        ("DM Sans", "normal", 500, "dm-sans/DMSans-latin.woff2"),
        ("DM Sans", "normal", 600, "dm-sans/DMSans-latin.woff2"),
        ("DM Sans", "normal", 700, "dm-sans/DMSans-latin.woff2"),
    ),
    DESIGN_SYSTEM_FONTS_IMPORT: (
        ("DM Mono", "normal", 300, "dm-mono/DMMono-300-latin.woff2"),
        ("DM Mono", "normal", 400, "dm-mono/DMMono-400-latin.woff2"),
        ("DM Mono", "normal", 500, "dm-mono/DMMono-500-latin.woff2"),
        ("DM Sans", "italic", 400, "dm-sans/DMSans-Italic-400-latin.woff2"),
        ("DM Sans", "normal", 400, "dm-sans/DMSans-wght-latin.woff2"),
        ("DM Sans", "normal", 500, "dm-sans/DMSans-wght-latin.woff2"),
        ("DM Sans", "normal", 600, "dm-sans/DMSans-wght-latin.woff2"),
        ("DM Sans", "normal", 700, "dm-sans/DMSans-wght-latin.woff2"),
    ),
    DESIGN_SYSTEM_DISPLAY_FONTS_IMPORT: (
        ("Barlow", "normal", 400, "barlow/Barlow-400-latin.woff2"),
        ("Barlow", "normal", 500, "barlow/Barlow-500-latin.woff2"),
        ("Barlow", "normal", 600, "barlow/Barlow-600-latin.woff2"),
        ("Barlow", "normal", 700, "barlow/Barlow-700-latin.woff2"),
    ),
}


def _pinned_face(family: str, style: str, weight: int, name: str) -> str:
    """One pinned face as an @font-face rule, its file embedded as data:."""
    font = base64.b64encode((PINNED_FONT_DIR / name).read_bytes()).decode("ascii")
    return (
        f"@font-face {{ font-family: '{family}'; font-style: {style}; font-weight: {weight}; "
        f"font-display: swap; src: url(data:font/woff2;base64,{font}) format('woff2'); "
        f"unicode-range: {LATIN_UNICODE_RANGE}; }}"
    )


def pinned_fonts_css(css: str) -> str:
    """``css`` with each Google Fonts @import line replaced by its pinned faces.

    The faces come first, in import order, then the CSS without its import
    lines. An import PINNED_FONT_IMPORTS has no faces for, or any other
    reference to Google Fonts left (an import written another way, an
    @font-face loading a Google file), raises ValueError naming it: a pinned
    run never loads a live webfont.
    """
    imports = GOOGLE_FONTS_IMPORT.findall(css)
    unpinned = [url for url in imports if url not in PINNED_FONT_IMPORTS]
    if unpinned:
        raise ValueError(f"no pinned faces for the Google Fonts import(s) {unpinned}")
    rest = GOOGLE_FONTS_IMPORT.sub("", css)
    for host in GOOGLE_FONTS_HOSTS:
        if host in rest:
            line = next(line for line in rest.splitlines() if host in line)
            raise ValueError(
                f"the CSS still loads from {host}, which cannot be pinned: {line.strip()[:200]}"
            )
    faces = [_pinned_face(*face) for url in imports for face in PINNED_FONT_IMPORTS[url]]
    return "".join(face + "\n" for face in faces) + rest


def load_fixture_deck(
    fixture_dir: Path, pin_fonts: bool = False
) -> tuple[dict, list[tuple[str, str]]]:
    """The fixture deck (deck.json with deck.css as its ``css``) and its slides, by name.

    With ``pin_fonts`` the deck's CSS loads its webfonts from the pinned files
    (pinned_fonts_css), and a slide that loads Google Fonts itself raises
    ValueError naming it.
    """
    deck = json.loads((fixture_dir / "deck.json").read_text(encoding="utf-8"))
    deck["css"] = (fixture_dir / "deck.css").read_text(encoding="utf-8")
    slides = [
        (path.stem, path.read_text(encoding="utf-8"))
        for path in sorted((fixture_dir / "slides").glob("*.html"))
    ]
    if pin_fonts:
        deck["css"] = pinned_fonts_css(deck["css"])
        unpinned = [
            name for name, html in slides if any(host in html for host in GOOGLE_FONTS_HOSTS)
        ]
        if unpinned:
            raise ValueError(
                f"slide(s) {unpinned} load Google Fonts themselves, which cannot be pinned"
            )
    return deck, slides


def build_documents(deck: dict, slides: list[tuple[str, str]], out_dir: Path) -> list[Path]:
    documents_dir = out_dir / "documents"
    documents_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, html in slides:
        document = build_slide_html({"slide_id": name, "html": html}, deck)
        path = documents_dir / f"{name}.html"
        path.write_text(document, encoding="utf-8")
        paths.append(path)
    return paths


def render_truth(documents: list[Path], out_dir: Path) -> None:
    truth_dir = out_dir / "truth"
    truth_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["node", str(Path(__file__).with_name("render_truth.cjs")), str(truth_dir), *map(str, documents)],
        check=True,
    )


# build_pptx_huashu echoes every sidecar stderr line behind this prefix. The
# snapshot engine logs one summary line per slide it writes (render_slide.cjs);
# a message the slide's own script logs reaches stderr as "Browser console: …",
# all of it on that one line whatever line breaks it holds (log_line.cjs), so
# slide script cannot pass for one.
SIDECAR_ECHO_PREFIX = "[huashu-emit] "
SLIDE_SUMMARY_LINE = SIDECAR_ECHO_PREFIX + "[html2pptx] slide summary "
# How export_pptx starts its warning for a slide part of whose model Node
# dropped (the summary's modelDrops, services/pptx-emit-huashu/model_check.cjs).
MODEL_DROPS_WARNING = "MODEL DROPS: "


class _Tee(io.TextIOBase):
    """A text stream that writes through to every stream it holds."""

    def __init__(self, *streams: TextIO) -> None:
        super().__init__()
        self._streams = streams

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        for stream in self._streams:
            stream.write(text)
        return len(text)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()


def _target_suffix(target: str) -> str:
    """What the files written for ``target`` add to their names: "" for PowerPoint."""
    return "" if target == "pptx" else f"-{target}"


def slide_summaries(stderr: str) -> list[dict]:
    """The JSON of each slide summary line the sidecar logged, in the order logged."""
    return [
        json.loads(line.removeprefix(SLIDE_SUMMARY_LINE))
        for line in stderr.splitlines()
        if line.startswith(SLIDE_SUMMARY_LINE)
    ]


def _summaries_by_document(
    summaries: list[dict], failures: list[dict], count: int
) -> list[dict | None]:
    """One entry per document, in slide order: its summary, or None for one the export failed.

    The sidecar writes the documents in order and logs a summary for each
    slide it writes, so the summaries belong to the documents ``failures`` does
    not name, in order. Summaries that do not match those documents one for
    one say nothing of any document.
    """
    failed = {failure.get("slide_index") for failure in failures}
    written = [index for index in range(count) if index not in failed]
    recorded: list[dict | None] = [None] * count
    if len(summaries) != len(written):
        if summaries:
            print(
                f"[export-fidelity] {len(summaries)} slide summaries for {len(written)} written "
                "slides: none is recorded",
                file=sys.stderr,
            )
        return recorded
    for index, summary in zip(written, summaries):
        recorded[index] = summary
    return recorded


def export_pptx(deck: dict, documents: list[Path], out_dir: Path, target: str = "pptx") -> Path:
    """The production export of ``documents``, written for ``target``: export.pptx for
    PowerPoint, export-gslides.pptx for Google Slides, with failures.json or
    failures-gslides.json beside it.

    The sidecar's stderr, which build_pptx_huashu echoes, is teed: it still
    reaches the ``sys.stderr`` in effect when this is called, and its slide
    summary lines are recorded in summaries.json or summaries-gslides.json
    (the harness reads them there), one entry per document in slide order, null for a
    slide the export failed. Each slide's speaker notes are its document's
    name, which check_text_loss pairs its reference with. A slide whose model
    Node dropped part of (its summary's modelDrops) exported without that part,
    so it is named in a MODEL DROPS warning on stderr.
    """
    os.environ["HUASHU_PIPELINE_ENABLED"] = "1"
    slides_payload = [{"html": path.read_text(encoding="utf-8"), "notes": path.stem} for path in documents]
    echoed = io.StringIO()
    with contextlib.redirect_stderr(_Tee(sys.stderr, echoed)):
        pptx_bytes, failures = pptx_from_html_huashu.build_pptx_huashu(
            deck.get("title", "slides"), slides_payload, bypass_validation=True, target=target
        )
    suffix = _target_suffix(target)
    (out_dir / f"failures{suffix}.json").write_text(json.dumps(failures, indent=2), encoding="utf-8")
    summaries = _summaries_by_document(slide_summaries(echoed.getvalue()), failures, len(documents))
    (out_dir / f"summaries{suffix}.json").write_text(
        json.dumps(summaries, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    for path, summary in zip(documents, summaries):
        drops = (summary or {}).get("modelDrops") or 0
        if drops:
            print(
                f"{MODEL_DROPS_WARNING}{path.stem}: {drops} part(s) of its slide model failed "
                "validation and were dropped; the slide exported without them",
                file=sys.stderr,
            )
    pptx_path = out_dir / f"export{suffix}.pptx"
    pptx_path.write_bytes(pptx_bytes)
    return pptx_path


def recorded_summaries(out_dir: Path, target: str = "pptx") -> list[dict | None]:
    """The slide summaries export_pptx recorded for ``target``, one per document."""
    path = out_dir / f"summaries{_target_suffix(target)}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def rasterise_pdf(pdf_path: Path, names: list[str], out_dir: Path) -> None:
    """Each page of an app's PDF as ``out_dir/<names[i]>.png``, the slide's 1280x720.

    The page is drawn at PDF_RASTER_SCALE times the slide's size and
    box-filtered down, so a picture the PDF embeds at twice its size is drawn
    as the app shows it, not with MuPDF's dark rules and fringes (PDF_RASTER).
    """
    import fitz  # pymupdf
    from PIL import Image

    pdf = fitz.open(pdf_path)
    for index, page in enumerate(pdf):
        zoom = PDF_RASTER_SCALE * SLIDE_WIDTH_PX / page.rect.width
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        drawn = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        drawn.resize((SLIDE_WIDTH_PX, SLIDE_HEIGHT_PX), Image.BOX).save(
            out_dir / f"{names[index]}.png"
        )


def render_with_libreoffice(pptx_path: Path, names: list[str], out_dir: Path) -> None:
    soffice = shutil.which("soffice") or "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    lo_dir = out_dir / "libreoffice"
    lo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(lo_dir), str(pptx_path)],
        check=True,
        capture_output=True,
    )
    rasterise_pdf(lo_dir / (pptx_path.stem + ".pdf"), names, lo_dir)


POWERPOINT_STAGING_DIR = (
    Path.home() / "Library" / "Containers" / "com.microsoft.Powerpoint" / "Data" / "tellr-export-fidelity"
)


# The harness's own presentations: every copy it stages is POWERPOINT_STAGING_DIR/export-*.pptx.
POWERPOINT_STAGED_PREFIX = "export-"
# How long closing the harness's presentations may take before it is given up.
POWERPOINT_CLOSE_TIMEOUT_SECONDS = 60


def _applescript_string(text: str) -> str:
    """``text`` as an AppleScript string literal."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def close_harness_presentations(timeout_seconds: float = POWERPOINT_CLOSE_TIMEOUT_SECONDS) -> bool:
    """Close, without saving, the presentations the harness staged, and nothing else.

    A presentation is the harness's when PowerPoint opened it from
    POWERPOINT_STAGING_DIR and its name starts with POWERPOINT_STAGED_PREFIX.
    Every other document stays open as the owner left it: PowerPoint is never
    quit "saving no", which would discard the owner's unsaved work. Nothing
    happens when PowerPoint is not running. Presentations are read by index,
    because a ``repeat with … in presentations`` reference loop hangs
    PowerPoint's AppleScript. Returns whether PowerPoint answered within
    ``timeout_seconds``; a modal dialog can hold it.
    """
    staging_dir = _applescript_string(str(POWERPOINT_STAGING_DIR))
    prefix = _applescript_string(POWERPOINT_STAGED_PREFIX)
    script = f"""
if application "Microsoft PowerPoint" is running then
  with timeout of {int(timeout_seconds)} seconds
    tell application "Microsoft PowerPoint"
      repeat with position from (count of presentations) to 1 by -1
        set candidate to presentation position
        if (path of candidate) is {staging_dir} and (name of candidate) starts with {prefix} then
          close candidate saving no
        end if
      end repeat
    end tell
  end timeout
end if
"""
    try:
        completed = subprocess.run(
            ["osascript", "-e", script],
            check=False,
            capture_output=True,
            timeout=timeout_seconds + 10,
        )
    except subprocess.TimeoutExpired:
        return False
    return completed.returncode == 0


def render_with_powerpoint(pptx_path: Path, names: list[str], out_dir: Path) -> Path:
    """Render the .pptx with Microsoft PowerPoint for Mac (the PPTX ground truth).

    PowerPoint is sandboxed: opening or saving outside its container raises a
    "grant access" dialog, so the file is staged inside the container first.
    Needs the deck's fonts installed locally (DM Sans / DM Mono for the corpora).

    Every run stages under a name of its own, because ``open`` on a file whose
    name is still open re-activates the old presentation, and its PDF would
    hold the wrong slides. A staged copy an earlier run left open is closed
    first (close_harness_presentations); the owner's own documents are never
    touched, so the script saves and closes only the presentation whose path
    is the copy it staged. The PDF is copied into ``out_dir/powerpoint``,
    where each page is rasterised (rasterise_pdf), and both staged files are
    deleted from the container. Returns the copied PDF.
    """
    close_harness_presentations()
    POWERPOINT_STAGING_DIR.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')}-{os.getpid()}"
    staged_pptx = POWERPOINT_STAGING_DIR / f"{POWERPOINT_STAGED_PREFIX}{stamp}.pptx"
    staged_pdf = POWERPOINT_STAGING_DIR / f"{POWERPOINT_STAGED_PREFIX}{stamp}.pdf"
    powerpoint_dir = out_dir / "powerpoint"
    powerpoint_dir.mkdir(parents=True, exist_ok=True)
    exported_pdf = powerpoint_dir / f"{pptx_path.stem}.pdf"
    shutil.copyfile(pptx_path, staged_pptx)
    staged = _applescript_string(str(staged_pptx))
    script = f"""
with timeout of 600 seconds
tell application "Microsoft PowerPoint"
  open POSIX file {staged}
  delay 3
  set exported to presentation {_applescript_string(staged_pptx.name)}
  if (full name of exported) is not {staged} then error "PowerPoint did not open " & {staged}
  save exported in POSIX file {_applescript_string(str(staged_pdf))} as save as PDF
  close exported saving no
end tell
end timeout
"""
    try:
        subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
        shutil.copyfile(staged_pdf, exported_pdf)
    except BaseException:
        # The script stopped part-way: its presentation may still be open.
        close_harness_presentations()
        raise
    finally:
        staged_pptx.unlink(missing_ok=True)
        staged_pdf.unlink(missing_ok=True)
    rasterise_pdf(exported_pdf, names, powerpoint_dir)
    return exported_pdf


# Unicode's Default_Ignorable_Code_Point (DerivedCoreProperties.txt), as
# inclusive ranges: characters that render as nothing, which the text-loss
# comparison sees through. The PowerPoint deck writes U+2060 WORD JOINER after a
# line-ending script run; authored text carries U+200B, U+00AD and their kin.
# The set text_check.cjs reads as \p{Default_Ignorable_Code_Point}.
_DEFAULT_IGNORABLE_RANGES = (
    (0x00AD, 0x00AD),
    (0x034F, 0x034F),
    (0x061C, 0x061C),
    (0x115F, 0x1160),
    (0x17B4, 0x17B5),
    (0x180B, 0x180F),
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2060, 0x206F),
    (0x3164, 0x3164),
    (0xFE00, 0xFE0F),
    (0xFEFF, 0xFEFF),
    (0xFFA0, 0xFFA0),
    (0xFFF0, 0xFFF8),
    (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A),
    (0xE0000, 0xE0FFF),
)
_DEFAULT_IGNORABLE = {
    code_point: None
    for start, end in _DEFAULT_IGNORABLE_RANGES
    for code_point in range(start, end + 1)
}
# U+2010 HYPHEN, which NFKC also makes of U+2011 NON-BREAKING HYPHEN: the decks
# write either as U+002D where an app would draw it from another font, the
# hyphen-minus the browser draws it as (CALIBRATION.md D8).
_HYPHEN_AS_MINUS = {0x2010: "-"}


def _normalise_text(text: str) -> str:
    """``text`` as the text-loss check compares it: text_check.cjs's normalisation, and a fold.

    Compatibility forms are folded (NFKC: a literal "¹" is "1", a ligature its
    letters, a fullwidth form its ASCII), then white space and default-ignorable
    code points are removed, then the rest is lower-cased, as text_check.cjs
    does. Besides, U+2010 (which NFKC also makes of U+2011) is the hyphen-minus
    the decks may write it as (emit_typography.cjs runText): this check reads
    the written deck, where text_check.cjs reads the slide model, which keeps
    the page's own characters and so needs no fold.
    """
    folded = unicodedata.normalize("NFKC", text).translate(_HYPHEN_AS_MINUS)
    folded = folded.translate(_DEFAULT_IGNORABLE)
    return "".join(folded.split()).lower()


def _slide_text(slide) -> str:
    """Every text frame's and table cell's text on ``slide``, run together."""
    exported = ""
    for shape in slide.shapes:
        if shape.has_text_frame:
            exported += shape.text_frame.text
        if shape.has_table:
            exported += "".join(cell.text for row in shape.table.rows for cell in row.cells)
    return exported


def _notes_text(slide) -> str | None:
    """``slide``'s speaker notes, or None when it has none."""
    if not slide.has_notes_slide:
        return None
    notes = slide.notes_slide.notes_text_frame
    return None if notes is None else notes.text.strip()


def _slides_by_name(slides: list, names: list[str]) -> dict:
    """The slide each reference name was exported as; a name the deck has no slide for is absent.

    export_pptx writes each document's name as its slide's speaker notes, so
    when the notes name the slides, a slide the export failed leaves its name
    without a slide wherever it falls in the deck (upstream PR #59), and the
    slides after it keep their own references. A deck whose notes do not name
    its slides (one export_pptx did not write) is paired by position.
    """
    notes = [_notes_text(slide) for slide in slides]
    if notes and len(set(notes)) == len(notes) and set(notes) <= set(names):
        return dict(zip(notes, slides))
    return dict(zip(names, slides))


def check_text_loss(
    pptx_path: Path,
    names: list[str],
    out_dir: Path,
    hidden_text: list[str] | None = None,
    target: str = "pptx",
) -> dict[str, list[str]]:
    """Words the browser renders that are absent from the exported slide.

    The reference is the browser's own rendered text (render_truth.cjs writes
    it), which no extraction code touches, so text the exporter drops shows up
    here. SVG and canvas text is excluded: it travels inside the picture. A
    word is lost when its normalised form (_normalise_text) is no substring of
    its slide's normalised text; a slide the deck lacks loses every word.

    ``hidden_text[i]``, when given, is the hidden text of slide ``names[i]``
    (its slide summary's ``hiddenText``): the words the
    page reads but the slide does not show, each whole (opacity 0, a clip, off
    the slide, cut by an ellipsis), which are no loss. A slide the deck lacks
    shows none of its words, so nothing it hides excuses any.

    ``target`` is the renderer the deck was written for, which names the file
    the losses are recorded in: text_loss.json, or text_loss-gslides.json.
    """
    from pptx import Presentation

    if hidden_text is not None and len(hidden_text) != len(names):
        raise ValueError(f"{len(hidden_text)} hidden texts for {len(names)} slides")
    presentation = Presentation(str(pptx_path))
    slides = _slides_by_name(list(presentation.slides), names)
    missing: dict[str, list[str]] = {}
    for index, name in enumerate(names):
        reference = (out_dir / "truth" / f"{name}.txt").read_text(encoding="utf-8")
        slide = slides.get(name)
        exported_normalised = _normalise_text(_slide_text(slide)) if slide is not None else ""
        hidden = hidden_text[index] if hidden_text is not None and slide is not None else ""
        hidden_words = {_normalise_text(word) for word in hidden.split()}
        lost = []
        for word in reference.split():
            normalised = _normalise_text(word)
            if normalised not in exported_normalised and normalised not in hidden_words:
                lost.append(word)
        if lost:
            missing[name] = lost
    (out_dir / f"text_loss{_target_suffix(target)}.json").write_text(
        json.dumps(missing, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return missing


def _google_token() -> str:
    return subprocess.run(
        ["gcloud", "auth", "application-default", "print-access-token"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _google_request(url: str, token: str, data: bytes | None = None, headers: dict | None = None) -> bytes:
    request_headers = {
        "Authorization": f"Bearer {token}",
        "x-goog-user-project": os.environ.get("GOOGLE_QUOTA_PROJECT", "gcp-dev-field-eng-aiapiquota"),
    }
    request_headers.update(headers or {})
    request = urllib.request.Request(url, data=data, headers=request_headers, method="POST" if data else "GET")
    with urllib.request.urlopen(request, timeout=300) as response:
        return response.read()


def render_with_google_slides(pptx_path: Path, names: list[str], out_dir: Path) -> str:
    token = _google_token()
    boundary = "tellr-export-fidelity-boundary"
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    metadata = json.dumps({
        "name": f"tellr-export-fidelity {stamp}",
        "mimeType": "application/vnd.google-apps.presentation",
    })
    body = (
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{metadata}\r\n"
        f"--{boundary}\r\nContent-Type: application/vnd.openxmlformats-officedocument.presentationml.presentation\r\n\r\n"
    ).encode() + pptx_path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    created = json.loads(_google_request(
        "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id",
        token,
        data=body,
        headers={"Content-Type": f"multipart/related; boundary={boundary}"},
    ))
    presentation_id = created["id"]
    url = f"https://docs.google.com/presentation/d/{presentation_id}/edit"
    # Recorded the moment the presentation exists, so a read below that fails
    # still leaves its id to the caller (which may then delete it).
    (out_dir / "gslides_url.txt").write_text(url + "\n", encoding="utf-8")
    presentation = json.loads(_google_request(
        f"https://slides.googleapis.com/v1/presentations/{presentation_id}", token
    ))
    (out_dir / "gslides.json").write_text(json.dumps(presentation), encoding="utf-8")
    gslides_dir = out_dir / "gslides"
    gslides_dir.mkdir(parents=True, exist_ok=True)
    for index, slide in enumerate(presentation.get("slides", [])):
        thumbnail = json.loads(_google_request(
            f"https://slides.googleapis.com/v1/presentations/{presentation_id}/pages/"
            f"{slide['objectId']}/thumbnail?thumbnailProperties.thumbnailSize=LARGE",
            token,
        ))
        image = _google_request(thumbnail["contentUrl"], token)
        (gslides_dir / f"{names[index]}.png").write_bytes(image)
        time.sleep(0.4)  # thumbnail endpoint is rate limited per minute
    return url


def compare(names: list[str], out_dir: Path) -> dict:
    from PIL import Image, ImageChops, ImageDraw, ImageStat

    renders = [kind for kind in ("powerpoint", "gslides", "libreoffice") if (out_dir / kind).exists()]
    compare_dir = out_dir / "compare"
    compare_dir.mkdir(parents=True, exist_ok=True)
    scores: dict[str, dict[str, float]] = {}
    for name in names:
        truth = Image.open(out_dir / "truth" / f"{name}.png").convert("RGB")
        panels = [("truth (UI)", truth)]
        scores[name] = {}
        for kind in renders:
            path = out_dir / kind / f"{name}.png"
            if not path.exists():
                continue
            rendered = Image.open(path).convert("RGB").resize(truth.size)
            difference = ImageChops.difference(truth, rendered).convert("L")
            scores[name][kind] = round(sum(ImageStat.Stat(difference).mean), 2)
            panels.append((kind, rendered))
        sheet = Image.new("RGB", (SLIDE_WIDTH_PX * len(panels), SLIDE_HEIGHT_PX + 28), "white")
        draw = ImageDraw.Draw(sheet)
        for index, (label, image) in enumerate(panels):
            sheet.paste(image, (index * SLIDE_WIDTH_PX, 28))
            draw.text((index * SLIDE_WIDTH_PX + 8, 8), f"{name} — {label}", fill="red")
        sheet.save(compare_dir / f"{name}.png")
    (out_dir / "scores.json").write_text(json.dumps(scores, indent=2), encoding="utf-8")
    return scores


def write_harness_record(out_dir: Path, fixture_dir: Path, slides: int) -> None:
    """``out_dir/harness.json``: the fixture the run read, its slide count and its PDF raster."""
    record = {"fixture": str(fixture_dir), "slides": slides, "pdfRaster": PDF_RASTER}
    (out_dir / HARNESS_RECORD).write_text(json.dumps(record, indent=2), encoding="utf-8")


# The apps in summary.md's columns, in compare's order, and what each is called there.
RENDERER_LABELS = {
    "powerpoint": "PowerPoint",
    "gslides": "Google Slides",
    "libreoffice": "LibreOffice",
}
# The apps scored from their PDF as rasterise_pdf draws it: what a baseline on
# another raster cannot be compared in.
PDF_RENDERERS = ("powerpoint", "libreoffice")
# The decks a run writes, in the order summary.md names them.
TARGETS = ("pptx", "gslides")
# A score this much above its baseline's is a slide gone worse (the Task 14
# Phase B rule); summary.md lists every one.
REGRESSION_THRESHOLD = 0.05
# The lost words summary.md shows of one slide and deck before it counts the rest.
LOST_WORDS_SHOWN = 8


def _read_json(path: Path, missing: object) -> object:
    """The JSON in ``path``, or ``missing`` when there is no such file."""
    if not path.is_file():
        return missing
    return json.loads(path.read_text(encoding="utf-8"))


def _deck_file(out_dir: Path, stem: str, target: str) -> Path:
    """The ``stem`` file of the ``target`` deck, as summaries.json or summaries-gslides.json."""
    return out_dir / f"{stem}{_target_suffix(target)}.json"


def _cell(text: str) -> str:
    """``text`` as one markdown table cell: a pipe in it divides no cells."""
    return text.replace("|", "\\|")


def _lost_words(words: list[str]) -> str:
    if not words:
        return "none"
    shown = " ".join(words[:LOST_WORDS_SHOWN])
    more = len(words) - LOST_WORDS_SHOWN
    return f"{shown} (+{more} more)" if more > 0 else shown


def _score_change(baseline: float | None, now: float | None) -> str:
    if now is None:
        return "—"
    if baseline is None:
        return f"{now:.2f}"
    return f"{baseline:.2f} → {now:.2f}"


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


# A slide's summary in one deck (summaries.json), or None for a slide the export failed.
def _model_drops(summary: dict | None) -> str:
    return "export failed" if summary is None else str(summary.get("modelDrops") or 0)


def _captures(summary: dict | None) -> str:
    """Captures taken / failed: the targets named, less those whose picture failed."""
    if summary is None:
        return "export failed"
    failed = summary.get("captureFailures") or 0
    return f"{(summary.get('captures') or 0) - failed} / {failed}"


def write_summary(out_dir: Path, names: list[str], baseline_dir: Path | None = None) -> Path:
    """``out_dir/summary.md``: one table row per slide, from the files the run wrote.

    Each row holds the slide's score in each app the run rendered in
    (scores.json), as ``baseline → now`` when ``baseline_dir`` (an earlier
    run's --out) scored it too; the words each deck loses (text_loss.json,
    text_loss-gslides.json); and each deck's MODEL DROPS and captures taken and
    failed (summaries.json, summaries-gslides.json), or "export failed" for a
    slide the deck lacks. A mean row follows, over the slides each column
    scores (both runs' means over the same slides), and then every slide worse
    than its baseline by more than REGRESSION_THRESHOLD. A baseline whose
    harness.json does not record this run's PDF raster (one from before it,
    which has none) rasterised its PDFs another way, so the apps scored from
    them (PDF_RENDERERS) are not compared with it: their rows and mean are this
    run's alone, and no rise of theirs is listed; the summary says so. A file
    the run did not write is taken as empty: a deck it did not export has no
    column.
    """
    scores = _read_json(out_dir / "scores.json", {})
    record = _read_json(out_dir / HARNESS_RECORD, {})
    renderers = [
        kind for kind in RENDERER_LABELS if any(kind in scores.get(name, {}) for name in names)
    ]
    targets = [target for target in TARGETS if _deck_file(out_dir, "summaries", target).is_file()]
    summaries = {
        target: _read_json(_deck_file(out_dir, "summaries", target), []) for target in targets
    }
    losses = {
        target: _read_json(_deck_file(out_dir, "text_loss", target), {}) for target in targets
    }
    baseline_scores = _read_json(baseline_dir / "scores.json", {}) if baseline_dir else {}
    baseline_record = _read_json(baseline_dir / HARNESS_RECORD, {}) if baseline_dir else {}
    baseline_raster = baseline_record.get("pdfRaster")
    raster_differs = baseline_dir is not None and baseline_raster != PDF_RASTER

    def compared(kind: str) -> bool:
        """Whether this app's scores are set against the baseline's."""
        return baseline_dir is not None and not (raster_differs and kind in PDF_RENDERERS)

    def label(kind: str) -> str:
        if baseline_dir is not None and not compared(kind):
            return f"{RENDERER_LABELS[kind]} (not compared: raster differs)"
        return RENDERER_LABELS[kind]

    decks = " / ".join(targets)
    header = [
        "Slide",
        *(label(kind) for kind in renderers),
        f"Text loss ({decks})",
        f"MODEL DROPS ({decks})",
        f"Captures taken / failed ({'; '.join(targets)})",
    ]
    lines = [
        "# Export fidelity summary",
        "",
        f"Fixture: `{record.get('fixture', '?')}`, {len(names)} slides. "
        f"Baseline: {f'`{baseline_dir}`' if baseline_dir else 'none'}.",
        "",
        "A score is the mean per-pixel difference from the UI's own rendering: 0 is identical, "
        f"lower is closer. PowerPoint's PDF is rasterised as {PDF_RASTER}; Google Slides is its "
        "LARGE thumbnail, resized to the slide's size.",
    ]
    if raster_differs:
        lines += [
            "",
            f"The baseline rasterised its PowerPoint PDFs another way "
            f"({baseline_raster or 'before harness.json recorded it'}), and its LibreOffice "
            "ones with them, so neither app's scores are compared with these.",
        ]
    lines += ["", "| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    worse = []
    means: dict[str, tuple[list[float], list[float]]] = {kind: ([], []) for kind in renderers}
    for index, name in enumerate(names):
        row = [_cell(name)]
        for kind in renderers:
            now = scores.get(name, {}).get(kind)
            before = baseline_scores.get(name, {}).get(kind) if compared(kind) else None
            row.append(_score_change(before, now))
            if now is None:
                continue
            if not compared(kind):
                means[kind][1].append(now)
            elif before is not None:
                means[kind][0].append(before)
                means[kind][1].append(now)
                if now - before > REGRESSION_THRESHOLD:
                    worse.append(f"{name} ({RENDERER_LABELS[kind]} +{now - before:.2f})")
        deck_summaries = [
            summaries[target][index] if index < len(summaries[target]) else None
            for target in targets
        ]
        lost = [_lost_words(losses[target].get(name, [])) for target in targets]
        row.append(_cell(" / ".join(lost)))
        row.append(" / ".join(_model_drops(summary) for summary in deck_summaries))
        row.append("; ".join(_captures(summary) for summary in deck_summaries))
        lines.append("| " + " | ".join(row) + " |")
    mean_row = ["**mean**"]
    for kind in renderers:
        before, now = means[kind]
        change = _score_change(_mean(before) if compared(kind) else None, _mean(now))
        mean_row.append(f"**{change}**" if now else change)
    mean_row += [""] * (len(header) - len(mean_row))
    lines.append("| " + " | ".join(mean_row) + " |")
    if baseline_dir is not None:
        worse_text = ", ".join(worse) or "none"
        lines += ["", f"Worse than the baseline by more than {REGRESSION_THRESHOLD}: {worse_text}."]
    path = out_dir / "summary.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("fixture_dir", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--powerpoint", action="store_true", help="render the .pptx with Microsoft PowerPoint (macOS)")
    parser.add_argument("--lo", action="store_true", help="render the .pptx with LibreOffice (smoke check only)")
    parser.add_argument("--gslides", action="store_true", help="convert through Google Drive")
    parser.add_argument("--only", nargs="*", help="slide name prefixes to include")
    parser.add_argument(
        "--pin-fonts",
        action="store_true",
        help="load the deck's Google Fonts from the committed files, so runs compare like for like",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        help="an earlier run's --out, whose scores summary.md sets this run's against",
    )
    args = parser.parse_args()

    deck, slides = load_fixture_deck(args.fixture_dir, pin_fonts=args.pin_fonts)
    if args.only:
        slides = [s for s in slides if any(s[0].startswith(prefix) for prefix in args.only)]
    args.out.mkdir(parents=True, exist_ok=True)
    names = [name for name, _ in slides]
    write_harness_record(args.out, args.fixture_dir, len(names))
    documents = build_documents(deck, slides, args.out)
    render_truth(documents, args.out)
    pptx_path = export_pptx(deck, documents, args.out)
    # Each slide's hidden text, from its summary; none for a slide without one.
    hidden_text = [(summary or {}).get("hiddenText", "") for summary in recorded_summaries(args.out)]
    lost = check_text_loss(pptx_path, names, args.out, hidden_text=hidden_text)
    print("Text missing from the export:", json.dumps(lost, indent=2, ensure_ascii=False) if lost else "none")
    if args.powerpoint:
        render_with_powerpoint(pptx_path, names, args.out)
    if args.lo:
        render_with_libreoffice(pptx_path, names, args.out)
    if args.gslides:
        # The Google Slides export writes its deck for Google (target "gslides"), so the
        # conversion here does too.
        gslides_path = export_pptx(deck, documents, args.out, target="gslides")
        gslides_hidden = [
            (summary or {}).get("hiddenText", "")
            for summary in recorded_summaries(args.out, target="gslides")
        ]
        gslides_lost = check_text_loss(
            gslides_path, names, args.out, hidden_text=gslides_hidden, target="gslides"
        )
        print(
            "Text missing from the Google Slides export:",
            json.dumps(gslides_lost, indent=2, ensure_ascii=False) if gslides_lost else "none",
        )
        print("Google Slides:", render_with_google_slides(gslides_path, names, args.out))
    scores = compare(names, args.out)
    print(json.dumps(scores, indent=2))
    print("Summary:", write_summary(args.out, names, args.baseline))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
