"""Slide-root background transfer across a pinned template's <section> wrapper.

d93f950 stopped the deck parser discarding the semantic ``<section>`` wrapper a
pinned design-system template makes the model emit around ``div.slide``.
Preserving that wrapper is what restores the bundle's only slide-root rule.

The huashu export sidecar located the slide root with ``body > [class*="slide"]``
and a ``body > div`` fallback. A preserved ``<section data-label="...">`` carries
no class and is not a div, so both lookups missed,
``transferSlideRootBackground()`` returned ``'no-root'``, and the slide-root →
body background transfer stopped running for pinned decks. The export derives
the *slide* background from the *body* background (snapshot.mjs
slideBackground), so dark/white variant slides whose export is correct today
would have exported white.

These tests measure the emitted .pptx. A DOM-level assertion that the selector
matched cannot show that the background actually reached the artifact, so the
background fill is read back out of ``ppt/slides/slide1.xml``. The one thing no
artifact can show is *which branch* ran — a rootless deck and a broken locator
both end up white — so the ``'no-root'`` sentinel is asserted separately via the
sidecar's ``probe_bg_transfer.mjs``.

A slide root whose ground holds a ``data:`` image (a photo, a pattern, under a
scrim gradient or not) is the other case: the transfer leaves that ground on the
root (``bgTransferred`` is ``image``), and the slide's ``<p:bg>`` is one
picture of the whole slide as the browser paints it under the content, each
layer at its own size and position (cover, contain, a side), over what lies
beneath the root. Those tests read the background picture's pixels against the
browser's own (``browser_pixels``) at points where cover, contain and a stretch
differ.

Gating matches the sibling export suite: needs ``node``, the extracted sidecar
``node_modules`` (run ``setup.sh``) and a local Chrome/Chromium.
"""

from __future__ import annotations

import base64
import dataclasses
import json
import re
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from src.services import pptx_from_html_huashu
from tests.fixtures.export_snapshot_support import (
    DECK_CSS,
    browser_pixels,
    build_pptx_guarded,
    export_logged,
    export_slides,
    run_node,
    slide_background,
    slide_background_picture,
    slide_document,
    slide_shapes,
    slide_summaries,
)

# Reuse the sibling suite's timestamp-canonical manifest so both modules mean
# exactly the same thing by "structurally identical pptx".
from tests.unit.test_export_svg_raster import (
    HUASHU_AVAILABLE,
    structural_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "export_slide_root"
PROBE_SCRIPT = REPO_ROOT / "services" / "pptx-emit-huashu" / "probe_bg_transfer.mjs"

# The fixtures' only colour. Synthetic — no brand palette in test data.
GROUND = "123456"
GROUND_RGB = "rgb(18, 52, 86)"
# A transparent body is ground on the white canvas (snapshot.mjs groundColour),
# which is what a lost background looks like in the artifact.
LOST = "FFFFFF"

requires_huashu_sidecar = pytest.mark.skipif(
    not HUASHU_AVAILABLE,
    reason=(
        "requires node, services/pptx-emit-huashu/node_modules (run setup.sh) "
        "and a local Chrome/Chromium"
    ),
)


def _build(monkeypatch: pytest.MonkeyPatch, fixture: str) -> bytes:
    """Export one fixture slide through the real huashu pipeline, its model whole.

    The hostile-realm suites build their decks with it too, so a model the
    model check dropped part of fails them all (``build_pptx_guarded``): a twin
    pair that both lost the same item would otherwise still compare equal.
    """
    monkeypatch.setenv("HUASHU_PIPELINE_ENABLED", "1")
    html = (FIXTURE_DIR / fixture).read_text(encoding="utf-8")
    pptx, failures = build_pptx_guarded("slide root background", [{"html": html}])
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
    proc = run_node(
        [str(PROBE_SCRIPT), *[str(FIXTURE_DIR / f) for f in fixtures]],
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
        """The wrapper costs the artifact nothing: the same ground, the same slide.

        The two fixtures share one stylesheet and differ only by the
        ``<section>`` wrapper, so this pins the regression exactly: before the
        locator was widened the wrapped deck exported ``FFFFFF`` while the
        unwrapped deck exported the ground. Comparing the two artifacts from
        the same run keeps the assertion independent of any golden, and of the
        machine's Chrome build.

        The wrapped page paints one layer more, and the export draws it: the
        wrapper is the slide root, whose ground is the slide background, and
        the ``.slide.dark`` body inside it paints the same ground again over
        it, a slide-sized rect beneath everything else. Every other item is the
        unwrapped deck's, in the same order (item names are sequence numbers,
        so they are left out).
        """
        wrapped = _build(monkeypatch, "wrapped_dark.html")
        unwrapped = _build(monkeypatch, "unwrapped_dark.html")

        assert _slide_background(unwrapped) == GROUND
        assert _slide_background(wrapped) == GROUND
        body, *rest = slide_shapes(wrapped)
        assert (body.kind, body.geometry, body.fill) == ("shape", "rect", GROUND), body
        assert (body.x, body.y, body.w, body.h) == (0, 0, 1280, 720), body
        assert [dataclasses.replace(shape, name="") for shape in rest] == [
            dataclasses.replace(shape, name="") for shape in slide_shapes(unwrapped)
        ]

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

    def test_ground_survives_a_chain_of_wrappers_not_just_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Promotion follows the WHOLE chain, as the backend's does.

        ``find_slide_roots`` promotes outward through every consecutive
        sole-child semantic wrapper, so for ``section > article > div.slide``
        it stores the outer ``<section>``. A locator that promotes a single
        level stops at the ``<article>``, does not recognise it as a root and
        falls through, so the slide exports white while the app renders it
        correctly — the two surfaces disagreeing about the same deck.

        The fixture shares wrapped_bare_slide.html's rules exactly and differs
        only by the interposed ``<article>``, so comparing the two artifacts
        from one run attributes any difference to that level alone.
        """
        nested = _build(monkeypatch, "wrapped_nested_bare_slide.html")
        single = _build(monkeypatch, "wrapped_bare_slide.html")

        assert _slide_background(nested) == GROUND
        assert _slide_background(nested) == _slide_background(single)
        assert structural_manifest(nested) == structural_manifest(single)

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


# ---------------------------------------------------------------------------
# A slide root whose ground is a data: image
# ---------------------------------------------------------------------------

# Four bands of 100 rows each, top to bottom, on a 400 px square: cover, contain
# and a stretch to the slide put the band edges at different heights.
STRIPE_COLOURS = ((238, 51, 34), (34, 170, 85), (34, 85, 204), (238, 187, 34))
IMAGE_GROUND_TITLE = "Industry outlook"
# A pixel of the exported ground and the browser's agree within this per channel.
GROUND_COLOUR_TOLERANCE = 8


def _stripes_png() -> str:
    image = Image.new("RGB", (400, 400))
    for band, colour in enumerate(STRIPE_COLOURS):
        image.paste(colour, (0, band * 100, 400, band * 100 + 100))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _photo_jpeg() -> str:
    """An 800x600 'photograph': smooth ramps on every channel, JPEG-encoded."""
    image = Image.new("RGB", (800, 600))
    image.putdata(
        [
            (40 + x * 180 // 800, 60 + y * 160 // 600, 200 - (x + y) * 120 // 1400)
            for y in range(600)
            for x in range(800)
        ]
    )
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _ground_pixels(pptx: bytes, points: list[tuple[float, float]]) -> list[tuple[int, int, int]]:
    """What the slide's background picture shows at each point, the picture laid over the slide.

    A slide's ground has no holes: each app shows its own colour through one,
    so the picture must be opaque wherever it is.
    """
    picture = slide_background_picture(pptx)
    assert picture is not None, "the slide has no background picture"
    image = Image.open(BytesIO(picture)).convert("RGBA")
    alpha = image.getchannel("A").getextrema()
    assert alpha == (255, 255), f"the background picture is not opaque: its alpha runs {alpha}"
    image = image.convert("RGB").resize((1280, 720), Image.BILINEAR)
    return [image.getpixel((int(x), int(y))) for x, y in points]


def _assert_ground_is_the_browsers(
    pptx: bytes, document: str, points: list[tuple[float, float]], what: str
) -> None:
    """The background picture shows what the browser shows at each point, within tolerance."""
    shown = browser_pixels(document, points)
    exported = _ground_pixels(pptx, points)
    wrong = [
        f"({x:g}, {y:g}): the browser shows {browser}, the background picture {picture}"
        for (x, y), browser, picture in zip(points, shown, exported)
        if max(abs(a - b) for a, b in zip(browser, picture)) > GROUND_COLOUR_TOLERANCE
    ]
    assert not wrong, f"{what}: the background picture is not the browser's ground:\n  " + (
        "\n  ".join(wrong)
    )


def _assert_ground_is_no_item(pptx: bytes, what: str) -> None:
    """The ground is the slide's background alone: no solid fill, no picture item over it."""
    assert slide_background(pptx) is None, (
        f"{what}: the slide's background is the solid {slide_background(pptx)}, not a picture"
    )
    pictures = [shape for shape in slide_shapes(pptx) if shape.kind == "picture"]
    assert pictures == [], f"{what}: the ground is repeated as {len(pictures)} picture item(s)"
    titles = [
        shape
        for shape in slide_shapes(pptx)
        if shape.kind == "text" and IMAGE_GROUND_TITLE in shape.text
    ]
    assert len(titles) == 1, f"{what}: the title is not one native text item"


@pytest.mark.slow
@requires_huashu_sidecar
class TestSlideRootImageGround:
    """A slide root painting a data: image is the slide's background picture, fitted as it shows."""

    def test_a_cover_image_ground_is_the_background_picture_the_browser_shows(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A ``.slide`` root painting a square banded image ``center / cover``.

        Cover scales the image to the slide's width and crops its top and
        bottom, so the band edges fall at 40, 360 and 680 px; stretched to the
        slide they would fall at 180, 360 and 540. The slide's ``<p:bg>`` is
        one picture showing the browser's pixels at points either side of
        each, the root's colour is no solid fill under it, no picture item
        repeats it, and the title stays native text.
        """
        body = (
            '<div class="slide" style="background: #000000 url('
            + _stripes_png()
            + ') center / cover no-repeat;">'
            f'<h1 style="font-size: 40px; color: #FFFFFF;">{IMAGE_GROUND_TITLE}</h1></div>'
        )
        document = slide_document(body, css=DECK_CSS, slide_id="snapshot-1")
        pptx, failures = export_slides([body], css=DECK_CSS, monkeypatch=monkeypatch)
        assert failures == [], failures
        _assert_ground_is_no_item(pptx, "the cover ground")
        points = [
            (x, y) for x in (640.0, 1100.0) for y in (20.0, 100.0, 250.0, 520.0, 620.0, 700.0)
        ]
        _assert_ground_is_the_browsers(pptx, document, points, "the cover ground")

    def test_a_photo_under_a_scrim_is_one_background_picture_and_the_text_stays_native(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A photo-cover slide: a JPEG ``center / cover`` under a gradient scrim, in one ground.

        The design system's industry and event covers paint a photograph on the
        slide; here the scrim is the ground's own first layer, as a generated
        deck often writes it. The background transfer leaves that ground on the
        root and says so (``bgTransferred`` is ``image``); the slide's
        ``<p:bg>`` is one picture of the photo under its scrim as the browser
        shows it, and the white title is native text over it.
        """
        body = (
            '<div class="slide" style="background: linear-gradient(90deg, rgba(0, 0, 0, 0.75), '
            "rgba(0, 0, 0, 0) 60%), url(" + _photo_jpeg() + ') center / cover; color: #FFFFFF;">'
            f'<h1 style="font-size: 40px;">{IMAGE_GROUND_TITLE}</h1></div>'
        )
        document = slide_document(body, css=DECK_CSS, slide_id="snapshot-1")
        logged = export_logged([document], monkeypatch=monkeypatch)
        assert logged.failures == [], logged.failures
        (summary,) = slide_summaries(logged.stderr)
        assert summary["bgTransferred"] == "image", summary
        _assert_ground_is_no_item(logged.pptx, "the photo ground")
        points = [(x, y) for x in (120.0, 640.0, 1000.0, 1250.0) for y in (30.0, 360.0, 690.0)]
        _assert_ground_is_the_browsers(logged.pptx, document, points, "the photo ground")

    def test_a_contained_image_on_a_section_root_letterboxes_on_its_colour(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A pinned template's ``<section>`` root painting the banded image ``right / contain``.

        Contain fits the whole image to the slide's height at its right, so
        the root's colour shows to its left and the bands are 180 px each. The
        background picture shows both as the browser does.
        """
        body = (
            '<section style="background: #123456 url('
            + _stripes_png()
            + ') no-repeat right center / contain;"><div class="slide" style="background: none;">'
            f'<h1 style="font-size: 40px; color: #FFFFFF;">{IMAGE_GROUND_TITLE}</h1>'
            "</div></section>"
        )
        document = slide_document(body, css=DECK_CSS, slide_id="snapshot-1")
        pptx, failures = export_slides([body], css=DECK_CSS, monkeypatch=monkeypatch)
        assert failures == [], failures
        _assert_ground_is_no_item(pptx, "the contained ground")
        points = [(x, y) for x in (300.0, 700.0, 1200.0) for y in (100.0, 250.0, 450.0, 650.0)]
        _assert_ground_is_the_browsers(pptx, document, points, "the contained ground")

    @pytest.mark.parametrize(
        ("body_style", "uncovered"),
        [("<style>body { background: #2B0D08; }</style>", (43, 13, 8)), ("", (255, 255, 255))],
        ids=["body-painted", "canvas-white"],
    )
    def test_a_ground_the_image_leaves_uncovered_shows_what_lies_beneath(
        self, monkeypatch: pytest.MonkeyPatch, body_style: str, uncovered: tuple[int, int, int]
    ) -> None:
        """A ``.slide`` root painting the banded image ``center / contain``, with no colour.

        Where the image leaves the slide uncovered, at its left and right, the
        browser shows what lies beneath the root: body's ground when the deck
        paints body (2B0D08), else the white canvas. The background picture is
        the whole slide as the browser paints it under the content, so it shows
        that there too, not a hole.
        """
        body = (
            body_style
            + '<div class="slide" style="background: url('
            + _stripes_png()
            + ') no-repeat center / contain;">'
            f'<h1 style="font-size: 40px; color: #FFFFFF;">{IMAGE_GROUND_TITLE}</h1></div>'
        )
        document = slide_document(body, css=DECK_CSS, slide_id="snapshot-1")
        pptx, failures = export_slides([body], css=DECK_CSS, monkeypatch=monkeypatch)
        assert failures == [], failures
        _assert_ground_is_no_item(pptx, "the uncovered ground")
        assert browser_pixels(document, [(150.0, 450.0)]) == [uncovered], (
            f"fixture drift: the browser does not show {uncovered} beside the image"
        )
        points = [(x, y) for x in (150.0, 640.0, 1150.0) for y in (250.0, 450.0, 650.0)]
        _assert_ground_is_the_browsers(pptx, document, points, "the uncovered ground")

    def test_a_document_that_paints_no_ground_shows_the_white_canvas(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A slide document of its own, painting neither html nor body, the image ``contain``.

        The export routes' documents paint html white; a document handed to
        the sidecar as it is may paint nothing, and then the browser shows its
        white canvas beside the image, which the picture shows too: opaque,
        not a hole.
        """
        document = (
            '<!DOCTYPE html><html><head><meta charset="utf-8"><style>'
            "* { margin: 0; padding: 0; } body { width: 1280px; height: 720px; } "
            ".slide { width: 1280px; height: 720px; }</style></head><body>"
            '<div class="slide" style="background: url('
            + _stripes_png()
            + ') no-repeat center / contain;">'
            f'<h1 style="font-size: 40px; color: #FFFFFF;">{IMAGE_GROUND_TITLE}</h1>'
            "</div></body></html>"
        )
        monkeypatch.setenv("HUASHU_PIPELINE_ENABLED", "1")
        pptx, failures = build_pptx_guarded("image ground", [{"html": document}])
        assert failures == [], failures
        _assert_ground_is_no_item(pptx, "the canvas ground")
        assert browser_pixels(document, [(150.0, 450.0)]) == [(255, 255, 255)], (
            "fixture drift: the browser does not show its white canvas beside the image"
        )
        points = [(x, y) for x in (150.0, 640.0, 1150.0) for y in (250.0, 450.0, 650.0)]
        _assert_ground_is_the_browsers(pptx, document, points, "the canvas ground")
