#!/bin/bash
# Setup Databricks secrets for the identity provider
#
# Usage:
#   ./scripts/setup_secrets.sh --profile <databricks-profile>
#
# This script will:
# 1. Create the tellr-secrets scope (if not exists)
# 2. Prompt you to enter the workspace admin token
# 3. Store it securely in Databricks secrets

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

PROFILE=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --profile)
            PROFILE="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 --profile <databricks-profile>"
            echo ""
            echo "Sets up Databricks secrets for the identity provider."
            echo ""
            echo "Arguments:"
            echo "  --profile    Databricks CLI profile from ~/.databrickscfg"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown argument: $1${NC}"
            exit 1
            ;;
    esac
done

if [ -z "$PROFILE" ]; then
    echo -e "${RED}Missing --profile argument${NC}"
    echo "Usage: $0 --profile <databricks-profile>"
    exit 1
fi

echo -e "${BLUE}Databricks Secrets Setup${NC}"
echo ""
echo "Profile: $PROFILE"
echo ""

# Create scope
echo -e "${BLUE}Creating secret scope 'tellr-secrets'...${NC}"
databricks secrets create-scope tellr-secrets --profile "$PROFILE" 2>/dev/null && \
    echo -e "${GREEN}✓ Scope created${NC}" || \
    echo -e "${YELLOW}Scope already exists${NC}"

echo ""
echo -e "${BLUE}Choose identity provider option:${NC}"
echo "  1. Workspace Admin Token (single workspace)"
echo "  2. Account Admin Token (cross-workspace)"
echo "  3. Skip (use local identity table only)"
echo ""
read -p "Enter choice [1-3]: " choice

case $choice in
    1)
        echo ""
        echo -e "${YELLOW}Enter your Workspace Admin PAT:${NC}"
        echo "(Token will not be displayed)"
        read -s token
        echo ""
        
        if [ -z "$token" ]; then
            echo -e "${RED}No token provided. Aborting.${NC}"
            exit 1
        fi
        
        echo "$token" | databricks secrets put-secret tellr-secrets workspace-admin-token --profile "$PROFILE"
        echo -e "${GREEN}✓ Workspace admin token stored${NC}"
        ;;
        
    2)
        echo ""
        read -p "Enter Databricks Account ID: " account_id
        echo -e "${YELLOW}Enter your Account Admin PAT:${NC}"
        echo "(Token will not be displayed)"
        read -s token
        echo ""
        
        if [ -z "$token" ] || [ -z "$account_id" ]; then
            echo -e "${RED}Missing values. Aborting.${NC}"
            exit 1
        fi
        
        echo "$account_id" | databricks secrets put-secret tellr-secrets account-id --profile "$PROFILE"
        echo "$token" | databricks secrets put-secret tellr-secrets account-admin-token --profile "$PROFILE"
        echo -e "${GREEN}✓ Account admin credentials stored${NC}"
        ;;
        
    3)
        echo -e "${YELLOW}Skipped. App will use local identity table only.${NC}"
        ;;
        
    *)
        echo -e "${RED}Invalid choice${NC}"
        exit 1
        ;;
esac

echo ""
echo -e "${BLUE}Current secrets in tellr-secrets:${NC}"
databricks secrets list-secrets tellr-secrets --profile "$PROFILE"

echo ""
echo -e "${GREEN}Done!${NC}"
echo ""
echo "Next steps:"
echo "  1. Uncomment the identity provider option in:"
echo "     packages/databricks-tellr/databricks_tellr/_templates/app.yaml.template"
echo "  2. Redeploy the app:"
echo "     ./scripts/deploy_local.sh update --env development --profile $PROFILE"

