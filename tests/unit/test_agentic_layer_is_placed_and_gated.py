"""Guards on layer 3 — the placement, the three gates, and the wording temptation.

WHY THESE GUARDS LIVE HERE AND NOT IN ``tests/agentic/``
------------------------------------------------------
Every module under ``tests/agentic/`` is unconditionally skipped, on purpose (see
``tests/agentic/gates.py``).  A guard parked in there would be skipped with them and
would check nothing.  These are the parts of layer 3 that must actually RUN, so they
live under ``tests/unit/`` — the job that collects the directory wholesale on every
backend PR.

The four things guarded, and the defect each one prevents
--------------------------------------------------------
1. **Placement.** ``tests/agentic/`` is a sibling of ``tests/unit/``, never a
   subdirectory.  ``unit-tests`` runs ``pytest tests/unit`` with **no ``-m`` filter
   and no Databricks credentials**, so under ``tests/unit/`` the ``live`` marker
   gates nothing at all: the suite would be collected on day one and saved only by
   the accident that a runner cannot reach the endpoint.
   ``tests/unit/test_dependencies_resolve.py`` documents that accident against
   itself.

2. **The three mechanisms.** Marker for selection, endpoint ``skipif`` for safety,
   unconditional ``skip`` for honesty.  Each module must carry all three; any one
   of them alone leaves a hole with a different shape.

3. **Wording.** Layer 3 is where "assert the model said the right sentence" is most
   tempting, and a phrasing assertion is both brittle and beside the point.  The
   guard reads the layer's own source and fails on a wording comparison.

4. **The placeholder era ending quietly.** The unconditional skip is honest only
   while the prompts really are placeholders.  The skill versions that shipped with
   them are pinned below, so re-authoring the prompts turns this red and puts the
   "should layer 3 be switched on now?" decision in front of whoever did it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = REPO_ROOT / "tests"
AGENTIC_DIR = TESTS_DIR / "agentic"
UNIT_DIR = TESTS_DIR / "unit"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "test.yml"
NODES = REPO_ROOT / "src" / "services" / "graph" / "nodes.py"

#: The CI job that runs this layer.  Its ``if:`` is deliberately NOT asserted
#: anywhere, and it is deliberately NOT in ``_GATE_EXEMPT``: switching the layer on
#: is (1) deleting ``if: false`` plus adding two secrets, and (2) deleting one line
#: from ``tests/agentic/gates.py``.  A guard that pinned ``if: false``, or an
#: exemption that had to be removed on the way in, would add a third edit to a test
#: file for no gain — the job is wired into the gate already, and a disabled job
#: reports ``skipped``, which the failure loop does not act on.
LAYER3_JOB = "agentic-tests"

#: The one command for this layer, and the directory it runs.  §G1 asks for "a
#: dedicated directory plus a ``make test-agentic`` (or equivalent script) …
#: discoverable and one command, rather than a marker nobody remembers".  There is
#: no Makefile in this repo — its convention is ``scripts/*.sh`` — so the script is
#: the deliverable, and it is what the CI job runs.
LAYER3_SCRIPT = REPO_ROOT / "scripts" / "run_agentic_tests.sh"
_LAYER3_RUN_TOKENS = ("tests/agentic", LAYER3_SCRIPT.name)

#: The three mechanisms, by the pytest mark name each one is spelled with.
_REQUIRED_MECHANISMS = frozenset({"live", "skipif", "skip"})

#: Non-test modules allowed under ``tests/agentic/``, each with a reason.  An empty
#: reason is not allowed — that is how an exemption becomes indistinguishable from a
#: file somebody forgot, which is the lesson ``DELIBERATE_EXCLUSIONS`` and
#: ``_GATE_EXEMPT`` already carry in this repo.
_SUPPORT_MODULES: dict[str, str] = {
    "__init__.py": "package marker; tests/ and tests/unit/ both have one",
    "gates.py": (
        "defines the three mechanisms once so seven modules cannot drift apart, "
        "and is the single place the placeholder skip is retired"
    ),
    "payloads.py": (
        "payload builders that mirror what the graph nodes actually send, so a "
        "layer-3 test cannot measure a prompt shape production never produces"
    ),
}

#: Skill versions as they shipped WITH the placeholder prompts.  Hard-coded, not
#: read from the registry twice: a check whose two sides move together passes
#: whatever happens (the self-comparison shape).  ``Skill.version`` is documented as
#: "increment when instructions change", so a bump here means the prompts changed.
_PLACEHOLDER_ERA_VERSIONS: dict[str, int] = {
    "architect": 2,
    "data_analyst": 2,
    "builder": 2,
    "fixer": 2,
    "build_reviewer": 2,
    "fix_reviewer": 2,
    "deck_reviewer": 2,
}

#: Fields of the skill outputs that carry free prose a model authored.  A
#: comparison between one of these and a literal containing WORDS is a wording
#: assertion.  Punctuation-only literals are fine: ``"?" in out.message`` asks
#: whether it asked something, which is structure.
_PROSE_FIELDS = frozenset({"message", "synthesis", "change_summary", "gap", "reason"})

#: ``str`` predicates that compare wording without an ``==``.
_STRING_PREDICATES = frozenset(
    {"startswith", "endswith", "find", "index", "count", "match", "search", "fullmatch"}
)

#: Two or more consecutive letters, twice — i.e. real words rather than punctuation
#: or a single sigil.
_WORDS = re.compile(r"[A-Za-z]{2,}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _layer3_test_files() -> list[Path]:
    """Every ``test_*.py`` under ``tests/agentic/``, recursively.

    Recursive on purpose: ``pytest tests/agentic`` recurses, so a module in a
    subdirectory is collected and must carry the gates like any other.
    """
    return sorted(AGENTIC_DIR.rglob("test_*.py"))


def _layer3_python_files() -> list[Path]:
    return sorted(AGENTIC_DIR.rglob("*.py"))


def _dotted(node: ast.AST) -> str:
    """``pytest.mark.skipif`` for the attribute chain of that shape, else ``""``."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def _gates_names_imported(tree: ast.Module) -> set[str]:
    """Names this module imported from ``tests.agentic.gates``."""
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "tests.agentic.gates":
            imported.update(alias.asname or alias.name for alias in node.names)
    return imported


def _pytestmark_value(tree: ast.Module) -> ast.expr | None:
    """The module-level ``pytestmark`` assignment's value, or ``None``.

    Module level only.  A ``pytestmark`` set inside a class or a function does not
    gate the module, and an ``@pytest.mark.skip`` decorator on one test does not
    either — which is why this looks at the assignment and nothing else.
    """
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "pytestmark":
                    return node.value
        if isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "pytestmark":
                return node.value
    return None


def _mechanisms(tree: ast.Module) -> tuple[set[str], list[str]]:
    """``(mechanisms found, unrecognised names)`` for a module's ``pytestmark``.

    Accepts three spellings, so a sibling task has more than one way to comply:
    ``pytestmark = LAYER3_MARKS``, the three constants named individually, or
    ``pytest.mark.live`` / ``pytest.mark.skipif(...)`` / ``pytest.mark.skip(...)``
    written inline.  The meaning of each gates constant comes from
    ``gates.MECHANISMS_BY_NAME``, not from a copy kept here — a renamed constant
    must not leave this guard accepting a name that no longer exists.
    """
    from tests.agentic.gates import MECHANISMS_BY_NAME

    value = _pytestmark_value(tree)
    if value is None:
        return set(), []

    imported = _gates_names_imported(tree)
    found: set[str] = set()
    unknown: list[str] = []

    for node in ast.walk(value):
        if isinstance(node, ast.Attribute):
            dotted = _dotted(node)
            prefix, _, mark = dotted.rpartition(".")
            if prefix == "pytest.mark" and mark in _REQUIRED_MECHANISMS:
                found.add(mark)
        elif isinstance(node, ast.Name):
            if node.id in MECHANISMS_BY_NAME and node.id in imported:
                found.update(MECHANISMS_BY_NAME[node.id])
            elif node.id in MECHANISMS_BY_NAME:
                unknown.append(
                    f"{node.id} (not imported from tests.agentic.gates in this file)"
                )
    return found, unknown


def _string_constants(node: ast.AST) -> list[str]:
    """String literals in *node*, excluding the fixed parts of f-strings.

    An f-string in this position is a diagnostic being built, not a comparison.
    Including its literal parts would flag every assertion that prints the model's
    own reply back to the reader — which is the thing that makes a failure
    diagnosable.
    """
    out: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.JoinedStr):
            continue
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            # ast.walk descends into JoinedStr regardless of the guard above, so
            # exclude its parts explicitly.
            out.append(child.value)
    joined_parts = {
        part.value
        for js in ast.walk(node)
        if isinstance(js, ast.JoinedStr)
        for part in js.values
        if isinstance(part, ast.Constant) and isinstance(part.value, str)
    }
    return [s for s in out if s not in joined_parts]


def _references_prose(node: ast.AST) -> list[str]:
    """Prose-bearing fields referenced anywhere in *node*."""
    hits: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute) and child.attr in _PROSE_FIELDS:
            hits.append(child.attr)
        elif isinstance(child, ast.Subscript):
            key = child.slice
            if isinstance(key, ast.Constant) and key.value in _PROSE_FIELDS:
                hits.append(str(key.value))
    return hits


def _wording_comparisons(path: Path) -> list[str]:
    """Every place *path* compares authored prose against a literal with words in it."""
    tree = ast.parse(path.read_text())
    offences: list[str] = []

    def _record(node: ast.AST, literals: list[str], fields: list[str]) -> None:
        worded = [s for s in literals if len(_WORDS.findall(s)) >= 1]
        if worded and fields:
            offences.append(
                f"{path.relative_to(REPO_ROOT)}:{getattr(node, 'lineno', '?')} "
                f"compares {sorted(set(fields))} against {worded!r}"
            )

    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            _record(node, _string_constants(node), _references_prose(node))
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in _STRING_PREDICATES:
                _record(node, _string_constants(node), _references_prose(node))
    return offences


def _workflow() -> dict:
    with open(WORKFLOW) as fh:
        return yaml.safe_load(fh)


def _jobs_that_run_layer3() -> set[str]:
    """Jobs whose ``run:`` block reaches layer 3 — by either available route.

    Both tokens, because there are two ways to run the layer and only checking one
    leaves the other unguarded: the directory named directly, or the one-command
    script that names it.  The CI job uses the script deliberately, so that CI and a
    laptop cannot disagree about what "run layer 3" means.
    """
    jobs = set()
    for name, job in (_workflow().get("jobs") or {}).items():
        for step in job.get("steps") or []:
            if not isinstance(step, dict):
                continue
            run = step.get("run") or ""
            if any(token in run for token in _LAYER3_RUN_TOKENS):
                jobs.add(name)
    return jobs


# ---------------------------------------------------------------------------
# The universe must not be empty
# ---------------------------------------------------------------------------


def test_the_layer3_directory_holds_tests_at_all():
    """A coverage guard that discovers nothing reports success over an empty set."""
    files = _layer3_test_files()
    assert files, (
        f"no test_*.py found under {AGENTIC_DIR}. Either the directory was emptied "
        "or the path is wrong; every check below would then pass vacuously."
    )


# ---------------------------------------------------------------------------
# 1 — placement
# ---------------------------------------------------------------------------


def test_the_agentic_directory_is_a_sibling_of_tests_unit():
    """Sibling, not subdirectory — and the negative half is the load-bearing one."""
    assert AGENTIC_DIR.is_dir(), f"{AGENTIC_DIR} does not exist"
    assert AGENTIC_DIR.parent == UNIT_DIR.parent, (
        f"{AGENTIC_DIR} and {UNIT_DIR} do not share a parent, so 'sibling' is no "
        "longer true and the reasoning behind the placement needs re-deriving."
    )
    assert not (UNIT_DIR / "agentic").exists(), (
        f"{UNIT_DIR / 'agentic'} exists. The unit-tests job runs `pytest tests/unit` "
        "with no -m filter and no Databricks credentials, so anything under there is "
        "COLLECTED in CI regardless of the `live` marker — the marker is not a gate "
        "at that path. Move it back out to tests/agentic/."
    )


def test_only_the_layer3_job_runs_the_agentic_layer():
    """No other CI job may run this layer, deliberately or by a copied run block."""
    running = _jobs_that_run_layer3()
    assert running == {LAYER3_JOB}, (
        f"jobs that reach layer 3 from their run: block are {sorted(running)}, "
        f"expected exactly {{{LAYER3_JOB!r}}}. These tests call a real serving "
        "endpoint with real spend; a second job running them — or the layer-3 job "
        "being renamed without updating this guard — is how that starts happening "
        "on every PR."
    )


def test_the_one_command_for_this_layer_exists_and_is_executable():
    """§G1's "one command", which this repo spells as a script in ``scripts/``.

    There is no Makefile here and adding one would be novel; the convention is
    ``scripts/*.sh`` (``deploy_local.sh``, ``run_e2e_local.sh``, ``build_wheels.sh``).
    A command that is documented but not executable is not one command.
    """
    import os

    assert LAYER3_SCRIPT.is_file(), (
        f"{LAYER3_SCRIPT} is missing. Layer 3's discoverability rests on it: without "
        "it, running the layer means remembering both a directory and a marker."
    )
    assert os.access(LAYER3_SCRIPT, os.X_OK), (
        f"{LAYER3_SCRIPT} is not executable, so `./{LAYER3_SCRIPT.name}` fails and the "
        "CI job that invokes it directly would too. chmod +x it, like its neighbours."
    )
    body = LAYER3_SCRIPT.read_text()
    assert "tests/agentic" in body and "-m live" in body, (
        f"{LAYER3_SCRIPT.name} does not run `tests/agentic` with `-m live`. It must "
        "select exactly what the CI job selects, or the one command and CI diverge — "
        "which is how a suite comes to pass locally and run nowhere."
    )


# ---------------------------------------------------------------------------
# 2 — the three mechanisms
# ---------------------------------------------------------------------------


def test_gates_publishes_all_three_mechanisms():
    """Introspect the real mark objects, not the source text that produced them.

    ``LAYER3_MARKS`` is what every module assigns to ``pytestmark``, so this is the
    one place the three mechanisms can be checked as OBJECTS: a ``live`` marker, a
    ``skipif`` whose condition is currently true (nothing is reachable in CI), and an
    unconditional ``skip`` carrying a reason.
    """
    from tests.agentic import gates

    by_name = {m.mark.name: m.mark for m in gates.LAYER3_MARKS}
    assert set(by_name) == _REQUIRED_MECHANISMS, (
        f"LAYER3_MARKS supplies {sorted(by_name)}, expected "
        f"{sorted(_REQUIRED_MECHANISMS)}. Selection, safety and honesty are three "
        "different statements and none substitutes for another: the marker is how "
        "CI selects, the skipif is why an unreachable endpoint skips instead of "
        "failing, and the unconditional skip is why placeholder prompts do not turn "
        "into weakened assertions."
    )

    skip = by_name["skip"]
    assert not skip.args, (
        f"the honesty gate is conditional ({skip.args!r}). pytest.mark.skip takes no "
        "condition; a conditional one would let some environment run these "
        "assertions against placeholder prompts."
    )
    assert (skip.kwargs.get("reason") or "").strip(), (
        "the unconditional skip carries no reason. `pytest -rs` and the one-command "
        "script both print it; without it a reader sees a skip and cannot tell "
        "whether it is honest or forgotten."
    )

    skipif = by_name["skipif"]
    assert skipif.args, (
        "the endpoint gate has no condition, so it is an unconditional skip wearing "
        "the safety gate's name."
    )
    assert (skipif.kwargs.get("reason") or "").strip(), (
        "the endpoint gate carries no reason"
    )


@pytest.mark.parametrize(
    "path", _layer3_test_files(), ids=lambda p: p.name
)
def test_every_layer3_module_carries_all_three_mechanisms(path: Path):
    """Marker, endpoint guard and placeholder skip — in the module's ``pytestmark``.

    The three accepted spellings are described in ``_mechanisms``.  A per-test
    ``@pytest.mark.skip`` does not count: it gates one test, and the requirement is
    that the whole module is gated.
    """
    tree = ast.parse(path.read_text())
    found, unknown = _mechanisms(tree)
    missing = sorted(_REQUIRED_MECHANISMS - found)

    assert not missing, (
        f"{path.relative_to(REPO_ROOT)} is a layer-3 module missing {missing} from "
        "its module-level pytestmark.\n\n"
        "The simplest way to comply is the one every other module uses:\n\n"
        "    from tests.agentic.gates import LAYER3_MARKS\n"
        "    pytestmark = LAYER3_MARKS\n\n"
        "Naming LIVE / ENDPOINT_GATE / PLACEHOLDER_GATE individually works too, as "
        "does spelling pytest.mark.live / pytest.mark.skipif(...) / "
        "pytest.mark.skip(...) inline. What does NOT work is a per-test decorator: "
        "the module must be gated, not one of its tests."
        + (f"\n\nUnrecognised: {unknown}" if unknown else "")
    )


def test_every_non_test_module_under_tests_agentic_is_named_with_a_reason():
    """Support modules are allowed; unlisted ones are not.

    A helper module carries no ``pytestmark`` and cannot, so the mechanism check
    above must skip it — which means an ungated *test* module could hide by not
    being named ``test_*.py``. This is the other half: every non-test file is named
    here, with a reason, or it fails.
    """
    empty = sorted(name for name, why in _SUPPORT_MODULES.items() if not why.strip())
    assert not empty, (
        f"these support modules are listed with no reason: {empty}. A reason-less "
        "entry is indistinguishable from a file somebody forgot."
    )

    test_files = {p.name for p in _layer3_test_files()}
    unlisted = sorted(
        str(p.relative_to(AGENTIC_DIR))
        for p in _layer3_python_files()
        if p.name not in test_files and p.name not in _SUPPORT_MODULES
    )
    assert not unlisted, (
        f"these files under tests/agentic/ are neither test_*.py nor listed as "
        f"support modules: {unlisted}.\n\nIf a file holds tests, rename it to "
        "test_*.py so it is collected AND gated. If it is a helper, add it to "
        "_SUPPORT_MODULES in this file with a reason."
    )

    stale = sorted(
        name
        for name in _SUPPORT_MODULES
        if not (AGENTIC_DIR / name).exists()
    )
    assert not stale, (
        f"these support modules are listed but no longer exist: {stale}. A stale "
        "entry quietly widens the exemption for whatever is created with that name "
        "next."
    )


# ---------------------------------------------------------------------------
# 3 — wording
# ---------------------------------------------------------------------------


def test_no_layer3_module_compares_model_wording():
    """The guard on ourselves.  Layer 3 is where this temptation lives.

    §G2's rule is *structure and behavioural outcomes, never wording*.  A phrasing
    assertion is brittle against a model that says the same thing differently, and
    it measures the wrong thing: that the reply matched a sentence somebody imagined,
    rather than that the agent did the right thing.

    What is flagged: a comparison (or a ``str`` predicate such as ``startswith``)
    between an authored-prose field — ``message``, ``synthesis``, ``change_summary``,
    ``gap``, ``reason`` — and a string literal containing words.  Punctuation is not
    words, so ``"?" in out.message`` is fine: it asks whether the architect asked
    something, which is structure.

    The sanctioned exception, and it is narrow: comparing a prose field against text
    the FIXTURE supplied (a variable, not a literal) is a pass-through check, e.g.
    "the single source came back verbatim". That is an assertion about the agent
    copying the test's own input, not about phrasing it invented. A reviewer's job is
    to confirm the text really was supplied as input; a literal spelled out in the
    test never is.
    """
    offences = [o for path in _layer3_python_files() for o in _wording_comparisons(path)]
    assert not offences, (
        "these layer-3 assertions compare a model's PHRASING against a literal:\n"
        + "\n".join(f"  - {o}" for o in offences)
        + "\n\nAssert the outcome instead — the intent, the criterion, the verdict, "
        "the index, the structure. If the behaviour genuinely is 'it asked a "
        "question', assert the punctuation, not the sentence."
    )


# ---------------------------------------------------------------------------
# 4 — the placeholder era must not end quietly
# ---------------------------------------------------------------------------


def test_the_placeholder_era_skill_versions_are_unchanged():
    """The tripwire that makes "are the prompts still placeholders?" un-ignorable.

    ``Skill.version`` is documented as *"Monotonically-incremented integer —
    increment when ``instructions`` change so callers can detect staleness"*.  The
    versions that shipped WITH the placeholder prompts are pinned above, so authoring
    the prompts trips this, and whoever trips it has to decide whether layer 3 should
    still be skipped.  Without it the honest skip would quietly outlive its reason.
    """
    from src.core.skills import list_skills, load_skill

    registered = set(list_skills())
    assert registered == set(_PLACEHOLDER_ERA_VERSIONS), (
        f"the registered skills are {sorted(registered)} but the placeholder-era pin "
        f"covers {sorted(_PLACEHOLDER_ERA_VERSIONS)}. A skill was added or removed; "
        "layer 3's coverage was drawn against the old set."
    )

    moved = {
        name: (pinned, load_skill(name).version)
        for name, pinned in _PLACEHOLDER_ERA_VERSIONS.items()
        if load_skill(name).version != pinned
    }
    assert not moved, (
        "these skills' versions have moved since layer 3 was written, which by "
        "Skill.version's own contract means their instructions changed:\n"
        + "\n".join(
            f"  - {name}: pinned at {was}, now {now}" for name, (was, now) in sorted(moved.items())
        )
        + "\n\nSo decide, rather than re-pinning by reflex:\n"
        "  * if these are now AUTHORED prompts, delete PLACEHOLDER_GATE from "
        "LAYER3_MARKS in tests/agentic/gates.py — that one edit switches the whole "
        "layer on, and the assertions are already written against real prompts;\n"
        "  * if they are still placeholders, update the pin above and say so."
    )


# ---------------------------------------------------------------------------
# 5 — the payload builders must match what production sends
# ---------------------------------------------------------------------------


def test_the_architect_payload_builder_matches_architect_node():
    """A layer-3 test must not exercise a prompt shape production never builds.

    The architect's payload is the one with ten keys and the one every
    architect-behaviour test (RC10's included) is built on, so it is the one worth
    pinning mechanically.  Read out of ``architect_node``'s own dict literal rather
    than from a comment, because that is what the model actually receives.
    """
    from tests.agentic.payloads import ARCHITECT_PAYLOAD_KEYS

    tree = ast.parse(NODES.read_text())
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "architect_node"
    ]
    assert len(functions) == 1, (
        f"expected exactly one architect_node in {NODES}, found {len(functions)}. A "
        "check that cannot locate its subject must fail rather than pass over it."
    )

    dicts = [
        node.value
        for node in ast.walk(functions[0])
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Dict)
        and any(isinstance(t, ast.Name) and t.id == "payload" for t in node.targets)
    ]
    assert len(dicts) == 1, (
        f"expected exactly one `payload = {{...}}` in architect_node, found "
        f"{len(dicts)}; the parse needs updating, not skipping."
    )

    production_keys = {
        key.value
        for key in dicts[0].keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    assert production_keys == set(ARCHITECT_PAYLOAD_KEYS), (
        "tests/agentic/payloads.py's architect payload has drifted from "
        "architect_node's:\n"
        f"  only in production: {sorted(production_keys - set(ARCHITECT_PAYLOAD_KEYS))}\n"
        f"  only in the tests:  {sorted(set(ARCHITECT_PAYLOAD_KEYS) - production_keys)}\n\n"
        "A key production sends but the fixture omits means layer 3 asks the "
        "architect a question it is never asked; a key the fixture invents means the "
        "tests measure a prompt shape that does not exist."
    )
