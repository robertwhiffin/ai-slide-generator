"""Genie space configuration API endpoints."""
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.api.models.config import GenieSpace, GenieSpaceCreate, GenieSpaceUpdate
from src.config.client import get_databricks_client
from src.config.database import get_db
from src.services.config import ConfigValidator, GenieService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/genie", tags=["genie-spaces"])


def get_genie_service(db: Session = Depends(get_db)) -> GenieService:
    """Dependency to get GenieService."""
    return GenieService(db)


@router.get("/available", response_model=Dict[str, Any])
def list_available_genie_spaces():
    """
    List all available Genie spaces from Databricks with descriptions.
    
    Returns:
        Dictionary with:
        - spaces: Dict mapping space IDs to space details (title, description)
        - sorted_titles: List of space titles sorted alphabetically
        
    Example:
        {
            "spaces": {
                "01ef1234...": {
                    "title": "Sales Analytics",
                    "description": "Sales data and metrics"
                }
            },
            "sorted_titles": ["Marketing Data", "Sales Analytics"]
        }
    """
    try:
        client = get_databricks_client()
        spaces_data = {}
        
        # Initial request
        response = client.genie.list_spaces()
        
        # Collect spaces from first page
        if response.spaces:
            for space in response.spaces:
                spaces_data[space.space_id] = {
                    "title": space.title,
                    "description": space.description or "",
                }
        
        # Handle pagination
        while response.next_page_token:
            response = client.genie.list_spaces(page_token=response.next_page_token)
            if response.spaces:
                for space in response.spaces:
                    spaces_data[space.space_id] = {
                        "title": space.title,
                        "description": space.description or "",
                    }
        
        # Sort titles alphabetically
        sorted_titles = sorted([details["title"] for details in spaces_data.values()])
        
        logger.info(f"Found {len(spaces_data)} available Genie spaces")
        return {
            "spaces": spaces_data,
            "sorted_titles": sorted_titles,
        }
        
    except Exception as e:
        logger.error(f"Error listing available Genie spaces: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list available Genie spaces: {str(e)}",
        )


@router.get("/{profile_id}", response_model=List[GenieSpace])
def list_genie_spaces(
    profile_id: int,
    service: GenieService = Depends(get_genie_service),
):
    """
    List all Genie spaces for a profile.
    
    Spaces are sorted with default space first, then alphabetically.
    
    Args:
        profile_id: Profile ID
        
    Returns:
        List of Genie spaces
    """
    try:
        spaces = service.list_genie_spaces(profile_id)
        return spaces
    except Exception as e:
        logger.error(f"Error listing Genie spaces for profile {profile_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list Genie spaces",
        )


@router.get("/{profile_id}/default", response_model=GenieSpace)
def get_default_genie_space(
    profile_id: int,
    service: GenieService = Depends(get_genie_service),
):
    """
    Get default Genie space for a profile.
    
    Args:
        profile_id: Profile ID
        
    Returns:
        Default Genie space
        
    Raises:
        404: No default space found
    """
    try:
        space = service.get_default_genie_space(profile_id)
        if not space:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No default Genie space found for profile {profile_id}",
            )
        return space
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting default Genie space for profile {profile_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get default Genie space",
        )


@router.post("/{profile_id}", response_model=GenieSpace, status_code=status.HTTP_201_CREATED)
def add_genie_space(
    profile_id: int,
    request: GenieSpaceCreate,
    service: GenieService = Depends(get_genie_service),
):
    """
    Add a new Genie space to a profile.
    
    Args:
        profile_id: Profile ID
        request: Genie space creation request
        
    Returns:
        Created Genie space
        
    Raises:
        400: Validation failed
    """
    try:
        # Validate
        validator = ConfigValidator()
        result = validator.validate_genie_space(request.space_id)
        if not result.valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.error,
            )
        
        # TODO: Get actual user from authentication
        user = "system"
        
        space = service.add_genie_space(
            profile_id=profile_id,
            space_id=request.space_id,
            space_name=request.space_name,
            description=request.description,
            is_default=request.is_default,
            user=user,
        )
        return space
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding Genie space to profile {profile_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to add Genie space",
        )


@router.put("/space/{space_id}", response_model=GenieSpace)
def update_genie_space(
    space_id: int,
    request: GenieSpaceUpdate,
    service: GenieService = Depends(get_genie_service),
):
    """
    Update Genie space metadata.
    
    Args:
        space_id: Genie space ID (internal database ID)
        request: Update request
        
    Returns:
        Updated Genie space
        
    Raises:
        404: Space not found
    """
    try:
        # TODO: Get actual user from authentication
        user = "system"
        
        space = service.update_genie_space(
            space_id=space_id,
            space_name=request.space_name,
            description=request.description,
            user=user,
        )
        return space
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error updating Genie space {space_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update Genie space",
        )


@router.delete("/space/{space_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_genie_space(
    space_id: int,
    service: GenieService = Depends(get_genie_service),
):
    """
    Delete a Genie space.
    
    Args:
        space_id: Genie space ID (internal database ID)
        
    Raises:
        404: Space not found
        403: Cannot delete the only Genie space
    """
    try:
        # TODO: Get actual user from authentication
        user = "system"
        
        service.delete_genie_space(space_id=space_id, user=user)
    except ValueError as e:
        error_msg = str(e).lower()
        if "not found" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e),
            )
        elif "cannot delete" in error_msg or "only" in error_msg:
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
        logger.error(f"Error deleting Genie space {space_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete Genie space",
        )


@router.post("/space/{space_id}/set-default", response_model=GenieSpace)
def set_default_genie_space(
    space_id: int,
    service: GenieService = Depends(get_genie_service),
):
    """
    Set a Genie space as the default for its profile.
    
    Args:
        space_id: Genie space ID (internal database ID)
        
    Returns:
        Updated Genie space
        
    Raises:
        404: Space not found
    """
    try:
        # TODO: Get actual user from authentication
        user = "system"
        
        space = service.set_default_genie_space(space_id=space_id, user=user)
        return space
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error setting default Genie space {space_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to set default Genie space",
        )

