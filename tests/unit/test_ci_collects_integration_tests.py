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
DELIBERATE_EXCLUSIONS: dict[str, str] = {
    "test_graph_live_real_model.py": (
        "ws4c's real-model Definition-of-done run. Marked `live` and MUST NOT run in CI: "
        "it calls a Databricks serving endpoint with real spend, and the `unit-tests` job "
        "applies no `-m` filter, so being named in any job would run it on every PR. It "
        "self-skips without both a reachable PostgreSQL and Databricks credentials, and its "
        "spend is bounded by an explicit call budget rather than a recursion limit."
    ),
}


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


def test_no_nested_integration_tests():
    """No test_*.py may exist inside a sub-directory of tests/integration/.

    The CI job names files by their flat path (tests/integration/test_foo.py).
    A file at tests/integration/subdir/test_foo.py cannot be named in the flat
    job listing, so it would silently receive no CI coverage.  The correct fix
    is to flatten it into tests/integration/ — not to silently ignore it or
    expand the guard to cover subdirectories.
    """
    nested = [
        p.relative_to(INTEGRATION_DIR)
        for p in INTEGRATION_DIR.rglob("test_*.py")
        if p.parent != INTEGRATION_DIR
    ]
    assert not nested, (
        "Found test_*.py files in sub-directories of tests/integration/:\n"
        + "\n".join(f"  - tests/integration/{p}" for p in sorted(nested))
        + "\n\nThe CI job lists files by their flat path under tests/integration/."
        " A nested file cannot be named in that listing and will receive no CI"
        " coverage. Flatten it into tests/integration/ and add it to a CI job."
    )


# ---------------------------------------------------------------------------
# Assertion 1 — coverage
# ---------------------------------------------------------------------------
def test_every_integration_file_is_collected_or_excluded_with_reason():
    """Every tests/integration/test_*.py is either named in a CI job's run
    block or in DELIBERATE_EXCLUSIONS with a non-empty reason.
    """
    run_blocks = _collect_run_blocks()
    test_names = _integration_test_names()

    # Guard: a coverage check that discovers zero files is vacuously true —
    # it reports success over an empty universe, which is the exact failure mode
    # these guards exist to prevent elsewhere.  If this fires, INTEGRATION_DIR
    # is wrong or the directory has been emptied; fix the path, not the assertion.
    assert test_names, (
        f"No test_*.py files found in {INTEGRATION_DIR.resolve()!s}. "
        "Either INTEGRATION_DIR points at the wrong path or the directory is empty. "
        "A coverage guard that discovers nothing must fail loudly rather than "
        "report success over an empty set."
    )

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

    # A file must not be in BOTH DELIBERATE_EXCLUSIONS and a CI job's run block.
    # If it is in both, CI still runs it even though it is supposed to be excluded
    # — the exclusion appears honoured while the file quietly continues to run.
    both = collected & set(DELIBERATE_EXCLUSIONS.keys())
    assert not both, (
        "These tests/integration/test_*.py files are in BOTH a CI job's run "
        "block and DELIBERATE_EXCLUSIONS:\n"
        + "\n".join(f"  - {n}" for n in sorted(both))
        + "\n\nA file in DELIBERATE_EXCLUSIONS will still run in CI if it is "
        "also named in a job's run block.  Remove it from the job."
    )

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
