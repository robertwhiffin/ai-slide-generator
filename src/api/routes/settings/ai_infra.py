"""AI infrastructure configuration API endpoints."""
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.api.schemas.settings import AIInfraConfig, AIInfraConfigUpdate, EndpointsList
from src.core.database import get_db
from src.services import ConfigService, ConfigValidator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai-db_app_deployment", tags=["ai-infrastructure"])


def get_config_service(db: Session = Depends(get_db)) -> ConfigService:
    """Dependency to get ConfigService."""
    return ConfigService(db)


@router.get("/{profile_id}", response_model=AIInfraConfig)
def get_ai_infra_config(
    profile_id: int,
    service: ConfigService = Depends(get_config_service),
):
    """
    Get AI infrastructure configuration for a profile.
    
    Args:
        profile_id: Profile ID
        
    Returns:
        AI infrastructure configuration
        
    Raises:
        404: Configuration not found
    """
    try:
        config = service.get_ai_infra_config(profile_id)
        return config
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error getting AI db_app_deployment config for profile {profile_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get AI infrastructure configuration",
        )


@router.put("/{profile_id}", response_model=AIInfraConfig)
def update_ai_infra_config(
    profile_id: int,
    request: AIInfraConfigUpdate,
    service: ConfigService = Depends(get_config_service),
):
    """
    Update AI infrastructure configuration.
    
    Args:
        profile_id: Profile ID
        request: Configuration update request
        
    Returns:
        Updated configuration
        
    Raises:
        404: Configuration not found
        400: Validation failed
    """
    try:
        # Validate if any values provided
        if request.llm_endpoint or request.llm_temperature is not None or request.llm_max_tokens is not None:
            # Get current settings for validation
            current = service.get_ai_infra_config(profile_id)

            # Use current values if not provided in request
            endpoint = request.llm_endpoint or current.llm_endpoint
            temperature = request.llm_temperature if request.llm_temperature is not None else current.llm_temperature
            max_tokens = request.llm_max_tokens if request.llm_max_tokens is not None else current.llm_max_tokens

            # Validate
            validator = ConfigValidator()
            result = validator.validate_ai_infra(endpoint, temperature, max_tokens)
            if not result.valid:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=result.error,
                )

        # TODO: Get actual user from authentication
        user = "system"

        config = service.update_ai_infra_config(
            profile_id=profile_id,
            llm_endpoint=request.llm_endpoint,
            llm_temperature=request.llm_temperature,
            llm_max_tokens=request.llm_max_tokens,
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
        logger.error(f"Error updating AI db_app_deployment config for profile {profile_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update AI infrastructure configuration",
        )


@router.get("/endpoints/available", response_model=EndpointsList)
def get_available_endpoints(
    service: ConfigService = Depends(get_config_service),
):
    """
    Get list of available Databricks serving endpoints.
    
    Endpoints are sorted with databricks- prefixed endpoints first,
    followed by custom endpoints.
    
    Returns:
        List of endpoint names
    """
    try:
        endpoints = service.get_available_endpoints()
        return EndpointsList(endpoints=endpoints)
    except Exception as e:
        logger.error(f"Error getting available endpoints: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get available endpoints",
        )

