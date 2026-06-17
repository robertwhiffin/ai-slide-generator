# tests/unit/test_text_caps.py
"""Tests for tool-output length capping (AISEC-248 PR2)."""

from src.utils.text_caps import cap_tool_output


def test_short_output_unchanged():
    assert cap_tool_output("hello") == "hello"


def test_long_output_truncated_with_marker():
    out = cap_tool_output("x" * 40000, limit=32768)
    assert len(out) <= 32768 + len("\n…[truncated]")
    assert out.endswith("…[truncated]")
