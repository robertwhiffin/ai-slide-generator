"""Guard: unit-test collection produces identical node IDs across independent runs.

Two separate subprocess invocations of ``pytest --collect-only -q tests/unit``
must yield exactly the same sorted list of node IDs.  Any ``ids=`` callable that
embeds an object memory address (e.g. ``ids=lambda v: str(v)`` applied to
functions) will produce a different address in each process and will cause this
test to fail.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

_PROJECT_ROOT = pathlib.Path(__file__).parent.parent.parent


def _collect_node_ids() -> list[str]:
    """Return sorted test node IDs collected from tests/unit in a fresh subprocess."""
    extra_path = os.pathsep.join([
        str(_PROJECT_ROOT),
        str(_PROJECT_ROOT / "packages" / "databricks-tellr"),
    ])
    env = {
        **os.environ,
        "PYTHONPATH": extra_path,
        "DATABASE_URL": "sqlite:////tmp/guard-collect.sqlite",
    }
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "--collect-only", "-q",
            "-p", "no:randomly",
            "tests/unit",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=_PROJECT_ROOT,
    )
    # Keep only node-ID lines (contain "::" and are not indented warnings/messages)
    return sorted(
        line
        for line in result.stdout.splitlines()
        if "::" in line and line.startswith("tests/")
    )


def test_unit_collection_is_stable_across_runs():
    """Node IDs must be identical between two independent subprocess collections.

    Fails when an ids= callable embeds an object memory address, because
    addresses differ between processes and xdist therefore aborts collection.
    """
    first = _collect_node_ids()
    second = _collect_node_ids()

    assert first, "no tests were collected in the first run — check PYTHONPATH / DATABASE_URL"
    assert first == second, (
        "Collection is NOT stable across independent runs. "
        "An ids= callable probably embeds an object address (e.g. ids=lambda v: str(v) "
        "applied to a function value).\n"
        f"Only in first run:   {sorted(set(first) - set(second))[:5]!r}\n"
        f"Only in second run:  {sorted(set(second) - set(first))[:5]!r}"
    )
