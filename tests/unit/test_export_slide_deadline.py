"""A slide whose script blocks its page fails alone, at the per-slide deadline (I1).

``render_slide.cjs`` gives each slide ``SLIDE_DEADLINE_MS``, from its browser's launch to
its last read. A slide whose script blocks its page's main thread (a busy loop) used to
hang every read after it, and with them the whole deck, until the sidecar's own timeout
(``SIDECAR_TIMEOUT_SECONDS``, 180 s) ended the export with no deck at all. Now that slide
is stopped at its deadline, its browser closed, and it fails with the failure entry the
routes report (``X-Huashu-Failures``); the deck goes on and is written with every other
slide.

The deadline is above every wait the engine bounds itself: a slide that those waits let
through, slow and exported as far as it settled, is not failed by the deadline instead.

It bounds every step of the slide, not only its page's reads: a browser that never hands
out the slide's context or page, or never lets the request guard route it (a browser
stalled under load), stops the slide at its deadline too. And a browser that does not
close once its slide is done is killed, one that has disconnected while its process lives
on too: neither ever holds up the deck, and no slide's browser outlives it.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.services import pptx_from_html_huashu
from tests.fixtures.export_snapshot_support import (
    export_documents,
    export_logged,
    node_json,
    requires_huashu_sidecar,
    requires_node,
    slide_document,
    slide_xml,
)

RENDER_SLIDE = pptx_from_html_huashu.SIDECAR_DIR / "render_slide.cjs"
CAPTURE = pptx_from_html_huashu.SIDECAR_DIR / "capture.cjs"

# The message a slide past its deadline fails with (render_slide.cjs).
PAST_ITS_DEADLINE = "did not finish within"
# A deck timeout of half the real one: a deck the deadline does not save ends at it, so a
# red run ends in a minute and a half, and a green one is well inside even this.
DECK_TIMEOUT_SECONDS = 90
# The share of its deadline a slide that finishes inside it spends blocked.
INSIDE_THE_DEADLINE = 0.75


def _deadline_ms() -> int:
    return node_json(
        f"console.log(JSON.stringify(require({json.dumps(str(RENDER_SLIDE))}).SLIDE_DEADLINE_MS));"
    )


def _blocked_after_load(milliseconds: int | None) -> str:
    """Script that blocks the page's main thread once it has loaded: for good, or for a while."""
    loop = (
        "for (;;) {}"
        if milliseconds is None
        else f"const until = Date.now() + {milliseconds}; while (Date.now() < until) {{}}"
    )
    return f"<script>addEventListener('load', () => setTimeout(() => {{ {loop} }}, 0));</script>"


def _slide(heading: str, script: str = "") -> str:
    return f'<div class="slide"><h1>{heading}</h1><p>Revenue grew 12%.</p>{script}</div>'


def _deck_texts(pptx: bytes, count: int) -> list[str]:
    return ["".join(slide_xml(pptx, index).itertext()) for index in range(count)]


@pytest.mark.slow
@requires_huashu_sidecar
class TestABlockedSlideFailsAlone:
    def test_a_slide_blocked_for_good_between_two_others_fails_at_its_deadline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(pptx_from_html_huashu, "SIDECAR_TIMEOUT_SECONDS", DECK_TIMEOUT_SECONDS)
        deadline_seconds = _deadline_ms() / 1000
        documents = [
            slide_document(_slide("First slide"), slide_id="deadline-1"),
            slide_document(_slide("Blocked slide", _blocked_after_load(None)), slide_id="deadline-2"),
            slide_document(_slide("Third slide"), slide_id="deadline-3"),
        ]

        started = time.monotonic()
        pptx, failures = export_documents(documents, monkeypatch=monkeypatch)
        elapsed = time.monotonic() - started

        assert [failure["slide_index"] for failure in failures] == [1], failures
        assert PAST_ITS_DEADLINE in failures[0]["error"], failures
        texts = _deck_texts(pptx, 2)
        assert "First slide" in texts[0] and "Third slide" in texts[1], texts
        assert elapsed < deadline_seconds + 30, (
            f"the deck took {elapsed:.1f}s with a {deadline_seconds:g}s deadline"
        )

    def test_a_slide_that_finishes_just_inside_its_deadline_is_kept(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(pptx_from_html_huashu, "SIDECAR_TIMEOUT_SECONDS", DECK_TIMEOUT_SECONDS)
        deadline_ms = _deadline_ms()
        blocked_ms = int(deadline_ms * INSIDE_THE_DEADLINE)
        document = slide_document(
            _slide("Slow slide", _blocked_after_load(blocked_ms)), slide_id="deadline-slow"
        )

        started = time.monotonic()
        pptx, failures = export_documents([document], monkeypatch=monkeypatch)
        elapsed = time.monotonic() - started

        assert failures == [], failures
        assert "Slow slide" in _deck_texts(pptx, 1)[0]
        assert elapsed > blocked_ms / 1000, (
            f"fixture drift: the slide took {elapsed:.1f}s, not the {blocked_ms / 1000:g}s it blocks"
        )


# Loaded into the real sidecar (NODE_OPTIONS --import): one step of one slide's browser
# never answers, the way a browser that stalls under load leaves it, and the process
# group of every browser launched before each launch, and at node's exit, is recorded.
# The exit handler is registered before Playwright's (which kills the browsers it
# launched), so a browser the engine left running is still seen at exit.
HUNG_STEP_PRELOAD = """
import fs from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(%(sidecar)s);
const { chromium } = require('playwright-core');
const RECORD = %(record)s;
const HUNG_LAUNCH = %(hung_launch)s;
const STEP = %(step)s;
const launched = [];
const never = () => new Promise(() => {});
function running(pid) {
  try {
    process.kill(-pid, 0);
    return true;
  } catch (error) {
    return error.code === 'EPERM';
  }
}
function record(at) {
  fs.appendFileSync(RECORD, JSON.stringify({ at, running: launched.filter(running) }) + '\\n');
}
process.on('exit', () => record('exit'));
const launch = chromium.launch.bind(chromium);
chromium.launch = async (options) => {
  record('launch ' + (launched.length + 1));
  const browser = await launch(options);
  const browserProcess = browser._connection.toImpl(browser).options.browserProcess.process;
  launched.push(browserProcess.pid);
  if (launched.length !== HUNG_LAUNCH) return browser;
  if (STEP === 'close') browser.close = never;
  // Its process group stopped and node's ends of its pipes closed, as a pipe that
  // broke: Playwright sees the browser disconnect, and its process lives on.
  if (STEP === 'disconnect') {
    browser.close = () => {
      process.kill(-browserProcess.pid, 'SIGSTOP');
      browserProcess.stdio[3].destroy();
      browserProcess.stdio[4].destroy();
      return never();
    };
  }
  // The browser closes for real, and its close never answers.
  if (STEP === 'closedUnanswered') {
    const close = browser.close.bind(browser);
    browser.close = () => {
      close().catch(() => {});
      return never();
    };
  }
  if (STEP === 'newContext') browser.newContext = never;
  if (STEP === 'newPage' || STEP === 'guard') {
    const newContext = browser.newContext.bind(browser);
    browser.newContext = async (...contextArguments) => {
      const context = await newContext(...contextArguments);
      if (STEP === 'newPage') context.newPage = never;
      if (STEP === 'guard') context.route = never;
      return context;
    };
  }
  return browser;
};
"""

# The steps of a slide's browser before its page is read: its context, the request
# guard's routing of it (request_guard.cjs guardContext) and its page.
SETUP_STEPS = ("newContext", "guard", "newPage")
# The slide of three whose step hangs.
HUNG_SLIDE = 2
# The line a slide whose browser would not close logs, and how it ends: its process
# killed, or found to have exited already (render_slide.cjs closeBrowser).
KILLED_LINE = "[html2pptx] the slide's browser did not close within"
KILLED = "its process was killed"
ALREADY_EXITED = "its process had already exited"
# A browser whose close never answers and whose process is still running: still
# connected ("close"), or disconnected, its process outliving the disconnection.
UNCLOSED_RUNNING = ("close", "disconnect")


def _three_slides() -> list[str]:
    return [
        slide_document(_slide(f"Slide {position}"), slide_id=f"hung-step-{position}")
        for position in range(1, 4)
    ]


@dataclass(frozen=True)
class _HungStepExport:
    """The three slides exported with one step of the second slide's browser hung."""

    pptx: bytes
    failures: list[dict]
    elapsed: float  # seconds
    stderr: str
    # The process groups of the browsers found running before each launch and at node's exit.
    browsers: list[dict]


def _export_with_a_hung_step(
    step: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> _HungStepExport:
    record = tmp_path / "browsers.jsonl"
    preload = tmp_path / "hung_step.mjs"
    preload.write_text(
        HUNG_STEP_PRELOAD
        % {
            "sidecar": json.dumps(str(pptx_from_html_huashu.SIDECAR_SCRIPT)),
            "record": json.dumps(str(record)),
            "hung_launch": json.dumps(HUNG_SLIDE),
            "step": json.dumps(step),
        },
        encoding="utf-8",
    )
    sidecar_env = pptx_from_html_huashu.sidecar_subprocess_env
    monkeypatch.setattr(
        pptx_from_html_huashu,
        "sidecar_subprocess_env",
        lambda: {**sidecar_env(), "NODE_OPTIONS": f"--import={preload.as_uri()}"},
    )
    monkeypatch.setattr(pptx_from_html_huashu, "SIDECAR_TIMEOUT_SECONDS", DECK_TIMEOUT_SECONDS)
    started = time.monotonic()
    logged = export_logged(_three_slides(), monkeypatch=monkeypatch)
    elapsed = time.monotonic() - started
    return _HungStepExport(
        pptx=logged.pptx,
        failures=logged.failures,
        elapsed=elapsed,
        stderr=logged.stderr,
        browsers=[json.loads(line) for line in record.read_text(encoding="utf-8").splitlines()],
    )


def _assert_no_browser_outlives_its_slide(browsers: list[dict]) -> None:
    """Before each launch every earlier slide's browser is gone, and at node's exit every one."""
    moments = [entry["at"] for entry in browsers]
    assert moments == ["launch 1", "launch 2", "launch 3", "exit"], browsers
    left = {entry["at"]: entry["running"] for entry in browsers if entry["running"]}
    assert not left, f"browser process groups still running: {left}"


@pytest.mark.slow
@requires_huashu_sidecar
class TestEveryStepOfASlideIsBounded:
    @pytest.mark.parametrize("step", SETUP_STEPS)
    def test_a_slide_whose_browser_never_answers_a_setup_step_fails_alone(
        self, step: str, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The second slide's browser never answers ``step``: that slide fails at its deadline.

        Its browser is closed then, before the third slide's launches, and the deck is
        written with the other two, well inside the deck's timeout.
        """
        deadline_seconds = _deadline_ms() / 1000
        export = _export_with_a_hung_step(step, tmp_path, monkeypatch)

        assert [failure["slide_index"] for failure in export.failures] == [HUNG_SLIDE - 1], (
            export.failures
        )
        assert PAST_ITS_DEADLINE in export.failures[0]["error"], export.failures
        texts = _deck_texts(export.pptx, 2)
        assert "Slide 1" in texts[0] and "Slide 3" in texts[1], texts
        assert export.elapsed < deadline_seconds + 20, (
            f"the deck took {export.elapsed:.1f}s with a {deadline_seconds:g}s deadline"
        )
        _assert_no_browser_outlives_its_slide(export.browsers)

    @pytest.mark.parametrize("step", UNCLOSED_RUNNING)
    def test_a_browser_that_never_closes_is_killed_and_its_slide_kept(
        self, step: str, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The second slide is read whole, then its browser never closes: its process is killed.

        So it is too when the browser has disconnected and its process lives on, which
        Playwright no longer finds once disconnected: the process is the one held since
        the browser launched.
        """
        export = _export_with_a_hung_step(step, tmp_path, monkeypatch)

        self._assert_kept_with_its_close_bounded(export, KILLED)
        _assert_no_browser_outlives_its_slide(export.browsers)

    def test_a_browser_that_closed_without_answering_is_said_to_have_exited(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The second slide's browser closes, and its close never answers: the line says so.

        Not that its process could not be killed: it had exited already.
        """
        export = _export_with_a_hung_step("closedUnanswered", tmp_path, monkeypatch)

        self._assert_kept_with_its_close_bounded(export, ALREADY_EXITED)
        _assert_no_browser_outlives_its_slide(export.browsers)

    @staticmethod
    def _assert_kept_with_its_close_bounded(export: _HungStepExport, outcome: str) -> None:
        """The slide's reads are done, so it is exported; its close is bounded, so the deck
        takes less than one slide's deadline; and one line says how the browser ended."""
        deadline_seconds = _deadline_ms() / 1000
        assert export.failures == [], export.failures
        texts = _deck_texts(export.pptx, 3)
        assert all(f"Slide {number}" in text for number, text in enumerate(texts, start=1)), texts
        assert export.elapsed < deadline_seconds, (
            f"the deck took {export.elapsed:.1f}s: the close was waited for, not bounded"
        )
        killed = [line for line in export.stderr.splitlines() if KILLED_LINE in line]
        assert len(killed) == 1, export.stderr[-3000:]
        assert outcome in killed[0], killed


# The waits render_slide.cjs and capture.cjs bound themselves, each read from its module:
# network idle, the fonts (before and after the animations finish), the canvases' buffers
# and their settle, and one capture (a slide's captures stop at the first that times out).
_BOUNDED_WAITS = (
    ("render_slide", "NETWORK_IDLE_TIMEOUT_MS", 1),
    ("render_slide", "FONTS_READY_TIMEOUT_MS", 2),
    ("render_slide", "CANVAS_READY_TIMEOUT_MS", 1),
    ("render_slide", "CANVAS_SETTLE_MS", 1),
    ("capture", "CAPTURE_TIMEOUT_MS", 1),
)


@requires_node
def test_the_deadline_is_above_every_wait_the_engine_bounds_itself() -> None:
    modules = {"render_slide": RENDER_SLIDE, "capture": CAPTURE}
    names = {(module, name) for module, name, _ in _BOUNDED_WAITS}
    read = node_json(
        "const read = {};"
        + "".join(
            f"read[{json.dumps(module + '.' + name)}] = require({json.dumps(str(modules[module]))})"
            f".{name};"
            for module, name in sorted(names)
        )
        + f"read.deadline = require({json.dumps(str(RENDER_SLIDE))}).SLIDE_DEADLINE_MS;"
        + "console.log(JSON.stringify(read));"
    )
    waits = [read[f"{module}.{name}"] * times for module, name, times in _BOUNDED_WAITS]
    assert all(isinstance(wait, int) and wait > 0 for wait in waits), read
    assert read["deadline"] > sum(waits), (
        f"the {read['deadline']} ms deadline would fail a slide the engine's own waits "
        f"({sum(waits)} ms) let through"
    )
