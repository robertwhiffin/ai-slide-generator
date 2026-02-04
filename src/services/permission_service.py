"""Permission service for session access control.

Handles all permission checking logic including:
- Ownership checks
- Explicit permission grants (user/group)
- Databricks group membership resolution
"""
import logging
from typing import List, Optional, Set

from databricks.sdk import WorkspaceClient
from databricks.sdk.service import iam
from sqlalchemy.orm import Session

from src.core.databricks_client import get_user_client
from src.core.user_context import get_current_user
from src.database.models.permissions import (
    PermissionLevel,
    PrincipalType,
    SessionPermission,
    SessionVisibility,
)
from src.database.models.session import UserSession

logger = logging.getLogger(__name__)


class PermissionDeniedError(Exception):
    """Raised when user lacks required permission for an operation."""
    pass


class PermissionService:
    """Service for checking and managing session permissions."""
    
    def __init__(self, db: Session):
        """Initialize permission service.
        
        Args:
            db: Database session for permission queries
        """
        self.db = db
        self._group_cache: dict[str, Set[str]] = {}
    
    def check_permission(
        self,
        session: UserSession,
        required_permission: PermissionLevel,
        current_user: Optional[str] = None,
    ) -> bool:
        """Check if current user has required permission on session.
        
        Permission hierarchy:
        1. Owner always has edit permission
        2. Workspace visibility grants read to all
        3. Explicit user grants
        4. Group membership grants
        
        Args:
            session: Session to check permissions for
            required_permission: Required permission level (read/edit)
            current_user: User to check (defaults to context user)
            
        Returns:
            True if user has permission, False otherwise
        """
        if current_user is None:
            current_user = get_current_user()
        
        # No user context = no permissions (except for system operations)
        if not current_user:
            logger.warning(f"Permission check failed: no current user for session {session.session_id}")
            return False
        
        # 1. Owner always has edit (and read) permission
        if session.created_by == current_user:
            logger.debug(f"User {current_user} is owner of session {session.session_id}")
            return True
        
        # 2. Workspace visibility grants read to everyone
        if session.visibility == SessionVisibility.WORKSPACE.value:
            if required_permission == PermissionLevel.READ:
                logger.debug(f"Session {session.session_id} has workspace visibility, granting read")
                return True
        
        # 3. Check explicit permission grants
        # First check user grants
        user_perm = (
            self.db.query(SessionPermission)
            .filter(
                SessionPermission.session_id == session.id,
                SessionPermission.principal_type == PrincipalType.USER.value,
                SessionPermission.principal_id == current_user,
            )
            .first()
        )
        
        if user_perm:
            # Edit permission includes read
            if user_perm.permission == PermissionLevel.EDIT.value:
                return True
            if required_permission == PermissionLevel.READ and user_perm.permission == PermissionLevel.READ.value:
                return True
        
        # 4. Check group membership grants
        user_groups = self._get_user_groups(current_user)
        
        for group in user_groups:
            group_perm = (
                self.db.query(SessionPermission)
                .filter(
                    SessionPermission.session_id == session.id,
                    SessionPermission.principal_type == PrincipalType.GROUP.value,
                    SessionPermission.principal_id == group,
                )
                .first()
            )
            
            if group_perm:
                # Edit permission includes read
                if group_perm.permission == PermissionLevel.EDIT.value:
                    return True
                if required_permission == PermissionLevel.READ and group_perm.permission == PermissionLevel.READ.value:
                    return True
        
        logger.debug(
            f"User {current_user} lacks {required_permission.value} permission on session {session.session_id}"
        )
        return False
    
    def require_permission(
        self,
        session: UserSession,
        required_permission: PermissionLevel,
        current_user: Optional[str] = None,
    ) -> None:
        """Check permission or raise PermissionDeniedError.
        
        Args:
            session: Session to check
            required_permission: Required permission level
            current_user: User to check (defaults to context user)
            
        Raises:
            PermissionDeniedError: If user lacks permission
        """
        if not self.check_permission(session, required_permission, current_user):
            user = current_user or get_current_user() or "anonymous"
            raise PermissionDeniedError(
                f"User {user} lacks {required_permission.value} permission on session {session.session_id}"
            )
    
    def grant_permission(
        self,
        session: UserSession,
        principal_type: PrincipalType,
        principal_id: str,
        permission: PermissionLevel,
        granted_by: Optional[str] = None,
    ) -> SessionPermission:
        """Grant permission to a user or group.
        
        Only session owners can grant permissions.
        
        Args:
            session: Session to grant permission on
            principal_type: Type of principal (user/group)
            principal_id: User email or group name
            permission: Permission level to grant
            granted_by: User granting permission (defaults to context user)
            
        Returns:
            Created or updated SessionPermission
            
        Raises:
            PermissionDeniedError: If granter is not the owner
        """
        if granted_by is None:
            granted_by = get_current_user()
        
        # Only owner can grant permissions
        if session.created_by != granted_by:
            raise PermissionDeniedError(
                f"Only session owner can grant permissions (owner: {session.created_by}, user: {granted_by})"
            )
        
        # Check if permission already exists
        existing = (
            self.db.query(SessionPermission)
            .filter(
                SessionPermission.session_id == session.id,
                SessionPermission.principal_type == principal_type.value,
                SessionPermission.principal_id == principal_id,
            )
            .first()
        )
        
        if existing:
            # Update existing permission
            existing.permission = permission.value
            existing.granted_by = granted_by
            self.db.flush()
            logger.info(
                f"Updated permission: {principal_type.value} {principal_id} "
                f"now has {permission.value} on session {session.session_id}"
            )
            return existing
        else:
            # Create new permission
            new_perm = SessionPermission(
                session_id=session.id,
                principal_type=principal_type.value,
                principal_id=principal_id,
                permission=permission.value,
                granted_by=granted_by,
            )
            self.db.add(new_perm)
            self.db.flush()
            logger.info(
                f"Granted permission: {principal_type.value} {principal_id} "
                f"has {permission.value} on session {session.session_id}"
            )
            return new_perm
    
    def revoke_permission(
        self,
        session: UserSession,
        principal_type: PrincipalType,
        principal_id: str,
        revoked_by: Optional[str] = None,
    ) -> bool:
        """Revoke permission from a user or group.
        
        Only session owners can revoke permissions.
        
        Args:
            session: Session to revoke permission on
            principal_type: Type of principal
            principal_id: User email or group name
            revoked_by: User revoking permission (defaults to context user)
            
        Returns:
            True if permission was revoked, False if it didn't exist
            
        Raises:
            PermissionDeniedError: If revoker is not the owner
        """
        if revoked_by is None:
            revoked_by = get_current_user()
        
        # Only owner can revoke permissions
        if session.created_by != revoked_by:
            raise PermissionDeniedError(
                f"Only session owner can revoke permissions (owner: {session.created_by}, user: {revoked_by})"
            )
        
        existing = (
            self.db.query(SessionPermission)
            .filter(
                SessionPermission.session_id == session.id,
                SessionPermission.principal_type == principal_type.value,
                SessionPermission.principal_id == principal_id,
            )
            .first()
        )
        
        if existing:
            self.db.delete(existing)
            self.db.flush()
            logger.info(
                f"Revoked permission: {principal_type.value} {principal_id} "
                f"no longer has access to session {session.session_id}"
            )
            return True
        else:
            return False
    
    def list_permissions(self, session: UserSession) -> List[SessionPermission]:
        """List all permissions for a session.
        
        Args:
            session: Session to list permissions for
            
        Returns:
            List of SessionPermission objects
        """
        return (
            self.db.query(SessionPermission)
            .filter(SessionPermission.session_id == session.id)
            .all()
        )
    
    def set_visibility(
        self,
        session: UserSession,
        visibility: SessionVisibility,
        changed_by: Optional[str] = None,
    ) -> None:
        """Change session visibility.
        
        Only session owners can change visibility.
        
        Args:
            session: Session to update
            visibility: New visibility level
            changed_by: User making the change (defaults to context user)
            
        Raises:
            PermissionDeniedError: If user is not the owner
        """
        if changed_by is None:
            changed_by = get_current_user()
        
        # Only owner can change visibility
        if session.created_by != changed_by:
            raise PermissionDeniedError(
                f"Only session owner can change visibility (owner: {session.created_by}, user: {changed_by})"
            )
        
        old_visibility = session.visibility
        session.visibility = visibility.value
        self.db.flush()
        
        logger.info(
            f"Changed session {session.session_id} visibility: {old_visibility} → {visibility.value}"
        )
    
    def _get_user_groups(self, username: str) -> Set[str]:
        """Get all Databricks groups the user belongs to.
        
        Uses caching to avoid repeated API calls within the same request.
        
        Args:
            username: User's email/username
            
        Returns:
            Set of group display names
        """
        # Check cache
        if username in self._group_cache:
            return self._group_cache[username]
        
        try:
            client = get_user_client()
            
            # Find user in workspace
            users = client.users.list(filter=f'userName eq "{username}"')
            user_list = list(users)
            
            if not user_list:
                logger.warning(f"User not found in workspace: {username}")
                self._group_cache[username] = set()
                return set()
            
            user = user_list[0]
            
            # Get group memberships
            groups = set()
            if user.groups:
                for group_ref in user.groups:
                    if group_ref.display:
                        groups.add(group_ref.display)
            
            logger.debug(f"User {username} belongs to groups: {groups}")
            self._group_cache[username] = groups
            return groups
            
        except Exception as e:
            logger.error(f"Failed to get groups for user {username}: {e}")
            # Cache empty set to avoid repeated failures
            self._group_cache[username] = set()
            return set()
    
    def list_accessible_sessions(
        self,
        current_user: Optional[str] = None,
        permission: PermissionLevel = PermissionLevel.READ,
    ) -> List[UserSession]:
        """List all sessions accessible to the current user.
        
        Includes:
        - Sessions owned by user
        - Sessions with workspace visibility (if read permission)
        - Sessions with explicit user grants
        - Sessions with group grants (based on user's group memberships)
        
        Args:
            current_user: User to check (defaults to context user)
            permission: Minimum permission level required
            
        Returns:
            List of UserSession objects
        """
        if current_user is None:
            current_user = get_current_user()
        
        if not current_user:
            return []
        
        # Get user's groups
        user_groups = self._get_user_groups(current_user)
        
        # Build query
        query = self.db.query(UserSession)
        
        # Sessions owned by user
        owned = query.filter(UserSession.created_by == current_user)
        
        # Sessions with workspace visibility (if only read required)
        if permission == PermissionLevel.READ:
            workspace_visible = query.filter(
                UserSession.visibility == SessionVisibility.WORKSPACE.value
            )
        else:
            workspace_visible = query.filter(False)  # Empty query
        
        # Sessions with explicit user permission
        user_perms = (
            self.db.query(SessionPermission.session_id)
            .filter(
                SessionPermission.principal_type == PrincipalType.USER.value,
                SessionPermission.principal_id == current_user,
            )
        )
        
        # For edit permission, only include edit grants
        if permission == PermissionLevel.EDIT:
            user_perms = user_perms.filter(
                SessionPermission.permission == PermissionLevel.EDIT.value
            )
        
        user_perm_session_ids = [p.session_id for p in user_perms.all()]
        
        # Sessions with group permission
        group_perms = (
            self.db.query(SessionPermission.session_id)
            .filter(
                SessionPermission.principal_type == PrincipalType.GROUP.value,
                SessionPermission.principal_id.in_(user_groups) if user_groups else False,
            )
        )
        
        if permission == PermissionLevel.EDIT:
            group_perms = group_perms.filter(
                SessionPermission.permission == PermissionLevel.EDIT.value
            )
        
        group_perm_session_ids = [p.session_id for p in group_perms.all()]
        
        # Combine all accessible session IDs
        all_session_ids = set(user_perm_session_ids + group_perm_session_ids)
        
        # Query sessions
        accessible = []
        accessible.extend(owned.all())
        accessible.extend(workspace_visible.all())
        
        if all_session_ids:
            explicitly_granted = query.filter(UserSession.id.in_(all_session_ids)).all()
            accessible.extend(explicitly_granted)
        
        # Deduplicate by session_id
        seen = set()
        unique_sessions = []
        for session in accessible:
            if session.session_id not in seen:
                seen.add(session.session_id)
                unique_sessions.append(session)
        
        return unique_sessions
