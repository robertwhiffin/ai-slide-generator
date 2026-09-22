"""Every slide mutation must take the deck-level spec with it, not only insert.

`session_slide_decks.deck_spec_json` was renumbered on INSERT and on nothing else
(final review C1).  After a delete, a duplicate or a reorder its `position` entries
described slides that had moved or gone, while the per-row `deck_spec_slide`
fragments travelled correctly — two representations of the same per-slide spec,
disagreeing.

That is not a forward-looking risk.  `DeckSpec.slide_at` looks up by the `position`
FIELD, and three consumers on this branch resolve it: the builder brief
(`nodes.py:build_branch_payload`), §4.6's re-review, and `architect_node`'s fallback
to the persisted spec on an edit turn.  Measured before the fix: `_covered_positions`
returned `[0, 1, 2]` on a 2-slide deck, so an edit turn dispatched a builder for a
position with no slide and the deck GAINED one nobody asked for.

Why these assertions read PURPOSES and never positions alone
------------------------------------------------------------
"the spec has three entries numbered 0, 1, 2" is true of a spec whose every entry
now describes the wrong slide.  Contiguity is necessary and nowhere near
sufficient, so every assertion below reads `{position: that entry's own purpose}`
and compares it against the slide markers actually in the rows.  A renumber that
keeps the numbers tidy while shuffling the meaning fails here.

The reorder case is the one that needs it most: a reorder PRESERVES the position
set, so the consumer-side guard `_persisted_spec_describes_these_rows` — which
compares position sets — reads a reordered deck as aligned.  Numbers alone cannot
express this defect at all.

The identity reorder is deliberate (§29, involution)
---------------------------------------------------
A renumber is a permutation, and a permutation applied to the identity is the
identity, so a test that only ever reorders `[1, 2, 0]` cannot distinguish "the
entries were permuted correctly" from "the entries were permuted twice" or from
"a no-op ran".  `test_a_reorder_that_changes_nothing_leaves_every_brief_alone`
pins the fixed point so the sabotage of the real case has somewhere to land.
"""
from __future__ import annotations

import contextlib
import json
import uuid
from typing import Any, Dict, List

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch

import src.database.models  # noqa: F401 — register all ORM models
from src.api.services.chat_service import ChatService
from src.api.services.session_manager import SessionManager
from src.core.database import Base
from src.database.models.session import (
    SessionSlide,
    SessionSlideDeck,
    SlideDeckVersion,
    UserSession,
)

_OWNER_SID = "renumber-owner-sess"
_CONTRIB_SID = "renumber-contrib-sess"
_MARKERS = ("A", "B", "C")

_SPEC: Dict[str, Any] = {
    "title": "Renumber test deck",
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
# Fixtures — mirroring tests/unit/test_insert_slide_service.py
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
                title="Renumber test deck",
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

    `write_deck_level_columns` opens its OWN `get_db_session`, so patching only
    session_manager's would send the deck-spec write to whatever database the
    environment points at.
    """
    fake = _fake_db(factory)
    with patch("src.api.services.session_manager.get_db_session", fake), patch(
        "src.api.services.deck_level_writer.get_db_session", fake
    ), patch(
        "src.api.services.chat_service.get_session_manager",
        return_value=SessionManager(),
    ):
        yield ChatService()


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
    """Each slide's own marker, in row-position order."""
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
            out.append(
                html.split("slide ")[1].split("<")[0] if "slide " in html else ""
            )
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


def _briefs_by_position(factory) -> Dict[int, str]:
    """`{position: that entry's own purpose}` — the shape that catches a shuffle."""
    return {e["position"]: e["purpose"] for e in _spec_slides(factory)}


def _spec_marker_order(factory) -> List[str]:
    """The spec's markers in position order, comparable with `_markers_in_order`.

    `PURPOSE-B` reads back as `B`, so the spec and the rows become directly
    comparable and "the entry describes the slide sitting there" is one assertion.
    """
    briefs = _briefs_by_position(factory)
    return [
        briefs[p].replace("PURPOSE-", "") if briefs[p].startswith("PURPOSE-") else ""
        for p in sorted(briefs)
    ]


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


def _clear_spec(factory) -> None:
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


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def test_a_delete_takes_its_own_spec_entry_and_shifts_the_rest_down(
    deck, service, factory
):
    """Deleting B must leave A at 0 and C at 1 — not B's brief sitting on C."""
    service.delete_slide(_OWNER_SID, 1)

    assert _markers_in_order(factory) == ["A", "C"]
    briefs = _briefs_by_position(factory)
    assert sorted(briefs) == [0, 1], (
        f"the spec is no longer contiguous with the rows: {briefs}"
    )
    assert briefs[0] == "PURPOSE-A"
    assert briefs[1] == "PURPOSE-C", (
        f"position 1 still carries the deleted slide's brief: {briefs}"
    )


def test_deleting_the_first_slide_shifts_every_remaining_entry_down(
    deck, service, factory
):
    service.delete_slide(_OWNER_SID, 0)

    assert _markers_in_order(factory) == ["B", "C"]
    assert _briefs_by_position(factory) == {0: "PURPOSE-B", 1: "PURPOSE-C"}


def test_deleting_the_last_slide_shifts_nothing_but_drops_its_entry(
    deck, service, factory
):
    service.delete_slide(_OWNER_SID, 2)

    assert _markers_in_order(factory) == ["A", "B"]
    assert _briefs_by_position(factory) == {0: "PURPOSE-A", 1: "PURPOSE-B"}


# ---------------------------------------------------------------------------
# Duplicate
# ---------------------------------------------------------------------------


def test_a_duplicate_gives_the_clone_its_sources_brief(deck, service, factory):
    """The clone is a copy of the slide, so it is a copy of the slide's brief.

    A blank entry would be safe for contiguity and wrong on the facts: we know
    exactly what this slide is for, because it is a copy of one we have a brief
    for.  The sweeper re-describes it either way.
    """
    service.duplicate_slide(_OWNER_SID, 0)

    assert _markers_in_order(factory) == ["A", "A", "B", "C"]
    briefs = _briefs_by_position(factory)
    assert sorted(briefs) == [0, 1, 2, 3], f"spec not contiguous: {briefs}"
    assert briefs[0] == "PURPOSE-A"
    assert briefs[1] == "PURPOSE-A", (
        f"the clone's position did not get its source's brief: {briefs}"
    )
    assert briefs[2] == "PURPOSE-B", (
        f"slide B's brief did not shift with slide B: {briefs}"
    )
    assert briefs[3] == "PURPOSE-C"


def test_duplicating_the_last_slide_appends_its_entry(deck, service, factory):
    service.duplicate_slide(_OWNER_SID, 2)

    assert _markers_in_order(factory) == ["A", "B", "C", "C"]
    assert _briefs_by_position(factory) == {
        0: "PURPOSE-A",
        1: "PURPOSE-B",
        2: "PURPOSE-C",
        3: "PURPOSE-C",
    }


# ---------------------------------------------------------------------------
# Reorder — the case the consumer-side guard structurally cannot see
# ---------------------------------------------------------------------------


def test_a_reorder_permutes_the_spec_entries_with_their_slides(
    deck, service, factory
):
    """`new_order[j] = old_index`, so old 1 lands at 0, old 2 at 1, old 0 at 2.

    A reorder preserves the POSITION SET, so `_persisted_spec_describes_these_rows`
    reads this deck as aligned whatever the entries say.  Nothing but a
    content-level assertion can express the defect.
    """
    service.reorder_slides(_OWNER_SID, [1, 2, 0])

    assert _markers_in_order(factory) == ["B", "C", "A"]
    briefs = _briefs_by_position(factory)
    assert briefs == {0: "PURPOSE-B", 1: "PURPOSE-C", 2: "PURPOSE-A"}, (
        f"the briefs did not travel with their slides: {briefs}"
    )


def test_a_reorder_that_changes_nothing_leaves_every_brief_alone(
    deck, service, factory
):
    """The permutation's fixed point, pinned so the live case has a control.

    A renumber is a permutation and the identity is one of them, so without this
    a passing reorder test cannot distinguish a correct remap from a no-op.
    """
    service.reorder_slides(_OWNER_SID, [0, 1, 2])

    assert _markers_in_order(factory) == ["A", "B", "C"]
    assert _briefs_by_position(factory) == {
        0: "PURPOSE-A",
        1: "PURPOSE-B",
        2: "PURPOSE-C",
    }


def test_a_reversal_is_not_its_own_inverse_by_accident(deck, service, factory):
    """Applied twice, a reversal IS the identity — so assert the halfway state.

    §29's involution trap: a test that reverses and reads back the original order
    passes when the renumber ran twice, and when it never ran at all.
    """
    service.reorder_slides(_OWNER_SID, [2, 1, 0])

    assert _markers_in_order(factory) == ["C", "B", "A"]
    assert _briefs_by_position(factory) == {
        0: "PURPOSE-C",
        1: "PURPOSE-B",
        2: "PURPOSE-A",
    }


# ---------------------------------------------------------------------------
# The property all three share: the spec describes the rows that are there
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda s: s.delete_slide(_OWNER_SID, 1), ["A", "C"]),
        (lambda s: s.delete_slide(_OWNER_SID, 0), ["B", "C"]),
        (lambda s: s.duplicate_slide(_OWNER_SID, 0), ["A", "A", "B", "C"]),
        (lambda s: s.duplicate_slide(_OWNER_SID, 2), ["A", "B", "C", "C"]),
        (lambda s: s.reorder_slides(_OWNER_SID, [1, 2, 0]), ["B", "C", "A"]),
        (lambda s: s.reorder_slides(_OWNER_SID, [2, 0, 1]), ["C", "A", "B"]),
        (lambda s: s.insert_slide(_OWNER_SID, 1), ["A", "", "B", "C"]),
    ],
)
def test_the_spec_describes_the_slide_actually_sitting_at_each_position(
    deck, service, factory, mutate, expected
):
    """One assertion for the whole contract, across every mutation route.

    Insert is in the list on purpose: it is the one route that already renumbered,
    so a change that breaks it while fixing the others is caught here.  Its new
    entry is a deliberate blank, which reads back as `''` on both sides.
    """
    mutate(service)

    rows = _markers_in_order(factory)
    assert rows == expected, f"the rows themselves are wrong: {rows}"
    assert _spec_marker_order(factory) == rows, (
        "the spec describes a different deck than the rows do: "
        f"spec={_spec_marker_order(factory)} rows={rows}"
    )


# ---------------------------------------------------------------------------
# Degradation: no spec, an unparseable spec, and a contributor session
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s.delete_slide(_OWNER_SID, 1),
        lambda s: s.duplicate_slide(_OWNER_SID, 0),
        lambda s: s.reorder_slides(_OWNER_SID, [1, 2, 0]),
    ],
)
def test_a_deck_with_no_spec_still_mutates(deck, service, factory, mutate):
    """Decks predate the spec column; no spec is not an error."""
    _clear_spec(factory)
    mutate(service)
    assert len(_markers_in_order(factory)) in (2, 4, 3)


@pytest.mark.parametrize(
    "mutate, expected_briefs",
    [
        (
            lambda s: s.delete_slide(_OWNER_SID, 1),
            {0: "PURPOSE-A", 1: "PURPOSE-C"},
        ),
        (
            lambda s: s.reorder_slides(_OWNER_SID, [1, 2, 0]),
            {0: "PURPOSE-B", 1: "PURPOSE-C", 2: "PURPOSE-A"},
        ),
    ],
)
def test_a_spec_that_no_longer_validates_is_renumbered_not_destroyed(
    deck, service, factory, mutate, expected_briefs
):
    """The renumber runs on the RAW dict, so an older or hand-edited shape survives.

    `design_contract` and `resolved_data` are removed here, which `DeckSpec` requires.
    Parsing to renumber would either raise or silently drop the unknown shape; the
    entries must come back renumbered with the foreign keys still present.
    """
    db = factory()
    try:
        row = (
            db.query(SessionSlideDeck)
            .filter(SessionSlideDeck.session_id == _owner_pk(factory))
            .one()
        )
        stale = json.loads(row.deck_spec_json)
        stale.pop("design_contract")
        stale.pop("resolved_data")
        stale["an_unknown_future_key"] = "keep me"
        row.deck_spec_json = json.dumps(stale)
        db.commit()
    finally:
        db.close()

    mutate(service)

    assert _briefs_by_position(factory) == expected_briefs
    db = factory()
    try:
        row = (
            db.query(SessionSlideDeck)
            .filter(SessionSlideDeck.session_id == _owner_pk(factory))
            .one()
        )
        assert json.loads(row.deck_spec_json)["an_unknown_future_key"] == "keep me", (
            "the renumber parsed and re-serialised the spec, dropping what it "
            "did not understand"
        )
    finally:
        db.close()


@pytest.mark.parametrize(
    "mutate, expected_briefs",
    [
        (
            lambda s: s.delete_slide(_CONTRIB_SID, 1),
            {0: "PURPOSE-A", 1: "PURPOSE-C"},
        ),
        (
            lambda s: s.duplicate_slide(_CONTRIB_SID, 0),
            {0: "PURPOSE-A", 1: "PURPOSE-A", 2: "PURPOSE-B", 3: "PURPOSE-C"},
        ),
        (
            lambda s: s.reorder_slides(_CONTRIB_SID, [1, 2, 0]),
            {0: "PURPOSE-B", 1: "PURPOSE-C", 2: "PURPOSE-A"},
        ),
    ],
)
def test_a_contributors_mutation_renumbers_the_owners_spec(
    deck, service, factory, mutate, expected_briefs
):
    """Decks are shared, and the spec lives on the OWNER's row.

    A standalone-session test cannot tell "resolved the deck owner" from "happened
    to be the deck owner" — nineteen tests elsewhere on this branch stayed green
    with owner resolution removed.
    """
    mutate(service)
    assert _briefs_by_position(factory) == expected_briefs


# ---------------------------------------------------------------------------
# The spec write must not multiply save points (VERSION_LIMIT evicts the oldest)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s.delete_slide(_OWNER_SID, 1),
        lambda s: s.duplicate_slide(_OWNER_SID, 0),
        lambda s: s.reorder_slides(_OWNER_SID, [1, 2, 0]),
    ],
)
def test_exactly_one_save_point_is_created_per_mutation(
    deck, service, factory, mutate
):
    """`SessionManager.VERSION_LIMIT` EVICTS the oldest version, so an extra save
    point per shifted position would delete real history rather than bloat it."""
    before = _version_count(factory)
    mutate(service)
    assert _version_count(factory) - before == 1, (
        "the deck-spec renumber added a save point of its own"
    )
