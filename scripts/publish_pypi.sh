#!/bin/bash
#
# Build and upload both packages to TestPyPI for pre-release validation.
# Production publishing is handled by the GitHub Actions workflow (.github/workflows/publish.yml)
# triggered by pushing a version tag (e.g. git tag v0.1.22 && git push origin v0.1.22).

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGES_DIR="$ROOT_DIR/packages"

TELLR_DIR="$PACKAGES_DIR/databricks-tellr"
APP_DIR="$PACKAGES_DIR/databricks-tellr-app"

if [[ ! -d "$TELLR_DIR" || ! -d "$APP_DIR" ]]; then
  echo "Missing packages directory structure."
  exit 1
fi

# Extract and validate versions match across both packages
VERSION=$(python3 -c "
import tomllib, pathlib
print(tomllib.loads(pathlib.Path('$TELLR_DIR/pyproject.toml').read_text())['project']['version'])
")
APP_VERSION=$(python3 -c "
import tomllib, pathlib
print(tomllib.loads(pathlib.Path('$APP_DIR/pyproject.toml').read_text())['project']['version'])
")

if [[ "$VERSION" != "$APP_VERSION" ]]; then
  echo "ERROR: Version mismatch — databricks-tellr=$VERSION, databricks-tellr-app=$APP_VERSION"
  exit 1
fi

echo "Version: $VERSION (TestPyPI)"

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

for tool in build twine; do
  if ! python -m "$tool" --version >/dev/null 2>&1; then
    if command -v uv >/dev/null 2>&1; then
      uv pip install "$tool"
    else
      python -m pip install "$tool"
    fi
  fi
done

echo "Building packages..."

rm -rf "$TELLR_DIR/dist" "$APP_DIR/dist"

python -m build --sdist --wheel "$TELLR_DIR"

cp -r "$ROOT_DIR/src" "$APP_DIR/src"
cleanup_src() {
  rm -rf "$APP_DIR/src"
}
trap cleanup_src EXIT

python -m build --sdist --wheel "$APP_DIR"

rm -rf "$APP_DIR/src"
trap - EXIT

echo "Uploading to TestPyPI..."

TWINE_REPOSITORY=testpypi python -m twine upload \
  "$TELLR_DIR/dist/"* "$APP_DIR/dist/"*

echo ""
echo "Done. Install and test with:"
echo "  pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ databricks-tellr==$VERSION"
echo "  pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ databricks-tellr-app==$VERSION"
