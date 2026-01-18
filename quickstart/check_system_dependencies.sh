#!/bin/bash

# AI Slide Generator - System Dependency Checker
# Verifies and optionally installs system dependencies on macOS

set -e

# Color codes for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Arrays to track issues
MISSING_DEPS=()
ENV_WARNINGS=()

# Get project root directory
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# First thing - verify macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    echo -e "${RED}❌ This quickstart script is designed for macOS only${NC}"
    echo ""
    echo "For other platforms, install manually and run:"
    echo "  ./quickstart/create_python_environment.sh"
    echo "  ./quickstart/setup_database.sh"
    echo ""
    exit 1
fi

echo "Checking system dependencies..."
echo ""

# ============================================================================
# 1. Check Homebrew
# ============================================================================
echo -e "${BLUE}Checking Homebrew...${NC}"
if ! command -v brew &> /dev/null; then
    echo -e "${RED}✗ Homebrew not found${NC}"
    echo ""
    read -p "Install Homebrew? (required for automated setup) (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${BLUE}→ Installing Homebrew...${NC}"
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        
        # Add Homebrew to PATH for current session
        if [[ -f "/opt/homebrew/bin/brew" ]]; then
            # M1/M2 Mac
            eval "$(/opt/homebrew/bin/brew shellenv)"
        elif [[ -f "/usr/local/bin/brew" ]]; then
            # Intel Mac
            eval "$(/usr/local/bin/brew shellenv)"
        fi
        
        # Verify installation
        if command -v brew &> /dev/null; then
            echo -e "${GREEN}✓ Homebrew installed${NC}"
        else
            echo -e "${RED}✗ Homebrew installation failed${NC}"
            echo "Please install manually from https://brew.sh"
            MISSING_DEPS+=("Homebrew (required)")
        fi
    else
        echo -e "${YELLOW}→ Skipping Homebrew installation${NC}"
        MISSING_DEPS+=("Homebrew (required for remaining setup)")
        # Can't continue without Homebrew
        echo ""
        echo -e "${RED}❌ Homebrew is required to install other dependencies${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓ Homebrew found${NC}"
fi

echo ""

# ============================================================================
# 2. Check Python 3.10+
# ============================================================================
echo -e "${BLUE}Checking Python 3.10+...${NC}"
PYTHON_OK=false

if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
    PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)
    
    if [ "$PYTHON_MAJOR" -ge 3 ] && [ "$PYTHON_MINOR" -ge 10 ]; then
        echo -e "${GREEN}✓ Python $PYTHON_VERSION found${NC}"
        PYTHON_OK=true
    else
        echo -e "${RED}✗ Python $PYTHON_VERSION found (need 3.10+)${NC}"
    fi
else
    echo -e "${RED}✗ Python not found${NC}"
fi

if [ "$PYTHON_OK" = false ]; then
    echo ""
    read -p "Install Python 3.11 via Homebrew? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${BLUE}→ Installing Python 3.11...${NC}"
        brew install python@3.11
        
        # Verify installation
        if command -v python3 &> /dev/null; then
            PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
            echo -e "${GREEN}✓ Python $PYTHON_VERSION installed${NC}"
            PYTHON_OK=true
        else
            echo -e "${RED}✗ Python installation failed${NC}"
            MISSING_DEPS+=("Python 3.10+")
        fi
    else
        echo -e "${YELLOW}→ Skipping Python installation${NC}"
        MISSING_DEPS+=("Python 3.10+")
    fi
fi

echo ""

# ============================================================================
# 3. Check PostgreSQL 14+
# ============================================================================
echo -e "${BLUE}Checking PostgreSQL 14+...${NC}"
POSTGRES_OK=false

if command -v psql &> /dev/null; then
    POSTGRES_VERSION=$(psql --version | grep -oE '[0-9]+' | head -1)
    echo -e "${GREEN}✓ PostgreSQL $POSTGRES_VERSION found${NC}"
    
    # Check if running
    if pg_isready &> /dev/null; then
        echo -e "${GREEN}✓ PostgreSQL is running${NC}"
        POSTGRES_OK=true
    else
        echo -e "${YELLOW}⚠ PostgreSQL installed but not running${NC}"
        echo ""
        read -p "Start PostgreSQL? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo -e "${BLUE}→ Starting PostgreSQL...${NC}"
            brew services start postgresql@14 2>/dev/null || brew services start postgresql
            sleep 2
            
            if pg_isready &> /dev/null; then
                echo -e "${GREEN}✓ PostgreSQL started${NC}"
                POSTGRES_OK=true
            else
                echo -e "${RED}✗ PostgreSQL failed to start${NC}"
                MISSING_DEPS+=("PostgreSQL (not running)")
            fi
        else
            echo -e "${YELLOW}→ PostgreSQL not started${NC}"
            MISSING_DEPS+=("PostgreSQL (not running)")
        fi
    fi
else
    echo -e "${RED}✗ PostgreSQL not found${NC}"
    echo ""
    read -p "Install PostgreSQL 14 via Homebrew? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${BLUE}→ Installing PostgreSQL 14...${NC}"
        brew install postgresql@14
        
        echo -e "${BLUE}→ Starting PostgreSQL...${NC}"
        brew services start postgresql@14
        sleep 2
        
        # Verify installation
        if command -v psql &> /dev/null && pg_isready &> /dev/null; then
            POSTGRES_VERSION=$(psql --version | grep -oE '[0-9]+' | head -1)
            echo -e "${GREEN}✓ PostgreSQL $POSTGRES_VERSION installed and running${NC}"
            POSTGRES_OK=true
        else
            echo -e "${RED}✗ PostgreSQL installation or startup failed${NC}"
            MISSING_DEPS+=("PostgreSQL 14+")
        fi
    else
        echo -e "${YELLOW}→ Skipping PostgreSQL installation${NC}"
        MISSING_DEPS+=("PostgreSQL 14+")
    fi
fi

echo ""

# ============================================================================
# 4. Check Node.js 18+
# ============================================================================
echo -e "${BLUE}Checking Node.js 18+...${NC}"
NODE_OK=false

if command -v node &> /dev/null; then
    NODE_VERSION=$(node --version | grep -oE '[0-9]+' | head -1)
    
    if [ "$NODE_VERSION" -ge 18 ]; then
        echo -e "${GREEN}✓ Node.js v$NODE_VERSION found${NC}"
        NODE_OK=true
    else
        echo -e "${RED}✗ Node.js v$NODE_VERSION found (need 18+)${NC}"
    fi
else
    echo -e "${RED}✗ Node.js not found${NC}"
fi

if [ "$NODE_OK" = false ]; then
    echo ""
    read -p "Install Node.js via Homebrew? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${BLUE}→ Installing Node.js...${NC}"
        brew install node
        
        # Verify installation
        if command -v node &> /dev/null; then
            NODE_VERSION=$(node --version | grep -oE '[0-9]+' | head -1)
            echo -e "${GREEN}✓ Node.js v$NODE_VERSION installed${NC}"
            NODE_OK=true
        else
            echo -e "${RED}✗ Node.js installation failed${NC}"
            MISSING_DEPS+=("Node.js 18+")
        fi
    else
        echo -e "${YELLOW}→ Skipping Node.js installation${NC}"
        MISSING_DEPS+=("Node.js 18+")
    fi
fi

# Check npm
if command -v npm &> /dev/null; then
    NPM_VERSION=$(npm --version)
    echo -e "${GREEN}✓ npm v$NPM_VERSION found${NC}"
else
    echo -e "${YELLOW}⚠ npm not found (should come with Node.js)${NC}"
    if [ "$NODE_OK" = true ]; then
        MISSING_DEPS+=("npm (unexpected)")
    fi
fi

echo ""

# ============================================================================
# 5. Check .env File (Warning Only)
# ============================================================================
echo -e "${BLUE}Checking .env configuration...${NC}"

if [ ! -f .env ]; then
    echo -e "${YELLOW}⚠️  .env file not found${NC}"
    ENV_WARNINGS+=(".env file missing (can be configured later)")
else
    echo -e "${GREEN}✓ .env file exists${NC}"
    
    # Check DATABRICKS_HOST
    if ! grep -q "^DATABRICKS_HOST=.\\+" .env; then
        echo -e "${YELLOW}⚠️  DATABRICKS_HOST not set${NC}"
        ENV_WARNINGS+=("DATABRICKS_HOST not configured")
    else
        echo -e "${GREEN}✓ DATABRICKS_HOST is set${NC}"
    fi
    
    # Check DATABRICKS_TOKEN
    if ! grep -q "^DATABRICKS_TOKEN=.\\+" .env; then
        echo -e "${YELLOW}⚠️  DATABRICKS_TOKEN not set${NC}"
        ENV_WARNINGS+=("DATABRICKS_TOKEN not configured")
    else
        echo -e "${GREEN}✓ DATABRICKS_TOKEN is set${NC}"
    fi
fi

echo ""

# ============================================================================
# Final Summary
# ============================================================================
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

if [ ${#MISSING_DEPS[@]} -eq 0 ]; then
    echo -e "${GREEN}✅ All system dependencies satisfied!${NC}"
    echo ""
    
    if [ ${#ENV_WARNINGS[@]} -gt 0 ]; then
        echo -e "${YELLOW}⚠️  Environment configuration warnings:${NC}"
        for warning in "${ENV_WARNINGS[@]}"; do
            echo -e "   - $warning"
        done
        echo ""
        echo "Note: These can be configured later before running the app."
        echo ""
    fi
    
    exit 0
else
    echo -e "${RED}❌ Missing required dependencies:${NC}"
    for dep in "${MISSING_DEPS[@]}"; do
        echo -e "   - $dep"
    done
    echo ""
    
    if [ ${#ENV_WARNINGS[@]} -gt 0 ]; then
        echo -e "${YELLOW}⚠️  Environment configuration warnings:${NC}"
        for warning in "${ENV_WARNINGS[@]}"; do
            echo -e "   - $warning"
        done
        echo ""
    fi
    
    exit 1
fi


