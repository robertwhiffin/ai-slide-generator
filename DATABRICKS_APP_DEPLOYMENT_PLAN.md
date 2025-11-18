# Databricks App Deployment Plan

## Overview

Transform the AI Slide Generator into a Databricks App with automated deployment, proper runtime configuration, and user authorization foundations for future multi-session support.

## 1. Project Structure Changes

Create new deployment infrastructure:

```
ai-slide-generator/
├── app.yaml                    # Databricks App configuration (NEW)
├── requirements.txt            # Already exists, may need adjustments
├── config/
│   ├── config.yaml            # Existing app config
│   ├── prompts.yaml           # Existing prompts
│   ├── mlflow.yaml            # Existing MLflow config
│   └── deployment.yaml        # Deployment configuration (NEW)
├── infra/                      # Deployment automation (NEW)
│   ├── __init__.py
│   ├── deploy.py              # Main deployment script
│   └── config.py              # YAML config loader
├── .databricks/               # Databricks workspace settings (NEW)
│   └── bundle.yml             # Asset bundle config (optional)
└── src/
    └── api/
        └── middleware/        # Auth middleware (NEW)
            ├── __init__.py
            └── auth.py
```

## 2. Automated Deployment (`infra/deploy.py`)

### Purpose
Single-command deployment script that packages, uploads, and creates/updates the Databricks App.

### Key Components

**Setup Functions:**
- `setup_deployment_directory()`: Create temporary staging area, copy source files, build frontend assets, exclude unnecessary files (.git, tests, node_modules, .venv)
- `upload_files_to_workspace()`: Upload files directly to Databricks workspace path, maintaining directory structure (e.g., `/Workspace/Users/{username}/apps/ai-slide-generator`)
- `setup_permissions()`: Configure app permissions (CAN_USE, CAN_MANAGE)

**Note:** Databricks Apps expects files to be uploaded directly (not as an archive) so they can be executed immediately.

**Deployment Functions:**
- `deploy_app()`: Main orchestrator that calls WorkspaceClient.apps.create() or update()
- `wait_for_deployment()`: Poll app status until RUNNING or FAILED
- `cleanup_staging()`: Remove temporary files

**CLI Interface:**
- Support `--create`, `--update`, `--delete` flags
- Environment-based config (dev/staging/prod) loaded from `config/deployment.yaml`
- Dry-run mode for validation

**Usage Example:**
```python
# In infra/deploy.py
from infra.config import load_deployment_config
from databricks.sdk import WorkspaceClient

def deploy(env: str, action: str, dry_run: bool = False):
    # Load environment-specific config from YAML
    config = load_deployment_config(env)
    
    # Initialize Databricks client with profile from config
    w = WorkspaceClient(profile=config.databricks_profile)
    
    # Use config values for deployment
    print(f"Deploying {config.app_name} to {config.workspace_path}")
    
    if dry_run:
        print(f"Dry run - would deploy with resources: {config.resources}")
        return
    
    # Actual deployment logic...
```

### Reference Pattern
Based on `initialsetup.py` from sql-migration-assistant, implement:
- Workspace client initialization from local `.databrickscfg` file using profile from YAML config
- Permission assignment using `w.apps.update_permissions()`
- Idempotent operations (create if not exists, update otherwise)

**Authentication with YAML Config:**
```python
from databricks.sdk import WorkspaceClient
from infra.config import load_deployment_config

# Load environment config from YAML
config = load_deployment_config("production")  # or "development", "staging"

# Initialize workspace client with profile from config
w = WorkspaceClient(profile=config.databricks_profile)

# Use config values for deployment
print(f"Deploying {config.app_name} to {config.workspace_path}")
print(f"Using Databricks profile: {config.databricks_profile}")
```

**Key Points:**
- Deployment script runs on your **local machine** with your personal credentials from `~/.databrickscfg`
- Profile to use is specified in `config/deployment.yaml` per environment
- Deployed app itself will use **auto-injected service principal token** (not your personal token)
- Config specifies which workspace to deploy to (via profile)

## 3. App Configuration (`app.yaml`)

### Runtime Configuration

```yaml
# App metadata
name: "ai-slide-generator"
description: "AI-powered slide deck generator using LLMs and Genie"

# Startup command - install wheel and run app
command:
  - "sh"
  - "-c"
  - |
    pip install wheels/*.whl && \
    uvicorn src.api.main:app --host 0.0.0.0 --port 8080

# Environment variables
env:
  - name: ENVIRONMENT
    value: "production"
  - name: DATABRICKS_HOST
    valueFrom: "system.databricks_host"  # Injected by Databricks
  - name: DATABRICKS_TOKEN
    valueFrom: "system.databricks_token"  # App service principal token
  - name: LOG_LEVEL
    value: "INFO"
  - name: MLFLOW_TRACKING_URI
    value: "databricks"

# Note: compute_size is set programmatically during deployment via the Databricks SDK
# Valid values configured in deployment.yaml: MEDIUM, LARGE, LIQUID
```

### Key Decisions

**Single Process Model:** Install wheel package then run uvicorn to serve both API and frontend.

**Port 8080:** Standard Databricks Apps port.

**Compute Size:** Set programmatically via SDK using values from `deployment.yaml`:
- **MEDIUM**: Balanced compute (default for dev/staging)
- **LARGE**: More resources (recommended for production)
- **LIQUID**: Auto-scaling compute

**Service Principal Token:** Databricks injects token automatically via `system.databricks_token` - use this for Genie queries and MLflow.

## 4. Dependencies (`requirements.txt`)

### Adjustments Needed

**Current File:** Already has core dependencies, but needs:
- Pin exact versions for reproducibility (e.g., `fastapi==0.104.1` instead of `>=0.104.0`)
- Remove dev-only packages (pytest, ruff - these shouldn't be in production)
- Verify compatibility with Databricks Apps Python runtime (currently Python 3.10)

**Production requirements.txt:**
```
# Core framework
fastapi==0.104.1
uvicorn[standard]==0.24.0
python-multipart==0.0.6
pydantic==2.4.2
pydantic-settings==2.0.3

# Databricks integration
databricks-sdk==0.20.0
databricks-langchain==0.1.0
mlflow==3.0.0

# LLM framework
langchain==0.3.0
langchain-core==0.3.0
langchain-community==0.3.0

# HTML processing
beautifulsoup4==4.12.0
lxml==4.9.3

# Utilities
httpx==0.25.0
python-dotenv==1.0.0
pyyaml==6.0.0
jinja2==3.1.0
pandas==2.0.3
```

**Note:** Do not include frontend dependencies (npm) - build frontend locally, copy `dist/` to deployment package.

## 5. User Authorization Foundations

### Middleware Implementation (`src/api/middleware/auth.py`)

**Purpose:** Extract user identity from Databricks-injected headers for future multi-session support.

**System Environment Variables (Auto-Injected):**
- `x-forwarded-access-token`: User's OAuth token
- `x-forwarded-user`: User's email/username
- `x-forwarded-email`: User's email
- `x-user-id`: Databricks user ID

**Middleware Responsibilities:**
- Extract user info from headers
- Attach to `request.state.user` for downstream use
- Log user actions with user_id context
- Return 401 if headers missing (shouldn't happen in prod)

**Future Multi-Session Integration:**
When implementing Phase 4, use `request.state.user["user_id"]` to:
- Isolate sessions per user
- Enforce ownership checks on session operations
- Track user activity in logs

### Service Principal Permissions

**App Service Principal:** Databricks automatically creates a service principal for the app. Grant it:
- `EXECUTE` on Genie space (for data queries)
- `USE CATALOG` and `USE SCHEMA` permissions on relevant Unity Catalog resources
- MLflow experiment permissions (if tracking enabled)

**User Permissions:** Grant via `infra/deploy.py`:
- `CAN_USE`: All authorized users
- `CAN_MANAGE`: Admin group only

## 6. Frontend Build Integration

### Build Process

**Pre-Deployment Steps:**
1. `cd frontend && npm install && npm run build`
2. Copy `frontend/dist/` to deployment staging area
3. Update `src/api/main.py` to serve static files in production mode:

```python
# Check if ENVIRONMENT=production
if os.getenv("ENVIRONMENT") == "production":
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse
    
    # Serve static assets
    app.mount("/assets", StaticFiles(directory="frontend/dist/assets"), name="assets")
    
    # Serve index.html for all non-API routes (SPA routing)
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        return FileResponse("frontend/dist/index.html")
```

### Environment Configuration

**Frontend `.env.production`:**
```
VITE_API_URL=/api  # Relative path, same origin
```

**No CORS in Production:** Remove/disable CORS middleware when `ENVIRONMENT=production` since frontend and backend served from same origin.

## 7. Deployment Workflow

### Developer Commands

```bash
# Initial deployment (uses default profile from ~/.databrickscfg)
python -m infra.deploy --create --env production

# Update existing app
python -m infra.deploy --update --env production

# Delete app
python -m infra.deploy --delete --env production

# Use specific Databricks profile
python -m infra.deploy --create --env production --profile my-workspace

# Dry run (validation only)
python -m infra.deploy --create --env production --dry-run
```

### Configuration Benefits

**YAML-Based Configuration:**
- **Consistency:** Matches existing project patterns (`config.yaml`, `prompts.yaml`, `mlflow.yaml`)
- **Easy Editing:** Non-technical users can modify deployment settings
- **Version Control:** Safe to commit (no secrets, just configuration)
- **Environment Isolation:** Clear separation of dev/staging/prod settings
- **Centralized:** All deployment config in one file

**Template Variables:**
- `{username}`: Replaced with current user from Databricks config
- Allows personal dev deployments without hardcoding usernames

### What Happens

1. **Load Configuration:** Read `config/deployment.yaml` for specified environment
2. **Validate Configuration:** Check app.yaml, pyproject.toml, deployment.yaml
3. **Build Python Wheel:** Create distributable `.whl` package using `python -m build`
4. **Build Frontend:** Run `npm run build` in frontend/
5. **Create Staging Area:** Organize wheel, config files, and frontend dist
6. **Upload to Workspace:** Upload files directly to workspace path maintaining directory structure
7. **Create/Update App:** Call `w.apps.create()` or `w.apps.update()` with reference to uploaded files
8. **Wait for Ready:** Poll until status=RUNNING (app installs wheel on startup)
9. **Configure Permissions:** Grant permissions from config (CAN_USE, CAN_MANAGE)
10. **Output URL:** Print app URL (e.g., `https://{workspace}.cloud.databricks.com/apps/{app_name}`)
11. **Cleanup:** Remove staging directory and build artifacts

### Configuration Files

**`config/deployment.yaml`** (NEW):

```yaml
# Deployment configuration for different environments
environments:
  development:
    app_name: "ai-slide-generator-dev"
    workspace_path: "/Workspace/Users/{username}/apps/dev/ai-slide-generator"
    databricks_profile: "DEFAULT"
    permissions:
      - user_name: "{username}"
        permission_level: "CAN_MANAGE"
    resources:
      cpu: "1"
      memory: "2Gi"
    env_vars:
      ENVIRONMENT: "development"
      LOG_LEVEL: "DEBUG"

  staging:
    app_name: "ai-slide-generator-staging"
    workspace_path: "/Workspace/Shared/apps/staging/ai-slide-generator"
    databricks_profile: "staging"
    permissions:
      - group_name: "developers"
        permission_level: "CAN_USE"
      - user_name: "{username}"
        permission_level: "CAN_MANAGE"
    resources:
      cpu: "2"
      memory: "4Gi"
    env_vars:
      ENVIRONMENT: "staging"
      LOG_LEVEL: "INFO"

  production:
    app_name: "ai-slide-generator"
    workspace_path: "/Workspace/Shared/apps/production/ai-slide-generator"
    databricks_profile: "production"
    permissions:
      - group_name: "users"
        permission_level: "CAN_USE"
      - group_name: "admins"
        permission_level: "CAN_MANAGE"
    resources:
      cpu: "4"
      memory: "8Gi"
    env_vars:
      ENVIRONMENT: "production"
      LOG_LEVEL: "INFO"

# Common settings across all environments
common:
  build:
    exclude_patterns:
      - "*.pyc"
      - "__pycache__"
      - ".git"
      - ".venv"
      - "venv"
      - "node_modules"
      - "tests"
      - ".pytest_cache"
      - "*.log"
      - ".env"
      - ".env.*"
  
  deployment:
    timeout_seconds: 300
    poll_interval_seconds: 5
```

**`infra/config.py`** (YAML loader):

```python
"""Load deployment configuration from YAML."""
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
import yaml


@dataclass
class DeploymentConfig:
    """Deployment configuration for a specific environment."""
    app_name: str
    workspace_path: str
    databricks_profile: str
    permissions: List[Dict[str, str]]
    resources: Dict[str, str]
    env_vars: Dict[str, str]
    
    # Common settings
    exclude_patterns: List[str]
    timeout_seconds: int
    poll_interval_seconds: int


def load_deployment_config(env: str) -> DeploymentConfig:
    """
    Load deployment configuration for specified environment.
    
    Args:
        env: Environment name (development, staging, production)
    
    Returns:
        DeploymentConfig for the specified environment
    
    Raises:
        ValueError: If environment not found in config
        FileNotFoundError: If deployment.yaml not found
    """
    config_path = Path(__file__).parent.parent / "config" / "deployment.yaml"
    
    if not config_path.exists():
        raise FileNotFoundError(f"Deployment config not found: {config_path}")
    
    with open(config_path, 'r') as f:
        config_data = yaml.safe_load(f)
    
    if env not in config_data['environments']:
        available = list(config_data['environments'].keys())
        raise ValueError(f"Unknown environment: {env}. Available: {available}")
    
    env_config = config_data['environments'][env]
    common_config = config_data['common']
    
    return DeploymentConfig(
        app_name=env_config['app_name'],
        workspace_path=env_config['workspace_path'],
        databricks_profile=env_config['databricks_profile'],
        permissions=env_config['permissions'],
        resources=env_config['resources'],
        env_vars=env_config['env_vars'],
        exclude_patterns=common_config['build']['exclude_patterns'],
        timeout_seconds=common_config['deployment']['timeout_seconds'],
        poll_interval_seconds=common_config['deployment']['poll_interval_seconds'],
    )
```

## 8. Logging & Observability

### Structured Logging

**Update `src/utils/logging_config.py`:**
- JSON format for all logs (easier to query in Databricks)
- Include `user_id` in all log entries (extracted from middleware)
- Send to stdout (Databricks captures automatically)

**Log Schema:**
```json
{
  "timestamp": "2024-11-17T10:30:00Z",
  "level": "INFO",
  "logger": "src.api.routes.chat",
  "message": "Slide generation completed",
  "user_id": "user@example.com",
  "session_id": "future-feature",
  "request_id": "req-123",
  "latency_ms": 1500
}
```

## 9. Testing Before Deployment

### Prerequisites

**Setup Databricks CLI Configuration:**
```bash
# Configure Databricks CLI (creates ~/.databrickscfg)
databricks configure --token

# Enter your workspace URL and personal access token when prompted
# This will be used by the deployment script

# Verify configuration
databricks workspace list /Users
```

**Alternative: Manual Configuration**
Edit `~/.databrickscfg`:
```ini
[DEFAULT]
host = https://your-workspace.cloud.databricks.com
token = dapi...

[production]
host = https://prod-workspace.cloud.databricks.com
token = dapi...
```

### Local Production Simulation

```bash
# Set production environment variables
export ENVIRONMENT=production
export DATABRICKS_HOST="https://your-workspace.cloud.databricks.com"
export DATABRICKS_TOKEN="dapi..."

# Build frontend
cd frontend && npm run build && cd ..

# Start backend (will serve frontend from dist/)
uvicorn src.api.main:app --host 0.0.0.0 --port 8080

# Test at http://localhost:8080
```

### Validation Checklist
- [ ] Frontend loads from FastAPI (not separate server)
- [ ] API calls work (same-origin, no CORS issues)
- [ ] User info extracted from headers (simulate with curl)
- [ ] Genie queries succeed with service principal token
- [ ] MLflow tracking works
- [ ] Logs in JSON format

## 10. Post-Deployment

### Monitoring
- View logs: Databricks workspace → Apps → ai-slide-generator → Logs
- Track usage: MLflow experiments for query patterns
- Set alerts: App downtime, error rate >5%, slow responses >10s

### Iteration
- For code updates: Run `python -m infra.deploy --update`
- For config changes: Update app.yaml, redeploy
- For dependency changes: Update requirements.txt, redeploy

### Rollback
- Keep previous versions in workspace (`app_v1.tar.gz`, `app_v2.tar.gz`)
- Implement `--rollback` flag in deploy script
- Restore previous archive, call `w.apps.update()`

## Key Differences from Phase 3 Plan

**Simplified Architecture:**
- No separate "middleware" folders - just add auth.py to existing structure
- No complex log routing - Databricks handles via stdout
- No need for separate production build scripts - integrate into deploy.py

**Modern Databricks Apps Features:**
- System environment variables for service principal (no manual token management)
- Built-in log aggregation (no custom log collectors)
- Native resource management (no manual container config)

**Focus Areas:**
- Automated deployment (biggest developer productivity win)
- User auth foundations (enables Phase 4 multi-session)
- Single-origin serving (eliminates CORS complexity)

## Success Criteria

- [ ] Deploy with single command: `python -m infra.deploy --create`
- [ ] App accessible at Databricks-provided URL
- [ ] User identity captured in logs
- [ ] All Phase 1-7 features work in production
- [ ] Zero CORS errors (same-origin)
- [ ] Service principal has correct permissions
- [ ] Update deployments complete in <2 minutes

## Estimated Implementation Time

- **Deployment automation (`infra/`):** 4-6 hours
- **app.yaml configuration:** 1 hour
- **Auth middleware:** 2-3 hours  
- **Frontend build integration:** 2 hours
- **Testing & validation:** 3-4 hours
- **Documentation:** 1-2 hours

**Total:** 13-18 hours

## Implementation Phases

### Phase A: Core Deployment (Priority 1)
- Create `config/deployment.yaml` with environment configurations
- Create `infra/config.py` YAML loader
- Create `app.yaml` for Databricks Apps runtime
- Create `infra/deploy.py` with basic create/update/delete
- Update `requirements.txt` with pinned versions
- Frontend build integration in `src/api/main.py`
- Local production testing

**Initial Setup:**
```bash
# Create example deployment config
cp config/deployment.example.yaml config/deployment.yaml
# Edit with your workspace details, groups, etc.
```

### Phase B: User Authorization (Priority 2)
- Implement `src/api/middleware/auth.py`
- Update logging to include user_id
- Test header extraction
- Document service principal setup

### Phase C: Advanced Features (Priority 3)
- Dry-run mode in deploy script
- Rollback functionality
- Environment-specific configs
- Monitoring dashboards

## Reference Documentation

- [Databricks Apps Overview](https://learn.microsoft.com/en-us/azure/databricks/dev-tools/databricks-apps/)
- [Databricks Apps System Environment](https://learn.microsoft.com/en-us/azure/databricks/dev-tools/databricks-apps/system-env)
- [Databricks Apps Runtime](https://learn.microsoft.com/en-us/azure/databricks/dev-tools/databricks-apps/app-runtime)
- [Databricks Apps Resources](https://learn.microsoft.com/en-us/azure/databricks/dev-tools/databricks-apps/resources)
- [Databricks Apps Genie Integration](https://learn.microsoft.com/en-us/azure/databricks/dev-tools/databricks-apps/genie)
- [Databricks Apps Best Practices](https://learn.microsoft.com/en-us/azure/databricks/dev-tools/databricks-apps/best-practices)
- [Databricks Apps Deployment](https://learn.microsoft.com/en-us/azure/databricks/dev-tools/databricks-apps/deploy)

## Notes

This plan prioritizes automation and simplicity, leveraging Databricks Apps' built-in capabilities rather than building custom infrastructure. The focus is on:

1. **Developer Experience:** Single command deployment with clear feedback
2. **Future-Proofing:** User auth foundations for multi-session support
3. **Production Readiness:** Proper logging, monitoring, and error handling
4. **Maintainability:** Clear separation of deployment logic from application code

**Configuration Management:**
- Create `config/deployment.example.yaml` as a template (commit to git)
- Add `config/deployment.yaml` to `.gitignore` (user-specific)
- Users customize the example with their workspace URLs, groups, and profiles
- Consistent with existing pattern: `config.example.yaml` → `config.yaml`

