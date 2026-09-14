"""The tour ships a hand-authored arc instead of firing the trigger.

`_phase2_add_slides` loads a canned fixture and saves it.  It is deck CREATION
from fixed bytes, identical on every tour, so firing `mark_dirty` there would
schedule an LLM arc re-description of the same demo deck for every user who takes
the tour, for no value.  The arc is therefore authored once, by hand, in
`src/api/fixtures/tour_demo_deck.json` — which is strictly better than excluding
the route, because the tour then also demonstrates the spec view.

The DoD item "`tour.py` never calls `mark_dirty`" is an ABSENCE assertion: it is
equally true if tour.py were deleted, if the parse silently failed, or if the
token were misspelled.  Every absence test here is paired with an entry assertion
on the path that must fire — the fixture's spec actually reaching the
`deck_spec_json` column.

Why the spec needs a SECOND write (brief C-1)
---------------------------------------------
The plan asserted the fixture's arc travels `save_slide_deck` -> `_upsert_slide_deck`
-> persisted `deck_spec_json`.  It does not: `save_slide_deck` never assigns
`deck.deck_spec_json`, and a `deck_spec` key in `deck_dict` is swallowed into the
`deck_json` blob and never read back into the column, with no exception.
`test_save_slide_deck_alone_does_not_persist_a_spec` below pins that measurement,
so nobody "simplifies" tour.py by deleting the `write_deck_level_columns` call and
silently loses the tour's spec again.
"""
from __future__ import annotations

import ast
import contextlib
import io
import json
import tokenize
from pathlib import Path

import pytest
from unittest.mock import patch

from src.api.routes.tour import _load_fixture, _phase1_create_session, _phase2_add_slides
from src.api.services.deck_level_writer import read_deck_spec
from src.domain.deck_spec import DeckSpec
from tests.unit.conftest import _make_fake_db, _make_factory, _make_in_memory_engine

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TOUR = _REPO_ROOT / "src/api/routes/tour.py"
_SLIDES = _REPO_ROOT / "src/api/routes/slides.py"

_MANAGER_DB = "src.api.services.session_manager.get_db_session"
_WRITER_DB = "src.api.services.deck_level_writer.get_db_session"

_TOUR_USER = "tour-taker@example.com"


def _name_tokens(path: Path) -> set:
    """NAME tokens only — comments and docstrings discarded."""
    readline = io.BytesIO(path.read_bytes()).readline
    return {
        tok.string
        for tok in tokenize.tokenize(readline)
        if tok.type == tokenize.NAME
    }


@contextlib.contextmanager
def _patched(factory):
    """Point the SessionManager and deck-level-writer DB sessions at *factory*."""
    fake = _make_fake_db(factory)
    with patch(_MANAGER_DB, fake), patch(_WRITER_DB, fake):
        yield


@pytest.fixture
def tour_db():
    """A throwaway engine with the deck schema, plus its session factory."""
    engine = _make_in_memory_engine()
    try:
        yield _make_factory(engine)
    finally:
        engine.dispose()


def _run_the_tour(factory) -> str:
    """Run both tour phases against *factory*, returning the session id."""
    with _patched(factory):
        created = _phase1_create_session(_TOUR_USER)
        session_id = created["session_id"]
        _phase2_add_slides(session_id, _TOUR_USER)
    return session_id


class TestTourDoesNotFireTheTrigger:
    def test_tour_py_never_references_mark_dirty(self):
        """The absence. Paired below with the arc that ships instead."""
        assert _TOUR.exists(), "anchor drifted: tour.py no longer exists"
        assert "mark_dirty" not in _name_tokens(_TOUR)

    def test_the_same_matcher_finds_the_calls_that_do_exist(self):
        """The pair: this matcher CAN see a mark_dirty reference when there is one.

        Without this, the assertion above would also pass on a tokenizer that
        returned nothing at all.
        """
        assert "mark_dirty" in _name_tokens(_SLIDES)

    def test_phase2_calls_the_deck_level_writer_not_the_trigger(self):
        """What tour.py does instead, pinned in the AST of the function itself."""
        tree = ast.parse(_TOUR.read_text())
        phase2 = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "_phase2_add_slides"
        )
        called = {
            n.id for n in ast.walk(phase2) if isinstance(n, ast.Name)
        } | {
            n.attr for n in ast.walk(phase2) if isinstance(n, ast.Attribute)
        }
        assert "write_deck_level_columns" in called
        assert "save_slide_deck" in called
        assert "mark_dirty" not in called


class TestTheFixtureShipsAHandAuthoredArc:
    def test_the_fixture_has_a_deck_spec(self):
        assert "deck_spec" in _load_fixture()

    def test_the_deck_spec_validates_as_a_real_DeckSpec(self):
        """Nine deck fields and three slide entries, checked by the real model.

        `design_contract`, `resolved_data` and `slides` are REQUIRED with no
        default, so a partial hand-authored spec fails here rather than at runtime.
        """
        spec = DeckSpec(**_load_fixture()["deck_spec"])
        assert spec.title
        assert spec.audience and spec.purpose and spec.argument
        assert spec.call_to_action

    def test_the_narrative_arc_is_a_NON_EMPTY_LIST(self):
        """The DoD guard. The field is `list[str]`, so a string is also wrong.

        A guard written for a string (`assert arc != ""`) would pass on `[]`, and
        one written for truthiness would pass on `[""]`.  All three are checked.
        """
        arc = _load_fixture()["deck_spec"]["narrative_arc"]
        assert isinstance(arc, list), f"narrative_arc is {type(arc).__name__}, not a list"
        assert len(arc) > 0, "narrative_arc is empty"
        for entry in arc:
            assert isinstance(entry, str)
            assert entry.strip(), "narrative_arc contains a blank entry"

    def test_the_arc_describes_the_actual_demo_deck(self):
        """Not a placeholder: the arc names what the three slides actually say.

        Guards against a lorem-ipsum arc that would satisfy "non-empty list" while
        telling the spec view nothing.
        """
        arc_text = " ".join(_load_fixture()["deck_spec"]["narrative_arc"]).lower()
        for topic in ("diagnostic", "detection", "treatment", "surgery"):
            assert topic in arc_text, f"the arc never mentions {topic!r}"

    def test_the_spec_has_one_slide_entry_per_fixture_slide(self):
        fixture = _load_fixture()
        spec = DeckSpec(**fixture["deck_spec"])
        assert len(spec.slides) == len(fixture["slides"]) == 3
        assert [s.position for s in spec.slides] == [0, 1, 2]
        for slide in spec.slides:
            assert slide.purpose.strip()
            assert slide.content_brief.strip()

    def test_the_spec_title_matches_the_deck_title(self):
        fixture = _load_fixture()
        assert fixture["deck_spec"]["title"] == fixture["title"]

    def test_the_design_contract_is_unbranded_and_not_over_specified(self):
        """All-None is valid and correct for an unbranded demo deck.

        `design_system_id` and `slide_style_id` are mutually exclusive, so setting
        both would raise — pinned so a later edit does not.
        """
        contract = _load_fixture()["deck_spec"]["design_contract"]
        assert contract == {
            "design_system_id": None,
            "template_id": None,
            "slide_style_id": None,
        }


class TestTheFixtureSpecReachesTheColumn:
    """The entry assertion for every absence above: the positive path fires."""

    def test_phase2_persists_the_spec_to_deck_spec_json(self, tour_db):
        session_id = _run_the_tour(tour_db)

        with _patched(tour_db):
            stored = read_deck_spec(session_id)

        assert stored is not None, (
            "the tour deck has no persisted spec: §7.1's spec view is empty and "
            "the next architect turn on this deck is blind"
        )
        assert stored == _load_fixture()["deck_spec"], (
            "the persisted spec is not the fixture's spec"
        )

    def test_the_persisted_arc_is_the_hand_authored_one(self, tour_db):
        """A distinctive value travelling end to end, not a default."""
        session_id = _run_the_tour(tour_db)

        with _patched(tour_db):
            stored = read_deck_spec(session_id)

        assert stored["narrative_arc"] == _load_fixture()["deck_spec"]["narrative_arc"]
        assert len(stored["narrative_arc"]) == 3

    def test_the_tour_deck_carries_no_dirty_marker(self, tour_db):
        """Taking the tour must not enqueue an arc review.

        Paired with the two tests above: the spec IS persisted (so phase 2 really
        ran and really wrote the deck) while the marker is NOT set.
        """
        from src.database.models.session import SessionSlideDeck

        session_id = _run_the_tour(tour_db)

        db = tour_db()
        try:
            deck = db.query(SessionSlideDeck).one()
            assert deck.deck_spec_json, "phase 2 did not write the spec at all"
            assert deck.spec_dirty_at is None, (
                "the tour scheduled an LLM arc re-description of the demo deck"
            )
            assert deck.spec_dirty_by is None
        finally:
            db.close()

    def test_the_tour_still_saves_its_slides(self, tour_db):
        """The extra write must not have displaced what phase 2 already did."""
        from src.database.models.session import SessionSlide, SessionSlideDeck

        session_id = _run_the_tour(tour_db)

        db = tour_db()
        try:
            deck = db.query(SessionSlideDeck).one()
            assert deck.title == _load_fixture()["title"]
            assert deck.slide_count == 3
            assert db.query(SessionSlide).count() == 3, (
                "the deck-level write pruned the slide rows"
            )
        finally:
            db.close()


class TestWhyTheSecondWriteExists:
    def test_save_slide_deck_alone_does_not_persist_a_spec(self, tour_db):
        """Brief C-1, pinned: the loss is silent, so only a test can hold it.

        `save_slide_deck` is handed a deck_dict CONTAINING a deck_spec and raises
        nothing, yet `deck_spec_json` stays NULL.  This is why tour.py needs the
        second call; delete that call and `test_phase2_persists_the_spec_to_
        deck_spec_json` goes red while this test keeps explaining why.
        """
        from src.api.services.session_manager import get_session_manager
        from src.database.models.session import SessionSlideDeck

        sentinel = {"title": "Spec That Should Not Survive", "narrative_arc": ["x"]}

        with _patched(tour_db):
            created = _phase1_create_session(_TOUR_USER)
            session_id = created["session_id"]
            get_session_manager().save_slide_deck(
                session_id=session_id,
                title="Deck With A Spec In Its Dict",
                html_content="",
                scripts_content="",
                slide_count=1,
                deck_dict={
                    "title": "Deck With A Spec In Its Dict",
                    "css": "",
                    "external_scripts": [],
                    "scripts": "",
                    "slides": [{"html": "<div>1</div>", "scripts": ""}],
                    "deck_spec": sentinel,
                },
                modified_by=_TOUR_USER,
            )

        db = tour_db()
        try:
            deck = db.query(SessionSlideDeck).one()
            assert deck.deck_spec_json is None, (
                "save_slide_deck now persists deck_spec — brief C-1 is out of "
                "date and tour.py's second write may be redundant"
            )
            # And the spec is not recoverable from the blob it WAS stored in.
            assert "deck_spec" in json.loads(deck.deck_json), (
                "anchor drifted: the spec no longer even reaches deck_json"
            )
        finally:
            db.close()

        with _patched(tour_db):
            assert read_deck_spec(session_id) is None, (
                "the read path recovered a spec that was never in the column"
            )
