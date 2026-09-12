"""Shared pytest fixtures for the integration-test suite.

NO module-level side effects — no engine creation, no database connections,
no set_current_user calls.  Only imports and fixture definitions.

Fixtures in this file
---------------------
  sqlite_engine_file_backed  — file-backed SQLite engine (cross-process safe)
  stub_writer                — monkeypatches SlideWriter, records calls in order
  partial_deck               — drives release-order assertions (land / placehold)
  released_deck              — session_id with a committed ascending prefix

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
