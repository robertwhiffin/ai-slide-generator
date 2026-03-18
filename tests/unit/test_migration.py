import pytest


def test_profile_with_genie_space_migrates():
    from src.core.migrate_profiles_to_agent_config import build_agent_config_from_profile

    profile_data = {
        "prompts": {
            "selected_slide_style_id": 3,
            "selected_deck_prompt_id": 7,
            "system_prompt": None,
            "slide_editing_instructions": None,
        },
        "genie_spaces": [
            {"space_id": "abc", "space_name": "Sales", "description": "Revenue data"}
        ],
    }
    config = build_agent_config_from_profile(profile_data)
    assert len(config["tools"]) == 1
    assert config["tools"][0]["type"] == "genie"
    assert config["tools"][0]["space_id"] == "abc"
    assert config["slide_style_id"] == 3
    assert config["deck_prompt_id"] == 7


def test_profile_without_genie_space_migrates():
    from src.core.migrate_profiles_to_agent_config import build_agent_config_from_profile

    profile_data = {
        "prompts": {
            "selected_slide_style_id": None,
            "selected_deck_prompt_id": None,
            "system_prompt": None,
            "slide_editing_instructions": None,
        },
        "genie_spaces": [],
    }
    config = build_agent_config_from_profile(profile_data)
    assert config["tools"] == []
    assert config["slide_style_id"] is None


def test_custom_prompts_preserved():
    from src.core.migrate_profiles_to_agent_config import build_agent_config_from_profile

    profile_data = {
        "prompts": {
            "selected_slide_style_id": None,
            "selected_deck_prompt_id": None,
            "system_prompt": "Custom system prompt",
            "slide_editing_instructions": "Custom editing instructions",
        },
        "genie_spaces": [],
    }
    config = build_agent_config_from_profile(profile_data)
    assert config["system_prompt"] == "Custom system prompt"
    assert config["slide_editing_instructions"] == "Custom editing instructions"


def test_default_prompts_become_none():
    from src.core.defaults import DEFAULT_CONFIG
    from src.core.migrate_profiles_to_agent_config import build_agent_config_from_profile

    default_system = DEFAULT_CONFIG["prompts"]["system_prompt"]
    profile_data = {
        "prompts": {
            "selected_slide_style_id": None,
            "selected_deck_prompt_id": None,
            "system_prompt": default_system,
            "slide_editing_instructions": None,
        },
        "genie_spaces": [],
    }
    config = build_agent_config_from_profile(profile_data)
    assert config["system_prompt"] is None
