"""Profile management service."""
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session, joinedload

from src.core.defaults import DEFAULT_CONFIG
from src.core.permission_context import get_permission_context
from src.database.models import (
    ConfigAIInfra,
    ConfigGenieSpace,
    ConfigProfile,
    ConfigProfileContributor,
    ConfigPrompts,
    SlideStyleLibrary,
    UserProfilePreference,
)
from src.database.models.profile_contributor import PermissionLevel


class ProfileService:
    """Manage configuration profiles."""

    def __init__(self, db: Session):
        self.db = db

    def list_profiles(self) -> List[ConfigProfile]:
        """Get all active (non-deleted) profiles.
        
        WARNING: This returns ALL profiles without permission filtering.
        Use list_accessible_profiles() for user-filtered results.
        """
        return (
            self.db.query(ConfigProfile)
            .filter(ConfigProfile.is_deleted == False)  # noqa: E712
            .order_by(ConfigProfile.name)
            .all()
        )

    def list_accessible_profiles(self) -> List[Tuple[ConfigProfile, PermissionLevel]]:
        """Get profiles the current user has access to, with permission levels.
        
        Checks the permission context from the current request and returns
        only profiles where the user has at least CAN_VIEW permission.
        
        Returns:
            List of (profile, permission_level) tuples
        """
        from src.services.permission_service import PermissionService
        
        ctx = get_permission_context()
        if not ctx:
            return []
        
        perm_service = PermissionService(self.db)
        return perm_service.get_profiles_with_permissions(
            user_id=ctx.user_id,
            user_name=ctx.user_name,
            group_ids=ctx.group_ids,
        )

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
                joinedload(ConfigProfile.prompts),
            )
            .filter(ConfigProfile.id == profile_id)
            .first()
        )

    def get_default_profile(self) -> Optional[ConfigProfile]:
        """Get the default profile for the current user.

        Resolution order:
        1. User's personal preference (user_profile_preferences table)
        2. Global is_default flag (system fallback)
        3. First accessible profile (final fallback)
        """
        ctx = get_permission_context()
        if ctx and ctx.user_name:
            pref = (
                self.db.query(UserProfilePreference)
                .filter(UserProfilePreference.user_name == ctx.user_name)
                .first()
            )
            if pref and pref.default_profile_id:
                profile = (
                    self.db.query(ConfigProfile)
                    .options(
                        joinedload(ConfigProfile.ai_infra),
                        joinedload(ConfigProfile.genie_spaces),
                        joinedload(ConfigProfile.prompts),
                    )
                    .filter(
                        ConfigProfile.id == pref.default_profile_id,
                        ConfigProfile.is_deleted == False,  # noqa: E712
                    )
                    .first()
                )
                if profile:
                    return profile

        return (
            self.db.query(ConfigProfile)
            .options(
                joinedload(ConfigProfile.ai_infra),
                joinedload(ConfigProfile.genie_spaces),
                joinedload(ConfigProfile.prompts),
            )
            .filter(ConfigProfile.is_default == True, ConfigProfile.is_deleted == False)  # noqa: E712
            .first()
        )

    def get_user_default_profile_id(self, user_name: str) -> Optional[int]:
        """Get the profile ID that a user has set as their personal default."""
        pref = (
            self.db.query(UserProfilePreference)
            .filter(UserProfilePreference.user_name == user_name)
            .first()
        )
        return pref.default_profile_id if pref else None

    def create_profile(
        self,
        name: str,
        description: Optional[str],
        user: str,
        user_databricks_id: Optional[str] = None,
    ) -> ConfigProfile:
        """
        Create new profile.
        
        If no default profile exists, the new profile will be set as default.
        New profiles require explicit Genie space configuration - no default is created.
        The creator is automatically added as a CAN_MANAGE contributor.
        
        Args:
            name: Profile name
            description: Profile description
            user: User creating the profile (username/email)
            user_databricks_id: Optional Databricks user ID for contributor entry
            
        Returns:
            Created profile
            
        Raises:
            ValueError: If profile name already exists
        """
        # Check for duplicate name
        existing = (
            self.db.query(ConfigProfile)
            .filter(ConfigProfile.name == name)
            .first()
        )
        if existing:
            raise ValueError(f"Profile with name '{name}' already exists")
        
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

        # Auto-add creator as CAN_MANAGE contributor
        # Use databricks_id if available, otherwise use username as identity_id
        contributor = ConfigProfileContributor(
            profile_id=profile.id,
            identity_id=user_databricks_id or user,
            identity_type="USER",
            identity_name=user,
            permission_level=PermissionLevel.CAN_MANAGE.value,
            created_by=user,
        )
        self.db.add(contributor)

        # Use defaults for AI infrastructure
        ai_infra = ConfigAIInfra(
            profile_id=profile.id,
            llm_endpoint=DEFAULT_CONFIG["llm"]["endpoint"],
            llm_temperature=DEFAULT_CONFIG["llm"]["temperature"],
            llm_max_tokens=DEFAULT_CONFIG["llm"]["max_tokens"],
        )
        self.db.add(ai_infra)

        # NO default Genie space - user must explicitly configure one

        # Get the first active slide style as default (required for agent to function)
        default_style = self.db.query(SlideStyleLibrary).filter_by(is_active=True).first()

        # Use default prompts with default slide style
        prompts = ConfigPrompts(
            profile_id=profile.id,
            system_prompt=DEFAULT_CONFIG["prompts"]["system_prompt"],
            slide_editing_instructions=DEFAULT_CONFIG["prompts"]["slide_editing_instructions"],
            selected_slide_style_id=default_style.id if default_style else None,
        )
        self.db.add(prompts)

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
        """
        Update profile metadata.
        
        Raises:
            ValueError: If profile not found or new name already exists
        """
        profile = self.get_profile(profile_id)
        if not profile:
            raise ValueError(f"Profile {profile_id} not found")

        changes = {}

        if name and name != profile.name:
            # Check for duplicate name
            existing = (
                self.db.query(ConfigProfile)
                .filter(ConfigProfile.name == name, ConfigProfile.id != profile_id)
                .first()
            )
            if existing:
                raise ValueError(f"Profile with name '{name}' already exists")
            
            changes["name"] = {"old": profile.name, "new": name}
            profile.name = name

        if description is not None and description != profile.description:
            changes["description"] = {"old": profile.description, "new": description}
            profile.description = description

        if changes:
            profile.updated_by = user

        self.db.commit()
        self.db.refresh(profile)

        return profile

    def delete_profile(self, profile_id: int, user: str) -> None:
        """
        Soft-delete profile.
        
        Marks the profile as deleted rather than removing it, so sessions
        that reference the profile can still display its name and be opened
        in read-only mode.
        
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

        profile.is_deleted = True
        profile.deleted_at = datetime.utcnow()
        profile.is_default = False
        profile.updated_by = user

        self.db.commit()

    def set_default_profile(self, profile_id: int, user: str) -> ConfigProfile:
        """Set a profile as the current user's personal default.

        Writes to the per-user user_profile_preferences table instead of
        toggling the global is_default flag.

        Args:
            profile_id: Profile to set as default
            user: Username making the change
            
        Returns:
            The profile that was set as default
        """
        profile = self.get_profile(profile_id)
        if not profile:
            raise ValueError(f"Profile {profile_id} not found")

        if profile.is_deleted:
            raise ValueError("Cannot set a deleted profile as default")

        pref = (
            self.db.query(UserProfilePreference)
            .filter(UserProfilePreference.user_name == user)
            .first()
        )
        if pref:
            pref.default_profile_id = profile_id
        else:
            pref = UserProfilePreference(
                user_name=user,
                default_profile_id=profile_id,
            )
            self.db.add(pref)

        self.db.commit()
        self.db.refresh(profile)

        return profile

    def create_profile_with_config(
        self,
        name: str,
        description: Optional[str],
        genie_space: Optional[dict],
        ai_infra: Optional[dict],
        prompts: Optional[dict],
        user: str,
        user_databricks_id: Optional[str] = None,
    ) -> ConfigProfile:
        """
        Create profile with all configurations in one transaction.
        
        Used by the creation wizard for complete profile setup.
        The creator is automatically added as a CAN_MANAGE contributor.
        
        Args:
            name: Profile name
            description: Profile description
            genie_space: Genie space config (optional - enables data queries)
            ai_infra: AI infrastructure config (optional, uses defaults)
            prompts: Prompts config (optional, uses defaults)
            user: User creating the profile (username/email)
            user_databricks_id: Optional Databricks user ID for contributor entry
            
        Returns:
            Created profile with all configurations
            
        Raises:
            ValueError: If profile name already exists
        """
        # Check for duplicate name
        existing = (
            self.db.query(ConfigProfile)
            .filter(ConfigProfile.name == name)
            .first()
        )
        if existing:
            raise ValueError(f"Profile with name '{name}' already exists")
        
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

        # Auto-add creator as CAN_MANAGE contributor
        contributor = ConfigProfileContributor(
            profile_id=profile.id,
            identity_id=user_databricks_id or user,
            identity_type="USER",
            identity_name=user,
            permission_level=PermissionLevel.CAN_MANAGE.value,
            created_by=user,
        )
        self.db.add(contributor)

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
            
        Raises:
            ValueError: If source profile not found or new name already exists
        """
        source_profile = self.get_profile(profile_id)
        if not source_profile:
            raise ValueError(f"Source profile {profile_id} not found")
        
        # Check for duplicate name
        existing = (
            self.db.query(ConfigProfile)
            .filter(ConfigProfile.name == new_name)
            .first()
        )
        if existing:
            raise ValueError(f"Profile with name '{new_name}' already exists")

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

        # Copy prompts
        prompts = ConfigPrompts(
            profile_id=profile.id,
            system_prompt=source_profile.prompts.system_prompt,
            slide_editing_instructions=source_profile.prompts.slide_editing_instructions,
            selected_deck_prompt_id=source_profile.prompts.selected_deck_prompt_id,
            selected_slide_style_id=source_profile.prompts.selected_slide_style_id,
        )
        self.db.add(prompts)

        self.db.commit()
        self.db.refresh(profile)

        return profile

