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

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Literal

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


def _process_table(proc: Path = Path("/proc")) -> list[tuple[int, int, int]]:
    """Every running process as ``(pid, ppid, pgid)``: from /proc on Linux, else from ``ps``.

    Bounded: ``ps`` gets ``SIDECAR_TERM_GRACE_SECONDS``, and a process that
    exits while it is read is skipped. An unreadable table is empty, logged.
    """
    if (proc / "self" / "stat").exists():
        table = []
        for entry in os.listdir(proc):
            if not entry.isdigit():
                continue
            try:
                stat = (proc / entry / "stat").read_text()
            except OSError:
                continue  # it exited, or is not ours to read
            # "pid (comm) state ppid pgrp …": comm can hold spaces and parentheses.
            fields = stat[stat.rindex(")") + 2 :].split()
            table.append((int(entry), int(fields[1]), int(fields[2])))
        return table
    try:
        listing = subprocess.run(
            ["ps", "-A", "-o", "pid=", "-o", "ppid=", "-o", "pgid="],
            capture_output=True,
            text=True,
            timeout=SIDECAR_TERM_GRACE_SECONDS,
            check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError) as error:
        logger.warning("could not list processes to sweep a blocked sidecar's browsers: %s", error)
        return []
    table = []
    for line in listing.splitlines():
        fields = line.split()
        if len(fields) == 3:
            table.append((int(fields[0]), int(fields[1]), int(fields[2])))
    return table


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
) -> subprocess.CompletedProcess:
    """Run a sidecar node script on ``input``, its output captured, bounded by ``timeout``.

    ``env`` defaults to ``sidecar_subprocess_env()``, never the app's own
    environment. The script starts a new session, so it leads a process group
    of its own. A run past ``timeout``, or interrupted, is ended with
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


def _local_dev_gate() -> bool:
    """True iff this process is running on a developer machine, not Apps.

    Hard rules (in priority order):
      - HUASHU_PIPELINE_ENABLED=1 explicit opt-in. This is what
        app.yaml.darwish sets so the route works on Databricks Apps
        (Chromium installed during boot via `npx playwright install
        chromium`). Wins over the Apps-name check.
      - DATABRICKS_APP_NAME being set without the opt-in means a
        deployed Apps container that hasn't installed Chromium —
        keep disabled to fail fast.
      - Otherwise allow if ENVIRONMENT=development.
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
    """Whether the huashu pipeline is ready to use.

    Returns False on Databricks Apps, when node isn't on PATH, when the
    sidecar files aren't present, or when Chromium hasn't been installed.
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

    payload_bytes = json.dumps({
        "title": title,
        "slides": slides_html,
        "bypassValidation": bypass_validation,
        # The app the deck is written for (module docstring, Renderer target).
        "target": target,
    }).encode("utf-8")

    with tempfile.TemporaryDirectory() as td:
        out_path = Path(td) / "out.pptx"
        cmd = ["node", str(SIDECAR_SCRIPT), str(out_path)]
        logger.info(
            "spawn huashu sidecar: %s (slides=%d, payload=%d bytes)",
            " ".join(cmd), len(slides_html), len(payload_bytes),
        )
        try:
            result = run_sidecar_process(cmd, input=payload_bytes, timeout=SIDECAR_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as e:
            raise HuashuExportError(
                f"huashu sidecar timed out after {SIDECAR_TIMEOUT_SECONDS}s"
            ) from e

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
