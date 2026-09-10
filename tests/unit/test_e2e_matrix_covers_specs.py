"""Guard: the e2e matrix in .github/workflows/test.yml must name every
*.spec.ts in frontend/tests/e2e/ or list it in DELIBERATE_EXCLUSIONS
with a non-empty reason.

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


def _load_matrix() -> list[str]:
    """Parse the workflow with yaml.safe_load; never a regex."""
    with open(WORKFLOW) as f:
        wf = yaml.safe_load(f)
    return wf["jobs"]["e2e-tests"]["strategy"]["matrix"]["test"]


def _e2e_spec_stems() -> set[str]:
    """All *.spec.ts stems directly in tests/e2e/ (non-recursive)."""
    return {p.stem.removesuffix(".spec") for p in E2E_DIR.glob("*.spec.ts")}


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
