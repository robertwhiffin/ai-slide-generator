"""Configuration validation API endpoints."""
import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from src.services.config import validate_profile_configuration
from src.services.config.config_validator import ConfigValidator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/validate", tags=["validation"])


class LLMValidateRequest(BaseModel):
    """Request model for LLM validation."""
    endpoint: str


class GenieValidateRequest(BaseModel):
    """Request model for Genie validation."""
    space_id: str


class MLflowValidateRequest(BaseModel):
    """Request model for MLflow validation."""
    experiment_name: str


@router.post("/{profile_id}", response_model=Dict[str, Any])
def validate_profile(profile_id: int):
    """
    Validate all components of a profile configuration.
    
    This endpoint tests:
    1. LLM endpoint connectivity with a test message
    2. Genie space query execution
    3. MLflow experiment creation/write permissions
    
    Args:
        profile_id: Profile ID to validate
        
    Returns:
        Dictionary with validation results for each component
        
    Example response:
        {
            "success": true,
            "profile_id": 1,
            "profile_name": "default",
            "results": [
                {
                    "component": "LLM",
                    "success": true,
                    "message": "Successfully connected to LLM endpoint: databricks-claude-sonnet-4-5",
                    "details": "Response received: Hello! How can I help you today?..."
                },
                {
                    "component": "Genie",
                    "success": true,
                    "message": "Successfully connected to Genie space: 01abc123...",
                    "details": "Query executed and returned data"
                },
                {
                    "component": "MLflow",
                    "success": true,
                    "message": "Successfully accessed MLflow experiment: /Workspace/Users/...",
                    "details": "Experiment ID: 12345"
                }
            ]
        }
    """
    try:
        logger.info(f"Starting validation for profile {profile_id}")
        result = validate_profile_configuration(profile_id)
        
        if result.get("success"):
            logger.info(f"Profile {profile_id} validation successful")
            return result
        else:
            logger.warning(f"Profile {profile_id} validation failed")
            return result
            
    except Exception as e:
        logger.error(f"Error validating profile {profile_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to validate profile: {str(e)}",
        )


@router.post("/llm", response_model=Dict[str, Any])
def validate_llm(request: LLMValidateRequest):
    """
    Validate LLM endpoint connectivity.
    
    Args:
        request: LLM validation request with endpoint name
        
    Returns:
        Validation result with success status and details
    """
    try:
        logger.info(f"Validating LLM endpoint: {request.endpoint}")
        validator = ConfigValidator()
        result = validator.validate_llm_endpoint(request.endpoint)
        
        return {
            "success": result.valid,
            "message": result.message if result.valid else result.error,
            "details": result.details,
        }
        
    except Exception as e:
        logger.error(f"Error validating LLM endpoint: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to validate LLM endpoint: {str(e)}",
        )


@router.post("/genie", response_model=Dict[str, Any])
def validate_genie(request: GenieValidateRequest):
    """
    Validate Genie space connectivity.
    
    Args:
        request: Genie validation request with space ID
        
    Returns:
        Validation result with success status and details
    """
    try:
        logger.info(f"Validating Genie space: {request.space_id}")
        validator = ConfigValidator()
        result = validator.validate_genie_space(request.space_id)
        
        return {
            "success": result.valid,
            "message": result.message if result.valid else result.error,
            "details": result.details,
        }
        
    except Exception as e:
        logger.error(f"Error validating Genie space: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to validate Genie space: {str(e)}",
        )


@router.post("/mlflow", response_model=Dict[str, Any])
def validate_mlflow(request: MLflowValidateRequest):
    """
    Validate MLflow experiment accessibility.
    
    Args:
        request: MLflow validation request with experiment name
        
    Returns:
        Validation result with success status and details
    """
    try:
        logger.info(f"Validating MLflow experiment: {request.experiment_name}")
        validator = ConfigValidator()
        result = validator.validate_mlflow_experiment(request.experiment_name)
        
        return {
            "success": result.valid,
            "message": result.message if result.valid else result.error,
            "details": result.details,
        }
        
    except Exception as e:
        logger.error(f"Error validating MLflow experiment: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to validate MLflow experiment: {str(e)}",
        )

