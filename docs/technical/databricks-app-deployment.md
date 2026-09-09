# Databricks App Deployment System

**One-line summary**: Two-package pip distribution enabling one-command deployment of Tellr to Databricks Apps with bundled frontend and runtime dependencies.

> **Deploying a dev/test build?** See [dev-deploy.md](dev-deploy.md) for the dev
> loop (publish a `.devN` to real PyPI, then `deploy_local --from-pypi`).

---

## Stack / Entry Points

**Technologies:**
- **Deployment Package**: `databricks-tellr` (PyPI) — deployment orchestration from notebooks
- **Application Package**: `databricks-tellr-app` (PyPI) — bundled runtime with backend + frontend
- **Build Tools**: `python -m build`, `npm run build` (Vite), custom `setup.py` for asset bundling
- **Databricks SDK**: `WorkspaceClient` for Apps API, Files API, Database API
- **Runtime**: FastAPI + uvicorn serving React SPA

**Key files:**
- `packages/databricks-tellr/` — Deployment CLI package
- `packages/databricks-tellr-app/` — Application runtime package
- `scripts/publish_pypi.sh` — Build and publish both packages
- `src/api/main.py` — FastAPI app with frontend serving

**Environment assumptions:**
- Deployment: Databricks notebook with `%pip install databricks-tellr`
- Runtime: Databricks Apps platform with auto-injected credentials
- Python 3.10+, Node.js for frontend builds (development only)

---

## Architecture Snapshot

```
┌──────────────────────────────────────────────────────────────┐
│ Databricks Notebook                                          │
│                                                               │
│  %pip install databricks-tellr databricks-sdk==0.96.0        │
│                                                               │
│  tellr.create(                                                │
│      lakebase_name="tellr-db",       # all params optional   │
│      schema_name="app_data",         # can also use          │
│      app_name="tellr",               # config_yaml_path      │
│      app_file_workspace_path="/Workspace/.../tellr"          │
│  )                                                            │
│                                                               │
│  Generates:                                                   │
│    ├─ requirements.txt  → "databricks-tellr-app==0.1.21"     │
│    └─ app.yaml          → startup command + env vars          │
└───────────────────────┬──────────────────────────────────────┘
                        │ Files API + Apps API
                        ↓
┌──────────────────────────────────────────────────────────────┐
│ Databricks Apps Runtime                                       │
│                                                               │
│  1. pip install -r requirements.txt                           │
│     └─ Installs databricks-tellr-app from PyPI               │
│        ├─ src/         (backend)                              │
│        └─ _assets/     (frontend bundle)                      │
│                                                               │
│  2. python -c "from databricks_tellr_app.run import          │
│                 init_database; init_database(                 │
│                 seed_databricks_defaults=True)"               │
│     └─ Creates tables + seeds defaults                        │
│                                                               │
│  3. python -m databricks_tellr_app.run                        │
│     └─ Starts uvicorn on port 8000                           │
│        ├─ API routes: /api/*                                  │
│        └─ Frontend SPA: / (from bundled assets)               │
└──────────────────────────────────────────────────────────────┘
```

---

## Two-Package Structure

The distribution splits into two complementary PyPI packages:

### 1. databricks-tellr (Deployment Package)

**Purpose:** Lightweight CLI for deploying Tellr from notebooks.

**Location:** `packages/databricks-tellr/`

**Contents:**

| File/Directory | Description |
|----------------|-------------|
| `databricks_tellr/__init__.py` | Exports `create`, `update`, `delete` functions |
| `databricks_tellr/deploy.py` | Deployment orchestration (Lakebase, file upload, app creation) |
| `databricks_tellr/_templates/app.yaml.template` | App manifest template |
| `databricks_tellr/_templates/requirements.txt.template` | Requirements template |

**Dependencies (minimal):**
```toml
dependencies = [
    "databricks-sdk>=0.20.0",
    "psycopg2-binary>=2.9.0",
    "pyyaml>=6.0.0",
]
```

**PyPI:** `pip install databricks-tellr`

### 2. databricks-tellr-app (Application Package)

**Purpose:** Complete runtime — backend code + bundled frontend + all dependencies.

**Location:** `packages/databricks-tellr-app/`

**Contents at Build Time:**

| Component | Source | Destination in Package |
|-----------|--------|------------------------|
| Backend | `src/` | `src/` (Python modules) |
| Frontend | `frontend/dist/` | `databricks_tellr_app/_assets/frontend/` |
| Entrypoint | `databricks_tellr_app/run.py` | Runtime startup script |

**Dependencies (full runtime):**
- FastAPI, uvicorn, pydantic
- LangChain, databricks-langchain, litellm
- SQLAlchemy, psycopg2-binary
- BeautifulSoup, lxml (HTML processing)
- MLflow, OpenTelemetry
- python-pptx, Playwright (export)
- Full list in `packages/databricks-tellr-app/pyproject.toml`

**PyPI:** Installed automatically via generated `requirements.txt`

---

## Build Process (scripts/publish_pypi.sh)

The publish script builds and uploads both packages to PyPI:

```bash
./scripts/publish_pypi.sh          # Upload to PyPI
./scripts/publish_pypi.sh --test   # Upload to TestPyPI
```

### Build Steps

1. **Build databricks-tellr** (simple):
   ```bash
   python -m build --sdist --wheel packages/databricks-tellr/
   ```
   - Packages `deploy.py` and templates
   - No special processing required

2. **Build databricks-tellr-app** (custom):
   ```bash
   # Copy src/ before build (find_packages needs it)
   cp -r src/ packages/databricks-tellr-app/src/
   
   python -m build --sdist --wheel packages/databricks-tellr-app/
   
   # Cleanup after build
   rm -rf packages/databricks-tellr-app/src/
   ```

3. **Custom setup.py (BuildWithFrontend)**:

   The `packages/databricks-tellr-app/setup.py` extends `build_py`:

   ```python
   class BuildWithFrontend(build_py):
       def run(self):
           # 1. Build frontend (npm install && npm run build)
           subprocess.run(["npm", "install"], cwd=frontend_dir)
           subprocess.run(["npm", "run", "build"], cwd=frontend_dir)
           
           # 2. Copy dist/ to package _assets/frontend/
           shutil.copytree(frontend_dir / "dist", assets_root / "frontend")
           
           # 3. Copy src/ to package (backend code)
           shutil.copytree(repo_root / "src", package_root / "src")
           
           # 4. Run standard build
           super().run()
           
           # 5. Cleanup copied directories
   ```

4. **Upload both packages**:
   ```bash
   python -m twine upload packages/databricks-tellr/dist/* \
                          packages/databricks-tellr-app/dist/*
   ```

---

## Frontend Serving in Production

When deployed, FastAPI serves the bundled frontend as static files.

### Resolution Path

```python
# src/api/main.py

def _resolve_frontend_dist():
    """Resolve frontend assets bundled in the app package."""
    # Uses importlib.resources to access package data
    assets_root = resources.files("databricks_tellr_app") / "_assets" / "frontend"
    
    if assets_root.is_dir():
        return resources.as_file(assets_root)  # Returns filesystem path
    return None
```

### Mounting Strategy

```python
def _mount_frontend(app: FastAPI, frontend_dist: Path):
    # Static assets (JS, CSS, images)
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"))
    
    # Favicon
    @app.get("/favicon.svg")
    async def serve_favicon():
        return FileResponse(frontend_dist / "favicon.svg")
    
    # SPA catch-all (all non-API routes serve index.html)
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404)
        return FileResponse(frontend_dist / "index.html")
```

### Development vs Production

| Aspect | Development | Production |
|--------|-------------|------------|
| Frontend | Vite dev server (port 5173) | Bundled in pip package |
| CORS | Enabled (localhost origins) | Disabled |
| Serving | Separate processes | Single FastAPI process |

---

## Deployment Flow

### tellr.create()

Creates all infrastructure and deploys the app:

1. **Lakebase Setup**
   - Get or create Lakebase database instance (autoscaling preferred, provisioned fallback)
   - Wait for instance to be running

2. **Generate Deployment Files**
   ```
   staging_dir/
   ├── requirements.txt  → "databricks-tellr-app==0.1.21"
   └── app.yaml          → startup command + env vars
   ```

3. **Upload to Workspace**
   - Create workspace directory
   - Upload requirements.txt and app.yaml

4. **Create Databricks App**
   - Register app with Apps API
   - Attach database resource with CAN_CONNECT_AND_CREATE permission
   - Configure user API scopes (sql, genie, catalog tables/schemas/catalogs, serving-endpoints)

5. **Setup Database Schema**
   - Create PostgreSQL schema
   - Grant permissions to app service principal

6. **Deploy App**
   - Trigger deployment
   - Wait for app to be running

### Generated app.yaml

```yaml
name: "tellr"
description: "Tellr - AI Slide Generator"

command:
  - "sh"
  - "-c"
  - |
    pip install --upgrade --no-cache-dir -r requirements.txt && \
    python -c "from databricks_tellr_app.run import init_database; init_database()" && \
    python -m databricks_tellr_app.run

env:
  - name: ENVIRONMENT
    value: "production"
  - name: LAKEBASE_INSTANCE
    value: "tellr-db"
  - name: LAKEBASE_SCHEMA
    value: "app_data"
  # Lakebase-backed (default): no encryption-key entry — the key lives in
  # the encryption_keys table. Secret-backed (opt-in): a valueFrom entry
  # injects the Databricks secret; no key material appears here.
  # - name: TELLR_ENCRYPTION_KEY
  #   valueFrom: "TELLR_ENCRYPTION_KEY"   # present only in secret-backed mode
  - name: LAKEBASE_TYPE
    value: "provisioned"       # or "autoscaling"
  - name: LAKEBASE_PG_HOST
    value: ""                  # set for autoscaling instances
  - name: LAKEBASE_PROJECT_ID
    value: ""                  # set for autoscaling instances
  - name: LAKEBASE_ENDPOINT_NAME
    value: ""                  # set for autoscaling instances
  - name: DATABRICKS_HOST
    valueFrom: "system.databricks_host"
  # No DATABRICKS_TOKEN — SP auth is platform OAuth M2M (SDR-4437 F-CR-18)
```

The `init_database()` call in the command accepts an optional `seed_databricks_defaults=True`
argument to seed Databricks-specific content (deck prompts, slide styles). When deployed via
`tellr.create()`, this defaults to `False`; the internal `_create_databricks()` function
controls the flag.

### Generated requirements.txt

```
# Generated by databricks-tellr
databricks-tellr-app==0.1.21
```

---

## Key Concepts / Data Contracts

### Deployment Function Signatures

```python
def create(
    lakebase_name: str | None = None,     # Lakebase instance name
    schema_name: str | None = None,       # PostgreSQL schema
    app_name: str | None = None,          # Databricks App name
    app_file_workspace_path: str | None = None,  # Where to upload files
    lakebase_compute: str = "CU_1",       # CU_1, CU_2, CU_4, CU_8
    app_compute: str = "MEDIUM",          # MEDIUM, LARGE, LIQUID
    app_version: Optional[str] = None,    # Pin specific version
    description: str = "Tellr AI Slide Generator",
    client: WorkspaceClient | None = None,
    profile: str | None = None,
    config_yaml_path: str | None = None,  # Load config from YAML (mutually exclusive with other args)
    encryption_key: str | None = None,    # Fernet key for Google OAuth; auto-generated if omitted
    encryption_secret_scope: str | None = None,  # Secret scope for secret-backed key (opt-in)
    encryption_secret_key: str = "tellr-encryption-key",  # Secret key name within the scope
) -> dict[str, Any]

def update(
    app_name: str,
    app_file_workspace_path: str,
    lakebase_name: str,
    schema_name: str,
    app_version: Optional[str] = None,
    reset_database: bool = False,         # Drop and recreate schema
    client: WorkspaceClient | None = None,
    profile: str | None = None,
    encryption_key: str | None = None,    # Fernet key; reads existing key from app.yaml if omitted
    encryption_secret_scope: str | None = None,  # Secret scope for secret-backed key (opt-in)
    encryption_secret_key: str = "tellr-encryption-key",  # Secret key name within the scope
) -> dict[str, Any]

def delete(
    app_name: str,
    lakebase_name: str | None = None,
    schema_name: str | None = None,
    reset_database: bool = False,
    client: WorkspaceClient | None = None,
    profile: str | None = None,
) -> dict[str, Any]
```

### Return Values

```python
# create() returns:
{
    "url": "https://workspace.cloud.databricks.com/apps/tellr",
    "app_name": "tellr",
    "lakebase_name": "tellr-db",
    "schema_name": "app_data",
    "status": "created"
}

# update() returns:
{
    "url": "...",
    "app_name": "tellr",
    "deployment_id": "d-abc123",
    "status": "updated",
    "database_reset": False
}

# delete() returns:
{
    "app_name": "tellr",
    "status": "deleted",
    "database_reset": True
}
```

---

## Component Responsibilities

| Module | Responsibility |
|--------|---------------|
| `databricks_tellr.deploy` | Orchestrates Lakebase, file upload, app lifecycle |
| `databricks_tellr._templates/` | app.yaml and requirements.txt templates |
| `databricks_tellr_app.run` | `init_database()` and `main()` entrypoints |
| `src/api/main.py` | FastAPI app, frontend mounting, middleware |
| `src/core/database.py` | SQLAlchemy engine, Lakebase token refresh |
| `src/core/init_default_profile.py` | Seeds default profiles, prompts, styles |

---

## State/Data Flow

### App Startup Sequence

1. **Databricks Apps runs command** from app.yaml
2. **pip install** fetches `databricks-tellr-app` from PyPI
3. **init_database(seed_databricks_defaults)** runs:
   - Creates SQLAlchemy tables (if not exist)
   - Seeds default profile, deck prompts, slide styles
   - When `seed_databricks_defaults=True`, also seeds Databricks-specific content
4. **uvicorn starts** FastAPI on port 8000
5. **Lifespan startup**:
   - Starts Lakebase token refresh (if applicable)
   - Mounts frontend assets (production mode)
   - Starts chat job queue worker
   - Starts export job queue worker
6. **App serves requests**:
   - API routes under `/api/*`
   - Frontend SPA at all other routes

### Request Flow

```
User Browser
    │
    ├─ GET /             → index.html (React SPA)
    ├─ GET /assets/*     → Static JS/CSS/images
    ├─ POST /api/chat    → Chat processing (agent)
    ├─ GET /api/sessions → Session management
    └─ GET /api/health   → Health check
```

---

## Operational Notes

### Version Pinning

By default, `tellr.create()` resolves the installed version of `databricks-tellr-app`:

```python
# If databricks-tellr-app is installed alongside databricks-tellr
version = metadata.version("databricks-tellr-app")  # e.g., "0.1.21"
# requirements.txt: databricks-tellr-app==0.1.21
```

To pin a specific version:
```python
tellr.create(..., app_version="0.1.20")
```

To use latest from PyPI:
```python
# Don't install databricks-tellr-app locally
# requirements.txt will just be: databricks-tellr-app
```

### Database Reset

To reset all app data (drop and recreate schema):

```python
tellr.update(
    app_name="tellr",
    app_file_workspace_path="/Workspace/.../tellr",
    lakebase_name="tellr-db",
    schema_name="app_data",
    reset_database=True  # Drops schema, tables recreated on startup
)
```

### Config YAML Deployment

Instead of passing individual arguments, provide a YAML config file:

```python
tellr.create(config_yaml_path="/Workspace/.../deploy_config.yaml")
```

The YAML file can specify `lakebase_name`, `schema_name`, `app_name`,
`app_file_workspace_path`, `lakebase_compute`, and `app_compute`. This is mutually
exclusive with passing those arguments directly — a `ValueError` is raised if both
are provided.

### Google OAuth Encryption

The Fernet master key for encrypting Google OAuth credentials lives in one of two
places, selected at deploy time:

**Lakebase-backed (default):** The key lives in the single-row `encryption_keys`
table of the app's Lakebase data schema. The `encryption_key` parameter on
`create()` / `update()` controls it:
- **create()**: auto-generates a key if not provided; seeds it into the table.
- **update()**: reads the existing key from the table (or from a legacy `app.yaml`
  env var on pre-migration installs) if not provided, preserving encrypted data
  across redeployments.

No encryption-related entry appears in `app.yaml` on this path — the key never
leaves the database.

**Secret-backed (opt-in):** Pass `encryption_secret_scope` (and optionally
`encryption_secret_key`, default `"tellr-encryption-key"`) to `create()` or
`update()`. The deploy tool:
1. Creates the scope if absent (creator becomes sole MANAGE holder — see risks below).
2. Writes (or reuses) the Fernet key in the secret.
3. Attaches a `TELLR_ENCRYPTION_KEY` app resource pointing at the secret.
4. Adds a `valueFrom` entry to `app.yaml` that injects the secret as
   `TELLR_ENCRYPTION_KEY` — the key reference appears in `app.yaml` but no key
   material does.
5. After a successful deploy, polls `/api/health` for `encryption_key_source ==
   "secret"`, then deletes the `encryption_keys` row (if any) — only after the
   live app confirms it is reading the secret.

The `encryption_keys` table stays empty on secret-backed installs; the app reads
the injected env var instead.

### Secret-backed encryption key

**What it does.** When `encryption_secret_scope` is passed, the Fernet key is stored
in a Databricks secret instead of the `encryption_keys` Lakebase table. The secret is
injected into the app container as the `TELLR_ENCRYPTION_KEY` environment variable via
a `valueFrom` entry in `app.yaml`. The app's boot path reads this variable first; if
absent it falls through to the Lakebase path.

**Scope creation.** If the named scope does not exist the deploy tool creates it with
`initial_manage_principal` omitted, making the scope creator the sole MANAGE holder.
Only the creator (or anyone they grant MANAGE) can run subsequent `update()` calls or
rotate the key. To allow a team or CI pipeline to deploy, pre-create the scope and
grant MANAGE to the relevant principal before running `create()` / `update()`.

**`valueFrom` in app.yaml.** A `valueFrom` entry referencing the resource key appears
in `app.yaml`; no key material does. The entry is added only in secret mode; legacy
deployments carry no encryption-related entry.

**Relocate flow.** On an existing Lakebase-backed app, `update(encryption_secret_scope=...)`
runs the following in order:
1. Resolves or generates the Fernet key and writes it to the secret.
2. Attaches the `TELLR_ENCRYPTION_KEY` resource to the app.
3. Deploys the new `app.yaml`.
4. Polls `/api/health` until `encryption_key_source == "secret"`.
5. Only then: `DELETE FROM <schema>.encryption_keys WHERE id = 1`.

The DELETE runs only after the live app confirms it is reading the secret — if
the poll times out, returns a non-200, or the field is absent (old app code), the
row is left intact and a warning is printed.

**Fork inheritance.** A devloop fork (`--env devloop --instance <id>`) of a
secret-backed app detects the source app's resources automatically and inherits
the same scope and key. No `--encryption-secret-scope` flag is needed on the
fork command. A fork does not run the DELETE (fresh branch, no pre-existing row).

**Accepted risks (documented as accepted; not mitigated):**

1. *The injected key is visible on the app's Environment page.* Anyone with MANAGE
   on the app can read the key value from the Databricks UI, and any subprocess that
   inherits the full container environment sees it. The converter jail
   (`src/services/converter_jail/jail.py`) scrubs the environment for its child, but
   the huashu bootstrap inherits everything. Accepted: the key is out of Lakebase and
   out of `app.yaml`, which is what was asked for.

2. *Detaching the resource silently reverts to Lakebase, orphaning ciphertext.* If
   the `TELLR_ENCRYPTION_KEY` resource is removed from the app after the relocate,
   the app falls through to `_from_lakebase()`, finds the empty post-relocate table,
   and mints a fresh key — making every stored Google credential undecryptable.
   Detaching requires MANAGE on the app; no mechanism short of that prevents it.
   Accepted: if someone removes the resource, existing ciphertext becomes
   unrecoverable without a key backup.

### Autoscaling Lakebase

Deployment automatically selects the best Lakebase backend:

1. **Detection**: checks for an existing provisioned instance first, then autoscaling
2. **Creation**: tries autoscaling (preferred) first; falls back to provisioned if the
   workspace does not support it or the SDK classes are unavailable
3. **Env vars**: the generated `app.yaml` includes `LAKEBASE_TYPE`, `LAKEBASE_PG_HOST`,
   `LAKEBASE_PROJECT_ID`, and `LAKEBASE_ENDPOINT_NAME` so the runtime can connect to
   either backend transparently

Autoscaling requires `databricks-sdk>=0.96.0` with `databricks.sdk.service.postgres`
support (`Project`, `ProjectSpec`, `ProjectDefaultEndpointSettings`).

### Error Handling

Common deployment errors:

| Error | Cause | Resolution |
|-------|-------|------------|
| `DeploymentError: Lakebase not found` | Instance doesn't exist | Will be auto-created |
| `App already exists` | Name collision | Use `update()` or different name |
| `Permission denied` | Insufficient workspace access | Check notebook permissions |
| `psycopg2 import error` | Missing dependency | Included in databricks-tellr deps |

### Logging

- Deployment: Structured output with step-by-step progress
- Runtime: Standard Python logging to Databricks Apps logs
- MLflow: Agent traces logged to workspace experiment

---

## Extension Guidance

### Add New Environment Variables

1. Edit `_templates/app.yaml.template`:
   ```yaml
   env:
     - name: MY_NEW_VAR
       value: "${MY_NEW_VAR}"
   ```

2. Resolve the value in `_write_app_yaml()` / deployment config (or add a key to `mlflow_tracing` / `TELLR_DEPLOY_*` pattern in `deploy.py` if it is another deploy-time secret)

3. Republish packages

### Test with Local Wheel

For development testing before publishing:

```python
# In deploy.py, _write_requirements supports local wheel path
_write_requirements(
    staging_dir,
    app_version=None,
    local_wheel_path="./wheels/databricks_tellr_app-0.1.21-py3-none-any.whl"
)
```

### Add New API Scopes

Edit `_create_app()` in deploy.py:
```python
app = App(
    ...,
    user_api_scopes=[
        "sql",
        "dashboards.genie",
        "catalog.tables:read",
        "catalog.schemas:read",
        "catalog.catalogs:read",
        "serving.serving-endpoints",
        "my.new.scope",  # Add new scope
    ],
)
```

---

## Key Invariants

**Package build requirements:**
- Frontend must build successfully (`npm run build` produces `frontend/dist/index.html`)
- `src/` must be a valid Python package
- Version numbers must match between packages (coordinated in pyproject.toml files)

**Deployment requirements:**
- Notebook must have workspace write access to `app_file_workspace_path`
- User must have permission to create Apps and Lakebase instances
- `databricks-sdk>=0.96.0` for Apps and Lakebase Autoscaling API compatibility

**Runtime requirements:**
- Databricks Apps platform provides `DATABRICKS_HOST` (via `app.yaml`) plus the
  `DATABRICKS_CLIENT_ID` / `DATABRICKS_CLIENT_SECRET` pair it injects itself; the SP
  authenticates with OAuth M2M and needs no token env var (SDR-4437 F-CR-18)
- Lakebase instance must be running (auto-provisioned credentials via database resource)
- Port 8000 available (Databricks Apps standard)

---

## Files Reference

| File | Purpose | Edit When |
|------|---------|-----------|
| `packages/databricks-tellr/pyproject.toml` | Deployment package metadata | Bump version, add dependencies |
| `packages/databricks-tellr/databricks_tellr/deploy.py` | Deployment orchestration | Add features, fix bugs |
| `packages/databricks-tellr/databricks_tellr/_templates/*` | app.yaml/requirements templates | Change startup behavior |
| `packages/databricks-tellr-app/pyproject.toml` | App package metadata | Bump version, add runtime deps |
| `packages/databricks-tellr-app/setup.py` | Custom build with frontend | Change asset bundling |
| `packages/databricks-tellr-app/databricks_tellr_app/run.py` | Runtime entrypoints | Change startup sequence |
| `scripts/publish_pypi.sh` | Build and publish script | Change build process |

---

## Cross-References

Related documentation:
- `docs/technical/backend-overview.md` – FastAPI architecture, ChatService, agent lifecycle
- `docs/technical/frontend-overview.md` – React components, API client, state management
- `docs/technical/database-configuration.md` – Lakebase schema, SQLAlchemy models
- `docs/technical/real-time-streaming.md` – SSE vs polling modes

For user-facing deployment instructions, see the main `README.md`.

---

**Maintenance note**: Update this doc when:
- Package versions are bumped
- New environment variables are added
- Build process changes
- Deployment API signatures change

Keep package versions synchronized between `databricks-tellr` and `databricks-tellr-app`.
