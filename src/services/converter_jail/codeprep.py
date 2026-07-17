# src/services/converter_jail/codeprep.py
"""Dependency-light code-prep helpers shared by the jail runners (SDR-4437 PR-5).

STDLIB-ONLY BY DESIGN. This module is imported inside the sandboxed child
(`python -I`), so it must never pull in `databricks`, `google*`, `bs4`,
`pptx`, or any `src.services.*` converter module — those graphs drag the
credential-capable SDK into the jail just to call string transformers.

Contents:
- ``sanitize_code``       — moved verbatim from ``HtmlToPptxConverterV3._sanitize_code``.
- ``_fix_apostrophe_strings`` / ``_convert_single_to_double_quoted`` — moved
  verbatim from ``html_to_google_slides``.
- ``prepare_requests_code`` — preps generated Google Slides data-out code
  (wraps bare code into ``build_slide_requests``; request-shape fixes).
"""

import ast
import re


def sanitize_code(code: str) -> str:
    """Fix common LLM-generated code issues before execution.

    Handles smart quotes, em-dashes, and apostrophes inside string literals
    that cause SyntaxError (e.g. ``Anthony's`` inside a single-quoted string).
    """
    # Smart/curly quotes → straight quotes
    for smart, straight in {
        "‘": "'", "’": "'",   # single curly quotes
        "“": '"', "”": '"',   # double curly quotes
    }.items():
        code = code.replace(smart, straight)

    # Em-dash / en-dash → regular hyphen (prevents SyntaxError when
    # they appear outside strings due to broken quoting)
    code = code.replace("—", "-")   # em-dash
    code = code.replace("–", "-")   # en-dash

    # Fix apostrophes inside single-quoted strings (e.g. 'Anthony's workflow')
    # by converting affected lines to use double-quoted strings.
    for _ in range(20):
        try:
            ast.parse(code)
            break
        except SyntaxError as exc:
            if exc.lineno is None:
                break
            lines = code.splitlines()
            idx = exc.lineno - 1
            if idx < 0 or idx >= len(lines):
                break
            original = lines[idx]
            # Re-quote single-quoted strings that contain apostrophes
            fixed = re.sub(
                r"'([^']*\w'\w[^']*)'",
                lambda m: '"' + m.group(1) + '"',
                original,
            )
            if fixed == original:
                break
            lines[idx] = fixed
            code = "\n".join(lines)
    return code


# ---------------------------------------------------------------------------
# Apostrophe-in-string syntax fixer
# ---------------------------------------------------------------------------

def _convert_single_to_double_quoted(line: str) -> str:
    """Re-quote single-quoted strings that contain apostrophes as double-quoted.

    Scans each single-quote-delimited token on *line*.  When an apostrophe is
    surrounded by word characters (``\\w'\\w``) it is treated as part of the
    content (not a closing delimiter), so the scanner continues until it finds a
    genuine closing quote.  Those strings are then re-emitted with double-quote
    delimiters so Python can parse them correctly.

    Example::

        'We didn't do it'  →  "We didn't do it"
    """
    result: list = []
    i = 0
    n = len(line)

    while i < n:
        if line[i] != "'":
            result.append(line[i])
            i += 1
            continue

        # Scan for the "real" closing quote, treating word-apostrophe-word as content.
        j = i + 1
        while j < n:
            if line[j] == "'":
                before_word = j > 0 and line[j - 1].isalnum()
                after_word = (j + 1) < n and line[j + 1].isalnum()
                if before_word and after_word:
                    j += 1  # it's a contraction apostrophe — keep scanning
                    continue
                break  # genuine closing quote
            j += 1

        if j >= n:
            # Never found a real closing quote — rest of line is broken content.
            content = line[i + 1:]
            result.append('"' + content.replace('"', '\\"') + '"')
            break

        content = line[i + 1: j]
        if re.search(r"\w'\w", content):
            # Content has an apostrophe → rewrite as double-quoted string.
            result.append('"' + content.replace('"', '\\"') + '"')
        else:
            result.append(line[i: j + 1])

        i = j + 1

    return "".join(result)


def _fix_apostrophe_strings(code: str) -> str:
    """Fix single-quoted literals whose content contains apostrophes (contractions).

    The LLM often emits ``'text': 'We don't ...'``.  The ``'`` in *don't* ends the
    literal early; the parser may report ``unterminated string``, ``eol while
    scanning``, or ``invalid character`` (e.g. em-dash) on the remainder.

    Repeatedly ``ast.parse`` and rewrite the error line with
    :func:`_convert_single_to_double_quoted` whenever that changes the line.
    """
    for _ in range(20):  # guard against infinite loops
        try:
            ast.parse(code)
            return code
        except SyntaxError as exc:
            if exc.lineno is None:
                return code

            lines = code.splitlines()
            line_idx = exc.lineno - 1
            if line_idx >= len(lines):
                return code

            original = lines[line_idx]
            fixed = _convert_single_to_double_quoted(original)
            if fixed == original:
                return code  # heuristic cannot improve this error

            lines[line_idx] = fixed
            code = "\n".join(lines)

    return code


# ---------------------------------------------------------------------------
# Google Slides data-out contract prep
# ---------------------------------------------------------------------------

_ALPHA_PAT = re.compile(r"""[,\s]*['"]alpha['"]\s*:\s*[\d.]+""")


def prepare_requests_code(code: str) -> str:
    """Prep generated code that defines build_slide_requests(...).

    Reuses the request-shape fixers from the legacy ``_prepare_code`` but wraps
    bare code into ``build_slide_requests`` (not ``add_slide_to_presentation``)
    and never references services."""
    if "def build_slide_requests" not in code:
        lines = code.split("\n")
        imports, body, helpers = [], [], []
        in_helper = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")) and not body:
                imports.append(line)
            elif stripped.startswith(("def emu(", "def hex_to_rgb(")):
                in_helper = True
                helpers.append(line)
            elif in_helper:
                if stripped == "" or (line and line[0] == " "):
                    helpers.append(line)
                    if stripped == "":
                        in_helper = False
                else:
                    in_helper = False
                    body.append(line)
            else:
                body.append(line)
        indented = [("    " + l if l.strip() else "") for l in body]
        parts = []
        if imports:
            parts.append("\n".join(imports) + "\n")
        if helpers:
            parts.append("\n".join(helpers) + "\n")
        parts.append("def build_slide_requests(html_str, assets_dir, page_id):")
        parts.extend(indented)
        parts.append("    return requests")
        code = "\n".join(parts)

    if "import os" not in code:
        code = "import os\nimport json\nimport uuid\n\n" + code

    for smart, straight in {"‘": "'", "’": "'", "“": '"', "”": '"'}.items():
        code = code.replace(smart, straight)

    if "alpha" in code:
        code = _ALPHA_PAT.sub("", code)
    if "'paragraphStyle'" in code:
        code = code.replace("'paragraphStyle'", "'style'")
    if '"paragraphStyle"' in code:
        code = code.replace('"paragraphStyle"', '"style"')
    if "'textStyle'" in code:
        code = code.replace("'textStyle'", "'style'")
    if '"textStyle"' in code:
        code = code.replace('"textStyle"', '"style"')

    code = _fix_apostrophe_strings(code)
    return code
