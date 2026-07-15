# src/services/converter_jail/jail.py
"""Host-side launcher for the converter subprocess jail (SDR-4437 HIGH-5).

Launches exactly one locked-down child per deck: scrubbed env, POSIX rlimits,
wall-clock timeout, and — on Linux where permitted — a network namespace with
no egress. The security boundary is this process isolation; the AST allowlist
and any judge pass are hardening layers on top.
"""

import logging
import os
import resource
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from src.services.converter_jail import protocol

logger = logging.getLogger(__name__)

# Parent directory of the `src` package. `python -I` ignores PYTHONPATH, so we
# pass this to the runner as argv[1] (part of the runner CLI contract).
# parents[3] of .../src/services/converter_jail/jail.py == dir containing `src`.
_SRC_PARENT = str(Path(__file__).resolve().parents[3])

# Environment keys copied through to the child (everything else is dropped).
_ENV_WHITELIST = ("PATH", "LANG")

_netns_cache: Optional[bool] = None


class JailError(Exception):
    """Raised when the jail cannot be launched at all (not for child errors)."""


@dataclass
class JailResult:
    returncode: int
    timed_out: bool
    stderr_tail: str = ""


@dataclass
class ResourceLimits:
    cpu_s: int = 60
    address_space_bytes: int = 2 * 1024 * 1024 * 1024  # 2 GiB
    file_size_bytes: int = 256 * 1024 * 1024           # 256 MiB
    nproc: Optional[int] = None  # None -> leave current soft limit


def build_scrubbed_env() -> dict:
    """Build the child environment: only PATH/LANG survive; HOME/TMPDIR point
    at a fresh temp dir. No DATABRICKS_*, no Fernet key, no Lakebase creds."""
    env: dict = {}
    for key in _ENV_WHITELIST:
        if key in os.environ:
            env[key] = os.environ[key]
    env.setdefault("LANG", "C.UTF-8")
    home = tempfile.mkdtemp(prefix="jail_home_")
    env["HOME"] = home
    env["TMPDIR"] = home
    env["PYTHONHASHSEED"] = "0"
    return env


def _rlimit_preexec(limits: ResourceLimits) -> Callable[[], None]:
    """Return a preexec_fn that applies rlimits best-effort (POSIX)."""
    def _apply() -> None:
        def _set(what, value):
            try:
                resource.setrlimit(what, (value, value))
            except (ValueError, OSError):
                pass  # platform rejects this limit; others still apply
        _set(resource.RLIMIT_CPU, limits.cpu_s)
        _set(resource.RLIMIT_AS, limits.address_space_bytes)
        _set(resource.RLIMIT_FSIZE, limits.file_size_bytes)
        if limits.nproc is not None and hasattr(resource, "RLIMIT_NPROC"):
            _set(resource.RLIMIT_NPROC, limits.nproc)
        # New session so a SIGKILL to the child's process group reaps any
        # grandchildren too.
        try:
            os.setsid()
        except OSError:
            pass
    return _apply


def netns_available() -> bool:
    """True iff `unshare --net` works on this host. Cached. Never raises."""
    global _netns_cache
    if _netns_cache is not None:
        return _netns_cache
    result = False
    unshare = shutil.which("unshare")
    if unshare:
        try:
            proc = subprocess.run(
                [unshare, "--net", "true"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=3,
            )
            result = proc.returncode == 0
        except Exception:
            result = False
    _netns_cache = result
    if not result:
        logger.warning(
            "Network namespace unavailable — converter jail runs without netns. "
            "Egress is possible but the scrubbed env carries no credentials "
            "(documented residual risk, SDR-4437 HIGH-5)."
        )
    return result


def _spawn(
    runner_file: str,
    argv: List[str],
    timeout_s: float,
    progress_cb: Optional[Callable[[int, int, str], None]],
    limits: Optional[ResourceLimits] = None,
) -> JailResult:
    """Launch one jailed child. Streams stdout, relaying progress lines to
    progress_cb; captures a tail of stderr for diagnostics.

    Timeout design (load-bearing): both stdout and stderr are drained on
    daemon reader threads while THIS thread enforces proc.wait(timeout=...).
    The timeout must never depend on the child writing to or closing its
    pipes — a silent, never-exiting child (no output, infinite loop) is
    exactly the runaway/DoS case this control exists for; a foreground
    `for line in proc.stdout` would block forever before any wait() ran.
    On expiry the child's whole process group is SIGKILLed.
    Consequence: progress_cb is invoked on the stdout reader thread, not the
    caller's thread — callbacks must be thread-safe.
    """
    limits = limits or ResourceLimits()
    cmd: List[str] = []
    if netns_available():
        cmd += [shutil.which("unshare"), "--net"]
    cmd += [sys.executable, "-I", runner_file, _SRC_PARENT, *argv]

    env = build_scrubbed_env()
    stderr_lines: List[str] = []

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=env["HOME"],
            preexec_fn=_rlimit_preexec(limits),
            text=True,
        )
    except Exception as exc:  # launch failure, not a child error
        raise JailError(f"Failed to launch jail: {exc}") from exc

    def _drain_stderr():
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_lines.append(line)
            if len(stderr_lines) > 200:
                del stderr_lines[0]

    err_thread = threading.Thread(target=_drain_stderr, daemon=True)
    err_thread.start()

    assert proc.stdout is not None

    def _drain_stdout():
        for line in proc.stdout:
            decoded = protocol.decode_progress(line)
            if decoded and progress_cb:
                try:
                    progress_cb(*decoded)
                except Exception:
                    logger.debug("progress_cb raised", exc_info=True)

    out_thread = threading.Thread(target=_drain_stdout, daemon=True)
    out_thread.start()

    timed_out = False
    try:
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(os.getpgid(proc.pid), 9)
        except Exception:
            proc.kill()
        proc.wait()
    finally:
        out_thread.join(timeout=1.0)
        err_thread.join(timeout=1.0)

    return JailResult(
        returncode=proc.returncode if proc.returncode is not None else -1,
        timed_out=timed_out,
        stderr_tail="".join(stderr_lines[-40:]),
    )


def run_pptx_jail(
    job_dir: str,
    output_path: str,
    *,
    timeout_s: float = 120.0,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> JailResult:
    """Run the PPTX runner in the jail. job_dir holds the manifest + per-slide
    inputs; the finished .pptx is written to output_path."""
    runner = str(Path(__file__).resolve().parent / "pptx_runner.py")
    return _spawn(runner, [job_dir, output_path], timeout_s, progress_cb)


def run_gslides_jail(
    job_dir: str,
    requests_out_path: str,
    *,
    timeout_s: float = 120.0,
) -> JailResult:
    """Run the Google Slides runner in the jail. Emits batchUpdate-request
    JSON to requests_out_path. No network, no progress channel (host executes
    the network calls and reports progress itself)."""
    runner = str(Path(__file__).resolve().parent / "gslides_runner.py")
    return _spawn(runner, [job_dir, requests_out_path], timeout_s, None)
