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

THE VENDORED WALKER IS NOW HARDENED TOO, which is why the artifact claims below
are ordinary expectations. Hardening ``preprocess.mjs`` alone made the PASS
return but not the EXPORT complete, because the vendored huashu walker had the
same defect one file over — and line 652 runs for every element the text walker
visits, so both fixtures hung there regardless of the preprocess fix:

    html2pptx.js  447  element.childNodes.forEach(...)        NodeList
                  576  document.querySelectorAll('*').forEach HTMLCollection
                  652  for (const node of el.childNodes)      NodeList
                  791  Array.from(el.querySelectorAll('li'))  NodeList
                  896  el.querySelector('b, i, u, ...')       Element lookup

All five now read through the same mechanism ``preprocess.mjs`` uses: accessors
captured from a src-less iframe's pristine realm, consumed by walking the sibling
chain or indexing under a bound. The measured effect on this module is four
sidecar timeouts becoming four passes, and the suite going from 109s to under
20s. These two claims carried ``xfail(strict=True)`` while the walker was open;
the strictness is what turned the fix into a failing test and made the markers'
removal owed rather than optional.

WHAT IS STILL NOT REACHED, measured rather than assumed. One raw site remains in
``preprocess.mjs``, inside ``emitInlineBackgrounds``:

    preprocess.mjs 866  document.querySelectorAll(SELECTOR).forEach(...)

That function is fenced off from this change by explicit instruction, so the site
is disclosed rather than closed. It is not a partial residual: a poisoned
``forEach`` ignores its receiver, so that line spins on ANY document — an empty
``span, mark, kbd`` NodeList still calls it — which leaves the hang and the raise
open for every deck, not only for decks carrying an inline background. The
sibling module ``test_export_accessor_hostile_realm.py`` states that residual as
its own strict expectations, so it fails the moment the fence is lifted.

Gating matches the sibling export suites: needs ``node``, the extracted sidecar
``node_modules`` (run ``setup.sh``) and a local Chrome/Chromium.
"""

from __future__ import annotations

import json

import pytest

from src.services import pptx_from_html_huashu
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

# Long enough to be a real export of a two-element slide (the hostile twins finish
# in a couple of seconds now that the walker terminates), short enough that a
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
