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
    SlideDeckVersion,
    UserSession,
)
from src.database.models.slide_comment import SlideComment

logger = logging.getLogger(__name__)


class SessionNotFoundError(Exception):
    """Raised when a session is not found."""

    pass


class VersionConflictError(Exception):
    """Raised when a write is rejected due to stale deck version."""

    def __init__(self, current_version: int, expected_version: int):
        self.current_version = current_version
        self.expected_version = expected_version
        super().__init__(
            f"Version conflict: expected {expected_version}, current is {current_version}"
        )


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
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new session.

        Args:
            user_id: Legacy user identifier (kept for backward compat)
            title: Optional session title
            session_id: Optional session ID (if not provided, one is generated)
            profile_id: Optional profile ID this session belongs to
            profile_name: Optional profile name (cached for display)
            created_by: Username of the authenticated user creating the session

        Returns:
            Dictionary with session info including session_id
        """
        if session_id is None:
            session_id = secrets.token_urlsafe(32)

        with get_db_session() as db:
            # Idempotent: return existing session if ID already taken
            existing = (
                db.query(UserSession)
                .filter(UserSession.session_id == session_id)
                .first()
            )
            if existing:
                return {
                    "session_id": existing.session_id,
                    "user_id": existing.user_id,
                    "created_by": existing.created_by,
                    "title": existing.title,
                    "created_at": existing.created_at.isoformat(),
                    "profile_id": existing.profile_id,
                    "profile_name": existing.profile_name,
                }

            session = UserSession(
                session_id=session_id,
                user_id=user_id,
                created_by=created_by,
                title=title or f"Session {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
                profile_id=profile_id,
                profile_name=profile_name,
            )
            db.add(session)
            db.flush()

            logger.info(
                "Created new session",
                extra={
                    "session_id": session_id,
                    "created_by": created_by,
                    "profile_id": profile_id,
                },
            )

            return {
                "session_id": session_id,
                "user_id": user_id,
                "created_by": created_by,
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

            profile_deleted = self._is_profile_deleted(db, session.profile_id)

            # Resolve parent session and shared slide deck for contributor sessions
            parent_session_id_str = None
            deck_owner = session
            if session.parent_session_id:
                parent = db.query(UserSession).filter(
                    UserSession.id == session.parent_session_id
                ).first()
                parent_session_id_str = parent.session_id if parent else None
                if parent:
                    deck_owner = parent

            return {
                "session_id": session.session_id,
                "user_id": session.user_id,
                "created_by": session.created_by,
                "title": session.title,
                "created_at": session.created_at.isoformat(),
                "last_activity": session.last_activity.isoformat(),
                "genie_conversation_id": session.genie_conversation_id,
                "message_count": len(session.messages),
                "has_slide_deck": deck_owner.slide_deck is not None,
                "profile_id": session.profile_id,
                "profile_name": session.profile_name,
                "google_slides_url": deck_owner.google_slides_url,
                "google_slides_presentation_id": deck_owner.google_slides_presentation_id,
                "profile_deleted": profile_deleted,
                "is_contributor_session": session.is_contributor_session,
                "parent_session_id": parent_session_id_str,
            }

    def get_or_create_contributor_session(
        self,
        parent_session_id: str,
        created_by: str,
    ) -> Dict[str, Any]:
        """Get or create a contributor session for a user on a shared presentation.

        Contributor sessions share the parent's slide deck but have their own
        private chat history. Idempotent: returns existing session if one exists.

        Args:
            parent_session_id: The owner's session_id (string)
            created_by: Username of the contributor

        Returns:
            Contributor session info dictionary

        Raises:
            SessionNotFoundError: If parent session doesn't exist
        """
        with get_db_session() as db:
            parent = self._get_session_or_raise(db, parent_session_id)

            # Don't allow contributor sessions on other contributor sessions
            if parent.is_contributor_session:
                raise ValueError("Cannot create contributor session on another contributor session")

            # Check for existing contributor session
            existing = (
                db.query(UserSession)
                .filter(
                    UserSession.parent_session_id == parent.id,
                    UserSession.created_by == created_by,
                )
                .first()
            )
            if existing:
                return {
                    "session_id": existing.session_id,
                    "created_by": existing.created_by,
                    "title": parent.title,
                    "parent_session_id": parent.session_id,
                    "is_contributor_session": True,
                    "profile_id": parent.profile_id,
                    "profile_name": parent.profile_name,
                    "created_at": existing.created_at.isoformat(),
                }

            contributor = UserSession(
                session_id=secrets.token_urlsafe(32),
                created_by=created_by,
                title=parent.title,
                parent_session_id=parent.id,
                profile_id=parent.profile_id,
                profile_name=parent.profile_name,
            )
            db.add(contributor)
            db.flush()

            logger.info(
                "Created contributor session",
                extra={
                    "contributor_session_id": contributor.session_id,
                    "parent_session_id": parent_session_id,
                    "created_by": created_by,
                },
            )

            return {
                "session_id": contributor.session_id,
                "created_by": created_by,
                "title": parent.title,
                "parent_session_id": parent.session_id,
                "is_contributor_session": True,
                "profile_id": parent.profile_id,
                "profile_name": parent.profile_name,
                "created_at": contributor.created_at.isoformat(),
            }

    def _get_deck_owner_session(self, db: Session, session: UserSession) -> UserSession:
        """Resolve the session that owns the slide deck.

        For root sessions, returns the session itself.
        For contributor sessions, follows parent_session_id to the owner.

        Args:
            db: Database session
            session: The session to resolve

        Returns:
            The root session that owns the slide deck
        """
        if not session.is_contributor_session:
            return session
        parent = db.query(UserSession).filter(
            UserSession.id == session.parent_session_id
        ).first()
        if not parent:
            raise SessionNotFoundError(
                f"Parent session not found for contributor session {session.session_id}"
            )
        return parent

    def list_sessions(
        self,
        created_by: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List sessions, optionally filtered by creator.

        Args:
            created_by: Filter sessions to those created by this username
            user_id: Legacy user filter (kept for backward compat)
            limit: Maximum number of sessions to return

        Returns:
            List of session info dictionaries
        """
        with get_db_session() as db:
            query = db.query(UserSession).filter(
                UserSession.messages.any(),
                UserSession.parent_session_id.is_(None),  # Exclude contributor sessions
            )

            if created_by:
                query = query.filter(UserSession.created_by == created_by)
            elif user_id:
                query = query.filter(UserSession.user_id == user_id)

            sessions = (
                query.order_by(UserSession.last_activity.desc())
                .limit(limit)
                .all()
            )

            # Batch-check which profiles are deleted to avoid N+1 queries
            deleted_profiles = self._get_deleted_profile_ids(
                db,
                [s.profile_id for s in sessions if s.profile_id is not None],
            )

            return [
                {
                    "session_id": s.session_id,
                    "user_id": s.user_id,
                    "created_by": s.created_by,
                    "title": s.title,
                    "created_at": s.created_at.isoformat(),
                    "last_activity": s.last_activity.isoformat(),
                    "message_count": len(s.messages),
                    "has_slide_deck": s.slide_deck is not None,
                    "profile_id": s.profile_id,
                    "profile_name": s.profile_name,
                    "profile_deleted": s.profile_id in deleted_profiles if s.profile_id else False,
                }
                for s in sessions
            ]

    def list_user_sessions(
        self,
        created_by: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List sessions belonging to a specific user.

        Convenience wrapper around ``list_sessions`` that enforces a mandatory
        ``created_by`` filter.

        Args:
            created_by: Username whose sessions to return (required)
            limit: Maximum number of sessions to return

        Returns:
            List of session info dictionaries
        """
        return self.list_sessions(created_by=created_by, limit=limit)

    def list_sessions_by_profile_ids(
        self,
        profile_ids: List[int],
        exclude_created_by: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List sessions belonging to specific profiles.

        Used for permission-based session listing where users can see sessions
        from profiles they have access to.

        Args:
            profile_ids: List of profile IDs to include
            exclude_created_by: Optionally exclude sessions by this creator
                (to avoid duplicates when combining with own sessions)
            limit: Maximum number of sessions to return

        Returns:
            List of session info dictionaries
        """
        if not profile_ids:
            return []

        with get_db_session() as db:
            query = db.query(UserSession).filter(
                UserSession.messages.any(),
                UserSession.profile_id.in_(profile_ids),
                UserSession.parent_session_id.is_(None),  # Only root sessions
            )

            if exclude_created_by:
                query = query.filter(UserSession.created_by != exclude_created_by)

            sessions = (
                query.order_by(UserSession.last_activity.desc())
                .limit(limit)
                .all()
            )

            # Batch-check which profiles are deleted to avoid N+1 queries
            deleted_profiles = self._get_deleted_profile_ids(
                db,
                [s.profile_id for s in sessions if s.profile_id is not None],
            )

            result = []
            for s in sessions:
                deck = s.slide_deck
                info = {
                    "session_id": s.session_id,
                    "user_id": s.user_id,
                    "created_by": s.created_by,
                    "title": s.title,
                    "created_at": s.created_at.isoformat(),
                    "last_activity": s.last_activity.isoformat(),
                    "message_count": len(s.messages),
                    "has_slide_deck": deck is not None,
                    "profile_id": s.profile_id,
                    "profile_name": s.profile_name,
                    "profile_deleted": s.profile_id in deleted_profiles if s.profile_id else False,
                    "modified_by": getattr(deck, "modified_by", None) or s.created_by if deck else None,
                    "modified_at": deck.updated_at.isoformat() if deck and deck.updated_at else None,
                }
                result.append(info)
            return result

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

    def set_google_slides_info(
        self,
        session_id: str,
        presentation_id: str,
        presentation_url: str,
    ) -> None:
        """Store Google Slides presentation info on the deck owner session.

        For contributor sessions the info is written to the parent so
        re-exports by any contributor overwrite the same presentation.
        """
        with get_db_session() as db:
            session = self._get_session_or_raise(db, session_id)
            deck_owner = self._get_deck_owner_session(db, session)
            deck_owner.google_slides_presentation_id = presentation_id
            deck_owner.google_slides_url = presentation_url

            logger.info(
                "Stored Google Slides info on deck owner session",
                extra={
                    "session_id": session_id,
                    "deck_owner_session_id": deck_owner.session_id,
                    "presentation_id": presentation_id,
                },
            )

    def get_google_slides_info(self, session_id: str) -> Optional[Dict[str, str]]:
        """Get the stored Google Slides presentation info.

        For contributor sessions reads from the deck owner.

        Returns:
            Dict with ``presentation_id`` and ``presentation_url``, or None.
        """
        with get_db_session() as db:
            session = self._get_session_or_raise(db, session_id)
            deck_owner = self._get_deck_owner_session(db, session)
            if deck_owner.google_slides_presentation_id:
                return {
                    "presentation_id": deck_owner.google_slides_presentation_id,
                    "presentation_url": deck_owner.google_slides_url,
                }
            return None

    def set_experiment_id(self, session_id: str, experiment_id: str) -> None:
        """Set the MLflow experiment ID for a session.

        Used to track per-session MLflow experiments for tracing.

        Args:
            session_id: Session to update
            experiment_id: MLflow experiment ID
        """
        with get_db_session() as db:
            session = self._get_session_or_raise(db, session_id)
            session.experiment_id = experiment_id

            logger.info(
                "Set session experiment_id",
                extra={"session_id": session_id, "experiment_id": experiment_id},
            )

    def get_experiment_id(self, session_id: str) -> Optional[str]:
        """Get the MLflow experiment ID for a session.

        Args:
            session_id: Session to get experiment for

        Returns:
            Experiment ID or None if not set
        """
        with get_db_session() as db:
            session = self._get_session_or_raise(db, session_id)
            return session.experiment_id

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
        modified_by: Optional[str] = None,
        expected_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Save or update slide deck for a session.

        For contributor sessions, writes to the parent's slide deck.

        When *modified_by* is provided, any slide in *deck_dict* that is
        missing ``created_by`` will be stamped with creation metadata
        automatically.

        Args:
            session_id: Session to save deck for
            title: Deck title
            html_content: Full HTML content (knitted)
            scripts_content: JavaScript content
            slide_count: Number of slides
            deck_dict: Full SlideDeck structure for restoration
            modified_by: Username to stamp on slides missing authorship
            expected_version: If provided, reject write when the current
                DB version doesn't match (optimistic locking). Raises
                ``VersionConflictError`` on mismatch.

        Returns:
            Slide deck info dictionary

        Raises:
            VersionConflictError: If expected_version doesn't match current version
        """
        # Auto-stamp creation metadata on slides that have none yet
        if deck_dict and modified_by:
            now = datetime.utcnow().isoformat() + "Z"
            for slide in deck_dict.get("slides", []):
                if not slide.get("created_by"):
                    slide["created_by"] = modified_by
                    slide["created_at"] = now
                    slide["modified_by"] = modified_by
                    slide["modified_at"] = now

        with get_db_session() as db:
            session = self._get_session_or_raise(db, session_id)
            deck_owner = self._get_deck_owner_session(db, session)

            # Serialize deck structure to JSON
            deck_json = json.dumps(deck_dict) if deck_dict else None

            if deck_owner.slide_deck:
                # Update existing
                deck = deck_owner.slide_deck

                # Optimistic locking: reject stale writes
                if expected_version is not None and deck.version != expected_version:
                    raise VersionConflictError(
                        current_version=deck.version,
                        expected_version=expected_version,
                    )

                deck.title = title
                deck.html_content = html_content
                deck.scripts_content = scripts_content
                deck.slide_count = slide_count
                deck.deck_json = deck_json
                deck.version += 1
                if modified_by:
                    deck.modified_by = modified_by
            else:
                # Create new
                deck = SessionSlideDeck(
                    session_id=deck_owner.id,
                    title=title,
                    html_content=html_content,
                    scripts_content=scripts_content,
                    slide_count=slide_count,
                    deck_json=deck_json,
                    version=1,
                )
                db.add(deck)
                db.flush()

            # Update activity on both the requesting session and the deck owner
            session.last_activity = datetime.utcnow()
            if session.id != deck_owner.id:
                deck_owner.last_activity = datetime.utcnow()

            logger.info(
                "Saved slide deck",
                extra={
                    "session_id": session_id,
                    "deck_owner_session_id": deck_owner.session_id,
                    "slide_count": slide_count,
                    "version": deck.version,
                },
            )

            return {
                "session_id": session_id,
                "title": deck.title,
                "slide_count": deck.slide_count,
                "updated_at": deck.updated_at.isoformat(),
                "version": deck.version,
            }

    def get_slide_deck(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get slide deck for a session with verification merged by content hash.

        For contributor sessions, follows parent_session_id to read the
        shared slide deck from the owner's session.

        Args:
            session_id: Session to get deck for

        Returns:
            Full SlideDeck dictionary (with slides array and verification) or None
        """
        from src.utils.slide_hash import compute_slide_hash
        
        with get_db_session() as db:
            session = self._get_session_or_raise(db, session_id)
            deck_owner = self._get_deck_owner_session(db, session)

            if not deck_owner.slide_deck:
                return None

            deck = deck_owner.slide_deck
            
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
                
                # Backfill missing per-slide authorship from the deck owner
                fallback_user = deck_owner.created_by
                needs_persist = False
                created_at_fallback = deck.created_at.isoformat() + "Z" if deck.created_at else None

                # Merge verification and backfill metadata
                for slide in deck_dict.get("slides", []):
                    if slide.get("html"):
                        content_hash = compute_slide_hash(slide["html"])
                        slide["verification"] = verification_map.get(content_hash)
                        slide["content_hash"] = content_hash

                    if not slide.get("created_by") and fallback_user:
                        slide["created_by"] = fallback_user
                        slide["created_at"] = slide.get("created_at") or created_at_fallback
                        slide["modified_by"] = slide.get("modified_by") or fallback_user
                        slide["modified_at"] = slide.get("modified_at") or created_at_fallback
                        needs_persist = True

                # Persist backfilled metadata so this is a one-time migration
                if needs_persist:
                    try:
                        deck.deck_json = json.dumps(deck_dict)
                    except Exception:
                        pass

                # Deck-level authorship metadata
                deck_dict["created_by"] = deck_owner.created_by
                deck_dict["created_at"] = deck.created_at.isoformat() + "Z" if deck.created_at else None
                deck_dict["modified_by"] = deck.modified_by or deck_owner.created_by
                deck_dict["modified_at"] = deck.updated_at.isoformat() + "Z" if deck.updated_at else None
                deck_dict["version"] = deck.version
                
                return deck_dict
            
            # Legacy: return basic info without slides array
            return {
                "title": deck.title,
                "html_content": deck.html_content,
                "scripts_content": deck.scripts_content,
                "slide_count": deck.slide_count,
                "created_by": deck_owner.created_by,
                "created_at": deck.created_at.isoformat() + "Z" if deck.created_at else None,
                "modified_by": deck.modified_by or deck_owner.created_by,
                "modified_at": deck.updated_at.isoformat() + "Z" if deck.updated_at else None,
                "version": deck.version,
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
            deck_owner = self._get_deck_owner_session(db, session)

            if not deck_owner.slide_deck:
                logger.warning(f"No slide deck for session {session_id}, cannot save verification")
                return

            deck = deck_owner.slide_deck
            
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
            deck_owner = self._get_deck_owner_session(db, session)

            if not deck_owner.slide_deck or not deck_owner.slide_deck.verification_map:
                return {}

            try:
                return json.loads(deck_owner.slide_deck.verification_map)
            except json.JSONDecodeError:
                logger.warning(f"Invalid verification_map JSON for session {session_id}")
                return {}

    # Version/Save Point operations
    VERSION_LIMIT = 40  # Maximum save points per session

    def create_version(
        self,
        session_id: str,
        description: str,
        deck_dict: Dict[str, Any],
        verification_map: Optional[Dict[str, Any]] = None,
        chat_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Create a new save point (version) for the slide deck.

        If version limit is exceeded, the oldest version is deleted.
        Version numbers are never reused - they continue incrementing.

        Args:
            session_id: Session to create version for
            description: Auto-generated description of the change
            deck_dict: Complete deck snapshot
            verification_map: Verification results at time of snapshot
            chat_history: Chat messages up to this point (auto-captured if not provided)

        Returns:
            Version info dictionary
        """
        with get_db_session() as db:
            session = self._get_session_or_raise(db, session_id)
            deck_owner = self._get_deck_owner_session(db, session)

            # Get the next version number
            max_version = (
                db.query(SlideDeckVersion.version_number)
                .filter(SlideDeckVersion.session_id == deck_owner.id)
                .order_by(SlideDeckVersion.version_number.desc())
                .first()
            )
            next_version = (max_version[0] + 1) if max_version else 1

            # Check version limit and delete oldest if needed
            version_count = (
                db.query(SlideDeckVersion)
                .filter(SlideDeckVersion.session_id == deck_owner.id)
                .count()
            )
            if version_count >= self.VERSION_LIMIT:
                # Delete the oldest version
                oldest = (
                    db.query(SlideDeckVersion)
                    .filter(SlideDeckVersion.session_id == deck_owner.id)
                    .order_by(SlideDeckVersion.version_number.asc())
                    .first()
                )
                if oldest:
                    db.delete(oldest)
                    logger.info(
                        "Deleted oldest version due to limit",
                        extra={
                            "session_id": session_id,
                            "deleted_version": oldest.version_number,
                        },
                    )

            # Capture chat history from the requesting session (private to them)
            if chat_history is None:
                chat_history = [
                    {
                        "id": m.id,
                        "role": m.role,
                        "content": m.content,
                        "message_type": m.message_type,
                        "created_at": m.created_at.isoformat(),
                    }
                    for m in session.messages
                ]

            # Create new version on the deck owner's session
            version = SlideDeckVersion(
                session_id=deck_owner.id,
                version_number=next_version,
                description=description,
                deck_json=json.dumps(deck_dict),
                verification_map_json=json.dumps(verification_map) if verification_map else None,
                chat_history_json=json.dumps(chat_history) if chat_history else None,
            )
            db.add(version)
            db.flush()

            logger.info(
                "Created save point",
                extra={
                    "session_id": session_id,
                    "version_number": next_version,
                    "description": description,
                    "message_count": len(chat_history) if chat_history else 0,
                },
            )

            return {
                "version_number": version.version_number,
                "description": version.description,
                "created_at": version.created_at.isoformat(),
                "slide_count": deck_dict.get("slide_count", len(deck_dict.get("slides", []))),
                "message_count": len(chat_history) if chat_history else 0,
            }

    def update_version_verification(
        self,
        session_id: str,
        version_number: int,
        verification_map: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Update the verification_map on an existing save point.

        Called after auto-verification completes to backfill results onto
        a save point that was created before verification ran.

        Args:
            session_id: Session that owns the version
            version_number: Version to update
            verification_map: New verification results to store

        Returns:
            Updated version info

        Raises:
            SessionNotFoundError: If session doesn't exist
            ValueError: If version not found
        """
        with get_db_session() as db:
            session = self._get_session_or_raise(db, session_id)
            deck_owner = self._get_deck_owner_session(db, session)

            version = (
                db.query(SlideDeckVersion)
                .filter(
                    SlideDeckVersion.session_id == deck_owner.id,
                    SlideDeckVersion.version_number == version_number,
                )
                .first()
            )

            if not version:
                raise ValueError(f"Version {version_number} not found")

            version.verification_map_json = json.dumps(verification_map)
            db.flush()

            logger.info(
                "Updated verification on save point",
                extra={
                    "session_id": session_id,
                    "version_number": version_number,
                    "verification_entries": len(verification_map),
                },
            )

            return {
                "version_number": version.version_number,
                "description": version.description,
                "verification_entries": len(verification_map),
            }

    def list_versions(self, session_id: str) -> List[Dict[str, Any]]:
        """List all save points for a session's slide deck.

        For contributor sessions, returns the parent's versions.

        Args:
            session_id: Session to list versions for

        Returns:
            List of version info dictionaries (newest first)
        """
        with get_db_session() as db:
            session = self._get_session_or_raise(db, session_id)
            deck_owner = self._get_deck_owner_session(db, session)

            versions = (
                db.query(SlideDeckVersion)
                .filter(SlideDeckVersion.session_id == deck_owner.id)
                .order_by(SlideDeckVersion.version_number.desc())
                .all()
            )

            result = []
            for v in versions:
                deck_dict = json.loads(v.deck_json) if v.deck_json else {}
                result.append({
                    "version_number": v.version_number,
                    "description": v.description,
                    "created_at": v.created_at.isoformat(),
                    "slide_count": deck_dict.get("slide_count", len(deck_dict.get("slides", []))),
                })

            return result

    def get_version(self, session_id: str, version_number: int) -> Optional[Dict[str, Any]]:
        """Get a specific version for preview.

        For contributor sessions, reads from the parent's versions.

        Args:
            session_id: Session to get version from
            version_number: Version number to retrieve

        Returns:
            Version data including full deck snapshot, or None if not found
        """
        with get_db_session() as db:
            session = self._get_session_or_raise(db, session_id)
            deck_owner = self._get_deck_owner_session(db, session)

            version = (
                db.query(SlideDeckVersion)
                .filter(
                    SlideDeckVersion.session_id == deck_owner.id,
                    SlideDeckVersion.version_number == version_number,
                )
                .first()
            )

            if not version:
                return None

            deck_dict = json.loads(version.deck_json) if version.deck_json else {}
            verification_map = (
                json.loads(version.verification_map_json)
                if version.verification_map_json
                else {}
            )

            # Merge verification into slides by content hash
            from src.utils.slide_hash import compute_slide_hash

            for slide in deck_dict.get("slides", []):
                if slide.get("html"):
                    content_hash = compute_slide_hash(slide["html"])
                    slide["verification"] = verification_map.get(content_hash)
                    slide["content_hash"] = content_hash

            # Substitute {{image:ID}} placeholders with base64 for client
            from src.utils.image_utils import substitute_deck_dict_images

            substitute_deck_dict_images(deck_dict, db)

            # Parse chat history for preview
            chat_history = (
                json.loads(version.chat_history_json)
                if version.chat_history_json
                else []
            )

            return {
                "version_number": version.version_number,
                "description": version.description,
                "created_at": version.created_at.isoformat(),
                "deck": deck_dict,
                "verification_map": verification_map,
                "chat_history": chat_history,
            }

    def restore_version(self, session_id: str, version_number: int) -> Dict[str, Any]:
        """Restore deck to a specific version and delete all newer versions.

        For contributor sessions, operates on the parent's versions and deck.

        Args:
            session_id: Session to restore
            version_number: Version to restore to

        Returns:
            Restored deck dictionary

        Raises:
            ValueError: If version not found
        """
        with get_db_session() as db:
            session = self._get_session_or_raise(db, session_id)
            deck_owner = self._get_deck_owner_session(db, session)

            # Get the version to restore
            version = (
                db.query(SlideDeckVersion)
                .filter(
                    SlideDeckVersion.session_id == deck_owner.id,
                    SlideDeckVersion.version_number == version_number,
                )
                .first()
            )

            if not version:
                raise ValueError(f"Version {version_number} not found")

            # Delete all versions newer than the restored one
            deleted_count = (
                db.query(SlideDeckVersion)
                .filter(
                    SlideDeckVersion.session_id == deck_owner.id,
                    SlideDeckVersion.version_number > version_number,
                )
                .delete()
            )

            # Parse the deck data
            deck_dict = json.loads(version.deck_json) if version.deck_json else {}
            verification_map = (
                json.loads(version.verification_map_json)
                if version.verification_map_json
                else {}
            )
            chat_history = (
                json.loads(version.chat_history_json)
                if version.chat_history_json
                else []
            )

            # Merge verification into slides by content hash
            from src.utils.slide_hash import compute_slide_hash

            for slide in deck_dict.get("slides", []):
                if slide.get("html"):
                    content_hash = compute_slide_hash(slide["html"])
                    slide["verification"] = verification_map.get(content_hash)
                    slide["content_hash"] = content_hash

            # Delete messages created after this save point
            deleted_messages = 0
            if version.created_at:
                deleted_messages = (
                    db.query(SessionMessage)
                    .filter(
                        SessionMessage.session_id == session.id,
                        SessionMessage.created_at > version.created_at,
                    )
                    .delete()
                )

            # Update the current slide deck in database (use deck_owner for
            # contributor sessions whose own slide_deck is None)
            if deck_owner.slide_deck:
                deck_owner.slide_deck.deck_json = version.deck_json
                deck_owner.slide_deck.verification_map = version.verification_map_json
                deck_owner.slide_deck.title = deck_dict.get("title")
                deck_owner.slide_deck.slide_count = len(deck_dict.get("slides", []))
                deck_owner.slide_deck.updated_at = datetime.utcnow()

            logger.info(
                "Restored to save point",
                extra={
                    "session_id": session_id,
                    "version_number": version_number,
                    "deleted_newer_versions": deleted_count,
                    "deleted_messages": deleted_messages,
                },
            )

            return {
                "version_number": version_number,
                "description": version.description,
                "deck": deck_dict,
                "verification_map": verification_map,
                "chat_history": chat_history,
                "deleted_versions": deleted_count,
                "deleted_messages": deleted_messages,
            }

    def get_current_version_number(self, session_id: str) -> Optional[int]:
        """Get the current (latest) version number for a session's slide deck.

        For contributor sessions, returns the parent's latest version.

        Args:
            session_id: Session to check

        Returns:
            Latest version number or None if no versions exist
        """
        with get_db_session() as db:
            session = self._get_session_or_raise(db, session_id)
            deck_owner = self._get_deck_owner_session(db, session)

            max_version = (
                db.query(SlideDeckVersion.version_number)
                .filter(SlideDeckVersion.session_id == deck_owner.id)
                .order_by(SlideDeckVersion.version_number.desc())
                .first()
            )

            return max_version[0] if max_version else None

    # ------------------------------------------------------------------
    # Session editing lock — first user to open a shared session gets
    # exclusive editing rights. Others see a "locked by X" banner.
    # The lock auto-expires if the holder stops sending heartbeats.
    # ------------------------------------------------------------------
    EDITING_LOCK_TIMEOUT_SECONDS = 600  # 10 minutes without heartbeat

    def acquire_editing_lock(self, session_id: str, user: str) -> dict:
        """Try to acquire the editing lock when opening a session.

        Returns a dict with {"acquired": bool, "locked_by": str|None}.
        If another user holds a non-expired lock, acquisition fails.
        If the same user re-acquires, the lock is refreshed.
        """
        with get_db_session() as db:
            session = self._get_session_or_raise(db, session_id)
            deck_owner = self._get_deck_owner_session(db, session)

            if not deck_owner.slide_deck:
                return {"acquired": True, "locked_by": None}

            deck = deck_owner.slide_deck
            now = datetime.utcnow()

            if deck.locked_by and deck.locked_by != user:
                if deck.locked_at:
                    age = (now - deck.locked_at).total_seconds()
                    if age < self.EDITING_LOCK_TIMEOUT_SECONDS:
                        return {"acquired": False, "locked_by": deck.locked_by}
                # Stale lock — take it over

            deck.locked_by = user
            deck.locked_at = now
            logger.info("Editing lock acquired", extra={"session_id": session_id, "user": user})
            return {"acquired": True, "locked_by": user}

    def release_editing_lock(self, session_id: str, user: str) -> None:
        """Release the editing lock (called on session close / navigation away)."""
        with get_db_session() as db:
            session = (
                db.query(UserSession)
                .filter(UserSession.session_id == session_id)
                .first()
            )
            if not session:
                return

            deck_owner = self._get_deck_owner_session(db, session)
            if not deck_owner.slide_deck:
                return

            deck = deck_owner.slide_deck
            if deck.locked_by == user or deck.locked_by is None:
                deck.locked_by = None
                deck.locked_at = None
                logger.info("Editing lock released", extra={"session_id": session_id, "user": user})

    def heartbeat_editing_lock(self, session_id: str, user: str) -> bool:
        """Renew the lock timestamp. Returns False if user no longer holds the lock."""
        with get_db_session() as db:
            session = (
                db.query(UserSession)
                .filter(UserSession.session_id == session_id)
                .first()
            )
            if not session:
                return False

            deck_owner = self._get_deck_owner_session(db, session)
            if not deck_owner.slide_deck:
                return False

            deck = deck_owner.slide_deck
            if deck.locked_by != user:
                return False

            deck.locked_at = datetime.utcnow()
            return True

    def get_editing_lock_status(self, session_id: str) -> dict:
        """Check who holds the editing lock.

        Returns {"locked": bool, "locked_by": str|None}.
        """
        with get_db_session() as db:
            session = (
                db.query(UserSession)
                .filter(UserSession.session_id == session_id)
                .first()
            )
            if not session:
                return {"locked": False, "locked_by": None}

            deck_owner = self._get_deck_owner_session(db, session)
            if not deck_owner.slide_deck:
                return {"locked": False, "locked_by": None}

            deck = deck_owner.slide_deck
            if not deck.locked_by:
                return {"locked": False, "locked_by": None}

            if deck.locked_at:
                age = (datetime.utcnow() - deck.locked_at).total_seconds()
                if age >= self.EDITING_LOCK_TIMEOUT_SECONDS:
                    # Expired — clear it
                    deck.locked_by = None
                    deck.locked_at = None
                    return {"locked": False, "locked_by": None}

            return {"locked": True, "locked_by": deck.locked_by}

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

    @staticmethod
    def _is_profile_deleted(db: Session, profile_id: Optional[int]) -> bool:
        """Check if a profile has been soft-deleted or no longer exists."""
        if profile_id is None:
            return False
        from src.database.models import ConfigProfile
        profile = db.query(ConfigProfile).filter_by(id=profile_id).first()
        if profile is None:
            return True
        return bool(profile.is_deleted)

    @staticmethod
    def _get_deleted_profile_ids(db: Session, profile_ids: List[int]) -> set:
        """Return the subset of profile_ids that are deleted or missing."""
        if not profile_ids:
            return set()
        from src.database.models import ConfigProfile
        unique_ids = set(profile_ids)
        active_profiles = (
            db.query(ConfigProfile.id)
            .filter(
                ConfigProfile.id.in_(unique_ids),
                ConfigProfile.is_deleted == False,  # noqa: E712
            )
            .all()
        )
        active_ids = {row[0] for row in active_profiles}
        return unique_ids - active_ids

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

    # ================================================================
    # Slide Comments
    # ================================================================

    def add_comment(
        self,
        session_id: str,
        slide_id: str,
        user_name: str,
        content: str,
        parent_comment_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Add a comment on a slide.

        Comments are stored against the *deck owner* session so all
        contributors see them.
        """
        with get_db_session() as db:
            session = self._get_session_or_raise(db, session_id)
            deck_owner = self._get_deck_owner_session(db, session)

            if parent_comment_id is not None:
                parent = db.query(SlideComment).filter(
                    SlideComment.id == parent_comment_id,
                    SlideComment.session_id == deck_owner.id,
                ).first()
                if not parent:
                    raise ValueError("Parent comment not found")

            import re
            mentioned = re.findall(r"@([\w.\-]+(?:@[\w.\-]+)?)", content)
            mentioned = list(dict.fromkeys(mentioned))  # dedupe, preserve order

            comment = SlideComment(
                session_id=deck_owner.id,
                slide_id=slide_id,
                user_name=user_name,
                content=content,
                mentions=mentioned or None,
                parent_comment_id=parent_comment_id,
            )
            db.add(comment)
            db.flush()

            logger.info(
                "Added slide comment",
                extra={
                    "comment_id": comment.id,
                    "session_id": session_id,
                    "slide_id": slide_id,
                    "user": user_name,
                },
            )
            return self._comment_to_dict(comment)

    def list_comments(
        self,
        session_id: str,
        slide_id: Optional[str] = None,
        include_resolved: bool = False,
    ) -> List[Dict[str, Any]]:
        """List comments for a presentation (optionally filtered by slide).

        Only top-level comments are returned; replies are nested inside.
        """
        with get_db_session() as db:
            session = self._get_session_or_raise(db, session_id)
            deck_owner = self._get_deck_owner_session(db, session)

            query = db.query(SlideComment).filter(
                SlideComment.session_id == deck_owner.id,
                SlideComment.parent_comment_id.is_(None),
            )
            if slide_id:
                query = query.filter(SlideComment.slide_id == slide_id)
            if not include_resolved:
                query = query.filter(SlideComment.resolved.is_(False))

            comments = query.order_by(SlideComment.created_at.asc()).all()
            return [self._comment_to_dict(c, include_replies=True) for c in comments]

    def update_comment(
        self, comment_id: int, user_name: str, content: str
    ) -> Dict[str, Any]:
        """Edit a comment (only by the author)."""
        import re

        with get_db_session() as db:
            comment = db.query(SlideComment).filter(SlideComment.id == comment_id).first()
            if not comment:
                raise ValueError("Comment not found")
            if comment.user_name != user_name:
                raise PermissionError("Only the author can edit a comment")
            comment.content = content
            mentioned = re.findall(r"@([\w.\-]+(?:@[\w.\-]+)?)", content)
            comment.mentions = list(dict.fromkeys(mentioned)) or None
            db.flush()
            return self._comment_to_dict(comment)

    def delete_comment(self, comment_id: int, user_name: str, is_manager: bool = False) -> bool:
        """Delete a comment. Authors can always delete their own; managers can delete any."""
        with get_db_session() as db:
            comment = db.query(SlideComment).filter(SlideComment.id == comment_id).first()
            if not comment:
                raise ValueError("Comment not found")
            if comment.user_name != user_name and not is_manager:
                raise PermissionError("Only the author or a manager can delete this comment")
            db.delete(comment)
            return True

    def resolve_comment(
        self, comment_id: int, resolved_by: str
    ) -> Dict[str, Any]:
        """Mark a comment (and its replies) as resolved."""
        with get_db_session() as db:
            comment = db.query(SlideComment).filter(SlideComment.id == comment_id).first()
            if not comment:
                raise ValueError("Comment not found")
            comment.resolved = True
            comment.resolved_by = resolved_by
            comment.resolved_at = datetime.utcnow()
            db.flush()
            return self._comment_to_dict(comment)

    def unresolve_comment(self, comment_id: int) -> Dict[str, Any]:
        """Re-open a resolved comment."""
        with get_db_session() as db:
            comment = db.query(SlideComment).filter(SlideComment.id == comment_id).first()
            if not comment:
                raise ValueError("Comment not found")
            comment.resolved = False
            comment.resolved_by = None
            comment.resolved_at = None
            db.flush()
            return self._comment_to_dict(comment)

    @staticmethod
    def _comment_to_dict(
        comment: SlideComment, include_replies: bool = False
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "id": comment.id,
            "slide_id": comment.slide_id,
            "user_name": comment.user_name,
            "content": comment.content,
            "mentions": comment.mentions or [],
            "resolved": comment.resolved,
            "resolved_by": comment.resolved_by,
            "resolved_at": comment.resolved_at.isoformat() if comment.resolved_at else None,
            "parent_comment_id": comment.parent_comment_id,
            "created_at": comment.created_at.isoformat(),
            "updated_at": comment.updated_at.isoformat(),
        }
        if include_replies and comment.replies:
            result["replies"] = [
                SessionManager._comment_to_dict(r) for r in comment.replies
            ]
        else:
            result["replies"] = []
        return result

    def list_mentions(self, user_name: str) -> List[Dict[str, Any]]:
        """List comments that @mention a specific user, newest first.

        Uses JSONB containment on PostgreSQL, LIKE fallback on SQLite.
        Always double-checks in Python to avoid false positives.
        """
        with get_db_session() as db:
            try:
                is_sqlite = "sqlite" in str(db.bind.url)
            except Exception:
                is_sqlite = False

            if is_sqlite:
                comments = (
                    db.query(SlideComment)
                    .filter(SlideComment.mentions.isnot(None))
                    .filter(SlideComment.content.contains(f"@{user_name}"))
                    .order_by(SlideComment.created_at.desc())
                    .limit(100)
                    .all()
                )
            else:
                from sqlalchemy import text as sa_text
                comments = (
                    db.query(SlideComment)
                    .filter(SlideComment.mentions.isnot(None))
                    .filter(sa_text(
                        "mentions::jsonb @> :target"
                    ).bindparams(target=f'["{user_name}"]'))
                    .order_by(SlideComment.created_at.desc())
                    .limit(100)
                    .all()
                )

            results = []
            for c in comments:
                mentions_list = c.mentions if isinstance(c.mentions, list) else []
                if user_name in mentions_list:
                    d = self._comment_to_dict(c)
                    d["session_id_str"] = self._get_session_id_str(db, c.session_id)
                    results.append(d)
            return results

    def get_mentionable_users(self, session_id: str) -> List[str]:
        """Return usernames that can be @mentioned for a session.

        Includes the session owner and all contributors of the profile
        the session belongs to.
        """
        from src.database.models.profile_contributor import ConfigProfileContributor

        with get_db_session() as db:
            session = self._get_session_or_raise(db, session_id)
            deck_owner = self._get_deck_owner_session(db, session)

            users: set[str] = set()
            if deck_owner.created_by:
                users.add(deck_owner.created_by)

            if deck_owner.profile_id:
                contributors = (
                    db.query(ConfigProfileContributor.identity_name)
                    .filter(ConfigProfileContributor.profile_id == deck_owner.profile_id)
                    .all()
                )
                for (name,) in contributors:
                    if name:
                        users.add(name)

            return sorted(users)

    def _get_session_id_str(self, db, internal_id: int) -> Optional[str]:
        """Resolve internal DB id to the external session_id string."""
        from src.database.models.session import UserSession
        sess = db.query(UserSession.session_id).filter(UserSession.id == internal_id).first()
        return sess[0] if sess else None


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

