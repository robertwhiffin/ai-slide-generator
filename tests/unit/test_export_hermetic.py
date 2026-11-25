"""The export suites load nothing from the network (I4).

They used to default to Google Fonts and jsdelivr's Chart.js, live, so their results moved
with the network: Google now and then answers an @import with another font file, and grid
lines moved up to 0.08 px between runs. Now:

* every export a unit test runs is offline: ``tests/unit/conftest.py`` gives the sidecar
  no https host (``SIDECAR_REQUEST_HOSTS``), so its request guard aborts every request a
  slide's page makes but its own file, data: and blob:, and an export whose slides asked
  for anything that was aborted fails its test, naming the slide (a test whose slides
  reach for what the guard aborts, by design, says so: ``requests_blocked``);
* the test documents carry what they load: ``DECK_CSS`` is the corpus deck's CSS with its
  webfonts embedded (``pinned_font_css``), and ``slide_document`` writes the corpus deck's
  Chart.js inline, from a vendored copy (``VENDORED_SCRIPTS``, test-only: no npm
  dependency, and the sidecar's package.json is unchanged);
* ``measure.cjs``, the tests' own browser, loads nothing from the network either, and
  refuses a document that asks;
* a test that means the network is marked ``network``: its export gets the slide CSP's
  hosts, as an app's does, and it skips itself where they cannot be reached.
"""

from __future__ import annotations

import hashlib
import re

import pytest

from src.services import pptx_from_html_huashu
from tests.fixtures.export_snapshot_support import (
    CORPUS_DECK,
    CORPUS_DECK_CSS,
    DECK_CSS,
    VENDORED_SCRIPTS,
    browser_rect,
    corpus_document,
    export_documents,
    export_logged,
    requires_huashu_sidecar,
    slide_document,
    slide_summaries,
)

# What jsdelivr's own index gives as the npm package's dist/chart.umd.js (data.jsdelivr.com,
# chart.js@4.4.1): the file it serves, behind a comment of its own, for the corpus's
# chart.umd.min.js.
CHART_JS_4_4_1_SHA256 = "74401d738dd3e03ee5dfb3b6841210fe2c4ead8a960c4011ca4ba0b78a9fd8f3"
# A resource a document loads from the network: a stylesheet @import, a <link> or a
# <script src>, or a url() in CSS.
NETWORK_RESOURCE = re.compile(
    r"@import\s+url\(['\"]?https?:|<link\b[^>]*\bhref=['\"]https?:|<script\b[^>]*\bsrc=['\"]https?:"
    r"|url\(['\"]?https?:",
    re.IGNORECASE,
)
GOOGLE_FONTS_STYLESHEET = (
    "@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400&display=swap');\n"
)


class TestTheTestDocumentsCarryWhatTheyLoad:
    def test_the_deck_css_loads_no_webfont_from_the_network(self) -> None:
        assert NETWORK_RESOURCE.search(CORPUS_DECK_CSS), "fixture drift: the corpus CSS loads nothing"
        assert not NETWORK_RESOURCE.search(DECK_CSS), NETWORK_RESOURCE.search(DECK_CSS)

    def test_a_corpus_chart_slides_document_loads_nothing_from_the_network(self) -> None:
        assert any(src in VENDORED_SCRIPTS for src in CORPUS_DECK["external_scripts"]), (
            "fixture drift: the corpus deck loads no script the tests vendor"
        )
        document = corpus_document("11")
        assert not NETWORK_RESOURCE.search(document), NETWORK_RESOURCE.search(document)
        assert "Chart.js v4.4.1" in document, "the vendored Chart.js is not inline"

    def test_the_vendored_chart_js_is_the_file_jsdelivr_serves(self) -> None:
        (path,) = set(VENDORED_SCRIPTS.values())
        assert hashlib.sha256(path.read_bytes()).hexdigest() == CHART_JS_4_4_1_SHA256
        assert (path.parent / "LICENSE.md").read_text(encoding="utf-8").startswith("The MIT License")


def test_the_unit_suite_gives_the_sidecar_no_host() -> None:
    assert pptx_from_html_huashu.SIDECAR_REQUEST_HOSTS == {}


@pytest.mark.slow
@requires_huashu_sidecar
class TestAnExportThatReachesTheNetworkFails:
    def test_a_webfont_from_the_network_fails_the_export(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        document = slide_document(
            '<div class="slide"><p>Revenue grew</p></div>', css=GOOGLE_FONTS_STYLESHEET
        )
        with pytest.raises(AssertionError, match="network"):
            export_documents([document], monkeypatch=monkeypatch)

    def test_a_corpus_chart_slide_exports_its_chart_offline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        logged = export_logged([corpus_document("11")], monkeypatch=monkeypatch)
        assert logged.failures == [], logged.failures
        (summary,) = slide_summaries(logged.stderr)
        assert summary["blockedRequests"] == 0, summary
        assert summary["captures"] >= 1 and summary["captureFailures"] == 0, summary


@pytest.mark.slow
@requires_huashu_sidecar
def test_measure_refuses_a_document_that_loads_from_the_network() -> None:
    document = slide_document(
        '<div class="slide"><p id="probe">Revenue grew</p></div>', css=GOOGLE_FONTS_STYLESHEET
    )
    with pytest.raises(AssertionError, match="network"):
        browser_rect(document, "#probe")
