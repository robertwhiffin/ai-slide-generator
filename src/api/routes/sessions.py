"""Session management endpoints.

Provides CRUD operations for managing user sessions with persistent storage.
All blocking database calls are wrapped with asyncio.to_thread to avoid blocking the event loop.
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from src.api.schemas.requests import CreateSessionRequest
from src.api.services.session_manager import (
    SessionNotFoundError,
    get_session_manager,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _substitute_deck_images(deck_dict: dict) -> None:
    """Substitute {{image:ID}} placeholders in a deck dict with base64 data URIs."""
    from src.core.database import get_db_session
    from src.utils.image_utils import substitute_deck_dict_images

    with get_db_session() as db:
        substitute_deck_dict_images(deck_dict, db)


@router.post("")
async def create_session(request: CreateSessionRequest = None):
    """Create a new session.

    Args:
        request: Optional session creation parameters

    Returns:
        Created session info with session_id
    """
    request = request or CreateSessionRequest()

    try:
        session_manager = get_session_manager()
        result = await asyncio.to_thread(
            session_manager.create_session,
            session_id=request.session_id,
            user_id=request.user_id,
            title=request.title,
        )

        logger.info(
            "Session created via API",
            extra={"session_id": result["session_id"]},
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
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    limit: int = Query(50, ge=1, le=100, description="Maximum sessions to return"),
):
    """List sessions.

    Args:
        user_id: Optional user filter
        limit: Maximum number of sessions to return

    Returns:
        List of session summaries
    """
    try:
        session_manager = get_session_manager()
        sessions = await asyncio.to_thread(
            session_manager.list_sessions,
            user_id=user_id,
            limit=limit,
        )

        return {"sessions": sessions, "count": len(sessions)}

    except Exception as e:
        logger.error(f"Failed to list sessions: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list sessions: {str(e)}",
        ) from e


@router.get("/{session_id}")
async def get_session(session_id: str):
    """Get session details including messages and slides.

    Args:
        session_id: Session identifier

    Returns:
        Session information with messages and slide_deck
    """
    try:
        session_manager = get_session_manager()

        # Get session info
        session = await asyncio.to_thread(session_manager.get_session, session_id)

        # Get messages for conversation restoration
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
        }

    except SessionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Session not found: {session_id}",
        )
    except Exception as e:
        logger.error(f"Failed to get session: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get session: {str(e)}",
        ) from e


@router.patch("/{session_id}")
async def update_session(session_id: str, title: str = None):
    """Update session (rename).

    Args:
        session_id: Session to update
        title: New session title

    Returns:
        Updated session info
    """
    try:
        session_manager = get_session_manager()
        result = await asyncio.to_thread(
            session_manager.rename_session,
            session_id,
            title,
        )

        logger.info(
            "Session renamed via API",
            extra={"session_id": session_id, "new_title": title},
        )

        return result

    except SessionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Session not found: {session_id}",
        )
    except Exception as e:
        logger.error(f"Failed to update session: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update session: {str(e)}",
        ) from e


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """Delete a session.

    Args:
        session_id: Session to delete

    Returns:
        Deletion confirmation
    """
    try:
        session_manager = get_session_manager()
        await asyncio.to_thread(session_manager.delete_session, session_id)

        logger.info("Session deleted via API", extra={"session_id": session_id})

        return {"status": "deleted", "session_id": session_id}

    except SessionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Session not found: {session_id}",
        )
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

    Args:
        session_id: Session identifier
        limit: Optional limit on messages

    Returns:
        List of messages
    """
    try:
        session_manager = get_session_manager()
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
    except Exception as e:
        logger.error(f"Failed to get session messages: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get messages: {str(e)}",
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

