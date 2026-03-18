"""Genie space management service."""
from typing import Optional

from sqlalchemy.orm import Session

from src.database.models import ConfigGenieSpace


class GenieService:
    """
    Manage Genie space for profiles.
    
    Each profile has exactly one Genie space.
    """

    def __init__(self, db: Session):
        self.db = db

    def get_genie_space(self, profile_id: int) -> Optional[ConfigGenieSpace]:
        """
        Get the Genie space for a profile.
        
        Args:
            profile_id: Profile ID
            
        Returns:
            ConfigGenieSpace if exists, None otherwise
        """
        return (
            self.db.query(ConfigGenieSpace)
            .filter(ConfigGenieSpace.profile_id == profile_id)
            .first()
        )

    def add_genie_space(
        self,
        profile_id: int,
        space_id: str,
        space_name: str,
        description: str = None,
        user: str = None,
    ) -> ConfigGenieSpace:
        """
        Add Genie space to profile.
        
        Args:
            profile_id: Profile ID
            space_id: Databricks Genie space ID
            space_name: Display name for the space
            description: Optional description
            user: User making the change
            
        Returns:
            Created ConfigGenieSpace
            
        Raises:
            IntegrityError: If profile already has a Genie space
        """
        space = ConfigGenieSpace(
            profile_id=profile_id,
            space_id=space_id,
            space_name=space_name,
            description=description,
        )
        self.db.add(space)

        self.db.commit()
        self.db.refresh(space)

        return space

    def update_genie_space(
        self,
        space_id: int,
        space_name: str = None,
        description: str = None,
        user: str = None,
    ) -> ConfigGenieSpace:
        """Update Genie space metadata."""
        space = self.db.query(ConfigGenieSpace).filter_by(id=space_id).first()
        if not space:
            raise ValueError(f"Genie space {space_id} not found")

        changes = {}

        if space_name is not None and space_name != space.space_name:
            changes["space_name"] = {"old": space.space_name, "new": space_name}
            space.space_name = space_name

        if description is not None and description != space.description:
            changes["description"] = {"old": space.description, "new": description}
            space.description = description

        self.db.commit()
        self.db.refresh(space)

        return space

    def delete_genie_space(self, space_id: int, user: str) -> None:
        """
        Remove Genie space from profile.
        
        Args:
            space_id: Genie space ID
            user: User making the change
            
        Raises:
            ValueError: If space not found
        """
        space = self.db.query(ConfigGenieSpace).filter_by(id=space_id).first()
        if not space:
            raise ValueError(f"Genie space {space_id} not found")

        self.db.delete(space)
        self.db.commit()


