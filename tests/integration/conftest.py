"""Shared pytest fixtures for the integration-test suite.

NO module-level side effects — no engine creation, no database connections,
no set_current_user calls.  Only imports and fixture definitions.

Fixtures in this file
---------------------
  sqlite_engine_file_backed  — file-backed SQLite engine (cross-process safe)
  stub_writer                — monkeypatches SlideWriter, records calls in order
  partial_deck               — drives release-order assertions (land / placehold)
  released_deck              — session_id with a committed ascending prefix
  graph_turn_env             — the COMPILED graph over a real database, a real
                               checkpointer and a SkillRecorder (ws4c C5)

Why these three belong here and not in tests/unit/conftest.py:
  stub_writer's purpose is call-order assertions in ws4c/d; its named consumer
  is ws4c C5's suite in tests/integration/.  partial_deck and released_deck
  drive release-order scenarios that also live in tests/integration/.

  A conftest.py is scoped to its own directory tree, so a fixture declared
  under tests/unit/ is INVISIBLE to a test under tests/integration/.  Declared
  here they are available to every test under tests/integration/.

  If a future unit test needs one of these three, promote it to
  tests/conftest.py — never duplicate it.

The file-backed engine
----------------------
  Unlike tests/unit/ which uses in-memory SQLite, the engine here is
  file-backed because later concurrency suites (ws4e layer-4 job) need a
  database shared across TWO PROCESSES.  Two processes cannot share
  sqlite:///:memory: — they get separate in-memory databases.  A file path
  that both processes receive solves this.
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, inspect as sa_inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.database.models  # noqa: F401 — registers all ORM models on Base.metadata
from src.api.services.session_manager import SessionManager
from src.api.services.slide_repository import SlideWriter
from src.core.database import Base, _run_migrations
from src.database.models.session import (
    SessionSlideDeck,
    SessionSlide,
    SlideDeckVersion,
    UserSession,
)
from src.utils.slide_hash import compute_slide_hash


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

_SLIDE_HTMLS = [
    "<div class='slide'><h1>Slide One</h1><p>Content A</p></div>",
    "<div class='slide'><h1>Slide Two</h1><p>Content B</p></div>",
    "<div class='slide'><h1>Slide Three</h1><p>Content C</p></div>",
]


def _make_file_backed_engine() -> Any:
    """Create a file-backed SQLite engine with the full Tellr schema.

    Uses StaticPool so engine.begin() reuses the same connection across
    open/close cycles (required for file-backed SQLite in single-process use).

    File-backed so two processes can share the same database by path —
    required by ws4e's concurrency job.

    LOUD FAILURE GUARD: asserts table list is non-empty and contains the deck
    tables, guarding against the PR1 defect where a migration was disabled and
    the test stayed green.

    Returns (engine, path) — the caller owns the path and must unlink it.
    """
    fd, path = tempfile.mkstemp(suffix=".db", prefix="tellr_integration_")
    os.close(fd)

    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Production ordering: create_all then _run_migrations.
    Base.metadata.create_all(bind=engine)
    _run_migrations(engine)

    inspector = sa_inspect(engine)
    tables = set(inspector.get_table_names())
    assert tables, (
        "Engine has zero tables after Base.metadata.create_all — "
        "the import of src.database.models likely did not run before create_all."
    )
    assert "session_slide_decks" in tables, (
        f"session_slide_decks missing from engine; found: {sorted(tables)}"
    )
    assert "session_slides" in tables, (
        f"session_slides missing from engine; found: {sorted(tables)}"
    )
    return engine, path


def _make_factory(engine) -> Any:
    return sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        expire_on_commit=False,
    )


def _make_fake_db(factory):
    """Return a @contextmanager that yields a DB session from *factory*.

    Patch target for `get_db_session` when driving SessionManager against a
    throwaway engine.
    """
    @contextlib.contextmanager
    def fake_get_db_session():
        db = factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    return fake_get_db_session


def _new_session_id() -> str:
    return f"int-test-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# sqlite_engine_file_backed
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_engine_file_backed():
    """File-backed SQLite engine with the full Tellr schema.

    File-backed (not :memory:) so two processes can share the same database.
    Uses StaticPool for connection reuse within a single process.

    The db file is deleted after the test.  If the test itself needs the path
    (to share it with a subprocess), access engine.url.database.

    Fails loudly if the engine has no tables.
    """
    engine, path = _make_file_backed_engine()
    yield engine
    engine.dispose()
    try:
        os.unlink(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# stub_writer
# ---------------------------------------------------------------------------


class _StubWriter:
    """Monkeypatches SlideWriter; records write_slide and commit_placeholder calls in order.

    Call ORDER is the assertion in ws4c/d — the reorder buffer must release
    slides in position order regardless of the order builders finish.

    Surface:
      written_positions — list[int]: every position passed to write_slide, in call order
      written           — list[tuple[int, str]]: (position, html) in call order
      placeheld         — list[int]: positions passed to commit_placeholder, in call order
    """

    def __init__(self):
        self.written_positions: List[int] = []
        self.written: List[tuple] = []          # (position, html)
        self.placeheld: List[int] = []

    def _make_write_slide(self):
        stub = self

        def write_slide(self_sw, session_id, position, html, **kwargs):
            stub.written_positions.append(position)
            stub.written.append((position, html))

        return write_slide

    def _make_commit_placeholder(self):
        stub = self

        def commit_placeholder(self_sw, session_id, position, error_message=""):
            stub.placeheld.append(position)

        return commit_placeholder


@pytest.fixture
def stub_writer():
    """Monkeypatches SlideWriter.write_slide and SlideWriter.commit_placeholder.

    Records calls in call order so ws4c/d can assert the reorder buffer
    releases slides in ascending position order.

    Surface: written_positions, written (list of (position, html)), placeheld
    """
    recording = _StubWriter()

    with patch.object(SlideWriter, "write_slide", recording._make_write_slide()), \
         patch.object(SlideWriter, "commit_placeholder", recording._make_commit_placeholder()):
        yield recording


# ---------------------------------------------------------------------------
# partial_deck
# ---------------------------------------------------------------------------


class _PartialDeck:
    """Drives release-order assertions for ws4c/d.

    Provides a session_id and methods to land (write real slides) or placehold
    (write placeholder slides) at specific positions, using a real
    SlideWriter instance patched against the fixture's engine.

    Surface:
      session_id          — string session id
      land(positions)     — write a non-placeholder slide at each position
      placehold(position) — write a placeholder at the position
    """

    def __init__(self, session_id: str, engine, factory):
        self._session_id = session_id
        self._engine = engine
        self._factory = factory
        self._writer = SlideWriter()

    @property
    def session_id(self) -> str:
        return self._session_id

    def land(self, positions: List[int]) -> None:
        """Write a real (non-placeholder) slide at each position in *positions*."""
        fake_db = _make_fake_db(self._factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db), \
             patch("src.api.services.slide_repository.get_db_session", fake_db):
            for pos in positions:
                html = f"<div class='slide'><p>Slide {pos}</p></div>"
                self._writer.write_slide(
                    session_id=self._session_id,
                    position=pos,
                    html=html,
                    scripts="",
                )

    def placehold(self, position: int) -> None:
        """Write a placeholder at *position*."""
        fake_db = _make_fake_db(self._factory)
        with patch("src.api.services.session_manager.get_db_session", fake_db), \
             patch("src.api.services.slide_repository.get_db_session", fake_db):
            self._writer.commit_placeholder(
                session_id=self._session_id,
                position=position,
                error_message="test placeholder",
            )


@pytest.fixture
def partial_deck(sqlite_engine_file_backed):
    """A deck with some positions landed and some placeholded.

    Uses the file-backed engine for cross-process safety.
    Surface: session_id, land(positions=[...]), placehold(position=)
    """
    engine = sqlite_engine_file_backed
    factory = _make_factory(engine)
    sid = _new_session_id()

    # Insert the UserSession + SessionSlideDeck
    db = factory()
    try:
        us = UserSession(session_id=sid, created_by="test-user@example.com")
        db.add(us)
        db.flush()
        deck = SessionSlideDeck(
            session_id=us.id,
            title="Partial Deck",
            html_content="",
            scripts_content="",
            slide_count=0,
        )
        db.add(deck)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    yield _PartialDeck(sid, engine, factory)


# ---------------------------------------------------------------------------
# released_deck
# ---------------------------------------------------------------------------


@pytest.fixture
def released_deck(sqlite_engine_file_backed):
    """A deck with a committed ascending prefix of real slides.

    Three slides at positions 0, 1, 2 are already written (non-placeholder).
    Surface: session_id
    """
    engine = sqlite_engine_file_backed
    factory = _make_factory(engine)
    sid = _new_session_id()
    sm = SessionManager()

    db = factory()
    try:
        us = UserSession(session_id=sid, created_by="test-user@example.com")
        db.add(us)
        db.flush()
        deck = SessionSlideDeck(
            session_id=us.id,
            title="Released Deck",
            html_content="",
            scripts_content="",
            slide_count=0,
        )
        db.add(deck)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    # Write three slides in ascending order via SlideWriter
    writer = SlideWriter(session_manager=sm)
    fake_db = _make_fake_db(factory)
    with patch("src.api.services.session_manager.get_db_session", fake_db), \
         patch("src.api.services.slide_repository.get_db_session", fake_db):
        for pos, html in enumerate(_SLIDE_HTMLS):
            writer.write_slide(
                session_id=sid,
                position=pos,
                html=html,
                scripts="",
            )

    yield sid


# ---------------------------------------------------------------------------
# graph_turn_env — the compiled graph, a real database, a real checkpointer
#
# ws4c C5.  Everything a layer-1 orchestration test needs beyond call_skill:
# a live DB session (architect_node's deck-level write, the reviewers' row
# writes, the placeholder's row write, deck_reviewer_node's post-commit write)
# and a real checkpointer (turn 2, and the resumed-mid-fix case).
# ---------------------------------------------------------------------------


def _make_graph_engine(path: str) -> Any:
    """A file-backed SQLite engine with ORDINARY pooling, for a fanned graph run.

    NOT ``sqlite_engine_file_backed``, and the difference is measured rather than
    stylistic.  That fixture uses ``StaticPool``, which hands every thread the
    SAME sqlite3 connection; a compiled turn fans builders out across Pregel
    worker threads which write rows concurrently, and three consecutive runs of a
    15-slide turn on a StaticPool engine failed with three different corruptions
    — ``database schema has changed``, ``query aborted`` and ``database disk
    image is malformed``.  (On ws4b the same shape over ``sqlite:///:memory:``
    took the interpreter down with ``Fatal Python error: Segmentation fault``,
    3 of 3 runs.  A run that dies with no traceback is that.)

    Ordinary pooling gives each worker thread its own connection onto ONE
    file-backed database, which is what makes the fan-out safe.
    ``check_same_thread=False`` permits the cross-thread handoff and
    ``timeout=30`` waits out SQLite's writer lock instead of failing the test.

    The two ``graph_checkpoint*`` tables come from ``_run_migrations``, not from
    ``create_all`` — the same ordering production uses.
    """
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(bind=engine)
    _run_migrations(engine)

    tables = set(sa_inspect(engine).get_table_names())
    for required in ("session_slide_decks", "session_slides", "graph_checkpoints",
                     "graph_checkpoint_writes"):
        assert required in tables, (
            f"{required} missing from the graph engine; found {sorted(tables)}"
        )
    return engine


class _GraphTurnEnv:
    """One session, one compiled graph, one recorder — the layer-1 environment.

    Surface:
      session_id            — the session (and the checkpointer's thread_id)
      recorder              — the SkillRecorder every test parametrises
      run(...)              — invoke one turn, returns the final state
      stream(...)           — invoke one turn, returns [state after each superstep]
      rows()                — SessionSlide rows, ascending
      deck_row()            — the SessionSlideDeck row
      messages()            — the session's chat messages
      verdict_for(position) — the row's stored review verdict payload, or None
      wakes(state)          — this turn's foreman_wakes, read through scoped_vals
    """

    def __init__(self, session_id: str, engine, factory, recorder, graph):
        self.session_id = session_id
        self.engine = engine
        self.factory = factory
        self.recorder = recorder
        self.graph = graph
        self.last_turn_id: Optional[str] = None

    # -- driving the graph --------------------------------------------------

    def _turn_state(self, turn_id: Optional[str], initial: Optional[Dict[str, Any]]):
        turn = turn_id or uuid.uuid4().hex
        self.last_turn_id = turn
        state: Dict[str, Any] = {
            "session_id": self.session_id,
            "turn_id": turn,
            "initiated_by": "graph-user@example.com",
            "architect_message": "build me a deck",
        }
        state.update(initial or {})
        return state

    def _config(self, max_concurrency: Optional[int]):
        # thread_id is mandatory — omitting it raises out of the checkpointer.
        config: Dict[str, Any] = {"configurable": {"thread_id": self.session_id}}
        if max_concurrency is not None:
            config["max_concurrency"] = max_concurrency
        return config

    def run(
        self,
        *,
        turn_id: Optional[str] = None,
        initial: Optional[Dict[str, Any]] = None,
        max_concurrency: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Run one turn and return the final state.

        ``max_concurrency`` defaults to ``CAP``, which is what ``invoke_graph``
        passes in production.  The cap test raises it deliberately — see that
        test's docstring.
        """
        from src.services.foreman_service import CAP

        return self.graph.invoke(
            self._turn_state(turn_id, initial),
            self._config(CAP if max_concurrency is None else max_concurrency),
        )

    def stream(
        self,
        *,
        turn_id: Optional[str] = None,
        initial: Optional[Dict[str, Any]] = None,
        max_concurrency: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Run one turn and return the state after each superstep.

        ``stream_mode="values"`` is how a per-wake property (the committed
        prefix) is observed without wrapping a production node.
        """
        from src.services.foreman_service import CAP

        return list(
            self.graph.stream(
                self._turn_state(turn_id, initial),
                self._config(CAP if max_concurrency is None else max_concurrency),
                stream_mode="values",
            )
        )

    # -- reading the result -------------------------------------------------

    def _owner(self, db):
        return (
            db.query(UserSession)
            .filter(UserSession.session_id == self.session_id)
            .one()
        )

    def rows(self) -> List[SessionSlide]:
        db = self.factory()
        try:
            return (
                db.query(SessionSlide)
                .filter(SessionSlide.session_id == self._owner(db).id)
                .order_by(SessionSlide.position)
                .all()
            )
        finally:
            db.close()

    def rows_by_position(self) -> Dict[int, SessionSlide]:
        return {row.position: row for row in self.rows()}

    def deck_row(self) -> Optional[SessionSlideDeck]:
        db = self.factory()
        try:
            return (
                db.query(SessionSlideDeck)
                .filter(SessionSlideDeck.session_id == self._owner(db).id)
                .first()
            )
        finally:
            db.close()

    def messages(self) -> List[dict]:
        from src.api.services.session_manager import get_session_manager

        return get_session_manager().get_messages(self.session_id)

    def verdict_for(self, position: int) -> Optional[dict]:
        """The stored ``tellr_review`` payload for the row at *position*."""
        from src.domain.finding import VERDICT_KEY

        row = self.rows_by_position().get(position)
        if row is None or not row.verification_record:
            return None
        record = json.loads(row.verification_record)
        entry = record.get(compute_slide_hash(row.html)) or {}
        return entry.get(VERDICT_KEY)

    def is_placeholder(self, position: int) -> bool:
        from src.api.services.slide_repository import is_placeholder_record

        row = self.rows_by_position().get(position)
        if row is None:
            return False
        return is_placeholder_record(json.loads(row.verification_record or "{}"))

    @staticmethod
    def wakes(state: dict) -> List[List[int]]:
        """This turn's ``foreman_wakes``, read through ``scoped_vals``.

        Read through ``scoped_vals`` and never off the raw wrapper: the wrapper
        carries a turn discriminator, and a turn-2 assertion made against the
        raw value would silently read turn 1's wakes.
        """
        from src.services.graph.state import scoped_vals

        return [list(batch) for batch in scoped_vals(state, "foreman_wakes")]


@pytest.fixture
def graph_turn_env(monkeypatch, tmp_path):
    """The COMPILED graph over a real database and a real checkpointer.

    Only what reaches a Databricks workspace is stubbed, and only one thing
    does: ``call_skill``, replaced by a ``SkillRecorder``.  Everything else is
    the shipped code — ``SlideWriter`` row writes, ``write_deck_level_columns``,
    ``save_deck_review``, the chat message, ``resolve_style_source`` (which
    touches no database for an unpinned deck, and every spec this suite builds
    is unpinned) and the real ``SqlAlchemyCheckpointSaver``.  So an assertion
    about an author or a verdict is read back off a row rather than off a mock's
    call args.

    ``resolve_display_names`` is neutralised because ``get_slide_deck``'s row
    read resolves SCIM display names on every call: with the CI environment's
    ``DATABRICKS_HOST``/``DATABRICKS_TOKEN`` a real ``WorkspaceClient`` retries
    SCIM and hangs, and identity resolution is not what any test here is about.

    The compiled graph is built ONCE per environment and its saver is shared, so
    turn 2 resumes the same thread through the same checkpoint rows.
    """
    from src.core.checkpointer import SqlAlchemyCheckpointSaver
    from src.services.graph.builder import build_graph
    from tests.integration.conftest_stub_skills import SkillRecorder

    engine = _make_graph_engine(str(tmp_path / "graph_turn.db"))
    factory = _make_factory(engine)
    session_id = _new_session_id()

    db = factory()
    try:
        db.add(UserSession(session_id=session_id, created_by="owner@example.com"))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    fake_db = _make_fake_db(factory)
    for target in (
        "src.api.services.slide_repository.get_db_session",
        "src.api.services.session_manager.get_db_session",
        "src.api.services.deck_level_writer.get_db_session",
        "src.services.graph.nodes.get_db_session",
    ):
        monkeypatch.setattr(target, fake_db)
    monkeypatch.setattr(
        "src.services.identity_provider.resolve_display_names", lambda emails: {}
    )

    recorder = SkillRecorder()
    monkeypatch.setattr("src.services.graph.nodes.call_skill", recorder)

    graph = build_graph(
        checkpointer=SqlAlchemyCheckpointSaver(session_factory=factory)
    )

    yield _GraphTurnEnv(session_id, engine, factory, recorder, graph)

    engine.dispose()
