"""Reading the DOM must survive a realm that replaced the ACCESSORS.

``ef67a38`` closed the collection-ITERATOR vector: ``Array.from``, spread and
``for...of`` all read ``[Symbol.iterator]``, which page script can make endless.
This module is the vector that survived it, and it is a different property.

``NodeList.prototype.forEach`` is its own CONFIGURABLE own property. A document
that leaves ``[Symbol.iterator]`` entirely alone can still replace ``forEach``,
and every ``document.querySelectorAll(...).forEach(...)`` then does whatever
that replacement does. So can the LOOKUPS themselves: ``querySelector`` and
``querySelectorAll`` are configurable own properties of ``Document.prototype``
and ``Element.prototype`` — and those are DISTINCT function objects, a Document
one invoked on an element throwing *Illegal invocation*, so hardening one leaves
the other exactly as open as before. Every page-side read therefore goes through
the pristine-realm lookups of ``dom_access.mjs``.

REACHABILITY is the sibling suites' and no weaker: ``SLIDE_CSP``
(``src/utils/html_safety.py``) carries ``script-src 'unsafe-inline'``, so inline
script in an uploaded slide runs in the export page at load, before any pass.

FOUR measured failure modes, which is why the expectations below are not merely
"did not hang":

  * a HANG — an endless ``forEach`` spins, denying service in a sidecar that has
    no execution budget of its own.
  * SILENT CONTENT LOSS — a no-op ``forEach`` lets a read return promptly and
    report success having read nothing. No timeout catches this and no failure
    explains it, which is why it is asserted on the COUNTS the export reports
    and on the deck itself.
  * a WRONG DOCUMENT — a decoy-returning ``querySelector`` makes the slide-root
    locator resolve an element that is not in the document. The ground then
    never reaches body, and a slide without one exports WHITE: the exact
    surfaces-disagree failure the slide-root work exists to prevent, reached by
    another route.
  * a RAISE — a ``querySelectorAll`` returning something that is not a NodeList
    takes the whole pass down.

The fixtures are PURE ADDITIONS to one benign twin, ``every_collection_pass``,
which holds one of every kind of thing the snapshot reads: a heading, prose
and a monospace panel (text), a ``<div>`` with a background image, an SVG
data-URI ``<img>``, an inline ``<svg>`` and a ``<canvas>`` (pictures), a ``<p>``
and an inline element with a background (shapes), and a table. Each
hostile document is compared with it through the background transfer's result
(``{bgTransferred}``), the snapshot's slide summary (every count it reports, but
the clock reading ``captureMs``) and the whole exported deck.

Gating matches the sibling export suites: needs ``node``, the extracted sidecar
``node_modules`` (run ``setup.sh``) and a local Chrome/Chromium.
"""

from __future__ import annotations

import json

import pytest

from tests.fixtures.export_snapshot_support import (
    export_logged,
    slide_summaries,
    summary_without_clock,
)
from tests.unit.test_export_slide_root_background import (
    FIXTURE_DIR,
    GROUND_RGB,
    _build,
    requires_huashu_sidecar,
)
from tests.unit.test_export_slide_root_hostile_realm import (
    EVALUATE_TIMEOUT_MS,
    _probe_bounded,
)
from tests.unit.test_export_svg_raster import structural_manifest

# The benign document every fixture below is a copy of, plus one <script>.
BENIGN = "every_collection_pass"

# The summary counts the benign twin must hold above zero: a count left at zero
# would make the hostile document's equal count vacuous.
TWIN_COUNTS = ("elements", "text", "shapes", "tables", "pictures", "captures")

# Fixtures whose vector is CLOSED: the pass returns and reads the real document.
CLOSED_FIXTURES = ("hostile_foreach_silent", "hostile_selector_decoy")

# Every fixture, with the interfaces each one reports having poisoned. Checked
# before anything else: a poisoning the browser refused would make the
# expectations below vacuous, since the pass would return because there was never
# anything wrong with the realm.
POISONED_INTERFACES = {
    "hostile_foreach_endless": ("NodeList",),
    "hostile_foreach_silent": ("NodeList",),
    "hostile_selector_decoy": ("Document",),
    "hostile_selector_all_decoy": ("Document", "Element"),
}


def _summary(monkeypatch: pytest.MonkeyPatch, fixture: str) -> dict:
    """The slide summary of the fixture's export, without its clock reading."""
    logged = export_logged(
        [(FIXTURE_DIR / f"{fixture}.html").read_text(encoding="utf-8")], monkeypatch=monkeypatch
    )
    assert logged.failures == [], f"{fixture}: {logged.failures}"
    (summary,) = slide_summaries(logged.stderr)
    return summary_without_clock(summary)


@requires_huashu_sidecar
class TestThePoisoningIsActuallyHostile:
    """Before asserting anything else: prove the fixtures bite.

    Each fixture publishes what it managed to do on ``document.title``, read
    before the pass runs — the only moment a document that is about to hang can
    still answer.
    """

    @pytest.mark.parametrize("fixture", sorted(POISONED_INTERFACES))
    def test_the_accessor_is_replaceable_and_was_replaced(self, fixture: str) -> None:
        report = json.loads(_probe_bounded(fixture)[fixture]["title"])

        assert report["redefineResult"] == "ok", f"{fixture}: {report}"
        for interface in POISONED_INTERFACES[fixture]:
            assert report["configurable"].get(interface) is True, (
                f"{fixture}: {interface}.prototype's accessor was not "
                f"configurable, so the fixture could not poison it: {report}"
            )
            assert report["direct"].get(interface) is True, (
                f"{fixture}: {interface}.prototype has no own copy of the "
                f"accessor, so this fixture is not poisoning what the pass "
                f"consumes: {report}"
            )


@requires_huashu_sidecar
class TestTheBenignTwinDrivesEveryCount:
    """The instrument itself, asserted rather than assumed.

    Every claim below is "the hostile document read the same elements as this
    one". A twin that left a count at zero would make the corresponding
    comparison vacuously true, so the twin's own counts are pinned first.
    """

    def test_every_count_is_non_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert _probe_bounded(BENIGN)[BENIGN]["counts"] == {"bgTransferred": "solid"}
        summary = _summary(monkeypatch, BENIGN)
        zeroed = [name for name in TWIN_COUNTS if not summary[name]]
        assert zeroed == [], (
            f"{BENIGN} leaves these counts at zero, so they cannot attribute "
            f"a regression: {zeroed} ({summary})"
        )


@requires_huashu_sidecar
class TestTheClosedSitesReadTheRealDocument:
    """Returning is the floor; reading the REAL document is the bar."""

    @pytest.mark.parametrize("fixture", CLOSED_FIXTURES)
    def test_the_pass_returns(self, fixture: str) -> None:
        result = _probe_bounded(fixture)[fixture]

        assert result["timedOut"] is False, (
            f"{fixture}: the preprocess pass did not terminate within "
            f"{EVALUATE_TIMEOUT_MS}ms"
        )
        assert result["error"] is None, (
            f"{fixture}: the preprocess pass raised {result['error']!r}"
        )

    @pytest.mark.parametrize("fixture", CLOSED_FIXTURES)
    def test_every_count_matches_the_benign_twin(
        self, monkeypatch: pytest.MonkeyPatch, fixture: str
    ) -> None:
        """Same elements, measured as the counts the background transfer and the snapshot report.

        The transfer's result is probed in ONE run so both documents share a
        browser; the slide summaries are compared whole but for ``captureMs``.
        """
        probed = _probe_bounded(fixture, BENIGN)

        assert probed[fixture]["counts"] == probed[BENIGN]["counts"]
        assert _summary(monkeypatch, fixture) == _summary(monkeypatch, BENIGN)

    def test_the_ground_is_the_documents_own_and_not_the_decoy(self) -> None:
        """The positive half of the locator claim.

        A locator reading through a poisoned ``querySelector`` resolves the
        decoy, whose ground is a different synthetic colour. Asserting the
        document's OWN ground is what shows which element actually answered —
        "did not crash" would pass on the decoy too.
        """
        result = _probe_bounded("hostile_selector_decoy")["hostile_selector_decoy"]

        assert result["bgTransferred"] == "solid", (
            f"locator took the '{result['bgTransferred']}' branch"
        )
        assert result["bodyBackgroundColor"] == GROUND_RGB

    def test_the_wrapper_collection_survives_a_poisoned_lookup(self) -> None:
        """The one site every other fixture here cannot reach.

        ``every_collection_pass`` resolves the slide root on the locator's FIRST
        lookup, so nothing built from it exercises the wrapper COLLECTION read.
        This fixture has the wrapper shape, so the read happens — and its
        ``querySelectorAll`` returns a plain array-like, which the pristine
        ``NodeList.prototype.length`` getter refuses with *Illegal invocation*
        when handed a foreign receiver.

        The absence of that SPECIFIC failure is asserted first, because it is the
        attributable half: it is exactly what reverting the locator's collection
        read would bring back. The clean pass is then asserted as well.
        """
        result = _probe_bounded("hostile_wrapper_selector_all")[
            "hostile_wrapper_selector_all"
        ]

        assert "Illegal invocation" not in (result["error"] or ""), (
            "the wrapper collection is still read through the realm's own "
            f"querySelectorAll: {result['error']!r}"
        )
        assert result["error"] is None, (
            f"the pass raised {result['error']!r} on the wrapper-shaped document"
        )

    def test_the_decoy_deck_exports_as_the_benign_deck(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Measured on the .pptx, not the DOM — the export is the deliverable.

        Stronger than the colour assertion above: it also catches a fix that
        keeps the background but perturbs the passes downstream of it.
        """
        hostile = _build(monkeypatch, "hostile_selector_decoy.html")
        benign = _build(monkeypatch, f"{BENIGN}.html")

        assert structural_manifest(hostile) == structural_manifest(benign)


@requires_huashu_sidecar
class TestTheEndlessAndTheSilentForEach:
    """A poisoned ``forEach`` ignores its receiver, so a raw read spins on ANY document.

    An empty NodeList still calls it, which would leave the hang and the raise
    open for EVERY deck. The background transfer is asserted through the bounded
    probe: a hang costs the probe its 5s bound instead of the sidecar's 180s
    timeout, so a regression here stays cheap to catch. The snapshot's reads of
    these documents are held to terminate by test_export_snapshot_hostile_realm.py.
    """

    def test_an_endless_foreach_does_not_hang_the_pass(self) -> None:
        result = _probe_bounded("hostile_foreach_endless")["hostile_foreach_endless"]

        assert result["timedOut"] is False, (
            "hostile_foreach_endless: the preprocess pass did not terminate "
            f"within {EVALUATE_TIMEOUT_MS}ms — an endless NodeList.prototype."
            "forEach is still consumed somewhere in the pass"
        )

    def test_a_decoy_query_selector_all_does_not_raise(self) -> None:
        result = _probe_bounded("hostile_selector_all_decoy")[
            "hostile_selector_all_decoy"
        ]

        assert result["error"] is None, (
            f"hostile_selector_all_decoy: the preprocess pass raised "
            f"{result['error']!r} — a querySelectorAll result is still consumed "
            "through the realm's own prototype somewhere in the pass"
        )

    def test_a_silent_foreach_costs_the_deck_no_content_at_all(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Measured on the .pptx, not on counts: the deck is the benign twin's, entry for entry.

        The count parity above overlaps this deliberately: a no-op ``forEach``
        is the failure mode that reports SUCCESS, and what it would silently
        drop is worth naming in a test of its own.
        """
        hostile = _build(monkeypatch, "hostile_foreach_silent.html")
        benign = _build(monkeypatch, f"{BENIGN}.html")

        assert structural_manifest(hostile) == structural_manifest(benign)
