"""Write fence for chat turns.

Every durable write a turn makes calls :func:`fence_turn_write` as the first
lock-taking statement of its transaction (same ``db`` session as the write).  The
claim is a no-op ``UPDATE`` of the turn's ``chat_requests`` row that matches only
while the turn is live, so it takes the row lock: a rollback that cancels the row
waits for in-flight writers, and a writer arriving after the cancel is refused.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.core.database import get_db_session
from src.services.graph.event_emitter import get_chat_request_id

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
