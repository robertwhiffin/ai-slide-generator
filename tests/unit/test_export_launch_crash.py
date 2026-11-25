"""A slide whose browser crashes before its page loads is relaunched once.

Measured on a deployed app, under four exports at once: one Chromium of 420 crashed at its
launch (SIGSEGV), and its slide was lost, the user given 27 of 28 slides. No page of the slide
had been loaded, so nothing of the slide's own made it fail. Now ``render_slide.cjs`` launches
that slide's browser once more, inside the same per-slide deadline, and logs one line naming
how the browser exited (its signal or its exit code), which holds no text of the slide's. A
second exit fails the slide as before. A slide that failed for its own content (it navigated
away, it ran past its deadline, its page broke a read) is never relaunched, nor is a browser
that never started (its executable missing): only one that exited before the page loaded.

The seam is the deadline tests' (``test_export_slide_deadline.py``): a preload, loaded into the
real sidecar through ``NODE_OPTIONS``, wraps Playwright's ``chromium.launch``. On the launches a
case names it gives Playwright an executable that dies as asked, a signal or an exit code, so
Playwright fails the launch as it failed the measured one ("Target page, context or browser has
been closed", its log naming the exit); or it kills the real browser while its context opens,
and can tell node of that browser's exit only once its context has failed, as a loaded CI runner
did, so the line must wait for the exit to name it. It records each launch and, at each launch
and at node's exit, which earlier browsers still run.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.services import pptx_from_html_huashu
from tests.fixtures.export_snapshot_support import (
    export_logged,
    node_json,
    requires_huashu_sidecar,
    slide_document,
    slide_xml,
)

RENDER_SLIDE = pptx_from_html_huashu.SIDECAR_DIR / "render_slide.cjs"
# A deck timeout of half the real one, well past what any case here takes.
DECK_TIMEOUT_SECONDS = 90
# A word no slide holds by chance: no line about a browser's exit may carry it.
PLANTED_WORD = "Glimmerquartz"

# The line a slide whose browser exited before its page loaded logs (render_slide.cjs).
EXIT_LINE = "[html2pptx] the slide's browser exited before its page loaded"
RELAUNCHED = "relaunching it once"
FAILED_AGAIN = "it exited again once relaunched, so the slide fails"
# What Playwright's launch says of a browser that exited before it connected: the measured
# failure's first line, which the slide's failure keeps.
LAUNCH_CLOSED = "browserType.launch: Target page, context or browser has been closed"
# The failures of a slide's own content.
NAVIGATED_AWAY = "the slide's page navigated away from the slide"
PAST_ITS_DEADLINE = "did not finish within"

# Executables Playwright is given in a real browser's place: each dies as its name says,
# after DELAY seconds (0 unless a case sets it).
DYING_BROWSERS = {
    "signal": "#!/bin/sh\nsleep %(delay)s\nkill -SEGV $$\n",
    "exit": "#!/bin/sh\nsleep %(delay)s\nexit 3\n",
}
# What the exit line says of each.
EXIT_WORDS = {"signal": "on signal SIGSEGV", "exit": "with exit code 3"}
# What it says of an exit node has not been told of.
EXIT_STATUS_UNREAD = "its exit status unread"
# The whole line of a browser that exited as its context opened and is relaunched, how it
# exited in the place of %s: its fixed wording, which holds nothing of the slide's.
CONTEXT_EXIT_LINE = EXIT_LINE + " (at its context, %s): " + RELAUNCHED
# How much less than what is left of its slide's deadline a launch may be given: the time the
# engine takes from reading its clock to calling the launch.
LAUNCH_TIMEOUT_SLACK_MS = 500

# Loaded into the real sidecar (NODE_OPTIONS --import). CRASHES maps a launch's number, from
# 1 across the deck, to the executable it is launched with instead of the browser, or to
# "context": the real browser, killed with SIGSEGV as its context opens. EXIT_DELAYS maps a
# "context" launch's number to how many ms after its context has failed node is told of its
# browser's exit (its exit code or signal set, its 'exit' emitted), as a loaded runner was
# told only after the browser's pipe had closed. Each launch is recorded, with the process
# groups of the earlier browsers still running then; so is each "context" launch's failed
# context, with whether node had its browser's exit then, and node's exit. The exit handler
# is registered before Playwright's, which kills the browsers it launched, so a browser the
# engine left running is still seen there.
CRASHING_LAUNCH_PRELOAD = """
import fs from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(%(sidecar)s);
const { chromium } = require('playwright-core');
const RECORD = %(record)s;
const CRASHES = %(crashes)s;
const EXIT_DELAYS = %(exit_delays)s;
const launched = [];
let launches = 0;
function running(pid) {
  try {
    process.kill(-pid, 0);
    return true;
  } catch (error) {
    return error.code === 'EPERM';
  }
}
function record(at, fields = {}) {
  const entry = { at, now: Date.now(), running: launched.filter(running), ...fields };
  fs.appendFileSync(RECORD, JSON.stringify(entry) + '\\n');
}
process.on('exit', () => record('exit'));
const launch = chromium.launch.bind(chromium);
chromium.launch = async (options) => {
  launches += 1;
  const number = launches;
  record('launch ' + number, { timeout: options.timeout });
  const crash = CRASHES[String(number)];
  if (crash && crash !== 'context') return launch({ ...options, executablePath: crash });
  const earlier = launched.slice();
  const browser = await launch(options);
  const browserProcess = browser._connection.toImpl(browser).options.browserProcess.process;
  launched.push(browserProcess.pid);
  if (crash === 'context') {
    const exitDelay = EXIT_DELAYS[String(number)];
    let contextFailed;
    const failedContext = new Promise((resolve) => { contextFailed = resolve; });
    if (exitDelay !== undefined) {
      const handle = browserProcess._handle;
      const onexit = handle.onexit;
      handle.onexit = (...exitArguments) => failedContext.then(() =>
        setTimeout(() => onexit.apply(handle, exitArguments), exitDelay));
    }
    const newContext = browser.newContext.bind(browser);
    browser.newContext = (...contextArguments) => {
      const opening = newContext(...contextArguments);
      process.kill(browserProcess.pid, 'SIGSEGV');
      opening.catch(() => {
        record('context failed ' + number, {
          running: earlier.filter(running),
          exitReached: browserProcess.exitCode !== null || browserProcess.signalCode !== null,
        });
        contextFailed();
      });
      return opening;
    };
  }
  return browser;
};
"""


def _slide(heading: str, script: str = "") -> str:
    return (
        f'<div class="slide"><h1>{heading}</h1><p>{PLANTED_WORD} revenue grew 12%.</p>'
        f"{script}</div>"
    )


def _documents(*slides: str) -> list[str]:
    return [
        slide_document(body, slide_id=f"launch-crash-{index}")
        for index, body in enumerate(slides, start=1)
    ]


def _three_slides() -> list[str]:
    return _documents(*(_slide(f"Slide {number}") for number in (1, 2, 3)))


@dataclass(frozen=True)
class _CrashedExport:
    """A deck exported with some of its launches crashing."""

    pptx: bytes
    failures: list[dict]
    stderr: str
    elapsed: float  # seconds
    # Each launch, with the timeout it was given, and node's exit, each with the earlier
    # browsers' process groups still running then.
    record: list[dict]

    def exit_lines(self) -> list[str]:
        return [line for line in self.stderr.splitlines() if EXIT_LINE in line]

    def texts(self, count: int) -> list[str]:
        return ["".join(slide_xml(self.pptx, index).itertext()) for index in range(count)]


def _export(
    documents: list[str],
    crashes: dict[int, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    delay: float = 0,
    exit_delays: dict[int, float] | None = None,
) -> _CrashedExport:
    """``documents`` exported, launch ``n`` crashing as ``crashes[n]`` says.

    A crash is a ``DYING_BROWSERS`` name, ``"context"``, or a path, used as the executable.
    ``exit_delays[n]``, for a ``"context"`` launch, is how many ms after its browser's exit
    node is told of it.
    """
    executables = {}
    for name, script in DYING_BROWSERS.items():
        executable = tmp_path / f"dying_browser_{name}.sh"
        executable.write_text(script % {"delay": delay}, encoding="utf-8")
        executable.chmod(0o755)
        executables[name] = str(executable)
    record = tmp_path / "launches.jsonl"
    preload = tmp_path / "crashing_launch.mjs"
    preload.write_text(
        CRASHING_LAUNCH_PRELOAD
        % {
            "sidecar": json.dumps(str(pptx_from_html_huashu.SIDECAR_SCRIPT)),
            "record": json.dumps(str(record)),
            "crashes": json.dumps(
                {str(launch): executables.get(how, how) for launch, how in crashes.items()}
            ),
            "exit_delays": json.dumps(
                {str(launch): delay_ms for launch, delay_ms in (exit_delays or {}).items()}
            ),
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
    logged = export_logged(documents, monkeypatch=monkeypatch)
    return _CrashedExport(
        pptx=logged.pptx,
        failures=logged.failures,
        stderr=logged.stderr,
        elapsed=time.monotonic() - started,
        record=[json.loads(line) for line in record.read_text(encoding="utf-8").splitlines()],
    )


def _launches(export: _CrashedExport) -> int:
    return sum(1 for entry in export.record if entry["at"].startswith("launch "))


def _render_slide_constant(name: str) -> object:
    """What ``render_slide.cjs`` exports as ``name``."""
    return node_json(f"console.log(require({json.dumps(str(RENDER_SLIDE))}).{name})")


def _failed_context(export: _CrashedExport, launch: int) -> dict:
    """The record of launch ``launch``'s failed context, which a "context" crash makes."""
    (failed,) = [entry for entry in export.record if entry["at"] == f"context failed {launch}"]
    return failed


def _assert_no_browser_outlives_its_slide(export: _CrashedExport) -> None:
    left = {entry["at"]: entry["running"] for entry in export.record if entry["running"]}
    assert not left, f"browser process groups still running: {left}"


def _assert_holds_no_slide_text(lines: list[str]) -> None:
    for line in lines:
        assert PLANTED_WORD not in line and "Slide " not in line, line


@pytest.mark.slow
@requires_huashu_sidecar
class TestABrowserThatCrashesBeforeItsPageIsRelaunched:
    @pytest.mark.parametrize("how", ["signal", "exit"])
    def test_a_crash_at_launch_is_relaunched_once_and_the_slide_kept(
        self, how: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The second slide's first launch dies; its second launches, and the deck is whole.

        One line says so, naming the exit, and holds nothing of the slide's.
        """
        export = _export(_three_slides(), {2: how}, tmp_path, monkeypatch)

        assert export.failures == [], export.failures
        texts = export.texts(3)
        assert all(f"Slide {number}" in text for number, text in enumerate(texts, 1)), texts
        assert _launches(export) == 4, export.record
        (line,) = export.exit_lines()
        assert "at its launch" in line and EXIT_WORDS[how] in line and RELAUNCHED in line, line
        _assert_holds_no_slide_text([line])
        _assert_no_browser_outlives_its_slide(export)

    def test_a_second_crash_fails_the_slide_as_before(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both of the second slide's launches die: it fails with the launch's own failure,
        the other two are written, and each exit is one line."""
        export = _export(_three_slides(), {2: "signal", 3: "signal"}, tmp_path, monkeypatch)

        assert [failure["slide_index"] for failure in export.failures] == [1], export.failures
        assert export.failures[0]["error"].startswith(LAUNCH_CLOSED), export.failures
        texts = export.texts(2)
        assert "Slide 1" in texts[0] and "Slide 3" in texts[1], texts
        assert _launches(export) == 4, export.record
        first, second = export.exit_lines()
        assert RELAUNCHED in first and FAILED_AGAIN in second, (first, second)
        assert all(EXIT_WORDS["signal"] in line for line in (first, second))
        _assert_holds_no_slide_text([first, second])
        fail_lines = [line for line in export.stderr.splitlines() if "[2/3] FAIL:" in line]
        assert len(fail_lines) == 1 and LAUNCH_CLOSED in fail_lines[0], fail_lines

    def test_a_crash_while_its_context_opens_is_relaunched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The browser launched, and died before the slide's page was opened: as a launch's."""
        export = _export(_three_slides(), {2: "context"}, tmp_path, monkeypatch)

        assert export.failures == [], export.failures
        assert _launches(export) == 4, export.record
        (line,) = export.exit_lines()
        assert "at its context" in line and EXIT_WORDS["signal"] in line, line
        _assert_no_browser_outlives_its_slide(export)

    def test_an_exit_node_is_told_of_after_its_context_failed_is_named(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Node is told of the browser's exit only after its context has failed, as a loaded
        CI runner was, whose line said its exit status unread. The engine waits for it, up to
        EXIT_STATUS_WAIT_MS: the line names the signal, in its fixed wording."""
        wait_ms = _render_slide_constant("EXIT_STATUS_WAIT_MS")

        export = _export(
            _three_slides(), {2: "context"}, tmp_path, monkeypatch, exit_delays={2: wait_ms / 5}
        )

        assert _failed_context(export, 2)["exitReached"] is False, (
            "fixture drift: node had the browser's exit when its context failed"
        )
        assert export.failures == [], export.failures
        assert _launches(export) == 4, export.record
        (line,) = export.exit_lines()
        assert line.endswith(CONTEXT_EXIT_LINE % EXIT_WORDS["signal"]), line
        _assert_holds_no_slide_text([line])
        _assert_no_browser_outlives_its_slide(export)

    def test_an_exit_node_is_not_told_of_within_the_wait_is_said_unread(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Node is told of the browser's exit only well past the engine's wait for it: the
        line says its exit status unread rather than hold the slide for it, and the slide is
        relaunched and kept."""
        wait_ms = _render_slide_constant("EXIT_STATUS_WAIT_MS")

        export = _export(
            _three_slides(), {2: "context"}, tmp_path, monkeypatch, exit_delays={2: wait_ms * 3}
        )

        assert _failed_context(export, 2)["exitReached"] is False, (
            "fixture drift: node had the browser's exit when its context failed"
        )
        assert export.failures == [], export.failures
        assert "Slide 2" in export.texts(3)[1], export.texts(3)
        assert _launches(export) == 4, export.record
        (line,) = export.exit_lines()
        assert line.endswith(CONTEXT_EXIT_LINE % EXIT_STATUS_UNREAD), line
        _assert_holds_no_slide_text([line])
        _assert_no_browser_outlives_its_slide(export)

    def test_the_relaunch_is_within_the_same_deadline(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The first launch dies 5 s before the deadline, the relaunch would die 10 s after
        it: the slide fails at its one deadline, not at a second one or the relaunch's exit.

        Each launch is given what is left of the deadline as Playwright's own timeout: the
        whole deadline first, the 5 s left then."""
        deadline_seconds = node_json(
            f"console.log(require({json.dumps(str(RENDER_SLIDE))}).SLIDE_DEADLINE_MS)"
        ) / 1000
        documents = _documents(_slide("Slide 1"))
        delays = {1: deadline_seconds - 5, 2: 10}
        executables = {}
        for launch, delay in delays.items():
            executable = tmp_path / f"slow_dying_browser_{launch}.sh"
            executable.write_text(DYING_BROWSERS["signal"] % {"delay": delay}, encoding="utf-8")
            executable.chmod(0o755)
            executables[launch] = str(executable)

        export = _export(documents, executables, tmp_path, monkeypatch)

        assert [failure["slide_index"] for failure in export.failures] == [0], export.failures
        assert PAST_ITS_DEADLINE in export.failures[0]["error"], export.failures
        assert export.elapsed < deadline_seconds + 10, (
            f"the deck took {export.elapsed:.1f}s with a {deadline_seconds:g}s deadline"
        )
        (line,) = export.exit_lines()
        assert RELAUNCHED in line, line
        launches = [entry for entry in export.record if entry["at"] != "exit"]
        assert len(launches) == 2, export.record
        for launch in launches:
            left = deadline_seconds * 1000 - (launch["now"] - launches[0]["now"])
            assert left - LAUNCH_TIMEOUT_SLACK_MS < launch["timeout"] <= left, (
                f"{launch['at']} was given {launch['timeout']} ms with {left} ms of its "
                "deadline left"
            )


@pytest.mark.slow
@requires_huashu_sidecar
class TestNothingElseIsRelaunched:
    def test_a_browser_that_never_started_is_not_relaunched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Its executable missing: no browser ran, so none exited; the slide fails as before."""
        export = _export(
            _three_slides(), {2: str(tmp_path / "no-such-browser")}, tmp_path, monkeypatch
        )

        assert [failure["slide_index"] for failure in export.failures] == [1], export.failures
        assert _launches(export) == 3, export.record
        assert export.exit_lines() == [], export.exit_lines()

    def test_no_slide_that_failed_for_its_own_content_is_relaunched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A slide that navigates away, one whose page breaks a read, one blocked past its
        deadline: each fails once, on its one launch, and the fourth slide is written."""
        documents = _documents(
            _slide("Leaving", "<script>location.href = 'https://example.org/elsewhere';</script>"),
            _slide(
                "Broken read",
                "<script>window.getComputedStyle = () => { throw new Error('no style'); };"
                "</script>",
            ),
            _slide(
                "Blocked",
                "<script>addEventListener('load', () => setTimeout(() => { for (;;) {} }, 0));"
                "</script>",
            ),
            _slide("Kept"),
        )

        export = _export(documents, {}, tmp_path, monkeypatch)

        assert [failure["slide_index"] for failure in export.failures] == [0, 1, 2], (
            export.failures
        )
        errors = [failure["error"] for failure in export.failures]
        assert NAVIGATED_AWAY in errors[0], errors
        assert re.search(r"no style", errors[1]), errors
        assert PAST_ITS_DEADLINE in errors[2], errors
        assert "Kept" in export.texts(1)[0]
        assert _launches(export) == 4, export.record
        assert export.exit_lines() == [], export.exit_lines()
        _assert_no_browser_outlives_its_slide(export)
