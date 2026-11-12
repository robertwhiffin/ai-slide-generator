"""Generation snapshot and the all-or-nothing rollback of an Agent-deck turn.

When Enter is pressed, :func:`take_generation_snapshot` records, in the database,
everything the turn can change: the owner's deck content columns (or "no deck
row"), every ``session_slides`` row of the owner, the owner's ``deck_mode``,
``graph_release_id`` and ``title``, the actor's ``title`` and ``genie_one``
conversation id, the actor thread's newest checkpoint id, and a watermark into
the shared-deck mutation log.  Chat messages need no snapshot: every row the
turn writes carries its ``request_id``.

A stopped, failed, timed-out or interrupted turn is undone by
:func:`roll_back_generation`, in ONE transaction whose first statement is the
fence claim (:func:`~src.services.generation_fence.claim_turn_row`).  The claim
row-locks the turn's ``chat_requests`` row, so a writer that has already passed
its fence finishes before the restore, and one that arrives later is refused.
The restore never undoes another person's work: a mutation event on the deck by
any other actor after the watermark refuses a stop, and makes a failure keep
the deck as it stands.

When the turn completes, :func:`seal_generation` marks the snapshot ``sealed``
(the commit point); from then on a stop is "already finished" and a failure
keeps the finished deck.

The restore runs in a SAVEPOINT inside the claim's transaction.  If it fails,
the savepoint rolls back and the same transaction marks the request
``restore_failed`` and the snapshot ``state='restore_failed'`` before it commits,
so the deck-row lock is held throughout: an Enter queued on the deck sees the
pending restore, never the half-built deck.  The session lock stays held, so the
deck stays locked to its sender until :func:`recover_orphaned_generations`
retries the restore.

:func:`recover_orphaned_generations` (the timeout loop, and startup) also rolls
back every live turn whose job is gone: its sender's session lock is no longer
its own, or has not been refreshed for :data:`ORPHAN_AFTER_SECONDS`.
"""

from __future__ import annotations

import copy
import json
import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from sqlalchemy import DateTime, Table, delete, func, insert, or_, select, update
from sqlalchemy.orm import Session

from src.api.services.session_manager import get_session_manager
from src.core.checkpointer import get_checkpointer
from src.core.database import get_db_session
from src.database.models.generation_snapshot import GenerationSnapshot
from src.database.models.session import (
    ChatRequest,
    SessionMessage,
    SessionSlide,
    SessionSlideDeck,
    SharedDeckMutationEvent,
    UserSession,
)
from src.services.generation_fence import LIVE_STATUSES, claim_turn_row
from src.services.shared_deck_attribution import MutationActor, record_shared_deck_mutation

logger = logging.getLogger(__name__)

#: The restore-pending copy (Global Constraints, exact): the request's
#: ``error_message`` after a failed restore, and the 409 detail while one is pending.
RESTORE_PENDING_MESSAGE = (
    "This deck is still being restored after a failed generation. Try again in a minute."
)

#: A live turn whose sender's session lock has not been refreshed for this long is
#: an orphan: three missed refreshes of the timeout loop's 60 s heartbeat
#: (``job_queue.refresh_job_session_locks_once``).
ORPHAN_AFTER_SECONDS = 180

#: ``error_message`` of a turn the orphan sweep rolled back.
GENERATION_INTERRUPTED_MESSAGE = "Generation interrupted"

#: The owner's ``session_slide_decks`` columns a turn can change, restored exactly.
#: ``version`` is bumped instead (so open clients and other processes reload), and
#: ``updated_at`` follows the write.
DECK_CONTENT_COLUMNS: tuple[str, ...] = (
    "title",
    "html_content",
    "scripts_content",
    "slide_count",
    "deck_json",
    "verification_map",
    "deck_spec_json",
    "css",
    "external_scripts_json",
    "head_meta_json",
    "modified_by",
)

_TERMINAL_STATUSES = ("cancelled", "error")

_SNAPSHOT_ACTIVE = "active"
_SNAPSHOT_SEALED = "sealed"
_SNAPSHOT_RESTORE_FAILED = "restore_failed"


class RollbackResult(str, Enum):
    """What :func:`roll_back_generation` did."""

    ROLLED_BACK = "rolled_back"
    KEPT_FOREIGN_CHANGE = "kept_foreign_change"
    REFUSED_FOREIGN_CHANGE = "refused_foreign_change"
    NOT_LIVE = "not_live"
    NO_SNAPSHOT = "no_snapshot"
    RESTORE_FAILED = "restore_failed"
    SEALED_KEPT = "sealed_kept"


# ---------------------------------------------------------------------------
# Row encoding: every column, exactly, through JSON
# ---------------------------------------------------------------------------


def _encode_row(table: Table, row: Dict[str, Any]) -> Dict[str, Any]:
    """*row* as JSON-safe values; ``DateTime`` columns as ISO strings."""
    out: Dict[str, Any] = {}
    for column in table.columns:
        value = row[column.name]
        if isinstance(column.type, DateTime) and value is not None:
            value = value.isoformat()
        out[column.name] = value
    return out


def _decode_row(table: Table, data: Dict[str, Any]) -> Dict[str, Any]:
    """Inverse of :func:`_encode_row`, for the columns *table* still has."""
    out: Dict[str, Any] = {}
    for column in table.columns:
        if column.name not in data:
            continue
        value = data[column.name]
        if isinstance(column.type, DateTime) and value is not None:
            value = datetime.fromisoformat(value)
        out[column.name] = value
    return out


def _genie_one_entry(agent_config: Any) -> Optional[Dict[str, Any]]:
    """The raw ``genie_one`` tool entry of a stored agent config, or None."""
    if not isinstance(agent_config, dict):
        return None
    for tool in agent_config.get("tools") or []:
        if isinstance(tool, dict) and tool.get("type") == "genie_one":
            return tool
    return None


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def take_generation_snapshot(db: Session, *, request_id: str, session_id: str) -> None:
    """Record what the turn *request_id* on *session_id* can change.

    Runs in the caller's transaction and does not commit, so the snapshot exists
    exactly when the caller's Enter commits.

    Raises:
        SessionNotFoundError: *session_id* (or its deck owner) does not exist.
    """
    manager = get_session_manager()
    actor = manager._get_session_or_raise(db, session_id)
    owner = manager._get_deck_owner_session(db, actor)

    deck_table = SessionSlideDeck.__table__
    deck_row = (
        db.execute(
            select(*(deck_table.c[name] for name in DECK_CONTENT_COLUMNS)).where(
                deck_table.c.session_id == owner.id
            )
        )
        .mappings()
        .one_or_none()
    )

    slide_table = SessionSlide.__table__
    slide_rows = [
        _encode_row(slide_table, dict(row))
        for row in db.execute(
            select(slide_table)
            .where(slide_table.c.session_id == owner.id)
            .order_by(slide_table.c.position)
        ).mappings()
    ]

    genie_one = _genie_one_entry(actor.agent_config)
    session_fields = {
        "owner": {
            "deck_mode": owner.deck_mode,
            "graph_release_id": owner.graph_release_id,
            "title": owner.title,
        },
        "actor": {
            "title": actor.title,
            "genie_one_present": genie_one is not None,
            "genie_one_conversation_id": (
                genie_one.get("conversation_id") if genie_one is not None else None
            ),
        },
    }

    watermark = db.execute(
        select(func.max(SharedDeckMutationEvent.id)).where(
            SharedDeckMutationEvent.root_session_id == owner.id
        )
    ).scalar()

    db.add(
        GenerationSnapshot(
            request_id=request_id,
            actor_session_pk=actor.id,
            owner_session_pk=owner.id,
            deck_present=deck_row is not None,
            deck_columns_json=json.dumps(dict(deck_row)) if deck_row is not None else None,
            slide_rows_json=json.dumps(slide_rows),
            session_fields_json=json.dumps(session_fields),
            checkpoint_id=get_checkpointer().latest_checkpoint_id(actor.session_id, session=db),
            mutation_watermark=watermark or 0,
        )
    )
    db.flush()


def has_generation_snapshot(request_id: str) -> bool:
    """True while a snapshot row (in any state) exists for *request_id*."""
    with get_db_session() as db:
        return (
            db.execute(
                select(GenerationSnapshot.id).where(GenerationSnapshot.request_id == request_id)
            ).first()
            is not None
        )


def has_pending_restore(session_id: str) -> bool:
    """True when a failed restore is pending on *session_id*'s deck.

    That is any ``restore_failed`` snapshot whose actor is this session or whose
    deck owner is this session's deck owner.
    """
    with get_db_session() as db:
        session = db.execute(
            select(UserSession.id, UserSession.parent_session_id).where(
                UserSession.session_id == session_id
            )
        ).first()
        if session is None:
            return False
        owner_pk = session.parent_session_id or session.id
        return (
            db.execute(
                select(GenerationSnapshot.id).where(
                    GenerationSnapshot.state == _SNAPSHOT_RESTORE_FAILED,
                    or_(
                        GenerationSnapshot.actor_session_pk == session.id,
                        GenerationSnapshot.owner_session_pk == owner_pk,
                    ),
                )
            ).first()
            is not None
        )


def discard_generation_snapshot(db: Session, request_id: str) -> None:
    """Delete *request_id*'s snapshot in the caller's transaction (no commit)."""
    db.execute(delete(GenerationSnapshot).where(GenerationSnapshot.request_id == request_id))


def seal_generation(request_id: str) -> bool:
    """Mark the turn's snapshot ``sealed``: the turn has committed.

    One transaction: the fence claim, then ``active`` -> ``sealed``.  False (and
    nothing written) when the turn is no longer live or its snapshot is not
    ``active``.  A live turn with no snapshot at all is sealed vacuously (True,
    with a WARNING), so a graph turn is never abandoned in ``running``.
    """
    with get_db_session() as db:
        if not claim_turn_row(db, request_id):
            db.rollback()
            return False
        sealed = db.execute(
            update(GenerationSnapshot)
            .where(
                GenerationSnapshot.request_id == request_id,
                GenerationSnapshot.state == _SNAPSHOT_ACTIVE,
            )
            .values(state=_SNAPSHOT_SEALED)
            .execution_options(synchronize_session=False)
        ).rowcount
        if sealed == 1:
            return True
        exists = (
            db.execute(
                select(GenerationSnapshot.id).where(GenerationSnapshot.request_id == request_id)
            ).first()
            is not None
        )
        if exists:
            db.rollback()
            return False
        logger.warning(
            "Sealing a live generation that has no snapshot",
            extra={"request_id": request_id},
        )
        return True


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


def _end_request(
    db: Session,
    request_id: str,
    *,
    status: str,
    error_message: Optional[str],
    rollback_outcome: Optional[str],
) -> None:
    db.execute(
        update(ChatRequest)
        .where(ChatRequest.request_id == request_id)
        .values(
            status=status,
            error_message=error_message,
            completed_at=datetime.utcnow(),
            rollback_outcome=rollback_outcome,
        )
        .execution_options(synchronize_session=False)
    )


def _release_session_lock(db: Session, session_pk: int, request_id: str) -> None:
    """Release *session_pk*'s processing lock only while *request_id* owns it."""
    db.execute(
        update(UserSession)
        .where(
            UserSession.id == session_pk,
            UserSession.is_processing.is_(True),
            UserSession.processing_request_id == request_id,
        )
        .values(is_processing=False, processing_started_at=None, processing_request_id=None)
        .execution_options(synchronize_session=False)
    )


def _foreign_change_since(db: Session, snapshot: GenerationSnapshot) -> bool:
    """Whether anyone but the actor mutated the owner's deck after the snapshot."""
    return (
        db.execute(
            select(SharedDeckMutationEvent.id)
            .where(
                SharedDeckMutationEvent.root_session_id == snapshot.owner_session_pk,
                SharedDeckMutationEvent.id > (snapshot.mutation_watermark or 0),
                or_(
                    SharedDeckMutationEvent.actor_session_id.is_(None),
                    SharedDeckMutationEvent.actor_session_id != snapshot.actor_session_pk,
                ),
            )
            .limit(1)
        ).first()
        is not None
    )


def _restore_session_fields(owner: UserSession, actor: UserSession, fields: Dict[str, Any]) -> None:
    owner_fields = fields["owner"]
    owner.deck_mode = owner_fields["deck_mode"]
    owner.graph_release_id = owner_fields["graph_release_id"]
    owner.title = owner_fields["title"]

    actor_fields = fields["actor"]
    actor.title = actor_fields["title"]
    # Only the entry's conversation id, and only while the entry still exists:
    # every other agent-config change made mid-turn is the user's, and stays.
    if actor_fields["genie_one_present"]:
        config = copy.deepcopy(actor.agent_config)
        entry = _genie_one_entry(config)
        wanted = actor_fields["genie_one_conversation_id"]
        if entry is not None and entry.get("conversation_id") != wanted:
            entry["conversation_id"] = wanted
            actor.agent_config = config


def _restore_deck(
    db: Session,
    snapshot: GenerationSnapshot,
    *,
    owner: UserSession,
    actor: UserSession,
    deck: Optional[SessionSlideDeck],
) -> None:
    """Put the owner's deck row and slide rows back as the snapshot holds them."""
    slide_table = SessionSlide.__table__
    db.execute(delete(slide_table).where(slide_table.c.session_id == owner.id))

    if not snapshot.deck_present:
        # A first generation: no deck then, so none now.  Its deck_reviews go
        # through the foreign key's cascade and its mutation evidence keeps a
        # NULL root_deck_id.  No mutation is recorded: there is no deck to attribute.
        if deck is not None:
            db.expunge(deck)
            db.execute(delete(SessionSlideDeck).where(SessionSlideDeck.id == deck.id))
        return

    if deck is None:
        raise RuntimeError(
            f"generation snapshot {snapshot.request_id} has a deck but the deck row is gone"
        )
    columns = json.loads(snapshot.deck_columns_json or "{}")
    for name in DECK_CONTENT_COLUMNS:
        if name in columns:
            setattr(deck, name, columns[name])
    deck.version = (deck.version or 0) + 1

    rows = [_decode_row(slide_table, data) for data in json.loads(snapshot.slide_rows_json or "[]")]
    if rows:
        db.execute(insert(slide_table), rows)
    db.flush()

    # One restore_version/deck event, as restore_version records it.
    record_shared_deck_mutation(
        db,
        requesting_session=actor,
        deck_owner=owner,
        deck=deck,
        actor=MutationActor(actor.session_id, actor.graph_release_id),
        operation="restore_version",
        object_type="deck",
        object_id=None,
    )


class _Outcome:
    """What the rollback's transaction decided, carried out of its ``with``."""

    def __init__(self, result: RollbackResult, invalidate: tuple[str, ...] = ()):
        self.result = result
        self.invalidate = invalidate


def _sessions_touched(actor: UserSession, owner: UserSession) -> tuple[str, ...]:
    """The session ids whose cached decks a restore makes stale."""
    if owner.session_id == actor.session_id:
        return (actor.session_id,)
    return (actor.session_id, owner.session_id)


def _lock_deck(
    db: Session, snapshot: GenerationSnapshot
) -> tuple[UserSession, UserSession, Optional[SessionSlideDeck]]:
    """Lock the actor and owner session rows, then the owner's deck row.

    The order every deck writer's flush takes them (``user_sessions`` before
    ``session_slide_decks``).  Returns ``(actor, owner, deck)``.
    """
    sessions = {
        row.id: row
        for row in db.execute(
            select(UserSession)
            .where(UserSession.id.in_((snapshot.actor_session_pk, snapshot.owner_session_pk)))
            .order_by(UserSession.id)
            .with_for_update()
        ).scalars()
    }
    actor = sessions[snapshot.actor_session_pk]
    owner = sessions[snapshot.owner_session_pk]
    deck = db.execute(
        select(SessionSlideDeck).where(SessionSlideDeck.session_id == owner.id).with_for_update()
    ).scalar_one_or_none()
    return actor, owner, deck


def _restore_turn(
    db: Session,
    snapshot: GenerationSnapshot,
    *,
    actor: UserSession,
    owner: UserSession,
    deck: Optional[SessionSlideDeck],
) -> None:
    """Put back everything the turn changed: session fields, deck, slides,
    messages and checkpoints.  In the caller's transaction (no commit)."""
    _restore_session_fields(owner, actor, json.loads(snapshot.session_fields_json))
    db.flush()
    _restore_deck(db, snapshot, owner=owner, actor=actor, deck=deck)
    db.execute(delete(SessionMessage).where(SessionMessage.request_id == snapshot.request_id))
    get_checkpointer().delete_checkpoints_after(
        actor.session_id, snapshot.checkpoint_id, session=db
    )
    db.flush()


def _end_without_restore(
    db: Session,
    request_id: str,
    snapshot: Optional[GenerationSnapshot],
    *,
    terminal_status: str,
    error_message: Optional[str],
) -> Optional[_Outcome]:
    """The claimed turn's ending when there is nothing to restore, or None.

    No snapshot (a monolith request) ends it and frees its session; a sealed one
    keeps the finished deck (a stop arrived too late and changes nothing).
    """
    if snapshot is None:
        request_session_pk = db.execute(
            select(ChatRequest.session_id).where(ChatRequest.request_id == request_id)
        ).scalar_one()
        _end_request(
            db,
            request_id,
            status=terminal_status,
            error_message=error_message,
            rollback_outcome=None,
        )
        _release_session_lock(db, request_session_pk, request_id)
        return _Outcome(RollbackResult.NO_SNAPSHOT)

    if snapshot.state == _SNAPSHOT_SEALED:
        if terminal_status == "cancelled":
            # The turn has committed; a stop arrived too late and changes nothing.
            db.rollback()
            return _Outcome(RollbackResult.NOT_LIVE)
        # A failure, timeout or orphan after the commit point keeps the deck.
        _end_request(
            db, request_id, status="error", error_message=error_message, rollback_outcome=None
        )
        discard_generation_snapshot(db, request_id)
        _release_session_lock(db, snapshot.actor_session_pk, request_id)
        return _Outcome(RollbackResult.SEALED_KEPT)

    return None


def _record_restore_failed(
    db: Session,
    request_id: str,
    *,
    terminal_status: str,
    error_message: Optional[str],
) -> _Outcome:
    """After the restore's savepoint rolled back: mark the snapshot, then the
    request, ``restore_failed`` in the claim's transaction, the deck-row lock and
    the session lock still held.

    The snapshot first (C11): only an ``active`` one is marked, and the request
    only if it was.  A snapshot that is no longer active is judged as it is now.
    """
    marked = db.execute(
        update(GenerationSnapshot)
        .where(
            GenerationSnapshot.request_id == request_id,
            GenerationSnapshot.state == _SNAPSHOT_ACTIVE,
        )
        .values(state=_SNAPSHOT_RESTORE_FAILED)
        .execution_options(synchronize_session=False)
    ).rowcount
    if marked == 1:
        _end_request(
            db,
            request_id,
            status=terminal_status,
            error_message=RESTORE_PENDING_MESSAGE,
            rollback_outcome=RollbackResult.RESTORE_FAILED.value,
        )
        return _Outcome(RollbackResult.RESTORE_FAILED)

    # Not reachable while the claim is held (sealing needs it); decided again
    # from the snapshot's current state rather than marked blindly.
    snapshot = db.execute(
        select(GenerationSnapshot)
        .where(GenerationSnapshot.request_id == request_id)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    logger.warning(
        "A failed restore's snapshot was no longer active",
        extra={"request_id": request_id, "state": snapshot.state if snapshot else None},
    )
    outcome = _end_without_restore(
        db, request_id, snapshot, terminal_status=terminal_status, error_message=error_message
    )
    if outcome is None:
        raise RuntimeError(f"generation snapshot {request_id} is active but was not marked")
    return outcome


def _roll_back_claimed(
    db: Session,
    request_id: str,
    *,
    terminal_status: str,
    error_message: Optional[str],
    refuse_on_foreign_change: bool,
) -> _Outcome:
    """Steps 2-5 of the rollback, after the claim matched, in the claim's transaction."""
    snapshot = db.execute(
        select(GenerationSnapshot).where(GenerationSnapshot.request_id == request_id)
    ).scalar_one_or_none()

    ended = _end_without_restore(
        db, request_id, snapshot, terminal_status=terminal_status, error_message=error_message
    )
    if ended is not None:
        return ended

    actor, owner, deck = _lock_deck(db, snapshot)

    if _foreign_change_since(db, snapshot):
        if refuse_on_foreign_change:
            db.rollback()
            return _Outcome(RollbackResult.REFUSED_FOREIGN_CHANGE)
        logger.error(
            "Generation failed and was NOT rolled back: someone else changed the deck since Enter",
            extra={
                "request_id": request_id,
                "session_id": actor.session_id,
                "deck_owner_session_id": owner.session_id,
                "error_message": error_message,
            },
        )
        _end_request(
            db,
            request_id,
            status=terminal_status,
            error_message=error_message,
            rollback_outcome=RollbackResult.KEPT_FOREIGN_CHANGE.value,
        )
        discard_generation_snapshot(db, request_id)
        _release_session_lock(db, snapshot.actor_session_pk, request_id)
        return _Outcome(RollbackResult.KEPT_FOREIGN_CHANGE)

    # --- restore, in a savepoint: the row locks above outlive its rollback ---
    try:
        with db.begin_nested():
            _restore_turn(db, snapshot, actor=actor, owner=owner, deck=deck)
            _end_request(
                db,
                request_id,
                status=terminal_status,
                error_message=error_message,
                rollback_outcome=RollbackResult.ROLLED_BACK.value,
            )
            discard_generation_snapshot(db, request_id)
            _release_session_lock(db, snapshot.actor_session_pk, request_id)
    except Exception:
        logger.exception(
            "Generation restore failed; the deck stays locked until it is retried",
            extra={"request_id": request_id, "terminal_status": terminal_status},
        )
        return _record_restore_failed(
            db, request_id, terminal_status=terminal_status, error_message=error_message
        )

    return _Outcome(RollbackResult.ROLLED_BACK, _sessions_touched(actor, owner))


def _invalidate_local_deck_cache(session_ids: tuple[str, ...]) -> None:
    """Drop this process's cached decks; other processes reload on the version
    bump, or drop a deck whose row is gone (``ChatService._get_or_load_deck``)."""
    try:
        from src.api.services.chat_service import get_chat_service

        service = get_chat_service()
        for session_id in session_ids:
            service._invalidate_deck_cache(session_id)
    except Exception:
        logger.warning(
            "Could not invalidate the deck cache after a rollback",
            extra={"session_ids": list(session_ids)},
            exc_info=True,
        )


def roll_back_generation(
    request_id: str,
    *,
    terminal_status: Literal["cancelled", "error"],
    error_message: str | None,
    refuse_on_foreign_change: bool,
) -> RollbackResult:
    """End the turn *request_id* and put everything it changed back as at Enter.

    One transaction, the fence claim first:

    - not live (finished, already rolled back, unknown): ``NOT_LIVE``, nothing written
    - no snapshot (a monolith request): ends it and releases the lock, ``NO_SNAPSHOT``
    - sealed: a stop is ``NOT_LIVE`` and changes nothing; a failure keeps the
      finished deck and ends the request as ``error`` (``SEALED_KEPT``)
    - someone else changed the deck since Enter: a stop is refused and the turn
      stays live (``REFUSED_FOREIGN_CHANGE``); a failure ends the request and keeps
      the deck as it stands (``KEPT_FOREIGN_CHANGE``)
    - otherwise the deck, slides, session fields, messages and checkpoints are
      restored, the request ended, the snapshot deleted and the lock released
      (``ROLLED_BACK``)

    If the restore raises, its savepoint rolls back (nothing of it is kept) and
    the same transaction ends the request as ``restore_failed`` with the snapshot
    kept and the lock held (``RESTORE_FAILED``); :func:`recover_orphaned_generations`
    retries it.  Anything else that raises rolls the whole transaction back and
    propagates: the turn is then still live, so a later stop, timeout or orphan
    sweep ends it.
    """
    if terminal_status not in _TERMINAL_STATUSES:
        raise ValueError(f"terminal_status must be one of {_TERMINAL_STATUSES}")

    with get_db_session() as db:
        if not claim_turn_row(db, request_id):
            db.rollback()
            return RollbackResult.NOT_LIVE
        outcome = _roll_back_claimed(
            db,
            request_id,
            terminal_status=terminal_status,
            error_message=error_message,
            refuse_on_foreign_change=refuse_on_foreign_change,
        )

    if outcome.invalidate:
        _invalidate_local_deck_cache(outcome.invalidate)
    if outcome.result is RollbackResult.ROLLED_BACK:
        logger.info(
            "Rolled back generation",
            extra={"request_id": request_id, "terminal_status": terminal_status},
        )
    return outcome.result


# ---------------------------------------------------------------------------
# Recovery: orphaned turns and failed restores
# ---------------------------------------------------------------------------


def _orphaned_request_ids(now: datetime) -> List[str]:
    """Live requests with an ``active``/``sealed`` snapshot whose job is gone.

    The ACTOR session's lock decides: no longer bound to the request (NULL-safe,
    so a released or unbound lock counts), or not refreshed for
    :data:`ORPHAN_AFTER_SECONDS`.
    """
    cutoff = now - timedelta(seconds=ORPHAN_AFTER_SECONDS)
    with get_db_session() as db:
        return list(
            db.execute(
                select(ChatRequest.request_id)
                .join(GenerationSnapshot, GenerationSnapshot.request_id == ChatRequest.request_id)
                .join(UserSession, UserSession.id == GenerationSnapshot.actor_session_pk)
                .where(
                    ChatRequest.status.in_(LIVE_STATUSES),
                    GenerationSnapshot.state.in_((_SNAPSHOT_ACTIVE, _SNAPSHOT_SEALED)),
                    or_(
                        UserSession.processing_request_id.is_distinct_from(
                            ChatRequest.request_id
                        ),
                        UserSession.processing_started_at < cutoff,
                    ),
                )
                .order_by(GenerationSnapshot.id)
            ).scalars()
        )


def _restore_failed_snapshot_ids() -> List[int]:
    with get_db_session() as db:
        return list(
            db.execute(
                select(GenerationSnapshot.id)
                .where(GenerationSnapshot.state == _SNAPSHOT_RESTORE_FAILED)
                .order_by(GenerationSnapshot.id)
            ).scalars()
        )


def _settle_retried_request(db: Session, request_id: str, outcome: RollbackResult) -> None:
    """A retried restore's request: its status and ``completed_at`` stay as the
    failed restore ended it; the outcome is now final, so the restore-pending
    copy goes."""
    db.execute(
        update(ChatRequest)
        .where(ChatRequest.request_id == request_id)
        .values(error_message=None, rollback_outcome=outcome.value)
        .execution_options(synchronize_session=False)
    )


def _retry_restore(snapshot_id: int) -> Optional[RollbackResult]:
    """Retry one ``restore_failed`` snapshot's restore, in one transaction.

    The request is already terminal, so there is no liveness claim; the snapshot
    itself is claimed instead, by the transaction's first statement (a no-op
    UPDATE matched on the state, so a row lock): a second sweep waits on it and
    then finds the snapshot gone.  The foreign-change check runs again (C11).  A
    restore that raises rolls everything back, the claim included, and is retried
    by the next sweep.

    Returns:
        ``ROLLED_BACK`` or ``KEPT_FOREIGN_CHANGE``; None when another sweep holds
        (or has handled) the snapshot.
    """
    with get_db_session() as db:
        claimed = db.execute(
            update(GenerationSnapshot)
            .where(
                GenerationSnapshot.id == snapshot_id,
                GenerationSnapshot.state == _SNAPSHOT_RESTORE_FAILED,
            )
            .values(state=_SNAPSHOT_RESTORE_FAILED)
            .execution_options(synchronize_session=False)
        ).rowcount
        if claimed != 1:
            db.rollback()
            return None
        snapshot = db.execute(
            select(GenerationSnapshot).where(GenerationSnapshot.id == snapshot_id)
        ).scalar_one()
        request_id = snapshot.request_id
        actor, owner, deck = _lock_deck(db, snapshot)

        if _foreign_change_since(db, snapshot):
            logger.error(
                "A failed generation restore was NOT retried: someone else changed the "
                "deck since Enter",
                extra={
                    "request_id": request_id,
                    "session_id": actor.session_id,
                    "deck_owner_session_id": owner.session_id,
                },
            )
            result = RollbackResult.KEPT_FOREIGN_CHANGE
            invalidate: tuple[str, ...] = ()
        else:
            _restore_turn(db, snapshot, actor=actor, owner=owner, deck=deck)
            result = RollbackResult.ROLLED_BACK
            invalidate = _sessions_touched(actor, owner)

        _settle_retried_request(db, request_id, result)
        discard_generation_snapshot(db, request_id)
        _release_session_lock(db, snapshot.actor_session_pk, request_id)

    if invalidate:
        _invalidate_local_deck_cache(invalidate)
    logger.info(
        "Retried a failed generation restore",
        extra={"request_id": request_id, "rollback_result": result.value},
    )
    return result


def recover_orphaned_generations(now: datetime | None = None) -> int:
    """Roll back every orphaned turn, then retry every failed restore.

    An orphan is a live turn with an ``active`` or ``sealed`` snapshot whose job
    is gone: its sender's session lock is no longer bound to it, or has not been
    refreshed for :data:`ORPHAN_AFTER_SECONDS` (a restart, a dead process).  It is
    rolled back as a failure (``error``, ``"Generation interrupted"``, never
    refused on a foreign change); a sealed one keeps its finished deck
    (``SEALED_KEPT``).  Then every ``restore_failed`` snapshot is retried
    (:func:`_retry_restore`).  One entry's error is logged and the sweep goes on.

    Blocking (it restores decks): run it in a worker thread, never on the event loop.

    Args:
        now: The sweep's clock (``datetime.utcnow()`` when omitted).

    Returns:
        The number handled: orphans ended, plus restores retried.
    """
    now = now or datetime.utcnow()
    handled = 0

    for request_id in _orphaned_request_ids(now):
        try:
            result = roll_back_generation(
                request_id,
                terminal_status="error",
                error_message=GENERATION_INTERRUPTED_MESSAGE,
                refuse_on_foreign_change=False,
            )
        except Exception:
            logger.exception(
                "Could not roll back an orphaned generation", extra={"request_id": request_id}
            )
            continue
        if result is not RollbackResult.NOT_LIVE:
            handled += 1
            logger.warning(
                "Rolled back an orphaned generation",
                extra={"request_id": request_id, "rollback_result": result.value},
            )

    for snapshot_id in _restore_failed_snapshot_ids():
        try:
            if _retry_restore(snapshot_id) is not None:
                handled += 1
        except Exception:
            logger.exception(
                "Retrying a failed generation restore failed again",
                extra={"snapshot_id": snapshot_id},
            )

    return handled
