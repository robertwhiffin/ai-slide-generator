"""Dual-token authentication for the MCP endpoint.

Accepts three identity sources, evaluated in priority order:

1. ``x-forwarded-access-token`` — injected by the Databricks Apps proxy
   when a user hits tellr's own ``/mcp`` endpoint directly. Highest trust;
   cannot be spoofed from outside the proxy.
2. ``Authorization: Bearer <token>`` — fallback for external callers
   (laptop MCP clients, Claude Code, CI scripts) that are not behind the
   Databricks Apps proxy at all.
3. ``x-forwarded-email`` + ``x-forwarded-user`` — the identity-only path
   used by **app-to-app calls** in the Databricks Apps platform. The
   calling app's OBO token does not survive the proxy hop: the proxy
   strips ``Authorization`` and ``x-forwarded-access-token`` from inbound
   app-to-app traffic and replaces them with proxy-attested ``X-Forwarded-*``
   identity headers. The receiving app (tellr) trusts those headers
   because the same proxy sets them, strips any caller-supplied versions,
   and cannot be bypassed by external traffic. This path has no user
   token, so downstream Databricks API calls use tellr's own service
   principal credentials; attribution (``created_by`` on decks, etc.)
   remains the real user via ``user_name``.

The priority-3 path is gated on ``TELLR_TRUST_FORWARDED_IDENTITY=true``
so the behaviour is explicit at deploy time. Production Databricks Apps
deployments enable it; local dev does not.

The resolved identity is bound into the same request-scoped ContextVars
the browser flow uses (``set_current_user``, ``set_user_client``,
``set_permission_context``), so downstream services (session manager,
permission service, MLflow, Google OAuth) see the caller's identity
without any MCP-specific plumbing.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator, Optional

from fastapi import Request

from src.core.databricks_client import (
    get_or_create_user_client,
    get_system_client,
    set_user_client,
)
from src.core.permission_context import (
    build_permission_context,
    set_permission_context,
)
from src.core.user_context import set_current_user

logger = logging.getLogger(__name__)


def _trust_forwarded_identity() -> bool:
    """Deploy-time opt-in for the priority-3 identity-header path.

    Enabled by setting ``TELLR_TRUST_FORWARDED_IDENTITY`` to a truthy
    value in the app environment. Off by default so local runs and
    non-Databricks-Apps deployments behave identically to the prior
    dual-token model.
    """
    return os.getenv("TELLR_TRUST_FORWARDED_IDENTITY", "").lower() in (
        "1", "true", "yes", "on",
    )


class MCPAuthError(Exception):
    """Raised when a request to /mcp lacks valid authentication."""


@dataclass
class MCPIdentity:
    user_id: Optional[str]
    user_name: str
    token: Optional[str] = field(repr=False)
    source: str  # "x-forwarded-access-token" | "authorization-bearer" | "x-forwarded-identity"


def extract_mcp_identity(request: Request) -> MCPIdentity:
    """Resolve the caller's identity from request headers.

    Raises ``MCPAuthError`` if no valid identity source is found or if a
    presented token cannot be resolved to an identity.
    """
    # Priority 1: proxy-injected user OBO token
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

    if token:
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

    # Priority 3: proxy-attested forwarded identity (no token).
    # Only honored when TELLR_TRUST_FORWARDED_IDENTITY is set at deploy time
    # so non-Apps deployments (local dev, bare VMs) fail closed rather than
    # trusting freely-caller-supplied headers.
    if _trust_forwarded_identity():
        email = request.headers.get("x-forwarded-email")
        forwarded_user = request.headers.get("x-forwarded-user") or ""
        if email:
            # The proxy formats x-forwarded-user as "<user_id>@<workspace_id>".
            # Extract the user_id; if the format is unexpected, fall back to
            # None rather than surfacing a corrupt ID downstream.
            user_id = (
                forwarded_user.split("@", 1)[0]
                if "@" in forwarded_user
                else None
            )
            return MCPIdentity(
                user_id=user_id,
                user_name=email,
                token=None,
                source="x-forwarded-identity",
            )

    raise MCPAuthError("Authentication required: no credentials presented")


@contextmanager
def mcp_auth_scope(request: Request) -> Iterator[MCPIdentity]:
    """Authenticate an MCP request and bind identity ContextVars for the block.

    On entry: resolves identity, binds ``current_user``, ``user_client``,
    and ``permission_context``.

    On exit: clears all three ContextVars, even if the wrapped block raised.

    When the identity was resolved via priority 3 (no user token), the
    bound ``user_client`` is tellr's service-principal client — downstream
    services still function, but any SDK calls are made with SP credentials
    rather than the user's own. Attribution (``created_by``) is unaffected:
    it uses ``user_name`` from the forwarded identity headers, which the
    proxy attests.
    """
    identity = extract_mcp_identity(request)

    if identity.token is not None:
        user_client = get_or_create_user_client(identity.token)
    else:
        # Priority-3 path: no user token, so downstream Databricks API
        # calls use tellr's service principal. Safe because the app-to-app
        # model explicitly delegates credentialing to the receiving app.
        user_client = get_system_client()

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
