"""The one shared shape of a chat turn's ``generated_images`` metadata.

The graph node builds the metadata with :func:`sanitize_generated_images` and
``SessionManager.msg_to_stream_event`` filters what it forwards to polling clients with
it, so the backend, the polling path and the frontend agree on a single shape::

    {"token": "abc_DEF-1", "kind": "illustration", "option": 1,
     "prompt": "<= 300 chars", "for_slide": 3, "slides": [2]}

An entry with an invalid ``token``, ``kind`` or ``option`` is dropped; unknown keys are
dropped; a bad optional field is repaired (``for_slide`` becomes null, ``slides`` keeps its
valid numbers, a bad ``prompt`` is left out).  Nothing here ever raises.
"""

from __future__ import annotations

import re
from typing import Any, Final

GENERATED_IMAGE_KINDS: Final = ("illustration", "background", "icon", "vector_icon")
GENERATED_IMAGE_KEYS: Final = ("token", "kind", "option", "prompt", "for_slide", "slides")
MAX_PROMPT_CHARS: Final = 300

_TOKEN_RE: Final = re.compile(r"[A-Za-z0-9_-]+")


def _positive_int(value: object) -> bool:
    return type(value) is int and value >= 1


def _one(entry: object) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    token = entry["token"] if "token" in entry else None
    kind = entry["kind"] if "kind" in entry else None
    option = entry["option"] if "option" in entry else None
    if not (isinstance(token, str) and _TOKEN_RE.fullmatch(token)):
        return None
    if not (isinstance(kind, str) and kind in GENERATED_IMAGE_KINDS):
        return None
    if not _positive_int(option):
        return None
    out: dict[str, Any] = {"token": token, "kind": kind, "option": option}
    if "prompt" in entry and isinstance(entry["prompt"], str):
        out["prompt"] = entry["prompt"][:MAX_PROMPT_CHARS]
    if "for_slide" in entry:
        value = entry["for_slide"]
        out["for_slide"] = value if _positive_int(value) else None
    if "slides" in entry:
        value = entry["slides"]
        slides: list[int] = []
        if isinstance(value, list):
            slides = [n for n in value if _positive_int(n)]
        out["slides"] = slides
    return {key: out[key] for key in GENERATED_IMAGE_KEYS if key in out}


def sanitize_generated_images(value: object) -> list[dict]:
    """The valid entries of *value*, each reduced to the shared shape; ``[]`` for junk."""
    if not isinstance(value, list):
        return []
    result: list[dict] = []
    try:
        for entry in value:
            try:
                clean = _one(entry)
            except Exception:  # noqa: BLE001 - hostile input must never raise
                continue
            if clean is not None:
                result.append(clean)
    except Exception:  # noqa: BLE001
        return []
    return result
