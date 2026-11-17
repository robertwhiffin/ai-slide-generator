"""Model calls: the fault kinds, the per-process call limiter, the stop check, the deadline.

- ``model_fault_kind`` names the provider fault behind a failed call.
- ``FairCallLimiter`` caps the model calls in flight in one process
  (``get_model_call_limiter``, sized by ``TELLR_MODEL_CALL_CONCURRENCY``).  A freed slot
  goes to the waiting turn with the fewest calls in flight.
- ``check_turn_stopped`` asks whether the current turn was stopped, reusing an answer per
  turn for ``STOP_CHECK_INTERVAL_SECONDS``.
- ``set_turn_deadline`` / ``turn_deadline`` carry the turn's hard deadline in a
  ``ContextVar``.

The retries that use these arrive in a later task of the chat-concurrency build.

It must never import ``src.services.agent_runtime``: the runtime imports this module.
``generation_fence`` and ``graph.event_emitter`` are imported inside the functions that
use them.
"""

from __future__ import annotations

import itertools
import logging
import os
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from typing import Literal

import httpx
import openai
import requests
from databricks.sdk.errors import Aborted, DeadlineExceeded, InternalError

logger = logging.getLogger(__name__)

ModelFaultKind = Literal["rate_limited", "server_error", "timeout", "connection", "not_transient"]

#: The kinds a retry or a later turn can succeed on.
TRANSIENT_FAULT_KINDS: frozenset[str] = frozenset(
    {"rate_limited", "server_error", "timeout", "connection"}
)

# Checked before the connection classes: APITimeoutError subclasses APIConnectionError and
# httpx.TimeoutException subclasses httpx.TransportError.
_TIMEOUT_ERRORS = (
    openai.APITimeoutError,
    httpx.TimeoutException,
    requests.exceptions.Timeout,
    TimeoutError,
    DeadlineExceeded,
)

# Aborted subclasses the SDK's 409 ResourceConflict but is a dropped connection, not a 409
# status; the label is the contract.
_CONNECTION_ERRORS = (
    openai.APIConnectionError,
    httpx.TransportError,
    requests.exceptions.ConnectionError,
    ConnectionError,
    Aborted,
)


def _status_kind(status: int) -> ModelFaultKind:
    if status == 429:
        return "rate_limited"
    if status == 408:
        return "timeout"
    if status == 409 or status >= 500:
        return "server_error"
    return "not_transient"


def model_fault_kind(error: BaseException) -> ModelFaultKind:
    """Name the provider fault behind *error*, read off its ``raise ... from`` chain.

    Walks ``__cause__ or __context__`` with a seen-set; the first recognised link decides:
    a timeout class, then a connection class, then ``InternalError``, then an
    ``openai.APIStatusError`` by status.  An error with no recognised cause is
    ``not_transient``.
    """
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, _TIMEOUT_ERRORS):
            return "timeout"
        if isinstance(current, _CONNECTION_ERRORS):
            return "connection"
        if isinstance(current, InternalError):
            return "server_error"
        if isinstance(current, openai.APIStatusError):
            return _status_kind(current.status_code)
        current = current.__cause__ or current.__context__
    return "not_transient"


# --------------------------------------------------------------------------- the cap

# Model calls in flight per process, across every turn.  With 4 uvicorn processes the
# default keeps the app-wide ceiling at about 60 calls, as with one job runner each.
MODEL_CALL_CONCURRENCY_ENV = "TELLR_MODEL_CALL_CONCURRENCY"
DEFAULT_MODEL_CALL_CONCURRENCY = 15
MAX_MODEL_CALL_CONCURRENCY = 64


def model_call_concurrency() -> int:
    """Model calls in flight per process, from ``TELLR_MODEL_CALL_CONCURRENCY``.

    Default 15, max 64; an unusable value logs a warning and falls back to the default.
    """
    raw = os.getenv(MODEL_CALL_CONCURRENCY_ENV)
    if raw is None:
        return DEFAULT_MODEL_CALL_CONCURRENCY
    try:
        value = int(raw.strip())
    except ValueError:
        value = 0
    if value < 1:
        logger.warning(
            "Ignoring %s=%r; using %d model calls in flight per process",
            MODEL_CALL_CONCURRENCY_ENV,
            raw,
            DEFAULT_MODEL_CALL_CONCURRENCY,
        )
        return DEFAULT_MODEL_CALL_CONCURRENCY
    return min(value, MAX_MODEL_CALL_CONCURRENCY)


# --------------------------------------------------------------------------- the limiter


class _Waiter:
    """One queued caller: its group, its arrival number, and the condition it sleeps on."""

    __slots__ = ("group", "arrival", "wakeup", "granted")

    def __init__(self, group: str | None, arrival: int, wakeup: threading.Condition):
        self.group = group
        self.arrival = arrival
        self.wakeup = wakeup
        self.granted = False


class FairCallLimiter:
    """At most *capacity* calls in flight; a freed slot goes to the least-served group.

    A group is a turn's chat request id; callers with no turn share the group ``None``.

    - A caller takes a slot at once if one is free and nobody waits; otherwise it queues
      with an arrival number.
    - A release hands the freed slot straight to a waiter, under the lock: the one whose
      group has the fewest calls in flight, ties to the earliest arrival.  Grants go on
      while slots are free, and each grant wakes only its own waiter.
    - A waiter sleeps in ``wait_slice_seconds`` slices and calls *check_stop* between
      them, outside the lock.  If anything it waits on raises, it leaves the queue, gives
      back a slot granted to it meanwhile (which may grant the next waiter), and
      re-raises.
    """

    def __init__(self, capacity: int, *, wait_slice_seconds: float = 1.0):
        if capacity < 1:
            raise ValueError(f"capacity must be at least 1, got {capacity}")
        self._capacity = capacity
        self._wait_slice_seconds = wait_slice_seconds
        self._lock = threading.Lock()
        self._in_flight: dict[str | None, int] = {}
        self._total = 0
        self._waiters: list[_Waiter] = []
        self._arrivals = itertools.count()

    @contextmanager
    def slot(
        self, group: str | None, *, check_stop: Callable[[], None] | None = None
    ) -> Iterator[None]:
        """Hold one slot for the body; it is given back however the body ends."""
        self._acquire(group, check_stop)
        try:
            yield
        finally:
            with self._lock:
                self._free(group)

    def in_flight(self) -> dict[str | None, int]:
        """Calls in flight per group; a group with none has no entry."""
        with self._lock:
            return dict(self._in_flight)

    def waiting(self) -> int:
        """Callers queued for a slot and not yet granted one."""
        with self._lock:
            return len(self._waiters)

    def _acquire(self, group: str | None, check_stop: Callable[[], None] | None) -> None:
        with self._lock:
            if self._total < self._capacity and not self._waiters:
                self._take(group)
                return
            waiter = _Waiter(group, next(self._arrivals), threading.Condition(self._lock))
            self._waiters.append(waiter)
        try:
            while True:
                with self._lock:
                    if not waiter.granted:
                        waiter.wakeup.wait(self._wait_slice_seconds)
                    if waiter.granted:
                        return
                if check_stop is not None:
                    check_stop()
        except BaseException:
            with self._lock:
                if waiter.granted:
                    self._free(group)
                else:
                    self._waiters.remove(waiter)
            raise

    def _take(self, group: str | None) -> None:
        self._in_flight[group] = self._in_flight.get(group, 0) + 1
        self._total += 1

    def _free(self, group: str | None) -> None:
        """Give back one of *group*'s slots and grant what is free. Caller holds the lock."""
        remaining = self._in_flight[group] - 1
        if remaining:
            self._in_flight[group] = remaining
        else:
            del self._in_flight[group]
        self._total -= 1
        while self._waiters and self._total < self._capacity:
            waiter = min(self._waiters, key=lambda w: (self._in_flight.get(w.group, 0), w.arrival))
            self._waiters.remove(waiter)
            self._take(waiter.group)
            waiter.granted = True
            waiter.wakeup.notify()


@lru_cache(maxsize=1)
def get_model_call_limiter() -> FairCallLimiter:
    """The process's model-call limiter, sized by ``model_call_concurrency()``."""
    return FairCallLimiter(model_call_concurrency())


def current_call_group() -> str | None:
    """The limiter group of a call made here: the current turn's chat request id."""
    from src.services.graph.event_emitter import get_chat_request_id

    return get_chat_request_id()


# --------------------------------------------------------------------------- stop check

#: How long one answer to "was this turn stopped?" is reused for the same turn.
STOP_CHECK_INTERVAL_SECONDS = 2.0
# Answers older than this are dropped when a new one is stored.
_STOP_CHECK_RETENTION_SECONDS = 60.0

# request id -> (when it was asked, whether the turn was stopped).  Read and written by
# every slide thread, so guarded by its own lock; the query itself runs outside it.
_stop_checks: dict[str, tuple[float, bool]] = {}
_stop_checks_lock = threading.Lock()


def check_turn_stopped(
    request_id: str | None = None, *, clock: Callable[[], float] = time.monotonic
) -> None:
    """Raise ``TurnFencedError`` if the turn has ended; an answer is reused for a while.

    *request_id* defaults to ``current_call_group()``; no id means no turn, and no
    query.  Otherwise the answer of ``generation_fence.raise_if_turn_ended`` is reused
    for that turn for ``STOP_CHECK_INTERVAL_SECONDS``, a stop as well as a live answer.
    The query runs outside the cache's lock, so a slow read holds up only its caller.
    """
    rid = request_id or current_call_group()
    if rid is None:
        return
    from src.services.generation_fence import TurnFencedError, raise_if_turn_ended

    now = clock()
    with _stop_checks_lock:
        cached = _stop_checks.get(rid)
    if cached is not None and now - cached[0] < STOP_CHECK_INTERVAL_SECONDS:
        if cached[1]:
            # A fresh error per raise: one object raised on many threads shares a traceback.
            raise TurnFencedError(rid)
        return
    try:
        raise_if_turn_ended(rid)
    except TurnFencedError:
        _remember_stop_check(rid, now, stopped=True)
        raise
    _remember_stop_check(rid, now, stopped=False)


def _remember_stop_check(rid: str, now: float, *, stopped: bool) -> None:
    with _stop_checks_lock:
        for key in [
            key
            for key, (asked_at, _) in _stop_checks.items()
            if now - asked_at > _STOP_CHECK_RETENTION_SECONDS
        ]:
            del _stop_checks[key]
        previous = _stop_checks.get(rid)
        # Two threads can ask at once; the answer to the later question wins.
        if previous is None or previous[0] <= now:
            _stop_checks[rid] = (now, stopped)


def reset_stop_checks() -> None:
    """Forget every cached stop-check answer."""
    with _stop_checks_lock:
        _stop_checks.clear()


# --------------------------------------------------------------------------- deadline

# The turn's hard deadline, a ``time.monotonic()`` value; ``None`` outside a turn.
_turn_deadline_var: ContextVar[float | None] = ContextVar("model_call_turn_deadline", default=None)


def set_turn_deadline(deadline: float | None) -> None:
    """Set the current context's turn deadline (a ``time.monotonic()`` value, or ``None``)."""
    _turn_deadline_var.set(deadline)


def turn_deadline() -> float | None:
    """The current context's turn deadline, or ``None``."""
    return _turn_deadline_var.get()
