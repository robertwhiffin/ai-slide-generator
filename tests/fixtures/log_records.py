"""Log-record rendering helper for tests that check the log surface.

``rendered_record`` emits everything a handler could write for a record —
message, args, extras, and exception text — but never source-location attributes
(``pathname``, ``filename``, ``module``, ``funcName``, ``lineno``, ``created``,
etc.).  This prevents a test run from a path that contains a substring the test
checks (e.g. macOS's ``/private/tmp`` containing "private") from causing a false
positive.

``STANDARD_LOG_RECORD_ATTRS`` is the frozenset of attribute names that the stdlib
attaches to every ``LogRecord``.  The difference between ``vars(record)`` and this
set is exactly what an ``extra=`` dict contributed.

Both names are part of the public fixture interface and are consumed by Tasks 6–8.
``taskName`` is unioned in explicitly so that a Python 3.12 run (which adds it to
every ``LogRecord``) and a 3.11 run render identically.
"""

from __future__ import annotations

import logging

STANDARD_LOG_RECORD_ATTRS: frozenset[str] = (
    frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}
)


def rendered_record(record: logging.LogRecord) -> str:
    """Everything a handler could emit for *record* except its source location."""
    extras = {k: v for k, v in vars(record).items() if k not in STANDARD_LOG_RECORD_ATTRS}
    parts = [record.getMessage(), repr(record.args), repr(extras)]
    if record.exc_info:
        parts.append(logging.Formatter().formatException(record.exc_info))
    if record.exc_text:
        parts.append(record.exc_text)
    return "\n".join(parts)
