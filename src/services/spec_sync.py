"""The spec-dirty marker — "a human changed this deck, re-describe its narrative".

The graph commits a ``DeckSpec`` describing a deck's narrative.  A human editing a
slide by hand in the WYSIWYG editor makes that description stale.  This module
records that staleness so a later sweeper can re-run the arc review.

Public API
----------
:data:`DEBOUNCE_SECONDS`  how long a marker waits before the sweeper may claim it
:func:`mark_dirty`        ``(session_id, author) -> bool`` — set/refresh the marker
:func:`clear_marker`      ``(session_id) -> bool`` — the review is done; dequeue

and the sweeper that drains the queue those three define:

:data:`SWEEP_INTERVAL_SECONDS`   how often the loop wakes
:data:`CLAIM_TTL_SECONDS`        how long a worker's lease is honoured
:func:`claim_due_marker`         ``(now) -> (owner_session_id, author) | None``
:func:`run_arc_review`           ``(session_id, author) -> bool`` — never raises
:func:`sweep_once`               one tick: claim at most one marker and review it
:func:`spec_review_sweeper_loop` the periodic loop, started in the FastAPI lifespan

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
``src/database/models/session.py``), so no marker write here touches ``version``,
``modified_by`` or ``last_activity``.

:func:`run_arc_review` is the exception worth stating, because it is in this
module and it does reach all three — not itself, but through the graph turn it
invokes, whose ``architect_node`` calls ``write_deck_level_columns``.  That write
is made with ``user_visible=False`` on a describe-only turn, which is what keeps
the ``version`` bump, the ``updated_at`` touch and the ``last_activity`` touch
from firing.  Without it a sweeper review 409s the editing human's next save and
re-sorts their session list.

``updated_at`` needs one caveat, measured rather than assumed.  It carries
``Column(onupdate=datetime.utcnow)`` and is surfaced to the client as the deck's
``modified_at``, and SQLAlchemy fires that ``onupdate`` on **any** UPDATE of the
row — an ORM attribute assignment plus ``flush`` included.  So ``mark_dirty`` and
``clear_marker`` do in fact bump it.  The rule, applied deliberately: **a human action bumps
the deck's ``modified_at``; a sweeper action does not.**  So ``mark_dirty``
keeps its bump — a human really did just edit the deck — while
:func:`claim_due_marker`, :func:`_release_claim` and :func:`clear_marker` write
through :func:`_marker_write`, which names ``updated_at`` as itself and so
suppresses the ``onupdate``.  A no-net-change ORM assignment does NOT suppress
it: an attribute with no net change never reaches the SET clause.  Without this,
a sweeper finishing a review it alone scheduled shows every client that the deck
was modified just now.

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

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple

from sqlalchemy import or_, select, update

from src.api.services.session_manager import get_session_manager
from src.core.database import get_db_session
from src.core.user_context import get_current_user, set_current_user
from src.database.models.session import SessionSlideDeck, UserSession

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
            _marker_write(db, deck.id, spec_dirty_claimed_at=None)
            logger.info(
                "spec_sync.clear_marker: re-dirtied after the claim; "
                "marker kept, lease released",
                extra={
                    "session_id": session_id,
                    "deck_owner_session_id": deck_owner.session_id,
                },
            )
            return False

        _marker_write(
            db,
            deck.id,
            spec_dirty_at=None,
            spec_dirty_by=None,
            spec_dirty_claimed_at=None,
        )

        logger.info(
            "spec_sync.clear_marker: marker cleared",
            extra={
                "session_id": session_id,
                "deck_owner_session_id": deck_owner.session_id,
            },
        )
        return True


# ---------------------------------------------------------------------------
# The sweeper: claim a due marker, re-describe the arc, clear the marker.
# ---------------------------------------------------------------------------
#
# The queue this drains is a DB column, not ``enqueue_job``.
# ``src/api/services/job_queue.py`` is an in-process ``asyncio.Queue`` drained
# FIFO with no delay or at-time primitive, so a 180 s coalescing window has
# nothing to hang off.  What IS reusable is its *shape*:
# ``mark_timed_out_jobs_once`` + ``mark_timed_out_jobs_loop`` with a 60 s
# interval — a periodic loop that reads DB state and acts on whatever is due.
# ``sweep_once``/``spec_review_sweeper_loop`` below are that pair.

# How often the loop wakes.  60 s, matching TIMEOUT_SWEEP_INTERVAL_SECONDS: the
# debounce window is 180 s, so a tick every minute adds at most a third of a
# window to a marker's wait.
SWEEP_INTERVAL_SECONDS = 60

# How long a claim is honoured before another worker may take the deck.  A
# worker that dies mid-review (deploy, OOM, crash) leaves its lease behind; a
# bare ``spec_dirty_claimed_at IS NULL`` predicate would then wedge that deck
# permanently.  900 s is comfortably longer than an arc review and short enough
# that a wedged deck recovers within a quarter of an hour without a human.
CLAIM_TTL_SECONDS = 900

# What the sweeper asks the architect for.  The turn exists to make the
# committed spec describe the deck as a human left it, NOT to rebuild it.
ARC_REVIEW_MESSAGE = (
    "A person edited this deck by hand, outside the build, so the committed "
    "deck specification no longer describes what the deck actually says. "
    "Re-read the slides as they now stand and re-describe the deck's narrative "
    "arc so the specification matches them again. Describe what is there — do "
    "not rewrite, add, remove or reorder slides."
)


def claim_due_marker(now: datetime) -> Optional[Tuple[str, str]]:
    """Atomically take one due marker, or return ``None``.

    Returns ``(owner_session_id, author)`` where ``owner_session_id`` is the
    **string** id of the session that OWNS the deck — the id
    :func:`clear_marker` keys on — and ``author`` is the marker's recorded
    ``spec_dirty_by``.

    Why the claim is required and not defensive
    ------------------------------------------
    ``UVICORN_WORKERS`` defaults to **4** (``run.py``), and the loop below runs
    in every worker.  Four loops reading the same due marker with no lease means
    one WYSIWYG session pays for up to four identical LLM arc reviews per
    window — precisely the cost :data:`DEBOUNCE_SECONDS` exists to avoid.  The
    exclusivity comes from a **conditional UPDATE**: the ``unclaimed`` predicate
    appears both in the candidate subquery AND in the UPDATE's own WHERE, so a
    second worker that blocks on the row lock re-evaluates it against the
    committed row and matches nothing.  Dropping the outer copy makes the
    statement "claim whatever the subquery saw", which is a read-then-write race.

    Why it returns the string id and not what ``RETURNING`` hands back
    -----------------------------------------------------------------
    ``session_slide_decks.session_id`` is the INTEGER FK to ``user_sessions.id``;
    the string id lives on ``user_sessions.session_id``.  So ``RETURNING
    session_id`` yields an **int**, while :func:`clear_marker` (and
    ``read_deck_spec``, and every ``SessionManager`` helper) filters on the
    string.  Returning the int matches no row on the clear, the marker is never
    cleared, and the deck is re-claimed every :data:`CLAIM_TTL_SECONDS`
    **forever** — invisibly, because nothing raises.  Hence the second SELECT
    that maps the FK before returning.

    Three conditions gate a claim:

    * ``spec_dirty_at`` is set and at least :data:`DEBOUNCE_SECONDS` old — a
      burst of edits coalesces into one review.
    * ``spec_dirty_by`` is NOT NULL.  **A marker with no author is not
      claimed**: with no identity there is no attribution for the write, no cost
      attribution, and no permission provenance, and inventing a system identity
      was the rejected alternative.  Such a marker rests until a later
      authenticated edit refreshes its author.
    * the deck is unclaimed, or its claim is older than
      :data:`CLAIM_TTL_SECONDS`.

    Args:
        now: The instant to measure both windows against.  Passed in rather than
            read from the clock so a test can place a marker either side of a
            boundary without sleeping.

    Returns:
        ``(owner_session_id, author)``, or ``None`` when nothing is due, nothing
        is claimable, or the claimed row's owner session has vanished.
    """
    due_before = now - timedelta(seconds=DEBOUNCE_SECONDS)
    stale_before = now - timedelta(seconds=CLAIM_TTL_SECONDS)

    deck_table = SessionSlideDeck.__table__
    # The lease test, used TWICE on purpose — see the docstring.
    unclaimed = or_(
        deck_table.c.spec_dirty_claimed_at.is_(None),
        deck_table.c.spec_dirty_claimed_at <= stale_before,
    )

    candidate = (
        select(deck_table.c.id)
        .where(
            deck_table.c.spec_dirty_at.isnot(None),
            deck_table.c.spec_dirty_at <= due_before,
            deck_table.c.spec_dirty_by.isnot(None),
            unclaimed,
        )
        # Oldest marker first: the deck that has waited longest gets reviewed
        # first, so a busy deck cannot starve a quiet one.
        .order_by(deck_table.c.spec_dirty_at)
        .limit(1)
        .scalar_subquery()
    )

    claim = (
        update(deck_table)
        .where(deck_table.c.id == candidate)
        .where(unclaimed)
        .values(
            spec_dirty_claimed_at=now,
            # A lease is not a deck modification — see _marker_write for the
            # measured rule: a human action bumps the deck's client-visible
            # modified_at, a sweeper action does not.
            updated_at=deck_table.c.updated_at,
        )
        .returning(deck_table.c.session_id, deck_table.c.spec_dirty_by)
    )

    with get_db_session() as db:
        row = db.execute(claim).fetchone()
        if row is None:
            return None

        owner_pk, author = row[0], row[1]

        # The FK -> string mapping. Without it the caller gets an int and every
        # downstream lookup silently matches nothing.
        owner_session_id = db.execute(
            select(UserSession.session_id).where(UserSession.id == owner_pk)
        ).scalar()

        if owner_session_id is None:
            # The deck row outlived its session (the FK is ON DELETE CASCADE, so
            # this should be unreachable). The lease is deliberately LEFT IN
            # PLACE: releasing it would re-claim the orphan every tick, whereas
            # the TTL retries it at most once every CLAIM_TTL_SECONDS.
            logger.error(
                "spec_sync.claim_due_marker: claimed a deck whose owner session "
                "is missing; leaving the lease so the TTL rate-limits the retry",
                extra={"deck_owner_pk": owner_pk},
            )
            return None

        logger.info(
            "spec_sync.claim_due_marker: claimed",
            extra={
                "deck_owner_session_id": owner_session_id,
                "author": author,
                "claimed_at": now.isoformat(),
            },
        )
        return (owner_session_id, author)


def _marker_write(db, deck_id: int, **values) -> None:
    """UPDATE the marker columns on *deck_id* and leave ``updated_at`` alone.

    A Core UPDATE rather than an ORM attribute assignment, and the reason is
    measured rather than stylistic.  ``updated_at`` carries
    ``Column(onupdate=datetime.utcnow)`` and is surfaced to every client as the
    deck's ``modified_at``; SQLAlchemy fires that ``onupdate`` on any UPDATE of
    the row, an ORM flush included, and a no-net-change assignment does NOT
    suppress it because an attribute with no net change never reaches the SET
    clause.  Naming the column explicitly does suppress it, and only a Core
    statement can name it as itself.

    The rule this enforces: **a human action bumps the deck's ``modified_at``; a
    sweeper action does not.**  So :func:`mark_dirty` keeps its bump — a human
    genuinely did edit the deck — while :func:`claim_due_marker`,
    :func:`_release_claim` and :func:`clear_marker` suppress it.  Without this a
    sweeper finishing a review it alone scheduled shows every client that the
    deck was modified just now.
    """
    table = SessionSlideDeck.__table__
    db.execute(
        update(table)
        .where(table.c.id == deck_id)
        .values(updated_at=table.c.updated_at, **values)
    )


def _release_claim(session_id: str) -> bool:
    """Release the lease and KEEP the marker, so the next sweep retries.

    The difference from :func:`clear_marker` is the whole point: this is the
    failure path, and clearing ``spec_dirty_at`` here would drop a review that
    never ran.  Never raises — it is called from an ``except`` block on a
    background tick, where raising would replace the real failure with this one.
    """
    try:
        with get_db_session() as db:
            deck_owner, deck = _resolve_owner_deck(db, session_id)
            if deck is None:
                return False
            _marker_write(db, deck.id, spec_dirty_claimed_at=None)
            logger.info(
                "spec_sync._release_claim: lease released, marker kept for retry",
                extra={"deck_owner_session_id": deck_owner.session_id},
            )
            return True
    except Exception:
        logger.exception(
            "spec_sync._release_claim failed; the lease expires by TTL instead",
            extra={"target_session_id": session_id},
        )
        return False


def run_arc_review(session_id: str, author: str) -> bool:
    """Re-describe the deck's narrative arc as *author*, then clear the marker.

    **Never raises.**  A failure releases the **claim** and keeps the
    **marker**, so the next sweep retries rather than the deck wedging — the
    same fail-open direction as the rest of this PR's identity and mode
    resolution.

    Identity is BOUND, not merely stamped.  Two separate mechanisms, both
    needed:

    * ``principal=author`` is passed to ``invoke_graph``, which resolves
      ``principal or get_current_user()`` once into ``initiated_by``; every node
      reads it from state, and it is what lands in ``modified_by`` on the
      deck-level write.  A sweeper tick has no request, so the second half of
      that ``or`` is ``None`` — this caller is why the argument exists.
    * ``set_current_user(author)`` is bound for the duration, so anything on the
      turn that reads the ContextVar itself (``require_editing_lock`` is the
      motivating example) sees the human, not ``None``.  With ``None`` a deck
      whose editing lock a human currently holds would raise — and that is
      exactly the deck an arc review exists for, so it would degrade safely,
      silently, and forever.

    The ContextVar is **restored** afterwards.  This function runs inside a
    long-lived loop, not a request, so a ``set`` with no restore leaks one
    tick's author into the next tick's — and into anything else sharing that
    context.

    No ``emitter`` is passed: a sweeper tick has no SSE stream, and the graph's
    ``emit_event`` returns ``False`` rather than raising when the emitter is
    ``None``.

    ``describe_only=True`` is passed, and it is the difference between a review
    and a silent overwrite.  :data:`ARC_REVIEW_MESSAGE` asks the architect not to
    rewrite the deck, but intent is model output and asking is not a control: a
    ``build`` or ``edit`` intent routes to the foreman, which dispatches builders
    whose reviewers rewrite slide rows.  The flag makes ``architect_router`` end
    the turn instead.  The architect's own deck-level write still happens, which
    is the point — the re-described spec is persisted and no slide row is
    touched.

    Args:
        session_id: The **owner** session's string id, as
            :func:`claim_due_marker` returns it.
        author: The marker's recorded ``spec_dirty_by``.

    Returns:
        ``True`` when the review ran and the marker was dealt with — cleared,
        or deliberately kept by :func:`clear_marker`'s re-dirty rule.
        ``False`` when the review failed and the marker was left queued.

        **A ``False`` from :func:`clear_marker` is not a failure.**  It means
        "kept, still queued" — the deck was marked again after this claim was
        taken, so the later human edit gets its own review on a later tick.
        Treating it as an error would log a human's mid-review edit as a fault
        and, if that reading ever drove a retry-or-drop decision, lose it.
    """
    # Restore rather than reset-to-None: this is a plain value save/restore, so
    # it is correct whether or not something upstream had bound a user.
    previous_user = get_current_user()
    set_current_user(author)
    try:
        try:
            # Imported INSIDE this try, not above it, and that placement is the
            # whole point. The graph package pulls in the nodes, the skills and
            # the session manager, so this import can genuinely fail — a
            # circular import was hit while probing exactly this. Above the try
            # (whose enclosing block has a `finally` but no `except`) the
            # ImportError propagates out of a function C-6 says never raises:
            # the loop survives and the ContextVar is restored, but
            # `_release_claim` never runs and the deck stays LEASED for the full
            # CLAIM_TTL_SECONDS instead of retrying on the next 60-second tick.
            from src.services.graph.builder import invoke_graph

            invoke_graph(
                session_id,
                {"architect_message": ARC_REVIEW_MESSAGE},
                principal=author,
                # The message ASKS the architect not to rebuild; this ENFORCES
                # it. Intent is model output, so asking is not a control:
                # _INTENT_ROUTES maps both "build" and "edit" to the foreman,
                # and a sweeper turn that reached it would dispatch builders
                # whose reviewers overwrite the hand-edits that scheduled this
                # review — with no emitter, so nobody watching.
                describe_only=True,
            )
        except Exception:
            logger.exception(
                "spec_sync.run_arc_review: the arc review failed; marker kept "
                "for the next sweep",
                extra={"deck_owner_session_id": session_id, "author": author},
            )
            _release_claim(session_id)
            return False

        try:
            cleared = clear_marker(session_id)
        except Exception:
            # clear_marker raises by design (a swallowed failure would hide a
            # stuck queue). Releasing the lease turns a stuck queue into a
            # retried one.
            logger.exception(
                "spec_sync.run_arc_review: the review ran but the marker could "
                "not be cleared; lease released so the next sweep retries",
                extra={"deck_owner_session_id": session_id, "author": author},
            )
            _release_claim(session_id)
            return False

        logger.info(
            "spec_sync.run_arc_review: review complete",
            extra={
                "deck_owner_session_id": session_id,
                "author": author,
                # False here means the deck was re-dirtied during the review and
                # the newer marker was KEPT. Not an error.
                "marker_cleared": cleared,
            },
        )
        return True
    finally:
        set_current_user(previous_user)


def sweep_once(now: Optional[datetime] = None) -> int:
    """One tick: claim at most one due marker and review it.

    One marker per tick, deliberately.  An arc review is an LLM turn measured in
    tens of seconds, so draining a backlog inside a single tick would hold the
    loop for minutes and make the next tick's timing unpredictable.  With four
    workers each taking one per interval the queue still drains at four decks a
    minute, and the oldest marker is always the one taken.

    Returns:
        1 when a marker was claimed (whether or not its review succeeded), 0
        when nothing was due.
    """
    claimed = claim_due_marker(now or datetime.utcnow())
    if claimed is None:
        return 0

    session_id, author = claimed
    run_arc_review(session_id, author)
    return 1


async def spec_review_sweeper_loop() -> None:
    """Background loop: runs :func:`sweep_once` every 60 seconds.

    Started in the FastAPI **lifespan** beside ``mark_timed_out_jobs_loop`` and
    ``request_log_cleanup_loop`` — **not** in ``run.py::init_database``.  The
    pre-fork rule there is about migrations and backfills, which must run
    exactly once; a periodic loop is the opposite case, and one that ran only in
    the pre-fork step would die with it.

    Survives its own exceptions so one transient DB failure does not take the
    loop down for the life of the process, and re-raises
    ``asyncio.CancelledError`` for clean shutdown.  Shape copied from
    ``mark_timed_out_jobs_loop``.

    ``sweep_once`` is synchronous and does blocking DB and LLM work, so it runs
    on a worker thread rather than on the event loop.
    """
    while True:
        try:
            await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
            swept = await asyncio.to_thread(sweep_once)
            if swept:
                logger.info("Spec-review sweep reviewed %d deck(s)", swept)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(
                "Spec-review sweep iteration failed",
                exc_info=True,
                extra={"sweep_error": str(e)},
            )
