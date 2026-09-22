import pytest


def test_profile_with_genie_space_migrates():
    from src.core.migrate_profiles_to_agent_config import build_agent_config_from_profile

    profile_data = {
        "prompts": {
            "selected_slide_style_id": 3,
            "selected_deck_prompt_id": 7,
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
        },
        "genie_spaces": [],
    }
    config = build_agent_config_from_profile(profile_data)
    assert config["tools"] == []
    assert config["slide_style_id"] is None


# DELETED with B2.4: test_custom_prompts_preserved asserted that a custom
# system_prompt / slide_editing_instructions is CARRIED FORWARD into agent_config,
# and test_default_prompts_become_none asserted that a value equal to the default
# is normalised to None there. Both keys are retired — build_agent_config_from_profile
# no longer emits them at all — so neither behaviour exists to assert.


