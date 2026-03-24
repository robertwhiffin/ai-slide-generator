"""API endpoints for managing deck contributors (sharing decks)."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.permission_context import get_permission_context
from src.database.models.deck_contributor import DeckContributor
from src.database.models.profile_contributor import PermissionLevel
from src.database.models.session import UserSession
from src.services.permission_service import PermissionService, get_permission_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/sessions/{session_id}/contributors",
    tags=["deck-contributors"],
)

# Valid permission levels for deck contributors (CAN_USE is profile-only)
VALID_DECK_PERMISSIONS = {
    PermissionLevel.CAN_VIEW.value,
    PermissionLevel.CAN_EDIT.value,
    PermissionLevel.CAN_MANAGE.value,
}


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class DeckContributorCreate(BaseModel):
    identity_id: str = Field(..., description="Databricks user/group ID")
    identity_type: str = Field(..., description="USER or GROUP")
    identity_name: str = Field(..., description="Display name (email or group name)")
    permission_level: str = Field(
        default=PermissionLevel.CAN_VIEW.value,
        description="Permission level: CAN_VIEW, CAN_EDIT, or CAN_MANAGE",
    )


class DeckContributorUpdate(BaseModel):
    permission_level: str = Field(
        ..., description="Permission level: CAN_VIEW, CAN_EDIT, or CAN_MANAGE"
    )


class DeckContributorResponse(BaseModel):
    id: int
    identity_id: str
    identity_type: str
    identity_name: str
    permission_level: str
    created_at: str
    created_by: Optional[str] = None

    class Config:
        from_attributes = True


class DeckContributorListResponse(BaseModel):
    contributors: list[DeckContributorResponse]
    total: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_root_session_or_400(db: Session, session_id: str) -> UserSession:
    """Look up the UserSession by its string session_id.

    Raises 404 if not found, 400 if it is a contributor (child) session.
    """
    session = db.query(UserSession).filter(UserSession.session_id == session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )
    if session.parent_session_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot manage contributors on a contributor session",
        )
    return session


def _require_manage(perm_service: PermissionService, db: Session, session: UserSession):
    """Check that the current user has CAN_MANAGE on this deck."""
    ctx = get_permission_context()
    if not ctx or not ctx.is_authenticated:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to manage this deck",
        )
    if not perm_service.can_manage_deck(
        db,
        session.id,
        user_id=ctx.user_id,
        user_name=ctx.user_name,
        group_ids=ctx.group_ids,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to manage this deck",
        )


def _validate_deck_permission(level: str) -> str:
    """Validate that the permission level is allowed for deck contributors."""
    if level not in VALID_DECK_PERMISSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid permission level for deck contributor. Must be one of: {sorted(VALID_DECK_PERMISSIONS)}",
        )
    return level


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=DeckContributorListResponse)
def list_deck_contributors(
    session_id: str,
    db: Session = Depends(get_db),
    perm_service: PermissionService = Depends(get_permission_service),
):
    """List contributors for a deck. Requires CAN_MANAGE."""
    session = _get_root_session_or_400(db, session_id)
    _require_manage(perm_service, db, session)

    contributors = (
        db.query(DeckContributor)
        .filter(DeckContributor.user_session_id == session.id)
        .order_by(DeckContributor.identity_name)
        .all()
    )

    items = [
        DeckContributorResponse(
            id=c.id,
            identity_id=c.identity_id,
            identity_type=c.identity_type,
            identity_name=c.identity_name,
            permission_level=c.permission_level,
            created_at=c.created_at.isoformat(),
            created_by=c.created_by,
        )
        for c in contributors
    ]
    return DeckContributorListResponse(contributors=items, total=len(items))


@router.post("", response_model=DeckContributorResponse, status_code=status.HTTP_201_CREATED)
def add_deck_contributor(
    session_id: str,
    request: DeckContributorCreate,
    db: Session = Depends(get_db),
    perm_service: PermissionService = Depends(get_permission_service),
):
    """Add a contributor to a deck. Requires CAN_MANAGE."""
    session = _get_root_session_or_400(db, session_id)
    _require_manage(perm_service, db, session)

    # Validate permission level (CAN_USE not allowed for decks)
    _validate_deck_permission(request.permission_level)

    # Prevent adding the session creator as a contributor
    if request.identity_name == session.created_by:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot add the session creator as a contributor",
        )

    # Check for duplicates
    existing = (
        db.query(DeckContributor)
        .filter(
            DeckContributor.user_session_id == session.id,
            DeckContributor.identity_id == request.identity_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Contributor {request.identity_name} already has access to this deck",
        )

    ctx = get_permission_context()
    created_by = ctx.user_name if ctx else "system"

    contributor = DeckContributor(
        user_session_id=session.id,
        identity_type=request.identity_type,
        identity_id=request.identity_id,
        identity_name=request.identity_name,
        permission_level=request.permission_level,
        created_by=created_by,
    )
    db.add(contributor)
    db.commit()
    db.refresh(contributor)

    logger.info(
        f"Added deck contributor {request.identity_name} to session {session_id} "
        f"with permission {request.permission_level}"
    )

    return DeckContributorResponse(
        id=contributor.id,
        identity_id=contributor.identity_id,
        identity_type=contributor.identity_type,
        identity_name=contributor.identity_name,
        permission_level=contributor.permission_level,
        created_at=contributor.created_at.isoformat(),
        created_by=contributor.created_by,
    )


@router.put("/{contributor_id}", response_model=DeckContributorResponse)
def update_deck_contributor(
    session_id: str,
    contributor_id: int,
    request: DeckContributorUpdate,
    db: Session = Depends(get_db),
    perm_service: PermissionService = Depends(get_permission_service),
):
    """Update a deck contributor's permission level. Requires CAN_MANAGE."""
    session = _get_root_session_or_400(db, session_id)
    _require_manage(perm_service, db, session)

    _validate_deck_permission(request.permission_level)

    contributor = (
        db.query(DeckContributor)
        .filter(
            DeckContributor.id == contributor_id,
            DeckContributor.user_session_id == session.id,
        )
        .first()
    )
    if not contributor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contributor {contributor_id} not found",
        )

    contributor.permission_level = request.permission_level
    db.commit()
    db.refresh(contributor)

    logger.info(f"Updated deck contributor {contributor.identity_name} to {request.permission_level}")

    return DeckContributorResponse(
        id=contributor.id,
        identity_id=contributor.identity_id,
        identity_type=contributor.identity_type,
        identity_name=contributor.identity_name,
        permission_level=contributor.permission_level,
        created_at=contributor.created_at.isoformat(),
        created_by=contributor.created_by,
    )


@router.delete("/{contributor_id}")
def delete_deck_contributor(
    session_id: str,
    contributor_id: int,
    db: Session = Depends(get_db),
    perm_service: PermissionService = Depends(get_permission_service),
):
    """Remove a deck contributor. Requires CAN_MANAGE."""
    session = _get_root_session_or_400(db, session_id)
    _require_manage(perm_service, db, session)

    contributor = (
        db.query(DeckContributor)
        .filter(
            DeckContributor.id == contributor_id,
            DeckContributor.user_session_id == session.id,
        )
        .first()
    )
    if not contributor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contributor {contributor_id} not found",
        )

    # Defense-in-depth: reject if contributor identity_name matches session created_by
    if contributor.identity_name == session.created_by:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove the session creator as a contributor",
        )

    identity_name = contributor.identity_name
    db.delete(contributor)
    db.commit()

    logger.info(f"Removed deck contributor {identity_name} from session {session_id}")

    return {"detail": "Contributor removed"}
