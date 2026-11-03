"""The shape of an AI Gateway MCP service name (``catalog.schema.service``).

Kept free of ``src.services`` and ``src.api`` imports so the API schemas can use it
without a circular import.
"""

from __future__ import annotations

import re
from typing import Final

_SERVICE_NAME_RE: Final = re.compile(r"^[a-z0-9_-]+\.[a-z0-9_-]+\.[a-z0-9_-]+$")


def validate_service_name(name: str) -> str:
    """The service name, stripped and lower-cased; ``ValueError`` unless it is ``a.b.c``."""
    normalised = name.strip().lower()
    if not _SERVICE_NAME_RE.fullmatch(normalised):
        raise ValueError(
            f"Invalid MCP service name {name!r}: expected <catalog>.<schema>.<service>"
        )
    return normalised
