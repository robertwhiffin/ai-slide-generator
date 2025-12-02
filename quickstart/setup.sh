#!/bin/bash

# AI Slide Generator - Master Setup Script
# One-command setup for macOS

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

echo ""
echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║         AI Slide Generator - Automated Setup              ║${NC}"
echo -e "${BLUE}║                    macOS Only                              ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "This script will:"
echo "  1. Check and install system dependencies (Homebrew, Python, PostgreSQL, Node.js)"
echo "  2. Create Python virtual environment using uv"
echo "  3. Setup PostgreSQL database and run migrations"
echo ""
echo -e "${YELLOW}Note: You will be prompted before any installations.${NC}"
echo ""
read -p "Continue? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Setup cancelled."
    exit 0
fi

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  Step 1/3: Checking System Dependencies${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

if ! ./quickstart/check_system_dependencies.sh; then
    echo ""
    echo -e "${RED}❌ System dependency check failed${NC}"
    echo ""
    echo "Please install missing dependencies and try again."
    exit 1
fi

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  Step 2/3: Creating Python Environment${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

if ! ./quickstart/create_python_environment.sh; then
    echo ""
    echo -e "${RED}❌ Python environment setup failed${NC}"
    echo ""
    echo "Please check the error messages above and try again."
    exit 1
fi

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  Step 3/3: Setting up Database${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Activate venv for database setup
source .venv/bin/activate

if ! ./quickstart/setup_database.sh; then
    echo ""
    echo -e "${RED}❌ Database setup failed${NC}"
    echo ""
    echo "Please check the error messages above and try again."
    exit 1
fi

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║            Setup Completed Successfully! 🎉               ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check .env status
if [ ! -f .env ]; then
    echo -e "${YELLOW}⚠️  Configuration Required${NC}"
    echo ""
    echo "Before starting the app, you need to configure Databricks credentials:"
    echo ""
    echo "  1. Copy the example file:"
    echo -e "     ${BLUE}cp .env.example .env${NC}"
    echo ""
    echo "  2. Edit and set your credentials:"
    echo -e "     ${BLUE}nano .env${NC}"
    echo ""
    echo "     Required values:"
    echo "     - DATABRICKS_HOST=https://your-workspace.cloud.databricks.com"
    echo "     - DATABRICKS_TOKEN=your-token-here"
    echo ""
elif ! grep -q "^DATABRICKS_HOST=.\\+" .env || ! grep -q "^DATABRICKS_TOKEN=.\\+" .env; then
    echo -e "${YELLOW}⚠️  Configuration Incomplete${NC}"
    echo ""
    echo "Please complete your .env configuration:"
    echo -e "  ${BLUE}nano .env${NC}"
    echo ""
    echo "Required values:"
    echo "  - DATABRICKS_HOST=https://your-workspace.cloud.databricks.com"
    echo "  - DATABRICKS_TOKEN=your-token-here"
    echo ""
fi

echo -e "${BLUE}Next Steps:${NC}"
echo ""
echo "  Start the application:"
echo -e "    ${GREEN}./start_app.sh${NC}"
echo ""
echo "  This will open:"
echo "    - Frontend: http://localhost:3000"
echo "    - API Docs: http://localhost:8000/docs"
echo ""


