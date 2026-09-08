# Secret-Backed Fernet Key Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in deployment method that stores the Google-credential Fernet master key in a Databricks secret instead of the Lakebase `encryption_keys` table, leaving the existing Lakebase path byte-for-byte unchanged.

**Architecture:** The deploy tool declares a Databricks Apps `AppResourceSecret` with resource key `TELLR_ENCRYPTION_KEY` and writes a matching `valueFrom` entry into the generated `app.yaml`; the platform then injects the key as an environment variable. At boot, `get_encryption_key()` uses that variable when present and otherwise falls through to today's Lakebase resolution. On an existing app, `update()` relocates the key into the secret and deletes the Lakebase row — but only after the running app confirms via `/api/health` that it is reading from the secret.

**Tech Stack:** Python 3.11, `databricks-sdk` 0.112+, `cryptography` (Fernet), `psycopg2`, FastAPI, pytest, Databricks Apps, Lakebase (Postgres).

**Spec:** `docs/superpowers/specs/2026-08-20-secret-backed-fernet-key-design.md`

## Global Constraints

Every task's requirements implicitly include this section.

- **Secret mode must never write to Lakebase.** The secret branch of `get_encryption_key()` returns before any database access.
- **The legacy path must stay bit-for-bit unchanged.** Today's `get_encryption_key()` body moves verbatim into `_from_lakebase()`. Every existing test in `tests/unit/test_encryption.py` must pass untouched.
- **Injected variable name:** `TELLR_ENCRYPTION_KEY`. Never `GOOGLE_OAUTH_ENCRYPTION_KEY` — that name is the legacy seed source at `src/core/encryption.py:90` and writes its value *into* `encryption_keys`.
- **Resource key:** `TELLR_ENCRYPTION_KEY` (verified accepted by the Apps API).
- **Default secret key name:** `tellr-encryption-key`.
- **No `put_acl` call anywhere.** Attaching the resource auto-grants the app SP `READ` (verified). Adding one would require MANAGE on the scope, which breaks fork creation.
- **`ws.apps.update` must never receive `compute_size`** — it raises `InvalidParameterValue: Compute size updates are not supported in this update API`. It is also a full replace: omitted `description` becomes `''` and omitted `user_api_scopes` becomes `None`, so carry every mutable field explicitly.
- **Secrets API values are base64.** `get_secret().value` needs `base64.b64decode`. A missed decode fails loudly (`Fernet()` raises `ValueError`), but decode explicitly.
- **The health-source poll fails closed.** Missing field, unparseable body, non-200, or timeout all mean "not confirmed" and therefore "do not delete".
- **Do not name any new `_write_app_yaml` parameter `encryption_key`.** `tests/unit/test_deploy_app_yaml.py:37` asserts `"encryption_key" not in sig.parameters` and that guard protects the SDR-4437 invariant.
- **`delete()` must never touch secrets or scopes.** Forks share production's scope; teardown deleting it would destroy the production master key.
- **Accepted risks — do not build mitigations for these:** the injected key is visible on the app's Environment page; detaching the resource silently reverts to Lakebase and orphans ciphertext. Both are signed off in the spec.

---

## File Structure

**App side** (ships in `databricks-tellr-app` via `src/`):
- `src/core/encryption.py` — modify: dispatch, `_from_secret`, `_from_lakebase`, `key_source()`
- `src/api/main.py:490` — modify: add key-source field to `/api/health`
- `tests/unit/test_encryption.py` — modify: secret-mode tests + fixture hermeticity

**Deploy tool** (`databricks-tellr`):
- `packages/databricks-tellr/databricks_tellr/secret_key.py` — **create**: all secret-mode helpers (preflight, secret read/write/verify, health poll, ladder). Keeps this logic out of the already-1740-line `deploy.py` and unit-testable without mocking a whole deploy, following the existing `identifiers.py` precedent.
- `packages/databricks-tellr/databricks_tellr/_templates/app.yaml.template` — modify: conditional secret env block
- `packages/databricks-tellr/databricks_tellr/deploy.py` — modify: new arguments, wiring, resource attach, DELETE gate
- `packages/databricks-tellr/pyproject.toml` — modify: add `requests`, version bump
- `tests/unit/test_deploy_secret_encryption_key.py` — **create**
- `tests/unit/test_deploy_app_yaml.py` — modify

**Dev deploy:**
- `scripts/deploy_local.py`, `scripts/deploy_local.sh`, `config/deployment.yaml`, `config/deployment.example.yaml` — modify
- `tests/unit/test_deploy_local_preflight.py` — modify

---

### Task 1: Boot-time key resolution

**Files:**
- Modify: `src/core/encryption.py:103-135`
- Test: `tests/unit/test_encryption.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `get_encryption_key() -> bytes` (unchanged signature), `_from_secret() -> bytes`, `_from_lakebase() -> bytes`, `key_source() -> str` returning `"secret"` or `"lakebase"`.

- [ ] **Step 1: Add fixture hermeticity, then write the failing tests**

In `tests/unit/test_encryption.py`, add to the `db` fixture body immediately after the existing `monkeypatch.delenv("GOOGLE_OAUTH_ENCRYPTION_KEY", raising=False)` line:

```python
    monkeypatch.delenv("TELLR_ENCRYPTION_KEY", raising=False)
```

Then append these tests:

```python
def test_secret_env_var_is_used_and_lakebase_untouched(db, monkeypatch):
    """Secret mode returns the injected key and never writes to Lakebase."""
    engine, _ = db
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("TELLR_ENCRYPTION_KEY", key)
    assert get_encryption_key() == key.encode()
    assert _stored_key(engine) is None


def test_secret_env_var_wins_over_existing_row_and_leaves_it_alone(db, monkeypatch):
    """The env var takes precedence; the pre-existing row is not modified."""
    engine, session = db
    row_key = Fernet.generate_key().decode()
    with session() as s:
        s.execute(
            text(
                "INSERT INTO encryption_keys (id, key_value, created_at) "
                "VALUES (1, :k, CURRENT_TIMESTAMP)"
            ),
            {"k": row_key},
        )
    env_key = Fernet.generate_key().decode()
    monkeypatch.setenv("TELLR_ENCRYPTION_KEY", env_key)
    assert get_encryption_key() == env_key.encode()
    assert _stored_key(engine) == row_key


def test_secret_env_var_invalid_fernet_raises(db, monkeypatch):
    """A corrupt secret refuses to boot rather than producing garbage."""
    monkeypatch.setenv("TELLR_ENCRYPTION_KEY", "not-a-fernet-key")
    with pytest.raises(RuntimeError, match="TELLR_ENCRYPTION_KEY"):
        get_encryption_key()


def test_blank_secret_env_var_falls_through_to_lakebase(db, monkeypatch):
    """A blank variable is treated as absent, not as a corrupt key."""
    engine, _ = db
    monkeypatch.setenv("TELLR_ENCRYPTION_KEY", "   ")
    key = get_encryption_key()
    assert Fernet(key)
    assert _stored_key(engine) == key.decode()


def test_key_source_reports_secret_or_lakebase(db, monkeypatch):
    from src.core.encryption import key_source

    assert key_source() == "lakebase"
    monkeypatch.setenv("TELLR_ENCRYPTION_KEY", Fernet.generate_key().decode())
    assert key_source() == "secret"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_encryption.py -v -k "secret_env or key_source or blank_secret"`
Expected: FAIL — `ImportError: cannot import name 'key_source'`, and the env-var tests fail because the variable is ignored.

- [ ] **Step 3: Implement the dispatch**

In `src/core/encryption.py`, replace the body of `get_encryption_key` (lines 103-125) with a dispatch, moving the existing body into `_from_lakebase` verbatim:

```python
_SECRET_ENV_VAR = "TELLR_ENCRYPTION_KEY"


def key_source() -> str:
    """Report where the master key comes from, without reading the key itself.

    Consumed by /api/health so the deploy tool can confirm a relocated app is
    actually reading the secret before it deletes the Lakebase row.
    """
    return "secret" if os.getenv(_SECRET_ENV_VAR, "").strip() else "lakebase"


def _from_secret() -> bytes:
    """Return the Fernet key injected by the Apps secret resource.

    Deliberately touches no database: a secret-mode app's encryption_keys table
    is empty by construction, and writing to it would defeat the whole point.
    """
    raw = os.getenv(_SECRET_ENV_VAR, "").strip()
    try:
        Fernet(raw.encode())
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            f"{_SECRET_ENV_VAR} is not a valid Fernet key — refusing to start. "
            f"Check the value stored in the secret backing the "
            f"{_SECRET_ENV_VAR} app resource."
        ) from exc
    logger.info("Encryption key loaded from the %s secret resource", _SECRET_ENV_VAR)
    return raw.encode()


def _from_lakebase() -> bytes:
    """Return the Fernet master key from the encryption_keys table (id=1)."""
    from src.core.database import get_db_session

    # 1. Read-first (see module docstring for why this order matters).
    with get_db_session() as session:
        row = session.execute(_SELECT_KEY).first()
    if row and row[0]:
        return _validated(row[0].encode())

    # 2 + 3. Seed if absent — race-safe across workers/replicas.
    seed = _seed_value()
    with get_db_session() as session:
        session.execute(_INSERT_KEY, {"key_value": seed.decode()})
    with get_db_session() as session:
        row = session.execute(_SELECT_KEY).first()
    if not row or not row[0]:
        raise RuntimeError(
            "Failed to seed encryption_keys: no key row after insert. "
            "Check the app's SELECT, INSERT grants on the data schema."
        )
    return _validated(row[0].encode())


@lru_cache(maxsize=1)
def get_encryption_key() -> bytes:
    """Return the Fernet master key, from the secret resource or Lakebase."""
    if os.getenv(_SECRET_ENV_VAR, "").strip():
        return _from_secret()
    return _from_lakebase()
```

- [ ] **Step 4: Rewrite the module docstring for two paths**

Replace the first paragraph of the module docstring (lines 1-6) with:

```python
"""Fernet symmetric encryption for sensitive data (OAuth credentials, tokens).

Uses AES-128-CBC with HMAC-SHA256 authentication via the ``cryptography``
library. The master key comes from one of two places, selected at boot:

1. **Secret-backed (opt-in).** When the deploy tool has attached a Databricks
   Apps secret resource, the platform injects ``TELLR_ENCRYPTION_KEY`` into the
   environment and that value is the key. This path never touches the database.
   See docs/superpowers/specs/2026-08-20-secret-backed-fernet-key-design.md.
2. **Lakebase-backed (default, unchanged).** The key lives in the
   ``encryption_keys`` table of the application database (SDR-4437 CRITICAL-3):
   dynamic, persistent across restarts/restores, unique per deployment, zero
   operator setup.
"""
```

- [ ] **Step 5: Run the full encryption suite**

Run: `.venv/bin/python -m pytest tests/unit/test_encryption.py -v`
Expected: PASS — all new tests plus every pre-existing test unchanged.

- [ ] **Step 6: Commit**

```bash
git add src/core/encryption.py tests/unit/test_encryption.py
git commit -m "feat(encryption): resolve the Fernet key from an injected secret when present"
```

---

### Task 2: Report the key source on /api/health

**Files:**
- Modify: `src/api/main.py:488-495`
- Test: `tests/unit/test_health_key_source.py` (create)

**Interfaces:**
- Consumes: `key_source()` from Task 1.
- Produces: `GET /api/health` returning an `encryption_key_source` field valued `"secret"` or `"lakebase"`. Task 6's poll reads this exact field name.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_health_key_source.py`:

```python
"""The DELETE gate in the deploy tool reads this field; it must never leak the key."""

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from src.api.main import app

    return TestClient(app)


def test_health_reports_lakebase_by_default(client, monkeypatch):
    monkeypatch.delenv("TELLR_ENCRYPTION_KEY", raising=False)
    body = client.get("/api/health").json()
    assert body["encryption_key_source"] == "lakebase"


def test_health_reports_secret_when_injected(client, monkeypatch):
    monkeypatch.setenv("TELLR_ENCRYPTION_KEY", Fernet.generate_key().decode())
    body = client.get("/api/health").json()
    assert body["encryption_key_source"] == "secret"


def test_health_never_exposes_the_key(client, monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("TELLR_ENCRYPTION_KEY", key)
    raw = client.get("/api/health").text
    assert key not in raw
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_health_key_source.py -v`
Expected: FAIL with `KeyError: 'encryption_key_source'`.

- [ ] **Step 3: Add the field**

In `src/api/main.py`, replace the `health()` body:

```python
@app.get("/api/health")
async def health():
    """Health check endpoint.

    ``encryption_key_source`` is load-bearing for deployment: ``tellr.update``
    polls it to confirm a relocated app is reading the secret before it deletes
    the Lakebase key row. Reports the source only — never the key.
    """
    from src.core.encryption import key_source

    return {
        "status": "healthy",
        "environment": ENVIRONMENT,
        "version": "0.3.0",
        "encryption_key_source": key_source(),
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_health_key_source.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/api/main.py tests/unit/test_health_key_source.py
git commit -m "feat(health): report the encryption key source for the deploy-time DELETE gate"
```

---

### Task 3: app.yaml template gains a conditional secret block

**Files:**
- Modify: `packages/databricks-tellr/databricks_tellr/_templates/app.yaml.template`
- Modify: `packages/databricks-tellr/databricks_tellr/deploy.py:1363-1418` and call sites at `deploy.py:413`, `deploy.py:573`
- Modify: `scripts/deploy_local.py:476`, `scripts/deploy_local.py:768`
- Test: `tests/unit/test_deploy_app_yaml.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `_write_app_yaml(..., encryption_secret_resource_key: str | None = None)`. When set, the generated `app.yaml` contains an `env:` entry named after that resource key with a matching `valueFrom`. Tasks 7, 8 and 11 pass it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_deploy_app_yaml.py`:

```python
def test_app_yaml_omits_secret_block_in_legacy_mode(tmp_path: Path):
    """Legacy deploys must not reference a resource the app does not have."""
    deploy._write_app_yaml(
        tmp_path, lakebase_name="db-tellr", schema_name="app_data",
        lakebase_result={"type": "provisioned"},
    )
    content = (tmp_path / "app.yaml").read_text()
    assert "TELLR_ENCRYPTION_KEY" not in content
    assert "valueFrom" in content  # system.databricks_host etc. still present


def test_app_yaml_includes_secret_block_in_secret_mode(tmp_path: Path):
    deploy._write_app_yaml(
        tmp_path, lakebase_name="db-tellr", schema_name="app_data",
        lakebase_result={"type": "provisioned"},
        encryption_secret_resource_key="TELLR_ENCRYPTION_KEY",
    )
    content = (tmp_path / "app.yaml").read_text()
    assert "- name: TELLR_ENCRYPTION_KEY" in content
    assert 'valueFrom: "TELLR_ENCRYPTION_KEY"' in content


def test_app_yaml_never_contains_key_material(tmp_path: Path):
    """Secret mode references the resource; it must not embed a key."""
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    deploy._write_app_yaml(
        tmp_path, lakebase_name="db-tellr", schema_name="app_data",
        lakebase_result={"type": "provisioned"},
        encryption_secret_resource_key="TELLR_ENCRYPTION_KEY",
    )
    content = (tmp_path / "app.yaml").read_text()
    assert key not in content
    assert "GOOGLE_OAUTH_ENCRYPTION_KEY" not in content
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_deploy_app_yaml.py -v`
Expected: FAIL — `TypeError: _write_app_yaml() got an unexpected keyword argument 'encryption_secret_resource_key'`.

- [ ] **Step 3: Add the template placeholder**

At the end of the `env:` block in `_templates/app.yaml.template` (after the `HUASHU_PIPELINE_ENABLED` entry), append:

```yaml
${ENCRYPTION_SECRET_ENV_BLOCK}
```

`Template.substitute` is strict, so this placeholder must be supplied on every call — an empty string in legacy mode.

- [ ] **Step 4: Add the parameter**

In `deploy.py::_write_app_yaml`, add the parameter and build the block:

```python
def _write_app_yaml(
    staging_dir: Path,
    lakebase_name: str,
    schema_name: str,
    seed_databricks_defaults: bool = False,
    lakebase_result: dict[str, Any] | None = None,
    mlflow_tracing: dict[str, str] | None = None,
    encryption_secret_resource_key: str | None = None,
) -> None:
```

Extend the docstring's existing SDR-4437 note:

```python
    """...
        encryption_secret_resource_key: When set, add an ``env:`` entry mapping
            this Apps secret resource key into the environment. The resource
            declaration alone does not inject anything — the ``valueFrom`` entry
            is required (verified live). No key material is written; this is a
            resource reference only. Leave None for the Lakebase-backed path.
    """
```

Before the `Template(...).substitute(...)` call, add:

```python
    if encryption_secret_resource_key:
        # The Apps secret resource supplies the value; this only names it.
        secret_env_block = (
            f"  - name: {encryption_secret_resource_key}\n"
            f'    valueFrom: "{encryption_secret_resource_key}"\n'
        )
    else:
        secret_env_block = ""
```

and add to the `substitute(...)` keyword arguments:

```python
        ENCRYPTION_SECRET_ENV_BLOCK=secret_env_block,
```

- [ ] **Step 5: Thread it through all four call sites**

At `deploy.py:413` and `deploy.py:573`, and `scripts/deploy_local.py:476` and `scripts/deploy_local.py:768`, add the argument to each `_write_app_yaml(...)` call:

```python
                encryption_secret_resource_key=encryption_secret_resource_key,
```

For now define `encryption_secret_resource_key = None` locally at the top of each of the four enclosing functions; Tasks 7, 8 and 11 replace those with real values.

- [ ] **Step 6: Run the app.yaml suite**

Run: `.venv/bin/python -m pytest tests/unit/test_deploy_app_yaml.py -v`
Expected: PASS, including the pre-existing `test_write_app_yaml_is_keyless` (the new parameter is not literally named `encryption_key`).

- [ ] **Step 7: Commit**

```bash
git add packages/databricks-tellr/databricks_tellr/_templates/app.yaml.template \
        packages/databricks-tellr/databricks_tellr/deploy.py \
        scripts/deploy_local.py tests/unit/test_deploy_app_yaml.py
git commit -m "feat(deploy): emit a conditional secret valueFrom entry in app.yaml"
```

---

### Task 4: secret_key.py — scope preflight

**Files:**
- Create: `packages/databricks-tellr/databricks_tellr/secret_key.py`
- Test: `tests/unit/test_deploy_secret_encryption_key.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `SecretKeyError(Exception)`
  - `RESOURCE_KEY = "TELLR_ENCRYPTION_KEY"`, `DEFAULT_SECRET_KEY = "tellr-encryption-key"`
  - `preflight_scope(ws, scope: str) -> None`
  - `preflight_lakebase_privileges(cur, schema_name: str) -> None`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_deploy_secret_encryption_key.py`:

```python
"""Secret-backed Fernet key deploy helpers.

See docs/superpowers/specs/2026-08-20-secret-backed-fernet-key-design.md.
"""

from unittest.mock import MagicMock

import pytest

pytest.importorskip("databricks_tellr", reason="databricks-tellr not installed")

from databricks.sdk.service.workspace import ScopeBackendType, SecretScope
from databricks_tellr import secret_key
from databricks_tellr.secret_key import SecretKeyError


def _ws(scopes=(), create_error=None):
    ws = MagicMock()
    ws.secrets.list_scopes.return_value = list(scopes)
    if create_error:
        ws.secrets.create_scope.side_effect = create_error
    return ws


def test_preflight_accepts_existing_databricks_backed_scope():
    ws = _ws([SecretScope(name="tellr", backend_type=ScopeBackendType.DATABRICKS)])
    secret_key.preflight_scope(ws, "tellr")
    ws.secrets.create_scope.assert_not_called()


def test_preflight_creates_missing_scope_without_initial_manage_principal():
    ws = _ws([])
    secret_key.preflight_scope(ws, "tellr")
    kwargs = ws.secrets.create_scope.call_args.kwargs
    assert kwargs["scope"] == "tellr"
    assert "initial_manage_principal" not in kwargs


def test_preflight_refuses_keyvault_backed_scope():
    ws = _ws([SecretScope(name="tellr", backend_type=ScopeBackendType.AZURE_KEYVAULT)])
    with pytest.raises(SecretKeyError, match="Key Vault"):
        secret_key.preflight_scope(ws, "tellr")


def test_preflight_maps_permission_error_to_actionable_message():
    ws = _ws([], create_error=Exception("CUSTOMER_UNAUTHORIZED: nope"))
    with pytest.raises(SecretKeyError, match="databricks secrets create-scope tellr"):
        secret_key.preflight_scope(ws, "tellr")


def test_preflight_maps_scope_limit_to_actionable_message():
    ws = _ws([], create_error=Exception("RESOURCE_LIMIT_EXCEEDED"))
    with pytest.raises(SecretKeyError, match="secret-scope limit"):
        secret_key.preflight_scope(ws, "tellr")


def test_lakebase_privilege_probe_passes_when_both_granted():
    cur = MagicMock()
    cur.fetchone.side_effect = [(True,), (True,)]
    secret_key.preflight_lakebase_privileges(cur, "app_data_prod")


def test_lakebase_privilege_probe_aborts_when_delete_missing():
    cur = MagicMock()
    cur.fetchone.side_effect = [(True,), (False,)]
    with pytest.raises(SecretKeyError, match="DELETE"):
        secret_key.preflight_lakebase_privileges(cur, "app_data_prod")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_deploy_secret_encryption_key.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'databricks_tellr.secret_key'`.

- [ ] **Step 3: Create the module**

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_deploy_secret_encryption_key.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add packages/databricks-tellr/databricks_tellr/secret_key.py \
        tests/unit/test_deploy_secret_encryption_key.py
git commit -m "feat(deploy): add secret scope and Lakebase privilege preflight"
```

---

### Task 5: secret_key.py — read, write and verify the secret

**Files:**
- Modify: `packages/databricks-tellr/databricks_tellr/secret_key.py`
- Test: `tests/unit/test_deploy_secret_encryption_key.py`

**Interfaces:**
- Consumes: `SecretKeyError` from Task 4.
- Produces:
  - `read_secret_key(ws, scope, key) -> str | None` — returns the decoded Fernet key, `None` only when genuinely absent, raises on permission denial.
  - `write_and_verify_secret_key(ws, scope, key, value: str) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_deploy_secret_encryption_key.py`:

```python
import base64
from cryptography.fernet import Fernet
from databricks.sdk.service.workspace import GetSecretResponse


def _secret_ws(value=None, get_error=None):
    ws = MagicMock()
    if get_error:
        ws.secrets.get_secret.side_effect = get_error
    else:
        encoded = base64.b64encode(value.encode()).decode()
        ws.secrets.get_secret.return_value = GetSecretResponse(key="k", value=encoded)
    return ws


def test_read_secret_key_base64_decodes():
    key = Fernet.generate_key().decode()
    ws = _secret_ws(value=key)
    assert secret_key.read_secret_key(ws, "tellr", "k") == key


def test_read_secret_key_returns_none_when_absent():
    ws = _secret_ws(get_error=Exception("RESOURCE_DOES_NOT_EXIST"))
    assert secret_key.read_secret_key(ws, "tellr", "k") is None


def test_read_secret_key_raises_on_permission_denied():
    """A denial must never be mistaken for absence — that would clobber a live key."""
    ws = _secret_ws(get_error=Exception("PERMISSION_DENIED"))
    with pytest.raises(SecretKeyError, match="permission"):
        secret_key.read_secret_key(ws, "tellr", "k")


def test_read_secret_key_rejects_non_fernet_value():
    ws = _secret_ws(value="not-a-fernet-key")
    with pytest.raises(SecretKeyError, match="not a valid Fernet key"):
        secret_key.read_secret_key(ws, "tellr", "k")


def test_write_and_verify_round_trips():
    key = Fernet.generate_key().decode()
    ws = _secret_ws(value=key)
    secret_key.write_and_verify_secret_key(ws, "tellr", "k", key)
    ws.secrets.put_secret.assert_called_once_with(
        scope="tellr", key="k", string_value=key
    )


def test_write_and_verify_aborts_on_mismatch():
    """If the read-back differs, abort before anything irreversible happens."""
    ws = _secret_ws(value=Fernet.generate_key().decode())
    with pytest.raises(SecretKeyError, match="read-back"):
        secret_key.write_and_verify_secret_key(
            ws, "tellr", "k", Fernet.generate_key().decode()
        )
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_deploy_secret_encryption_key.py -v -k "read_secret or write_and_verify"`
Expected: FAIL — `AttributeError: module 'databricks_tellr.secret_key' has no attribute 'read_secret_key'`.

- [ ] **Step 3: Implement both functions**

Append to `secret_key.py`:

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_deploy_secret_encryption_key.py -v`
Expected: PASS (13 tests).

- [ ] **Step 5: Commit**

```bash
git add packages/databricks-tellr/databricks_tellr/secret_key.py \
        tests/unit/test_deploy_secret_encryption_key.py
git commit -m "feat(deploy): read, write and verify the Fernet key in a Databricks secret"
```

---

### Task 6: secret_key.py — the fail-closed health gate

**Files:**
- Modify: `packages/databricks-tellr/databricks_tellr/secret_key.py`
- Modify: `packages/databricks-tellr/pyproject.toml` (add `requests`)
- Test: `tests/unit/test_deploy_secret_encryption_key.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `app_reports_secret_source(ws, app_url: str, attempts: int = 10, delay: float = 6.0) -> bool` — `True` only when the live app reports `encryption_key_source == "secret"`.

This is the highest-value test target in the plan: every branch is a data-loss guard.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_deploy_secret_encryption_key.py`:

```python
def _poll_ws():
    ws = MagicMock()
    ws.config.authenticate.return_value = {"Authorization": "Bearer t"}
    return ws


def _resp(status=200, payload=None, raise_json=False):
    r = MagicMock()
    r.status_code = status
    if raise_json:
        r.json.side_effect = ValueError("not json")
    else:
        r.json.return_value = payload or {}
    return r


@pytest.mark.parametrize(
    "response",
    [
        _resp(200, {"encryption_key_source": "lakebase"}),
        _resp(200, {"status": "healthy"}),          # field absent — old app code
        _resp(200, raise_json=True),                 # unparseable body
        _resp(503, {"encryption_key_source": "secret"}),
    ],
    ids=["reports-lakebase", "field-absent", "unparseable", "non-200"],
)
def test_health_gate_fails_closed(monkeypatch, response):
    monkeypatch.setattr(secret_key.requests, "get", lambda *a, **k: response)
    assert secret_key.app_reports_secret_source(
        _poll_ws(), "https://app", attempts=1, delay=0
    ) is False


def test_health_gate_fails_closed_on_timeout(monkeypatch):
    def boom(*a, **k):
        raise TimeoutError("timed out")

    monkeypatch.setattr(secret_key.requests, "get", boom)
    assert secret_key.app_reports_secret_source(
        _poll_ws(), "https://app", attempts=2, delay=0
    ) is False


def test_health_gate_opens_only_on_secret(monkeypatch):
    monkeypatch.setattr(
        secret_key.requests, "get",
        lambda *a, **k: _resp(200, {"encryption_key_source": "secret"}),
    )
    assert secret_key.app_reports_secret_source(
        _poll_ws(), "https://app", attempts=1, delay=0
    ) is True


def test_health_gate_sends_workspace_credentials(monkeypatch):
    seen = {}

    def capture(url, headers=None, timeout=None):
        seen["url"] = url
        seen["headers"] = headers
        return _resp(200, {"encryption_key_source": "secret"})

    monkeypatch.setattr(secret_key.requests, "get", capture)
    secret_key.app_reports_secret_source(_poll_ws(), "https://app/", attempts=1, delay=0)
    assert seen["url"] == "https://app/api/health"
    assert seen["headers"]["Authorization"] == "Bearer t"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_deploy_secret_encryption_key.py -v -k health_gate`
Expected: FAIL — `AttributeError: module 'databricks_tellr.secret_key' has no attribute 'requests'`.

- [ ] **Step 3: Add `requests` as an explicit dependency**

In `packages/databricks-tellr/pyproject.toml`, add to `dependencies`:

```toml
    "requests>=2.31.0",
```

It is already present transitively via `databricks-sdk`; declaring it makes the import honest.

- [ ] **Step 4: Implement the gate**

Add `import time` and `import requests` to `secret_key.py`'s imports, then append:

```python
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
```

- [ ] **Step 5: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_deploy_secret_encryption_key.py -v`
Expected: PASS (21 tests).

- [ ] **Step 6: Commit**

```bash
git add packages/databricks-tellr/databricks_tellr/secret_key.py \
        packages/databricks-tellr/pyproject.toml \
        tests/unit/test_deploy_secret_encryption_key.py
git commit -m "feat(deploy): add the fail-closed health-source gate for the key DELETE"
```

---

### Task 7: create() in secret mode

**Files:**
- Modify: `packages/databricks-tellr/databricks_tellr/deploy.py:188-262` (`create`), `323-477` (`_create_databricks`), `1480-1535` (`_create_app`), `850-894` (`_load_deployment_config`)
- Test: `tests/unit/test_deploy_secret_encryption_key.py`

**Interfaces:**
- Consumes: `preflight_scope`, `read_secret_key`, `write_and_verify_secret_key`, `RESOURCE_KEY`, `DEFAULT_SECRET_KEY` (Tasks 4-5); `_write_app_yaml(..., encryption_secret_resource_key=...)` (Task 3).
- Produces: `create(..., encryption_secret_scope: str | None = None, encryption_secret_key: str = "tellr-encryption-key")`; `_create_app(..., encryption_secret_scope=None, encryption_secret_key=None)`; `secret_key.build_secret_resource(scope, key) -> AppResource`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_deploy_secret_encryption_key.py`:

```python
def test_build_secret_resource_shape():
    r = secret_key.build_secret_resource("tellr", "tellr-encryption-key")
    assert r.name == "TELLR_ENCRYPTION_KEY"
    assert r.secret.scope == "tellr"
    assert r.secret.key == "tellr-encryption-key"
    assert r.secret.permission.value.upper() == "READ"


def test_resolve_key_for_create_reuses_existing_secret():
    """An existing secret may already protect ciphertext — never overwrite it."""
    existing = Fernet.generate_key().decode()
    ws = _secret_ws(value=existing)
    assert secret_key.resolve_key_for_create(ws, "tellr", "k") == existing
    ws.secrets.put_secret.assert_not_called()


def test_resolve_key_for_create_generates_when_absent():
    ws = MagicMock()
    ws.secrets.get_secret.side_effect = Exception("RESOURCE_DOES_NOT_EXIST")
    generated = {}

    def capture(scope, key, string_value):
        generated["v"] = string_value
        encoded = base64.b64encode(string_value.encode()).decode()
        ws.secrets.get_secret.side_effect = None
        ws.secrets.get_secret.return_value = GetSecretResponse(key=key, value=encoded)

    ws.secrets.put_secret.side_effect = capture
    result = secret_key.resolve_key_for_create(ws, "tellr", "k")
    assert result == generated["v"]
    assert Fernet(result.encode())
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_deploy_secret_encryption_key.py -v -k "build_secret_resource or resolve_key_for_create"`
Expected: FAIL — attributes do not exist.

- [ ] **Step 3: Add the helpers**

Add to `secret_key.py` imports:

```python
from databricks.sdk.service.apps import (
    AppResource,
    AppResourceSecret,
    AppResourceSecretSecretPermission,
)
from cryptography.fernet import Fernet
```

Append:

```python
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
```

- [ ] **Step 4: Wire it into create()**

In `deploy.py`, add `from databricks_tellr import secret_key` to the imports. Add these parameters to both `create` (line 188) and `_create_databricks` (line 323):

```python
    encryption_secret_scope: str | None = None,
    encryption_secret_key: str = secret_key.DEFAULT_SECRET_KEY,
```

Document them on `create`:

```python
        encryption_secret_scope: Opt in to the secret-backed Fernet key. When set,
            the key is stored in this Databricks secret scope and attached to the
            app as a secret resource instead of living in the encryption_keys
            Lakebase table. When omitted, the Lakebase-backed path is used.
        encryption_secret_key: Secret key name within that scope.
```

Pass both through in `create`'s delegating call to `_create_databricks`.

In `_create_databricks`, after the YAML config block (so a scope from
`config/deployment.yaml` is visible) and **before** `_get_or_create_lakebase` at
line 402, insert:

```python
    if config_yaml_path:
        encryption_secret_scope = encryption_secret_scope or config.get(
            "encryption_secret_scope"
        )
        encryption_secret_key = (
            config.get("encryption_secret_key") or encryption_secret_key
        )

    # Preflight before anything is created, so a failure leaves nothing behind.
    resolved_key: str | None = None
    if encryption_secret_scope:
        print(f"Secret-backed encryption key: {encryption_secret_scope}/{encryption_secret_key}")
        secret_key.preflight_scope(ws, encryption_secret_scope)
        resolved_key = secret_key.resolve_key_for_create(
            ws, encryption_secret_scope, encryption_secret_key
        )
```

Replace the local `encryption_secret_resource_key = None` stub from Task 3 with:

```python
    encryption_secret_resource_key = (
        secret_key.RESOURCE_KEY if encryption_secret_scope else None
    )
```

Pass the scope and key into `_create_app`:

```python
            lakebase_type=lakebase_type,
            encryption_secret_scope=encryption_secret_scope,
            encryption_secret_key=encryption_secret_key,
```

- [ ] **Step 5: Attach the resource in both Lakebase branches**

In `_create_app` (line 1480), add the two parameters, then after the existing
`if lakebase_type == "provisioned": ... else: ...` block that builds
`app_resources`, append:

```python
    # Both branches: autoscaling builds an empty resource list, so appending
    # after the branch covers provisioned and autoscaling alike.
    if encryption_secret_scope:
        app_resources.append(
            secret_key.build_secret_resource(
                encryption_secret_scope, encryption_secret_key
            )
        )
```

- [ ] **Step 6: Add the YAML keys to the config loader**

In `_load_deployment_config` (line 850), add to the returned dict:

```python
        "encryption_secret_scope": env_config.get("encryption_secret_scope"),
        "encryption_secret_key": env_config.get("encryption_secret_key"),
```

- [ ] **Step 7: Run the suites**

Run: `.venv/bin/python -m pytest tests/unit/test_deploy_secret_encryption_key.py tests/unit/test_deploy_app_yaml.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add packages/databricks-tellr/databricks_tellr/secret_key.py \
        packages/databricks-tellr/databricks_tellr/deploy.py \
        tests/unit/test_deploy_secret_encryption_key.py
git commit -m "feat(deploy): support secret-backed encryption key in create()"
```

---

### Task 8: update() — the key resolution ladder

**Files:**
- Modify: `packages/databricks-tellr/databricks_tellr/secret_key.py`
- Modify: `packages/databricks-tellr/databricks_tellr/deploy.py:265-315` (`update`), `480-604` (`_update_databricks`)
- Test: `tests/unit/test_deploy_secret_encryption_key.py`

**Interfaces:**
- Consumes: everything from Tasks 4-5.
- Produces: `read_lakebase_key(cur, schema_name) -> str | None`, `resolve_key_for_update(ws, scope, key, lakebase_key, app_yaml_key) -> tuple[str, bool]` returning `(key_value, wrote_secret)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_deploy_secret_encryption_key.py`:

```python
def test_read_lakebase_key_returns_row_value():
    cur = MagicMock()
    cur.fetchone.return_value = ("abc",)
    assert secret_key.read_lakebase_key(cur, "app_data") == "abc"


def test_read_lakebase_key_returns_none_when_table_absent():
    cur = MagicMock()
    cur.execute.side_effect = Exception('relation "app_data.encryption_keys" does not exist')
    assert secret_key.read_lakebase_key(cur, "app_data") is None


def test_read_lakebase_key_fails_closed_on_permission_error():
    """A denied SELECT must abort, never look like 'no row'."""
    cur = MagicMock()
    cur.execute.side_effect = Exception("permission denied for table encryption_keys")
    with pytest.raises(SecretKeyError, match="permission"):
        secret_key.read_lakebase_key(cur, "app_data")


def test_ladder_case1_reuses_matching_secret():
    k = Fernet.generate_key().decode()
    ws = _secret_ws(value=k)
    value, wrote = secret_key.resolve_key_for_update(ws, "s", "k", k, None)
    assert (value, wrote) == (k, False)
    ws.secrets.put_secret.assert_not_called()


def test_ladder_case1_hard_fails_on_mismatch():
    """Reusing a mismatched secret would orphan ciphertext under the other key."""
    ws = _secret_ws(value=Fernet.generate_key().decode())
    with pytest.raises(SecretKeyError, match="different key"):
        secret_key.resolve_key_for_update(
            ws, "s", "k", Fernet.generate_key().decode(), None
        )


def test_ladder_case2_relocates_lakebase_key():
    row_key = Fernet.generate_key().decode()
    ws = MagicMock()
    ws.secrets.get_secret.side_effect = Exception("RESOURCE_DOES_NOT_EXIST")

    def capture(scope, key, string_value):
        ws.secrets.get_secret.side_effect = None
        ws.secrets.get_secret.return_value = GetSecretResponse(
            key=key, value=base64.b64encode(string_value.encode()).decode()
        )

    ws.secrets.put_secret.side_effect = capture
    value, wrote = secret_key.resolve_key_for_update(ws, "s", "k", row_key, None)
    assert (value, wrote) == (row_key, True)


def test_ladder_case3_relocates_app_yaml_key():
    legacy = Fernet.generate_key().decode()
    ws = MagicMock()
    ws.secrets.get_secret.side_effect = Exception("RESOURCE_DOES_NOT_EXIST")

    def capture(scope, key, string_value):
        ws.secrets.get_secret.side_effect = None
        ws.secrets.get_secret.return_value = GetSecretResponse(
            key=key, value=base64.b64encode(string_value.encode()).decode()
        )

    ws.secrets.put_secret.side_effect = capture
    value, wrote = secret_key.resolve_key_for_update(ws, "s", "k", None, legacy)
    assert (value, wrote) == (legacy, True)


def test_ladder_case4_generates_when_nothing_exists():
    ws = MagicMock()
    ws.secrets.get_secret.side_effect = Exception("RESOURCE_DOES_NOT_EXIST")

    def capture(scope, key, string_value):
        ws.secrets.get_secret.side_effect = None
        ws.secrets.get_secret.return_value = GetSecretResponse(
            key=key, value=base64.b64encode(string_value.encode()).decode()
        )

    ws.secrets.put_secret.side_effect = capture
    value, wrote = secret_key.resolve_key_for_update(ws, "s", "k", None, None)
    assert wrote is True
    assert Fernet(value.encode())
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_deploy_secret_encryption_key.py -v -k "lakebase_key or ladder"`
Expected: FAIL — attributes do not exist.

- [ ] **Step 3: Implement the ladder**

Append to `secret_key.py`:

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_deploy_secret_encryption_key.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/databricks-tellr/databricks_tellr/secret_key.py \
        tests/unit/test_deploy_secret_encryption_key.py
git commit -m "feat(deploy): add the secret-mode key resolution ladder with mismatch guard"
```

---

### Task 9: update() — attach the resource, gate, then DELETE

**Files:**
- Modify: `packages/databricks-tellr/databricks_tellr/secret_key.py`
- Modify: `packages/databricks-tellr/databricks_tellr/deploy.py:480-604`
- Test: `tests/unit/test_deploy_secret_encryption_key.py`

**Interfaces:**
- Consumes: Tasks 4-8.
- Produces: `attach_secret_resource(ws, app_name, scope, key) -> None`, `delete_lakebase_key_row(cur, schema_name) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_deploy_secret_encryption_key.py`:

```python
from databricks.sdk.service.apps import App, ComputeSize


def test_attach_preserves_mutable_fields_and_omits_compute_size():
    """apps.update rejects compute_size and wipes omitted fields (verified live)."""
    ws = MagicMock()
    db_resource = MagicMock()
    db_resource.name = "app_database"
    db_resource.secret = None
    ws.apps.get.return_value = App(
        name="app", description="Tellr", compute_size=ComputeSize.MEDIUM,
        default_source_code_path="/ws/src", user_api_scopes=["sql"],
        resources=[db_resource],
    )
    secret_key.attach_secret_resource(ws, "app", "tellr", "tellr-encryption-key")
    sent = ws.apps.update.call_args.kwargs["app"]
    assert sent.compute_size is None
    assert sent.description == "Tellr"
    assert sent.user_api_scopes == ["sql"]
    assert sent.default_source_code_path == "/ws/src"
    names = [r.name for r in sent.resources]
    assert names == ["app_database", "TELLR_ENCRYPTION_KEY"]


def test_attach_replaces_an_existing_secret_resource():
    ws = MagicMock()
    stale = secret_key.build_secret_resource("old-scope", "old-key")
    ws.apps.get.return_value = App(name="app", resources=[stale])
    secret_key.attach_secret_resource(ws, "app", "new-scope", "new-key")
    sent = ws.apps.update.call_args.kwargs["app"]
    assert len(sent.resources) == 1
    assert sent.resources[0].secret.scope == "new-scope"


def test_delete_lakebase_key_row_issues_the_delete():
    cur = MagicMock()
    secret_key.delete_lakebase_key_row(cur, "app_data")
    sql = cur.execute.call_args[0][0]
    assert "DELETE FROM" in sql and "encryption_keys" in sql
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_deploy_secret_encryption_key.py -v -k "attach or delete_lakebase"`
Expected: FAIL — attributes do not exist.

- [ ] **Step 3: Implement both**

Add `from databricks.sdk.service.apps import App` to `secret_key.py`, then append:

```python
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
```

- [ ] **Step 4: Wire the flow into `_update_databricks`**

Add the two new parameters to `update` (line 265) and `_update_databricks` (line 480), documented as on `create`, and pass them through.

In `_update_databricks`, replace the legacy migration block (lines 548-568) with a
secret-mode branch that keeps the legacy behaviour untouched when no scope is given:

```python
        if encryption_secret_scope:
            # Secret mode: relocate into the secret; never seed Lakebase.
            secret_key.preflight_scope(ws, encryption_secret_scope)
            mig_conn, _ = _get_lakebase_connection(
                ws, lakebase_name, lakebase_result=lakebase_result
            )
            try:
                with mig_conn.cursor() as cur:
                    secret_key.preflight_lakebase_privileges(cur, schema_name)
                    lakebase_key = secret_key.read_lakebase_key(cur, schema_name)
            finally:
                mig_conn.close()

            _, wrote = secret_key.resolve_key_for_update(
                ws, encryption_secret_scope, encryption_secret_key,
                lakebase_key, encryption_key,
            )
            if wrote:
                print("   Key written to the secret and verified")
            secret_key.attach_secret_resource(
                ws, app_name, encryption_secret_scope, encryption_secret_key
            )
            print("   Secret resource attached")
        elif encryption_key:
            # Legacy CRITICAL-3 relocation into Lakebase — unchanged.
            print("Relocating encryption key into Lakebase (encryption_keys)...")
            app_for_grant = ws.apps.get(name=app_name)
            grant_client_id = _get_app_client_id(app_for_grant)
            if not grant_client_id:
                print("   Warning: no app client ID — table grant will be skipped")
            mig_conn, _ = _get_lakebase_connection(
                ws, lakebase_name, lakebase_result=lakebase_result
            )
            try:
                with mig_conn.cursor() as cur:
                    _migrate_encryption_key_to_lakebase(
                        cur, schema_name, grant_client_id, encryption_key
                    )
            finally:
                mig_conn.close()
            print("   Key relocated (relocate, not rotate — no re-encryption)")
```

Replace the Task 3 stub with the real value before the `_write_app_yaml` call:

```python
    encryption_secret_resource_key = (
        secret_key.RESOURCE_KEY if encryption_secret_scope else None
    )
```

After `deploy_and_wait` succeeds and `app = ws.apps.get(name=app_name)` has run,
add the gate and DELETE:

```python
        if encryption_secret_scope:
            if not app.url:
                print("   WARNING: no app URL — cannot confirm the key source; "
                      "leaving the Lakebase key row in place")
            elif secret_key.app_reports_secret_source(ws, app.url):
                del_conn, _ = _get_lakebase_connection(
                    ws, lakebase_name, lakebase_result=lakebase_result
                )
                try:
                    with del_conn.cursor() as cur:
                        if secret_key.read_lakebase_key(cur, schema_name):
                            secret_key.delete_lakebase_key_row(cur, schema_name)
                            print("   Lakebase key row deleted — the secret is now "
                                  "the only copy")
                        else:
                            print("   No Lakebase key row to remove")
                except Exception as exc:  # noqa: BLE001 — deploy already succeeded
                    print(f"   WARNING: could not delete the Lakebase key row: {exc}")
                    print(f'   Run manually: DELETE FROM "{schema_name}".'
                          f"encryption_keys WHERE id = 1;")
                finally:
                    del_conn.close()
            else:
                print("   WARNING: the deployed app does not report the secret as "
                      "its key source. Leaving the Lakebase key row in place. This "
                      "is expected if the app version predates secret-mode support.")
```

- [ ] **Step 5: Run the suites**

Run: `.venv/bin/python -m pytest tests/unit/test_deploy_secret_encryption_key.py tests/unit/test_deploy_encryption_key_migration.py -v`
Expected: PASS — the legacy migration tests must still pass, proving the `elif` preserved that path.

- [ ] **Step 6: Commit**

```bash
git add packages/databricks-tellr/databricks_tellr/secret_key.py \
        packages/databricks-tellr/databricks_tellr/deploy.py \
        tests/unit/test_deploy_secret_encryption_key.py
git commit -m "feat(deploy): relocate the key and delete the row behind the health gate"
```

---

### Task 10: Guard legacy-mode update() against a secret-mode app

**Files:**
- Modify: `packages/databricks-tellr/databricks_tellr/secret_key.py`
- Modify: `packages/databricks-tellr/databricks_tellr/deploy.py:480-604`
- Test: `tests/unit/test_deploy_secret_encryption_key.py`

**Interfaces:**
- Consumes: `RESOURCE_KEY`.
- Produces: `app_is_secret_mode(ws, app_name) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
def test_app_is_secret_mode_detects_the_resource():
    ws = MagicMock()
    ws.apps.get.return_value = App(
        name="app", resources=[secret_key.build_secret_resource("s", "k")]
    )
    assert secret_key.app_is_secret_mode(ws, "app") is True


def test_app_is_secret_mode_false_without_the_resource():
    ws = MagicMock()
    ws.apps.get.return_value = App(name="app", resources=[])
    assert secret_key.app_is_secret_mode(ws, "app") is False


def test_update_refuses_legacy_encryption_key_against_secret_mode_app(monkeypatch):
    """Passing a legacy key would recreate the row this design deletes."""
    from databricks_tellr import deploy

    monkeypatch.setattr(secret_key, "app_is_secret_mode", lambda ws, name: True)
    monkeypatch.setattr(deploy, "_get_workspace_client", lambda c, p: MagicMock())
    with pytest.raises(deploy.DeploymentError, match="encryption_secret_scope"):
        deploy._update_databricks(
            app_name="app", app_file_workspace_path="/ws", lakebase_name="lb",
            schema_name="s", encryption_key="Zm9vYmFyYmF6cXV1eA==",
        )
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_deploy_secret_encryption_key.py -v -k "secret_mode or refuses_legacy"`
Expected: FAIL.

- [ ] **Step 3: Implement the detector**

Append to `secret_key.py`:

```python
def app_is_secret_mode(ws: Any, app_name: str) -> bool:
    """True when the app already carries the encryption-key secret resource."""
    try:
        app = ws.apps.get(name=app_name)
    except Exception:  # noqa: BLE001 — absence is not secret mode
        return False
    return any(r.name == RESOURCE_KEY for r in (app.resources or []))
```

- [ ] **Step 4: Add the guard**

In `_update_databricks`, immediately after `ws = _get_workspace_client(client, profile)`:

```python
    if not encryption_secret_scope and secret_key.app_is_secret_mode(ws, app_name):
        if encryption_key:
            raise DeploymentError(
                f"App {app_name} uses a secret-backed encryption key, so passing "
                f"encryption_key would recreate the Lakebase key row this app was "
                f"migrated off — and a mismatched value would silently orphan "
                f"stored credentials. Re-run with "
                f"encryption_secret_scope=... instead."
            )
        print("   Secret-backed encryption key retained (app resource unchanged)")
```

`_read_existing_encryption_key` runs before this in the current flow, so move the
guard above that call to keep the refusal cheap.

- [ ] **Step 5: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_deploy_secret_encryption_key.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/databricks-tellr/databricks_tellr/secret_key.py \
        packages/databricks-tellr/databricks_tellr/deploy.py \
        tests/unit/test_deploy_secret_encryption_key.py
git commit -m "feat(deploy): refuse a legacy encryption_key against a secret-mode app"
```

---

### Task 11: deploy_local.py — flags, config and the non-branching paths

**Files:**
- Modify: `scripts/deploy_local.py:60-78` (`_load_branch_source_config`), `81-144` (`load_deployment_config`), `376-500` (`create_local`), `596-800` (`update_local`), `850-930` (argument parser)
- Modify: `config/deployment.yaml`, `config/deployment.example.yaml`
- Test: `tests/unit/test_deploy_local_secret_mode.py` (create)

**Interfaces:**
- Consumes: all of `secret_key`.
- Produces: `--encryption-secret-scope` / `--encryption-secret-key` CLI arguments; `load_deployment_config` returning `encryption_secret_scope` and `encryption_secret_key`; `_load_branch_source_config` additionally returning `app_name`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_deploy_local_secret_mode.py`:

```python
"""deploy_local secret-mode plumbing."""

import pytest

pytest.importorskip("databricks_tellr", reason="databricks-tellr not installed")

from scripts import deploy_local


def test_parser_accepts_the_secret_flags():
    parser = deploy_local.build_parser()
    args = parser.parse_args([
        "--update", "--env", "devtest",
        "--encryption-secret-scope", "tellr",
        "--encryption-secret-key", "tellr-encryption-key",
    ])
    assert args.encryption_secret_scope == "tellr"
    assert args.encryption_secret_key == "tellr-encryption-key"


def test_config_surfaces_the_secret_keys(tmp_path, monkeypatch):
    cfg = tmp_path / "deployment.yaml"
    cfg.write_text(
        "environments:\n"
        "  devtest:\n"
        "    app_name: db-tellr-devtest\n"
        "    workspace_path: /ws/devtest\n"
        "    encryption_secret_scope: tellr\n"
        "    encryption_secret_key: custom-key\n"
        "    lakebase:\n"
        "      database_name: db-tellr\n"
        "      schema: devtest_app_data\n"
    )
    monkeypatch.setattr(deploy_local, "CONFIG_PATH", cfg)
    out = deploy_local.load_deployment_config("devtest")
    assert out["encryption_secret_scope"] == "tellr"
    assert out["encryption_secret_key"] == "custom-key"


def test_branch_source_config_exposes_the_source_app_name(tmp_path, monkeypatch):
    """The fork needs the source app's name to read its resources; the
    workspace_path carries no recoverable suffix rule."""
    cfg = tmp_path / "deployment.yaml"
    cfg.write_text(
        "environments:\n"
        "  production:\n"
        "    app_name: db-tellr-prod\n"
        "    workspace_path: /ws/prod/tellr\n"
        "    lakebase:\n"
        "      database_name: db-tellr\n"
        "      schema: app_data_prod\n"
    )
    monkeypatch.setattr(deploy_local, "CONFIG_PATH", cfg)
    src = deploy_local._load_branch_source_config("production")
    assert src["app_name"] == "db-tellr-prod"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_deploy_local_secret_mode.py -v`
Expected: FAIL — the parser rejects the flags and the config keys are absent. If `build_parser` does not exist as a separate function, extract the parser construction from `main()` into `build_parser()` first (a pure refactor with no behaviour change) so it is testable.

- [ ] **Step 3: Add the CLI arguments**

In the parser (around line 917), add:

```python
    parser.add_argument(
        "--encryption-secret-scope",
        help="Databricks secret scope for the Fernet encryption key. Opts into "
             "the secret-backed key path; omit for the Lakebase-backed default.",
    )
    parser.add_argument(
        "--encryption-secret-key",
        default=None,
        help="Secret key name within the scope (default: tellr-encryption-key).",
    )
```

- [ ] **Step 4: Surface the config keys**

In `load_deployment_config`, add to the returned dict:

```python
        "encryption_secret_scope": env_config.get("encryption_secret_scope"),
        "encryption_secret_key": env_config.get("encryption_secret_key"),
```

In `_load_branch_source_config`, add to its returned dict:

```python
        # Needed so the fork can read the source app's resources and inherit its
        # secret scope/key. Not derivable from workspace_path — the app name is
        # arbitrary config.
        "app_name": env_config.get("app_name"),
```

And in `load_deployment_config`, surface it on the main config dict alongside the
existing `branch_from_workspace_path`, under the name Task 13 consumes:

```python
        "branch_from_app_name": source.get("app_name"),
```

Document both keys in `config/deployment.example.yaml` under an environment:

```yaml
    # Optional: store the Google-credential Fernet key in a Databricks secret
    # instead of the Lakebase encryption_keys table. Omit for the default path.
    # encryption_secret_scope: "tellr"
    # encryption_secret_key: "tellr-encryption-key"
```

- [ ] **Step 5: Wire secret mode into `create_local` and the non-branching `update_local`**

In `create_local`, resolve the scope with the CLI argument taking precedence over
config, then before `_create_app`:

```python
    scope = encryption_secret_scope or config.get("encryption_secret_scope")
    skey = (
        encryption_secret_key
        or config.get("encryption_secret_key")
        or secret_key.DEFAULT_SECRET_KEY
    )
    if scope:
        secret_key.preflight_scope(ws, scope)
        secret_key.resolve_key_for_create(ws, scope, skey)
```

and pass `encryption_secret_scope=scope, encryption_secret_key=skey` into
`_create_app`, plus `encryption_secret_resource_key=secret_key.RESOURCE_KEY if scope else None`
into `_write_app_yaml`.

In `update_local`, replace the legacy block at lines 700-716. The full
replacement, guarded on the non-branching path only:

```python
            scope = encryption_secret_scope or config.get("encryption_secret_scope")
            skey = (
                encryption_secret_key
                or config.get("encryption_secret_key")
                or secret_key.DEFAULT_SECRET_KEY
            )
            if scope:
                secret_key.preflight_scope(ws, scope)
                mig_conn, _ = _get_lakebase_connection(
                    ws, lakebase_name, lakebase_result=lakebase_result
                )
                try:
                    with mig_conn.cursor() as cur:
                        secret_key.preflight_lakebase_privileges(cur, schema_name)
                        lakebase_key = secret_key.read_lakebase_key(cur, schema_name)
                finally:
                    mig_conn.close()
                legacy_key = _read_existing_encryption_key(ws, workspace_path)
                _, wrote = secret_key.resolve_key_for_update(
                    ws, scope, skey, lakebase_key, legacy_key
                )
                if wrote:
                    print("   Key written to the secret and verified")
                secret_key.attach_secret_resource(ws, app_name, scope, skey)
                print("   Secret resource attached")
            else:
                legacy_key = _read_existing_encryption_key(ws, workspace_path)
                if legacy_key:
                    # CRITICAL-3: relocate before the keyless app.yaml overwrites it
                    print("Relocating encryption key into Lakebase (encryption_keys)...")
                    app_for_grant = ws.apps.get(name=app_name)
                    grant_client_id = _get_app_client_id(app_for_grant)
                    mig_conn, _ = _get_lakebase_connection(
                        ws, lakebase_name, lakebase_result=lakebase_result
                    )
                    try:
                        with mig_conn.cursor() as cur:
                            _migrate_encryption_key_to_lakebase(
                                cur, schema_name, grant_client_id, legacy_key
                            )
                    finally:
                        mig_conn.close()
                    print("   Key relocated")
```

Then, after `deploy_and_wait` returns and the app has been re-fetched, add the
health gate and DELETE — again only on the non-branching path:

```python
            if scope and not branch_from_env:
                app = ws.apps.get(name=app_name)
                if not app.url:
                    print("   WARNING: no app URL — cannot confirm the key source; "
                          "leaving the Lakebase key row in place")
                elif secret_key.app_reports_secret_source(ws, app.url):
                    del_conn, _ = _get_lakebase_connection(
                        ws, lakebase_name, lakebase_result=lakebase_result
                    )
                    try:
                        with del_conn.cursor() as cur:
                            if secret_key.read_lakebase_key(cur, schema_name):
                                secret_key.delete_lakebase_key_row(cur, schema_name)
                                print("   Lakebase key row deleted")
                            else:
                                print("   No Lakebase key row to remove")
                    except Exception as exc:  # noqa: BLE001 — deploy already succeeded
                        print(f"   WARNING: could not delete the key row: {exc}")
                        print(f'   Run manually: DELETE FROM "{schema_name}".'
                              f"encryption_keys WHERE id = 1;")
                    finally:
                        del_conn.close()
                else:
                    print("   WARNING: the deployed app does not report the secret "
                          "as its key source. Leaving the Lakebase key row in "
                          "place. Expected if the app version predates secret mode.")
```

The branching path must never reach either block: a fork has no pre-existing row,
and `_get_lakebase_connection` connects as the deploying human, which breaks
SP-only dev-loop deploys.

- [ ] **Step 6: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_deploy_local_secret_mode.py tests/unit/test_deploy_local_preflight.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/deploy_local.py config/deployment.example.yaml \
        tests/unit/test_deploy_local_secret_mode.py
git commit -m "feat(deploy-local): add secret-mode flags, config keys and non-branching flow"
```

---

### Task 12: deploy_local.sh — accept and forward the flags

**Files:**
- Modify: `scripts/deploy_local.sh:94-107` (argument parsing), `213-230` (pass-through), plus `usage()`

**Interfaces:**
- Consumes: the CLI arguments from Task 11.
- Produces: `--encryption-secret-scope` / `--encryption-secret-key` usable through the documented shell entry point.

- [ ] **Step 1: Add the `case` arms**

Insert **before** the `-h|--help)` arm (line 100), so they precede the `*)` catch-all that would otherwise reject them:

```bash
        --encryption-secret-scope)
            ENCRYPTION_SECRET_SCOPE="$2"
            shift 2
            ;;
        --encryption-secret-key)
            ENCRYPTION_SECRET_KEY="$2"
            shift 2
            ;;
```

- [ ] **Step 2: Add the pass-through**

After the `INSTANCE_ARG` block (line 222), add:

```bash
ENCRYPTION_SECRET_SCOPE_ARG=()
if [ -n "$ENCRYPTION_SECRET_SCOPE" ]; then
    ENCRYPTION_SECRET_SCOPE_ARG=(--encryption-secret-scope "$ENCRYPTION_SECRET_SCOPE")
fi

ENCRYPTION_SECRET_KEY_ARG=()
if [ -n "$ENCRYPTION_SECRET_KEY" ]; then
    ENCRYPTION_SECRET_KEY_ARG=(--encryption-secret-key "$ENCRYPTION_SECRET_KEY")
fi
```

and extend the `python -m scripts.deploy_local` invocation (line 223-230):

```bash
    "${INSTANCE_ARG[@]}" \
    "${ENCRYPTION_SECRET_SCOPE_ARG[@]}" \
    "${ENCRYPTION_SECRET_KEY_ARG[@]}"
```

Without the pass-through the flags are accepted and silently dropped, which is
worse than rejection: the deploy appears to succeed in legacy mode.

- [ ] **Step 3: Document them in `usage()`**

Add to the options list:

```bash
    echo "  --encryption-secret-scope <scope>  Store the Fernet key in this Databricks secret scope"
    echo "  --encryption-secret-key <name>     Secret key name (default: tellr-encryption-key)"
```

- [ ] **Step 4: Verify the flags reach Python**

Run: `bash -n scripts/deploy_local.sh` (syntax check), then:
`./scripts/deploy_local.sh update --env devtest --encryption-secret-scope tellr --help 2>&1 | head -20`
Expected: no "Unknown argument" error.

- [ ] **Step 5: Commit**

```bash
git add scripts/deploy_local.sh
git commit -m "feat(deploy-local): accept and forward the encryption secret flags"
```

---

### Task 13: The devloop fork inherits the source app's secret

**Files:**
- Modify: `scripts/deploy_local.py:260-300` (`_check_branching_preconditions`), `433-445` (`create_local` branching block)
- Test: `tests/unit/test_deploy_local_preflight.py`

**Interfaces:**
- Consumes: `secret_key.app_is_secret_mode`, `secret_key.RESOURCE_KEY`, and `app_name` from `_load_branch_source_config` (Task 11).
- Produces: `_source_secret_config(ws, source_app_name) -> tuple[str, str] | None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_deploy_local_preflight.py`:

```python
def test_fork_inherits_the_source_apps_scope_and_key():
    """A fork must read the same secret: it inherits the source's ciphertext
    via copy-on-write but gets no encryption_keys row."""
    from unittest.mock import MagicMock

    from databricks_tellr import secret_key
    from scripts import deploy_local

    ws = MagicMock()
    ws.apps.get.return_value = MagicMock(
        resources=[secret_key.build_secret_resource("tellr", "tellr-encryption-key")]
    )
    assert deploy_local._source_secret_config(ws, "db-tellr-prod") == (
        "tellr", "tellr-encryption-key",
    )


def test_fork_of_legacy_source_returns_none():
    from unittest.mock import MagicMock

    from scripts import deploy_local

    ws = MagicMock()
    ws.apps.get.return_value = MagicMock(resources=[])
    assert deploy_local._source_secret_config(ws, "db-tellr-prod") is None


def test_fork_refuses_when_source_resources_unreadable():
    from unittest.mock import MagicMock

    from scripts import deploy_local

    ws = MagicMock()
    ws.apps.get.side_effect = Exception("PERMISSION_DENIED")
    with pytest.raises(SystemExit):
        deploy_local._source_secret_config(ws, "db-tellr-prod")
```

Add `import pytest` and `from databricks_tellr.secret_key import SecretKeyError` at the top if absent.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_deploy_local_preflight.py -v -k fork`
Expected: FAIL — `_source_secret_config` does not exist.

- [ ] **Step 3: Implement the detector**

Add to `scripts/deploy_local.py`:

```python
def _source_secret_config(ws, source_app_name: str) -> tuple[str, str] | None:
    """Return the (scope, key) the source app uses, or None if it is legacy.

    The fork inherits the source's ciphertext through the copy-on-write branch but
    gets no encryption_keys row, because secret mode never writes one. So a fork of
    a secret-mode app MUST point at the same secret, or it boots, finds nothing,
    mints a fresh key, and silently destroys its own inherited test data.

    Fetching the source app is the only source of truth here; the
    --encryption-secret-scope flag applies to non-branching deploys only.
    """
    try:
        app = ws.apps.get(name=source_app_name)
    except Exception as exc:
        print(
            f"ERROR: cannot read the source app '{source_app_name}' to determine "
            f"whether it uses a secret-backed encryption key: {exc}\n"
            f"Refusing to fork: if the source is in secret mode, the fork would "
            f"mint a fresh key over inherited ciphertext."
        )
        raise SystemExit(1) from exc
    for r in (app.resources or []):
        if r.name == secret_key.RESOURCE_KEY and getattr(r, "secret", None):
            return r.secret.scope, r.secret.key
    return None
```

- [ ] **Step 4: Use it in the branching path**

In `_check_branching_preconditions`, after the existing legacy-key check, add:

```python
    # Secret mode needs no Lakebase seeding, so the legacy refusal does not
    # apply — but the fork must inherit the same scope/key.
    source_app = config.get("branch_from_app_name")
    if source_app:
        config["_inherited_secret"] = _source_secret_config(ws, source_app)
```

In `create_local`'s branching block, when `_inherited_secret` is set, pass its
scope and key into `_create_app` and set
`encryption_secret_resource_key=secret_key.RESOURCE_KEY` for `_write_app_yaml`.
Do **not** open a Lakebase connection and do **not** run a DELETE on this path:
a fork has no pre-existing row, and a human Postgres login breaks SP-only
dev-loop deploys.

Surface `branch_from_app_name` in `load_deployment_config` from the source config
loaded in Task 11.

- [ ] **Step 5: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_deploy_local_preflight.py -v`
Expected: PASS — including the pre-existing preflight tests.

- [ ] **Step 6: Commit**

```bash
git add scripts/deploy_local.py tests/unit/test_deploy_local_preflight.py
git commit -m "feat(deploy-local): forks inherit the source app's encryption secret"
```

---

### Task 14: Documentation and version bump

**Files:**
- Modify: `docs/technical/databricks-app-deployment.md` (including the stale `GOOGLE_OAUTH_ENCRYPTION_KEY` references at lines 296 and 505)
- Modify: `docs/technical/database-configuration.md`, `docs/technical/google-slides-integration.md` (stale references at lines 115, 120, 344)
- Modify: `docs/technical/export-features.md:251`, `docs/user-guide/07-exporting-to-google-slides.md:110,114`
- Modify: `docs/technical/dev-deploy.md`, `.claude/skills/deploy-tellr-dev/SKILL.md`
- Modify: `README.md` (the `tellr.create` / `tellr.update` snippets)
- Modify: `src/database/models/encryption_key.py:1-9`
- Modify: `packages/databricks-tellr/pyproject.toml`, `packages/databricks-tellr-app/pyproject.toml`

- [ ] **Step 1: Add the reference section to `databricks-app-deployment.md`**

Document both new arguments under the `tellr.create()` and `tellr.update()`
reference, plus a "Secret-backed encryption key" section covering: what it does,
that the scope is created if missing with the creator as sole manager, that the
`valueFrom` entry appears in the generated `app.yaml` while the key itself never
does, the relocate flow with the health gate, and the two accepted risks copied
from the spec. Fix the stale `GOOGLE_OAUTH_ENCRYPTION_KEY` text at lines 296 and
505 to describe the current two-path reality.

- [ ] **Step 2: Update the remaining docs**

`database-configuration.md` and `google-slides-integration.md`: state that the
key lives either in `encryption_keys` or in a Databricks secret, and remove the
stale claims at `google-slides-integration.md:115,120,344`,
`export-features.md:251`, and `07-exporting-to-google-slides.md:110,114`.

`dev-deploy.md` and `.claude/skills/deploy-tellr-dev/SKILL.md`: document the two
new flags with an example, and note that a devloop fork inherits the source app's
scope and key automatically.

`README.md`: add `encryption_secret_scope="tellr"` as a commented-out optional
argument in both snippets.

- [ ] **Step 3: Update the model docstring**

In `src/database/models/encryption_key.py`, extend the accepted-risk paragraph:

```python
"""Application-managed encryption key storage (SDR-4437 CRITICAL-3).

Holds the Fernet master key for OAuth credential/token encryption in the
ACL-governed Lakebase data schema instead of app.yaml. Single-row table
(id = 1). Deliberately shares the data schema's grants: the key carries
the same ACLs as the ciphertext it protects — an explicitly accepted risk
in the SDR-4437 remediation. Do NOT add key-specific grant tightening here.

Deployments that need the key out of Lakebase entirely can opt into the
secret-backed path instead, in which case this table stays empty and the key
lives in a Databricks secret injected as TELLR_ENCRYPTION_KEY. See
docs/superpowers/specs/2026-08-20-secret-backed-fernet-key-design.md.
"""
```

- [ ] **Step 4: Add the `delete()` guard comment**

The spec requires this explicitly under Out of scope: forks share production's
scope and key, so a "cleanup" refactor of `delete()` could destroy the production
master key during a dev-loop teardown. Add to `deploy.py::delete`'s docstring:

```python
    Deliberately does NOT touch secrets or secret scopes. A devloop fork shares
    the production app's secret scope and key by design (so it can decrypt
    inherited ciphertext), which means deleting the secret here would destroy
    production's Fernet master key during a fork teardown. Only the app and its
    Lakebase branch are removed. Do not "clean up" the secret here.
```

- [ ] **Step 5: Bump both versions**

Change `version = "0.4.2"` to `version = "0.5.0"` in both
`packages/databricks-tellr/pyproject.toml` and
`packages/databricks-tellr-app/pyproject.toml`. Minor, not major: the Lakebase
path is untouched and this is purely additive.

- [ ] **Step 6: Run the full unit suite**

Run: `.venv/bin/python -m pytest tests/unit -q`
Expected: no net-new failures versus the pre-existing baseline (SVG/cairo,
mlflow-tracing and autoscaling-mock failures are known and unrelated). Record the
baseline before starting if you have not already.

- [ ] **Step 7: Commit**

```bash
git add docs README.md src/database/models/encryption_key.py \
        packages/databricks-tellr/pyproject.toml \
        packages/databricks-tellr-app/pyproject.toml \
        .claude/skills/deploy-tellr-dev/SKILL.md
git commit -m "docs: document the secret-backed encryption key path and bump to 0.5.0"
```

---

## Live verification (after Task 14, before merge)

Unit tests cannot prove runtime behaviour here; this repo has learned that
repeatedly. Publish a dev build and exercise a real app:

```bash
gh workflow run publish-dev.yml            # note the resolved .devN version
./scripts/deploy_local.sh update --env devtest --profile tellr-dev \
    --from-pypi <version> --encryption-secret-scope tellr
databricks apps logs db-tellr-devtest -p tellr-dev-oauth   # OAuth, not PAT
```

- [ ] Full lifecycle on an app holding real ciphertext: store a Google credential, run `update(encryption_secret_scope=...)`, confirm the boot log reports the key came from the secret resource, confirm the stored credential still decrypts, and confirm `encryption_keys` is empty.
- [ ] Re-run the same update: it must be idempotent — ladder case 1 reuses the secret, and no row remains to delete.
- [ ] Deliberately detach the resource and restart, to observe accepted risk 2 rather than assume it.
- [ ] Create a devloop fork of the secret-mode app and confirm it inherits the scope/key and can decrypt the inherited credential.
