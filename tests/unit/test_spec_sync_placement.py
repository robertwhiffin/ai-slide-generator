"""The placement rule IS the design: only route handlers may call mark_dirty.

`mark_dirty` records "a human changed this deck".  It is safe to draw that
conclusion from "arrived via the route" ONLY while the route handlers in
`src/api/routes/slides.py` are the sole call sites: the LangGraph build calls the
service methods those handlers wrap and never issues an HTTP request.  A single
call added from a graph node, `deck_level_writer.py`, `slide_repository.py` or
`session_manager.py` would make the graph mark its own writes dirty and schedule
an LLM re-description of the agent's own output — so the structural guarantee is
load-bearing, not ceremony, and this file is what keeps it true.

Why tokenize and not a text grep
--------------------------------
`session_manager.py:1138` already contains the string `mark_dirty` in a COMMENT
("mark_dirty trigger list: a duplicate never starts with a stale spec"), and this
module's own docstrings discuss it at length.  A `grep -l mark_dirty src/` would
flag those and the honest fix would be an allowlist that also hides a real call in
the same file.  Tokenizing and keeping only NAME tokens finds imports and calls
while ignoring every mention in a comment or string, so the allowlist stays at
exactly the two files that are permitted to contain the identifier at all.

The DoD's absence assertions live here, each PAIRED with an entry assertion in the
same test, because "file X does not call mark_dirty" is also true when the parse
never ran or the token name was misspelled: every test that asserts an absence
also asserts the same machinery finds the calls that DO exist.
"""
from __future__ import annotations

import ast
import io
import tokenize
from pathlib import Path
from typing import Dict, List, Set

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"

# The definition module, and the ONLY module permitted to reference the name.
_DEFINING_MODULE = "src/services/spec_sync.py"
_ONLY_CALLER = "src/api/routes/slides.py"

_TRIGGER = "mark_dirty"


def _name_tokens(path: Path) -> List[str]:
    """Return every NAME token in *path*, with comments and strings discarded.

    Uses `tokenize` over the real bytes, so an identifier reached by attribute
    access (`spec_sync.mark_dirty(...)`) is still found: `mark_dirty` is a NAME
    token there too.
    """
    source = path.read_bytes()
    names: List[str] = []
    readline = io.BytesIO(source).readline
    for tok in tokenize.tokenize(readline):
        if tok.type == tokenize.NAME:
            names.append(tok.string)
    return names


def _src_files() -> List[Path]:
    """Every .py file under src/, excluding caches.

    Scoped to src/ deliberately: tests reference `mark_dirty` legitimately, and
    `.claude/worktrees/` holds stale copies of this repo that would give false
    hits — it is outside src/ and therefore never walked.
    """
    return [
        p
        for p in sorted(_SRC.rglob("*.py"))
        if "__pycache__" not in p.parts
    ]


def _files_referencing_trigger() -> Set[str]:
    """Repo-relative paths of every file under src/ whose CODE names mark_dirty."""
    hits: Set[str] = set()
    for path in _src_files():
        if _TRIGGER in _name_tokens(path):
            hits.add(path.relative_to(_REPO_ROOT).as_posix())
    return hits


class TestOnlyTheRouteModuleReferencesTheTrigger:
    """C-6 / DoD: grep the TREE and allow exactly one caller."""

    def test_the_walk_actually_reaches_the_tree(self):
        """Guard the guard: a broken walk would make every absence test vacuous."""
        files = _src_files()
        assert len(files) > 100, (
            f"expected the whole src/ tree, walked only {len(files)} files"
        )
        rel = {p.relative_to(_REPO_ROOT).as_posix() for p in files}
        # Three files this suite reasons about must all be in the walk.
        for expected in (
            _DEFINING_MODULE,
            _ONLY_CALLER,
            "src/api/routes/tour.py",
            "src/api/services/session_manager.py",
        ):
            assert expected in rel, f"{expected} missing from the walked tree"

    def test_exactly_two_files_under_src_reference_mark_dirty(self):
        """The definition module and the route module. Nothing else. Ever.

        A third entry here means some other layer can now mark a deck dirty, and
        the "arrived via the route means a human did it" inference is dead.
        """
        assert _files_referencing_trigger() == {_DEFINING_MODULE, _ONLY_CALLER}

    def test_the_defining_module_is_the_one_that_defines_it(self):
        """Pins WHICH of the two files is the definition, not just the count."""
        tree = ast.parse((_REPO_ROOT / _DEFINING_MODULE).read_text())
        defined = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert _TRIGGER in defined
        assert "clear_marker" in defined
        assert "DEBOUNCE_SECONDS" in {
            t.id
            for node in tree.body
            if isinstance(node, ast.Assign)
            for t in node.targets
            if isinstance(t, ast.Name)
        }

    def test_the_service_layer_the_graph_calls_never_references_it(self):
        """The named modules the graph writes through, checked individually.

        Subsumed by the set equality above, but pinned by name so a failure says
        WHICH layer broke the design rather than only that a set differs.
        """
        graph_write_path = [
            "src/api/services/chat_service.py",
            "src/api/services/deck_level_writer.py",
            "src/api/services/slide_repository.py",
            "src/api/services/session_manager.py",
            "src/services/graph/nodes.py",
            "src/api/routes/sessions.py",
            "src/api/routes/chat.py",
            "src/api/routes/tour.py",
        ]
        for rel in graph_write_path:
            path = _REPO_ROOT / rel
            assert path.exists(), f"anchor drifted: {rel} no longer exists"
            assert _TRIGGER not in _name_tokens(path), (
                f"{rel} references {_TRIGGER}; only {_ONLY_CALLER} may"
            )
        # PAIRED entry assertion: the same tokenizer finds the calls that exist,
        # so the absences above are real absences and not a broken matcher.
        assert _TRIGGER in _name_tokens(_REPO_ROOT / _ONLY_CALLER)
        assert _TRIGGER in _name_tokens(_REPO_ROOT / _DEFINING_MODULE)

    def test_the_comment_in_session_manager_is_still_only_a_comment(self):
        """session_manager.py mentions mark_dirty in prose; that must stay prose.

        This is why the guard tokenizes.  If the tokenizer were replaced by a text
        grep, this file would have to allowlist session_manager.py — and the
        allowlist would then hide a REAL call added to it later.
        """
        path = _REPO_ROOT / "src/api/services/session_manager.py"
        raw = path.read_text()
        assert _TRIGGER in raw, (
            "anchor drifted: session_manager.py no longer mentions mark_dirty at "
            "all, so this test no longer proves the tokenizer ignores comments"
        )
        assert _TRIGGER not in _name_tokens(path)


# ---------------------------------------------------------------------------
# Which routes trigger, and which are ruled out IN CODE (C-5)
# ---------------------------------------------------------------------------

# Every route on the slides router, with whether its handler must call the
# trigger.  This table is the machine-checkable form of the plan's route table:
# a later PR that wires a trigger into one of the False rows without thinking
# reddens this test instead of silently changing debounce behaviour.
#
# POST /slides (insert) is deliberately ABSENT: it does not exist yet.  The task
# that adds it adds its own trigger and its own row here.
_EXPECTED_TRIGGERS: Dict[str, bool] = {
    # (verb, path): triggers?
    "GET ": False,
    "PUT /reorder": True,             # narrative arc changes with NO html change
    "PATCH /{index}": True,           # the human HTML edit
    "POST /{index}/duplicate": True,  # slide added
    "DELETE /{index}": True,          # slide removed
    # Out of scope for this PR, ruled out here rather than only in prose:
    "PATCH /{index}/verification": False,   # completes a task a prior change began
    "POST /versions/create": False,         # a version save leaves the live deck alone
    "PATCH /versions/{version_number}/verification": False,
    "POST /versions/sync-verification": False,
    "POST /versions/{version_number}/restore": False,  # D6 CANCELS the review instead
    "GET /versions": False,
    "GET /versions/current": False,
    "GET /versions/{version_number}": False,
}


def _route_table() -> Dict[str, bool]:
    """Map "VERB path" -> whether that handler's body names mark_dirty.

    Parsed from the AST of slides.py: for every function carrying an
    `@router.<verb>(<path>)` decorator, walk the function body for a NAME node
    equal to `mark_dirty`.  Walking the body (not the file) is what makes this a
    per-route assertion rather than a per-file one.
    """
    tree = ast.parse((_REPO_ROOT / _ONLY_CALLER).read_text())
    table: Dict[str, bool] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            func = dec.func
            if not (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "router"
            ):
                continue
            verb = func.attr.upper()
            path = ""
            if dec.args and isinstance(dec.args[0], ast.Constant):
                path = dec.args[0].value
            key = f"{verb} {path}"
            names = {
                n.id for n in ast.walk(node) if isinstance(n, ast.Name)
            }
            table[key] = _TRIGGER in names
    return table


class TestEveryMutatingRouteIsPinned:
    def test_the_route_table_is_exactly_the_routes_that_exist(self):
        """No route appears or disappears without this file being updated.

        Also the entry assertion for the whole class: if the AST walk found no
        routes, every "does not trigger" assertion below would be vacuously true.
        """
        found = _route_table()
        assert found, "AST walk found no @router-decorated handlers at all"
        assert set(found) == set(_EXPECTED_TRIGGERS), (
            "slides.py's route set changed.\n"
            f"  only in code: {sorted(set(found) - set(_EXPECTED_TRIGGERS))}\n"
            f"  only in table: {sorted(set(_EXPECTED_TRIGGERS) - set(found))}"
        )

    def test_each_route_triggers_exactly_as_the_table_says(self):
        assert _route_table() == _EXPECTED_TRIGGERS

    def test_four_routes_trigger_and_nine_do_not(self):
        """The counts, stated separately so a wholesale table edit is visible.

        Four, not the plan's five: `POST /slides` is Task 6's and does not exist
        yet (brief C-4).
        """
        found = _route_table()
        triggering = sorted(k for k, v in found.items() if v)
        assert triggering == [
            "DELETE /{index}",
            "PATCH /{index}",
            "POST /{index}/duplicate",
            "PUT /reorder",
        ]
        assert len([k for k, v in found.items() if not v]) == 9

    def test_no_insert_route_exists_yet(self):
        """C-4: POST /slides is a later task's. Do not pre-wire it."""
        assert "POST " not in _route_table(), (
            "POST /slides now exists — that task must add its own mark_dirty call "
            "and its own row in _EXPECTED_TRIGGERS"
        )


class TestTheAuthorIsPassedFromTheRequestContext:
    """The author must be read in the handler, not inside the worker thread.

    `get_current_user()` is a ContextVar.  `mark_dirty` runs via
    `asyncio.to_thread`, and this repo carries `run_in_thread_with_context`
    precisely because ContextVars do not reliably reach a worker thread.  Reading
    the user in the handler and passing the value keeps attribution correct
    regardless of which thread wrapper is used.
    """

    def test_every_trigger_call_passes_get_current_user_as_an_argument(self):
        tree = ast.parse((_REPO_ROOT / _ONLY_CALLER).read_text())
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and any(
                isinstance(a, ast.Name) and a.id == _TRIGGER for a in node.args
            )
        ]
        assert len(calls) == 4, (
            f"expected 4 to_thread(mark_dirty, ...) calls, found {len(calls)}"
        )
        for call in calls:
            arg_src = {
                ast.unparse(a) for a in call.args
            }
            assert "get_current_user()" in arg_src, (
                "a trigger call does not pass get_current_user() explicitly: "
                f"{ast.unparse(call)}"
            )
