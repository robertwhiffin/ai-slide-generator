#!/bin/bash
# =============================================================================
# check_system_dependencies.sh - macOS Dependency Checker
# =============================================================================
# Purpose: Verify and optionally install system dependencies
# Platform: macOS only
#
# Checks (in order):
#   1. macOS (required)
#   2. Homebrew (offer to install)
#   3. Python 3.10+ (offer to install)
#   4. PostgreSQL 14+ (offer to install, check if running)
#   5. Node.js 18+ (offer to install)
#   6. .env file (warning only)
#
# Exit Codes:
#   0 - All required dependencies satisfied (.env warnings OK)
#   1 - Missing required dependencies
# =============================================================================

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Arrays to track issues
MISSING_DEPS=()
ENV_WARNINGS=()

# Get project root (parent of quickstart directory)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "Checking system dependencies..."
echo ""

# =============================================================================
# 1. Platform Check - Verify macOS (lines 102-113)
# =============================================================================
if [[ "$OSTYPE" != "darwin"* ]]; then
    echo -e "${RED}❌ This quickstart script is designed for macOS only${NC}"
    echo ""
    echo "For other platforms, install manually and run:"
    echo "  ./quickstart/create_python_environment.sh"
    echo "  ./quickstart/setup_database.sh"
    exit 1
fi
echo -e "${GREEN}✓ macOS detected${NC}"

# =============================================================================
# 2. Homebrew Check (lines 117-127)
# =============================================================================
echo ""
echo -e "${BLUE}Checking Homebrew...${NC}"

if ! command -v brew &> /dev/null; then
    echo -e "${RED}✗ Homebrew not found${NC}"
    read -p "Install Homebrew? (required for automated setup) (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${BLUE}→ Installing Homebrew...${NC}"
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        
        # Add Homebrew to PATH for this session (M1/M2 Macs)
        if [[ -f "/opt/homebrew/bin/brew" ]]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
        elif [[ -f "/usr/local/bin/brew" ]]; then
            eval "$(/usr/local/bin/brew shellenv)"
        fi
        
        if command -v brew &> /dev/null; then
            echo -e "${GREEN}✓ Homebrew installed${NC}"
        else
            echo -e "${RED}✗ Homebrew installation failed${NC}"
            echo "Please install Homebrew manually: https://brew.sh"
            MISSING_DEPS+=("Homebrew")
        fi
    else
        echo -e "${RED}✗ Homebrew is required for automated setup${NC}"
        MISSING_DEPS+=("Homebrew")
    fi
else
    BREW_VERSION=$(brew --version | head -1)
    echo -e "${GREEN}✓ $BREW_VERSION${NC}"
fi

# If Homebrew is missing, we can't install other dependencies
if [[ " ${MISSING_DEPS[*]} " =~ " Homebrew " ]]; then
    echo ""
    echo -e "${RED}❌ Cannot continue without Homebrew${NC}"
    echo "Please install Homebrew first: https://brew.sh"
    exit 1
fi

# =============================================================================
# 3. Python 3.10+ Check (lines 129-146)
# =============================================================================
echo ""
echo -e "${BLUE}Checking Python 3.10+...${NC}"

PYTHON_OK=false

# First check the default python3 (covers most users with 3.10, 3.11, 3.12, etc.)
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PYTHON_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
    PYTHON_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
    
    if [[ "$PYTHON_MAJOR" -ge 3 ]] && [[ "$PYTHON_MINOR" -ge 10 ]]; then
        echo -e "${GREEN}✓ Python $PYTHON_VERSION found${NC}"
        PYTHON_OK=true
    else
        # python3 is too old, but check if Homebrew versions exist
        echo -e "${YELLOW}⚠ Default python3 is $PYTHON_VERSION (need 3.10+)${NC}"
        
        # Check for Homebrew Python (might be installed but not default)
        if command -v python3.11 &> /dev/null; then
            PYTHON_VERSION=$(python3.11 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
            echo -e "${GREEN}✓ Python $PYTHON_VERSION found via Homebrew (python3.11)${NC}"
            PYTHON_OK=true
        elif command -v python3.10 &> /dev/null; then
            PYTHON_VERSION=$(python3.10 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
            echo -e "${GREEN}✓ Python $PYTHON_VERSION found via Homebrew (python3.10)${NC}"
            PYTHON_OK=true
        fi
    fi
else
    echo -e "${RED}✗ Python not found${NC}"
fi

if [ "$PYTHON_OK" = false ]; then
    read -p "Install Python 3.11 via Homebrew? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${BLUE}→ Installing Python 3.11...${NC}"
        brew install python@3.11
        
        # Add Python 3.11 to PATH for this session
        if [[ -d "/opt/homebrew/opt/python@3.11/libexec/bin" ]]; then
            export PATH="/opt/homebrew/opt/python@3.11/libexec/bin:$PATH"
        elif [[ -d "/usr/local/opt/python@3.11/libexec/bin" ]]; then
            export PATH="/usr/local/opt/python@3.11/libexec/bin:$PATH"
        fi
        
        # Verify installation using python3.11 directly
        if command -v python3.11 &> /dev/null; then
            PYTHON_VERSION=$(python3.11 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
            echo -e "${GREEN}✓ Python $PYTHON_VERSION installed${NC}"
            echo -e "${YELLOW}Note: You may need to restart your terminal for 'python3' to use 3.11${NC}"
        else
            echo -e "${RED}✗ Python installation failed${NC}"
            MISSING_DEPS+=("Python 3.10+")
        fi
    else
        MISSING_DEPS+=("Python 3.10+")
    fi
fi

# =============================================================================
# 4. PostgreSQL 14+ Check (lines 148-170)
# =============================================================================
echo ""
echo -e "${BLUE}Checking PostgreSQL 14+...${NC}"

POSTGRES_OK=false
if command -v psql &> /dev/null; then
    PSQL_VERSION=$(psql --version | grep -oE '[0-9]+' | head -1)
    echo -e "${GREEN}✓ PostgreSQL $PSQL_VERSION found${NC}"
    POSTGRES_OK=true
    
    # Check if PostgreSQL is running
    if pg_isready &> /dev/null; then
        echo -e "${GREEN}✓ PostgreSQL is running${NC}"
    else
        echo -e "${YELLOW}⚠ PostgreSQL installed but not running${NC}"
        read -p "Start PostgreSQL? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo -e "${BLUE}→ Starting PostgreSQL...${NC}"
            brew services start postgresql@14 2>/dev/null || brew services start postgresql
            sleep 2
            
            if pg_isready &> /dev/null; then
                echo -e "${GREEN}✓ PostgreSQL started${NC}"
            else
                echo -e "${RED}✗ Failed to start PostgreSQL${NC}"
                MISSING_DEPS+=("PostgreSQL (not running)")
            fi
        else
            MISSING_DEPS+=("PostgreSQL (not running)")
        fi
    fi
else
    echo -e "${RED}✗ PostgreSQL not found${NC}"
    read -p "Install PostgreSQL 14 via Homebrew? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${BLUE}→ Installing PostgreSQL 14...${NC}"
        brew install postgresql@14
        
        echo -e "${BLUE}→ Starting PostgreSQL...${NC}"
        brew services start postgresql@14
        sleep 2
        
        # Add PostgreSQL to PATH
        if [[ -d "/opt/homebrew/opt/postgresql@14/bin" ]]; then
            export PATH="/opt/homebrew/opt/postgresql@14/bin:$PATH"
        elif [[ -d "/usr/local/opt/postgresql@14/bin" ]]; then
            export PATH="/usr/local/opt/postgresql@14/bin:$PATH"
        fi
        
        if pg_isready &> /dev/null; then
            echo -e "${GREEN}✓ PostgreSQL installed and running${NC}"
        else
            echo -e "${YELLOW}⚠ PostgreSQL installed but may need shell restart${NC}"
            echo "  Try: brew services start postgresql@14"
        fi
    else
        MISSING_DEPS+=("PostgreSQL 14+")
    fi
fi

# =============================================================================
# 5. Node.js 18+ Check (lines 172-197)
# =============================================================================
echo ""
echo -e "${BLUE}Checking Node.js 18+...${NC}"

NODE_OK=false
if command -v node &> /dev/null; then
    NODE_VERSION=$(node --version | grep -oE '[0-9]+' | head -1)
    
    if [[ "$NODE_VERSION" -ge 18 ]]; then
        echo -e "${GREEN}✓ Node.js v$NODE_VERSION found${NC}"
        NODE_OK=true
    else
        echo -e "${RED}✗ Node.js v$NODE_VERSION found (need 18+)${NC}"
    fi
else
    echo -e "${RED}✗ Node.js not found${NC}"
fi

if [ "$NODE_OK" = false ]; then
    read -p "Install Node.js 20 via Homebrew? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${BLUE}→ Installing Node.js 20...${NC}"
        brew install node@20
        
        # Add Node to PATH
        if [[ -d "/opt/homebrew/opt/node@20/bin" ]]; then
            export PATH="/opt/homebrew/opt/node@20/bin:$PATH"
        elif [[ -d "/usr/local/opt/node@20/bin" ]]; then
            export PATH="/usr/local/opt/node@20/bin:$PATH"
        fi
        
        if command -v node &> /dev/null; then
            NODE_VERSION=$(node --version)
            echo -e "${GREEN}✓ Node.js $NODE_VERSION installed${NC}"
        else
            echo -e "${RED}✗ Node.js installation failed${NC}"
            MISSING_DEPS+=("Node.js 18+")
        fi
    else
        MISSING_DEPS+=("Node.js 18+")
    fi
fi

# Check npm
if command -v npm &> /dev/null; then
    NPM_VERSION=$(npm --version)
    echo -e "${GREEN}✓ npm v$NPM_VERSION found${NC}"
else
    echo -e "${YELLOW}⚠ npm not found (should come with Node)${NC}"
    MISSING_DEPS+=("npm")
fi

# =============================================================================
# 6. .env File Check - Warning Only (lines 199-225)
# =============================================================================
echo ""
echo -e "${BLUE}Checking .env configuration...${NC}"

if [ ! -f .env ]; then
    echo -e "${YELLOW}⚠️  .env file not found${NC}"
    ENV_WARNINGS+=(".env file not found - create with: cp .env.example .env")
else
    echo -e "${GREEN}✓ .env file exists${NC}"
    
    # Check DATABRICKS_HOST
    if ! grep -q "^DATABRICKS_HOST=.\+" .env; then
        echo -e "${YELLOW}⚠️  DATABRICKS_HOST not set${NC}"
        ENV_WARNINGS+=("DATABRICKS_HOST not set in .env")
    else
        echo -e "${GREEN}✓ DATABRICKS_HOST is set${NC}"
    fi
    
    # Check DATABRICKS_TOKEN
    if ! grep -q "^DATABRICKS_TOKEN=.\+" .env; then
        echo -e "${YELLOW}⚠️  DATABRICKS_TOKEN not set${NC}"
        ENV_WARNINGS+=("DATABRICKS_TOKEN not set in .env")
    else
        echo -e "${GREEN}✓ DATABRICKS_TOKEN is set${NC}"
    fi
fi

# =============================================================================
# Final Summary (lines 227-250)
# =============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ ${#MISSING_DEPS[@]} -eq 0 ]; then
    echo -e "${GREEN}✅ All system dependencies satisfied!${NC}"
    
    if [ ${#ENV_WARNINGS[@]} -gt 0 ]; then
        echo ""
        echo -e "${YELLOW}⚠️  Environment configuration warnings:${NC}"
        for warning in "${ENV_WARNINGS[@]}"; do
            echo "  - $warning"
        done
        echo ""
        echo "Note: These can be configured later before running the app."
    fi
    
    exit 0
else
    echo -e "${RED}❌ Missing required dependencies:${NC}"
    for dep in "${MISSING_DEPS[@]}"; do
        echo "  - $dep"
    done
    
    if [ ${#ENV_WARNINGS[@]} -gt 0 ]; then
        echo ""
        echo -e "${YELLOW}⚠️  Environment configuration warnings:${NC}"
        for warning in "${ENV_WARNINGS[@]}"; do
            echo "  - $warning"
        done
    fi
    
    exit 1
fi

