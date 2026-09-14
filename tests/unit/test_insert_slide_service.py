"""`chat_service.insert_slide` — the capability Tellr did not have.

`SlideDeck.insert_slide` has existed all along with six internal call sites, but
there was no service method and no route, so a user could only get a new slide by
asking the agent or duplicating one.

What these tests are careful about
----------------------------------
**Identity, not counts.**  Each seeded slide carries a distinctive marker in its
HTML.  "the deck now has four slides" is true of an insert that landed in the wrong
place, dropped a slide and duplicated another, so every ordering assertion reads the
markers back in order.

**A contributor session, not only the owner's.**  Decks are shared: a contributor
UserSession has `parent_session_id` set and no `slide_deck` of its own, and the
write must land on the OWNER's rows.  A standalone-session test cannot tell
"resolved the deck owner" from "happened to be the deck owner", which is how
nineteen tests elsewhere in this PR stayed green with owner resolution removed.

**The clamp boundary is asserted where it is owned.**  `SlideDeck.insert_slide`
delegates to `list.insert`, which clamps a too-large position into an append, so
`insert_slide` deliberately does not re-check the upper bound.  The lower bound is
the service's: `list.insert(-1, x)` would land second-to-last, so a negative
position is rejected instead of silently relocated.
"""
from __future__ import annotations

import contextlib
import json
import uuid
from typing import Any, Dict, List, Optional

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch

import src.database.models  # noqa: F401 — register all ORM models
from src.api.services.chat_service import BLANK_SLIDE_HTML, ChatService
from src.api.services.session_manager import SessionManager
from src.core.database import Base
from src.database.models.session import (
    SessionSlide,
    SessionSlideDeck,
    SlideDeckVersion,
    UserSession,
)

_OWNER_SID = "insert-owner-sess"
_CONTRIB_SID = "insert-contrib-sess"
_MARKERS = ("A", "B", "C")

_SPEC = {
    "title": "Insert test deck",
    "audience": "test",
    "purpose": "test",
    "argument": "test",
    "call_to_action": "test",
    "narrative_arc": ["a", "b", "c"],
    "design_contract": {
        "design_system_id": None,
        "template_id": None,
        "slide_style_id": None,
    },
    "resolved_data": {"synthesis": "s", "figures": [], "gaps": []},
    "slides": [
        {
            "position": i,
            "purpose": f"PURPOSE-{m}",
            "content_brief": f"BRIEF-{m}",
            "assumes": "",
            "hands_off": "",
            "data_references": [],
        }
        for i, m in enumerate(_MARKERS)
    ],
}


def _html(marker: str) -> str:
    return f'<div class="slide"><h1>slide {marker}</h1></div>'


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    yield sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _fake_db(factory):
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


@pytest.fixture()
def deck(factory):
    """Owner + contributor sessions, a 3-slide deck with a spec, and marked rows."""
    db = factory()
    try:
        owner = UserSession(session_id=_OWNER_SID, created_by="owner@test.com")
        db.add(owner)
        db.flush()
        db.add(
            SessionSlideDeck(
                session_id=owner.id,
                title="Insert test deck",
                html_content="",
                scripts_content="",
                slide_count=3,
                version=1,
                deck_spec_json=json.dumps(_SPEC),
            )
        )
        for position, marker in enumerate(_MARKERS):
            db.add(
                SessionSlide(
                    session_id=owner.id,
                    position=position,
                    id=str(uuid.uuid4()),
                    html=_html(marker),
                    slide_id=f"durable-{uuid.uuid4().hex[:8]}",
                    scripts="",
                    created_by="owner@test.com",
                )
            )
        db.add(
            UserSession(
                session_id=_CONTRIB_SID,
                created_by="contrib@test.com",
                parent_session_id=owner.id,
            )
        )
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def service(factory):
    """A ChatService whose every DB hop reaches this test's engine.

    `write_deck_level_columns` opens its OWN `get_db_session` (it is a separate
    module), so patching only session_manager's would send the deck-spec write to
    whatever database the environment points at.
    """
    fake = _fake_db(factory)
    with patch("src.api.services.session_manager.get_db_session", fake), patch(
        "src.api.services.deck_level_writer.get_db_session", fake
    ), patch(
        "src.api.services.chat_service.get_session_manager",
        return_value=SessionManager(),
    ):
        svc = ChatService()
        yield svc


# ---------------------------------------------------------------------------
# Read-back helpers
# ---------------------------------------------------------------------------


def _owner_pk(factory) -> int:
    db = factory()
    try:
        return (
            db.query(UserSession).filter(UserSession.session_id == _OWNER_SID).one().id
        )
    finally:
        db.close()


def _markers_in_order(factory) -> List[str]:
    """Each slide's own marker, in row-position order. Empty slide reads as ''."""
    db = factory()
    try:
        rows = (
            db.query(SessionSlide)
            .filter(SessionSlide.session_id == _owner_pk(factory))
            .order_by(SessionSlide.position)
            .all()
        )
        out = []
        for row in rows:
            html = row.html or ""
            out.append(html.split("slide ")[1].split("<")[0] if "slide " in html else "")
        return out
    finally:
        db.close()


def _spec_slides(factory) -> List[Dict[str, Any]]:
    db = factory()
    try:
        deck_row = (
            db.query(SessionSlideDeck)
            .filter(SessionSlideDeck.session_id == _owner_pk(factory))
            .one()
        )
        return json.loads(deck_row.deck_spec_json)["slides"]
    finally:
        db.close()


def _version_count(factory) -> int:
    db = factory()
    try:
        return (
            db.query(SlideDeckVersion)
            .filter(SlideDeckVersion.session_id == _owner_pk(factory))
            .count()
        )
    finally:
        db.close()


def _row_count(factory) -> int:
    db = factory()
    try:
        return (
            db.query(SessionSlide)
            .filter(SessionSlide.session_id == _owner_pk(factory))
            .count()
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Where the slide lands, and what moves
# ---------------------------------------------------------------------------


def test_the_slide_lands_at_the_requested_position(deck, service, factory):
    service.insert_slide(_OWNER_SID, 1, html=_html("NEW"))
    assert _markers_in_order(factory) == ["A", "B", "C"][:1] + ["NEW", "B", "C"]


def test_every_higher_slide_shifts_up_and_none_is_lost(deck, service, factory):
    """The shift asserted by identity: B and C keep their own content.

    A count assertion (`4 rows`) passes just as happily on an insert that
    overwrote B, so the markers are read back in order instead.
    """
    service.insert_slide(_OWNER_SID, 1, html=_html("NEW"))
    assert _markers_in_order(factory) == ["A", "NEW", "B", "C"]
    assert _row_count(factory) == 4


def test_inserting_at_zero_puts_the_slide_first(deck, service, factory):
    service.insert_slide(_OWNER_SID, 0, html=_html("NEW"))
    assert _markers_in_order(factory) == ["NEW", "A", "B", "C"]


def test_inserting_beyond_the_end_appends_rather_than_erroring(deck, service, factory):
    """The domain's clamp, pinned where a caller can see it.

    `SlideDeck.insert_slide` delegates to `list.insert`, which clamps rather than
    raising, so this must be an append and not a 400.  Position 99 on a 3-slide
    deck lands at index 3.
    """
    result = service.insert_slide(_OWNER_SID, 99, html=_html("NEW"))
    assert _markers_in_order(factory) == ["A", "B", "C", "NEW"]
    assert len(result["slides"]) == 4


def test_a_negative_position_is_rejected_not_clamped(deck, service, factory):
    """The bound the service owns, because `list.insert(-1, x)` lands second-last.

    Paired with a read-back: the deck must be untouched, or "it raised" would be
    compatible with having inserted first and raised afterwards.
    """
    with pytest.raises(ValueError, match="Invalid slide position"):
        service.insert_slide(_OWNER_SID, -1, html=_html("NEW"))
    assert _markers_in_order(factory) == ["A", "B", "C"]


def test_html_without_a_slide_wrapper_is_rejected(deck, service, factory):
    with pytest.raises(ValueError, match="slide"):
        service.insert_slide(_OWNER_SID, 1, html="<p>no wrapper</p>")
    assert _markers_in_order(factory) == ["A", "B", "C"]


def test_omitting_html_inserts_an_empty_slide_that_is_still_a_slide(
    deck, service, factory
):
    """A blank slide must still carry the wrapper every other layer recognises."""
    service.insert_slide(_OWNER_SID, 1)
    db = factory()
    try:
        row = (
            db.query(SessionSlide)
            .filter(
                SessionSlide.session_id == _owner_pk(factory),
                SessionSlide.position == 1,
            )
            .one()
        )
        assert row.html == BLANK_SLIDE_HTML
    finally:
        db.close()
    assert _markers_in_order(factory) == ["A", "", "B", "C"]


# ---------------------------------------------------------------------------
# The deck spec
# ---------------------------------------------------------------------------


def test_the_deck_spec_gains_an_entry_and_higher_entries_shift(deck, service, factory):
    """Entries move by IDENTITY: B's brief must end up at position 2, not 1.

    `DeckSpec.slide_at` looks up by the `position` FIELD, so an entry left at its
    old number briefs a builder for its neighbour's slide.
    """
    service.insert_slide(_OWNER_SID, 1, html=_html("NEW"))
    entries = _spec_slides(factory)

    assert [e["position"] for e in entries] == [0, 1, 2, 3], (
        f"spec positions are no longer contiguous: {entries}"
    )
    by_position = {e["position"]: e["purpose"] for e in entries}
    assert by_position[0] == "PURPOSE-A"
    assert by_position[1] == "", (
        f"the new position did not get a placeholder entry: {by_position}"
    )
    assert by_position[2] == "PURPOSE-B", (
        f"slide B's spec entry did not shift with slide B: {by_position}"
    )
    assert by_position[3] == "PURPOSE-C", (
        f"slide C's spec entry did not shift with slide C: {by_position}"
    )


def test_appending_beyond_the_end_gives_the_spec_the_position_it_really_landed_at(
    deck, service, factory
):
    """The clamp reaches the spec too.

    Requesting 99 on a 3-slide deck must produce a spec entry at 3 — the position
    the slide actually took — not at 99, which would break contiguity forever.
    """
    service.insert_slide(_OWNER_SID, 99, html=_html("NEW"))
    entries = _spec_slides(factory)
    assert [e["position"] for e in entries] == [0, 1, 2, 3], (
        f"the spec recorded the requested position rather than the real one: {entries}"
    )
    by_position = {e["position"]: e["purpose"] for e in entries}
    assert by_position[3] == ""
    assert by_position[2] == "PURPOSE-C", (
        f"an append must shift nothing: {by_position}"
    )


def test_a_deck_with_no_spec_still_inserts(deck, service, factory):
    """No spec is not an error: decks predate the column."""
    db = factory()
    try:
        row = (
            db.query(SessionSlideDeck)
            .filter(SessionSlideDeck.session_id == _owner_pk(factory))
            .one()
        )
        row.deck_spec_json = None
        db.commit()
    finally:
        db.close()

    service.insert_slide(_OWNER_SID, 1, html=_html("NEW"))
    assert _markers_in_order(factory) == ["A", "NEW", "B", "C"]


# ---------------------------------------------------------------------------
# The save point
# ---------------------------------------------------------------------------


def test_exactly_one_save_point_is_created_for_one_insert(deck, service, factory):
    """One per user-visible operation, not one per shifted position.

    VERSION_LIMIT is enforced by DELETING the oldest version, so a save point per
    position would evict real history rather than merely bloat it.
    """
    before = _version_count(factory)
    service.insert_slide(_OWNER_SID, 1, html=_html("NEW"))
    assert _version_count(factory) == before + 1, (
        f"expected exactly one new save point, went from {before} to "
        f"{_version_count(factory)}"
    )


# ---------------------------------------------------------------------------
# The single-direction trap: a contributor session
# ---------------------------------------------------------------------------


def test_a_contributor_inserts_into_the_owners_deck(deck, service, factory):
    """The case a standalone-session test structurally cannot distinguish.

    The contributor has no `slide_deck` of its own, so if the write keyed on the
    calling session's pk instead of the deck owner's it would land on rows nobody
    reads — and every owner-session test above would still pass.
    """
    service.insert_slide(_CONTRIB_SID, 1, html=_html("NEW"))

    assert _markers_in_order(factory) == ["A", "NEW", "B", "C"], (
        "the contributor's insert did not reach the owner's rows"
    )

    # PAIRED: nothing was written under the contributor's own session pk.
    db = factory()
    try:
        contrib_pk = (
            db.query(UserSession)
            .filter(UserSession.session_id == _CONTRIB_SID)
            .one()
            .id
        )
        stray = (
            db.query(SessionSlide)
            .filter(SessionSlide.session_id == contrib_pk)
            .count()
        )
        assert stray == 0, (
            f"{stray} slide rows landed on the contributor session instead of the "
            "deck owner"
        )
    finally:
        db.close()


def test_a_contributors_insert_shifts_the_owners_deck_spec(deck, service, factory):
    """Owner resolution has to hold on the deck-spec hop too, not just the rows.

    `write_deck_level_columns` resolves the owner independently of
    `save_slide_deck`, so this is a second place the same defect can hide.
    """
    service.insert_slide(_CONTRIB_SID, 1, html=_html("NEW"))
    entries = _spec_slides(factory)
    by_position = {e["position"]: e["purpose"] for e in entries}
    assert [e["position"] for e in entries] == [0, 1, 2, 3]
    assert by_position[2] == "PURPOSE-B", (
        f"the contributor's insert did not shift the owner's spec: {by_position}"
    )
