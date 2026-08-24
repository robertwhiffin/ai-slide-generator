"""Secret-backed Fernet master key helpers for the Tellr deploy tool.

The Lakebase-backed path (SDR-4437 CRITICAL-3) remains the default; everything
here serves the opt-in path that stores the key in a Databricks secret and
attaches it to the app as a secret resource. Design and the live-verified
platform behaviour this relies on:
docs/superpowers/specs/2026-08-20-secret-backed-fernet-key-design.md

Deliberately a separate module: deploy.py is already very large, and keeping
these helpers here makes them unit-testable without mocking a whole deployment.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from cryptography.fernet import Fernet
from databricks.sdk.service.workspace import ScopeBackendType

logger = logging.getLogger(__name__)

#: Apps secret-resource key, and therefore the injected env var name. Verified
#: that uppercase-underscore resource keys are accepted.
RESOURCE_KEY = "TELLR_ENCRYPTION_KEY"

#: Default secret key name. Spaces are actually accepted by the API, but a
#: hyphenated name keeps it consistent with the resource key.
DEFAULT_SECRET_KEY = "tellr-encryption-key"


class SecretKeyError(Exception):
    """Raised for any recoverable secret-mode setup failure."""


def preflight_scope(ws: Any, scope: str) -> None:
    """Ensure *scope* exists and is usable, before any key material is written.

    Runs before the app is created or updated so a failure leaves nothing
    half-done. Creates the scope when absent, with ``initial_manage_principal``
    omitted so the creator is sole manager — explicitly NOT ``"users"``, which
    would grant every workspace user MANAGE on the scope holding the key.
    """
    existing = {s.name: s for s in ws.secrets.list_scopes()}
    if scope in existing:
        backend = existing[scope].backend_type
        if backend is not None and backend != ScopeBackendType.DATABRICKS:
            raise SecretKeyError(
                f"Secret scope '{scope}' is {backend} backed. Secret mode writes "
                f"the key and reads it back to verify; Key Vault backed scopes are "
                f"written and read through Key Vault, not this API. Use a "
                f"Databricks-backed scope."
            )
        return

    try:
        ws.secrets.create_scope(scope=scope)
    except Exception as exc:  # noqa: BLE001 — mapped to actionable guidance below
        text = str(exc).upper()
        manual = f"databricks secrets create-scope {scope}"
        if "LIMIT" in text:
            raise SecretKeyError(
                f"Cannot create secret scope '{scope}': this workspace is at its "
                f"secret-scope limit (1,000 by default, raisable on request). Pass "
                f"an existing scope via encryption_secret_scope instead."
            ) from exc
        if "UNAUTHORIZED" in text or "PERMISSION" in text or "BAD_REQUEST" in text:
            raise SecretKeyError(
                f"Not permitted to create secret scope '{scope}'. Ask a workspace "
                f"admin to run `{manual}` and grant you MANAGE on it, then re-run."
            ) from exc
        raise SecretKeyError(
            f"Could not create secret scope '{scope}': {exc}. Create it manually "
            f"with `{manual}` and re-run."
        ) from exc
    logger.info("Created secret scope %s (creator is sole manager)", scope)


def preflight_lakebase_privileges(cur: Any, schema_name: str) -> None:
    """Verify the deploying human can read and delete the encryption_keys row.

    On installs where the app SP created the table and ``REASSIGN OWNED`` rehomed
    it to ``tellr_app_owners``, a deployer outside ``databricks_superuser`` has
    neither privilege. Without this probe a denied SELECT would be indistinguishable
    from "no row", and the relocate ladder would mint a fresh key over live
    ciphertext.
    """
    table = f"{schema_name}.encryption_keys"
    missing = []
    for priv in ("SELECT", "DELETE"):
        cur.execute(
            "SELECT has_table_privilege(current_user, %s, %s)", (table, priv)
        )
        row = cur.fetchone()
        if not row or not row[0]:
            missing.append(priv)
    if missing:
        raise SecretKeyError(
            f"The deploying identity lacks {' and '.join(missing)} on {table}, so "
            f"the key cannot be safely relocated out of Lakebase. Grant those "
            f"privileges (or run the deploy as an identity in databricks_superuser) "
            f"and re-run. Nothing has been changed."
        )
