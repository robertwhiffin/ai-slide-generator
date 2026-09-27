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
from sqlalchemy.exc import IntegrityError
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
from src.services.graph_configuration import GraphConfiguration, PublishedRelease, RestoredRelease
from tests.integration.postgres_concurrency_helpers import (
    _WAIT_SECONDS,
    _await_blocked_by,
)
from tests.integration.test_graph_release_publication_postgres import (
    _drop_commit_failure,
    _install_commit_failure,
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


# ============================================================================
# Task 5 — Rollback against every conversation creator (Correction 43)
# ============================================================================
#
# Cleanup-vs-rollback ordering is already proved in Task 4's
# ``test_rollback_and_cleanup_serialize_with_exact_deletions`` (reused, not
# duplicated here).  The three tests below cover the remaining brief items:
# rollback-first (all 7 creators), creation-first (all 7 creators), and the
# creator-behind-fully-flushed-rollback parametrize (outcome × creators).
#
# Every ordering test goes RED rather than hangs:
#   - SET LOCAL lock_timeout on every named thread (in _RollbackRace._before).
#   - Every future is bounded (_WAIT_SECONDS * 2).
#   - The paused holder is released in an inner ``finally``.
#   - PIDs are captured before the blocking statement (C5 / C41).
#   - _await_blocked_by uses keyword arguments (C41).

_ROLLBACK = "rollback"

# ---------------------------------------------------------------------------
# Predicates (Corrections 6 and 43)
# ---------------------------------------------------------------------------

_L0_LOCK_MODES_ON_RELEASE = (
    "FOR UPDATE OF GRAPH_RELEASE",
    "FOR SHARE OF GRAPH_RELEASE",
    "FOR NO KEY UPDATE OF GRAPH_RELEASE",
    "FOR KEY SHARE OF GRAPH_RELEASE",
)


def _is_l0_both_parents(normalized: str) -> bool:
    """C6: mode-agnostic both-parents L0 matcher for rollback-vs-creator tests.

    Fires for any row-lock mode so the controller sabotage (draft-only lock)
    still fires the pause, and goes RED only at ``_await_blocked_by``.
    """
    return (
        "FROM GRAPH_RELEASE" in normalized
        and "GRAPH_DRAFT" in normalized
        and "GRAPH_DRAFT_AGENT" not in normalized
        and any(mode in normalized for mode in _L0_LOCK_MODES_ON_RELEASE)
    )


def _is_rollback_draft_agent_write(normalized: str) -> bool:
    """Fires after the rollback's reset write: the last per-role draft flush."""
    return normalized.startswith("UPDATE GRAPH_DRAFT_AGENT SET")


# ---------------------------------------------------------------------------
# _RollbackRace: publication-vs-creator machinery, writer is now rollback
# ---------------------------------------------------------------------------


class _RollbackRace:
    """Mirrors _Race but the writer thread is named ``_ROLLBACK``.

    *rollback_pause* defaults to the C6 mode-agnostic L0 matcher.  Pass
    ``rollback_pause=_is_rollback_draft_agent_write`` for the fully-flushed
    test, where the rollback pauses after its last draft-agent reset write.
    """

    def __init__(
        self,
        engine,
        *,
        rollback_pause=None,
        rollback_raises=None,
        creator_pauses_after_insert: bool = False,
    ) -> None:
        self.engine = engine
        self._rollback_pause = (
            rollback_pause if rollback_pause is not None else _is_l0_both_parents
        )
        self._rollback_raises = rollback_raises
        self._creator_pauses = creator_pauses_after_insert
        self.pids: dict[str, int] = {}
        self.pid_recorded = {
            _ROLLBACK: threading.Event(),
            _CREATOR: threading.Event(),
        }
        self.scans: list[int] = []
        self.rollback_statements: list[str] = []
        self.rollback_paused = threading.Event()
        self.release_rollback = threading.Event()
        self.creator_statements: list[str] = []
        self.creator_paused = threading.Event()
        self.release_creator = threading.Event()

    def _before(self, conn, _cursor, statement, _params, _context, _executemany):
        name = threading.current_thread().name
        if name not in (_ROLLBACK, _CREATOR):
            return
        with conn.connection.driver_connection.cursor() as raw:
            raw.execute(f"SET LOCAL lock_timeout = '{int(_WAIT_SECONDS)}s'")
        if name == _ROLLBACK and _ROLLBACK not in self.pids:
            # Capture rollback PID before its first statement (#269 C5).
            self.pids[_ROLLBACK] = _backend_pid(conn)
            self.pid_recorded[_ROLLBACK].set()
        if name == _CREATOR and "FROM graph_release" in statement and "FOR UPDATE" in statement:
            self.pids.setdefault(_CREATOR, _backend_pid(conn))
            self.scans.append(1)
            self.pid_recorded[_CREATOR].set()

    def _after(self, conn, _cursor, statement, _params, _context, _executemany):
        name = threading.current_thread().name
        normalized = _normalized(statement)
        if (
            name == _ROLLBACK
            and not self.rollback_statements
            and self._rollback_pause(normalized)
        ):
            self.rollback_statements.append(normalized)
            self.rollback_paused.set()
            assert self.release_rollback.wait(
                timeout=_WAIT_SECONDS
            ), "the test never released the rollback"
            if self._rollback_raises is not None:
                raise self._rollback_raises
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
        self.release_rollback.set()
        self.release_creator.set()

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


# ---------------------------------------------------------------------------
# Seed: v1..v4 with a burned id so ids differ from versions
# ---------------------------------------------------------------------------


def _seed_v4(postgres_engine, creator):
    """v1..v4, architect ``+2``–``+4``, published with ``_NoEvidenceGate``.

    Burns id 2 (a failed v2 commit) so ids differ from versions:
    (1, 1), (3, 2), (4, 3), (5, 4); the next release will be id 6.
    ``contributor``/``duplicate`` sources are pinned to v4.
    Returns ``(factory, v2_id, v4_id, lock)`` where *lock* is the draft
    lock-version after publishing v4.
    """
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    GraphConfiguration().bootstrap_v1(factory)
    lock = 0
    v2_id = None
    v4_id = None
    for v in range(2, 5):
        saved = _save_prompt(factory, "architect", f"\n\n+{v}", lock=lock)
        lock = saved.draft.lock_version
        if v == 2:
            # Burn id 2: deferred trigger fails the next commit.
            _install_commit_failure(postgres_engine)
            with pytest.raises(IntegrityError, match="injected commit failure"):
                _publish(factory, lock)
            assert _drop_commit_failure(postgres_engine) == 1
        published = _publish(factory, lock)
        assert isinstance(published, PublishedRelease)
        assert published.release.version_number == v
        lock = published.draft.lock_version
        if v == 2:
            v2_id = published.release.release_id
        if v == 4:
            v4_id = published.release.release_id
    if creator in {"contributor", "duplicate"}:
        with factory.begin() as db:
            source = UserSession(
                session_id=f"{creator}-source",
                created_by="owner@example.com",
                title="R4 source",
                graph_release_id=v4_id,
            )
            db.add(source)
            db.flush()
            if creator == "duplicate":
                db.add(
                    SessionSlideDeck(
                        session_id=source.id,
                        title="R4 source",
                        html_content="<div>R4</div>",
                        slide_count=1,
                        deck_json='{"slides":[{"html":"<div>R4</div>"}]}',
                    )
                )
                db.add(
                    SessionMessage(
                        session_id=source.id,
                        role="user",
                        content=f"{AGENT_MODE_PHRASE} duplicate",
                    )
                )
    return factory, v2_id, v4_id, lock


def _restore(factory, *, lock: int, version: int = 2):
    """Zero-argument callable: restores *version* with *lock*."""

    def _call():
        with factory() as db:
            return GraphConfiguration().restore_release(
                db,
                version_number=version,
                expected_lock_version=lock,
                release_note="Emergency: back to 2",
                actor="oncall@example.com",
            )

    return _call


def _assert_source_keeps_v4(factory, creator, actor, v4_id) -> None:
    """Analog of ``_assert_source_keeps_v1`` but for the v4-pinned source."""
    if creator not in {"contributor", "duplicate"}:
        return
    source = _session(factory, f"{creator}-source")
    assert source.graph_release_id == v4_id
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
# Rollback first: every creator queues behind rollback's L0
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("creator", CREATORS)
def test_rollback_first_each_creator_pins_the_restoring_release(postgres_engine, creator):
    """Rollback holds L0; every creator queues and pins the restored release (v5).

    The rollback pauses after L0 (C6 mode-agnostic matcher).  The creator is
    observed blocked by the rollback PID, then after release it rescans and
    pins v5.  Scan sequence ``[1, 1]`` matches publication-first in #269 Task 3:
    scan 1 hits the now-closed v4 row (0 results), scan 2 locks v5 (1 result).
    Source sessions for ``contributor``/``duplicate`` still pin v4.
    """
    factory, v2_id, v4_id, lock = _seed_v4(postgres_engine, creator)
    race = _RollbackRace(postgres_engine)
    race.install()
    try:
        with _creator_patches(factory), ThreadPoolExecutor(max_workers=2) as pool:
            rollback_fut = pool.submit(_named(_ROLLBACK, _restore(factory, lock=lock)))
            created_fut = None
            try:
                assert race.rollback_paused.wait(timeout=_WAIT_SECONDS), (
                    "rollback never took an L0 lock"
                )
                created_fut = pool.submit(
                    _named(_CREATOR, lambda: _create(factory, creator))
                )
                # C6 order: _await_blocked_by first, then the lock-mode assertion.
                assert race.blocked(waiter=_CREATOR, blocker=_ROLLBACK), (
                    f"{creator} was never blocked by the paused rollback"
                )
                assert _PARENT_LOCK_TAIL in race.rollback_statements[0]
                assert not created_fut.done()
            finally:
                race.release_all()
            restored = _outcome(rollback_fut)
            actor_id = _outcome(created_fut)
    finally:
        race.remove()

    assert isinstance(restored, RestoredRelease), restored
    v5_id = restored.published.release.release_id
    assert restored.published.release.version_number == 5
    assert restored.source.release_id == v2_id
    assert race.scans == [1, 1]
    actor = _session(factory, actor_id)
    assert actor.graph_release_id == v5_id
    with factory() as db:
        assert db.get(GraphRelease, actor.graph_release_id).version_number == 5
    rows = _release_rows(factory)
    assert len(rows) == 5
    assert rows[-1] == (v5_id, 5, True)
    assert all(r[2] is False for r in rows[:-1])
    _assert_source_keeps_v4(factory, creator, actor, v4_id)


# ---------------------------------------------------------------------------
# Creation first: rollback blocks at L0 behind the creator's release lock
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("creator", CREATORS)
def test_creation_first_rollback_waits_and_creator_keeps_v4(postgres_engine, creator):
    """Creator pauses after INSERT; rollback blocks at L0, then creates v5.

    The creator holds ``lock_active_graph_release``'s ``FOR UPDATE`` on v4.
    The rollback's ``_lock_current_parents(exclusive=True)`` conflicts on that
    row and waits.  After release the creator pins v4 and the rollback creates
    v5; ``get_conversation_graph_version`` reflects ``(4, 5, True)``.
    """
    factory, v2_id, v4_id, lock = _seed_v4(postgres_engine, creator)
    race = _RollbackRace(postgres_engine, creator_pauses_after_insert=True)
    race.install()
    try:
        with _creator_patches(factory), ThreadPoolExecutor(max_workers=2) as pool:
            created_fut = pool.submit(
                _named(_CREATOR, lambda: _create(factory, creator))
            )
            rollback_fut = None
            try:
                assert race.creator_paused.wait(timeout=_WAIT_SECONDS), (
                    f"{creator} never flushed its session"
                )
                rollback_fut = pool.submit(
                    _named(_ROLLBACK, _restore(factory, lock=lock))
                )
                assert race.blocked(waiter=_ROLLBACK, blocker=_CREATOR), (
                    f"rollback was never blocked by {creator}"
                )
                # C6 strengthening: rollback is blocked at L0, not a later write.
                assert race.waiting_query(_ROLLBACK).endswith(_PARENT_LOCK_TAIL)
                assert not rollback_fut.done()
            finally:
                race.release_all()
            actor_id = _outcome(created_fut)
            restored = _outcome(rollback_fut)
    finally:
        race.remove()

    actor = _session(factory, actor_id)
    assert actor.graph_release_id == v4_id
    with factory() as db:
        assert db.get(GraphRelease, actor.graph_release_id).version_number == 4
    assert isinstance(restored, RestoredRelease), restored
    assert restored.published.release.version_number == 5
    assert restored.published.previous_release_id == v4_id
    with factory() as db:
        assert get_conversation_graph_version(db, actor) == ConversationGraphVersion(
            graph_version=4, active_graph_version=5, is_older_than_active=True
        )
    _assert_source_keeps_v4(factory, creator, actor, v4_id)


# ---------------------------------------------------------------------------
# Creator behind a fully flushed rollback (Corrections 6 and 43)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("outcome", ["rollback", "commit"])
@pytest.mark.parametrize("creator", CREATORS)
def test_creator_behind_fully_flushed_rollback_never_sees_partial_release(
    postgres_engine, creator, outcome
):
    """Creator sees only a complete rollback state, never a partial one.

    The rollback pauses after its last ``UPDATE GRAPH_DRAFT_AGENT SET``.  All
    writes are flushed (the release INSERT, seven mapping INSERTs, the evidence
    INSERT, the draft UPDATE, and the architect reset UPDATE) but the transaction
    has not committed.  Only architect is reset (v4→v2), so exactly one
    ``UPDATE GRAPH_DRAFT_AGENT SET`` fires, making the pause unconditional.
    The creator is observed blocked by the rollback PID.

    - ``rollback``: injected error aborts the transaction; v4 is still active;
      creator pins v4.
    - ``commit``: rollback succeeds; v5 is active; creator pins v5.
    """
    factory, v2_id, v4_id, lock = _seed_v4(postgres_engine, creator)
    injected = RuntimeError("injected at draft_reset")
    race = _RollbackRace(
        postgres_engine,
        rollback_pause=_is_rollback_draft_agent_write,
        rollback_raises=injected if outcome == "rollback" else None,
    )
    race.install()
    try:
        with _creator_patches(factory), ThreadPoolExecutor(max_workers=2) as pool:
            rollback_fut = pool.submit(_named(_ROLLBACK, _restore(factory, lock=lock)))
            created_fut = None
            try:
                assert race.rollback_paused.wait(timeout=_WAIT_SECONDS), (
                    "rollback never reached its draft-agent write"
                )
                created_fut = pool.submit(
                    _named(_CREATOR, lambda: _create(factory, creator))
                )
                assert race.blocked(waiter=_CREATOR, blocker=_ROLLBACK), (
                    f"{creator} was never blocked by the flushed rollback"
                )
                assert not created_fut.done()
            finally:
                race.release_all()
            rollback_error = rollback_fut.exception(timeout=_WAIT_SECONDS * 2)
            actor_id = _outcome(created_fut)
    finally:
        race.remove()

    actor = _session(factory, actor_id)
    rows = _release_rows(factory)
    if outcome == "rollback":
        assert rollback_error is injected
        assert actor.graph_release_id == v4_id
        assert len(rows) == 4  # v5 was never committed
        assert rows[-1] == (v4_id, 4, True)
    else:
        assert rollback_error is None
        restored = rollback_fut.result(timeout=0)
        assert isinstance(restored, RestoredRelease), restored
        v5_id = restored.published.release.release_id
        assert actor.graph_release_id == v5_id
        assert len(rows) == 5
        assert rows[-1] == (v5_id, 5, True)
    _assert_source_keeps_v4(factory, creator, actor, v4_id)
