"""Permission service for checking user access to profiles, decks, and related resources.

This service provides centralized permission checking logic for:
- Profile access (use, edit, manage)
- Deck access (view, edit, manage) via DeckContributor
- Session access (based on deck or profile permissions)

Permission hierarchy: CAN_MANAGE > CAN_EDIT > CAN_VIEW = CAN_USE

Users can have permissions through:
1. Direct USER-type contributor entry (by identity_id)
2. Fallback USER-type contributor entry (by identity_name)
3. GROUP-type contributor entry (if user is member of that group)
4. Being the creator (implicit CAN_MANAGE)
"""

import logging
from typing import List, Optional, Set, Tuple

from fastapi import HTTPException, status
from sqlalchemy import or_, and_
from sqlalchemy.orm import Session

from src.core.permission_context import get_permission_context, PermissionContext
from src.database.models import ConfigProfile, ConfigProfileContributor
from src.database.models.deck_contributor import DeckContributor
from src.database.models.profile_contributor import PermissionLevel
from src.database.models.session import UserSession

logger = logging.getLogger(__name__)


# Permission level priority (higher = more permissions)
PERMISSION_PRIORITY = {
    PermissionLevel.CAN_USE: 1,
    PermissionLevel.CAN_VIEW: 1,
    PermissionLevel.CAN_EDIT: 2,
    PermissionLevel.CAN_MANAGE: 3,
}


class PermissionService:
    """Stateless service for checking user permissions on profiles and decks."""

    # ------------------------------------------------------------------
    # Profile permission methods (renamed from original)
    # ------------------------------------------------------------------

    def get_profile_permission(
        self,
        db: Session,
        profile_id: int,
        user_id: Optional[str] = None,
        user_name: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> Optional[PermissionLevel]:
        """
        Get the user's permission level on a profile.

        Checks both direct user access and group-based access.
        Returns the highest permission level found.

        Args:
            db: Database session
            profile_id: Profile to check
            user_id: Databricks user ID (from permission context)
            user_name: Username/email (for fallback matching and creator check)
            group_ids: List of group IDs the user belongs to

        Returns:
            PermissionLevel or None if no access
        """
        # Get profile to check creator
        profile = db.query(ConfigProfile).filter(
            ConfigProfile.id == profile_id
        ).first()

        if not profile:
            return None

        if profile.is_deleted:
            return None

        permissions_found: List[PermissionLevel] = []

        # Check 1: Is user the profile creator? (implicit CAN_MANAGE)
        if user_name and profile.created_by == user_name:
            logger.debug(f"User {user_name} is creator of profile {profile_id}")
            permissions_found.append(PermissionLevel.CAN_MANAGE)

        # Check 2: Direct user permission (by user_id)
        if user_id:
            direct_match = db.query(ConfigProfileContributor).filter(
                ConfigProfileContributor.profile_id == profile_id,
                ConfigProfileContributor.identity_type == "USER",
                ConfigProfileContributor.identity_id == user_id,
            ).first()

            if direct_match:
                logger.debug(f"Found direct permission for user {user_id} on profile {profile_id}: {direct_match.permission_level}")
                permissions_found.append(PermissionLevel(direct_match.permission_level))

        # Check 3: Fallback - Direct user permission (by username/email)
        # This handles cases where identity_name was stored as email
        if user_name and not permissions_found:
            name_match = db.query(ConfigProfileContributor).filter(
                ConfigProfileContributor.profile_id == profile_id,
                ConfigProfileContributor.identity_type == "USER",
                ConfigProfileContributor.identity_name == user_name,
            ).first()

            if name_match:
                logger.debug(f"Found permission by name for {user_name} on profile {profile_id}: {name_match.permission_level}")
                permissions_found.append(PermissionLevel(name_match.permission_level))

        # Check 4: Group-based permission
        if group_ids:
            group_matches = db.query(ConfigProfileContributor).filter(
                ConfigProfileContributor.profile_id == profile_id,
                ConfigProfileContributor.identity_type == "GROUP",
                ConfigProfileContributor.identity_id.in_(group_ids),
            ).all()

            for match in group_matches:
                logger.debug(f"Found group permission on profile {profile_id}: {match.identity_name} -> {match.permission_level}")
                permissions_found.append(PermissionLevel(match.permission_level))

        if not permissions_found:
            if profile.global_permission:
                return PermissionLevel(profile.global_permission)
            return None

        # Return highest permission found
        return max(permissions_found, key=lambda p: PERMISSION_PRIORITY[p])

    def get_current_user_profile_permission(self, db: Session, profile_id: int) -> Optional[PermissionLevel]:
        """
        Get the current request user's permission on a profile.

        Uses the permission context from the current request.

        Args:
            db: Database session
            profile_id: Profile to check

        Returns:
            PermissionLevel or None if no access
        """
        ctx = get_permission_context()
        if not ctx:
            logger.warning("No permission context available")
            return None

        return self.get_profile_permission(
            db=db,
            profile_id=profile_id,
            user_id=ctx.user_id,
            user_name=ctx.user_name,
            group_ids=ctx.group_ids,
        )

    def can_use_profile(self, db: Session, profile_id: int) -> bool:
        """Check if current user can use a profile (CAN_USE/CAN_VIEW or higher)."""
        perm = self.get_current_user_profile_permission(db, profile_id)
        return perm is not None

    def can_edit_profile(self, db: Session, profile_id: int) -> bool:
        """Check if current user can edit a profile (CAN_EDIT or higher)."""
        perm = self.get_current_user_profile_permission(db, profile_id)
        if not perm:
            return False
        return PERMISSION_PRIORITY[perm] >= PERMISSION_PRIORITY[PermissionLevel.CAN_EDIT]

    def can_manage_profile(self, db: Session, profile_id: int) -> bool:
        """Check if current user can manage a profile (CAN_MANAGE only)."""
        perm = self.get_current_user_profile_permission(db, profile_id)
        if not perm:
            return False
        return perm == PermissionLevel.CAN_MANAGE

    def require_use_profile(self, db: Session, profile_id: int) -> None:
        """Require CAN_USE/CAN_VIEW permission or raise 403."""
        if not self.can_use_profile(db, profile_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to view this profile",
            )

    def require_edit_profile(self, db: Session, profile_id: int) -> None:
        """Require CAN_EDIT permission or raise 403."""
        if not self.can_edit_profile(db, profile_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to edit this profile",
            )

    def require_manage_profile(self, db: Session, profile_id: int) -> None:
        """Require CAN_MANAGE permission or raise 403."""
        if not self.can_manage_profile(db, profile_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to manage this profile",
            )

    # ------------------------------------------------------------------
    # Deck permission methods (new)
    # ------------------------------------------------------------------

    def get_deck_permission(
        self,
        db: Session,
        session_id: int,
        user_id: Optional[str] = None,
        user_name: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> Optional[PermissionLevel]:
        """
        Get the user's permission level on a deck (UserSession).

        Resolution order:
        1. Creator check — session.created_by == user_name → CAN_MANAGE
        2. Direct user by identity_id
        3. Fallback by identity_name
        4. Group matches (highest wins)
        5. None

        Args:
            db: Database session
            session_id: UserSession.id (integer PK)
            user_id: Databricks user ID
            user_name: Username/email
            group_ids: List of group IDs the user belongs to

        Returns:
            PermissionLevel or None if no access
        """
        session = db.query(UserSession).filter(UserSession.id == session_id).first()
        if not session:
            return None

        permissions_found: List[PermissionLevel] = []

        # Check 1: Is user the session creator? (implicit CAN_MANAGE)
        if user_name and session.created_by == user_name:
            logger.debug(f"User {user_name} is creator of session {session_id}")
            permissions_found.append(PermissionLevel.CAN_MANAGE)

        # Check 2: Direct user permission (by identity_id)
        if user_id:
            direct_match = db.query(DeckContributor).filter(
                DeckContributor.user_session_id == session_id,
                DeckContributor.identity_type == "USER",
                DeckContributor.identity_id == user_id,
            ).first()

            if direct_match:
                logger.debug(f"Found direct deck permission for user {user_id} on session {session_id}: {direct_match.permission_level}")
                permissions_found.append(PermissionLevel(direct_match.permission_level))

        # Check 3: Fallback - Direct user permission (by identity_name)
        if user_name and not permissions_found:
            name_match = db.query(DeckContributor).filter(
                DeckContributor.user_session_id == session_id,
                DeckContributor.identity_type == "USER",
                DeckContributor.identity_name == user_name,
            ).first()

            if name_match:
                logger.debug(f"Found deck permission by name for {user_name} on session {session_id}: {name_match.permission_level}")
                permissions_found.append(PermissionLevel(name_match.permission_level))

        # Check 4: Group-based permission
        if group_ids:
            group_matches = db.query(DeckContributor).filter(
                DeckContributor.user_session_id == session_id,
                DeckContributor.identity_type == "GROUP",
                DeckContributor.identity_id.in_(group_ids),
            ).all()

            for match in group_matches:
                logger.debug(f"Found group deck permission on session {session_id}: {match.identity_name} -> {match.permission_level}")
                permissions_found.append(PermissionLevel(match.permission_level))

        if not permissions_found:
            return None

        # Return highest permission found
        return max(permissions_found, key=lambda p: PERMISSION_PRIORITY[p])

    def can_view_deck(
        self, db: Session, session_id: int,
        user_id: Optional[str] = None, user_name: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> bool:
        """Check if user can view a deck (any permission level)."""
        perm = self.get_deck_permission(db, session_id, user_id, user_name, group_ids)
        return perm is not None

    def can_edit_deck(
        self, db: Session, session_id: int,
        user_id: Optional[str] = None, user_name: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> bool:
        """Check if user can edit a deck (CAN_EDIT or higher)."""
        perm = self.get_deck_permission(db, session_id, user_id, user_name, group_ids)
        if not perm:
            return False
        return PERMISSION_PRIORITY[perm] >= PERMISSION_PRIORITY[PermissionLevel.CAN_EDIT]

    def can_manage_deck(
        self, db: Session, session_id: int,
        user_id: Optional[str] = None, user_name: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> bool:
        """Check if user can manage a deck (CAN_MANAGE only)."""
        perm = self.get_deck_permission(db, session_id, user_id, user_name, group_ids)
        if not perm:
            return False
        return perm == PermissionLevel.CAN_MANAGE

    def require_view_deck(
        self, db: Session, session_id: int,
        user_id: Optional[str] = None, user_name: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> None:
        """Require view permission on a deck or raise 403."""
        if not self.can_view_deck(db, session_id, user_id, user_name, group_ids):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to view this deck",
            )

    def require_edit_deck(
        self, db: Session, session_id: int,
        user_id: Optional[str] = None, user_name: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> None:
        """Require edit permission on a deck or raise 403."""
        if not self.can_edit_deck(db, session_id, user_id, user_name, group_ids):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to edit this deck",
            )

    def require_manage_deck(
        self, db: Session, session_id: int,
        user_id: Optional[str] = None, user_name: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> None:
        """Require manage permission on a deck or raise 403."""
        if not self.can_manage_deck(db, session_id, user_id, user_name, group_ids):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to manage this deck",
            )

    # ------------------------------------------------------------------
    # Shared session discovery
    # ------------------------------------------------------------------

    def get_shared_session_ids(
        self,
        db: Session,
        user_id: Optional[str] = None,
        user_name: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> Set[int]:
        """
        Return set of UserSession.id values shared with this user via deck_contributors,
        excluding sessions where the user is the creator.

        Args:
            db: Database session
            user_id: Databricks user ID
            user_name: Username/email
            group_ids: List of group IDs

        Returns:
            Set of UserSession.id (integer PKs)
        """
        shared_session_ids: Set[int] = set()

        # Direct user match by identity_id
        if user_id:
            rows = db.query(DeckContributor.user_session_id).filter(
                DeckContributor.identity_type == "USER",
                DeckContributor.identity_id == user_id,
            ).all()
            shared_session_ids.update(r.user_session_id for r in rows)

        # Fallback by identity_name
        if user_name:
            rows = db.query(DeckContributor.user_session_id).filter(
                DeckContributor.identity_type == "USER",
                DeckContributor.identity_name == user_name,
            ).all()
            shared_session_ids.update(r.user_session_id for r in rows)

        # Group matches
        if group_ids:
            rows = db.query(DeckContributor.user_session_id).filter(
                DeckContributor.identity_type == "GROUP",
                DeckContributor.identity_id.in_(group_ids),
            ).all()
            shared_session_ids.update(r.user_session_id for r in rows)

        if not shared_session_ids:
            return set()

        # Exclude sessions where user is creator
        if user_name:
            own_sessions = db.query(UserSession.id).filter(
                UserSession.id.in_(shared_session_ids),
                UserSession.created_by == user_name,
            ).all()
            own_ids = {s.id for s in own_sessions}
            shared_session_ids -= own_ids

        return shared_session_ids

    # ------------------------------------------------------------------
    # Profile list methods (signatures updated: db as first param)
    # ------------------------------------------------------------------

    def get_accessible_profile_ids(
        self,
        db: Session,
        user_id: Optional[str] = None,
        user_name: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> List[int]:
        """
        Get list of profile IDs the user has access to.

        Args:
            db: Database session
            user_id: Databricks user ID
            user_name: Username/email
            group_ids: List of group IDs

        Returns:
            List of profile IDs with any level of access
        """
        accessible_ids = set()

        # Global profiles (visible to everyone)
        global_profiles = db.query(ConfigProfile.id).filter(
            ConfigProfile.is_deleted == False,
            ConfigProfile.global_permission.isnot(None),
        ).all()
        accessible_ids.update(p.id for p in global_profiles)

        # Profiles where user is creator
        if user_name:
            creator_profiles = db.query(ConfigProfile.id).filter(
                ConfigProfile.is_deleted == False,
                ConfigProfile.created_by == user_name,
            ).all()
            accessible_ids.update(p.id for p in creator_profiles)

        # Profiles with direct user contributor entry (by user_id)
        if user_id:
            user_id_profiles = db.query(ConfigProfileContributor.profile_id).filter(
                ConfigProfileContributor.identity_type == "USER",
                ConfigProfileContributor.identity_id == user_id,
            ).all()
            accessible_ids.update(p.profile_id for p in user_id_profiles)

        # Profiles with direct user contributor entry (by username - fallback)
        if user_name:
            user_name_profiles = db.query(ConfigProfileContributor.profile_id).filter(
                ConfigProfileContributor.identity_type == "USER",
                ConfigProfileContributor.identity_name == user_name,
            ).all()
            accessible_ids.update(p.profile_id for p in user_name_profiles)

        # Profiles with group contributor entry
        if group_ids:
            group_profiles = db.query(ConfigProfileContributor.profile_id).filter(
                ConfigProfileContributor.identity_type == "GROUP",
                ConfigProfileContributor.identity_id.in_(group_ids),
            ).all()
            accessible_ids.update(p.profile_id for p in group_profiles)

        return list(accessible_ids)

    def get_current_user_accessible_profile_ids(self, db: Session) -> List[int]:
        """
        Get profile IDs accessible to the current request user.

        Uses the permission context from the current request.

        Args:
            db: Database session

        Returns:
            List of accessible profile IDs
        """
        ctx = get_permission_context()
        if not ctx:
            logger.warning("No permission context available")
            return []

        return self.get_accessible_profile_ids(
            db=db,
            user_id=ctx.user_id,
            user_name=ctx.user_name,
            group_ids=ctx.group_ids,
        )

    def get_profiles_with_permissions(
        self,
        db: Session,
        user_id: Optional[str] = None,
        user_name: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> List[Tuple[ConfigProfile, PermissionLevel]]:
        """
        Get all accessible profiles with their permission levels.

        Args:
            db: Database session
            user_id: Databricks user ID
            user_name: Username/email
            group_ids: List of group IDs

        Returns:
            List of (profile, permission_level) tuples
        """
        accessible_ids = self.get_accessible_profile_ids(db, user_id, user_name, group_ids)

        if not accessible_ids:
            return []

        profiles = db.query(ConfigProfile).filter(
            ConfigProfile.id.in_(accessible_ids),
            ConfigProfile.is_deleted == False,
        ).order_by(ConfigProfile.name).all()

        result = []
        for profile in profiles:
            perm = self.get_profile_permission(
                db=db,
                profile_id=profile.id,
                user_id=user_id,
                user_name=user_name,
                group_ids=group_ids,
            )
            if perm:
                result.append((profile, perm))

        return result


def get_permission_service() -> PermissionService:
    """Factory function to create PermissionService instance."""
    return PermissionService()
