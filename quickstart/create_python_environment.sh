#!/bin/bash
# =============================================================================
# create_python_environment.sh - Python Environment Setup
# =============================================================================
# Purpose: Create venv and install Python dependencies using uv
# 
# Flow:
#   1. Check for existing .venv (offer to recreate)
#   2. Check for uv (install if missing)
#   3. Create venv and install dependencies via uv sync
#   4. Verify installation
#
# Exit Codes:
#   0 - venv created and dependencies installed successfully
#   1 - Failed to create venv or install dependencies
#
# What uv sync Does:
#   - Reads pyproject.toml for dependencies
#   - Uses uv.lock for deterministic versions
#   - Creates .venv/ automatically
#   - Installs all packages
#   - Much faster than pip install -r requirements.txt
#
# Why Keep requirements.txt:
#   - Required for Databricks App deployment
#   - Fallback for users without uv
#   - Can be regenerated from uv.lock if needed
# =============================================================================

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get project root (parent of quickstart directory)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# Ensure Homebrew Python 3.11 is in PATH (if installed)
if [[ -d "/opt/homebrew/opt/python@3.11/libexec/bin" ]]; then
    export PATH="/opt/homebrew/opt/python@3.11/libexec/bin:$PATH"
elif [[ -d "/usr/local/opt/python@3.11/libexec/bin" ]]; then
    export PATH="/usr/local/opt/python@3.11/libexec/bin:$PATH"
fi

echo "Setting up Python environment..."
echo ""

# Show which Python will be used
PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "unknown")
echo -e "${BLUE}Using Python: ${NC}$(which python3) (version $PYTHON_VERSION)"
echo ""

# =============================================================================
# 1. Check for existing .venv (lines 268-282)
# =============================================================================
if [ -d ".venv" ]; then
    echo -e "${YELLOW}⚠️  Virtual environment already exists at .venv/${NC}"
    read -p "Recreate it? (will delete existing) (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${BLUE}→ Removing existing .venv...${NC}"
        rm -rf .venv
    else
        echo -e "${BLUE}→ Using existing .venv${NC}"
        
        # Still verify it works
        source .venv/bin/activate
        if python -c "import fastapi; import sqlalchemy; import alembic" 2>/dev/null; then
            echo -e "${GREEN}✓ Existing environment is valid${NC}"
            exit 0
        else
            echo -e "${YELLOW}⚠ Existing environment may be incomplete${NC}"
            echo "  Consider recreating: rm -rf .venv && ./quickstart/create_python_environment.sh"
            exit 0
        fi
    fi
fi

# =============================================================================
# 2. Check for uv (lines 284-291)
# =============================================================================
echo -e "${BLUE}Checking for uv...${NC}"

# Add common user bin paths to PATH
export PATH="$HOME/.local/bin:$HOME/Library/Python/3.9/bin:$HOME/Library/Python/3.11/bin:$PATH"

if ! command -v uv &> /dev/null; then
    echo -e "${YELLOW}ℹ️  uv not found - installing for faster dependency management...${NC}"
    
    # Use the official installer (recommended)
    curl -LsSf https://astral.sh/uv/install.sh | sh
    
    # Add uv to PATH for this session
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    
    if command -v uv &> /dev/null; then
        UV_VERSION=$(uv --version)
        echo -e "${GREEN}✓ $UV_VERSION installed${NC}"
    else
        echo -e "${RED}✗ Failed to install uv${NC}"
        echo "Please install uv manually: https://github.com/astral-sh/uv"
        exit 1
    fi
else
    UV_VERSION=$(uv --version)
    echo -e "${GREEN}✓ $UV_VERSION${NC}"
fi

# =============================================================================
# 3. Create venv and install dependencies (lines 293-310)
# =============================================================================
echo ""
echo -e "${BLUE}→ Creating virtual environment and installing dependencies...${NC}"
echo "  (This uses uv for 10-100x faster installation)"
echo ""

# Use uv sync with explicit Python version to avoid system Python issues
# This ensures we use Python 3.11+ even if 'python3' points to an older version
if command -v python3.11 &> /dev/null; then
    echo -e "${BLUE}→ Using Python 3.11 explicitly${NC}"
    uv sync --python 3.11
elif command -v python3.10 &> /dev/null; then
    echo -e "${BLUE}→ Using Python 3.10 explicitly${NC}"
    uv sync --python 3.10
else
    # Fall back to default python3
    uv sync
fi

if [ $? -ne 0 ]; then
    echo ""
    echo -e "${RED}❌ Failed to create Python environment${NC}"
    echo ""
    echo "Troubleshooting:"
    echo "  - Ensure Python 3.10+ is installed: brew install python@3.11"
    echo "  - Check pyproject.toml exists and is valid"
    echo "  - Check uv.lock exists"
    echo "  - Try manually: uv sync --python 3.11 --verbose"
    exit 1
fi

echo ""
echo -e "${GREEN}✓ Dependencies installed${NC}"

# =============================================================================
# 4. Verify installation (lines 312-334)
# =============================================================================
echo ""
echo -e "${BLUE}→ Verifying installation...${NC}"

# Activate venv
source .venv/bin/activate

# Test critical imports
if python -c "import fastapi; import sqlalchemy; import alembic" 2>/dev/null; then
    echo -e "${GREEN}✓ Core packages verified (fastapi, sqlalchemy, alembic)${NC}"
else
    echo -e "${RED}❌ Dependency verification failed${NC}"
    echo ""
    echo "Some packages may not have installed correctly."
    echo "Try:"
    echo "  rm -rf .venv"
    echo "  ./quickstart/create_python_environment.sh"
    exit 1
fi

# Additional verification for key packages
if python -c "import psycopg2" 2>/dev/null; then
    echo -e "${GREEN}✓ psycopg2 verified (PostgreSQL driver)${NC}"
else
    echo -e "${YELLOW}⚠ psycopg2 not found - installing PostgreSQL driver...${NC}"
    pip install psycopg2-binary
    if python -c "import psycopg2" 2>/dev/null; then
        echo -e "${GREEN}✓ psycopg2-binary installed${NC}"
    else
        echo -e "${RED}✗ Failed to install psycopg2 - database operations may fail${NC}"
    fi
fi

if python -c "import langchain" 2>/dev/null; then
    echo -e "${GREEN}✓ langchain verified${NC}"
else
    echo -e "${YELLOW}⚠ langchain not found${NC}"
fi

echo ""
echo -e "${GREEN}✓ Python environment ready!${NC}"
echo ""
echo "Tip: Activate manually with: source .venv/bin/activate"

exit 0

