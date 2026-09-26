"""Unit runs must never reach the operator's dev database (#271 Task 1).

With no ``DATABASE_URL`` and no Lakebase environment, ``src/core/database.py``
resolves ``postgresql://localhost/ai_slide_generator``, the developer's dev
database. No unit test needs it, but best-effort request/usage logging writes to
whatever ``DATABASE_URL`` resolves to, so an unconfigured unit run wrote rows into
it. ``tests/conftest.py`` therefore:

* refuses to start when ``DATABASE_URL`` names ``ai_slide_generator``;
* supplies a throwaway SQLite URL when ``DATABASE_URL`` is unset, one per xdist
  worker (CI runs ``pytest tests/unit -n auto`` with ``DATABASE_URL`` unset on
  purpose, ``.github/workflows/test.yml``).

The subprocess tests load the REAL ``tests/conftest.py`` as a plugin
(``-p tests.conftest``) against a throwaway probe file, so they measure the
conftest itself rather than a copy of its logic.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from src.core.database import _get_database_url

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFTEST = _REPO_ROOT / "tests" / "conftest.py"

_PROBE = """
import json, os, pathlib

def test_record_{n}():
    from src.core.database import _get_database_url
    out = pathlib.Path(os.environ["T271_PROBE_OUT"])
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    (out / f"{{worker}}-{n}.json").write_text(json.dumps({{
        "worker": worker,
        "url": _get_database_url(),
        "defaulted": os.environ.get("TELLR_TESTS_DATABASE_URL_DEFAULTED"),
    }}))
"""


def _run_probe(tmp_path: Path, extra_args: list[str], env_updates: dict[str, str]):
    probe_dir = tmp_path / "probe"
    out_dir = tmp_path / "out"
    probe_dir.mkdir()
    out_dir.mkdir()
    (probe_dir / "test_probe.py").write_text("\n".join(_PROBE.format(n=n) for n in range(4)))
    env = {
        k: v
        for k, v in os.environ.items()
        if k
        not in {
            "DATABASE_URL",
            "TELLR_TESTS_DATABASE_URL_DEFAULTED",
            "PYTEST_XDIST_WORKER",
            "PYTEST_XDIST_WORKER_COUNT",
            "PYTEST_XDIST_TESTRUNUID",
            "PYTEST_ADDOPTS",
        }
    }
    env["PYTHONPATH"] = os.pathsep.join(
        [str(_REPO_ROOT), str(_REPO_ROOT / "packages" / "databricks-tellr")]
    )
    env["T271_PROBE_OUT"] = str(out_dir)
    env.update(env_updates)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "tests.conftest",
            *extra_args,
            str(probe_dir / "test_probe.py"),
        ],
        cwd=probe_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    records = [json.loads(p.read_text()) for p in sorted(out_dir.glob("*.json"))]
    return proc, records


def test_a_unit_run_never_resolves_the_operator_dev_database():
    url = _get_database_url()
    assert "ai_slide_generator" not in url, url
    if os.environ.get("TELLR_TESTS_DATABASE_URL_DEFAULTED") == "1":
        assert url.startswith("sqlite:///"), url


def test_the_default_is_installed_before_any_src_import():
    text = _CONFTEST.read_text()
    default_at = text.index('os.environ["DATABASE_URL"]')
    first_src_import = text.index("from src.")
    assert default_at < first_src_import


def test_each_xdist_worker_gets_its_own_sqlite_file(tmp_path):
    """``--dist each`` runs every probe on both workers, so both must report."""
    proc, records = _run_probe(tmp_path, ["-n", "2", "--dist", "each"], {})
    assert proc.returncode == 0, proc.stdout + proc.stderr

    by_worker: dict[str, set[str]] = {}
    for record in records:
        assert record["defaulted"] == "1", record
        assert record["url"].startswith("sqlite:///"), record
        by_worker.setdefault(record["worker"], set()).add(record["url"])

    assert sorted(by_worker) == ["gw0", "gw1"], (by_worker, proc.stdout)
    # One URL per worker, and the two workers' URLs differ.
    assert all(len(urls) == 1 for urls in by_worker.values()), by_worker
    paths = {next(iter(urls)) for urls in by_worker.values()}
    assert len(paths) == 2, f"xdist workers share one SQLite file: {by_worker}"


def test_an_explicit_database_url_is_left_alone(tmp_path):
    explicit = f"sqlite:///{tmp_path}/explicit.sqlite"
    proc, records = _run_probe(tmp_path, [], {"DATABASE_URL": explicit})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert records and {r["url"] for r in records} == {explicit}, records
    assert {r["defaulted"] for r in records} == {None}, records


def test_a_database_url_naming_the_dev_database_is_refused(tmp_path):
    proc, records = _run_probe(
        tmp_path, [], {"DATABASE_URL": "postgresql://localhost/ai_slide_generator"}
    )
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert records == [], "a test ran against the dev database"
    assert "refusing to run tests against the ai_slide_generator dev database" in (
        proc.stdout + proc.stderr
    ), proc.stdout + proc.stderr
