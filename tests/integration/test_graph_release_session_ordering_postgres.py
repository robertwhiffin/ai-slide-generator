"""#269 Task 3: conversation creation versus real publication, every creator.

The real ``publish_draft`` and every graph-capable creator linearize at the
active ``graph_release`` row, in both lock orders.  No production code is
exercised through a fake: the publisher is ``GraphConfiguration.publish_draft``
and each creator is the production entry point driven by
``test_mixed_release_creation_postgres._create``.

Harness rules (Corrections 5, 6, 8-3):

* Creator PIDs are captured with the ``before_cursor_execute`` recipe on the
  creator's ``FROM graph_release … FOR UPDATE`` statement; the publisher's PID
  is captured the same way on its first statement, so a publisher that never
  enters ``_lock_current_parents`` is still observable.
* The publisher pause fires after the publisher thread's *first* statement
  containing ``FOR UPDATE`` (no table filter); the partial-release variant
  pauses after ``UPDATE GRAPH_DRAFT SET`` instead.
* Every statement on a named thread runs under ``SET LOCAL lock_timeout``,
  every wait is bounded, and every pause is released in an inner ``finally``
  before the executor joins, so a broken ordering goes RED instead of hanging.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.orm import sessionmaker

from src.api.services.session_manager import SessionManager
from src.database.models.graph_configuration import GraphRelease
from src.database.models.session import SessionMessage, SessionSlideDeck, UserSession
from src.domain.conversation_engine import AGENT_MODE_PHRASE
from src.services.conversation_pins import (
    ConversationGraphVersion,
    get_conversation_graph_version,
    lock_active_graph_release,
)
from src.services.graph_configuration import GraphConfiguration, PublishedRelease
from tests.integration.postgres_concurrency_helpers import (
    _WAIT_SECONDS,
    _await_blocked_by,
)
from tests.integration.test_graph_release_publication_postgres import (
    _NoEvidenceGate,
    _save_prompt,
)
from tests.integration.test_mixed_release_creation_postgres import (
    CREATORS,
    _backend_pid,
    _create,
    _creator_patches,
)

pytestmark = pytest.mark.postgres

_PUBLISHER = "publisher"
_CREATOR = "creator"
_NAMED_THREADS = frozenset({_PUBLISHER, _CREATOR})
_PARENT_LOCK_TAIL = "FOR UPDATE OF GRAPH_RELEASE, GRAPH_DRAFT"


def _normalized(statement: str) -> str:
    return " ".join(statement.upper().split())


def _is_first_for_update(normalized: str) -> bool:
    return "FOR UPDATE" in normalized


def _is_draft_rebase(normalized: str) -> bool:
    return normalized.startswith("UPDATE GRAPH_DRAFT SET")


# ---------------------------------------------------------------------------
# Seed: bootstrap owns v1; one saved role makes the draft publishable
# ---------------------------------------------------------------------------


def _seed(postgres_engine, creator):
    """Bootstrap v1, save one role, and seed a v1 source for copy creators.

    Mirrors ``test_mixed_release_creation_postgres._seed`` for the source session
    but inserts no release: ``bootstrap_v1`` owns v1.  Returns
    ``(factory, v1_id, publish_lock)``.
    """
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    GraphConfiguration().bootstrap_v1(factory)
    saved = _save_prompt(factory, "architect", "\n\nOrdering tune.", lock=0)
    with factory.begin() as db:
        v1 = db.scalar(select(GraphRelease).where(GraphRelease.effective_to.is_(None)))
        assert v1.version_number == 1
        v1_id = v1.id
        if creator in {"contributor", "duplicate"}:
            source = UserSession(
                session_id=f"{creator}-source",
                created_by="owner@example.com",
                title="R1 source",
                graph_release_id=v1_id,
            )
            db.add(source)
            db.flush()
            if creator == "duplicate":
                db.add(
                    SessionSlideDeck(
                        session_id=source.id,
                        title="R1 source",
                        html_content="<div>R1</div>",
                        slide_count=1,
                        deck_json='{"slides":[{"html":"<div>R1</div>"}]}',
                    )
                )
                db.add(
                    SessionMessage(
                        session_id=source.id,
                        role="user",
                        content=f"{AGENT_MODE_PHRASE} duplicate",
                    )
                )
    return factory, v1_id, saved.draft.lock_version


def _publish(factory, lock):
    with factory() as db:
        return GraphConfiguration().publish_draft(
            db,
            expected_lock_version=lock,
            release_note="Ordering publication",
            actor="publisher@example.com",
            evidence_gate=_NoEvidenceGate(),
        )


# ---------------------------------------------------------------------------
# The observed race
# ---------------------------------------------------------------------------


class _Race:
    """Listeners, PIDs, scan counts and pauses for one publisher and one creator."""

    def __init__(
        self,
        engine,
        *,
        publisher_pause=_is_first_for_update,
        publisher_holds=True,
        publisher_raises=None,
        creator_pauses_after_insert=False,
    ) -> None:
        self.engine = engine
        self._publisher_pause = publisher_pause
        self._publisher_raises = publisher_raises
        self._creator_pauses = creator_pauses_after_insert
        self.pids: dict[str, int] = {}
        self.pid_recorded = {name: threading.Event() for name in _NAMED_THREADS}
        self.scans: list[int] = []
        self.publisher_statements: list[str] = []
        self.publisher_paused = threading.Event()
        self.release_publisher = threading.Event()
        if not publisher_holds:
            self.release_publisher.set()
        self.creator_statements: list[str] = []
        self.creator_paused = threading.Event()
        self.release_creator = threading.Event()

    # -- listeners -----------------------------------------------------------

    def _before(self, conn, _cursor, statement, _params, _context, _executemany):
        name = threading.current_thread().name
        if name not in _NAMED_THREADS:
            return
        # Bound every lock wait on this transaction (SET LOCAL lasts until it
        # ends).  A raw DBAPI cursor keeps the SET out of these listeners.
        with conn.connection.driver_connection.cursor() as raw:
            raw.execute(f"SET LOCAL lock_timeout = '{int(_WAIT_SECONDS)}s'")
        if name == _PUBLISHER and _PUBLISHER not in self.pids:
            self.pids[_PUBLISHER] = _backend_pid(conn)
            self.pid_recorded[_PUBLISHER].set()
        if name == _CREATOR and "FROM graph_release" in statement and "FOR UPDATE" in statement:
            self.pids.setdefault(_CREATOR, _backend_pid(conn))
            self.scans.append(1)
            self.pid_recorded[_CREATOR].set()

    def _after(self, conn, _cursor, statement, _params, _context, _executemany):
        name = threading.current_thread().name
        normalized = _normalized(statement)
        if (
            name == _PUBLISHER
            and not self.publisher_statements
            and self._publisher_pause(normalized)
        ):
            self.publisher_statements.append(normalized)
            self.publisher_paused.set()
            assert self.release_publisher.wait(
                timeout=_WAIT_SECONDS
            ), "the test never released the publisher"
            if self._publisher_raises is not None:
                raise self._publisher_raises
        if (
            name == _CREATOR
            and self._creator_pauses
            and not self.creator_statements
            and normalized.startswith("INSERT INTO USER_SESSIONS")
        ):
            self.creator_statements.append(normalized)
            self.pids.setdefault(_CREATOR, _backend_pid(conn))
            self.pid_recorded[_CREATOR].set()
            self.creator_paused.set()
            assert self.release_creator.wait(
                timeout=_WAIT_SECONDS
            ), "the test never released the creator"

    def install(self) -> None:
        event.listen(self.engine, "before_cursor_execute", self._before)
        event.listen(self.engine, "after_cursor_execute", self._after)

    def remove(self) -> None:
        event.remove(self.engine, "before_cursor_execute", self._before)
        event.remove(self.engine, "after_cursor_execute", self._after)

    def release_all(self) -> None:
        self.release_publisher.set()
        self.release_creator.set()

    # -- observations --------------------------------------------------------

    def blocked(self, *, waiter: str, blocker: str) -> bool:
        assert self.pid_recorded[waiter].wait(
            timeout=_WAIT_SECONDS
        ), f"{waiter} never recorded its PID"
        assert self.pid_recorded[blocker].wait(
            timeout=_WAIT_SECONDS
        ), f"{blocker} never recorded its PID"
        assert self.pids[waiter] != self.pids[blocker]
        return _await_blocked_by(
            self.engine, waiter_pid=self.pids[waiter], blocker_pid=self.pids[blocker]
        )

    def waiting_query(self, name: str) -> str:
        with self.engine.connect() as observer:
            return _normalized(
                observer.scalar(
                    text("SELECT query FROM pg_stat_activity WHERE pid = :pid"),
                    {"pid": self.pids[name]},
                )
                or ""
            )


def _named(name, fn):
    def _call():
        threading.current_thread().name = name
        return fn()

    return _call


def _outcome(future):
    """The finished future's result, re-raising its exception; bounded."""
    return future.result(timeout=_WAIT_SECONDS * 2)


# ---------------------------------------------------------------------------
# Final-state reads
# ---------------------------------------------------------------------------


def _session(factory, session_id) -> UserSession:
    with factory() as db:
        row = db.scalar(select(UserSession).where(UserSession.session_id == session_id))
        assert row is not None, session_id
        return row


def _release_rows(factory) -> list[tuple[int, int, bool]]:
    with factory() as db:
        return [
            (row.id, row.version_number, row.effective_to is None)
            for row in db.scalars(select(GraphRelease).order_by(GraphRelease.id))
        ]


def _assert_source_keeps_v1(factory, creator, actor, v1_id) -> None:
    if creator not in {"contributor", "duplicate"}:
        return
    source = _session(factory, f"{creator}-source")
    assert source.graph_release_id == v1_id
    assert source.id != actor.id
    if creator == "contributor":
        assert actor.parent_session_id == source.id
    else:
        assert actor.parent_session_id is None
        with factory() as db:
            copied = db.scalar(
                select(SessionMessage).where(SessionMessage.session_id == actor.id)
            )
        assert copied.content == f"{AGENT_MODE_PHRASE} duplicate"


# ---------------------------------------------------------------------------
# Publication first: every creator queues behind L0 and pins the exact v2
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("creator", CREATORS)
def test_publication_first_each_creator_pins_exact_new_release(postgres_engine, creator):
    factory, v1_id, lock = _seed(postgres_engine, creator)
    race = _Race(postgres_engine)
    race.install()
    try:
        with _creator_patches(factory), ThreadPoolExecutor(max_workers=2) as pool:
            publisher = pool.submit(_named(_PUBLISHER, lambda: _publish(factory, lock)))
            created = None
            try:
                assert race.publisher_paused.wait(
                    timeout=_WAIT_SECONDS
                ), "publisher never took a FOR UPDATE lock"
                created = pool.submit(_named(_CREATOR, lambda: _create(factory, creator)))
                # C6 order: blocked first, then the lock statement's tables.
                assert race.blocked(waiter=_CREATOR, blocker=_PUBLISHER), (
                    f"{creator} was never blocked by the paused publisher"
                )
                assert "GRAPH_RELEASE" in race.publisher_statements[0]
                assert "GRAPH_DRAFT" in race.publisher_statements[0]
                assert not created.done()
            finally:
                race.release_all()
            published = _outcome(publisher)
            actor_id = _outcome(created)
    finally:
        race.remove()

    assert isinstance(published, PublishedRelease)
    assert published.previous_release_id == v1_id
    v2_id = published.release.release_id
    assert race.scans == [1, 1]
    actor = _session(factory, actor_id)
    assert actor.graph_release_id == v2_id
    with factory() as db:
        assert db.get(GraphRelease, actor.graph_release_id).version_number == 2
    assert _release_rows(factory) == [(v1_id, 1, False), (v2_id, 2, True)]
    _assert_source_keeps_v1(factory, creator, actor, v1_id)


# ---------------------------------------------------------------------------
# Creation first: the publisher waits at L0 and the creator keeps v1
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("creator", CREATORS)
def test_creation_first_publisher_waits_and_creator_keeps_v1(postgres_engine, creator):
    factory, v1_id, lock = _seed(postgres_engine, creator)
    # The publisher's first-FOR-UPDATE pause only records here: it must reach
    # (and be observed waiting in) its L0 statement while the creator holds v1.
    race = _Race(postgres_engine, publisher_holds=False, creator_pauses_after_insert=True)
    race.install()
    try:
        with _creator_patches(factory), ThreadPoolExecutor(max_workers=2) as pool:
            created = pool.submit(_named(_CREATOR, lambda: _create(factory, creator)))
            publisher = None
            try:
                assert race.creator_paused.wait(
                    timeout=_WAIT_SECONDS
                ), f"{creator} never flushed its session"
                publisher = pool.submit(
                    _named(_PUBLISHER, lambda: _publish(factory, lock))
                )
                assert race.blocked(waiter=_PUBLISHER, blocker=_CREATOR), (
                    f"publisher was never blocked by {creator}"
                )
                # C6 strengthening: blocked on L0, not on a later write.
                assert race.waiting_query(_PUBLISHER).endswith(_PARENT_LOCK_TAIL)
                assert not publisher.done()
            finally:
                race.release_all()
            actor_id = _outcome(created)
            published = _outcome(publisher)
    finally:
        race.remove()

    assert race.publisher_statements[0].endswith(_PARENT_LOCK_TAIL)
    assert isinstance(published, PublishedRelease)
    v2_id = published.release.release_id
    assert published.previous_release_id == v1_id
    assert published.release.previous_release_id == v1_id
    assert published.release.version_number == 2
    actor = _session(factory, actor_id)
    assert actor.graph_release_id == v1_id
    with factory() as db:
        v1 = db.get(GraphRelease, v1_id)
        v2 = db.get(GraphRelease, v2_id)
        assert v1.effective_to is not None
        assert v1.effective_to == v2.effective_from
        assert v2.effective_to is None
        assert get_conversation_graph_version(db, actor) == ConversationGraphVersion(
            graph_version=1, active_graph_version=2, is_older_than_active=True
        )
    _assert_source_keeps_v1(factory, creator, actor, v1_id)


# ---------------------------------------------------------------------------
# A creator behind a fully flushed publication (Correction 8 part 3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("outcome", ["rollback", "commit"])
@pytest.mark.parametrize("creator", CREATORS)
def test_creator_behind_fully_flushed_publication_never_sees_partial_release(
    postgres_engine, creator, outcome
):
    factory, v1_id, lock = _seed(postgres_engine, creator)
    injected = RuntimeError("injected at draft_rebased")
    race = _Race(
        postgres_engine,
        publisher_pause=_is_draft_rebase,
        publisher_raises=injected if outcome == "rollback" else None,
    )
    race.install()
    try:
        with _creator_patches(factory), ThreadPoolExecutor(max_workers=2) as pool:
            publisher = pool.submit(_named(_PUBLISHER, lambda: _publish(factory, lock)))
            created = None
            try:
                assert race.publisher_paused.wait(
                    timeout=_WAIT_SECONDS
                ), "publisher never flushed its draft rebase"
                created = pool.submit(_named(_CREATOR, lambda: _create(factory, creator)))
                assert race.blocked(waiter=_CREATOR, blocker=_PUBLISHER), (
                    f"{creator} was never blocked by the flushed publication"
                )
                assert not created.done()
            finally:
                race.release_all()
            publisher_error = publisher.exception(timeout=_WAIT_SECONDS * 2)
            actor_id = _outcome(created)
    finally:
        race.remove()

    assert len(race.publisher_statements) == 1
    actor = _session(factory, actor_id)
    if outcome == "rollback":
        assert publisher_error is injected
        assert race.scans == [1]
        assert actor.graph_release_id == v1_id
        assert _release_rows(factory) == [(v1_id, 1, True)]
    else:
        assert publisher_error is None
        published = publisher.result(timeout=0)
        assert isinstance(published, PublishedRelease)
        v2_id = published.release.release_id
        assert race.scans == [1, 1]
        assert actor.graph_release_id == v2_id
        assert _release_rows(factory) == [(v1_id, 1, False), (v2_id, 2, True)]
    _assert_source_keeps_v1(factory, creator, actor, v1_id)


# ---------------------------------------------------------------------------
# Sequential: old conversations keep v1, new ones pin v2
# ---------------------------------------------------------------------------


def test_new_conversation_after_publication_pins_new_and_old_retains(postgres_engine):
    factory, v1_id, lock = _seed(postgres_engine, "explicit-root")
    manager = SessionManager()
    with _creator_patches(factory):
        old_id = manager.create_session(
            session_id="root-before-publication",
            created_by="actor@example.com",
            graph_capable=True,
        )["session_id"]
        published = _publish(factory, lock)
        new_id = manager.create_session(
            session_id="root-after-publication",
            created_by="actor@example.com",
            graph_capable=True,
        )["session_id"]

    assert isinstance(published, PublishedRelease)
    v2_id = published.release.release_id
    assert v2_id != v1_id
    assert (
        _session(factory, old_id).graph_release_id,
        _session(factory, new_id).graph_release_id,
    ) == (v1_id, v2_id)
    with factory() as db, db.begin():
        assert lock_active_graph_release(db).release_id == v2_id
