# Design: secret-backed Fernet key as a second deployment method

> Date: 2026-08-20. Status: approved design, not yet implemented.
> Supersedes nothing. The Lakebase-backed path from SDR-4437 CRITICAL-3 stays
> exactly as it is; this adds a parallel, opt-in path.

## Why

The Fernet master key that encrypts Google OAuth credentials and tokens
currently lives in the `encryption_keys` table of the app's Lakebase data
schema (`src/database/models/encryption_key.py`). That table deliberately
shares the data schema's grants, so the key carries the same ACLs as the
ciphertext it protects — an explicitly accepted risk recorded in the SDR-4437
remediation.

Security has asked that the key live in a Databricks secret instead. Rather
than replace the existing mechanism, this design adds a second deployment
method: an operator who passes a secret scope gets a secret-backed key, and
everyone else keeps the Lakebase behaviour unchanged.

Prior art worth reading first: `docs/superpowers/specs/2026-07-20-fernet-key-net-handoff.md`
documents why boot-time rewriting of `app.yaml` is architecturally impossible
(the app's service principal cannot read or write its own source `app.yaml`)
and why the human-run deploy tool is the only place privileged enough to move
key material. This design respects that constraint: every write to the secret
happens in the deploy tool, never in the app.

## Mechanism

Databricks Apps secret resources. Per
<https://docs.databricks.com/aws/en/dev-tools/databricks-apps/secrets>:

> When you deploy an app that uses secret resources, Databricks injects each
> secret as an environment variable. The name of each variable matches the
> resource key that you defined when you added the secret.

So the deploy tool declares an `AppResourceSecret` with resource key
`TELLR_ENCRYPTION_KEY`. **The declaration alone injects nothing** — verified on a
live app (see Spike results). The generated `app.yaml` must also carry an `env:`
entry mapping the resource into the environment:

```yaml
  - name: TELLR_ENCRYPTION_KEY
    valueFrom: "TELLR_ENCRYPTION_KEY"
```

That entry is the only key-related content in `app.yaml` and it holds no key
material — only a resource reference. It must be written in secret mode and
omitted in legacy mode, where it would point at a resource the app does not
have. Consequently `_write_app_yaml` gains a parameter and the template gains a
conditional block; `Template.substitute` is strict, so the placeholder must be
supplied (as an empty string) on every one of its four call sites.

The alternative considered was to write the scope and key *names* into `app.yaml`
and have the app fetch the value at runtime with `secrets.get_secret`. That is
what the docs' own best-practices section recommends, and it keeps the key out of
the container environment entirely. The spike confirmed the alternative **is**
available — `get_secret` works from a plain shell — so this is a genuine
trade-off, chosen for simplicity: no runtime workspace API call on the boot path,
and the app's secret access is declared on the app where it can be audited. The
residual exposure is recorded under Accepted risks below.

## Spike results (verified live, 2026-08-21)

Run against a disposable app (`db-tellr-fernet-spike`) and secret scope in the
tellr-dev workspace, both since deleted. These supersede the corresponding open
questions.

| Question | Answer |
| --- | --- |
| `get_secret` from a plain shell, outside a notebook? | **Works.** The SDK docstring's "only from the DBUtils interface" / `BAD_REQUEST` warning did not reproduce. |
| Encoding of `GetSecretResponse.value`? | **base64.** `b64decode(value) == original`; `Fernet(raw)` raises `ValueError`, so a missed decode fails loudly rather than silently. |
| Spaces in a secret *key* name? | **Accepted.** `"Tellr encryption key"` was written successfully. The documented charset rule does not apply to key names, so the hyphenated default is a style choice, not a constraint. |
| Uppercase-underscore resource key? | **Accepted.** `TELLR_ENCRYPTION_KEY` created without complaint. |
| Does attaching the resource auto-grant the app SP `READ`? | **Yes.** The SP's `READ` ACL appeared on the scope with no `put_acl` call. |
| Does the resource declaration alone inject the env var? | **No.** With the resource attached and no `env:` entry, no `TELLR_*` variable existed in the container. |
| Does `valueFrom` inject it? | **Yes.** With the `env:` entry, `TELLR_ENCRYPTION_KEY` was present, length 44 — the raw Fernet key, already decoded. No base64 handling needed in the app. |
| `apps.update` with a GET-fetched `App`? | **Fails:** `InvalidParameterValue: Compute size updates are not supported in this update API.` |
| Correct `apps.update` construction? | Build a fresh `App(name=..., resources=..., description=..., user_api_scopes=..., default_source_code_path=...)` and **omit `compute_size`**. Omitted fields are wiped — `description` became `''` and `user_api_scopes` became `None` — so every mutable field must be carried explicitly. |
| Can the deploying human `SELECT`/`DELETE` on `encryption_keys`? | **Yes here, but not for the reason assumed.** It works because the deployer is a member of `databricks_superuser`, which holds explicit privileges on every table in the schema — not because of table ownership. |

Two consequences worth stating plainly. First, the auto-grant removes `put_acl`
from the design entirely, which in turn removes the MANAGE requirement that made
fork creation problematic: a fork only needs the resource declaration copied.
Second, the `apps.update` result means the "round-trip the fetched object"
prescription was wrong and must be replaced with explicit field-carrying.

On the Lakebase privilege question, the shared-owner model does behave as the
review claimed — in `app_data_prod`, 30 of 31 tables are owned by
`tellr_app_owners` (which the human is not an inheriting member of), and only
`encryption_keys` is human-owned, because the legacy migration created it with
`CREATE TABLE IF NOT EXISTS` as the human. The relocate therefore works for an
admin deployer via `databricks_superuser`, and would fail for a deployer without
it. That makes a `has_table_privilege` preflight probe the right resolution
rather than an accepted risk: it is one query, and it converts a silent
data-loss path into an actionable preflight error.

## Boot resolution

`src/core/encryption.py`. Today's `get_encryption_key()` body moves verbatim
into `_from_lakebase()`, and the entry point becomes a two-branch dispatch:

```python
@lru_cache(maxsize=1)
def get_encryption_key() -> bytes:
    env_key = os.getenv("TELLR_ENCRYPTION_KEY", "").strip()
    if env_key:
        return _validated(env_key.encode())   # secret resource attached
    return _from_lakebase()                   # today's body, unchanged
```

Properties this gives us:

- **The legacy path is bit-for-bit unchanged.** `_from_lakebase` keeps
  SELECT-first resolution, `_seed_value()`, and the race-safe
  `INSERT ... ON CONFLICT` unchanged, so every existing test in
  `tests/unit/test_encryption.py` passes untouched.
- **Secret mode never writes to Lakebase.** The secret branch returns before
  any database access. This is the property the unit tests must pin down.
- **A corrupt secret fails loudly.** `_validated()` (already present) raises
  `RuntimeError` on a value that is not a valid Fernet key, so a mangled
  secret refuses to start rather than silently producing garbage. Its message
  needs a secret-mode variant naming the resource key.

The injected variable is deliberately **not** named
`GOOGLE_OAUTH_ENCRYPTION_KEY`. That name is the legacy migration seed source
at `src/core/encryption.py:90`, and its entire purpose is to write the value
*into* `encryption_keys` — reusing it would push the secret straight back into
the database this design exists to remove it from.

`ensure_encryption_key()` needs no change. `packages/databricks-tellr-app/databricks_tellr_app/run.py:93`
already calls it pre-fork inside a `try/except` that logs a traceback and exits
1, so a broken secret kills the deployment before any uvicorn worker forks,
rather than failing once per worker.

Rotation still requires an app restart, because `lru_cache` holds the key for
the process lifetime. That is equally true of the Lakebase path today, so it
is not a regression — but do not expect live rotation.

## Deploy-time interface

Both public entry points gain the same two arguments, threaded through to
`_create_databricks` / `_update_databricks`:

```python
encryption_secret_scope: str | None = None
encryption_secret_key: str = "tellr-encryption-key"
```

Presence of `encryption_secret_scope` selects secret mode. In legacy mode
`encryption_secret_key` is ignored. The default key name is hyphenated because
secret scope names are documented as *"alphanumeric characters, dashes,
underscores, and periods"* (no `@` — `@` is not a valid character in scope or
key names), and key names go through the same validator in practice.

**`create()` only:** `config_yaml_path` and `config/deployment.yaml` accept the
same two keys (`encryption_secret_scope`, `encryption_secret_key`), following
the `mlflow_tracing` precedent already in `deploy.py` — YAML values apply
first, an explicit argument overrides.

To implement: extend `deploy.py::_load_deployment_config` (currently line 850)
and `scripts/deploy_local.py::load_deployment_config` (currently line 81) to
read and return the new keys from the environment's YAML section. Both loaders
return a flat dict; add the new keys there. The `mlflow_tracing` precedent
(`_mlflow_flat_from_env_section` + substitutions) is app.yaml-placeholder-shaped
and not directly reusable — instead, add the keys directly to each loader's
return dict, mirroring how `lakebase_name`, `schema_name`, and `app_name` are
returned.

The `update()` entry point takes no `config_yaml_path` parameter; values from
deployment YAML are not loaded on update (per its docstring). For `update()`,
secret-mode credentials are specified via arguments only (no YAML loading on
update). If environment-variable fallback is desired, add layering after
argument parsing (similar to the MLflow precedent, which accepts
`TELLR_DEPLOY_MLFLOW_*` variables) — name the variables explicitly in `deploy.py`
around the argument handling, and document them alongside the argument reference.

Note: `_create_databricks`'s mutual-exclusion check is `if any([lakebase_name,
schema_name, app_name, app_file_workspace_path])`, so the two new arguments are
silently permitted alongside `config_yaml_path` while the four core ones are
not. This is intentional (argument overrides YAML) and safe, but worth noting
as consistent with the design's rule that arguments override YAML.

### Scope preflight

`_preflight_encryption_scope(ws, scope)` must run **after argument and YAML
config resolution (so the scope value is known), but before `_get_or_create_lakebase`,
and before any key material is generated or the app is touched**. In
`_create_databricks`, this is after lines 367-378 (YAML loading) but before
`_get_or_create_lakebase`. This placement ensures that a scope preflight failure
aborts before any infrastructure is created or modified. Failing after a Lakebase is created but before the app is
deployed would leave an orphaned or partially-configured Lakebase instance.

1. Already in `ws.secrets.list_scopes()` → confirm it is Databricks-backed,
   done.
2. Absent → `ws.secrets.create_scope(scope)` with `initial_manage_principal`
   **omitted**, making the creator sole manager. Explicitly not `"users"`,
   which would grant every workspace user MANAGE on the scope holding the key.
   **Deliberate trade-off:** Only the scope creator can run subsequent deploys
   and rotate the key. If another human or CI needs to run `update()` later,
   they will need MANAGE permission granted by the creator (or the scope must
   be pre-created by someone who grants MANAGE to the intended operators/CI).
   This is the least-privilege choice; a future enhancement could extend step 2
   to accept an optional `initial_manage_principal` parameter to grant MANAGE
   to a named group.
3. Creation failures map to actionable messages rather than a raw API error:
   - permission denied → name the `databricks secrets create-scope <scope>`
     command to hand to an admin, and the MANAGE grant needed back.
   - scope limit reached → workspace is at its secret-scope limit (1,000 by
     default, raisable on request); pass an existing scope instead.
   - anything else → surface the original error alongside the manual command.
4. Non-Databricks-backed scopes are refused. The design both writes the value
   and reads it back for verification; Key Vault-backed scopes are written and
   read through Key Vault, not this API.

The `put_secret` → read-back round trip tests write and read permission. The
spike removed the MANAGE concern that used to live here: attaching the resource
auto-grants the app SP `READ`, so the design makes no `put_acl` call and the
operator needs only WRITE+READ on the scope.

Preflight must additionally probe the Lakebase privilege the relocate depends
on, before any key material is written:
`SELECT has_table_privilege(current_user, '<schema>.encryption_keys', 'SELECT')`
and the same for `DELETE`. On installs where the app SP created the table and
`REASSIGN OWNED` re-homed it to `tellr_app_owners`, a deployer outside
`databricks_superuser` has neither, and the relocate would otherwise read the
denial as "no row" and mint a fresh key. Abort preflight instead.

**Error handling:** `get_secret` throws `RESOURCE_DOES_NOT_EXIST` (secret not
found) and `PERMISSION_DENIED` (caller lacks READ); the code must distinguish
them and avoid treating a permission denial as "secret absent", which would
fall through to creating a new secret and clobbering the live key. `create_scope` throws
different errors: `RESOURCE_ALREADY_EXISTS`, `RESOURCE_LIMIT_EXCEEDED`,
`INVALID_PARAMETER_VALUE`, `BAD_REQUEST` (e.g., invalid name), `CUSTOMER_UNAUTHORIZED`,
or `UNAUTHENTICATED` — not `PERMISSION_DENIED`. Handle creation failures by
mapping observable errors to actionable messages (e.g., `CUSTOMER_UNAUTHORIZED`
or `BAD_REQUEST` may indicate a permission issue; surface that to the caller
alongside the manual command).

### `create()`

Key resolution runs before the app exists:

- Secret already present at `(scope, key)` → read it with `get_secret()`,
  base64-decode the returned value (the Databricks Secrets API returns values
  as base64 in JSON), validate as Fernet, **reuse it**, and print that it is
  being reused. Never overwrite: an existing secret may already protect
  ciphertext from a previous install pointed at the same place.
- Otherwise `Fernet.generate_key()` → `put_secret(scope, key, string_value=...)`
  → read back with `get_secret()`, base64-decode, compare, validate.

`_create_app` then builds `resources` as today's `AppResourceDatabase`
(provisioned Lakebase only) **plus**:

```python
AppResource(
    name="TELLR_ENCRYPTION_KEY",
    secret=AppResourceSecret(scope=scope, key=key,
                             permission=AppResourceSecretSecretPermission.READ),
)
```

**Note:** `_create_app` builds `app_resources = []` for autoscaling Lakebase
and tries autoscaling first; the secret resource must be appended in both
the provisioned and autoscaling branches.

No `put_acl` call is needed: the spike confirmed that attaching the resource
auto-grants the app's service principal `READ` on the scope. Do not add one —
it is the only call that would require MANAGE, and requiring MANAGE is what
made fork creation unworkable.

**In `scripts/deploy_local.py`:** `create_local` calls `_create_app` on its own
path, so the secret resource must be appended there too — but no ACL grant is
required in either place, per the auto-grant finding above.

For the **non-branching path in `update_local`** (when `branch_from_env` is
`None`): the secret-mode key ladder, resource attachment, and DELETE must also
run in `update_local` — not just in `_update_databricks`. Currently `update_local`
reimplements the flow with its own `_read_existing_encryption_key` +
`_migrate_encryption_key_to_lakebase` (lines 700-712), so apply the same
secret-mode changes here: if `encryption_secret_scope` is set, run the ladder
to resolve or generate the key, read it back, attach the resource, deploy, then
DELETE (or skip DELETE if branching).

Schema setup and deploy are unchanged. `_write_app_yaml` is untouched.

### `update()` — the relocate

Key resolution is a ladder; first hit wins:

1. A valid Fernet key already at `(scope, key)` → read it, validate as Fernet,
   and reuse it **only if it matches the key currently in encryption_keys**
   (if a row exists). A mismatch is a hard error: reusing a mismatched key
   would orphan ciphertext encrypted under the other key, exactly as
   `_migrate_encryption_key_to_lakebase` guards against (`deploy.py:834-842`).
   This is what makes re-runs idempotent.
2. An `encryption_keys` row in Lakebase → this is the key being relocated.
   **Must fail closed on read errors:** any error other than
   `RESOURCE_DOES_NOT_EXIST` (table/row genuinely absent) aborts. Fresh-era
   installs see `PERMISSION_DENIED` because the human deployer lacks SELECT on
   the app-owned schema; this must not fall through to case 3 as "no row".
3. `GOOGLE_OAUTH_ENCRYPTION_KEY` still present in the deployed `app.yaml`
   (never-migrated install) → `_read_existing_encryption_key`
   (`deploy.py:757`) already reads exactly this.
4. Nothing anywhere → generate a fresh key.

Cases 2–4 `put_secret` then read back (with `get_secret()`, base64-decode),
and compare before anything else happens. In secret mode `_migrate_encryption_key_to_lakebase`
(`deploy.py:791`) is skipped entirely: case 3 relocates to the secret, not to
Lakebase.

Attaching the resource must not clobber the rest of the app, and the obvious
approach does not work. Passing a GET-fetched `App` straight back to
`ws.apps.update` fails with `InvalidParameterValue: Compute size updates are not
supported in this update API` (verified). `update` is also a full replace on the
fields it does accept: omitting `description` blanked it to `''` and omitting
`user_api_scopes` blanked it to `None`.

So the update reads the current app with `ws.apps.get` and builds a **fresh**
`App`, carrying every mutable field across explicitly and omitting
`compute_size`:

```python
cur = ws.apps.get(name=app_name)
ws.apps.update(name=app_name, app=App(
    name=app_name,
    description=cur.description,
    default_source_code_path=cur.default_source_code_path,
    user_api_scopes=cur.user_api_scopes,
    resources=<cur.resources with TELLR_ENCRYPTION_KEY added or replaced>,
    # compute_size deliberately omitted — passing it is rejected
))
```

`app_database` is carried through as part of `cur.resources`. No `put_acl`
follows.

**Ordering of the DELETE is load-bearing.** The obvious order — delete the
row, attach the resource, deploy — is wrong. Between the delete and a
successful deploy the app is still running *old* code against an empty table.
`lru_cache` protects the live process, but any platform-initiated restart in
that window sends old code into `_seed_value()`, which mints a fresh key and
orphans every stored credential. So:

```
verify the secret  ->  attach the resource  ->  deploy_and_wait
                   ->  poll /api/health for key source == "secret"
                   ->  DELETE FROM <schema>.encryption_keys WHERE id = 1
```

The health poll is the gate, not the deploy's success: see "DELETE gating" below
for the full rule, the fail-closed requirement, and why the check runs on every
secret-mode update rather than only the relocating one. Forks are excepted. The
row is removed only once the live app has confirmed it is reading the secret, and
only once that secret has been read back and confirmed.

**On fresh-era installs** (where `encryption_keys` was created by the app SP
inside `init_db()`, not by the human's `CREATE TABLE IF NOT EXISTS` in
`_migrate_encryption_key_to_lakebase`), the deploying human may not have
DELETE privilege on the table — the spike confirmed the mechanism, and that it
works for an admin deployer only because membership of `databricks_superuser`
carries explicit privileges on every table in the schema, not because of
ownership. `_preflight_encryption_scope` therefore probes
`has_table_privilege(current_user, '<schema>.encryption_keys', 'SELECT'/'DELETE')`
before any key material is written, and aborts if either is missing. If the
DELETE still fails at the end, print a loud warning with the exact SQL rather
than failing the deploy — by that point the deploy has succeeded and the key is
safely in the secret.

### `update()` in legacy mode against a secret-mode app

When `update()` is called without `encryption_secret_scope` on an app that
already carries the `TELLR_ENCRYPTION_KEY` resource:

- If `encryption_key` parameter is `None` (the default): nothing harmful happens.
  `_read_existing_encryption_key` returns `None` on a keyless `app.yaml`, no
  Lakebase migration runs, and `apps.update` is never called, so the resource
  survives. Add a detection line — if the fetched app already carries a
  `TELLR_ENCRYPTION_KEY` resource, print that secret mode is being retained — so
  nobody concludes the app quietly reverted.
- If `encryption_key` parameter is **not** `None` (explicitly passed): **refuse
  the operation**. Passing a legacy key value would run `_migrate_encryption_key_to_lakebase`,
  recreating the row this design exists to delete. If the passed value differs
  from the secret, it creates a mismatch that silently orphans ciphertext on
  boot. Add a guard: if the fetched app carries the `TELLR_ENCRYPTION_KEY`
  resource, raise an error refusing `encryption_key` and directing the user to
  use `update(encryption_secret_scope=...)` instead if they need to rotate the
  key in the secret.

## Dev deploy and the devloop fork

Both `scripts/deploy_local.py` and `scripts/deploy_local.sh` gain
`--encryption-secret-scope` and `--encryption-secret-key`. `config/deployment.yaml`
gains the same two keys per environment, documented in `config/deployment.example.yaml`.

`deploy_local.sh` needs two edits:
- Add `case` arms for `--encryption-secret-scope` and `--encryption-secret-key`
  *before* the `*)` catch-all (around line 103), alongside `--instance` at 96-99.
  Without this, the flags are rejected as "Unknown argument".
- Add pass-through for the new flags to the Python invocation: construct
  `ENCRYPTION_SECRET_SCOPE_ARG` and `ENCRYPTION_SECRET_KEY_ARG` arrays (similar
  to `FROM_PYPI_ARG` and `INSTANCE_ARG` at lines 215-222) and include them in
  the `python -m scripts.deploy_local` call (lines 223-230). Without the
  pass-through, the flags are accepted and silently dropped — a worse failure
  than rejection, because the deploy appears to succeed in legacy mode. 

Secret-mode handling must be added to the branching path (`scripts/deploy_local.py:631-693`)
**within** `_check_branching_preconditions` or immediately after it returns successfully.
The path must NOT call `_get_lakebase_connection` because that connects as the deploying
human (breaking SP-only dev-loop deploys). Within the branching path, detect secret mode
on the source app and inherit the same scope/key (see below), so the forked app has access
to the secret. A fork never needs a DELETE: it is a fresh branch with no pre-existing row
to clean up.

The fork path needs explicit handling. `_check_branching_preconditions`
(`scripts/deploy_local.py:260`; the `_read_existing_encryption_key` call is at
line 282 inside it) currently refuses to fork when the source `app.yaml` still
carries a legacy key. The refusal is not about CoW inheritance
(after the legacy-key migration, the source app's row in the encryption_keys
table is present and inherited by the fork via copy-on-write); it is because
the fork cannot write to the source app's `app.yaml`, and seeding the fork's
own `encryption_keys` table requires a human Postgres login (breaking SP-only
dev-loop deploys). In secret mode, there is no need to seed a Lakebase row —
the fork inherits the source's ciphertext via CoW and must inherit the same
secret scope and key to decrypt it. A fork of a secret-mode app that is not
given the same secret boots, finds no environment variable, finds no row (since
secret mode never writes to Lakebase), and mints a fresh key against inherited
ciphertext. Harmless to production, but it silently destroys the fork's test
data and presents as a bug in whatever was being tested.

So: detect secret mode on the source app by fetching its resources, have the
fork **inherit the same scope and key automatically** rather than requiring the
operator to retype them, and refuse only if the source is in secret mode but
its resources cannot be read. This is the only source of truth for the fork's
credentials; the `--encryption-secret-scope` CLI flag does not override detected
resources (it applies only to non-branching deploys). This mirrors the existing
precondition's intent.

**Implementation note:** The source app's name is available directly as
`environments[branch_from]["app_name"]` (already loaded in the config dict).
Pass it through `_load_branch_source_config`'s return dict alongside the
existing `workspace_path`, `schema`, and `database_name` keys, so
`ws.apps.get(name=source_app_name)` can fetch the source app and read its
resources. The `workspace_path` carries no recoverable suffix rule; the app
name is arbitrary config that cannot be derived from the path.

## Accepted risks

1. **The injected key is visible on the app's Environment page.** The docs'
   best-practices section states that *"Secret values injected directly as
   environment variables appear in plaintext on the app's Environment page"*
   and recommends fetching at runtime instead. Anyone with MANAGE on the app
   can therefore read the key from the UI, and any subprocess inheriting the
   full container environment sees it. `src/services/converter_jail/jail.py:63`
   already scrubs the environment for the converter child, but the huashu
   bootstrap invoked from the `app.yaml` `command:` block inherits everything.
   Accepted: the key is out of Lakebase and out of `app.yaml`, which is what
   was asked for.

2. **Detaching the resource silently reverts to Lakebase, orphaning
   ciphertext.** With no marker in `app.yaml`, the app cannot distinguish "not
   in secret mode" from "in secret mode, resource detached". If someone removes
   the resource — the docs note the app then "loses access to the secret unless
   you add it again" — boot falls through to `_from_lakebase()`, finds the
   empty post-relocate table, and mints a fresh key, making every stored Google
   credential undecryptable.

   Two mitigations were considered and both declined: a plain-value marker
   environment variable in `app.yaml` to make the mode explicit, and a
   ciphertext-aware guard refusing to generate a fresh key while rows exist in
   `google_global_credentials` / `google_oauth_tokens` (the guard parked as
   YAGNI in `docs/superpowers/specs/2026-07-20-fernet-key-net-handoff.md:222`).
   Detaching an app resource requires MANAGE on the app, and no mechanism short
   of that permission prevents it. Accepted deliberately: if someone detaches
   the resource, so be it.

## Testing

### Unit — `tests/unit/test_encryption.py`

- `TELLR_ENCRYPTION_KEY` set → returned as the key, **and `encryption_keys`
  stays empty**. This is the load-bearing assertion: secret mode must never
  write to Lakebase.
- Environment variable set with a row also present → the environment variable
  wins **and the row is left unmodified** (verifying that the lookup is
  read-first, not write-on-presence).
- Environment variable set to a non-Fernet value → `RuntimeError`.
- Environment variable absent → every existing legacy test passes unchanged.
- `monkeypatch.delenv("TELLR_ENCRYPTION_KEY", raising=False)` in the `db`
  fixture, alongside the `GOOGLE_OAUTH_ENCRYPTION_KEY` delenv already there for
  exactly this hermeticity reason.

### Unit — `tests/unit/test_deploy_local_preflight.py` (existing tests affected)

Existing assertions in `test_deploy_local_preflight.py:25-35` assert
`_check_branching_preconditions(mock_ws, good_config) is None` (no return value).
If the secret-mode detection moves inside `_check_branching_preconditions` or
immediately after (L293-295), the return contract may change. Additionally, new
`ws.apps.get` calls on mock objects require proper setup — `MagicMock().resources`
must be iterable by default or mocked. Update these tests alongside the
implementation.

### Unit — new `tests/unit/test_deploy_secret_encryption_key.py`

- Preflight: missing scope is created; creation denied yields the actionable
  error; non-Databricks-backed scope is refused; the
  `has_table_privilege` probe aborts when the deployer lacks SELECT or DELETE on
  `encryption_keys`, before any key material is written.
- `create`: an existing secret is reused and not overwritten; an absent one is
  generated, written, and read back.
- The `update` ladder in all four branches, including ladder case 2 read errors
  (PERMISSION_DENIED vs. RESOURCE_DOES_NOT_EXIST distinction).
- Read-back mismatch aborts **and the row is not deleted**.
- Resource rebuild preserves `app_database` and `user_api_scopes`.
- The DELETE happens only after a successful deploy, asserted by call ordering
  on the mock.
- The health-source gate, which is the highest-value test in this file because
  every branch of it is a data-loss guard. Each of these must leave the row
  intact: the app reports `"lakebase"`; the key-source field is **absent**
  (the old-app-code case); the body is unparseable; the endpoint returns non-200;
  the poll times out. Only a reported `"secret"` permits the DELETE.
- A row left over from a previously-interrupted run is deleted on a later update
  even though that run resolves to ladder case 1 and performs no relocate.
- Secret mode disables the legacy `_migrate_encryption_key_to_lakebase` migration
  (no row exists to migrate, and the secret is the source of truth instead).
  Existing tests in `tests/unit/test_deploy_encryption_key_migration.py` cover
  the legacy path; they should be untouched (run only when no secret scope is
  configured).
- Fork path: source app's secret mode is detected via `ws.apps.get().resources`,
  source app name is passed through config dict, and fork inherits scope/key
  automatically. Fork creation does **not** run DELETE (fresh branch, no row).

### Unit — `tests/unit/test_deploy_app_yaml.py`

Assert that secret mode adds nothing to the generated `app.yaml` (when the
resource declaration alone is sufficient to inject the variable) and that no
key material appears in it — a regression guard against ever putting the key
back in the template. The test at line 37-38 asserts that `"encryption_key"`
is not a literal parameter name in `sig.parameters`; this remains true as long
as the resource declaration is sufficient (exact-key membership check, not
substring matching).

**Note on open question 2's fallback:** If the variable does not appear from the
resource declaration alone, the fallback adds a `valueFrom:` entry to the
template. This requires: (1) a new placeholder in `app.yaml.template`; (2) a
new parameter on `_write_app_yaml` to conditionally include it (only in secret
mode); (3) threading that parameter through all four call sites
(`deploy.py:413`, `deploy.py:573`, `deploy_local.py:476`, `deploy_local.py:768`);
(4) ensuring any new parameter name does not break the invariant that
`"encryption_key"` is not a parameter (exact membership check). The entry must
be conditional so legacy-mode apps (no secret mode) do not carry an
unconditional reference to a non-existent resource. This is the implementation
cost if question 2 is answered "no".

### Live verification

This repo has learned repeatedly that runtime behaviour is only provable on a
deployed app; see the verification section of the 2026-07-20 handoff doc.
Publish a dev build (`gh workflow run publish-dev.yml`) and deploy with
`./scripts/deploy_local.sh update --from-pypi <version>`. Reading app logs
requires an OAuth (U2M) profile — `databricks apps logs <app> -p <oauth-profile>`
refuses PAT auth.

### Blocking implementation

**RESOLVED by the spike — no longer blocking:** `ws.secrets.get_secret()` works
from the deploy tool outside a notebook. Read-back verification, case-1 reuse and
the ladder-case-1 comparison are all available as designed, and the
presence-only/`--force` fallback is dropped: it is unnecessary, and it would have
converted the one guard against clobbering a live key into an opt-in.

**RESOLVED — no version gate, superseded by the health-source gate below.**
Deploying pre-feature app code alongside secret mode would leave the app ignoring
`TELLR_ENCRYPTION_KEY`, and a DELETE at that point orphans stored credentials at
the next restart. This is reachable *unintentionally*: `databricks-tellr` does not
depend on `databricks-tellr-app`, so `pip install -U databricks-tellr` upgrades the
tool alone, and a default `app_version=None` then resolves to whatever stale app
version sits in the deployer's venv (`_resolve_installed_app_version`,
`deploy.py:1355`). A version-comparison guard was rejected as unnecessary: the
health-source gate makes an old app fail closed — it has no key-source field, so
the DELETE never runs, the row is retained, and the app keeps reading Lakebase.
Graceful degradation rather than delayed data loss.

### DELETE gating — decided: verify the live app, then delete

The DELETE is gated on positive proof that the deployed app is reading from the
secret, and it is evaluated on **every** secret-mode update rather than only on
the run that relocates.

1. The app reports its key *source* — never the key — on `/api/health`
   (`src/api/main.py:490`), as `"secret"` or `"lakebase"`.
2. After `deploy_and_wait`, the deploy tool polls that endpoint.
3. `DELETE FROM <schema>.encryption_keys WHERE id = 1` runs only when the app
   reports `"secret"` **and** a row actually exists.

**The poll must fail closed.** A missing field, an unparseable body, a non-200,
or a timeout all mean "not confirmed", and not-confirmed means do not delete —
print what was observed and leave the row. The missing-field case is exactly the
old-app-code case above, so treating it as "probably fine" would reintroduce the
hazard this gate exists to remove.

Evaluating on every update (rather than only when this run relocated) is
deliberate. A run that writes the secret but dies before the DELETE leaves a row;
on the next update ladder case 1 short-circuits, so a relocate-only condition
would never revisit it and key material would sit in Lakebase indefinitely while
every signal reported healthy. The cost is one `SELECT` per secret-mode update
over a human Lakebase connection — where `_update_databricks` currently opens
none outside the one-time legacy migration (`deploy.py:552-558`). Accepted: the
guarantee that Lakebase holds no key material is the point of the work.

**The fork path is excepted.** It has no row by construction and must not open a
human Lakebase connection — `scripts/deploy_local.py` avoids one there because it
would break SP-only dev-loop deploys.

### Open questions — both closed by the spike

1. **Uppercase-underscore resource key accepted?** Yes. `TELLR_ENCRYPTION_KEY`
   was accepted as a resource key, so no rename cascade is needed.
2. **Does the variable appear from the resource declaration alone?** No — the
   `valueFrom` entry is required. This is now part of the design rather than a
   fallback; see Mechanism, and the `_write_app_yaml` parameter it implies.

One question the spike did **not** answer, worth knowing before implementation
because it bears on accepted risk 2: what happens when `app.yaml` carries a
`valueFrom` entry for a resource that is *not* attached. If the deploy rejects
it, the "someone detached the resource" case becomes a loud deploy failure
instead of a silent revert to Lakebase, which would partly close that risk for
free. The reverse case (resource attached, no `valueFrom`) was tested and simply
yields no variable.

### Verification steps (live testing on deployed app)

1. Full lifecycle on a legacy app holding real ciphertext: `update(scope=...)`
   → boot log shows the secret path → the previously-stored Google credential
   still decrypts → `encryption_keys` is empty.
2. Detach the resource once and restart, to observe accepted risk 2 rather than
   assume it.

## Docs and version

- `docs/technical/databricks-app-deployment.md` — argument reference plus a
  secret-backed-key section (also update `296`, `505` which still document
  `GOOGLE_OAUTH_ENCRYPTION_KEY` as the production key source — now stale).
- `docs/technical/database-configuration.md`,
  `docs/technical/google-slides-integration.md` — where the key lives, now two
  options (also update `115`, `120`, `344` in google-slides-integration.md which
  still document the old source).
- `docs/technical/dev-deploy.md`, `.claude/skills/deploy-tellr-dev/SKILL.md` —
  the dev flags.
- `docs/technical/export-features.md:251` — still documents
  `GOOGLE_OAUTH_ENCRYPTION_KEY` as the production key source (now stale after
  Lakebase migration); update to current state.
- `docs/user-guide/07-exporting-to-google-slides.md:110,114` — similar stale
  references; update to current state.
- `config/deployment.example.yaml`, and the `create`/`update` snippets in
  `README.md`.
- `src/core/encryption.py` module docstring — rewrite for two paths.
- `src/api/main.py:490` (`/api/health`) — add the key-source field the DELETE gate
  reads. Report the source only (`"secret"` / `"lakebase"`), never the key.
- `src/database/models/encryption_key.py:5-8` — the accepted-risk paragraph
  gains a pointer to the secret-backed alternative.
- Minor version bump on `packages/databricks-tellr/pyproject.toml` and
  `packages/databricks-tellr-app/pyproject.toml`. The legacy path is untouched,
  so this is purely additive.

## Out of scope

- Key rotation. Neither path supports live rotation; `lru_cache` means a
  changed key needs an app restart.
- Re-encryption of existing ciphertext. Every path here relocates a key, never
  rotates one.
- Removing or deprecating the Lakebase path.
- Any boot-time modification of `app.yaml` — architecturally impossible, see
  the 2026-07-20 handoff doc.
- **Secret cleanup on `delete()`.** The fork path shares the production app's
  scope and key (by design, so inherited ciphertext is readable). Fork teardown
  calls `delete_local` → `delete()`. The `delete()` function must NOT touch
  secrets or scopes; it must only delete the app and branch. This is enforced
  by construction (secrets API calls require explicit principal permission, and
  only the app resource is modified), but the implementation should carry a
  clear comment to prevent future "cleanup" refactors from destroying production's
  master key during a dev-loop fork teardown.
