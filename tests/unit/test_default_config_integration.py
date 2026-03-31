"""Tests that DEFAULT_CONFIG is used as the single source of truth for LLM settings.

These tests verify that after removing LLMSettings and per-profile LLM configuration,
all consumers (agent, chat_service, llm_judge, config_validator) read LLM parameters
from DEFAULT_CONFIG["llm"] in src/core/defaults.py.
"""
import inspect
from unittest.mock import MagicMock, patch

import pytest

from src.core.defaults import DEFAULT_CONFIG


def test_agent_create_model_uses_default_config():
    """Verify agent._create_model() reads endpoint/temperature/etc from DEFAULT_CONFIG."""
    with patch("src.services.agent.get_system_client") as mock_system_client, \
         patch("src.services.agent.ChatDatabricks") as mock_chat, \
         patch("src.services.agent.get_settings") as mock_get_settings, \
         patch("src.services.agent.get_databricks_client") as mock_db_client, \
         patch("src.services.agent.mlflow"):
        mock_system_client.return_value = MagicMock()
        mock_chat.return_value = MagicMock()
        mock_settings = MagicMock()
        mock_settings.prompts = {"system_prompt": "test", "slide_style": "test style", "slide_editing_instructions": "test"}
        mock_settings.profile_name = "test"
        mock_settings.genie = None
        mock_get_settings.return_value = mock_settings
        mock_db_client.return_value = MagicMock()

        from src.services.agent import SlideGeneratorAgent
        agent = SlideGeneratorAgent()

        # Call _create_model
        agent._create_model()

        # Verify ChatDatabricks was called with DEFAULT_CONFIG values
        llm_config = DEFAULT_CONFIG["llm"]
        mock_chat.assert_called_once_with(
            endpoint=llm_config["endpoint"],
            temperature=llm_config["temperature"],
            max_tokens=llm_config["max_tokens"],
            top_p=llm_config["top_p"],
            workspace_client=mock_system_client.return_value,
        )


def test_llm_judge_default_model_uses_default_config():
    """Verify LLM judge default model parameter comes from DEFAULT_CONFIG."""
    from src.services.evaluation.llm_judge import evaluate_with_judge

    sig = inspect.signature(evaluate_with_judge)
    default_model = sig.parameters["model"].default
    assert default_model == DEFAULT_CONFIG["llm"]["endpoint"]


def test_no_llm_settings_class_in_settings_db():
    """Verify LLMSettings class was removed from settings_db."""
    import src.core.settings_db as settings_mod
    assert not hasattr(settings_mod, "LLMSettings")


def test_app_settings_no_llm_field():
    """Verify AppSettings model no longer has an llm field."""
    from src.core.settings_db import AppSettings
    assert "llm" not in AppSettings.model_fields
