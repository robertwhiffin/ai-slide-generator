"""Tellr → editable .pptx through the snapshot engine, a Node sidecar.

Spawns ``services/pptx-emit-huashu/emit_deck.mjs``, which loads each slide's
complete HTML document in server-side Chromium (Playwright), reads the page as
the browser laid it out (``render_slide.cjs``: settle the page, move the slide
root's ground onto body, snapshot the page read-only, screenshot what cannot be
drawn natively) and writes one editable .pptx with pptxgenjs: text boxes,
shapes, native tables and pictures where the browser drew them.

Availability. ``is_available()`` gates every call: it needs node, the
sidecar's ``node_modules`` and a Playwright Chromium, and either
``HUASHU_PIPELINE_ENABLED=1`` (set by the deployed app's app.yaml, whose boot
runs the sidecar's ``setup.sh`` to install them) or ``ENVIRONMENT=development``.
Until then the export routes answer 503, and the frontend's Google Slides
export falls back to the records pipeline.

Timeout. A run past ``SIDECAR_TIMEOUT_SECONDS`` must end node and every
Chromium it launched: killed alone, node would leave its browser running with
no parent, holding its memory until the app restarts. Playwright launches each
browser ``detached``, the leader of a process group of its own, and kills those
groups from node's exit handler, so no signal to node's group reaches a
browser. ``run_sidecar_process`` therefore sends SIGTERM to the sidecar's own
group first, which emit_deck.mjs answers with ``process.exit(143)``, so node
leaves through that exit path. A node still running after a grace period could
not (its event loop blocked), so the helper kills the groups of node's detached
children, its browsers, itself, then SIGKILLs node's group as a backstop. The
admin routes that run probe_launch.mjs and the Playwright installer use the
same helper.

Concurrency. The export routes run in FastAPI's threadpool, so a worker could
start a sidecar per request; each node and Chromium tree takes about 790 MB.
``build_pptx_huashu`` runs at most ``TELLR_SIDECAR_CONCURRENCY`` of them at
once per worker process (default 1). An export past the cap waits for a slot,
logged once, and its timeout starts only once it has one. A waiting export
holds one of the threadpool's threads (40 per worker, shared with every sync
route and every authenticated request's identity lookup), so the waiting is
bounded: at most ``TELLR_SIDECAR_QUEUE`` exports (default 15) wait past the
cap, and an export past them is refused at once; one that waits
``TELLR_SIDECAR_WAIT_SECONDS`` (default 60) is refused then, and one that gets
its slot logs how long it waited. Either refusal is ``HuashuBusyError``, which
the export routes answer 429 with a message to retry. With the defaults, an
export is answered within the 300 s the Databricks Apps proxy allows a request
(measured): 60 s of waiting plus the 180 s sidecar timeout, and on the Google
Slides route its Drive upload, each request of which fails after
``DRIVE_HTTP_TIMEOUT_SECONDS`` (drive_uploader.py) of silence. Bounds that
would defeat this, a wait whose worst case reaches the proxy's 300 s or as
many places as the worker has threads, are warned about once, when this
module loads (``sidecar_bounds_warnings``), which the app's startup does in
every worker (``log_sidecar_bounds``).

Telemetry. Every export logs one line once it ends, however it ends (written,
partly written, failed, timed out, or refused as busy): ``[huashu] export
summary {json}`` (``_ExportSummary``), counts and timings only, never a slide's
content, a user or a path. Its ``peakRssMb`` is the most memory the sidecar's
process tree held, node and every Chromium it launched, read from the process
table about every ``MEMORY_SAMPLE_SECONDS`` while it runs
(``_TreeMemorySampler``); ``containerPeakMb`` is the most the whole container
held meanwhile, as its cgroup counts it (``CGROUP_ROOT``), null where there is
none. A reading that fails is null, and never fails or slows the export. The
container's memory limit is logged once, when a worker starts
(``log_sidecar_bounds``). Both lines have a logger of their own that writes
each record as one line to stderr (``telemetry_logger``), not through the
app's root handler: in a worker that is FastMCP's RichHandler, which wraps a
long line at 80 columns where stderr is no terminal, as on Databricks Apps, so
the JSON would reach the logs in pieces.

Renderer target. ``build_pptx_huashu(..., target=...)`` names the app the deck
is written for: ``"pptx"`` (the default) for PowerPoint and the .pptx download,
``"gslides"`` for the Google Slides conversion. The two place a few constructs
apart, and only those are written differently, all on lines that hold a
superscript or subscript run (measured in both apps;
``scripts/export_fidelity/CALIBRATION.md`` A2, A4 and A5):

* a script run's size. PowerPoint shrinks a script run and places its line by
  its other runs, so the run is written enlarged and PowerPoint draws it at the
  browser's size; Google Slides sizes the whole line by that enlarged size and
  draws it low, so for it the run is capped at its line's size (its glyph then
  drawn at 0.8 of the browser's, an accepted trade-off);
* for PowerPoint alone, a word joiner after a script run that ends its line,
  which PowerPoint would otherwise size the line by;
* the growth of a later line the browser set further down than its spacing
  (a raised script run's line box, a larger run's own line height, the
  block's strut), which both apps space by its paragraph alone: written as
  that line's space before, in both decks but for a line within its paragraph
  that holds a script run, which Google Slides grows by the run's written
  size instead (a later paragraph's first line holding one takes the space
  before).

So a deck with no script run is the same for both targets.
"""

from __future__ import annotations

import contextlib
import json
import logging
import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, NamedTuple

logger = logging.getLogger(__name__)

def _resolve_sidecar_dir() -> Path:
    # Dev / editable install: services/ lives at the repo root.
    dev = Path(__file__).resolve().parents[2] / "services" / "pptx-emit-huashu"
    if dev.exists():
        return dev
    # Wheel install: setup.py copies the sidecar under databricks_tellr_app/_assets/sidecars/.
    try:
        import databricks_tellr_app  # type: ignore
        wheel = Path(databricks_tellr_app.__file__).resolve().parent / "_assets" / "sidecars" / "pptx-emit-huashu"
        if wheel.exists():
            return wheel
    except Exception:
        pass
    return dev


SIDECAR_DIR = _resolve_sidecar_dir()
SIDECAR_SCRIPT = SIDECAR_DIR / "emit_deck.mjs"
SIDECAR_SYS_LIBS_DIR = SIDECAR_DIR / "sys-libs"
SIDECAR_TIMEOUT_SECONDS = 180  # huashu opens chromium per-slide; slower than pptx-emit

# How many sidecars one worker process runs at once. Each is a node and
# Chromium tree of about 790 MB (measured), and the export routes run in the
# threadpool, so without a cap a burst of exports would start them all.
SIDECAR_CONCURRENCY_ENV = "TELLR_SIDECAR_CONCURRENCY"
DEFAULT_SIDECAR_CONCURRENCY = 1


def sidecar_concurrency(environ: Mapping[str, str] = os.environ) -> int:
    """The cap ``TELLR_SIDECAR_CONCURRENCY`` sets: a whole number from 1, else the default, 1."""
    value = environ.get(SIDECAR_CONCURRENCY_ENV)
    if value is None:
        return DEFAULT_SIDECAR_CONCURRENCY
    try:
        cap = int(value)
    except ValueError:
        cap = 0
    if cap < 1:
        logger.warning(
            "%s=%r is not a whole number from 1; running %d sidecar(s) at once",
            SIDECAR_CONCURRENCY_ENV,
            value,
            DEFAULT_SIDECAR_CONCURRENCY,
        )
        return DEFAULT_SIDECAR_CONCURRENCY
    return cap


# How many exports past the cap one worker lets wait for a slot, and for how
# long. Each waiting export holds a thread of the worker's threadpool (40 by
# default, shared with every sync route and with every authenticated request's
# identity lookup), so both are bounded: with the defaults, exports hold at most
# 16 of the 40. The default wait, the sidecar's own timeout and a Drive upload,
# 60 + 180 + about 20 s, stay under the 300 s the Databricks Apps proxy allows a
# request, with some 40 s to spare.
SIDECAR_QUEUE_ENV = "TELLR_SIDECAR_QUEUE"
DEFAULT_SIDECAR_QUEUE = 15
SIDECAR_WAIT_ENV = "TELLR_SIDECAR_WAIT_SECONDS"
DEFAULT_SIDECAR_WAIT_SECONDS = 60

# What the bounds are checked against (sidecar_bounds_warnings). The Databricks
# Apps proxy ends a request at about 300 s (measured: a request answered at
# 185 s returned, one at 310 s got 502 at 300 s). The Google Slides route, the
# longest, answers after its slot wait, its sidecar run and its Drive upload,
# which DRIVE_UPLOAD_MARGIN_SECONDS stands for (4 to 20 s measured). A worker
# runs every sync route in Starlette's threadpool, THREADPOOL_THREADS threads.
APPS_PROXY_REQUEST_SECONDS = 300
DRIVE_UPLOAD_MARGIN_SECONDS = 20
THREADPOOL_THREADS = 40


def sidecar_queue(environ: Mapping[str, str] = os.environ) -> int:
    """How many exports ``TELLR_SIDECAR_QUEUE`` lets wait past the cap.

    A whole number from 0, else the default, 15.
    """
    value = environ.get(SIDECAR_QUEUE_ENV)
    if value is None:
        return DEFAULT_SIDECAR_QUEUE
    try:
        queue = int(value)
    except ValueError:
        queue = -1
    if queue < 0:
        logger.warning(
            "%s=%r is not a whole number from 0; letting %d export(s) wait for a sidecar",
            SIDECAR_QUEUE_ENV,
            value,
            DEFAULT_SIDECAR_QUEUE,
        )
        return DEFAULT_SIDECAR_QUEUE
    return queue


def sidecar_wait_seconds(environ: Mapping[str, str] = os.environ) -> float:
    """How long ``TELLR_SIDECAR_WAIT_SECONDS`` lets an export wait for a sidecar slot.

    A number of seconds above 0 and under ``threading.TIMEOUT_MAX``, the longest
    wait a lock can be told (a longer one raises OverflowError, not
    HuashuBusyError), else the default, 60.
    """
    value = environ.get(SIDECAR_WAIT_ENV)
    if value is None:
        return DEFAULT_SIDECAR_WAIT_SECONDS
    try:
        seconds = float(value)
    except ValueError:
        seconds = 0.0
    if not (math.isfinite(seconds) and 0 < seconds < threading.TIMEOUT_MAX):
        logger.warning(
            "%s=%r is not a number of seconds above 0 and under %g; "
            "an export waits up to %ds for a sidecar",
            SIDECAR_WAIT_ENV,
            value,
            threading.TIMEOUT_MAX,
            DEFAULT_SIDECAR_WAIT_SECONDS,
        )
        return DEFAULT_SIDECAR_WAIT_SECONDS
    return seconds


def sidecar_bounds_warnings(
    cap: int, queue: int, wait: float, timeout: float = SIDECAR_TIMEOUT_SECONDS
) -> list[str]:
    """What these sidecar bounds defeat in the app they run in, one message each: [] for nothing.

    ``cap`` sidecars run at once, ``queue`` exports more wait for one, each up
    to ``wait`` seconds, and a run is bounded by ``timeout``.
    """
    warnings = []
    worst = wait + timeout + DRIVE_UPLOAD_MARGIN_SECONDS
    if worst >= APPS_PROXY_REQUEST_SECONDS:
        warnings.append(
            f"{SIDECAR_WAIT_ENV}={wait:g}: a queued Google Slides export can take {wait:g} s "
            f"of waiting, the {timeout:g} s sidecar timeout and about "
            f"{DRIVE_UPLOAD_MARGIN_SECONDS} s of Drive upload, {worst:g} s, which reaches the "
            f"{APPS_PROXY_REQUEST_SECONDS} s the Databricks Apps proxy allows a request: the "
            "proxy would answer it 502 before the app does"
        )
    if cap + queue >= THREADPOOL_THREADS:
        warnings.append(
            f"{SIDECAR_CONCURRENCY_ENV}={cap} and {SIDECAR_QUEUE_ENV}={queue}: {cap + queue} "
            f"exports at once can hold all {THREADPOOL_THREADS} threads of the worker's "
            "threadpool, which every sync route and every authenticated request's identity "
            "lookup need too"
        )
    return warnings


_sidecar_cap = sidecar_concurrency()
_sidecar_queue = sidecar_queue()
_sidecar_slots = threading.BoundedSemaphore(_sidecar_cap)
# A place for each export this worker lets in: one per sidecar slot, and one per
# export queued for a slot. Taken without waiting, so with every place taken an
# export is refused at once (HuashuBusyError).
_sidecar_admissions = threading.BoundedSemaphore(_sidecar_cap + _sidecar_queue)
SIDECAR_WAIT_SECONDS = sidecar_wait_seconds()


def _warn_about_the_bounds() -> None:
    """Log each warning ``sidecar_bounds_warnings`` has for this worker's bounds."""
    for warning in sidecar_bounds_warnings(_sidecar_cap, _sidecar_queue, SIDECAR_WAIT_SECONDS):
        logger.warning("%s", warning)


_warn_about_the_bounds()


def log_sidecar_bounds() -> None:
    """Log this worker's sidecar bounds and the container's memory limit.

    The app's startup calls it, in every worker. Loading this module has warned
    already about any bound that defeats what it is for, so with the startup
    loading it a misconfiguration shows when a worker starts, not on its first
    export. The limit, ``[huashu] container memory limit <MB or none>``, is what
    the exports' ``containerPeakMb`` is read against (module docstring,
    Telemetry); one that cannot be read is logged as none, and never stops the
    startup.
    """
    logger.info(
        "[huashu] export sidecars per worker: %d at once, %d more waiting, each up to %gs",
        _sidecar_cap,
        _sidecar_queue,
        SIDECAR_WAIT_SECONDS,
    )
    try:
        limit = _container_memory_limit_bytes()
    except (OSError, ValueError) as error:
        logger.warning("could not read the container's cgroup limit: %s", error)
        limit = None
    telemetry_logger.info(
        "[huashu] container memory limit %s",
        "none" if limit is None else f"{limit / BYTES_PER_MB:.1f} MB",
    )

# SDR-4437 F-CR-35: the only environment keys the node/Chromium child gets.
# No DATABRICKS_*, no Fernet key, no Lakebase creds. HOME stays real (unlike
# the converter jail's scrubbed env): Playwright finds Chromium under
# ~/.cache/ms-playwright. Proxy and CA settings stay so the page can still
# load Chart.js from its CDN.
_SIDECAR_ENV_ALLOWLIST = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
    "LD_LIBRARY_PATH",
    "PLAYWRIGHT_BROWSERS_PATH",
    "XDG_CACHE_HOME",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "NODE_EXTRA_CA_CERTS",
)


def sidecar_subprocess_env() -> dict[str, str]:
    """Build the env dict for any node subprocess that ends up spawning
    Chromium: an allowlist of the app's environment (see
    ``_SIDECAR_ENV_ALLOWLIST``), never a copy of it. Prepends
    ``services/pptx-emit-huashu/sys-libs/`` onto
    ``LD_LIBRARY_PATH`` if the directory exists, so Chromium can find the
    bundled libnspr4/libnss3/etc. on Databricks Apps where the host glibc-
    next runtime libs aren't installed. Scoping it here (not as a global
    env in app.yaml) prevents the Python process from accidentally loading
    incompatible libs from the bundle.
    """
    env = {k: os.environ[k] for k in _SIDECAR_ENV_ALLOWLIST if k in os.environ}
    if SIDECAR_SYS_LIBS_DIR.exists():
        existing = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = (
            f"{SIDECAR_SYS_LIBS_DIR}:{existing}" if existing else str(SIDECAR_SYS_LIBS_DIR)
        )
    return env


class HuashuExportError(RuntimeError):
    """Raised when the huashu sidecar cannot run at all (setup, timeout)."""


class HuashuBusyError(RuntimeError):
    """Raised when this worker has no room for another export just now.

    Either every export place is taken (the sidecar slots and the queue for
    them) or the wait for a slot ran past ``SIDECAR_WAIT_SECONDS``. Not a
    ``HuashuExportError``: the export routes answer this 429 with a message to
    retry, but a ``HuashuExportError`` 500 or 503, and the frontend answers a
    503 by falling back to the records pipeline.
    """


@contextlib.contextmanager
def _export_place() -> Iterator[None]:
    """One of this worker's export places, held for the whole export.

    With every place taken, ``HuashuBusyError`` at once.
    """
    admissions = _sidecar_admissions
    if not admissions.acquire(blocking=False):
        raise HuashuBusyError(
            f"every export place of this worker is taken: its sidecar slots "
            f"({SIDECAR_CONCURRENCY_ENV}) and the queue for them ({SIDECAR_QUEUE_ENV})"
        )
    try:
        yield
    finally:
        admissions.release()


@contextlib.contextmanager
def _sidecar_slot(slides: int) -> Iterator[None]:
    """One of this worker's sidecar slots for a run, waited for up to ``SIDECAR_WAIT_SECONDS``.

    A wait past it raises ``HuashuBusyError``. An export that waits says so,
    and once it has the slot, how long it waited.
    """
    slots = _sidecar_slots
    if not slots.acquire(blocking=False):
        bound = SIDECAR_WAIT_SECONDS
        logger.info(
            "[huashu] export waits for a sidecar slot (%s per worker), up to %gs: %d slide(s)",
            SIDECAR_CONCURRENCY_ENV,
            bound,
            slides,
        )
        waiting_since = time.monotonic()
        if not slots.acquire(timeout=bound):
            raise HuashuBusyError(
                f"no sidecar slot came free within {bound:g}s ({SIDECAR_WAIT_ENV})"
            )
        logger.info(
            "[huashu] export took a sidecar slot after %.1fs: %d slide(s)",
            time.monotonic() - waiting_since,
            slides,
        )
    try:
        yield
    finally:
        slots.release()


# How long a sidecar told to stop (SIGTERM) has to end before it is killed
# (SIGKILL), and the bound on each wait for it after that: node ends through
# its exit path within it, where Playwright kills the browsers it launched.
SIDECAR_TERM_GRACE_SECONDS = 5


def _signal_process_group(process: subprocess.Popen, sig: signal.Signals) -> None:
    """Send ``sig`` to the process group ``process`` leads, else to ``process`` itself.

    The group's id is the process's own (``start_new_session``). A group that
    cannot be found (ProcessLookupError), or cannot be signalled
    (PermissionError: macOS answers EPERM for a group whose only member is the
    process, exited and not yet reaped), gets the signal on the process alone
    while it still runs; ``poll`` reaps it otherwise.
    """
    try:
        os.killpg(process.pid, sig)
    except (ProcessLookupError, PermissionError):
        if process.poll() is None:
            try:
                process.send_signal(sig)
            except (ProcessLookupError, PermissionError):
                pass  # it exited between the poll and the signal


class _ProcessRow(NamedTuple):
    """A running process: its id, its parent's, its group's, and its resident memory."""

    pid: int
    ppid: int
    pgid: int
    # Bytes resident (RSS); None where its /proc line stops short of the field.
    rss_bytes: int | None


# /proc/<pid>/stat, past "pid (comm) ": state is field 3, ppid 4, pgrp 5, rss 24
# (proc(5)), the number of pages resident.
_STAT_PPID, _STAT_PGRP, _STAT_RSS = 1, 2, 21
# ps reports RSS in KiB.
_PS_RSS_UNIT_BYTES = 1024


def _read_process_table(proc: Path = Path("/proc")) -> list[_ProcessRow]:
    """Every running process, in one pass: from /proc on Linux, else from ``ps``.

    Bounded: ``ps`` gets ``SIDECAR_TERM_GRACE_SECONDS``, and a process that
    exits while it is read, or whose line does not parse, is skipped. A table
    that cannot be read at all raises ``OSError`` or ``subprocess.SubprocessError``.
    """
    if (proc / "self" / "stat").exists():
        page_bytes = os.sysconf("SC_PAGE_SIZE")
        table = []
        for entry in os.listdir(proc):
            if not entry.isdigit():
                continue
            try:
                stat = (proc / entry / "stat").read_text()
                # "pid (comm) state ppid pgrp …": comm can hold spaces and parentheses.
                fields = stat[stat.rindex(")") + 2 :].split()
                pages = int(fields[_STAT_RSS]) if len(fields) > _STAT_RSS else None
                table.append(
                    _ProcessRow(
                        int(entry),
                        int(fields[_STAT_PPID]),
                        int(fields[_STAT_PGRP]),
                        None if pages is None else pages * page_bytes,
                    )
                )
            except (OSError, ValueError, IndexError):
                continue  # it exited, is not ours to read, or its line does not parse
        return table
    listing = subprocess.run(
        ["ps", "-A", "-o", "pid=", "-o", "ppid=", "-o", "pgid=", "-o", "rss="],
        capture_output=True,
        text=True,
        timeout=SIDECAR_TERM_GRACE_SECONDS,
        check=True,
    ).stdout
    table = []
    for line in listing.splitlines():
        try:
            pid, ppid, pgid, rss = (int(field) for field in line.split())
        except ValueError:
            continue  # not four numbers: not a process's line
        table.append(_ProcessRow(pid, ppid, pgid, rss * _PS_RSS_UNIT_BYTES))
    return table


def _process_table(proc: Path = Path("/proc")) -> list[tuple[int, int, int]]:
    """Every running process as ``(pid, ppid, pgid)`` (``_read_process_table``).

    An unreadable table is empty, logged.
    """
    try:
        rows = _read_process_table(proc)
    except (OSError, subprocess.SubprocessError) as error:
        logger.warning("could not list processes to sweep a blocked sidecar's browsers: %s", error)
        return []
    return [(row.pid, row.ppid, row.pgid) for row in rows]


def _kill_detached_children(process: subprocess.Popen) -> None:
    """SIGKILL the group of each of the sidecar's children that leads a group of its own.

    The browsers Playwright launches are such children (``detached``). Only
    called while the sidecar still runs: a living node has not reaped its
    children, so none of their ids can have been reused by another process.
    """
    for pid, ppid, pgid in _process_table():
        if ppid == process.pid and pgid == pid and pid != process.pid:
            try:
                os.killpg(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass  # gone already, or a zombie its node has yet to reap


def _end_process_group(process: subprocess.Popen) -> None:
    """Stop the sidecar's process group, never waiting on it for long.

    SIGTERM first: the sidecar's node scripts answer it with process.exit(143)
    (emit_deck.mjs, probe_launch.mjs), and Playwright's exit handler then
    SIGKILLs the group of every browser it launched. Playwright launches each
    browser ``detached``, the leader of a group of its own, so no signal to the
    sidecar's group reaches a browser: only node's exit path does. A node still
    running after ``SIDECAR_TERM_GRACE_SECONDS`` could not take that path (its
    event loop blocked, so no handler of its ran), so the groups of its detached
    children, its browsers, are killed here. Then SIGKILL to whatever of the
    sidecar's own group remains: node, or a child it started in that group.
    """
    _signal_process_group(process, signal.SIGTERM)
    try:
        process.wait(timeout=SIDECAR_TERM_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    if process.poll() is None:
        _kill_detached_children(process)
    _signal_process_group(process, signal.SIGKILL)
    try:
        process.wait(timeout=SIDECAR_TERM_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        logger.warning("sidecar pid %s did not exit after SIGKILL", process.pid)


def run_sidecar_process(
    command: list[str],
    *,
    input: bytes,
    timeout: float,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    on_spawn: Callable[[subprocess.Popen], None] | None = None,
) -> subprocess.CompletedProcess:
    """Run a sidecar node script on ``input``, its output captured, bounded by ``timeout``.

    ``env`` defaults to ``sidecar_subprocess_env()``, never the app's own
    environment. The script starts a new session, so it leads a process group
    of its own. ``on_spawn``, when given, is called with the process once it
    has started, before it is given ``input`` (the export's memory sampler,
    ``_TreeMemorySampler.watch``); what it raises ends the run as an interruption
    does. A run past ``timeout``, or interrupted, is ended with
    ``_end_process_group`` (SIGTERM, then SIGKILL after the grace period) and
    ``subprocess.TimeoutExpired`` is raised with what it printed. After any
    exit, a failing one included, the group is swept with SIGKILL, so no child
    it started in its own group outlives it. No wait is unbounded: the run
    returns within ``timeout`` plus four grace periods (the waits, and the
    process listing a blocked sidecar's sweep reads).
    """
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=sidecar_subprocess_env() if env is None else env,
        start_new_session=True,
    )
    try:
        try:
            if on_spawn is not None:
                on_spawn(process)
            stdout, stderr = process.communicate(input, timeout=timeout)
        except subprocess.TimeoutExpired as timed_out:
            _end_process_group(process)
            stdout, stderr = _remaining_output(process)
            raise subprocess.TimeoutExpired(
                command, timeout, output=stdout, stderr=stderr
            ) from timed_out
        except BaseException:
            _end_process_group(process)
            raise
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    finally:
        try:
            _signal_process_group(process, signal.SIGKILL)
        finally:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream:
                    stream.close()


def _remaining_output(process: subprocess.Popen) -> tuple[bytes, bytes]:
    """What an ended sidecar printed, read for at most ``SIDECAR_TERM_GRACE_SECONDS``.

    A process outside its group (a detached browser) can still hold its
    pipes open, so the read is bounded; past it, the output is given up.
    """
    try:
        return process.communicate(timeout=SIDECAR_TERM_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        return b"", b""


# The export summary's memory reading (_TreeMemorySampler): how often the
# sidecar's process tree is read while it runs, and the unit of the reading (MiB).
MEMORY_SAMPLE_SECONDS = 0.25
BYTES_PER_MB = 1024 * 1024


def _tree_resident_bytes(root: int, table: list[_ProcessRow]) -> int | None:
    """The resident bytes of process ``root`` and of every descendant of it; None once it is gone.

    Descendants by the PPID chain, whatever their group: Playwright launches
    each browser ``detached``, the leader of a group of its own (found as
    ``_kill_detached_children`` finds it), and a browser's own processes are
    its children. A process of the tree whose resident size the table does not
    give raises ``ValueError``: a sum without it would read low.
    """
    rows: dict[int, _ProcessRow] = {}
    children: dict[int, list[_ProcessRow]] = {}
    for row in table:
        rows[row.pid] = row
        children.setdefault(row.ppid, []).append(row)
    if root not in rows:
        return None
    total = 0
    counted: set[int] = set()
    pending = [rows[root]]
    while pending:
        row = pending.pop()
        if row.pid in counted:
            continue  # each process once, whatever chain the table holds
        counted.add(row.pid)
        if row.rss_bytes is None:
            raise ValueError(f"the process table gives no resident size for process {row.pid}")
        total += row.rss_bytes
        pending.extend(children.get(row.pid, ()))
    return total


# The container's own memory, as its cgroup charges it against its limit:
# cgroup v2's memory.current and memory.max, else cgroup v1's usage and limit.
# A container sees its own cgroup at this root; a machine with neither file
# (macOS, a host's root cgroup) has no reading. Tests point it at a fake one.
CGROUP_ROOT = Path("/sys/fs/cgroup")
_CGROUP_MEMORY_FILES = (
    ("memory.current", "memory.max"),
    ("memory/memory.usage_in_bytes", "memory/memory.limit_in_bytes"),
)
# A cgroup v1 limit this large is none: v1 says "no limit" with the largest
# page-aligned 63-bit number, v2 with "max".
_CGROUP_UNLIMITED_BYTES = 1 << 62


def _cgroup_memory_files() -> tuple[Path, Path] | None:
    """The container's cgroup memory usage and limit files, v2 before v1; None for neither."""
    for usage, limit in _CGROUP_MEMORY_FILES:
        if (CGROUP_ROOT / usage).is_file():
            return CGROUP_ROOT / usage, CGROUP_ROOT / limit
    return None


def _container_memory_limit_bytes() -> int | None:
    """The container's memory limit, or None: no limit, or no cgroup memory files.

    A limit file that cannot be read, or does not hold a number, raises
    ``OSError`` or ``ValueError``.
    """
    files = _cgroup_memory_files()
    if files is None:
        return None
    value = files[1].read_text(encoding="ascii").strip()
    if value == "max":
        return None
    limit = int(value)
    return None if limit >= _CGROUP_UNLIMITED_BYTES else limit


class _MemoryPeaks(NamedTuple):
    """What a ``_TreeMemorySampler`` read, in MB (MiB): None for a reading it does not have."""

    # The sidecar's process tree: node and every Chromium it launched, RSS summed.
    tree_mb: float | None
    # The whole container, as its cgroup counts it.
    container_mb: float | None


def _megabytes(held: int | None) -> float | None:
    return None if held is None else round(held / BYTES_PER_MB, 1)


class _TreeMemorySampler:
    """The most memory a sidecar's process tree held, and the container with it.

    ``watch`` (``run_sidecar_process``'s ``on_spawn``) starts a daemon thread
    that reads, every ``MEMORY_SAMPLE_SECONDS`` and in one pass each, the
    process table (``_read_process_table``) and, where there is one, the
    container's cgroup memory usage (``_cgroup_memory_files``). It keeps the
    largest resident size of the tree (``_tree_resident_bytes``) and the largest
    usage of the container. It stops once the sidecar has ended, or at
    ``stop``. It is telemetry: a thread that cannot start, or a pass that fails
    before ``stop``, leaves no readings (None, not the part read before it), and
    nothing here raises into the export or waits on the thread. A pass that
    fails after ``stop`` changes nothing: the export has logged its readings.
    """

    def __init__(self) -> None:
        # Guards what the thread records against ``stop`` reading it.
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._peak_bytes: int | None = None
        self._container_peak_bytes: int | None = None
        self._failed = False

    def watch(self, process: subprocess.Popen) -> None:
        """Start reading ``process``'s tree, in a thread of its own."""
        try:
            threading.Thread(
                target=self._sample, args=(process,), name="huashu-memory", daemon=True
            ).start()
        except Exception as error:  # noqa: BLE001 (telemetry never fails an export)
            self._fail(error)

    def _sample(self, process: subprocess.Popen) -> None:
        try:
            cgroup = _cgroup_memory_files()
            while not self._stopped.is_set() and process.returncode is None:
                held = _tree_resident_bytes(process.pid, _read_process_table())
                if held is None:
                    return  # the sidecar has ended: no process has its id
                container = None
                if cgroup is not None:
                    container = int(cgroup[0].read_text(encoding="ascii"))
                with self._lock:
                    if self._peak_bytes is None or held > self._peak_bytes:
                        self._peak_bytes = held
                    if container is not None and (
                        self._container_peak_bytes is None
                        or container > self._container_peak_bytes
                    ):
                        self._container_peak_bytes = container
                self._stopped.wait(MEMORY_SAMPLE_SECONDS)
        except Exception as error:  # noqa: BLE001 (telemetry never fails an export)
            self._fail(error)

    def _fail(self, error: Exception) -> None:
        with self._lock:
            if self._stopped.is_set():
                return  # the export has its readings already, and has logged them
            self._failed = True
        logger.warning("[huashu] export memory not read, its summary says null: %s", error)

    def stop(self) -> _MemoryPeaks:
        """Stop reading, without waiting: the most the tree and the container held, in MB.

        Each is None when it was not read, or when a pass failed.
        """
        with self._lock:
            self._stopped.set()
            if self._failed:
                return _MemoryPeaks(tree_mb=None, container_mb=None)
            return _MemoryPeaks(
                tree_mb=_megabytes(self._peak_bytes),
                container_mb=_megabytes(self._container_peak_bytes),
            )


# The line each export logs once it ends (_ExportSummary), its prefix fixed: the
# owner greps the app's logs for it.
EXPORT_SUMMARY_PREFIX = "[huashu] export summary "


class _StderrLineHandler(logging.StreamHandler):
    """Each record as one line on ``sys.stderr``, the stream as it is when the record is logged.

    Looked up per record, as logging's own last-resort handler does, so a
    redirected stderr (a test's capture, the fidelity harness's tee) gets it.
    """

    def __init__(self) -> None:
        logging.Handler.__init__(self)

    @property
    def stream(self):  # type: ignore[override]
        return sys.stderr


# The telemetry's logger, for each export's summary line and the container's
# memory limit at startup: INFO, each record one line on stderr, and not
# passed on to the app's root handler, which in a worker wraps a long line
# (module docstring, Telemetry).
telemetry_logger = logging.getLogger(f"{__name__}.telemetry")
telemetry_logger.setLevel(logging.INFO)
telemetry_logger.propagate = False
if not telemetry_logger.handlers:
    _telemetry_handler = _StderrLineHandler()
    _telemetry_handler.setFormatter(logging.Formatter("%(message)s"))
    telemetry_logger.addHandler(_telemetry_handler)


@dataclass
class _ExportSummary:
    """One export's summary line (``EXPORT_SUMMARY_PREFIX``): counts and timings only.

    ``outcome`` is ``failed`` until the export says otherwise: ``ok`` or
    ``partial`` for a deck written without or with failed slides
    (``exported``), and ``timeout`` or ``busy`` where those are raised.
    """

    target: str
    slides: int
    outcome: str = "failed"
    slides_exported: int = 0
    failures: int = 0
    # Waiting for a sidecar slot; no run until there is one.
    wait_seconds: float = 0.0
    run_seconds: float | None = None
    # The sidecar's process tree, and the whole container (_TreeMemorySampler).
    peak_rss_mb: float | None = None
    container_peak_mb: float | None = None
    pptx_bytes: int = 0

    def exported(self, pptx_bytes: bytes, failures: list[dict[str, Any]]) -> None:
        """What the export returned: a deck of the slides that passed, or none at all."""
        self.pptx_bytes = len(pptx_bytes)
        self.failures = len(failures)
        if pptx_bytes:
            self.slides_exported = max(self.slides - self.failures, 0)
            self.outcome = "partial" if failures else "ok"

    def line(self) -> str:
        """The line: its JSON's keys in a fixed order, read by the owner's tools."""
        if self.run_seconds is None or not self.slides:
            seconds_per_slide = None
        else:
            seconds_per_slide = round(self.run_seconds / self.slides, 3)
        fields = {
            "target": self.target,
            "slides": self.slides,
            "slidesExported": self.slides_exported,
            "failures": self.failures,
            "outcome": self.outcome,
            "waitSeconds": round(self.wait_seconds, 3),
            "runSeconds": None if self.run_seconds is None else round(self.run_seconds, 3),
            "secondsPerSlide": seconds_per_slide,
            "peakRssMb": self.peak_rss_mb,
            "containerPeakMb": self.container_peak_mb,
            "pptxBytes": self.pptx_bytes,
            "sidecarConcurrency": _sidecar_cap,
            "queueBound": _sidecar_queue,
        }
        return EXPORT_SUMMARY_PREFIX + json.dumps(fields, separators=(",", ":"))

    def log(self) -> None:
        """Log the line. A failure to is logged, and never raised into the export."""
        try:
            telemetry_logger.info("%s", self.line())
        except Exception:  # noqa: BLE001 (telemetry never fails an export)
            logger.exception("could not log the export summary")


def _local_dev_gate() -> bool:
    """Whether this process is one the export may run in, before its prerequisites are checked.

    In priority order:
      - ``HUASHU_PIPELINE_ENABLED=1``: yes. The app template sets it on
        Databricks Apps, whose boot runs the sidecar's ``setup.sh`` to
        extract its ``node_modules`` and install Chromium.
      - ``DATABRICKS_APP_NAME`` set without it: no, a deployed app that has
        not opted in, so it fails fast instead of launching a browser it
        never installed.
      - Otherwise yes exactly when ``ENVIRONMENT=development``.
    """
    if os.environ.get("HUASHU_PIPELINE_ENABLED") == "1":
        return True
    if os.environ.get("DATABRICKS_APP_NAME"):
        return False
    return os.environ.get("ENVIRONMENT") == "development"


def _has_chromium() -> bool:
    """Cheap heuristic for whether `npx playwright install chromium` ran.

    The browser binary lives under ``~/Library/Caches/ms-playwright/``
    (macOS) or ``~/.cache/ms-playwright/`` (Linux). We don't enumerate the
    chrome-mac.app subtree; the cache directory's existence is enough as
    a "did the user run the install step" proof.
    """
    home = Path.home()
    for candidate in (
        home / "Library" / "Caches" / "ms-playwright",
        home / ".cache" / "ms-playwright",
    ):
        if candidate.exists() and any(candidate.iterdir()):
            return True
    return False


def is_available() -> bool:
    """Whether the export can run here.

    It needs ``HUASHU_PIPELINE_ENABLED=1`` (a deployed app, its sidecar set up
    by ``setup.sh``) or ``ENVIRONMENT=development`` (``_local_dev_gate``), and
    then node on PATH, the sidecar's ``emit_deck.mjs``, its ``playwright`` and
    ``pptxgenjs`` modules, and a Playwright Chromium. False until all are there.
    """
    if not _local_dev_gate():
        return False
    if shutil.which("node") is None:
        return False
    if not SIDECAR_SCRIPT.exists():
        return False
    if not (SIDECAR_DIR / "node_modules" / "playwright").exists():
        return False
    if not (SIDECAR_DIR / "node_modules" / "pptxgenjs").exists():
        return False
    if not _has_chromium():
        return False
    return True


RenderTarget = Literal["pptx", "gslides"]
RENDER_TARGETS: tuple[RenderTarget, ...] = ("pptx", "gslides")


def _run_measured(
    cmd: list[str], payload_bytes: bytes, summary: _ExportSummary
) -> subprocess.CompletedProcess:
    """The sidecar's run, its wall time and its memory peaks recorded on ``summary``."""
    sampler = _TreeMemorySampler()
    started = time.monotonic()
    try:
        return run_sidecar_process(
            cmd, input=payload_bytes, timeout=SIDECAR_TIMEOUT_SECONDS, on_spawn=sampler.watch
        )
    except subprocess.TimeoutExpired as e:
        summary.outcome = "timeout"
        raise HuashuExportError(
            f"huashu sidecar timed out after {SIDECAR_TIMEOUT_SECONDS}s"
        ) from e
    finally:
        summary.run_seconds = time.monotonic() - started
        summary.peak_rss_mb, summary.container_peak_mb = sampler.stop()


def _export_deck(
    title: str,
    slides_html: list[dict[str, Any]],
    *,
    bypass_validation: bool,
    target: RenderTarget,
    summary: _ExportSummary,
) -> tuple[bytes, list[dict[str, Any]]]:
    """``build_pptx_huashu``'s export, its wait for a slot and its run recorded on ``summary``."""
    payload_bytes = json.dumps({
        "title": title,
        "slides": slides_html,
        "bypassValidation": bypass_validation,
        # The app the deck is written for (module docstring, Renderer target).
        "target": target,
    }).encode("utf-8")

    # A place among this worker's exports for the whole export, refused at once
    # when every one is taken, and a sidecar slot for the run, waited for before
    # it so the wait does not count against its timeout (module docstring,
    # Concurrency). Past either bound: HuashuBusyError.
    with _export_place(), tempfile.TemporaryDirectory() as td:
        out_path = Path(td) / "out.pptx"
        cmd = ["node", str(SIDECAR_SCRIPT), str(out_path)]
        asked_at = time.monotonic()
        try:
            with _sidecar_slot(len(slides_html)):
                summary.wait_seconds = time.monotonic() - asked_at
                logger.info(
                    "spawn huashu sidecar: %s (slides=%d, payload=%d bytes)",
                    " ".join(cmd), len(slides_html), len(payload_bytes),
                )
                result = _run_measured(cmd, payload_bytes, summary)
        except HuashuBusyError:
            # Refused once its wait for a slot ran out: the wait was all of it.
            summary.wait_seconds = time.monotonic() - asked_at
            raise

        stderr = result.stderr.decode("utf-8", errors="replace")
        # Echo informational stderr lines into our log so the user sees
        # per-slide progress. The result line is parsed separately.
        for line in stderr.splitlines():
            if line.strip() and not line.startswith("__HUASHU_RESULT__"):
                print(f"[huashu-emit] {line}", file=sys.stderr, flush=True)

        # Parse the sentinel line for structured failure data. emit_deck.mjs
        # prints it last, once every slide is done, so the last one is its own:
        # anything a slide's page made the sidecar print comes before it.
        failures: list[dict[str, Any]] = []
        for line in reversed(stderr.splitlines()):
            if line.startswith("__HUASHU_RESULT__"):
                try:
                    parsed = json.loads(line.removeprefix("__HUASHU_RESULT__").strip())
                    failures = parsed.get("failed", []) or []
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Could not parse huashu result line: %s", exc)
                break

        if not out_path.exists():
            # All-fail or hard-fail; still return failures so caller can show them.
            if failures:
                return b"", failures
            raise HuashuExportError(
                f"huashu sidecar exited {result.returncode} with no pptx and no result line. "
                f"stderr tail: {stderr[-500:]}"
            )

        return out_path.read_bytes(), failures


def build_pptx_huashu(
    title: str,
    slides_html: list[dict[str, Any]],
    *,
    bypass_validation: bool = False,
    target: RenderTarget = "pptx",
) -> tuple[bytes, list[dict[str, Any]]]:
    """Run huashu's pipeline over each slide's HTML, return (pptx_bytes, failures).

    ``slides_html`` is a list of ``{ "html": "<full doc string>", "notes": "..." }``.
    The HTML string must be a complete standalone document with body sized
    to 1280×720 px (= 13.333"×7.5"); the caller assembles this — see
    ``src/api/routes/export.py::build_slide_html``.

    ``bypass_validation``: when True, huashu's design-rule validation
    (overflow > 100px, text-near-bottom-edge, layout dimension mismatch,
    other authoring quality checks) becomes a per-slide console warning
    instead of a throw. Slides that violate the rules still end up in the
    output PPTX. Used by the Google Slides Drive route to guarantee every
    slide ships, with the trade-off that some slides may render imperfectly.

    ``target``: the app the deck is written for, ``"pptx"`` (PowerPoint, the
    default) or ``"gslides"`` (the Google Slides conversion); see the module
    docstring. Any other value raises ``ValueError``.

    Each export logs one ``[huashu] export summary {json}`` line once it ends,
    however it ends (module docstring, Telemetry). A call stopped before the
    export starts, by an unknown ``target`` or with the pipeline unavailable
    here (which the export routes answer 503), logs none.

    Returns a 2-tuple:
      * pptx_bytes — the .pptx as bytes, even if some slides failed
        (empty if ALL slides failed; the caller should handle that).
      * failures  — list of ``{ slide_index, error }`` with one entry per
        slide huashu rejected. Empty list = clean run.
    """
    if target not in RENDER_TARGETS:
        raise ValueError(f"unknown render target {target!r}: expected one of {RENDER_TARGETS}")
    if not is_available():
        raise HuashuExportError(
            "huashu pipeline not available: it needs HUASHU_PIPELINE_ENABLED=1 "
            "(Databricks Apps, whose boot runs the sidecar's setup.sh) or "
            "ENVIRONMENT=development, node on PATH, the sidecar's node_modules "
            "(playwright, pptxgenjs) and a Playwright Chromium "
            "(`npx playwright install chromium` in services/pptx-emit-huashu/)"
        )

    # The export's one summary line, logged once it ends, however it ends
    # (module docstring, Telemetry).
    summary = _ExportSummary(target=target, slides=len(slides_html))
    try:
        pptx_bytes, failures = _export_deck(
            title,
            slides_html,
            bypass_validation=bypass_validation,
            target=target,
            summary=summary,
        )
    except HuashuBusyError:
        summary.outcome = "busy"
        raise
    else:
        summary.exported(pptx_bytes, failures)
        return pptx_bytes, failures
    finally:
        summary.log()
