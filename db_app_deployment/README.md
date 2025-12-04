# Databricks App Deployment

CLI tool for deploying the AI Slide Generator to Databricks Apps.

## Usage

```bash
# Create new app
python -m db_app_deployment.deploy --create --env development --profile <profile>

# Update existing app
python -m db_app_deployment.deploy --update --env production --profile <profile>

# Delete app
python -m db_app_deployment.deploy --delete --env staging --profile <profile>

# Validate without deploying
python -m db_app_deployment.deploy --create --env production --profile <profile> --dry-run
```

---

## Arguments

| Flag | Required | Description |
|------|----------|-------------|
| `--env` | Yes | Environment: `development`, `staging`, `production` |
| `--create` | One of | Create new Databricks App |
| `--update` | these | Update existing app |
| `--delete` | three | Delete app |
| `--profile` | Yes | Databricks CLI profile from `~/.databrickscfg` |
| `--dry-run` | No | Validate config without deploying |

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

