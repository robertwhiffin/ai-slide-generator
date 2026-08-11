"""
Dry-run dependency resolution against the Databricks pip proxy.

Phase A verification: Resolves the explicit LangGraph/LangChain version set
that PR2 introduces, proving the candidate stack can be resolved on the proxy
that Databricks Apps BUILD uses. This test proves the explicit specs are
resolvable BEFORE pyproject.toml is edited (Phase B, after Task 2 writes the
pins, runs the same confirm via `-e .`).

Evidence: The controller's Phase A dry-run (phaseA-proxy-dryrun.log) already
confirmed exit-0 on 2026-08-09 with these exact specs. This test re-verifies
the same claim and will fail loudly if the proxy's availability shifts.

Both tests are marked @live (excluded in CI with -m 'not live'). If the
proxy is unreachable the tests skip rather than fail.
"""
import re
import subprocess
import sys

import pytest


PROXY_URL = "https://pypi-proxy.dev.databricks.com/simple/"

# Explicit version specs — the 11 candidates from the PR2 spec (brief §Phase A),
# plus one extra constraint added after controller's run: databricks-sdk<0.126.
#
# Why the extra constraint: the controller's run (2026-08-09) resolved
# databricks-sdk-0.125.0 successfully. On 2026-08-11, version 0.126.0 appeared on
# the proxy index but its metadata endpoint returns HTTP 403. Without the constraint
# the resolver picks 0.126.0 (newest satisfying databricks-langchain>=0.65.0) and
# fails. Constraining to <0.126 matches exactly what was confirmed to work.
# This should be surfaced to Task 2 as a known-good upper bound for pinning.
#
# Do NOT replace with `-e .`: resolving the current pyproject.toml proves nothing
# because langgraph is not pinned there at all.
PHASE_A_SPECS = [
    "langgraph==1.2.10",
    "langchain==1.3.14",
    "langchain-core==1.5.3",
    "langgraph-checkpoint==4.1.1",
    "langgraph-prebuilt==1.1.0",
    "langgraph-sdk==0.4.2",
    "mlflow==3.14.0",
    "databricks-langchain==0.9.0",
    "psycopg2-binary==2.9.10",
    "fastapi<0.137",
    "starlette<1.3",
    # Extra: pin to below the 403-ing 0.126.0 (confirmed 0.125.0 works)
    "databricks-sdk<0.126",
]

# Critical packages that must be present on the proxy at their pinned versions.
CRITICAL_PACKAGES = [
    ("langgraph", "1.2.10"),
    ("langchain", "1.3.14"),
    ("langchain-core", "1.5.3"),
    ("langgraph-checkpoint", "4.1.1"),
    ("mlflow", "3.14.0"),
    ("databricks-langchain", "0.9.0"),
    ("psycopg2-binary", "2.9.10"),
]


def _proxy_reachable() -> bool:
    """Quick connectivity probe: ask the proxy for pip's version list."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "index", "versions", "pip",
             "--index-url", PROXY_URL],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _skip_if_offline():
    """Skip (not fail) when the proxy is unreachable — e.g. hermetic CI."""
    if not _proxy_reachable():
        pytest.skip(
            "Databricks pip proxy not reachable; skipping proxy-dependent tests. "
            "Run on a machine with access to https://pypi-proxy.dev.databricks.com/ "
            "to verify the resolution."
        )


@pytest.mark.live
def test_critical_packages_available_on_proxy():
    """Assert that each critical package/version exists on the Databricks proxy.

    Queries `pip index versions <pkg>` for each critical package and checks that
    the required version string appears in the output. Fails loudly (does NOT
    silently pass) if any package is missing — this catches proxy availability
    shifts before they break a production deploy.
    """
    _skip_if_offline()

    failures = []
    for pkg, version in CRITICAL_PACKAGES:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "index", "versions", pkg,
             "--index-url", PROXY_URL],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Treat as available only when pip exited 0 AND the version string
        # appears in stdout (the "Available versions:" line) without an ERROR.
        # Use a boundary pattern so "1.3" doesn't spuriously match "1.3.14".
        version_present = bool(
            re.search(r"(?<![.\d])" + re.escape(version) + r"(?![.\d])", result.stdout)
        )
        available = (
            result.returncode == 0
            and version_present
            and "ERROR" not in result.stderr.upper()
        )
        if not available:
            failures.append(
                f"{pkg}=={version}: rc={result.returncode} "
                f"stdout={result.stdout[:200]!r} stderr={result.stderr[:200]!r}"
            )

    assert not failures, (
        "The following packages were not available at the required version on the proxy:\n"
        + "\n".join(f"  - {f}" for f in failures)
    )


@pytest.mark.live
@pytest.mark.slow
def test_dependencies_resolve_on_proxy():
    """Phase A: dry-run the 11 explicit PR2 specs against the Databricks proxy.

    Uses --ignore-installed so pip actually exercises the proxy resolver rather
    than short-circuiting on locally-satisfied packages. The real resolve took
    ~8 minutes; timeout is set to 600 s to accommodate that.

    Evidence for initial pass: controller's phaseA-proxy-dryrun.log (2026-08-09)
    confirmed exit-0 with these exact specs. This test re-verifies the same
    claim on demand and will fail loudly if the stack later conflicts.
    """
    _skip_if_offline()

    result = subprocess.run(
        [
            sys.executable, "-m", "pip", "install",
            "--dry-run",
            "--ignore-installed",
            "--index-url", PROXY_URL,
        ] + PHASE_A_SPECS,
        capture_output=True,
        text=True,
        timeout=600,  # real resolve took ~8 min; generous ceiling
    )

    if result.returncode != 0:
        # Print tails so the failure is debuggable without drowning the terminal
        print("\n=== STDOUT (last 5000 chars) ===")
        print(result.stdout[-5000:])
        print("\n=== STDERR (last 2000 chars) ===")
        print(result.stderr[-2000:])

    assert result.returncode == 0, (
        f"pip dry-run resolution failed (exit {result.returncode}).\n"
        f"stderr tail:\n{result.stderr[-2000:]}"
    )

    # Log the "Would install ..." summary line for traceability
    print("\n=== Phase A resolution succeeded — resolved set: ===")
    for line in result.stdout.split("\n"):
        if "Would install" in line:
            print(line)
            break
