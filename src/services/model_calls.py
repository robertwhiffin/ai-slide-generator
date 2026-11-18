"""Model calls: the fault kinds, the limiter, the stop check, the deadline, the retries.

- ``model_fault_kind`` names the provider fault behind a failed call.
- ``FairCallLimiter`` caps the model calls in flight in one process
  (``get_model_call_limiter``, sized by ``TELLR_MODEL_CALL_CONCURRENCY``).  A freed slot
  goes to the waiting turn with the fewest calls in flight.
- ``check_turn_stopped`` asks whether the current turn was stopped, reusing an answer per
  turn for ``STOP_CHECK_INTERVAL_SECONDS``.
- ``set_turn_deadline`` / ``turn_deadline`` carry the turn's hard deadline in a
  ``ContextVar``.

- ``call_model`` owns the retries: it runs a call under the limiter and retries a transient
  fault with jittered, ``Retry-After``-aware backoff (``RetryPolicy``), never past the
  turn's deadline and never after the turn was stopped.

It must never import ``src.services.agent_runtime``: the runtime imports this module.
``generation_fence`` and ``graph.event_emitter`` are imported inside the functions that
use them.
"""

from __future__ import annotations

import email.utils
import itertools
import logging
import math
import os
import random
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import timezone
from functools import lru_cache
from typing import Literal, TypeVar

import httpx
import openai
import requests
from databricks.sdk.errors import Aborted, DeadlineExceeded, InternalError

logger = logging.getLogger(__name__)

T = TypeVar("T")

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
# default keeps the app-wide ceiling at about 40 calls, below the ~60 that one job
# runner each allowed.  Set by the 2026-11-18 devloop load test: at 15, an 8-deck
# burst drew 290 Gateway 429s and 4 of 7 turns gave up on rate_limited.
MODEL_CALL_CONCURRENCY_ENV = "TELLR_MODEL_CALL_CONCURRENCY"
DEFAULT_MODEL_CALL_CONCURRENCY = 10
MAX_MODEL_CALL_CONCURRENCY = 64


def model_call_concurrency() -> int:
    """Model calls in flight per process, from ``TELLR_MODEL_CALL_CONCURRENCY``.

    Default 10, max 64; an unusable value logs a warning and falls back to the default.
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


# --------------------------------------------------------------------------- retries


@dataclass(frozen=True)
class RetryPolicy:
    """How a transient fault is retried.

    - ``base_seconds``: the cap of the first wait; it doubles with each failure.
    - ``max_wait_seconds``: the cap of one backed-off wait (a ``Retry-After`` hint is not
      capped by it).
    - ``budget_seconds``: how long retrying may go on, counted from the first failure.
    """

    base_seconds: float = 2.0
    max_wait_seconds: float = 30.0
    budget_seconds: float = 150.0


DEFAULT_RETRY_POLICY = RetryPolicy()

# A backoff sleeps in slices of at most this long, so a stop is noticed within one.
_SLEEP_SLICE_SECONDS = 1.0


def _usable_seconds(value: float) -> float | None:
    return value if math.isfinite(value) and value >= 0 else None


def retry_after_seconds(
    error: BaseException, *, now: Callable[[], float] = time.time
) -> float | None:
    """The wait the provider asked for, in seconds, or ``None``.

    Reads the first ``openai.APIStatusError`` on the ``__cause__ or __context__`` chain:
    ``retry-after-ms`` (milliseconds), else ``retry-after`` as seconds or an HTTP-date
    (a zone-less date is UTC).  An unusable ``retry-after-ms`` falls through to
    ``retry-after``; a negative or non-finite result is ``None``.
    """
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, openai.APIStatusError):
            break
        current = current.__cause__ or current.__context__
    else:
        return None
    headers = current.response.headers

    raw_ms = headers.get("retry-after-ms")
    if raw_ms is not None:
        try:
            ms = _usable_seconds(float(raw_ms))
        except ValueError:
            ms = None
        if ms is not None:
            return ms / 1000.0

    raw = headers.get("retry-after")
    if raw is None:
        return None
    try:
        return _usable_seconds(float(raw))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return _usable_seconds(when.timestamp() - now())


def call_model(
    fn: Callable[[], T],
    *,
    agent_key: str,
    policy: RetryPolicy | None = DEFAULT_RETRY_POLICY,
    limiter: FairCallLimiter | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    rand: Callable[[], float] = random.random,
) -> T:
    """Run *fn*, a model call, retrying a transient fault; the one place retries live.

    - The turn's stop check runs before every attempt, whatever the policy.  With a
      *limiter*, *fn* runs holding one slot of ``current_call_group()``.
    - ``TurnFencedError``, a non-transient error, and every error when *policy* is
      ``None`` propagate at once.
    - After the n-th transient failure the wait is the backoff ``cap * (0.5 + 0.5 * r)``
      with ``cap = min(max_wait_seconds, base_seconds * 2 ** (n - 1))`` and ``r = rand()``.
      A ``Retry-After`` from the provider is a floor: the wait is then
      ``max(hint * (1 + 0.25 * r), backoff)``, so a longer hint is waited in full,
      jittered upwards, and a shorter or zero one never makes the retry sooner.
    - The original error is re-raised when the wait would run past ``budget_seconds``
      (counted from the first failure) or reach the turn's deadline.
    - The wait is slept outside the limiter's slot, in slices, with a stop check after each.
    """
    from src.services.generation_fence import TurnFencedError

    entered = clock()
    first_failure: float | None = None
    attempt = 0
    while True:
        check_turn_stopped()
        attempt += 1
        try:
            if limiter is None:
                return fn()
            with limiter.slot(current_call_group(), check_stop=check_turn_stopped):
                return fn()
        except TurnFencedError:
            raise
        except Exception as error:
            if policy is None:
                raise
            kind = model_fault_kind(error)
            if kind not in TRANSIENT_FAULT_KINDS:
                raise
            now = clock()
            if first_failure is None:
                first_failure = now
            # One draw for both terms.  A hint is a floor, never a replacement: a 0 or
            # tiny Retry-After still waits the jittered backoff, so slides do not retry
            # in lockstep.
            r = rand()
            cap = min(policy.max_wait_seconds, policy.base_seconds * 2 ** (attempt - 1))
            wait = cap * (0.5 + 0.5 * r)
            hint = retry_after_seconds(error)
            if hint is not None:
                wait = max(hint * (1 + 0.25 * r), wait)
            deadline = turn_deadline()
            if now - first_failure + wait > policy.budget_seconds or (
                deadline is not None and now + wait >= deadline
            ):
                logger.warning(
                    "model_call_gave_up agent=%s fault=%s attempts=%d elapsed_s=%.1f request_id=%s",
                    agent_key,
                    kind,
                    attempt,
                    now - entered,
                    current_call_group(),
                )
                raise
            logger.warning(
                "model_call_retry agent=%s fault=%s attempt=%d wait_s=%.1f request_id=%s",
                agent_key,
                kind,
                attempt,
                wait,
                current_call_group(),
            )
        # Outside the except block, so a stop raised here does not carry the fault as its
        # __context__.
        remaining = wait
        while remaining > 0:
            step = min(_SLEEP_SLICE_SECONDS, remaining)
            sleep(step)
            remaining -= step
            check_turn_stopped()
