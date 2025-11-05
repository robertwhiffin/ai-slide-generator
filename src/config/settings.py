"""
Application settings management using Pydantic.

This module combines YAML configuration with environment variables to create
a unified settings object.
"""

from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.config.loader import ConfigurationError, load_config, load_prompts, merge_with_env


# Pydantic models for configuration sections
class LLMStageSettings(BaseSettings):
    """Settings for a specific LLM stage."""

    temperature: float = 0.7
    max_tokens: int = 4096


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
        if v < 1 or v > 32000:
            raise ValueError("max_tokens must be between 1 and 32000")
        return v


class GenieSettings(BaseSettings):
    """Genie configuration settings."""

    space_id: str
    space_description: str

class APISettings(BaseSettings):
    """API configuration settings."""

    host: str = "0.0.0.0"
    port: int = 8000
    cors_enabled: bool = True
    cors_origins: list[str] = Field(default_factory=list)
    request_timeout: int = 180
    max_concurrent_requests: int = 10

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        return v


class OutputSettings(BaseSettings):
    """Output configuration settings."""

    default_max_slides: int = 10
    min_slides: int = 3
    max_slides: int = 20
    html_template: str = "professional"
    include_metadata: bool = True
    include_source_citations: bool = True

    @field_validator("html_template")
    @classmethod
    def validate_template(cls, v: str) -> str:
        valid_templates = ["professional", "minimal", "colorful"]
        if v not in valid_templates:
            raise ValueError(f"Template must be one of: {', '.join(valid_templates)}")
        return v

    @field_validator("min_slides", "max_slides", "default_max_slides")
    @classmethod
    def validate_slide_count(cls, v: int) -> int:
        if v < 1 or v > 50:
            raise ValueError("Slide count must be between 1 and 50")
        return v


class LoggingSettings(BaseSettings):
    """Logging configuration settings."""

    level: str = "INFO"
    format: str = "json"
    include_request_id: bool = True
    log_file: str = "logs/app.log"
    max_file_size_mb: int = 10
    backup_count: int = 5

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"Log level must be one of: {', '.join(valid_levels)}")
        return v_upper

    @field_validator("format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        valid_formats = ["json", "text"]
        if v not in valid_formats:
            raise ValueError(f"Log format must be one of: {', '.join(valid_formats)}")
        return v


class FeatureFlags(BaseSettings):
    """Feature flags for optional functionality."""

    enable_caching: bool = False
    enable_streaming: bool = False
    enable_batch_processing: bool = False


class AppSettings(BaseSettings):
    """
    Main application settings.

    Combines environment variables (for secrets) with YAML configuration
    (for application settings).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow",
    )

    # Secrets from environment variables
    databricks_host: str = Field(..., description="Databricks workspace URL")
    databricks_token: str = Field(..., description="Databricks access token")

    # Application configuration (from YAML)
    llm: LLMSettings
    genie: GenieSettings
    api: APISettings
    output: OutputSettings
    logging: LoggingSettings
    features: FeatureFlags = Field(default_factory=FeatureFlags)

    # Prompts (loaded separately)
    prompts: dict[str, Any] = Field(default_factory=dict)

    # Optional environment identifier
    environment: str = "development"

    @field_validator("databricks_host")
    @classmethod
    def validate_databricks_host(cls, v: str) -> str:
        if not v.startswith(("https://", "http://")):
            raise ValueError("databricks_host must start with https:// or http://")
        return v.rstrip("/")


def create_settings() -> AppSettings:
    """
    Create application settings by combining YAML config and environment variables.

    Returns:
        AppSettings instance with all configuration loaded

    Raises:
        ConfigurationError: If configuration cannot be loaded or is invalid
    """
    try:
        # Load YAML configuration
        config = load_config()
        prompts = load_prompts()

        # Merge with environment overrides
        config = merge_with_env(config)

        # Create nested Pydantic models
        llm_settings = LLMSettings(**config["llm"])
        genie_settings = GenieSettings(**config["genie"])
        api_settings = APISettings(**config["api"])
        output_settings = OutputSettings(**config["output"])
        logging_settings = LoggingSettings(**config["logging"])
        feature_flags = FeatureFlags(**config.get("features", {}))

        # Create main settings object
        # Environment variables will be loaded automatically by Pydantic
        settings = AppSettings(
            llm=llm_settings,
            genie=genie_settings,
            api=api_settings,
            output=output_settings,
            logging=logging_settings,
            features=feature_flags,
            prompts=prompts,
            environment=config.get("environment", "development"),
        )

        return settings

    except Exception as e:
        raise ConfigurationError(f"Failed to create settings: {e}") from e


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """
    Get the application settings singleton.

    This function is cached, so subsequent calls return the same instance.
    Use reload_settings() to force a reload during development.

    Returns:
        Cached AppSettings instance
    """
    return create_settings()


def reload_settings() -> AppSettings:
    """
    Reload settings by clearing the cache and recreating.

    Useful during development when config files change.

    Returns:
        New AppSettings instance
    """
    get_settings.cache_clear()
    return get_settings()

