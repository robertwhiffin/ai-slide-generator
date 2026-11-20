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
   (``--powerpoint``), and/or converts a deck written for Google Slides
   (``target="gslides"``, ``export-gslides.pptx``) through Drive and downloads
   the slide thumbnails (``--gslides``): the deck and the conversion the
   Google Slides export uses;
5. writes one side-by-side comparison PNG per slide plus a ``scores.json``
   holding a per-slide visual difference score (lower is closer).

Usage (from the repo root)::

    uv run --with pymupdf --with pillow python scripts/export_fidelity/run.py \
        tests/fixtures/export_fidelity --out /tmp/fidelity --lo --gslides

The Google Slides path uses gcloud application-default credentials and the
quota project in ``GOOGLE_QUOTA_PROJECT``. Converted presentations are left in
Drive (named ``tellr-export-fidelity <timestamp>``) so they can be opened
and inspected; delete them by hand when finished.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import io
import json
import os
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


def load_fixture_deck(fixture_dir: Path) -> tuple[dict, list[tuple[str, str]]]:
    deck = json.loads((fixture_dir / "deck.json").read_text(encoding="utf-8"))
    deck["css"] = (fixture_dir / "deck.css").read_text(encoding="utf-8")
    slides = [
        (path.stem, path.read_text(encoding="utf-8"))
        for path in sorted((fixture_dir / "slides").glob("*.html"))
    ]
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


def render_with_libreoffice(pptx_path: Path, names: list[str], out_dir: Path) -> None:
    import fitz  # pymupdf

    soffice = shutil.which("soffice") or "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    lo_dir = out_dir / "libreoffice"
    lo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(lo_dir), str(pptx_path)],
        check=True,
        capture_output=True,
    )
    pdf = fitz.open(lo_dir / (pptx_path.stem + ".pdf"))
    for index, page in enumerate(pdf):
        zoom = SLIDE_WIDTH_PX / page.rect.width
        page.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).save(str(lo_dir / f"{names[index]}.png"))


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
    is the copy it staged. The PDF is copied into ``out_dir/powerpoint`` and
    both staged files are deleted from the container. Returns the copied PDF.
    """
    import fitz  # pymupdf

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
    pdf = fitz.open(exported_pdf)
    for index, page in enumerate(pdf):
        zoom = SLIDE_WIDTH_PX / page.rect.width
        page.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).save(str(powerpoint_dir / f"{names[index]}.png"))
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


def _normalise_text(text: str) -> str:
    """``text`` as the text-loss check compares it, the way text_check.cjs normalises.

    Compatibility forms are folded (NFKC: a literal "¹" is "1", a ligature its
    letters, a fullwidth form its ASCII), then white space and default-ignorable
    code points are removed, then the rest is lower-cased.
    """
    folded = unicodedata.normalize("NFKC", text).translate(_DEFAULT_IGNORABLE)
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
    pptx_path: Path, names: list[str], out_dir: Path, hidden_text: list[str] | None = None
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
    (out_dir / "text_loss.json").write_text(json.dumps(missing, indent=2, ensure_ascii=False), encoding="utf-8")
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("fixture_dir", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--powerpoint", action="store_true", help="render the .pptx with Microsoft PowerPoint (macOS)")
    parser.add_argument("--lo", action="store_true", help="render the .pptx with LibreOffice (smoke check only)")
    parser.add_argument("--gslides", action="store_true", help="convert through Google Drive")
    parser.add_argument("--only", nargs="*", help="slide name prefixes to include")
    args = parser.parse_args()

    deck, slides = load_fixture_deck(args.fixture_dir)
    if args.only:
        slides = [s for s in slides if any(s[0].startswith(prefix) for prefix in args.only)]
    args.out.mkdir(parents=True, exist_ok=True)
    names = [name for name, _ in slides]
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
        print("Google Slides:", render_with_google_slides(gslides_path, names, args.out))
    scores = compare(names, args.out)
    print(json.dumps(scores, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
