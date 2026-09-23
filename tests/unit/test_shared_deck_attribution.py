from __future__ import annotations

import importlib
import importlib.util
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.core.database import Base
from src.database.models.graph_configuration import GraphRelease
from src.database.models.session import SessionSlideDeck, UserSession


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session
    engine.dispose()


def _attribution_module():
    """Fail as an assertion while the test-first production module is absent."""
    spec = importlib.util.find_spec("src.services.shared_deck_attribution")
    assert spec is not None, "shared-deck attribution seam is not implemented"
    return importlib.import_module("src.services.shared_deck_attribution")


def _event_model():
    import src.database.models.session as session_models

    model = getattr(session_models, "SharedDeckMutationEvent", None)
    assert model is not None, "shared-deck mutation aggregate is not implemented"
    return model


def _release(db, version: int, *, active: bool) -> GraphRelease:
    effective_from = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)
    release = GraphRelease(
        version_number=version,
        previous_release_id=None,
        restored_from_release_id=None,
        release_note=f"release {version}",
        published_by="test:shared-deck-attribution",
        published_at=effective_from,
        effective_from=effective_from,
        effective_to=None if active else effective_from + timedelta(seconds=1),
    )
    db.add(release)
    db.flush()
    return release


def _root_and_deck(db, *, session_id: str, release_id: int | None):
    root = UserSession(
        session_id=session_id,
        created_by="owner@example.com",
        graph_release_id=release_id,
    )
    db.add(root)
    db.flush()
    deck = SessionSlideDeck(session_id=root.id, title="Shared deck")
    db.add(deck)
    db.flush()
    return root, deck


def _record(db, *, requester, owner, deck, release_id, operation="save_deck", object_type="deck"):
    module = _attribution_module()
    return module.record_shared_deck_mutation(
        db,
        requesting_session=requester,
        deck_owner=owner,
        deck=deck,
        actor=module.MutationActor(
            actor_session_id=requester.session_id,
            graph_release_id=release_id,
        ),
        operation=operation,
        object_type=object_type,
        object_id="object-1",
    )


def test_root_actor_records_root_r1_identity_and_exact_release(db):
    """Break caught: a root write loses its three opaque snapshots or exact R1."""
    r1 = _release(db, 1, active=True)
    root, deck = _root_and_deck(db, session_id="root-r1", release_id=r1.id)

    event = _record(
        db,
        requester=root,
        owner=root,
        deck=deck,
        release_id=r1.id,
    )

    assert event.root_session_id == root.id
    assert event.root_deck_id == deck.id
    assert event.actor_session_id == root.id
    assert event.root_session_identity == root.collaboration_identity
    assert event.root_deck_identity == deck.collaboration_identity
    assert event.actor_session_identity == root.collaboration_identity
    assert (event.graph_release_id, event.graph_version) == (r1.id, 1)


def test_contributor_r2_uses_owner_root_but_actor_release(db):
    """Break caught: contributor evidence reads root identity from R2 or release from owner R1."""
    r1 = _release(db, 1, active=False)
    r2 = _release(db, 2, active=True)
    root, deck = _root_and_deck(db, session_id="owner-r1", release_id=r1.id)
    contributor = UserSession(
        session_id="contributor-r2",
        created_by="contributor@example.com",
        parent_session_id=root.id,
        graph_release_id=r2.id,
    )
    db.add(contributor)
    db.flush()

    event = _record(
        db,
        requester=contributor,
        owner=root,
        deck=deck,
        release_id=r2.id,
        operation="update_slide",
    )

    assert (event.root_session_id, event.root_session_identity) == (
        root.id,
        root.collaboration_identity,
    )
    assert (event.actor_session_id, event.actor_session_identity) == (
        contributor.id,
        contributor.collaboration_identity,
    )
    assert (event.graph_release_id, event.graph_version) == (r2.id, 2)


def test_null_pinned_actor_records_a_null_release_pair(db):
    """Break caught: legacy null provenance is inferred from an active release."""
    _release(db, 1, active=True)
    root, deck = _root_and_deck(db, session_id="legacy-root", release_id=None)

    event = _record(
        db,
        requester=root,
        owner=root,
        deck=deck,
        release_id=None,
    )

    assert event.graph_release_id is None
    assert event.graph_version is None


def test_actor_pin_mismatch_is_rejected_before_event_insert(db):
    """Break caught: caller-supplied provenance can disagree with the persisted actor pin."""
    r1 = _release(db, 1, active=False)
    r2 = _release(db, 2, active=True)
    root, deck = _root_and_deck(db, session_id="pinned-r1", release_id=r1.id)

    with pytest.raises(ValueError, match="pin"):
        _record(
            db,
            requester=root,
            owner=root,
            deck=deck,
            release_id=r2.id,
        )

    assert db.scalar(select(func.count()).select_from(_event_model())) == 0


def test_missing_actor_row_is_rejected(db):
    """Break caught: a detached/request-only actor is accepted without an exact DB row."""
    module = _attribution_module()
    root, deck = _root_and_deck(db, session_id="owner", release_id=None)
    missing = UserSession(id=9999, session_id="missing-actor", created_by="missing@example.com")

    with pytest.raises(ValueError, match="actor session"):
        module.record_shared_deck_mutation(
            db,
            requesting_session=missing,
            deck_owner=root,
            deck=deck,
            actor=module.MutationActor("missing-actor", None),
            operation="save_deck",
            object_type="deck",
            object_id=None,
        )


def test_missing_exact_release_is_rejected(db):
    """Break caught: a dangling actor pin falls back to active/latest release metadata."""
    _release(db, 1, active=True)
    root, deck = _root_and_deck(db, session_id="dangling-pin", release_id=9999)

    with pytest.raises(ValueError, match="Graph Release"):
        _record(
            db,
            requester=root,
            owner=root,
            deck=deck,
            release_id=9999,
        )


@pytest.mark.parametrize(
    ("operation", "object_type"),
    (("write_slide", "deck"), ("save_deck", "slide")),
)
def test_illegal_operation_object_pair_is_rejected(db, operation, object_type):
    """Break caught: a closed operation is recorded against the wrong object kind."""
    root, deck = _root_and_deck(db, session_id=f"illegal-{operation}", release_id=None)

    with pytest.raises(ValueError, match="operation/object"):
        _record(
            db,
            requester=root,
            owner=root,
            deck=deck,
            release_id=None,
            operation=operation,
            object_type=object_type,
        )


def test_opaque_uuid_snapshots_exist_without_sensitive_fields_and_recorder_does_not_commit(db):
    """Break caught: evidence stores identity/payload fields or commits the caller transaction."""
    root, deck = _root_and_deck(db, session_id="uuid-root", release_id=None)

    event = _record(
        db,
        requester=root,
        owner=root,
        deck=deck,
        release_id=None,
    )

    assert isinstance(root.collaboration_identity, uuid.UUID)
    assert isinstance(deck.collaboration_identity, uuid.UUID)
    assert isinstance(event.root_session_identity, uuid.UUID)
    assert isinstance(event.root_deck_identity, uuid.UUID)
    assert isinstance(event.actor_session_identity, uuid.UUID)
    columns = set(_event_model().__table__.columns.keys())
    assert not columns.intersection(
        {"principal", "created_by", "modified_by", "user_id", "payload", "prompt", "output", "html"}
    )
    assert event.id is not None

    db.rollback()
    assert db.scalar(select(func.count()).select_from(_event_model())) == 0


def test_orm_events_are_append_only(db):
    """Break caught: an application ORM path updates or deletes authoritative evidence."""
    root, deck = _root_and_deck(db, session_id="append-only", release_id=None)
    event = _record(
        db,
        requester=root,
        owner=root,
        deck=deck,
        release_id=None,
    )
    db.commit()
    event_id = event.id

    event.operation = "reorder_slides"
    with pytest.raises(ValueError, match="append-only"):
        db.flush()
    db.rollback()

    event = db.get(_event_model(), event_id)
    db.delete(event)
    with pytest.raises(ValueError, match="append-only"):
        db.flush()


def test_collaboration_identities_are_immutable_through_the_orm(db):
    """Break caught: an application update changes a stable session or deck grouping UUID."""
    root, deck = _root_and_deck(db, session_id="immutable-identities", release_id=None)
    db.commit()

    root.collaboration_identity = uuid.uuid4()
    with pytest.raises(ValueError, match="collaboration identity is immutable"):
        db.flush()
    db.rollback()

    deck = db.get(SessionSlideDeck, deck.id)
    deck.collaboration_identity = uuid.uuid4()
    with pytest.raises(ValueError, match="collaboration identity is immutable"):
        db.flush()
