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


@dataclass(frozen=True)
class ConversationGraphVersion:
    """The safe graph-release information a session response may disclose."""

    graph_version: int | None
    active_graph_version: int
    is_older_than_active: bool


class ActiveGraphReleaseUnavailableError(RuntimeError):
    """No active release existed across the bounded lock scans."""


class ConversationPinMissingError(RuntimeError):
    """A known conversation has no persisted graph-release identity."""


class ConversationSessionNotFoundError(RuntimeError):
    """The requested conversation does not exist."""


class ConversationGraphReleaseIntegrityError(RuntimeError):
    """A session pin or active release no longer has a valid referent."""


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


def _require_active_graph_release(db: Session) -> GraphRelease:
    """Load exactly one active release for a public session projection."""
    active = db.execute(
        select(GraphRelease).where(GraphRelease.effective_to.is_(None))
    ).scalar_one_or_none()
    if active is None:
        raise ConversationGraphReleaseIntegrityError("no active Graph Release")
    return active


def _pinned_graph_release_or_none(
    db: Session, graph_release_id: int | None
) -> GraphRelease | None:
    """Load a persisted pin, preserving null pins and rejecting dangling ones."""
    if graph_release_id is None:
        return None
    if not isinstance(graph_release_id, int):
        raise ConversationGraphReleaseIntegrityError("invalid Graph Release pin")
    pinned = db.get(GraphRelease, graph_release_id)
    if pinned is None:
        raise ConversationGraphReleaseIntegrityError("missing pinned Graph Release")
    return pinned


def get_conversation_graph_version(
    db: Session, session: UserSession
) -> ConversationGraphVersion:
    """Project a session's pinned release without disclosing its internal identity."""
    active = _require_active_graph_release(db)
    pinned = _pinned_graph_release_or_none(db, session.graph_release_id)
    return ConversationGraphVersion(
        graph_version=None if pinned is None else pinned.version_number,
        active_graph_version=active.version_number,
        is_older_than_active=bool(
            pinned and pinned.version_number < active.version_number
        ),
    )


def get_conversation_graph_versions(
    db: Session, sessions: list[UserSession]
) -> dict[int, ConversationGraphVersion]:
    """Batch-project session versions with one active lookup and one pinned join."""
    if not sessions:
        return {}

    active = _require_active_graph_release(db)
    session_ids = [session.id for session in sessions]
    rows = db.execute(
        select(
            UserSession.id,
            UserSession.graph_release_id,
            GraphRelease.version_number,
        )
        .outerjoin(GraphRelease, UserSession.graph_release_id == GraphRelease.id)
        .where(UserSession.id.in_(session_ids))
    ).all()

    versions: dict[int, ConversationGraphVersion] = {}
    for session_id, graph_release_id, graph_version in rows:
        if graph_release_id is not None and graph_version is None:
            raise ConversationGraphReleaseIntegrityError("missing pinned Graph Release")
        versions[session_id] = ConversationGraphVersion(
            graph_version=graph_version,
            active_graph_version=active.version_number,
            is_older_than_active=bool(
                graph_version is not None and graph_version < active.version_number
            ),
        )
    if len(versions) != len(session_ids):
        raise ConversationGraphReleaseIntegrityError("missing session in graph projection")
    return versions


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
