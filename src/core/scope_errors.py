"""Missing OAuth scope detection and the user-facing consent message."""

from __future__ import annotations

import base64
import json
import re

_SCOPE_RE = re.compile(r"(required scopes|invalid scope)", re.I)

_PLACEHOLDER_CLIENT_ID = "<this app's OAuth client ID>"


def is_missing_scope_error(exc: BaseException) -> bool:
    """True if exc, its cause/context chain or any exception group member mentions a missing scope."""
    seen: set[int] = set()
    stack: list[BaseException] = [exc]
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if _SCOPE_RE.search(str(current)):
            return True
        if current.__cause__ is not None:
            stack.append(current.__cause__)
        if current.__context__ is not None:
            stack.append(current.__context__)
        if isinstance(current, BaseExceptionGroup):
            stack.extend(current.exceptions)
    return False


def oauth_client_id_from_token(token: str | None) -> str | None:
    """Read client_id (else azp) from a JWT payload without verifying it. Never raises."""
    try:
        if not token:
            return None
        parts = token.split(".")
        if len(parts) != 3:
            return None
        segment = parts[1]
        segment += "=" * (-len(segment) % 4)
        payload = json.loads(base64.urlsafe_b64decode(segment.encode("ascii")))
        if not isinstance(payload, dict):
            return None
        value = payload.get("client_id") or payload.get("azp")
        return value if isinstance(value, str) and value else None
    except Exception:
        return None


def consent_message(*, oauth_client_id: str | None) -> str:
    client_id = oauth_client_id or _PLACEHOLDER_CLIENT_ID
    return (
        "Tellr can't do this on your behalf yet: your sign-in to this app is missing a permission it needs.\n"
        "\n"
        "There are two possible causes:\n"
        "1. The app itself hasn't been given the permission. A workspace admin fixes this by running tellr.update() for this app.\n"
        "2. You approved this app before it needed this permission. To approve it again:\n"
        f"   a. Run: databricks api delete /api/2.0/oauth-app-integrations/{client_id}/user-consent/me\n"
        "   b. Clear this site's data in your browser, or open the app in a private window.\n"
        "   c. Reload the app and approve the new permissions when asked."
    )
