#!/bin/bash

# AI Slide Generator - Python Environment Setup
# Creates virtual environment and installs dependencies using uv

set -e

# Color codes for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Get project root directory
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "Setting up Python environment..."
echo ""

# ============================================================================
# 1. Check for existing .venv
# ============================================================================
if [ -d ".venv" ]; then
    echo -e "${YELLOW}⚠️  Virtual environment already exists at .venv/${NC}"
    echo ""
    read -p "Recreate it? (will delete existing) (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${BLUE}→ Removing existing .venv...${NC}"
        rm -rf .venv
        echo -e "${GREEN}✓ Removed${NC}"
    else
        echo -e "${GREEN}→ Using existing .venv${NC}"
        echo ""
        echo -e "${GREEN}✅ Python environment ready${NC}"
        echo ""
        echo "Tip: Activate with:"
        echo -e "  ${BLUE}source .venv/bin/activate${NC}"
        echo ""
        exit 0
    fi
    echo ""
fi

# ============================================================================
# 2. Check for uv
# ============================================================================
echo -e "${BLUE}Checking for uv...${NC}"

# Add common pip install locations to PATH
export PATH="$HOME/.local/bin:$PATH"

if ! command -v uv &> /dev/null; then
    echo -e "${YELLOW}ℹ️  uv not found - installing for faster dependency management...${NC}"
    pip3 install --user uv
    echo -e "${GREEN}✓ uv installed${NC}"
    
    # Make sure uv is available in PATH after installation
    export PATH="$HOME/.local/bin:$PATH"
    hash -r  # Clear bash's command cache
    
    # Verify uv is now available
    if ! command -v uv &> /dev/null; then
        echo -e "${RED}❌ uv installation succeeded but command not found${NC}"
        echo "Trying to locate uv..."
        # Try to find uv in common locations
        UV_PATH=$(python3 -c "import site; print(site.USER_BASE)" 2>/dev/null)/bin/uv
        if [ -f "$UV_PATH" ]; then
            echo -e "${YELLOW}Found uv at: $UV_PATH${NC}"
            export PATH="$(dirname $UV_PATH):$PATH"
        else
            echo -e "${RED}Could not locate uv. You may need to add it to your PATH manually.${NC}"
            exit 1
        fi
    fi
else
    echo -e "${GREEN}✓ uv found${NC}"
fi

echo ""

# ============================================================================
# 3. Create venv and install dependencies
# ============================================================================
echo -e "${BLUE}→ Creating virtual environment and installing dependencies...${NC}"
echo "  (This uses uv for 10-100x faster installation)"
echo ""

# Try uv command directly, fall back to python -m uv if needed
if command -v uv &> /dev/null; then
    UV_CMD="uv"
else
    echo -e "${YELLOW}Using python3 -m uv (uv not in PATH)${NC}"
    UV_CMD="python3 -m uv"
fi

if $UV_CMD sync --all-extras; then
    echo ""
    echo -e "${GREEN}✓ Dependencies installed (including dev tools)${NC}"
else
    echo ""
    echo -e "${RED}❌ Failed to create Python environment${NC}"
    echo ""
    echo "Troubleshooting:"
    echo "  - Check that requirements.txt exists"
    echo "  - Check that pyproject.toml is valid"
    echo "  - Try: pip3 install --user uv --upgrade"
    echo "  - Or manually add ~/.local/bin to your PATH"
    echo ""
    exit 1
fi

echo ""

# ============================================================================
# 4. Verify installation
# ============================================================================
echo -e "${BLUE}→ Verifying installation...${NC}"

# Activate venv
source .venv/bin/activate

# Test critical imports
if python -c "import fastapi; import sqlalchemy; import pytest" 2>/dev/null; then
    echo -e "${GREEN}✓ Critical dependencies verified (including dev tools)${NC}"
    echo ""
    echo -e "${GREEN}✅ Python environment ready!${NC}"
    echo ""
    echo "Tip: Activate with:"
    echo -e "  ${BLUE}source .venv/bin/activate${NC}"
    echo ""
    exit 0
else
    echo -e "${RED}❌ Dependency verification failed${NC}"
    echo ""
    echo "Some packages may not have installed correctly."
    echo "Try:"
    echo "  rm -rf .venv"
    echo "  ./quickstart/create_python_environment.sh"
    echo ""
    exit 1
fi


