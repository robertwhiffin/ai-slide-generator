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
from src.database.models.session import (
    ChatRequest,
    SessionMessage,
    SessionSlideDeck,
    UserSession,
)

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
        profile_id: Optional[int] = None,
        profile_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new session.

        Args:
            user_id: Optional user identifier for session isolation
            title: Optional session title
            session_id: Optional session ID (if not provided, one is generated)
            profile_id: Optional profile ID this session belongs to
            profile_name: Optional profile name (cached for display)

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
                profile_id=profile_id,
                profile_name=profile_name,
            )
            db.add(session)
            db.flush()

            logger.info(
                "Created new session",
                extra={"session_id": session_id, "user_id": user_id, "profile_id": profile_id},
            )

            return {
                "session_id": session_id,
                "user_id": user_id,
                "title": session.title,
                "created_at": session.created_at.isoformat(),
                "profile_id": profile_id,
                "profile_name": profile_name,
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
                "profile_id": session.profile_id,
                "profile_name": session.profile_name,
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
                    "profile_id": s.profile_id,
                    "profile_name": s.profile_name,
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

    def set_session_profile(
        self,
        session_id: str,
        profile_id: int,
        profile_name: str,
    ) -> None:
        """Set the profile for a session.

        Used to associate a session with a profile when it's first used.

        Args:
            session_id: Session to update
            profile_id: Profile ID to associate
            profile_name: Profile name (cached for display)
        """
        with get_db_session() as db:
            session = self._get_session_or_raise(db, session_id)
            # Only set if not already set (preserve original profile)
            if session.profile_id is None:
                session.profile_id = profile_id
                session.profile_name = profile_name

                logger.info(
                    "Set session profile",
                    extra={
                        "session_id": session_id,
                        "profile_id": profile_id,
                        "profile_name": profile_name,
                    },
                )

    # Message operations
    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        message_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add a message to a session.

        Args:
            session_id: Session to add message to
            role: Message role ('user', 'assistant', 'system')
            content: Message content
            message_type: Optional message type classification
            metadata: Optional additional metadata
            request_id: Optional chat request ID for async polling

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
                request_id=request_id,
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
        """Get slide deck for a session with verification merged by content hash.

        Verification results are stored separately in verification_map and
        merged back into slides based on content hash matching.

        Args:
            session_id: Session to get deck for

        Returns:
            Full SlideDeck dictionary (with slides array and verification) or None
        """
        from src.utils.slide_hash import compute_slide_hash
        
        with get_db_session() as db:
            session = self._get_session_or_raise(db, session_id)

            if not session.slide_deck:
                return None

            deck = session.slide_deck
            
            # Load verification map (separate from deck_json)
            verification_map = {}
            if deck.verification_map:
                try:
                    verification_map = json.loads(deck.verification_map)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid verification_map JSON for session {session_id}")
            
            # Return full deck structure if available
            if deck.deck_json:
                deck_dict = json.loads(deck.deck_json)
                # Ensure it has required fields
                deck_dict.setdefault("title", deck.title)
                deck_dict.setdefault("slide_count", deck.slide_count)
                # Include html_content for raw HTML debug view
                if deck.html_content:
                    deck_dict["html_content"] = deck.html_content
                
                # Merge verification into slides by content hash
                for slide in deck_dict.get("slides", []):
                    if slide.get("html"):
                        content_hash = compute_slide_hash(slide["html"])
                        slide["verification"] = verification_map.get(content_hash)
                        slide["content_hash"] = content_hash
                
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

    def save_verification(
        self,
        session_id: str,
        content_hash: str,
        verification: Dict[str, Any],
    ) -> None:
        """Save verification result for a slide by content hash.

        Verification is stored separately from deck_json so it survives
        deck regeneration when chat modifies slides.

        Args:
            session_id: Session to save verification for
            content_hash: Hash of the slide content
            verification: Verification result dictionary
        """
        with get_db_session() as db:
            session = self._get_session_or_raise(db, session_id)

            if not session.slide_deck:
                logger.warning(f"No slide deck for session {session_id}, cannot save verification")
                return

            deck = session.slide_deck
            
            # Load existing verification map
            verification_map = {}
            if deck.verification_map:
                try:
                    verification_map = json.loads(deck.verification_map)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid verification_map JSON, starting fresh")
            
            # Update with new verification
            verification_map[content_hash] = verification
            
            # Save back to database
            deck.verification_map = json.dumps(verification_map)
            
            logger.info(
                "Saved verification",
                extra={
                    "session_id": session_id,
                    "content_hash": content_hash,
                    "score": verification.get("score"),
                },
            )

    def get_verification_map(self, session_id: str) -> Dict[str, Any]:
        """Get the verification map for a session.

        Args:
            session_id: Session to get verification map for

        Returns:
            Dictionary mapping content hashes to verification results
        """
        with get_db_session() as db:
            session = self._get_session_or_raise(db, session_id)

            if not session.slide_deck or not session.slide_deck.verification_map:
                return {}

            try:
                return json.loads(session.slide_deck.verification_map)
            except json.JSONDecodeError:
                logger.warning(f"Invalid verification_map JSON for session {session_id}")
                return {}

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

    # Chat request operations (for polling-based streaming)
    def create_chat_request(
        self,
        session_id: str,
        profile_id: Optional[int] = None,
        profile_name: Optional[str] = None,
    ) -> str:
        """Create a new chat request, return request_id.

        Auto-creates the session if it doesn't exist.

        Args:
            session_id: Session to create request for
            profile_id: Profile ID to associate with new sessions
            profile_name: Profile name (cached for display)

        Returns:
            Generated request_id
        """
        request_id = secrets.token_urlsafe(24)

        with get_db_session() as db:
            # Get or create session
            session = (
                db.query(UserSession)
                .filter(UserSession.session_id == session_id)
                .first()
            )

            if not session:
                # Auto-create session on first request
                session = UserSession(
                    session_id=session_id,
                    title=f"Session {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
                    profile_id=profile_id,
                    profile_name=profile_name,
                )
                db.add(session)
                db.flush()
                logger.info(
                    "Auto-created session for chat request",
                    extra={"session_id": session_id, "profile_id": profile_id},
                )
            elif session.profile_id is None and profile_id is not None:
                # Update profile for existing session without one
                session.profile_id = profile_id
                session.profile_name = profile_name
                logger.info(
                    "Updated session profile on chat request",
                    extra={"session_id": session_id, "profile_id": profile_id},
                )

            chat_request = ChatRequest(
                request_id=request_id,
                session_id=session.id,
                status="pending",
            )
            db.add(chat_request)
            db.flush()

            logger.info(
                "Created chat request",
                extra={"request_id": request_id, "session_id": session_id},
            )

            return request_id

    def update_chat_request_status(
        self,
        request_id: str,
        status: str,
        error: Optional[str] = None,
    ) -> None:
        """Update request status (pending/running/completed/error).

        Args:
            request_id: Request ID to update
            status: New status
            error: Optional error message
        """
        with get_db_session() as db:
            chat_request = (
                db.query(ChatRequest)
                .filter(ChatRequest.request_id == request_id)
                .first()
            )

            if not chat_request:
                logger.warning(f"ChatRequest not found: {request_id}")
                return

            chat_request.status = status
            if error:
                chat_request.error_message = error
            if status in ("completed", "error"):
                chat_request.completed_at = datetime.utcnow()

    def set_chat_request_result(
        self, request_id: str, result: Optional[dict]
    ) -> None:
        """Store final result (slides, raw_html, etc).

        Args:
            request_id: Request ID to update
            result: Result dictionary to store as JSON
        """
        with get_db_session() as db:
            chat_request = (
                db.query(ChatRequest)
                .filter(ChatRequest.request_id == request_id)
                .first()
            )

            if not chat_request:
                return

            chat_request.result_json = json.dumps(result) if result else None

    def get_chat_request(self, request_id: str) -> Optional[Dict[str, Any]]:
        """Get request status and result.

        Args:
            request_id: Request ID to look up

        Returns:
            Request info dictionary or None if not found
        """
        with get_db_session() as db:
            chat_request = (
                db.query(ChatRequest)
                .filter(ChatRequest.request_id == request_id)
                .first()
            )

            if not chat_request:
                return None

            return {
                "request_id": chat_request.request_id,
                "session_id": chat_request.session_id,
                "status": chat_request.status,
                "error_message": chat_request.error_message,
                "created_at": chat_request.created_at.isoformat(),
                "completed_at": (
                    chat_request.completed_at.isoformat()
                    if chat_request.completed_at
                    else None
                ),
                "result": (
                    json.loads(chat_request.result_json)
                    if chat_request.result_json
                    else None
                ),
            }

    def get_session_id_for_request(self, request_id: str) -> Optional[str]:
        """Get the session_id (string) for a chat request.

        Args:
            request_id: Request ID to look up

        Returns:
            Session ID string or None if not found
        """
        with get_db_session() as db:
            chat_request = (
                db.query(ChatRequest)
                .filter(ChatRequest.request_id == request_id)
                .first()
            )

            if not chat_request:
                return None

            # Get the UserSession to get the string session_id
            session = (
                db.query(UserSession)
                .filter(UserSession.id == chat_request.session_id)
                .first()
            )

            return session.session_id if session else None

    def get_messages_for_request(
        self,
        request_id: str,
        after_id: int = 0,
    ) -> List[Dict[str, Any]]:
        """Get messages with request_id, optionally after a given message ID.

        Args:
            request_id: Request ID to filter by
            after_id: Return messages with ID greater than this

        Returns:
            List of message dictionaries
        """
        with get_db_session() as db:
            query = db.query(SessionMessage).filter(
                SessionMessage.request_id == request_id
            )

            if after_id > 0:
                query = query.filter(SessionMessage.id > after_id)

            messages = query.order_by(SessionMessage.created_at).all()

            return [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "message_type": m.message_type,
                    "created_at": m.created_at.isoformat(),
                    "metadata": (
                        json.loads(m.metadata_json) if m.metadata_json else None
                    ),
                }
                for m in messages
            ]

    def msg_to_stream_event(self, msg: dict) -> dict:
        """Convert database message to StreamEvent-like dict for polling response.

        Args:
            msg: Message dictionary from get_messages_for_request

        Returns:
            StreamEvent-compatible dictionary
        """
        event_type = "assistant"  # default

        if msg["message_type"] == "tool_call":
            event_type = "tool_call"
        elif msg["message_type"] == "tool_result":
            event_type = "tool_result"
        elif msg["role"] == "user":
            event_type = "assistant"  # User messages use assistant type for display

        metadata = msg.get("metadata") or {}

        return {
            "type": event_type,
            "content": msg["content"],
            "tool_name": metadata.get("tool_name"),
            "tool_input": metadata.get("tool_input"),
            "tool_output": msg["content"] if event_type == "tool_result" else None,
            "message_id": msg["id"],
        }

    def cleanup_stale_requests(self, max_age_hours: int = 24) -> int:
        """Clean up old/stuck chat requests.

        Args:
            max_age_hours: Delete requests older than this

        Returns:
            Number of requests deleted
        """
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)

        with get_db_session() as db:
            stale = (
                db.query(ChatRequest).filter(ChatRequest.created_at < cutoff).all()
            )

            count = len(stale)
            for req in stale:
                db.delete(req)

            if count > 0:
                logger.info(
                    "Cleaned up stale chat requests",
                    extra={"count": count},
                )

            return count

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

