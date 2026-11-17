"""Model-call fault handling: which kind of provider fault ended a call.

Today this module owns the fault kinds (``model_fault_kind``); the call limiter and the
retries that act on them arrive in later tasks of the chat-concurrency build.

It must never import ``src.services.agent_runtime``: the runtime imports this module.
"""

from __future__ import annotations

from typing import Literal

import httpx
import openai
import requests
from databricks.sdk.errors import Aborted, DeadlineExceeded, InternalError

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
