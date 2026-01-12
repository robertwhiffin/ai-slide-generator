"""Profile management service."""
from typing import List, Optional

from sqlalchemy.orm import Session, joinedload

from src.core.defaults import DEFAULT_CONFIG
from src.database.models import (
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
        user: str,
    ) -> ConfigProfile:
        """
        Create new profile.
        
        If no default profile exists, the new profile will be set as default.
        New profiles require explicit Genie space configuration - no default is created.
        MLflow experiment name is auto-set based on creator's username.
        
        Args:
            name: Profile name
            description: Profile description
            user: User creating the profile
            
        Returns:
            Created profile
        """
        # Check if a default profile already exists
        has_default = (
            self.db.query(ConfigProfile)
            .filter(ConfigProfile.is_default == True)
            .first()
            is not None
        )

        # Create profile - make it default if no default exists
        profile = ConfigProfile(
            name=name,
            description=description,
            is_default=not has_default,  # First profile becomes default
            created_by=user,
            updated_by=user,
        )
        self.db.add(profile)
        self.db.flush()

        # Use defaults for AI infrastructure
        ai_infra = ConfigAIInfra(
            profile_id=profile.id,
            llm_endpoint=DEFAULT_CONFIG["llm"]["endpoint"],
            llm_temperature=DEFAULT_CONFIG["llm"]["temperature"],
            llm_max_tokens=DEFAULT_CONFIG["llm"]["max_tokens"],
        )
        self.db.add(ai_infra)

        # NO default Genie space - user must explicitly configure one

        # Auto-set MLflow experiment name based on creator's username
        experiment_name = f"/Workspace/Users/{user}/ai-slide-generator"
        mlflow = ConfigMLflow(
            profile_id=profile.id,
            experiment_name=experiment_name,
        )
        self.db.add(mlflow)

        # Use default prompts
        prompts = ConfigPrompts(
            profile_id=profile.id,
            system_prompt=DEFAULT_CONFIG["prompts"]["system_prompt"],
            slide_editing_instructions=DEFAULT_CONFIG["prompts"]["slide_editing_instructions"],
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

    def create_profile_with_config(
        self,
        name: str,
        description: Optional[str],
        genie_space: Optional[dict],
        ai_infra: Optional[dict],
        mlflow: Optional[dict],
        prompts: Optional[dict],
        user: str,
    ) -> ConfigProfile:
        """
        Create profile with all configurations in one transaction.
        
        Used by the creation wizard for complete profile setup.
        
        Args:
            name: Profile name
            description: Profile description
            genie_space: Genie space config (optional - enables data queries)
            ai_infra: AI infrastructure config (optional, uses defaults)
            mlflow: MLflow config (optional, auto-generated)
            prompts: Prompts config (optional, uses defaults)
            user: User creating the profile
            
        Returns:
            Created profile with all configurations
        """
        # Check if a default profile already exists
        has_default = (
            self.db.query(ConfigProfile)
            .filter(ConfigProfile.is_default == True)
            .first()
            is not None
        )

        # Create profile
        profile = ConfigProfile(
            name=name,
            description=description,
            is_default=not has_default,
            created_by=user,
            updated_by=user,
        )
        self.db.add(profile)
        self.db.flush()

        # Create AI infrastructure (use provided or defaults)
        ai_config = ai_infra or {}
        ai_infra_record = ConfigAIInfra(
            profile_id=profile.id,
            llm_endpoint=ai_config.get("llm_endpoint") or DEFAULT_CONFIG["llm"]["endpoint"],
            llm_temperature=ai_config.get("llm_temperature") if ai_config.get("llm_temperature") is not None else DEFAULT_CONFIG["llm"]["temperature"],
            llm_max_tokens=ai_config.get("llm_max_tokens") or DEFAULT_CONFIG["llm"]["max_tokens"],
        )
        self.db.add(ai_infra_record)

        # Create Genie space (optional - profiles without Genie run in prompt-only mode)
        if genie_space:
            genie_record = ConfigGenieSpace(
                profile_id=profile.id,
                space_id=genie_space["space_id"],
                space_name=genie_space["space_name"],
                description=genie_space.get("description"),
            )
            self.db.add(genie_record)

        # Create MLflow (use provided or auto-generate)
        mlflow_config = mlflow or {}
        experiment_name = mlflow_config.get("experiment_name") or f"/Workspace/Users/{user}/ai-slide-generator"
        mlflow_record = ConfigMLflow(
            profile_id=profile.id,
            experiment_name=experiment_name,
        )
        self.db.add(mlflow_record)

        # Create prompts (use provided or defaults)
        prompts_config = prompts or {}
        prompts_record = ConfigPrompts(
            profile_id=profile.id,
            system_prompt=prompts_config.get("system_prompt") or DEFAULT_CONFIG["prompts"]["system_prompt"],
            slide_editing_instructions=prompts_config.get("slide_editing_instructions") or DEFAULT_CONFIG["prompts"]["slide_editing_instructions"],
            selected_deck_prompt_id=prompts_config.get("selected_deck_prompt_id"),
            selected_slide_style_id=prompts_config.get("selected_slide_style_id"),
        )
        self.db.add(prompts_record)

        # Log creation
        history = ConfigHistory(
            profile_id=profile.id,
            domain="profile",
            action="create_with_config",
            changed_by=user,
            changes={
                "name": {"old": None, "new": name}, 
                "genie_space": genie_space["space_id"] if genie_space else None,
                "prompt_only_mode": genie_space is None,
            },
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
        
        Copies all configuration from the source profile including
        AI infrastructure, Genie space, MLflow, and prompts.
        
        Args:
            profile_id: Profile to duplicate
            new_name: Name for new profile
            user: User creating the duplicate
            
        Returns:
            New profile
        """
        source_profile = self.get_profile(profile_id)
        if not source_profile:
            raise ValueError(f"Source profile {profile_id} not found")

        # Check if a default profile already exists
        has_default = (
            self.db.query(ConfigProfile)
            .filter(ConfigProfile.is_default == True)
            .first()
            is not None
        )

        # Create new profile
        profile = ConfigProfile(
            name=new_name,
            description=f"Copy of {source_profile.name}",
            is_default=not has_default,
            created_by=user,
            updated_by=user,
        )
        self.db.add(profile)
        self.db.flush()

        # Copy AI infrastructure
        ai_infra = ConfigAIInfra(
            profile_id=profile.id,
            llm_endpoint=source_profile.ai_infra.llm_endpoint,
            llm_temperature=source_profile.ai_infra.llm_temperature,
            llm_max_tokens=source_profile.ai_infra.llm_max_tokens,
        )
        self.db.add(ai_infra)

        # Copy Genie space if exists
        if source_profile.genie_spaces:
            space = source_profile.genie_spaces[0]
            new_space = ConfigGenieSpace(
                profile_id=profile.id,
                space_id=space.space_id,
                space_name=space.space_name,
                description=space.description,
            )
            self.db.add(new_space)

        # Copy MLflow config
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
            selected_deck_prompt_id=source_profile.prompts.selected_deck_prompt_id,
            selected_slide_style_id=source_profile.prompts.selected_slide_style_id,
        )
        self.db.add(prompts)

        # Log creation
        history = ConfigHistory(
            profile_id=profile.id,
            domain="profile",
            action="duplicate",
            changed_by=user,
            changes={"source_profile_id": profile_id, "name": new_name},
        )
        self.db.add(history)

        self.db.commit()
        self.db.refresh(profile)

        return profile

