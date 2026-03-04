"""
Database-backed application settings.

This module provides settings loaded from the database configuration system.
Configuration profiles are stored in PostgreSQL/Lakebase and managed via the
settings API endpoints.
"""

import logging
import os
from typing import Any, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.core.database import get_db_session
from src.database.models import (
    ConfigAIInfra,
    ConfigGenieSpace,
    ConfigProfile,
    ConfigPrompts,
)

logger = logging.getLogger(__name__)

# Global variable to track the currently active profile
_active_profile_id: Optional[int] = None


# Reuse existing Pydantic schemas for backward compatibility
class LLMSettings(BaseSettings):
    """LLM configuration settings."""

    model_config = SettingsConfigDict(extra="allow")

    endpoint: str
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 0.95
    timeout: int = 600

    @field_validator("temperature")
    @classmethod
    def validate_temperature(cls, v: float) -> float:
        if not 0.0 <= v <= 2.0:
            raise ValueError("Temperature must be between 0.0 and 2.0")
        return v

    @field_validator("max_tokens")
    @classmethod
    def validate_max_tokens(cls, v: int) -> int:
        if v < 1 or v > 64000:
            raise ValueError("max_tokens must be between 1 and 64000")
        return v


class GenieSettings(BaseSettings):
    """Genie configuration settings."""

    model_config = SettingsConfigDict(extra="allow", populate_by_name=True)

    space_id: str = Field(alias="default_space_id")
    description: str = Field(default="")


class APISettings(BaseSettings):
    """API configuration settings (from environment/defaults)."""

    host: str = "0.0.0.0"
    port: int = 8000
    cors_enabled: bool = True
    cors_origins: list[str] = Field(default_factory=lambda: [
        "http://localhost:3000",
        "http://localhost:5173",
    ])
    request_timeout: int = 180
    max_concurrent_requests: int = 10


class OutputSettings(BaseSettings):
    """Output configuration settings (from environment/defaults)."""

    html_template: str = "professional"
    include_metadata: bool = True
    include_source_citations: bool = True


class LoggingSettings(BaseSettings):
    """Logging configuration settings (from environment/defaults)."""

    level: str = "INFO"
    format: str = "json"
    include_request_id: bool = True
    log_file: str = "logs/app.log"
    max_file_size_mb: int = 10
    backup_count: int = 5


class FeatureFlags(BaseSettings):
    """Feature flags for optional functionality."""

    enable_caching: bool = False
    enable_streaming: bool = False
    enable_batch_processing: bool = False


class AppSettings(BaseSettings):
    """
    Main application settings loaded from database.

    This replaces the YAML-based configuration with database-backed profiles.
    Secrets still come from environment variables.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow",
    )

    # Database connection
    database_url: str = Field(default="")

    # Profile info
    profile_id: int
    profile_name: str

    # Secrets from environment variables
    databricks_host: str = Field(default="", description="Databricks workspace URL")
    databricks_token: str = Field(default="", description="Databricks access token")

    # Configuration from database
    llm: LLMSettings
    genie: Optional[GenieSettings] = None  # Optional - enables data queries when configured

    # Prompts (from database)
    prompts: dict[str, Any] = Field(default_factory=dict)

    # Static configuration (from defaults/environment)
    api: APISettings = Field(default_factory=APISettings)
    output: OutputSettings = Field(default_factory=OutputSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    features: FeatureFlags = Field(default_factory=FeatureFlags)

    # Environment identifier
    environment: str = "development"

    @field_validator("databricks_host")
    @classmethod
    def validate_databricks_host(cls, v: str) -> str:
        if not v:
            return ""
        # Automatically add https:// if missing
        if not v.startswith(("https://", "http://")):
            v = f"https://{v}"
        return v.rstrip("/")


def get_active_profile_id() -> Optional[int]:
    """Return the currently active profile ID."""
    return _active_profile_id


def _resolve_profile(db, profile_id: Optional[int] = None) -> "ConfigProfile":
    """Resolve a profile by ID, falling back to active then default.

    Args:
        db: SQLAlchemy session
        profile_id: Specific profile ID, or None for active/default

    Returns:
        ConfigProfile instance

    Raises:
        ValueError: If no matching profile is found
    """
    if profile_id is None and _active_profile_id is not None:
        profile = db.query(ConfigProfile).filter_by(id=_active_profile_id).first()
        if not profile:
            logger.warning(
                f"Active profile {_active_profile_id} not found, falling back to default"
            )
            profile = db.query(ConfigProfile).filter_by(is_default=True).first()
    elif profile_id is None:
        profile = db.query(ConfigProfile).filter_by(is_default=True).first()
        if not profile:
            raise ValueError("No default profile found in database")
    else:
        profile = db.query(ConfigProfile).filter_by(id=profile_id).first()
        if not profile:
            raise ValueError(f"Profile {profile_id} not found")
    return profile


def fetch_prompt_content(profile_id: Optional[int] = None) -> dict[str, str]:
    """Fetch the latest prompt content from the database for a profile.

    This is a lightweight query (3 SELECTs) designed to be called per-request
    so that prompt edits take effect immediately without agent reload.

    Args:
        profile_id: Profile ID to fetch for, or None for active/default

    Returns:
        Dict with keys: deck_prompt, slide_style, image_guidelines,
        system_prompt, slide_editing_instructions
    """
    try:
        with get_db_session() as db:
            profile = _resolve_profile(db, profile_id)

            prompts = db.query(ConfigPrompts).filter_by(profile_id=profile.id).first()
            if not prompts:
                raise ValueError(f"Prompts settings not found for profile {profile.id}")

            deck_prompt_content = None
            if prompts.selected_deck_prompt_id:
                from src.database.models import SlideDeckPromptLibrary

                deck_prompt = db.query(SlideDeckPromptLibrary).filter_by(
                    id=prompts.selected_deck_prompt_id,
                    is_active=True,
                ).first()
                if deck_prompt:
                    deck_prompt_content = deck_prompt.prompt_content

            slide_style_content = None
            image_guidelines = None
            if prompts.selected_slide_style_id:
                from src.database.models import SlideStyleLibrary

                slide_style = db.query(SlideStyleLibrary).filter_by(
                    id=prompts.selected_slide_style_id,
                    is_active=True,
                ).first()
                if slide_style:
                    slide_style_content = slide_style.style_content
                    image_guidelines = slide_style.image_guidelines

            return {
                "deck_prompt": deck_prompt_content or "",
                "slide_style": slide_style_content or "",
                "image_guidelines": image_guidelines or "",
                "system_prompt": prompts.system_prompt,
                "slide_editing_instructions": prompts.slide_editing_instructions,
            }

    except Exception as e:
        logger.error(f"Failed to fetch prompt content: {e}", exc_info=True)
        raise


def load_settings_from_database(profile_id: Optional[int] = None) -> AppSettings:
    """
    Load settings from database profile.

    Args:
        profile_id: Specific profile ID to load, or None for default (or active profile)

    Returns:
        AppSettings instance with database-backed configuration

    Raises:
        ValueError: If profile not found or required settings missing
    """
    try:
        with get_db_session() as db:
            profile = _resolve_profile(db, profile_id)

            logger.info(
                "Loading configuration from database",
                extra={"profile_id": profile.id, "profile_name": profile.name},
            )

            ai_infra = db.query(ConfigAIInfra).filter_by(profile_id=profile.id).first()
            if not ai_infra:
                raise ValueError(f"AI infra settings not found for profile {profile.id}")

            genie_space = db.query(ConfigGenieSpace).filter_by(
                profile_id=profile.id
            ).first()

            prompt_content = fetch_prompt_content(profile.id)

            llm_settings = LLMSettings(
                endpoint=ai_infra.llm_endpoint,
                temperature=float(ai_infra.llm_temperature),
                max_tokens=ai_infra.llm_max_tokens,
                top_p=0.95,  # Default value
                timeout=600,  # Default value
            )

            # Create Genie settings only if configured
            genie_settings = None
            if genie_space:
                genie_settings = GenieSettings(
                    default_space_id=genie_space.space_id,
                    description=genie_space.description or "",
                )

            settings = AppSettings(
                database_url=os.getenv("DATABASE_URL", ""),
                profile_id=profile.id,
                profile_name=profile.name,
                llm=llm_settings,
                genie=genie_settings,
                prompts=prompt_content,
                environment=os.getenv("ENVIRONMENT", "development"),
            )

            logger.info(
                "Configuration loaded successfully",
                extra={
                    "profile_id": profile.id,
                    "profile_name": profile.name,
                    "llm_endpoint": ai_infra.llm_endpoint,
                    "genie_space": genie_space.space_name if genie_space else None,
                    "prompt_only_mode": genie_space is None,
                },
            )

            return settings

    except Exception as e:
        logger.error(f"Failed to load settings from database: {e}", exc_info=True)
        raise


def get_settings() -> AppSettings:
    """
    Load application settings from the database.

    Each call queries the database for the active (or default) profile.
    There is no caching — callers that need to hold onto settings should
    store the returned object themselves.

    Returns:
        AppSettings instance from database

    Raises:
        ValueError: If configuration cannot be loaded
    """
    return load_settings_from_database()


def reload_settings(profile_id: Optional[int] = None) -> AppSettings:
    """
    Switch the active profile and reload settings from database.

    Updates the global active profile ID so that subsequent calls to
    ``get_settings()`` and ``fetch_prompt_content()`` target the new profile.

    Args:
        profile_id: Profile ID to activate, or None for default

    Returns:
        New AppSettings instance for the activated profile
    """
    logger.info("Reloading settings from database", extra={"profile_id": profile_id})

    if profile_id is not None:
        global _active_profile_id
        _active_profile_id = profile_id
        logger.info(f"Set active profile ID to {profile_id}")

    settings = get_settings()

    logger.info(
        "Settings reloaded successfully",
        extra={
            "profile_id": settings.profile_id,
            "profile_name": settings.profile_name,
            "llm_endpoint": settings.llm.endpoint,
            "genie_space_id": settings.genie.space_id if settings.genie else None,
            "prompt_only_mode": settings.genie is None,
        },
    )

    return settings

