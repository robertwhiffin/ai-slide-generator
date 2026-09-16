#!/bin/bash
#
# Run the layer-3 agentic-behaviour tests.  This is THE command for that layer —
# discoverable and one command, rather than a marker nobody remembers.
#
# Usage:
#   ./scripts/run_agentic_tests.sh                        # run the layer
#   ./scripts/run_agentic_tests.sh -k architect           # extra pytest args pass through
#   ./scripts/run_agentic_tests.sh -v --tb=long
#   PYTHON=~/.pyenv/versions/3.11.0/bin/python ./scripts/run_agentic_tests.sh
#
# Options:
#   Anything you pass is forwarded to pytest verbatim, after the layer's own
#   arguments (`tests/agentic -m live -rs`).
#
# Environment:
#   PYTHON   Interpreter to run pytest with (default: python3).
#
# What this layer is:
#   The test suite has four layers, organised by what each NEEDS in order to run.
#   Layer 3 is the one that needs a real language model, reached through a real
#   Databricks serving endpoint — so it cannot run on a CI runner with no
#   credentials, and it costs real money where it can.
#
# EXPECT EVERY TEST TO SKIP, and expect that to be the honest answer today.
#   Three mechanisms gate this layer, and they are not interchangeable:
#     * the `live` marker           — selection: how this script and the CI job pick
#                                     these tests, and how `-m "not live"` excludes
#                                     them everywhere else;
#     * a skipif on reachability    — safety: no reachable endpoint means skip, never
#                                     a failure that looks like a finding;
#     * an unconditional skip       — honesty: the seven skills ship PLACEHOLDER
#                                     prompts, and no assertion here is weakened
#                                     until one of them satisfies it.
#   `-rs` below prints the reason for every skip, so this command always explains
#   itself rather than just printing a row of dots.
#
# To turn the layer on — two steps, and they are not both in the workflow:
#   1. delete `if: false` from the `agentic-tests` job in
#      .github/workflows/test.yml and give the repo DATABRICKS_HOST /
#      DATABRICKS_TOKEN secrets.  That job already gates the build (it is in
#      test-summary's needs:, echo block and failure loop), so nothing else in the
#      workflow changes.
#   2. delete PLACEHOLDER_GATE from LAYER3_MARKS in tests/agentic/gates.py.  ONE
#      line, for the whole layer — but it is not a workflow file, and without it an
#      enabled job just reports a green all-skipped run.
#

set -euo pipefail

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$ROOT_DIR"

PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" > /dev/null 2>&1; then
    echo -e "${RED}Interpreter not found: ${PYTHON}${NC}"
    echo "Set PYTHON to the interpreter that has this project's dev extras installed, e.g."
    echo "  PYTHON=~/.pyenv/versions/3.11.0/bin/python $0"
    exit 1
fi

if [[ ! -d "$ROOT_DIR/tests/agentic" ]]; then
    echo -e "${RED}tests/agentic/ not found under ${ROOT_DIR}.${NC}"
    echo "This script runs the layer-3 suite; without the directory there is nothing to run."
    exit 1
fi

echo -e "${BLUE}Layer 3 — agentic behaviour${NC}"
echo -e "${BLUE}Interpreter:${NC} $("$PYTHON" -c 'import sys; print(sys.executable)')"

if [[ -z "${DATABRICKS_HOST:-}" ]]; then
    echo -e "${YELLOW}DATABRICKS_HOST is not set in this shell.${NC}"
    echo "  A local .env supplies it (src/core/database.py calls load_dotenv()), so the"
    echo "  endpoint gate may still pass. If it does not, every test reports that reason."
fi

echo ""

# -m live       selection: the same filter the CI job uses, so this command and CI
#               run exactly the same set.
# -rs           print the reason for every skip. Layer 3 is skipped by design; a
#               command that hid the reason would make an honest skip look like an
#               accident.
set +e
"$PYTHON" -m pytest tests/agentic -m live -rs "$@"
STATUS=$?
set -e

echo ""
if [[ $STATUS -eq 0 ]]; then
    echo -e "${GREEN}Layer 3 completed without failures.${NC}"
    echo "  All-skipped is the expected result until the authored prompts land: see the"
    echo "  reasons printed above, and tests/agentic/gates.py for how to retire the"
    echo "  placeholder gate."
else
    echo -e "${RED}Layer 3 reported failures (pytest exit ${STATUS}).${NC}"
    echo "  If these ran against PLACEHOLDER prompts, the fix is not a weaker assertion."
    echo "  Restore the placeholder gate in tests/agentic/gates.py, or author the prompts."
fi

exit $STATUS
