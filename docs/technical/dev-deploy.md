# Dev deploys (test builds to a Databricks Apps dev workspace)

## The problem this solves

`deploy_local` originally uploaded the locally-built wheel into the app's
`source_code_path`. Databricks Apps cap that source bundle at ~10MB, and the
`databricks-tellr-app` wheel is ~31MB (it bundles the huashu PPTX sidecar:
`node_modules.tar.gz` ~12MB + `sys-libs-bullseye.tar.gz` ~19MB). So local-wheel
dev deploys fail the cap.

Prod avoids this: its `requirements.txt` is the bare `databricks-tellr-app`, and
the wheel is pulled from a package index at install time — nothing large enters
the source bundle.

## How Databricks Apps install dependencies (the key fact)

Apps install `requirements.txt` in a platform-managed **BUILD phase** using the
**internal PyPI proxy** (`pypi-proxy.dev.databricks.com`), which mirrors
**real PyPI only**. This happens *before* the `app.yaml` `command:` runs, so a
custom `--index-url` in the command is never used. This is why an earlier
test-PyPI attempt failed: the proxy can't see test-PyPI, so the build errored with
`Could not find a version that satisfies the requirement databricks-tellr-app==<devN>`.

**Consequence: dev builds publish to real PyPI**, as PEP 440 `.devN` pre-releases.
The proxy mirrors them, and the BUILD phase resolves the pinned version exactly
like prod.

## Is this safe for prod?

Yes. `pip` excludes pre-releases by default, so a bare
`pip install databricks-tellr-app` (prod's path, no `--pre`) always resolves to the
highest **final** release. A `.devN` is only selectable with an explicit `--pre`
*and* a base higher than any final — never the default path. Cost: `.devN` releases
are visible on the public project page.

## Versioning

Dev builds lead toward the **next patch**: the publish workflow takes the highest
final on PyPI, bumps the patch (e.g. `0.3.9` → `0.3.10`), and publishes the next
free `0.3.10.devN`. Pass an explicit `version` to the workflow for minor/major dev
builds (e.g. `0.4.0.dev1`).

## The loop

```bash
# 1. Publish (auto-increments; includes a 10s settle for PyPI to process)
gh workflow run publish-dev.yml
gh run watch <run-id> --exit-status        # note the resolved version in the summary

# 2. Deploy that exact version
./scripts/deploy_local.sh update --env devtest --profile tellr-dev --from-pypi <version>

# 3. Open the app URL and verify
```

`devtest` deploys app `db-tellr-devtest`, reusing the `db-tellr` lakebase with
schema `devtest_app_data`. Use `create` if the app does not exist yet.

If the deploy's BUILD phase reports `Could not find a version ...` immediately after
publishing, that's proxy mirror lag — wait a moment and re-run the deploy step.

## Workflows

- `publish-dev.yml` — `workflow_dispatch`, publishes dev `.devN` to real PyPI.
- `publish.yml` — tagged (`v*`) final releases to real PyPI. Unchanged; not for dev.

See also the `deploy-tellr-dev` skill (`.claude/skills/deploy-tellr-dev/`).

## Per-instance dev loop (`devloop`) — branch off prod

For agentic dev loops that run multiple deployments at once, use the `devloop`
env with an `--instance <id>`. Each instance gets its own app
(`db-tellr-dev-<id>`) and a fresh copy-on-write branch of production Lakebase
(`branches/dev-<id>`), recreated on every deploy:

```bash
gh workflow run publish-dev.yml          # publish the next .devN
./scripts/deploy_local.sh create --env devloop --instance agent-7f3a \
    --profile tellr-dev --from-pypi <version>    # first deploy
./scripts/deploy_local.sh update --env devloop --instance agent-7f3a \
    --profile tellr-dev --from-pypi <version>    # iterate (reuses app, refreshes branch)
./scripts/deploy_local.sh delete --env devloop --instance agent-7f3a \
    --profile tellr-dev                          # teardown (app + branch)
```

`--instance` must match `^[a-z][a-z0-9-]*$` and be ≤59 chars. Concurrent
instances are fully isolated. The app compute is created once and reused; the
branch is deleted and re-forked from prod on every deploy (fresh prod data each
time — anything written to an instance is wiped on its next deploy).

Each instance is a full prod mirror: it can create tables, read/write prod data,
and run `ALTER`-bearing migrations against inherited prod tables. Ownership of
`app_data_prod` lives on the shared `tellr_app_owners` role; on `create` the
deploy triggers a serverless job (running as a dedicated granter SP) that grants
the instance's service principal into that role, so its migrations can alter the
inherited tables. See `docs/technical/lakebase-table-ownership.md`.

## Fernet key handling (why there is no dev/prod divergence)

The Fernet master key that encrypts OAuth credentials lives in the
`encryption_keys` Lakebase table (row `id = 1`), **not** in `app.yaml`. This is
the runtime source of truth on every path (see `src/core/encryption.py`).

**Boot owns the one-time legacy→table migration.** On the cutover boot, if the
table is empty, boot seeds the row from the `GOOGLE_OAUTH_ENCRYPTION_KEY` env
var (the old app.yaml location), then best-effort scrubs that plaintext key out
of the deployed `app.yaml`. Because key resolution is SELECT-first, the env var
is read only on that first boot; every later boot reads the row. The scrub never
blocks boot and only deletes a copy that exactly matches the validated table key.

**Deploy tools carry the key forward — they do not relocate it via DDL.** Both
`tellr.update` and `deploy_local update` read any existing
`GOOGLE_OAUTH_ENCRYPTION_KEY` out of the deployed `app.yaml` and re-emit it into
the regenerated `app.yaml`, so the *next* boot can perform the migration above.
The earlier deploy-time DDL relocation was removed: deploy tools no longer touch
the `encryption_keys` table.

**The devloop/fork path inherits the key via copy-on-write.** A forked branch
already carries the seeded `encryption_keys` row from prod, so no key is written
into the fork's `app.yaml`. This only works if the source env was migrated once
first — the fork preflight (`_check_branching_preconditions`) deliberately
**aborts** if the source env's `app.yaml` still carries a legacy key, telling you
to update the source env first. Keep that check.

**The rule this enforces:** boot performs the migration identically on every
path — the UI **Deploy** button (which reuses the existing `app.yaml`),
`tellr.update`, and `deploy_local update`. So code that works under
`deploy_local` also works under a UI-button upgrade; there is no dev/prod
divergence in key handling. This is the divergence that caused the original
data-loss bug, and it is why the migration lives in boot rather than in a deploy
step.
