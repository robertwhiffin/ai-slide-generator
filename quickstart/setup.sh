#!/bin/bash
# =============================================================================
# setup.sh - Master Setup Orchestrator
# =============================================================================
# Purpose: Orchestrate all setup steps in order
# Platform: macOS only
# 
# Flow:
#   1. Print welcome banner
#   2. cd to project root
#   3. Run check_system_dependencies.sh
#   4. Run create_python_environment.sh
#   5. Activate .venv
#   6. Run setup_database.sh
#   7. Print completion banner
#   8. Check .env status
#   9. Print next steps
# =============================================================================

set -e  # Exit on error

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# =============================================================================
# Step 1: Print welcome banner
# =============================================================================
echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                                                              ║${NC}"
echo -e "${BLUE}║          🚀 AI Slide Generator - Setup                       ║${NC}"
echo -e "${BLUE}║                                                              ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "This script will set up your development environment."
echo "Platform: macOS only"
echo ""

# =============================================================================
# Step 2: cd to project root
# =============================================================================
cd "$PROJECT_ROOT"
echo -e "${BLUE}→ Working directory: ${NC}$PROJECT_ROOT"
echo ""

# =============================================================================
# Step 3: Run check_system_dependencies.sh (1/3)
# =============================================================================
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  Step 1/3: Checking System Dependencies${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

if ! "$SCRIPT_DIR/check_system_dependencies.sh"; then
    echo ""
    echo -e "${RED}❌ System dependency check failed${NC}"
    echo ""
    echo "Please resolve the issues above and re-run:"
    echo -e "  ${BLUE}./quickstart/setup.sh${NC}"
    exit 1
fi

echo ""

# =============================================================================
# Step 4: Run create_python_environment.sh (2/3)
# =============================================================================
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  Step 2/3: Setting Up Python Environment${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

if ! "$SCRIPT_DIR/create_python_environment.sh"; then
    echo ""
    echo -e "${RED}❌ Python environment setup failed${NC}"
    echo ""
    echo "Please resolve the issues above and re-run:"
    echo -e "  ${BLUE}./quickstart/setup.sh${NC}"
    exit 1
fi

echo ""

# =============================================================================
# Step 5: Activate .venv
# =============================================================================
echo -e "${BLUE}→ Activating virtual environment...${NC}"
source .venv/bin/activate
echo -e "${GREEN}✓ Virtual environment activated${NC}"
echo ""

# =============================================================================
# Step 6: Run setup_database.sh (3/3)
# =============================================================================
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  Step 3/3: Setting Up Database${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

if ! "$SCRIPT_DIR/setup_database.sh"; then
    echo ""
    echo -e "${RED}❌ Database setup failed${NC}"
    echo ""
    echo "Please resolve the issues above and re-run:"
    echo -e "  ${BLUE}./quickstart/setup.sh${NC}"
    exit 1
fi

echo ""

# =============================================================================
# Step 7: Print completion banner
# =============================================================================
echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                                                              ║${NC}"
echo -e "${GREEN}║          ✅ Setup Complete!                                  ║${NC}"
echo -e "${GREEN}║                                                              ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# =============================================================================
# Step 8: Check .env status
# =============================================================================
ENV_CONFIGURED=true

if [ ! -f .env ]; then
    ENV_CONFIGURED=false
    echo -e "${YELLOW}⚠️  Configuration Required${NC}"
    echo ""
    echo "Create your .env file:"
    echo -e "  ${BLUE}cp .env.example .env${NC}"
    echo -e "  ${BLUE}nano .env${NC}  # or use your preferred editor"
    echo ""
    echo "Required settings:"
    echo "  - DATABRICKS_HOST=https://your-workspace.cloud.databricks.com"
    echo "  - DATABRICKS_TOKEN=your-access-token"
    echo ""
else
    # Check if required variables are set
    if ! grep -q "^DATABRICKS_HOST=.\+" .env 2>/dev/null; then
        ENV_CONFIGURED=false
    fi
    if ! grep -q "^DATABRICKS_TOKEN=.\+" .env 2>/dev/null; then
        ENV_CONFIGURED=false
    fi
    
    if [ "$ENV_CONFIGURED" = false ]; then
        echo -e "${YELLOW}⚠️  Configuration Incomplete${NC}"
        echo ""
        echo "Please update your .env file with:"
        echo "  - DATABRICKS_HOST=https://your-workspace.cloud.databricks.com"
        echo "  - DATABRICKS_TOKEN=your-access-token"
        echo ""
    fi
fi

# =============================================================================
# Step 9: Print next steps
# =============================================================================
echo -e "${BLUE}Next Steps:${NC}"
echo ""

if [ "$ENV_CONFIGURED" = false ]; then
    echo "  1. Configure your .env file (see above)"
    echo "  2. Start the application:"
    echo -e "     ${BLUE}./start_app.sh${NC}"
else
    echo "  Start the application:"
    echo -e "  ${BLUE}./start_app.sh${NC}"
fi

echo ""
echo "The app will be available at:"
echo "  - Frontend: http://localhost:3000"
echo "  - API Docs: http://localhost:8000/docs"
echo ""

exit 0

