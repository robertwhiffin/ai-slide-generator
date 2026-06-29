# Ephemeral per-instance dev environments branched from prod Lakebase

**Status:** Approved design (2026-06-29)
**Author:** robert.whiffin@databricks.com

> **Dependency / blocker for the migration story.** Live probing (2026-06-29)
> found that a forked branch inherits prod's objects *owned by the prod app's
> service principal*, and a *different* (dev) SP cannot `ALTER`/`DROP` those
> inherited tables — so the app's `ALTER`-heavy migrations fail on a fork. The
> branch mechanism in this spec is proven and independent, but **full
> prod-fidelity migrations require a separate "Lakebase table ownership
> (shared-owner)" workstream** — see [Dependency: Lakebase table ownership](#dependency-lakebase-table-ownership-shared-owner-model)
> below. Until that lands, a `devloop` instance supports new-table creation +
> DML against prod data, but **not** migrations that alter inherited prod
> tables.

## Problem

The dev pipeline publishes dev `.devN` builds to real PyPI and deploys them to a
single `devtest` app backed by a static schema (`devtest_app_data`) on the prod
`db-tellr` Lakebase instance. That schema diverges from prod, so a dev deploy can
pass while the same build would fail against prod's actual schema and data. It
also cannot decrypt prod-encrypted fields (Google OAuth credentials use prod's
`GOOGLE_OAUTH_ENCRYPTION_KEY`).

We are building the foundation for **agentic dev loops**: multiple concurrent
deployments at any one time, each iterating on its own build. A single shared
`devtest` env cannot support that — concurrent deploys would clobber each other.

We want every dev deployment to run against a **fresh copy of production** — same
schema, same data, same encryption key — and for multiple such deployments to
coexist in isolation.

## Solution

A single template env **`devloop`** in `config/deployment.yaml` carries
`branch_from: production` plus *base* names. An `--instance <id>` flag fills in
the unique parts at deploy time, giving each concurrent loop an isolated app and
an isolated copy-on-write branch of production Lakebase.

| Resource | Pattern | Example (`--instance agent-7f3a`) | Lifecycle |
|----------|---------|-----------------------------------|-----------|
| App compute | `<base app_name>-<instance>` | `db-tellr-dev-agent-7f3a` | created once, reused every deploy |
| Lakebase branch | fixed `dev-<instance>` off `branches/production` | `branches/dev-agent-7f3a` | delete + recreate (fresh prod) every deploy |
| Workspace path | `<base workspace_path>/<instance>` | `.../.apps/devloop/agent-7f3a` | — |

Because the branch is forked from `branches/production` and the app inherits
prod's schema (`app_data_prod`) and prod's `GOOGLE_OAUTH_ENCRYPTION_KEY`, each
dev instance is a full mirror of prod: it reads prod-shaped data and decrypts
prod-encrypted fields. Dev ≈ prod for testing purposes. (Running *migrations*
against that mirror additionally requires the ownership dependency — see the
callout above and the dependency section below.)

The deploy loop is unchanged in shape (manual, from a laptop):

```bash
gh workflow run publish-dev.yml                 # publishes the next .devN
./scripts/deploy_local.sh create --env devloop --instance agent-7f3a \
    --profile tellr-dev --from-pypi <version>   # first deploy of this instance
./scripts/deploy_local.sh update --env devloop --instance agent-7f3a \
    --profile tellr-dev --from-pypi <version>   # subsequent iterations
./scripts/deploy_local.sh delete --env devloop --instance agent-7f3a \
    --profile tellr-dev                         # teardown
```

## Decisions

| # | Decision | Chosen | Why |
|---|----------|--------|-----|
| 1 | Identity of a deployment | Explicit `--instance <id>` flag | Most flexible for an agent-driven loop; no git coupling; works from laptop or CI. Drives app name, branch name, and workspace path from one id. |
| 2 | Concurrency model | Many concurrent instances, each its own app + branch | Foundation for agentic dev loops; a fixed shared name would clobber. |
| 3 | Branch freshness | Fresh copy of prod **every** deploy | Simplest correct model — sidesteps "did this build touch the data model?". Every deploy is a faithful prod-fidelity test. Copy-on-write makes it cheap. |
| 4 | Branch mechanism | `delete_branch().wait()` then `create_branch()` on a **fixed name** | Empirically proven clean (~6s, see below). Gives a stable 1:1 `dev-<instance>` branch ↔ app mapping. |
| 5 | App compute | Created once, reused every deploy | `update` rewrites `requirements.txt` to the new `.devN` and redeploys; compute never recreated. |
| 6 | Cleanup | Manual `delete --instance <id>`; branch TTL as orphan backstop | No reaper/cron for now (YAGNI). TTL auto-GCs instances nobody tears down, softening the manual-only risk. |
| 7 | Data + encryption | Full mirror (prod schema, prod key) | The point is prod-fidelity testing; rotating secrets defeats it and makes OAuth credentials un-decryptable. |
| 8 | Implementation shape | Reuse existing `branch_from` machinery, parameterized by `--instance` | The staging design already built `_branch_exists`/`_create_branch_from`/`_recreate_ephemeral_branch` and a `branch_from`-aware config loader. This change parameterizes them, it does not rebuild them. |
| 9 | Migration support | Deferred to the ownership dependency | The dev SP can't `ALTER` inherited prod-SP-owned tables (proven). Shipping order: branch mechanism first (new-table + DML works), then the shared-owner workstream unblocks `ALTER` migrations. |

## Empirical findings (live `db-tellr` probes, 2026-06-29)

Two throwaway probes against the live autoscaling `projects/db-tellr` project
(forking only throwaway branches off `branches/production`; production never
mutated) settled the branch mechanism:

1. **`create_branch(replace_existing=True)` does NOT re-copy prod.** It is an
   idempotent upsert: a marker row written to a branch *survived* a second
   `create_branch(..., replace_existing=True)` call, and the endpoint/host did
   not change. So `replace_existing` preserves existing branch data — it cannot
   deliver "fresh copy of prod each deploy". **Not used.**
2. **`delete_branch().wait()` then `create_branch()` on the same fixed name is
   clean.** Recreate succeeded on the first attempt in ~6s. The current code's
   comment claiming fixed-name reuse "collides for many minutes after delete"
   **does not reproduce**. The timestamp-suffix + TTL workaround it justifies is
   therefore unnecessary and is removed.

## Dependency: Lakebase table ownership (shared-owner model)

This is a **separate, prod-touching workstream** that gates the migration story
of this feature. It is documented in full here so a fresh agent can pick it up
and drive it independently. (Companion notes:
`memory/lakebase_branch_permissions.md`; Databricks runbook ES-1783639,
Confluence "Change table ownership to a group", page `6095568937`.)

### The problem

Each Databricks App gets its **own** managed service principal (SP). Lakebase
objects are owned by **whichever SP created them**. On `db-tellr`, the entire
`app_data_prod` schema and all ~20 tables are owned by the **prod app's SP**
(`161834b3-c54d-4b24-82c4-8f0166c191f4`). A forked branch inherits that
ownership. The new dev app's SP is a *different* identity, and in Postgres only
the **owner** (or a true superuser) may `ALTER`/`DROP` a table.

The app's migrations (`src/core/database.py`, `_run_migrations`) are
`ALTER`-heavy — `ADD COLUMN`, `ALTER COLUMN ... TYPE`, `DROP COLUMN`,
`RENAME` against existing tables. So a dev build whose schema has moved since the
fork point fails on first startup with `must be owner of table`. New-table
`CREATE` and DML succeed (the existing `GRANT CREATE/USAGE` + DML grants cover
them); altering inherited tables does not.

### What was proven (live probes, 2026-06-29)

- **The deployer cannot fix it.** Run as the human deployer (`robert.whiffin`),
  `ALTER ... OWNER`, `ALTER SCHEMA OWNER`, and `REASSIGN OWNED BY <prod_sp>` all
  fail. Only the **current owner** (the prod SP) or a true superuser can move
  ownership.
- **`databricks_superuser` is a red herring.** It has `rolsuper = false`; you
  cannot `SET ROLE` to it, and membership does not grant ownership-bypass. Only
  `databricks_control_plane` is a true superuser (`rolsuper = true`, unusable).
- **`generate_database_credential` cannot impersonate** another SP; the `claims`
  param scopes permissions *down*, it does not switch identity.
- **The fix works: a member of the owning role can `ALTER` via `INHERIT`.** A
  real login identity that is a *member* of a normal shared owning role can
  `ALTER`/`DROP` that role's tables **as itself, without `SET ROLE`**, including
  on a fork. This is the mechanism the dev SP will use. `REASSIGN OWNED BY <self>
  TO <shared_role>` also works for moving one's own objects into the shared role.

### Required end state

All of `app_data_prod`'s objects are owned by a **shared owner** that *every*
app SP (prod + each dev) is a member of. Then any member SP can migrate the
inherited tables on its fork.

### Two implementation routes (pick one in the dependency's own spec)

1. **Permanent shared Postgres role** (recommended — built only from proven
   mechanisms, no unsolved steps):
   - Create a permanent `NOLOGIN` role, e.g. `tellr_app_owners`.
   - **One-time prod transfer**, run *as the prod SP* (the current owner): grant
     the prod SP membership in `tellr_app_owners`, then
     `REASSIGN OWNED BY <prod_sp> TO tellr_app_owners` for `app_data_prod`.
   - **Keep new objects shared-owned:** the app's migration step ends with
     `REASSIGN OWNED BY CURRENT_USER TO tellr_app_owners` (the SP owns anything
     it just created and is a member of the shared role, so this is allowed) — or
     the app `SET ROLE`s the shared role before DDL if SET membership is granted.
   - **Per dev deploy:** `GRANT tellr_app_owners TO "<dev_sp_client_id>"` on the
     branch (run by a role with admin on `tellr_app_owners`). The dev SP then
     inherits owner rights on the inherited tables.
2. **Native Databricks group** (more native membership management via the
   Databricks UI/API; matches the runbook):
   - Group is created in Settings → Identity and access → Groups; made a
     connectable Postgres role via `ws.postgres.create_role(identity_type=GROUP,
     auth_method=LAKEBASE_OAUTH_V1)`.
   - Ownership transferred with the runbook's temp-role bridge, finishing by
     **connecting *as* the group** and `REASSIGN OWNED BY temp_table_owners TO
     "<group>"`.
   - **Open issue:** connecting as the group via the SDK
     (`generate_database_credential` token + `-U <group>`) failed with
     "Malformed OAuth token"; the runbook uses a **UI-issued** OAuth token. The
     SDK path for connect-as-group is unsolved and must be figured out before
     this route is viable.

### What a fresh agent should do next

1. Write a dedicated spec `…/specs/<date>-lakebase-shared-owner-design.md`,
   choosing route 1 or 2 (recommend route 1).
2. Decide who/what runs the one-time prod ownership transfer *as the prod SP*
   (the deploy runs as the human, which can't — needs the app/SP to do it, e.g.
   a guarded one-shot path in `init_database`, or a manual maintenance script run
   with prod-SP creds).
3. Add the per-deploy "grant new SP into the shared owner" step to the `devloop`
   create flow (`scripts/deploy_local.py`), alongside `_ensure_sp_autoscaling_role`.
4. Add the "keep new objects shared-owned" step to the app's migration path.
5. Validate end-to-end on a throwaway project with a **real** member SP
   (authenticate as the SP, not via `SET ROLE`) — confirm it can `ALTER` a
   shared-owned table on a fork.

### Interaction with this spec

- `_setup_database_schema` / `_grant_schema_permissions` stay (they cover
  USAGE/CREATE/DML and are still needed).
- The `devloop` create flow gains the "add SP to shared owner" call once the
  dependency lands.
- Until then, `devloop` is usable for non-migrating builds; document the
  limitation (see Out of scope).

## Feasibility (verified)

- `projects/db-tellr` is an **autoscaling** Lakebase project, and
  `branches/production` exists.
- The `production` env in `deployment.yaml` uses `database_name: db-tellr` and
  `schema: app_data_prod` — so `devloop` (same `database_name`) satisfies the
  same-instance branching precondition, and inherits `app_data_prod`.

## Configuration

New `devloop` env in `config/deployment.yaml` (additive — existing `devtest`,
`chatfix`, `test`, `development`, `production` entries are untouched):

```yaml
devloop:
  app_name: "db-tellr-dev"                 # base; --instance appended -> db-tellr-dev-<id>
  description: "AI Slide Generator - Dev loop (prod branch)"
  workspace_path: "/Workspace/Users/robert.whiffin@databricks.com/.apps/devloop"  # base; /<id> appended
  permissions:
    - user_name: "robert.whiffin@databricks.com"
      permission_level: "CAN_MANAGE"
  compute_size: "MEDIUM"
  env_vars:
    ENVIRONMENT: "development"
    LOG_LEVEL: "DEBUG"
    LAKEBASE_INSTANCE: "db-tellr"
    # LAKEBASE_SCHEMA inherited from branch_from (app_data_prod) — not set here
  lakebase:
    database_name: "db-tellr"
    branch_from: "production"               # ephemeral branch of production per deploy
    capacity: "CU_1"
    # schema removed — inherited from branch_from env
```

**Naming conventions** (driven by `--instance <id>`):

- App: `<app_name>-<id>` → `db-tellr-dev-<id>`.
- Branch: `dev-<id>` off `branches/production`. Fixed name, delete+recreate each
  deploy. (Prefix `dev-` keeps the branch namespace tidy and distinct from
  `production`/`staging`.)
- Workspace path: `<workspace_path>/<id>`.

**`--instance` validation:** `id` must match `^[a-z][a-z0-9-]*$` and be ≤59
chars (so `dev-<id>` stays within the Lakebase 1–63-char branch-id limit). A
non-conforming id fails fast with an actionable error.

## Deployment flow

### `deploy_local.sh create --env devloop --instance <id> [--from-pypi <ver>]`

1. Load config. `--instance` requires the env to set `lakebase.branch_from`
   (else error). Derive `app_name`, `workspace_path`, and target branch
   `dev-<id>` from the base config + id.
2. **Preflight** (existing 6 checks, fail loud before any mutation):
   1. `branch_from` resolves to an env in `deployment.yaml`.
   2. Source and target share `lakebase.database_name`.
   3. Source app deployed (`production` app.yaml downloadable).
   4. Source app.yaml contains `GOOGLE_OAUTH_ENCRYPTION_KEY`.
   5. Lakebase is autoscaling (`_probe_autoscaling_available` + `get_project`).
   6. Source branch `production` exists.
3. **Recreate ephemeral branch:** `_recreate_ephemeral_branch` =
   `_delete_branch(dev-<id>)` (idempotent no-op if absent) then
   `_create_branch_from(production → dev-<id>)` with a fixed branch id and a
   TTL backstop. Wait for the create op; poll `list_endpoints` for a ready
   endpoint; capture `host`/`endpoint_name`. Returns a `lakebase_result`-shaped
   dict with `branch_id = dev-<id>`.
4. **Create the app** `db-tellr-dev-<id>`.
5. **Register the app SP** on `branches/dev-<id>` via
   `_ensure_sp_autoscaling_role(..., branch_name="dev-<id>")`.
6. **Setup schema = grant-only.** The branch already carries `app_data_prod`;
   `CREATE SCHEMA IF NOT EXISTS` is a no-op, then grant the SP access.
   *(Ownership dependency: once the shared-owner workstream lands, this step also
   adds the new SP to the shared owner — `GRANT tellr_app_owners TO "<sp>"` — so
   the SP can `ALTER` inherited tables.)*
7. **Generate app.yaml** with the branch's `host`/`endpoint_name`, prod's schema
   (`app_data_prod`), and prod's encryption key (read from `production`
   app.yaml).
8. **Deploy.** First startup runs migrations against the fresh prod copy.
   New-table + DML migrations work today; `ALTER`s on inherited prod tables fail
   until the ownership dependency lands (see the dependency section).

### `deploy_local.sh update --env devloop --instance <id> [--from-pypi <ver>]`

Same as `create` except step 4 is skipped — the app already exists (error "run
create first" if it does not). The branch is still delete+recreated (fresh prod
copy), and the app compute is reused: `requirements.txt` is rewritten to the new
`.devN` and the app redeployed.

### `deploy_local.sh delete --env devloop --instance <id>`

1. Delete the app `db-tellr-dev-<id>`.
2. Delete `branches/dev-<id>` (idempotent — swallow "not found" so the command
   is re-runnable).

### `--reset-db` on a branching env

Remains a no-op with a warning — each deploy is already a fresh branch.

## Code changes

### `packages/databricks-tellr/databricks_tellr/deploy.py`

- **`_create_branch_from(ws, project_name, source_branch, branch_id)`** — take
  the fixed `branch_id` directly instead of building `{prefix}-{timestamp}`.
  Keep the create-with-TTL + endpoint-poll body. Return `branch_id` unchanged in
  the result dict.
- **`_recreate_ephemeral_branch(ws, project_name, source_branch, branch_id)`** —
  call `_delete_branch(ws, project_name, branch_id)` then
  `_create_branch_from(...)`. Update the docstring/comment: the async-purge
  collision the old comment describes does not reproduce; delete+create on a
  fixed name is the supported path.
- Remove the now-obsolete timestamp/`_BRANCH_TTL`-for-freshness rationale
  comment (TTL stays, but as an orphan backstop, not the freshness mechanism).
- `_branch_exists`, `_delete_branch`, `_ensure_sp_autoscaling_role(...,
  branch_name=...)` — unchanged (already parameterized).

### `scripts/deploy_local.py`

- **CLI**: add `--instance <id>`. Validate the slug. `--instance` requires the
  resolved env to have `branch_from`.
- **Config derivation**: a helper that, given the base config + `instance`,
  returns `app_name=<base>-<id>`, `workspace_path=<base>/<id>`, and target
  branch `dev-<id>`. When `--instance` is absent, behavior is exactly as today
  (env-named branch — preserves the staging path).
- **`create_local` / `update_local`**: accept `instance`; use the derived names;
  pass the fixed `dev-<id>` branch to `_recreate_ephemeral_branch`; SP role uses
  `dev-<id>`.
- **`delete_local`**: accept `instance`; delete the derived app and explicitly
  delete `branches/dev-<id>`.

### `.github/workflows/publish-dev.yml`

- The deploy summary prints the new `--env devloop --instance <id>` form
  alongside the existing example.

### Docs

- `docs/technical/dev-deploy.md` and the `deploy-tellr-dev` skill describe the
  per-instance `devloop` loop.

## Error handling

| Failure | Message |
|---------|---------|
| `--instance` set but env has no `branch_from` | `--instance requires a branch_from env; '<env>' is not a branching env` |
| Invalid instance slug | `--instance must match ^[a-z][a-z0-9-]*$ and be <=59 chars` |
| `branch_from` unset in referenced env | `branch_from "production" not found in deployment config` |
| Different `database_name` source vs target | `branching requires same database_name; devloop=<x>, production=<y>` |
| Source not deployed | `production not deployed — deploy production first` |
| Key missing from source app.yaml | `GOOGLE_OAUTH_ENCRYPTION_KEY missing from production app.yaml` |
| Lakebase not autoscaling | `Lakebase branching requires autoscaling; <db> is not an autoscaling project` |
| Source branch missing | `source branch "production" not found in project <db>` |
| `update` before `create` | `App '<app>' does not exist — run 'deploy_local.sh create --env devloop --instance <id>' first` |

All preflight failures raise `DeploymentError` before any mutating
`ws.postgres` call. A failed deploy never half-creates a branch + app.

### Orphan risk

If branch creation succeeds but app creation fails, the next deploy's
delete+create self-heals, and the branch TTL backstops abandoned instances. No
rollback machinery.

## Testing

### Unit tests (new / updated)

- Instance → name derivation: `app_name`, `workspace_path`, branch `dev-<id>`.
- Slug validation: rejects uppercase / leading digit / `>59` chars / illegal
  chars; accepts `agent-7f3a`.
- `--instance` without `branch_from` env → `DeploymentError`.
- `_recreate_ephemeral_branch` does **delete-then-create** with the fixed
  `branch_id` (mocked `ws`): asserts `_delete_branch` called, then
  `create_branch` with `branch_id == dev-<id>` and `source_branch == production`.
- `_create_branch_from` no longer appends a timestamp — `branch_id` is used
  verbatim. **Update** existing tests that assert timestamp-suffixed ids.
- `delete_local` deletes the derived app and `branches/dev-<id>` (idempotent on
  not-found).

### Regression

- `tests/unit/test_database_autoscaling.py`,
  `tests/unit/test_deploy_branch_helpers.py`,
  `tests/unit/test_deploy_local_config_branching.py`,
  `tests/unit/test_deploy_local_preflight.py` — re-run; update any assertions
  tied to timestamp branch ids or env-named branches.

### Integration (manual, against a real workspace)

1. **Concurrency:** `create --instance a` and `create --instance b` (different
   ids). Verify two apps (`db-tellr-dev-a`, `db-tellr-dev-b`) and two branches
   (`dev-a`, `dev-b`), both children of `branches/production`, mutually isolated.
2. **Fresh-each-deploy:** write a row in instance `a`, then `update --instance a`
   with a newer version; confirm the row is gone (branch re-forked) and the app
   compute is the same (URL unchanged, new `.devN` serving).
3. **Decrypt + data:** confirm a copy of prod sessions/decks is visible and a
   prod Google OAuth credential decrypts in the dev instance.
4. **Teardown:** `delete --instance a`; confirm app and `branches/dev-a` are
   gone; `branches/production` and instance `b` untouched.
5. **Precondition failure:** invalid `--instance FOO` fails fast with the slug
   message and makes no `ws.postgres` call.
6. **Migration limitation (pre-dependency):** a build that only adds a *new*
   table or writes data deploys cleanly; a build that `ALTER`s an inherited prod
   table fails at startup with `must be owner of table`. This is expected until
   the ownership dependency lands — verifying this failure mode is part of
   confirming the dependency is still needed.

## Out of scope

- **The shared-owner ownership workstream itself** — tracked as a dependency
  (see [Dependency: Lakebase table ownership](#dependency-lakebase-table-ownership-shared-owner-model));
  it gets its own spec. This spec ships the branch mechanism; migrations that
  alter inherited tables are unblocked by that separate work.
- CI-run deploys — the deploy stays a manual laptop step; `publish-dev.yml`
  still only publishes and prints the command.
- Auto-reaper / cron cleanup — manual delete + branch TTL only.
- Deriving the instance id from git branch / worktree / PR.
- Scrubbing or masking prod data in dev instances.
- Migrating other static-schema envs (`devtest`, `chatfix`, `test`) onto
  branching — `devloop` is additive; they are left as-is.
