"""Reconcile ``{{image:TOKEN}}`` references against the tokens that really exist.

A model that mistypes an image token's tail, or invents one, must not break a
slide:

- a known reference is kept;
- an unknown reference of at least 12 characters is replaced by the one known
  token that shares its first 12 characters (none or several: no fix);
- otherwise it is removed and reported.  In HTML a removed reference takes its
  whole ``<img ...>`` element with it, or, inside ``url(...)``, the whole
  ``background-image`` declaration.

This module must not import ``src.core.skills``.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from typing import Any, Final

from src.utils.image_utils import IMAGE_PLACEHOLDER_PATTERN

#: The one shared placeholder pattern: ``{{image:TOKEN}}``, group 1 is the token.
IMAGE_REF_RE: Final = IMAGE_PLACEHOLDER_PATTERN

_PREFIX_LEN: Final = 12
_IMG_RE: Final = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_BG_DECL_RE: Final = re.compile(
    r"\s*background-image\s*:\s*url\(\s*['\"]?\{\{image:([A-Za-z0-9_-]+)\}\}['\"]?\s*\)\s*;?",
    re.IGNORECASE,
)
_SLIDE_PATH_RE: Final = re.compile(r"^deck_spec\.slides\[(\d+)\]")
_OP_PATH_RE: Final = re.compile(r"^operations\[(\d+)\](?:\.slides\[(\d+)\])?")


def _resolve(ref: str, known: Collection[str]) -> str | None:
    """The known token *ref* stands for, or ``None`` if it cannot be pinned to one."""
    if ref in known:
        return ref
    if len(ref) < _PREFIX_LEN:
        return None
    matches = {token for token in known if token[:_PREFIX_LEN] == ref[:_PREFIX_LEN]}
    return next(iter(matches)) if len(matches) == 1 else None


def reconcile_text(text: str, known: Collection[str]) -> tuple[str, list[str]]:
    """*text* with unknown references fixed or removed, and the refs removed."""
    removed: list[str] = []

    def replace(match: re.Match[str]) -> str:
        ref = match.group(1)
        token = _resolve(ref, known)
        if token is None:
            removed.append(ref)
            return ""
        return "{{image:" + token + "}}"

    return IMAGE_REF_RE.sub(replace, text), removed


def reconcile_html(html: str, known: Collection[str]) -> tuple[str, list[str]]:
    """Like :func:`reconcile_text`, but a removed reference takes its ``<img>``
    element (or its ``background-image`` declaration) with it."""
    removed: list[str] = []

    def img(match: re.Match[str]) -> str:
        refs = IMAGE_REF_RE.findall(match.group(0))
        unresolved = [ref for ref in refs if _resolve(ref, known) is None]
        if not unresolved:
            return match.group(0)  # the text pass below corrects a typo in place
        removed.extend(unresolved)
        return ""

    def declaration(match: re.Match[str]) -> str:
        ref = match.group(1)
        if _resolve(ref, known) is not None:
            return match.group(0)
        removed.append(ref)
        return ""

    html = _IMG_RE.sub(img, html)
    html = _BG_DECL_RE.sub(declaration, html)
    html, rest = reconcile_text(html, known)
    return html, removed + rest


def refs_in(obj: Any) -> set[str]:
    """Every image reference in any string inside a nested dict/list."""
    if isinstance(obj, str):
        return set(IMAGE_REF_RE.findall(obj))
    found: set[str] = set()
    if isinstance(obj, dict):
        for value in obj.values():
            found |= refs_in(value)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            found |= refs_in(value)
    return found


def reconcile_model_strings(
    obj: Any, known: Collection[str]
) -> tuple[Any, list[tuple[str, str]]]:
    """A copy of *obj* with :func:`reconcile_text` applied to every string, and the
    removals as ``(json_path, ref)``, a path like ``deck_spec.slides[2].content_brief``."""
    removed: list[tuple[str, str]] = []

    def walk(node: Any, path: str) -> Any:
        if isinstance(node, str):
            fixed, gone = reconcile_text(node, known)
            removed.extend((path, ref) for ref in gone)
            return fixed
        if isinstance(node, dict):
            return {
                key: walk(value, f"{path}.{key}" if path else str(key))
                for key, value in node.items()
            }
        if isinstance(node, list):
            return [walk(value, f"{path}[{index}]") for index, value in enumerate(node)]
        return node

    return walk(obj, ""), removed


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _slide_number(output: dict, path: str) -> int | None:
    try:
        match = _SLIDE_PATH_RE.match(path)
        if match:
            slide = output["deck_spec"]["slides"][int(match.group(1))]
            position = _int_or_none(slide.get("position"))
            return None if position is None else position + 1
        match = _OP_PATH_RE.match(path)
        if match:
            op = output["operations"][int(match.group(1))]
            if op.get("op") == "insert":
                after = _int_or_none(op.get("after_position"))
                if after is None or match.group(2) is None:
                    return None
                return after + 2 + int(match.group(2))
            position = _int_or_none(op.get("position"))
            return None if position is None else position + 1
    except (KeyError, IndexError, TypeError, AttributeError):
        return None
    return None


def removed_slide_numbers(
    architect_output: dict, removed: list[tuple[str, str]]
) -> list[int | None]:
    """The 1-based slide number each removal belongs to (``None`` if none applies)."""
    return [_slide_number(architect_output, path) for path, _ref in removed]
