"""Grant-job entry point: add one app SP to tellr_app_owners on a branch.

Runs as the granter SP (the job's run_as identity). Connects to the target
branch endpoint and issues an idempotent GRANT. Parameters arrive as argv.
"""
from __future__ import annotations

import argparse

import psycopg2
from databricks.sdk import WorkspaceClient

# Import works both as part of the `scripts` package (unit tests) and as a
# standalone file deployed to a Databricks job, where only the file's own
# directory is on sys.path (sibling import).
try:
    from scripts.lakebase_shared_owner_sql import OWNING_ROLE, sql_grant_member
except ModuleNotFoundError:  # deployed job: sibling module on sys.path
    from lakebase_shared_owner_sql import OWNING_ROLE, sql_grant_member


def grant_member(cur, owning_role: str, new_sp_id: str) -> None:
    cur.execute(sql_grant_member(owning_role, new_sp_id))


def run_grant(*, ws, new_sp_id, host, endpoint_name, owning_role, granter_sp_id=None) -> None:
    # The job runs AS the granter SP, so its own identity IS the Postgres user to
    # connect as. Deriving it (rather than requiring --granter-sp-id) means the
    # per-run params from deploy_local's run_now — which override the task's
    # static params — are sufficient. An explicit granter_sp_id still wins (tests).
    if not granter_sp_id:
        granter_sp_id = ws.current_user.me().user_name
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
    # Optional: the job runs as the granter SP, so its identity is used by
    # default. An explicit value overrides (e.g. running outside the job).
    p.add_argument("--granter-sp-id", default=None)
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
    # Only raise SystemExit on a non-zero code. `raise SystemExit(0)` is a
    # normal clean exit for a CLI, but a Databricks python task treats ANY
    # SystemExit as an uncaught exception and marks the run FAILED — so on
    # success we simply fall through.
    _rc = main()
    if _rc:
        raise SystemExit(_rc)
