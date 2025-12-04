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
│  ├─ Chat Panel: Send prompts, view responses                        │
│  ├─ Selection Ribbon: Pick slides for editing                       │
│  └─ Slide Panel: View, reorder, edit slides                         │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ REST API
┌──────────────────────────▼──────────────────────────────────────────┐
│  Backend (FastAPI + LangChain)                                      │
│  ├─ ChatService: Session management, slide deck state               │
│  ├─ SlideGeneratorAgent: Tool-calling LLM agent                     │
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
- **Genie Integration:** Converts natural language to SQL queries against your data
- **SlideDeck Parser:** Robust HTML parsing with BeautifulSoup for slide manipulation
- **Chart.js:** Data visualizations with defensive rendering

---

## Databricks CLI Dependency

Regardless of whether you are deploying for development or use, there is a hard requirement for an authenticated Databricks CLI setup. Please follow these [instructions](https://docs.databricks.com/aws/en/dev-tools/cli/install) to get set up with the Databricks CLI and authenticated.

---

## Deploy to Databricks

Deploy the app as a Databricks App with Lakebase for persistence.

### Prerequisites

- Databricks workspace with Apps enabled
- Permission to create a Lakebase, or ability to create schema on an existing one.
- Genie space configured with your data
- Access to a chat model foundation model (Databricks Foundation Model APIs are easiest for quick setup, but the App is compatitible with any Databricks model serving endpoint.)

### Deploy

```bash
# 1. Clone and enter the repo
git clone <repository-url>
cd ai-slide-generator

# 2. Copy deployment config
cp config/deployment.example.yaml config/deployment.yaml

# 3. Edit deployment.yaml with your workspace details
#    - Replace {username} with your Databricks username
#    - Set appropriate permissions

# 4. Deploy to development environment
python -m db_app_deployment.deploy --create --env development

# Or update an existing deployment
python -m db_app_deployment.deploy --update --env development
```

### Deployment Environments

| Environment | Use Case | Compute |
|-------------|----------|---------|
| `development` | Personal dev/test | MEDIUM |
| `staging` | Team testing | MEDIUM |
| `production` | End users | MEDIUM |

NB - Compute is an option of MEDIUM or LARGE. This is a lightweight app - it is unlikely to need a LARGE. 

### Configuration

Edit `config/deployment.yaml` to customize:

```yaml
environments:
  development:
    app_name: "ai-slide-generator-dev"
    workspace_path: "/Workspace/Users/you@example.com/apps/dev/ai-slide-generator"
    permissions:
      - user_name: "you@example.com"
        permission_level: "CAN_MANAGE"
    compute_size: "MEDIUM"
    lakebase:
      database_name: "ai-slide-generator-dev-db"
      schema: "app_data"
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
├── src/
│   ├── api/              # FastAPI routes and services
│   ├── core/             # Settings, database, Databricks client
│   ├── models/           # Slide and SlideDeck classes
│   ├── services/         # Agent and Genie tools
│   └── utils/            # HTML parsing, logging
├── frontend/             # React + Vite + TypeScript
├── config/               # YAML configuration files
├── db_app_deployment/    # Databricks deployment CLI
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
| [Databricks Deployment](docs/technical/databricks-app-deployment.md) | Deployment CLI, environments |
| [Slide Parser](docs/technical/slide-parser-and-script-management.md) | HTML parsing, script handling |
| [Database Config](docs/technical/database-configuration.md) | PostgreSQL/Lakebase schema |

---

## Usage

### Generate Slides

```
Create a 10-slide presentation about Q3 revenue trends
```

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
