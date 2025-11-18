# Databricks App Deployment System

**One-line summary**: Packaging, configuration, and deployment automation for hosting the AI Slide Generator as a Databricks App with environment-specific settings and authentication.

---

## Stack / Entry Points

**Technologies:**
- **Deployment CLI**: `infra/deploy.py` (Python, uses Databricks SDK)
- **Build tools**: `python -m build` (setuptools-scm for wheels), `npm run build` (Vite for frontend)
- **Databricks SDK**: `WorkspaceClient` for Files API and Apps API
- **Configuration**: YAML files (`deployment.yaml`, `app.yaml`)

**Key files:**
- `infra/deploy.py` – Main deployment orchestrator (CLI entry point)
- `infra/config.py` – Parses `deployment.yaml` into dataclasses
- `config/deployment.yaml` – Environment definitions (dev, staging, prod)
- `app.yaml` – Databricks Apps runtime manifest
- `src/config/client.py` – Runtime Databricks authentication (env vars only)

**Environment assumptions:**
- Deployment requires `DATABRICKS_HOST` + `DATABRICKS_TOKEN` or `~/.databrickscfg` profile
- Runtime app automatically receives workspace credentials from Databricks Apps platform
- Python 3.11+, Node.js for frontend builds

---

## Architecture Snapshot

```
┌──────────────────────────────────────────────────────────────┐
│ Local Development Machine                                    │
│                                                               │
│  infra/deploy.py (CLI)                                       │
│    ├─ Build: wheel + frontend bundle                         │
│    ├─ Stage: temp dir with structured layout                 │
│    └─ Upload: Files API → workspace path                     │
│                                                               │
│  Authentication: --profile or env vars (deployment time)     │
└───────────────────────┬──────────────────────────────────────┘
                        │ Files API + Apps API
                        ↓
┌──────────────────────────────────────────────────────────────┐
│ Databricks Workspace                                         │
│                                                               │
│  /Workspace/Users/.../ai-slide-generator/                    │
│    ├─ wheels/ai_slide_generator-*.whl                        │
│    ├─ config/*.yaml                                          │
│    ├─ frontend/dist/                                         │
│    └─ app.yaml (entrypoint)                                  │
│                                                               │
│  Databricks App Runtime                                      │
│    • Runs: sh run_app.sh → pip install wheel → uvicorn      │
│    • Env: DATABRICKS_HOST, DATABRICKS_TOKEN (auto-injected) │
│    • Auth: Service principal (not personal token)            │
└──────────────────────────────────────────────────────────────┘
```

**Critical separation**: Deployment uses optional profiles for multi-workspace management. Runtime uses only environment variables (12-factor app pattern).

---

## Key Concepts / Data Contracts

### DeploymentConfig

```python
@dataclass
class DeploymentConfig:
    app_name: str                      # Unique Databricks App identifier
    description: str                   # Human-readable description
    workspace_path: str                # Where files are uploaded
    permissions: List[Dict[str, str]]  # ACLs (CAN_USE, CAN_MANAGE)
    compute_size: str                  # MEDIUM, LARGE, or LIQUID
    env_vars: Dict[str, str]           # Injected into app container
    exclude_patterns: List[str]        # Build exclusions
    timeout_seconds: int               # Deployment timeout
    poll_interval_seconds: int         # Status polling interval
```

### deployment.yaml Structure

```yaml
environments:
  development:
    app_name: "ai-slide-generator-dev"
    workspace_path: "/Workspace/Users/{username}/apps/dev/..."
    permissions:
      - user_name: "user@example.com"
        permission_level: "CAN_MANAGE"
    compute_size: "MEDIUM"
    env_vars:
      ENVIRONMENT: "development"
      LOG_LEVEL: "DEBUG"

common:
  build:
    exclude_patterns: ["tests", "*.md", "__pycache__"]
  deployment:
    timeout_seconds: 300
```

**No secrets**: `deployment.yaml` is version controlled. Contains paths, permissions, compute settings only.

### Authentication Contracts

| Context | Method | Source |
|---------|--------|--------|
| **Deployment** (infra/deploy.py) | Profile OR env vars | `--profile logfood` or `DATABRICKS_HOST`/`TOKEN` |
| **Runtime** (src/config/client.py) | Env vars only | Platform-injected credentials |

**Why different?** Deployment manages multiple workspaces; runtime follows 12-factor principles.

---

## Component Responsibilities

| Module | Responsibility | Key Functions/Classes |
|--------|---------------|----------------------|
| `infra/deploy.py` | CLI orchestration, build pipeline, upload, app lifecycle | `deploy()`, `build_python_wheel()`, `upload_files_to_workspace()`, `create_app()`, `update_app()` |
| `infra/config.py` | Parse YAML, validate environments | `load_deployment_config()`, `DeploymentConfig` |
| `config/deployment.yaml` | Environment definitions | N/A (data file) |
| `config/deployment.example.yaml` | Template/documentation | N/A (reference) |
| `app.yaml` | Databricks Apps manifest | Defines entrypoint, compute |
| `src/config/client.py` | Runtime auth (env vars) | `get_databricks_client()` |
| `src/config/settings.py` | Merge YAML + env overrides | `get_settings()`, `AppSettings` |

---

## State/Data Flow

### Deployment Flow (Create/Update)

1. **Load config**: Parse `deployment.yaml` for specified environment (dev/staging/prod)
2. **Validate**: Check environment exists, required fields present
3. **Build artifacts**:
   - Python wheel: `python -m build --wheel` → `dist/ai_slide_generator-*.whl`
   - Frontend bundle: `cd frontend && npm run build` → `frontend/dist/`
4. **Stage directory**: Assemble temp dir with structured layout:
   ```
   /tmp/ai-slide-generator-deploy-xxxxx/
   ├── wheels/*.whl
   ├── config/*.yaml (excludes deployment.yaml)
   ├── frontend/dist/
   └── app.yaml
   ```
5. **Upload files**: Use Databricks Files API to copy to workspace path
   - Clean old wheels (keep only latest)
   - Overwrite config files
   - Replace frontend assets
6. **Create/Update app**: Call Apps API with:
   - `name`, `description`, `source_code_path`
   - Compute config (MEDIUM/LARGE/LIQUID)
   - Environment variables from `deployment.yaml`
7. **Set permissions**: Apply ACLs (user/group permissions)
8. **Cleanup**: Remove temp staging directory

### Runtime Startup

1. Databricks Apps runs `sh run_app.sh` (defined in `app.yaml`)
2. Script installs wheel: `pip install wheels/*.whl`
3. Starts FastAPI: `uvicorn src.api.main:app --host 0.0.0.0 --port 8080`
4. `src/config/settings.py` loads config:
   - Read YAML files (`config.yaml`, `mlflow.yaml`, `prompts.yaml`)
   - Merge env var overrides (`LOG_LEVEL`, `ENVIRONMENT`)
5. `src/config/client.py` creates `WorkspaceClient()` using env vars:
   - `DATABRICKS_HOST` and `DATABRICKS_TOKEN` auto-injected by platform
6. Application serves on port 8080 (Databricks Apps standard)

---

## Deployment CLI Interface

### Commands

```bash
# Create new app
python -m infra.deploy --create --env development [--profile <name>]

# Update existing app (code + config changes)
python -m infra.deploy --update --env production [--profile <name>]

# Delete app (workspace files remain)
python -m infra.deploy --delete --env staging [--profile <name>]

# Validate config without deploying
python -m infra.deploy --create --env production --dry-run
```

### Arguments

| Flag | Required | Description |
|------|----------|-------------|
| `--env` | Yes | Environment name (development, staging, production) |
| `--create` | One of | Create new Databricks App |
| `--update` | create/update/delete | Update existing app |
| `--delete` | required | Delete app registration |
| `--profile` | No | Databricks profile from `~/.databrickscfg` |
| `--dry-run` | No | Validate without deploying |

### Authentication Priority

1. `--profile` flag (if provided)
2. Environment variables (`DATABRICKS_HOST`, `DATABRICKS_TOKEN`)
3. Default Databricks SDK auth chain (config file, Azure CLI, etc.)

---

## Operational Notes

### Error Handling

**Common failures:**
- **"App already exists"**: Use `--update` instead of `--create`
- **"Permission denied"**: Deployment identity needs workspace file access
- **"Connection failed"**: Verify `DATABRICKS_HOST` includes `https://`
- **Build failures**: Check `python -m build` and `npm run build` work locally

**Debugging workflow:**
```bash
# 1. Validate config
python -m infra.deploy --create --env dev --dry-run

# 2. Test auth separately
python -c "from databricks.sdk import WorkspaceClient; print(WorkspaceClient().current_user.me())"

# 3. Check app status in Databricks UI
# Navigate to: Apps → [app-name] → Logs
```

### Logging

- Deployment script outputs structured steps (emoji prefixes for scanning)
- Runtime logs go to Databricks Apps logging (view in UI)
- MLflow traces capture agent interactions (see `backend-overview.md`)

### Configuration Overrides

**Deployment-time** (in `deployment.yaml`):
```yaml
env_vars:
  ENVIRONMENT: "production"
  LOG_LEVEL: "INFO"
  CUSTOM_SETTING: "value"
```

**Runtime precedence**:
1. Platform-injected variables
2. `deployment.yaml` → `env_vars`
3. `config.yaml` defaults

### Monitoring

**Health checks:**
```bash
curl https://<app-url>/health
# Expected: {"status": "ok"}

curl https://<app-url>/api/health
# Full health endpoint
```

**App status**: Databricks UI → Apps → `ai-slide-generator-{env}` → Status/Logs

---

## Extension Guidance

### Add a New Environment

1. **Edit `config/deployment.yaml`**:
   ```yaml
   environments:
     qa:
       app_name: "ai-slide-generator-qa"
       workspace_path: "/Workspace/Shared/apps/qa/..."
       permissions:
         - group_name: "qa-team"
           permission_level: "CAN_USE"
       compute_size: "MEDIUM"
       env_vars:
         ENVIRONMENT: "qa"
   ```

2. **Update `infra/deploy.py` choices** (optional enforcement):
   ```python
   parser.add_argument("--env", choices=["development", "staging", "production", "qa"])
   ```

3. **Deploy**:
   ```bash
   python -m infra.deploy --create --env qa --profile qa-workspace
   ```

### Add Pre-Deployment Validation

```python
# infra/deploy.py :: deploy()
def validate_before_deploy(config: DeploymentConfig):
    """Run checks before uploading."""
    # Verify builds succeed
    wheel_path = build_python_wheel(project_root)
    assert wheel_path.exists()
    
    # Test config validity
    from src.config.settings import get_settings
    settings = get_settings()
    
    # Check workspace path accessible
    try:
        workspace_client.workspace.get_status(config.workspace_path)
    except NotFound:
        print("⚠️  Path will be created")
```

### Implement CI/CD

**GitHub Actions example**:
```yaml
name: Deploy to Databricks
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Deploy to staging
        env:
          DATABRICKS_HOST: ${{ secrets.DATABRICKS_HOST_STAGING }}
          DATABRICKS_TOKEN: ${{ secrets.DATABRICKS_TOKEN_STAGING }}
        run: python -m infra.deploy --update --env staging
```

**Best practices:**
- Store credentials as GitHub Secrets
- Use `--update` for idempotent deployments
- Run tests before deploying (`pytest tests/`)
- Add approval gates for production

### Blue-Green Deployment

**Current limitation**: Single app name = single instance.

**Workaround**:
1. Deploy new version with different name: `ai-slide-generator-v2`
2. Test new version
3. Update external routing (if applicable)
4. Delete old version

**Future**: Use Databricks Apps deployment slots or versioned paths.

### Add Environment-Specific Config

**Option 1: Use `env_vars` in deployment.yaml**
```yaml
env_vars:
  FEATURE_FLAG_X: "true"
  EXTERNAL_API: "https://api.example.com"
```

**Option 2: Load different runtime configs**
```python
# src/config/loader.py
env = os.getenv("ENVIRONMENT", "development")
config_path = f"config/config.{env}.yaml"  # config.production.yaml
```

---

## Key Invariants

**Must hold for successful deployments:**
- `deployment.yaml` must exist and be valid YAML
- Specified environment must be defined in `deployment.yaml`
- Workspace path must be accessible to deployment identity
- App name must be unique per workspace
- `app.yaml` must define valid command entrypoint
- Frontend build must succeed (`frontend/dist/index.html` exists)
- Python wheel must build successfully

**Runtime requirements:**
- `DATABRICKS_HOST` and `DATABRICKS_TOKEN` must be set (platform provides)
- Config files (`config.yaml`, `mlflow.yaml`, `prompts.yaml`) must exist in workspace
- Port 8080 must be available (Databricks Apps standard)

---

## Files Reference

| File | Purpose | Edit When |
|------|---------|-----------|
| `infra/deploy.py` | Deployment orchestration | Add validations, new operations |
| `infra/config.py` | Parse deployment.yaml | Add config fields, validation |
| `config/deployment.yaml` | Environment definitions | Add environments, change paths/compute |
| `config/deployment.example.yaml` | Template/docs | Schema changes |
| `app.yaml` | App entrypoint | Change startup command (rare) |
| `src/config/client.py` | Runtime auth | Modify auth strategy (discouraged) |
| `src/config/settings.py` | Settings loader | Add config sections, env overrides |

---

## Integration with Other Systems

### Frontend Build

- **Source**: `frontend/src/` (React + Vite + TypeScript)
- **Build**: `npm run build` → `frontend/dist/`
- **Deployment**: Copied to workspace → served by FastAPI static files
- **See**: `docs/technical/frontend-overview.md` for UI architecture

### Backend Runtime

- **Entry**: `src/api/main.py` (FastAPI app)
- **Config**: Loads from `config/*.yaml` + env vars
- **Auth**: `get_databricks_client()` uses platform credentials
- **See**: `docs/technical/backend-overview.md` for API/agent architecture

### MLflow Integration

- **Config**: `config/mlflow.yaml` defines experiment tracking
- **Runtime**: Agent automatically logs traces to Databricks MLflow
- **Observability**: View traces in workspace MLflow UI
- **See**: `backend-overview.md` → "MLflow traces" section

---

## Comparison: Deployment vs Runtime Auth

| Aspect | Deployment (infra/deploy.py) | Runtime (src/config/client.py) |
|--------|----------------------------|--------------------------------|
| **Method** | Profile OR env vars | Env vars only |
| **Source** | `--profile` or `DATABRICKS_HOST`/`TOKEN` | Platform-injected |
| **Identity** | Personal or service account | App service principal |
| **Use case** | Manage multiple workspaces | Running application |
| **Configured in** | CLI args or local env | `deployment.yaml` → `env_vars` |

**Rationale**: Deployment tooling needs flexibility for multi-workspace management. Runtime follows 12-factor app principles (config via environment).

---

## Troubleshooting Checklist

**Before deploying:**
- [ ] Tests pass (`pytest tests/`)
- [ ] `deployment.yaml` is valid YAML
- [ ] Environment exists in `deployment.yaml`
- [ ] Databricks credentials configured (env vars or profile)
- [ ] Frontend builds locally (`cd frontend && npm run build`)
- [ ] Python wheel builds (`python -m build`)

**After deployment:**
- [ ] App shows "Running" in Databricks UI
- [ ] `/health` endpoint returns 200
- [ ] Logs show FastAPI startup
- [ ] Can send chat message and generate slides
- [ ] MLflow traces appear in experiment

**If deployment fails:**
1. Run `--dry-run` to validate config
2. Test auth: `databricks workspace list /`
3. Check workspace path is accessible
4. Review deployment script output for errors
5. Inspect app logs in Databricks UI

---

## Best Practices

**Configuration:**
- Keep secrets out of YAML (use env vars)
- Version control `deployment.yaml` (no secrets)
- Use `deployment.example.yaml` as documentation
- Override with env vars for runtime customization

**Deployment Strategy:**
- **Dev**: Deploy frequently, single-user, use `--update`
- **Staging**: Deploy on merge to main, team testing
- **Prod**: Manual approval, full test suite, larger compute

**Security:**
- Rotate tokens regularly
- Principle of least privilege in permissions
- Separate workspaces for environments (not just paths)
- Review app access logs

**Monitoring:**
- Set up health check probes (`/health`)
- Monitor app logs for errors
- Track MLflow traces for agent performance
- Alert on app downtime

---

## Cross-References

Related documentation:
- `docs/technical/backend-overview.md` – FastAPI architecture, ChatService, agent lifecycle
- `docs/technical/frontend-overview.md` – React components, API client, state management
- `docs/technical/slide-parser-and-script-management.md` – HTML parsing, script handling
- `DEPLOYMENT_SETUP.md` – Quick-start deployment guide
- `DATABRICKS_APP_DEPLOYMENT_PLAN.md` – Original design (historical)

This document covers deployment mechanics. For runtime behavior (how the app processes requests, generates slides, manages sessions), see the backend and frontend overviews.

---

**Maintenance note**: Update this doc when deployment process changes (new environments, authentication methods, or build steps). Keep synchronized with `deployment.yaml` schema and `infra/deploy.py` implementation.

