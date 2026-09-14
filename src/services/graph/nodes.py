"""The nine nodes of the deck-generation graph.

``architect``, ``data_analyst``, ``foreman``, ``builder``, ``build_reviewer``,
``fixer``, ``fix_reviewer``, ``placeholder``, ``deck_reviewer``.  Nine — there is
no tenth, and there is no ``reviewer_router`` (``build_reviewer -> foreman`` is a
static edge; see ``routers.py``).

Two node kinds, and the difference decides everything
-----------------------------------------------------
*Edge-reached* nodes (``architect``, ``data_analyst``, ``foreman``, ``fixer``,
``fix_reviewer``, ``placeholder``, ``deck_reviewer``) receive ``GraphState``.

*``Send``-reached* nodes (``builder``, ``build_reviewer``) receive **only their
payload** — measured: the node saw ``['batch', 'position']`` and no state key at
all.  That is why :func:`build_branch_payload` pre-copies everything a branch
needs, and why the builder carries its payload forward in ``slides[position]``
so the re-fan can rebuild the reviewer's input from it.

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
import time
from typing import Any, Dict, List, Optional

from src.api.schemas.agent_config import AgentConfig, resolve_agent_config
from src.api.schemas.streaming import StreamEvent, StreamEventType
from src.api.services.deck_level_writer import read_deck_spec, write_deck_level_columns
from src.api.services.session_manager import get_session_manager
from src.api.services.slide_repository import SlideWriter, is_placeholder_record
from src.core.database import get_db_session
from src.core.skills import call_skill
from src.database.models.session import SessionSlideDeck, UserSession
from src.domain.deck_spec import DeckSpec, DesignContractRef, SlideSpec
from src.domain.finding import (
    CRITERIA,
    Finding,
    build_verification_record,
    make_finding_id,
)
from src.domain.slide_deck import SlideDeck
from src.services.agent import SAFETY_RETRY_NOTICE
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
    get_event_emitter,
    get_slide_cursor,
)
from src.services.graph.state import has_pending_fix, scoped, scoped_vals
from src.services.template_sections import (
    extract_section,
    resolve_template_bytes,
    section_inventory,
)
from src.utils.graph_safety import gate_emitted_html, spotlight_prior_slides
from src.utils.slide_hash import compute_slide_hash

logger = logging.getLogger(__name__)

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


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _emit(
    event_type: StreamEventType,
    *,
    content: Optional[str] = None,
    error: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Queue one event, or do nothing when no emitter is installed.

    Uses only shipped ``StreamEventType`` members: ws4c adds no event type, no
    route and no frontend change.
    """
    emit_event(
        StreamEvent(
            type=event_type, content=content, error=error, metadata=metadata
        )
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

    released: List[int] = []
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
        emit_slide_ready(
            position=position,
            html=row["html"] or "",
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


def _concat_css(token_css: str, style_block: str) -> str:
    """``token_css`` + the template's ``<style>`` block, concatenated (§17).

    Both halves are CSS **text**; neither is ``<style>``-wrapped.  A wrapped
    block reaching ``aggregate_deck_css`` parses to error nodes and is dropped
    SILENTLY — no exception, no log — which is why the unwrapping is
    ``resolve_template_bytes``' contract and not attempted here.
    """
    return "\n\n".join(part for part in (token_css, style_block) if part)


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
    ``style_block``, ``deterministic_css``, ``section_inventory``.
    """
    from src.services.agent_resolution import resolve_style_source

    style = resolve_style_source(_agent_config_for(contract))

    layout_html = ""
    style_block = ""
    token_css = ""
    if (
        contract is not None
        and contract.design_system_id is not None
        and contract.template_id is not None
    ):
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
    return turns


def _committed_slide_htmls(session_id: str) -> List[str]:
    """Every committed slide's HTML, in deck order (``[]`` when there are none)."""
    try:
        rows = SlideWriter().list_slides_in_position_order(session_id)
    except Exception:
        logger.debug("No committed slides for session", exc_info=True)
        return []
    return [row.get("html") or "" for row in rows]


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
    )
    return content_hash


def _surface_notice(session_id: str, message: str) -> None:
    """Persist a machine-generated advisory as an ``info`` chat message.

    The shipped channel for advisories the user must see.  Used by every
    non-fatal failure path a **fanned** node can take, because those paths
    cannot write ``error_state``: it is single-writer with no reducer, and two
    branches failing in the same superstep then raise — measured on the
    installed langgraph::

        InvalidUpdateError: At key 'error_state': Can receive only one value per
        step. Use an Annotated key to handle multiple values.

    which would kill the turn, exactly the failure the handler exists to
    prevent.  A chat message is per-row and concurrency-safe, and unlike a
    stream event it survives ``emitter=None`` (the sweeper path).
    """
    try:
        get_session_manager().add_message(
            session_id, role="assistant", content=message, message_type="info"
        )
    except Exception:
        logger.warning("Could not surface a failure notice", exc_info=True)


def _placehold_failed_position(
    position: int,
    *,
    session_id: str,
    node: str,
    reason: str,
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
    a durable ``info`` chat line.  All four of them — the two fanned nodes
    (``builder``, ``build_reviewer``), ``fix_reviewer``'s undeliverable-row path,
    and ``placeholder_node``'s stall path.  There is no flag to make one quieter
    than another, deliberately: the emitter is optional and is ``None`` on the
    sweeper path (and in every layer-1 state test), so an event-only surface
    would let a failed position leave a silently missing slide.  The chat notice
    is the only surface that survives ``emitter=None``, and ``error_state`` is
    unavailable to the two FANNED paths — it is single-writer with no reducer,
    and two branches failing in one superstep would raise
    ``InvalidUpdateError`` and kill the turn (measured).  The two edge-reached
    callers may record it and ``fix_reviewer`` does; that is the only difference
    between the callers, and it is a difference in what the *caller* returns,
    never in what this function surfaces.

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

    ``commit_placeholder`` takes neither ``modified_by`` nor ``deck_spec_slide``
    (Ruling C-15), so these rows ship with a NULL author here too.
    """
    _emit(
        StreamEventType.ERROR,
        error=f"Slide {position} could not be generated.",
        metadata={"node": node, "position": position},
    )
    writer = SlideWriter()
    try:
        writer.commit_placeholder(session_id, position, error_message=reason)
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
    _surface_notice(
        session_id,
        f"Slide {position} could not be generated and has been left as a "
        f"placeholder ({node}: {reason}). The rest of the deck is unaffected.",
    )
    return True


def _advisory_text(findings: List[Finding]) -> str:
    """Compose the deck-review advisory from findings alone (§5, Ruling C-3).

    ``DeckReviewOutput`` declares ``findings`` and nothing else — no verdict
    field and no prose field — so the message is composed here rather than read
    off the model output.  An empty list gets an explicit "no issues" line: a
    silent absence is indistinguishable from a review that never ran.
    """
    if not findings:
        return (
            "Deck review complete: no narrative issues found across the deck."
        )
    lines = [
        f"Deck review found {len(findings)} narrative "
        f"{'issue' if len(findings) == 1 else 'issues'}:"
    ]
    for finding in findings:
        lines.append(f"- {finding.criterion}: {finding.message}")
    return "\n".join(lines)


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

    return {
        "session_id": state["session_id"],
        "turn_id": state["turn_id"],
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


# ---------------------------------------------------------------------------
# architect_node
# ---------------------------------------------------------------------------


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
    ``proposed_design_contract``.
    """
    session_id = state["session_id"]
    turn_id = state["turn_id"]
    initiated_by = state.get("initiated_by")

    committed_htmls = _committed_slide_htmls(session_id)
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
                # in the prompt as its repr.
                prior_review = {
                    "digest": stored.get("digest"),
                    "author": stored.get("author"),
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

    payload = {
        "session_id": session_id,
        "conversation": _conversation(session_id),
        "message": state.get("architect_message"),
        "current_deck_spec": persisted_spec_dict,
        "committed_slide_count": len(committed_htmls),
        "previous_deck_review": prior_review,
        "available_design_contract": (
            inbound_contract.model_dump() if inbound_contract else None
        ),
        "template_sections": brand["section_inventory"],
        "resolved_style": brand["resolved_style"],
    }

    out = call_skill("architect", payload, brand["design_system_active"])
    intent = out.intent

    updates: Dict[str, Any] = {
        "architect_intent": intent,
        "architect_message": out.message,
        "target_positions": None,
        "fix_target": None,
        "error_state": None,
    }
    _emit(StreamEventType.ASSISTANT, content=out.message,
          metadata={"node": "architect", "intent": intent})

    if intent == "ask_data":
        # GraphState declares no analyst channel and undeclared keys are
        # silently dropped (§11), so the request travels in architect_message —
        # the same key the analyst answers through.
        updates["architect_message"] = "\n\n".join(
            [out.message, "DATA REQUEST: " + out.data_request.model_dump_json()]
        )
        return updates

    if intent not in ("build", "edit"):
        # discuss and confirm_design_contract both END the turn. A confirmation
        # WAITS for the user, so nothing may restyle before they answer, and the
        # proposal stays in proposed_design_contract — never in deck_spec (§M1).
        return updates

    spec = out.deck_spec if out.deck_spec is not None else prior_spec
    if spec is None:
        # An edit with nothing to edit. Degrade to a discussion turn rather than
        # routing to a foreman that would cover no positions and reach deck
        # review on an unbuilt deck.
        updates["architect_intent"] = "discuss"
        updates["architect_message"] = (
            "I could not find a deck specification to edit for this session. "
            "Tell me what you would like to build and I will draft one."
        )
        updates["error_state"] = {
            "node": "architect",
            "code": "edit_without_spec",
            "message": "intent='edit' with no committed deck_spec",
        }
        return updates

    if _contract_ids(spec.design_contract) != _contract_ids(inbound_contract):
        brand = _resolve_brand(spec.design_contract)

    if intent == "edit":
        updates["target_positions"] = list(out.target_positions)

    external_scripts = [SlideDeck.CHART_JS_URL]
    head_meta = json.dumps(_DEFAULT_HEAD_META)

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
            # ONE element on a pinned deck, none on an unpinned one, and CSS
            # TEXT rather than <style>-wrapped markup: a wrapped block is
            # dropped SILENTLY by the aggregator (§17).
            "emitted_style_blocks": scoped(
                turn_id, [brand["style_block"]] if brand["style_block"] else []
            ),
        }
    )

    # ---- the pre-fan-out deck-level write (§H1) -------------------------
    # Five columns: title, external_scripts, head_meta, deck_spec and css.
    # external_scripts and head_meta are resolved DETERMINISTICALLY — the
    # Chart.js CDN default and the deck's <meta> set are known before any
    # builder runs, and ArchitectOutput declares neither field. The brand bytes
    # in css come from resolve_template_bytes, never from model output.
    #
    # css is passed only when it is non-empty. Every column parameter defaults
    # to _UNSET ("leave the stored value alone") and an explicit value
    # overwrites, so passing "" on an unpinned deck would ERASE an existing
    # deck's stylesheet, and the post-commit aggregate_deck_css would then
    # preserve the erasure. Omitting it is the writer's own documented way to
    # say "this turn resolved no deterministic CSS".
    # A describe-only turn (ws4d's arc-review sweeper) is not a change the client
    # should see. It re-describes the narrative and changes no slide, but
    # deck.version is what the WYSIWYG client sends back as expected_version, and
    # a bump turns the human's very next save into a 409 — on exactly the deck
    # whose editor is mid-session, because the sweeper runs BECAUSE they are
    # editing. deck.updated_at, which the client renders as modified_at, is
    # suppressed by the same flag: leaving it bumped beside an unchanged version
    # token would show "modified just now" against a deck whose lock says nothing
    # changed, and that half-state is worse than either choice made consistently.
    describe_only = bool(scoped_vals(state, "describe_only"))

    deck_write: Dict[str, Any] = {
        "title": spec.title,
        "external_scripts": external_scripts,
        "head_meta": head_meta,
        "deck_spec": spec.to_json(),
        "modified_by": initiated_by,
        "user_visible": not describe_only,
    }
    if brand["deterministic_css"]:
        deck_write["css"] = brand["deterministic_css"]
    try:
        write_deck_level_columns(session_id, **deck_write)
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


def data_analyst_node(state: dict) -> Dict[str, Any]:
    """Fetch what the architect asked for and answer through ``architect_message``.

    ``GraphState`` declares **no analyst key** and the runtime silently drops
    undeclared keys, so both the request and the answer travel on
    ``architect_message`` (§11, Ruling C-7); the edge back to the architect is
    static.  That key is written by two nodes and still needs no reducer,
    because the architect and the analyst never run in the same superstep.

    Returns exactly one of three outcome shapes, all as prose on that key:
    ``success`` -> the synthesis, ``missing_data`` -> the gap, ``no_tool`` ->
    the reason plus the tools tried.  Reads only ``AnalystOutput``'s declared
    fields: ``outcome``, ``synthesis``, ``sources``, ``gap``, ``tried_tools``,
    ``reason``.

    **``ResolvedData.figures`` stays empty, and that is recorded rather than
    worked around (§12).**  ``AnalystOutput`` declares no field that maps to
    ``ResolvedFigure(key, value, source)``, so a graph-built spec's
    ``resolved_data.figures`` is always ``[]`` — which makes
    ``source_contradiction`` ("only assertable against ``resolved_data``")
    unreachable on the graph path.  Closing it needs a declared field on
    ``AnalystOutput``, an escalation to ws4b, not a mapping invented here.
    """
    session_id = state["session_id"]
    request = state.get("architect_message") or ""

    payload = {
        "session_id": session_id,
        "data_request": request,
        "deck_purpose": (
            state["deck_spec"].purpose if state.get("deck_spec") else None
        ),
    }
    out = call_skill(
        "data_analyst", payload, bool(state.get("design_system_active"))
    )

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

    _emit(
        StreamEventType.ASSISTANT,
        content=message,
        metadata={"node": "data_analyst", "outcome": out.outcome},
    )

    return {"architect_message": message}


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

    **The decision order is ``fix -> dispatch -> stall -> all-committed ->
    END``** (Ruling C-2), not the plan's ``fix -> stall -> dispatch``.  Those two
    are mutually unsatisfiable: after the superstep barrier, a position left
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
      dispatched** are stamped: a wake whose decision is ``"fixer"`` or
      ``"placeholder"`` stamps nothing, or the next wake reads positions that
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
    #    the others: the pending-fix limb returns immediately, and the
    #    all-committed limb is the wake that carries the LAST slide of the deck.
    _release_slides(state)

    # 1. A pending fix preempts dispatch entirely. A 31-slide deck stops
    #    dispatching new builders until every fix completes; fix rounds
    #    serialise one position per superstep.
    if has_pending_fix(state):
        return {"foreman_wakes": scoped(turn_id, [[]])}

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
    _emit(StreamEventType.ERROR, error=message, metadata={"node": "foreman"})
    try:
        get_session_manager().add_message(
            state["session_id"],
            role="assistant",
            content=message,
            message_type="info",
        )
    except Exception:
        logger.warning("Could not surface the unreconciled-END notice", exc_info=True)
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


def builder_node(payload: dict) -> Dict[str, Any]:
    """Author one slide's body HTML from its pre-copied payload.

    Reached by ``Send``, so this receives **only the payload** — no state key is
    visible.  ``BuilderOutput`` rejects any ``<style>`` element (deck-level CSS
    has a single writer), so the node emits body HTML only.

    The emitted HTML goes through ``gate_emitted_html`` (AISEC-248) before it
    reaches state: spec §8.1 gates reviewer INPUT as well as fixer output, and
    the gate's ``regenerate`` argument is a zero-arg callable, so the corrective
    instruction travels in the payload the closure captures.

    The whole payload is carried forward in ``slides[position]`` so the re-fan
    router can rebuild the reviewer's input from it — the reviewer is
    ``Send``-reached too and can see nothing else.

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

    skill_payload = dict(payload)

    try:
        out = call_skill("builder", skill_payload, design_system_active)

        def _regenerate() -> str:
            retry_payload = {
                **skill_payload,
                "corrective_instruction": _SAFETY_CORRECTION,
            }
            return call_skill(
                "builder", retry_payload, design_system_active
            ).html

        def _on_retry() -> None:
            _emit(
                StreamEventType.ASSISTANT,
                content=SAFETY_RETRY_NOTICE,
                metadata={"node": "builder", "position": position},
            )

        html, _retried = gate_emitted_html(
            out.html, _regenerate, session_id, on_retry=_on_retry
        )
    except Exception as exc:
        logger.exception("Builder failed at position %s", position)
        if not _placehold_failed_position(
            position,
            session_id=session_id,
            node="builder",
            reason=type(exc).__name__,
        ):
            return {}
        return {"placeheld_positions": scoped(turn_id, {position})}

    record = {**skill_payload, "html": html, "scripts": out.scripts}
    return {"slides": scoped(turn_id, {position: record})}


# ---------------------------------------------------------------------------
# build_reviewer_node
# ---------------------------------------------------------------------------


def build_reviewer_node(payload: dict) -> Dict[str, Any]:
    """Review one built slide; either land it or open a fix.

    Reached by the re-fan ``Send``, with the payload the builder carried in
    ``slides[position]``.

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

    try:
        content_hash = compute_slide_hash(html)
        review_payload = {
            "position": position,
            "slide_spec": payload.get("slide_spec"),
            "resolved_style": payload.get("resolved_style"),
            "section_css": payload.get("section_css"),
            "resolved_data": payload.get("resolved_data"),
            "html": html,
            "scripts": scripts,
        }
        out = call_skill(
            "build_reviewer",
            review_payload,
            bool(payload.get("design_system_active")),
        )

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
            )
            _emit(
                StreamEventType.ASSISTANT,
                content=f"Slide {position} reviewed: {verdict}.",
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
        logger.exception("Build review failed at position %s", position)
        if not _placehold_failed_position(
            position,
            session_id=session_id,
            node="build_reviewer",
            reason=type(exc).__name__,
        ):
            return {}
        # reviewed_positions too: the position is committed as a placeholder, so
        # a resumed re-fan must not review it again.
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
    )
    return findings


def _reconcile_stale_fixes(
    stale: Dict[int, dict],
    *,
    session_id: str,
    initiated_by: Optional[str],
) -> List[Finding]:
    """Land the originals for fixes left ``in_flight`` by a dead process.

    Returns the findings it persisted; the CALLER assembles the state update, so
    every state key a node writes stays inside that node's body where the
    exhaustiveness scan can see it.  A helper returning a state dict is
    invisible to that scan.

    Reached only on a resumed checkpoint: within a turn the fixer and the fix
    reviewer are strictly sequential (``fixer -> fix_reviewer -> foreman``), and
    the fix reviewer tombstones its entry on every path including its own
    exception — so an ``in_flight`` entry the fixer can still see is stale by
    construction.

    Without this the turn LIVELOCKS: ``has_pending_fix`` stays True (an
    ``in_flight`` entry is not a tombstone), so the foreman routes to the fixer,
    the fixer finds no fresh candidate, ``fixer_router`` returns to the foreman,
    and the pair bounce until ``GraphRecursionError`` at 10007 supersteps.
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
    """Dispatch the lowest pending fix, marking it ``in_flight``.

    Candidates are ``fix_map`` entries that are neither tombstoned (``None`` —
    ``turn_scoped_merge`` cannot delete a key, and ``bool({0: None})`` is
    ``True``) nor already ``in_flight``.

    **``in_flight`` is what makes "exactly one fix round" true rather than
    aspirational.**  Without it ``fix_reviewer_node`` clears only ``fix_target``,
    so every position above the minimum is re-fixed on the next foreman pass —
    measured as each position entering the fixer twice and deck review firing
    twice.

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
                stale, session_id=session_id, initiated_by=initiated_by
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
    }
    design_system_active = bool(
        payload.get("design_system_active")
        or state.get("design_system_active")
    )

    try:
        out = call_skill("fixer", fix_payload, design_system_active)

        def _regenerate() -> str:
            retry_payload = {
                **fix_payload,
                "corrective_instruction": _SAFETY_CORRECTION,
            }
            return call_skill("fixer", retry_payload, design_system_active).html

        def _on_retry() -> None:
            _emit(
                StreamEventType.ASSISTANT,
                content=SAFETY_RETRY_NOTICE,
                metadata={"node": "fixer", "position": position},
            )

        html, _retried = gate_emitted_html(
            out.html, _regenerate, session_id, on_retry=_on_retry
        )
    except Exception:
        logger.exception("Fixer failed at position %s; landing the original", position)
        findings = _land_original(
            position, entry, session_id=session_id, initiated_by=initiated_by
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
                "slide_spec": payload.get("slide_spec"),
                "resolved_style": payload.get("resolved_style"),
                "section_css": payload.get("section_css"),
            }
            try:
                out = call_skill(
                    "fix_reviewer",
                    review_payload,
                    bool(payload.get("design_system_active")),
                )
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
            except Exception:
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
        )
    except Exception as exc:
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
            # Unlike the two FANNED failure paths this node may write
            # `error_state`: `fixer -> fix_reviewer -> foreman` is strictly
            # sequential, so no second writer can share its superstep and
            # `InvalidUpdateError` is unreachable here.
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
        ):
            updates["placeheld_positions"] = scoped(turn_id, {position})
        return updates

    _emit(
        StreamEventType.ASSISTANT,
        content=f"Slide {position} fix reviewed: {verdict}.",
        metadata={"node": "fix_reviewer", "position": position, "verdict": verdict},
    )

    return {
        "fix_map": scoped(turn_id, {position: None}),
        "fix_target": None,
        "landed_positions": scoped(turn_id, {position}),
        "findings": findings,
    }


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

    placeheld: set = set()
    for position in positions:
        if _placehold_failed_position(
            position,
            session_id=session_id,
            node="placeholder",
            reason=_STALL_REASON,
        ):
            placeheld.add(position)

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
                session_id, modified_by=initiated_by, **deck_write
            )
        except Exception as exc:
            logger.exception("Post-commit deck-level write failed")
            updates["error_state"] = {
                "node": "deck_reviewer",
                "code": "deck_level_write_failed",
                "message": type(exc).__name__,
            }
            _surface_notice(
                session_id,
                "The deck's slides were saved, but the deck's own record of them "
                "could not be updated this turn "
                f"(deck_reviewer: {type(exc).__name__}).",
            )

    if derivation_error is not None:
        # There is nothing to review: the slides could not be read.  Calling the
        # reviewer with zero slides would spend a model call and then tell the
        # user "no narrative issues found across the deck" about a deck this node
        # could not read — the misleading half of the F1b outcome.  The advisory
        # IS the notice on this path, so the user gets exactly one honest line.
        advisory = (
            "Your slides were saved, but the deck's own record of them could not "
            "be updated this turn, so the deck-level review was skipped "
            f"(deck_reviewer: {derivation_error})."
        )
    else:
        try:
            digest = compute_deck_digest(slide_htmls)
            review_payload = {
                "session_id": session_id,
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
            out = call_skill(
                "deck_reviewer",
                review_payload,
                bool(state.get("design_system_active")),
            )
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
            logger.exception("Deck review failed; the delivered deck stands")
            advisory = (
                "The deck is complete, but the deck-level review could not be "
                "completed this turn."
            )
            updates["error_state"] = {
                "node": "deck_reviewer",
                "code": "deck_review_failed",
                "message": type(exc).__name__,
            }

    try:
        manager.add_message(
            session_id,
            role="assistant",
            content=advisory,
            message_type="info",
        )
    except Exception:
        logger.warning("Could not persist the deck-review advisory", exc_info=True)
    _emit(
        StreamEventType.ASSISTANT,
        content=advisory,
        metadata={"node": "deck_reviewer"},
    )

    return updates
