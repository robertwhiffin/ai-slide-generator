"""Shared pytest fixtures for the unit-test suite.

NO module-level side effects — no engine creation, no database connections,
no set_current_user calls.  Only imports and fixture definitions live here.
Anything that executes at import time would break concurrent agents' runs.

Fixture routing:
  tests/unit/conftest.py      — everything below (this file)
  tests/integration/conftest.py — stub_writer, partial_deck, released_deck,
                                   plus the file-backed sqlite engine fixture
  tests/conftest.py           — shared fixtures visible to both trees

If a unit test later needs stub_writer / partial_deck / released_deck, promote
those fixtures to tests/conftest.py — never duplicate them.
"""
from __future__ import annotations

import contextlib
import json
import os
import queue
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, inspect as sa_inspect, text
from sqlalchemy.orm import sessionmaker

# One import registers EVERY model on Base.metadata — must come before create_all.
import src.database.models  # noqa: F401
from src.api.schemas.streaming import StreamEvent, StreamEventType
from src.api.services.session_manager import SessionManager
from src.api.services.slide_repository import SlideWriter, is_placeholder_record
from src.core.database import Base, _run_migrations
from src.core.user_context import get_current_user, set_current_user
from src.database.models.profile import ConfigProfile
from src.database.models.session import (
    SessionMessage,
    SessionSlide,
    SessionSlideDeck,
    SlideDeckVersion,
    UserSession,
)
from src.utils.slide_hash import compute_slide_hash

# ---------------------------------------------------------------------------
# Sample slide HTML used by deck fixtures.  Three slides, content distinct so
# compute_slide_hash gives three different values.
# ---------------------------------------------------------------------------
_SLIDE_HTMLS = [
    "<div class='slide'><h1>Slide One</h1><p>Content A</p></div>",
    "<div class='slide'><h1>Slide Two</h1><p>Content B</p></div>",
    "<div class='slide'><h1>Slide Three</h1><p>Content C</p></div>",
]

# Minimal DeckSpec JSON that passes DeckSpec.model_validate_json.
_MINIMAL_DECK_SPEC = {
    "title": "Test Deck",
    "audience": "Test audience",
    "purpose": "Test purpose",
    "argument": "Test argument",
    "call_to_action": "Test CTA",
    "narrative_arc": ["intro", "body", "conclusion"],
    "design_contract": {
        "design_system_id": None,
        "template_id": None,
        "slide_style_id": None,
    },
    "resolved_data": {
        "synthesis": "Test synthesis",
        "figures": [],
        "gaps": [],
    },
    "slides": [
        {
            "position": 0,
            "purpose": "intro",
            "content_brief": "Brief 0",
            "assumes": "",
            "hands_off": "",
            "data_references": [],
        },
        {
            "position": 1,
            "purpose": "body",
            "content_brief": "Brief 1",
            "assumes": "",
            "hands_off": "",
            "data_references": [],
        },
        {
            "position": 2,
            "purpose": "conclusion",
            "content_brief": "Brief 2",
            "assumes": "",
            "hands_off": "",
            "data_references": [],
        },
    ],
}


# ---------------------------------------------------------------------------
# Private helpers — not fixtures.
# ---------------------------------------------------------------------------


def _make_in_memory_engine() -> Any:
    """Create an in-memory SQLite engine with the full Tellr schema.

    LOUD FAILURE GUARD: asserts table list is non-empty and contains the deck
    tables.  A fixture that yields an engine with zero tables and no error is
    the measured PR1 defect where an idempotency test stayed green with the
    migration disabled.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    # Production ordering: create_all then _run_migrations.  CF finding #22.
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
    return engine


def _make_factory(engine) -> Any:
    """Return a sessionmaker bound to *engine*.

    expire_on_commit=False so objects returned by fixture methods remain
    accessible after the session that loaded them is closed.
    """
    return sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        expire_on_commit=False,
    )


def _make_fake_db(factory):
    """Return a @contextmanager that yields a DB session from *factory*.

    This is the patch target for `get_db_session` when a fixture drives
    SessionManager methods against a throwaway engine.  Pattern copied from
    tests/integration/test_slide_row_identity_and_verdicts.py.
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
    return f"test-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Base class for deck / contributor fixtures.
# Provides the _patched() context manager used by methods that call SessionManager.
# ---------------------------------------------------------------------------


class _FixtureBase:
    """Common machinery for fixtures that drive SessionManager."""

    def __init__(self, engine, factory):
        self._engine = engine
        self._factory = factory
        self._sm = SessionManager()

    @contextlib.contextmanager
    def _patched(self):
        """Patch get_db_session so SessionManager uses this fixture's engine."""
        with patch(
            "src.api.services.session_manager.get_db_session",
            _make_fake_db(self._factory),
        ):
            yield

    def _owner_pk(self, session_id: str) -> int:
        db = self._factory()
        try:
            return (
                db.query(UserSession)
                .filter(UserSession.session_id == session_id)
                .one()
                .id
            )
        finally:
            db.close()


# ---------------------------------------------------------------------------
# sqlite_engine_with_decks
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_engine_with_decks():
    """Throwaway in-memory SQLite engine with the deck tables.

    Schema built via the real production sequence:
        import src.database.models  (registers all ORM models on Base.metadata)
        Base.metadata.create_all(bind=engine)
        _run_migrations(engine)

    Fails loudly if the engine has no tables (guards against the PR1 defect
    where a migration was disabled and the test stayed green).
    """
    engine = _make_in_memory_engine()
    yield engine
    engine.dispose()


# ---------------------------------------------------------------------------
# sqlite_engine_with_prompts
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_engine_with_prompts():
    """Same as sqlite_engine_with_decks, additionally asserting config_prompts exists.

    For tests that read/write ConfigPrompts rows.
    """
    engine = _make_in_memory_engine()
    inspector = sa_inspect(engine)
    tables = set(inspector.get_table_names())
    assert "config_prompts" in tables, (
        f"config_prompts missing from engine; found: {sorted(tables)}"
    )
    yield engine
    engine.dispose()


# ---------------------------------------------------------------------------
# deck_fixture
# ---------------------------------------------------------------------------


class _DeckFixture(_FixtureBase):
    """One UserSession + SessionSlideDeck, no slides.

    Surface: session_id, deck_row(), prune_all_versions()
    """

    def __init__(self, session_id: str, engine, factory):
        super().__init__(engine, factory)
        self._session_id = session_id

    @property
    def session_id(self) -> str:
        return self._session_id

    def deck_row(self) -> SessionSlideDeck:
        """Return the current SessionSlideDeck row (detached)."""
        db = self._factory()
        try:
            owner_id = self._owner_pk(self._session_id)
            deck = (
                db.query(SessionSlideDeck)
                .filter(SessionSlideDeck.session_id == owner_id)
                .one()
            )
            db.expunge(deck)
            return deck
        finally:
            db.close()

    def prune_all_versions(self) -> None:
        """Delete every SlideDeckVersion for this deck."""
        db = self._factory()
        try:
            owner_id = self._owner_pk(self._session_id)
            db.query(SlideDeckVersion).filter(
                SlideDeckVersion.session_id == owner_id
            ).delete()
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


@pytest.fixture
def deck_fixture():
    """One UserSession + SessionSlideDeck; exposes session_id, deck_row(), prune_all_versions()."""
    engine = _make_in_memory_engine()
    factory = _make_factory(engine)
    sid = _new_session_id()

    db = factory()
    try:
        us = UserSession(session_id=sid, created_by="test-user@example.com")
        db.add(us)
        db.flush()
        deck = SessionSlideDeck(
            session_id=us.id,
            title="Test Deck",
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

    fixture = _DeckFixture(sid, engine, factory)
    yield fixture
    engine.dispose()


# ---------------------------------------------------------------------------
# deck_with_three_rows — the workhorse
# ---------------------------------------------------------------------------


class _DeckWithThreeRows(_FixtureBase):
    """UserSession + SessionSlideDeck + 3 SessionSlide rows.

    Surface: session_id, rows(), row_snapshot(), deck_row(), deck_json(),
             version(), session_row(), deck_row_for(sid), set_raw_deck_spec_json(s),
             get_slide_deck(), duplicate(version_number=None), create_version(),
             version_count()
    """

    def __init__(self, session_id: str, engine, factory):
        super().__init__(engine, factory)
        self._session_id = session_id

    @property
    def session_id(self) -> str:
        return self._session_id

    def rows(self) -> List[SessionSlide]:
        """Return the SessionSlide rows ordered by position (detached)."""
        db = self._factory()
        try:
            owner_id = self._owner_pk(self._session_id)
            rows = (
                db.query(SessionSlide)
                .filter(SessionSlide.session_id == owner_id)
                .order_by(SessionSlide.position)
                .all()
            )
            for r in rows:
                db.expunge(r)
            return rows
        finally:
            db.close()

    def row_snapshot(self) -> List[Dict[str, Any]]:
        """Capture enough columns to prove no row changed.

        Captures: position, html, slide_id (stable per-slide UUID),
        id (internal String(64) row identity — distinct from slide_id),
        scripts, created_by, modified_by, modified_at, verification_record,
        deck_spec_slide.

        Note on identity: SessionSlide.id is a String(64) internal row
        identity; SessionSlide.slide_id is a String(255) stable per-slide UUID
        the frontend uses.  Both are captured here so callers can assert on
        either.
        """
        db = self._factory()
        try:
            owner_id = self._owner_pk(self._session_id)
            rows = (
                db.query(SessionSlide)
                .filter(SessionSlide.session_id == owner_id)
                .order_by(SessionSlide.position)
                .all()
            )
            return [
                {
                    "position": r.position,
                    "html": r.html,
                    "slide_id": r.slide_id,       # String(255) stable frontend UUID
                    "id": r.id,                   # String(64) internal row identity
                    "scripts": r.scripts,
                    "created_by": r.created_by,
                    "modified_by": r.modified_by,
                    "modified_at": r.modified_at,
                    "verification_record": r.verification_record,
                    "deck_spec_slide": r.deck_spec_slide,
                }
                for r in rows
            ]
        finally:
            db.close()

    def deck_row(self) -> SessionSlideDeck:
        """Return the current SessionSlideDeck row (detached)."""
        db = self._factory()
        try:
            owner_id = self._owner_pk(self._session_id)
            deck = (
                db.query(SessionSlideDeck)
                .filter(SessionSlideDeck.session_id == owner_id)
                .one()
            )
            db.expunge(deck)
            return deck
        finally:
            db.close()

    def deck_json(self) -> Optional[Dict[str, Any]]:
        """Return the parsed deck_json column, or None if absent."""
        db = self._factory()
        try:
            owner_id = self._owner_pk(self._session_id)
            deck = (
                db.query(SessionSlideDeck)
                .filter(SessionSlideDeck.session_id == owner_id)
                .one()
            )
            raw = deck.deck_json
            return json.loads(raw) if raw else None
        finally:
            db.close()

    def version(self) -> int:
        """Return the optimistic-lock version counter."""
        db = self._factory()
        try:
            owner_id = self._owner_pk(self._session_id)
            deck = (
                db.query(SessionSlideDeck)
                .filter(SessionSlideDeck.session_id == owner_id)
                .one()
            )
            return deck.version
        finally:
            db.close()

    def session_row(self) -> UserSession:
        """Return the UserSession row (detached)."""
        db = self._factory()
        try:
            us = (
                db.query(UserSession)
                .filter(UserSession.session_id == self._session_id)
                .one()
            )
            db.expunge(us)
            return us
        finally:
            db.close()

    def deck_row_for(self, sid: str) -> SessionSlideDeck:
        """Return the SessionSlideDeck row for the session with string id *sid* (detached)."""
        db = self._factory()
        try:
            owner_id = self._owner_pk(sid)
            deck = (
                db.query(SessionSlideDeck)
                .filter(SessionSlideDeck.session_id == owner_id)
                .one()
            )
            db.expunge(deck)
            return deck
        finally:
            db.close()

    def set_raw_deck_spec_json(self, s: Optional[str]) -> None:
        """Overwrite deck_spec_json with the raw string *s* (bypasses ORM validation)."""
        db = self._factory()
        try:
            owner_id = self._owner_pk(self._session_id)
            deck = (
                db.query(SessionSlideDeck)
                .filter(SessionSlideDeck.session_id == owner_id)
                .one()
            )
            deck.deck_spec_json = s
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def get_slide_deck(self) -> Optional[Dict[str, Any]]:
        """Call SessionManager.get_slide_deck via patched get_db_session."""
        with self._patched():
            return self._sm.get_slide_deck(self._session_id)

    def duplicate(self, version_number: Optional[int] = None) -> Dict[str, Any]:
        """Call SessionManager.duplicate_session via patched get_db_session."""
        with self._patched():
            return self._sm.duplicate_session(
                source_session_id=self._session_id,
                created_by="test-user@example.com",
                version_number=version_number,
            )

    def create_version(self) -> Dict[str, Any]:
        """Create a SlideDeckVersion snapshot via SessionManager.create_version."""
        deck_data = self.get_slide_deck() or {}
        with self._patched():
            return self._sm.create_version(
                session_id=self._session_id,
                description="test snapshot",
                deck_dict=deck_data,
            )

    def version_count(self) -> int:
        """Return the number of SlideDeckVersion rows for this deck."""
        db = self._factory()
        try:
            owner_id = self._owner_pk(self._session_id)
            return (
                db.query(SlideDeckVersion)
                .filter(SlideDeckVersion.session_id == owner_id)
                .count()
            )
        finally:
            db.close()


def _insert_three_rows(sid: str, factory) -> None:
    """Insert one UserSession + SessionSlideDeck + 3 SessionSlide rows."""
    db = factory()
    try:
        us = UserSession(session_id=sid, created_by="test-user@example.com")
        db.add(us)
        db.flush()

        slides_data = json.dumps(
            [
                {
                    "html": html,
                    "scripts": "",
                    "slide_id": str(uuid.uuid4()),
                    "created_by": "test-user@example.com",
                    "created_at": "2024-01-01T00:00:00Z",
                    "modified_by": "test-user@example.com",
                    "modified_at": "2024-01-01T00:00:00Z",
                }
                for html in _SLIDE_HTMLS
            ]
        )
        deck = SessionSlideDeck(
            session_id=us.id,
            title="Three-Row Test Deck",
            html_content="",
            scripts_content="",
            slide_count=3,
            deck_json=json.dumps(
                {
                    "title": "Three-Row Test Deck",
                    "css": "",
                    "external_scripts": [],
                    "scripts": "",
                    "slides": json.loads(slides_data),
                }
            ),
        )
        db.add(deck)
        db.flush()

        for pos, html in enumerate(_SLIDE_HTMLS):
            row = SessionSlide(
                session_id=us.id,
                position=pos,
                id=str(uuid.uuid4()),
                html=html,
                slide_id=str(uuid.uuid4()),
                scripts="",
                created_by="test-user@example.com",
                created_at=datetime.utcnow(),
                modified_by="test-user@example.com",
                modified_at=datetime.utcnow(),
            )
            db.add(row)

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@pytest.fixture
def deck_with_three_rows():
    """UserSession + SessionSlideDeck + 3 SessionSlide rows.

    The workhorse fixture: use it when a test needs slide rows, a deck dict,
    version management, or duplication.
    """
    engine = _make_in_memory_engine()
    factory = _make_factory(engine)
    sid = _new_session_id()
    _insert_three_rows(sid, factory)
    fixture = _DeckWithThreeRows(sid, engine, factory)
    yield fixture
    engine.dispose()


# ---------------------------------------------------------------------------
# deck_with_spec — deck_with_three_rows + parsed DeckSpec in deck_spec_json
# ---------------------------------------------------------------------------


class _DeckWithSpec(_DeckWithThreeRows):
    """deck_with_three_rows plus a loaded DeckSpec.

    Additional surface: set_spec_audience(audience: str)
    """

    def set_spec_audience(self, audience: str) -> None:
        """Update the spec's audience field and write back to deck_spec_json."""
        raw = self.deck_row().deck_spec_json
        spec = json.loads(raw) if raw else dict(_MINIMAL_DECK_SPEC)
        spec["audience"] = audience
        self.set_raw_deck_spec_json(json.dumps(spec))


@pytest.fixture
def deck_with_spec():
    """deck_with_three_rows plus a valid DeckSpec in deck_spec_json.

    Extra surface: set_spec_audience(str)
    """
    engine = _make_in_memory_engine()
    factory = _make_factory(engine)
    sid = _new_session_id()
    _insert_three_rows(sid, factory)

    # Write the spec into deck_spec_json
    db = factory()
    try:
        owner_id = (
            db.query(UserSession)
            .filter(UserSession.session_id == sid)
            .one()
            .id
        )
        deck = (
            db.query(SessionSlideDeck)
            .filter(SessionSlideDeck.session_id == owner_id)
            .one()
        )
        deck.deck_spec_json = json.dumps(_MINIMAL_DECK_SPEC)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    fixture = _DeckWithSpec(sid, engine, factory)
    yield fixture
    engine.dispose()


# ---------------------------------------------------------------------------
# deck_with_spec_but_no_rows — forces the deck_json blob-fallback read path
# ---------------------------------------------------------------------------


class _DeckWithSpecButNoRows(_FixtureBase):
    """UserSession + SessionSlideDeck with deck_spec_json, but NO SessionSlide rows.

    When get_slide_deck is called it falls through to the legacy deck_json
    blob path (the row-less branch in the dual-read logic).

    Surface: get_slide_deck()
    """

    def __init__(self, session_id: str, engine, factory):
        super().__init__(engine, factory)
        self._session_id = session_id

    @property
    def session_id(self) -> str:
        return self._session_id

    def get_slide_deck(self) -> Optional[Dict[str, Any]]:
        """Call SessionManager.get_slide_deck; exercises the blob-fallback path."""
        with self._patched():
            return self._sm.get_slide_deck(self._session_id)


@pytest.fixture
def deck_with_spec_but_no_rows():
    """UserSession + deck with deck_spec_json, no SessionSlide rows.

    Forces the deck_json blob-fallback read path in get_slide_deck.
    Surface: get_slide_deck()
    """
    engine = _make_in_memory_engine()
    factory = _make_factory(engine)
    sid = _new_session_id()

    blob_slides = [
        {
            "html": html,
            "scripts": "",
            "slide_id": str(uuid.uuid4()),
            "created_by": "test-user@example.com",
            "created_at": "2024-01-01T00:00:00Z",
            "modified_by": "test-user@example.com",
            "modified_at": "2024-01-01T00:00:00Z",
        }
        for html in _SLIDE_HTMLS
    ]
    deck_blob = json.dumps(
        {
            "title": "Spec-Only Deck",
            "css": "",
            "external_scripts": [],
            "scripts": "",
            "slides": blob_slides,
        }
    )

    db = factory()
    try:
        us = UserSession(session_id=sid, created_by="test-user@example.com")
        db.add(us)
        db.flush()
        deck = SessionSlideDeck(
            session_id=us.id,
            title="Spec-Only Deck",
            html_content="",
            scripts_content="",
            slide_count=3,
            deck_json=deck_blob,
            deck_spec_json=json.dumps(_MINIMAL_DECK_SPEC),
        )
        db.add(deck)
        db.commit()
        # Deliberately NO SessionSlide rows
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    fixture = _DeckWithSpecButNoRows(sid, engine, factory)
    yield fixture
    engine.dispose()


# ---------------------------------------------------------------------------
# deck_with_verdicts
# ---------------------------------------------------------------------------


class _DeckWithVerdicts(_DeckWithThreeRows):
    """deck_with_three_rows with verification_record written per slide.

    Verdicts are keyed by compute_slide_hash(html) so they survive a reorder.

    Surface: verdict_for_html_at(pos: int) -> Optional[dict]
    """

    def verdict_for_html_at(self, pos: int) -> Optional[Dict[str, Any]]:
        """Return the verdict for the slide at *pos*, or None if absent.

        Reads the raw verification_record from the row, parses it, and returns
        the verdict keyed by compute_slide_hash(html at that position).
        """
        db = self._factory()
        try:
            owner_id = self._owner_pk(self._session_id)
            row = (
                db.query(SessionSlide)
                .filter(
                    SessionSlide.session_id == owner_id,
                    SessionSlide.position == pos,
                )
                .one_or_none()
            )
            if not row or not row.verification_record:
                return None
            record = json.loads(row.verification_record)
            content_hash = compute_slide_hash(row.html)
            return record.get(content_hash)
        finally:
            db.close()


@pytest.fixture
def deck_with_verdicts():
    """deck_with_three_rows with a verification verdict written for each slide.

    Verdicts are hash-keyed so they survive position reorders.
    Surface: verdict_for_html_at(pos: int)
    """
    engine = _make_in_memory_engine()
    factory = _make_factory(engine)
    sid = _new_session_id()
    _insert_three_rows(sid, factory)

    # Write a verdict for each slide position using write_slide_verification
    sm = SessionManager()
    fake_db = _make_fake_db(factory)

    for pos, html in enumerate(_SLIDE_HTMLS):
        content_hash = compute_slide_hash(html)
        verdict = {"score": 70 + pos * 10, "rating": "amber", "issues": []}
        with patch("src.api.services.session_manager.get_db_session", fake_db):
            sm.write_slide_verification(
                session_id=sid,
                position=pos,
                verification_record={content_hash: verdict},
            )

    fixture = _DeckWithVerdicts(sid, engine, factory)
    yield fixture
    engine.dispose()


# ---------------------------------------------------------------------------
# deck_with_marker
# ---------------------------------------------------------------------------


class _DeckWithMarker(_FixtureBase):
    """UserSession + SessionSlideDeck + SlideDeckVersion(s) for restore tests.

    The deck starts with one committed version so restore_latest_version() has
    something to restore to.

    DIRTY-COLUMN STATUS: spec_dirty_at / spec_dirty_by / spec_dirty_claimed_at
    EXIST.  This same PR added them — declared on SessionSlideDeck
    (src/database/models/session.py) and added to already-provisioned databases
    by _migrate_spec_dirty_marker (src/core/database.py) — so set_marker() and
    set_claim() work against a live schema and their raw SQL succeeds.  Do NOT
    mark tests that call them xfail: they pass.  (An earlier revision of this
    docstring said the columns were still pending migration task B2.3 and told
    callers to xfail; that instruction is obsolete and was wrong to follow.)

    restore_latest_version() and restore_version(n) work right now.
    require_editing_lock passes when no lock is held (locked_by IS NULL).

    Surface: set_marker(age_seconds, author), set_claim(age_seconds),
             deck_row(), restore_latest_version(), restore_version(n)
    """

    def __init__(self, session_id: str, engine, factory):
        super().__init__(engine, factory)
        self._session_id = session_id

    @property
    def session_id(self) -> str:
        return self._session_id

    def deck_row(self) -> SessionSlideDeck:
        db = self._factory()
        try:
            owner_id = self._owner_pk(self._session_id)
            deck = (
                db.query(SessionSlideDeck)
                .filter(SessionSlideDeck.session_id == owner_id)
                .one()
            )
            db.expunge(deck)
            return deck
        finally:
            db.close()

    def set_marker(self, age_seconds: float = 0.0, author: str = "marker-user@example.com") -> None:
        """Set spec_dirty_at and spec_dirty_by on the deck row.

        The columns exist (see the class docstring); this works and needs no xfail.
        """
        db = self._factory()
        try:
            owner_id = self._owner_pk(self._session_id)
            deck = (
                db.query(SessionSlideDeck)
                .filter(SessionSlideDeck.session_id == owner_id)
                .one()
            )
            dirty_at = datetime.utcnow() - __import__('datetime').timedelta(seconds=age_seconds)
            db.execute(
                text(
                    "UPDATE session_slide_decks "
                    "SET spec_dirty_at = :at, spec_dirty_by = :by "
                    "WHERE id = :id"
                ),
                {"at": dirty_at, "by": author, "id": deck.id},
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def set_claim(self, age_seconds: float = 0.0) -> None:
        """Set spec_dirty_claimed_at on the deck row.

        The column exists (see the class docstring); this works and needs no xfail.
        """
        db = self._factory()
        try:
            owner_id = self._owner_pk(self._session_id)
            deck = (
                db.query(SessionSlideDeck)
                .filter(SessionSlideDeck.session_id == owner_id)
                .one()
            )
            claimed_at = datetime.utcnow() - __import__('datetime').timedelta(seconds=age_seconds)
            db.execute(
                text(
                    "UPDATE session_slide_decks "
                    "SET spec_dirty_claimed_at = :at "
                    "WHERE id = :id"
                ),
                {"at": claimed_at, "id": deck.id},
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def restore_latest_version(self) -> Dict[str, Any]:
        """Restore to the highest-numbered version.

        SessionManager has no restore_latest_version method; this fixture
        implements it: find the max version_number then call restore_version.
        require_editing_lock passes because locked_by IS NULL on this deck.
        """
        db = self._factory()
        try:
            owner_id = self._owner_pk(self._session_id)
            latest = (
                db.query(SlideDeckVersion)
                .filter(SlideDeckVersion.session_id == owner_id)
                .order_by(SlideDeckVersion.version_number.desc())
                .first()
            )
            if not latest:
                raise ValueError(
                    f"No versions exist for session {self._session_id}"
                )
            version_number = latest.version_number
        finally:
            db.close()

        return self.restore_version(version_number)

    def restore_version(self, n: int) -> Dict[str, Any]:
        """Call SessionManager.restore_version(session_id, n) with patched DB.

        The deck has no lock (locked_by IS NULL) so require_editing_lock passes.
        """
        with self._patched():
            return self._sm.restore_version(self._session_id, n)


@pytest.fixture
def deck_with_marker():
    """UserSession + SessionSlideDeck + one committed version.

    restore_latest_version() and restore_version(n) work immediately.  So do
    set_marker() and set_claim(): the three spec_dirty_* columns exist (this PR
    added them) — do NOT mark consuming tests xfail.

    Surface: set_marker(age_seconds, author), set_claim(age_seconds),
             deck_row(), restore_latest_version(), restore_version(n)
    """
    engine = _make_in_memory_engine()
    factory = _make_factory(engine)
    sid = _new_session_id()

    sm = SessionManager()
    fake_db = _make_fake_db(factory)

    # Set up session and deck
    db = factory()
    try:
        us = UserSession(session_id=sid, created_by="test-user@example.com")
        db.add(us)
        db.flush()

        slides_data = [
            {
                "html": _SLIDE_HTMLS[0],
                "scripts": "",
                "slide_id": str(uuid.uuid4()),
                "created_by": "test-user@example.com",
                "created_at": "2024-01-01T00:00:00Z",
                "modified_by": "test-user@example.com",
                "modified_at": "2024-01-01T00:00:00Z",
            }
        ]
        deck_dict = {
            "title": "Marker Test Deck",
            "css": "",
            "external_scripts": [],
            "scripts": "",
            "slides": slides_data,
        }
        deck = SessionSlideDeck(
            session_id=us.id,
            title="Marker Test Deck",
            html_content="",
            scripts_content="",
            slide_count=1,
            deck_json=json.dumps(deck_dict),
        )
        db.add(deck)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    # Create one version via SessionManager so restore has something to restore
    with patch("src.api.services.session_manager.get_db_session", fake_db):
        sm.create_version(
            session_id=sid,
            description="initial snapshot",
            deck_dict={
                "title": "Marker Test Deck",
                "css": "",
                "external_scripts": [],
                "scripts": "",
                "slides": [
                    {
                        "html": _SLIDE_HTMLS[0],
                        "scripts": "",
                        "slide_id": str(uuid.uuid4()),
                        "created_by": "test-user@example.com",
                        "created_at": "2024-01-01T00:00:00Z",
                        "modified_by": "test-user@example.com",
                        "modified_at": "2024-01-01T00:00:00Z",
                    }
                ],
            },
        )

    fixture = _DeckWithMarker(sid, engine, factory)
    yield fixture
    engine.dispose()


# ---------------------------------------------------------------------------
# contributor_session
# ---------------------------------------------------------------------------


class _ContributorSession(_FixtureBase):
    """Owner UserSession + SessionSlideDeck + contributor UserSession.

    A contributor session is a UserSession with parent_session_id set to the
    owner's integer PK.  _get_deck_owner_session follows that FK to the root.

    Surface: contributor_session_id, owner_deck_row()
    """

    def __init__(
        self,
        contributor_session_id: str,
        owner_session_id: str,
        engine,
        factory,
    ):
        super().__init__(engine, factory)
        self._contributor_session_id = contributor_session_id
        self._owner_session_id = owner_session_id

    @property
    def contributor_session_id(self) -> str:
        return self._contributor_session_id

    def owner_deck_row(self) -> SessionSlideDeck:
        """Return the owner's SessionSlideDeck (detached)."""
        db = self._factory()
        try:
            owner_id = self._owner_pk(self._owner_session_id)
            deck = (
                db.query(SessionSlideDeck)
                .filter(SessionSlideDeck.session_id == owner_id)
                .one()
            )
            db.expunge(deck)
            return deck
        finally:
            db.close()


@pytest.fixture
def contributor_session():
    """Owner session + contributor session (parent_session_id set to owner.id).

    A contributor writes through the same deck as the owner.
    Surface: contributor_session_id, owner_deck_row()
    """
    engine = _make_in_memory_engine()
    factory = _make_factory(engine)
    owner_sid = _new_session_id()
    contrib_sid = _new_session_id()

    db = factory()
    try:
        # Owner
        owner = UserSession(session_id=owner_sid, created_by="owner@example.com")
        db.add(owner)
        db.flush()

        deck = SessionSlideDeck(
            session_id=owner.id,
            title="Shared Deck",
            html_content="",
            scripts_content="",
            slide_count=0,
        )
        db.add(deck)
        db.flush()

        # Contributor — parent_session_id = owner.id (integer PK)
        contrib = UserSession(
            session_id=contrib_sid,
            created_by="contributor@example.com",
            parent_session_id=owner.id,
        )
        db.add(contrib)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    fixture = _ContributorSession(contrib_sid, owner_sid, engine, factory)
    yield fixture
    engine.dispose()


# ---------------------------------------------------------------------------
# contributor_session_with_spec
# ---------------------------------------------------------------------------


class _ContributorSessionWithSpec(_ContributorSession):
    """Contributor session where the owner deck also has deck_spec_json.

    Surface: contributor_session_id, owner_deck_row(),
             get_slide_deck_as_contributor()
    """

    def get_slide_deck_as_contributor(self) -> Optional[Dict[str, Any]]:
        """Call get_slide_deck with the contributor's session_id.

        §7.5: spec visibility equals deck visibility — the contributor sees the
        same deck_spec_json as the owner.
        """
        with self._patched():
            return self._sm.get_slide_deck(self._contributor_session_id)


@pytest.fixture
def contributor_session_with_spec():
    """Contributor session where the owner's deck carries deck_spec_json.

    §7.5: spec visibility equals deck visibility.
    Surface: contributor_session_id, owner_deck_row(), get_slide_deck_as_contributor()
    """
    engine = _make_in_memory_engine()
    factory = _make_factory(engine)
    owner_sid = _new_session_id()
    contrib_sid = _new_session_id()

    db = factory()
    try:
        owner = UserSession(session_id=owner_sid, created_by="owner@example.com")
        db.add(owner)
        db.flush()

        deck = SessionSlideDeck(
            session_id=owner.id,
            title="Shared Spec Deck",
            html_content="",
            scripts_content="",
            slide_count=0,
            deck_spec_json=json.dumps(_MINIMAL_DECK_SPEC),
        )
        db.add(deck)
        db.flush()

        contrib = UserSession(
            session_id=contrib_sid,
            created_by="contributor@example.com",
            parent_session_id=owner.id,
        )
        db.add(contrib)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    fixture = _ContributorSessionWithSpec(contrib_sid, owner_sid, engine, factory)
    yield fixture
    engine.dispose()


# ---------------------------------------------------------------------------
# Shared engine for session-level (non-deck) fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def _session_unit_engine():
    """Private function-scoped engine shared by session-level fixtures.

    Because pytest resolves function-scoped fixtures once per test, two fixtures
    that both depend on _session_unit_engine receive the SAME engine within a
    single test.  This lets session_with_messages and session_messages share a
    database: data written by the factory is immediately visible to the helper.
    """
    engine = _make_in_memory_engine()
    yield engine
    engine.dispose()


# ---------------------------------------------------------------------------
# session_with_messages — factory fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def session_with_messages(_session_unit_engine):
    """Factory fixture: creates a UserSession with SessionMessage rows.

    Usage: session_id = session_with_messages(["user msg 1", "user msg 2"])
           session_id = session_with_messages(["q"], assistant_messages=["a"])

    Returns the string session_id.
    ws4d's engine-mode resolution reads the earliest role='user' row.
    """
    factory = _make_factory(_session_unit_engine)

    def _make(user_msgs: List[str], assistant_messages: Optional[List[str]] = None) -> str:
        from datetime import timedelta as _td
        sid = _new_session_id()
        db = factory()
        try:
            us = UserSession(session_id=sid, created_by="test-user@example.com")
            db.add(us)
            db.flush()
            base = datetime.utcnow()
            for i, msg in enumerate(user_msgs):
                db.add(
                    SessionMessage(
                        session_id=us.id,
                        role="user",
                        content=msg,
                        created_at=base + _td(seconds=i),
                    )
                )
            for i, msg in enumerate(assistant_messages or []):
                db.add(
                    SessionMessage(
                        session_id=us.id,
                        role="assistant",
                        content=msg,
                        created_at=base + _td(seconds=100 + i),
                    )
                )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        return sid

    return _make


# ---------------------------------------------------------------------------
# session_messages — helper fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def session_messages(_session_unit_engine):
    """Helper fixture: returns messages for a session_id.

    Returns a callable: session_messages(sid) -> List[SessionMessage] (detached)

    ws4d asserts that the earliest role='user' row drives engine-mode resolution.
    When session_messages shares _session_unit_engine with session_with_messages,
    it can read data inserted by that factory.
    """
    factory = _make_factory(_session_unit_engine)

    def _helper(sid: str) -> List[SessionMessage]:
        db = factory()
        try:
            us = (
                db.query(UserSession)
                .filter(UserSession.session_id == sid)
                .one()
            )
            msgs = (
                db.query(SessionMessage)
                .filter(SessionMessage.session_id == us.id)
                .order_by(SessionMessage.created_at)
                .all()
            )
            for m in msgs:
                db.expunge(m)
            return msgs
        finally:
            db.close()

    return _helper


# ---------------------------------------------------------------------------
# empty_session
# ---------------------------------------------------------------------------


@pytest.fixture
def empty_session(_session_unit_engine):
    """A UserSession with no messages.  Returns the string session_id."""
    factory = _make_factory(_session_unit_engine)
    sid = _new_session_id()
    db = factory()
    try:
        db.add(UserSession(session_id=sid, created_by="test-user@example.com"))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return sid


# ---------------------------------------------------------------------------
# mcp_created_session
# ---------------------------------------------------------------------------


@pytest.fixture
def mcp_created_session(_session_unit_engine):
    """A UserSession created via the MCP pathway (no chat messages).

    agent_config carries an MCPTool entry so it is distinguishable from an
    empty_session when engine-mode resolution inspects agent_config.type.
    Returns the string session_id.
    """
    factory = _make_factory(_session_unit_engine)
    sid = _new_session_id()
    db = factory()
    try:
        mcp_config = {
            "tools": [
                {
                    "type": "mcp",
                    "connection_name": "test-connection",
                    "server_name": "test-server",
                    "description": "MCP test tool",
                    "config": {},
                }
            ]
        }
        db.add(
            UserSession(
                session_id=sid,
                created_by="mcp-user@example.com",
                agent_config=mcp_config,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return sid


# ---------------------------------------------------------------------------
# session_with_spec_and_messages
# ---------------------------------------------------------------------------


@pytest.fixture
def session_with_spec_and_messages(_session_unit_engine):
    """UserSession + chat messages + deck with deck_spec_json.

    Context clearing keeps the spec — asserts that clearing messages does not
    wipe deck_spec_json.
    Returns session_id (string).
    """
    factory = _make_factory(_session_unit_engine)
    sid = _new_session_id()
    db = factory()
    try:
        us = UserSession(session_id=sid, created_by="test-user@example.com")
        db.add(us)
        db.flush()

        db.add(
            SessionMessage(
                session_id=us.id,
                role="user",
                content="Initial question",
                created_at=datetime.utcnow(),
            )
        )
        deck = SessionSlideDeck(
            session_id=us.id,
            title="Spec Session",
            html_content="",
            scripts_content="",
            slide_count=0,
            deck_spec_json=json.dumps(_MINIMAL_DECK_SPEC),
        )
        db.add(deck)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return sid


# ---------------------------------------------------------------------------
# session_and_profile_with_legacy_blobs
# ---------------------------------------------------------------------------


class _LegacyBlobsFixture:
    """UserSession + ConfigProfile each carrying retired JSON keys in agent_config.

    B2.5's strip_retired_prompt_keys migration removes 'system_prompt' and
    'slide_editing_instructions' from agent_config blobs.  This fixture provides
    a before-state so tests can verify the migration cleans the blobs.

    Surface:
      session_local  — sessionmaker bound to this fixture's engine
      reload_blobs() — re-read agent_config from both rows; returns a dict
                       {"session": <value>, "profile": <value>}
    """

    def __init__(self, session_id: str, profile_name: str, factory):
        self.session_id = session_id
        self.profile_name = profile_name
        self.session_local = factory

    def reload_blobs(self) -> Dict[str, Any]:
        """Re-read agent_config from the session and profile rows."""
        db = self.session_local()
        try:
            session_cfg = (
                db.query(UserSession)
                .filter(UserSession.session_id == self.session_id)
                .one()
                .agent_config
            )
            profile_cfg = (
                db.query(ConfigProfile)
                .filter(ConfigProfile.name == self.profile_name)
                .one()
                .agent_config
            )
            return {"session": session_cfg, "profile": profile_cfg}
        finally:
            db.close()


@pytest.fixture
def session_and_profile_with_legacy_blobs():
    """UserSession + ConfigProfile with retired system_prompt / slide_editing_instructions keys.

    B2.5's strip_retired_prompt_keys migration must strip those keys.
    Surface: session_local (sessionmaker), session_id, profile_name, reload_blobs()
    """
    engine = _make_in_memory_engine()
    factory = _make_factory(engine)
    sid = _new_session_id()
    profile_name = f"test-profile-{uuid.uuid4().hex[:8]}"

    legacy_session_config = {
        "tools": [],
        "system_prompt": "You are a helpful assistant.",
        "slide_editing_instructions": "Use a formal tone.",
    }
    legacy_profile_config = {
        "tools": [],
        "system_prompt": "Default system prompt.",
        "slide_editing_instructions": "Keep slides concise.",
    }

    db = factory()
    try:
        db.add(
            UserSession(
                session_id=sid,
                created_by="test-user@example.com",
                agent_config=legacy_session_config,
            )
        )
        profile = ConfigProfile(
            name=profile_name,
            description="Legacy profile",
            is_default=False,
            agent_config=legacy_profile_config,
        )
        db.add(profile)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    fixture = _LegacyBlobsFixture(sid, profile_name, factory)
    yield fixture
    engine.dispose()


# ---------------------------------------------------------------------------
# session_with_garbage_blob
# ---------------------------------------------------------------------------


class _GarbageBlobFixture:
    """UserSession whose agent_config is a JSON list (not a dict).

    The ORM writes it as JSON so the read-back does not raise (the result
    processor decodes it as a list successfully).  But any caller that does
    agent_config.get("model") receives AttributeError because .get is not
    defined on list — the failure is inside the CALLER, where a guard can see
    it.

    IMPORTANT — both halves recorded (ruling R-G(i)):
      REACHABLE: an ORM-written non-dict blob (list, string) reads back
        without raising.  The consumer's .get() fails inside the function.
      NOT GUARDABLE: a raw-SQL blob that is genuinely unparseable JSON raises
        json.JSONDecodeError inside SQLAlchemy's result processor, BEFORE any
        code in the consumer runs.  No caller-side try can catch that.

    Surface: session_local (sessionmaker), session_id
    """

    def __init__(self, session_id: str, factory):
        self.session_id = session_id
        self.session_local = factory


@pytest.fixture
def session_with_garbage_blob():
    """UserSession with an agent_config that is a JSON list (survives decode, fails downstream).

    See _GarbageBlobFixture docstring for the two-halves ruling.
    Surface: session_local (sessionmaker), session_id
    """
    engine = _make_in_memory_engine()
    factory = _make_factory(engine)
    sid = _new_session_id()

    # Write a list via ORM — survives the result processor (decoded as list),
    # but consumer code calling .get("model") gets AttributeError.
    garbage_config = [1, 2, "not-a-dict"]

    db = factory()
    try:
        db.add(
            UserSession(
                session_id=sid,
                created_by="test-user@example.com",
                agent_config=garbage_config,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    fixture = _GarbageBlobFixture(sid, factory)
    yield fixture
    engine.dispose()


# ---------------------------------------------------------------------------
# as_user — context-manager fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def as_user():
    """Context-manager factory that stamps a user identity via set_current_user.

    Usage:
        with as_user("alice@example.com"):
            # get_current_user() returns "alice@example.com"
        # previous value is restored

    Restores the previous ContextVar value on exit, so tests are isolated even
    when nested or when the same test uses multiple identities.
    """
    @contextlib.contextmanager
    def _ctx(username: str):
        prev = get_current_user()
        set_current_user(username)
        try:
            yield
        finally:
            set_current_user(prev)

    return _ctx


# ---------------------------------------------------------------------------
# other_user — context-manager fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def other_user():
    """Context-manager that stamps a fixed alternative identity.

    Useful for permission-denial assertions where the test body runs as the
    default user and needs a distinct principal.

    Usage:
        with other_user():
            # get_current_user() returns "other-user@example.com"
    """
    @contextlib.contextmanager
    def _ctx():
        prev = get_current_user()
        set_current_user("other-user@example.com")
        try:
            yield
        finally:
            set_current_user(prev)

    return _ctx


# ---------------------------------------------------------------------------
# fake_queue
# ---------------------------------------------------------------------------


class FakeQueue:
    """In-memory queue with item capture.

    Wraps queue.Queue-compatible interface so it can be passed wherever a
    real queue.Queue is expected.  .items records everything that has been put
    on the queue, including after .get() removes it.

    ws4d asserts that the emitter queues StreamEvent OBJECTS, not strings:
        assert isinstance(fake_queue.items[0], StreamEvent)
    """

    def __init__(self):
        self.items: List[Any] = []
        self._q: queue.Queue = queue.Queue()

    def put(self, item: Any) -> None:
        self.items.append(item)
        self._q.put(item)

    def get(self, block: bool = True, timeout: Optional[float] = None) -> Any:
        return self._q.get(block=block, timeout=timeout)

    def empty(self) -> bool:
        return self._q.empty()

    def qsize(self) -> int:
        return self._q.qsize()


@pytest.fixture
def fake_queue():
    """A FakeQueue whose .items list captures every StreamEvent put on it.

    The emitter queues StreamEvent pydantic objects (not strings).
    Assert: isinstance(fake_queue.items[0], StreamEvent)
    """
    return FakeQueue()
