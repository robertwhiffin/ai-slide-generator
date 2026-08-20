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
`TELLR_ENCRYPTION_KEY`, and the platform injects `TELLR_ENCRYPTION_KEY` into
the container environment at deploy time. Nothing about the key appears in the
generated `app.yaml` — the resource declaration is the entire configuration.

The alternative considered and rejected was to write the scope and key *names*
into `app.yaml` and have the app fetch the value at runtime with
`secrets.get_secret`. That is what the docs' own best-practices section
recommends, and it keeps the key out of the container environment entirely. It
was rejected in favour of env injection for simplicity: no runtime workspace
API call on the boot path, and the app's secret access is declared on the app
where it can be audited. The residual exposure is recorded under Accepted
risks below.

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
same two keys, following the `mlflow_tracing` precedent already in `deploy.py` —
YAML values apply first, an explicit argument overrides. The `update()` entry point
takes no `config_yaml_path` parameter; values from deployment YAML are not loaded
on update (per its docstring). For `update()` and `relocate()`, secret-mode
credentials are specified via arguments (no YAML loading on update). If
environment-variable fallback is desired, add layering after argument parsing
(similar to the MLflow precedent, which accepts `TELLR_DEPLOY_MLFLOW_*` variables)
— name the variables explicitly in `deploy.py` around the argument handling,
and document them alongside the argument reference.

### Scope preflight

`_preflight_encryption_scope(ws, scope)` must run **at the very start of
`_create_databricks` and `_update_databricks`, before `_get_or_create_lakebase`**
and before any key material is generated or the app is touched. This placement
ensures that a scope preflight failure aborts before any infrastructure is
created or modified. Failing after a Lakebase is created but before the app is
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

The `put_secret` → read-back round trip that follows doubles as the write and
read permission check, so no separate probe is needed. **Error handling:**
`get_secret` throws `RESOURCE_DOES_NOT_EXIST` (secret not found) and
`PERMISSION_DENIED` (caller lacks READ); the code must distinguish them and
avoid treating a permission denial as "secret absent", which would fall through
to creating a new secret and clobbering the live key. `create_scope` throws
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

Immediately after `create_and_wait`, and unconditionally,
`ws.secrets.put_acl(scope, principal=<sp_client_id>, permission=READ)`. The
call is idempotent and cheap, and it removes the open question of whether
declaring the resource auto-grants the app's service principal — we do not
need to know either way.

**In `scripts/deploy_local.py`:** The `create_local` function calls `_create_app`
(same as `deploy.py:1533`), so the ACL grant must also run there. Add the same
`put_acl` call unconditionally after the returned `app` object, before the
schema setup and deployment (mirroring the deploy.py flow).

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
3. `GOOGLE_OAUTH_ENCRYPTION_KEY` still present in the deployed `app.yaml`
   (never-migrated install) → `_read_existing_encryption_key`
   (`deploy.py:757`) already reads exactly this.
4. Nothing anywhere → generate a fresh key.

Cases 2–4 `put_secret` then read back (with `get_secret()`, base64-decode),
and compare before anything else happens. In secret mode `_migrate_encryption_key_to_lakebase`
(`deploy.py:791`) is skipped entirely: case 3 relocates to the secret, not to
Lakebase.

Attaching the resource must not clobber the rest of the app.
`ws.apps.update(name, app)` takes a whole `App` and replaces `resources`
wholesale, so the update reads the current app with `ws.apps.get`, mutates
**only** `resources` on that object — adding or replacing the
`TELLR_ENCRYPTION_KEY` entry while carrying `app_database` through — and
passes that object back. `compute_size`, `description`,
`default_source_code_path` and `user_api_scopes` all come from the fetched app
rather than being re-derived, so nothing is silently reset. Then the same
idempotent `put_acl`.

**Ordering of the DELETE is load-bearing.** The obvious order — delete the
row, attach the resource, deploy — is wrong. Between the delete and a
successful deploy the app is still running *old* code against an empty table.
`lru_cache` protects the live process, but any platform-initiated restart in
that window sends old code into `_seed_value()`, which mints a fresh key and
orphans every stored credential. So:

```
verify the secret  ->  attach the resource  ->  deploy_and_wait
                   ->  DELETE FROM <schema>.encryption_keys WHERE id = 1
```

The row is deleted **unconditionally** after every successful secret-mode deploy,
not just on the first run (when the ladder resolves to case 2 or 3). This means
every secret-mode `update()` requires a Postgres connection to delete the row.
For branching deploys (dev forks), which must avoid human Postgres logins, the
DELETE is omitted: a fork never has a pre-existing row, so no delete is needed.
The row is removed only once code that prefers the injected variable is
actually live, and only once the secret has been read back and confirmed.

**On fresh-era installs** (where `encryption_keys` was created by the app SP
inside `init_db()`, not by the human's `CREATE TABLE IF NOT EXISTS` in
`_migrate_encryption_key_to_lakebase`), the deploying human may not have
DELETE privilege on the table. Preflight step 2's scope creation runs as the
human; table grants come from the app SP only. Add a permission check in
`_preflight_encryption_scope` to verify the human can DELETE from
`<schema>.encryption_keys` before proceeding (or accept this as an explicit risk
for fresh-era stores turning on secret mode, in which case capture it in
Accepted risks rather than failing the deploy silently). If the DELETE itself
fails, print a loud warning with the exact SQL rather than failing the deploy
— by that point the deploy has succeeded and the key is safely in the secret.

**Minimum app version:** Deploying old app code with secret mode, or rolling
back to an earlier app version after the DELETE, leaves the app running code
that ignores `TELLR_ENCRYPTION_KEY` and finds no row, so it mints a fresh key
and orphans stored credentials. Either refuse secret mode when `app_version` is
below the minimum version that carries the secret-path boot code (once that
version is released), or require an explicit `app_version` parameter to pin the
deployed version before the DELETE.

### `update()` in legacy mode against a secret-mode app

Nothing harmful happens: `_read_existing_encryption_key` returns `None` on a
keyless `app.yaml`, no Lakebase migration runs, and `apps.update` is never
called, so the resource survives. Add a detection line — if the fetched app
already carries a `TELLR_ENCRYPTION_KEY` resource, print that secret mode is
being retained — so nobody concludes the app quietly reverted.

## Dev deploy and the devloop fork

Both `scripts/deploy_local.py` and `scripts/deploy_local.sh` gain
`--encryption-secret-scope` and `--encryption-secret-key`. `config/deployment.yaml`
gains the same two keys per environment, documented in `config/deployment.example.yaml`.

`deploy_local.sh` has a fixed argument allowlist (lines 103-107); add the new flags
there so they pass through to the Python script. Without this, the flags will be
rejected as "Unknown argument" at line 104. 

Secret-mode handling must be added to the branching path (`scripts/deploy_local.py:631-693`)
**within** `_check_branching_preconditions` or immediately after it returns successfully.
The path must NOT call `_get_lakebase_connection` because that connects as the deploying
human (breaking SP-only dev-loop deploys). Within the branching path, detect secret mode
on the source app and inherit the same scope/key (see below), so the forked app has access
to the secret. A fork never needs a DELETE: it is a fresh branch with no pre-existing row
to clean up.

The fork path needs explicit handling. `_check_branching_preconditions`
(`scripts/deploy_local.py:282`) currently refuses to fork when the source
`app.yaml` still carries a legacy key. The refusal is not about CoW inheritance
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

**Implementation note:** The source app's name must be derived from the
`branch_from_workspace_path` (suffix rules from `_resolve_target`, reversing
the `--instance` logic) so `ws.apps.get(name=source_app_name)` can fetch the
source app and read its resources. This derivation logic is new and must be added.

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

### Unit — new `tests/unit/test_deploy_secret_encryption_key.py`

- Preflight: missing scope is created; creation denied yields the actionable
  error; non-Databricks-backed scope is refused.
- `create`: an existing secret is reused and not overwritten; an absent one is
  generated, written, and read back.
- The `update` ladder in all four branches.
- Read-back mismatch aborts **and the row is not deleted**.
- Resource rebuild preserves `app_database` and `user_api_scopes`.
- The DELETE happens only after a successful deploy, asserted by call ordering
  on the mock.
- Secret mode disables the legacy `_migrate_encryption_key_to_lakebase` migration
  (no row exists to migrate, and the secret is the source of truth instead).
  Existing tests in `tests/unit/test_deploy_encryption_key_migration.py` cover
  the legacy path; they should be untouched (run only when no secret scope is
  configured).

### Unit — `tests/unit/test_deploy_app_yaml.py`

Assert that secret mode adds nothing to the generated `app.yaml` (when the
resource declaration alone is sufficient to inject the variable) and that no
key material appears in it — a regression guard against ever putting the key
back in the template. The test at line 37-38 asserts that `"encryption_key"` is
not a parameter to `_write_app_yaml`; this remains true as long as the resource
declaration is sufficient.

**Note on open question 2's fallback:** If the variable does not appear from the
resource declaration alone, the fallback adds a `valueFrom:` entry to the
template. This requires: (1) a new placeholder in `app.yaml.template`; (2) a
new parameter on `_write_app_yaml` to conditionally include it (only in secret
mode); (3) threading that parameter through all four call sites
(`deploy.py:413`, `deploy.py:573`, `deploy_local.py:476`, `deploy_local.py:768`);
(4) updating the test at `test_deploy_app_yaml.py:37-38` to exclude the new
parameter name from the substring check (or rename the parameter to avoid
collision with the "encryption_key" substring). The entry must be conditional
so legacy-mode apps (no secret mode) do not carry an unconditional reference to
a non-existent resource. This is the implementation cost if question 2 is answered "no".

### Live verification

This repo has learned repeatedly that runtime behaviour is only provable on a
deployed app; see the verification section of the 2026-07-20 handoff doc.
Publish a dev build (`gh workflow run publish-dev.yml`) and deploy with
`./scripts/deploy_local.sh update --from-pypi <version>`. Reading app logs
requires an OAuth (U2M) profile — `databricks apps logs <app> -p <oauth-profile>`
refuses PAT auth.

### Blocking implementation

**CRITICAL BLOCKER:**

1. **Can `ws.secrets.get_secret()` be called from the deploy tool
   (a normal user outside a notebook)?** The SDK's docstring states
   *"This API can only be called from the DBUtils interface"* and
   *"Throws `BAD_REQUEST` if normal user calls get secret outside of a
   notebook."* The design's read-back verification, case-1 reuse, and
   ladder-case-1 comparison all depend on this call succeeding. If it fails,
   we cannot verify the written value, cannot safely reuse existing secrets,
   and cannot guard against mismatches. If it is unavailable, the fallback
   is presence-only detection (via `list_secrets()`) plus a required explicit
   `--force` flag to proceed with an overwrite when the secret cannot be
   verified.

**DATA-LOSS GUARD CHOICE (blocks implementation):**

2. **Minimum app version:** Deploying old app code with secret mode, or rolling
   back after the DELETE, leaves the app running code that ignores
   `TELLR_ENCRYPTION_KEY` and mints a fresh key, orphaning stored credentials.
   Choose one approach: (a) refuse secret mode when `app_version` is below the
   minimum version that carries the secret-path boot code (once released), or
   (b) require an explicit `app_version` parameter to pin the deployed version
   before the DELETE. Option (a) gates the feature on a version check; option (b)
   shifts responsibility to the operator. The local-wheel-path flow (`local_wheel_path`
   parameter in `_write_requirements`) bypasses version resolution (L1324-1326),
   so the guard must be enforceable on that path too, or documented as an
   exception with explicit risk acceptance.

### Open questions (defined fallbacks, non-blocking)

2. Is an uppercase-underscore resource key accepted? The existing resource is
   `app_database` and the documented default resource key is `secret`. If not,
   name the resource `tellr_encryption_key` and read that variable instead.
   **Scope of change if answered "no":** The resource name and environment variable
   name are used throughout: the dispatch at L59, the `_validated` secret-mode
   message (L76), all four test assertions (L323-332), and the `monkeypatch.delenv`
   name (L330). The boot code itself is identical either way; only the names change.
3. Does the variable appear from the resource declaration alone? One sentence
   in the docs — *"each one becomes a separate environment variable when
   referenced in `valueFrom`"* — leaves room for doubt. If it does not appear,
   add a single `- name: TELLR_ENCRYPTION_KEY` / `valueFrom: "TELLR_ENCRYPTION_KEY"`
   entry to the template. The boot code is identical either way.

### Verification steps (live testing on deployed app)

1. Was `put_acl` necessary, and in which principal form does it accept the app
   service principal?
2. Full lifecycle on a legacy app holding real ciphertext: `update(scope=...)`
   → boot log shows the secret path → the previously-stored Google credential
   still decrypts → `encryption_keys` is empty.
3. Detach the resource once and restart, to observe accepted risk 2 rather than
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
