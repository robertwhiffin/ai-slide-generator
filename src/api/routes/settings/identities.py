"""API endpoints for Databricks identities (users and groups).

Uses the multi-source identity provider which automatically selects:
1. Account API (if DATABRICKS_ACCOUNT_ADMIN_TOKEN configured)
2. Workspace API (if DATABRICKS_WORKSPACE_ADMIN_TOKEN configured)
3. Local identity table (default fallback)
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.services.identity_provider import (
    IdentityProviderMode,
    get_identity_provider,
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
    source: str = Field(..., description="Identity source: account, workspace, or local")


class IdentityProviderInfoResponse(BaseModel):
    """Information about the current identity provider."""

    mode: str = Field(..., description="Current mode: account, workspace, or local")
    description: str = Field(..., description="Human-readable description of the mode")


@router.get("/provider", response_model=IdentityProviderInfoResponse)
def get_provider_info():
    """
    Get information about the current identity provider.
    
    Returns:
        Current provider mode and description
    """
    provider = get_identity_provider()
    
    descriptions = {
        IdentityProviderMode.ACCOUNT: "Using Databricks Account SCIM API (all account users/groups)",
        IdentityProviderMode.WORKSPACE: "Using Databricks Workspace SCIM API (workspace users/groups)",
        IdentityProviderMode.LOCAL: "Using local identity table (only users who have signed in)",
    }
    
    return IdentityProviderInfoResponse(
        mode=provider.mode.value,
        description=descriptions.get(provider.mode, "Unknown provider mode"),
    )


@router.get("/users", response_model=IdentityListResponse)
def list_users(
    query: Optional[str] = Query(None, description="Search query for filtering users"),
    max_results: int = Query(100, ge=1, le=500, description="Maximum results to return"),
):
    """
    List users from the configured identity source.
    
    Args:
        query: Optional search string to filter by email or display name
        max_results: Maximum number of users to return
        
    Returns:
        List of users with their IDs and display names
    """
    try:
        provider = get_identity_provider()
        
        users = provider.list_users(filter_query=query, max_results=max_results)
        
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
            source=provider.mode.value,
        )
    except Exception as e:
        logger.error(f"Failed to list users: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list users: {e}",
        )


@router.get("/groups", response_model=IdentityListResponse)
def list_groups(
    query: Optional[str] = Query(None, description="Search query for filtering groups"),
    max_results: int = Query(100, ge=1, le=500, description="Maximum results to return"),
):
    """
    List groups from the configured identity source.
    
    Args:
        query: Optional search string to filter by group name
        max_results: Maximum number of groups to return
        
    Returns:
        List of groups with their IDs and display names
    """
    try:
        provider = get_identity_provider()
        
        groups = provider.list_groups(filter_query=query, max_results=max_results)
        
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
            source=provider.mode.value,
        )
    except Exception as e:
        logger.error(f"Failed to list groups: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list groups: {e}",
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
        provider = get_identity_provider()
        
        results = provider.search_identities(
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
            source=provider.mode.value,
        )
    except Exception as e:
        logger.error(f"Failed to search identities: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to search identities: {e}",
        )
