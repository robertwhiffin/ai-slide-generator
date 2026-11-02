# App Admins from a Lakebase Permissions Table — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. In this repo also load `executing-plans-tellr`. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the workspace `admins` group check with a Lakebase `permissions` table. Admin = direct CAN_MANAGE on the Databricks App (synced by the app's service principal) or added on a new Admins tab.

**Architecture:**
- **Storage:** a new ORM table, `permissions`, holds grants. It is built by `create_all` in the existing pre-fork migration step. A one-row `permission_sync_state` table records the health of the sync.
- **Sync:** a lifespan background loop reads the app's permission list with the app service principal (SP) and reconciles the `can_manage_sync` rows.
- **Admin check:** `require_admin` keeps its shape; only its probe now reads the table.
- **Deploy:** the deploy package grants the app SP CAN_MANAGE on its own app, which the sync needs.
- **UI:** a new Admins tab lists, adds and removes admins.

**Tech Stack:** FastAPI, SQLAlchemy (SQLite in unit tests, Lakebase Postgres in prod), databricks-sdk 0.157 (`apps.get_permissions` / `apps.update_permissions`), React + TypeScript, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-02-admin-permissions-design.md`. Read it first. This plan settles everything the spec left to the builder.

## Global Constraints

- **Exact string values:**
  - resource type `app`; app-wide resource id `""` (empty string, never NULL);
  - privilege `admin`;
  - sources `can_manage_sync` and `manual`;
  - identity types `USER` and `GROUP` (reuse `IdentityType` from `src/database/models/profile_contributor.py`);
  - sync-state key `app_can_manage`.
- **Identity matching** is case-insensitive on `identity_name.strip().lower()`, stored in an `identity_key` column.
- **Sync timing:** the first run is immediate at startup; retry every **30 s** until the first success, then every **300 s**.
- **Sync filter:**
  - keep USER (`user_name`) and GROUP (`group_name`) entries that have at least one `all_permissions` item with `permission_level == AppPermissionLevel.CAN_MANAGE` and `inherited` falsy;
  - `AppPermissionLevel` is a plain `Enum`, so compare against the enum member and **never** against the string `"CAN_MANAGE"`: `AppPermissionLevel.CAN_MANAGE == "CAN_MANAGE"` is False;
  - drop every `service_principal_name` entry;
  - a successful read that leaves zero holders is **untrusted**: no rows change.
- **A failed or untrusted read never deletes rows.**
- **Deploy grant:** `ws.apps.update_permissions(app_name=..., access_control_list=[AppAccessControlRequest(service_principal_name=<app SP client id>, permission_level=AppPermissionLevel.CAN_MANAGE)])`. **Never** call `set_permissions`. A failure warns and the deploy continues.
- **UI copy, verbatim:**
  - tab label `Admins`;
  - badges `CAN_MANAGE on app` and `Added in Tellr`;
  - search placeholder `Search users or groups to make admin…`;
  - button `Add admin`;
  - green status `Synced from app permissions N min ago` (`just now` under one minute);
  - amber status `Tellr can't read this app's permissions. Run tellr.update to grant the app access.`;
  - lock tooltip `Change this in the app's Permissions in Databricks`;
  - empty-read error stored as `the app's permissions list no direct CAN_MANAGE users or groups`.
- **Python:** the per-worktree venv, via `uv run …` (never `pip install`). Deploy-package tests need `PYTHONPATH=packages/databricks-tellr`, or they skip.
- **Frontend:** run `npm ci` in `frontend/` once per worktree before vitest or Playwright.
- **Commits:** every commit message ends with `Co-authored-by: Isaac <no-reply@databricks.com>`. Do not push.
- **Out of scope:**
  - local dev: the existing non-production bypass in `require_admin` is untouched;
  - deck and deck-spec permissions;
  - seeding the table at deploy time.

## Review Focus

1. **Email case differs** between the permission list (`Robert.Whiffin@…`) and the signed-in caller (`robert.whiffin@…`). It must still be admin, and the sync must not create two rows. Pinned in Task 1 (`is_app_admin`) and Task 2 (dedupe).
2. **One person is admin both ways.** They appear as one list line with both badges. Remove deletes only the manual row, and they are still admin afterwards. Pinned in Task 1 (`list_admins`, `remove_manual_admin`) and Task 6 (UI).
3. **A permission-list entry with both an inherited and a direct CAN_MANAGE item** is kept. An entry whose only direct item is CAN_USE is dropped. Pinned in Task 2.
4. **A workspace admin with no row** (in the `admins` group, but no USER or GROUP row) is **not** admin. This is the reason the feature exists. Pinned in Task 3.
5. **The sync has never succeeded,** or the last read failed after earlier successes. The Admins tab shows amber with the stored error. Pinned in Task 6.

---

### Task 1: `permissions` tables and the store service

**Models:** `test=opus impl=sonnet`

**Files:**
- Create: `src/database/models/permission.py`
- Modify: `src/database/models/__init__.py` (import and `__all__`)
- Create: `src/services/admin_permissions.py`
- Test: `tests/unit/test_admin_permissions_store.py`

**Interfaces:**
- Produces (`src/database/models/permission.py`):
  - constants `RESOURCE_APP = "app"`, `APP_WIDE_RESOURCE_ID = ""`, `PRIVILEGE_ADMIN = "admin"`, `SOURCE_CAN_MANAGE_SYNC = "can_manage_sync"`, `SOURCE_MANUAL = "manual"`, `SYNC_KEY_APP_CAN_MANAGE = "app_can_manage"`, `SYNC_CREATED_BY = "can_manage_sync"` (the `created_by` value on synced rows; spec: "for synced rows, 'who' is the sync");
  - `class Permission(Base)`, `__tablename__ = "permissions"`, with columns:
    - `id` Integer PK
    - `resource_type` String(32) not null
    - `resource_id` String(255) not null default `""`
    - `identity_type` String(10) not null
    - `identity_id` String(255) nullable
    - `identity_name` String(255) not null
    - `identity_key` String(255) not null
    - `privilege` String(32) not null
    - `source` String(32) not null
    - `created_by` String(255) nullable
    - `created_at` / `updated_at` DateTime (pattern from `deck_contributor.py`)

    plus `UniqueConstraint("resource_type", "resource_id", "identity_type", "identity_key", "privilege", "source", name="uq_permissions_grant")` and `Index("ix_permissions_lookup", "resource_type", "resource_id", "privilege")`. Do not also put `index=True` on those columns: a duplicate index name crashes `create_all`.
  - `class PermissionSyncState(Base)`, `__tablename__ = "permission_sync_state"`, with columns `sync_key` String(64) PK, `last_attempt_at` DateTime nullable, `last_success_at` DateTime nullable, `last_error` Text nullable.
- Produces (`src/services/admin_permissions.py`). No function here commits; callers commit.
  - `normalize_identity_name(name: str) -> str`: returns `name.strip().lower()`.
  - `@dataclass(frozen=True) class AclHolder: identity_type: str; identity_name: str`
  - `class EmptyHolderSetError(ValueError)`. Its message is exactly `the app's permissions list no direct CAN_MANAGE users or groups`.
  - `class NotManualPermissionError(ValueError)`
  - `is_app_admin(db: Session, user_name: str, get_group_names: Callable[[], Iterable[str]]) -> bool`
  - `reconcile_can_manage(db: Session, holders: Sequence[AclHolder]) -> tuple[int, int]`: returns `(added, removed)`.
  - `add_manual_admin(db: Session, *, identity_type: str, identity_name: str, identity_id: str | None, created_by: str | None) -> Permission`
  - `remove_manual_admin(db: Session, permission_id: int) -> None`
  - `@dataclass class AdminEntry` with fields `identity_type: str`, `identity_name: str`, `identity_id: str | None`, `sources: list[str]`, `manual_permission_id: int | None`, `added_by: str | None`, `added_at: datetime | None`
  - `list_admins(db: Session) -> list[AdminEntry]`
  - `@dataclass class SyncStatus` with fields `last_attempt_at: datetime | None`, `last_success_at: datetime | None`, `last_error: str | None`
  - `record_sync_result(db: Session, *, now: datetime, error: str | None) -> None`
  - `get_sync_status(db: Session) -> SyncStatus`

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_admin_permissions_store.py`. Use a local `db_session` fixture on in-memory SQLite: `import src.database.models`, `Base.metadata.create_all`, then `sessionmaker(bind=engine, autoflush=False)`. The `autoflush=False` matches production (`src/core/database.py:365`); with the default `autoflush=True` a non-flushing `add_manual_admin` would pass. Follow `tests/unit/test_usage_service.py:12-21`. Every assertion reads rows back with a fresh query. The tests:
  - `test_tables_are_registered`: `{"permissions", "permission_sync_state"} <= set(Base.metadata.tables)`.
  - `test_user_row_match_is_case_insensitive_and_skips_group_lookup`: seed a manual USER row `Robert.Whiffin@Databricks.com`. `is_app_admin(db, "robert.whiffin@databricks.com", groups)` is True, where `groups` is a `MagicMock` that is asserted **not called**.
  - `test_workspace_admins_group_member_without_a_row_is_not_admin`: no rows, and `get_group_names` returns `["admins", "users"]`. The result is False.
  - `test_group_row_matches_callers_group_case_insensitively`: seed a GROUP row `Tellr Maintainers`; the caller's groups are `["tellr maintainers"]`. The result is True.
  - `test_group_lookup_skipped_when_no_group_rows`: only a USER row for someone else exists. The result is False and `get_group_names` is not called.
  - `test_group_lookup_error_propagates`: a GROUP row exists and `get_group_names` raises `RuntimeError`. `is_app_admin` raises `RuntimeError`.
  - `test_rows_for_other_privilege_or_resource_do_not_grant_admin`: a USER row for the caller with `privilege="edit"`, and another with `resource_type="deck_spec"`. The result is False.
  - `test_reconcile_inserts_and_deletes_only_sync_rows`:
    - seed sync rows for `a@x.com` and `b@x.com`, and a manual row for `b@x.com`;
    - reconcile with holders `[USER a@x.com, GROUP Team]` returns `(1, 1)`;
    - the remaining sync keys are `{("USER","a@x.com"),("GROUP","team")}`;
    - the newly inserted `Team` row has `created_by == SYNC_CREATED_BY`;
    - the manual `b@x.com` row is still present.
  - `test_reconcile_dedupes_case_variants`: holders `[USER A@x.com, USER a@x.com]` give exactly one sync row.
  - `test_reconcile_is_idempotent`: two identical reconciles. The second returns `(0, 0)` and the row count is unchanged.
  - `test_reconcile_refuses_empty_holder_set`:
    - seed two sync rows;
    - `reconcile_can_manage(db, [])` raises `EmptyHolderSetError`, and `str(exc)` equals the exact message above;
    - both rows are still present.
  - `test_reconcile_swallows_a_concurrent_duplicate_insert`:
    - seed the sync row `a@x.com`;
    - monkeypatch `admin_permissions._existing_sync_keys` to return `set()`, which simulates another worker inserting between this worker's read and its insert;
    - reconcile `[USER a@x.com]` does not raise;
    - exactly one row exists for that key, and the session is still usable (a follow-up `db.query(Permission).count()` works).
  - `test_add_manual_admin_is_idempotent_and_normalizes`: adding `USER Priya@Example.com` twice returns the same row id. `identity_key == "priya@example.com"`, `identity_name == "Priya@Example.com"`, `source == "manual"`, and `created_by` is stored.
  - `test_add_manual_admin_rejects_blank_name_and_bad_type`: the name `"  "` raises `ValueError`, and `identity_type="SP"` raises `ValueError`.
  - `test_remove_manual_admin_refuses_sync_rows`: removing a sync row's id raises `NotManualPermissionError` and the row remains. Removing a missing id raises `LookupError`.
  - `test_remove_manual_admin_ignores_rows_outside_app_admin`: a `manual` row with `resource_type="deck_spec"` cannot be removed through `remove_manual_admin`. It raises `LookupError`, and the row remains.
  - `test_record_sync_result_survives_concurrent_first_insert`:
    - insert the `app_can_manage` state row directly (as if another worker had won);
    - monkeypatch `admin_permissions._get_sync_state` (the helper `record_sync_result` uses to fetch the row) to return None on its first call only;
    - `record_sync_result(now=t, error=None)` does not raise;
    - after commit, exactly one state row exists, with `last_success_at == t`.
  - `test_list_admins_merges_sources_per_identity`:
    - rows: sync `sam@x.com`; manual `SAM@x.com` (`created_by` `priya`); manual GROUP `Team`;
    - `list_admins` returns 2 entries;
    - the Sam entry has `sources == ["can_manage_sync", "manual"]`, `manual_permission_id` equal to the manual row's id, and `added_by == "priya"`;
    - the Team entry has `sources == ["manual"]`;
    - entries are sorted by `(identity_type, identity_key)`.
  - `test_remove_manual_keeps_admin_through_sync_row`: Sam has both rows. After `remove_manual_admin(manual_id)`, `is_app_admin(db, "sam@x.com", lambda: [])` is still True.
  - `test_sync_status_round_trip`:
    - `get_sync_status` on an empty table returns all-None fields;
    - `record_sync_result(now=t1, error=None)` then `record_sync_result(now=t2, error="boom")` gives `last_attempt_at == t2`, `last_success_at == t1` and `last_error == "boom"`;
    - a later success at `t3` gives `last_error is None` and `last_success_at == t3`.

- [ ] **Step 2: Confirm the tests fail.** Run `uv run pytest tests/unit/test_admin_permissions_store.py -v`. Expected: collection errors (`ModuleNotFoundError: src.database.models.permission`).

- [ ] **Step 3: Implement the models,** then add the import and `__all__` entries for `Permission` and `PermissionSyncState` in `src/database/models/__init__.py`.

- [ ] **Step 4: Implement `src/services/admin_permissions.py`.**
  - **Base filter:** every query filters on `resource_type == RESOURCE_APP`, `resource_id == APP_WIDE_RESOURCE_ID` and `privilege == PRIVILEGE_ADMIN`.
  - **`is_app_admin`:**
    - return True if a USER row exists whose `identity_key` is `normalize_identity_name(user_name)`;
    - otherwise return False if no GROUP rows exist, without calling `get_group_names`;
    - otherwise intersect the GROUP keys with the normalized caller groups.
  - **`reconcile_can_manage`:**
    - raise `EmptyHolderSetError` before any write if `holders` is empty;
    - compute the wanted keys `{(type, normalize(name)): name}`;
    - read the existing sync keys through a module-level helper `_existing_sync_keys(db) -> set[tuple[str, str]]` (the test patches it);
    - insert each missing key inside `db.begin_nested()` (with `created_by=SYNC_CREATED_BY`), flushing inside the savepoint, catching `IntegrityError` (another worker won) and continuing;
    - delete the sync rows whose key is not wanted;
    - `db.flush()`.
  - **`add_manual_admin`:** validate the type (USER or GROUP) and the stripped name (not empty). Return the existing manual row when its key is already present. Otherwise `db.add`, then `db.flush()` before returning, so the id exists and the uniqueness check runs in-session.
  - **`remove_manual_admin`:** apply the same base filter as the queries above. A row outside it is treated as missing (`LookupError`).
  - **`list_admins`:** each entry's `sources` is sorted (`["can_manage_sync", "manual"]` when both are present).
  - **`record_sync_result`:**
    - fetch the row through a module-level helper `_get_sync_state(db) -> PermissionSyncState | None` (a wrapper on `db.get(PermissionSyncState, SYNC_KEY_APP_CAN_MANAGE)`);
    - when it is None, create the row inside `db.begin_nested()` and flush. On `IntegrityError` (another worker created it first), re-fetch with a plain `db.get`;
    - set `last_attempt_at = now`. On success set `last_success_at = now` and `last_error = None`. On failure set `last_error = error[:1000]`.

- [ ] **Step 5: Confirm the tests pass.** Run `uv run pytest tests/unit/test_admin_permissions_store.py -v`. Expected: all PASS. Then run `uv run pytest tests/unit/test_startup_migrations.py tests/unit/test_graph_configuration_models.py -q`. Expected: no new failure causes.

- [ ] **Step 6: Commit** `feat(admin): permissions table and admin store service`.

---

### Task 2: CAN_MANAGE sync (permission list → table) and the lifespan loop

**Models:** `test=opus impl=sonnet`

**Files:**
- Create: `src/services/can_manage_sync.py`
- Modify: `src/api/main.py`: start the loop in `lifespan` next to `_spec_sweeper_task` (around `:185-195`), and cancel it on shutdown the same way that task is cancelled.
- Test: `tests/unit/test_can_manage_sync.py`

**Interfaces:**
- Consumes (Task 1): `AclHolder`, `normalize_identity_name`, `reconcile_can_manage`, `record_sync_result`, `get_sync_status`, `EmptyHolderSetError`, `IdentityType`.
- Produces:
  - `RETRY_INTERVAL_SECONDS = 30`
  - `SYNC_INTERVAL_SECONDS = 300`
  - `holders_from_acl(acl: AppPermissions) -> list[AclHolder]`
  - `sync_once(now: datetime | None = None) -> bool`: True only when the reconcile committed.
  - `async def can_manage_sync_loop() -> None`
  - module-level imports `get_db_session` (from `src.core.database`) and `get_system_client` (from `src.core.databricks_client`), so tests can patch `src.services.can_manage_sync.<name>`.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_can_manage_sync.py`.
  - **Fixtures:**
    - Build `AppPermissions` / `AppAccessControlResponse` / `AppPermission` objects from `databricks.sdk.service.apps`.
    - One fixture reproduces the spike's real payload (`~/tellr-loop/admin-acl-spike/probe-4-can-manage-delayed.json`): the `admins` group CAN_MANAGE inherited from `/apps`; the SP `434da09e-…` with direct CAN_MANAGE; the user `robert.whiffin@databricks.com` with direct CAN_MANAGE.
    - For `sync_once`, patch `src.services.can_manage_sync.get_db_session` with a context manager over an in-memory SQLite factory that commits on exit, and patch `get_system_client` to return a `MagicMock` whose `apps.get_permissions` returns or raises. Use `monkeypatch.setenv("DATABRICKS_APP_NAME", "tellr")`.
  - **The tests:**
    - `test_spike_payload_yields_only_the_direct_user`: the result equals `[AclHolder("USER", "robert.whiffin@databricks.com")]`.
    - `test_direct_group_grant_is_kept_even_if_named_admins`: a GROUP `admins` with a direct (non-inherited) CAN_MANAGE gives `AclHolder("GROUP", "admins")`.
    - `test_entry_with_inherited_and_direct_can_manage_is_kept`: `all_permissions` holds `[inherited CAN_MANAGE, direct CAN_MANAGE]`, and the user is kept.
    - `test_direct_can_use_only_is_dropped`: a user with only direct `CAN_USE` is not in the result.
    - `test_service_principals_are_dropped`: any `service_principal_name` entry, even with direct CAN_MANAGE, is not in the result.
    - `test_sync_once_success_reconciles_and_records_success`:
      - seed a stale sync row `gone@x.com` and a manual row `keep@x.com`;
      - the permission list holds `new@x.com` with direct CAN_MANAGE;
      - `sync_once(now=t)` is True;
      - the sync keys are `{("USER","new@x.com")}`, and the manual row remains;
      - `get_sync_status` gives `last_success_at == t` and `last_error is None`;
      - `get_permissions` was called with `app_name="tellr"`.
    - `test_sync_once_read_failure_changes_nothing`:
      - seed a sync row;
      - `get_permissions` raises `PermissionDenied("does not have apps.ruleSets/get")`;
      - the result is False, and the row is still present;
      - `last_error` contains `ruleSets/get`, and `last_success_at` is unchanged (None);
      - a warning is logged (`caplog`). Because no sync has ever succeeded, the log text also contains `tellr.update`.
    - `test_sync_once_untrusted_empty_read_changes_nothing`:
      - seed a sync row;
      - the permission list holds only the inherited `admins` group and the SP;
      - the result is False, and the row is still present;
      - `last_error` equals the exact empty-read message.
    - `test_sync_once_without_app_name_fails_without_calling_the_api`: with `delenv("DATABRICKS_APP_NAME")`, the result is False and `get_system_client` is not called.
    - `test_loop_retries_fast_until_first_success_then_slows`:
      - patch `sync_once` to return `False, False, True, True` in turn;
      - patch the module's own `asyncio` name, not the stdlib: `monkeypatch.setattr(can_manage_sync, "asyncio", SimpleNamespace(sleep=fake_sleep, to_thread=inline_to_thread, CancelledError=asyncio.CancelledError))`. `fake_sleep` is an async fake that records its argument and raises `asyncio.CancelledError` on the 4th call; `inline_to_thread` is an async function that calls its argument directly. The module must therefore reach `sleep`, `to_thread` and `CancelledError` only as `asyncio.<name>`;
      - run `can_manage_sync_loop()` under `pytest.raises(asyncio.CancelledError)`;
      - the recorded sleeps are `[30, 30, 300, 300]`, and `sync_once` was called 4 times (the first call comes before any sleep).
    - `test_loop_survives_an_exception_in_sync_once`: `sync_once` raises `RuntimeError` once and then returns True. The loop keeps going, and the sleeps start `[30, 300]`.

- [ ] **Step 2: Confirm the tests fail.** Run `uv run pytest tests/unit/test_can_manage_sync.py -v`. Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/services/can_manage_sync.py`.**
  - **`holders_from_acl`:** apply the Global Constraints filter, keeping the first spelling seen per `(type, normalized name)`.
  - **`sync_once`:**
    - read `DATABRICKS_APP_NAME`; if it is unset, record the failure `DATABRICKS_APP_NAME is not set` and return False;
    - `client = get_system_client()`, then `acl = client.apps.get_permissions(app_name=app_name)`, then `holders_from_acl`;
    - inside `with get_db_session() as db:`, call `reconcile_can_manage` and then `record_sync_result(error=None)`;
    - on any exception (including `EmptyHolderSetError`), record the failure with `f"{type(exc).__name__}: {exc}"` (or the bare message for `EmptyHolderSetError`) in a **separate** `get_db_session()`, wrapped so that a failure to record is only logged, then log a warning and return False.
    - The warning says, when `get_sync_status().last_success_at is None`: "no CAN_MANAGE sync has ever succeeded; only admins added in Tellr exist. Run tellr.update so the app's service principal holds CAN_MANAGE on the app."
  - **`can_manage_sync_loop`:**
    - loop forever: `ok = await asyncio.to_thread(sync_once)`, catching and logging `Exception` and re-raising `CancelledError`;
    - set `succeeded |= ok`;
    - then `await asyncio.sleep(SYNC_INTERVAL_SECONDS if succeeded else RETRY_INTERVAL_SECONDS)`.

- [ ] **Step 4: Wire the loop into `lifespan` in `src/api/main.py`.**
  - Add the module-level `_can_manage_sync_task = None` next to `_spec_sweeper_task = None` (`main.py:79`), and add `_can_manage_sync_task` to the lifespan's `global` line (`main.py:88`). Otherwise TestClient shutdown reads an unbound name, because the start is skipped under `IS_TESTING`.
  - Inside the existing `if not IS_TESTING:` block, add `if IS_PRODUCTION and os.getenv("DATABRICKS_APP_NAME"):`, start `asyncio.create_task(can_manage_sync_loop())`, and log `"App CAN_MANAGE admin sync started"`.
  - On shutdown, cancel and await it using the same module-level pattern as `_spec_sweeper_task` (`main.py:261-266`).

- [ ] **Step 5: Confirm the tests pass.** Run `uv run pytest tests/unit/test_can_manage_sync.py -v`. Expected: all PASS. Then run `uv run python -c "import src.api.main"`. Expected: no error.

- [ ] **Step 6: Commit** `feat(admin): sync CAN_MANAGE holders into the permissions table`.

---

### Task 3: `require_admin` decides from the table

**Models:** `test=opus impl=sonnet`

**Files:**
- Modify: `src/api/routes/_authz.py`: the module docstring; the "HIGH-2" comment block (`:291-334`); `_ADMIN_GROUP` (delete it); `_admin_acl_probe` (`:346`); and the `require_admin` and `is_caller_admin` docstrings.
- Modify: `tests/unit/test_authz_helpers.py`: rewrite the `_admin_acl_probe` section (`:205-281`).
- Modify: `tests/unit/test_user_current_is_admin.py`: the group-seam failure test (`:55-78`).
- Test: the same two files.

**Interfaces:**
- Consumes (Task 1): `is_app_admin`.
- Produces: `_admin_acl_probe(user_name: str) -> bool`. The name is kept as the test seam: about 15 test files patch it. It raises on any DB or group-lookup error. `_caller_group_display_names(client, user_name) -> set[str]` is unchanged. `require_admin`, `is_caller_admin` and `reset_admin_cache` keep their signatures.

- [ ] **Step 1: Rewrite the probe tests** in `tests/unit/test_authz_helpers.py`. Replace the "workspace admins group (Direction C)" section with a table-backed one:
  - **Wiring:** patch `_authz.get_db_session` with a context manager over an in-memory SQLite session that has the tables, and seed rows with Task 1's `add_manual_admin` / `reconcile_can_manage`. Patch `src.core.databricks_client.get_user_client` to a `MagicMock` and `_authz._caller_group_display_names` to a recording lambda.
  - **The tests:**
    - `test_probe_user_row_is_admin_without_group_lookup`: a row for `bob@test.com`; `_admin_acl_probe("BOB@test.com")` is True, and the group seam is not called.
    - `test_probe_workspace_admins_member_without_row_is_denied`: no rows, and the caller's groups are `{"admins"}`. The result is False. This is the regression that pins the semantic change.
    - `test_probe_group_row_matches_callers_group`: a GROUP row `Tellr Maintainers`; the caller's groups are `{"tellr maintainers"}`. The result is True.
    - `test_probe_db_error_raises`: patch `get_db_session` to raise `OperationalError`, and assert that `_admin_acl_probe` raises.
    - `test_probe_group_lookup_error_raises_when_group_rows_exist`: a GROUP row exists, and `current_user.me` raises `RuntimeError`. The probe raises.
  - **Keep and adapt:** `test_caller_group_display_names_reads_me_group_display` stays as it is. The `require_admin` tests at `:130-205` already patch `_admin_acl_probe` and stay as they are.

- [ ] **Step 2: Make `test_user_current_is_admin.py`'s broken-group-lookup test non-vacuous.** The probe now skips the group lookup when there are no GROUP rows, so patching the seam alone no longer reaches it. Seed a GROUP row through a patched `_authz.get_db_session` (as in Step 1), keep `boom` on `_caller_group_display_names`, and assert `is_admin is False` and that `boom` **was called**, using a call-recording wrapper.

- [ ] **Step 3: Confirm the tests fail.** Run `uv run pytest tests/unit/test_authz_helpers.py tests/unit/test_user_current_is_admin.py -v`. Expected: the new probe tests FAIL. For example, `test_probe_workspace_admins_member_without_row_is_denied` returns True, and the user-row test calls `me()`.

- [ ] **Step 4: Implement.**
  - **`_admin_acl_probe(user_name)`:** `with get_db_session() as db: return is_app_admin(db, user_name, lambda: _caller_group_display_names(get_user_client(), user_name))`. Import `get_user_client` inside the function, as today.
  - **Delete `_ADMIN_GROUP`.**
  - **Rewrite the comment block:**
    - keep a short history of the three earlier attempts (the July PR #228 walls);
    - add the spike result: the app SP can read its own permission list once it holds CAN_MANAGE on itself; CAN_USE is not enough; the grant takes about 30–60 s to propagate; the SP cannot see group members;
    - state the new definition: admin = a row in `permissions` for (`app`, `""`, `admin`) matching the caller's email, or one of the caller's own group display names; rows come from the CAN_MANAGE sync or the Admins tab.
  - **Update the docstrings** of `require_admin` and `is_caller_admin`: replace every mention of the "workspace `admins` group", and leave behaviour as it is.

- [ ] **Step 5: Confirm the tests pass.** Run `uv run pytest tests/unit/test_authz_helpers.py tests/unit/test_user_current_is_admin.py -v`. Expected: all PASS. Then run every file that patches the seam (`grep -rl _admin_acl_probe tests/unit | xargs uv run pytest -q`). Expected: no new failure causes against the baseline.

- [ ] **Step 6: Commit** `feat(admin): require_admin reads the permissions table instead of the admins group`.

---

### Task 4: Admin API for listing, adding and removing admins

**Models:** `test=opus impl=sonnet`

**Files:**
- Create: `src/api/routes/admin_permissions.py`
- Modify: `src/api/main.py`: add `admin_permissions` to the `from src.api.routes import (...)` block (`main.py:14-32`, where `admin_usage` is imported; `src/api/routes/__init__.py` does **not** export `admin_usage`, so leave it alone), then `app.include_router(admin_permissions.router)` next to `admin_usage.router` (`:527`).
- Modify: `tests/unit/test_admin_route_authorization_inventory.py`:
  - add the three routes to the `EXPECTED_ALL_ADMIN_ROUTES` literal (`:117-130`);
  - bump the pinned count from 37 to **40** in `assert len(EXPECTED_ALL_ADMIN_ROUTES) == 37` (`:220`);
  - rename `test_the_expected_route_sets_have_exactly_24_2_and_37_pairs` to `…_24_2_and_40_pairs`;
  - update the "37" in the module docstring and comments (`:1-20`, `:102-105`).

  This adds entries; nothing is removed.
- Test: `tests/unit/test_admin_permissions_routes.py`

**Interfaces:**
- Consumes (Task 1): `list_admins`, `add_manual_admin`, `remove_manual_admin`, `get_sync_status`, `NotManualPermissionError`. Consumes (Task 3): `require_admin`, `reset_admin_cache`.
- Produces: `router = APIRouter(prefix="/api/admin/admins", tags=["admin-permissions"], dependencies=[Depends(require_admin)])` with these routes:
  - `GET ""` returns 200 `{"admins": [{"identity_type","identity_name","identity_id","sources","manual_permission_id","added_by","added_at"}], "sync": {"last_attempt_at","last_success_at","last_error"}}`. Datetimes are ISO 8601 strings or null.
  - `POST ""` takes the body `{"identity_type": "USER"|"GROUP", "identity_name": str, "identity_id": str|null}` and returns 201 `{"permission_id": int}`. A bad type or blank name gives 422.
  - `DELETE "/{permission_id}"` returns 204. A missing id gives 404. A non-manual row gives 409 with the detail `This admin comes from CAN_MANAGE on the app. Change it in the app's Permissions in Databricks.`
  - Both POST and DELETE call `db.commit()` and then `reset_admin_cache()`. `created_by` is `get_current_user()`.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_admin_permissions_routes.py`.
  - **Wiring:**
    - use `TestClient(app)` with `app.dependency_overrides[get_db]` yielding an in-memory SQLite session (`autoflush=False`) that has the tables;
    - for the gate itself, patch `_authz._is_production` to True and `_authz._admin_acl_probe` to True or False;
    - call `_authz.reset_admin_cache()` in the fixture's setup **and** teardown, because the verdict cache is process-global;
    - patch the cache-reset recorder on the name the route module calls (`src.api.routes.admin_permissions.reset_admin_cache`), not on `_authz`.
  - **The tests:**
    - `test_non_admin_gets_403_on_every_admin_route`: with the probe False, GET, POST and DELETE each return 403, and no row is written.
    - `test_list_returns_merged_entries_and_sync_status`:
      - seed sync and manual rows for `sam@x.com` and record a sync failure;
      - the response has one Sam entry with `sources == ["can_manage_sync","manual"]`;
      - `sync.last_error` is the stored string, and `sync.last_success_at` is null.
    - `test_add_then_list_shows_added_in_tellr`: POST a USER `priya@example.com`, then GET lists her with `sources == ["manual"]` and `added_by` equal to the current user (patch `get_current_user` in the route module).
    - `test_add_validation_422`: the type `SP` and the name `"  "` each return 422.
    - `test_delete_manual_row_204_and_cache_reset`: patch `reset_admin_cache` with a recorder. The DELETE returns 204, the row is gone, and the recorder was called once.
    - `test_delete_sync_row_409_and_row_kept`: the 409 detail matches exactly, and the row still exists.
    - `test_delete_missing_404`.

- [ ] **Step 2: Confirm the tests fail.** Run `uv run pytest tests/unit/test_admin_permissions_routes.py tests/unit/test_admin_route_authorization_inventory.py -v`. Expected: the new tests fail with 404 (no route), and the inventory test fails on the missing routes.

- [ ] **Step 3: Implement the router** with Pydantic request and response models. Map `ValueError` to 422, `LookupError` to 404 and `NotManualPermissionError` to 409. Then register it.

- [ ] **Step 4: Confirm the tests pass.** Run the same command as Step 2. Expected: all PASS, including `test_every_admin_route_declares_require_admin` and the renamed `…_24_2_and_40_pairs` count test.

- [ ] **Step 5: Commit** `feat(admin): admin API to list, add and remove app admins`.

---

### Task 5: Deploy grants the app SP CAN_MANAGE, plus the docs

**Models:** `test=opus impl=sonnet`

**Files:**
- Modify: `packages/databricks-tellr/databricks_tellr/deploy.py`:
  - add `_ensure_app_sp_can_manage` next to `_ensure_app_user_api_scopes` (`:1714`);
  - call it in `_create_databricks` right after `_create_app(...)` prints "App registered" (`:495`), passing `_get_app_client_id(app)`;
  - call it in `_update_databricks` after the scopes block and before `deploy_and_wait` (`:692-707`).
- Modify: `scripts/deploy_local.py`:
  - import the function in the `from databricks_tellr.deploy import (...)` block (`:38`);
  - call it in `create_local` after "App registered" (`:603`), passing `_get_app_client_id(app)`;
  - call it in `update_local` before `deploy_and_wait` (`:925`) as `_ensure_app_sp_can_manage(ws, app_name)`, with **no** client id. On the plain non-branch update path `app` and `client_id` are unbound there (`app` is bound only at `:736` and `:853`, `client_id` only at `:754`), so let the helper look the id up.
- Modify: `docs/technical/permissions-model.md`: replace the "Workspace Admin" section (`:489-513`).
- Modify: `docs/technical/databricks-app-deployment.md`: one new step under create and update.
- Test: `tests/unit/test_deploy_app_sp_can_manage.py`

**Interfaces:**
- Produces: `_ensure_app_sp_can_manage(ws: WorkspaceClient, app_name: str, client_id: str | None = None) -> bool`. It **never raises**.
  - When `client_id` is None, it is looked up through `_get_app_client_id(ws.apps.get(name=app_name))`, inside the guarded block.
  - On success it prints `   App service principal granted CAN_MANAGE on the app (admin sync)` and returns True.
  - On any failure, or when no client id can be found, it prints a `WARNING:` line plus the manual fix and returns False. The fix, verbatim with the values filled in:
    `databricks apps update-permissions <app_name> --json '{"access_control_list":[{"service_principal_name":"<client_id>","permission_level":"CAN_MANAGE"}]}'`
    When the id is unknown, the fix says instead: "add the app's service principal with Can Manage in the app's Permissions tab".

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_deploy_app_sp_can_manage.py`. Use `pytest.importorskip("databricks_tellr")`, and run with `PYTHONPATH=packages/databricks-tellr`.
  - `test_grants_can_manage_additively`:
    - `_ensure_app_sp_can_manage(ws, "app", "cid")` is True;
    - `ws.apps.update_permissions` was called once with `app_name="app"`, and `access_control_list[0]` has `service_principal_name == "cid"` and `permission_level == AppPermissionLevel.CAN_MANAGE`;
    - `ws.apps.set_permissions.assert_not_called()`.
  - `test_looks_up_client_id_when_not_given`: `ws.apps.get.return_value = App(name="app", service_principal_client_id="cid")`, and the grant uses `cid`.
  - `test_failure_warns_with_manual_fix_and_returns_false`: `update_permissions` raises `PermissionDenied`. The result is False, and `capsys` output contains `WARNING` and the exact CLI command with `app` and `cid` filled in.
  - `test_missing_client_id_warns_and_makes_no_call`.
  - `test_update_grants_before_deploying`: copy the stub pattern from `tests/unit/test_deploy_app_scopes.py:64-100`. Record the call order between `ws.apps.update_permissions` and `ws.apps.deploy_and_wait`, and assert the grant comes first.
  - `test_update_still_deploys_when_grant_fails`: `update_permissions` raises, and `deploy_and_wait` is still called once.
  - `test_create_grants_after_app_registration`: write a `_stub_create_steps(monkeypatch, ws)` helper modelled on the update stubs in `tests/unit/test_deploy_app_scopes.py:64-100`. It stubs `_get_workspace_client`, `_get_or_create_lakebase` (return `{"type": "provisioned"}`), `_write_requirements`, `_write_app_yaml`, `_upload_files`, `_staging_dir`, `_create_app` (returning `App(name="app", service_principal_client_id="cid")`), `_setup_database_schema` and `_deploy_app`, plus anything else `_create_databricks` calls before deploying. (`test_deploy_local_schema_setup_sp_only.py` stubs `scripts.deploy_local`, not `deploy._create_databricks`, so it does not apply here.) Record the call order and assert that `update_permissions` runs after `_create_app` and before `_deploy_app`, with `cid`.
  - `test_deploy_local_create_and_update_grant`: drive `deploy_local.create_local` using the stubs in `tests/unit/test_deploy_local_schema_setup_sp_only.py`, and `deploy_local.update_local` using `tests/unit/test_deploy_local_config_branching.py`. Patch `deploy_local._ensure_app_sp_can_manage` with a recorder, and assert it is called once in each flow with that flow's app name. For `update_local`, drive the plain non-branch path, where `app` is unbound, and assert the recorder received no client id.

- [ ] **Step 2: Confirm the tests fail.** Run `PYTHONPATH=packages/databricks-tellr uv run pytest tests/unit/test_deploy_app_sp_can_manage.py -v`. Expected: an `AttributeError: _ensure_app_sp_can_manage` (not a skip; a skip means `PYTHONPATH` is wrong).

- [ ] **Step 3: Implement** the function and the four call sites.

- [ ] **Step 4: Confirm the tests pass.** Run `PYTHONPATH=packages/databricks-tellr uv run pytest tests/unit/test_deploy_app_sp_can_manage.py tests/unit/test_deploy_app_scopes.py tests/unit/test_deploy_local_schema_setup_sp_only.py tests/unit/test_deploy_local_config_branching.py -v`. Expected: all PASS.

- [ ] **Step 5: Docs.**
  - **`permissions-model.md`:** rename the section to "App Admin" and cover:
    - the union definition;
    - the `permissions` table and its two sources;
    - the sync: app SP, direct CAN_MANAGE only, inherited and SP entries skipped, 30 s/300 s, a failed or empty read changes nothing;
    - group rows matched against the caller's own `me().groups`;
    - the 60 s per-worker cache;
    - the deploy grant and why it is needed (the spike);
    - keep the "fails closed", "dev short-circuit" and "client-side guard is cosmetic" paragraphs and the "Where the admin tier applies" table.
  - **`databricks-app-deployment.md`:** one step under both create and update saying the deploy grants the app SP CAN_MANAGE on its own app, with the manual CLI fix.

- [ ] **Step 6: Commit** `feat(deploy): grant the app service principal CAN_MANAGE on its own app`.

---

### Task 6: The Admins tab

**Models:** `test=opus impl=sonnet`

**Files:**
- Modify: `frontend/src/api/admin.ts`:
  - make `fetchJson` return `undefined` on a 204 (the DELETE needs it);
  - add the types and three functions;
  - on a non-OK response, throw an `Error` whose message is the `detail` of the JSON body when there is one, and the text otherwise.
- Create: `frontend/src/components/Admin/AdminAdmins.tsx`
- Modify: `frontend/src/components/Admin/AdminPage.tsx`: add `'admins'` to `TabId`, a last tab button `Admins` (`id="admins-tab"`, `aria-controls="admins-panel"`), and a panel that mounts `<AdminAdmins />` only after the tab is first opened. Copy the `hasVisitedAgentDefinitions` pattern, so other admin e2e tests do not hit an unmocked `/api/admin/admins`.
- Test: `frontend/src/components/Admin/AdminAdmins.test.tsx` (vitest, jsdom); `frontend/tests/e2e/admin-page.spec.ts` (one new test, already in the CI e2e matrix).

**Interfaces:**
- Consumes (Task 4): the HTTP contract above. Also `configApi.searchIdentities(query)` (`frontend/src/api/config.ts:782`), which returns `{identities: Identity[]}` with `{id, display_name, user_name?, type}`.
- Produces in `admin.ts`:
  - `type AdminSource = 'can_manage_sync' | 'manual'`
  - `interface AppAdminEntry { identity_type: 'USER' | 'GROUP'; identity_name: string; identity_id: string | null; sources: AdminSource[]; manual_permission_id: number | null; added_by: string | null; added_at: string | null }`
  - `interface AdminSyncStatus { last_attempt_at: string | null; last_success_at: string | null; last_error: string | null }`
  - `interface AppAdminsResponse { admins: AppAdminEntry[]; sync: AdminSyncStatus }`
  - `adminApi.listAdmins(): Promise<AppAdminsResponse>`
  - `adminApi.addAdmin(body: { identity_type: 'USER' | 'GROUP'; identity_name: string; identity_id: string | null }): Promise<{ permission_id: number }>`
  - `adminApi.removeAdmin(permissionId: number): Promise<void>`
- Produces in `AdminAdmins.tsx`: `export const AdminAdmins: React.FC`. Each list line has `data-testid={\`admin-row-${identity_type}-${identity_name}\`}`. The status line has `data-testid="admin-sync-status"` and `data-state="ok" | "warn"`.

- [ ] **Step 1: Write the failing vitest tests** in `AdminAdmins.test.tsx`. Mock `../../api/admin`, `../../api/config` and `../../contexts/ToastContext` the way `AdminDesignSystemDefault.test.tsx:1-30` does, and use `vi.useFakeTimers` for the search debounce.
  - **The tests:**
    - `renders one line per identity with a badge per source`:
      - Sam has `['can_manage_sync','manual']`, Robert has `['can_manage_sync']`, and the group Team has `['manual']`;
      - Sam's line shows both `CAN_MANAGE on app` and `Added in Tellr`, plus a `Remove sam@x.com` button;
      - Robert's line has **no** Remove button, and has an element with `title="Change this in the app's Permissions in Databricks"`;
      - Team's line shows the subtitle `group`;
      - Sam's line (`added_by: 'priya'`, `added_at: '2026-11-01T10:00:00Z'`) shows text matching `/added by priya · /`.
    - `shows green status after a successful sync`: `last_success_at` is 5 minutes before the faked now and `last_error` is null. The status has `data-state="ok"` and the text `Synced from app permissions 5 min ago`.
    - `shows amber status when no sync ever succeeded`: `last_success_at` is null and `last_error` is `PermissionDenied: … ruleSets/get`. The status has `data-state="warn"`, contains the exact amber copy, and shows the error text.
    - `shows amber status when the last read failed after earlier successes`: both fields are set, so the state is `warn`.
    - `search then Add admin posts the USER email, not the display name`:
      - typing `pri` and advancing 300 ms calls `searchIdentities('pri')`;
      - clicking the result `{id:'u1', display_name:'Priya P', user_name:'priya@example.com', type:'USER'}` and then `Add admin` calls `addAdmin({identity_type:'USER', identity_name:'priya@example.com', identity_id:'u1'})`;
      - then `listAdmins` is called again.
    - `Add admin is disabled until a result is picked`.
    - `adding a group posts its display name`.
    - `Remove calls removeAdmin with the manual id and reloads`: `removeAdmin(42)` is called, followed by a second `listAdmins`.
    - `a failed remove shows an error toast and keeps the line`.

- [ ] **Step 2: Write the e2e test** `Admins tab lists admins with source badges` in `frontend/tests/e2e/admin-page.spec.ts`:
  - route `**/api/admin/admins` GET with the fixture from the first vitest test plus a green sync status;
  - open `/admin` and click the `Admins` tab;
  - assert Sam's row shows both badges, and Robert's row has no `Remove` button.

- [ ] **Step 3: Confirm the tests fail.** Run `cd frontend && npx vitest run src/components/Admin/AdminAdmins.test.tsx`. Expected: FAIL (module not found).

- [ ] **Step 4: Implement** the API additions, `AdminAdmins` and the `AdminPage` tab.
  - **Search:** a 300 ms debounce (pattern from `DeckContributorsManager.tsx:102-130`). Selecting a result sets `selected`.
  - **USER rows** post `user_name ?? display_name`; **GROUP rows** post `display_name`.
  - **Status age:** "N min ago" uses whole minutes, `just now` under one minute, and `N h ago` from 60 minutes.
  - **Style:** match the existing admin panels (Tailwind, `react-icons/fi`).

- [ ] **Step 5: Confirm the tests pass.**
  - `cd frontend && npx vitest run src/components/Admin/` passes.
  - `npx tsc --noEmit -p .` (or the project's `npm run typecheck`, if present) shows no errors.
  - `npx playwright test tests/e2e/admin-page.spec.ts` passes. If the local Chromium install is unavailable, record that in the ledger and leave the e2e to CI.

- [ ] **Step 6: Commit** `feat(admin): Admins tab to list, add and remove app admins`.

---

## Notes for the orchestrator

- **Task order:** Tasks 1→6 run in order. Tasks 2 and 4 both touch `src/api/main.py`, and Tasks 3 and 4 both depend on Task 1.
- **Inventory pin:** `test_admin_route_authorization_inventory.py` pins the routes exactly. Task 4 only adds entries. If the auto-mode classifier refuses that edit, stop and ask the user. Do not route around it.
- **Deviations from the spec (rulings):**
  - The user-guide screenshots (`frontend/tests/user-guide/`) are not regenerated in this plan. The Admins panel mounts lazily, so those runs see only one extra tab label.
  - `admin-route-gate.spec.ts` needs no change: it returns 500 for every `/api/admin/**` call and never opens the Admins tab.
  - The new routes live in their own router file (`admin_permissions.py`, prefix `/api/admin/admins`, `dependencies=[Depends(require_admin)]`) rather than inside `admin.py`, the same way `admin_usage.py` does. The gate and the route inventory are the same as the spec intends.
- **Live checks for the devloop** (not unit-testable):
  1. After `deploy_local update`, the app SP holds CAN_MANAGE on its devloop app.
  2. The first sync succeeds within about a minute; the green status appears.
  3. The deploying user is listed with `CAN_MANAGE on app`.
  4. A user added on the tab gains admin; removing them takes it away again (within the 60 s cache).
  5. Record whether `me().groups` includes indirect groups.
