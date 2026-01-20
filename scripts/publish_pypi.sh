#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGES_DIR="$ROOT_DIR/packages"

TELLR_DIR="$PACKAGES_DIR/databricks-tellr"
APP_DIR="$PACKAGES_DIR/databricks-tellr-app"

TWINE_REPOSITORY=""

usage() {
  echo "Usage: $0 [--test]"
  echo ""
  echo "Builds and uploads both packages to PyPI."
  echo "Use --test to upload to TestPyPI."
  exit 1
}

if [[ "${1:-}" == "--test" ]]; then
  TWINE_REPOSITORY="testpypi"
elif [[ "${1:-}" != "" ]]; then
  usage
fi

if [[ ! -d "$TELLR_DIR" || ! -d "$APP_DIR" ]]; then
  echo "Missing packages directory structure."
  exit 1
fi

if [[ -z "${VIRTUAL_ENV:-}" ]]; then
  if [[ -d "$ROOT_DIR/.venv" ]]; then
    # shellcheck disable=SC1091
    source "$ROOT_DIR/.venv/bin/activate"
  else
    echo "No virtual environment detected."
    echo "Create .venv or activate a venv before publishing."
    exit 1
  fi
fi

if ! python -m twine --version >/dev/null 2>&1; then
  if command -v uv >/dev/null 2>&1; then
    uv pip install twine
  else
    python -m pip install twine
  fi
fi

echo "Building packages..."

rm -rf "$TELLR_DIR/dist" "$APP_DIR/dist"

python -m build --sdist --wheel "$TELLR_DIR"

# Copy src/ to APP_DIR before building (find_packages runs at import time,
# before BuildWithFrontend.run() copies it, so we need it present earlier)
cp -r "$ROOT_DIR/src" "$APP_DIR/src"
cleanup_src() {
  rm -rf "$APP_DIR/src"
}
trap cleanup_src EXIT

python -m build --sdist --wheel "$APP_DIR"

# Clean up copied src/ directory
rm -rf "$APP_DIR/src"
trap - EXIT

echo "Uploading packages..."

if [[ -n "$TWINE_REPOSITORY" ]]; then
  TWINE_REPOSITORY="$TWINE_REPOSITORY" python -m twine upload \
    "$TELLR_DIR/dist/"* "$APP_DIR/dist/"*
else
  python -m twine upload "$TELLR_DIR/dist/"* "$APP_DIR/dist/"*
fi

echo "Done."
