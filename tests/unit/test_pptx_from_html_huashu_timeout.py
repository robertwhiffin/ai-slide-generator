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
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.api.routes import export as export_routes
from src.services import pptx_from_html_huashu
from src.services.pptx_from_html_huashu import HuashuExportError
from tests.fixtures.export_snapshot_support import requires_huashu_sidecar, requires_node

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
  const newPage = browser.newPage.bind(browser);
  browser.newPage = async (...pageArguments) => {
    const page = await newPage(...pageArguments);
    const goto = page.goto.bind(page);
    page.goto = async (...gotoArguments) => {
      await goto(...gotoArguments);
      for (;;) { /* the event loop blocked */ }
    };
    return page;
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


def _playwright_browsers() -> dict[int, int]:
    """Every running Playwright browser process: pid -> process group id."""
    listing = subprocess.run(
        ["ps", "-axo", "pid=,pgid=,command="], capture_output=True, text=True, check=True
    ).stdout
    browsers = {}
    for line in listing.splitlines():
        fields = line.split(None, 2)
        if len(fields) == 3 and PLAYWRIGHT_BROWSER_FLAG in fields[2]:
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
    """The Playwright browsers that start while it watches, with their process groups."""

    def __init__(self) -> None:
        self._before = set(_playwright_browsers())
        self.seen: dict[int, int] = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()

    def _watch(self) -> None:
        while not self._stop.is_set():
            for pid, group in _playwright_browsers().items():
                if pid not in self._before:
                    self.seen[pid] = group
            time.sleep(0.2)

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()

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
def browser_watch() -> Iterator[_BrowserWatch]:
    watch = _BrowserWatch()
    try:
        yield watch
    finally:
        watch.stop()
        for group in set(watch.seen.values()):
            try:
                os.killpg(group, signal.SIGKILL)
            except ProcessLookupError:
                pass


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


@requires_node
class TestTheSidecarsAreCappedPerWorker:
    """Each node and Chromium tree takes about 790 MB: a worker runs at most its cap at once.

    The cap is ``TELLR_SIDECAR_CONCURRENCY`` (default 1 per worker process).
    An export past it waits for a slot, says so once on its log, and starts its
    timeout only once it has the slot.
    """

    def _two_exports(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cap: int
    ) -> list[tuple[float, float]]:
        log = tmp_path / "runs.jsonl"
        stub = tmp_path / "stub_recorded_run.mjs"
        stub.write_text(
            STUB_RECORDED_RUN
            % {"log": json.dumps(str(log)), "ms": RECORDED_RUN_SECONDS * 1000},
            encoding="utf-8",
        )
        monkeypatch.setattr(pptx_from_html_huashu, "SIDECAR_SCRIPT", stub)
        monkeypatch.setattr(
            pptx_from_html_huashu, "SIDECAR_TIMEOUT_SECONDS", CAPPED_TIMEOUT_SECONDS
        )
        monkeypatch.setattr(pptx_from_html_huashu, "is_available", lambda: True)
        monkeypatch.setattr(
            pptx_from_html_huashu, "_sidecar_slots", threading.BoundedSemaphore(cap), raising=False
        )
        outcomes: list[object] = []

        def export() -> None:
            try:
                outcomes.append(
                    pptx_from_html_huashu.build_pptx_huashu("deck", [{"html": "<p>x</p>"}])
                )
            except Exception as error:  # noqa: BLE001 (recorded, then asserted on)
                outcomes.append(error)

        threads = [threading.Thread(target=export) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=4 * RECORDED_RUN_SECONDS + RETURN_SLACK_SECONDS)
        assert not any(thread.is_alive() for thread in threads), "an export never returned"
        assert outcomes == [(b"PK", []), (b"PK", [])], outcomes
        events: dict[int, dict[str, float]] = {}
        for line in log.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            events.setdefault(entry["pid"], {})[entry["event"]] = entry["at"]
        return sorted((run["start"], run["end"]) for run in events.values())

    def test_with_a_cap_of_one_the_sidecars_run_one_after_the_other(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The second waits for the first, and its wait does not count against its timeout."""
        with caplog.at_level("INFO", logger=pptx_from_html_huashu.__name__):
            (first, second) = self._two_exports(tmp_path, monkeypatch, cap=1)
        assert second[0] >= first[1], f"the sidecars overlapped: {first} and {second}"
        waits = [
            record for record in caplog.records if "waits for a sidecar slot" in record.message
        ]
        assert len(waits) == 1 and waits[0].message.startswith("[huashu]"), [
            record.message for record in caplog.records
        ]

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
