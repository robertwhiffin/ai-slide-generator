"""The spec-dirty marker — "a human changed this deck, re-describe its narrative".

The graph commits a ``DeckSpec`` describing a deck's narrative.  A human editing a
slide by hand in the WYSIWYG editor makes that description stale.  This module
records that staleness so a later sweeper can re-run the arc review.

Public API
----------
:data:`DEBOUNCE_SECONDS`  how long a marker waits before the sweeper may claim it
:func:`mark_dirty`        ``(session_id, author) -> bool`` — set/refresh the marker
:func:`clear_marker`      ``(session_id) -> bool`` — the review is done; dequeue

The placement rule IS the design
--------------------------------
``mark_dirty`` is called from the route handlers in ``src/api/routes/slides.py``
and **from nowhere else**.  The LangGraph deck build calls the *service* methods
(``chat_service``, ``slide_repository``, ``deck_level_writer``) directly and never
issues an HTTP request, so "arrived via the route" *means* "a human did this" — by
construction, not by convention.

That is why there is no ``origin='human'|'agent'`` parameter (a caller who forgets
it silently schedules an LLM re-description of the agent's own work) and no
ContextVar (invisible coupling; a missed reset leaks origin into the next request).
The failure mode here requires someone to actively wire a **new** route call, not
merely to forget an argument — and
``tests/unit/test_spec_sync_placement.py`` fails if any other module under ``src/``
so much as imports the name.

Marker semantics
----------------
Setting is **idempotent within a window**: an existing *unclaimed* marker keeps its
**original** ``spec_dirty_at``, so a burst of WYSIWYG edits coalesces into one
review instead of pushing the window out forever.  The **author is refreshed** on
every set — the most recent human editor is the right attribution, and the review
has not run yet.

A marker that has already been **claimed** by a sweeper starts a *new* window
(``spec_dirty_at = now``) because the in-flight review cannot cover an edit made
after it began.  The claim itself (``spec_dirty_claimed_at``) is deliberately left
alone: clearing another worker's lease would let a second worker review the same
deck concurrently.  :func:`clear_marker` is the half that closes this loop — see
its docstring for the re-dirty rule that keeps the new window from being wiped by
the finishing review.

Owner-deck resolution — the shape that raises ``TypeError`` if you get it wrong
------------------------------------------------------------------------------
Decks are shared across sessions via ``UserSession.parent_session_id``, and a
contributor session's own ``UserSession.slide_deck`` is ``None``.  The routes pass
``request.session_id`` straight through, so this module **will** receive
contributor ids.  ``SessionManager._get_deck_owner_session`` is an **instance
method taking a live SQLAlchemy ``Session`` and a ``UserSession`` OBJECT**
(``session_manager.py:828``, ~20 call sites) — never a session_id string.  So both
functions here open a session, look the ``UserSession`` up from its string id, and
pass the object.  The pattern is ws4b's ``deck_level_writer.read_deck_spec``
(``deck_level_writer.py:293``), reused rather than reinvented.

The marker therefore lives on the **owner's** deck row, and both functions key on
the same owner-resolved row.  ``claim_due_marker`` returns the owner's string id,
so a marker set by a contributor is cleared by the sweeper's clear on the owner —
if the two keyed differently, markers would never clear and the deck would be
re-claimed forever.

Why the version counter is NOT bumped
-------------------------------------
``session_slide_decks.version`` is the client's optimistic lock.  The human whose
edit set this marker is holding the version their edit produced; a marker write
that bumped it again would 409 their very next save.  The marker is internal sweep
scheduling, not deck state (see the column comments in
``src/database/models/session.py``), so neither function touches ``version``,
``modified_by``, ``updated_at`` or ``last_activity``.

Why ``mark_dirty`` swallows and ``clear_marker`` raises
-------------------------------------------------------
``mark_dirty`` sits on a human's request path **after their edit has already
committed**.  Letting it raise would turn a successful edit into an HTTP 500 (the
route's ``except Exception`` handler is right there), telling the user their work
was lost when it was not, and inviting a retry.  A lost marker costs one skipped
re-description; a lost edit costs the user's work.  So it logs and returns
``False``.

``clear_marker`` runs on the sweeper's own background tick where there is no user
to mislead and swallowing would hide a stuck queue, so it raises.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional, Tuple

from src.api.services.session_manager import get_session_manager
from src.core.database import get_db_session
from src.database.models.session import SessionSlideDeck

logger = logging.getLogger(__name__)

# How long a marker rests before the sweeper may claim it, so that a burst of
# WYSIWYG edits becomes one arc review rather than one per keystroke-batch.
# Read by Task 5's claim_due_marker; defined here because it is a property of the
# marker, not of the loop that drains it.
DEBOUNCE_SECONDS = 180


def _resolve_owner_deck(
    db, session_id: str
) -> Tuple[object, Optional[SessionSlideDeck]]:
    """Return ``(deck_owner_session, deck_or_None)`` for a session's string id.

    Reuses ``SessionManager``'s two helpers rather than reimplementing the FK
    walk: ``session_slide_decks.session_id`` is the INTEGER FK to
    ``user_sessions.id`` while the string id is ``user_sessions.session_id``, and
    a contributor session reaches its deck only through ``parent_session_id``.

    Raises:
        SessionNotFoundError: session_id does not exist (or a contributor's
            parent is missing) — propagated from the reused helpers.
    """
    manager = get_session_manager()
    session = manager._get_session_or_raise(db, session_id)
    deck_owner = manager._get_deck_owner_session(db, session)
    return deck_owner, deck_owner.slide_deck


def mark_dirty(session_id: str, author: Optional[str]) -> bool:
    """Record that a human's out-of-graph edit made the committed spec stale.

    Call this from a route handler in ``src/api/routes/slides.py`` and nowhere
    else (see the module docstring — the placement rule is the design).

    Args:
        session_id: The requesting session's string id.  May be a **contributor**
            id; it is resolved to the owner's deck.
        author: The human whose edit triggered the mark, normally
            ``get_current_user()``.  Required positionally so a new call site
            cannot silently omit attribution.  ``None`` is accepted and stored as
            SQL NULL (an unauthenticated local dev request).

    Returns:
        ``True`` when a marker is set or refreshed; ``False`` when there was
        nothing to mark (no deck row yet) or the write failed.  Never raises —
        the caller's edit has already committed.
    """
    try:
        with get_db_session() as db:
            deck_owner, deck = _resolve_owner_deck(db, session_id)

            if deck is None:
                # No deck row means no committed spec to invalidate.  Marking is
                # meaningless and creating a row here would fabricate a deck.
                logger.info(
                    "spec_sync.mark_dirty: no deck row; nothing to mark",
                    extra={"session_id": session_id},
                )
                return False

            coalesced = (
                deck.spec_dirty_at is not None
                and deck.spec_dirty_claimed_at is None
            )
            if not coalesced:
                # No marker, or one already claimed by a sweeper whose in-flight
                # review cannot cover this edit: open a new window.
                deck.spec_dirty_at = datetime.utcnow()

            # Refreshed on every set, coalesced or not: the most recent human
            # editor is the right attribution and the review has not run yet.
            deck.spec_dirty_by = author

            db.flush()

            logger.info(
                "spec_sync.mark_dirty: marker set",
                extra={
                    "session_id": session_id,
                    "deck_owner_session_id": deck_owner.session_id,
                    "author": author,
                    "coalesced": coalesced,
                    "spec_dirty_at": deck.spec_dirty_at.isoformat(),
                },
            )
            return True
    except Exception:
        # The human's edit already committed.  Never turn a lost marker into a
        # lost edit — see the module docstring.
        logger.exception(
            "spec_sync.mark_dirty failed; the deck's spec stays stale",
            extra={"session_id": session_id},
        )
        return False


def clear_marker(session_id: str) -> bool:
    """Clear the marker after the arc review for it has finished.

    Keys on the **same owner-resolved deck row** as :func:`mark_dirty`, which is
    the row whose owner string id ``claim_due_marker`` returns.

    The re-dirty rule: if the deck was marked *again* after the sweeper took its
    claim (``spec_dirty_at > spec_dirty_claimed_at``), that later human edit is
    NOT covered by the review now finishing.  Clearing all three columns would
    discard it silently, so instead only the lease is released and the newer
    marker survives to be claimed on a subsequent tick.

    Args:
        session_id: Any session id sharing the deck — owner or contributor.

    Returns:
        ``True`` when the marker was cleared; ``False`` when there was nothing to
        clear (no deck row, or no marker) or when a newer marker was deliberately
        preserved by the re-dirty rule.

    Raises:
        SessionNotFoundError: session_id does not exist.  Unlike
            :func:`mark_dirty` this does not swallow — it runs on a background
            tick where a swallowed failure would hide a stuck queue.
    """
    with get_db_session() as db:
        deck_owner, deck = _resolve_owner_deck(db, session_id)

        if deck is None:
            logger.info(
                "spec_sync.clear_marker: no deck row; nothing to clear",
                extra={"session_id": session_id},
            )
            return False

        if deck.spec_dirty_at is None and deck.spec_dirty_claimed_at is None:
            return False

        re_dirtied = (
            deck.spec_dirty_claimed_at is not None
            and deck.spec_dirty_at is not None
            and deck.spec_dirty_at > deck.spec_dirty_claimed_at
        )
        if re_dirtied:
            # Release the lease only; keep the newer marker for the next tick.
            deck.spec_dirty_claimed_at = None
            db.flush()
            logger.info(
                "spec_sync.clear_marker: re-dirtied after the claim; "
                "marker kept, lease released",
                extra={
                    "session_id": session_id,
                    "deck_owner_session_id": deck_owner.session_id,
                },
            )
            return False

        deck.spec_dirty_at = None
        deck.spec_dirty_by = None
        deck.spec_dirty_claimed_at = None
        db.flush()

        logger.info(
            "spec_sync.clear_marker: marker cleared",
            extra={
                "session_id": session_id,
                "deck_owner_session_id": deck_owner.session_id,
            },
        )
        return True
