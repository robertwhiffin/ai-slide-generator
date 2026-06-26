# Real-PyPI dev-deploy loop — Design

**Date:** 2026-06-26
**Status:** Approved (design); ready for implementation plan
**Supersedes:** `2026-06-24-test-pypi-dev-deploy-design.md` (test-PyPI approach — proven unworkable on Databricks Apps; see Root cause. Removed as part of this change — see Cleanup).

## Problem

`scripts/deploy_local.py` deploys the app by building the wheel locally and
uploading it into the app's `source_code_path`. Databricks Apps snapshot
`source_code_path` into the service-principal's area and copy it to the
container's local disk; the **app source bundle has a ~10MB cap**. The
`databricks-tellr-app` wheel is **~31MB** (it bundles the huashu PPTX sidecar as
`node_modules.tar.gz` ~12MB + `sys-libs-bullseye.tar.gz` ~19MB), so dev deploys
that upload the wheel hit the cap and fail.

Production does not hit this: prod's `requirements.txt` is the bare
`databricks-tellr-app`, the source bundle contains only `app.yaml` +
`requirements.txt`, and the wheel is pulled from a package index at install
time — never into the source bundle.

The goal is a dev loop that behaves like prod: the app pulls a full,
huashu-bearing wheel from a package index at install time, keyed by a dev
version, so nothing large enters the source bundle.

## Root cause of the failed test-PyPI approach (institutional knowledge)

The prior design published dev wheels to **test-PyPI** and injected
`--index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/`
into the `app.yaml` `command:` block. **This cannot work on Databricks Apps**, and
the reason must be recorded so it is not re-attempted:

- **Databricks Apps installs `requirements.txt` in a platform-managed `[BUILD]`
  phase, using the internal PyPI proxy** (`pypi-proxy.dev.databricks.com`), which
  **mirrors public/real PyPI only — not test-PyPI**.
- That BUILD phase runs **before** the `app.yaml` `command:` ever executes. The
  custom `--index-url` args live in the command (RUN layer) and are **never
  reached**.
- Evidence (deploy of `db-tellr-devtest` against `0.3.9.dev2`): logs showed
  **22 `[BUILD]` lines, 1 `[SYSTEM]`, zero `[APP]`/`[RUN]`**; no
  `Looking in indexes: test.pypi.org` line; the build failed in **~1.4s**
  (too fast to be a blocked-egress retry against a public host); and the pip
  candidate list was exactly the real-PyPI finals set `0.1.0…0.3.9` with **no
  `.devN`** — i.e. it resolved against the proxy, which has no test-PyPI versions.
- A driver-node notebook *could* `pip download databricks-tellr-app==0.3.9.dev2`
  from test-PyPI with the same args — because the notebook ran pip directly. The
  App platform does not; the notebook is not a faithful stand-in for the App
  BUILD phase.

**Conclusion:** "deploy like prod" means "publish where the proxy can see it."
The proxy mirrors **real PyPI**, so dev wheels must go to **real PyPI**.

## Goal

Publish dev builds of both packages to **real PyPI** as PEP 440 developmental
(`.devN`) pre-releases, and deploy them by pinning the exact version in
`requirements.txt`. The Apps BUILD phase resolves them via the proxy — identical
in shape to prod. Keep it an agent-drivable loop: dispatch a publish, then deploy
the exact version it produced.

## Decisions

1. **Real PyPI, same package name.** Dev versions publish under the existing
   `databricks-tellr-app` (and `databricks-tellr`) projects as `.devN`
   pre-releases. **Prod is unaffected:** pip excludes pre-releases by default, so
   a bare `pip install databricks-tellr-app` (prod's path) always resolves to the
   highest *final*. A dev is only selectable via explicit `--pre` *and* a higher
   base than any final — never the default path. Cost accepted: `.devN` releases
   are visible on the public project page.
2. **Auto-increment.** The publish workflow computes the next `.devN` itself, so
   agents never block on a version-name collision.
3. **Dev builds lead toward the next patch.** Base = `highest final on PyPI` +
   patch bump (e.g. highest final `0.3.9` → base `0.3.10`), then the next free
   `devN` within that base. Basing off the highest *final* guarantees dev builds
   sort ahead of every release. An explicit `version` input overrides this for
   minor/major dev builds.
4. **Codify for both agents and humans:** a committed project skill + a human
   doc + a root `CLAUDE.md` pointer.

## Components

### A. New workflow `.github/workflows/publish-dev.yml` (replaces `publish-testpypi.yml`)

Repurposes the publish-testpypi workflow; `publish-testpypi.yml` is **deleted**.

- **Trigger:** `workflow_dispatch` with an **optional** `version` input (PEP 440).
- **`build` job — version resolution:**
  - If `version` supplied → validate PEP 440 and use it.
  - If omitted → query `https://pypi.org/pypi/databricks-tellr-app/json`, parse
    `releases` with `packaging.version`; `base = highest_final + patch bump`;
    `N = max(existing base.devN) + 1` (or `dev1` if none); version = `base.devN`.
    A 404 (project never published) means start at `<base>.dev1`.
  - Stamp the resolved version into **both** `pyproject.toml` files (they stay
    version-locked).
- **`build` job — packaging (unchanged from current):** build both
  `databricks-tellr` and `databricks-tellr-app`; run the **verify gate** —
  assert the app wheel contains both huashu tarballs
  (`databricks_tellr_app/_assets/sidecars/pptx-emit-huashu/{node_modules,sys-libs-bullseye}.tar.gz`)
  and is ≥ 25MB; upload dist artifacts.
- **`publish-tellr` + `publish-tellr-app` jobs:** `needs: build`,
  `environment: pypi`, `permissions: id-token: write`,
  `pypa/gh-action-pypi-publish@release/v1` with the **default `repository-url`**
  (real PyPI). Reuses the existing real-PyPI trusted publisher that `publish.yml`
  already uses — **no new PyPI setup.**
- **Summary:** print the resolved version and the consume command.
- **`publish.yml` (tagged final releases) is untouched.** Tags → finals,
  dispatch → devs.

Consequence (accepted): the dispatch workflow publishes to real PyPI under the
same `pypi` environment/trusted publisher as prod releases, i.e. it carries
real-PyPI publish rights.

### B. Consumer side — `deploy_local` + `app.yaml`

- **Remove the test-PyPI index machinery.** In `databricks_tellr.deploy`,
  `_write_app_yaml` drops the `use_test_pypi` parameter and the
  `--index-url`/`--extra-index-url` injection. The boot command reverts to the
  plain prod shape: `pip install --upgrade --no-cache-dir -r requirements.txt`.
  The Apps BUILD phase + proxy resolve the pinned version; no custom index
  anywhere.
- **`requirements.txt`** for a dev deploy is just `databricks-tellr-app==<devN>`
  (already how `_write_requirements` emits it).
- **Rename `--from-test-pypi <version>` → `--from-pypi <version>`** in
  `scripts/deploy_local.py` and `scripts/deploy_local.sh`. Behaviour unchanged
  otherwise: skip local wheel build/upload, pin the given version, deploy.
  Keep the `_is_valid_version` (PEP 440) check.
- **No `--from-pypi latest`.** Agents pass the exact version the publish step
  emitted — deterministic, and avoids racing the proxy mirror.

The agent loop:

1. `gh workflow run publish-dev.yml` (auto-resolves `0.3.10.devN`, publishes,
   prints the version).
2. Capture the version `X` from the run summary.
3. `./scripts/deploy_local.sh update --env devtest --profile tellr-dev --from-pypi X`.

### C. Codification

- **Project skill** `.claude/skills/deploy-tellr-dev/SKILL.md` (committed; first
  in-repo skill). Its `description` triggers on deploying a tellr dev/test build
  to a Databricks Apps dev workspace. Content: when to use; the BUILD-phase "why"
  (real PyPI required, test-PyPI/custom-index-in-command does **not** work, with
  the evidence so nobody re-attempts it); the 3-step loop; reading deploy logs
  (OAuth profile `tellr-dev-oauth`); the `db-tellr-devtest` env as the canonical
  test target.
- **Human doc** `docs/technical/dev-deploy.md`, cross-linked from
  `docs/technical/databricks-app-deployment.md`. Fuller narrative: 10MB-cap
  origin, BUILD-phase/proxy mechanism, real-PyPI `.devN` + prod-safety (pip
  pre-release exclusion), version convention (next-patch `.devN`), auto-increment.
- **Root `CLAUDE.md`** (new) with a short "Deploying dev builds" section pointing
  at the skill and the doc, so the process is discovered every session.

### D. Cleanup

- **Delete `.github/workflows/publish-testpypi.yml`** (on `main` via PR #199 and
  on the feature branch); `publish-dev.yml` replaces it.
- **Delete the `testpypi` GitHub Actions environment** (`gh api --method DELETE`).
- **test-PyPI trusted publishers** and the already-published `dev1`/`dev2` live on
  test.pypi.org (immutable, harmless, unreferenced by the repo) — optional manual
  cleanup, noted, not required.
- **Keep** the `db-tellr-devtest` app, the `devtest_app_data` schema in `db-tellr`,
  and the `devtest` env in `config/deployment.yaml` — they are the validation
  target.
- Update the two project memory notes (huashu wheel-size; test-PyPI auto-increment)
  to record the BUILD-phase finding and the real-PyPI decision.
- **Delete the superseded spec** `docs/superpowers/specs/2026-06-24-test-pypi-dev-deploy-design.md`
  (this document replaces it; no test-PyPI design left floating).

## Validation

- **End-to-end is the real test:** dispatch `publish-dev.yml` (auto →
  `0.3.10.dev1`), then `deploy_local --from-pypi 0.3.10.dev1 --env devtest`.
  Success = the app reaches the **`[APP]`/RUN phase**, installs from the proxy,
  and the URL loads. That single success validates the whole pivot.
- **Mirror lag:** if the proxy has not yet mirrored the just-published version,
  the deploy's BUILD phase fails transiently → re-run the deploy step.
- The workflow verify gate guards build shape; auto-increment avoids immutability
  collisions.
- No meaningful unit-test surface (workflow YAML + a flag rename) — validation is
  the deploy itself.

## Assumptions / risks

- **Proxy mirrors pre-releases with acceptable lag.** The proxy demonstrably
  serves released finals (`0.1.0…0.3.9`). `.devN` pre-releases are ordinary files
  on real PyPI and should mirror the same way; lag is handled by re-running the
  deploy. If the proxy were found *not* to mirror pre-releases at all, the
  fallback is to publish dev builds as full patch releases — undesirable, but the
  same workflow shape.
- **Prod safety** rests on pip's default pre-release exclusion (documented above)
  and the fact that prod installs the bare package name with no `--pre`.
- **Real-PyPI publish rights** now attach to a `workflow_dispatch` workflow
  (`environment: pypi`). Accepted: the dev workflow is owner-triggered and uses
  the same trusted publisher as the existing release path.

## Out of scope

- Changing `publish.yml` (real-PyPI tagged-release path) — unchanged.
- A `--from-pypi latest` resolver, or a dedicated orchestration wrapper script
  (the three commands are the loop).
- Reconciling the feature branch with `main` (separate hygiene task).
