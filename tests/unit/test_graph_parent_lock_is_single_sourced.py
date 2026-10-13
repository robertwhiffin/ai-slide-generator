"""#269 Concern-1 ruling (b): one L0 parent-lock statement in ``src``.

PostgreSQL takes the L0 row locks in the order of the ``FOR UPDATE/SHARE OF``
list, so the release-before-draft order (the basis of the #269 deadlock
argument) lives in exactly one place: ``_lock_current_parents``.  Any other
function that locks a statement naming both ``GraphRelease`` and ``GraphDraft``
could lock them in another order.  Release-only locks (session creation,
``conversation_pins._active_release_for_update``) are allowed.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
_ALLOWED = {("services/graph_configuration_workbench.py", "_lock_current_parents")}
_RAW_LOCK = re.compile(r"\bFOR\s+(UPDATE|SHARE|NO\s+KEY\s+UPDATE|KEY\s+SHARE)\b", re.I)


def _functions(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _names(node: ast.AST) -> set[str]:
    found: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            found.add(child.id)
        elif isinstance(child, ast.Attribute):
            found.add(child.attr)
    return found


def _both_parent_lockers(root: Path) -> set[tuple[str, str]]:
    hits: set[tuple[str, str]] = set()
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for function in _functions(tree):
            names = _names(function)
            orm_lock = "with_for_update" in names and {
                "GraphRelease",
                "GraphDraft",
            } <= names
            raw_lock = any(
                isinstance(c, ast.Constant)
                and isinstance(c.value, str)
                and _RAW_LOCK.search(c.value)
                and re.search(r"\bgraph_release\b", c.value, re.I)
                and re.search(r"\bgraph_draft\b", c.value, re.I)
                for c in ast.walk(function)
            )
            if orm_lock or raw_lock:
                hits.add((relative, function.name))
    return hits


def test_only_lock_current_parents_locks_both_graph_parents():
    assert _both_parent_lockers(SRC) == _ALLOWED


def test_the_scanner_finds_an_orm_and_a_raw_second_parent_locker(tmp_path):
    """Non-vacuity: a second locker, in either spelling, is reported."""
    (tmp_path / "rogue.py").write_text(
        "def orm_rogue(session):\n"
        "    return select(GraphDraft, GraphRelease).with_for_update(\n"
        "        of=(GraphDraft, GraphRelease))\n"
        "\n"
        "def raw_rogue(session):\n"
        "    return text('SELECT 1 FROM graph_draft, graph_release FOR SHARE')\n"
        "\n"
        "def release_only(session):\n"
        "    return select(GraphRelease).with_for_update()\n",
        encoding="utf-8",
    )
    assert _both_parent_lockers(tmp_path) == {
        ("rogue.py", "orm_rogue"),
        ("rogue.py", "raw_rogue"),
    }
