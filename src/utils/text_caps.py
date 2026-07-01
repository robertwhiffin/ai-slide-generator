# src/utils/text_caps.py
"""Length caps for untrusted tool output (AISEC-248 PR2)."""

DEFAULT_TOOL_OUTPUT_LIMIT = 32768  # 32 KB
_MARKER = "\n…[truncated]"


def cap_tool_output(text: str, limit: int = DEFAULT_TOOL_OUTPUT_LIMIT) -> str:
    """Truncate tool output to `limit` chars, appending a truncation marker."""
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + _MARKER
