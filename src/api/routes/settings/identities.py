"""API endpoints for Databricks workspace identities (users and groups)."""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.services.databricks_identity_service import (
    DatabricksIdentityError,
    DatabricksIdentityService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/identities", tags=["identities"])


# Response models
class IdentityResponse(BaseModel):
    """Single identity (user or group)."""

    id: str = Field(..., description="Databricks identity ID")
    display_name: str = Field(..., description="Display name (email for users, name for groups)")
    type: str = Field(..., description="Identity type: USER or GROUP")


class IdentityListResponse(BaseModel):
    """List of identities."""

    identities: list[IdentityResponse]
    total: int


def get_identity_service() -> DatabricksIdentityService:
    """Get Databricks identity service instance."""
    return DatabricksIdentityService()


@router.get("/users", response_model=IdentityListResponse)
def list_users(
    query: Optional[str] = Query(None, description="Search query for filtering users"),
    max_results: int = Query(100, ge=1, le=500, description="Maximum results to return"),
):
    """
    List Databricks workspace users.
    
    Args:
        query: Optional search string to filter by email or display name
        max_results: Maximum number of users to return
        
    Returns:
        List of users with their IDs and display names
    """
    try:
        service = get_identity_service()
        
        filter_query = None
        if query:
            filter_query = f'userName co "{query}" or displayName co "{query}"'
        
        users = service.list_users(filter_query=filter_query, max_results=max_results)
        
        return IdentityListResponse(
            identities=[
                IdentityResponse(
                    id=u["id"],
                    display_name=u.get("displayName") or u.get("userName", "Unknown"),
                    type="USER",
                )
                for u in users
            ],
            total=len(users),
        )
    except DatabricksIdentityError as e:
        logger.error(f"Failed to list users: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Unexpected error listing users: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list users",
        )


@router.get("/groups", response_model=IdentityListResponse)
def list_groups(
    query: Optional[str] = Query(None, description="Search query for filtering groups"),
    max_results: int = Query(100, ge=1, le=500, description="Maximum results to return"),
):
    """
    List Databricks workspace groups.
    
    Args:
        query: Optional search string to filter by group name
        max_results: Maximum number of groups to return
        
    Returns:
        List of groups with their IDs and display names
    """
    try:
        service = get_identity_service()
        
        filter_query = None
        if query:
            filter_query = f'displayName co "{query}"'
        
        groups = service.list_groups(filter_query=filter_query, max_results=max_results)
        
        return IdentityListResponse(
            identities=[
                IdentityResponse(
                    id=g["id"],
                    display_name=g.get("displayName", "Unknown"),
                    type="GROUP",
                )
                for g in groups
            ],
            total=len(groups),
        )
    except DatabricksIdentityError as e:
        logger.error(f"Failed to list groups: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Unexpected error listing groups: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list groups",
        )


@router.get("/search", response_model=IdentityListResponse)
def search_identities(
    query: str = Query(..., min_length=1, description="Search query"),
    include_users: bool = Query(True, description="Include users in results"),
    include_groups: bool = Query(True, description="Include groups in results"),
    max_results: int = Query(50, ge=1, le=200, description="Maximum results to return"),
):
    """
    Search for users and groups matching a query.
    
    Args:
        query: Search string to match against names/emails
        include_users: Whether to include users in results
        include_groups: Whether to include groups in results
        max_results: Maximum total results to return
        
    Returns:
        Combined list of matching users and groups
    """
    try:
        service = get_identity_service()
        
        results = service.search_identities(
            query=query,
            include_users=include_users,
            include_groups=include_groups,
            max_results=max_results,
        )
        
        return IdentityListResponse(
            identities=[
                IdentityResponse(
                    id=r["id"],
                    display_name=r.get("displayName") or r.get("userName", "Unknown"),
                    type=r["type"],
                )
                for r in results
            ],
            total=len(results),
        )
    except DatabricksIdentityError as e:
        logger.error(f"Failed to search identities: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Unexpected error searching identities: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to search identities",
        )

