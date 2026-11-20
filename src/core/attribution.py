"""The labels Tellr puts on its own requests.

A label is a product name, a version or a value from a fixed list.  Nothing here
ever carries a prompt, deck content, user text or a customer name.  The Gateway tag
(``src/services/gateway_clients.py``) carries ``"source": "tellr"``, an optional
``component`` from ``gateway_clients.COMPONENTS`` and an optional ``entrypoint``
from :data:`ENTRYPOINTS`; a value off its list adds no key.
The version lookup (``package_version``, and so ``system_product_kwargs``) returns
a fallback instead of raising, and a value off a list is ignored rather than raising:
a label must never be the reason a request or a deploy fails.  A user's product name
is remembered under a SHA-256 of their token, never the token itself, so a client
built in a worker thread can still be labelled.  A chat turn's entrypoint lives in a
ContextVar: only the turn's own context, and the copies of it that the job queue and
the chat service take, can see it.
"""

from __future__ import annotations

import hashlib
import threading
from contextvars import ContextVar
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


#: At least as many tokens as the user-client cache holds at once.
_MAX_TOKEN_PRODUCTS: Final[int] = 200
#: SHA-256 of a user token -> that user's product name.  Never the token itself.
_token_products: dict[str, str] = {}
_token_products_lock = threading.Lock()


def _token_key(token: object) -> str | None:
    """The SHA-256 of ``token``, or ``None`` (no token) unless it is a non-empty ``str``."""
    if not isinstance(token, str) or not token:
        return None
    try:
        return hashlib.sha256(token.encode()).hexdigest()
    except Exception:  # noqa: BLE001 - a token that cannot be encoded is no token
        return None


def remember_user_product(token: str, product: str) -> None:
    """Record the product name of the user who owns ``token`` (oldest entry dropped at the cap).

    Remembering a token again replaces its product name and makes it the newest entry.
    A token that is not a non-empty ``str`` is not recorded.
    """
    key = _token_key(token)
    if key is None:
        return
    with _token_products_lock:
        _token_products.pop(key, None)
        while len(_token_products) >= _MAX_TOKEN_PRODUCTS:
            _token_products.pop(next(iter(_token_products)))
        _token_products[key] = product


def user_product_kwargs(token: str | None = None) -> dict[str, str]:
    """``product=`` / ``product_version=`` for a client that runs as a user.

    The product remembered for ``token`` (works in any thread), else the hash of
    the request's user, else ``tellr-app-unknown``.  Makes no network call, and
    never raises: a token that is not a non-empty ``str`` counts as no token, and a
    request user that cannot be read or hashed as no user.
    """
    product: str | None = None
    key = _token_key(token)
    if key is not None:
        with _token_products_lock:
            product = _token_products.get(key)
    if product is None:
        try:
            from src.core.user_context import get_current_user

            username = get_current_user()
            product = (
                f"{PRODUCT_NAME_USER_PREFIX}{hash_username(username)}"
                if username
                else PRODUCT_NAME_UNKNOWN
            )
        except Exception:  # noqa: BLE001 - a label never fails a request
            product = PRODUCT_NAME_UNKNOWN
    return {"product": product, "product_version": package_version()}


def mcp_user_agent() -> str:
    """User-Agent of Tellr's MCP HTTP client: product first, the library's own kept after it."""
    import httpx

    return f"tellr/{package_version()} python-httpx/{httpx.__version__}"


#: How a chat turn reached Tellr: its own UI, or its MCP server.
ENTRYPOINTS: Final[frozenset[str]] = frozenset({"app", "mcp"})
#: The chat turn's entrypoint, ``None`` outside a turn.  Each enqueue site sets it in
#: its request's own context just before ``enqueue_job``, which copies that context
#: for the worker, so every Gateway client built for the turn reads it.
_entrypoint_var: ContextVar[str | None] = ContextVar("tellr_entrypoint", default=None)


def set_entrypoint(value: str) -> None:
    """Mark the current context's chat turn; a value off the list is ignored.

    Only a plain ``str`` in :data:`ENTRYPOINTS` counts.  Any other value, an unhashable
    value or a ``str`` stand-in included, changes nothing and never raises.
    """
    if type(value) is str and value in ENTRYPOINTS:
        _entrypoint_var.set(value)


def get_entrypoint() -> str | None:
    """The current context's chat-turn entrypoint, or ``None`` outside a turn."""
    return _entrypoint_var.get()
