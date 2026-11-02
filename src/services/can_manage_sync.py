"""Sync the Databricks App's direct CAN_MANAGE holders into the permissions table.

The app service principal reads the app's permission list; direct CAN_MANAGE
users and groups become synced admin rows. A failed or untrusted (empty) read
never deletes rows.
"""
import asyncio
import logging
import os
from datetime import datetime

from databricks.sdk.service.apps import AppPermissionLevel, AppPermissions

from src.core.database import get_db_session
from src.core.databricks_client import get_system_client
from src.services.admin_permissions import (
    AclHolder,
    EmptyHolderSetError,
    get_sync_status,
    normalize_identity_name,
    reconcile_can_manage,
    record_sync_result,
)

logger = logging.getLogger(__name__)

RETRY_INTERVAL_SECONDS = 30
SYNC_INTERVAL_SECONDS = 300


def holders_from_acl(acl: AppPermissions) -> list[AclHolder]:
    holders: list[AclHolder] = []
    seen: set[tuple[str, str]] = set()
    for entry in acl.access_control_list or []:
        if entry.service_principal_name:
            continue
        if entry.user_name is not None:
            identity_type, name = "USER", entry.user_name
        elif entry.group_name is not None:
            identity_type, name = "GROUP", entry.group_name
        else:
            continue
        if not name or not name.strip():
            continue
        direct_manage = any(
            p.permission_level == AppPermissionLevel.CAN_MANAGE
            and not p.inherited
            and not p.inherited_from_object
            for p in (entry.all_permissions or [])
        )
        if not direct_manage:
            continue
        key = (identity_type, normalize_identity_name(name))
        if key in seen:
            continue
        seen.add(key)
        holders.append(AclHolder(identity_type, name))
    return holders


def _record_failure(now: datetime | None, message: str) -> None:
    try:
        with get_db_session() as db:
            record_sync_result(db, now=now or datetime.utcnow(), error=message)
    except Exception:
        logger.warning("Could not record CAN_MANAGE sync failure", exc_info=True)


def _never_succeeded() -> bool:
    try:
        with get_db_session() as db:
            return get_sync_status(db).last_success_at is None
    except Exception:
        return False


def sync_once(now: datetime | None = None) -> bool:
    """Run one sync. True only when the reconcile committed."""
    now = now or datetime.utcnow()
    try:
        app_name = os.getenv("DATABRICKS_APP_NAME")
        if not app_name:
            raise _ConfigError("DATABRICKS_APP_NAME is not set")
        client = get_system_client()
        acl = client.apps.get_permissions(app_name=app_name)
        holders = holders_from_acl(acl)
        with get_db_session() as db:
            added, removed = reconcile_can_manage(db, holders)
            record_sync_result(db, now=now, error=None)
        logger.info(
            "CAN_MANAGE sync ok: %d holders, %d added, %d removed",
            len(holders),
            added,
            removed,
        )
        return True
    except Exception as exc:
        if isinstance(exc, (EmptyHolderSetError, _ConfigError)):
            message = str(exc)
        else:
            message = f"{type(exc).__name__}: {exc}"
        _record_failure(now, message)
        hint = ""
        if _never_succeeded():
            hint = (
                " No CAN_MANAGE sync has ever succeeded; only admins added in "
                "Tellr exist. Run tellr.update so the app's service principal "
                "holds CAN_MANAGE on the app."
            )
        logger.warning("CAN_MANAGE sync failed: %s.%s", message, hint)
        return False


class _ConfigError(Exception):
    pass


async def can_manage_sync_loop() -> None:
    succeeded = False
    while True:
        try:
            ok = await asyncio.to_thread(sync_once)
            succeeded = succeeded or bool(ok)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("CAN_MANAGE sync tick failed", exc_info=True)
        await asyncio.sleep(
            SYNC_INTERVAL_SECONDS if succeeded else RETRY_INTERVAL_SECONDS
        )
