"""Unit tests for configuration management."""

import os
import pytest
from pathlib import Path
from unittest.mock import patch

from slide_generator.config import Config, config, get_output_path, get_test_fixture_path


class TestConfig:
    """Test the configuration system."""
    
    def test_default_config_values(self):
        """Test that default configuration values are set correctly."""
        test_config = Config()
        
        assert test_config.debug is False
        assert test_config.log_level == "INFO"
        assert test_config.llm_endpoint == "databricks-claude-sonnet-4"
        assert test_config.gradio_host == "127.0.0.1"
        assert test_config.gradio_port == 7860
        assert test_config.gradio_share is False
        assert isinstance(test_config.output_dir, Path)
        assert "slide creation assistant" in test_config.system_prompt.lower()
    
    @patch.dict(os.environ, {
        "DEBUG": "true",
        "LOG_LEVEL": "DEBUG", 
        "LLM_ENDPOINT": "test-endpoint",
        "GRADIO_HOST": "0.0.0.0",
        "GRADIO_PORT": "8080",
        "GRADIO_SHARE": "true"
    })
    def test_config_from_environment(self):
        """Test that configuration reads from environment variables."""
        # Need to reload the config module to pick up env changes
        from slide_generator import config as config_module
        import importlib
        importlib.reload(config_module)
        
        test_config = config_module.Config()
        
        assert test_config.debug is True
        assert test_config.log_level == "DEBUG"
        assert test_config.llm_endpoint == "test-endpoint"
        assert test_config.gradio_host == "0.0.0.0"
        assert test_config.gradio_port == 8080
        assert test_config.gradio_share is True
    
    def test_config_validation(self):
        """Test configuration validation."""
        test_config = Config()
        
        # Valid config should pass
        assert test_config.validate() is True
        
        # Invalid config should raise error
        test_config.llm_endpoint = ""
        with pytest.raises(ValueError, match="LLM_ENDPOINT must be specified"):
            test_config.validate()
    
    def test_get_output_path(self):
        """Test output path generation."""
        path = get_output_path("test.html")
        
        assert isinstance(path, Path)
        assert path.name == "test.html"
        assert "output" in str(path)
    
    def test_get_test_fixture_path(self):
        """Test test fixture path generation."""
        path = get_test_fixture_path("sample.html")
        
        assert isinstance(path, Path)
        assert path.name == "sample.html"
        assert "fixtures" in str(path)
    
    def test_global_config_instance(self):
        """Test that the global config instance is properly initialized."""
        assert config is not None
        assert isinstance(config, Config)
        assert config.llm_endpoint is not None
        assert config.output_dir is not None



