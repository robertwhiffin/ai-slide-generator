"""Snapshot engine: the page is read with every font face its text uses loaded.

``render_slide.cjs pageFontsSettled`` waits for ``document.fonts.ready`` and,
forcing the layout each round, until no face is loading. A face is requested
only when the layout first sets text in it, so the wait also runs once the
export has finished the slide's animations: an animation whose end state sets
text in another face asks for that face then. The faces and their status are
read through the pristine-realm accessors (``dom_access.mjs``), or the page's
own (``OWN_DOM_ACCESS``) where no pristine realm can be had.

The late face here is DM Mono (the pinned copy), served from a local server
that answers after ``LATE_FONT_DELAY_SECONDS``, so it is loading when the page
is read unless the export waits for it. Every slide holds one paragraph; the
oracle is the width the export gives that paragraph's text box:

* ``settled`` sets the paragraph in the late face from the start: the width the
  face gives it once loaded;
* ``fallback`` sets it in serif: the width it has while the face loads;
* ``animated`` starts in serif, and an animation's end state sets it in the
  late face, which the export's finish of the animation first asks for;
* ``animated-own-access`` is ``animated`` with the pristine realm denied (its
  script makes every iframe's ``contentWindow`` this window), so the faces are
  read through the page's own accessors;
* ``hostile-fonts`` sets the paragraph in the late face from the start, and its
  script makes ``document.fonts`` a decoy whose ``ready`` never settles and
  whose faces stay loading, as it does the real set's ``ready``: the wait reads
  the real set, so the slide neither waits out the font budget nor logs that
  its fonts did not finish loading.
"""

from __future__ import annotations

import http.server
import json
import threading
import time
from collections.abc import Iterator

import pytest

from src.services import pptx_from_html_huashu
from tests.fixtures.export_snapshot_support import (
    PINNED_FONT_DIR,
    LoggedExport,
    browser_title,
    export_logged,
    node_json,
    requires_huashu_sidecar,
    slide_shapes,
)

LATE_FONT = PINNED_FONT_DIR / "dm-mono" / "DMMono-400-latin.woff2"
DOM_ACCESS_MODULE = pptx_from_html_huashu.SIDECAR_DIR / "dom_access.mjs"
# Longer than a read of the page takes, well inside the export's 5 s font budget.
LATE_FONT_DELAY_SECONDS = 2
PARAGRAPH_TEXT = "Settled typeface"
# The line render_slide.cjs logs when a slide's fonts outlast the budget.
FONTS_TIMEOUT_LINE = "fonts did not finish loading"
# The widths of one paragraph set in the same face agree to layout rounding.
WIDTH_TOLERANCE_PX = 0.5
# DM Mono and serif set the paragraph this far apart at 40 px, at least.
FACE_WIDTH_GAP_PX = 50

# The pristine realm denied: every iframe's contentWindow is this window, which
# the capture refuses (dom_access.mjs), so the page's own accessors are used.
DENY_PRISTINE_REALM = """
Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {
  configurable: true, get: function () { return window; }
});
document.title = JSON.stringify({
  deniesPristine: document.createElement('iframe').contentWindow === window
});
"""

# document.fonts and the real set's ready made to lie: a decoy set whose ready
# never settles and whose one face stays loading.
HOSTILE_FONTS = """
var neverReady = new Promise(function () {});
var setPrototype = Object.getPrototypeOf(document.fonts);
Object.defineProperty(setPrototype, 'ready', {
  configurable: true, get: function () { return neverReady; }
});
var decoy = {
  ready: neverReady,
  status: 'loading',
  forEach: function (callback) { callback({ status: 'loading' }); },
  values: function () { return [{ status: 'loading' }][Symbol.iterator](); }
};
Object.defineProperty(Document.prototype, 'fonts', {
  configurable: true, get: function () { return decoy; }
});
document.title = JSON.stringify({
  fontsIsDecoy: document.fonts === decoy, readyReplaced: document.fonts.ready === neverReady
});
"""


class _LateFontHandler(http.server.BaseHTTPRequestHandler):
    font = LATE_FONT.read_bytes()

    def do_GET(self) -> None:  # noqa: N802 (the http.server interface)
        time.sleep(LATE_FONT_DELAY_SECONDS)
        self.send_response(200)
        self.send_header("Content-Type", "font/woff2")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(self.font)

    def log_message(self, *_: object) -> None:
        return None


@pytest.fixture(scope="module")
def late_font_url() -> Iterator[str]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _LateFontHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/late.woff2"
    finally:
        server.shutdown()
        thread.join()


def _document(font_url: str, paragraph_css: str, script: str = "") -> str:
    """A complete slide document: one paragraph, styled by ``paragraph_css``, after ``script``."""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<script>{script}</script>
<style>
@font-face {{ font-family: 'Late'; src: url('{font_url}') format('woff2'); }}
html, body {{ margin: 0; padding: 0; width: 1280px; height: 720px; }}
.slide {{ position: relative; width: 1280px; height: 720px; background: #F9F7F4; color: #1B3139; }}
#late {{ position: absolute; left: 88px; top: 100px; margin: 0; font-size: 40px; {paragraph_css} }}
@keyframes swap {{ to {{ font-family: 'Late', serif; }} }}
</style></head>
<body><div class="slide"><p id="late">{PARAGRAPH_TEXT}</p></div></body></html>"""


def _documents(font_url: str) -> dict[str, str]:
    late = "font-family: 'Late', serif;"
    animated = "font-family: serif; animation: swap 100s forwards;"
    return {
        "settled": _document(font_url, late),
        "fallback": _document(font_url, "font-family: serif;"),
        "animated": _document(font_url, animated),
        "animated-own-access": _document(font_url, animated, DENY_PRISTINE_REALM),
        "hostile-fonts": _document(font_url, late, HOSTILE_FONTS),
    }


@pytest.fixture(scope="module")
def font_deck(late_font_url: str) -> Iterator[tuple[list[str], LoggedExport]]:
    documents = _documents(late_font_url)
    with pytest.MonkeyPatch.context() as monkeypatch:
        logged = export_logged(list(documents.values()), monkeypatch=monkeypatch)
    assert logged.failures == [], logged.failures
    yield list(documents), logged


def _paragraph_width(deck: tuple[list[str], LoggedExport], name: str) -> float:
    names, logged = deck
    boxes = [
        shape
        for shape in slide_shapes(logged.pptx, names.index(name))
        if shape.kind == "text" and PARAGRAPH_TEXT in (shape.text or "")
    ]
    assert len(boxes) == 1, f"{name}: expected one text box holding the paragraph, got {boxes}"
    return boxes[0].w


def _slide_lines(logged: LoggedExport, names: list[str], name: str) -> list[str]:
    """The sidecar lines one slide printed: those between the previous slide's OK and its own."""
    lines = logged.stderr.splitlines()
    ends = [index for index, line in enumerate(lines) if "[huashu] [" in line and "] OK" in line]
    position = names.index(name)
    start = ends[position - 1] + 1 if position else 0
    return lines[start : ends[position] + 1]


@pytest.mark.slow
@requires_huashu_sidecar
class TestFontsSettle:
    def test_the_fixtures_bite(self, late_font_url: str) -> None:
        documents = _documents(late_font_url)
        assert json.loads(browser_title(documents["animated-own-access"])) == {
            "deniesPristine": True
        }
        assert json.loads(browser_title(documents["hostile-fonts"])) == {
            "fontsIsDecoy": True,
            "readyReplaced": True,
        }

    def test_the_two_faces_set_the_paragraph_apart(
        self, font_deck: tuple[list[str], LoggedExport]
    ) -> None:
        """The oracle discriminates: loaded, the late face sets the paragraph far from serif."""
        gap = _paragraph_width(font_deck, "settled") - _paragraph_width(font_deck, "fallback")
        assert abs(gap) > FACE_WIDTH_GAP_PX, f"the faces set the paragraph only {gap:.1f}px apart"

    @pytest.mark.parametrize("name", ["animated", "animated-own-access", "hostile-fonts"])
    def test_the_paragraph_is_read_in_its_loaded_face(
        self, font_deck: tuple[list[str], LoggedExport], name: str
    ) -> None:
        settled = _paragraph_width(font_deck, "settled")
        width = _paragraph_width(font_deck, name)
        fallback = _paragraph_width(font_deck, "fallback")
        assert width == pytest.approx(settled, abs=WIDTH_TOLERANCE_PX), (
            f"{name}: the paragraph is {width:.2f}px wide, not the {settled:.2f}px of its loaded "
            f"face (in serif, the face still loading: {fallback:.2f}px)"
        )

    def test_a_hostile_font_set_costs_no_wait(
        self, font_deck: tuple[list[str], LoggedExport]
    ) -> None:
        """The wait reads the real set: no slide waits out the font budget."""
        names, logged = font_deck
        late = [line for line in logged.stderr.splitlines() if FONTS_TIMEOUT_LINE in line]
        assert late == [], f"a slide's fonts were waited out: {late}"
        lines = _slide_lines(logged, names, "hostile-fonts")
        assert any("[html2pptx] slide summary" in line for line in lines), lines


# Read in a real page, a face of it loading: the font accessors of
# DOM_ACCESS_SOURCE, through the pristine realm or the page's own.
FONT_ACCESS_SCRIPT = """
(async () => {
  const { chromium } = require('playwright');
  const { DOM_ACCESS_SOURCE } = await import(%(dom_access)s);
  const options = { args: ['--disable-gpu', '--no-sandbox'] };
  if (%(channel)s) options.channel = %(channel)s;
  const browser = await chromium.launch(options);
  try {
    const page = await browser.newPage();
    await page.setContent('<p>x</p>');
    if (%(deny)s) await page.evaluate(%(deny_script)s);
    await page.evaluate((url) => {
      const face = new FontFace('Late', 'url(' + url + ')');
      document.fonts.add(face);
      face.load().catch(() => {});
    }, %(url)s);
    const read = await page.evaluate(`(async () => {
      const DOM_ACCESS_LOG_PREFIX = '[html2pptx]';
      ${DOM_ACCESS_SOURCE}
      const dom = domAccess();
      const loading = dom.loadingFontFaces();
      await dom.fontsReady();
      return { pristine: dom.pristine, loading, settled: dom.loadingFontFaces() };
    })()`);
    process.stdout.write(JSON.stringify({ ...read, version: browser.version() }));
  } finally {
    await browser.close();
  }
})();
"""

# The browsers the export runs: Chrome (macOS) and the Chromium headless shell
# (the Linux deploy, and the one with no global FontFaceSet).
FONT_ACCESS_CHANNELS = ("chrome", "chromium")


@pytest.mark.slow
@requires_huashu_sidecar
class TestFontAccessors:
    @pytest.mark.parametrize("channel", FONT_ACCESS_CHANNELS)
    @pytest.mark.parametrize("deny", [False, True], ids=["pristine", "own-access"])
    def test_a_loading_face_is_counted_until_it_loads(
        self, late_font_url: str, channel: str, deny: bool
    ) -> None:
        read = node_json(
            FONT_ACCESS_SCRIPT
            % {
                "dom_access": json.dumps(DOM_ACCESS_MODULE.as_uri()),
                "channel": json.dumps(channel),
                "deny": json.dumps(deny),
                "deny_script": json.dumps(DENY_PRISTINE_REALM),
                "url": json.dumps(late_font_url),
            }
        )
        assert read["pristine"] is (not deny), read
        assert (read["loading"], read["settled"]) == (1, 0), read
