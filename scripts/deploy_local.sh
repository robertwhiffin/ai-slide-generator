#!/bin/bash

# AI Slide Generator - Local Development Deployment Script
# Builds wheels locally and deploys to Databricks Apps

set -e

# Color codes for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# Show usage
usage() {
    echo "Usage: $0 <action> --env <environment> --profile <databricks-profile> [options]"
    echo ""
    echo "Actions:"
    echo "  create    Create a new Databricks App"
    echo "  update    Update an existing Databricks App"
    echo "  delete    Delete a Databricks App"
    echo ""
    echo "Required Arguments:"
    echo "  --env <environment>    Environment: development, staging, or production"
    echo "  --profile <profile>    Databricks CLI profile from ~/.databrickscfg"
    echo ""
    echo "Options:"
    echo "  --reset-db                   Drop and recreate database tables (WARNING: deletes all data)"
    echo "  --include-databricks-prompts Include Databricks-specific deck prompts and brand style"
    echo "  --skip-build                 Skip wheel build (use existing wheels in dist/)"
    echo "  -h, --help                   Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 create --env development --profile my-profile"
    echo "  $0 update --env development --profile my-profile"
    echo "  $0 update --env development --profile my-profile --reset-db"
    echo "  $0 update --env staging --profile my-profile --skip-build"
    echo "  $0 delete --env development --profile my-profile"
    exit 1
}

# Parse arguments
ACTION=""
ENV=""
PROFILE=""
RESET_DB=""
INCLUDE_DB_PROMPTS=""
SKIP_BUILD=""

while [[ $# -gt 0 ]]; do
    case $1 in
        create|update|delete)
            ACTION="$1"
            shift
            ;;
        --env)
            ENV="$2"
            shift 2
            ;;
        --profile)
            PROFILE="$2"
            shift 2
            ;;
        --reset-db)
            RESET_DB="--reset-db"
            shift
            ;;
        --include-databricks-prompts)
            INCLUDE_DB_PROMPTS="--include-databricks-prompts"
            shift
            ;;
        --skip-build)
            SKIP_BUILD="true"
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo -e "${RED}Unknown argument: $1${NC}"
            echo ""
            usage
            ;;
    esac
done

# Validate required arguments
if [ -z "$ACTION" ]; then
    echo -e "${RED}Missing action (create, update, or delete)${NC}"
    echo ""
    usage
fi

if [ -z "$ENV" ]; then
    echo -e "${RED}Missing --env argument${NC}"
    echo ""
    usage
fi

if [ -z "$PROFILE" ]; then
    echo -e "${RED}Missing --profile argument${NC}"
    echo ""
    usage
fi

# Validate environment
if [[ ! "$ENV" =~ ^(development|staging|production)$ ]]; then
    echo -e "${RED}Invalid environment: $ENV${NC}"
    echo "   Valid options: development, staging, production"
    exit 1
fi

# Safety check for production
if [[ "$ENV" == "production" ]]; then
    echo -e "${YELLOW}WARNING: You are deploying to PRODUCTION${NC}"
    echo ""
    read -p "Type 'PRODUCTION' to confirm: " confirm
    if [[ "$confirm" != "PRODUCTION" ]]; then
        echo -e "${RED}Aborted.${NC}"
        exit 1
    fi
    echo ""
fi

echo -e "${BLUE}AI Slide Generator - Local Development Deployment${NC}"
echo ""
echo "  Action:      $ACTION"
echo "  Environment: $ENV"
echo "  Profile:     $PROFILE"
if [ -n "$RESET_DB" ]; then
    echo "  Reset DB:    yes"
fi
if [ -n "$INCLUDE_DB_PROMPTS" ]; then
    echo "  DB Prompts:  yes"
fi
if [ -n "$SKIP_BUILD" ]; then
    echo "  Skip Build:  yes"
fi
echo ""

# Check if .venv exists
if [ ! -d ".venv" ]; then
    echo -e "${RED}Virtual environment not found${NC}"
    echo ""
    echo "Please run the setup first:"
    echo -e "  ${BLUE}./quickstart/setup.sh${NC}"
    echo ""
    exit 1
fi

# Activate virtual environment
echo -e "${BLUE}Activating virtual environment...${NC}"
source .venv/bin/activate
echo -e "${GREEN}Virtual environment activated${NC}"
echo ""

# Step 1: Build wheels (unless skipped or deleting)
if [[ "$ACTION" != "delete" && -z "$SKIP_BUILD" ]]; then
    echo -e "${BLUE}Step 1: Building wheels...${NC}"
    echo ""
    
    "$SCRIPT_DIR/build_wheels.sh"
    
    echo ""
else
    if [[ -n "$SKIP_BUILD" ]]; then
        echo -e "${YELLOW}Skipping wheel build (--skip-build)${NC}"
    fi
    if [[ "$ACTION" == "delete" ]]; then
        echo -e "${BLUE}Skipping wheel build (delete action)${NC}"
    fi
    echo ""
fi

# Step 2: Run Python deployment
echo -e "${BLUE}Step 2: Running deployment...${NC}"
echo ""

python -m scripts.deploy_local \
    --$ACTION \
    --env "$ENV" \
    --profile "$PROFILE" \
    $RESET_DB \
    $INCLUDE_DB_PROMPTS

echo ""
echo -e "${GREEN}Done!${NC}"
