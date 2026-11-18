"""``call_model``: the one place that retries a transient model fault.

``call_model(fn, *, agent_key, policy, limiter, sleep, clock, rand)`` checks for a stop before
every attempt and runs ``fn`` inside one limiter slot of the current turn's group.  A
``TurnFencedError``, a non-transient error, and every error when ``policy is None``, propagate
at once.  After the n-th transient failure it waits ``cap * (0.5 + 0.5 * rand())`` with
``cap = min(max_wait_seconds, base_seconds * 2 ** (n - 1))``; when the error carries a
``Retry-After``, the hint is a floor: the wait is the longer of that backoff and
``hint * (1 + 0.25 * rand())``, from one ``rand()`` draw (F1).  It re-raises the last attempt's
own error when that wait would take it past the retry budget (counted from the first
transient failure, R1) or reach the turn's deadline.  It sleeps in slices of at most 1 s,
outside the ``except`` block and outside the slot, checking for a stop after each.

Conventions:

- Time is a ``_FakeTime``: ``clock`` reads it and ``sleep`` advances it, so no test sleeps
  for real on the call path.  It starts at ``ORIGIN`` (not 0), so a budget or deadline taken
  from the wrong reference shows.  ``rand`` is injected in every call.
- Errors are built as in ``test_model_fault_kind.py``; headers go through
  ``httpx.Response(code, headers=...)``.  Every attempt raises a fresh error object, so a
  test can tell *which* one was re-raised.
- Stop scenarios patch ``src.services.model_calls.check_turn_stopped`` (C7).  An autouse
  fixture makes the real stop query (``generation_fence.raise_if_turn_ended``, C3) fail
  loudly, so a ``call_model`` that bound the real check at import time fails instead of
  touching a database.
- A runaway retry loop raises ``_Runaway`` (a ``BaseException``, which no ``except
  Exception`` catches) after ``MAX_CALLS`` attempts or ``MAX_SLICES`` sleeps, so a broken
  budget fails a test instead of hanging the run.
- Tests that use a real ``FairCallLimiter`` run ``call_model`` on a daemon thread with a
  10 ms slice and a bounded join; ``threading.Event`` handshakes order the threads and no
  assertion relies on a sleep.  A limiter that leaked a slot fails the join, not the run.
- The turn (chat request id and deadline) is set inside ``contextvars.copy_context().run``
  or on a fresh thread, so nothing leaks into the next test (R9).
- The autouse stop-check cache reset lives in ``tests/conftest.py``; none is added here.
"""

from __future__ import annotations

import contextvars
import dataclasses
import email.utils
import inspect
import logging
import os
import random
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from itertools import pairwise

import httpx
import openai
import pytest
from databricks.sdk.errors import InternalError
from langchain_core.exceptions import OutputParserException

from src.services.agent_runtime import ModelProviderUnavailableError
from src.services.generation_fence import TurnFencedError
from src.services.graph.event_emitter import set_chat_request_id
from src.services.model_calls import (
    DEFAULT_RETRY_POLICY,
    FairCallLimiter,
    RetryPolicy,
    call_model,
    model_fault_kind,
    retry_after_seconds,
    set_turn_deadline,
)
from src.services.persisted_graph_release import PinnedInvocationEndpointError
from tests.unit.test_model_fault_kind import _cycle, _within

#: What every stop scenario patches (C7): ``call_model`` must read it at call time.
CHECK = "src.services.model_calls.check_turn_stopped"
#: The real stop query behind ``check_turn_stopped`` (C3); it must never run here.
FENCE = "src.services.generation_fence.raise_if_turn_ended"
LOGGER = "src.services.model_calls"

AGENT = "builder"
RID = "req-retry"
#: Where the fake clock starts.
ORIGIN = 1000.0
#: An epoch second for ``retry_after_seconds(..., now=...)``: 2025-11-17 17:20:00 UTC.
NOW = 1_763_400_000.0

#: ``wait_slice_seconds`` for every limiter built here.
SLICE = 0.01
#: The bound on every wait, join and poll.
TIMEOUT = 5.0
#: A call that gets this far is not going to stop by itself.
MAX_CALLS = 200
MAX_SLICES = 20_000


# --------------------------------------------------------------------------- helpers


class _Runaway(BaseException):
    """Ends a retry loop that never stops: no ``except Exception`` catches it."""


class _FakeTime:
    """A stand-in for ``time.monotonic`` and ``time.sleep``: sleeping advances the clock.

    ``slices`` records every sleep; ``events`` is the shared, ordered log of the stop
    checks, the attempts and the sleeps.
    """

    def __init__(self) -> None:
        self.now = ORIGIN
        self.slices: list[float] = []
        self.events: list[tuple[str, float]] = []

    def clock(self) -> float:
        return self.now

    @property
    def elapsed(self) -> float:
        return self.now - ORIGIN

    def sleep(self, seconds: float) -> None:
        if len(self.slices) >= MAX_SLICES:
            raise _Runaway(f"slept {len(self.slices)} times; the call never stopped retrying")
        self.slices.append(seconds)
        self.events.append(("sleep", seconds))
        self.now += seconds


class _Fail:
    """An outcome of ``_Model``: raise a fresh error built by *make*."""

    def __init__(self, make: Callable[[], BaseException]):
        self.make = make


class _Model:
    """Stands in for ``fn``: plays *outcomes* in order, repeating the last one forever.

    An outcome is a ``_Fail`` (raise a fresh error) or a value (return it).  ``calls`` is the
    fake time each attempt started at (relative to ``ORIGIN``), ``raised`` every error raised,
    in order.  *durations* advance the fake clock during the first attempts; *inside* runs
    during every attempt.
    """

    def __init__(
        self,
        fake: _FakeTime,
        *outcomes: object,
        durations: tuple[float, ...] = (),
        inside: Callable[[], None] | None = None,
    ):
        assert outcomes, "a model needs at least one outcome"
        self.fake = fake
        self.outcomes = outcomes
        self.durations = durations
        self.inside = inside
        self.calls: list[float] = []
        self.raised: list[BaseException] = []

    def __call__(self) -> object:
        if len(self.calls) >= MAX_CALLS:
            raise _Runaway(f"{len(self.calls)} attempts; the call never stopped retrying")
        index = len(self.calls)
        self.calls.append(self.fake.elapsed)
        self.fake.events.append(("call", self.fake.elapsed))
        if self.inside is not None:
            self.inside()
        if index < len(self.durations):
            self.fake.now += self.durations[index]
        outcome = self.outcomes[min(index, len(self.outcomes) - 1)]
        if isinstance(outcome, _Fail):
            error = outcome.make()
            self.raised.append(error)
            raise error
        return outcome

    @property
    def gaps(self) -> list[float]:
        return [later - earlier for earlier, later in pairwise(self.calls)]


class _StopCheck:
    """Stands in for ``model_calls.check_turn_stopped``.

    Records the fake time of every check and raises a fresh ``TurnFencedError`` once the
    clock has reached *stop_at* (relative to ``ORIGIN``); ``None`` means the turn is live.
    """

    def __init__(self, fake: _FakeTime, stop_at: float | None = None):
        self.fake = fake
        self.stop_at = stop_at
        self.times: list[float] = []
        self.raised: list[TurnFencedError] = []

    def __call__(self, request_id: str | None = None) -> None:
        self.times.append(self.fake.elapsed)
        self.fake.events.append(("check", self.fake.elapsed))
        if self.stop_at is not None and self.fake.elapsed >= self.stop_at:
            error = TurnFencedError(RID)
            self.raised.append(error)
            raise error


class _StopWhen:
    """A thread-safe stop check: live until *stop* is set, then raises a fresh error."""

    def __init__(self) -> None:
        self.stop = threading.Event()
        self.raised: list[TurnFencedError] = []

    def __call__(self, request_id: str | None = None) -> None:
        if self.stop.is_set():
            error = TurnFencedError(RID)
            self.raised.append(error)
            raise error


def _request() -> httpx.Request:
    return httpx.Request("POST", "http://x")


def _status(code: int, headers: dict[str, str] | None = None) -> openai.APIStatusError:
    return openai.APIStatusError(
        "status",
        response=httpx.Response(code, headers=headers or {}, request=_request()),
        body=None,
    )


def _raised_from(outer: BaseException, cause: BaseException) -> BaseException:
    """*outer* as caught after ``raise outer from cause``."""
    try:
        try:
            raise cause
        except BaseException as inner:
            raise outer from inner
    except BaseException as caught:
        return caught


def _raised_while_handling(outer: BaseException, context: BaseException) -> BaseException:
    """*outer* raised while handling *context*, with no ``from``: only ``__context__``."""
    try:
        try:
            raise context
        except BaseException:
            raise outer  # noqa: B904 - the point
    except BaseException as caught:
        assert caught.__cause__ is None and caught.__context__ is context
        return caught


def _pinned(cause: BaseException) -> BaseException:
    """The production collapse: pinned error from unavailable error from *cause*."""
    pinned = PinnedInvocationEndpointError(
        endpoint_name="databricks-claude", graph_release_id=1, agent_definition_revision_id=2
    )
    return _raised_from(pinned, _raised_from(ModelProviderUnavailableError("gone"), cause))


def _in_turn(body: Callable[[], object], *, rid: str | None = RID, deadline: float | None = None):
    """Run *body* in a copy of this context with the turn's request id and deadline set."""

    def run() -> object:
        set_chat_request_id(rid)
        set_turn_deadline(deadline)
        return body()

    return contextvars.copy_context().run(run)


def _call(
    model: _Model, fake: _FakeTime, *, rand: float, deadline: float | None = None, **kwargs
) -> object:
    """``call_model`` with the fake clock and a constant ``rand``, inside the turn ``RID``.

    *deadline* is the turn's (an absolute fake-clock reading); *kwargs* go to ``call_model``.
    """
    kwargs.setdefault("agent_key", AGENT)
    return _in_turn(
        lambda: call_model(model, sleep=fake.sleep, clock=fake.clock, rand=lambda: rand, **kwargs),
        deadline=deadline,
    )


def _lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The ``model_call_*`` lines logged, in order; each must be a WARNING."""
    records = [
        record
        for record in caplog.records
        if record.name == LOGGER and record.getMessage().startswith("model_call_")
    ]
    assert all(record.levelno == logging.WARNING for record in records), [
        (record.levelname, record.getMessage()) for record in records
    ]
    return [record.getMessage() for record in records]


def _retry_line(fault: str, attempt: int, wait: str, rid: str = RID) -> str:
    return (
        f"model_call_retry agent={AGENT} fault={fault} attempt={attempt} "
        f"wait_s={wait} request_id={rid}"
    )


def _gave_up_line(fault: str, attempts: int, elapsed: str, rid: str = RID) -> str:
    return (
        f"model_call_gave_up agent={AGENT} fault={fault} attempts={attempts} "
        f"elapsed_s={elapsed} request_id={rid}"
    )


def _wait_until(predicate: Callable[[], bool], timeout: float = TIMEOUT) -> bool:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.001)
    return True


class _Thread:
    """Run *body* on a daemon thread; keep its result or the exception it raised."""

    def __init__(self, body: Callable[[], object], name: str = "call-model"):
        self.result: object = None
        self.error: BaseException | None = None
        self._body = body
        self.thread = threading.Thread(target=self._run, name=name, daemon=True)

    def _run(self) -> None:
        try:
            self.result = self._body()
        except BaseException as exc:  # noqa: BLE001 - kept and asserted on by the test
            self.error = exc

    def start(self) -> _Thread:
        self.thread.start()
        return self

    def join(self) -> _Thread:
        self.thread.join(TIMEOUT)
        assert not self.thread.is_alive(), f"{self.thread.name} did not finish in {TIMEOUT}s"
        return self


def _on_thread(body: Callable[[], object], *, rid: str | None = RID) -> _Thread:
    """Run *body* to the end on a fresh daemon thread whose turn is *rid*."""

    def run() -> object:
        set_chat_request_id(rid)
        return body()

    return _Thread(run).start().join()


class _Holder:
    """A caller on another thread that holds one slot of *limiter* until ``finish``."""

    def __init__(self, limiter: FairCallLimiter, group: str):
        self.entered = threading.Event()
        self.release = threading.Event()

        def hold() -> None:
            with limiter.slot(group):
                self.entered.set()
                if not self.release.wait(TIMEOUT):
                    raise AssertionError("the holder was never released")

        self.worker = _Thread(hold, name=f"holder-{group}").start()
        assert self.entered.wait(TIMEOUT), "the holder did not get the free slot"

    def finish(self) -> None:
        self.release.set()
        self.worker.join()
        assert self.worker.error is None, repr(self.worker.error)


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def no_real_stop_query(monkeypatch):
    """Every test stands in for the stop check, so the real query must never run (C7)."""

    def refuse(request_id: str | None = None) -> None:
        raise AssertionError(
            f"the real stop query ran for {request_id!r}: call_model must look up "
            "check_turn_stopped at call time"
        )

    monkeypatch.setattr(FENCE, refuse)


@pytest.fixture
def fake() -> _FakeTime:
    return _FakeTime()


@pytest.fixture
def stops(monkeypatch, fake) -> _StopCheck:
    """A live stop check, patched in for ``call_model``; set ``stop_at`` to stop the turn."""
    check = _StopCheck(fake)
    monkeypatch.setattr(CHECK, check)
    return check


@pytest.fixture
def local_time_not_utc():
    """Run with local time at UTC+5:30, so a zone-less date read as local time shows."""
    if not hasattr(time, "tzset"):
        pytest.skip("time.tzset is POSIX-only")
    saved = os.environ.get("TZ")
    os.environ["TZ"] = "TLR-5:30"
    time.tzset()
    try:
        assert time.timezone == -19800, "the local zone did not change"
        yield
    finally:
        if saved is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = saved
        time.tzset()


# --------------------------------------------------------------------------- the interface


def test_the_retry_policy_its_defaults_and_the_signatures():
    assert [field.name for field in dataclasses.fields(RetryPolicy)] == [
        "base_seconds",
        "max_wait_seconds",
        "budget_seconds",
    ]
    assert RetryPolicy() == RetryPolicy(2.0, 30.0, 150.0)
    assert DEFAULT_RETRY_POLICY == RetryPolicy()
    with pytest.raises(dataclasses.FrozenInstanceError):
        DEFAULT_RETRY_POLICY.budget_seconds = 1.0  # type: ignore[misc]

    params = inspect.signature(call_model).parameters
    assert list(params) == ["fn", "agent_key", "policy", "limiter", "sleep", "clock", "rand"]
    assert params["fn"].kind in (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    )
    keyword_only = ["agent_key", "policy", "limiter", "sleep", "clock", "rand"]
    assert [params[name].kind for name in keyword_only] == [inspect.Parameter.KEYWORD_ONLY] * 6
    assert params["agent_key"].default is inspect.Parameter.empty
    assert params["policy"].default is DEFAULT_RETRY_POLICY
    assert params["limiter"].default is None
    assert params["sleep"].default is time.sleep
    assert params["clock"].default is time.monotonic
    assert params["rand"].default is random.random

    retry_after = inspect.signature(retry_after_seconds).parameters
    assert list(retry_after) == ["error", "now"]
    assert retry_after["now"].kind is inspect.Parameter.KEYWORD_ONLY
    assert retry_after["now"].default is time.time


# --------------------------------------------------------------------------- the plan's list


def test_a_success_is_returned_without_waiting(fake, stops):
    answer = object()
    model = _Model(fake, answer)
    assert _call(model, fake, rand=1.0) is answer
    assert model.calls == [0.0]
    assert fake.slices == []


def test_a_rate_limit_is_retried_until_it_succeeds(fake, stops):
    model = _Model(fake, _Fail(lambda: _status(429)), _Fail(lambda: _status(429)), "ok")
    assert _call(model, fake, rand=0.0) == "ok"
    assert model.calls == [0.0, 1.0, 3.0]


def test_the_backoff_grows_and_is_capped(fake, stops):
    """C8: 9 calls, the last at exactly 150 s (``120 + 30 > 150`` is False)."""
    model = _Model(fake, _Fail(lambda: _status(503)))
    with pytest.raises(openai.APIStatusError) as raised:
        _call(model, fake, rand=1.0)
    assert model.gaps == pytest.approx([2, 4, 8, 16, 30, 30, 30, 30], abs=1e-9)
    assert model.calls == pytest.approx([0, 2, 6, 14, 30, 60, 90, 120, 150], abs=1e-9)
    assert len(model.raised) == 9
    # The last attempt's own error, not the first one's, nor a wrapper.
    assert raised.value is model.raised[-1]
    assert raised.value.status_code == 503
    assert all(0 < piece <= 1.0 for piece in fake.slices), max(fake.slices)
    assert sum(fake.slices) == pytest.approx(150.0, abs=1e-9)


@pytest.mark.parametrize(
    ("headers", "gap"),
    [
        pytest.param({"Retry-After": "7"}, 7.0, id="retry-after"),
        pytest.param({"retry-after-ms": "1500"}, 1.5, id="retry-after-ms"),
    ],
)
def test_retry_after_is_honoured(fake, stops, headers, gap):
    model = _Model(fake, _Fail(lambda: _status(429, headers)), "ok")
    assert _call(model, fake, rand=0.0) == "ok"
    assert model.gaps == pytest.approx([gap], abs=1e-9)


def test_a_retry_after_past_the_budget_fails_at_once(fake, stops):
    """Review Focus 1: a 600 s ``Retry-After`` fails the call now; it does not park the turn."""
    model = _Model(fake, _Fail(lambda: _status(429, {"Retry-After": "600"})), "ok")
    with pytest.raises(openai.APIStatusError) as raised:
        _call(model, fake, rand=0.0)
    assert model.calls == [0.0]
    assert fake.slices == []
    assert raised.value is model.raised[0]


@pytest.mark.parametrize(
    ("deadline_in", "calls"),
    [
        # The plan's case: at t=2 the next wait (4 s) would end at 6, past the deadline at 5.
        pytest.param(5.0, [0, 2], id="plan"),
        # ``>=``: a wait that would end exactly at the deadline is not started.
        pytest.param(6.0, [0, 2], id="a-wait-ending-on-the-deadline"),
        # A deadline far away leaves the budget in charge (the positive control).
        pytest.param(1000.0, [0, 2, 6, 14, 30, 60, 90, 120, 150], id="far-deadline"),
    ],
)
def test_it_never_waits_past_the_turn_deadline(fake, stops, deadline_in, calls):
    model = _Model(fake, _Fail(lambda: _status(503)))
    with pytest.raises(openai.APIStatusError) as raised:
        _call(model, fake, rand=1.0, deadline=fake.clock() + deadline_in)
    assert model.calls == pytest.approx(calls, abs=1e-9)
    assert raised.value is model.raised[-1]


@pytest.mark.parametrize(
    "make",
    [
        pytest.param(lambda: _status(400), id="400"),
        pytest.param(lambda: _status(401), id="401"),
        pytest.param(lambda: OutputParserException("no tool call"), id="OutputParserException"),
        pytest.param(lambda: ValueError("a bug"), id="ValueError"),
        pytest.param(lambda: ModelProviderUnavailableError("gone"), id="no-provider-cause"),
    ],
)
def test_a_non_transient_error_is_raised_at_once(fake, stops, make):
    model = _Model(fake, _Fail(make), "ok")
    with pytest.raises(type(make())) as raised:
        _call(model, fake, rand=0.0)
    assert model.calls == [0.0]
    assert fake.slices == []
    assert raised.value is model.raised[0]


@pytest.mark.parametrize(
    "make",
    [
        pytest.param(lambda: _status(429), id="429"),
        pytest.param(lambda: openai.APIConnectionError(request=_request()), id="connection"),
    ],
)
def test_no_policy_means_one_attempt(fake, stops, make):
    model = _Model(fake, _Fail(make), "ok")
    with pytest.raises(type(make())) as raised:
        _call(model, fake, rand=0.0, policy=None)
    assert model.calls == [0.0]
    assert fake.slices == []
    assert raised.value is model.raised[0]


def test_a_stop_during_a_backoff_ends_the_call(fake, stops):
    """The first wait is 2 s; the turn is stopped once the clock passes the first slice."""
    stops.stop_at = 1.0
    model = _Model(fake, _Fail(lambda: _status(503)), "ok")
    with pytest.raises(TurnFencedError) as raised:
        _call(model, fake, rand=1.0)
    assert model.calls == [0.0]
    # Noticed after a slice, before the 2 s wait was over: not only at the next attempt.
    assert 1.0 <= fake.elapsed < 2.0
    assert raised.value is stops.raised[0]


def test_the_slot_is_not_held_while_waiting(monkeypatch, fake):
    """C8: record ``in_flight()`` inside the fake sleep, and assert after the call."""
    monkeypatch.setattr(CHECK, _StopWhen())
    limiter = FairCallLimiter(1, wait_slice_seconds=SLICE)
    during_attempts: list[dict] = []
    during_sleeps: list[dict] = []

    def sleep(seconds: float) -> None:
        during_sleeps.append(limiter.in_flight())
        fake.sleep(seconds)

    model = _Model(
        fake,
        _Fail(lambda: _status(503)),
        _Fail(lambda: _status(503)),
        "ok",
        inside=lambda: during_attempts.append(limiter.in_flight()),
    )
    worker = _on_thread(
        lambda: call_model(
            model, agent_key=AGENT, limiter=limiter, sleep=sleep, clock=fake.clock, rand=lambda: 1.0
        )
    )
    assert worker.error is None, repr(worker.error)
    assert worker.result == "ok"
    # The positive control: each attempt held the turn's slot ...
    assert during_attempts == [{RID: 1}] * 3
    # ... and no slice of the 2 s and 4 s waits did.
    assert sum(fake.slices) == pytest.approx(6.0, abs=1e-9)
    assert during_sleeps == [{}] * len(fake.slices)
    assert limiter.in_flight() == {}


def test_each_retry_logs_one_line_with_its_fields_in_the_message(fake, stops, caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    model = _Model(fake, _Fail(lambda: _status(429)), "ok")
    assert _call(model, fake, rand=0.0) == "ok"
    assert _lines(caplog) == [_retry_line("rate_limited", 1, "1.0")]
    assert "model_call_retry agent=builder fault=rate_limited attempt=1" in _lines(caplog)[0]


def _date(epoch: float) -> str:
    """*epoch* as an HTTP-date in GMT."""
    return email.utils.format_datetime(datetime.fromtimestamp(epoch, tz=timezone.utc), usegmt=True)


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        pytest.param({"retry-after": "7"}, 7.0, id="seconds"),
        pytest.param({"Retry-After": "7"}, 7.0, id="seconds-as-a-server-spells-it"),
        pytest.param({"retry-after": "2.5"}, 2.5, id="float-seconds"),
        pytest.param({"retry-after": "0"}, 0.0, id="zero"),
        pytest.param({"retry-after-ms": "1500"}, 1.5, id="ms"),
        pytest.param({"retry-after-ms": "1500", "retry-after": "7"}, 1.5, id="ms-first"),
        pytest.param(
            {"retry-after-ms": "soon", "retry-after": "7"}, 7.0, id="ms-garbage-falls-through"
        ),
        pytest.param({"retry-after": _date(NOW + 10)}, 10.0, id="http-date"),
        pytest.param({"retry-after": _date(NOW - 10)}, None, id="http-date-in-the-past"),
        pytest.param({"retry-after": "soon"}, None, id="garbage"),
        pytest.param({"retry-after": ""}, None, id="empty"),
        pytest.param({"retry-after": "-3"}, None, id="negative"),
        pytest.param({"retry-after": "nan"}, None, id="nan"),
        pytest.param({"retry-after": "inf"}, None, id="inf"),
        pytest.param({"retry-after-ms": "soon"}, None, id="ms-garbage-alone"),
        pytest.param({"retry-after-ms": "-5"}, None, id="ms-negative-alone"),
        pytest.param({"retry-after-ms": "nan"}, None, id="ms-nan-alone"),
        pytest.param({}, None, id="absent"),
    ],
)
def test_retry_after_parsing(headers, expected):
    hint = retry_after_seconds(_status(429, headers), now=lambda: NOW)
    if expected is None:
        assert hint is None
    else:
        assert type(hint) is float
        assert hint == pytest.approx(expected, abs=1e-9)


# --------------------------------------------------------------------------- R5: parsing


def test_a_zoneless_http_date_is_utc(local_time_not_utc):
    """``-0000`` parses to a naive datetime; it is UTC, not local time (R5)."""
    header = email.utils.formatdate(NOW + 10, localtime=False, usegmt=False)
    assert header.endswith("-0000")
    assert email.utils.parsedate_to_datetime(header).tzinfo is None
    assert retry_after_seconds(_status(429, {"Retry-After": header}), now=lambda: NOW) == 10.0


@pytest.mark.parametrize(
    ("make", "expected"),
    [
        pytest.param(lambda: _status(429, {"Retry-After": "7"}), 7.0, id="bare"),
        pytest.param(
            lambda: _raised_from(
                ModelProviderUnavailableError("gone"), _status(429, {"Retry-After": "7"})
            ),
            7.0,
            id="a-chained-cause",
        ),
        pytest.param(
            lambda: _raised_while_handling(
                ModelProviderUnavailableError("gone"), _status(429, {"Retry-After": "7"})
            ),
            7.0,
            id="an-implicit-context",
        ),
        pytest.param(
            lambda: _pinned(_status(429, {"Retry-After": "7"})), 7.0, id="the-pinned-collapse"
        ),
        pytest.param(
            lambda: _raised_from(TimeoutError(), _status(429, {"Retry-After": "7"})),
            7.0,
            id="behind-a-link-that-is-not-a-status-error",
        ),
        pytest.param(
            lambda: _raised_from(_status(503), _status(429, {"Retry-After": "7"})),
            None,
            id="only-the-first-status-error-is-read",
        ),
        pytest.param(lambda: ValueError("no response"), None, id="no-status-error"),
        pytest.param(lambda: openai.APIConnectionError(request=_request()), None, id="no-response"),
    ],
)
def test_the_header_is_read_off_the_first_status_error_on_the_chain(make, expected):
    assert retry_after_seconds(make(), now=lambda: NOW) == expected


def test_a_cyclic_chain_has_no_retry_after():
    error = _cycle()
    assert error.__cause__.__context__ is error
    assert _within(2.0, lambda e: retry_after_seconds(e, now=lambda: NOW), error) is None


# --------------------------------------------------------------------------- the numbers


def test_a_policy_s_own_numbers_are_used(fake, stops):
    policy = RetryPolicy(base_seconds=1.0, max_wait_seconds=4.0, budget_seconds=10.0)
    model = _Model(fake, _Fail(lambda: _status(503)))
    with pytest.raises(openai.APIStatusError):
        _call(model, fake, rand=1.0, policy=policy)
    # Waits 1, 2, 4; the next (4 s at t=7) would end past the 10 s budget.
    assert model.calls == pytest.approx([0, 1, 3, 7], abs=1e-9)


@pytest.mark.parametrize(
    ("rand", "gaps"),
    [
        # cap * 0.5: the shortest wait is half the cap, never zero (R4: not full jitter).
        pytest.param(0.0, [1, 2, 4, 8] + [15] * 9, id="rand-0"),
        pytest.param(0.5, [1.5, 3, 6, 12] + [22.5] * 5, id="rand-0.5"),
    ],
)
def test_the_no_hint_jitter_spans_half_to_the_whole_cap(fake, stops, rand, gaps):
    model = _Model(fake, _Fail(lambda: _status(503)))
    with pytest.raises(openai.APIStatusError):
        _call(model, fake, rand=rand)
    assert model.gaps == pytest.approx(gaps, abs=1e-9)


@pytest.mark.parametrize(
    ("headers", "rand", "gap"),
    [
        pytest.param({"Retry-After": "7"}, 1.0, 8.75, id="retry-after-rand-1"),
        pytest.param({"Retry-After": "7"}, 0.5, 7.875, id="retry-after-rand-0.5"),
        # max(1.5 * 1.25, 2.0 * 1.0): the 1.875 s hint is below the 2 s backoff (F1).
        pytest.param({"retry-after-ms": "1500"}, 1.0, 2.0, id="retry-after-ms-rand-1"),
        pytest.param({"retry-after-ms": "5000"}, 1.0, 6.25, id="retry-after-ms-above-the-backoff"),
    ],
)
def test_a_retry_after_is_jittered_upwards(fake, stops, headers, rand, gap):
    """``max(hint * (1 + 0.25 * rand()), backoff)`` (R4, F1): never earlier than the server
    asked, and never earlier than the backoff."""
    model = _Model(fake, _Fail(lambda: _status(429, headers)), "ok")
    assert _call(model, fake, rand=rand) == "ok"
    assert model.gaps == pytest.approx([gap], abs=1e-9)


def test_a_retry_after_above_the_per_wait_cap_is_honoured(fake, stops):
    """The 30 s cap shapes the exponential waits; a server's 45 s is waited in full."""
    model = _Model(fake, _Fail(lambda: _status(429, {"Retry-After": "45"})), "ok")
    assert _call(model, fake, rand=0.0) == "ok"
    assert model.gaps == pytest.approx([45.0], abs=1e-9)


@pytest.mark.parametrize(
    ("rand", "wait"),
    [pytest.param(0.0, 1.0, id="rand-0"), pytest.param(1.0, 2.0, id="rand-1")],
)
def test_a_retry_after_of_zero_waits_the_backoff(fake, stops, caplog, rand, wait):
    """``0`` still parses as a hint (R5), but a hint is a floor, not a replacement (F1).

    The first wait is the 2 s cap's backoff, ``2 * (0.5 + 0.5 * rand)``: never 0.
    """
    caplog.set_level(logging.WARNING, logger=LOGGER)
    model = _Model(fake, _Fail(lambda: _status(429, {"Retry-After": "0"})), "ok")
    assert _call(model, fake, rand=rand) == "ok"
    assert model.calls == pytest.approx([0.0, wait], abs=1e-9)
    assert _lines(caplog) == [_retry_line("rate_limited", 1, f"{wait:.1f}")]


@pytest.mark.parametrize(
    ("outcomes", "gaps"),
    [
        # 50 ms at the first failure: the 1 s backoff (2 s cap, rand 0) wins.
        pytest.param(
            (_Fail(lambda: _status(429, {"retry-after-ms": "50"})), "ok"),
            [1.0],
            id="retry-after-ms-50-at-attempt-1",
        ),
        # 1 s at the third failure: the 4 s backoff (8 s cap, rand 0) wins.
        pytest.param(
            (
                _Fail(lambda: _status(503)),
                _Fail(lambda: _status(503)),
                _Fail(lambda: _status(429, {"retry-after": "1"})),
                "ok",
            ),
            [1.0, 2.0, 4.0],
            id="retry-after-1-at-attempt-3",
        ),
    ],
)
def test_a_retry_after_below_the_backoff_waits_the_backoff(fake, stops, outcomes, gaps):
    """A small hint never makes a call retry sooner than its own backoff (F1)."""
    model = _Model(fake, *outcomes)
    assert _call(model, fake, rand=0.0) == "ok"
    assert model.gaps == pytest.approx(gaps, abs=1e-9)


def test_slides_rate_limited_with_a_zero_retry_after_spread_their_retries(monkeypatch):
    """No lockstep (F1): one ``rand()`` per slide spreads the slides' first waits.

    Each slide is its own call with its own clock, as a turn's slides run side by side;
    under a replacing hint every one of them waited exactly 0.
    """
    monkeypatch.setattr(CHECK, _StopWhen())
    draws = [0.0, 0.25, 0.5, 0.75, 1.0]
    waits: list[float] = []
    for draw in draws:
        slide = _FakeTime()
        model = _Model(slide, _Fail(lambda: _status(429, {"Retry-After": "0"})), "ok")
        assert _call(model, slide, rand=draw) == "ok"
        waits.extend(model.gaps)
    assert waits == pytest.approx([1.0, 1.25, 1.5, 1.75, 2.0], abs=1e-9)
    assert len(set(waits)) == len(draws), waits
    assert min(waits) > 0, waits


def test_the_backoff_counts_every_failure_including_a_hinted_one(fake, stops):
    """After the 2nd failure the cap is 4 s, though the 1st wait came from a header."""
    model = _Model(
        fake, _Fail(lambda: _status(429, {"Retry-After": "7"})), _Fail(lambda: _status(503)), "ok"
    )
    assert _call(model, fake, rand=0.0) == "ok"
    assert model.gaps == pytest.approx([7.0, 2.0], abs=1e-9)


@pytest.mark.parametrize(
    ("make", "kind"),
    [
        pytest.param(lambda: _status(429), "rate_limited", id="429"),
        pytest.param(lambda: _status(503), "server_error", id="503"),
        pytest.param(lambda: _status(408), "timeout", id="408"),
        pytest.param(lambda: openai.APITimeoutError(request=_request()), "timeout", id="timeout"),
        pytest.param(
            lambda: openai.APIConnectionError(request=_request()), "connection", id="connection"
        ),
        pytest.param(lambda: InternalError("x"), "server_error", id="InternalError"),
        pytest.param(
            lambda: _raised_from(ModelProviderUnavailableError("gone"), _status(429)),
            "rate_limited",
            id="chained-429",
        ),
        pytest.param(
            lambda: _raised_while_handling(ValueError("wrapped"), _status(502)),
            "server_error",
            id="implicit-502",
        ),
    ],
)
def test_every_transient_kind_is_retried(fake, stops, caplog, make, kind):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    model = _Model(fake, _Fail(make), "ok")
    assert _call(model, fake, rand=0.0) == "ok"
    assert model.calls == [0.0, 1.0]
    assert _lines(caplog) == [_retry_line(kind, 1, "1.0")]


def test_a_non_transient_error_after_retries_is_raised_at_once(fake, stops):
    model = _Model(fake, _Fail(lambda: _status(429)), _Fail(lambda: _status(400)), "ok")
    with pytest.raises(openai.APIStatusError) as raised:
        _call(model, fake, rand=0.0)
    assert model.calls == [0.0, 1.0]
    assert raised.value is model.raised[1]
    assert raised.value.status_code == 400


# --------------------------------------------------------------------------- R1: the budget


def test_a_slow_first_attempt_does_not_eat_the_retry_budget(fake, stops, caplog):
    """The budget starts at the first transient failure, not at entry (R1).

    The first attempt takes 100 s.  Counted from entry, the budget would allow 5 attempts;
    counted from the first failure it allows the full 9.  ``elapsed_s`` is since entry.
    """
    caplog.set_level(logging.WARNING, logger=LOGGER)
    model = _Model(fake, _Fail(lambda: _status(503)), durations=(100.0,))
    with pytest.raises(openai.APIStatusError) as raised:
        _call(model, fake, rand=1.0)
    assert model.calls == pytest.approx([0, 102, 106, 114, 130, 160, 190, 220, 250], abs=1e-9)
    assert raised.value is model.raised[-1]
    assert _lines(caplog)[-1] == _gave_up_line("server_error", 9, "250.0")


# --------------------------------------------------------------------------- R2, R3: stops


@pytest.mark.parametrize(
    "policy", [pytest.param(DEFAULT_RETRY_POLICY, id="default"), pytest.param(None, id="None")]
)
def test_a_stopped_turn_makes_no_call(fake, stops, policy):
    stops.stop_at = 0.0
    model = _Model(fake, "ok")
    with pytest.raises(TurnFencedError) as raised:
        _call(model, fake, rand=0.0, policy=policy)
    assert model.calls == []
    assert stops.times == [0.0]
    assert raised.value is stops.raised[0]

    # The positive control: the same check, live, lets exactly one attempt through.
    stops.stop_at = None
    stops.times.clear()
    assert _call(model, fake, rand=0.0, policy=policy) == "ok"
    assert stops.times == [0.0]
    assert model.calls == [0.0]


def test_every_attempt_and_every_slice_is_followed_by_a_stop_check(fake, stops):
    """A check right before each attempt, and one after each slice of at most 1 s."""
    model = _Model(fake, _Fail(lambda: _status(429)), _Fail(lambda: _status(503)), "ok")
    assert _call(model, fake, rand=0.5) == "ok"
    assert model.calls == pytest.approx([0.0, 1.5, 4.5], abs=1e-9)
    events = fake.events
    assert events[0] == ("check", 0.0)
    for index, (kind, value) in enumerate(events):
        if kind == "call":
            assert events[index - 1] == ("check", value), events
        if kind == "sleep":
            assert 0 < value <= 1.0, events
            assert events[index + 1][0] == "check", events
    slept: list[float] = []
    total = 0.0
    for kind, value in events:
        if kind == "sleep":
            total += value
        if kind == "call" and value > 0:
            slept.append(total)
            total = 0.0
    assert slept == pytest.approx([1.5, 3.0], abs=1e-9)


def test_a_stop_is_noticed_within_one_slice(fake, stops):
    """The 5th wait runs from t=30 to t=60; the turn stops at t=37.3."""
    stops.stop_at = 37.3
    model = _Model(fake, _Fail(lambda: _status(503)))
    with pytest.raises(TurnFencedError) as raised:
        _call(model, fake, rand=1.0)
    assert model.calls == pytest.approx([0, 2, 6, 14, 30], abs=1e-9)
    assert 37.3 <= fake.elapsed <= 38.3
    assert all(0 < piece <= 1.0 for piece in fake.slices), max(fake.slices)
    assert raised.value is stops.raised[0]


def test_a_stop_during_a_backoff_is_not_a_provider_fault(fake, stops):
    """The backoff sleeps outside the ``except`` block (R3).

    Inside it, the stop error would carry the 503 as ``__context__``, and the fault-kind
    reading of the turn's failure would call a stop a server error.
    """
    stops.stop_at = 1.0
    model = _Model(fake, _Fail(lambda: _status(503)))
    with pytest.raises(TurnFencedError) as raised:
        _call(model, fake, rand=1.0)
    assert model_fault_kind(model.raised[0]) == "server_error"
    assert raised.value.__context__ is None
    assert raised.value.__cause__ is None
    assert model_fault_kind(raised.value) == "not_transient"


# --------------------------------------------------------------------------- R6: gave up


@pytest.mark.parametrize(
    ("outcome", "rand", "deadline_in", "expected"),
    [
        pytest.param(
            lambda: _status(503),
            1.0,
            None,
            [
                *(
                    _retry_line("server_error", n, wait)
                    for n, wait in enumerate(
                        ["2.0", "4.0", "8.0", "16.0", "30.0", "30.0", "30.0", "30.0"], start=1
                    )
                ),
                _gave_up_line("server_error", 9, "150.0"),
            ],
            id="the-budget",
        ),
        pytest.param(
            lambda: _status(503),
            1.0,
            5.0,
            [_retry_line("server_error", 1, "2.0"), _gave_up_line("server_error", 2, "2.0")],
            id="the-deadline",
        ),
        pytest.param(
            lambda: _status(429, {"Retry-After": "600"}),
            0.0,
            None,
            [_gave_up_line("rate_limited", 1, "0.0")],
            id="a-retry-after-past-the-budget",
        ),
    ],
)
def test_the_gave_up_line_is_logged_once_when_retries_run_out(
    fake, stops, caplog, outcome, rand, deadline_in, expected
):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    model = _Model(fake, _Fail(outcome))
    deadline = None if deadline_in is None else fake.clock() + deadline_in
    with pytest.raises(openai.APIStatusError):
        _call(model, fake, rand=rand, deadline=deadline)
    assert _lines(caplog) == expected


def _fenced_from_a_rate_limit() -> TurnFencedError:
    error = _raised_from(TurnFencedError(RID), _status(429, {"Retry-After": "1"}))
    assert isinstance(error, TurnFencedError)
    return error


@pytest.mark.parametrize(
    ("outcome", "policy", "stop_at", "raises", "expected"),
    [
        pytest.param(
            lambda: _status(400),
            DEFAULT_RETRY_POLICY,
            None,
            openai.APIStatusError,
            [],
            id="non-transient",
        ),
        pytest.param(lambda: _status(429), None, None, openai.APIStatusError, [], id="no-policy"),
        pytest.param(
            _fenced_from_a_rate_limit,
            DEFAULT_RETRY_POLICY,
            None,
            TurnFencedError,
            [],
            id="a-fenced-error",
        ),
        pytest.param(
            lambda: _status(429),
            DEFAULT_RETRY_POLICY,
            1.0,
            TurnFencedError,
            [_retry_line("rate_limited", 1, "2.0")],
            id="a-stop",
        ),
    ],
)
def test_no_gave_up_line_when_the_retries_did_not_run_out(
    fake, stops, caplog, outcome, policy, stop_at, raises, expected
):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    stops.stop_at = stop_at
    model = _Model(fake, _Fail(outcome))
    with pytest.raises(raises):
        _call(model, fake, rand=1.0, policy=policy)
    assert _lines(caplog) == expected


# --------------------------------------------------------------------------- R7: fenced


def test_a_fenced_error_chained_from_a_rate_limit_is_not_retried(fake, stops):
    model = _Model(fake, _Fail(_fenced_from_a_rate_limit), "ok")
    with pytest.raises(TurnFencedError) as raised:
        _call(model, fake, rand=0.0)
    # The chain under it really is transient by kind: only the type keeps it from a retry.
    assert model_fault_kind(raised.value) == "rate_limited"
    assert raised.value is model.raised[0]
    assert model.calls == [0.0]
    assert fake.slices == []


# --------------------------------------------------------------------------- R8: the limiter


@pytest.mark.parametrize("rid", [RID, None])
def test_the_call_runs_holding_one_slot_of_its_turn(monkeypatch, fake, rid):
    monkeypatch.setattr(CHECK, _StopWhen())
    limiter = FairCallLimiter(3, wait_slice_seconds=SLICE)
    during: list[dict] = []
    model = _Model(fake, "ok", inside=lambda: during.append(limiter.in_flight()))
    worker = _on_thread(
        lambda: call_model(
            model,
            agent_key=AGENT,
            limiter=limiter,
            sleep=fake.sleep,
            clock=fake.clock,
            rand=lambda: 0.0,
        ),
        rid=rid,
    )
    assert worker.error is None, repr(worker.error)
    assert worker.result == "ok"
    assert during == [{rid: 1}]
    assert limiter.in_flight() == {}


def _raise_fenced() -> TurnFencedError:
    return TurnFencedError(RID)


@pytest.mark.parametrize(
    ("outcomes", "policy", "stop_at", "attempts"),
    [
        pytest.param(("ok",), DEFAULT_RETRY_POLICY, None, 1, id="success"),
        pytest.param(
            (_Fail(lambda: _status(400)),), DEFAULT_RETRY_POLICY, None, 1, id="non-transient"
        ),
        pytest.param(
            (_Fail(lambda: _status(503)),),
            RetryPolicy(budget_seconds=3.0),
            None,
            2,
            id="retries-spent",
        ),
        pytest.param((_Fail(_raise_fenced),), DEFAULT_RETRY_POLICY, None, 1, id="fenced"),
        pytest.param(
            (_Fail(lambda: _status(503)),), DEFAULT_RETRY_POLICY, 1.0, 1, id="stop-during-a-backoff"
        ),
    ],
)
def test_the_slot_is_given_back_however_the_call_ends(
    monkeypatch, fake, outcomes, policy, stop_at, attempts
):
    check = _StopCheck(fake, stop_at=stop_at)
    monkeypatch.setattr(CHECK, check)
    limiter = FairCallLimiter(1, wait_slice_seconds=SLICE)
    during: list[dict] = []
    model = _Model(fake, *outcomes, inside=lambda: during.append(limiter.in_flight()))
    worker = _on_thread(
        lambda: call_model(
            model,
            agent_key=AGENT,
            policy=policy,
            limiter=limiter,
            sleep=fake.sleep,
            clock=fake.clock,
            rand=lambda: 1.0,
        )
    )
    if stop_at is not None:
        assert worker.error is check.raised[0]
    elif model.raised:
        assert worker.error is model.raised[-1]
    else:
        assert worker.error is None, repr(worker.error)
        assert worker.result == "ok"
    assert len(model.calls) == attempts
    assert during == [{RID: 1}] * attempts
    assert limiter.in_flight() == {}
    assert limiter.waiting() == 0


def test_a_call_waits_for_a_free_slot(monkeypatch, fake):
    """The positive control for the stop test below: a full limiter holds ``fn`` back."""
    monkeypatch.setattr(CHECK, _StopWhen())
    limiter = FairCallLimiter(1, wait_slice_seconds=SLICE)
    holder = _Holder(limiter, "req-other")
    during: list[dict] = []
    model = _Model(fake, "ok", inside=lambda: during.append(limiter.in_flight()))

    def body() -> object:
        set_chat_request_id(RID)
        return call_model(
            model,
            agent_key=AGENT,
            limiter=limiter,
            sleep=fake.sleep,
            clock=fake.clock,
            rand=lambda: 0.0,
        )

    worker = _Thread(body).start()
    try:
        assert _wait_until(lambda: limiter.waiting() == 1), "the call did not queue for a slot"
        assert model.calls == []
    finally:
        holder.finish()
    worker.join()
    assert worker.error is None, repr(worker.error)
    assert worker.result == "ok"
    assert during == [{RID: 1}]
    assert limiter.in_flight() == {}
    assert limiter.waiting() == 0


def test_a_stop_while_waiting_for_a_slot_ends_the_call_without_calling_fn(monkeypatch, fake):
    """The slot's ``check_stop`` is ``check_turn_stopped``, read at call time (R8, C7)."""
    check = _StopWhen()
    monkeypatch.setattr(CHECK, check)
    limiter = FairCallLimiter(1, wait_slice_seconds=SLICE)
    holder = _Holder(limiter, "req-other")
    model = _Model(fake, "ok")

    def body() -> object:
        set_chat_request_id(RID)
        return call_model(
            model,
            agent_key=AGENT,
            limiter=limiter,
            sleep=fake.sleep,
            clock=fake.clock,
            rand=lambda: 0.0,
        )

    worker = _Thread(body).start()
    try:
        assert _wait_until(lambda: limiter.waiting() == 1), "the call did not queue for a slot"
        check.stop.set()
        worker.join()
        assert isinstance(worker.error, TurnFencedError), repr(worker.error)
        assert worker.error is check.raised[-1]
        assert model.calls == []
        assert limiter.waiting() == 0
        assert limiter.in_flight() == {"req-other": 1}
    finally:
        holder.finish()
    assert limiter.in_flight() == {}


def test_no_limiter_means_no_slot(monkeypatch, fake, stops):
    """``limiter=None`` runs ``fn`` bare; it does not fall back to the process limiter."""

    def refuse() -> FairCallLimiter:
        raise AssertionError("call_model reached for the process limiter")

    monkeypatch.setattr("src.services.model_calls.get_model_call_limiter", refuse)
    model = _Model(fake, _Fail(lambda: _status(429)), "ok")
    assert _call(model, fake, rand=0.0) == "ok"
    assert model.calls == [0.0, 1.0]
