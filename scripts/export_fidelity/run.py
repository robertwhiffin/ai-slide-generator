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


def export_pptx(deck: dict, documents: list[Path], out_dir: Path) -> Path:
    os.environ["HUASHU_PIPELINE_ENABLED"] = "1"
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

    renders = [kind for kind in ("gslides", "libreoffice") if (out_dir / kind).exists()]
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
    parser.add_argument("--lo", action="store_true", help="render the .pptx with LibreOffice")
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
    if args.lo:
        render_with_libreoffice(pptx_path, names, args.out)
    if args.gslides:
        print("Google Slides:", render_with_google_slides(pptx_path, names, args.out))
    scores = compare(names, args.out)
    print(json.dumps(scores, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
