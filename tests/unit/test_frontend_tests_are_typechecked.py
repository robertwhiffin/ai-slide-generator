"""Guard: frontend/tests/**/*.ts must be covered by a tsconfig that the CI step builds.

The CI step runs ``tsc -b`` from ``frontend/``, which follows the project references in
``frontend/tsconfig.json``.  The typecheck for the test tree lives in
``frontend/tsconfig.e2e.json`` and must be reachable from that root config.

The three assertions below pin three properties that, together, mean ``frontend/tests``
is actually typechecked:

1. ``tsconfig.json`` references ``tsconfig.e2e.json`` — so ``tsc -b`` picks it up.
2. ``tsconfig.e2e.json`` includes ``tests/**/*.ts`` — so every spec is in scope.
3. ``tsconfig.e2e.json`` does NOT contain ``verbatimModuleSyntax`` — the C3 correction
   prohibits it; with it enabled, 34 TS1484 errors appear across 29 spec files.

Reviewer sabotage: delete ``{"path": "./tsconfig.e2e.json"}`` from ``tsconfig.json``
references.  Predicted RED: assertion 1 fails (guard fires) while
``tsc --noEmit -p tsconfig.e2e.json`` stays silently green (direct invocation still
works).  That is exactly why this guard exists.
"""
import json
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_TSCONFIG_ROOT = _REPO / "frontend" / "tsconfig.json"
_TSCONFIG_E2E = _REPO / "frontend" / "tsconfig.e2e.json"


def test_tsconfig_json_references_tsconfig_e2e():
    """tsconfig.json must list tsconfig.e2e.json in its references array.

    Without this reference, ``tsc -b`` (the CI step) never typechecks
    ``frontend/tests/**/*.ts``.
    """
    root = json.loads(_TSCONFIG_ROOT.read_text())
    refs = root.get("references", [])
    assert {"path": "./tsconfig.e2e.json"} in refs, (
        f"Expected {{\"path\": \"./tsconfig.e2e.json\"}} in tsconfig.json references, "
        f"got: {refs!r}"
    )


def test_tsconfig_e2e_includes_test_files():
    """tsconfig.e2e.json must include tests/**/*.ts.

    Without this, the e2e config exists but covers nothing.
    """
    e2e = json.loads(_TSCONFIG_E2E.read_text())
    include = e2e.get("include", [])
    assert "tests/**/*.ts" in include, (
        f"Expected \"tests/**/*.ts\" in tsconfig.e2e.json include, got: {include!r}"
    )


def test_tsconfig_e2e_has_no_verbatim_module_syntax():
    """tsconfig.e2e.json must not enable verbatimModuleSyntax.

    With verbatimModuleSyntax: true, 34 TS1484 errors appear across 29 spec
    files (C3 correction).  The e2e config only needs to typecheck, not enforce
    strict ESM import style.
    """
    e2e_text = _TSCONFIG_E2E.read_text()
    e2e = json.loads(e2e_text)
    compiler_opts = e2e.get("compilerOptions", {})
    assert "verbatimModuleSyntax" not in compiler_opts, (
        "tsconfig.e2e.json must not set verbatimModuleSyntax — it causes 34 TS1484 "
        "errors across 29 spec files (PLAN-CORRECTIONS.md C3)"
    )
