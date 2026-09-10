"""Guard: every tests/integration/test_*.py must be named in some CI job's
run block in .github/workflows/test.yml, or listed in DELIBERATE_EXCLUSIONS
with a non-empty reason.

An empty reason is not allowed — that is exactly how an exclusion becomes a
silent gap, indistinguishable from a file that was simply forgotten.  A new
integration file that silently goes uncollected by CI is the defect this test
exists to prevent; adding it to DELIBERATE_EXCLUSIONS with an empty reason is
not materially different.

Two assertions
--------------
1. coverage: every tests/integration/test_*.py is either named in a job's run
   block or in DELIBERATE_EXCLUSIONS with a non-empty reason.
2. pin: test_slide_row_identity_and_verdicts.py is named in a job (the most
   load-bearing of the previously-uncollected files; a future re-drop must be
   loud).
"""
import yaml
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths (anchored from this file — never cwd-relative)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "test.yml"
INTEGRATION_DIR = REPO_ROOT / "tests" / "integration"

# ---------------------------------------------------------------------------
# Explicit exclusions — integration test files that are NOT collected in any
# CI job because they require external services, credentials, or other
# conditions unavailable in CI.  Each must have a non-empty reason; an empty
# reason fails the test.
# ---------------------------------------------------------------------------
DELIBERATE_EXCLUSIONS: dict[str, str] = {}


def _collect_run_blocks() -> list[str]:
    """Parse the workflow with yaml.safe_load; never a regex.

    Returns a flat list of all 'run' strings found in every job's steps.
    """
    with open(WORKFLOW) as f:
        wf = yaml.safe_load(f)

    run_blocks: list[str] = []
    for job in wf.get("jobs", {}).values():
        for step in (job.get("steps") or []):
            if isinstance(step, dict) and "run" in step:
                run_blocks.append(step["run"])
    return run_blocks


def _integration_test_names() -> set[str]:
    """All test_*.py filenames directly in tests/integration/ (non-recursive)."""
    return {p.name for p in INTEGRATION_DIR.glob("test_*.py")}


# ---------------------------------------------------------------------------
# Assertion 1 — coverage
# ---------------------------------------------------------------------------
def test_every_integration_file_is_collected_or_excluded_with_reason():
    """Every tests/integration/test_*.py is either named in a CI job's run
    block or in DELIBERATE_EXCLUSIONS with a non-empty reason.
    """
    run_blocks = _collect_run_blocks()
    test_names = _integration_test_names()

    # First validate that every DELIBERATE_EXCLUSIONS entry has a non-empty
    # reason — an empty reason is not allowed.
    empty_reasons = {name for name, reason in DELIBERATE_EXCLUSIONS.items() if not reason.strip()}
    assert not empty_reasons, (
        f"DELIBERATE_EXCLUSIONS entries must have a non-empty reason. "
        f"These have an empty reason: {sorted(empty_reasons)}"
    )

    # Determine which files are named in any job's run block.
    collected = {
        name
        for name in test_names
        if any(f"tests/integration/{name}" in block for block in run_blocks)
    }

    # Every file must be collected or explicitly excluded.
    uncovered = test_names - collected - set(DELIBERATE_EXCLUSIONS.keys())
    assert not uncovered, (
        "The following tests/integration/test_*.py files are neither named in "
        "a CI job's run block nor in DELIBERATE_EXCLUSIONS:\n"
        + "\n".join(f"  - {n}" for n in sorted(uncovered))
        + "\n\nAdd each to a CI job in .github/workflows/test.yml, or add it to "
        "DELIBERATE_EXCLUSIONS in this file with a non-empty reason."
    )


# ---------------------------------------------------------------------------
# Assertion 2 — pin test_slide_row_identity_and_verdicts
# ---------------------------------------------------------------------------
def test_slide_row_identity_and_verdicts_is_collected():
    """test_slide_row_identity_and_verdicts.py must be named in a CI job.

    It is PR1's row-per-slide identity and verdict suite — the foundation
    every later PR in this workstream builds on.  Pinning it here means a
    future accidental removal is loud.
    """
    run_blocks = _collect_run_blocks()
    target = "test_slide_row_identity_and_verdicts.py"
    assert any(f"tests/integration/{target}" in block for block in run_blocks), (
        f"'tests/integration/{target}' is not named in any CI job's run block in "
        ".github/workflows/test.yml.  It is PR1's row-per-slide identity and "
        "verdict suite that the entire workstream builds on — restore it to a job."
    )
