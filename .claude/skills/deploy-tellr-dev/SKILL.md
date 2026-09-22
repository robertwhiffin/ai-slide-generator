---
name: deploy-tellr-dev
description: Use when deploying a dev/test build of the Tellr app to a Databricks Apps dev workspace (e.g. the db-tellr-devtest env). Covers publishing a dev .devN to real PyPI and deploying it with deploy_local --from-pypi. Triggers on "deploy tellr dev", "dev deploy", "test build to dev workspace", "publish a dev version".
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

## The loop

1. Publish a dev build (auto-increments the next-patch `.devN`):

   ```bash
   gh workflow run publish-dev.yml            # or: -f version=0.4.0.dev1 to override
   gh run watch <run-id> --exit-status        # the run includes a 10s settle for PyPI
   ```

   Capture the resolved version from the run summary (e.g. `0.3.10.dev1`).

2. **Confirm the version exists from the workflow's upload log — never from a
   package index listing:**

   ```bash
   gh run view <run-id> --log | grep -E '200 OK|View at:'
   ```

   You want `200 OK` plus `View at: https://pypi.org/project/databricks-tellr-app/<version>/`.
   That is the authoritative signal, and it is available the moment the run finishes.

   **DO NOT gate the deploy on a package-index listing — go straight to step 3.**
   `pip index versions databricks-tellr-app --pre` looks like a readiness probe for the
   BUILD phase, because local pip is configured with
   `index-url = https://pypi-proxy.dev.databricks.com/simple` — the *same proxy host* the
   BUILD phase resolves against. It is not one. The proxy caches the `/simple/` **listing**
   separately from its ability to fetch an **exact pinned version**. Measured 2026-09-21:
   `0.4.3.dev27` published, the BUILD phase installed it first try — and the listing still
   stopped at `.dev26` **1h15m later**, more than an hour after that successful install. A
   stale listing is not evidence the build will fail, and waiting for it can wait forever.
   (`curl https://pypi.org/...` from the laptop returns `503` — egress is proxied, so real
   PyPI cannot be checked directly either.)

   | Tempting thought | Reality |
   |---|---|
   | "The index doesn't list it yet, so the build will fail" | The listing and the pinned fetch are different caches. Measured: listing stale 1h15m *after* a successful install. |
   | "Better to wait than burn a Lakebase fork on a doomed deploy" | The fork is cheap and re-forked every deploy anyway. An indefinite wait costs more. |
   | "My pip hits the same proxy, so it's the same answer" | Same host, different cache. Same host is exactly what makes this trap convincing. |

3. Deploy that exact version to the dev app:

   ```bash
   ./scripts/deploy_local.sh update --env devtest --profile tellr-dev --from-pypi <version>
   ```

   Use `create` instead of `update` if the app does not exist yet. `devtest` =
   app `db-tellr-devtest`, reusing the `db-tellr` lakebase with schema
   `devtest_app_data`.

4. Verify the deploy — `deploy_local` exiting 0 only means the app was *submitted*:

   ```bash
   # want app_status.state=RUNNING and active_deployment.status.state=SUCCEEDED
   databricks apps get <app-name> -p tellr-dev -o json
   ```

   Expect `/health` to return **502 for ~30s after** that, while startup migrations and
   data backfills run in the FastAPI lifespan. That is normal, not a failed deploy.

   To prove a **frontend-only** change is actually live, grep the served bundle for a
   distinctive minified string from the diff, and run the same grep against
   `db-tellr-prod`'s bundle as a control — a 0-vs-N result is what makes the check
   non-vacuous:

   ```bash
   curl -sH "Authorization: Bearer $TOK" "$APP_URL/" | grep -oE '/assets/[^"]+\.js'
   # then fetch that asset from BOTH the dev app and db-tellr-prod and compare hit counts
   ```

## Upgrade path & the encryption key (SDR-4437) — use the tool, not the UI button

The Google-OAuth Fernet master key lives either in the `encryption_keys` Lakebase
table (default) or in a Databricks secret (opt-in). `tellr.update` / `deploy_local`
(run as the human) migrate a pre-key-table app: read the legacy `GOOGLE_OAUTH_ENCRYPTION_KEY`
from the old `app.yaml`, seed the table, and write a **keyless** `app.yaml`.

**Secret-backed deployments:** pass `--encryption-secret-scope <scope>` to store
the key in a Databricks secret instead of Lakebase. The deploy tool writes the key
to the secret and injects it as `TELLR_ENCRYPTION_KEY` via a `valueFrom` entry in
`app.yaml`; the `encryption_keys` table stays empty. You can also pass
`--encryption-secret-key` to override the default key name (`tellr-encryption-key`).

```bash
./scripts/deploy_local.sh update --env devtest --profile tellr-dev \
    --from-pypi <version> --encryption-secret-scope tellr
```

A devloop fork inherits secret mode automatically from the source app — no flag needed.

**Always upgrade via `deploy_local` / `tellr.update`, never the Databricks Apps
UI "Deploy" button.** The UI button bypasses the tool and reuses the old
key-bearing `app.yaml`, skipping the migration. The booting app has a safety net
— it seeds the table from the injected `GOOGLE_OAUTH_ENCRYPTION_KEY` env var if
the table is still empty — but the tool path is the only supported one. There is
no boot-time `app.yaml` scrub (the app's SP can't write its own source). See
`docs/technical/dev-deploy.md` for the full mechanism.

## Per-instance dev loop (`devloop`)

For parallel/agentic loops, use `--env devloop --instance <id>` instead of
`devtest`. Each instance gets its own app (`db-tellr-dev-<id>`) and a fresh
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
databricks apps logs db-tellr-devtest -p tellr-dev-oauth
```

If the token is expired: `databricks auth login --host <workspace-host> -p tellr-dev-oauth`.
A BUILD-phase `Could not find a version that satisfies the requirement ...` that has
**actually occurred** can mean proxy mirror lag — wait and re-run the deploy step. Only
react to that failure once you have seen it. Never pre-empt it by polling a package-index
listing, which can stay stale indefinitely (see step 2 of the loop).

See `docs/technical/dev-deploy.md` for the full background.
