"""Profile management API endpoints."""
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.api.schemas.settings import (
    ProfileCreate,
    ProfileCreateWithConfig,
    ProfileDetail,
    ProfileDuplicate,
    ProfileSummary,
    ProfileUpdate,
)
from src.api.services.chat_service import ChatService, get_chat_service
from src.core.database import get_db
from src.core.permission_context import get_permission_context
from src.services import ProfileService
from src.services.permission_service import PermissionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/profiles", tags=["profiles"])


def get_profile_service(db: Session = Depends(get_db)) -> ProfileService:
    """Dependency to get ProfileService."""
    return ProfileService(db)


def get_permission_service(db: Session = Depends(get_db)) -> PermissionService:
    """Dependency to get PermissionService."""
    return PermissionService(db)


def _get_current_user_info() -> tuple[str, Optional[str]]:
    """Get current user's username and Databricks ID.
    
    Returns:
        Tuple of (username, user_databricks_id)
    """
    ctx = get_permission_context()
    if ctx and ctx.user_name:
        return ctx.user_name, ctx.user_id
    
    # Fallback for dev/test
    if os.getenv("ENVIRONMENT") in ("development", "test"):
        return "system", None
    
    # Try to get from Databricks client
    try:
        from src.core.databricks_client import get_user_client
        client = get_user_client()
        me = client.current_user.me()
        return me.user_name, me.id
    except Exception:
        return "system", None


@router.get("", response_model=List[ProfileSummary])
def list_profiles(service: ProfileService = Depends(get_profile_service)):
    """
    List configuration profiles accessible to the current user.
    
    Returns profiles where the user has at least CAN_VIEW permission,
    including the user's permission level on each profile.
    
    Returns:
        List of profile summaries with permission levels
    """
    try:
        profiles_with_perms = service.list_accessible_profiles()
        
        # Convert to response model with permission
        result = []
        for profile, permission in profiles_with_perms:
            summary = ProfileSummary(
                id=profile.id,
                name=profile.name,
                description=profile.description,
                is_default=profile.is_default,
                created_at=profile.created_at,
                created_by=profile.created_by,
                updated_at=profile.updated_at,
                updated_by=profile.updated_by,
                my_permission=permission.value,
            )
            result.append(summary)
        
        return result
    except Exception as e:
        logger.error(f"Error listing profiles: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list profiles",
        )


@router.get("/default", response_model=ProfileDetail)
def get_default_profile(service: ProfileService = Depends(get_profile_service)):
    """
    Get the default configuration profile.
    
    Returns:
        Default profile with all configurations
        
    Raises:
        404: No default profile found
    """
    try:
        profile = service.get_default_profile()
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No default profile found",
            )
        return profile
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting default profile: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get default profile",
        )


@router.get("/{profile_id}", response_model=ProfileDetail)
def get_profile(
    profile_id: int,
    service: ProfileService = Depends(get_profile_service),
    perm_service: PermissionService = Depends(get_permission_service),
):
    """
    Get profile by ID with all configurations.
    
    Requires at least CAN_VIEW permission on the profile.
    
    Args:
        profile_id: Profile ID
        
    Returns:
        Profile detail with all configurations and user's permission level
        
    Raises:
        403: No permission to view this profile
        404: Profile not found
    """
    try:
        # Check existence first
        profile = service.get_profile(profile_id)
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Profile {profile_id} not found",
            )
        
        # Then check permission
        perm_service.require_view(profile_id)
        permission = perm_service.get_current_user_permission(profile_id)
        
        # Convert ORM object to response with permission
        return ProfileDetail(
            id=profile.id,
            name=profile.name,
            description=profile.description,
            is_default=profile.is_default,
            created_at=profile.created_at,
            created_by=profile.created_by,
            updated_at=profile.updated_at,
            updated_by=profile.updated_by,
            ai_infra=profile.ai_infra,
            genie_spaces=profile.genie_spaces,
            prompts=profile.prompts,
            my_permission=permission.value if permission else None,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting profile {profile_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get profile",
        )


@router.post("", response_model=ProfileDetail, status_code=status.HTTP_201_CREATED)
def create_profile(
    request: ProfileCreate,
    service: ProfileService = Depends(get_profile_service),
):
    """
    Create a new configuration profile.
    
    The creator is automatically added as a CAN_MANAGE contributor.
    
    Args:
        request: Profile creation request
        
    Returns:
        Created profile with default configurations.
        Note: Genie space must be configured separately after creation.
        
    Raises:
        400: Invalid request
        409: Profile name already exists
    """
    try:
        user, user_databricks_id = _get_current_user_info()

        profile = service.create_profile(
            name=request.name,
            description=request.description,
            user=user,
            user_databricks_id=user_databricks_id,
        )
        return profile
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error creating profile: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create profile",
        )


@router.post("/with-config", response_model=ProfileDetail, status_code=status.HTTP_201_CREATED)
def create_profile_with_config(
    request: ProfileCreateWithConfig,
    service: ProfileService = Depends(get_profile_service),
):
    """
    Create a new profile with all configurations in one request.
    
    Used by the creation wizard for complete profile setup.
    The creator is automatically added as a CAN_MANAGE contributor.
    
    Args:
        request: Profile creation request with inline configurations
        
    Returns:
        Created profile with all configurations
        
    Raises:
        400: Invalid request
        409: Profile name already exists
    """
    try:
        user, user_databricks_id = _get_current_user_info()

        profile = service.create_profile_with_config(
            name=request.name,
            description=request.description,
            genie_space={
                "space_id": request.genie_space.space_id,
                "space_name": request.genie_space.space_name,
                "description": request.genie_space.description,
            } if request.genie_space else None,
            ai_infra={
                "llm_endpoint": request.ai_infra.llm_endpoint,
                "llm_temperature": request.ai_infra.llm_temperature,
                "llm_max_tokens": request.ai_infra.llm_max_tokens,
            } if request.ai_infra else None,
            prompts={
                "selected_deck_prompt_id": request.prompts.selected_deck_prompt_id,
                "selected_slide_style_id": request.prompts.selected_slide_style_id,
                "system_prompt": request.prompts.system_prompt,
                "slide_editing_instructions": request.prompts.slide_editing_instructions,
            } if request.prompts else None,
            user=user,
            user_databricks_id=user_databricks_id,
        )
        return profile
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error creating profile with config: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create profile",
        )


@router.put("/{profile_id}", response_model=ProfileDetail)
def update_profile(
    profile_id: int,
    request: ProfileUpdate,
    service: ProfileService = Depends(get_profile_service),
    perm_service: PermissionService = Depends(get_permission_service),
):
    """
    Update profile metadata.
    
    Requires CAN_EDIT permission on the profile.
    
    Args:
        profile_id: Profile ID
        request: Profile update request
        
    Returns:
        Updated profile
        
    Raises:
        403: No permission to edit this profile
        404: Profile not found
        400: Invalid request
    """
    try:
        # Check permission first
        perm_service.require_edit(profile_id)
        
        user, _ = _get_current_user_info()

        profile = service.update_profile(
            profile_id=profile_id,
            name=request.name,
            description=request.description,
            user=user,
        )
        return profile
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND if "not found" in str(e).lower() else status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error updating profile {profile_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update profile",
        )


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(
    profile_id: int,
    service: ProfileService = Depends(get_profile_service),
    perm_service: PermissionService = Depends(get_permission_service),
):
    """
    Delete a configuration profile.
    
    Requires CAN_MANAGE permission on the profile.
    
    Args:
        profile_id: Profile ID
        
    Raises:
        403: No permission to manage this profile / Cannot delete default
        404: Profile not found
    """
    try:
        # Check permission first
        perm_service.require_manage(profile_id)
        
        user, _ = _get_current_user_info()

        service.delete_profile(profile_id=profile_id, user=user)
    except HTTPException:
        raise
    except ValueError as e:
        error_msg = str(e).lower()
        if "not found" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e),
            )
        elif "cannot delete" in error_msg or "default" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(e),
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )
    except Exception as e:
        logger.error(f"Error deleting profile {profile_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete profile",
        )


@router.post("/{profile_id}/set-default", response_model=ProfileDetail)
def set_default_profile(
    profile_id: int,
    service: ProfileService = Depends(get_profile_service),
    perm_service: PermissionService = Depends(get_permission_service),
):
    """
    Set profile as the user's default.
    
    Any user with at least CAN_VIEW permission can set a profile as their default.
    
    Args:
        profile_id: Profile ID to set as default
        
    Returns:
        Updated profile
        
    Raises:
        403: No permission to view this profile
        404: Profile not found
    """
    try:
        # Only need view permission to set as default
        perm_service.require_view(profile_id)
        
        user, _ = _get_current_user_info()

        profile = service.set_default_profile(profile_id=profile_id, user=user)
        return profile
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error setting default profile {profile_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to set default profile",
        )


@router.post("/{profile_id}/duplicate", response_model=ProfileDetail, status_code=status.HTTP_201_CREATED)
def duplicate_profile(
    profile_id: int,
    request: ProfileDuplicate,
    service: ProfileService = Depends(get_profile_service),
    perm_service: PermissionService = Depends(get_permission_service),
):
    """
    Duplicate a profile with a new name.
    
    Requires CAN_VIEW permission on the source profile.
    The current user becomes the owner (CAN_MANAGE) of the new profile.
    
    Args:
        profile_id: Source profile ID
        request: Duplication request with new name
        
    Returns:
        New profile with copied configurations
        
    Raises:
        403: No permission to view source profile
        404: Source profile not found
        409: Profile name already exists
    """
    try:
        # Need view permission on source profile
        perm_service.require_view(profile_id)
        
        user, _ = _get_current_user_info()

        profile = service.duplicate_profile(
            profile_id=profile_id,
            new_name=request.new_name,
            user=user,
        )
        return profile
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND if "not found" in str(e).lower() else status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error duplicating profile {profile_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to duplicate profile",
        )


@router.post("/{profile_id}/load", response_model=Dict[str, Any])
def load_profile(
    profile_id: int,
    service: ProfileService = Depends(get_profile_service),
    chat_service: ChatService = Depends(get_chat_service),
    perm_service: PermissionService = Depends(get_permission_service),
):
    """
    Load profile and reload application with new configuration.
    
    Requires CAN_VIEW permission on the profile.
    This performs a hot-reload of the application configuration from the database,
    updating the LLM, Genie, MLflow, and prompts settings to match the specified profile.
    Active sessions and conversation state are preserved during the reload.
    
    Args:
        profile_id: Profile ID to load
        
    Returns:
        Dictionary with reload status and profile information
        
    Raises:
        403: No permission to view this profile
        404: Profile not found
        500: Reload failed
    """
    try:
        # Check permission first
        perm_service.require_view(profile_id)
        
        profile = service.get_profile(profile_id)
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Profile {profile_id} not found",
            )

        if profile.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Profile {profile_id} has been deleted",
            )

        logger.info(
            "Loading profile configuration",
            extra={"profile_id": profile_id, "profile_name": profile.name},
        )

        # Reload agent with new profile
        result = chat_service.reload_agent(profile_id)

        logger.info(
            "Profile loaded successfully",
            extra={"profile_id": profile_id, "profile_name": profile.name},
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error loading profile {profile_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load profile: {str(e)}",
        )


@router.post("/reload", response_model=Dict[str, Any])
def reload_configuration(
    profile_id: Optional[int] = None,
    chat_service: ChatService = Depends(get_chat_service),
):
    """
    Reload configuration from database.
    
    If profile_id is provided, loads that specific profile.
    Otherwise, reloads the current default profile.
    
    This allows hot-reload of configuration without restarting the application.
    Useful after updating configuration through the admin UI.
    
    Args:
        profile_id: Optional profile ID to load (None = reload default)
        
    Returns:
        Dictionary with reload status and profile information
        
    Raises:
        500: Reload failed
    """
    try:
        logger.info(
            "Reloading configuration",
            extra={"profile_id": profile_id or "default"},
        )

        result = chat_service.reload_agent(profile_id)

        logger.info(
            "Configuration reloaded successfully",
            extra={"profile_id": result["profile_id"]},
        )

        return result

    except Exception as e:
        logger.error(f"Error reloading configuration: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reload configuration: {str(e)}",
        )

