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
