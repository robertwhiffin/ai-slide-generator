#!/bin/sh
# Build the two tarballs (node_modules.tar.gz + sys-libs-bullseye.tar.gz)
# that setup.sh extracts at boot. Run from CI (publish.yml) before
# `python -m build`, or locally for testing.
#
# Requirements:
#   - npm + node (for `npm ci`)
#   - apt-get + dpkg-deb (Debian/Ubuntu — works on the Apps Bullseye base
#     image and on github actions ubuntu-latest)
#
# Output:
#   ./node_modules.tar.gz       (~12 MB compressed)
#   ./sys-libs-bullseye.tar.gz  (~15 MB compressed)
#
# Both must be present when `setup.py::BuildWithFrontend` runs, otherwise
# the wheel ships without bootstrap artifacts and the huashu pipeline
# stays unavailable on every install.

set -e
cd "$(dirname "$0")"
SIDECAR_DIR="$(pwd)"

echo "=== build-artifacts.sh in $SIDECAR_DIR ==="

# ---------- 1. node_modules.tar.gz --------------------------------------
echo "--- node_modules.tar.gz ---"
rm -rf node_modules node_modules.tar.gz

# IMPORTANT: skip Playwright's postinstall chromium download. The deployed
# app's setup.sh runs `playwright install chromium` at boot. Letting npm
# ci do it here means the runner downloads ~150 MB of Chromium that we
# never ship — and worse, on GitHub's ubuntu-latest the postinstall
# regularly crashes mid-download with "npm error Exit handler never called!"
# leaving node_modules with empty package directories. v0.3.2's broken
# wheel was caused by exactly this.
export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

if [ -f package-lock.json ]; then
  npm ci --omit=dev
else
  echo "WARN: no package-lock.json — falling back to 'npm install --omit=dev'"
  npm install --omit=dev
fi

# Hard-fail if node_modules came out empty/partial (e.g. npm crashed
# without raising an exit code). v0.3.2 shipped a 4 KB tarball because
# this check didn't exist; never again.
if [ ! -f node_modules/playwright/cli.js ] && [ ! -f node_modules/playwright-core/cli.js ]; then
  echo "ERROR: npm ci finished but node_modules has no playwright/cli.js"
  echo "       (most likely Playwright postinstall crashed; check above logs)"
  ls -la node_modules/playwright 2>&1 | head
  ls -la node_modules/playwright-core 2>&1 | head
  exit 1
fi

# Tar the dir, then remove the on-disk copy so wheel build doesn't see
# both `node_modules/` and `node_modules.tar.gz`.
tar czf node_modules.tar.gz node_modules
rm -rf node_modules

# Sanity check: tarball must be at least 1 MB. A working tree compresses
# to ~12 MB; anything under 1 MB is definitely broken.
TGZ_SIZE=$(stat -c%s node_modules.tar.gz 2>/dev/null || stat -f%z node_modules.tar.gz)
if [ "$TGZ_SIZE" -lt 1000000 ]; then
  echo "ERROR: node_modules.tar.gz is only $TGZ_SIZE bytes (expected >1 MB)"
  exit 1
fi
echo "    $(du -h node_modules.tar.gz)"

# ---------- 2. sys-libs-bullseye.tar.gz ---------------------------------
# Linux runtime libs needed by Chromium that the Apps non-root container
# doesn't ship. Sourced from apt — Bullseye-pinned because that matches
# the Apps base image today. List enumerated from the user's working
# .pw-linux-build/sys-libs-bullseye/ artifact on mohamed-tellr-darwish.
echo "--- sys-libs-bullseye.tar.gz ---"
rm -rf sys-libs sys-libs-bullseye sys-libs-bullseye.tar.gz

if ! command -v apt-get >/dev/null 2>&1; then
  echo "ERROR: apt-get not available. This script must run on a Debian/Ubuntu"
  echo "       host (e.g. github actions ubuntu-latest) so the runtime libs"
  echo "       can be apt-downloaded for the Apps Bullseye base image."
  exit 1
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# Comprehensive list of Bullseye packages whose .so's Chromium loads.
# This script runs on Ubuntu 22.04 (Jammy) — see publish.yml's
# `runs-on: ubuntu-22.04` pin. Jammy's package names are close enough
# to Bullseye for these libs that apt-downloading them produces a working
# bundle for the Apps Bullseye-base container. (Earlier we used
# ubuntu-latest = Noble = 24.04, where libssl1.1, libtiff5, libwebp6,
# libpng16-16, libjpeg62-turbo no longer exist; that's why v0.3.2 shipped
# an empty sys-libs tarball.)
PACKAGES="
  libnspr4
  libnss3
  libgcc-s1
  libstdc++6
  libxkbcommon0
  libxcomposite1
  libxdamage1
  libxfixes3
  libxrandr2
  libxext6
  libx11-6
  libx11-xcb1
  libxcb1
  libxshmfence1
  libgbm1
  libasound2
  libatk1.0-0
  libatk-bridge2.0-0
  libatspi2.0-0
  libcups2
  libpango-1.0-0
  libpangocairo-1.0-0
  libcairo2
  libdrm2
  libdbus-1-3
  libexpat1
  libffi7
  libfontconfig1
  libfreetype6
  libfribidi0
  libgcrypt20
  libgdk-pixbuf-2.0-0
  libgio-2.0-0
  libglib2.0-0
  libgmodule-2.0-0
  libgobject-2.0-0
  libgthread-2.0-0
  libgraphite2-3
  libharfbuzz0b
  libjpeg62-turbo
  libpcre3
  libpixman-1-0
  libpng16-16
  libssl1.1
  libsystemd0
  libthai0
  libtiff5
  libuuid1
  libwayland-client0
  libwayland-cursor0
  libwebp7
  libdatrie1
  zlib1g
"

cd "$TMP"
echo "    apt-get download into $TMP"
# shellcheck disable=SC2086
apt-get download $PACKAGES 2>&1 | tail -n 5 || \
  echo "    WARN: some packages failed to download (they may not exist on this distro)"

mkdir extracted
for deb in *.deb; do
  [ -f "$deb" ] || continue
  dpkg-deb -x "$deb" extracted/
done

mkdir -p "$SIDECAR_DIR/sys-libs-bullseye"
# Flatten: copy every .so* (preserving symlinks) into a single dir.
find extracted -name "*.so*" -print0 | while IFS= read -r -d '' f; do
  cp -P "$f" "$SIDECAR_DIR/sys-libs-bullseye/"
done

cd "$SIDECAR_DIR"
SO_COUNT=$(ls sys-libs-bullseye 2>/dev/null | wc -l)
echo "    sys-libs-bullseye/ has $SO_COUNT .so files"

# Hard-fail if apt-get download silently dropped most packages (e.g. running
# on a too-new Ubuntu where Bullseye package names no longer exist).
# Working bundle has 100+ .so files; anything under 30 is broken.
if [ "$SO_COUNT" -lt 30 ]; then
  echo "ERROR: sys-libs-bullseye/ only has $SO_COUNT .so files (expected 100+)"
  echo "       Most likely apt-get download failed for most packages — check"
  echo "       above for 'E: Unable to locate' / 'E: Can't select candidate' errors."
  echo "       This usually means the runner OS is too new (need Ubuntu 22.04 / Jammy)."
  exit 1
fi

tar czf sys-libs-bullseye.tar.gz sys-libs-bullseye
rm -rf sys-libs-bullseye

TGZ_SIZE=$(stat -c%s sys-libs-bullseye.tar.gz 2>/dev/null || stat -f%z sys-libs-bullseye.tar.gz)
if [ "$TGZ_SIZE" -lt 1000000 ]; then
  echo "ERROR: sys-libs-bullseye.tar.gz is only $TGZ_SIZE bytes (expected >1 MB)"
  exit 1
fi
echo "    $(du -h sys-libs-bullseye.tar.gz)"

echo "=== build-artifacts.sh done ==="
