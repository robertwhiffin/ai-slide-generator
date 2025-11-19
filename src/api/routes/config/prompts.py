"""Prompts configuration API endpoints."""
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.api.models.config import PromptsConfig, PromptsConfigUpdate
from src.config.database import get_db
from src.services.config import ConfigService, ConfigValidator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/prompts", tags=["prompts"])


def get_config_service(db: Session = Depends(get_db)) -> ConfigService:
    """Dependency to get ConfigService."""
    return ConfigService(db)


@router.get("/{profile_id}", response_model=PromptsConfig)
def get_prompts_config(
    profile_id: int,
    service: ConfigService = Depends(get_config_service),
):
    """
    Get prompts configuration for a profile.
    
    Args:
        profile_id: Profile ID
        
    Returns:
        Prompts configuration
        
    Raises:
        404: Configuration not found
    """
    try:
        config = service.get_prompts_config(profile_id)
        return config
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error getting prompts config for profile {profile_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get prompts configuration",
        )


@router.put("/{profile_id}", response_model=PromptsConfig)
def update_prompts_config(
    profile_id: int,
    request: PromptsConfigUpdate,
    service: ConfigService = Depends(get_config_service),
):
    """
    Update prompts configuration.
    
    Args:
        profile_id: Profile ID
        request: Configuration update request
        
    Returns:
        Updated configuration
        
    Raises:
        404: Configuration not found
        400: Validation failed (missing required placeholders)
    """
    try:
        # Validate
        validator = ConfigValidator()
        result = validator.validate_prompts(
            system_prompt=request.system_prompt,
            user_prompt_template=request.user_prompt_template,
        )
        if not result.valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.error,
            )
        
        # TODO: Get actual user from authentication
        user = "system"
        
        config = service.update_prompts_config(
            profile_id=profile_id,
            system_prompt=request.system_prompt,
            slide_editing_instructions=request.slide_editing_instructions,
            user_prompt_template=request.user_prompt_template,
            user=user,
        )
        return config
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating prompts config for profile {profile_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update prompts configuration",
        )

