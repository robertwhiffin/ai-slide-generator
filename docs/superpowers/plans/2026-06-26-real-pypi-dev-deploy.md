# Real-PyPI Dev-Deploy Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the unworkable test-PyPI dev-deploy path with one that publishes dev `.devN` pre-releases to real PyPI (which the Databricks Apps build proxy mirrors), and codify the process so agents and humans use it correctly.

**Architecture:** A `workflow_dispatch` workflow (`publish-dev.yml`) builds both packages, auto-increments the next-patch `.devN` version (querying PyPI's JSON API), publishes to real PyPI via the existing `pypi` trusted publisher, then waits 10s so PyPI can process the upload. The consumer (`deploy_local --from-pypi <version>`) pins that version in `requirements.txt`; the Apps BUILD phase resolves it through the internal proxy exactly like prod. All test-PyPI index machinery is removed.

**Tech Stack:** GitHub Actions, `pypa/gh-action-pypi-publish`, Python 3.12 (`packaging`, `urllib`), Databricks SDK, bash, pytest.

## Global Constraints

- Python version in CI: **3.12**; Node: **20** (copy from existing workflows).
- Both packages stay **version-locked** — the same resolved version is stamped into `packages/databricks-tellr/pyproject.toml` and `packages/databricks-tellr-app/pyproject.toml`.
- App wheel must contain both huashu tarballs (`databricks_tellr_app/_assets/sidecars/pptx-emit-huashu/node_modules.tar.gz`, `sys-libs-bullseye.tar.gz`) and be **≥ 25MB** (verify gate).
- Dev versions are PEP 440 **developmental** releases (`.devN`); published under the existing package names on **real PyPI**.
- Publish auth is **OIDC trusted publishing**, `environment: pypi` (no tokens).
- Do **not** edit `packages/databricks-tellr/build/` — it is generated build output.
- Work happens on branch `feat/devops-test-pypi-dev-deploy`; the final PR to `main` also removes `publish-testpypi.yml` from `main`.

---

### Task 1: Replace `publish-testpypi.yml` with `publish-dev.yml`

**Files:**
- Create: `.github/workflows/publish-dev.yml`
- Delete: `.github/workflows/publish-testpypi.yml`

**Interfaces:**
- Produces: a `workflow_dispatch` workflow named `Publish Dev to PyPI`, file `publish-dev.yml`, optional input `version`. Emits the resolved version in the run summary and prints the consume command.

- [ ] **Step 1: Write `publish-dev.yml`**

```yaml
name: Publish Dev to PyPI

on:
  workflow_dispatch:
    inputs:
      version:
        description: "Optional explicit PEP 440 dev version (e.g. 0.4.0.dev1). Leave blank to auto-increment the next patch .devN."
        required: false
        type: string

env:
  PYTHON_VERSION: "3.12"
  NODE_VERSION: "20"

jobs:
  build:
    name: Build Packages
    runs-on: ubuntu-latest
    outputs:
      version: ${{ steps.resolve.outputs.version }}
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: "pip"

      - uses: actions/setup-node@v4
        with:
          node-version: ${{ env.NODE_VERSION }}
          cache: "npm"
          cache-dependency-path: frontend/package-lock.json

      - name: Install build tools
        run: pip install build packaging

      - name: Resolve dev version
        id: resolve
        env:
          INPUT_VERSION: ${{ inputs.version }}
        run: |
          python - <<'PY' >> "$GITHUB_OUTPUT"
          import json
          import os
          import urllib.error
          import urllib.request
          from packaging.version import Version

          explicit = os.environ.get("INPUT_VERSION", "").strip()
          if explicit:
              v = Version(explicit)  # raises if not PEP 440
              if not v.is_prerelease or v.dev is None:
                  raise SystemExit(
                      f"ERROR: explicit version '{explicit}' must be a .devN pre-release"
                  )
              print(f"version={explicit}")
              raise SystemExit(0)

          url = "https://pypi.org/pypi/databricks-tellr-app/json"
          try:
              with urllib.request.urlopen(url, timeout=30) as resp:
                  data = json.load(resp)
              releases = [Version(v) for v in data.get("releases", {})]
          except urllib.error.HTTPError as e:
              if e.code == 404:
                  releases = []
              else:
                  raise

          finals = [v for v in releases if not v.is_prerelease]
          highest_final = max(finals) if finals else Version("0.0.0")
          base = f"{highest_final.major}.{highest_final.minor}.{highest_final.micro + 1}"

          devs = [
              v.dev for v in releases
              if v.dev is not None
              and (v.major, v.minor, v.micro) == tuple(int(x) for x in base.split("."))
          ]
          next_n = (max(devs) + 1) if devs else 1
          print(f"version={base}.dev{next_n}")
          PY
          echo "Resolved version: $(grep '^version=' "$GITHUB_OUTPUT" | tail -1)"

      - name: Stamp version into both pyproject.toml files
        env:
          RESOLVED_VERSION: ${{ steps.resolve.outputs.version }}
        run: |
          python - <<'PY'
          import os
          import pathlib
          import re
          import tomllib

          version = os.environ["RESOLVED_VERSION"]
          for path in (
              pathlib.Path("packages/databricks-tellr/pyproject.toml"),
              pathlib.Path("packages/databricks-tellr-app/pyproject.toml"),
          ):
              text = path.read_text()
              new_text, count = re.subn(
                  r'(?m)^version\s*=\s*".*"$', f'version = "{version}"', text, count=1
              )
              if count != 1:
                  raise SystemExit(f"ERROR: expected one version line in {path}, replaced {count}")
              path.write_text(new_text)
              stamped = tomllib.loads(path.read_text())["project"]["version"]
              print(f"Stamped {stamped} into {path}")
          PY

      - name: Build databricks-tellr
        run: python -m build --sdist --wheel packages/databricks-tellr

      - name: Build databricks-tellr-app
        run: |
          cp -r src packages/databricks-tellr-app/src
          python -m build --sdist --wheel packages/databricks-tellr-app
          rm -rf packages/databricks-tellr-app/src

      - name: Verify built artifacts (huashu tarballs present, wheel >= 25MB)
        run: |
          python - <<'PY'
          import glob, os, sys, zipfile
          wheels = glob.glob("packages/databricks-tellr-app/dist/*.whl")
          if len(wheels) != 1:
              sys.exit(f"ERROR: expected exactly one wheel, found: {wheels}")
          wheel = wheels[0]
          size_mb = os.path.getsize(wheel) / (1024 * 1024)
          print(f"Wheel: {wheel} ({size_mb:.1f} MB)")
          base = "databricks_tellr_app/_assets/sidecars/pptx-emit-huashu"
          required = [f"{base}/node_modules.tar.gz", f"{base}/sys-libs-bullseye.tar.gz"]
          with zipfile.ZipFile(wheel) as zf:
              names = set(zf.namelist())
          missing = [n for n in required if n not in names]
          if missing:
              sys.exit("ERROR: wheel missing huashu tarball(s): " + ", ".join(missing))
          if size_mb < 25:
              sys.exit(f"ERROR: wheel is {size_mb:.1f} MB, under the 25MB floor")
          print("Verify gate passed.")
          PY

      - name: Upload tellr dist
        uses: actions/upload-artifact@v4
        with:
          name: dist-tellr
          path: packages/databricks-tellr/dist/

      - name: Upload tellr-app dist
        uses: actions/upload-artifact@v4
        with:
          name: dist-tellr-app
          path: packages/databricks-tellr-app/dist/

  publish-tellr:
    name: Publish databricks-tellr to PyPI
    runs-on: ubuntu-latest
    needs: build
    environment: pypi
    permissions:
      id-token: write
    steps:
      - name: Download dist
        uses: actions/download-artifact@v4
        with:
          name: dist-tellr
          path: dist/
      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1

  publish-tellr-app:
    name: Publish databricks-tellr-app to PyPI
    runs-on: ubuntu-latest
    needs: build
    environment: pypi
    permissions:
      id-token: write
    steps:
      - name: Download dist
        uses: actions/download-artifact@v4
        with:
          name: dist-tellr-app
          path: dist/
      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1

  settle:
    name: Settle (let PyPI process the upload)
    runs-on: ubuntu-latest
    needs: [build, publish-tellr, publish-tellr-app]
    steps:
      - name: Wait 10s for PyPI to process the upload
        run: sleep 10
      - name: Write deploy summary
        env:
          RESOLVED_VERSION: ${{ needs.build.outputs.version }}
        run: |
          {
            echo "## Published dev build to PyPI"
            echo ""
            echo "**Version:** \`${RESOLVED_VERSION}\` (databricks-tellr + databricks-tellr-app)"
            echo ""
            echo "### Deploy it"
            echo '```bash'
            echo "./scripts/deploy_local.sh update --env devtest --profile tellr-dev --from-pypi ${RESOLVED_VERSION}"
            echo '```'
          } >> "$GITHUB_STEP_SUMMARY"
```

- [ ] **Step 2: Delete the old workflow**

```bash
git rm .github/workflows/publish-testpypi.yml
```

- [ ] **Step 3: Validate the YAML parses**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/publish-dev.yml'))" && echo OK`
Expected: `OK`

- [ ] **Step 4: (If available) lint with actionlint**

Run: `command -v actionlint >/dev/null && actionlint .github/workflows/publish-dev.yml || echo "actionlint not installed; skipping"`
Expected: no errors, or the skip message.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/publish-dev.yml
git commit -m "ci(devops): replace publish-testpypi with publish-dev (real PyPI, auto-increment, settle)"
```

---

### Task 2: Remove `use_test_pypi` machinery from `deploy.py` + template

**Files:**
- Modify: `packages/databricks-tellr/databricks_tellr/deploy.py` (`create`, `update`, `_create_databricks`, `_update_databricks`, `_write_app_yaml`)
- Modify: `packages/databricks-tellr/databricks_tellr/_templates/app.yaml.template:10`
- Test: `tests/unit/test_deploy_app_yaml.py` (new)

**Interfaces:**
- Produces: `_write_app_yaml(staging_dir, lakebase_name, schema_name, seed_databricks_defaults=False, encryption_key=None, lakebase_result=None, mlflow_tracing=None)` — **no** `use_test_pypi` parameter. Generated `app.yaml` boot command is `pip install --upgrade --no-cache-dir -r requirements.txt` with no index args.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_deploy_app_yaml.py`:

```python
import inspect
from pathlib import Path

from databricks_tellr import deploy


def test_write_app_yaml_has_no_use_test_pypi_param():
    sig = inspect.signature(deploy._write_app_yaml)
    assert "use_test_pypi" not in sig.parameters


def test_generated_app_yaml_has_no_custom_index_url(tmp_path: Path):
    deploy._write_app_yaml(
        tmp_path,
        lakebase_name="db-tellr",
        schema_name="devtest_app_data",
        lakebase_result={"type": "provisioned"},
    )
    content = (tmp_path / "app.yaml").read_text()
    assert "--index-url" not in content
    assert "test.pypi.org" not in content
    assert "pip install --upgrade --no-cache-dir -r requirements.txt" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_deploy_app_yaml.py -v`
Expected: FAIL — `test_write_app_yaml_has_no_use_test_pypi_param` fails (param still present); the index-url assertion may also fail.

- [ ] **Step 3: Edit the template**

In `packages/databricks-tellr/databricks_tellr/_templates/app.yaml.template`, change line 10 from:

```
    pip install --upgrade --no-cache-dir ${PIP_INDEX_ARGS}-r requirements.txt
```

to:

```
    pip install --upgrade --no-cache-dir -r requirements.txt
```

- [ ] **Step 4: Edit `_write_app_yaml`**

In `deploy.py`, remove the `use_test_pypi: bool = False,` parameter (line ~1297) and its docstring line (~1310). Remove the `pip_index_args` block (lines ~1332–1335):

```python
    pip_index_args = (
        "--index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ "
        if use_test_pypi else ""
    )
```

And remove the `PIP_INDEX_ARGS=pip_index_args,` line (~1350) from the `Template(...).substitute(...)` call.

- [ ] **Step 5: Remove the param from the four callers**

In `deploy.py`, in each of `create` (~199), `update` (~279), `_create_databricks` (~343), `_update_databricks` (~503): delete the `use_test_pypi: bool = False,` parameter line and its docstring mention. In `create`/`update`, delete the `use_test_pypi=use_test_pypi,` argument passed downstream (~264, ~319). In `_create_databricks`/`_update_databricks`, delete the `use_test_pypi=use_test_pypi,` argument in the `_write_app_yaml(...)` call (~430, ~571).

- [ ] **Step 6: Run the new test + existing deploy tests**

Run: `pytest tests/unit/test_deploy_app_yaml.py tests/unit/test_deploy_autoscaling.py -v`
Expected: PASS (new tests pass; existing autoscaling tests still pass — they patch `_write_app_yaml` and never pass `use_test_pypi`).

- [ ] **Step 7: Commit**

```bash
git add packages/databricks-tellr/databricks_tellr/deploy.py \
        packages/databricks-tellr/databricks_tellr/_templates/app.yaml.template \
        tests/unit/test_deploy_app_yaml.py
git commit -m "refactor(deploy): drop use_test_pypi/index-url machinery (real PyPI only)"
```

---

### Task 3: Rename `--from-test-pypi` → `--from-pypi` in `deploy_local`

**Files:**
- Modify: `scripts/deploy_local.py` (`create_local`, `update_local`, argparse, `main`)
- Modify: `scripts/deploy_local.sh`
- Test: `tests/unit/test_deploy_local_args.py` (new)

**Interfaces:**
- Consumes: `deploy._write_app_yaml` and `deploy._write_requirements` from Task 2 (no `use_test_pypi`).
- Produces: `deploy_local.py` CLI flag `--from-pypi VERSION`; `create_local`/`update_local` keyword `from_pypi: Optional[str]`; result dict key `pypi_version`. `deploy_local.sh` flag `--from-pypi <version>` that skips the wheel build.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_deploy_local_args.py`:

```python
import importlib
import inspect

deploy_local = importlib.import_module("scripts.deploy_local")


def test_create_local_accepts_from_pypi_kwarg():
    params = inspect.signature(deploy_local.create_local).parameters
    assert "from_pypi" in params
    assert "from_test_pypi" not in params


def test_update_local_accepts_from_pypi_kwarg():
    params = inspect.signature(deploy_local.update_local).parameters
    assert "from_pypi" in params
    assert "from_test_pypi" not in params
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_deploy_local_args.py -v`
Expected: FAIL — signatures still use `from_test_pypi`.

- [ ] **Step 3: Rename in `deploy_local.py`**

Mechanical rename throughout `scripts/deploy_local.py`:
- Parameter `from_test_pypi` → `from_pypi` in `create_local` (~267) and `update_local` (~451), and their docstrings.
- All `if from_test_pypi:` → `if from_pypi:` (~304, ~350, ~552, ~571).
- Print strings: `"Using Test PyPI version: ..."` → `"Using PyPI version: ..."`; `"Generated requirements.txt (Test PyPI: ...)"` → `"Generated requirements.txt (PyPI: ...)"`.
- `_write_requirements(staging_dir, from_test_pypi)` → `_write_requirements(staging_dir, from_pypi)` (~351, ~572).
- Delete the now-invalid `use_test_pypi=bool(from_test_pypi),` argument in both `_write_app_yaml(...)` calls (~370, ~591) — `_write_app_yaml` no longer takes it.
- Result dict key `"test_pypi_version": from_test_pypi,` → `"pypi_version": from_pypi,` (~437, ~616).
- argparse (~719): `--from-test-pypi` → `--from-pypi`, `dest="from_test_pypi"` → `dest="from_pypi"`, update the `help=` text to "from PyPI".
- Validation (~732): `args.from_test_pypi` → `args.from_pypi`; update the error message text.
- `main` call-throughs (~756, ~764): `from_test_pypi=args.from_test_pypi` → `from_pypi=args.from_pypi`.

- [ ] **Step 4: Rename in `deploy_local.sh`**

In `scripts/deploy_local.sh`: rename the option `--from-test-pypi` → `--from-pypi`, the variable `FROM_TEST_PYPI` → `FROM_PYPI` and `FROM_TEST_PYPI_ARG` → `FROM_PYPI_ARG`, the usage/example text ("Test PyPI" → "PyPI"), the build-skip condition, and the passthrough array `(--from-pypi "$FROM_PYPI")`.

- [ ] **Step 5: Run tests + a smoke parse**

Run: `pytest tests/unit/test_deploy_local_args.py -v`
Expected: PASS.

Run: `python -m scripts.deploy_local --help 2>&1 | grep -- --from-pypi`
Expected: a line showing `--from-pypi VERSION`.

Run: `grep -c "from_test_pypi\|from-test-pypi\|FROM_TEST_PYPI" scripts/deploy_local.py scripts/deploy_local.sh`
Expected: `0` matches in each file.

- [ ] **Step 6: Commit**

```bash
git add scripts/deploy_local.py scripts/deploy_local.sh tests/unit/test_deploy_local_args.py
git commit -m "feat(deploy): rename --from-test-pypi to --from-pypi (real PyPI)"
```

---

### Task 4: Add the `deploy-tellr-dev` project skill

**Files:**
- Create: `.claude/skills/deploy-tellr-dev/SKILL.md`

**Interfaces:**
- Produces: a project skill whose `description` triggers on deploying a tellr dev/test build to a Databricks Apps dev workspace.

- [ ] **Step 1: Write the skill**

Create `.claude/skills/deploy-tellr-dev/SKILL.md`:

```markdown
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

## Reading deploy logs

App logs require OAuth (not PAT):

```bash
databricks apps logs db-tellr-devtest -p tellr-dev-oauth
```

If the token is expired: `databricks auth login --host <workspace-host> -p tellr-dev-oauth`.
A failed BUILD-phase `Could not find a version ...` right after publishing usually
means proxy mirror lag — wait and re-run the deploy step.

See `docs/technical/dev-deploy.md` for the full background.
```

- [ ] **Step 2: Verify frontmatter parses**

Run: `python -c "import yaml,io; t=open('.claude/skills/deploy-tellr-dev/SKILL.md').read(); fm=t.split('---')[1]; print(yaml.safe_load(fm)['name'])"`
Expected: `deploy-tellr-dev`

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/deploy-tellr-dev/SKILL.md
git commit -m "docs(devops): add deploy-tellr-dev project skill"
```

---

### Task 5: Add the human doc + cross-link

**Files:**
- Create: `docs/technical/dev-deploy.md`
- Modify: `docs/technical/databricks-app-deployment.md` (add a cross-link near the top)

**Interfaces:**
- Produces: `docs/technical/dev-deploy.md`, linked from `databricks-app-deployment.md`.

- [ ] **Step 1: Write `docs/technical/dev-deploy.md`**

Create `docs/technical/dev-deploy.md`:

```markdown
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
```

- [ ] **Step 2: Add a cross-link to `databricks-app-deployment.md`**

Near the top of `docs/technical/databricks-app-deployment.md` (after the first heading), add:

```markdown
> **Deploying a dev/test build?** See [dev-deploy.md](dev-deploy.md) for the dev
> loop (publish a `.devN` to real PyPI, then `deploy_local --from-pypi`).
```

- [ ] **Step 3: Commit**

```bash
git add docs/technical/dev-deploy.md docs/technical/databricks-app-deployment.md
git commit -m "docs(devops): add dev-deploy guide + cross-link"
```

---

### Task 6: Add root `CLAUDE.md` pointer

**Files:**
- Create: `CLAUDE.md`

**Interfaces:**
- Produces: a root `CLAUDE.md` with a "Deploying dev builds" section pointing at the skill and doc.

- [ ] **Step 1: Write `CLAUDE.md`**

Create `CLAUDE.md`:

```markdown
# Tellr — repo conventions for Claude

## Deploying dev builds

To deploy a dev/test build of the app to a Databricks Apps dev workspace, use the
**`deploy-tellr-dev`** skill (`.claude/skills/deploy-tellr-dev/`), or read
`docs/technical/dev-deploy.md`.

Key rule: dev wheels are published to **real PyPI** as `.devN` pre-releases — the
Databricks Apps build proxy mirrors real PyPI only, so test-PyPI / custom-index
approaches do **not** work. The loop is: `gh workflow run publish-dev.yml` →
note the version → `./scripts/deploy_local.sh update --env devtest --profile
tellr-dev --from-pypi <version>`.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(devops): add CLAUDE.md with dev-deploy pointer"
```

---

### Task 7: Cleanup of test-PyPI artifacts

**Files:** none in-repo (the old workflow and spec were already removed in Task 1 and during brainstorming).

- [ ] **Step 1: Delete the `testpypi` GitHub Actions environment**

Run: `gh api --method DELETE repos/robertwhiffin/ai-slide-generator/environments/testpypi && echo "deleted"`
Expected: `deleted` (or a 404 if already gone).

- [ ] **Step 2: Confirm no test-PyPI references remain in-repo**

Run: `grep -rn "test.pypi.org\|test-pypi\|from-test-pypi\|use_test_pypi\|publish-testpypi" --include="*.py" --include="*.sh" --include="*.yml" --include="*.md" . | grep -v "docs/superpowers/specs/2026-06-26" | grep -v "build/lib"`
Expected: no output (the only allowed mentions are historical context in the 2026-06-26 spec).

- [ ] **Step 3: Note manual cleanup (no action in repo)**

The test-PyPI trusted publishers (tellr + tellr-app) and the published `0.3.9.dev1`/`0.3.9.dev2` live on test.pypi.org. They are immutable and unreferenced; deleting them is optional and done by the maintainer in the test.pypi.org UI. No repo change.

---

### Task 8: End-to-end validation

**Files:** none (operational).

**Interfaces:**
- Consumes: `publish-dev.yml` (Task 1), `deploy_local --from-pypi` (Task 3), the `devtest` env in `config/deployment.yaml`.

- [ ] **Step 1: Push the branch and ensure `publish-dev.yml` is on `main`**

`workflow_dispatch` requires the workflow on the default branch. Open/merge the PR that lands `publish-dev.yml` (and removes `publish-testpypi.yml`) to `main` before dispatching, then:

Run: `gh workflow view publish-dev.yml`
Expected: shows the workflow (no 404).

- [ ] **Step 2: Dispatch and watch**

```bash
gh workflow run publish-dev.yml --ref feat/devops-test-pypi-dev-deploy
sleep 6
RUN_ID=$(gh run list --workflow=publish-dev.yml --limit 1 --json databaseId -q '.[0].databaseId')
gh run watch "$RUN_ID" --exit-status
```
Expected: all jobs green (build → publish-tellr + publish-tellr-app → settle). Note the resolved version from the run summary (expected `0.3.10.dev1`).

- [ ] **Step 3: Deploy the published version to `devtest`**

```bash
source .venv/bin/activate
python -m scripts.deploy_local --update --env devtest --profile tellr-dev --from-pypi <resolved-version>
```
Expected: deployment completes; prints the app URL. (If the BUILD phase reports `Could not find a version ...`, that's proxy mirror lag — re-run this step.)

- [ ] **Step 4: Confirm the app reached RUN phase**

```bash
databricks apps logs db-tellr-devtest -p tellr-dev-oauth 2>&1 | grep -oE "\[(BUILD|APP|RUN|SYSTEM)\]" | sort | uniq -c
```
Expected: at least one `[APP]`/`[RUN]` line (not BUILD-only), confirming install succeeded and the app started.

- [ ] **Step 5: Confirm app status + URL loads**

```bash
databricks apps get db-tellr-devtest -p tellr-dev -o json | python3 -c "import sys,json; d=json.load(sys.stdin); print((d.get('app_status') or {}).get('state'), d.get('url'))"
```
Expected: `RUNNING` (or `ACTIVE`/available) and the URL. Open the URL in a browser to confirm it loads.

- [ ] **Step 6: Update memory notes**

Update the two project memory notes to reflect the resolution:
- `huashu_wheel_size_investigation.md` / `testpypi_auto_increment_idea.md`: record that Databricks Apps resolve `requirements.txt` via the internal proxy at BUILD time (real-PyPI mirror only), that the dev loop publishes `.devN` to real PyPI via `publish-dev.yml`, and that auto-increment is implemented. Adjust the `MEMORY.md` index lines accordingly.
```
