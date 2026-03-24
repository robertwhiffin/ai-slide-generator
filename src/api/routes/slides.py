"""Slide manipulation endpoints for reordering, editing, duplicating, and deleting slides.

All blocking operations are wrapped with asyncio.to_thread for multi-user concurrency.
Mutation operations use session locking to prevent race conditions.

Slide access is controlled by session permissions:
- CAN_VIEW: Can view slides (via get_slides)
- CAN_EDIT: Can modify slides (reorder, update, duplicate, delete)
- CAN_MANAGE: Full control (same as owner)
"""

import asyncio
import logging
from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.api.services.chat_service import get_chat_service
from src.api.services.session_manager import SessionNotFoundError, VersionConflictError, get_session_manager
from src.core.context_utils import run_in_thread_with_context
from src.core.database import get_db
from src.core.permission_context import get_permission_context
from src.core.user_context import get_current_user
from src.database.models.profile_contributor import PermissionLevel
from src.services.permission_service import PermissionService, PERMISSION_PRIORITY

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/slides", tags=["slides"])


def _get_session_permission(
    session_id: str,
    db: Session,
) -> Tuple[bool, Optional[PermissionLevel]]:
    """Check if current user has access to a session's slides.

    For contributor sessions, permission is derived from the profile — not
    from session creation. For root (owner) sessions, the creator gets
    CAN_MANAGE.
    
    Args:
        session_id: Session identifier
        db: Database session
        
    Returns:
        Tuple of (has_access, permission_level)
    """
    session_manager = get_session_manager()
    current_user = get_current_user()
    ctx = get_permission_context()
    
    try:
        session_info = session_manager.get_session(session_id)
    except SessionNotFoundError:
        return False, None
    
    is_contributor = session_info.get("is_contributor_session", False)

    # For root sessions, creator gets full control
    if not is_contributor and session_info.get("created_by") == current_user:
        return True, PermissionLevel.CAN_MANAGE
    
    # For contributor sessions (or non-creator access), use profile permission
    profile_id = session_info.get("profile_id")
    if profile_id and ctx:
        perm_service = PermissionService()
        permission = perm_service.get_profile_permission(
            db,
            profile_id=profile_id,
            user_id=ctx.user_id,
            user_name=ctx.user_name,
            group_ids=ctx.group_ids,
        )
        if permission:
            return True, permission
    
    # Allow contributor session creator even without explicit profile permission
    # (they were granted access when the contributor session was created)
    if is_contributor and session_info.get("created_by") == current_user:
        return True, PermissionLevel.CAN_VIEW
    
    return False, None


def _require_slide_permission(
    session_id: str,
    db: Session,
    min_permission: PermissionLevel = PermissionLevel.CAN_VIEW,
) -> PermissionLevel:
    """Require user has at least the specified permission level on slides.
    
    Args:
        session_id: Session identifier
        db: Database session
        min_permission: Minimum required permission (default: CAN_VIEW)
        
    Returns:
        The user's actual permission level
        
    Raises:
        HTTPException 403: If user doesn't have required permission
    """
    has_access, permission = _get_session_permission(session_id, db)
    
    if not has_access or permission is None:
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to access these slides",
        )
    
    if PERMISSION_PRIORITY[permission] < PERMISSION_PRIORITY[min_permission]:
        raise HTTPException(
            status_code=403,
            detail=f"This action requires {min_permission.value} permission",
        )
    
    return permission


class ReorderRequest(BaseModel):
    """Request to reorder slides."""

    session_id: str
    new_order: List[int]
    expected_version: Optional[int] = None


class UpdateSlideRequest(BaseModel):
    """Request to update a slide's HTML."""

    session_id: str
    html: str
    expected_version: Optional[int] = None


class SlideActionRequest(BaseModel):
    """Request for slide actions (duplicate)."""

    session_id: str
    expected_version: Optional[int] = None


class UpdateVerificationRequest(BaseModel):
    """Request to update a slide's verification result."""

    session_id: str
    verification: dict | None  # VerificationResult or None to clear


@router.get("")
async def get_slides(
    session_id: str = Query(..., description="Session ID"),
    db: Session = Depends(get_db),
):
    """Get current slide deck.

    Requires at least CAN_VIEW permission.

    Args:
        session_id: Session identifier

    Returns:
        Slide deck dictionary with user's permission level

    Raises:
        HTTPException: 403 if no permission, 404 if no slides available, 500 on error
    """
    try:
        # Check permission
        permission = _require_slide_permission(session_id, db, PermissionLevel.CAN_VIEW)
        
        chat_service = get_chat_service()
        result = await asyncio.to_thread(chat_service.get_slides, session_id)

        if not result:
            raise HTTPException(status_code=404, detail="No slides available")

        # Add permission level to response
        result["my_permission"] = permission.value

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
async def reorder_slides(request: ReorderRequest, db: Session = Depends(get_db)):
    """Reorder slides.

    Requires CAN_EDIT permission.
    Uses session locking to prevent concurrent modifications.

    Args:
        request: ReorderRequest with session_id and new slide order

    Returns:
        Updated slide deck

    Raises:
        HTTPException: 403 if no permission, 400 for validation errors, 409 if session busy, 500 on error
    """
    _require_slide_permission(request.session_id, db, PermissionLevel.CAN_EDIT)
    
    session_manager = get_session_manager()

    try:
        await run_in_thread_with_context(session_manager.require_editing_lock, request.session_id)
    except PermissionError as e:
        raise HTTPException(status_code=423, detail=str(e))

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
            expected_version=request.expected_version,
        )

        logger.info(
            "Reordered slides",
            extra={"new_order": request.new_order, "session_id": request.session_id},
        )
        return result

    except VersionConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=423, detail=str(e))
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
async def update_slide(index: int, request: UpdateSlideRequest, db: Session = Depends(get_db)):
    """Update a single slide's HTML.

    Requires CAN_EDIT permission.
    Uses session locking to prevent concurrent modifications.

    Args:
        index: Slide index to update
        request: UpdateSlideRequest with session_id and new HTML

    Returns:
        Updated slide information

    Raises:
        HTTPException: 403 if no permission, 400 for validation errors, 409 if session busy, 500 on error
    """
    _require_slide_permission(request.session_id, db, PermissionLevel.CAN_EDIT)
    session_manager = get_session_manager()

    try:
        await run_in_thread_with_context(session_manager.require_editing_lock, request.session_id)
    except PermissionError as e:
        raise HTTPException(status_code=423, detail=str(e))

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
            expected_version=request.expected_version,
        )

        logger.info(
            "Updated slide",
            extra={"index": index, "session_id": request.session_id},
        )
        return result

    except VersionConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=423, detail=str(e))
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
async def duplicate_slide(index: int, request: SlideActionRequest, db: Session = Depends(get_db)):
    """Duplicate a slide.

    Requires CAN_EDIT permission.
    Uses session locking to prevent concurrent modifications.

    Args:
        index: Slide index to duplicate
        request: SlideActionRequest with session_id

    Returns:
        Updated slide deck

    Raises:
        HTTPException: 403 if no permission, 400 for validation errors, 409 if session busy, 500 on error
    """
    _require_slide_permission(request.session_id, db, PermissionLevel.CAN_EDIT)
    
    session_manager = get_session_manager()

    try:
        await run_in_thread_with_context(session_manager.require_editing_lock, request.session_id)
    except PermissionError as e:
        raise HTTPException(status_code=423, detail=str(e))

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
            expected_version=request.expected_version,
        )

        logger.info(
            "Duplicated slide",
            extra={"index": index, "session_id": request.session_id},
        )
        return result

    except VersionConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=423, detail=str(e))
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
async def delete_slide(
    index: int,
    session_id: str = Query(..., description="Session ID"),
    expected_version: Optional[int] = Query(None, description="Expected deck version for optimistic locking"),
    db: Session = Depends(get_db),
):
    """Delete a slide.

    Requires CAN_EDIT permission.
    Uses session locking to prevent concurrent modifications.

    Args:
        index: Slide index to delete
        session_id: Session identifier
        expected_version: If provided, reject when stale

    Returns:
        Updated slide deck

    Raises:
        HTTPException: 403 if no permission, 400 for validation errors, 409 if session busy or version conflict, 500 on error
    """
    _require_slide_permission(session_id, db, PermissionLevel.CAN_EDIT)
    
    session_manager = get_session_manager()

    try:
        await run_in_thread_with_context(session_manager.require_editing_lock, session_id)
    except PermissionError as e:
        raise HTTPException(status_code=423, detail=str(e))

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
            expected_version=expected_version,
        )

        logger.info(
            "Deleted slide",
            extra={"index": index, "session_id": session_id},
        )
        return result

    except VersionConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=423, detail=str(e))
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


class UpdateVersionVerificationRequest(BaseModel):
    """Request to update verification on an existing version."""

    session_id: str
    verification_map: dict


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


@router.patch("/versions/{version_number}/verification")
async def update_version_verification(
    version_number: int,
    request: UpdateVersionVerificationRequest,
):
    """Update verification results on an existing save point.

    Called by the frontend after auto-verification completes to backfill
    verification results onto a save point that was created before
    verification ran.

    Args:
        version_number: Version to update
        request: UpdateVersionVerificationRequest with session_id and verification_map

    Returns:
        Updated version info

    Raises:
        HTTPException: 400 if version not found, 500 on error
    """
    try:
        session_manager = get_session_manager()
        result = await asyncio.to_thread(
            session_manager.update_version_verification,
            request.session_id,
            version_number,
            request.verification_map,
        )

        logger.info(
            "Updated version verification via API",
            extra={
                "session_id": request.session_id,
                "version_number": version_number,
            },
        )
        return result

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update version verification: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class SyncVerificationRequest(BaseModel):
    """Request to sync verification onto the latest save point."""

    session_id: str


@router.post("/versions/sync-verification")
async def sync_latest_version_verification(request: SyncVerificationRequest):
    """Sync the current session verification_map onto the latest save point.

    Called by the frontend after auto-verification completes. The backend
    reads the current verification_map from the session and updates the
    most recent version with it.

    Args:
        request: SyncVerificationRequest with session_id

    Returns:
        Updated version info, or empty dict if no versions exist
    """
    try:
        session_manager = get_session_manager()

        # Get latest version number
        versions = await asyncio.to_thread(
            session_manager.list_versions,
            request.session_id,
        )
        if not versions:
            return {}

        latest_version = versions[0]["version_number"]

        # Get current verification map from session
        verification_map = await asyncio.to_thread(
            session_manager.get_verification_map,
            request.session_id,
        )

        if not verification_map:
            return {}

        # Update the latest version
        result = await asyncio.to_thread(
            session_manager.update_version_verification,
            request.session_id,
            latest_version,
            verification_map,
        )

        logger.info(
            "Synced verification to latest version",
            extra={
                "session_id": request.session_id,
                "version_number": latest_version,
                "verification_entries": len(verification_map),
            },
        )
        return result

    except Exception as e:
        logger.error(f"Failed to sync version verification: {e}", exc_info=True)
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

    except SessionNotFoundError:
        # Session hasn't been persisted yet (local UUID) - return empty list
        return {"versions": [], "current_version": None}
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
        result = await run_in_thread_with_context(
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

    except PermissionError as e:
        raise HTTPException(status_code=423, detail=str(e))
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

    except SessionNotFoundError:
        # Session hasn't been persisted yet (local UUID) - no versions
        return {"current_version": None}
    except Exception as e:
        logger.error(f"Failed to get current version: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
