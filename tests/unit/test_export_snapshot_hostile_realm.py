"""Snapshot engine: the text walk in a HOSTILE JS realm.

``SLIDE_CSP`` carries ``script-src 'unsafe-inline'``, so inline script in an
uploaded slide runs in the export page before the snapshot does. The sibling
hostile-realm suites (``test_export_*_hostile_realm.py``) pin the background
transfer and the settle reads. This module pins the snapshot's text walk, which
reads child NODES (text included), each node's type and each text node's
characters, and measures every word with a ``Range``. Each of those reads is a
configurable property page script can replace.

* ``hostile_text_nodes`` replaces every node-level read the text walk could make:
  ``firstChild`` and ``nextSibling`` return the node itself, ``nodeType`` is
  always 3, ``childNodes`` claims a billion entries, and ``textContent`` and
  ``CharacterData.data`` return a decoy. The walk reads through the pristine
  realm's accessors in ``dom_access.mjs``, so the deck must export exactly as its
  benign twin ``collection_passes`` does.
* ``hostile_range_rects`` makes ``Range.getClientRects`` report a trillion rects.
  Correctness is forfeit (no rect is real), but the export must terminate and
  announce the loss with the ``[html2pptx] collection`` line.
* Every other hostile fixture of the sibling suites must terminate, and the two
  twins of the collection-iteration suite must export identically.

Each fixture is a byte-identical copy of its benign twin plus its ``<script>``,
which publishes on ``document.title`` what it managed to replace and what a
reader of the realm now sees, so the poisoning is proven rather than assumed.
Every export goes through the model check's zero-drop guard
(``export_documents``): a twin pair whose models both lose the same item would
otherwise still compare equal.
"""

from __future__ import annotations

import json

import pytest

from src.services import pptx_from_html_huashu
from tests.fixtures.export_snapshot_support import export_documents
from tests.unit.test_export_collection_iteration_hostile_realm import (
    HOSTILE_EXPORT_TIMEOUT_SECONDS,
)
from tests.unit.test_export_slide_root_background import FIXTURE_DIR, requires_huashu_sidecar
from tests.unit.test_export_slide_root_hostile_realm import _probe_bounded
from tests.unit.test_export_svg_raster import structural_manifest

EXPORT_TITLE = "snapshot hostile realm"

TEXT_NODES = "hostile_text_nodes"
RANGE_RECTS = "hostile_range_rects"

# Each hostile fixture and the benign twin it must export identically to: this
# module's text-node fixture, then the collection-iteration suite's twins.
SNAPSHOT_TWINS = {
    TEXT_NODES: "collection_passes",
    "hostile_collection_passes": "collection_passes",
    "hostile_wrapper_iterator": "wrapped_nested_bare_slide",
}

# Every other hostile fixture: its export must terminate.
TERMINATION_FIXTURES = tuple(
    sorted(
        path.stem
        for path in FIXTURE_DIR.glob("hostile_*.html")
        if path.stem not in SNAPSHOT_TWINS and path.stem != RANGE_RECTS
    )
)

# What each of this module's fixtures replaces, as "<prototype>.<property>".
POISONED = {
    TEXT_NODES: (
        "Node.firstChild",
        "Node.nextSibling",
        "Node.nodeType",
        "Node.childNodes",
        "Node.textContent",
        "CharacterData.data",
    ),
    RANGE_RECTS: ("Range.getClientRects",),
}

# The line reportCollectionLoss prints when a bound is met, as the sidecar echoes it.
COLLECTION_LOSS_LINE = "[html2pptx] collection"
# Where the text layout's own budget says it was met (snapshot_text.mjs spend).
TEXT_LAYOUT_BUDGET = "in the snapshot text layout"


def _export_snapshot(
    monkeypatch: pytest.MonkeyPatch, fixture: str, *, debug_text: bool = False
) -> tuple[bytes, list[dict]]:
    """Export one fixture slide, bounded so a hang fails in seconds, its model whole.

    A sidecar that does not finish within ``HOSTILE_EXPORT_TIMEOUT_SECONDS`` raises
    ``HuashuExportError``; a slide model the model check dropped part of fails
    the export (``export_documents``). ``debug_text`` logs what the page logs,
    the engine's own page-side lines among it.
    """
    monkeypatch.setattr(
        pptx_from_html_huashu, "SIDECAR_TIMEOUT_SECONDS", HOSTILE_EXPORT_TIMEOUT_SECONDS
    )
    html = (FIXTURE_DIR / f"{fixture}.html").read_text(encoding="utf-8")
    return export_documents(
        [html], monkeypatch=monkeypatch, title=EXPORT_TITLE, debug_text=debug_text
    )


def test_every_other_hostile_fixture_is_covered() -> None:
    """The termination set is derived from the fixture directory; it must not come up empty."""
    assert TERMINATION_FIXTURES, f"no hostile fixtures found in {FIXTURE_DIR}"


@pytest.mark.slow
@requires_huashu_sidecar
class TestThePoisoningIsActuallyHostile:
    """Before asserting anything else: prove the fixtures bite.

    A replacement the browser refused would make every expectation below vacuous.
    Each fixture publishes, on ``document.title``, whether each property was
    configurable, whether redefining it succeeded, and what a reader of the
    realm now sees through it.
    """

    @pytest.mark.parametrize("fixture", tuple(POISONED))
    def test_every_read_is_replaceable_and_was_replaced(self, fixture: str) -> None:
        report = json.loads(_probe_bounded(fixture)[fixture]["title"])

        assert report["redefineResult"] == "ok", f"{fixture}: {report}"
        for name in POISONED[fixture]:
            assert report["configurable"].get(name) is True, (
                f"{fixture}: {name} was not configurable, so the fixture could not "
                f"replace it: {report}"
            )
        # Each replacement, keyed by its property, took effect for a reader of the realm.
        replaced = {name.split(".", 1)[1] for name in POISONED[fixture]}
        assert set(report["bites"]) == replaced, (
            f"{fixture}: the fixture checks {sorted(report['bites'])}, it replaces {sorted(replaced)}"
        )
        untaken = sorted(name for name in replaced if report["bites"][name] is not True)
        assert not untaken, (
            f"{fixture}: these replacements did not take effect for a reader of the realm: {untaken}"
        )


@pytest.mark.slow
@requires_huashu_sidecar
class TestTheTextWalkReadsThePristineTree:
    """The hostile deck exports as the benign deck: the whole artifact, not just its text."""

    @pytest.mark.parametrize("fixture", tuple(SNAPSHOT_TWINS))
    def test_the_hostile_deck_exports_as_the_benign_deck(
        self, monkeypatch: pytest.MonkeyPatch, fixture: str
    ) -> None:
        hostile, hostile_failures = _export_snapshot(monkeypatch, fixture)
        benign, benign_failures = _export_snapshot(monkeypatch, SNAPSHOT_TWINS[fixture])

        assert hostile_failures == [] and benign_failures == [], (
            f"{fixture}: the export rejected a slide: {hostile_failures} / {benign_failures}"
        )
        assert structural_manifest(hostile) == structural_manifest(benign), (
            f"{fixture} does not export as its benign twin {SNAPSHOT_TWINS[fixture]}"
        )


@pytest.mark.slow
@requires_huashu_sidecar
class TestTheSnapshotEngineTerminates:
    """Termination only: correctness may be forfeit, the export may not hang."""

    @pytest.mark.parametrize("fixture", TERMINATION_FIXTURES)
    def test_the_export_returns(self, monkeypatch: pytest.MonkeyPatch, fixture: str) -> None:
        pptx, failures = _export_snapshot(monkeypatch, fixture)

        assert pptx or failures, (
            f"{fixture}: the sidecar returned neither a .pptx nor per-slide failures"
        )

    def test_a_range_that_lies_about_its_rects_is_bounded_and_announced(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``getClientRects()`` claims a trillion rects: the text walk's budget ends the reads.

        The export returns within the bound, and the loss is announced on stderr,
        because the text past the bound is missing from the deck.
        """
        pptx, failures = _export_snapshot(monkeypatch, RANGE_RECTS, debug_text=True)

        assert pptx and failures == [], f"the export did not complete: {failures}"
        stderr = capsys.readouterr().err
        lines = [line for line in stderr.splitlines() if COLLECTION_LOSS_LINE in line]
        assert lines, f"the text walk met its bound without announcing it; sidecar stderr:\n{stderr}"
        assert any(TEXT_LAYOUT_BUDGET in line for line in lines), (
            f"the bound met is not the text layout's own ({TEXT_LAYOUT_BUDGET!r}): {lines}"
        )
