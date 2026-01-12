"""Profile management API endpoints."""
import logging
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
from src.services import ProfileService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/profiles", tags=["profiles"])


def get_profile_service(db: Session = Depends(get_db)) -> ProfileService:
    """Dependency to get ProfileService."""
    return ProfileService(db)


@router.get("", response_model=List[ProfileSummary])
def list_profiles(service: ProfileService = Depends(get_profile_service)):
    """
    List all configuration profiles.
    
    Returns:
        List of profile summaries
    """
    try:
        profiles = service.list_profiles()
        return profiles
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
):
    """
    Get profile by ID with all configurations.
    
    Args:
        profile_id: Profile ID
        
    Returns:
        Profile detail with all configurations
        
    Raises:
        404: Profile not found
    """
    try:
        profile = service.get_profile(profile_id)
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Profile {profile_id} not found",
            )
        return profile
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
    
    Args:
        request: Profile creation request
        
    Returns:
        Created profile with default configurations.
        Note: Genie space must be configured separately after creation.
        MLflow experiment name is auto-set based on creator's username.
        
    Raises:
        400: Invalid request
        409: Profile name already exists
    """
    try:
        # Get the current user from Databricks for MLflow experiment path
        try:
            from src.core.databricks_client import get_databricks_client
            client = get_databricks_client()
            user = client.current_user.me().user_name
        except Exception:
            user = "system"

        profile = service.create_profile(
            name=request.name,
            description=request.description,
            user=user,
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
    Genie space is required; other configurations have defaults.
    
    Args:
        request: Profile creation request with inline configurations
        
    Returns:
        Created profile with all configurations
        
    Raises:
        400: Invalid request
        409: Profile name already exists
    """
    try:
        # Get the current user from Databricks
        try:
            from src.core.databricks_client import get_databricks_client
            client = get_databricks_client()
            user = client.current_user.me().user_name
        except Exception:
            user = "system"

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
            mlflow={
                "experiment_name": request.mlflow.experiment_name,
            } if request.mlflow else None,
            prompts={
                "selected_deck_prompt_id": request.prompts.selected_deck_prompt_id,
                "selected_slide_style_id": request.prompts.selected_slide_style_id,
                "system_prompt": request.prompts.system_prompt,
                "slide_editing_instructions": request.prompts.slide_editing_instructions,
            } if request.prompts else None,
            user=user,
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
):
    """
    Update profile metadata.
    
    Args:
        profile_id: Profile ID
        request: Profile update request
        
    Returns:
        Updated profile
        
    Raises:
        404: Profile not found
        400: Invalid request
    """
    try:
        # TODO: Get actual user from authentication
        user = "system"

        profile = service.update_profile(
            profile_id=profile_id,
            name=request.name,
            description=request.description,
            user=user,
        )
        return profile
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
):
    """
    Delete a configuration profile.
    
    Args:
        profile_id: Profile ID
        
    Raises:
        404: Profile not found
        403: Cannot delete default profile
    """
    try:
        # TODO: Get actual user from authentication
        user = "system"

        service.delete_profile(profile_id=profile_id, user=user)
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
):
    """
    Set profile as the default.
    
    Args:
        profile_id: Profile ID to set as default
        
    Returns:
        Updated profile
        
    Raises:
        404: Profile not found
    """
    try:
        # TODO: Get actual user from authentication
        user = "system"

        profile = service.set_default_profile(profile_id=profile_id, user=user)
        return profile
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
):
    """
    Duplicate a profile with a new name.
    
    Args:
        profile_id: Source profile ID
        request: Duplication request with new name
        
    Returns:
        New profile with copied configurations
        
    Raises:
        404: Source profile not found
        409: Profile name already exists
    """
    try:
        # TODO: Get actual user from authentication
        user = "system"

        profile = service.duplicate_profile(
            profile_id=profile_id,
            new_name=request.new_name,
            user=user,
        )
        return profile
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
):
    """
    Load profile and reload application with new configuration.
    
    This performs a hot-reload of the application configuration from the database,
    updating the LLM, Genie, MLflow, and prompts settings to match the specified profile.
    Active sessions and conversation state are preserved during the reload.
    
    Args:
        profile_id: Profile ID to load
        
    Returns:
        Dictionary with reload status and profile information
        
    Raises:
        404: Profile not found
        500: Reload failed
    """
    # Verify profile exists
    try:
        profile = service.get_profile(profile_id)
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Profile {profile_id} not found",
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

