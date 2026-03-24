"""API endpoints for managing profile contributors (sharing)."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.database.models import (
    ConfigProfile,
    ConfigProfileContributor,
    IdentityType,
    PermissionLevel,
)
from src.services.permission_service import PermissionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/profiles/{profile_id}/contributors", tags=["contributors"])


def get_permission_service() -> PermissionService:
    """Dependency to get PermissionService."""
    return PermissionService()


# Request/Response models
class ContributorCreate(BaseModel):
    """Request to add a contributor to a profile."""

    identity_id: str = Field(..., description="Databricks user/group ID")
    identity_type: str = Field(..., description="USER or GROUP")
    identity_name: str = Field(..., description="Display name (email or group name)")
    permission_level: str = Field(
        default=PermissionLevel.CAN_VIEW.value,
        description="Permission level: CAN_MANAGE, CAN_EDIT, or CAN_VIEW",
    )


class ContributorUpdate(BaseModel):
    """Request to update a contributor's permission level."""

    permission_level: str = Field(
        ..., description="Permission level: CAN_MANAGE, CAN_EDIT, or CAN_VIEW"
    )


class ContributorResponse(BaseModel):
    """Contributor details."""

    id: int
    identity_id: str
    identity_type: str
    identity_name: str
    display_name: Optional[str] = None
    user_name: Optional[str] = None
    permission_level: str
    created_at: str
    created_by: Optional[str] = None

    class Config:
        from_attributes = True


class ContributorListResponse(BaseModel):
    """List of contributors."""

    contributors: list[ContributorResponse]
    total: int


class ContributorBulkCreate(BaseModel):
    """Request to add multiple contributors at once."""

    contributors: list[ContributorCreate]


def _validate_permission_level(level: str) -> str:
    """Validate and normalize permission level."""
    try:
        return PermissionLevel(level).value
    except ValueError:
        valid = [p.value for p in PermissionLevel]
        raise ValueError(f"Invalid permission level. Must be one of: {valid}")


def _validate_identity_type(type_str: str) -> str:
    """Validate and normalize identity type."""
    try:
        return IdentityType(type_str).value
    except ValueError:
        valid = [t.value for t in IdentityType]
        raise ValueError(f"Invalid identity type. Must be one of: {valid}")


def _resolve_user_identities(contributors: list) -> dict[str, dict]:
    """Batch-resolve emails for USER contributors."""
    result: dict[str, dict] = {}
    user_ids = [c.identity_id for c in contributors if c.identity_type == "USER"]
    if not user_ids:
        return result

    try:
        from src.services.identity_provider import get_identity_provider
        provider = get_identity_provider()
    except Exception:
        return result

    for uid in user_ids:
        try:
            info = provider.get_user_by_id(uid)
            if info:
                email = info.get("userName", "")
                display = info.get("displayName") or email
                result[uid] = {"display_name": display, "user_name": email}
        except Exception:
            pass

    return result


def _get_profile_or_404(db: Session, profile_id: int) -> ConfigProfile:
    """Get profile or raise 404."""
    profile = db.query(ConfigProfile).filter(ConfigProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile {profile_id} not found",
        )
    if profile.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile {profile_id} has been deleted",
        )
    return profile


@router.get("", response_model=ContributorListResponse)
def list_contributors(
    profile_id: int,
    db: Session = Depends(get_db),
    perm_service: PermissionService = Depends(get_permission_service),
):
    """
    List all contributors for a profile.
    
    Requires CAN_VIEW permission on the profile.
    
    Args:
        profile_id: Profile ID
        
    Returns:
        List of contributors with their permissions
    """
    # Check permission first
    perm_service.require_use_profile(db, profile_id)
    
    _get_profile_or_404(db, profile_id)
    
    contributors = (
        db.query(ConfigProfileContributor)
        .filter(ConfigProfileContributor.profile_id == profile_id)
        .order_by(ConfigProfileContributor.identity_name)
        .all()
    )

    resolved = _resolve_user_identities(contributors)

    items = []
    for c in contributors:
        info = resolved.get(c.identity_id, {})
        items.append(ContributorResponse(
            id=c.id,
            identity_id=c.identity_id,
            identity_type=c.identity_type,
            identity_name=c.identity_name,
            display_name=info.get("display_name") or c.identity_name,
            user_name=info.get("user_name"),
            permission_level=c.permission_level,
            created_at=c.created_at.isoformat(),
            created_by=c.created_by,
        ))

    return ContributorListResponse(contributors=items, total=len(items))


@router.post("", response_model=ContributorResponse, status_code=status.HTTP_201_CREATED)
def add_contributor(
    profile_id: int,
    request: ContributorCreate,
    db: Session = Depends(get_db),
    perm_service: PermissionService = Depends(get_permission_service),
):
    """
    Add a contributor to a profile.
    
    Requires CAN_EDIT permission on the profile.
    
    Args:
        profile_id: Profile ID
        request: Contributor details
        
    Returns:
        Created contributor
        
    Raises:
        403: No permission to edit this profile
        400: Invalid request
        404: Profile not found
        409: Contributor already exists
    """
    # Check permission first
    perm_service.require_edit_profile(db, profile_id)
    
    _get_profile_or_404(db, profile_id)
    
    try:
        permission_level = _validate_permission_level(request.permission_level)
        identity_type = _validate_identity_type(request.identity_type)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    
    # Check if contributor already exists
    existing = (
        db.query(ConfigProfileContributor)
        .filter(
            ConfigProfileContributor.profile_id == profile_id,
            ConfigProfileContributor.identity_id == request.identity_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Contributor {request.identity_name} already has access to this profile",
        )
    
    # Get current user for audit
    from src.core.permission_context import get_permission_context
    ctx = get_permission_context()
    created_by = ctx.user_name if ctx else "system"
    
    # Create contributor
    contributor = ConfigProfileContributor(
        profile_id=profile_id,
        identity_id=request.identity_id,
        identity_type=identity_type,
        identity_name=request.identity_name,
        permission_level=permission_level,
        created_by=created_by,
    )
    db.add(contributor)
    db.commit()
    db.refresh(contributor)
    
    logger.info(
        f"Added contributor {request.identity_name} to profile {profile_id} "
        f"with permission {permission_level}"
    )
    
    return ContributorResponse(
        id=contributor.id,
        identity_id=contributor.identity_id,
        identity_type=contributor.identity_type,
        identity_name=contributor.identity_name,
        permission_level=contributor.permission_level,
        created_at=contributor.created_at.isoformat(),
        created_by=contributor.created_by,
    )


@router.post("/bulk", response_model=ContributorListResponse, status_code=status.HTTP_201_CREATED)
def add_contributors_bulk(
    profile_id: int,
    request: ContributorBulkCreate,
    db: Session = Depends(get_db),
    perm_service: PermissionService = Depends(get_permission_service),
):
    """
    Add multiple contributors to a profile at once.
    
    Requires CAN_EDIT permission on the profile.
    
    Args:
        profile_id: Profile ID
        request: List of contributors to add
        
    Returns:
        List of created contributors (skips duplicates)
    """
    # Check permission first
    perm_service.require_edit_profile(db, profile_id)
    
    _get_profile_or_404(db, profile_id)
    
    # Get current user for audit
    from src.core.permission_context import get_permission_context
    ctx = get_permission_context()
    created_by = ctx.user_name if ctx else "system"
    
    created = []
    for contrib in request.contributors:
        try:
            permission_level = _validate_permission_level(contrib.permission_level)
            identity_type = _validate_identity_type(contrib.identity_type)
        except ValueError:
            continue  # Skip invalid entries
        
        # Check if already exists
        existing = (
            db.query(ConfigProfileContributor)
            .filter(
                ConfigProfileContributor.profile_id == profile_id,
                ConfigProfileContributor.identity_id == contrib.identity_id,
            )
            .first()
        )
        if existing:
            continue  # Skip duplicates
        
        contributor = ConfigProfileContributor(
            profile_id=profile_id,
            identity_id=contrib.identity_id,
            identity_type=identity_type,
            identity_name=contrib.identity_name,
            permission_level=permission_level,
            created_by=created_by,
        )
        db.add(contributor)
        created.append(contributor)
    
    db.commit()
    
    # Refresh all created contributors
    for c in created:
        db.refresh(c)
    
    logger.info(f"Added {len(created)} contributors to profile {profile_id}")
    
    return ContributorListResponse(
        contributors=[
            ContributorResponse(
                id=c.id,
                identity_id=c.identity_id,
                identity_type=c.identity_type,
                identity_name=c.identity_name,
                permission_level=c.permission_level,
                created_at=c.created_at.isoformat(),
                created_by=c.created_by,
            )
            for c in created
        ],
        total=len(created),
    )


@router.put("/{contributor_id}", response_model=ContributorResponse)
def update_contributor(
    profile_id: int,
    contributor_id: int,
    request: ContributorUpdate,
    db: Session = Depends(get_db),
    perm_service: PermissionService = Depends(get_permission_service),
):
    """
    Update a contributor's permission level.
    
    Requires CAN_EDIT permission on the profile.
    
    Args:
        profile_id: Profile ID
        contributor_id: Contributor ID
        request: New permission level
        
    Returns:
        Updated contributor
    """
    # Check permission first
    perm_service.require_edit_profile(db, profile_id)
    
    _get_profile_or_404(db, profile_id)
    
    contributor = (
        db.query(ConfigProfileContributor)
        .filter(
            ConfigProfileContributor.id == contributor_id,
            ConfigProfileContributor.profile_id == profile_id,
        )
        .first()
    )
    if not contributor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contributor {contributor_id} not found",
        )
    
    try:
        permission_level = _validate_permission_level(request.permission_level)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    
    contributor.permission_level = permission_level
    db.commit()
    db.refresh(contributor)
    
    logger.info(
        f"Updated contributor {contributor.identity_name} permission to {permission_level}"
    )
    
    return ContributorResponse(
        id=contributor.id,
        identity_id=contributor.identity_id,
        identity_type=contributor.identity_type,
        identity_name=contributor.identity_name,
        permission_level=contributor.permission_level,
        created_at=contributor.created_at.isoformat(),
        created_by=contributor.created_by,
    )


@router.delete("/{contributor_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_contributor(
    profile_id: int,
    contributor_id: int,
    db: Session = Depends(get_db),
    perm_service: PermissionService = Depends(get_permission_service),
):
    """
    Remove a contributor from a profile.
    
    Requires CAN_EDIT permission on the profile.
    
    Args:
        profile_id: Profile ID
        contributor_id: Contributor ID
    """
    # Check permission first
    perm_service.require_edit_profile(db, profile_id)
    
    _get_profile_or_404(db, profile_id)
    
    contributor = (
        db.query(ConfigProfileContributor)
        .filter(
            ConfigProfileContributor.id == contributor_id,
            ConfigProfileContributor.profile_id == profile_id,
        )
        .first()
    )
    if not contributor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contributor {contributor_id} not found",
        )
    
    identity_name = contributor.identity_name
    db.delete(contributor)
    db.commit()
    
    logger.info(f"Removed contributor {identity_name} from profile {profile_id}")

