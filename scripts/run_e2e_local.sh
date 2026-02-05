#!/bin/bash
#
# Run E2E tests locally with CI-like database state
#
# Usage:
#   ./scripts/run_e2e_local.sh                     # Run all E2E tests
#   ./scripts/run_e2e_local.sh profile-integration # Run specific test file
#   ./scripts/run_e2e_local.sh --headed            # Run in headed mode
#   ./scripts/run_e2e_local.sh profile-integration --headed
#
# Options:
#   --headed       Run browser in headed mode (visible)
#   --no-reset     Skip database reset (useful for re-running tests)
#   --debug        Enable Playwright debug mode
#
# Prerequisites:
#   - PostgreSQL running locally (will use database: e2e_test_db)
#   - Python environment with dependencies installed
#   - Frontend dependencies installed (npm install in frontend/)
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
DB_NAME="e2e_test_db"
DB_USER="${DB_USER:-$(whoami)}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
BACKEND_PORT=8000
FRONTEND_PORT=3000

# Parse arguments
TEST_FILE=""
HEADED=""
NO_RESET=false
DEBUG=""
EXTRA_ARGS=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --headed)
            HEADED="--headed"
            shift
            ;;
        --no-reset)
            NO_RESET=true
            shift
            ;;
        --debug)
            DEBUG="--debug"
            shift
            ;;
        --*)
            EXTRA_ARGS="$EXTRA_ARGS $1"
            shift
            ;;
        *)
            if [[ -z "$TEST_FILE" ]]; then
                TEST_FILE="$1"
            else
                EXTRA_ARGS="$EXTRA_ARGS $1"
            fi
            shift
            ;;
    esac
done

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}   E2E Test Runner (CI-like setup)${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if PostgreSQL is running
echo -e "${YELLOW}[1/6] Checking PostgreSQL...${NC}"
if ! command -v psql &> /dev/null; then
    echo -e "${RED}Error: psql not found. Please install PostgreSQL.${NC}"
    exit 1
fi

if ! pg_isready -h "$DB_HOST" -p "$DB_PORT" -q 2>/dev/null; then
    echo -e "${RED}Error: PostgreSQL is not running at $DB_HOST:$DB_PORT${NC}"
    echo "Start PostgreSQL with: brew services start postgresql@14"
    exit 1
fi
echo -e "${GREEN}✓ PostgreSQL is running${NC}"

# Create/reset test database
if [[ "$NO_RESET" == false ]]; then
    echo ""
    echo -e "${YELLOW}[2/6] Setting up test database...${NC}"
    
    # Drop and recreate database
    echo "Dropping database $DB_NAME (if exists)..."
    psql -h "$DB_HOST" -p "$DB_PORT" -c "DROP DATABASE IF EXISTS $DB_NAME;" postgres 2>/dev/null || true
    
    echo "Creating database $DB_NAME..."
    psql -h "$DB_HOST" -p "$DB_PORT" -c "CREATE DATABASE $DB_NAME;" postgres
    
    echo -e "${GREEN}✓ Database $DB_NAME created${NC}"
else
    echo ""
    echo -e "${YELLOW}[2/6] Skipping database reset (--no-reset)${NC}"
fi

# Set environment for seeding
export DATABASE_URL="postgresql://$DB_USER@$DB_HOST:$DB_PORT/$DB_NAME"
export ENVIRONMENT="test"
export DATABRICKS_HOST="https://test.databricks.com"
export DATABRICKS_TOKEN="test-token"

# Seed database (same as CI)
if [[ "$NO_RESET" == false ]]; then
    echo ""
    echo -e "${YELLOW}[3/6] Seeding database (CI-like)...${NC}"
    
    python -c "
from src.core.database import init_db, get_db_session
from src.core.init_default_profile import seed_defaults
from src.database.models import ConfigProfile, ConfigAIInfra, ConfigPrompts, SlideStyleLibrary

# Create tables
init_db()
print('  ✓ Tables created')

# Seed deck prompts and slide styles
seed_defaults()
print('  ✓ Default deck prompts and slide styles seeded')

# Create a minimal default profile for E2E tests (same as CI)
with get_db_session() as db:
    existing = db.query(ConfigProfile).filter_by(name='default').first()
    if not existing:
        # Get the first slide style
        style = db.query(SlideStyleLibrary).first()
        style_id = style.id if style else None
        
        # Create profile
        profile = ConfigProfile(
            name='default',
            description='Default test profile',
            is_default=True
        )
        db.add(profile)
        db.flush()
        
        # Create AI infra config
        ai_infra = ConfigAIInfra(
            profile_id=profile.id,
            llm_endpoint='databricks-claude-sonnet',
            llm_temperature=0.7,
            llm_max_tokens=4096
        )
        db.add(ai_infra)
        
        # Create prompts config
        prompts = ConfigPrompts(
            profile_id=profile.id,
            selected_slide_style_id=style_id,
            system_prompt='You are a helpful assistant.',
            slide_editing_instructions='Edit slides as requested.'
        )
        db.add(prompts)
        
        db.commit()
        print(f'  ✓ Created default profile (id={profile.id})')
    else:
        print('  ✓ Default profile already exists')

# Verify seeding
with get_db_session() as db:
    from src.database.models import SlideDeckPromptLibrary
    profiles = db.query(ConfigProfile).count()
    styles = db.query(SlideStyleLibrary).count()
    prompts = db.query(SlideDeckPromptLibrary).count()
    print(f'  Database state: {profiles} profile(s), {styles} style(s), {prompts} deck prompt(s)')
"
    echo -e "${GREEN}✓ Database seeded${NC}"
else
    echo ""
    echo -e "${YELLOW}[3/6] Skipping database seeding (--no-reset)${NC}"
fi

# Kill any existing backend on the port
echo ""
echo -e "${YELLOW}[4/6] Starting backend server...${NC}"
if lsof -ti:$BACKEND_PORT >/dev/null 2>&1; then
    echo "Stopping existing process on port $BACKEND_PORT..."
    kill $(lsof -ti:$BACKEND_PORT) 2>/dev/null || true
    sleep 1
fi

# Start backend
DATABASE_URL="$DATABASE_URL" \
ENVIRONMENT="test" \
DATABRICKS_HOST="https://test.databricks.com" \
DATABRICKS_TOKEN="test-token" \
python -m uvicorn src.api.main:app --host 0.0.0.0 --port $BACKEND_PORT &
BACKEND_PID=$!

# Wait for backend to be ready
echo "Waiting for backend to start..."
for i in {1..30}; do
    if curl -s "http://localhost:$BACKEND_PORT/api/health" > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Backend is ready (PID: $BACKEND_PID)${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${RED}Error: Backend failed to start${NC}"
        kill $BACKEND_PID 2>/dev/null || true
        exit 1
    fi
    sleep 1
done

# Cleanup function
cleanup() {
    echo ""
    echo -e "${YELLOW}Cleaning up...${NC}"
    if [[ -n "$BACKEND_PID" ]]; then
        kill $BACKEND_PID 2>/dev/null || true
        echo "  ✓ Backend stopped"
    fi
}
trap cleanup EXIT

# Verify API endpoints
echo ""
echo -e "${YELLOW}[5/6] Verifying API endpoints...${NC}"
echo -n "  Profiles: "
PROFILES=$(curl -s "http://localhost:$BACKEND_PORT/api/settings/profiles" | python -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('profiles',d)))" 2>/dev/null || echo "ERROR")
echo "$PROFILES profile(s)"

echo -n "  Slide Styles: "
STYLES=$(curl -s "http://localhost:$BACKEND_PORT/api/settings/slide-styles" | python -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('styles',[])))" 2>/dev/null || echo "ERROR")
echo "$STYLES style(s)"

echo -n "  Deck Prompts: "
PROMPTS=$(curl -s "http://localhost:$BACKEND_PORT/api/settings/deck-prompts" | python -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('prompts',[])))" 2>/dev/null || echo "ERROR")
echo "$PROMPTS prompt(s)"
echo -e "${GREEN}✓ API endpoints working${NC}"

# Run tests
echo ""
echo -e "${YELLOW}[6/6] Running E2E tests...${NC}"
cd frontend

# Build test command
TEST_CMD="npx playwright test"
if [[ -n "$TEST_FILE" ]]; then
    TEST_CMD="$TEST_CMD tests/e2e/${TEST_FILE}.spec.ts"
fi
TEST_CMD="$TEST_CMD --project=chromium --workers=1 $HEADED $DEBUG $EXTRA_ARGS"

echo "Running: $TEST_CMD"
echo ""

# Set test environment
export CI=true
export VITE_API_URL="http://127.0.0.1:$BACKEND_PORT"

# Run tests
eval $TEST_CMD
TEST_EXIT_CODE=$?

echo ""
if [[ $TEST_EXIT_CODE -eq 0 ]]; then
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}   All tests passed!${NC}"
    echo -e "${GREEN}========================================${NC}"
else
    echo -e "${RED}========================================${NC}"
    echo -e "${RED}   Tests failed (exit code: $TEST_EXIT_CODE)${NC}"
    echo -e "${RED}========================================${NC}"
    echo ""
    echo "View report: npx playwright show-report (in frontend/)"
fi

exit $TEST_EXIT_CODE
