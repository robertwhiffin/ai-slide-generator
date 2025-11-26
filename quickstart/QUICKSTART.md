# Quick Start Guide - AI Slide Generator

Get up and running in **5 minutes**! This guide will help you set up the AI Slide Generator from scratch.

## Prerequisites Check

Before starting, verify you have:

- [ ] **Python 3.10+** installed (`python3 --version`)
- [ ] **PostgreSQL 14+** installed (`psql --version`)
- [ ] **Node.js 18+** and npm installed (`node --version`)
- [ ] **Databricks workspace access** with:
  - Personal access token
  - Model serving endpoint deployed
  - Genie space configured

### Installing Prerequisites

#### macOS
```bash
# Install Homebrew if not already installed
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install prerequisites
brew install python@3.11 postgresql@14 node

# Start PostgreSQL
brew services start postgresql@14
```

#### Ubuntu/Debian
```bash
# Update package list
sudo apt-get update

# Install prerequisites
sudo apt-get install -y python3.11 python3-pip python3-venv postgresql postgresql-contrib nodejs npm

# Start PostgreSQL
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

## Database Architecture

This application uses **PostgreSQL** for local development with a clear path to **Lakebase** (Unity Catalog) for production:

```
Development          Production
───────────         ────────────
PostgreSQL    →     Lakebase
     ↑                   ↑
     └── SQLAlchemy ─────┘
     (no code changes needed)
```

**Default Profiles:**
- Profiles are defined in `config/seed_profiles.yaml`
- Automatically loaded during setup
- Easy to customize before first run

**Why PostgreSQL?**
- Multi-user session support
- State persistence
- Direct path to Lakebase (same SQLAlchemy code)

## Setup Steps

### Step 1: Clone Repository
```bash
git clone <repository-url>
cd ai-slide-generator
```

### Step 2: Configure Environment
```bash
# Copy environment template
cp .env.example .env

# Edit .env with your credentials
nano .env  # or use your preferred editor
```

**Required configuration:**
- `DATABRICKS_HOST` - Your Databricks workspace URL (e.g., `https://your-workspace.cloud.databricks.com`)
- `DATABRICKS_TOKEN` - Your personal access token (create at: Workspace Settings > Developer > Access Tokens)
- `DATABASE_URL` - PostgreSQL connection (default: `postgresql://localhost:5432/ai_slide_generator`)

### Step 3: Set Up Database
```bash
# Run automated database setup
chmod +x quickstart/setup_database.sh
./quickstart/setup_database.sh
```

This script will:
1. Check PostgreSQL is installed and running
2. Create `ai_slide_generator` database
3. Apply database schema via Alembic (creates tables)
4. Load default profiles from `config/seed_profiles.yaml`

### Step 4: Start Application
```bash
# Start both backend and frontend
chmod +x start_app.sh
./start_app.sh
```

This will:
- Create virtual environment (if needed)
- Install all dependencies
- Start backend on port 8000
- Start frontend on port 3000
- Run health checks

### Step 5: Verify Installation

1. **Open the web interface:** http://localhost:3000

2. **Test the application:**
   - Type in the chat: `"Create 5 slides about data analytics trends"`
   - Press Enter
   - Watch slides appear in real-time!

3. **Check API documentation:** http://localhost:8000/docs

## Quick Test

Once running, try these example prompts:

1. **Basic generation:**
   ```
   Create a 10-page slide deck about Q3 sales performance
   ```

2. **Data-driven slides:**
   ```
   Show me consumption trends for the last 6 months with charts
   ```

3. **Editing slides:**
   - Select slides 2-3 in the slide ribbon
   - Type: `Combine these into a single chart slide`

## Common Issues

### "PostgreSQL is not running"
```bash
# macOS
brew services start postgresql@14

# Linux
sudo systemctl start postgresql
```

### "DATABRICKS_HOST or DATABRICKS_TOKEN not set"
1. Check `.env` file exists in project root
2. Verify values are set correctly (no quotes needed)
3. Ensure `DATABRICKS_HOST` starts with `https://`

### "Database connection failed"
```bash
# Test connection manually
psql -d ai_slide_generator -c "SELECT version();"

# If fails, recreate database
./quickstart/setup_database.sh
```

### "Port 8000 or 3000 already in use"
```bash
# Stop existing processes
./stop_app.sh

# Or manually kill processes
lsof -ti:8000 | xargs kill -9
lsof -ti:3000 | xargs kill -9
```

## Next Steps

Once you're up and running:

1. **Read the main documentation:** [README.md](../README.md)
2. **Explore features:**
   - Drag-and-drop slide reordering
   - HTML editing with Monaco editor
   - Slide duplication and deletion
   - Raw HTML debugging views

3. **Review technical docs:**
   - [Backend Overview](../docs/technical/backend-overview.md)
   - [Frontend Overview](../docs/technical/frontend-overview.md)
   - [Database Configuration](../docs/technical/database-configuration.md)

4. **Run tests:**
   ```bash
   source .venv/bin/activate
   pytest
   ```

## Stopping the Application

```bash
./stop_app.sh
```

## Getting Help

- **Issues?** Check [TROUBLESHOOTING.md](./TROUBLESHOOTING.md)
- **Development?** See [../docs/](../docs/)
- **Questions?** Open an issue on GitHub

---

**Total time:** ~5 minutes ⏱️

**Ready to generate slides!** 🎉

