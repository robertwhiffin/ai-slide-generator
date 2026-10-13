"""Tour demo deck endpoints.

The tour replays one multi-agent ("graph") generation turn as a forward-only
sequence of idempotent stages, so the user watches the deck being planned,
built, reviewed and edited without any model call.

Phase 1 -- POST /api/tour/demo-deck
  Creates a session holding only the user's prompt (stage ``prompt``).

Stages -- POST /api/tour/demo-deck/{session_id}/stages/{stage}
  ``plan``   architect reply.
  ``build``  foreman line, the three slides, the deck spec, per-slide build
             review lines, and a seeded verification record (with the scripted
             finding) for every slide.
  ``review`` deck reviewer advisory.
  ``edit``   a follow-up user request, the architect reply, one rewritten slide
             and its brief, and verification re-seeded for every slide.

Every chat row is tagged ``metadata.tour_stage``; re-running a stage is a no-op
and a stage whose predecessor has not run is rejected (409) before any write.
"""

import asyncio
import copy
import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from src.api.routes._authz import _check_deck_permission_for_session
from src.api.services.deck_level_writer import write_deck_level_columns
from src.api.services.session_manager import get_session_manager
from src.domain.finding import Finding, build_verification_record, make_finding_id
from src.core.user_context import get_current_user
from src.database.models.profile_contributor import PermissionLevel
from src.utils.slide_hash import compute_slide_hash

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tour", tags=["tour"])

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "tour_demo_deck.json"

_fixture_cache: dict | None = None


def _load_fixture() -> dict:
    global _fixture_cache
    if _fixture_cache is None:
        with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
            _fixture_cache = json.load(f)
    return _fixture_cache


def _get_user_prompt(fixture: dict) -> str:
    return fixture["chat_prompt"]


def _phase1_create_session(created_by: str) -> dict:
    """Phase 1: create session + user message only (no slides)."""
    fixture = _load_fixture()
    sm = get_session_manager()

    # Graph-capable (pinned): the fixture's chat_prompt carries no
    # USE LEGACY MODE opt-out, so since 2026-10-12 the tour deck resolves to
    # the graph like any other deck, and a graph turn on an unpinned session
    # raises ConversationPinMissingError.  The fixture already ships a
    # deck_spec for exactly this (ws4d), so a user who keeps chatting after the
    # tour gets the default engine.
    session = sm.create_session(
        title=fixture["title"],
        created_by=created_by,
        graph_capable=True,
    )
    session_id = session["session_id"]

    sm.add_message(
        session_id=session_id,
        role="user",
        content=_get_user_prompt(fixture),
        message_type="chat",
        metadata={"tour_stage": "prompt", "node": "user"},
    )

    return {"session_id": session_id, "title": fixture["title"]}


STAGES: tuple[str, ...] = ("prompt", "plan", "build", "review", "edit")


class StageOrderError(Exception):
    """A stage was requested before the stage it follows has run."""


def _applied_stages(sm, session_id: str) -> set[str]:
    return {
        (m.get("metadata") or {}).get("tour_stage")
        for m in sm.get_messages(session_id)
    } - {None}


def _say(sm, session_id, stage, node, content, message_type, role="assistant"):
    sm.add_message(
        session_id=session_id,
        role=role,
        content=content,
        message_type=message_type,
        metadata={"tour_stage": stage, "node": node},
    )


def _save_deck(sm, session_id: str, slides: list, deck_spec: dict, created_by: str) -> None:
    """Replace the deck's slides and write its spec (two writes, see below)."""
    fixture = _load_fixture()
    deck_dict = {
        "title": fixture["title"],
        "css": fixture.get("css", ""),
        "external_scripts": fixture.get("external_scripts", []),
        "scripts": fixture.get("scripts", ""),
        "slides": slides,
        "slide_count": len(slides),
    }

    sm.save_slide_deck(
        session_id=session_id,
        title=fixture["title"],
        html_content="",
        scripts_content="",
        slide_count=len(slides),
        deck_dict=deck_dict,
        modified_by=created_by,
    )

    # The fixture's hand-authored deck spec needs a SECOND write.
    #
    # save_slide_deck does NOT persist a deck spec: it writes deck_json, css,
    # external_scripts_json, head_meta_json and the per-slide rows, and never
    # touches deck.deck_spec_json.  A "deck_spec" key handed to it in deck_dict is
    # swallowed into the deck_json blob and never read back into the column, with
    # no exception — measured, and guarded by
    # tests/unit/test_tour_ships_a_spec.py::test_save_slide_deck_alone_does_not
    # _persist_a_spec.  So the spec is written here through ws4b's deck-level
    # writer, which does own that column.
    #
    # Teaching save_slide_deck about specs was rejected: it is on the monolith's
    # hot path with a large test surface, and the tour needs one extra call, not a
    # new behaviour on a shared writer.  The cost is one deck.version bump, which
    # is harmless for a freshly created tour deck.
    #
    # This is deck CREATION from fixed bytes, identical on every tour, so it
    # deliberately does NOT call spec_sync.mark_dirty: that would schedule an LLM
    # arc re-description of the same demo deck for every user who takes the tour.
    # Shipping the arc in the fixture instead also lets the tour demonstrate the
    # spec view, which an excluded-and-specless tour deck could not.
    write_deck_level_columns(
        session_id,
        deck_spec=deck_spec,
        modified_by=created_by,
        mutation=sm.deck_mutation_context(
            session_id,
            operation="write_deck_level",
            object_type="deck",
        ),
    )


def _seed_verification(sm, session_id: str, slides: list, findings_by_position: dict) -> None:
    """Store a verification record for EVERY slide.

    useAutoVerification fires an LLM judge on any slide whose verification is
    falsy, and save_slide_deck replaces every slide row, so this must run after
    each save for all slides, not just the ones that changed.
    """
    stage_build = _load_fixture()["stages"]["build"]
    judge = {
        **{k: stage_build["verification"][k] for k in ("score", "rating", "explanation")},
        "issues": [],
        "duration_ms": 0,
        "error": False,
    }
    for position, slide in enumerate(slides):
        content_hash = compute_slide_hash(slide["html"])
        findings = [
            Finding(
                id=make_finding_id(f["criterion"], content_hash, ordinal=i),
                slide_index=position,
                category=f["category"],
                criterion=f["criterion"],
                message=f["message"],
                objective=f["objective"],
            )
            for i, f in enumerate(findings_by_position.get(position, []))
        ]
        record = build_verification_record(
            content_hash=content_hash,
            findings=findings,
            verdict="surfaced" if findings else "clean",
        )
        record[content_hash] = {**judge, **record[content_hash]}
        sm.write_slide_verification(session_id, position, record)


def _run_stage(session_id: str, stage: str, created_by: str) -> dict:
    """Apply one stage of the scripted graph turn (idempotent, forward-only)."""
    if stage not in STAGES or stage == "prompt":
        raise ValueError(f"Unknown tour stage: {stage!r}")
    sm = get_session_manager()

    applied = _applied_stages(sm, session_id)
    if stage not in applied:
        previous = STAGES[STAGES.index(stage) - 1]
        if previous not in applied:
            raise StageOrderError(f"Stage {stage!r} requires {previous!r} to run first")

    def slide_count() -> int:
        deck = sm.get_slide_deck(session_id) or {}
        return len(deck.get("slides") or [])

    if stage in applied:
        return {"session_id": session_id, "stage": stage, "applied": False, "slide_count": slide_count()}

    fixture = _load_fixture()
    script = fixture["stages"]
    # JSON object keys are strings; positions are ints.
    findings = {int(k): v for k, v in script["build"]["findings"].items()}

    if stage == "plan":
        _say(sm, session_id, stage, "architect", script["plan"]["architect_reply"], "llm_response")
    elif stage == "build":
        slides = copy.deepcopy(fixture["slides"])
        _say(sm, session_id, stage, "foreman", script["build"]["foreman_line"], "info")
        _save_deck(sm, session_id, slides, copy.deepcopy(fixture["deck_spec"]), created_by)
        _seed_verification(sm, session_id, slides, findings)
        for line in script["build"]["review_lines"]:
            _say(sm, session_id, stage, "build_reviewer", line, "info")
    elif stage == "review":
        _say(sm, session_id, stage, "deck_reviewer", script["review"]["advisory"], "info")
    else:  # edit
        edit = script["edit"]
        slides = copy.deepcopy(fixture["slides"])
        slides[edit["position"]] = copy.deepcopy(edit["slide"])
        spec = copy.deepcopy(fixture["deck_spec"])
        spec["slides"][edit["position"]]["content_brief"] = edit["content_brief"]
        _say(sm, session_id, stage, "user", edit["user_prompt"], "chat", role="user")
        _say(sm, session_id, stage, "architect", edit["architect_reply"], "llm_response")
        _save_deck(sm, session_id, slides, spec, created_by)
        _seed_verification(sm, session_id, slides, findings)
        _say(sm, session_id, stage, "build_reviewer", edit["review_line"], "info")

    return {"session_id": session_id, "stage": stage, "applied": True, "slide_count": slide_count()}


@router.post("/demo-deck")
async def create_demo_deck():
    """Phase 1: create session with the user prompt only."""
    current_user = get_current_user()
    try:
        result = await asyncio.to_thread(_phase1_create_session, current_user)
        logger.info("Tour demo deck phase 1", extra={"session_id": result["session_id"]})
        return result
    except Exception as e:
        logger.error(f"Tour demo deck phase 1 failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create demo deck") from e


@router.post("/demo-deck/{session_id}/stages/{stage}")
async def run_demo_stage(session_id: str, stage: str):
    """Advance the demo deck by one stage of a scripted graph turn."""
    # SDR-4437 HIGH-1 class: writes into an arbitrary session_id.
    _check_deck_permission_for_session(session_id, PermissionLevel.CAN_EDIT)
    if stage not in STAGES or stage == "prompt":
        raise HTTPException(status_code=404, detail="Unknown tour stage")
    current_user = get_current_user()
    try:
        result = await asyncio.to_thread(_run_stage, session_id, stage, current_user)
    except StageOrderError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Tour demo stage {stage} failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to run demo stage") from e
    logger.info("Tour demo stage", extra={"session_id": session_id, "stage": stage})
    return result
