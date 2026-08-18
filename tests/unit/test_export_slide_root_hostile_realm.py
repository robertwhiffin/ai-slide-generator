"""The slide-root walk must terminate in a HOSTILE JS realm, not just in a DOM.

bcb87fd removed the sidecar's wrapper-depth cap and justified the removal
structurally: every step of the walk moves from a node to its sole ELEMENT
CHILD, so the walk only ever travels down a parent → child chain, and such a
chain is finite and acyclic in any DOM.

That argument is sound about the DOM and unsound about the realm the walk runs
in. Every accessor that answers "what is this element's sole element child" —
``children``, ``firstElementChild``, ``nextElementSibling`` — is a CONFIGURABLE
accessor on ``Element.prototype``, so page script can replace them with ones that
report any node they like, including the node itself. The descent then never
advances and never ends.

REACHABILITY, which is what makes this a defect in our code rather than a
curiosity: ``SLIDE_CSP`` (``src/utils/html_safety.py``) carries
``script-src 'unsafe-inline'``, so inline script in a slide document DOES run in
the export page, at load, before the preprocess pass is evaluated. A malicious —
or merely broken — uploaded template can therefore hang the export worker on a
Playwright page that has no execution budget of its own. That is a denial of
service in the sidecar.

The fixtures wrap hostile scripts around the SAME shape and the SAME single
ground as ``wrapped_nested_bare_slide.html``, so the fix is held to the stronger
of the two available bars wherever it can be: not merely "the pass returns" but
"the pass returns the RIGHT ROOT", proven at the artifact.

Two layers are under test, and they are not the same claim:

  * reading the tree through a PRISTINE realm (a src-less iframe, whose
    intrinsics no page script has touched) — best-effort by nature, since page
    script runs first and can subvert the route to that realm. Correctness.
  * a hard iteration bound — unconditional. Termination.

``hostile_capture_blocked.html`` is the fixture that separates them: it denies the
pristine realm, so only the bound is left, and the expectation drops from "keeps
its ground" to "terminates, loses the ground, and SAYS SO".

A note on what these tests do NOT cover. A hostile realm can also replace a
collection's ``[Symbol.iterator]``, which every ``Array.from(<collection>)`` in
this pass consumed — including, one line above the descent, the loop over this
locator's own wrapper NodeList. That residual is closed, and is pinned by
``test_export_collection_iteration_hostile_realm.py``; what stays open there is
the same defect in the vendored walker, ``html2pptx.js``. (The line numbers this
note used to carry were correct when written and stale two commits later; the
sibling suite names functions and sites instead.)

Gating matches the sibling export suites: needs ``node``, the extracted sidecar
``node_modules`` (run ``setup.sh``) and a local Chrome/Chromium.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from src.services import pptx_from_html_huashu
from tests.unit.test_export_slide_root_background import (
    FIXTURE_DIR,
    GROUND,
    GROUND_RGB,
    LOST,
    PROBE_SCRIPT,
    _build,
    _slide_background,
    requires_huashu_sidecar,
)
from tests.unit.test_export_svg_raster import structural_manifest

# Hostile documents whose ground must SURVIVE — the pristine read is available to
# them, so a poisoned realm costs the deck nothing.
#
#   hostile_children_self   every accessor reports the node itself, so the
#                           descent never advances (the reported repro).
#   hostile_children_fresh  every accessor reports a BRAND-NEW node, so the walk
#                           never revisits anything. This is the case a
#                           visited-set alone does not terminate.
RESOLVING_FIXTURES = ("hostile_children_self", "hostile_children_fresh")

# The hostile document that also denies the pristine realm: termination only.
CAPTURE_BLOCKED = "hostile_capture_blocked"

# Every hostile document must terminate, whatever else it costs.
TERMINATING_FIXTURES = RESOLVING_FIXTURES + (CAPTURE_BLOCKED,)

# The child accessors each fixture replaces.
POISONED_ACCESSORS = ("children", "firstElementChild", "nextElementSibling")

# The benign fixture the resolving ones are built around: same shape, same single
# ground, same expected artifact.
BENIGN_TWIN = "wrapped_nested_bare_slide.html"

# Bound on the preprocess pass for these documents. The walk is single-digit
# milliseconds at wrapper depth 509 (see test_export_slide_root_depth.py), so five
# seconds is not a performance assertion — it is the line between "terminates" and
# "does not", made finite so a hang is a test failure instead of a hung suite.
EVALUATE_TIMEOUT_MS = 5000


def _probe_bounded(*fixtures: str) -> dict[str, dict]:
    """Probe with the preprocess pass BOUNDED, keyed by fixture stem.

    ``PROBE_EVALUATE_TIMEOUT_MS`` makes the sidecar probe report
    ``timedOut: true`` rather than waiting on a pass that never returns, which is
    what lets non-termination be asserted as ordinary data.
    """
    env = pptx_from_html_huashu.sidecar_subprocess_env()
    env["PROBE_EVALUATE_TIMEOUT_MS"] = str(EVALUATE_TIMEOUT_MS)
    proc = subprocess.run(
        ["node", str(PROBE_SCRIPT), *[str(FIXTURE_DIR / f"{f}.html") for f in fixtures]],
        cwd=pptx_from_html_huashu.SIDECAR_DIR,
        env=env,
        capture_output=True,
        text=True,
        # Generous relative to the per-document bound: enough for browser startup
        # plus every document, so this timeout never front-runs the in-page bound
        # the test is actually measuring.
        timeout=pptx_from_html_huashu.SIDECAR_TIMEOUT_SECONDS,
    )
    assert proc.returncode == 0, f"probe failed: {proc.stderr}"
    results = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    return {result["file"].removesuffix(".html"): result for result in results}


@requires_huashu_sidecar
class TestHostileRealmIsActuallyHostile:
    """Before asserting anything about the walk: prove the fixtures bite.

    A poisoning the browser silently refused would make every assertion in this
    module vacuous — the pass would terminate because there was never anything
    wrong with the realm. Each fixture publishes what it managed to do on
    ``document.title``, read before the pass runs.
    """

    @pytest.mark.parametrize("fixture", TERMINATING_FIXTURES)
    def test_every_child_accessor_is_replaceable_and_was_replaced(
        self, fixture: str
    ) -> None:
        report = json.loads(_probe_bounded(fixture)[fixture]["title"])

        assert report["redefineResult"] == "ok", f"{fixture}: {report}"
        for accessor in POISONED_ACCESSORS:
            assert report["configurable"].get(accessor) is True, (
                f"{fixture}: Element.prototype.{accessor} was not configurable, "
                f"so the fixture could not poison it: {report}"
            )

    def test_the_route_to_a_pristine_realm_is_replaceable_too(self) -> None:
        """The premise of ``hostile_capture_blocked``: ``contentWindow`` gives way."""
        report = json.loads(_probe_bounded(CAPTURE_BLOCKED)[CAPTURE_BLOCKED]["title"])

        assert report["redefineResult"] == "ok"
        assert report["configurable"]["contentWindow"] is True


@requires_huashu_sidecar
class TestHostileRealmTermination:
    """The pass must return. This is the denial-of-service fix itself."""

    @pytest.mark.parametrize("fixture", TERMINATING_FIXTURES)
    def test_a_poisoned_child_accessor_does_not_hang_the_export(
        self, fixture: str
    ) -> None:
        """RED before the fix: the pass never returns and this times out."""
        result = _probe_bounded(fixture)[fixture]

        assert result["timedOut"] is False, (
            f"{fixture}: the preprocess pass did not terminate within "
            f"{EVALUATE_TIMEOUT_MS}ms — the slide-root walk is non-terminating in "
            "a hostile realm"
        )


@requires_huashu_sidecar
class TestHostileRealmStillResolvesTheRealRoot:
    """Terminating is the floor; reading the REAL tree is the bar.

    Stopping the hang by giving up on the walk would export white — a hostile page
    script would still get to break the deck, just more quietly. These pin the
    stronger outcome: the walk resolves the same root it resolves in a clean
    realm, so the poisoning costs the deck nothing.
    """

    @pytest.mark.parametrize("fixture", RESOLVING_FIXTURES)
    def test_the_solid_ground_branch_still_runs(self, fixture: str) -> None:
        result = _probe_bounded(fixture)[fixture]

        assert result["bgTransferred"] == "solid", (
            f"{fixture}: locator took the '{result['bgTransferred']}' branch"
        )
        assert result["bodyBackgroundColor"] == GROUND_RGB

    @pytest.mark.parametrize("fixture", RESOLVING_FIXTURES)
    def test_the_ground_reaches_the_artifact(
        self, monkeypatch: pytest.MonkeyPatch, fixture: str
    ) -> None:
        """Measured on the .pptx, not the DOM — the export is the deliverable."""
        assert _slide_background(_build(monkeypatch, f"{fixture}.html")) == GROUND

    @pytest.mark.parametrize("fixture", RESOLVING_FIXTURES)
    def test_the_hostile_deck_exports_as_the_benign_deck(
        self, monkeypatch: pytest.MonkeyPatch, fixture: str
    ) -> None:
        """The hostile script must cost the artifact nothing at all.

        Each fixture differs from ``wrapped_nested_bare_slide.html`` by its
        ``<script>`` and nothing else, so comparing the two artifacts from one run
        attributes any difference to the hostile script alone. Stronger than a
        colour assertion: it also catches a fix that resolves the right root but
        perturbs the rest of the pass on the way.
        """
        hostile = _build(monkeypatch, f"{fixture}.html")
        benign = _build(monkeypatch, BENIGN_TWIN)

        assert structural_manifest(hostile) == structural_manifest(benign)


@requires_huashu_sidecar
class TestNoTrustworthyReadDegradesLoudly:
    """When even the pristine realm is denied, what is left must be honest.

    Correctness is not recoverable here — there is no trustworthy way left to read
    the tree — so the deck exports white. The claims worth pinning are that it
    STOPS, and that it does not do so silently.
    """

    def test_it_terminates_and_reports_no_root(self) -> None:
        result = _probe_bounded(CAPTURE_BLOCKED)[CAPTURE_BLOCKED]

        assert result["timedOut"] is False
        assert result["bgTransferred"] == "no-root"

    def test_the_artifact_is_the_untouched_body_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """White, not invented, and not a crash: the same outcome as no root."""
        assert _slide_background(_build(monkeypatch, f"{CAPTURE_BLOCKED}.html")) == LOST
