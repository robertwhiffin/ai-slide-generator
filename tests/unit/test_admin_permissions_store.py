"""Unit tests for the app-admin ``permissions`` tables and their store service.

Task 1 of docs/superpowers/plans/2026-11-02-admin-permissions.md. The service
never commits; these tests commit where a caller would, and every assertion on
stored state reads the rows back with a fresh column-level query (column
queries return values from the database, not from the session's identity map,
and with ``autoflush=False`` they do not see anything the code left unflushed).
"""

from dataclasses import FrozenInstanceError, fields
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import DateTime, String, Text, create_engine, event, inspect, insert
from sqlalchemy.orm import sessionmaker

from src.core.database import Base
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
from src.services import admin_permissions
from src.services.admin_permissions import (
    AclHolder,
    AdminEntry,
    EmptyHolderSetError,
    NotManualPermissionError,
    SyncStatus,
    add_manual_admin,
    get_sync_status,
    is_app_admin,
    list_admins,
    normalize_identity_name,
    reconcile_can_manage,
    record_sync_result,
    remove_manual_admin,
)

EMPTY_HOLDERS_MESSAGE = (
    "the app's permissions list no direct CAN_MANAGE users or groups"
)

T1 = datetime(2026, 11, 2, 9, 0, 0)
T2 = datetime(2026, 11, 2, 9, 5, 0)
T3 = datetime(2026, 11, 2, 9, 10, 0)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    import src.database.models  # noqa: F401 - register all models

    Base.metadata.create_all(bind=engine)
    # autoflush=False matches production (src/core/database.py get_session_local);
    # with autoflush on, a store function that forgot to flush would still pass.
    factory = sessionmaker(bind=engine, autoflush=False)
    session = factory()
    yield session
    session.close()
    engine.dispose()


# ---------------------------------------------------------------------------
# Helpers: seed rows directly (independent of the code under test) and read
# them back with column-level queries.
# ---------------------------------------------------------------------------

_PERMISSION_COLUMNS = (
    "id",
    "resource_type",
    "resource_id",
    "identity_type",
    "identity_id",
    "identity_name",
    "identity_key",
    "privilege",
    "source",
    "created_by",
    "created_at",
    "updated_at",
)

_SYNC_STATE_COLUMNS = ("sync_key", "last_attempt_at", "last_success_at", "last_error")


def _add_row(
    db,
    *,
    identity_type,
    identity_name,
    source,
    resource_type=RESOURCE_APP,
    resource_id=APP_WIDE_RESOURCE_ID,
    privilege=PRIVILEGE_ADMIN,
    identity_id=None,
    created_by=None,
    created_at=None,
) -> int:
    """Insert one Permission row and flush it. Returns its id."""
    row = Permission(
        resource_type=resource_type,
        resource_id=resource_id,
        identity_type=identity_type,
        identity_id=identity_id,
        identity_name=identity_name,
        identity_key=identity_name.strip().lower(),
        privilege=privilege,
        source=source,
        created_by=created_by,
    )
    if created_at is not None:
        row.created_at = created_at
        row.updated_at = created_at
    db.add(row)
    db.flush()
    return row.id


def _sync_row(db, identity_type, identity_name, **kwargs) -> int:
    kwargs.setdefault("created_by", SYNC_CREATED_BY)
    return _add_row(
        db,
        identity_type=identity_type,
        identity_name=identity_name,
        source=SOURCE_CAN_MANAGE_SYNC,
        **kwargs,
    )


def _manual_row(db, identity_type, identity_name, **kwargs) -> int:
    return _add_row(
        db,
        identity_type=identity_type,
        identity_name=identity_name,
        source=SOURCE_MANUAL,
        **kwargs,
    )


def _read_rows(db, *criteria) -> list[dict]:
    """Fresh column-level read of permission rows, ordered by id."""
    columns = [getattr(Permission, name) for name in _PERMISSION_COLUMNS]
    query = db.query(*columns)
    for criterion in criteria:
        query = query.filter(criterion)
    return [dict(zip(_PERMISSION_COLUMNS, r)) for r in query.order_by(Permission.id)]


def _app_admin_criteria():
    return (
        Permission.resource_type == "app",
        Permission.resource_id == "",
        Permission.privilege == "admin",
    )


def _sync_keys(db) -> set[tuple[str, str]]:
    rows = _read_rows(db, *_app_admin_criteria(), Permission.source == "can_manage_sync")
    return {(r["identity_type"], r["identity_key"]) for r in rows}


def _read_sync_state_rows(db) -> list[dict]:
    columns = [getattr(PermissionSyncState, name) for name in _SYNC_STATE_COLUMNS]
    return [dict(zip(_SYNC_STATE_COLUMNS, r)) for r in db.query(*columns).all()]


# ---------------------------------------------------------------------------
# Tables, schema and interface values
# ---------------------------------------------------------------------------


def test_tables_are_registered():
    import src.database.models as models_pkg

    assert {"permissions", "permission_sync_state"} <= set(Base.metadata.tables)
    # init_database's create_all only sees models that `import src.database.models`
    # loads, so the package itself must import and export both models.
    assert models_pkg.Permission is Permission
    assert models_pkg.PermissionSyncState is PermissionSyncState
    assert {"Permission", "PermissionSyncState"} <= set(models_pkg.__all__)


def test_permissions_schema_matches_the_brief(db_session):
    db = db_session
    insp = inspect(db.get_bind())

    expected_permissions = {
        # name: (type class, length, nullable)
        "id": (None, None, None),
        "resource_type": (String, 32, False),
        "resource_id": (String, 255, False),
        "identity_type": (String, 10, False),
        "identity_id": (String, 255, True),
        "identity_name": (String, 255, False),
        "identity_key": (String, 255, False),
        "privilege": (String, 32, False),
        "source": (String, 32, False),
        "created_by": (String, 255, True),
        "created_at": (DateTime, None, False),
        "updated_at": (DateTime, None, False),
    }
    columns = {c["name"]: c for c in insp.get_columns("permissions")}
    assert set(columns) == set(expected_permissions)
    for name, (type_cls, length, nullable) in expected_permissions.items():
        if type_cls is None:
            continue
        assert isinstance(columns[name]["type"], type_cls), name
        if length is not None:
            assert columns[name]["type"].length == length, name
        assert columns[name]["nullable"] is nullable, name
    assert insp.get_pk_constraint("permissions")["constrained_columns"] == ["id"]

    uniques = {u["name"]: u["column_names"] for u in insp.get_unique_constraints("permissions")}
    assert uniques.get("uq_permissions_grant") == [
        "resource_type",
        "resource_id",
        "identity_type",
        "identity_key",
        "privilege",
        "source",
    ]
    indexes = {i["name"]: i for i in insp.get_indexes("permissions")}
    assert "ix_permissions_lookup" in indexes
    assert indexes["ix_permissions_lookup"]["column_names"] == [
        "resource_type",
        "resource_id",
        "privilege",
    ]
    assert not indexes["ix_permissions_lookup"]["unique"]

    expected_state = {
        "sync_key": (String, 64, False),
        "last_attempt_at": (DateTime, None, True),
        "last_success_at": (DateTime, None, True),
        "last_error": (Text, None, True),
    }
    state_columns = {c["name"]: c for c in insp.get_columns("permission_sync_state")}
    assert set(state_columns) == set(expected_state)
    for name, (type_cls, length, nullable) in expected_state.items():
        assert isinstance(state_columns[name]["type"], type_cls), name
        if length is not None:
            assert state_columns[name]["type"].length == length, name
        if name != "sync_key":
            assert state_columns[name]["nullable"] is nullable, name
    assert insp.get_pk_constraint("permission_sync_state")["constrained_columns"] == [
        "sync_key"
    ]

    # resource_id defaults to "" (app-wide, never NULL) and the audit
    # timestamps fill themselves in.
    db.add(
        Permission(
            resource_type="app",
            identity_type="USER",
            identity_name="d@x.com",
            identity_key="d@x.com",
            privilege="admin",
            source="manual",
        )
    )
    db.flush()
    (row,) = _read_rows(db)
    assert row["resource_id"] == ""
    assert row["created_at"] is not None
    assert row["updated_at"] is not None


def test_interface_values_are_pinned():
    assert RESOURCE_APP == "app"
    assert APP_WIDE_RESOURCE_ID == ""
    assert PRIVILEGE_ADMIN == "admin"
    assert SOURCE_CAN_MANAGE_SYNC == "can_manage_sync"
    assert SOURCE_MANUAL == "manual"
    assert SYNC_KEY_APP_CAN_MANAGE == "app_can_manage"
    assert SYNC_CREATED_BY == "can_manage_sync"

    assert normalize_identity_name("  Robert.Whiffin@Databricks.COM \n") == (
        "robert.whiffin@databricks.com"
    )
    assert normalize_identity_name("Tellr Maintainers") == "tellr maintainers"

    assert issubclass(EmptyHolderSetError, ValueError)
    assert issubclass(NotManualPermissionError, ValueError)

    holder = AclHolder(identity_type="USER", identity_name="a@x.com")
    assert len({holder, AclHolder(identity_type="USER", identity_name="a@x.com")}) == 1
    with pytest.raises(FrozenInstanceError):
        holder.identity_name = "b@x.com"  # type: ignore[misc]

    assert [f.name for f in fields(AdminEntry)] == [
        "identity_type",
        "identity_name",
        "identity_id",
        "sources",
        "manual_permission_id",
        "added_by",
        "added_at",
    ]
    assert [f.name for f in fields(SyncStatus)] == [
        "last_attempt_at",
        "last_success_at",
        "last_error",
    ]


# ---------------------------------------------------------------------------
# is_app_admin
# ---------------------------------------------------------------------------


def test_user_row_match_is_case_insensitive_and_skips_group_lookup(db_session):
    db = db_session
    _manual_row(db, "USER", "Robert.Whiffin@Databricks.com")
    # A GROUP row exists, so skipping the group lookup is down to the USER
    # match, not to "there are no group rows".
    _manual_row(db, "GROUP", "Tellr Maintainers")
    db.commit()

    groups = MagicMock(return_value=[])
    assert is_app_admin(db, "robert.whiffin@databricks.com", groups) is True
    assert is_app_admin(db, " ROBERT.WHIFFIN@databricks.com ", groups) is True
    groups.assert_not_called()

    # Someone without a USER row is not an admin (their groups match nothing).
    assert is_app_admin(db, "someone.else@databricks.com", groups) is False


def test_workspace_admins_group_member_without_a_row_is_not_admin(db_session):
    db = db_session

    assert is_app_admin(db, "wsadmin@x.com", lambda: ["admins", "users"]) is False

    # Only a row decides: a direct GROUP grant to `admins` is honoured (spec),
    # so the same caller with the same groups becomes an admin.
    _manual_row(db, "GROUP", "admins")
    db.commit()
    assert is_app_admin(db, "wsadmin@x.com", lambda: ["admins", "users"]) is True


def test_group_row_matches_callers_group_case_insensitively(db_session):
    db = db_session
    _manual_row(db, "GROUP", "Tellr Maintainers")
    db.commit()

    assert is_app_admin(db, "member@x.com", lambda: ["tellr maintainers"]) is True
    # The caller's group names are normalized too, not only the stored key.
    assert is_app_admin(db, "member@x.com", lambda: ["users", " TELLR Maintainers "]) is True
    assert is_app_admin(db, "outsider@x.com", lambda: ["users", "tellr"]) is False


def test_group_lookup_skipped_when_no_group_rows(db_session):
    db = db_session
    _manual_row(db, "USER", "other@x.com")
    db.commit()

    groups = MagicMock(return_value=["tellr maintainers", "admins"])
    assert is_app_admin(db, "robert@x.com", groups) is False
    assert is_app_admin(db, "other@x.com", groups) is True
    groups.assert_not_called()


def test_group_lookup_error_propagates(db_session):
    db = db_session
    _manual_row(db, "GROUP", "Tellr Maintainers")
    _manual_row(db, "USER", "sam@x.com")
    db.commit()

    def failing_groups():
        raise RuntimeError("scim unavailable")

    with pytest.raises(RuntimeError, match="scim unavailable"):
        is_app_admin(db, "robert@x.com", failing_groups)
    # The lookup is only consulted when needed: a USER match never reaches it.
    assert is_app_admin(db, "sam@x.com", failing_groups) is True


def test_rows_for_other_privilege_or_resource_do_not_grant_admin(db_session):
    db = db_session
    caller = "robert@x.com"
    _manual_row(db, "USER", caller, privilege="edit")
    _manual_row(db, "USER", caller, resource_type="deck_spec")
    _manual_row(db, "USER", caller, resource_id="deck-42")
    _manual_row(db, "GROUP", "Tellr Maintainers", privilege="edit")
    _manual_row(db, "GROUP", "Tellr Maintainers", resource_type="deck_spec")
    _manual_row(db, "GROUP", "Tellr Maintainers", resource_id="deck-42")
    db.commit()

    assert is_app_admin(db, caller, lambda: ["Tellr Maintainers"]) is False

    # The same caller and groups do match an app-wide admin row.
    _manual_row(db, "GROUP", "Tellr Maintainers")
    db.commit()
    assert is_app_admin(db, caller, lambda: ["Tellr Maintainers"]) is True


# ---------------------------------------------------------------------------
# reconcile_can_manage
# ---------------------------------------------------------------------------


def test_reconcile_inserts_and_deletes_only_sync_rows(db_session):
    db = db_session
    a_sync_id = _sync_row(db, "USER", "a@x.com")
    _sync_row(db, "USER", "b@x.com")
    b_manual_id = _manual_row(
        db, "USER", "b@x.com", identity_id="u-b", created_by="priya", created_at=T1
    )
    db.commit()
    (b_manual_before,) = _read_rows(db, Permission.id == b_manual_id)

    result = reconcile_can_manage(
        db,
        [
            AclHolder(identity_type="USER", identity_name="a@x.com"),
            AclHolder(identity_type="GROUP", identity_name="Team"),
        ],
    )

    assert result == (1, 1)
    assert _sync_keys(db) == {("USER", "a@x.com"), ("GROUP", "team")}

    rows = _read_rows(db)
    assert len(rows) == 3
    # The surviving sync row was kept, not deleted and re-inserted.
    assert [r["id"] for r in rows if r["identity_key"] == "a@x.com"] == [a_sync_id]

    (team,) = [r for r in rows if r["identity_type"] == "GROUP"]
    assert team["resource_type"] == "app"
    assert team["resource_id"] == ""
    assert team["identity_name"] == "Team"
    assert team["identity_key"] == "team"
    assert team["privilege"] == "admin"
    assert team["source"] == "can_manage_sync"
    assert team["created_by"] == SYNC_CREATED_BY
    assert not team["identity_id"]  # the permission list carries names, not ids
    assert team["created_at"] is not None

    # The manual b@x.com row is untouched.
    assert _read_rows(db, Permission.id == b_manual_id) == [b_manual_before]


def test_reconcile_ignores_rows_outside_app_admin(db_session):
    db = db_session
    # Sync-sourced rows for other resources/privileges are not app-admin rows:
    # they neither count as "already present" nor get deleted.
    off_ids = [
        _sync_row(db, "USER", "c@x.com", resource_type="deck_spec"),
        _sync_row(db, "USER", "c@x.com", privilege="edit"),
        _sync_row(db, "USER", "c@x.com", resource_id="deck-42"),
        _sync_row(db, "USER", "d@x.com", resource_type="deck_spec"),
    ]
    db.commit()
    off_before = _read_rows(db, Permission.id.in_(off_ids))

    result = reconcile_can_manage(db, [AclHolder(identity_type="USER", identity_name="c@x.com")])

    assert result == (1, 0)
    assert _sync_keys(db) == {("USER", "c@x.com")}
    assert _read_rows(db, Permission.id.in_(off_ids)) == off_before
    assert len(_read_rows(db)) == 5


def test_reconcile_dedupes_case_variants(db_session):
    db = db_session
    holders = [
        AclHolder(identity_type="USER", identity_name="A@x.com"),
        AclHolder(identity_type="USER", identity_name="a@x.com"),
    ]

    assert reconcile_can_manage(db, holders) == (1, 0)

    rows = _read_rows(db)
    assert len(rows) == 1
    assert rows[0]["identity_type"] == "USER"
    assert rows[0]["identity_key"] == "a@x.com"
    assert rows[0]["identity_name"].lower() == "a@x.com"
    assert rows[0]["source"] == "can_manage_sync"

    db.commit()
    assert reconcile_can_manage(db, holders) == (0, 0)
    assert _read_rows(db) == rows


def test_reconcile_is_idempotent(db_session):
    db = db_session
    holders = [
        AclHolder(identity_type="USER", identity_name="Robert.Whiffin@Databricks.com"),
        AclHolder(identity_type="GROUP", identity_name="Tellr Maintainers"),
    ]

    assert reconcile_can_manage(db, holders) == (2, 0)
    db.commit()
    rows_after_first = _read_rows(db)
    assert len(rows_after_first) == 2

    assert reconcile_can_manage(db, holders) == (0, 0)
    db.commit()
    assert _read_rows(db) == rows_after_first

    # The list spelling the email differently is still the same admin: no new
    # row, nothing deleted.
    case_variants = [
        AclHolder(identity_type="USER", identity_name="robert.whiffin@databricks.com"),
        AclHolder(identity_type="GROUP", identity_name="TELLR MAINTAINERS"),
    ]
    assert reconcile_can_manage(db, case_variants) == (0, 0)
    db.commit()
    assert _read_rows(db) == rows_after_first


def test_reconcile_refuses_empty_holder_set(db_session):
    db = db_session
    _sync_row(db, "USER", "a@x.com")
    _sync_row(db, "GROUP", "Team")
    db.commit()
    before = _read_rows(db)
    assert len(before) == 2

    with pytest.raises(EmptyHolderSetError) as exc_info:
        reconcile_can_manage(db, [])

    assert str(exc_info.value) == EMPTY_HOLDERS_MESSAGE
    # Commit anything the call might have left pending: nothing may change.
    db.commit()
    assert _read_rows(db) == before


def test_reconcile_swallows_a_concurrent_duplicate_insert(db_session, monkeypatch):
    db = db_session
    a_id = _sync_row(db, "USER", "a@x.com")
    db.commit()
    # Uncommitted work already in the caller's transaction must survive the
    # lost race (a savepoint, not a full rollback).
    canary_id = _manual_row(db, "USER", "canary@x.com")

    calls = []

    def stale_existing_keys(session):
        calls.append(session)
        return set()

    # Another worker inserted a@x.com between this worker's read and its insert.
    monkeypatch.setattr(admin_permissions, "_existing_sync_keys", stale_existing_keys)

    reconcile_can_manage(db, [AclHolder(identity_type="USER", identity_name="a@x.com")])

    assert calls, "reconcile must read existing keys through _existing_sync_keys"
    a_rows = _read_rows(
        db,
        *_app_admin_criteria(),
        Permission.source == "can_manage_sync",
        Permission.identity_type == "USER",
        Permission.identity_key == "a@x.com",
    )
    assert [r["id"] for r in a_rows] == [a_id]
    # The session is still usable, and the caller's earlier work is intact.
    assert db.query(Permission).count() == 2
    db.commit()
    assert {r["id"] for r in _read_rows(db)} == {a_id, canary_id}


# ---------------------------------------------------------------------------
# add_manual_admin / remove_manual_admin
# ---------------------------------------------------------------------------


def test_add_manual_admin_is_idempotent_and_normalizes(db_session):
    db = db_session

    first = add_manual_admin(
        db,
        identity_type="USER",
        identity_name="Priya@Example.com",
        identity_id="u-priya",
        created_by="robert@x.com",
    )
    assert isinstance(first, Permission)
    first_id = first.id
    assert first_id is not None  # flushed before returning

    second = add_manual_admin(
        db,
        identity_type="USER",
        identity_name="Priya@Example.com",
        identity_id="u-priya",
        created_by="robert@x.com",
    )
    assert second.id == first_id
    third = add_manual_admin(
        db,
        identity_type="USER",
        identity_name=" PRIYA@example.com ",
        identity_id="u-priya",
        created_by="someone-else@x.com",
    )
    assert third.id == first_id

    # Read without committing: the row must already be in the database.
    rows = _read_rows(db)
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == first_id
    assert row["resource_type"] == "app"
    assert row["resource_id"] == ""
    assert row["identity_type"] == "USER"
    assert row["identity_id"] == "u-priya"
    assert row["identity_name"] == "Priya@Example.com"
    assert row["identity_key"] == "priya@example.com"
    assert row["privilege"] == "admin"
    assert row["source"] == "manual"
    assert row["created_by"] == "robert@x.com"  # the existing row is returned as is
    assert row["created_at"] is not None
    assert row["updated_at"] is not None

    db.commit()
    assert _read_rows(db) == rows


def test_add_manual_admin_alongside_a_sync_row_creates_a_manual_row(db_session):
    db = db_session
    sync_id = _sync_row(db, "USER", "sam@x.com")
    db.commit()

    manual = add_manual_admin(
        db,
        identity_type="USER",
        identity_name="Sam@x.com",
        identity_id="u-sam",
        created_by="priya",
    )

    assert manual.id != sync_id
    rows = _read_rows(db)
    assert sorted((r["id"], r["source"]) for r in rows) == sorted(
        [(sync_id, "can_manage_sync"), (manual.id, "manual")]
    )
    (manual_row,) = [r for r in rows if r["source"] == "manual"]
    assert manual_row["identity_key"] == "sam@x.com"
    assert manual_row["created_by"] == "priya"


def test_add_manual_admin_rejects_blank_name_and_bad_type(db_session):
    db = db_session

    with pytest.raises(ValueError):
        add_manual_admin(
            db, identity_type="USER", identity_name="  ", identity_id=None, created_by="r"
        )
    with pytest.raises(ValueError):
        add_manual_admin(
            db,
            identity_type="SP",
            identity_name="sp-app@x.com",
            identity_id=None,
            created_by="r",
        )

    # A valid GROUP add still works, and the rejected calls wrote nothing.
    add_manual_admin(
        db,
        identity_type="GROUP",
        identity_name="Tellr Maintainers",
        identity_id="g-1",
        created_by="r",
    )
    db.commit()
    rows = _read_rows(db)
    assert [(r["identity_type"], r["identity_key"], r["source"]) for r in rows] == [
        ("GROUP", "tellr maintainers", "manual")
    ]


def test_remove_manual_admin_refuses_sync_rows(db_session):
    db = db_session
    sync_id = _sync_row(db, "USER", "sam@x.com")
    db.commit()
    before = _read_rows(db)

    with pytest.raises(NotManualPermissionError):
        remove_manual_admin(db, sync_id)
    with pytest.raises(LookupError):
        remove_manual_admin(db, sync_id + 1000)

    db.commit()
    assert _read_rows(db) == before


def test_remove_manual_admin_ignores_rows_outside_app_admin(db_session):
    db = db_session
    off_ids = [
        _manual_row(db, "USER", "sam@x.com", resource_type="deck_spec"),
        _manual_row(db, "USER", "sam@x.com", privilege="edit"),
        _manual_row(db, "USER", "sam@x.com", resource_id="deck-42"),
    ]
    app_admin_id = _manual_row(db, "USER", "sam@x.com")
    db.commit()
    off_before = _read_rows(db, Permission.id.in_(off_ids))

    for off_id in off_ids:
        with pytest.raises(LookupError):
            remove_manual_admin(db, off_id)

    # The app-admin manual row is removable through the same call.
    remove_manual_admin(db, app_admin_id)
    db.commit()
    assert _read_rows(db, Permission.id.in_(off_ids)) == off_before
    assert _read_rows(db, Permission.id == app_admin_id) == []


def test_remove_manual_keeps_admin_through_sync_row(db_session):
    db = db_session
    sync_id = _sync_row(db, "USER", "sam@x.com")
    manual_id = _manual_row(db, "USER", "Sam@x.com", created_by="priya")
    db.commit()

    remove_manual_admin(db, manual_id)
    db.commit()

    assert [(r["id"], r["source"]) for r in _read_rows(db)] == [(sync_id, "can_manage_sync")]
    assert is_app_admin(db, "sam@x.com", lambda: []) is True
    (entry,) = list_admins(db)
    assert entry.sources == ["can_manage_sync"]
    assert entry.manual_permission_id is None


# ---------------------------------------------------------------------------
# list_admins
# ---------------------------------------------------------------------------


def test_list_admins_merges_sources_per_identity(db_session):
    db = db_session
    # Inserted so that neither the sources nor the entries come out sorted by
    # accident: the manual row precedes the sync row, and USER precedes GROUP.
    sam_manual_id = _manual_row(
        db, "USER", "SAM@x.com", identity_id="u-sam", created_by="priya", created_at=T1
    )
    _sync_row(db, "USER", "sam@x.com", created_at=T2)
    team_id = _manual_row(
        db, "GROUP", "Team", identity_id="g-team", created_by="robert", created_at=T3
    )
    db.commit()

    entries = list_admins(db)

    assert len(entries) == 2
    team, sam = entries  # sorted by (identity_type, identity_key): GROUP < USER
    assert team == AdminEntry(
        identity_type="GROUP",
        identity_name="Team",
        identity_id="g-team",
        sources=["manual"],
        manual_permission_id=team_id,
        added_by="robert",
        added_at=T3,
    )
    assert sam.identity_type == "USER"
    assert sam.identity_name.lower() == "sam@x.com"
    assert sam.identity_id == "u-sam"  # the SCIM id is known from the manual row
    assert sam.sources == ["can_manage_sync", "manual"]
    assert sam.manual_permission_id == sam_manual_id
    assert sam.added_by == "priya"
    assert sam.added_at == T1


def test_list_admins_sync_only_entries_and_ordering(db_session):
    db = db_session
    # Inserted out of order; "Bob" sorts before "amy" by name but after it by key.
    _sync_row(db, "USER", "Bob@x.com")
    _sync_row(db, "USER", "amy@x.com")
    _sync_row(db, "GROUP", "Tellr Maintainers")
    # Not an app-admin row, so it is not listed.
    _manual_row(db, "USER", "carl@x.com", resource_type="deck_spec")
    db.commit()

    entries = list_admins(db)

    assert [(e.identity_type, e.identity_name) for e in entries] == [
        ("GROUP", "Tellr Maintainers"),
        ("USER", "amy@x.com"),
        ("USER", "Bob@x.com"),
    ]
    for entry in entries:
        assert entry.sources == ["can_manage_sync"]
        # No manual row: the Admins tab shows a lock, not Remove.
        assert entry.manual_permission_id is None
        assert entry.identity_id is None


# ---------------------------------------------------------------------------
# Sync status
# ---------------------------------------------------------------------------


def test_record_sync_result_survives_concurrent_first_insert(db_session, monkeypatch):
    db = db_session
    # Another worker created the state row first (and recorded a failure).
    db.execute(
        insert(PermissionSyncState).values(
            sync_key=SYNC_KEY_APP_CAN_MANAGE,
            last_attempt_at=T1,
            last_success_at=None,
            last_error="an earlier failure",
        )
    )
    db.commit()
    # Uncommitted work already in the caller's transaction must survive.
    canary_id = _manual_row(db, "USER", "canary@x.com")

    real_get_sync_state = admin_permissions._get_sync_state
    calls = []

    def stale_first_read(session):
        calls.append(session)
        if len(calls) == 1:
            return None
        return real_get_sync_state(session)

    monkeypatch.setattr(admin_permissions, "_get_sync_state", stale_first_read)

    record_sync_result(db, now=T2, error=None)
    db.commit()

    assert calls, "record_sync_result must fetch the row through _get_sync_state"
    assert _read_sync_state_rows(db) == [
        {
            "sync_key": "app_can_manage",
            "last_attempt_at": T2,
            "last_success_at": T2,
            "last_error": None,
        }
    ]
    assert [r["id"] for r in _read_rows(db)] == [canary_id]


def test_sync_status_round_trip(db_session):
    db = db_session

    assert get_sync_status(db) == SyncStatus(
        last_attempt_at=None, last_success_at=None, last_error=None
    )

    record_sync_result(db, now=T1, error=None)
    db.commit()
    assert get_sync_status(db) == SyncStatus(
        last_attempt_at=T1, last_success_at=T1, last_error=None
    )

    record_sync_result(db, now=T2, error="boom")
    db.commit()
    assert get_sync_status(db) == SyncStatus(
        last_attempt_at=T2, last_success_at=T1, last_error="boom"
    )
    assert _read_sync_state_rows(db) == [
        {
            "sync_key": "app_can_manage",
            "last_attempt_at": T2,
            "last_success_at": T1,
            "last_error": "boom",
        }
    ]

    record_sync_result(db, now=T3, error=None)
    db.commit()
    status = get_sync_status(db)
    assert status.last_error is None
    assert status.last_success_at == T3
    assert status == SyncStatus(last_attempt_at=T3, last_success_at=T3, last_error=None)
    assert _read_sync_state_rows(db) == [
        {
            "sync_key": "app_can_manage",
            "last_attempt_at": T3,
            "last_success_at": T3,
            "last_error": None,
        }
    ]


def test_record_sync_result_truncates_long_errors(db_session):
    db = db_session
    record_sync_result(db, now=T1, error=None)
    db.commit()

    long_error = "PermissionDenied: " + "".join(f"{i % 10}" for i in range(1500))
    record_sync_result(db, now=T2, error=long_error)
    db.commit()

    (state,) = _read_sync_state_rows(db)
    assert state["last_error"] == long_error[:1000]
    assert state["last_attempt_at"] == T2
    assert state["last_success_at"] == T1


# ---------------------------------------------------------------------------
# Transaction ownership
# ---------------------------------------------------------------------------


def test_store_functions_never_commit(db_session):
    db = db_session
    engine = db.get_bind()
    commits = []

    def on_commit(conn):
        commits.append(conn)

    event.listen(engine, "commit", on_commit)
    try:
        manual = add_manual_admin(
            db,
            identity_type="USER",
            identity_name="priya@example.com",
            identity_id="u-1",
            created_by="robert",
        )
        reconcile_can_manage(db, [AclHolder(identity_type="USER", identity_name="sam@x.com")])
        is_app_admin(db, "sam@x.com", lambda: [])
        list_admins(db)
        remove_manual_admin(db, manual.id)
        record_sync_result(db, now=T1, error=None)  # creates the state row
        record_sync_result(db, now=T2, error="boom")  # updates it
        get_sync_status(db)
        assert commits == []

        # The listener does see a real commit: the caller's.
        db.commit()
        assert len(commits) == 1
    finally:
        event.remove(engine, "commit", on_commit)
