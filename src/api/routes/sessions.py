"""Session management endpoints.

Provides CRUD operations for managing user sessions with persistent storage.
All blocking database calls are wrapped with asyncio.to_thread to avoid blocking the event loop.

Session access is controlled by:
1. Being the session creator (created_by)
2. Having permission on the session's profile (CAN_VIEW, CAN_EDIT, CAN_MANAGE)
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.schemas.requests import CreateSessionRequest
from src.api.services.session_manager import (
    SessionNotFoundError,
    get_session_manager,
)
from src.core.database import get_db
from src.core.permission_context import get_permission_context
from src.core.user_context import get_current_user
from src.database.models.profile_contributor import PermissionLevel
from src.services.permission_service import PermissionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


class UpdateSessionRequest(BaseModel):
    """Optional body for PATCH /api/sessions/{session_id}."""

    title: Optional[str] = Field(None, description="Session/deck title")
    slide_count: Optional[int] = Field(None, ge=0, description="Deck slide count")


def _get_session_permission(
    session_info: dict,
    db: Session,
) -> Tuple[bool, Optional[PermissionLevel]]:
    """Check if current user has access to a session and return their permission level.

    For root (owner) sessions, the creator gets CAN_MANAGE.
    For contributor sessions, permission comes from the profile.
    
    Args:
        session_info: Session dict with created_by, profile_id, is_contributor_session
        db: Database session
        
    Returns:
        Tuple of (has_access, permission_level)
    """
    current_user = get_current_user()
    ctx = get_permission_context()
    is_contributor = session_info.get("is_contributor_session", False)
    
    # For root sessions, creator gets full control
    if not is_contributor and session_info.get("created_by") == current_user:
        return True, PermissionLevel.CAN_MANAGE
    
    # For contributor sessions (or non-creator access), use profile permission
    profile_id = session_info.get("profile_id")
    if profile_id and ctx:
        perm_service = PermissionService(db)
        permission = perm_service.get_user_permission(
            profile_id=profile_id,
            user_id=ctx.user_id,
            user_name=ctx.user_name,
            group_ids=ctx.group_ids,
        )
        if permission:
            return True, permission
    
    # Fallback: contributor session creator can at least view
    if is_contributor and session_info.get("created_by") == current_user:
        return True, PermissionLevel.CAN_VIEW
    
    return False, None


def _require_session_access(
    session_info: dict,
    db: Session,
    min_permission: PermissionLevel = PermissionLevel.CAN_VIEW,
) -> PermissionLevel:
    """Require user has at least the specified permission level on a session.
    
    Args:
        session_info: Session dict with created_by and profile_id
        db: Database session
        min_permission: Minimum required permission (default: CAN_VIEW)
        
    Returns:
        The user's actual permission level
        
    Raises:
        HTTPException 403: If user doesn't have required permission
    """
    from src.services.permission_service import PERMISSION_PRIORITY
    
    has_access, permission = _get_session_permission(session_info, db)
    
    if not has_access or permission is None:
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to access this session",
        )
    
    if PERMISSION_PRIORITY[permission] < PERMISSION_PRIORITY[min_permission]:
        raise HTTPException(
            status_code=403,
            detail=f"This action requires {min_permission.value} permission",
        )
    
    return permission


def _substitute_deck_images(deck_dict: dict) -> None:
    """Substitute {{image:ID}} placeholders in a deck dict with base64 data URIs."""
    from src.core.database import get_db_session
    from src.utils.image_utils import substitute_deck_dict_images

    with get_db_session() as db:
        substitute_deck_dict_images(deck_dict, db)


@router.post("")
async def create_session(request: CreateSessionRequest = None):
    """Create a new session.

    The ``created_by`` field is set server-side from the authenticated user
    identity resolved by the middleware (never from the client request body).

    Args:
        request: Optional session creation parameters

    Returns:
        Created session info with session_id
    """
    request = request or CreateSessionRequest()
    current_user = get_current_user()

    # Use profile from the request (sent by the frontend) if available,
    # otherwise fall back to the server-side loaded profile.
    profile_id = request.profile_id
    profile_name = request.profile_name
    if profile_id is None:
        try:
            from src.core.settings_db import get_settings
            settings = get_settings()
            profile_id = getattr(settings, 'profile_id', None)
            profile_name = getattr(settings, 'profile_name', None)
        except Exception:
            pass

    try:
        session_manager = get_session_manager()
        result = await asyncio.to_thread(
            session_manager.create_session,
            session_id=request.session_id,
            title=request.title,
            created_by=current_user,
            profile_id=profile_id,
            profile_name=profile_name,
        )

        logger.info(
            "Session created via API",
            extra={"session_id": result["session_id"], "created_by": current_user},
        )

        return result

    except Exception as e:
        logger.error(f"Failed to create session: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create session: {str(e)}",
        ) from e


@router.get("")
async def list_sessions(
    limit: int = Query(50, ge=1, le=100, description="Maximum sessions to return"),
):
    """List sessions created by the current user (My Sessions).

    Sessions are scoped to the authenticated user only.
    Use /api/sessions/shared for sessions shared with you via profile access.

    Args:
        limit: Maximum number of sessions to return

    Returns:
        List of session summaries with my_permission = CAN_MANAGE
    """
    current_user = get_current_user()

    try:
        session_manager = get_session_manager()
        sessions = await asyncio.to_thread(
            session_manager.list_sessions,
            created_by=current_user,
            limit=limit,
        )
        
        # Add permission info (creator always has CAN_MANAGE)
        for session in sessions:
            session["my_permission"] = "CAN_MANAGE"

        return {"sessions": sessions, "count": len(sessions)}

    except Exception as e:
        logger.error(f"Failed to list sessions: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list sessions: {str(e)}",
        ) from e


@router.get("/shared")
async def list_shared_presentations(
    limit: int = Query(50, ge=1, le=100, description="Maximum presentations to return"),
    db: Session = Depends(get_db),
):
    """List presentations (slide decks) shared with the current user via profile access.

    Returns presentation-only data from profiles where the user has CAN_VIEW, CAN_EDIT,
    or CAN_MANAGE permission. Conversations (chat messages) are never exposed —
    contributors only see the slide decks.

    Args:
        limit: Maximum number of presentations to return

    Returns:
        List of presentation summaries with my_permission and slide metadata
    """
    current_user = get_current_user()
    ctx = get_permission_context()

    if not ctx:
        return {"presentations": [], "count": 0}

    try:
        perm_service = PermissionService(db)
        accessible_profile_ids = perm_service.get_accessible_profile_ids(
            user_id=ctx.user_id,
            user_name=ctx.user_name,
            group_ids=ctx.group_ids,
        )

        if not accessible_profile_ids:
            return {"presentations": [], "count": 0}

        session_manager = get_session_manager()
        sessions = await asyncio.to_thread(
            session_manager.list_sessions_by_profile_ids,
            profile_ids=accessible_profile_ids,
            exclude_created_by=current_user,
            limit=limit,
        )

        presentations = []
        for session in sessions:
            if not session.get("has_slide_deck"):
                continue

            profile_id = session.get("profile_id")
            permission = None
            if profile_id:
                permission = perm_service.get_user_permission(
                    profile_id=profile_id,
                    user_id=ctx.user_id,
                    user_name=ctx.user_name,
                    group_ids=ctx.group_ids,
                )

            presentations.append({
                "session_id": session["session_id"],
                "title": session.get("title"),
                "created_by": session.get("created_by"),
                "created_at": session.get("created_at"),
                "last_activity": session.get("last_activity"),
                "modified_by": session.get("modified_by"),
                "modified_at": session.get("modified_at"),
                "profile_id": profile_id,
                "profile_name": session.get("profile_name"),
                "my_permission": permission.value if permission else "CAN_VIEW",
            })

        return {"presentations": presentations, "count": len(presentations)}

    except Exception as e:
        logger.error(f"Failed to list shared presentations: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list shared presentations: {str(e)}",
        ) from e


@router.post("/{session_id}/contribute")
async def get_or_create_contributor_session(
    session_id: str,
    db: Session = Depends(get_db),
):
    """Get or create a contributor session for a shared presentation.

    When a contributor opens a shared presentation, this endpoint creates
    their private session that shares the parent's slide deck. The contributor
    can chat through this session to modify slides, but their conversation
    is private and never visible to other users.

    Requires at least CAN_VIEW permission on the parent session's profile.

    Args:
        session_id: The owner's session ID (parent)

    Returns:
        Contributor session info with session_id for chat/slide operations
    """
    current_user = get_current_user()

    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        session_manager = get_session_manager()

        # Get parent session to check permissions
        parent_session = await asyncio.to_thread(
            session_manager.get_session, session_id
        )

        # Don't allow creating contributor session on your own session
        if parent_session.get("created_by") == current_user:
            raise HTTPException(
                status_code=400,
                detail="You are the owner of this session. Use it directly.",
            )

        # Check profile-level permission
        profile_id = parent_session.get("profile_id")
        if not profile_id:
            raise HTTPException(
                status_code=403,
                detail="This session has no profile — cannot determine access.",
            )

        permission = _require_session_access(parent_session, db, PermissionLevel.CAN_VIEW)

        # Create or retrieve contributor session
        result = await asyncio.to_thread(
            session_manager.get_or_create_contributor_session,
            parent_session_id=session_id,
            created_by=current_user,
        )
        result["my_permission"] = permission.value

        return result

    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create contributor session: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create contributor session: {str(e)}",
        ) from e


@router.get("/{session_id}")
async def get_session(session_id: str, db: Session = Depends(get_db)):
    """Get session details including slides, and messages if user is session creator.

    Conversations are private: only the session creator can see chat messages.
    Contributors (via profile sharing) see the slide deck only.

    Requires at least CAN_VIEW permission (via ownership or profile access).

    Args:
        session_id: Session identifier

    Returns:
        Session information with slide_deck, user's permission level,
        and messages (only if user is the session creator)
    """
    try:
        session_manager = get_session_manager()
        current_user = get_current_user()

        # Get session info
        session = await asyncio.to_thread(session_manager.get_session, session_id)

        # Check permission
        permission = _require_session_access(session, db, PermissionLevel.CAN_VIEW)

        # Only the session creator sees chat messages — conversations are private
        is_creator = session.get("created_by") == current_user
        messages = []
        if is_creator:
            messages = await asyncio.to_thread(session_manager.get_messages, session_id)

        # Get slide deck if it exists
        slide_deck = await asyncio.to_thread(session_manager.get_slide_deck, session_id)

        # Substitute {{image:ID}} placeholders with base64 before sending to client
        if slide_deck:
            await asyncio.to_thread(_substitute_deck_images, slide_deck)

        return {
            **session,
            "messages": messages,
            "slide_deck": slide_deck,
            "my_permission": permission.value,
        }

    except SessionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Session not found: {session_id}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get session: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get session: {str(e)}",
        ) from e


@router.patch("/{session_id}")
async def update_session(
    session_id: str,
    title: Optional[str] = Query(None, description="Session title (legacy query)"),
    body: Optional[UpdateSessionRequest] = None,
    db: Session = Depends(get_db),
):
    """Update session metadata (title and/or slide_count).

    Requires CAN_EDIT permission (via ownership or profile access).
    At least one of title (query or body) or body.slide_count is required.
    """
    title_val = body.title if body else None
    if title_val is None and title is not None:
        title_val = title
    slide_count_val = body.slide_count if body else None
    if title_val is None and slide_count_val is None:
        raise HTTPException(
            status_code=400,
            detail="At least one of title or slide_count is required",
        )
    try:
        session_manager = get_session_manager()
        
        # Get session and check permission
        session = await asyncio.to_thread(session_manager.get_session, session_id)
        _require_session_access(session, db, PermissionLevel.CAN_EDIT)
        
        result = await asyncio.to_thread(
            session_manager.update_session,
            session_id,
            title=title_val,
            slide_count=slide_count_val,
        )

        logger.info(
            "Session updated via API",
            extra={"session_id": session_id, "title": title_val, "slide_count": slide_count_val},
        )

        return result

    except SessionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Session not found: {session_id}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update session: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update session: {str(e)}",
        ) from e


@router.delete("/{session_id}")
async def delete_session(session_id: str, db: Session = Depends(get_db)):
    """Delete a session.

    Requires CAN_MANAGE permission (via ownership or profile access).

    Args:
        session_id: Session to delete

    Returns:
        Deletion confirmation
    """
    try:
        session_manager = get_session_manager()
        
        # Get session and check permission
        session = await asyncio.to_thread(session_manager.get_session, session_id)
        _require_session_access(session, db, PermissionLevel.CAN_MANAGE)
        
        await asyncio.to_thread(session_manager.delete_session, session_id)

        logger.info("Session deleted via API", extra={"session_id": session_id})

        return {"status": "deleted", "session_id": session_id}

    except SessionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Session not found: {session_id}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete session: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete session: {str(e)}",
        ) from e


@router.get("/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    limit: Optional[int] = Query(None, ge=1, le=1000, description="Limit messages returned"),
):
    """Get messages for a session.

    Conversations are private: only the session creator can read messages.

    Args:
        session_id: Session identifier
        limit: Optional limit on messages

    Returns:
        List of messages

    Raises:
        HTTPException 403: If user is not the session creator
    """
    current_user = get_current_user()

    try:
        session_manager = get_session_manager()
        session = await asyncio.to_thread(session_manager.get_session, session_id)

        if session.get("created_by") != current_user:
            raise HTTPException(
                status_code=403,
                detail="Conversations are private. Only the session creator can view messages.",
            )

        messages = await asyncio.to_thread(
            session_manager.get_messages,
            session_id,
            limit=limit,
        )

        return {"session_id": session_id, "messages": messages, "count": len(messages)}

    except SessionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Session not found: {session_id}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get session messages: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get messages: {str(e)}",
        ) from e


class AddMessageRequest(BaseModel):
    """Request model for adding a message to a session."""

    role: str = Field(default="user", description="Message role (user, assistant, system)")
    content: str = Field(..., description="Message content")


@router.post("/{session_id}/messages")
async def add_message(session_id: str, request: AddMessageRequest):
    """Add a message to a session.

    Only the session creator can add messages — conversations are private.

    Args:
        session_id: Session to add message to
        request: Message role and content

    Returns:
        Created message info
    """
    current_user = get_current_user()

    try:
        session_manager = get_session_manager()
        session = await asyncio.to_thread(session_manager.get_session, session_id)

        if session.get("created_by") != current_user:
            raise HTTPException(
                status_code=403,
                detail="Only the session creator can add messages.",
            )

        result = await asyncio.to_thread(
            session_manager.add_message,
            session_id=session_id,
            role=request.role,
            content=request.content,
        )

        return result

    except SessionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Session not found: {session_id}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add message: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to add message: {str(e)}",
        ) from e


@router.get("/{session_id}/slides")
async def get_session_slides(session_id: str):
    """Get slide deck for a session.

    Args:
        session_id: Session identifier

    Returns:
        Slide deck info or null if no deck
    """
    try:
        session_manager = get_session_manager()
        deck = await asyncio.to_thread(session_manager.get_slide_deck, session_id)

        if deck:
            await asyncio.to_thread(_substitute_deck_images, deck)

        return {"session_id": session_id, "slide_deck": deck}

    except SessionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Session not found: {session_id}",
        )
    except Exception as e:
        logger.error(f"Failed to get session slides: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get slides: {str(e)}",
        ) from e


@router.post("/cleanup")
async def cleanup_expired_sessions():
    """Clean up expired sessions.

    Returns:
        Number of sessions deleted
    """
    try:
        session_manager = get_session_manager()
        count = await asyncio.to_thread(session_manager.cleanup_expired_sessions)

        logger.info("Session cleanup completed", extra={"deleted_count": count})

        return {"status": "completed", "deleted_count": count}

    except Exception as e:
        logger.error(f"Failed to cleanup sessions: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Cleanup failed: {str(e)}",
        ) from e


@router.post("/{session_id}/export")
async def export_session(session_id: str):
    """Export full session data to logs/sessions/{session_id}.json for debugging.
    
    Exports:
    - Session info (id, timestamps, profile)
    - All chat messages (user + AI responses with full content)
    - Full slide deck (HTML, scripts, slide count)
    
    Args:
        session_id: Session to export
        
    Returns:
        Export confirmation with file path
    """
    try:
        session_manager = get_session_manager()
        
        # Get all session data
        session = await asyncio.to_thread(session_manager.get_session, session_id)
        messages = await asyncio.to_thread(session_manager.get_messages, session_id)
        slide_deck = await asyncio.to_thread(session_manager.get_slide_deck, session_id)
        
        # Build export data
        export_data = {
            "exported_at": datetime.utcnow().isoformat(),
            "session": session,
            "messages": messages,
            "slide_deck": slide_deck,
            "summary": {
                "message_count": len(messages),
                "slide_count": slide_deck.get("slide_count", 0) if slide_deck else 0,
                "user_messages": sum(1 for m in messages if m.get("role") == "user"),
                "ai_messages": sum(1 for m in messages if m.get("role") == "assistant"),
            }
        }
        
        # Ensure logs/sessions directory exists
        sessions_dir = Path("logs/sessions")
        sessions_dir.mkdir(parents=True, exist_ok=True)
        
        # Write to file
        export_path = sessions_dir / f"{session_id}.json"
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2, default=str)
        
        logger.info(
            "Session exported",
            extra={
                "session_id": session_id,
                "export_path": str(export_path),
                "message_count": len(messages),
            },
        )
        
        return {
            "status": "exported",
            "session_id": session_id,
            "export_path": str(export_path),
            "summary": export_data["summary"],
        }
        
    except SessionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Session not found: {session_id}",
        )
    except Exception as e:
        logger.error(f"Failed to export session: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Export failed: {str(e)}",
        ) from e


# =========================================================================
# Editing lock endpoints — first user to open a shared session gets
# exclusive edit access; others see a read-only banner.
# =========================================================================

@router.post("/{session_id}/lock")
async def acquire_editing_lock(session_id: str):
    """Acquire the editing lock when opening a session."""
    current_user = get_current_user()
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    session_manager = get_session_manager()
    try:
        result = await asyncio.to_thread(
            session_manager.acquire_editing_lock,
            session_id,
            current_user,
        )
        return result
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Failed to acquire editing lock: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{session_id}/lock")
async def release_editing_lock(session_id: str):
    """Release the editing lock when leaving a session."""
    current_user = get_current_user()
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    session_manager = get_session_manager()
    try:
        await asyncio.to_thread(
            session_manager.release_editing_lock,
            session_id,
            current_user,
        )
        return {"status": "released"}
    except Exception as e:
        logger.error(f"Failed to release editing lock: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{session_id}/lock")
async def get_editing_lock_status(session_id: str):
    """Check who holds the editing lock."""
    session_manager = get_session_manager()
    try:
        return await asyncio.to_thread(
            session_manager.get_editing_lock_status,
            session_id,
        )
    except Exception as e:
        logger.error(f"Failed to check editing lock: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{session_id}/lock/heartbeat")
async def heartbeat_editing_lock(session_id: str):
    """Renew the editing lock timestamp (call every ~60s while session is open)."""
    current_user = get_current_user()
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    session_manager = get_session_manager()
    try:
        ok = await asyncio.to_thread(
            session_manager.heartbeat_editing_lock,
            session_id,
            current_user,
        )
        return {"renewed": ok}
    except Exception as e:
        logger.error(f"Failed to heartbeat editing lock: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

