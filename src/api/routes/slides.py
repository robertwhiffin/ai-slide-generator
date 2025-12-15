"""Slide manipulation endpoints for reordering, editing, duplicating, and deleting slides.

All blocking operations are wrapped with asyncio.to_thread for multi-user concurrency.
Mutation operations use session locking to prevent race conditions.
"""

import asyncio
import logging
from typing import List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.api.services.chat_service import get_chat_service
from src.api.services.session_manager import get_session_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/slides", tags=["slides"])


class ReorderRequest(BaseModel):
    """Request to reorder slides."""

    session_id: str
    new_order: List[int]


class UpdateSlideRequest(BaseModel):
    """Request to update a slide's HTML."""

    session_id: str
    html: str


class SlideActionRequest(BaseModel):
    """Request for slide actions (duplicate)."""

    session_id: str


class UpdateVerificationRequest(BaseModel):
    """Request to update a slide's verification result."""

    session_id: str
    verification: dict | None  # VerificationResult or None to clear


@router.get("")
async def get_slides(session_id: str = Query(..., description="Session ID")):
    """Get current slide deck.

    Args:
        session_id: Session identifier

    Returns:
        Slide deck dictionary

    Raises:
        HTTPException: 404 if no slides available, 500 on error
    """
    try:
        chat_service = get_chat_service()
        result = await asyncio.to_thread(chat_service.get_slides, session_id)

        if not result:
            raise HTTPException(status_code=404, detail="No slides available")

        logger.info(
            "Retrieved slides",
            extra={"slide_count": result.get("slide_count", 0), "session_id": session_id},
        )
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get slides: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/reorder")
async def reorder_slides(request: ReorderRequest):
    """Reorder slides.

    Uses session locking to prevent concurrent modifications.

    Args:
        request: ReorderRequest with session_id and new slide order

    Returns:
        Updated slide deck

    Raises:
        HTTPException: 400 for validation errors, 409 if session busy, 500 on error
    """
    session_manager = get_session_manager()

    locked = await asyncio.to_thread(
        session_manager.acquire_session_lock,
        request.session_id,
    )
    if not locked:
        raise HTTPException(
            status_code=409,
            detail="Session is currently processing another request. Please wait.",
        )

    try:
        chat_service = get_chat_service()
        result = await asyncio.to_thread(
            chat_service.reorder_slides,
            request.session_id,
            request.new_order,
        )

        logger.info(
            "Reordered slides",
            extra={"new_order": request.new_order, "session_id": request.session_id},
        )
        return result

    except ValueError as e:
        logger.warning(f"Validation error in reorder_slides: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to reorder slides: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await asyncio.to_thread(
            session_manager.release_session_lock,
            request.session_id,
        )


@router.patch("/{index}")
async def update_slide(index: int, request: UpdateSlideRequest):
    """Update a single slide's HTML.

    Uses session locking to prevent concurrent modifications.

    Args:
        index: Slide index to update
        request: UpdateSlideRequest with session_id and new HTML

    Returns:
        Updated slide information

    Raises:
        HTTPException: 400 for validation errors, 409 if session busy, 500 on error
    """
    session_manager = get_session_manager()

    locked = await asyncio.to_thread(
        session_manager.acquire_session_lock,
        request.session_id,
    )
    if not locked:
        raise HTTPException(
            status_code=409,
            detail="Session is currently processing another request. Please wait.",
        )

    try:
        chat_service = get_chat_service()
        result = await asyncio.to_thread(
            chat_service.update_slide,
            request.session_id,
            index,
            request.html,
        )

        logger.info(
            "Updated slide",
            extra={"index": index, "session_id": request.session_id},
        )
        return result

    except ValueError as e:
        logger.warning(f"Validation error in update_slide: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update slide: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await asyncio.to_thread(
            session_manager.release_session_lock,
            request.session_id,
        )


@router.post("/{index}/duplicate")
async def duplicate_slide(index: int, request: SlideActionRequest):
    """Duplicate a slide.

    Uses session locking to prevent concurrent modifications.

    Args:
        index: Slide index to duplicate
        request: SlideActionRequest with session_id

    Returns:
        Updated slide deck

    Raises:
        HTTPException: 400 for validation errors, 409 if session busy, 500 on error
    """
    session_manager = get_session_manager()

    locked = await asyncio.to_thread(
        session_manager.acquire_session_lock,
        request.session_id,
    )
    if not locked:
        raise HTTPException(
            status_code=409,
            detail="Session is currently processing another request. Please wait.",
        )

    try:
        chat_service = get_chat_service()
        result = await asyncio.to_thread(
            chat_service.duplicate_slide,
            request.session_id,
            index,
        )

        logger.info(
            "Duplicated slide",
            extra={"index": index, "session_id": request.session_id},
        )
        return result

    except ValueError as e:
        logger.warning(f"Validation error in duplicate_slide: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to duplicate slide: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await asyncio.to_thread(
            session_manager.release_session_lock,
            request.session_id,
        )


@router.delete("/{index}")
async def delete_slide(index: int, session_id: str = Query(..., description="Session ID")):
    """Delete a slide.

    Uses session locking to prevent concurrent modifications.

    Args:
        index: Slide index to delete
        session_id: Session identifier

    Returns:
        Updated slide deck

    Raises:
        HTTPException: 400 for validation errors, 409 if session busy, 500 on error
    """
    session_manager = get_session_manager()

    locked = await asyncio.to_thread(
        session_manager.acquire_session_lock,
        session_id,
    )
    if not locked:
        raise HTTPException(
            status_code=409,
            detail="Session is currently processing another request. Please wait.",
        )

    try:
        chat_service = get_chat_service()
        result = await asyncio.to_thread(
            chat_service.delete_slide,
            session_id,
            index,
        )

        logger.info(
            "Deleted slide",
            extra={"index": index, "session_id": session_id},
        )
        return result

    except ValueError as e:
        logger.warning(f"Validation error in delete_slide: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to delete slide: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await asyncio.to_thread(
            session_manager.release_session_lock,
            session_id,
        )


@router.patch("/{index}/verification")
async def update_slide_verification(index: int, request: UpdateVerificationRequest):
    """Update a slide's verification result.

    This persists the LLM as Judge verification result with the slide
    so it survives page refresh and session restore.

    Args:
        index: Slide index to update
        request: UpdateVerificationRequest with session_id and verification result

    Returns:
        Updated slide deck

    Raises:
        HTTPException: 400 for validation errors, 404 if slide not found, 500 on error
    """
    session_manager = get_session_manager()

    try:
        # Get current deck
        deck = await asyncio.to_thread(
            session_manager.get_slide_deck,
            request.session_id,
        )

        if not deck:
            raise HTTPException(status_code=404, detail="No slide deck found")

        slides = deck.get("slides", [])
        if index < 0 or index >= len(slides):
            raise HTTPException(
                status_code=400,
                detail=f"Slide index {index} out of range (0-{len(slides)-1})",
            )

        # Update verification for the slide
        # If verification is None, remove the key entirely (avoids null in JSON)
        # This ensures frontend receives undefined instead of null
        if request.verification is None:
            slides[index].pop("verification", None)
        else:
            slides[index]["verification"] = request.verification

        # Save updated deck
        import json
        await asyncio.to_thread(
            session_manager.save_slide_deck,
            request.session_id,
            deck.get("title"),
            deck.get("html_content", ""),
            deck.get("scripts", ""),
            len(slides),
            deck,  # Full deck dict with updated verification
        )

        logger.info(
            "Updated slide verification",
            extra={
                "index": index,
                "session_id": request.session_id,
                "has_verification": request.verification is not None,
            },
        )

        return deck

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update slide verification: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
