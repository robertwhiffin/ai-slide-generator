"""Final-review fixes for SlideWriter (F6, F8, F9).

  F6  commit_placeholder wrote ``{"error": True, "message": ...}`` — NOT hash-keyed.
      It was therefore unreadable through get_slide_deck (which does
      ``.get(content_hash)``) and it polluted get_verification_map's flat
      aggregate, persisting "error"/"message" keys into save-point
      verification_map_json.
  F8  write_slide's UPDATE branch set ``existing.modified_by = modified_by``
      unconditionally, so a call omitting modified_by nulled the existing author.
  F9  write_slide's INSERT never set slide_id, so PR3-authored slides arrived
      with ``slide_id: null`` (the frontend declares it non-optional and uses it
      as the dnd/React key).

Signature note: PR3 is already written against write_slide/get_slide/
list_slides_in_position_order/delete_slide/commit_placeholder, the no-arg
constructor, and the absence of VersionConflictError.  These tests only exercise
the published signatures plus the new optional ``slide_id`` keyword.
"""
from __future__ import annotations

import contextlib
import json
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.database.models  # noqa: F401
from src.api.services.session_manager import SessionManager
from src.api.services.slide_repository import (
    PLACEHOLDER_ERROR_KEY,
    SlideWriter,
    is_placeholder_record,
)
from src.core.database import Base
from src.database.models.session import SessionSlide, SessionSlideDeck, UserSession
from src.utils.slide_hash import compute_slide_hash


@pytest.fixture()
def sqlite_engine():
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
    """A session that already owns a (row-less) slide deck."""
    db = factory()
    us = UserSession(session_id="writer-session-001", created_by="owner@example.com")
    db.add(us)
    db.flush()
    db.add(
        SessionSlideDeck(
            session_id=us.id,
            title="Deck",
            html_content="",
            scripts_content="",
            slide_count=0,
            deck_json=json.dumps({"title": "Deck", "slides": []}),
            version=1,
            css="",
            external_scripts_json="[]",
        )
    )
    db.commit()
    db.close()
    return "writer-session-001"


def _fake_db(factory):
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


@contextlib.contextmanager
def _patched(factory):
    fake = _fake_db(factory)
    with patch("src.api.services.slide_repository.get_db_session", fake):
        with patch("src.api.services.session_manager.get_db_session", fake):
            with patch(
                "src.services.identity_provider.resolve_display_names",
                lambda emails: {},
            ):
                yield


def _owner_pk(factory) -> int:
    db = factory()
    pk = db.query(UserSession).filter(UserSession.session_id == "writer-session-001").one().id
    db.close()
    return pk


def _raw_rows(factory):
    db = factory()
    rows = (
        db.query(SessionSlide)
        .filter(SessionSlide.session_id == _owner_pk(factory))
        .order_by(SessionSlide.position)
        .all()
    )
    out = [
        {
            "position": r.position,
            "html": r.html,
            "slide_id": r.slide_id,
            "created_by": r.created_by,
            "modified_by": r.modified_by,
            "verification_record": r.verification_record,
        }
        for r in rows
    ]
    db.close()
    return out


# ---------------------------------------------------------------------------
# F8 — the UPDATE branch must not null modified_by
# ---------------------------------------------------------------------------


def test_write_slide_update_does_not_null_modified_by(factory, session_id):
    with _patched(factory):
        writer = SlideWriter(SessionManager())
        writer.write_slide(
            session_id=session_id,
            position=0,
            html="<p>v1</p>",
            modified_by="reviewer@example.com",
        )
        # PR3's reviewer nodes rewrite HTML without passing modified_by
        writer.write_slide(session_id=session_id, position=0, html="<p>v2</p>")

    rows = _raw_rows(factory)
    assert len(rows) == 1
    assert rows[0]["html"] == "<p>v2</p>"
    assert rows[0]["modified_by"] == "reviewer@example.com", (
        f"write_slide nulled modified_by on update: {rows[0]['modified_by']!r}"
    )


def test_write_slide_update_does_not_null_created_by(factory, session_id):
    with _patched(factory):
        writer = SlideWriter(SessionManager())
        writer.write_slide(
            session_id=session_id,
            position=0,
            html="<p>v1</p>",
            modified_by="builder@example.com",
        )
        writer.write_slide(session_id=session_id, position=0, html="<p>v2</p>")

    rows = _raw_rows(factory)
    assert rows[0]["created_by"] == "builder@example.com", (
        f"write_slide nulled created_by on update: {rows[0]['created_by']!r}"
    )


def test_write_slide_update_still_overwrites_modified_by_when_given(factory, session_id):
    with _patched(factory):
        writer = SlideWriter(SessionManager())
        writer.write_slide(
            session_id=session_id, position=0, html="<p>v1</p>", modified_by="first@example.com"
        )
        writer.write_slide(
            session_id=session_id, position=0, html="<p>v2</p>", modified_by="second@example.com"
        )

    rows = _raw_rows(factory)
    assert rows[0]["modified_by"] == "second@example.com"


# ---------------------------------------------------------------------------
# F9 — slide_id must be set
# ---------------------------------------------------------------------------


def test_write_slide_insert_sets_slide_id(factory, session_id):
    """A row written by SlideWriter must carry a non-null slide_id.

    The frontend type declares ``slide_id: string`` (non-optional) and uses it as
    the dnd/React key, so a null breaks the thumbnail ribbon.
    """
    with _patched(factory):
        SlideWriter(SessionManager()).write_slide(
            session_id=session_id, position=0, html="<p>Agent slide</p>"
        )

    rows = _raw_rows(factory)
    assert rows[0]["slide_id"] is not None, "SlideWriter INSERT left slide_id NULL"
    assert isinstance(rows[0]["slide_id"], str)
    assert rows[0]["slide_id"]


def test_write_slide_honours_explicit_slide_id(factory, session_id):
    with _patched(factory):
        SlideWriter(SessionManager()).write_slide(
            session_id=session_id, position=0, html="<p>x</p>", slide_id="explicit-id"
        )

    assert _raw_rows(factory)[0]["slide_id"] == "explicit-id"


def test_write_slide_update_preserves_slide_id_when_omitted(factory, session_id):
    with _patched(factory):
        writer = SlideWriter(SessionManager())
        writer.write_slide(
            session_id=session_id, position=0, html="<p>v1</p>", slide_id="stable-id"
        )
        writer.write_slide(session_id=session_id, position=0, html="<p>v2</p>")

    assert _raw_rows(factory)[0]["slide_id"] == "stable-id", (
        "an omitted slide_id must not clear the existing one"
    )


# ---------------------------------------------------------------------------
# F6 — commit_placeholder's record must be hash-keyed
# ---------------------------------------------------------------------------


class TestPlaceholderRecordIsHashKeyed:
    def test_record_is_keyed_by_the_placeholder_html_hash(self, factory, session_id):
        with _patched(factory):
            writer = SlideWriter(SessionManager())
            writer.commit_placeholder(
                session_id=session_id, position=0, error_message="builder crashed"
            )
            slide = writer.get_slide(session_id=session_id, position=0)

        assert slide is not None
        record = slide["verification_record"]
        expected_hash = compute_slide_hash(slide["html"])
        assert set(record.keys()) == {expected_hash}, (
            f"placeholder record is not hash-keyed: keys={sorted(record.keys())}"
        )
        assert record[expected_hash][PLACEHOLDER_ERROR_KEY] is True
        assert record[expected_hash]["message"] == "builder crashed"

    def test_record_is_readable_through_get_slide_deck(self, factory, session_id):
        """get_slide_deck resolves verification via ``.get(content_hash)``."""
        with _patched(factory):
            SlideWriter(SessionManager()).commit_placeholder(
                session_id=session_id, position=0, error_message="timeout"
            )
            deck = SessionManager().get_slide_deck(session_id)

        assert deck is not None
        verdict = deck["slides"][0]["verification"]
        assert verdict is not None, (
            "placeholder record unreadable through get_slide_deck (returned None)"
        )
        assert verdict[PLACEHOLDER_ERROR_KEY] is True
        assert verdict["message"] == "timeout"

    def test_record_does_not_pollute_get_verification_map(self, factory, session_id):
        """The flat aggregate must not gain bare ``error``/``message`` keys.

        get_verification_map feeds create_version, so a non-hash key persists into
        save-point verification_map_json forever.
        """
        with _patched(factory):
            SlideWriter(SessionManager()).commit_placeholder(
                session_id=session_id, position=0, error_message="boom"
            )
            vmap = SessionManager().get_verification_map(session_id)

        assert "error" not in vmap, f"'error' leaked into the flat map: {sorted(vmap)}"
        assert "message" not in vmap, f"'message' leaked into the flat map: {sorted(vmap)}"
        assert len(vmap) == 1
        only_key = next(iter(vmap))
        assert len(only_key) == 16 and all(c in "0123456789abcdef" for c in only_key), (
            f"map key is not a content hash: {only_key!r}"
        )

    def test_placeholder_is_still_detectable(self, factory, session_id):
        """A robust placeholder check must still work for PR3 / the UI badge."""
        with _patched(factory):
            writer = SlideWriter(SessionManager())
            writer.commit_placeholder(
                session_id=session_id, position=0, error_message="failed"
            )
            writer.write_slide(
                session_id=session_id,
                position=1,
                html="<p>real slide</p>",
                verification_record={compute_slide_hash("<p>real slide</p>"): {"score": 90}},
            )
            slides = writer.list_slides_in_position_order(session_id=session_id)

        assert is_placeholder_record(slides[0]["verification_record"]) is True
        assert is_placeholder_record(slides[1]["verification_record"]) is False
        assert is_placeholder_record(None) is False

    def test_placeholder_verdict_from_get_slide_deck_carries_error_flag(
        self, factory, session_id
    ):
        """A per-task review advised keying the UI on verification_record["error"].

        After hash-keying, the *resolved verdict* (what the UI actually sees on
        ``slide.verification``) still carries the error flag.
        """
        with _patched(factory):
            SlideWriter(SessionManager()).commit_placeholder(
                session_id=session_id, position=0, error_message="nope"
            )
            deck = SessionManager().get_slide_deck(session_id)

        assert deck["slides"][0]["verification"].get(PLACEHOLDER_ERROR_KEY) is True
