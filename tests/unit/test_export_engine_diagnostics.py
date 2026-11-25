"""The engine's own page-side diagnostics reach the app's log, on a channel no page writes to.

The engine's page-side passes (``preprocess.mjs``, the snapshot's modules and the settle
reads ``render_slide.cjs`` composes with ``dom_access.mjs``) say when content leaves the
deck: a slide with no root, a collection cut at its bound, a table exported as
positioned items, a read the page made fail. They used to say it on the page's console,
which slide script can replace (a ``console.warn`` that does nothing) and write to (a
line with the engine's prefix), so without the debug text the log counted those lines
and quoted none of them. Each pass now collects what it says in its own closure, from
nothing the page's realm can replace, and returns it with its result; Node reads it
through the DevTools protocol, checks every entry against the engine's own wordings
(``model_check.cjs`` checkDiagnostics) and logs it with the pass's prefix
(``log_line.cjs`` diagnosticLine).

* Every wording is logged without the debug text; what in an entry came from the page
  (an error's message, a tag name) is logged by its length alone, and whole with it.
* A page that replaces its console, or owns ``Array.prototype.push`` (which Playwright's
  own page-side serializer calls), neither silences an entry nor forges one.
* The results the passes return beside their diagnostics are checked too: the
  background transfer's and the animations' are logged in the slide summary, and a
  page that owned ``Array.prototype.push`` used to write its own words there.
"""

from __future__ import annotations

import json

import pytest

from src.services import pptx_from_html_huashu
from tests.fixtures.export_snapshot_support import (
    MODEL_DROP_PREFIX,
    SIDECAR_ECHO_PREFIX,
    export_logged,
    node_json,
    requires_huashu_sidecar,
    slide_document,
    slide_summaries,
)
from tests.unit.test_export_slide_root_background import FIXTURE_DIR

pytestmark = [pytest.mark.slow, requires_huashu_sidecar]

RENDER_SLIDE = pptx_from_html_huashu.SIDECAR_DIR / "render_slide.cjs"
LOG_LINE = pptx_from_html_huashu.SIDECAR_DIR / "log_line.cjs"
MODEL_CHECK = pptx_from_html_huashu.SIDECAR_DIR / "model_check.cjs"

NO_ROOT_LINE = "[preprocess] no slide root:"
NO_CANDIDATES = "wrapper candidates (none)"
NO_ROOT_COST_LINE = "resolved NO root"
# The child tags of rootless.html's body, as the no-root line names them.
ROOTLESS_TAGS = "H1, P"
PAGE_CONSOLE_LINE = "[html2pptx] page console: "
DIAGNOSTICS_MORE_LINE = "[html2pptx] diagnostics: "
BROWSER_CONSOLE = "Browser console: "
# How a diagnostic line ends that left a page's text out.
WITHHELD_NOTE = f"(page text not logged: {pptx_from_html_huashu.SIDECAR_DEBUG_TEXT_ENV}=1 logs it)"

THROWN_WORD = "Zyqthrownword"
FORGED_WORD = "Zyqforgedword"
LEAKED_WORD = "Zyqleakword"


def _sidecar_lines(stderr: str) -> list[str]:
    """What the sidecar itself printed on stderr, as the wrapper echoed it, the echo prefix off."""
    return [
        line.removeprefix(SIDECAR_ECHO_PREFIX)
        for line in stderr.splitlines()
        if line.startswith(SIDECAR_ECHO_PREFIX)
    ]


def _rootless(script: str = "") -> str:
    """The rootless fixture, with ``script`` run in its head before anything else."""
    html = (FIXTURE_DIR / "rootless.html").read_text(encoding="utf-8")
    assert "<head>" in html, "fixture drift: rootless.html has no head"
    return html.replace("<head>", f"<head><script>{script}</script>", 1)


@pytest.fixture(scope="module")
def rootless_logs() -> dict[bool, list[str]]:
    """The rootless slide exported without the debug text and with it: its sidecar lines."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        exports = {
            debug: export_logged([_rootless()], monkeypatch=monkeypatch, debug_text=debug)
            for debug in (False, True)
        }
    return {debug: _sidecar_lines(logged.stderr) for debug, logged in exports.items()}


class TestTheWordingsReachTheLogWithoutTheDebugText:
    def test_a_slide_with_no_root_says_so(self, rootless_logs: dict[bool, list[str]]) -> None:
        lines = rootless_logs[False]
        (no_root,) = [line for line in lines if line.startswith(NO_ROOT_LINE)]
        assert NO_CANDIDATES in no_root, no_root
        assert any(NO_ROOT_COST_LINE in line for line in lines), lines

    def test_its_page_text_is_logged_by_its_length_and_whole_with_the_flag(
        self, rootless_logs: dict[bool, list[str]]
    ) -> None:
        """Body's child tags are the page's: a custom element can be named for the deck."""
        (without,) = [line for line in rootless_logs[False] if line.startswith(NO_ROOT_LINE)]
        assert f"body children [<{len(ROOTLESS_TAGS)} characters>]" in without, without
        assert without.endswith(WITHHELD_NOTE), without
        (with_flag,) = [line for line in rootless_logs[True] if line.startswith(NO_ROOT_LINE)]
        assert f"body children [{ROOTLESS_TAGS}]" in with_flag, with_flag
        assert WITHHELD_NOTE not in with_flag, with_flag

    def test_the_engines_own_lines_are_no_page_console_messages(
        self, rootless_logs: dict[bool, list[str]]
    ) -> None:
        """The rootless page logs nothing itself, so no line counts its console."""
        assert [line for line in rootless_logs[False] if line.startswith(PAGE_CONSOLE_LINE)] == []
        assert [line for line in rootless_logs[True] if BROWSER_CONSOLE in line] == []


# Slide script that leaves the preprocess pass the page's own lookups (the pristine
# realm's capture answers the page's window, so it is refused) and makes the wrapper
# lookup claim 2,000,001 wrappers, each the slide's real <section>: the pass reads up to
# its bound, finds the slide root in the first, and announces the cut.
WRAPPER_FLOOD = """
Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {
  configurable: true, get: function () { return window; }
});
var queryAll = Document.prototype.querySelectorAll;
Document.prototype.querySelectorAll = function (selector) {
  if (selector !== 'body > section, body > article') return queryAll.call(this, selector);
  var section = queryAll.call(this, 'body > section')[0];
  return new Proxy({}, {
    get: function (target, key) { return key === 'length' ? 2000001 : section; }
  });
};
"""
# The script is body's child beside the <section>, so the section holds the slide alone.
FLOODED_BODY = (
    '<section style="background: #123456;"><div class="slide"><h1 style="color: #fff;">'
    f"Flooded wrappers</h1></div></section><script>{WRAPPER_FLOOD}</script>"
)
PREPROCESS_COLLECTION_LINE = (
    "[preprocess] collection truncated at 1000000 of 2000001 items in nodeListToArray: "
    "content past that point is NOT in the exported deck."
)


def test_a_preprocess_collection_cut_at_its_bound_is_announced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logged = export_logged([slide_document(FLOODED_BODY)], monkeypatch=monkeypatch)
    assert logged.failures == [], logged.failures

    lines = _sidecar_lines(logged.stderr)
    assert [line for line in lines if line.startswith(PREPROCESS_COLLECTION_LINE)], lines
    (summary,) = slide_summaries(logged.stderr)
    assert summary["bgTransferred"] == "solid", summary


# Slide script that replaces the page's console with functions that do nothing, after
# keeping the real one, and owns Array.prototype.push, which Playwright's page-side
# serializer calls for every value an evaluate returns. The push drops what would carry
# a pass's diagnostics through that serializer, and adds a forged stream of them in the
# engine's own encoding beside every value it serializes; the kept console writes a
# forged no-root line under the engine's prefix. It says once, on that console, that its
# push ran, so the poisoning is seen to take.
def _stream(*entries: tuple[str, ...]) -> str:
    """Entries in the engine's encoding (dom_access.mjs diagnose): each token, then each
    entry, written after its length and a colon."""
    encoded = ["".join(f"{len(token)}:{token}" for token in entry) for entry in entries]
    return "".join(f"{len(entry)}:{entry}" for entry in encoded)


FORGED_STREAM = _stream(
    ("noSlideRoot", str(len(FORGED_WORD)), FORGED_WORD, "0", "0", "pristineTree"),
    ("forgedKey", f"{FORGED_WORD} after its own line"),
)
SILENCING_AND_FORGING = """
var realWarn = console.warn.bind(console);
console.warn = console.error = console.log = console.info = console.debug = function () {};
realWarn('[preprocess] no slide root: %(forged)s');
var realPush = Array.prototype.push;
var announced = false;
Array.prototype.push = function () {
  if (!announced) { announced = true; realWarn('[html2pptx] the page owns Array.prototype.push'); }
  var kept = [];
  for (var index = 0; index < arguments.length; index++) {
    var value = arguments[index];
    if (typeof value === 'string' && /no slide root|noSlideRoot/.test(value)) continue;
    if (value && typeof value === 'object' && value.k === 'diagnostics') continue;
    kept[kept.length] = value;
    if (value && typeof value === 'object' && typeof value.k === 'string' && 'v' in value) {
      kept[kept.length] = { k: 'diagnostics', v: %(stream)s };
    }
  }
  return realPush.apply(this, kept);
};
""" % {"forged": FORGED_WORD, "stream": json.dumps(FORGED_STREAM)}


@pytest.mark.parametrize("debug", [False, True], ids=["counted", "debug-text"])
def test_a_page_neither_silences_nor_forges_a_diagnostic(
    monkeypatch: pytest.MonkeyPatch, debug: bool
) -> None:
    logged = export_logged(
        [_rootless(SILENCING_AND_FORGING)],
        monkeypatch=monkeypatch,
        debug_text=debug,
        allow_model_drops=True,
    )
    assert logged.failures == [], logged.failures
    lines = _sidecar_lines(logged.stderr)

    (no_root,) = [line for line in lines if line.startswith(NO_ROOT_LINE)]
    assert NO_CANDIDATES in no_root and FORGED_WORD not in no_root, no_root
    forged = [line for line in lines if FORGED_WORD in line and BROWSER_CONSOLE not in line]
    assert not forged, forged
    if debug:
        forwarded = [line for line in lines if line.startswith(BROWSER_CONSOLE)]
        assert any("owns Array.prototype.push" in line for line in forwarded), (
            f"fixture drift: the page's push never ran: {forwarded}"
        )
    else:
        (counted,) = [line for line in lines if line.startswith(PAGE_CONSOLE_LINE)]
        assert "2 with the engine's prefix" in counted, (
            f"fixture drift: the forged line and the push's own were not both logged: {counted}"
        )
        assert FORGED_WORD not in logged.stderr, logged.stderr[-3000:]


# Slide script whose document.fonts throws an error holding a word of its own: the
# snapshot's webfont read fails with that message (snapshot_text.mjs loadedFonts).
THROWING_FONTS = (
    "Object.defineProperty(Document.prototype, 'fonts', { configurable: true,"
    f" get: function () {{ throw new Error('the page threw {THROWN_WORD}'); }} }});"
)
FONTS_LINE = "[html2pptx] document.fonts could not be read ("
FONTS_LOSS = "a family whose faces were not read exports without weight-named faces"


@pytest.mark.parametrize("debug", [False, True], ids=["by-length", "debug-text"])
def test_a_message_the_page_made_is_logged_by_its_length(
    monkeypatch: pytest.MonkeyPatch, debug: bool
) -> None:
    body = f'<div class="slide"><h1>Fonts that throw</h1><script>{THROWING_FONTS}</script></div>'
    logged = export_logged([slide_document(body)], monkeypatch=monkeypatch, debug_text=debug)
    assert logged.failures == [], logged.failures

    (line,) = [line for line in _sidecar_lines(logged.stderr) if line.startswith(FONTS_LINE)]
    assert FONTS_LOSS in line, line
    message = f"the page threw {THROWN_WORD}"
    if debug:
        assert f"({message})" in line, line
    else:
        assert f"(<{len(message)} characters>)" in line and line.endswith(WITHHELD_NOTE), line
        assert THROWN_WORD not in logged.stderr, logged.stderr[-3000:]


# Slide script that owns Array.prototype.push and rewrites what Playwright's page-side
# serializer pushes for the background transfer's result and the animations' counts,
# both of which the slide summary logs.
REWRITING_RESULTS = (
    "var realPush = Array.prototype.push;"
    "Array.prototype.push = function () {"
    "  for (var index = 0; index < arguments.length; index++) {"
    "    var value = arguments[index];"
    "    if (value && typeof value === 'object'"
    "        && (value.k === 'bgTransferred' || value.k === 'finished'))"
    f"      value.v = '{LEAKED_WORD}';"
    "  }"
    "  return realPush.apply(this, arguments);"
    "};"
)


def test_a_pass_result_the_page_rewrote_is_dropped_not_logged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = (
        '<div class="slide" style="background: #123456;"><h1>Results</h1>'
        f"<script>{REWRITING_RESULTS}</script></div>"
    )
    logged = export_logged([slide_document(body)], monkeypatch=monkeypatch, allow_model_drops=True)
    assert logged.failures == [], logged.failures

    assert LEAKED_WORD not in logged.stderr, logged.stderr[-3000:]
    (summary,) = slide_summaries(logged.stderr)
    assert summary["bgTransferred"] is None, summary
    assert summary["animations"] == {"finished": 0, "cancelled": 0, "unfinished": 0}, summary
    assert summary["modelDrops"] >= 2, summary
    assert [line for line in _sidecar_lines(logged.stderr) if line.startswith(MODEL_DROP_PREFIX)], (
        logged.stderr[-3000:]
    )


# Slide script that adds tables past what one pass keeps of its diagnostics, each ruled
# (a grid an a:tbl would draw) and with a cell made in another namespace, laid out as a
# cell but no HTML cell, whose spans cannot be read: each table says so once.
TABLES_PAST_THE_BOUND = 120
UNREADABLE_TABLES_BODY = (
    '<div class="slide"><style>#tables table { border-collapse: collapse; font-size: 12px; }'
    " #tables td { display: table-cell; padding: 2px; border-bottom: 1px solid #888; }</style>"
    '<h1>Tables</h1><div id="tables"></div><script>(function () {'
    "  var holder = document.getElementById('tables');"
    f"  for (var index = 0; index < {TABLES_PAST_THE_BOUND}; index++) {{"
    "    var table = document.createElement('table');"
    "    table.style.cssText = 'position: absolute; top: 200px; left: '"
    "      + (10 * (index % 100)) + 'px;';"
    "    var row = table.insertRow();"
    "    row.insertCell().textContent = 'n';"
    "    var cell = document.createElementNS('http://example.com/not-html', 'td');"
    "    cell.appendChild(document.createTextNode('f'));"
    "    row.appendChild(cell);"
    "    holder.appendChild(table);"
    "  }"
    "})();</script></div>"
)
NATIVE_TABLE_LINE = (
    "[html2pptx] native table: a cell's spans could not be read; it exports as positioned items"
)


def _diagnostic_bounds() -> dict:
    """How many diagnostic lines a slide logs at most, and how many diagnostics a pass keeps."""
    return node_json(
        f"const slide = require({json.dumps(str(RENDER_SLIDE))}).DIAGNOSTIC_LINES_PER_SLIDE;"
        f"const pass = require({json.dumps(str(LOG_LINE))}).DIAGNOSTICS_PER_PASS;"
        "console.log(JSON.stringify({ perSlide: slide, perPass: pass }));"
    )


def test_a_pass_keeps_its_bound_of_diagnostics_and_counts_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bounds = _diagnostic_bounds()
    assert TABLES_PAST_THE_BOUND > bounds["perPass"], bounds
    logged = export_logged([slide_document(UNREADABLE_TABLES_BODY)], monkeypatch=monkeypatch)
    assert logged.failures == [], logged.failures

    lines = _sidecar_lines(logged.stderr)
    tables = [line for line in lines if line == NATIVE_TABLE_LINE]
    assert len(tables) == bounds["perPass"], lines[:5]
    more = TABLES_PAST_THE_BOUND - bounds["perPass"]
    (counted,) = [line for line in lines if line.startswith(DIAGNOSTICS_MORE_LINE)]
    assert counted.startswith(f"{DIAGNOSTICS_MORE_LINE}{more} more not logged"), counted


# Node: a slide's log given two passes' diagnostics, more than a slide logs between them,
# then a pass's diagnostics of which Node dropped two.
SLIDE_LOG_SCRIPT = """
const { slideLog } = require(%(render_slide)s);
const written = [];
console.error = (line) => written.push(String(line));
const log = slideLog();
const entry = ['box-shadow fits: ', '1', ' box(es) past the ', '64', ' fits a slide makes',
  ' carry their first shadow layer'];
const pass = (count, over, dropped) => ({
  entries: Array.from({ length: count }, () => entry), over, dropped,
});
log.diagnostics('[html2pptx]', pass(%(first)d, 0, 0));
log.diagnostics('[html2pptx]', pass(%(second)d, %(over)d, 0));
log.diagnostics('[html2pptx]', pass(0, 0, 2));
log.report();
process.stdout.write(JSON.stringify({ written, drops: log.drops() }));
"""


def test_a_slide_logs_its_bound_of_diagnostics_across_its_passes_and_counts_drops() -> None:
    bounds = _diagnostic_bounds()
    first, second, over = bounds["perSlide"] - 20, 80, 5
    script = SLIDE_LOG_SCRIPT % {
        "render_slide": json.dumps(str(RENDER_SLIDE)),
        "first": first,
        "second": second,
        "over": over,
    }
    read = node_json(script)
    written = read["written"]
    shown = [line for line in written if line.startswith("[html2pptx] box-shadow fits: 1 box(es)")]
    assert len(shown) == bounds["perSlide"], len(shown)
    (dropped,) = [line for line in written if line.startswith(MODEL_DROP_PREFIX)]
    assert dropped == f"{MODEL_DROP_PREFIX}2 diagnostic(s) failed validation and were dropped", (
        dropped
    )
    assert read["drops"] == 2, read
    more = first + second + over - bounds["perSlide"]
    assert written[-1].startswith(f"{DIAGNOSTICS_MORE_LINE}{more} more not logged"), written[-1]


# Entries a page could forge, in the engine's encoding: a real wording whose page slot holds
# the page's word (kept: a page slot is the page's), then three that are no line the engine
# writes: a key of no wording, a number slot holding a word, and page text longer than the
# length it claims (dropped and counted).
FORGED_ENTRIES = (
    ("noSlideRoot", str(len(FORGED_WORD)), FORGED_WORD, "0", "0", "pristineTree"),
    ("forgedKey", f"{FORGED_WORD} on a line of its own"),
    ("boxShadowFits", FORGED_WORD, "64"),
    ("rootUnmarked", "3", FORGED_WORD),
)
FORGED_DROPS = len(FORGED_ENTRIES) - 1

CHECK_SCRIPT = """
const { checkDiagnostics } = require(%(model_check)s);
const { diagnosticLine } = require(%(log_line)s);
const checked = checkDiagnostics(%(stream)s, 0);
process.stdout.write(JSON.stringify({
  lines: checked.entries.map((parts) => diagnosticLine('[preprocess]', parts)),
  dropped: checked.dropped,
}));
"""


def test_the_check_takes_nothing_but_the_engines_wordings() -> None:
    checked = node_json(
        CHECK_SCRIPT
        % {
            "model_check": json.dumps(str(MODEL_CHECK)),
            "log_line": json.dumps(str(LOG_LINE)),
            "stream": json.dumps(_stream(*FORGED_ENTRIES)),
        }
    )
    assert checked["dropped"] == FORGED_DROPS, checked
    (line,) = checked["lines"]
    assert line.startswith(NO_ROOT_LINE) and FORGED_WORD not in line, line


# Slide script that takes over the evaluation itself: window.eval, which Playwright's
# utility script calls with every pass's source, runs the pass and puts FORGED_ENTRIES
# in place of what it diagnosed, so the diagnostics Node reads are the page's own.
TAKING_OVER_THE_EVALUATION = """
var realEval = window.eval;
var forged = %(stream)s;
function forge(value) {
  if (value && typeof value === 'object' && 'diagnostics' in value) value.diagnostics = forged;
  return value;
}
window.eval = function (source) {
  var result = realEval(source);
  return result && typeof result.then === 'function' ? result.then(forge) : forge(result);
};
""" % {"stream": json.dumps(_stream(*FORGED_ENTRIES))}


def test_a_page_that_takes_over_the_evaluation_forges_no_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It decides what each pass says it diagnosed, and still logs no word of its own.

    Each forged entry that is no line of the engine's is dropped and counted (the
    summary's modelDrops, and the model drop line, which every other export test fails
    on); the one that is says its page slot by its length alone.
    """
    body = '<div class="slide"><h1>Taken over</h1></div>'
    logged = export_logged(
        [slide_document(body + f"<script>{TAKING_OVER_THE_EVALUATION}</script>")],
        monkeypatch=monkeypatch,
        allow_model_drops=True,
    )
    assert logged.failures == [], logged.failures

    assert FORGED_WORD not in logged.stderr, logged.stderr[-3000:]
    lines = _sidecar_lines(logged.stderr)
    forged = [line for line in lines if NO_ROOT_LINE.split(" ", 1)[1] in line]
    assert forged and all(f"[<{len(FORGED_WORD)} characters>]" in line for line in forged), (
        f"fixture drift: the page did not take the evaluation over: {lines}"
    )
    drops = [line for line in lines if line.startswith(MODEL_DROP_PREFIX)]
    assert drops and all(f"{FORGED_DROPS} diagnostic(s)" in line for line in drops), drops
    (summary,) = slide_summaries(logged.stderr)
    assert summary["modelDrops"] >= FORGED_DROPS, summary
