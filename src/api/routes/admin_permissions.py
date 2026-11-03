"""Admin endpoints for listing, adding and removing app admins (admin-gated)."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.routes._authz import require_admin, reset_admin_cache
from src.core.database import get_db
from src.core.user_context import get_current_user
from src.services.admin_permissions import (
    NotManualPermissionError,
    add_manual_admin,
    get_sync_status,
    list_admins,
    remove_manual_admin,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/admins",
    tags=["admin-permissions"],
    dependencies=[Depends(require_admin)],
)

_NOT_MANUAL_DETAIL = (
    "This admin comes from CAN_MANAGE on the app. "
    "Change it in the app's Permissions in Databricks."
)


class AdminEntryResponse(BaseModel):
    identity_type: str
    identity_name: str
    identity_id: str | None
    sources: list[str]
    manual_permission_id: int | None
    added_by: str | None
    added_at: str | None


class SyncStatusResponse(BaseModel):
    last_attempt_at: str | None
    last_success_at: str | None
    last_error: str | None


class AdminListResponse(BaseModel):
    admins: list[AdminEntryResponse]
    sync: SyncStatusResponse


class AddAdminRequest(BaseModel):
    identity_type: str
    identity_name: str = Field(max_length=255)
    identity_id: str | None = Field(default=None, max_length=255)


class AddAdminResponse(BaseModel):
    permission_id: int


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


@router.get("", response_model=AdminListResponse)
def list_app_admins(db: Session = Depends(get_db)) -> AdminListResponse:
    entries = list_admins(db)
    sync = get_sync_status(db)
    return AdminListResponse(
        admins=[
            AdminEntryResponse(
                identity_type=e.identity_type,
                identity_name=e.identity_name,
                identity_id=e.identity_id,
                sources=list(e.sources),
                manual_permission_id=e.manual_permission_id,
                added_by=e.added_by,
                added_at=_iso(e.added_at),
            )
            for e in entries
        ],
        sync=SyncStatusResponse(
            last_attempt_at=_iso(sync.last_attempt_at),
            last_success_at=_iso(sync.last_success_at),
            last_error=sync.last_error,
        ),
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=AddAdminResponse)
def add_app_admin(
    body: AddAdminRequest, db: Session = Depends(get_db)
) -> AddAdminResponse:
    try:
        permission = add_manual_admin(
            db,
            identity_type=body.identity_type,
            identity_name=body.identity_name,
            identity_id=body.identity_id,
            created_by=get_current_user(),
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    permission_id = permission.id
    created_by = get_current_user()
    db.commit()
    reset_admin_cache()
    logger.info(
        "App admin added: %s %s by %s", body.identity_type, body.identity_name, created_by
    )
    return AddAdminResponse(permission_id=permission_id)


@router.delete("/{permission_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_app_admin(permission_id: int, db: Session = Depends(get_db)) -> Response:
    try:
        remove_manual_admin(db, permission_id)
    except NotManualPermissionError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_NOT_MANUAL_DETAIL)
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    db.commit()
    reset_admin_cache()
    logger.info(
        "App admin removed: permission %s by %s", permission_id, get_current_user()
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
