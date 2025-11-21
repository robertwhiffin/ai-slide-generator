"""Profile management service."""
from typing import List, Optional

from sqlalchemy.orm import Session, joinedload

from src.config.defaults import DEFAULT_CONFIG
from src.models.config import (
    ConfigAIInfra,
    ConfigGenieSpace,
    ConfigHistory,
    ConfigMLflow,
    ConfigProfile,
    ConfigPrompts,
)


class ProfileService:
    """Manage configuration profiles."""

    def __init__(self, db: Session):
        self.db = db

    def list_profiles(self) -> List[ConfigProfile]:
        """Get all profiles."""
        return self.db.query(ConfigProfile).order_by(ConfigProfile.name).all()

    def get_profile(self, profile_id: int) -> Optional[ConfigProfile]:
        """
        Get profile with all configurations.
        
        Args:
            profile_id: Profile ID
            
        Returns:
            Profile with related configs loaded, or None
        """
        return (
            self.db.query(ConfigProfile)
            .options(
                joinedload(ConfigProfile.ai_infra),
                joinedload(ConfigProfile.genie_spaces),
                joinedload(ConfigProfile.mlflow),
                joinedload(ConfigProfile.prompts),
            )
            .filter(ConfigProfile.id == profile_id)
            .first()
        )

    def get_default_profile(self) -> Optional[ConfigProfile]:
        """Get default profile."""
        return (
            self.db.query(ConfigProfile)
            .options(
                joinedload(ConfigProfile.ai_infra),
                joinedload(ConfigProfile.genie_spaces),
                joinedload(ConfigProfile.mlflow),
                joinedload(ConfigProfile.prompts),
            )
            .filter(ConfigProfile.is_default == True)
            .first()
        )

    def create_profile(
        self,
        name: str,
        description: Optional[str],
        copy_from_id: Optional[int],
        user: str,
    ) -> ConfigProfile:
        """
        Create new profile.
        
        Args:
            name: Profile name
            description: Profile description
            copy_from_id: If provided, copy configs from this profile
            user: User creating the profile
            
        Returns:
            Created profile
        """
        # Create profile
        profile = ConfigProfile(
            name=name,
            description=description,
            is_default=False,
            created_by=user,
            updated_by=user,
        )
        self.db.add(profile)
        self.db.flush()

        if copy_from_id:
            # Copy from existing profile
            source_profile = self.get_profile(copy_from_id)
            if not source_profile:
                raise ValueError(f"Source profile {copy_from_id} not found")

            # Copy AI infra
            ai_infra = ConfigAIInfra(
                profile_id=profile.id,
                llm_endpoint=source_profile.ai_infra.llm_endpoint,
                llm_temperature=source_profile.ai_infra.llm_temperature,
                llm_max_tokens=source_profile.ai_infra.llm_max_tokens,
            )
            self.db.add(ai_infra)

            # Copy Genie space (only one per profile)
            if source_profile.genie_spaces:
                # Copy the first (and only) genie space
                space = source_profile.genie_spaces[0]
                new_space = ConfigGenieSpace(
                    profile_id=profile.id,
                    space_id=space.space_id,
                    space_name=space.space_name,
                    description=space.description,
                )
                self.db.add(new_space)

            # Copy MLflow
            mlflow = ConfigMLflow(
                profile_id=profile.id,
                experiment_name=source_profile.mlflow.experiment_name,
            )
            self.db.add(mlflow)

            # Copy prompts
            prompts = ConfigPrompts(
                profile_id=profile.id,
                system_prompt=source_profile.prompts.system_prompt,
                slide_editing_instructions=source_profile.prompts.slide_editing_instructions,
                user_prompt_template=source_profile.prompts.user_prompt_template,
            )
            self.db.add(prompts)
        else:
            # Use defaults
            ai_infra = ConfigAIInfra(
                profile_id=profile.id,
                llm_endpoint=DEFAULT_CONFIG["llm"]["endpoint"],
                llm_temperature=DEFAULT_CONFIG["llm"]["temperature"],
                llm_max_tokens=DEFAULT_CONFIG["llm"]["max_tokens"],
            )
            self.db.add(ai_infra)

            genie_space = ConfigGenieSpace(
                profile_id=profile.id,
                space_id=DEFAULT_CONFIG["genie"]["space_id"],
                space_name=DEFAULT_CONFIG["genie"]["space_name"],
                description=DEFAULT_CONFIG["genie"]["description"],
            )
            self.db.add(genie_space)

            mlflow = ConfigMLflow(
                profile_id=profile.id,
                experiment_name=DEFAULT_CONFIG["mlflow"]["experiment_name"],
            )
            self.db.add(mlflow)

            prompts = ConfigPrompts(
                profile_id=profile.id,
                system_prompt=DEFAULT_CONFIG["prompts"]["system_prompt"],
                slide_editing_instructions=DEFAULT_CONFIG["prompts"]["slide_editing_instructions"],
                user_prompt_template=DEFAULT_CONFIG["prompts"]["user_prompt_template"],
            )
            self.db.add(prompts)

        # Log creation
        history = ConfigHistory(
            profile_id=profile.id,
            domain="profile",
            action="create",
            changed_by=user,
            changes={"name": {"old": None, "new": name}},
        )
        self.db.add(history)

        self.db.commit()
        self.db.refresh(profile)

        return profile

    def update_profile(
        self,
        profile_id: int,
        name: Optional[str],
        description: Optional[str],
        user: str,
    ) -> ConfigProfile:
        """Update profile metadata."""
        profile = self.get_profile(profile_id)
        if not profile:
            raise ValueError(f"Profile {profile_id} not found")

        changes = {}

        if name and name != profile.name:
            changes["name"] = {"old": profile.name, "new": name}
            profile.name = name

        if description is not None and description != profile.description:
            changes["description"] = {"old": profile.description, "new": description}
            profile.description = description

        if changes:
            profile.updated_by = user

            history = ConfigHistory(
                profile_id=profile.id,
                domain="profile",
                action="update",
                changed_by=user,
                changes=changes,
            )
            self.db.add(history)

        self.db.commit()
        self.db.refresh(profile)

        return profile

    def delete_profile(self, profile_id: int, user: str) -> None:
        """
        Delete profile.
        
        Args:
            profile_id: Profile to delete
            user: User deleting the profile
            
        Raises:
            ValueError: If trying to delete default profile
        """
        profile = self.get_profile(profile_id)
        if not profile:
            raise ValueError(f"Profile {profile_id} not found")

        if profile.is_default:
            raise ValueError("Cannot delete default profile")

        # Log deletion before deleting
        history = ConfigHistory(
            profile_id=profile.id,
            domain="profile",
            action="delete",
            changed_by=user,
            changes={"name": {"old": profile.name, "new": None}},
        )
        self.db.add(history)
        self.db.flush()

        self.db.delete(profile)
        self.db.commit()

    def set_default_profile(self, profile_id: int, user: str) -> ConfigProfile:
        """
        Mark profile as default.
        
        Args:
            profile_id: Profile to mark as default
            user: User making the change
            
        Returns:
            Updated profile
        """
        profile = self.get_profile(profile_id)
        if not profile:
            raise ValueError(f"Profile {profile_id} not found")

        if profile.is_default:
            return profile  # Already default

        # Unmark other default profiles
        self.db.query(ConfigProfile).filter(
            ConfigProfile.is_default == True
        ).update({"is_default": False})

        # Mark this as default
        profile.is_default = True
        profile.updated_by = user

        history = ConfigHistory(
            profile_id=profile.id,
            domain="profile",
            action="set_default",
            changed_by=user,
            changes={"is_default": {"old": False, "new": True}},
        )
        self.db.add(history)

        self.db.commit()
        self.db.refresh(profile)

        return profile

    def duplicate_profile(
        self,
        profile_id: int,
        new_name: str,
        user: str,
    ) -> ConfigProfile:
        """
        Duplicate profile with new name.
        
        Args:
            profile_id: Profile to duplicate
            new_name: Name for new profile
            user: User creating the duplicate
            
        Returns:
            New profile
        """
        return self.create_profile(
            name=new_name,
            description=f"Copy of profile {profile_id}",
            copy_from_id=profile_id,
            user=user,
        )

