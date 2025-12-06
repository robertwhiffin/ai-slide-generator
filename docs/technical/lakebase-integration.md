# Lakebase Integration – PostgreSQL-Compatible OLTP Database for Databricks Apps

This document describes how the AI Slide Generator integrates with Databricks Lakebase for persistent data storage when deployed to Databricks Apps.

---

## Stack / Entry Points

| Component | Path | Purpose |
|-----------|------|---------|
| Lakebase Module | `src/core/lakebase.py` | Instance management, credentials, schema setup |
| Database Module | `src/core/database.py` | SQLAlchemy engine, session management, auto-detection |
| Deployment Config | `db_app_deployment/config.py` | `LakebaseConfig` dataclass |
| Deployment Script | `db_app_deployment/deploy.py` | Orchestrates instance + app + schema creation |
| App Config | `app.yaml` | Runtime environment variables |
| Environment Config | `config/deployment.yaml` | Per-environment Lakebase settings |

**Key Dependencies:**
- `databricks-sdk` – Instance management and credential generation
- `psycopg2-binary` – PostgreSQL connections
- `sqlalchemy` – ORM and connection pooling

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Databricks Apps Runtime                      │
│  ┌─────────────────┐    ┌─────────────────┐                     │
│  │   FastAPI App   │───▶│  database.py    │                     │
│  │  (src/api/*)    │    │  (SQLAlchemy)   │                     │
│  └─────────────────┘    └────────┬────────┘                     │
│                                  │                               │
│         Auto-injected:           │  Builds connection URL        │
│         PGHOST, PGUSER           │  using OAuth token            │
│                                  ▼                               │
│                         ┌─────────────────┐                     │
│                         │  Lakebase OLTP  │                     │
│                         │   Instance      │                     │
│                         │ (PostgreSQL)    │                     │
│                         └─────────────────┘                     │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                     Deployment Time                              │
│  ┌─────────────────┐    ┌─────────────────┐                     │
│  │   deploy.py     │───▶│  lakebase.py    │                     │
│  │   (CLI)         │    │  (SDK calls)    │                     │
│  └─────────────────┘    └────────┬────────┘                     │
│                                  │                               │
│         1. Create instance       │                               │
│         2. Create app            │                               │
│         3. Setup schema          │                               │
│         4. Grant permissions     │                               │
│         5. Initialize tables     ▼                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key Concepts

### Lakebase Hierarchy

```
Lakebase Instance (e.g., "ai-slide-generator-dev-db")
  └── Database: "databricks_postgres" (default, always exists)
        └── Schema: "app_data" (created by deployment)
              └── Tables: user_sessions, config_profiles, etc.
```

- **Instance**: The OLTP server (capacity units: CU_1, CU_2, CU_4, CU_8)
- **Database**: Always `databricks_postgres` (Lakebase default)
- **Schema**: Application namespace (default: `app_data`)

### Authentication Flow

When a database resource is attached to a Databricks App:
1. Databricks auto-injects `PGHOST` and `PGUSER` environment variables
2. A Postgres role is created for the app's service principal
3. The app generates short-lived OAuth tokens via `generate_database_credential()`

```python
# Token generation (database.py)
cred = ws.database.generate_database_credential(
    request_id=str(uuid.uuid4()),
    instance_names=[instance_name],
)
password = cred.token  # Use as PostgreSQL password
```

---

## Component Responsibilities

| Module | Responsibility | SDK/API Used |
|--------|---------------|--------------|
| `get_or_create_lakebase_instance()` | Create/get OLTP instance | `ws.database.create_database_instance_and_wait()` |
| `generate_lakebase_credential()` | Generate OAuth token | `ws.database.generate_database_credential()` |
| `get_lakebase_connection_info()` | Build connection params | `ws.database.get_database_instance()` |
| `get_lakebase_connection_url()` | Build SQLAlchemy URL | Combines above functions |
| `setup_lakebase_schema()` | Create schema + grant perms | Direct SQL via psycopg2 |
| `initialize_lakebase_tables()` | Create SQLAlchemy tables | `Base.metadata.create_all()` |
| `_get_database_url()` (database.py) | Auto-detect environment | Checks `PGHOST` env var |

---

## Deployment Flow

When deploying with `python -m db_app_deployment.deploy --create --env development`:

```
1. Load config from deployment.yaml
   └── LakebaseConfig(database_name, schema, capacity)

2. Create Lakebase instance (if not exists)
   └── get_or_create_lakebase_instance()
   └── Returns: instance name, DNS hostname, state

3. Build and stage artifacts
   └── Inject LAKEBASE_INSTANCE into app.yaml

4. Upload to Databricks workspace

5. Create app with database resource
   └── AppResourceDatabase(
         instance_name="ai-slide-generator-dev-db",
         database_name="databricks_postgres",
         permission=CAN_CONNECT_AND_CREATE
       )

6. Deploy source code
   └── apps.deploy_and_wait()

7. Setup schema and permissions
   └── setup_lakebase_schema(instance, schema, client_id)
   └── SQL: CREATE SCHEMA, GRANT permissions

8. Initialize tables
   └── initialize_lakebase_tables()
   └── SQLAlchemy: Base.metadata.create_all()
```

---

## Runtime Connection Detection

`database.py` auto-detects the environment:

```python
def _get_database_url() -> str:
    # Priority 1: Explicit DATABASE_URL
    if os.getenv("DATABASE_URL"):
        return os.getenv("DATABASE_URL")
    
    # Priority 2: Lakebase (PGHOST auto-set by Databricks)
    if os.getenv("PGHOST") and os.getenv("PGUSER"):
        token = _get_lakebase_token()
        return f"postgresql://{user}:{token}@{host}:5432/databricks_postgres"
    
    # Priority 3: Local development
    return "postgresql://localhost/ai_slide_generator"
```

---

## Configuration

### deployment.yaml

```yaml
environments:
  development:
    lakebase:
      database_name: "ai-slide-generator-dev-db"  # Instance name
      schema: "app_data"                          # PostgreSQL schema
      capacity: "CU_1"                            # CU_1, CU_2, CU_4, CU_8
```

### Environment Variables (Runtime)

| Variable | Source | Description |
|----------|--------|-------------|
| `PGHOST` | Auto-injected | Lakebase DNS hostname |
| `PGUSER` | Auto-injected | Service principal as Postgres role |
| `LAKEBASE_INSTANCE` | Injected by deploy.py | Instance name for credential generation |
| `LAKEBASE_SCHEMA` | app.yaml | Schema name (default: `app_data`) |

---

## Permissions Granted

The deployment grants these permissions to the app's service principal:

```sql
-- Schema access
GRANT USAGE ON SCHEMA "app_data" TO "<client_id>";
GRANT CREATE ON SCHEMA "app_data" TO "<client_id>";

-- Table access (existing)
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "app_data" TO "<client_id>";

-- Sequence access (for auto-increment)
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA "app_data" TO "<client_id>";

-- Default privileges (future objects)
ALTER DEFAULT PRIVILEGES IN SCHEMA "app_data" 
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "<client_id>";
ALTER DEFAULT PRIVILEGES IN SCHEMA "app_data" 
  GRANT USAGE, SELECT ON SEQUENCES TO "<client_id>";
```

---

## Error Handling

| Error | Cause | Resolution |
|-------|-------|------------|
| `connection to localhost refused` | `PGHOST` not set | Ensure database resource attached to app |
| `Failed to decode token for role` | Missing `LAKEBASE_INSTANCE` | Check app.yaml has instance injected |
| `permission denied for sequence` | Missing sequence grants | Redeploy to apply sequence permissions |
| `schema does not exist` | Schema not created | Run deployment with `--create` |

---

## Local Development

For local development without Lakebase:

```bash
# Use local PostgreSQL
export DATABASE_URL="postgresql://localhost/ai_slide_generator"

# Or start local PostgreSQL
brew services start postgresql
createdb ai_slide_generator
python scripts/init_database.py
```

---

## Extension Guidance

- **Adding new tables**: Define in `src/database/models/`, they'll be created on next deployment
- **Changing schema name**: Update `deployment.yaml` and redeploy (creates new schema)
- **Scaling capacity**: Update `capacity` in deployment.yaml (CU_1 → CU_8)
- **Multiple environments**: Each env gets its own instance (dev, staging, prod)

---

## Cross-References

- [Backend Overview](backend-overview.md) – FastAPI application structure
- [Databricks App Deployment](databricks-app-deployment.md) – Full deployment process
- [Database Configuration](database-configuration.md) – Local PostgreSQL setup

---

## External Documentation

- [Databricks Lakebase Docs](https://docs.databricks.com/aws/en/oltp/instances/query/notebook)
- [Databricks SDK - Database API](https://databricks-sdk-py.readthedocs.io/en/stable/workspace/database/database.html)
- [Databricks Blog: Lakebase for Apps](https://www.databricks.com/blog/how-use-lakebase-transactional-data-layer-databricks-apps)



