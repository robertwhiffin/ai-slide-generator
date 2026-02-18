#!/bin/bash

# Build wheels for local development deployment
# This script builds both databricks-tellr and databricks-tellr-app packages
# without uploading to PyPI.
#
# For local development, a .dev{timestamp} suffix is added to ensure each build
# has a unique version, preventing pip cache issues on Databricks Apps.

set -euo pipefail

# Color codes for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# Get project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PACKAGES_DIR="$ROOT_DIR/packages"

TELLR_DIR="$PACKAGES_DIR/databricks-tellr"
APP_DIR="$PACKAGES_DIR/databricks-tellr-app"

# Generate unique dev version suffix using epoch timestamp
DEV_SUFFIX=".dev$(date +%s)"

echo -e "${BLUE}Building wheels for local deployment...${NC}"
echo -e "${YELLOW}Dev version suffix: ${DEV_SUFFIX}${NC}"
echo ""

# Validate directories exist
if [[ ! -d "$TELLR_DIR" || ! -d "$APP_DIR" ]]; then
    echo -e "${RED}Missing packages directory structure.${NC}"
    echo "Expected:"
    echo "  $TELLR_DIR"
    echo "  $APP_DIR"
    exit 1
fi

# Function to get current version from pyproject.toml
get_version() {
    local pyproject="$1"
    grep -E '^version = "' "$pyproject" | sed 's/version = "\(.*\)"/\1/'
}

# Function to set version in pyproject.toml
set_version() {
    local pyproject="$1"
    local new_version="$2"
    if [[ "$(uname)" == "Darwin" ]]; then
        # macOS sed requires empty string for -i
        sed -i '' "s/^version = \".*\"/version = \"$new_version\"/" "$pyproject"
    else
        sed -i "s/^version = \".*\"/version = \"$new_version\"/" "$pyproject"
    fi
}

# Store original versions
TELLR_PYPROJECT="$TELLR_DIR/pyproject.toml"
APP_PYPROJECT="$APP_DIR/pyproject.toml"
TELLR_ORIG_VERSION=$(get_version "$TELLR_PYPROJECT")
APP_ORIG_VERSION=$(get_version "$APP_PYPROJECT")

# Function to restore original versions (used in cleanup)
restore_versions() {
    echo -e "${BLUE}Restoring original versions...${NC}"
    set_version "$TELLR_PYPROJECT" "$TELLR_ORIG_VERSION"
    set_version "$APP_PYPROJECT" "$APP_ORIG_VERSION"
}

# Set up cleanup trap to always restore versions
cleanup() {
    restore_versions
    rm -rf "$APP_DIR/src" 2>/dev/null || true
}
trap cleanup EXIT

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

# Clean previous builds (including stale frontend assets and setuptools build cache)
echo -e "${BLUE}Cleaning previous builds...${NC}"
rm -rf "$TELLR_DIR/dist" "$TELLR_DIR/build"
rm -rf "$APP_DIR/dist" "$APP_DIR/build"
rm -rf "$ROOT_DIR/frontend/dist"

# Apply dev version suffix to both packages
TELLR_DEV_VERSION="${TELLR_ORIG_VERSION}${DEV_SUFFIX}"
APP_DEV_VERSION="${APP_ORIG_VERSION}${DEV_SUFFIX}"

echo -e "${BLUE}Applying dev versions...${NC}"
echo "  databricks-tellr:     $TELLR_ORIG_VERSION -> $TELLR_DEV_VERSION"
echo "  databricks-tellr-app: $APP_ORIG_VERSION -> $APP_DEV_VERSION"
set_version "$TELLR_PYPROJECT" "$TELLR_DEV_VERSION"
set_version "$APP_PYPROJECT" "$APP_DEV_VERSION"
echo ""

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

python -m build --wheel "$APP_DIR" --outdir "$APP_DIR/dist"

# Clean up copied src/ directory (also done in trap, but do it here for cleanliness)
rm -rf "$APP_DIR/src"

APP_WHEEL=$(ls "$APP_DIR/dist/"*.whl 2>/dev/null | head -1)
if [[ -z "$APP_WHEEL" ]]; then
    echo -e "${RED}Failed to build databricks-tellr-app wheel${NC}"
    exit 1
fi
echo -e "${GREEN}  Built: $(basename "$APP_WHEEL")${NC}"

# Restore original versions before final output (trap will also do this on exit)
restore_versions
trap - EXIT

echo ""
echo -e "${GREEN}Build complete!${NC}"
echo ""
echo "Wheel locations:"
echo "  databricks-tellr:     $TELLR_WHEEL"
echo "  databricks-tellr-app: $APP_WHEEL"
echo ""
echo -e "${YELLOW}Note: Wheels built with dev version suffix for cache-busting.${NC}"
echo -e "${YELLOW}Original versions in pyproject.toml have been restored.${NC}"

# Output paths for use by other scripts (can be captured with $())
# Format: TELLR_WHEEL=path APP_WHEEL=path
echo ""
echo "# Export for scripts:"
echo "export TELLR_WHEEL=\"$TELLR_WHEEL\""
echo "export APP_WHEEL=\"$APP_WHEEL\""
