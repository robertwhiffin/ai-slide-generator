"""The export tests leave no Playwright browser running.

The export suites start node helpers that launch Chromium through Playwright: ``measure.cjs``
(``browser_rect`` and its kin), ``node -e`` scripts (``node_json``), the slide-root probes, and
the sidecar itself. Playwright launches each browser detached, the leader of a process group of
its own, and kills it from node's exit handler. ``subprocess.run``'s timeout SIGKILLs node, so no
handler of node's runs and the browser is left running with no parent; over a long session such
browsers piled up until the machine ran out of memory. So the export test support runs every
node helper through the wrapper's ``run_sidecar_process`` (``run_node``), which ends node
through its exit path, kills its browsers' groups and then its own; and a session-wide check
(``tests/fixtures/browser_leak_check.py``) gives the suite's child processes a ``TMPDIR`` of its
own and, once the session ends, kills and reports every Playwright browser still running with
its profile under it.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src.services import pptx_from_html_huashu
from tests.fixtures import export_snapshot_support as support
from tests.fixtures.export_snapshot_support import requires_huashu_sidecar

REPO_ROOT = Path(__file__).resolve().parents[2]
RENDER_SLIDE = pptx_from_html_huashu.SIDECAR_DIR / "render_slide.cjs"
# What only Playwright's launched browsers carry on their command line, and the prefix of the
# profile directory each is given under its launching node's TMPDIR.
PLAYWRIGHT_BROWSER_FLAG = "--remote-debugging-pipe"
PLAYWRIGHT_PROFILE_PREFIX = "playwright_chromiumdev_profile-"
# The prefix of the session's own TMPDIR (browser_leak_check.SESSION_TMPDIR_PREFIX).
SESSION_TMPDIR_PREFIX = "tellr-test-browsers-"
# A helper's timeout here: past a browser's launch, well short of the helpers' own.
SHORT_HELPER_TIMEOUT_SECONDS = 4
# How long a browser ended with its helper may take to be gone.
GONE_WITHIN_SECONDS = 15
# How long an inner pytest session, one browser launch and its end check, may take.
INNER_SESSION_SECONDS = 120

# A node helper that launches a browser as the engine does (render_slide.cjs launchOptions),
# opens a page whose script blocks it, says so on stderr, and then never ends. An idle browser
# exits by itself once node's end of its pipe closes (measured); one whose page is blocked does
# not, as a slide whose script loops forever leaves it.
HANGING_BROWSER = """
const { chromium } = require('playwright');
const { launchOptions } = require(%(render_slide)s);
const os = require('os');
(async () => {
  const browser = await chromium.launch(launchOptions(os.tmpdir()));
  const page = await (await browser.newContext()).newPage();
  page.goto('data:text/html,<script>for (;;) {}</script>').catch(() => {});
  await new Promise((resolve) => setTimeout(resolve, 500));
  console.error('browser launched');
  setInterval(() => {}, 1000);
})();
"""

# A test that leaves a browser running, as a helper killed outright does: node launches it with
# the session's TMPDIR, opens a page whose script blocks it, then SIGKILLs itself, so no exit
# handler kills the browser, and its blocked page keeps it from exiting by itself.
LEAKING_TEST = """
import subprocess
from src.services import pptx_from_html_huashu as wrapper

SCRIPT = '''
const { chromium } = require('playwright');
const { launchOptions } = require(%(render_slide)s);
const os = require('os');
(async () => {
  const browser = await chromium.launch(launchOptions(os.tmpdir()));
  const page = await (await browser.newContext()).newPage();
  page.goto('data:text/html,<script>for (;;) {}</script>').catch(() => {});
  await new Promise((resolve) => setTimeout(resolve, 500));
  process.kill(process.pid, 'SIGKILL');
})();
'''


def test_leaves_a_browser():
    subprocess.run(
        ["node", "-e", SCRIPT], cwd=wrapper.SIDECAR_DIR, env=wrapper.sidecar_subprocess_env(),
        timeout=60, check=False,
    )
"""

CLEAN_TEST = """
def test_leaves_nothing():
    pass
"""


def _browsers_under(scope: Path) -> dict[int, int]:
    """The running Playwright browsers whose profile is under ``scope``: pid -> process group."""
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


def _still_running_after_a_while(scope: Path) -> dict[int, int]:
    deadline = time.monotonic() + GONE_WITHIN_SECONDS
    while True:
        browsers = _browsers_under(scope)
        if not browsers or time.monotonic() > deadline:
            return browsers
        time.sleep(0.2)


def _kill(browsers: dict[int, int]) -> None:
    for group in set(browsers.values()):
        try:
            os.killpg(group, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


@pytest.fixture
def scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A TMPDIR for this test's helpers: their browsers' profiles go under it."""
    directory = tmp_path / "browsers"
    directory.mkdir()
    monkeypatch.setenv("TMPDIR", str(directory))
    yield directory
    _kill(_browsers_under(directory))


@requires_huashu_sidecar
class TestAHelperPastItsTimeoutTakesItsBrowsers:
    def test_a_node_script(self, scope: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(support, "NODE_TIMEOUT_SECONDS", SHORT_HELPER_TIMEOUT_SECONDS)
        script = HANGING_BROWSER % {"render_slide": repr(str(RENDER_SLIDE))}

        with pytest.raises(subprocess.TimeoutExpired) as raised:
            support.node_json(script)

        stderr = raised.value.stderr or b""
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        assert "browser launched" in stderr, f"fixture drift: no browser launched: {stderr!r}"
        left = _still_running_after_a_while(scope)
        assert left == {}, f"node_json left its browser running: {left}"

    def test_measure(self, scope: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """measure.cjs on a page that never loads, past the helper's timeout."""
        monkeypatch.setattr(support, "MEASURE_TIMEOUT_SECONDS", SHORT_HELPER_TIMEOUT_SECONDS)
        document = support.slide_document(
            '<div class="slide"><p>x</p><script>for (;;) {}</script></div>'
        )

        with pytest.raises(subprocess.TimeoutExpired):
            support.browser_rect(document, "p")

        left = _still_running_after_a_while(scope)
        assert left == {}, f"measure.cjs left its browser running: {left}"


def test_the_suite_gives_its_child_processes_a_temporary_directory_of_its_own() -> None:
    """So every Playwright browser the suite starts has its profile under it."""
    tmpdir = Path(os.environ["TMPDIR"])
    assert tmpdir.name.startswith(SESSION_TMPDIR_PREFIX) and tmpdir.is_dir(), tmpdir


def _inner_session(tmp_path: Path, test_source: str) -> subprocess.CompletedProcess:
    """A pytest session of its own over ``test_source``, with the session check loaded."""
    test_file = tmp_path / "test_inner.py"
    test_file.write_text(test_source, encoding="utf-8")
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:xdist"]
        + ["-p", "tests.fixtures.browser_leak_check", str(test_file)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=INNER_SESSION_SECONDS,
    )


@requires_huashu_sidecar
class TestTheSessionCheck:
    def test_a_browser_left_running_fails_the_session_and_is_killed(self, tmp_path: Path) -> None:
        source = LEAKING_TEST % {"render_slide": repr(str(RENDER_SLIDE))}

        inner = _inner_session(tmp_path, source)

        output = inner.stdout + inner.stderr
        assert inner.returncode != 0, output[-3000:]
        assert re.search(r"\b1 passed\b.*\b1 error\b", output), output[-3000:]
        assert "still running" in output, output[-3000:]
        left = re.findall(r"pids? \[([0-9, ]+)\]", output)
        assert left, output[-3000:]
        pids = [int(pid) for pid in left[0].split(",")]
        assert all(not _alive(pid) for pid in pids), f"the check left {pids} running"

    def test_a_session_that_leaves_nothing_passes(self, tmp_path: Path) -> None:
        inner = _inner_session(tmp_path, CLEAN_TEST)

        assert inner.returncode == 0, (inner.stdout + inner.stderr)[-3000:]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
