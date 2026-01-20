# AI Slide Generator

Generate professional HTML slide decks from natural language using LLMs and Databricks Genie. Ask questions, get data-driven presentations with visualizations.

**In this README:**
- [What It Does](#what-it-does) – Overview of the application
- [Architecture](#architecture) – System components and data flow
- [Deploy to Databricks](#deploy-to-databricks) – Production deployment guide
- [Local Development Setup](#local-development-setup) – Get running for development
- [Usage](#usage) – How to generate and edit slides

---

## What It Does

**Input:** Natural language (e.g., "Create a 10-slide report on Q3 consumption trends")

**Output:** Interactive HTML slide deck with charts, data tables, and narrative

**How:**
1. LangChain agent receives your question
2. Agent queries Databricks Genie for structured data
3. Agent analyzes patterns and generates insights
4. Agent produces HTML slides with Chart.js visualizations
5. You can edit, reorder, or refine slides via chat

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Frontend (React + Vite + TypeScript)                               │
│  ├─ Chat Panel: Real-time SSE streaming, message persistence        │
│  ├─ Selection Ribbon: Pick slides for editing                       │
│  └─ Slide Panel: View, reorder, edit slides                         │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ REST API + SSE
┌──────────────────────────▼──────────────────────────────────────────┐
│  Backend (FastAPI + LangChain)                                      │
│  ├─ ChatService: Session management, streaming, history             │
│  ├─ SlideGeneratorAgent: Tool-calling LLM with callbacks            │
│  ├─ SlideDeck: HTML parsing and manipulation                        │
│  └─ Genie Tool: Natural language → SQL data retrieval               │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────────┐
│  Databricks Platform                                                │
│  ├─ LLM Serving Endpoint (Llama 3.1 70B or similar)                 │
│  ├─ Genie Space (SQL data access)                                   │
│  ├─ MLflow (tracing and observability)                              │
│  └─ Lakebase (session/config persistence - production)              │
└─────────────────────────────────────────────────────────────────────┘
```

**Key Components:**
- **LangChain Agent:** Orchestrates multi-step reasoning with tool calls
- **SSE Streaming:** Real-time progress via Server-Sent Events with message persistence
- **Genie Integration:** Converts natural language to SQL queries against your data
- **SlideDeck Parser:** Robust HTML parsing with BeautifulSoup for slide manipulation
- **Chart.js:** Data visualizations with defensive rendering
- **LLM as Judge:** Auto-verifies slide accuracy against Genie source data with MLflow tracing
- **Deck Prompt Library:** Reusable presentation templates for consistent, standardized decks

---

## Databricks CLI Dependency

Regardless of whether you are deploying for development or use, there is a hard requirement for an authenticated Databricks CLI setup. Please follow these [instructions](https://docs.databricks.com/aws/en/dev-tools/cli/install) to get set up with the Databricks CLI and authenticated.

---

## Deploy to Databricks

Deploy the app as a Databricks App with Lakebase for persistence.

### Prerequisites

- Databricks workspace with Apps enabled
- Permission to create a Lakebase, or ability to create schema on an existing one
- Genie space configured with your data
- Access to a chat model foundation model (Databricks Foundation Model APIs are easiest for quick setup, but the app is compatible with any Databricks model serving endpoint)

### Option 1: Deploy via Python Package (Recommended for Production)

Install the deployment package and deploy from a notebook or Python script:

```bash
pip install databricks-tellr
```

**From a Databricks Notebook:**

```python
from databricks_tellr import deploy

# Create a new app
deploy.create(
    lakebase_name="ai-slide-generator-db",
    schema_name="app_data",
    app_name="ai-slide-generator",
    app_file_workspace_path="/Workspace/Users/you@example.com/.apps/ai-slide-generator",
    lakebase_compute="CU_1",      # Options: CU_1, CU_2, CU_4, CU_8
    app_compute="MEDIUM",          # Options: MEDIUM, LARGE
    app_version="0.1.18",          # Optional: pin to specific version
)

# Update an existing app
deploy.update(
    app_name="ai-slide-generator",
    app_file_workspace_path="/Workspace/Users/you@example.com/.apps/ai-slide-generator",
    lakebase_name="ai-slide-generator-db",
    schema_name="app_data",
    reset_database=False,          # Set True to drop and recreate schema
)

# Delete an app
deploy.delete(
    app_name="ai-slide-generator",
    lakebase_name="ai-slide-generator-db",
    schema_name="app_data",
    reset_database=True,           # Drop schema before deleting
)
```

**From local Python with a CLI profile:**

```python
from databricks_tellr import deploy

deploy.create(
    lakebase_name="ai-slide-generator-db",
    schema_name="app_data",
    app_name="ai-slide-generator-dev",
    app_file_workspace_path="/Workspace/Users/you@example.com/.apps/dev/ai-slide-generator",
    profile="my-databricks-profile",  # Uses ~/.databrickscfg
)
```

### Option 2: Deploy from Local Source (Development)

For testing local code changes before publishing, use the local deployment script:

```bash
# 1. Clone and enter the repo
git clone <repository-url>
cd ai-slide-generator

# 2. Copy deployment config
cp config/deployment.example.yaml config/deployment.yaml

# 3. Edit deployment.yaml with your workspace details

# 4. Create a new app with local code
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

### Verify Deployment

```bash
# Check app health
curl https://<your-app-url>/health

# View in Databricks UI: Apps → ai-slide-generator-dev → Status/Logs
```

---

## Local Development Setup

Run the full stack locally for development.

### Prerequisites

- macOS for automated setup (Linux/Windows requires manual steps below)
- Python 3.11+, Node.js 18+, PostgreSQL 14+ (installed automatically if missing)

### Quick Setup (macOS)

```bash
# 1. Clone repo
git clone <repository-url>
cd ai-slide-generator

# 2. Copy .env.example and fill in your values
cp .env.example .env
# Edit .env with your Databricks workspace details

# 3. Run automated setup
./quickstart/setup.sh

# 4. Start the app
./start_app.sh

# 5. Open http://localhost:3000

# 6. To stop front and back end
./stop_app.sh
```

The setup script will:
- Install system dependencies (Homebrew, Python, PostgreSQL, Node.js)
- Create Python virtual environment with uv
- Initialize PostgreSQL database
- Install frontend dependencies

### Manual Setup

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

### Verify Local Setup

```bash
# Backend health
curl http://localhost:8000/health

# Run tests
pytest

# Check logs
tail -f logs/backend.log
```

---

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
├── docs/technical/       # Architecture documentation
├── tests/                # Unit and integration tests
└── quickstart/           # Setup scripts
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [Backend Overview](docs/technical/backend-overview.md) | FastAPI, agent lifecycle, API contracts |
| [Frontend Overview](docs/technical/frontend-overview.md) | React components, state management |
| [Real-Time Streaming](docs/technical/real-time-streaming.md) | SSE events, conversation persistence |
| [Databricks Deployment](docs/technical/databricks-app-deployment.md) | Deployment CLI, environments |
| [Slide Parser](docs/technical/slide-parser-and-script-management.md) | HTML parsing, CSS merging, script handling |
| [Slide Editing Robustness](docs/technical/slide-editing-robustness-fixes.md) | Deck preservation, validation, clarification guards, canvas deduplication |
| [Database Config](docs/technical/database-configuration.md) | PostgreSQL/Lakebase schema |

---

## Usage

### Generate Slides

```
Create a 10-slide presentation about Q3 revenue trends
```

### Use Deck Prompts

For standardized presentations (e.g., QBRs, consumption reviews), use Deck Prompts:

1. Go to **Deck Prompts** page to view/create templates
2. In **Profiles**, select a profile and go to the **Deck Prompt** tab
3. Select a template — the AI will follow its structure when generating slides

### Edit Existing Slides

1. Select slides 2-4 in the selection ribbon
2. Type: "Combine these into a single summary slide with a chart"

### Manual Adjustments

- **Reorder:** Drag slides in the panel
- **Edit HTML:** Click edit icon, modify in Monaco editor
- **Duplicate/Delete:** Use toolbar icons

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `DATABRICKS_HOST not set` | Create `.env` file with credentials |
| `Database connection failed` | Run `./quickstart/setup_database.sh` |
| `Port already in use` | Run `./stop_app.sh` first |
| Deployment fails | Run with `--dry-run` to validate config |

See [Troubleshooting Guide](quickstart/TROUBLESHOOTING.md) for more.

---

## Tech Stack

**Backend:** Python 3.11, FastAPI, LangChain, Databricks SDK, SQLAlchemy, BeautifulSoup

**Frontend:** React 18, TypeScript, Vite, Tailwind CSS, Monaco Editor, @dnd-kit

**Infrastructure:** Databricks Apps, Lakebase, MLflow, PostgreSQL (local)
