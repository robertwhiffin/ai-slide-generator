"""Consuming a live DOM collection must terminate in a HOSTILE JS realm.

5d9229a hardened the slide-root DESCENT against a realm that lies about an
element's children, and said in as many words what it was leaving behind:
``Array.from(NodeList)`` consumes ``NodeList.prototype[Symbol.iterator]``, which
a hostile realm can make endless. This is that residual.

The defect is one layer up from the descent and in six more places than the
disclosure named. ``Array.from()`` — like spread, and like ``for...of`` — reads
the collection's ``[Symbol.iterator]``, and that property is CONFIGURABLE on both
``NodeList.prototype`` and ``HTMLCollection.prototype``. An iterator that never
reports ``done`` therefore stops the pass at whichever of these it reaches first:

    preprocess.mjs  45   Array.from(panel.children)          HTMLCollection
                    53   Array.from(panel.childNodes)        NodeList
                    59   Array.from(child.childNodes)        NodeList
                    140  Array.from(parent.childNodes)       NodeList
                    381  for (const wrapper of wrappers)     NodeList
                    864  Array.from(querySelectorAll('img')) NodeList
                    921  Array.from(querySelectorAll('svg')) NodeList

REACHABILITY is the same as the sibling suite's and no weaker: ``SLIDE_CSP``
(``src/utils/html_safety.py``) carries ``script-src 'unsafe-inline'``, so inline
script in an uploaded template runs in the export page at load, before this pass.
Line 140 is reached for every ``<div>``, ``<pre>`` and ``<code>`` in the document,
so unlike the locator's own read this one is on the path of EVERY deck — the
residual is more reachable than the layer already fixed.

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

The two fixtures split the file's collection reads by LAYER:

  hostile_wrapper_iterator      the wrapper shape, so the locator's own
                                collection read is what the pass reaches (381).
  hostile_collection_passes     a shape the locator resolves on its first lookup,
                                so the pass runs on into the reads a hardened
                                locator cannot help (45, 53, 59, 140, 864, 921).

Each is a byte-identical copy of a BENIGN twin plus its ``<script>``, so any
difference in the artifact is attributable to the hostile script alone. That is
also what makes the second fixture pin every site at once rather than only the
first: its twin's export depends on all four of its collection reads — the
monospace panel, the prose div, the ``<svg>`` and the ``<img>`` — so the artifact
matches only when every one of them yields the same elements in the same order.

WHAT THIS FIX DOES NOT REACH, measured rather than assumed. Hardening
``preprocess.mjs`` makes the PASS return — proven above at the pass's own
boundary, in single-digit milliseconds and with the same counts as the benign
twin — but it does not make the EXPORT complete, because the vendored huashu
walker has the same defect one file over:

    html2pptx.js  652  for (const node of el.childNodes)     NodeList
                  791  Array.from(el.querySelectorAll('li')) NodeList
                  1025 Array.from(querySelectorAll('canvas')) NodeList

Line 652 runs for every element the text walker visits, so both fixtures still
hang the export there. Measured, not inferred: changing that ONE line to an index
loop takes this module's artifact tests from four 180s sidecar timeouts to seven
passes in 13s. It is left alone here because it is a different file and this
change is confined to the collection reads in ``preprocess.mjs``; the artifact
claims below are therefore ``xfail(strict=True)``, which documents the residual
and turns into a failure the moment the walker is fixed and the markers are owed
removal.

Gating matches the sibling export suites: needs ``node``, the extracted sidecar
``node_modules`` (run ``setup.sh``) and a local Chrome/Chromium.
"""

from __future__ import annotations

import json

import pytest

from tests.unit.test_export_slide_root_background import (
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

from src.services import pptx_from_html_huashu

# The export cannot complete while html2pptx.js:652 consumes el.childNodes with
# for...of — see the module docstring. strict, so that fixing the walker fails
# this suite instead of quietly leaving a stale marker behind.
blocked_on_the_vendored_walker = pytest.mark.xfail(
    strict=True,
    raises=pptx_from_html_huashu.HuashuExportError,
    reason=(
        "html2pptx.js:652 walks el.childNodes with for...of, so the hostile "
        "iterator still hangs the export downstream of the preprocess pass. "
        "Out of scope here: a different file. Remove this marker with that fix."
    ),
)

# Long enough to be a real export of a two-element slide (the benign twins finish
# in a couple of seconds), short enough that four blocked cases cost the suite
# 100s instead of the 180s-per-case the production timeout would.
BLOCKED_EXPORT_TIMEOUT_SECONDS = 25

# Each hostile fixture and the benign twin it must export identically to.
TWINS = {
    "hostile_wrapper_iterator": "wrapped_nested_bare_slide",
    "hostile_collection_passes": "collection_passes",
}

HOSTILE_FIXTURES = tuple(TWINS)

# The two interfaces whose [Symbol.iterator] the fixtures replace. Both, because
# the pass consumes both: childNodes and querySelectorAll() are NodeLists,
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
    def test_every_pass_reports_the_same_counts_as_the_benign_twin(
        self, fixture: str
    ) -> None:
        """Same elements, per pass, measured as the counts the pass returns.

        Probed in ONE run so the two documents share a browser, and compared as a
        whole object so a collection read that silently returned fewer elements
        shows up as a smaller count rather than having to be predicted here.
        """
        twin = TWINS[fixture]
        probed = _probe_bounded(fixture, twin)

        assert probed[fixture]["counts"] == probed[twin]["counts"]

    @blocked_on_the_vendored_walker
    @pytest.mark.parametrize("fixture", HOSTILE_FIXTURES)
    def test_the_ground_reaches_the_artifact(
        self, monkeypatch: pytest.MonkeyPatch, fixture: str
    ) -> None:
        """Measured on the .pptx, not the DOM — the export is the deliverable."""
        monkeypatch.setattr(
            pptx_from_html_huashu,
            "SIDECAR_TIMEOUT_SECONDS",
            BLOCKED_EXPORT_TIMEOUT_SECONDS,
        )

        assert _slide_background(_build(monkeypatch, f"{fixture}.html")) == GROUND

    @blocked_on_the_vendored_walker
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
            BLOCKED_EXPORT_TIMEOUT_SECONDS,
        )
        hostile = _build(monkeypatch, f"{fixture}.html")
        benign = _build(monkeypatch, f"{TWINS[fixture]}.html")

        assert structural_manifest(hostile) == structural_manifest(benign)
