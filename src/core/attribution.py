"""The labels Tellr puts on its own requests.

A label is a product name, a version or one of a fixed list of feature names.
Nothing here ever carries a prompt, deck content, user text or a customer name.
Every function returns a fallback instead of raising: a label must never be the
reason a request or a deploy fails.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from importlib import metadata
from typing import Final

#: The wheel a deployed app installs (``packages/databricks-tellr-app``).
APP_PACKAGE: Final[str] = "databricks-tellr-app"
PRODUCT_NAME_SYSTEM: Final[str] = "tellr-app-system"
PRODUCT_NAME_USER_PREFIX: Final[str] = "tellr-app-"
PRODUCT_NAME_UNKNOWN: Final[str] = "tellr-app-unknown"


@lru_cache(maxsize=1)
def package_version() -> str:
    """The deployed release: the installed wheel's metadata, else the source tree's.

    The wheel's copied ``src/`` has no generated ``_version.py``, so the source
    tree alone reports ``src/__init__``'s placeholder on a deployed app.  Looked
    up once per process; ``package_version.cache_clear()`` forgets the answer.
    """
    try:
        installed: str | None = metadata.version(APP_PACKAGE)
    except Exception:  # noqa: BLE001 - not installed, or unreadable metadata
        installed = None
    if installed:  # a dist-info with no ``Version`` field reports ``None``
        return installed
    try:
        from src._version import version

        return version
    except Exception:  # noqa: BLE001 - not generated (a wheel's ``src/``), or unreadable
        pass
    try:
        from src import __version__

        return __version__
    except Exception:  # noqa: BLE001 - the last link: never raise into a request
        return "unknown"


def hash_username(username: str) -> str:
    """First 12 hex of SHA-256 of the email's local part (the whole name if no ``@``)."""
    local_part = username.split("@")[0] if "@" in username else username
    return hashlib.sha256(local_part.encode()).hexdigest()[:12]


def system_product_kwargs() -> dict[str, str]:
    """``product=`` / ``product_version=`` for a client that runs as the app."""
    return {"product": PRODUCT_NAME_SYSTEM, "product_version": package_version()}
