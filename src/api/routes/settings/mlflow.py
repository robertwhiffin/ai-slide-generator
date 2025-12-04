"""MLflow configuration API endpoints."""
import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.api.schemas.settings import MLflowConfig, MLflowConfigUpdate
from src.core.database import get_db
from src.services import ConfigService, ConfigValidator
from src.services.config_validator import ConfigurationValidator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mlflow", tags=["mlflow"])


@router.post("/validate", response_model=Dict[str, Any])
def validate_mlflow_experiment(experiment_name: str):
    """
    Validate that an MLflow experiment is accessible and writable.
    
    Args:
        experiment_name: The MLflow experiment name/path to validate
        
    Returns:
        Dictionary with validation result:
        - success: Whether the experiment is valid and accessible
        - message: Description of the validation result
    """
    try:
        validator = ConfigurationValidator(profile_id=None)
        result = validator.validate_mlflow_experiment(experiment_name)
        
        return {
            "success": result.success,
            "message": result.message,
        }
        
    except Exception as e:
        logger.error(f"Error validating MLflow experiment {experiment_name}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to validate MLflow experiment: {str(e)}",
        )


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

