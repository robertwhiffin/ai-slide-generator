"""Simplified profile routes — profiles are named snapshots of agent_config."""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.api.schemas.agent_config import AgentConfig, GenieTool, resolve_agent_config
from src.api.services.session_manager import SessionNotFoundError, get_session_manager
from src.core.database import get_db_session
from src.core.permission_context import get_permission_context
from src.core.user_context import get_current_user
from src.database.models.profile import ConfigProfile
from src.database.models.session import UserSession
from src.services.permission_service import get_permission_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/profiles", tags=["profiles"])
load_router = APIRouter(prefix="/api/sessions", tags=["profiles"])


# ── request/response schemas ─────────────────────────────────────────────


class SaveProfileRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    agent_config: Optional[dict] = None  # Client-side config takes precedence over session


class UpdateProfileRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    is_default: Optional[bool] = None


# ── helpers ───────────────────────────────────────────────────────────────


def _profile_to_dict(profile: ConfigProfile) -> dict:
    """Serialize a profile to a dict, eagerly reading all fields."""
    return {
        "id": profile.id,
        "name": profile.name,
        "description": profile.description,
        "is_default": profile.is_default,
        "agent_config": profile.agent_config,
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "created_by": profile.created_by,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


def _get_profile(db, profile_id: int) -> ConfigProfile:
    """Load a profile by ID, raising 404 if not found or deleted."""
    profile = (
        db.query(ConfigProfile)
        .filter(ConfigProfile.id == profile_id, ConfigProfile.is_deleted == False)  # noqa: E712
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail=f"Profile not found: {profile_id}")
    # Eagerly access agent_config to avoid DetachedInstanceError after session close
    _ = profile.agent_config
    return profile


# ── routes ────────────────────────────────────────────────────────────────


@router.get("")
async def list_profiles():
    """List non-deleted profiles accessible to the current user."""
    perm_ctx = get_permission_context()
    perm_service = get_permission_service()

    with get_db_session() as db:
        accessible_ids = set(perm_service.get_accessible_profile_ids(
            db,
            user_id=perm_ctx.user_id if perm_ctx else None,
            user_name=perm_ctx.user_name if perm_ctx else None,
            group_ids=perm_ctx.group_ids if perm_ctx else None,
        ))

        profiles = (
            db.query(ConfigProfile)
            .filter(
                ConfigProfile.is_deleted == False,  # noqa: E712
                ConfigProfile.id.in_(accessible_ids) if accessible_ids else False,
            )
            .order_by(ConfigProfile.name)
            .all()
        )
        return [_profile_to_dict(p) for p in profiles]


@router.post("/save-from-session/{session_id}", status_code=201)
async def save_from_session(session_id: str, body: SaveProfileRequest):
    """Snapshot a session's agent_config into a new named profile."""
    # Get agent_config from session
    try:
        mgr = get_session_manager()
        session = mgr.get_session(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    # Permission check: caller must be session creator OR have deck access
    perm_ctx = get_permission_context()
    created_by = session.get("created_by")
    is_creator = perm_ctx and perm_ctx.user_name and perm_ctx.user_name == created_by
    if not is_creator:
        # Check deck-level access
        root_id = session.get("parent_session_internal_id") or session.get("id")
        perm_service = get_permission_service()
        with get_db_session() as db:
            deck_perm = perm_service.get_deck_permission(
                db, root_id,
                user_id=perm_ctx.user_id if perm_ctx else None,
                user_name=perm_ctx.user_name if perm_ctx else None,
                group_ids=perm_ctx.group_ids if perm_ctx else None,
            )
        if deck_perm is None:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to save a profile from this session",
            )

    # Prefer client-side config (has resolved defaults) over session's stored config
    raw_config = body.agent_config if body.agent_config else session.get("agent_config")
    config = resolve_agent_config(raw_config)

    # Strip session-specific conversation_ids before persisting
    for tool in config.tools:
        if isinstance(tool, GenieTool):
            tool.conversation_id = None

    config_dict = config.model_dump()

    with get_db_session() as db:
        current_user = get_current_user()
        profile = ConfigProfile(
            name=body.name,
            description=body.description,
            agent_config=config_dict,
            created_by=current_user,
        )
        db.add(profile)
        db.flush()  # get the id
        result = _profile_to_dict(profile)

    return result


@load_router.post("/{session_id}/load-profile/{profile_id}")
async def load_profile_into_session(session_id: str, profile_id: int):
    """Copy a profile's agent_config into a session. Requires CAN_USE on the profile."""
    perm_service = get_permission_service()
    with get_db_session() as db:
        perm_service.require_use_profile(db, profile_id)
        profile = _get_profile(db, profile_id)
        agent_config = profile.agent_config

        # Write to session
        session = (
            db.query(UserSession)
            .filter(UserSession.session_id == session_id)
            .first()
        )
        if not session:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

        config = resolve_agent_config(agent_config)
        session.agent_config = config.model_dump()

    return {"status": "loaded", "agent_config": config.model_dump()}


@router.put("/{profile_id}")
async def update_profile(profile_id: int, body: UpdateProfileRequest):
    """Update profile name, description, or is_default. Requires CAN_EDIT."""
    perm_service = get_permission_service()
    with get_db_session() as db:
        perm_service.require_edit_profile(db, profile_id)
        profile = _get_profile(db, profile_id)

        if body.name is not None:
            profile.name = body.name
        if body.description is not None:
            profile.description = body.description
        if body.is_default is True:
            # Clear default flag on all other profiles
            from sqlalchemy import update

            db.execute(
                update(ConfigProfile)
                .where(ConfigProfile.id != profile_id)
                .values(is_default=False)
            )
            profile.is_default = True
        elif body.is_default is False:
            profile.is_default = False

        result = _profile_to_dict(profile)

    return result


@router.delete("/{profile_id}")
async def delete_profile(profile_id: int):
    """Soft-delete a profile. Requires CAN_MANAGE."""
    perm_service = get_permission_service()
    with get_db_session() as db:
        perm_service.require_manage_profile(db, profile_id)
        profile = _get_profile(db, profile_id)
        profile.is_deleted = True
        profile.deleted_at = datetime.utcnow()

    return {"status": "deleted", "id": profile_id}
