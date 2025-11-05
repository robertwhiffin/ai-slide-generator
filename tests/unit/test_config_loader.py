"""
Unit tests for configuration loader.
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from src.config.loader import (
    ConfigurationError,
    get_config_path,
    load_config,
    load_prompts,
    load_yaml_file,
    merge_with_env,
)


class TestGetConfigPath:
    """Tests for get_config_path function."""

    def test_get_config_path_success(self):
        """Test getting config path for existing file."""
        # This test uses the actual config files in the project
        result = get_config_path("config.yaml")
        assert result.name == "config.yaml"
        assert result.exists()

    def test_get_config_path_file_not_found(self):
        """Test error when config file doesn't exist."""
        with pytest.raises(ConfigurationError, match="Configuration file not found"):
            get_config_path("nonexistent.yaml")


class TestLoadYamlFile:
    """Tests for load_yaml_file function."""

    def test_load_valid_yaml(self, tmp_path: Path):
        """Test loading valid YAML file."""
        yaml_file = tmp_path / "test.yaml"
        test_data = {"key": "value", "number": 42}

        with open(yaml_file, "w") as f:
            yaml.dump(test_data, f)

        result = load_yaml_file(yaml_file)
        assert result == test_data

    def test_load_empty_yaml(self, tmp_path: Path):
        """Test error on empty YAML file."""
        yaml_file = tmp_path / "empty.yaml"
        yaml_file.write_text("")

        with pytest.raises(ConfigurationError, match="YAML file is empty"):
            load_yaml_file(yaml_file)

    def test_load_invalid_yaml(self, tmp_path: Path):
        """Test error on invalid YAML syntax."""
        yaml_file = tmp_path / "invalid.yaml"
        # Use truly invalid YAML syntax that will fail parsing
        yaml_file.write_text("key: [\ninvalid")

        with pytest.raises(ConfigurationError, match="Failed to parse YAML"):
            load_yaml_file(yaml_file)

    def test_load_non_dict_yaml(self, tmp_path: Path):
        """Test error when YAML doesn't contain a dictionary."""
        yaml_file = tmp_path / "list.yaml"
        yaml_file.write_text("- item1\n- item2")

        with pytest.raises(ConfigurationError, match="must contain a dictionary"):
            load_yaml_file(yaml_file)

    def test_load_file_not_found(self, tmp_path: Path):
        """Test error when file doesn't exist."""
        yaml_file = tmp_path / "nonexistent.yaml"

        with pytest.raises(ConfigurationError, match="Failed to read file"):
            load_yaml_file(yaml_file)


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_success(self, sample_config: dict):
        """Test successful config loading."""
        with patch("src.config.loader.load_yaml_file", return_value=sample_config):
            result = load_config()
            assert result == sample_config

    def test_load_config_missing_required_keys(self):
        """Test error when required keys are missing."""
        incomplete_config = {"llm": {}, "genie": {}}

        with patch("src.config.loader.load_yaml_file", return_value=incomplete_config):
            with pytest.raises(ConfigurationError, match="Missing required configuration sections"):
                load_config()

    def test_load_config_validates_all_required_keys(self, sample_config: dict):
        """Test all required keys are validated."""
        for key in ["llm", "genie", "api", "output", "logging"]:
            incomplete_config = sample_config.copy()
            del incomplete_config[key]

            with patch("src.config.loader.load_yaml_file", return_value=incomplete_config):
                with pytest.raises(ConfigurationError, match=f"Missing required.*{key}"):
                    load_config()


class TestLoadPrompts:
    """Tests for load_prompts function."""

    def test_load_prompts_success(self, sample_prompts: dict):
        """Test successful prompts loading."""
        with patch("src.config.loader.load_yaml_file", return_value=sample_prompts):
            result = load_prompts()
            assert result == sample_prompts

    def test_load_prompts_missing_required_prompts(self):
        """Test error when required prompts are missing."""
        incomplete_prompts = {"system_prompt": "test"}

        with patch("src.config.loader.load_yaml_file", return_value=incomplete_prompts):
            with pytest.raises(ConfigurationError, match="Missing required prompts"):
                load_prompts()

    def test_load_prompts_validates_all_required(self, sample_prompts: dict):
        """Test all required prompts are validated."""
        required = [
            "system_prompt",
            "intent_analysis",
            "data_interpretation",
            "narrative_construction",
            "html_generation",
        ]

        for prompt_key in required:
            incomplete_prompts = sample_prompts.copy()
            del incomplete_prompts[prompt_key]

            with patch("src.config.loader.load_yaml_file", return_value=incomplete_prompts):
                with pytest.raises(ConfigurationError, match=f"Missing required.*{prompt_key}"):
                    load_prompts()


class TestMergeWithEnv:
    """Tests for merge_with_env function."""

    def test_merge_api_port(self, sample_config: dict):
        """Test API_PORT environment variable override."""
        with patch.dict(os.environ, {"API_PORT": "9000"}):
            result = merge_with_env(sample_config)
            assert result["api"]["port"] == 9000

    def test_merge_log_level(self, sample_config: dict):
        """Test LOG_LEVEL environment variable override."""
        with patch.dict(os.environ, {"LOG_LEVEL": "debug"}):
            result = merge_with_env(sample_config)
            assert result["logging"]["level"] == "DEBUG"

    def test_merge_environment(self, sample_config: dict):
        """Test ENVIRONMENT variable."""
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}):
            result = merge_with_env(sample_config)
            assert result["environment"] == "production"

    def test_merge_invalid_port(self, sample_config: dict):
        """Test invalid API_PORT is ignored."""
        original_port = sample_config["api"]["port"]

        with patch.dict(os.environ, {"API_PORT": "invalid"}):
            result = merge_with_env(sample_config)
            assert result["api"]["port"] == original_port

    def test_merge_no_overrides(self, sample_config: dict):
        """Test config unchanged when no env vars set."""
        with patch.dict(os.environ, {}, clear=True):
            result = merge_with_env(sample_config)
            assert result == sample_config

    def test_merge_doesnt_modify_original(self, sample_config: dict):
        """Test original config is not modified."""
        original = sample_config.copy()

        with patch.dict(os.environ, {"API_PORT": "9000"}):
            merge_with_env(sample_config)
            assert sample_config == original

