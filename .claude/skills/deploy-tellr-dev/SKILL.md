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

2. Deploy that exact version to the dev app:

   ```bash
   ./scripts/deploy_local.sh update --env devtest --profile tellr-dev --from-pypi <version>
   ```

   Use `create` instead of `update` if the app does not exist yet. `devtest` =
   app `db-tellr-devtest`, reusing the `db-tellr` lakebase with schema
   `devtest_app_data`.

3. Open the app URL and verify it loads.

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

**Migration limitation:** a build that `ALTER`s an *inherited* prod table fails
at startup with `must be owner of table` (creating new tables is fine). See
`docs/technical/dev-deploy.md` for details.

## Reading deploy logs

App logs require OAuth (not PAT):

```bash
databricks apps logs db-tellr-devtest -p tellr-dev-oauth
```

If the token is expired: `databricks auth login --host <workspace-host> -p tellr-dev-oauth`.
A failed BUILD-phase `Could not find a version ...` right after publishing usually
means proxy mirror lag — wait and re-run the deploy step.

See `docs/technical/dev-deploy.md` for the full background.
