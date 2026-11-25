"""Phase 5 — editable-export SVG rasterization: goldens + behavior.

pptxgenjs 3.12.0 running in Node writes every ``data:image/svg+xml`` image
with a hardcoded broken-image placeholder PNG (``IMG_BROKEN``) as the primary
``<a:blip>`` and the real SVG only in the ``<asvg:svgBlip>`` extension.
PowerPoint renders the extension (masking the bug); Google Drive PPTX→Slides
conversion, LibreOffice, and most thumbnailers render the placeholder.

SVG never reaches either Node sidecar as SVG data; it arrives as a PNG drawn
by the browser page that already rendered it:

* records path — ``rasterizeSvgImage`` inside the walker
  (``frontend/src/services/domWalker.ts``); the sidecar
  (``services/pptx-emit/emit.bundle.mjs``) is intentionally UNCHANGED.
* huashu path — the snapshot engine embeds only raster ``data:`` images as
  they are, and captures everything else the browser draws (an ``<img>`` with
  an SVG source, an SVG CSS background) as an element-isolated screenshot of
  its box at device scale 2 (``services/pptx-emit-huashu/capture.cjs``).

This module protects two invariants:

1. REGRESSION (golden manifests): for SVG-free decks each emitter's output
   is pinned structurally. Raw byte equality is impossible (pptx zips embed
   wall-clock timestamps), so the goldens record the sorted zip entry list
   plus a SHA256 per entry, with ``docProps/core.xml`` canonicalized by
   masking the ``dcterms`` created/modified values. The records golden was
   captured at d50b716; the huashu golden is the snapshot engine's.

   The huashu golden is pinned to the machine/Chrome build that captured it
   (the snapshot reads the page from a live Chrome), so there is one per
   platform (``HUASHU_PNG_GOLDENS``): macOS's, from Chrome, and Linux's, from
   Playwright's Chromium headless shell as the export engine job runs it
   (Chrome Headless Shell 147.0.7727.15, Playwright's chromium v1217, with the
   sidecar's setup.sh). They differ in ``ppt/slides/slide1.xml`` alone, the
   layout each browser read; the Linux one is the manifest the job's runs
   45495272109 and 45504855550 both exported, without the font bundle and with
   it. To re-capture the current platform's:
   ``TELLR_REGEN_EXPORT_GOLDENS=1 uv run --no-sync pytest
   tests/unit/test_export_svg_raster.py`` (regen runs report as skipped so
   they can never fake a pass).

2. NEW BEHAVIOR: an SVG-bearing deck exported through the huashu pipeline
   must contain no ``.svg`` media, no ``svgBlip`` references, no media blob
   matching the IMG_BROKEN placeholder, and real PNGs at 2x the layout box
   they were captured from. (The records-path equivalent lives in the
   frontend runner — ``frontend/tests/e2e/svg-raster-export.spec.ts`` —
   because the walker needs a real browser.)

Gating: records tests need ``node`` + the checked-in sidecar bundle; huashu
tests additionally need the extracted sidecar ``node_modules`` and a local
Chrome/Chromium (skipped otherwise, e.g. on CI).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import struct
import sys
import zipfile
from io import BytesIO
from pathlib import Path
from unittest import mock

import pytest

from src.services import pptx_from_html_huashu, pptx_from_records
from tests.fixtures.export_snapshot_support import build_pptx_guarded

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "export_svg_raster"
RECORDS_BUNDLE = REPO_ROOT / "services" / "pptx-emit" / "emit.bundle.mjs"

REGEN_ENV = "TELLR_REGEN_EXPORT_GOLDENS"
# The huashu PNG control deck's golden for each platform's browser (see the module's
# docstring): the export reads its layout from that browser.
HUASHU_PNG_GOLDENS = {
    "darwin": FIXTURE_DIR / "golden_huashu_png_manifest.json",
    "linux": FIXTURE_DIR / "golden_huashu_png_manifest_linux.json",
}

# SHA256 of pptxgenjs 3.12.0's hardcoded Node-side PNG fallback for SVG data
# URIs (the 1594-byte gray broken-image icon). Pinned so the tests below can
# prove emitted media is not the placeholder, and as a tripwire: if a
# pptxgenjs upgrade changes the constant, this fails loudly instead of the
# no-placeholder assertions silently passing against the wrong bytes.
IMG_BROKEN_SHA256 = "0db2447fffb75ae48f57c711c26783f619591d48b1713f997a7bc34626c95ff1"

# The device scale the snapshot engine captures at (render_slide.cjs
# DEVICE_SCALE_FACTOR): every captured picture is twice its CSS box.
CAPTURE_SCALE = 2

_DCTERMS_RE = re.compile(
    rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*(</dcterms:(?:created|modified)>)"
)

RECORDS_AVAILABLE = pptx_from_records.is_available()


def _huashu_available() -> bool:
    # conftest pins ENVIRONMENT=test, which closes the local-dev gate; the
    # explicit opt-in is how availability is probed (and how the tests run).
    with mock.patch.dict(os.environ, {"HUASHU_PIPELINE_ENABLED": "1"}):
        return pptx_from_html_huashu.is_available()


HUASHU_AVAILABLE = _huashu_available()

requires_records_sidecar = pytest.mark.skipif(
    not RECORDS_AVAILABLE,
    reason="requires node + services/pptx-emit/emit.bundle.mjs",
)
requires_huashu_sidecar = pytest.mark.skipif(
    not HUASHU_AVAILABLE,
    reason=(
        "requires node, services/pptx-emit-huashu/node_modules (run setup.sh) "
        "and a local Chrome/Chromium"
    ),
)


def _img_broken_bytes() -> bytes:
    bundle = RECORDS_BUNDLE.read_text(encoding="utf-8")
    match = re.search(r'IMG_BROKEN = "data:image/png;base64,([^"]+)"', bundle)
    assert match is not None, "IMG_BROKEN constant not found in emit.bundle.mjs"
    return base64.b64decode(match.group(1))


def _png_dimensions(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"not a PNG: {data[:12]!r}"
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def structural_manifest(pptx_bytes: bytes) -> dict:
    """Timestamp-canonical structural manifest of a pptx zip.

    Hashes the *uncompressed* content of every entry (zip-local mtimes and
    deflate framing never participate), masking only the dcterms timestamps
    in ``docProps/core.xml``. Everything else — slide XML, rels, content
    types, media bytes — must match exactly.
    """
    entry_sha256: dict[str, str] = {}
    with zipfile.ZipFile(BytesIO(pptx_bytes)) as zf:
        for name in sorted(zf.namelist()):
            data = zf.read(name)
            if name == "docProps/core.xml":
                data = _DCTERMS_RE.sub(rb"\1TIMESTAMP\2", data)
            entry_sha256[name] = hashlib.sha256(data).hexdigest()
    return {"entries": sorted(entry_sha256), "sha256": entry_sha256}


def _assert_matches_golden(manifest: dict, golden_path: Path) -> None:
    if os.environ.get(REGEN_ENV) == "1":
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        pytest.skip(f"regenerated golden {golden_path.name}")
    assert golden_path.exists(), (
        f"golden manifest missing: {golden_path} — capture it on a known-good "
        f"checkout with {REGEN_ENV}=1"
    )
    expected = json.loads(golden_path.read_text(encoding="utf-8"))
    assert manifest == expected, (
        "structural manifest drifted from the golden — the emitter changed "
        "output for an SVG-free deck"
    )


def _load_records_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _media_entries(zf: zipfile.ZipFile) -> dict[str, bytes]:
    """ppt/media files — excluding jszip's explicit directory entry."""
    return {
        n: zf.read(n)
        for n in zf.namelist()
        if n.startswith("ppt/media/") and not n.endswith("/")
    }


def test_img_broken_constant_matches_documented_sha() -> None:
    """Tripwire: the checked-in bundle's IMG_BROKEN is the documented blob."""
    blob = _img_broken_bytes()
    assert len(blob) == 1594
    assert hashlib.sha256(blob).hexdigest() == IMG_BROKEN_SHA256


@requires_records_sidecar
class TestRecordsEmitterGolden:
    """The records sidecar is untouched by the fix — prove it stays that way."""

    def test_png_control_deck_matches_golden_manifest(self) -> None:
        payload = _load_records_fixture("records_png_control.json")
        pptx = pptx_from_records.build_pptx(
            payload["title"], payload["slides"], font_mode=payload["font_mode"]
        )
        manifest = structural_manifest(pptx)

        # Direct sanity independent of the golden: healthy PNG media only.
        broken = _img_broken_bytes()
        with zipfile.ZipFile(BytesIO(pptx)) as zf:
            media = _media_entries(zf)
        assert media, "control deck should embed its PNG images as media"
        assert not [n for n in media if n.endswith(".svg")]
        assert all(blob != broken for blob in media.values())

        _assert_matches_golden(
            manifest, FIXTURE_DIR / "golden_records_png_manifest.json"
        )

    def test_svg_records_keep_todays_svgblip_fallback(self) -> None:
        """Pins the walker's failure-fallback semantics, not a desired end state.

        When in-browser rasterization fails, the walker keeps the raw SVG data
        URI and the sidecar must keep accepting it exactly as today: no crash,
        raw SVG media + svgBlip extension + the IMG_BROKEN placeholder as the
        primary blip. If this ever changes (e.g. a pptxgenjs upgrade), the
        fallback story needs re-validating — that is what this test surfaces.
        """
        payload = _load_records_fixture("records_svg_fallback.json")
        pptx = pptx_from_records.build_pptx(
            payload["title"], payload["slides"], font_mode=payload["font_mode"]
        )
        broken = _img_broken_bytes()
        with zipfile.ZipFile(BytesIO(pptx)) as zf:
            names = zf.namelist()
            svg_media = [
                n for n in names if n.startswith("ppt/media/") and n.endswith(".svg")
            ]
            assert svg_media, "raw SVG record should still ship as svg media"
            slide_xml = zf.read("ppt/slides/slide1.xml")
            assert b"asvg:svgBlip" in slide_xml
            placeholder_media = [
                n
                for n in names
                if n.startswith("ppt/media/") and zf.read(n) == broken
            ]
            assert placeholder_media, (
                "the primary blip PNG should be the IMG_BROKEN placeholder"
            )


@pytest.mark.slow
@requires_huashu_sidecar
class TestHuashuEmitter:
    """The snapshot engine: raster data: images embedded, everything else captured at 2x."""

    def _build(self, monkeypatch: pytest.MonkeyPatch, fixture: str, title: str) -> bytes:
        monkeypatch.setenv("HUASHU_PIPELINE_ENABLED", "1")
        html = (FIXTURE_DIR / fixture).read_text(encoding="utf-8")
        pptx, failures = build_pptx_guarded(title, [{"html": html, "notes": "p5"}])
        assert failures == [], f"huashu rejected the fixture slide: {failures}"
        assert pptx, "huashu produced no pptx bytes"
        return pptx

    def test_png_control_deck_matches_golden_manifest(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pptx = self._build(
            monkeypatch, "huashu_png_control.html", "P5 PNG control (huashu)"
        )
        manifest = structural_manifest(pptx)
        golden = HUASHU_PNG_GOLDENS.get(sys.platform)
        assert golden is not None, f"no huashu golden for this platform ({sys.platform})"
        _assert_matches_golden(manifest, golden)

    def test_svg_deck_emits_rasterized_pngs_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """NEW BEHAVIOR: SVG data-URI images arrive in the pptx as real PNGs.

        The fixture has an ``<img>`` SVG at 240x80 and a CSS
        ``background-image`` SVG on a 300x200 div. Each is captured as a
        screenshot of its box at device scale 2, so they must land as 480x160
        and 600x400 PNGs, twice the box — with no svg media, no svgBlip
        extension, and no IMG_BROKEN placeholder anywhere.
        """
        pptx = self._build(monkeypatch, "huashu_svg.html", "P5 SVG deck (huashu)")
        broken = _img_broken_bytes()
        with zipfile.ZipFile(BytesIO(pptx)) as zf:
            names = zf.namelist()

            svg_media = [
                n for n in names if n.startswith("ppt/media/") and n.endswith(".svg")
            ]
            assert svg_media == [], f"svg media leaked into the pptx: {svg_media}"

            slide_xml = b"".join(
                zf.read(n)
                for n in names
                if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)
            )
            assert b"svgBlip" not in slide_xml

            # NB: [Content_Types].xml is NOT asserted on — pptxgenjs 3.12.0
            # declares `Extension="svg"` unconditionally (the pre-fix PNG-only
            # controls carry it too); it is inert without an svg part. The
            # meaningful check is that no relationship targets an svg part.
            rels_xml = b"".join(
                zf.read(n) for n in names if n.endswith(".xml.rels")
            )
            assert b".svg" not in rels_xml

            media = _media_entries(zf)
            assert media, "rasterized PNGs should be embedded as media"
            placeholder_media = [n for n, blob in media.items() if blob == broken]
            assert placeholder_media == [], (
                f"IMG_BROKEN placeholder embedded: {placeholder_media}"
            )
            dims = sorted(_png_dimensions(blob) for blob in media.values())
            boxes = [(240, 80), (300, 200)]
            assert dims == [(CAPTURE_SCALE * w, CAPTURE_SCALE * h) for w, h in boxes], (
                f"expected captures at {CAPTURE_SCALE}x the img's and the bg div's boxes "
                f"{boxes}, got {dims}"
            )

    def test_non_ratio_true_box_letterboxes_instead_of_stretching(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The stretched-footer-logo bug: a 3:1 logo in a 13.8:1 flex-stretched
        box must be CONTAIN-fit (letterboxed), not stretch-filled.

        The browser draws the SVG letterboxed in its box (its viewBox keeps
        the default ``xMidYMid meet``), and the capture is that box at 2x, so
        dimensions alone cannot tell the two apart — the artwork's own
        geometry is what differs.
        The fixture logo is a rounded navy rect on transparency, so with
        contain-fit the drawn artwork occupies a centered 3:1 band and the far
        left/right of the canvas stays EMPTY; a stretch-fill paints navy all
        the way across. Asserting on the painted extent is therefore the
        non-tautological check.
        """
        from PIL import Image

        pptx = self._build(
            monkeypatch,
            "huashu_svg_stretched_logo.html",
            "Stretched footer logo (huashu)",
        )
        with zipfile.ZipFile(BytesIO(pptx)) as zf:
            media = _media_entries(zf)
        assert media, "expected a rasterized PNG for the footer logo"

        # The footer logo is the widest raster on the slide.
        blob = max(media.values(), key=lambda b: _png_dimensions(b)[0])
        width, height = _png_dimensions(blob)
        assert width > height * 4, (
            f"fixture should produce a very wide box raster, got {width}x{height}"
        )

        image = Image.open(BytesIO(blob)).convert("RGBA")
        # Painted = any non-transparent pixel. Column extent of the artwork.
        alpha = image.getchannel("A")
        painted_columns = [
            x
            for x in range(image.width)
            if alpha.crop((x, 0, x + 1, image.height)).getextrema()[1] > 0
        ]
        assert painted_columns, "raster is entirely transparent"
        painted_width = painted_columns[-1] - painted_columns[0] + 1
        drawn_ratio = painted_width / image.height

        # Contain-fit keeps the source's 3:1 ratio (240x80). A stretch-fill
        # would paint the full canvas width, i.e. ~13.8:1 here.
        assert drawn_ratio == pytest.approx(3.0, abs=0.35), (
            f"artwork drawn at {painted_width}x{image.height} (ratio "
            f"{drawn_ratio:.2f}) in a {width}x{height} box — expected the "
            "source 3:1 ratio to be preserved (contain-fit), not stretched to "
            "fill the box"
        )
