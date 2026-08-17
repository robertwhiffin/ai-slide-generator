"""WF-02: the DEPLOYED wheel must declare what ``src/`` imports.

THE DEFECT CLASS, which is what this file exists to close: the repo root's
``pyproject.toml`` is what a developer installs, and
``packages/databricks-tellr-app/pyproject.toml`` is what Databricks Apps actually
deploys. They are separate manifests. An import can therefore be satisfied in every
dev environment and every test run while being ABSENT from the deployed
environment — and nothing fails at import time, because the call sites that need
these packages import them lazily inside a function.

MEASURED (WF-02, HIGH, pre-existing, live at dev14). ``svgpathtools`` is imported by
both Python emitters (``html_to_pptx.py``, ``html_to_google_slides.py``) and declared
in the ROOT manifest, but the app wheel had NEVER declared it. The consequence chain
was observed end to end: image extraction is a silent no-op ("HTML length after image
extraction: 379898", unchanged) -> base64 survives into the prompt -> after the
truncation guard the prompt body is 98% base64 with 0 real words on 3 of 4 slides ->
slide 1 exports background-only, slides 3-4 carry INVENTED content, and the Drive deck
reports "no chart images were available". With the package present, extraction removes
7,575 B and the prompt body goes from 0 to 25 real words.

WHY A STATIC TEST IS THE RIGHT SHAPE. The bug is a discrepancy between two files, so
it is fully decidable from those two files, with no deployment required. A runtime
test cannot see it at all: in the test environment the import always succeeds.
"""
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_ROOT_MANIFEST = _REPO / "pyproject.toml"
_APP_MANIFEST = _REPO / "packages" / "databricks-tellr-app" / "pyproject.toml"

#: Root runtime dependencies deliberately NOT declared in the app wheel, each with
#: the reason it is safe. Anything else missing is a WF-02-shaped defect.
_ALLOWED_ABSENT_FROM_WHEEL = {
    # Declared in root only as an UPPER BOUND on a transitive: fastapi pulls
    # starlette, and root pins `starlette<1.3` because 1.3 regressed
    # APIRouter flattening. The wheel reaches the same end by exact-pinning
    # `fastapi==0.121.2`, whose closure resolves starlette==0.49.3 — inside the
    # bound. So the constraint is honoured without a direct declaration.
    "starlette",
    # KNOWN-OPEN, and the SAME DEFECT as WF-02 rather than an exception to it:
    # `databricks_mcp` is imported at src/services/tools/mcp_tool.py:56,129 and is
    # absent from the wheel's dependencies AND from its resolved closure, so that
    # MCP tool path cannot work on any deployment. It is listed here (not fixed)
    # because it fails LOUDLY — the import is wrapped and re-raised as
    # MCPToolError("databricks-mcp package not installed") — where WF-02 failed
    # silently, and because adding a dependency to this wheel has to clear the
    # Apps build-phase resolution budget on its own evidence.
    "databricks-mcp",
}


#: The ``[project]`` ``dependencies`` array, up to its closing bracket. Anchored to
#: the line start so it cannot match ``dev = [`` under
#: ``[project.optional-dependencies]`` — dev extras are not deployed and must not
#: be compared.
_DEPENDENCIES_ARRAY_RE = re.compile(r"^dependencies = \[(.*?)^\]", re.DOTALL | re.MULTILINE)

#: One requirement string inside that array. Matched PER LINE and only on lines that
#: are not comments, because the app manifest's own comments contain double-quoted
#: prose (e.g. the "App process did not start within 10 minutes" deploy error) and a
#: whole-array scan reads that as a dependency — inflating the set and, worse, able to
#: mask a real gap under a name that only ever appeared inside a comment.
_REQUIREMENT_RE = re.compile(r'"([^"]+)"')


def _declared(manifest: Path) -> dict[str, str]:
    """Runtime dependencies of *manifest*, keyed by normalized distribution name.

    Parsed with a regex rather than ``tomllib`` deliberately: ``tomllib`` is stdlib
    only from 3.11, while both manifests declare ``requires-python = ">=3.10"``, so
    importing it here would make this test the one thing in the suite that cannot
    run on the oldest interpreter the project claims to support.
    """
    array = _DEPENDENCIES_ARRAY_RE.search(manifest.read_text(encoding="utf-8"))
    assert array, f"no [project] dependencies array in {manifest}"
    out: dict[str, str] = {}
    for line in array.group(1).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # One requirement per line in both manifests; take the FIRST quoted string so
        # a trailing inline comment cannot contribute a second "requirement".
        match = _REQUIREMENT_RE.search(stripped)
        if not match:
            continue
        spec = match.group(1)
        # Strip the version specifier, extras and environment marker to get the name.
        name = re.split(r"[<>=!~\[;]", spec.strip(), maxsplit=1)[0].strip()
        out[name.lower().replace("_", "-")] = spec
    return out


@pytest.fixture(scope="module")
def app_deps() -> dict[str, str]:
    return _declared(_APP_MANIFEST)


@pytest.fixture(scope="module")
def root_deps() -> dict[str, str]:
    return _declared(_ROOT_MANIFEST)


def test_the_app_wheel_declares_svgpathtools(app_deps):
    """WF-02 itself. Both Python emitters import it; without it in THIS manifest,
    image extraction is a no-op on every deployment."""
    assert "svgpathtools" in app_deps, (
        "svgpathtools is imported by the PPTX and Google-Slides emitters and "
        "declared in the root manifest, but the deployed app wheel does not "
        "declare it — image extraction silently no-ops in production"
    )


def test_the_emitters_that_need_svgpathtools_still_import_it():
    """Non-vacuity for the test above: it only protects anything while these two
    modules actually depend on the package. If both stop importing it, the
    declaration is dead weight and this pin should be revisited, not kept."""
    importers = {
        path.name
        for path in (_REPO / "src").rglob("*.py")
        if "svgpathtools" in path.read_text(encoding="utf-8")
    }
    assert importers == {"html_to_pptx.py", "html_to_google_slides.py"}, importers


def test_no_root_runtime_dependency_is_silently_absent_from_the_app_wheel(
    root_deps, app_deps
):
    """THE DEFECT CLASS, closed. Every runtime dependency the root manifest
    declares must also be declared in the wheel we deploy, unless it is listed in
    ``_ALLOWED_ABSENT_FROM_WHEEL`` with a stated reason.

    This is the check that would have caught WF-02 before it ever deployed, and it
    fails loudly on the NEXT such divergence instead of turning into a
    plausible-looking wrong deck."""
    missing = set(root_deps) - set(app_deps) - _ALLOWED_ABSENT_FROM_WHEEL
    assert not missing, (
        "these runtime dependencies are declared in the root manifest but NOT in "
        f"the deployed app wheel: {sorted(missing)}. Either declare them in "
        "packages/databricks-tellr-app/pyproject.toml or add them to "
        "_ALLOWED_ABSENT_FROM_WHEEL with the reason they are safe to omit."
    )


def test_the_allowlist_does_not_outlive_its_entries(root_deps):
    """Keep the allowlist honest: an entry that is no longer a root dependency at
    all is stale, and a stale entry could mask a future real gap under the same
    name."""
    stale = _ALLOWED_ABSENT_FROM_WHEEL - set(root_deps)
    assert not stale, f"_ALLOWED_ABSENT_FROM_WHEEL names non-dependencies: {sorted(stale)}"
