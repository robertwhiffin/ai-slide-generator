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

if [ -f package-lock.json ]; then
  npm ci --omit=dev
else
  echo "WARN: no package-lock.json — falling back to 'npm install --omit=dev'"
  npm install --omit=dev
fi

# Tar the dir, then remove the on-disk copy so wheel build doesn't see
# both `node_modules/` and `node_modules.tar.gz`.
tar czf node_modules.tar.gz node_modules
rm -rf node_modules
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
# Adding a new package is safe (extra .so's just sit in the bundle and
# get picked up via LD_LIBRARY_PATH if Chromium needs them).
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
  libwebp6
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
echo "    sys-libs-bullseye/ has $(ls sys-libs-bullseye | wc -l) .so files"

tar czf sys-libs-bullseye.tar.gz sys-libs-bullseye
rm -rf sys-libs-bullseye
echo "    $(du -h sys-libs-bullseye.tar.gz)"

echo "=== build-artifacts.sh done ==="
