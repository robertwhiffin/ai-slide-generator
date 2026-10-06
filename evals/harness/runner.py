"""Eval harness runner: thread-safe run_candidate wrapper with infra-error retry.

The Runner constructs its own AgentRuntime with a stub loader whose .resolve()
always raises AssertionError (the harness never resolves a release) and a bounded
DatabricksModelAdapter.  The model_adapter is injectable for tests.

Thread safety: run_candidate builds a fresh ResolvedDefinition per call and uses
a pass-through identity sink.  PromptAssembler and AgentSchemaRegistry are
read-only after construction.  The _OBSERVED_TEST_RUN ContextVar is per-thread,
so no shared mutable state is written across concurrent calls.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import src.core.database  # break import cycle before src.services imports  # noqa: F401

from evals.harness.config import AgentEvalConfig
from src.services.agent_runtime import (
    AgentAssemblyContext,
    AgentRuntime,
    CandidateRunOutcome,
    DatabricksModelAdapter,
    RunObservation,
)
from src.services.agent_runtime_identity import LoggingAgentInvocationIdentitySink

logger = logging.getLogger(__name__)


class _StubLoader:
    """Stub definition loader whose .resolve() always raises AssertionError.

    The eval harness runner calls run_candidate, which constructs a
    ResolvedDefinition directly from the candidate content and never touches the
    loader.  Any call to .resolve() indicates a caller mistake.
    """

    def resolve(self, graph_release_id: int, agent_key: str) -> None:  # type: ignore[return]
        raise AssertionError(
            "The eval harness stub loader must never resolve a release. "
            f"Attempted to resolve graph_release_id={graph_release_id!r}, "
            f"agent_key={agent_key!r}.  Use run_candidate, not run."
        )


@dataclass(frozen=True)
class RunResult:
    """Outcome of one candidate run through the eval harness."""

    status: str
    structured: dict | None
    raw: dict | None
    prompt: str | None
    latency_ms: float | None
    input_tokens: int | None
    output_tokens: int | None
    error_detail: str | None
    infra_error: bool


def _is_infra_error(outcome: CandidateRunOutcome) -> bool:
    """Return True if the outcome represents a transient infrastructure error.

    Infra errors are model_error outcomes whose error_detail starts with
    ``endpoint_unavailable:`` (a PinnedInvocationEndpointError) or
    ``unexpected_error:`` (any other unexpected provider-side failure).
    A ``contract``/``incomplete`` failure is a real content failure and is
    never considered an infra error.
    """
    if outcome.status != "model_error":
        return False
    if outcome.error_detail is None:
        return False
    return outcome.error_detail.startswith(
        "endpoint_unavailable:"
    ) or outcome.error_detail.startswith("unexpected_error:")


class Runner:
    """Thread-safe runner over AgentRuntime.run_candidate with infra-error retry.

    A single Runner instance may be shared across threads safely: run_candidate
    builds a fresh ResolvedDefinition per call and the _OBSERVED_TEST_RUN
    ContextVar is per-thread context, so no shared mutable state is written.

    Parameters
    ----------
    model_adapter:
        Injectable adapter for tests.  When None, a bounded
        DatabricksModelAdapter(transport_options={"timeout": 120.0,
        "max_retries": 0}) is used.
    max_infra_retries:
        Maximum number of retry attempts on an infra error.  After
        max_infra_retries retries (total = 1 + max_infra_retries attempts)
        the run returns RunResult(infra_error=True).  Default: 3.
    """

    def __init__(self, *, model_adapter=None, max_infra_retries: int = 3) -> None:
        self._max_infra_retries = max_infra_retries
        adapter = (
            model_adapter
            if model_adapter is not None
            else DatabricksModelAdapter(
                transport_options={"timeout": 120.0, "max_retries": 0}
            )
        )
        self._runtime = AgentRuntime(
            persisted_release_loader=_StubLoader(),
            model_adapter=adapter,
            identity_sink=LoggingAgentInvocationIdentitySink(logger=logger),
        )

    def run(
        self,
        config: AgentEvalConfig,
        payload: dict,
        *,
        design_system_active: bool,
    ) -> RunResult:
        """Run one candidate definition through run_candidate with infra-error retry.

        Retries only when the outcome is an infra error (model_error with
        endpoint_unavailable: or unexpected_error: detail) using exponential
        backoff (2^attempt seconds before each retry).  Any other failure
        (incomplete, assembly_error, contract) is returned as-is.  After
        max_infra_retries retries returns RunResult(infra_error=True).
        """
        assembly_ctx = AgentAssemblyContext(design_system_active)
        obs = RunObservation()
        outcome: CandidateRunOutcome | None = None

        for attempt in range(self._max_infra_retries + 1):
            if attempt > 0:
                # Exponential backoff: 1s, 2s, 4s, … before each retry.
                time.sleep(2 ** (attempt - 1))

            obs = RunObservation()
            outcome = self._runtime.run_candidate(
                config.agent_key,
                config.content,
                config.content_hash,
                payload,
                assembly_ctx,
                observation=obs,
            )

            if not _is_infra_error(outcome):
                # Completed or a real failure (incomplete, assembly_error):
                # return as-is, never retry.
                break
            # Infra error: retry if attempts remain.

        assert outcome is not None  # loop runs at least once

        infra_error = _is_infra_error(outcome)

        structured: dict | None = None
        if outcome.result is not None:
            structured = outcome.result.output.model_dump(mode="python")

        return RunResult(
            status=outcome.status,
            structured=structured,
            raw=dict(outcome.raw_output) if outcome.raw_output is not None else None,
            prompt=obs.prompt,
            latency_ms=obs.model_latency_ms,
            input_tokens=obs.input_tokens,
            output_tokens=obs.output_tokens,
            error_detail=outcome.error_detail,
            infra_error=infra_error,
        )
