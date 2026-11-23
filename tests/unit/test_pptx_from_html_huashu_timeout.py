"""A sidecar that runs past its timeout takes every process it started with it.

``build_pptx_huashu`` runs ``node emit_deck.mjs``, which launches Chromium for
each slide through Playwright, and the admin ``install-chromium`` and
``probe-launch`` routes run node scripts that download or launch it. Playwright
launches each browser ``detached``, the leader of a process group of its own, and
kills that group from node's ``exit`` handler. So a sidecar that overruns its
timeout must end through node's exit path: ``run_sidecar_process`` sends SIGTERM
to the sidecar's own process group, which the scripts answer with
``process.exit(143)``, and SIGKILLs the group only as a backstop. Killing node
outright would leave its browser running with no parent, holding its memory
until the app restarts.

The stub sidecars here stand in for node's scripts and behave as they do: a
detached child that only their exit handler kills (the browser), and a child in
their own group (anything else they start). Each records its process ids where
the test reads them, sleeps past a short timeout, and exits by itself after
``STUB_LIFETIME_SECONDS``, so no fault in the helper can hang the test: a helper
that waits for the stub is caught by the elapsed-time assertion instead. The
real-browser cases run the real scripts on a browser that never finishes.

Every export, however it ends, also logs one ``[huashu] export summary {json}``
line (``TestEveryExportLogsOneSummary`` and the classes after it): counts,
timings and the peak memory of the sidecar's process tree, read while it runs.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import NamedTuple

import pytest

from src.api.routes import export as export_routes
from src.services import pptx_from_html_huashu
from src.services.pptx_from_html_huashu import HuashuExportError
from tests.fixtures.export_snapshot_support import (
    CORPUS_DECK,
    CORPUS_DIR,
    TEST_DECK_TITLE,
    build_pptx_guarded,
    pinned_font_css,
    requires_huashu_sidecar,
    requires_node,
    slide_document,
)
from tests.unit.test_export_svg_raster import structural_manifest

REPO_ROOT = Path(__file__).resolve().parents[2]
# A fresh interpreter imports the wrapper within this.
MODULE_LOAD_TIMEOUT_SECONDS = 60

# Short enough to keep the stub tests quick, long enough for node to start the
# stub and write its process ids first.
STUB_TIMEOUT_SECONDS = 3
# A stub ends itself after this long whatever the helper does: past every bound below.
STUB_LIFETIME_SECONDS = 30
# How long a killed process may take to be gone: reaped by its parent, or by
# launchd/init once its parent is gone too.
GONE_WITHIN_SECONDS = 10
# The longest a timed-out run may take to return: its timeout, the helper's
# SIGTERM grace, its process listing and its bounded waits after the SIGKILL,
# with slack.
RETURN_SLACK_SECONDS = 4 * pptx_from_html_huashu.SIDECAR_TERM_GRACE_SECONDS + 3

# The real sidecar's timeout for a slide that never loads: long enough for the
# browser to launch, so the test sees the browser it must not leave behind.
HUNG_SLIDE_TIMEOUT_SECONDS = 10
# A slide whose script never yields: its page never loads, so the export waits
# on it until the timeout.
HUNG_SLIDE = (
    "<!doctype html><html><body><div class='slide'><p>hung</p></div>"
    "<script>while (true) {}</script></body></html>"
)
# What only Playwright's launched browser processes carry on their command line.
PLAYWRIGHT_BROWSER_FLAG = "--remote-debugging-pipe"
# Playwright makes each browser's profile in a directory of its own under the
# launching node's TMPDIR, named with this prefix, and names it on the browser's
# command line (--user-data-dir), so a browser says which run's TMPDIR it is of.
PLAYWRIGHT_PROFILE_PREFIX = "playwright_chromiumdev_profile-"

# A stub node script. The browser child is detached and killed (its group) by
# the stub's exit handler, as Playwright does; the helper child stays in the
# stub's group; SIGTERM ends the stub through its exit path, as the real
# scripts do (emit_deck.mjs, probe_launch.mjs).
STUB_SCRIPT = """
import { spawn } from 'node:child_process';
import fs from 'node:fs';
const browser = spawn('sleep', ['600'], { detached: true, stdio: 'ignore' });
process.on('exit', () => {
  try { process.kill(-browser.pid, 'SIGKILL'); } catch (error) { /* already gone */ }
});
const helper = spawn('sleep', ['600'], { stdio: 'ignore' });
process.on('SIGTERM', () => process.exit(143));
fs.writeFileSync(
  %(pids)s, JSON.stringify({ sidecar: process.pid, browser: browser.pid, helper: helper.pid })
);
setTimeout(() => process.exit(0), %(lifetime_ms)d);
setInterval(() => {}, 1000);
"""

# A stub that ignores SIGTERM: only the helper's SIGKILL backstop ends it.
STUB_IGNORING_SIGTERM = """
import { spawn } from 'node:child_process';
import fs from 'node:fs';
const helper = spawn('sleep', ['600'], { stdio: 'ignore' });
process.on('SIGTERM', () => {});
fs.writeFileSync(%(pids)s, JSON.stringify({ sidecar: process.pid, helper: helper.pid }));
setTimeout(() => process.exit(0), %(lifetime_ms)d);
setInterval(() => {}, 1000);
"""

# node exits at once, leaving a detached child that holds its stdout and
# stderr: the pipes outlive node, so its run times out with node a zombie that
# leads a group of no other member (on macOS, killpg on it answers EPERM).
STUB_EXITS_LEAVING_ITS_PIPES = """
import { spawn } from 'node:child_process';
import fs from 'node:fs';
const holder = spawn(
  'sleep', ['%(lifetime_s)d'], { detached: true, stdio: ['ignore', 'inherit', 'inherit'] }
);
fs.writeFileSync(%(pids)s, JSON.stringify({ sidecar: process.pid, holder: holder.pid }));
holder.unref();
process.exit(0);
"""

# node starts a detached browser and then blocks its own event loop, so its
# SIGTERM handler, which would exit through the exit handler that kills the
# browser, never runs. It ends itself after the lifetime, the loop still blocked.
STUB_BLOCKED_LOOP = """
import { spawn } from 'node:child_process';
import fs from 'node:fs';
const browser = spawn('sleep', ['%(lifetime_s)d'], { detached: true, stdio: 'ignore' });
process.on('exit', () => {
  try { process.kill(-browser.pid, 'SIGKILL'); } catch (error) { /* already gone */ }
});
process.on('SIGTERM', () => process.exit(143));
fs.writeFileSync(%(pids)s, JSON.stringify({ sidecar: process.pid, browser: browser.pid }));
const until = Date.now() + %(lifetime_s)d * 1000;
while (Date.now() < until) { /* the event loop blocked */ }
process.exit(0);
"""

# Loaded into the real emit_deck.mjs through NODE_OPTIONS: once its browser has
# loaded the slide, node blocks its event loop for good, so no handler of
# node's runs. A browser with a page open outlives node's pipe closing (Chrome
# on macOS: seven processes measured); one with none exits by itself.
BLOCKING_LAUNCH_PRELOAD = """
import { createRequire } from 'node:module';
const require = createRequire(%(sidecar)s);
const { chromium } = require('playwright-core');
const launch = chromium.launch.bind(chromium);
chromium.launch = async (options) => {
  const browser = await launch(options);
  const newContext = browser.newContext.bind(browser);
  browser.newContext = async (...contextArguments) => {
    const context = await newContext(...contextArguments);
    const newPage = context.newPage.bind(context);
    context.newPage = async (...pageArguments) => {
      const page = await newPage(...pageArguments);
      const goto = page.goto.bind(page);
      page.goto = async (...gotoArguments) => {
        await goto(...gotoArguments);
        for (;;) { /* the event loop blocked */ }
      };
      return page;
    };
    return context;
  };
  return browser;
};
"""

# Loaded into the real probe_launch.mjs through NODE_OPTIONS: the browser it
# launches never hands out a context, so the probe waits on it until the timeout.
HANGING_LAUNCH_PRELOAD = """
import { createRequire } from 'node:module';
const require = createRequire(%(sidecar)s);
const { chromium } = require('playwright-core');
const launch = chromium.launch.bind(chromium);
chromium.launch = async (options) => {
  const browser = await launch(options);
  browser.newContext = () => new Promise(() => {});
  return browser;
};
"""


def _alive(pid: int) -> bool:
    """Whether a process with this id exists (a zombie not yet reaped counts)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _still_alive(pids: list[int]) -> list[int]:
    """The ids still alive once ``GONE_WITHIN_SECONDS`` have passed, or [] as soon as none is."""
    deadline = time.monotonic() + GONE_WITHIN_SECONDS
    while True:
        alive = [pid for pid in pids if _alive(pid)]
        if not alive or time.monotonic() > deadline:
            return alive
        time.sleep(0.1)


def _kill(pids: list[int]) -> None:
    for pid in pids:
        if _alive(pid):
            os.kill(pid, signal.SIGKILL)


def _write_stub(path: Path, pids_path: Path, script: str = STUB_SCRIPT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        script % {"pids": json.dumps(str(pids_path)), "lifetime_ms": STUB_LIFETIME_SECONDS * 1000},
        encoding="utf-8",
    )


def _playwright_browsers(scope: str) -> dict[int, int]:
    """The running Playwright browsers launched under TMPDIR ``scope``: pid -> process group id.

    Under it: an export runs its sidecar with a TMPDIR of its own, a directory it
    makes inside the TMPDIR it is given (pptx_from_html_huashu._export_deck), so a
    browser's profile is in ``scope`` or in a directory under it. Only those: a
    browser another run on the machine launched (another test run, a developer's
    own) is not this run's to watch or kill.
    """
    profile = re.compile(
        re.escape(f"{scope}/") + r"(?:[^/\s]+/)*" + re.escape(PLAYWRIGHT_PROFILE_PREFIX)
    )
    listing = subprocess.run(
        ["ps", "-axo", "pid=,pgid=,command="], capture_output=True, text=True, check=True
    ).stdout
    browsers = {}
    for line in listing.splitlines():
        fields = line.split(None, 2)
        if len(fields) == 3 and PLAYWRIGHT_BROWSER_FLAG in fields[2] and profile.search(fields[2]):
            browsers[int(fields[0])] = int(fields[1])
    return browsers


def _group_members(groups: set[int]) -> list[int]:
    """Every running process in any of ``groups``."""
    listing = subprocess.run(
        ["ps", "-axo", "pid=,pgid="], capture_output=True, text=True, check=True
    ).stdout
    return [
        int(pid)
        for pid, group in (line.split() for line in listing.splitlines() if line.strip())
        if int(group) in groups
    ]


class _BrowserWatch:
    """The Playwright browsers of its run that start while it watches, with their process groups.

    Its run is every node launched with TMPDIR ``scope`` or a directory under it
    (``browser_watch`` sets it for the test).
    """

    def __init__(self, scope: str) -> None:
        self._scope = scope
        self._before = set(_playwright_browsers(scope))
        self.seen: dict[int, int] = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()

    def _watch(self) -> None:
        while not self._stop.is_set():
            for pid, group in _playwright_browsers(self._scope).items():
                if pid not in self._before:
                    self.seen[pid] = group
            time.sleep(0.2)

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()

    def end(self) -> None:
        """Stop watching, and SIGKILL the group of every browser it saw."""
        self.stop()
        for group in set(self.seen.values()):
            try:
                os.killpg(group, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def survivors(self) -> list[int]:
        """The processes of the browsers' groups still alive after ``GONE_WITHIN_SECONDS``."""
        groups = set(self.seen.values())
        deadline = time.monotonic() + GONE_WITHIN_SECONDS
        while True:
            alive = _group_members(groups)
            if not alive or time.monotonic() > deadline:
                return alive

            time.sleep(0.2)


@pytest.fixture
def browser_watch(monkeypatch: pytest.MonkeyPatch) -> Iterator[_BrowserWatch]:
    """A watch over the browsers this test's nodes launch: each gets TMPDIR of the watch's own.

    TMPDIR reaches every sidecar through ``sidecar_subprocess_env``, and an export's
    sidecar gets a directory the export makes under it. It is a short
    path under /tmp because Chrome makes its singleton socket under TMPDIR, and a
    socket path may not be much longer than 100 bytes.
    """
    scope = tempfile.mkdtemp(prefix="tellr-watch-", dir="/tmp")
    monkeypatch.setenv("TMPDIR", scope)
    watch = _BrowserWatch(scope)
    try:
        yield watch
    finally:
        watch.end()
        shutil.rmtree(scope, ignore_errors=True)


@requires_node
class TestTheHelperEndsTheWholeSidecar:
    def test_a_timed_out_sidecar_leaves_no_process_behind(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Its detached browser (killed by its exit handler) and the child in its group both go."""
        pids_path = tmp_path / "pids.json"
        stub = tmp_path / "stub_sidecar.mjs"
        _write_stub(stub, pids_path)
        monkeypatch.setattr(pptx_from_html_huashu, "SIDECAR_SCRIPT", stub)
        monkeypatch.setattr(
            pptx_from_html_huashu, "SIDECAR_TIMEOUT_SECONDS", STUB_TIMEOUT_SECONDS
        )
        monkeypatch.setattr(pptx_from_html_huashu, "is_available", lambda: True)

        started = time.monotonic()
        with pytest.raises(HuashuExportError, match="timed out"):
            pptx_from_html_huashu.build_pptx_huashu("deck", [{"html": "<p>x</p>"}])
        elapsed = time.monotonic() - started

        pids = json.loads(pids_path.read_text(encoding="utf-8"))
        everything = [pids["sidecar"], pids["browser"], pids["helper"]]
        try:
            assert elapsed < STUB_TIMEOUT_SECONDS + RETURN_SLACK_SECONDS, (
                f"the timed-out export took {elapsed:.1f}s to return"
            )
            alive = _still_alive(everything)
            assert alive == [], (
                f"still running {GONE_WITHIN_SECONDS}s after the timeout: {alive} "
                f"(sidecar {pids['sidecar']}, its detached browser {pids['browser']}, "
                f"its child {pids['helper']})"
            )
        finally:
            _kill(everything)

    def test_a_sidecar_that_ignores_sigterm_is_killed(self, tmp_path: Path) -> None:
        """The SIGKILL backstop: a group outliving the grace period is killed, the wait bounded."""
        pids_path = tmp_path / "pids.json"
        stub = tmp_path / "stub_ignoring_sigterm.mjs"
        _write_stub(stub, pids_path, STUB_IGNORING_SIGTERM)

        started = time.monotonic()
        with pytest.raises(subprocess.TimeoutExpired):
            pptx_from_html_huashu.run_sidecar_process(
                ["node", str(stub)], input=b"", timeout=STUB_TIMEOUT_SECONDS
            )
        elapsed = time.monotonic() - started

        pids = json.loads(pids_path.read_text(encoding="utf-8"))
        everything = [pids["sidecar"], pids["helper"]]
        try:
            assert elapsed < STUB_TIMEOUT_SECONDS + RETURN_SLACK_SECONDS, (
                f"the timed-out run took {elapsed:.1f}s to return"
            )
            assert _still_alive(everything) == []
        finally:
            _kill(everything)

    def test_a_sidecar_that_exits_leaves_no_child_behind(self, tmp_path: Path) -> None:
        """After any exit, a failing one included, the sidecar's group is swept."""
        pids_path = tmp_path / "pids.json"
        stub = tmp_path / "stub_exits.mjs"
        stub.write_text(
            "import { spawn } from 'node:child_process';\n"
            "import fs from 'node:fs';\n"
            "const helper = spawn('sleep', ['600'], { stdio: 'ignore' });\n"
            f"fs.writeFileSync({json.dumps(str(pids_path))}, "
            "JSON.stringify({ sidecar: process.pid, helper: helper.pid }));\n"
            "process.stderr.write('boom\\n');\n"
            "process.exit(1);\n",
            encoding="utf-8",
        )

        result = pptx_from_html_huashu.run_sidecar_process(
            ["node", str(stub)], input=b"", timeout=STUB_LIFETIME_SECONDS
        )

        pids = json.loads(pids_path.read_text(encoding="utf-8"))
        try:
            assert (result.returncode, result.stderr) == (1, b"boom\n")
            assert _still_alive([pids["helper"]]) == []
        finally:
            _kill([pids["sidecar"], pids["helper"]])


@requires_node
class TestASidecarWhoseLoopIsBlocked:
    def test_its_detached_browser_is_swept(self, tmp_path: Path) -> None:
        """No handler of node's can run: the helper kills its detached child's group itself."""
        pids_path = tmp_path / "pids.json"
        stub = tmp_path / "stub_blocked_loop.mjs"
        stub.write_text(
            STUB_BLOCKED_LOOP
            % {"pids": json.dumps(str(pids_path)), "lifetime_s": STUB_LIFETIME_SECONDS},
            encoding="utf-8",
        )

        started = time.monotonic()
        with pytest.raises(subprocess.TimeoutExpired):
            pptx_from_html_huashu.run_sidecar_process(
                ["node", str(stub)], input=b"", timeout=STUB_TIMEOUT_SECONDS
            )
        elapsed = time.monotonic() - started

        pids = json.loads(pids_path.read_text(encoding="utf-8"))
        everything = [pids["sidecar"], pids["browser"]]
        try:
            assert elapsed < STUB_TIMEOUT_SECONDS + RETURN_SLACK_SECONDS, elapsed
            alive = _still_alive(everything)
            assert alive == [], f"still running after the timeout: {alive} of {pids}"
        finally:
            _kill(everything)


class TestTheProcessTable:
    """What the blocked-sidecar sweep reads: every process as (pid, ppid, pgid)."""

    def test_it_holds_this_process(self) -> None:
        table = pptx_from_html_huashu._process_table()
        assert (os.getpid(), os.getppid(), os.getpgrp()) in table

    def test_a_malformed_entry_is_skipped(self, tmp_path: Path) -> None:
        """A stat line that does not parse (no closing parenthesis, no numbers) is no process."""
        for pid, stat in {
            "self": "7 (python) S 1 7 7 0",
            "7": "7 (python) S 1 7 7 0",
            "8": "8 (truncated",
            "9": "9 (node) S not-a-number 9 9 0",
        }.items():
            (tmp_path / pid).mkdir()
            (tmp_path / pid / "stat").write_text(stat, encoding="utf-8")

        assert pptx_from_html_huashu._process_table(tmp_path) == [(7, 1, 7)]

    def test_it_reads_proc_whatever_a_command_name_holds(self, tmp_path: Path) -> None:
        """Linux: /proc/<pid>/stat, whose command name can hold spaces and parentheses."""
        for pid, stat in {
            "self": "7 (python) S 1 7 7 0",
            "7": "7 (python) S 1 7 7 0",
            "42": "42 (Chrome (helper) x) S 7 42 42 0",
            "43": "43 (node) R 7 7 7 0",
        }.items():
            (tmp_path / pid).mkdir()
            (tmp_path / pid / "stat").write_text(stat, encoding="utf-8")
        (tmp_path / "meminfo").write_text("not a process", encoding="utf-8")

        table = pptx_from_html_huashu._process_table(tmp_path)

        assert sorted(table) == [(7, 1, 7), (42, 7, 42), (43, 7, 7)]


def _open_descriptors() -> int:
    """How many file descriptors this process holds open."""
    return len(os.listdir("/dev/fd"))


@requires_node
class TestASidecarWhosePipesOutliveIt:
    def test_its_run_is_reported_as_timed_out_and_cleaned_up(self, tmp_path: Path) -> None:
        """A timeout, node reaped and the pipes closed, though its group is a zombie alone."""
        pids_path = tmp_path / "pids.json"
        stub = tmp_path / "stub_exits_leaving_its_pipes.mjs"
        stub.write_text(
            STUB_EXITS_LEAVING_ITS_PIPES
            % {"pids": json.dumps(str(pids_path)), "lifetime_s": STUB_LIFETIME_SECONDS},
            encoding="utf-8",
        )
        descriptors = _open_descriptors()

        started = time.monotonic()
        try:
            with pytest.raises(subprocess.TimeoutExpired):
                pptx_from_html_huashu.run_sidecar_process(
                    ["node", str(stub)], input=b"", timeout=STUB_TIMEOUT_SECONDS
                )
            elapsed = time.monotonic() - started
            pids = json.loads(pids_path.read_text(encoding="utf-8"))
            assert not _alive(pids["sidecar"]), "node was left a zombie: never reaped"
            assert _open_descriptors() == descriptors, "the sidecar's pipes were left open"
            assert elapsed < STUB_TIMEOUT_SECONDS + RETURN_SLACK_SECONDS, elapsed
        finally:
            if pids_path.exists():
                holder = json.loads(pids_path.read_text(encoding="utf-8"))["holder"]
                try:
                    os.killpg(holder, signal.SIGKILL)
                except ProcessLookupError:
                    pass


# Another run's Playwright browser: launched, a ready file written, then held open.
FOREIGN_BROWSER = """
import fs from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(%(sidecar)s);
const { chromium } = require('playwright');
await chromium.launch();
fs.writeFileSync(%(ready)s, 'ready');
await new Promise(() => {});
"""


# How long a SIGKILLed process takes to stop running, with slack.
KILL_SETTLE_SECONDS = 2


def _running_after(pid: int, seconds: float) -> bool:
    """Whether ``pid`` still runs (a zombie does not) once ``seconds`` have passed."""
    time.sleep(seconds)
    state = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True
    ).stdout.strip()
    return bool(state) and not state.startswith("Z")


def _browser_of(node_pid: int) -> int | None:
    """The Playwright browser node ``node_pid`` launched (its child with the pipe flag), or None."""
    listing = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,command="], capture_output=True, text=True, check=True
    ).stdout
    for line in listing.splitlines():
        fields = line.split(None, 2)
        if len(fields) == 3 and int(fields[1]) == node_pid:
            if PLAYWRIGHT_BROWSER_FLAG in fields[2]:
                return int(fields[0])
    return None


@pytest.mark.slow
@requires_huashu_sidecar
class TestTheWatchIsItsOwnRuns:
    def test_a_browser_of_another_run_is_neither_counted_nor_killed(
        self, tmp_path: Path, browser_watch: _BrowserWatch
    ) -> None:
        """A Playwright browser another run starts while the watch runs outlives the watch.

        Another agent's or a developer's test run can launch Playwright browsers
        on the same machine at any time. The watch sees, and so kills, only the
        browsers of its own run; this one is launched with a TMPDIR of its own.
        """
        other = tempfile.mkdtemp(prefix="tellr-other-", dir="/tmp")
        ready = tmp_path / "foreign_browser.ready"
        script = tmp_path / "foreign_browser.mjs"
        script.write_text(
            FOREIGN_BROWSER
            % {
                "sidecar": json.dumps(str(pptx_from_html_huashu.SIDECAR_DIR) + "/"),
                "ready": json.dumps(str(ready)),
            },
            encoding="utf-8",
        )
        env = {**pptx_from_html_huashu.sidecar_subprocess_env(), "TMPDIR": other}
        node = subprocess.Popen(
            ["node", str(script)],
            cwd=pptx_from_html_huashu.SIDECAR_DIR,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        browser = None
        try:
            deadline = time.monotonic() + HUNG_SLIDE_TIMEOUT_SECONDS
            while not ready.exists():
                assert node.poll() is None and time.monotonic() < deadline, (
                    "fixture drift: the other run's browser never started"
                )
                time.sleep(0.1)
            browser = _browser_of(node.pid)
            assert browser is not None, "fixture drift: the other run launched no browser"
            time.sleep(1)  # several of the watch's looks at the process table

            browser_watch.end()

            counted = browser in browser_watch.seen
            killed = not _running_after(browser, KILL_SETTLE_SECONDS)
            assert not counted and not killed, (
                f"another run's browser {browser}: counted by the watch {counted}, killed {killed}"
            )
        finally:
            for group in (browser, node.pid):
                if group is not None:
                    try:
                        os.killpg(group, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        pass  # gone already, or a zombie group macOS will not signal
            node.wait()
            shutil.rmtree(other, ignore_errors=True)


@pytest.mark.slow
@requires_huashu_sidecar
class TestTheRealSidecarLeavesNoBrowser:
    def test_a_hung_slide_leaves_no_browser_behind(
        self, monkeypatch: pytest.MonkeyPatch, browser_watch: _BrowserWatch
    ) -> None:
        """A slide whose script never yields: the export times out, its Chromium with it."""
        monkeypatch.setenv("HUASHU_PIPELINE_ENABLED", "1")
        monkeypatch.setattr(
            pptx_from_html_huashu, "SIDECAR_TIMEOUT_SECONDS", HUNG_SLIDE_TIMEOUT_SECONDS
        )

        with pytest.raises(HuashuExportError, match="timed out"):
            pptx_from_html_huashu.build_pptx_huashu("hung deck", [{"html": HUNG_SLIDE}])
        browser_watch.stop()

        assert browser_watch.seen, "fixture drift: the export launched no browser"
        survivors = browser_watch.survivors()
        assert survivors == [], (
            f"the timed-out export left its browser running: {survivors} "
            f"(browser groups {sorted(set(browser_watch.seen.values()))})"
        )


@pytest.mark.slow
@requires_huashu_sidecar
class TestTheRealSidecarWithItsLoopBlocked:
    def test_its_browser_is_swept(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        browser_watch: _BrowserWatch,
    ) -> None:
        """emit_deck.mjs blocks once its browser has loaded the slide: the browser goes too."""
        preload = tmp_path / "blocking_launch.mjs"
        preload.write_text(
            BLOCKING_LAUNCH_PRELOAD
            % {"sidecar": json.dumps(str(pptx_from_html_huashu.SIDECAR_DIR) + "/")},
            encoding="utf-8",
        )
        sidecar_env = pptx_from_html_huashu.sidecar_subprocess_env

        def env_with_preload() -> dict[str, str]:
            env = sidecar_env()
            env["NODE_OPTIONS"] = f"--import={preload.as_uri()}"
            return env

        monkeypatch.setenv("HUASHU_PIPELINE_ENABLED", "1")
        monkeypatch.setattr(pptx_from_html_huashu, "sidecar_subprocess_env", env_with_preload)
        monkeypatch.setattr(
            pptx_from_html_huashu, "SIDECAR_TIMEOUT_SECONDS", HUNG_SLIDE_TIMEOUT_SECONDS
        )

        with pytest.raises(HuashuExportError, match="timed out"):
            pptx_from_html_huashu.build_pptx_huashu(
                "blocked deck", [{"html": "<div class='slide'><p>x</p></div>"}]
            )
        browser_watch.stop()

        assert browser_watch.seen, "fixture drift: the export launched no browser"
        survivors = browser_watch.survivors()
        assert survivors == [], f"the blocked sidecar left its browser running: {survivors}"


@requires_node
class TestTheAdminRoutesLeaveNoChild:
    """The ``install-chromium`` and ``probe-launch`` routes, each on a run that never ends."""

    def test_install_chromium_leaves_no_child_behind(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pids_path = tmp_path / "pids.json"
        _write_stub(tmp_path / "node_modules" / "playwright" / "cli.js", pids_path)
        (tmp_path / "node_modules" / "playwright" / "package.json").write_text(
            '{"type": "module"}', encoding="utf-8"
        )
        monkeypatch.setattr(pptx_from_html_huashu, "SIDECAR_DIR", tmp_path)
        monkeypatch.setattr(
            export_routes, "HUASHU_INSTALL_CHROMIUM_TIMEOUT_SECONDS", STUB_TIMEOUT_SECONDS
        )

        started = time.monotonic()
        response = asyncio.run(export_routes.export_pptx_huashu_install_chromium())
        elapsed = time.monotonic() - started

        pids = json.loads(pids_path.read_text(encoding="utf-8"))
        everything = [pids["sidecar"], pids["browser"], pids["helper"]]
        try:
            assert response == {"ok": False, "error": "timeout"}, response
            assert elapsed < STUB_TIMEOUT_SECONDS + RETURN_SLACK_SECONDS, elapsed
            alive = _still_alive(everything)
            assert alive == [], f"still running after the timeout: {alive} of {pids}"
        finally:
            _kill(everything)

    def test_probe_launch_leaves_no_child_behind(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pids_path = tmp_path / "pids.json"
        _write_stub(tmp_path / "probe_launch.mjs", pids_path)
        monkeypatch.setattr(pptx_from_html_huashu, "SIDECAR_DIR", tmp_path)
        monkeypatch.setattr(
            export_routes, "HUASHU_PROBE_LAUNCH_TIMEOUT_SECONDS", STUB_TIMEOUT_SECONDS
        )

        started = time.monotonic()
        response = asyncio.run(export_routes.export_pptx_huashu_probe_launch())
        elapsed = time.monotonic() - started

        pids = json.loads(pids_path.read_text(encoding="utf-8"))
        everything = [pids["sidecar"], pids["browser"], pids["helper"]]
        try:
            assert response == {"ok": False, "error": "timeout"}, response
            assert elapsed < STUB_TIMEOUT_SECONDS + RETURN_SLACK_SECONDS, elapsed
            alive = _still_alive(everything)
            assert alive == [], f"still running after the timeout: {alive} of {pids}"
        finally:
            _kill(everything)


@pytest.mark.slow
@requires_huashu_sidecar
class TestTheScriptsEndOnSigterm:
    """Each real script, its browser running, answers SIGTERM by exiting 143 within the grace.

    That is what lets Playwright's exit handler kill the browser it launched:
    without the handler, SIGTERM leaves node running Playwright's own graceful
    close, past the grace period, and the SIGKILL that follows skips the exit
    handler.
    """

    def _assert_ends_on_sigterm(
        self, command: list[str], payload: bytes, env: dict[str, str], watch: _BrowserWatch
    ) -> None:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=pptx_from_html_huashu.SIDECAR_DIR,
            env=env,
            start_new_session=True,
        )
        try:
            process.stdin.write(payload)
            process.stdin.close()
            deadline = time.monotonic() + HUNG_SLIDE_TIMEOUT_SECONDS
            while not watch.seen and time.monotonic() < deadline:
                time.sleep(0.2)
            assert watch.seen, "fixture drift: the script launched no browser"
            time.sleep(1)
            process.send_signal(signal.SIGTERM)
            try:
                code = process.wait(timeout=pptx_from_html_huashu.SIDECAR_TERM_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                code = None
            watch.stop()
            grace = pptx_from_html_huashu.SIDECAR_TERM_GRACE_SECONDS
            assert code == 143, (
                f"the script did not exit 143 within {grace}s of SIGTERM (exit code {code})"
            )
            assert watch.survivors() == [], "the browser outlived its script"
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()

    def test_emit_deck(self, tmp_path: Path, browser_watch: _BrowserWatch) -> None:
        payload = json.dumps(
            {"title": "hung deck", "slides": [{"html": HUNG_SLIDE}], "bypassValidation": True}
        ).encode("utf-8")
        self._assert_ends_on_sigterm(
            ["node", str(pptx_from_html_huashu.SIDECAR_SCRIPT), str(tmp_path / "out.pptx")],
            payload,
            pptx_from_html_huashu.sidecar_subprocess_env(),
            browser_watch,
        )

    def test_probe_launch(self, tmp_path: Path, browser_watch: _BrowserWatch) -> None:
        """The real probe, its launched browser made to hang (HANGING_LAUNCH_PRELOAD)."""
        preload = tmp_path / "hanging_launch.mjs"
        preload.write_text(
            HANGING_LAUNCH_PRELOAD
            % {"sidecar": json.dumps(str(pptx_from_html_huashu.SIDECAR_DIR) + "/")},
            encoding="utf-8",
        )
        env = pptx_from_html_huashu.sidecar_subprocess_env()
        env["NODE_OPTIONS"] = f"--import={preload.as_uri()}"
        self._assert_ends_on_sigterm(
            ["node", str(pptx_from_html_huashu.SIDECAR_DIR / "probe_launch.mjs")],
            b"",
            env,
            browser_watch,
        )


class TestTheUnavailableMessageSaysWhatItNeeds:
    """The export says where it runs: Apps with HUASHU_PIPELINE_ENABLED=1, or local dev."""

    def test_the_wrapper_names_the_gate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(pptx_from_html_huashu, "is_available", lambda: False)
        with pytest.raises(HuashuExportError) as raised:
            pptx_from_html_huashu.build_pptx_huashu("deck", [{"html": "<p>x</p>"}])
        message = str(raised.value)
        assert "local dev only" not in message, message
        assert "HUASHU_PIPELINE_ENABLED=1" in message and "ENVIRONMENT=development" in message

    def test_the_route_names_the_gate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from fastapi import HTTPException

        monkeypatch.setattr(pptx_from_html_huashu, "is_available", lambda: False)
        monkeypatch.setattr(export_routes, "_check_deck_permission_for_session", lambda *_: None)
        with pytest.raises(HTTPException) as raised:
            export_routes.export_pptx_huashu_from_html(
                export_routes.ExportPPTXEditableRequest(session_id="session")
            )
        assert raised.value.status_code == 503
        detail = str(raised.value.detail)
        assert "local dev only" not in detail, detail
        assert "HUASHU_PIPELINE_ENABLED=1" in detail and "ENVIRONMENT=development" in detail


# The export's sidecar, its run recorded: it appends a line when it starts and
# when it ends, sleeps between, and writes the .pptx and the result line.
STUB_RECORDED_RUN = """
import fs from 'node:fs';
const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const record = (event) => fs.appendFileSync(
  %(log)s, JSON.stringify({ pid: process.pid, event, at: Date.now() / 1000 }) + '\\n'
);
record('start');
await new Promise((resolve) => setTimeout(resolve, %(ms)d));
fs.writeFileSync(process.argv[2], 'PK');
record('end');
console.error('__HUASHU_RESULT__ ' + JSON.stringify({ totalSlides: 1, succeeded: 1, failed: [] }));
"""
# Each recorded run lasts this long; the sidecar timeout is shorter than two of them.
RECORDED_RUN_SECONDS = 2
CAPPED_TIMEOUT_SECONDS = 3
# An export refused at once returns within this: well under one recorded run.
REFUSED_WITHIN_SECONDS = 1
# The bounded-wait case: the wait for a slot is bounded at WAIT_BOUND_SECONDS, and the run
# holding the slot lasts longer than the bound and a refusal, so it still runs when the wait ends.
WAIT_BOUND_SECONDS = 1
LONG_RUN_SECONDS = 4
# The longest a few exports at once may take to return, whatever the bounds do.
EXPORTS_RETURN_WITHIN_SECONDS = 4 * LONG_RUN_SECONDS + RETURN_SLACK_SECONDS


def _recorded_sidecar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, run_seconds: float) -> Path:
    """The export's sidecar made a recorded run of ``run_seconds``; returns the run log."""
    log = tmp_path / "runs.jsonl"
    stub = tmp_path / "stub_recorded_run.mjs"
    stub.write_text(
        STUB_RECORDED_RUN % {"log": json.dumps(str(log)), "ms": int(run_seconds * 1000)},
        encoding="utf-8",
    )
    monkeypatch.setattr(pptx_from_html_huashu, "SIDECAR_SCRIPT", stub)
    monkeypatch.setattr(pptx_from_html_huashu, "is_available", lambda: True)
    return log


def _bound(monkeypatch: pytest.MonkeyPatch, *, cap: int, queue: int, wait: float) -> None:
    """The worker's sidecar bounds: ``cap`` run at once, ``queue`` more wait, each ``wait`` s."""
    monkeypatch.setattr(pptx_from_html_huashu, "_sidecar_cap", cap)
    monkeypatch.setattr(pptx_from_html_huashu, "_sidecar_queue", queue)
    monkeypatch.setattr(pptx_from_html_huashu, "_sidecar_slots", threading.BoundedSemaphore(cap))
    monkeypatch.setattr(
        pptx_from_html_huashu, "_sidecar_admissions", threading.BoundedSemaphore(cap + queue)
    )
    monkeypatch.setattr(pptx_from_html_huashu, "SIDECAR_WAIT_SECONDS", wait)


class _Export(NamedTuple):
    # What the export returned, (pptx bytes, failures), or the exception it raised.
    outcome: object
    # How long it took to return.
    seconds: float
    # When it returned, on the clock the run log records (time.time, as node's Date.now).
    returned_at: float


def _exports_at_once(count: int) -> list[_Export]:
    """``count`` exports started together, each in a thread, in the order they returned."""
    exports: list[_Export] = []

    def export() -> None:
        started = time.monotonic()
        try:
            outcome: object = pptx_from_html_huashu.build_pptx_huashu(
                "deck", [{"html": "<p>x</p>"}]
            )
        except Exception as error:  # noqa: BLE001 (recorded, then asserted on)
            outcome = error
        exports.append(_Export(outcome, time.monotonic() - started, time.time()))

    threads = [threading.Thread(target=export) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=EXPORTS_RETURN_WITHIN_SECONDS)
    assert not any(thread.is_alive() for thread in threads), "an export never returned"
    return exports


def _runs(log: Path) -> list[tuple[float, float]]:
    """The sidecar runs the log recorded, each ``(start, end)``, in the order they started."""
    events: dict[int, dict[str, float]] = {}
    for line in log.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        events.setdefault(entry["pid"], {})[entry["event"]] = entry["at"]
    return sorted((run["start"], run["end"]) for run in events.values())


def _free(semaphore: threading.BoundedSemaphore) -> int:
    """How many of the semaphore's places are free: each is taken, counted, then given back."""
    taken = 0
    while semaphore.acquire(blocking=False):
        taken += 1
    for _ in range(taken):
        semaphore.release()
    return taken


@requires_node
class TestTheSidecarsAreCappedPerWorker:
    """Each node and Chromium tree takes about 790 MB: a worker runs at most its cap at once.

    The cap is ``TELLR_SIDECAR_CONCURRENCY`` (default 1 per worker process).
    An export past it waits for a slot, says so once on its log, and starts its
    timeout only once it has the slot, logging how long it waited.
    """

    def _two_exports(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cap: int
    ) -> list[tuple[float, float]]:
        log = _recorded_sidecar(tmp_path, monkeypatch, RECORDED_RUN_SECONDS)
        monkeypatch.setattr(
            pptx_from_html_huashu, "SIDECAR_TIMEOUT_SECONDS", CAPPED_TIMEOUT_SECONDS
        )
        _bound(monkeypatch, cap=cap, queue=1, wait=EXPORTS_RETURN_WITHIN_SECONDS)
        exports = _exports_at_once(2)
        assert [export.outcome for export in exports] == [(b"PK", []), (b"PK", [])], exports
        return _runs(log)

    def test_with_a_cap_of_one_the_sidecars_run_one_after_the_other(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The second waits for the first, and its wait does not count against its timeout."""
        with caplog.at_level("INFO", logger=pptx_from_html_huashu.__name__):
            (first, second) = self._two_exports(tmp_path, monkeypatch, cap=1)
        assert second[0] >= first[1], f"the sidecars overlapped: {first} and {second}"
        messages = [record.message for record in caplog.records]
        waits = [message for message in messages if "waits for a sidecar slot" in message]
        assert len(waits) == 1 and waits[0].startswith("[huashu]"), messages
        took = [message for message in messages if "took a sidecar slot after" in message]
        assert len(took) == 1 and took[0].startswith("[huashu]"), messages
        waited = float(re.search(r"after (\d+(?:\.\d+)?)s", took[0]).group(1))
        # It waited out the first export's run: its node start, its recorded run, its exit.
        assert RECORDED_RUN_SECONDS <= waited < RECORDED_RUN_SECONDS + REFUSED_WITHIN_SECONDS, (
            took[0]
        )

    def test_with_a_cap_of_two_they_overlap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level("INFO", logger=pptx_from_html_huashu.__name__):
            (first, second) = self._two_exports(tmp_path, monkeypatch, cap=2)
        assert second[0] < first[1], f"the sidecars ran one after the other: {first}, {second}"
        assert not [record for record in caplog.records if "sidecar slot" in record.message]

    @pytest.mark.parametrize(
        ("value", "cap"), [(None, 1), ("1", 1), ("3", 3), ("0", 1), ("-2", 1), ("two", 1)]
    )
    def test_the_cap_is_read_from_the_environment(self, value: str | None, cap: int) -> None:
        environ = {} if value is None else {"TELLR_SIDECAR_CONCURRENCY": value}
        assert pptx_from_html_huashu.sidecar_concurrency(environ) == cap


def _raising(error: BaseException):
    """A sidecar run that raises ``error``."""

    def run(*_: object, **__: object) -> None:
        raise error

    return run


def _writing_no_deck(*_: object, **__: object) -> subprocess.CompletedProcess:
    """A sidecar run that exits 1 having written no deck and no result line."""
    return subprocess.CompletedProcess(["node"], 1, b"", b"boom\n")


# The run of an export that must be refused before it starts one.
_RUN_NOT_EXPECTED = _raising(AssertionError("the refused export ran its sidecar"))


class TestTheWaitForASidecarIsBounded:
    """An export waiting for a sidecar slot holds a threadpool thread, so its wait is bounded.

    A worker has 40 threads (Starlette's default), shared with every sync route
    and with the identity lookup of every authenticated request. So at most
    ``TELLR_SIDECAR_QUEUE`` exports (default 15) wait past the cap, each for at
    most ``TELLR_SIDECAR_WAIT_SECONDS`` (default 60, which with the 180 s sidecar
    timeout and a Drive upload stays under the Apps proxy's 300 s per request, by
    some 40 s). An export past either
    bound raises ``HuashuBusyError``, which the export routes answer 429. It is not
    a ``HuashuExportError``: the routes answer that 500 or 503, and the frontend
    answers a 503 by falling back to the records pipeline.
    """

    @requires_node
    def test_an_export_past_the_queue_is_refused_at_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cap 1 and queue 1: of three exports at once, one runs, one waits, one is refused."""
        log = _recorded_sidecar(tmp_path, monkeypatch, RECORDED_RUN_SECONDS)
        _bound(monkeypatch, cap=1, queue=1, wait=EXPORTS_RETURN_WITHIN_SECONDS)

        exports = _exports_at_once(3)

        built = [export for export in exports if not isinstance(export.outcome, BaseException)]
        refused = [export for export in exports if isinstance(export.outcome, BaseException)]
        assert [export.outcome for export in built] == [(b"PK", []), (b"PK", [])], exports
        assert len(refused) == 1, exports
        assert type(refused[0].outcome) is pptx_from_html_huashu.HuashuBusyError, refused
        assert not isinstance(refused[0].outcome, HuashuExportError)
        assert refused[0].seconds < REFUSED_WITHIN_SECONDS, (
            f"the export past the queue was refused after {refused[0].seconds:.1f}s"
        )
        assert len(_runs(log)) == 2, "the refused export ran a sidecar"

    @requires_node
    def test_a_wait_past_its_bound_is_refused_while_the_slot_is_still_taken(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cap 1 and a 1 s bound: the second export is refused after 1 s, the first still runs."""
        log = _recorded_sidecar(tmp_path, monkeypatch, LONG_RUN_SECONDS)
        _bound(monkeypatch, cap=1, queue=15, wait=WAIT_BOUND_SECONDS)

        exports = _exports_at_once(2)

        assert [type(export.outcome) for export in exports] == [
            pptx_from_html_huashu.HuashuBusyError,
            tuple,
        ], exports
        refused, built = exports
        assert built.outcome == (b"PK", [])
        assert not isinstance(refused.outcome, HuashuExportError)
        assert (
            WAIT_BOUND_SECONDS - 0.1
            <= refused.seconds
            < WAIT_BOUND_SECONDS + REFUSED_WITHIN_SECONDS
        ), f"refused after {refused.seconds:.1f}s, the bound {WAIT_BOUND_SECONDS}s"
        ((_, first_ended),) = _runs(log)
        assert refused.returned_at < first_ended, "refused only once the slot was free again"

    @requires_node
    def test_an_export_keeps_its_place_while_its_sidecar_runs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """While the first export's sidecar runs, of two exports more one waits, one is refused.

        Cap 1 and queue 1. The two arrive only after the first export's sidecar
        has recorded its start, so the first holds its slot and, all the while
        it runs, its place: a place given back once the slot is taken would let
        both in.
        """
        log = _recorded_sidecar(tmp_path, monkeypatch, RECORDED_RUN_SECONDS)
        _bound(monkeypatch, cap=1, queue=1, wait=EXPORTS_RETURN_WITHIN_SECONDS)
        first: list[_Export] = []
        running = threading.Thread(target=lambda: first.extend(_exports_at_once(1)))
        running.start()
        try:
            deadline = time.monotonic() + RECORDED_RUN_SECONDS
            while not (log.exists() and log.read_text(encoding="utf-8").strip()):
                assert time.monotonic() < deadline, "the first export's sidecar never started"
                time.sleep(0.02)

            later = _exports_at_once(2)
        finally:
            running.join(timeout=EXPORTS_RETURN_WITHIN_SECONDS)

        assert not running.is_alive() and [export.outcome for export in first] == [(b"PK", [])]
        refused = [export for export in later if isinstance(export.outcome, BaseException)]
        built = [export for export in later if not isinstance(export.outcome, BaseException)]
        assert len(refused) == 1 and len(built) == 1, later
        assert type(refused[0].outcome) is pptx_from_html_huashu.HuashuBusyError, refused
        assert refused[0].seconds < REFUSED_WITHIN_SECONDS, (
            f"the export past the queue was refused after {refused[0].seconds:.1f}s"
        )
        assert built[0].outcome == (b"PK", [])
        assert len(_runs(log)) == 2, "the refused export ran a sidecar"

    @pytest.mark.parametrize(
        ("run", "raised"),
        [
            (_raising(OSError("node not found")), OSError),
            (
                _raising(subprocess.TimeoutExpired(["node"], 1, output=b"", stderr=b"")),
                HuashuExportError,
            ),
            (_raising(KeyboardInterrupt()), KeyboardInterrupt),
            (_raising(RuntimeError("anything else")), RuntimeError),
            (_writing_no_deck, HuashuExportError),
        ],
        ids=["no node", "timed out", "interrupted", "anything else", "no deck written"],
    )
    def test_a_failed_run_gives_its_slot_and_its_place_back(
        self, run, raised: type[BaseException], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _bound(monkeypatch, cap=1, queue=1, wait=WAIT_BOUND_SECONDS)
        monkeypatch.setattr(pptx_from_html_huashu, "is_available", lambda: True)
        monkeypatch.setattr(pptx_from_html_huashu, "run_sidecar_process", run)

        with pytest.raises(raised):
            pptx_from_html_huashu.build_pptx_huashu("deck", [{"html": "<p>x</p>"}])

        assert _free(pptx_from_html_huashu._sidecar_slots) == 1, "the slot was kept"
        assert _free(pptx_from_html_huashu._sidecar_admissions) == 2, "the place was kept"

    def test_a_refused_wait_gives_its_place_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _bound(monkeypatch, cap=1, queue=1, wait=WAIT_BOUND_SECONDS)
        monkeypatch.setattr(pptx_from_html_huashu, "is_available", lambda: True)
        monkeypatch.setattr(pptx_from_html_huashu, "run_sidecar_process", _RUN_NOT_EXPECTED)
        slots = pptx_from_html_huashu._sidecar_slots
        assert slots.acquire(blocking=False)  # another export's run
        try:
            # In a thread, bounded: a wait that never ends fails here, not hangs.
            (export,) = _exports_at_once(1)
        finally:
            slots.release()

        assert type(export.outcome) is pptx_from_html_huashu.HuashuBusyError, export
        assert _free(slots) == 1
        assert _free(pptx_from_html_huashu._sidecar_admissions) == 2, "the place was kept"

    def test_an_export_refused_at_once_gives_back_nothing_it_did_not_take(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every place taken: the refusal releases none (one too many raises ValueError here)."""
        _bound(monkeypatch, cap=1, queue=1, wait=WAIT_BOUND_SECONDS)
        monkeypatch.setattr(pptx_from_html_huashu, "is_available", lambda: True)
        monkeypatch.setattr(pptx_from_html_huashu, "run_sidecar_process", _RUN_NOT_EXPECTED)
        admissions = pptx_from_html_huashu._sidecar_admissions
        assert admissions.acquire(blocking=False) and admissions.acquire(blocking=False)
        try:
            with pytest.raises(pptx_from_html_huashu.HuashuBusyError):
                pptx_from_html_huashu.build_pptx_huashu("deck", [{"html": "<p>x</p>"}])
            assert _free(admissions) == 0, "the refused export gave back a place it never took"
        finally:
            admissions.release()
            admissions.release()

        assert _free(admissions) == 2
        assert _free(pptx_from_html_huashu._sidecar_slots) == 1

    @pytest.mark.parametrize(
        ("value", "queue"),
        [(None, 15), ("15", 15), ("4", 4), ("0", 0), ("-1", 15), ("many", 15), ("2.5", 15)],
    )
    def test_the_queue_is_read_from_the_environment(self, value: str | None, queue: int) -> None:
        environ = {} if value is None else {"TELLR_SIDECAR_QUEUE": value}
        assert pptx_from_html_huashu.sidecar_queue(environ) == queue

    @pytest.mark.parametrize(
        ("value", "seconds"),
        [
            (None, 60),
            ("100", 100),
            ("1", 1),
            ("2.5", 2.5),
            ("0", 60),
            ("-5", 60),
            ("inf", 60),
            ("nan", 60),
            ("soon", 60),
            # A lock's wait cannot be told this long (threading.TIMEOUT_MAX): the
            # wait would raise OverflowError, not HuashuBusyError.
            ("1e10", 60),
            (repr(threading.TIMEOUT_MAX), 60),
        ],
    )
    def test_the_wait_is_read_from_the_environment(
        self, value: str | None, seconds: float
    ) -> None:
        environ = {} if value is None else {"TELLR_SIDECAR_WAIT_SECONDS": value}
        assert pptx_from_html_huashu.sidecar_wait_seconds(environ) == seconds

    def test_a_wait_a_lock_cannot_be_told_is_refused_and_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A wait at threading.TIMEOUT_MAX or more falls back to the default, and says so."""
        with caplog.at_level("WARNING", logger=pptx_from_html_huashu.__name__):
            seconds = pptx_from_html_huashu.sidecar_wait_seconds(
                {"TELLR_SIDECAR_WAIT_SECONDS": "1e10"}
            )
        assert seconds == pptx_from_html_huashu.DEFAULT_SIDECAR_WAIT_SECONDS
        messages = [record.message for record in caplog.records]
        assert len(messages) == 1 and "TELLR_SIDECAR_WAIT_SECONDS='1e10'" in messages[0], messages


class TestTheBoundsAreCheckedAgainstTheApp:
    """Bounds that defeat what they are for are warned about once, when the module loads.

    * a wait whose worst case, with the sidecar timeout and a Drive upload,
      reaches the 300 s the Databricks Apps proxy allows a request (measured):
      the proxy would answer the Google Slides export 502 before the app does;
    * as many export places as the worker's 40 threads (Starlette's
      threadpool): waiting exports alone could hold every one.
    """

    def test_the_default_bounds_are_within_both(self) -> None:
        assert (
            pptx_from_html_huashu.sidecar_bounds_warnings(
                pptx_from_html_huashu.sidecar_concurrency({}),
                pptx_from_html_huashu.sidecar_queue({}),
                pptx_from_html_huashu.sidecar_wait_seconds({}),
            )
            == []
        )

    @pytest.mark.parametrize(("wait", "warned"), [(99.5, False), (100, True), (150, True)])
    def test_a_wait_that_reaches_the_proxy_limit_is_warned_about(
        self, wait: float, warned: bool
    ) -> None:
        """100 s of waiting, the 180 s sidecar timeout and 20 s of Drive upload make 300 s."""
        warnings = pptx_from_html_huashu.sidecar_bounds_warnings(1, 15, wait)
        assert bool(warnings) is warned, warnings
        if warned:
            (warning,) = warnings
            assert "TELLR_SIDECAR_WAIT_SECONDS" in warning and "300 s" in warning, warning

    @pytest.mark.parametrize(
        ("cap", "queue", "warned"), [(1, 38, False), (1, 39, True), (4, 36, True), (2, 50, True)]
    )
    def test_as_many_places_as_threads_is_warned_about(
        self, cap: int, queue: int, warned: bool
    ) -> None:
        warnings = pptx_from_html_huashu.sidecar_bounds_warnings(cap, queue, 60)
        assert bool(warnings) is warned, warnings
        if warned:
            (warning,) = warnings
            assert "TELLR_SIDECAR_QUEUE" in warning and "40 threads" in warning, warning

    def test_the_module_warns_once_when_it_loads(self) -> None:
        """Both bounds out of reach in a fresh interpreter: each warning once, the bounds kept."""
        script = (
            "import logging, sys\n"
            "logging.basicConfig(level=logging.WARNING, stream=sys.stderr)\n"
            "from src.services import pptx_from_html_huashu as m\n"
            "print(m.SIDECAR_WAIT_SECONDS, m._sidecar_cap, m._sidecar_queue)\n"
        )
        env = {**os.environ, "TELLR_SIDECAR_WAIT_SECONDS": "150", "TELLR_SIDECAR_QUEUE": "45"}
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=MODULE_LOAD_TIMEOUT_SECONDS,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.split() == ["150.0", "1", "45"], result.stdout
        lines = result.stderr.splitlines()
        budget = [line for line in lines if "SIDECAR_WAIT_SECONDS" in line and "300 s" in line]
        threads = [line for line in lines if "SIDECAR_QUEUE" in line and "40 threads" in line]
        assert len(budget) == 1 and len(threads) == 1, result.stderr

    def test_the_app_warns_when_it_starts(self) -> None:
        """A wait past the proxy's limit shows when a worker starts, before any export runs.

        A fresh interpreter imports the app, says so, then runs its lifespan's
        startup: the budget warning comes between the two, once, and so do the
        lines ``log_sidecar_bounds`` logs, the bounds the worker runs with and the
        container's memory limit. The warning alone would show only that the
        startup loaded the wrapper.
        """
        script = (
            "import asyncio, logging, sys\n"
            "logging.basicConfig(level=logging.INFO, stream=sys.stderr, format='%(message)s')\n"
            "from src.api.main import app, lifespan\n"
            "logging.getLogger('probe').info('PROBE app imported')\n"
            "async def start():\n"
            "    async with lifespan(app):\n"
            "        logging.getLogger('probe').info('PROBE app started')\n"
            "asyncio.run(start())\n"
        )
        env = {**os.environ, "TELLR_SIDECAR_WAIT_SECONDS": "200", "ENVIRONMENT": "test"}
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=MODULE_LOAD_TIMEOUT_SECONDS,
        )
        assert result.returncode == 0, result.stderr
        lines = result.stderr.splitlines()
        imported = lines.index("PROBE app imported")
        started = lines.index("PROBE app started")
        budget = [
            index
            for index, line in enumerate(lines)
            if "SIDECAR_WAIT_SECONDS=200" in line and "300 s" in line
        ]
        assert len(budget) == 1 and imported < budget[0] < started, (
            f"the budget warning is not one line of the app's startup: {lines}"
        )
        cap = pptx_from_html_huashu.sidecar_concurrency(env)
        queue = pptx_from_html_huashu.sidecar_queue(env)
        bounds_line = (
            f"[huashu] export sidecars per worker: {cap} at once, {queue} more waiting, "
            "each up to 200s"
        )
        bounds = [index for index, line in enumerate(lines) if line == bounds_line]
        assert len(bounds) == 1 and imported < bounds[0] < started, (
            f"the startup did not log its bounds ({bounds_line!r}) once: {lines}"
        )
        limits = [index for index, line in enumerate(lines) if line.startswith(LIMIT_PREFIX)]
        assert len(limits) == 1 and imported < limits[0] < started, (
            f"the startup did not log the container's memory limit once: {lines}"
        )
        if sys.platform == "darwin":
            assert lines[limits[0]] == LIMIT_PREFIX + "none", lines[limits[0]]


# ---------------------------------------------------------------------------
# The export summary: one line per export, however it ends
# ---------------------------------------------------------------------------

# What the owner greps the app's logs for: each export's line starts with this, then its JSON.
SUMMARY_PREFIX = "[huashu] export summary "
# The line's keys, in this order (docs/technical/export-features.md, The export summary line).
SUMMARY_KEYS = [
    "target",
    "slides",
    "slidesExported",
    "failures",
    "outcome",
    "waitSeconds",
    "runSeconds",
    "secondsPerSlide",
    "peakRssMb",
    "containerPeakMb",
    "containerWorkingSetMb",
    "pptxBytes",
    "sidecarConcurrency",
    "queueBound",
]
# Whole numbers, from 0.
SUMMARY_COUNTS = (
    "slides",
    "slidesExported",
    "failures",
    "pptxBytes",
    "sidecarConcurrency",
    "queueBound",
)
# Read once the sidecar has run: null for an export refused before it ran.
SUMMARY_RUN_READINGS = (
    "runSeconds",
    "secondsPerSlide",
    "peakRssMb",
    "containerPeakMb",
    "containerWorkingSetMb",
)
# The container's own readings, from its cgroup.
CONTAINER_KEYS = ("containerPeakMb", "containerWorkingSetMb")
SUMMARY_OUTCOMES = ("ok", "partial", "failed", "timeout", "busy")
SUMMARY_TARGETS = ("pptx", "gslides")

# The summarised stub's run: long enough for the memory sampler (every 0.25 s) to
# read the sidecar a few times.
SUMMARISED_RUN_SECONDS = 1
# A word no slide, title or note holds by chance, planted to show the line carries none.
PLANTED_WORD = "Quellbrunnenzauber"
# A slide's content the summary must not carry, three slides of it.
THREE_SLIDES = [
    {"html": f"<div class='slide'><p>{PLANTED_WORD} {number}</p></div>", "notes": PLANTED_WORD}
    for number in (1, 2, 3)
]
# How much of its queue wait a summary may leave out: the start of node and the
# reading of the clock are not its first export's run.
QUEUE_WAIT_SLACK_SECONDS = 0.2
# What the stub's detached child (a browser's stand-in) holds resident, in MB (MiB).
DETACHED_CHILD_MB = 128
BYTES_PER_MB = 1024 * 1024

# The sidecar whose run a summary reads: it reads the payload, lives
# SUMMARISED_RUN_SECONDS, reports as failed each slide it is told to (its error
# quoting the slide, as a validation message can), and writes the deck when at
# least one slide passed, as emit_deck.mjs does.
STUB_SUMMARISED_RUN = """
import fs from 'node:fs';
const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const slides = JSON.parse(Buffer.concat(chunks).toString('utf-8')).slides;
const failed = %(failed)s.map(
  (index) => ({ slide_index: index, error: 'rejected: ' + slides[index].html })
);
await new Promise((resolve) => setTimeout(resolve, %(ms)d));
if (failed.length < slides.length) fs.writeFileSync(process.argv[2], 'PK');
const result = { totalSlides: slides.length, succeeded: slides.length - failed.length, failed };
console.error('__HUASHU_RESULT__ ' + JSON.stringify(result));
"""

# A sidecar that fails outright: no deck, no result line.
STUB_FAILING_RUN = """
process.stderr.write('boom\\n');
process.exit(1);
"""

# A sidecar that never finishes: it answers SIGTERM by exiting, as emit_deck.mjs does.
STUB_HUNG_RUN = """
process.on('SIGTERM', () => process.exit(143));
setTimeout(() => process.exit(0), %(lifetime_ms)d);
setInterval(() => {}, 1000);
"""

# A sidecar whose detached child, a browser's stand-in, holds DETACHED_CHILD_MB of
# random bytes resident (random: nothing can compress them away) until the
# sidecar's exit handler kills its group, as Playwright's does.
STUB_DETACHED_MEMORY = """
import { spawn } from 'node:child_process';
import fs from 'node:fs';
const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const hog = "const held = require('node:crypto').randomFillSync(Buffer.allocUnsafe(%(bytes)d));"
  + " process.stdout.write('ready'); setInterval(() => held[0], 1000);";
const browser = spawn(process.execPath, ['-e', hog], {
  detached: true, stdio: ['ignore', 'pipe', 'ignore'],
});
process.on('exit', () => {
  try { process.kill(-browser.pid, 'SIGKILL'); } catch (error) { /* already gone */ }
});
fs.writeFileSync(%(pids)s, JSON.stringify({ sidecar: process.pid, browser: browser.pid }));
await new Promise((resolve) => browser.stdout.once('data', resolve));
await new Promise((resolve) => setTimeout(resolve, %(ms)d));
fs.writeFileSync(process.argv[2], 'PK');
console.error('__HUASHU_RESULT__ ' + JSON.stringify({ totalSlides: 1, succeeded: 1, failed: [] }));
// The child's pipe would hold node's event loop open: exit, through the handler above.
process.exit(0);
"""

# STUB_DETACHED_MEMORY's child, freed before the sidecar ends: it holds its bytes
# for %(ms)d ms, is killed (a browser closed between slides), and the sidecar runs
# on as long again without it, so the last reading of the tree is node alone.
STUB_FREED_MEMORY = STUB_DETACHED_MEMORY.replace(
    "await new Promise((resolve) => setTimeout(resolve, %(ms)d));\n",
    "await new Promise((resolve) => setTimeout(resolve, %(ms)d));\n"
    "const exited = new Promise((resolve) => browser.once('exit', resolve));\n"
    "process.kill(-browser.pid, 'SIGKILL');\n"
    "await exited;\n"
    "await new Promise((resolve) => setTimeout(resolve, %(ms)d));\n",
)

# A sidecar that sets the fake cgroup's memory.current to each of its readings in
# turn (MiB), holding each longer than two samples, and writes each whole (a new
# file renamed over the old), so no sample reads half a number.
STUB_CGROUP_READINGS = """
import fs from 'node:fs';
const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const usage = %(usage)s;
for (const mb of %(readings)s) {
  fs.writeFileSync(usage + '.next', String(mb * 1048576) + '\\n');
  fs.renameSync(usage + '.next', usage);
  await new Promise((resolve) => setTimeout(resolve, %(hold_ms)d));
}
fs.writeFileSync(process.argv[2], 'PK');
console.error('__HUASHU_RESULT__ ' + JSON.stringify({ totalSlides: 1, succeeded: 1, failed: [] }));
"""
# What the fake cgroup's memory.current reads before and during STUB_CGROUP_READINGS,
# and the lifetime peak its memory.peak claims, which the export must not report.
CGROUP_BEFORE_MB = 100
CGROUP_READINGS_MB = (300, 500, 200)
CGROUP_LIFETIME_PEAK_MB = 900
CGROUP_HOLD_MS = 600
# The working-set stub's cgroup, (memory.current, inactive_file) in MiB: before it
# runs, then at each of its steps. The working sets, 100, 100, 400 and 200, peak at
# 400, neither at the usage's peak (500) nor last.
WORKING_SET_BEFORE = (100, 0)
WORKING_SET_STEPS = ((500, 400), (450, 50), (200, 0))
# What memory.stat's other lines hold, in MiB.
STAT_NOISE_MB = 7

# A sidecar that moves the fake cgroup's memory.current and memory.stat through
# WORKING_SET_STEPS, each file written whole, holding each step longer than two
# samples. Two files cannot change at once, so each step writes them in the order
# under which a sample taken between the two writes reads no larger working set,
# and no larger usage, than the steps on either side of it.
STUB_CGROUP_WORKING_SET = """
import fs from 'node:fs';
const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const MB = 1048576;
const write = (path, text) => {
  fs.writeFileSync(path + '.next', text);
  fs.renameSync(path + '.next', path);
};
const usage = (mb) => write(%(usage)s, String(mb * MB) + '\\n');
const noise = %(noise_mb)d * MB;
const stat = (mb) => write(
  %(stat)s,
  `anon ${noise}\\ninactive_anon ${noise}\\ninactive_file ${mb * MB}\\nactive_file ${noise}\\n`,
);
let inactive = %(before)d;
for (const [current, next] of %(steps)s) {
  if (next > inactive) { stat(next); usage(current); } else { usage(current); stat(next); }
  inactive = next;
  await new Promise((resolve) => setTimeout(resolve, %(hold_ms)d));
}
fs.writeFileSync(process.argv[2], 'PK');
console.error('__HUASHU_RESULT__ ' + JSON.stringify({ totalSlides: 1, succeeded: 1, failed: [] }));
"""
# cgroup v1's "no limit": the largest page-aligned 63-bit value.
CGROUP_V1_UNLIMITED = 9223372036854771712
# The startup line for the container's memory limit.
LIMIT_PREFIX = "[huashu] container memory limit "


def _join_samplers() -> None:
    """Wait for every memory sampler's thread to end: the export itself never waits on one."""
    for thread in threading.enumerate():
        if thread.name == "huashu-memory":
            thread.join(timeout=EXPORTS_RETURN_WITHIN_SECONDS)


def _cgroup(root: Path, files: dict[str, str]) -> Path:
    """A fake cgroup filesystem at ``root``: each file of ``files`` with its contents."""
    for name, contents in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(contents, encoding="utf-8")
    return root


def _use_cgroup(
    monkeypatch: pytest.MonkeyPatch,
    base: Path,
    files: dict[str, str],
    membership: str | None = None,
) -> Path:
    """The cgroup the export reads made a fake one, under ``base``; returns its filesystem's root.

    The filesystem, ``base / "cgroup"``, holds ``files``. This process's
    ``/proc/self/cgroup`` reads ``membership``, or, for None, there is no such
    file, as on macOS.
    """
    base.mkdir(parents=True, exist_ok=True)
    root = _cgroup(base / "cgroup", files)
    own = base / "proc-self-cgroup"
    if membership is not None:
        own.write_text(membership, encoding="utf-8")
    monkeypatch.setattr(pptx_from_html_huashu, "CGROUP_ROOT", root)
    monkeypatch.setattr(pptx_from_html_huashu, "PROC_SELF_CGROUP", own)
    return root


def _memory_stat(key: str, megabytes: int) -> str:
    """A cgroup ``memory.stat`` giving ``key`` in MiB, among neighbours whose names start alike."""
    noise = STAT_NOISE_MB * BYTES_PER_MB
    return (
        f"anon {noise}\ninactive_anon {noise}\n{key} {megabytes * BYTES_PER_MB}\n"
        f"active_file {noise}\n"
    )


def _sidecar_script(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, script: str) -> None:
    """The export's sidecar made ``script``, with the pipeline available."""
    stub = tmp_path / "stub_sidecar.mjs"
    stub.write_text(script, encoding="utf-8")
    monkeypatch.setattr(pptx_from_html_huashu, "SIDECAR_SCRIPT", stub)
    monkeypatch.setattr(pptx_from_html_huashu, "is_available", lambda: True)


def _summarised_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed: tuple[int, ...] = ()
) -> None:
    """The export's sidecar made a ``STUB_SUMMARISED_RUN`` failing the slides ``failed``."""
    _sidecar_script(
        tmp_path,
        monkeypatch,
        STUB_SUMMARISED_RUN
        % {"failed": json.dumps(list(failed)), "ms": SUMMARISED_RUN_SECONDS * 1000},
    )


def _summary_lines(stderr: str) -> list[str]:
    """Every export summary line on ``stderr``, in the order the exports logged them."""
    return [line for line in stderr.splitlines() if line.startswith(SUMMARY_PREFIX)]


def _summaries(stderr: str) -> list[dict]:
    """The JSON of every export summary line on ``stderr``, each checked for its form."""
    summaries = [json.loads(line.removeprefix(SUMMARY_PREFIX)) for line in _summary_lines(stderr)]
    for summary in summaries:
        _assert_well_formed(summary)
    return summaries


def _assert_well_formed(summary: dict) -> None:
    """The line's keys, in order, each of its type."""
    assert list(summary) == SUMMARY_KEYS, summary
    assert summary["target"] in SUMMARY_TARGETS, summary
    assert summary["outcome"] in SUMMARY_OUTCOMES, summary
    for key in SUMMARY_COUNTS:
        assert type(summary[key]) is int and summary[key] >= 0, (key, summary)
    assert type(summary["waitSeconds"]) is float and summary["waitSeconds"] >= 0, summary
    for key in SUMMARY_RUN_READINGS:
        reading = summary[key]
        assert reading is None or (type(reading) is float and reading >= 0), (key, summary)


def _the_summary(capsys: pytest.CaptureFixture[str]) -> dict:
    """The one summary line the export logged since the last read."""
    summaries = _summaries(capsys.readouterr().err)
    assert len(summaries) == 1, f"{len(summaries)} summary lines for one export: {summaries}"
    return summaries[0]


def _counts(summary: dict) -> dict:
    """The summary without its timings and its memory reading."""
    readings = ("waitSeconds", *SUMMARY_RUN_READINGS)
    return {key: value for key, value in summary.items() if key not in readings}


def _built(*, slides: int, exported: int, failures: int, outcome: str, deck: int) -> dict:
    """What ``_counts`` reads from an export of ``slides`` at cap 1, queue 1, for PowerPoint."""
    return {
        "target": "pptx",
        "slides": slides,
        "slidesExported": exported,
        "failures": failures,
        "outcome": outcome,
        "pptxBytes": deck,
        "sidecarConcurrency": 1,
        "queueBound": 1,
    }


def _assert_ran(summary: dict, *, at_least: float, slides: int) -> None:
    """The sidecar ran ``at_least`` seconds, its memory read, its time per slide its run's share."""
    assert at_least <= summary["runSeconds"] < at_least + RETURN_SLACK_SECONDS, summary
    assert summary["secondsPerSlide"] == pytest.approx(summary["runSeconds"] / slides, abs=1e-3)
    assert summary["peakRssMb"] is not None and summary["peakRssMb"] > 0, summary


def _assert_never_ran(summary: dict) -> None:
    """No sidecar ran: no run time, no time per slide, no memory reading."""
    assert [summary[key] for key in SUMMARY_RUN_READINGS] == [None] * len(SUMMARY_RUN_READINGS), (
        summary
    )


@requires_node
class TestEveryExportLogsOneSummary:
    """One ``[huashu] export summary {json}`` line per export, once it ends, however it ends.

    The owner reads them from the app's logs on Databricks Apps (the recipe is in
    docs/technical/export-features.md, under "Reading the lines on Apps"), and a
    build that launches one browser per deck will be measured against this one by
    the same line. So the line is one physical line, its keys fixed, each of a
    fixed type: whole-number counts, seconds as numbers, and the run's readings
    null when no sidecar ran.
    """

    @pytest.fixture(autouse=True)
    def _known_bounds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Cap 1, queue 1, whatever the environment sets, so the line's bounds are known."""
        _bound(monkeypatch, cap=1, queue=1, wait=EXPORTS_RETURN_WITHIN_SECONDS)

    @pytest.mark.parametrize("target", SUMMARY_TARGETS)
    def test_an_export_of_three_slides_that_all_passed(
        self,
        target: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _summarised_sidecar(tmp_path, monkeypatch)

        exported = pptx_from_html_huashu.build_pptx_huashu("deck", THREE_SLIDES, target=target)

        assert exported == (b"PK", [])
        summary = _the_summary(capsys)
        assert _counts(summary) == {
            **_built(slides=3, exported=3, failures=0, outcome="ok", deck=2),
            "target": target,
        }
        assert summary["waitSeconds"] < REFUSED_WITHIN_SECONDS, "a free slot was waited for"
        _assert_ran(summary, at_least=SUMMARISED_RUN_SECONDS, slides=3)

    def test_an_export_some_of_whose_slides_failed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _summarised_sidecar(tmp_path, monkeypatch, failed=(1,))

        pptx, failures = pptx_from_html_huashu.build_pptx_huashu("deck", THREE_SLIDES)

        assert (pptx, [failure["slide_index"] for failure in failures]) == (b"PK", [1])
        summary = _the_summary(capsys)
        assert _counts(summary) == _built(
            slides=3, exported=2, failures=1, outcome="partial", deck=2
        )
        _assert_ran(summary, at_least=SUMMARISED_RUN_SECONDS, slides=3)

    def test_an_export_every_slide_of_which_failed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """No deck, every slide's failure returned: failed."""
        _summarised_sidecar(tmp_path, monkeypatch, failed=(0, 1, 2))

        pptx, failures = pptx_from_html_huashu.build_pptx_huashu("deck", THREE_SLIDES)

        assert (pptx, len(failures)) == (b"", 3)
        summary = _the_summary(capsys)
        assert _counts(summary) == _built(
            slides=3, exported=0, failures=3, outcome="failed", deck=0
        )
        _assert_ran(summary, at_least=SUMMARISED_RUN_SECONDS, slides=3)

    def test_an_export_whose_sidecar_failed_outright(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """No deck and no result line: the export raises, and its line says failed."""
        _sidecar_script(tmp_path, monkeypatch, STUB_FAILING_RUN)

        with pytest.raises(HuashuExportError, match="no pptx and no result line"):
            pptx_from_html_huashu.build_pptx_huashu("deck", THREE_SLIDES)

        summary = _the_summary(capsys)
        assert _counts(summary) == _built(
            slides=3, exported=0, failures=0, outcome="failed", deck=0
        )
        assert summary["runSeconds"] is not None and summary["secondsPerSlide"] is not None

    def test_an_export_that_timed_out(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _sidecar_script(
            tmp_path, monkeypatch, STUB_HUNG_RUN % {"lifetime_ms": STUB_LIFETIME_SECONDS * 1000}
        )
        monkeypatch.setattr(
            pptx_from_html_huashu, "SIDECAR_TIMEOUT_SECONDS", STUB_TIMEOUT_SECONDS
        )

        with pytest.raises(HuashuExportError, match="timed out"):
            pptx_from_html_huashu.build_pptx_huashu("deck", THREE_SLIDES)

        summary = _the_summary(capsys)
        assert _counts(summary) == _built(
            slides=3, exported=0, failures=0, outcome="timeout", deck=0
        )
        _assert_ran(summary, at_least=STUB_TIMEOUT_SECONDS, slides=3)

    def test_an_export_refused_at_once(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Every place taken: busy, no wait and no run."""
        monkeypatch.setattr(pptx_from_html_huashu, "is_available", lambda: True)
        monkeypatch.setattr(pptx_from_html_huashu, "run_sidecar_process", _RUN_NOT_EXPECTED)
        admissions = pptx_from_html_huashu._sidecar_admissions
        assert admissions.acquire(blocking=False) and admissions.acquire(blocking=False)
        try:
            with pytest.raises(pptx_from_html_huashu.HuashuBusyError):
                pptx_from_html_huashu.build_pptx_huashu("deck", THREE_SLIDES)
        finally:
            admissions.release()
            admissions.release()

        summary = _the_summary(capsys)
        assert _counts(summary) == _built(slides=3, exported=0, failures=0, outcome="busy", deck=0)
        assert summary["waitSeconds"] == 0.0, summary
        _assert_never_ran(summary)

    def test_an_export_refused_after_its_wait(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The slot taken for longer than the wait bound: busy, after waiting the bound."""
        _bound(monkeypatch, cap=1, queue=1, wait=WAIT_BOUND_SECONDS)
        monkeypatch.setattr(pptx_from_html_huashu, "is_available", lambda: True)
        monkeypatch.setattr(pptx_from_html_huashu, "run_sidecar_process", _RUN_NOT_EXPECTED)
        slots = pptx_from_html_huashu._sidecar_slots
        assert slots.acquire(blocking=False)  # another export's run
        try:
            (export,) = _exports_at_once(1)
        finally:
            slots.release()

        assert type(export.outcome) is pptx_from_html_huashu.HuashuBusyError, export
        summary = _the_summary(capsys)
        assert _counts(summary) == _built(slides=1, exported=0, failures=0, outcome="busy", deck=0)
        assert (
            WAIT_BOUND_SECONDS - 0.1
            <= summary["waitSeconds"]
            < WAIT_BOUND_SECONDS + REFUSED_WITHIN_SECONDS
        ), summary
        _assert_never_ran(summary)

    @pytest.mark.parametrize(
        ("run", "raised", "outcome"),
        [
            (_raising(OSError("node not found")), OSError, "failed"),
            (
                _raising(subprocess.TimeoutExpired(["node"], 1, output=b"", stderr=b"")),
                HuashuExportError,
                "timeout",
            ),
            (_raising(KeyboardInterrupt()), KeyboardInterrupt, "failed"),
            (_raising(RuntimeError("anything else")), RuntimeError, "failed"),
            (_writing_no_deck, HuashuExportError, "failed"),
        ],
        ids=["no node", "timed out", "interrupted", "anything else", "no deck written"],
    )
    def test_an_export_however_its_run_ends(
        self,
        run,
        raised: type[BaseException],
        outcome: str,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Each way a run can end without a deck, the line logged once and named for it."""
        monkeypatch.setattr(pptx_from_html_huashu, "is_available", lambda: True)
        monkeypatch.setattr(pptx_from_html_huashu, "run_sidecar_process", run)

        with pytest.raises(raised):
            pptx_from_html_huashu.build_pptx_huashu("deck", THREE_SLIDES)

        summary = _the_summary(capsys)
        assert _counts(summary) == _built(
            slides=3, exported=0, failures=0, outcome=outcome, deck=0
        )
        # The stand-in run starts no process, so there is no memory to read.
        assert summary["runSeconds"] is not None and summary["peakRssMb"] is None, summary

    def test_a_queued_export_logs_its_wait(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Cap 1, two exports at once: the second waited out the first's run."""
        _recorded_sidecar(tmp_path, monkeypatch, RECORDED_RUN_SECONDS)

        exports = _exports_at_once(2)

        assert [export.outcome for export in exports] == [(b"PK", []), (b"PK", [])], exports
        first, second = _summaries(capsys.readouterr().err)
        assert first["waitSeconds"] < QUEUE_WAIT_SLACK_SECONDS, first
        assert second["waitSeconds"] >= first["runSeconds"] - QUEUE_WAIT_SLACK_SECONDS, (
            f"the second export waited {second['waitSeconds']}s for a slot the first held "
            f"{first['runSeconds']}s"
        )

    def test_the_line_holds_no_slide_content_and_no_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Counts and timings only: not the title, a slide, its notes, a failure or a file."""
        _summarised_sidecar(tmp_path, monkeypatch, failed=(0,))

        pptx, failures = pptx_from_html_huashu.build_pptx_huashu(
            f"{PLANTED_WORD} deck", THREE_SLIDES
        )

        assert pptx == b"PK" and PLANTED_WORD in failures[0]["error"], (
            "fixture drift: the planted word is not in what the export returns"
        )
        (line,) = _summary_lines(capsys.readouterr().err)
        assert PLANTED_WORD not in line, line
        assert "/" not in line and "\\" not in line, f"a path in the summary: {line}"

    def test_the_line_is_one_whole_line_in_the_apps_log(self, tmp_path: Path) -> None:
        """Under the app's own logging, the summary is one line, and the only one naming it.

        A fresh interpreter loads the app as a worker does, which leaves FastMCP's
        RichHandler as the root handler: it wraps a long line at 80 columns when
        stderr is no terminal, as on Databricks Apps. It then exports through a stub
        sidecar, its stderr a pipe and no COLUMNS set: the summary must reach that
        stderr whole, not as the handler's wrapped pieces, and not twice.
        """
        stub = tmp_path / "stub_sidecar.mjs"
        stub.write_text(STUB_SUMMARISED_RUN % {"failed": "[]", "ms": 0}, encoding="utf-8")
        script = (
            "import logging, sys\n"
            "from pathlib import Path\n"
            "import src.api.main\n"
            "from src.services import pptx_from_html_huashu as wrapper\n"
            "print(*[type(handler).__name__ for handler in logging.getLogger().handlers])\n"
            "wrapper.SIDECAR_SCRIPT = Path(sys.argv[1])\n"
            "wrapper.is_available = lambda: True\n"
            "slides = [{'html': '<p>x</p>', 'notes': ''}] * 3\n"
            "print(wrapper.build_pptx_huashu('deck', slides))\n"
        )
        env = {key: value for key, value in os.environ.items() if key != "COLUMNS"}
        env["ENVIRONMENT"] = "test"
        result = subprocess.run(
            [sys.executable, "-c", script, str(stub)],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=MODULE_LOAD_TIMEOUT_SECONDS,
        )

        assert result.returncode == 0, result.stderr
        handlers, exported = result.stdout.splitlines()[-2:]
        assert handlers == "RichHandler", (
            f"fixture drift: the app's root handlers are {handlers!r}, not FastMCP's RichHandler"
        )
        assert exported == "(b'PK', [])", result.stdout
        mentions = [line for line in result.stderr.splitlines() if "export summary" in line]
        assert len(mentions) == 1 and mentions[0].startswith(SUMMARY_PREFIX), mentions
        (summary,) = _summaries(result.stderr)
        assert summary["outcome"] == "ok", summary


@requires_node
class TestTheSummaryReadsTheWholeTree:
    """``peakRssMb``: the most the sidecar's process tree held, node and every Chromium it launched.

    Playwright launches each browser ``detached``, the leader of a process group
    of its own, so the tree is found through the PPID chain, as the blocked-loop
    sweep finds the browsers, not through node's group.
    """

    def test_the_tree_is_node_and_every_descendant(self) -> None:
        rows = [
            pptx_from_html_huashu._ProcessRow(pid=10, ppid=1, pgid=10, rss_bytes=1000),
            pptx_from_html_huashu._ProcessRow(pid=20, ppid=10, pgid=20, rss_bytes=100),
            # A detached browser, the leader of its own group, and its renderer.
            pptx_from_html_huashu._ProcessRow(pid=21, ppid=20, pgid=21, rss_bytes=10),
            pptx_from_html_huashu._ProcessRow(pid=22, ppid=21, pgid=21, rss_bytes=1),
            # A child in node's own group.
            pptx_from_html_huashu._ProcessRow(pid=23, ppid=20, pgid=20, rss_bytes=5),
            # Node's sibling, the app's other child: not node's.
            pptx_from_html_huashu._ProcessRow(pid=30, ppid=10, pgid=30, rss_bytes=7000),
        ]
        assert pptx_from_html_huashu._tree_resident_bytes(20, rows) == 116
        assert pptx_from_html_huashu._tree_resident_bytes(99, rows) is None

    def test_a_detached_child_is_counted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A detached child holding 128 MB is read, though it is outside node's own group."""
        pids_path = tmp_path / "pids.json"
        _sidecar_script(
            tmp_path,
            monkeypatch,
            STUB_DETACHED_MEMORY
            % {
                "bytes": DETACHED_CHILD_MB * BYTES_PER_MB,
                "pids": json.dumps(str(pids_path)),
                "ms": SUMMARISED_RUN_SECONDS * 1000,
            },
        )
        monkeypatch.setattr(
            pptx_from_html_huashu, "SIDECAR_TIMEOUT_SECONDS", STUB_LIFETIME_SECONDS
        )
        try:
            assert pptx_from_html_huashu.build_pptx_huashu("deck", [{"html": "x"}]) == (b"PK", [])
        finally:
            if pids_path.exists():
                pids = json.loads(pids_path.read_text(encoding="utf-8"))
                _kill([pids["sidecar"], pids["browser"]])

        summary = _the_summary(capsys)
        assert summary["peakRssMb"] is not None and summary["peakRssMb"] >= DETACHED_CHILD_MB, (
            f"the detached child's {DETACHED_CHILD_MB} MB were not read: {summary}"
        )

    def test_the_reading_is_the_peak_not_the_last(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A child that held 128 MB and was freed before the end: the reading is still 128 MB."""
        pids_path = tmp_path / "pids.json"
        _sidecar_script(
            tmp_path,
            monkeypatch,
            STUB_FREED_MEMORY
            % {
                "bytes": DETACHED_CHILD_MB * BYTES_PER_MB,
                "pids": json.dumps(str(pids_path)),
                "ms": SUMMARISED_RUN_SECONDS * 1000,
            },
        )
        monkeypatch.setattr(
            pptx_from_html_huashu, "SIDECAR_TIMEOUT_SECONDS", STUB_LIFETIME_SECONDS
        )
        readings: list[int] = []
        tree_bytes = pptx_from_html_huashu._tree_resident_bytes

        def recorded(root: int, table: list) -> int | None:
            held = tree_bytes(root, table)
            if held is not None:
                readings.append(held)
            return held

        monkeypatch.setattr(pptx_from_html_huashu, "_tree_resident_bytes", recorded)
        try:
            assert pptx_from_html_huashu.build_pptx_huashu("deck", [{"html": "x"}]) == (b"PK", [])
            _join_samplers()
        finally:
            if pids_path.exists():
                pids = json.loads(pids_path.read_text(encoding="utf-8"))
                _kill([pids["sidecar"], pids["browser"]])

        child = DETACHED_CHILD_MB * BYTES_PER_MB
        assert readings and max(readings) >= child, "fixture drift: the child was never read"
        assert readings[-1] < child, (
            f"fixture drift: the last reading ({readings[-1] / BYTES_PER_MB:.1f} MB) is not "
            "after the child was freed"
        )
        summary = _the_summary(capsys)
        assert summary["peakRssMb"] is not None and summary["peakRssMb"] >= DETACHED_CHILD_MB, (
            f"the reading is not the tree's peak but a later one: {summary}"
        )

    def test_this_process_has_a_resident_size(self) -> None:
        """The table the sampler reads: this process, its parent and group, and its RSS."""
        rows = {row.pid: row for row in pptx_from_html_huashu._read_process_table()}
        row = rows[os.getpid()]
        assert (row.ppid, row.pgid) == (os.getppid(), os.getpgrp())
        assert row.rss_bytes is not None and row.rss_bytes > 0, row

    def test_it_reads_each_resident_size_from_proc(self, tmp_path: Path) -> None:
        """Linux: /proc/<pid>/stat's 24th field, the resident pages."""
        page = os.sysconf("SC_PAGE_SIZE")
        fields = "S 7 42 42 0 -1 4194560 100 0 0 0 1 2 0 0 20 0 1 0 12345 1000000 250 0 0"
        for pid, stat in {
            "self": "7 (python) S 1 7 7 0",
            "42": f"42 (Chrome (helper) x) {fields}",
            "43": "43 (node) R 7 7 7 0",
        }.items():
            (tmp_path / pid).mkdir()
            (tmp_path / pid / "stat").write_text(stat, encoding="utf-8")

        rows = sorted(pptx_from_html_huashu._read_process_table(tmp_path))

        assert rows == [
            pptx_from_html_huashu._ProcessRow(pid=42, ppid=7, pgid=42, rss_bytes=250 * page),
            pptx_from_html_huashu._ProcessRow(pid=43, ppid=7, pgid=7, rss_bytes=None),
        ]


@requires_node
class TestASamplerThatFailsNeverFailsTheExport:
    """Memory sampling is telemetry: when it fails the export still succeeds, its reading null."""

    @pytest.fixture(autouse=True)
    def _known_bounds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _bound(monkeypatch, cap=1, queue=1, wait=EXPORTS_RETURN_WITHIN_SECONDS)

    def test_a_table_that_cannot_be_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _summarised_sidecar(tmp_path, monkeypatch)

        def unreadable(*_: object) -> list:
            raise OSError("no process table here")

        monkeypatch.setattr(pptx_from_html_huashu, "_read_process_table", unreadable)

        assert pptx_from_html_huashu.build_pptx_huashu("deck", THREE_SLIDES) == (b"PK", [])
        summary = _the_summary(capsys)
        assert (summary["outcome"], summary["peakRssMb"]) == ("ok", None), summary

    def test_a_failure_after_good_readings_leaves_no_partial_reading(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A reading that missed part of the run is not its peak: null, not a smaller number."""
        _summarised_sidecar(tmp_path, monkeypatch)
        read = pptx_from_html_huashu._read_process_table
        passes: list[int] = []

        def failing_after_two(*arguments: object) -> list:
            passes.append(len(passes))
            if len(passes) > 2:
                raise OSError("the process table went away")
            return read(*arguments)

        monkeypatch.setattr(pptx_from_html_huashu, "_read_process_table", failing_after_two)

        assert pptx_from_html_huashu.build_pptx_huashu("deck", THREE_SLIDES) == (b"PK", [])
        assert len(passes) > 2, f"fixture drift: the sampler read the table {len(passes)} times"
        summary = _the_summary(capsys)
        assert (summary["outcome"], summary["peakRssMb"]) == ("ok", None), summary

    def test_a_sampler_whose_thread_cannot_start(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A worker out of threads: the export runs unsampled."""
        _summarised_sidecar(tmp_path, monkeypatch)

        class Unstartable(threading.Thread):
            def start(self) -> None:
                raise RuntimeError("can't start new thread")

        monkeypatch.setattr(
            pptx_from_html_huashu,
            "threading",
            SimpleNamespace(Thread=Unstartable, Event=threading.Event, Lock=threading.Lock),
        )

        assert pptx_from_html_huashu.build_pptx_huashu("deck", THREE_SLIDES) == (b"PK", [])
        summary = _the_summary(capsys)
        assert (summary["outcome"], summary["peakRssMb"]) == ("ok", None), summary

    def test_a_failure_once_the_export_has_its_reading_says_nothing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A pass that fails after the export logged its number must not warn the number is null.

        The first pass reads the table; the next blocks until the export has
        returned, its summary logged with that first reading, and then fails.
        """
        _summarised_sidecar(tmp_path, monkeypatch)
        read = pptx_from_html_huashu._read_process_table
        returned = threading.Event()
        passes: list[int] = []

        def failing_once_returned(*arguments: object) -> list:
            passes.append(len(passes))
            if len(passes) == 1:
                return read(*arguments)
            returned.wait(EXPORTS_RETURN_WITHIN_SECONDS)
            raise OSError("the process table went away")

        monkeypatch.setattr(pptx_from_html_huashu, "_read_process_table", failing_once_returned)

        with caplog.at_level("WARNING", logger=pptx_from_html_huashu.__name__):
            assert pptx_from_html_huashu.build_pptx_huashu("deck", THREE_SLIDES) == (b"PK", [])
            returned.set()
            _join_samplers()

        assert len(passes) >= 2, f"fixture drift: the sampler read the table {len(passes)} times"
        warnings = [record.message for record in caplog.records if "memory" in record.message]
        assert warnings == [], f"a warning that contradicts the logged reading: {warnings}"
        summary = _the_summary(capsys)
        assert summary["peakRssMb"] is not None, f"fixture drift: no reading was logged: {summary}"


@requires_node
class TestTheContainerMemory:
    """The container's own memory, as its cgroup counts it, during the export.

    ``containerPeakMb`` is the most its cgroup's usage read (cgroup v2's
    ``memory.current``, else v1's ``memory.usage_in_bytes``), and
    ``containerWorkingSetMb`` the most its working set did: that usage less the
    page cache nothing has used lately (``memory.stat``'s ``inactive_file``, v1's
    ``total_inactive_file``), as the kubelet and cAdvisor count it. Both are read
    by the sampler in the same passes as the process tree, the largest reading of
    the export kept, never the cgroup's lifetime ``memory.peak``; null where there
    is no cgroup (macOS). The cgroup is this process's own: its path in
    ``/proc/self/cgroup`` under the cgroup root, else the root itself. Its limit
    is logged once, when a worker starts.
    """

    @pytest.fixture(autouse=True)
    def _known_bounds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _bound(monkeypatch, cap=1, queue=1, wait=EXPORTS_RETURN_WITHIN_SECONDS)

    def test_no_cgroup_memory_is_null(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _summarised_sidecar(tmp_path, monkeypatch)
        _use_cgroup(monkeypatch, tmp_path, {})

        assert pptx_from_html_huashu.build_pptx_huashu("deck", THREE_SLIDES) == (b"PK", [])

        summary = _the_summary(capsys)
        assert [summary[key] for key in CONTAINER_KEYS] == [None, None], summary
        assert summary["peakRssMb"] is not None, "the tree is read without a cgroup"

    @pytest.mark.skipif(sys.platform != "darwin", reason="macOS has no cgroup filesystem")
    def test_on_macos_it_is_null(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _summarised_sidecar(tmp_path, monkeypatch)

        assert pptx_from_html_huashu.build_pptx_huashu("deck", THREE_SLIDES) == (b"PK", [])

        summary = _the_summary(capsys)
        assert [summary.get(key, "absent") for key in CONTAINER_KEYS] == [None, None], summary

    def test_it_is_the_largest_cgroup_v2_reading_during_the_export(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """memory.current moves 100, 300, 500, 200 MB: 500, not the last, nor memory.peak's 900.

        No memory.stat: the working set cannot be read, so it is null.
        """
        cgroup = _use_cgroup(
            monkeypatch,
            tmp_path,
            {
                "memory.current": f"{CGROUP_BEFORE_MB * BYTES_PER_MB}\n",
                "memory.peak": f"{CGROUP_LIFETIME_PEAK_MB * BYTES_PER_MB}\n",
                "memory.max": "max\n",
            },
            membership="0::/\n",
        )
        _sidecar_script(
            tmp_path,
            monkeypatch,
            STUB_CGROUP_READINGS
            % {
                "usage": json.dumps(str(cgroup / "memory.current")),
                "readings": json.dumps(list(CGROUP_READINGS_MB)),
                "hold_ms": CGROUP_HOLD_MS,
            },
        )

        assert pptx_from_html_huashu.build_pptx_huashu("deck", [{"html": "x"}]) == (b"PK", [])

        summary = _the_summary(capsys)
        assert summary["containerPeakMb"] == float(max(CGROUP_READINGS_MB)), summary
        assert summary["containerWorkingSetMb"] is None, summary

    def test_the_working_set_is_its_own_peak(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Usage less inactive file cache, at its largest: 400, though usage peaks at 500."""
        cgroup = _use_cgroup(
            monkeypatch,
            tmp_path,
            {
                "memory.current": f"{WORKING_SET_BEFORE[0] * BYTES_PER_MB}\n",
                "memory.stat": _memory_stat("inactive_file", WORKING_SET_BEFORE[1]),
            },
            membership="0::/\n",
        )
        _sidecar_script(
            tmp_path,
            monkeypatch,
            STUB_CGROUP_WORKING_SET
            % {
                "usage": json.dumps(str(cgroup / "memory.current")),
                "stat": json.dumps(str(cgroup / "memory.stat")),
                "before": WORKING_SET_BEFORE[1],
                "steps": json.dumps([list(step) for step in WORKING_SET_STEPS]),
                "noise_mb": STAT_NOISE_MB,
                "hold_ms": CGROUP_HOLD_MS,
            },
        )

        assert pptx_from_html_huashu.build_pptx_huashu("deck", [{"html": "x"}]) == (b"PK", [])

        summary = _the_summary(capsys)
        assert summary["containerPeakMb"] == 500.0, summary
        assert summary["containerWorkingSetMb"] == 400.0, summary

    @pytest.mark.parametrize(
        ("files", "membership", "peak", "working_set"),
        [
            (
                {
                    "memory/memory.usage_in_bytes": f"{256 * BYTES_PER_MB}\n",
                    "memory/memory.stat": _memory_stat("total_inactive_file", 56)
                    + f"inactive_file {6 * BYTES_PER_MB}\n",
                },
                "12:memory:/\n",
                256.0,
                200.0,
            ),
            (
                {
                    "memory.current": f"{100 * BYTES_PER_MB}\n",
                    "memory.stat": _memory_stat("inactive_file", 150),
                },
                "0::/\n",
                100.0,
                0.0,
            ),
        ],
        ids=["v1, its total_inactive_file", "more inactive cache than usage"],
    )
    def test_the_working_set_as_the_kubelet_counts_it(
        self,
        files: dict[str, str],
        membership: str,
        peak: float,
        working_set: float,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _summarised_sidecar(tmp_path, monkeypatch)
        _use_cgroup(monkeypatch, tmp_path, files, membership=membership)

        assert pptx_from_html_huashu.build_pptx_huashu("deck", THREE_SLIDES) == (b"PK", [])

        summary = _the_summary(capsys)
        assert [summary[key] for key in CONTAINER_KEYS] == [peak, working_set], summary

    @pytest.mark.parametrize(
        ("membership", "files", "found"),
        [
            # A private cgroup namespace: the container's own cgroup is the root.
            ("0::/\n", {"memory.current": "1"}, "."),
            # A host's view: the root is the machine's, the container's is nested.
            (
                "0::/kubepods/pod1/container\n",
                {"memory.current": "1", "kubepods/pod1/container/memory.current": "2"},
                "kubepods/pod1/container",
            ),
            # The path names a cgroup this view does not show (a bind-mounted one).
            ("0::/kubepods/pod1/container\n", {"memory.current": "1"}, "."),
            # cgroup v1, the memory controller's line, among others and a v2 line.
            (
                "12:memory:/docker/abc\n4:cpu,cpuacct:/docker/abc\n0::/\n",
                {
                    "memory/memory.usage_in_bytes": "1",
                    "memory/docker/abc/memory.usage_in_bytes": "2",
                },
                "memory/docker/abc",
            ),
            (
                "7:hugetlb,memory:/docker/abc\n",
                {
                    "memory/memory.usage_in_bytes": "1",
                    "memory/docker/abc/memory.usage_in_bytes": "2",
                },
                "memory/docker/abc",
            ),
            # A path that climbs ("..") puts the process outside the root it sees, so
            # that root is not its own cgroup: nothing is read, not the root.
            ("0::/../outside\n", {"memory.current": "1", "../outside/memory.current": "2"}, None),
            # No /proc/self/cgroup (macOS, here with a cgroup filesystem anyway).
            (None, {"memory.current": "1"}, "."),
            (None, {}, None),
        ],
        ids=[
            "private namespace",
            "host view, nested",
            "nested, not in this view",
            "v1 memory line",
            "v1 memory among controllers",
            "climbs out",
            "no proc file",
            "nothing",
        ],
    )
    def test_the_cgroup_is_this_processs_own(
        self,
        membership: str | None,
        files: dict[str, str],
        found: str | None,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        root = _use_cgroup(monkeypatch, tmp_path / "fs", files, membership=membership)

        cgroup = pptx_from_html_huashu._container_cgroup()

        if found is None:
            assert cgroup is None, cgroup
        else:
            assert cgroup is not None, f"no cgroup found, {found!r} expected"
            assert cgroup.directory.resolve() == (root / found).resolve(), cgroup

    def test_the_export_reads_its_own_cgroup_not_the_machines(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A host's view: the root cgroup holds the machine's 7000 MB, the container's 300."""
        _summarised_sidecar(tmp_path, monkeypatch)
        _use_cgroup(
            monkeypatch,
            tmp_path,
            {
                "memory.current": f"{7000 * BYTES_PER_MB}\n",
                "kubepods/pod1/container/memory.current": f"{300 * BYTES_PER_MB}\n",
            },
            membership="0::/kubepods/pod1/container\n",
        )

        assert pptx_from_html_huashu.build_pptx_huashu("deck", THREE_SLIDES) == (b"PK", [])

        assert _the_summary(capsys)["containerPeakMb"] == 300.0

    @pytest.mark.parametrize("failure", ["unparsable", "unreadable"])
    def test_a_cgroup_that_fails_nulls_only_the_container(
        self,
        failure: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A cgroup read or parse error: the container's keys null, the process tree still read."""
        _summarised_sidecar(tmp_path, monkeypatch)
        _use_cgroup(
            monkeypatch,
            tmp_path,
            {"memory.current": "not a number\n" if failure == "unparsable" else "1\n"},
            membership="0::/\n",
        )
        if failure == "unreadable":

            def unreadable(*_: object) -> tuple:
                raise OSError("Input/output error")

            monkeypatch.setattr(pptx_from_html_huashu, "_container_memory", unreadable)

        with caplog.at_level("WARNING", logger=pptx_from_html_huashu.__name__):
            assert pptx_from_html_huashu.build_pptx_huashu("deck", THREE_SLIDES) == (b"PK", [])

        summary = _the_summary(capsys)
        assert [summary[key] for key in CONTAINER_KEYS] == [None, None], summary
        assert summary["peakRssMb"] is not None and summary["peakRssMb"] > 0, summary
        warned = [record.message for record in caplog.records if "memory" in record.message]
        assert len(warned) == 1 and "container" in warned[0], warned

    def test_a_process_table_that_fails_nulls_only_the_tree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _summarised_sidecar(tmp_path, monkeypatch)
        _use_cgroup(
            monkeypatch,
            tmp_path,
            {
                "memory.current": f"{256 * BYTES_PER_MB}\n",
                "memory.stat": _memory_stat("inactive_file", 56),
            },
            membership="0::/\n",
        )

        def unreadable(*_: object) -> list:
            raise OSError("no process table here")

        monkeypatch.setattr(pptx_from_html_huashu, "_read_process_table", unreadable)

        assert pptx_from_html_huashu.build_pptx_huashu("deck", THREE_SLIDES) == (b"PK", [])

        summary = _the_summary(capsys)
        assert summary["peakRssMb"] is None, summary
        assert [summary[key] for key in CONTAINER_KEYS] == [256.0, 200.0], summary

    @pytest.mark.parametrize(
        ("files", "membership", "limit"),
        [
            (
                {"memory.current": "1\n", "memory.max": f"{4096 * BYTES_PER_MB}\n"},
                None,
                "4096.0 MB",
            ),
            # cgroup v2 says "no limit" with "max": a reading, not an error.
            ({"memory.current": "1\n", "memory.max": "max\n"}, None, "none"),
            (
                {
                    "memory/memory.usage_in_bytes": "1\n",
                    "memory/memory.limit_in_bytes": f"{2048 * BYTES_PER_MB}\n",
                },
                None,
                "2048.0 MB",
            ),
            (
                {
                    "memory/memory.usage_in_bytes": "1\n",
                    "memory/memory.limit_in_bytes": f"{CGROUP_V1_UNLIMITED}\n",
                },
                None,
                "none",
            ),
            ({}, None, "none"),
            ({"memory.current": "1\n", "memory.max": "not a number\n"}, None, "none"),
            # A host's view: the container's own cgroup's limit, not the machine's root.
            (
                {
                    "memory.current": "1\n",
                    "kubepods/pod1/container/memory.current": "1\n",
                    "kubepods/pod1/container/memory.max": f"{2048 * BYTES_PER_MB}\n",
                },
                "0::/kubepods/pod1/container\n",
                "2048.0 MB",
            ),
            # The limit is the pod's, set on a parent the container's cgroup sits in.
            (
                {
                    "memory.current": "1\n",
                    "kubepods/pod1/memory.max": f"{1024 * BYTES_PER_MB}\n",
                    "kubepods/pod1/container/memory.current": "1\n",
                    "kubepods/pod1/container/memory.max": "max\n",
                },
                "0::/kubepods/pod1/container\n",
                "1024.0 MB",
            ),
            # The walk up stops at the top of the hierarchy in view: a smaller
            # limit file above it is not the container's.
            (
                {
                    "memory.current": "1\n",
                    "memory.max": f"{2048 * BYTES_PER_MB}\n",
                    "../memory.max": f"{512 * BYTES_PER_MB}\n",
                },
                "0::/\n",
                "2048.0 MB",
            ),
            (
                {
                    "memory/memory.usage_in_bytes": "1\n",
                    "memory/memory.limit_in_bytes": f"{2048 * BYTES_PER_MB}\n",
                    "memory.limit_in_bytes": f"{512 * BYTES_PER_MB}\n",
                },
                "12:memory:/\n",
                "2048.0 MB",
            ),
            # A climbing path: the root in view is not the container's, so no limit.
            (
                {"memory.current": "1\n", "memory.max": f"{1024 * BYTES_PER_MB}\n"},
                "0::/../outside\n",
                "none",
            ),
        ],
        ids=[
            "v2 limit",
            "v2 no limit",
            "v1 limit",
            "v1 no limit",
            "no cgroup",
            "unreadable",
            "own nested cgroup",
            "a parent's limit",
            "v2 stops at its top",
            "v1 stops at its top",
            "climbs out",
        ],
    )
    def test_the_limit_is_logged_when_a_worker_starts(
        self,
        files: dict[str, str],
        membership: str | None,
        limit: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
        request: pytest.FixtureRequest,
    ) -> None:
        """Once, in MB or as none; only a limit file that cannot be read is warned about."""
        _use_cgroup(monkeypatch, tmp_path, files, membership=membership)

        with caplog.at_level("WARNING", logger=pptx_from_html_huashu.__name__):
            pptx_from_html_huashu.log_sidecar_bounds()

        stderr = capsys.readouterr().err
        lines = [line for line in stderr.splitlines() if line.startswith(LIMIT_PREFIX)]
        assert lines == [LIMIT_PREFIX + limit], stderr
        warned = [record.message for record in caplog.records if "cgroup limit" in record.message]
        unreadable = request.node.callspec.id == "unreadable"
        assert bool(warned) is unreadable, warned


class _NoSampler:
    """A memory sampler that reads nothing: the export as it ran before its summary."""

    def watch(self, process: subprocess.Popen) -> None:
        return None

    def stop(self) -> pptx_from_html_huashu._MemoryPeaks:
        return pptx_from_html_huashu._MemoryPeaks(
            tree_mb=None, container_mb=None, working_set_mb=None
        )


def _deck_text(pptx: bytes) -> str:
    """Every slide part of a deck, as text."""
    with zipfile.ZipFile(io.BytesIO(pptx)) as deck:
        return "".join(
            deck.read(name).decode("utf-8")
            for name in deck.namelist()
            if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
        )


@pytest.mark.slow
@requires_huashu_sidecar
class TestTheSummaryOfARealExport:
    """The real sidecar, node and Chromium: what its line reads, and what it leaves alone."""

    def test_it_reads_the_memory_of_node_and_its_browsers(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("HUASHU_PIPELINE_ENABLED", "1")
        document = slide_document(f"<div class='slide'><p>{PLANTED_WORD}</p></div>")

        pptx, failures = build_pptx_guarded(
            f"{PLANTED_WORD} deck",
            [{"html": document, "notes": PLANTED_WORD}],
            bypass_validation=True,
        )

        assert failures == [] and PLANTED_WORD in _deck_text(pptx), (
            "fixture drift: the planted word is not in the deck"
        )
        (line,) = _summary_lines(capsys.readouterr().err)
        assert PLANTED_WORD not in line, line
        (summary,) = _summaries(line)
        assert (summary["outcome"], summary["slidesExported"]) == ("ok", 1), summary
        assert summary["pptxBytes"] == len(pptx), summary
        assert summary["peakRssMb"] is not None and summary["peakRssMb"] > 0, summary

    def test_a_pinned_corpus_export_is_identical_with_it(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The 18-slide corpus, its fonts pinned: the same deck with the summary and without it.

        Without it: no memory sampler and no line. The sampler reads the process
        table while the sidecar renders, so it must not change what is rendered.
        """
        monkeypatch.setenv("HUASHU_PIPELINE_ENABLED", "1")
        css = pinned_font_css()
        paths = sorted((CORPUS_DIR / "slides").glob("*.html"))
        assert len(paths) == 18, f"fixture drift: the corpus has {len(paths)} slides"
        title = CORPUS_DECK.get("title", TEST_DECK_TITLE)
        slides = [
            {
                "html": slide_document(
                    path.read_text(encoding="utf-8"),
                    css=css,
                    scripts=CORPUS_DECK.get("scripts", ""),
                    external_scripts=tuple(CORPUS_DECK.get("external_scripts", [])),
                    title=title,
                    slide_id=path.stem,
                ),
                "notes": path.stem,
            }
            for path in paths
        ]

        def manifest() -> dict:
            pptx, failures = build_pptx_guarded(title, slides, bypass_validation=True)
            assert failures == [], failures
            return structural_manifest(pptx)

        with monkeypatch.context() as without_summary:
            without_summary.setattr(pptx_from_html_huashu, "_TreeMemorySampler", _NoSampler)
            without_summary.setattr(pptx_from_html_huashu.telemetry_logger, "disabled", True)
            unsummarised = manifest()
        assert _summary_lines(capsys.readouterr().err) == [], "fixture drift: the summary ran"
        summarised = manifest()
        (summary,) = _summaries(capsys.readouterr().err)
        assert summary["outcome"] == "ok" and summary["peakRssMb"] is not None, summary

        assert summarised == unsummarised, "the export summary changed the deck"
