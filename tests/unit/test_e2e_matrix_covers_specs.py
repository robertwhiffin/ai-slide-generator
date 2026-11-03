"""Guard: the e2e matrix in .github/workflows/test.yml must name every
*.spec.ts in frontend/tests/e2e/ or list it in DELIBERATE_EXCLUSIONS
with a non-empty reason.

The matrix is a list of shards (``include: [{shard: n, specs: [...]}]``);
"in the matrix" means named in some shard's ``specs:`` list.

An empty reason is not allowed — that is exactly how an exclusion
becomes a silent gap, indistinguishable from a spec that was simply
forgotten.  A new spec that silently goes uncollected by CI is the
defect this test exists to prevent; adding it to DELIBERATE_EXCLUSIONS
with an empty reason is not materially different.

Three assertions
----------------
1. coverage: every *.spec.ts in tests/e2e/ is either in the matrix or
   in DELIBERATE_EXCLUSIONS with a non-empty reason.
2. placement: no *.spec.ts remains anywhere outside tests/e2e/ (scoped to
   *.spec.ts, so helpers like user-guide/shared.ts staying put is fine).
3. pin: slide-viewer is in the matrix (the only spec that exercises the
   findings drawer, which ws4b and ws4e depend on).

Plus two that sharding needs:

5. no spec is in two shards (it would run twice, and a shard's balance
   would be wrong).
6. the job actually hands each shard's list to the runner — a list the
   run step ignores would make every assertion above decorative.

DELIBERATE_EXCLUSIONS — two distinct kinds
------------------------------------------
KIND A — Documentation screenshot generators (keys 01-* through 07-*):
  These specs write PNG screenshots to docs/user-guide/images when run.
  They are NEVER meant to run in CI, and there is no expectation that they
  will return to the matrix.

KIND B — Quarantined specs pending re-authoring (FOLLOW-UP marker):
  These were written against an older app shell that has since been
  redesigned (AppLayout / brand-header / sidebar / deck-history replaced
  the shell these specs target).  They were surfaced — not caused — by
  the matrix widening that added them to CI collection.  They are
  expected to return to the matrix once re-authored against the current
  shell.  Search for FOLLOW-UP to find them all.
"""
import yaml
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths (anchored from this file — never cwd-relative)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "test.yml"
E2E_DIR = REPO_ROOT / "frontend" / "tests" / "e2e"
FRONTEND_TESTS = REPO_ROOT / "frontend" / "tests"

# ---------------------------------------------------------------------------
# Explicit exclusions — specs that live in tests/e2e/ but are NOT in the
# matrix because they are documentation screenshot generators, not functional
# specs.  Each must have a non-empty reason; an empty reason fails the test.
# ---------------------------------------------------------------------------
DELIBERATE_EXCLUSIONS: dict[str, str] = {
    "01-generating-slides": (
        "Documentation screenshot generator, not a functional spec. "
        "Writes PNG screenshots to docs/user-guide/images when run."
    ),
    "02-creating-profiles": (
        "Documentation screenshot generator, not a functional spec. "
        "Writes PNG screenshots to docs/user-guide/images when run."
    ),
    "03-advanced-configuration": (
        "Documentation screenshot generator, not a functional spec. "
        "Writes PNG screenshots to docs/user-guide/images when run."
    ),
    "04-retrieving-feedback": (
        "Documentation screenshot generator, not a functional spec. "
        "Writes PNG screenshots to docs/user-guide/images when run."
    ),
    "06-uploading-images": (
        "Documentation screenshot generator, not a functional spec. "
        "Writes PNG screenshots to docs/user-guide/images when run."
    ),
    "07-exporting-to-google-slides": (
        "Documentation screenshot generator, not a functional spec. "
        "Writes PNG screenshots to docs/user-guide/images when run."
    ),
    # KIND B — quarantined specs pending re-authoring against the current AppLayout shell.
    # Failures are pre-existing; they were surfaced, not caused, by the matrix widening.
    # FOLLOW-UP: re-author each against AppLayout / brand-header / sidebar / deck-history
    # and restore to the matrix.
    "save-points-versioning": (
        "FOLLOW-UP: pre-existing failures surfaced by matrix widening; not caused by it. "
        "22 failures: spec targets the pre-redesign app shell — selectors "
        "'New Session' (button, removed from frontend/src/), role=navigation (app-shell "
        "landmark, now only on breadcrumb/tab-strip), and 'Chat' level-2 heading no longer "
        "exist in the current AppLayout/brand-header/sidebar shell. "
        "Needs re-authoring against the current shell before returning to the matrix."
    ),
    "share-link": (
        "FOLLOW-UP: pre-existing failures surfaced by matrix widening; not caused by it. "
        "4 failures: spec targets the pre-redesign app shell — selector "
        "'New Session' (button removed from frontend/src/) and role=navigation "
        "(app-shell landmark replaced by AppLayout/brand-header/sidebar). "
        "Needs re-authoring against the current shell before returning to the matrix."
    ),
    "slide-generator": (
        "FOLLOW-UP: pre-existing failures surfaced by matrix widening; not caused by it. "
        "3 failures: spec targets the pre-redesign app shell — selector "
        "'New Session' (button removed from frontend/src/), role=navigation "
        "(app-shell landmark), and tool-picker/deck-prompt UI selectors that have drifted. "
        "Needs re-authoring against the current AppLayout shell before returning to the matrix."
    ),
    "routing": (
        "FOLLOW-UP: pre-existing failures surfaced by matrix widening; not caused by it. "
        "3 failures: spec targets the pre-redesign app shell — selectors "
        "'New Session' (button removed from frontend/src/) and role=navigation "
        "(app-shell landmark replaced by AppLayout/brand-header/sidebar). "
        "Needs re-authoring against the current shell before returning to the matrix."
    ),
    "navigation": (
        "FOLLOW-UP: pre-existing failures surfaced by matrix widening; not caused by it. "
        "2 failures: spec targets the pre-redesign app shell — selectors "
        "'New Session' (button removed from frontend/src/) and role=navigation "
        "(app-shell landmark replaced by AppLayout/brand-header/sidebar). "
        "Needs re-authoring against the current shell before returning to the matrix."
    ),
    "slide-host-frame": (
        "FOLLOW-UP: pre-existing failures surfaced by matrix widening; not caused by it. "
        "1 failure: spec pins a four-surface contract map against "
        "src/components/SlidePanel/SlideSelection.tsx, which no longer exists anywhere "
        "in frontend/src/. "
        "Needs re-authoring against the current slide panel component before returning to the matrix."
    ),
    "genie-detail-panel": (
        "FOLLOW-UP: pre-existing failures surfaced by matrix widening; not caused by it. "
        "1 failure: spec uses selector 'add-tool-genie' / tool-picker that has drifted "
        "from the current UI (tool-picker UI redesigned, selector no longer present). "
        "Needs re-authoring against the current tool-picker surface before returning to the matrix."
    ),
}


def _e2e_job() -> dict:
    """Parse the workflow with yaml.safe_load; never a regex."""
    with open(WORKFLOW) as f:
        wf = yaml.safe_load(f)
    return wf["jobs"]["e2e-tests"]


def _load_shards() -> list[dict]:
    """The matrix is a list of shards, each ``{shard: <n>, specs: [<stem>, ...]}``."""
    shards = _e2e_job()["strategy"]["matrix"]["include"]
    assert shards, "the e2e matrix declares no shards"
    for entry in shards:
        assert isinstance(entry.get("specs"), list) and entry["specs"], (
            f"e2e shard {entry.get('shard')!r} has no `specs:` list"
        )
    return shards


def _load_matrix() -> list[str]:
    """Every spec stem named by any shard, duplicates kept (see the test below)."""
    return [spec for entry in _load_shards() for spec in entry["specs"]]


def _e2e_spec_stems() -> set[str]:
    """All *.spec.ts stems directly in tests/e2e/ (non-recursive)."""
    return {p.stem.removesuffix(".spec") for p in E2E_DIR.glob("*.spec.ts")}


# ---------------------------------------------------------------------------
# Assertion 4 — no nested specs
# ---------------------------------------------------------------------------
def test_no_nested_e2e_specs():
    """No *.spec.ts may exist inside a sub-directory of frontend/tests/e2e/.

    The e2e matrix names specs by their flat stem (e.g. "slide-viewer").  A
    spec at tests/e2e/subdir/foo.spec.ts cannot be named in that flat list, so
    a flat matrix can never collect it.  The correct fix is to flatten it into
    tests/e2e/ — not to silently ignore it or expand the matrix format to
    accommodate subdirectories.
    """
    nested = [
        p.relative_to(E2E_DIR)
        for p in E2E_DIR.rglob("*.spec.ts")
        if p.parent != E2E_DIR
    ]
    assert not nested, (
        "Found *.spec.ts files in sub-directories of frontend/tests/e2e/:\n"
        + "\n".join(f"  - frontend/tests/e2e/{p}" for p in sorted(nested))
        + "\n\nThe e2e matrix names specs by flat stem only. A nested spec"
        " cannot be named in the matrix and will never run in CI. Flatten it"
        " into frontend/tests/e2e/ and add it to the matrix."
    )


# ---------------------------------------------------------------------------
# Assertion 1 — coverage
# ---------------------------------------------------------------------------
def test_every_spec_is_in_matrix_or_excluded_with_reason():
    """Every *.spec.ts in tests/e2e/ is either in the matrix or in
    DELIBERATE_EXCLUSIONS with a non-empty reason.
    """
    matrix = set(_load_matrix())
    specs = _e2e_spec_stems()

    # Guard: a coverage check that discovers zero files is vacuously true —
    # it reports success over an empty universe, which is the exact failure mode
    # these guards exist to prevent elsewhere.  If this fires, E2E_DIR is wrong
    # or the directory has been emptied; fix the path, not the assertion.
    assert specs, (
        f"No *.spec.ts files found in {E2E_DIR.resolve()!s}. "
        "Either E2E_DIR points at the wrong path or the directory is empty. "
        "A coverage guard that discovers nothing must fail loudly rather than "
        "report success over an empty set."
    )

    # First validate that every DELIBERATE_EXCLUSIONS entry has a non-empty
    # reason — an empty reason is not allowed.
    empty_reasons = {stem for stem, reason in DELIBERATE_EXCLUSIONS.items() if not reason.strip()}
    assert not empty_reasons, (
        f"DELIBERATE_EXCLUSIONS entries must have a non-empty reason. "
        f"These have an empty reason: {sorted(empty_reasons)}"
    )

    # No spec may be in both the matrix and DELIBERATE_EXCLUSIONS — if it is in
    # the matrix it will still run in CI even though it is supposed to be excluded.
    both = matrix & set(DELIBERATE_EXCLUSIONS.keys())
    assert not both, (
        f"These specs are in BOTH the e2e matrix and DELIBERATE_EXCLUSIONS:\n"
        + "\n".join(f"  - {s}" for s in sorted(both))
        + "\n\nA spec in DELIBERATE_EXCLUSIONS will still run in CI if it is also "
        "in the matrix.  Remove it from the matrix."
    )

    # Every spec must be in the matrix or explicitly excluded.
    uncovered = specs - matrix - set(DELIBERATE_EXCLUSIONS.keys())
    assert not uncovered, (
        f"The following *.spec.ts files in frontend/tests/e2e/ are neither in the "
        f"e2e matrix nor in DELIBERATE_EXCLUSIONS:\n"
        + "\n".join(f"  - {s}" for s in sorted(uncovered))
        + "\n\nAdd each to the matrix in .github/workflows/test.yml, or add it to "
        "DELIBERATE_EXCLUSIONS in this file with a non-empty reason."
    )


# ---------------------------------------------------------------------------
# Assertion 2 — placement
# ---------------------------------------------------------------------------
def test_no_spec_outside_e2e():
    """No *.spec.ts remains anywhere outside frontend/tests/e2e/.

    Scoped to *.spec.ts only, so helpers such as user-guide/shared.ts
    staying in frontend/tests/user-guide/ does not trip this assertion.
    """
    # Search the whole frontend/tests/ tree but exclude e2e/ itself.
    stray_specs = [
        p.relative_to(FRONTEND_TESTS)
        for p in FRONTEND_TESTS.rglob("*.spec.ts")
        if E2E_DIR not in p.parents and p.parent != E2E_DIR
    ]
    assert not stray_specs, (
        f"Found *.spec.ts files outside frontend/tests/e2e/:\n"
        + "\n".join(f"  - {p}" for p in sorted(stray_specs))
        + "\n\nMove them into frontend/tests/e2e/ and fix their relative imports."
    )


# ---------------------------------------------------------------------------
# Assertion 3 — pin slide-viewer
# ---------------------------------------------------------------------------
def test_slide_viewer_is_in_matrix():
    """slide-viewer must be in the e2e matrix.

    It is the only spec exercising the feedback drawer and findings
    panel, which ws4b and ws4e depend on as their primary frontend
    surface.  Pinning it here means a future accidental removal is loud.
    """
    matrix = set(_load_matrix())
    assert "slide-viewer" in matrix, (
        "'slide-viewer' is missing from the e2e matrix in "
        ".github/workflows/test.yml.  It is the only spec covering the "
        "findings drawer — restore it to the matrix."
    )


# ---------------------------------------------------------------------------
# Assertion 5 — each spec in exactly one shard
# ---------------------------------------------------------------------------
def test_no_spec_is_in_two_shards():
    """A spec named by two shards runs twice and skews both shards' run time."""
    seen: dict[str, list] = {}
    for entry in _load_shards():
        for spec in entry["specs"]:
            seen.setdefault(spec, []).append(entry.get("shard"))
    duplicated = {spec: shards for spec, shards in seen.items() if len(shards) > 1}
    assert not duplicated, (
        "These specs are named by more than one e2e shard in "
        ".github/workflows/test.yml:\n"
        + "\n".join(f"  - {s} (shards {shards})" for s, shards in sorted(duplicated.items()))
        + "\n\nKeep each spec in exactly one shard."
    )


# ---------------------------------------------------------------------------
# Assertion 6 — the shard's list is what actually runs
# ---------------------------------------------------------------------------
def test_run_step_passes_the_shards_specs_to_the_runner():
    """The shard lists are only coverage if the run step consumes them.

    Every assertion above inspects ``specs:``; none would notice a run step
    that ran a hard-coded list, or nothing, instead.
    """
    runs = [step.get("run", "") for step in _e2e_job()["steps"]]
    consuming = [
        run for run in runs
        if "scripts/run_e2e_specs.sh" in run and "matrix.specs" in run
    ]
    assert consuming, (
        "No step of the e2e-tests job passes `matrix.specs` to "
        "scripts/run_e2e_specs.sh, so the shard lists in "
        ".github/workflows/test.yml are not what runs. Expected a step like:\n"
        "  run: ./scripts/run_e2e_specs.sh ${{ join(matrix.specs, ' ') }}"
    )


# ---------------------------------------------------------------------------
# Assertion 7 — a change to the runner runs E2E
# ---------------------------------------------------------------------------
def test_runner_changes_trigger_e2e():
    """e2e-tests runs only when the `frontend` paths filter matches.

    The runner script decides how every spec runs, so a PR that edits only it
    must still run E2E — otherwise the change that most needs E2E skips it.
    """
    with open(WORKFLOW) as f:
        wf = yaml.safe_load(f)
    assert "needs.changes.outputs.frontend" in str(_e2e_job()["if"]), (
        "e2e-tests is no longer gated on the `frontend` filter; update this test "
        "to check whichever filter gates it now"
    )
    filter_step = next(
        s for s in wf["jobs"]["changes"]["steps"] if s.get("id") == "filter"
    )
    frontend_paths = yaml.safe_load(filter_step["with"]["filters"])["frontend"]
    missing = [
        p for p in ("scripts/run_e2e_specs.sh", ".github/workflows/test.yml")
        if p not in frontend_paths
    ]
    assert not missing, (
        "The `frontend` paths filter in .github/workflows/test.yml (which gates "
        f"e2e-tests) does not match {missing}, so a PR changing only that would "
        "skip E2E."
    )
