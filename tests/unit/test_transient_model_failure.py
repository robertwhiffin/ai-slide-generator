"""Which provider faults count as transient — read off the ``raise ... from`` chain."""

from __future__ import annotations

import httpx
import openai
import pytest

from src.services.agent_runtime import ModelProviderUnavailableError, is_transient_model_failure


def _status(code: int) -> openai.APIStatusError:
    return openai.APIStatusError(
        "status",
        response=httpx.Response(code, request=httpx.Request("POST", "http://x")),
        body=None,
    )


def _chained(cause: BaseException) -> BaseException:
    try:
        try:
            raise cause
        except BaseException as inner:
            raise ModelProviderUnavailableError("unavailable") from inner
    except ModelProviderUnavailableError as outer:
        return outer


@pytest.mark.parametrize("code", [408, 409, 429, 500, 502, 503, 529])
def test_retryable_statuses_are_transient(code):
    assert is_transient_model_failure(_chained(_status(code)))


@pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
def test_client_errors_are_not(code):
    assert not is_transient_model_failure(_chained(_status(code)))


def test_timeouts_and_dropped_connections_are_transient():
    request = httpx.Request("POST", "http://x")
    assert is_transient_model_failure(_chained(openai.APITimeoutError(request=request)))
    assert is_transient_model_failure(_chained(httpx.ReadTimeout("slow", request=request)))
    assert is_transient_model_failure(_chained(ConnectionResetError()))


def test_no_cause_is_not_transient():
    """The pinned-failure contract holds for an error the runtime raised itself."""
    assert not is_transient_model_failure(ModelProviderUnavailableError("gone"))
