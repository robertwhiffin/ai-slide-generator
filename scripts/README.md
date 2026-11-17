# Scripts

Utility scripts for the AI Slide Generator.

## `init_database.py`

Initialize the PostgreSQL database with seed profiles from YAML.

```bash
source .venv/bin/activate
python scripts/init_database.py
```

**What it does:**
1. Creates database tables (if they don't exist)
2. Loads profiles from `config/seed_profiles.yaml`
3. Creates config records (AI settings, Genie space, MLflow, prompts)

**Prerequisites:**
- PostgreSQL running with `ai_slide_generator` database created
- `.env` file with `DATABASE_URL` configured
- `config/seed_profiles.yaml` exists

**Idempotent:** Safe to run multiple times - skips if profiles already exist.

---

## Seed Profiles

Profiles are defined in `config/seed_profiles.yaml`:

```yaml
profiles:
  - name: "Default"
    description: "Default configuration"
    is_default: true
    genie_space:
      space_id: "your-space-id"
      space_name: "Your Space"
    mlflow:
      experiment_name: "/Users/{username}/ai-slide-generator"
```

A `prompts:` block is no longer read: the per-profile `system_prompt` /
`slide_editing_instructions` overrides are retired and prompts are assembled from
`src/core/prompt_modules.py`.

The `{username}` placeholder is replaced with the current Databricks user.

---

## `publish_pypi.sh`

Build and upload both packages to PyPI or TestPyPI.

```bash
source .venv/bin/activate
./scripts/publish_pypi.sh
```

**TestPyPI:**
```bash
source .venv/bin/activate
./scripts/publish_pypi.sh --test
```

**Credentials (recommended env vars):**
```bash
export TWINE_USERNAME="__token__"
export TWINE_PASSWORD="pypi-<your-token>"
```

**Credentials via `~/.pypirc`:**
```bash
export TWINE_REPOSITORY="pypi"      # or "testpypi"
```

---

## `build_metrics.py`

Measures an agent build from Claude Code transcripts and GitHub PR data (standard library
only; `gh` for GitHub). It reports, per build, the time and cost from the first task
dispatch to handover, and how much of the PR was edited after handover (commits, lines,
share of the PR, and commits marked `Parked-task:`). Costs are list prices, relative only:
use them to compare builds, not to reconcile a bill.

```bash
# Print the build-metrics block to paste into the PR body
uv run python -m scripts.build_metrics record --pr 412 --plan docs/superpowers/plans/x.md

# Build the single-session baseline from [{"pr", "session", "first_task_at"?}, ...]
uv run python -m scripts.build_metrics baseline --input builds.json --out docs/agents/build-metrics-baseline.json

# Print the report: the baseline plus every PR body carrying a block, with a median row per mode
uv run python -m scripts.build_metrics report [--baseline PATH] [--limit 200]
```

The user reads the report and decides; no thresholds, and nothing is reverted automatically.
