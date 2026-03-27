"""REST endpoints for reading and updating a session's agent configuration."""

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError

from src.api.schemas.agent_config import AgentConfig, ToolEntry, resolve_agent_config
from src.api.services.session_manager import SessionNotFoundError, get_session_manager
from src.core.database import get_db_session
from src.database.models import UserSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions/{session_id}/agent-config", tags=["agent-config"])


# ── helpers ──────────────────────────────────────────────────────────────


def _validate_references(config: AgentConfig) -> None:
    """Validate that slide_style_id and deck_prompt_id reference existing library entries."""
    from src.database.models import SlideStyleLibrary, SlideDeckPromptLibrary

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
    try:
        mgr = get_session_manager()
        session = await asyncio.to_thread(mgr.get_session, session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    raw = session.get("agent_config")
    config = resolve_agent_config(raw)
    result = config.model_dump()
    result["is_configured"] = raw is not None
    return result


@router.put("")
async def put_agent_config(session_id: str, config: AgentConfig):
    """Replace the full agent config for a session."""
    # Pydantic already validated duplicates via model_validator.
    # Now validate foreign-key references.
    _validate_references(config)

    try:
        result = await asyncio.to_thread(_save_agent_config, session_id, config)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    return result


@router.patch("/tools")
async def patch_tools(session_id: str, body: PatchToolRequest):
    """Add or remove a single tool from the session's agent config."""
    try:
        mgr = get_session_manager()
        session = await asyncio.to_thread(mgr.get_session, session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    config = resolve_agent_config(session.get("agent_config"))

    if body.action == "add":
        config.tools.append(body.tool)
    elif body.action == "remove":
        # Match by discriminator key (genie:space_id or mcp:server_uri)
        from src.api.schemas.agent_config import GenieTool, MCPTool

        def _key(t):
            if isinstance(t, GenieTool):
                return f"genie:{t.space_id}"
            elif isinstance(t, MCPTool):
                return f"mcp:{t.server_uri}"
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
