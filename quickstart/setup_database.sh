#!/bin/bash

# AI Slide Generator - Database Setup Script
# Automatically creates PostgreSQL database and runs migrations

set -e

# Color codes for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║        AI Slide Generator - Database Setup                ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Get project root directory
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# Default database name
DB_NAME="ai_slide_generator"

# Check if PostgreSQL is installed
echo -e "${BLUE}➤ Checking PostgreSQL installation...${NC}"
if ! command -v psql &> /dev/null; then
    echo -e "${RED}✗ PostgreSQL is not installed${NC}"
    echo ""
    echo "Please install PostgreSQL first:"
    echo ""
    echo -e "${YELLOW}macOS:${NC}"
    echo "  brew install postgresql@14"
    echo "  brew services start postgresql@14"
    echo ""
    echo -e "${YELLOW}Ubuntu/Debian:${NC}"
    echo "  sudo apt-get update"
    echo "  sudo apt-get install postgresql postgresql-contrib"
    echo "  sudo systemctl start postgresql"
    echo ""
    echo -e "${YELLOW}Windows:${NC}"
    echo "  Download from https://www.postgresql.org/download/windows/"
    echo ""
    exit 1
fi
echo -e "${GREEN}✓ PostgreSQL is installed${NC}"

# Check if PostgreSQL is running
echo -e "${BLUE}➤ Checking if PostgreSQL is running...${NC}"
if ! pg_isready &> /dev/null; then
    echo -e "${YELLOW}⚠ PostgreSQL is not running. Attempting to start...${NC}"
    
    # Try to start PostgreSQL based on OS
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        if brew services list | grep -q postgresql; then
            brew services start postgresql || brew services start postgresql@14
        else
            echo -e "${RED}✗ Could not start PostgreSQL${NC}"
            echo "Please start PostgreSQL manually:"
            echo "  brew services start postgresql@14"
            exit 1
        fi
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        # Linux
        if command -v systemctl &> /dev/null; then
            sudo systemctl start postgresql
        else
            echo -e "${RED}✗ Could not start PostgreSQL${NC}"
            echo "Please start PostgreSQL manually"
            exit 1
        fi
    fi
    
    # Wait a moment for PostgreSQL to start
    sleep 2
    
    # Check again
    if ! pg_isready &> /dev/null; then
        echo -e "${RED}✗ PostgreSQL failed to start${NC}"
        exit 1
    fi
fi
echo -e "${GREEN}✓ PostgreSQL is running${NC}"

# Check if database already exists
echo -e "${BLUE}➤ Checking if database '$DB_NAME' exists...${NC}"
if psql -lqt | cut -d \| -f 1 | grep -qw "$DB_NAME"; then
    echo -e "${YELLOW}⚠ Database '$DB_NAME' already exists${NC}"
    read -p "Do you want to drop and recreate it? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${BLUE}➤ Dropping existing database...${NC}"
        dropdb "$DB_NAME" 2>/dev/null || true
        echo -e "${GREEN}✓ Database dropped${NC}"
    else
        echo -e "${YELLOW}➤ Keeping existing database${NC}"
    fi
fi

# Create database if it doesn't exist
if ! psql -lqt | cut -d \| -f 1 | grep -qw "$DB_NAME"; then
    echo -e "${BLUE}➤ Creating database '$DB_NAME'...${NC}"
    createdb "$DB_NAME"
    echo -e "${GREEN}✓ Database created${NC}"
fi

# Verify database connection
echo -e "${BLUE}➤ Verifying database connection...${NC}"
if psql -d "$DB_NAME" -c "SELECT version();" &> /dev/null; then
    echo -e "${GREEN}✓ Database connection successful${NC}"
else
    echo -e "${RED}✗ Could not connect to database${NC}"
    exit 1
fi

# Update .env file with database URL if it exists
if [ -f .env ]; then
    echo -e "${BLUE}➤ Checking .env configuration...${NC}"
    if grep -q "^DATABASE_URL=" .env; then
        echo -e "${GREEN}✓ DATABASE_URL already set in .env${NC}"
    else
        echo "DATABASE_URL=postgresql://localhost:5432/$DB_NAME" >> .env
        echo -e "${GREEN}✓ Added DATABASE_URL to .env${NC}"
    fi
else
    echo -e "${YELLOW}⚠ No .env file found. Please copy .env.example to .env${NC}"
fi

# Check if virtual environment exists and activate it
if [ -d ".venv" ]; then
    echo -e "${BLUE}➤ Activating virtual environment...${NC}"
    source .venv/bin/activate
    echo -e "${GREEN}✓ Virtual environment activated${NC}"
else
    echo -e "${YELLOW}⚠ Virtual environment not found${NC}"
    echo -e "${YELLOW}  Please run: python3 -m venv .venv && source .venv/bin/activate${NC}"
fi

# Check if alembic is installed
if ! command -v alembic &> /dev/null; then
    echo -e "${YELLOW}⚠ Alembic not installed. Installing dependencies...${NC}"
    pip install -r requirements.txt > /dev/null
    echo -e "${GREEN}✓ Dependencies installed${NC}"
fi

# Run database migrations
echo -e "${BLUE}➤ Running database migrations...${NC}"
export DATABASE_URL="postgresql://localhost:5432/$DB_NAME"
alembic upgrade head
echo -e "${GREEN}✓ Migrations completed${NC}"

# Initialize database with seed profiles from YAML
echo -e "${BLUE}➤ Initializing database with seed profiles...${NC}"
if python scripts/init_database.py; then
    echo -e "${GREEN}✓ Database initialized${NC}"
else
    echo -e "${YELLOW}⚠ Configuration initialization skipped (already initialized)${NC}"
fi

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              Database Setup Complete! 🎉                  ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Database:${NC} $DB_NAME"
echo -e "${BLUE}Connection:${NC} postgresql://localhost:5432/$DB_NAME"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "  1. Ensure your .env file has DATABRICKS_HOST and DATABRICKS_TOKEN set"
echo "  2. Run: ./start_app.sh"
echo ""

