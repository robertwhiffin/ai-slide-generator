"""Permission service for checking user access to profiles and related resources.

This service provides centralized permission checking logic for:
- Profile access (view, edit, manage)
- Session access (based on profile permissions)
- Slide operations (based on profile permissions)

Permission hierarchy: CAN_MANAGE > CAN_EDIT > CAN_VIEW

Users can have permissions through:
1. Direct USER-type contributor entry
2. GROUP-type contributor entry (if user is member of that group)
3. Being the profile creator (implicit CAN_MANAGE)
"""

import logging
from typing import List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy import or_, and_, case
from sqlalchemy.orm import Session

from src.core.permission_context import get_permission_context, PermissionContext
from src.database.models import ConfigProfile, ConfigProfileContributor
from src.database.models.profile_contributor import PermissionLevel

logger = logging.getLogger(__name__)


# Permission level priority (higher = more permissions)
PERMISSION_PRIORITY = {
    PermissionLevel.CAN_MANAGE: 3,
    PermissionLevel.CAN_EDIT: 2,
    PermissionLevel.CAN_VIEW: 1,
}


class PermissionService:
    """Service for checking user permissions on profiles and resources."""

    def __init__(self, db: Session):
        self.db = db

    def get_user_permission(
        self,
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
            profile_id: Profile to check
            user_id: Databricks user ID (from permission context)
            user_name: Username/email (for fallback matching and creator check)
            group_ids: List of group IDs the user belongs to
            
        Returns:
            PermissionLevel or None if no access
        """
        # Get profile to check creator
        profile = self.db.query(ConfigProfile).filter(
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
            direct_match = self.db.query(ConfigProfileContributor).filter(
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
            name_match = self.db.query(ConfigProfileContributor).filter(
                ConfigProfileContributor.profile_id == profile_id,
                ConfigProfileContributor.identity_type == "USER",
                ConfigProfileContributor.identity_name == user_name,
            ).first()
            
            if name_match:
                logger.debug(f"Found permission by name for {user_name} on profile {profile_id}: {name_match.permission_level}")
                permissions_found.append(PermissionLevel(name_match.permission_level))
        
        # Check 4: Group-based permission
        if group_ids:
            group_matches = self.db.query(ConfigProfileContributor).filter(
                ConfigProfileContributor.profile_id == profile_id,
                ConfigProfileContributor.identity_type == "GROUP",
                ConfigProfileContributor.identity_id.in_(group_ids),
            ).all()
            
            for match in group_matches:
                logger.debug(f"Found group permission on profile {profile_id}: {match.identity_name} -> {match.permission_level}")
                permissions_found.append(PermissionLevel(match.permission_level))
        
        if not permissions_found:
            return None
        
        # Return highest permission found
        return max(permissions_found, key=lambda p: PERMISSION_PRIORITY[p])

    def get_current_user_permission(self, profile_id: int) -> Optional[PermissionLevel]:
        """
        Get the current request user's permission on a profile.
        
        Uses the permission context from the current request.
        
        Args:
            profile_id: Profile to check
            
        Returns:
            PermissionLevel or None if no access
        """
        ctx = get_permission_context()
        if not ctx:
            logger.warning("No permission context available")
            return None
        
        return self.get_user_permission(
            profile_id=profile_id,
            user_id=ctx.user_id,
            user_name=ctx.user_name,
            group_ids=ctx.group_ids,
        )

    def can_view(self, profile_id: int) -> bool:
        """Check if current user can view a profile (CAN_VIEW or higher)."""
        perm = self.get_current_user_permission(profile_id)
        return perm is not None

    def can_edit(self, profile_id: int) -> bool:
        """Check if current user can edit a profile (CAN_EDIT or higher)."""
        perm = self.get_current_user_permission(profile_id)
        if not perm:
            return False
        return PERMISSION_PRIORITY[perm] >= PERMISSION_PRIORITY[PermissionLevel.CAN_EDIT]

    def can_manage(self, profile_id: int) -> bool:
        """Check if current user can manage a profile (CAN_MANAGE only)."""
        perm = self.get_current_user_permission(profile_id)
        if not perm:
            return False
        return perm == PermissionLevel.CAN_MANAGE

    def require_view(self, profile_id: int) -> None:
        """Require CAN_VIEW permission or raise 403."""
        if not self.can_view(profile_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to view this profile",
            )

    def require_edit(self, profile_id: int) -> None:
        """Require CAN_EDIT permission or raise 403."""
        if not self.can_edit(profile_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to edit this profile",
            )

    def require_manage(self, profile_id: int) -> None:
        """Require CAN_MANAGE permission or raise 403."""
        if not self.can_manage(profile_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to manage this profile",
            )

    def get_accessible_profile_ids(
        self,
        user_id: Optional[str] = None,
        user_name: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> List[int]:
        """
        Get list of profile IDs the user has access to.
        
        Args:
            user_id: Databricks user ID
            user_name: Username/email
            group_ids: List of group IDs
            
        Returns:
            List of profile IDs with any level of access
        """
        accessible_ids = set()
        
        # Profiles where user is creator
        if user_name:
            creator_profiles = self.db.query(ConfigProfile.id).filter(
                ConfigProfile.is_deleted == False,
                ConfigProfile.created_by == user_name,
            ).all()
            accessible_ids.update(p.id for p in creator_profiles)
        
        # Profiles with direct user contributor entry (by user_id)
        if user_id:
            user_id_profiles = self.db.query(ConfigProfileContributor.profile_id).filter(
                ConfigProfileContributor.identity_type == "USER",
                ConfigProfileContributor.identity_id == user_id,
            ).all()
            accessible_ids.update(p.profile_id for p in user_id_profiles)
        
        # Profiles with direct user contributor entry (by username - fallback)
        if user_name:
            user_name_profiles = self.db.query(ConfigProfileContributor.profile_id).filter(
                ConfigProfileContributor.identity_type == "USER",
                ConfigProfileContributor.identity_name == user_name,
            ).all()
            accessible_ids.update(p.profile_id for p in user_name_profiles)
        
        # Profiles with group contributor entry
        if group_ids:
            group_profiles = self.db.query(ConfigProfileContributor.profile_id).filter(
                ConfigProfileContributor.identity_type == "GROUP",
                ConfigProfileContributor.identity_id.in_(group_ids),
            ).all()
            accessible_ids.update(p.profile_id for p in group_profiles)
        
        return list(accessible_ids)

    def get_current_user_accessible_profile_ids(self) -> List[int]:
        """
        Get profile IDs accessible to the current request user.
        
        Uses the permission context from the current request.
        
        Returns:
            List of accessible profile IDs
        """
        ctx = get_permission_context()
        if not ctx:
            logger.warning("No permission context available")
            return []
        
        return self.get_accessible_profile_ids(
            user_id=ctx.user_id,
            user_name=ctx.user_name,
            group_ids=ctx.group_ids,
        )

    def get_profiles_with_permissions(
        self,
        user_id: Optional[str] = None,
        user_name: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> List[Tuple[ConfigProfile, PermissionLevel]]:
        """
        Get all accessible profiles with their permission levels.
        
        Args:
            user_id: Databricks user ID
            user_name: Username/email
            group_ids: List of group IDs
            
        Returns:
            List of (profile, permission_level) tuples
        """
        accessible_ids = self.get_accessible_profile_ids(user_id, user_name, group_ids)
        
        if not accessible_ids:
            return []
        
        profiles = self.db.query(ConfigProfile).filter(
            ConfigProfile.id.in_(accessible_ids),
            ConfigProfile.is_deleted == False,
        ).order_by(ConfigProfile.name).all()
        
        result = []
        for profile in profiles:
            perm = self.get_user_permission(
                profile_id=profile.id,
                user_id=user_id,
                user_name=user_name,
                group_ids=group_ids,
            )
            if perm:
                result.append((profile, perm))
        
        return result


def get_permission_service(db: Session) -> PermissionService:
    """Factory function to create PermissionService instance."""
    return PermissionService(db)

