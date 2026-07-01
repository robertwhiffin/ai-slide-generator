# Lakebase table ownership — shared-owner model for prod-branch dev forks

**One-line summary:** All `app_data_prod` objects are owned by a shared Postgres
role (`tellr_app_owners`); app service principals join that role to migrate
copy-on-write branches of production, and a single granter service principal —
exercised through a serverless Databricks job anyone can run — confers that
membership at deploy time.

## Why this model exists

Each Databricks App runs as its **own** managed service principal (SP). In
Lakebase Postgres, an object is owned by **whichever role created it**, and only
its owner (or a true superuser, which no app identity is) may `ALTER`/`DROP` it.

The `devloop` dev pipeline (`docs/technical/dev-deploy.md`) forks a copy-on-write
branch of production for each dev instance. A fork inherits production's object
ownership. Because each dev app has a *different* SP from the prod app, a dev SP
that tries to run an `ALTER`-bearing migration against an inherited production
table is blocked with `must be owner of table`.

The shared-owner model removes that block: ownership of every `app_data_prod`
object lives on a role that all app SPs can be members of, and a **member** of an
owning role can `ALTER`/`DROP` that role's tables **as itself, through `INHERIT`**
— no `SET ROLE`, no superuser. Migrations therefore run as code on any fork.

## Core concepts

### The owning role

`tellr_app_owners` is a permanent `NOLOGIN` Postgres role. It owns the
`app_data_prod` schema and every table and sequence in it. It is the single
owner of record for production's data model.

### Two separable privileges

Role membership confers two capabilities that this model grants to different
identities on purpose:

| Capability | Granted as | Held by | Effect |
|---|---|---|---|
| **Owner rights** — `ALTER`/`DROP` the role's tables | membership `WITH INHERIT TRUE` | app SPs (prod + each dev) | The SP migrates inherited tables on its fork as code. |
| **Admin-to-grant** — add/remove role members | membership `WITH ADMIN OPTION, INHERIT FALSE` | the granter SP only | Confers membership on new SPs while holding **no** power to touch tables. |

Humans hold **neither** capability. The data model is changed only by application
migration code running as a service principal; there is no path for a person to
hand-edit Lakebase tables through this role.

### Identities

| Identity | Membership in `tellr_app_owners` | Role |
|---|---|---|
| Prod app SP | `INHERIT TRUE` | Runs production migrations; owns nothing directly, alters via inheritance. |
| Dev app SP (per `devloop` instance) | `INHERIT TRUE` | Runs migrations on its fork. Granted at deploy time. |
| Granter SP | `ADMIN OPTION, INHERIT FALSE` | The only identity that can add members. Its admin membership is established on production, so every fork inherits it. |

## How membership is wired into automation

### The grant job

A **serverless** Databricks job runs **as the granter SP**. Its run-ACL is open,
so any human or agent may trigger it without holding any Postgres privilege — the
privilege lives in the SP the job runs as, not in the caller.

| Aspect | Value |
|---|---|
| Runs as | the granter SP |
| Compute | serverless |
| Parameters | new app SP id, branch host/endpoint |
| Action | `GRANT tellr_app_owners TO "<new_sp>" WITH INHERIT TRUE` against the branch (idempotent) |
| Run-ACL | open (`CAN_RUN` for deployers) |

The grant runs in Postgres against the branch endpoint rather than via Databricks
group membership: the granter SP's admin membership is inherited by every fork,
so it can grant any new SP on any branch immediately, with no dependence on
group-membership federation reflecting onto an already-forked branch.

### Deploy flow

`scripts/deploy_local.py` (`create`) wires the job into the `devloop` deploy:
after creating the branch, creating the app, and registering the new app SP, it
triggers the grant job (run-now) with the new SP id and branch host, waits for
completion, then deploys the app. `update` does not re-grant — the SP is
unchanged and the freshly re-forked branch already carries the role and its
members.

### Keeping new objects shared

`src/core/database.py` (`_run_migrations`) ends with:

```sql
REASSIGN OWNED BY CURRENT_USER TO tellr_app_owners;
```

guarded to run only when `tellr_app_owners` exists. Any object a migration just
created — owned at first by the SP that created it — is re-homed onto the shared
role. This keeps production's data model wholly owned by `tellr_app_owners` so
the next fork inherits a uniformly shared schema. The guard makes the step a
no-op in static-schema environments that have no such role.

### Establishing ownership

`scripts/lakebase_transfer_ownership.py` is the run-once, idempotent maintenance
script that puts the model in place on production. It authenticates two ways in a
single run, no-ops if `app_data_prod` is already owned by `tellr_app_owners`, and
prints a dry-run summary requiring confirmation before mutating:

- **As the operator** (`CREATEROLE`): create `tellr_app_owners`; grant the
  granter SP `WITH ADMIN OPTION, INHERIT FALSE`; grant the prod SP
  `WITH INHERIT TRUE`.
- **As the prod SP** (a UI-issued OAuth token — only the current owner can give
  ownership away): `REASSIGN OWNED BY CURRENT_USER TO tellr_app_owners` and
  `ALTER SCHEMA app_data_prod OWNER TO tellr_app_owners`.

## Component responsibilities

| File / asset | Responsibility |
|---|---|
| `tellr_app_owners` (Postgres role) | Single owner of `app_data_prod` and its objects. |
| Granter SP + serverless grant job | Confer `INHERIT` membership on new app SPs, on any branch. |
| `scripts/deploy_local.py` (`create`) | Trigger the grant job for each new `devloop` instance's SP before deploying. |
| `src/core/database.py` (`_run_migrations`) | Re-home newly created objects onto `tellr_app_owners`. |
| `scripts/lakebase_transfer_ownership.py` | One-off: create the role and transfer existing ownership as the prod SP. |

## Operational notes

- **A failed grant blocks the deploy.** If the grant job run fails, `create`
  stops before deploying the app, so no instance is left serving without owner
  access to its fork.
- **Idempotency.** The grant (`GRANT ... TO`), the migration `REASSIGN`, and the
  transfer script are all idempotent; re-running any of them is safe.
- **Human access.** People interact with the data model only by shipping
  migration code. Triggering the grant job requires `CAN_RUN` on the job and
  nothing in Postgres.
- **Scope.** The model applies to production and its forks. Static-schema dev
  environments (`devtest`, `chatfix`, `test`, `development`) have no fork and no
  `tellr_app_owners` role; the migration guard leaves them untouched.

## Cross-references

- `docs/technical/dev-deploy.md` — the `devloop` per-instance branch dev loop this
  unblocks.
- `docs/technical/lakebase-integration.md` — Lakebase connection, credentials, and
  schema setup.
- `docs/technical/database-configuration.md` — migration framework and schema
  management.
