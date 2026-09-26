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
import pytest
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


def _collect_job_run_blocks(job_name: str) -> list[str]:
    """Return run blocks for one named workflow job, failing on a stale job name."""
    with open(WORKFLOW) as f:
        wf = yaml.safe_load(f)

    job = (wf.get("jobs") or {}).get(job_name)
    assert job is not None, (
        f"{job_name!r} is absent from {WORKFLOW}; update the job-specific CI guard "
        "to the replacement job rather than letting it pass over an empty set."
    )
    return [
        step["run"]
        for step in (job.get("steps") or [])
        if isinstance(step, dict) and "run" in step
    ]


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


def test_conversation_pin_migration_is_collected_by_integration_graph():
    """The Conversation Pin PostgreSQL migration belongs in the graph CI job."""
    target = "tests/integration/test_conversation_pin_migration_postgres.py"
    run_blocks = _collect_job_run_blocks("integration-graph")
    assert any(target in block for block in run_blocks), (
        f"{target!r} is not named in integration-graph's run block in "
        ".github/workflows/test.yml. Its PostgreSQL upgrade/backfill assertions "
        "must run in the graph job's PostgreSQL environment."
    )


def test_conversation_pin_creation_is_collected_by_integration_graph():
    """The Conversation Pin PostgreSQL linearization tests belong in graph CI."""
    target = "tests/integration/test_conversation_pin_creation_postgres.py"
    run_blocks = _collect_job_run_blocks("integration-graph")
    assert any(target in block for block in run_blocks), (
        f"{target!r} is not named in integration-graph's run block in "
        ".github/workflows/test.yml. Its PostgreSQL lock-order assertions must "
        "run in the graph job's PostgreSQL environment."
    )


@pytest.mark.parametrize(
    "filename",
    [
        "test_mixed_release_creation_postgres.py",
        "test_conversation_creator_exclusions_postgres.py",
    ],
)
def test_remaining_creation_lock_suites_are_collected_by_integration_graph(filename):
    """Task-2 creator ordering and exclusions require graph-job PostgreSQL."""
    target = f"tests/integration/{filename}"
    run_blocks = _collect_job_run_blocks("integration-graph")
    assert any(target in block for block in run_blocks), (
        f"{target!r} is not named in integration-graph's run block in "
        ".github/workflows/test.yml. Task-2 creator lock and exclusion coverage "
        "must execute against PostgreSQL."
    )


def test_persisted_graph_runtime_failures_are_collected_by_integration_graph():
    """Persisted runtime failure coverage requires the graph job's PostgreSQL."""
    target = "tests/integration/test_persisted_graph_runtime_failures_postgres.py"
    run_blocks = _collect_job_run_blocks("integration-graph")
    assert any(target in block for block in run_blocks), (
        f"{target!r} is not named in integration-graph's run block in "
        ".github/workflows/test.yml. Its exact-release failure and redaction "
        "assertions must execute against PostgreSQL."
    )


def test_conversation_pin_acceptance_is_collected_by_integration_graph():
    """The final persisted-runtime acceptance belongs in graph CI."""
    target = "tests/integration/test_conversation_pin_acceptance_postgres.py"
    run_blocks = _collect_job_run_blocks("integration-graph")
    assert any(target in block for block in run_blocks), (
        f"{target!r} is not named in integration-graph's run block in "
        ".github/workflows/test.yml. Its compiled-graph pin assertions must "
        "execute against PostgreSQL."
    )


def test_shared_deck_mutation_migration_is_collected_by_integration_graph():
    """The append-only evidence migration/lifecycle suite requires PostgreSQL."""
    target = "tests/integration/test_shared_deck_mutation_migration_postgres.py"
    run_blocks = _collect_job_run_blocks("integration-graph")
    assert any(target in block for block in run_blocks), (
        f"{target!r} is not named in integration-graph's run block in "
        ".github/workflows/test.yml. Its trigger and FK lifecycle assertions must "
        "execute against PostgreSQL."
    )


def test_shared_deck_mutation_lifecycle_is_collected_by_integration_graph():
    """The evidence-preserving deletion/expiry lifecycle requires PostgreSQL."""
    target = "tests/integration/test_shared_deck_mutation_lifecycle_postgres.py"
    run_blocks = _collect_job_run_blocks("integration-graph")
    assert any(target in block for block in run_blocks), (
        f"{target!r} is not named in integration-graph's run block in "
        ".github/workflows/test.yml. Its cascade and per-candidate transaction "
        "assertions must execute against PostgreSQL."
    )


def test_mixed_release_collaboration_acceptance_is_collected_by_integration_graph():
    """#262's cross-writer acceptance and both final contract audits need PostgreSQL.

    Four of its claims cannot be cashed anywhere else. The ``ON DELETE SET NULL``
    retention needs real cascades — the SQLite fixtures report
    ``PRAGMA foreign_keys = 0``, so a delete there leaves a dangling FK rather
    than a nulled one and the retention assertion would pass vacuously. The
    append-only trigger and the ``collaboration_identity`` immutability trigger
    are PL/pgSQL. The forced creation lock orderings need two genuinely
    concurrent transactions plus ``pg_stat_activity`` to observe a waiter, which
    a single shared SQLite connection cannot produce. And the one grouped
    statement is counted against the real dialect's aggregation.

    The two executable contract audits ride in the same module deliberately:
    they are the plan's final ``rg`` sweeps, and a sweep whose result lives in a
    report is re-run by hand or not at all.
    """
    target = "tests/integration/test_mixed_release_collaboration_acceptance_postgres.py"
    run_blocks = _collect_job_run_blocks("integration-graph")
    assert any(target in block for block in run_blocks), (
        f"{target!r} is not named in integration-graph's run block in "
        ".github/workflows/test.yml. Its cross-writer acceptance, cascade "
        "retention, trigger, lock-ordering and contract-audit assertions must "
        "execute against PostgreSQL."
    )


def test_collaboration_history_api_is_collected_by_integration_graph():
    """The authorization-scoped collaboration history API requires PostgreSQL.

    Its load-bearing assertions are dialect-specific: the five-check CAN_VIEW
    predicate against real ``uuid``/``varchar`` columns and PostgreSQL's NULL
    semantics for ``IN``, newest-first grouped aggregation despite PostgreSQL's
    ``NULLS FIRST`` default for ``DESC``, and evidence surviving real
    ``ON DELETE SET NULL`` cascades.

    That last claim is the one this docstring must actually be able to cash, and
    only PostgreSQL can cash it: the unit fixture's in-memory SQLite reports
    ``PRAGMA foreign_keys = 0``, so no cascade fires there at all and a ``DELETE``
    would leave a dangling FK rather than a nulled one. The PostgreSQL module
    therefore owns three real deletions — every actor, the deck row, and the root
    session — plus the two-actors-on-one-release guard that is the only shape able
    to catch grouping on ``actor_session_id`` instead of the opaque
    ``actor_session_identity``.
    """
    target = "tests/integration/test_collaboration_history_api_postgres.py"
    run_blocks = _collect_job_run_blocks("integration-graph")
    assert any(target in block for block in run_blocks), (
        f"{target!r} is not named in integration-graph's run block in "
        ".github/workflows/test.yml. Its five-check CAN_VIEW predicate, grouped "
        "projection ordering and SET NULL survival assertions must execute "
        "against PostgreSQL."
    )


def test_agent_schema_overlay_is_collected_by_integration_graph():
    """#264's schema-overlay writer coverage belongs in the graph CI job.

    Its assertions are about real row-level locks, distinct backend PIDs and an
    observably waiting session, none of which SQLite can express — so it must run
    in the graph job's PostgreSQL environment rather than the unit job.
    """
    target = "tests/integration/test_agent_schema_overlay_postgres.py"
    run_blocks = _collect_job_run_blocks("integration-graph")
    assert any(target in block for block in run_blocks), (
        f"{target!r} is not named in integration-graph's run block in "
        ".github/workflows/test.yml. Its schema-overlay validation, v2 contract "
        "upgrade and two-session serialization assertions must execute against "
        "PostgreSQL."
    )


def test_graph_release_publication_is_collected_by_integration_graph():
    """#269's atomic publication core belongs in the graph CI job.

    Its lock-statement order, rollback-at-every-write-seam and published-history
    guard assertions need real PostgreSQL row locks, deferred constraint
    triggers and backend PIDs, none of which SQLite can express.
    """
    target = "tests/integration/test_graph_release_publication_postgres.py"
    run_blocks = _collect_job_run_blocks("integration-graph")
    assert any(target in block for block in run_blocks), (
        f"{target!r} is not named in integration-graph's run block in "
        ".github/workflows/test.yml. Its publication lock-order, rollback and "
        "release-history guard assertions must execute against PostgreSQL."
    )


def test_graph_release_session_ordering_is_collected_by_integration_graph():
    """#269's creator-versus-publication ordering proof belongs in the graph CI job.

    It proves every conversation creator linearizes with real publication at the
    active release row, observed through backend PIDs and ``pg_blocking_pids``,
    none of which SQLite can express.
    """
    target = "tests/integration/test_graph_release_session_ordering_postgres.py"
    run_blocks = _collect_job_run_blocks("integration-graph")
    assert any(target in block for block in run_blocks), (
        f"{target!r} is not named in integration-graph's run block in "
        ".github/workflows/test.yml. Its creator-versus-publication lock-order "
        "assertions must execute against PostgreSQL."
    )
