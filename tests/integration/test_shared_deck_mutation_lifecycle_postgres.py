from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import sessionmaker

from src.api.routes import sessions as sessions_route
from src.api.services import session_manager as session_manager_module
from src.api.services.session_manager import SessionManager
from src.database.models.graph_configuration import GraphRelease
from src.database.models.profile_contributor import PermissionLevel
from src.database.models.session import (
    SessionSlideDeck,
    SharedDeckMutationEvent,
    UserSession,
)
from src.services.shared_deck_attribution import (
    MutationActor,
    record_shared_deck_mutation,
)

pytestmark = pytest.mark.postgres


def _factory_and_db_context(postgres_engine):
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)

    @contextmanager
    def database_session():
        with factory() as db:
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    return factory, database_session


def _release(db) -> GraphRelease:
    now = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)
    release = GraphRelease(
        version_number=17,
        previous_release_id=None,
        restored_from_release_id=None,
        release_note="lifecycle release",
        published_by="test:shared-deck-lifecycle",
        published_at=now,
        effective_from=now,
        effective_to=None,
    )
    db.add(release)
    db.flush()
    return release


def _root_and_deck(db, release, session_id: str, *, last_activity=None):
    root = UserSession(
        session_id=session_id,
        created_by=f"{session_id}@example.com",
        graph_release_id=release.id,
        last_activity=last_activity or datetime.utcnow(),
    )
    db.add(root)
    db.flush()
    deck = SessionSlideDeck(session_id=root.id, title=f"Deck for {session_id}")
    db.add(deck)
    db.flush()
    return root, deck


def _contributor(db, release, root, session_id: str, *, last_activity=None):
    actor = UserSession(
        session_id=session_id,
        created_by=f"{session_id}@example.com",
        graph_release_id=release.id,
        parent_session_id=root.id,
        last_activity=last_activity or datetime.utcnow(),
    )
    db.add(actor)
    db.flush()
    return actor


def _record_event(db, release, root, deck, actor) -> SharedDeckMutationEvent:
    return record_shared_deck_mutation(
        db,
        requesting_session=actor,
        deck_owner=root,
        deck=deck,
        actor=MutationActor(actor.session_id, release.id),
        operation="update_slide",
        object_type="deck",
        object_id="slide-3",
    )


def _immutable_event_state(event):
    return (
        event.root_session_identity,
        event.root_deck_identity,
        event.actor_session_identity,
        event.graph_release_id,
        event.graph_version,
        event.operation,
        event.object_type,
        event.object_id,
        event.occurred_at,
    )


def test_delete_route_removes_evidenced_root_and_keeps_opaque_event(postgres_engine):
    """Break caught: root deletion is rejected or destroys/anonymizes its evidence."""
    factory, database_session = _factory_and_db_context(postgres_engine)
    with factory.begin() as db:
        release = _release(db)
        release_id = release.id
        root, deck = _root_and_deck(db, release, "route-root")
        root_id, deck_id = root.id, deck.id
        event = _record_event(db, release, root, deck, root)
        event_id = event.id
        immutable_before = _immutable_event_state(event)
        root_identity = event.root_session_identity

    manager = SessionManager()
    with factory() as authorization_db, patch.object(
        session_manager_module, "get_db_session", database_session
    ), patch.object(sessions_route, "get_session_manager", return_value=manager), patch.object(
        sessions_route,
        "_require_session_access",
        return_value=PermissionLevel.CAN_MANAGE,
    ):
        response = asyncio.run(sessions_route.delete_session("route-root", db=authorization_db))

    assert response == {"status": "deleted", "session_id": "route-root"}
    with factory() as db:
        assert db.get(UserSession, root_id) is None
        assert db.get(SessionSlideDeck, deck_id) is None
        assert db.get(GraphRelease, release_id) is not None
        event = db.get(SharedDeckMutationEvent, event_id)
        assert event is not None
        assert (event.root_session_id, event.root_deck_id, event.actor_session_id) == (
            None,
            None,
            None,
        )
        assert _immutable_event_state(event) == immutable_before
        assert db.scalar(
            select(func.count(SharedDeckMutationEvent.id)).where(
                SharedDeckMutationEvent.root_session_identity == root_identity
            )
        ) == 1


def test_delete_evidenced_contributor_nulls_only_actor_link(postgres_engine):
    """Break caught: deleting an actor deletes or rewrites the root/deck evidence group."""
    factory, database_session = _factory_and_db_context(postgres_engine)
    with factory.begin() as db:
        release = _release(db)
        root, deck = _root_and_deck(db, release, "actor-owner")
        actor = _contributor(db, release, root, "evidenced-actor")
        root_id, deck_id, actor_id = root.id, deck.id, actor.id
        event = _record_event(db, release, root, deck, actor)
        event_id = event.id
        actor_identity = event.actor_session_identity
        immutable_before = _immutable_event_state(event)

    with patch.object(session_manager_module, "get_db_session", database_session):
        assert SessionManager().delete_session("evidenced-actor") is True

    with factory() as db:
        assert db.get(UserSession, actor_id) is None
        assert db.get(UserSession, root_id) is not None
        assert db.get(SessionSlideDeck, deck_id) is not None
        event = db.get(SharedDeckMutationEvent, event_id)
        assert (event.root_session_id, event.root_deck_id, event.actor_session_id) == (
            root_id,
            deck_id,
            None,
        )
        assert _immutable_event_state(event) == immutable_before
        assert db.scalar(
            select(func.count(SharedDeckMutationEvent.id)).where(
                SharedDeckMutationEvent.actor_session_identity == actor_identity
            )
        ) == 1


def test_delete_root_cascade_keeps_contributor_event(postgres_engine):
    """Break caught: root cascade deletes contributor-authored evidence with live rows."""
    factory, database_session = _factory_and_db_context(postgres_engine)
    with factory.begin() as db:
        release = _release(db)
        root, deck = _root_and_deck(db, release, "cascade-root")
        actor = _contributor(db, release, root, "cascade-contributor")
        root_id, deck_id, actor_id = root.id, deck.id, actor.id
        event = _record_event(db, release, root, deck, actor)
        event_id = event.id
        immutable_before = _immutable_event_state(event)

    with patch.object(session_manager_module, "get_db_session", database_session):
        assert SessionManager().delete_session("cascade-root") is True

    with factory() as db:
        assert db.get(UserSession, root_id) is None
        assert db.get(UserSession, actor_id) is None
        assert db.get(SessionSlideDeck, deck_id) is None
        event = db.get(SharedDeckMutationEvent, event_id)
        assert event is not None
        assert (event.root_session_id, event.root_deck_id, event.actor_session_id) == (
            None,
            None,
            None,
        )
        assert _immutable_event_state(event) == immutable_before


def test_cleanup_continues_after_failed_candidate_and_preserves_all_evidence(postgres_engine):
    """Break caught: a shared rollback leaves a later ordinary expiry undeleted."""
    factory, database_session = _factory_and_db_context(postgres_engine)
    old = datetime.utcnow() - timedelta(hours=48)
    with factory.begin() as db:
        release = _release(db)

        old_root, old_deck = _root_and_deck(
            db, release, "expired-evidenced-root", last_activity=old
        )
        root_event = _record_event(db, release, old_root, old_deck, old_root)

        fresh_root, fresh_deck = _root_and_deck(db, release, "fresh-owner")
        old_actor = _contributor(
            db, release, fresh_root, "expired-evidenced-actor", last_activity=old
        )
        actor_event = _record_event(db, release, fresh_root, fresh_deck, old_actor)

        failing = UserSession(session_id="expired-failing", last_activity=old)
        later = UserSession(session_id="expired-ordinary-later", last_activity=old)
        db.add_all((failing, later))
        db.flush()

        old_root_id = old_root.id
        old_actor_id = old_actor.id
        failing_id = failing.id
        later_id = later.id
        fresh_root_id = fresh_root.id
        root_event_id = root_event.id
        actor_event_id = actor_event.id
        root_event_before = _immutable_event_state(root_event)
        actor_event_before = _immutable_event_state(actor_event)

    with postgres_engine.begin() as conn:
        conn.execute(
            text(
                "CREATE FUNCTION reject_one_expired_session() RETURNS trigger "
                "LANGUAGE plpgsql AS $$ BEGIN "
                "IF OLD.id = :failing_id THEN "
                "RAISE EXCEPTION 'deliberate expiry failure'; "
                "END IF; RETURN OLD; END; $$"
            ),
            {"failing_id": failing_id},
        )
        conn.execute(
            text(
                "CREATE TRIGGER trg_reject_one_expired_session "
                "BEFORE DELETE ON user_sessions FOR EACH ROW "
                "EXECUTE FUNCTION reject_one_expired_session()"
            )
        )

    with patch.object(session_manager_module, "get_db_session", database_session):
        deleted_count = SessionManager(session_ttl_hours=24).cleanup_expired_sessions()

    assert deleted_count == 3
    with factory() as db:
        assert db.get(UserSession, old_root_id) is None
        assert db.get(UserSession, old_actor_id) is None
        assert db.get(UserSession, later_id) is None
        assert db.get(UserSession, failing_id) is not None
        assert db.get(UserSession, fresh_root_id) is not None

        root_event = db.get(SharedDeckMutationEvent, root_event_id)
        actor_event = db.get(SharedDeckMutationEvent, actor_event_id)
        assert root_event is not None
        assert actor_event is not None
        assert _immutable_event_state(root_event) == root_event_before
        assert _immutable_event_state(actor_event) == actor_event_before
        root_event_links = (
            root_event.root_session_id,
            root_event.root_deck_id,
            root_event.actor_session_id,
        )
        assert root_event_links == (
            None,
            None,
            None,
        )
        assert actor_event.root_session_id == fresh_root_id
        assert actor_event.root_deck_id == fresh_deck.id
        assert actor_event.actor_session_id is None
        assert db.scalar(select(func.count(SharedDeckMutationEvent.id))) == 2
