"""Which kind of provider fault ended a model call, read off the ``raise ... from`` chain.

``model_fault_kind`` walks ``__cause__ or __context__`` from the error it is given, with a
seen-set, and the first link it recognises decides: a timeout class, then a connection
class, then ``InternalError``, then an ``openai.APIStatusError`` by its status (429 is
``rate_limited``, 408 ``timeout``, 409 and every 5xx ``server_error``, any other status
``not_transient``).  The production path never hands it the provider error
itself: the runtime raises ``ModelProviderUnavailableError`` from it, then
``PinnedInvocationEndpointError`` from that.  So every case is checked bare and under each
of those chain shapes, and an implementation that reads only the outermost link, only the
direct cause, or only ``__cause__`` cannot pass.

Ordering facts the cases pin (openai 3.26.1, httpx 0.28.1, requests 2.32.5):

- ``openai.APITimeoutError`` subclasses ``openai.APIConnectionError`` and
  ``httpx.ReadTimeout`` subclasses ``httpx.TransportError``, so the timeout check must come
  before the connection check;
- ``requests.exceptions.ConnectionError`` is not the builtin ``ConnectionError``, and
  ``DeadlineExceeded`` / ``Aborted`` / ``InternalError`` are ``DatabricksError`` (an
  ``OSError``), not ``TimeoutError`` or ``ConnectionError``: each must be named itself;
- ``Aborted`` subclasses the SDK's 409 ``ResourceConflict`` but is ``connection`` (a 409
  *status* is ``server_error``).  Both are transient; the label is the contract.
"""

from __future__ import annotations

import ctypes
import threading
import typing
from collections.abc import Callable

import httpx
import openai
import pytest
import requests
from databricks.sdk.errors import Aborted, DeadlineExceeded, InternalError
from langchain_core.exceptions import OutputParserException

from src.services.agent_runtime import ModelProviderUnavailableError, is_transient_model_failure
from src.services.model_calls import TRANSIENT_FAULT_KINDS, ModelFaultKind, model_fault_kind
from src.services.persisted_graph_release import PinnedInvocationEndpointError

#: Long enough for any terminating walk on a loaded CI box, short enough not to stall the
#: suite when the walk loops.
_WALK_SECONDS = 2.0


def _request() -> httpx.Request:
    return httpx.Request("POST", "http://x")


def _status(code: int) -> openai.APIStatusError:
    return openai.APIStatusError(
        "status",
        response=httpx.Response(code, request=_request()),
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


def _chained(cause: BaseException) -> BaseException:
    try:
        try:
            raise cause
        except BaseException as inner:
            raise ModelProviderUnavailableError("unavailable") from inner
    except ModelProviderUnavailableError as outer:
        return outer


def _pinned(cause: BaseException) -> BaseException:
    """The full production collapse: pinned error from unavailable error from *cause*."""
    pinned = PinnedInvocationEndpointError(
        endpoint_name="databricks-claude",
        graph_release_id=1,
        agent_definition_revision_id=2,
    )
    outer = _raised_from(pinned, _chained(cause))
    assert outer.__cause__.__cause__ is cause
    return outer


def _implicitly_chained(cause: BaseException) -> BaseException:
    """Raised while handling *cause* with no ``from``: only ``__context__`` reaches it."""
    try:
        try:
            raise cause
        except BaseException:
            raise ModelProviderUnavailableError("unavailable")  # noqa: B904 - the point
    except ModelProviderUnavailableError as outer:
        assert outer.__cause__ is None and outer.__context__ is cause
        return outer


def _cause_over_context(cause: BaseException, context: BaseException) -> BaseException:
    """Raised ``from`` *cause* while handling *context*: the walk follows the cause."""
    try:
        try:
            raise context
        except BaseException:
            raise ModelProviderUnavailableError("unavailable") from cause
    except ModelProviderUnavailableError as outer:
        assert outer.__cause__ is cause and outer.__context__ is context
        return outer


#: How the classified error reaches ``model_fault_kind``.
_SHAPES: dict[str, Callable[[BaseException], BaseException]] = {
    "bare": lambda error: error,
    "chained": _chained,
    "pinned": _pinned,
    "implicit": _implicitly_chained,
}

#: (case id, factory building a fresh error, expected kind).  Factories, so no test sees an
#: error whose chain another test has already set.
Case = tuple[str, Callable[[], BaseException], str]

_STATUS_KINDS: list[tuple[int, str]] = [
    (429, "rate_limited"),
    (408, "timeout"),
    (409, "server_error"),
    (500, "server_error"),
    (502, "server_error"),
    (503, "server_error"),
    (529, "server_error"),
    # Not in the plan's list: today every status >= 500 is transient, so a 5xx the plan
    # does not name must stay a server error (a gateway timeout is the common one).
    (501, "server_error"),
    (504, "server_error"),
    (400, "not_transient"),
    (401, "not_transient"),
    (403, "not_transient"),
    (404, "not_transient"),
    (422, "not_transient"),
]
_STATUS_CASES: list[Case] = [
    (f"status_{code}", lambda code=code: _status(code), kind) for code, kind in _STATUS_KINDS
]

_TIMEOUT_CASES: list[Case] = [
    ("openai_APITimeoutError", lambda: openai.APITimeoutError(request=_request()), "timeout"),
    ("httpx_ReadTimeout", lambda: httpx.ReadTimeout("slow", request=_request()), "timeout"),
    ("requests_ReadTimeout", lambda: requests.exceptions.ReadTimeout(), "timeout"),
    ("builtin_TimeoutError", lambda: TimeoutError(), "timeout"),
    ("databricks_DeadlineExceeded", lambda: DeadlineExceeded("x"), "timeout"),
]

_CONNECTION_CASES: list[Case] = [
    (
        "openai_APIConnectionError",
        lambda: openai.APIConnectionError(request=_request()),
        "connection",
    ),
    ("httpx_ConnectError", lambda: httpx.ConnectError("x", request=_request()), "connection"),
    ("requests_ConnectionError", lambda: requests.exceptions.ConnectionError(), "connection"),
    ("builtin_ConnectionResetError", lambda: ConnectionResetError(), "connection"),
    ("databricks_Aborted", lambda: Aborted("x"), "connection"),
]

_INTERNAL_ERROR_CASES: list[Case] = [
    ("databricks_InternalError", lambda: InternalError("x"), "server_error"),
]

_PARSE_ERROR_CASES: list[Case] = [
    ("OutputParserException", lambda: OutputParserException("no tool call"), "not_transient"),
]

#: The walk stops at the first link it recognises; a status there decides even when a
#: transient fault lies deeper.
_FIRST_LINK_CASES: list[Case] = [
    ("400_from_429", lambda: _raised_from(_status(400), _status(429)), "not_transient"),
    ("429_from_400", lambda: _raised_from(_status(429), _status(400)), "rate_limited"),
    (
        "400_from_APITimeoutError",
        lambda: _raised_from(_status(400), openai.APITimeoutError(request=_request())),
        "not_transient",
    ),
    ("TimeoutError_from_400", lambda: _raised_from(TimeoutError(), _status(400)), "timeout"),
    (
        "from_400_while_handling_429",
        lambda: _cause_over_context(_status(400), _status(429)),
        "not_transient",
    ),
    (
        "from_429_while_handling_400",
        lambda: _cause_over_context(_status(429), _status(400)),
        "rate_limited",
    ),
]


def _cycle() -> BaseException:
    a = ModelProviderUnavailableError("a")
    b = ValueError("b")
    a.__cause__ = b
    b.__context__ = a
    return a


def _shaped(cases: list[Case]) -> list:
    """Every case under every chain shape, as pytest params."""
    return [
        pytest.param(make, shape, kind, id=f"{name}-{shape}")
        for name, make, kind in cases
        for shape in _SHAPES
    ]


#: An error the runtime raised itself, with no provider cause under it.
_NO_CAUSE = pytest.param(
    lambda: ModelProviderUnavailableError("gone"), "bare", "not_transient", id="no_cause"
)

#: Every error the tests above classify, bare and chained, plus the two unshaped ones.
_ALL_CASES = [
    *_shaped(_STATUS_CASES),
    *_shaped(_TIMEOUT_CASES),
    *_shaped(_CONNECTION_CASES),
    *_shaped(_INTERNAL_ERROR_CASES),
    *_shaped(_PARSE_ERROR_CASES),
    *_shaped(_FIRST_LINK_CASES),
    _NO_CAUSE,
    pytest.param(_cycle, "bare", "not_transient", id="cycle"),
]


class _WalkAbandoned(BaseException):
    """Raised into a classifier thread that never returned, to stop it spinning."""


def _within(seconds: float, classify: Callable[[BaseException], object], error: BaseException):
    """``classify(error)`` on a daemon thread; fail instead of hanging if it never returns.

    pytest-timeout is not installed, so a walk with no seen-set would hang the run.  A
    thread that is still running after *seconds* is stopped with an async exception, so a
    looping walk does not hold the GIL and slow the rest of the suite.
    """
    outcome: dict[str, object] = {}

    def run() -> None:
        try:
            outcome["value"] = classify(error)
        except BaseException as exc:  # noqa: BLE001 - re-raised on the test thread
            outcome["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout=seconds)
    looped = worker.is_alive()
    if looped:
        ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_ulong(worker.ident), ctypes.py_object(_WalkAbandoned)
        )
        worker.join(timeout=seconds)
    assert not looped, f"{classify.__name__} did not return within {seconds}s: the walk loops"
    if "error" in outcome:
        raise outcome["error"]  # type: ignore[misc]
    return outcome["value"]


def test_the_five_kinds_and_the_four_transient_ones():
    kinds = typing.get_args(getattr(ModelFaultKind, "__value__", ModelFaultKind))
    assert len(kinds) == 5
    assert set(kinds) == {"rate_limited", "server_error", "timeout", "connection", "not_transient"}
    assert isinstance(TRANSIENT_FAULT_KINDS, frozenset)
    assert TRANSIENT_FAULT_KINDS == frozenset(
        {"rate_limited", "server_error", "timeout", "connection"}
    )


@pytest.mark.parametrize(("make", "shape", "kind"), _shaped(_STATUS_CASES))
def test_status_codes_map_to_kinds(make, shape, kind):
    assert model_fault_kind(_SHAPES[shape](make())) == kind


@pytest.mark.parametrize(("make", "shape", "kind"), _shaped(_TIMEOUT_CASES))
def test_timeouts_are_timeouts(make, shape, kind):
    assert model_fault_kind(_SHAPES[shape](make())) == kind == "timeout"


@pytest.mark.parametrize(("make", "shape", "kind"), _shaped(_CONNECTION_CASES))
def test_dropped_connections_are_connection(make, shape, kind):
    assert model_fault_kind(_SHAPES[shape](make())) == kind == "connection"


@pytest.mark.parametrize(("make", "shape", "kind"), _shaped(_INTERNAL_ERROR_CASES))
def test_internal_error_is_server_error(make, shape, kind):
    assert model_fault_kind(_SHAPES[shape](make())) == kind == "server_error"


@pytest.mark.parametrize(("make", "shape", "kind"), [_NO_CAUSE, *_shaped(_PARSE_ERROR_CASES)])
def test_no_cause_or_a_parse_error_is_not_transient(make, shape, kind):
    """The pinned-failure contract holds for an error the runtime raised itself."""
    assert model_fault_kind(_SHAPES[shape](make())) == kind == "not_transient"


@pytest.mark.parametrize(("make", "shape", "kind"), _shaped(_FIRST_LINK_CASES))
def test_the_outermost_status_decides(make, shape, kind):
    assert model_fault_kind(_SHAPES[shape](make())) == kind


def test_a_cyclic_chain_terminates():
    error = _cycle()
    assert error.__cause__.__context__ is error
    assert _within(_WALK_SECONDS, model_fault_kind, error) == "not_transient"


@pytest.mark.parametrize(("make", "shape", "kind"), _ALL_CASES)
def test_is_transient_agrees_with_the_kind(make, shape, kind):
    error = _SHAPES[shape](make())
    fault_kind = _within(_WALK_SECONDS, model_fault_kind, error)
    transient = _within(_WALK_SECONDS, is_transient_model_failure, error)
    assert fault_kind == kind
    assert transient is (fault_kind in TRANSIENT_FAULT_KINDS)
    assert transient is (kind in TRANSIENT_FAULT_KINDS)
