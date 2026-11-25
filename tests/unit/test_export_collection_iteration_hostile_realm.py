"""Consuming a live DOM collection must terminate in a HOSTILE JS realm.

5d9229a hardened the slide-root DESCENT against a realm that lies about an
element's children, and said in as many words what it was leaving behind:
``Array.from(NodeList)`` consumes ``NodeList.prototype[Symbol.iterator]``, which
a hostile realm can make endless. This is that residual.

``Array.from()`` — like spread, and like ``for...of`` — reads the collection's
``[Symbol.iterator]``, and that property is CONFIGURABLE on both
``NodeList.prototype`` and ``HTMLCollection.prototype``. An iterator that never
reports ``done`` stops whichever read reaches it first: the slide-root locator's
loop over its wrapper candidates, and every collection the snapshot reads after
it. So every page-side read goes through ``dom_access.mjs``, which walks the
sibling chain or indexes under a bound and never iterates a live collection.

REACHABILITY is the same as the sibling suite's and no weaker: ``SLIDE_CSP``
(``src/utils/html_safety.py``) carries ``script-src 'unsafe-inline'``, so inline
script in an uploaded template runs in the export page at load, before any pass.

It has TWO measured failure modes, which is why the expectations below are
"returned", not merely "did not hang":

  * a HANG, where each iteration does bounded real work — the locator's
    ``for...of``, whose body walks a wrapper chain per candidate.
  * a RAISE, where it does not: a tight ``Array.from()`` grows its result until it
    exceeds the maximum array length and throws ``RangeError: Invalid array
    length``, which propagates out of ``page.evaluate`` and fails the export.

Both are a denial of service in the sidecar, which has no execution budget of its
own. Neither is distinguishable, from outside, from a deck that simply cannot be
exported.

The two fixtures split the reads by LAYER:

  hostile_wrapper_iterator      the wrapper shape, so the locator's own
                                collection read is what the pass reaches.
  hostile_collection_passes     a shape the locator resolves on its first lookup,
                                so the export runs on into the snapshot's reads of
                                a monospace panel, a prose div, an ``<svg>`` and an
                                ``<img>``, which a hardened locator cannot help.

Each is a byte-identical copy of a BENIGN twin plus its ``<script>``, so any
difference in the artifact is attributable to the hostile script alone. Each pair
is compared three ways: the background transfer's result (``{bgTransferred}``),
the snapshot's slide summary (every count it reports, without the clock reading
``captureMs``), and the whole exported deck.

Gating matches the sibling export suites: needs ``node``, the extracted sidecar
``node_modules`` (run ``setup.sh``) and a local Chrome/Chromium.
"""

from __future__ import annotations

import json

import pytest

from src.services import pptx_from_html_huashu
from tests.fixtures.export_snapshot_support import (
    export_logged,
    slide_summaries,
    summary_without_clock,
)
from tests.unit.test_export_slide_root_background import (
    FIXTURE_DIR,
    GROUND,
    GROUND_RGB,
    _build,
    _slide_background,
    requires_huashu_sidecar,
)
from tests.unit.test_export_slide_root_hostile_realm import (
    EVALUATE_TIMEOUT_MS,
    _probe_bounded,
)
from tests.unit.test_export_svg_raster import structural_manifest

# Long enough to be a real export of a two-element slide (the hostile twins finish
# in a couple of seconds now that every read terminates), short enough that a
# regression costs the suite seconds instead of the 180s-per-case the production
# timeout would.
HOSTILE_EXPORT_TIMEOUT_SECONDS = 25

# Each hostile fixture and the benign twin it must export identically to.
TWINS = {
    "hostile_wrapper_iterator": "wrapped_nested_bare_slide",
    "hostile_collection_passes": "collection_passes",
}

HOSTILE_FIXTURES = tuple(TWINS)

# The two interfaces whose [Symbol.iterator] the fixtures replace. Both, because
# the export reads both: childNodes and querySelectorAll() are NodeLists,
# element.children is an HTMLCollection.
POISONED_INTERFACES = ("NodeList", "HTMLCollection")


@requires_huashu_sidecar
class TestTheIteratorPoisoningIsActuallyHostile:
    """Before asserting anything else: prove the fixtures bite.

    A poisoning the browser refused would make every expectation below vacuous —
    the pass would return because there was never anything wrong with the realm.
    Each fixture publishes what it managed to do on ``document.title``, read
    before the pass runs.
    """

    @pytest.mark.parametrize("fixture", HOSTILE_FIXTURES)
    def test_both_collection_iterators_are_replaceable_and_were_replaced(
        self, fixture: str
    ) -> None:
        report = json.loads(_probe_bounded(fixture)[fixture]["title"])

        assert report["redefineResult"] == "ok", f"{fixture}: {report}"
        for interface in POISONED_INTERFACES:
            assert report["configurable"].get(interface) is True, (
                f"{fixture}: {interface}.prototype[Symbol.iterator] was not "
                f"configurable, so the fixture could not poison it: {report}"
            )
            assert report["direct"].get(interface) is True, (
                f"{fixture}: {interface}.prototype has no own [Symbol.iterator], "
                f"so this fixture is not poisoning what the pass consumes: {report}"
            )


@requires_huashu_sidecar
class TestThePassStillReturns:
    """The denial-of-service fix itself, stated over both failure modes."""

    @pytest.mark.parametrize("fixture", HOSTILE_FIXTURES)
    def test_an_endless_collection_iterator_does_not_hang_the_export(
        self, fixture: str
    ) -> None:
        """RED before the fix: hostile_wrapper_iterator never returns."""
        result = _probe_bounded(fixture)[fixture]

        assert result["timedOut"] is False, (
            f"{fixture}: the preprocess pass did not terminate within "
            f"{EVALUATE_TIMEOUT_MS}ms — consuming a DOM collection is "
            "non-terminating in a hostile realm"
        )

    @pytest.mark.parametrize("fixture", HOSTILE_FIXTURES)
    def test_an_endless_collection_iterator_does_not_raise(self, fixture: str) -> None:
        """RED before the fix: hostile_collection_passes raises RangeError.

        Separate from the hang because it is a separate failure: an Array.from()
        whose iterator never finishes exhausts the maximum array length instead of
        spinning, and the throw propagates out of the pass.
        """
        result = _probe_bounded(fixture)[fixture]

        assert result["error"] is None, (
            f"{fixture}: the preprocess pass raised {result['error']!r} — "
            "consuming a DOM collection is unsafe in a hostile realm"
        )


@requires_huashu_sidecar
class TestTheHostileScriptCostsTheDeckNothing:
    """Returning is the floor; reading the REAL collection is the bar.

    Stopping the hang by giving up on a collection would silently drop content —
    a hostile page script would still get to break the deck, just more quietly.
    """

    def test_the_wrapper_shape_still_resolves_its_ground(self) -> None:
        result = _probe_bounded("hostile_wrapper_iterator")["hostile_wrapper_iterator"]

        assert result["bgTransferred"] == "solid", (
            f"locator took the '{result['bgTransferred']}' branch"
        )
        assert result["bodyBackgroundColor"] == GROUND_RGB

    @pytest.mark.parametrize("fixture", HOSTILE_FIXTURES)
    def test_every_read_reports_the_same_counts_as_the_benign_twin(
        self, monkeypatch: pytest.MonkeyPatch, fixture: str
    ) -> None:
        """Same elements, measured as the counts the background transfer and the snapshot report.

        The transfer's result is probed in ONE run so the two documents share a
        browser. The snapshot's slide summary counts the elements it walked and
        the items, pictures and captures it made of them, so a collection read
        that silently returned fewer elements shows up as a smaller count rather
        than having to be predicted here; it is compared whole but for its clock
        reading, ``captureMs``.
        """
        twin = TWINS[fixture]
        probed = _probe_bounded(fixture, twin)

        assert probed[fixture]["counts"] == probed[twin]["counts"]
        assert set(probed[twin]["counts"]) == {"bgTransferred"}, probed[twin]["counts"]

        monkeypatch.setattr(
            pptx_from_html_huashu,
            "SIDECAR_TIMEOUT_SECONDS",
            HOSTILE_EXPORT_TIMEOUT_SECONDS,
        )
        summaries = {}
        for name in (fixture, twin):
            logged = export_logged(
                [(FIXTURE_DIR / f"{name}.html").read_text(encoding="utf-8")],
                monkeypatch=monkeypatch,
            )
            assert logged.failures == [], f"{name}: {logged.failures}"
            (summary,) = slide_summaries(logged.stderr)
            summaries[name] = summary_without_clock(summary)

        assert summaries[twin]["elements"] > 0, summaries[twin]
        assert summaries[fixture] == summaries[twin]

    @pytest.mark.parametrize("fixture", HOSTILE_FIXTURES)
    def test_the_ground_reaches_the_artifact(
        self, monkeypatch: pytest.MonkeyPatch, fixture: str
    ) -> None:
        """Measured on the .pptx, not the DOM — the export is the deliverable."""
        monkeypatch.setattr(
            pptx_from_html_huashu,
            "SIDECAR_TIMEOUT_SECONDS",
            HOSTILE_EXPORT_TIMEOUT_SECONDS,
        )

        assert _slide_background(_build(monkeypatch, f"{fixture}.html")) == GROUND

    @pytest.mark.parametrize("fixture", HOSTILE_FIXTURES)
    def test_the_hostile_deck_exports_as_the_benign_deck(
        self, monkeypatch: pytest.MonkeyPatch, fixture: str
    ) -> None:
        """The whole artifact, not just its ground.

        Stronger than the colour assertion above: it also catches a fix that keeps
        the background but perturbs the passes downstream of it — a dropped code
        line, an unrasterized icon, a lost inline run.
        """
        monkeypatch.setattr(
            pptx_from_html_huashu,
            "SIDECAR_TIMEOUT_SECONDS",
            HOSTILE_EXPORT_TIMEOUT_SECONDS,
        )
        hostile = _build(monkeypatch, f"{fixture}.html")
        benign = _build(monkeypatch, f"{TWINS[fixture]}.html")

        assert structural_manifest(hostile) == structural_manifest(benign)
