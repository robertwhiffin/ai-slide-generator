#!/bin/bash

# Build wheels for local development deployment
# This script builds both databricks-tellr and databricks-tellr-app packages
# without uploading to PyPI.

set -euo pipefail

# Color codes for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Get project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PACKAGES_DIR="$ROOT_DIR/packages"

TELLR_DIR="$PACKAGES_DIR/databricks-tellr"
APP_DIR="$PACKAGES_DIR/databricks-tellr-app"

echo -e "${BLUE}Building wheels for local deployment...${NC}"
echo ""

# Validate directories exist
if [[ ! -d "$TELLR_DIR" || ! -d "$APP_DIR" ]]; then
    echo -e "${RED}Missing packages directory structure.${NC}"
    echo "Expected:"
    echo "  $TELLR_DIR"
    echo "  $APP_DIR"
    exit 1
fi

# Activate virtual environment if not active
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    if [[ -d "$ROOT_DIR/.venv" ]]; then
        echo -e "${BLUE}Activating virtual environment...${NC}"
        # shellcheck disable=SC1091
        source "$ROOT_DIR/.venv/bin/activate"
    else
        echo -e "${RED}No virtual environment detected.${NC}"
        echo "Create .venv or activate a venv before building."
        exit 1
    fi
fi

# Ensure build package is available
if ! python -m build --version >/dev/null 2>&1; then
    echo -e "${BLUE}Installing build package...${NC}"
    if command -v uv >/dev/null 2>&1; then
        uv pip install build
    else
        python -m pip install build
    fi
fi

# Clean previous builds
echo -e "${BLUE}Cleaning previous builds...${NC}"
rm -rf "$TELLR_DIR/dist" "$APP_DIR/dist"

# Build databricks-tellr package
echo -e "${BLUE}Building databricks-tellr...${NC}"
python -m build --wheel "$TELLR_DIR" --outdir "$TELLR_DIR/dist"

TELLR_WHEEL=$(ls "$TELLR_DIR/dist/"*.whl 2>/dev/null | head -1)
if [[ -z "$TELLR_WHEEL" ]]; then
    echo -e "${RED}Failed to build databricks-tellr wheel${NC}"
    exit 1
fi
echo -e "${GREEN}  Built: $(basename "$TELLR_WHEEL")${NC}"

# Build databricks-tellr-app package
# This requires copying src/ to the app package directory first
# (find_packages runs at import time, before any custom build steps)
echo -e "${BLUE}Building databricks-tellr-app...${NC}"

# Copy src/ to APP_DIR before building
cp -r "$ROOT_DIR/src" "$APP_DIR/src"

# Set up cleanup trap
cleanup_src() {
    rm -rf "$APP_DIR/src"
}
trap cleanup_src EXIT

python -m build --wheel "$APP_DIR" --outdir "$APP_DIR/dist"

# Clean up copied src/ directory
rm -rf "$APP_DIR/src"
trap - EXIT

APP_WHEEL=$(ls "$APP_DIR/dist/"*.whl 2>/dev/null | head -1)
if [[ -z "$APP_WHEEL" ]]; then
    echo -e "${RED}Failed to build databricks-tellr-app wheel${NC}"
    exit 1
fi
echo -e "${GREEN}  Built: $(basename "$APP_WHEEL")${NC}"

echo ""
echo -e "${GREEN}Build complete!${NC}"
echo ""
echo "Wheel locations:"
echo "  databricks-tellr:     $TELLR_WHEEL"
echo "  databricks-tellr-app: $APP_WHEEL"

# Output paths for use by other scripts (can be captured with $())
# Format: TELLR_WHEEL=path APP_WHEEL=path
echo ""
echo "# Export for scripts:"
echo "export TELLR_WHEEL=\"$TELLR_WHEEL\""
echo "export APP_WHEEL=\"$APP_WHEEL\""
