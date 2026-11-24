"""Guard: CI runs the export engine's suites with the sidecar installed (I3).

The unit job collects the export suites, but every test that needs the sidecar skips there,
for its node_modules and Chromium are not installed: 499 engine tests never ran in CI. The
``export-engine-tests`` job installs them as the deployed app's boot does and runs the
suites, the sidecar's process-tree and timeout tests included, on the unit job's triggers
and on a change to the sidecar alone. This pins what that takes, so a later edit cannot
quietly drop a step or the timeout file.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "test.yml"
JOB = "export-engine-tests"
SUITES = '-k "export or huashu or google"'
NO_NETWORK = '-m "not network"'
# How the job's comment tells a developer to run the deselected tests themselves.
HAND_RUN = 'pytest tests/unit -m network -k "export or huashu or google"'


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _steps() -> list[dict]:
    return _workflow()["jobs"][JOB]["steps"]


def _step_running(fragment: str) -> dict:
    (step,) = [step for step in _steps() if fragment in step.get("run", "")]
    return step


def test_it_runs_on_the_unit_jobs_triggers_and_the_sidecars_own() -> None:
    jobs = _workflow()["jobs"]
    assert jobs[JOB]["needs"] == jobs["unit-tests"]["needs"] == "changes"
    assert jobs["unit-tests"]["if"] in jobs[JOB]["if"]
    assert "needs.changes.outputs.sidecar == 'true'" in jobs[JOB]["if"]
    filters = yaml.safe_load(
        next(step for step in jobs["changes"]["steps"] if step.get("id") == "filter")["with"]["filters"]
    )
    assert "services/pptx-emit-huashu/**" in filters["sidecar"]


def test_it_installs_the_sidecar_as_the_apps_boot_does() -> None:
    """With the sidecar's own setup.sh, which the deployed app's boot runs: its node_modules,
    bundled libraries, and the font bundle with the fontconfig the sidecar's Chromium reads.
    setup.sh only warns when the fonts do not extract, so the job checks they are in place,
    or the suites would draw the runner's DejaVu, a face production never draws."""
    setup = _step_running("sh setup.sh")
    assert setup["working-directory"] == "services/pptx-emit-huashu"
    assert "fonts/fonts.conf" in setup["run"] and "exit 1" in setup["run"], setup["run"]
    chromium = _step_running("install --with-deps chromium")
    assert chromium["working-directory"] == "services/pptx-emit-huashu"
    assert "node_modules/playwright/cli.js" in chromium["run"]


def test_it_installs_the_frontends_esbuild_for_the_ui_documents() -> None:
    assert _step_running("npm ci")["working-directory"] == "frontend"


def test_it_runs_every_export_suite_the_timeout_file_included_in_parallel() -> None:
    run = _step_running("pytest")["run"]
    assert "tests/unit" in run and SUITES in run and "-n auto" in run
    assert "timeout" not in run, f"the timeout file must run here: {run}"
    assert not re.search(r"--ignore|--deselect", run), run


def test_it_leaves_out_the_tests_that_load_the_network(pytestconfig: pytest.Config) -> None:
    """A test marked ``network`` loads the slide CSP's CDNs live, so a CDN's hiccup would
    fail a required job: the job deselects the marker, which pytest knows (an unknown one
    would select nothing silently), and its comment says how to run those tests by hand."""
    run = _step_running("pytest")["run"]
    assert NO_NETWORK in run, run
    markers = [marker.split(":", 1)[0] for marker in pytestconfig.getini("markers")]
    assert "network" in markers, markers
    assert HAND_RUN in WORKFLOW.read_text(encoding="utf-8"), (
        f"the job's comment does not say how to run the network tests by hand ({HAND_RUN!r})"
    )
