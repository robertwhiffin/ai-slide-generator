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

A restore that fails rolls back whole.  A second transaction then marks the
request ``restore_failed`` and the snapshot ``state='restore_failed'``, and the
session lock stays held, so the deck stays locked to its sender until a later
retry restores it.
"""

from __future__ import annotations

import copy
import json
import logging
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Literal, Optional

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
from src.services.generation_fence import claim_turn_row
from src.services.shared_deck_attribution import MutationActor, record_shared_deck_mutation

logger = logging.getLogger(__name__)

#: The restore-pending copy (Global Constraints, exact): the request's
#: ``error_message`` after a failed restore, and the 409 detail while one is pending.
RESTORE_PENDING_MESSAGE = (
    "This deck is still being restored after a failed generation. Try again in a minute."
)

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


def _roll_back_claimed(
    db: Session,
    request_id: str,
    *,
    terminal_status: str,
    error_message: Optional[str],
    refuse_on_foreign_change: bool,
) -> _Outcome:
    """Steps 2-5 of the rollback, after the claim matched, in the claim's transaction."""
    request_session_pk = db.execute(
        select(ChatRequest.session_id).where(ChatRequest.request_id == request_id)
    ).scalar_one()
    snapshot = db.execute(
        select(GenerationSnapshot).where(GenerationSnapshot.request_id == request_id)
    ).scalar_one_or_none()

    if snapshot is None:
        # A monolith request: nothing to restore; end it and free the session.
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

    # Lock the two session rows, then the deck row: the order every deck writer's
    # flush takes them (user_sessions before session_slide_decks).
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

    # --- restore ---------------------------------------------------------
    _restore_session_fields(owner, actor, json.loads(snapshot.session_fields_json))
    db.flush()
    _restore_deck(db, snapshot, owner=owner, actor=actor, deck=deck)
    db.execute(delete(SessionMessage).where(SessionMessage.request_id == request_id))
    get_checkpointer().delete_checkpoints_after(
        actor.session_id, snapshot.checkpoint_id, session=db
    )
    db.flush()

    _end_request(
        db,
        request_id,
        status=terminal_status,
        error_message=error_message,
        rollback_outcome=RollbackResult.ROLLED_BACK.value,
    )
    discard_generation_snapshot(db, request_id)
    _release_session_lock(db, snapshot.actor_session_pk, request_id)

    invalidate = (actor.session_id,)
    if owner.session_id != actor.session_id:
        invalidate += (owner.session_id,)
    return _Outcome(RollbackResult.ROLLED_BACK, invalidate)


def _record_restore_failed(request_id: str, terminal_status: str) -> None:
    """The failed restore's second transaction: end the request as
    ``restore_failed`` and mark the snapshot, leaving the session lock held."""
    try:
        with get_db_session() as db:
            if claim_turn_row(db, request_id):
                _end_request(
                    db,
                    request_id,
                    status=terminal_status,
                    error_message=RESTORE_PENDING_MESSAGE,
                    rollback_outcome=RollbackResult.RESTORE_FAILED.value,
                )
            # Only an active snapshot: a sealed one belongs to a turn that committed.
            db.execute(
                update(GenerationSnapshot)
                .where(
                    GenerationSnapshot.request_id == request_id,
                    GenerationSnapshot.state == _SNAPSHOT_ACTIVE,
                )
                .values(state=_SNAPSHOT_RESTORE_FAILED)
                .execution_options(synchronize_session=False)
            )
    except Exception:
        logger.exception(
            "Could not record a failed generation restore",
            extra={"request_id": request_id},
        )


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

    If the restore raises, its transaction rolls back whole, the request ends as
    ``restore_failed`` with the snapshot kept and the lock held (``RESTORE_FAILED``).
    """
    if terminal_status not in _TERMINAL_STATUSES:
        raise ValueError(f"terminal_status must be one of {_TERMINAL_STATUSES}")

    claimed = False
    try:
        with get_db_session() as db:
            if not claim_turn_row(db, request_id):
                db.rollback()
                return RollbackResult.NOT_LIVE
            claimed = True
            outcome = _roll_back_claimed(
                db,
                request_id,
                terminal_status=terminal_status,
                error_message=error_message,
                refuse_on_foreign_change=refuse_on_foreign_change,
            )
    except Exception:
        if not claimed:
            raise
        # The first transaction is closed (rolled back) before the second opens:
        # on PostgreSQL the second's claim would otherwise wait on the first's lock.
        logger.exception(
            "Generation restore failed; the deck stays locked until it is retried",
            extra={"request_id": request_id, "terminal_status": terminal_status},
        )
        _record_restore_failed(request_id, terminal_status)
        return RollbackResult.RESTORE_FAILED

    if outcome.invalidate:
        _invalidate_local_deck_cache(outcome.invalidate)
    if outcome.result is RollbackResult.ROLLED_BACK:
        logger.info(
            "Rolled back generation",
            extra={"request_id": request_id, "terminal_status": terminal_status},
        )
    return outcome.result
