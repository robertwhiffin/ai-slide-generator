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
    inlineBgs              inline element with a background             866  FENCED

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

# The one sub-pass still driven by a raw accessor, because it lives inside
# emitInlineBackgrounds, which this change is instructed to leave byte-identical.
FENCED_SUB_PASS = "inlineBgs"

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

# The residual is NOT a smaller version of the same defect, which is why these
# carry the whole failure mode rather than a weakened one. A poisoned forEach
# ignores its receiver, so the raw site at preprocess.mjs:866 spins on ANY
# document — an empty 'span, mark, kbd' NodeList still calls it. The hang and the
# raise are therefore open for EVERY deck while that line stands.
#
# strict, so that closing it fails this suite instead of quietly leaving a stale
# marker behind: the marker is removed by the change that hardens line 866.
fenced_by_emit_inline_backgrounds = pytest.mark.xfail(
    strict=True,
    reason=(
        "preprocess.mjs:866 consumes document.querySelectorAll(SELECTOR) with the "
        "realm's NodeList.prototype.forEach. That line is inside "
        "emitInlineBackgrounds, which this change is instructed to leave "
        "byte-identical, so the site is disclosed rather than closed. Remove this "
        "marker with that fix."
    ),
)


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

        Probed in ONE run so both documents share a browser. The fenced sub-pass
        is excluded here and asserted on its own below, so that this expectation
        states exactly what the change closed and nothing it did not.
        """
        probed = _probe_bounded(fixture, BENIGN)
        hostile = dict(probed[fixture]["counts"])
        benign = dict(probed[BENIGN]["counts"])
        hostile.pop(FENCED_SUB_PASS)
        benign.pop(FENCED_SUB_PASS)

        assert hostile == benign

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

        Asserted as the ABSENCE of that specific failure rather than as a clean
        pass, because the fenced site still raises further down the same run: the
        claim here is that the locator's collection read is no longer what breaks,
        which is exactly what reverting that one site would undo.
        """
        result = _probe_bounded("hostile_wrapper_selector_all")[
            "hostile_wrapper_selector_all"
        ]

        assert "Illegal invocation" not in (result["error"] or ""), (
            "the wrapper collection is still read through the realm's own "
            f"querySelectorAll: {result['error']!r}"
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
class TestTheFencedSiteIsTheOnlyResidual:
    """What the fence costs, stated as expectations rather than prose.

    Asserted through the bounded probe rather than a real export: a hang costs
    the probe its 5s bound instead of the sidecar's 180s timeout, so disclosing
    the residual does not make the suite expensive.
    """

    @fenced_by_emit_inline_backgrounds
    def test_an_endless_foreach_does_not_hang_the_pass(self) -> None:
        result = _probe_bounded("hostile_foreach_endless")["hostile_foreach_endless"]

        assert result["timedOut"] is False, (
            "hostile_foreach_endless: the preprocess pass did not terminate "
            f"within {EVALUATE_TIMEOUT_MS}ms — an endless NodeList.prototype."
            "forEach is still consumed somewhere in the pass"
        )

    @fenced_by_emit_inline_backgrounds
    def test_a_decoy_query_selector_all_does_not_raise(self) -> None:
        result = _probe_bounded("hostile_selector_all_decoy")[
            "hostile_selector_all_decoy"
        ]

        assert result["error"] is None, (
            f"hostile_selector_all_decoy: the preprocess pass raised "
            f"{result['error']!r} — a querySelectorAll result is still consumed "
            "through the realm's own prototype somewhere in the pass"
        )

    @fenced_by_emit_inline_backgrounds
    def test_a_silent_foreach_costs_the_deck_no_content_at_all(self) -> None:
        """The fenced sub-pass, excluded from the parity claim above.

        Separate from that claim so neither is weakened: that one states what the
        change closed, this one states what the fence left open.
        """
        probed = _probe_bounded("hostile_foreach_silent", BENIGN)

        assert (
            probed["hostile_foreach_silent"]["counts"][FENCED_SUB_PASS]
            == probed[BENIGN]["counts"][FENCED_SUB_PASS]
        )
