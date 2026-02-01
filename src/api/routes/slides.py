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
    """Update a slide's verification result in verification_map.

    Note: With the content hash approach, verification is normally saved
    automatically by the verify_slide endpoint. This endpoint can be used
    to explicitly save or clear verification results.
    
    When verification is None (clearing), this is typically not needed
    because editing a slide changes its content hash, so the old verification
    naturally won't match.

    Args:
        index: Slide index to update
        request: UpdateVerificationRequest with session_id and verification result

    Returns:
        Updated slide deck with verification merged

    Raises:
        HTTPException: 400 for validation errors, 404 if slide not found, 500 on error
    """
    from src.utils.slide_hash import compute_slide_hash
    
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

        slide = slides[index]
        slide_html = slide.get("html", "")
        content_hash = compute_slide_hash(slide_html)

        if request.verification is not None:
            # Save verification by content hash
            await asyncio.to_thread(
                session_manager.save_verification,
                request.session_id,
                content_hash,
                request.verification,
            )
            
            logger.info(
                "Updated slide verification",
                extra={
                    "index": index,
                    "session_id": request.session_id,
                    "content_hash": content_hash,
                    "has_verification": True,
                },
            )
        else:
            # Clearing verification is typically not needed with hash-based approach
            # The old verification naturally won't match after content edit
            logger.info(
                "Clear verification request (no-op with hash-based storage)",
                extra={
                    "index": index,
                    "session_id": request.session_id,
                },
            )

        # Reload deck to get updated verification merged in
        updated_deck = await asyncio.to_thread(
            session_manager.get_slide_deck,
            request.session_id,
        )

        return updated_deck

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update slide verification: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Version / Save Point Endpoints
# ============================================================================


class RestoreVersionRequest(BaseModel):
    """Request to restore a version."""

    session_id: str


class CreateVersionRequest(BaseModel):
    """Request to create a save point."""

    session_id: str
    description: str


@router.post("/versions/create")
async def create_version(request: CreateVersionRequest):
    """Create a save point for the current deck state.

    Called by frontend after auto-verification completes to ensure
    the save point captures the verification results.

    Args:
        request: CreateVersionRequest with session_id and description

    Returns:
        Created version info

    Raises:
        HTTPException: 400 if no deck exists, 500 on error
    """
    try:
        chat_service = get_chat_service()
        version_info = await asyncio.to_thread(
            chat_service.create_save_point,
            request.session_id,
            request.description,
        )

        logger.info(
            "Created save point via API",
            extra={
                "session_id": request.session_id,
                "version_number": version_info.get("version_number"),
                "description": request.description,
            },
        )
        return version_info

    except ValueError as e:
        logger.warning(f"Validation error in create_version: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create version: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/versions")
async def list_versions(session_id: str = Query(..., description="Session ID")):
    """List all save points for a session.

    Args:
        session_id: Session identifier

    Returns:
        List of version info dictionaries (newest first)

    Raises:
        HTTPException: 404 if session not found, 500 on error
    """
    session_manager = get_session_manager()

    try:
        versions = await asyncio.to_thread(
            session_manager.list_versions,
            session_id,
        )

        logger.info(
            "Listed versions",
            extra={"session_id": session_id, "count": len(versions)},
        )
        return {"versions": versions, "current_version": versions[0]["version_number"] if versions else None}

    except Exception as e:
        logger.error(f"Failed to list versions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/versions/{version_number}")
async def preview_version(
    version_number: int,
    session_id: str = Query(..., description="Session ID"),
):
    """Preview a specific save point.

    Returns the full deck snapshot for the version without restoring it.
    Use this for the preview feature before deciding to revert.

    Args:
        version_number: Version number to preview
        session_id: Session identifier

    Returns:
        Version data including full deck snapshot

    Raises:
        HTTPException: 404 if version not found, 500 on error
    """
    session_manager = get_session_manager()

    try:
        version = await asyncio.to_thread(
            session_manager.get_version,
            session_id,
            version_number,
        )

        if not version:
            raise HTTPException(
                status_code=404,
                detail=f"Version {version_number} not found",
            )

        logger.info(
            "Previewed version",
            extra={"session_id": session_id, "version_number": version_number},
        )
        return version

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to preview version: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/versions/{version_number}/restore")
async def restore_version(version_number: int, request: RestoreVersionRequest):
    """Restore to a specific save point.

    This will:
    1. Restore the deck to the specified version
    2. Delete all versions newer than the restored one
    3. Update the current deck in the database

    Uses session locking to prevent concurrent modifications.

    Args:
        version_number: Version number to restore to
        request: RestoreVersionRequest with session_id

    Returns:
        Restored deck data

    Raises:
        HTTPException: 400 if version not found, 409 if session busy, 500 on error
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
        result = await asyncio.to_thread(
            session_manager.restore_version,
            request.session_id,
            version_number,
        )

        # Also update the in-memory cache in chat_service
        chat_service = get_chat_service()
        await asyncio.to_thread(
            chat_service.reload_deck_from_database,
            request.session_id,
        )

        logger.info(
            "Restored version",
            extra={
                "session_id": request.session_id,
                "version_number": version_number,
                "deleted_versions": result.get("deleted_versions", 0),
            },
        )
        return result

    except ValueError as e:
        logger.warning(f"Validation error in restore_version: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to restore version: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await asyncio.to_thread(
            session_manager.release_session_lock,
            request.session_id,
        )


@router.get("/versions/current")
async def get_current_version(session_id: str = Query(..., description="Session ID")):
    """Get the current (latest) version number.

    Args:
        session_id: Session identifier

    Returns:
        Current version number or null if no versions exist

    Raises:
        HTTPException: 500 on error
    """
    session_manager = get_session_manager()

    try:
        version_number = await asyncio.to_thread(
            session_manager.get_current_version_number,
            session_id,
        )

        return {"current_version": version_number}

    except Exception as e:
        logger.error(f"Failed to get current version: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
