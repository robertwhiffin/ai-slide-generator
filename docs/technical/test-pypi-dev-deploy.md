# Test-PyPI Dev Evaluation Loop

**One-line summary**: Deploy dev builds the same way prod does — the app pip-installs the full huashu-bearing wheel from an index at boot — using test-PyPI as the dev index so nothing oversized lands in the app source bundle.

---

## Why This Exists

The `databricks-tellr-app` wheel is **~31MB** because it bundles the huashu (Claude
Design PPTX) sidecar as two tarballs (`node_modules.tar.gz` ~12.4MB,
`sys-libs-bullseye.tar.gz` ~18.7MB). At app boot, `setup.sh` extracts those tarballs
from the installed package, so they must be present in the wheel.

Databricks Apps cap the deployed **source bundle at ~10MB**. `deploy_local.py`'s default
flow uploads the locally built wheel *into* the app's `source_code_path` and references
it as `./wheels/*.whl` in `requirements.txt` — which blows past the cap and fails.

**Production avoids this entirely**: prod's `requirements.txt` is just bare
`databricks-tellr-app`, the source bundle contains only `app.yaml` + `requirements.txt`,
and pip downloads the full 31MB wheel from PyPI **into the container at boot** — never
into the source bundle. This loop replicates that pattern for dev, swapping real PyPI for
**test-PyPI** as the dev index.

---

## One-Time Setup

No tokens required — publishing uses GitHub OIDC trusted publishing.

1. **Configure trusted publishing on test.pypi.org** for `databricks-tellr-app`. Add a
   pending publisher (Account settings → Publishing) with:

   | Field | Value |
   |-------|-------|
   | PyPI Project Name | `databricks-tellr-app` |
   | Owner | `robertwhiffin` |
   | Repository name | `ai-slide-generator` |
   | Workflow name | `publish-testpypi.yml` |
   | Environment name | `testpypi` |

2. **Create the `testpypi` GitHub Actions environment** (Repo Settings → Environments →
   New environment → `testpypi`). The publish job references `environment: testpypi`.

---

## The Dev Loop

Three commands. Pick a fresh `<X>` version each run (e.g. `0.3.9.dev3`).

```bash
# 1. Build the full (huashu-bearing) wheel and publish it to test-PyPI
gh workflow run publish-testpypi.yml -f version=<X>

# 2. Wait for the run to succeed
gh run watch

# 3. Deploy the app pinned to that test-PyPI version
./scripts/deploy_local.sh update --env <dev-env> --profile <profile> --from-test-pypi <X>
```

Then open the deployed app URL and log in.

The `--from-test-pypi <X>` mode skips the local wheel build and upload (nothing large
enters the source bundle), pins `databricks-tellr-app==<X>` in `requirements.txt`, and
injects `--index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/`
into the app's pip command so app dependencies still resolve from real PyPI while our
package comes from test-PyPI.

---

## Notes / Caveats

- **Versions are immutable on test-PyPI.** A version cannot be re-uploaded — supply a
  fresh `version` each run (bump the `.devN` suffix). The workflow fails clearly if the
  version already exists.
- **Churn is confined to test-PyPI.** Real PyPI and prod version history are untouched;
  those only get `v*` tag releases via `publish.yml`.
- **The app container must reach `test.pypi.org` at boot** to pip-install the wheel. If
  egress to test-PyPI is blocked, the fallback is publishing dev versions to real PyPI
  (same workflow shape, different `repository-url`).
- **Brief indexing lag.** test-PyPI may take a few seconds to index a new upload before
  it is installable. If the deploy step races the index, simply re-run step 3.

---

## Cross-References

- `docs/technical/databricks-app-deployment.md` – two-package distribution, app.yaml,
  the prod PyPI install-at-boot model, and `use_test_pypi` deployment flag.
- `.github/workflows/publish-testpypi.yml` – the build + publish workflow.
- `.github/workflows/publish.yml` – the real-PyPI release path (`v*` tags), unchanged.
- `scripts/deploy_local.sh` / `scripts/deploy_local.py` – the `--from-test-pypi` mode.
