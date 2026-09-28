---
name: deploy-tellr-dev
description: Use when deploying a dev/test build of the Tellr app to a Databricks Apps dev workspace. Always deploys to a per-instance devloop app (never devtest). Covers pushing the branch, publishing a dev .devN to real PyPI as the personal gh account, and deploying it with deploy_local --env devloop --from-pypi. Triggers on "deploy tellr dev", "dev deploy", "test build to dev workspace", "publish a dev version".
---

# Deploying a Tellr dev build

## Why this exists (read first)

Databricks Apps install `requirements.txt` in a platform-managed **BUILD phase**
using the **internal PyPI proxy** (`pypi-proxy.dev.databricks.com`), which mirrors
**real PyPI only**. That phase runs *before* the `app.yaml` `command:` block, so any
`--index-url` in the command never takes effect.

**Therefore: dev wheels MUST be published to real PyPI** (as `.devN` pre-releases).
Test-PyPI does not work — the proxy can't see it, and the build fails with
`Could not find a version that satisfies the requirement ...`. Do not re-attempt a
test-PyPI or custom-index approach.

Prod is unaffected: `pip` ignores pre-releases by default, so a bare
`pip install databricks-tellr-app` always picks the highest final.

## Always use `devloop`, never `devtest`

**Every dev deploy goes to a `devloop` instance** (`--env devloop --instance <id>`).
Do not use `--env devtest`, even for a one-off. `devtest` reuses the
`devtest_app_data` schema. If `db-tellr-devtest` is deleted and recreated, its
new service principal does not own the existing tables, so the first startup
migration crashes with `must be owner of table user_sessions`. This happened on
2026-09-28. `devloop` forks prod Lakebase per instance and grants the app's SP
into `tellr_app_owners`, so migrations always run as the owner.

## The loop

0. Use the **personal** GitHub account (`robertwhiffin`), never the EMU account:

   ```bash
   gh auth switch --hostname github.com --user robertwhiffin
   gh api user --jq .login                     # must print robertwhiffin
   ```

1. Push the branch you are deploying. The workflow builds from GitHub, not from
   your working tree:

   ```bash
   git push origin <branch>
   ```

2. Publish a dev build of that branch (auto-increments the next-patch `.devN`):

   ```bash
   gh workflow run publish-dev.yml --ref <branch>   # or add: -f version=0.4.0.dev1
   gh run list --workflow publish-dev.yml --limit 1 # get the run id
   gh run watch <run-id> --exit-status              # includes a 10s settle for PyPI
   ```

   Without `--ref`, the workflow builds the default branch, not your code.
   Capture the resolved version from the run log (`version=0.4.3.dev28`).

3. Deploy that exact version to a devloop instance:

   ```bash
   ./scripts/deploy_local.sh create --env devloop --instance <id> \
       --profile tellr-dev --from-pypi <version>   # first deploy of this instance
   ./scripts/deploy_local.sh update --env devloop --instance <id> \
       --profile tellr-dev --from-pypi <version>   # later deploys
   ```

   To check whether an instance exists, run
   `databricks apps get db-tellr-dev-<id> --profile tellr-dev`.

4. Verify the app is actually running. `Deployment complete!` only means the
   deploy was submitted; the app can still crash on startup:

   ```bash
   databricks apps get db-tellr-dev-<id> --profile tellr-dev -o json   # app_status.state must be RUNNING
   ```

   If it shows `CRASHED`, read the logs (see below).

## Upgrade path & the encryption key (SDR-4437) — use the tool, not the UI button

The Google-OAuth Fernet master key lives in the `encryption_keys` Lakebase
table, not in `app.yaml`. `tellr.update` / `deploy_local` (run as the human)
migrate a pre-key-table app: read the legacy `GOOGLE_OAUTH_ENCRYPTION_KEY` from
the old `app.yaml`, seed the table, and write a **keyless** `app.yaml`.

**Always upgrade via `deploy_local` / `tellr.update`, never the Databricks Apps
UI "Deploy" button.** The UI button bypasses the tool and reuses the old
key-bearing `app.yaml`, skipping the migration. The booting app has a safety net
— it seeds the table from the injected `GOOGLE_OAUTH_ENCRYPTION_KEY` env var if
the table is still empty — but the tool path is the only supported one. There is
no boot-time `app.yaml` scrub (the app's SP can't write its own source). See
`docs/technical/dev-deploy.md` for the full mechanism.

## How `devloop` instances work

Each instance gets its own app (`db-tellr-dev-<id>`) and a fresh
copy-on-write branch of prod Lakebase (`branches/dev-<id>`), so concurrent
instances stay isolated:

```bash
./scripts/deploy_local.sh create --env devloop --instance agent-7f3a \
    --profile tellr-dev --from-pypi <version>    # first deploy
./scripts/deploy_local.sh update --env devloop --instance agent-7f3a \
    --profile tellr-dev --from-pypi <version>    # iterate (app reused, branch refreshed)
./scripts/deploy_local.sh delete --env devloop --instance agent-7f3a \
    --profile tellr-dev                          # teardown (app + branch)
```

`--instance` must match `^[a-z][a-z0-9-]*$` and be ≤59 chars. The branch is
re-forked from prod on every deploy, so anything written to an instance is wiped
on its next deploy.

**Migrations run as code on the fork.** A build can `ALTER`/`DROP` inherited prod
tables *and* create new ones — `app_data_prod` is owned by the shared
`tellr_app_owners` role, and `devloop create` grants each instance's SP into that
role (via a serverless granter job) so its migrations run as owner through
`INHERIT`. New objects a migration creates are reassigned back to the shared role
so the next fork inherits them too. See
`docs/technical/lakebase-table-ownership.md` for the ownership model.

## Reading deploy logs

App logs require OAuth (not PAT):

```bash
databricks apps logs db-tellr-dev-<id> -p tellr-dev-oauth
```

If the token is expired: `databricks auth login --host <workspace-host> -p tellr-dev-oauth`.
A failed BUILD-phase `Could not find a version ...` right after publishing usually
means proxy mirror lag. Wait a few minutes and re-run the deploy step. If it keeps
failing, see the next section.

## When the PyPI index is stale (`Could not find a version` that persists)

On 2026-09-28, dev29 and dev30 uploaded successfully but stayed invisible for
hours. PyPI answered `200 OK` on upload, then `400 File already exists` on
re-upload, but its cached project-level pages (the web page, `/pypi/<pkg>/json`
and `/simple/<pkg>/`) kept showing an older list. The Databricks PyPI proxies
inherited the stale list. The build was fine; the app's code change was not the
cause.

**Diagnose, don't guess.** pypi.org is blocked from Databricks laptops ("Web Page
Blocked"), so query the proxy. Its per-version JSON is fresh even when the index
is stale:

```bash
P=https://pypi-proxy.dev.databricks.com
curl -s $P/simple/databricks-tellr-app/ | grep -oE 'dev[0-9]+-py3' | sort -u | tail -3   # what pip sees
curl -s $P/pypi/databricks-tellr-app/<version>/json | python -m json.tool | head      # does the file exist?
```

If the per-version JSON has the file but `/simple/` doesn't list it, the index
is stale, not the build. The app's build proxy can differ from the one you can
reach, so treat its `from versions: ...` list in the build log as the truth for
what the app can see.

**Publishing while the index is stale:** auto-increment reads the stale project
JSON, so it re-picks a version that already exists, and the publish fails with
`400 File already exists`. Pass the next version explicitly:

```bash
gh workflow run publish-dev.yml --ref <branch> -f version=0.4.3.devN
```

**Deploying while the index is stale: pin by direct URL.** The Apps BUILD phase
can fetch straight from `files.pythonhosted.org` (verified 2026-09-28). After a
normal `deploy_local create|update` has uploaded the app files, overwrite the
app's `requirements.txt` with a hash-pinned direct URL and redeploy:

```bash
V=0.4.3.devN; ID=<instance>
SRC=/Workspace/Users/<you>/.apps/devloop/tellr/$ID
curl -s https://pypi-proxy.dev.databricks.com/pypi/databricks-tellr-app/$V/json | python -c "
import json,sys; u=[x for x in json.load(sys.stdin)['urls'] if x['filename'].endswith('.whl')][0]
print('databricks-tellr-app @ %s#sha256=%s' % (u['url'], u['digests']['sha256']))" > /tmp/req.txt
databricks workspace import $SRC/requirements.txt --file /tmp/req.txt --format AUTO --overwrite --profile tellr-dev
databricks apps deploy db-tellr-dev-$ID --source-code-path $SRC --profile tellr-dev
```

Confirm the right wheel installed: the app log's pip lines name the
`...-$V-py3-none-any.whl#sha256=...` URL. This is a hand edit. The next
`deploy_local --from-pypi` rewrites the normal `==<version>` pin, which fails
again until the index catches up.

Do not deploy a different version to an instance someone else is using. Create a
new devloop instance instead.

See `docs/technical/dev-deploy.md` for the full background.
