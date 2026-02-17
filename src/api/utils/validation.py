"""Validation utilities for API routes."""

import json


def validate_credentials_json(raw: str) -> dict:
    """Parse and validate the credentials JSON structure.

    Google OAuth credentials must contain either an ``installed`` or ``web`` key.

    Raises:
        ValueError: If the JSON is invalid or missing required keys.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("Credentials must be a JSON object")

    if "installed" not in data and "web" not in data:
        raise ValueError(
            "Invalid Google OAuth credentials: must contain an 'installed' or 'web' key"
        )

    return data
