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
    ai_infra:
      llm_endpoint: "databricks-llama-3-1-70b-instruct"
      llm_temperature: 0.7
      llm_max_tokens: 16000
    genie_space:
      space_id: "your-space-id"
      space_name: "Your Space"
    mlflow:
      experiment_name: "/Users/{username}/ai-slide-generator"
    prompts:
      system_prompt: "..."
      slide_editing_instructions: "..."
      user_prompt_template: "..."
```

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
