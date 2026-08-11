"""Tests for SlideWriter (src/api/services/slide_repository.py).

Uses in-memory SQLite via the same fixture pattern as
tests/integration/test_save_slide_deck_dual_write.py.

All tests are real — no pass-stubs.

Sabotage verification (per task brief):
- test_contributor_session_keying_uses_deck_owner_id:  if you sabotage
  SlideWriter to use session.id instead of deck_owner.id, this test fails
  with AssertionError because the row lands on the contributor session pk.

- test_verification_record_preserved_when_none:  if you sabotage write_slide
  to always overwrite verification_record (even when None is passed), this
  test fails because the original record is wiped.
"""
from __future__ import annotations

import contextlib
import json
import uuid
from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.database.models  # noqa: F401 — register all ORM models
from src.api.services.session_manager import SessionManager, SessionNotFoundError
from src.api.services.slide_repository import SlideWriter, _PLACEHOLDER_CLASS
from src.core.database import Base
from src.database.models.session import SessionSlide, UserSession


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sqlite_engine():
    """Fresh in-memory SQLite engine per test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def factory(sqlite_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=sqlite_engine)


@pytest.fixture()
def session_id(factory):
    """Create one root UserSession and return its string business key."""
    db = factory()
    us = UserSession(session_id="root-sess-001", created_by="owner@test.com")
    db.add(us)
    db.commit()
    db.close()
    return "root-sess-001"


def _make_fake_db(factory):
    """Return a context manager yielding a SQLAlchemy session from *factory*."""

    @contextlib.contextmanager
    def _cm():
        db = factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return _cm


def _get_slides(factory, owner_int_id: int):
    """Return all SessionSlide rows for owner, ordered by position, as dicts."""
    db = factory()
    rows = (
        db.query(SessionSlide)
        .filter(SessionSlide.session_id == owner_int_id)
        .order_by(SessionSlide.position)
        .all()
    )
    result = []
    for r in rows:
        result.append(
            {
                "session_id": r.session_id,
                "position": r.position,
                "html": r.html,
                "scripts": r.scripts,
                "verification_record": r.verification_record,
                "deck_spec_slide": r.deck_spec_slide,
                "id": r.id,
            }
        )
    db.close()
    return result


def _root_pk(factory) -> int:
    db = factory()
    pk = db.query(UserSession).filter(UserSession.session_id == "root-sess-001").one().id
    db.close()
    return pk


def _make_root_and_contributor(factory):
    """Return (root_str_sid, contrib_str_sid, root_int_pk, contrib_int_pk)."""
    db = factory()
    root = UserSession(session_id="root-contrib-001", created_by="owner@test.com")
    db.add(root)
    db.flush()
    contrib = UserSession(
        session_id="contrib-001",
        created_by="contrib@test.com",
        parent_session_id=root.id,
    )
    db.add(contrib)
    db.commit()
    root_pk = root.id
    contrib_pk = contrib.id
    db.close()
    return "root-contrib-001", "contrib-001", root_pk, contrib_pk


# ---------------------------------------------------------------------------
# Test: no-arg construction works (REQUIRED for PR3 graph nodes)
# ---------------------------------------------------------------------------


def test_no_arg_construction(factory):
    """SlideWriter() with no arguments must not raise."""
    fake_db = _make_fake_db(factory)
    with patch("src.api.services.slide_repository.get_db_session", fake_db):
        writer = SlideWriter()
    assert isinstance(writer, SlideWriter)
    assert writer.session_manager is not None


# ---------------------------------------------------------------------------
# Test: basic insert
# ---------------------------------------------------------------------------


def test_write_slide_inserts_row(factory, session_id):
    """write_slide creates a new row at the given position."""
    fake_db = _make_fake_db(factory)
    with patch("src.api.services.slide_repository.get_db_session", fake_db):
        writer = SlideWriter(SessionManager())
        writer.write_slide(
            session_id=session_id,
            position=0,
            html="<p>Hello</p>",
            scripts="console.log('a')",
            verification_record={"abc": {"score": 90}},
            deck_spec_slide={"purpose": "intro"},
            modified_by="user@test.com",
        )

    pk = _root_pk(factory)
    rows = _get_slides(factory, pk)
    assert len(rows) == 1
    assert rows[0]["position"] == 0
    assert rows[0]["html"] == "<p>Hello</p>"
    assert rows[0]["scripts"] == "console.log('a')"
    assert rows[0]["id"] is not None
    rec = json.loads(rows[0]["verification_record"])
    assert rec == {"abc": {"score": 90}}
    spec = json.loads(rows[0]["deck_spec_slide"])
    assert spec == {"purpose": "intro"}


# ---------------------------------------------------------------------------
# Test: update existing row (no duplicate)
# ---------------------------------------------------------------------------


def test_write_slide_updates_existing_row(factory, session_id):
    """Calling write_slide twice at the same position updates, never inserts a duplicate."""
    fake_db = _make_fake_db(factory)
    with patch("src.api.services.slide_repository.get_db_session", fake_db):
        writer = SlideWriter(SessionManager())
        writer.write_slide(session_id=session_id, position=0, html="<p>First</p>")
        writer.write_slide(session_id=session_id, position=0, html="<p>Second</p>")

    pk = _root_pk(factory)
    rows = _get_slides(factory, pk)
    assert len(rows) == 1, f"Expected 1 row (no duplicate), got {len(rows)}"
    assert rows[0]["html"] == "<p>Second</p>"


# ---------------------------------------------------------------------------
# Test: verification_record preservation when None is passed
# ---------------------------------------------------------------------------


def test_verification_record_preserved_when_none(factory, session_id):
    """If verification_record=None, the existing record is PRESERVED (not wiped)."""
    original = {"hash123": {"score": 95, "rating": "excellent"}}

    fake_db = _make_fake_db(factory)
    with patch("src.api.services.slide_repository.get_db_session", fake_db):
        writer = SlideWriter(SessionManager())
        # First write: set a verification record
        writer.write_slide(
            session_id=session_id,
            position=0,
            html="<p>Original</p>",
            verification_record=original,
        )
        # Second write: pass None — must NOT clear the record
        writer.write_slide(
            session_id=session_id,
            position=0,
            html="<p>Updated HTML</p>",
            verification_record=None,
        )

    pk = _root_pk(factory)
    rows = _get_slides(factory, pk)
    assert len(rows) == 1
    assert rows[0]["html"] == "<p>Updated HTML</p>"
    stored = json.loads(rows[0]["verification_record"])
    assert stored == original, (
        f"verification_record was wiped: expected {original}, got {stored}"
    )


# ---------------------------------------------------------------------------
# Test: deck_spec_slide preservation when None is passed
# ---------------------------------------------------------------------------


def test_deck_spec_slide_preserved_when_none(factory, session_id):
    """If deck_spec_slide=None, the existing spec is PRESERVED (not wiped)."""
    original_spec = {"purpose": "title slide", "data_references": []}

    fake_db = _make_fake_db(factory)
    with patch("src.api.services.slide_repository.get_db_session", fake_db):
        writer = SlideWriter(SessionManager())
        writer.write_slide(
            session_id=session_id,
            position=0,
            html="<p>v1</p>",
            deck_spec_slide=original_spec,
        )
        writer.write_slide(
            session_id=session_id,
            position=0,
            html="<p>v2</p>",
            deck_spec_slide=None,
        )

    pk = _root_pk(factory)
    rows = _get_slides(factory, pk)
    assert len(rows) == 1
    stored = json.loads(rows[0]["deck_spec_slide"])
    assert stored == original_spec, (
        f"deck_spec_slide was wiped: expected {original_spec}, got {stored}"
    )


# ---------------------------------------------------------------------------
# Test: JSON round-trip through get_slide
# ---------------------------------------------------------------------------


def test_verification_and_spec_roundtrip_via_get_slide(factory, session_id):
    """get_slide parses verification_record and deck_spec_slide from JSON."""
    vr = {"deadbeef": {"score": 80, "issues": ["minor"]}}
    ds = {"position": 0, "purpose": "agenda"}

    fake_db = _make_fake_db(factory)
    with patch("src.api.services.slide_repository.get_db_session", fake_db):
        writer = SlideWriter(SessionManager())
        writer.write_slide(
            session_id=session_id,
            position=0,
            html="<p>Content</p>",
            verification_record=vr,
            deck_spec_slide=ds,
        )
        result = writer.get_slide(session_id=session_id, position=0)

    assert result is not None
    assert result["verification_record"] == vr
    assert result["deck_spec_slide"] == ds
    assert "content_hash" in result
    assert isinstance(result["content_hash"], str)
    assert len(result["content_hash"]) > 0


# ---------------------------------------------------------------------------
# Test: get_slide returns None for missing row
# ---------------------------------------------------------------------------


def test_get_slide_returns_none_for_missing(factory, session_id):
    """get_slide must return None when the row does not exist."""
    fake_db = _make_fake_db(factory)
    with patch("src.api.services.slide_repository.get_db_session", fake_db):
        writer = SlideWriter(SessionManager())
        result = writer.get_slide(session_id=session_id, position=99)

    assert result is None


# ---------------------------------------------------------------------------
# Test: list_slides_in_position_order ordering and from_position filter
# ---------------------------------------------------------------------------


def test_list_slides_ordering_and_from_position(factory, session_id):
    """list_slides_in_position_order returns slides in ORDER BY position,
    even when seeded out of order, and respects from_position."""
    fake_db = _make_fake_db(factory)
    with patch("src.api.services.slide_repository.get_db_session", fake_db):
        writer = SlideWriter(SessionManager())
        # Insert out-of-order: position 2, then 0, then 1
        writer.write_slide(session_id=session_id, position=2, html="<p>C</p>")
        writer.write_slide(session_id=session_id, position=0, html="<p>A</p>")
        writer.write_slide(session_id=session_id, position=1, html="<p>B</p>")

        all_slides = writer.list_slides_in_position_order(session_id=session_id)
        from_1 = writer.list_slides_in_position_order(
            session_id=session_id, from_position=1
        )

    assert [s["position"] for s in all_slides] == [0, 1, 2], (
        f"Out-of-order seed not sorted: {[s['position'] for s in all_slides]}"
    )
    assert [s["html"] for s in all_slides] == ["<p>A</p>", "<p>B</p>", "<p>C</p>"]

    assert len(from_1) == 2
    assert from_1[0]["position"] == 1
    assert from_1[1]["position"] == 2


# ---------------------------------------------------------------------------
# Test: delete_slide
# ---------------------------------------------------------------------------


def test_delete_slide_removes_row(factory, session_id):
    """delete_slide must remove the row; subsequent get_slide returns None."""
    fake_db = _make_fake_db(factory)
    with patch("src.api.services.slide_repository.get_db_session", fake_db):
        writer = SlideWriter(SessionManager())
        writer.write_slide(session_id=session_id, position=0, html="<p>Gone</p>")
        writer.delete_slide(session_id=session_id, position=0)
        result = writer.get_slide(session_id=session_id, position=0)

    assert result is None


def test_delete_slide_is_noop_when_absent(factory, session_id):
    """delete_slide on a missing row must not raise."""
    fake_db = _make_fake_db(factory)
    with patch("src.api.services.slide_repository.get_db_session", fake_db):
        writer = SlideWriter(SessionManager())
        # Should not raise
        writer.delete_slide(session_id=session_id, position=999)


# ---------------------------------------------------------------------------
# Test: commit_placeholder — landed + distinguishable
# ---------------------------------------------------------------------------


def test_commit_placeholder_is_in_position_order_list(factory, session_id):
    """Invariant 1: list_slides_in_position_order includes a placeholder row."""
    fake_db = _make_fake_db(factory)
    with patch("src.api.services.slide_repository.get_db_session", fake_db):
        writer = SlideWriter(SessionManager())
        writer.commit_placeholder(
            session_id=session_id,
            position=3,
            error_message="timeout",
        )
        slides = writer.list_slides_in_position_order(session_id=session_id)

    positions = [s["position"] for s in slides]
    assert 3 in positions, f"Placeholder at position 3 not in list: {positions}"


def test_commit_placeholder_is_distinguishable(factory, session_id):
    """Invariant 2: placeholder is distinguishable from a real slide."""
    fake_db = _make_fake_db(factory)
    with patch("src.api.services.slide_repository.get_db_session", fake_db):
        writer = SlideWriter(SessionManager())
        writer.commit_placeholder(
            session_id=session_id,
            position=5,
            error_message="build crashed",
        )
        slide = writer.get_slide(session_id=session_id, position=5)

    assert slide is not None
    # HTML must contain the sentinel class
    assert _PLACEHOLDER_CLASS in slide["html"], (
        f"Placeholder html missing sentinel class '{_PLACEHOLDER_CLASS}': {slide['html']!r}"
    )
    # verification_record must carry error=True
    vr = slide.get("verification_record") or {}
    assert vr.get("error") is True, (
        f"Placeholder verification_record missing error=True: {vr}"
    )


# ---------------------------------------------------------------------------
# Test: contributor-session keying — rows land on ROOT session
# (SABOTAGE TARGET: change deck_owner.id → session.id to see it fail)
# ---------------------------------------------------------------------------


def test_contributor_session_keying_uses_deck_owner_id(factory):
    """write_slide via a contributor session must land on the ROOT session's id.

    This is the sharing-boundary correctness invariant. If write_slide keyed on
    session.id (the caller's id) instead of deck_owner.id, a contributor's edit
    would write to the wrong session slot, corrupting the deck.
    """
    root_sid, contrib_sid, root_pk, contrib_pk = _make_root_and_contributor(factory)

    fake_db = _make_fake_db(factory)
    with patch("src.api.services.slide_repository.get_db_session", fake_db):
        writer = SlideWriter(SessionManager())
        writer.write_slide(
            session_id=contrib_sid,  # caller is the contributor
            position=0,
            html="<p>From contributor</p>",
        )
        # Read back using the root session id (to confirm where the row landed)
        rows_on_root = _get_slides(factory, root_pk)
        rows_on_contrib = _get_slides(factory, contrib_pk)

    assert len(rows_on_root) == 1, (
        f"Expected 1 row on root (pk={root_pk}), got {len(rows_on_root)}"
    )
    assert rows_on_root[0]["html"] == "<p>From contributor</p>"
    assert rows_on_contrib == [], (
        f"Row landed on contributor (pk={contrib_pk}) instead of root — "
        f"session keying is broken"
    )


# ---------------------------------------------------------------------------
# Test: SessionNotFoundError for unknown session
# ---------------------------------------------------------------------------


def test_session_not_found_error_on_write(factory):
    """write_slide raises SessionNotFoundError for an unknown session_id."""
    fake_db = _make_fake_db(factory)
    with patch("src.api.services.slide_repository.get_db_session", fake_db):
        writer = SlideWriter(SessionManager())
        with pytest.raises(SessionNotFoundError):
            writer.write_slide(
                session_id="does-not-exist",
                position=0,
                html="<p>x</p>",
            )


def test_session_not_found_error_on_get(factory):
    """get_slide raises SessionNotFoundError for an unknown session_id."""
    fake_db = _make_fake_db(factory)
    with patch("src.api.services.slide_repository.get_db_session", fake_db):
        writer = SlideWriter(SessionManager())
        with pytest.raises(SessionNotFoundError):
            writer.get_slide(session_id="does-not-exist", position=0)


def test_session_not_found_error_on_list(factory):
    """list_slides_in_position_order raises SessionNotFoundError for unknown session."""
    fake_db = _make_fake_db(factory)
    with patch("src.api.services.slide_repository.get_db_session", fake_db):
        writer = SlideWriter(SessionManager())
        with pytest.raises(SessionNotFoundError):
            writer.list_slides_in_position_order(session_id="does-not-exist")
