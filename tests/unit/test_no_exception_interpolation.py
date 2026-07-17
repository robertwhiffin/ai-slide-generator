"""MEDIUM-2 gate (SDR-4437 PR-4): no exception interpolation in client responses.

Walks every file under src/api/routes/ with the AST and flags:

1. any ``detail=`` argument (keyword, or HTTPException's 2nd positional)
   inside an ``except ... as <name>:`` block that references ``<name>`` —
   this catches the whole family (``str(e)``, ``{e}``, ``{exc}``,
   ``{str(e)}``, multi-line f-strings) regardless of variable name; and
2. any ``HTMLResponse(...)`` call inside such a block that references the
   exception variable (the OAuth-callback ``{exc}`` reflection class).

NOTE while PR-4 is in flight: this test is committed RED at the end of the
serial gate and turns green as the per-file MEDIUM-2 tasks land.
"""

import ast
from pathlib import Path

ROUTES_DIR = Path(__file__).resolve().parents[2] / "src" / "api" / "routes"


def _call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    return getattr(func, "attr", "")


def _references(node: ast.AST, name: str) -> bool:
    return any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(node))


def _scan():
    detail_sites = []
    html_sites = []
    for path in sorted(ROUTES_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for handler in ast.walk(tree):
            if not isinstance(handler, ast.ExceptHandler) or not handler.name:
                continue
            for call in (n for n in ast.walk(handler) if isinstance(n, ast.Call)):
                values = [kw.value for kw in call.keywords if kw.arg == "detail"]
                if _call_name(call) == "HTTPException" and len(call.args) > 1:
                    values.append(call.args[1])
                for value in values:
                    if _references(value, handler.name):
                        detail_sites.append(
                            f"{path.relative_to(ROUTES_DIR)}:{value.lineno}"
                        )
                if _call_name(call) == "HTMLResponse" and _references(
                    call, handler.name
                ):
                    html_sites.append(
                        f"{path.relative_to(ROUTES_DIR)}:{call.lineno}"
                    )
    return detail_sites, html_sites


def test_no_exception_interpolation_in_detail():
    detail_sites, _ = _scan()
    assert detail_sites == [], (
        "Exception objects interpolated into client-facing detail= strings "
        "(SDR-4437 MEDIUM-2 — apply the PR-4 replacement recipe; log the "
        "exception server-side and return a generic message):\n  "
        + "\n  ".join(detail_sites)
    )


def test_no_exception_reflection_into_html_responses():
    _, html_sites = _scan()
    assert html_sites == [], (
        "Exception objects reflected into HTMLResponse bodies "
        "(SDR-4437 MEDIUM-2):\n  " + "\n  ".join(html_sites)
    )
