"""The CANVAS PREFLIGHT must read the DOM the way the rest of the export does.

``cbf6619`` and ``bb30e2f`` routed the preprocess pass and the slide walk through
pristine-realm accessors. This module is the site that survived both, and the
reason it survived is worth stating plainly, because it is a fact about the TESTS
and not only about the code.

``html2pptx()`` settles ``<canvas>`` slides before it does anything else: it reads
the canvas count, and then waits for every canvas to report a drawing buffer.
Both of those are ``page.evaluate``/``page.waitForFunction`` callbacks of their
own, and they run BEFORE ``preprocess.mjs`` is evaluated into the page. A
``page.evaluate`` callback is serialised and cannot close over anything on the
Node side, so the pristine accessors the later passes share are provably out of
scope there — the same constraint html2pptx.js already documents for why those
helpers are repeated rather than imported.

WHY THE SUITE WAS BLIND TO IT: every existing hostile-realm module asserts through
``probe_bg_transfer.mjs``, which evaluates the preprocess source against a fixture
directly. That is the right instrument for the pass it measures and the wrong one
here — it never runs the preflight at all, so a green suite proved nothing about
this path. Everything below therefore drives the REAL sidecar end to end, through
``_build``, and measures the .pptx.

THREE measured failure modes, one per read and per poisoning shape:

  * a REJECTED SLIDE — the count read carries no ``.catch()`` and
    ``page.evaluate`` has no timeout of its own, so a throwing lookup takes the
    whole export down and the slide never ships.
  * a STALLED WORKER — a lookup that does not return occupies the renderer's main
    thread. Nothing in the sidecar bounds it, so the export holds a browser and a
    worker slot until the Python wrapper's own subprocess timeout kills it.
  * a STALLED WORKER REACHED BY THE OTHER PROPERTY — the readiness check builds an
    array with ``Array.from``, which reads ``[Symbol.iterator]`` off the
    collection. A document that leaves ``querySelectorAll`` alone still gets in
    this way, which is why closing one read does not close the other.

Each fixture is a PURE ADDITION to ``every_collection_pass`` — one ``<script>`` in
the head, nothing else touched — so the deck they should export is a deck this
repo already exports, and parity against that twin is what shows the hardening
costs the slide no content.

Gating matches the sibling export suites: needs ``node``, the extracted sidecar
``node_modules`` (run ``setup.sh``) and a local Chrome/Chromium.
"""

from __future__ import annotations

import json

import pytest

from src.services import pptx_from_html_huashu
from tests.unit.test_export_slide_root_background import (
    _build,
    requires_huashu_sidecar,
)
from tests.unit.test_export_slide_root_hostile_realm import _probe_bounded
from tests.unit.test_export_svg_raster import structural_manifest

# The benign document every fixture here is a copy of, plus one <script>. It
# already carries a drawn <canvas>, which is what makes it a twin for THIS path:
# a canvas-free document skips the readiness wait entirely.
BENIGN = "every_collection_pass"

# The sub-pass whose non-zero count proves the twin's canvas is real and drawn.
# Without it the readiness read is never reached and every claim below is vacuous.
CANVAS_SUB_PASS = "canvasImgs"

# Cut down from the wrapper's own 180s. A healthy export of this deck measures
# ~3.5s, and the stalling fixtures hold the renderer far longer than this, so the
# budget separates the two by a wide margin while keeping a caught stall cheap.
# The benign twin is built under the SAME budget below, so a machine too slow for
# it fails as a control rather than passing this off as a stall.
BOUNDED_SIDECAR_SECONDS = 30

# Every fixture, with the interface each one reports having poisoned. Checked
# before anything else: a poisoning the browser refused would make the
# expectations below vacuous, since the export would succeed because there was
# never anything wrong with the realm.
POISONED_INTERFACES = {
    "hostile_canvas_selector_throw": "Document",
    "hostile_canvas_selector_stall": "Document",
    "hostile_canvas_iterator_stall": "NodeList",
}

HOSTILE_FIXTURES = tuple(sorted(POISONED_INTERFACES))


def _build_bounded(monkeypatch: pytest.MonkeyPatch, fixture: str) -> bytes:
    """``_build``, with the wrapper's sidecar timeout cut to a bounded budget.

    A stall then surfaces as ``HuashuExportError`` in seconds instead of holding
    the suite for the wrapper's full timeout.
    """
    monkeypatch.setattr(
        pptx_from_html_huashu, "SIDECAR_TIMEOUT_SECONDS", BOUNDED_SIDECAR_SECONDS
    )
    return _build(monkeypatch, f"{fixture}.html")


@requires_huashu_sidecar
class TestThePoisoningIsActuallyHostile:
    """Before asserting anything else: prove the fixtures bite.

    Each fixture publishes what it managed to do on ``document.title``, read
    before any pass runs. Probed through the preprocess harness on purpose: it is
    the cheapest way to read that report, and a clean run through it is itself
    the useful negative — it shows the preprocess pass is already immune to these
    poisonings, which is what leaves the preflight as the one site in question.
    """

    @pytest.mark.parametrize("fixture", HOSTILE_FIXTURES)
    def test_the_accessor_is_replaceable_and_was_replaced(self, fixture: str) -> None:
        interface = POISONED_INTERFACES[fixture]
        report = json.loads(_probe_bounded(fixture)[fixture]["title"])

        assert report["redefineResult"] == "ok", f"{fixture}: {report}"
        assert report["configurable"].get(interface) is True, (
            f"{fixture}: {interface}.prototype's accessor was not configurable, "
            f"so the fixture could not poison it: {report}"
        )
        assert report["direct"].get(interface) is True, (
            f"{fixture}: {interface}.prototype has no own copy of the accessor, "
            f"so this fixture is not poisoning what the preflight consumes: "
            f"{report}"
        )


@requires_huashu_sidecar
class TestTheBenignTwinReachesThePreflight:
    """The instrument itself, asserted rather than assumed."""

    def test_the_twin_carries_a_canvas_the_preflight_has_to_settle(self) -> None:
        """A canvas-free twin would skip the readiness read entirely.

        ``canvasImgs`` is non-zero only when the pass found a canvas whose
        ``toDataURL()`` is long enough to have been drawn on, so this is the
        available proof that the preflight's count is greater than zero and its
        readiness branch is entered.
        """
        counts = _probe_bounded(BENIGN)[BENIGN]["counts"]

        assert counts[CANVAS_SUB_PASS], (
            f"{BENIGN} reports {CANVAS_SUB_PASS}=0, so it has no drawn canvas and "
            "the preflight's readiness read is never reached — every stall claim "
            "in this module would be vacuous"
        )

    def test_the_twin_exports_well_inside_the_bounded_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The control for every stall claim below.

        If this fails, the machine is too slow for ``BOUNDED_SIDECAR_SECONDS`` and
        the stall assertions are measuring the budget rather than a stall.
        """
        assert _build_bounded(monkeypatch, BENIGN)


@requires_huashu_sidecar
class TestThePreflightSurvivesAHostileRealm:
    """The claim itself, measured on the real export rather than on a probe."""

    @pytest.mark.parametrize("fixture", HOSTILE_FIXTURES)
    def test_the_slide_still_exports(
        self, monkeypatch: pytest.MonkeyPatch, fixture: str
    ) -> None:
        """Neither rejected nor stalled.

        ``_build`` asserts the sidecar reported no per-slide failure, so a
        rejection surfaces here with the sidecar's own message. A stall surfaces
        as ``HuashuExportError`` once the bounded budget expires.
        """
        assert _build_bounded(monkeypatch, fixture)

    @pytest.mark.parametrize("fixture", HOSTILE_FIXTURES)
    def test_the_deck_is_the_benign_twins_deck_entry_for_entry(
        self, monkeypatch: pytest.MonkeyPatch, fixture: str
    ) -> None:
        """Exporting is the floor; exporting the SAME deck is the bar.

        Reading past the poisoning and then settling the canvas differently would
        still cost the deck its chart, and "the export succeeded" would not show
        it. Both decks are built in the same run so the comparison is independent
        of any golden and of the machine's Chrome build.
        """
        hostile = _build_bounded(monkeypatch, fixture)
        benign = _build_bounded(monkeypatch, BENIGN)

        assert structural_manifest(hostile) == structural_manifest(benign)
