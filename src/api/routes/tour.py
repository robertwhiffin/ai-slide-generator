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

from src.api.services.session_manager import get_session_manager
from src.core.user_context import get_current_user

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
    return fixture.get(
        "chat_prompt",
        "Create 3 slides about the benefits of AI in modern healthcare, "
        "with a title slide, key advantages, and future outlook.",
    )


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

    assistant_reply = fixture.get(
        "chat_reply",
        f"Here's your deck with {len(slides)} slides! I've created:\n\n"
        "1. **Title Slide** — introducing AI in healthcare\n"
        "2. **Key Advantages** — early detection, personalized treatment, "
        "operational efficiency, and drug discovery\n"
        "3. **Future Outlook** — predictive monitoring, AI-assisted surgery, "
        "and global health equity\n\n"
        "Feel free to ask me to refine any slide, add new ones, or change the style.",
    )

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
    current_user = get_current_user()
    try:
        result = await asyncio.to_thread(_phase2_add_slides, session_id, current_user)
        logger.info("Tour demo deck phase 2", extra={"session_id": session_id})
        return result
    except Exception as e:
        logger.error(f"Tour demo deck phase 2 failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to add demo slides") from e
