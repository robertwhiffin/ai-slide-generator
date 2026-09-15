"""Guard: a CI job that provisions PostgreSQL must tell the tests it did.

The defect this exists to prevent, measured on feat/ws4d-wiring
---------------------------------------------------------------
Eight jobs in .github/workflows/test.yml provisioned a ``postgres:15`` service
and exported only ``DATABASE_URL``.  ``TELLR_TEST_POSTGRES_URL`` — the variable
every PostgreSQL suite in this repo reads — was set in NO job.  So all six
postgres-marked modules under tests/unit/ self-skipped in CI while passing on
every developer's laptop: CI was strictly weaker than a laptop, and silently,
because a skip is green.

A guard on the *shape* rather than on a list of names
----------------------------------------------------
The check is derived from the workflow itself: for every job that starts a
postgres service, the URL exported to the tests must reconstruct THAT job's own
service — user, password, database and host port all read out of the service
block, never hard-coded here.  A ninth postgres job added later is covered the
moment it exists; a job whose service credentials change and whose env does not
fails immediately.

``postgresql+psycopg2://`` is required, not merely accepted: it is what the
default in every ``_PG_URL``/``_ADMIN_URL`` in the repo names, and the suites
carry that URL through ``make_url(...).set(database=...)`` into a per-test
throwaway database, so the driver token has to survive verbatim.
"""
from pathlib import Path

import pytest
import yaml
from sqlalchemy.engine import make_url

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "test.yml"

_VAR = "TELLR_TEST_POSTGRES_URL"


def _workflow() -> dict:
    with open(WORKFLOW) as fh:
        return yaml.safe_load(fh)


def _postgres_jobs() -> dict:
    """{job_name: job_dict} for every job that provisions a postgres service."""
    jobs = {}
    for name, job in (_workflow().get("jobs") or {}).items():
        for svc in (job.get("services") or {}).values():
            if isinstance(svc, dict) and str(svc.get("image", "")).startswith("postgres"):
                jobs[name] = job
                break
    return jobs


def _expected_url(job: dict) -> str:
    """Rebuild the URL from the job's OWN service block.

    Both halves of the comparison come from the workflow, but from two
    independent places in it: this side from ``services.postgres``, the other from
    the job's or step's ``env``.  Nothing here is copied from the env being
    checked, so the assertion cannot be satisfied by a value agreeing with
    itself.
    """
    svc = next(
        s for s in job["services"].values()
        if isinstance(s, dict) and str(s.get("image", "")).startswith("postgres")
    )
    env = svc.get("env") or {}
    user = env["POSTGRES_USER"]
    password = env["POSTGRES_PASSWORD"]
    database = env["POSTGRES_DB"]

    # ports entries are "<host>:<container>"; the tests reach the service on the
    # host port, which is what has to appear in the URL.
    ports = [str(p) for p in (svc.get("ports") or [])]
    assert ports, f"the postgres service declares no ports mapping: {svc!r}"
    host_port = ports[0].split(":")[0]

    return f"postgresql+psycopg2://{user}:{password}@localhost:{host_port}/{database}"


def _visible_values(job: dict) -> dict:
    """{where: value} for every place in *job* that sets the variable."""
    found = {}
    job_level = (job.get("env") or {}).get(_VAR)
    if job_level is not None:
        found["job env"] = job_level
    for idx, step in enumerate(job.get("steps") or []):
        if not isinstance(step, dict):
            continue
        value = (step.get("env") or {}).get(_VAR)
        if value is not None:
            found[f"step {idx} ({step.get('name') or step.get('uses') or 'run'})"] = value
    return found


def _pytest_steps(job: dict) -> list:
    """Indexes of steps whose run block invokes pytest."""
    return [
        idx
        for idx, step in enumerate(job.get("steps") or [])
        if isinstance(step, dict) and "pytest" in (step.get("run") or "")
    ]


# ---------------------------------------------------------------------------
# The universe must not be empty — a coverage guard that discovers nothing
# reports success over an empty set, which is the failure mode it exists to stop.
# ---------------------------------------------------------------------------


def test_the_workflow_provisions_postgres_somewhere():
    jobs = _postgres_jobs()
    assert jobs, (
        f"no job in {WORKFLOW} provisions a postgres service. Either the "
        "workflow path is wrong or every service was removed; a guard that "
        "iterates an empty set passes vacuously, so this fails instead."
    )


# ---------------------------------------------------------------------------
# Assertion 1 — every postgres job exports the variable
# ---------------------------------------------------------------------------


def test_every_postgres_job_exports_the_test_url():
    missing = sorted(name for name, job in _postgres_jobs().items() if not _visible_values(job))
    assert not missing, (
        f"These jobs provision a postgres service but never export {_VAR}:\n"
        + "\n".join(f"  - {n}" for n in missing)
        + f"\n\nEvery PostgreSQL suite in this repo reads {_VAR} and SELF-SKIPS "
        "when it is unset, so those jobs run a database no test can see and the "
        "suites pass by skipping. Add it to the job's env, or to the env of the "
        "step that runs pytest."
    )


# ---------------------------------------------------------------------------
# Assertion 2 — the exported URL names that job's own service
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("job_name", sorted(_postgres_jobs()))
def test_the_exported_url_matches_that_jobs_own_service(job_name):
    job = _postgres_jobs()[job_name]
    expected = _expected_url(job)
    values = _visible_values(job)
    assert values, f"{job_name} exports no {_VAR}"

    for where, actual in values.items():
        # Driver FIRST, then the whole URL. The order is deliberate: `expected`
        # hard-codes postgresql+psycopg2, so an equality check placed first would
        # fire on a wrong driver and this assertion could never run — an
        # unreachable assertion that looks like coverage. Checking the driver
        # first leaves both individually reachable, each with its own diagnosis.
        url = make_url(actual)
        assert url.drivername == "postgresql+psycopg2", (
            f"{job_name}: {_VAR} at {where} uses driver "
            f"{url.drivername!r}. The suites carry this URL through "
            "make_url(...).set(database=...) into a throwaway database, and "
            "their documented default is postgresql+psycopg2 — the driver token "
            "has to survive verbatim."
        )

        assert actual == expected, (
            f"{job_name}: {_VAR} at {where} is\n  {actual}\nbut this job's own "
            f"postgres service is reachable at\n  {expected}\n"
            "The URL must name the service the job actually started — a URL "
            "pointing anywhere else makes the suites skip (unreachable) or, "
            "worse, share a database with another job."
        )


# ---------------------------------------------------------------------------
# Assertion 3 — every pytest step in a postgres job actually SEES the variable
# ---------------------------------------------------------------------------


def test_every_pytest_step_in_a_postgres_job_sees_the_url():
    """A step-level env on the wrong step is the same gap as no env at all.

    GitHub gives a step its job's env plus its own; a value set on some other
    step is invisible to the one running pytest.  A job with no pytest step at
    all must set it at job level, which is the only place a future pytest step
    would inherit it from.
    """
    broken = []
    for name, job in _postgres_jobs().items():
        job_level = _VAR in (job.get("env") or {})
        steps = job.get("steps") or []
        pytest_steps = _pytest_steps(job)

        if not pytest_steps:
            if not job_level:
                broken.append(
                    f"{name}: runs no pytest step and does not set {_VAR} at job "
                    "level, so a pytest step added later inherits nothing"
                )
            continue

        for idx in pytest_steps:
            if job_level or _VAR in ((steps[idx].get("env") or {})):
                continue
            broken.append(
                f"{name}: step {idx} ({steps[idx].get('name') or 'run'}) invokes "
                f"pytest but neither it nor the job sets {_VAR}"
            )

    assert not broken, "\n".join(["Postgres jobs whose pytest cannot see the URL:"] + broken)


# ---------------------------------------------------------------------------
# Assertion 4 — the pin. unit-tests is where the postgres-marked files LIVE.
# ---------------------------------------------------------------------------


def test_the_unit_tests_job_provisions_postgres():
    """Six modules under tests/unit/ need a database; unit-tests is what runs them.

    Removing this service is the cheapest possible way to put the repo back in
    the state that motivated this file — the suites would go on reporting green
    by skipping — so the removal has to be loud.
    """
    assert "unit-tests" in _postgres_jobs(), (
        "the unit-tests job no longer provisions a postgres service. "
        "tests/unit/ holds five pytest.mark.postgres modules plus one that skips "
        "itself at import; without a service in the job that RUNS them they all "
        "self-skip, and a skip is indistinguishable from a pass in CI."
    )


def test_the_postgres_marked_unit_files_still_live_under_tests_unit():
    """Pairs with the test above: the service is only the right fix while the
    files are there.

    If a future change moves them to tests/integration/, this fails and points at
    the service that has become dead weight — rather than leaving a postgres
    container starting on every backend PR for nothing.
    """
    unit_dir = REPO_ROOT / "tests" / "unit"
    marked = sorted(
        p.name for p in unit_dir.glob("test_*.py")
        if "TELLR_TEST_POSTGRES_URL" in p.read_text()
    )
    assert len(marked) >= 6, (
        "expected at least six PostgreSQL-dependent modules under tests/unit/, "
        f"found {marked}. If they moved, move the postgres service to whichever "
        "job now runs them and update test_the_unit_tests_job_provisions_postgres."
    )
