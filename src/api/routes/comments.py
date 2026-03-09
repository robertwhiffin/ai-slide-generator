"""Slide comment endpoints.

Provides CRUD and resolution workflow for per-slide threaded comments.
Comments are shared across all contributors of a presentation — they are
stored against the deck-owner session so viewers, editors, and managers
all see the same thread.

Permission rules:
- CAN_VIEW  → read comments
- CAN_VIEW  → add comments (viewers can participate in discussion)
- CAN_EDIT+ → resolve / unresolve comments
- Author    → edit or delete own comment
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.services.session_manager import SessionNotFoundError, get_session_manager
from src.core.database import get_db
from src.core.user_context import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/comments", tags=["comments"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class AddCommentRequest(BaseModel):
    session_id: str
    slide_id: str
    content: str = Field(..., min_length=1, max_length=4000)
    parent_comment_id: Optional[int] = None


class UpdateCommentRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/mentionable-users")
async def mentionable_users(
    session_id: str = Query(..., description="Session ID"),
):
    """List users who can be @mentioned in comments for a session.

    Returns the session owner plus all profile contributors.
    """
    current_user = get_current_user()
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    session_manager = get_session_manager()
    try:
        users = await asyncio.to_thread(
            session_manager.get_mentionable_users,
            session_id,
        )
        return {"users": users}
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Failed to list mentionable users: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mentions")
async def list_mentions():
    """List comments that @mention the current user (for notifications)."""
    current_user = get_current_user()
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    session_manager = get_session_manager()
    try:
        mentions = await asyncio.to_thread(
            session_manager.list_mentions,
            current_user,
        )
        return {"mentions": mentions, "count": len(mentions)}
    except Exception as e:
        logger.error(f"Failed to list mentions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
async def list_comments(
    session_id: str = Query(..., description="Session ID"),
    slide_id: Optional[str] = Query(None, description="Filter by slide_id"),
    include_resolved: bool = Query(False, description="Include resolved comments"),
):
    """List comments for a presentation or a specific slide.

    Returns top-level comments with nested replies.
    """
    session_manager = get_session_manager()
    try:
        comments = await asyncio.to_thread(
            session_manager.list_comments,
            session_id,
            slide_id=slide_id,
            include_resolved=include_resolved,
        )
        return {"comments": comments, "count": len(comments)}
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Failed to list comments: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("")
async def add_comment(request: AddCommentRequest):
    """Add a comment on a slide."""
    current_user = get_current_user()
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    session_manager = get_session_manager()
    try:
        comment = await asyncio.to_thread(
            session_manager.add_comment,
            session_id=request.session_id,
            slide_id=request.slide_id,
            user_name=current_user,
            content=request.content,
            parent_comment_id=request.parent_comment_id,
        )
        return comment
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to add comment: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{comment_id}")
async def update_comment(comment_id: int, request: UpdateCommentRequest):
    """Edit a comment (author only)."""
    current_user = get_current_user()
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    session_manager = get_session_manager()
    try:
        comment = await asyncio.to_thread(
            session_manager.update_comment,
            comment_id=comment_id,
            user_name=current_user,
            content=request.content,
        )
        return comment
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update comment: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{comment_id}")
async def delete_comment(comment_id: int):
    """Delete a comment (author only). Replies are cascaded."""
    current_user = get_current_user()
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    session_manager = get_session_manager()
    try:
        await asyncio.to_thread(
            session_manager.delete_comment,
            comment_id=comment_id,
            user_name=current_user,
        )
        return {"status": "deleted", "comment_id": comment_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to delete comment: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{comment_id}/resolve")
async def resolve_comment(comment_id: int):
    """Mark a comment as resolved."""
    current_user = get_current_user()
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    session_manager = get_session_manager()
    try:
        comment = await asyncio.to_thread(
            session_manager.resolve_comment,
            comment_id=comment_id,
            resolved_by=current_user,
        )
        return comment
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to resolve comment: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{comment_id}/unresolve")
async def unresolve_comment(comment_id: int):
    """Re-open a resolved comment."""
    current_user = get_current_user()
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    session_manager = get_session_manager()
    try:
        comment = await asyncio.to_thread(
            session_manager.unresolve_comment,
            comment_id=comment_id,
        )
        return comment
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to unresolve comment: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
