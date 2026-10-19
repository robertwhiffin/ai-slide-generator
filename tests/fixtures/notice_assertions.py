"""Shared assertions for the plain-language failure notices (#321).

Task 1 (``tests/unit/test_graph_user_notices.py``) runs these over every notice
the catalogue in ``src/services/graph/user_notices.py`` can produce; Task 3 runs
them over the ``info`` rows the real graph nodes persist.

* ``assert_plain_language(text)`` fails on anything technical leaking into a
  user-facing string: snake_case or CamelCase tokens, ``[`` or ``(`` (how a
  Python list or a ``(stage: Error)`` suffix would leak), the words "position"
  and "reconcile", a graph node / stage identifier, or an exception class name.
  Identifiers and class names are matched as WHOLE WORDS, so "built",
  "building", "build" and "fix" never trip the ``builder`` / ``fixer`` checks.
* ``assert_numbered(text, position)`` requires the 1-based slide number for the
  0-based ``position`` and forbids the 0-based one.
* ``failure_notice_records(caplog)`` returns the ``graph_failure_notice`` WARNING
  records — the one log line written per failure notice (D6).

Every failure names the offending token(s) and the full text, so a red run says
exactly what leaked.
"""

from __future__ import annotations

import logging
import re
from typing import List

import pytest

# A snake_case token: a stage id (``build_reviewer``), a code
# (``end_with_outstanding_positions``) or any other Python identifier.
_SNAKE_CASE = re.compile(r"\b[a-z]+_[a-z_]+\b")
# A CamelCase token: an exception or class name (``ValidationError``).
_CAMEL_CASE = re.compile(r"\b[A-Z][a-z]+[A-Z]\w*\b")
# An acronym-led class name (``OSError``, ``JSONDecodeError``, ``HTTPError``): two or
# more capitals running straight into lowercase. "AI" alone does not match.
_ACRONYM_CAMEL_CASE = re.compile(r"\b[A-Z]{2,}[a-z]\w*\b")
# How a Python list (``[1, 3]``) or a ``(stage: Error)`` suffix would leak.
_FORBIDDEN_CHARACTERS = ("[", "(")
# Internal vocabulary, matched case-insensitively as a substring (so the plural
# "positions" and "reconciled" are caught too).
_FORBIDDEN_WORDS = ("position", "reconcile")

# Graph node / pipeline stage identifiers.  Whole words, case-insensitive: a
# sentence-initial "Builder" is still the node's name, but "built"/"building"
# are ordinary English and must not match.
STAGE_IDENTIFIERS = (
    "builder",
    "build_reviewer",
    "fixer",
    "fix_reviewer",
    "foreman",
    "deck_reviewer",
    "slide_pipeline",
    "architect",
    "data_analyst",
)
# Exception class names a failure site can catch or a runtime can raise.  Whole
# words, case-sensitive — they are class names.  ``Exception`` is listed because
# it is not CamelCase, so the CamelCase pattern alone would let it through.
EXCEPTION_CLASS_NAMES = (
    "ValidationError",
    "OutputParserException",
    "AgentOutputValidationError",
    "UnsafeContentError",
    "RuntimeError",
    "PinnedInvocationEndpointError",
    "PersistedRuntimeError",
    "ModelProviderUnavailableError",
    "KeyError",
    "Exception",
)

_STAGE_IDENTIFIER_PATTERNS = tuple(
    (name, re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)) for name in STAGE_IDENTIFIERS
)
_EXCEPTION_CLASS_PATTERNS = tuple(
    (name, re.compile(rf"\b{re.escape(name)}\b")) for name in EXCEPTION_CLASS_NAMES
)

FAILURE_NOTICE_LOG_PREFIX = "graph_failure_notice "


def plain_language_offences(text: str) -> List[str]:
    """Every reason *text* is not plain language, each naming the offending token."""
    offences: List[str] = []
    for match in _SNAKE_CASE.finditer(text):
        offences.append(f"snake_case token {match.group(0)!r}")
    for match in _CAMEL_CASE.finditer(text):
        offences.append(f"CamelCase token {match.group(0)!r}")
    for match in _ACRONYM_CAMEL_CASE.finditer(text):
        offences.append(f"CamelCase token {match.group(0)!r}")
    for character in _FORBIDDEN_CHARACTERS:
        if character in text:
            offences.append(f"character {character!r}")
    lowered = text.lower()
    for word in _FORBIDDEN_WORDS:
        if word in lowered:
            offences.append(f"internal word {word!r}")
    for name, pattern in _STAGE_IDENTIFIER_PATTERNS:
        match = pattern.search(text)
        if match:
            offences.append(f"stage identifier {match.group(0)!r} (matches {name!r})")
    for name, pattern in _EXCEPTION_CLASS_PATTERNS:
        if pattern.search(text):
            offences.append(f"exception class name {name!r}")
    return offences


def assert_plain_language(text: str) -> None:
    """Fail unless *text* is a non-empty string free of any technical leak."""
    if not isinstance(text, str):
        raise AssertionError(
            f"expected the notice to be a str, got {type(text).__name__}: {text!r}"
        )
    if not text.strip():
        raise AssertionError(f"expected a non-empty notice, got {text!r}")
    offences = plain_language_offences(text)
    if offences:
        raise AssertionError(
            "notice is not plain language — found " + "; ".join(offences) + f"\n  text: {text!r}"
        )


def assert_numbered(text: str, position: int) -> None:
    """Fail unless *text* names the slide at 0-based *position* by its 1-based number.

    ``Slide {position + 1}`` must appear as a whole number (so "Slide 10" does not
    satisfy position 0), and ``slide {position}`` must not appear in any case.
    """
    number = position + 1
    if not re.search(rf"\b[Ss]lide {number}\b", text):
        raise AssertionError(
            f"expected the 1-based 'Slide {number}' for 0-based position {position}"
            f"\n  text: {text!r}"
        )
    zero_based = re.search(rf"\bslide {position}\b", text, re.IGNORECASE)
    if zero_based:
        raise AssertionError(
            f"found the 0-based {zero_based.group(0)!r} for position {position} "
            f"(the UI calls it slide {number})\n  text: {text!r}"
        )


def failure_notice_records(caplog: pytest.LogCaptureFixture) -> List[logging.LogRecord]:
    """The captured ``graph_failure_notice`` log records, in emission order."""
    return [
        record
        for record in caplog.records
        if record.getMessage().startswith(FAILURE_NOTICE_LOG_PREFIX)
    ]
