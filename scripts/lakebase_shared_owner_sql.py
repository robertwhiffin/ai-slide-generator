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
