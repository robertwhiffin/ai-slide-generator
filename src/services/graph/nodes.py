"""The nodes of the deck-generation graph.

Six graph nodes: ``architect``, ``data_analyst``, ``foreman``,
``slide_pipeline``, ``placeholder``, ``deck_reviewer``.

``slide_pipeline`` runs four STAGE functions in sequence for one slide:
``builder_node``, ``build_reviewer_node``, ``fixer_node`` and
``fix_reviewer_node``.  They were graph nodes until the superstep barrier was
measured to serialise every deck behind its slowest slide and run fixes one at a
time (see :func:`slide_pipeline_node`); they keep their own contracts and
tests, and the pipeline folds their updates with ``GraphState``'s reducers.

Two node kinds, and the difference decides everything
-----------------------------------------------------
*Edge-reached* nodes (``architect``, ``data_analyst``, ``foreman``,
``placeholder``, ``deck_reviewer``) receive ``GraphState``.

The *``Send``-reached* node (``slide_pipeline``) receives **only its payload** —
measured: a Send-reached node saw ``['batch', 'position']`` and no state key at
all.  That is why :func:`build_branch_payload` pre-copies everything a branch
needs.  Within the pipeline, ``builder_node`` and ``build_reviewer_node`` take
payload-shaped input, and ``fixer_node`` / ``fix_reviewer_node`` take a
slide-local state the pipeline assembles from that payload.

What each node may return
-------------------------
``GraphState`` is an **exhaustive** contract: the runtime silently drops an
undeclared key, so a node returning one produces no error and no write.  Every
key returned below is declared in ``state.py``; ``tests/unit/test_graph_nodes.py``
greps this module's returns against the TypedDict as a standing check.

Who writes the dispatch marker
------------------------------
Only ``foreman_node`` writes ``dispatched_at``, and it writes it **before** the
batch runs.  Written on builder *return* it would be a completion timestamp, and
``stalled_positions`` could never observe the case it exists for (a branch that
hung or died never returns).  No node tombstones a ``dispatched_at`` entry: a
landed or placeheld position is excluded from ``outstanding`` before the
in-flight count is taken, so a live timestamp on a committed position costs
nothing — and clearing it on completion would make a position whose *reviewer*
died read as never-dispatched, which is exactly the case limb 1 of
``stalled_positions`` exists to catch.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from dataclasses import replace as dataclass_replace
from typing import Any, Dict, Final, List, Literal, Optional, Sequence, Set, Tuple, get_type_hints

from src.api.schemas.agent_config import AgentConfig, GenieOneTool, resolve_agent_config
from src.api.schemas.streaming import StreamEvent, StreamEventType
from src.api.services.deck_level_writer import read_deck_spec, write_deck_level_columns
from src.api.services.session_manager import get_session_manager, resolve_streamed_ds_assets
from src.api.services.slide_repository import (
    SlideRowsChangedError,
    SlideWriter,
    is_placeholder_record,
    is_placeholder_verdict,
    layout_mutation_operation,
)
from src.core.database import get_db_session
from src.core.databricks_client import get_user_client
from src.core.scope_errors import (
    consent_message,
    oauth_client_id_from_token,
    oauth_scopes_from_token,
    scopes_grant,
)
from src.database.models.design_system import DesignSystem, DesignSystemTemplate
from src.database.models.session import SessionSlideDeck, UserSession
from src.domain.deck_spec import DeckSpec, DesignContractRef, ResolvedFigure, SlideSpec
from src.domain.deck_spec_slides import is_blank_slide_html, is_blank_slide_spec
from src.domain.deck_style import (
    css_class_names,
    deck_style_context,
    dropped_classes_in_use,
    rank_logos,
    sanitise_deck_style,
)
from src.domain.finding import (
    CRITERIA,
    Finding,
    build_verification_record,
    make_finding_id,
)
from src.domain.finding_copy import (
    DECK_ADVISORY_CLOSING,
    DECK_ADVISORY_HEADER_PREFIX,
    DECK_ADVISORY_HEADER_SUFFIX,
    REVIEWER_DETAILS_SEPARATOR,
    deck_advisory_issue,
)
from src.domain.slide_alignment import AlignmentRefused, SlideAlignment, align_slides
from src.domain.slide_deck import SlideDeck
from src.domain.slide_numbering import architect_slide_payload, edit_ignores_references
from src.domain.slide_operations import (
    DeckChanges,
    OperationProblem,
    OperationProblems,
    OperationsResult,
    apply_operations,
    compose_edit_spec,
    dropped_class_problem,
    problem_sentence,
)
from src.services.agent import SAFETY_RETRY_NOTICE, UnsafeContentError
from src.services.agent_runtime import (
    AgentAssemblyContext,
    get_agent_runtime,
    is_provider_parse_error,
    is_transient_model_failure,
)
from src.services.agent_tools.genie_one import (
    GENIE_ONE_SCOPE,
    GENIE_ONE_SOURCE,
    GenieOneAnswer,
    figures_from_answer,
)
from src.services.agent_tools.registry import GenieOneAgentTool, build_analyst_toolset
from src.services.agent_tools.toolset import AgentToolset
from src.services.deck_css_aggregator import aggregate_deck_css
from src.services.deck_review_store import (
    compute_deck_digest,
    get_deck_review,
    save_deck_review,
)
from src.services.foreman_service import (
    all_positions_committed,
    next_dispatch_batch,
    outstanding_positions,
    releasable_positions,
    stalled_positions,
)
from src.services.graph.event_emitter import (
    advance_slide_cursor,
    emit_event,
    emit_slide_ready,
    get_chat_request_id,
    get_event_emitter,
    get_slide_cursor,
)
from src.services.graph.progress import (
    SlideProgressStage,
    TurnPhase,
    report_phase,
    report_slide,
    report_slides,
)
from src.services.graph.state import GraphState, scoped, scoped_vals
from src.services.graph.user_notices import (
    FailureNotice,
    deck_not_updated_notice,
    deck_review_failed_notice,
    placeholder_notice,
    slide_number,
    slides_phrase,
    unfinished_slides_notice,
    unreviewed_slide_notice,
)
from src.services.persisted_graph_release import PersistedRuntimeError
from src.services.shared_deck_attribution import (
    DeckMutationContext,
    MutationActor,
    MutationObjectType,
    MutationOperation,
)
from src.services.template_sections import (
    complete_index_only_bindings,
    extract_section,
    invalid_slide_bindings,
    resolve_template_bytes,
    section_inventory,
)
from src.utils.graph_safety import gate_emitted_html, spotlight_prior_slides
from src.utils.html_utils import strip_inter_tag_escapes
from src.utils.slide_hash import compute_slide_hash
from src.utils.slide_number_tokens import substitute_slide_numbers
from src.utils.spotlight import neutralize_delimiters, spotlight

logger = logging.getLogger(__name__)


def _deck_mutation_context(
    session_id: str,
    graph_release_id: Optional[int],
    *,
    operation: MutationOperation,
    object_type: MutationObjectType,
    object_id: Optional[str] = None,
) -> DeckMutationContext:
    return DeckMutationContext(
        actor=MutationActor(session_id, graph_release_id),
        operation=operation,
        object_type=object_type,
        object_id=object_id,
    )


def _assembly_context(
    design_system_active: Any,
    root_session_id: Any,
    actor_session_id: Any,
    *,
    toolset: Optional[AgentToolset] = None,
) -> AgentAssemblyContext:
    """Build the FOURTH argument every ``get_agent_runtime().run(...)`` call passes.

    The one place in this module that constructs an ``AgentAssemblyContext``, and
    that is deliberate.  ``AgentAssemblyContext``'s two session-ID fields carry
    ``""`` defaults — they must, because every caller outside the graph
    constructs it with one argument — so a call site that simply forgot them
    would trace blank and nothing would raise.  Routing all ten through here
    makes the omission a *structural* fact an AST assertion can see
    (``TestNoCallSiteMayTraceBlank``) rather than a silent hole.

    Tolerant of an absent key by design.  The trace is evidence ABOUT a
    mutation, never a precondition for one: a payload assembled by an older
    checkpoint should degrade to an unattributed invocation, not kill a user's
    turn in a reviewer's exception handler that would placehold their slide.
    Production cannot reach that branch — ``invoke_graph`` writes both keys on
    every invocation, before any node runs — which is why the end-to-end tests
    assert the real owner and contributor IDs rather than the fallback.

    **IDs never select the release.**  ``run``'s second argument does; these two
    are inert for resolution and are read by nothing but the identity sink.

    ``toolset`` is keyword-only and invocation-scoped, never an id: only
    ``data_analyst_node`` (Genie One in agent mode) and ``builder_node`` and
    ``fixer_node`` (the brand-asset search, :func:`_brand_search_toolset`, deck
    style addendum A) pass it, and every other call site leaves it ``None``, so
    their single structured-output call is unchanged.
    """
    return AgentAssemblyContext(
        bool(design_system_active),
        root_session_id or "",
        actor_session_id or "",
        toolset=toolset,
    )


def _brand_search_toolset(payload: Mapping[str, Any]) -> Optional[AgentToolset]:
    """A fresh ``search_brand_assets`` toolset for one builder or fixer run, or ``None``.

    Bound only when all three hold (deck style addendum A): a design system is
    active, the deck has a deck style (an old deck's payload never carries one,
    so its call is exactly today's single structured-output call), and the
    design contract names the design system the search is scoped to.
    ``payload`` is the builder's branch payload — for the fixer, the builder
    record its fix entry carries.

    The tool is ``brand_search.BrandSearchAgentTool`` over ``build_ds_asset_tool``
    for that design system: the row cap, the spotlight and the fixed failure text
    are that module's, shared with the eval harness.  A toolset counts its calls,
    so every run asks for its own (the safety-gate retry too).  Nothing here
    reads the database: each search opens its own session.  Any failure to build
    it binds no tool.
    """
    if not payload.get("design_system_active") or payload.get("deck_style") is None:
        return None
    contract = payload.get("design_contract")
    design_system_id = (
        contract.get("design_system_id") if isinstance(contract, Mapping) else None
    )
    if design_system_id is None:
        return None
    # Everything that builds the toolset sits inside the guard, so a failure
    # builds the slide without a search instead of failing it.
    try:
        from src.services.agent_tools.brand_search import build_brand_search_toolset
        from src.services.tools.ds_asset_tool import build_ds_asset_tool

        return build_brand_search_toolset(build_ds_asset_tool(int(design_system_id)))
    except Exception:
        logger.warning(
            "brand-asset search unavailable; the slide is built without it", exc_info=True
        )
        return None


def _raise_if_persisted_runtime_failure(exc: Exception) -> None:
    if isinstance(exc, PersistedRuntimeError):
        raise exc

# Appended to a skill payload when the safety gate rejects the first attempt.
# The gate's `regenerate` argument is a ZERO-ARG callable it invokes, so the
# corrective instruction has to travel in the payload the closure captures.
_SAFETY_CORRECTION = (
    "The previous attempt was rejected: it referenced external network or "
    "resource access, which is not allowed. Re-emit the slide using only "
    "inline markup and the CSS classes already provided."
)

# The deck's deterministic <meta> set: exactly what SlideDeck.knit() would
# default to, resolved here because head_meta is a pre-fan-out column and
# ArchitectOutput declares no field for it.
_DEFAULT_HEAD_META = {
    "charset": "UTF-8",
    "viewport": "width=device-width, initial-scale=1.0",
}

# The reason recorded on a placeholder the FOREMAN reconciled (the stall path),
# as against one a failing node wrote for itself — those pass the exception's
# type name.  The two texts are load-bearing: they are the only way an
# integration test can tell the two call sites of `commit_placeholder` apart, so
# the stall reason is a named constant rather than a literal at the call site.
_STALL_REASON = "Slide generation did not complete"

# Conversation roles/types worth replaying to a skill, mirroring
# chat_service._hydrate_chat_history: `info` is deliberately excluded, which is
# what keeps deck_reviewer_node's advisory message out of the architect's input.
_HUMAN_TYPES = {"user_query", "user_input", "chat"}
_AI_TYPES = {"llm_response", "clarification"}

# The metadata key a refused edit's transcript row carries its reasons under
# (spec §7): ``{"code": <the degrade code>, "problems": [{"code", "positions",
# "detail"}]}``.  The row itself stays an ordinary ``llm_response``, so the UI
# shows the refusal as it always has; the key is what lets ``_conversation`` tell
# the architect, next turn, that a check rejected its plan — the refusal's prose
# alone reads as a reply the architect chose to give.
REFUSAL_METADATA_KEY = "architect_refusal"

# The opening of the ``system`` turn ``_conversation`` replays right after such a
# row (spec §7).  The problems' details follow it.
_REFUSAL_NOTE_PREFIX = (
    "The edit above was NOT applied; nothing in the deck changed. "
    "It was rejected because: "
)

# Appended to a `confirm_design_contract` message when confirming would drop the
# deck's slide style (§L4).  ONE user action mutates TWO fields — setting
# design_system_id and losing slide_style_id — and DesignContractRef's L1
# validator rejects a spec carrying both, so the drop is the CALLER's, not a
# validator's quiet correction.  The sentence is the only place the user learns
# it, and it must arrive while they can still say no.
_SLIDE_STYLE_DROPPED = (
    "Note: a design system and a slide style cannot both apply to one deck, so "
    "confirming this drops the slide style this deck currently uses (slide style "
    "{}). Confirming also rebuilds every slide against the new design, because a "
    "restyle affects all of them."
)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _emit(
    event_type: StreamEventType,
    *,
    content: Optional[str] = None,
    error: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    agent: Optional[str] = None,
) -> None:
    """Queue one event, or do nothing when no emitter is installed.

    Uses only shipped ``StreamEventType`` members: ws4c adds no event type, no
    route and no frontend change.
    """
    emit_event(
        StreamEvent(
            type=event_type, content=content, error=error, metadata=metadata,
            agent=agent,
        )
    )


def _say(
    state: dict,
    message: str,
    *,
    message_type: str = "llm_response",
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Persist one assistant utterance so it survives the turn.  Never raises.

    **The durable half of speaking to the user, and it is not optional.**  An
    ``_emit`` alone reaches the SSE client and NOBODY ELSE:
    ``job_queue.process_chat_request`` handles only ``COMPLETE`` and
    ``SESSION_TITLE`` and discards every other event, and ``GET /chat/poll`` reads
    a turn's assistant text out of **persisted rows**
    (``get_messages_for_request``).  So on the polling transport — the one the
    deployed app uses — an emit-only reply is dropped between the job and the
    poll, and the user is shown silence for a turn that completed and called the
    model.  Measured live before this existed.

    The second consumer is the architect itself.  ``_conversation`` builds the
    architect's history from these rows and admits an assistant turn only when
    ``message_type`` is in :data:`_AI_TYPES`, so a reply that is not persisted
    with a replayable type leaves the architect able to ask a clarifying question
    and, next turn, unable to remember asking.  ``llm_response`` is the type that
    replays; ``info`` deliberately does not (that exclusion is what keeps the deck
    reviewer's advisory out of the architect's prose — see :data:`_AI_TYPES`), so
    ``info`` is the right type for an utterance the user should SEE but the
    architect must not read back as its own words.

    ``request_id`` comes from the turn's ``ContextVar``, not from state: the
    polling projection filters on that column, and a row without it is durable but
    invisible to the client waiting on it.  ``None`` (the SSE path, the sweeper) is
    correct and still writes the row.

    Not to be used for a machine advisory: :func:`_surface_notice` is the ungated
    writer for those, and it stays ungated because a failure notice's value is that
    it lands on every turn.  This one is for a node's own conversational turn.

    *metadata* is stored on the row as given.  A refused edit uses it to record
    why (:data:`REFUSAL_METADATA_KEY`), which ``_conversation`` reads back; an
    ordinary utterance passes none.

    **A describe-only turn writes nothing.**  ws4d's arc-review sweeper invokes
    the graph with ``describe_only=True``, no emitter and no human waiting; its
    reply is addressed to nobody.  Persisting it would put machine-generated prose
    in a human's transcript AND — worse — feed it into ``_conversation``, so the
    human's next turn would find the architect apparently having said something
    they never saw, in answer to a question they never asked.  Suppression is
    keyed on the same turn-scoped flag ``architect_router`` gates dispatch on, and
    it is read HERE rather than passed by each caller so a new caller cannot
    forget it.

    Never raises: like emission, a transcript write must not be the thing that
    fails a turn that has otherwise produced a deck.
    """
    if bool(scoped_vals(state, "describe_only")):
        return
    session_id = state.get("session_id")
    if not session_id or not message:
        return
    try:
        get_session_manager().add_message(
            session_id,
            role="assistant",
            content=message,
            message_type=message_type,
            metadata=metadata,
            request_id=get_chat_request_id(),
        )
    except Exception:
        logger.warning(
            "Could not persist an assistant turn; the user may see silence on "
            "the polling transport",
            exc_info=True,
        )


def _release_slides(state: dict) -> List[int]:
    """Emit ``slide_ready`` for every position the reorder buffer NEWLY releases.

    This is ws4d D3's SSE half.  Called from ``foreman_node`` and from nowhere
    else, for one reason: the foreman is the only node that runs **alone, after
    the superstep barrier**.  Emitting from ``build_reviewer_node`` instead would
    put the decision inside the fan-out, where N reviewers run concurrently — two
    of them would compute overlapping prefixes, and position 3's reviewer
    finishing before position 2's would send slide 3 first.  Ascending order is
    the feature; the barrier is what guarantees it.

    ``releasable_positions(state)`` decides WHAT is releasable, not
    ``slides_since_cursor``, and the difference matters on an edit turn: the rows
    for every untouched position already exist from a previous turn, so a
    row-derived prefix would "release" the whole deck's stale HTML on the first
    foreman wake — before the targeted builders had run — and the cursor would
    then sit past the positions this turn actually rewrites.  Graph state knows
    what THIS turn committed (``landed_positions`` / ``placeheld_positions`` are
    turn-scoped); rows do not.  The polling path has no graph state and so uses
    the row-derived twin, ``SessionManager.slides_since_cursor``; the two prefix
    rules are pinned against each other by a test.

    A **placeholder releases like any other position**: ``placeheld_positions`` is
    inside ``releasable_positions``' committed set and ``commit_placeholder``
    writes a real row, so there is no special case here either.

    Returns the positions emitted (ascending), for the tests and for the caller's
    logging — never raises, because emission is an optional side channel.
    """
    if get_event_emitter() is None:
        return []  # sweeper tick / layer-1 state test: nothing to emit into
    session_id = state.get("session_id")
    if not session_id:
        return []

    cursor = get_slide_cursor()
    pending = [p for p in releasable_positions(state) if p >= cursor]
    if not pending:
        return []

    try:
        rows = {
            row["position"]: row
            for row in SlideWriter().list_slides_in_position_order(
                session_id, from_position=pending[0]
            )
        }
    except Exception:
        logger.warning(
            "Could not read committed slides for release; skipping this wake",
            exc_info=True,
        )
        return []

    # Live page numbers: number = position + 1, count = the spec's slide count.
    spec_slides = getattr(state.get("deck_spec"), "slides", None)
    spec_count = len(spec_slides) if spec_slides else pending[-1] + 1

    to_release: List[Tuple[int, dict]] = []
    for position in pending:
        row = rows.get(position)
        if row is None:
            # State says committed but no row is readable.  STOP rather than skip:
            # releasing the next position would deliver it ahead of this one.
            logger.warning(
                "Position %s is releasable but has no committed row; "
                "holding the release here",
                position,
            )
            break
        to_release.append((position, row))

    # The REST readers' order: page tokens, then brand assets, the latter for the
    # whole wake in one read (and no read when no slide carries a handle).
    htmls = resolve_streamed_ds_assets(
        session_id,
        [
            substitute_slide_numbers(row["html"] or "", position + 1, spec_count)
            for position, row in to_release
        ],
    )

    released: List[int] = []
    for (position, row), html in zip(to_release, htmls):
        emit_slide_ready(
            position=position,
            html=html,
            scripts=row["scripts"] or "",
            agent=row.get("modified_by") or row.get("created_by"),
        )
        released.append(position)

    if released:
        advance_slide_cursor(released[-1] + 1)
    return released


def _agent_config_for(contract: Optional[DesignContractRef]) -> AgentConfig:
    """Build the ``AgentConfig`` the style resolver takes, from a design contract.

    ``resolve_style_source`` is the one implementation of the style BRANCH
    (design system -> legacy style -> default) and it takes an ``AgentConfig``,
    so the contract's three ids are mapped onto it rather than re-implementing
    the branch here.
    """
    if contract is None:
        return AgentConfig()
    return AgentConfig(
        design_system_id=contract.design_system_id,
        template_id=contract.template_id,
        slide_style_id=contract.slide_style_id,
    )


def _contract_ids(contract: Optional[DesignContractRef]) -> tuple:
    """The three ids that decide brand resolution, as a comparable tuple."""
    if contract is None:
        return (None, None, None)
    return (
        contract.design_system_id,
        contract.template_id,
        contract.slide_style_id,
    )


#: The spec fields whose change invalidates every slide at once (§4.6).
#:
#: ``title`` is deliberately ABSENT: renaming a deck contradicts no slide, and
#: including it would classify every re-title as a deck-level change and — once
#: §4.6's other half lands — re-review a whole deck because the user fixed a
#: typo in its name.  ``slides`` and ``resolved_data`` are absent for the mirror
#: reason: a change there is per-slide work the foreman's ordinary coverage
#: already covers, not a deck-wide invalidation.
_DECK_LEVEL_FIELDS = (
    "audience",
    "purpose",
    "argument",
    "call_to_action",
    "narrative_arc",
)


#: Criteria that mark a slide as no longer serving the deck's brief on §4.6's
#: RE-REVIEW pass, in addition to the objective ones.
#:
#: ``brief_not_delivered`` is the ONLY criterion in the registry that can express
#: "this slide no longer serves the brief", and it is ``objective=False``
#: (``finding.py``: *"The one subjective slide criterion"*).  So the build path's
#: objective-only rule — right there, because an objective finding is what a fixer
#: can act on — is exactly wrong here, where the whole question is subjective.
#: Counting objective findings alone made the pass unable to fail for the one
#: reason it exists: it shipped once returning ``set()`` for a
#: ``brief_not_delivered`` finding.
#:
#: The build path is untouched: ``build_reviewer_node`` still branches on
#: ``objective`` alone.
_REREVIEW_FAILING_CRITERIA = frozenset({"brief_not_delivered"})


def classify_spec_change(
    new_spec: Optional[DeckSpec], persisted: Optional[DeckSpec]
) -> str:
    """Classify what a newly committed spec changes against the persisted one.

    Returns one of three strings:

    ``"design_contract"``
        Any of ``design_system_id``, ``template_id``, ``slide_style_id`` differs.
        **This wins over** ``"deck_level"`` when both differ: it is the stronger,
        confirm-first case, and a restyle genuinely affects every slide.
        ``template_id`` is what "pinning or unpinning a template" means — there
        is no persisted ``template_pinned`` field anywhere;
        ``ResolvedStyle.template_pinned`` is a computed NamedTuple member on no
        ORM model and no part of this contract, so watching it would watch
        something that never persists.
    ``"deck_level"``
        Any of :data:`_DECK_LEVEL_FIELDS` differs.
    ``"none"``
        Nothing relevant differs — **including when there is no persisted spec at
        all.**  A first build is not a change: classifying it as one would fire
        §4.6's confirm-first path on the very first turn of every new deck, when
        there are no slides to invalidate and nothing to confirm.

    Both arguments are ``DeckSpec`` objects the caller already has.  The
    persisted side comes from ``deck_level_writer.read_deck_spec``, which
    ``architect_node`` has already called — there is deliberately no read in
    here, so this stays a pure function and the node keeps its single reader.
    """
    if new_spec is None or persisted is None:
        return "none"
    if _contract_ids(new_spec.design_contract) != _contract_ids(
        persisted.design_contract
    ):
        return "design_contract"
    if any(
        getattr(new_spec, field) != getattr(persisted, field)
        for field in _DECK_LEVEL_FIELDS
    ):
        return "deck_level"
    return "none"


def _slide_style_being_dropped(
    proposal: Optional[DesignContractRef],
    inbound: Optional[DesignContractRef],
    prior_spec: Optional[DeckSpec],
) -> Optional[int]:
    """The ``slide_style_id`` a confirmed *proposal* would drop, or ``None``.

    §L4's point is that **one user action mutates two fields** and the user must
    be told.  The clearing is real on ``AgentConfig`` — a serializer
    (``_one_style_authority``) and ``put_agent_config`` both null
    ``slide_style_id`` — but on the deck spec there is **nothing to clear**:
    ``DesignContractRef``'s L1 validator REJECTS a spec carrying both ids.  So
    whoever constructs the new contract must drop the slide style itself, and
    this function exists to name what that drop costs while the user can still
    say no.  Get it backwards and the architect's commit raises a
    ``ValidationError`` on the exact path §4.6 exists for.

    Two places are consulted for the style currently in force, in order:
    ``inbound`` (the contract this turn's brand was actually resolved from — the
    session's own selection when it has one, else the persisted spec's) and then
    the persisted spec's contract.  The second is not redundant: when the session
    has already been switched to a design system, ``AgentConfig``'s serializer
    has ALREADY nulled its ``slide_style_id``, so ``inbound`` carries no style
    while the persisted spec still does — and that deck is exactly one whose
    style is about to be dropped.
    """
    if proposal is None or proposal.design_system_id is None:
        return None
    candidates = [inbound]
    if prior_spec is not None:
        candidates.append(prior_spec.design_contract)
    for contract in candidates:
        if contract is not None and contract.slide_style_id is not None:
            return contract.slide_style_id
    return None


def rereview_committed_slides(
    session_id: str,
    spec: DeckSpec,
    brand: Dict[str, Any],
    graph_release_id: int,
    root_session_id: str = "",
    actor_session_id: str = "",
) -> Dict[str, Any]:
    """Score every committed slide against the **new** spec, serially, here.

    §4.6's re-review pass.  It runs inside ``architect_node`` — **Option 2** —
    because the two-pass turn the plan imagined cannot exist on this topology.
    Measured on the compiled graph (the earlier four-node topology, whose
    re-fan router skipped reviewed positions), in both directions:

    * A turn that reviews a position before building it puts the position in
      ``reviewed_positions``, the re-fan then skipped its builder's review, and a three-slide deck came back with **three
      placeholders and ``error_state`` None** — builders paid for, output
      discarded, silently.
    * Landing in the review pass instead makes ``all_positions_committed`` true
      on the first wake, so the turn dispatched **zero** builders and went
      straight to deck review — and it rewrites the very rows a hand-edit lives
      in, which is the thing §4.6 is organised around preserving.

    Both channels are turn-scoped **sets** with union reducers and there is no
    tombstone for set membership, so neither can be un-set within a turn: **in
    this graph reviews come after builds by construction.**  Running the pass
    here touches no reducer, no router, no foreman and not
    ``build_reviewer_node``; the failing positions then travel on
    ``target_positions`` and the shipped ``builder -> build_reviewer -> land``
    path rebuilds exactly those.

    ``root_session_id`` and ``actor_session_id`` are taken as arguments, exactly
    like ``graph_release_id``, because this pass runs inside ``architect_node``
    but is not a node: it has no state of its own, so its provenance has to
    travel with the release it reviews under.  They default to ``""`` only so the
    suites that predate the trace keep calling it with four arguments; the
    architect always passes all six.

    The cost, stated rather than hidden: this is **serial**, so §4.6's "cheap,
    parallel" becomes "cheap, serial" — one review call per committed slide,
    inside one architect turn.

    Three judgement calls, each recorded because a reviewer may want to overrule
    one:

    **A placeholder fails by definition and costs no model call.**  There is no
    slide there to preserve, so asking a model whether it still fits the brief
    would be paying to be told what its own marker already says.

    **A position whose review RAISES is left alone, not rebuilt.**  Both
    directions are wrong in some way: leaving it risks one stale slide, and
    rebuilding it risks overwriting a manual edit we could not judge.  §4.6
    rejected the blanket rebuild-all as *"expensive and destructive"* and named
    preserving manual edits as the reason, so the tie breaks toward preservation.
    The position is logged and reported in ``unreviewable``.

    **"Contradicts the new spec" means at least one OBJECTIVE finding**, decided
    exactly as ``build_reviewer_node`` decides it — ``_stamp_findings``
    re-derives ``objective`` from ``CRITERIA`` before it is read, so a model
    returning ``objective=False`` for ``overflow`` cannot quietly suppress a
    rebuild.  A subjective finding is surfaced, never acted on, on both paths.

    **Nothing is written.**  No row, and nothing on the ``findings`` channel:
    that channel's contract is *"exactly what this node persisted into a row"*,
    and this pass persists nothing, so an entry here would be an "open" finding
    that nothing ever supersedes.  This is a decision procedure, not a review of
    record.

    **A blank entry is not judged either** (#314 follow-up, m2).  An entry with
    no purpose and no brief (``is_blank_slide_spec``) has nothing a slide could
    contradict, and a "failing" verdict would rebuild the user's blank from an
    empty brief.  It is counted in ``committed`` and in ``blank``, never in
    ``reviewed`` or ``failing``, and costs no model call.  Entry-based, like the
    architect's N1, so a blank someone typed into is spared too.  The check runs
    AFTER the placeholder check: a pending row at a blank entry (an agent insert,
    #337) is still placeheld and failing.  This also spares a blank on a
    deck-level BUILD turn.

    Returns a dict of plain sets: ``committed`` (positions the spec covers that
    have a row), ``reviewed`` (positions a model actually scored), ``failing``,
    ``unreviewable``, ``placeheld``, ``blank``.
    """
    empty = {
        "committed": set(),
        "reviewed": set(),
        "failing": set(),
        "unreviewable": set(),
        "placeheld": set(),
        "blank": set(),
        "surfaced": [],
    }
    try:
        rows = SlideWriter().list_slides_in_position_order(session_id)
    except Exception:
        logger.warning(
            "Could not read the committed slides to re-review them; leaving this "
            "turn's coverage as the architect set it",
            exc_info=True,
            extra={"session_id": session_id},
        )
        return empty

    spec_positions = {slide.position for slide in spec.slides}
    by_position = {
        row.get("position"): row
        for row in rows
        if row.get("position") in spec_positions
    }
    if not by_position:
        return empty

    resolved_style = brand.get("resolved_style") or ""
    section_css = brand.get("deterministic_css") or ""
    layout_html = brand.get("template_layout_html") or ""
    design_system_active = bool(brand.get("design_system_active"))
    deck_brief = {field: getattr(spec, field) for field in _DECK_LEVEL_FIELDS}

    committed: set = set()
    reviewed: set = set()
    failing: set = set()
    unreviewable: set = set()
    placeheld: set = set()
    blank: set = set()
    surfaced: List[dict] = []

    for position in sorted(by_position):
        row = by_position[position]
        committed.add(position)

        if _holds_placeholder(row):
            placeheld.add(position)
            failing.add(position)
            continue

        slide_spec = spec.slide_at(position)
        if slide_spec is None:  # unreachable: by_position is filtered to the spec
            continue
        if is_blank_slide_spec(slide_spec):
            blank.add(position)
            continue

        html = row.get("html") or ""
        # Same extraction build_branch_payload does; "" when unbound, no layout,
        # or the index is out of range (the slide is still reviewed).
        section_html = ""
        if layout_html and slide_spec.template_section_index is not None:
            try:
                section_html = extract_section(
                    layout_html, slide_spec.template_section_index
                )
            except IndexError:
                logger.warning(
                    "template_section_index %s is out of range for this layout; "
                    "re-reviewing position %s with no section markup",
                    slide_spec.template_section_index,
                    position,
                )
        # The SAME payload shape build_reviewer_node builds, key for key, so the
        # skill is judged on the input it was written against.
        review_payload = {
            "position": position,
            "slide_spec": slide_spec.model_dump(),
            "resolved_style": resolved_style,
            "section_css": section_css,
            "resolved_data": spec.resolved_data.model_dump(),
            "section_html": section_html,
            "html": html,
            "scripts": row.get("scripts") or "",
            # The five deck-level fields, WITHOUT WHICH THIS PASS CANNOT WORK.
            # Built from _DECK_LEVEL_FIELDS — the same tuple classify_spec_change
            # watches — so the fields that TRIGGER a re-review and the fields the
            # reviewer is SHOWN can never drift apart.  Neither the reviewer's own
            # payload nor SlideSpec carries any of them, so without this key the
            # reviewer is asked whether a slide still serves a brief it was never
            # told, and can only answer with rendering findings that no spec edit
            # can cause.  Its presence is also what adds DECK_BRIEF_REVIEW to the
            # instructions (see AgentRuntime's protected prompt assembly).
            "deck_brief": deck_brief,
        }
        if spec.deck_style is not None:
            review_payload["deck_style"] = spec.deck_style.model_dump()
        try:
            out = get_agent_runtime().run(
                "build_reviewer",
                graph_release_id,
                review_payload,
                _assembly_context(
                    design_system_active, root_session_id, actor_session_id
                ),
            ).output
            findings = _stamp_findings(
                _skill_findings(out),
                subject_hash=compute_slide_hash(html),
                slide_index=position,
            )
        except Exception as exc:
            _raise_if_persisted_runtime_failure(exc)
            logger.warning(
                "Re-review failed at position %s; treating the slide as still "
                "valid rather than overwriting work we could not judge",
                position,
                exc_info=True,
                extra={"session_id": session_id},
            )
            unreviewable.add(position)
            continue

        reviewed.add(position)
        for item in findings:
            # Surfaced, not discarded. Given brief_not_delivered is subjective,
            # dropping non-objective findings threw away the only signal this pass
            # can produce — and left the notice claiming every slide still fit.
            surfaced.append(
                {
                    "position": position,
                    "criterion": item.criterion,
                    "message": item.message,
                    "objective": bool(item.objective),
                }
            )
        if any(
            item.objective or item.criterion in _REREVIEW_FAILING_CRITERIA
            for item in findings
        ):
            failing.add(position)

    return {
        "committed": committed,
        "reviewed": reviewed,
        "failing": failing,
        "unreviewable": unreviewable,
        "placeheld": placeheld,
        "blank": blank,
        "surfaced": surfaced,
    }


def _design_system_library() -> List[dict]:
    """Every live design system with its templates — §M1, delivered as payload.

    §M1 asks for "the architect's tool manifest" to carry the design-system
    library.  **There is no manifest.** ``TOOL_GRANTS`` is ``[]``, the one
    ``bind_tools`` under ``src/`` binds only the output schema (the structured-
    output binding in ``agent_runtime``), and AgentRuntime invokes the architect
    with structured output and no other tool bound, so a library wired into
    ``tool_grants`` would be read by nothing.  The operator ratified delivering
    §M1 through the architect's **payload** instead, beside
    ``available_design_contract`` and ``template_sections`` — the only channel
    the architect actually reads.

    **Ids and the brand's own labels only — never ``layout_html`` or
    ``token_css``.**  The architect picks an id and ``_resolve_brand`` resolves
    the bytes from it on the turn the pick is committed; shipping compiled
    content here would put a snapshot in a prompt that can go stale against
    ``COMPILER_VERSION`` (the very thing ``DesignContractRef`` stores ids to
    avoid) and would cost the whole catalog's CSS in tokens on every architect
    call.

    Templates of a soft-deleted system never appear: the grouping is built off
    the live systems, so an inactive parent's rows are dropped with it.

    Returns ``[]`` on any failure, and that is deliberate.  A deck can be built
    with no brand at all, so an unreadable catalog must degrade to "no brand on
    offer this turn" rather than kill the turn — the same contract
    ``_session_contract`` and ``_conversation`` already keep.
    """
    try:
        with get_db_session() as db:
            systems = (
                db.query(
                    DesignSystem.id,
                    DesignSystem.name,
                    DesignSystem.description,
                    DesignSystem.is_default,
                )
                .filter(DesignSystem.is_active.is_(True))
                .order_by(DesignSystem.name)
                .all()
            )
            templates = (
                db.query(
                    DesignSystemTemplate.design_system_id,
                    DesignSystemTemplate.id,
                    DesignSystemTemplate.name,
                    DesignSystemTemplate.description,
                )
                .order_by(
                    DesignSystemTemplate.design_system_id,
                    DesignSystemTemplate.name,
                )
                .all()
            )
    except Exception:
        logger.warning(
            "Could not read the design-system library; the architect will see "
            "no brand on offer this turn",
            exc_info=True,
        )
        return []

    by_system: Dict[int, List[dict]] = {}
    for design_system_id, template_id, name, description in templates:
        by_system.setdefault(design_system_id, []).append(
            {
                "template_id": template_id,
                "name": name,
                "description": description,
            }
        )
    return [
        {
            "design_system_id": design_system_id,
            "name": name,
            "description": description,
            "is_default": bool(is_default),
            "templates": by_system.get(design_system_id, []),
        }
        for design_system_id, name, description, is_default in systems
    ]


def _design_system_logos(design_system_id: int) -> List[dict]:
    """The design system's ``logo``/``lockup`` assets as ranked ``{handle, filename}`` rows.

    Handles are ``{{ds-asset:<id>}}``; no asset bytes are read (the ``data`` column
    is deferred by ``search_assets``). Ranked and capped by ``rank_logos``. Returns
    ``[]`` on any failure: a deck can be built without logos, so an unreadable
    asset table logs and the turn goes on.
    """
    try:
        from src.services.design_system_service import search_assets

        # One unfiltered read, filtered here: a ``kind=`` filter is applied in
        # Python by ``search_assets`` anyway, so two filtered calls read twice.
        with get_db_session() as db:
            rows = [
                {
                    "handle": "{{ds-asset:%d}}" % a.id,
                    "filename": a.filename,
                    "kind": a.kind,
                    "mime": a.mime,
                }
                for a in search_assets(db, design_system_id)
                if (a.kind or "").lower() in ("logo", "lockup")
            ]
        return rank_logos(rows)
    except Exception:
        logger.warning(
            "design-system logo read failed; the architect sees no logos this turn",
            exc_info=True,
        )
        return []


def _concat_css(token_css: str, style_block: str) -> str:
    """``token_css`` + the template's ``<style>`` block, concatenated (§17).

    Both halves are CSS **text**; neither is ``<style>``-wrapped.  A wrapped
    block reaching ``aggregate_deck_css`` parses to error nodes and is dropped
    SILENTLY — no exception, no log — which is why the unwrapping is
    ``resolve_template_bytes``' contract and not attempted here.
    """
    return "\n\n".join(part for part in (token_css, style_block) if part)


def _with_default_template(
    contract: Optional[DesignContractRef],
) -> Optional[DesignContractRef]:
    """Fill an unpinned template slot with the design system's default template.

    A design system without a template gives the architect an empty
    ``template_sections``, so nothing can be bound and every builder improvises
    markup outside the template's painted ``<section>`` roots. Applied only to the
    contract the brand is RESOLVED from: the session's stored contract, the
    payload's ``available_design_contract`` and the committed spec keep the
    unpinned slot, so this fallback never reads as a design-contract change.
    """
    if (
        contract is None
        or contract.design_system_id is None
        or contract.template_id is not None
    ):
        return contract
    from src.core.settings_db import get_default_template_id

    template_id = get_default_template_id(contract.design_system_id)
    if template_id is None:
        return contract
    return contract.model_copy(update={"template_id": template_id})


def _resolve_brand(contract: Optional[DesignContractRef]) -> Dict[str, Any]:
    """Resolve every brand-related value for *contract*, in one place.

    ``architect_node`` is the sole caller: brand bytes are resolved once per turn
    so no builder re-resolves inside its own branch (§L5).

    The template resolution is guarded on ``design_system_id is not None and
    template_id is not None`` — **never on the contract's truthiness.**
    ``design_contract`` is a REQUIRED field with no ``default_factory``, and an
    explicitly-constructed all-``None`` ``DesignContractRef()`` is still truthy,
    so ``if contract:`` would call ``resolve_template_bytes(None, None)`` on
    every unpinned deck (§10, where the plan's stated reason for the guard is
    stale but the guard itself stands).

    Returns a dict of plain JSON-native values: ``resolved_style``,
    ``design_system_active``, ``template_layout_html``, ``token_css``,
    ``style_block``, ``deterministic_css``, ``section_inventory``; and
    ``resolved_for``, the :func:`_contract_ids` of *contract* as given (before
    the default-template fill).  That last one lets a caller holding only a
    brand apply the node's re-resolve rule — "the committed contract's ids differ
    from the ones this brand was resolved for" — without being handed the
    inbound contract as well: the operations planner, which may run twice in a
    turn, always receives the INBOUND brand, so it must be able to tell.
    ``template_requested`` says whether the default-filled contract names a
    design system AND a template, so template bytes were asked for: an empty
    ``deterministic_css`` then means the resolution failed closed (a transient
    DB error, a deactivated design system, a deleted template), not that the
    deck has no brand CSS.
    """
    from src.services.agent_resolution import resolve_style_source

    resolved_for = _contract_ids(contract)
    contract = _with_default_template(contract)
    style = resolve_style_source(_agent_config_for(contract))

    layout_html = ""
    style_block = ""
    token_css = ""
    template_requested = (
        contract is not None
        and contract.design_system_id is not None
        and contract.template_id is not None
    )
    if template_requested:
        layout_html, style_block, token_css = resolve_template_bytes(
            contract.design_system_id, contract.template_id
        )

    inventory: List[dict] = []
    if layout_html:
        try:
            inventory = section_inventory(layout_html)
        except Exception:
            logger.warning(
                "section_inventory failed; the architect will assign no template "
                "sections this turn",
                exc_info=True,
            )

    return {
        "resolved_style": style.slide_style,
        "design_system_active": bool(style.design_system_active),
        "template_layout_html": layout_html,
        "token_css": token_css,
        "style_block": style_block,
        "deterministic_css": _concat_css(token_css, style_block),
        "section_inventory": inventory,
        "resolved_for": resolved_for,
        "template_requested": template_requested,
    }


def _session_contract(session_id: str) -> Optional[DesignContractRef]:
    """The brand the USER selected on this session, as a design contract.

    The graph's ``DesignContractRef`` is ids-only and the architect is the node
    that fills it, so without this the graph path could never pin a design
    system at all: nothing else in the topology knows which brand the user
    chose.  ``AgentConfig`` is the shipped home of that choice and
    ``resolve_agent_config`` is its lenient reader.

    Returns ``None`` when the session has no style selection, or when a stored
    combination cannot be expressed as a contract (``template_id`` without its
    owning ``design_system_id``) — both mean "no pin", never an exception.
    """
    try:
        raw = get_session_manager().get_session(session_id).get("agent_config")
    except Exception:
        logger.debug("No session agent_config available", exc_info=True)
        return None
    config = resolve_agent_config(raw if isinstance(raw, dict) else None)
    if (
        config.design_system_id is None
        and config.slide_style_id is None
    ):
        return None
    try:
        return DesignContractRef(
            design_system_id=config.design_system_id,
            template_id=config.template_id,
            slide_style_id=config.slide_style_id,
        )
    except Exception:
        logger.warning(
            "Session agent_config does not express a valid design contract; "
            "treating the deck as unpinned",
            exc_info=True,
        )
        return None


def _conversation(session_id: str) -> List[Dict[str, str]]:
    """Replayable conversation turns for a skill payload.

    Filtered exactly as ``chat_service._hydrate_chat_history`` filters:
    ``info`` is skipped, so the deck reviewer's advisory message never reaches
    the architect as prose.

    **A refused edit is followed by a ``system`` turn** (spec §7).  The refusal
    row replays as the assistant turn it is, and right after it comes
    :func:`_refusal_note`, built from the row's :data:`REFUSAL_METADATA_KEY`.
    Without it the architect reads its own refusal as a reply it chose to give,
    so next turn it cannot tell that a check rejected the plan, nor why, and
    proposes the same edit again.  A row without the key replays exactly as it
    always has.
    """
    try:
        messages = get_session_manager().get_messages(session_id)
    except Exception:
        logger.debug("No conversation available for session", exc_info=True)
        return []
    turns: List[Dict[str, str]] = []
    for message in messages:
        role = message.get("role") or ""
        content = message.get("content") or ""
        mtype = message.get("message_type") or ""
        if not content:
            continue
        if role == "user" and mtype in _HUMAN_TYPES:
            turns.append({"role": "user", "content": content})
        elif role == "assistant" and mtype in _AI_TYPES:
            turns.append({"role": "assistant", "content": content})
            metadata = message.get("metadata")
            refusal = (
                metadata.get(REFUSAL_METADATA_KEY) if isinstance(metadata, dict) else None
            )
            if isinstance(refusal, dict):
                turns.append({"role": "system", "content": _refusal_note(refusal)})
    return turns


def _refusal_note(refusal: Dict[str, Any]) -> str:
    """The ``system`` turn replayed after a refused edit: why it was refused.

    The problems' model-facing details — the text a retry is handed, in
    positions, not the user's slide numbers — ``; ``-joined.  A problem with no
    detail is named by its code, and a refusal recorded with no problems by its
    own code, so the note always gives a reason.  Tolerant of any shape: it reads
    a stored row, and a malformed one must not cost the turn its conversation.
    """
    problems = refusal.get("problems")
    reasons = [
        str(problem.get("detail") or problem.get("code") or "")
        for problem in (problems if isinstance(problems, list) else [])
        if isinstance(problem, dict)
    ]
    because = "; ".join(reason for reason in reasons if reason)
    return _REFUSAL_NOTE_PREFIX + (because or str(refusal.get("code") or "a check")) + "."


def _committed_slide_rows(session_id: str) -> List[Dict[str, Any]]:
    """Every committed slide row, in deck order (``[]`` when there are none).

    One read with two consumers inside ``architect_node``: the deck digest wants
    each row's HTML and the persisted-spec alignment check wants each row's
    POSITION.  Reading the rows twice per architect turn to fetch them separately
    is a query nobody needs.
    """
    try:
        return SlideWriter().list_slides_in_position_order(session_id)
    except Exception:
        logger.debug("No committed slides for session", exc_info=True)
        return []


def _deck_positions(
    committed_positions: Set[int], prior_spec: Optional[DeckSpec]
) -> List[int]:
    """The positions the user's slide numbers count over (#313, D1).

    The committed rows' positions when there are any (the slide panel renders
    the rows), else the persisted spec's slide positions (a deck described but
    not yet built), else ``[]``.  Rows win over the spec even when the two
    disagree: an edit whose spec and rows disagree is refused anyway
    (``_persisted_spec_describes_these_rows``), and what the user reads their
    numbers off is the panel.  Ascending; ``slide_numbering`` numbers them 1..n.
    """
    if committed_positions:
        return sorted(committed_positions)
    if prior_spec is not None:
        return sorted(slide.position for slide in prior_spec.slides)
    return []


def _persisted_spec_describes_these_rows(
    prior_spec: DeckSpec, row_positions: Set[int]
) -> bool:
    """Whether a PERSISTED spec's positions still match the committed rows.

    Applied to the persisted spec only, and never to a spec the architect just
    emitted: a spec with more slides than the deck has rows is exactly how a deck
    GROWS (the first build has no rows at all, and "add a slide" describes one
    before it exists), so the row set cannot constrain model output.  What it can
    constrain is an EDIT — the model revises the persisted spec, so an edit of
    a description written for a deck whose rows have since moved is refused.

    Every deck-mutation route now moves ``session_slide_decks.deck_spec_json``
    with the rows: the manual insert splices its entry inside
    ``SessionManager.insert_slide``'s own transaction (#314 follow-up), and delete,
    duplicate and reorder renumber it through
    ``ChatService._rewrite_deck_spec_slides``, so the spec normally tracks the
    rows (final review C1 was the earlier state, when only insert did).  A deck
    changed any other way still leaves its ``position`` entries describing slides
    that have moved or gone, while the row-level ``deck_spec_slide`` fragments
    travel correctly.  Comparing the two sets is what makes that mismatch
    representable at the one consumer that acts on it, rather than relying on
    every writer to remember to renumber.

    **No rows means nothing to disagree with**, so an unbuilt deck is aligned by
    definition: the check exists to stop a stale brief reaching a slide a human
    already has, and there is no such slide.

    **A reorder is invisible here and that is a known limit**, stated so the next
    reader does not mistake this for a total guarantee: reordering leaves the two
    position sets equal while every entry describes a different slide.  The two
    stronger predicates were both measured and rejected — comparing a row
    fragment's own ``position`` to its row position fires after an INSERT (a route
    that renumbers the deck spec correctly, because fragments travel with their
    slides and keep their original position), and comparing fragment CONTENT
    to the deck-level entry fires after any §4.6 deck-level change, where the spec
    is deliberately newer than the slides not yet rebuilt against it.  The reorder
    route now permutes the spec entries with the slides, which closes the case for
    a reorder made through it; this check still cannot see one made any other way.
    """
    if not row_positions:
        return True
    return {slide.position for slide in prior_spec.slides} == set(row_positions)


def _description_keeps_what_it_cannot_see(
    spec: DeckSpec, prior_spec: DeckSpec, committed_rows: List[Dict[str, Any]]
) -> DeckSpec:
    """A describe-only re-description, less what it cannot have seen (#314, N2).

    The arc-review sweeper's architect is shown the persisted spec and no slide
    HTML.  On a deck whose persisted spec still describes its rows (the caller's
    gate: ``_persisted_spec_describes_these_rows``), two things in its answer
    cannot be a reading of the deck:

    * **(a) Another position set.**  A describe-only turn moves no row, so an
      answer that drops or adds an entry describes slides that are not there.
      The persisted spec is kept whole, on every deck, and as a DEEP copy: the
      caller mutates what this returns (``complete_index_only_bindings``) before
      it compares it with ``prior_spec``.  WARNING
      ``describe_spec_positions_changed``.
    * **(b) A description of a blank.**  Where the committed row is still an
      empty frame (``is_blank_slide_html``) and the persisted entry is still
      blank (``is_blank_slide_spec``), a purpose or brief is invention, and an
      invented brief would later fail re-review and rebuild the blank.  A copy of
      the persisted entry replaces the model's; the rest of the answer is the
      model's.  A blank someone has typed into is no longer an empty row, so
      describing it is reading, and the model's entry stands.  INFO
      ``describe_kept_blank_slides``.

    ``committed_rows`` are read for ``"position"`` and ``"html"`` only.
    """
    spec_positions = sorted(slide.position for slide in spec.slides)
    prior_positions = sorted(slide.position for slide in prior_spec.slides)
    if set(spec_positions) != set(prior_positions):
        logger.warning(
            "describe_spec_positions_changed: the describe-only deck_spec has slide "
            "positions %s but the persisted deck_spec, which describes the rows, has "
            "%s; a describe-only turn moves no row, so the persisted spec is kept",
            spec_positions,
            prior_positions,
        )
        return prior_spec.model_copy(deep=True)

    empty_rows = {
        row.get("position")
        for row in committed_rows
        if is_blank_slide_html(row.get("html"))
    }
    kept: List[int] = []
    slides: List[SlideSpec] = []
    for slide in spec.slides:
        persisted = prior_spec.slide_at(slide.position)
        if (
            slide.position in empty_rows
            and persisted is not None
            and is_blank_slide_spec(persisted)
            and slide != persisted
        ):
            slides.append(persisted.model_copy(deep=True))
            kept.append(slide.position)
        else:
            slides.append(slide)
    if not kept:
        return spec
    logger.info(
        "describe_kept_blank_slides: positions %s are still blank slides with blank "
        "entries; the describe-only turn's descriptions of them are discarded",
        kept,
    )
    return spec.model_copy(update={"slides": slides})


def _untouched_blank_positions(
    spec: DeckSpec,
    alignment: Optional[SlideAlignment],
    inserting: bool,
    *,
    rebuild: Optional[Sequence[int]] = None,
) -> Set[int]:
    """The final spec's blank entries this edit neither added nor revised (#314, N1).

    A blank entry (``is_blank_slide_spec``: no purpose, no brief) gives a builder
    nothing to build from, so building or re-judging one nobody touched can only
    replace the user's blank, or what they have since typed into it, with
    something invented from an empty brief.  Entry-based on purpose: the row is
    not read, which is what keeps a hand-typed blank safe.

    Decided on the FINAL spec (after an insert's re-stamp), so a blank that an
    insert moved is found at its new position.  Touched means
    ``inserted_indices | revised_indices`` on an insert turn, where the spec is
    re-stamped to exactly those indices, and ``alignment.revised`` otherwise
    (positions, correct on a gapped deck).  An inserted blank entry (#337) is
    touched, so it is still built.

    **The operations path passes** *rebuild* **instead of an alignment** (spec
    §4): touched is exactly what an insert, update or replace produced, so a
    blank only moved, or left where it was, is untouched.  *rebuild* must be in
    *spec*'s own numbering, which is the plan's: composed indices after a
    re-stamp, persisted positions on an identity layout (C10).  Comparing the
    plan's rebuild with a spec in the other numbering is the bug this pairing
    exists to prevent: on a gapped deck it marks the wrong entries untouched.

    ``set()`` when there is neither: only an edit that is not describe-only is
    aligned or planned, so a build turn (a build replaces the deck by request)
    and the arc-review sweeper are outside this.
    """
    if rebuild is not None:
        touched = set(rebuild)
    elif alignment is None:
        return set()
    elif inserting:
        touched = set(alignment.inserted_indices) | set(alignment.revised_indices)
    else:
        touched = set(alignment.revised)
    blank = {slide.position for slide in spec.slides if is_blank_slide_spec(slide)}
    return blank - touched


def _drop_untouched_blanks(
    session_id: str,
    positions: List[int],
    untouched: Set[int],
    slide_references: List[Dict[str, Any]],
    slide_numbering: List[Dict[str, int]],
    notified: Set[int],
) -> List[int]:
    """*positions* without the *untouched* blanks, in their order (#314, N1).

    The one filter for the three lists an edit turn builds from: its targets,
    the design-contract rebuild-all and the deck-level ``rebuild`` set.

    A dropped blank the user's message NAMED is said, because "fill slide 4"
    answered by a model that left slide 4's entry blank would otherwise build
    nothing and say nothing: one WARNING ``blank_named_but_not_described`` and
    one notice, at most once per blank per turn however many lists drop it
    (*notified* is the turn's shared record).  The number is the user's own, from
    ``slide_numbering``.  The caller passes no references on an insert turn:
    they are numbered before the insert, and there a named slide is the anchor
    ("after slide 3"), not a request to fill it.  Nor on the operations path:
    its targets never hold an untouched blank, so it says its named blanks once,
    before any list is filtered, by C12's rule (:func:`_blanks_named_but_left_alone`).
    """
    if not untouched:
        return list(positions)
    _say_named_blanks(
        session_id,
        [position for position in positions if position in untouched],
        slide_references,
        slide_numbering,
        notified,
    )
    return [position for position in positions if position not in untouched]


def _say_named_blanks(
    session_id: str,
    blanks: List[int],
    slide_references: List[Dict[str, Any]],
    slide_numbering: List[Dict[str, int]],
    notified: Set[int],
) -> None:
    """Say each of *blanks* the user's message named, in order, once per turn (#314, N1).

    One WARNING ``blank_named_but_not_described`` and one notice per blank;
    *notified* is the turn's shared record, so a blank two callers both reach is
    said once.  *blanks*, the references' positions and the numbering must be in
    one numbering; the number said is the numbering's.
    """
    named = {
        position
        for reference in slide_references
        for position in reference.get("positions") or ()
    }
    numbers = {entry["position"]: entry["slide_number"] for entry in slide_numbering}
    for position in blanks:
        if position not in named or position in notified:
            continue
        notified.add(position)
        # A named position is always numbered: both come from the same positions.
        number = numbers.get(position, position + 1)
        logger.warning(
            "blank_named_but_not_described: the user's message names slide %s "
            "(position %s) but the edit left its spec entry blank, so it is not built",
            number,
            position,
            extra={"session_id": session_id},
        )
        _surface_notice(
            session_id,
            f"Slide {number} is still blank, so I left it as it is. "
            "Tell me what to put on it.",
        )


def _blanks_named_but_left_alone(
    prior_spec: DeckSpec,
    operations: Sequence[Any],
    slide_references: List[Dict[str, Any]],
) -> List[int]:
    """The persisted blanks the user named that no operation acts on or anchors to (C12).

    The operations path's form of "named but not described" (spec §4).  On the
    full-spec path the notice rides on a build list dropping the blank; here no
    list ever holds an untouched blank (the targets ARE ``rebuild``), so "fill
    slide 2" answered by operations that never mention slide 2 would build
    nothing there and say nothing.  Decided on the PERSISTED deck, which is what
    the references and the operations both count:

    * a slide that is the ``position`` of an operation was acted on — updated,
      replaced, deleted or moved — so the user's naming it was answered;
    * a slide that is the ``after_position`` of an insert or move was named as a
      PLACE ("after slide 3"), not as a request to fill it — today's insert path
      passes no references for the same reason.

    Entry-based, like N1: the persisted entry is blank (``is_blank_slide_spec``),
    whatever the row holds.  Ascending, and pure.
    """
    acted_on = {op.position for op in operations if op.position is not None}
    anchors = {
        op.after_position
        for op in operations
        if op.op in ("insert", "move") and op.after_position is not None
    }
    named = {
        position
        for reference in slide_references
        for position in reference.get("positions") or ()
    }
    left_alone: List[int] = []
    for position in sorted(named - acted_on - anchors):
        slide = prior_spec.slide_at(position)
        if slide is not None and is_blank_slide_spec(slide):
            left_alone.append(position)
    return left_alone


def _resolve_deck_id(db, session_id: str) -> Optional[int]:
    """Resolve the owning deck's integer id from a session_id string.

    The recipe is ``deck_review_store``'s own, quoted in its module docstring:
    look the ``UserSession`` up, follow contributor -> owner through
    ``SessionManager._get_deck_owner_session`` (which takes a ``UserSession``
    OBJECT and a ``db``, not a string), then read that owner's deck row.  Do not
    write a second implementation of the contributor-following logic.
    """
    session = (
        db.query(UserSession).filter(UserSession.session_id == session_id).first()
    )
    if session is None:
        return None
    owner = get_session_manager()._get_deck_owner_session(db, session)
    deck = (
        db.query(SessionSlideDeck)
        .filter(SessionSlideDeck.session_id == owner.id)
        .first()
    )
    return deck.id if deck is not None else None


def _stamp_findings(
    findings: List[Finding],
    *,
    subject_hash: str,
    slide_index: int,
) -> List[Finding]:
    """Return *findings* with authoritative ``objective``, ``id`` and ``slide_index``.

    Three corrections applied to every model-produced finding:

    * **``objective`` is re-derived from ``CRITERIA``** (§6).  ``Finding``'s
      validator checks ``criterion`` and ``category`` but NOT ``objective``, so a
      model returning ``objective=False`` for ``overflow`` would silently disable
      the whole one-fix-round path, and ``objective=True`` for ``arc_gap`` would
      send a narrative finding to the fixer.  Neither raises.
    * **``id`` is minted with all three arguments** —
      ``make_finding_id(criterion, subject_hash, ordinal)``.  ``ordinal`` is the
      0-indexed position among findings of that same criterion on this subject;
      the default of 0 is a documented trap, and omitting it makes two
      ``overflow`` findings share one id, so the drawer renders one and
      dismissing it marks the other seen.
    * **``slide_index`` comes from the caller**, not the model: the node knows
      which slide it is reviewing and the model can be wrong.
    """
    ordinals: Dict[str, int] = {}
    stamped: List[Finding] = []
    for finding in findings:
        ordinal = ordinals.get(finding.criterion, 0)
        ordinals[finding.criterion] = ordinal + 1
        stamped.append(
            finding.model_copy(
                update={
                    "objective": CRITERIA[finding.criterion].objective,
                    "id": make_finding_id(
                        finding.criterion, subject_hash, ordinal
                    ),
                    "slide_index": slide_index,
                }
            )
        )
    return stamped


def _write_reviewed_row(
    *,
    session_id: str,
    position: int,
    html: str,
    scripts: str,
    findings: List[Finding],
    verdict: str,
    slide_spec: Any,
    initiated_by: Optional[str],
    mutation: DeckMutationContext,
) -> str:
    """Commit one reviewed slide row and return its content hash.

    Three parameters carry the whole reason this helper exists:

    * ``modified_by=initiated_by`` — ``get_current_user()`` is ``None`` inside
      the graph, and ``write_slide``'s partial-update semantics then *preserve*
      the existing author, which on an INSERT leaves it **NULL**.  The principal
      is resolved once in ``invoke_graph`` and carried in state and in the branch
      payload for exactly this call.
    * ``deck_spec_slide`` takes a **dict** (it is serialised to JSON on write),
      so the payload carries ``slide_spec.model_dump()``, never the pydantic
      object.
    * ``verification_record`` is built by ``build_verification_record`` — the
      ``{content_hash: verdict}`` shape ``get_slide_deck`` reads back with
      ``.get(compute_slide_hash(row.html))``.  A record keyed any other way is
      invisible to the UI **and** pollutes ``get_verification_map``'s flat
      aggregate, which is persisted into save points.

    ``slide_id`` is deliberately not passed: on an UPDATE the existing id is
    preserved, and on an INSERT a fresh uuid4 is generated.
    """
    content_hash = compute_slide_hash(html)
    SlideWriter().write_slide(
        session_id=session_id,
        position=position,
        html=html,
        scripts=scripts or "",
        verification_record=build_verification_record(
            content_hash=content_hash,
            findings=findings,
            verdict=verdict,
        ),
        deck_spec_slide=slide_spec if isinstance(slide_spec, dict) else None,
        modified_by=initiated_by,
        mutation=mutation,
    )
    return content_hash


def _surface_notice(
    session_id: str, message: str, *, details: Optional[Dict[str, str]] = None
) -> None:
    """Persist a machine-generated advisory as an ``info`` chat message.

    The shipped channel for advisories the user must see, and the graph's ONE
    **ungated** chat writer: it writes on every turn, describe-only included.
    That is the line between this and :func:`_say` — ``_say`` carries a node's
    conversational turn and suppresses it when nobody is listening; this carries a
    machine advisory whose whole value is that it is durable regardless.  Used by
    every non-fatal failure path a **fanned** node can take, because those paths
    cannot write ``error_state``: it is single-writer with no reducer, and two
    branches failing in the same superstep then raise — measured on the
    installed langgraph::

        InvalidUpdateError: At key 'error_state': Can receive only one value per
        step. Use an Annotated key to handle multiple values.

    which would kill the turn, exactly the failure the handler exists to
    prevent.  A chat message is per-row and concurrency-safe, and unlike a
    stream event it survives ``emitter=None`` (the sweeper path).

    Two non-fanned callers use it too — ``foreman_node``'s unreconciled-END notice
    and ``deck_reviewer_node``'s review advisory — because they want exactly these
    semantics and each previously carried its own copy of this write, which is how
    one of them ended up untagged and invisible to the polling client.

    ``request_id`` is stamped because "an advisory the user must see" was only
    half true before it was: ``GET /chat/poll`` reads a turn's chat text through
    ``get_messages_for_request``, which filters on that column, so an untagged
    row was durable and **invisible to every polling client** — the transport the
    deployed app uses.  The value comes from the turn's ``ContextVar``, which
    survives the ``Send`` fan-out this helper is reached from, and is ``None`` on
    the SSE path and the sweeper.  The ``info`` TYPE is unchanged and must stay:
    it is what keeps these notices out of ``_conversation``, so the architect
    never reads a machine advisory back as its own prose.

    ``details`` is the technical half of a plain-language notice (#321): the
    stage, the error class or code, and the request id.  It is persisted as the
    row's ``metadata["details"]`` and shown behind a collapsed disclosure in chat,
    never as the headline.  It never carries exception text.
    """
    try:
        get_session_manager().add_message(
            session_id,
            role="assistant",
            content=message,
            message_type="info",
            request_id=get_chat_request_id(),
            metadata={"details": dict(details)} if details else None,
        )
    except Exception:
        logger.warning("Could not surface a failure notice", exc_info=True)


def _surface_failure_notice(session_id: str, notice: FailureNotice) -> None:
    """Log and persist a plain-language failure notice (#321).

    The only sanctioned way to write a details-bearing notice: it writes the one
    ``graph_failure_notice`` WARNING for the failure, then the ``info`` chat row
    through :func:`_surface_notice` with the notice's ``details`` as the row's
    metadata.  A site that called ``_surface_notice(..., details=...)`` directly
    would skip the log line, which is why an AST test forbids it.

    The log fields go in the **message**, not only in ``extra``: the production
    root logger formats the message alone, so a field that lived only in ``extra``
    would never reach the deployed log.  ``extra`` is kept for any structured
    handler wired later.  ``positions=`` is labelled as positions because the
    values are **0-based**; nobody should read them as slide numbers.  The
    ``request_id`` is the repo's own key for the turn's id.

    Never raises.  A failed log line must not cost the chat row, and
    :func:`_surface_notice` already swallows its own write failure.
    """
    try:
        request_id = notice.details.get("request_id")
        positions = list(notice.positions)
        logger.warning(
            "graph_failure_notice kind=%s stage=%s error=%s positions=%s "
            "request_id=%s session_id=%s",
            notice.kind,
            notice.stage,
            notice.error,
            positions,
            request_id,
            session_id,
            extra={
                "notice_kind": notice.kind,
                "graph_stage": notice.stage,
                "error_class": notice.error,
                "positions": positions,
                "request_id": request_id,
                "session_id": session_id,
            },
        )
    except Exception:
        logger.warning("Could not log a failure notice", exc_info=True)
    _surface_notice(session_id, notice.text, details=notice.details)


def _placehold_failed_position(
    position: int,
    *,
    session_id: str,
    node: str,
    reason: str,
    mutation: DeckMutationContext,
    error: Optional[BaseException] = None,
) -> bool:
    """Commit a terminal placeholder for one failed branch, visibly.

    The single sanctioned way a fanned node marks a position it could not
    deliver: ``commit_placeholder`` (never a hand-rolled marker), detection
    through ``is_placeholder_record`` (never an HTML class), and an ``ERROR``
    stream event.

    Returns ``True`` when the row reads back as a placeholder, which is the only
    case in which the caller may claim ``placeheld_positions``: claiming it
    otherwise would make ``all_positions_committed`` true for a position with no
    row, and the deck would go to review incomplete.  On ``False`` the caller
    returns no state at all and the foreman reconciles the position through
    ``stalled_positions``.

    **Every path that placeholds a position takes this one function and gets the
    same three surfaces**: the row's error marker, an ``ERROR`` stream event, and
    a durable ``info`` chat line (plain language, through
    :func:`_surface_failure_notice`).  All four of them — the three pipeline stages
    (``builder``, ``build_reviewer``, ``fix_reviewer``'s undeliverable-row
    path) and ``placeholder_node``'s stall path.  There is no flag to make one quieter
    than another, deliberately: the emitter is optional and is ``None`` on the
    sweeper path (and in every layer-1 state test), so an event-only surface
    would let a failed position leave a silently missing slide.  The chat notice
    is the only surface that survives ``emitter=None``, and ``error_state`` is
    unavailable to every FANNED path — it is single-writer with no reducer,
    and two branches failing in one superstep would raise
    ``InvalidUpdateError`` and kill the turn (measured).  ``fix_reviewer``
    records it anyway, and ``slide_pipeline_node`` keeps it branch-local
    (``_PIPELINE_LOCAL_KEYS``); that is a difference in what a *caller*
    returns, never in what this function surfaces.

    ``placeholder_node`` used to carry a hand-written copy of this call and
    diverged three ways — a different ``error_message``, the ``ERROR`` event
    after the commit rather than before, and **no durable chat notice at all**,
    so a stalled position was placeheld silently and the only line the user
    received was the deck reviewer's "no narrative issues found".  Hence one
    implementation and a ``reason`` parameter, rather than a fourth copy.

    The ``ERROR`` event is emitted **before** the commit is attempted, so a
    position that cannot even be placeheld is still surfaced.

    So the failure is never silent, whichever node hit it, and the exception is
    logged with its traceback either way.

    **What the user reads (#321).**  The chat line and the event are plain
    language from :func:`placeholder_notice`, numbered 1-based as the UI numbers
    slides, with the technical side (``stage``, ``error``, ``request_id``) behind
    ``details``.  ``position`` is the 0-based position everywhere in data (event
    metadata, the row marker, the log).  The event is emitted before the commit,
    when no placeholder exists yet, so it carries the notice's ``headline``, which
    claims nothing about the slide's state; the chat line, written only after the
    placeholder reads back, carries the full ``text`` and the one
    ``graph_failure_notice`` log record.  ``reason`` is the row's error marker and
    goes to ``commit_placeholder`` verbatim.  ``error`` is the caught exception,
    when there is one: it is used only to recognise a safety-gate block
    (``UnsafeContentError``), and only its class name, never its text, can reach
    the notice.

    ``commit_placeholder`` takes neither ``modified_by`` nor ``deck_spec_slide``
    (Ruling C-15), so these rows ship with a NULL author here too.
    """
    notice = placeholder_notice(
        position,
        stage=node,
        error=reason,
        unsafe=isinstance(error, UnsafeContentError),
        request_id=get_chat_request_id(),
    )
    _emit(
        StreamEventType.ERROR,
        error=notice.headline,
        metadata={"node": node, "position": position, "details": dict(notice.details)},
    )
    writer = SlideWriter()
    try:
        writer.commit_placeholder(
            session_id,
            position,
            error_message=reason,
            mutation=mutation,
        )
        row = writer.get_slide(session_id, position) or {}
    except Exception:
        logger.exception(
            "commit_placeholder failed at position %s; the foreman will "
            "reconcile it",
            position,
        )
        return False
    if not is_placeholder_record(row.get("verification_record")):
        logger.error(
            "Placeholder row at position %s does not read back as a "
            "placeholder; the foreman will reconcile it",
            position,
        )
        return False
    _surface_failure_notice(session_id, notice)
    return True


def _advisory_text(findings: List[Finding]) -> str:
    """Compose the deck-review advisory from findings alone (§5, Ruling C-3).

    ``DeckReviewOutput`` declares ``findings`` and nothing else, so the message is
    composed here.  Shape (#316): plain lines from src/domain/finding_copy.py
    (never a criterion slug), one closing line, then the REVIEWER_DETAILS_SEPARATOR
    section with each reviewer message verbatim — the only actionable slide
    references.  frontend/src/utils/findingText.ts matches exactly this shape to
    collapse the details; the strings are pinned equal by
    tests/unit/test_finding_conformance.py.  This is an ``info`` row, so neither
    replay path (``_conversation``, ``_hydrate_chat_history``) feeds it back to the
    architect.  The empty-list line is byte-identical to before (pinned by
    tests/unit/test_graph_nodes.py::TestDeckAdvisoryIsPlain::
    test_no_findings_line_is_byte_identical; the tour fixture's copy of it is
    pinned separately by tests/unit/test_tour_fixture_script.py), and a silent
    absence is indistinguishable from a review that never ran.
    """
    if not findings:
        return (
            "Deck review complete: no narrative issues found across the deck."
        )
    counts: Dict[str, int] = {}
    for finding in findings:
        line = deck_advisory_issue(finding.criterion)
        counts[line] = counts.get(line, 0) + 1
    total = len(findings)
    lines = [
        f"{DECK_ADVISORY_HEADER_PREFIX}{total} "
        f"{'thing' if total == 1 else 'things'}{DECK_ADVISORY_HEADER_SUFFIX}"
    ]
    for line, count in counts.items():  # first-seen order
        lines.append(f"- {line[:-1]} (noted {count} times)." if count > 1 else f"- {line}")
    lines.append(DECK_ADVISORY_CLOSING)
    text = "\n".join(lines)
    details = [f"- {finding.message}" for finding in findings if finding.message.strip()]
    if details:
        text += REVIEWER_DETAILS_SEPARATOR + "\n".join(details)
    return text


def _skill_findings(output: Any) -> List[Finding]:
    """The ``findings`` list off a review output, defensively."""
    return list(getattr(output, "findings", None) or [])


# ---------------------------------------------------------------------------
# build_branch_payload — pre-copy everything, resolve nothing
# ---------------------------------------------------------------------------


def build_branch_payload(state: dict, position: int) -> Dict[str, Any]:
    """Everything one builder branch needs, copied out of state.

    A ``Send``-reached node cannot see ``GraphState`` (measured: the node saw
    only its payload's keys), so every value it needs is copied here.

    **This function resolves nothing and reads no database.**
    ``architect_node`` already put ``template_layout_html``,
    ``deterministic_css`` and ``resolved_style`` in state once per turn, so this
    only **extracts** the assigned section with ``extract_section``, carries
    ``deterministic_css`` **whole** as the section CSS (§M5 — never pruned), and
    copies the style prose across.  ``design_contract`` does not close that gap:
    it is ids-only, *"WHICH brand, never the compiled content"*.

    The ``SlideSpec`` is looked up **by position** with ``deck_spec.slide_at``,
    never by list index: the two diverge after a delete or a partial
    multi-target rebuild, at which point indexing by list position silently
    briefs a builder for the wrong slide.  ``slide_at`` returning ``None`` is a
    real state and raises, naming the position — the spec and the turn disagree
    and a builder briefed for nothing would produce a plausible wrong slide.

    Only JSON-native values go in (Ruling C-21): the ``SlideSpec``, the design
    contract and the resolved data travel as ``model_dump()`` dicts, and
    ``design_system_active`` as a plain ``bool``.  ``resolved_data`` comes from
    ``state["deck_spec"].resolved_data`` — it is not a state key and must not
    become one (§11).
    """
    spec: Optional[DeckSpec] = state.get("deck_spec")
    if spec is None:
        raise ValueError(
            f"build_branch_payload called for position {position} with no "
            "deck_spec in state; the architect commits the spec before the "
            "foreman dispatches anything"
        )

    slide_spec: Optional[SlideSpec] = spec.slide_at(position)
    if slide_spec is None:
        raise ValueError(
            f"deck_spec has no slide at position {position} "
            f"(spec positions: {sorted(s.position for s in spec.slides)}); "
            "the spec and this turn disagree"
        )

    layout_html = state.get("template_layout_html") or ""
    section_html = ""
    if layout_html and slide_spec.template_section_index is not None:
        try:
            section_html = extract_section(
                layout_html, slide_spec.template_section_index
            )
        except IndexError:
            logger.warning(
                "template_section_index %s is out of range for this layout; "
                "briefing position %s with no section markup",
                slide_spec.template_section_index,
                position,
            )

    branch_payload = {
        "session_id": state["session_id"],
        "graph_release_id": state["graph_release_id"],
        "turn_id": state["turn_id"],
        # The collaboration trace, DECLARED here because a Send-reached node sees
        # only its payload: the slide pipeline and every stage in it cannot read
        # state at all, so an omission here is an unattributed mutation rather
        # than an error.  Copied, never re-resolved — invoke_graph resolved the
        # owner once for the whole turn, and a branch that looked it up again
        # could disagree with its siblings.
        "root_session_id": state.get("root_session_id") or "",
        "actor_session_id": state.get("actor_session_id") or "",
        "initiated_by": state.get("initiated_by"),
        "position": position,
        "slide_spec": slide_spec.model_dump(),
        # assumes/hands_off are inside slide_spec too; they are lifted out
        # because they are the hand-off contract between adjacent slides and
        # the plan names them as first-class payload fields.
        "assumes": slide_spec.assumes,
        "hands_off": slide_spec.hands_off,
        "design_contract": spec.design_contract.model_dump(),
        "resolved_data": spec.resolved_data.model_dump(),
        "section_html": section_html,
        "section_css": state.get("deterministic_css") or "",
        "resolved_style": state.get("resolved_style") or "",
        "design_system_active": bool(state.get("design_system_active")),
    }
    # Only when the deck has one: an old deck's payload is exactly what it was.
    if spec.deck_style is not None:
        branch_payload["deck_style"] = spec.deck_style.model_dump()
    return branch_payload


# ---------------------------------------------------------------------------
# architect_node
# ---------------------------------------------------------------------------


# The refusal for an edit spec that drops or renumbers slides.  An edit may ADD
# slides (#314), so the sentence names only what is still refused.
_POSITIONS_CHANGED_TEXT = (
    "I could not apply that edit: it would have removed or renumbered slides, "
    "and an edit only adds slides or changes the ones that are there. Nothing "
    "has been changed."
)

# An edit spec the alignment cannot read without guessing (#314, D1), by
# ``AlignmentRefused.code``: the degrade code and the user's sentence.
# ``removes_slides`` is caught earlier by the position-set guard; it falls back
# to that guard's refusal should it ever get here.
_ALIGNMENT_REFUSALS = {
    "ambiguous": (
        "edit_insert_ambiguous",
        "I could not tell which of the existing slides I was changing and where "
        "the new slide goes, so nothing has been changed. Ask me to add the slide "
        "on its own first, then for the other change.",
    ),
    "moves_slides": (
        "edit_spec_moves_slides",
        "I could not apply that edit: it would have moved existing slides, and an "
        "edit only adds slides or changes the ones that are there. Nothing has "
        "been changed.",
    ),
}

# What a refused edit without operations tells the MODEL (spec §4: "the problem
# tells the model to list the changes as operations").  The user's sentence above
# and ``error_state`` keep their text; only the retry's problem (and the refusal
# row's, which the next turn's note replays) says this.  Each problem says what
# went wrong and then how to answer instead — never that the change cannot be
# made, because as operations it can: the prompt's ``rejected_edit`` rule turns
# "cannot be done" into a ``discuss`` that tells the user deleting or moving is
# impossible, the very symptom operations exist to remove.  So the alignment's
# own detail ("removing slides is not supported", "an edit cannot move a slide")
# reaches ``error_state`` only, never the model.
_AS_OPERATIONS = (
    "return this edit as `operations` (insert, update, delete, replace or move, "
    "at the positions of current_deck_spec) instead of a revised deck_spec: "
    "removing a slide is a delete and reordering slides is a move"
)

# What the alignment could not read, by ``AlignmentRefused.code``, in the model's
# terms and with no verdict on what an edit may do.
_ALIGNMENT_PROBLEM_DETAILS = {
    "ambiguous": (
        "your revised deck_spec can be matched to current_deck_spec in more than "
        "one way, so it is unclear which slides are new and which were changed"
    ),
    "moves_slides": (
        "your revised deck_spec moves a slide: one of its slides is a copy of a "
        "different slide of current_deck_spec"
    ),
    "removes_slides": (
        "your revised deck_spec has fewer slides than current_deck_spec"
    ),
}


def _as_operations_problem(code: str, what_went_wrong: str) -> OperationProblem:
    """A refused full-spec edit's problem: what went wrong, then answer as operations."""
    return OperationProblem(code, (), f"{what_went_wrong}; {_AS_OPERATIONS}")

# The two ways a row write planned against the committed rows can fail to land
# (#314 D4).  The insert shift and the operations layout share the CODES, so an
# operator sees one code per cause whichever path wrote.  They do not share the
# sentences (C11): the insert shift's predate the operations path and are kept
# byte for byte, but "I have not added the slide" is false of a delete or a move,
# so the operations layout says the edit-neutral twin.  The rows-changed one is
# NOT a failure: the deck moved under the planner (a panel edit while the
# architect thought), so nothing the model could fix.
_ROWS_CHANGED_DEGRADE = {
    "code": "insert_rows_changed",
    "message": "the committed rows are not the rows the insert was "
    "planned against",
    "user": (
        "The deck changed while I was planning, so I have not added "
        "the slide. Nothing has been changed; please ask again."
    ),
}
_OPERATIONS_ROWS_CHANGED_DEGRADE = {
    "code": "insert_rows_changed",
    "message": "the committed rows are not the rows the edit was planned against",
    "user": (
        "The deck changed while I was planning, so I have not made that edit. "
        "Nothing has been changed; please ask again."
    ),
}


def _rows_failed_degrade(exc: Exception, *, operations: bool = False) -> Dict[str, str]:
    """The refusal for a row write that raised anything else (the type, never the text).

    *operations* selects the operations layout's edit-neutral sentence (C11).
    """
    return {
        "code": "insert_rows_failed",
        "message": type(exc).__name__,
        "user": (
            "I could not make that edit, so nothing has been changed. "
            "Please try asking again."
            if operations
            else "I could not add the slide, so nothing has been changed. "
            "Please try asking again."
        ),
    }


# The planning refusals the model can fix (spec §5), by degrade code: operations
# problems (and the DeckSpec problems composing reports with them), template
# binding errors, today's alignment and position-set refusals of a full-spec
# edit, and an edit that returned neither operations nor a spec (a slip the new
# prompt's "deck_spec is not needed" invites).  The full-spec and spec-less ones
# tell the model to answer with operations (_AS_OPERATIONS).  On one of these
# the architect is asked ONCE more, told what it answered and exactly why that
# was refused, and the turn degrades only if the second answer is refused too.
# Everything else is the deck's state, not the answer's — no persisted spec, a
# spec the rows have outgrown, and a row write that did not land — so asking
# again would only spend a model call to reach the same refusal.
RETRYABLE_EDIT_CODES = frozenset(
    {
        "edit_operations_rejected",
        "invalid_slide_type_binding",
        "edit_insert_ambiguous",
        "edit_spec_moves_slides",
        "edit_spec_positions_changed",
        "edit_without_revised_spec",
    }
)

# What of a refused answer the retry hands back as ``your_previous_answer``
# (spec §5): what the answer asked for, not its prose or its whole spec.
_PREVIOUS_ANSWER_FIELDS = {"intent", "operations", "deck_changes", "target_positions"}


def _binding_problems(binding_errors: Sequence[str]) -> Tuple[OperationProblem, ...]:
    """Template binding errors as problems: one per bad slide, naming no position.

    The slide may not have a persisted position (an insert, a build), and the
    error already numbers it.
    """
    return tuple(
        OperationProblem("invalid_slide_type_binding", (), error) for error in binding_errors
    )


def _refusal_problems(degrade: Dict[str, Any]) -> Tuple[OperationProblem, ...]:
    """Why *degrade* refused, as problems: what a retry is told and the row records.

    A planning refusal carries its own under ``"problems"`` (an operations list's,
    one per binding error, and for an edit without operations — refused by the
    alignment or the position-set guard, or carrying no spec at all — one that
    says what went wrong and to answer with operations).  Any other refusal is
    one problem: its code and its model-facing message.
    """
    problems = degrade.get("problems")
    if problems:
        return tuple(problems)
    return (OperationProblem(degrade["code"], (), degrade["message"]),)


def _problem_payload(problem: OperationProblem) -> Dict[str, Any]:
    """*problem* as the JSON the model is shown and the row stores (spec §5)."""
    return {
        "code": problem.code,
        "positions": list(problem.positions),
        "detail": problem.detail,
    }


# The opening of an operations refusal (spec §5).  What follows it is the
# problems, one clause each, in the user's slide numbers.
_OPERATIONS_REJECTED_PREFIX = (
    "I couldn't apply that edit, so nothing in the deck has changed: "
)


def _operations_rejected(
    problems: OperationProblems, slide_numbering: List[Dict[str, int]]
) -> Dict[str, Any]:
    """The degrade for an operations list that does not check out (spec §4-§5).

    Two audiences, two texts.  The user gets ``problem_sentence``'s clauses,
    numbered off ``slide_numbering`` — the deck as the user saw it when they
    wrote the message, which is also what every operation's positions count, so
    a gapped deck's position 5 is "slide 3" and not "slide 6".  ``error_state``
    gets the model-facing details, in positions, which is what an operator
    reading the turn needs and what the model itself can act on.  The deck's
    size is the numbering's: the slides the user can see, rows when the deck
    has any.  The problems themselves travel too, for the retry and the row.
    """
    numbers = {entry["position"]: entry["slide_number"] for entry in slide_numbering}
    count = len(slide_numbering)
    return {
        "code": "edit_operations_rejected",
        "message": "; ".join(problem.detail for problem in problems.problems),
        "user": (
            _OPERATIONS_REJECTED_PREFIX
            + "; ".join(
                problem_sentence(problem, numbers, count) for problem in problems.problems
            )
            + "."
        ),
        "problems": problems.problems,
    }


def _degrade_edit(
    state: dict, updates: Dict[str, Any], degrade: Dict[str, Any]
) -> Dict[str, Any]:
    """Turn an edit that cannot be applied into a discussion, said on both surfaces.

    Mutates *updates* (and returns it); callers then ``return updates`` so the
    node's state keys stay visible in the node itself.

    The row records why (spec §7): ``metadata={REFUSAL_METADATA_KEY: {"code",
    "problems"}}``, the problems being the ones a retry is handed
    (:func:`_refusal_problems`).  ``_conversation`` replays them to the
    architect next turn as a note after the refusal.
    """
    # An edit that cannot be applied.  Degrade to a discussion turn rather
    # than routing to a foreman that would cover no positions and reach deck
    # review on an unbuilt deck — or dispatch a builder against a brief that
    # describes another slide.  ONE degrade path for every cause,
    # deliberately: several shapes of the same refusal would be several things
    # to keep in step.  Only the code and the sentence differ, and the
    # sentence differs because telling a user with a visible deck that no
    # specification could be found would be false.
    updates["architect_intent"] = "discuss"
    updates["architect_message"] = degrade["user"]
    updates["error_state"] = {
        "node": "architect",
        "code": degrade["code"],
        "message": degrade["message"],
    }
    # A failed shift degrades AFTER the edit's targets were set, and a refused
    # edit rebuilds nothing.
    updates["target_positions"] = None
    # The refusal is the ONLY thing said (spec §7).  A build's or an edit's own
    # line ("Editing slide 2.") waits until its plan has landed, so on a refusal
    # it was never said — saying it would tell the user an edit is under way and
    # then nothing happens.  The refusal is SAID, on the same two surfaces the
    # model's line would have taken, or the user is shown nothing for a turn
    # that called the model.  A describe-only turn stays silent the same way the
    # model's line does: _say suppresses it and the sweeper has no emitter.
    _emit(StreamEventType.ASSISTANT, content=degrade["user"],
          metadata={"node": "architect", "intent": "discuss"})
    refusal = {
        "code": degrade["code"],
        "problems": [_problem_payload(p) for p in _refusal_problems(degrade)],
    }
    _say(state, degrade["user"], metadata={REFUSAL_METADATA_KEY: refusal})
    return updates


@dataclass(frozen=True)
class _EditPlan:
    """An edit given as operations that has passed every check (spec §4 steps 2-3).

    Two numberings, and which field is in which is the point:

    * ``spec`` and ``rebuild`` are in the numbering of the deck the edit
      produces — ``rebuild`` is the positions of ``spec`` to build.  That is
      ``0..m-1`` after a re-stamp, or the persisted positions when
      ``keeps_positions`` (C10: an identity layout re-stamps nothing, so a gapped
      deck's rows and spec keep agreeing and the next turn is not
      ``spec_positions_stale``).
    * ``layout`` is ``apply_operations``' own, in PERSISTED positions: entry *i*
      is the persisted position whose row lands at index *i*, ``None`` a new
      slide.  The writer takes row indices, so ``_apply_edit_plan`` maps it (C7).

    ``references_map`` takes a persisted position — what the user's message and
    its resolved ``slide_references`` count — to its position in ``spec``; a
    deleted slide has no entry.  ``brand`` is the brand of ``spec``'s contract,
    re-resolved when the edit changed it, and every later step must use it rather
    than the brand the turn started with.

    ``keeps_positions`` cannot be derived from the other fields: a re-stamped
    deck that only lost its last slides has ``spec`` positions equal to its
    ``layout`` too, and is a layout the rows must still follow.
    """

    spec: DeckSpec
    layout: Tuple[Optional[int], ...]
    rebuild: Tuple[int, ...]
    references_map: Dict[int, int]
    brand: Dict[str, Any]
    keeps_positions: bool


#: The class of every slide's frame (``<div class="slide">``), whatever the
#: template: a deck style may scope a piece under it, but never owns it.
_SLIDE_FRAME_CLASS = "slide"


def _stranded_style_classes(
    prior_spec: DeckSpec,
    composed: DeckSpec,
    result: OperationsResult,
    committed_rows: List[Dict[str, Any]],
    style_block: str,
) -> Optional[OperationProblems]:
    """Classes the composed deck style drops that a kept, non-rebuilt slide uses.

    Spec §5: a slide still using a class the new style drops would silently lose
    its styling, so every such slide needs an ``update`` in the same edit.  Kept
    means ``result.layout`` carries the slide over and ``result.rebuild`` does not
    list it; a moved slide is kept, as its row travels whole.  The problem's
    positions are the PERSISTED ones, which the rows are at (the caller has
    passed the persisted-spec guards).

    Every class the style stops naming counts — the ``dk-`` pieces and the
    unprefixed classes inside them alike (a code block's ``.dk-code .kw`` token
    spans: renaming ``kw`` strips the keyword colour from every kept slide) —
    except the classes something else styles anyway (Ruling R22): the template's
    own, those of *style_block* (the composed contract's template CSS), and the
    slide frame's ``slide``.  A style that stops scoping a piece under one of
    those (``.slide .dk-note`` to ``.dk-note``) strips nothing from a slide.
    ``None`` when nothing is stranded.
    """
    html_by_position = {
        row.get("position"): row.get("html") or "" for row in committed_rows
    }
    rebuilt = set(result.rebuild)
    kept_rows = {
        position: html_by_position.get(position, "")
        for index, position in enumerate(result.layout)
        if position is not None and index not in rebuilt
    }
    styled_elsewhere = css_class_names(style_block) | {_SLIDE_FRAME_CLASS}
    stranded = {
        name: positions
        for name, positions in dropped_classes_in_use(
            prior_spec.deck_style, composed.deck_style, kept_rows
        ).items()
        if name not in styled_elsewhere
    }
    if not stranded:
        return None
    return OperationProblems(
        tuple(
            dropped_class_problem(name, positions)
            for name, positions in stranded.items()
        )
    )


def _deck_changes_of(
    state: dict, out: Any, prior_spec: DeckSpec
) -> Optional[DeckChanges]:
    """The answer's ``deck_changes``, plus a contract given only in ``deck_spec`` (C19).

    The prompt commits a confirmed contract inside ``deck_spec`` on a build and in
    ``deck_changes.design_contract`` on an edit (its DESIGN SYSTEMS block said
    "inside deck_spec" only until the ``edit-ops-b`` follow-up).  This is a
    tolerance for an operations answer that still puts it in ``deck_spec``: it
    would lose the contract, since the operations path reads nothing else of
    ``deck_spec`` — and it still reads nothing else: not its slides, not its
    other deck-level fields.  So when ``deck_changes`` sets no contract and
    ``deck_spec`` carries one whose ids differ from the persisted spec's, that
    contract is the edit's.  The same contract is no change and adopts nothing,
    so an echoed spec cannot turn ``nothing_to_do`` into a no-op edit.

    Returns a copy; the answer is not mutated, so a retry plans from it afresh.
    """
    changes = out.deck_changes
    adopted = _contract_from_deck_spec(out, prior_spec)
    if adopted is None:
        return changes
    logger.info(
        "operations_contract_from_deck_spec: the architect's operations answer "
        "sets no deck_changes.design_contract but its deck_spec carries %s (the "
        "persisted spec has %s); committing that contract",
        _contract_ids(adopted),
        _contract_ids(prior_spec.design_contract),
        extra={"session_id": state.get("session_id")},
    )
    return (changes or DeckChanges()).model_copy(update={"design_contract": adopted})


def _contract_from_deck_spec(
    out: Any, prior_spec: DeckSpec
) -> Optional[DesignContractRef]:
    """The contract C19 adopts from an operations answer's ``deck_spec``, else ``None``.

    :func:`_deck_changes_of`'s rule without its log, so the deck-style sanitiser
    can find the contract an edit commits before the answer is planned without
    saying "committing that contract" twice.
    """
    changes = out.deck_changes
    if changes is not None and changes.design_contract is not None:
        return None
    spec = out.deck_spec
    if spec is None or _contract_ids(spec.design_contract) == _contract_ids(
        prior_spec.design_contract
    ):
        return None
    return spec.design_contract


def _plan_operations_edit(
    state: dict,
    out: Any,
    prior_spec: DeckSpec,
    committed_rows: List[Dict[str, Any]],
    brand: Dict[str, Any],
    slide_payload: Dict[str, Any],
) -> _EditPlan | OperationProblems:
    """Plan an edit given as ``operations``/``deck_changes``; say and write nothing.

    The planning half of the operations path (spec §4 steps 2-3), kept free of
    side effects so that a refused plan leaves nothing behind and the caller can
    plan a second answer from the same inputs: no emit, no ``_say``, no row or
    deck write.  It reads brand bytes, and only when the edit changes the
    contract.

    1. ``apply_operations`` over the persisted slides.  ``operations=None`` is the
       empty list, which is the identity (C6), so a ``deck_changes``-only edit
       composes the same slides.
    2. ``compose_edit_spec``: the persisted spec, plus the ``deck_changes``
       fields that are set, plus the composed slides, re-validated.  The one
       field ever read out of ``deck_spec`` is a new ``design_contract`` that
       ``deck_changes`` does not set (C19, :func:`_deck_changes_of`).
    3. The brand of the composed contract, by the node's own re-resolve rule.
       Then, on the same contract, a new deck style may not drop a class a kept
       slide still uses (:func:`_stranded_style_classes`).
    4. The template bindings, completed and checked on the COMPOSED spec — an
       inserted slide is checked like any other.  A binding error becomes an
       ``invalid_slide_type_binding`` problem, so it degrades (and can be
       retried) exactly like a faulty operation.
    5. The numbering decision (C10), and the targets in it.

    Every refusal is returned as ``OperationProblems``, never raised.  It is
    called only after the persisted-spec guards, which is what lets it treat the
    persisted spec's positions as the committed rows' (``committed_rows`` is not
    re-checked here; ``_apply_edit_plan`` maps onto it).  The user's numbering
    (``slide_payload``) is the caller's to apply to a refusal.
    """
    result = apply_operations(prior_spec.slides, out.operations or [])
    if isinstance(result, OperationProblems):
        return result
    deck_changes = _deck_changes_of(state, out, prior_spec)
    composed = compose_edit_spec(prior_spec, result, deck_changes)
    if isinstance(composed, OperationProblems):
        return composed

    # Today's rule, applied to the composed spec: the deck binds against the
    # template it will actually use, so a restyle in deck_changes re-resolves.
    # Compared with what the inbound brand was resolved FOR, not with the
    # persisted contract: a session whose own selection differs from the spec's
    # resolves the spec's on an edit, exactly as the full-spec path does.
    if _contract_ids(composed.design_contract) != brand.get("resolved_for"):
        brand = _resolve_brand(composed.design_contract)

    # Spec §5 (R7, C17): a restyle may not strand a kept slide.  Checked only
    # when this edit brings a deck style and there was one to drop from, and
    # never on a contract change: that rebuilds every slide (classify_spec_change,
    # later), so its fresh style strands nothing.  The composed spec's contract
    # decides, wherever the answer gave it (C19).  After the re-resolve, so the
    # template classes it leaves out (R22) are the composed contract's.
    if (
        deck_changes is not None
        and deck_changes.deck_style is not None
        and prior_spec.deck_style is not None
        and _contract_ids(composed.design_contract)
        == _contract_ids(prior_spec.design_contract)
    ):
        stranded = _stranded_style_classes(
            prior_spec, composed, result, committed_rows, brand["style_block"]
        )
        if stranded is not None:
            return stranded

    # While the composed spec is still numbered 0..m-1, so an error's "slide N"
    # is that slide's number in the deck the edit produces.  On an identity
    # layout that is also the user's own number, which position + 1 on a gapped
    # deck is not.  complete_index_only_bindings mutates; `composed` is
    # compose_edit_spec's fresh copy, so nothing the caller holds changes.
    complete_index_only_bindings(composed, brand["section_inventory"])
    binding_errors = invalid_slide_bindings(composed, brand["section_inventory"])
    if binding_errors:
        # One problem per bad slide, naming no persisted position: the slide may
        # not have one (an insert), and the detail already numbers it.
        return OperationProblems(_binding_problems(binding_errors))

    persisted = tuple(sorted(slide.position for slide in prior_spec.slides))
    if result.layout == persisted:
        # C10: the identity — the same persisted positions, in order, no new
        # slide — moves no row, so the spec must not move either.  Each composed
        # slide takes back the persisted position it came from, the targets are
        # those positions, and nothing reaches the row writer.  This is today's
        # equal-length rule (#314 D1: an edit that adds nothing keeps positions);
        # re-stamping a gapped (0, 2, 5) deck to 0..2 would leave its rows behind
        # and brief a builder at a position with no row.
        spec = composed.model_copy(
            update={
                "slides": [
                    slide.model_copy(update={"position": position})
                    for slide, position in zip(composed.slides, result.layout)
                ]
            }
        )
        rebuild = tuple(result.layout[index] for index in result.rebuild)
        references_map = {position: position for position in persisted}
        keeps_positions = True
    else:
        # Anything else re-stamps 0..m-1, rows and spec together, as an insert
        # does today: the composed spec already is that numbering.
        spec = composed
        rebuild = tuple(result.rebuild)
        references_map = {
            position: index
            for index, position in enumerate(result.layout)
            if position is not None
        }
        keeps_positions = False

    # The model's own targets are never honoured here: the operations say what
    # is built, and a target counted in the pre-message numbering would rebuild
    # (and destroy the hand edits on) a slide that only moved.  A difference is
    # logged, as on the insert path.  An empty list is no claim — an edit given
    # as operations needs no targets, and warning on every one would bury the
    # answers that do disagree.
    model_targets = sorted(set(out.target_positions))
    if model_targets and model_targets != list(rebuild):
        logger.warning(
            "operations_targets_disagree: the model targeted positions %s but its "
            "operations build %s; building %s",
            model_targets,
            list(rebuild),
            list(rebuild),
            extra={"session_id": state.get("session_id")},
        )

    return _EditPlan(
        spec=spec,
        layout=tuple(result.layout),
        rebuild=rebuild,
        references_map=references_map,
        brand=brand,
        keeps_positions=keeps_positions,
    )


def _apply_edit_plan(
    state: dict,
    plan: _EditPlan,
    committed_rows: List[Dict[str, Any]],
    updates: Dict[str, Any],
) -> Optional[Dict[str, str]]:
    """Land *plan*: lay the rows out as it says, then target what it builds.

    Returns ``None`` once the plan has landed, with ``target_positions`` set on
    *updates*; otherwise the degrade the caller hands to ``_degrade_edit``, with
    nothing written.  Targets are set only here because they name rows, and a
    plan whose rows did not move names rows that are not there.

    **The rows** (spec §4 step 4, §6).  An identity layout (``keeps_positions``)
    writes nothing: builders overwrite the updated rows in place, as on today's
    equal-length edit.  Anything else is ONE ``SlideWriter.apply_slide_layout``
    transaction — rows moved, deleted and opened as pending placeholders, the
    composed spec and the version bump, or nothing — before any builder is
    dispatched and before ``classify_spec_change``, so a deck-level re-review
    reads each slide's own HTML against its own composed entry.

    The writer is called whatever the top-of-node read returned, exactly as the
    insert shift is: that read swallows errors and returns ``[]``, and the writer
    re-reads in its own transaction and refuses rows the node did not plan
    against.  A deck with no rows at all (described, not yet built) has nothing
    to move: every slot is new to the writer, which then only takes the spec.
    """
    session_id = state["session_id"]
    if not plan.keeps_positions:
        try:
            # The plan's persisted positions as the writer's row INDICES (C7),
            # for the layout and for the operation it is recorded as.  The rows
            # are in position order and, past the persisted-spec guard, at
            # exactly the persisted spec's positions, so the lookup is total; a
            # miss would mean the guard was bypassed, and it fails closed (a
            # KeyError, a write that never starts) rather than reading a missing
            # row as a new one and deleting the slide that was there.
            if committed_rows:
                row_index = {
                    row.get("position"): index for index, row in enumerate(committed_rows)
                }
                row_layout = [
                    None if position is None else row_index[position]
                    for position in plan.layout
                ]
            else:
                row_layout = [None] * len(plan.layout)
            SlideWriter().apply_slide_layout(
                session_id,
                row_layout,
                deck_spec=plan.spec.to_json(),
                expected_rows=[
                    (row.get("slide_id"), row.get("content_hash"))
                    for row in committed_rows
                ],
                created_by=state.get("initiated_by"),
                mutation=_deck_mutation_context(
                    session_id,
                    state.get("graph_release_id"),
                    operation=layout_mutation_operation(row_layout, len(committed_rows)),
                    object_type="deck",
                ),
            )
        except SlideRowsChangedError:
            # Caught before Exception: it IS a RuntimeError, and a deck someone
            # changed mid-plan is not a failure — nor something a retry can fix.
            logger.warning(
                "The deck's rows changed while the architect planned an edit; "
                "nothing was laid out",
                exc_info=True,
                extra={"session_id": session_id},
            )
            return dict(_OPERATIONS_ROWS_CHANGED_DEGRADE)
        except Exception as exc:
            _raise_if_persisted_runtime_failure(exc)
            logger.exception("Laying out the rows for an operations edit failed")
            return _rows_failed_degrade(exc, operations=True)
        logger.info(
            "Laid out the rows for an operations edit as %s (persisted positions "
            "%s); building %s",
            row_layout,
            list(plan.layout),
            list(plan.rebuild),
            extra={"session_id": session_id},
        )
    # Possibly empty: a delete- or move-only edit builds nothing, and `[]` (not
    # None, which would cover every position) sends the foreman straight to deck
    # review.
    updates["target_positions"] = list(plan.rebuild)
    return None


def _say_architect_message(state: dict, message: str, intent: str) -> None:
    """Say the architect's own message for the turn, on both surfaces.

    BOTH surfaces, and the pairing is the fix.  The event is what an SSE client
    sees as it happens; the row is what a POLLING client sees at all, and what
    the architect reads back next turn as its own words.  An emit without a row
    is the shape that shipped: the model was called, the turn completed, and the
    user saw nothing.

    WHEN it is said is the caller's (spec §7): straight away on a turn that
    plans nothing, and on a build or an edit only once the plan has landed.
    """
    _emit(StreamEventType.ASSISTANT, content=message,
          metadata={"node": "architect", "intent": intent})
    _say(state, message)


# What an edit's retry is told when the sanitiser kept nothing of its
# ``deck_changes.deck_style`` (Ruling R4); the sanitiser's notes follow it.
_DECK_STYLE_DROPPED_PREFIX = "deck_changes.deck_style was dropped: "


def _design_system_active_for(
    contract: Optional[DesignContractRef], brand: Dict[str, Any]
) -> bool:
    """Whether *contract* resolves to a design system, as its brand would say.

    *brand*'s own flag when *contract* is the one it was resolved for; otherwise
    the style source alone is resolved, exactly as :func:`_resolve_brand` would
    resolve it.  Never ``_resolve_brand`` itself: a contract's template bytes are
    resolved once per turn, by the planner that commits it.
    """
    if _contract_ids(contract) == brand.get("resolved_for"):
        return brand["design_system_active"]
    from src.services.agent_resolution import resolve_style_source

    style = resolve_style_source(_agent_config_for(_with_default_template(contract)))
    return bool(style.design_system_active)


def _sanitise_answer_deck_style(
    out: Any,
    session_id: str,
    *,
    prior_spec: Optional[DeckSpec],
    brand: Dict[str, Any],
) -> Tuple[Any, Optional[Tuple[str, ...]]]:
    """*out* with ``deck_spec.deck_style`` and ``deck_changes.deck_style`` sanitised.

    Applied to every answer, the retry's included, BEFORE it is planned, so no
    check, commit or ``deck.css`` write ever reads a deck style the sanitiser has
    not passed, and a retry's ``your_previous_answer`` echoes the cleaned answer.
    Each style is cleaned under the design-system flag of the contract it would
    commit with (Ruling R3: on a design system ``:root`` goes too, or it would
    replace the template's in the post-commit merge): ``deck_spec``'s own
    contract, and for ``deck_changes`` the composed spec's — its own contract,
    else the one C19 adopts from ``deck_spec``, else the persisted spec's.  Each
    note is logged.

    Returns the cleaned copy (*out* itself when it carries no style, so an old
    deck resolves and logs nothing more), and the notes when the sanitiser kept
    nothing of ``deck_changes.deck_style`` — an edit whose only change that was
    is refused for it (R4), one with other changes applies them without it (R31,
    :func:`_plan_answer`) — else ``None``.  A build whose ``deck_spec`` style is
    dropped commits ``deck_style=None`` and builds.
    """
    update: Dict[str, Any] = {}
    dropped: Optional[Tuple[str, ...]] = None
    spec = out.deck_spec
    if spec is not None and spec.deck_style is not None:
        cleaned, _ = _sanitise_logged(
            "deck_spec",
            spec.deck_style,
            _design_system_active_for(spec.design_contract, brand),
            session_id,
        )
        update["deck_spec"] = spec.model_copy(update={"deck_style": cleaned})
    changes = out.deck_changes
    if changes is not None and changes.deck_style is not None:
        cleaned, notes = _sanitise_logged(
            "deck_changes",
            changes.deck_style,
            _design_system_active_for(_committed_edit_contract(out, prior_spec), brand),
            session_id,
        )
        if cleaned is None:
            dropped = notes
        update["deck_changes"] = changes.model_copy(update={"deck_style": cleaned})
    if not update:
        return out, None
    return out.model_copy(update=update), dropped


def _sanitise_logged(
    field: str, style: Any, design_system_active: bool, session_id: str
) -> Tuple[Any, Tuple[str, ...]]:
    """``sanitise_deck_style``, with each note logged against *field* and the session."""
    cleaned, notes = sanitise_deck_style(style, design_system_active=design_system_active)
    for note in notes:
        logger.info(
            "deck_style_sanitised: the architect's %s.deck_style: %s",
            field,
            note,
            extra={"session_id": session_id},
        )
    if cleaned is None:
        logger.warning(
            "deck_style_dropped: nothing of the architect's %s.deck_style could be "
            "kept (%d note(s))",
            field,
            len(notes),
            extra={"session_id": session_id},
        )
    return cleaned, notes


def _resanitise_carried_deck_style(
    plan: "_EditPlan", out: Any, session_id: str
) -> "_EditPlan":
    """*plan* with the deck style it carries from the persisted spec re-sanitised.

    An operations edit that brings no ``deck_changes.deck_style`` keeps the
    persisted one, which was sanitised under the contract it was committed with.
    When this edit moves the deck onto a design system, that style may still hold
    a ``:root`` palette, which the post-commit merge would let replace the
    template's ``:root`` (Ruling R3, C11).  So the carried style is sanitised again
    under the committed contract's flag (``plan.brand``).  Ruling R18: this runs on
    every carried style, not only when the flag differs from the inbound brand's,
    because the inbound brand is the session's contract and need not be the one
    the style was committed under.  It is a no-op otherwise: a sanitised style
    comes back unchanged under the same or a looser flag.  A style that cleans to
    nothing commits as ``deck_style=None``; the edit is not refused, since it asked
    for a contract change, not a restyle.  The plan's spec is what
    ``_apply_edit_plan`` persists, so the cleaned spec replaces it there too.
    """
    carried = plan.spec.deck_style
    changes = out.deck_changes
    if carried is None or (changes is not None and changes.deck_style is not None):
        return plan
    cleaned, notes = sanitise_deck_style(
        carried, design_system_active=plan.brand["design_system_active"]
    )
    if cleaned is carried:
        return plan
    for note in notes:
        logger.info(
            "deck_style_resanitised: the persisted deck style carried into contract "
            "%s: %s",
            _contract_ids(plan.spec.design_contract),
            note,
            extra={"session_id": session_id},
        )
    if cleaned is None:
        logger.warning(
            "deck_style_dropped: nothing of the persisted deck style could be kept "
            "under contract %s (%d note(s)); committing deck_style=None",
            _contract_ids(plan.spec.design_contract),
            len(notes),
            extra={"session_id": session_id},
        )
    return dataclass_replace(plan, spec=plan.spec.model_copy(update={"deck_style": cleaned}))


def _changes_beside_deck_style(out: Any, prior_spec: DeckSpec) -> bool:
    """Whether an operations edit changes anything but ``deck_changes.deck_style``.

    Ruling R31: an operation, any other ``deck_changes`` field that is set, or a
    contract C19 adopts from ``deck_spec`` — whatever ``compose_edit_spec`` would
    count as a change once the style is gone.
    """
    if out.operations:
        return True
    changes = out.deck_changes
    if changes is not None and any(
        getattr(changes, name) is not None
        for name in DeckChanges.model_fields
        if name != "deck_style"
    ):
        return True
    return _contract_from_deck_spec(out, prior_spec) is not None


def _brand_css_missing(brand: Dict[str, Any]) -> bool:
    """Whether *brand* asked for template bytes and got none (final review MF1).

    The contract, after the default-template fill, names a design system and a
    template, yet ``resolve_template_bytes`` failed closed (a transient DB error,
    a deactivated design system, a deleted template).  The pre-fan-out write then
    leaves ``deck.css`` as stored.
    """
    return not brand["deterministic_css"] and bool(brand.get("template_requested", False))


def _resanitise_committed_deck_style(
    spec: DeckSpec, brand: Dict[str, Any], session_id: str
) -> DeckSpec:
    """*spec* with its deck style sanitised under *brand*'s final design-system flag.

    The last gate before the pre-fan-out write (final review SF1): every other
    sanitise ran under the flag of the contract a style was committed with, and
    the R8/R23 carry brings the persisted style forward untouched, so a flag that
    changed on the same contract ids was never applied to it.  *spec* itself when
    it has no deck style or the style is clean under the flag (a fixed point,
    C24); a style that cleans to nothing commits as ``deck_style=None``.

    On a brand miss (:func:`_brand_css_missing`) the flag is forced on (Ruling
    R32): ``deck.css`` keeps its stored token and template CSS, and a deck-style
    ``:root`` would replace the token ``:root`` in the post-commit merge — which
    happens exactly when the miss is a deactivated design system, whose style
    source then reports none.
    """
    style = spec.deck_style
    if style is None:
        return spec
    cleaned, notes = sanitise_deck_style(
        style,
        design_system_active=bool(brand["design_system_active"])
        or _brand_css_missing(brand),
    )
    if cleaned is style:
        return spec
    for note in notes:
        logger.info(
            "deck_style_resanitised: the committed deck style under contract %s's "
            "final design-system flag: %s",
            _contract_ids(spec.design_contract),
            note,
            extra={"session_id": session_id},
        )
    if cleaned is None:
        logger.warning(
            "deck_style_dropped: nothing of the committed deck style could be kept "
            "under contract %s's final design-system flag (%d note(s)); committing "
            "deck_style=None",
            _contract_ids(spec.design_contract),
            len(notes),
            extra={"session_id": session_id},
        )
    return spec.model_copy(update={"deck_style": cleaned})


def _committed_edit_contract(
    out: Any, prior_spec: Optional[DeckSpec]
) -> Optional[DesignContractRef]:
    """The contract ``compose_edit_spec`` gives an operations edit's spec.

    ``deck_changes``' own contract, else the one C19 adopts from ``deck_spec``
    (:func:`_contract_from_deck_spec`), else the persisted spec's.  With no
    persisted spec the edit is refused before it is planned, so ``deck_spec``'s
    contract, if any, stands in.
    """
    changes = out.deck_changes
    if changes is not None and changes.design_contract is not None:
        return changes.design_contract
    if prior_spec is None:
        return out.deck_spec.design_contract if out.deck_spec is not None else None
    adopted = _contract_from_deck_spec(out, prior_spec)
    return adopted if adopted is not None else prior_spec.design_contract


@dataclass(frozen=True)
class _PlannedAnswer:
    """One architect answer, checked (spec §5): what the turn does with it, or why not.

    Built by :func:`_plan_answer`, which says and writes nothing, so a refused
    answer leaves no trace and the node can ask once more.  ``refusal`` is the
    degrade the answer earns, ``None`` once it has passed every check.  ``message``
    is the one the user is shown (a confirmation's carries §L4's note).  ``spec``
    and ``brand`` are the turn's from here on: an operations ``plan``'s composed
    spec and its brand, else the model's spec and the brand of its contract.
    ``alignment`` is set on a full-spec edit that was aligned.
    """

    out: Any
    intent: str
    message: str
    spec: Optional[DeckSpec]
    brand: Dict[str, Any]
    plan: Optional[_EditPlan]
    alignment: Optional[SlideAlignment]
    refusal: Optional[Dict[str, Any]]


def _plan_answer(
    state: dict,
    out: Any,
    *,
    describe_only: bool,
    inbound_contract: Optional[DesignContractRef],
    prior_spec: Optional[DeckSpec],
    committed_rows: List[Dict[str, Any]],
    committed_positions: Set[int],
    brand: Dict[str, Any],
    slide_payload: Dict[str, Any],
    deck_style_dropped: Optional[Tuple[str, ...]] = None,
) -> _PlannedAnswer:
    """Check one architect answer from the top; say and write nothing (spec §5).

    Everything ``architect_node`` decides about an answer before it may speak or
    write: the operations-ignored rule, §L4's augmentation of a confirmation and,
    for a build or an edit, every guard and check that can refuse it — the
    persisted-spec guards, the operations plan, the position-set guard, the
    template bindings and the alignment.  Free of side effects (it reads,
    resolves brands and logs, nothing more), so the node can hand a refused
    answer back to the model and plan the second answer exactly as it planned
    the first: a retry may answer with another intent altogether.

    *brand* is the inbound brand, the one the payload was built from; a plan or
    a re-pinned spec resolves its own, and the result's ``brand`` carries it.
    *out* has already been through :func:`_sanitise_answer_deck_style`, and
    *deck_style_dropped* is its notes when that kept nothing of
    ``deck_changes.deck_style``.
    """
    session_id = state["session_id"]
    intent = out.intent
    message = out.message

    # Only an edit that is not describe-only applies operations (spec §4).  Any
    # other turn carrying them is handled exactly as the same answer without
    # them — a build from its deck_spec, the sweeper's re-description through
    # deck_spec, a discussion that ends the turn — and says so here, once per
    # answer, before the turns that return early.  Ignored, not refused: refusing would
    # throw away an otherwise usable answer for a field that turn has no use for.
    operations_given = out.operations is not None or out.deck_changes is not None
    operations_edit = operations_given and intent == "edit" and not describe_only
    if operations_given and not operations_edit:
        logger.info(
            "operations_ignored: the architect's %s answer carries operations or "
            "deck_changes, which only an edit that is not describe-only applies; "
            "they are ignored",
            "describe-only edit" if intent == "edit" else intent,
            extra={"session_id": session_id},
        )

    # §L4 — a confirmation that would DROP the slide style has to say so, and it
    # has to say so in the message the user actually sees.  That is why the
    # augmentation happens HERE, before the emit and before `updates` is built:
    # the emit is the streamed assistant turn and architect_message is the
    # persisted one, so augmenting either alone would show the user a sentence
    # the transcript does not contain, or the reverse.  Planning runs on every
    # answer, so a confirmation given as the retry's answer is augmented too.
    if intent == "confirm_design_contract":
        dropped_style_id = _slide_style_being_dropped(
            out.proposed_design_contract, inbound_contract, prior_spec
        )
        if dropped_style_id is not None:
            message = "\n\n".join(
                [message.rstrip(), _SLIDE_STYLE_DROPPED.format(dropped_style_id)]
            )

    if intent not in ("build", "edit"):
        # Nothing to plan: a discussion, a data request or a confirmation is
        # never refused.
        return _PlannedAnswer(
            out=out,
            intent=intent,
            message=message,
            spec=out.deck_spec,
            brand=brand,
            plan=None,
            alignment=None,
            refusal=None,
        )

    # A build uses the architect's own spec.  An EDIT must also carry its spec
    # (the deck spec is the source of truth, so every edit returns it revised;
    # this node enforces that, not ArchitectOutput's validator) and that spec
    # briefs the builder, which resolves its brief BY POSITION out of it
    # (``build_branch_payload``).
    #
    # The model edits the PERSISTED spec, so the persisted spec must still
    # describe the deck before an edit is accepted.  Both guards below are decided
    # from ``prior_spec`` and the committed rows, BEFORE the model's spec is used
    # and whatever it returned: measured, an edit aimed at a position whose row was
    # deleted rebuilds the row and the deck gains a slide, and an edit after a
    # MIDDLE delete rewrites the human's surviving slide against the deleted
    # slide's brief.  See _persisted_spec_describes_these_rows for what this can
    # and cannot see.
    #
    # A DESCRIBE-ONLY turn (the arc-review sweeper) is the exception to both
    # persisted-spec guards and to the position-set guard: it dispatches no
    # builder, so no stale brief can reach a slide, and it is scheduled precisely
    # because a delete or duplicate left the persisted spec stale — refusing its
    # re-description would leave the spec stale for good while the sweeper clears
    # its marker.  It still needs a spec to persist.
    #
    # An edit given as OPERATIONS passes the same two persisted-spec guards — its
    # positions count the persisted deck, so a stale one would aim them at the
    # wrong slides — and then composes its spec instead of returning one
    # (``_plan_operations_edit``).  Whatever ``deck_spec`` it also carries is not
    # read — but for a new contract ``deck_changes`` does not set (C19) — the
    # composed spec is the persisted spec plus ``deck_changes`` plus the composed
    # slides, so the spec-shape guards below do not apply to it.
    spec = out.deck_spec
    edit_degrade: Optional[Dict[str, Any]] = None
    plan: Optional[_EditPlan] = None
    if intent == "edit":
        if prior_spec is None and (spec is None or not describe_only):
            edit_degrade = {
                "code": "edit_without_spec",
                "message": "intent='edit' with no committed deck_spec",
                "user": (
                    "I could not find a deck specification to edit for this "
                    "session. Tell me what you would like to build and I will "
                    "draft one."
                ),
            }
        elif not describe_only and not _persisted_spec_describes_these_rows(
            prior_spec, committed_positions
        ):
            spec_positions = sorted(s.position for s in prior_spec.slides)
            row_positions = sorted(committed_positions)
            logger.warning(
                "The persisted deck spec describes positions %s but this deck's "
                "rows are at %s, so it cannot be used to brief a build; the deck "
                "was changed outside the chat and the spec has not caught up "
                "(the arc-review sweeper re-describes it)",
                spec_positions,
                row_positions,
                extra={"session_id": session_id},
            )
            edit_degrade = {
                "code": "spec_positions_stale",
                "message": (
                    "the persisted deck_spec describes positions "
                    f"{spec_positions} but the committed rows are at "
                    f"{row_positions}"
                ),
                "user": (
                    "This deck has changed since I last described it — its slides "
                    "no longer line up with the plan I hold — so I have not "
                    "rebuilt anything. Tell me what this deck should say and I "
                    "will describe it again from what is there now."
                ),
            }
        elif (
            operations_edit
            and deck_style_dropped is not None
            and not _changes_beside_deck_style(out, prior_spec)
        ):
            # Ruling R4 (C12): the sanitiser kept nothing of the edit's deck
            # style, and the style was the edit's only change.  Planned without
            # it, the edit would be refused as "nothing to do" and the retry
            # would never learn why.  So it is refused as an operations problem
            # carrying the notes, which takes the one retry like any other.
            # Beside other changes the style is ignored instead (R31, below).
            edit_degrade = _operations_rejected(
                OperationProblems(
                    (
                        OperationProblem(
                            "invalid_deck_changes",
                            (),
                            _DECK_STYLE_DROPPED_PREFIX + "; ".join(deck_style_dropped),
                        ),
                    )
                ),
                slide_payload["slide_numbering"],
            )
        elif operations_edit:
            if deck_style_dropped is not None:
                # Ruling R31 (final review risk 1): the dropped style rides beside
                # operations or other deck_changes.  Refusing would cost the user
                # those edits for a style nothing of which could be kept — what an
                # old prompt that fills deck_style with unprefixed classes earns
                # every time — so the style is ignored (it is already None on
                # ``out``: the persisted style is carried) and the rest is planned.
                logger.warning(
                    "deck_style_ignored: nothing of the architect's "
                    "deck_changes.deck_style could be kept (%s); applying the "
                    "edit's other changes without it",
                    "; ".join(deck_style_dropped),
                    extra={"session_id": session_id},
                )
            planned = _plan_operations_edit(
                state, out, prior_spec, committed_rows, brand, slide_payload
            )
            if isinstance(planned, OperationProblems):
                edit_degrade = _operations_rejected(
                    planned, slide_payload["slide_numbering"]
                )
            else:
                # From here on the plan's spec and brand ARE the turn's: every
                # later step (classify_spec_change, the re-review, state, the
                # pre-fan-out write) reads `spec` and `brand`.
                plan = _resanitise_carried_deck_style(planned, out, session_id)
                spec = plan.spec
                brand = plan.brand
        elif spec is None:
            # ArchitectOutput's validator still accepts a spec-less edit: its
            # source is hashed into the frozen schema-contract digest, so the
            # rule is enforced here instead.  Never fall back to prior_spec —
            # that would rebuild the slide from its stale brief.
            edit_degrade = {
                "code": "edit_without_revised_spec",
                "message": "intent='edit' returned no deck_spec; the deck spec "
                "is the source of truth so an edit must return it revised",
                "user": (
                    "I could not apply that edit: I did not produce an updated "
                    "plan for the deck, so nothing has been changed. Please "
                    "try asking again."
                ),
                # What the retry is told: a slip the model can fix (M4).
                "problems": (
                    OperationProblem(
                        "edit_without_revised_spec",
                        (),
                        "your edit returned neither `operations` nor a deck_spec, "
                        "so it changes nothing; an edit must list its changes as "
                        "`operations` (insert, update, delete, replace or move, at "
                        "the positions of current_deck_spec), or return the full "
                        "revised deck_spec only to re-describe the deck as it stands",
                    ),
                ),
            }
        elif not describe_only and (
            len(spec.slides) < len(prior_spec.slides)
            or (
                len(spec.slides) == len(prior_spec.slides)
                and {s.position for s in spec.slides}
                != {s.position for s in prior_spec.slides}
            )
        ):
            # An edit may ADD slides (#314: a longer spec is aligned below), but
            # it never removes or renumbers one (there is no delete intent).  A
            # shorter spec would silently drop a committed row's spec; an
            # equal-length one with other positions describes rows that are not
            # there.
            revised_positions = sorted(s.position for s in spec.slides)
            current_positions = sorted(s.position for s in prior_spec.slides)
            edit_degrade = {
                "code": "edit_spec_positions_changed",
                "message": (
                    f"the edit's deck_spec has slide positions {revised_positions} "
                    f"but the persisted deck_spec has {current_positions}"
                ),
                "user": _POSITIONS_CHANGED_TEXT,
                # What the retry is told (spec §4): what went wrong, and to list
                # the change as operations, where a delete or a move is fine.
                "problems": (
                    _as_operations_problem(
                        "edit_spec_positions_changed",
                        f"your revised deck_spec has slide positions "
                        f"{revised_positions} but current_deck_spec has "
                        f"{current_positions}",
                    ),
                ),
            }

    # #314 follow-up (N2): a describe-only turn sees no HTML, so on a deck its
    # persisted spec describes, it keeps what it cannot see.
    if (
        describe_only
        and intent in ("build", "edit")
        and spec is not None
        and prior_spec is not None
        and edit_degrade is None
        and committed_positions
        and _persisted_spec_describes_these_rows(prior_spec, committed_positions)
    ):
        spec = _description_keeps_what_it_cannot_see(spec, prior_spec, committed_rows)

    # R8 (C18): a full-spec edit — the sweeper's re-description or an aligned
    # edit — keeps the persisted deck style whatever its deck_spec carries.  The
    # sweeper does not echo the style, and a restyle goes through
    # deck_changes.deck_style, where the dropped-class check runs; this path has
    # none.  On a contract change every slide is rebuilt, so the answer's
    # (sanitised) style stands.  R23: the sweeper's intent is model output, and a
    # describe-only BUILD re-describes the same deck (it builds nothing), so it
    # keeps the style too; only a real build writes a style of its own.
    if (
        (intent == "edit" or (describe_only and intent == "build"))
        and plan is None
        and edit_degrade is None
        and spec is not None
        and prior_spec is not None
        and _contract_ids(spec.design_contract)
        == _contract_ids(prior_spec.design_contract)
    ):
        spec = spec.model_copy(update={"deck_style": prior_spec.deck_style})

    # The spec's pinned template, not the inbound payload's: a turn that pins or
    # changes the contract binds against the template it will actually use.
    # Resolved here, before the degrade decision, so an invalid pair is refused
    # before anything is persisted or dispatched.  A plan has already done this
    # and the binding check below, on its composed spec (``_plan_operations_edit``).
    if (
        edit_degrade is None
        and plan is None
        and spec is not None
        and _contract_ids(spec.design_contract) != _contract_ids(inbound_contract)
    ):
        brand = _resolve_brand(spec.design_contract)

    if (
        edit_degrade is None
        and plan is None
        and intent in ("build", "edit")
        and spec is not None
    ):
        complete_index_only_bindings(spec, brand["section_inventory"])
        binding_errors = invalid_slide_bindings(spec, brand["section_inventory"])
        if binding_errors:
            # Never coerce the pair to None: erasing the bind would generate an
            # unrelated slide.  Same single degrade path as an unusable edit.
            edit_degrade = {
                "code": "invalid_slide_type_binding",
                "message": "; ".join(binding_errors),
                "user": (
                    "I could not use that plan because a slide is bound to a "
                    "template section that does not match: "
                    + "; ".join(binding_errors)
                    + ". Nothing has been changed."
                ),
                # One problem per bad slide, as on the operations path.
                "problems": _binding_problems(binding_errors),
            }

    # #314 (D1): which slides an edit adds is DERIVED from the two specs by an
    # order-preserving alignment, never read off the model's targets.  It runs
    # after the bindings (they mutate ``spec``) and before the degrade decision,
    # so a refusal writes nothing.  Equal-length edits are aligned too: a spec
    # that swaps two slides' entries is refused, not rebuilt in place.  Not on a
    # describe-only turn, which dispatches no builder and shifts no row, and not
    # on a plan, whose operations already say what changed.
    alignment: Optional[SlideAlignment] = None
    if (
        edit_degrade is None
        and plan is None
        and intent == "edit"
        and not describe_only
        and prior_spec is not None
    ):
        listed = [s.position for s in spec.slides]
        if listed != sorted(listed):
            logger.info(
                "The edit's deck_spec lists its slides as positions %s; they are "
                "read in position order",
                listed,
                extra={"session_id": session_id},
            )
        try:
            alignment = align_slides(prior_spec.slides, spec.slides)
        except AlignmentRefused as exc:
            code, user = _ALIGNMENT_REFUSALS.get(
                exc.code, ("edit_spec_positions_changed", _POSITIONS_CHANGED_TEXT)
            )
            edit_degrade = {
                "code": code,
                "message": exc.detail,
                "user": user,
                # What the retry is told (spec §4-§5): what the alignment could
                # not read, then to list the change as operations — not the
                # alignment's own detail, whose "is not supported" / "cannot
                # move" would steer the model to tell the user it is impossible.
                # It names no position, because what it could not read is the
                # relation between two lists, not a slide.  Its prefix keeps it
                # apart from an operations problem's code.
                "problems": (
                    _as_operations_problem(
                        f"alignment_{exc.code}",
                        _ALIGNMENT_PROBLEM_DETAILS.get(
                            exc.code,
                            "your revised deck_spec does not line up with "
                            "current_deck_spec",
                        ),
                    ),
                ),
            }

    return _PlannedAnswer(
        out=out,
        intent=intent,
        message=message,
        spec=spec,
        brand=brand,
        plan=plan,
        alignment=alignment,
        refusal=edit_degrade,
    )


def _with_genie_figures(spec: DeckSpec, figures: List[ResolvedFigure]) -> DeckSpec:
    """*spec* with *figures* as its code-owned Genie One figures.  Pure.

    Keeps the architect's own figures whose source is not Genie One and whose key
    is not one of *figures*' keys, in its order, then appends *figures* in order.
    So a Genie value the architect retyped, a Genie figure it dropped and a stray
    one it invented are all put right: what reaches ``resolved_data`` is what the
    code built from Genie One's result rows.
    """
    keys = {figure.key for figure in figures}
    kept = [
        figure
        for figure in spec.resolved_data.figures
        if figure.source != GENIE_ONE_SOURCE and figure.key not in keys
    ]
    return spec.model_copy(
        update={
            "resolved_data": spec.resolved_data.model_copy(
                update={"figures": kept + list(figures)}
            )
        }
    )


def _code_owned_genie_figures(
    state: dict, prior_spec: Optional[DeckSpec]
) -> List[ResolvedFigure]:
    """The Genie One figures this turn's spec must carry verbatim.

    The UNION, keyed by key, of the PERSISTED prior spec's Genie One figures
    (the one ``architect_node`` read from the database; a contributor's
    checkpointed ``state["deck_spec"]`` can be stale) and this turn's
    ``analyst_figures``, so a later edit can neither retype nor drop a figure an
    untouched slide still cites.  On a key both carry, this turn's value wins, in
    the prior figure's place; this turn's new keys follow, in order.
    """
    merged: Dict[str, ResolvedFigure] = {}
    if prior_spec is not None:
        for figure in prior_spec.resolved_data.figures:
            if figure.source == GENIE_ONE_SOURCE:
                merged[figure.key] = figure
    for figure in _turn_analyst_figures(state):
        merged[figure.key] = figure
    return list(merged.values())


def _turn_analyst_figures(state: dict) -> List[ResolvedFigure]:
    """This turn's ``analyst_figures``, validated; an entry that does not validate is skipped."""
    figures: List[ResolvedFigure] = []
    for raw in scoped_vals(state, "analyst_figures"):
        try:
            figures.append(ResolvedFigure.model_validate(raw))
        except Exception:
            logger.warning("An analyst figure does not validate; skipped", exc_info=True)
    return figures


def architect_node(state: dict) -> Dict[str, Any]:
    """Decide the turn's intent, commit the spec, resolve every brand value.

    Reads the **previous arc verdict** through
    ``get_deck_review(db, deck_id, digest)`` — the ws4b signature, not the
    plan's ``(session_id, deck_id)`` (§4).  The digest is of the **currently
    committed** slides, i.e. what the deck looked like when the previous turn's
    deck review ran, resolved before this turn changes anything.  Without it,
    turn *n+1* re-proposes an arc the deck reviewer already rejected, forever.

    **Sole resolver of everything brand-related** (§L5): the style branch and
    the template bytes are resolved here, once per turn, so no builder
    re-resolves inside its own branch.  The resolution runs twice only when the
    architect changes the pin this turn — the flag the architect's own skill
    call needs cannot be derived from a contract the architect has not yet
    produced, so the inbound contract (the user's session selection, else the
    persisted spec's) resolves it first, and the committed contract re-resolves
    only if its ids differ.

    Three keys are reset on every pass, and the reason is the same for all
    three: ``target_positions``, ``fix_target`` and ``error_state`` are
    single-writer keys with **no reducer and no turn scoping**, so turn 2 would
    otherwise inherit turn 1's values from the checkpointer — an edit turn's
    ``target_positions`` would silently narrow the next build turn's coverage to
    the same slides.

    Reads only fields ``ArchitectOutput`` declares: ``intent``, ``message``,
    ``deck_spec``, ``data_request``, ``target_positions``,
    ``proposed_design_contract``, ``operations``, ``deck_changes``.

    **§4.6 lives here, in two halves and one hole.**  A committed spec is
    classified against the persisted one by :func:`classify_spec_change`.  A
    ``design_contract`` change forces coverage to every position — the one place
    a rebuild-all is correct — and a ``confirm_design_contract`` turn's message
    is augmented to name the slide style that confirming would drop (§L4).  The
    third case, a ``deck_level`` change, re-reviews every committed slide against
    the new spec — SERIALLY, here, see ``rereview_committed_slides`` for the
    measurement of why it cannot be a two-pass turn — and narrows coverage to the
    slides that contradict it, so still-valid work including manual edits
    survives.

    **An edit may add slides (#314).**  Which slides are new is derived by
    aligning the edit's spec to the persisted one (``align_slides``), never read
    off the model's targets; an alignment that would guess is refused.  The spec
    is re-stamped to ``0..m-1`` and the rows are shifted to match
    (``SlideWriter.insert_pending_slides``) before ``classify_spec_change``, and
    only the new and revised slides are targeted.

    **An edit may instead list its changes as operations** (architect edit
    operations, spec §4): insert, update, delete, replace and move, against the
    persisted deck, plus ``deck_changes`` for the deck-level fields.  Nothing is
    aligned or guessed then: :func:`_plan_operations_edit` composes the next spec
    deterministically, :func:`_apply_edit_plan` lays the rows out in one
    transaction, and exactly the inserted, updated and replaced slides are
    targeted.  An edit with neither field takes the full-spec path above,
    unchanged — older releases, the describe-only sweeper and a model that
    ignores its prompt all rely on it.  Every other turn ignores both fields.

    **One retry, and nothing said before the plan lands** (spec §5, §7).  Each
    answer is checked by :func:`_plan_answer`, which says and writes nothing.  A
    refusal the model can fix (:data:`RETRYABLE_EDIT_CODES`) asks the architect
    once more, with ``rejected_edit`` naming its answer and the problems, and the
    second answer is handled from the top.  A describe-only turn is never
    retried, and a retry call that raises leaves the first answer's refusal
    standing (the persisted-runtime family still fails the turn).  A build's or
    an edit's own message
    is said only once its plan has landed; on any refusal only the refusal is
    said, and its row records why (:data:`REFUSAL_METADATA_KEY`) so the next
    turn's architect is told.
    """
    session_id = state["session_id"]
    turn_id = state["turn_id"]
    initiated_by = state.get("initiated_by")

    # #319: the placeholder's first stage, for the whole architect call
    report_phase(TurnPhase.PLANNING)

    committed_rows = _committed_slide_rows(session_id)
    committed_htmls = [row.get("html") or "" for row in committed_rows]
    committed_positions = {
        row.get("position")
        for row in committed_rows
        if row.get("position") is not None
    }
    prior_digest = compute_deck_digest(committed_htmls) if committed_htmls else None
    prior_review = None
    if prior_digest is not None:
        try:
            with get_db_session() as db:
                deck_id = _resolve_deck_id(db, session_id)
                stored = (
                    get_deck_review(db, deck_id, prior_digest)
                    if deck_id is not None
                    else None
                )
            if stored is not None:
                # get_deck_review returns Finding OBJECTS; the payload is
                # serialised with json.dumps, where a pydantic model would land
                # in the prompt as its repr.  The stored ``author`` is the
                # reviewing user's identity and stays out (#258: nothing
                # session- or user-specific reaches any role's model).
                prior_review = {
                    "digest": stored.get("digest"),
                    "findings": [
                        f.model_dump() if hasattr(f, "model_dump") else f
                        for f in (stored.get("findings") or [])
                    ],
                }
        except Exception:
            logger.warning(
                "Could not read the previous deck review; the architect will "
                "re-propose without it",
                exc_info=True,
            )

    persisted_spec_dict = None
    try:
        persisted_spec_dict = read_deck_spec(session_id)
    except Exception:
        logger.debug("No persisted deck spec", exc_info=True)
    prior_spec: Optional[DeckSpec] = None
    if isinstance(persisted_spec_dict, dict):
        try:
            prior_spec = DeckSpec.model_validate(persisted_spec_dict)
        except Exception:
            logger.warning("Persisted deck spec does not validate", exc_info=True)

    inbound_contract = _session_contract(session_id)
    if inbound_contract is None and prior_spec is not None:
        inbound_contract = prior_spec.design_contract
    brand = _resolve_brand(inbound_contract)

    # ``describe_only`` is read ahead of the payload because a describe-only turn
    # resolves no slide references (#313, D4); it is the one definition the edit
    # guards below also use.
    describe_only = bool(scoped_vals(state, "describe_only"))
    conversation = _conversation(session_id)
    slide_payload = architect_slide_payload(
        conversation,
        state.get("architect_message"),
        _deck_positions(committed_positions, prior_spec),
        describe_only=describe_only,
    )

    # The model-facing payload is content only (#258, user decision): no
    # session, user, turn or release identifier.  This dict is built for the
    # model alone, so it IS the architect's allowlist; ``session_id`` stays in
    # the node for the reads above and the writes below, and the trace gets the
    # root/actor pair through ``_assembly_context``.
    payload = {
        "conversation": conversation,
        "message": state.get("architect_message"),
        "current_deck_spec": persisted_spec_dict,
        "committed_slide_count": len(committed_htmls),
        # #313: the user's 1-based slide numbers mapped to positions, and every
        # slide reference in the user's latest message already resolved
        # (src/domain/slide_numbering.py), so the model copies positions instead
        # of computing them.
        "slide_numbering": slide_payload["slide_numbering"],
        "slide_references": slide_payload["slide_references"],
        "previous_deck_review": prior_review,
        "available_design_contract": (
            inbound_contract.model_dump() if inbound_contract else None
        ),
        "template_sections": brand["section_inventory"],
        "resolved_style": brand["resolved_style"],
        # §M1, as a PAYLOAD key and not a tool manifest — see
        # _design_system_library.  Without this the architect cannot offer a
        # brand it cannot see: available_design_contract carries only the ids
        # already in force, so every other design system in the org is invisible.
        "design_system_library": _design_system_library(),
        # The token names and template classes the deck style may use, without
        # any font data (see src/domain/deck_style.py).
        "deck_style_context": deck_style_context(
            brand["token_css"],
            brand["style_block"],
            _design_system_logos(inbound_contract.design_system_id)
            if brand["design_system_active"]
            and inbound_contract is not None
            and inbound_contract.design_system_id is not None
            else [],
        ),
    }

    # ---- ask, plan, and at most once ask again (spec §5) ---------------------
    # Every answer is planned BEFORE anything is said or written: _plan_answer
    # runs every check that can refuse it and has no side effects, so a refused
    # answer leaves no trace.  When the refusal is one the model can fix
    # (RETRYABLE_EDIT_CODES), the architect is asked once more with the SAME
    # payload plus ``rejected_edit`` — what it answered and exactly why that was
    # refused — and the second answer is planned from the top: it may be another
    # intent, a discussion included, and it passes every check the first did.  At
    # most two calls per turn, by the loop's bound; a second refusal degrades
    # with the second answer's problems.  A row write that fails later is never
    # retried: it is the deck's state, not the answer's.  A describe-only turn
    # (the arc-review sweeper) is never retried either: it is addressed to
    # nobody and builds nothing, so a second model call buys it nothing.
    rejected_edit: Optional[Dict[str, Any]] = None
    answer: Optional[_PlannedAnswer] = None
    for attempt in range(2):
        try:
            out = get_agent_runtime().run(
                "architect",
                state["graph_release_id"],
                # A NEW dict on the retry, never the first one mutated: the
                # runtime, and the trace of the first call, keep the payload they
                # were handed.
                payload if rejected_edit is None else payload | {"rejected_edit": rejected_edit},
                _assembly_context(
                    brand["design_system_active"],
                    state.get("root_session_id"),
                    state.get("actor_session_id"),
                ),
            ).output
        except Exception as exc:
            if answer is None:
                # The first call fails the turn as it always has: there is no
                # refusal to fall back on.
                raise
            # The retry is a second chance, not a new way to fail the turn: a
            # retry call that raises (the endpoint, an answer that does not parse)
            # leaves the turn refused exactly as the first answer earned, with
            # its code, sentence and problems — `answer` is still the first
            # one's.  The persisted-runtime family still fails the turn, as it
            # does on every model call.
            _raise_if_persisted_runtime_failure(exc)
            logger.warning(
                "architect_retry_failed: the architect's retry call raised %s; the "
                "turn is refused with the first answer's refusal (%s)",
                type(exc).__name__,
                answer.refusal["code"],
                exc_info=True,
                extra={"session_id": session_id},
            )
            break
        # Every answer's deck style is sanitised before it is planned, so nothing
        # downstream — the plan, the commit, the deck.css write, the retry's echo
        # of this answer — sees one the sanitiser has not passed.
        out, deck_style_dropped = _sanitise_answer_deck_style(
            out, session_id, prior_spec=prior_spec, brand=brand
        )
        answer = _plan_answer(
            state,
            out,
            describe_only=describe_only,
            inbound_contract=inbound_contract,
            prior_spec=prior_spec,
            committed_rows=committed_rows,
            committed_positions=committed_positions,
            brand=brand,
            slide_payload=slide_payload,
            deck_style_dropped=deck_style_dropped,
        )
        refusal = answer.refusal
        if (
            attempt
            or describe_only
            or refusal is None
            or refusal["code"] not in RETRYABLE_EDIT_CODES
        ):
            break
        rejected_edit = {
            "your_previous_answer": out.model_dump(
                include=_PREVIOUS_ANSWER_FIELDS, mode="json"
            ),
            "problems": [_problem_payload(p) for p in _refusal_problems(refusal)],
        }
        logger.info(
            "architect_retry: the architect's %s answer was refused (%s: %s); "
            "asking once more with the problems",
            out.intent,
            refusal["code"],
            refusal["message"],
            extra={"session_id": session_id},
        )

    intent = answer.intent
    message = answer.message
    # From here on the answer's spec and brand ARE the turn's (an operations
    # plan's composed spec and brand, else the model's spec and the brand of its
    # contract): every later step — classify_spec_change, the re-review, state,
    # the pre-fan-out write — reads `spec` and `brand`.
    spec = answer.spec
    brand = answer.brand
    plan = answer.plan
    alignment = answer.alignment

    updates: Dict[str, Any] = {
        "architect_intent": intent,
        "architect_message": message,
        "target_positions": None,
        "fix_target": None,
        "error_state": None,
    }

    if intent not in ("build", "edit"):
        # Said straight away (spec §7): nothing is planned on these turns, so
        # there is nothing to land first and nothing left that could refuse them.
        _say_architect_message(state, message, intent)
        if intent == "ask_data":
            # GraphState declares no analyst channel and undeclared keys are
            # silently dropped (§11), so the request travels in architect_message —
            # the same key the analyst answers through.
            updates["architect_message"] = "\n\n".join(
                [message, "DATA REQUEST: " + out.data_request.model_dump_json()]
            )
            return updates
        # discuss and confirm_design_contract both END the turn. A confirmation
        # WAITS for the user, so nothing may restyle before they answer, and the
        # proposal stays in proposed_design_contract — never in deck_spec (§M1).
        return updates

    if answer.refusal is not None:
        _degrade_edit(state, updates, answer.refusal)
        return updates

    # ---- Genie One figures are code-owned (Genie One in agent mode) ----------
    # Applied once, here, before any writer reads the spec: the operations
    # layout writes plan.spec, the insert shift and the deck-level write `spec`.
    # The figures are the ones the code built from Genie One's result rows, so the
    # model's copy of them (retyped, dropped, or inherited through
    # compose_edit_spec) never reaches resolved_data.  classify_spec_change does
    # not compare resolved_data, so this triggers no deck-level re-review.
    genie_figures = _code_owned_genie_figures(state, prior_spec)
    if genie_figures:
        if spec is not None:
            spec = _with_genie_figures(spec, genie_figures)
        if plan is not None:
            plan = dataclass_replace(plan, spec=_with_genie_figures(plan.spec, genie_figures))

    # ---- the operations path: land the plan (spec §4 step 4) ----------------
    # The rows are laid out FIRST — before the targets are read, any builder is
    # dispatched or classify_spec_change runs — for the reasons the insert shift
    # below gives: builders land by position, and a deck-level re-review must
    # read each slide's own row against its own composed entry.  A layout that
    # does not land is refused like a failed shift, with nothing written.
    if plan is not None:
        landing_degrade = _apply_edit_plan(state, plan, committed_rows, updates)
        if landing_degrade is not None:
            _degrade_edit(state, updates, landing_degrade)
            return updates

    # An edit that adds slides.  Its spec is re-stamped to positions 0..m-1, the
    # numbering the shifted rows will have, and that canonical spec is the one
    # every later step uses: the targets, the shift, classify_spec_change, state
    # and the pre-fan-out write.
    inserting = alignment is not None and bool(alignment.inserted_indices)
    if inserting:
        model_to_final = {
            position: index for index, position in enumerate(alignment.new_positions)
        }
        spec = spec.model_copy(
            update={
                "slides": [
                    slide.model_copy(update={"position": model_to_final[slide.position]})
                    for slide in sorted(spec.slides, key=lambda s: s.position)
                ]
            }
        )

    # Every slide the edit's spec changes is rebuilt, not only the ones the model
    # named: a slide whose brief changed but is not rebuilt is spec/slide drift.
    edit_targets: List[int] = []
    if plan is not None:
        # Exactly the inserted, updated and replaced slides, as _apply_edit_plan
        # set them once the rows had landed.  The model's own targets were
        # compared, and a difference logged, by the planner; the #313 D5 guard
        # has nothing to check, since no target here is the model's.
        edit_targets = list(updates["target_positions"])
    elif inserting:
        # D3: exactly the new and the revised slides, in the canonical numbering.
        # The model's targets are NOT honoured: one that counted in the old
        # numbering would rebuild (and destroy any hand edit on) a slide that
        # only moved.  They are compared, and a difference is logged.
        edit_targets = sorted(
            set(alignment.inserted_indices) | set(alignment.revised_indices)
        )
        updates["target_positions"] = list(edit_targets)
        model_targets = sorted(
            {model_to_final[p] for p in out.target_positions if p in model_to_final}
        )
        unknown = sorted(p for p in out.target_positions if p not in model_to_final)
        if model_targets != edit_targets or unknown:
            logger.warning(
                "insert_targets_disagree: the model targeted positions %s (%s once "
                "re-stamped%s) but the edit adds %s and revises %s; building %s",
                sorted(out.target_positions),
                model_targets,
                f"; {unknown} are not in its spec" if unknown else "",
                list(alignment.inserted_indices),
                list(alignment.revised_indices),
                edit_targets,
                extra={"session_id": session_id},
            )
        # The #313 D5 guard is skipped: on an add, a named slide is the ANCHOR
        # ("after slide 3"), never a target, so missing it is no off-by-one.
    elif intent == "edit":
        if alignment is not None:
            # Equal length: the revised POSITIONS, which equal the positional
            # comparison below on any deck, gapped included.
            changed = set(alignment.revised)
        else:
            # No alignment ran (a describe-only turn): today's comparison.
            prior_by_position = (
                {s.position: s for s in prior_spec.slides} if prior_spec else {}
            )
            changed = {
                s.position
                for s in spec.slides
                if s != prior_by_position.get(s.position)
            }
        edit_targets = sorted(set(out.target_positions) | changed)
        updates["target_positions"] = list(edit_targets)
        # #313 (D5), log only: the user named slides and the model's targets miss
        # every one of them, the signature of an off-by-one.  Nothing is
        # overridden or degraded — an off-by-one model also revised the wrong
        # SlideSpec, and legitimate edits can be disjoint from the named slides
        # ("slide 2 is perfect; tighten the rest").  Not on a describe-only turn,
        # which resolves no references.
        if not describe_only and edit_ignores_references(
            out.target_positions, slide_payload["slide_references"]
        ):
            logger.warning(
                "The edit targets positions %s but the user's message named %s; "
                "the model may have read a slide number as a position",
                sorted(out.target_positions),
                "; ".join(
                    f"{ref['text']!r} (positions {ref['positions']})"
                    for ref in slide_payload["slide_references"]
                ),
                extra={"session_id": session_id},
            )

    # A BUILD answer to an add rebuilds every position in place, so identity and
    # records stay by position and every slide after the new one is
    # mis-attributed (pre-existing build semantics, D1).  Diagnostic only: it
    # changes nothing, and it must never fail a build that shrinks or reorders
    # the deck, which the alignment refuses (C10).
    if (
        intent == "build"
        and prior_spec is not None
        and committed_rows
        and not describe_only
    ):
        try:
            probe = align_slides(prior_spec.slides, spec.slides)
        except AlignmentRefused:
            probe = None
        if probe is not None and probe.inserted_indices and not probe.revised_indices:
            logger.warning(
                "build_looks_like_insert: the build's deck_spec is the persisted "
                "spec plus new slides at %s over %d committed rows; a build "
                "rebuilds every position in place, so the slides after them lose "
                "their identity and records",
                list(probe.inserted_indices),
                len(committed_rows),
                extra={"session_id": session_id},
            )

    # ---- #314 (D4): shift the rows for the new slides ------------------------
    # At commit, before any builder is dispatched (builders land BY POSITION, so
    # a shift at land time would interleave with them) and BEFORE
    # classify_spec_change, so a deck-level re-review reads each shifted slide
    # against its own spec entry.  ALWAYS called on an insert, whatever the
    # top-of-node read returned: that read swallows errors and returns [], and
    # the shift re-reads in its own transaction and refuses rows the node did
    # not plan against.  One transaction: rows, pending placeholders, the
    # canonical spec and the version bump, or nothing.
    if inserting:
        shift_degrade: Optional[Dict[str, str]] = None
        try:
            SlideWriter().insert_pending_slides(
                session_id,
                alignment.inserted_indices,
                deck_spec=spec.to_json(),
                expected_rows=[
                    (row.get("slide_id"), row.get("content_hash"))
                    for row in committed_rows
                ],
                created_by=initiated_by,
                mutation=_deck_mutation_context(
                    session_id,
                    state.get("graph_release_id"),
                    operation="insert_slide",
                    object_type="deck",
                ),
            )
        except SlideRowsChangedError:
            # Caught before Exception: it IS a RuntimeError, and a deck someone
            # changed mid-plan is a retry, not a failure.
            logger.warning(
                "The deck's rows changed while the architect planned an insert; "
                "nothing was shifted",
                exc_info=True,
                extra={"session_id": session_id},
            )
            shift_degrade = dict(_ROWS_CHANGED_DEGRADE)
        except Exception as exc:
            _raise_if_persisted_runtime_failure(exc)
            logger.exception("Shifting the rows for an insert failed")
            shift_degrade = _rows_failed_degrade(exc)
        if shift_degrade is not None:
            _degrade_edit(state, updates, shift_degrade)
            return updates
        logger.info(
            "Inserted slides at %s (revised %s); the rows are shifted and the new "
            "positions hold pending placeholders",
            list(alignment.inserted_indices),
            list(alignment.revised_indices),
            extra={"session_id": session_id},
        )

    # ---- spec §7: the plan has landed, so say what it does ------------------
    # A build's or an edit's own message is said only HERE: once every check has
    # passed and the rows are laid out (the operations layout or the insert shift
    # above), so a refused answer's message is never shown — a refusal says only
    # the refusal (_degrade_edit).  Before the notices about blanks below, which
    # qualify it, and before classify_spec_change, so a deck-level re-review's
    # notice follows the message it reports on.
    _say_architect_message(state, message, intent)

    # #314 follow-up (N1): an untouched blank is never built.  Insert-turn
    # references count the pre-insert deck and name an anchor, so none is passed.
    blanks_said: Set[int] = set()
    numbering = slide_payload["slide_numbering"]
    if plan is not None:
        # Decided on the composed deck (spec §4): a blank no insert, update or
        # replace produced is untouched, wherever the layout moved it.  Both
        # inputs are in the plan's own numbering, the spec's positions and its
        # rebuild.  The targets list is clean of untouched blanks by
        # construction; the design-contract and deck-level lists below are what
        # this filters.
        untouched_blanks = _untouched_blank_positions(
            spec, None, False, rebuild=plan.rebuild
        )
        # C12: the "still blank" notice is said HERE, once, for every blank the
        # user named that no operation acted on or anchored to, in the user's own
        # numbers (the pre-message deck the references count).  Not left to the
        # lists' drops: the targets never hold the blank, so a plain edit would
        # never say it, and a rebuild-all would say a blank the user named only
        # as a place or to move it.  So those drops get no references.  After the
        # rows have landed, so a refused edit says only its refusal, and after the
        # model's message, so the notice follows the message it qualifies.
        _say_named_blanks(
            session_id,
            _blanks_named_but_left_alone(
                prior_spec, out.operations or [], slide_payload["slide_references"]
            ),
            slide_payload["slide_references"],
            numbering,
            blanks_said,
        )
        blank_refs = []
    else:
        untouched_blanks = _untouched_blank_positions(spec, alignment, inserting)
        blank_refs = [] if inserting else slide_payload["slide_references"]
    if untouched_blanks:
        edit_targets = _drop_untouched_blanks(
            session_id, edit_targets, untouched_blanks, blank_refs, numbering, blanks_said
        )
        updates["target_positions"] = list(edit_targets)

    # ---- §4.6: what does this commit change about the DECK, not a slide? ----
    # Classified AFTER the edit turn's target_positions is set, so the
    # design-contract branch below OVERRIDES it.  Reversing the two lines is the
    # whole defect: an "edit slide 2, and use the Acme brand" turn would restyle
    # the deck and rebuild only slide 2, leaving nineteen slides rendering
    # against a stylesheet the deck no longer has.
    spec_change = classify_spec_change(spec, prior_spec)
    if spec_change == "design_contract":
        # THE one place a rebuild-all is correct (§4.6).  A restyle genuinely
        # affects every slide, so re-review-then-selective-rebuild would flag all
        # of them anyway.  It is gated on confirmation by the topology rather
        # than by a flag: the architect asks with `confirm_design_contract`,
        # which routes to END and dispatches nothing, so a build/edit turn whose
        # spec CHANGES the contract is by construction the turn that applies an
        # answered confirmation.
        #
        # Written as the explicit position list rather than left as None.  On a
        # build turn the two are equivalent — `_covered_positions` derives every
        # spec position when target_positions is None — but only the explicit
        # list also covers the EDIT turn, and only the explicit list is visible
        # in final state, so "confirming rebuilt every position" is observable
        # rather than inferred from an absence.
        updates["target_positions"] = _drop_untouched_blanks(
            session_id,
            [slide.position for slide in spec.slides],
            untouched_blanks, blank_refs, numbering, blanks_said,
        )
        logger.info(
            "Design-contract change committed; rebuilding every position",
            extra={"session_id": session_id},
        )
    elif spec_change == "deck_level":
        # §4.6's other half: re-review ALL, rebuild only what fails.  A new
        # audience logically invalidates every slide, but a blanket rebuild-all
        # was rejected as expensive and destructive, so every committed slide is
        # scored against the NEW spec and only the ones that contradict it are
        # rebuilt — which is what preserves still-valid work INCLUDING manual
        # user edits.  The pass runs serially inside rereview_committed_slides;
        # its docstring carries the measurement of why it cannot be the two-pass
        # turn the plan imagined.
        report_phase(TurnPhase.CHECKING_SLIDES)
        verdicts = rereview_committed_slides(
            session_id,
            spec,
            brand,
            state["graph_release_id"],
            state.get("root_session_id") or "",
            state.get("actor_session_id") or "",
        )
        if not verdicts["committed"]:
            # Nothing committed to score (an unbuilt deck, or the row read
            # failed).  Coverage is left exactly as the architect set it: writing
            # an empty target list here would make the turn cover NOTHING and
            # complete vacuously, which is worse than building what was asked.
            logger.warning(
                "Deck-level spec change with no committed slide to re-review; "
                "leaving this turn's coverage as the architect set it",
                extra={"session_id": session_id},
            )
        else:
            # A position the new spec declares but no row covers cannot be
            # "still valid" — there is nothing there — so it joins the rebuild
            # set.  Without this a deck-level change that also ADDS a slide would
            # silently never build the new one.
            uncovered = {
                slide.position for slide in spec.slides
            } - verdicts["committed"]
            # An explicit edit request is honoured whatever the review said: the
            # user asked for that slide, so "it still fits the brief" is not a
            # reason to refuse.
            requested = set(edit_targets)
            rebuild = _drop_untouched_blanks(
                session_id,
                sorted(verdicts["failing"] | uncovered | requested),
                untouched_blanks, blank_refs, numbering, blanks_said,
            )
            updates["target_positions"] = rebuild

            # Could the pass judge ANYTHING?  Every position unreviewable means
            # the deck is now stale against a brief nothing checked it against,
            # and the tie-break that leaves unreviewable slides alone gives that
            # staleness no retry path.  So it must not read as a successful
            # re-review: it is recorded on error_state (single-writer, and this
            # node is its writer) and SAID in the notice, rather than reported as
            # "every slide still fits".
            # A blank is never judged (m2), so it is not a review that failed.
            judged_nothing = (
                bool(verdicts["committed"] - verdicts["blank"]) and not verdicts["reviewed"]
            )
            if judged_nothing:
                message = (
                    f"The deck's brief changed, but I could not check any of its "
                    f"{len(verdicts['committed'])} slide(s) against it — every "
                    f"re-review failed. The slides are unchanged, so the deck may "
                    f"no longer match its brief. Ask me again to re-check it."
                )
                logger.error(
                    "Deck-level spec change: every re-review failed for %d "
                    "committed slide(s); the deck is stale against its new brief "
                    "and nothing will be rebuilt to fix it",
                    len(verdicts["committed"]),
                    extra={"session_id": session_id},
                )
                updates["error_state"] = {
                    "node": "architect",
                    "code": "rereview_judged_nothing",
                    "message": message,
                    "positions": sorted(verdicts["unreviewable"]),
                }
            else:
                message = (
                    f"The deck's brief changed, so I re-checked all "
                    f"{len(verdicts['committed'])} slide(s) against it. "
                    + (
                        f"Rebuilding {slides_phrase(rebuild)}."
                        if rebuild
                        else "Every slide still fits, so I am rebuilding none."
                    )
                )
                logger.info(
                    "Deck-level spec change: re-reviewed %d slide(s), rebuilding "
                    "%s (unreviewable: %s, surfaced: %s)",
                    len(verdicts["committed"]),
                    rebuild,
                    sorted(verdicts["unreviewable"]),
                    verdicts["surfaced"],
                    extra={"session_id": session_id},
                )
            _emit(
                StreamEventType.ASSISTANT,
                content=message,
                metadata={
                    "node": "architect",
                    "spec_change": "deck_level",
                    "reviewed": sorted(verdicts["reviewed"]),
                    "rebuilding": rebuild,
                    "unreviewable": sorted(verdicts["unreviewable"]),
                    # Every finding the pass produced, objective or not. The
                    # subjective ones ARE the signal here, so dropping them left
                    # the pass with nothing to report.
                    "surfaced": verdicts["surfaced"],
                    "stale": judged_nothing,
                },
            )
            # The architect's SECOND utterance of the same turn, and it takes the
            # same pair of surfaces as its first for one reason: this is the only
            # place a user is told what the re-review decided.  Persisting the
            # reply above while leaving this one emit-only would make the
            # architect audible on a plain build turn and mute on a deck-level
            # one — the same defect, moved rather than fixed.
            _say(state, message)

    external_scripts = [SlideDeck.CHART_JS_URL]
    head_meta = json.dumps(_DEFAULT_HEAD_META)
    # The committed deck style, sanitised once more under the FINAL brand's
    # design-system flag (final review SF1).  The answer's style was sanitised
    # before it was planned, but the R8/R23 carry commits the persisted style as
    # it is, and that was sanitised under the flag of the turn that wrote it: a
    # design system reactivated on the same contract ids (or a style source that
    # swallowed an error and said "none") would let its :root palette replace
    # the template's in the post-commit merge.  On a brand miss the flag is forced
    # on (R32): the stored token :root stays in deck.css and must not be replaced.
    # A clean style is a fixed point (C24), so this is the same object on every
    # other turn.
    spec = _resanitise_committed_deck_style(spec, brand, session_id)
    # Its CSS follows the template block in both places it is written — the css
    # column below and emitted_style_blocks — so the post-commit merge keeps that
    # order and the deck style layers over the template, never under it.
    style_css = spec.deck_style.css if spec.deck_style is not None else ""

    updates.update(
        {
            "deck_spec": spec,
            "title": spec.title,
            "token_css": brand["token_css"],
            "deterministic_css": brand["deterministic_css"],
            "template_layout_html": brand["template_layout_html"],
            "resolved_style": brand["resolved_style"],
            "design_system_active": brand["design_system_active"],
            "external_scripts": external_scripts,
            "head_meta": head_meta,
            # The template block on a pinned deck, then the deck style's CSS,
            # each only when non-empty, and CSS TEXT rather than <style>-wrapped
            # markup: a wrapped block is dropped SILENTLY by the aggregator
            # (§17).  The post-commit aggregate re-merges both, in this order.
            "emitted_style_blocks": scoped(
                turn_id, [block for block in (brand["style_block"], style_css) if block]
            ),
        }
    )

    # ---- the pre-fan-out deck-level write (§H1) -------------------------
    # Five columns: title, external_scripts, head_meta, deck_spec and css.
    # external_scripts and head_meta are resolved DETERMINISTICALLY — the
    # Chart.js CDN default and the deck's <meta> set are known before any
    # builder runs, and ArchitectOutput declares neither field. The brand bytes
    # in css come from resolve_template_bytes, never from model output; the one
    # model-written part is the committed deck style, sanitised, after them.
    #
    # css is passed only when it is non-empty. Every column parameter defaults
    # to _UNSET ("leave the stored value alone") and an explicit value
    # overwrites, so passing "" on an unpinned deck would ERASE an existing
    # deck's stylesheet, and the post-commit aggregate_deck_css would then
    # preserve the erasure. Omitting it is the writer's own documented way to
    # say "this turn resolved no deterministic CSS". A committed deck style
    # makes css non-empty and replaces the stored column whole, never merged
    # into it, so a restyle leaves none of the old style's rules behind.
    # Except (final review MF1) when the brand was expected and resolved empty:
    # the contract names a design system and a template, and
    # resolve_template_bytes failed closed.  The style alone would then erase the
    # stored token and template CSS, with no backstop after it (token_css is ""
    # too), so css is omitted exactly as on an unstyled deck, and the post-commit
    # merge applies the style from emitted_style_blocks over the stored column.
    # A deck with no template to resolve (unpinned, a slide style, a design
    # system without one) still has the style replace the column.
    # spec.to_json() runs inside the try: whatever the sanitiser let through, a
    # spec that cannot serialise fails this write, never the turn.
    # A describe-only turn (ws4d's arc-review sweeper) is not a change the client
    # should see. It re-describes the narrative and changes no slide, but
    # deck.version is what the WYSIWYG client sends back as expected_version, and
    # a bump turns the human's very next save into a 409 — on exactly the deck
    # whose editor is mid-session, because the sweeper runs BECAUSE they are
    # editing. deck.updated_at, which the client renders as modified_at, is
    # suppressed by the same flag: leaving it bumped beside an unchanged version
    # token would show "modified just now" against a deck whose lock says nothing
    # changed, and that half-state is worse than either choice made consistently.
    # (``describe_only`` is read once, above the edit guards.)

    deck_write: Dict[str, Any] = {
        "title": spec.title,
        "external_scripts": external_scripts,
        "head_meta": head_meta,
        "modified_by": initiated_by,
        "user_visible": not describe_only,
    }
    css = _concat_css(brand["deterministic_css"], style_css)
    if _brand_css_missing(brand) and style_css:
        logger.warning(
            "brand_css_missing: contract %s resolved no template CSS; deck.css is "
            "left as stored and the post-commit merge applies the deck style",
            _contract_ids(spec.design_contract),
            extra={"session_id": session_id},
        )
    elif css:
        deck_write["css"] = css
    try:
        deck_write["deck_spec"] = spec.to_json()
        write_deck_level_columns(
            session_id,
            mutation=_deck_mutation_context(
                session_id,
                state.get("graph_release_id"),
                operation="write_deck_level",
                object_type="deck",
            ),
            **deck_write,
        )
    except Exception as exc:
        logger.exception("Pre-fan-out deck-level write failed")
        updates["error_state"] = {
            "node": "architect",
            "code": "deck_level_write_failed",
            "message": type(exc).__name__,
        }

    return updates


# ---------------------------------------------------------------------------
# data_analyst_node
# ---------------------------------------------------------------------------


#: The analyst runs at most this many times in one turn.  A further request is
#: answered by code, without calling the model: each Genie One question takes
#: minutes, and an architect that keeps asking would spend the job's budget.
MAX_ANALYST_ROUNDS_PER_TURN: Final = 2

_ANALYST_ROUNDS_COMPLETE: Final = (
    "Data gathering for this turn is complete. Plan the deck with the data already gathered."
)

#: Said to the user when Genie One refuses them for want of a grant (no EXECUTE
#: on the service).  A missing OAuth scope gets ``consent_message`` instead.
_GENIE_ONE_GRANT_MESSAGE: Final = (
    "Genie One refused the request. You may need EXECUTE permission on "
    "system.ai.genie_one_mcp; ask a workspace admin to grant it."
)

#: The ``tool_name`` a Genie One progress line carries, on SSE and on its row.
_GENIE_ONE_PROGRESS_TOOL: Final = "genie_one"


@dataclass(frozen=True)
class _GenieOneRun:
    """One analyst run's Genie One toolset, and what the node needs after it.

    ``token`` is the signed-in user's (the consent message names the OAuth
    client it was issued to), kept out of ``repr`` so no log line or traceback
    prints it; ``stored_conversation_id`` is the actor row's value before the
    run, so an unchanged id is not written again.
    """

    toolset: AgentToolset
    tool: GenieOneAgentTool
    token: str = field(repr=False)
    stored_conversation_id: Optional[str]


def _genie_one_run(state: dict) -> Optional[_GenieOneRun]:
    """The Genie One toolset for this run, or ``None`` to run exactly as before.

    Tools come from the ACTOR's own row (a contributor's row starts with no
    tools; the deck owner's Genie One is theirs).  Any failure to read it counts
    as no config.  With a Genie One entry, the user's identity is captured HERE,
    in the node thread, where the request's ContextVars are set: no user client
    (production fails closed) means no toolset, never the service principal's.

    **Scope pre-flight.**  When the user's token says which scopes it carries
    and ``ai-gateway`` (or ``all-apis``) is not among them, every Genie One call
    would be refused: the user is told the consent message once, here, and the
    analyst runs without tools.  A token whose scopes cannot be read is not
    refused; the gateway's answer decides.
    """
    try:
        config = resolve_agent_config(
            get_session_manager().get_session(state["actor_session_id"]).get("agent_config")
        )
    except Exception:
        logger.warning(
            "Could not read the actor's agent config; the analyst runs without tools",
            exc_info=True,
        )
        return None
    if not any(isinstance(tool, GenieOneTool) for tool in config.tools):
        return None
    try:
        client_config = get_user_client().config
        host, token = client_config.host, client_config.token
    except Exception:
        logger.warning(
            "Genie One is configured but no user client is bound; the analyst runs "
            "without tools",
            exc_info=True,
        )
        return None
    if not host or not token:
        logger.warning(
            "Genie One is configured but the user client has no host or token; the "
            "analyst runs without tools"
        )
        return None
    scopes = oauth_scopes_from_token(token)
    if scopes is not None and not scopes_grant(scopes, GENIE_ONE_SCOPE):
        logger.warning(
            "Genie One is configured but the user's token lacks the %s scope; the "
            "analyst runs without tools",
            GENIE_ONE_SCOPE,
            extra={"session_id": state.get("session_id")},
        )
        _say_consent(state, token)
        return None

    def on_question(question: str) -> None:
        # Said BEFORE the question is asked: an answer takes minutes.  Both
        # surfaces (C7): the event for SSE, the row for the polling transport.
        line = f"Asking Genie One: {question}"
        _emit(
            StreamEventType.TOOL_CALL,
            content=line,
            metadata={"node": "data_analyst", "tool_name": _GENIE_ONE_PROGRESS_TOOL},
        )
        _say(
            state,
            line,
            message_type="tool_call",
            metadata={
                "tool_name": _GENIE_ONE_PROGRESS_TOOL,
                "tool_input": {"question": question},
            },
        )

    built = build_analyst_toolset(
        config,
        host=host,
        token=token,
        on_question=on_question,
        session_id=state.get("session_id"),
    )
    if built is None:
        return None
    toolset, tool = built
    return _GenieOneRun(toolset, tool, token, tool.conversation_id)


def _merge_answer_figures(
    answers: Sequence[GenieOneAnswer],
    *,
    earlier: Sequence[ResolvedFigure] = (),
    earlier_answers: int = 0,
) -> List[ResolvedFigure]:
    """This run's NEW figures, in order, with repeats across the turn resolved.

    Seeded with *earlier*, the figures an earlier analyst round of this turn
    already wrote, and numbered turn-wide: this run's answers are questions
    ``earlier_answers + 1`` onwards.  An exact (key, value) repeat of an earlier
    figure is dropped; a key that reappears with a DIFFERENT value is kept, in
    place, as ``"<key> (question m)"``, m that 1-based turn-wide answer index.
    Keys within one answer are already unique (``figures_from_answer``).
    """
    merged: List[ResolvedFigure] = []
    values: Dict[str, str] = {figure.key: figure.value for figure in earlier}
    for index, answer in enumerate(answers, start=earlier_answers + 1):
        for figure in figures_from_answer(answer):
            key = figure.key
            if key in values and values[key] != figure.value:
                key = f"{key} (question {index})"
            if key in values:
                continue
            values[key] = figure.value
            merged.append(
                figure if key == figure.key else figure.model_copy(update={"key": key})
            )
    return merged


def _turn_answer_count(state: dict) -> int:
    """How many Genie One answers this turn's earlier analyst rounds received."""
    count = 0
    for marker in scoped_vals(state, "analyst_rounds"):
        if isinstance(marker, dict) and isinstance(marker.get("answers"), int):
            count += marker["answers"]
    return count


def _genie_one_block(
    figures: Sequence[ResolvedFigure], answers: Sequence[GenieOneAnswer]
) -> str:
    """The figure keys the architect must cite, then each distinct deep link ("" if none)."""
    lines: List[str] = []
    if figures:
        lines.append("Figures from Genie One (use these keys in data_references):")
        lines.extend(f"- {figure.key}: {figure.value}" for figure in figures)
    links: List[str] = []
    for answer in answers:
        if answer.deep_link and answer.deep_link not in links:
            links.append(answer.deep_link)
    lines.extend(f"Explore in Databricks: {link}" for link in links)
    return "\n".join(lines)


def _persist_genie_one_conversation(state: dict, run: _GenieOneRun) -> None:
    """Store a new Genie One conversation id on the ACTOR's row.  Never raises."""
    conversation_id = run.tool.conversation_id
    if not conversation_id or conversation_id == run.stored_conversation_id:
        return
    try:
        get_session_manager().set_genie_one_conversation_id(
            state["actor_session_id"], conversation_id
        )
    except Exception:
        logger.warning(
            "Could not store the Genie One conversation id; the next turn starts a "
            "new conversation",
            exc_info=True,
        )


def _say_consent(state: dict, token: str) -> None:
    """Tell the user how to give this app the permission their sign-in lacks."""
    _say(
        state,
        consent_message(oauth_client_id=oauth_client_id_from_token(token)),
        message_type="info",
    )


def _say_genie_one_access(state: dict, run: _GenieOneRun) -> None:
    """Tell the user, once per kind, what a Genie One refusal needs them to do."""
    kinds = {error.kind for error in run.toolset.access_errors}
    if "missing_scope" in kinds:
        _say_consent(state, run.token)
    if "access_denied" in kinds:
        _say(state, _GENIE_ONE_GRANT_MESSAGE, message_type="info")


def data_analyst_node(state: dict) -> Dict[str, Any]:
    """Fetch what the architect asked for and answer through ``architect_message``.

    ``GraphState`` declares no channel for the analyst's ANSWER and the runtime
    silently drops undeclared keys, so both the request and the answer travel on
    ``architect_message`` (§11, Ruling C-7); the edge back to the architect is
    static.  That key is written by two nodes and still needs no reducer,
    because the architect and the analyst never run in the same superstep.

    Returns exactly one of three outcome shapes, all as prose on that key:
    ``success`` -> the synthesis, ``missing_data`` -> the gap, ``no_tool`` ->
    the reason plus the tools tried.  Reads only ``AnalystOutput``'s declared
    fields: ``outcome``, ``synthesis``, ``sources``, ``gap``, ``tried_tools``,
    ``reason``.

    **Genie One (agent mode).**  When the ACTOR's agent config has a Genie One
    entry and a user is signed in, the run carries a toolset
    (:func:`_genie_one_run`): the model may ask Genie One up to three questions,
    as that user, each announced by a progress line.  The figures are then built
    by CODE from Genie One's result rows (``figures_from_answer``), never from the
    model's prose, and written on the turn-scoped ``analyst_figures``, which
    ``architect_node`` writes verbatim into ``resolved_data.figures``.  A second
    round in the same turn is seeded with the first round's figures and numbers
    its answers turn-wide (:func:`_merge_answer_figures`).  Every Genie figure of
    the turn and this run's deep links are listed after the analyst's prose: in
    ONE ``spotlight("genie_one", ...)`` wrapper on ``architect_message`` (they are
    Genie One's output), as plain text for the user.  A new conversation id is
    stored on the actor's row, and a refusal tells the user the consent or the
    grant they need.  Without a Genie One entry ``resolved_data.figures`` is
    whatever the architect wrote, as before: ``AnalystOutput`` still declares no
    figure field.

    **At most** :data:`MAX_ANALYST_ROUNDS_PER_TURN` **runs per turn**
    (``analyst_rounds``, one marker per run): a further request is answered by
    code, and the model is not called.
    """
    report_phase(TurnPhase.GATHERING_DATA)
    turn_id = state["turn_id"]

    if len(scoped_vals(state, "analyst_rounds")) >= MAX_ANALYST_ROUNDS_PER_TURN:
        logger.info(
            "data_analyst: %d rounds already ran this turn; answering without the model",
            MAX_ANALYST_ROUNDS_PER_TURN,
            extra={"session_id": state.get("session_id")},
        )
        return {
            "architect_message": _ANALYST_ROUNDS_COMPLETE,
            "analyst_figures": scoped(turn_id, []),
            "analyst_rounds": scoped(turn_id, [{"answers": 0}]),
        }

    request = state.get("architect_message") or ""

    # Content only (#258): the analyst's model is handed no session identifier.
    # A Genie One tool runs with the user's token captured below, never one read
    # from the payload; the session is still read off ``state`` by ``_say``.
    payload = {
        "data_request": request,
        "deck_purpose": (
            state["deck_spec"].purpose if state.get("deck_spec") else None
        ),
    }
    genie = _genie_one_run(state)
    out = get_agent_runtime().run(
        "data_analyst",
        state["graph_release_id"],
        payload,
        _assembly_context(
            state.get("design_system_active"),
            state.get("root_session_id"),
            state.get("actor_session_id"),
            toolset=genie.toolset if genie is not None else None,
        ),
    ).output

    if out.outcome == "success":
        message = out.synthesis or ""
        if out.sources:
            message = "\n".join([message, "Sources: " + ", ".join(out.sources)])
    elif out.outcome == "missing_data":
        message = (
            "The requested data could not be found: "
            + (out.gap or "no matching metrics were returned.")
        )
    else:  # no_tool
        tried = ", ".join(out.tried_tools) if out.tried_tools else "none"
        message = (
            "No tool is available for this kind of data request "
            f"({out.reason or 'no reason given'}). Tools tried: {tried}."
        )

    # The user is shown the figure block as text; the architect gets it
    # spotlighted (its column names and cells are Genie One's output).  The
    # analyst's own prose can quote Genie One, so in the architect's copy its
    # delimiters are escaped: nothing outside the wrapper can open or close one.
    architect_message = neutralize_delimiters(message)
    figures: List[ResolvedFigure] = []
    if genie is not None:
        earlier = _turn_analyst_figures(state)
        figures = _merge_answer_figures(
            genie.tool.answers, earlier=earlier, earlier_answers=_turn_answer_count(state)
        )
        # Every Genie figure of the turn is listed, so the architect can cite an
        # earlier round's keys too; only this run's new ones are written below.
        block = _genie_one_block(earlier + figures, genie.tool.answers)
        if block:
            message = f"{message}\n{block}"
            architect_message = "\n".join(
                [
                    architect_message,
                    spotlight("genie_one", block, session_id=state.get("actor_session_id")),
                ]
            )
        _persist_genie_one_conversation(state, genie)

    _emit(
        StreamEventType.ASSISTANT,
        content=message,
        metadata={"node": "data_analyst", "outcome": out.outcome},
        agent="data_analyst",
    )
    # Persisted as ``info``, NOT ``llm_response``, and the difference is not
    # cosmetic.  This is user-facing prose from a node that speaks to the user, so
    # it needs a durable row or the polling transport shows the user nothing where
    # the SSE transport showed them the analyst's answer.  But it must NOT replay:
    # ``_conversation`` has only ``user`` and ``assistant`` roles, so an
    # ``llm_response`` here would come back to the architect next turn as the
    # ARCHITECT's own words — and it would arrive twice on THIS turn, because the
    # analyst also hands the same text to the architect on ``architect_message``
    # (GraphState declares no analyst channel, Ruling C-7), which is the field the
    # architect answers from.  ``info`` is the shipped type for exactly this:
    # durable and visible, deliberately outside ``_AI_TYPES``.
    _say(state, message, message_type="info", metadata={"agent": "data_analyst"})
    if genie is not None:
        _say_genie_one_access(state, genie)

    return {
        "architect_message": architect_message,
        "analyst_figures": scoped(turn_id, [figure.model_dump() for figure in figures]),
        # The answer count numbers a later round's questions turn-wide.
        "analyst_rounds": scoped(
            turn_id, [{"answers": len(genie.tool.answers) if genie is not None else 0}]
        ),
    }


# ---------------------------------------------------------------------------
# foreman_node
# ---------------------------------------------------------------------------


def _with_wake_appended(state: dict, turn_id: str, batch: List[int]) -> dict:
    """A COPY of *state* carrying *batch* as an extra ``foreman_wakes`` entry.

    ``stalled_positions``' limb 1 excludes the most recent wake's batch, so the
    check has to run against the state the ROUTER will see — this entry's empty
    wake already appended.  Building a copy (never mutating ``state``, never
    ``wakes.append(...)``) is what keeps checkpointed state untouched.
    """
    wakes = list(scoped_vals(state, "foreman_wakes")) + [list(batch)]
    return {**state, "foreman_wakes": scoped(turn_id, wakes)}


def foreman_node(state: dict) -> Dict[str, Any]:
    """Decide what happens next, and record the decision for the router.

    **The decision order is ``dispatch -> stall -> all-committed -> END``**
    (Ruling C-2, with its leading ``fix`` limb removed: a slide's fix round now
    runs inside its own ``slide_pipeline_node``, so no fix is ever pending at a
    wake and nothing preempts dispatch).  Stall must come AFTER dispatch, not
    before as the plan had it.  The two orders are mutually unsatisfiable: after the superstep barrier, a position left
    uncommitted by a completed batch is **always in** the most recent
    ``foreman_wakes`` batch, so ``stalled_positions``' limb 1 — which excludes
    that batch — would exclude exactly the case it exists for, and the turn
    would end with a slide missing, no placeholder and nothing in chat.  The
    stall check therefore runs only once the batch has come back empty **and the
    empty wake has been recorded**, which is what makes limb 1 fire on the
    leftovers of the completed batch.

    **Consequence worth stating: a stalled position is placeheld one wake later
    than the plan implies** when unstarted work remains.  The foreman dispatches
    real work first and reconciles when the queue drains.  That costs one extra
    superstep and is strictly better than placeholding while builders are
    available.

    **``END`` is reachable only with nothing outstanding and nothing to
    reconcile.**  Reaching it with an uncommitted position is a bug, so that
    branch records ``error_state`` and surfaces a notice rather than returning
    quietly.  There is deliberately **no live-stall guard**: the barrier means
    this node runs only once a batch has completed, so a timeout evaluated here
    can never fire while a position is actually stalled, and claiming otherwise
    in a docstring would describe a guard the runtime cannot provide.

    Two writes, and how NOT to write them:

    * ``dispatched_at`` as ``scoped(turn_id, {p: now})`` — the wrapper, never
      ``state["dispatched_at"][p] = now``.  Only the positions **actually
      dispatched** are stamped: a wake whose decision is ``"placeholder"``
      or deck review stamps nothing, or the next wake reads positions that
      never started as dispatched-and-never-completed.
    * ``foreman_wakes`` as ``scoped(turn_id, [batch])`` — a wake on **every**
      entry, ``[]`` included.  ``wakes + [batch]`` returned bare arrives at
      ``turn_scoped_concat`` unwrapped, fails its ``isinstance`` check and is
      discarded or raises; ``wakes.append(batch)`` is worse still — in-place
      mutation of checkpointed state.
    """
    turn_id = state["turn_id"]

    # 0. ws4d D3 — release committed slides BEFORE the ladder, so every wake
    #    delivers what the previous superstep committed no matter which limb this
    #    wake then takes.  Inside the ladder it would sit on one branch and miss
    #    the others: the all-committed limb is the wake that carries the LAST
    #    slide of the deck.
    _release_slides(state)

    # 2/3. Compute the batch ONCE. The router reads it back out of the last
    #      wake and never recomputes it (Ruling C-1).
    batch = next_dispatch_batch(state)
    if batch:
        now = time.time()
        _emit(
            StreamEventType.ASSISTANT,
            content=f"Building {len(batch)} slide(s).",
            metadata={"node": "foreman", "batch": list(batch)},
        )
        # #319: the same moment as data — every covered position (the total
        # never shrinks across wakes) and this batch marked as building.  The
        # foreman's report is the ONLY one that puts a slide into building: it
        # precedes every Send, so the pipeline needs no start-of-build report.
        report_phase(
            TurnPhase.BUILDING,
            covered=outstanding_positions(state),
            dispatched=batch,
        )
        return {
            "foreman_wakes": scoped(turn_id, [list(batch)]),
            "dispatched_at": scoped(turn_id, {p: now for p in batch}),
        }

    updates: Dict[str, Any] = {"foreman_wakes": scoped(turn_id, [[]])}

    # 4. Reconcile against the state the router will see.
    if stalled_positions(_with_wake_appended(state, turn_id, []), time.time()):
        return updates

    # 5. Everything covered is landed or placeheld.
    if all_positions_committed(state):
        return updates

    # 6. END with work outstanding is a bug, not a quiet exit.
    #    outstanding_positions is C2's — it derives this turn's coverage from
    #    target_positions on an edit turn and from deck_spec on a build turn, so
    #    re-deriving it here would over-report on an edit.
    outstanding = outstanding_positions(state)
    message = (
        "Some slides could not be completed and could not be reconciled: "
        f"positions {outstanding}."
    )
    logger.error("Foreman reached END with uncommitted positions: %s", outstanding)
    # The technical `message` above stays for the log and `error_state`; the user
    # reads the plain-language notice instead (#321).  Guarded on `outstanding`:
    # the catalogue refuses an empty position list, and the foreman must never
    # crash the turn over the wording of its own failure notice.  `error_state` is
    # set either way.
    if outstanding:
        notice = unfinished_slides_notice(
            outstanding, request_id=get_chat_request_id()
        )
        _emit(
            StreamEventType.ERROR,
            error=notice.text,
            metadata={
                "node": "foreman",
                "positions": outstanding,
                "details": dict(notice.details),
            },
        )
        # Through `_surface_failure_notice` -> `_surface_notice`, the shipped
        # ungated writer, rather than a hand-rolled `add_message`: that is where
        # the request-id tag lives, and an untagged row never reaches
        # `GET /chat/poll`.  NOT through `_say` — this notice is a machine
        # advisory that must be durable on every turn, and `_say` suppresses a
        # describe-only one.
        _surface_failure_notice(state["session_id"], notice)
    updates["error_state"] = {
        "node": "foreman",
        "code": "end_with_outstanding_positions",
        "message": message,
        "positions": outstanding,
    }
    return updates


# ---------------------------------------------------------------------------
# builder_node
# ---------------------------------------------------------------------------


# The ONLY payload keys the builder's model is handed: the slide's content and
# styling inputs (#258, user decision — nothing session-, user-, turn- or
# release-specific reaches the model).  An allowlist, so a metadata key added to
# ``build_branch_payload`` later stays out of the prompt by default.  Excluded
# and still used by the node itself: ``session_id``, ``root_session_id``,
# ``actor_session_id`` (mutation actor, trace), ``initiated_by``, ``turn_id``
# (turn scoping), ``graph_release_id`` (release pin) and ``design_contract``
# (row IDs resolved from the session's agent config, unusable by the model) —
# all carried in the ``slides[position]`` record.  ``position`` stays:
# ``BuilderOutput.position`` echoes it.
_BUILDER_MODEL_PAYLOAD_KEYS = frozenset(
    {
        "position",
        "slide_spec",
        "assumes",
        "hands_off",
        "resolved_data",
        "section_html",
        "section_css",
        "resolved_style",
        "design_system_active",
        "deck_style",
    }
)


def builder_node(payload: dict) -> Dict[str, Any]:
    """Author one slide's body HTML from its pre-copied payload.

    Reached by ``Send``, so this receives **only the payload** — no state key is
    visible.  ``BuilderOutput`` rejects any ``<style>`` element (deck-level CSS
    has a single writer), so the node emits body HTML only.

    The emitted HTML goes through ``gate_emitted_html`` (AISEC-248) before it
    reaches state: spec §8.1 gates reviewer INPUT as well as fixer output, and
    the gate's ``regenerate`` argument is a zero-arg callable, so the corrective
    instruction travels in the payload the closure captures.

    The whole payload is carried forward in ``slides[position]`` so
    ``slide_pipeline_node`` can build the reviewer's input from it
    (:func:`build_review_payload`) — the reviewer sees nothing else.

    On any exception the position is **placeheld**, never landed:
    ``commit_placeholder`` writes a terminal marker so the reorder buffer and
    the all-committed trigger can proceed, and ``placeheld_positions`` (not
    ``landed_positions``) records it.  The failure is surfaced through an
    ``ERROR`` stream event, the row's own error marker and a logged traceback —
    and NOT through ``error_state``: that key is single-writer with no reducer,
    and two branches failing in one superstep would raise ``InvalidUpdateError``
    and kill the whole turn (measured).  It also persists a durable ``info``
    notice, exactly as the build reviewer's failure path does — the two are
    symmetric by construction, through ``_placehold_failed_position``.
    """
    position = payload["position"]
    session_id = payload["session_id"]
    turn_id = payload["turn_id"]
    design_system_active = bool(payload.get("design_system_active"))
    mutation = _deck_mutation_context(
        session_id,
        payload.get("graph_release_id"),
        operation="write_slide",
        object_type="slide",
    )

    # The model-facing payload is slide content only (#258, user decision).
    # Every metadata value stays in ``payload`` for the node's own work: the
    # mutation actor above, the trace via ``_assembly_context``, the release
    # pin, turn scoping, the placeholder and the carried record below.
    # Filtered in payload order, so the rendered prompt keeps its key order.
    skill_payload = {
        key: value
        for key, value in payload.items()
        if key in _BUILDER_MODEL_PAYLOAD_KEYS
    }
    # The brand-asset search rides on the context, never in the model-facing
    # payload; ``None`` for an old deck, so its call is today's.  Each run builds
    # its own toolset: one counts its calls, so the retry must not inherit them.
    try:
        out = get_agent_runtime().run(
            "builder",
            payload["graph_release_id"],
            skill_payload,
            _assembly_context(
                design_system_active,
                payload.get("root_session_id"),
                payload.get("actor_session_id"),
                toolset=_brand_search_toolset(payload),
            ),
        ).output

        def _regenerate() -> str:
            retry_payload = {
                **skill_payload,
                "corrective_instruction": _SAFETY_CORRECTION,
            }
            return get_agent_runtime().run(
                "builder",
                payload["graph_release_id"],
                retry_payload,
                _assembly_context(
                    design_system_active,
                    payload.get("root_session_id"),
                    payload.get("actor_session_id"),
                    toolset=_brand_search_toolset(payload),
                ),
            ).output.html

        def _on_retry() -> None:
            _emit(
                StreamEventType.ASSISTANT,
                content=SAFETY_RETRY_NOTICE,
                metadata={"node": "builder", "position": position},
            )

        html, _retried = gate_emitted_html(
            out.html, _regenerate, session_id, on_retry=_on_retry
        )
        html = strip_inter_tag_escapes(html)
    except Exception as exc:
        _raise_if_persisted_runtime_failure(exc)
        logger.exception("Builder failed at position %s", position)
        if not _placehold_failed_position(
            position,
            session_id=session_id,
            node="builder",
            reason=type(exc).__name__,
            error=exc,
            mutation=mutation,
        ):
            return {}
        return {"placeheld_positions": scoped(turn_id, {position})}

    record = {
        **payload,
        "graph_release_id": payload["graph_release_id"],
        "html": html,
        "scripts": out.scripts,
    }
    return {"slides": scoped(turn_id, {position: record})}


# ---------------------------------------------------------------------------
# build_reviewer_node
# ---------------------------------------------------------------------------


def build_reviewer_node(payload: dict) -> Dict[str, Any]:
    """Review one built slide; either land it or open a fix.

    A ``slide_pipeline_node`` stage, called with :func:`build_review_payload`
    of the record the builder carried in ``slides[position]``.

    No objective finding -> **write the row**, with an explicit
    ``verification_record`` built by ``build_verification_record``, and record
    the position as landed.  At least one objective finding -> populate
    ``fix_map[position]`` with ``original_html`` **and ``original_scripts``**
    and write nothing: the row is written once, by whichever reviewer decides
    the final HTML, so a fix round cannot leave a half-reviewed row behind.

    ``objective`` is re-derived from ``CRITERIA`` (§6) before branching on it —
    it is unvalidated, so a model returning ``objective=False`` for ``overflow``
    would silently disable the fix path.

    The ``findings`` channel receives exactly what this node persisted into a
    row.  On the fix path it persists nothing, so it returns nothing to the
    channel and hands its findings to the fix reviewer through the ``fix_map``
    entry instead — ``findings`` is ``operator.add`` and NOT turn-scoped, so
    every entry lives forever and a duplicate "open" copy of a finding that is
    about to be fixed would never be superseded.

    A review the provider's parser refused (``is_provider_parse_error``:
    unparseable output, or a Finding the registry rejects) is retried once first.

    **On any exception the position is placeheld, exactly as a failed builder's
    is, and the turn continues.**  Measured before this handler existed: a
    raising ``build_reviewer`` produced **no placeholder, no deck-level write and
    nothing in chat** — the turn simply died, so §I's terminal-failure rule was
    unreachable through this node and so was the foreman's own rule that
    reaching ``END`` with an uncommitted position must record an error and
    surface a notice.  The handler uses the one sanctioned marker
    (``commit_placeholder``, detected with ``is_placeholder_record``), so the
    one-reviewer-writes-one-row invariant is untouched: this branch writes the
    placeholder row instead of a reviewed row, never both.

    It writes no ``error_state``.  That key is single-writer with no reducer, and
    two reviewers failing in the same superstep would raise
    ``InvalidUpdateError: At key 'error_state': Can receive only one value per
    step`` (measured) — killing the turn, which is the failure being fixed.  The
    failure is surfaced through the ``info`` chat notice instead, which is
    per-row, concurrency-safe, and survives ``emitter=None``.
    """
    position = payload["position"]
    session_id = payload["session_id"]
    turn_id = payload["turn_id"]
    html = payload["html"]
    scripts = payload.get("scripts") or ""
    initiated_by = payload.get("initiated_by")
    mutation = _deck_mutation_context(
        session_id,
        payload.get("graph_release_id"),
        operation="write_slide",
        object_type="slide",
    )

    try:
        content_hash = compute_slide_hash(html)
        review_payload = {
            "position": position,
            "slide_spec": payload.get("slide_spec"),
            "resolved_style": payload.get("resolved_style"),
            "section_css": payload.get("section_css"),
            "resolved_data": payload.get("resolved_data"),
            # The section the slide was built from, verbatim from the record, so
            # the reviewer can compare the built html to its source section.
            "section_html": payload.get("section_html") or "",
            "html": html,
            "scripts": scripts,
        }
        if payload.get("deck_style") is not None:
            review_payload["deck_style"] = payload["deck_style"]

        def _review():
            return get_agent_runtime().run(
                "build_reviewer",
                payload["graph_release_id"],
                review_payload,
                _assembly_context(
                    payload.get("design_system_active"),
                    payload.get("root_session_id"),
                    payload.get("actor_session_id"),
                ),
            ).output

        try:
            out = _review()
        except Exception as exc:
            if not is_provider_parse_error(exc):
                raise
            # An unparseable review is a model glitch, not a verdict on the
            # slide, and placeholding discards a good build: one more attempt
            # (measured: 2 slides in ~150 on the deck-parity devloop rounds).
            logger.warning(
                "Build review output unusable at position %s; retrying once",
                position,
                exc_info=True,
            )
            out = _review()

        findings = _stamp_findings(
            _skill_findings(out), subject_hash=content_hash, slide_index=position
        )
        objective = [f for f in findings if f.objective]

        if not objective:
            verdict = "surfaced" if findings else "clean"
            _write_reviewed_row(
                session_id=session_id,
                position=position,
                html=html,
                scripts=scripts,
                findings=findings,
                verdict=verdict,
                slide_spec=payload.get("slide_spec"),
                initiated_by=initiated_by,
                mutation=mutation,
            )
            _emit(
                StreamEventType.ASSISTANT,
                content=f"Slide {slide_number(position)} reviewed: {verdict}.",
                metadata={"node": "build_reviewer", "position": position,
                          "verdict": verdict},
            )
            return {
                "landed_positions": scoped(turn_id, {position}),
                "reviewed_positions": scoped(turn_id, {position}),
                "findings": findings,
            }

        return {
            "fix_map": scoped(
                turn_id,
                {
                    position: {
                        "original_html": html,
                        "original_scripts": scripts,
                        "finding": objective[0].model_dump(),
                        "findings": [f.model_dump() for f in findings],
                        "payload": payload,
                    }
                },
            ),
            "reviewed_positions": scoped(turn_id, {position}),
        }
    except Exception as exc:
        _raise_if_persisted_runtime_failure(exc)
        logger.exception("Build review failed at position %s", position)
        if not _placehold_failed_position(
            position,
            session_id=session_id,
            node="build_reviewer",
            reason=type(exc).__name__,
            error=exc,
            mutation=mutation,
        ):
            return {}
        # reviewed_positions too: the position is committed as a placeholder and
        # its review has run, whatever the turn does next.
        return {
            "placeheld_positions": scoped(turn_id, {position}),
            "reviewed_positions": scoped(turn_id, {position}),
        }


# ---------------------------------------------------------------------------
# fixer_node
# ---------------------------------------------------------------------------


def _land_original(
    position: int,
    entry: dict,
    *,
    session_id: str,
    initiated_by: Optional[str],
    mutation: DeckMutationContext,
) -> List[Finding]:
    """Write the pre-fix HTML back with its findings surfaced, and return them."""
    payload = entry.get("payload") or {}
    findings = [Finding.model_validate(f) for f in (entry.get("findings") or [])]
    _write_reviewed_row(
        session_id=session_id,
        position=position,
        html=entry.get("original_html", ""),
        scripts=entry.get("original_scripts", ""),
        findings=findings,
        verdict="surfaced",
        slide_spec=payload.get("slide_spec"),
        initiated_by=initiated_by,
        mutation=mutation,
    )
    return findings


def _reconcile_stale_fixes(
    stale: Dict[int, dict],
    *,
    session_id: str,
    initiated_by: Optional[str],
    mutation: DeckMutationContext,
) -> List[Finding]:
    """Land the originals for fixes left ``in_flight`` by a dead process.

    Returns the findings it persisted; the CALLER assembles the state update, so
    every state key a node writes stays inside that node's body where the
    exhaustiveness scan can see it.  A helper returning a state dict is
    invisible to that scan.

    **Unreachable from ``slide_pipeline_node``**, which hands the fixer a
    slide-local state holding one fresh (never ``in_flight``) entry; kept as the
    fixer stage's own contract for a caller that hands it a stale one.  It was
    built for the four-node topology, where the fix state was checkpointed
    between ``fixer`` and ``fix_reviewer`` supersteps: a resumed checkpoint
    could carry an ``in_flight`` entry, ``has_pending_fix`` stayed True, the
    foreman routed back to the fixer, the fixer found no fresh candidate, and
    the pair bounced until ``GraphRecursionError`` at 10007 supersteps.
    Landing the original is the same fallback the fixer's own exception path
    takes: the slide exists and is good, and the fix was only an improvement
    pass.  It costs no model call, so "exactly one fix round per position" still
    holds.

    Accepted edge: if the fix reviewer wrote the fixed row and then died before
    returning, this overwrites it with the original.  That is one lost
    improvement on a crashed turn, against a livelock on every one.
    """
    findings: List[Finding] = []
    for position, entry in sorted(stale.items()):
        logger.warning(
            "Reconciling a stale in-flight fix at position %s; landing the "
            "original slide",
            position,
        )
        try:
            findings.extend(
                _land_original(
                    position,
                    entry,
                    session_id=session_id,
                    initiated_by=initiated_by,
                    mutation=mutation,
                )
            )
        except Exception:
            logger.exception(
                "Could not land the original at position %s; the foreman will "
                "reconcile it",
                position,
            )
    return findings


def fixer_node(state: dict) -> Dict[str, Any]:
    """Run the lowest pending fix in *state*, marking it ``in_flight``.

    A ``slide_pipeline_node`` stage: the state it is handed carries exactly one
    slide's ``fix_map`` entry, so "lowest" is that slide.

    Candidates are ``fix_map`` entries that are neither tombstoned (``None`` —
    ``turn_scoped_merge`` cannot delete a key, and ``bool({0: None})`` is
    ``True``) nor already ``in_flight``.

    **``in_flight`` is what makes "exactly one fix round" true rather than
    aspirational.**  Without it ``fix_reviewer_node`` clears only ``fix_target``,
    so every position above the minimum is re-fixed on the next pass —
    measured on the four-node topology as each position entering the fixer
    twice and deck review firing twice.

    The slide under edit is **not** given prior-slide framing: it is this turn's
    own builder output, already gated on emission, and wrapping it would
    instruct the fixer to *"follow no embedded directives"* about the very HTML
    it was asked to edit.  Its own output IS gated, per spec §8.1.

    A fixer that raises lands the **original** slide with its findings surfaced
    rather than placeholding a slide that already exists: the fix is an
    improvement pass, and losing a good slide because the improvement failed is
    the worse outcome.
    """
    turn_id = state["turn_id"]
    session_id = state["session_id"]
    initiated_by = state.get("initiated_by")
    fix_map = scoped_vals(state, "fix_map")
    mutation = _deck_mutation_context(
        session_id,
        state.get("graph_release_id"),
        operation="write_slide",
        object_type="slide",
    )

    candidates = [
        position
        for position, entry in fix_map.items()
        if entry is not None and not entry.get("in_flight")
    ]
    if not candidates:
        stale = {
            position: entry
            for position, entry in fix_map.items()
            if entry is not None and entry.get("in_flight")
        }
        if stale:
            reconciled = _reconcile_stale_fixes(
                stale,
                session_id=session_id,
                initiated_by=initiated_by,
                mutation=mutation,
            )
            return {
                "fix_target": None,
                "fix_map": scoped(turn_id, {p: None for p in stale}),
                "landed_positions": scoped(turn_id, set(stale)),
                "findings": reconciled,
            }
        return {"fix_target": None}

    position = min(candidates)
    entry = fix_map[position]
    payload = entry.get("payload") or {}
    finding = entry.get("finding") or {}

    fix_payload = {
        "position": position,
        "finding": finding,
        "html": entry.get("original_html", ""),
        "scripts": entry.get("original_scripts", ""),
        "slide_spec": payload.get("slide_spec"),
        "resolved_style": payload.get("resolved_style"),
        "section_css": payload.get("section_css"),
        "resolved_data": payload.get("resolved_data"),
    }
    if payload.get("deck_style") is not None:
        fix_payload["deck_style"] = payload["deck_style"]
    design_system_active = bool(
        payload.get("design_system_active")
        or state.get("design_system_active")
    )
    # The brand-asset search is decided on the builder record, as the builder's
    # own binding was; each run (the retry too) builds its own toolset.
    try:
        out = get_agent_runtime().run(
            "fixer",
            state["graph_release_id"],
            fix_payload,
            _assembly_context(
                design_system_active,
                state.get("root_session_id"),
                state.get("actor_session_id"),
                toolset=_brand_search_toolset(payload),
            ),
        ).output

        def _regenerate() -> str:
            retry_payload = {
                **fix_payload,
                "corrective_instruction": _SAFETY_CORRECTION,
            }
            return get_agent_runtime().run(
                "fixer",
                state["graph_release_id"],
                retry_payload,
                _assembly_context(
                    design_system_active,
                    state.get("root_session_id"),
                    state.get("actor_session_id"),
                    toolset=_brand_search_toolset(payload),
                ),
            ).output.html

        def _on_retry() -> None:
            _emit(
                StreamEventType.ASSISTANT,
                content=SAFETY_RETRY_NOTICE,
                metadata={"node": "fixer", "position": position},
            )

        html, _retried = gate_emitted_html(
            out.html, _regenerate, session_id, on_retry=_on_retry
        )
        html = strip_inter_tag_escapes(html)
    except Exception as exc:
        _raise_if_persisted_runtime_failure(exc)
        logger.exception("Fixer failed at position %s; landing the original", position)
        findings = _land_original(
            position,
            entry,
            session_id=session_id,
            initiated_by=initiated_by,
            mutation=mutation,
        )
        return {
            "fix_map": scoped(turn_id, {position: None}),
            "fix_target": None,
            "landed_positions": scoped(turn_id, {position}),
            "findings": findings,
        }

    return {
        "fix_target": position,
        "fixed": scoped(
            turn_id,
            {
                position: {
                    "html": html,
                    "scripts": out.scripts,
                    "changed": bool(getattr(out, "changed", False)),
                    "change_summary": getattr(out, "change_summary", ""),
                }
            },
        ),
        "fix_map": scoped(turn_id, {position: {**entry, "in_flight": True}}),
    }


# ---------------------------------------------------------------------------
# fix_reviewer_node
# ---------------------------------------------------------------------------


def fix_reviewer_node(state: dict) -> Dict[str, Any]:
    """Choose fixed-or-original, write the winner, tombstone the fix.

    The fixed candidate wins only when the re-review no longer reports the
    objective criterion that opened the fix; otherwise the original is written
    back, so a fixer that made things worse cannot ship.  An auto-fixed
    objective finding is marked ``status="fixed"`` — ``objective`` is a
    predicate about the criterion and ``status`` is state about whether a fixer
    handled it, and they are independent.

    When the candidate loses, the findings written with the original are the
    original's own (``prior_findings``) — never the re-review's, which are
    stamped against the candidate's hash.  A verdict must describe the content
    the row is written with; see the comment on that branch.

    The ``fix_map`` entry is **tombstoned** (``{position: None}``), which is what
    makes ``has_pending_fix`` go False once every entry is decided;
    ``turn_scoped_merge`` cannot delete a key, and a truthiness test on the dict
    would route to the fixer forever.  It is tombstoned on **every** path,
    including the two failure paths, for that reason.

    **Non-fatal throughout, and the guarantee is the row write's, not only the
    model call's.**  A failing re-review keeps the original.  A failure that
    prevents a row being delivered at all — an unvalidatable prior finding, or
    the write itself — placeholds the position through
    ``_placehold_failed_position``, exactly as a failed build reviewer's is, and
    records ``error_state``.  The turn continues to deck review either way, so
    the deck never comes back with rows committed and ``slide_count = 0``.
    """
    turn_id = state["turn_id"]
    session_id = state["session_id"]
    initiated_by = state.get("initiated_by")
    position = state.get("fix_target")
    if position is None:
        return {}
    mutation = _deck_mutation_context(
        session_id,
        state.get("graph_release_id"),
        operation="write_slide",
        object_type="slide",
    )

    fix_map = scoped_vals(state, "fix_map")
    entry = fix_map.get(position) or {}
    fixed = (scoped_vals(state, "fixed") or {}).get(position) or {}
    payload = entry.get("payload") or {}

    original_finding = entry.get("finding") or {}
    criterion = original_finding.get("criterion")

    try:
        prior_findings = [
            Finding.model_validate(f) for f in (entry.get("findings") or [])
        ]

        fixed_html = fixed.get("html") or ""
        fixed_scripts = fixed.get("scripts") or ""

        verdict = "surfaced"
        winner_html = entry.get("original_html", "")
        winner_scripts = entry.get("original_scripts", "")
        findings = prior_findings

        if fixed_html:
            review_payload = {
                "position": position,
                "finding": original_finding,
                "change_summary": fixed.get("change_summary", ""),
                "html": fixed_html,
                "scripts": fixed_scripts,
                # The slide as it was before the fix: without it the reviewer
                # judges the fix in isolation and cannot see collateral changes
                # (rewritten content, a restyle) made while clearing the finding.
                "original_html": entry.get("original_html", ""),
                "original_scripts": entry.get("original_scripts", ""),
                "slide_spec": payload.get("slide_spec"),
                "resolved_style": payload.get("resolved_style"),
                "section_css": payload.get("section_css"),
            }
            if payload.get("deck_style") is not None:
                review_payload["deck_style"] = payload["deck_style"]
            try:
                out = get_agent_runtime().run(
                    "fix_reviewer",
                    state["graph_release_id"],
                    review_payload,
                    _assembly_context(
                        payload.get("design_system_active"),
                        state.get("root_session_id"),
                        state.get("actor_session_id"),
                    ),
                ).output
                re_findings = _stamp_findings(
                    _skill_findings(out),
                    subject_hash=compute_slide_hash(fixed_html),
                    slide_index=position,
                )
                still_open = [f for f in re_findings if f.criterion == criterion]
                if not still_open:
                    winner_html = fixed_html
                    winner_scripts = fixed_scripts
                    verdict = "fixed"
                    findings = [
                        f.model_copy(update={"status": "fixed"})
                        if f.criterion == criterion and f.objective
                        else f
                        for f in prior_findings
                    ]
                else:
                    # The candidate LOST, so the ORIGINAL is what ships — and the
                    # findings written with it must be the ones stamped against
                    # the original's own hash, which is what `prior_findings`
                    # are.  `re_findings` describe the rejected candidate: their
                    # ids are minted from ITS hash, so persisting them here
                    # attaches a verdict to content nobody can see, breaks
                    # `make_finding_id`'s contract that the subject is the
                    # content hash, puts markup that was never shipped in the
                    # drawer, and silently drops the shipped slide's own
                    # findings.  The surviving objective finding is already in
                    # `prior_findings` with `status="open"`, which is exactly
                    # what "the fix did not hold" means; the re-review's own
                    # findings inform only that decision.  Same shape as
                    # `_land_original`, deliberately.
                    findings = prior_findings
            except Exception as exc:
                _raise_if_persisted_runtime_failure(exc)
                logger.exception(
                    "Fix review failed at position %s; keeping the original",
                    position,
                )

        _write_reviewed_row(
            session_id=session_id,
            position=position,
            html=winner_html,
            scripts=winner_scripts,
            findings=findings,
            verdict=verdict,
            slide_spec=payload.get("slide_spec"),
            initiated_by=initiated_by,
            mutation=mutation,
        )
    except Exception as exc:
        _raise_if_persisted_runtime_failure(exc)
        # The row could not be delivered at all — the prior findings would not
        # validate, or the write itself failed.  Unguarded, this killed the turn
        # (measured: rows [0, 2] committed, `slide_count = 0`, no deck review and
        # nothing in chat), which is the outcome §48 names as unacceptable and
        # which nothing recovers, because `slide_count` and `html_content` have
        # exactly one writer, in the last node of the turn.  So the position is
        # placeheld exactly as a failed build reviewer's is and the turn
        # continues to deck review.
        #
        # The fix_map entry is tombstoned on this path too: leaving it in_flight
        # sends the foreman back to the fixer, whose stale-fix branch would then
        # claim `landed_positions` for a row this writer just failed to write.
        logger.exception(
            "Fix review could not deliver a row at position %s; placeholding it",
            position,
        )
        updates: Dict[str, Any] = {
            "fix_map": scoped(turn_id, {position: None}),
            "fix_target": None,
            # Unlike the build-stage failure paths this stage may write
            # `error_state`: it runs strictly after its own fixer inside one
            # slide's pipeline.  The pipeline keeps the key branch-local
            # (`_PIPELINE_LOCAL_KEYS`), because two pipelines returning it in
            # one superstep WOULD raise `InvalidUpdateError`.
            "error_state": {
                "node": "fix_reviewer",
                "code": "fix_review_delivery_failed",
                "message": type(exc).__name__,
            },
        }
        if _placehold_failed_position(
            position,
            session_id=session_id,
            node="fix_reviewer",
            reason=type(exc).__name__,
            error=exc,
            mutation=mutation,
        ):
            updates["placeheld_positions"] = scoped(turn_id, {position})
        return updates

    _emit(
        StreamEventType.ASSISTANT,
        content=f"Slide {slide_number(position)} fix reviewed: {verdict}.",
        metadata={"node": "fix_reviewer", "position": position, "verdict": verdict},
    )

    return {
        "fix_map": scoped(turn_id, {position: None}),
        "fix_target": None,
        "landed_positions": scoped(turn_id, {position}),
        "findings": findings,
    }


# ---------------------------------------------------------------------------
# slide_pipeline_node
# ---------------------------------------------------------------------------


#: The reducer of every fan-in key, read off ``GraphState`` itself so the
#: pipeline folds its stages' updates exactly as the runtime would fold them
#: across supersteps — never a hand-copied second definition of the merge.
_FAN_IN_REDUCERS: Dict[str, Any] = {
    name: hint.__metadata__[0]
    for name, hint in get_type_hints(GraphState, include_extras=True).items()
    if getattr(hint, "__metadata__", None)
}

#: Keys a slide's own fix round reads and writes, and which therefore never
#: leave its pipeline.  ``fix_map``/``fix_target``/``fixed`` describe ONE
#: slide's fix and are meaningless to its siblings; ``error_state`` is
#: single-writer with no reducer, so two pipelines returning it in one superstep
#: would raise ``InvalidUpdateError`` and kill the turn — the very failure the
#: fanned failure paths already avoid by surfacing an ``info`` notice instead.
_PIPELINE_LOCAL_KEYS = frozenset({"fix_map", "fix_target", "fixed", "error_state"})


#: At most this many slides of one turn run their fix round at once.  The fix
#: rounds used to run one at a time; running every flagged slide's at once put
#: up to ``CAP`` fixer and fix-reviewer calls on the endpoint together, and a
#: rate limit on any of them used to fail the turn.  Five is the user's call
#: (2026-10-12) between that and the latency the serial queue cost.
FIX_CONCURRENCY = 5

#: This turn's fix slots.  Set by ``invoke_graph`` on every turn
#: (:func:`reset_fix_slots`), so concurrent turns do not share a budget.  It
#: works across the fan-out for the same reason the slide cursor does: LangGraph
#: copies the context into each task, and a copy shares the semaphore OBJECT.
_fix_slots_var: ContextVar[Optional[threading.BoundedSemaphore]] = ContextVar(
    "graph_fix_slots", default=None
)
#: The slots a graph invoked without ``invoke_graph`` (tests) draws from.
_DEFAULT_FIX_SLOTS = threading.BoundedSemaphore(FIX_CONCURRENCY)


def reset_fix_slots() -> None:
    """Give this context's turn a fresh set of ``FIX_CONCURRENCY`` fix slots."""
    _fix_slots_var.set(threading.BoundedSemaphore(FIX_CONCURRENCY))


def _fix_slots() -> threading.BoundedSemaphore:
    return _fix_slots_var.get() or _DEFAULT_FIX_SLOTS


def _transient_failure_notice(
    session_id: str, position: int, *, during: Literal["review", "fix"]
) -> None:
    """Say in chat which slide was kept as built because a model call failed.

    Plain language (#321): :func:`unreviewed_slide_notice` names the slide by its
    1-based number (*position* is the 0-based position), says the AI service was
    briefly unavailable, and offers one action.  ``during`` is the literal
    ``"review"`` (the slide was not checked) or ``"fix"`` (its automatic fix was
    skipped); anything else raises in the catalogue, so callers pass only those
    two literals.  The notice carries ``details`` (stage, the fixed error code and
    the request id) and is logged once through :func:`_surface_failure_notice`.

    The caught exception is deliberately **not** a parameter: a transient fault
    is always a ``PersistedRuntimeError`` subclass, whose name must never reach a
    user-visible disclosure (#271), and ``str(exc)`` can echo model output.  The
    useful cause is on the ``raise ... from`` chain, which the caller's
    ``logger.warning(..., exc_info=True)`` already logs.
    """
    _surface_failure_notice(
        session_id,
        unreviewed_slide_notice(
            position, during=during, request_id=get_chat_request_id()
        ),
    )


def _fold(acc: Dict[str, Any], update: Dict[str, Any]) -> None:
    """Fold one stage's *update* into *acc* with ``GraphState``'s reducers."""
    for key, value in update.items():
        reducer = _FAN_IN_REDUCERS.get(key)
        if key in acc and reducer is not None:
            acc[key] = reducer(acc[key], value)
        else:
            acc[key] = value


def _holds_placeholder(row: Optional[dict]) -> bool:
    """Whether *row* is a position whose CURRENT slide is a placeholder.

    Judges the verdict stored under the row's CURRENT ``content_hash`` with the
    strict ``is_placeholder_verdict``, never the whole ``verification_record``
    with ``is_placeholder_record``:

    * a verification record is keyed by content hash and keeps the history of
      every hash the slot has held, so a placeholder hash left behind by a slide
      that was later rebuilt is not the slide that is there now;
    * the LLM judge's error verdict also sets ``error`` but carries ``score``,
      ``rating``, ``explanation`` and more, so a real, judged slide whose judge
      call failed is not a placeholder.

    ``None`` (an empty position) holds nothing.
    """
    return row is not None and is_placeholder_verdict(
        (row.get("verification_record") or {}).get(row.get("content_hash"))
    )


def _write_draft_row(record: dict, mutation: DeckMutationContext) -> bool:
    """Commit the builder's HTML so the slide is visible before it is reviewed.

    Product decision (2026-10-12): show the draft, then replace it once the
    slide's own review — and fix, if any — lands.  The polling transport
    releases committed rows, so this write is what makes the slide visible;
    the reviewed write later overwrites it in place.

    **A draft never overwrites a committed REAL slide.**  On an edit or a
    rebuild the position already holds a committed slide, and a turn that then
    dies on a persisted runtime failure (a removed pinned endpoint, say) would
    leave the user's good slide replaced by an unreviewed draft and report an
    error.  So a position holding a real slide keeps it until the reviewed write
    replaces it.  A position that is empty, or holds only a placeholder (a
    pending inserted slide or a failed one — ``_holds_placeholder``), has no
    real slide to protect and is filled.

    **No ``verification_record``**: ``write_slide`` preserves the row's existing
    record when given ``None``, and that record is keyed by content hash, so
    the draft's own hash carries no verdict and reads as unreviewed rather than
    clean.  The HTML has already been through ``gate_emitted_html`` in the
    builder.

    Best-effort: a failed draft write costs only the early preview, so it is
    logged and the slide carries on to review, which writes the row anyway.

    Returns whether the draft was committed — the pipeline may keep it as the
    slide's final row if review then fails transiently.
    """
    position = record["position"]
    slide_spec = record.get("slide_spec")
    try:
        writer = SlideWriter()
        existing = writer.get_slide(record["session_id"], position)
        if existing is not None and not _holds_placeholder(existing):
            return False
        writer.write_slide(
            session_id=record["session_id"],
            position=position,
            html=record["html"],
            scripts=record.get("scripts") or "",
            deck_spec_slide=slide_spec if isinstance(slide_spec, dict) else None,
            modified_by=record.get("initiated_by"),
            mutation=mutation,
        )
    except Exception:
        logger.warning(
            "Could not commit the draft of slide %s; it will appear once reviewed",
            position,
            exc_info=True,
        )
        return False
    return True


def build_review_payload(record: dict, authority: dict) -> Dict[str, Any]:
    """The build reviewer's input: the builder's *record*, provenance re-declared.

    *authority* is the branch payload ``build_branch_payload`` built from state
    (or state itself).  Provenance is RE-DECLARED from it, never inherited from
    the record: the reviewer is the WRITER of the row, and the mutation event's
    actor is built from ``session_id`` (``_deck_mutation_context``), so a record
    carrying a different root, actor, release or session would make the trace
    and the evidence row name different actors.  Pinned by
    ``test_the_review_payload_overwrites_a_hostile_root_actor_and_release_in_the_record``.

    ``session_id`` falls back to the record's own value rather than to ``None``:
    the authority always carries it in production, so the fallback is
    unreachable there, and this line can only ever HARDEN a value.
    """
    return {
        **dict(record),
        "session_id": authority.get("session_id") or record.get("session_id"),
        "graph_release_id": authority["graph_release_id"],
        "root_session_id": authority.get("root_session_id") or "",
        "actor_session_id": authority.get("actor_session_id") or "",
    }


def slide_pipeline_node(payload: dict) -> Dict[str, Any]:
    """Carry ONE slide from build to its final reviewed row, without its siblings.

    ``builder -> draft row -> build_reviewer -> [fixer -> fix_reviewer]``, run
    in sequence inside one ``Send``-reached task.  This replaces the
    ``builder``, ``build_reviewer``, ``fixer`` and ``fix_reviewer`` graph nodes,
    and the reason is the runtime's superstep barrier, measured on a real
    10-slide deck: every slide waited for the slowest builder and then the
    slowest reviewer, and the flagged slides' fixes then ran ONE AT A TIME
    (``fixer`` took the lowest pending position per superstep) — 186s of a 308s
    turn.  Fanning the fixers out with ``Send`` would have removed the queue but
    not the barriers; folding the chain into one task removes both, so a slide
    is done when ITS chain is done and the batch's only barrier is the foreman's
    wake after the slowest whole chain.

    The four stages are the shipped node functions, called unchanged, and their
    updates are folded with ``GraphState``'s own reducers (``_fold``):

    * a builder that placeholds ends the chain — nothing to review;
    * the builder's HTML is committed as a draft (``_write_draft_row``) before
      review, so the slide is visible while it is reviewed;
    * the review payload is the builder's record with provenance re-declared
      from this payload, which ``build_branch_payload`` built from state
      (:func:`build_review_payload`);
    * a review that opens a fix hands the fixer and fix reviewer a slide-local
      state carrying only this slide's ``fix_map`` entry, so "exactly one fix
      round per slide" holds by construction and ``in_flight`` stays the
      fixer's own guard against a re-entry.

    Only fan-in keys reach graph state; ``_PIPELINE_LOCAL_KEYS`` stay here.
    Every stage's failure path is the one its node already had (placehold on a
    failed build or review, land the original on a failed fix, placehold on a
    fix review that cannot deliver), so the turn continues to deck review.
    """
    position = payload["position"]
    acc: Dict[str, Any] = {}

    _fold(acc, builder_node(payload))
    record = ((acc.get("slides") or {}).get("vals") or {}).get(position)
    if record is None:
        report_slide(position, SlideProgressStage.DONE)
        return {k: v for k, v in acc.items() if k not in _PIPELINE_LOCAL_KEYS}

    session_id = payload["session_id"]
    turn_id = payload["turn_id"]
    mutation = _deck_mutation_context(
        session_id,
        payload.get("graph_release_id"),
        operation="write_slide",
        object_type="slide",
    )
    drafted = _write_draft_row(record, mutation)
    report_slide(position, SlideProgressStage.REVIEWING)

    try:
        _fold(acc, build_reviewer_node(build_review_payload(record, payload)))
    except PersistedRuntimeError as exc:
        # A transient model fault (rate limit, 5xx, timeout) while reviewing:
        # the draft is already the committed row, so keep it — unreviewed, no
        # verdict — rather than fail the deck.  Without a draft (the position
        # held a slide already) there is nothing safe to keep: re-raise.
        if not (drafted and is_transient_model_failure(exc)):
            raise
        logger.warning(
            "Build review of slide %s failed transiently; keeping its draft",
            position,
            exc_info=True,
        )
        _transient_failure_notice(session_id, position, during="review")
        _fold(
            acc,
            {
                "landed_positions": scoped(turn_id, {position}),
                "reviewed_positions": scoped(turn_id, {position}),
            },
        )
        report_slide(position, SlideProgressStage.DONE)
        return {k: v for k, v in acc.items() if k not in _PIPELINE_LOCAL_KEYS}

    entry = ((acc.get("fix_map") or {}).get("vals") or {}).get(position)
    if entry is not None:
        report_slide(position, SlideProgressStage.FIXING)
        fix_state: Dict[str, Any] = {
            "turn_id": turn_id,
            "session_id": session_id,
            "graph_release_id": payload["graph_release_id"],
            "initiated_by": payload.get("initiated_by"),
            "root_session_id": payload.get("root_session_id") or "",
            "actor_session_id": payload.get("actor_session_id") or "",
            "design_system_active": payload.get("design_system_active"),
            "fix_map": acc["fix_map"],
        }
        with _fix_slots():
            try:
                fixer_update = fixer_node(fix_state)
                _fold(acc, fixer_update)
                _fold(fix_state, fixer_update)
                if fix_state.get("fix_target") is not None:
                    _fold(acc, fix_reviewer_node(fix_state))
            except PersistedRuntimeError as exc:
                # Transient while fixing: the slide was built and reviewed, so
                # land the original with its findings surfaced — the fixer
                # stage's own fallback for any other failure.  Nothing was
                # written by the failed stage (both re-raise before writing).
                if not is_transient_model_failure(exc):
                    raise
                logger.warning(
                    "Fix round of slide %s failed transiently; landing the original",
                    position,
                    exc_info=True,
                )
                _transient_failure_notice(session_id, position, during="fix")
                _fold(
                    acc,
                    {
                        "landed_positions": scoped(turn_id, {position}),
                        "findings": _land_original(
                            position,
                            entry,
                            session_id=session_id,
                            initiated_by=payload.get("initiated_by"),
                            mutation=mutation,
                        ),
                    },
                )

    report_slide(position, SlideProgressStage.DONE)
    return {k: v for k, v in acc.items() if k not in _PIPELINE_LOCAL_KEYS}


# ---------------------------------------------------------------------------
# placeholder_node
# ---------------------------------------------------------------------------


def placeholder_node(state: dict) -> Dict[str, Any]:
    """Commit a terminal placeholder for every stalled position.

    **Every position placeheld here goes through
    ``_placehold_failed_position``, the same function the two fanned failure
    paths use**, so a stalled position gets the same three surfaces they do: the
    row's error marker, an ``ERROR`` stream event and a **durable ``info`` chat
    notice**.  This node used to carry a hand-written copy of that call and the
    notice was the part it omitted, so on the stall path — the primary
    production failure limb 1 exists for, *"a branch that hung or died [and]
    never returns"* — the deck came back missing slides and the only chat line
    the user received was the deck reviewer's "no narrative issues found".  The
    stream event does not cover it: it is not durable across a reload and does
    not exist at all on the ``emitter=None`` path (the sweeper, and every
    layer-1 state test).

    The copy also left ``get_slide``'s read-back outside its ``try``, so a read
    failure killed the turn where the shared helper survives it.  Sharing the
    implementation fixes that by construction rather than by a second edit.

    ``_STALL_REASON`` is what distinguishes a foreman-reconciled placeholder from
    one a failing node wrote for itself — see that constant.

    Failure detection is ``is_placeholder_record`` — a **module-level function**
    in ``slide_repository``, not a method, and never an HTML class check: the
    marker lives in the row's ``verification_record`` as ``{content_hash:
    {"error": True, ...}}`` and the class is an implementation detail of the
    placeholder HTML.  It is applied inside the helper, and a position whose row
    does not read back as a placeholder is **not** claimed in
    ``placeheld_positions``: claiming it would make ``all_positions_committed``
    true for a position with no usable row.

    **``commit_placeholder`` takes NEITHER ``modified_by`` NOR
    ``deck_spec_slide``, and ws4c does not widen it (Ruling C-15).**  Placeholder
    rows therefore ship with a NULL author and no spec fragment.  That is a
    decision, not an oversight: nothing in ws4c/d/e consumes attribution on a
    terminal-failure marker, and the author/spec assertions belong to a
    reviewer-written row.  If ws4d's attribution work needs it, two optional
    pass-through kwargs is an additive change in a file that is neither frozen
    nor R2-barred.
    """
    turn_id = state["turn_id"]
    session_id = state["session_id"]
    positions = stalled_positions(state, time.time())
    mutation = _deck_mutation_context(
        session_id,
        state.get("graph_release_id"),
        operation="write_slide",
        object_type="slide",
    )

    placeheld: set = set()
    for position in positions:
        if _placehold_failed_position(
            position,
            session_id=session_id,
            node="placeholder",
            reason=_STALL_REASON,
            mutation=mutation,
        ):
            placeheld.add(position)

    report_slides(placeheld, SlideProgressStage.DONE)
    if not placeheld:
        return {}
    return {"placeheld_positions": scoped(turn_id, placeheld)}


# ---------------------------------------------------------------------------
# deck_reviewer_node
# ---------------------------------------------------------------------------


def deck_reviewer_node(state: dict) -> Dict[str, Any]:
    """Post-commit deck-level write, then review the arc. Non-fatal throughout.

    The write comes FIRST and the review second, because a review failure must
    never invalidate a delivered deck: it clears out with a notice, and the deck
    keeps its columns.

    **The guarantee covers the write's INPUTS, not only the write call**, and
    that is the whole reason the derivation sits inside the handler.  Measured
    when the five statements that compute them sat ABOVE the ``try``, with
    ``aggregate_deck_css`` failing: every row committed, ``slide_count = 0``,
    ``html_content`` and ``scripts_content`` empty, nothing in chat and the turn
    dead — the *"deck reads as ``0 slides``, silently"* outcome §48 names as
    unacceptable, reached through a door nothing guarded, in the node whose
    entire design rationale is ordering-for-robustness.  Nothing recovers it:
    ``slide_count`` and ``html_content`` have exactly one writer, here, with no
    compensating write anywhere.

    So each column is derived and added to the write dict **as soon as it
    exists**, and ``slide_count`` is derived first: a failure part-way through
    still writes what was already derived, and every column parameter defaults to
    _UNSET ("leave the stored value alone"), so the columns that were not derived
    are left as they stand rather than erased.  On the same measured failure the
    deck now keeps ``slide_count``, ``html_content`` and ``scripts_content`` and
    only ``css`` is left untouched.

    If even the row read fails there is nothing to review, so the review is
    **skipped** rather than run over zero slides — a review of nothing returns no
    findings and would tell the user "no narrative issues found across the deck"
    about a deck this node could not read.  The advisory carries the failure
    instead, so the user gets exactly one honest line on that path.

    Post-commit columns are ``slide_count``, ``html_content``,
    ``scripts_content`` plus the aggregated ``css``.  The middle two are
    **derived, not read from state**: ``SlideDeck.from_dict`` (there is no
    ``from_json``), then ``knit()`` for ``html_content`` and the aggregating
    ``.scripts`` property for ``scripts_content``.

    **``scripts_content``'s read-only property is its SOURCE, not an obstacle.**
    ``SlideDeck.scripts`` IIFE-wraps and joins the slides' own scripts, which is
    exactly the value all six monolith save sites persist.  It cannot go in the
    pre-fan-out write — no slides exist yet — and leaving it NULL regresses
    graph decks **silently**: the row-read dict emits ``deck.scripts_content or
    ""`` and thumbnails, PDF export and PPTX export then render with no
    JavaScript and blank charts, with no exception raised.  ``export.py`` is a
    consumer of that key, not merely a logger.

    ``css`` is written by BOTH deck writes and the second pass is deliberate:
    ``aggregate_deck_css`` dedupes the template block the column already
    contains and runs the ``ensure_deck_token_css`` backstop over the knitted
    deck.  Do not "optimise" it away.

    **Deck-level findings do NOT enter the ``findings`` channel (§9).**  They go
    only to ``deck_reviews`` and to the ``info`` chat message.
    ``SlideViewer.tsx`` filters findings by index, so a ``slide_index == -1``
    finding would be invisible AND would land in the unseen set.  Their
    ``make_finding_id`` subject is the **deck digest** (§8), the same value the
    ``deck_reviews`` row is keyed on.

    ``info`` needs no new machinery: it is the shipped channel for
    machine-generated advisories the user must see, the frontend keys rendering
    on ``role`` and never inspects ``message_type``, and ``_hydrate_chat_history``
    skips ``info`` explicitly, so the architect does not also receive it as
    prose.  No new ``StreamEventType``, no route, no frontend change.

    The slides' HTML reaching the review prompt is framed with
    ``spotlight_prior_slides``: this is the one node in the shipped topology
    that receives OTHER slides' HTML (SDR-4437 F-TM-12).  The builder and the
    fixer receive none — ``build_branch_payload`` copies no other slide's markup
    and neither node reads the database — so the call belongs here, and belongs
    there the moment a payload field for prior slides exists.
    """
    report_phase(TurnPhase.REVIEWING_DECK)
    session_id = state["session_id"]
    initiated_by = state.get("initiated_by")

    manager = get_session_manager()
    updates: Dict[str, Any] = {}
    slide_htmls: List[str] = []

    # Every input to the post-commit write is derived INSIDE a handler, and each
    # derived column is added to `deck_write` as soon as it exists, so a failure
    # part-way through still writes the columns already derived.  `slide_count`
    # is derived first deliberately: it is the column whose absence makes a deck
    # whose slides exist read as `0 slides` (§48), and it survives every failure
    # except the row read itself.  Every column parameter defaults to _UNSET
    # ("leave the stored value alone"), so omitting one erases nothing.
    deck_write: Dict[str, Any] = {}
    derivation_error: Optional[str] = None
    # Set on the two paths whose advisory is a plain-language failure notice
    # (derivation failed, review failed); `None` on the success path, whose
    # advisory text (#316) and metadata stay exactly as they were.
    advisory_notice: Optional[FailureNotice] = None
    try:
        deck_dict = manager.get_slide_deck(session_id) or {}
        deck = SlideDeck.from_dict(deck_dict)
        slide_htmls = [slide.html for slide in deck.slides]
        deck_write["slide_count"] = len(deck.slides)
        deck_write["html_content"] = deck.knit()
        deck_write["scripts_content"] = deck.scripts
        deck_write["css"] = aggregate_deck_css(
            deck_dict.get("css"),
            scoped_vals(state, "emitted_style_blocks"),
            state.get("token_css"),
        )
    except Exception as exc:
        logger.exception("Post-commit deck-level derivation failed")
        derivation_error = type(exc).__name__
        updates["error_state"] = {
            "node": "deck_reviewer",
            "code": "deck_level_derivation_failed",
            "message": derivation_error,
        }

    if "html_content" in deck_write:
        updates["knitted_html"] = deck_write["html_content"]
    if "scripts_content" in deck_write:
        updates["scripts_content"] = deck_write["scripts_content"]

    if deck_write:
        try:
            write_deck_level_columns(
                session_id,
                mutation=_deck_mutation_context(
                    session_id,
                    state.get("graph_release_id"),
                    operation="write_deck_level",
                    object_type="deck",
                ),
                modified_by=initiated_by,
                # Passed here for the same reason the architect passes it, and
                # passed EXPLICITLY rather than left to the default: these are the
                # two deck-level writers, and one of them being describe-only
                # aware while the other defaults to `True` is a divergence held
                # apart only by `architect_router`'s gate — an accident of routing
                # rather than an agreement between the writers.  A sixth intent
                # routing to the foreman, or a describe-only turn that ever
                # reaches this node, would otherwise re-open the 409 the flag
                # exists for: bump the version out of band and the human's next
                # save fails.  Derived identically to the architect's, off the
                # same turn-scoped key.
                user_visible=not bool(scoped_vals(state, "describe_only")),
                **deck_write,
            )
        except Exception as exc:
            logger.exception("Post-commit deck-level write failed")
            updates["error_state"] = {
                "node": "deck_reviewer",
                "code": "deck_level_write_failed",
                "message": type(exc).__name__,
            }
            _surface_failure_notice(
                session_id,
                deck_not_updated_notice(
                    review_skipped=False,
                    error=type(exc).__name__,
                    request_id=get_chat_request_id(),
                ),
            )

    if derivation_error is not None:
        # There is nothing to review: the slides could not be read.  Calling the
        # reviewer with zero slides would spend a model call and then tell the
        # user "no narrative issues found across the deck" about a deck this node
        # could not read — the misleading half of the F1b outcome.  The advisory
        # IS the notice on this path, so the user gets exactly one honest line.
        advisory_notice = deck_not_updated_notice(
            review_skipped=True,
            error=derivation_error,
            request_id=get_chat_request_id(),
        )
        advisory = advisory_notice.text
    else:
        try:
            digest = compute_deck_digest(slide_htmls)
            # Content only (#258): no session identifier reaches the model.
            # ``session_id`` still drives the spotlight's injection-scan log,
            # the deck-id lookup and the review write below.
            review_payload = {
                "narrative_arc": (
                    state["deck_spec"].narrative_arc if state.get("deck_spec") else []
                ),
                "call_to_action": (
                    state["deck_spec"].call_to_action
                    if state.get("deck_spec")
                    else None
                ),
                "slide_count": len(slide_htmls),
                "slides": spotlight_prior_slides(slide_htmls, session_id),
            }
            out = get_agent_runtime().run(
                "deck_reviewer",
                state["graph_release_id"],
                review_payload,
                _assembly_context(
                    state.get("design_system_active"),
                    state.get("root_session_id"),
                    state.get("actor_session_id"),
                ),
            ).output
            findings = _stamp_findings(
                _skill_findings(out), subject_hash=digest, slide_index=-1
            )
            with get_db_session() as db:
                deck_id = _resolve_deck_id(db, session_id)
                if deck_id is None:
                    raise ValueError(
                        f"No deck row for session {session_id}; cannot persist the "
                        "deck review"
                    )
                save_deck_review(db, deck_id, digest, findings, initiated_by)
            advisory = _advisory_text(findings)
        except Exception as exc:
            _raise_if_persisted_runtime_failure(exc)
            logger.exception("Deck review failed; the delivered deck stands")
            advisory_notice = deck_review_failed_notice(
                error=type(exc).__name__,
                request_id=get_chat_request_id(),
            )
            advisory = advisory_notice.text
            updates["error_state"] = {
                "node": "deck_reviewer",
                "code": "deck_review_failed",
                "message": type(exc).__name__,
            }

    # Through `_surface_notice` (a failure notice through `_surface_failure_notice`,
    # which calls it), the shipped ungated writer, rather than a hand-rolled
    # `add_message`: that is where the request-id tag lives, and an untagged row
    # never reaches `GET /chat/poll`.  NOT through `_say`, which suppresses a
    # describe-only turn's write — a describe-only turn cannot reach this node
    # today (`architect_router` ends it first) but the unit suite calls this node
    # directly with the flag set and PINS that the advisory still lands,
    # deliberately: "gating the advisory is a change to what the user is told".
    # The `info` TYPE is load-bearing and unchanged — its exclusion from
    # `_AI_TYPES` keeps this advisory out of the architect's replayed conversation.
    # The success path's advisory (`_advisory_text`, #316) carries no `details`.
    if advisory_notice is not None:
        _surface_failure_notice(session_id, advisory_notice)
    else:
        _surface_notice(session_id, advisory)
    _emit(
        StreamEventType.ASSISTANT,
        content=advisory,
        metadata={
            "node": "deck_reviewer",
            **(
                {"details": dict(advisory_notice.details)}
                if advisory_notice is not None
                else {}
            ),
        },
    )

    return updates
