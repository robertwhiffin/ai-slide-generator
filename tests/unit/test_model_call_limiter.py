"""The per-process model-call limiter, the cached stop check and the turn deadline.

``FairCallLimiter`` caps the model calls in flight in one process.  A caller takes a slot
at once when one is free and nobody waits; otherwise it queues.  A freed slot goes to the
waiter whose group (its turn's chat request id, or ``None`` for a caller with no turn) has
the fewest calls in flight *when the slot frees*, ties to the earliest arrival.  A waiter
blocks in ``wait_slice_seconds`` slices and calls its ``check_stop`` between them, outside
the limiter's lock.  When that raises, the waiter leaves the queue, gives back a slot
granted to it meanwhile (which may grant the next waiter), and re-raises the same error.

The threaded tests use real threads, ``threading.Event`` handshakes and a 10 ms slice.  No
assertion relies on a sleep: arrival order is fixed by polling ``waiting()`` before the
next caller starts, and every wait, join and poll is bounded, so a broken limiter fails a
test instead of hanging the run (pytest-timeout is not installed).  Every acquire that a
broken limiter could leave blocked runs on a daemon helper thread, and an exception raised
on one is kept and asserted on.

``check_turn_stopped`` asks ``generation_fence.raise_if_turn_ended``, which it imports
lazily, so the tests patch it on ``generation_fence`` (C3).  It reuses an answer per request
id for ``STOP_CHECK_INTERVAL_SECONDS``.  ``tests/conftest.py`` empties that cache before and
after every test (C4); ``test_every_test_starts_with_no_cached_stop_checks`` fails if it
stops doing so.
"""

from __future__ import annotations

import contextvars
import logging
import threading
import time
from collections.abc import Callable

import pytest

from src.services.generation_fence import TurnFencedError
from src.services.graph.event_emitter import set_chat_request_id
from src.services.model_calls import (
    DEFAULT_MODEL_CALL_CONCURRENCY,
    MAX_MODEL_CALL_CONCURRENCY,
    MODEL_CALL_CONCURRENCY_ENV,
    STOP_CHECK_INTERVAL_SECONDS,
    FairCallLimiter,
    check_turn_stopped,
    current_call_group,
    get_model_call_limiter,
    model_call_concurrency,
    reset_stop_checks,
    set_turn_deadline,
    turn_deadline,
)

#: ``wait_slice_seconds`` for every limiter built here.
SLICE = 0.01
#: The bound on every wait, join and poll: a test that would hang fails after this long.
TIMEOUT = 5.0
#: How long a lock probe may take before it counts as blocked.
PROBE_TIMEOUT = 2.0
#: Where ``check_turn_stopped``'s lazy import reads the stop query from (C3).
FENCE = "src.services.generation_fence.raise_if_turn_ended"
LOGGER = "src.services.model_calls"


# --------------------------------------------------------------------------- helpers


def _wait_until(predicate: Callable[[], bool], timeout: float = TIMEOUT) -> bool:
    """Poll *predicate* until it holds or *timeout* passes. The caller asserts the result."""
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.001)
    return True


class _Worker:
    """A daemon thread that keeps the exception its body raised, joined with a bound."""

    def __init__(self, name: str):
        self.error: BaseException | None = None
        self.thread = threading.Thread(target=self._run, name=name, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def _run(self) -> None:
        try:
            self.body()
        except BaseException as exc:  # noqa: BLE001 - kept and asserted on by the test
            self.error = exc

    def body(self) -> None:
        raise NotImplementedError

    def join(self, timeout: float = TIMEOUT) -> None:
        self.thread.join(timeout)
        assert not self.thread.is_alive(), f"{self.thread.name} did not finish in {timeout}s"


class _Call(_Worker):
    """Run *fn* on a daemon thread."""

    def __init__(self, fn: Callable[[], None], name: str = "call"):
        super().__init__(name)
        self._fn = fn

    def body(self) -> None:
        self._fn()


class _Caller(_Worker):
    """One model call through *limiter* that holds its slot until ``release`` is set.

    Inside the slot it appends *label* to *grants* (when given) and sets ``entered``.
    ``exited`` is set once the slot has been given back, so a test can wait for a release
    made on the caller's own thread.
    """

    def __init__(
        self,
        limiter: FairCallLimiter,
        group: str | None,
        *,
        label: str | None = None,
        grants: list[str] | None = None,
        check_stop: Callable[[], None] | None = None,
    ):
        self.label = label if label is not None else str(group)
        super().__init__(f"caller-{self.label}")
        self.limiter = limiter
        self.group = group
        self.grants = grants
        self.check_stop = check_stop
        self.entered = threading.Event()
        self.release = threading.Event()
        self.exited = threading.Event()

    def body(self) -> None:
        with self.limiter.slot(self.group, check_stop=self.check_stop):
            if self.grants is not None:
                self.grants.append(self.label)
            self.entered.set()
            if not self.release.wait(TIMEOUT):
                raise AssertionError(f"{self.label} was never released")
        self.exited.set()

    def finish(self) -> None:
        """Let the call give its slot back, and join it."""
        self.release.set()
        self.join()


def _hold(limiter: FairCallLimiter, group: str | None, label: str | None = None) -> _Caller:
    """A caller that has taken its slot (asserted) and holds it."""
    caller = _Caller(limiter, group, label=label).start()
    assert caller.entered.wait(TIMEOUT), f"{caller.label} did not get a free slot"
    return caller


def _queue(
    limiter: FairCallLimiter,
    group: str | None,
    *,
    position: int,
    label: str | None = None,
    grants: list[str] | None = None,
    check_stop: Callable[[], None] | None = None,
) -> _Caller:
    """A caller that has joined the queue, as its *position*-th waiter (asserted)."""
    caller = _Caller(limiter, group, label=label, grants=grants, check_stop=check_stop).start()
    assert _wait_until(lambda: limiter.waiting() == position), (
        f"{caller.label} did not queue: waiting()={limiter.waiting()}, expected {position}"
    )
    assert not caller.entered.is_set(), f"{caller.label} took a slot instead of queueing"
    return caller


def _assert_clean(*callers: _Worker) -> None:
    for caller in callers:
        assert caller.error is None, f"{caller.thread.name} raised {caller.error!r}"


class _FenceRecorder:
    """Stands in for ``raise_if_turn_ended``: records each id asked, raises *error* if set."""

    def __init__(self, error: BaseException | None = None):
        self.asked: list[str | None] = []
        self.error = error

    def __call__(self, request_id: str | None = None) -> None:
        self.asked.append(request_id)
        if self.error is not None:
            raise self.error


class _Clock:
    """A settable stand-in for ``time.monotonic``."""

    def __init__(self, now: float = 0.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


# --------------------------------------------------------------------------- the cap


def test_default_cap_is_six(monkeypatch):
    # Lowered from 15 (then 10) by the 2026-11-18 devloop load test: an 8-deck burst
    # had 4 of 7 turns give up on rate_limited at 15, and 5 of 8 at 10.
    monkeypatch.delenv(MODEL_CALL_CONCURRENCY_ENV, raising=False)
    assert model_call_concurrency() == 6
    assert DEFAULT_MODEL_CALL_CONCURRENCY == 6


@pytest.mark.parametrize(("raw", "expected"), [("12", 12), (" 3 ", 3), ("1", 1), ("64", 64)])
def test_cap_comes_from_the_environment(monkeypatch, raw, expected):
    monkeypatch.setenv(MODEL_CALL_CONCURRENCY_ENV, raw)
    assert model_call_concurrency() == expected


@pytest.mark.parametrize("raw", ["0", "-1", "x", "", "2.5"])
def test_an_unusable_value_falls_back(monkeypatch, caplog, raw):
    monkeypatch.setenv(MODEL_CALL_CONCURRENCY_ENV, raw)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert model_call_concurrency() == 6
    warnings = [
        r
        for r in caplog.records
        if r.name == LOGGER
        and r.levelno == logging.WARNING
        and "TELLR_MODEL_CALL_CONCURRENCY" in r.getMessage()
    ]
    assert len(warnings) == 1, [r.getMessage() for r in caplog.records]


def test_a_huge_value_is_capped(monkeypatch):
    monkeypatch.setenv(MODEL_CALL_CONCURRENCY_ENV, "500")
    assert model_call_concurrency() == 64
    assert MAX_MODEL_CALL_CONCURRENCY == 64


def test_the_env_var_name_is_stable():
    assert MODEL_CALL_CONCURRENCY_ENV == "TELLR_MODEL_CALL_CONCURRENCY"


@pytest.fixture
def fresh_process_limiter():
    """Drop the cached process limiter around the test, so no test inherits its size."""
    get_model_call_limiter.cache_clear()
    yield
    get_model_call_limiter.cache_clear()


def test_the_process_limiter_is_shared_and_sized_by_the_environment(
    monkeypatch, fresh_process_limiter
):
    monkeypatch.setenv(MODEL_CALL_CONCURRENCY_ENV, "2")
    limiter = get_model_call_limiter()
    assert isinstance(limiter, FairCallLimiter)
    assert get_model_call_limiter() is limiter

    first = _hold(limiter, "A")
    second = _hold(limiter, "B")
    third = _queue(limiter, "C", position=1)
    assert limiter.in_flight() == {"A": 1, "B": 1}

    first.finish()
    assert third.entered.wait(TIMEOUT), "the freed slot never reached the queued call"
    second.finish()
    third.finish()
    _assert_clean(first, second, third)
    assert limiter.in_flight() == {}
    assert limiter.waiting() == 0


def test_the_cap_holds_across_threads():
    limiter = FairCallLimiter(3, wait_slice_seconds=SLICE)
    lock = threading.Lock()
    state = {"inside": 0, "peak": 0, "done": 0}
    gate = threading.Event()

    def call(group: str) -> Callable[[], None]:
        def run() -> None:
            with limiter.slot(group):
                with lock:
                    state["inside"] += 1
                    state["peak"] = max(state["peak"], state["inside"])
                try:
                    if not gate.wait(TIMEOUT):
                        raise AssertionError("the gate never opened")
                finally:
                    with lock:
                        state["inside"] -= 1
            with lock:
                state["done"] += 1

        return run

    workers = [_Call(call(f"turn-{i % 4}"), name=f"call-{i}").start() for i in range(12)]

    saturated = _wait_until(lambda: limiter.waiting() == 9 and state["inside"] == 3)
    assert saturated, f"waiting()={limiter.waiting()}, state={state}"
    assert state["peak"] == 3

    gate.set()
    for worker in workers:
        worker.join()
    _assert_clean(*workers)
    assert state["done"] == 12
    assert state["peak"] <= 3
    assert limiter.in_flight() == {}
    assert limiter.waiting() == 0


# --------------------------------------------------------------------------- fairness


def test_a_freed_slot_goes_to_the_turn_with_fewest_calls_in_flight():
    limiter = FairCallLimiter(2, wait_slice_seconds=SLICE)
    grants: list[str] = []
    a1 = _hold(limiter, "A", "A1")
    a2 = _hold(limiter, "A", "A2")
    a3 = _queue(limiter, "A", position=1, label="A3", grants=grants)
    b1 = _queue(limiter, "B", position=2, label="B1", grants=grants)

    a1.finish()
    assert _wait_until(lambda: len(grants) >= 1), "the freed slot was granted to nobody"
    assert grants == ["B1"]
    assert limiter.in_flight() == {"A": 1, "B": 1}
    assert limiter.waiting() == 1

    b1.finish()
    assert _wait_until(lambda: len(grants) >= 2), "A3 was never granted"
    assert grants == ["B1", "A3"]
    a2.finish()
    a3.finish()
    _assert_clean(a1, a2, a3, b1)
    assert limiter.in_flight() == {}
    assert limiter.waiting() == 0


def test_fewest_in_flight_is_counted_when_the_slot_frees():
    """``A2`` and ``B2`` each queued while their turn had one call in flight; ``A2`` first.

    When ``B``'s call ends, ``B`` has none in flight and ``A`` still has one, so the slot
    goes to ``B2``.  A limiter that ranks waiters by the count they arrived with sees a
    tie, and gives it to ``A2``.
    """
    limiter = FairCallLimiter(2, wait_slice_seconds=SLICE)
    grants: list[str] = []
    a1 = _hold(limiter, "A", "A1")
    b1 = _hold(limiter, "B", "B1")
    a2 = _queue(limiter, "A", position=1, label="A2", grants=grants)
    b2 = _queue(limiter, "B", position=2, label="B2", grants=grants)

    b1.finish()
    assert _wait_until(lambda: len(grants) >= 1), "the freed slot was granted to nobody"
    assert grants == ["B2"]
    assert limiter.in_flight() == {"A": 1, "B": 1}

    for caller in (a1, b2, a2):
        caller.finish()
    assert grants == ["B2", "A2"]
    _assert_clean(a1, b1, a2, b2)
    assert limiter.in_flight() == {}


@pytest.mark.parametrize(
    ("first", "second"), [("C", "D"), ("D", "C")], ids=["C-then-D", "D-then-C"]
)
def test_ties_go_first_come_first_served(first, second):
    limiter = FairCallLimiter(1, wait_slice_seconds=SLICE)
    grants: list[str] = []
    holder = _hold(limiter, "X")
    early = _queue(limiter, first, position=1, label=f"{first}1", grants=grants)
    late = _queue(limiter, second, position=2, label=f"{second}1", grants=grants)

    holder.finish()
    assert _wait_until(lambda: len(grants) >= 1), "the freed slot was granted to nobody"
    assert grants == [f"{first}1"]

    early.finish()
    assert _wait_until(lambda: len(grants) >= 2), f"{second}1 was never granted"
    assert grants == [f"{first}1", f"{second}1"]
    late.finish()
    _assert_clean(holder, early, late)
    assert limiter.in_flight() == {}


def test_a_grant_wakes_its_waiter_at_once():
    """A freed slot reaches its waiter now, not when the waiter's slice runs out.

    The only test with a long slice: a minute here, a second in production.  A limiter
    that never notifies its waiters would still pass every other test, on the 10 ms
    slices, while adding up to a slice of delay to each grant.
    """
    limiter = FairCallLimiter(1, wait_slice_seconds=60.0)
    holder = _hold(limiter, "H")
    waiter = _queue(limiter, "W", position=1)

    holder.finish()
    assert waiter.entered.wait(TIMEOUT), "the waiter was not woken by the grant"
    waiter.finish()
    _assert_clean(holder, waiter)
    assert limiter.in_flight() == {}


def test_calls_with_no_turn_share_one_group():
    limiter = FairCallLimiter(3, wait_slice_seconds=SLICE)
    first = _hold(limiter, None, "none-1")
    second = _hold(limiter, None, "none-2")
    assert limiter.in_flight() == {None: 2}

    first.finish()
    second.finish()
    _assert_clean(first, second)
    assert limiter.in_flight() == {}


def test_calls_with_no_turn_queue_as_one_group():
    """The sweeper's and the previews' calls are ranked together, as one turn would be."""
    limiter = FairCallLimiter(2, wait_slice_seconds=SLICE)
    grants: list[str] = []
    n1 = _hold(limiter, None, "none-1")
    n2 = _hold(limiter, None, "none-2")
    n3 = _queue(limiter, None, position=1, label="none-3", grants=grants)
    t1 = _queue(limiter, "req-t", position=2, label="T1", grants=grants)

    n1.finish()
    assert _wait_until(lambda: len(grants) >= 1), "the freed slot was granted to nobody"
    assert grants == ["T1"]
    assert limiter.in_flight() == {None: 1, "req-t": 1}

    for caller in (n2, t1, n3):
        caller.finish()
    _assert_clean(n1, n2, n3, t1)
    assert limiter.in_flight() == {}


# --------------------------------------------------------------------------- releases


def test_a_slot_is_released_when_the_call_raises():
    limiter = FairCallLimiter(1, wait_slice_seconds=SLICE)
    boom = ValueError("the reply did not parse")

    def failing_call() -> None:
        with limiter.slot("A"):
            raise boom

    run = _Call(failing_call, name="failing-call").start()
    run.join()
    assert run.error is boom
    assert limiter.in_flight() == {}
    assert limiter.waiting() == 0

    fresh = _Caller(limiter, "B").start()
    assert fresh.entered.wait(TIMEOUT), "the slot the failed call held was never given back"
    assert limiter.in_flight() == {"B": 1}
    fresh.finish()
    _assert_clean(fresh)
    assert limiter.in_flight() == {}


# --------------------------------------------------------------------------- stops


def test_a_stop_ends_a_wait_and_leaves_no_trace():
    limiter = FairCallLimiter(2, wait_slice_seconds=SLICE)
    h1 = _hold(limiter, "H", "H1")
    h2 = _hold(limiter, "H", "H2")
    stop_now = threading.Event()
    stop = TurnFencedError("req-w")
    raised: list[TurnFencedError] = []

    def check_stop() -> None:
        if stop_now.is_set():
            raised.append(stop)
            raise stop

    waiter = _queue(limiter, "W", position=1, check_stop=check_stop)
    stop_now.set()
    waiter.join()
    assert raised, "check_stop was never called while the call waited"
    assert waiter.error is stop
    assert not waiter.entered.is_set()
    assert limiter.waiting() == 0
    assert limiter.in_flight() == {"H": 2}

    h1.finish()
    h2.finish()
    _assert_clean(h1, h2)
    assert limiter.in_flight() == {}

    # The whole capacity can be taken again: the stopped call left no claim behind.
    z1 = _hold(limiter, "Z", "Z1")
    z2 = _hold(limiter, "Z", "Z2")
    assert limiter.in_flight() == {"Z": 2}
    assert limiter.waiting() == 0
    z1.finish()
    z2.finish()
    _assert_clean(z1, z2)
    assert limiter.in_flight() == {}


def test_a_stop_racing_a_grant_returns_the_slot():
    """The stopping waiter is granted the slot inside its own ``check_stop``, then stops.

    It must give that slot back, and the call queued behind it must then get it.
    """
    limiter = FairCallLimiter(1, wait_slice_seconds=SLICE)
    grants: list[str] = []
    holder = _hold(limiter, "H")
    go = threading.Event()
    stop = TurnFencedError("req-s")
    seen: dict[str, bool] = {}

    def check_stop() -> None:
        if not go.is_set():
            return
        holder.release.set()
        seen["holder_gave_its_slot_back"] = holder.exited.wait(TIMEOUT)
        raise stop

    stopper = _queue(limiter, "S", position=1, label="S", grants=grants, check_stop=check_stop)
    behind = _queue(limiter, "N", position=2, label="N", grants=grants)

    go.set()
    stopper.join()
    assert stopper.error is stop
    assert seen == {"holder_gave_its_slot_back": True}
    assert not stopper.entered.is_set()
    holder.join()

    assert behind.entered.wait(TIMEOUT), "the slot the stopped call was granted was not returned"
    assert grants == ["N"]
    assert limiter.in_flight() == {"N": 1}
    assert limiter.waiting() == 0
    behind.finish()
    _assert_clean(holder, behind)
    assert limiter.in_flight() == {}
    assert limiter.waiting() == 0


def test_a_stop_check_runs_outside_the_lock():
    """While a waiter's ``check_stop`` runs, another thread can still read the limiter.

    ``threading.Condition()`` defaults to an ``RLock``, so a probe on the waiter's own
    thread would get in even under the lock; only a probe from another thread tells.
    """
    limiter = FairCallLimiter(1, wait_slice_seconds=SLICE)
    holder = _hold(limiter, "H")
    probes: list[bool] = []
    stop = TurnFencedError("req-w")

    def probe(done: threading.Event) -> None:
        limiter.in_flight()
        limiter.waiting()
        done.set()

    def check_stop() -> None:
        if len(probes) < 3:
            done = threading.Event()
            threading.Thread(target=probe, args=(done,), daemon=True).start()
            probes.append(done.wait(PROBE_TIMEOUT))
            return
        raise stop

    waiter = _Caller(limiter, "W", check_stop=check_stop).start()
    waiter.join(timeout=3 * PROBE_TIMEOUT + TIMEOUT)
    assert probes == [True, True, True], "check_stop ran while the limiter's lock was held"
    assert waiter.error is stop
    assert limiter.waiting() == 0
    holder.finish()
    _assert_clean(holder)
    assert limiter.in_flight() == {}


# --------------------------------------------------------------------------- stop check


def test_no_request_id_means_no_stop_query(monkeypatch):
    fence = _FenceRecorder(error=AssertionError("a call with no turn queried its status"))
    monkeypatch.setattr(FENCE, fence)

    def no_turn() -> None:
        set_chat_request_id(None)
        assert check_turn_stopped(None) is None
        assert check_turn_stopped() is None

    contextvars.copy_context().run(no_turn)
    assert fence.asked == []


def test_the_stop_check_defaults_to_the_current_turn(monkeypatch):
    """The positive control for the test above: inside a turn, the turn's id is asked."""
    fence = _FenceRecorder()
    monkeypatch.setattr(FENCE, fence)
    seen: dict[str, str | None] = {}

    def in_turn() -> None:
        set_chat_request_id("req-x")
        seen["inside"] = current_call_group()
        check_turn_stopped()
        check_turn_stopped("req-explicit")

    def around() -> None:
        set_chat_request_id(None)
        seen["before"] = current_call_group()
        contextvars.copy_context().run(in_turn)
        seen["after"] = current_call_group()

    contextvars.copy_context().run(around)
    assert seen == {"before": None, "inside": "req-x", "after": None}
    assert fence.asked == ["req-x", "req-explicit"]


def test_a_stop_check_is_reused_within_the_interval(monkeypatch):
    assert STOP_CHECK_INTERVAL_SECONDS == 2.0
    fence = _FenceRecorder()
    monkeypatch.setattr(FENCE, fence)
    clock = _Clock(0.0)

    check_turn_stopped("req-live", clock=clock)
    clock.now = 1.9
    check_turn_stopped("req-live", clock=clock)
    assert fence.asked == ["req-live"]

    clock.now = 2.1
    check_turn_stopped("req-live", clock=clock)
    assert fence.asked == ["req-live", "req-live"]

    # Another turn inside req-live's interval is asked about on its own.
    clock.now = 2.5
    check_turn_stopped("req-other", clock=clock)
    check_turn_stopped("req-live", clock=clock)
    assert fence.asked == ["req-live", "req-live", "req-other"]

    # A stopped answer is reused too: both checks inside the interval raise.
    stopped = _FenceRecorder(error=TurnFencedError("req-stopped"))
    monkeypatch.setattr(FENCE, stopped)
    clock.now = 10.0
    with pytest.raises(TurnFencedError) as first:
        check_turn_stopped("req-stopped", clock=clock)
    clock.now = 11.9
    with pytest.raises(TurnFencedError) as second:
        check_turn_stopped("req-stopped", clock=clock)
    assert stopped.asked == ["req-stopped"]
    assert first.value.request_id == second.value.request_id == "req-stopped"


def test_reset_stop_checks_forgets_cached_results(monkeypatch):
    fence = _FenceRecorder()
    monkeypatch.setattr(FENCE, fence)
    clock = _Clock(5.0)
    check_turn_stopped("req-r", clock=clock)
    check_turn_stopped("req-r", clock=clock)
    assert fence.asked == ["req-r"]

    reset_stop_checks()
    check_turn_stopped("req-r", clock=clock)
    assert fence.asked == ["req-r", "req-r"]

    # A cached stop is forgotten too: after a reset the turn is asked about afresh.
    monkeypatch.setattr(FENCE, _FenceRecorder(error=TurnFencedError("req-s")))
    with pytest.raises(TurnFencedError):
        check_turn_stopped("req-s", clock=clock)
    reset_stop_checks()
    live = _FenceRecorder()
    monkeypatch.setattr(FENCE, live)
    assert check_turn_stopped("req-s", clock=clock) is None
    assert live.asked == ["req-s"]


@pytest.mark.parametrize("case", ["first", "second"])
def test_every_test_starts_with_no_cached_stop_checks(request, monkeypatch, case):
    """Guards the autouse reset in ``tests/conftest.py`` (C4).

    Both cases ask about the same turn at the same instant.  The second is asked afresh
    only if the cache was emptied after the first, so removing the fixture turns it red.
    Under xdist the two cases can run on different workers, so the fixture's presence is
    checked as well.
    """
    assert "reset_model_call_stop_checks" in request.fixturenames
    fence = _FenceRecorder()
    monkeypatch.setattr(FENCE, fence)
    check_turn_stopped("req-guard", clock=lambda: 100.0)
    assert fence.asked == ["req-guard"]


# --------------------------------------------------------------------------- deadline


def test_the_turn_deadline_is_per_context():
    def scenario() -> None:
        assert turn_deadline() is None

        turn = contextvars.copy_context()
        turn.run(set_turn_deadline, 1234.5)
        assert turn.run(turn_deadline) == 1234.5
        assert turn_deadline() is None

        set_turn_deadline(99.0)
        assert turn_deadline() == 99.0
        assert turn.run(turn_deadline) == 1234.5
        set_turn_deadline(None)
        assert turn_deadline() is None

    # A brand-new context: every variable at its default, whatever this thread set before.
    contextvars.Context().run(scenario)
