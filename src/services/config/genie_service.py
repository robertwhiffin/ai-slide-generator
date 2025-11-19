"""Genie space management service."""
from typing import List, Optional

from sqlalchemy.orm import Session

from src.models.config import ConfigGenieSpace, ConfigHistory


class GenieService:
    """Manage Genie spaces for profiles."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def list_genie_spaces(self, profile_id: int) -> List[ConfigGenieSpace]:
        """Get all Genie spaces for profile."""
        return (
            self.db.query(ConfigGenieSpace)
            .filter(ConfigGenieSpace.profile_id == profile_id)
            .order_by(ConfigGenieSpace.is_default.desc(), ConfigGenieSpace.space_name)
            .all()
        )
    
    def get_default_genie_space(self, profile_id: int) -> Optional[ConfigGenieSpace]:
        """Get default Genie space for profile."""
        return (
            self.db.query(ConfigGenieSpace)
            .filter(
                ConfigGenieSpace.profile_id == profile_id,
                ConfigGenieSpace.is_default == True,
            )
            .first()
        )
    
    def add_genie_space(
        self,
        profile_id: int,
        space_id: str,
        space_name: str,
        description: str = None,
        is_default: bool = False,
        user: str = None,
    ) -> ConfigGenieSpace:
        """Add Genie space to profile."""
        space = ConfigGenieSpace(
            profile_id=profile_id,
            space_id=space_id,
            space_name=space_name,
            description=description,
            is_default=is_default,
        )
        self.db.add(space)
        
        # Log creation
        history = ConfigHistory(
            profile_id=profile_id,
            domain="genie",
            action="create",
            changed_by=user or "system",
            changes={
                "space_id": {"old": None, "new": space_id},
                "space_name": {"old": None, "new": space_name},
            },
        )
        self.db.add(history)
        
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
        
        if changes:
            history = ConfigHistory(
                profile_id=space.profile_id,
                domain="genie",
                action="update",
                changed_by=user or "system",
                changes=changes,
            )
            self.db.add(history)
        
        self.db.commit()
        self.db.refresh(space)
        
        return space
    
    def delete_genie_space(self, space_id: int, user: str) -> None:
        """Remove Genie space from profile."""
        space = self.db.query(ConfigGenieSpace).filter_by(id=space_id).first()
        if not space:
            raise ValueError(f"Genie space {space_id} not found")
        
        if space.is_default:
            # Check if there are other spaces
            other_spaces = (
                self.db.query(ConfigGenieSpace)
                .filter(
                    ConfigGenieSpace.profile_id == space.profile_id,
                    ConfigGenieSpace.id != space_id,
                )
                .count()
            )
            
            if other_spaces == 0:
                raise ValueError("Cannot delete the only Genie space")
        
        # Log deletion
        history = ConfigHistory(
            profile_id=space.profile_id,
            domain="genie",
            action="delete",
            changed_by=user,
            changes={"space_name": {"old": space.space_name, "new": None}},
        )
        self.db.add(history)
        self.db.flush()
        
        self.db.delete(space)
        self.db.commit()
    
    def set_default_genie_space(self, space_id: int, user: str) -> ConfigGenieSpace:
        """Mark Genie space as default for its profile."""
        space = self.db.query(ConfigGenieSpace).filter_by(id=space_id).first()
        if not space:
            raise ValueError(f"Genie space {space_id} not found")
        
        if space.is_default:
            return space  # Already default
        
        # Unmark other default spaces in this profile
        self.db.query(ConfigGenieSpace).filter(
            ConfigGenieSpace.profile_id == space.profile_id,
            ConfigGenieSpace.is_default == True,
        ).update({"is_default": False})
        
        # Mark this as default
        space.is_default = True
        
        history = ConfigHistory(
            profile_id=space.profile_id,
            domain="genie",
            action="set_default",
            changed_by=user,
            changes={"is_default": {"old": False, "new": True}},
        )
        self.db.add(history)
        
        self.db.commit()
        self.db.refresh(space)
        
        return space

