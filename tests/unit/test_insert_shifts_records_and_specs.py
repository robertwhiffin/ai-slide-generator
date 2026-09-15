"""A verification record and a spec fragment belong to a SLIDE, not a position.

`_attribute_slide_records` exists because a reorder must not hand slide A's
verdict to slide B (F1/F2).  It shipped mapping ONLY
`{new_position: verification_record}` — and `_upsert_slide_row` treats
`deck_spec_slide=None` as "leave the existing value alone" on its full-identity
UPDATE path too (`session_manager.py`, the non-partial branch).  So on any shift
the verdict moved and the per-slide spec fragment silently stayed behind on the
position, where it now describes a different slide.

That is SHIPPED behaviour, not a forward-looking risk: `src/services/graph/nodes.py`
writes `deck_spec_slide` on every reviewed slide today, so every graph-built deck
carries fragments that a reorder, a duplicate or an insert mis-attributes.  These
tests were written to FAIL against the tree before the fix and were confirmed
failing (task-7 report, red run) before `_attribute_slide_records` was changed to
map both.

Why the assertions are keyed on a MARKER and never on a count
------------------------------------------------------------
"the deck has four rows" is true of a completely mis-attributed deck, and so is
"some row has a fragment".  Each slide therefore carries a distinctive marker in
its HTML, and every assertion below reads
`{slide marker: (its verdict marker, its fragment marker)}`.  Only that shape can
tell "the record travelled with its slide" from "a record happens to sit at that
position".

Which attribution pass these tests exercise, and why it is asserted
------------------------------------------------------------------
Pass 1, match by `slide_id`.  `_reindex_slide_ids` now PRESERVES a slide's id and
mints one only where it is missing or collides, so the deck handed to
`save_slide_deck` carries the rows' own ids for the three existing slides and a
fresh one for the inserted slide — and pass 1 resolves all four correctly.

That was not always so.  `_reindex_slide_ids` used to rewrite every id to
`slide_<index>`, which put POSITIONAL ids on both sides of pass 1's comparison and
degenerated it into match-by-position, defeating the F1/F2 fix outright; these tests
originally passed through pass 2 (content hash) for that reason.  Both properties
the current path depends on — the rows have durable unique ids, and the deck
preserves them — are asserted below rather than assumed, so a return of the
wholesale rewrite reddens here and not only in
`tests/integration/test_slide_id_is_durable.py`.
"""
from __future__ import annotations

import contextlib
import json
import uuid
from typing import Dict, List, Optional, Tuple

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch

import src.database.models  # noqa: F401 — register all ORM models
from src.api.services.chat_service import ChatService
from src.api.services.session_manager import SessionManager
from src.core.database import Base
from src.database.models.session import SessionSlide, SessionSlideDeck, UserSession
from src.domain.slide import Slide
from src.domain.slide_deck import SlideDeck
from src.utils.slide_hash import compute_slide_hash

_OWNER_SID = "insert-shift-owner"
_MARKERS = ("A", "B", "C")


# ---------------------------------------------------------------------------
# Fixtures — self-contained, mirroring tests/unit/test_slide_writer.py
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


def _html(marker: str) -> str:
    return f'<div class="slide"><h1>slide {marker}</h1></div>'


@pytest.fixture()
def three_marked_rows(factory):
    """Owner session + deck + three rows, each with its OWN verdict and fragment.

    Returns the list of durable slide_ids the rows carry, in position order.
    """
    db = factory()
    try:
        owner = UserSession(session_id=_OWNER_SID, created_by="owner@test.com")
        db.add(owner)
        db.flush()
        db.add(
            SessionSlideDeck(
                session_id=owner.id,
                title="Marked deck",
                html_content="",
                scripts_content="",
                slide_count=3,
                version=1,
            )
        )
        db.flush()

        slide_ids: List[str] = []
        for position, marker in enumerate(_MARKERS):
            html = _html(marker)
            durable_id = f"durable-{uuid.uuid4().hex[:8]}"
            slide_ids.append(durable_id)
            db.add(
                SessionSlide(
                    session_id=owner.id,
                    position=position,
                    id=str(uuid.uuid4()),
                    html=html,
                    slide_id=durable_id,
                    scripts="",
                    created_by="owner@test.com",
                    verification_record=json.dumps(
                        {compute_slide_hash(html): {"marker": f"VERDICT-{marker}"}}
                    ),
                    deck_spec_slide=json.dumps(
                        {"purpose": f"FRAGMENT-{marker}", "position": position}
                    ),
                )
            )
        db.commit()
    finally:
        db.close()
    return slide_ids


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _owner_pk(factory) -> int:
    db = factory()
    try:
        return (
            db.query(UserSession).filter(UserSession.session_id == _OWNER_SID).one().id
        )
    finally:
        db.close()


def _row_slide_ids(factory) -> List[str]:
    db = factory()
    try:
        return [
            r.slide_id
            for r in db.query(SessionSlide)
            .filter(SessionSlide.session_id == _owner_pk(factory))
            .order_by(SessionSlide.position)
            .all()
        ]
    finally:
        db.close()


def _marker_of(html: str) -> str:
    """Read a slide's distinctive marker back out of its HTML."""
    return html.split("slide ")[1].split("<")[0]


def _attribution_by_marker(
    factory,
) -> Dict[str, Tuple[Optional[str], Optional[str]]]:
    """Map each slide's OWN marker -> (its verdict marker, its fragment marker).

    Keyed on the slide, never on the position: that is the whole point.
    """
    db = factory()
    try:
        out: Dict[str, Tuple[Optional[str], Optional[str]]] = {}
        for row in (
            db.query(SessionSlide)
            .filter(SessionSlide.session_id == _owner_pk(factory))
            .order_by(SessionSlide.position)
            .all()
        ):
            record = json.loads(row.verification_record) if row.verification_record else {}
            verdicts = [v.get("marker") for v in record.values() if isinstance(v, dict)]
            fragment = json.loads(row.deck_spec_slide) if row.deck_spec_slide else None
            out[_marker_of(row.html)] = (
                verdicts[0] if verdicts else None,
                (fragment or {}).get("purpose"),
            )
        return out
    finally:
        db.close()


def _insert_and_save(factory, slide_ids: List[str], insert_at: int) -> None:
    """Shift the deck exactly the way chat_service.insert_slide does, then save.

    Calls the REAL `ChatService._reindex_slide_ids` rather than imitating it.  An
    earlier version of this helper hand-rolled the id step as `slide_<index>`, and
    when that function's contract changed the imitation silently became a test of
    behaviour the code no longer had.  Simulating a collaborator you can just call is
    how a test stops describing the system.
    """
    deck = SlideDeck(
        slides=[
            Slide(html=_html(marker), slide_id=slide_ids[i], scripts="")
            for i, marker in enumerate(_MARKERS)
        ]
    )
    deck.insert_slide(Slide(html=_html("NEW")), insert_at)
    ChatService._reindex_slide_ids(deck)
    slides: List[dict] = deck.to_dict()["slides"]

    with patch(
        "src.api.services.session_manager.get_db_session", _fake_db(factory)
    ):
        SessionManager().save_slide_deck(
            session_id=_OWNER_SID,
            title="Marked deck",
            html_content="<html></html>",
            slide_count=len(slides),
            deck_dict={
                "title": "Marked deck",
                "css": "",
                "external_scripts": [],
                "scripts": "",
                "slides": slides,
            },
        )


# ---------------------------------------------------------------------------
# The fixture's own precondition
# ---------------------------------------------------------------------------


def test_the_rows_carry_durable_unique_slide_ids(three_marked_rows, factory):
    """Guard the guard, half one: the rows have identities to attribute BY."""
    ids = _row_slide_ids(factory)
    assert len(ids) == 3
    assert all(ids), f"a row has no slide_id, so pass 1 cannot run at all: {ids}"
    assert len(set(ids)) == 3, (
        f"the fixture's rows share an id; pass 1 SKIPS an ambiguous id: {ids}"
    )


def test_the_insert_preserves_the_rows_ids_and_mints_one_for_the_newcomer(
    three_marked_rows, factory
):
    """Guard the guard, half two: the property the whole fix turns on.

    The deck that reaches `save_slide_deck` must still carry each existing slide's
    OWN id — that is what lets pass 1 attribute by identity — and the inserted slide
    must carry a new one rather than inheriting the id of whatever it displaced.

    If `_reindex_slide_ids` went back to rewriting every id positionally, this
    reddens with a precise diagnosis instead of leaving the tests below to fail with
    a confusing attribution mismatch.
    """
    deck = SlideDeck(
        slides=[
            Slide(html=_html(marker), slide_id=three_marked_rows[i], scripts="")
            for i, marker in enumerate(_MARKERS)
        ]
    )
    deck.insert_slide(Slide(html=_html("NEW")), 1)
    ChatService._reindex_slide_ids(deck)

    by_marker = {
        _marker_of(s.html): s.slide_id for s in deck.slides
    }
    assert by_marker["A"] == three_marked_rows[0]
    assert by_marker["B"] == three_marked_rows[1], (
        f"slide B's id was rewritten, so pass 1 can no longer find it: {by_marker}"
    )
    assert by_marker["C"] == three_marked_rows[2], (
        f"slide C's id was rewritten: {by_marker}"
    )
    assert by_marker["NEW"] not in three_marked_rows, (
        f"the inserted slide took an existing slide's identity: {by_marker}"
    )
    ids = list(by_marker.values())
    assert len(set(ids)) == 4, f"the insert produced a duplicate id: {ids}"


# ---------------------------------------------------------------------------
# The shift
# ---------------------------------------------------------------------------


def test_a_verification_record_travels_with_its_slide(three_marked_rows, factory):
    """The half that already worked — the paired direction for the test below.

    Without this, "the fragment travelled" could be true of a save that never
    attributed anything at all.
    """
    _insert_and_save(factory, three_marked_rows, insert_at=1)
    attributed = _attribution_by_marker(factory)

    assert set(attributed) == {"A", "B", "C", "NEW"}, (
        f"the insert itself did not happen as expected: {sorted(attributed)}"
    )
    assert attributed["A"][0] == "VERDICT-A"
    assert attributed["B"][0] == "VERDICT-B", (
        "slide B moved from position 1 to position 2 and its verdict did not "
        f"follow it: {attributed}"
    )
    assert attributed["C"][0] == "VERDICT-C", (
        f"slide C's verdict did not follow it across the shift: {attributed}"
    )


def test_a_deck_spec_fragment_travels_with_its_slide(three_marked_rows, factory):
    """The defect. Written to fail against the pre-fix tree, and it did.

    Before the fix this failed on B: `_attribute_slide_records` mapped only the
    verification record, so B's row at its NEW position kept whatever fragment the
    previous occupant of that position had left there.
    """
    _insert_and_save(factory, three_marked_rows, insert_at=1)
    attributed = _attribution_by_marker(factory)

    assert attributed["A"][1] == "FRAGMENT-A"
    assert attributed["B"][1] == "FRAGMENT-B", (
        "slide B moved from position 1 to position 2 and its spec fragment stayed "
        "behind: the fragment now on B's row describes a different slide "
        f"({attributed})"
    )
    assert attributed["C"][1] == "FRAGMENT-C", (
        f"slide C's spec fragment did not follow it across the shift: {attributed}"
    )


def test_the_inserted_slide_inherits_nothing_from_the_position_it_took(
    three_marked_rows, factory
):
    """The other direction, and the one `deck_spec_slide=None` hid.

    The new slide takes position 1, whose row held slide B's verdict AND B's
    fragment.  It must arrive carrying neither.  A fix that only ADDS the fragment
    to the mapping without letting an attributed None CLEAR the column leaves the
    displaced fragment sitting on the newcomer's row — which is why "leave
    unchanged" made the naive fix look like it worked.
    """
    _insert_and_save(factory, three_marked_rows, insert_at=1)
    attributed = _attribution_by_marker(factory)

    verdict, fragment = attributed["NEW"]
    assert verdict is None, (
        f"the inserted slide arrived carrying someone else's verdict: {verdict}"
    )
    assert fragment is None, (
        "the inserted slide arrived carrying the displaced slide's spec fragment: "
        f"{fragment}"
    )


def test_an_ordinary_in_place_save_keeps_every_fragment(three_marked_rows, factory):
    """The regression the fix could plausibly cause, pinned.

    Making the non-partial UPDATE write `deck_spec_slide` unconditionally means a
    save that shifts nothing must still re-attribute every fragment to its own
    slide, or a plain HTML edit would wipe the whole deck's fragments.
    """
    slides = [
        {"html": _html(marker), "slide_id": three_marked_rows[i], "scripts": ""}
        for i, marker in enumerate(_MARKERS)
    ]
    with patch(
        "src.api.services.session_manager.get_db_session", _fake_db(factory)
    ):
        SessionManager().save_slide_deck(
            session_id=_OWNER_SID,
            title="Marked deck",
            html_content="<html></html>",
            slide_count=3,
            deck_dict={
                "title": "Marked deck",
                "css": "",
                "external_scripts": [],
                "scripts": "",
                "slides": slides,
            },
        )

    attributed = _attribution_by_marker(factory)
    assert attributed == {
        "A": ("VERDICT-A", "FRAGMENT-A"),
        "B": ("VERDICT-B", "FRAGMENT-B"),
        "C": ("VERDICT-C", "FRAGMENT-C"),
    }, f"a save that moved nothing lost or moved something: {attributed}"


# ---------------------------------------------------------------------------
# Tier 1 of the matcher — the case that DISTINGUISHES it from tiers 2 and 3
# ---------------------------------------------------------------------------


def test_a_save_that_both_reorders_and_edits_needs_durable_identity(
    three_marked_rows, factory
):
    """The only shape in which `_attribute_slide_records` tier 1 is load-bearing.

    Disabling tier 1 (match by ``slide_id``) entirely used to leave the whole suite
    green: every other attribution assertion is satisfied by tier 2's content hash,
    because in those tests the moved slides' HTML is unchanged and hashes still
    match.  So the tier documented as "durable per-slide identity" — the one this
    round's defect corrupted — had no test that could fail.

    This is the case that separates the tiers.  One save both REORDERS the deck and
    EDITS one slide's HTML:

      * tier 2 cannot resolve the edited slide — its content changed, so no hash
        matches;
      * tier 3 cannot either — the old row at the edited slide's NEW position has
        already been claimed by whichever slide moved into it;
      * only tier 1, matching the id the slide still carries, can.

    So the edited slide keeps its own verdict here if and only if tier 1 works.
    """
    edited_html = _html("B-EDITED")

    deck = SlideDeck(
        slides=[
            Slide(html=_html(marker), slide_id=three_marked_rows[i], scripts="")
            for i, marker in enumerate(_MARKERS)
        ]
    )
    # Rotate to B, C, A *and* rewrite B's HTML — both in the one save.
    #
    # The arrangement is load-bearing and was got wrong on the first attempt: an
    # earlier version rotated to C, B, A, which leaves the edited slide at position 1
    # — its OWN old position — so tier 3's positional fallback resolved it and the
    # test passed with tier 1 disabled (measured: 48 passed).  The edited slide must
    # therefore MOVE, and move onto a position whose old row another slide has
    # already claimed, so that neither tier 2 nor tier 3 can reach it.  B moves to
    # position 0, whose old row belongs to A — and tier 2 claims A's row by hash.
    deck.slides = [deck.slides[1], deck.slides[2], deck.slides[0]]
    deck.slides[0].html = edited_html
    ChatService._reindex_slide_ids(deck)

    with patch("src.api.services.session_manager.get_db_session", _fake_db(factory)):
        SessionManager().save_slide_deck(
            session_id=_OWNER_SID,
            title="Marked deck",
            html_content="<html></html>",
            slide_count=3,
            deck_dict={
                "title": "Marked deck",
                "css": "",
                "external_scripts": [],
                "scripts": "",
                "slides": deck.to_dict()["slides"],
            },
        )

    attributed = _attribution_by_marker(factory)

    # The edited slide is the one only tier 1 can place.
    assert attributed["B-EDITED"] == ("VERDICT-B", "FRAGMENT-B"), (
        "the edited slide lost its own verdict and spec fragment: its content hash "
        "no longer matches (so tier 2 cannot find it) and its old position is taken "
        "(so tier 3 cannot either), which leaves tier 1 — matching the id it still "
        f"carries — as the only thing that can. Got {attributed['B-EDITED']}"
    )
    # PAIRED: the two slides that only MOVED are placed correctly too, so the
    # assertion above cannot pass on a save that attributed nothing at all.
    assert attributed["A"] == ("VERDICT-A", "FRAGMENT-A")
    assert attributed["C"] == ("VERDICT-C", "FRAGMENT-C")


# ---------------------------------------------------------------------------
# The AGENT add path — impersonation, caught behaviourally and not only by grep
# ---------------------------------------------------------------------------


@pytest.fixture()
def three_monolith_rows(factory):
    """Rows whose ids are `slide_0..slide_2` — what `from_html_string` produces.

    The impersonation needs this shape specifically: a stamped positional id can only
    steal an identity if some real slide already holds that id, and on a freshly
    parsed deck every slide does.
    """
    db = factory()
    try:
        owner = UserSession(session_id=_OWNER_SID, created_by="owner@test.com")
        db.add(owner)
        db.flush()
        db.add(
            SessionSlideDeck(
                session_id=owner.id,
                title="Monolith deck",
                html_content="",
                scripts_content="",
                slide_count=3,
                version=1,
            )
        )
        db.flush()
        for position, marker in enumerate(_MARKERS):
            html = _html(marker)
            db.add(
                SessionSlide(
                    session_id=owner.id,
                    position=position,
                    id=str(uuid.uuid4()),
                    html=html,
                    slide_id=f"slide_{position}",
                    scripts="",
                    created_by="owner@test.com",
                    verification_record=json.dumps(
                        {compute_slide_hash(html): {"marker": f"VERDICT-{marker}"}}
                    ),
                    deck_spec_slide=json.dumps({"purpose": f"FRAGMENT-{marker}"}),
                )
            )
        db.commit()
    finally:
        db.close()


def test_an_agent_added_slide_cannot_impersonate_an_existing_slide(
    three_monolith_rows, factory
):
    """The agent add path, driven for real — not a text check on the source.

    `_apply_slide_replacements`' add branch used to stamp
    `f"slide_{insert_position + idx}"` on every slide the LLM added.  Inserted at
    position 1 on a freshly parsed deck, that id already belongs to the slide
    currently at position 1 — and `_reindex_slide_ids` resolves a collision in favour
    of the FIRST holder, which is the newcomer.  So the newcomer KEPT the real
    slide's identity, attribution tier 1 handed it that slide's verdict and spec
    fragment, and the displaced slide was re-minted with neither.

    Note what this means: the uniqueness pass running is not protection.  It resolved
    the collision, in the wrong direction.  That is why the stamp had to go rather
    than be deduplicated afterwards.
    """
    service = ChatService()
    with patch(
        "src.api.services.session_manager.get_db_session", _fake_db(factory)
    ), patch(
        "src.api.services.chat_service.get_session_manager",
        return_value=SessionManager(),
    ):
        before = service._get_or_load_deck(_OWNER_SID)
        assert [s.slide_id for s in before.slides] == ["slide_0", "slide_1", "slide_2"], (
            "fixture precondition: the deck carries parse-shaped positional ids"
        )

        result = service._apply_slide_replacements(
            {
                "replacement_slides": [Slide(html=_html("AGENT-NEW"))],
                "start_index": 0,
                "original_count": 1,
                "is_add_operation": True,
                "position_type": "after",
            },
            _OWNER_SID,
        )

    by_marker = {
        _marker_of(s["html"]): s["slide_id"] for s in result["slides"]
    }
    assert set(by_marker) == {"A", "B", "C", "AGENT-NEW"}, (
        f"the add did not land as expected: {sorted(by_marker)}"
    )

    assert by_marker["B"] == "slide_1", (
        "slide B was re-minted because the agent's new slide took its identity: "
        f"{by_marker}"
    )
    assert by_marker["A"] == "slide_0" and by_marker["C"] == "slide_2", (
        f"an existing slide lost its identity to the newcomer: {by_marker}"
    )
    assert by_marker["AGENT-NEW"] not in {"slide_0", "slide_1", "slide_2"}, (
        "the agent's new slide is carrying an id that belongs to an existing slide, "
        f"so tier 1 will hand it that slide's verdict: {by_marker}"
    )
    ids = list(by_marker.values())
    assert len(set(ids)) == 4, f"duplicate slide_id after the add: {ids}"
