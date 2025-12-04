"""
Database-backed application settings.

This module provides settings loaded from the database configuration system.
Configuration profiles are stored in PostgreSQL/Lakebase and managed via the
settings API endpoints.
"""

import logging
import os
from functools import lru_cache
from typing import Any, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.core.database import get_db_session
from src.database.models import (
    ConfigAIInfra,
    ConfigGenieSpace,
    ConfigMLflow,
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
    timeout: int = 120

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


class MLFlowTracingSettings(BaseSettings):
    """MLFlow tracing configuration."""

    enabled: bool = True
    backend: str = "databricks"
    sample_rate: float = 1.0
    capture_input_output: bool = True
    capture_model_config: bool = True
    max_trace_depth: int = 10


class MLFlowServingEnvironment(BaseSettings):
    """MLFlow serving configuration for an environment."""

    endpoint_name: str
    workload_size: str = "Small"
    scale_to_zero_enabled: bool = True
    min_scale: int = 0
    max_scale: int = 3


class MLFlowSettings(BaseSettings):
    """MLFlow configuration."""

    model_config = SettingsConfigDict(extra="allow")

    # Tracking
    tracking_uri: str = "databricks-uc"
    experiment_name: str

    # Tracing
    tracing: MLFlowTracingSettings = Field(default_factory=MLFlowTracingSettings)

    # Registry
    registry_uri: str = "databricks-uc"
    model_name: str = "slide_generator"
    dev_model_name: str = "slide_generator_dev"

    # Serving environments
    serving_dev: MLFlowServingEnvironment = Field(default_factory=lambda: MLFlowServingEnvironment(
        endpoint_name="slide-generator-dev"
    ))
    serving_prod: MLFlowServingEnvironment = Field(default_factory=lambda: MLFlowServingEnvironment(
        endpoint_name="slide-generator-prod"
    ))

    # Logging options
    log_models: bool = True
    log_input_examples: bool = True
    log_model_signatures: bool = True
    log_system_metrics: bool = True
    log_artifacts: bool = True

    # Metrics tracking
    track_latency: bool = True
    track_token_usage: bool = True
    track_cost: bool = True

    # Cost estimation (USD per 1M tokens)
    cost_per_million_input_tokens: float = 1.0
    cost_per_million_output_tokens: float = 3.0


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
    genie: GenieSettings
    mlflow: MLFlowSettings

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
    global _active_profile_id

    try:
        with get_db_session() as db:
            # Get profile (priority: specified > active > default)
            if profile_id is None and _active_profile_id is not None:
                # Use the currently active profile
                profile = db.query(ConfigProfile).filter_by(id=_active_profile_id).first()
                if not profile:
                    # Fallback to default if active profile not found
                    logger.warning(
                        f"Active profile {_active_profile_id} not found, falling back to default"
                    )
                    profile = db.query(ConfigProfile).filter_by(is_default=True).first()
            elif profile_id is None:
                # No profile specified and no active profile - use default
                profile = db.query(ConfigProfile).filter_by(is_default=True).first()
                if not profile:
                    raise ValueError("No default profile found in database")
            else:
                # Specific profile requested
                profile = db.query(ConfigProfile).filter_by(id=profile_id).first()
                if not profile:
                    raise ValueError(f"Profile {profile_id} not found")

            logger.info(
                "Loading configuration from database",
                extra={"profile_id": profile.id, "profile_name": profile.name},
            )

            # Load all configs
            ai_infra = db.query(ConfigAIInfra).filter_by(profile_id=profile.id).first()
            if not ai_infra:
                raise ValueError(f"AI infra settings not found for profile {profile.id}")

            # Get the Genie space for this profile (one per profile)
            genie_space = db.query(ConfigGenieSpace).filter_by(
                profile_id=profile.id
            ).first()
            if not genie_space:
                raise ValueError(f"No Genie space found for profile {profile.id}")

            mlflow_config = db.query(ConfigMLflow).filter_by(profile_id=profile.id).first()
            if not mlflow_config:
                raise ValueError(f"MLflow settings not found for profile {profile.id}")

            prompts = db.query(ConfigPrompts).filter_by(profile_id=profile.id).first()
            if not prompts:
                raise ValueError(f"Prompts settings not found for profile {profile.id}")

            # Get username for MLflow experiment name formatting
            try:
                from src.core.databricks_client import get_databricks_client
                client = get_databricks_client()
                username = client.current_user.me().user_name
            except Exception:
                # Fallback to environment variable if Databricks not available
                username = os.getenv("USER", "default_user")

            # Format experiment name
            experiment_name = mlflow_config.experiment_name
            if "{username}" in experiment_name:
                experiment_name = experiment_name.format(username=username)

            # Create settings
            llm_settings = LLMSettings(
                endpoint=ai_infra.llm_endpoint,
                temperature=float(ai_infra.llm_temperature),
                max_tokens=ai_infra.llm_max_tokens,
                top_p=0.95,  # Default value
                timeout=120,  # Default value
            )

            genie_settings = GenieSettings(
                default_space_id=genie_space.space_id,
                description=genie_space.description or "",
            )

            mlflow_settings = MLFlowSettings(
                experiment_name=experiment_name,
            )

            settings = AppSettings(
                database_url=os.getenv("DATABASE_URL", ""),
                profile_id=profile.id,
                profile_name=profile.name,
                llm=llm_settings,
                genie=genie_settings,
                mlflow=mlflow_settings,
                prompts={
                    "system_prompt": prompts.system_prompt,
                    "slide_editing_instructions": prompts.slide_editing_instructions,
                    "user_prompt_template": prompts.user_prompt_template,
                },
                environment=os.getenv("ENVIRONMENT", "development"),
            )

            logger.info(
                "Configuration loaded successfully",
                extra={
                    "profile_id": profile.id,
                    "profile_name": profile.name,
                    "llm_endpoint": ai_infra.llm_endpoint,
                    "genie_space": genie_space.space_name,
                },
            )

            return settings

    except Exception as e:
        logger.error(f"Failed to load settings from database: {e}", exc_info=True)
        raise


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """
    Get the application settings singleton (database-backed).

    This function is cached, so subsequent calls return the same instance.
    Use reload_settings() to force a reload.

    Returns:
        Cached AppSettings instance from database

    Raises:
        ValueError: If configuration cannot be loaded
    """
    return load_settings_from_database()


def reload_settings(profile_id: Optional[int] = None) -> AppSettings:
    """
    Reload settings from database.

    Clears the cache and loads fresh settings from the specified profile
    or the default profile.

    Args:
        profile_id: Profile ID to load, or None for default

    Returns:
        New AppSettings instance
    """
    logger.info("Reloading settings from database", extra={"profile_id": profile_id})

    # Log cache state before clearing
    cache_info_before = get_settings.cache_info()
    logger.info(f"Cache info BEFORE clear: {cache_info_before}")

    # Store the active profile ID globally BEFORE clearing cache
    # This ensures get_settings() knows which profile to load
    if profile_id is not None:
        global _active_profile_id
        _active_profile_id = profile_id
        logger.info(f"Set active profile ID to {profile_id}")

    # Clear the cache
    get_settings.cache_clear()
    cache_info_after_clear = get_settings.cache_info()
    logger.info(f"Cache info AFTER clear: {cache_info_after_clear}")

    # Force immediate cache repopulation by calling get_settings()
    # This ensures the cache contains the correct profile
    settings = get_settings()
    cache_info_after_reload = get_settings.cache_info()
    logger.info(f"Cache info AFTER reload: {cache_info_after_reload}")

    logger.info(
        "Settings reloaded successfully",
        extra={
            "profile_id": settings.profile_id,
            "profile_name": settings.profile_name,
            "llm_endpoint": settings.llm.endpoint,
            "genie_space_id": settings.genie.space_id,
        },
    )

    return settings

