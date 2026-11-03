#!/usr/bin/env bash
#
# Run Playwright E2E specs one after another, each against its own fresh copy of
# the seeded database and its own freshly started backend. CI's e2e-tests job
# calls this once per shard.
#
# Why every spec still gets a fresh database and backend: until 2026-11 each spec
# ran in a CI job of its own, so no spec could see another spec's rows or the
# backend's in-process state. Grouping specs into shards (56 one-spec jobs were
# queueing behind GitHub's 20-concurrent-job cap) must not weaken that, or a spec
# could start passing only because an earlier one left data behind. So before
# each spec this script:
#   1. stops the backend, so no in-memory state carries over;
#   2. drops the database and re-creates it from the snapshot taken right after
#      seeding (CREATE DATABASE ... TEMPLATE, well under a second);
#   3. starts the backend again and waits for /api/health.
# Playwright starts and stops its own Vite dev server per spec (webServer in
# frontend/playwright.config.ts) and gives every test a new browser context, as
# before. The backend's only file outside the database, ~/.tellr/config.yaml, is
# written solely by POST /api/setup/configure, which no spec calls.
#
# Usage:
#   scripts/run_e2e_specs.sh --snapshot              # once, after seeding
#   scripts/run_e2e_specs.sh <spec-stem> [...]       # e.g. slide-viewer chat-ui
#
# Environment (the e2e-tests job sets all of these):
#   DATABASE_URL       the seeded database, e.g. postgresql://test@localhost:5432/test_db;
#                      the backend uses it, and its server's `postgres` database is
#                      used to drop and re-create it
#   ENVIRONMENT, DATABRICKS_HOST, DATABRICKS_TOKEN   passed through to the backend
#   E2E_SEED_DB        snapshot name (default: <database>_e2e_seed)
#   E2E_LOG_DIR        where backend logs go (default: frontend/test-results/_backend,
#                      which the job already uploads; Playwright only cleans
#                      test-results/<spec>, never its parent)
#   E2E_SPEC_TIMEOUT   per-spec backstop for `timeout` (default: 15m)
#
# Exits non-zero if any spec failed, after running all of them.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT=8000
LOG_DIR="${E2E_LOG_DIR:-$REPO_ROOT/frontend/test-results/_backend}"
SPEC_TIMEOUT="${E2E_SPEC_TIMEOUT:-15m}"
BACKEND_PID=""

: "${DATABASE_URL:?DATABASE_URL must name the seeded database}"

# snapshot: copy the seeded database to the template.  reset: replace the
# database with a fresh copy of the template.  Both need autocommit, because
# CREATE/DROP DATABASE cannot run inside a transaction.
db() {
  python - "$1" <<'PY'
import os
import sys
from urllib.parse import urlsplit, urlunsplit

import psycopg2

url = urlsplit(os.environ["DATABASE_URL"])
url = url._replace(scheme=url.scheme.split("+")[0])  # tolerate postgresql+psycopg2://
db = url.path.lstrip("/")
seed = os.environ.get("E2E_SEED_DB") or f"{db}_e2e_seed"


def q(name):
    return '"' + name.replace('"', '""') + '"'


conn = psycopg2.connect(urlunsplit(url._replace(path="/postgres")))
conn.autocommit = True
cur = conn.cursor()
if sys.argv[1] == "snapshot":
    cur.execute(f"DROP DATABASE IF EXISTS {q(seed)}")
    cur.execute(f"CREATE DATABASE {q(seed)} TEMPLATE {q(db)}")
    print(f"Snapshot {seed} taken from {db}")
else:
    cur.execute(f"DROP DATABASE IF EXISTS {q(db)} WITH (FORCE)")
    cur.execute(f"CREATE DATABASE {q(db)} TEMPLATE {q(seed)}")
conn.close()
PY
}

stop_backend() {
  [ -n "$BACKEND_PID" ] || return 0
  # The group's stderr redirect also swallows bash's own "Terminated" job notice.
  {
    kill -TERM "$BACKEND_PID"
    for _ in $(seq 1 15); do
      kill -0 "$BACKEND_PID" || break
      sleep 1
    done
    kill -KILL "$BACKEND_PID"
    wait "$BACKEND_PID"
  } 2>/dev/null
  BACKEND_PID=""
}

start_backend() {
  local log="$1"
  (cd "$REPO_ROOT" && exec python -m uvicorn src.api.main:app --host 0.0.0.0 --port "$BACKEND_PORT") \
    >"$log" 2>&1 &
  BACKEND_PID=$!
  for _ in $(seq 1 60); do
    if curl -sf "http://localhost:$BACKEND_PORT/api/health" >/dev/null 2>&1; then
      return 0
    fi
    kill -0 "$BACKEND_PID" 2>/dev/null || return 1
    sleep 1
  done
  return 1
}

run_playwright() {
  local spec="$1"
  local cmd=(npx playwright test "tests/e2e/$spec.spec.ts" --project=chromium --workers=1
             --output="test-results/$spec")
  if command -v timeout >/dev/null 2>&1; then
    cmd=(timeout "$SPEC_TIMEOUT" "${cmd[@]}")
  fi
  (cd "$REPO_ROOT/frontend" \
    && PLAYWRIGHT_HTML_OUTPUT_DIR="playwright-report/$spec" PLAYWRIGHT_HTML_OPEN=never "${cmd[@]}")
}

if [ "${1:-}" = "--snapshot" ]; then
  db snapshot
  exit $?
fi

if [ $# -eq 0 ]; then
  echo "usage: $0 --snapshot | <spec-stem> [<spec-stem> ...]" >&2
  exit 2
fi

trap stop_backend EXIT
mkdir -p "$LOG_DIR"
failed=()
summary=()

for spec in "$@"; do
  echo "::group::E2E $spec"
  started=$SECONDS
  log="$LOG_DIR/$spec.log"
  stop_backend
  status=passed
  if [ ! -f "$REPO_ROOT/frontend/tests/e2e/$spec.spec.ts" ]; then
    echo "No such spec: frontend/tests/e2e/$spec.spec.ts"
    status="failed (no such spec)"
  elif ! db reset; then
    status="failed (database reset)"
  elif ! start_backend "$log"; then
    status="failed (backend did not start)"
  elif ! run_playwright "$spec"; then
    status=failed
  fi
  echo "::endgroup::"

  elapsed=$((SECONDS - started))
  summary+=("| \`$spec\` | $status | ${elapsed}s |")
  if [ "$status" != passed ]; then
    failed+=("$spec")
    echo "::error title=E2E spec failed::$spec — $status"
    if [ -f "$log" ]; then
      echo "::group::Backend log for $spec (last 100 lines)"
      tail -n 100 "$log"
      echo "::endgroup::"
    fi
  fi
done

stop_backend

{
  echo "| Spec | Result | Time |"
  echo "| --- | --- | --- |"
  printf '%s\n' "${summary[@]}"
} | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}"

if [ ${#failed[@]} -gt 0 ]; then
  echo "${#failed[@]} of $# specs failed: ${failed[*]}"
  exit 1
fi
echo "All $# specs passed."
