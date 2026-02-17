# Local Development Setup

Run the full stack locally for development and testing.

## Prerequisites

- macOS for automated setup (Linux/Windows requires manual steps below)
- Python 3.11+, Node.js 18+, PostgreSQL 14+ (installed automatically if missing)
- Authenticated Databricks CLI (see [Databricks CLI setup](https://docs.databricks.com/aws/en/dev-tools/cli/install))

## Quick Setup (macOS)

```bash
# 1. Clone repo
git clone https://github.com/robertwhiffin/ai-slide-generator.git
cd ai-slide-generator

# 2. Run automated setup
./quickstart/setup.sh

# 3. Start the app
./start_app.sh

# 4. Open http://localhost:3000
#    - First run: Enter your Databricks workspace URL and sign in
#    - Subsequent runs: Goes straight to the app

# 5. To stop front and back end
./stop_app.sh
```

The setup script will:
- Install system dependencies (Homebrew, Python, PostgreSQL, Node.js)
- Create Python virtual environment with uv
- Initialize PostgreSQL database
- Install frontend dependencies

## Authentication Options

tellr supports multiple ways to authenticate with Databricks:

| Method | How to Use |
|--------|------------|
| **Browser SSO** (recommended) | Just run the app — enter your workspace URL in the welcome screen and sign in via browser |
| **Environment file** | Create `.env` with `DATABRICKS_HOST` and `DATABRICKS_TOKEN` (traditional method) |
| **Databricks CLI** | If you have `~/.databrickscfg` configured, tellr will use it automatically |

**No PAT tokens required** — the browser SSO method lets you sign in with your normal Databricks credentials.

## Manual Setup

<details>
<summary>Click to expand manual steps</summary>

```bash
# Python environment
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Database
createdb ai_slide_generator
python scripts/init_database.py

# Frontend
cd frontend
npm install
cd ..

# Start backend
uvicorn src.api.main:app --reload --port 8000

# Start frontend (new terminal)
cd frontend
npm run dev
```

</details>

## Verify Local Setup

```bash
# Backend health
curl http://localhost:8000/health

# Run tests
pytest

# Check logs
tail -f logs/backend.log
```

## Project Structure

```
ai-slide-generator/
├── src/                  # Application source code
│   ├── api/              # FastAPI routes and services
│   ├── core/             # Settings, database, Databricks client
│   ├── domain/           # Slide and SlideDeck classes
│   ├── services/         # Agent, Genie tools, evaluation
│   └── utils/            # HTML parsing, logging
├── frontend/             # React + Vite + TypeScript
├── packages/             # Distributable Python packages
│   ├── databricks-tellr/       # Deployment tooling (pip install databricks-tellr)
│   └── databricks-tellr-app/   # App package for Databricks Apps
├── scripts/              # Development and deployment scripts
│   ├── deploy_local.sh   # Local wheel deployment to Databricks
│   ├── build_wheels.sh   # Build packages locally
│   └── publish_pypi.sh   # Publish to PyPI
├── config/               # YAML configuration files
├── docs/
│   ├── user-guide/       # User guide with screenshots
│   └── technical/        # Architecture documentation
├── tests/                # Unit and integration tests
└── quickstart/           # Setup scripts
```

## Deploy Local Changes to Databricks

For testing local code changes before publishing, use the local deployment script:

```bash
# Copy deployment config
cp config/deployment.example.yaml config/deployment.yaml

# Edit deployment.yaml with your workspace details

# Create a new app with local code
./scripts/deploy_local.sh create --env development --profile my-profile

# Update with your latest local changes
./scripts/deploy_local.sh update --env development --profile my-profile

# Update and reset database (WARNING: deletes all data)
./scripts/deploy_local.sh update --env development --profile my-profile --reset-db

# Include Databricks-specific prompts when seeding
./scripts/deploy_local.sh create --env development --profile my-profile --include-databricks-prompts

# Skip wheel rebuild (use existing wheels)
./scripts/deploy_local.sh update --env development --profile my-profile --skip-build

# Delete an app
./scripts/deploy_local.sh delete --env development --profile my-profile
```

The local deployment script:
1. Builds Python wheels for both `databricks-tellr` and `databricks-tellr-app`
2. Uploads the app wheel to your Databricks workspace
3. Creates/updates the Databricks App to use the uploaded wheel

### Deployment Environments

| Environment | Use Case | Compute |
|-------------|----------|---------|
| `development` | Personal dev/test | MEDIUM |
| `staging` | Team testing | MEDIUM |
| `production` | End users | MEDIUM |

Compute options are MEDIUM or LARGE. This is a lightweight app - MEDIUM is typically sufficient.

### Configuration

Edit `config/deployment.yaml` to customize environments:

```yaml
environments:
  development:
    app_name: "ai-slide-generator-dev"
    workspace_path: "/Workspace/Users/you@example.com/.apps/dev/ai-slide-generator"
    permissions:
      - user_name: "you@example.com"
        permission_level: "CAN_MANAGE"
    compute_size: "MEDIUM"
    lakebase:
      database_name: "ai-slide-generator-db-dev"
      schema: "app_data_dev"
      capacity: "CU_1"
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `DATABRICKS_HOST not set` | Use the welcome screen to enter your workspace URL, or create `.env` file |
| `Database connection failed` | Run `./quickstart/setup_database.sh` |
| `Port already in use` | Run `./stop_app.sh` first |
| Deployment fails | Run with `--dry-run` to validate config |
| Want to change workspace | Delete config and restart: `rm ~/.tellr/config.yaml && ./start_app.sh` |

For more troubleshooting information, see the troubleshooting guide in the quickstart directory at the project root.

## Tech Stack

**Backend:** Python 3.11, FastAPI, LangChain, Databricks SDK, SQLAlchemy, BeautifulSoup

**Frontend:** React 18, TypeScript, Vite, Tailwind CSS, Monaco Editor, @dnd-kit

**Infrastructure:** Databricks Apps, Lakebase, MLflow, PostgreSQL (local)
