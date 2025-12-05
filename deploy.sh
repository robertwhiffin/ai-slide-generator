#!/bin/bash

# AI Slide Generator - Deployment Script
# Deploys the app to Databricks Apps

set -e

# Color codes for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get project root directory
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

# Show usage
usage() {
    echo "Usage: $0 <action> --env <environment> --profile <databricks-profile> [--dry-run]"
    echo ""
    echo "Actions:"
    echo "  create    Create a new Databricks App"
    echo "  update    Update an existing Databricks App"
    echo "  delete    Delete a Databricks App"
    echo ""
    echo "Arguments:"
    echo "  --env        Environment: development, staging, or production"
    echo "  --profile    Databricks CLI profile from ~/.databrickscfg"
    echo "  --dry-run    Validate configuration without deploying"
    echo ""
    echo "Examples:"
    echo "  $0 create --env development --profile my-profile"
    echo "  $0 update --env production --profile prod-profile"
    echo "  $0 create --env staging --profile my-profile --dry-run"
    exit 1
}

# Parse arguments
ACTION=""
ENV=""
PROFILE=""
DRY_RUN=""

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
        --dry-run)
            DRY_RUN="--dry-run"
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo -e "${RED}❌ Unknown argument: $1${NC}"
            echo ""
            usage
            ;;
    esac
done

# Validate required arguments
if [ -z "$ACTION" ]; then
    echo -e "${RED}❌ Missing action (create, update, or delete)${NC}"
    echo ""
    usage
fi

if [ -z "$ENV" ]; then
    echo -e "${RED}❌ Missing --env argument${NC}"
    echo ""
    usage
fi

if [ -z "$PROFILE" ]; then
    echo -e "${RED}❌ Missing --profile argument${NC}"
    echo ""
    usage
fi

# Validate environment
if [[ ! "$ENV" =~ ^(development|staging|production)$ ]]; then
    echo -e "${RED}❌ Invalid environment: $ENV${NC}"
    echo "   Valid options: development, staging, production"
    exit 1
fi

echo "🚀 AI Slide Generator Deployment"
echo ""

# Check if .venv exists
if [ ! -d ".venv" ]; then
    echo -e "${RED}❌ Virtual environment not found${NC}"
    echo ""
    echo "Please run the setup first:"
    echo -e "  ${BLUE}./quickstart/setup.sh${NC}"
    echo ""
    exit 1
fi

# Activate virtual environment
echo -e "${BLUE}🔧 Activating virtual environment...${NC}"
source .venv/bin/activate
echo -e "${GREEN}✅ Virtual environment activated${NC}"
echo ""

# Run the deployment
echo -e "${BLUE}📦 Running deployment: $ACTION --env $ENV --profile $PROFILE $DRY_RUN${NC}"
echo ""

python -m db_app_deployment.deploy --$ACTION --env "$ENV" --profile "$PROFILE" $DRY_RUN

