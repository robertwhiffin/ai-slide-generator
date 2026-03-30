"""Tests for DEFAULT_CONFIG in src.core.defaults."""

from src.core.defaults import DEFAULT_CONFIG


def test_llm_config_has_correct_values():
    """Verify LLM defaults match Opus 4.6 configuration."""
    llm = DEFAULT_CONFIG["llm"]
    assert llm["endpoint"] == "databricks-claude-opus-4-6"
    assert llm["temperature"] == 0.7
    assert llm["max_tokens"] == 60000
    assert llm["top_p"] == 0.95
    assert llm["timeout"] == 600


def test_llm_config_has_exactly_expected_keys():
    """Ensure no unexpected keys sneak into the LLM config."""
    expected_keys = {"endpoint", "temperature", "max_tokens", "top_p", "timeout"}
    assert set(DEFAULT_CONFIG["llm"].keys()) == expected_keys
