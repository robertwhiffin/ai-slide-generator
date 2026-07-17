"""Validation for identifiers interpolated into Postgres DDL (SDR-4437 MEDIUM-5).

Both inputs are config/platform-derived today (schema_name from deploy
config, client_id from the app SP), so this is hardening against future
user-derived values, not a live injection.

Lives only in this (deploy-tool) distribution: the app distribution has no
DDL-identifier interpolation site once the dead setup_lakebase_schema is
removed, so there is no counterpart to keep in sync.
"""

import re

_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# UUID (App SP client id) OR all-digits (str(service_principal_id) fallback
# in _get_app_client_id). Both are injection-safe charsets.
_CLIENT_ID_RE = re.compile(
    r"^(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|[0-9]+)$"
)


def validate_schema_name(schema: str) -> str:
    """Return *schema* if it is a safe Postgres schema identifier; else raise."""
    if not isinstance(schema, str) or not _SCHEMA_RE.match(schema):
        raise ValueError(f"Invalid Postgres schema name: {schema!r}")
    return schema


def validate_client_id(client_id: str) -> str:
    """Return *client_id* if it is a UUID or numeric SP id; else raise."""
    if not isinstance(client_id, str) or not _CLIENT_ID_RE.match(client_id):
        raise ValueError(
            f"Invalid service-principal client id (expected UUID or numeric id): "
            f"{client_id!r}"
        )
    return client_id
