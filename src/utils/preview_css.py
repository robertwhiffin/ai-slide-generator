"""CSS helpers for the small MCP deck preview.

Pure string work (no I/O, no CSS parser dependency). A small brace-matching
scanner treats quoted strings, comments and ``url(...)`` bodies (quoted or not)
as opaque, so braces, semicolons and whitespace inside them never affect
statement ends, brace matching or minification.

Public API:

* ``strip_embedded_font_faces`` removes ``@font-face`` rules whose ``src`` embeds
  a ``data:`` URI or a ``{{ds-asset:N}}`` handle and reports the families.
* ``google_fonts_imports`` turns that report into Google Fonts ``@import`` lines.
* ``trim_css`` strips comments, drops rules that are certainly dead for the
  given deck text, and minifies conservatively.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# family name -> {(ital, weight)} with ital 0/1
FontFaces = dict[str, set[tuple[int, int]]]

_EMBEDDED_SRC = re.compile(r"url\(\s*['\"]?\s*(?:data:|\{\{ds-asset:)", re.IGNORECASE)
_NAME_TOKEN = re.compile(r"[.#](-?[A-Za-z_][A-Za-z0-9_-]*)")
_WORD = re.compile(r"[A-Za-z0-9_-]+")
_AT_NAME = re.compile(r"@([\w-]+)")
_IDENT_CHAR = re.compile(r"[\w-]")
_TRIMMED_AT_RULES = frozenset({"media", "supports", "container", "layer"})


# ---------------------------------------------------------------------------
# scanner
# ---------------------------------------------------------------------------


def _string_end(css: str, i: int) -> int:
    """Index just past the quoted string starting at ``css[i]``."""
    quote = css[i]
    i += 1
    while i < len(css):
        if css[i] == "\\":
            i += 2
        elif css[i] == quote:
            return i + 1
        else:
            i += 1
    return len(css)


def _opaque_end(css: str, i: int) -> int:
    """If an opaque atom starts at ``i`` return the index past it, else ``i``.

    Opaque atoms: backslash escapes, quoted strings, ``/* */`` comments and
    ``url(...)`` (quoted or unquoted, up to its closing ``)``).
    """
    ch = css[i]
    if ch == "\\":
        return min(i + 2, len(css))
    if ch in "\"'":
        return _string_end(css, i)
    if css.startswith("/*", i):
        end = css.find("*/", i + 2)
        return len(css) if end < 0 else end + 2
    if css[i : i + 4].lower() == "url(" and not (i and _IDENT_CHAR.match(css[i - 1])):
        j = i + 4
        while j < len(css) and css[j].isspace():
            j += 1
        if j < len(css) and css[j] in "\"'":
            j = _string_end(css, j)
        end = css.find(")", j)
        return len(css) if end < 0 else end + 1
    return i


def _find_top(css: str, start: int, targets: str) -> int:
    """Index of the first char in ``targets`` outside opaque atoms, or -1."""
    i = start
    while i < len(css):
        end = _opaque_end(css, i)
        if end > i:
            i = end
        elif css[i] in targets:
            return i
        else:
            i += 1
    return -1


def _strip_comments(css: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(css):
        end = _opaque_end(css, i)
        if end == i:
            out.append(css[i])
            i += 1
            continue
        if not css.startswith("/*", i):
            out.append(css[i:end])
        i = end
    return "".join(out)


class _Item(NamedTuple):
    start: int  # first char of the item (leading whitespace/comments excluded)
    end: int  # index past the item
    block: int  # index of the opening '{', or -1 for a statement / stray text


def _split_items(css: str) -> list[_Item]:
    """Split top-level CSS into statements (``...;``) and blocks (``...{...}``)."""
    items: list[_Item] = []
    i = 0
    while i < len(css):
        if css[i].isspace():
            i += 1
            continue
        if css.startswith("/*", i):
            i = _opaque_end(css, i)
            continue
        stop = _find_top(css, i, ";{}")
        if stop < 0:
            items.append(_Item(i, len(css), -1))
            break
        if css[stop] != "{":
            items.append(_Item(i, stop + 1, -1))
            i = stop + 1
            continue
        depth = 1
        j = stop + 1
        while depth:
            k = _find_top(css, j, "{}")
            if k < 0:
                j = len(css)
                break
            depth += 1 if css[k] == "{" else -1
            j = k + 1
        items.append(_Item(i, j, stop))
        i = j
    return items


def _block_body(css: str, item: _Item) -> str:
    """Text between the braces of a block item (tolerates a missing ``}``)."""
    end = item.end - 1 if css.endswith("}", 0, item.end) else item.end
    return css[item.block + 1 : end]


# ---------------------------------------------------------------------------
# @font-face
# ---------------------------------------------------------------------------


def _declarations(body: str) -> dict[str, str]:
    decls: dict[str, str] = {}
    i = 0
    while i < len(body):
        end = _find_top(body, i, ";")
        end = len(body) if end < 0 else end
        name, sep, value = body[i:end].partition(":")
        if sep:
            decls[name.strip().lower()] = value.strip()
        i = end + 1
    return decls


def _font_face_entries(decls: dict[str, str]) -> tuple[str, set[tuple[int, int]]]:
    family = " ".join(decls.get("font-family", "").strip("\"' \t\r\n").split())
    ital = 1 if re.search(r"\b(?:italic|oblique)\b", decls.get("font-style", ""), re.I) else 0
    weights: set[int] = set()
    for token in decls.get("font-weight", "").lower().split():
        if token.isdigit():
            weights.add(int(token))
        elif token == "bold":
            weights.add(700)
        elif token == "normal":
            weights.add(400)
    return family, {(ital, w) for w in (weights or {400})}


def strip_embedded_font_faces(css: str) -> tuple[str, FontFaces]:
    """Remove ``@font-face`` rules embedding ``data:``/``{{ds-asset:`` fonts.

    Returns the remaining CSS (otherwise byte-for-byte unchanged) and the
    removed faces as ``{family: {(ital, weight)}}``. Faces with only
    ``http(s):`` sources stay and are not reported.
    """
    faces: FontFaces = {}
    out: list[str] = []
    pos = 0
    for item in _split_items(css):
        if item.block < 0:
            continue
        if not css[item.start : item.block].strip().lower().startswith("@font-face"):
            continue
        decls = _declarations(_strip_comments(_block_body(css, item)))
        if not _EMBEDDED_SRC.search(decls.get("src", "")):
            continue
        family, entries = _font_face_entries(decls)
        if family:
            faces.setdefault(family, set()).update(entries)
        out.append(css[pos : item.start])
        pos = item.end
    out.append(css[pos:])
    return "".join(out), faces


def google_fonts_imports(faces: FontFaces) -> str:
    """One Google Fonts ``@import`` line per family (sorted), ``""`` if none."""
    lines = []
    for family in sorted(faces):
        axes = ";".join(f"{ital},{weight}" for ital, weight in sorted(faces[family]))
        lines.append(
            "@import url('https://fonts.googleapis.com/css2?"
            f"family={family.replace(' ', '+')}:ital,wght@{axes}&display=swap');"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# trimming
# ---------------------------------------------------------------------------


def _split_selectors(prelude: str) -> list[str]:
    """Split a selector list on commas at depth 0 of ``()`` and ``[]``."""
    parts: list[str] = []
    depth = 0
    last = 0
    i = 0
    while i < len(prelude):
        end = _opaque_end(prelude, i)
        if end > i:
            i = end
            continue
        ch = prelude[i]
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(depth - 1, 0)
        elif ch == "," and depth == 0:
            parts.append(prelude[last:i])
            last = i + 1
        i += 1
    parts.append(prelude[last:])
    return parts


def _selector_names(selector: str) -> list[str]:
    """``.name`` / ``#name`` tokens outside ``[...]`` and quoted strings."""
    kept: list[str] = []
    i = 0
    while i < len(selector):
        if selector[i] == "[":
            close = _find_top(selector, i + 1, "]")
            i = len(selector) if close < 0 else close + 1
            kept.append(" ")
            continue
        end = _opaque_end(selector, i)
        if end > i:
            kept.append(" ")
            i = end
            continue
        kept.append(selector[i])
        i += 1
    return _NAME_TOKEN.findall("".join(kept))


def _is_dead(selector: str, words: set[str]) -> bool:
    if "\\" in selector or "(" in selector:
        return False
    return any(name not in words for name in _selector_names(selector))


def _trim_items(css: str, words: set[str]) -> str:
    out: list[str] = []
    for item in _split_items(css):
        text = css[item.start : item.end]
        if item.block < 0:
            out.append(text.strip())
            continue
        prelude = css[item.start : item.block].strip()
        body = _block_body(css, item)
        if prelude.startswith("@"):
            match = _AT_NAME.match(prelude)
            if match and match.group(1).lower() in _TRIMMED_AT_RULES:
                inner = _trim_items(body, words)
                if inner:
                    out.append(f"{prelude}{{{inner}}}")
            else:
                out.append(text)
            continue
        kept = [s.strip() for s in _split_selectors(prelude) if not _is_dead(s, words)]
        if kept:
            out.append(f"{','.join(kept)}{{{body}}}")
    return "".join(out)


def _minify(css: str) -> str:
    """Collapse whitespace; drop it next to ``{ } ;`` and the last ``;`` before ``}``."""
    out: list[str] = []
    pending_space = False
    i = 0
    while i < len(css):
        ch = css[i]
        if ch.isspace():
            pending_space = True
            i += 1
            continue
        end = _opaque_end(css, i)
        chunk = css[i:end] if end > i else ch
        i = max(end, i + 1)
        if pending_space and out and out[-1] not in "{};" and ch not in "{};":
            out.append(" ")
        pending_space = False
        if ch == "}" and out and out[-1] == ";":
            out.pop()
        out.append(chunk)
    return "".join(out)


def trim_css(css: str, used_text: str) -> str:
    """Strip comments, drop certainly-dead rules, and minify.

    A selector is dead only when it holds neither ``\\`` nor ``(`` and at least
    one ``.name`` / ``#name`` token (outside ``[...]``) is not a whole word of
    ``used_text``. Anything unclassifiable is kept. ``@media``, ``@supports``,
    ``@container`` and ``@layer`` blocks are trimmed recursively (and dropped
    when empty); every other at-rule is kept verbatim.
    """
    words = set(_WORD.findall(used_text))
    return _minify(_trim_items(_strip_comments(css), words))
