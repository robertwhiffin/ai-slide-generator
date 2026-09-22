"""Persistence operations for a conversation's immutable graph identity."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from src.database.models.graph_configuration import GraphRelease
from src.database.models.session import SessionMessage, UserSession
from src.domain.conversation_engine import AGENT_MODE_PHRASE


@dataclass(frozen=True)
class BackfillResult:
    graph_release_id: int
    graph_version: int
    pinned_count: int


@dataclass(frozen=True)
class PinnedRelease:
    """The immutable identity selected while creating a graph-capable root."""

    release_id: int
    graph_version: int


class ActiveGraphReleaseUnavailableError(RuntimeError):
    """No active release existed across the bounded lock scans."""


class ConversationPinMissingError(RuntimeError):
    """A known conversation has no persisted graph-release identity."""


class ConversationSessionNotFoundError(RuntimeError):
    """The requested conversation does not exist."""


MAX_ACTIVE_RELEASE_LOCK_SCANS = 2


def _active_release_for_update():
    return (
        select(GraphRelease)
        .where(GraphRelease.effective_to.is_(None))
        .with_for_update()
    )


def lock_active_graph_release(db: Session) -> PinnedRelease:
    """Lock the active release, retrying only the publication handoff once."""
    for scan in range(MAX_ACTIVE_RELEASE_LOCK_SCANS):
        release = db.execute(_active_release_for_update()).scalar_one_or_none()
        if release is not None:
            return PinnedRelease(release.id, release.version_number)
        if scan == 0:
            continue
    raise ActiveGraphReleaseUnavailableError("no active Graph Release")


def load_conversation_pin(session_factory: sessionmaker, session_id: str) -> int:
    """Return exactly the persisted pin, never an active/latest substitute."""
    with session_factory() as db:
        row = db.scalar(select(UserSession).where(UserSession.session_id == session_id))
        if row is None:
            raise ConversationSessionNotFoundError(session_id)
        if not isinstance(row.graph_release_id, int):
            raise ConversationPinMissingError(session_id)
        return row.graph_release_id


def backfill_conversation_pins(session_factory: sessionmaker) -> BackfillResult:
    """Pin historical graph conversations to V1 in one transaction/set update."""
    with session_factory.begin() as db:
        return _backfill_in_transaction(db)


def _backfill_in_transaction(db) -> BackfillResult:
    graph_release_id, graph_version = db.execute(
        select(GraphRelease.id, GraphRelease.version_number).where(
            GraphRelease.version_number == 1
        )
    ).one()

    ranked_first_user_messages = (
        select(
            SessionMessage.session_id.label("session_id"),
            SessionMessage.content.label("content"),
            func.row_number()
            .over(
                partition_by=SessionMessage.session_id,
                order_by=(SessionMessage.created_at, SessionMessage.id),
            )
            .label("message_rank"),
        )
        .join(UserSession, UserSession.id == SessionMessage.session_id)
        .where(
            UserSession.parent_session_id.is_(None),
            SessionMessage.role == "user",
        )
        .cte("ranked_first_user_messages")
    )
    graph_root_ids = select(ranked_first_user_messages.c.session_id).where(
        ranked_first_user_messages.c.message_rank == 1,
        ranked_first_user_messages.c.content.contains(AGENT_MODE_PHRASE),
    )
    root_owner_id = func.coalesce(UserSession.parent_session_id, UserSession.id)
    result = db.execute(
        update(UserSession)
        .where(
            root_owner_id.in_(graph_root_ids),
            UserSession.graph_release_id.is_(None),
        )
        .values(graph_release_id=graph_release_id)
        .execution_options(synchronize_session=False)
    )
    return BackfillResult(
        graph_release_id=graph_release_id,
        graph_version=graph_version,
        pinned_count=result.rowcount,
    )
