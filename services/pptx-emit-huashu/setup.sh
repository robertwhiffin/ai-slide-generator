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

# 1. node_modules — re-extract from tarball if missing, partial, OR if the
# tarball is newer than the extracted dir (i.e. wheel was upgraded since
# last boot). Container filesystem persists across pip upgrades, so we
# can't just check "did node_modules exist" — that would hold us on the
# OLD extracted tree forever. Stamp the tarball's mtime against the
# extracted dir; if they don't match, re-extract.
needs_extract_node=true
if [ -d node_modules ] && \
   { [ -f node_modules/playwright/cli.js ] || [ -f node_modules/playwright-core/cli.js ]; } && \
   [ -f node_modules.tar.gz ] && \
   [ "node_modules.tar.gz" -ot "node_modules" ]; then
  echo "[setup] node_modules up-to-date with tarball, skipping extract" >> "$LOG"
  needs_extract_node=false
fi
if [ "$needs_extract_node" = "true" ]; then
  if [ ! -f node_modules.tar.gz ]; then
    echo "[setup] WARN: no node_modules.tar.gz to extract" >> "$LOG"
  else
    if [ -d node_modules ]; then
      echo "[setup] node_modules stale or missing playwright CLI; clearing for clean extract" >> "$LOG"
      rm -rf node_modules
    fi
    echo "[setup] extracting node_modules.tar.gz" >> "$LOG"
    tar xzf node_modules.tar.gz >> "$LOG" 2>&1
    # Touch dir so future mtime comparison picks up tarball updates.
    touch node_modules
    echo "[setup] node_modules ready" >> "$LOG"
  fi
fi

# 2. sys-libs — same pattern. Extracted dir is sys-libs/ (the Python
# wrapper's path); tarball is sys-libs-bullseye.tar.gz with a top-level
# sys-libs-bullseye/ dir we rename.
needs_extract_sys=true
if [ -d sys-libs ] && \
   [ -f sys-libs/libnss3.so ] && \
   [ -f sys-libs-bullseye.tar.gz ] && \
   [ "sys-libs-bullseye.tar.gz" -ot "sys-libs" ]; then
  echo "[setup] sys-libs up-to-date with tarball, skipping extract" >> "$LOG"
  needs_extract_sys=false
fi
if [ "$needs_extract_sys" = "true" ]; then
  if [ ! -f sys-libs-bullseye.tar.gz ]; then
    echo "[setup] WARN: no sys-libs-bullseye.tar.gz to extract" >> "$LOG"
  else
    if [ -d sys-libs ] || [ -d sys-libs-bullseye ]; then
      echo "[setup] sys-libs stale or incomplete; clearing for clean extract" >> "$LOG"
      rm -rf sys-libs sys-libs-bullseye
    fi
    echo "[setup] extracting sys-libs-bullseye.tar.gz" >> "$LOG"
    tar xzf sys-libs-bullseye.tar.gz >> "$LOG" 2>&1
    if [ -d sys-libs-bullseye ]; then
      mv sys-libs-bullseye sys-libs
      touch sys-libs
      echo "[setup] sys-libs ready" >> "$LOG"
    fi
  fi
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
