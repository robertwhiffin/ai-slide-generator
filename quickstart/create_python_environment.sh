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
if ! command -v uv &> /dev/null; then
    echo -e "${YELLOW}ℹ️  uv not found - installing for faster dependency management...${NC}"
    pip3 install uv
    echo -e "${GREEN}✓ uv installed${NC}"
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

if uv sync --all-extras; then
    echo ""
    echo -e "${GREEN}✓ Dependencies installed (including dev tools)${NC}"
else
    echo ""
    echo -e "${RED}❌ Failed to create Python environment${NC}"
    echo ""
    echo "Troubleshooting:"
    echo "  - Check that requirements.txt exists"
    echo "  - Check that pyproject.toml is valid"
    echo "  - Try: pip3 install uv --upgrade"
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


