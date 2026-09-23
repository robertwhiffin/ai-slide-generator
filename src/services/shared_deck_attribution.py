"""Transactional attribution seam for append-only shared-deck evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models.graph_configuration import GraphRelease
from src.database.models.session import (
    SessionSlideDeck,
    SharedDeckMutationEvent,
    UserSession,
)

MutationOperation = Literal[
    "save_deck",
    "save_deck_slides",
    "write_slide",
    "delete_slide",
    "write_deck_level",
    "insert_slide",
    "update_slide",
    "duplicate_slide",
    "reorder_slides",
    "restore_version",
]
MutationObjectType = Literal["deck", "slide"]

_OPERATION_OBJECT_TYPES: dict[str, str] = {
    "save_deck": "deck",
    "save_deck_slides": "deck",
    "write_slide": "slide",
    "delete_slide": "slide",
    "write_deck_level": "deck",
    "insert_slide": "deck",
    "update_slide": "deck",
    "duplicate_slide": "deck",
    "reorder_slides": "deck",
    "restore_version": "deck",
}


@dataclass(frozen=True, slots=True)
class MutationActor:
    actor_session_id: str
    graph_release_id: int | None


def record_shared_deck_mutation(
    db: Session,
    *,
    requesting_session: UserSession,
    deck_owner: UserSession,
    deck: SessionSlideDeck,
    actor: MutationActor,
    operation: MutationOperation,
    object_type: MutationObjectType,
    object_id: str | None,
) -> SharedDeckMutationEvent:
    """Append evidence inside the caller's transaction without committing it."""
    expected_object_type = _OPERATION_OBJECT_TYPES.get(operation)
    if expected_object_type != object_type:
        raise ValueError("illegal shared-deck mutation operation/object pair")
    if actor.actor_session_id != requesting_session.session_id:
        raise ValueError("mutation actor must equal the requesting session")
    if requesting_session.id is None:
        raise ValueError("requesting session must be persisted before attribution")
    if deck_owner.id is None or deck.id is None or deck.session_id != deck_owner.id:
        raise ValueError("deck must belong to the supplied deck owner")

    # Avoid an implicit autoflush while validating provenance. The explicit flush
    # below is the mutation boundary: caller content is durable in this transaction
    # before its evidence row and both still roll back together on any later error.
    with db.no_autoflush:
        persisted_actor = db.scalar(
            select(UserSession).where(
                UserSession.session_id == actor.actor_session_id
            )
        )
        if persisted_actor is None:
            raise ValueError("mutation actor session does not exist")
        if persisted_actor.id != requesting_session.id:
            raise ValueError("mutation actor must equal the requesting session")
        if persisted_actor.graph_release_id != actor.graph_release_id:
            raise ValueError("mutation actor pin does not match its persisted pin")

        release = None
        if actor.graph_release_id is not None:
            release = db.get(GraphRelease, actor.graph_release_id)
            if release is None:
                raise ValueError("mutation actor's exact Graph Release does not exist")

    db.flush()
    if (
        deck_owner.collaboration_identity is None
        or deck.collaboration_identity is None
        or persisted_actor.collaboration_identity is None
    ):
        raise ValueError("collaboration identities must exist before mutation evidence")

    mutation_event = SharedDeckMutationEvent(
        root_session_id=deck_owner.id,
        root_deck_id=deck.id,
        actor_session_id=persisted_actor.id,
        root_session_identity=deck_owner.collaboration_identity,
        root_deck_identity=deck.collaboration_identity,
        actor_session_identity=persisted_actor.collaboration_identity,
        graph_release_id=actor.graph_release_id,
        graph_version=None if release is None else release.version_number,
        operation=operation,
        object_type=object_type,
        object_id=object_id,
    )
    db.add(mutation_event)
    db.flush()
    return mutation_event
