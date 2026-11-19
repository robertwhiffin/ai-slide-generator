"""Script lines: where PowerPoint and Google Slides draw a line holding a superscript or subscript.

The snapshot engine writes a script run's size, and the lines around it, for the
app the deck is written for (``build_pptx_huashu(..., target=...)``; see
``scripts/export_fidelity/CALIBRATION.md``, A2 and A4). This script measures
what each app makes of each deck, against the browser:

1. builds the probe slides below with the production ``build_slide_html`` and
   the corpus ``deck.css`` (DM Sans), as the harness ``run.py`` does;
2. reads the browser's baselines: each line's lead word's glyph top (its
   span's rect) plus its face's ascent, and its left edge, with
   ``tests/fixtures/export_snapshot/measure.cjs``, the export tests' own
   measurer;
3. exports the slides through the snapshot engine for each target, ``pptx``
   and ``gslides``;
4. ``--powerpoint``: renders the deck written for PowerPoint in PowerPoint
   for Mac (``run.render_with_powerpoint``) and reads each lead word's
   baseline and left edge, and each script glyph's size, from the text of
   the PDF PowerPoint saves; ``--gslides``: converts both decks through Drive
   (``run.render_with_google_slides``), exports each conversion as PDF and
   reads it the same way, then deletes the presentation by its id;
5. prints, per deck, app and slide, each line's baseline offset (app minus
   browser; + is lower), line by line, the first lead word's left-edge offset
   (+ is right) and the script glyph's drawn size over the browser's;
6. with ``--gslides``, ``GOOGLE_LINE_GROWTH_PER_PX``'s points (A4): for each
   one-line superscript slide, how far Google lowers the line written for
   PowerPoint (its script run at the browser's size over
   ``SUPERSCRIPT_SIZE_FACTOR``) below the one written for Google (capped at its
   line's size), per px the first's script run is written larger.

Usage (from the repo root)::

    uv run --with pymupdf python scripts/export_fidelity/measure_script_lines.py \\
        --out /tmp/script-lines --powerpoint --gslides

``--sidecar label=path`` (repeatable) exports with the sidecar copy at
``path`` instead of the repo's, to compare engine states; ``--only`` measures
the named slides. The tables are also written to ``<out>/script_lines.md`` and
everything measured to ``<out>/script_lines.json``.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services import pptx_from_html_huashu  # noqa: E402
from tests.fixtures.export_snapshot_support import (  # noqa: E402
    browser_ascent,
    browser_each_rect,
    browser_style,
    delete_drive_file,
    drive_file_exists,
)

CORPUS_DIR = REPO_ROOT / "tests" / "fixtures" / "export_fidelity"
DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
PRESENTATION_URL = re.compile(r"https://docs\.google\.com/presentation/d/([^/\s]+)/edit")
SLIDE_WIDTH_PX = 1280
PT_PER_PX = 0.75
HUNDREDTHS = 100
TARGETS = ("pptx", "gslides")
FAMILY = "DM Sans"
WEIGHT = 400


def _paragraph(size_px: int, line_height: str | None, lines: str, extra: str = "") -> str:
    spacing = f" line-height:{line_height};" if line_height else ""
    return (
        '<div class="slide"><p id="target" style="position:absolute; left:100px; top:150px; '
        f"margin:0; font-size:{size_px}px;{spacing} white-space:nowrap; font-family:'{FAMILY}';"
        f'{extra}">{lines}</p></div>'
    )


FIRST = '<span id="first">Alpha</span>'
SECOND = '<span id="second">Gamma</span>'
SECOND_24 = '<span id="second" style="font-size:24px">Gamma</span>'
ALIGNED = " width:400px;"


@dataclass(frozen=True)
class ProbeSlide:
    """One probe slide: its body, and what is read of it.

    ``words`` are the lead words of its lines, each (text, selector, size in
    px); ``script`` the text of its script run, read by the selector
    ``#target sup`` or ``#target sub`` (None without one).
    """

    body: str
    words: tuple[tuple[str, str, float], ...]
    script: tuple[str, str] | None = None


def _one_line(size_px: int, lines: str, lead: str, script: tuple[str, str], extra: str = ""):
    return ProbeSlide(_paragraph(size_px, None, lines, extra), ((lead, "#first", size_px),), script)


def _two_lines(line_height: str, lines: str, second_px: float = 20, script=("1", "sup")):
    return ProbeSlide(
        _paragraph(20, line_height, lines),
        (("Alpha", "#first", 20), ("Gamma", "#second", second_px)),
        script,
    )


SUP = ("1", "sup")
SUB = ("2", "sub")
PLAIN_PX = 16
PLAIN_WORDS = (
    ("Alpha", None, " revenue grew"),
    ("Gamma", 20, " margin held"),
    ("Delta", None, " costs fell"),
    ("Omega", None, " cash rose"),
)


def _plain(line_height: str, words: tuple[tuple[str, int | None, str], ...]) -> ProbeSlide:
    """A 16 px paragraph whose line n leads with #l<n>, at its own size where one is given."""
    lines = []
    for number, (word, size_px, rest) in enumerate(words, start=1):
        style = f' style="font-size:{size_px}px"' if size_px else ""
        lines.append(f'<span id="l{number}"{style}>{word}</span>{rest}')
    return ProbeSlide(
        _paragraph(PLAIN_PX, line_height, "<br>".join(lines)),
        tuple(
            (word, f"#l{number}", size_px or PLAIN_PX)
            for number, (word, size_px, _) in enumerate(words, start=1)
        ),
    )
ENDS_LINE_1 = f"{FIRST} revenue grew<sup>1</sup><br>{SECOND} margin held"
ENDS_LINE_2 = f"{FIRST} revenue grew<br>{SECOND} margin held<sup>1</sup>"
MID_LINE_2 = f"{FIRST} revenue grew<br>{SECOND} margin<sup>1</sup> held"
SMALL_SECOND = '<small id="second">Gamma'
REVENUE = '<span id="first">Revenue</span>'
REVENUE_UP = f"{REVENUE} grew 12%<sup>1</sup>"
# Each probe slide, by name. The first nine are the task-11 round-3 re-review's
# PowerPoint cases (findings r4, Important 2), the next three ruling R11g's.
SLIDES: dict[str, ProbeSlide] = {
    "sup-mid-20": _one_line(20, f"{REVENUE}<sup>1</sup> grew", "Revenue", SUP),
    "sup-end-20": _one_line(20, REVENUE_UP, "Revenue", SUP),
    "sup-end-40": _one_line(40, REVENUE_UP, "Revenue", SUP),
    "sub-end-20": _one_line(
        20, '<span id="first">Emissions</span> of CO<sub>2</sub>', "Emissions", SUB
    ),
    "29px-sup-ends-line-1": _two_lines("29px", ENDS_LINE_1),
    "22px-sup-ends-line-1": _two_lines("22px", ENDS_LINE_1),
    "22px-sup-ends-line-2": _two_lines("22px", ENDS_LINE_2),
    "29px-sup-ends-line-2": _two_lines("29px", ENDS_LINE_2),
    "29px-sup-mid-line-2": _two_lines("29px", MID_LINE_2),
    "sup-mid-40": _one_line(40, f"{REVENUE}<sup>1</sup> grew", "Revenue", SUP),
    "sub-mid-20": _one_line(20, '<span id="first">CO</span><sub>2</sub> output fell', "CO", SUB),
    "22px-sup-mid-line-2": _two_lines("22px", MID_LINE_2),
    # A second line that opens a paragraph of its own in the slide model.
    "29px-24px-run-and-sup-on-line-2": _two_lines(
        "29px", f"{FIRST} revenue grew<br>{SECOND_24} margin<sup>1</sup> held", 24
    ),
    "29px-24px-run-on-line-2": _two_lines(
        "29px", f"{FIRST} revenue grew<br>{SECOND_24} margin held", 24, None
    ),
    "1.45-24px-run-on-line-2": _two_lines(
        "1.45", f"{FIRST} revenue grew<br>{SECOND_24} margin held", 24, None
    ),
    "29px-24px-run-on-line-1": ProbeSlide(
        _paragraph(
            20, "29px", '<span id="first" style="font-size:24px">Alpha</span> revenue grew<br>'
            f"{SECOND} margin held"
        ),
        (("Alpha", "#first", 24), ("Gamma", "#second", 20)),
    ),
    "29px-small-line-2": ProbeSlide(
        _paragraph(20, "29px", f"{FIRST} revenue grew<br>{SMALL_SECOND} margin held</small>"),
        (("Alpha", "#first", 20), ("Gamma", "#second", 50 / 3)),
    ),
    "29px-plain": _two_lines("29px", f"{FIRST} revenue grew<br>{SECOND} margin held", 20, None),
    # A corpus-style title, 900 px wide, whose footnote marker ends its second line.
    "42px-title-sup-ends-line-2": ProbeSlide(
        '<div class="slide"><h2 id="target" style="position:absolute; left:88px; top:80px; '
        f"margin:0; width:900px; font-family:'{FAMILY}'; font-size:42px; font-weight:{WEIGHT}; "
        'line-height:1.08;"><span id="first">FY2024</span> delivered the largest margin step-up '
        'in five <span id="second">years</span><sup>1</sup></h2></div>',
        (("FY2024", "#first", 42), ("years", "#second", 42)),
        SUP,
    ),
    # A line-ending superscript in a right-aligned and a centred line.
    "sup-end-right": _one_line(20, REVENUE_UP, "Revenue", SUP, ALIGNED + " text-align:right;"),
    "sup-end-center": _one_line(20, REVENUE_UP, "Revenue", SUP, ALIGNED + " text-align:center;"),
    # A later paragraph's first line holding a superscript (ruling R11j).
    "1.45-24px-run-and-sup-on-line-2": _two_lines(
        "1.45", f"{FIRST} revenue grew<br>{SECOND_24} margin<sup>1</sup> held", 24
    ),
    "29px-24px-line-1-sup-on-line-2": ProbeSlide(
        _paragraph(
            20, "29px", '<span id="first" style="font-size:24px">Alpha</span> revenue grew<br>'
            f"{SECOND} margin<sup>1</sup> held"
        ),
        (("Alpha", "#first", 24), ("Gamma", "#second", 20)),
        SUP,
    ),
    # Same-size relative nudges (ruling R11h): one word among plain ones, a
    # whole line moved up, and one moved down.
    "nudge-one-word": _one_line(
        20, f'{REVENUE} <span style="position:relative; top:-3px">&#9650;</span> 12% up',
        "Revenue", None,
    ),
    "nudge-whole-line-up": _one_line(
        20, f'<span style="position:relative; top:-3px">{REVENUE} &#9650; 12% up</span>',
        "Revenue", None,
    ),
    "nudge-whole-line-down": _one_line(
        20, f'<span style="position:relative; top:4px">{REVENUE} grew 12%</span>', "Revenue", None
    ),
    # Paragraphs with no script run whose later lines the browser grows.
    "plain-1.4-28px-line-2": _plain(
        "1.4", (("Alpha", None, " body text"), ("Gamma", 28, " big figure"),
                ("Delta", None, " body again")),
    ),
    "plain-1.6-20px-line-2": _plain("1.6", PLAIN_WORDS),
    "plain-26px-20px-line-2": _plain("26px", PLAIN_WORDS),
}
ONE_LINE_SUPERSCRIPTS = ("sup-mid-20", "sup-mid-40")


def load_harness():
    """``scripts/export_fidelity/run.py``, imported by path (it is a script, not a package)."""
    spec = importlib.util.spec_from_file_location("export_fidelity_harness", SCRIPT_DIR / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def browser_truth(document: str, slide: ProbeSlide) -> dict:
    """Each lead word's baseline and left edge, and the script run's size, in the browser (px)."""
    truth: dict = {"words": {}}
    for word, selector, size_px in slide.words:
        rect = browser_each_rect(document, selector)[0]
        ascent = browser_ascent(document, FAMILY, WEIGHT, size_px)
        truth["words"][word] = {"baseline": rect["y"] + ascent, "left": rect["x"]}
    if slide.script:
        size = browser_style(document, f"#target {slide.script[1]}")["fontSize"]
        truth["scriptPx"] = float(size.removesuffix("px"))
    return truth


def pdf_reading(pdf_path: Path, page_index: int, slide: ProbeSlide) -> dict:
    """What the app drew on one page: each lead word's baseline and left edge, the script's size."""
    import fitz  # pymupdf

    page = fitz.open(pdf_path)[page_index]
    scale = SLIDE_WIDTH_PX / page.rect.width
    reading: dict = {"words": {}}
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                characters = [character for character in span["chars"] if character["c"].strip()]
                text = "".join(character["c"] for character in characters)
                for word, _, _ in slide.words:
                    if word not in reading["words"] and text.startswith(word):
                        reading["words"][word] = {
                            "baseline": span["origin"][1] * scale,
                            "left": characters[0]["bbox"][0] * scale,
                        }
                if slide.script and "scriptPx" not in reading and text == slide.script[0]:
                    reading["scriptPx"] = span["size"] * scale
    return reading


def script_sizes_px(pptx: bytes, names: list[str]) -> dict[str, float]:
    """Each slide's script run's written size (the a:rPr with a baseline), in px."""
    archive = zipfile.ZipFile(io.BytesIO(pptx))
    sizes = {}
    for index, name in enumerate(names):
        xml = archive.read(f"ppt/slides/slide{index + 1}.xml").decode("utf-8")
        found = re.findall(r'<a:rPr lang="[^"]*" sz="(\d+)" baseline="-?\d+"', xml)
        if found:
            sizes[name] = int(found[0]) / HUNDREDTHS / PT_PER_PX
    return sizes


@contextlib.contextmanager
def sidecar(path: Path | None):
    """Exports inside run with the sidecar copy at ``path`` (the repo's when None)."""
    saved = (pptx_from_html_huashu.SIDECAR_DIR, pptx_from_html_huashu.SIDECAR_SCRIPT)
    if path is not None:
        pptx_from_html_huashu.SIDECAR_DIR = path
        pptx_from_html_huashu.SIDECAR_SCRIPT = path / "emit_deck.mjs"
    try:
        yield
    finally:
        pptx_from_html_huashu.SIDECAR_DIR, pptx_from_html_huashu.SIDECAR_SCRIPT = saved


def google_pdf(harness, pptx_path: Path, names: list[str], out_dir: Path) -> Path:
    """Drive's PDF of the Google Slides conversion of ``pptx_path``; the presentation is deleted."""
    out_dir.mkdir(parents=True, exist_ok=True)
    recorded = out_dir / "gslides_url.txt"
    try:
        url = harness.render_with_google_slides(pptx_path, names, out_dir)
        presentation_id = PRESENTATION_URL.search(url).group(1)
        pdf_path = out_dir / f"{pptx_path.stem}.pdf"
        pdf_path.write_bytes(
            harness._google_request(
                f"{DRIVE_FILES_URL}/{presentation_id}/export?mimeType=application/pdf",
                harness._google_token(),
            )
        )
        return pdf_path
    finally:
        if recorded.exists():
            presentation_id = PRESENTATION_URL.search(recorded.read_text(encoding="utf-8")).group(1)
            delete_drive_file(presentation_id)
            print(
                f"Google Slides: deleted {presentation_id}; still in Drive: "
                f"{drive_file_exists(presentation_id)}"
            )


def _offset(drawn: dict, truth: dict, word: str, key: str) -> float | None:
    if word not in drawn["words"]:
        return None
    return drawn["words"][word][key] - truth["words"][word][key]


def _cell(value: float | None, digits: int = 2, signed: bool = True) -> str:
    if value is None:
        return "-"
    return f"{value:+.{digits}f}" if signed else f"{value:.{digits}f}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--powerpoint", action="store_true", help="render in PowerPoint for Mac")
    parser.add_argument("--gslides", action="store_true", help="convert through Google Drive")
    parser.add_argument(
        "--sidecar", action="append", default=[], metavar="LABEL=PATH",
        help="export with the sidecar copy at PATH as well, labelled LABEL",
    )
    parser.add_argument("--only", nargs="*", default=None, help="measure these slides alone")
    args = parser.parse_args()
    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    harness = load_harness()

    names = [name for name in SLIDES if args.only is None or name in args.only]
    deck = json.loads((CORPUS_DIR / "deck.json").read_text(encoding="utf-8"))
    deck["css"] = (CORPUS_DIR / "deck.css").read_text(encoding="utf-8")
    deck["scripts"] = ""
    deck["external_scripts"] = []
    bodies = [(name, SLIDES[name].body) for name in names]
    documents = harness.build_documents(deck, bodies, out_dir)
    truth = {
        name: browser_truth(document.read_text(encoding="utf-8"), SLIDES[name])
        for name, document in zip(names, documents)
    }

    engines = [("repo", None)] + [
        (label, Path(path)) for label, path in (value.split("=", 1) for value in args.sidecar)
    ]
    results: dict = {"truth": truth, "decks": {}}
    rows = []
    for label, path in engines:
        for target in TARGETS:
            deck_dir = out_dir / f"{label}-{target}"
            deck_dir.mkdir(parents=True, exist_ok=True)
            with sidecar(path):
                pptx_path = harness.export_pptx(
                    deck, documents, deck_dir, engine="snapshot", target=target
                )
            key = f"{label} {target}"
            results["decks"][key] = {"scriptPx": script_sizes_px(pptx_path.read_bytes(), names)}
            apps = []
            # PowerPoint opens the deck written for it; Google converts both,
            # the one written for PowerPoint for A4's points.
            if args.powerpoint and target == "pptx":
                pdf_path = harness.render_with_powerpoint(pptx_path, names, deck_dir)
                apps.append(("PowerPoint", pdf_path))
            if args.gslides:
                apps.append(("Google", google_pdf(harness, pptx_path, names, deck_dir / "google")))
            for app, pdf_path in apps:
                for index, name in enumerate(names):
                    slide = SLIDES[name]
                    drawn = pdf_reading(pdf_path, index, slide)
                    results["decks"][key].setdefault(app, {})[name] = drawn
                    words = [word for word, _, _ in slide.words]
                    offsets = [_offset(drawn, truth[name], word, "baseline") for word in words]
                    script_ratio = (
                        drawn["scriptPx"] / truth[name]["scriptPx"]
                        if slide.script and "scriptPx" in drawn
                        else None
                    )
                    rows.append(
                        f"| {label} | {target} | {app} | {name} | "
                        f"{' / '.join(_cell(offset) for offset in offsets)} | "
                        f"{_cell(_offset(drawn, truth[name], words[0], 'left'))} | "
                        f"{_cell(script_ratio, 3, signed=False)} |"
                    )

    lines = [
        "| engine | target | app | slide | baseline per line | lead word left | "
        "script glyph / browser |",
        "|---|---|---|---|---|---|---|",
        *rows,
    ]
    if args.gslides:
        lines += [
            "",
            "| engine | slide | excess written (px) | Google lowers the line (px) | per px |",
        ]
        lines.append("|---|---|---|---|---|")
        for label, _ in engines:
            powerpoint_deck = results["decks"][f"{label} pptx"]
            google_deck = results["decks"][f"{label} gslides"]
            for name in ONE_LINE_SUPERSCRIPTS:
                if name not in names:
                    continue
                excess = powerpoint_deck["scriptPx"][name] - google_deck["scriptPx"][name]
                word = SLIDES[name].words[0][0]
                lowered = (
                    powerpoint_deck["Google"][name]["words"][word]["baseline"]
                    - google_deck["Google"][name]["words"][word]["baseline"]
                )
                lines.append(
                    f"| {label} | {name} | {excess:.2f} | {lowered:.2f} | {lowered / excess:.3f} |"
                )
    text = "\n".join(lines) + "\n"
    (out_dir / "script_lines.md").write_text(text, encoding="utf-8")
    (out_dir / "script_lines.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
