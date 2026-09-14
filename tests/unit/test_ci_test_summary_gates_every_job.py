"""Guard: ``test-summary`` must actually GATE every job in the workflow.

The defect this exists to prevent, found by review on ws4c C5
-------------------------------------------------------------
``integration-graph`` was added to ``test-summary``'s ``needs:`` and to its echo
block, and it still gated **nothing**: the step's pass/fail decision is a
``for result in "${{ needs.<job>.result }}" …`` loop, and the job was absent from
it.  ``test-summary`` runs ``if: always()``, so a red job printed
``Graph Orchestration: failure`` and the step exited **0**.

A new integration job therefore needs THREE edits, not two:

1. ``needs:`` — makes it a dependency (so the summary waits for it);
2. the echo block — makes its result visible to a human reading the log;
3. **the failure loop — this is the gate.**

``needs:`` alone is a dependency, not a gate.  ws4a's
``test_ci_collects_integration_tests.py`` cannot catch this: it only checks that
a filename appears in some job's ``run:`` block.

THE UNIVERSE IS THE WORKFLOW'S OWN ``jobs:``, NOT ``needs:``
------------------------------------------------------------
This guard's first version derived every one of its assertions from
``test-summary``'s own ``needs:`` list — so a job that exists under ``jobs:`` and
is **absent from ``needs:`` entirely** was invisible to it.  Falsified by review:
a real test job ``integration-ws4d-clone`` was added to the workflow, left out of
``needs:``, and all three assertions still passed.  Such a job runs in CI, prints
its own result and gates nothing at all — the same defect one level up, and a
guard blind to the set both of its checks were drawn from.

Corrections §59 hands exactly this to ws4d and ws4e — *"ws4d and ws4e will clone
this job; name the loop explicitly when they do"* — and forgetting ``needs:`` is
the likeliest clone mistake, because the job block and the three edit sites are
~500 lines apart in one file.

So the universe is ``workflow["jobs"]`` minus ``_GATE_EXEMPT``, an allow-list
that must be **edited** to exempt a job.  A new job is therefore gated, or this
test names it — never neither.

Assertions, and the reverse direction that looks redundant but is not
--------------------------------------------------------------------
An unresolvable expression such as ``${{ needs.integraton-slides.result }}``
(typo) evaluates to the **empty string** in GitHub Actions rather than erroring,
so it can never equal ``failure`` — a silent hole shaped exactly like the one
above, in the other direction.

The job-name pattern below includes DIGITS deliberately: the grep
``'^  [a-z_-]*:'`` that this repo has used before MISSES ``e2e-tests``
(corrections §26, fact 4).
"""

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "test.yml"

SUMMARY_JOB = "test-summary"

#: Jobs deliberately outside the gate, each with a non-empty reason.  An empty
#: reason is not allowed: that is how an exemption becomes indistinguishable from
#: a job somebody forgot (ws4a's collection guard learned the same lesson).
#: Exempting a job is an EDIT here, which is the property that makes this check
#: reach the path — a cloned test job left out of ``needs:`` fails the gate
#: assertion below unless its author comes here and says why.
_GATE_EXEMPT = {
    "changes": (
        "the dorny/paths-filter job every other job's `if:` reads; it runs no "
        "tests, and it is already a `needs:` of the jobs it gates, so a failure "
        "skips them and they report as skipped rather than passing"
    ),
    SUMMARY_JOB: "it IS the gate; it cannot gate itself",
}

#: ``needs.<job>.result``.  Digits included — see the module docstring.
_NEEDS_RESULT = re.compile(r"needs\.([A-Za-z0-9_-]+)\.result")


def _jobs() -> dict:
    """Every top-level job in the workflow, keyed by id.

    Parsed with ``yaml.safe_load``, never a regex over indentation: the grep this
    repo has used before (``'^  [a-z_-]*:'``) both misses ``e2e-tests`` and would
    match a nested key.
    """
    with open(WORKFLOW) as f:
        workflow = yaml.safe_load(f)
    jobs = workflow.get("jobs") or {}
    assert jobs, f"no jobs found in {WORKFLOW}; a check over nothing must fail"
    assert SUMMARY_JOB in jobs, (
        f"{SUMMARY_JOB} is not a job in {WORKFLOW}; either it was renamed (update "
        "this guard) or the gate has been deleted."
    )
    return jobs


def _summary_job() -> dict:
    return _jobs()[SUMMARY_JOB]


def _jobs_that_must_be_gated() -> list[str]:
    """Every job in the workflow except the explicitly exempt ones.

    The exempt names are checked against the real job list, so a renamed or
    deleted job cannot leave a stale exemption behind quietly widening the hole.
    """
    jobs = _jobs()
    stale = sorted(name for name in _GATE_EXEMPT if name not in jobs)
    assert not stale, (
        "these names are exempted from the gate but are not jobs in the "
        f"workflow any more, so the exemption is stale: {stale}.  Remove them "
        "from _GATE_EXEMPT (or fix the name) rather than leaving an exemption "
        "that matches nothing."
    )
    empty = sorted(name for name, why in _GATE_EXEMPT.items() if not (why or "").strip())
    assert not empty, (
        f"these exemptions have no reason: {empty}.  An exemption without a "
        "reason is indistinguishable from a job somebody forgot."
    )
    return sorted(set(jobs) - set(_GATE_EXEMPT))


def _summary_run_script() -> str:
    steps = _summary_job().get("steps") or []
    scripts = [
        step["run"]
        for step in steps
        if isinstance(step, dict) and isinstance(step.get("run"), str)
    ]
    assert scripts, f"{SUMMARY_JOB} has no run: step to inspect"
    return "\n".join(scripts)


def _needed_jobs() -> list[str]:
    needs = _summary_job().get("needs") or []
    if isinstance(needs, str):  # single-job form
        needs = [needs]
    assert needs, (
        f"{SUMMARY_JOB} declares no needs:.  A gate over an empty set of jobs "
        "reports success over nothing, which is the failure mode this guard "
        "exists to prevent."
    )
    return list(needs)


def _jobs_in_the_failure_loop() -> set[str]:
    """The jobs the ``for result in …`` loop actually tests.

    Parsed from the loop construct alone — NOT from the whole script.  The echo
    block references every job too, so scanning the whole ``run:`` would report
    success for a job that is only echoed, which is precisely the hole found on
    C5.
    """
    script = _summary_run_script()
    start = script.find("for result in")
    assert start != -1, (
        "no `for result in …` loop found in test-summary's run: block.  If the "
        "gate was rewritten in another shape, update this guard to parse it — do "
        "not delete it: the gate is the only thing that turns a red job into a "
        "red check."
    )
    end = script.find("; do", start)
    assert end != -1, (
        "found `for result in` with no terminating `; do` — the loop could not be "
        "delimited, so this guard cannot see what it tests.  Fix the parse."
    )
    loop = script[start:end]

    jobs = set(_NEEDS_RESULT.findall(loop))
    assert jobs, (
        "the failure loop references no needs.<job>.result at all.  A check that "
        "finds nothing must fail rather than pass: either the loop's shape "
        f"changed or the gate is empty.  Loop text was:\n{loop}"
    )
    return jobs


def test_every_job_in_the_workflow_is_gated_or_explicitly_exempt():
    """The assertion the ``needs:``-derived version could not make.

    A job can only fail the build if it is BOTH a dependency of ``test-summary``
    (so the summary waits for it) and named in the failure loop (so its result is
    read).  Derived from ``jobs:``, so a job nobody wired up is caught here
    rather than running green-and-toothless for a workstream or two.
    """
    must_be_gated = _jobs_that_must_be_gated()
    needed = set(_needed_jobs())
    gated = _jobs_in_the_failure_loop()

    missing = {
        job: [
            place
            for place, present in (("needs:", job in needed), ("failure loop", job in gated))
            if not present
        ]
        for job in must_be_gated
        if job not in needed or job not in gated
    }
    assert missing == {}, (
        "these jobs exist in .github/workflows/test.yml but do not gate the "
        "build — each runs, prints its own result and cannot fail the check:\n"
        + "\n".join(f"  - {job}: missing from {', '.join(where)}" for job, where in sorted(missing.items()))
        + "\n\nAdd each to test-summary's needs:, its echo block and the "
        '`for result in "${{ needs.<job>.result }}" …` loop — or, if it really '
        "must sit outside the gate, add it to _GATE_EXEMPT in this file with a "
        "reason."
    )


def test_every_needed_job_is_tested_by_the_failure_loop():
    """Every job in ``needs:`` must appear in the loop that decides pass/fail."""
    needed = _needed_jobs()
    gated = _jobs_in_the_failure_loop()

    ungated = [job for job in needed if job not in gated]
    assert not ungated, (
        "these jobs are in test-summary's needs: but NOT in its failure loop, so "
        "they gate nothing — the summary step exits 0 even when they fail:\n"
        + "\n".join(f"  - {job}" for job in ungated)
        + '\n\nAdd each to the `for result in "${{ needs.<job>.result }}" …` loop '
        "in .github/workflows/test.yml."
    )


def test_the_failure_loop_references_no_job_outside_needs():
    """A job in the loop but not in ``needs:`` evaluates to the empty string.

    GitHub Actions resolves an unknown ``needs.<job>.result`` to ``""`` rather
    than failing, so it can never equal ``failure`` — the same silent hole in
    the other direction, and the shape a typo takes.
    """
    needed = set(_needed_jobs())
    gated = _jobs_in_the_failure_loop()

    unknown = sorted(job for job in gated if job not in needed)
    assert not unknown, (
        "the failure loop tests these jobs, which are NOT in test-summary's "
        "needs::\n"
        + "\n".join(f"  - {job}" for job in unknown)
        + "\n\nAn unresolvable needs.<job>.result is the empty string, never "
        "'failure', so each of these silently tests nothing.  Fix the name or "
        "add the job to needs:."
    )


def test_every_needed_job_is_echoed_in_the_summary():
    """The reporting surface, not the gate — but a missing line hides a result.

    Kept separate from the gate assertion so a missing echo line can never be
    mistaken for, or mask, a missing gate entry.
    """
    script = _summary_run_script()
    echoed = {
        job
        for line in script.splitlines()
        if line.strip().startswith("echo")
        for job in _NEEDS_RESULT.findall(line)
    }
    assert echoed, "no echo line in test-summary references a job result"

    missing = [job for job in _needed_jobs() if job not in echoed]
    assert not missing, (
        "these jobs are in test-summary's needs: but their result is never "
        "echoed, so a reader of the log cannot see them:\n"
        + "\n".join(f"  - {job}" for job in missing)
    )
