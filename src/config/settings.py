"""
Application settings management using Pydantic.

This module combines YAML configuration with environment variables to create
a unified settings object.
"""

from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.config.loader import (
    ConfigurationError,
    load_config,
    load_mlflow_config,
    load_prompts,
    merge_with_env,
)


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

    model_config = SettingsConfigDict(extra="allow", populate_by_name=True)

    space_id: str = Field(alias="default_space_id")
    timeout: int = 60
    max_retries: int = 3
    retry_delay: int = 2
    poll_interval: int = 2

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


class MLFlowTracingSettings(BaseSettings):
    """MLFlow tracing configuration."""

    enabled: bool = True
    backend: str = "databricks"
    sample_rate: float = 1.0
    capture_input_output: bool = True
    capture_model_config: bool = True
    max_trace_depth: int = 10

    @field_validator("sample_rate")
    @classmethod
    def validate_sample_rate(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("sample_rate must be between 0.0 and 1.0")
        return v


class MLFlowServingEnvironment(BaseSettings):
    """MLFlow serving configuration for an environment."""

    endpoint_name: str
    workload_size: str = "Small"
    scale_to_zero_enabled: bool = True
    min_scale: int = 0
    max_scale: int = 3

    @field_validator("workload_size")
    @classmethod
    def validate_workload_size(cls, v: str) -> str:
        valid_sizes = ["Small", "Medium", "Large"]
        if v not in valid_sizes:
            raise ValueError(f"workload_size must be one of: {', '.join(valid_sizes)}")
        return v


class MLFlowSettings(BaseSettings):
    """MLFlow configuration for experiment tracking and model serving."""

    model_config = SettingsConfigDict(extra="allow")

    # Tracking
    tracking_uri: str = "databricks"
    experiment_name: str

    # Tracing
    tracing: MLFlowTracingSettings

    # Registry
    registry_uri: str = "databricks-uc"
    model_name: str
    dev_model_name: str

    # Serving environments
    serving_dev: MLFlowServingEnvironment
    serving_prod: MLFlowServingEnvironment

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
    databricks_host: str = Field(default="", description="Databricks workspace URL")
    databricks_token: str = Field(default="", description="Databricks access token")
    databricks_profile: str = Field(default="", description="Databricks CLI profile name")

    # Application configuration (from YAML)
    llm: LLMSettings
    genie: GenieSettings
    api: APISettings
    output: OutputSettings
    logging: LoggingSettings
    features: FeatureFlags = Field(default_factory=FeatureFlags)
    mlflow: MLFlowSettings

    # Prompts (loaded separately)
    prompts: dict[str, Any] = Field(default_factory=dict)

    # Optional environment identifier
    environment: str = "development"

    @field_validator("databricks_host")
    @classmethod
    def validate_databricks_host(cls, v: str) -> str:
        if v and not v.startswith(("https://", "http://")):
            raise ValueError("databricks_host must start with https:// or http://")
        return v.rstrip("/") if v else ""


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
        mlflow_config = load_mlflow_config()

        # Merge with environment overrides
        config = merge_with_env(config)

        # Get current user from environment for MLFlow experiment name
        import os
        from databricks.sdk import WorkspaceClient
        
        try:
            w = WorkspaceClient()
            username = w.current_user.me().user_name
        except Exception:
            # Fallback to environment variable or default
            username = os.getenv("USER", "default_user")

        # Format experiment name with username
        mlflow_config["tracking"]["experiment_name"] = mlflow_config["tracking"][
            "experiment_name"
        ].format(username=username)

        # Create nested Pydantic models
        llm_settings = LLMSettings(**config["llm"])
        genie_settings = GenieSettings(**config["genie"])
        api_settings = APISettings(**config["api"])
        output_settings = OutputSettings(**config["output"])
        logging_settings = LoggingSettings(**config["logging"])
        feature_flags = FeatureFlags(**config.get("features", {}))

        # Create MLFlow settings
        mlflow_tracing = MLFlowTracingSettings(**mlflow_config["tracing"])
        mlflow_serving_dev = MLFlowServingEnvironment(**mlflow_config["serving"]["dev"])
        mlflow_serving_prod = MLFlowServingEnvironment(**mlflow_config["serving"]["prod"])

        mlflow_settings = MLFlowSettings(
            tracking_uri=mlflow_config["tracking"]["uri"],
            experiment_name=mlflow_config["tracking"]["experiment_name"],
            tracing=mlflow_tracing,
            registry_uri=mlflow_config["registry"]["uri"],
            model_name=mlflow_config["registry"]["model_name"],
            dev_model_name=mlflow_config["registry"]["dev_model_name"],
            serving_dev=mlflow_serving_dev,
            serving_prod=mlflow_serving_prod,
            log_models=mlflow_config["logging"]["log_models"],
            log_input_examples=mlflow_config["logging"]["log_input_examples"],
            log_model_signatures=mlflow_config["logging"]["log_model_signatures"],
            log_system_metrics=mlflow_config["logging"]["log_system_metrics"],
            log_artifacts=mlflow_config["logging"]["log_artifacts"],
            track_latency=mlflow_config["metrics"]["track_latency"],
            track_token_usage=mlflow_config["metrics"]["track_token_usage"],
            track_cost=mlflow_config["metrics"]["track_cost"],
            cost_per_million_input_tokens=mlflow_config["metrics"][
                "cost_per_million_tokens"
            ]["input"],
            cost_per_million_output_tokens=mlflow_config["metrics"][
                "cost_per_million_tokens"
            ]["output"],
        )

        # Create main settings object
        # Environment variables will be loaded automatically by Pydantic
        settings = AppSettings(
            llm=llm_settings,
            genie=genie_settings,
            api=api_settings,
            output=output_settings,
            logging=logging_settings,
            features=feature_flags,
            mlflow=mlflow_settings,
            prompts=prompts,
            environment=config.get("environment", "development"),
            databricks_profile=config.get("databricks", {}).get("profile", ""),
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

