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
