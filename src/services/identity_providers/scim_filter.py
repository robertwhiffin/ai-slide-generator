"""Helpers for safely constructing SCIM filters."""


def escape_scim_filter_string(value: str) -> str:
    """Escape a value for use inside a SCIM filter string literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"')
