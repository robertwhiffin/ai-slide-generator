"""Strip the retired prompt-override keys out of every stored ``agent_config`` blob.

``system_prompt`` and ``slide_editing_instructions`` are retired: prompts are
assembled from :mod:`src.core.prompt_modules`, and a per-profile override no longer
takes effect. The physical columns go in
``src.core.database._migrate_drop_config_prompt_columns``; the SAME two keys are also
stored inside the ``agent_config`` JSON blob on both ``config_profiles`` and
``user_sessions``, and dropping columns does not touch those. This module removes
them from the blobs.

Lives under ``src/`` rather than ``scripts/`` because the app calls
:func:`strip_retired_prompt_keys` from ``init_database`` in
``packages/databricks-tellr-app/databricks_tellr_app/run.py``, pre-fork before the
uvicorn workers start, and the Databricks Apps wheel ships only ``src/`` (see
``packages/databricks-tellr-app/setup.py``, which copytrees ``src`` and the
frontend/sidecars but NOT ``scripts``). A startup step written as
``from scripts.… import …`` raises ``ModuleNotFoundError`` at boot in production
while working perfectly locally. Any operator CLI imports FROM here, so there is
exactly ONE implementation.

SURGICAL BY DESIGN, for the same reason ``NormalizedAgentConfig`` refuses to
generalise: it deletes two keys and passes every other key and value through
untouched. It deliberately does NOT round-trip the blob through ``AgentConfig`` —
that model ignores unknown keys (so a value a newer writer stored would be silently
destroyed) and fills in every default (so a lean ``{"tools": []}`` would INFLATE
into the full field set). Re-serialization is done by the column's own JSON
serializer, so incidental encoding (key separators, non-ASCII escaping) is whatever
that serializer emits; every key and value is preserved exactly.

Idempotent: a second run finds no blob carrying either key and returns 0.

THE READ IS RAW SQL, AND THAT IS LOAD-BEARING. ``agent_config`` is a
``NormalizedAgentConfig`` column whose ``impl`` is ``sqlalchemy.JSON``, so reading it
through the ORM attribute decodes the JSON *in the result processor, during the
query* — a genuinely unparseable blob (only reachable if it was written by raw SQL,
which bypasses every Python-side hook) raises ``json.JSONDecodeError`` BEFORE any
``try`` in this module could see it, and one bad row would abort the whole startup
step. Reading the column as TEXT and calling :func:`json.loads` here is what makes
"a blob that will not parse is logged and skipped, never raised" actually true.
Measured, ws4b corrections §12.

Three blob shapes therefore have to be handled:

* a JSON **object** — the keys are removed;
* JSON that parses but is **not an object** (a scalar, an array) — not a config;
  skipped and logged. This shape is reachable through the ORM without any raise;
* text that **does not parse at all** — skipped and logged.

A failed WRITE is not swallowed: the caller in ``run.py`` turns it into
``SystemExit(1)``, which is the right outcome for a blob we could read, decide to
edit, and then fail to store.

Exercised against SQLite (the unit tests) and against local PostgreSQL 14.20 on a
throwaway database, where ``agent_config`` is a real ``json`` column: the
``CAST(agent_config AS TEXT)`` read works there, the strip reported 1 then 0, and a
lean blob came back byte-identical. The third shape — text that will not parse — is
unreachable on PostgreSQL, which rejects it at the column
(``psycopg2.errors.InvalidTextRepresentation``); it is reachable on SQLite, whose
JSON column is plain TEXT. NOT verified against Lakebase.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional, Tuple

from sqlalchemy import text, update

logger = logging.getLogger(__name__)

#: The two keys removed from every ``agent_config`` blob. Mirrors
#: ``src.core.database._RETIRED_CONFIG_PROMPT_COLUMNS`` — the same two names, in the
#: blob instead of in the schema.
RETIRED_BLOB_KEYS: Tuple[str, ...] = ("system_prompt", "slide_editing_instructions")


def _qualified(table) -> str:
    """Quote *table*'s name, schema-qualified only when the table carries a schema.

    ``init_db()`` stamps ``LAKEBASE_SCHEMA`` onto every ORM table before this module
    runs (it is the first step of ``init_database``, this is the last), so on Lakebase
    the raw SQL below is schema-qualified exactly like ``database.py``'s ``_qual()``
    helper, while on SQLite unit tests and schema-less local PostgreSQL the name stays
    bare. If the schema were somehow unset on Lakebase the bare name would still
    resolve, because ``_get_database_url`` appends
    ``options=-csearch_path%3D<schema>`` to the connection URL (see the NOTE in
    ``src/core/encryption.py``).
    """
    if table.schema:
        return f'"{table.schema}"."{table.name}"'
    return f'"{table.name}"'


def _strip_blob(raw: Any) -> Optional[dict]:
    """Return the blob minus the retired keys, or ``None`` if there is nothing to do.

    ``None`` means "leave this row alone" — it already carries neither key, or it is
    not a JSON object at all. Everything other than the two keys is copied through.
    """
    if raw is None:
        return None

    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")

    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError) as exc:
            # Only reachable for a blob written by raw SQL; see the module docstring.
            logger.warning(
                "agent_config blob will not parse as JSON (%s); skipping this row "
                "rather than aborting startup",
                exc,
            )
            return None
    else:
        # Some drivers hand back an already-decoded value for a JSON column even from
        # raw SQL (psycopg2 registers a json typecaster). CAST(... AS TEXT) in the
        # SELECT below is what normally prevents this; accept the decoded form too.
        parsed = raw

    if parsed is None:
        # A stored JSON ``null`` document, which reads as empty but is not SQL NULL
        # (see NormalizedAgentConfig's none_as_null note). Nothing to strip.
        logger.debug("agent_config is a JSON null document; nothing to strip")
        return None

    if not isinstance(parsed, dict):
        logger.warning(
            "agent_config blob is a %s, not a JSON object; skipping this row",
            type(parsed).__name__,
        )
        return None

    if not any(key in parsed for key in RETIRED_BLOB_KEYS):
        return None

    cleaned = {k: v for k, v in parsed.items() if k not in RETIRED_BLOB_KEYS}
    return cleaned


def _strip_table(db, model) -> int:
    """Strip the retired keys from one table's ``agent_config`` blobs. Returns rows changed."""
    table = model.__table__
    qualified = _qualified(table)

    # RAW SQL read, cast to TEXT: the decode must happen in _strip_blob, not in the
    # column's result processor. CAST(x AS TEXT) is valid on both SQLite and
    # PostgreSQL. The IS NOT NULL filter skips rows with no config at all.
    rows = db.execute(
        text(
            f"SELECT id, CAST(agent_config AS TEXT) AS agent_config_text "
            f"FROM {qualified} WHERE agent_config IS NOT NULL"
        )
    ).fetchall()

    changed = 0
    for row_id, raw in rows:
        cleaned = _strip_blob(raw)
        if cleaned is None:
            continue
        db.execute(
            update(table).where(table.c.id == row_id).values(agent_config=cleaned)
        )
        changed += 1

    if changed:
        logger.info(
            "Stripped retired prompt keys from %d %s row(s)", changed, table.name
        )
    return changed


def strip_retired_prompt_keys(session_factory) -> int:
    """Remove the retired prompt keys from every stored ``agent_config``. Returns rows changed.

    Called from ``init_database`` in
    ``packages/databricks-tellr-app/databricks_tellr_app/run.py`` as the LAST startup
    step — after ``seed_defaults()`` and ``ensure_encryption_key()`` — because that is
    the one position no later step can undo by writing a fresh blob. (The physical
    ``DROP COLUMN`` is a different step with the opposite constraint: it must run
    early, inside ``_run_migrations``, before anything creates a profile.)

    Args:
        session_factory: A sessionmaker, e.g. ``get_session_local()``. Matches the
            house shape of the other startup steps.

    Returns:
        Total rows changed across ``config_profiles`` and ``user_sessions``. 0 on
        every run after the first.
    """
    from src.database.models.profile import ConfigProfile
    from src.database.models.session import UserSession

    db = session_factory()
    try:
        changed = 0
        for model in (ConfigProfile, UserSession):
            changed += _strip_table(db, model)
        if changed:
            db.commit()
        else:
            db.rollback()
        return changed
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
