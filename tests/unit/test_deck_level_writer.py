"""Tests for src/api/services/deck_level_writer.py (B3.1).

Real sqlite throughout — every assertion reads the database back.  No mock stands
in for a column write, because the defect class this module exists to prevent
(a deck-level write that destroys `session_slides` rows) is invisible to a mock.

Driving the writer: `write_deck_level_columns` opens its own DB session via
`get_db_session`, exactly as every `SessionManager` method does, so a throwaway
engine reaches it only by patching (.ws4b-PLAN-CORRECTIONS.md §14.1).  The patch
target is this module's own reference, `src.api.services.deck_level_writer.
get_db_session`; the writer passes `db` explicitly into the two reused
`SessionManager` helpers, so `session_manager.get_db_session` needs no patch.
`_make_fake_db` is reused from tests/unit/conftest.py rather than reinvented.
"""
from __future__ import annotations

import contextlib
import json

import pytest
from unittest.mock import patch

from src.api.services.deck_level_writer import (
    read_deck_spec,
    write_deck_level_columns,
)
from src.api.services.session_manager import (
    SessionNotFoundError,
    VersionConflictError,
)
from src.database.models.session import SessionSlide, SessionSlideDeck, UserSession
from tests.unit.conftest import _make_fake_db, _make_factory

_WRITER_DB = "src.api.services.deck_level_writer.get_db_session"
_MANAGER_DB = "src.api.services.session_manager.get_db_session"


@contextlib.contextmanager
def _patched(factory):
    """Point both get_db_session references at *factory*'s throwaway engine.

    The writer only ever uses its OWN reference, so the SessionManager patch is
    inert for a correct implementation.  It is here deliberately: if the writer
    ever delegates to a `SessionManager` method (the wrong implementation this
    module exists to rule out — `save_slide_deck(deck_dict={"slides": []})`),
    that delegation runs against THIS engine and the row-safety test fails on
    destroyed rows, which is the defect, instead of on a real-database
    connection error, which would hide it.
    """
    fake = _make_fake_db(factory)
    with patch(_WRITER_DB, fake), patch(_MANAGER_DB, fake):
        yield


# Representative deck-level payloads.
_CSS = ".slide { color: rebeccapurple; }"
_EXTERNAL_SCRIPTS = ["https://cdn.jsdelivr.net/npm/chart.js@4"]
_HEAD_META = {"viewport": "width=1280, initial-scale=1.0", "charset": "utf-8"}
_DECK_SPEC = {
    "title": "Written By The Architect",
    "audience": "Board",
    "slides": [{"position": 0, "purpose": "intro"}],
}


# ---------------------------------------------------------------------------
# The reason the module exists: no session_slides row is touched.
# ---------------------------------------------------------------------------


class TestTouchesNoSlideRows:
    def test_pre_fan_out_write_touches_no_session_slides_row(self, deck_with_three_rows):
        """A deck-level write leaves all three slide rows byte-identical.

        This is the test the mandatory sabotage targets: delegating to
        `save_slide_deck(deck_dict={"slides": []})` prunes every row at
        position >= 0, i.e. the whole live deck, mid-turn.
        """
        before = deck_with_three_rows.row_snapshot()
        assert len(before) == 3, "fixture precondition: three slide rows exist"

        with _patched(deck_with_three_rows._factory):
            write_deck_level_columns(
                deck_with_three_rows.session_id,
                title="Pre-fan-out title",
                css=_CSS,
                external_scripts=_EXTERNAL_SCRIPTS,
                head_meta=_HEAD_META,
                deck_spec=_DECK_SPEC,
            )

        after = deck_with_three_rows.row_snapshot()
        assert len(after) == 3, f"row COUNT changed: 3 -> {len(after)}"
        assert after == before, "a session_slides row was modified"

    def test_post_commit_write_touches_no_session_slides_row(self, deck_with_three_rows):
        """The second write of the turn is equally row-safe."""
        before = deck_with_three_rows.row_snapshot()

        with _patched(deck_with_three_rows._factory):
            write_deck_level_columns(
                deck_with_three_rows.session_id,
                css=_CSS,
                slide_count=3,
                html_content="<html>knitted</html>",
                scripts_content="(function(){})();",
            )

        assert deck_with_three_rows.row_snapshot() == before

    def test_write_does_not_null_deck_json(self, deck_with_three_rows):
        """deck_json survives, unchanged — save_slide_deck(deck_dict=None) nulls it."""
        before = deck_with_three_rows.deck_json()
        assert before is not None, "fixture precondition: deck_json is populated"

        with _patched(deck_with_three_rows._factory):
            write_deck_level_columns(
                deck_with_three_rows.session_id,
                title="Still has a blob",
                css=_CSS,
            )

        after = deck_with_three_rows.deck_json()
        assert after is not None, "deck_json was nulled"
        assert after == before


# ---------------------------------------------------------------------------
# Optimistic locking — the shape reused from save_slide_deck.
# ---------------------------------------------------------------------------


class TestOptimisticLock:
    def test_version_bumps_exactly_once_per_call(self, deck_with_three_rows):
        start = deck_with_three_rows.version()

        with _patched(deck_with_three_rows._factory):
            first = write_deck_level_columns(
                deck_with_three_rows.session_id, css=_CSS
            )
        assert deck_with_three_rows.version() == start + 1
        assert first["version"] == start + 1

        with _patched(deck_with_three_rows._factory):
            second = write_deck_level_columns(
                deck_with_three_rows.session_id, slide_count=3
            )
        assert deck_with_three_rows.version() == start + 2
        assert second["version"] == start + 2

    def test_matching_expected_version_is_accepted(self, deck_with_three_rows):
        current = deck_with_three_rows.version()

        with _patched(deck_with_three_rows._factory):
            result = write_deck_level_columns(
                deck_with_three_rows.session_id,
                css=_CSS,
                expected_version=current,
            )

        assert result["version"] == current + 1
        assert deck_with_three_rows.deck_row().css == _CSS

    def test_stale_expected_version_is_rejected_and_writes_nothing(
        self, deck_with_three_rows
    ):
        current = deck_with_three_rows.version()
        css_before = deck_with_three_rows.deck_row().css

        with _patched(deck_with_three_rows._factory):
            with pytest.raises(VersionConflictError) as exc:
                write_deck_level_columns(
                    deck_with_three_rows.session_id,
                    css="/* stale writer */",
                    expected_version=current - 1,
                )

        assert exc.value.current_version == current
        assert exc.value.expected_version == current - 1
        assert deck_with_three_rows.version() == current, "version moved on a rejected write"
        assert deck_with_three_rows.deck_row().css == css_before, "rejected write persisted"


# ---------------------------------------------------------------------------
# The sentinel: omitted != explicit None.
# ---------------------------------------------------------------------------


class TestSentinelSemantics:
    def test_omitted_columns_survive_the_second_write(self, deck_with_three_rows):
        """The crux: the post-commit write must not erase the pre-fan-out write.

        Call 1 persists the five pre-fan-out columns; call 2 supplies only the
        three post-commit ones.  Every value from call 1 must still be there.
        """
        with _patched(deck_with_three_rows._factory):
            write_deck_level_columns(
                deck_with_three_rows.session_id,
                title="Architect's title",
                css=_CSS,
                external_scripts=_EXTERNAL_SCRIPTS,
                head_meta=_HEAD_META,
                deck_spec=_DECK_SPEC,
            )

        with _patched(deck_with_three_rows._factory):
            write_deck_level_columns(
                deck_with_three_rows.session_id,
                slide_count=3,
                html_content="<html>knitted</html>",
                scripts_content="(function(){/*charts*/})();",
            )

        deck = deck_with_three_rows.deck_row()
        assert deck.title == "Architect's title", "title erased by the second write"
        assert deck.css == _CSS, "css erased by the second write"
        assert json.loads(deck.external_scripts_json) == _EXTERNAL_SCRIPTS, (
            "external_scripts_json erased — Chart.js would vanish from every export"
        )
        assert json.loads(deck.head_meta_json) == _HEAD_META, "head_meta_json erased"
        assert json.loads(deck.deck_spec_json) == _DECK_SPEC, "deck_spec_json erased"

    def test_all_eight_columns_written_across_the_two_calls(self, deck_with_three_rows):
        with _patched(deck_with_three_rows._factory):
            write_deck_level_columns(
                deck_with_three_rows.session_id,
                title="Eight Columns",
                css=_CSS,
                external_scripts=_EXTERNAL_SCRIPTS,
                head_meta=_HEAD_META,
                deck_spec=_DECK_SPEC,
            )
        with _patched(deck_with_three_rows._factory):
            write_deck_level_columns(
                deck_with_three_rows.session_id,
                css=_CSS + " /* aggregated */",
                slide_count=7,
                html_content="<html>knitted</html>",
                scripts_content="(function(){/*charts*/})();",
            )

        deck = deck_with_three_rows.deck_row()
        assert deck.title == "Eight Columns"
        assert deck.css == _CSS + " /* aggregated */"
        assert json.loads(deck.external_scripts_json) == _EXTERNAL_SCRIPTS
        assert json.loads(deck.head_meta_json) == _HEAD_META
        assert json.loads(deck.deck_spec_json) == _DECK_SPEC
        assert deck.slide_count == 7
        assert deck.html_content == "<html>knitted</html>"
        assert deck.scripts_content == "(function(){/*charts*/})();"

    def test_explicit_none_writes_null(self, deck_fixture):
        """`None` is a value, not an omission — it clears the column."""
        with _patched(deck_fixture._factory):
            write_deck_level_columns(deck_fixture.session_id, css=_CSS)
        assert deck_fixture.deck_row().css == _CSS

        with _patched(deck_fixture._factory):
            write_deck_level_columns(deck_fixture.session_id, css=None)
        assert deck_fixture.deck_row().css is None

    def test_html_content_is_optional(self, deck_fixture):
        """The pre-fan-out write has no knitted HTML; save_slide_deck demands it."""
        with _patched(deck_fixture._factory):
            write_deck_level_columns(
                deck_fixture.session_id,
                title="No HTML yet",
                css=_CSS,
                deck_spec=_DECK_SPEC,
            )

        deck = deck_fixture.deck_row()
        assert deck.title == "No HTML yet"
        assert deck.html_content == "", "html_content was altered by a write that omitted it"


# ---------------------------------------------------------------------------
# Session row, owner resolution, and the no-row case.
# ---------------------------------------------------------------------------


class TestSessionRowAndOwner:
    def test_title_also_updates_the_session_row(self, deck_with_three_rows):
        """The session list renders UserSession.title, not the deck's."""
        with _patched(deck_with_three_rows._factory):
            write_deck_level_columns(
                deck_with_three_rows.session_id, title="Renamed by the graph"
            )

        assert deck_with_three_rows.session_row().title == "Renamed by the graph"
        assert deck_with_three_rows.deck_row().title == "Renamed by the graph"

    def test_a_write_that_omits_title_leaves_the_session_row_alone(
        self, deck_with_three_rows
    ):
        """A title must be established first, or this test cannot fail.

        The fixture's UserSession.title starts NULL, so asserting
        "unchanged" against that start state passes even when an omitted
        title nulls the row.  Write a title, THEN omit it.
        """
        with _patched(deck_with_three_rows._factory):
            write_deck_level_columns(
                deck_with_three_rows.session_id, title="Established"
            )
        assert deck_with_three_rows.session_row().title == "Established"

        with _patched(deck_with_three_rows._factory):
            write_deck_level_columns(deck_with_three_rows.session_id, css=_CSS)

        assert deck_with_three_rows.session_row().title == "Established", (
            "the session row's title was clobbered by a write that omitted title"
        )

    def test_contributor_session_writes_to_the_owner(self, contributor_session):
        with _patched(contributor_session._factory):
            result = write_deck_level_columns(
                contributor_session.contributor_session_id,
                title="Written by a contributor",
                css=_CSS,
                deck_spec=_DECK_SPEC,
            )

        owner_deck = contributor_session.owner_deck_row()
        assert owner_deck.title == "Written by a contributor"
        assert owner_deck.css == _CSS
        assert json.loads(owner_deck.deck_spec_json) == _DECK_SPEC
        assert result["created"] is False, "wrote a second deck instead of the owner's"

        # And no separate deck row was created for the contributor session.
        db = contributor_session._factory()
        try:
            assert db.query(SessionSlideDeck).count() == 1
        finally:
            db.close()

    def test_creates_the_deck_row_when_none_exists(
        self, empty_session, _session_unit_engine
    ):
        """The pre-fan-out write is the FIRST deck write of a brand-new session.

        Without a create branch every graph turn on a new session raises.
        `empty_session` is a UserSession with no SessionSlideDeck; it shares the
        function-scoped `_session_unit_engine` so the same engine is patched in.
        """
        factory = _make_factory(_session_unit_engine)

        db = factory()
        try:
            owner_pk = (
                db.query(UserSession)
                .filter(UserSession.session_id == empty_session)
                .one()
                .id
            )
            assert (
                db.query(SessionSlideDeck)
                .filter(SessionSlideDeck.session_id == owner_pk)
                .count()
                == 0
            ), "fixture precondition: no deck row"
        finally:
            db.close()

        with _patched(factory):
            result = write_deck_level_columns(
                empty_session,
                title="Brand new deck",
                css=_CSS,
                external_scripts=_EXTERNAL_SCRIPTS,
                head_meta=_HEAD_META,
                deck_spec=_DECK_SPEC,
                modified_by="graph@example.com",
            )

        assert result["created"] is True
        assert result["version"] == 1

        db = factory()
        try:
            deck = (
                db.query(SessionSlideDeck)
                .filter(SessionSlideDeck.session_id == owner_pk)
                .one()
            )
            assert deck.title == "Brand new deck"
            assert deck.css == _CSS
            assert json.loads(deck.deck_spec_json) == _DECK_SPEC
            assert deck.version == 1
            assert deck.modified_by == "graph@example.com"
            assert deck.slide_count == 0, "slide_count NULL renders nothing in the list"
            assert deck.deck_json is None
            # Still no slide rows.
            assert (
                db.query(SessionSlide)
                .filter(SessionSlide.session_id == owner_pk)
                .count()
                == 0
            )
        finally:
            db.close()

    def test_unknown_session_raises(self, deck_fixture):
        with _patched(deck_fixture._factory):
            with pytest.raises(SessionNotFoundError):
                write_deck_level_columns("no-such-session", css=_CSS)


# ---------------------------------------------------------------------------
# read_deck_spec
# ---------------------------------------------------------------------------


class TestReadDeckSpec:
    def test_round_trips_a_written_spec(self, deck_with_three_rows):
        with _patched(deck_with_three_rows._factory):
            write_deck_level_columns(
                deck_with_three_rows.session_id, deck_spec=_DECK_SPEC
            )
            assert read_deck_spec(deck_with_three_rows.session_id) == _DECK_SPEC

    def test_returns_none_when_absent(self, deck_fixture):
        assert deck_fixture.deck_row().deck_spec_json is None
        with _patched(deck_fixture._factory):
            assert read_deck_spec(deck_fixture.session_id) is None

    def test_returns_none_for_an_unparseable_column(self, deck_with_three_rows):
        deck_with_three_rows.set_raw_deck_spec_json("{not json at all")
        with _patched(deck_with_three_rows._factory):
            assert read_deck_spec(deck_with_three_rows.session_id) is None

    def test_returns_none_for_a_non_object_column(self, deck_with_three_rows):
        """Parses fine, but the contract is `dict | None`."""
        deck_with_three_rows.set_raw_deck_spec_json(json.dumps([1, 2, 3]))
        with _patched(deck_with_three_rows._factory):
            assert read_deck_spec(deck_with_three_rows.session_id) is None

    def test_contributor_reads_the_owners_spec(self, contributor_session):
        with _patched(contributor_session._factory):
            write_deck_level_columns(
                contributor_session.contributor_session_id, deck_spec=_DECK_SPEC
            )
            assert (
                read_deck_spec(contributor_session.contributor_session_id) == _DECK_SPEC
            )
