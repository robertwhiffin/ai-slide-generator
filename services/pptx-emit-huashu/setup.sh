#!/bin/sh
# Boot-time bootstrap for the Claude Design (huashu) PPTX path.
#
# Runs in two situations:
#  - From a wheel install: `_assets/sidecars/pptx-emit-huashu/setup.sh`
#    (relative to the installed databricks_tellr_app package).
#  - From a synced repo: `services/pptx-emit-huashu/setup.sh`.
#
# In both cases it does the same three things, idempotently:
#   1. Extract node_modules.tar.gz if node_modules/ is missing.
#   2. Extract sys-libs-bullseye.tar.gz into sys-libs/ if missing.
#   3. Run `node node_modules/playwright/cli.js install chromium` to
#      download the Chromium binary (Playwright caches under
#      ~/.cache/ms-playwright/ so subsequent boots skip it).
#
# Logs to /tmp/huashu-setup.log so the diagnostic /huashu/available
# endpoint can surface progress to ops.

set -e
SIDECAR_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SIDECAR_DIR"

LOG=/tmp/huashu-setup.log
echo "=== huashu setup at $(date -u +%FT%TZ) ===" > "$LOG"
echo "sidecar dir: $SIDECAR_DIR" >> "$LOG"

# 1. node_modules — extract from tarball if missing OR present-but-empty.
# We can't trust just `[ -d node_modules ]` because the wheel can ship empty
# placeholder dirs (node_modules/playwright/, node_modules/playwright-core/)
# that look like a valid tree until you actually try to use them. Validate
# by probing for a known file (the playwright CLI). If it's missing, force
# a clean re-extract from the tarball.
if [ -d node_modules ] && { [ -f node_modules/playwright/cli.js ] || [ -f node_modules/playwright-core/cli.js ]; }; then
  echo "[setup] node_modules already present and valid, skipping extract" >> "$LOG"
elif [ -f node_modules.tar.gz ]; then
  if [ -d node_modules ]; then
    echo "[setup] node_modules dir present but missing playwright CLI; clearing for clean extract" >> "$LOG"
    rm -rf node_modules
  fi
  echo "[setup] extracting node_modules.tar.gz" >> "$LOG"
  tar xzf node_modules.tar.gz >> "$LOG" 2>&1
  echo "[setup] node_modules ready" >> "$LOG"
else
  echo "[setup] WARN: no node_modules dir and no node_modules.tar.gz" >> "$LOG"
fi

# 2. sys-libs — extracted dir should be named sys-libs/ (the Python wrapper
# looks for that path). The tarball contains a top-level sys-libs-bullseye/
# dir, which we rename. Validate by probing for libnss3.so (Chromium's
# core network-security lib) so a half-extracted sys-libs/ is forced to
# re-extract.
if [ -d sys-libs ] && [ -f sys-libs/libnss3.so ]; then
  echo "[setup] sys-libs already present and valid, skipping extract" >> "$LOG"
elif [ -f sys-libs-bullseye.tar.gz ]; then
  if [ -d sys-libs ] || [ -d sys-libs-bullseye ]; then
    echo "[setup] sys-libs dir present but incomplete; clearing for clean extract" >> "$LOG"
    rm -rf sys-libs sys-libs-bullseye
  fi
  echo "[setup] extracting sys-libs-bullseye.tar.gz" >> "$LOG"
  tar xzf sys-libs-bullseye.tar.gz >> "$LOG" 2>&1
  if [ -d sys-libs-bullseye ]; then
    mv sys-libs-bullseye sys-libs
    echo "[setup] sys-libs ready" >> "$LOG"
  fi
else
  echo "[setup] WARN: no sys-libs dir and no sys-libs-bullseye.tar.gz" >> "$LOG"
fi

# 3. Chromium — Playwright CLI does the download + caches under
# ~/.cache/ms-playwright/. No-op once the cache exists.
PW_CLI=
if [ -f node_modules/playwright/cli.js ]; then
  PW_CLI=node_modules/playwright/cli.js
elif [ -f node_modules/playwright-core/cli.js ]; then
  PW_CLI=node_modules/playwright-core/cli.js
fi

if [ -n "$PW_CLI" ]; then
  echo "[setup] running: node $PW_CLI install chromium" >> "$LOG"
  node "$PW_CLI" install chromium >> "$LOG" 2>&1 || \
    echo "[setup] WARN: chromium install rc=$?" >> "$LOG"
  echo "[setup] chromium step done" >> "$LOG"
else
  echo "[setup] WARN: no playwright CLI in node_modules — skipping chromium install" >> "$LOG"
fi

echo "[setup] done at $(date -u +%FT%TZ)" >> "$LOG"
