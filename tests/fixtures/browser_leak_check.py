"""No Playwright browser the test suite starts outlives the session.

The export suites start node helpers that launch Chromium through Playwright, each browser
detached, the leader of a process group of its own. A helper ended outright (SIGKILL), or one
that crashed, runs none of node's exit handlers, so a browser it launched can go on running with
no parent: an idle one exits once node's end of its pipe closes, but one whose page is blocked
does not. Over a long session such browsers piled up until the machine ran out of memory.

So the session gives the suite's child processes a ``TMPDIR`` of its own
(``SESSION_TMPDIR_PREFIX``): Playwright makes each browser's profile under its launching node's
``TMPDIR``, and names it on the browser's command line, so every browser the suite starts says
it is the suite's. When the session ends, a browser still running with its profile there gets
``BROWSERS_GONE_WITHIN_SECONDS`` to exit; past that its process group is killed (never the
session's own: a browser in that group is killed by its pid) and the session fails (an error at
the last test's teardown), naming the pids. A test that sets ``TMPDIR`` for its own helpers
watches its own browsers.

``tests/conftest.py`` imports the fixture, so it is on for every session; a pytest run of its own
loads it with ``-p tests.fixtures.browser_leak_check``.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

# The prefix of the session's own TMPDIR.
SESSION_TMPDIR_PREFIX = "tellr-test-browsers-"
# What only Playwright's launched browsers carry on their command line, and the prefix of the
# profile directory Playwright makes for each under its launching node's TMPDIR.
PLAYWRIGHT_BROWSER_FLAG = "--remote-debugging-pipe"
PLAYWRIGHT_PROFILE_PREFIX = "playwright_chromiumdev_profile-"
# How long a browser still running when the session ends has to exit by itself.
BROWSERS_GONE_WITHIN_SECONDS = 10
# How long the process table may take to be read.
PROCESS_LIST_TIMEOUT_SECONDS = 10


def playwright_browsers(scope: Path) -> dict[int, int]:
    """The running Playwright browsers whose profile is at or under ``scope``: pid -> group."""
    profile = re.compile(
        re.escape(f"{scope}/") + r"(?:[^/\s]+/)*" + re.escape(PLAYWRIGHT_PROFILE_PREFIX)
    )
    listing = subprocess.run(
        ["ps", "-axo", "pid=,pgid=,command="],
        capture_output=True,
        text=True,
        check=True,
        timeout=PROCESS_LIST_TIMEOUT_SECONDS,
    ).stdout
    browsers = {}
    for line in listing.splitlines():
        fields = line.split(None, 2)
        if len(fields) == 3 and PLAYWRIGHT_BROWSER_FLAG in fields[2] and profile.search(fields[2]):
            browsers[int(fields[0])] = int(fields[1])
    return browsers


def _still_running(scope: Path) -> dict[int, int]:
    """The browsers under ``scope`` still running once they have had time to exit."""
    deadline = time.monotonic() + BROWSERS_GONE_WITHIN_SECONDS
    while True:
        browsers = playwright_browsers(scope)
        if not browsers or time.monotonic() > deadline:
            return browsers
        time.sleep(0.2)


def _kill_groups(browsers: dict[int, int]) -> None:
    """Kill each browser's process group, never this process's own.

    A browser in this process's group (one its helper launched without detaching it) is killed
    alone, by its pid: killing that group would kill the session itself, and whatever else is
    in its group (the shell or ``uv`` that started pytest).
    """
    own_group = os.getpgrp()
    for group in sorted(set(browsers.values()) - {own_group}):
        _send_sigkill(os.killpg, group)
    for pid in sorted(pid for pid, group in browsers.items() if group == own_group):
        _send_sigkill(os.kill, pid)


def _send_sigkill(send: Callable[[int, int], None], target: int) -> None:
    """``send(target, SIGKILL)``: ``os.killpg`` to a group, or ``os.kill`` to a process."""
    try:
        send(target, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass  # gone already, or a zombie its parent has yet to reap


@pytest.fixture(scope="session", autouse=True)
def no_playwright_browser_outlives_the_suite() -> Iterator[Path]:
    """The session's own TMPDIR for its child processes; at its end, no browser of theirs runs.

    Python's own temporary directory stays where it was: ``mkdtemp`` reads it, and keeps it,
    before the environment's ``TMPDIR`` is changed for the children.
    """
    scope = Path(tempfile.mkdtemp(prefix=SESSION_TMPDIR_PREFIX))
    previous = os.environ.get("TMPDIR")
    os.environ["TMPDIR"] = str(scope)
    try:
        yield scope
    finally:
        if previous is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = previous
        survivors = _still_running(scope)
        _kill_groups(survivors)
        shutil.rmtree(scope, ignore_errors=True)
    if survivors:
        pytest.fail(
            f"{len(survivors)} Playwright browser(s) the suite started were still running at "
            f"its end, now killed: pids {sorted(survivors)}, process groups "
            f"{sorted(set(survivors.values()))}. A test or helper left them: run node through "
            "tests/fixtures/export_snapshot_support.py run_node, which ends its browsers with it.",
            pytrace=False,
        )
