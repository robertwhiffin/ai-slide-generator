"""Final-review fixes: row identity + verdict attribution across position mutations.

Covers the F1/F2 blocker from the whole-branch final review (and F5/F6/F8/F9/F10):

  F1  the dual-write UPDATE branch left slide_id / created_by / created_at pinned
      to the *position*, so a reorder reattached them to the wrong slide.
  F2  same cause for verification_record: a reorder stranded slide A's verdict on
      the row that now holds slide B, and A's verdict resolved to None (lost).
  F5  the row read path dropped head_meta (and per-slide index).
  F6  commit_placeholder wrote a non-hash-keyed verification_record.
  F8  SlideWriter.write_slide's UPDATE nulled modified_by unguarded.
  F9  SlideWriter never set slide_id.
  F10 only the backfill normalised tz-aware timestamps to naive UTC.

Pattern: in-memory SQLite via
  patch("src.api.services.session_manager.get_db_session", fake_get_db_session)
— the same approach used by test_save_slide_deck_dual_write.py.
"""
from __future__ import annotations

import contextlib
import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.database.models  # noqa: F401 — register all ORM models
from src.api.services.session_manager import SessionManager
from src.core.database import Base
from src.database.models.session import SessionSlide, SessionSlideDeck, UserSession
from src.utils.slide_hash import compute_slide_hash


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
    db = factory()
    db.add(UserSession(session_id="test-session-001", created_by="test-user@example.com"))
    db.commit()
    db.close()
    return "test-session-001"


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


def _owner_pk(factory) -> int:
    db = factory()
    pk = db.query(UserSession).filter(UserSession.session_id == "test-session-001").one().id
    db.close()
    return pk


def _rows(factory, owner_id: int) -> List[Dict[str, Any]]:
    db = factory()
    out = []
    for r in (
        db.query(SessionSlide)
        .filter(SessionSlide.session_id == owner_id)
        .order_by(SessionSlide.position)
        .all()
    ):
        out.append(
            {
                "position": r.position,
                "html": r.html,
                "slide_id": r.slide_id,
                "scripts": r.scripts,
                "created_by": r.created_by,
                "created_at": r.created_at,
                "modified_by": r.modified_by,
                "modified_at": r.modified_at,
                "verification_record": (
                    json.loads(r.verification_record) if r.verification_record else None
                ),
            }
        )
    db.close()
    return out


def _slide(
    html: str,
    slide_id: str,
    created_by: str = "author@example.com",
    created_at: str = "2024-01-01T00:00:00Z",
) -> Dict[str, Any]:
    return {
        "html": html,
        "slide_id": slide_id,
        "scripts": "",
        "created_by": created_by,
        "created_at": created_at,
        "modified_by": created_by,
        "modified_at": created_at,
    }


def _deck(slides: List[Dict[str, Any]], **extra) -> Dict[str, Any]:
    d = {
        "title": "Reorder Deck",
        "css": ".a{}",
        "external_scripts": ["https://cdn.jsdelivr.net/npm/chart.js"],
        "scripts": "",
        "slides": slides,
    }
    d.update(extra)
    return d


def _save(mgr, factory, session_id: str, deck_dict: Dict[str, Any], **kw) -> None:
    with patch("src.api.services.session_manager.get_db_session", _fake_db(factory)):
        mgr.save_slide_deck(
            session_id=session_id,
            title=deck_dict.get("title"),
            html_content="",
            slide_count=len(deck_dict.get("slides") or []),
            deck_dict=deck_dict,
            **kw,
        )


def _verify(mgr, factory, session_id: str, position: int, html: str, verdict: dict) -> None:
    """Write a verdict for the slide currently at *position*, keyed by its hash."""
    with patch("src.api.services.session_manager.get_db_session", _fake_db(factory)):
        mgr.write_slide_verification(
            session_id=session_id,
            position=position,
            verification_record={compute_slide_hash(html): verdict},
        )


def _read(mgr, factory, session_id: str) -> Dict[str, Any]:
    with patch("src.api.services.session_manager.get_db_session", _fake_db(factory)):
        with patch(
            "src.services.identity_provider.resolve_display_names",
            lambda emails: {},
        ):
            return mgr.get_slide_deck(session_id)


# ---------------------------------------------------------------------------
# F1 / F2 — the controller's live repro, as a test
# ---------------------------------------------------------------------------

HTML_A = "<p>A</p>"
HTML_B = "<p>B</p>"
HTML_C = "<p>C</p>"
VERDICT_A = {"score": 99, "rating": "excellent"}
VERDICT_B = {"score": 42, "rating": "poor"}


class TestReorderPreservesIdentityAndVerdicts:
    """The exact scenario the controller reproduced against live code:

        2 slides A,B; verdict written on A at position 0; then reorder to B,A.

    Broken behaviour observed:
        pos=0 html='<p>B</p>' slide_id='id-A' verdict={hash_of_A: {...}}
        pos=1 html='<p>A</p>' slide_id='id-B' verdict=None

    slide_id was attached to the wrong slide, and A's verdict sat on B's row —
    so get_slide_deck's `.get(compute_slide_hash(row.html))` returned None for A
    and the verdict was user-visibly LOST.
    """

    def test_reorder_moves_slide_id_with_its_slide(self, factory, session_id):
        mgr = SessionManager()
        _save(mgr, factory, session_id, _deck([_slide(HTML_A, "id-A"), _slide(HTML_B, "id-B")]))

        # Reorder: B, A
        _save(mgr, factory, session_id, _deck([_slide(HTML_B, "id-B"), _slide(HTML_A, "id-A")]))

        rows = _rows(factory, _owner_pk(factory))
        assert [r["html"] for r in rows] == [HTML_B, HTML_A]
        assert rows[0]["slide_id"] == "id-B", (
            f"position 0 holds {rows[0]['html']!r} but carries slide_id "
            f"{rows[0]['slide_id']!r} — identity attached to the WRONG slide"
        )
        assert rows[1]["slide_id"] == "id-A", (
            f"position 1 holds {rows[1]['html']!r} but carries slide_id "
            f"{rows[1]['slide_id']!r} — identity attached to the WRONG slide"
        )

    def test_reorder_moves_verdict_with_its_slide(self, factory, session_id):
        mgr = SessionManager()
        _save(mgr, factory, session_id, _deck([_slide(HTML_A, "id-A"), _slide(HTML_B, "id-B")]))

        # Verify A (currently at position 0)
        _verify(mgr, factory, session_id, 0, HTML_A, VERDICT_A)

        # Reorder: B, A
        _save(mgr, factory, session_id, _deck([_slide(HTML_B, "id-B"), _slide(HTML_A, "id-A")]))

        rows = _rows(factory, _owner_pk(factory))
        hash_a, hash_b = compute_slide_hash(HTML_A), compute_slide_hash(HTML_B)

        assert rows[0]["html"] == HTML_B
        assert hash_a not in (rows[0]["verification_record"] or {}), (
            f"A's verdict is stranded on B's row: {rows[0]['verification_record']!r}"
        )
        assert rows[1]["html"] == HTML_A
        assert (rows[1]["verification_record"] or {}).get(hash_a) == VERDICT_A, (
            f"A's verdict did not follow A to position 1: "
            f"{rows[1]['verification_record']!r}"
        )
        assert hash_b not in (rows[1]["verification_record"] or {})

    def test_reorder_verdict_still_resolves_through_get_slide_deck(self, factory, session_id):
        """The user-visible symptom: A's verdict must not read back as None."""
        mgr = SessionManager()
        _save(mgr, factory, session_id, _deck([_slide(HTML_A, "id-A"), _slide(HTML_B, "id-B")]))
        _verify(mgr, factory, session_id, 0, HTML_A, VERDICT_A)
        _save(mgr, factory, session_id, _deck([_slide(HTML_B, "id-B"), _slide(HTML_A, "id-A")]))

        deck = _read(mgr, factory, session_id)
        by_html = {s["html"]: s for s in deck["slides"]}
        assert by_html[HTML_A]["verification"] == VERDICT_A, (
            f"A's verdict LOST through the row read path: "
            f"{by_html[HTML_A]['verification']!r}"
        )
        assert by_html[HTML_B]["verification"] is None, (
            f"B inherited A's verdict: {by_html[HTML_B]['verification']!r}"
        )

    def test_reorder_both_verdicts_follow_their_slides(self, factory, session_id):
        """Both A's and B's verdicts must follow their slides, not their positions."""
        mgr = SessionManager()
        _save(mgr, factory, session_id, _deck([_slide(HTML_A, "id-A"), _slide(HTML_B, "id-B")]))
        _verify(mgr, factory, session_id, 0, HTML_A, VERDICT_A)
        _verify(mgr, factory, session_id, 1, HTML_B, VERDICT_B)

        _save(mgr, factory, session_id, _deck([_slide(HTML_B, "id-B"), _slide(HTML_A, "id-A")]))

        deck = _read(mgr, factory, session_id)
        by_html = {s["html"]: s for s in deck["slides"]}
        assert by_html[HTML_A]["verification"] == VERDICT_A
        assert by_html[HTML_B]["verification"] == VERDICT_B

    def test_reorder_moves_authorship_with_its_slide(self, factory, session_id):
        """created_by/created_at are per-slide identity and must move with the slide."""
        mgr = SessionManager()
        _save(
            mgr,
            factory,
            session_id,
            _deck(
                [
                    _slide(HTML_A, "id-A", created_by="alice@example.com",
                           created_at="2024-01-01T00:00:00Z"),
                    _slide(HTML_B, "id-B", created_by="bob@example.com",
                           created_at="2024-06-01T00:00:00Z"),
                ]
            ),
        )
        _save(
            mgr,
            factory,
            session_id,
            _deck(
                [
                    _slide(HTML_B, "id-B", created_by="bob@example.com",
                           created_at="2024-06-01T00:00:00Z"),
                    _slide(HTML_A, "id-A", created_by="alice@example.com",
                           created_at="2024-01-01T00:00:00Z"),
                ]
            ),
        )

        rows = _rows(factory, _owner_pk(factory))
        assert rows[0]["html"] == HTML_B
        assert rows[0]["created_by"] == "bob@example.com", (
            f"Bob's slide reports created_by={rows[0]['created_by']!r}"
        )
        assert rows[0]["created_at"] == datetime(2024, 6, 1, 0, 0, 0)
        assert rows[1]["html"] == HTML_A
        assert rows[1]["created_by"] == "alice@example.com"
        assert rows[1]["created_at"] == datetime(2024, 1, 1, 0, 0, 0)


class TestInsertAndDeleteShiftPositions:
    def test_insert_at_front_does_not_misattribute(self, factory, session_id):
        mgr = SessionManager()
        _save(mgr, factory, session_id, _deck([_slide(HTML_A, "id-A"), _slide(HTML_B, "id-B")]))
        _verify(mgr, factory, session_id, 0, HTML_A, VERDICT_A)
        _verify(mgr, factory, session_id, 1, HTML_B, VERDICT_B)

        # Insert C at the front: C, A, B
        _save(
            mgr,
            factory,
            session_id,
            _deck([_slide(HTML_C, "id-C"), _slide(HTML_A, "id-A"), _slide(HTML_B, "id-B")]),
        )

        rows = _rows(factory, _owner_pk(factory))
        assert [r["html"] for r in rows] == [HTML_C, HTML_A, HTML_B]
        assert [r["slide_id"] for r in rows] == ["id-C", "id-A", "id-B"]

        deck = _read(mgr, factory, session_id)
        by_html = {s["html"]: s for s in deck["slides"]}
        assert by_html[HTML_C]["verification"] is None, (
            f"new slide C inherited a verdict: {by_html[HTML_C]['verification']!r}"
        )
        assert by_html[HTML_A]["verification"] == VERDICT_A
        assert by_html[HTML_B]["verification"] == VERDICT_B

    def test_delete_middle_does_not_misattribute(self, factory, session_id):
        mgr = SessionManager()
        _save(
            mgr,
            factory,
            session_id,
            _deck([_slide(HTML_A, "id-A"), _slide(HTML_B, "id-B"), _slide(HTML_C, "id-C")]),
        )
        _verify(mgr, factory, session_id, 0, HTML_A, VERDICT_A)
        _verify(mgr, factory, session_id, 2, HTML_C, {"score": 77})

        # Delete the middle slide: A, C
        _save(mgr, factory, session_id, _deck([_slide(HTML_A, "id-A"), _slide(HTML_C, "id-C")]))

        rows = _rows(factory, _owner_pk(factory))
        assert [r["html"] for r in rows] == [HTML_A, HTML_C]
        assert [r["slide_id"] for r in rows] == ["id-A", "id-C"]

        deck = _read(mgr, factory, session_id)
        by_html = {s["html"]: s for s in deck["slides"]}
        assert by_html[HTML_A]["verification"] == VERDICT_A
        assert by_html[HTML_C]["verification"] == {"score": 77}, (
            f"C's verdict lost when B was deleted: {by_html[HTML_C]['verification']!r}"
        )


class TestHashKeyedHistoryStillSurvivesEdits:
    """Regression guard: the hash-keyed history property (spec §5.2.4 / PRD §12.1).

    Editing a slide and reverting it must find the original verdict again.  This
    is what the hash-keyed record buys, and the fix must not trade it away.
    """

    def test_edit_then_revert_recovers_verdict(self, factory, session_id):
        mgr = SessionManager()
        _save(mgr, factory, session_id, _deck([_slide(HTML_A, "id-A")]))
        _verify(mgr, factory, session_id, 0, HTML_A, VERDICT_A)

        edited = "<p>A edited</p>"
        _save(mgr, factory, session_id, _deck([_slide(edited, "id-A")]))
        deck = _read(mgr, factory, session_id)
        assert deck["slides"][0]["verification"] is None, "edited content must be unverified"

        # Revert to the original content
        _save(mgr, factory, session_id, _deck([_slide(HTML_A, "id-A")]))
        deck = _read(mgr, factory, session_id)
        assert deck["slides"][0]["verification"] == VERDICT_A, (
            "reverting to verified content must recover the hash-keyed verdict; got "
            f"{deck['slides'][0]['verification']!r}"
        )


# ---------------------------------------------------------------------------
# F5 — head_meta (and the per-slide `index` key) must survive the row path
# ---------------------------------------------------------------------------


class TestDeckDictKeysSurviveRowPath:
    HEAD_META = {"charset": "utf-8", "viewport": "width=1280, initial-scale=0.8"}

    def test_head_meta_survives_row_round_trip(self, factory, session_id):
        mgr = SessionManager()
        _save(
            mgr,
            factory,
            session_id,
            _deck([_slide(HTML_A, "id-A")], head_meta=self.HEAD_META),
        )

        deck = _read(mgr, factory, session_id)
        assert deck.get("head_meta") == self.HEAD_META, (
            f"row read path dropped head_meta: {deck.get('head_meta')!r}"
        )

    def test_head_meta_survives_a_full_domain_round_trip(self, factory, session_id):
        """get_slide_deck -> SlideDeck.from_dict -> to_dict -> save_slide_deck (F3 path)."""
        from src.domain.slide_deck import SlideDeck

        mgr = SessionManager()
        _save(
            mgr,
            factory,
            session_id,
            _deck([_slide(HTML_A, "id-A")], head_meta=self.HEAD_META),
        )

        read_back = _read(mgr, factory, session_id)
        round_tripped = SlideDeck.from_dict(read_back).to_dict()
        _save(mgr, factory, session_id, round_tripped)

        deck = _read(mgr, factory, session_id)
        assert deck.get("head_meta") == self.HEAD_META, (
            f"head_meta lost after one chat_service-style round trip: "
            f"{deck.get('head_meta')!r}"
        )

    def test_per_slide_index_present_on_row_path(self, factory, session_id):
        mgr = SessionManager()
        _save(
            mgr,
            factory,
            session_id,
            _deck([_slide(HTML_A, "id-A"), _slide(HTML_B, "id-B")]),
        )
        deck = _read(mgr, factory, session_id)
        assert [s.get("index") for s in deck["slides"]] == [0, 1], (
            f"row read path dropped per-slide index: "
            f"{[s.get('index') for s in deck['slides']]}"
        )

    def test_row_path_emits_every_to_dict_key(self, factory, session_id):
        """Enumerate SlideDeck.to_dict()'s keys against the row branch's output."""
        from src.domain.slide import Slide
        from src.domain.slide_deck import SlideDeck

        reference = SlideDeck(
            title="T",
            css=".a{}",
            external_scripts=["https://cdn.jsdelivr.net/npm/chart.js"],
            slides=[
                Slide(
                    html=HTML_A,
                    slide_id="id-A",
                    scripts="",
                    created_by="author@example.com",
                    created_at="2024-01-01T00:00:00Z",
                    modified_by="author@example.com",
                    modified_at="2024-01-01T00:00:00Z",
                )
            ],
            head_meta=self.HEAD_META,
        ).to_dict()

        mgr = SessionManager()
        _save(mgr, factory, session_id, reference)
        row_dict = _read(mgr, factory, session_id)

        missing_top = set(reference) - set(row_dict)
        assert not missing_top, f"row path drops top-level to_dict keys: {sorted(missing_top)}"

        missing_slide = set(reference["slides"][0]) - set(row_dict["slides"][0])
        assert not missing_slide, (
            f"row path drops per-slide to_dict keys: {sorted(missing_slide)}"
        )


# ---------------------------------------------------------------------------
# F10 — every writer stores naive UTC timestamps
# ---------------------------------------------------------------------------


class TestTimestampsAreNaiveUtc:
    TZ_AWARE = "2026-03-04T05:06:07+05:30"
    EXPECTED = datetime(2026, 3, 3, 23, 36, 7)  # same instant, naive UTC

    def test_dual_write_normalises_tz_aware_timestamps(self, factory, session_id):
        mgr = SessionManager()
        _save(
            mgr,
            factory,
            session_id,
            _deck([_slide(HTML_A, "id-A", created_at=self.TZ_AWARE)]),
        )
        rows = _rows(factory, _owner_pk(factory))
        assert rows[0]["created_at"].tzinfo is None
        assert rows[0]["created_at"] == self.EXPECTED, (
            f"dual-write stored {rows[0]['created_at']!r}, expected naive UTC "
            f"{self.EXPECTED!r} (5.5h skew into a TIMESTAMP WITHOUT TIME ZONE column)"
        )
        assert rows[0]["modified_at"] == self.EXPECTED

    def test_dual_write_update_branch_normalises_too(self, factory, session_id):
        mgr = SessionManager()
        _save(mgr, factory, session_id, _deck([_slide(HTML_A, "id-A")]))
        _save(
            mgr,
            factory,
            session_id,
            _deck([_slide(HTML_A, "id-A", created_at=self.TZ_AWARE)]),
        )
        rows = _rows(factory, _owner_pk(factory))
        assert rows[0]["created_at"].tzinfo is None
        assert rows[0]["created_at"] == self.EXPECTED
        assert rows[0]["modified_at"] == self.EXPECTED

    def test_restore_normalises_tz_aware_timestamps(self, factory, session_id):
        mgr = SessionManager()
        deck_dict = _deck([_slide(HTML_A, "id-A", created_at=self.TZ_AWARE)])
        _save(mgr, factory, session_id, deck_dict)

        with patch("src.api.services.session_manager.get_db_session", _fake_db(factory)):
            mgr.create_version(
                session_id=session_id,
                description="v1",
                deck_dict=deck_dict,
            )
        # Overwrite rows with a different deck, then restore
        _save(mgr, factory, session_id, _deck([_slide(HTML_B, "id-B")]))
        with patch("src.api.services.session_manager.get_db_session", _fake_db(factory)):
            mgr.restore_version(session_id, 1)

        rows = _rows(factory, _owner_pk(factory))
        assert rows[0]["created_at"].tzinfo is None
        assert rows[0]["created_at"] == self.EXPECTED, (
            f"restore stored {rows[0]['created_at']!r}, expected naive UTC {self.EXPECTED!r}"
        )

    def test_slide_writer_stores_naive_utc(self, factory, session_id):
        from src.api.services.slide_repository import SlideWriter

        with patch("src.api.services.slide_repository.get_db_session", _fake_db(factory)):
            with patch("src.api.services.session_manager.get_db_session", _fake_db(factory)):
                SlideWriter(SessionManager()).write_slide(
                    session_id=session_id, position=0, html=HTML_A
                )

        rows = _rows(factory, _owner_pk(factory))
        assert rows[0]["created_at"].tzinfo is None
        assert rows[0]["modified_at"].tzinfo is None
