# Quick Start Guide - AI Slide Generator

**Platform:** macOS only  
**Time:** ~5 minutes ⏱️

## Prerequisites

Before starting, you need:
- [ ] macOS (Catalina 10.15 or later)
- [ ] Databricks workspace credentials (host URL + access token)

**Optional (will be installed if missing):**
- Homebrew
- Python 3.10+
- PostgreSQL 14+
- Node.js 18+

## One-Command Setup

### Step 1: Clone Repository
```bash
git clone <repository-url>
cd ai-slide-generator
```

### Step 2: Configure Databricks Credentials (Optional)
```bash
cp .env.example .env
nano .env  # Set DATABRICKS_HOST and DATABRICKS_TOKEN
```

> 💡 **Tip:** You can skip this and configure later. The setup will run without it.

### Step 3: Run Automated Setup
```bash
./quickstart/setup.sh
```

This single command will:
1. ✓ Check system dependencies (offer to install if missing)
2. ✓ Create Python virtual environment using uv
3. ✓ Install all Python dependencies
4. ✓ Create PostgreSQL database
5. ✓ Run migrations and load default profiles

### Step 4: Start Application
```bash
./start_app.sh
```

Opens:
- **Frontend:** http://localhost:3000
- **API Docs:** http://localhost:8000/docs

---

## What the Setup Script Does

### Interactive Dependency Installation

The setup script will check for required dependencies and offer to install them:

```bash
Checking Homebrew...
✗ Homebrew not found
Install Homebrew? (required for automated setup) (y/N): y
→ Installing Homebrew...
✓ Homebrew installed

Checking Python 3.10+...
✗ Python not found
Install Python 3.11 via Homebrew? (y/N): y
→ Installing Python 3.11...
✓ Python 3.11.5 installed
```

**You control what gets installed** - the script asks before making any changes.

---

## Manual Setup (Advanced Users)

If you need to run individual steps or troubleshoot:

### Individual Setup Steps
```bash
# 1. Check and install system dependencies
./quickstart/check_system_dependencies.sh

# 2. Create Python environment
./quickstart/create_python_environment.sh

# 3. Setup database
./quickstart/setup_database.sh
```

### Running Individual Scripts

**Check system dependencies only:**
```bash
./quickstart/check_system_dependencies.sh
```

**Recreate Python environment:**
```bash
rm -rf .venv
./quickstart/create_python_environment.sh
```

**Reset database:**
```bash
./quickstart/setup_database.sh
# Will prompt if database exists
```

---

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

---

## Common Issues

### "PostgreSQL is not running"
```bash
brew services start postgresql@14
```

### "DATABRICKS_HOST or DATABRICKS_TOKEN not set"

**Option A — UI authentication (recommended):**
Simply open http://localhost:3000, enter your workspace URL in the welcome screen, and sign in via browser. No `.env` file needed.

**Option B — Environment file:**
1. Create `.env` file: `cp .env.example .env`
2. Edit and set values: `nano .env`
3. Restart app: `./stop_app.sh && ./start_app.sh`

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

### "Virtual environment not found" when running start_app.sh
```bash
# Run Python environment setup
./quickstart/create_python_environment.sh
```

---

## What Gets Installed

### System Dependencies (via Homebrew)
- **Python 3.11** - Runtime environment
- **PostgreSQL 14** - Database for sessions and configuration
- **Node.js 20** - Frontend development server

### Python Dependencies (via uv)
Installed in `.venv/` from `requirements.txt`:
- FastAPI, Uvicorn - Backend API
- SQLAlchemy, Alembic - Database ORM and migrations
- Databricks SDK - Integration with Databricks
- LangChain - LLM orchestration
- BeautifulSoup4 - HTML parsing

### Why uv?
- **10-100x faster** than pip
- **Deterministic builds** via uv.lock
- **Built-in venv management**

---

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

---

## Stopping the Application

```bash
./stop_app.sh
```

---

## Getting Help

- **Setup issues?** Check [TROUBLESHOOTING.md](./TROUBLESHOOTING.md)
- **Development questions?** See [../docs/](../docs/)
- **Found a bug?** Open an issue on GitHub

---

**Total time:** ~5 minutes ⏱️  
**Ready to generate slides!** 🎉
