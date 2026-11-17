"""``DatabricksModelAdapter`` calls the model through ``call_model`` (chat concurrency, Task 4).

Spec §2-§3: one per-process limiter covers every adapter model call, and the adapter, not
the SDK, owns the retries.  So:

- ``invoke`` and each round of ``invoke_with_tools`` run ``<model>.invoke(<arg>)`` through
  ``call_model(..., agent_key=..., policy=..., limiter=...)``, inside
  ``_model_provider_errors_collapsed()``: a spent retry collapses exactly as today, with
  the provider error as the cause.  The model and the client are built outside
  ``call_model``, once per invocation however many attempts it takes; a tool runs between
  rounds, outside ``call_model`` and outside any slot.
- An adapter built with no ``transport_options`` (production) retries with
  ``DEFAULT_RETRY_POLICY``, holds a slot of ``get_model_call_limiter()`` and builds its
  model with ``max_retries=0``.  An adapter built with ``transport_options`` (the admin
  test runs, the eval harness) keeps today's behaviour: no Tellr retries, no limiter, its
  options passed through unchanged.  Explicit ``retry_policy`` / ``limiter`` always win.

Conventions:

- The chat model is a ``_Chat`` double behind the adapter's ``model_factory``; the
  structured-output binding, the parser, the tool loop, ``call_model`` and the limiter are
  production's.  Each invocation records its input and, when the test passes ``observe``,
  what the limiter held at that moment, so every "no slot after" check is paired with
  proof that a slot WAS held.  A tool records the same from its ``run``: an assertion
  raised inside ``run`` would be answered to the model in-band and the test would stay
  green (C11).
- Tests inject ``POLICY`` (waits of 0.5-2 ms) and a ``FairCallLimiter(2)`` unless they are
  about the production defaults.  Those use a 429 carrying ``retry-after-ms: 1``, so the
  default policy waits about 1 ms: ``call_model``'s ``sleep`` is bound at definition time
  and cannot be patched.
- No test binds a chat request id or a turn deadline, so the limiter group is ``None``
  and the real stop check issues no query.  Stop scenarios patch
  ``src.services.model_calls.check_turn_stopped`` (C7).  The stop-check cache reset is the
  autouse fixture in ``tests/conftest.py``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
import openai
import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableLambda

import src.services.agent_runtime as agent_runtime
import src.services.model_calls as model_calls
from src.services.agent_runtime import (
    DatabricksModelAdapter,
    ModelProviderUnavailableError,
    is_transient_model_failure,
)
from src.services.generation_fence import TurnFencedError
from src.services.model_calls import (
    DEFAULT_RETRY_POLICY,
    FairCallLimiter,
    RetryPolicy,
    get_model_call_limiter,
    model_fault_kind,
)
from tests.fixtures.tool_call_doubles import no_tool_call_reply, tool_call_reply
from tests.unit.test_agent_runtime_tool_loop import (
    CONFIGURATION,
    OUTPUT,
    PROMPT,
    SCHEMA,
    LookupArgs,
    RecordingTool,
    _ask,
    _toolset,
)

LOGGER = "src.services.model_calls"
AGENT = "data_analyst"
RID = "req-adapter-retries"

#: The policy injected by most tests: real waits of 0.5-2 ms.
POLICY = RetryPolicy(base_seconds=0.001, max_wait_seconds=0.002, budget_seconds=1.0)
#: Always-failing calls give up after about 0.02 s of retrying.
SHORT_BUDGET = RetryPolicy(base_seconds=0.001, max_wait_seconds=0.002, budget_seconds=0.02)
#: A provider hint of 1 ms, so even the default policy retries at once.
RETRY_SOON = {"retry-after-ms": "1"}

#: ``invoke`` and ``invoke_with_tools``: every model call must behave the same on both.
PATHS = ["invoke", "invoke_with_tools"]

#: A call that gets this far is not going to stop by itself.
MAX_INVOCATIONS = 1000

EXPECTED = SCHEMA.model_validate(OUTPUT)


# --------------------------------------------------------------------------- doubles


class _Runaway(BaseException):
    """Ends a retry loop that never stops: no ``except Exception`` catches it."""


class _Fault:
    """A scripted outcome: raise a fresh error built by *make*."""

    def __init__(self, make: Callable[[], BaseException]):
        self.make = make


class _Chat:
    """A chat-model double; its bound model plays *script*, the last entry repeating.

    An entry is a ``_Fault`` (raise a fresh error) or a reply to return.  ``invocations``
    keeps a snapshot of each input (the loop keeps appending to one list), ``observed``
    what *observe* returned during each invocation, ``raised`` every error raised.
    """

    def __init__(self, *script: Any, observe: Callable[[], Any] | None = None):
        assert script, "a chat double needs at least one outcome"
        self._script = script
        self._observe = observe
        self.bindings: list[tuple[list[Any], dict[str, Any]]] = []
        self.invocations: list[Any] = []
        self.observed: list[Any] = []
        self.raised: list[BaseException] = []

    def bind_tools(self, tools, **kwargs):
        self.bindings.append((list(tools), dict(kwargs)))
        return RunnableLambda(self._reply)

    def _reply(self, messages: Any) -> AIMessage:
        if len(self.invocations) >= MAX_INVOCATIONS:
            raise _Runaway(f"{len(self.invocations)} invocations; the call never stopped")
        index = len(self.invocations)
        self.invocations.append(list(messages) if isinstance(messages, list) else messages)
        if self._observe is not None:
            self.observed.append(self._observe())
        outcome = self._script[min(index, len(self._script) - 1)]
        if isinstance(outcome, _Fault):
            error = outcome.make()
            self.raised.append(error)
            raise error
        return outcome


@dataclass
class _Rig:
    chat: _Chat
    adapter: DatabricksModelAdapter
    #: The model factory's kwargs, one entry per model built.
    constructed: list[dict[str, Any]]
    #: One entry per client built.
    clients: list[object]
    client: object


def _rig(chat: _Chat, **adapter_kwargs: Any) -> _Rig:
    """An adapter over *chat*; *adapter_kwargs* are the constructor's other arguments."""
    constructed: list[dict[str, Any]] = []
    clients: list[object] = []
    client = object()

    def model_factory(**kwargs: Any) -> _Chat:
        constructed.append(dict(kwargs))
        return chat

    def client_factory() -> object:
        clients.append(client)
        return client

    adapter = DatabricksModelAdapter(
        model_factory=model_factory, client_factory=client_factory, **adapter_kwargs
    )
    return _Rig(chat, adapter, constructed, clients, client)


def _run(
    adapter: DatabricksModelAdapter,
    path: str,
    *,
    agent_key: str = AGENT,
    tool: RecordingTool | None = None,
) -> Any:
    if path == "invoke":
        return adapter.invoke(
            agent_key=agent_key, configuration=CONFIGURATION, schema=SCHEMA, prompt=PROMPT
        )
    return adapter.invoke_with_tools(
        agent_key=agent_key,
        configuration=CONFIGURATION,
        schema=SCHEMA,
        prompt=PROMPT,
        toolset=_toolset(tool or RecordingTool()),
    )


def _valid() -> AIMessage:
    """A reply that calls the schema with valid args."""
    return tool_call_reply(SCHEMA, OUTPUT)


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://example.invalid/ai-gateway/mlflow/v1/chat/completions")


def _rate_limited(headers: dict[str, str] | None = None) -> openai.RateLimitError:
    return openai.RateLimitError(
        "rate limited",
        response=httpx.Response(429, headers=headers or {}, request=_request()),
        body=None,
    )


def _soon_rate_limited() -> openai.RateLimitError:
    return _rate_limited(RETRY_SOON)


def _lines(caplog: pytest.LogCaptureFixture, prefix: str) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.name == LOGGER and record.getMessage().startswith(prefix)
    ]


def _kwargs(client: object, **extra: Any) -> dict[str, Any]:
    """The model factory's kwargs for ``CONFIGURATION`` on *client*, plus *extra*."""
    return {
        "model": CONFIGURATION.endpoint_name,
        "max_tokens": CONFIGURATION.max_tokens,
        "workspace_client": client,
        **extra,
    }


# --------------------------------------------------------------------------- retries


@pytest.mark.parametrize("agent_key", ["data_analyst", "fix_reviewer"])
def test_the_production_adapter_retries_a_rate_limit(agent_key, caplog):
    """A 429 then a schema call: the parsed schema after two invocations of one model."""
    caplog.set_level(logging.WARNING, logger=LOGGER)
    limiter = FairCallLimiter(2)
    chat = _Chat(_Fault(_rate_limited), _valid(), observe=limiter.in_flight)
    rig = _rig(chat, retry_policy=POLICY, limiter=limiter)

    result = _run(rig.adapter, "invoke", agent_key=agent_key)

    assert result == EXPECTED
    assert chat.invocations == [PROMPT, PROMPT]
    assert chat.observed == [{None: 1}, {None: 1}], "each attempt runs holding one slot"
    assert limiter.in_flight() == {}
    # The model is built and bound once; only its invoke is retried (ruling 4).
    assert rig.constructed == [_kwargs(rig.client, max_retries=0)]
    assert rig.clients == [rig.client]
    assert len(chat.bindings) == 1
    # ``agent_key`` names the retry line (no longer deleted).
    retries = _lines(caplog, "model_call_retry")
    assert len(retries) == 1
    assert retries[0].levelno == logging.WARNING
    message = retries[0].getMessage()
    assert message.startswith(f"model_call_retry agent={agent_key} fault=rate_limited attempt=1 ")


def test_each_tool_loop_round_is_retried_on_its_own(caplog):
    """Round 1 calls a tool; round 2 is rate-limited once, retried, then calls the schema.

    The retry re-sends round 2's history; it does not restart the loop or rerun the tool.
    """
    caplog.set_level(logging.WARNING, logger=LOGGER)
    limiter = FairCallLimiter(2)
    tool = RecordingTool(results=("42 rows: north=7, south=35",))
    chat = _Chat(
        _ask("sales by region", "call_1"),
        _Fault(_rate_limited),
        _valid(),
        observe=limiter.in_flight,
    )
    rig = _rig(chat, retry_policy=POLICY, limiter=limiter)

    result = _run(rig.adapter, "invoke_with_tools", agent_key="builder", tool=tool)

    assert result == EXPECTED
    assert [run.args for run in tool.runs] == [LookupArgs(question="sales by region")]
    assert len(chat.invocations) == 3
    first, failed, retried = chat.invocations
    assert first == [HumanMessage(content=PROMPT)]
    assert len(failed) == 3
    assert isinstance(failed[-1], ToolMessage)
    assert failed[-1].tool_call_id == "call_1"
    assert retried == failed, "the retried round must send the failed attempt's history"
    assert chat.observed == [{None: 1}] * 3
    assert limiter.in_flight() == {}
    assert rig.constructed == [_kwargs(rig.client, max_retries=0)]
    assert rig.clients == [rig.client]
    assert len(chat.bindings) == 1
    retries = _lines(caplog, "model_call_retry")
    assert len(retries) == 1
    assert retries[0].getMessage().startswith("model_call_retry agent=builder fault=rate_limited ")


@pytest.mark.parametrize("path", PATHS)
def test_spent_retries_still_collapse_with_the_cause(path, caplog):
    """Always 429: once the budget is spent the error collapses exactly as today."""
    caplog.set_level(logging.WARNING, logger=LOGGER)
    limiter = FairCallLimiter(2)
    chat = _Chat(_Fault(_rate_limited), observe=limiter.in_flight)
    rig = _rig(chat, retry_policy=SHORT_BUDGET, limiter=limiter)

    with pytest.raises(ModelProviderUnavailableError) as raised:
        _run(rig.adapter, path)

    assert str(raised.value) == "pinned model provider unavailable"
    assert len(chat.invocations) >= 2, "the call was never retried"
    assert raised.value.__cause__ is chat.raised[-1], "the last attempt's error is the cause"
    assert model_fault_kind(raised.value) == "rate_limited"
    assert is_transient_model_failure(raised.value)
    assert chat.observed == [{None: 1}] * len(chat.invocations)
    assert limiter.in_flight() == {}
    gave_up = _lines(caplog, "model_call_gave_up")
    assert len(gave_up) == 1
    assert gave_up[0].getMessage().startswith(f"model_call_gave_up agent={AGENT} ")


# --------------------------------------------------------------------------- slots


def test_a_parse_failure_is_not_retried_and_frees_its_slot(caplog):
    """Two replies without a tool call (the nudge path): no retry, and no slot left held."""
    caplog.set_level(logging.WARNING, logger=LOGGER)
    limiter = FairCallLimiter(2)
    tool = RecordingTool()
    chat = _Chat(no_tool_call_reply(), no_tool_call_reply(), observe=limiter.in_flight)
    rig = _rig(chat, retry_policy=POLICY, limiter=limiter)

    with pytest.raises(OutputParserException):
        _run(rig.adapter, "invoke_with_tools", tool=tool)

    assert len(chat.invocations) == 2, "the reply and the nudged reply, nothing retried"
    assert chat.observed == [{None: 1}, {None: 1}], "each model call held a slot"
    assert limiter.in_flight() == {}
    assert tool.runs == []
    assert _lines(caplog, "model_call_") == []


def test_a_parse_failure_in_invoke_is_not_retried_and_frees_its_slot(caplog):
    """``invoke`` parses inside the call: the parse error is raised holding the slot."""
    caplog.set_level(logging.WARNING, logger=LOGGER)
    limiter = FairCallLimiter(2)
    chat = _Chat(no_tool_call_reply(), observe=limiter.in_flight)
    rig = _rig(chat, retry_policy=POLICY, limiter=limiter)

    with pytest.raises(OutputParserException):
        _run(rig.adapter, "invoke")

    assert len(chat.invocations) == 1
    assert chat.observed == [{None: 1}]
    assert limiter.in_flight() == {}
    assert _lines(caplog, "model_call_") == []


@pytest.mark.parametrize("path", PATHS)
def test_a_bug_inside_a_model_call_is_not_retried_and_frees_its_slot(path):
    """Review Focus 3: a non-provider error raised holding a slot leaks no slot."""
    limiter = FairCallLimiter(2)
    chat = _Chat(_Fault(lambda: KeyError("a bug in the reply handling")), observe=limiter.in_flight)
    rig = _rig(chat, retry_policy=POLICY, limiter=limiter)

    with pytest.raises(KeyError) as raised:
        _run(rig.adapter, path)

    assert raised.value is chat.raised[0], "a bug is neither retried nor collapsed"
    assert len(chat.invocations) == 1
    assert chat.observed == [{None: 1}]
    assert limiter.in_flight() == {}


def test_no_slot_is_held_while_a_tool_runs():
    """Spec §2: a slot is held for the model call only, not while a tool runs."""
    limiter = FairCallLimiter(2)
    during_tool: list[dict[str | None, int]] = []
    tool = RecordingTool(
        results=("first answer", "second answer"),
        on_run=lambda: during_tool.append(limiter.in_flight()),
    )
    chat = _Chat(_ask("q1", "call_1"), _ask("q2", "call_2"), _valid(), observe=limiter.in_flight)
    rig = _rig(chat, retry_policy=POLICY, limiter=limiter)

    result = _run(rig.adapter, "invoke_with_tools", tool=tool)

    assert result == EXPECTED
    assert len(tool.runs) == 2
    assert during_tool == [{}, {}], "a slot was held while a tool ran"
    assert chat.observed == [{None: 1}] * 3, "each model round held a slot"
    assert limiter.in_flight() == {}


# --------------------------------------------------------------------------- stops


@pytest.mark.parametrize("path", PATHS)
def test_a_stop_inside_a_model_call_is_not_collapsed(path, monkeypatch):
    """A stop seen before the first attempt is a ``TurnFencedError``, never a provider fault.

    ``TurnFencedError`` is a ``RuntimeError`` outside ``_MODEL_PROVIDER_ERRORS``; this
    keeps it so.
    """
    checks: list[str | None] = []

    def stopped(request_id: str | None = None) -> None:
        checks.append(request_id)
        raise TurnFencedError(RID)

    monkeypatch.setattr(model_calls, "check_turn_stopped", stopped)
    limiter = FairCallLimiter(2)
    chat = _Chat(_valid(), observe=limiter.in_flight)
    rig = _rig(chat, retry_policy=POLICY, limiter=limiter)

    with pytest.raises(TurnFencedError) as raised:
        _run(rig.adapter, path)

    assert not isinstance(raised.value, ModelProviderUnavailableError)
    assert raised.value.request_id == RID
    assert checks, "the stop check never ran"
    assert chat.invocations == [], "a stopped turn made a model call"
    assert limiter.in_flight() == {}


@pytest.mark.parametrize("path", PATHS)
def test_a_stop_during_a_backoff_is_not_collapsed(path, monkeypatch):
    """A 429, then the turn is stopped while waiting to retry: the stop ends the call.

    It is not collapsed into a provider fault, and it does not carry the 429 (R3).
    """
    checks: list[str | None] = []

    def stopped_after_the_first_check(request_id: str | None = None) -> None:
        checks.append(request_id)
        if len(checks) > 1:
            raise TurnFencedError(RID)

    monkeypatch.setattr(model_calls, "check_turn_stopped", stopped_after_the_first_check)
    limiter = FairCallLimiter(2)
    chat = _Chat(_Fault(_rate_limited), _valid(), observe=limiter.in_flight)
    rig = _rig(chat, retry_policy=POLICY, limiter=limiter)

    with pytest.raises(TurnFencedError) as raised:
        _run(rig.adapter, path)

    assert not isinstance(raised.value, ModelProviderUnavailableError)
    assert model_fault_kind(raised.value) == "not_transient"
    assert len(chat.invocations) == 1, "a model call was retried after the stop"
    assert chat.observed == [{None: 1}]
    assert limiter.in_flight() == {}


# --------------------------------------------------------------------------- production defaults


@pytest.mark.parametrize("path", PATHS)
def test_the_production_adapter_turns_off_the_sdk_retries(path):
    """No transport options (production): the model is built with ``max_retries=0``."""
    constructed: list[dict[str, Any]] = []
    client = object()
    chat = _Chat(_valid())

    def fake(**kwargs: Any) -> _Chat:
        constructed.append(dict(kwargs))
        return chat

    adapter = DatabricksModelAdapter(model_factory=fake, client_factory=lambda: client)

    assert _run(adapter, path) == EXPECTED
    assert constructed == [_kwargs(client, max_retries=0)]


@pytest.mark.parametrize("path", PATHS)
def test_a_production_adapter_retries_without_being_given_a_policy(path):
    """Built with no ``retry_policy``, the adapter still retries a transient fault."""
    chat = _Chat(_Fault(_soon_rate_limited), _valid())
    rig = _rig(chat)

    assert _run(rig.adapter, path) == EXPECTED
    assert len(chat.invocations) == 2


@pytest.mark.parametrize("path", PATHS)
def test_a_production_adapter_holds_a_slot_of_the_process_limiter(path):
    """Built with no ``limiter``, each model call holds one slot of the process limiter."""
    assert get_model_call_limiter().in_flight() == {}, "another call holds a slot already"
    chat = _Chat(_valid(), observe=lambda: get_model_call_limiter().in_flight())
    rig = _rig(chat)

    assert _run(rig.adapter, path) == EXPECTED
    assert chat.observed == [{None: 1}]
    assert get_model_call_limiter().in_flight() == {}


def _spy_on_call_model(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record the keyword arguments of every ``call_model`` call, whichever way it is imported."""
    real = model_calls.call_model
    seen: list[dict[str, Any]] = []

    def spy(fn, **kwargs):
        seen.append(kwargs)
        return real(fn, **kwargs)

    monkeypatch.setattr(model_calls, "call_model", spy)
    monkeypatch.setattr(agent_runtime, "call_model", spy, raising=False)
    return seen


@pytest.mark.parametrize(
    ("path", "rounds"),
    [("invoke", 1), ("invoke_with_tools", 2)],
)
def test_every_production_model_call_uses_the_default_policy_and_the_process_limiter(
    path, rounds, monkeypatch
):
    """The production sentinels resolve to ``DEFAULT_RETRY_POLICY`` and the process limiter.

    One ``call_model`` call per model call: ``invoke``'s one, and each tool-loop round's.
    """
    seen = _spy_on_call_model(monkeypatch)
    chat = _Chat(_ask("q1", "call_1"), _valid()) if rounds == 2 else _Chat(_valid())
    rig = _rig(chat)

    assert _run(rig.adapter, path, agent_key="build_reviewer") == EXPECTED

    assert len(seen) == rounds == len(chat.invocations)
    for kwargs in seen:
        assert kwargs["agent_key"] == "build_reviewer"
        assert kwargs["policy"] == DEFAULT_RETRY_POLICY
        assert kwargs["limiter"] is get_model_call_limiter()


# --------------------------------------------------------------------------- explicit arguments


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize(
    "options",
    [{"timeout": 120.0, "max_retries": 0}, {"timeout": 1.5}],
    ids=["test-run-options", "timeout-only"],
)
def test_an_adapter_with_transport_options_is_unchanged(path, options, monkeypatch, caplog):
    """Transport options (admin test runs, evals): no Tellr retries, no limiter, as given."""
    caplog.set_level(logging.WARNING, logger=LOGGER)
    process_limiter = get_model_call_limiter()
    getter_calls: list[None] = []

    def no_process_limiter() -> FairCallLimiter:
        getter_calls.append(None)
        raise AssertionError("an adapter with transport options must not use the limiter")

    monkeypatch.setattr(model_calls, "get_model_call_limiter", no_process_limiter)
    monkeypatch.setattr(agent_runtime, "get_model_call_limiter", no_process_limiter, raising=False)
    chat = _Chat(_Fault(_soon_rate_limited), _valid(), observe=process_limiter.in_flight)
    rig = _rig(chat, transport_options=dict(options))

    with pytest.raises(ModelProviderUnavailableError) as raised:
        _run(rig.adapter, path)

    assert raised.value.__cause__ is chat.raised[0]
    assert len(chat.invocations) == 1, "an adapter with transport options retried"
    assert chat.observed == [{}]
    assert rig.constructed == [_kwargs(rig.client, **options)]
    assert getter_calls == []
    assert _lines(caplog, "model_call_") == []


@pytest.mark.parametrize("path", PATHS)
def test_explicit_no_retries_and_no_limiter_win_over_the_production_defaults(path):
    """``retry_policy=None`` / ``limiter=None`` on a production adapter mean exactly that.

    The transport is still production's (``max_retries=0``): only transport options set it.
    """
    process_limiter = get_model_call_limiter()
    chat = _Chat(_Fault(_soon_rate_limited), _valid(), observe=process_limiter.in_flight)
    rig = _rig(chat, retry_policy=None, limiter=None)

    with pytest.raises(ModelProviderUnavailableError) as raised:
        _run(rig.adapter, path)

    assert raised.value.__cause__ is chat.raised[0]
    assert len(chat.invocations) == 1
    assert chat.observed == [{}]
    assert rig.constructed == [_kwargs(rig.client, max_retries=0)]


@pytest.mark.parametrize("path", PATHS)
def test_an_explicit_policy_and_limiter_win_over_transport_options(path):
    limiter = FairCallLimiter(2)
    chat = _Chat(_Fault(_rate_limited), _valid(), observe=limiter.in_flight)
    rig = _rig(chat, transport_options={"timeout": 1.5}, retry_policy=POLICY, limiter=limiter)

    assert _run(rig.adapter, path) == EXPECTED
    assert len(chat.invocations) == 2
    assert chat.observed == [{None: 1}, {None: 1}]
    assert limiter.in_flight() == {}
    assert rig.constructed == [_kwargs(rig.client, timeout=1.5)]


# --------------------------------------------------------------------------- construction


@pytest.mark.parametrize("path", PATHS)
def test_a_transient_failure_building_the_model_is_not_retried(path):
    """Only the model's invoke runs inside ``call_model``; building it fails at once, as today."""
    error = httpx.ConnectError("refused")
    chat = _Chat(_valid())
    attempts: list[dict[str, Any]] = []

    def model_factory(**kwargs: Any) -> _Chat:
        attempts.append(dict(kwargs))
        if len(attempts) == 1:
            raise error
        return chat

    adapter = DatabricksModelAdapter(
        model_factory=model_factory,
        client_factory=lambda: object(),
        retry_policy=POLICY,
        limiter=FairCallLimiter(2),
    )

    with pytest.raises(ModelProviderUnavailableError) as raised:
        _run(adapter, path)

    assert raised.value.__cause__ is error
    assert len(attempts) == 1, "building the model was retried"
    assert chat.invocations == []
