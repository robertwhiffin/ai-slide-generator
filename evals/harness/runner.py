"""Eval harness runner: thread-safe run_candidate wrapper with infra-error retry.

The Runner constructs its own AgentRuntime with a stub loader whose .resolve()
always raises AssertionError (the harness never resolves a release) and a bounded
DatabricksModelAdapter.  The model_adapter is injectable for tests.

Thread safety: run_candidate builds a fresh ResolvedDefinition per call and uses
a pass-through identity sink.  PromptAssembler and AgentSchemaRegistry are
read-only after construction.  The _OBSERVED_TEST_RUN ContextVar is per-thread,
so no shared mutable state is written across concurrent calls.

The brand-asset search (deck style addendum A): a builder or fixer run on a deck
style with a design system active gets the brand-search toolset, as
``builder_node`` and ``fixer_node`` do.  It is production's
(``brand_search.build_brand_search_toolset``, the same tool, row cap, spotlight
and call budget); only its search backend is faked, answering from the Meridian
fake asset index and recording each call on the run's own list, returned as
``RunResult.tool_calls``.

The architect's image tool (chat image generation, Task 9): an architect run of a config
that opts in (``image_tool: true``) gets production's ``generate_image`` tool
(``ImageGenerationAgentTool``: its name, description, args schema, caps and spotlighted
answer) on a toolset of production's first-pass budget, as ``architect_node`` binds it
(``_ImageToolPass`` and ``_architect_toolset``).  Only its backends are faked: the generator
answers with a small valid image of the preset's format and the Library save returns a fresh
token, so nothing reaches a model, a network or a database.  Each call the tool starts, and
each image it saves, is recorded on the run's own list (``RunResult.tool_calls``).  A config
that does not opt in binds nothing for the architect, exactly as before.

A test run's context never carries a toolset (``AgentRuntime.run_candidate``
refuses one), so the toolset reaches the model through the Runner's adapter
instead: :class:`_ToolLoopAdapter` hands it to the inner adapter's
``invoke_with_tools``, the same tool loop ``builder_node``'s runs reach through
``AgentRuntime``.  The toolset of the run in flight rides a ContextVar, per thread.
"""

from __future__ import annotations

import html
import io
import json
import logging
import secrets
import threading
import time
from contextvars import ContextVar
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Mapping, Optional

import src.core.database  # break import cycle before src.services imports  # noqa: F401
from evals.harness.case import MERIDIAN_DIR
from evals.harness.config import DATA_TOOLS_ROLES, IMAGE_TOOL_ROLES, AgentEvalConfig
from src.services.agent_runtime import (
    AgentAssemblyContext,
    AgentRuntime,
    CandidateRunOutcome,
    DatabricksModelAdapter,
    RunObservation,
)
from src.services.agent_runtime_identity import LoggingAgentInvocationIdentitySink
from src.services.agent_tools.brand_search import build_brand_search_toolset
from src.services.agent_tools.toolset import AgentToolset

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
    #: The run's tool calls, in call order, JSON-serialisable. A brand-asset search is
    #: ``{"name": "search_brand_assets", "args": {"query": ..., "kind": ...}}``; an image call
    #: the architect's tool started is ``{"name": "generate_image", "args": {"kind": ...,
    #: "count": ...}, "saved": [{"token", "prompt", "category", "tags"}, ...]}``. Empty when no
    #: tool was bound or the model never called it.
    tool_calls: tuple = ()


#: The roles production binds the brand-asset search for (``nodes._brand_search_toolset``).
BRAND_SEARCH_ROLES = ("builder", "fixer")
#: The Meridian fake asset index the fake search answers from (the architect's logo read uses
#: the same file, ``case.meridian_deck_style_context``).
ASSET_INDEX_FILE = MERIDIAN_DIR / "assets.json"
SEARCH_TOOL_NAME = "search_brand_assets"


def _binds_brand_search(
    config: AgentEvalConfig, payload: Mapping[str, Any], design_system_active: bool
) -> bool:
    """Whether a run gets the brand-asset search: production's gate
    (``nodes._brand_search_toolset``) as the harness can see it.

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
    """The fake search backend: ``build_ds_asset_tool``'s shape, over the fake asset index.

    It keeps ``build_ds_asset_tool``'s name, description and arguments, filters and ranks as
    ``design_system_service.search_assets`` does (its own excluded kinds and sort key), and
    answers in ``build_ds_asset_tool``'s JSON.  Production's brand-search tool wraps it
    (:func:`_fake_brand_search_toolset`); the index holds fewer rows than that tool's row cap.
    Each call is appended to ``record`` before it is answered.
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


def _fake_brand_search_toolset(record: list[dict]) -> AgentToolset:
    """Production's brand-search toolset over the fake backend: a fresh one per run."""
    return build_brand_search_toolset(_fake_brand_search(record))


def _binds_image_tool(config: AgentEvalConfig) -> bool:
    """Whether a run gets the architect's image tool: its config opted in (``image_tool``).

    Production binds it for the architect when image generation is available and the turn is
    not the sweeper's describe-only one; in the harness the config's opt-in stands for both.
    """
    return config.agent_key in IMAGE_TOOL_ROLES and config.image_tool


#: The owner the fake Library save is handed (the tool refuses to run without one). Never a
#: real user: nothing is saved.
EVAL_IMAGE_OWNER = "eval-harness"

#: A small valid image per preset output format: (Pillow format or None, mime, extension).
_FAKE_IMAGE_FORMATS = {
    "jpeg": ("JPEG", "image/jpeg", "jpg"),
    "png": ("PNG", "image/png", "png"),
    "svg": (None, "image/svg+xml", "svg"),
}
_FAKE_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" width="16" height="16">'
    b'<circle cx="8" cy="8" r="6" fill="#0f766e"/></svg>'
)


def _fake_image_bytes(output_format: str) -> tuple[bytes, str, str]:
    """``(data, mime, ext)`` of a small valid image in a preset's ``output_format``."""
    pil_format, mime, ext = _FAKE_IMAGE_FORMATS[output_format]
    if pil_format is None:
        return _FAKE_SVG, mime, ext
    from PIL import Image

    buf = io.BytesIO()
    mode = "RGBA" if pil_format == "PNG" else "RGB"
    Image.new(mode, (24, 16), (15, 118, 110)).save(buf, format=pil_format)
    return buf.getvalue(), mime, ext


class _FakeImageGenerator:
    """``ImageGenerator.generate``'s shape, with no client: a small valid image, at once.

    The request is resolved by production's ``resolve_request`` (an unknown preset or model fails
    as it does there), and the image carries the preset's default model, which the tool tags.
    """

    def generate(self, prompt, preset_id, model=None, quality=None, *, timeout_s=None):
        del prompt, timeout_s
        from src.services.image_generation import GeneratedImage, resolve_request

        preset, model, _quality = resolve_request(preset_id, model, quality)
        data, mime, ext = _fake_image_bytes(preset.output_format)
        return GeneratedImage(
            data=data, mime=mime, ext=ext, model=model, preset_id=preset.id,
            revised_prompt=None, latency_s=0.0, usage=None,
        )


def _fake_image_toolset(record: list[dict]) -> AgentToolset:
    """Production's ``generate_image`` tool over fake backends: a fresh one per attempt.

    Sized as ``_ImageToolPass.tool`` sizes a turn's first pass (``turn_budget`` over the tool's
    per-turn caps, the turn deadline from now), on a toolset of that budget alone, as
    ``_architect_toolset`` builds one with no Gateway tools.  The tool's ``on_call`` opens the
    call's entry on ``record`` (``{"name", "args": {"kind", "count"}, "saved": []}``); each save
    appends ``{"token", "prompt", "category", "tags"}`` to it and returns a fresh token shaped as
    the Image Library mints one (``secrets.token_urlsafe(32)``, 43 url-safe characters).
    """
    from src.services.agent_tools.gateway_toolset import (
        GATEWAY_TURN_DEADLINE_SECONDS,
        turn_budget,
    )
    from src.services.agent_tools.image_generation_tool import (
        BUDGET_SECONDS,
        IMAGE_TOOL_NAME,
        MAX_CALLS_PER_TURN,
        MAX_IMAGES_PER_TURN,
        ImageGenerationAgentTool,
        ImageToolContext,
    )

    lock = threading.Lock()

    def on_call(kind: str, count: int) -> None:
        with lock:
            record.append({"name": IMAGE_TOOL_NAME, "args": {"kind": kind, "count": count},
                           "saved": []})

    def save(img, *, owner, prompt, category, tags) -> str:
        del img, owner
        token = secrets.token_urlsafe(32)
        with lock:
            if not record or record[-1].get("name") != IMAGE_TOOL_NAME:
                record.append({"name": IMAGE_TOOL_NAME, "args": {}, "saved": []})
            record[-1]["saved"].append(
                {"token": token, "prompt": prompt, "category": category, "tags": list(tags)})
        return token

    now = time.time()
    calls_left, seconds_left = turn_budget(
        used_calls=0, used_seconds=0.0, max_calls=MAX_CALLS_PER_TURN,
        budget_seconds=BUDGET_SECONDS, turn_started_at=now, now=now,
    )
    tool = ImageGenerationAgentTool(ImageToolContext(
        owner=EVAL_IMAGE_OWNER,
        session_id=None,
        on_call=on_call,
        calls_left=calls_left,
        images_left=MAX_IMAGES_PER_TURN,
        seconds_left=seconds_left,
        deadline_at=now + GATEWAY_TURN_DEADLINE_SECONDS,
        generator_factory=_FakeImageGenerator,
        save=save,
    ))
    return AgentToolset(tools=(tool,), max_calls=calls_left, budget_seconds=seconds_left)


def _binds_data_tools(config: AgentEvalConfig) -> bool:
    """Whether a run gets the analyst's fake data tools: its config opted in (``data_tools``)."""
    return config.agent_key in DATA_TOOLS_ROLES and config.data_tools


#: What the Sales fake Genie Agent is described as (a Genie space's own description).
FAKE_SALES_DESCRIPTION = "Regional sales by month: revenue, units and orders per region"
FAKE_SALES_SPACE = "Sales"
FAKE_WEB_TOOL_NAME = "you-search"


class _FakeGenieClient:
    """``GenieOneClient.ask`` / ``GenieAgentClient.ask``'s shape, with no network: one canned
    answer holding one small result table, the call recorded on the run's list."""

    def __init__(self, record: list[dict], lock: threading.Lock, *, tool_name: str, source: str,
                 columns: tuple[str, ...], rows: tuple[tuple[str, ...], ...], summary: str):
        self._record = record
        self._lock = lock
        self._tool_name = tool_name
        self._source = source
        self._columns = columns
        self._rows = rows
        self._summary = summary

    def ask(self, question, *, conversation_id, timeout_seconds):
        from src.services.agent_tools.genie_one import GenieOneAnswer, GenieOneQueryResult

        del timeout_seconds
        with self._lock:
            self._record.append({"name": self._tool_name, "args": {"question": question}})
        return GenieOneAnswer(
            conversation_id=conversation_id or "eval-conversation",
            response_id="eval-response",
            status="completed",
            final_answer=self._summary,
            deep_link=None,
            query_results=(GenieOneQueryResult(
                item_id="eval-result", sql=None, columns=self._columns, rows=self._rows,
                total_row_count=len(self._rows), truncated=False),),
            source=self._source,
        )


class _FakeGatewayClient:
    """``GatewayMcpClient.call_tool``'s shape, with no network: a canned web-search answer."""

    def __init__(self, record: list[dict], lock: threading.Lock, *, tool_name: str):
        self._record = record
        self._lock = lock
        self._tool_name = tool_name

    def call_tool(self, name, arguments, *, timeout_seconds=None):
        del name, timeout_seconds
        with self._lock:
            self._record.append({"name": self._tool_name, "args": dict(arguments)})
        text = (
            "Top result: Industry analysts estimate the global market for this category at "
            "roughly 80 billion dollars in 2025 (source: example-research.test/market-report)."
        )
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)], structuredContent=None, isError=False)


def _fake_data_toolset(record: list[dict]) -> AgentToolset:
    """The analyst's toolset over fake clients: production's ``GenieOneAgentTool`` (``genie``),
    ``GenieAgentTool`` (``genie_agent_sales``) and one ``GatewayMcpAgentTool`` (``you-search``),
    on the budget production gives an analyst with more than Genie One. Fresh per attempt."""
    from src.services.agent_tools.gateway_mcp import GatewayToolSpec
    from src.services.agent_tools.gateway_tool import GatewayMcpAgentTool, GatewayToolContext
    from src.services.agent_tools.gateway_toolset import (
        ANALYST_GATEWAY_BUDGET_SECONDS,
        ANALYST_GATEWAY_MAX_CALLS,
        GATEWAY_TURN_DEADLINE_SECONDS,
        turn_budget,
    )
    from src.services.agent_tools.genie_agent import (
        GenieAgentTool,
        genie_agent_source,
        genie_agent_tool_names,
    )
    from src.services.agent_tools.genie_one import GENIE_ONE_SOURCE
    from src.services.agent_tools.registry import GENIE_ONE_MAX_QUESTIONS, GenieOneAgentTool

    lock = threading.Lock()
    (sales_name,) = genie_agent_tool_names([FAKE_SALES_SPACE])
    sales_source = genie_agent_source(FAKE_SALES_SPACE)

    genie = GenieOneAgentTool(
        _FakeGenieClient(
            record, lock, tool_name="genie", source=GENIE_ONE_SOURCE,
            columns=("month", "tickets_opened"),
            rows=(("2026-01", "412"), ("2026-02", "388"), ("2026-03", "451")),
            summary="Support tickets opened per month are in the table."),
        conversation_id=None, on_question=lambda q: None, session_id=None,
        max_questions=GENIE_ONE_MAX_QUESTIONS)
    sales = GenieAgentTool(
        _FakeGenieClient(
            record, lock, tool_name=sales_name, source=sales_source,
            columns=("region", "revenue"),
            rows=(("EMEA", "4200000"), ("AMER", "6100000"), ("APAC", "2900000")),
            summary="Revenue by region is in the table."),
        model_name=sales_name, space_id="eval-sales-space", space_name=FAKE_SALES_SPACE,
        user_description=FAKE_SALES_DESCRIPTION, conversation_id=None,
        on_question=lambda space, q: None, session_id=None)
    web = GatewayMcpAgentTool(
        GatewayToolSpec(
            name="you-search",
            description="Search the web and return the top results for a query.",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}},
                          "required": ["query"]}),
        GatewayToolContext(
            display_name="You.com", service_name="you-com",
            client=_FakeGatewayClient(record, lock, tool_name=FAKE_WEB_TOOL_NAME),
            save_image=lambda data, mime: "", on_call=lambda label: None, session_id=None),
        model_name=FAKE_WEB_TOOL_NAME, description_prefix=None)

    now = time.time()
    calls_left, seconds_left = turn_budget(
        used_calls=0, used_seconds=0.0, max_calls=ANALYST_GATEWAY_MAX_CALLS,
        budget_seconds=ANALYST_GATEWAY_BUDGET_SECONDS, turn_started_at=now, now=now,
        deadline_seconds=GATEWAY_TURN_DEADLINE_SECONDS)
    return AgentToolset(tools=(genie, sales, web), max_calls=calls_left, budget_seconds=seconds_left)


#: The toolset of the run in flight on this thread (brand search or image tool), or ``None``.
_RUN_TOOLSET: ContextVar[AgentToolset | None] = ContextVar("eval_run_toolset", default=None)


class _ToolLoopAdapter:
    """The Runner's model seam: the production tool loop for a run that binds the search.

    The runtime calls ``invoke`` with its four keywords, as for every test run.  With the
    run's toolset set (:data:`_RUN_TOOLSET`) this calls the inner adapter's
    ``invoke_with_tools`` with it, the loop production reaches through ``AgentRuntime`` for a
    context that carries a toolset; otherwise it is the inner adapter's own single call.  An
    inner adapter without the loop refuses a toolset, as ``AgentRuntime`` does.
    """

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    def invoke(self, *, agent_key, configuration, schema, prompt):
        toolset = _RUN_TOOLSET.get()
        if toolset is None:
            return self.inner.invoke(
                agent_key=agent_key, configuration=configuration, schema=schema, prompt=prompt
            )
        invoke_with_tools = getattr(self.inner, "invoke_with_tools", None)
        if invoke_with_tools is None:
            raise TypeError("model adapter cannot run tools")
        return invoke_with_tools(
            agent_key=agent_key,
            configuration=configuration,
            schema=schema,
            prompt=prompt,
            toolset=toolset,
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
            model_adapter=_ToolLoopAdapter(adapter),
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

        A builder or fixer run on a deck style with a design system active is handed the
        brand-search toolset over the fake backend (``_binds_brand_search``); an architect run
        of a config that opts in is handed the image tool over fake backends
        (``_binds_image_tool``); every other run binds no tool, exactly as before.  Each attempt
        gets a fresh toolset and record, so its budget is its own and the result's
        ``tool_calls`` are the calls of the attempt it reports.
        """
        binds_search = _binds_brand_search(config, payload, design_system_active)
        binds_image = _binds_image_tool(config)
        binds_data = _binds_data_tools(config)
        obs = RunObservation()
        record: list[dict] = []
        outcome: CandidateRunOutcome | None = None

        for attempt in range(self._max_infra_retries + 1):
            if attempt > 0:
                # Exponential backoff: 1s, 2s, 4s, … before each retry.
                time.sleep(2 ** (attempt - 1))

            record = []
            toolset = (
                _fake_brand_search_toolset(record) if binds_search
                else _fake_image_toolset(record) if binds_image
                else _fake_data_toolset(record) if binds_data
                else None
            )
            obs = RunObservation()
            scope = _RUN_TOOLSET.set(toolset)
            try:
                outcome = self._runtime.run_candidate(
                    config.agent_key,
                    config.content,
                    config.content_hash,
                    payload,
                    AgentAssemblyContext(design_system_active),
                    observation=obs,
                )
            finally:
                _RUN_TOOLSET.reset(scope)

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
