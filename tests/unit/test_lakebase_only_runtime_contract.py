"""Structural guards: the runtime resolves Agent Definitions only from Lakebase (#271).

The compatibility runtime (code-owned ``Skill`` records exposed as Agent
Definitions) was deleted in #271 Task 12.  These guards pin that it stays gone and
that no ``src/`` module grows a second, code-owned definition source:

1. the retired names are absent from ``src.services.agent_runtime``;
2. ``src.core.skills`` is imported by ``src/`` only for the six protected-bundle
   names ``prompt_assembler.py`` reads (Corrections C6, C20, C31);
3. the Graph Version 1 bootstrap manifest is read only by its own loader module
   and by bootstrap (Correction C30);
4. no module on the Agent Definition resolution path reads code-owned model
   defaults, and the runtime module carries no tool-grant field (AC5; C6, C31);
5. both production runtime factories resolve through the persisted-release
   loader (a regression pin: it already held before the deletion).
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

import src.services.agent_runtime as runtime_module
from src.services.agent_runtime import AgentRuntime

_SRC = pathlib.Path(runtime_module.__file__).resolve().parents[1]
_RETIRED = {
    "CodeOwnedAgentDefinitionSource",
    "CompatibilityResolvedDefinitionLoader",
    "AgentDefinitionSource",
    "AgentDefinition",
    "TEST_COMPATIBILITY_GRAPH_RELEASE_ID",
    "TEST_COMPATIBILITY_GRAPH_VERSION",
    "RuntimeContractIdentityError",
    "_SchemaContractRegistry",
    # R5: the duplicated v1 identity machinery.  ``agent_schema_registry`` owns
    # the one copy; a second one here would be a second, drift-prone oracle.
    "_canonical_digest",
    "_schema_contract_material",
    "_schema_configuration_material",
    "_schema_validator_material",
    "_SCHEMA_CONTRACT_VERSION",
    "_SCHEMA_CONTRACT_DIGESTS",
    "_PROTECTED_PROMPT_VERSION",
    "_PROTECTED_PROMPT_DIGEST",
    # R7: the code-owned inputs the deleted source read.
    "load_skill",
    "DEFAULT_CONFIG",
    "OUTPUT_SCHEMAS",
    "load_graph_v1_manifest",
}

_SKILLS_PACKAGE = "src.core.skills"

#: (importing file relative to ``src/``, imported module, imported name) — the
#: exact protected-bundle material ``prompt_assembler.py:15-27`` reads (C31).
_ASSEMBLER = "services/prompt_assembler.py"
_BUILD_REVIEWER = "src.core.skills.build_reviewer"
_DATA_ANALYST = "src.core.skills.data_analyst"
_ALLOWED_SKILLS_IMPORTS = {
    (_ASSEMBLER, _BUILD_REVIEWER, "BUILD_REVIEWER_AUTHORED_INSTRUCTIONS"),
    (_ASSEMBLER, _BUILD_REVIEWER, "BUILD_REVIEWER_CRITERIA_STAGE"),
    (_ASSEMBLER, _BUILD_REVIEWER, "DECK_BRIEF_REVIEW"),
    (_ASSEMBLER, _BUILD_REVIEWER, "INSTRUCTIONS"),
    (_ASSEMBLER, _DATA_ANALYST, "ANALYST_AUTHORED_INSTRUCTIONS"),
    (_ASSEMBLER, _DATA_ANALYST, "INSTRUCTIONS"),
}

#: Every module on the Agent Definition resolution path (C6 instruction 2).
_RESOLUTION_PATH = (
    "services/agent_runtime.py",
    "services/persisted_graph_release.py",
    "services/prompt_assembler.py",
    "services/agent_schema_registry.py",
)
_DEFAULT_LLM_READ = re.compile(r"""DEFAULT_CONFIG\s*(\[\s*["']llm["']|\.get\(\s*["']llm["'])""")


def _src_files() -> list[pathlib.Path]:
    return sorted(_SRC.rglob("*.py"))


def _relative(path: pathlib.Path) -> str:
    return path.relative_to(_SRC).as_posix()


def _is_skills_module(module: str) -> bool:
    return module == _SKILLS_PACKAGE or module.startswith(_SKILLS_PACKAGE + ".")


def _package_of(path: pathlib.Path) -> str:
    """The dotted package a ``src/`` file's relative imports resolve against.

    Its containing directory, for a module and for a package's ``__init__.py``.
    """
    return ".".join(path.resolve().relative_to(_SRC.parent).parent.parts)


def _absolute_module(node: ast.ImportFrom, package: str) -> str | None:
    """Resolve an ``ImportFrom`` to its absolute module, as the import system would.

    ``level`` 1 is the file's own package; each further level drops one parent.
    Returns ``None`` for a relative import that climbs above the top package.
    """
    if node.level == 0:
        return node.module
    parts = package.split(".")
    if node.level - 1 >= len(parts):
        return None
    base = ".".join(parts[: len(parts) - (node.level - 1)])
    return f"{base}.{node.module}" if node.module else base


def _skills_imports_in(source: str, package: str):
    """Yield (module, name) for every ``src.core.skills`` import in one source.

    Catches ``from src.core.skills[.x] import y``, ``import src.core.skills[.x]``
    (the form a function-level sabotage uses, C31), ``from src.core import
    skills``, and every relative spelling of those (``from ..core.skills import
    y``, ``from ..core import skills``, ``from . import skills``), which are
    resolved against ``package`` first (fix round 1, I1).  A whole-package
    binding yields the name ``"*"``, which can never be allowlisted.  A relative
    import that cannot be resolved is reported as an offender, never skipped.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = _absolute_module(node, package)
            if module is None:
                for alias in node.names:
                    yield f"<unresolved relative import level {node.level}>", alias.name
            elif _is_skills_module(module):
                for alias in node.names:
                    yield module, alias.name
            else:
                for alias in node.names:
                    if _is_skills_module(f"{module}.{alias.name}"):
                        yield f"{module}.{alias.name}", "*"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if _is_skills_module(alias.name):
                    yield alias.name, "*"


def _skills_imports(path: pathlib.Path):
    return _skills_imports_in(path.read_text(encoding="utf-8"), _package_of(path))


def test_the_compatibility_runtime_is_gone():
    assert not hasattr(AgentRuntime, "compatibility")
    assert _RETIRED.isdisjoint(vars(runtime_module))


def test_no_src_module_reads_code_owned_agent_definitions():
    seen = set()
    offenders = []
    for path in _src_files():
        relative = _relative(path)
        if relative.startswith("core/skills/"):
            continue
        for module, name in _skills_imports(path):
            entry = (relative, module, name)
            if entry in _ALLOWED_SKILLS_IMPORTS:
                seen.add(entry)
            else:
                offenders.append(entry)
    assert offenders == []
    # The allowlist is exact: a name dropped from prompt_assembler must leave it too.
    assert seen == _ALLOWED_SKILLS_IMPORTS


def test_the_bootstrap_manifest_is_read_only_by_bootstrap():
    readers = set()
    for path in _src_files():
        text = path.read_text(encoding="utf-8")
        if "load_graph_v1_manifest" in text or "agent_definition_manifest_v1" in text:
            readers.add(_relative(path))
    assert readers == {
        "services/graph_definition_manifest.py",
        "services/graph_configuration_bootstrap.py",
    }


def test_the_runtime_module_reads_no_code_default_model_configuration():
    text = pathlib.Path(runtime_module.__file__).read_text(encoding="utf-8")
    assert "DEFAULT_CONFIG" not in text and "tool_grants" not in text

    resolution_path = [_SRC / relative for relative in _RESOLUTION_PATH]
    resolution_path += sorted((_SRC / "services" / "graph").rglob("*.py"))
    readers = [
        _relative(path)
        for path in resolution_path
        if _DEFAULT_LLM_READ.search(path.read_text(encoding="utf-8"))
    ]
    assert readers == []


def test_production_runtimes_resolve_only_persisted_releases():
    from src.services.agent_runtime import get_agent_runtime, get_agent_test_runtime
    from src.services.persisted_graph_release import PersistedGraphReleaseLoader

    for factory in (get_agent_runtime, get_agent_test_runtime):
        factory.cache_clear()
        assert type(factory()._persisted_release_loader) is PersistedGraphReleaseLoader
        factory.cache_clear()


# ---------------------------------------------------------------------------
# Guard 2's import walk, driven on synthetic sources (fix round 1, I1): every
# spelling of a ``src.core.skills`` import must resolve to its absolute module,
# relative imports included.
# ---------------------------------------------------------------------------


_SK = _SKILLS_PACKAGE
_SVC = "src.services"


@pytest.mark.parametrize(
    ("source", "package", "expected"),
    [
        ("from src.core.skills import load_skill", _SVC, {(_SK, "load_skill")}),
        ("import src.core.skills", _SVC, {(_SK, "*")}),
        ("from src.core import skills", _SVC, {(_SK, "*")}),
        # The reviewer's probe, verbatim.
        ("from ..core.skills import load_skill as _probe", _SVC, {(_SK, "load_skill")}),
        ("from ..core import skills", _SVC, {(_SK, "*")}),
        (
            "from ...core.skills.data_analyst import INSTRUCTIONS",
            "src.services.graph",
            {(f"{_SK}.data_analyst", "INSTRUCTIONS")},
        ),
        ("from . import skills", "src.core", {(_SK, "*")}),
        ("from .skills import load_skill", "src.core", {(_SK, "load_skill")}),
        ("def f():\n    from ..core.skills import load_skill\n", _SVC, {(_SK, "load_skill")}),
        ("from ....skills import x", _SVC, {("<unresolved relative import level 4>", "x")}),
        ("from . import prompt_assembler", _SVC, set()),
        ("from ..core import defaults", _SVC, set()),
    ],
)
def test_the_import_walk_resolves_every_spelling_of_a_skills_import(source, package, expected):
    assert set(_skills_imports_in(source, package)) == expected


def test_the_package_of_a_src_file_is_its_dotted_directory():
    assert _package_of(_SRC / "services" / "persisted_graph_release.py") == "src.services"
    assert _package_of(_SRC / "services" / "graph" / "nodes.py") == "src.services.graph"
    assert _package_of(_SRC / "core" / "skills" / "__init__.py") == "src.core.skills"
