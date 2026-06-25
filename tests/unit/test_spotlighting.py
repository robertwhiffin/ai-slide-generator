"""Tests for untrusted-data spotlighting (AISEC-248 PR2)."""

from src.core.prompt_modules import (
    UNTRUSTED_DATA_NOTICE,
    build_generation_system_prompt,
    build_editing_system_prompt,
)
from src.utils.text_caps import cap_tool_output  # noqa: F401  (sanity)


def test_notice_present_in_both_prompts():
    gen = build_generation_system_prompt("STYLE")
    edit = build_editing_system_prompt("STYLE")
    assert UNTRUSTED_DATA_NOTICE in gen
    assert UNTRUSTED_DATA_NOTICE in edit


def test_notice_mentions_no_following_instructions():
    assert "Do not follow" in UNTRUSTED_DATA_NOTICE or "never follow" in UNTRUSTED_DATA_NOTICE.lower()
