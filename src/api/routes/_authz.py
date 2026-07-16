"""Shared authorization helpers for API routes (SDR-4437 PR-2).

Consolidates the deck-permission helpers that previously lived in
``sessions.py`` and ``slides.py`` (names and signatures preserved), and adds:

- ``_require_export_job_access`` — job-ID → session_id → deck permission
  (closes the job-ID IDOR on export poll/download and Google Slides poll).
- ``require_admin`` — HIGH-2 admin primitive. Admin == holds CAN_MANAGE on
  the Databricks App itself, tested by reading the app's ACL with the
  caller's own OBO client (reading an object's ACL requires CAN_MANAGE on
  it, so the read succeeding *is* the admin test; group-held / inherited
  CAN_MANAGE resolves server-side for free).
"""

import logging
import os
import time
from typing import Optional, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from src.api.services.session_manager import SessionNotFoundError, get_session_manager
from src.core.database import get_db_session
from src.core.permission_context import get_permission_context
from src.core.user_context import get_current_user
from src.database.models.profile_contributor import PermissionLevel
from src.services.permission_service import PERMISSION_PRIORITY, get_permission_service

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Deck-permission helpers (moved from sessions.py / slides.py — verbatim)
# ---------------------------------------------------------------------------


def _get_session_permission_for_info(
    session_info: dict,
    db: Session,
) -> Tuple[bool, Optional[PermissionLevel]]:
    """Check user's permission on a session via deck_contributors.

    (Moved from sessions.py:_get_session_permission.)

    Resolves to the root session (parent for contributor sessions) and checks
    the DeckContributor table for the current user's permission level.

    Args:
        session_info: Session dict with id, created_by, parent_session_id, etc.
        db: Database session

    Returns:
        Tuple of (has_access, permission_level)
    """
    perm_ctx = get_permission_context()
    perm_service = get_permission_service()
    parent_id = session_info.get("parent_session_internal_id")
    root_session_id = parent_id if parent_id is not None else session_info.get("id")
    perm = perm_service.get_deck_permission(
        db, root_session_id,
        user_id=perm_ctx.user_id if perm_ctx else None,
        user_name=perm_ctx.user_name if perm_ctx else None,
        group_ids=perm_ctx.group_ids if perm_ctx else None,
    )
    if perm is None:
        return False, None
    return True, perm


def _get_session_permission_by_id(
    session_id: str,
    db: Session,
) -> Tuple[bool, Optional[PermissionLevel]]:
    """Check if current user has access to a session's slides via deck_contributors.

    (Moved from slides.py:_get_session_permission.)

    Resolves to the root session (parent for contributor sessions) and checks
    the DeckContributor table for the current user's permission level.

    Args:
        session_id: Session identifier (string)
        db: Database session

    Returns:
        Tuple of (has_access, permission_level)
    """
    session_manager = get_session_manager()
    ctx = get_permission_context()

    try:
        session_info = session_manager.get_session(session_id)
    except SessionNotFoundError:
        return False, None

    perm_service = get_permission_service()
    parent_internal_id = session_info.get("parent_session_internal_id")
    root_session_id = (
        parent_internal_id if parent_internal_id is not None else session_info.get("id")
    )

    perm = perm_service.get_deck_permission(
        db, root_session_id,
        user_id=ctx.user_id if ctx else None,
        user_name=ctx.user_name if ctx else None,
        group_ids=ctx.group_ids if ctx else None,
    )
    if perm is None:
        return False, None
    return True, perm


def _require_session_access(
    session_info: dict,
    db: Session,
    min_permission: PermissionLevel = PermissionLevel.CAN_VIEW,
) -> PermissionLevel:
    """Require user has at least the specified permission level on a session.

    (Moved from sessions.py.)

    Args:
        session_info: Session dict with created_by and profile_id
        db: Database session
        min_permission: Minimum required permission (default: CAN_VIEW)

    Returns:
        The user's actual permission level

    Raises:
        HTTPException 403: If user doesn't have required permission
    """
    has_access, permission = _get_session_permission_for_info(session_info, db)

    if not has_access or permission is None:
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to access this session",
        )

    if PERMISSION_PRIORITY[permission] < PERMISSION_PRIORITY[min_permission]:
        raise HTTPException(
            status_code=403,
            detail=f"This action requires {min_permission.value} permission",
        )

    return permission


def _require_slide_permission(
    session_id: str,
    db: Session,
    min_permission: PermissionLevel = PermissionLevel.CAN_VIEW,
) -> PermissionLevel:
    """Require user has at least the specified permission level on slides.

    (Moved from slides.py.)

    Args:
        session_id: Session identifier
        db: Database session
        min_permission: Minimum required permission (default: CAN_VIEW)

    Returns:
        The user's actual permission level

    Raises:
        HTTPException 403: If user doesn't have required permission
    """
    has_access, permission = _get_session_permission_by_id(session_id, db)

    if not has_access or permission is None:
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to access these slides",
        )

    if PERMISSION_PRIORITY[permission] < PERMISSION_PRIORITY[min_permission]:
        raise HTTPException(
            status_code=403,
            detail=f"This action requires {min_permission.value} permission",
        )

    return permission


def _check_deck_permission_for_session(
    session_id: str,
    min_permission: PermissionLevel = PermissionLevel.CAN_VIEW,
) -> None:
    """Look up a session by string ID, resolve root, and enforce deck permission.

    (Moved from sessions.py.)

    This is the standard pattern for endpoints that only have a session_id string
    and need to gate on deck permissions.  It opens its own DB session via
    ``get_db_session`` so it can be called from endpoints that do not already
    have one.

    Args:
        session_id: The string session_id passed to the endpoint.
        min_permission: Minimum required permission level.

    Raises:
        HTTPException 404: If the session does not exist (stale tab, deleted session, wrong ID).
        HTTPException 403: If the caller lacks the required permission.
    """
    session_manager = get_session_manager()
    try:
        session_info = session_manager.get_session(session_id)
    except SessionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Session not found: {session_id}",
        ) from None
    with get_db_session() as db:
        _require_session_access(session_info, db, min_permission)


# ---------------------------------------------------------------------------
# Job-ID access (export poll/download, Google Slides poll)
# ---------------------------------------------------------------------------


def _require_export_job_access(
    job_id: str,
    min_permission: PermissionLevel = PermissionLevel.CAN_VIEW,
) -> None:
    """Resolve an export job's session and enforce deck permission on it.

    Every ExportJob row is session-bound (both enqueue sites require a
    session_id), so possession of a job_id must not grant access to another
    user's export — the caller needs ``min_permission`` on the job's deck.

    Raises:
        HTTPException 404: unknown job_id.
        HTTPException 404/403: from the deck-permission check.
    """
    from src.database.models.session import ExportJob

    with get_db_session() as db:
        job = db.query(ExportJob).filter(ExportJob.job_id == job_id).first()
        session_id = job.session_id if job is not None else None
    if session_id is None:
        raise HTTPException(status_code=404, detail="Export job not found")
    _check_deck_permission_for_session(session_id, min_permission)


# ---------------------------------------------------------------------------
# HIGH-2: admin primitive — caller holds CAN_MANAGE in the App's ACL
# ---------------------------------------------------------------------------
#
# SECURITY NOTE (why this is NOT a "can you read the ACL?" test): an earlier
# design decided admin by whether the caller's OBO client could read the app
# ACL, on the premise "reading an ACL requires CAN_MANAGE." That premise is
# FALSE — ``apps.get_permissions`` only needs the ``iam.access-control:read``
# scope, which is present on every user's OBO token, so a faithful
# readability probe classifies EVERY authenticated user as admin (fail-OPEN).
# The correct control is an authorization DECISION: does the caller's own
# identity (directly, or via a group they belong to) appear in the app ACL
# with a CAN_MANAGE grant? That is a presence-in-grant check and cannot fail
# open to "everyone is admin."

_ADMIN_CACHE: dict = {}
_ADMIN_CACHE_TTL_SECONDS = 60.0

# App ACL entries carry Databricks IAM permission levels as *strings* like
# "CAN_MANAGE" (databricks.sdk.service.iam.PermissionLevel); do NOT confuse
# with the deck-permission ``PermissionLevel`` imported at module top.
_APP_CAN_MANAGE = "CAN_MANAGE"


def _is_production() -> bool:
    return os.getenv("ENVIRONMENT", "development") == "production"


def _caller_group_display_names(client, user_name: str) -> set:
    """Resolve the caller's group *display names* via workspace SCIM.

    The app ACL identifies groups by ``group_name`` (display name, e.g.
    "admins"), so membership matching must be on display names — not the
    group IDs that ``permission_context``/``get_user_groups`` return, and not
    the request-time permission context (which is built with
    ``fetch_groups=False`` in production). We therefore look the caller up
    directly through the system client's SCIM ``users`` API and read the
    ``display`` of each group they belong to.
    """
    users = list(
        client.users.list(filter=f'userName eq "{user_name}"', attributes="groups")
    )
    names: set = set()
    for u in users:
        for g in (u.groups or []):
            if g.display:
                names.add(g.display)
    return names


def _admin_acl_probe(user_name: str) -> bool:
    """Return True iff ``user_name`` holds CAN_MANAGE in the app's ACL.

    Admin is a real authorization decision (presence-in-grant), not an ACL
    readability oracle: the caller is admin iff their ``user_name`` appears
    as a direct CAN_MANAGE grant in the app ACL, OR any group they belong to
    appears as a CAN_MANAGE ``group_name`` grant (inherited grants — e.g. the
    workspace ``admins`` group — count). Both the ACL read and the caller's
    group resolution use the SP/system client, which is unambiguously
    permitted to read them and, crucially, does not depend on the caller's
    OBO scopes (so it cannot be tricked into a fail-open verdict).

    Returns False for a caller absent from every CAN_MANAGE grant (even
    though such a caller can still *read* the ACL). Missing app name -> False.
    Raises on genuine infra/API errors so ``require_admin`` can fail closed
    without caching a transient blip.
    """
    app_name = os.environ.get("DATABRICKS_APP_NAME")
    if not app_name:
        logger.warning("require_admin: DATABRICKS_APP_NAME unset; failing closed")
        return False
    from src.core.databricks_client import get_system_client

    client = get_system_client()
    acl = client.apps.get_permissions(app_name)

    caller_groups = _caller_group_display_names(client, user_name)

    for entry in (acl.access_control_list or []):
        grants_manage = any(
            getattr(p.permission_level, "value", p.permission_level) == _APP_CAN_MANAGE
            for p in (entry.all_permissions or [])
        )
        if not grants_manage:
            continue
        if entry.user_name and entry.user_name == user_name:
            return True
        if entry.group_name and entry.group_name in caller_groups:
            return True
    return False


def require_admin() -> None:
    """FastAPI dependency: caller must hold CAN_MANAGE in the app's ACL.

    - Local dev/test: bypass (dev auth is DEV_USER_ID with no token or ACL
      behind it) — same pattern as the dev-only CORS gate in main.py.
    - Admin verdict = ``_admin_acl_probe`` (a presence-in-grant check against
      the app ACL, direct or via group membership). See the SECURITY NOTE
      above for why this is a membership decision, not an ACL-readability
      test.
    - Verdicts cached per-username with a short TTL. The cache is in-memory
      and therefore per-worker — deliberately fine here: a cache miss on
      another worker just re-runs the lookup; correctness never depends on
      which worker got the request.
    - Only *definitive* verdicts are cached (the probe's True/False result).
      Transient probe errors fail closed for the current request but are NOT
      cached — otherwise one network blip would lock a real admin out for the
      full TTL.
    - Fail closed (403) on non-admin, missing user, or lookup error.
    """
    if not _is_production():
        return
    user = get_current_user()
    if not user:
        raise HTTPException(status_code=403, detail="Admin access required")

    now = time.monotonic()
    cached = _ADMIN_CACHE.get(user)
    if cached is not None and now - cached[1] < _ADMIN_CACHE_TTL_SECONDS:
        verdict = cached[0]
    else:
        try:
            verdict = _admin_acl_probe(user)
            # Definitive membership verdict (True or False). Cacheable.
            _ADMIN_CACHE[user] = (verdict, now)
        except Exception:
            logger.warning(
                "require_admin: ACL membership check failed for %s; failing "
                "closed (uncached)",
                user,
                exc_info=True,
            )
            # Fail closed on THIS request only — do not cache error-derived
            # denials (a transient blip must not deny an admin for the TTL).
            verdict = False

    if not verdict:
        raise HTTPException(status_code=403, detail="Admin access required")


def reset_admin_cache() -> None:
    """Clear the admin-verdict cache (tests)."""
    _ADMIN_CACHE.clear()
