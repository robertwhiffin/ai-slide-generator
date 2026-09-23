"""Public graph-version projections for session responses."""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 -- register ORM tables before create_all
from src.api.services.session_manager import SessionManager
from src.core.database import Base
from src.database.models.graph_configuration import GraphRelease
from src.database.models.session import SessionMessage, UserSession
from src.services.conversation_pins import (
    ConversationGraphReleaseIntegrityError,
    PinnedRelease,
    get_conversation_graph_version,
    get_conversation_graph_versions,
)


@pytest.fixture
def factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def _database_context(factory):
    @contextlib.contextmanager
    def managed_session():
        db = factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return managed_session


def _seed_releases_and_sessions(factory):
    now = datetime.now(timezone.utc)
    with factory.begin() as db:
        historical = GraphRelease(
            version_number=1,
            release_note="historical test release",
            published_by="unit-test@example.com",
            published_at=now - timedelta(days=1),
            effective_from=now - timedelta(days=1),
            effective_to=now,
        )
        active = GraphRelease(
            version_number=2,
            previous_release_id=1,
            release_note="active test release",
            published_by="unit-test@example.com",
            published_at=now,
            effective_from=now,
        )
        db.add_all([historical, active])
        db.flush()
        db.add_all(
            [
                UserSession(
                    session_id="historical",
                    created_by="owner@example.com",
                    graph_release_id=historical.id,
                ),
                UserSession(
                    session_id="active",
                    created_by="owner@example.com",
                    graph_release_id=active.id,
                ),
                UserSession(
                    session_id="unpinned",
                    created_by="owner@example.com",
                    graph_release_id=None,
                ),
            ]
        )


def _assert_no_private_graph_fields(value):
    forbidden = {
        "graph_release_id",
        "release_id",
        "revision",
        "prompt",
        "endpoint",
        "schema",
    }
    if isinstance(value, dict):
        assert not (set(value) & forbidden)
        for nested in value.values():
            _assert_no_private_graph_fields(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_private_graph_fields(nested)


@pytest.mark.parametrize(
    ("session_id", "expected"),
    [
        ("historical", (1, 2, True)),
        ("active", (2, 2, False)),
        ("unpinned", (None, 2, False)),
    ],
)
def test_projection_uses_persisted_pin_and_exposes_only_public_version_fields(
    factory, session_id, expected
):
    """Replacing a persisted pin with latest would make the historical case lie."""
    _seed_releases_and_sessions(factory)

    with factory() as db:
        session = db.query(UserSession).filter_by(session_id=session_id).one()
        projection = get_conversation_graph_version(db, session)

    assert (
        projection.graph_version,
        projection.active_graph_version,
        projection.is_older_than_active,
    ) == expected
    _assert_no_private_graph_fields(projection.__dict__)


def test_missing_pinned_release_is_an_integrity_error(factory):
    """Falling back when graph identity is corrupt would misrepresent a conversation."""
    now = datetime.now(timezone.utc)
    with factory.begin() as db:
        db.add(
            GraphRelease(
                version_number=2,
                release_note="active test release",
                published_by="unit-test@example.com",
                published_at=now,
                effective_from=now,
            )
        )
        db.add(UserSession(session_id="missing-pinned", graph_release_id=999))

    with factory() as db:
        session = db.query(UserSession).filter_by(session_id="missing-pinned").one()
        with pytest.raises(ConversationGraphReleaseIntegrityError):
            get_conversation_graph_version(db, session)


def test_missing_active_release_is_an_integrity_error(factory):
    """A null pin must not turn a missing active release into a latest fallback."""
    with factory.begin() as db:
        db.add(UserSession(session_id="no-active", graph_release_id=None))

    with factory() as db:
        session = db.query(UserSession).filter_by(session_id="no-active").one()
        with pytest.raises(ConversationGraphReleaseIntegrityError):
            get_conversation_graph_version(db, session)


def test_non_integer_single_session_pin_is_an_integrity_error(factory):
    """Accepting a string pin would turn an invalid persisted identity into a lookup."""
    _seed_releases_and_sessions(factory)
    invalid_pin = UserSession(session_id="invalid-pin", graph_release_id="not-an-id")

    with factory() as db:
        with pytest.raises(ConversationGraphReleaseIntegrityError, match="invalid"):
            get_conversation_graph_version(db, invalid_pin)


def test_batch_projection_rejects_dangling_pinned_release(factory):
    """Treating an outer-join miss as null would silently unpin a corrupted session."""
    _seed_releases_and_sessions(factory)
    with factory.begin() as db:
        db.add(UserSession(session_id="batch-dangling", graph_release_id=999))

    with factory() as db:
        dangling = db.query(UserSession).filter_by(session_id="batch-dangling").one()
        with pytest.raises(ConversationGraphReleaseIntegrityError, match="missing pinned"):
            get_conversation_graph_versions(db, [dangling])


def test_batch_projection_rejects_requested_session_absent_from_rows(factory, monkeypatch):
    """Returning a partial batch would otherwise omit a requested session silently."""
    _seed_releases_and_sessions(factory)
    with factory() as db:
        requested = db.query(UserSession).filter_by(session_id="active").one()
        real_execute = db.execute
        execute_count = 0

        def execute(statement, *args, **kwargs):
            nonlocal execute_count
            execute_count += 1
            if execute_count == 2:
                return SimpleNamespace(all=lambda: [])
            return real_execute(statement, *args, **kwargs)

        monkeypatch.setattr(db, "execute", execute)
        with pytest.raises(ConversationGraphReleaseIntegrityError, match="missing session"):
            get_conversation_graph_versions(db, [requested])

    assert execute_count == 2


def test_create_get_and_list_merge_public_versions_without_private_identity(factory, monkeypatch):
    """Omitting any response path would make callers see inconsistent graph identity."""
    _seed_releases_and_sessions(factory)
    manager = SessionManager()
    monkeypatch.setattr(
        "src.api.services.session_manager.get_db_session", _database_context(factory)
    )
    monkeypatch.setattr(
        "src.api.services.session_manager.lock_active_graph_release",
        lambda db: PinnedRelease(release_id=2, graph_version=2),
    )

    created = manager.create_session(session_id="created", graph_capable=True)
    existing = manager.create_session(session_id="created", graph_capable=True)
    detail = manager.get_session("historical")

    with factory.begin() as db:
        listed = db.query(UserSession).filter_by(session_id="historical").one()
        db.add(SessionMessage(session_id=listed.id, role="user", content="include in list"))
    summaries = manager.list_sessions(created_by="owner@example.com")

    assert {
        key: created[key]
        for key in ("graph_version", "active_graph_version", "is_older_than_active")
    } == {"graph_version": 2, "active_graph_version": 2, "is_older_than_active": False}
    assert {
        key: existing[key]
        for key in ("graph_version", "active_graph_version", "is_older_than_active")
    } == {"graph_version": 2, "active_graph_version": 2, "is_older_than_active": False}
    assert {
        key: detail[key]
        for key in ("graph_version", "active_graph_version", "is_older_than_active")
    } == {"graph_version": 1, "active_graph_version": 2, "is_older_than_active": True}
    assert [
        (row["graph_version"], row["active_graph_version"], row["is_older_than_active"])
        for row in summaries
    ] == [(1, 2, True)]
    _assert_no_private_graph_fields([created, existing, detail, summaries])


def test_list_uses_one_active_lookup_and_one_pinned_outer_join(factory, monkeypatch):
    """A per-session release lookup would turn the session list into an N+1 query."""
    _seed_releases_and_sessions(factory)
    with factory.begin() as db:
        for session in db.query(UserSession).all():
            db.add(SessionMessage(session_id=session.id, role="user", content="list me"))

    monkeypatch.setattr(
        "src.api.services.session_manager.get_db_session", _database_context(factory)
    )
    statements: list[str] = []

    @event.listens_for(factory.kw["bind"], "before_cursor_execute")
    def record_queries(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    try:
        rows = SessionManager().list_sessions(created_by="owner@example.com")
    finally:
        event.remove(factory.kw["bind"], "before_cursor_execute", record_queries)

    assert len(rows) == 3
    graph_queries = [
        statement.upper()
        for statement in statements
        if "FROM GRAPH_RELEASE" in statement.upper()
        or "LEFT OUTER JOIN GRAPH_RELEASE" in statement.upper()
    ]
    assert len(graph_queries) == 2
    assert sum("LEFT OUTER JOIN GRAPH_RELEASE" in statement for statement in graph_queries) == 1
    assert (
        sum(
            "FROM GRAPH_RELEASE" in statement and "JOIN" not in statement
            for statement in graph_queries
        )
        == 1
    )
