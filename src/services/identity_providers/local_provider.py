"""
Local identity provider using Lakebase table.

Stores and retrieves identities from the local app_identities table.
Populated automatically when users sign in to the app.

This is the fallback provider when no admin tokens are configured.
"""

import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)


class LocalIdentityError(Exception):
    """Error interacting with local identity storage."""
    pass


class LocalIdentityProvider:
    """
    Fetch identities from local Lakebase table.
    
    This provider uses the app_identities table which is populated
    automatically when users sign in to the application.
    
    Limitations:
    - Only sees users who have logged into the app at least once
    - Group memberships are limited to what was captured at login time
    - Cannot see users/groups that have never interacted with the app
    """
    
    def __init__(self):
        """Initialize the local identity provider."""
        logger.info("LocalIdentityProvider initialized")
    
    def _get_db_session(self):
        """Get a database session."""
        from src.core.database import get_db_session
        return get_db_session()
    
    def list_users(
        self,
        filter_query: Optional[str] = None,
        max_results: int = 100,
    ) -> List[dict]:
        """
        List users from local identity table.
        
        Args:
            filter_query: Optional search filter (applied to identity_name)
            max_results: Maximum number of results
            
        Returns:
            List of user dictionaries with id, userName, displayName, type
        """
        from src.database.models.identity import AppIdentity
        
        try:
            with self._get_db_session() as db:
                query = db.query(AppIdentity).filter(
                    AppIdentity.identity_type == "USER",
                    AppIdentity.is_active == True,
                )
                
                if filter_query:
                    # Simple contains filter on identity_name
                    query = query.filter(
                        AppIdentity.identity_name.ilike(f"%{filter_query}%")
                    )
                
                identities = query.limit(max_results).all()
                
                users = [identity.to_dict() for identity in identities]
                logger.debug(f"Fetched {len(users)} users from local table")
                return users
                
        except Exception as e:
            logger.error(f"Failed to fetch users from local table: {e}")
            return []
    
    def list_groups(
        self,
        filter_query: Optional[str] = None,
        max_results: int = 100,
    ) -> List[dict]:
        """
        List groups from local identity table.
        
        Args:
            filter_query: Optional search filter (applied to identity_name)
            max_results: Maximum number of results
            
        Returns:
            List of group dictionaries with id, displayName, type
        """
        from src.database.models.identity import AppIdentity
        
        try:
            with self._get_db_session() as db:
                query = db.query(AppIdentity).filter(
                    AppIdentity.identity_type == "GROUP",
                    AppIdentity.is_active == True,
                )
                
                if filter_query:
                    query = query.filter(
                        AppIdentity.identity_name.ilike(f"%{filter_query}%")
                    )
                
                identities = query.limit(max_results).all()
                
                groups = [identity.to_dict() for identity in identities]
                logger.debug(f"Fetched {len(groups)} groups from local table")
                return groups
                
        except Exception as e:
            logger.error(f"Failed to fetch groups from local table: {e}")
            return []
    
    def search_identities(
        self,
        query: str,
        include_users: bool = True,
        include_groups: bool = True,
        max_results: int = 50,
    ) -> List[dict]:
        """
        Search for users and groups matching a query.
        
        Args:
            query: Search string to match against names
            include_users: Whether to include users
            include_groups: Whether to include groups
            max_results: Maximum total results
            
        Returns:
            Combined list of matching users and groups
        """
        from src.database.models.identity import AppIdentity
        
        try:
            with self._get_db_session() as db:
                db_query = db.query(AppIdentity).filter(
                    AppIdentity.is_active == True,
                    AppIdentity.identity_name.ilike(f"%{query}%"),
                )
                
                # Filter by type
                if include_users and not include_groups:
                    db_query = db_query.filter(AppIdentity.identity_type == "USER")
                elif include_groups and not include_users:
                    db_query = db_query.filter(AppIdentity.identity_type == "GROUP")
                elif not include_users and not include_groups:
                    return []
                
                identities = db_query.order_by(AppIdentity.identity_name).limit(max_results).all()
                
                return [identity.to_dict() for identity in identities]
                
        except Exception as e:
            logger.error(f"Failed to search identities in local table: {e}")
            return []
    
    def get_user_by_id(self, user_id: str) -> Optional[dict]:
        """
        Get a specific user by ID.
        
        Args:
            user_id: Databricks user ID
            
        Returns:
            User dictionary or None if not found
        """
        from src.database.models.identity import AppIdentity
        
        try:
            with self._get_db_session() as db:
                identity = db.query(AppIdentity).filter(
                    AppIdentity.identity_id == user_id,
                    AppIdentity.identity_type == "USER",
                    AppIdentity.is_active == True,
                ).first()
                
                if identity:
                    return identity.to_dict()
                return None
                
        except Exception as e:
            logger.error(f"Failed to get user {user_id} from local table: {e}")
            return None
    
    def get_group_by_id(self, group_id: str) -> Optional[dict]:
        """
        Get a specific group by ID.
        
        Args:
            group_id: Databricks group ID
            
        Returns:
            Group dictionary or None if not found
        """
        from src.database.models.identity import AppIdentity
        
        try:
            with self._get_db_session() as db:
                identity = db.query(AppIdentity).filter(
                    AppIdentity.identity_id == group_id,
                    AppIdentity.identity_type == "GROUP",
                    AppIdentity.is_active == True,
                ).first()
                
                if identity:
                    return identity.to_dict()
                return None
                
        except Exception as e:
            logger.error(f"Failed to get group {group_id} from local table: {e}")
            return None
    
    def get_user_groups(self, user_id: str) -> List[str]:
        """
        Get list of group IDs that a user belongs to.
        
        NOTE: This is limited in local mode - we can only return groups
        if we have explicitly recorded the user-group relationship.
        Currently returns empty list as we don't track memberships locally.
        
        Args:
            user_id: Databricks user ID
            
        Returns:
            List of group IDs (empty in local mode)
        """
        # Local provider doesn't track group memberships
        # This would require a separate user_group_memberships table
        logger.debug(f"get_user_groups called in local mode - returning empty (no membership tracking)")
        return []
    
    def record_identity(
        self,
        identity_id: str,
        identity_type: str,
        identity_name: str,
        display_name: Optional[str] = None,
    ) -> bool:
        """
        Record an identity in the local table.
        
        Called automatically when users sign in to populate the local cache.
        
        Args:
            identity_id: Databricks user/group ID
            identity_type: "USER" or "GROUP"
            identity_name: Email for users, name for groups
            display_name: Friendly display name
            
        Returns:
            True if recorded successfully, False otherwise
        """
        from src.database.models.identity import AppIdentity
        
        try:
            with self._get_db_session() as db:
                # Try to find existing identity
                existing = db.query(AppIdentity).filter(
                    AppIdentity.identity_id == identity_id
                ).first()
                
                if existing:
                    # Update last_seen_at and ensure it's active
                    existing.last_seen_at = datetime.utcnow()
                    existing.is_active = True
                    # Update display name if provided and different
                    if display_name and display_name != existing.display_name:
                        existing.display_name = display_name
                    logger.debug(f"Updated existing identity: {identity_type}:{identity_name}")
                else:
                    # Create new identity
                    new_identity = AppIdentity(
                        identity_id=identity_id,
                        identity_type=identity_type,
                        identity_name=identity_name,
                        display_name=display_name or identity_name,
                        first_seen_at=datetime.utcnow(),
                        last_seen_at=datetime.utcnow(),
                        is_active=True,
                    )
                    db.add(new_identity)
                    logger.info(f"Recorded new identity: {identity_type}:{identity_name}")
                
                db.commit()
                return True
                
        except IntegrityError:
            # Race condition - another request already added this identity
            logger.debug(f"Identity {identity_id} already exists (concurrent insert)")
            return True
        except Exception as e:
            logger.error(f"Failed to record identity {identity_id}: {e}")
            return False

