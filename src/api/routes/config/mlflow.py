"""MLflow configuration API endpoints."""
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.api.models.config import MLflowConfig, MLflowConfigUpdate
from src.config.database import get_db
from src.services.config import ConfigService, ConfigValidator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mlflow", tags=["mlflow"])


def get_config_service(db: Session = Depends(get_db)) -> ConfigService:
    """Dependency to get ConfigService."""
    return ConfigService(db)


@router.get("/{profile_id}", response_model=MLflowConfig)
def get_mlflow_config(
    profile_id: int,
    service: ConfigService = Depends(get_config_service),
):
    """
    Get MLflow configuration for a profile.
    
    Args:
        profile_id: Profile ID
        
    Returns:
        MLflow configuration
        
    Raises:
        404: Configuration not found
    """
    try:
        config = service.get_mlflow_config(profile_id)
        return config
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error getting MLflow config for profile {profile_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get MLflow configuration",
        )


@router.put("/{profile_id}", response_model=MLflowConfig)
def update_mlflow_config(
    profile_id: int,
    request: MLflowConfigUpdate,
    service: ConfigService = Depends(get_config_service),
):
    """
    Update MLflow configuration.
    
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
        # Validate
        validator = ConfigValidator()
        result = validator.validate_mlflow(request.experiment_name)
        if not result.valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.error,
            )

        # TODO: Get actual user from authentication
        user = "system"

        config = service.update_mlflow_config(
            profile_id=profile_id,
            experiment_name=request.experiment_name,
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
        logger.error(f"Error updating MLflow config for profile {profile_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update MLflow configuration",
        )

