from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.orm import sessionmaker

from src.database.models.graph_configuration import GraphRelease
from src.database.models.session import UserSession
from src.services.conversation_pins import lock_active_graph_release
from tests.integration.postgres_concurrency_helpers import _WAIT_SECONDS, _await_lock_waiters

pytestmark = pytest.mark.postgres


def _release(version_number: int, *, active: bool = True) -> GraphRelease:
    now = datetime.now(timezone.utc)
    return GraphRelease(
        version_number=version_number,
        release_note=f"release {version_number}",
        published_by="conversation-pin-test@example.com",
        published_at=now,
        effective_from=now,
        effective_to=None if active else now + timedelta(seconds=1),
    )


def _pin_for(factory, session_id: str) -> int:
    with factory() as db:
        return db.scalar(
            select(UserSession.graph_release_id).where(UserSession.session_id == session_id)
        )


def _await_specific_lock_waiter(engine, pid: int) -> bool:
    """Observe this backend waiting from a separate observer connection."""
    deadline = time.monotonic() + _WAIT_SECONDS
    while time.monotonic() < deadline:
        with engine.connect() as observer:
            waiting = observer.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                    "WHERE datname = current_database() AND pid = :pid "
                    "AND wait_event_type = 'Lock')"
                ),
                {"pid": pid},
            )
        if waiting:
            return True
        time.sleep(0.02)
    return False


def test_publication_first_retries_after_active_row_changes_before_lock(
    postgres_engine,
):
    """The first scan may see R1 before publication, then lock the post-publication R2."""
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    with factory.begin() as db:
        r1 = _release(1)
        db.add(r1)
        db.flush()
        r1_id = r1.id

    publisher_has_r1_lock = threading.Event()
    release_publisher = threading.Event()
    pids: dict[str, int] = {}
    scans: list[int] = []

    @event.listens_for(postgres_engine, "before_cursor_execute")
    def count_creator_active_scans(_conn, _cursor, statement, _params, _ctx, _many):
        if (
            threading.current_thread().name == "creator"
            and "FROM graph_release" in statement
            and "FOR UPDATE" in statement
        ):
            scans.append(1)

    def create_root():
        threading.current_thread().name = "creator"
        with factory.begin() as db:
            pids["creator"] = db.scalar(text("SELECT pg_backend_pid()"))
            pinned = lock_active_graph_release(db)
            db.add(UserSession(session_id="publication-first", graph_release_id=pinned.release_id))
            db.flush()
            return pinned

    def publish_replacement():
        threading.current_thread().name = "publisher"
        with factory.begin() as db:
            pids["publisher"] = db.scalar(text("SELECT pg_backend_pid()"))
            r1 = db.scalar(
                select(GraphRelease)
                .where(GraphRelease.version_number == 1)
                .with_for_update()
            )
            publisher_has_r1_lock.set()
            assert release_publisher.wait(timeout=20), "creator was never observed waiting"
            r1.effective_to = datetime.now(timezone.utc) + timedelta(seconds=1)
            r2 = _release(2)
            db.add(r2)
            db.flush()
            return r2.id

    with ThreadPoolExecutor(max_workers=2) as pool:
        publisher = pool.submit(publish_replacement)
        assert publisher_has_r1_lock.wait(timeout=10), "publisher did not lock R1"
        creator = pool.submit(create_root)
        deadline = time.monotonic() + 10
        while "creator" not in pids and time.monotonic() < deadline:
            time.sleep(0.02)
        assert _await_specific_lock_waiter(postgres_engine, pids["creator"])
        assert _await_lock_waiters(postgres_engine, 1) >= 1
        assert pids["creator"] != pids["publisher"]
        release_publisher.set()
        r2_id = publisher.result(timeout=20)
        pinned = creator.result(timeout=20)

    event.remove(postgres_engine, "before_cursor_execute", count_creator_active_scans)
    assert scans == [1, 1]
    assert pinned.release_id == r2_id
    assert r2_id != r1_id
    assert pinned.graph_version == 2
    assert _pin_for(factory, "publication-first") == pinned.release_id


def test_creation_first_holds_active_release_lock_until_pinned_root_commits(postgres_engine):
    """A publisher must wait while creation owns R1's row lock and flushes its root."""
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    with factory.begin() as db:
        r1 = _release(1)
        db.add(r1)
        db.flush()
        r1_id = r1.id

    created_and_flushed = threading.Event()
    allow_creator_commit = threading.Event()
    publisher_started = threading.Event()
    pids: dict[str, int] = {}
    created_pin: dict[str, int] = {}

    def create_root():
        threading.current_thread().name = "creator"
        with factory.begin() as db:
            pids["creator"] = db.scalar(text("SELECT pg_backend_pid()"))
            pinned = lock_active_graph_release(db)
            created_pin["id"] = pinned.release_id
            db.add(UserSession(session_id="creation-first", graph_release_id=pinned.release_id))
            db.flush()
            created_and_flushed.set()
            assert allow_creator_commit.wait(timeout=20)
            return pinned

    def publish():
        threading.current_thread().name = "publisher"
        with factory.begin() as db:
            pids["publisher"] = db.scalar(text("SELECT pg_backend_pid()"))
            publisher_started.set()
            r1 = db.scalar(
                select(GraphRelease)
                .where(GraphRelease.version_number == 1)
                .with_for_update()
            )
            r1.effective_to = datetime.now(timezone.utc) + timedelta(seconds=1)
            db.add(_release(2))

    with ThreadPoolExecutor(max_workers=2) as pool:
        creator = pool.submit(create_root)
        assert created_and_flushed.wait(timeout=10), "creator did not lock and flush R1 root"
        publisher = pool.submit(publish)
        assert publisher_started.wait(timeout=10), "publisher did not start"
        assert _await_specific_lock_waiter(postgres_engine, pids["publisher"])
        assert _await_lock_waiters(postgres_engine, 1) >= 1
        assert pids["creator"] != pids["publisher"]
        allow_creator_commit.set()
        pinned = creator.result(timeout=20)
        publisher.result(timeout=20)

    assert pinned.release_id == r1_id == created_pin["id"]
    assert pinned.graph_version == 1
    assert _pin_for(factory, "creation-first") == created_pin["id"]
    with factory() as db:
        active = db.scalar(select(GraphRelease).where(GraphRelease.effective_to.is_(None)))
    assert active.version_number == 2
    assert active.id != r1_id
