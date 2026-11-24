"""The app's queue workers after a loop error, and the queues each test waits on.

Each of the app's three background queues (the chat jobs', the exports', the slide-style
previews') is a module-level ``asyncio.Queue``, bound to the first event loop that waits on
it. A test that drives a worker under its own ``asyncio.run`` leaves the queue bound to that
loop once the loop ends (``tests/integration/test_architect_reply_is_persisted.py`` drives
the real chat worker so), and a wait on it in any later loop raises ``RuntimeError`` at once,
before yielding. Each worker caught that, logged it and waited again: a loop that never
yielded, so the sweeper's worker test (``test_job_queue_timeout_sweeper.py``) never reached
its own 2 s timeout, and the log records pytest keeps grew the serial suite's one process
to 18 GB until macOS killed it.

* each worker yields after a loop error, for its backoff, so a queue it cannot wait on costs
  one log line per backoff and its task can still be cancelled;
* each test waits on fresh queues (``tests/conftest.py``), so no test inherits a queue an
  earlier test's loop bound.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib

import pytest

#: (module, its queue, its worker): each background queue the app drains.
QUEUE_WORKERS = (
    ("src.api.services.job_queue", "job_queue", "worker"),
    ("src.api.services.export_job_queue", "export_queue", "export_worker"),
    ("src.api.services.slide_style_preview_queue", "preview_queue", "preview_worker"),
)
#: How long a worker is given over a queue it cannot wait on, under its backoff.
WINDOW_SECONDS = 0.2
#: A worker that logs this many loop errors in the window has not yielded between them.
SPIN_CALLS = 50


class _Spun(BaseException):
    """Ends a worker that logged SPIN_CALLS loop errors without yielding."""


def _bind_to_an_ended_loop(queue: asyncio.Queue) -> None:
    """Bind ``queue`` to an event loop that then ends, as a test's ``asyncio.run`` does."""

    async def wait_briefly() -> None:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(queue.get(), timeout=0.01)

    asyncio.run(wait_briefly())


def _wait_in_a_new_loop(queue: asyncio.Queue) -> str:
    """What waiting on the empty ``queue`` in a new event loop does: ``waits``, or its error."""

    async def wait_briefly() -> str:
        try:
            await asyncio.wait_for(queue.get(), timeout=0.01)
        except asyncio.TimeoutError:
            return "waits"
        except RuntimeError as error:
            return f"raises {error}"
        return "returns an item"

    return asyncio.run(wait_briefly())


@pytest.mark.parametrize("module_name, queue_name, worker_name", QUEUE_WORKERS)
def test_a_worker_yields_after_a_loop_error(
    module_name: str, queue_name: str, worker_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Over a queue another loop bound, the worker logs the error once per backoff and yields.

    The test's own sleep returns only if the worker yields; then cancelling the worker
    stops it. A worker that logs SPIN_CALLS errors first is stopped by the counting log.
    """
    module = importlib.import_module(module_name)
    queue: asyncio.Queue = asyncio.Queue()
    _bind_to_an_ended_loop(queue)
    monkeypatch.setattr(module, queue_name, queue)
    errors: list[str] = []

    def count_error(message: object, *args: object, **kwargs: object) -> None:
        errors.append(str(message))
        if len(errors) >= SPIN_CALLS:
            raise _Spun

    monkeypatch.setattr(module.logger, "error", count_error)

    async def run_for_the_window() -> bool:
        task = asyncio.create_task(getattr(module, worker_name)())
        await asyncio.sleep(WINDOW_SECONDS)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, _Spun):
            await task
        return task.done()

    stopped = asyncio.run(run_for_the_window())
    assert len(errors) < SPIN_CALLS, (
        f"{worker_name} logged {len(errors)} loop errors in {WINDOW_SECONDS} s without "
        f"yielding between them; the first: {errors[0]!r}"
    )
    assert errors and "different event loop" in errors[0], (
        f"fixture drift: {worker_name} over a queue an ended loop bound logged {errors}"
    )
    most = WINDOW_SECONDS / module.WORKER_LOOP_ERROR_BACKOFF_SECONDS + 1
    assert len(errors) <= most, (
        f"{worker_name} logged {len(errors)} loop errors in {WINDOW_SECONDS} s, more than one "
        f"per {module.WORKER_LOOP_ERROR_BACKOFF_SECONDS} s backoff"
    )
    assert stopped, f"{worker_name} did not stop when cancelled"


class TestEachTestWaitsOnFreshQueues:
    """In order: the first test binds each queue to its ended loop; the next waits on fresh ones."""

    @pytest.mark.parametrize("module_name, queue_name, worker_name", QUEUE_WORKERS)
    def test_a_test_may_leave_its_queue_bound_to_an_ended_loop(
        self, module_name: str, queue_name: str, worker_name: str
    ) -> None:
        module = importlib.import_module(module_name)
        _bind_to_an_ended_loop(getattr(module, queue_name))
        outcome = _wait_in_a_new_loop(getattr(module, queue_name))
        assert outcome.startswith("raises") and "different event loop" in outcome, (
            f"fixture drift: {queue_name}, bound to an ended loop, then in a new loop {outcome}"
        )

    @pytest.mark.parametrize("module_name, queue_name, worker_name", QUEUE_WORKERS)
    def test_the_next_test_waits_on_a_fresh_queue(
        self, module_name: str, queue_name: str, worker_name: str
    ) -> None:
        module = importlib.import_module(module_name)
        outcome = _wait_in_a_new_loop(getattr(module, queue_name))
        assert outcome == "waits", (
            f"{queue_name}, which the test before this one bound to its ended loop, in this "
            f"test's loop {outcome}: a test inherits a queue an earlier test bound"
        )
