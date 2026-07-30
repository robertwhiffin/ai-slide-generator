"""REST endpoints for reading and updating a session's agent configuration."""

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError

from src.api.routes._authz import _check_deck_permission_for_session
from src.api.schemas.agent_config import AgentConfig, ToolEntry, resolve_agent_config
from src.api.services.session_manager import SessionNotFoundError, get_session_manager
from src.core.database import get_db_session
from src.database.models import UserSession
from src.database.models.profile_contributor import PermissionLevel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions/{session_id}/agent-config", tags=["agent-config"])


# ── helpers ──────────────────────────────────────────────────────────────


def _sanitize_stale_pins(config: AgentConfig, *, session_id: str | None = None) -> bool:
    """Clear ``design_system_id`` / ``template_id`` when they no longer resolve.

    Both pins can be invalidated by SOMEONE ELSE while a user's config
    legitimately holds them: template ids are re-minted by the sanctioned
    delete+re-upload workflow, and a design system can be DELETED by its creator
    (or an admin) while other users' sessions still point at it. So neither is a
    client error, and rejecting either wedges every later config update.

    The design-system pin used to be STRICT, and the consequence was severe:
    because the frontend PUTs the WHOLE config, a user whose pinned design system
    had been deleted could no longer change their slide style, deck prompt,
    template, tools or model — every save returned 422 — and the dropdown
    rendered blank with no explanation. Generation already degraded to the no-DS
    prompt, so the strictness bought nothing and cost the session.

    A ``design_system_id`` that does not resolve to an ACTIVE row is therefore
    cleared in place with a warning naming the stale id and *session_id*; that
    also invalidates any ``template_id`` hanging off it, which the template branch
    then clears for the same reason. Run on BOTH write and read, so what is
    persisted and what the client is shown agree.

    Returns True when anything was cleared (callers may persist the repair).
    """
    from src.database.models import DesignSystem, DesignSystemTemplate

    cleared = False
    with get_db_session() as db:
        if config.design_system_id is not None:
            design_system = (
                db.query(DesignSystem)
                .filter(
                    DesignSystem.id == config.design_system_id,
                    DesignSystem.is_active == True,  # noqa: E712
                )
                .first()
            )
            if not design_system:
                logger.warning(
                    "Clearing stale design_system_id %s (session_id=%s): the "
                    "design system no longer exists or is inactive (deleted by "
                    "its creator or an admin); serving the config without it",
                    config.design_system_id,
                    session_id,
                )
                config.design_system_id = None
                cleared = True
        if config.template_id is not None:
            template = None
            if config.design_system_id is not None:
                template = (
                    db.query(DesignSystemTemplate)
                    .filter(
                        DesignSystemTemplate.id == config.template_id,
                        DesignSystemTemplate.design_system_id == config.design_system_id,
                    )
                    .first()
                )
            if template is None:
                logger.warning(
                    "Clearing stale template pin %s (design_system_id=%s, "
                    "session_id=%s): the template does not exist or does not "
                    "belong to the selected design system; serving the config "
                    "without it",
                    config.template_id,
                    config.design_system_id,
                    session_id,
                )
                config.template_id = None
                cleared = True
    return cleared


def _validate_references(config: AgentConfig, *, session_id: str | None = None) -> None:
    """Sanitize the stale pins, then STRICTLY validate the remaining references.

    ``slide_style_id`` and ``deck_prompt_id`` stay strict (422 on a
    missing/inactive entry — the existing convention): those libraries are
    admin-managed and are not deleted out from under a session, so a bad id there
    is a CLIENT error and must not be silently swallowed.

    The self-healing half lives in :func:`_sanitize_stale_pins`, which the READ
    path calls on its own (a bogus slide style must not make a session
    unloadable — only unsaveable).
    """
    from src.database.models import SlideDeckPromptLibrary, SlideStyleLibrary

    _sanitize_stale_pins(config, session_id=session_id)

    with get_db_session() as db:
        if config.slide_style_id is not None:
            style = (
                db.query(SlideStyleLibrary)
                .filter(
                    SlideStyleLibrary.id == config.slide_style_id,
                    SlideStyleLibrary.is_active == True,  # noqa: E712
                )
                .first()
            )
            if not style:
                raise HTTPException(
                    status_code=422,
                    detail=f"slide_style_id {config.slide_style_id} not found",
                )
        if config.deck_prompt_id is not None:
            prompt = (
                db.query(SlideDeckPromptLibrary)
                .filter(
                    SlideDeckPromptLibrary.id == config.deck_prompt_id,
                    SlideDeckPromptLibrary.is_active == True,  # noqa: E712
                )
                .first()
            )
            if not prompt:
                raise HTTPException(
                    status_code=422,
                    detail=f"deck_prompt_id {config.deck_prompt_id} not found",
                )


def _save_agent_config(session_id: str, config: AgentConfig) -> dict:
    """Persist *config* onto the session row and return its dict representation."""
    with get_db_session() as db:
        session = (
            db.query(UserSession)
            .filter(UserSession.session_id == session_id)
            .first()
        )
        if not session:
            raise SessionNotFoundError(f"Session not found: {session_id}")
        session.agent_config = config.model_dump()
    return config.model_dump()


# ── request schemas ──────────────────────────────────────────────────────


class PatchToolRequest(BaseModel):
    action: Literal["add", "remove"]
    tool: ToolEntry = Field(...)


# ── routes ───────────────────────────────────────────────────────────────


@router.get("")
async def get_agent_config(session_id: str):
    """Return the current agent config for a session (defaults if null)."""
    # SDR-4437 HIGH-1: reading a session's agent config requires CAN_VIEW.
    _check_deck_permission_for_session(session_id, PermissionLevel.CAN_VIEW)
    try:
        mgr = get_session_manager()
        session = await asyncio.to_thread(mgr.get_session, session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    raw = session.get("agent_config")
    config = resolve_agent_config(raw)
    # LOAD self-heals the same pins the PUT does. Without this the dropdown binds
    # to an id that no longer exists and renders BLANK — no selection, no
    # explanation — and the very next save (which PUTs the whole config) would
    # have to clear it anyway. Sanitizing on read means the client is shown
    # "None", which is the truth.
    #
    # Only the PIN sanitizer runs here, never the strict half: a bogus
    # slide_style_id must not make a session UNLOADABLE (it is already
    # unsaveable), and a read is not the place to reject stored state.
    await asyncio.to_thread(_sanitize_stale_pins, config, session_id=session_id)
    result = config.model_dump()
    result["is_configured"] = raw is not None
    return result


@router.put("")
async def put_agent_config(session_id: str, config: AgentConfig):
    """Replace the full agent config for a session."""
    # SDR-4437 HIGH-1: agent-config writes repoint the session's tools — CAN_MANAGE.
    _check_deck_permission_for_session(session_id, PermissionLevel.CAN_MANAGE)
    # Pydantic already validated duplicates via model_validator.
    # Now validate foreign-key references; a stale design-system or template pin
    # is sanitized (cleared in place) rather than rejected, so what is persisted
    # and returned below is the effective config.
    _validate_references(config, session_id=session_id)

    try:
        result = await asyncio.to_thread(_save_agent_config, session_id, config)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    return result


@router.patch("/tools")
async def patch_tools(session_id: str, body: PatchToolRequest):
    """Add or remove a single tool from the session's agent config."""
    # SDR-4437 HIGH-1: agent-config writes repoint the session's tools — CAN_MANAGE.
    _check_deck_permission_for_session(session_id, PermissionLevel.CAN_MANAGE)
    try:
        mgr = get_session_manager()
        session = await asyncio.to_thread(mgr.get_session, session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    config = resolve_agent_config(session.get("agent_config"))

    if body.action == "add":
        config.tools.append(body.tool)
    elif body.action == "remove":
        # Match by discriminator key (e.g. genie:space_id, mcp:connection_name)
        from src.api.schemas.agent_config import (
            GenieTool, MCPTool, VectorIndexTool, ModelEndpointTool, AgentBricksTool,
        )

        def _key(t):
            if isinstance(t, GenieTool):
                return f"genie:{t.space_id}"
            elif isinstance(t, MCPTool):
                return f"mcp:{t.connection_name}"
            elif isinstance(t, VectorIndexTool):
                return f"vector_index:{t.endpoint_name}:{t.index_name}"
            elif isinstance(t, ModelEndpointTool):
                return f"model_endpoint:{t.endpoint_name}"
            elif isinstance(t, AgentBricksTool):
                return f"agent_bricks:{t.endpoint_name}"
            return None

        remove_key = _key(body.tool)
        config.tools = [t for t in config.tools if _key(t) != remove_key]

    # Re-validate (catches duplicates on add)
    try:
        config = AgentConfig.model_validate(config.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        result = await asyncio.to_thread(_save_agent_config, session_id, config)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    return result
