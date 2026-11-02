"""Store service for app-admin permissions. No function here commits."""
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.database.models.permission import (
    APP_WIDE_RESOURCE_ID,
    PRIVILEGE_ADMIN,
    RESOURCE_APP,
    SOURCE_CAN_MANAGE_SYNC,
    SOURCE_MANUAL,
    SYNC_CREATED_BY,
    SYNC_KEY_APP_CAN_MANAGE,
    Permission,
    PermissionSyncState,
)

_VALID_IDENTITY_TYPES = ("USER", "GROUP")


def normalize_identity_name(name: str) -> str:
    return name.strip().lower()


@dataclass(frozen=True)
class AclHolder:
    identity_type: str
    identity_name: str


class EmptyHolderSetError(ValueError):
    pass


class NotManualPermissionError(ValueError):
    pass


@dataclass
class AdminEntry:
    identity_type: str
    identity_name: str
    identity_id: str | None
    sources: list[str]
    manual_permission_id: int | None
    added_by: str | None
    added_at: datetime | None


@dataclass
class SyncStatus:
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None


def _admin_rows(db: Session):
    return db.query(Permission).filter(
        Permission.resource_type == RESOURCE_APP,
        Permission.resource_id == APP_WIDE_RESOURCE_ID,
        Permission.privilege == PRIVILEGE_ADMIN,
    )


def is_app_admin(
    db: Session, user_name: str, get_group_names: Callable[[], Iterable[str]]
) -> bool:
    key = normalize_identity_name(user_name)
    if (
        _admin_rows(db)
        .filter(Permission.identity_type == "USER", Permission.identity_key == key)
        .first()
    ):
        return True
    group_keys = {
        k
        for (k,) in _admin_rows(db)
        .filter(Permission.identity_type == "GROUP")
        .with_entities(Permission.identity_key)
        .all()
    }
    if not group_keys:
        return False
    caller_groups = {normalize_identity_name(g) for g in get_group_names()}
    return bool(group_keys & caller_groups)


def _existing_sync_keys(db: Session) -> set[tuple[str, str]]:
    rows = (
        _admin_rows(db)
        .filter(Permission.source == SOURCE_CAN_MANAGE_SYNC)
        .with_entities(Permission.identity_type, Permission.identity_key)
        .all()
    )
    return {(t, k) for t, k in rows}


def reconcile_can_manage(db: Session, holders: Sequence[AclHolder]) -> tuple[int, int]:
    if not holders:
        raise EmptyHolderSetError(
            "the app's permissions list no direct CAN_MANAGE users or groups"
        )
    wanted: dict[tuple[str, str], str] = {}
    for h in holders:
        wanted.setdefault(
            (h.identity_type, normalize_identity_name(h.identity_name)), h.identity_name
        )

    existing = _existing_sync_keys(db)
    added = 0
    for key, name in wanted.items():
        if key in existing:
            continue
        try:
            with db.begin_nested():
                db.add(
                    Permission(
                        resource_type=RESOURCE_APP,
                        resource_id=APP_WIDE_RESOURCE_ID,
                        identity_type=key[0],
                        identity_name=name.strip(),
                        identity_key=key[1],
                        privilege=PRIVILEGE_ADMIN,
                        source=SOURCE_CAN_MANAGE_SYNC,
                        created_by=SYNC_CREATED_BY,
                    )
                )
                db.flush()
            added += 1
        except IntegrityError:
            continue

    removed = 0
    for row in _admin_rows(db).filter(Permission.source == SOURCE_CAN_MANAGE_SYNC).all():
        if (row.identity_type, row.identity_key) not in wanted:
            db.delete(row)
            removed += 1
    db.flush()
    return added, removed


def add_manual_admin(
    db: Session,
    *,
    identity_type: str,
    identity_name: str,
    identity_id: str | None,
    created_by: str | None,
) -> Permission:
    if identity_type not in _VALID_IDENTITY_TYPES:
        raise ValueError(f"identity_type must be one of {_VALID_IDENTITY_TYPES}")
    name = (identity_name or "").strip()
    if not name:
        raise ValueError("identity_name must not be blank")
    key = normalize_identity_name(name)
    existing = (
        _admin_rows(db)
        .filter(
            Permission.source == SOURCE_MANUAL,
            Permission.identity_type == identity_type,
            Permission.identity_key == key,
        )
        .first()
    )
    if existing:
        return existing
    row = Permission(
        resource_type=RESOURCE_APP,
        resource_id=APP_WIDE_RESOURCE_ID,
        identity_type=identity_type,
        identity_id=identity_id,
        identity_name=name,
        identity_key=key,
        privilege=PRIVILEGE_ADMIN,
        source=SOURCE_MANUAL,
        created_by=created_by,
    )
    db.add(row)
    db.flush()
    return row


def remove_manual_admin(db: Session, permission_id: int) -> None:
    row = _admin_rows(db).filter(Permission.id == permission_id).first()
    if row is None:
        raise LookupError(f"permission {permission_id} not found")
    if row.source != SOURCE_MANUAL:
        raise NotManualPermissionError(
            f"permission {permission_id} is not a manually added admin"
        )
    db.delete(row)
    db.flush()


def list_admins(db: Session) -> list[AdminEntry]:
    entries: dict[tuple[str, str], AdminEntry] = {}
    for row in _admin_rows(db).order_by(Permission.id).all():
        k = (row.identity_type, row.identity_key)
        entry = entries.get(k)
        if entry is None:
            entry = entries[k] = AdminEntry(
                identity_type=row.identity_type,
                identity_name=row.identity_name,
                identity_id=row.identity_id,
                sources=[],
                manual_permission_id=None,
                added_by=None,
                added_at=None,
            )
        entry.sources.append(row.source)
        if entry.identity_id is None and row.identity_id:
            entry.identity_id = row.identity_id
        if row.source == SOURCE_MANUAL:
            entry.manual_permission_id = row.id
            entry.added_by = row.created_by
            entry.added_at = row.created_at
            entry.identity_name = row.identity_name
    for entry in entries.values():
        entry.sources.sort()
    return [entries[k] for k in sorted(entries)]


def _get_sync_state(db: Session) -> PermissionSyncState | None:
    return db.get(PermissionSyncState, SYNC_KEY_APP_CAN_MANAGE)


def record_sync_result(db: Session, *, now: datetime, error: str | None) -> None:
    state = _get_sync_state(db)
    if state is None:
        try:
            with db.begin_nested():
                state = PermissionSyncState(sync_key=SYNC_KEY_APP_CAN_MANAGE)
                db.add(state)
                db.flush()
        except IntegrityError:
            state = db.get(PermissionSyncState, SYNC_KEY_APP_CAN_MANAGE)
    state.last_attempt_at = now
    if error is None:
        state.last_success_at = now
        state.last_error = None
    else:
        state.last_error = error[:1000]
    db.flush()


def get_sync_status(db: Session) -> SyncStatus:
    state = _get_sync_state(db)
    if state is None:
        return SyncStatus(None, None, None)
    return SyncStatus(state.last_attempt_at, state.last_success_at, state.last_error)
