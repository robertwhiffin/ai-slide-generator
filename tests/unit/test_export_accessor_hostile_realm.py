"""Reading the DOM must survive a realm that replaced the ACCESSORS.

``ef67a38`` closed the collection-ITERATOR vector: ``Array.from``, spread and
``for...of`` all read ``[Symbol.iterator]``, which page script can make endless.
This module is the vector that survived it, and it is a different property.

``NodeList.prototype.forEach`` is its own CONFIGURABLE own property. A document
that leaves ``[Symbol.iterator]`` entirely alone can still replace ``forEach``,
and every ``document.querySelectorAll(...).forEach(...)`` in the preprocess pass
then does whatever that replacement does. So can the LOOKUPS themselves:
``querySelector`` and ``querySelectorAll`` are configurable own properties of
``Document.prototype`` and ``Element.prototype`` — and those are DISTINCT function
objects, a Document one invoked on an element throwing *Illegal invocation*, so
hardening one leaves the other exactly as open as before.

REACHABILITY is the sibling suites' and no weaker: ``SLIDE_CSP``
(``src/utils/html_safety.py``) carries ``script-src 'unsafe-inline'``, so inline
script in an uploaded slide runs in the export page at load, before this pass.

FOUR measured failure modes, which is why the expectations below are not merely
"did not hang":

  * a HANG — an endless ``forEach`` spins, denying service in a sidecar that has
    no execution budget of its own.
  * SILENT CONTENT LOSS — a no-op ``forEach`` lets the pass return promptly and
    report success with sub-passes that did nothing. No timeout catches this and
    no artifact explains it, which is why it is asserted on the pass's own
    per-sub-pass COUNTS.
  * a WRONG DOCUMENT — a decoy-returning ``querySelector`` makes the slide-root
    locator resolve an element that is not in the document. The ground then goes
    transparent, and ``rgbToHex`` in html2pptx.js resolves a transparent body to
    WHITE, so the deck exports white: the exact surfaces-disagree failure the
    slide-root work exists to prevent, reached by another route.
  * a RAISE — a ``querySelectorAll`` returning something that is not a NodeList
    takes the whole pass down.

The fixtures are PURE ADDITIONS to one benign twin, ``every_collection_pass``,
which is built to drive EVERY sub-pass to a non-zero count. That is what gives
per-site attribution rather than a single pass/fail: each count below is produced
by exactly one collection read, so reverting one site drops exactly one count.

    bgTransferred          the slide-root lookups        preprocess.mjs 461, 477
    (wrappers)             the wrapper collection                       464
    codeBlocks             monospace panel                              40
    wrapped                bare inline text in a div                    180
    replacedImgs           div with a background-image                  603
    peeledTextTags         <p> carrying a background                    640
    tableCells             table + its th/td                            681, 682
    canvasImgs             <canvas>                                     890
    svgImgsRasterized      <img> with an svg data URI                   955
    inlineSvgsRasterized   inline <svg>                                 1012
    inlineBgs              inline element with a background             866

Gating matches the sibling export suites: needs ``node``, the extracted sidecar
``node_modules`` (run ``setup.sh``) and a local Chrome/Chromium.
"""

from __future__ import annotations

import json

import pytest

from tests.unit.test_export_slide_root_background import (
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

# The sub-pass inside emitInlineBackgrounds. It was the last site reading through
# the realm's own prototype, so it is stated on its own below as well as in the
# aggregate parity claim, rather than only in the aggregate.
INLINE_BG_SUB_PASS = "inlineBgs"

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
class TestTheBenignTwinDrivesEverySubPass:
    """The instrument itself, asserted rather than assumed.

    Every claim below is "the hostile document read the same elements as this
    one". A twin that left a sub-pass at zero would make the corresponding
    comparison vacuously true, so the twin's own counts are pinned first.
    """

    def test_every_sub_pass_reports_a_non_zero_count(self) -> None:
        counts = _probe_bounded(BENIGN)[BENIGN]["counts"]

        assert counts["bgTransferred"] == "solid"
        zeroed = [
            name
            for name, value in counts.items()
            if name != "bgTransferred" and not value
        ]
        assert zeroed == [], (
            f"{BENIGN} leaves these sub-passes at zero, so they cannot attribute "
            f"a regression: {zeroed}"
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
    def test_every_closed_sub_pass_matches_the_benign_twin(self, fixture: str) -> None:
        """Same elements, per sub-pass, measured as the counts the pass returns.

        Probed in ONE run so both documents share a browser. EVERY sub-pass is
        compared, ``inlineBgs`` included: the exclusion that used to sit here
        existed only because ``emitInlineBackgrounds`` was fenced, and closing
        that site is what removed the reason for it.
        """
        probed = _probe_bounded(fixture, BENIGN)

        assert probed[fixture]["counts"] == probed[BENIGN]["counts"]

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
        read would bring back. The clean pass is then asserted as well — while
        ``emitInlineBackgrounds`` was fenced this fixture still raised further down
        the same run, so a clean pass could not be claimed; closing that site is
        what makes the stronger statement true.
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
class TestTheLastSiteIsClosed:
    """``emitInlineBackgrounds``, which was the one site left reading raw.

    It was fenced when the sibling sites were hardened, and these three
    expectations were the disclosure of what that cost: a poisoned ``forEach``
    ignores its receiver, so the raw site spun on ANY document — an empty
    ``'span, mark, kbd'`` NodeList still called it — leaving the hang and the
    raise open for EVERY deck. The site now reads through ``queryAll``, so they
    are ordinary passing expectations.

    Asserted through the bounded probe rather than a real export: a hang costs
    the probe its 5s bound instead of the sidecar's 180s timeout, so a
    regression here stays cheap to catch.
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

    def test_a_silent_foreach_costs_the_deck_no_content_at_all(self) -> None:
        """This sub-pass on its own, named rather than only inside the aggregate.

        The parity claim above now covers ``inlineBgs`` too, so this overlaps it
        deliberately: a no-op ``forEach`` is the failure mode that reports SUCCESS,
        and the count it silently zeroes is worth naming in a test of its own.
        """
        probed = _probe_bounded("hostile_foreach_silent", BENIGN)

        assert (
            probed["hostile_foreach_silent"]["counts"][INLINE_BG_SUB_PASS]
            == probed[BENIGN]["counts"][INLINE_BG_SUB_PASS]
        )
