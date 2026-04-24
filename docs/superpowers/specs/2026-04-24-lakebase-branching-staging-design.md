# Staging deploys against an ephemeral branch of production Lakebase

**Status:** Approved design (2026-04-24)
**Author:** robert.whiffin@databricks.com

## Problem

Today, `deploy_local.sh update --env staging` deploys the staging app against a
sibling schema (`app_data_staging`) on the same Lakebase instance as production.
That schema has its own, diverging data set. It does not exercise the code path
against prod-shaped data, so staging deploys can pass while a prod deploy of
the same build fails against prod's actual schema and data.

We want staging to be a one-shot integration test *against prod's current
database state* before every prod push.

## Solution

Staging deploys target an **ephemeral copy-on-write branch** of the production
Lakebase project. On every `deploy_local.sh create|update --env staging`:

1. If `branches/staging` exists on the prod Lakebase project, delete it.
2. Create a fresh `branches/staging` forked from `branches/production`.
3. Point the staging app at the new branch via `LAKEBASE_PG_HOST` /
   `LAKEBASE_ENDPOINT_NAME` / `LAKEBASE_SCHEMA`.
4. Deploy. First startup runs migrations against a byte-identical copy of prod.

On `deploy_local.sh delete --env staging`, the app and the branch are both
removed.

This gives a full mirror: staging reads schema `app_data_prod` on the branch
and uses prod's `GOOGLE_OAUTH_ENCRYPTION_KEY`, so encrypted fields (notably
Google OAuth credentials) decrypt. Staging ≈ prod for testing purposes.

## Decisions

| # | Decision | Chosen | Why |
|---|----------|--------|-----|
| 1 | Branch lifecycle | Ephemeral per-deploy | Long-lived branches diverge from prod and eventually mask real breakage. |
| 2 | Data + encryption | Full mirror (same key, same schema) | Staging's job is "does this work against prod" — rotating secrets defeats the point and makes OAuth credentials un-decryptable. |
| 3 | Branch naming | Fixed name `staging`, recreate on every deploy | Keeps Lakebase console tidy; matches ephemeral lifecycle. |
| 4 | Scope | Staging only (for now) | Dev stays cheap / empty. Dev engineers wanting prod-data tests deploy to staging. |
| 5 | Implementation shape | Config-driven via `branch_from` field in `deployment.yaml` | Avoids magic strings; generalizes cleanly if we later opt another env into branching. |

## Configuration

`config/deployment.yaml` — staging entry loses `schema` and gains
`branch_from`:

```yaml
staging:
  app_name: "db-tellr-staging"
  description: "AI Slide Generator - Staging (prod branch)"
  workspace_path: "/Workspace/Users/robert.whiffin@databricks.com/.apps/staging/tellr"
  permissions:
    - user_name: "robert.whiffin@databricks.com"
      permission_level: "CAN_MANAGE"
  compute_size: "MEDIUM"
  env_vars:
    ENVIRONMENT: "staging"
    LOG_LEVEL: "DEBUG"
    LAKEBASE_INSTANCE: "db-tellr"
    # LAKEBASE_SCHEMA derived from branch_from env — not set here
  lakebase:
    database_name: "db-tellr"
    branch_from: "production"       # NEW: name of env to branch from
    capacity: "CU_1"
    # schema removed — inherited from branch_from env
```

Dev and prod entries are unchanged. `app.yaml.template` is unchanged — the
template already takes `LAKEBASE_PG_HOST` / `LAKEBASE_ENDPOINT_NAME` /
`LAKEBASE_SCHEMA` / `GOOGLE_OAUTH_ENCRYPTION_KEY` as substitutions.

**Target branch naming convention:** for any env in branching mode, the target
branch is named after the env itself. Staging → `branches/staging`. If a future
env `preview` also sets `branch_from: production`, it would target
`branches/preview`. There is no per-env override of the target branch name;
keeping the env name and the branch name aligned removes a dimension of config
drift.

**Legacy `app_data_staging` schema:** the existing `app_data_staging` schema on
the production Lakebase instance becomes orphaned after this change — nothing
will write to it. Leave it alone. Dropping it is out of scope (it's harmless,
and a manual `DROP SCHEMA` remains an option later if storage cost ever
matters).

## Deployment flow

### `deploy_local.sh create|update --env staging`

1. Load config. If `lakebase.branch_from` is set, enter branching mode.
   Otherwise, behave as today.
2. **Preflight** (branching mode only; fail loud, stop):
   1. `branch_from` resolves to an env that exists in `deployment.yaml`.
   2. Source and target share the same `lakebase.database_name`.
   3. Source app is deployed — `ws.workspace.download(<source>/app.yaml)`
      succeeds.
   4. Source app.yaml contains `GOOGLE_OAUTH_ENCRYPTION_KEY`.
   5. Lakebase is autoscaling — `_probe_autoscaling_available(ws)` AND
      `ws.postgres.get_project(name="projects/<db>")` succeed.
   6. Source branch exists — `ws.postgres.get_branch(...)` succeeds for
      `projects/<db>/branches/<branch_from>`.
3. **Recreate ephemeral branch.** Delete `projects/<db>/branches/staging` if
   present, then `ws.postgres.create_branch(parent=...)` with
   `spec.parent_branch="projects/<db>/branches/production"`. Wait for the
   operation. Poll `list_endpoints(parent=branches/staging)` for a ready
   endpoint; capture `endpoint_name` and `host`.
4. Build a `lakebase_result` dict with the **staging branch's** host/endpoint,
   the same shape `_get_or_create_lakebase_autoscaling()` returns today. Every
   existing helper that accepts `lakebase_result` then routes to the staging
   branch automatically.
5. **Create the app** (only on `create`; `update` skips this). Same call as
   today — no `AppResourceDatabase` because autoscaling.
6. **Register the staging app's SP on the staging branch** via
   `_ensure_sp_autoscaling_role(ws, project_name, client_id, branch_name="staging")`.
   (The currently-hardcoded `branches/production` path is parameterised.)
7. **Setup schema = grant-only.** The branch already carries `app_data_prod`
   and its tables. `_setup_database_schema()` runs unchanged —
   `CREATE SCHEMA IF NOT EXISTS` is a no-op, then `_grant_schema_permissions()`
   gives the staging SP access.
8. **Generate app.yaml** with the staging branch's `host`/`endpoint_name`,
   prod's schema (`app_data_prod`), and prod's encryption key (read from
   `<branch_from>/app.yaml` via `_read_existing_encryption_key`).
9. **Deploy.** First startup runs `init_database()` — migrations are
   idempotent on existing columns; new columns get added. That is the test.

### `deploy_local.sh delete --env staging`

1. Delete the app (as today via `databricks_tellr.deploy.delete`).
2. Delete `projects/<db>/branches/staging`. Silently swallow "not found" so the
   command is re-runnable.

### `--reset-db` on a branching env

Prints `WARNING: --reset-db is a no-op for branching envs (each deploy is
already a fresh branch)` and skips `_reset_schema`. No behavioural difference —
the branch about to be destroyed on the next deploy would have been reset
anyway.

## Code changes

### Modified helpers (backward-compatible)

- `_ensure_sp_autoscaling_role(ws, project_name, client_id, branch_name: str = "production")`
  — thread `branch_name` through instead of hardcoding it in the function body.
- `_get_or_create_lakebase_autoscaling(ws, database_name, capacity, branch_name: str = "production")`
  — optional `branch_name` so staging can fetch endpoint info from
  `branches/staging`. Creation path unchanged (create_project still only
  creates the project; the `production` branch is auto-created).

Both defaults remain `"production"` so existing callers keep working.

### New helpers in `packages/databricks-tellr/databricks_tellr/deploy.py`

- `_branch_exists(ws, project_name, branch_name) -> bool` — wraps
  `ws.postgres.get_branch`, returns False on "not found".
- `_create_branch_from(ws, project_name, source_branch, target_branch) -> dict`
  — calls `ws.postgres.create_branch` with parent set to the source branch,
  waits for the operation, then polls `list_endpoints` for a ready endpoint.
  Returns a `lakebase_result`-shaped dict pointing at the new branch.
- `_delete_branch(ws, project_name, branch_name) -> None` — idempotent; no-op
  on "not found".
- `_recreate_ephemeral_branch(ws, project_name, source_branch, target_branch) -> dict`
  — composition of delete + create. Single call site; exists for
  `create_local`/`update_local` readability.

### New helper in `scripts/deploy_local.py`

- `_load_branch_source_config(all_environments, branch_from_env_name) -> dict`
  — returns `{workspace_path, schema, database_name}` from the source env.
  Caller validates `database_name` matches staging's.

### Modified flow functions

- `load_deployment_config(env)` (scripts/deploy_local.py) — if
  `lakebase.branch_from` is set, derive schema from source env and add two new
  output keys: `branch_from_env` and `branch_from_workspace_path`.
- `create_local`, `update_local` — if `branch_from` set, run preflight then the
  branch recreation before app creation; read encryption key from
  `branch_from_workspace_path`; pass `lakebase_result` pointing at the staging
  branch.
- `delete_local` — if `branch_from` set, delete the branch after deleting the
  app.

### Unchanged helpers that Just Work

- `_get_lakebase_connection` — reads host/endpoint from `lakebase_result`.
- `_setup_database_schema`, `_reset_schema`, `_grant_schema_permissions` —
  operate on whatever connection `_get_lakebase_connection` returns.
- `_write_app_yaml` — already templates
  `LAKEBASE_PG_HOST` / `LAKEBASE_ENDPOINT_NAME` / `LAKEBASE_SCHEMA` from the
  `lakebase_result` dict.
- `_read_existing_encryption_key` — already takes an arbitrary
  `workspace_path`. Called against `branch_from_workspace_path` for staging.

## Error handling

All preflight failures raise `DeploymentError` with an actionable message and
happen **before** any mutating call. A bad staging deploy never half-creates a
branch, half-deploys an app, or leaves orphaned resources.

| Failure | Message |
|---------|---------|
| `branch_from` unset in referenced env | `branch_from "production" not found in deployment config` |
| Different `database_name` between source and target | `branching requires same database_name; staging=<x>, production=<y>` |
| Source not deployed | `production not deployed — deploy production first` |
| Key missing from source app.yaml | `GOOGLE_OAUTH_ENCRYPTION_KEY missing from production app.yaml` |
| Lakebase is provisioned, not autoscaling | `Lakebase branching requires autoscaling; <db> is not an autoscaling project` |
| Source branch missing | `source branch "production" not found in project <db>` |

### Runtime failures during branch ops

- **Delete-old-branch, "not found"** → treat as success.
- **Delete-old-branch, "active connections"** → retry once after 5 s, then
  surface. The previous staging app's connections should drain when
  `ws.apps.get_or_deploy` cycles compute; if this keeps biting in practice,
  add an explicit "stop app" step before branch delete.
- **Create-branch operation times out** → surface with the operation ID.
- **SP role creation fails** → surface (same failure mode as today's prod
  path).

### Orphan risk

If branch creation succeeds but `_create_app` fails, we have a fresh branch
with no app attached. Acceptable — next staging deploy deletes it and
recreates. Self-healing. No rollback machinery.

## Testing

### Unit tests (new)

- `tests/unit/test_load_deployment_config_branching.py`
  - `branch_from` unset → behaviour unchanged from today.
  - `branch_from: production` → resolved config has prod's schema and both
    new keys populated.
  - `branch_from` points at missing env → `DeploymentError`.
  - `database_name` mismatch → `DeploymentError`.
- `tests/unit/test_branch_helpers.py` (with `ws` mocked)
  - `_branch_exists`: False on "not found", True on success, surfaces other
    errors.
  - `_delete_branch`: idempotent on "not found".
  - `_create_branch_from`: correct `parent_branch` in spec, polls endpoints.
  - `_recreate_ephemeral_branch`: delete-then-create order.
- `tests/unit/test_deploy_local_preflight.py`
  - Each of the 6 preconditions fails with the expected message.
  - On preflight failure, no mutating `ws.postgres` call is made.

### Regression

- `tests/unit/test_database_autoscaling.py` — re-run to confirm the modified
  signatures with default args still match every existing call site.

### Integration (manual)

Documented here; not automated. Hits a real Databricks workspace.

1. **Baseline:** `deploy_local.sh update --env development --profile <p>`
   succeeds. (Non-branching path untouched.)
2. **Staging create:** `deploy_local.sh create --env staging --profile <p>`.
   Verify in the Lakebase UI that `projects/db-tellr/branches/staging` exists
   as a child of `branches/production`. Verify the deployed staging `app.yaml`
   has prod's encryption key and `LAKEBASE_SCHEMA=app_data_prod`. Log in to
   the staging app and confirm a copy of your own prod sessions/decks is
   visible and a decrypted Google OAuth credential works.
3. **Staging update:** `deploy_local.sh update --env staging --profile <p>`.
   Confirm `branches/staging` has a newer creation timestamp. Any data you
   wrote in step 2 is gone.
4. **Staging delete:** `deploy_local.sh delete --env staging --profile <p>`.
   Confirm both the app and `branches/staging` are gone. `branches/production`
   untouched.
5. **Production untouched:** during 2–4, prod app continues serving with no
   extra deploys triggered.
6. **Precondition failures:** temporarily rename the prod workspace_path and
   run `update --env staging` → should fail at preflight with
   `production not deployed — deploy production first`, and no `ws.postgres`
   mutation has been attempted.

## Out of scope

- Branch-per-PR / branch-per-git-branch. Could be added later by giving
  `branch_from` a templating syntax (e.g., `staging-${GIT_SHA}`) without
  changing the rest of the flow.
- Dev env branching. Staging-only for now.
- Automating the integration test above in CI.
- Stopping an in-flight staging app before branch delete (only needed if the
  "active connections" failure mode becomes routine).
