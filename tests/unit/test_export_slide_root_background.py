"""Slide-root background transfer across a pinned template's <section> wrapper.

d93f950 stopped the deck parser discarding the semantic ``<section>`` wrapper a
pinned design-system template makes the model emit around ``div.slide``.
Preserving that wrapper is what restores the bundle's only slide-root rule.

The huashu export sidecar located the slide root with ``body > [class*="slide"]``
and a ``body > div`` fallback. A preserved ``<section data-label="...">`` carries
no class and is not a div, so both lookups missed,
``transferSlideRootBackground()`` returned ``'no-root'``, and the slide-root →
body background transfer stopped running for pinned decks. html2pptx.js derives
the *slide* background from the *body* background, so dark/white variant slides
whose export is correct today would have exported white.

These tests measure the emitted .pptx. A DOM-level assertion that the selector
matched cannot show that the background actually reached the artifact, so the
background fill is read back out of ``ppt/slides/slide1.xml``. The one thing no
artifact can show is *which branch* ran — a rootless deck and a broken locator
both end up white — so the ``'no-root'`` sentinel is asserted separately via the
sidecar's ``probe_bg_transfer.mjs``.

Gating matches the sibling export suite: needs ``node``, the extracted sidecar
``node_modules`` (run ``setup.sh``) and a local Chrome/Chromium.
"""

from __future__ import annotations

import json
import re
import subprocess
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from src.services import pptx_from_html_huashu

# Reuse the sibling suite's timestamp-canonical manifest so both modules mean
# exactly the same thing by "structurally identical pptx".
from tests.unit.test_export_svg_raster import (
    HUASHU_AVAILABLE,
    structural_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "export_slide_root"
PROBE_SCRIPT = (
    REPO_ROOT / "services" / "pptx-emit-huashu" / "probe_bg_transfer.mjs"
)

# The fixtures' only colour. Synthetic — no brand palette in test data.
GROUND = "123456"
GROUND_RGB = "rgb(18, 52, 86)"
# rgbToHex() in html2pptx.js resolves a transparent body to white, which is
# what a lost background looks like in the artifact.
LOST = "FFFFFF"

requires_huashu_sidecar = pytest.mark.skipif(
    not HUASHU_AVAILABLE,
    reason=(
        "requires node, services/pptx-emit-huashu/node_modules (run setup.sh) "
        "and a local Chrome/Chromium"
    ),
)


def _build(monkeypatch: pytest.MonkeyPatch, fixture: str) -> bytes:
    """Export one fixture slide through the real huashu pipeline."""
    monkeypatch.setenv("HUASHU_PIPELINE_ENABLED", "1")
    html = (FIXTURE_DIR / fixture).read_text(encoding="utf-8")
    pptx, failures = pptx_from_html_huashu.build_pptx_huashu(
        "slide root background", [{"html": html}]
    )
    assert failures == [], f"huashu rejected {fixture}: {failures}"
    assert pptx, f"huashu produced no pptx bytes for {fixture}"
    return pptx


def _slide_background(pptx: bytes) -> str:
    """The slide's background fill, read out of the emitted pptx."""
    with zipfile.ZipFile(BytesIO(pptx)) as zf:
        xml = zf.read("ppt/slides/slide1.xml").decode("utf-8")
    bg = re.search(r"<p:bg>.*?</p:bg>", xml, re.S)
    assert bg is not None, "slide carries no <p:bg> element at all"
    fills = re.findall(r'<a:srgbClr val="([0-9A-Fa-f]{6})"', bg.group(0))
    assert len(fills) == 1, f"expected one background fill, got {fills}"
    return fills[0].upper()


def _probe(*fixtures: str) -> list[dict]:
    """Run the real PREPROCESS_SOURCE and report the branch it took."""
    proc = subprocess.run(
        ["node", str(PROBE_SCRIPT), *[str(FIXTURE_DIR / f) for f in fixtures]],
        cwd=pptx_from_html_huashu.SIDECAR_DIR,
        env=pptx_from_html_huashu.sidecar_subprocess_env(),
        capture_output=True,
        text=True,
        timeout=pptx_from_html_huashu.SIDECAR_TIMEOUT_SECONDS,
    )
    assert proc.returncode == 0, f"probe failed: {proc.stderr}"
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


@requires_huashu_sidecar
class TestPinnedWrapperBackground:
    """A pinned template's wrapper must cost the export nothing."""

    def test_wrapped_deck_exports_identically_to_the_unwrapped_deck(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The wrapper is invisible to the artifact.

        The two fixtures share one stylesheet and differ only by the
        ``<section>`` wrapper, so this pins the regression exactly: before the
        locator was widened the wrapped deck exported ``FFFFFF`` while the
        unwrapped deck exported the ground. Comparing the two artifacts from
        the same run keeps the assertion independent of any golden, and of the
        machine's Chrome build.
        """
        wrapped = _build(monkeypatch, "wrapped_dark.html")
        unwrapped = _build(monkeypatch, "unwrapped_dark.html")

        assert _slide_background(unwrapped) == GROUND
        assert _slide_background(wrapped) == GROUND
        assert structural_manifest(wrapped) == structural_manifest(unwrapped)

    def test_wrapper_ground_survives_when_the_slide_body_is_bare(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The OUTERMOST root wins, not the inner .slide.

        Here only the wrapper paints a ground and the ``.slide`` inside it
        carries no variant class, so nothing covers the slide and ``<p:bg>`` is
        the ground the viewer sees. A locator resolving to the inner ``.slide``
        would read a transparent background and emit white, so this is what
        makes the suite discriminating rather than merely colour-blind.
        """
        pptx = _build(monkeypatch, "wrapped_bare_slide.html")
        assert _slide_background(pptx) == GROUND

    def test_wrapperless_no_design_deck_keeps_its_background(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guards the ``body > div`` fallback that no-DS decks rely on."""
        pptx = _build(monkeypatch, "unwrapped_nodesign.html")
        assert _slide_background(pptx) == GROUND

    def test_rootless_deck_exports_the_untouched_body_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nothing is invented for a deck with no slide root."""
        pptx = _build(monkeypatch, "rootless.html")
        assert _slide_background(pptx) == LOST


@requires_huashu_sidecar
class TestSlideRootBranchTaken:
    """Which branch of the locator ran — the part no artifact can show."""

    def test_rootless_input_still_takes_the_no_root_path(self) -> None:
        """The 'no-root' sentinel must stay reachable, not become dead code."""
        (result,) = _probe("rootless.html")
        assert result["bgTransferred"] == "no-root"
        assert result["bodyBackgroundColor"] == "rgba(0, 0, 0, 0)"

    def test_wrapped_and_wrapperless_shapes_all_transfer_the_ground(self) -> None:
        """Every shape that has a slide root resolves to exactly one ground."""
        results = _probe(
            "wrapped_dark.html",
            "wrapped_bare_slide.html",
            "unwrapped_dark.html",
            "unwrapped_nodesign.html",
        )
        assert [r["bgTransferred"] for r in results] == ["solid"] * 4
        assert [r["bodyBackgroundColor"] for r in results] == [GROUND_RGB] * 4
