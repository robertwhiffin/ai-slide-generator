"""The export sidecars' slots: a counting semaphore of the container (``sidecar_slots.py``).

``SidecarSlots`` keeps ``threading.BoundedSemaphore``'s interface (``acquire`` with
``blocking`` and ``timeout``, ``release``), so the wrapper's admission takes it where it took
a worker's own semaphore. Each slot is a file of one directory, held with a non-blocking
``fcntl.flock`` on a descriptor of its own: a lock is the open file's, not the process's, so
two threads of one process contend for a slot as two processes do. The cases across real
processes, and the wrapper's and ``run.py``'s use of it, are in
``test_export_sidecar_slots_across_workers.py``.
"""

from __future__ import annotations

import os
import stat
import threading
import time
from pathlib import Path

import pytest

from src.services.sidecar_slots import SLOTS_DIR_ENV, SidecarSlots, slots_directory

# A wait that must end at its bound ends within this much past it: the slots are tried
# again every SLOT_POLL_SECONDS, and a thread takes time to be scheduled.
WAIT_SLACK_SECONDS = 0.5
# The bound of the bounded waits below.
SHORT_WAIT_SECONDS = 0.3


def _taken(slots: SidecarSlots, attempts: int) -> list[bool]:
    """``attempts`` non-blocking acquires, each from a thread of its own, in order."""
    results: list[bool] = []

    def attempt() -> None:
        results.append(slots.acquire(blocking=False))

    for _ in range(attempts):
        thread = threading.Thread(target=attempt)
        thread.start()
        thread.join()
    return results


class TestTheSlotsAreCounted:
    def test_the_threads_of_one_process_hold_at_most_its_count(self, tmp_path: Path) -> None:
        slots = SidecarSlots(2, tmp_path)
        try:
            assert _taken(slots, 3) == [True, True, False]
            slots.release()
            assert _taken(slots, 1) == [True]
        finally:
            slots.release()
            slots.release()

    def test_two_slot_sets_on_one_directory_share_its_slots(self, tmp_path: Path) -> None:
        """As two workers do: what one holds, the other cannot take."""
        first, second = SidecarSlots(1, tmp_path), SidecarSlots(1, tmp_path)
        assert first.acquire(blocking=False)
        try:
            assert not second.acquire(blocking=False)
        finally:
            first.release()
        assert second.acquire(blocking=False)
        second.release()

    def test_a_slot_count_below_one_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            SidecarSlots(0, tmp_path)


class TestTheWaitIsBounded:
    def test_a_wait_with_every_slot_held_ends_at_its_timeout(self, tmp_path: Path) -> None:
        holder, waiter = SidecarSlots(1, tmp_path), SidecarSlots(1, tmp_path)
        assert holder.acquire(blocking=False)
        try:
            started = time.monotonic()
            taken = waiter.acquire(timeout=SHORT_WAIT_SECONDS)
            waited = time.monotonic() - started
        finally:
            holder.release()
        assert not taken
        assert SHORT_WAIT_SECONDS <= waited < SHORT_WAIT_SECONDS + WAIT_SLACK_SECONDS, waited

    def test_a_waiter_takes_the_slot_once_it_is_released(self, tmp_path: Path) -> None:
        holder, waiter = SidecarSlots(1, tmp_path), SidecarSlots(1, tmp_path)
        assert holder.acquire(blocking=False)
        released = threading.Timer(SHORT_WAIT_SECONDS, holder.release)
        started = time.monotonic()
        released.start()
        try:
            taken = waiter.acquire(timeout=10)
            waited = time.monotonic() - started
        finally:
            released.join()
        assert taken
        waiter.release()
        assert SHORT_WAIT_SECONDS <= waited < SHORT_WAIT_SECONDS + WAIT_SLACK_SECONDS, waited


class TestTheSemaphoreInterfaceIsKept:
    """What ``threading.BoundedSemaphore`` answers, ``SidecarSlots`` answers too."""

    def test_releasing_more_than_was_taken_raises(self, tmp_path: Path) -> None:
        slots = SidecarSlots(1, tmp_path)
        with pytest.raises(ValueError):
            slots.release()
        assert slots.acquire(blocking=False)
        slots.release()
        with pytest.raises(ValueError):
            slots.release()

    def test_a_non_blocking_acquire_takes_no_timeout(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            SidecarSlots(1, tmp_path).acquire(blocking=False, timeout=1)

    def test_a_timeout_past_the_longest_a_lock_takes_overflows(self, tmp_path: Path) -> None:
        with pytest.raises(OverflowError):
            SidecarSlots(1, tmp_path).acquire(timeout=threading.TIMEOUT_MAX * 2)

    def test_a_slot_taken_by_one_thread_can_be_released_by_another(self, tmp_path: Path) -> None:
        """A counting semaphore's release is no one thread's, and its slots are alike."""
        slots = SidecarSlots(1, tmp_path)
        assert _taken(slots, 1) == [True]
        releasing = threading.Thread(target=slots.release)
        releasing.start()
        releasing.join()
        assert slots.acquire(blocking=False)
        slots.release()


class TestWhereTheSlotsAre:
    def test_a_directory_removed_under_the_slots_is_made_again(self, tmp_path: Path) -> None:
        """The owner's alone, as run.py made it (a temporary-file sweep can remove it)."""
        directory = tmp_path / "slots"
        directory.mkdir(mode=0o700)
        slots = SidecarSlots(1, directory)
        assert slots.acquire(blocking=False)
        slots.release()
        for slot in directory.iterdir():
            slot.unlink()
        directory.rmdir()
        assert slots.acquire(blocking=False)
        slots.release()
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700

    def test_the_slot_files_are_the_owners_alone(self, tmp_path: Path) -> None:
        slots = SidecarSlots(2, tmp_path)
        assert slots.acquire(blocking=False)
        slots.release()
        modes = {stat.S_IMODE(slot.stat().st_mode) for slot in tmp_path.iterdir()}
        assert modes == {0o600}, modes

    @pytest.mark.parametrize(("value", "named"), [(None, False), ("", False), ("/x/slots", True)])
    def test_the_directory_is_read_from_the_environment(
        self, value: str | None, named: bool
    ) -> None:
        environ = {} if value is None else {SLOTS_DIR_ENV: value}
        assert slots_directory(environ) == (Path(value) if named else None)


def test_the_slots_hold_no_descriptor_once_released(tmp_path: Path) -> None:
    """Each taken slot's descriptor is closed with its release: none leaks per export."""
    slots = SidecarSlots(2, tmp_path)
    before = len(os.listdir("/dev/fd"))
    for _ in range(20):
        assert slots.acquire(blocking=False) and slots.acquire(blocking=False)
        assert not slots.acquire(blocking=False)
        slots.release()
        slots.release()
    assert len(os.listdir("/dev/fd")) == before
