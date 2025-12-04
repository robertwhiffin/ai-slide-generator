"""
Genie space configuration API endpoints.

Each profile has exactly one Genie space.
"""
import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.api.schemas.settings import GenieSpace, GenieSpaceCreate, GenieSpaceUpdate
from src.core.databricks_client import get_databricks_client
from src.core.database import get_db
from src.services import GenieService
from src.services.config_validator import ConfigurationValidator

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
        page_num = 1

        # Initial request with explicit page_size
        logger.info("Fetching Genie spaces from Databricks (page_size=100)")
        response = client.genie.list_spaces(page_size=100)

        # Collect spaces from first page
        first_page_count = len(response.spaces) if response.spaces else 0
        logger.info(f"Page {page_num}: received {first_page_count} spaces, has_next_page={bool(response.next_page_token)}")
        
        if response.spaces:
            for space in response.spaces:
                spaces_data[space.space_id] = {
                    "title": space.title,
                    "description": space.description or "",
                }

        # Handle pagination
        while response.next_page_token:
            page_num += 1
            logger.info(f"Fetching page {page_num} with token: {response.next_page_token[:20]}...")
            response = client.genie.list_spaces(page_token=response.next_page_token, page_size=100)
            page_count = len(response.spaces) if response.spaces else 0
            logger.info(f"Page {page_num}: received {page_count} spaces, has_next_page={bool(response.next_page_token)}")
            
            if response.spaces:
                for space in response.spaces:
                    spaces_data[space.space_id] = {
                        "title": space.title,
                        "description": space.description or "",
                    }

        # Sort titles alphabetically
        sorted_titles = sorted([details["title"] for details in spaces_data.values()])

        logger.info(f"Found {len(spaces_data)} total Genie spaces across {page_num} page(s)")
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


@router.get("/{profile_id}", response_model=GenieSpace)
def get_genie_space(
    profile_id: int,
    service: GenieService = Depends(get_genie_service),
):
    """
    Get the Genie space for a profile.
    
    Each profile has exactly one Genie space.
    
    Args:
        profile_id: Profile ID
        
    Returns:
        Genie space for the profile
        
    Raises:
        404: No Genie space found for profile
    """
    try:
        space = service.get_genie_space(profile_id)
        if not space:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No Genie space found for profile {profile_id}",
            )
        return space
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting Genie space for profile {profile_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get Genie space",
        )


@router.post("/{profile_id}", response_model=GenieSpace, status_code=status.HTTP_201_CREATED)
def add_genie_space(
    profile_id: int,
    request: GenieSpaceCreate,
    service: GenieService = Depends(get_genie_service),
):
    """
    Add a Genie space to a profile.
    
    Each profile can have exactly one Genie space. If a space already exists,
    this will fail with a 400 error.
    
    Args:
        profile_id: Profile ID
        request: Genie space creation request
        
    Returns:
        Created Genie space
        
    Raises:
        400: Validation failed or profile already has a Genie space
    """
    try:
        # Validate
        validator = ConfigurationValidator(profile_id=None)
        result = validator.validate_genie_space(request.space_id)
        if not result.success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.message,
            )

        # TODO: Get actual user from authentication
        user = "system"

        space = service.add_genie_space(
            profile_id=profile_id,
            space_id=request.space_id,
            space_name=request.space_name,
            description=request.description,
            user=user,
        )
        return space
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e).lower()
        if "unique constraint" in error_msg or "already exists" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Profile {profile_id} already has a Genie space",
            )
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
    """
    try:
        # TODO: Get actual user from authentication
        user = "system"

        service.delete_genie_space(space_id=space_id, user=user)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error deleting Genie space {space_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete Genie space",
        )
