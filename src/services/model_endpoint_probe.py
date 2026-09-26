"""#266 saved-candidate structured-output probe.

An administrator runs one role's *saved* draft model configuration once, under
the runtime identity, through the same structured-output binding helper the
runtime uses.  The probe proves only that this endpoint and configuration bind
and answer a code-owned minimal schema; it approves nothing and writes nothing.

Ownership boundaries:

* The endpoint, sampling values, hash and lock all come from the server-side
  saved candidate.  No request field can supply any of them.
* The prompt and response schema are code-owned constants.  The prompt carries
  no role, draft, session, user, turn or release value (#258 payload rule).
* This is not #267's versioned test-case, run, evidence or approval system.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import openai
from databricks.sdk.errors import PermissionDenied
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from src.services import agent_runtime
from src.services.agent_runtime import (
    AgentModelConfiguration,
    DatabricksModelAdapter,
    saved_model_configuration,
)
from src.services.graph_configuration import (
    DraftSaveConflict,
    GraphConfiguration,
)
from src.services.graph_definition_manifest import AgentKey

logger = logging.getLogger(__name__)

StructuredOutputProbeCode = Literal[
    "unsupported_structured_output",
    "endpoint_probe_forbidden",
    "structured_output_probe_failed",
]


class StructuredOutputProbeFailure(RuntimeError):  # noqa: N818 - stable public domain name
    """One sanitized probe outcome; its message is code-owned, never provider text."""

    def __init__(
        self,
        code: StructuredOutputProbeCode,
        message: str,
        retryable: bool,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


_UNSUPPORTED = (
    "unsupported_structured_output",
    "The endpoint rejected the structured-output test request.",
    False,
)
_FORBIDDEN = (
    "endpoint_probe_forbidden",
    "The app is not permitted to query this endpoint.",
    False,
)
_FAILED = (
    "structured_output_probe_failed",
    "The structured output probe could not complete. Retry the probe.",
    True,
)


class _StructuredOutputProbeResponse(BaseModel):
    """The code-owned probe schema: exactly one literal ``ok`` result."""

    model_config = ConfigDict(extra="forbid")

    result: Literal["ok"]


#: The code-owned synthetic prompt.  It deliberately names nothing about the
#: role, the draft, the endpoint or the requesting principal.
_PROBE_PROMPT = 'Reply with the single field result set to the string "ok".'

#: The probe holds no database lock (correction 13), but it runs inside one
#: admin request, so it must not inherit the provider client's default window
#: of ten minutes per attempt with retries.  One attempt with a finite
#: timeout; a timeout is the retryable ambiguous failure.  These are transport
#: bounds, not model configuration: the saved sampling values are unchanged.
PROBE_TIMEOUT_SECONDS = 30.0
PROBE_MAX_RETRIES = 0


#: The runtime's Databricks chat model talks to the endpoint through the openai
#: client, so these are the types a real provider rejection arrives as (measured over
#: ``databricks-langchain`` 0.9.0; fix round 1).  An authorization rejection is
#: forbidden; a request rejection (400, 404, 422) means the endpoint refused the
#: structured request, so it is unsupported and not worth retrying.  The copy
#: says only that the request was rejected: a deleted endpoint (404) or a saved
#: ``max_tokens`` the model refuses (400) arrives here too.  Rate
#: limits, 5xx, connection errors and timeouts stay the ambiguous retryable
#: failure.
_OPENAI_FORBIDDEN: tuple[type[BaseException], ...] = (
    openai.PermissionDeniedError,
    openai.AuthenticationError,
)
_OPENAI_UNSUPPORTED: tuple[type[BaseException], ...] = (
    openai.BadRequestError,
    openai.NotFoundError,
    openai.UnprocessableEntityError,
)


class StructuredOutputProbeAdapter(Protocol):
    """Probe one saved model configuration; raise ``StructuredOutputProbeFailure``."""

    def probe(self, configuration: AgentModelConfiguration) -> None: ...


class DatabricksStructuredOutputProbe:
    """Production adapter over the runtime's model factory and runtime identity.

    The defaults are ``DatabricksModelAdapter``'s own factories, so the probe
    constructs the same client the runtime does; construction does no work.
    Classification reads exception types only, never exception text:

    * ``NotImplementedError`` from the binding step, and an openai request
      rejection (400/404/422) from invocation, are ``unsupported``;
    * the SDK's ``PermissionDenied`` from binding or invocation, and an openai
      401/403 from invocation, are ``forbidden``;
    * every other failure (rate limit, 5xx, connection, timeout, anything
      else), and any result other than the exact ``ok`` schema instance, is
      the ambiguous retryable ``failed``.
    """

    def __init__(
        self,
        *,
        model_factory: Callable[..., Any] | None = None,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._model_factory = model_factory or DatabricksModelAdapter._default_model_factory
        self._client_factory = client_factory or DatabricksModelAdapter._default_client_factory

    def probe(self, configuration: AgentModelConfiguration) -> None:
        try:
            workspace_client = self._client_factory()
        except Exception as error:  # noqa: BLE001 - runtime identity unavailable
            raise _failure(_FAILED, error) from error
        try:
            bound = agent_runtime.bind_structured_output_model(
                model_factory=self._model_factory,
                workspace_client=workspace_client,
                configuration=configuration,
                schema=_StructuredOutputProbeResponse,
                transport_options={
                    "timeout": PROBE_TIMEOUT_SECONDS,
                    "max_retries": PROBE_MAX_RETRIES,
                },
            )
        except NotImplementedError as error:
            raise _failure(_UNSUPPORTED, error) from error
        except PermissionDenied as error:
            raise _failure(_FORBIDDEN, error) from error
        except Exception as error:  # noqa: BLE001 - ambiguous by contract
            raise _failure(_FAILED, error) from error
        try:
            output = bound.invoke(_PROBE_PROMPT)
        except PermissionDenied as error:
            raise _failure(_FORBIDDEN, error) from error
        except _OPENAI_FORBIDDEN as error:
            raise _failure(_FORBIDDEN, error) from error
        except _OPENAI_UNSUPPORTED as error:
            raise _failure(_UNSUPPORTED, error) from error
        except Exception as error:  # noqa: BLE001 - ambiguous by contract
            raise _failure(_FAILED, error) from error
        if not isinstance(output, _StructuredOutputProbeResponse) or output.result != "ok":
            raise _failure(_FAILED, None)


def _failure(
    outcome: tuple[StructuredOutputProbeCode, str, bool],
    error: BaseException | None,
) -> StructuredOutputProbeFailure:
    code, message, retryable = outcome
    # The class name only: provider text can carry hosts, URLs or tokens.
    logger.warning(
        "structured output probe outcome %s (%s)",
        code,
        type(error).__name__ if error is not None else "unexpected_output",
    )
    return StructuredOutputProbeFailure(code, message, retryable)


class FakeStructuredOutputProbe:
    """Deterministic adapter: replays queued outcomes, then succeeds.

    ``None`` in the queue is one success; a ``StructuredOutputProbeFailure`` is
    raised as-is.  ``calls`` records every configuration it was handed.
    """

    def __init__(
        self, outcomes: Iterable[StructuredOutputProbeFailure | None] = ()
    ) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[AgentModelConfiguration] = []

    def probe(self, configuration: AgentModelConfiguration) -> None:
        self.calls.append(configuration)
        if self._outcomes:
            outcome = self._outcomes.pop(0)
            if outcome is not None:
                raise outcome


@dataclass(frozen=True)
class SavedEndpointProbeIdentity:
    """The exact saved candidate a probe ran against, copied before the call."""

    agent_key: AgentKey
    endpoint_name: str
    candidate_hash: str
    lock_version: int


@dataclass(frozen=True)
class SavedEndpointProbeResult:
    identity: SavedEndpointProbeIdentity
    #: ``None`` is success.
    failure: StructuredOutputProbeFailure | None


class ModelEndpointProbeService:
    """Copy the saved candidate, release the database, then probe it once."""

    def __init__(
        self,
        adapter: StructuredOutputProbeAdapter,
        *,
        configuration_factory: Callable[[], GraphConfiguration] = GraphConfiguration,
    ) -> None:
        self._adapter = adapter
        self._configuration_factory = configuration_factory

    def probe_saved_candidate(
        self,
        session: Session,
        *,
        agent_key: AgentKey,
        expected_lock_version: int,
    ) -> SavedEndpointProbeResult | DraftSaveConflict[None]:
        """Raise ``DraftContentRejected`` for an invalid request or stored name.

        A stale lock returns the conflict and the adapter is never called.  The
        facade's transaction has ended before the adapter runs, and nothing is
        written on any path.
        """
        candidate = self._configuration_factory().read_draft_probe_candidate(
            session,
            agent_key=agent_key,
            expected_lock_version=expected_lock_version,
        )
        if isinstance(candidate, DraftSaveConflict):
            return candidate
        identity = SavedEndpointProbeIdentity(
            agent_key=candidate.agent_key,
            endpoint_name=candidate.model.endpoint_name,
            candidate_hash=candidate.candidate_hash,
            lock_version=candidate.lock_version,
        )
        try:
            self._adapter.probe(saved_model_configuration(candidate.model))
        except StructuredOutputProbeFailure as failure:
            return SavedEndpointProbeResult(identity=identity, failure=failure)
        return SavedEndpointProbeResult(identity=identity, failure=None)


__all__ = [
    "PROBE_MAX_RETRIES",
    "PROBE_TIMEOUT_SECONDS",
    "DatabricksStructuredOutputProbe",
    "FakeStructuredOutputProbe",
    "ModelEndpointProbeService",
    "SavedEndpointProbeIdentity",
    "SavedEndpointProbeResult",
    "StructuredOutputProbeAdapter",
    "StructuredOutputProbeCode",
    "StructuredOutputProbeFailure",
]
