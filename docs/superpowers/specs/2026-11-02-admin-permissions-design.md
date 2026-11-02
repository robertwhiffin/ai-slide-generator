# App admins from a Lakebase permissions table — design

**Date:** 2026-11-02
**Status:** agreed in conversation with the repo owner. Calls I made without the owner are listed under "Calls made without the owner".
**Background:** a live spike on `tellr-dev` (throwaway app `acl-spike`, now stopped). The source and probe JSON are in `~/tellr-loop/admin-acl-spike/`. Facts are summarised under "Spike facts" below.

## Why

Today a Tellr admin is anyone in the workspace `admins` group (`_admin_acl_probe`, `src/api/routes/_authz.py:346`). That has two problems.

- **It is the wrong group of people.** Workspace admins run the workspace, not Tellr. The people who own a Tellr install, i.e. those who hold CAN_MANAGE on the app, may not be workspace admins at all.
- **Logfood has no admin.** The owner runs the logfood install but is not a workspace admin there, so nobody can reach the admin page.

The owner also wants a start on a general permissions model. Today only decks have permissions. Deck specs will need them later. The new table should be able to hold those later without a redesign, but this work only adds the `admin` privilege.

## Goals

- **Who is an admin:** someone is a Tellr admin if they hold CAN_MANAGE on the Databricks App, **or** an admin added them on the new Admins tab, or both. Holding CAN_MANAGE grants admin automatically, but someone can be an admin without it.
- **Being a workspace admin no longer makes someone a Tellr admin.** In particular, the `admins` entry every app inherits from the workspace-wide `/apps` permissions does not count. A CAN_MANAGE holder who deliberately grants a group CAN_MANAGE directly on the app is choosing to make that group admins, and that is honoured even if the group is `admins`.
- **The admin list stays in step with CAN_MANAGE without a redeploy.** Anyone granted CAN_MANAGE in the Databricks UI becomes an admin within a few minutes. Anyone who loses CAN_MANAGE loses the admin it gave them, but keeps admin if they were also added on the Admins tab.
- **Logfood works:** after one `tellr.update` by a CAN_MANAGE holder, the people with CAN_MANAGE on the logfood app are Tellr admins. CI service principals created the logfood app and Lakebase project. The owner deployed it by running `databricks_tellr.deploy.update` by hand (profile `logfood-canonical`, 2026-10-29), so a new step in that function reaches logfood. If logfood deploys ever move to CI, that CI job has to run the same `update`.
- **An "Admins" tab on the admin page** shows every admin, says why each one is an admin, and lets an admin add or remove users and groups.
- **The table can grow:** it is a general `permissions` table (resource, identity, privilege), not an admins-only table.

## Non-goals

- Deck permissions (`deck_contributors`) and deck-spec permissions. They stay as they are and are not moved into the new table.
- Local development. The existing non-production bypass in `require_admin` stays exactly as it is.
- Anything special for devloop instances. A devloop fork copies prod's Lakebase branch, so its `permissions` rows come with it, and its own sync then mirrors the devloop app's CAN_MANAGE list.
- Seeding the table with the installer's identity at deploy time. The sync replaces that idea.
- Changing what any admin-gated route does. Only *who passes* the gate changes.

## Anti-goals (failures even if it "works")

- **A failed or partial read of the app's permissions removes admins.** A failed read must change nothing.
- **Workspace admins quietly stay admins,** for example because the sync copied the inherited `admins` group entry.
- **The UI and the server disagree.** The `is_admin` flag in `/api/user/current` must keep coming from the same check the routes use (`is_caller_admin` delegates to `require_admin` today, and that must stay true).
- **A new way to fail open.** Every lookup error still denies.
- **Removing someone on the Admins tab appears to work but they are back five minutes later.** CAN_MANAGE-derived admin cannot be removed in Tellr, and the page must make that clear.

## Spike facts (tellr-dev, 2026-11-02)

| The app's own SP holds, on its own app | `apps.get_permissions(app_name)` as the app SP |
|---|---|
| nothing (every app starts like this) | `PermissionDenied … apps.ruleSets/get`. This is the July "wall 2" from PR #228. |
| CAN_USE | still denied |
| CAN_MANAGE | **works**, but only after roughly 30–60 s. The call made straight after the grant still failed. |

- **What the permission list contains:** each entry has `user_name` (the email) for a user, `group_name` for a group, or `service_principal_name` for a service principal. Each also has `all_permissions[]`, where each item has `permission_level`, `inherited` and `inherited_from_object`.
  - The workspace `admins` group appears as CAN_MANAGE with `inherited: true`, `inherited_from_object: ['/apps']`.
  - The app's own SP appears once it is granted.
- **The app ID equals the SP's client ID.** `DATABRICKS_APP_NAME` and `DATABRICKS_CLIENT_ID` are injected into the app's environment.
- **The app SP can't see group members.** It can call SCIM `groups.list`, but `members` comes back empty (0 for `admins`, where a full user token sees 11), and `users.list` returns empty `groups`. So the SP **cannot expand a group into its members**.
- **The caller's own groups are already readable.** The existing code reads them with the caller's own token through `current_user.me().groups[].display` (`_caller_group_display_names`, `_authz.py`).

## The design

### 1. The `permissions` table

This is a new ORM model, so `create_all` builds it in the existing migration step: `run.py::init_database`, which runs once before the workers fork, never in the lifespan. `_run_migrations` already moves new objects onto `tellr_app_owners` (`src/core/database.py:2009`), so there is no new ownership work. The deploy package must **not** create this table.

Each row is one grant. These are the fields; exact column names and types are the builder's call.

- **Resource type:** `app` for now. Later values would include `deck_spec`.
- **Resource id:** empty for app-wide grants. Uniqueness must still hold when it is empty, because Postgres treats NULLs as distinct.
- **Identity type:** `USER` or `GROUP`.
- **Identity name:** the email for a user, the group display name for a group. Matching is case-insensitive.
- **Identity id:** the SCIM id when it is known, which is the case for picker adds. It is empty for synced rows, because the permission list carries names, not ids.
- **Privilege:** `admin`. It is the only value for now.
- **Source:** `can_manage_sync` or `manual`. A person can have one row of each, and that is how the union works. Losing CAN_MANAGE deletes only the `can_manage_sync` row.
- **Who added it and when.** For synced rows, "who" is the sync.

The table needs a uniqueness rule over (resource type, resource id, identity type, lower-cased identity name, privilege, source).

### 2. The admin check

`require_admin` keeps its shape: the production-only gate, a 60 s per-worker verdict cache that caches only definite answers, and a denial on any error. Only the verdict changes. The caller is an admin if a `permissions` row for (`app`, app-wide, `admin`) matches either:

- a `USER` row whose name equals the caller's email (`get_current_user()`), compared case-insensitively; or
- a `GROUP` row whose name is one of the caller's own group display names, from `current_user.me().groups` with the caller's token, as today.

Group membership has to be checked against the caller's groups at request time, because the SP cannot list group members. The middleware builds the permission context with `fetch_groups=False` (`src/api/main.py:440`), so the group ids that context holds do not help here. Use `me().groups` display names.

- **The old check goes completely:** remove `_ADMIN_GROUP` and the "`admins` group" decision. Rewrite the long comment block in `_authz.py`, keeping the history of the three earlier attempts and adding this design and the spike result.
- **Cache refresh:** when the Admins tab adds or removes a row, clear the cache for that worker. Other workers may lag by up to the 60 s TTL, which is accepted.
- **Callers do not change:** about 35 routes depend on `require_admin` (the whole `/api/admin` router, admin usage, feedback, graph shipping, agent definitions, the huashu export probes, deck prompts, slide styles, design systems, and one inline call in `profiles.py`). `is_caller_admin` and `/api/user/current` also stay as they are. Today's tests patch `_admin_acl_probe`, and the builder may keep that seam or move it.

### 3. The CAN_MANAGE sync

This is a background loop started in the FastAPI lifespan, like the existing sweepers (`src/api/main.py:179-194`). It is not part of `init_database`.

1. **Read the permission list:** call `apps.get_permissions(app_name=DATABRICKS_APP_NAME)` with the **app SP** client, because there is no user token in a background loop.
2. **Keep the right entries:** keep users and groups with at least one `all_permissions` item that is `CAN_MANAGE` and `inherited: false`. Drop inherited entries; that is what removes the workspace `admins` group. Drop service principals, including the app's own SP.
3. **Reconcile the synced rows:** compare the result with the `can_manage_sync` rows. Insert the missing ones and delete the ones no longer present. Never touch `manual` rows.
4. **Write nothing if the read fails or its result can't be trusted.** On any exception, change no rows, record the failure (see the status below), and try again on the next tick. A read that succeeds but leaves **zero** users or groups after step 2 also counts as untrusted: no rows change and the status goes amber with "the app's permissions list no direct CAN_MANAGE users or groups". A real app always has at least its creator or deployer, and wiping every synced admin on one odd read is worse than leaving a removed admin in place for one more cycle.
5. **Timing:** run at startup, retry about every 30 s until the first success (to ride out the propagation delay after a fresh grant), then every 5 minutes.
6. **Several workers:** every uvicorn worker (4 by default) may run the loop. The reconcile must stay correct when two workers run it at once; the uniqueness rule plus idempotent inserts and deletes are enough. Whether to use a lease so that only one worker syncs, as `spec_review_sweeper_loop` does, is the builder's call.
7. **Sync status in the database:** the time of the last successful sync and the last error, if any, are stored so the Admins tab can show them whichever worker serves the page. Where they live is the builder's call.
8. **Loud logs:** a failed read logs a warning every time. If no sync has ever succeeded, the log says plainly that only Tellr-added admins exist and how to fix it: grant the app's SP CAN_MANAGE on the app by running `tellr.update`. If the table is also empty, nobody can open the Admins tab to see the amber status.

### 4. The deploy side: grant the app SP CAN_MANAGE on its own app

There is one new deploy step, run by whoever runs the deploy. That person or SP already holds CAN_MANAGE, since deploying requires it.

- **The call:** `apps.update_permissions(app_name, [{service_principal_name: <app SP client id>, permission_level: CAN_MANAGE}])`. This is the **additive** PATCH. Never use `set_permissions`, which replaces the whole permission list.
- **Where it runs:** in `databricks_tellr.deploy` `create` (after the app exists, when the SP id is known) and `update` (before `deploy_and_wait`, so the grant has propagated by the time the new version's first sync runs). It also has to go into `scripts/deploy_local.py` `create_local` / `update_local`, which have their own create and update flows and only import helpers from `deploy.py`.
- **A failed grant does not abort the deploy.** Follow `_ensure_app_user_api_scopes`: print a warning with the exact manual fix (the CLI command, or "add the app's service principal with Can Manage in the app's Permissions tab"). The new version still ships, and Tellr-added admins still work.
- **The grant is safe to repeat:** if the SP already holds CAN_MANAGE, it changes nothing.

### 5. The Admins tab (layout "A — one list", chosen by the owner)

There is a new tab, **Admins**, last in `AdminPage.tsx`'s tab row. The mockup is in `~/tellr-loop/admin-permissions/.superpowers/brainstorm/*/content/admins-tab.html`.

- **Status line at the top:**
  - green: "Synced from app permissions N min ago";
  - amber when the last read failed or no sync has ever succeeded: "Tellr can't read this app's permissions. Run `tellr.update` to grant the app access", with the error shown in a quieter style.
- **Search and add:** the same user and group picker as deck sharing (`/api/settings/identities/search`, which already returns users and groups), plus an **Add admin** button. It creates a `manual` row. Any admin can add.
- **One list,** with one line per identity (user or group) and a badge for each source: **CAN_MANAGE on app** and/or **Added in Tellr**. A user line shows the email. A group line shows the group name with "group" underneath. A manual row shows "added by X · date".
- **Remove** appears only when the identity has a `manual` row, and deletes only that row. An identity whose only source is CAN_MANAGE shows a lock instead, and hovering on it says "Change this in the app's Permissions in Databricks".
- **New API routes** go on the existing `/api/admin` router, so they inherit `require_admin`: list (identities, sources and sync status), add a manual row, and delete a manual row. Deleting a `can_manage_sync` row is refused. Exact paths and payloads are the builder's call.

### 6. Docs and tests to update

- **Rewrite:** `docs/technical/permissions-model.md` "Workspace Admin" section (line 489), becoming app admin: the table, the union, the sync, groups, the cache, and the deploy grant.
- **Update:**
  - `docs/technical/databricks-app-deployment.md`: the new deploy step.
  - `docs/technical/dev-deploy.md`: if devloop behaviour is worth a line.
- **Tests and docs that check admin behaviour:**
  - `test_admin_route_authorization_inventory.py`, which lists the known `/api/admin` routes. The new routes must be added there.
  - the frontend admin-page e2e tests (`admin-page.spec.ts`, `admin-route-gate.spec.ts`)
  - the user-guide screenshots (`frontend/tests/user-guide/`)

## Constraints

- **The app SP needs CAN_MANAGE on its own app.** Without it the sync cannot read anything (spike). Every install's deploy path has to make that grant: package `create`/`update` and `deploy_local`.
- **The permission list holds names, not ids:** emails and group display names. Matching is by name, case-insensitive.
- **The app SP cannot list group members.**
- **No migration code in the lifespan, and no periodic loop in `init_database`** (the comments at `src/api/main.py:129` and `:185`).
- **Fail closed everywhere.** A sync failure never deletes rows.
- **Repo process:** every task in the plan needs a `Models:` tag, and the plan is executed with the `executing-plans-tellr` skill (see `CLAUDE.md`).

## Risks to record

- **The app SP becomes CAN_MANAGE on its own app.** Anyone holding the app SP's credentials can then redeploy, delete or re-permission the Databricks App object. Inside Tellr this adds nothing new, because those credentials can already write the `permissions` table in Lakebase, but it is new power over the app object. Note it for the security review (SDR-4437 follow-up).
- **CI-managed installs (logfood).** If the logfood CI re-applies the app's permissions from its own config, it may remove the SP's self-grant. The sync then fails safely: the status goes amber and the existing rows are kept. The fix is another `tellr.update`, or adding the grant to the CI config.
- **The upgrade drops workspace admins.** On the first release, workspace admins who hold only the inherited CAN_MANAGE stop being Tellr admins. This is intended, and it should go in the release notes.

## Calls made without the owner

- Inherited permission entries are ignored by the sync (owner agreed with the guess). Service principals are also ignored, including a CI SP that holds CAN_MANAGE directly: they never use the UI, and they already control the app through CAN_MANAGE.
- A group granted CAN_MANAGE **directly** on the app counts, even if it is the workspace `admins` group. Only the inherited entry is excluded.
- A successful read with zero qualifying users or groups is treated as untrusted and changes nothing.
- Sync timing: at startup, about every 30 s until the first success, then every 5 minutes.
- No "last admin" guard on the Admins tab. CAN_MANAGE holders are always admins, so the page cannot lock the app out. Admins may remove their own manual row.
- A failed self-grant at deploy time warns and doesn't abort, the same way scopes are handled today.
- Group admins are matched on group display name against the caller's own `me().groups`.
- The 60 s verdict cache stays. Changes on the Admins tab clear only the serving worker's cache.

## Left to the builder

- The exact table and column names and types, and how the empty-resource-id uniqueness is enforced.
- Whether one worker holds a lease for the sync or all workers reconcile idempotently.
- Where the sync status is stored.
- API paths and payloads for list, add and remove.
- Whether to keep the `_admin_acl_probe` seam name for tests.
- Whether to pull the deck-sharing picker out into a shared component or reuse it as it is.
- Whether `me().groups` includes nested (indirect) groups. If it doesn't, nested groups don't grant admin; document whichever is true.
