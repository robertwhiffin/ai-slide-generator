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

A browser is told by its command line, which both platforms give whole (``process_table``):
Playwright launches each with ``--remote-debugging-pipe`` and ``--user-data-dir`` naming its
profile, the last of its arguments. On Linux the table is read from ``/proc``, each command line
exactly as the kernel holds it; ``ps`` there fits its last column to ``COLUMNS`` when that is
set, which would cut those two arguments off. macOS has no ``/proc``, and its ``ps -ww`` prints
every column whole.

``tests/conftest.py`` imports the fixture, so it is on for every session; a pytest run of its own
loads it with ``-p tests.fixtures.browser_leak_check``.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import NamedTuple

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


class Process(NamedTuple):
    """One running process: its id, its parent's, its process group's, and its command line."""

    pid: int
    ppid: int
    pgid: int
    command: str


def _proc_table() -> list[Process]:
    """Linux: every process in ``/proc``, its command line's arguments joined by spaces."""
    table = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text(encoding="utf-8", errors="replace")
            arguments = (entry / "cmdline").read_bytes()
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue  # it ended while the table was read, or is no process of ours to read
        # "pid (name) state ppid pgrp ...": the name may hold spaces and parentheses.
        _, ppid, pgid = stat.rsplit(")", 1)[1].split()[:3]
        command = " ".join(
            argument.decode("utf-8", "replace") for argument in arguments.split(b"\0") if argument
        )
        table.append(Process(int(entry.name), int(ppid), int(pgid), command))
    return table


def _ps_table() -> list[Process]:
    """Elsewhere: ``ps`` over every process (``-A``), every column whole (``-ww``)."""
    listing = subprocess.run(
        ["ps", "-A", "-ww", "-o", "pid=", "-o", "ppid=", "-o", "pgid=", "-o", "command="],
        capture_output=True,
        text=True,
        check=True,
        timeout=PROCESS_LIST_TIMEOUT_SECONDS,
        env={key: value for key, value in os.environ.items() if key != "COLUMNS"},
    ).stdout
    table = []
    for line in listing.splitlines():
        fields = line.split(None, 3)
        if len(fields) >= 3:
            command = fields[3] if len(fields) == 4 else ""
            table.append(Process(int(fields[0]), int(fields[1]), int(fields[2]), command))
    return table


def process_table() -> list[Process]:
    """Every running process, with its whole command line, on Linux and on macOS alike."""
    return _proc_table() if sys.platform.startswith("linux") else _ps_table()


def is_playwright_browser(process: Process) -> bool:
    """Whether the process is a browser Playwright launched (its pipe flag; not its children)."""
    return PLAYWRIGHT_BROWSER_FLAG in process.command.split()


def playwright_browsers(scope: Path | str) -> dict[int, int]:
    """The running Playwright browsers whose profile is at or under ``scope``: pid -> group."""
    profile = re.compile(
        re.escape(f"{scope}/") + r"(?:[^/\s]+/)*" + re.escape(PLAYWRIGHT_PROFILE_PREFIX)
    )
    return {
        process.pid: process.pgid
        for process in process_table()
        if is_playwright_browser(process) and profile.search(process.command)
    }


# How much of each command line ``chromium_processes`` shows.
DESCRIBED_COMMAND_CHARACTERS = 300


def chromium_processes() -> list[str]:
    """Each running process whose command line names Chrome or Chromium, for a failure message.

    Its pid, parent and group, its command line's length, and the start and end of it: where a
    browser was expected and none was found, what the process table held in its place.
    """
    half = DESCRIBED_COMMAND_CHARACTERS // 2
    described = []
    for process in process_table():
        if not re.search(r"chrom|headless", process.command, re.I):
            continue
        command = process.command
        shown = command if len(command) <= 2 * half else f"{command[:half]} ... {command[-half:]}"
        described.append(
            f"pid {process.pid} ppid {process.ppid} pgid {process.pgid} "
            f"({len(command)} characters): {shown}"
        )
    return described


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
