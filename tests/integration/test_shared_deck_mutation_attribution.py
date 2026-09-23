"""Behavioral coverage for the transactional deck-writer attribution seam.

These tests use real SQLAlchemy transactions.  The only substituted boundary is
``get_db_session`` so every production writer shares the test database.
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 - register all mappings
from src.api.services.chat_service import ChatService
from src.api.services.deck_level_writer import write_deck_level_columns
from src.api.services.session_manager import SessionManager
from src.api.services.slide_repository import SlideWriter
from src.core.database import Base
from src.database.models.graph_configuration import GraphRelease
from src.database.models.session import (
    SessionMessage,
    SessionSlide,
    SessionSlideDeck,
    SharedDeckMutationEvent,
    SlideDeckVersion,
    UserSession,
)
from src.services.graph.nodes import placeholder_node
from src.services.graph.state import scoped
from src.services.shared_deck_attribution import (
    DeckMutationContext,
    MutationActor,
)


@pytest.fixture()
def writer_env(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    @contextlib.contextmanager
    def db_session():
        db = factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    for target in (
        "src.api.services.session_manager.get_db_session",
        "src.api.services.slide_repository.get_db_session",
        "src.api.services.deck_level_writer.get_db_session",
    ):
        monkeypatch.setattr(target, db_session)

    effective = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)
    with factory() as db:
        r1 = GraphRelease(
            version_number=101,
            release_note="R1",
            published_by="test",
            published_at=effective,
            effective_from=effective,
            effective_to=effective + timedelta(seconds=1),
        )
        r2 = GraphRelease(
            version_number=202,
            release_note="R2",
            published_by="test",
            published_at=effective,
            effective_from=effective + timedelta(seconds=1),
            effective_to=None,
        )
        db.add_all([r1, r2])
        db.flush()
        root = UserSession(
            session_id="root-r1",
            created_by="owner@example.com",
            graph_release_id=r1.id,
        )
        db.add(root)
        db.flush()
        contributor = UserSession(
            session_id="contributor-r2",
            created_by="contributor@example.com",
            parent_session_id=root.id,
            graph_release_id=r2.id,
        )
        legacy = UserSession(
            session_id="legacy-null",
            created_by="legacy@example.com",
            graph_release_id=None,
        )
        db.add_all([contributor, legacy])
        db.commit()
        ids = {
            "root_pk": root.id,
            "root_identity": root.collaboration_identity,
            "contributor_pk": contributor.id,
            "contributor_identity": contributor.collaboration_identity,
            "r1": r1.id,
            "r2": r2.id,
        }

    yield factory, ids
    engine.dispose()


def _deck(slides):
    return {
        "title": "Shared",
        "css": ".slide{}",
        "external_scripts": [],
        "head_meta": {},
        "slides": slides,
    }


def _events(factory):
    with factory() as db:
        return list(
            db.scalars(
                select(SharedDeckMutationEvent).order_by(
                    SharedDeckMutationEvent.id
                )
            )
        )


def _seed_direct_deck(factory):
    slides = [
        {"slide_id": "slide-a", "html": '<div class="slide">A</div>'},
        {"slide_id": "slide-b", "html": '<div class="slide">B</div>'},
        {"slide_id": "slide-c", "html": '<div class="slide">C</div>'},
    ]
    SessionManager().save_slide_deck(
        "contributor-r2",
        "Shared",
        "".join(slide["html"] for slide in slides),
        slide_count=3,
        deck_dict=_deck(slides),
    )
    with factory() as db:
        db.query(SharedDeckMutationEvent).delete()
        db.commit()


def _run_direct(service, operation):
    if operation == "insert_slide":
        return service.insert_slide(
            "contributor-r2", 1, html='<div class="slide">new</div>'
        )
    if operation == "update_slide":
        return service.update_slide(
            "contributor-r2", 1, '<div class="slide">updated</div>'
        )
    if operation == "duplicate_slide":
        return service.duplicate_slide("contributor-r2", 1)
    if operation == "delete_slide":
        return service.delete_slide("contributor-r2", 1)
    if operation == "reorder_slides":
        return service.reorder_slides("contributor-r2", [2, 0, 1])
    raise AssertionError(operation)


def test_monolith_save_records_literal_root_r1_event_order(writer_env):
    """Break caught: full-deck save omits or reorders deck/slides evidence."""
    factory, ids = writer_env
    SessionManager().save_slide_deck(
        "root-r1",
        "Shared",
        '<div class="slide">one</div>',
        slide_count=1,
        deck_dict=_deck(
            [{"slide_id": "slide-one", "html": '<div class="slide">one</div>'}]
        ),
    )

    events = _events(factory)
    assert [event.operation for event in events] == ["save_deck", "save_deck_slides"]
    assert [event.object_type for event in events] == ["deck", "deck"]
    assert [event.object_id for event in events] == [None, None]
    assert len(events) == 2
    for event in events:
        assert event.root_session_id == ids["root_pk"]
        assert event.actor_session_id == ids["root_pk"]
        assert event.root_session_identity == ids["root_identity"]
        assert event.actor_session_identity == ids["root_identity"]
        assert (event.graph_release_id, event.graph_version) == (ids["r1"], 101)


def test_contributor_named_save_uses_root_r1_actor_r2_and_no_generic_event(writer_env):
    """Break caught: direct contributor mutation uses owner release or duplicates evidence."""
    factory, ids = writer_env
    mutation = DeckMutationContext(
        actor=MutationActor("contributor-r2", ids["r2"]),
        operation="insert_slide",
        object_type="deck",
        object_id="slide-new",
        suppress_nested_events=True,
    )
    SessionManager().save_slide_deck(
        "contributor-r2",
        "Shared",
        '<div class="slide">new</div>',
        slide_count=1,
        deck_dict=_deck(
            [{"slide_id": "slide-new", "html": '<div class="slide">new</div>'}]
        ),
        mutation=mutation,
    )

    [event] = _events(factory)
    assert (event.operation, event.object_type, event.object_id) == (
        "insert_slide",
        "deck",
        "slide-new",
    )
    assert (event.root_session_id, event.actor_session_id) == (
        ids["root_pk"],
        ids["contributor_pk"],
    )
    assert event.actor_session_identity == ids["contributor_identity"]
    assert (event.graph_release_id, event.graph_version) == (ids["r2"], 202)


def test_unsuppressed_context_keeps_named_and_nested_monolith_events(writer_env):
    """Break caught: suppress_nested_events is an inert flag on the public seam."""
    factory, ids = writer_env
    mutation = DeckMutationContext(
        actor=MutationActor("root-r1", ids["r1"]),
        operation="update_slide",
        object_type="deck",
        object_id="slide-one",
        suppress_nested_events=False,
    )
    SessionManager().save_slide_deck(
        "root-r1",
        "Shared",
        '<div class="slide">one</div>',
        slide_count=1,
        deck_dict=_deck(
            [{"slide_id": "slide-one", "html": '<div class="slide">one</div>'}]
        ),
        mutation=mutation,
    )

    assert [event.operation for event in _events(factory)] == [
        "update_slide",
        "save_deck",
        "save_deck_slides",
    ]


def test_row_and_deck_writers_record_stable_slide_id_and_legacy_null(writer_env):
    """Break caught: row/deck writers commit content without their explicit context."""
    factory, ids = writer_env
    SessionManager().save_slide_deck(
        "legacy-null", "Legacy", "", deck_dict=None
    )
    baseline_count = len(_events(factory))

    SlideWriter().write_slide(
        "legacy-null",
        0,
        '<div class="slide">legacy</div>',
        slide_id="stable-slide",
        mutation=DeckMutationContext(
            actor=MutationActor("legacy-null", None),
            operation="write_slide",
            object_type="slide",
            object_id="stable-slide",
        ),
    )
    write_deck_level_columns(
        "legacy-null",
        title="Legacy renamed",
        mutation=DeckMutationContext(
            actor=MutationActor("legacy-null", None),
            operation="write_deck_level",
            object_type="deck",
        ),
    )

    events = _events(factory)[baseline_count:]
    assert [
        (event.operation, event.object_type, event.object_id)
        for event in events
    ] == [
        ("write_slide", "slide", "stable-slide"),
        ("write_deck_level", "deck", None),
    ]
    assert [(event.graph_release_id, event.graph_version) for event in events] == [
        (None, None),
        (None, None),
    ]


def test_event_failure_rolls_back_slide_content(writer_env, monkeypatch):
    """Break caught: event insert failure leaves the row committed by itself."""
    factory, ids = writer_env

    def fail_event(*args, **kwargs):
        raise RuntimeError("event insert failed")

    monkeypatch.setattr(
        "src.api.services.slide_repository.record_shared_deck_mutation", fail_event
    )
    with pytest.raises(RuntimeError, match="event insert failed"):
        SlideWriter().write_slide(
            "root-r1",
            0,
            '<div class="slide">must roll back</div>',
            slide_id="rollback-slide",
            mutation=DeckMutationContext(
                actor=MutationActor("root-r1", ids["r1"]),
                operation="write_slide",
                object_type="slide",
                object_id="rollback-slide",
            ),
        )

    with factory() as db:
        assert db.scalar(select(SessionSlide)) is None
        assert db.scalar(select(SharedDeckMutationEvent)) is None


def test_row_delete_records_stable_slide_id_and_contributor_release(writer_env):
    """Break caught: the row-deletion seam loses its pre-delete object identity."""
    factory, ids = writer_env
    _seed_direct_deck(factory)

    SlideWriter().delete_slide(
        "contributor-r2",
        1,
        mutation=DeckMutationContext(
            actor=MutationActor("contributor-r2", ids["r2"]),
            operation="delete_slide",
            object_type="slide",
        ),
    )

    [event] = _events(factory)
    assert (event.operation, event.object_type, event.object_id) == (
        "delete_slide",
        "slide",
        "slide-b",
    )
    assert (event.root_session_id, event.actor_session_id) == (
        ids["root_pk"],
        ids["contributor_pk"],
    )
    assert (event.graph_release_id, event.graph_version) == (ids["r2"], 202)
    with factory() as db:
        deleted = db.scalar(
            select(SessionSlide).where(SessionSlide.slide_id == "slide-b")
        )
        assert deleted is None


def test_row_delete_event_failure_rolls_back_deleted_slide(writer_env, monkeypatch):
    """Break caught: row deletion commits when its evidence insert is rejected."""
    factory, ids = writer_env
    _seed_direct_deck(factory)

    def fail_event(*args, **kwargs):
        raise RuntimeError("delete event failed")

    monkeypatch.setattr(
        "src.api.services.slide_repository.record_shared_deck_mutation", fail_event
    )
    with pytest.raises(RuntimeError, match="delete event failed"):
        SlideWriter().delete_slide(
            "contributor-r2",
            1,
            mutation=DeckMutationContext(
                actor=MutationActor("contributor-r2", ids["r2"]),
                operation="delete_slide",
                object_type="slide",
            ),
        )

    with factory() as db:
        row = db.scalar(
            select(SessionSlide).where(SessionSlide.slide_id == "slide-b")
        )
        assert row is not None
        assert db.scalar(select(SharedDeckMutationEvent)) is None


@pytest.mark.parametrize(
    ("operation", "object_id"),
    [
        ("insert_slide", None),
        ("update_slide", "slide-b"),
        ("duplicate_slide", None),
        ("delete_slide", "slide-b"),
        ("reorder_slides", None),
    ],
)
def test_direct_crud_records_exactly_one_named_contributor_event(
    writer_env, operation, object_id
):
    """Break caught: direct CRUD emits generic nested events or loses R2."""
    factory, ids = writer_env
    _seed_direct_deck(factory)
    _run_direct(ChatService(), operation)

    [event] = _events(factory)
    assert (event.operation, event.object_type) == (operation, "deck")
    if object_id is not None:
        assert event.object_id == object_id
    elif operation == "reorder_slides":
        assert event.object_id is None
    else:
        assert event.object_id not in {None, "slide-a", "slide-b", "slide-c"}
    assert (event.root_session_id, event.actor_session_id) == (
        ids["root_pk"],
        ids["contributor_pk"],
    )
    assert (event.graph_release_id, event.graph_version) == (ids["r2"], 202)


@pytest.mark.parametrize(
    ("operation", "expected_object_id"),
    [
        ("insert_slide", "direct-new-slide"),
        ("update_slide", "slide-b"),
        ("duplicate_slide", "direct-new-slide"),
        ("delete_slide", "slide-b"),
        ("reorder_slides", None),
    ],
)
def test_direct_event_failure_rolls_back_and_stops_followup_work(
    writer_env, monkeypatch, operation, expected_object_id
):
    """Break caught: rejected evidence leaves content or reaches spec/savepoint work."""
    factory, ids = writer_env
    _seed_direct_deck(factory)
    monkeypatch.setattr(
        "src.api.services.chat_service.uuid.uuid4",
        lambda: "direct-new-slide",
    )
    with factory() as db:
        before_deck = SessionManager().get_slide_deck("root-r1")
        before_rows = [
            (row.position, row.slide_id, row.html)
            for row in db.scalars(select(SessionSlide).order_by(SessionSlide.position))
        ]
        before_version = SessionManager().get_slide_deck_version("root-r1")

    def fail_event(*args, **kwargs):
        assert kwargs["operation"] == operation
        assert kwargs["object_type"] == "deck"
        assert kwargs["object_id"] == expected_object_id
        assert kwargs["actor"] == MutationActor("contributor-r2", ids["r2"])
        raise RuntimeError("event insert failed")

    def forbidden(*args, **kwargs):
        raise AssertionError("follow-up work ran after event failure")

    monkeypatch.setattr(
        "src.api.services.session_manager.record_shared_deck_mutation", fail_event
    )
    service = ChatService()
    monkeypatch.setattr(service, "create_save_point", forbidden)
    monkeypatch.setattr(service, "_rewrite_deck_spec_slides", forbidden)

    with pytest.raises(RuntimeError, match="event insert failed"):
        _run_direct(service, operation)

    with factory() as db:
        after_rows = [
            (row.position, row.slide_id, row.html)
            for row in db.scalars(select(SessionSlide).order_by(SessionSlide.position))
        ]
    assert after_rows == before_rows
    assert SessionManager().get_slide_deck_version("root-r1") == before_version
    assert SessionManager().get_slide_deck("root-r1") == before_deck
    assert _events(factory) == []


@pytest.mark.parametrize(
    "operation",
    ["insert_slide", "duplicate_slide", "delete_slide", "reorder_slides"],
)
def test_spec_rewrite_failure_keeps_content_and_exactly_one_named_event(
    writer_env, monkeypatch, operation
):
    """Break caught: best-effort spec repair rolls back or double-counts CRUD."""
    factory, ids = writer_env
    _seed_direct_deck(factory)
    with factory() as db:
        deck = db.scalar(select(SessionSlideDeck))
        deck.deck_spec_json = (
            '{"title":"Shared","slides":['
            '{"position":0},{"position":1},{"position":2}]}'
        )
        db.commit()
    before_version = SessionManager().get_slide_deck_version("root-r1")

    def fail_spec_write(*args, **kwargs):
        raise RuntimeError("spec rewrite failed")

    monkeypatch.setattr(
        "src.api.services.deck_level_writer.write_deck_level_columns",
        fail_spec_write,
    )
    result = _run_direct(ChatService(), operation)

    assert result is not None
    [event] = _events(factory)
    assert (event.operation, event.object_type) == (operation, "deck")
    assert (event.root_session_id, event.actor_session_id) == (
        ids["root_pk"],
        ids["contributor_pk"],
    )
    assert SessionManager().get_slide_deck_version("root-r1") == before_version + 1


def _seed_restore_state(factory):
    manager = SessionManager()
    manager.save_slide_deck(
        "contributor-r2",
        "Current",
        '<div class="slide">current</div>',
        slide_count=1,
        deck_dict=_deck(
            [
                {
                    "slide_id": "current-slide",
                    "html": '<div class="slide">current</div>',
                }
            ]
        ),
    )
    with factory() as db:
        root = db.scalar(select(UserSession).where(UserSession.session_id == "root-r1"))
        contributor = db.scalar(
            select(UserSession).where(UserSession.session_id == "contributor-r2")
        )
        now = datetime.utcnow()
        db.add_all(
            [
                SlideDeckVersion(
                    session_id=root.id,
                    version_number=1,
                    description="target",
                    deck_json=(
                        '{"title":"Restored","slides":['
                        '{"slide_id":"restored-slide",'
                        '"html":"<div class=\\"slide\\">restored</div>"}]}'
                    ),
                    verification_map_json="{}",
                    chat_history_json="[]",
                    created_at=now - timedelta(minutes=2),
                ),
                SlideDeckVersion(
                    session_id=root.id,
                    version_number=2,
                    description="newer",
                    deck_json='{"title":"Current","slides":[]}',
                    verification_map_json="{}",
                    chat_history_json="[]",
                    created_at=now - timedelta(minutes=1),
                ),
                SessionMessage(
                    session_id=contributor.id,
                    role="user",
                    content="newer message",
                    created_at=now,
                ),
            ]
        )
        db.query(SharedDeckMutationEvent).delete()
        db.commit()


def _restore_snapshot(factory):
    with factory() as db:
        deck = db.scalar(select(SessionSlideDeck))
        rows = list(db.scalars(select(SessionSlide).order_by(SessionSlide.position)))
        return {
            "deck": (deck.title, deck.deck_json, deck.version),
            "rows": [(row.position, row.slide_id, row.html) for row in rows],
            "versions": list(
                db.scalars(select(SlideDeckVersion.version_number).order_by(SlideDeckVersion.version_number))
            ),
            "messages": list(db.scalars(select(SessionMessage.content))),
            "events": len(list(db.scalars(select(SharedDeckMutationEvent)))),
        }


def test_restore_records_contributor_r2_event_inside_restore_transaction(
    writer_env, monkeypatch
):
    """Break caught: restore commits content/deletions without exact actor evidence."""
    factory, ids = writer_env
    _seed_restore_state(factory)
    monkeypatch.setattr(SessionManager, "require_editing_lock", lambda *args: None)
    monkeypatch.setattr("src.services.spec_sync.discard_marker", lambda *args: None)

    result = SessionManager().restore_version("contributor-r2", 1)

    assert result["version_number"] == 1
    [event] = _events(factory)
    assert (event.operation, event.object_type, event.object_id) == (
        "restore_version",
        "deck",
        None,
    )
    assert (event.root_session_id, event.actor_session_id) == (
        ids["root_pk"],
        ids["contributor_pk"],
    )
    assert (event.graph_release_id, event.graph_version) == (ids["r2"], 202)
    snapshot = _restore_snapshot(factory)
    assert snapshot["rows"] == [
        (0, "restored-slide", '<div class="slide">restored</div>')
    ]
    assert snapshot["versions"] == [1]
    assert snapshot["messages"] == []


def test_restore_event_failure_rolls_back_content_deletions_and_event(
    writer_env, monkeypatch
):
    """Break caught: restore evidence runs after its content transaction commits."""
    factory, _ids = writer_env
    _seed_restore_state(factory)
    before = _restore_snapshot(factory)
    monkeypatch.setattr(SessionManager, "require_editing_lock", lambda *args: None)
    monkeypatch.setattr("src.services.spec_sync.discard_marker", lambda *args: None)

    def fail_event(*args, **kwargs):
        raise RuntimeError("restore event failed")

    monkeypatch.setattr(
        "src.api.services.session_manager.record_shared_deck_mutation", fail_event
    )
    with pytest.raises(RuntimeError, match="restore event failed"):
        SessionManager().restore_version("contributor-r2", 1)

    assert _restore_snapshot(factory) == before


def test_graph_turn_records_deck_rows_deck_with_exact_root_actor_release(graph_turn_env):
    """Break caught: any graph writer bypasses the explicit provenance seam."""
    graph_turn_env.run()
    with graph_turn_env.factory() as db:
        events = list(
            db.scalars(
                select(SharedDeckMutationEvent).order_by(SharedDeckMutationEvent.id)
            )
        )
        root = db.scalar(
            select(UserSession).where(
                UserSession.session_id == graph_turn_env.session_id
            )
        )
        deck = db.scalar(
            select(SessionSlideDeck).where(SessionSlideDeck.session_id == root.id)
        )

    assert [event.operation for event in events] == [
        "write_deck_level",
        "write_slide",
        "write_slide",
        "write_slide",
        "write_deck_level",
    ]
    assert [event.object_type for event in events] == [
        "deck",
        "slide",
        "slide",
        "slide",
        "deck",
    ]
    assert events[0].object_id is None
    assert events[-1].object_id is None
    assert sorted(event.object_id for event in events[1:-1]) == sorted(
        row.slide_id for row in graph_turn_env.rows()
    )
    for event in events:
        assert (event.root_session_id, event.root_deck_id, event.actor_session_id) == (
            root.id,
            deck.id,
            root.id,
        )
        assert (event.graph_release_id, event.graph_version) == (
            graph_turn_env.graph_release_id,
            1,
        )


def test_builder_failure_placeholder_has_exact_graph_actor(graph_turn_env):
    """Break caught: the failure placeholder drops mutation context forwarding."""
    graph_turn_env.recorder.configure(slide_count=1, fail_positions={0})
    graph_turn_env.run()

    with graph_turn_env.factory() as db:
        events = list(
            db.scalars(
                select(SharedDeckMutationEvent).order_by(SharedDeckMutationEvent.id)
            )
        )
    assert [event.operation for event in events] == [
        "write_deck_level",
        "write_slide",
        "write_deck_level",
    ]
    assert events[1].object_id == graph_turn_env.rows()[0].slide_id
    assert (events[1].graph_release_id, events[1].graph_version) == (
        graph_turn_env.graph_release_id,
        1,
    )


@pytest.mark.parametrize("failing_agent", ["build_reviewer", "fixer", "fix_reviewer"])
def test_reviewer_and_fixer_failures_keep_exact_row_attribution(
    graph_turn_env, monkeypatch, failing_agent
):
    """Break caught: a fallback row path forgets the branch actor context."""
    recorder = graph_turn_env.recorder
    recorder.configure(
        slide_count=1,
        objective_findings_at={0} if failing_agent != "build_reviewer" else set(),
    )
    real_run = recorder.run

    def run(agent_key, graph_release_id, payload, assembly_context):
        if agent_key == failing_agent:
            raise RuntimeError(f"{failing_agent} failed")
        return real_run(agent_key, graph_release_id, payload, assembly_context)

    monkeypatch.setattr(recorder, "run", run)
    graph_turn_env.run()

    with graph_turn_env.factory() as db:
        events = list(
            db.scalars(
                select(SharedDeckMutationEvent).order_by(SharedDeckMutationEvent.id)
            )
        )
    assert [event.operation for event in events] == [
        "write_deck_level",
        "write_slide",
        "write_deck_level",
    ]
    assert [event.object_type for event in events] == ["deck", "slide", "deck"]
    assert events[1].object_id == graph_turn_env.rows()[0].slide_id
    assert (events[1].graph_release_id, events[1].graph_version) == (
        graph_turn_env.graph_release_id,
        1,
    )


def test_stalled_placeholder_records_one_stable_slide_event(graph_turn_env):
    """Break caught: placeholder_node calls commit_placeholder without context."""
    graph_turn_env.recorder.configure(slide_count=1)
    graph_turn_env.run()
    before = len(graph_turn_env.rows())

    result = placeholder_node(
        {
            "session_id": graph_turn_env.session_id,
            "graph_release_id": graph_turn_env.graph_release_id,
            "turn_id": "stalled-turn",
            "dispatched_at": scoped("stalled-turn", {before: 0.0}),
            "landed_positions": scoped("stalled-turn", set()),
            "placeheld_positions": scoped("stalled-turn", set()),
            "foreman_wakes": scoped("stalled-turn", []),
        }
    )

    assert result == {"placeheld_positions": scoped("stalled-turn", {before})}
    with graph_turn_env.factory() as db:
        event = db.scalars(
            select(SharedDeckMutationEvent).order_by(SharedDeckMutationEvent.id.desc())
        ).first()
    assert (event.operation, event.object_type) == ("write_slide", "slide")
    assert event.object_id == graph_turn_env.rows()[-1].slide_id
    assert (event.graph_release_id, event.graph_version) == (
        graph_turn_env.graph_release_id,
        1,
    )


def test_duplicate_session_private_deck_is_not_a_shared_mutation(writer_env):
    """C-5: copying into a fresh private aggregate does not mutate the source."""
    factory, _ids = writer_env
    _seed_direct_deck(factory)

    result = SessionManager().duplicate_session("root-r1", "copy@example.com")

    assert result["source_session_id"] == "root-r1"
    assert _events(factory) == []


def test_read_time_legacy_authorship_repair_emits_no_user_event(writer_env):
    """C-7: one-time read migration is content repair, not a user mutation."""
    factory, _ids = writer_env
    _seed_direct_deck(factory)
    with factory() as db:
        deck = db.scalar(select(SessionSlideDeck))
        deck.deck_json = (
            '{"title":"Legacy","slides":['
            '{"slide_id":"legacy-slide","html":"<div class=\\"slide\\">x</div>"}]}'
        )
        db.query(SessionSlide).delete()
        db.commit()

    repaired = SessionManager().get_slide_deck("root-r1")

    assert repaired["slides"][0]["created_by"] == "owner@example.com"
    assert _events(factory) == []
