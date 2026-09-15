"""Tour demo deck endpoints.

Two-phase creation so the tour can show the user prompt first,
then reveal the AI response and slides after a short delay.

Phase 1 — POST /api/tour/demo-deck
  Creates a session with only the user's chat message.

Phase 2 — POST /api/tour/demo-deck/{session_id}/slides
  Adds the assistant reply and pre-built slides to the session.
"""

import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from src.api.routes._authz import _check_deck_permission_for_session
from src.api.services.deck_level_writer import write_deck_level_columns
from src.api.services.session_manager import get_session_manager
from src.core.user_context import get_current_user
from src.database.models.profile_contributor import PermissionLevel

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

    session = sm.create_session(
        title=fixture["title"],
        created_by=created_by,
    )
    session_id = session["session_id"]

    sm.add_message(
        session_id=session_id,
        role="user",
        content=_get_user_prompt(fixture),
        message_type="chat",
    )

    return {"session_id": session_id, "title": fixture["title"]}


def _phase2_add_slides(session_id: str, created_by: str) -> dict:
    """Phase 2: add assistant reply + slides."""
    fixture = _load_fixture()
    sm = get_session_manager()

    slides = fixture.get("slides", [])
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
        deck_spec=fixture["deck_spec"],
        modified_by=created_by,
    )

    assistant_reply = fixture["chat_reply"]

    sm.add_message(
        session_id=session_id,
        role="assistant",
        content=assistant_reply,
        message_type="chat",
    )

    return {"session_id": session_id, "slide_count": len(slides)}


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


@router.post("/demo-deck/{session_id}/slides")
async def add_demo_slides(session_id: str):
    """Phase 2: add assistant reply and pre-built slides."""
    # SDR-4437 HIGH-1 class: writes slides into an arbitrary session_id.
    _check_deck_permission_for_session(session_id, PermissionLevel.CAN_EDIT)
    current_user = get_current_user()
    try:
        result = await asyncio.to_thread(_phase2_add_slides, session_id, current_user)
        logger.info("Tour demo deck phase 2", extra={"session_id": session_id})
        return result
    except Exception as e:
        logger.error(f"Tour demo deck phase 2 failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to add demo slides") from e
