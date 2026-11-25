#!/bin/sh
# Boot-time bootstrap for the Claude Design (huashu) PPTX path.
#
# Runs in two situations:
#  - From a wheel install: `_assets/sidecars/pptx-emit-huashu/setup.sh`
#    (relative to the installed databricks_tellr_app package).
#  - From a synced repo: `services/pptx-emit-huashu/setup.sh`.
#
# In both cases it does the same four things, idempotently:
#   1. Extract node_modules.tar.gz if node_modules/ is missing.
#   2. Extract sys-libs-bullseye.tar.gz into sys-libs/ if missing.
#   3. Extract fonts-liberation.tar.gz into fonts/ if missing, stale or
#      incomplete, whole or not at all, and write fonts/fonts.conf for a
#      whole bundle, the fontconfig the sidecar's Chromium reads
#      (FONTCONFIG_FILE, set by src/services/pptx_from_html_huashu.py).
#   4. Run `node node_modules/playwright/cli.js install chromium` to
#      download the Chromium binary (Playwright caches under
#      ~/.cache/ms-playwright/ so subsequent boots skip it).
#
# Logs to $HUASHU_SETUP_LOG, /tmp/huashu-setup.log when it is not set, which
# the diagnostic /huashu/available endpoint reads (src/api/routes/export.py)
# to surface progress to ops.

set -e
SIDECAR_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SIDECAR_DIR"

LOG=${HUASHU_SETUP_LOG:-/tmp/huashu-setup.log}
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

# 3. fonts. fonts-liberation.tar.gz has a top-level fonts/ dir: the Liberation
# faces, their licence and fonts.conf.in, the fontconfig template
# (scripts/sidecar_fonts/). Without them Chromium lays out every font stack
# with no loaded webfont in the base image's DejaVu, 10-38 % wider than a
# desktop's faces.
# Unlike steps 1 and 2, fonts/ is a whole bundle or none: the bundle is
# extracted into a staging directory made fresh for this boot (mktemp -d,
# fonts-staging.XXXXXX, beside fonts/ so the moves stay on one filesystem),
# moved into place only once tar has succeeded, and then stamped
# (fonts/.bundle-complete). A staging directory an earlier boot left and could
# not remove (one cut off, a file it could not delete) blocks no later boot. The up-to-date check keys on that
# stamp, not on fonts/, whose mtime every boot's fonts.conf moves, so an
# extraction cut off part way is done again on the next boot; one that fails
# leaves the bundle already in place as it was.
# A failure here is a warning, not a stop: the export then runs as it did
# before the bundle. Every command that can fail runs in an if or && list,
# where set -e does not end the script, so the Chromium step still runs.
FONTS_STAMP=fonts/.bundle-complete
FONTS_STAGING=

# Extracts the bundle into this boot's staging directory, then puts its fonts/
# in place of the old one (moved aside into the staging directory's previous/)
# and stamps it.
extract_fonts() {
  FONTS_STAGING=$(mktemp -d "$SIDECAR_DIR/fonts-staging.XXXXXX") &&
    tar xzf fonts-liberation.tar.gz -C "$FONTS_STAGING" >> "$LOG" 2>&1 &&
    [ -f "$FONTS_STAGING/fonts/fonts.conf.in" ] &&
    { [ ! -e fonts ] || mv fonts "$FONTS_STAGING/previous"; } &&
    mv "$FONTS_STAGING/fonts" fonts &&
    touch "$FONTS_STAMP"
}

needs_extract_fonts=true
if [ -f "$FONTS_STAMP" ] && \
   [ -f fonts-liberation.tar.gz ] && \
   [ "fonts-liberation.tar.gz" -ot "$FONTS_STAMP" ]; then
  echo "[setup] fonts up-to-date with tarball, skipping extract" >> "$LOG"
  needs_extract_fonts=false
fi
if [ "$needs_extract_fonts" = "true" ]; then
  if [ ! -f fonts-liberation.tar.gz ]; then
    echo "[setup] WARN: no fonts-liberation.tar.gz to extract" >> "$LOG"
  else
    echo "[setup] extracting fonts-liberation.tar.gz" >> "$LOG"
    if extract_fonts; then
      echo "[setup] fonts ready" >> "$LOG"
    else
      echo "[setup] WARN: fonts-liberation.tar.gz did not extract whole; fonts/ is as it was" >> "$LOG"
    fi
    if [ -n "$FONTS_STAGING" ] && ! rm -rf "$FONTS_STAGING" 2>> "$LOG"; then
      echo "[setup] WARN: $FONTS_STAGING could not be removed" >> "$LOG"
    fi
  fi
fi

# fonts.conf names this directory's fonts by absolute path, which fontconfig
# 2.13 (the base image's) requires, so it is written on every boot: an install
# that moved still names its own faces. The path is escaped for XML, then for
# sed's replacement. Only a whole bundle has one, so the wrapper never points
# Chromium at part of one.
write_fonts_conf() {
  FONTS_DIR_XML=$(printf '%s' "$SIDECAR_DIR/fonts" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g') &&
    FONTS_DIR_SED=$(printf '%s' "$FONTS_DIR_XML" | sed -e 's/[\\#&]/\\&/g') &&
    sed "s#@FONTS_DIR@#$FONTS_DIR_SED#g" fonts/fonts.conf.in > fonts/fonts.conf.tmp &&
    mv fonts/fonts.conf.tmp fonts/fonts.conf
}

if [ -f "$FONTS_STAMP" ]; then
  if write_fonts_conf; then
    echo "[setup] fonts/fonts.conf written for $SIDECAR_DIR/fonts" >> "$LOG"
  else
    rm -f fonts/fonts.conf.tmp 2>> "$LOG" || :
    echo "[setup] WARN: fonts/fonts.conf could not be written" >> "$LOG"
  fi
elif [ -e fonts/fonts.conf ]; then
  if rm -f fonts/fonts.conf 2>> "$LOG"; then
    echo "[setup] WARN: fonts/ holds no whole bundle; fonts/fonts.conf removed" >> "$LOG"
  else
    echo "[setup] WARN: fonts/ holds no whole bundle, and fonts/fonts.conf could not be removed" >> "$LOG"
  fi
fi

# 4. Chromium — Playwright CLI does the download + caches under
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
