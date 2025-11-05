"""
Unit tests for settings module.
"""

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.config.loader import ConfigurationError
from src.config.settings import (
    APISettings,
    AppSettings,
    FeatureFlags,
    GenieSettings,
    LLMSettings,
    LoggingSettings,
    OutputSettings,
    create_settings,
    get_settings,
    reload_settings,
)


class TestLLMSettings:
    """Tests for LLMSettings model."""

    def test_valid_llm_settings(self):
        """Test creating valid LLM settings."""
        settings = LLMSettings(
            endpoint="test-endpoint",
            temperature=0.7,
            max_tokens=4096,
            top_p=0.95,
            timeout=120,
        )
        assert settings.endpoint == "test-endpoint"
        assert settings.temperature == 0.7

    def test_temperature_validation(self):
        """Test temperature must be in valid range."""
        with pytest.raises(ValidationError, match="Temperature must be between"):
            LLMSettings(endpoint="test", temperature=3.0, max_tokens=100)

        with pytest.raises(ValidationError, match="Temperature must be between"):
            LLMSettings(endpoint="test", temperature=-1.0, max_tokens=100)

    def test_max_tokens_validation(self):
        """Test max_tokens must be in valid range."""
        with pytest.raises(ValidationError, match="max_tokens must be between"):
            LLMSettings(endpoint="test", temperature=0.7, max_tokens=0)

        with pytest.raises(ValidationError, match="max_tokens must be between"):
            LLMSettings(endpoint="test", temperature=0.7, max_tokens=50000)


class TestGenieSettings:
    """Tests for GenieSettings model."""

    def test_valid_genie_settings(self):
        """Test creating valid Genie settings."""
        settings = GenieSettings(
            default_space_id="test-space",
            timeout=60,
            max_retries=3,
        )
        assert settings.default_space_id == "test-space"
        assert settings.timeout == 60

    def test_positive_value_validation(self):
        """Test all numeric fields must be positive."""
        with pytest.raises(ValidationError, match="Value must be positive"):
            GenieSettings(default_space_id="test", timeout=0)

        with pytest.raises(ValidationError, match="Value must be positive"):
            GenieSettings(default_space_id="test", timeout=60, max_retries=-1)


class TestAPISettings:
    """Tests for APISettings model."""

    def test_valid_api_settings(self):
        """Test creating valid API settings."""
        settings = APISettings(
            host="0.0.0.0",
            port=8000,
            cors_enabled=True,
            cors_origins=["http://localhost:3000"],
        )
        assert settings.host == "0.0.0.0"
        assert settings.port == 8000
        assert len(settings.cors_origins) == 1

    def test_port_validation(self):
        """Test port must be in valid range."""
        with pytest.raises(ValidationError, match="Port must be between"):
            APISettings(port=0)

        with pytest.raises(ValidationError, match="Port must be between"):
            APISettings(port=70000)

    def test_default_values(self):
        """Test default values are set correctly."""
        settings = APISettings()
        assert settings.host == "0.0.0.0"
        assert settings.port == 8000
        assert settings.cors_enabled is True


class TestOutputSettings:
    """Tests for OutputSettings model."""

    def test_valid_output_settings(self):
        """Test creating valid output settings."""
        settings = OutputSettings(
            default_max_slides=10,
            min_slides=3,
            max_slides=20,
            html_template="professional",
        )
        assert settings.default_max_slides == 10
        assert settings.html_template == "professional"

    def test_template_validation(self):
        """Test html_template must be valid."""
        with pytest.raises(ValidationError, match="Template must be one of"):
            OutputSettings(html_template="invalid")

        # Valid templates should work
        for template in ["professional", "minimal", "colorful"]:
            settings = OutputSettings(html_template=template)
            assert settings.html_template == template

    def test_slide_count_validation(self):
        """Test slide counts must be in valid range."""
        with pytest.raises(ValidationError, match="Slide count must be between"):
            OutputSettings(min_slides=0)

        with pytest.raises(ValidationError, match="Slide count must be between"):
            OutputSettings(max_slides=100)


class TestLoggingSettings:
    """Tests for LoggingSettings model."""

    def test_valid_logging_settings(self):
        """Test creating valid logging settings."""
        settings = LoggingSettings(
            level="INFO",
            format="json",
            log_file="logs/app.log",
        )
        assert settings.level == "INFO"
        assert settings.format == "json"

    def test_level_validation(self):
        """Test log level must be valid."""
        with pytest.raises(ValidationError, match="Log level must be one of"):
            LoggingSettings(level="INVALID")

        # Valid levels should work (case insensitive)
        for level in ["DEBUG", "info", "Warning"]:
            settings = LoggingSettings(level=level)
            assert settings.level in ["DEBUG", "INFO", "WARNING"]

    def test_format_validation(self):
        """Test log format must be valid."""
        with pytest.raises(ValidationError, match="Log format must be one of"):
            LoggingSettings(format="xml")

        # Valid formats should work
        for fmt in ["json", "text"]:
            settings = LoggingSettings(format=fmt)
            assert settings.format == fmt


class TestFeatureFlags:
    """Tests for FeatureFlags model."""

    def test_default_feature_flags(self):
        """Test all features are disabled by default."""
        flags = FeatureFlags()
        assert flags.enable_caching is False
        assert flags.enable_streaming is False
        assert flags.enable_batch_processing is False

    def test_enable_features(self):
        """Test enabling features."""
        flags = FeatureFlags(
            enable_caching=True,
            enable_streaming=True,
        )
        assert flags.enable_caching is True
        assert flags.enable_streaming is True
        assert flags.enable_batch_processing is False


class TestAppSettings:
    """Tests for AppSettings model."""

    def test_create_settings_success(
        self, mock_config_loader, mock_env_vars, sample_config, sample_prompts
    ):
        """Test successful settings creation."""
        with patch("src.config.settings.load_config", return_value=sample_config):
            with patch("src.config.settings.load_prompts", return_value=sample_prompts):
                settings = create_settings()

                assert settings.databricks_host == "https://test.cloud.databricks.com"
                assert settings.databricks_token == "test-token-12345"
                assert settings.llm.endpoint == sample_config["llm"]["endpoint"]
                assert settings.prompts == sample_prompts

    def test_databricks_host_validation(self, mock_config_loader, mock_env_vars, sample_config, sample_prompts):
        """Test databricks_host must be a valid URL."""
        with patch("src.config.settings.load_config", return_value=sample_config):
            with patch("src.config.settings.load_prompts", return_value=sample_prompts):
                with patch.dict("os.environ", {"DATABRICKS_HOST": "invalid-url"}):
                    with pytest.raises(ConfigurationError, match="must start with https://"):
                        create_settings()

    def test_databricks_host_strips_trailing_slash(self, mock_config_loader, sample_config, sample_prompts):
        """Test trailing slash is removed from databricks_host."""
        with patch("src.config.settings.load_config", return_value=sample_config):
            with patch("src.config.settings.load_prompts", return_value=sample_prompts):
                with patch.dict(
                    "os.environ",
                    {
                        "DATABRICKS_HOST": "https://test.cloud.databricks.com/",
                        "DATABRICKS_TOKEN": "test-token",
                    },
                ):
                    settings = create_settings()
                    assert not settings.databricks_host.endswith("/")

    def test_get_settings_caching(self, mock_config_loader, mock_env_vars):
        """Test get_settings returns cached instance."""
        settings1 = get_settings()
        settings2 = get_settings()

        assert settings1 is settings2

    def test_reload_settings_clears_cache(self, mock_config_loader, mock_env_vars):
        """Test reload_settings creates new instance."""
        settings1 = get_settings()
        settings2 = reload_settings()

        # Should be different instances (cache was cleared)
        assert settings1 is not settings2

    def test_settings_with_feature_flags(
        self, mock_config_loader, mock_env_vars, sample_config, sample_prompts
    ):
        """Test settings with feature flags enabled."""
        # Modify the config
        modified_config = sample_config.copy()
        modified_config["features"] = {"enable_caching": True, "enable_streaming": False, "enable_batch_processing": False}

        with patch("src.config.settings.load_config", return_value=modified_config):
            with patch("src.config.settings.load_prompts", return_value=sample_prompts):
                settings = create_settings()
                assert settings.features.enable_caching is True

    def test_environment_setting(self, mock_config_loader, mock_env_vars):
        """Test environment setting is loaded."""
        settings = create_settings()
        assert settings.environment == "test"

