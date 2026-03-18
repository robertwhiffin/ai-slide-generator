"""One-time migration: convert relational profile data to agent_config JSON.

Called during database startup migration. Populates agent_config on
config_profiles and backfills user_sessions from their profile_id.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from src.core.defaults import DEFAULT_CONFIG

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = DEFAULT_CONFIG.get("prompts", {}).get("system_prompt")
_DEFAULT_EDITING_INSTRUCTIONS = DEFAULT_CONFIG.get("prompts", {}).get(
    "slide_editing_instructions"
)


def _differs_from_default(value: Optional[str], default: Optional[str]) -> bool:
    """Return True if value is set and differs from the default."""
    if value is None:
        return False
    if default is None:
        return True
    return value.strip() != default.strip()


def build_agent_config_from_profile(profile_data: dict[str, Any]) -> dict[str, Any]:
    """Build an agent_config dict from relational profile data."""
    prompts = profile_data.get("prompts", {})
    genie_spaces = profile_data.get("genie_spaces", [])

    tools = []
    for gs in genie_spaces:
        tools.append({
            "type": "genie",
            "space_id": gs["space_id"],
            "space_name": gs["space_name"],
            "description": gs.get("description"),
        })

    system_prompt = prompts.get("system_prompt")
    editing_instructions = prompts.get("slide_editing_instructions")

    return {
        "tools": tools,
        "slide_style_id": prompts.get("selected_slide_style_id"),
        "deck_prompt_id": prompts.get("selected_deck_prompt_id"),
        "system_prompt": system_prompt
        if _differs_from_default(system_prompt, _DEFAULT_SYSTEM_PROMPT)
        else None,
        "slide_editing_instructions": editing_instructions
        if _differs_from_default(editing_instructions, _DEFAULT_EDITING_INSTRUCTIONS)
        else None,
    }


def migrate_profiles(session_factory) -> int:
    """Migrate all profiles to agent_config JSON. Returns count migrated."""
    from src.database.models.profile import ConfigProfile

    db = session_factory()
    try:
        profiles = db.query(ConfigProfile).filter(
            ConfigProfile.agent_config.is_(None)
        ).all()

        count = 0
        for profile in profiles:
            profile_data = {
                "prompts": {
                    "selected_slide_style_id": getattr(profile.prompts, "selected_slide_style_id", None) if profile.prompts else None,
                    "selected_deck_prompt_id": getattr(profile.prompts, "selected_deck_prompt_id", None) if profile.prompts else None,
                    "system_prompt": getattr(profile.prompts, "system_prompt", None) if profile.prompts else None,
                    "slide_editing_instructions": getattr(profile.prompts, "slide_editing_instructions", None) if profile.prompts else None,
                },
                "genie_spaces": [
                    {
                        "space_id": gs.space_id,
                        "space_name": gs.space_name,
                        "description": gs.description,
                    }
                    for gs in (profile.genie_spaces or [])
                ],
            }
            profile.agent_config = build_agent_config_from_profile(profile_data)
            count += 1
            logger.info(f"Migrated profile '{profile.name}' (id={profile.id}) to agent_config")

        db.commit()
        return count
    finally:
        db.close()


def backfill_sessions(session_factory) -> int:
    """Backfill agent_config on existing sessions from their profile_id."""
    from src.database.models.profile import ConfigProfile
    from src.database.models.session import UserSession

    db = session_factory()
    try:
        sessions = (
            db.query(UserSession)
            .filter(
                UserSession.agent_config.is_(None),
                UserSession.profile_id.isnot(None),
            )
            .all()
        )

        count = 0
        for session in sessions:
            profile = db.query(ConfigProfile).filter(
                ConfigProfile.id == session.profile_id
            ).first()
            if profile and profile.agent_config:
                session.agent_config = profile.agent_config
                count += 1

        db.commit()
        logger.info(f"Backfilled agent_config on {count} sessions")
        return count
    finally:
        db.close()
