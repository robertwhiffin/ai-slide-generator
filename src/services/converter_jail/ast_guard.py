# src/services/converter_jail/ast_guard.py
"""Best-effort AST import allowlist for generated converter code.

Defense-in-depth ONLY — bypassable by construction (e.g. __import__,
importlib). The security boundary is the subprocess jail, not this check.
Runs on the trusted host before launch so obviously-hostile code never
reaches the child.
"""

import ast


class DisallowedImport(Exception):
    """Raised when generated code imports a module outside the allowlist."""


# Top-level module names generated converters legitimately need.
# Keep this GENEROUS for harmless stdlib: a snippet failing this check is
# downgraded to a blank placeholder slide (has_code=False in the job-dir
# builders, Tasks 4/6), so a too-narrow list silently blanks legitimate
# slides. The prompts only show example imports — they do not restrict the
# LLM to a fixed set — and the jail, not this list, is the security boundary.
DEFAULT_ALLOWED = frozenset({
    # PPTX path
    "pptx", "os", "re", "math", "json", "uuid", "base64", "io",
    "datetime", "collections", "itertools", "string", "textwrap",
    # harmless stdlib the LLM commonly emits unprompted
    "sys", "time", "typing", "functools", "random", "copy",
    "html", "unicodedata", "decimal",
    # image handling
    "PIL", "lxml",
    # Google Slides path emits data only; googleapiclient is host-side now,
    # but allow the http helper import in case a snippet still references it
    # (host strips its effect; import alone is harmless).
    "googleapiclient",
    "xml",
})


def _root(name: str) -> str:
    return name.split(".", 1)[0]


def check_imports(code: str, allowed: frozenset = DEFAULT_ALLOWED) -> None:
    """Raise DisallowedImport if *code* imports a non-allowlisted top-level
    module. Raises SyntaxError if *code* does not parse."""
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _root(alias.name) not in allowed:
                    raise DisallowedImport(_root(alias.name))
        elif isinstance(node, ast.ImportFrom):
            # Relative imports (node.level > 0) have no module root to check;
            # they cannot reach outside the (nonexistent) package, so allow.
            if node.level == 0 and node.module is not None:
                if _root(node.module) not in allowed:
                    raise DisallowedImport(_root(node.module))
