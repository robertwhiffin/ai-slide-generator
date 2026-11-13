"""Write fence for chat turns.

Every durable write a turn makes calls :func:`fence_turn_write` as the first
lock-taking statement of its transaction (same ``db`` session as the write).  The
claim is a no-op ``UPDATE`` of the turn's ``chat_requests`` row that matches only
while the turn is live, so it takes the row lock: a rollback that cancels the row
waits for in-flight writers, and a writer arriving after the cancel is refused.
"""

from __future__ import annotations

import logging

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from src.core.database import get_db_session
from src.services.graph.event_emitter import get_chat_request_id

logger = logging.getLogger(__name__)

LIVE_STATUSES: tuple[str, ...] = ("pending", "running")


class TurnFencedError(RuntimeError):
    """A write was refused because its turn is no longer live."""

    def __init__(self, request_id: str):
        super().__init__(f"turn {request_id} is no longer live; write refused")
        self.request_id = request_id


class TurnStopped(RuntimeError):
    """Raised by the generator's consumer loop when the turn was stopped.

    Never raised by a writer.
    """

    def __init__(self, request_id: str):
        super().__init__(f"turn {request_id} was stopped")
        self.request_id = request_id


def _claim(db: Session, request_id: str, statuses: tuple[str, ...]) -> bool:
    # Statuses are internal constants, never user input.
    in_list = ", ".join(f"'{s}'" for s in statuses)
    result = db.execute(
        text(
            "UPDATE chat_requests SET status = status "
            f"WHERE request_id = :rid AND status IN ({in_list})"
        ),
        {"rid": request_id},
    )
    return result.rowcount == 1


def claim_turn_row(db: Session, request_id: str) -> bool:
    """Lock the turn's row while it is live. True when the turn may still write."""
    return _claim(db, request_id, LIVE_STATUSES)


def fence_turn_write(
    db: Session,
    request_id: str | None = None,
    *,
    allow_completed: bool = False,
) -> None:
    """Refuse the write (``TurnFencedError``) unless the turn is still live.

    No request id (explicit or from the ContextVar) means no turn to fence: no SQL.
    ``allow_completed`` also admits ``completed`` (title thread only).
    """
    rid = request_id or get_chat_request_id()
    if rid is None:
        return
    statuses = LIVE_STATUSES + ("completed",) if allow_completed else LIVE_STATUSES
    if not _claim(db, rid, statuses):
        raise TurnFencedError(rid)


def start_chat_request(db: Session, request_id: str) -> bool:
    """Move ``pending`` -> ``running``. True only if this call made the move."""
    result = db.execute(
        text(
            "UPDATE chat_requests SET status = 'running' "
            "WHERE request_id = :rid AND status = 'pending'"
        ),
        {"rid": request_id},
    )
    return result.rowcount == 1


def turn_is_live(request_id: str) -> bool:
    """Read-only check of the turn's committed status, in its own session."""
    with get_db_session() as db:
        status = db.execute(
            text("SELECT status FROM chat_requests WHERE request_id = :rid"),
            {"rid": request_id},
        ).scalar()
    return status in LIVE_STATUSES


def raise_if_turn_ended(request_id: str | None = None) -> None:
    """Raise ``TurnFencedError`` if the turn is no longer live. Read-only; no lock.

    For a turn path that is about to start a model call with no fenced write before
    it, so an abandoned turn stops here instead of paying for that call.  It is a
    check, not a fence: a stop that lands just after it is still refused by the
    turn's next fenced write.  An unreadable status counts as live, for the same
    reason.  No request id (explicit or from the ContextVar) means no turn: no SQL.
    """
    rid = request_id or get_chat_request_id()
    if rid is None:
        return
    try:
        live = turn_is_live(rid)
    except Exception:
        logger.warning(
            "Could not read the turn's status; carrying on",
            exc_info=True,
            extra={"request_id": rid},
        )
        return
    if not live:
        raise TurnFencedError(rid)


def generation_hold_clause(owner_pk, *, live_only: bool = False):
    """Predicate on ``generation_snapshots`` rows that hold the deck of *owner_pk*.

    The ONE busy-deck rule: a snapshot on the deck whose request is live, or (unless
    *live_only*) whose own state is ``restore_failed``.  *owner_pk* is a column or
    value for ``user_sessions.id`` of the deck owner.  Returns ``(select, where)``:
    the select is ``GenerationSnapshot`` outer-joined to ``ChatRequest``; callers add
    columns / ``EXISTS`` around it.
    """
    from src.database.models.generation_snapshot import GenerationSnapshot
    from src.database.models.session import ChatRequest

    held = ChatRequest.status.in_(LIVE_STATUSES)
    if not live_only:
        held = or_(held, GenerationSnapshot.state == "restore_failed")
    base = select(GenerationSnapshot.id).select_from(GenerationSnapshot).outerjoin(
        ChatRequest, ChatRequest.request_id == GenerationSnapshot.request_id
    )
    return base, (GenerationSnapshot.owner_session_pk == owner_pk, held)
