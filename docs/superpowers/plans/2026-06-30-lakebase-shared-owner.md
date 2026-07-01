# Lakebase shared-owner model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move ownership of all `app_data_prod` objects to a shared Postgres role (`tellr_app_owners`) so any app service principal can run `ALTER`-bearing migrations on a copy-on-write fork of production Lakebase.

**Architecture:** A permanent `NOLOGIN` role owns the prod schema. App SPs join it `WITH INHERIT TRUE` (table powers); one dedicated granter SP joins `WITH ADMIN OPTION, INHERIT FALSE` (membership powers, no table powers). A serverless Databricks job running as the granter SP confers membership on each new dev SP at deploy time. The app's migration path re-homes any newly created object onto the role. A run-once script performs the historic ownership transfer by connecting *as the prod SP* with a UI-issued OAuth token.

**Tech Stack:** Python 3.11, `databricks-sdk` (`WorkspaceClient`, `ws.postgres`, `ws.jobs`), `psycopg2-binary`, SQLAlchemy (migrations), `pytest` + `unittest.mock`.

## Global Constraints

- Owning role: `tellr_app_owners`, `NOLOGIN`. Owns schema `app_data_prod` and all its objects.
- App SP membership grant: `WITH INHERIT TRUE`. Granter SP membership grant: `WITH ADMIN OPTION, INHERIT FALSE`. Humans get **no** Postgres membership.
- Membership grants use PG16 option syntax (`WITH ADMIN OPTION, INHERIT FALSE` / `WITH INHERIT TRUE`). The Lakebase Postgres major version being ≥16 is a **validation gate** (Task 8) before any prod step.
- Production project / database: `db-tellr` (autoscaling). Production branch: `production`. Schema: `app_data_prod`.
- The historic `REASSIGN` runs **as the prod SP** (current owner) using a UI-issued OAuth token — no SDK-minted token, no `SET ROLE`, no superuser.
- The grant job runs on **serverless** compute, runs **as the granter SP**, has an **open run-ACL**, and is parameterised by the new SP id + branch host + branch endpoint.
- The grant job executes `GRANT tellr_app_owners TO "<new_sp>" WITH INHERIT TRUE` against the **branch** endpoint (Postgres path — never Databricks group membership).
- Identifiers are quoted with double quotes in SQL (`"tellr_app_owners"`, `"<client_id>"`), matching `_grant_schema_permissions`.
- Every database step (grant, reassign, role create) is idempotent. The transfer script no-ops if the schema is already owned by the role and requires explicit confirmation after a dry-run summary.
- Prove every fork-specific behaviour on a throwaway autoscaling project (Task 8) **before** touching prod (Task 9).

---

## File structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `scripts/lakebase_shared_owner_sql.py` | Create | Pure SQL-builder + guard functions shared by the transfer script and grant job. No I/O — fully unit-testable. |
| `scripts/lakebase_transfer_ownership.py` | Create | Run-once, two-identity transfer: operator setup + reassign-as-prod-SP. CLI. |
| `scripts/lakebase_grant_owner_role.py` | Create | Grant-job entry point: connect to a branch as the granter SP, grant a new SP into the role. |
| `src/core/database.py` | Modify (`_run_migrations`, add `_reassign_new_objects_to_shared_owner`) | Re-home newly created objects onto `tellr_app_owners` at end of migrations. |
| `scripts/deploy_local.py` | Modify (`create_local`, add `_trigger_owner_grant_job`) | Trigger the grant job for each new `devloop` instance's SP and wait. |
| `config/deployment.yaml` | Modify (`devloop` env) | Carry `lakebase.owner_grant_job_id`. |
| `tests/unit/test_lakebase_shared_owner_sql.py` | Create | Unit tests for the SQL builders/guards. |
| `tests/unit/test_lakebase_transfer_ownership.py` | Create | Unit tests for the transfer orchestration (mocked connections). |
| `tests/unit/test_lakebase_grant_owner_role.py` | Create | Unit tests for the grant-job entry point (mocked ws + psycopg2). |
| `tests/unit/test_reassign_shared_owner_migration.py` | Create | Unit tests for the migration REASSIGN step. |
| `tests/unit/test_deploy_local_owner_grant.py` | Create | Unit tests for the deploy-flow job trigger. |
| `docs/technical/dev-deploy.md` | Modify | Replace the migration-limitation note once the model ships. |

---

## Task 1: SQL builders + guards (`lakebase_shared_owner_sql.py`)

**Files:**
- Create: `scripts/lakebase_shared_owner_sql.py`
- Test: `tests/unit/test_lakebase_shared_owner_sql.py`

**Interfaces:**
- Produces:
  - `OWNING_ROLE: str = "tellr_app_owners"`
  - `owning_role_exists(cur, role: str = OWNING_ROLE) -> bool`
  - `schema_owner(cur, schema: str) -> str | None`
  - `schema_is_shared_owned(cur, schema: str, role: str = OWNING_ROLE) -> bool`
  - `sql_create_owning_role(role: str = OWNING_ROLE) -> str`
  - `sql_grant_admin(role: str, granter_sp_id: str) -> str`
  - `sql_grant_member(role: str, sp_id: str) -> str`
  - `sql_reassign_owned(role: str) -> str`
  - `sql_alter_schema_owner(schema: str, role: str) -> str`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_lakebase_shared_owner_sql.py
from unittest.mock import MagicMock
import scripts.lakebase_shared_owner_sql as m


def test_sql_builders_exact_strings():
    assert m.OWNING_ROLE == "tellr_app_owners"
    assert m.sql_create_owning_role() == 'CREATE ROLE "tellr_app_owners" NOLOGIN'
    assert (
        m.sql_grant_admin("tellr_app_owners", "gid")
        == 'GRANT "tellr_app_owners" TO "gid" WITH ADMIN OPTION, INHERIT FALSE'
    )
    assert (
        m.sql_grant_member("tellr_app_owners", "sid")
        == 'GRANT "tellr_app_owners" TO "sid" WITH INHERIT TRUE'
    )
    assert m.sql_reassign_owned("tellr_app_owners") == 'REASSIGN OWNED BY CURRENT_USER TO "tellr_app_owners"'
    assert (
        m.sql_alter_schema_owner("app_data_prod", "tellr_app_owners")
        == 'ALTER SCHEMA "app_data_prod" OWNER TO "tellr_app_owners"'
    )


def test_owning_role_exists_true_false():
    cur = MagicMock()
    cur.fetchone.return_value = (1,)
    assert m.owning_role_exists(cur) is True
    cur.fetchone.return_value = None
    assert m.owning_role_exists(cur) is False


def test_schema_owner_and_shared_owned():
    cur = MagicMock()
    cur.fetchone.return_value = ("tellr_app_owners",)
    assert m.schema_owner(cur, "app_data_prod") == "tellr_app_owners"
    assert m.schema_is_shared_owned(cur, "app_data_prod") is True
    cur.fetchone.return_value = ("161834b3-...",)
    assert m.schema_is_shared_owned(cur, "app_data_prod") is False
    cur.fetchone.return_value = None
    assert m.schema_owner(cur, "app_data_prod") is None
    assert m.schema_is_shared_owned(cur, "app_data_prod") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_lakebase_shared_owner_sql.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.lakebase_shared_owner_sql'`

- [ ] **Step 3: Write the implementation**

```python
# scripts/lakebase_shared_owner_sql.py
"""Pure SQL builders + read-only guards for the Lakebase shared-owner model.

No connections are opened here; every function takes an already-open DB-API
cursor or returns a SQL string. This keeps the ownership logic unit-testable
and shared between the one-off transfer script and the per-deploy grant job.
"""
from __future__ import annotations

OWNING_ROLE = "tellr_app_owners"


def sql_create_owning_role(role: str = OWNING_ROLE) -> str:
    return f'CREATE ROLE "{role}" NOLOGIN'


def sql_grant_admin(role: str, granter_sp_id: str) -> str:
    return f'GRANT "{role}" TO "{granter_sp_id}" WITH ADMIN OPTION, INHERIT FALSE'


def sql_grant_member(role: str, sp_id: str) -> str:
    return f'GRANT "{role}" TO "{sp_id}" WITH INHERIT TRUE'


def sql_reassign_owned(role: str = OWNING_ROLE) -> str:
    return f'REASSIGN OWNED BY CURRENT_USER TO "{role}"'


def sql_alter_schema_owner(schema: str, role: str = OWNING_ROLE) -> str:
    return f'ALTER SCHEMA "{schema}" OWNER TO "{role}"'


def owning_role_exists(cur, role: str = OWNING_ROLE) -> bool:
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
    return cur.fetchone() is not None


def schema_owner(cur, schema: str) -> str | None:
    cur.execute(
        "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = %s",
        (schema,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def schema_is_shared_owned(cur, schema: str, role: str = OWNING_ROLE) -> bool:
    return schema_owner(cur, schema) == role
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_lakebase_shared_owner_sql.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/lakebase_shared_owner_sql.py tests/unit/test_lakebase_shared_owner_sql.py
git commit -m "feat(lakebase): SQL builders + guards for shared-owner model"
```

---

## Task 2: One-off transfer script (`lakebase_transfer_ownership.py`)

**Files:**
- Create: `scripts/lakebase_transfer_ownership.py`
- Test: `tests/unit/test_lakebase_transfer_ownership.py`

**Interfaces:**
- Consumes: `lakebase_shared_owner_sql` (Task 1); `databricks_tellr.deploy._get_lakebase_connection` (connects as the deployer) and `_resolve_production_endpoint` (added in this task).
- Produces:
  - `operator_setup(cur, owning_role, granter_sp_id, owner_sp_id) -> None`
  - `reassign_as_owner(cur, owning_role, schema) -> None`
  - `run_transfer(*, ws, owner_sp_id, granter_sp_id, sp_token, owning_role, schema, database, confirm) -> str` returning one of `"noop"`, `"transferred"`.
  - `main(argv=None) -> int`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_lakebase_transfer_ownership.py
from unittest.mock import MagicMock, patch
import scripts.lakebase_transfer_ownership as t


def _cur_with_owner(owner):
    cur = MagicMock()
    # schema_owner -> fetchone returns (owner,)
    cur.fetchone.return_value = (owner,) if owner else None
    return cur


def test_operator_setup_emits_create_and_grants():
    cur = MagicMock()
    cur.fetchone.return_value = None  # role does not exist yet
    t.operator_setup(cur, "tellr_app_owners", "gid", "oid")
    executed = [c.args[0] for c in cur.execute.call_args_list]
    assert 'CREATE ROLE "tellr_app_owners" NOLOGIN' in executed
    assert 'GRANT "tellr_app_owners" TO "gid" WITH ADMIN OPTION, INHERIT FALSE' in executed
    assert 'GRANT "tellr_app_owners" TO "oid" WITH INHERIT TRUE' in executed


def test_operator_setup_skips_create_when_role_exists():
    cur = MagicMock()
    cur.fetchone.return_value = (1,)  # role exists
    t.operator_setup(cur, "tellr_app_owners", "gid", "oid")
    executed = [c.args[0] for c in cur.execute.call_args_list]
    assert 'CREATE ROLE "tellr_app_owners" NOLOGIN' not in executed


def test_reassign_as_owner_emits_reassign_then_alter_schema():
    cur = MagicMock()
    t.reassign_as_owner(cur, "tellr_app_owners", "app_data_prod")
    executed = [c.args[0] for c in cur.execute.call_args_list]
    assert executed == [
        'REASSIGN OWNED BY CURRENT_USER TO "tellr_app_owners"',
        'ALTER SCHEMA "app_data_prod" OWNER TO "tellr_app_owners"',
    ]


def test_run_transfer_noops_when_already_shared_owned():
    ws = MagicMock()
    op_conn = MagicMock()
    op_conn.cursor.return_value.__enter__.return_value = _cur_with_owner("tellr_app_owners")
    with patch.object(t, "_open_operator_conn", return_value=op_conn), \
         patch.object(t, "_open_sp_conn") as sp_open:
        result = t.run_transfer(
            ws=ws, owner_sp_id="oid", granter_sp_id="gid", sp_token="tok",
            owning_role="tellr_app_owners", schema="app_data_prod",
            database="db-tellr", confirm=True,
        )
    assert result == "noop"
    sp_open.assert_not_called()  # never connect as the SP if nothing to do


def test_run_transfer_runs_setup_then_reassign():
    ws = MagicMock()
    op_cur = _cur_with_owner("some-prod-sp")   # not yet shared-owned
    op_conn = MagicMock()
    op_conn.cursor.return_value.__enter__.return_value = op_cur
    sp_cur = MagicMock()
    sp_conn = MagicMock()
    sp_conn.cursor.return_value.__enter__.return_value = sp_cur
    with patch.object(t, "_open_operator_conn", return_value=op_conn), \
         patch.object(t, "_open_sp_conn", return_value=sp_conn):
        result = t.run_transfer(
            ws=ws, owner_sp_id="oid", granter_sp_id="gid", sp_token="tok",
            owning_role="tellr_app_owners", schema="app_data_prod",
            database="db-tellr", confirm=True,
        )
    assert result == "transferred"
    op_executed = [c.args[0] for c in op_cur.execute.call_args_list]
    assert 'GRANT "tellr_app_owners" TO "gid" WITH ADMIN OPTION, INHERIT FALSE' in op_executed
    sp_executed = [c.args[0] for c in sp_cur.execute.call_args_list]
    assert 'REASSIGN OWNED BY CURRENT_USER TO "tellr_app_owners"' in sp_executed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_lakebase_transfer_ownership.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.lakebase_transfer_ownership'`

- [ ] **Step 3: Write the implementation**

```python
# scripts/lakebase_transfer_ownership.py
"""Run-once, idempotent transfer of app_data_prod ownership to tellr_app_owners.

Two identities in one run:
  * the operator (your ambient SDK/profile creds; needs CREATEROLE) creates the
    role and grants the granter SP (admin option) and the prod SP (inherit);
  * the prod SP (a UI-issued OAuth token) runs the REASSIGN — only the current
    owner can give ownership away.

Idempotent: no-op if the schema is already owned by tellr_app_owners. Prints a
dry-run summary and requires confirmation before mutating.
"""
from __future__ import annotations

import argparse
import sys

import psycopg2
from databricks.sdk import WorkspaceClient

# Reuse the deploy helpers for endpoint resolution + operator connection.
sys.path.insert(0, "packages/databricks-tellr")
from databricks_tellr.deploy import (  # noqa: E402
    _get_lakebase_connection,
    _resolve_production_endpoint,
)
from scripts.lakebase_shared_owner_sql import (  # noqa: E402
    OWNING_ROLE,
    owning_role_exists,
    schema_is_shared_owned,
    sql_alter_schema_owner,
    sql_create_owning_role,
    sql_grant_admin,
    sql_grant_member,
    sql_reassign_owned,
)


def operator_setup(cur, owning_role: str, granter_sp_id: str, owner_sp_id: str) -> None:
    if not owning_role_exists(cur, owning_role):
        cur.execute(sql_create_owning_role(owning_role))
    cur.execute(sql_grant_admin(owning_role, granter_sp_id))
    cur.execute(sql_grant_member(owning_role, owner_sp_id))


def reassign_as_owner(cur, owning_role: str, schema: str) -> None:
    cur.execute(sql_reassign_owned(owning_role))
    cur.execute(sql_alter_schema_owner(schema, owning_role))


def _open_operator_conn(ws, database):
    endpoint = _resolve_production_endpoint(ws, database)  # {"host","endpoint_name","type"}
    conn, _user = _get_lakebase_connection(ws, database, lakebase_result=endpoint)
    return conn


def _open_sp_conn(ws, database, owner_sp_id, sp_token):
    endpoint = _resolve_production_endpoint(ws, database)
    conn = psycopg2.connect(
        host=endpoint["host"], port=5432, user=owner_sp_id, password=sp_token,
        dbname="databricks_postgres", sslmode="require",
    )
    conn.autocommit = True
    return conn


def run_transfer(*, ws, owner_sp_id, granter_sp_id, sp_token, owning_role,
                 schema, database, confirm) -> str:
    op_conn = _open_operator_conn(ws, database)
    try:
        with op_conn.cursor() as cur:
            if schema_is_shared_owned(cur, schema, owning_role):
                print(f"Schema {schema} already owned by {owning_role} — nothing to do.")
                return "noop"
            print(f"DRY RUN: will create/verify role {owning_role}, grant granter SP "
                  f"{granter_sp_id} (admin option), grant prod SP {owner_sp_id}, then "
                  f"REASSIGN all {owner_sp_id}-owned objects + schema {schema} to "
                  f"{owning_role}.")
            if not confirm:
                print("Re-run with --yes to apply.")
                return "noop"
            operator_setup(cur, owning_role, granter_sp_id, owner_sp_id)
    finally:
        op_conn.close()

    sp_conn = _open_sp_conn(ws, database, owner_sp_id, sp_token)
    try:
        with sp_conn.cursor() as cur:
            reassign_as_owner(cur, owning_role, schema)
    finally:
        sp_conn.close()
    print(f"Transfer complete: {schema} now owned by {owning_role}.")
    return "transferred"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Transfer app_data_prod ownership to a shared role")
    p.add_argument("--owner-sp-id", required=True, help="Current owner (prod app SP) client id")
    p.add_argument("--granter-sp-id", required=True, help="Dedicated granter SP client id")
    p.add_argument("--sp-token", required=True, help="UI-issued OAuth token for the prod SP")
    p.add_argument("--owning-role", default=OWNING_ROLE)
    p.add_argument("--schema", default="app_data_prod")
    p.add_argument("--database", default="db-tellr")
    p.add_argument("--yes", action="store_true", help="Apply (omit for dry-run)")
    args = p.parse_args(argv)

    ws = WorkspaceClient()
    result = run_transfer(
        ws=ws, owner_sp_id=args.owner_sp_id, granter_sp_id=args.granter_sp_id,
        sp_token=args.sp_token, owning_role=args.owning_role, schema=args.schema,
        database=args.database, confirm=args.yes,
    )
    return 0 if result in ("noop", "transferred") else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Add `_resolve_production_endpoint` to `deploy.py`**

This helper resolves the autoscaling production branch's host + endpoint so the
transfer script can connect. Add near `_get_lakebase_connection` in
`packages/databricks-tellr/databricks_tellr/deploy.py`:

```python
def _resolve_production_endpoint(
    ws: WorkspaceClient, project_name: str, branch_name: str = "production",
) -> dict[str, Any]:
    """Resolve an autoscaling branch's host + endpoint_name for a psycopg2 connect.

    Returns a dict shaped like _get_or_create_lakebase()'s autoscaling result so
    it can be passed straight to _get_lakebase_connection(..., lakebase_result=...).
    """
    branch_path = f"projects/{project_name}/branches/{branch_name}"
    endpoints = list(ws.postgres.list_endpoints(parent=branch_path))
    ready = next((e for e in endpoints if e.status and e.status.host), None)
    if not ready:
        raise DeploymentError(
            f"no ready endpoint for {branch_path} in project {project_name}"
        )
    return {
        "type": "autoscaling",
        "host": ready.status.host,
        "endpoint_name": ready.name,
    }
```

> If `list_endpoints`'s exact field names differ in the installed SDK, align them
> with the existing endpoint-poll code in `_create_branch_from`
> (`deploy.py:1129`), which already reads ready endpoints for branches.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_lakebase_transfer_ownership.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add scripts/lakebase_transfer_ownership.py tests/unit/test_lakebase_transfer_ownership.py packages/databricks-tellr/databricks_tellr/deploy.py
git commit -m "feat(lakebase): one-off ownership transfer script (two-identity, idempotent)"
```

---

## Task 3: Grant-job entry point (`lakebase_grant_owner_role.py`)

**Files:**
- Create: `scripts/lakebase_grant_owner_role.py`
- Test: `tests/unit/test_lakebase_grant_owner_role.py`

**Interfaces:**
- Consumes: `lakebase_shared_owner_sql.sql_grant_member` (Task 1).
- Produces:
  - `grant_member(cur, owning_role: str, new_sp_id: str) -> None`
  - `run_grant(*, ws, new_sp_id, host, endpoint_name, granter_sp_id, owning_role) -> None`
  - `main(argv=None) -> int`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_lakebase_grant_owner_role.py
from unittest.mock import MagicMock, patch
import scripts.lakebase_grant_owner_role as g


def test_grant_member_emits_inherit_true_grant():
    cur = MagicMock()
    g.grant_member(cur, "tellr_app_owners", "new-sp")
    cur.execute.assert_called_once_with('GRANT "tellr_app_owners" TO "new-sp" WITH INHERIT TRUE')


def test_run_grant_connects_as_granter_and_grants():
    ws = MagicMock()
    ws.postgres.generate_database_credential.return_value.token = "tok"
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    with patch.object(g.psycopg2, "connect", return_value=conn) as connect:
        g.run_grant(
            ws=ws, new_sp_id="new-sp", host="h.example", endpoint_name="ep",
            granter_sp_id="gid", owning_role="tellr_app_owners",
        )
    ws.postgres.generate_database_credential.assert_called_once_with(endpoint="ep")
    kwargs = connect.call_args.kwargs
    assert kwargs["host"] == "h.example" and kwargs["user"] == "gid" and kwargs["password"] == "tok"
    cur.execute.assert_called_once_with('GRANT "tellr_app_owners" TO "new-sp" WITH INHERIT TRUE')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_lakebase_grant_owner_role.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# scripts/lakebase_grant_owner_role.py
"""Grant-job entry point: add one app SP to tellr_app_owners on a branch.

Runs as the granter SP (the job's run_as identity). Connects to the target
branch endpoint and issues an idempotent GRANT. Parameters arrive as argv.
"""
from __future__ import annotations

import argparse

import psycopg2
from databricks.sdk import WorkspaceClient

from scripts.lakebase_shared_owner_sql import OWNING_ROLE, sql_grant_member


def grant_member(cur, owning_role: str, new_sp_id: str) -> None:
    cur.execute(sql_grant_member(owning_role, new_sp_id))


def run_grant(*, ws, new_sp_id, host, endpoint_name, granter_sp_id, owning_role) -> None:
    cred = ws.postgres.generate_database_credential(endpoint=endpoint_name)
    conn = psycopg2.connect(
        host=host, port=5432, user=granter_sp_id, password=cred.token,
        dbname="databricks_postgres", sslmode="require",
    )
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            grant_member(cur, owning_role, new_sp_id)
    finally:
        conn.close()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Grant an app SP into the shared owning role")
    p.add_argument("--new-sp-id", required=True)
    p.add_argument("--host", required=True)
    p.add_argument("--endpoint-name", required=True)
    p.add_argument("--granter-sp-id", required=True)
    p.add_argument("--owning-role", default=OWNING_ROLE)
    args = p.parse_args(argv)

    ws = WorkspaceClient()
    run_grant(
        ws=ws, new_sp_id=args.new_sp_id, host=args.host,
        endpoint_name=args.endpoint_name, granter_sp_id=args.granter_sp_id,
        owning_role=args.owning_role,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_lakebase_grant_owner_role.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/lakebase_grant_owner_role.py tests/unit/test_lakebase_grant_owner_role.py
git commit -m "feat(lakebase): grant-job entry point (grant SP into shared owner on a branch)"
```

---

## Task 4: Keep new objects shared-owned in migrations

**Files:**
- Modify: `src/core/database.py` (add `_reassign_new_objects_to_shared_owner`; call it at the end of `_run_migrations`'s `with engine.begin()` block, after `_migrate_image_assets_tags_json_to_jsonb`, `database.py:522`)
- Test: `tests/unit/test_reassign_shared_owner_migration.py`

**Interfaces:**
- Produces: `_reassign_new_objects_to_shared_owner(conn, is_sqlite: bool, owning_role: str = "tellr_app_owners") -> None`
- Behaviour: no-op on SQLite; no-op when the role does not exist; otherwise runs `REASSIGN OWNED BY CURRENT_USER TO "<role>"` inside a SAVEPOINT (`conn.begin_nested()`) so a failure cannot abort the outer migration transaction.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_reassign_shared_owner_migration.py
from unittest.mock import MagicMock
from src.core.database import _reassign_new_objects_to_shared_owner


def _conn_role_exists(exists: bool):
    conn = MagicMock()
    conn.execute.return_value.scalar.return_value = 1 if exists else None
    return conn


def test_noop_on_sqlite():
    conn = MagicMock()
    _reassign_new_objects_to_shared_owner(conn, is_sqlite=True)
    conn.execute.assert_not_called()


def test_noop_when_role_absent():
    conn = _conn_role_exists(False)
    _reassign_new_objects_to_shared_owner(conn, is_sqlite=False)
    sql = " ".join(str(c.args[0]) for c in conn.execute.call_args_list)
    assert "REASSIGN OWNED" not in sql
    conn.begin_nested.assert_not_called()


def test_reassign_runs_in_savepoint_when_role_present():
    conn = _conn_role_exists(True)
    _reassign_new_objects_to_shared_owner(conn, is_sqlite=False)
    conn.begin_nested.assert_called_once()
    sql = " ".join(str(c.args[0]) for c in conn.execute.call_args_list)
    assert 'REASSIGN OWNED BY CURRENT_USER TO "tellr_app_owners"' in sql
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_reassign_shared_owner_migration.py -v`
Expected: FAIL with `ImportError: cannot import name '_reassign_new_objects_to_shared_owner'`

- [ ] **Step 3: Write the implementation**

Add to `src/core/database.py` (mirrors the `_ensure_llm_judge_backend_default` SAVEPOINT pattern):

```python
def _reassign_new_objects_to_shared_owner(
    conn, is_sqlite: bool, owning_role: str = "tellr_app_owners"
) -> None:
    """Re-home objects this connection's role just created onto the shared owner.

    No-op on SQLite and when the owning role is absent (static-schema envs).
    Wrapped in a SAVEPOINT so a failure cannot poison the outer migration
    transaction. Idempotent: REASSIGN OWNED is a no-op when nothing is owned.
    """
    from sqlalchemy import text

    if is_sqlite:
        return
    exists = conn.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": owning_role}
    ).scalar()
    if not exists:
        return
    logger.info(f"Migration: reassigning new objects to shared owner {owning_role}")
    with conn.begin_nested():
        conn.execute(text(f'REASSIGN OWNED BY CURRENT_USER TO "{owning_role}"'))
```

Then add the call as the last statement inside the `with engine.begin() as conn:`
block in `_run_migrations` (immediately after the
`_migrate_image_assets_tags_json_to_jsonb(...)` call at `database.py:522`):

```python
        # --- keep newly created objects owned by the shared role (prod forks) ---
        _reassign_new_objects_to_shared_owner(conn, is_sqlite)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_reassign_shared_owner_migration.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full DB test module to check for regressions**

Run: `pytest tests/unit/ -k "database or migration" -v`
Expected: PASS (no regressions in existing migration tests)

- [ ] **Step 6: Commit**

```bash
git add src/core/database.py tests/unit/test_reassign_shared_owner_migration.py
git commit -m "feat(db): reassign new objects to tellr_app_owners at end of migrations"
```

---

## Task 5: Trigger the grant job from `deploy_local create`

**Files:**
- Modify: `scripts/deploy_local.py` (add `_trigger_owner_grant_job`; call it in `create_local` right after the `_ensure_sp_autoscaling_role(...)` block, `deploy_local.py:447-449`, when `branch_from_env` is set)
- Modify: `config/deployment.yaml` (`devloop.lakebase.owner_grant_job_id`)
- Test: `tests/unit/test_deploy_local_owner_grant.py`

**Interfaces:**
- Consumes: `lakebase_result` (has `host`, `endpoint_name`), the new app `client_id`, and `config["lakebase"]["owner_grant_job_id"]`.
- Produces: `_trigger_owner_grant_job(ws, job_id, new_sp_id, host, endpoint_name) -> None` — runs the job and waits; raises `DeploymentError` if the run does not succeed.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_deploy_local_owner_grant.py
from unittest.mock import MagicMock
import pytest
import scripts.deploy_local as d


def test_trigger_owner_grant_job_runs_and_waits():
    ws = MagicMock()
    run = MagicMock()
    run.state.result_state = "SUCCESS"
    ws.jobs.run_now.return_value.result.return_value = run
    d._trigger_owner_grant_job(ws, 123, "new-sp", "h.example", "ep")
    _, kwargs = ws.jobs.run_now.call_args
    assert kwargs["job_id"] == 123
    params = kwargs["python_params"]
    assert "--new-sp-id" in params and "new-sp" in params
    assert "--host" in params and "h.example" in params
    assert "--endpoint-name" in params and "ep" in params


def test_trigger_owner_grant_job_raises_on_failure():
    ws = MagicMock()
    run = MagicMock()
    run.state.result_state = "FAILED"
    ws.jobs.run_now.return_value.result.return_value = run
    with pytest.raises(d.DeploymentError):
        d._trigger_owner_grant_job(ws, 123, "new-sp", "h.example", "ep")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_deploy_local_owner_grant.py -v`
Expected: FAIL with `AttributeError: module 'scripts.deploy_local' has no attribute '_trigger_owner_grant_job'`

- [ ] **Step 3: Write the implementation**

Add to `scripts/deploy_local.py` (imports `DeploymentError` already available there via the deploy module):

```python
def _trigger_owner_grant_job(ws, job_id, new_sp_id, host, endpoint_name) -> None:
    """Run the serverless grant job (as the granter SP) to add new_sp_id to the
    shared owning role on this branch, and wait for it. Raises on failure so a
    deploy never proceeds with an SP that cannot migrate its fork."""
    print(f"   Granting SP {new_sp_id} into shared owning role via job {job_id}...")
    run = ws.jobs.run_now(
        job_id=job_id,
        python_params=[
            "--new-sp-id", new_sp_id,
            "--host", host,
            "--endpoint-name", endpoint_name,
        ],
    ).result()
    state = run.state.result_state if run.state else None
    if str(state) != "SUCCESS" and getattr(state, "value", None) != "SUCCESS":
        raise DeploymentError(
            f"owner-grant job {job_id} did not succeed (state={state}); "
            f"SP {new_sp_id} cannot migrate its fork"
        )
    print("   SP granted into shared owning role")
```

Then call it in `create_local`, immediately after the
`_ensure_sp_autoscaling_role(...)` block (`deploy_local.py:447-449`):

```python
                _ensure_sp_autoscaling_role(
                    ws, lakebase_name, client_id, branch_name=sp_branch
                )
                grant_job_id = config.get("lakebase", {}).get("owner_grant_job_id")
                if branch_from_env and grant_job_id and client_id:
                    _trigger_owner_grant_job(
                        ws, grant_job_id, client_id,
                        lakebase_result["host"], lakebase_result["endpoint_name"],
                    )
```

- [ ] **Step 4: Add the job id to `config/deployment.yaml`**

Under `devloop.lakebase`, add (value filled in by Task 7):

```yaml
    owner_grant_job_id: 0            # serverless grant job id (set in Task 7)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_deploy_local_owner_grant.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Run deploy_local's existing unit suites for regressions**

Run: `pytest tests/unit/ -k "deploy_local" -v`
Expected: PASS (no regressions)

- [ ] **Step 7: Commit**

```bash
git add scripts/deploy_local.py config/deployment.yaml tests/unit/test_deploy_local_owner_grant.py
git commit -m "feat(deploy): trigger serverless owner-grant job for new devloop SPs"
```

---

## Task 6: Create the granter SP + its connectable PG role (operational)

No new application code. This provisions the standing identity. Run against a
**throwaway autoscaling project first** (Task 8 validates), then prod (Task 9).

- [ ] **Step 1: Create the granter service principal**

```bash
databricks service-principals create --display-name "tellr-lakebase-granter" --profile tellr-dev
```

Record the SP's `applicationId` (used as `--granter-sp-id` and as the job's
`run_as`). Expected: JSON with `applicationId` and `id`.

- [ ] **Step 2: Create the granter SP's connectable Postgres role on production**

The granter SP must be able to *connect* to branch endpoints. Create its
`LAKEBASE_OAUTH_V1` role on the production branch (inherited by every fork).
Use a short Python snippet (the existing `_ensure_sp_autoscaling_role` hardcodes
`DATABRICKS_SUPERUSER` membership, which the granter must NOT have — so create it
directly):

```python
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.database import (
    Role, RoleRoleSpec, RoleIdentityType, RoleAuthMethod,
)
ws = WorkspaceClient(profile="tellr-dev")
GRANTER = "<granter-application-id>"
branch_path = "projects/db-tellr/branches/production"
ws.postgres.create_role(
    parent=branch_path,
    role=Role(spec=RoleRoleSpec(
        postgres_role=GRANTER,
        identity_type=RoleIdentityType.SERVICE_PRINCIPAL,
        auth_method=RoleAuthMethod.LAKEBASE_OAUTH_V1,
    )),
    role_id=f"sp-{GRANTER}",
).wait()
```

Expected: role created (no superuser membership). Verify: `ws.postgres.get_role(name=f"{branch_path}/roles/sp-{GRANTER}")` returns it with `auth_method == LAKEBASE_OAUTH_V1`.

> The granter SP's `tellr_app_owners` membership (`WITH ADMIN OPTION, INHERIT
> FALSE`) is granted by the transfer script's operator phase (Task 2 /
> Task 9) — not here.

- [ ] **Step 2 (gate):** Do not commit secrets. Record the SP id in the team's secret store / runbook, not in the repo.

---

## Task 7: Deploy the serverless grant job (operational)

Creates the Databricks job that runs `scripts/lakebase_grant_owner_role.py` as the
granter SP, on serverless, runnable by anyone.

- [ ] **Step 1: Make the entry script reachable by the job**

Sync the repo `scripts/` to the workspace so the job can run the file as a
serverless `python` task (or package it in the app wheel). For a workspace-file
task:

```bash
databricks sync scripts /Workspace/Users/robert.whiffin@databricks.com/.tellr/scripts --profile tellr-dev
```

Expected: files synced, including `lakebase_grant_owner_role.py` and
`lakebase_shared_owner_sql.py`.

- [ ] **Step 2: Create the serverless job (run_as granter SP, open run-ACL)**

```python
from databricks.sdk import WorkspaceClient
from databricks.sdk.service import jobs
ws = WorkspaceClient(profile="tellr-dev")
created = ws.jobs.create(
    name="tellr-lakebase-owner-grant",
    tasks=[jobs.Task(
        task_key="grant",
        spark_python_task=jobs.SparkPythonTask(
            python_file="/Workspace/Users/robert.whiffin@databricks.com/.tellr/scripts/lakebase_grant_owner_role.py",
            parameters=["--granter-sp-id", "<granter-application-id>"],
        ),
        environment_key="default",
    )],
    environments=[jobs.JobEnvironment(environment_key="default", spec=jobs.Environment(
        client="1", dependencies=["psycopg2-binary", "databricks-sdk"],
    ))],
    run_as=jobs.JobRunAs(service_principal_name="<granter-application-id>"),
)
print(created.job_id)
```

Expected: prints the new `job_id`.

> Field names (`SparkPythonTask`/serverless environment) may need aligning with
> the installed SDK version; the invariants are: **serverless compute**,
> **`run_as` = granter SP**, entry file = `lakebase_grant_owner_role.py`, and the
> static `--granter-sp-id` parameter. Per-run params (`--new-sp-id`, `--host`,
> `--endpoint-name`) are appended by `run_now(python_params=...)` from Task 5.

- [ ] **Step 3: Open the run-ACL**

```bash
databricks permissions set jobs <job_id> --json '{"access_control_list":[{"group_name":"users","permission_level":"CAN_MANAGE_RUN"}]}' --profile tellr-dev
```

Expected: anyone in `users` can trigger the job.

- [ ] **Step 4: Record the job id**

Set `devloop.lakebase.owner_grant_job_id: <job_id>` in `config/deployment.yaml`
(replacing the `0` placeholder from Task 5).

```bash
git add config/deployment.yaml
git commit -m "chore(deploy): wire devloop to the lakebase owner-grant job id"
```

---

## Task 8: Validate the whole model on a throwaway project (operational gate)

Prove every fork-specific assumption on a throwaway autoscaling project before
prod. **Do not proceed to Task 9 until all pass.**

- [ ] **Step 1: Confirm Postgres major version ≥ 16**

Connect to the throwaway and run `SHOW server_version;`. Expected: ≥ 16 (the
`WITH ... INHERIT TRUE/FALSE` grant syntax requires it). If < 16, stop and revise
the grant syntax in Task 1.

- [ ] **Step 2: Run the transfer script against the throwaway**

Create a throwaway role-owned schema seeded with a couple of tables owned by a
"prod-like" SP, then:

```bash
python -m scripts.lakebase_transfer_ownership \
  --owner-sp-id <throwaway-owner-sp> --granter-sp-id <granter-sp> \
  --sp-token <UI-issued token for the throwaway owner SP> \
  --schema <throwaway_schema> --database <throwaway-project> --yes
```

Expected: `Transfer complete`. Re-run without `--yes`: prints the already-owned
no-op. Validates the UI-token connect-as-owner path and idempotency.

- [ ] **Step 3: Validate granter admin-option is effective on a fork**

Fork a branch off the throwaway's transferred branch. Run the grant job (or
`run_grant` directly) as the granter SP against the **fork** for a fresh test SP.
Expected: `GRANT ... WITH INHERIT TRUE` succeeds on the fork — confirms the
granter SP's admin membership, established on the source, is inherited by the
fork (validation item 1) and that the granter SP can connect to an arbitrary
branch endpoint (validation item 2).

- [ ] **Step 4: Validate a freshly-granted SP can ALTER an inherited table on its fork**

Authenticating **as the freshly-granted test SP** (not `SET ROLE`), run
`ALTER TABLE <inherited_table> ADD COLUMN probe int` on the fork. Expected:
succeeds (validation item 3). Drop the probe column.

- [ ] **Step 5: Validate the migration REASSIGN step**

As the test SP on the fork, create a new table, then run
`REASSIGN OWNED BY CURRENT_USER TO "tellr_app_owners"`. Expected: succeeds and
the new table's owner becomes `tellr_app_owners`. Confirms the Task 4 step on a
real fork. Run again with nothing new owned — expected: clean no-op.

- [ ] **Step 6: Record results**

Note pass/fail for each validation item in the team runbook /
`memory/lakebase_branch_permissions.md`. All must pass to proceed.

---

## Task 9: Prod rollout + end-to-end devloop fork migration (operational)

- [ ] **Step 1: Merge the code tasks (1–5, 7) to main** via PR; confirm CI green
  (`pytest tests/unit`).

- [ ] **Step 2: Run the transfer against prod**

```bash
python -m scripts.lakebase_transfer_ownership \
  --owner-sp-id 161834b3-c54d-4b24-82c4-8f0166c191f4 \
  --granter-sp-id <granter-application-id> \
  --sp-token <UI-issued token for the prod app SP> \
  --schema app_data_prod --database db-tellr --yes
```

Expected: dry-run summary, then `Transfer complete: app_data_prod now owned by
tellr_app_owners.` Verify with `schema_owner` / `\dn+ app_data_prod`.

- [ ] **Step 3: Confirm prod app still healthy**

Trigger a normal prod migration cycle (next prod deploy) and confirm
`_reassign_new_objects_to_shared_owner` runs clean (prod SP is now an INHERIT
member; it can `ALTER` the role-owned tables). Expected: app reaches RUNNING, no
`must be owner of table`, no aborted transaction.

- [ ] **Step 4: End-to-end devloop fork ALTER migration**

Publish a dev `.devN` whose build introduces a **genuinely new** `ALTER`
migration on an existing `app_data_prod` table. Deploy it:

```bash
gh workflow run publish-dev.yml --ref <branch>
./scripts/deploy_local.sh create --env devloop --instance ownertest \
  --profile tellr-dev --from-pypi <version>
```

Expected: the grant job runs during `create`, the app reaches RUNNING, and the
new `ALTER` migration applies on the fork — the exact case that fails today.
Teardown: `./scripts/deploy_local.sh delete --env devloop --instance ownertest --profile tellr-dev`.

---

## Task 10: Update `dev-deploy.md` (current-state)

**Files:**
- Modify: `docs/technical/dev-deploy.md` (the "Migration limitation" block, lines 91-95)

- [ ] **Step 1: Replace the limitation note**

Replace the `**Migration limitation:**` paragraph with a current-state statement
that fork migrations work, pointing to the ownership doc:

```markdown
Each instance is a full prod mirror: it can create tables, read/write prod data,
and run `ALTER`-bearing migrations against inherited prod tables. Ownership of
`app_data_prod` lives on the shared `tellr_app_owners` role, which the deploy
grants each instance's service principal into — see
`docs/technical/lakebase-table-ownership.md`.
```

- [ ] **Step 2: Commit**

```bash
git add docs/technical/dev-deploy.md
git commit -m "docs(dev-deploy): fork migrations work under the shared-owner model"
```

---

## Self-review notes

- **Spec coverage:** owning role (T1/T2/T9), INHERIT-vs-ADMIN split (T1 builders, T2 setup, T6/T7 granter), granter SP (T6), serverless grant job + open ACL (T7), PG-grant-on-branch path (T3), deploy wiring (T5), stay-shared migration (T4), one-off transfer as prod SP w/ UI token + dry-run/confirm/idempotency (T2/T9), validation checklist (T8), no Databricks group / no human membership (enforced by absence — nothing grants humans), serverless pinned (T7), technical doc current-state (already shipped; T10 updates dev-deploy.md).
- **Type consistency:** `OWNING_ROLE`/`sql_grant_member`/`sql_grant_admin` defined in T1 are the exact names consumed in T2 and T3; `lakebase_result["host"]`/`["endpoint_name"]` keys match `_get_or_create_lakebase`'s autoscaling result and `_resolve_production_endpoint` (T2).
- **Known SDK-shape risks (flagged inline, resolved during implementation against the installed SDK):** `ws.postgres.list_endpoints` field names (T2 Step 4), serverless job task/environment fields (T7 Step 2), and `run.state.result_state` value type (T5 handles both enum and str).
