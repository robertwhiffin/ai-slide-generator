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
from src.core.database import get_db, get_db_session
from src.core.permission_context import get_permission_context
from src.core.user_context import get_current_user
from src.database.models.profile_contributor import PermissionLevel
from src.services.permission_service import get_permission_service

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
    """Check user's permission on a session via deck_contributors.

    Resolves to the root session (parent for contributor sessions) and checks
    the DeckContributor table for the current user's permission level.

    Args:
        session_info: Session dict with id, created_by, parent_session_id, etc.
        db: Database session

    Returns:
        Tuple of (has_access, permission_level)
    """
    perm_ctx = get_permission_context()
    perm_service = get_permission_service()
    parent_id = session_info.get("parent_session_internal_id")
    root_session_id = parent_id if parent_id is not None else session_info.get("id")
    perm = perm_service.get_deck_permission(
        db, root_session_id,
        user_id=perm_ctx.user_id if perm_ctx else None,
        user_name=perm_ctx.user_name if perm_ctx else None,
        group_ids=perm_ctx.group_ids if perm_ctx else None,
    )
    if perm is None:
        return False, None
    return True, perm


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


def _check_deck_permission_for_session(
    session_id: str,
    min_permission: PermissionLevel = PermissionLevel.CAN_VIEW,
) -> None:
    """Look up a session by string ID, resolve root, and enforce deck permission.

    This is the standard pattern for endpoints that only have a session_id string
    and need to gate on deck permissions.  It opens its own DB session via
    ``get_db_session`` so it can be called from endpoints that do not already
    have one.

    Args:
        session_id: The string session_id passed to the endpoint.
        min_permission: Minimum required permission level.

    Raises:
        HTTPException 403: If the caller lacks the required permission.
    """
    session_manager = get_session_manager()
    session_info = session_manager.get_session(session_id)
    with get_db_session() as db:
        _require_session_access(session_info, db, min_permission)


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

    try:
        session_manager = get_session_manager()
        result = await asyncio.to_thread(
            session_manager.create_session,
            session_id=request.session_id,
            title=request.title,
            created_by=current_user,
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
    """List presentations (slide decks) shared with the current user via deck_contributors.

    Returns presentation-only data from decks where the user has CAN_VIEW, CAN_EDIT,
    or CAN_MANAGE permission. Conversations (chat messages) are never exposed —
    contributors only see the slide decks.

    Args:
        limit: Maximum number of presentations to return

    Returns:
        List of presentation summaries with my_permission and slide metadata
    """
    ctx = get_permission_context()

    if not ctx:
        return {"presentations": [], "count": 0}

    try:
        perm_service = get_permission_service()
        shared_session_ids = perm_service.get_shared_session_ids(
            db,
            user_id=ctx.user_id,
            user_name=ctx.user_name,
            group_ids=ctx.group_ids,
        )

        if not shared_session_ids:
            return {"presentations": [], "count": 0}

        # Query the actual sessions from DB
        from src.database.models.session import UserSession as UserSessionModel

        sessions = (
            db.query(UserSessionModel)
            .filter(
                UserSessionModel.id.in_(shared_session_ids),
                UserSessionModel.parent_session_id.is_(None),  # Only root sessions
            )
            .order_by(UserSessionModel.last_activity.desc())
            .limit(limit)
            .all()
        )

        presentations = []
        for s in sessions:
            deck = s.slide_deck
            if not deck:
                continue

            permission = perm_service.get_deck_permission(
                db, s.id,
                user_id=ctx.user_id,
                user_name=ctx.user_name,
                group_ids=ctx.group_ids,
            )

            presentations.append({
                "session_id": s.session_id,
                "title": s.title,
                "created_by": s.created_by,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "last_activity": s.last_activity.isoformat() if s.last_activity else None,
                "has_slide_deck": True,
                "slide_count": deck.slide_count if deck else 0,
                "modified_by": getattr(deck, "modified_by", None) or s.created_by,
                "modified_at": deck.updated_at.isoformat() if deck and deck.updated_at else None,
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

        # Check deck-level permission on parent session
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
        # Permission check: require CAN_VIEW on the deck
        await asyncio.to_thread(
            _check_deck_permission_for_session, session_id, PermissionLevel.CAN_VIEW
        )

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
    except HTTPException:
        raise
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
        # Permission check: require CAN_VIEW on the deck
        await asyncio.to_thread(
            _check_deck_permission_for_session, session_id, PermissionLevel.CAN_VIEW
        )

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
    except HTTPException:
        raise
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

    # Permission check: require CAN_EDIT on the deck
    await asyncio.to_thread(
        _check_deck_permission_for_session, session_id, PermissionLevel.CAN_EDIT
    )

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

    # Permission check: require CAN_EDIT on the deck
    await asyncio.to_thread(
        _check_deck_permission_for_session, session_id, PermissionLevel.CAN_EDIT
    )

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
    # Permission check: require CAN_VIEW on the deck
    await asyncio.to_thread(
        _check_deck_permission_for_session, session_id, PermissionLevel.CAN_VIEW
    )

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

    # Permission check: require CAN_EDIT on the deck
    await asyncio.to_thread(
        _check_deck_permission_for_session, session_id, PermissionLevel.CAN_EDIT
    )

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

