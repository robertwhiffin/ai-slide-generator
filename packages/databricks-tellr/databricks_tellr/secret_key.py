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
import time
from typing import Any

import requests
from cryptography.fernet import Fernet
from databricks.sdk.service.apps import (
    App,
    AppResource,
    AppResourceSecret,
    AppResourceSecretSecretPermission,
)
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


def _looks_absent(exc: Exception) -> bool:
    return "RESOURCE_DOES_NOT_EXIST" in str(exc).upper()


def read_secret_key(ws: Any, scope: str, key: str) -> str | None:
    """Return the Fernet key stored at *(scope, key)*, or None if truly absent.

    ``GetSecretResponse.value`` is base64 (the API returns the value "in its byte
    representation"), so it must be decoded. Any error other than a genuine
    not-found is raised: treating a permission denial as absence would let the
    caller overwrite a secret that is already protecting live ciphertext.
    """
    try:
        resp = ws.secrets.get_secret(scope=scope, key=key)
    except Exception as exc:  # noqa: BLE001
        if _looks_absent(exc):
            return None
        raise SecretKeyError(
            f"Could not read secret {scope}/{key}: {exc}. This is not a "
            f"'not found' error, so it is most likely a permission problem — "
            f"refusing to continue rather than risk overwriting a key that may "
            f"already protect stored credentials."
        ) from exc

    if resp is None or not resp.value:
        return None
    value = base64.b64decode(resp.value).decode()
    try:
        Fernet(value.encode())
    except (ValueError, TypeError) as exc:
        raise SecretKeyError(
            f"Secret {scope}/{key} exists but is not a valid Fernet key. Refusing "
            f"to use or overwrite it — inspect it manually and resolve."
        ) from exc
    return value


def write_and_verify_secret_key(ws: Any, scope: str, key: str, value: str) -> None:
    """Write *value* to *(scope, key)* and confirm it reads back identically.

    The read-back is the gate that later permits deleting the Lakebase row: no
    key material is removed from Lakebase until the secret has been proven
    present and correct.
    """
    ws.secrets.put_secret(scope=scope, key=key, string_value=value)
    stored = read_secret_key(ws, scope, key)
    if stored != value:
        raise SecretKeyError(
            f"Secret {scope}/{key} failed read-back verification after write. "
            f"The Lakebase key row has NOT been touched. Resolve the secret "
            f"store problem and re-run."
        )
    logger.info("Secret %s/%s written and verified", scope, key)


def build_secret_resource(scope: str, key: str) -> AppResource:
    """Build the Apps secret resource that injects the key.

    No ``put_acl`` is needed anywhere: attaching this resource auto-grants the
    app's service principal READ on the scope (verified live). Adding one would
    require MANAGE on the scope, which is what made fork creation unworkable.
    """
    return AppResource(
        name=RESOURCE_KEY,
        secret=AppResourceSecret(
            scope=scope, key=key,
            permission=AppResourceSecretSecretPermission.READ,
        ),
    )


def resolve_key_for_create(ws: Any, scope: str, key: str) -> str:
    """Return the key a fresh install should use, writing one if none exists."""
    existing = read_secret_key(ws, scope, key)
    if existing:
        logger.info("Reusing the existing Fernet key at %s/%s", scope, key)
        return existing
    generated = Fernet.generate_key().decode()
    write_and_verify_secret_key(ws, scope, key, generated)
    return generated


def read_lakebase_key(cur: Any, schema_name: str) -> str | None:
    """Read the existing Fernet key row, failing closed on anything but absence.

    Only a genuinely missing table or row yields None. A permission error must
    abort: on installs where the app SP owns the table, a deployer outside
    ``databricks_superuser`` gets denied, and treating that as "no row" would walk
    the ladder to case 4 and mint a fresh key over live ciphertext.
    """
    try:
        cur.execute(
            f'SELECT key_value FROM "{schema_name}".encryption_keys WHERE id = 1'
        )
    except Exception as exc:  # noqa: BLE001
        text = str(exc).lower()
        if "does not exist" in text and "relation" in text:
            return None
        raise SecretKeyError(
            f"Could not read the existing key from {schema_name}.encryption_keys: "
            f"{exc}. This is not a missing-table error, so it is most likely a "
            f"permission problem. Refusing to continue — proceeding could generate "
            f"a fresh key and orphan every stored Google credential."
        ) from exc
    row = cur.fetchone()
    return row[0] if row and row[0] else None


def resolve_key_for_update(
    ws: Any,
    scope: str,
    key: str,
    lakebase_key: str | None,
    app_yaml_key: str | None,
) -> tuple[str, bool]:
    """Decide which key secret mode should hold. Returns (value, wrote_secret).

    First hit wins:
      1. A valid key already in the secret — authoritative, and hard-fails if it
         disagrees with an existing Lakebase row (mirrors the guard in
         ``_migrate_encryption_key_to_lakebase``).
      2. The existing Lakebase row — the relocate case.
      3. A legacy ``GOOGLE_OAUTH_ENCRYPTION_KEY`` still in the deployed app.yaml.
      4. Nothing anywhere — generate fresh.
    """
    existing = read_secret_key(ws, scope, key)
    if existing:
        if lakebase_key and lakebase_key != existing:
            raise SecretKeyError(
                f"Secret {scope}/{key} holds a different key from "
                f"encryption_keys. Refusing to continue: attaching the secret and "
                f"deleting the row would orphan every credential encrypted under "
                f"the other key. Resolve which key is correct, then re-run."
            )
        logger.info("Secret %s/%s already holds the key — reusing", scope, key)
        return existing, False

    value = lakebase_key or app_yaml_key or Fernet.generate_key().decode()
    write_and_verify_secret_key(ws, scope, key, value)
    return value, True


def app_reports_secret_source(
    ws: Any, app_url: str, attempts: int = 10, delay: float = 6.0
) -> bool:
    """Return True only if the live app reports it is reading from the secret.

    This is the gate on deleting the Lakebase key row. It **fails closed**: a
    missing field, an unparseable body, a non-200, or a network error all return
    False, because every one of those is indistinguishable from "the deployed code
    does not know about secret mode". An app pinned to a pre-feature version has
    no ``encryption_key_source`` field at all, which is exactly the case that must
    not delete the row.

    Databricks Apps sit behind the workspace proxy, so the request carries
    workspace credentials from ``ws.config.authenticate()``.
    """
    url = f"{app_url.rstrip('/')}/api/health"
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.get(url, headers=ws.config.authenticate(), timeout=15)
            if resp.status_code == 200:
                source = resp.json().get("encryption_key_source")
                if source == "secret":
                    return True
                logger.info(
                    "Health gate attempt %s/%s: key source is %r, not 'secret'",
                    attempt, attempts, source,
                )
            else:
                logger.info(
                    "Health gate attempt %s/%s: HTTP %s", attempt, attempts,
                    resp.status_code,
                )
        except Exception as exc:  # noqa: BLE001 — any failure means "not confirmed"
            logger.info("Health gate attempt %s/%s failed: %s", attempt, attempts, exc)
        if attempt < attempts and delay:
            time.sleep(delay)
    return False


def attach_secret_resource(ws: Any, app_name: str, scope: str, key: str) -> None:
    """Add or replace the secret resource on an existing app.

    A GET-fetched ``App`` cannot be passed back: ``apps.update`` rejects it with
    "Compute size updates are not supported in this update API" (verified). It is
    also a full replace on the fields it does accept — omitting ``description``
    blanks it and omitting ``user_api_scopes`` nulls it. So build a fresh App,
    carry every mutable field explicitly, and omit ``compute_size``.
    """
    cur = ws.apps.get(name=app_name)
    # Filter by name only: an app may legitimately carry other secret
    # resources, and dropping those would silently break it.
    kept = [r for r in (cur.resources or []) if r.name != RESOURCE_KEY]
    kept.append(build_secret_resource(scope, key))
    ws.apps.update(
        name=app_name,
        app=App(
            name=app_name,
            description=cur.description,
            default_source_code_path=cur.default_source_code_path,
            user_api_scopes=cur.user_api_scopes,
            resources=kept,
            # compute_size deliberately omitted — passing it is rejected.
        ),
    )
    logger.info("Attached %s resource to app %s", RESOURCE_KEY, app_name)


def delete_lakebase_key_row(cur: Any, schema_name: str) -> None:
    """Remove the relocated key row. Only ever called behind the health gate."""
    cur.execute(f'DELETE FROM "{schema_name}".encryption_keys WHERE id = 1')
    logger.info("Deleted the relocated key row from %s.encryption_keys", schema_name)


def app_is_secret_mode(ws: Any, app_name: str) -> bool:
    """True when the app already carries the encryption-key secret resource."""
    try:
        app = ws.apps.get(name=app_name)
    except Exception:  # noqa: BLE001 — absence is not secret mode
        return False
    return any(r.name == RESOURCE_KEY for r in (app.resources or []))
