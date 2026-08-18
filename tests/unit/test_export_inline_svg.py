"""Inline-``<svg>`` slides must survive the huashu (Claude Design) export.

Regression for the silent slide drop: huashu's vendored walker read
``el.className.includes(...)`` on every element, but ``className`` on SVG
elements is an ``SVGAnimatedString`` (no ``.includes``) — the resulting
TypeError aborted the whole slide, so a 6-slide deck with icons exported as
3 slides with no error surfaced to the user.

Two-layer fix under test:

1. GUARD — ``services/pptx-emit-huashu/html2pptx.js`` reads
   ``getAttribute('class')`` (string-or-null on every element type), so an
   inline ``<svg>`` can never throw the walk again.
2. RASTER — ``rasterizeInlineSvgs`` in
   ``services/pptx-emit-huashu/preprocess.mjs`` serializes each top-level
   inline ``<svg>``, rasterizes it to a PNG data-URI ``<img>`` at 2x the
   layout box (mirroring the Phase-5 SVG-data-URI pattern, including the
   leave-in-place failure fallback), so recovered slides keep their icons.

Gating matches ``test_export_svg_raster.py``: needs node, the extracted
sidecar ``node_modules`` and a local Chrome/Chromium (skipped otherwise).
"""

from __future__ import annotations

import os
import re
import struct
import zipfile
from io import BytesIO
from pathlib import Path
from unittest import mock

import pytest

from src.services import pptx_from_html_huashu

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "export_inline_svg"


def _huashu_available() -> bool:
    with mock.patch.dict(os.environ, {"HUASHU_PIPELINE_ENABLED": "1"}):
        return pptx_from_html_huashu.is_available()


requires_huashu_sidecar = pytest.mark.skipif(
    not _huashu_available(),
    reason=(
        "requires node, services/pptx-emit-huashu/node_modules (run setup.sh) "
        "and a local Chrome/Chromium"
    ),
)


def _png_dimensions(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"not a PNG: {data[:12]!r}"
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def _fixture_html(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


@pytest.mark.slow
@requires_huashu_sidecar
class TestInlineSvgExport:
    def test_inline_svg_deck_exports_every_slide(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A deck mixing inline-SVG and plain slides exports N-of-N."""
        monkeypatch.setenv("HUASHU_PIPELINE_ENABLED", "1")
        slides = [
            {"html": _fixture_html("slide_icon_card.html"), "notes": "icon card"},
            {"html": _fixture_html("slide_banner.html"), "notes": "banner"},
            {"html": _fixture_html("slide_text_control.html"), "notes": "control"},
        ]
        pptx, failures = pptx_from_html_huashu.build_pptx_huashu(
            "Inline SVG deck", slides, bypass_validation=True
        )
        assert failures == [], f"huashu rejected slides: {failures}"
        assert pptx, "huashu produced no pptx bytes"

        with zipfile.ZipFile(BytesIO(pptx)) as zf:
            names = zf.namelist()
            slide_xmls = [
                n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)
            ]
            assert len(slide_xmls) == len(slides), (
                f"expected {len(slides)} slides in the pptx, got "
                f"{len(slide_xmls)}: {sorted(slide_xmls)}"
            )

            # The inline SVGs must arrive as rasterized PNG media (2x the
            # 120x120 icon and the 200x100 banner), never as svg parts.
            svg_media = [
                n for n in names if n.startswith("ppt/media/") and n.endswith(".svg")
            ]
            assert svg_media == [], f"svg media leaked into the pptx: {svg_media}"
            media = {
                n: zf.read(n)
                for n in names
                if n.startswith("ppt/media/") and not n.endswith("/")
            }
            dims = sorted(_png_dimensions(blob) for blob in media.values())
            assert dims == [(240, 240), (400, 200)], (
                f"expected 2x rasters of the 120x120 and 200x100 inline svgs, "
                f"got {dims}"
            )
