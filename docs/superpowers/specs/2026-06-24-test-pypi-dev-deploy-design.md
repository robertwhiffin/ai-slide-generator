# Test-PyPI dev eval loop — Design

**Date:** 2026-06-24
**Status:** Approved (design); ready for implementation plan

## Problem

`scripts/deploy_local.py` deploys the app by building the wheel locally,
uploading it into the app's workspace `source_code_path` (`{workspace_path}/wheels/*.whl`),
and referencing it as a relative `./wheels/*.whl` in `requirements.txt`. Databricks
Apps snapshot `source_code_path` into the service-principal's area and copy it to
the container's local disk at deploy time; the **app source bundle has a ~10MB cap**.

The `databricks-tellr-app` wheel is **~31MB** because it bundles the huashu
(Claude Design PPTX) sidecar runtime as two tarballs:

- `node_modules.tar.gz` (~12.4MB)
- `sys-libs-bullseye.tar.gz` (~18.7MB)

At app boot, `app.yaml.template` runs the bundled `setup.sh`, which **extracts those
tarballs** from the pip-installed package (`databricks_tellr_app/_assets/sidecars/pptx-emit-huashu/`)
and runs `playwright install chromium`. So the tarballs must be present in the
installed wheel for huashu to work.

Because the local wheel lives inside `source_code_path`, deploy_local hits the app
cap and fails. **Production does not hit this**: prod's `requirements.txt` is just
`databricks-tellr-app` (bare), the app source bundle contains only `app.yaml` +
`requirements.txt`, and pip downloads the full 31MB wheel from PyPI **into the
container at boot** — never into the source bundle. (Empirically confirmed:
`pip download databricks-tellr-app` → `databricks_tellr_app-0.3.9-py3-none-any.whl`,
31MB, containing both tarballs.)

### Ruled-out alternatives

- **Strip the tarballs from the dev wheel** (current AISEC-248 branch behaviour):
  shrinks the wheel to ~4MB and fits the cap, but `setup.sh` then finds no tarballs
  → huashu silently dies. Would also break prod if published.
- **Absolute `/Workspace/...` path in requirements.txt**: Apps containers do **not**
  FUSE-mount Workspace Files (per internal Apps "Filesystems & Persistence" docs —
  workspace files are API-accessible only). pip cannot read a `/Workspace` path.
- **Manual upload of tarballs to the SP folder post-deploy**: the container runs from
  a one-time local snapshot, `/Workspace` is not mounted, `setup.sh` reads from
  ephemeral site-packages, and containers re-provision on restart. Nothing manual
  survives.
- **Unity Catalog Volumes**: excluded by requirement (adds deployment complexity).

## Goal

Make dev deploys behave like prod: **the app pulls the full huashu-bearing wheel
from a package index at boot**, so nothing large lands in the source bundle and
huashu works in dev. Use **test-PyPI** as the dev index. Keep it an agent-drivable,
one-command loop: give a version → CI builds + publishes to test-PyPI → app is
(re)deployed against that version → dev logs in.

## Components

### A. New workflow: `.github/workflows/publish-testpypi.yml`

Mirrors the existing `publish.yml` build so the dev wheel is byte-for-byte the same
shape as the prod wheel, differing only in trigger, versioning, and publish target.

- **Trigger:** `workflow_dispatch` with a required input `version` (PEP 440 string,
  e.g. `0.3.9.dev3`). The dev/agent supplies it.
- **Scope: only `databricks-tellr-app` is published.** It depends solely on
  third-party packages (fastapi, langchain, etc.), all on real PyPI — it does **not**
  depend on `databricks-tellr`. So its deps resolve from real PyPI via the
  extra-index, and nothing else needs publishing. `databricks-tellr` (the deploy CLI)
  is run locally from the repo for the deploy step, so it is **not** published to
  test-PyPI. (Can be added later if a dev ever wants to test the CLI from test-PyPI.)
- **`build` job:**
  - `actions/checkout@v4`; `setup-python@v5` (3.12); `setup-node@v4` (20); `pip install build`.
  - Stamp `version` into `packages/databricks-tellr-app/pyproject.toml`
    (in-runner only, not committed).
  - `cp -r src packages/databricks-tellr-app/src`; build `databricks-tellr-app`
    (sdist + wheel); `rm -rf packages/databricks-tellr-app/src`.
  - **Verify gate:** assert the built app wheel contains
    `databricks_tellr_app/_assets/sidecars/pptx-emit-huashu/node_modules.tar.gz`
    and `sys-libs-bullseye.tar.gz`, and that the wheel is ≥ ~25MB. Fail the job
    otherwise. (Prevents silently shipping a huashu-less wheel.)
  - Upload the `dist/` artifact.
  - **No `build-artifacts.sh`** — rely on the committed tarballs in
    `services/pptx-emit-huashu/` (identical to what 0.3.9 shipped) plus the verify gate.
- **`publish-tellr-app` job:**
  - `needs: build`; `environment: testpypi`; `permissions: id-token: write`.
  - Download the dist artifact.
  - `pypa/gh-action-pypi-publish@release/v1` with
    `repository-url: https://test.pypi.org/legacy/`.
- **Summary:** print the exact consumption command for the published version
  (`./scripts/deploy_local.sh update --env <env> --profile <profile> --from-test-pypi <version>`).

### B. `deploy_local.py` consumption: `--from-test-pypi <version>` mode

Contained to `create_local` / `update_local` in `scripts/deploy_local.py` (which
currently reimplement staging rather than calling `deploy.py`'s public entry points).

When `--from-test-pypi <version>` is set:

- **Skip** `build_wheels.sh` (handled by `deploy_local.sh`) and **skip** `upload_wheel`
  (no local wheel uploaded; nothing large enters the bundle).
- Write requirements via `_write_requirements(staging_dir, app_version=<version>)`
  → pins `databricks-tellr-app==<version>` (the existing PyPI branch).
- Write app.yaml via `_write_app_yaml(..., use_test_pypi=True)` → injects
  `--index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/`
  into `PIP_INDEX_ARGS` (already implemented). App deps resolve from real PyPI via
  the extra-index; our two packages from test-PyPI.
- Everything else (lakebase resolution, encryption-key preservation, uploading
  app.yaml + requirements.txt, `deploy_and_wait`) reuses the existing flow.

Plumbing:

- `scripts/deploy_local.py` argparse: add `--from-test-pypi <version>`, thread into
  `create_local` / `update_local`.
- `scripts/deploy_local.sh`: add a `--from-test-pypi <version>` passthrough that also
  **skips the wheel build step** (Step 1) when present, and forwards the flag to
  `python -m scripts.deploy_local`.

### C. Agent orchestration loop (documented, no new script)

The agent, on request, runs:

1. `gh workflow run publish-testpypi.yml -f version=<X>`
2. `gh run watch` (or poll `gh run list`) until success
3. `./scripts/deploy_local.sh update --env <dev-env> --profile <profile> --from-test-pypi <X>`

The dev then opens the deployed app URL and logs in. No wrapper script is built
(YAGNI); the three commands are the loop, documented in the deploy README/usage.

## One-time setup (operational, outside code)

- Configure **trusted publishing** on test.pypi.org for `databricks-tellr-app`:
  publisher = this GitHub repo, workflow file `publish-testpypi.yml`,
  environment `testpypi`.
- Create the `testpypi` GitHub Actions environment.

## Assumptions / risks

- **Runtime egress:** the deployed app container can reach `test.pypi.org` at boot
  to pip-install the wheel. (Per decision: proxies do not constrain Databricks
  workspace egress.) If this proves false, the fallback is publishing dev versions
  to real PyPI instead — same workflow shape, different `repository-url`.
- **test-PyPI immutability:** a version cannot be re-uploaded. The dev/agent supplies
  a fresh `version` each run; the workflow fails clearly if the version already exists.
  Churn is confined to test-PyPI (sandbox); real PyPI and prod version history are
  untouched (those only get `v*` tag releases via `publish.yml`).
- **Dependency resolution lag:** test-PyPI may take a few seconds to index a new
  upload before it is installable. The app's boot `pip install --upgrade` will pick
  it up; if a deploy races the index, re-running the deploy step resolves it.

## Out of scope

- Changing `publish.yml` (real-PyPI release path) — unchanged.
- A dedicated orchestration script/skill for the agent loop.
