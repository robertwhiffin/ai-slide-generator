"""Export fidelity harness: what the user sees vs what the export produces.

For a fixture deck (``deck.css`` + ``deck.json`` + ``slides/*.html``) this:

1. builds every slide's export document with the production
   ``build_slide_html`` (so the harness exercises exactly what the export
   routes feed the sidecar);
2. renders the ground truth: a 1280x720 Chromium screenshot of that document;
3. runs the production huashu export (``build_pptx_huashu``) to a .pptx;
4. renders the .pptx with LibreOffice (``--lo``) and/or converts it to
   Google Slides through Drive and downloads the slide thumbnails
   (``--gslides``), which is the same conversion the Google Slides export uses;
5. writes one side-by-side comparison PNG per slide plus a ``scores.json``
   holding a per-slide visual difference score (lower is closer).

Usage (from the repo root)::

    uv run --with pymupdf --with pillow python scripts/export_fidelity/run.py \
        tests/fixtures/export_fidelity --out /tmp/fidelity --lo --gslides

``--engine snapshot`` exports with the snapshot engine (``render_slide.cjs``)
instead of the legacy converter, through ``TELLR_EXPORT_ENGINE``.

The Google Slides path uses gcloud application-default credentials and the
quota project in ``GOOGLE_QUOTA_PROJECT``. Converted presentations are left in
Drive (named ``tellr-export-fidelity <timestamp>``) so they can be opened
and inspected; delete them by hand when finished.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

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


def export_pptx(deck: dict, documents: list[Path], out_dir: Path, engine: str = "legacy") -> Path:
    os.environ["HUASHU_PIPELINE_ENABLED"] = "1"
    # build_pptx_huashu reads the engine from the environment and sends it to the sidecar.
    os.environ["TELLR_EXPORT_ENGINE"] = engine
    slides_payload = [{"html": path.read_text(encoding="utf-8"), "notes": path.stem} for path in documents]
    pptx_bytes, failures = pptx_from_html_huashu.build_pptx_huashu(
        deck.get("title", "slides"), slides_payload, bypass_validation=True
    )
    (out_dir / "failures.json").write_text(json.dumps(failures, indent=2), encoding="utf-8")
    pptx_path = out_dir / "export.pptx"
    pptx_path.write_bytes(pptx_bytes)
    return pptx_path


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


def _normalise_text(text: str) -> str:
    return "".join(text.split()).lower()


def check_text_loss(pptx_path: Path, names: list[str], out_dir: Path) -> dict[str, list[str]]:
    """Words the browser renders that are absent from the exported slide.

    The reference is the browser's own rendered text (render_truth.cjs writes
    it), which no extraction code touches, so text the exporter drops shows up
    here. SVG and canvas text is excluded: it travels inside the picture.
    """
    from pptx import Presentation

    presentation = Presentation(str(pptx_path))
    slides = list(presentation.slides)
    missing: dict[str, list[str]] = {}
    for index, name in enumerate(names):
        reference = (out_dir / "truth" / f"{name}.txt").read_text(encoding="utf-8")
        exported = ""
        if index < len(slides):
            for shape in slides[index].shapes:
                if shape.has_text_frame:
                    exported += shape.text_frame.text
                if shape.has_table:
                    exported += "".join(cell.text for row in shape.table.rows for cell in row.cells)
        exported_normalised = _normalise_text(exported)
        lost = [word for word in reference.split() if _normalise_text(word) not in exported_normalised]
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
    url = f"https://docs.google.com/presentation/d/{presentation_id}/edit"
    (out_dir / "gslides_url.txt").write_text(url + "\n", encoding="utf-8")
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
    parser.add_argument(
        "--engine",
        choices=("legacy", "snapshot"),
        default="legacy",
        help="the sidecar's per-slide converter (sets TELLR_EXPORT_ENGINE)",
    )
    args = parser.parse_args()

    deck, slides = load_fixture_deck(args.fixture_dir)
    if args.only:
        slides = [s for s in slides if any(s[0].startswith(prefix) for prefix in args.only)]
    args.out.mkdir(parents=True, exist_ok=True)
    names = [name for name, _ in slides]
    documents = build_documents(deck, slides, args.out)
    render_truth(documents, args.out)
    pptx_path = export_pptx(deck, documents, args.out, engine=args.engine)
    lost = check_text_loss(pptx_path, names, args.out)
    print("Text missing from the export:", json.dumps(lost, indent=2, ensure_ascii=False) if lost else "none")
    if args.powerpoint:
        render_with_powerpoint(pptx_path, names, args.out)
    if args.lo:
        render_with_libreoffice(pptx_path, names, args.out)
    if args.gslides:
        print("Google Slides:", render_with_google_slides(pptx_path, names, args.out))
    scores = compare(names, args.out)
    print(json.dumps(scores, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
