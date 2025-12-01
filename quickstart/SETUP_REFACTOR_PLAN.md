# Quickstart Setup Refactor - Implementation Plan

**Date:** 2025-12-01  
**Platform:** macOS only  
**Goal:** Modular, user-friendly setup process with one-command installation

---

## Overview

Replace the current semi-automated setup with a fully modular approach that:
- Offers to install missing system dependencies (Homebrew, Python, PostgreSQL, Node.js)
- Uses `uv` for fast Python dependency management
- Maintains `requirements.txt` for Databricks App deployment compatibility
- Provides clear, actionable error messages
- Separates setup concerns into focused scripts

---

## Design Principles

1. **User Consent First** - Offer to install, don't force
2. **Fail Fast with Guidance** - Clear errors with next steps
3. **Idempotent Operations** - Safe to re-run all scripts
4. **Separation of Concerns** - Each script has one job
5. **Runtime vs Setup** - .env validated at runtime, not setup

---

## File Structure

```
quickstart/
├── setup.sh                          # NEW: Master orchestrator
├── check_system_dependencies.sh      # NEW: macOS dependency checker
├── create_python_environment.sh      # NEW: venv + uv + deps
├── setup_database.sh                 # MODIFY: Remove venv/deps logic
├── QUICKSTART.md                     # UPDATE: Lead with one-command
└── SETUP_REFACTOR_PLAN.md           # This file

start_app.sh                          # MODIFY: Error if venv missing
```

---

## Dependency Categories

| Dependency | Check Phase | Missing Behavior | Required For |
|------------|-------------|------------------|--------------|
| macOS | check_system_dependencies.sh | ❌ Error, exit | Setup |
| Homebrew | check_system_dependencies.sh | Offer to install | Setup |
| Python 3.10+ | check_system_dependencies.sh | Offer to install | Setup |
| PostgreSQL 14+ | check_system_dependencies.sh | Offer to install | Setup |
| Node.js 18+ | check_system_dependencies.sh | Offer to install | Setup |
| .env file | check_system_dependencies.sh | ⚠️ Warn, continue | Runtime |
| .env values | check_system_dependencies.sh | ⚠️ Warn, continue | Runtime |
| .venv | start_app.sh | ❌ Error, exit | Runtime |
| .env file | start_app.sh | ❌ Error, exit | Runtime |
| .env values | start_app.sh | ❌ Error, exit | Runtime |

---

## Script Specifications

### 1. **quickstart/setup.sh** (NEW - Master Script)

**Purpose:** Orchestrate all setup steps in order

**Flow:**
```bash
1. Print welcome banner
2. cd to project root
3. Run check_system_dependencies.sh
   → If exit 1: Display error, exit
4. Run create_python_environment.sh
   → If exit 1: Display error, exit
5. Activate .venv
6. Run setup_database.sh
   → If exit 1: Display error, exit
7. Print completion banner
8. Check .env status
   → If missing/incomplete: Print configuration instructions
9. Print next steps
```

**Key Features:**
- Clear step numbering (1/3, 2/3, 3/3)
- Fails fast on any error
- Visual separation between steps
- Reminds about .env at end if needed

**Exit Codes:**
- `0` - All setup completed successfully
- `1` - Setup failed at any step

---

### 2. **quickstart/check_system_dependencies.sh** (NEW)

**Purpose:** Verify and optionally install system dependencies

**Platform Check:**
```bash
# First thing - verify macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "❌ This quickstart script is designed for macOS only"
    echo ""
    echo "For other platforms, install manually and run:"
    echo "  ./quickstart/create_python_environment.sh"
    echo "  ./quickstart/setup_database.sh"
    exit 1
fi
```

**Dependency Checks (in order):**

#### 1. Homebrew
```bash
if ! command -v brew &> /dev/null; then
    ✗ Not found
    → Prompt: "Install Homebrew? (required) (y/N)"
    → If yes: Run official install script
    → If no: Error and exit (required for rest)
else
    ✓ Found
fi
```

#### 2. Python 3.10+
```bash
if command -v python3 &> /dev/null; then
    Version check using: python3 -c 'import sys; print(...)'
    if version >= 3.10:
        ✓ Python X.Y found
    else:
        ✗ Python X.Y found (need 3.10+)
        → Prompt: "Install Python 3.11? (y/N)"
        → If yes: brew install python@3.11
        → If no: Add to MISSING_DEPS
else
    ✗ Not found
    → Prompt: "Install Python 3.11? (y/N)"
    → If yes: brew install python@3.11
    → If no: Add to MISSING_DEPS
fi
```

#### 3. PostgreSQL 14+
```bash
if command -v psql &> /dev/null; then
    ✓ PostgreSQL X.Y found
    
    # Check if running
    if pg_isready &> /dev/null; then
        ✓ PostgreSQL is running
    else:
        ⚠ PostgreSQL installed but not running
        → Prompt: "Start PostgreSQL? (y/N)"
        → If yes: brew services start postgresql@14
        → If no: Add to MISSING_DEPS
else:
    ✗ Not found
    → Prompt: "Install PostgreSQL 14? (y/N)"
    → If yes: 
        brew install postgresql@14
        brew services start postgresql@14
        Wait 2s, verify with pg_isready
    → If no: Add to MISSING_DEPS
fi
```

#### 4. Node.js 18+
```bash
if command -v node &> /dev/null; then
    Version check: node --version | grep -oE '[0-9]+' | head -1
    if version >= 18:
        ✓ Node.js vX found
    else:
        ✗ Node.js vX found (need 18+)
        → Prompt: "Install Node.js 20? (y/N)"
        → If yes: brew install node@20
        → If no: Add to MISSING_DEPS
else:
    ✗ Not found
    → Prompt: "Install Node.js 20? (y/N)"
    → If yes: brew install node@20
    → If no: Add to MISSING_DEPS
fi

# Check npm
if command -v npm &> /dev/null; then
    ✓ npm vX found
else:
    ⚠ npm not found (should come with Node)
    Add to MISSING_DEPS
fi
```

#### 5. .env File (Warning Only)
```bash
ENV_WARNINGS=()

if [ ! -f .env ]; then
    ⚠️ .env file not found
    Add to ENV_WARNINGS
else:
    ✓ .env file exists
    
    # Check DATABRICKS_HOST
    if ! grep -q "^DATABRICKS_HOST=.+" .env; then
        ⚠️ DATABRICKS_HOST not set
        Add to ENV_WARNINGS
    else:
        ✓ DATABRICKS_HOST is set
    fi
    
    # Check DATABRICKS_TOKEN
    if ! grep -q "^DATABRICKS_TOKEN=.+" .env; then
        ⚠️ DATABRICKS_TOKEN not set
        Add to ENV_WARNINGS
    else:
        ✓ DATABRICKS_TOKEN is set
    fi
fi
```

**Final Summary:**
```bash
if [ ${#MISSING_DEPS[@]} -eq 0 ]; then
    echo "✅ All system dependencies satisfied!"
    
    if [ ${#ENV_WARNINGS[@]} -gt 0 ]; then
        echo "⚠️  Environment configuration warnings:"
        Print each ENV_WARNING
        echo "Note: These can be configured later before running the app."
    fi
    
    exit 0
else:
    echo "❌ Missing required dependencies:"
    Print each MISSING_DEP
    
    if [ ${#ENV_WARNINGS[@]} -gt 0 ]; then
        echo "⚠️  Environment configuration warnings:"
        Print each ENV_WARNING
    fi
    
    exit 1
fi
```

**Exit Codes:**
- `0` - All required dependencies satisfied (.env warnings OK)
- `1` - Missing required dependencies

**Variables Tracked:**
- `MISSING_DEPS[]` - Array of missing hard requirements
- `ENV_WARNINGS[]` - Array of .env issues (non-blocking)

---

### 3. **quickstart/create_python_environment.sh** (NEW)

**Purpose:** Create venv and install Python dependencies using uv

**Flow:**

#### 1. Check for existing .venv
```bash
if [ -d ".venv" ]; then
    echo "⚠️  Virtual environment already exists at .venv/"
    read -p "Recreate it? (will delete existing) (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "→ Removing existing .venv..."
        rm -rf .venv
    else:
        echo "→ Using existing .venv"
        exit 0  # Success, nothing to do
    fi
fi
```

#### 2. Check for uv
```bash
if ! command -v uv &> /dev/null; then
    echo "ℹ️  uv not found - installing for faster dependency management..."
    pip3 install uv
    echo "✓ uv installed"
fi
```

#### 3. Create venv and install dependencies
```bash
echo "→ Creating virtual environment and installing dependencies..."
echo "  (This uses uv for 10-100x faster installation)"
echo ""

uv sync

if [ $? -ne 0 ]; then
    echo "❌ Failed to create Python environment"
    echo ""
    echo "Troubleshooting:"
    echo "  - Check requirements.txt exists"
    echo "  - Check pyproject.toml is valid"
    echo "  - Try: pip3 install uv --upgrade"
    exit 1
fi
```

#### 4. Verify installation
```bash
echo "→ Verifying installation..."

# Activate venv
source .venv/bin/activate

# Test critical imports
if python -c "import fastapi; import sqlalchemy; import alembic" 2>/dev/null; then
    echo "✓ Python environment ready!"
    echo ""
    echo "Tip: Activate with: source .venv/bin/activate"
    exit 0
else:
    echo "❌ Dependency verification failed"
    echo ""
    echo "Some packages may not have installed correctly."
    echo "Try:"
    echo "  rm -rf .venv"
    echo "  ./quickstart/create_python_environment.sh"
    exit 1
fi
```

**Exit Codes:**
- `0` - venv created and dependencies installed successfully
- `1` - Failed to create venv or install dependencies

**What `uv sync` Does:**
- Reads `pyproject.toml` for dependencies
- Uses `uv.lock` for deterministic versions
- Creates `.venv/` automatically
- Installs all packages
- Much faster than `pip install -r requirements.txt`

**Why Keep requirements.txt:**
- Required for Databricks App deployment
- Fallback for users without uv
- Can be regenerated from uv.lock if needed

---

### 4. **quickstart/setup_database.sh** (MODIFY)

**Changes Required:**

#### Remove Lines 132-147
Current code that handles venv creation and dependency installation:
```bash
# Lines 132-140: Check if virtual environment exists and activate it
if [ -d ".venv" ]; then
    echo -e "${BLUE}➤ Activating virtual environment...${NC}"
    source .venv/bin/activate
    echo -e "${GREEN}✓ Virtual environment activated${NC}"
else
    echo -e "${YELLOW}⚠ Virtual environment not found${NC}"
    echo -e "${YELLOW}  Please run: python3 -m venv .venv && source .venv/bin/activate${NC}"
fi

# Lines 142-147: Check if alembic is installed
if ! command -v alembic &> /dev/null; then
    echo -e "${YELLOW}⚠ Alembic not installed. Installing dependencies...${NC}"
    pip install -r requirements.txt > /dev/null
    echo -e "${GREEN}✓ Dependencies installed${NC}"
fi
```

#### Add at Beginning (After Line 26)
```bash
# Default database name
DB_NAME="ai_slide_generator"

# Verify Python environment is ready
echo -e "${BLUE}➤ Checking Python environment...${NC}"
if [ ! -d ".venv" ]; then
    echo -e "${RED}✗ Virtual environment not found${NC}"
    echo ""
    echo "Please run Python environment setup first:"
    echo -e "  ${BLUE}./quickstart/create_python_environment.sh${NC}"
    echo ""
    exit 1
fi

# Activate venv
source .venv/bin/activate
echo -e "${GREEN}✓ Virtual environment activated${NC}"

# Verify alembic is available
if ! command -v alembic &> /dev/null; then
    echo -e "${RED}✗ alembic not found in virtual environment${NC}"
    echo ""
    echo "Please run Python environment setup:"
    echo -e "  ${BLUE}./quickstart/create_python_environment.sh${NC}"
    echo ""
    exit 1
fi
echo -e "${GREEN}✓ alembic found${NC}"
```

**Keep Unchanged:**
- All PostgreSQL checks (lines 28-86)
- Database creation logic (lines 88-108)
- Database connection verification (lines 110-117)
- .env DATABASE_URL handling (lines 119-130)
- Migration execution (lines 149-153)
- Seed data loading (lines 155-161)
- Success banner (lines 163-175)

**Exit Codes:**
- `0` - Database setup completed successfully
- `1` - Failed (missing venv, Postgres issue, migration failure, etc.)

---

### 5. **start_app.sh** (MODIFY)

**Changes to Lines 32-47:**

**Current Code:**
```bash
# Check if .venv exists
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}⚠️  Virtual environment not found. Creating one...${NC}"
    python3 -m venv .venv
    echo -e "${GREEN}✅ Virtual environment created${NC}"
fi

# Activate virtual environment
echo -e "${BLUE}🔧 Activating virtual environment...${NC}"
source .venv/bin/activate

# Check if requirements are installed
if ! python -c "import fastapi" 2>/dev/null; then
    echo -e "${YELLOW}⚠️  Dependencies not installed. Installing...${NC}"
    pip install -r requirements.txt
    echo -e "${GREEN}✅ Dependencies installed${NC}"
fi
```

**New Code:**
```bash
# Check if .venv exists
if [ ! -d ".venv" ]; then
    echo -e "${RED}❌ Virtual environment not found${NC}"
    echo ""
    echo "Please run the setup first:"
    echo -e "  ${BLUE}./quickstart/setup.sh${NC}         # Full setup"
    echo "  or"
    echo -e "  ${BLUE}./quickstart/create_python_environment.sh${NC}  # Just Python env"
    echo ""
    exit 1
fi

# Activate virtual environment
echo -e "${BLUE}🔧 Activating virtual environment...${NC}"
source .venv/bin/activate

# Verify critical dependencies are installed
if ! python -c "import fastapi" 2>/dev/null; then
    echo -e "${RED}❌ Dependencies not properly installed${NC}"
    echo ""
    echo "Please run: ${BLUE}./quickstart/create_python_environment.sh${NC}"
    echo ""
    exit 1
fi
echo -e "${GREEN}✅ Dependencies verified${NC}"
```

**Add .env Validation (After Line 29):**

**Current Code:**
```bash
# Load environment variables from .env file
if [ -f .env ]; then
    echo -e "${BLUE}🔧 Loading environment variables from .env...${NC}"
    # Export variables safely (handles values with spaces)
    export $(grep -v '^#' .env | grep -v '^$' | xargs -d '\n')
    echo -e "${GREEN}✅ Environment variables loaded${NC}"
else
    echo -e "${YELLOW}⚠️  No .env file found. Using system environment variables.${NC}"
fi
```

**New Code:**
```bash
# Load environment variables from .env file
if [ -f .env ]; then
    echo -e "${BLUE}🔧 Loading environment variables from .env...${NC}"
    # Export variables safely (handles values with spaces)
    export $(grep -v '^#' .env | grep -v '^$' | xargs -d '\n')
    echo -e "${GREEN}✅ Environment variables loaded${NC}"
else
    echo -e "${RED}❌ .env file not found${NC}"
    echo ""
    echo "Please create .env file:"
    echo -e "  ${BLUE}cp .env.example .env${NC}"
    echo -e "  ${BLUE}nano .env${NC}  # Set DATABRICKS_HOST and DATABRICKS_TOKEN"
    echo ""
    exit 1
fi

# Validate required environment variables
if [ -z "$DATABRICKS_HOST" ] || [ -z "$DATABRICKS_TOKEN" ]; then
    echo -e "${RED}❌ Missing required environment variables${NC}"
    echo ""
    echo "Please ensure .env file contains:"
    echo "  - DATABRICKS_HOST=https://your-workspace.cloud.databricks.com"
    echo "  - DATABRICKS_TOKEN=your-token-here"
    echo ""
    exit 1
fi
```

**Keep Unchanged:**
- Frontend checks and setup (lines 55-71)
- Log directory creation (line 74)
- Backend startup (lines 76-94)
- Frontend startup (lines 96-105)
- Success banner and URLs (lines 107-131)

---

### 6. **quickstart/QUICKSTART.md** (UPDATE)

**Restructure Document:**

#### New Structure

```markdown
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
```

**Key Changes:**
- Lead with platform requirement (macOS only)
- Emphasize one-command setup
- .env is optional during setup
- Show what the interactive install looks like
- Move manual steps to "Advanced Users"
- Add troubleshooting for new error messages
- Explain why uv is used

---

## Implementation Checklist

### New Files to Create (3)
- [ ] `quickstart/setup.sh` - Master orchestrator script
- [ ] `quickstart/check_system_dependencies.sh` - macOS dependency checker
- [ ] `quickstart/create_python_environment.sh` - venv + uv setup

### Files to Modify (3)
- [ ] `quickstart/setup_database.sh`
  - [ ] Remove lines 132-147 (venv/deps handling)
  - [ ] Add venv check at start (after line 26)
  - [ ] Keep all other logic unchanged
  
- [ ] `start_app.sh`
  - [ ] Change lines 32-47 (error on missing venv)
  - [ ] Add .env validation after load (after line 29)
  - [ ] Keep all other logic unchanged
  
- [ ] `quickstart/QUICKSTART.md`
  - [ ] Add platform requirement at top
  - [ ] Restructure around one-command setup
  - [ ] Move manual steps to advanced section
  - [ ] Update troubleshooting section

### Script Permissions
All new scripts need execute permissions:
```bash
chmod +x quickstart/setup.sh
chmod +x quickstart/check_system_dependencies.sh
chmod +x quickstart/create_python_environment.sh
```

### Testing Strategy

#### Test 1: Fresh Install (Nothing Installed)
```bash
# Simulated: No Homebrew, no Python, no Postgres, no Node
./quickstart/setup.sh
# Should offer to install everything
```

#### Test 2: Partial Install (Some Dependencies Present)
```bash
# Simulated: Has Homebrew and Python, missing Postgres and Node
./quickstart/setup.sh
# Should skip Python, offer Postgres and Node
```

#### Test 3: Complete Dependencies, No .env
```bash
# All deps present, no .env file
./quickstart/setup.sh
# Should complete with warning about .env
./start_app.sh
# Should error and prompt for .env
```

#### Test 4: Complete Dependencies, Empty .env
```bash
# All deps present, .env exists but empty
./quickstart/setup.sh
# Should complete with warning about .env values
./start_app.sh
# Should error and prompt to fill in .env
```

#### Test 5: Re-run Setup (Idempotency)
```bash
# After successful setup
./quickstart/setup.sh
# Should detect everything present, skip reinstalls
```

#### Test 6: Individual Scripts
```bash
# Run each script independently
./quickstart/check_system_dependencies.sh  # Should pass
./quickstart/create_python_environment.sh  # Should prompt about existing .venv
./quickstart/setup_database.sh             # Should complete successfully
```

#### Test 7: Error Recovery
```bash
# Kill Postgres
brew services stop postgresql@14
./start_app.sh
# Should detect DB unavailable (may be caught by backend startup)

# Remove .venv
rm -rf .venv
./start_app.sh
# Should error immediately with guidance

# Remove .env
mv .env .env.backup
./start_app.sh
# Should error immediately with guidance
```

---

## Benefits Summary

### User Experience
✅ **One command to set up** - `./quickstart/setup.sh`  
✅ **Interactive and guided** - Offers to install, explains what's happening  
✅ **Safe and transparent** - User approves each installation  
✅ **Fast** - Uses uv for 10-100x faster Python installs  
✅ **Recoverable** - Clear error messages with next steps  

### Developer Experience
✅ **Modular** - Each script has one clear purpose  
✅ **Maintainable** - Easy to update individual components  
✅ **Testable** - Can test each script independently  
✅ **Documented** - Clear comments and structure  

### Technical
✅ **Idempotent** - Safe to re-run without breaking state  
✅ **Fail-fast** - Errors caught early with guidance  
✅ **Platform-specific** - Optimized for macOS, no unnecessary complexity  
✅ **Keeps requirements.txt** - Compatible with Databricks deployment  

---

## Open Questions / Considerations

### 1. .env.example File
- **Status:** Assumed to exist in repo
- **Action:** Verify file exists and has correct template format

### 2. Frontend Dependencies
- **Status:** Handled by start_app.sh (lines 56-71)
- **Decision:** Keep in start_app.sh, not part of quickstart setup
- **Rationale:** Frontend setup is quick, defer to runtime

### 3. Database Seeding
- **Status:** Handled by setup_database.sh (scripts/init_database.py)
- **Question:** What if seeding fails? Should it be fatal?
- **Current:** Non-fatal, prints warning

### 4. Python Version Detection
- **Challenge:** Homebrew may install python3.11 but `python3` may point to system Python
- **Solution:** Use `python3` command explicitly, check version before proceeding

### 5. PATH Updates After Install
- **Issue:** Newly installed Homebrew packages may not be in PATH until shell restart
- **Solution:** 
  - Eval brew shellenv after Homebrew install
  - Warn user about potential shell restart need
  - Check commands again after install

### 6. M1/M2 Mac vs Intel Mac
- **Difference:** Homebrew installs to /opt/homebrew vs /usr/local
- **Solution:** Use `brew --prefix` for dynamic path resolution
- **Status:** Homebrew handles this automatically

---

## Future Enhancements (Out of Scope)

### Linux Support
- Add separate `check_system_dependencies_linux.sh`
- Detect apt vs yum vs pacman
- Handle sudo properly
- Update master script to detect OS and call appropriate checker

### Windows Support (via WSL)
- Create `check_system_dependencies_wsl.sh`
- Handle Windows-specific paths
- Document WSL setup requirements

### Docker Option
- Create `docker-compose.yml` for full stack
- Bypass system dependency checks
- Still need .env file

### Offline Mode
- Download all packages ahead of time
- Use local pip cache
- Bundle Homebrew formulae

---

## References

- **Homebrew:** https://brew.sh
- **uv:** https://github.com/astral-sh/uv
- **PostgreSQL on macOS:** https://www.postgresql.org/download/macosx/
- **Python Version Management:** https://docs.python.org/3/using/mac.html

---

**End of Plan**

