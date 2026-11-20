"""Inline-``<svg>`` slides must survive the huashu (Claude Design) export.

Regression for the silent slide drop: the converter the export once ran read
``el.className.includes(...)`` on every element, but ``className`` on SVG
elements is an ``SVGAnimatedString`` (no ``.includes``) — the resulting
TypeError aborted the whole slide, so a 6-slide deck with icons exported as
3 slides with no error surfaced to the user.

The snapshot engine reads an inline ``<svg>`` as one picture: the element is a
capture target, screenshotted in isolation at device scale 2
(``services/pptx-emit-huashu/capture.cjs``), and the picture sits on the svg's
own box. So every slide exports, each icon is a picture where the browser drew
it, and no SVG data reaches pptxgenjs.

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
from tests.fixtures.export_snapshot_support import slide_shapes

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


# Per slide of the deck below: the inline svg's box (x, y, w, h) in CSS px and
# its capture's PNG size, twice the box; None for the slide with no svg.
SVG_BOXES = (
    ((128, 240, 120, 120), (240, 240)),
    ((88, 72, 200, 100), (400, 200)),
    (None, None),
)


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
                f"expected captures at 2x the 120x120 and 200x100 inline svgs' boxes, "
                f"got {dims}"
            )

        # Each icon is one captured picture on the svg's own box: the card's
        # icon at (88 + 40, 200 + 40), the banner at (88, 72). The text-only
        # control slide holds none.
        for index, (box, size) in enumerate(SVG_BOXES):
            pictures = [shape for shape in slide_shapes(pptx, index) if shape.kind == "picture"]
            assert len(pictures) == (1 if box else 0), (
                f"slide {index + 1}: expected {1 if box else 0} picture(s), got {pictures}"
            )
            if not box:
                continue
            (picture,) = pictures
            placed = (round(picture.x), round(picture.y), round(picture.w), round(picture.h))
            assert placed == box, f"slide {index + 1}: the icon is placed at {placed}, not {box}"
            assert picture.image is not None and _png_dimensions(picture.image) == size, (
                f"slide {index + 1}: the icon's picture is not a {size} capture"
            )
