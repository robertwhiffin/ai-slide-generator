"""Dual-token authentication for the MCP endpoint.

Accepts two token sources in priority order:

1. ``x-forwarded-access-token`` — injected by the Databricks Apps proxy.
   Highest trust; cannot be spoofed from outside the proxy.
2. ``Authorization: Bearer <token>`` — fallback for external callers
   (laptop MCP clients, agent tools) that are not behind the proxy.

The resolved identity is bound into the same request-scoped ContextVars
the browser flow uses (``set_current_user``, ``set_user_client``,
``set_permission_context``), so downstream services (session manager,
permission service, MLflow, Google OAuth) see the caller's identity
without any MCP-specific plumbing.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator, Optional

from fastapi import Request

from src.core.databricks_client import (
    get_or_create_user_client,
    set_user_client,
)
from src.core.permission_context import (
    build_permission_context,
    set_permission_context,
)
from src.core.user_context import set_current_user

logger = logging.getLogger(__name__)


class MCPAuthError(Exception):
    """Raised when a request to /mcp lacks valid authentication."""


@dataclass
class MCPIdentity:
    user_id: Optional[str]
    user_name: str
    token: str = field(repr=False)
    source: str  # "x-forwarded-access-token" or "authorization-bearer"


def extract_mcp_identity(request: Request) -> MCPIdentity:
    """Resolve the caller's identity from request headers.

    Raises ``MCPAuthError`` if no valid token is found or if the token
    cannot be resolved to an identity.
    """
    # Priority 1: proxy-injected token
    token = request.headers.get("x-forwarded-access-token")
    source = "x-forwarded-access-token"

    if not token:
        # Priority 2: Authorization: Bearer fallback
        authz = (
            request.headers.get("authorization")
            or request.headers.get("Authorization")
            or ""
        )
        if authz.lower().startswith("bearer "):
            token = authz[len("Bearer "):].strip()
            source = "authorization-bearer"
        elif authz:
            raise MCPAuthError(
                "Unsupported Authorization scheme; expected 'Bearer <token>'"
            )

    if not token:
        logger.warning(
            "MCP auth: no credentials presented; received header keys: %s",
            sorted(request.headers.keys()),
        )
        raise MCPAuthError("Authentication required: no credentials presented")

    try:
        user_client = get_or_create_user_client(token)
        me = user_client.current_user.me()
    except Exception as e:
        logger.warning("MCP auth: identity resolution failed: %s", e)
        raise MCPAuthError("Invalid or expired credentials") from e

    return MCPIdentity(
        user_id=getattr(me, "id", None),
        user_name=getattr(me, "user_name", "") or "",
        token=token,
        source=source,
    )


@contextmanager
def mcp_auth_scope(request: Request) -> Iterator[MCPIdentity]:
    """Authenticate an MCP request and bind identity ContextVars for the block.

    On entry: resolves identity, binds ``current_user``, ``user_client``,
    and ``permission_context``.

    On exit: clears all three ContextVars, even if the wrapped block raised.
    """
    identity = extract_mcp_identity(request)

    user_client = get_or_create_user_client(identity.token)
    permission_ctx = build_permission_context(
        user_id=identity.user_id,
        user_name=identity.user_name,
        fetch_groups=False,
    )

    set_current_user(identity.user_name)
    set_user_client(user_client)
    set_permission_context(permission_ctx)

    logger.debug(
        "MCP auth scope entered",
        extra={
            "user_name": identity.user_name,
            "token_source": identity.source,
        },
    )

    try:
        yield identity
    finally:
        set_current_user(None)
        set_user_client(None)
        set_permission_context(None)
