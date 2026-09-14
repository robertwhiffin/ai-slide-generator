"""Deck-level-only writer — the graph's two-pass deck write.

Public API
----------
:func:`write_deck_level_columns`  ``(session_id, *, <eight keyword columns>,
                                     modified_by=None, expected_version=None) -> dict``
:func:`read_deck_spec`            ``(session_id) -> dict | None``

Why this module exists rather than a call to ``SessionManager.save_slide_deck``
------------------------------------------------------------------------------
The LangGraph deck build writes deck-level state TWICE per turn: once BEFORE the
per-slide builders fan out (so an incrementally-released slide renders styled and
the committed spec is durable), and once AFTER their rows are committed (so the
aggregate columns reflect what was actually built).  ``save_slide_deck`` has
exactly two behaviours and neither is a deck-level-only write [measured against
``src/api/services/session_manager.py`` this session]:

* ``deck_dict=None`` -> ``deck_json = json.dumps(deck_dict) if deck_dict else None``
  (``session_manager.py:1310``) is then assigned at ``:1327``, so the call **nulls
  ``deck_json``**.  Note: there is no literal ``deck.deck_json = None`` anywhere in
  that file — the hazard is reached by that computed assignment, and an implementer
  who greps for the literal and finds nothing must not conclude it is imaginary
  (``.ws4b-PLAN-CORRECTIONS.md`` §5/A1).
* ``deck_dict={...}`` -> it upserts every slide in ``deck_dict["slides"]`` and then
  calls ``_prune_slide_rows_beyond(db, deck_owner.id, len(slides))``
  (``session_manager.py:1410``), **hard-deleting every row at
  ``position >= len(slides)``**.  A pre-fan-out call carries a shorter slide list
  than the live row count, so it would truncate the live deck mid-turn.

It also takes ``html_content`` as a **required positional**, and the graph has not
knitted any HTML at fan-out time.

This writer therefore reuses ``save_slide_deck``'s *locking shape* (the
``expected_version`` check at ``session_manager.py:1317-1321`` and the
``deck.version += 1`` bump just below) and its *no-row create* branch, but touches
**no ``session_slides`` row and never assigns ``deck_json``**.

The sentinel, and why it is not ``None``
----------------------------------------
Two writes happen per turn, so the second must not erase what the first persisted.
``_UNSET`` means "not supplied — leave the stored value alone"; an explicit ``None``
means "write SQL NULL".  Those are different operations and a ``None`` default
cannot express both.  Every one of the eight column parameters defaults to
``_UNSET``.

Which column belongs to which write (nothing self-heals)
--------------------------------------------------------
=========================  ============  ==================================================
Column                     Write         Cost of never writing it
=========================  ============  ==================================================
``title``                  pre-fan-out   untitled deck AND untitled session row
``css``                    both          unstyled deck (``knit()`` guards ``if self.css:``)
``external_scripts_json``  pre-fan-out   Chart.js missing from every export — SILENT
``head_meta_json``         pre-fan-out   custom viewport reverts to ``knit()``'s default
``deck_spec_json``         pre-fan-out   spec never persisted; next turn's architect is blind
``slide_count``            post-commit   session list renders ``0 slides`` (a column, not derived)
``html_content``           post-commit   raw-HTML debug view empty
``scripts_content``        post-commit   thumbnails/PDF/PPTX render with no JS — SILENT
=========================  ============  ==================================================

``scripts_content`` is a denormalised cache of the per-slide aggregate
(``SlideDeck.scripts``), which is why it belongs to the post-commit write: at
fan-out time there are no slides to aggregate.

All eight columns already exist on ``session_slide_decks``, ``version`` included
(``src/database/models/session.py`` ``class SessionSlideDeck``;
``.ws4b-PLAN-CORRECTIONS.md`` §3/S1).  **This module adds no migration and no column.**

Two deliberate divergences from ``save_slide_deck``, recorded so neither reads as
an oversight
-------------------------------------------------------------------------------
1. **No permission check.**  ``save_slide_deck`` calls neither
   ``_require_deck_permission`` nor ``require_editing_lock``; this writer matches it.
   Authorisation belongs to the route that started the graph run.
2. **No ``deck_created`` usage event.**  ``save_slide_deck``'s create branch emits
   ``record_deck_created`` (``session_manager.py``, inside its ``else: # Create new``).
   This writer does not.  UNVERIFIED whether the graph path needs that metric — it
   was left out because the event writes through its own unpatched
   ``get_db_session``, and it is flagged for ws4c rather than guessed at here.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from src.api.services.session_manager import (
    VersionConflictError,
    get_session_manager,
)
from src.core.database import get_db_session
from src.database.models.session import SessionSlideDeck

logger = logging.getLogger(__name__)


class _Unset:
    """Type of the module's "argument not supplied" sentinel.

    Deliberately does NOT define ``__bool__``: a falsy sentinel would let
    ``if title:`` silently treat "not supplied" as "empty value".  Left truthy so
    that mistakenly using the sentinel as a value fails loudly (e.g. in
    ``json.dumps``) instead of quietly writing the wrong thing.
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<UNSET>"


_UNSET = _Unset()

# Parameter name -> column name, for the three columns whose value is serialised.
_JSON_COLUMNS = {
    "external_scripts": "external_scripts_json",
    "head_meta": "head_meta_json",
    "deck_spec": "deck_spec_json",
}

# Parameter name -> column name, for the five stored verbatim.
_PLAIN_COLUMNS = {
    "title": "title",
    "css": "css",
    "slide_count": "slide_count",
    "html_content": "html_content",
    "scripts_content": "scripts_content",
}


def _encode_json(value: Any) -> Optional[str]:
    """Serialise a supplied JSON-column value.

    ``None`` -> ``None`` (SQL NULL — an explicit null, distinct from ``_UNSET``).
    ``str``  -> stored verbatim, so a caller holding ``model_dump_json()`` output
                does not get it double-encoded.
    anything else -> ``json.dumps(value)``.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value)


def write_deck_level_columns(
    session_id: str,
    *,
    title: Any = _UNSET,
    css: Any = _UNSET,
    external_scripts: Any = _UNSET,
    head_meta: Any = _UNSET,
    scripts_content: Any = _UNSET,
    deck_spec: Any = _UNSET,
    slide_count: Any = _UNSET,
    html_content: Any = _UNSET,
    modified_by: Optional[str] = None,
    expected_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Write only deck-level columns on a session's slide deck.

    Touches no ``session_slides`` row and never assigns ``deck_json``.  Creates the
    ``SessionSlideDeck`` row when none exists — the pre-fan-out write is the FIRST
    deck write of a brand-new session, so without that branch every graph turn on a
    new session would raise.

    Every column argument defaults to ``_UNSET``.  Omit one and the stored value is
    left untouched; pass ``None`` and SQL NULL is written.  ``external_scripts``,
    ``head_meta`` and ``deck_spec`` are serialised into their ``*_json`` columns; the
    other five are stored verbatim.

    ``title`` is written to the deck row AND to the deck owner's ``UserSession.title``
    (the session list reads the session row).

    Args:
        session_id: Requesting session's string id.  A contributor session resolves
            through ``SessionManager._get_deck_owner_session`` to the owner's deck.
        title, css, external_scripts, head_meta, scripts_content, deck_spec,
            slide_count, html_content: the eight deck-level columns.
        modified_by: Stamped on ``deck.modified_by`` when truthy.
        expected_version: Optimistic lock.  When given and the stored ``version``
            differs, raises ``VersionConflictError`` and writes nothing.  As in
            ``save_slide_deck``, the check applies only to an EXISTING row: a row
            that does not yet exist has no version to be stale against, and is
            created at ``version=1``.

    Returns:
        dict with ``session_id``, ``deck_owner_session_id``, ``title``,
        ``slide_count``, ``version``, ``updated_at``, ``created`` and
        ``columns_written``.

    Raises:
        SessionNotFoundError: session_id does not exist (or a contributor's parent
            is missing) — both from the reused ``SessionManager`` helpers.
        VersionConflictError: ``expected_version`` does not match an existing row.
    """
    supplied: Dict[str, Any] = {
        key: value
        for key, value in (
            ("title", title),
            ("css", css),
            ("external_scripts", external_scripts),
            ("head_meta", head_meta),
            ("scripts_content", scripts_content),
            ("deck_spec", deck_spec),
            ("slide_count", slide_count),
            ("html_content", html_content),
        )
        if value is not _UNSET
    }

    with get_db_session() as db:
        manager = get_session_manager()
        # Reuse, do not reimplement: _get_deck_owner_session takes a UserSession
        # OBJECT and a db (session_manager.py:709, ~20 call sites), so the string
        # session_id must be looked up first.
        session = manager._get_session_or_raise(db, session_id)
        deck_owner = manager._get_deck_owner_session(db, session)

        deck = deck_owner.slide_deck
        created = deck is None

        if created:
            # Mirrors save_slide_deck's `else: # Create new` branch: version starts
            # at 1, and the two columns whose NULL would be read as data get the
            # same defaults that branch uses.
            deck = SessionSlideDeck(
                session_id=deck_owner.id,
                html_content="",
                scripts_content=None,
                slide_count=0,
                version=1,
            )
            db.add(deck)
            db.flush()
        else:
            # Locking shape copied from session_manager.py:1317-1321.
            if expected_version is not None and deck.version != expected_version:
                raise VersionConflictError(
                    current_version=deck.version,
                    expected_version=expected_version,
                )

        for key, value in supplied.items():
            if key in _JSON_COLUMNS:
                setattr(deck, _JSON_COLUMNS[key], _encode_json(value))
            else:
                setattr(deck, _PLAIN_COLUMNS[key], value)

        if not created:
            # Exactly one bump per accepted call (session_manager.py:1328).
            deck.version += 1

        if modified_by:
            deck.modified_by = modified_by

        if "title" in supplied:
            # The session list renders UserSession.title, not the deck's, so a
            # deck-only title write leaves an untitled session row behind.
            deck_owner.title = supplied["title"]

        now = datetime.utcnow()
        deck_owner.last_activity = now
        if session.id != deck_owner.id:
            session.last_activity = now

        db.flush()

        logger.info(
            "Wrote deck-level columns",
            extra={
                "session_id": session_id,
                "deck_owner_session_id": deck_owner.session_id,
                "columns": sorted(supplied),
                # NOT "created": that is a reserved LogRecord attribute and
                # logging raises KeyError when extra= tries to overwrite one.
                "row_created": created,
                "version": deck.version,
            },
        )

        return {
            "session_id": session_id,
            "deck_owner_session_id": deck_owner.session_id,
            "title": deck.title,
            "slide_count": deck.slide_count,
            "version": deck.version,
            "updated_at": deck.updated_at.isoformat() if deck.updated_at else None,
            "created": created,
            "columns_written": sorted(supplied),
        }


def read_deck_spec(session_id: str) -> Optional[Dict[str, Any]]:
    """Return the deck's persisted spec as a dict, or ``None``.

    ``None`` for: no deck row yet, a NULL/empty ``deck_spec_json``, a column that
    does not parse as JSON, and a column that parses to something other than an
    object.  A malformed column is a logged warning, not an exception: the caller
    (the architect node) treats "no readable spec" the same way it treats "no spec",
    and raising would abort a turn that can still proceed by re-authoring.

    Raises:
        SessionNotFoundError: session_id does not exist.
    """
    with get_db_session() as db:
        manager = get_session_manager()
        session = manager._get_session_or_raise(db, session_id)
        deck_owner = manager._get_deck_owner_session(db, session)

        deck = deck_owner.slide_deck
        if deck is None or not deck.deck_spec_json:
            return None

        raw = deck.deck_spec_json
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            logger.warning(
                "deck_spec_json does not parse as JSON; treating as absent",
                extra={"session_id": session_id},
            )
            return None

        if not isinstance(parsed, dict):
            logger.warning(
                "deck_spec_json parsed to %s, not an object; treating as absent",
                type(parsed).__name__,
                extra={"session_id": session_id},
            )
            return None

        return parsed
