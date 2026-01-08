# Databricks App Deployment

CLI tool for deploying the AI Slide Generator to Databricks Apps.

## Usage

Use the `deploy.sh` wrapper script from the project root (activates venv automatically):

```bash
# Create new app
./deploy.sh create --env development --profile <profile>

# Update existing app
./deploy.sh update --env production --profile <profile>

# Delete app
./deploy.sh delete --env staging --profile <profile>

# Update with database reset (drop and recreate tables first)
./deploy.sh update --env development --profile <profile> --reset-db

# Validate without deploying
./deploy.sh create --env production --profile <profile> --dry-run
```

<details>
<summary>Alternative: Direct Python invocation</summary>

If you need to run the Python module directly (requires venv activation):

```bash
source .venv/bin/activate
python -m db_app_deployment.deploy --create --env development --profile <profile>
```

</details>

---

## Arguments

| Flag | Required | Description |
|------|----------|-------------|
| `--env` | Yes | Environment: `development`, `staging`, `production` |
| `--create` | One of | Create new Databricks App |
| `--update` | these | Update existing app |
| `--delete` | three | Delete app |
| `--profile` | Yes | Databricks CLI profile from `~/.databrickscfg` |
| `--reset-db` | No | Drop and recreate database tables before deploying |
| `--dry-run` | No | Validate config without deploying |

> **Warning:** `--reset-db` deletes all data, is blocked in production, and requires typing `RESET` to confirm.

---

## What It Does

1. **Build artifacts**
   - Python wheel (`python -m build --wheel`)
   - Frontend bundle (`npm run build`)

2. **Stage files** in temp directory:
   ```
   staging/
   ├── wheels/*.whl
   ├── config/*.yaml
   ├── frontend/dist/
   ├── requirements.txt
   └── app.yaml
   ```

3. **Upload** to Databricks workspace via Files API

4. **Lakebase setup**
   - Create/get Lakebase instance
   - Create schema and tables
   - Grant permissions

5. **Create/update Databricks App** with compute, env vars, and resources

### Database Reset (`--reset-db`)

For development/staging environments when schema changes require a fresh start.
Combine with `update` to reset the database and deploy new code in one command:

```bash
./deploy.sh update --env development --profile <profile> --reset-db
```

This will:
1. Connect to Lakebase instance
2. Drop all tables in the app schema
3. Recreate tables from current SQLAlchemy models
4. Deploy the updated application code

---

## Configuration

Settings are read from `config/deployment.yaml`:

```yaml
environments:
  development:
    app_name: "ai-slide-generator-dev"
    workspace_path: "/Workspace/Users/{username}/apps/dev/..."
    permissions:
      - user_name: "you@example.com"
        permission_level: "CAN_MANAGE"
    compute_size: "MEDIUM"  # MEDIUM, LARGE, or LIQUID
    env_vars:
      ENVIRONMENT: "development"
      LOG_LEVEL: "DEBUG"
    lakebase:
      database_name: "ai-slide-generator-dev-db"
      schema: "app_data"
      capacity: "CU_1"

common:
  build:
    exclude_patterns: ["tests", "*.md", "__pycache__"]
  deployment:
    timeout_seconds: 300
```

Copy `config/deployment.example.yaml` to `config/deployment.yaml` and customize.

---

## Files

| File | Purpose |
|------|---------|
| `deploy.py` | Main deployment CLI and logic |
| `config.py` | Parse `deployment.yaml` into dataclasses |

---

## Prerequisites

- Databricks CLI authenticated (`databricks auth login`)
- Permission to create Apps and Lakebase instances
- Python build tools: `pip install build`
- Node.js for frontend build

