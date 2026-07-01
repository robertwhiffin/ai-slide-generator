# Lakebase shared-owner model (unblocks devloop fork migrations)

**Status:** Approved design (2026-06-30)
**Author:** robert.whiffin@databricks.com

> **What this unblocks.** The `devloop` per-instance branching pipeline
> (`docs/superpowers/specs/2026-06-29-devloop-instance-branching-design.md`, PR
> #206) already works for every dev build *except* one that introduces a
> **genuinely new schema migration** — a real `ALTER`/`ADD`/`DROP` against a table
> that already exists in `app_data_prod`. Those fail on a fork with
> `must be owner of table`, because every `app_data_prod` object is owned by the
> prod app's service principal and a dev app's *different* SP cannot alter
> inherited tables. This spec moves ownership of `app_data_prod` to a shared
> Postgres role that every app SP can join, so any SP can migrate inherited tables
> on its fork. It is the "shared-owner workstream" called out as a dependency in
> the devloop spec.

## Problem

Each Databricks App gets its **own** managed service principal (SP). Lakebase
objects are owned by **whichever SP created them**. On `projects/db-tellr`, the
entire `app_data_prod` schema and all ~20 tables are owned by the **prod app's
SP** (`161834b3-c54d-4b24-82c4-8f0166c191f4`). A forked branch inherits that
ownership. A dev app's SP is a *different* identity, and in Postgres only the
**owner** (or a true superuser, which we do not have) may `ALTER`/`DROP` a table.

The app's migrations (`src/core/database.py`, `_run_migrations`) are
`ALTER`-heavy. A dev build whose schema has moved since the fork point therefore
fails on first startup with `must be owner of table`. New-table `CREATE` and DML
already succeed (existing `GRANT CREATE/USAGE` + DML grants cover them); altering
*inherited* tables does not.

### What is already proven (live probes against `db-tellr`, 2026-06-29)

- **The deployer cannot fix it.** Run as the human deployer (`robert.whiffin`),
  `ALTER ... OWNER`, `ALTER SCHEMA OWNER`, and `REASSIGN OWNED BY <prod_sp>` all
  fail. Only the **current owner** (the prod SP) or a true superuser can move
  ownership. `databricks_superuser` has `rolsuper = false` and is a red herring;
  only `databricks_control_plane` is a true superuser (unusable).
  `generate_database_credential` cannot impersonate another SP.
- **A *member* of the owning role can `ALTER` via `INHERIT`.** A login identity
  that is a member of a normal shared owning role can `ALTER`/`DROP` that role's
  tables **as itself, without `SET ROLE`**, including on a fork.
  `REASSIGN OWNED BY <self> TO <shared_role>` also works for moving one's own
  objects into a role one is a member of.
- **The historic transfer must run *as the current owner* (the prod SP).** This
  was previously done by manually pulling connection details from the Lakebase UI
  and connecting **as the prod SP** with a UI-issued OAuth token. SDK-minted
  tokens for connect-as failed earlier with "Malformed OAuth token"; the
  **UI-issued** token works.

(Companion notes: `memory/lakebase_branch_permissions.md`,
`memory/devloop_instance_branching.md`; Databricks runbook ES-1783639, Confluence
"Change table ownership to a group", page `6095568937`.)

## Solution

Move ownership of all `app_data_prod` objects to a permanent shared Postgres role
**`tellr_app_owners`** (`NOLOGIN`). Every app SP that needs to migrate a fork is
granted **`INHERIT`** membership in that role and can then `ALTER` inherited
tables as itself. No `SET ROLE`, no superuser, no connecting *as* a group is ever
required — the design is built only from mechanisms proven on `db-tellr`.

The privilege to *grant* new SPs into the role is centralised in **one dedicated
"granter" service principal**, exercised through **one Databricks job** that
anyone may run but that executes *as* the granter SP. No human ever holds
ownership rights or even Postgres admin rights — humans only need permission to
trigger the job.

### Two privileges, deliberately separated

Postgres role membership confers two independently-grantable capabilities, and
keeping them apart is the core of this design:

| Capability | Postgres grant | Who gets it | Why |
|---|---|---|---|
| **Owner rights** — `ALTER`/`DROP` the role's tables | membership `WITH INHERIT TRUE` | **app SPs only** | They run migrations *as code*. Humans never get this — it would re-open manual hand-editing of Lakebase tables, an anti-pattern. |
| **Admin-to-grant** — add/remove members | membership `WITH ADMIN OPTION, INHERIT FALSE` | **the granter SP only** | Lets it hand out membership while having zero power to touch tables. |

There is **no Databricks group** in this design. Earlier iterations introduced a
`tellr-developers` group to give humans owner rights and then admin rights; both
needs evaporated once humans were removed from the privilege chain entirely.

## Decisions

| # | Decision | Chosen | Why |
|---|----------|--------|-----|
| 1 | Owning entity | Permanent `NOLOGIN` PG role `tellr_app_owners` | Built only from proven mechanisms; SQL-grantable; avoids the unsolved connect-as-group SDK path. |
| 2 | Who may edit tables | App SPs only (`INHERIT` members) | Migrations run as code; humans editing tables by hand is an anti-pattern we explicitly exclude. |
| 3 | Who grants new SPs | A single dedicated **granter SP** (`ADMIN OPTION, INHERIT FALSE`) | Centralises the privilege in one stable, auditable service identity; no human holds it. |
| 4 | How the grant is invoked | A **Databricks job** that runs *as* the granter SP, parameterised by the new SP id + branch host; open run-ACL | Anyone can trigger it; the privilege lives in the SP the job runs as, not in the caller. Every grant is a logged job run. |
| 5 | What the job executes | `GRANT tellr_app_owners TO "<new_sp>" WITH INHERIT TRUE` on the **branch** endpoint (Postgres path) | The granter SP's admin membership is established on prod once and inherited by every fork, so it can grant any new SP on any fork immediately. No dependency on Databricks→Lakebase group-membership federation reflecting a post-fork change. |
| 6 | Historic ownership transfer | One-off, two-identity repo script connecting **as the prod SP** with a pasted UI OAuth token | Only the current owner can give ownership away; the deployer provably cannot, and the prod SP token is obtained manually from the UI. A run-once, prod-touching operation belongs in an explicit, guarded script, not the deploy hot path. |
| 7 | Keeping new objects shared | `REASSIGN OWNED BY CURRENT_USER TO tellr_app_owners` at the end of `_run_migrations`, guarded on role existence | Uses the proven membership/INHERIT mechanism; no-op when nothing new was created; self-heals prod and dev forks alike. Avoids `SET ROLE`, whose SET membership option we have not validated on Lakebase. |
| 8 | Databricks group | None | Only ever existed to give humans privileges; humans now need none. |

## Components

### 1. The shared role and the granter SP (standing state)

- `tellr_app_owners` — `NOLOGIN` Postgres role, owns the `app_data_prod` schema
  and every object in it.
- **Granter SP** — a dedicated Databricks service principal, member of
  `tellr_app_owners` `WITH ADMIN OPTION, INHERIT FALSE`. Its membership is granted
  on **prod**, so every branch forked from prod inherits the granter SP's
  admin-to-grant capability.
- App SPs (prod + each dev) — members `WITH INHERIT TRUE`; the prod SP is granted
  during the one-off transfer, each dev SP by the grant job at deploy time.

### 2. One-off transfer script — `scripts/lakebase_transfer_ownership.py`

A run-once, idempotent, guarded maintenance script. **No-op** if `app_data_prod`
is already owned by `tellr_app_owners`. Operates on the **production** branch
only. Authenticates **two ways** in a single run:

**As the operator** (ambient SDK/profile creds; the operator has `CREATEROLE`):
1. `CREATE ROLE tellr_app_owners NOLOGIN` if absent.
2. `GRANT tellr_app_owners TO "<granter-sp-id>" WITH ADMIN OPTION, INHERIT FALSE`.
3. `GRANT tellr_app_owners TO "<owner-sp-id>" WITH INHERIT TRUE, SET TRUE` (so the
   prod SP can reassign to the role and run `ALTER SCHEMA ... OWNER TO` it — which
   requires the `SET` option — and, once it no longer *owns* the tables, can still
   `ALTER` them via `INHERIT` when running prod migrations). `SET TRUE` is made
   explicit rather than relying on PG16's default; validated live 2026-07-01.

**As the prod SP** (pasted UI-issued OAuth token):
4. `REASSIGN OWNED BY CURRENT_USER TO tellr_app_owners` (moves all tables/sequences
   the prod SP owns).
5. `ALTER SCHEMA app_data_prod OWNER TO tellr_app_owners`.

**Inputs:**

| Flag | Default | Meaning |
|---|---|---|
| `--owner-sp-id` | — (required) | Application id of the current owner (the prod app SP). |
| `--granter-sp-id` | — (required) | Application id of the dedicated granter SP. |
| `--sp-token` | — (required) | UI-issued OAuth token for the prod SP, used for the reassign phase. |
| `--owning-role` | `tellr_app_owners` | Name of the shared owning role. |
| `--database` | `db-tellr` | Lakebase project / database (prod). |

**Safety:** before mutating, the script prints a **dry-run summary** of exactly
what it will reassign (object count by type) and requires explicit confirmation.
`REASSIGN` on prod is hard to reverse cleanly, so the script must never run
silently.

### 3. The grant job (per-deploy membership)

A Databricks job, defined in the repo, that:
- **Runs as the granter SP.**
- Takes parameters: the **new app SP id** and the **branch host/endpoint**.
- Connects to that branch endpoint and runs
  `GRANT tellr_app_owners TO "<new_sp>" WITH INHERIT TRUE`. Idempotent (no-op if
  already a member).
- Has an **open run-ACL** (`CAN_RUN` for the relevant deployer population) so any
  human or agent can trigger it without holding any Postgres privilege.
- Runs on **serverless** compute (no job-cluster spin-up) to keep per-deploy
  latency low.

### 4. Deploy-flow change — `scripts/deploy_local.py` (`create`)

After the existing branch-create → app-create → `_ensure_sp_autoscaling_role`
steps, the `devloop` `create` flow:
1. Resolves the new app SP id and the branch host.
2. Triggers the grant job (run-now) with those parameters and **waits** for
   completion.
3. Proceeds to deploy the app.

`update` does not re-grant (the SP is unchanged); the branch is re-forked from
prod, which already carries the role and its members.

### 5. Stay-shared migration step — `src/core/database.py` (`_run_migrations`)

Append, at the end of the migration sequence:

```sql
REASSIGN OWNED BY CURRENT_USER TO tellr_app_owners;
```

Guarded to run only when `tellr_app_owners` exists, so static-schema envs
(`devtest`, `chatfix`, `test`, `development`) that have no such role are
unaffected. This keeps any newly-created object shared-owned on both prod (next
prod migration) and dev forks.

## Setup / rollout order (run once)

1. Create the **granter SP** in Databricks.
2. Define and deploy the **grant job** (runs as the granter SP, open run-ACL).
3. Run `scripts/lakebase_transfer_ownership.py` against prod (creates the role,
   grants the granter SP admin option, grants the prod SP, reassigns ownership as
   the prod SP).
4. Ship the `_run_migrations` "stay-shared" change.
5. Wire the grant-job trigger into `deploy_local.py create`.

After step 3, prod's objects are shared-owned; after step 4, they stay that way;
after step 5, every new `devloop` instance's SP is granted automatically and can
migrate its fork.

## Validation checklist (prove on a throwaway autoscaling project first)

Each is a fork-specific behaviour that must be confirmed before relying on it in
prod:

1. The granter SP's `ADMIN OPTION` membership, established on the source branch,
   is **effective on a fork** — i.e. the granter SP can `GRANT tellr_app_owners`
   to a new SP on a freshly-forked branch.
2. The granter SP can **connect to an arbitrary branch endpoint** of the instance
   (network + credential issuance for itself against any branch host).
3. A freshly-granted app SP, authenticating **as itself** (not `SET ROLE`), can
   then `ALTER` an inherited table on its fork.
4. `REASSIGN OWNED BY CURRENT_USER TO tellr_app_owners` at end of migrations is a
   clean no-op when no new objects exist, and correctly re-homes a newly created
   object.
5. The pasted UI OAuth token connect-as-prod-SP path still works for the one-off
   transfer.

## Testing

### Unit

- Transfer script: SQL sequencing per identity (mocked connections); idempotency
  guard returns no-op when schema already owned by `tellr_app_owners`; dry-run
  summary printed and confirmation required before any mutation.
- `_run_migrations`: the `REASSIGN` statement is emitted only when the role
  exists; absent-role envs are untouched.
- `deploy_local.py create`: triggers the grant job with the new SP id + branch
  host and waits; `update` does not.

### Integration (throwaway project, then prod)

- Walk the full validation checklist above.
- End-to-end: a `devloop` instance running a build that introduces a
  **genuinely new `ALTER` migration** deploys cleanly and the migration applies
  on the fork (the exact case that fails today).

## Error handling

| Failure | Behaviour |
|---|---|
| Schema already owned by `tellr_app_owners` | Transfer script no-ops with a clear message. |
| Prod SP token invalid / expired | Transfer script fails before the reassign phase with an actionable message; setup phase changes (role/grants) are idempotent and safe to re-run. |
| Grant job fails during `create` | `create` surfaces the job run failure and stops before deploying the app (no half-granted instance left serving). |
| `tellr_app_owners` missing during migration | `_run_migrations` skips the `REASSIGN` (guard), so non-prod envs are unaffected. |

## Out of scope

- **Route 2 (group-as-owner)** and any Databricks-group machinery — dropped.
- Automating creation of the granter SP or the job via IaC beyond a repo-checked
  job definition.
- Granting humans any Postgres membership — explicitly excluded (anti-pattern).
- Auto-reaping branches/instances (covered by the devloop spec's TTL backstop).
- Migrating static-schema envs (`devtest`, `chatfix`, `test`) onto the shared
  owner — they have no fork and need none.
- A troubleshooting skill for permission errors — unnecessary, since `create`
  runs the grant job automatically.
