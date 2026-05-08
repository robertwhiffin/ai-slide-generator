#!/bin/sh
# Verify the pre-built huashu bootstrap tarballs are present and not
# corrupt. Called by .github/workflows/publish.yml before
# `python -m build`.
#
# We commit the tarballs directly to git instead of building them in CI:
#
#   - npm ci on GitHub Actions reliably hits a known npm bug
#     ("Exit handler never called!") and produces broken trees. We
#     re-confirmed this on every attempt for v0.3.2 → v0.3.3 → v0.3.3
#     until we gave up and shipped pre-built. Same bug Tariq's
#     app.yaml.darwish has documented for months.
#   - apt-get download for Bullseye runtime libs needs a 22.04 runner
#     and Bullseye-era package names that keep getting removed from
#     newer Ubuntu releases.
#
# So: build the tarballs once on a working host (your laptop, or a
# Bullseye/Jammy container), commit them, never run npm or apt in CI.
#
# REGEN INSTRUCTIONS (when playwright/pptxgenjs versions in package.json
# bump, or when sys-libs need updating for a new Apps base image):
#
#   cd services/pptx-emit-huashu
#
#   # node_modules: build on a host where `npm ci` works (Mac dev box
#   # works; CI doesn't). Skip postinstall to keep the tree small + clean.
#   rm -rf node_modules
#   PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm ci --ignore-scripts
#   tar czf node_modules.tar.gz node_modules
#   rm -rf node_modules
#
#   # sys-libs: apt-download Bullseye runtime libs (run on Jammy or in a
#   # Debian Bullseye container). The list is the same one
#   # build-artifacts.sh@d8d3ec used; ~50 packages including libnss3,
#   # libnspr4, libgcc-s1, libstdc++6, libxkbcommon0, libxcomposite1,
#   # etc. Flatten all .so* files into sys-libs-bullseye/ then tar.
#
#   git add node_modules.tar.gz sys-libs-bullseye.tar.gz
#   git commit -m "chore(huashu): regenerate bootstrap tarballs"

set -e
cd "$(dirname "$0")"

NODE_TGZ=node_modules.tar.gz
SYS_TGZ=sys-libs-bullseye.tar.gz

echo "=== verify huashu bootstrap tarballs ==="

if [ ! -f "$NODE_TGZ" ]; then
  echo "ERROR: $NODE_TGZ missing. Regenerate per the comment block at the top of this script."
  exit 1
fi
if [ ! -f "$SYS_TGZ" ]; then
  echo "ERROR: $SYS_TGZ missing. Regenerate per the comment block at the top of this script."
  exit 1
fi

# Working node_modules.tar.gz is ~12 MB; sys-libs ~18 MB. Anything under
# 1 MB is definitely broken (dir-only tar etc).
size_of() { stat -c%s "$1" 2>/dev/null || stat -f%z "$1"; }

NODE_SIZE=$(size_of "$NODE_TGZ")
SYS_SIZE=$(size_of "$SYS_TGZ")

if [ "$NODE_SIZE" -lt 1000000 ]; then
  echo "ERROR: $NODE_TGZ is only $NODE_SIZE bytes (expected >1 MB)."
  echo "       The committed tarball is likely truncated or empty. Regenerate."
  exit 1
fi
if [ "$SYS_SIZE" -lt 1000000 ]; then
  echo "ERROR: $SYS_TGZ is only $SYS_SIZE bytes (expected >1 MB)."
  echo "       The committed tarball is likely truncated or empty. Regenerate."
  exit 1
fi

# Validate tarballs aren't corrupt and contain what setup.sh needs.
if ! tar tzf "$NODE_TGZ" 2>/dev/null | grep -q '^node_modules/playwright/cli\.js$\|^node_modules/playwright-core/cli\.js$'; then
  echo "ERROR: $NODE_TGZ does not contain playwright/cli.js or playwright-core/cli.js."
  echo "       The committed tarball is broken. Regenerate."
  exit 1
fi

echo "    $NODE_TGZ  $(du -h "$NODE_TGZ" | cut -f1)"
echo "    $SYS_TGZ   $(du -h "$SYS_TGZ" | cut -f1)"
echo "=== huashu tarballs ok ==="
