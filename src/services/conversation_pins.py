"""Persistence operations for a conversation's immutable graph identity."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.orm import sessionmaker

from src.database.models.graph_configuration import GraphRelease
from src.database.models.session import SessionMessage, UserSession
from src.domain.conversation_engine import AGENT_MODE_PHRASE


@dataclass(frozen=True)
class BackfillResult:
    graph_release_id: int
    graph_version: int
    pinned_count: int


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
