"""Request-scoped user identity via ContextVar.

The middleware sets the current user at the start of each request and clears it
in the ``finally`` block, giving every downstream handler cheap, synchronous
access to the authenticated username without an extra Databricks API call.
"""

from contextvars import ContextVar
from typing import Optional

_current_user_var: ContextVar[Optional[str]] = ContextVar(
    "current_user", default=None
)


def set_current_user(username: Optional[str]) -> None:
    """Store the authenticated username for the current request."""
    _current_user_var.set(username)


def get_current_user() -> Optional[str]:
    """Return the authenticated username, or ``None`` if not set."""
    return _current_user_var.get()


def require_current_user() -> str:
    """Return the authenticated username or raise if unavailable.

    Raises:
        RuntimeError: When no user identity has been set for the request.
    """
    user = _current_user_var.get()
    if not user:
        raise RuntimeError("No authenticated user in request context")
    return user
