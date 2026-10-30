"""Missing OAuth scope detection and the user-facing consent message."""

from __future__ import annotations

import base64
import builtins
import json
import re

_GROUP = getattr(builtins, "BaseExceptionGroup", ())

_SCOPE_RE = re.compile(r"(required scopes|invalid scope)", re.I)

_PLACEHOLDER_CLIENT_ID = "<this app's OAuth client ID>"

#: A token scoped ``all-apis`` (a CLI or PAT-style OAuth token) may call every
#: API, so it holds every narrower scope too.
_ALL_APIS_SCOPE = "all-apis"


def mentions_missing_scope(text: str) -> bool:
    """True if *text* says a scope is missing (``required scopes`` / ``invalid scope``)."""
    return _SCOPE_RE.search(text) is not None


def is_missing_scope_error(exc: BaseException) -> bool:
    """True if exc, its cause/context chain or any exception group member mentions a missing scope."""
    seen: set[int] = set()
    stack: list[BaseException] = [exc]
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if mentions_missing_scope(str(current)):
            return True
        if current.__cause__ is not None:
            stack.append(current.__cause__)
        if current.__context__ is not None:
            stack.append(current.__context__)
        if _GROUP and isinstance(current, _GROUP):
            stack.extend(current.exceptions)
    return False


def _jwt_payload(token: str | None) -> dict | None:
    """The payload of a JWT, decoded WITHOUT verifying it; ``None`` if *token* is not one."""
    if not token:
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    segment = parts[1]
    segment += "=" * (-len(segment) % 4)
    payload = json.loads(base64.urlsafe_b64decode(segment.encode("ascii")))
    return payload if isinstance(payload, dict) else None


def oauth_client_id_from_token(token: str | None) -> str | None:
    """Read client_id (else azp) from a JWT payload without verifying it. Never raises."""
    try:
        payload = _jwt_payload(token)
        if payload is None:
            return None
        value = payload.get("client_id") or payload.get("azp")
        return value if isinstance(value, str) and value else None
    except Exception:
        return None


def oauth_scopes_from_token(token: str | None) -> frozenset[str] | None:
    """The OAuth scopes a JWT says it carries, read WITHOUT verifying it. Never raises.

    Reads the ``scope`` claim (else ``scp``): a space-separated string or a list
    of strings.  ``None`` means "not known": *token* is not a JWT, or neither
    claim names a scope.  Callers act only on a known set, so an unreadable
    token is never refused for a scope it may well have.
    """
    try:
        payload = _jwt_payload(token)
        if payload is None:
            return None
        for claim in ("scope", "scp"):
            value = payload.get(claim)
            if isinstance(value, str):
                scopes = value.split()
            elif isinstance(value, list):
                scopes = [s for item in value if isinstance(item, str) for s in item.split()]
            else:
                continue
            if scopes:
                return frozenset(scopes)
        return None
    except Exception:
        return None


def scopes_grant(scopes: frozenset[str], scope: str) -> bool:
    """True if a token carrying *scopes* holds *scope* (``all-apis`` holds every scope)."""
    return scope in scopes or _ALL_APIS_SCOPE in scopes


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
