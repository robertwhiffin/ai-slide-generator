"""Database-backed session manager for persistent multi-session support.

This service handles CRUD operations for sessions stored in the database,
supporting both local PostgreSQL and Databricks Lakebase deployments.
"""
import json
import logging
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.core.database import get_db_session
from src.database.models.session import SessionMessage, SessionSlideDeck, UserSession

logger = logging.getLogger(__name__)


class SessionNotFoundError(Exception):
    """Raised when a session is not found."""

    pass


class SessionManager:
    """Manager for database-backed session operations.

    Provides CRUD operations for sessions with support for:
    - Multi-user session isolation
    - Session expiration and cleanup
    - Slide deck persistence
    - Message history storage
    """

    def __init__(self, session_ttl_hours: int = 24):
        """Initialize session manager.

        Args:
            session_ttl_hours: Hours after which inactive sessions expire
        """
        self.session_ttl_hours = session_ttl_hours

    def create_session(
        self,
        user_id: Optional[str] = None,
        title: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new session.

        Args:
            user_id: Optional user identifier for session isolation
            title: Optional session title
            session_id: Optional session ID (if not provided, one is generated)

        Returns:
            Dictionary with session info including session_id
        """
        if session_id is None:
            session_id = secrets.token_urlsafe(32)

        with get_db_session() as db:
            session = UserSession(
                session_id=session_id,
                user_id=user_id,
                title=title or f"Session {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
            )
            db.add(session)
            db.flush()

            logger.info(
                "Created new session",
                extra={"session_id": session_id, "user_id": user_id},
            )

            return {
                "session_id": session_id,
                "user_id": user_id,
                "title": session.title,
                "created_at": session.created_at.isoformat(),
            }

    def get_session(self, session_id: str) -> Dict[str, Any]:
        """Get session by ID.

        Args:
            session_id: Session identifier

        Returns:
            Session information dictionary

        Raises:
            SessionNotFoundError: If session doesn't exist
        """
        with get_db_session() as db:
            session = self._get_session_or_raise(db, session_id)

            return {
                "session_id": session.session_id,
                "user_id": session.user_id,
                "title": session.title,
                "created_at": session.created_at.isoformat(),
                "last_activity": session.last_activity.isoformat(),
                "genie_conversation_id": session.genie_conversation_id,
                "message_count": len(session.messages),
                "has_slide_deck": session.slide_deck is not None,
            }

    def list_sessions(
        self,
        user_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List sessions, optionally filtered by user.

        Args:
            user_id: Optional user filter
            limit: Maximum number of sessions to return

        Returns:
            List of session info dictionaries
        """
        with get_db_session() as db:
            query = db.query(UserSession)

            if user_id:
                query = query.filter(UserSession.user_id == user_id)

            sessions = (
                query.order_by(UserSession.last_activity.desc())
                .limit(limit)
                .all()
            )

            return [
                {
                    "session_id": s.session_id,
                    "user_id": s.user_id,
                    "title": s.title,
                    "created_at": s.created_at.isoformat(),
                    "last_activity": s.last_activity.isoformat(),
                    "message_count": len(s.messages),
                    "has_slide_deck": s.slide_deck is not None,
                }
                for s in sessions
            ]

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and all associated data.

        Args:
            session_id: Session to delete

        Returns:
            True if session was deleted

        Raises:
            SessionNotFoundError: If session doesn't exist
        """
        with get_db_session() as db:
            session = self._get_session_or_raise(db, session_id)
            db.delete(session)

            logger.info("Deleted session", extra={"session_id": session_id})
            return True

    def rename_session(self, session_id: str, title: str) -> Dict[str, Any]:
        """Rename a session.

        Args:
            session_id: Session to rename
            title: New title for the session

        Returns:
            Updated session info

        Raises:
            SessionNotFoundError: If session doesn't exist
        """
        with get_db_session() as db:
            session = self._get_session_or_raise(db, session_id)
            session.title = title
            session.last_activity = datetime.utcnow()

            logger.info(
                "Renamed session",
                extra={"session_id": session_id, "new_title": title},
            )

            return {
                "session_id": session.session_id,
                "title": session.title,
                "updated_at": session.last_activity.isoformat(),
            }

    def update_last_activity(self, session_id: str) -> None:
        """Update session's last activity timestamp.

        Args:
            session_id: Session to update
        """
        with get_db_session() as db:
            session = self._get_session_or_raise(db, session_id)
            session.last_activity = datetime.utcnow()

    def set_genie_conversation_id(
        self,
        session_id: str,
        conversation_id: Optional[str],
    ) -> None:
        """Set or clear the Genie conversation ID for a session.

        Args:
            session_id: Session to update
            conversation_id: Genie conversation ID (or None to clear)
        """
        with get_db_session() as db:
            session = self._get_session_or_raise(db, session_id)
            session.genie_conversation_id = conversation_id

            logger.info(
                "Updated Genie conversation ID",
                extra={"session_id": session_id, "conversation_id": conversation_id},
            )

    # Message operations
    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        message_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Add a message to a session.

        Args:
            session_id: Session to add message to
            role: Message role ('user', 'assistant', 'system')
            content: Message content
            message_type: Optional message type classification
            metadata: Optional additional metadata

        Returns:
            Message info dictionary
        """
        with get_db_session() as db:
            session = self._get_session_or_raise(db, session_id)

            message = SessionMessage(
                session_id=session.id,
                role=role,
                content=content,
                message_type=message_type,
                metadata_json=json.dumps(metadata) if metadata else None,
            )
            db.add(message)
            db.flush()

            # Update session activity
            session.last_activity = datetime.utcnow()

            return {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "created_at": message.created_at.isoformat(),
            }

    def get_messages(
        self,
        session_id: str,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Get messages for a session.

        Args:
            session_id: Session to get messages for
            limit: Optional limit on messages returned

        Returns:
            List of message dictionaries
        """
        with get_db_session() as db:
            session = self._get_session_or_raise(db, session_id)

            messages = session.messages
            if limit:
                messages = messages[-limit:]

            return [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "message_type": m.message_type,
                    "created_at": m.created_at.isoformat(),
                    "metadata": json.loads(m.metadata_json) if m.metadata_json else None,
                }
                for m in messages
            ]

    # Slide deck operations
    def save_slide_deck(
        self,
        session_id: str,
        title: Optional[str],
        html_content: str,
        scripts_content: Optional[str] = None,
        slide_count: int = 0,
        deck_dict: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Save or update slide deck for a session.

        Args:
            session_id: Session to save deck for
            title: Deck title
            html_content: Full HTML content (knitted)
            scripts_content: JavaScript content
            slide_count: Number of slides
            deck_dict: Full SlideDeck structure for restoration

        Returns:
            Slide deck info dictionary
        """
        with get_db_session() as db:
            session = self._get_session_or_raise(db, session_id)

            # Serialize deck structure to JSON
            deck_json = json.dumps(deck_dict) if deck_dict else None

            if session.slide_deck:
                # Update existing
                deck = session.slide_deck
                deck.title = title
                deck.html_content = html_content
                deck.scripts_content = scripts_content
                deck.slide_count = slide_count
                deck.deck_json = deck_json
            else:
                # Create new
                deck = SessionSlideDeck(
                    session_id=session.id,
                    title=title,
                    html_content=html_content,
                    scripts_content=scripts_content,
                    slide_count=slide_count,
                    deck_json=deck_json,
                )
                db.add(deck)
                db.flush()

            # Update session activity
            session.last_activity = datetime.utcnow()

            logger.info(
                "Saved slide deck",
                extra={"session_id": session_id, "slide_count": slide_count},
            )

            return {
                "session_id": session_id,
                "title": deck.title,
                "slide_count": deck.slide_count,
                "updated_at": deck.updated_at.isoformat(),
            }

    def get_slide_deck(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get slide deck for a session.

        Args:
            session_id: Session to get deck for

        Returns:
            Full SlideDeck dictionary (with slides array) or None if no deck exists
        """
        with get_db_session() as db:
            session = self._get_session_or_raise(db, session_id)

            if not session.slide_deck:
                return None

            deck = session.slide_deck
            
            # Return full deck structure if available
            if deck.deck_json:
                deck_dict = json.loads(deck.deck_json)
                # Ensure it has required fields
                deck_dict.setdefault("title", deck.title)
                deck_dict.setdefault("slide_count", deck.slide_count)
                return deck_dict
            
            # Legacy: return basic info without slides array
            return {
                "title": deck.title,
                "html_content": deck.html_content,
                "scripts_content": deck.scripts_content,
                "slide_count": deck.slide_count,
                "created_at": deck.created_at.isoformat(),
                "updated_at": deck.updated_at.isoformat(),
            }

    # Session locking for concurrent request handling
    def acquire_session_lock(self, session_id: str, timeout_seconds: int = 300) -> bool:
        """Try to acquire processing lock for a session.

        Uses database-level locking to work across multiple uvicorn workers.

        Args:
            session_id: Session to lock
            timeout_seconds: Max time a lock can be held before considered stale

        Returns:
            True if lock acquired (or session doesn't exist yet), False if session is already locked
        """
        with get_db_session() as db:
            session = (
                db.query(UserSession)
                .filter(UserSession.session_id == session_id)
                .first()
            )

            # If session doesn't exist yet, allow proceeding (will be auto-created)
            if not session:
                logger.info(
                    "Session not found for locking, allowing auto-creation",
                    extra={"session_id": session_id},
                )
                return True

            if session.is_processing:
                # Check if lock is stale (held too long)
                if session.processing_started_at:
                    age = (datetime.utcnow() - session.processing_started_at).total_seconds()
                    if age < timeout_seconds:
                        return False  # Legitimately locked
                # Stale lock - proceed to acquire

            session.is_processing = True
            session.processing_started_at = datetime.utcnow()

            logger.info(
                "Acquired session lock",
                extra={"session_id": session_id},
            )
            return True

    def release_session_lock(self, session_id: str) -> None:
        """Release processing lock for a session.

        Args:
            session_id: Session to unlock
        """
        with get_db_session() as db:
            session = (
                db.query(UserSession)
                .filter(UserSession.session_id == session_id)
                .first()
            )

            # If session doesn't exist, nothing to unlock
            if not session:
                return

            session.is_processing = False
            session.processing_started_at = None

            logger.info(
                "Released session lock",
                extra={"session_id": session_id},
            )

    # Cleanup operations
    def cleanup_expired_sessions(self) -> int:
        """Delete sessions that have exceeded TTL.

        Returns:
            Number of sessions deleted
        """
        cutoff = datetime.utcnow() - timedelta(hours=self.session_ttl_hours)

        with get_db_session() as db:
            expired = (
                db.query(UserSession)
                .filter(UserSession.last_activity < cutoff)
                .all()
            )

            count = len(expired)
            for session in expired:
                db.delete(session)

            if count > 0:
                logger.info(
                    "Cleaned up expired sessions",
                    extra={"count": count, "cutoff": cutoff.isoformat()},
                )

            return count

    def _get_session_or_raise(self, db: Session, session_id: str) -> UserSession:
        """Get session by ID or raise error.

        Args:
            db: Database session
            session_id: Session identifier

        Returns:
            UserSession instance

        Raises:
            SessionNotFoundError: If session doesn't exist
        """
        session = (
            db.query(UserSession)
            .filter(UserSession.session_id == session_id)
            .first()
        )

        if not session:
            raise SessionNotFoundError(f"Session not found: {session_id}")

        return session


# Global session manager instance
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """Get the global SessionManager instance.

    Returns:
        SessionManager singleton instance
    """
    global _session_manager

    if _session_manager is None:
        _session_manager = SessionManager()

    return _session_manager

