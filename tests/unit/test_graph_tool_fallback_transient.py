# ruff: noqa: F811 - the graph_env / images_on / image_tools fixtures are imported, then requested by name.
"""#380: a tool-carrying model call that hit a transient provider fault is not made again
without its tools.

A model call that carries tools (the architect's ``generate_image`` and Gateway MCP tools,
the analyst's Gateway tools) and raises is made once more with no toolset, so that a tool the
provider rejected never fails the turn (I2).  A rate limit, a 5xx, a timeout or a dropped
connection is not that: it says nothing about the tools, the endpoint is still overloaded, and
the same call again at once doubles its load exactly when it is rate limiting.  Since #376 the
image tool is bound on every agent-mode architect call, so this path covers every turn.

So a transient fault (``is_transient_model_failure``, read off the ``raise ... from`` chain the
runtime builds) takes the path a call without tools takes: the first attempt fails the turn,
an edit retry leaves the turn refused with the first answer's refusal, and the analyst's error
propagates.  A tool or schema rejection (a 400), the tool loop giving up, and an endpoint error
with no transient cause keep the single fallback without tools.
"""

from __future__ import annotations

import logging
import time

import httpx
import openai
import pytest

from src.services.agent_runtime import ModelProviderUnavailableError
from src.services.graph import nodes
from src.services.persisted_graph_release import PinnedInvocationEndpointError
from tests.fixtures.graph_tool_runtime import FakeRuntime, install_runtime, turn_state
from tests.unit.conftest_graph import (  # noqa: F401 - graph_env is a fixture
    architect_build,
    graph_env,
    make_spec,
)
from tests.unit.test_graph_gateway_mcp import (
    CREATE,
    WEB,
    WEB_ANALYST_ROW,
    _analyst_state,
    _entry,
    _gateway_deck,
    _info,
    _lakedraw_deck,
    _loop_gave_up,
    _pinned_error,
    _run_analyst,
    _Service,
    _success,
    _tools_failed,
    _web_tools,
)
from tests.unit.test_graph_image_tool import (  # noqa: F401 - fixtures by name
    IMAGE_TOOL,
    _discuss,
    _generate,
    _run,
    image_tools,
    images_on,
)

# ---------------------------------------------------------------------------
# Errors, chained as the runtime chains them
# ---------------------------------------------------------------------------


def _response(status: int) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("POST", "http://endpoint"))


def _cause(kind: str) -> BaseException:
    if kind == "429":
        return openai.RateLimitError("rate limited", response=_response(429), body=None)
    if kind == "503":
        return openai.APIStatusError("unavailable", response=_response(503), body=None)
    if kind == "timeout":
        return openai.APITimeoutError(request=httpx.Request("POST", "http://endpoint"))
    if kind == "connection":
        return openai.APIConnectionError(request=httpx.Request("POST", "http://endpoint"))
    if kind == "400":
        return openai.BadRequestError(
            "invalid tool definition", response=_response(400), body=None
        )
    raise AssertionError(kind)


def _endpoint_error(kind: str) -> PinnedInvocationEndpointError:
    """What ``AgentRuntime.run`` raises for a provider fault: the endpoint error, from
    ``ModelProviderUnavailableError``, from the provider's own error."""
    try:
        try:
            raise _cause(kind)
        except BaseException as cause:
            raise ModelProviderUnavailableError("pinned model provider unavailable") from cause
    except ModelProviderUnavailableError as collapsed:
        try:
            raise PinnedInvocationEndpointError(
                endpoint_name="databricks-claude-endpoint",
                graph_release_id=1,
                agent_definition_revision_id=1,
            ) from collapsed
        except PinnedInvocationEndpointError as error:
            return error


TRANSIENT = ["429", "503", "timeout", "connection"]

#: Not transient: each keeps today's single fallback without tools.
NOT_TRANSIENT = {
    "tool-rejected-400": lambda: _endpoint_error("400"),
    "endpoint-error-no-cause": _pinned_error,
    "loop-gave-up": _loop_gave_up,
}


def _fallback_lines(caplog) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == nodes.__name__
        and ("tools_failed" in r.getMessage() or "image_tool_failed" in r.getMessage())
    ]


# ---------------------------------------------------------------------------
# The architect's generate_image tool
# ---------------------------------------------------------------------------


@pytest.mark.image_tool
@pytest.mark.parametrize("kind", TRANSIENT)
def test_a_transient_fault_with_the_image_tool_is_not_made_again(
    graph_env, monkeypatch, caplog, images_on, image_tools, kind
):
    def fails(call):
        raise _endpoint_error(kind)

    runtime = install_runtime(monkeypatch, FakeRuntime(architect=fails))

    with caplog.at_level(logging.WARNING, logger=nodes.__name__):
        with pytest.raises(PinnedInvocationEndpointError):
            _run(graph_env, turn_state(graph_env))

    calls = runtime.calls_for("architect")
    assert calls[0].tool_names == [IMAGE_TOOL]
    assert len(calls) == 1, "a rate-limited call must not be made again without its tools"
    assert _fallback_lines(caplog) == []


@pytest.mark.image_tool
@pytest.mark.parametrize("make_error", list(NOT_TRANSIENT.values()), ids=list(NOT_TRANSIENT))
def test_other_failures_with_the_image_tool_still_fall_back_once(
    graph_env, monkeypatch, images_on, image_tools, make_error
):
    def fails(call):
        assert call.tool_names == [IMAGE_TOOL]
        raise make_error()

    spec = make_spec((0, 1))
    runtime = install_runtime(monkeypatch, FakeRuntime(architect=[fails, architect_build(spec)]))

    t = _run(graph_env, turn_state(graph_env))

    first, second = runtime.calls_for("architect")
    assert first.toolset is not None and second.context.toolset is None
    assert t.updates["error_state"] is None
    assert t.updates["deck_spec"].title == spec.title


@pytest.mark.image_tool
def test_a_transient_fault_on_the_edit_retry_is_not_made_again(
    graph_env, monkeypatch, images_on, image_tools
):
    """Attempt 1 is refused with a retryable code; its retry, carrying the tool, is rate
    limited.  No third call: the endpoint error fails the turn, as the persisted-runtime
    family does on every model call (``_raise_if_persisted_runtime_failure``)."""
    refused = architect_build(make_spec((0, 1), slide_type="title"))

    def retry_rate_limited(call):
        raise _endpoint_error("429")

    runtime = install_runtime(monkeypatch, FakeRuntime(architect=[refused, retry_rate_limited]))

    with pytest.raises(PinnedInvocationEndpointError):
        _run(graph_env, turn_state(graph_env))

    calls = runtime.calls_for("architect")
    assert "rejected_edit" in calls[1].payload and calls[1].toolset is not None
    assert len(calls) == 2, "the rate-limited retry must not be made again without its tools"


# ---------------------------------------------------------------------------
# The architect's Gateway MCP tools (image generation off)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", TRANSIENT)
def test_a_transient_fault_with_gateway_tools_is_not_made_again(
    graph_env, monkeypatch, caplog, kind
):
    _lakedraw_deck(graph_env, monkeypatch)

    def fails(call):
        raise _endpoint_error(kind)

    runtime = install_runtime(monkeypatch, FakeRuntime(architect=fails))

    with caplog.at_level(logging.WARNING, logger=nodes.__name__):
        with pytest.raises(PinnedInvocationEndpointError):
            _run(graph_env, turn_state(graph_env))

    calls = runtime.calls_for("architect")
    assert calls[0].has_tool(CREATE)
    assert len(calls) == 1, "a rate-limited call must not be made again without its tools"
    assert _fallback_lines(caplog) == []
    rows = graph_env.messages()
    assert _tools_failed("LakeDraw") not in _info(rows), "the connection did not fail"


@pytest.mark.parametrize("make_error", list(NOT_TRANSIENT.values()), ids=list(NOT_TRANSIENT))
def test_other_failures_with_gateway_tools_still_fall_back_once(
    graph_env, monkeypatch, make_error
):
    _lakedraw_deck(graph_env, monkeypatch)

    def fails(call):
        assert call.has_tool(CREATE)
        raise make_error()

    runtime = install_runtime(
        monkeypatch, FakeRuntime(architect=[fails, architect_build(make_spec((0, 1)))])
    )

    t = _run(graph_env, turn_state(graph_env))

    first, second = runtime.calls_for("architect")
    assert first.toolset is not None and second.context.toolset is None
    assert t.updates["error_state"] is None
    assert t.info == [_tools_failed("LakeDraw")]


# ---------------------------------------------------------------------------
# Both kinds of tools on one toolset
# ---------------------------------------------------------------------------


@pytest.mark.image_tool
@pytest.mark.parametrize("kind", TRANSIENT)
def test_a_transient_fault_with_both_kinds_of_tools_is_not_made_again(
    graph_env, monkeypatch, caplog, images_on, image_tools, kind
):
    _lakedraw_deck(graph_env, monkeypatch)

    def fails(call):
        if call.toolset is not None:
            _generate(call, count=1)
        raise _endpoint_error(kind)

    runtime = install_runtime(monkeypatch, FakeRuntime(architect=fails))

    with caplog.at_level(logging.WARNING, logger=nodes.__name__):
        with pytest.raises(PinnedInvocationEndpointError):
            _run(graph_env, turn_state(graph_env))

    calls = runtime.calls_for("architect")
    assert calls[0].has_tool(CREATE) and calls[0].has_tool(IMAGE_TOOL)
    assert len(calls) == 1, "a rate-limited call must not be made again without its tools"
    assert _fallback_lines(caplog) == []


@pytest.mark.image_tool
def test_a_tool_rejection_with_both_kinds_of_tools_falls_back_once(
    graph_env, monkeypatch, images_on, image_tools
):
    _lakedraw_deck(graph_env, monkeypatch)

    def fails(call):
        assert call.has_tool(CREATE) and call.has_tool(IMAGE_TOOL)
        raise _endpoint_error("400")

    runtime = install_runtime(monkeypatch, FakeRuntime(architect=[fails, _discuss("Sure.")]))

    t = _run(graph_env, turn_state(graph_env))

    first, second = runtime.calls_for("architect")
    assert first.toolset is not None and second.context.toolset is None
    assert t.updates["error_state"] is None


# ---------------------------------------------------------------------------
# The data analyst's Gateway tools
# ---------------------------------------------------------------------------


def _web_analyst_deck(env, monkeypatch) -> None:
    _gateway_deck(
        env,
        monkeypatch,
        entries=[_entry(WEB, "Web Search")],
        rows=[WEB_ANALYST_ROW],
        services=[_Service(WEB, _web_tools())],
    )


@pytest.mark.parametrize("kind", TRANSIENT)
def test_a_transient_fault_with_the_analysts_gateway_tools_propagates(
    graph_env, monkeypatch, kind
):
    _web_analyst_deck(graph_env, monkeypatch)

    def fails(call):
        raise _endpoint_error(kind)

    runtime = install_runtime(monkeypatch, FakeRuntime(data_analyst=fails))

    with pytest.raises(PinnedInvocationEndpointError):
        _run_analyst(graph_env, _analyst_state(graph_env, turn_started_at=time.time() - 5))

    calls = runtime.calls_for("data_analyst")
    assert calls[0].tool_names == ["web_search"]
    assert len(calls) == 1, "a rate-limited call must not be made again without its tools"


@pytest.mark.parametrize("make_error", list(NOT_TRANSIENT.values()), ids=list(NOT_TRANSIENT))
def test_other_failures_with_the_analysts_gateway_tools_still_fall_back_once(
    graph_env, monkeypatch, make_error
):
    _web_analyst_deck(graph_env, monkeypatch)

    def fails(call):
        assert call.tool_names == ["web_search"]
        raise make_error()

    runtime = install_runtime(
        monkeypatch, FakeRuntime(data_analyst=[fails, _success(["The request"])])
    )

    _run_analyst(graph_env, _analyst_state(graph_env, turn_started_at=time.time() - 5))

    first, second = runtime.calls_for("data_analyst")
    assert first.toolset is not None and second.context.toolset is None


# ---------------------------------------------------------------------------
# The errors themselves
# ---------------------------------------------------------------------------


def test_the_test_errors_are_classified_as_the_runtime_would():
    """The fixtures above are what they claim: transient ones through the cause chain,
    the 400 and the endpoint error with no cause not."""
    from src.services.agent_runtime import is_transient_model_failure

    assert all(is_transient_model_failure(_endpoint_error(kind)) for kind in TRANSIENT)
    assert not any(is_transient_model_failure(make()) for make in NOT_TRANSIENT.values())
