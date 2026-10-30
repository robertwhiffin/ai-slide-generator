"""Eval harness runner: thread-safe run_candidate wrapper with infra-error retry.

The Runner constructs its own AgentRuntime with a stub loader whose .resolve()
always raises AssertionError (the harness never resolves a release) and a bounded
DatabricksModelAdapter.  The model_adapter is injectable for tests.

Thread safety: run_candidate builds a fresh ResolvedDefinition per call and uses
a pass-through identity sink.  PromptAssembler and AgentSchemaRegistry are
read-only after construction.  The _OBSERVED_TEST_RUN ContextVar is per-thread,
so no shared mutable state is written across concurrent calls.

The brand-asset search (deck style addendum A): a builder or fixer run on a deck
style with a design system active gets a fake ``search_brand_assets`` on its
``AgentAssemblyContext``, as ``builder_node`` and ``fixer_node`` bind the real
one.  It answers from the Meridian fake asset index and records each call on
the run's own list, returned as ``RunResult.tool_calls``.
"""

from __future__ import annotations

import html
import json
import logging
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Mapping, Optional

import src.core.database  # break import cycle before src.services imports  # noqa: F401

from evals.harness.case import MERIDIAN_DIR
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
    #: The run's brand-asset searches, in call order: ``{"name": "search_brand_assets",
    #: "args": {"query": ..., "kind": ...}}`` each (JSON-serialisable). Empty when no tool was
    #: bound or the model never called it.
    tool_calls: tuple = ()


#: The roles production binds the brand-asset search for (``nodes._brand_search_tools``).
BRAND_SEARCH_ROLES = ("builder", "fixer")
#: The Meridian fake asset index the fake search answers from (the architect's logo read uses
#: the same file, ``case.meridian_deck_style_context``).
ASSET_INDEX_FILE = MERIDIAN_DIR / "assets.json"
SEARCH_TOOL_NAME = "search_brand_assets"


def _binds_brand_search(
    config: AgentEvalConfig, payload: Mapping[str, Any], design_system_active: bool
) -> bool:
    """Whether a run gets the brand-asset search: production's gate (``nodes._brand_search_tools``)
    as the harness can see it.

    A builder or fixer, a design system active and a deck style in the payload.  The run's
    ``design_system_active`` stands for both production's payload flag (a fixer payload carries
    none) and its design-contract id (an eval payload carries no contract).
    """
    return (
        config.agent_key in BRAND_SEARCH_ROLES
        and bool(design_system_active)
        and payload.get("deck_style") is not None
    )


def _fake_brand_search(record: list[dict]) -> Any:
    """A ``search_brand_assets`` tool production-shaped to the model, over the fake asset index.

    It keeps ``build_ds_asset_tool``'s name, description and arguments, filters and ranks as
    ``design_system_service.search_assets`` does (its own excluded kinds and sort key), and
    answers in ``build_ds_asset_tool``'s JSON.  The index holds fewer rows than production's
    row cap, so no cap applies.  Each call is appended to ``record`` before it is answered.
    """
    from langchain_core.tools import StructuredTool

    from src.services.design_system_service import (
        _TOOL_EXCLUDED_ASSET_KINDS,
        _asset_search_sort_key,
    )
    from src.services.tools.ds_asset_tool import SearchBrandAssetsInput, build_ds_asset_tool
    from src.utils.ds_asset_utils import DS_ASSET_PLACEHOLDER_PATTERN

    production = build_ds_asset_tool(0)  # for its name and description only: never invoked
    assets = [
        SimpleNamespace(
            id=int(DS_ASSET_PLACEHOLDER_PATTERN.fullmatch(row["handle"]).group(1)),
            kind=row["kind"],
            filename=row["filename"],
        )
        for row in json.loads(ASSET_INDEX_FILE.read_text())
    ]

    def _search_brand_assets(query: Optional[str] = None, kind: Optional[str] = None) -> str:
        record.append({"name": SEARCH_TOOL_NAME, "args": {"query": query, "kind": kind}})
        found = [a for a in assets if (a.kind or "").lower() not in _TOOL_EXCLUDED_ASSET_KINDS]
        if kind:
            kind_l = kind.strip().lower()
            found = [a for a in found if (a.kind or "").lower() == kind_l]
        if query:
            query_l = query.strip().lower()
            found = [a for a in found if query_l in (a.filename or "").lower()]
        found.sort(key=_asset_search_sort_key)
        rows = [
            {
                "id": a.id,
                "kind": a.kind,
                "filename": a.filename,
                "usage": '<img src="{{ds-asset:%d}}" alt="%s"/>'
                % (a.id, html.escape(str(a.filename or ""))),
            }
            for a in found
        ]
        if not rows:
            return json.dumps(
                {"message": "No brand assets found for this design system.", "assets": []})
        return json.dumps({"message": f"Found {len(rows)} brand asset(s).", "assets": rows})

    return StructuredTool.from_function(
        func=_search_brand_assets,
        name=production.name,
        description=production.description,
        args_schema=SearchBrandAssetsInput,
    )


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


def _failure_detail(outcome: CandidateRunOutcome) -> str | None:
    """The runtime's error_detail plus the exception's message, for content failures.

    The runtime keeps only the exception class in ``error_detail`` (``invalid_output:
    ValidationError``), which cannot tell an optimiser which field was wrong.  For a
    run that is neither completed nor an infra error, append the exception's message
    and that of its cause (pydantic lists field locations and offending input values),
    e.g. ``invalid_output:ValidationError: <message>``.  Infra errors and completed
    runs keep the runtime's detail unchanged; ``_is_infra_error`` always reads the
    outcome's own detail, never this string.
    """
    detail = outcome.error_detail
    if outcome.status == "completed" or _is_infra_error(outcome) or outcome.error is None:
        return detail
    messages = [str(outcome.error)]
    cause = outcome.error.__cause__
    if cause is not None and str(cause) not in messages:
        messages.append(str(cause))
    message = "\n".join(m for m in messages if m)
    if not message:
        return detail
    return f"{detail}: {message}" if detail else message


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

        A builder or fixer run on a deck style with a design system active is handed the fake
        brand-asset search (``_binds_brand_search``); every other run binds no tool, exactly as
        before.  Each attempt gets a fresh search and record, so the result's ``tool_calls`` are
        the searches of the attempt it reports.
        """
        binds_search = _binds_brand_search(config, payload, design_system_active)
        obs = RunObservation()
        record: list[dict] = []
        outcome: CandidateRunOutcome | None = None

        for attempt in range(self._max_infra_retries + 1):
            if attempt > 0:
                # Exponential backoff: 1s, 2s, 4s, … before each retry.
                time.sleep(2 ** (attempt - 1))

            record = []
            tools = (_fake_brand_search(record),) if binds_search else ()
            assembly_ctx = AgentAssemblyContext(design_system_active, tools=tools)
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
            error_detail=_failure_detail(outcome),
            infra_error=infra_error,
            tool_calls=tuple(record),
        )
