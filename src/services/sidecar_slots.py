"""The export sidecars' run slots, shared by every worker process of the container.

The app runs several uvicorn worker processes in one container (``UVICORN_WORKERS``,
``packages/databricks-tellr-app/databricks_tellr_app/run.py``), and the kernel does not
balance requests across them: measured on a deployed app, three of four simultaneous exports
landed on one worker while the others idled. What a sidecar slot protects, memory (a node and
Chromium tree takes about 790 MB), is the container's, so the slots are the container's too.

``SidecarSlots`` is a counting semaphore of the container, with ``threading.BoundedSemaphore``'s
interface. Each of its ``count`` slots is a file of one directory (``slot-0`` …), held with a
non-blocking ``fcntl.flock`` on a descriptor opened for it. A lock belongs to the open file,
not to the process, so two threads of one worker contend for a slot as two workers do; and
the kernel drops it when its descriptor closes, so a worker that dies holding a slot (killed,
or out of memory) frees it. A waiting acquire tries the slots again every
``SLOT_POLL_SECONDS`` until its timeout, so the slots go to waiters in no particular order.

Every process that names the same directory shares its slots. ``run.py`` makes one for the
workers it starts and names it in their environment (``SLOTS_DIR_ENV``), since uvicorn starts
each worker as a fresh interpreter that inherits it, and removes it once they have stopped. A
process the environment names none for (local development's single ``uvicorn`` process, a
test) runs alone, so the export wrapper counts its slots with a semaphore of its own, and no
file holds them (``pptx_from_html_huashu._container_slots``).
"""

from __future__ import annotations

import fcntl
import os
import threading
import time
from collections.abc import Mapping
from pathlib import Path

# The variable run.py names the workers' shared slot directory in (run.py SIDECAR_SLOTS_DIR_ENV).
SLOTS_DIR_ENV = "TELLR_SIDECAR_SLOTS_DIR"
# How often a waiting acquire tries the slots again.
SLOT_POLL_SECONDS = 0.05
# A slot directory made again here, and the slot files, are their owner's alone.
_DIRECTORY_MODE = 0o700
_SLOT_FILE_MODE = 0o600


def slots_directory(environ: Mapping[str, str] = os.environ) -> Path | None:
    """The slot directory the environment names (``SLOTS_DIR_ENV``), or None for none."""
    value = environ.get(SLOTS_DIR_ENV)
    return Path(value) if value else None


class SidecarSlots:
    """``count`` slots shared by every process that names ``directory``.

    ``acquire`` and ``release`` answer as ``threading.BoundedSemaphore``'s do. The slots are
    alike, so a release gives back one this process holds, whichever thread took it.
    """

    def __init__(self, count: int, directory: str | os.PathLike[str]) -> None:
        if count < 1:
            raise ValueError(f"a sidecar slot count must be a whole number from 1, not {count!r}")
        self.count = count
        self.directory = Path(directory)
        self._lock = threading.Lock()
        # The descriptor of each slot this process holds, its lock taken.
        self._held: list[int] = []

    def _open_slot(self, index: int) -> int:
        """A new descriptor of slot ``index``'s file, the directory made again if it is gone."""
        path = self.directory / f"slot-{index}"
        flags = os.O_RDWR | os.O_CREAT
        try:
            return os.open(path, flags, _SLOT_FILE_MODE)
        except FileNotFoundError:
            path.parent.mkdir(mode=_DIRECTORY_MODE, parents=True, exist_ok=True)
            return os.open(path, flags, _SLOT_FILE_MODE)

    def _take(self) -> bool:
        """One free slot taken, without waiting: True, or False when every slot is held."""
        for index in range(self.count):
            descriptor = self._open_slot(index)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(descriptor)
                continue
            except BaseException:
                os.close(descriptor)
                raise
            with self._lock:
                self._held.append(descriptor)
            return True
        return False

    def acquire(self, blocking: bool = True, timeout: float | None = None) -> bool:
        """Take a slot: at once, or waiting up to ``timeout`` seconds (None: until one is free).

        Returns whether it took one. As ``threading.Semaphore``: a non-blocking acquire
        takes no timeout (ValueError), and a timeout past ``threading.TIMEOUT_MAX`` is
        OverflowError.
        """
        if not blocking and timeout is not None:
            raise ValueError("can't specify timeout for non-blocking acquire")
        if timeout is not None and timeout > threading.TIMEOUT_MAX:
            raise OverflowError("timeout value is too large")
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if self._take():
                return True
            if not blocking:
                return False
            if deadline is None:
                time.sleep(SLOT_POLL_SECONDS)
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(SLOT_POLL_SECONDS, remaining))

    def release(self) -> None:
        """Give back one slot this process holds; ValueError when it holds none."""
        with self._lock:
            if not self._held:
                raise ValueError("SidecarSlots released more slots than were taken")
            descriptor = self._held.pop()
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)
